"""프로젝트에 묶인 명령의 공통 검사(hazop/shell/api.py dispatch). 실행: python -m unittest tests.test_shell_project

재현(검토 반려 3): 프로젝트 A에서 읽은 구간 목록(set_rev·targets)으로 보낸 nodes.confirm이 프로젝트를 바꾼 뒤에도 ok가 되어 B의 같은 ID 구간을 확정했다.
이제 웹이 보내는 명령은 본 프로젝트 ID를 실어야 하고, 지금 프로젝트와 다르면 아무것도 쓰지 않고 거절한다. 영역 파일(구간·결과·초기사건·채팅 동작)은 이 한 곳의 검사를 따른다.
"""

import copy
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.shell import api, api_nodes  # noqa: E402
from tests.test_shell_nodes import Env  # noqa: E402


class ProjectBoundTest(Env):
    def setUp(self):
        super().setUp()
        from hazop.app import project_ctx
        self.a = self.pg
        self.b = copy.deepcopy(self.a)
        self.b["project_id"] = "OTHER"
        p = mock.patch.object(project_ctx, "project_graph", lambda pid: self.b if pid == "OTHER" else self.a)
        p.start()
        self.addCleanup(p.stop)

    def two_projects(self):
        self.create(name="A 프로젝트 가압기 구간")
        self.engine.dispatch("project.set", {"project_id": "OTHER"})
        self.pg = self.b
        self.create(name="B 프로젝트 다른 구간")
        self.engine.dispatch("project.set", {"project_id": "SNP"})
        web = api_nodes.summary(self.engine)                       # 웹이 A에서 읽어 들고 있는 목록
        self.engine.dispatch("project.set", {"project_id": "OTHER"})  # 위 막대에서 프로젝트를 바꿈
        return web

    def confirm_args(self, web):
        n = web["nodes"][0]
        return {"project_id": web["project_id"], "node_ids": [n["node_id"]], "set_rev": web["set_rev"], "targets": [{"node_id": n["node_id"], "rev": n["rev"], "state": n["state"]}]}

    def test_a_stale_web_list_cannot_confirm_a_node_of_the_other_project(self):
        web = self.two_projects()
        r = self.engine.dispatch("nodes.confirm", self.confirm_args(web), project="SNP", via_web=True)
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "wrong_project"), r)
        states = {n["node_id"]: n["state"] for n in api_nodes.summary(self.engine)["nodes"]}
        self.assertEqual(set(states.values()), {"applied"}, "B의 구간은 그대로: %s" % states)

    def test_the_same_project_passes_and_missing_project_is_refused_for_web(self):
        self.create(name="가")
        web = api_nodes.summary(self.engine)
        ok = self.engine.dispatch("nodes.confirm", self.confirm_args(web), project="SNP", via_web=True)
        self.assertTrue(ok["ok"], ok)
        web = api_nodes.summary(self.engine)
        r = self.engine.dispatch("nodes.unconfirm", dict(self.confirm_args(web)), via_web=True)
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"), "웹이 보낸 명령은 프로젝트 ID가 있어야 한다")

    def test_every_project_bound_command_family_is_checked(self):
        for name in ("results.set_status", "results.run", "ie.suggest", "chat.action.approve", "nodes.create"):
            r = self.engine.dispatch(name, {}, project="NOT-THIS", via_web=True)
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "wrong_project"), name)
        for name in api.COMMANDS:
            if name.startswith(api.PROJECT_BOUND):
                continue
            self.assertFalse(any(name.startswith(p) for p in ("nodes.", "results.", "ie.")), name)

    def test_project_switch_tells_the_web_to_reread_every_area(self):
        self.engine.dispatch("project.set", {"project_id": "OTHER"})
        topics = [e.get("topic") for e in self.events if e.get("t") == "changed"]
        for t in ("drawings", "state", "nodes", "results", "ie"):
            self.assertIn(t, topics)
        self.assertIn("project.changed", [e.get("name") for e in self.events if e.get("t") == "event"])

    def test_non_bound_commands_ignore_the_project_field(self):
        r = self.engine.dispatch("settings.set_reviewer", {"name": "검토자B"}, project="ANY", via_web=True)
        self.assertTrue(r["ok"], r)


if __name__ == "__main__":
    unittest.main()
