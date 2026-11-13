"""새 웹 화면 3단계 ⑥ 초기사건의 엔진 쪽(앱 틀 규격 §2.1·§2.3 ⑥). Qt를 import하지 않는다.

- **읽기** `ie`(요약: 머리 수치·그룹 목록·묶이지 않은 후보·완전성 대조·품질 경고·판 지문), `ie/group/<IEG>`(그룹 상세: 정의·소속 후보·표제·최종상태·기본사건·
  확정 조건). 읽기는 인계 묶음(hazop.ie.bundle.build_bundle)을 메모리에서 만들어 그 값을 그대로 보인다 — 화면과 내보내는 묶음이 같은 계산을 쓴다. 파일을 쓰지 않는다.
- **명령** `ie.suggest`(규칙 초안 만들기), `ie.confirm`·`ie.reopen`(그룹 확정·확정 풀기). 쓰기는 읽은 지문(ver)을 들고 가고 거절되면 아무것도 쓰지 않는다.
  확정자는 설정의 검토자 이름이다(웹 인자 아님). 인계 묶음 내보내기는 `results.export_ie`(저장 위치는 창이 묻는다).
- 아직 이 길에 없는 것(이전 화면 ⑥에 남음): 그룹·표제·최종상태 고치기, 나누기, 지우기, 후보 옮기기, 범주 대조 판정(set_coverage).
"""

import logging

from hazop.ie import bundle, model
from hazop.ie import store as ie_store
from hazop.study import nodes
from hazop.study import results as res

LOG = logging.getLogger("hazop.shell.api_ie")


def _api():
    from hazop.shell import api
    return api


def _results():
    from hazop.shell import api_results
    return api_results


def _context(engine):
    """(pg, 구간 집합, 결과 문서, ie 문서, ie 지문) 또는 (None, 이유)."""
    R = _results()
    pg = R._pg(engine, strict=False)
    if pg is None:
        return None, "프로젝트 그래프가 없습니다. 도면을 먼저 추출하세요."
    ns, legacy = R._node_set(pg)
    if legacy:
        return None, "옛 판 구간 파일입니다. 구간 패널에서 새 판으로 바꾸세요."
    if not [n for n in ns["nodes"] if nodes.is_active(n)]:
        return None, "확정한 구간이 아직 없습니다. 구간을 확정하고 분석한 뒤 초기사건을 봅니다."
    try:
        doc, _fp = R._load(ns)
    except (OSError, ValueError) as exc:
        return None, "분석 결과 파일을 읽을 수 없습니다(%s)." % str(exc)[:120]
    try:
        ie_doc, ie_fp = ie_store.load(ns.get("project_id"))
    except ie_store.Unreadable as exc:
        return None, "초기사건 파일을 읽을 수 없습니다: %s" % "; ".join(exc.problems[:2])[:200]
    return (pg, ns, doc, ie_doc, ie_fp), None


def _view_doc(ie_doc, doc, ns):
    """읽기용: 승인 항목과 맞춘 문서(sync는 사본을 돌려줄 뿐 저장하지 않는다)."""
    return model.sync(ie_doc, doc, node_set=ns)


def _ver(fp):
    return fp or "none"


def summary(engine):
    ctx, why = _context(engine)
    if ctx is None:
        return {"available": False, "reason": why}
    pg, ns, doc, ie_doc, ie_fp = ctx
    ie_doc = _view_doc(ie_doc, doc, ns)
    b = bundle.build_bundle(doc, ns, pg, ie_doc, nodes.now_utc())
    grouped = {m for g in b["groups"] for m in g["members"]}
    unassigned = [c for c in b["candidates"] if c["candidate_id"] not in grouped]
    status_count = {}
    for g in b["groups"]:
        status_count[g["status"]] = status_count.get(g["status"], 0) + 1
    gaps = [c for c in b["completeness"] if c["status"] == "gap"]
    return {"available": True, "ver": _ver(ie_fp), "project_id": b["project_id"],
            "kpi": {"candidates": len(b["candidates"]), "unassigned": len(unassigned), "groups": len(b["groups"]),
                    "confirmed": status_count.get("confirmed", 0), "draft": status_count.get("draft", 0),
                    "warnings": len(b["warnings"]), "gaps": len(gaps), "categories": len(b["completeness"])},
            "groups": [_group_row(g) for g in b["groups"]], "unassigned": unassigned, "completeness": b["completeness"],
            "warnings": b["warnings"], "warning_summary": b["warning_summary"], "created_at": b["created_at"]}


