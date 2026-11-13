"""새 웹 화면의 설계 문서 패널(완료 목록 2 A7, INTENT §2·§3.3·§3.10). Qt를 import하지 않는다.

- **읽기 `docs`**: `docs`(이 프로젝트의 설계 문서 목록: 상태·뽑힌 항목 수·지식그래프에서 도면에 이어진 수·읽을 수 없는 사유),
  `docs/<자료 ID>`(문서 하나의 뽑힌 항목: 설정치·운전조건·요건과 근거 위치). 읽기는 파일을 쓰지 않는다.
- **명령 `docs.*`**: `docs.add`(파일 고르기 창을 열어 고른 PDF를 등록하고 지식 추출까지 작업으로 돌림), `docs.extract`(자료 ID로 지식 추출 다시 하기).
  웹은 경로를 보내지 않는다: 파일은 Python 쪽 대화상자가 고르고(`engine.hooks["pick_doc"]`, 없으면 `pick_files`에서 PDF만) 웹에는 자료 ID와 작업 ID만 돌아간다.
- **채팅이 부를 실행 함수**: `list_documents`, `run_extraction`, `open_panel`. 채팅 연결(hazop/chat/actions.py)은 채팅 담당이 한다.
- 등록·추출은 이전 화면 ①이 부르는 엔진 함수를 그대로 부른다: `registry.register(…, "design_document")` → `data.extract_document`
  (규칙 기반 `hazop.kg.docextract`, AI 없음) → 프로젝트 지식그래프 다시 빌드. 뽑힌 항목의 상태는 모두 '자동 추출 · 사람 확인 전'이다.
- 같은 파일을 다시 등록하면 엔진이 `reused`로 돌려준다. 이미 추출돼 있으면 다시 추출하지 않고 알리기만 한다(추출 다시 하기는 `docs.extract`).
"""

import json
import logging
import os

from hazop import paths
from hazop.app import data
from hazop.kg import auto
from hazop.register import registry

LOG = logging.getLogger("hazop.shell.api_docs")
TOPICS = ("docs",)
KINDS = (("design_document", "설계 문서 (PDF)"),)      # 도면(P&ID)은 도면 패널로 등록한다
COUNT_LABELS = (("doc_chunk", "문서 조각"), ("setpoint", "설정치"), ("condition", "운전조건"), ("requirement", "요건"))
ITEM_TYPES = ("setpoint", "condition", "requirement")
ITEMS_SHOWN = 300
KG_LINK_KINDS_NOTE = "도면 구성요소와 이어진 수는 지식그래프의 관계(언급·적용·설정치)로 센 값이다"


def _api():
    from hazop.shell import api
    return api


# ---------------------------------------------------------------- 자료 읽기

def _entries(engine):
    """이 프로젝트의 설계 문서 등록 행(최신 버전)."""
    pid = engine.project_id()
    return [e for e in data.list_registrations()
            if e["record"].get("material_type") == "design_document" and e["record"].get("project_id") == pid]


def _read_doc(e):
    name = e.get("extract_name")
    if not name:
        return None
    p = os.path.join(data.doc_root(), name, auto.DOC_FILE)
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _kg(engine):
    from hazop.shell import api_kg
    return api_kg._load_kg(engine.project_id())[0]


def _linked(kg, ids):
    """문서 노드(ids)와 도면 쪽 끝이 있는 관계의 수와 이어진 도면 노드 수."""
    links, pid_ends = 0, set()
    for l in (kg or {}).get("links") or []:
        if l.get("link_status") == "rejected":
            continue
        ends = l.get("ends") or {}
        a, b = ends.get("from") or {}, ends.get("to") or {}
        for mine, other in ((a, b), (b, a)):
            if mine.get("layer") == "knowledge" and mine.get("ref") in ids and other.get("layer") == "pid":
                links += 1
                pid_ends.add((other.get("graph_id"), other.get("entity_id") or other.get("source_object_id")))
    return links, len(pid_ends)


def _reasons(rec, doc):
    out = []
    if rec.get("status") != "registered":
        out += [str(b.get("reason")) for b in (rec.get("validation") or {}).get("blockers") or [] if b.get("reason")]
    if doc:
        out += [str(b.get("reason")) for b in (doc.get("validation") or {}).get("blockers") or [] if b.get("reason")]
    return out[:5]


