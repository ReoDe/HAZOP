"""표제란 값(도면 번호·개정·제목)의 후보와 사람 확정(INTENT §3.1, 완료 목록 2 A3, 화면 규격 HZ-DSN-05 '표제란 후보 확정').

표제란에서 읽은 값은 등록정보의 `auto_candidates`에 후보로만 있고, 사람이 확정한 값만 등록정보의 `drawing_number`·`design_revision`·
`title`에 들어간다(hazop.register.registry). 이 모듈은 그 둘을 화면·채팅이 쓸 꼴로 보이고, 확정·확정 취소를 엔진 한 곳에서 한다.
Qt를 import하지 않는다. 명령 표는 docs/units/2026-11-13-drawing-knowledge/evidence/titleblock-commands.md.

- view(project_id): 자료(도면)마다 세 항목의 확정값·후보·근거(읽은 자리)·누가 언제 확정했는가, 상태, 판 표시(ver).
- confirm(project_id, material_id, fields, by, ver): 후보 그대로 또는 고친 값으로 확정. unconfirm(..., field_names): 확정 취소.
- execute(project_id, command, args, by, ver): 채팅이 부를 실행 함수(view·confirm·unconfirm).

확정하면 등록정보에 새 등록 버전이 생기고(이력 confirm_metadata·unconfirm_metadata), 이미 추출한 도면이면 새 버전으로 다시 추출한다.
추출 결과 폴더 이름에는 등록 버전이 들어가므로(`<프로젝트>__<자료>-r<버전>-p<쪽>`) 다시 추출하기 **전에** 지금 쪽의 사람 수정 기록과
AI 후보 기록을 새 이름으로 옮겨 쓰고(그래야 새 그래프가 사람 수정을 담는다, 앞 파일은 지우지 않음), 앞 버전의 graph.json은
graph.superseded.json으로 비켜 둔다(한 도면이 프로젝트 그래프에 두 번 들어가지 않게). 다시 추출이 실패하면 비켜 둔 그래프를 되돌리고,
그 자료는 '다시 읽기 필요'로 보인다. 같은 확정을 다시 하면 새 버전 없이 다시 읽기만 한다. 쪽 확정 기록은 옮기지 않는다(추출 결과가
바뀌어 어차피 풀리고, 사람이 바뀐 도면을 다시 보고 확정해야 한다).

'지금 쪽'은 쪽마다 추출 결과가 있는 가장 새 등록 버전이다(다시 추출이 실패해 최신 버전에는 추출이 없을 수 있다).

도면 번호는 그래프 ID(`graph-<도면 번호>`)이고 검토구간·분석 결과의 열쇠다(파일 이름은 paths.safe_name, Windows에서는 대소문자 무시).
- 그래프 ID가 바뀌는 확정·취소는 앞 ID나 새 ID에 구간·분석 결과가 있으면 막는다(ID를 옮기는 길이 아직 없음).
- 새 ID의 파일 열쇠가 다른 자료의 그래프 ID(확정 번호 또는 확정 전 쪽 이름에서 온 것)와 같으면: 글자가 다르면(대소문자·특수 문자만
  다름) 막고, 글자가 같고 형식도 같으면 막고, 형식이 다르면(drawio·PDF·DEXPI) 막지 않고 충돌을 알린다(hazop.graph.sources의 길).
- 여러 쪽 자료(PDF 여러 쪽)는 등록정보의 번호 하나를 모든 쪽이 나눠 써서 쪽마다 그래프 ID가 겹치므로 확정하지 않는다(쪽별 확정은 후속).
"""

import json
import os
import re
import unicodedata

from hazop import paths, store_io
from hazop.register import registry

FIELDS = (("drawing_number", "도면 번호"), ("design_revision", "개정"), ("title", "제목"))
LABELS = dict(FIELDS)
COMMANDS = ("view", "confirm", "unconfirm")
CODES = ("unknown_command", "bad_actor", "bad_args", "stale", "not_found", "rule", "conflict", "io")
MAX_VALUE = 200
SUPERSEDED = "graph.superseded.json"


