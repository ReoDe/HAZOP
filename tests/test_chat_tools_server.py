"""채팅 읽기 도구를 MCP 서버(hazop.chat.mcp_server)로 왕복하는 시험(단위 C1). 실제 구독·CLI 없음.

SNP 가상 도면 그래프에 규격 §2.2의 질문 Q0·Q1이 부르는 도구를 서버의 tools/call로 부르고, 서버가 내주는 cursor가 인자에
묶이는지, 도구 목록의 스키마가 서버가 내는 값을 받는지 본다. 실행: python -m unittest tests.test_chat_tools_server
"""

import json
import os
import re
import shutil
import tempfile
import unittest

from hazop.chat import mcp_server, registry
from tests.test_chat_tools import S102, ChatToolsBase


class ServerRoundTripTest(ChatToolsBase):
    def setUp(self):
        self.qdir = tempfile.mkdtemp(prefix="hazop-chattools-q-")
        self.qfile = os.path.join(self.qdir, "question.json")
        self.n = 0
        self.server = mcp_server.Server(registry.REGISTRY, "SNP-SAMPLE", self.qfile, loader=lambda pid: self.ctx,
                                        refresher=lambda ctx: ctx)
        self.new_question()

    def tearDown(self):
        shutil.rmtree(self.qdir, ignore_errors=True)

    def new_question(self):
        self.n += 1
        with open(self.qfile, "w", encoding="utf-8") as fh:
            json.dump({"question_id": "q-%d" % self.n}, fh)

    def rpc(self, name, **args):
        rep = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        text = rep["result"]["content"][0]["text"]
        self.assertTrue(text.startswith(mcp_server.PREFIX))
        self.assertLessEqual(len(text), mcp_server.MAX_RESULT_CHARS)
        return json.loads(text.split("\n", 1)[1])

    def test_tools_list_matches_registry_and_cursor_schema(self):
        rep = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        listed = {t["name"]: t for t in rep["result"]["tools"]}
        self.assertEqual(sorted(listed), sorted(registry.REGISTRY))
        for name, t in listed.items():
            pat = t["inputSchema"]["properties"].get("cursor", {}).get("pattern")
            if pat:
                self.assertTrue(re.match(pat, "c-0123456789ab"), name)

    def test_q0_valves_on_path(self):
        """Q0 'RC-PZ01에서 RC-PSV101까지 배관 경로에 있는 밸브 태그': 도구 한 번(trace_path)으로 답이 나온다."""
        env = self.rpc("trace_path", start="RC-PZ01", end="RC-PSV101")
        self.assertTrue(env["ok"], env["error"])
        steps = env["data"]["path"]["steps"]
        valves = [x["tag"] for x in steps if x["kind"] in ("psv", "manual_valve", "control_valve", "check_valve")]
        self.assertEqual(valves, ["RC-PSV101"])
        self.assertEqual(env["data"]["path"]["path_ref"]["basis"], "ignoring_direction")

    def test_q1_control_valves_and_neighbors(self):
        """Q1 '제어밸브는 몇 개이고 태그는 무엇이야? 그중 RC-PZ01과 바로 이어진 것': search/count 후 neighbors."""
        cnt = self.rpc("count", filter={"kinds": ["control_valve"]}, group_by="kind")
        self.assertEqual(cnt["data"]["groups"], [{"key": "control_valve", "count": 3}])
        found = self.rpc("search", filter={"kinds": ["control_valve"]})
        tags = sorted(x["tag"] for x in found["data"]["items"])
        self.assertEqual(len(tags), 3)
        self.assertIn("RC-PV101", tags)
        nb = self.rpc("neighbors", id="RC-PZ01")
        self.assertTrue(nb["ok"])
        near = {v["node"]["tag"] for v in nb["data"]["via_segment"]}
        self.assertTrue(near)

    def test_cursor_from_server_is_bound_to_arguments(self):
        first = self.rpc("trace_flow", start="RC-RV01", direction="down", limit=5)
        self.assertTrue(first["cursor"])
        self.assertRegex(first["cursor"], r"^c-[0-9a-f]{12}$")
        other = self.rpc("trace_flow", start="RC-PZ01", direction="up", limit=5, cursor=first["cursor"])
        self.assertFalse(other["ok"])
        self.assertEqual(other["error"]["code"], "bad_args")
        same = self.rpc("trace_flow", start="RC-RV01", direction="down", limit=5, cursor=first["cursor"])
        self.assertTrue(same["ok"])
        self.assertNotEqual([x["id"] for x in same["data"]["reached"]], [x["id"] for x in first["data"]["reached"]])

    def test_path_like_arguments_never_reach_the_tools(self):
        for bad in ("../x", "C:\\Windows", "/etc/passwd"):
            env = self.rpc("get_component", id=bad)
            self.assertEqual(env["error"]["code"], "bad_args")


if __name__ == "__main__":
    unittest.main()
