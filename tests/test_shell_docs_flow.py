"""설계 문서 패널을 실제 틀 창(ShellWindow, 오프스크린)에 임시로 이어 본다. 실행: python -m unittest tests.test_shell_docs_flow

패널 등록 줄(api.py MODULES, panels/index.js, window.py의 pick_doc)은 틀 담당(s-frame)이 넣는다. 그 전에도 확인할 수 있게 이 시험은 읽기 API에 docs 길을,
명령 표에 docs.*를 시험 안에서만 잇고 패널은 웹에서 모듈을 읽어 화면 가운데에 따로 그린다. 파일 고르기 창은 가짜(pick_doc)다.
샘플 SNP-M-101·102(가상 도면)는 등록 없이 추출된 것이라 문서와 도면의 이어짐은 엔진 시험(test_shell_docs)이 본다.
"""

import glob
import json
import os
import unittest
from unittest import mock

from hazop.shell import api, api_docs
from tests.test_shell_web import ShellBase, pump, wait_for

DOC_PDF = glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "docextract", "*.pdf"))[0]
BASE = "document.baseURI"
MOUNT = """(async () => {
  if (!document.querySelector('.docs')) {
    const H = await import(new URL('js/ui/html.js', document.baseURI).href);
    const M = await import(new URL('js/panels/docs.js', document.baseURI).href);
    const host = document.createElement('div'); host.id = 'docs-host';
    document.querySelector('.center').appendChild(host);
    H.render(H.html`<${M.DocsPanel} onClose=${() => { H.render(null, host); }} />`, host);
  }
  return true; })()"""


class DocsPanelFlowTest(ShellBase):
    n = 0

    def setUp(self):
        real = api.ReadApi.read

        def read(this, parts, query):
            if parts and parts[0] == "docs":
                return api_docs.read(this.engine, parts, query)
            return real(this, parts, query)
        for p in (mock.patch.object(api.ReadApi, "read", read), mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        if "docs.add" not in api.COMMANDS:
            api_docs.register(api.COMMANDS)

    def mount(self, win):
        DocsPanelFlowTest.n += 1
        self.switch_project(win, "A7-FLOW-%d" % DocsPanelFlowTest.n)     # 시험마다 새 프로젝트(작업 루트는 클래스가 함께 씀)
        win.engine.hooks["pick_doc"] = lambda: [DOC_PDF]
        self.js(win, MOUNT)
        self.assertTrue(wait_for(lambda: "등록한 설계 문서가 없습니다" in self.text(win), 20), self.text(win)[-300:])

    def test_add_extract_and_read_items(self):
        win = self.window()
        self.mount(win)
        self.assertIn("스캔 PDF는 지원하지 않습니다", self.text(win))
        self.click(win, ".docs .btn.primary")
        self.assertTrue(wait_for(lambda: "추출함" in self.text(win), 60), self.text(win)[-500:])
        t = self.text(win)
        self.assertIn("설정치 3", t)
        self.assertIn("요건 4", t)
        self.assertIn("등록 버전 1", t)
        self.click(win, ".docs-doc .btn:not(.primary)")             # 뽑힌 항목 보기
        self.assertTrue(wait_for(lambda: "자동 추출 · 사람 확인 전" in self.text(win), 15), self.text(win)[-400:])
        self.assertIn("16.6", self.text(win))

    def test_same_document_again_says_it_is_already_there(self):
        win = self.window()
        self.mount(win)
        self.click(win, ".docs .btn.primary")
        self.assertTrue(wait_for(lambda: "추출함" in self.text(win), 60))
        self.click(win, ".docs .btn.primary")
        self.assertTrue(wait_for(lambda: len(win.engine.running_jobs()) == 0 and "시작했습니다" in self.text(win), 30))
        pump(1.0)
        self.assertEqual(self.text(win).count("등록 버전 1"), 1)         # 같은 문서는 한 줄
        self.assertEqual(self.js(win, "document.querySelectorAll('.docs-doc').length"), 1)

    def test_chat_open_event_opens_the_panel_state(self):
        win = self.window()
        self.js(win, "import(new URL('js/panels/docs_state.js', document.baseURI).href)")
        pump(0.5)
        api_docs.open_panel(win.engine)
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().panel") == "docs", 10))

    def test_no_console_errors_or_remote_requests(self):
        win = self.window()
        self.mount(win)
        self.click(win, ".docs .btn.primary")
        self.assertTrue(wait_for(lambda: "추출함" in self.text(win), 60))
        pump(1.0)
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [])
        self.assertEqual(win.view.interceptor.blocked, [], "실행 중 원격 요청 0")


if __name__ == "__main__":
    unittest.main()