class Refused(Exception):
    def __init__(self, target, code, reason):
        Exception.__init__(self, reason)
        self.row = {"target": target, "code": code, "reason": reason}


# ---------------------------------------------------------------- 읽기

def _store_root(store_root):
    return store_root or paths.store_root()


def _materials(project_id, store_root):
    store = registry.Store(_store_root(store_root), project_id)
    if not os.path.isfile(store.index_path):
        return []
    return [m["material_id"] for m in store.load_index(project_id)["materials"] if m.get("versions")]


def _out_name(record, page, version=None):
    from hazop.app import data
    rec = record if version is None else dict(record, registration_version=version)
    return data.script_module("extract_drawio").registered_out_name(rec, page)


def _page_count(record):
    return sum(len(d.get("page_ids") or []) for d in record.get("documents") or []) or 1


def _graph_id_of(extraction):
    """build_graph와 같은 규칙의 그래프 ID."""
    drawing = extraction.get("drawing") or {}
    return "graph-%s" % (drawing.get("drawing_number") or (extraction.get("source_context") or {}).get("page_name") or "drawing")


def _sheets(record):
    """쪽마다 추출 결과가 있는 가장 새 등록 버전 [{page, version, name, graph_id, page_name}]. 추출한 적 없는 쪽은 뺀다."""
    out = []
    for page in range(_page_count(record)):
        for version in range(record["registration_version"], 0, -1):
            name = _out_name(record, page, version)
            try:
                with open(os.path.join(paths.output_root("extract"), name, "extraction.json"), encoding="utf-8") as fh:
                    ex = json.load(fh)
            except (OSError, ValueError):
                continue
            out.append({"page": page, "version": version, "name": name, "graph_id": _graph_id_of(ex),
                        "page_name": (ex.get("source_context") or {}).get("page_name")})
            break
    return out


def _key(graph_id):
    return paths.safe_name(graph_id).casefold()


def _ref_places(project_id):
    """그래프 ID(도면 번호)를 열쇠로 쓰는 프로젝트 기록 [(이름, 파일 목록)]. 새 화면은 구간·분석 결과를 프로젝트 그래프
    (study-nodes/<프로젝트>/project-<프로젝트>.json)에 두고 구성원을 '<그래프 ID>/<엔터티 ID>'로 적으므로, 도면 파일 이름이 아니라
    파일 안의 참조를 센다. 도면 하나짜리 옛 파일(graph-<번호>.json)도 같은 폴더라 함께 센다."""
    from hazop.graph import project
    from hazop.ie import store as ie_store
    from hazop.kg import expect
    from hazop.study import nodes
    pid = paths.safe_name(project_id)

    def files(folder):
        out = []
        for d, _dirs, names in os.walk(folder):
            out += [os.path.join(d, n) for n in sorted(names) if n.endswith(".json")]
        return out
    return [("구간", files(os.path.join(nodes.store_dir(), pid))),
            ("분석 결과", files(paths.folder("analysis-results", pid)) + files(paths.folder("analysis-results-test", pid))),
            ("초기사건", [ie_store.store_path(project_id)]),
            ("잠재 후보 판단", [expect.store_path(project_id)]),
            ("도면 연결 지정", [project.manual_path(project_id)]),
            ("지식그래프 판단", files(paths.folder("knowledge-graph", paths.safe_name(project_id, "project"))))]


def _references(project_id, graph_id):
    """그래프 ID를 가리키는 참조 수 {이름: 수}(0인 것은 뺀다). 참조 꼴은 "<그래프 ID>"·"<그래프 ID>/…"·"<그래프 ID>#…"."""
    if not graph_id:
        return {}
    pat = re.compile(r'"%s(?=["/#])' % re.escape(graph_id))
    out = {}
    for name, files in _ref_places(project_id):
        n = 0
        for f in files:
            try:
                with open(f, encoding="utf-8") as fh:
                    n += len(pat.findall(fh.read()))
            except (OSError, UnicodeDecodeError):
                continue
        if n:
            out[name] = out.get(name, 0) + n
    return out


def _describe(refs):
    return "·".join("%s %d곳" % (k, v) for k, v in refs.items())


