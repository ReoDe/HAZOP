"""프로젝트 그래프(도면 간 연결) 검사 (QA용). 근거: hazop/graph/project.py, 사용자 요청 2026-11-07.

샘플 도면 6장(SNP-M-101~501)을 임시 폴더에서 새로 추출·빌드해 프로젝트 그래프를 만들고 측정·판정한다
(저장소의 출력/·데이터/에 쓰지 않음).
- 도면 연결 매칭: 짝 12, 미연결 2(상대 도면 SNP-M-402 미등록), 방향 모순 0
- 물리 연결 성분 1(도면별 6 → 1), 같은 입력 순서를 바꿔도 같은 graph_version
- 프로젝트 전체 검토구간: 덮음률 100%, 구간당 능동 요소 ≤ 5, 도면을 넘는 구간 있음, 도면별 보기가 모든 도면을 덮음
- 도면을 넘는 경로 질의(SNP-M-102 RC-PZ01 → SNP-M-301 SI-TK01), 탐색이 이어진 연결점에서 멈추지 않음
- AI 맥락: 지식그래프를 프로젝트 ID로 옮겨 차단 없이 씀, 구간 밖 다른 도면 기기 태그는 근거 경고
- 사람 지정(link·unlink)이 자동 매칭보다 앞섬, no-project 저장본을 그대로 읽음
종료 코드 0 = 전부 통과.
"""

import copy
import json
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.analysis import explore  # noqa: E402
from hazop.graph import project  # noqa: E402
from hazop.graph.query import GraphQuery  # noqa: E402
from hazop.study import ai_cells  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402

import check_study_nodes  # noqa: E402

AT = "2026-11-07T00:00:00Z"
PID = project.UNREGISTERED_PROJECT
EXPECT = {"linked": 12, "unlinked": {"unregistered_drawing": 2}, "direction_conflicts": 0, "physical_components": 1}


def _tag(pg, tag):
    return next(n["entity_id"] for n in pg["nodes"] if n.get("tag") == tag and n["node_type"] == "drawing_object")


def check_links(graphs, pg, s):
    f = []
    for k, v in EXPECT.items():
        if s[k] != v:
            f.append("%s = %r (기대 %r)" % (k, s[k], v))
    for l in pg["sheet_links"]:
        if l["status"] == project.LINKED and not (l["from"]["direction"] == "to" and l["to"]["direction"] == "from"):
            f.append("%s 흐름 방향이 TO→FROM이 아님" % l["link_id"])
        if not l["from"]["label_text"]:
            f.append("%s 근거(연결 표시 원문) 없음" % l["link_id"])
    shuffled = [dict(g, nodes=list(reversed(g["nodes"]))) for g in reversed(graphs)]
    if project.build(PID, shuffled) != pg:
        f.append("입력 순서를 바꾸면 결과가 다름")
    return f


def check_study(pg):
    f = []
    s = sn.propose(pg, at=AT)
    pf, cov = check_study_nodes.check_proposal(pg, s)
    f += pf
    cross = [n for n in s["nodes"] if len(project.sheets_of(pg, n["members"])) > 1]
    if not cross:
        f.append("도면을 넘는 구간이 없음")
    seen = set()
    for sh in pg["sheets"]:
        view = project.sheet_view(s, pg, sh["graph_id"])
        seen |= {project.nid(sh["graph_id"], m) for v in view for m in v["members"]}
    sheet_ids = {n["entity_id"] for n in pg["nodes"] if n.get("sheet")}
    if seen != sheet_ids:
        f.append("도면별 보기가 도면 구성요소를 다 덮지 않음(%d/%d)" % (len(seen), len(sheet_ids)))
    return f, s, cov, cross


def check_query(pg, s):
    f = []
    a, b = _tag(pg, "RC-PZ01"), _tag(pg, "SI-TK01")
    p = GraphQuery(pg).path(a, b)
    if not p["ignoring_direction"]["found"]:
        f.append("도면을 넘는 경로 질의 실패 RC-PZ01 → SI-TK01")
    else:
        steps = [x["entity_id"] for x in p["ignoring_direction"]["nodes"]]
        if len(project.sheets_of(pg, steps)) < 2:
            f.append("경로가 한 도면 안에 있음")
    node = next(n for n in s["nodes"] if a in n["members"])
    r = explore.explore(GraphQuery(pg), a, explore.region_members(pg, node["members"]), ["has_endpoint"], 30, 500)
    linked = {n["entity_id"] for n in pg["nodes"] if (n.get("sheet_link") or {}).get("status") == project.LINKED}
    stopped = [t["at"] for t in r["truncations"] if t["reason"] == "external_drawing"]
    if set(stopped) & linked:
        f.append("탐색이 이어진 연결점에서 멈춤: %s" % sorted(set(stopped) & linked)[:3])
    return f, p


