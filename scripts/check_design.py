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

뷰어·앱 색 비교(W4, D5): 배치 측정 전에 독립 뷰어 템플릿 :root·하드코딩 색을 앱 tokens.web_css()와 비교한다.
어긋나면 플랫폼과 관계없이 종료 코드 1(판정 불가 2는 유지). --colors-only는 색 검사만 한다(Qt 불필요).
명암비(W5, D7): 이어서 CONTRAST_PAIRS의 토큰 쌍을 WCAG 2.1 공식으로 계산해 글자 4.5:1·그래픽 3:1 미달이면 종료 코드 1.
판정은 불투명 토큰 값 기준이다. 반투명 선·채움을 흰 도면에 합성한 대비는 보고만 한다(종료 코드 미반영).
앱 코드 색 리터럴(W6, D8): hazop/app/**/*.py(tokens.py는 COLORS 블록만 제외, T1 파일 제외)·hazop/viewer/build.py에
색 리터럴이 있으면(APP_COLOR_ALLOW 밖) 종료 코드 1. --colors-only에도 포함한다.
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


# ---------------------------------------------------------------- 뷰어·앱 색 비교(W4, D5). Qt 없이 문자열만 본다.
# 독립 뷰어(hazop/viewer/template.html)의 색은 앱 토큰(hazop/app/tokens.py)을 따른다. 앱 안에서는 web_css()가
# :root를 덮어쓰므로, 비교 기준은 web_css()의 :root(= COLORS + --selected + --hl-dim)다.
VIEWER_DATA_VARS = ("equipment", "valve", "instrument", "piping_element", "unclassified", "physical_connection",
                    "signal_connection", "measurement_connection", "unresolved")  # 템플릿 JS가 "var(--" + 종류 로 만듦
# 토큰과 값이 달라 남겨 둔 색 리터럴. (선택자, 속성, 값) 조합에서만 허용한다(값 통일은 결정 대상, evidence/w4-토큰.md §5).
# 템플릿 HTML 속성·JS에는 색 리터럴이 없다(EDGE_COLOR에 없는 관계 종류는 undefined, 범례 대체는 var(--muted)).
VIEWER_COLOR_ALLOW = {
    (".chip.passed::before", "color", "#16a34a"): "구조 검증 통과 점(앱 --ok #15803d와 다름)",
    ("aside .warn", "color", "#b45309"): "속성 패널 경고 글자(토큰 없음)",
    ("#pathq .res .bad", "color", "#b45309"): "경로 질의 경고 글자(토큰 없음)",
}
SELECTED_RULE = ".selected.sym, .selected.tagbox"
# CSS 이름 색(CSS Color Module Level 4). transparent·currentcolor·none은 색 값이 아니라 뺀다.
CSS_NAMED_COLORS = frozenset("""
aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood
cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray
darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue
firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew
hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray
lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue
mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred
midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid
palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple
rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue
slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white
whitesmoke yellow yellowgreen
""".split())
# 색 값을 받는 속성. "-?"는 JS camelCase(backgroundColor·borderTopColor·stopColor 등, 대소문자 무시로 찾음)도 잡는다.
_COLOR_PROP = (r"(?:color|background(?:-?color)?|border(?:-?(?:top|right|bottom|left))?(?:-?color)?|outline(?:-?color)?"
               r"|fill|stroke|box-?shadow|text-?shadow|stop-?color|flood-?color)")
_HEX_RE = r"(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])"
_FUNC_RE = r"\b(?:rgba?|hsla?)\(\s*[^()]*\)"


def _norm_color(v):
    v = " ".join(v.strip().lower().split())
    if len(v) == 4 and v.startswith("#"):
        v = "#" + "".join(ch * 2 for ch in v[1:])
    return v


def css_rules(css):
    """CSS → [(선택자, [(속성, 값)])]. 주석을 먼저 지우고, @media 등 안쪽 규칙도 펼친다(가장 안쪽 블록 기준)."""
    import re
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    out = []
    for m in re.finditer(r"([^{};]*)\{([^{}]*)\}", css):
        decls = []
        for d in m.group(2).split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                k = k.strip()
                decls.append((k if k.startswith("--") else k.lower(), " ".join(v.split())))  # --변수는 대소문자 구분
        out.append((" ".join(m.group(1).split()), decls))
    return out


def css_root_vars(css):
    """CSS의 :root 규칙 → {이름(-- 뺀 것): 값}. :root가 여러 개면 뒤 값이 이긴다(검사는 viewer_color_problems)."""
    out = {}
    for sel, decls in css_rules(css):
        if sel == ":root":
            out.update((k[2:], v) for k, v in decls if k.startswith("--"))
    return out