def _evidence(cand):
    if not cand:
        return None
    src = cand.get("source")
    where = {"title_block": "표제란", "dexpi_meta": "DEXPI 도면 정보"}.get(src, src or "?")
    page = cand.get("page_id")
    cell = cand.get("value_object_id")
    text = where + (" · %s" % page if page else "") + (" · 칸 %s" % cell if cell else "")
    return {"source": src, "page_id": page, "key_object_id": cand.get("key_object_id"), "value_object_id": cell, "text": text}


def _who(record, field):
    """그 항목을 지금 값으로 확정한 마지막 기록 {by, at, reason} 또는 None."""
    for h in reversed(record.get("history") or []):
        if h.get("field") == field and h.get("action") in ("confirm_metadata", "unconfirm_metadata"):
            if h.get("action") == "confirm_metadata" and h.get("after") == record.get(field):
                return {"by": h.get("by"), "at": h.get("at"), "reason": h.get("reason")}
            return None
    return None


def row(project_id, material_id, store_root=None):
    """자료 하나의 표제란 상태. 없으면 None."""
    record, path = registry.latest(project_id, material_id, _store_root(store_root))
    if record is None:
        return None
    cands = record.get("auto_candidates") or {}
    fields = []
    for field, label in FIELDS:
        cand = cands.get(field)
        who = _who(record, field) if record.get(field) is not None else None
        fields.append({"field": field, "label": label, "value": record.get(field),
                       "candidate": str(cand["value"]) if cand and cand.get("value") is not None else None,
                       "evidence": _evidence(cand), "confirmed_by": (who or {}).get("by"), "confirmed_at": (who or {}).get("at")})
    done = sum(1 for f in fields if f["value"] is not None)
    sheets = _sheets(record) if record.get("status") == "registered" else []
    return {"material_id": material_id, "project_id": project_id, "version": record.get("registration_version"),
            "name": record.get("original_name"), "format": record.get("format"), "material_type": record.get("material_type"),
            "status": record.get("status"), "pages": _page_count(record),
            "state": "confirmed" if done == len(FIELDS) else ("partial" if done else "unconfirmed"),
            "fields": fields, "ver": store_io.fingerprint(path), "sheets": sheets,
            "needs_reextract": any(s["version"] != record.get("registration_version") for s in sheets),
            "review_data": [_describe(r) for r in [_merged_refs(project_id, sheets)] if r],
            "multi_page": _page_count(record) > 1}


def _merged_refs(project_id, sheets):
    out = {}
    for gid in sorted({s["graph_id"] for s in sheets if s.get("graph_id")}):
        for k, v in _references(project_id, gid).items():
            out[k] = out.get(k, 0) + v
    return out


def view(project_id, store_root=None, material_type="P&ID"):
    """프로젝트의 도면 자료마다 row(...)."""
    out = []
    for mid in _materials(project_id, store_root):
        r = row(project_id, mid, store_root)
        if r is not None and (material_type is None or (r["material_type"] or "P&ID") == material_type):
            out.append(r)
    return out


# ---------------------------------------------------------------- 확정·취소

def _check_values(fields):
    if not isinstance(fields, dict) or not fields:
        raise Refused("fields", "bad_args", "확정할 항목이 없음")
    out = {}
    for k, v in fields.items():
        if k not in LABELS:
            raise Refused("fields", "bad_args", "알 수 없는 항목: %s" % k)
        if not isinstance(v, str):
            raise Refused(k, "bad_args", "%s 값은 글이어야 함" % LABELS[k])
        if any(unicodedata.category(ch) in ("Cc", "Cf") and ch not in "\t\n\r" for ch in v):
            raise Refused(k, "bad_args", "%s 값에 보이지 않는 제어 문자가 있음" % LABELS[k])
        text = " ".join(v.split())
        if not text or len(text) > MAX_VALUE:
            raise Refused(k, "bad_args", "%s 값은 비어 있지 않은 %d자 이하 글이어야 함" % (LABELS[k], MAX_VALUE))
        out[k] = text
    return out


