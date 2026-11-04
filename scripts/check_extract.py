"""단계 ① 추출 검사를 한 번에 실행한다 (QA용).

1) 샘플 6개 추출 -> 출력/추출/<도면번호>/
2) 결과 파일 구조 확인 (필수 키, 차단 오류 0, SVG offset 일관성)
3) tests/ 아래 unittest 전체 실행
종료 코드 0 = 전부 통과.
"""

import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

import extract_drawio  # noqa: E402

REQUIRED_KEYS = ["schema_version", "extraction_run_id", "run", "source", "source_context", "drawing",
                 "coordinate_system", "nodes", "relations", "unresolved_connectors", "texts",
                 "unclassified", "source_locations", "validation", "summary"]
EXPECTED_SAMPLES = 6


def main():
    safe_console()
    failures = []
    print("== 1. 샘플 추출")
    rc = extract_drawio.main(["--samples"])
    if rc != 0:
        failures.append("추출 중 blocked 결과 있음")

    print("== 2. 결과 파일 확인")
    out_root = extract_drawio.DEFAULT_OUT
    dirs = sorted(d for d in os.listdir(out_root) if os.path.isdir(os.path.join(out_root, d)))
    if len(dirs) < EXPECTED_SAMPLES:
        failures.append("출력 폴더 수 %d < %d" % (len(dirs), EXPECTED_SAMPLES))
    for d in dirs:
        base = os.path.join(out_root, d)
        for fname in ("extraction.json", "validation_report.md"):
            if not os.path.isfile(os.path.join(base, fname)):
                failures.append("%s/%s 없음" % (d, fname))
        if not os.path.isfile(os.path.join(base, "extraction.json")):
            continue
        with open(os.path.join(base, "extraction.json"), encoding="utf-8") as fh:
            r = json.load(fh)
        missing = [k for k in REQUIRED_KEYS if k not in r]
        if missing:
            failures.append("%s: 필수 키 누락 %s" % (d, missing))
        if r["validation"]["blockers"]:
            failures.append("%s: 차단 오류 %d" % (d, len(r["validation"]["blockers"])))
        al = r["coordinate_system"]["svg_alignment"]
        if not al or al["status"] != "verified":
            failures.append("%s: SVG 좌표 정렬 미검증 %s" % (d, al and al["reasons"]))
        located = {loc["object_id"] for loc in r["source_locations"]}
        for n in r["nodes"] + r["relations"]:
            if n["source_object_id"] not in located:
                failures.append("%s: bbox 없음 %s" % (d, n["source_object_id"]))
        print("  %s: ok=%s" % (d, not any(f.startswith(d) for f in failures)))

    print("== 3. unittest")
    suite = unittest.defaultTestLoader.discover(os.path.join(REPO_ROOT, "tests"), top_level_dir=REPO_ROOT)
    outcome = unittest.TextTestRunner(verbosity=1).run(suite)
    if not outcome.wasSuccessful():
        failures.append("unittest 실패 (failures %d, errors %d)"
                        % (len(outcome.failures), len(outcome.errors)))

    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