def color_literals(value, named=True):
    """값 문자열 안의 색 리터럴: 3·4·6·8자리 hex, rgb()/rgba()/hsl()/hsla()(쉼표형·공백형), named=True면 CSS 이름 색."""
    import re
    v = re.sub(r"--[\w-]+", " ", value)  # 변수 이름(--red 등)은 색이 아님
    lits = re.findall(_HEX_RE, v) + re.findall(_FUNC_RE, v, re.I)
    if named:
        rest = re.sub(_FUNC_RE, " ", re.sub(_HEX_RE, " ", v), flags=re.I)
        lits += [w for w in re.findall(r"[A-Za-z]+", rest) if w.lower() in CSS_NAMED_COLORS]
    return lits


def _rgba_alpha(lit):
    """rgba(r,g,b,a) 또는 rgb(r g b / a)에서 a < 1이면 ((r,g,b), a), 아니면 None."""
    import re
    m = re.fullmatch(r"rgba?\((.*)\)", _norm_color(lit))
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(1).strip()) if p]
    if len(parts) != 4 or not all(re.fullmatch(r"\d+", p) for p in parts[:3]):
        return None
    try:
        a = float(parts[3].rstrip("%")) / (100 if parts[3].endswith("%") else 1)
    except ValueError:
        return None
    return (tuple(int(p) for p in parts[:3]), a) if a < 1 else None


def _translucent_rgb(lit):
    """rgba(r,g,b,a) 또는 rgb(r g b / a)에서 a < 1이면 (r,g,b), 아니면 None."""
    ra = _rgba_alpha(lit)
    return ra[0] if ra else None