def _gid(number, sheet):
    return "graph-%s" % (number or sheet.get("page_name") or "drawing")


def _others(project_id, material_id, store_root):
    """다른 자료가 쓰는 그래프 ID [(그래프 ID, 형식, 자료 이름, 자료 ID)]: 추출한 쪽의 그래프 ID, 추출 전이면 확정 번호."""
    out = []
    for mid in _materials(project_id, store_root):
        if mid == material_id:
            continue
        other, _p = registry.latest(project_id, mid, _store_root(store_root))
        if not other or other.get("status") != "registered" or (other.get("material_type") or "P&ID") != "P&ID":
            continue
        gids = [s["graph_id"] for s in _sheets(other)]
        if not gids and other.get("drawing_number"):
            gids = ["graph-%s" % other["drawing_number"]]
        out += [(g, other.get("format"), other.get("original_name"), mid) for g in gids]
    return out


def _guard_number(project_id, record, sheets, new_number, store_root):
    """도면 번호가 new_number(None이면 확정 취소)가 될 때 끊기거나 겹치는 것을 막는다."""
    if record.get("drawing_number") == new_number:
        return
    if _page_count(record) > 1:
        raise Refused("drawing_number", "rule", "여러 쪽 자료(%d쪽)는 쪽마다 도면 번호가 달라 자료 하나에 번호를 확정하지 않음"
                      "(쪽별 확정은 아직 없음)" % _page_count(record))
    old_number = record.get("drawing_number")
    if old_number is not None:
        from hazop.graph import sources
        if old_number in sources.load_choices(project_id):
            raise Refused("drawing_number", "rule", "도면 번호 %s에 사람이 고른 원본 형식 선택이 있어 번호를 바꾸지 않음(같은 번호의 다른 형식 "
                          "원본에 걸린 선택이라 새 번호로 옮길 수 없음)" % old_number)
    targets = [(s.get("graph_id"), _gid(new_number, s)) for s in sheets]
    if not sheets and new_number is not None:
        targets = [(None, "graph-%s" % new_number)]
    for old, new in targets:
        if old is not None and old != new:
            for gid, what in ((old, "이 도면"), (new, "새 번호의 도면")):
                refs = _references(project_id, gid)
                if refs:
                    raise Refused("drawing_number", "rule", "%s(%s)의 구성요소를 %s이 가리키고 있어 번호를 바꾸면 끊기거나 섞임. 그래프 "
                                  "ID를 옮기는 길이 아직 없어 막음: 번호를 바꾸려면 그 기록을 먼저 정리해야 함" % (what, gid, _describe(refs)))
        for gid, fmt, name, mid in _others(project_id, record["material_id"], store_root):
            if _key(gid) != _key(new):
                continue
            if gid != new:
                raise Refused("drawing_number", "conflict", "다른 자료 %s(%s)의 도면 %s와 글자만 달라 같은 파일을 쓰게 됨: 같은 도면이면 "
                              "그 번호를 그대로 쓰고, 다른 도면이면 다른 번호를 쓸 것" % (name, mid, gid[len("graph-"):]))
            if fmt == record.get("format"):
                raise Refused("drawing_number", "conflict", "같은 형식(%s)의 다른 자료 %s(%s)가 이미 도면 %s를 씀: 그래프 ID가 겹침"
                              % (fmt, name, mid, gid[len("graph-"):]))


def _union(first, second, key):
    """first 목록에 second에서 key가 겹치지 않는 항목을 더한 것(first가 이긴다)."""
    seen = {x.get(key) for x in first if isinstance(x, dict)}
    return list(first) + [x for x in second if isinstance(x, dict) and x.get(key) not in seen]


