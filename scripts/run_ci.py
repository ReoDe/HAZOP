"""CI 진입점. 워크플로는 이 파일 하나만 부르고, 무엇을 돌릴지는 여기서 정한다(이름 이전 때 고칠 곳을 한 곳으로 모은다).

  python scripts/run_ci.py              # unittest 전체 + 화면 없는 검사 스크립트(CHECKS)
  python scripts/run_ci.py --diagnose   # 러너 진단 줄(글꼴, 드라이브, 판 번호)만 찍는다

하나가 실패해도 끝까지 돌리고, 실패가 하나라도 있으면 종료 코드 1이다.
요약 표는 $GITHUB_STEP_SUMMARY에 덧붙인다. 그 변수가 없으면 표준 출력에 찍는다.
"""

import argparse
import collections
import os
import platform
import subprocess
import sys
import tempfile
import time
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHECKS = (
    "check_adapter",
    "check_compare",
    "check_corrections",
    "check_export",
    "check_kg_context",
    "check_review",
    "check_study_nodes",
    "check_symbols",
    "check_version_migration",
    "check_snp_baseline",
    "check_layout",        # 정리된 보기 정돈: SNP 6장 모두 0, APR1400 표본 2쪽 이어짐·겹침
    "check_read_quality",  # DCD 원본이 없는 CI에서는 SNP 쪽만 잰다
)

NOT_IN_CI = {
    "check_analysis": "작업 루트의 git 제외 데이터(data/regions)가 필요하다. 리허설 2026-11-10 rc=1",
    "check_expect": "작업 루트에 추출한 도면(output/graph)이 있어야 한다. 리허설 2026-11-10 rc=1",
    "check_kg": "작업 루트의 git 제외 데이터(data/knowledge-graph)가 필요하다. 리허설 2026-11-10 rc=1",
    "check_kg_algo": "작업 루트의 git 제외 데이터(data/knowledge-graph)가 필요하다. 리허설 2026-11-10 rc=1",
    "check_work_root_counts": "저장소 밖 작업 루트 사본이 있어야 한다. 이름 이전 전후에 손으로 돌린다",
    "check_contract": "작업 루트의 output/analysis가 있어야 한다. 리허설 2026-11-10 rc=2",
    "check_extract": "안에서 unittest 전체를 다시 돈다(리허설 394초). unittest를 끄는 옵션이 생기면 넣는다",
    "check_graph": "안에서 unittest 전체를 다시 돈다(리허설 332초)",
    "check_register": "안에서 unittest 전체를 다시 돈다(리허설 334초)",
    "check_viewer": "안에서 unittest 전체를 다시 돈다(리허설 334초)",
    "check_app": "QtWebEngine 화면. 러너에서 뜨는지 확인한 뒤 둘째 단계에 넣는다",
    "check_edit_screen": "QtWebEngine 화면. 둘째 단계",
    "check_kg_link": "QtWebEngine 화면. 둘째 단계",
    "check_kg_renderer": "QtWebEngine 화면. 둘째 단계",
    "check_kg_screen": "QtWebEngine 화면. 둘째 단계",
    "check_design": "하위 프로세스 렌더. 둘째 단계",
    "check_user_scenarios": "실제 데스크톱이 필요하다",
    "check_desktop_support": "실제 데스크톱이 필요하다",
    "check_apr1400": "저장소 밖 DCD 원본이 필요하다",
    "check_project_kg": "저장소 밖 DCD 원본이 필요하다",
    "check_cli_live": "실제 Claude CLI를 부른다",
    "check_ai_analysis": "실제 Claude를 부른다",
}

CHECK_TIMEOUT_S = 900
MALGUN = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "malgun.ttf")


