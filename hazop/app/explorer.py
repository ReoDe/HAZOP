"""단계별 탐색기 모듈(U-04). 레일에서 고른 단계 k의 모듈 STAGE_MODULES[k](win)만 탐색기에 보인다.

모듈은 [Group]을 돌려준다. 항목은 (글자, 대상, 오른쪽 글자, 아이콘, 도구 설명)이고 대상은 (화면 index, key) 또는
("cmd", 명령 이름)이다. 명령은 COMMANDS가 실행한다(빈 상태 버튼·바로가기 줄이 같은 길을 쓴다).
단계를 넘나드는 것(권고 등)은 한 모듈에만 두고 명령 팔레트(Ctrl+P)로 어디서든 찾는다."""

from collections import namedtuple

from hazop.app import data, project_ctx, related
from hazop.app.screens.register import STATUS_LABELS, material_type_of
from hazop.app.screens.study import seg_icon
from hazop.extract import corrections
from hazop.graph import project
from hazop.ie import model as ie_model
from hazop.study import nodes as study_nodes
from hazop.study import results as res
from hazop.study import span

# empty: (안내 글, 버튼 또는 None). 버튼·action은 (글자, 대상, 도구 설명). info: 개수에 세지 않는 정보 줄 [(글자, 도구 설명)]
Group = namedtuple("Group", "name items empty action about info")
Group.__new__.__defaults__ = (None, None, ())

STATUS_SHORT = {"registered": "등록됨", "failed": "실패", "on_hold": "보류", "draft": "진행 중"}


def go_then(index, method=None, *args):
    def run(win):
        if win.go(index) and method:
            getattr(win.screens[index], method)(*args)
    return run


COMMANDS = {
    "register_new": go_then(0, "_pick"),
    "go_extract": go_then(1),
    "go_graph": go_then(4),
    "go_study": go_then(5),
    "repropose": go_then(5, "repropose"),
    "go_results": go_then(6),
    "run_ai": go_then(6, "request_ai", "all"),
    "export_excel": go_then(6, "export_excel"),
    "go_initiating": go_then(7),
    "export_ie": go_then(7, "export_bundle"),
    "suggest_ie": go_then(7, "suggest"),
}


def cmd(name):
    return ("cmd", name)


# ---------------------------------------------------------------- ① 등록
def register_module(win):
    """등록 자료(도면·문서)와 상태·개정·등록일, 등록 작업 진행, 새 자료 등록. 등록 없이 추출된 도면은 따로 묶는다."""
    scr = win.screens[0]
    drawings, docs = [], []
    for e in scr.rows:
        rec = e["record"]
        name = rec.get("original_name") or rec["material_id"]
        number = rec.get("drawing_number")
        rev = data.unknown_text(rec.get("design_revision"))
        at = ((rec.get("history") or [{}])[0].get("at") or "")[:10]
        tip = "%s\n%s · 개정 %s · 등록 %s · %s" % (name, rec["material_id"], rev, at or "—",
                                              STATUS_LABELS.get(rec.get("status"), rec.get("status")))
        item = (number or name, (0, e["path"]), STATUS_SHORT.get(rec.get("status"), rec.get("status") or ""), None, tip)
        (docs if material_type_of(rec) == "design_document" else drawings).append(item)
    job = scr.job
    running = ["%s %s" % (job.name.text(), job.step.text())] if job.isVisible() and job.step.isVisible() else []
    new = ("＋ 새 자료 등록…", cmd("register_new"), "P&ID 도면(drawio·PDF) 또는 설계 문서를 골라 등록합니다")
    groups = [Group("도면", drawings, ("등록한 도면 없음", new), new if drawings else None,
                    info=[("진행 · %s" % t, t) for t in running]),
              Group("문서", docs, ("등록한 문서 없음", None))]
    loose = [(name, (1, name), "샘플" if origin == "샘플 실행 데이터" else "미등록", None,
              "%s\n출처: %s(① 등록을 거치지 않은 추출)\n누르면 ② 추출에서 엽니다." % (name, origin))
             for name, origin in data.unregistered_extractions()]
    if loose:
        groups.append(Group("등록 없이 추출", loose, ("", None)))
    return groups