def _merge(kind, src, dst):
    """옮겨 쓸 기록(src, 지금 쪽 = 사람이 마지막으로 고친 곳)과 새 이름에 이미 있는 기록(dst)을 연산·후보 단위로 합친다. 지금 쪽이 이긴다."""
    out = dict(src)
    if kind == "edits":
        removed = {i for e in src.get("log") or [] if isinstance(e, dict) for i in e.get("removed") or []}
        extra = [o for o in dst.get("ops") or [] if isinstance(o, dict) and o.get("op_id") not in removed]
        out["ops"] = _union(src.get("ops") or [], extra, "op_id")   # 지금 쪽에서 지운 연산은 되살리지 않는다
        out["log"] = list(dst.get("log") or []) + [e for e in src.get("log") or [] if e not in (dst.get("log") or [])]
    else:
        out["candidates"] = _union(src.get("candidates") or [], dst.get("candidates") or [], "cand_id")
        out["runs"] = list(dst.get("runs") or []) + [r for r in src.get("runs") or [] if r not in (dst.get("runs") or [])]
    return out


def _carry(sheets, new_record):
    """지금 쪽 이름의 사람 수정 기록·AI 후보 기록을 새 등록 버전 이름으로 옮겨 쓴다(앞 파일은 지우지 않음). 새 이름에 이미 기록이 있으면
    (앞서 다시 추출이 실패한 시도가 옮겨 둔 것 등) 덮지 않고 연산·후보 단위로 합친다(지금 쪽이 이긴다).
    반환 ([{from, to, edits, ai_review}], 이번에 새로 만든 파일 경로 목록)."""
    from hazop.extract import ai_review, corrections
    out, created = [], []
    for s in sheets:
        new_name = _out_name(new_record, s["page"])
        if new_name == s["name"]:
            continue
        moved = {"from": s["name"], "to": new_name, "edits": False, "ai_review": False}
        for key, path_of in (("edits", corrections.store_path), ("ai_review", ai_review.store_path)):
            data, _fp = store_io.read_bytes(path_of(s["name"]))
            if data is None:
                continue
            doc = json.loads(data.decode("utf-8"))
            if not isinstance(doc, dict):
                continue
            target = path_of(new_name)
            have, have_fp = store_io.read_bytes(target)
            if have is not None:
                old = json.loads(have.decode("utf-8"))
                doc = _merge(key, doc, old if isinstance(old, dict) else {})
            doc["extraction_name"] = new_name
            doc["carried_from"] = list(dict.fromkeys(list(doc.get("carried_from") or []) + [s["name"]]))
            store_io.write_json(target, doc, expect=have_fp, sort_keys=False)
            if have is None:
                created.append(target)
            moved[key] = True
        out.append(moved)
    return out, created


def _set_aside(sheets, new_record):
    """새 이름이 될 쪽의 앞 graph.json을 graph.superseded.json으로 비켜 둔다. 반환 [(앞 경로, 비켜 둔 경로)]."""
    moved = []
    for s in sheets:
        if _out_name(new_record, s["page"]) == s["name"]:
            continue
        folder = os.path.join(paths.output_root("graph"), s["name"])
        src, dst = os.path.join(folder, "graph.json"), os.path.join(folder, SUPERSEDED)
        if os.path.isfile(src):
            os.replace(src, dst)
            moved.append((src, dst))
    return moved


def _put_back(moved):
    for src, dst in moved:
        if os.path.isfile(dst) and not os.path.exists(src):
            os.replace(dst, src)


def _confirmed_sheets(sheets):
    from hazop.extract import confirmation
    out = []
    for s in sheets:
        try:
            if confirmation.sheet_confirmation(s["name"])["state"] == "confirmed":
                out.append(s["name"])
        except (OSError, ValueError):
            pass
    return out


def _reextract(record, registration_path, sheets, extract, progress):
    """sheets를 record(새 등록 버전)로 옮겨 다시 추출한다: 기록 옮겨 쓰기 → 앞 그래프 비켜 두기 → 추출. 실패하면 그래프를 되돌린다."""
    carried, created = _carry(sheets, record)
    moved = _set_aside(sheets, record)
    progress("다시 추출·그래프", 2, 2)
    try:
        extract(registration_path)
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 앞 그래프와 옮겨 쓴 기록을 되돌리고 사유를 알린다
        _put_back(moved)
        for path in created:  # 이번 시도가 새로 만든 사본만 지운다: 지금 쪽(앞 이름)의 기록 하나만 진실로 남게
            try:
                os.remove(path)
            except OSError:
                pass
        raise Refused("extraction", "io", "확정은 저장했으나 도면을 다시 읽지 못함(%s). 같은 확정을 다시 하면 다시 읽음"
                      % (" ".join(str(exc).split())[:160] or type(exc).__name__))
    return carried


