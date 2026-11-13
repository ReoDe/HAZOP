"""도면 쪽 확정: 어떤 쪽(추출 결과 하나)을 사람이 확정할 수 있는지 판정하고, 견줌·확정 기록을 저장한다.

근거: docs/design/app-shell-web.md §10.4(미확인의 정의)·§10.5(원본에 남은 것)·§10.6(기본 보기)·§10.7(확정 조건),
docs/specs/dexpi-exchange.md §6.1(내보내기는 확정된 쪽만). 명령 표는
docs/units/2026-11-13-drawing-knowledge/evidence/sheet-commands.md.

- check(extraction, ai_doc, ops): 사람 수정을 반영한 추출 결과에서 미확인 목록 전체·위치 없음·원본에 남은 것을 센다(순수 함수).
  정리된 보기(hazop/shell/clean_items.py)와 DEXPI 내보내기가 같은 기준을 쓰도록 세는 규칙을 여기 하나에 둔다.
- sheet_confirmation(name): 세 파일(추출 결과, 사람 수정 기록, AI 후보 기록)을 한 번씩 읽어 check의 답에 지문과 견줌·확정
  기록을 붙이고 state(open·ready·confirmed)를 정한다. 파일을 쓰지 않는다.
- execute(name, command, args, by=…, fingerprint=…, rev=…): 상태 읽기·견줌·확정·확정 해제. 기록은 세 파일 밖
  <작업 루트>/data/sheet-confirmations/<이름>.json에 둔다(확정을 써도 지문이 바뀌지 않게).
- default_view(read_method, state): 처음 열 때 원본·정리 가운데 무엇을 보일지.

세 파일 가운데 하나라도 바뀌면(다시 추출, 사람 수정, 후보 수락·거절) 견줌·확정이 함께 풀린다. 풀린 기록은 지우지 않고
상태 읽기의 released에 무엇이 바뀌었는지와 함께 보이며, 다음에 쓰는 명령이 기록의 log에 'released'로 남긴다.
"""

import hashlib
import json
import os

from hazop import paths, store_io
from hazop.extract import corrections
from hazop.study.nodes import now_utc

KIND = "hazop_sheet_confirmation"
SCHEMA_VERSION = "0.1"
KNOWN_FORMATS = ("drawio", "dexpi", "pdf_vector", "raster")
CLEAN_FIRST = ("drawio", "dexpi")              # 처음부터 정리된 보기
CLEAN_WHEN_CONFIRMED = ("pdf_vector", "raster")  # 확정된 쪽만 정리된 보기
TAGGED = ("equipment", "valve", "instrument")   # 태그를 갖는 종류(없으면 '태그 없음')
# 추출의 미확인 기록(validation.unknowns) 말고 이 판정이 직접 정하는 사유. 그 밖의 사유는 unknowns의 check 코드 그대로다
REASONS = ("unknown_symbol", "missing_tag", "open_end", "unresolved_connector", "ai_candidate", "unplaced")
# 사람 수정의 '이대로 확인'(corrections의 confirm 연산, items[].check)으로 끝낼 수 있는 사유. AI 후보는 수락·거절로만 끝낸다
ACKNOWLEDGEABLE = ("unknown_symbol", "missing_tag", "open_end", "unresolved_connector", "unplaced")
FILES = ("extraction", "edits", "ai_review")
COMPARE_MODES = ("side_by_side", "overlay", "dexpi_list")
COMMANDS = ("status", "compare", "confirm", "unconfirm")
# 거절 사유 코드(구간·결과 명령과 같은 갈래)
CODES = ("unknown_command", "bad_actor", "stale", "conflict", "unreadable", "rule", "io")


# ---------------------------------------------------------------- 읽은 방법과 기본 보기

def source_format(extraction):
    """읽은 방법. 모르는 값·빈 값은 'unknown'(가장 조심스러운 쪽)."""
    fmt = str((extraction.get("source") or {}).get("format") or "").strip().lower()
    if fmt.startswith("pdf"):
        return "pdf_vector"
    return fmt if fmt in KNOWN_FORMATS else "unknown"