# ---------------------------------------------------------------- ② 추출
def unlinked_by_drawing(pg):
    """{도면 번호: 미연결 연결점 수}(프로젝트 그래프의 sheet_links)."""
    dn = {s["graph_id"]: s["drawing_number"] for s in pg["sheets"]}
    out = dict.fromkeys(dn.values(), 0)  # 이 프로젝트 도면은 0부터(다른 프로젝트 도면과 구분)
    for l in pg["sheet_links"]:
        if l["status"] != project.LINKED:
            for end in (l["from"], l.get("to")):
                if end and end["graph_id"] in dn:
                    out[dn[end["graph_id"]]] = out.get(dn[end["graph_id"]], 0) + 1
    return out


def extract_module(win):
    """도면별 추출 상태: 미확인·사람 수정·도면 간 미연결 수. 누르면 ②에서 그 도면을 연다. 미추출 쪽·자료는 따로 묶는다."""
    idx = win.index()
    unlinked = unlinked_by_drawing(idx.graph) if idx and idx.graph else {}
    items = []
    for e in data.list_extractions():
        b = data.extraction_brief(e["path"]) or {}
        number = b.get("drawing_number") or e["name"]
        try:
            fixes = len((corrections.load(e["name"]) or {}).get("ops") or [])
        except (OSError, ValueError):
            fixes = 0
        unk, link = b.get("unknowns") or 0, unlinked.get(number)
        parts = ["미확인 %d" % unk, "사람 수정 %d" % fixes,
                 "도면 간 미연결 %s" % (link if link is not None else "— (다른 프로젝트)")]
        tip = "%s%s\n추출됨 · %s%s\n누르면 ② 추출에서 엽니다." % (
            e["name"], " · %s" % b["title"] if b.get("title") else "", " · ".join(parts),
            "\n출처: %s" % b["origin"] if b.get("origin") else "")
        right = "미확인 %d" % unk if unk else ("미연결 %d" % link if link else "추출됨")
        items.append((number if number == e["name"] else "%s (%s)" % (number, e["name"]), (1, e["name"]), right, None, tip))
    data.save_briefs()
    pending = []
    for e in win.screens[0].rows:
        rec, pages = e["record"], e.get("pages") or {}
        name = rec.get("original_name") or rec["material_id"]
        left = pages.get("total", 0) - pages.get("extracted", 0) - pages.get("skipped", 0)
        if rec.get("status") == "registered" and not e["extracted"]:
            pending.append((rec.get("drawing_number") or name, (0, e["path"]), "미추출", None,
                            "%s\n아직 추출하지 않았습니다. 누르면 ① 등록에서 그 행을 고릅니다." % name))
        elif left > 0:
            pending.append((rec.get("drawing_number") or name, (0, e["path"]), "%d쪽" % left, None,
                            "%s\n추출하지 않은 쪽 %d (전체 %d쪽)" % (name, left, pages["total"])))
    groups = [Group("도면 추출", items, ("추출한 도면 없음", ("① 등록 먼저", cmd("register_new"),
                                                              "도면을 등록하면 drawio는 바로, PDF는 쪽마다 추출합니다")))]
    if pending:
        groups.append(Group("미추출", pending, ("", None)))
    return groups