def _apply(project_id, material_id, by, ver, store_root, change, extract, progress, dry=False):
    """change(record) -> (새 버전을 만드는 함수 또는 None, 새 도면 번호). 공통: 판 대조, 번호 검사, 새 버전, 옮겨 쓰기, 다시 추출.
    dry면 검사까지만 하고 아무것도 쓰지 않는다(화면이 작업을 시작하기 전에 거절 사유를 바로 보이려고)."""
    by = (by or "").strip()
    if not by:
        raise Refused("by", "bad_actor", "확정한 사람 이름이 있어야 함(설정의 검토자 이름)")
    record, path = registry.latest(project_id, material_id, _store_root(store_root))
    if record is None:
        raise Refused("material_id", "not_found", "등록된 자료가 아님: %s" % material_id)
    if ver is not None and ver != store_io.fingerprint(path):
        raise Refused("ver", "stale", "본 뒤 등록정보가 바뀜(다시 보고 확정할 것)")
    if record.get("status") != "registered":
        raise Refused("material_id", "rule", "등록이 끝나지 않은 자료라 확정할 수 없음(status %s)" % record.get("status"))
    sheets = _sheets(record)
    behind = [s for s in sheets if s["version"] != record["registration_version"]]
    make, new_number = change(record)
    if make is None and not behind:
        return {"ok": True, "changed": False, "row": row(project_id, material_id, store_root), "refused": []}
    if make is not None:
        _guard_number(project_id, record, sheets, new_number, store_root)
    if dry:
        return {"ok": True, "changed": True, "dry": True, "re_extract": bool(sheets), "refused": []}
    released = _confirmed_sheets(sheets)
    if make is None:  # 앞서 다시 추출이 실패한 자료: 새 버전 없이 다시 읽기만
        carried = _reextract(record, path, behind, extract, progress)
        return {"ok": True, "changed": True, "version": record["registration_version"], "re_extracted": True,
                "carried": carried, "released_sheet_confirmations": released, "conflicts": [], "notes": ["다시 읽기만 함"],
                "row": row(project_id, material_id, store_root), "refused": []}
    progress("표제란 확정 저장", 1, 2)
    try:
        res = make()
    except (OSError, ValueError) as exc:
        raise Refused("registration", "io", "등록정보를 쓰지 못함(%s)" % exc)
    rec = res["record"]
    if res["outcome"] != "new_version" or rec.get("status") != "registered":
        cause = "; ".join(str(b.get("reason")) for b in (rec.get("validation") or {}).get("blockers") or []) \
            or "; ".join(res.get("notes") or []) or res["outcome"]
        raise Refused("registration", "io", "새 등록 버전을 만들지 못함: %s" % cause)
    carried = _reextract(rec, res["registration_file"], sheets, extract, progress) if sheets else []
    return {"ok": True, "changed": True, "version": rec["registration_version"], "re_extracted": bool(sheets),
            "carried": carried, "released_sheet_confirmations": released, "conflicts": res.get("conflicts") or [],
            "notes": res.get("notes") or [], "row": row(project_id, material_id, store_root), "refused": []}


def _default_extract(registration_path):
    from hazop.app import data
    return data.extract_and_graph(registration_path)


def _quiet(*_a):
    return None


