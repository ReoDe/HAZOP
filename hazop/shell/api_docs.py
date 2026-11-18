"""새 웹 화면의 설계 문서 패널(완료 목록 2 A7, INTENT §2·§3.3·§3.10). Qt를 import하지 않는다.

- **읽기 `docs`**: `docs`(이 프로젝트의 설계 문서 목록: 상태·뽑힌 항목 수·도면에 이어진 확정·후보 수·읽을 수 없는 사유·지식그래프 반영 여부·
  판 대응), `docs/<자료 ID>`(문서 하나의 뽑힌 항목과 근거 위치). 읽기는 파일을 쓰지 않는다.
- **명령 `docs.*`**: `docs.add`(파일 고르기 창 → 고른 PDF마다 등록·지식 추출 작업), `docs.extract`(자료 ID로 추출 다시 하기),
  `docs.revision`(같은 문서의 새 판인지 묻는 물음에 답하기: replace 새 판으로 지정 · separate 다른 문서).
  웹은 경로를 보내지 않는다: 파일은 Python 쪽 대화상자(`engine.hooks["pick_doc"]`, 없으면 `pick_files`에서 PDF만)가 고른다.
- **프로젝트**: 명령을 받은 때(창을 열기 전)의 프로젝트 ID를 잡아 작업에 넘긴다. 창이 열린 사이 프로젝트가 바뀌어도 그 프로젝트에 등록한다.
- **판 대응**(hazop.kg.doc_revisions): 같은 문서 번호의 새 판이 옛 판을 대신하고 옛 판 지식은 지식그래프에서 빠진다. 번호를 못 읽거나 개정이 더
  낮으면 묻는다. 옛 판 지식에 걸린 사람 판단은 지우지 않고 지식그래프 조립이 '재확인 필요'로 알린다.
- **지식그래프 상태**: 추출 뒤 지식그래프 만들기가 실패하면 그 사유를 목록 머리에 보이고(이 실행 동안 기억), 문서마다 지금 지식그래프에 들어갔는지
  (inputs.documents)를 보인다. 낡은 지식그래프 기준으로 '이어짐'을 보이지 않으려는 것이다. 지식그래프 파일이 해시 검사에 걸리면 '없음'과 갈라 알린다.
- **채팅이 부를 실행 함수**: `list_documents`, `run_extraction`, `open_panel`.
- 등록·추출은 이전 화면 ①과 같은 엔진 함수다: `registry.register(…, "design_document")` → `data.extract_document`(규칙 기반, AI 없음).
  같은 파일을 다시 등록하면 엔진의 `reused`를 따르고, 이미 추출돼 있으면 다시 추출하지 않고 그렇다고 알린다.
"""

import json
import logging
import os
import threading
import time

from hazop import paths
from hazop.app import data
from hazop.kg import auto, doc_revisions
from hazop.register import registry

LOG = logging.getLogger("hazop.shell.api_docs")
TOPICS = ("docs",)
COUNT_LABELS = (("doc_chunk", "문서 조각"), ("setpoint", "설정치"), ("condition", "운전조건"), ("requirement", "요건"))
ITEM_TYPES = ("setpoint", "condition", "requirement")
ITEMS_SHOWN = 300
_LAST_BUILD = {}             # 프로젝트 ID -> {"error", "at"}: 이 실행에서 마지막 지식그래프 만들기가 실패했으면 그 사유
_LAST_LOCK = threading.Lock()


def _api():
    from hazop.shell import api
    return api


# ---------------------------------------------------------------- 자료 읽기

def _entries(pid):
    """이 프로젝트의 설계 문서 등록 행(최신 버전)."""
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


def _kg_state(pid):
    """(knowledge, kg, 상태 dict). 상태: none(아직 없음) · unreadable(해시·형식 검사에 걸림) · blocked(검증 막힘) · ok."""
    from hazop.kg import build
    root = os.path.join(paths.output_root("knowledge-graph"), paths.safe_name("kg-%s" % pid))
    if not os.path.isfile(os.path.join(root, build.POINTER_FILE)):
        return None, None, {"state": "none", "text": "지식그래프가 아직 없습니다. 문서를 추출하면 만들어집니다."}
    try:
        knowledge, kg = build.load_outputs(root)
    except (OSError, ValueError, KeyError) as exc:
        LOG.warning("지식그래프를 읽지 못함: %s", exc)
        return None, None, {"state": "unreadable", "text": "지식그래프 파일이 검사에 걸려 읽지 않았습니다(내용이 기록과 다름). 문서의 '추출 다시 하기'로 다시 만드세요."}
    v = (kg.get("validation") or {}).get("status")
    if v != "passed":
        return knowledge, kg, {"state": "blocked", "text": "지식그래프 검증이 막혀 있습니다(%s). 지식은 확인 전 자료로만 보세요." % (v or "상태 없음")}
    return knowledge, kg, {"state": "ok", "text": None}