def check_ai(graphs, pg, cross):
    import check_kg_context
    from hazop.kg import build as kg_build
    f = []
    g102 = next(g for g in graphs if g["graph_id"] == "graph-SNP-M-102")
    kg = kg_build.build_kg(check_kg_context.sample_knowledge(), [g102])
    ctxs = [(n, ai_cells.node_context(n, pg, kg)) for n in cross]
    blocked = [c["kg_note"] for _, c in ctxs if c["kg_note"] and "쓰지 않음" in c["kg_note"]]
    with_items = [(n, c) for n, c in ctxs if (c["prompt"]["knowledge"] or {}).get("items")]
    if blocked:
        f.append("프로젝트 그래프에서 지식그래프가 차단됨: %s" % blocked[0])
    if not with_items:
        return f + ["도면을 넘는 구간에 SNP-M-102 지식 항목이 들어가지 않음"]
    node, ctx = with_items[0]
    comps = [c for c in ctx["prompt"]["components"] if not c["entity_id"].startswith("xlink-")]
    if len(ctx["prompt"]["drawing"]["drawings"]) < 2 or not all("drawing" in c for c in comps):
        f.append("AI 맥락에 출처 도면이 없음")
    stale = copy.deepcopy(kg)
    stale["graph_refs"] = [dict(r, graph_version="v-old") for r in stale["graph_refs"]]
    if "쓰지 않음" not in (ai_cells.node_context(node, pg, stale)["kg_note"] or ""):
        f.append("판이 다른 지식그래프를 막지 않음")
    outside = sorted(ctx["allowed"]["outside_sheet_tags"])
    warn = ai_cells.check_evidence({"equipment_tags": outside[:1]}, ctx) if outside else []
    if not outside or not any("다른 도면" in w for w in warn):
        f.append("구간 밖 다른 도면 기기 태그에 근거 경고가 없음")
    if ai_cells.check_evidence({"equipment_tags": [c["tag"] for c in comps if c["tag"]]}, ctx):
        f.append("구간 안 다른 도면 기기 태그에 경고가 붙음")
    return f


def check_manual(graphs, pg):
    f = []
    first = next(l for l in pg["sheet_links"] if l["status"] == project.LINKED)
    end = {"drawing_number": first["from"]["drawing_number"], "source_object_id": first["from"]["source_object_id"]}
    ops = [{"op_id": "op-1", "op": "unlink", "ends": [end], "by": "검사", "at": AT, "reason": "검사"}]
    out = project.build(PID, graphs, ops)
    s = project.summary(out)
    if s["linked"] != EXPECT["linked"] - 1 or s["unlinked"].get("manual_unlink") != 1:
        f.append("사람 unlink가 반영되지 않음: %s" % s)
    other = {"drawing_number": first["to"]["drawing_number"], "source_object_id": first["to"]["source_object_id"]}
    ops2 = ops + [{"op_id": "op-2", "op": "link", "ends": [end, other], "by": "검사", "at": AT, "reason": "검사"}]
    if project.build(PID, graphs, ops2)["manual_skipped"] != [
            {"op_id": "op-2", "reason": "같은 연결점을 가리키는 앞선 지정이 있음"}]:
        f.append("같은 연결점을 두 번 지정해도 건너뛰지 않음")
    return f


def check_legacy(tmp):
    f = []
    g = {"graph_id": "graph-L", "graph_version": "v1", "project_id": None, "nodes": [], "edges": []}
    legacy = os.path.join(sn.store_dir(), project.LEGACY_PROJECT_DIR, "graph-L.json")
    os.makedirs(os.path.dirname(legacy), exist_ok=True)
    doc = {"kind": sn.KIND, "graph_id": "graph-L", "status": "confirmed", "nodes": []}
    with open(legacy, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    if sn.load(g) != doc:
        f.append("no-project 저장본을 읽지 못함")
    if not sn.store_path(None, "graph-L").endswith(os.path.join(PID, "graph-L.json")):
        f.append("project_id 없는 저장 경로가 %s 폴더가 아님" % PID)
    return f


def main():
    safe_console()
    tmp = tempfile.mkdtemp(prefix="hazop_project_kg_")
    old = os.environ.get(paths.ENV_WORK_ROOT)
    os.environ[paths.ENV_WORK_ROOT] = tmp
    failures = []
    try:
        graphs = check_study_nodes.build_graphs(tmp)
        pg = project.build(PID, graphs)
        s = project.summary(pg)
        failures += check_links(graphs, pg, s)
        f, nodes, cov, cross = check_study(pg)
        failures += f
        f, p = check_query(pg, nodes)
        failures += f
        failures += check_ai(graphs, pg, cross)
        failures += check_manual(graphs, pg)
        failures += check_legacy(tmp)
        per_sheet = sum(len(project.components(g)) for g in graphs)
        print("== 도면 %d장, 연결점 %d개" % (s["sheets"], s["continuations"]))
        print("   연결 매칭: 짝 %d, 미연결 %s, 방향 모순 %d" % (s["linked"], s["unlinked"], s["direction_conflicts"]))
        for l in pg["sheet_links"]:
            print("   %-8s %-22s %s %s → %s" % (l["status"], l["reason"] or "-", l["from"]["line_no"],
                                              l["from"]["drawing_number"], (l["to"] or {}).get("drawing_number") or
                                              l["from"]["to_drawing"]))
        print("   물리 연결 성분: 도면별 합 %d → 프로젝트 %d (전체 관계 기준 %d, 도면을 넘는 성분 %d)"
              % (per_sheet, s["physical_components"], s["all_components"], s["cross_sheet_components"]))
        print("   검토구간: 프로젝트 %d개(도면별 합 %d), 도면을 넘는 구간 %d개, 덮음률 %d/%d"
              % (len(nodes["nodes"]), sum(len(sn.propose(g, at=AT)["nodes"]) for g in graphs), len(cross),
                 cov["covered"], cov["total"]))
        for n in cross:
            print("     %s %s — %s" % (n["node_id"], n["name"], ", ".join(
                x[len("graph-"):] for x in project.sheets_of(pg, n["members"]))))
        print("   경로 RC-PZ01 → SI-TK01: %d단계, 도면 %s" % (
            p["ignoring_direction"].get("length", -1),
            project.sheets_of(pg, [x["entity_id"] for x in p["ignoring_direction"].get("nodes", [])])))
    finally:
        if old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = old
        shutil.rmtree(tmp, ignore_errors=True)
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for x in failures:
        print("  -", x)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
