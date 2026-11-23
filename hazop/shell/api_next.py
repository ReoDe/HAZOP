"""'다음에 할 일' 한 줄(규격 HZ-DSN-06 §3.1, 단위 U1). 읽기 토픽 `next`.

각 영역의 요약(구간·결과·초기사건·표제란·AI 검토·쪽 확정·작업)을 읽기만 해 사실(facts)을 모으고, 아래 RULES 표의 차례대로 할 일 목록을 만든다.
파일을 쓰지 않는다. 한 영역을 읽다 실패해도 그 영역만 빠지고 나머지는 나온다(이 줄은 안내다: 화면을 막지 않는다).

차례를 정하는 원칙(규격 §3.1): (1) 이미 한 일을 잃거나 틀린 결과로 이어질 수 있는 것, (2) 다음 단계를 막는 것, (3) 작업 흐름 순서.
새 상태(예: 시트 정체 단위의 '같은 번호 자리의 다른 파일 고르기', '여러 쪽 자료 등록 보류')는 RULES에 한 줄을 그 자리에 넣고, 필요한 사실을
facts()에 한 칸 더하면 된다. 웹은 차례를 정하지 않고 받은 대로 그린다.

꼴: {"ver", "running": {...}|None, "items": [{"kind", "count", "text", "detail", "action": {"label", "go"}, "tone"}]}
go: "panel:<이름>[#<자리>]" · "queue:<ai|lost>" · "confirm:<명령>"
"""

import logging

LOG = logging.getLogger(__name__)

TOPICS = ("next",)
# 이 영역들이 바뀌었다고 알리면 엔진이 next도 바뀌었다고 알린다(api.Engine.changed)
SOURCES = ("titleblock", "aireview", "nodes", "results", "ie", "drawings", "sheetconf", "sources", "links", "state")

UNREVIEWED = ("not_run", "partial", "failed")     # 'AI 검토 시작'을 기다리는 도면(§3.7. nothing·waiting·running은 세지 않는다)
RUNNING_TEXT = {"register": "도면을 읽고 있습니다", "ai_review": "AI가 도면을 검토하고 있습니다", "analysis": "AI 분석을 하고 있습니다",
                "graph_refresh": "도면 연결 정보를 갱신하고 있습니다", "export": "내보내고 있습니다"}


def _api():
    from hazop.shell import api
    return api


def _conflicts(engine):
    from hazop.graph import sources
    return sources.conflicts(engine.project_id())


def _safe(fn, what):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - 안내 한 줄을 위해 읽는다: 한 영역이 실패해도 나머지는 보인다
        LOG.warning("다음에 할 일: %s 읽기 실패", what, exc_info=True)
        return None