def viewer_color_problems(template, app_css):
    """독립 뷰어 템플릿과 앱 web_css()의 색이 어긋난 곳 [문구]. 빈 목록이면 통과. CSS 주석은 지우고 본다.
    1) 템플릿 :root 규칙은 정확히 하나다. 그 안 변수 중복, 다른 규칙·인라인 style에서 --변수 재선언은 실패.
    2) 템플릿 :root의 각 변수가 앱 :root에 있고 값이 같다.
    3) 템플릿 전체(CSS·HTML·JS)의 var( --x )(공백·대체값·중첩 포함)와 데이터 종류 변수(VIEWER_DATA_VARS)는
       템플릿 :root에 정의돼 있다(단독으로 열 때 빈 색 방지). 형식이 틀린 var()도 실패.
    4) :root 밖 색 리터럴(hex 3·4·6·8자리, rgb/rgba/hsl/hsla, 색 속성 값의 CSS 이름 색)은 템플릿 전체에서 실패.
       예외: <style> 규칙의 (선택자, 속성, 값)이 VIEWER_COLOR_ALLOW에 있거나, 반투명 rgba의 rgb가 앱 토큰 색·검정
       (채움·그림자 등. 글자색 color 속성의 반투명은 대비가 토큰 값보다 낮아지므로 실패, W5 D7).
    5) 클릭 선택 채움(SELECTED_RULE fill)은 앱 web_css와 같다."""
    import re
    bad = []
    app_rules = css_rules(app_css)
    app = {k: _norm_color(v) for k, v in css_root_vars(app_css).items()}
    styles = re.findall(r"<style[^>]*>(.*?)</style>", template, re.S | re.I)
    style = "\n".join(styles)
    # <style> 블록은 같은 수의 줄바꿈으로 바꿔 HTML·JS 실패 문구의 줄 번호가 원본 행과 같게 한다
    rest = re.sub(r"<style[^>]*>.*?</style>", lambda m: "\n" * m.group(0).count("\n"), template, flags=re.S | re.I)
    rules = css_rules(style)

    # 1) :root
    roots = [(s, d) for s, d in rules if ":root" in s]
    if len(roots) != 1:
        bad.append(":root 규칙 %d개: 정확히 하나여야 함(뒤쪽 재선언 금지)" % len(roots))
    tpl = {}
    for sel, decls in roots:
        if sel != ":root":
            bad.append(":root 선택자 '%s': 단독 :root만 허용" % sel)
        for k, v in decls:
            if k.startswith("--"):
                if k[2:] in tpl:
                    bad.append("%s: :root 안에서 중복 선언" % k)
                tpl[k[2:]] = v
    for sel, decls in rules:
        if ":root" not in sel:
            bad += ["%s: '%s'에서 재선언(:root에만 둘 것)" % (k, sel) for k, _ in decls if k.startswith("--")]
    bad += ["%s: HTML·JS에서 재선언(:root에만 둘 것)" % m.group(1)
            for m in re.finditer(r"(?<![\w-])(--[\w-]+)\s*:", rest)]
    if not roots:
        bad.append("템플릿 <style>에 :root 없음")
    # 한 규칙 안 같은 속성 중복 금지(뒤 선언이 이기는데 검사가 앞 값만 보는 일을 막음)
    for sel, decls in rules:
        keys = [k for k, _ in decls]
        bad += ["'%s' %s: 한 규칙 안에서 중복 선언" % (sel, k) for k in sorted(set(keys)) if keys.count(k) > 1]

    # 2) 템플릿 :root = 앱 :root
    for k, v in tpl.items():
        if k not in app:
            bad.append("--%s: 앱 토큰에 없음(템플릿 %s)" % (k, v))
        elif _norm_color(v) != app[k]:
            bad.append("--%s: 템플릿 %s ≠ 앱 %s" % (k, v, app[k]))

    # 3) var() 참조
    used = set(VIEWER_DATA_VARS)
    for text in (re.sub(r"/\*.*?\*/", " ", style, flags=re.S), rest):
        for m in re.finditer(r"(?i:var)\(\s*(--[\w-]+)?", text):  # 함수명은 대소문자 무시, 변수명은 그대로
            if m.group(1):
                used.add(m.group(1)[2:])
            elif not re.match(r"(?i:var)\(\s*--[\"']", text[m.start():]):  # JS "var(--" + 종류 는 VIEWER_DATA_VARS로 확인
                bad.append("var() 형식 오류: %s" % text[m.start():m.start() + 30].split("\n")[0])
    for k in sorted(used - set(tpl)):
        bad.append("var(--%s): 템플릿 :root에 정의 없음" % k)

    # 4) 색 리터럴
    rgb_ok = {(0, 0, 0)}
    for v in app.values():
        if re.fullmatch(r"#[0-9a-f]{6}", v):
            rgb_ok.add(tuple(int(v[i:i + 2], 16) for i in (1, 3, 5)))
    for sel, decls in rules:
        if ":root" in sel:
            continue
        for k, v in decls:
            for lit in color_literals(v, named=bool(re.fullmatch(_COLOR_PROP, k, re.I))):
                if (sel, k, _norm_color(lit)) in VIEWER_COLOR_ALLOW:
                    continue
                if _translucent_rgb(lit) in rgb_ok:
                    if k != "color":
                        continue
                    bad.append("반투명 글자색 %s ('%s' color): 글자는 불투명 토큰 var(--토큰)만(명암비 D7)" % (lit, sel))
                    continue
                bad.append("색 리터럴 %s ('%s' %s): var(--토큰)으로 바꿀 것" % (lit, sel, k))
    for i, line in enumerate(rest.split("\n")):
        lits = color_literals(line, named=False)
        # 이름 색은 색 속성 값 위치만: style "fill:red", 속성 fill="red", JS .fill = "red"·{ fill: "red" },
        # setAttribute("fill", "red")
        pos = (r"(?<![\w-])" + _COLOR_PROP + r"[\"']?\s*[:=]\s*[\"']?([^;\"'}<>]*)",
               r"setAttribute\(\s*[\"']" + _COLOR_PROP + r"[\"']\s*,\s*[\"']([^\"']*)")
        for p in pos:
            for m in re.finditer(p, line, re.I):
                lits += [w for w in color_literals(m.group(1)) if w.lower() in CSS_NAMED_COLORS]
        bad += ["색 리터럴 %s (HTML·JS, 스타일 밖 %d번째 줄): var(--토큰)으로 바꿀 것" % (lit, i + 1) for lit in lits]

    # 5) 클릭 선택 채움. 기준 규칙 밖에서 .selected.sym·.selected.tagbox의 fill을 다시 선언하면 실패(뒤 선언이나 더
    #    구체적인 선택자가 이겨 비교가 무의미해짐). 같은 규칙 안 중복은 위에서 거부한다. 값은 마지막 선언을 쓴다.
    #    선택자는 쉼표로 나눈 각 복합 선택자의 클래스 집합으로 판정한다(클래스 순서·추가 클래스와 무관, 총괄 수정).
    #    기준 규칙과 같은 선택자를 여러 번 써서 fill을 겹쳐 선언하는 것도 거부한다(!important 우회 방지).
    targets = [{"selected", "sym"}, {"selected", "tagbox"}]

    def hits_selected(sel):
        for part in sel.split(","):
            classes = set(re.findall(r"\.([A-Za-z0-9_-]+)", part))
            if any(t <= classes for t in targets):
                return True
        return False

    base_fills = 0
    for sel, decls in rules:
        has_fill = any(k == "fill" for k, _ in decls)
        if sel == SELECTED_RULE:
            base_fills += sum(1 for k, _ in decls if k == "fill")
        elif has_fill and hits_selected(sel):
            bad.append("클릭 선택 채움: '%s'에서 재선언('%s'에만 둘 것)" % (sel, SELECTED_RULE))
    if base_fills > 1:
        bad.append("클릭 선택 채움: '%s'의 fill이 %d번 선언됨(한 번만 둘 것)" % (SELECTED_RULE, base_fills))

    def fill(rs):
        have = None
        for sel, decls in rs:
            if sel == SELECTED_RULE:
                for k, v in decls:
                    if k == "fill":
                        have = re.sub(r"\s+", "", v).replace("!important", "").lower()
        return have
    want, have = fill(app_rules), fill(rules)
    if want != have:
        bad.append("클릭 선택 채움: 템플릿 %s ≠ 앱 %s" % (have, want))
    return bad