def default_view(read_method, state=None):
    """처음 열 때의 보기 'clean' 또는 'original'(§10.6 표). drawio·DEXPI는 정리, PDF·래스터는 확정된 쪽만 정리,
    모르는 읽은 방법이나 빈 값은 원본."""
    fmt = read_method if read_method in KNOWN_FORMATS else "unknown"
    if fmt in CLEAN_FIRST or (fmt in CLEAN_WHEN_CONFIRMED and state == "confirmed"):
        return "clean"
    return "original"


# ---------------------------------------------------------------- 세기(순수 함수)

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pair(p):
    if isinstance(p, (list, tuple)) and len(p) == 2 and None not in (_num(p[0]), _num(p[1])):
        return [_num(p[0]), _num(p[1])]
    if isinstance(p, dict) and None not in (_num(p.get("x")), _num(p.get("y"))):
        return [_num(p["x"]), _num(p["y"])]
    return None


def _node_box(n):
    """노드 자리 [x0, y0, x1, y1]. geometry, 없으면 글자 자리(label_location.bbox [x, y, w, h]). 없으면 None."""
    g = n.get("geometry") or {}
    x, y, w, h = (_num(g.get(k)) for k in ("x", "y", "width", "height"))
    if None not in (x, y, w, h):
        return [x, y, x + w, y + h]
    b = (n.get("label_location") or {}).get("bbox")
    if isinstance(b, (list, tuple)) and len(b) == 4 and None not in [_num(v) for v in b]:
        return [b[0], b[1], b[0] + b[2], b[1] + b[3]]
    return None


def _line_points(r):
    """관계 선의 점(끝점과 꺾이는 점). 두 점 미만이면 위치 없음."""
    ends = [_pair(ep.get("point")) for ep in r.get("endpoints") or [] if isinstance(ep, dict)]
    way = [_pair(w) for w in r.get("waypoints") or []]
    return [p for p in ends + way if p is not None]