def confirm(project_id, material_id, fields, by, ver=None, reason=None, store_root=None, extract=None, progress=None, now=None,
            dry=False):
    """fields {항목: 값}을 사람 확정값으로 저장한다(후보 그대로든 고친 값이든 사람이 고른 값). ver(본 등록정보의 판, row의 ver)가
    None이 아니면 지금 판과 같아야 한다. 반환 {ok, changed, version, re_extracted, carried, released_sheet_confirmations, conflicts,
    notes, row, refused}. 막히면 ok False와 refused [{target, code, reason}]. 바뀐 값이 없으면 changed False(새 버전을 만들지 않음).
    앞서 다시 추출이 실패한 자료면 값이 같아도 다시 읽는다. dry면 검사만 한다({ok, changed, dry, re_extract})."""
    try:
        values = _check_values(fields)

        def change(record):
            diff = {k: v for k, v in values.items() if record.get(k) != v}
            if not diff:
                return None, record.get("drawing_number")
            meta = dict(diff, by=by.strip(), reason=(reason or "").strip() or "표제란 확정")
            src = registry.Store(_store_root(store_root), project_id).abs_ref(record["storage_ref"])
            return (lambda: registry.register(src, project_id, record.get("material_type") or "P&ID", _store_root(store_root),
                                              meta, by.strip(), now)), diff.get("drawing_number", record.get("drawing_number"))
        return _apply(project_id, material_id, by, ver, store_root, change, extract or _default_extract, progress or _quiet, dry)
    except Refused as exc:
        return {"ok": False, "changed": False, "refused": [exc.row]}


def unconfirm(project_id, material_id, field_names, by, ver=None, reason=None, store_root=None, extract=None, progress=None,
              now=None, dry=False):
    """확정을 취소해 그 항목을 다시 후보만 있는 상태로 둔다. field_names가 None이면 세 항목 모두, 빈 목록은 거절.
    돌려주는 꼴은 confirm과 같다."""
    try:
        if field_names is not None and not field_names:
            raise Refused("fields", "bad_args", "취소할 항목이 없음")
        names = list(field_names) if field_names is not None else [f for f, _ in FIELDS]
        bad = [f for f in names if f not in LABELS]
        if bad:
            raise Refused("fields", "bad_args", "알 수 없는 항목: %s" % ", ".join(map(str, bad)))

        def change(record):
            if all(record.get(f) is None for f in names):
                return None, record.get("drawing_number")
            return (lambda: registry.clear_metadata(project_id, material_id, names, (by or "").strip(), reason,
                                                    _store_root(store_root), now)), \
                (None if "drawing_number" in names else record.get("drawing_number"))
        return _apply(project_id, material_id, by, ver, store_root, change, extract or _default_extract, progress or _quiet, dry)
    except Refused as exc:
        return {"ok": False, "changed": False, "refused": [exc.row]}


def execute(project_id, command, args=None, by=None, ver=None, store_root=None, extract=None, progress=None):
    """채팅이 부를 실행 함수. view(args.material_id 선택) · confirm(args.material_id, args.fields, args.reason) ·
    unconfirm(args.material_id, args.fields 목록 선택, args.reason). 쓰는 명령은 사람 확인을 거친 뒤에만 부르고, ver(view가 준 판)가
    없으면 거절한다(채팅 규격의 확인 상자)."""
    a = dict(args or {})
    if command not in COMMANDS:
        return {"ok": False, "changed": False, "refused": [{"target": "command", "code": "unknown_command",
                                                           "reason": "모르는 명령(%s 가운데 하나)" % ", ".join(COMMANDS)}]}
    if command == "view":
        if a.get("material_id"):
            r = row(project_id, a["material_id"], store_root)
            if r is None:
                return {"ok": False, "changed": False, "refused": [{"target": "material_id", "code": "not_found",
                                                                   "reason": "등록된 자료가 아님"}]}
            return {"ok": True, "changed": False, "rows": [r], "refused": []}
        return {"ok": True, "changed": False, "rows": view(project_id, store_root), "refused": []}
    if not isinstance(ver, str) or not ver:   # 채팅은 본 판(row의 ver)을 꼭 넘긴다: 그 사이 다른 창이 바꾼 것을 덮지 않게
        return {"ok": False, "changed": False, "refused": [{"target": "ver", "code": "bad_args",
                                                           "reason": "본 등록정보의 판(ver)이 있어야 함(view의 ver)"}]}
    if command == "confirm":
        return confirm(project_id, a.get("material_id"), a.get("fields"), by, ver, a.get("reason"), store_root, extract, progress)
    return unconfirm(project_id, a.get("material_id"), a.get("fields"), by, ver, a.get("reason"), store_root, extract, progress)