def check_path(name):
    return os.path.join(REPO_ROOT, "scripts", name + ".py")


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def run_unittests():
    suite = unittest.defaultTestLoader.discover(os.path.join(REPO_ROOT, "tests"), top_level_dir=REPO_ROOT)
    result = unittest.TextTestResult(unittest.runner._WritelnDecorator(sys.stderr), True, 1)
    modules = []
    result.startTestRun()
    for module_suite in suite:
        if not module_suite.countTestCases():
            continue
        name = next(t.id().rsplit(".", 2)[0] for t in _iter_tests(module_suite))
        print("\n[모듈 시작] %s" % name, flush=True)
        before = (result.testsRun, len(result.failures) + len(result.errors), len(result.skipped))
        start = time.perf_counter()
        module_suite.run(result)
        took = time.perf_counter() - start
        after = (result.testsRun, len(result.failures) + len(result.errors), len(result.skipped))
        row = (name, after[0] - before[0], after[1] - before[1], after[2] - before[2], took)
        modules.append(row)
        print("\n[모듈 끝] %s 시험 %d, 실패 %d, 건너뜀 %d, %.1f초" % row, flush=True)
    result.stopTestRun()
    result.printErrors()
    return result, modules


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def run_checks():
    rows = []
    for name in CHECKS:
        print("\n=== %s" % name, flush=True)
        start = time.perf_counter()
        try:
            rc = subprocess.run([sys.executable, check_path(name)], cwd=REPO_ROOT, timeout=CHECK_TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            rc = "제한 시간 초과(%d초)" % CHECK_TIMEOUT_S
        rows.append((name, rc, time.perf_counter() - start))
        print("=== %s rc=%s %.1f초" % rows[-1], flush=True)
    return rows


def diagnose_lines():
    try:
        import PySide6
        pyside = PySide6.__version__
    except ImportError:
        pyside = "없음"
    return [
        "Python %s (%s)" % (platform.python_version(), platform.platform()),
        "PySide6 %s" % pyside,
        "맑은 고딕(malgun.ttf): %s" % ("있음" if os.path.isfile(MALGUN) else "없음"),
        "임시 폴더 드라이브: %s" % (os.path.splitdrive(tempfile.gettempdir())[0] or "-"),
        "작업 디렉터리 드라이브: %s" % (os.path.splitdrive(os.getcwd())[0] or "-"),
        "작업 루트 드라이브: %s" % (os.path.splitdrive(os.environ.get("HAZOP_WORK_ROOT", ""))[0] or "(지정 안 됨)"),
    ]


def summary_markdown(result, modules, checks, timings):
    lines = ["## 시험 요약", ""]
    lines.append("시험 %d, 실패 %d, 오류 %d, 건너뜀 %d, 예상 밖 통과 %d" % (
        result.testsRun, len(result.failures), len(result.errors), len(result.skipped),
        len(result.unexpectedSuccesses)))
    if not result.testsRun:
        lines += ["", "**시험을 하나도 찾지 못했다. 실패로 친다.**"]
    lines += ["", "### 건너뛴 이유", "", "| 이유 | 수 |", "| --- | --- |"]
    for reason, count in collections.Counter(r for _, r in result.skipped).most_common():
        lines.append("| %s | %d |" % (_cell(reason), count))
    bad = [t.id() for t, _ in result.failures + result.errors] + [t.id() for t in result.unexpectedSuccesses]
    if bad:
        lines += ["", "### 실패·오류 시험", ""] + ["- `%s`" % b for b in bad]
    lines += ["", "### 오래 걸린 시험 모듈 (상위 10)", "", "| 모듈 | 시험 | 초 |", "| --- | --- | --- |"]
    for name, n, _, _, took in sorted(modules, key=lambda m: -m[4])[:10]:
        lines.append("| %s | %d | %.1f |" % (name, n, took))
    lines += ["", "### 검사 스크립트", "", "| 스크립트 | rc | 초 |", "| --- | --- | --- |"]
    for name, rc, took in checks:
        lines.append("| %s | %s | %.1f |" % (name, _cell(rc), took))
    lines += ["", "### 단계별 시간", ""] + ["- %s: %.1f초" % kv for kv in timings]
    lines += ["", "### 진단", ""] + ["- %s" % d for d in diagnose_lines()]
    return "\n".join(lines) + "\n"


def write_summary(text):
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(text)
    print("\n" + text, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diagnose", action="store_true", help="진단 줄만 찍고 끝낸다")
    args = ap.parse_args(argv)
    if args.diagnose:
        print("\n".join(diagnose_lines()))
        return 0
    os.chdir(REPO_ROOT)
    start = time.perf_counter()
    result, modules = run_unittests()
    unit_s = time.perf_counter() - start
    checks = run_checks()
    timings = [("unittest", unit_s), ("검사 스크립트", time.perf_counter() - start - unit_s)]
    write_summary(summary_markdown(result, modules, checks, timings))
    failed = not result.testsRun or not result.wasSuccessful() or any(rc != 0 for _, rc, _ in checks)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