def color_check():
    """실제 템플릿과 tokens.web_css()를 비교해 출력하고 문제 목록을 돌려준다."""
    from hazop.app import tokens
    from hazop.viewer import build
    with open(build.TEMPLATE, encoding="utf-8") as fh:
        bad = viewer_color_problems(fh.read(), tokens.web_css())
    print("뷰어·앱 색 비교: %s" % ("통과(템플릿 :root = 앱 토큰, 색 리터럴은 허용 목록 %d곳뿐)" % len(VIEWER_COLOR_ALLOW)
                                 if not bad else "실패 %d건" % len(bad)))
    for b in bad:
        print("  - %s" % b)
    return bad


# ---------------------------------------------------------------- 명암비(W5, D7). WCAG 2.1 상대 휘도·대비 공식.
# 기준: 글자 4.5:1(SC 1.4.3, 앱 글자는 11~15px라 모두 일반 글자), UI 구성요소·그래픽 3:1(SC 1.4.11).
# (글자·그래픽 색, 바탕, 기준, 쓰는 곳). 이름은 tokens.COLORS 키, "#"로 시작하면 토큰 밖 리터럴(템플릿 허용 목록).
TEXT, GRAPHIC = 4.5, 3.0
_DATA = ("equipment", "valve", "instrument", "piping_element", "unclassified", "physical_connection",
         "signal_connection", "measurement_connection", "unresolved")
CONTRAST_PAIRS = [
    ("ink", "card", TEXT, "본문 글자(카드·패널)"),
    ("ink", "bg", TEXT, "본문 글자(화면 바탕)"),
    ("ink", "ui-weak", TEXT, "선택된 표 행 글자"),
    ("ink", "ai-hatch-a", TEXT, "AI 산출 상자 글자"),
    ("ink-2", "bg", TEXT, "기본 칩·plain 배지"),
    ("ink-2", "card", TEXT, "범례·그래프 라벨"),
    ("ink", "kg-canvas", TEXT, "③ 캔버스 노드 값 글자·범례 제목"),
    ("ink-2", "kg-canvas", TEXT, "③ 캔버스 관계 라벨·칩"),
    ("muted", "kg-canvas", TEXT, "③ 범례 메모·캔버스 안내"),
    ("muted", "card", TEXT, "단계 탭·섹션 제목·상태줄·뷰어 패널 보조 글자"),
    ("muted", "bg", TEXT, "표 머리·QLabel#muted·뷰어 .chip"),
    ("muted", "ui-weak", TEXT, "선택된 표 행의 제외 후보 회색 글자"),
    ("ui", "card", TEXT, "링크(뷰어 a.back·aside .link). 클릭 선택 테두리·입력 포커스·버튼 hover 테두리(3:1)도 이 쌍으로 충족"),
    ("on-fill", "ui", TEXT, "선택된 단계 탭·주 버튼 글자"),
    ("ui-ink", "ui-weak", TEXT, "ui 배지"),
    ("ok", "ok-bg", TEXT, "통과 칩"),
    ("err-ink", "err-bg", TEXT, "막힘 칩·오류 띠"),
    ("warn-ink", "warn-bg", TEXT, "경고 칩·경고 띠·뷰어 정렬 경고"),
    ("warn-ink", "card", TEXT, "③ 오른쪽 상세의 경고 글자"),
    ("err-ink", "card", TEXT, "③ 오른쪽 상세의 '근거 없음' 글자"),
    ("ai-ink", "ai-hatch-a", TEXT, "AI 배지"),
    ("on-fill", "human-line", TEXT, "사람 확정 배지"),
    ("risk-ok-ink", "risk-ok-bg", TEXT, "위험도 확정 칩 1·2"),
    ("risk-cond-ink", "risk-cond-bg", TEXT, "위험도 확정 칩 3·4"),
    ("risk-deny-ink", "risk-deny-bg", TEXT, "위험도 확정 칩 5"),
    ("risk-ok-ink", "card", TEXT, "위험도 제안 칩 1·2 글자(속 빈 칩)"),
    ("risk-cond-line", "card", TEXT, "위험도 제안 칩 3·4 글자(속 빈 칩)"),
    ("risk-deny-line", "card", TEXT, "위험도 제안 칩 5 글자(속 빈 칩)"),
    ("on-fill", "hl-safeguard", TEXT, "보호수단 배지"),
    ("hl-safeguard", "card", TEXT, "보호수단 약한 배지 글자"),
    ("#b45309", "card", TEXT, "뷰어 경고 글자(aside .warn·경로 질의 .bad, 허용 목록)"),
]
# 도면·그래프 기호 색: 실제로 그리는 바탕은 ②·독립 뷰어·graph_only_html의 흰 도면(--card·#fff)과 ③ 캔버스(--kg-canvas).
# --bg 쌍은 그리는 바탕이 아니라 D1이 계측 연결 조정을 확정한 근거(W1 §3.1)를 지키는 회귀 방지 쌍이다.
CONTRAST_PAIRS += [(k, b, GRAPHIC, "노드·관계 색") for k in _DATA for b in ("card", "bg", "kg-canvas")]
# hl-safeguard/card는 글자 쌍(보호수단 약한 배지 글자, 4.5:1)이 더 엄격해 그래픽 쌍을 따로 두지 않는다(W6에서 #ffffff → card)
CONTRAST_PAIRS += [(k, b, GRAPHIC, "시나리오 강조") for k in ("hl-cause", "hl-path", "hl-safeguard") for b in ("card", "bg")
                   if (k, b) != ("hl-safeguard", "card")]