def _linked(kg, ids):
    """문서 노드(ids)에서 도면 쪽 끝으로 가는 관계: (확정 관계 수, 후보 관계 수, 이어진 도면 노드 수). 기각은 세지 않는다."""
    confirmed = candidate = 0
    pid_ends = set()
    for l in (kg or {}).get("links") or []:
        st = l.get("link_status") or "confirmed"
        if st == "rejected":
            continue
        ends = l.get("ends") or {}
        a, b = ends.get("from") or {}, ends.get("to") or {}
        for mine, other in ((a, b), (b, a)):
            if mine.get("layer") == "knowledge" and mine.get("ref") in ids and other.get("layer") == "pid":
                if st == "confirmed" and (l.get("knowledge_status") or "confirmed") == "confirmed":
                    confirmed += 1
                else:
                    candidate += 1
                pid_ends.add((other.get("graph_id"), other.get("entity_id") or other.get("source_object_id")))
    return confirmed, candidate, len(pid_ends)


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


def _name(rec):
    return rec.get("title") or rec.get("original_name") or rec.get("material_id")


def _row(e, knowledge, kg, revisions, names):
    rec = e["record"]
    mid = rec.get("material_id")
    doc = _read_doc(e) if e.get("extracted") else None
    state = _state(rec, e.get("extracted"), doc)
    summary = (doc or {}).get("summary") or {}
    ids = {n["id"] for n in (doc or {}).get("nodes") or []}
    conf, cand, n_pid = _linked(kg, ids) if ids else (0, 0, 0)
    in_kg = any(d.get("material_id") == mid and d.get("registration_version") == rec.get("registration_version")
                and d.get("source_sha256") == (doc or {}).get("source_sha256")
                for d in ((knowledge or {}).get("inputs") or {}).get("documents") or [])
    rep = revisions["replaced"].get(mid)
    pending = revisions["pending"].get(mid) or []
    return {"material_id": mid, "name": rec.get("original_name"), "title": _name(rec),
            "version": rec.get("registration_version"), "state": state, "pages": (doc or {}).get("page_count"),
            "doc_number": (doc or {}).get("doc_number"), "revision": (doc or {}).get("revision"),
            "counts": {k: summary.get(k, 0) for k, _ in COUNT_LABELS},
            "unknowns": len(((doc or {}).get("validation") or {}).get("unknowns") or []),
            "linked_confirmed": conf, "linked_candidate": cand, "linked_nodes": n_pid, "reasons": _reasons(rec, doc),
            "in_kg": in_kg, "replaced_by": {"material_id": rep["by"], "title": names.get(rep["by"], rep["by"]), "reason": rep.get("reason")} if rep else None,
            "ask_revision": [{"material_id": m, "title": names.get(m, m)} for m in pending if m in names]}


def summary(engine, pid=None):
    pid = pid or engine.project_id()
    knowledge, kg, kg_status = _kg_state(pid)
    try:
        revisions = doc_revisions.load(pid)
    except (OSError, ValueError):
        revisions = {"replaced": {}, "pending": {}}
    entries = _entries(pid)
    names = {e["record"].get("material_id"): _name(e["record"]) for e in entries}
    rows = [_row(e, knowledge, kg, revisions, names) for e in entries]
    notes = [n for n in ((knowledge or {}).get("inputs") or {}).get("notes") or [] if "재확인" in n]
    with _LAST_LOCK:
        last = dict(_LAST_BUILD.get(pid) or {})
    return {"project_id": pid, "count_labels": [{"id": k, "label": v} for k, v in COUNT_LABELS], "docs": rows,
            "kg": dict(kg_status, build_error=last.get("error"), recheck=notes),
            "totals": {"docs": len(rows), "problems": sum(1 for r in rows if r["state"] in ("failed", "blocked")),
                       "asks": sum(1 for r in rows if r["ask_revision"])}}


