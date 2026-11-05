"""지원 화면 배치 검사 (docs/2026-11-05-design-system 결정 D1·D3·D4, 작업 W2·W3). 네트워크·AI 호출 없음.

메인 창을 화면에 띄우지 않고(WA_DontShowOnScreen) 상태별·화면별로 창 minimumSizeHint 폭·높이를 잰다.
- 상태: A 데이터 없음 → B 샘플 분석 실행 열림(tests/run_fixture 고정 응답) → C 검토 기록 있음(⑤ d12 저장 뒤 다시 열기)
  → D 지식그래프 실행·E 지식그래프 생략 실행(scripts/check_kg_context의 샘플 지식그래프·고정 응답, ⑤ d09 관련 지식 펼침).
  각 상태에서 화면 ①~⑤를 한 번씩 먼저 방문하고(⑤는 후보 선택) 다시 화면별로 잰다. 쌓인 화면(QStackedWidget)의
  최소 폭은 모든 화면의 최대값이고 ⑤는 첫 방문 때 문구를 채우므로, 이렇게 해야 최악값이 나온다.
- 화면마다 최소 폭에 기여하는 가장 넓은 말단 위젯 상위 N개(클래스·objectName·문구 앞부분·폭)를 함께 기록한다.
- 줄임표 라벨(widgets.ElidedLabel)은 1366×768로 맞춘 창에서 줄여 그려졌는지와 툴팁 = 전체 문구인지 기록한다.
- 작업·저장 루트(HAZOP_WORK_ROOT·HAZOP_STORE_ROOT)와 설정 파일은 임시 폴더. 실제 자료저장소·출력/ 실행은 쓰지 않는다.

판정(D1·D3·D4안): 지원 화면 두 가지의 작업 영역(작업 표시줄·제목 표시줄 제외)과 창 최소 크기(논리 px)를 비교한다.
- 100%: 1366×768 → 작업 영역 1366×689. 125%: 논리 1536×864 → 1536×785. (작업 표시줄 48, 제목 표시줄 31, 논리 px)
- 창 최소 크기는 1366×768로 맞춘 창에서 재고, 폼 적합성·줄임표 라벨·가로 스크롤바는 창을 그 배율의 작업 영역 크기로
  다시 맞춘 뒤에도 잰다(at_area).
- --platform windows(배율 100%, DPR 1.0·96 DPI): 100% 기준으로 판정한 뒤 새 프로세스로 --scale 1.25 판정을 이어서 하고
  나쁜 쪽 종료 코드를 돌려준다(--no-125로 생략). 통과 0. 실패 1 = 창 최소 크기 > 작업 영역, ⑤ 폼 내용 최소 폭 >
  보이는 폭, 줄임표 툴팁 규칙 위반. 실제 DPR이 요청 배율과 다르거나 96 DPI가 아니면 판정하지 않고 2.
- --scale 1.25(QT_SCALE_FACTOR로 125% 흉내): 125% 작업 영역으로 판정(0/1/2). 그 밖의 배율은 참고치(종료 코드 0).
- --platform offscreen: 글꼴 대체로 폭이 과대하므로 판정하지 않는다. --baseline <이전 결과 JSON>을 주면 늘어난 값만
  경고로 알린다(종료 코드 0). 기준 수치는 docs/2026-11-05-design-system/evidence/w3-작업영역125.md에 기록한다.
결과 JSON: 출력/디자인검사/design-<platform>[-s<배율>].json (출력/는 git 제외). --out으로 바꿀 수 있다.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

LIMIT_W, LIMIT_H = 1366, 768  # 측정 때 창을 맞추는 크기(100% 화면)
TASKBAR_H, TITLEBAR_H = 48, 31  # 논리 px. Windows 11 기본 작업 표시줄, 제목 표시줄(SM_CYCAPTION 23 + 크기 틀 4 + 여백 4, 96 DPI)
SCREENS = {1.0: (1366, 768), 1.25: (1536, 864)}  # 지원 화면(D3): 배율 → 논리 화면 크기
REGION = "region-SNP-M-102-pzr"
SCREEN_ORDER = ((0, "①"), (1, "②"), (4, "③"), (2, "④"), (3, "⑤"))  # main_window.screens 인덱스 → 화면 번호
VISIT_CANDIDATES = ("deviation-p86-d09", "deviation-p86-d12")
REVIEW_CANDIDATE = "deviation-p86-d12"
REVIEW_KG_CANDIDATE = "deviation-p86-d09"
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


def measure(win, label, top=5, area=None):
    """현재 화면에서 창·화면·헤더·상태줄 최소 크기와 가장 넓은 위젯(창 1366×768), 그리고 창을 작업 영역 area
    (기본 100% 작업 영역)로 맞춘 뒤의 폼 적합성·줄임표 라벨·가로 스크롤바(at_area)."""
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
            "screen_widest": widest_widgets(scr, top), "window_widest": widest_widgets(win, top),
            "elided": elided_labels(scr), "form": form_fit(scr), "at_area": measure_at(win, scr, area)}


def measure_at(win, scr, area=None):
    """창을 작업 영역(논리 px)으로 맞춘 뒤 실제 창 크기, ⑤ 폼 적합성, 줄임표 라벨, 보이는 가로 스크롤바."""
    from PySide6.QtWidgets import QAbstractScrollArea
    area = area or work_area(1.0)
    win.resize(*area)
    pump(win, 0.1)
    hs = [{"class": type(a).__name__, "objectName": a.objectName()} for a in scr.findChildren(QAbstractScrollArea)
          if a.isVisibleTo(scr) and a.horizontalScrollBar().isVisible()]
    return {"area": list(area), "win_size": [win.width(), win.height()], "form": form_fit(scr),
            "elided": elided_labels(scr), "hscroll": hs}


def elided_labels(root):
    """root 안의 보이는 줄임표 라벨 [{objectName, text, elided, tooltip_ok, min_w, full_w}].
    tooltip_ok: 줄여 그렸으면 툴팁 = 전체 문구, 아니면 툴팁 없음(widgets.ElidedLabel 규칙)."""
    from hazop.app.widgets import ElidedLabel
    rows = []
    for w in root.findChildren(ElidedLabel):
        if w.elide is None or not w.isVisibleTo(root) or not w.text():
            continue
        rows.append({"objectName": w.objectName(), "text": widget_text(w), "elided": w.is_elided(),
                     "tooltip_ok": w.toolTip() == (w.text() if w.is_elided() else ""), "min_w": w.minimumSizeHint().width(), "full_w": w.sizeHint().width()})
    return rows


def form_fit(scr):
    """⑤ 결정 폼(스크롤 영역)의 내용 최소 폭과 보이는 폭. 폼이 없으면 None."""
    from PySide6.QtWidgets import QScrollArea
    sa = getattr(scr, "scroll", None)  # QWidget.scroll은 메서드라 형식으로 가린다
    if not isinstance(sa, QScrollArea) or sa.widget() is None:
        return None
    return {"need": sa.widget().minimumSizeHint().width(), "have": sa.viewport().width()}


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


def measure_all(win, state, top, area=None):
    rows = []
    for idx, label in SCREEN_ORDER:
        win.go(idx)
        pump(win, 0.1)
        r = measure(win, label, top, area)
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


def install_kg_runs(roots):
    """지식그래프 실행 2개(일반·항목 상한 4로 생략)를 임시 작업 루트에 만든다. {"kg"|"trunc": 실행 폴더}.
    tests/test_kg_review.py와 같은 방법(scripts/check_kg_context의 샘플 그래프·지식·고정 응답)."""
    from unittest import mock
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import check_kg_context as kgc
    from hazop.analysis import ai, run
    from hazop.kg import build, context
    graph = kgc.sample_graph()
    gdir = os.path.join(roots.work, "출력", "그래프", "SNP-M-102")
    os.makedirs(gdir, exist_ok=True)
    graph_path = os.path.join(gdir, "graph.json")
    with open(graph_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(graph, fh, ensure_ascii=False)
    knowledge = kgc.sample_knowledge()
    knowledge["kg_id"] = kgc.KG_ID
    build.write_outputs(os.path.join(roots.work, "출력", "지식그래프", kgc.KG_ID), knowledge,
                        build.build_kg(knowledge, [graph]))
    region = kgc.load(kgc.REGION_FILE)
    region["inputs"]["knowledge_graph"] = kgc.KG_REF
    rp = os.path.join(roots.tmp, "region-kg.json")
    with open(rp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(region, fh, ensure_ascii=False)
    out = {}
    for name, limits in (("kg", {}), ("trunc", {"max_items": 4})):
        with mock.patch.dict(context.LIMITS, limits):
            ins = run.load_inputs(rp, roots.work, graph_path=graph_path, resource_root=REPO_ROOT)
            _, out[name] = run.execute(ins, ai.FixedResponseClient(kgc.KG_RESPONSES),
                                       os.path.join(roots.work, "출력", "분석"), run_id="analysis-kg-%s" % name,
                                       now=kgc.now)
    return out


def expand_knowledge(win):
    """⑤ 결정 폼의 '관련 지식 (참고)' 묶음을 모두 펼친다(가장 넓은 상태)."""
    for f in win.screens[3].sforms.values():
        if f.knowledge.toggle is not None and not f.knowledge.toggle.isChecked():
            f.knowledge.toggle.click()
    pump(win, 0.1)


def run_states(roots, top=5, area=None):
    """상태 A~E 측정 결과 목록."""
    rows = []
    win = new_window(roots)
    try:
        visit_all(win)
        rows += measure_all(win, "A 데이터 없음", top, area)
    finally:
        close_window(win)
    run_dir = roots.install_sample_run()
    win = new_window(roots)
    try:
        win.set_reviewer_name("검토자A")
        win.open_run(run_dir)
        pump(win, 0.3)
        visit_all(win)
        rows += measure_all(win, "B 샘플 분석 실행 열림", top, area)
        save_sample_review(win)
    finally:
        close_window(win)
    win = new_window(roots)
    try:
        win.open_run(run_dir)
        pump(win, 0.3)
        visit_all(win, REVIEW_CANDIDATE)
        rows += measure_all(win, "C 검토 기록 있음", top, area)
    finally:
        close_window(win)
    kg_runs = install_kg_runs(roots)
    for state, name in (("D 지식그래프 실행", "kg"), ("E 지식그래프 생략 실행", "trunc")):
        win = new_window(roots)
        try:
            win.set_reviewer_name("검토자A")
            win.open_run(kg_runs[name])
            pump(win, 0.3)
            visit_all(win, REVIEW_KG_CANDIDATE)
            win.go(3)
            expand_knowledge(win)
            rows += measure_all(win, state, top, area)
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


def work_area(scale=1.0):
    """지원 화면(D3)의 작업 영역(논리 px): 화면 높이에서 작업 표시줄·제목 표시줄을 뺀다. 지원 배율이 아니면 None."""
    if scale not in SCREENS:
        return None
    w, h = SCREENS[scale]
    return w, h - TASKBAR_H - TITLEBAR_H


def over_limit(rows, limit):
    """창 최소 크기(논리 px)가 limit(폭, 높이)를 넘는 측정 [(state, screen, w, h)]."""
    return [(r["state"], r["screen"], r["win_min_w"], r["win_min_h"]) for r in rows
            if r["win_min_w"] > limit[0] or r["win_min_h"] > limit[1]]


def elide_problems(rows):
    """줄임표 라벨 툴팁 규칙(줄였으면 전체 문구, 아니면 없음)을 어긴 측정 [(state, screen, objectName)]."""
    return [(r["state"], r["screen"], e["objectName"]) for r in rows
            for e in list(r.get("elided") or ()) + list((r.get("at_area") or {}).get("elided") or ())
            if not e["tooltip_ok"]]


def form_problems(rows):
    """⑤ 폼 내용 최소 폭이 보이는 폭보다 큰 측정(가로 잘림) [(state, screen, 창 크기, need, have)]."""
    bad = []
    for r in rows:
        for where, f in (("1366x768", r.get("form")), ("작업 영역", (r.get("at_area") or {}).get("form"))):
            if f and f["need"] > f["have"]:
                bad.append((r["state"], r["screen"], where, f["need"], f["have"]))
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
    print("%-22s %-3s %6s %6s %6s %6s %4s  %s" % ("상태", "화면", "창폭", "창높이", "화면폭", "헤더", "줄임",
                                                 "화면 안 가장 넓은 위젯"))
    for r in rows:
        w = r["screen_widest"][0] if r["screen_widest"] else None
        print("%-22s %-3s %6d %6d %6d %6s %4d  %s" % (
            r["state"], r["screen"], r["win_min_w"], r["win_min_h"], r["screen_min_w"], r["header_min_w"],
            sum(e["elided"] for e in (r.get("at_area") or {}).get("elided") or ()),
            "%s#%s %d '%s'" % (w["class"], w["objectName"], w["width"], w["text"]) if w else "-"))


def main(argv=None):
    from hazop.console import safe_console
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform", choices=("windows", "offscreen"), default="windows")
    ap.add_argument("--scale", type=float, default=1.0, help="QT_SCALE_FACTOR(1.25는 125%% 판정, 그 밖은 참고치)")
    ap.add_argument("--no-125", action="store_true", help="windows 100%% 판정 뒤 125%% 판정을 이어서 하지 않음")
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
        rows = run_states(roots, args.top, work_area(args.scale) or work_area(1.0))
    print_table(rows)

    rc, verdict = 0, ""
    limit = work_area(args.scale)
    if args.platform == "windows":
        if env["logical_dpi"] != 96 or abs(env["dpr"] - args.scale) > 1e-3:
            rc, verdict = 2, "판정 불가: 기준 환경(배율 %s·96 DPI)이 아님(DPR %s, DPI %s)" % (
                args.scale, env["dpr"], env["logical_dpi"])
        elif limit is None:
            verdict = "참고치(배율 %s, 지원 배율 아님): 100%% 작업 영역 %s 초과 %d건" % (
                args.scale, work_area(1.0), len(over_limit(rows, work_area(1.0))))
        else:
            bad = over_limit(rows, limit) + elide_problems(rows) + form_problems(rows)
            rc = 1 if bad else 0
            verdict = ("배율 %d%%: " % round(args.scale * 100)) + (
                "통과(모든 측정 ≤ 작업 영역 %d×%d, ⑤ 폼 가로 잘림 없음, 줄임표 툴팁 규칙 지킴)" % limit
                if not bad else "실패 %d건: %s" % (len(bad), bad))
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
        json.dump({"environment": env, "limit": list(limit) if limit else None, "verdict": verdict, "rc": rc,
                   "rows": rows}, fh, ensure_ascii=False, indent=2)
    print("결과 JSON: %s" % out)
    print("결과: %s" % verdict)
    if args.platform == "windows" and args.scale == 1.0 and not args.no_125 and rc != 2:
        import subprocess
        print("--- 125% 판정(새 프로세스, --scale 1.25) ---")
        sys.stdout.flush()
        cmd = [sys.executable, os.path.abspath(__file__), "--platform", "windows", "--scale", "1.25", "--top", str(args.top)]
        if args.out:
            cmd += ["--out", os.path.splitext(args.out)[0] + "-s125.json"]
        rc = max(rc, subprocess.call(cmd))
        print("종합 종료 코드: %d" % rc)
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