def _state(rec, extracted, doc):
    if rec.get("status") != "registered":
        return "failed"
    if not extracted or doc is None:
        return "pending"
    return "blocked" if (doc.get("validation") or {}).get("status") == "blocked" else "ok"


def _row(e, kg):
    rec = e["record"]
    doc = _read_doc(e) if e.get("extracted") else None
    state = _state(rec, e.get("extracted"), doc)
    summary = (doc or {}).get("summary") or {}
    ids = {n["id"] for n in (doc or {}).get("nodes") or []}
    n_links, n_pid = _linked(kg, ids) if ids else (0, 0)
    tags = {t for m in (doc or {}).get("tag_mentions") or [] for t in m.get("tags") or []}
    return {"material_id": rec.get("material_id"), "name": rec.get("original_name"), "title": rec.get("title"),
            "version": rec.get("registration_version"), "state": state, "pages": (doc or {}).get("page_count"),
            "counts": {k: summary.get(k, 0) for k, _ in COUNT_LABELS}, "unknowns": len((doc or {}).get("validation", {}).get("unknowns") or []),
            "linked_links": n_links, "linked_nodes": n_pid, "tags": len(tags), "reasons": _reasons(rec, doc),
            "extractor": (doc or {}).get("extractor")}


def summary(engine):
    kg = _kg(engine)
    rows = [_row(e, kg) for e in _entries(engine)]
    return {"project_id": engine.project_id(), "kinds": [{"id": k, "label": v} for k, v in KINDS],
            "count_labels": [{"id": k, "label": v} for k, v in COUNT_LABELS], "docs": rows, "has_kg": kg is not None,
            "totals": {"docs": len(rows), "ok": sum(1 for r in rows if r["state"] == "ok"),
                       "problems": sum(1 for r in rows if r["state"] in ("failed", "blocked")),
                       "items": sum(sum(r["counts"][k] for k in ITEM_TYPES) for r in rows)},
            "note": KG_LINK_KINDS_NOTE}


def detail(engine, material_id):
    e = next((x for x in _entries(engine) if x["record"].get("material_id") == material_id), None)
    if e is None:
        return None
    doc = _read_doc(e) if e.get("extracted") else None
    kg = _kg(engine)
    row = _row(e, kg)
    linked = set()
    for l in (kg or {}).get("links") or []:
        ends = l.get("ends") or {}
        for side in ("from", "to"):
            x, y = ends.get(side) or {}, ends.get("to" if side == "from" else "from") or {}
            if x.get("layer") == "knowledge" and y.get("layer") == "pid" and l.get("link_status") != "rejected":
                linked.add(x.get("ref"))
    items = []
    for n in (doc or {}).get("nodes") or []:
        if n.get("node_type") in ITEM_TYPES:
            src = n.get("source") or {}
            items.append({"id": n["id"], "type": n["node_type"], "item": n.get("item"), "value": n.get("value"), "unit": n.get("unit"),
                          "basis": n.get("pressure_basis"), "text": (n.get("text") or "")[:300], "locator": src.get("locator"),
                          "status": n.get("knowledge_status"), "linked": n["id"] in linked})
    return {"doc": row, "items": items[:ITEMS_SHOWN], "items_total": len(items)}