def detail(engine, material_id):
    pid = engine.project_id()
    e = next((x for x in _entries(pid) if x["record"].get("material_id") == material_id), None)
    if e is None:
        return None
    s = summary(engine, pid)
    row = next(r for r in s["docs"] if r["material_id"] == material_id)
    doc = _read_doc(e) if e.get("extracted") else None
    _knowledge, kg, _st = _kg_state(pid)
    linked = set()
    for l in (kg or {}).get("links") or []:
        if l.get("link_status") == "rejected":
            continue
        ends = l.get("ends") or {}
        for side in ("from", "to"):
            x, y = ends.get(side) or {}, ends.get("to" if side == "from" else "from") or {}
            if x.get("layer") == "knowledge" and y.get("layer") == "pid":
                linked.add(x.get("ref"))
    items = []
    for n in (doc or {}).get("nodes") or []:
        if n.get("node_type") in ITEM_TYPES:
            src = n.get("source") or {}
            items.append({"id": n["id"], "type": n["node_type"], "item": n.get("item"), "value": n.get("value"), "unit": n.get("unit"),
                          "basis": n.get("pressure_basis"), "text": (n.get("text") or "")[:300], "locator": src.get("locator"),
                          "status": n.get("knowledge_status"), "linked": n["id"] in linked and row["in_kg"]})
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


# ---------------------------------------------------------------- 작업(작업 스레드)

def _cause(result):
    rec = result["record"]
    blockers = (rec.get("validation") or {}).get("blockers") or []
    reasons = [str(b.get("reason")) for b in blockers[:3] if b.get("reason")]
    return "; ".join(reasons) or next(iter(result.get("notes") or []), None) or result["outcome"]


def _note_build(pid, error):
    with _LAST_LOCK:
        if error:
            _LAST_BUILD[pid] = {"error": str(error)[:300], "at": time.time()}
        else:
            _LAST_BUILD.pop(pid, None)


def _rebuild(pid):
    """판 대응을 바꾼 뒤 지식그래프를 다시 만든다 -> 실패 사유 또는 None."""
    try:
        data.build_project_kg(pid)
    except (OSError, ValueError, KeyError) as exc:
        return str(exc)
    return None


def _revision_step(pid, material_id, doc, who):
    """새로 추출한 문서와 같은 문서의 옛 판이 있는지 본다 -> 결과 dict 또는 None. 대신하면 지식그래프를 다시 만든다."""
    with doc_revisions.LOCK:      # 여러 문서를 한꺼번에 등록하면 작업 스레드가 동시에 온다: 읽고 정하고 적는 것을 한 번에 하나씩
        if material_id in doc_revisions.load(pid)["replaced"]:
            return None               # 같이 등록된 다른 판이 먼저 이 문서를 대신했다(서로 대신하지 않게)
        current, _old = auto.split_documents(pid, data.doc_root())
        action, target, why = doc_revisions.decide(doc, current)
        if action == "replace":
            for old in target:
                doc_revisions.record_replace(pid, old["material_id"], material_id, "auto", why, who, registry_now())
        elif action == "ask":
            doc_revisions.record_pending(pid, material_id, [d["material_id"] for d in target])
    if action == "replace":
        return {"action": "replace", "old": ", ".join(d.get("title") or d["material_id"] for d in target), "reason": why, "kg_error": _rebuild(pid)}
    if action == "ask":
        return {"action": "ask", "candidates": [d.get("title") or d["material_id"] for d in target], "reason": why}
    return None


def registry_now():
    from hazop.study import nodes as study_nodes
    return study_nodes.now_utc()


def _done(engine, pid, material_id, outcome, out=None, skipped=None, revision=None):
    doc = (out or {}).get("document") or {}
    kg_error = (out or {}).get("kg_error") or (revision or {}).get("kg_error")
    if out is not None or revision is not None:
        _note_build(pid, kg_error)
    engine.changed("docs")
    engine.changed("kg")
    return {"outcome": outcome, "material_id": material_id, "skipped": skipped,
            "counts": {k: (doc.get("summary") or {}).get(k, 0) for k, _ in COUNT_LABELS},
            "blocked": [str(b.get("reason")) for b in (doc.get("validation") or {}).get("blockers") or []],
            "kg_error": kg_error, "kg_notes": [n for n in ((out or {}).get("kg") or {}).get("notes") or [] if "재확인" in n],
            "revision": {k: v for k, v in (revision or {}).items() if k != "kg_error"} or None}


