"""1366×768 배치 검사 (docs/2026-11-05-design-system 결정 D1, 작업 W2). 네트워크·AI 호출 없음.

메인 창을 화면에 띄우지 않고(WA_DontShowOnScreen) 상태별·화면별로 창 minimumSizeHint 폭·높이를 잰다.
- 상태: A 데이터 없음 → B 샘플 분석 실행 열림(tests/run_fixture 고정 응답) → C 검토 기록 있음(⑤ d12 저장 뒤 다시 열기).
  각 상태에서 화면 ①~⑤를 한 번씩 먼저 방문하고(⑤는 후보 선택) 다시 화면별로 잰다. 쌓인 화면(QStackedWidget)의
  최소 폭은 모든 화면의 최대값이고 ⑤는 첫 방문 때 문구를 채우므로, 이렇게 해야 최악값이 나온다.
- 화면마다 최소 폭에 기여하는 가장 넓은 말단 위젯 상위 N개(클래스·objectName·문구 앞부분·폭)를 함께 기록한다.
- 작업·저장 루트(HAZOP_WORK_ROOT·HAZOP_STORE_ROOT)와 설정 파일은 임시 폴더. 실제 자료저장소·출력/ 실행은 쓰지 않는다.

판정(D1):
- --platform windows, 배율 100%(DPR 1.0·96 DPI): 모든 측정에서 창 최소 폭 ≤ 1366, 높이 ≤ 768이면 통과(종료 코드 0),
  넘으면 1. 화면 배율이 100%가 아니면 기준 환경이 아니므로 2.
- --scale 1.25 등(QT_SCALE_FACTOR): 참고치. 물리 폭(논리 폭 × DPR)을 1366과 비교해 보여주기만 하고 종료 코드는 0.
- --platform offscreen: 글꼴 대체로 폭이 과대하므로 판정하지 않는다. --baseline <이전 결과 JSON>을 주면 늘어난 값만
  경고로 알린다(종료 코드 0). 기준 수치는 docs/2026-11-05-design-system/evidence/w2-1366기준.md에 기록한다.
결과 JSON: 출력/디자인검사/design-<platform>[-s<배율>].json (출력/는 git 제외). --out으로 바꿀 수 있다.
"""

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

LIMIT_W, LIMIT_H = 1366, 768
REGION = "region-SNP-M-102-pzr"
SCREEN_ORDER = ((0, "①"), (1, "②"), (4, "③"), (2, "④"), (3, "⑤"))  # main_window.screens 인덱스 → 화면 번호
VISIT_CANDIDATES = ("deviation-p86-d09", "deviation-p86-d12")
REVIEW_CANDIDATE = "deviation-p86-d12"
TEXT_HEAD = 40
OUT_DIR = os.path.join(REPO_ROOT, "출력", "디자인검사")


# ---------------------------------------------------------------- 위젯 측정(순수 함수, Qt 위젯만 받음)
def effective_width(w):
    return max(w.minimumSizeHint().width(), w.minimumWidth())


def contributes(w, root):
    """w의 최소 폭이 root의 최소 크기 계산에 들어가는가.
    - 명시적으로 숨긴 위젯은 빠진다. 단 QStackedLayout의 숨은 페이지는 최소 크기에 들어간다(쌓인 화면 = 최대값).
    - 스크롤 영역 안 내용은 스크롤 영역 최소 크기에 들어가지 않는다."""
    from PySide6.QtWidgets import QAbstractScrollArea, QStackedLayout
    cur = w
    while cur is not root:
        p = cur.parentWidget()
        if p is None or cur.isWindow():
            return False
        if cur.isHidden() and not isinstance(p.layout(), QStackedLayout):
            return False
        gp = p.parentWidget()
        if isinstance(gp, QAbstractScrollArea) and p is gp.viewport():
            return False
        cur = p
    return True


def _is_leaf(w):
    from PySide6.QtWidgets import QWidget
    return not any(isinstance(c, QWidget) and not c.isWindow() and not c.isHidden() for c in w.children())