CONTRAST_PAIRS += [
    ("ui", "bg", GRAPHIC, "화면 바탕 위 버튼 hover·입력 포커스 테두리"),
    ("tag", "card", GRAPHIC, "태그 상자 테두리"),
    ("#16a34a", "bg", GRAPHIC, "뷰어 통과 점(.chip.passed::before, 허용 목록)"),
]


def relative_luminance(color):
    """WCAG 2.1 상대 휘도(sRGB). '#rgb' 또는 '#rrggbb'."""
    v = _norm_color(color).lstrip("#")
    if len(v) != 6:
        raise ValueError("불투명 #rrggbb 색이 아님: %s" % color)
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
           for c in (int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a, b):
    """WCAG 2.1 대비 (L1 + 0.05) / (L2 + 0.05), L1은 밝은 쪽. 1~21."""
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def contrast_rows(colors, pairs=None):
    """쌍별 (글자·그래픽, 바탕, 값들, 비율, 기준, 쓰는 곳)."""
    def val(name):
        return name if name.startswith("#") else colors[name]
    rows = []
    for fg, bg, need, use in (CONTRAST_PAIRS if pairs is None else pairs):
        rows.append((fg, bg, val(fg), val(bg), contrast_ratio(val(fg), val(bg)), need, use))
    return rows


def contrast_problems(colors, pairs=None):
    return ["명암비 %s %s / %s %s = %.4f:1 < %.1f:1 (%s)" % (fg, fv, bg, bv, r, need, use)
            for fg, bg, fv, bv, r, need, use in contrast_rows(colors, pairs) if r < need]


def contrast_check():
    """tokens.COLORS로 지정 쌍의 명암비를 계산해 출력하고 문제 목록을 돌려준다."""
    from hazop.app import tokens
    bad = contrast_problems(tokens.COLORS)
    print("명암비(WCAG 2.1, 글자 4.5:1·그래픽 3:1): %s" % (
        "통과(지정 %d쌍)" % len(CONTRAST_PAIRS) if not bad else "실패 %d건 / %d쌍" % (len(bad), len(CONTRAST_PAIRS))))
    for b in bad:
        print("  - %s" % b)
    return bad


# 반투명 선·채움을 실제 바탕에 합성한 대비(보고 전용, rc 미반영, D7). 판정은 불투명 토큰 값 기준이고,
# 반투명 관계선의 실제 대비는 열린 항목이다(PROGRESS §5). 선 색은 템플릿 JS가 종류별 var(--종류)로 넣는다.
TRANSLUCENT_STROKES = {
    ".pipe-line": ("physical_connection", "signal_connection", "measurement_connection", "unresolved"),  # 종류 없으면 unresolved
    ".gedge": ("physical_connection", "signal_connection", "measurement_connection"),  # 그래프 관계 EDGE_COLOR
}


def _over(rgb, a, bg):
    """rgb(0~255)를 불투명도 a로 바탕 bg(#rrggbb)에 합성한 #rrggbb."""
    b = _norm_color(bg)
    base = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    a = min(1.0, max(0.0, a))  # CSS처럼 알파를 [0,1]로 제한(음수·1 초과 입력으로 채널이 범위를 넘지 않게)
    return "#%02x%02x%02x" % tuple(round(c * a + d * (1 - a)) for c, d in zip(rgb, base))


def translucent_rows(template, colors):
    """[(선택자, 속성, 원래 색, 불투명도, 합성 색, 바탕, 대비)]. 바탕은 도면 --card."""
    import re
    style = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", template, re.S | re.I))
    bg = colors["card"]
    rows = []
    for sel, decls in css_rules(style):
        if ":root" in sel:
            continue
        for k, v in decls:
            if k == "stroke-opacity" and sel in TRANSLUCENT_STROKES:
                raw = v.replace("!important", "").strip()
                try:
                    a = float(raw[:-1]) / 100 if raw.endswith("%") else float(raw)  # 50%도 유효한 CSS 값
                except ValueError:
                    continue
                a = min(1.0, max(0.0, a))
                if a < 1:
                    for kind in TRANSLUCENT_STROKES[sel]:
                        c = _norm_color(colors[kind])
                        mix = _over([int(c[i:i + 2], 16) for i in (1, 3, 5)], a, bg)
                        rows.append((sel, "stroke(--%s)" % kind, c, a, mix, bg, contrast_ratio(mix, bg)))
                continue
            for lit in color_literals(v, named=False):
                ra = _rgba_alpha(lit)
                if ra:
                    mix = _over(ra[0], ra[1], bg)
                    rows.append((sel, k, lit, ra[1], mix, bg, contrast_ratio(mix, bg)))
    return rows


