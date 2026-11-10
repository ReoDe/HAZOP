"""④ 검토구간 자동 제안 검사 (QA용). 근거: 3단계 명세 §B nodes.py.

샘플 도면 전부를 임시 폴더에서 새로 추출·빌드한 그래프로 확인한다(저장소의 output/·data/에 쓰지 않음).
도면마다: 덮음률 100%, 남긴 구간당 분할 가중 요소(밸브·펌프) ≤ 5, 같은 입력 → 같은 출력,
병합·분할·확정·저장·읽기 왕복, 미포함 구성요소가 있으면 확정 거부, 구성요소가 바뀐 그래프 판은 stale 감지,
구성요소가 같고 판만 바뀌면 확정을 판 이전(U10).
종료 코드 0 = 전부 통과.
"""

import copy
import glob
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.study import nodes as sn, segment  # noqa: E402

AT = "2026-11-07T00:00:00Z"


def build_graphs(tmp):
    import extract_drawio
    out = []
    for path in sorted(glob.glob(extract_drawio.SAMPLE_GLOB)):
        ex, _ = extract_drawio.run_one(path, os.path.join(tmp, "extract"))
        out.append(build.build_graph(ex))
    return out


def check_proposal(g, s):
    f = []
    by = {n["entity_id"]: n for n in g["nodes"]}
    cov = sn.coverage(s, g)
    if cov["uncovered"]:
        f.append("미포함 %d개 %s" % (len(cov["uncovered"]), cov["uncovered"][:5]))
    for n in s["nodes"]:
        active = sum(segment.traits(by[m]).weighted for m in n["members"] if m in by)
        if n["screen"]["status"] != "excluded" and active > segment.MAX_ACTIVE:
            f.append("%s 분할 가중 요소 %d개 > %d" % (n["node_id"], active, segment.MAX_ACTIVE))
        if not n["members"] or n["members"] != sorted(set(n["members"])):
            f.append("%s members가 비었거나 정렬·중복 위반" % n["node_id"])
    if [n["node_id"] for n in s["nodes"]] != ["S%d" % i for i in range(1, len(s["nodes"]) + 1)]:
        f.append("node_id가 S1..Sn이 아님")
    shuffled = copy.deepcopy(g)
    shuffled["nodes"].reverse()
    shuffled["edges"].reverse()
    if sn.propose(g, at=AT) != s or sn.propose(shuffled, at=AT) != s:
        f.append("같은 입력에 다른 제안")
    return f, cov


def check_round_trip(g, s):
    f = []
    if len(s["nodes"]) >= 2:
        a, b = s["nodes"][0]["node_id"], s["nodes"][1]["node_id"]
        merged = sn.merge(s, [a, b], at=AT)
        moved = s["nodes"][1]["members"]
        if set(sn.nodes_of(merged, moved[0])) != {a}:
            f.append("병합 뒤 nodes_of가 병합 구간을 가리키지 않음")
        s = sn.split(merged, a, moved, at=AT)
        if sn.coverage(s, g)["uncovered"]:
            f.append("병합·분할 뒤 미포함 발생")
    multi = next((n for n in s["nodes"] if len(n["members"]) >= 2
                  and len(sn.nodes_of(s, n["members"][0])) == 1), None)
    if multi:
        dropped = sn.remove_member(s, multi["node_id"], multi["members"][0], at=AT)
        try:
            sn.confirm(dropped, g, "검사", at=AT)
            f.append("미포함 구성요소가 있는데 확정됨")
        except ValueError:
            pass
    done = sn.confirm(s, g, "검사", at=AT)
    sn.save(done)
    loaded = sn.load(g)
    if loaded != done:
        f.append("저장·읽기 왕복 불일치")
    if not sn.any_confirmed():
        f.append("any_confirmed가 False")
    changed = copy.deepcopy(g)
    changed["graph_version"] += "-changed"
    changed["nodes"][0]["source_object_id"] = "gone-%s" % changed["nodes"][0]["source_object_id"]
    if not sn.is_stale(sn.load(changed), changed):
        f.append("구성요소가 바뀐 그래프 판을 stale로 감지하지 못함")
    newer = dict(g, graph_version=g["graph_version"] + "-new")
    moved = sn.load(newer)
    if sn.is_stale(moved, newer) or moved["history"][-1]["op"] != "migrate_version" or moved["status"] != "confirmed":
        f.append("구성요소가 같은 그래프 판 변경에서 확정을 판 이전하지 못함")
    try:
        sn.confirm(sn.reopen(loaded, at=AT), newer, "검사", at=AT)
        f.append("판이 바뀐 그래프로 확정됨")
    except ValueError:
        pass
    return f


def main():
    safe_console()
    tmp = tempfile.mkdtemp(prefix="hazop-study-")
    old = os.environ.get(paths.ENV_WORK_ROOT)
    os.environ[paths.ENV_WORK_ROOT] = tmp
    failures = []
    try:
        graphs = build_graphs(tmp)
        if len(graphs) < 6:
            failures.append("샘플 도면 %d개 < 6" % len(graphs))
        print("%-12s %10s %6s %14s" % ("drawing", "components", "nodes", "covered/total"))
        for g in graphs:
            name = g["source"]["drawing_number"] or g["graph_id"]
            s = sn.propose(g, at=AT)
            f, cov = check_proposal(g, s)
            f += check_round_trip(g, s)
            print("%-12s %10d %6d %14s %s" % (name, len(g["nodes"]), len(s["nodes"]),
                                             "%d/%d" % (cov["covered"], cov["total"]), "OK" if not f else "FAIL"))
            failures += ["%s: %s" % (name, x) for x in f]
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
