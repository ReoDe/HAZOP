"""그래프 판이 바뀌는 다른 길에서도 검토구간 판 이전을 이어서 하는지(081373a 검토 빠진 길 2·3). 실행: python -m unittest tests.test_shell_catch_up_paths

(1) 앱을 켤 때: 웹이 시작 끝에 project.open_check를 부르고, 끈 사이 낡은 프로젝트를 맞춘다. (2) 원본 형식 고르기(sources.choose)와 (3) 도면 연결 지정
(links.*)은 프로젝트 그래프 판을 바꾸므로 저장 뒤 알린다. (4) 실제 되부름 길: 프로젝트 그래프를 지으려다 낡은 도면을 다시 만들면(ensure_project → rebuild →
notify → catch_up_study → 프로젝트 그래프) 바꿔치기 없이 끝까지 돌고, 분석 시작 검사처럼 판 이전 잠금을 쥔 채 불러도 멈추지 않는다.
저장은 임시 작업 루트에만 한다. 실제 구독 호출 없음.
"""

import os
import re
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.app import data  # noqa: E402
from hazop.shell import sheet_refresh  # noqa: E402
from tests.test_shell_auto_catch_up import Base as AutoBase  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wait(cond, seconds=8):
    end = time.monotonic() + seconds
    while not cond() and time.monotonic() < end:
        time.sleep(0.05)
    return cond()


class AppStartTest(AutoBase):
    def test_the_open_check_brings_a_project_that_went_stale_while_the_app_was_off(self):
        self.re_extract()                        # 앱을 끈 사이 다시 읽혔다(알림 없음)
        self.assertTrue(self.stale())
        out = self.engine.dispatch("project.open_check", {}, via_web=True)
        self.assertTrue(out["ok"], out)
        self.assertTrue(wait(lambda: not self.stale()), "앱을 켜면 누르지 않아도 맞춘다")

    def test_the_web_calls_it_when_it_starts(self):
        with open(os.path.join(REPO, "hazop", "shell", "web", "js", "main.js"), encoding="utf-8") as fh:
            src = fh.read()
        body = src[src.index("async function boot()"):]
        body = body[:body.index("\n}\n")]
        self.assertTrue(re.search(r'cmd\("project\.open_check"\)', body), "boot()이 project.open_check를 부른다")


class SourcesChooseTest(unittest.TestCase):
    def test_choosing_a_source_format_notifies_after_it_is_saved(self):
        from tests.test_shell_sources import SourcesApiTest
        from tests import test_drawing_sources as S
        t = SourcesApiTest("test_choosing_a_format_is_saved_with_the_reviewer_and_changes_the_graph_in_use")
        t.setUp()
        try:
            from hazop.graph import sources
            t.both()
            seen = []
            with mock.patch.object(data, "notify_graph_changed", lambda pid: seen.append((pid, dict(sources.load_choices(pid))))):
                r = t.choose("dexpi")
            self.assertTrue(r["ok"], r)
            self.assertEqual([p for p, _ in seen], [t.engine.project_id()])
            self.assertEqual(seen[0][1][S.DWG]["format"], "dexpi", "고른 것을 저장한 뒤에 알린다(판 이전이 새 그래프로 짓게)")
            with mock.patch.object(data, "notify_graph_changed") as spy:
                bad = t.choose("pdf_vector")
            self.assertFalse(bad["ok"])
            spy.assert_not_called()
        finally:
            t.doCleanups()


class LinksTest(unittest.TestCase):
    def test_a_link_assignment_migrates_the_node_set_to_the_new_project_graph(self):
        from hazop.app import project_ctx
        from hazop.study import nodes as sn
        from tests.test_shell_links import PairUnlinkClearTest
        t = PairUnlinkClearTest("test_unlink_asks_then_both_ends_are_unlinked_and_the_record_says_who_and_why")
        t.setUp()
        try:
            pg = project_ctx.project_graph(t.engine.project_id())
            sn.save(sn.propose(pg, at="2026-11-23T00:00:00Z"))
            a, _b = t.linked_pair()
            with mock.patch.object(data, "notify_graph_changed", wraps=data.notify_graph_changed) as spy:
                t.confirmed("unlink", a, reason="도면 개정으로 끊김")
            spy.assert_called_with(t.engine.project_id())
            now = project_ctx.project_graph(t.engine.project_id())
            self.assertNotEqual(now["graph_version"], pg["graph_version"], "도면 연결은 프로젝트 그래프 판에 든다(시험의 전제)")
            ns = sn.read_as_is(now)
            self.assertTrue(wait(lambda: not sn.is_stale(sn.read_as_is(now), now)), "누르지 않아도 새 판으로 옮겨진다")
            self.assertIsNotNone(ns)
        finally:
            t.doCleanups()