def register_document(engine, pid, path, progress):
    """작업 스레드: 등록 → 지식 추출 → 지식그래프 → 판 대응. pid는 명령을 받은 때의 프로젝트(창을 열기 전에 잡은 값)."""
    progress("등록 중", 1, 2)
    result = registry.register(path, pid, "design_document", paths.store_root(), None, engine.reviewer())
    rec = result["record"]
    if rec.get("status") != "registered" or result["outcome"] in ("failed", "on_hold"):
        raise RuntimeError("등록하지 못함: %s" % _cause(result))
    if result["outcome"] == "reused":
        done = next((x for x in _entries(pid) if x["record"].get("material_id") == rec["material_id"]), None)
        if done is not None and done.get("extracted"):
            return _done(engine, pid, rec["material_id"], "reused",
                         skipped="이미 등록하고 추출한 같은 파일입니다. 다시 추출하려면 그 문서의 '추출 다시 하기'를 누르세요.")
    progress("지식 추출", 2, 2)
    out = data.extract_document(result["registration_file"])
    revision = _revision_step(pid, rec["material_id"], out["document"], engine.reviewer() or "자동")
    return _done(engine, pid, rec["material_id"], result["outcome"], out, revision=revision)


def extract_document(engine, pid, material_id, progress):
    e = next((x for x in _entries(pid) if x["record"].get("material_id") == material_id), None)
    if e is None:
        raise RuntimeError("등록한 문서를 찾지 못했습니다")
    if e["record"].get("status") != "registered":
        raise RuntimeError("등록이 끝나지 않은 문서라 추출할 수 없습니다")
    progress("지식 추출", 1, 1)
    out = data.extract_document(e["path"])
    return _done(engine, pid, material_id, "extracted", out)


def answer_revision(engine, pid, material_id, answer, old, progress):
    """사람의 답: replace(old를 이 문서가 대신) · separate(다른 문서). 답을 적고 지식그래프를 다시 만든다."""
    progress("판 대응 적용", 1, 1)
    if answer == "replace":
        doc_revisions.record_replace(pid, old, material_id, "human", "사람이 같은 문서의 새 판으로 지정", engine.reviewer(), registry_now())
    else:
        doc_revisions.record_separate(pid, material_id)
    return _done(engine, pid, material_id, answer, revision={"action": answer, "kg_error": _rebuild(pid)})


# ---------------------------------------------------------------- 명령

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
    """파일 고르기 창 → 고른 PDF마다 등록·추출 작업. {"jobs": [작업 ID]}. 취소하면 빈 목록. 프로젝트는 창을 열기 전에 잡는다."""
    api = _api()
    pid = engine.project_id()
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
    return {"project_id": pid,
            "jobs": [engine.start_job(os.path.basename(f), lambda progress, f=f: register_document(engine, pid, f, progress)) for f in checked]}


def run_extraction(engine, material_id):
    """채팅·패널이 부른다: 자료 ID의 지식 추출을 작업으로 돌린다 -> {"job": 작업 ID}."""
    api = _api()
    pid = engine.project_id()
    e = next((x for x in _entries(pid) if x["record"].get("material_id") == material_id), None)
    if e is None:
        raise api.CommandError("not_found", "등록한 문서를 찾지 못했습니다")
    label = e["record"].get("original_name") or material_id
    return {"job": engine.start_job("지식 추출 " + label, lambda progress: extract_document(engine, pid, material_id, progress))}


def _h_revision(engine, a):
    api = _api()
    pid = engine.project_id()
    names = {e["record"].get("material_id") for e in _entries(pid)}
    if a["material_id"] not in names or (a["answer"] == "replace" and a.get("old") not in names):
        raise api.CommandError("not_found", "등록한 문서를 찾지 못했습니다")
    if a["answer"] == "replace" and a["old"] == a["material_id"]:
        raise api.CommandError("bad_args", "같은 문서를 자기 옛 판으로 지정할 수 없습니다")
    return {"job": engine.start_job("문서 판 대응", lambda progress: answer_revision(engine, pid, a["material_id"], a["answer"], a.get("old"), progress))}


def open_panel(engine):
    engine.emit("docs.open", {})
    return {"opened": True}


def register(commands):
    api = _api()
    C, v_str, v_enum = api.Command, api.v_str, api.v_enum

    def put(name, spec_, handler, doc):
        key = "docs." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("add", {}, lambda engine, a: add_documents(engine),
        "설계 문서 PDF를 고르는 창을 열어 등록하고 지식 추출까지 돌린다(경로는 웹이 보내지 않는다)")
    put("extract", {"material_id": (v_str(1, 80), True)}, lambda engine, a: run_extraction(engine, a["material_id"]),
        "등록한 설계 문서의 지식 추출을 다시 한다")
    put("revision", {"material_id": (v_str(1, 80), True), "answer": (v_enum("replace", "separate"), True), "old": (v_str(1, 80), False)},
        _h_revision, "같은 문서의 새 판인지 묻는 물음에 답한다(replace: old를 이 문서가 대신, separate: 다른 문서)")
