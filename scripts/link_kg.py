"""엔티티 연결 후보 생성·일괄 확인·확인 반영 (기획서/그래프활용.md §3.1·§3.2, §8.2 D6).

  python scripts/link_kg.py candidates SNP-SAMPLE --graph-id graph-SNP-M-102
      데이터/지식/<project_id>/knowledge_nodes.csv의 문서 조각 -> link_candidates.csv(재실행 시 사람 판단 보존)
  python scripts/link_kg.py confirm-exact SNP-SAMPLE --graph-id graph-SNP-M-102 --reviewer 이름 --reason 사유 [--reviewed-at YYYY-MM-DD]
      정확 일치·비모호 후보 일괄 확인(검토자·사유 필수, 조건은 원문·그래프로 다시 계산해 판단).
      유사·모호·재확인(previous_status 있음) 후보는 CSV에서 한 건씩 판단
  python scripts/link_kg.py apply SNP-SAMPLE --graph-id graph-SNP-M-102
      confirmed 후보만 knowledge_links.csv에 mentions 행으로 추가(두 번 반영해도 행이 늘지 않음). 그 뒤 build_kg.py로 재빌드

--graph-id: 이 프로젝트의 P&ID 그래프(반복 지정). 프로젝트-도면 대응표가 아직 없으므로 사람이 지정한다.
종료 코드: 0 = 정상, 1 = 반영은 했지만 사람이 고칠 항목 있음(기각했는데 knowledge_links.csv에 이미 있는 관계),
2 = 입력 오류(CSV 열 규격, 판단 열 오류, 확인 행 열 조작, 그래프 없음 등).
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

import build_kg  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.kg import link  # noqa: E402


def select_graphs(graph_root, graph_ids):
    graphs = {g["graph_id"]: g for g in build_kg.load_graphs(graph_root)}
    missing = [g for g in graph_ids if g not in graphs]
    if missing:
        raise link.LinkError("P&ID 그래프가 없음: %s (먼저 build_graph.py)" % ", ".join(missing))
    return [graphs[g] for g in sorted(set(graph_ids))]


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("candidates", "confirm-exact", "apply"))
    ap.add_argument("project_id")
    ap.add_argument("--input-root", default=build_kg.DEFAULT_INPUT_ROOT)
    ap.add_argument("--graph-root", default=build_kg.DEFAULT_GRAPH_ROOT)
    ap.add_argument("--graph-id", action="append", default=[])
    ap.add_argument("--reviewer")
    ap.add_argument("--reason")
    ap.add_argument("--reviewed-at")
    args = ap.parse_args(argv)
    try:
        input_dir = paths.safe_join(args.input_root, args.project_id)
        if not args.graph_id:
            raise link.LinkError("--graph-id를 하나 이상 지정해야 함")
        graphs = select_graphs(args.graph_root, args.graph_id)
        if args.command == "confirm-exact":
            n = link.run_confirm_exact(input_dir, graphs, args.reviewer, args.reason, args.reviewed_at)
            print("정확 일치 후보 %d건 확인(검토자 %s)" % (n, args.reviewer))
        elif args.command == "candidates":
            res = link.run_generate(input_dir, graphs)
            rows = res["rows"]
            count = {s: sum(1 for r in rows if r["link_status"] == s) for s in link.LINK_STATUS}
            print("후보 %d행(이번 생성 %d, candidate %d, confirmed %d, rejected %d, 재확인 previous_status %d)"
                  % (len(rows), len(res["candidates"]), count["candidate"], count["confirmed"], count["rejected"],
                     sum(1 for r in rows if r["link_status"] == "candidate" and r["previous_status"])))
            for u in res["unmatched"]:
                print("  [도면에 없는 언급] %s %r @%d:%d" % (u["chunk_id"], u["match_text"], u["match_start"], u["match_end"]))
            for it in res["review_items"]:
                print("  [검토] %s %s %r: %s" % (it["check"], it["chunk_id"], it["match_text"], it["reason"]))
        else:
            res = link.run_apply(input_dir, graphs)
            print("반영: 추가 %d, 이미 있음 %d, 재확인 필요(키가 현재와 다름) %d"
                  % (len(res["add"]), len(res["skipped_existing"]), len(res["stale"])))
            for r in res["add"]:
                print("  + %s %s -> %s" % (r["id"], r["from"], r["to"]))
            for k in res["stale"]:
                print("  [재확인 필요] %s" % k)
            for k in res["rejected_but_linked"]:
                print("  [조치 필요] 기각했지만 knowledge_links.csv에 이미 있음: %s (관계 %s)" % (k, link.relation_id(k)))
                print("    도구는 행을 지우지 않음. knowledge_links.csv의 해당 행 link_status를 사람이 rejected로 고칠 것")
            if res["rejected_but_linked"]:
                return 1
    except (OSError, ValueError) as e:
        print("입력 오류:", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
