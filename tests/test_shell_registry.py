"""영역 등록표(hazop/shell/api.py MODULES·TOPIC_OWNER·PROJECT_BOUND)의 약속. 실행: python -m unittest tests.test_shell_registry

- 등록된 모든 영역의 명령은 프로젝트에 묶인다(웹은 프로젝트 A인데 엔진이 B인 상태의 저장이 거절된다). 모듈이 PROJECT_PREFIXES를 빠뜨려도 마찬가지다.
- 읽기 토픽은 한 모듈만 갖고, 이름이 겹치면 바로 알린다. 읽지 못하는 모듈은 그 영역만 꺼진다.
"""

import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.shell import api  # noqa: E402


class RegistryContractTest(unittest.TestCase):
    def test_every_command_of_a_registered_area_is_project_bound(self):
        heads = {t + "." for t in api.TOPIC_OWNER} | {"chat.action.", "sheet."}
        for topic in api.TOPIC_OWNER:
            self.assertIn(topic + ".", api.PROJECT_BOUND, "%s. 접두가 프로젝트에 묶이지 않음" % topic)
        for name in api.COMMANDS:
            if name.split(".", 1)[0] + "." in heads:
                self.assertTrue(name.startswith(api.PROJECT_BOUND), name)

    def test_the_knowledge_graph_commands_refuse_another_project(self):
        self.assertIn("kg.", api.PROJECT_BOUND)
        tmp = tempfile.mkdtemp(prefix="hazop-registry-")
        self.addCleanup(shutil.rmtree, tmp, True)
        engine = api.Engine(settings_path=os.path.join(tmp, "settings.json"))
        engine.settings["project_id"] = "REG-A"
        names = [c for c in api.COMMANDS if c.startswith(("kg.", "docs.", "sources.", "nodes.", "results.", "ie."))]
        self.assertTrue(any(n.startswith("kg.") for n in names))
        for name in names:
            r = engine.dispatch(name, {}, project="REG-B", via_web=True)
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "wrong_project"), name)
            r = engine.dispatch(name, {}, via_web=True)
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"), name + ": 프로젝트 ID 없이 보낸 웹 명령")

    def test_a_module_that_leaves_out_project_prefixes_is_bound_by_default(self):
        stub = types.ModuleType("hazop.shell.api_zeta")
        stub.read = lambda engine, parts, query: None
        stub.register = lambda commands: commands.update({"zeta.save": api.Command({}, lambda e, a: {}, "시험용")})
        with mock.patch.dict(sys.modules, {"hazop.shell.api_zeta": stub}), mock.patch.object(api, "MODULES", ("api_zeta",)), \
                mock.patch.dict(api.COMMANDS), mock.patch.dict(api.TOPIC_OWNER, clear=True), mock.patch.dict(api.LOADED, clear=True):
            bound = api._load_modules()
        self.assertIn("zeta.", bound)
        self.assertIn("chat.action.", bound)

    def test_a_module_can_bind_extra_prefixes_and_opt_out_explicitly(self):
        stub = types.ModuleType("hazop.shell.api_eta")
        stub.TOPICS = ("eta",)
        stub.PROJECT_PREFIXES = ("extra.",)
        stub.UNBOUND_PREFIXES = ("loose.",)
        stub.read = lambda engine, parts, query: None
        stub.register = lambda commands: commands.update({"eta.go": api.Command({}, lambda e, a: {}, "x"), "loose.go": api.Command({}, lambda e, a: {}, "x")})
        with mock.patch.dict(sys.modules, {"hazop.shell.api_eta": stub}), mock.patch.object(api, "MODULES", ("api_eta",)), \
                mock.patch.dict(api.COMMANDS), mock.patch.dict(api.TOPIC_OWNER, clear=True), mock.patch.dict(api.LOADED, clear=True):
            bound = api._load_modules()
        self.assertTrue({"eta.", "extra."} <= set(bound))
        self.assertNotIn("loose.", bound)

    def test_duplicate_topics_and_commands_are_refused_and_a_missing_module_is_skipped(self):
        stub = types.ModuleType("hazop.shell.api_theta")
        stub.TOPICS = ("nodes",)
        stub.read = lambda engine, parts, query: None
        with mock.patch.dict(sys.modules, {"hazop.shell.api_theta": stub}), mock.patch.object(api, "MODULES", ("api_nodes", "api_theta")), \
                mock.patch.dict(api.COMMANDS), mock.patch.dict(api.TOPIC_OWNER, clear=True), mock.patch.dict(api.LOADED, clear=True):
            with self.assertRaises(ValueError):
                api._load_modules()
        with mock.patch.object(api, "MODULES", ("api_does_not_exist",)), mock.patch.dict(api.COMMANDS), \
                mock.patch.dict(api.TOPIC_OWNER, clear=True), mock.patch.dict(api.LOADED, clear=True):
            with self.assertLogs("hazop.shell.api", level="ERROR"):
                bound = api._load_modules()
        self.assertEqual(bound, ("chat.action.", "sheet."))


if __name__ == "__main__":
    unittest.main()