def list_documents(engine):
    """채팅이 부른다: 이 프로젝트의 설계 문서 목록(요약 행)."""
    return summary(engine)["docs"]


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'docs'. 없는 자료는 None(404)."""
    api = _api()
    if len(parts) == 1:
        return api._json(summary(engine))
    if len(parts) == 2:
        d = detail(engine, parts[1])
        return api._json(d) if d is not None else None
    return None


# ---------------------------------------------------------------- 명령

def _cause(result):
    rec = result["record"]
    blockers = (rec.get("validation") or {}).get("blockers") or []
    reasons = [str(b.get("reason")) for b in blockers[:3] if b.get("reason")]
    return "; ".join(reasons) or next(iter(result.get("notes") or []), None) or result["outcome"]


def _doc_result(engine, material_id, outcome, out=None, skipped=None):
    engine.changed("docs")
    engine.changed("kg")
    doc = (out or {}).get("document") or {}
    res = {"outcome": outcome, "material_id": material_id, "skipped": skipped,
           "counts": {k: (doc.get("summary") or {}).get(k, 0) for k, _ in COUNT_LABELS},
           "blocked": [str(b.get("reason")) for b in (doc.get("validation") or {}).get("blockers") or []],
           "kg_error": (out or {}).get("kg_error")}
    return res


def register_document(engine, path, progress):
    """작업 스레드: 등록 → 지식 추출 → 지식그래프. 등록이 실패·보류면 이유를 적어 오류로 올린다(완료로 표시하지 않는다)."""
    progress("등록 중", 1, 2)
    result = registry.register(path, engine.project_id(), "design_document", paths.store_root(), None, engine.reviewer())
    rec = result["record"]
    if rec.get("status") != "registered" or result["outcome"] in ("failed", "on_hold"):
        raise RuntimeError("등록하지 못함: %s" % _cause(result))
    if result["outcome"] == "reused":
        done = next((x for x in data.list_registrations() if x["record"].get("material_id") == rec["material_id"]
                     and x["record"].get("project_id") == rec.get("project_id")), None)
        if done is not None and done.get("extracted"):
            engine.changed("docs")
            return _doc_result(engine, rec["material_id"], "reused", skipped="이미 등록하고 추출한 같은 문서입니다. 다시 추출하려면 '추출 다시 하기'를 누르세요.")
    progress("지식 추출", 2, 2)
    out = data.extract_document(result["registration_file"])
    return _doc_result(engine, rec["material_id"], result["outcome"], out)


def extract_document(engine, material_id, progress):
    e = next((x for x in _entries(engine) if x["record"].get("material_id") == material_id), None)
    if e is None:
        raise RuntimeError("등록한 문서를 찾지 못했습니다")
    if e["record"].get("status") != "registered":
        raise RuntimeError("등록이 끝나지 않은 문서라 추출할 수 없습니다")
    progress("지식 추출", 1, 1)
    out = data.extract_document(e["path"])
    return _doc_result(engine, material_id, "extracted", out)


def _pick(engine):
    api = _api()
    hook = engine.hooks.get("pick_doc")
    fallback = False
    if hook is None:
        hook, fallback = engine.hooks.get("pick_files"), True
    if hook is None:
        raise api.CommandError("failed", "파일 고르기를 쓸 수 없음")
    files = list(hook() or [])
    if fallback:
        files = [f for f in files if str(f).lower().endswith(".pdf")]
    return files


def add_documents(engine):
    """파일 고르기 창 → 고른 PDF마다 등록·추출 작업. {"jobs": [작업 ID]}. 취소하면 빈 목록."""
    api = _api()
    files = _pick(engine)[:api.MAX_FILES]
    if not files:
        return {"jobs": []}
    checked = []
    for p in files:
        if not isinstance(p, str) or not p or len(p) > api.MAX_PATH_CHARS or "\x00" in p:
            raise api.CommandError("bad_args", "등록할 수 없는 파일 경로")
        full = os.path.abspath(p)
        if not full.lower().endswith(".pdf") or not os.path.isfile(full):
            raise api.CommandError("bad_args", "설계 문서는 PDF만 등록합니다: %s" % os.path.basename(full))
        checked.append(full)
    return {"jobs": [engine.start_job(os.path.basename(f), lambda progress, f=f: register_document(engine, f, progress)) for f in checked]}


def run_extraction(engine, material_id):
    """채팅·패널이 부른다: 자료 ID의 지식 추출을 작업으로 돌린다 -> {"job": 작업 ID}."""
    api = _api()
    e = next((x for x in _entries(engine) if x["record"].get("material_id") == material_id), None)
    if e is None:
        raise api.CommandError("not_found", "등록한 문서를 찾지 못했습니다")
    label = e["record"].get("original_name") or material_id
    return {"job": engine.start_job("지식 추출 " + label, lambda progress: extract_document(engine, material_id, progress))}


def open_panel(engine):
    engine.emit("docs.open", {})
    return {"opened": True}


def _h_add(engine, a):
    return add_documents(engine)


def _h_extract(engine, a):
    return run_extraction(engine, a["material_id"])


def register(commands):
    api = _api()
    C, v_str, v_enum = api.Command, api.v_str, api.v_enum

    def put(name, spec_, handler, doc):
        key = "docs." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("add", {"kind": (v_enum(*[k for k, _ in KINDS]), True)}, _h_add,
        "설계 문서 PDF를 고르는 창을 열어 등록하고 지식 추출까지 돌린다(경로는 웹이 보내지 않는다)")
    put("extract", {"material_id": (v_str(1, 80), True)}, _h_extract, "등록한 설계 문서의 지식 추출을 다시 한다")