class SaveCorrectionsOrderTest(unittest.TestCase):
    def test_the_old_screen_save_notifies_after_the_knowledge_graph_is_rebuilt(self):
        order = []

        class Builder:
            def build_one(self, path, root):
                order.append("build")
                return {"project_id": "P-X", "graph_id": "graph-X", "graph_version": "v"}, root
        with mock.patch.object(data, "read_json", lambda p: {"drawing": {}}),                 mock.patch.object(data.corrections, "save_fp", lambda *a, **k: ("p", "fp")),                 mock.patch.object(data, "script_module", lambda name: Builder()),                 mock.patch.object(data, "extraction_path", lambda name: name),                 mock.patch.object(data, "_with_kg", lambda out, pid: order.append("kg")),                 mock.patch.object(data, "notify_graph_changed", lambda pid: order.append("notify")),                 mock.patch.object(data.study_nodes, "read_as_is", lambda g: None),                 mock.patch.object(data.os.path, "isfile", lambda p: False):
            data.save_corrections("x", [], "검토자A")
        self.assertEqual(order, ["build", "kg", "notify"])


class RecursionTest(unittest.TestCase):
    """실제 길: 등록된 도면을 고친 뒤 다시 만들지 못한 채(낡은 표시) 프로젝트 그래프를 지으면 그 안에서 다시 만들고, 다시 만들기 끝의 알림이 판 이전을 하고,
    판 이전이 다시 프로젝트 그래프를 짓는다(ensure_project는 되풀이하지 않는다). 어느 것도 바꿔치기하지 않는다."""

    def setUp(self):
        from tests.test_shell_corrections import RegisteredPathTest
        self.t = RegisteredPathTest("test_a_web_edit_rebuilds_the_sheet_once")
        self.t.setUp()
        self.addCleanup(self.t.doCleanups)
        ex = data.read_json(data.extraction_path(self.t.name))
        rel = next(r for r in ex["relations"] if r["kind"] == "physical_connection" and all(ep.get("node_local_id") for ep in r["endpoints"]))
        self.t.call_nodes("create", {"sheet": self.t.gid, "ids": [rel["local_id"]], "name": "구간"})

    def stale_edit(self):
        """도면 추출을 고치고 다시 만들지 않은 채 낡은 표시만 남긴다(다시 만들기가 실패했거나 앱이 그 사이 꺼진 경우)."""
        from hazop import store_io
        path = data.extraction_path(self.t.name)
        ex = data.read_json(path)
        n = next(x for x in ex["nodes"] if x.get("tag"))
        n["tag"] = "RECUR-1"
        store_io.write_json(path, ex)
        sheet_refresh.mark_stale(self.t.name, "시험")

    def build(self, hold_study_lock=False):
        from hazop.app import project_ctx
        out = {}

        def run():
            try:
                if hold_study_lock:
                    with self.t.engine._study_lock:          # 분석 시작 검사(api_results._run)가 이 잠금을 쥔 채 프로젝트 그래프를 짓는다
                        out["pg"] = project_ctx.project_graph("REG-P")
                else:
                    out["pg"] = project_ctx.project_graph("REG-P")
            except Exception as exc:  # noqa: BLE001
                out["error"] = exc
        th = threading.Thread(target=run, daemon=True)
        th.start()
        th.join(60)
        self.assertFalse(th.is_alive(), "프로젝트 그래프 짓기가 되부름에서 멈췄다")
        self.assertNotIn("error", out, out.get("error"))
        return out["pg"]

    def current(self):
        from hazop.app import project_ctx
        from hazop.study import nodes as sn
        pg = project_ctx.project_graph("REG-P")
        return not sn.is_stale(sn.read_as_is(pg), pg)

    def test_building_the_project_graph_rebuilds_the_stale_sheet_and_migrates_without_any_stub(self):
        self.stale_edit()
        with mock.patch.object(data, "catch_up_study", wraps=data.catch_up_study) as cu:
            self.build()
        self.assertTrue(cu.called, "다시 만들기 끝의 알림이 판 이전을 불렀다")
        self.assertFalse(sheet_refresh.graph_stale(self.t.name))
        self.assertTrue(wait(self.current), "검토구간이 새 판으로 옮겨졌다")

    def test_it_does_not_hang_when_the_caller_holds_the_study_lock(self):
        self.stale_edit()
        self.build(hold_study_lock=True)
        self.assertTrue(wait(self.current))


if __name__ == "__main__":
    unittest.main()