# ---------------------------------------------------------------- 사실 모으기(읽기만)
def facts(engine):
    """영역 요약에서 RULES가 쓰는 수를 모은다. 못 읽은 영역의 값은 None(그 규칙은 건너뜀)."""
    from hazop.shell import api_aireview, api_drawings, api_ie, api_nodes, api_results, api_titleblock  # noqa: F401
    f = {"project_id": engine.project_id()}
    f["running"] = engine.job_progress()
    names = _safe(engine.graph_names, "도면 목록") or {}
    f["sheets"] = len(names)
    cf = _safe(lambda: _conflicts(engine), "원본 고르기")
    if cf is not None:
        open_ = [c for c in cf if c.get("reason") != "settle_rebuild_failed" and not c.get("chosen") and not c.get("chosen_material")]   # 사람이 고른 자리는 끝난 일
        f["sheet_choose"] = len(open_)
        f["sheet_choose_first"] = open_[0]["graph_id"] if open_ else None
        f["sheet_skipped"] = sum(1 for c in cf if c.get("reason") == "settle_rebuild_failed")
        f["sheet_skipped_text"] = next((c.get("text") for c in cf if c.get("reason") == "settle_rebuild_failed"), None)
    lb = _safe(lambda: api_drawings.labels(engine), "도면 이름")
    if lb is not None:
        f["number_held"] = sum(1 for r in lb.values() if r.get("number_state") == "held")
    tb = _safe(lambda: api_titleblock.summary(engine), "표제란")
    f["titleblock"] = (tb["totals"]["materials"] - tb["totals"]["confirmed"]) if tb else None
    f["titleblock_first"] = next((r.get("material_id") for r in (tb or {}).get("rows") or [] if r.get("state") != "confirmed"), None)
    ar = _safe(lambda: api_aireview.overview(engine), "AI 검토")
    f["ai_candidates"] = sum(r["proposed"] for r in ar["drawings"]) if ar else None
    with_cands = [r for r in (ar or {}).get("drawings") or [] if r["proposed"]]
    f["ai_candidates_first"] = with_cands[0]["graph_id"] if with_cands else None
    f["ai_candidates_sheet"] = (with_cands[0]["drawing_number"], with_cands[0]["proposed"], len(with_cands)) if with_cands else None
    sc = _safe(lambda: api_drawings.exportable(engine), "쪽 확정")
    # 'AI 검토 시작'은 물을 곳이 있고(not_run·partial·failed) 사람이 아직 쪽을 확정하지 않은 도면만(실제 창 3차, 총괄 결정)
    confirmed = {r["graph_id"] for r in (sc or {}).get("drawings") or [] if r.get("state") == "confirmed"}
    todo = [r for r in (ar or {}).get("drawings") or [] if r.get("review") in UNREVIEWED and r["graph_id"] not in confirmed]
    f["ai_unreviewed"] = len(todo) if ar else None
    f["ai_unreviewed_first"] = todo[0]["graph_id"] if todo else None
    f["ai_unreviewed_sheet"] = todo[0]["drawing_number"] if todo else None
    f["sheet_confirm"] = sum(1 for r in sc["drawings"] if r.get("state") != "confirmed") if sc else None
    f["sheets_confirmed"] = sum(1 for r in sc["drawings"] if r.get("state") == "confirmed") if sc else None
    f["sheet_confirm_first"] = next((r["graph_id"] for r in (sc or {}).get("drawings") or [] if r.get("state") != "confirmed"), None)
    ns = _safe(lambda: api_nodes.summary(engine), "구간") if names else None
    rs = _safe(lambda: api_results.summary(engine), "분석 결과") if names else None
    if ns and ns.get("available"):
        f["nodes_total"] = len(ns["nodes"])
        f["nodes_draft"] = sum(1 for n in ns["nodes"] if n["state"] == "applied")
        f["apply_failed"] = bool(ns.get("stale")) and not engine.catching(f["project_id"])
        f["lost_members"] = sum((ns.get("check") or {}).get("lost_members", {}).values())
        f["lost_nodes"] = sorted((ns.get("check") or {}).get("lost_members", {}))
    if rs and rs.get("available") and not rs.get("empty"):
        f["lost_refs"] = sum(n.get("lost_refs") or 0 for n in rs["nodes"])
        f["lost_nodes"] = sorted(set(f.get("lost_nodes") or []) | {n["node_id"] for n in rs["nodes"] if n.get("lost_refs")})
        m = rs.get("matrix") or {}
        f["nodes_unrun"] = sum(1 for n in rs["nodes"] if not any(c.get("state") == "analyzed" for c in (m.get(n["node_id"]) or {}).values()))
        f["results_unjudged"] = int((rs.get("kpi") or {}).get("unreviewed") or 0)
    ie = _safe(lambda: api_ie.summary(engine), "초기사건") if names else None
    if ie and ie.get("available"):
        k = ie.get("kpi") or {}
        f["ie_draft"] = int(k.get("draft") or 0)
        f["ie_none"] = 1 if not k.get("groups") and k.get("candidates") else 0      # 초안이 없고 승인된 결과(후보)가 있다
    return f


