"""CI 진입점. 워크플로는 이 파일 하나만 부르고, 무엇을 돌릴지는 여기서 정한다(이름 이전 때 고칠 곳을 한 곳으로 모은다).

  python scripts/run_ci.py              # unittest 전체 + 화면 없는 검사 스크립트(CHECKS)
  python scripts/run_ci.py --diagnose   # 러너 진단 줄(글꼴, 드라이브, 판 번호)만 찍는다

하나가 실패해도 끝까지 돌리고, 실패가 하나라도 있으면 종료 코드 1이다.
시험 모듈 하나가 한도(MODULE_TIMEOUT_S, 환경변수 HAZOP_CI_MODULE_TIMEOUT_S)를 넘기면 멈춘 것으로 보고 모든 스레드의 호출 자리를 적은 뒤 앱 이벤트 루프를 끝내
그 모듈을 실패로 적고 다음으로 간다. 그래도 풀리지 않으면(60초) 지금까지의 요약을 적고 검사 스크립트 단계만 따로 돌린 뒤 이 프로세스와 자식을 정리하고 끝낸다.
요약 표는 $GITHUB_STEP_SUMMARY에 덧붙인다. 그 변수가 없으면 표준 출력에 찍는다.
"""

import argparse
import collections
import faulthandler
import os
import platform
import subprocess
import sys
import tempfile
import threading
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
    "check_shell_scenarios": "QtWebEngine 새 화면을 띄우고 --out이 필요하다(둘째 단계). 지금은 알려진 결함 N10(표제란 미확정 도면이 있으면 Excel 내보내기가 멈춤) 때문에 rc 1",
    "check_desktop_support": "실제 데스크톱이 필요하다",
    "check_apr1400": "저장소 밖 DCD 원본이 필요하다",
    "check_project_kg": "저장소 밖 DCD 원본이 필요하다",
    "check_cli_live": "실제 Claude CLI를 부른다",
    "check_ai_analysis": "실제 Claude를 부른다",
    "check_scan_quality": "스캔 읽기 venv(OpenCV·OCR, 결정 D7)가 있어야 하고 쪽마다 20~60초가 걸린다. 러너에는 그 venv가 없다",
}

CHECK_TIMEOUT_S = 900
MODULE_TIMEOUT_S = int(os.environ.get("HAZOP_CI_MODULE_TIMEOUT_S") or 1200)      # 시험 모듈 하나의 한도(가장 오래 걸리는 모듈이 약 5분이다)
MODULE_GRACE_S = 60                                                                # 한도 뒤 이벤트 루프를 끝낸 다음 풀리기를 기다리는 시간
MALGUN = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "malgun.ttf")


def check_path(name):
    return os.path.join(REPO_ROOT, "scripts", name + ".py")


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _quit_qt():
    """앱 이벤트 루프를 어느 스레드에서든 안전하게 끝낸다(창이 떠서 닫히지 않는 시험이 run_ci 전체를 세우던 일을 푼다)."""
    try:
        from PySide6.QtCore import QCoreApplication, QMetaObject, Qt
        app = QCoreApplication.instance()
        if app is not None:
            QMetaObject.invokeMethod(app, "quit", Qt.QueuedConnection)
    except Exception:  # noqa: BLE001 - 끝내지 못해도 다음 단계(강제 종료)가 있다
        pass


def _timeout_failure(result, name, limit):
    """시간 초과를 이름 있는 실패 시험 하나로 남긴다."""
    class ModuleTimeout(unittest.TestCase):
        def runTest(self):
            pass
    case = ModuleTimeout()
    case.id = lambda: "%s.모듈 시간 초과" % name
    result.addFailure(case, (AssertionError, AssertionError("시험 모듈이 %d초를 넘겨 멈춘 것으로 보고 끝냈다" % limit), None))


class ModuleWatch:
    """시험 모듈 하나의 시간 한도. 넘기면 호출 자리를 적고 이벤트 루프를 끝내며, 그래도 안 풀리면 force(name)를 부른다.
    모듈이 끝나 cancel()을 부른 뒤에는 어느 타이머도 더는 아무것도 하지 않는다(끝나는 순간과 한도가 겹쳐도 강제 종료가 뒤늦게 나가지 않게 잠금으로 막는다)."""

    def __init__(self, name, limit, force, grace=None):
        self.name, self.limit, self.force = name, limit, force
        self.grace = MODULE_GRACE_S if grace is None else grace
        self.fired = False
        self._cancelled = False
        self._lock = threading.Lock()
        self._timers = []

    def _start(self, seconds, fn):
        with self._lock:
            if self._cancelled:
                return
            timer = threading.Timer(seconds, fn)
            timer.daemon = True
            self._timers.append(timer)
            timer.start()

    def start(self):
        self._start(self.limit, self._fire)
        return self

    def _fire(self):
        with self._lock:
            if self._cancelled:
                return
            self.fired = True
        print("\n[모듈 시간 초과] %s: %d초를 넘겨 멈춘 것으로 보고 앱 이벤트 루프를 끝낸다. 아래는 그때 모든 스레드의 호출 자리다." % (self.name, self.limit), flush=True)
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        self._start(self.grace, self._force)          # 이벤트 루프를 끝내기 전에 둘째 타이머를 건다
        _quit_qt()

    def _force(self):
        with self._lock:
            if self._cancelled:
                return
        self.force(self.name)

    def cancel(self):
        with self._lock:
            self._cancelled = True
            for timer in self._timers:
                timer.cancel()


def _force_finish(name, result, modules, limit):
    """이벤트 루프를 끝내도 풀리지 않을 때: 지금까지의 요약을 적고 검사 스크립트 단계만 따로 돌린 뒤 이 프로세스와 자식을 정리하고 끝낸다."""
    print("\n[모듈 강제 종료] %s: 풀리지 않아 지금까지의 결과를 적고 검사 스크립트만 따로 돌린 뒤 끝낸다." % name, flush=True)
    _timeout_failure(result, name, limit)
    modules.append((name, 0, 1, 0, float(limit)))
    rc = subprocess.run([sys.executable, os.path.abspath(__file__), "--checks-only"], cwd=REPO_ROOT).returncode
    write_summary(summary_markdown(result, modules, [], [("unittest", float(limit)), ("검사 스크립트(따로)", 0.0)]))
    print("검사 스크립트 단계 종료 코드 %s. 멈춘 모듈이 있어 실패로 끝낸다." % rc, flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os._exit(1)


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
        watch = ModuleWatch(name, MODULE_TIMEOUT_S, lambda n: _force_finish(n, result, modules, MODULE_TIMEOUT_S)).start()
        try:
            module_suite.run(result)
        finally:
            watch.cancel()
        if watch.fired:                    # 이벤트 루프를 끝내서 풀린 경우: 그 모듈을 실패로 적고 다음으로 간다
            _timeout_failure(result, name, MODULE_TIMEOUT_S)
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
    ap.add_argument("--checks-only", action="store_true", help="시험은 건너뛰고 검사 스크립트만 돌린다(멈춘 모듈 뒤에 이어 돌리는 길)")
    args = ap.parse_args(argv)
    if args.diagnose:
        print("\n".join(diagnose_lines()))
        return 0
    os.chdir(REPO_ROOT)
    if args.checks_only:
        checks = run_checks()
        return 1 if any(rc != 0 for _, rc, _ in checks) else 0
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