def translucent_check():
    """실제 템플릿의 반투명 선·채움 합성 대비를 출력만 한다(rc 미반영)."""
    from hazop.app import tokens
    from hazop.viewer import build
    with open(build.TEMPLATE, encoding="utf-8") as fh:
        rows = translucent_rows(fh.read(), tokens.COLORS)
    print("반투명 합성 대비(보고 전용, 종료 코드 미반영, 바탕 --card): %d건" % len(rows))
    for sel, k, c, a, mix, bg, r in rows:
        print("  - '%s' %s %s × %g → %s / %s = %.4f:1%s" % (sel, k, c, a, mix, bg, r,
                                                          " (선 3:1 미만)" if k.startswith("stroke") and r < GRAPHIC else ""))
    return rows


# ---------------------------------------------------------------- 앱 코드 색 리터럴(W6, D8).
# 앱 Python 코드는 색을 tokens.COLORS(정의 파일 hazop/app/tokens.py)에서 읽는다. 대상은 hazop/app/**/*.py(T1 파일 제외)와
# hazop/viewer/build.py. 주석은 보지 않고(tokenize) 문자열 리터럴(문서 문자열·f-string 포함, 이어 붙인 문자열은 한 덩어리)만 본다.
# QColor(...)·Qt 전역 색은 ast로 본다. 보고 행 번호는 원본 행이다. 회귀 방지용 휴리스틱이다(한계: evidence/w6-앱색.md §4).
APP_COLOR_EXCLUDE_BLOCKS = {"hazop/app/tokens.py": ("COLORS",)}  # 토큰 정의 대입문(AST 노드의 시작·끝 위치만 뺀다)
APP_COLOR_T1 = ("hazop/app/screens/knowledge.py", "hazop/app/webview.py")  # T1 소유(README §8) — 검사 대상에서 뺌
# 판정할 수 없어 남기는 리터럴: (저장소 기준 경로, 리터럴, 최상위 문장 이름, CSS 선택자 또는 None) → 사유.
# 최상위 문장 이름은 리터럴을 감싼 최상위 def·class 이름이나 대입 대상 이름이다. 같은 리터럴도 다른 자리면 실패한다.
APP_COLOR_ALLOW = {
    ("hazop/app/tokens.py", "rgba(37,99,235,.12)", "web_css", ".selected.sym, .selected.tagbox"):
        "클릭 선택 채움(반투명 ui). 독립 뷰어와 같은 값이어야 한다(D5 ⑤)",
    ("hazop/app/tokens.py", "rgba(220,38,38,.30)", "web_css", ".hz-cause.sym, .hz-cause.gnode, .hz-cause.tagbox"):
        "원인 설비 강조 채움(반투명 hl-cause). 반투명 채움은 토큰 밖(D7)",
    ("hazop/app/tokens.py", "rgba(0,0,0,.06)", "CARD_SHADOW", None): "CARD_SHADOW 정의(장식 그림자, 반투명 검정)",
}
_QT_GLOBAL_COLORS = frozenset("white black red darkRed green darkGreen blue darkBlue cyan darkCyan magenta darkMagenta "
                              "yellow darkYellow gray darkGray lightGray".split())


def app_color_files():
    """검사 대상 파일(저장소 기준 '/' 경로) 목록. T1 소유 파일(APP_COLOR_T1)은 뺀다."""
    out = []
    for base, dirs, names in os.walk(os.path.join(REPO_ROOT, "hazop", "app")):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for n in sorted(names):
            if n.endswith(".py"):
                rel = os.path.relpath(os.path.join(base, n), REPO_ROOT).replace(os.sep, "/")
                if rel not in APP_COLOR_T1:
                    out.append(rel)
    return out + ["hazop/viewer/build.py"]


def _string_groups(text, starts):
    """문자열 리터럴 덩어리 [(원문, 글자별 원본 위치, 내용 시작 위치 집합)]. 주석은 빠진다. 줄바꿈·주석만 사이에 둔
    이어 붙인 문자열은 한 덩어리로 합친다. f-string은 바깥 범위 전체를 한 문자열로 본다. starts: 행 시작 위치."""
    import io
    import re
    import tokenize

    def off(rc):
        return starts[rc[0] - 1] + rc[1]
    fs, fe = getattr(tokenize, "FSTRING_START", -1), getattr(tokenize, "FSTRING_END", -1)
    groups, cur, depth, fstart = [], None, 0, 0
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        span = None
        if tok.type == fs:
            fstart = off(tok.start) if depth == 0 else fstart
            depth += 1
        elif tok.type == fe:
            depth -= 1
            span = (fstart, off(tok.end)) if depth == 0 else None
        elif depth:
            continue
        elif tok.type == tokenize.STRING:
            span = (off(tok.start), off(tok.end))
        elif tok.type not in (tokenize.NL, tokenize.COMMENT):
            cur = None
        if span:
            if cur is None:
                cur = []
                groups.append(cur)
            cur.append(span)
    out = []
    for spans in groups:
        g, offs, content = "", [], set()
        for a, b in spans:
            m = re.match(r"[A-Za-z]*(?:'''|\"\"\"|'|\")", text[a:b])
            content.add(len(g) + (m.end() if m else 0))
            g += text[a:b]
            offs += list(range(a, b))
        # CSS 주석(/* … */)은 같은 길이 공백으로 지운다(위치 유지)
        g = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), g, flags=re.S)
        out.append((g, offs, content))
    return out