def widget_text(w):
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit
    if isinstance(w, (QLabel, QAbstractButton)):
        t = w.text()
    elif isinstance(w, QComboBox):
        t = w.currentText()
    elif isinstance(w, QLineEdit):
        t = w.text() or w.placeholderText()
    else:
        return ""
    t = " ".join(t.split())
    return t[:TEXT_HEAD] + ("…" if len(t) > TEXT_HEAD else "")


def widest_widgets(root, top=5):
    """root의 최소 폭에 기여하는 말단 위젯을 폭 내림차순으로 top개. [{class, objectName, text, width}]"""
    from PySide6.QtWidgets import QWidget
    rows = []
    for w in root.findChildren(QWidget):
        if w.isWindow() or not _is_leaf(w) or not contributes(w, root):
            continue
        rows.append({"class": type(w).__name__, "objectName": w.objectName(), "text": widget_text(w),
                     "width": effective_width(w)})
    rows.sort(key=lambda r: -r["width"])
    return rows[:top]


def measure(win, label, top=5):
    """현재 화면에서 창·화면·헤더·상태줄 최소 크기와 가장 넓은 위젯."""
    from PySide6.QtWidgets import QWidget
    win.resize(LIMIT_W, LIMIT_H)
    pump(win, 0.1)
    scr = win.current_screen()
    hint = win.minimumSizeHint()
    header = win.findChild(QWidget, "header")
    return {"screen": label, "title": getattr(scr, "title", type(scr).__name__),
            "win_min_w": hint.width(), "win_min_h": hint.height(),
            "win_w_after_resize": win.width(), "win_h_after_resize": win.height(),
            "screen_min_w": scr.minimumSizeHint().width(), "screen_min_h": scr.minimumSizeHint().height(),
            "header_min_w": header.minimumSizeHint().width() if header is not None else None,
            "status_min_w": win.statusBar().minimumSizeHint().width(),
            "screen_widest": widest_widgets(scr, top), "window_widest": widest_widgets(win, top)}


# ---------------------------------------------------------------- 창과 상태 만들기
def pump(win=None, seconds=0.0):
    from PySide6.QtCore import QCoreApplication
    if win is not None:
        win.tasks.wait(120000)
    end = time.monotonic() + seconds
    while True:
        QCoreApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.02)


