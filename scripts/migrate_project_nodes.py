"""도면별 검토구간·⑤ 결과 -> 프로젝트 전체 검토구간·결과 이전(옛 파일은 그대로 둔다).

  python scripts/migrate_project_nodes.py SNP-SAMPLE            # 미리보기: 대응표와 옮길 항목 수만 출력
  python scripts/migrate_project_nodes.py SNP-SAMPLE --write    # 새 파일 쓰기

- 프로젝트 집합: 저장본이 있으면 그것에, 없으면 새 제안에 legacy_ids를 붙인다(상태·구성요소는 바꾸지 않음).
- 대응 없는 옛 구간·칸·편차가 있으면 아무것도 쓰지 않고 멈춘다.
- 프로젝트 결과: 이미 있으면 덮어쓰지 않고 멈춘다(사람이 검토한 프로젝트 결과 보호). 확인과 저장 사이에 다른
  실행이 끼어드는 경우는 막지 않는다(한 사람이 손으로 돌리는 도구). 항목 상태는 그대로이고
  범위가 바뀐 구간에서 온 항목에는 scope_changed가 붙는다. 결과의 study_nodes_ref는 이전한 집합 기준이라,
  프로젝트 집합을 확정한 뒤에 이전해야 ⑤에서 '재확인 필요'로 보이지 않는다.
종료 코드 0 = 성공(미리보기 포함), 1 = 멈춤·오류.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop.graph import project  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from hazop.study import span  # noqa: E402


def plan(project_id, at=None):
    pg = project.load(project_id)
    sheets, problem = sn.exclusion_for(pg)
    if problem:
        raise SystemExit(problem)  # 표시를 못 읽은 채 뺀 도면까지 제안해 옮기지 않는다(앱의 이전과 같은 규칙)
    pset = sn.load(pg) or sn.propose(pg, at=at, exclude_sheets=sheets)
    old_sets, old_results = [], []
    for s in pg["sheets"]:
        sheet_graph = {"graph_id": s["graph_id"], "project_id": None if project_id == project.UNREGISTERED_PROJECT
                       else project_id}
        old = sn.load(sheet_graph)
        if old:
            old_sets.append(old)
            r = res.load(old)
            if r:
                old_results.append(r)
    return pg, pset, old_sets, old_results


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    pg, pset, old_sets, old_results = plan(a.project_id)
    mapping = span.legacy_map(old_sets, pset, pg)
    for k, v in sorted(mapping.items()):
        print("%-28s -> %-4s %s%s" % (k, v["node_id"], "같은 범위" if v["exact"] else "범위 바뀜",
                                       "" if len(v["overlap"]) < 2 else " (겹침 %s)" % ", ".join(v["overlap"])))
    out, report = span.migrate_results(old_results, old_sets, pset, res.load_deviations(), pg)
    print("옮길 항목 %d(사람 검토 %d, 범위 바뀜 %d, 옛 결과가 이미 재확인 필요 %d)" % (
        report["moved_entries"], report["human_entries"], report["scope_changed_entries"], report["stale_entries"]))
    stop = span.blocked(report)
    if stop:
        print("멈춤: 대응 없는 옛 자료 %s" % {k: report[k][:5] for k in stop})
        return 1
    if not a.write:
        print("미리보기만 함(--write로 씀)")
        return 0
    if pset.get("status") != "confirmed":
        print("멈춤: 프로젝트 검토구간이 확정되지 않음 — ④에서 확정한 뒤 이전(확정 전 결과는 확정 때 무효가 됨)")
        return 1
    if os.path.isfile(res.store_path(pset["project_id"], pset["graph_id"])):
        print("멈춤: 프로젝트 결과가 이미 있음 — 덮어쓰지 않음")
        return 1
    print(sn.save(span.migrate_set(old_sets, pset, pg)))
    print(res.save(out, pset["project_id"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