def _hex_is_color(g, i, j):
    """g[i:j]의 hex는 기본적으로 색이다. 예외: href=·src=·url( 뒤(참조), 앞 글자가 이름 글자(QFrame#이름 등 객체 이름
    선택자), CSS 선택자 문맥(뒤에 ';'·'}' 없이 '{'가 옴 — `#abc {`, `#abc:not(.on) {`, `:not(#abc) {`)."""
    import re
    if i and (g[i - 1].isalnum() or g[i - 1] in "_-"):
        return False
    if re.search(r"(?i)(?:(?:href|src)\s*=\s*|url\(\s*)\\?[\"']?$", g[max(0, i - 40):i]):
        return False
    # '{' 앞에 따옴표가 있으면 선택자가 아니다(f-string·format 자리표시자 `'#fff'>{msg}` 등, 최종 재검토 총괄 수정).
    # '>'는 CSS 자식 결합자(`#a > p {`)에도 쓰이므로 막지 않는다.
    if re.search(r"(?i)url\(\s*[^)]*$", g[max(0, i - 200):i]):
        return False  # url(…) 안의 '#'·이름은 파일 경로다(Codex 최종 재검토, 총괄 수정)
    return not re.match(r"[^;{}'\"]*\{", g[j:])


def _named_in(value, base):
    """선언·속성 값 전체에서 CSS 이름 색 [(값 안 위치, 이름)]. --변수·%(이름)s 자리표시자·url(…)은 뺀다."""
    import re
    v = re.sub(r"--[\w-]+|%\([^)]*\)[a-z]?|(?i:url)\([^)]*\)", lambda m: " " * len(m.group(0)), value)
    return [(base + m.start(), m.group(0)) for m in re.finditer(r"[A-Za-z]+", v)
            if m.group(0).lower() in CSS_NAMED_COLORS]


def _selector_at(g, i, content):
    """g[i]를 감싼 CSS 규칙의 선택자(공백 정리). 규칙 밖이면 None."""
    o, c = g.rfind("{", 0, i), g.rfind("}", 0, i)
    if o < 0 or c > o:
        return None
    start = max([c] + [k - 1 for k in content if k <= o])
    return " ".join(g[start + 1:o].split()) or None


