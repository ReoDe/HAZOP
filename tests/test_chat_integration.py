"""채팅 끝에서 끝까지 시험(단위 C2 통합). 실행: python -m unittest tests.test_chat_integration

가상 도면 SNP-M-101·102를 임시 작업 루트에서 추출한 뒤, 실제 MainWindow 안의 채팅 창이 실제 `ChatSession`·실제 MCP 도구 서버로
질문 → 도구 호출 → 답 카드 → 도면 위 경로 표시(도면을 넘는 경로 포함)까지 가는지 본다. CLI만 가짜(tests/fake_claude)다.
실제 구독 호출·실제 창 조작은 없다.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from PySide6.QtWidgets import QPushButton  # noqa: E402

from scripts.check_edit_screen import install_sample  # noqa: E402
from tests.test_app import pump, tearDownModule, wait_for  # noqa: E402,F401

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(REPO, "tests", "fake_claude", "fake_claude.py")
S101, S102 = "graph-SNP-M-101", "graph-SNP-M-102"


class ChatIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-chatint-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop.app import make_application
        cls.qapp = make_application(["test"])
        cls.names = [install_sample(os.environ["HAZOP_WORK_ROOT"], d) for d in ("SNP-M-101", "SNP-M-102")]

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def window(self, width=1920):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=os.path.join(tempfile.mkdtemp(dir=self.tmp), "settings.json"), ask_reviewer=False)
        win.resize(width, 900)
        win.show()
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.webview.dispose)
        self.addCleanup(win.close)
        pump(win, 0.1)
        win.go(1)
        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready), "웹뷰 준비 안 됨")
        pump(win, 0.3)
        return win

    def fake_session(self, win, answer, calls):
        """채팅 창의 세션을 가짜 CLI + 실제 MCP 서버로 바꿔 끼운다."""
        from hazop.chat.session import ChatSession
        script = os.path.join(tempfile.mkdtemp(dir=self.tmp), "script.json")
        with open(script, "w", encoding="utf-8") as fh:
            json.dump({"turns": [{"calls": calls, "answer": answer}]}, fh, ensure_ascii=False)
        log = tempfile.mkdtemp(dir=self.tmp)
        pid = win._chat_project_id()
        self.assertTrue(pid)
        win.chat_panel._factory = lambda model, cb: ChatSession(
            pid, model=model, argv_prefix=[sys.executable, FAKE, "chat@" + script, log], **cb)
        return log

    def trace(self, win, start, end):
        from hazop.chat import tools
        env, _pg = win._chat_env()
        res = tools.call(env.ctx, "trace_path", {"start": start, "end": end})
        self.assertTrue(res["ok"], res)
        tag = {n["tag"]: n["entity_id"] for n in env.ctx.pg["nodes"] if n.get("tag") and n["node_type"] != "pipe_segment"}
        return res["data"]["path"]["path_ref"], tag

    def test_question_to_card_to_cross_sheet_path_on_drawing(self):
        win = self.window()
        ref, tag = self.trace(win, "RC-RV01", "RC-PZ01")
        answer = {"text": "원자로 RC-RV01에서 가압기 RC-PZ01까지 두 도면에 걸쳐 이어집니다.", "general": "",
                  "refs": [{"kind": "component", "id": tag["RC-RV01"]}, {"kind": "component", "id": tag["RC-PZ01"]}],
                  "paths": [{"label": "RC-RV01 → RC-PZ01", "path_ref": ref}], "highlight": [], "warnings": [], "actions": []}
        self.fake_session(win, answer, [{"name": "trace_path", "args": {"start": "RC-RV01", "end": "RC-PZ01"}}])
        panel = win.chat_panel
        self.assertTrue(panel.ask("RC-RV01에서 RC-PZ01까지 경로를 알려줘"))
        self.assertTrue(wait_for(lambda: not panel.busy(), 60), "답이 오지 않음")
        pump(win, 0.3)
        self.assertEqual(len(panel.cards()), 1)
        card = panel.cards()[0].card
        self.assertEqual((card.dropped, card.ungrounded), (0, 0), "도구 결과에 나온 ID만 근거로 친다")
        self.assertEqual(len(card.paths), 1, card.path_notes)
        tags = [c["tag"] for c in card.paths[0].chips]
        self.assertEqual((tags[0], tags[-1]), ("RC-RV01", "RC-PZ01"))
        self.assertEqual([s for s, _ in card.paths[0].sheets], [S101, S102])
        self.assertIn("도면", card.badges)
        self.assertEqual(card.paths[0].sheet_labels, {S101: "SNP-M-101", S102: "SNP-M-102"})
        self.assertIn("도면 연결점", tags, "태그 없는 연결점은 '도면 연결점'으로 보인다")
        # 도면 위: 지금 도면(101)에 먼저 그리고, 도면별 단추로 102로 옮겨 가 그린다
        host = win.viewer_host
        rid = panel._rid
        self.assertTrue(rid)
        self.assertEqual(sorted(host._marks[rid]), [S101, S102])
        self.assertTrue(host._sent.get(rid), "지금 도면에 경로를 그렸다")
        before = host.current_sheet()
        btn = next(b for b in panel.findChildren(QPushButton) if b.objectName() == "chat_sheet" and b.text().startswith("SNP-M-102"))
        btn.click()
        self.assertTrue(wait_for(lambda: host.current_sheet() == S102 and host._sent.get(rid), 30), "102로 옮겨 그리지 못함")
        self.assertNotEqual(before, host.current_sheet())

    def test_answer_citing_an_id_the_tools_never_returned_is_marked_ungrounded(self):
        win = self.window()
        _ref, tag = self.trace(win, "RC-RV01", "RC-PZ01")
        # 도구는 count만 불렀는데 답은 구성요소 하나를 근거라고 댄다
        answer = {"text": "제어밸브가 있습니다.", "general": "", "refs": [{"kind": "component", "id": tag["RC-PZ01"]}],
                  "paths": [], "highlight": [], "warnings": [], "actions": []}
        self.fake_session(win, answer, [{"name": "count", "args": {"group_by": "kind"}}])
        panel = win.chat_panel
        panel.ask("제어밸브는 몇 개야?")
        self.assertTrue(wait_for(lambda: not panel.busy(), 60))
        pump(win, 0.2)
        card = panel.cards()[0].card
        self.assertEqual(card.ungrounded, 1)
        self.assertEqual(card.refs, [])

    def test_example_questions_use_project_tags_when_opened(self):
        win = self.window(1366)
        win.open_chat()
        pump(win, 0.5)
        texts = " ".join(b.text() for b in win.chat_panel.findChildren(QPushButton) if b.objectName() == "chat_example")
        self.assertRegex(texts, r"RC-[A-Z0-9]+")


if __name__ == "__main__":
    unittest.main()