# ---------------------------------------------------------------- 규칙 표(차례 = 표의 줄 순서)
def _n(f, key):
    v = f.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _recheck(f):
    """다시 확인할 수: 찾지 못한 구성요소 수(알림 줄과 같은 단위, 실제 창 3차 결함 6). 구성요소가 없고 분석 결과만 걸렸으면 그 수."""
    return _n(f, "lost_members") or _n(f, "lost_refs")


def _lost_detail(f):
    ids = f.get("lost_nodes") or []
    if not ids:
        return None
    shown = "·".join(ids[:5]) + (" 외 %d개" % (len(ids) - 5) if len(ids) > 5 else "")
    return "검토구간 %s에 걸려 있습니다" % shown


# (kind, 수를 세는 함수, 문장, 단추 글, 가는 곳, 꼴)
RULES = (
    ("apply_failed", lambda f: 1 if f.get("apply_failed") else 0,
     lambda f, n: "도면 변경을 반영하지 못했습니다", "다시 시도", "confirm:nodes.catch_up", "warn"),
    ("no_sheets", lambda f: 1 if f.get("sheets") == 0 and not f.get("running") else 0,
     lambda f, n: "등록한 도면이 없습니다. 도면 파일을 끌어 놓아 시작하세요", "도면 올리기", "panel:drawings", ""),
    ("recheck", _recheck,
     lambda f, n: ("도면이 바뀌어 찾지 못한 구성요소 %d개를 다시 확인해야 합니다" if _n(f, "lost_members") else "도면이 바뀌어 분석 결과 %d곳을 다시 확인해야 합니다") % n,
     "확인하기", "queue:lost", "warn"),
    # 시트 정체(U4): 같은 번호 자리에 파일·형식이 둘 이상이면 고르기, 정착이 들이지 못한 가려진 도면
    ("sheet_choose", lambda f: _n(f, "sheet_choose"),
     lambda f, n: "같은 번호의 도면 파일이 둘 이상인 곳이 %d곳 있습니다. 쓸 파일을 고르세요" % n, "파일 고르기", "panel:drawings#sources", "warn"),
    ("sheet_skipped", lambda f: _n(f, "sheet_skipped"),
     lambda f, n: "도면 %d장을 목록에 들이지 못했습니다" % n, "도면 보기", "panel:drawings#sources", "warn"),
    ("titleblock", lambda f: _n(f, "titleblock"),
     lambda f, n: "표제란을 확정하지 않은 도면이 %d장 있습니다" % n, "표제란 확정", "panel:drawings#titleblock", ""),
    ("number_held", lambda f: _n(f, "number_held") if not _n(f, "titleblock") else 0,
     lambda f, n: "여러 쪽 자료라 도면 번호를 쓰지 못한 쪽이 %d장 있습니다" % n, "도면 보기", "panel:drawings", ""),
    ("ai_unreviewed", lambda f: _n(f, "ai_unreviewed"),
     lambda f, n: ("%s는 아직 AI 검토를 하지 않았습니다" % f["ai_unreviewed_sheet"]) if n == 1 and f.get("ai_unreviewed_sheet") else "AI 검토를 하지 않은 도면이 %d장 있습니다" % n,
     "AI 검토 시작", "confirm:aireview.run", ""),
    ("ai_candidates", lambda f: _n(f, "ai_candidates"),
     lambda f, n: ("%s의 AI 후보 %d건을 확인해 주세요" % f["ai_candidates_sheet"][:2]) if f.get("ai_candidates_sheet") else "AI 후보 %d건을 확인해 주세요" % n,
     "검토하기", "queue:ai", ""),
    ("sheet_confirm", lambda f: _n(f, "sheet_confirm") if not _n(f, "titleblock") else 0,
     lambda f, n: "원본과 견주어 확정할 쪽이 %d장 있습니다" % n, "쪽 확정", "panel:drawings#sheetconf", ""),
    ("nodes_none", lambda f: 1 if _n(f, "sheets_confirmed") and f.get("nodes_total") == 0 else 0,
     lambda f, n: "검토구간을 만들 차례입니다. 도면에서 네모로 끌어 고르세요", "구간 만들기", "panel:nodes#pick", ""),
    ("nodes_draft", lambda f: _n(f, "nodes_draft"),
     lambda f, n: "확정하지 않은 검토구간이 %d개 있습니다" % n, "모두 확정", "confirm:nodes.confirm", ""),
    ("nodes_unrun", lambda f: _n(f, "nodes_unrun"),
     lambda f, n: "분석하지 않은 검토구간이 %d개 있습니다" % n, "분석 실행", "panel:results#run", ""),
    ("results_unjudged", lambda f: _n(f, "results_unjudged"),
     lambda f, n: "판정하지 않은 분석 결과가 %d건 있습니다" % n, "판정하기", "panel:results#unjudged", ""),
    ("ie_none", lambda f: _n(f, "ie_none"),
     lambda f, n: "초기사건 초안을 만들 차례입니다", "초안 만들기", "confirm:ie.suggest", ""),
    ("ie_draft", lambda f: _n(f, "ie_draft"),
     lambda f, n: "초기사건 초안 %d그룹을 확인해 주세요" % n, "초안 보기", "panel:ie#draft", ""),
)
# 단추가 바로 갈 자리(화면이 그 도면·자료·구간을 연다). 없으면 그 패널만 연다
TARGET = {"sheet_choose": "sheet_choose_first", "titleblock": "titleblock_first", "sheet_confirm": "sheet_confirm_first", "ai_unreviewed": "ai_unreviewed_first",
          "ai_candidates": "ai_candidates_first"}

