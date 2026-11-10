"""⑤ AI 실행 흐름 스크린샷(디자인/AI연결-화면설계.md §6·§7·§8, 시안 6·7·8과 나란히 보기). 사용:
    python scripts/shoot_ai_run.py <출력 폴더> [--scale 1.25]

주 창(1366×768, --scale 1.25면 논리 1536×864 = 1920×1080 화면) 위에 장면을 찍는다: 실행 확인(API 키·구독 한도 앎·
구독 한도 모름·고정 응답·API 키로 이어서), 한도 도달 띠와 '한도로 멈춤' 칸, 칸 상세 출처 줄, 시험 결과 띠, 창 닫기 물음과
기다림 창. 구독은 가짜 CLI(tests/fake_claude_flow.py), API 키는 가짜 클라이언트다(실제 CLI·네트워크 없음).
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
FLOW = os.path.join(REPO_ROOT, "tests", "fake_claude_flow.py")


def pump(secs=0.3):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + secs
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.02)


def wait(cond, secs=60):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + secs
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def compose(win, dlg):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter
    img = win.grab().toImage()
    d = dlg.grab()
    ratio = d.devicePixelRatio() or 1.0
    wr = img.devicePixelRatio() or 1.0
    at = QPoint(int((img.width() / wr - d.width() / ratio) // 2), int(max(20, (img.height() / wr - d.height() / ratio) // 3)))
    p = QPainter(img)
    p.drawPixmap(at, d)
    p.end()
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args()
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    w, h = (1366, 768) if args.scale == 1.0 else (1536, 864)
    tag = "1366" if args.scale == 1.0 else "1920"
    os.makedirs(args.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shot-run-")
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    os.makedirs(os.environ["HAZOP_WORK_ROOT"])
    import shoot_results
    shoot_results.prepare(os.environ["HAZOP_WORK_ROOT"])
    from hazop.app import make_application
    app = make_application(["shot"])
    from hazop.app.main_window import MainWindow
    from hazop.app.screens import results as rmod
    from hazop.study import ai_cells, claude_cli, providers
    files = []

    def save(img, name):
        path = os.path.join(args.out, "%s-%s.png" % (name, tag))
        img.save(path)
        files.append(path)

    def window(scenarios, method="subscription", debug=False):
        win = MainWindow(settings_path=os.path.join(tmp, "settings-%s.json" % time.monotonic_ns()), ask_reviewer=False,
                         debug=debug)
        win.api_keys.add("회사 워크스페이스", shoot_results.KEY, persist=False)
        state = tempfile.mkdtemp(dir=tmp)
        win.ai_conn.cli_factory = lambda path, **kw: claude_cli.ClaudeCliClient(
            argv_prefix=[sys.executable, FLOW, scenarios, state], limits_path=os.path.join(state, "limits.json"),
            run_root=os.path.join(state, "run"), **kw)
        win.ai_prefs.choose(method)
        win.ai_prefs.ack_terms()
        win.resize(w, h)
        win.show()
        win.go(6)
        scr = win.screens[6]
        scr.make_client = lambda: shoot_results.FakeClient() if scr.run_method == "api" else \
            win.ai_conn.make_client(scr.run_method)
        scr.ask_close = lambda n: "now"
        scr.matrix.setCurrentCell(0, 0)
        pump()
        return win, scr

    def shoot_confirm(win, scr, name, scope="node", method=None):
        def ask(dlg):
            dlg.fit()
            dlg.show()
            pump()
            save(compose(win, dlg), name)
            dlg.hide()
            return None
        with mock.patch.object(rmod.RunConfirmDialog, "ask", ask):
            scr._request(scope, True, method)
            wait(lambda: not scr.running(), 30)

    # 1. 실행 확인: API 키
    win, scr = window("ok", method="api")
    shoot_confirm(win, scr, "6-실행확인-API키")
    win.close()
    # 2. 구독(한도 모름) → 정상 실행 → 출처 줄
    win, scr = window("ok,ok,warning")
    shoot_confirm(win, scr, "6-실행확인-구독-한도모름")
    with mock.patch.object(rmod.RunConfirmDialog, "ask", lambda dlg: "start"):
        scr.request_ai("node")
        wait(lambda: not scr.running())
    shoot_confirm(win, scr, "6-실행확인-구독-한도앎")
    nid = scr.node_set["nodes"][0]["node_id"]
    scr.open_cell(nid, scr.deviations[0]["deviation_id"])
    pump()
    save(win.grab().toImage(), "8-칸상세-출처")
    win.close()
    # 3. 한도 도달 띠와 '한도로 멈춤' 칸, API 키로 이어서
    win, scr = window("ok,rejected")
    with mock.patch.object(rmod.RunConfirmDialog, "ask", lambda dlg: "start"):
        scr.request_ai("node")
        wait(lambda: not scr.running())
    pump()
    save(win.grab().toImage(), "7-한도도달")
    shoot_confirm(win, scr, "7-API키로이어서-확인", scope="resume", method="api")
    win.close()
    # 4. 실행 중 창 닫기 물음과 기다림 창
    win, scr = window("hang")
    with mock.patch.object(rmod.RunConfirmDialog, "ask", lambda dlg: "start"):
        scr.request_ai("node")
        wait(lambda: scr.runner is not None and scr.runner.calls_in_flight() == 1, 30)
    pump(1.2)
    seen = {}

    def ask_close(n):
        from PySide6.QtWidgets import QMessageBox
        from hazop.app import conn_view
        box = QMessageBox(QMessageBox.Question, conn_view.CLOSE_TITLE, conn_view.CLOSE_TEXT % n, parent=scr)
        box.addButton(conn_view.CLOSE_WAIT, QMessageBox.AcceptRole)
        box.addButton(conn_view.CLOSE_NOW, QMessageBox.DestructiveRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.show()
        pump()
        save(compose(win, box), "닫기-물음")
        box.hide()
        seen["asked"] = True
        return "wait"
    scr.ask_close = ask_close
    win.close()
    wait(lambda: scr._close_wait_box.isVisible(), 5)
    pump(1.2)
    save(compose(win, scr._close_wait_box), "닫기-기다림")
    scr._close_now()
    wait(lambda: not win.isVisible(), 30)
    # 5. 고정 응답(디버그): 실행 확인과 시험 결과 띠
    win, scr = window("ok", method="api", debug=True)
    folder = os.path.join(tmp, "시험응답")
    os.makedirs(folder)
    units = ai_cells.plan_units(scr.node_set, scr.deviations)
    ctxs = scr._contexts(units)
    import json
    for u in units[:-1]:
        key = providers.fixed_key(ai_cells.build_request(u, ctxs[u["node_id"]], scr.deviations))
        with open(os.path.join(folder, key + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"output": shoot_results.FakeClient().analyze(ai_cells.build_request(
                u, ctxs[u["node_id"]], scr.deviations))["output"]}, fh, ensure_ascii=False)
    win.ai_prefs.set_fixed_dir(folder)
    win.ai_prefs.choose("fixed")
    shoot_confirm(win, scr, "6-실행확인-고정응답", scope="all")
    with mock.patch.object(rmod.RunConfirmDialog, "ask", lambda dlg: "start"):
        scr.request_ai("node")
        wait(lambda: not scr.running())
    scr.open_cell(units[0]["node_id"], units[0]["deviation_ids"][0])
    pump()
    save(win.grab().toImage(), "8-시험결과띠")
    win.close()
    app.processEvents()
    for f in files:
        print(f)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