# ---------------------------------------------------------------- ③ 그래프
def graph_module(win):
    """프로젝트 지식그래프 목록과, ③에서 연 그래프의 노드 종류·관계 요약, 고아·근거 공백 수."""
    scr = win.screens[4]
    kgs = [(t, (4, k), "", None, t) for t, k in scr.explorer_items()]
    groups = [Group("지식그래프", kgs, ("추출 뒤 자동으로 만듭니다", ("② 추출 보기", cmd("go_extract"),
                                                                       "지식그래프는 추출한 도면과 문서로 만듭니다")))]
    d = scr.data
    if d and kgs:
        kinds = {}
        for n in d["nodes"]:
            k = "P&ID · %s" % (n.get("kind") or "기타") if n["layer"] == "pid" else "지식 · %s" % (n.get("type") or "기타")
            kinds[k] = kinds.get(k, 0) + 1
        rels = {}
        for l in d["links"]:
            rels[l["kind"]] = rels.get(l["kind"], 0) + 1
        a2 = d["algo"].get("A2") or {}
        m = d["meta"]
        info = [("노드 %d · 관계 %d" % (len(d["nodes"]), len(d["links"])),
                 "\n".join("%s %d" % kv for kv in sorted(kinds.items()))),
                ("관계 종류 %d" % len(rels), "\n".join("%s %d" % kv for kv in sorted(rels.items()))),
                ("고아 %d · 근거 공백 %d" % (len(a2.get("orphans") or {}), len(a2.get("gaps") or {})),
                 "A2 고아·근거 공백(자료 요청 메모 후보). ③ 범례에서 강조합니다."),
                ("미확인 %d · 충돌 %d" % (m["unknowns"], m["conflicts"]),
                 "지식그래프 검증 상태(③ 위 칩과 같음). 재확인 필요 %d" % m["recheck"])]
        groups.append(Group("요약", [], ("", None), about=(scr.kg or {}).get("kg_id"), info=info))
    return groups


# ---------------------------------------------------------------- ④ 구간 · ⑤ 결과(같은 프로젝트 구간)
def project_nodes(win):
    """(idx, pg, ns, view, usable, results) 지금 도면이 속한 프로젝트의 구간 집합과 ⑤ 결과."""
    idx = win.index()
    study = win.screens[5]
    pg = idx.graph if idx else None
    live = (study.node_set if pg and study.node_set and study.name == win.drawing
            and study.node_set.get("graph_id") == pg["graph_id"] else None)  # ④가 연 프로젝트 집합(저장 전 포함)
    ns = live or (idx.node_set if idx else None)
    view = (idx.view_of(ns) if live else idx.view) if ns else None
    usable = idx is not None and (live is None or bool(study_nodes.active_nodes(live)))  # 결과는 확정·잠금 구간에만 있다
    rs = win.screens[6]
    results = (rs.results if rs.results is not None and rs.name == win.drawing else idx.results if idx else None)
    if results is not None and ns and res.is_stale(results, ns):
        results = None  # 다른(이전) 확정본으로 만든 결과는 지금 구간의 진행으로 보이지 않는다
    return idx, pg, ns, view, usable, results


def node_items(win, view, ns, dn, progress):
    """구간 항목. progress(node_id) → (오른쪽 글자, 설명). 도면 필터 dn이면 그 도면을 지나는 구간(걸친 구간 포함)."""
    listed = (view or ns or {}).get("nodes", [])
    shown = span.nodes_on_drawing(view, dn) if dn and view else listed
    order = {n["node_id"]: i for i, n in enumerate((ns or view or {}).get("nodes", []))}  # 색은 집합 순서(④·⑤와 같게)
    out = []
    for n in shown:
        right, detail = progress(n["node_id"])
        text = project_ctx.node_label(n)
        out.append((text, (5, n["node_id"]), right, seg_icon(order[n["node_id"]], ""),
                    "%s\n%s\n누르기: ⑤ 결과 화면에서는 그 행, 다른 화면에서는 ④ 구간 · Alt+누르기: ④ 구간" % (text, detail)))
    return out


