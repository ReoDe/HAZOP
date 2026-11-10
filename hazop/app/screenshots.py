"""화면별 스크린샷(QWidget.grab()) — scripts/run_app.py --screenshots, scripts/check_app.py가 쓴다.
③ 지식그래프는 작업 루트에 지식그래프가 있을 때만 찍고, 없으면 건너뛰고 표준 출력에 남긴다.
take_stages는 레일 단계 ①~⑤의 첫 화면을 STAGE_SIZES 크기마다 찍는다(작업 루트에 있는 그대로, 아무것도 저장하지 않음)."""

import os
import time

from PySide6.QtCore import QCoreApplication, QEventLoop


def wait(cond, timeout=15.0, step=0.05):
    """조건이 참이 될 때까지 이벤트를 돌린다. 시간 안에 참이 되면 True."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
        if cond():
            return True
        time.sleep(step)
    QCoreApplication.processEvents()
    return bool(cond())


def settle(seconds=0.6):
    wait(lambda: False, seconds)


def _ready(win):
    return lambda: win.webview.isHidden() or win.webview.current_file is None or win.webview.bridge.is_ready


def take_all(app, win, out_dir, run_dir=None, candidate="deviation-p86-d09"):
    os.makedirs(out_dir, exist_ok=True)
    files = []

    def shot(name):
        wait(_ready(win), 20)
        settle(0.8)
        p = os.path.join(out_dir, name)
        win.grab().save(p)
        files.append(os.path.abspath(p))

    win.go(0)
    shot("01-register.png")
    win.go(1)
    shot("02-viewer.png")
    viewer = win.screens[1]
    if viewer.editable():  # 편집 모드는 켜기만 하고 아무것도 고치지 않는다(저장할 것이 없어 끌 때 묻지 않음)
        viewer.edit_btn.setChecked(True)
        shot("02-viewer-edit.png")
        viewer.edit_btn.setChecked(False)
    else:
        print("[건너뜀] 02-viewer-edit.png: ②에 편집할 수 있는 도면 없음")
    win.go(2)
    if run_dir:
        win.open_run(run_dir)
        scr = win.screens[2]
        scr.select_candidate(candidate)
        if scr.scenario_list.count() > 2:
            scr.scenario_list.setCurrentRow(2)
    shot("04-analysis.png")
    win.go(3)
    if run_dir:
        win.screens[3].select_candidate(candidate)
    shot("05-review.png")
    if run_dir:  # 사람 확정 표시 예시: 결정 하나를 임시 저장 루트에 저장한 뒤 촬영(run_app이 저장 루트를 임시로 바꿈)
        scr = win.screens[3]
        if not win.reviewer_name():
            win.set_reviewer_name("검토자(예시)")
        scr.reviewer_edit.setText(win.reviewer_name())
        scr.select_candidate("deviation-p86-d12")
        sf = next(iter(scr.sforms.values()), None)
        if sf is not None:
            sf.radios.set_value("accept")
            sf.reason.setPlainText("원안 수용(스크린샷 예시)")
            for cb, v in ((sf.sev, 3), (sf.f0, 2), (sf.f, 2)):
                cb.setCurrentIndex(cb.findData(v))
            sf.sev_basis.setText("강도 근거(예시)")
            sf.f_basis.setText("빈도 근거(예시)")
            for df in scr.dforms.values():
                df.radios.set_value("defer")
                df.reason.setPlainText("자료 확인 후 결정(예시)")
            scr.summary_reason.setText("스크린샷 예시 저장")
            scr.save(ask_name=False)
            shot("05-review-confirmed.png")
    if run_dir:  # 작은 화면(1366×768)에서 ⑤ 폼이 가로로 잘리지 않는지 확인용
        size = win.size()
        win.showNormal()
        win.resize(1366, 768)
        settle(0.5)
        win.screens[3].select_candidate(candidate)
        shot("05-review-1366.png")
        scr = win.screens[3]
        sf = next(iter(scr.sforms.values()), None)
        if sf is not None:  # 보호수단 편집·위험도 입력란이 잘리지 않는지 보이도록 스크롤
            scr.scroll.ensureWidgetVisible(sf.risk_box, 0, 0)
            shot("05-review-1366-risk.png")
        win.resize(size)
    from hazop.app.main_window import STEPS
    win.go(STEPS.index("③ 지식그래프"))
    kg_scr = win.screens[STEPS.index("③ 지식그래프")]
    if kg_scr.stack.currentIndex() == 1:  # 지식그래프를 읽어 캔버스를 띄운 경우만
        settle(2.0)
        shot("03-knowledge.png")
    else:
        print("[건너뜀] 03-knowledge.png: ③ 지식그래프 없음(%s)" % " ".join(kg_scr.empty.text().split()))
    return files + take_stages(win, os.path.join(out_dir, "stages"))


STAGE_SIZES = ((1366, 768), (1920, 1080))


def take_stages(win, out_dir, sizes=STAGE_SIZES):
    """단계 ①②③④⑤(레일 순서) × sizes. 파일 이름 stage<번호>-<짧은 이름>-<폭>x<높이>.png.
    ④는 첫 구간을 고른 상태, ⑤는 확정 구간이 있으면 첫 칸 워크시트를 연 상태로 찍는다."""
    from hazop.app.main_window import STAGES
    os.makedirs(out_dir, exist_ok=True)
    files = []
    size0 = win.size()
    for w, h in sizes:
        win.showNormal()
        win.resize(w, h)
        settle(0.5)
        for num, short, idxs in STAGES:
            win.go(idxs[0])
            scr = win.screens[idxs[0]]
            if num == "3":
                settle(2.0)  # ③ 지식그래프 배치
            matrix = getattr(scr, "matrix", None)
            if matrix is not None and getattr(scr, "node_set", None):
                scr.open_cell(scr.node_set["nodes"][0]["node_id"], scr.deviations[0]["deviation_id"])
            wait(_ready(win), 20)
            settle(1.2)
            p = os.path.join(out_dir, "stage%s-%s-%dx%d.png" % (num, short, w, h))
            win.grab().save(p)
            files.append(os.path.abspath(p))
    win.resize(size0)
    return files