def _group_row(g):
    return {"group_id": g["group_id"], "name": g["name"], "status": g["status"], "origin": g["origin"], "member_count": g["member_count"],
            "held_member_count": g["held_member_count"], "categories": g["categories"], "problems": g["problems"], "confirmed_by": g["confirmed_by"]}


def group_view(engine, gid):
    ctx, _why = _context(engine)
    if ctx is None:
        return None
    pg, ns, doc, ie_doc, ie_fp = ctx
    ie_doc = _view_doc(ie_doc, doc, ns)
    b = bundle.build_bundle(doc, ns, pg, ie_doc, nodes.now_utc())
    g = next((x for x in b["groups"] if x["group_id"] == gid), None)
    if g is None:
        return None
    cands = {c["candidate_id"]: c for c in b["candidates"]}
    return {"group": g, "members": [cands[m] for m in g["members"] if m in cands],
            "headings": [h for h in b["top_events"] if gid in h["group_ids"]],
            "end_states": [e for e in b["end_states"] if gid in e["group_ids"]],
            "basic_events": [be for be in b["basic_events"] if set(be["candidate_ids"]) & set(g["members"])],
            "ver": _ver(ie_fp)}


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'ie'. 없는 자료는 None(404)."""
    api = _api()
    if len(parts) == 1:
        return api._json(summary(engine))
    if len(parts) == 3 and parts[1] == "group":
        data = group_view(engine, parts[2])
        return api._json(data) if data is not None else None
    return None


# ---------------------------------------------------------------- 쓰기

def _write(engine, a, fn):
    """fn(ie_doc, results, ns, pg, by) -> 새 ie 문서. 읽은 지문(ver)을 대조하고 저장한다."""
    api = _api()
    by = engine.reviewer()
    if not by:
        raise api.CommandError("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 확정한 사람으로 남습니다.")
    ctx, why = _context(engine)
    if ctx is None:
        raise api.CommandError("failed", why)
    pg, ns, doc, ie_doc, ie_fp = ctx
    ver = a.get("ver")
    if ver not in (None, "none") and ver != ie_fp:
        raise api.CommandError("stale", "초기사건이 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요.")
    base = model.sync(ie_doc, doc, node_set=ns)
    try:
        new = fn(base, doc, ns, pg, by)
    except ValueError as exc:
        raise api.CommandError("failed", str(exc)[:300])
    try:
        fp = ie_store.save(new, expect=ie_fp)
    except ie_store.Conflict:
        raise api.CommandError("stale", "초기사건이 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요.")
    except (ValueError, OSError) as exc:
        raise api.CommandError("failed", "저장하지 못했습니다(%s)." % str(exc)[:200])
    engine.changed("ie", None)
    return {"ver": fp}


def _suggest(engine, a):
    return _write(engine, a, lambda base, doc, ns, pg, by: model.suggest(base, doc, pg=pg))


def _confirm(engine, a):
    return _write(engine, a, lambda base, doc, ns, pg, by: model.confirm(base, a["group_id"], doc, by, node_set=ns))


def _reopen(engine, a):
    return _write(engine, a, lambda base, doc, ns, pg, by: model.reopen(base, a["group_id"]))


def register(commands):
    api = _api()
    C, v_str = api.Command, api.v_str
    ver = (v_str(1, 100), True)

    def put(name, spec_, handler, doc):
        key = "ie." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("suggest", {"ver": ver}, _suggest, "규칙 초안 만들기(확정하지 않음, 두 번 돌려도 더하는 것이 없다)")
    put("confirm", {"group_id": (v_str(1, 20), True), "ver": ver}, _confirm, "그룹 확정(검토자 이름이 확정자로 남는다)")
    put("reopen", {"group_id": (v_str(1, 20), True), "ver": ver}, _reopen, "그룹 확정 풀기")
