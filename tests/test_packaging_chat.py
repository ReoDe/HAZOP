"""배포본의 채팅(P16, 규격 docs/specs/chat-panel.md §8·§10 P16 줄) 시험. 빌드 없이 돈다. 실제 구독·CLI 호출 없음.

- 묶음 목록(build_package.hazop_modules)에 채팅 모듈이 들어간다.
- packaging/verify_bundle.chat_tools_problems가 개발 환경 서버의 실제 응답을 통과시키고, 망가진 응답은 잡는다.
- 배포본에서도 구독 연결을 고를 수 있다(U3 2026-11-13 개정, DEC-0306). 서버 명령은 HAZOP.exe --chat-tools다.
실행: python -m unittest tests.test_packaging_chat
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from hazop.chat import session
from hazop.study import providers

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO_ROOT, *rel.split("/")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BundleChatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vb = _load("packaging/verify_bundle.py", "hazop_verify_bundle_chat")
        cls.bp = _load("scripts/build_package.py", "hazop_build_package_chat")
        cls.tmp = tempfile.mkdtemp(prefix="hazop-pkg-chat-")
        q = os.path.join(cls.tmp, "q.json")
        with open(q, "w", encoding="utf-8") as fh:
            json.dump({"question_id": "q-verify"}, fh)
        data = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in cls.vb.CHAT_REQUESTS).encode("utf-8")
        env = dict(os.environ, HAZOP_WORK_ROOT=os.path.join(cls.tmp, "work"))
        p = subprocess.run([sys.executable, "-E", "-s", os.path.join(REPO_ROOT, "scripts", "run_chat_tools_server.py"),
                            "--project", "verify", "--question-file", q], input=data, capture_output=True, env=env,
                           cwd=cls.tmp, timeout=120)
        cls.rc, cls.out, cls.err = p.returncode, p.stdout, p.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_chat_modules_in_bundle_list(self):
        mods = self.bp.hazop_modules()
        for m in ("hazop.chat", "hazop.chat.mcp_server", "hazop.chat.session", "hazop.chat.registry",
                  "hazop.chat.tools", "hazop.chat.context"):
            self.assertIn(m, mods)

    def test_dev_server_passes_bundle_check(self):
        self.assertEqual(self.vb.chat_tools_problems(self.rc, self.out, self.err), [],
                         self.err.decode("utf-8", "replace"))

    def test_check_catches_broken_replies(self):
        vb = self.vb
        self.assertTrue(vb.chat_tools_problems(1, self.out, b""))
        self.assertTrue(vb.chat_tools_problems(0, b"hello\n" + self.out, b""))
        self.assertTrue(vb.chat_tools_problems(0, b"", b""))
        self.assertTrue(vb.chat_tools_problems("timeout", b"", b""))
        lines = [json.loads(x) for x in self.out.decode("utf-8").splitlines()]
        for r in lines:
            if r.get("id") == 2:
                r["result"]["tools"] = [t for t in r["result"]["tools"] if t["name"] != "trace_path"]
            if r.get("id") == 4:
                r["result"]["content"][0]["text"] = "ok"
        broken = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines).encode("utf-8")
        probs = vb.chat_tools_problems(0, broken, b"")
        self.assertEqual(len(probs), 2, probs)

    def test_bundle_offers_subscription_and_runs_server_from_exe(self):
        with mock.patch("hazop.paths.frozen_bundle_dir", return_value="C:/HAZOP/_internal"):
            self.assertIn("subscription", providers.available_methods())
            self.assertNotIn("fixed", providers.available_methods())
            cmd = session.server_command("p", "q.json")
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1:3], ["--chat-tools", "--project"])

    def test_verify_requires_chat_check(self):
        with open(os.path.join(REPO_ROOT, "packaging", "verify_bundle.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('not checks.get("chat_tools_problems", ["미실행"])', src)
        self.assertIn("chat_tools_step(", src)


if __name__ == "__main__":
    unittest.main()