NONE_ITEM = {"kind": "none", "count": 0, "text": "지금 할 일이 없습니다", "detail": None,
             "action": {"label": "Excel로 내보내기", "go": "confirm:results.export_excel"}, "tone": "quiet"}


def items(f):
    """사실 → 할 일 목록(규칙 표 차례). 할 일이 없으면 '할 일 없음' 하나."""
    out = []
    for kind, count, text, label, go, tone in RULES:
        n = count(f)
        if n:
            out.append({"kind": kind, "count": n, "text": text(f, n), "detail": _detail(f, kind),
                        "action": {"label": label, "go": go, "target": _target(f, kind)}, "tone": tone})
    return out or [dict(NONE_ITEM)]


def _detail(f, kind):
    if kind == "recheck":
        return _lost_detail(f)
    if kind == "sheet_skipped":
        return f.get("sheet_skipped_text")
    if kind == "ai_candidates" and f.get("ai_candidates_sheet") and f["ai_candidates_sheet"][2] > 1:
        return "도면 %d장에 모두 %d건" % (f["ai_candidates_sheet"][2], f["ai_candidates"])
    return None


def _target(f, kind):
    if kind == "recheck":
        return (f.get("lost_nodes") or [None])[0]
    return f.get(TARGET.get(kind, ""))


def _running(f):
    jobs = f.get("running") or []
    if not jobs:
        return None
    j = jobs[0]
    label = j.get("text") or RUNNING_TEXT.get(j.get("kind")) or j.get("label") or "작업을 하고 있습니다"
    return {"what": j.get("kind"), "label": label, "done": j.get("done"), "total": j.get("total"), "jobs": len(jobs)}


def summary(engine):
    f = facts(engine)
    out = {"project_id": f["project_id"], "running": _running(f), "items": items(f)}
    out["ver"] = "|".join("%s:%s" % (i["kind"], i["count"]) for i in out["items"]) + ("|run" if out["running"] else "")
    return out


def read(engine, parts, query):
    if parts == ["next"]:
        return _api()._json(summary(engine))
    return None
