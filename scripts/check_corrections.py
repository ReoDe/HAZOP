"""② 도면 사람 수정 기록 검사 (QA용). 근거: drawing-edit-spec(2026-11-07) 수정 기록 레이어.

1) 동작 검사: tests/test_corrections.py 전부(임시 작업 루트에서 연산별 효과, 적용 불가 건너뛰기, 저장·다시 읽기,
   다시 추출 뒤 유지, 원본 extraction.json 불변, 태그 중복, 그래프·지식그래프 재빌드와 ④·⑤ 재확인 안내).
2) PDF 시연: 참고자료의 PDF 샘플 하나를 메모리에서 추출하고, 검토자가 할 수정(양 끝이 정해진 물리 배관은
   끝점 순서대로 set_flow, 끝점이 없는 배관의 흐름 방향 미확인은 confirm)을 적용해 미확인 비율 전후를 출력한다.
   저장소의 출력/·데이터/에 쓰지 않는다. --out <md>를 주면 시연 표를 쓴다.
종료 코드 0 = 전부 통과.
"""

import argparse
import glob
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402

from hazop.extract import corrections  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
from hazop.graph import build  # noqa: E402

SAMPLE_GLOB = paths.folder("참고", "pid-samples", "*", "*.pdf")
FLOW = "unknown_flow_direction"


def behaviour_checks():
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_corrections")
    ids = [t.id() for t in _tests(suite)]  # 실행한 뒤에는 묶음이 테스트를 비운다
    result = unittest.TestResult()
    suite.run(result)
    bad = {t.id(): msg for t, msg in result.failures + result.errors}
    failures = []
    for i in ids:
        print("%s %s" % ("실패" if i in bad else "통과", i.rsplit(".", 1)[-1]))
        if i in bad:
            failures.append("%s: %s" % (i, bad[i].strip().splitlines()[-1]))
    if result.testsRun == 0 or result.skipped:
        failures.append("동작 검사 실행 %d건, 건너뜀 %d건" % (result.testsRun, len(result.skipped)))
    return failures


def _tests(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _tests(t)
        else:
            yield t


def reviewer_ops(ext):
    """흐름 방향 미확인마다 검토자가 할 수정. 양 끝이 서로 다른 노드인 정상 관계는 set_flow, 아니면 confirm."""
    rels = {r["local_id"]: (r, key == "relations") for key in ("relations", "unresolved_connectors") for r in ext[key]}
    ops = []
    for u in ext["validation"]["unknowns"]:
        if u["check"] != FLOW or u.get("target") not in rels:
            continue
        rel, resolved = rels[u["target"]]
        ends = [ep["source_object_id"] for ep in rel["endpoints"]]
        op_id = "c-%04d" % (len(ops) + 1)
        if resolved and ends[0] != ends[1]:
            ops.append(corrections.make_op(ext, "set_flow", rel["source_object_id"], {"from": ends[0], "to": ends[1]},
                                           "검사", op_id=op_id))
        else:
            ops.append(corrections.make_op(ext, "confirm", rel["source_object_id"], {"items": [{"check": FLOW, "reason": u.get("reason") or ""}]}, "검사",
                                           op_id=op_id))
    return ops


def pdf_demo():
    pdfs = sorted(glob.glob(SAMPLE_GLOB))
    if not pdfs:
        return ["PDF 샘플 없음: %s" % SAMPLE_GLOB], None
    pdf = pdfs[0]
    name = os.path.basename(os.path.dirname(pdf))
    ext = pdf_vector.extract(pdf, repo_root=REPO_ROOT)
    ops = reviewer_ops(ext)
    out = corrections.apply(ext, ops)
    graph = build.build_graph(out)
    count = {k: sum(o["op"] == k for o in ops) for k in ("set_flow", "confirm")}
    row = {"name": name, "objects": len(ext["nodes"]) + len(ext["relations"]) + len(ext["unresolved_connectors"]),
           "unknowns_before": len(ext["validation"]["unknowns"]), "unknowns_after": len(out["validation"]["unknowns"]),
           "ratio_before": corrections.unknown_ratio(ext), "ratio_after": corrections.unknown_ratio(out),
           "flow_unknowns": sum(u["check"] == FLOW for u in ext["validation"]["unknowns"]),
           "set_flow": count["set_flow"], "confirm": count["confirm"],
           "not_applicable": len(out["corrections"]["not_applicable"]),
           "resolved": out["corrections"]["resolved_unknowns"], "graph_status": graph["validation"]["status"]}
    print("PDF 시연 %s: 대상 %d, 미확인 %d → %d, 비율 %.3f → %.3f (흐름 미확인 %d: set_flow %d, confirm %d, 적용 불가 %d)"
          % (name, row["objects"], row["unknowns_before"], row["unknowns_after"], row["ratio_before"],
             row["ratio_after"], row["flow_unknowns"], row["set_flow"], row["confirm"], row["not_applicable"]))
    failures = []
    if not ops:
        failures.append("%s: 흐름 방향 미확인이 없어 시연할 수정이 없음" % name)
    if row["not_applicable"]:
        failures.append("%s: 적용 불가 %s" % (name, out["corrections"]["not_applicable"][:3]))
    if row["resolved"] != row["flow_unknowns"] or row["ratio_after"] >= row["ratio_before"]:
        failures.append("%s: 흐름 방향 미확인이 모두 지워지지 않음(%d/%d)" % (name, row["resolved"], row["flow_unknowns"]))
    if row["graph_status"] != "passed":
        failures.append("%s: 고친 추출의 그래프 구조 검증 %s" % (name, row["graph_status"]))
    return failures, row


def demo_table(row):
    return ("| 도면 | 대상(노드+관계+미해결) | 미확인 전 → 후 | 미확인 비율 전 → 후 | 흐름 미확인 | set_flow | confirm "
            "| 적용 불가 | 고친 그래프 |\n|---|---|---|---|---|---|---|---|---|\n"
            "| %(name)s | %(objects)d | %(unknowns_before)d → %(unknowns_after)d | %(ratio_before).3f → %(ratio_after).3f "
            "| %(flow_unknowns)d | %(set_flow)d | %(confirm)d | %(not_applicable)d | %(graph_status)s |\n" % row)


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="PDF 시연 표를 쓸 Markdown 파일")
    args = ap.parse_args(argv)
    failures = behaviour_checks()
    demo_failures, row = pdf_demo()
    failures += demo_failures
    if args.out and row:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(demo_table(row))
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for x in failures:
        print("  -", x)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
