"""AI 연결 화면 스크린샷(디자인/AI연결-화면설계.md 시안과 나란히 보기). 사용:
    python scripts/shoot_ai_connection.py <출력 폴더> [--scale 1.25]

주 창(1366×768, --scale 1.25면 논리 1536×864 = 1920×1080 화면) 위에 장면을 찍는다: 설정 창(구독 연결됨, 구독 로그인 필요,
API 키, 실행 중, 배포본), 이용 조건 창, 상태줄 연결 칩(넓은·좁은 형식)과 칩 상세 창. 상태는 가짜 값이다(실제 CLI·네트워크 없음).
키는 가짜 값이고 메모리에만 둔다. 화면 글자에 키가 보이면 실패한다.
"""

import argparse
import datetime
import os
import shutil
import sys
import tempfile
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from hazop import paths  # noqa: E402
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

KEYS = (("회사 워크스페이스", "sk-ant-api03-FAKEFAKEFAKE-shot-only-a1b2"),)


def kst_today(h, m):
    from hazop.study import claude_cli
    now = datetime.datetime.now(claude_cli.KST)
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def sub_ok():
    seen = kst_today(14, 2).isoformat(timespec="seconds")
    return {"via": "subscription", "state": "ok", "detail": "", "plan": "max_20x", "checked_at": seen,
            "limit": {"status": "limit_ok", "window": "five_hour", "utilization": 0.38,
                      "resets_at": int(kst_today(17, 40).timestamp()), "seen_at": seen}}


def compose(win, dlg):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter
    img = win.grab().toImage()
    p = QPainter(img)
    d = dlg.grab()
    ratio = d.devicePixelRatio() or 1.0
    at = QPoint(int((img.width() / (img.devicePixelRatio() or 1) - d.width() / ratio) // 2),
                int(max(20, (img.height() / (img.devicePixelRatio() or 1) - d.height() / ratio) // 2)))
    p.drawPixmap(at, d)
    p.end()
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=os.path.join(paths.DEV_WORK_ROOT, "출력", "스크린샷", "AI연결"))
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args()
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    tag = "1366" if args.scale == 1.0 else "1920"
    size = (1366, 768) if args.scale == 1.0 else (1536, 864)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shoot-ai-")
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    try:
        from PySide6.QtWidgets import QApplication, QComboBox, QLabel
        from hazop.app.ai_conn import AiConnection
        from hazop.app.main_window import MainWindow
        from hazop.app.settings_dialog import SettingsDialog, TermsDialog
        from hazop.study.ai_settings import AiPrefs

        app = QApplication.instance() or QApplication([])
        win = MainWindow(settings_path=os.path.join(tmp, "settings.json"), ask_reviewer=False)
        win.resize(*size)
        win.show()
        for name, key in KEYS:
            win.api_keys.add(name, key, persist=False)
        win.set_conn_status(sub_ok())
        files = []

        def save(img, name):
            path = os.path.join(out_dir, "%s-%s.png" % (name, tag))
            img.save(path)
            files.append(path)

        def check_text(dlg):
            text = "\n".join([w.text() for w in dlg.findChildren(QLabel)]
                             + [c.itemText(i) for c in dlg.findChildren(QComboBox) for i in range(c.count())])
            for _n, key in KEYS:
                if key in text:
                    raise SystemExit("화면 글자에 API 키가 보임")

        def scene(name, method, conn=None, before=None):
            dlg = SettingsDialog(win.api_keys, win, conn=conn or win.ai_conn)
            dlg.select(method)
            if before:
                before(dlg)
            dlg.show()
            app.processEvents()
            check_text(dlg)
            save(compose(win, dlg), name)
            dlg.close()
            dlg.deleteLater()

        scene("1-연결설정-구독", "subscription", before=lambda d: d.say("연결 확인 성공."))
        win.set_conn_status(dict(sub_ok(), state="login_required", plan=None, limit=None))
        scene("9-연결설정-구독-로그인필요", "subscription")
        win.set_conn_status(sub_ok())
        scene("2-연결설정-API키", "api")
        win.ai_conn.cancel_handler = lambda: None
        win.ai_conn.set_running(True, "AI 분석 실행 중 · 4/10 호출")
        scene("3-연결설정-실행중", "subscription")
        win.ai_conn.set_running(False)
        with mock.patch.object(sys, "_MEIPASS", tmp, create=True):
            bundle = AiConnection(AiPrefs(), win.api_keys)
            scene("10-배포본", "api", conn=bundle)
        terms = TermsDialog(win)
        terms.show()
        app.processEvents()
        save(compose(win, terms), "4-구독처음사용")
        terms.close()

        # 연결 칩: 넓은 형식(빈 상태줄)과 좁은 형식(긴 메시지·저장 시각이 있는 상태줄), 칩 상세 창
        limit = {"status": "limit_reached", "window": "five_hour", "resets_at": int(kst_today(17, 40).timestamp())}
        win.set_conn_status(dict(sub_ok(), state="limit_reached", limit=limit))
        win.status_message("")
        app.processEvents()
        save(win.grab().toImage(), "5-연결칩-상태줄-빈메시지")
        win.drawing_label.setText("SNP-M-102")
        win.count_label.setText("구간 5 · 칸 30")
        for lab in (win.drawing_label, win.count_label):
            lab.show()
        win.status_message("AI 분석 멈춤(한도 도달): 4/10 호출 · 2:41 걸림 · 저장: C:\\HAZOP\\자료저장소\\결과\\SNP-M-102.json")
        win.saved_label.setText("● 저장됨 14:20")
        win.saved_label.show()
        win._fit_conn_chip()
        app.processEvents()
        save(win.grab().toImage(), "5-연결칩-상태줄-메시지")
        win.count_label.setText("구간 5 · 칸 30 · 미검토 12 · 실패 2")
        win.task_label.setText("진행 중: AI 분석 실행")
        win.task_label.show()
        win._fit_conn_chip()
        app.processEvents()
        save(win.grab().toImage(), "5-연결칩-상태줄-좁은형식")
        win.task_label.setText("")
        win.task_label.hide()
        pop = win.open_conn_popup()
        app.processEvents()
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPainter
        img = win.grab().toImage()
        p = QPainter(img)
        p.drawPixmap(win.mapFromGlobal(pop.pos()) if pop.isVisible() else QPoint(img.width() - 360, 400), pop.grab())
        p.end()
        save(img, "5-연결칩-상세창")
        pop.close()
        print("\n".join(files))
        print("chip:", win.conn_chip.text(), "|", win.conn_chip.accessibleName())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
