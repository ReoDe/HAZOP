"""새 웹 화면의 '같은 도면 번호의 원본이 여러 형식일 때' 읽기·선택 명령과 등록 알림(hazop/shell/api_drawings.py, register_flow).
실행: python -m unittest tests.test_shell_sources

충돌 사실과 선택 저장은 hazop.graph.sources(c1-tools 몫)가 하고, 이 시험은 화면 쪽 길(읽기 `sources`, 명령 `sources.choose`, 프로젝트 묶음,
바뀜 알림, 그래프 캐시 갱신, 등록 결과의 `conflicts`)만 본다.
"""

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.app import project_ctx  # noqa: E402
from hazop.graph import sources  # noqa: E402
from hazop.shell import api, register_flow  # noqa: E402
from tests import test_drawing_sources as S  # noqa: E402


class Events:
    def __init__(self):
        self.items = []

    def __call__(self, event):
        self.items.append(event)

    def topics(self):
        return [e.get("topic") for e in self.items if e.get("t") == "changed"]


class SourcesApiTest(S.Base):
    def setUp(self):
        super().setUp()
        self.events = Events()
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events)
        self.engine.settings["project_id"] = S.PROJECT
        self.engine.settings["reviewer_name"] = "검토자A"

    def read(self):
        r = api.ReadApi(self.engine).read(["sources"], {})
        self.assertIsNotNone(r)
        return json.loads(r.body.decode("utf-8"))

    def choose(self, fmt, project=S.PROJECT):
        return self.engine.dispatch("sources.choose", {"drawing_number": S.DWG, "format": fmt}, project=project, via_web=True)

    def both(self):
        self.drawio_pair(age=60)
        self.dexpi_pair(age=0)

    def test_no_conflict_reads_an_empty_list(self):
        self.drawio_pair(age=0)
        self.assertEqual(self.read(), {"conflicts": []})

    def test_conflict_is_listed_with_the_format_in_use_and_no_paths(self):
        self.both()
        data = self.read()
        self.assertEqual(len(data["conflicts"]), 1)
        c = data["conflicts"][0]
        self.assertEqual((c["drawing_number"], c["formats"], c["in_use_format"], c["chosen"]), (S.DWG, ["dexpi", "drawio"], "drawio", None))
        self.assertEqual(sorted(x["format"] for x in c["candidates"]), ["dexpi", "drawio"])
        self.assertNotIn(self.tmp, json.dumps(data, ensure_ascii=False), "경로를 웹에 싣지 않는다")

    def test_choosing_a_format_is_saved_with_the_reviewer_and_changes_the_graph_in_use(self):
        self.both()
        before = project_ctx._graph_inputs(S.PROJECT)
        r = self.choose("dexpi")
        self.assertTrue(r["ok"], r)
        c = self.read()["conflicts"][0]
        self.assertEqual((c["in_use_format"], c["chosen"]), ("dexpi", "dexpi"))
        self.assertEqual(sources.load_choices(S.PROJECT)[S.DWG]["by"], "검토자A")
        self.assertNotEqual(project_ctx._graph_inputs(S.PROJECT), before, "고른 기록이 바뀌면 프로젝트 그래프를 다시 짓는다")
        self.assertIn("sources", self.events.topics())
        self.assertIn("drawings", self.events.topics())
        self.assertTrue(self.choose("drawio")["ok"], "다시 고르면 되돌아온다")
        self.assertEqual(self.read()["conflicts"][0]["in_use_format"], "drawio")

    def test_refusals_leave_the_choice_unwritten(self):
        self.both()
        r = self.choose("pdf_vector")
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"), "그 형식의 그래프가 없다")
        self.assertEqual(sources.load_choices(S.PROJECT), {})
        r = self.choose("dexpi", project="OTHER")
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "wrong_project"))
        r = self.engine.dispatch("sources.choose", {"drawing_number": S.DWG, "format": "dexpi"}, via_web=True)
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"), "웹이 보낸 명령은 프로젝트 ID가 있어야 한다")
        self.engine.settings["reviewer_name"] = ""
        r = self.choose("dexpi")
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"), "고른 사람 이름이 있어야 한다")
        self.assertEqual(sources.load_choices(S.PROJECT), {})

    def test_choosing_without_a_conflict_is_refused(self):
        self.drawio_pair(age=0)
        r = self.choose("drawio")
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"))


class RegistrationNoticeTest(unittest.TestCase):
    def test_registration_result_names_the_conflicting_drawing_numbers(self):
        engine = mock.Mock()
        engine.project_id.return_value = "P"
        engine.reviewer.return_value = "검토자A"
        engine.settings = {}
        fake = {"record": {"status": "registered", "material_id": "m1"}, "outcome": "registered", "registration_file": "x",
                "conflicts": [{"drawing_number": "SNP-M-101", "materials": []}]}
        with mock.patch.object(register_flow.registry, "register", return_value=fake), \
                mock.patch.object(register_flow.data, "extract_and_graph", return_value={"pages": [{"extract_dir": "/a/SNP-M-101", "extraction": {}}]}):
            out = register_flow.register_and_extract(engine, "/in/x.xml", lambda *a: None)
        self.assertEqual(out["conflicts"], ["SNP-M-101"])
        fake.pop("conflicts")
        with mock.patch.object(register_flow.registry, "register", return_value=fake), \
                mock.patch.object(register_flow.data, "extract_and_graph", return_value={"pages": [{"extract_dir": "/a/SNP-M-101", "extraction": {}}]}):
            out = register_flow.register_and_extract(engine, "/in/x.xml", lambda *a: None)
        self.assertEqual(out["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
