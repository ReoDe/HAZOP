"""API 키 설정 창 스크린샷. 사용: python scripts/shoot_apikey.py <출력 폴더>

1366×768 주 창 위에 키 설정 창을 띄운 장면 셋을 찍는다: 연결됨, 오류(크레딧 부족), 키 여러 개 드롭다운 펼침.
키는 가짜 값이고 메모리에만 둔다(임시 설정 폴더, 네트워크 없음 - 가짜 opener). 화면 글자에 키가 보이면 실패한다.
"""

import json
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

KEYS = (("회사 워크스페이스", "sk-ant-api03-FAKEFAKEFAKE-shot-only-a1b2"),
        ("개인 시험용", "sk-ant-api03-FAKEFAKEFAKE-shot-only-c3d4"),
        ("팀 공용(이번 실행만)", "sk-ant-api03-FAKEFAKEFAKE-shot-only-e5f6"))


class Opener:
    def __init__(self, status=200, body=b"{}"):
        self.status, self.body = status, body

    def __call__(self, url, headers, body, timeout):
        return self.status, self.body


def compose(win, dlg, popup=None):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter
    img = win.grab().toImage()
    p = QPainter(img)
    d = dlg.grab()
    at = QPoint((img.width() - d.width()) // 2, max(20, (img.height() - d.height()) // 2))
    p.drawPixmap(at, d)
    if popup is not None:
        combo, view = popup
        pos = at + combo.mapTo(dlg, QPoint(0, combo.height()))
        p.drawPixmap(pos, view.grab())
    p.end()
    return img


def main():
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO_ROOT, "출력", "스크린샷", "apikey"))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shoot-apikey-")
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    try:
        from PySide6.QtWidgets import QApplication, QComboBox, QLabel
        from hazop.app.main_window import MainWindow
        from hazop.app.screenshots import wait
        from hazop.app.settings_dialog import SettingsDialog

        app = QApplication.instance() or QApplication([])
        win = MainWindow(settings_path=os.path.join(tmp, "settings.json"), ask_reviewer=False)
        win.resize(1366, 768)
        win.show()
        for name, key in KEYS:
            win.api_keys.add(name, key, persist=False)
        win.api_keys.select(win.api_keys.entries()[0]["id"])
        files = []

        def scene(name, opener, popup=False):
            dlg = SettingsDialog(win.api_keys, win, opener=opener)
            dlg.show()
            dlg.test_connection()
            dlg.tasks.wait(10000)
            wait(lambda: dlg.test_btn.isEnabled(), 5)
            win._update_ai_label()
            app.processEvents()
            text = "\n".join([w.text() for w in dlg.findChildren(QLabel)] + [win.ai_label.text()]
                             + [c.itemText(i) for c in dlg.findChildren(QComboBox) for i in range(c.count())])
            for _n, key in KEYS:
                if key in text:
                    raise SystemExit("화면 글자에 API 키가 보임")
            pop = None
            if popup:
                dlg.key_combo.showPopup()
                app.processEvents()
                pop = (dlg.key_combo, dlg.key_combo.view())
            path = os.path.join(out_dir, "%s.png" % name)
            compose(win, dlg, pop).save(path)
            if popup:
                dlg.key_combo.hidePopup()
            dlg.close()
            files.append(path)

        scene("1-연결됨-1366", Opener())
        credit = json.dumps({"error": {"type": "invalid_request_error",
                                       "message": "Your credit balance is too low to access the Anthropic API."}})
        scene("2-오류-크레딧부족-1366", Opener(400, credit.encode("utf-8")))
        scene("3-키여러개-드롭다운-1366", Opener(), popup=True)
        print("\n".join(files))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