class TempRoots:
    """HAZOP_WORK_ROOT·HAZOP_STORE_ROOT·설정 파일을 임시 폴더로 바꾸고 끝나면 되돌린다."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-design-")
        self.work = os.path.join(self.tmp, "work")
        self.settings = os.path.join(self.tmp, "settings.json")
        self.old = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}

    def __enter__(self):
        os.environ["HAZOP_WORK_ROOT"] = self.work
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(self.tmp, "store")
        os.makedirs(self.work)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install_sample_run(self):
        """샘플 구간 JSON과 고정 응답 분석 실행을 임시 작업 루트에 복사. 실행 폴더 경로."""
        from tests.run_fixture import fresh_run_dir
        src = fresh_run_dir()
        os.makedirs(os.path.join(self.work, "데이터", "구간"), exist_ok=True)
        shutil.copy(os.path.join(REPO_ROOT, "데이터", "구간", REGION + ".json"),
                    os.path.join(self.work, "데이터", "구간"))
        run_dir = os.path.join(self.work, "출력", "분석", REGION, os.path.basename(src))
        if not os.path.isdir(run_dir):
            shutil.copytree(src, run_dir)
        return run_dir


def new_window(roots):
    from PySide6.QtCore import Qt
    from hazop.app.main_window import MainWindow
    win = MainWindow(settings_path=roots.settings, ask_reviewer=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    win.resize(LIMIT_W, LIMIT_H)
    pump(win, 0.1)
    return win


def close_window(win):
    from PySide6.QtCore import QCoreApplication, QEvent
    from hazop.app.webview import HazopWebView
    for v in win.findChildren(HazopWebView):
        v.dispose()
    win.close()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()


def visit_all(win, candidate=None):
    """화면 ①~⑤를 한 번씩 방문(⑤에서는 후보 선택). 쌓인 화면 최소 폭이 최악값이 되게 한다."""
    for idx, _ in SCREEN_ORDER:
        win.go(idx)
        pump(win, 0.1)
        if idx == 3 and win.run_ctx is not None:
            for cid in ([candidate] if candidate else VISIT_CANDIDATES):
                win.screens[3].select_candidate(cid)
                pump(win, 0.1)


def measure_all(win, state, top):
    rows = []
    for idx, label in SCREEN_ORDER:
        win.go(idx)
        pump(win, 0.1)
        r = measure(win, label, top)
        r["state"] = state
        rows.append(r)
    return rows


def save_sample_review(win):
    """⑤ d12에 검토 기록 1건 저장(상태 C 준비). 저장 경로."""
    win.go(3)
    s5 = win.screens[3]
    s5.select_candidate(REVIEW_CANDIDATE)
    pump(win, 0.1)
    (sf,), (df,) = list(s5.sforms.values()), list(s5.dforms.values())
    sf.radios.set_value("accept")
    sf.reason.setPlainText("원안 수용")
    df.radios.set_value("accept")
    df.reason.setPlainText("권고 필요")
    df.recommendation.setPlainText("가압기 고온 경보 추가 검토")
    s5.summary_reason.setText("편차 검토 요약")
    for cb, v in ((sf.sev, 3), (sf.f0, 2), (sf.f, 2)):
        cb.setCurrentIndex(cb.findData(v))
    sf.sev_basis.setText("강도 근거")
    sf.f_basis.setText("빈도 근거")
    path = s5.save(ask_name=False)
    pump(win, 0.1)
    if not path:
        raise RuntimeError("검토 기록 저장 실패: %s" % s5.last_errors)
    return path


def run_states(roots, top=5):
    """상태 A·B·C 측정 결과 목록."""
    rows = []
    win = new_window(roots)
    try:
        visit_all(win)
        rows += measure_all(win, "A 데이터 없음", top)
    finally:
        close_window(win)
    run_dir = roots.install_sample_run()
    win = new_window(roots)
    try:
        win.set_reviewer_name("검토자A")
        win.open_run(run_dir)
        pump(win, 0.3)
        visit_all(win)
        rows += measure_all(win, "B 샘플 분석 실행 열림", top)
        save_sample_review(win)
    finally:
        close_window(win)
    win = new_window(roots)
    try:
        win.open_run(run_dir)
        pump(win, 0.3)
        visit_all(win, REVIEW_CANDIDATE)
        rows += measure_all(win, "C 검토 기록 있음", top)
    finally:
        close_window(win)
    return rows


# ---------------------------------------------------------------- 판정
def environment():
    from PySide6.QtGui import QFont, QFontInfo, QGuiApplication
    scr = QGuiApplication.primaryScreen()
    f = QFont("Malgun Gothic")
    return {"platform": QGuiApplication.platformName(), "dpr": scr.devicePixelRatio(),
            "logical_dpi": scr.logicalDotsPerInch(), "screen_logical": list(scr.geometry().size().toTuple()),
            "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR") or None,
            "malgun_resolved": QFontInfo(f).family()}


def over_limit(rows, dpr=1.0):
    """기준(물리 폭 1366·높이 768)을 넘는 측정 [(state, screen, w, h)]. 물리 = ceil(논리 × DPR)."""
    bad = []
    for r in rows:
        w, h = math.ceil(r["win_min_w"] * dpr), math.ceil(r["win_min_h"] * dpr)
        if w > LIMIT_W or h > LIMIT_H:
            bad.append((r["state"], r["screen"], w, h))
    return bad


def baseline_increases(rows, baseline_rows):
    """기준선 대비 창 최소 폭·높이가 늘어난 측정 [(state, screen, key, old, new)]."""
    old = {(r["state"], r["screen"]): r for r in baseline_rows}
    inc = []
    for r in rows:
        b = old.get((r["state"], r["screen"]))
        if b is None:
            continue
        for k in ("win_min_w", "win_min_h"):
            if r[k] > b[k]:
                inc.append((r["state"], r["screen"], k, b[k], r[k]))
    return inc


def print_table(rows):
    print("%-22s %-3s %6s %6s %6s %6s  %s" % ("상태", "화면", "창폭", "창높이", "화면폭", "헤더", "화면 안 가장 넓은 위젯"))
    for r in rows:
        w = r["screen_widest"][0] if r["screen_widest"] else None
        print("%-22s %-3s %6d %6d %6d %6s  %s" % (
            r["state"], r["screen"], r["win_min_w"], r["win_min_h"], r["screen_min_w"], r["header_min_w"],
            "%s#%s %d '%s'" % (w["class"], w["objectName"], w["width"], w["text"]) if w else "-"))


def main(argv=None):
    from hazop.console import safe_console
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform", choices=("windows", "offscreen"), default="windows")
    ap.add_argument("--scale", type=float, default=1.0, help="QT_SCALE_FACTOR(참고치, 1이 아니면 판정하지 않음)")
    ap.add_argument("--top", type=int, default=5, help="가장 넓은 위젯 보고 개수")
    ap.add_argument("--baseline", help="offscreen 회귀 감시용 이전 결과 JSON(늘어나면 경고)")
    ap.add_argument("--out", help="결과 JSON 경로(기본 출력/디자인검사/design-<platform>[-s<배율>].json)")
    args = ap.parse_args(argv)
    if "PySide6.QtGui" in sys.modules:
        print("PySide6를 이미 가져온 프로세스에서는 플랫폼을 바꿀 수 없습니다. 새 프로세스로 실행하세요.")
        return 2
    os.environ["QT_QPA_PLATFORM"] = args.platform
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = repr(args.scale)
    from hazop.app import make_application
    make_application(["check_design"])
    env = environment()
    print("환경: %s" % env)
    with TempRoots() as roots:
        rows = run_states(roots, args.top)
    print_table(rows)

    rc, verdict = 0, ""
    if args.platform == "windows":
        bad = over_limit(rows, env["dpr"])
        if args.scale != 1.0:
            verdict = "참고치(배율 %s): 물리 기준 초과 %d건 %s" % (args.scale, len(bad), bad)
        elif env["dpr"] != 1.0 or env["logical_dpi"] != 96:
            rc, verdict = 2, "판정 불가: 기준 환경(100%·96 DPI)이 아님(DPR %s, DPI %s)" % (env["dpr"], env["logical_dpi"])
        else:
            rc = 1 if bad else 0
            verdict = "통과(모든 측정 ≤ %d×%d)" % (LIMIT_W, LIMIT_H) if not bad else "실패 %d건: %s" % (len(bad), bad)
    else:
        verdict = "offscreen: 판정 없음(회귀 감시용)"
        if args.baseline:
            with open(args.baseline, encoding="utf-8") as fh:
                inc = baseline_increases(rows, json.load(fh)["rows"])
            verdict += "; 기준선 대비 증가 %d건%s" % (len(inc), (" [경고] %s" % inc) if inc else "")
    out = args.out or os.path.join(OUT_DIR, "design-%s%s.json" % (
        args.platform, "" if args.scale == 1.0 else "-s%d" % round(args.scale * 100)))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"environment": env, "limit": [LIMIT_W, LIMIT_H], "verdict": verdict, "rc": rc, "rows": rows},
                  fh, ensure_ascii=False, indent=2)
    print("결과 JSON: %s" % out)
    print("결과: %s" % verdict)
    return rc


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # QtWebEngine 종료 처리가 멈추는 경우를 피한다(측정·저장은 끝난 뒤)