def app_color_findings(text, exclude_blocks=()):
    """Python 소스의 색 리터럴 [(원본 행, 리터럴, 최상위 문장 이름, CSS 선택자)]. 리터럴은 따옴표·공백을 정리한 값.
    - 문자열 안: hex 3·4·6·8자리(_hex_is_color 예외 밖), rgb/rgba/hsl/hsla()(여러 줄·이어 붙인 문자열 포함),
      CSS 선언 값 전체(`border: 1px solid red`)와 색 속성 따옴표 값(`fill="white"`, JS `x.color = "red"`)의 CSS 이름 색.
      CSS 주석 안과 url(…) 안은 보지 않는다.
    - 코드: QColor("red")·QColor(1, 2, 3)(인자가 다음 줄이면 인자 행), Qt.white·Qt.GlobalColor.darkRed.
    exclude_blocks: 이 이름에 대입하는 최상위 문장(AST 노드의 시작·끝 위치, 열 포함)은 뺀다(tokens.py의 COLORS)."""
    import ast
    import bisect
    import re
    starts = [0]
    for ln in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(ln))
    src_lines = text.splitlines(keepends=True)

    def pos(lineno, col_bytes):  # ast 열은 UTF-8 바이트 기준
        return starts[lineno - 1] + len(src_lines[lineno - 1].encode("utf-8")[:col_bytes].decode("utf-8", "ignore"))

    def span(node):
        return pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset)

    tree = ast.parse(text)
    skip, scopes = [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        else:
            targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            name = names[0] if names else None
            if any(n in exclude_blocks for n in names):
                skip.append(span(node))
        scopes.append(span(node) + (name,))

    def where(o):
        return next((s[2] for s in scopes if s[0] <= o < s[1]), None)

    found = []  # (원본 위치, 리터럴, 선택자)
    decl = r"(?i)(?<![\w-])%s\s*:\s*([^;{}\"'<>\n]*)" % _COLOR_PROP
    attr = r"(?i)(?<![\w-])%s\s*=\s*([\"'])([^\"'\n]*)\1" % _COLOR_PROP
    url_re = r"(?i)url\((?:[^()]|\([^()]*\))*\)"  # url(…) 전체(괄호 한 단계 포함)를 같은 길이 공백으로 가린다
    for g, offs, content in _string_groups(text, starts):
        gm = re.sub(url_re, lambda m: re.sub(r"[^\n]", " ", m.group(0)), g)  # 위치·줄바꿈 보존
        hits = [(m.start(), m.group(0)) for m in re.finditer(_HEX_RE, gm) if _hex_is_color(gm, m.start(), m.end())]
        hits += [(m.start(), " ".join(re.sub(r"[\"']", "", m.group(0)).split()))
                 for m in re.finditer(_FUNC_RE, gm, re.I)]
        for m in re.finditer(decl, g):
            hits += _named_in(m.group(1), m.start(1))
        for m in re.finditer(attr, g):
            hits += _named_in(m.group(2), m.start(2))
        found += [(offs[i], lit, _selector_at(g, i, content)) for i, lit in hits]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and (
                getattr(node.func, "id", None) == "QColor" or getattr(node.func, "attr", None) == "QColor"):
            a = node.args[0].value
            if (isinstance(a, (int, float)) and not isinstance(a, bool)) or (
                    isinstance(a, str) and a.lower() in CSS_NAMED_COLORS):
                found.append((span(node.args[0])[0], "QColor(%r" % (a,), None))
        elif isinstance(node, ast.Attribute) and node.attr in _QT_GLOBAL_COLORS:
            v = node.value
            if getattr(v, "id", None) == "Qt":
                found.append((span(node)[0], "Qt." + node.attr, None))
            elif getattr(v, "attr", None) == "GlobalColor" and getattr(v.value, "id", None) == "Qt":
                found.append((span(node)[0], "Qt.GlobalColor." + node.attr, None))
    return sorted((bisect.bisect_right(starts, o), lit, where(o), sel) for o, lit, sel in found
                  if not any(a <= o < b for a, b in skip))


def app_color_literals(text, exclude_blocks=()):
    """app_color_findings의 [(원본 행, 리터럴)]."""
    return [(n, lit) for n, lit, _w, _s in app_color_findings(text, exclude_blocks)]


def app_color_problems(sources=None):
    """앱 코드 색 리터럴 [문구]. sources = {경로: 소스 문자열}(기본은 app_color_files()를 읽음). 빈 목록이면 통과.
    허용 목록은 (경로, 리터럴, 최상위 문장 이름, 선택자)가 모두 맞을 때만 적용한다."""
    if sources is None:
        sources = {}
        for rel in app_color_files():
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                sources[rel] = fh.read()
    bad = []
    for rel, text in sources.items():
        for no, lit, scope, sel in app_color_findings(text, APP_COLOR_EXCLUDE_BLOCKS.get(rel, ())):
            if (rel, lit, scope, sel) not in APP_COLOR_ALLOW:
                bad.append("앱 코드 색 리터럴 %s:%d %s (hazop.app.tokens 참조로 바꿀 것)" % (rel, no, lit))
    return bad


def app_color_check():
    """실제 앱 코드의 색 리터럴을 출력하고 문제 목록을 돌려준다."""
    files = app_color_files()
    bad = app_color_problems()
    print("앱 코드 색 리터럴(%d개 파일, tokens.py는 COLORS 블록만 제외, T1 파일 %d개 제외): %s" % (
        len(files), len(APP_COLOR_T1), ("없음(허용 목록 %d곳)" % len(APP_COLOR_ALLOW)) if not bad else "실패 %d건" % len(bad)))
    for b in bad:
        print("  - %s" % b)
    return bad


def merge_color_result(rc, verdict, color_bad):
    """배치 판정(rc, verdict)에 색 검사(뷰어·앱 색 비교, 명암비, 앱 코드 색 리터럴) 결과를 합친다. 판정 불가(2)는 그대로 둔다."""
    if color_bad:
        rc = rc if rc == 2 else 1
        verdict += "; 색 검사 실패 %d건(뷰어·앱 색 비교·명암비·앱 코드 색 리터럴): %s" % (len(color_bad), color_bad)
    return rc, verdict


def write_result(out, env, limit, rows, rc, verdict, color_bad):
    """색 비교를 합친 rc·verdict로 결과 JSON을 쓰고 (rc, verdict)를 돌려준다. JSON의 rc = 종료 코드."""
    rc, verdict = merge_color_result(rc, verdict, color_bad)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"environment": env, "limit": list(limit) if limit else None, "verdict": verdict, "rc": rc,
                   "color_problems": list(color_bad), "rows": rows}, fh, ensure_ascii=False, indent=2)
    print("결과 JSON: %s" % out)
    print("결과: %s" % verdict)
    return rc, verdict


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
    ap.add_argument("--colors-only", action="store_true", help="색 검사(뷰어·앱 색 비교·명암비·앱 코드 색 리터럴)만 하고 배치 측정은 하지 않음")
    args = ap.parse_args(argv)
    color_bad = color_check() + contrast_check() + app_color_check()
    translucent_check()
    if args.colors_only:
        return 1 if color_bad else 0
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
    rc, verdict = write_result(out, env, limit, rows, rc, verdict, color_bad)
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