def study_module(win):
    """프로젝트 구간 S1…Sn(도면 범위 [101 → 102]), 확정 상태·덮음률·미포함, 도면 필터."""
    idx, pg, ns, view, _usable, _results = project_nodes(win)
    dn = win.explorer_drawing_choice(pg)
    scope = dn or (pg["project_id"] if pg else None)
    if not pg:
        return [Group("검토구간", [], ("도면을 고르면 구간이 보입니다",
                                     ("② 추출 먼저", cmd("go_extract"), "구간은 추출한 도면의 프로젝트 그래프로 제안합니다")))]
    info = []
    cover = None
    if ns:
        cover, c = idx.ctx.coverage_text(ns)
        active = study_nodes.active_nodes(ns)
        state = ("확정됨" if study_nodes.all_confirmed(ns) else "일부 확정 %d/%d" % (len(active), len(ns["nodes"]))
                 if active else "적용됨(확정 전)")
        info = [("상태 · %s" % state, "구간 집합 상태. 확정해야 ⑤ 분석을 합니다."),
                ("덮음률 · %d%%" % round(c["project"]["ratio"] * 100), "%s\n모든 구성요소가 어느 구간에 들어가야 100%%" % cover),
                ("미포함 %d" % (c["project"]["total"] - c["project"]["covered"]),
                 "어느 구간에도 들어가지 않은 프로젝트 구성요소 수")]
    scr = win.screens[5]
    ai = scr.review_counts() if ns and scr.node_set is not None and scr.node_set.get("graph_id") == ns.get("graph_id") else None
    if ai and ai["total"]:
        info.append(("AI 제안 %d건 · 미처리 %d건" % (ai["total"], ai["open"]),
                     "④ AI 구간 검토 제안(초안). 미처리 제안이 있어도 확정은 막지 않습니다%s"
                     % (" · 오래된 제안 %d건(구간이 바뀜)" % ai["stale"] if ai["stale"] else "")))
    items = node_items(win, view, ns, dn, lambda _nid: ("", "구간 구성은 ④ 구간 화면에서 봅니다"))
    empty = (("이 도면을 지나는 구간 없음", None) if ns else
             ("아직 구간이 없습니다", ("구간 제안 실행", cmd("repropose"), "프로젝트 그래프로 구간을 새로 제안합니다")))
    return [Group("검토구간" + (" · %s" % scope if scope else ""), items, empty,
                  about="%s%s" % ("" if dn else "프로젝트 전체 구간\n", cover or ""), info=info)]


def _result_rows(view):
    """⑤ 행렬과 같은 행: 스크리닝 제외 구간은 빼고 낮음 구간은 맨 아래(results 화면 _rows와 같은 규칙)."""
    if not view:
        return view
    status = lambda n: (n.get("screen") or {}).get("status") or "keep"  # noqa: E731
    shown = [n for n in view["nodes"] if status(n) != "excluded" and study_nodes.is_active(n)]
    return dict(view, nodes=[n for n in shown if status(n) != "low"] + [n for n in shown if status(n) == "low"])


def results_module(win):
    """구간별 분석 진행(분석 전·미검토·실패), 권고 목록, 내보내기."""
    idx, pg, ns, view, usable, results = project_nodes(win)
    dn = win.explorer_drawing_choice(pg)
    scope = dn or (pg["project_id"] if pg else None)
    rs = win.screens[6]
    confirmed = bool(ns) and bool(study_nodes.active_nodes(ns))
    shown = results if usable else None
    cached, counted = getattr(rs, "summary_of", (None, None))
    summary = (counted if shown is cached else res.matrix_summary(shown)) if shown else None
    table = related.progress_table(shown, len(rs.deviations), summary) if shown else None
    rows = _result_rows(view)
    items = node_items(win, rows, ns, dn,
                       lambda nid: related.node_progress(table, nid, len(rs.deviations)))
    info, todo = [], None
    if confirmed and shown:
        visible = {n["node_id"] for n in (rows or {}).get("nodes", [])} if rows else None
        cells = [c for c in shown["cells"] if visible is None or c["node_id"] in visible]  # ⑤ 행렬 행과 같은 칸만
        summary = {k: v for k, v in summary.items() if visible is None or k in visible}
        failed = sum((c.get("ai_run") or {}).get("status") == "failed" for c in cells)
        todo = sum(c["state"] == "not_analyzed" for c in cells)
        unrev = sum(s["unreviewed"] for row in summary.values() for s in row.values())
        info = [("분석 전 %d칸" % todo, "⑤ 행렬 전체 칸 기준"),
                ("미검토 %d · 실패 %d" % (unrev, failed), "⑤ 행렬 전체 칸 기준. J로 다음 미검토 칸")]
    export = (("Excel로 내보내기…", cmd("export_excel"), "⑤ 결과를 HAZOP 워크시트(Excel)로 내보냅니다")
              if confirmed and usable else None)
    if not pg:
        empty = ("도면을 고르면 구간이 보입니다", ("② 추출 먼저", cmd("go_extract"), "도면을 먼저 추출합니다"))
    elif not confirmed:
        empty = ("확정한 구간이 없습니다", ("④ 구간 확정하러 가기", cmd("go_study"), "④ 검토구간에서 구간을 확정합니다"))
    else:
        empty = ("이 도면을 지나는 구간 없음", None)
    groups = [Group("구간별 분석" + (" · %s" % dn if dn else ""), items if confirmed else [], empty, export,
                    about="%s의 구간 × 편차 진행(⑤ 행렬과 같은 수)" % scope if scope else None, info=info)]
    recs = []
    if idx and idx.results:
        for c in idx.results["cells"]:
            for e in c.get("entries") or []:
                if e.get("recommendation") and e.get("status") != "rejected":
                    d = idx.deviation(c["deviation_id"])
                    text = "%s × %s · %s" % (c["node_id"], d["label"] if d else c["deviation_id"], e["recommendation"])
                    recs.append((text, (6, (c["node_id"], c["deviation_id"])), "", None, text))
    groups.append(Group("권고", recs, ("분석하면 권고가 모입니다",
                                       ("AI 일괄 분석", cmd("run_ai"), "확정 구간 × 편차 칸을 AI로 분석합니다")
                                       if confirmed and usable and todo != 0 else None)))
    return groups