def _box_of(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _acknowledged(extraction, ops):
    """사람이 '이대로 확인'한 사유 {(대상 local_id, 사유)}: 적용된 confirm 연산의 items[].check가 ACKNOWLEDGEABLE인 것.
    (validation.unknowns의 확인은 corrections.apply가 이미 목록에서 지웠다.)"""
    applied = set((extraction.get("corrections") or {}).get("applied") or [])
    moved = {(m.get("op_id"), m.get("from")): m.get("to")
             for m in (extraction.get("corrections") or {}).get("retargeted") or [] if isinstance(m, dict)}
    local = {}
    for key in ("nodes", "relations", "unresolved_connectors"):
        for obj in extraction.get(key) or []:
            if isinstance(obj, dict) and obj.get("source_object_id") is not None:
                local[obj["source_object_id"]] = obj.get("local_id")
    out = set()
    for op in ops or ():
        if not isinstance(op, dict) or op.get("op") != "confirm" or op.get("op_id") not in applied:
            continue
        target = moved.get((op["op_id"], op.get("target")), op.get("target"))
        lid = local.get(target)
        for item in (op.get("value") or {}).get("items") or []:
            if isinstance(item, dict) and item.get("check") in ACKNOWLEDGEABLE and lid:
                out.add((lid, item["check"]))
    return out


def ai_pending(ai_doc):
    """수락 전 AI 후보(accepted·rejected가 아닌 것) 목록."""
    return [c for c in (ai_doc or {}).get("candidates") or []
            if isinstance(c, dict) and c.get("status") not in ("accepted", "rejected")]


def leftovers(extraction):
    """원본에 남은 것(§10.5) {paths, texts, total, source}. 엔진이 세지 못하는 쪽이면 None(그 쪽은 확정할 수 없음).
    - 추출 결과에 leftovers({"paths": [...], "texts": [...]})가 있으면 그것(PDF 추출이 이 필드를 더한 뒤).
    - drawio: 분류하지 못한 셀(unclassified). 작성자가 일부러 뺀 셀(drawing.ignored_objects)은 세지 않는다(정리된 보기와 같음).
    - DEXPI: 원본 그림이 없고, 대응표에 없는 클래스도 미분류 노드로 들어와 미확인으로 세므로 남은 것은 없다(0).
    - PDF(leftovers 없음)·래스터·모르는 형식: None."""
    lo = extraction.get("leftovers")
    if isinstance(lo, dict):
        p, t = len(lo.get("paths") or []), len(lo.get("texts") or [])
        return {"paths": p, "texts": t, "total": p + t, "source": "extraction"}
    fmt = source_format(extraction)
    if fmt == "drawio":
        n = sum(1 for c in extraction.get("unclassified") or [] if isinstance(c, dict))
        return {"paths": n, "texts": 0, "total": n, "source": "drawio_unclassified"}
    if fmt == "dexpi":
        return {"paths": 0, "texts": 0, "total": 0, "source": "dexpi_no_drawing"}
    return None


def check(extraction, ai_doc=None, ops=()):
    """사람 수정을 반영한 추출 결과(corrections.apply의 결과) → {read_method, unconfirmed, unplaced, counts, leftovers}.

    unconfirmed: [{id(대상 local_id 또는 None = 쪽 전체), reason(사유 코드), detail(추출의 미확인 문구 또는 None)}]를 도면 안
    순서(위→아래, 왼→오른, 위치 없는 것과 쪽 전체는 끝)로. 같은 대상·같은 사유는 한 번, 다른 사유는 따로 센다(§10.4).
    사유: validation.unknowns의 check 코드 전체, 끝이 미확정인 연결(unresolved_connector), 분류 안 된 기호(unknown_symbol),
    태그 없음(missing_tag), 열린 끝(open_end), 수락 전 AI 후보(ai_candidate), 위치 없음(unplaced).
    위치가 없어도 다른 사유는 함께 센다. ops(저장된 사람 수정 연산)의 '이대로 확인'은 그 사유를 뺀다.
    counts: 사유별 수, total, 그리고 unknowns(추출의 미확인 기록 수)·unplaced·open_ends(열린 끝 + 끝 미확정 연결)·
    ai_pending(수락 전 후보 수)."""
    acked = _acknowledged(extraction, ops)
    pending = ai_pending(ai_doc)
    boxes, rows, unplaced = {}, [], []

    def add(lid, reason, detail=None):
        if (lid, reason) not in acked:
            rows.append({"id": lid, "reason": reason, "detail": detail})

    for n in extraction.get("nodes") or []:
        if not isinstance(n, dict) or not isinstance(n.get("local_id"), str):
            continue
        lid = n["local_id"]
        box = _node_box(n)
        if box is None:
            unplaced.append({"id": lid, "kind": "node", "tag": n.get("tag") or None})
            add(lid, "unplaced")
        else:
            boxes[lid] = box
        if n.get("classification") not in (None, "classified") or not n.get("kind"):
            add(lid, "unknown_symbol")
        elif n.get("category") in TAGGED and not str(n.get("tag") or "").strip():
            add(lid, "missing_tag")
    for r in extraction.get("relations") or []:
        if not isinstance(r, dict) or not isinstance(r.get("local_id"), str):
            continue
        lid = r["local_id"]
        pts = _line_points(r)
        if len(pts) < 2:
            unplaced.append({"id": lid, "kind": "relation", "tag": r.get("line_no") or None})
            add(lid, "unplaced")
        else:
            boxes[lid] = _box_of(pts)
        if any(isinstance(ep, dict) and ep.get("status") != "connected" for ep in r.get("endpoints") or []):
            add(lid, "open_end")
    for c in extraction.get("unresolved_connectors") or []:
        if isinstance(c, dict) and isinstance(c.get("local_id"), str):
            pts = _line_points(c)
            if pts:
                boxes.setdefault(c["local_id"], _box_of(pts))
            add(c["local_id"], "unresolved_connector")
    unknowns = [u for u in (extraction.get("validation") or {}).get("unknowns") or [] if isinstance(u, dict) and u.get("check")]
    for u in unknowns:
        add(u.get("target") if isinstance(u.get("target"), str) else None, str(u["check"]), u.get("reason"))
    for c in pending:
        add(c.get("target") if isinstance(c.get("target"), str) else None, "ai_candidate", c.get("cand_id"))

    seen, out = set(), []
    for u in rows:
        key = (u["id"], u["reason"])
        if key not in seen:
            seen.add(key)
            out.append(u)

    def order(u):
        b = boxes.get(u["id"]) if u["id"] else None
        if b is None:
            return (1, 0, 0, str(u["id"]), u["reason"])
        return (0, round(b[1]), round(b[0]), u["id"], u["reason"])
    out.sort(key=order)
    counts = {r: 0 for r in REASONS}
    for u in out:
        counts[u["reason"]] = counts.get(u["reason"], 0) + 1
    counts.update(total=len(out), unknowns=len(unknowns), unplaced=len(unplaced),
                  open_ends=counts["open_end"] + counts["unresolved_connector"], ai_pending=len(pending))
    return {"read_method": source_format(extraction), "unconfirmed": out, "unplaced": unplaced, "counts": counts,
            "leftovers": leftovers(extraction)}


# ---------------------------------------------------------------- 세 파일과 기록

def extraction_path(name):
    return os.path.join(paths.output_root("extract"), name, "extraction.json")


def file_paths(name):
    """지문에 드는 세 파일 {extraction, edits, ai_review}."""
    from hazop.extract import ai_review
    return {"extraction": extraction_path(name), "edits": corrections.store_path(name),
            "ai_review": ai_review.store_path(name)}


def store_path(name):
    return paths.folder("sheet-confirmations", paths.safe_name(name) + ".json")


def _combined(files):
    text = "|".join("%s=%s" % (k, files[k] or "-") for k in FILES)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_sources(name):
    """세 파일을 한 번씩 읽어 (고친 추출 결과, AI 후보 문서, 저장된 수정 연산, 파일별 지문). 판정과 지문이 같은 바이트에서
    나온다. 추출 결과가 없으면 FileNotFoundError, 깨졌으면 ValueError."""
    from hazop.extract import ai_review
    p = file_paths(name)
    raw, files = {}, {}
    for key in FILES:
        raw[key], files[key] = store_io.read_bytes(p[key])
    if raw["extraction"] is None:
        raise FileNotFoundError("추출 결과가 없음: %s" % p["extraction"])
    original = json.loads(raw["extraction"].decode("utf-8-sig"))
    edits = json.loads(raw["edits"].decode("utf-8")) if raw["edits"] is not None else None
    ai_doc = json.loads(raw["ai_review"].decode("utf-8")) if raw["ai_review"] is not None else None
    for doc, kind, what in ((edits, corrections.KIND, "도면 수정 기록"), (ai_doc, ai_review.KIND, "AI 검토 후보")):
        if doc is not None and (not isinstance(doc, dict) or doc.get("kind") != kind):
            raise ValueError("%s 파일이 아님" % what)
    ops = (edits or {}).get("ops") or []
    return corrections.apply(original, ops), ai_doc, ops, files


def _read_record(name):
    """(기록 문서, 지문). 없으면 (빈 기록, None)."""
    path = store_path(name)
    data, fp = store_io.read_bytes(path)
    if data is None:
        return {"kind": KIND, "schema_version": SCHEMA_VERSION, "extraction_name": name, "rev": 0,
                "compared": None, "confirmed": None, "log": []}, None
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError("쪽 확정 기록 파일이 아님: %s" % path)
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("이 앱이 모르는 판(%s)의 쪽 확정 기록이라 읽지 않음: %s" % (doc.get("schema_version"), path))
    return doc, fp


def _changed(record_files, files):
    return [k for k in FILES if (record_files or {}).get(k) != files.get(k)]


def _status(name, record, sources):
    ex, ai_doc, ops, files = sources
    out = check(ex, ai_doc, ops)
    fp = _combined(files)
    ready = not out["unconfirmed"] and not out["unplaced"] and out["leftovers"] is not None
    valid, released = {}, []
    for what in ("compared", "confirmed"):
        rec = record.get(what)
        if not rec:
            valid[what] = None
        elif rec.get("fingerprint") == fp:
            valid[what] = rec
        else:
            valid[what] = None
            released.append(dict(rec, what=what, changed=_changed(rec.get("files"), files)))
    state = "open" if not ready else ("confirmed" if valid["compared"] and valid["confirmed"] else "ready")
    out.update(name=name, state=state, fingerprint=fp, files=files, compared=valid["compared"],
               confirmed=valid["confirmed"] if state == "confirmed" else None, released=released,
               rev=record.get("rev", 0), default_view=default_view(out["read_method"], state))
    return out


def sheet_confirmation(name):
    """쪽 이름(추출 폴더 이름) → check의 답 + {name, state, fingerprint, files, compared, confirmed, released, rev,
    default_view}. state: open(미확인·위치 없음이 있거나 원본에 남은 것을 세지 못함), ready(그 셋은 되었으나 원본과 견줌·
    사람의 확정이 아직), confirmed. compared·confirmed는 지금 지문과 같은 기록만, released는 세 파일이 바뀌어 풀린 기록
    (changed: 바뀐 파일). 파일을 쓰지 않는다. 추출 결과가 없으면 FileNotFoundError, 파일이 깨졌으면 ValueError."""
    return _status(name, _read_record(name)[0], _read_sources(name))


# ---------------------------------------------------------------- 명령

def _refused(command, rows, status=None, rev=None):
    return {"ok": False, "command": command, "changed": False, "rev": rev, "status": status,
            "refused": [{"target": str(t), "code": c, "reason": str(r)} for t, c, r in rows]}


def _ok(command, changed, status):
    return {"ok": True, "command": command, "changed": changed, "rev": status["rev"], "status": status, "refused": []}


def _left(st):
    """확정을 막는 것들 [(target, code, reason)]."""
    rows = []
    c = st["counts"]
    if st["unconfirmed"]:
        kinds = ", ".join("%s %d" % (k, v) for k, v in sorted(
            {u["reason"]: sum(1 for x in st["unconfirmed"] if x["reason"] == u["reason"]) for u in st["unconfirmed"]}.items()))
        rows.append(("unconfirmed", "rule", "미확인 %d곳이 남음(%s)" % (len(st["unconfirmed"]), kinds)))
    if st["unplaced"]:
        rows.append(("unplaced", "rule", "위치 없는 구성요소 %d개(위치를 주거나 '도면에 없음'으로 지울 것)" % c["unplaced"]))
    if st["leftovers"] is None:
        rows.append(("leftovers", "rule", "원본에 남은 것을 엔진이 세지 않는 읽은 방법(%s)이라 확정할 수 없음"
                     % st["read_method"]))
    return rows


def execute(name, command, args=None, by=None, fingerprint=None, rev=None):
    """쪽 확정 명령. 돌려주는 값 {ok, command, changed, rev, status(sheet_confirmation의 답), refused[{target, code, reason}]}.
    - status: 읽기만.
    - compare(args.mode: side_by_side·overlay·dexpi_list): '원본과 견줌'을 남긴다. 미확인 0·위치 없음 0·남은 것을 셀 때만.
    - confirm: 확정. 위 셋과 지금 지문의 견줌 기록이 있어야 한다. 원본에 남은 수(leftovers_seen)를 함께 남긴다.
    - unconfirm(args.reason 선택): 견줌·확정을 함께 푼다.
    쓰는 명령은 by(사람 이름)가 있어야 하고 at은 엔진이 채운다. fingerprint(화면이 본 세 파일 지문)·rev(화면이 본 기록 판)가
    None이 아니면 지금 값과 같아야 한다(다르면 stale). 바뀐 것이 없으면 쓰지 않고 changed False."""
    if command not in COMMANDS:
        return _refused(command, [("command", "unknown_command", "모르는 명령(%s 가운데 하나)" % ", ".join(COMMANDS))])
    a = dict(args or {})
    who = (by or "").strip()
    if command != "status" and not who:
        return _refused(command, [("by", "bad_actor", "사람 이름이 있어야 함(확정 기록에 남음)")])
    try:
        record, record_fp = _read_record(name)
        st = _status(name, record, _read_sources(name))
    except (OSError, ValueError) as exc:
        return _refused(command, [("sheet", "unreadable", "쪽 자료를 읽을 수 없음(%s)" % exc)])
    if command == "status":
        return _ok(command, False, st)
    if fingerprint is not None and fingerprint != st["fingerprint"]:
        return _refused(command, [("fingerprint", "stale", "본 뒤 도면 자료(추출 결과·사람 수정·AI 후보)가 바뀜. 다시 보고 할 것")],
                        st, st["rev"])
    if rev is not None and rev != st["rev"]:
        return _refused(command, [("rev", "stale", "본 뒤 확정 기록이 바뀜(본 판 %s, 지금 %s)" % (rev, st["rev"]))], st, st["rev"])
    at = now_utc()
    entry = {"at": at, "by": who, "action": command, "fingerprint": st["fingerprint"]}
    if command == "unconfirm":
        if not record.get("compared") and not record.get("confirmed"):
            return _ok(command, False, st)
        if (a.get("reason") or "").strip():
            entry["reason"] = a["reason"].strip()
        new = dict(record, compared=None, confirmed=None)
    else:
        rows = _left(st)
        if command == "confirm" and not rows and not st["compared"]:
            rows.append(("compared", "rule", "원본과 견준 기록이 없음(견주기 화면에서 확인한 뒤 확정)"))
        if rows:
            return _refused(command, rows, st, st["rev"])
        if command == "compare":
            mode = a.get("mode") or "side_by_side"
            if mode not in COMPARE_MODES:
                return _refused(command, [("mode", "rule", "견준 방식은 %s 가운데 하나" % ", ".join(COMPARE_MODES))],
                                st, st["rev"])
            if st["compared"] and st["compared"].get("mode") == mode:
                return _ok(command, False, st)
            mark = {"by": who, "at": at, "fingerprint": st["fingerprint"], "files": st["files"], "mode": mode,
                    "leftovers_seen": st["leftovers"]["total"]}
            new = dict(record, compared=mark)
            entry["mode"] = mode
        else:
            if st["state"] == "confirmed":
                return _ok(command, False, st)
            mark = {"by": who, "at": at, "fingerprint": st["fingerprint"], "files": st["files"],
                    "leftovers_seen": st["leftovers"]["total"], "compared_at": st["compared"]["at"]}
            new = dict(record, confirmed=mark)
        entry["leftovers_seen"] = st["leftovers"]["total"]
    log = list(record.get("log") or [])
    for old in st["released"]:  # 세 파일이 바뀌어 풀린 기록을 남긴다(지우지 않고 log로 옮김)
        log.append({"at": at, "by": None, "action": "released", "what": old["what"], "changed": old["changed"],
                    "record": {k: v for k, v in old.items() if k not in ("what", "changed")}})
        if new.get(old["what"]) is record.get(old["what"]):
            new[old["what"]] = None
    log.append(entry)
    new.update(rev=record.get("rev", 0) + 1, log=log)
    try:
        store_io.write_json(store_path(name), new, expect=record_fp)
    except store_io.Conflict as exc:
        return _refused(command, [("file", "conflict", "읽은 뒤 확정 기록이 바뀌어 저장하지 않음(%s)" % exc)], st, st["rev"])
    except OSError as exc:
        return _refused(command, [("file", "io", "확정 기록을 쓰지 못함(%s)" % exc)], st, st["rev"])
    return _ok(command, True, _status(name, new, _read_sources(name)))