# ---------------------------------------------------------------- ⑥ 초기사건
def initiating_module(win):
    """초기사건 그룹(상태), 판정 대기(보류·AI 초안 판정·미배정), 완전성 공백, 내보내기. ⑥ 화면이 그린 묶음 dict를 읽는다."""
    scr = win.screens[7]
    v = scr.view
    if v is None:
        return [Group("초기사건 그룹", [], ("⑥ 화면을 열면 ⑤에서 승인한 원인이 후보로 들어옵니다",
                                        ("⑥ 초기사건 열기", cmd("go_initiating"), "⑥ 초기사건 화면으로 갑니다")))]
    groups = [("%s %s" % (g["group_id"], g["name"]), (7, ("group", g["group_id"])),
               ie_model.GROUP_STATUSES[g["status"]], None,
               "%s %s\n상태: %s · 후보 %d%s" % (g["group_id"], g["name"], ie_model.GROUP_STATUSES[g["status"]],
                                            g["member_count"], "".join("\n· " + p for p in g["problems"][:4])))
              for g in v["groups"]]
    loose = sum(c["group_id"] is None and c["judgement"] == "yes" for c in v["candidates"])
    held = sum(c["judgement"] == "undecided" for c in v["candidates"])
    ai = sum(c["ie_origin"] != "human" for c in v["candidates"])
    suggest = ("규칙 초안 만들기", cmd("suggest_ie"), "같은 범주·같은 보호수단 후보를 초안 그룹으로 묶습니다(§6.3)")
    gaps = [r for r in v["completeness"] if r["status"] == "gap" and r["code"] not in scr.doc["coverage"]]
    return [Group("초기사건 그룹", groups, ("아직 그룹이 없습니다", suggest), suggest if groups else None,
                  info=[("미배정 후보 %d" % loose, "판정이 '후보'인데 그룹에 들지 않은 후보")]),
            Group("판정 대기", [("보류 %d · 사람 판정 필요" % held, (7, ("tab", 0)), "", None, "⑤에서 판정을 정합니다"),
                                ("AI 초안 판정 %d" % ai, (7, ("tab", 0)), "", None, "⑤에서 사람이 판정해야 그룹을 확정할 수 있음")],
                  ("", None)),
            Group("완전성 대조", [("처리를 정하지 않은 공백 범주 %d" % len(gaps), (7, ("tab", 5)), "", None,
                                   "공백 행마다 범위 밖 · 다른 기법 · 해당 없음 중 하나와 사유를 적습니다")], ("", None)),
            Group("내보내기", [("IE 인계 묶음(Excel·JSON)…", cmd("export_ie"), "", None,
                                "승인 항목만으로 IE 인계 묶음을 저장합니다")], ("", None))]


STAGE_MODULES = (register_module, extract_module, graph_module, study_module, results_module,
                 initiating_module)  # 레일 단계 ①~⑥
DRAWING_FILTER_STAGES = (3, 4)  # 도면 필터는 구간 목록이 있는 ④·⑤ 모듈에만
