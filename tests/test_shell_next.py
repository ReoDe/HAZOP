"""'다음에 할 일' 읽기(next, hazop/shell/api_next.py, 규격 HZ-DSN-06 §3.1·G1 엔진 쪽). 실행: python -m unittest tests.test_shell_next

(1) 규칙 표의 차례가 규격 §3.1 표와 같다. (2) 실제 프로젝트 꼴에서 엔진 값대로 나온다: 도면 없음, 등록 직후(표제란), 다시 확인, 반영 실패, 작업 중.
(3) 영역이 바뀌었다고 알리면 next도 알린다. (4) 읽기는 파일을 쓰지 않는다. 저장은 임시 작업 루트에만 한다. 실제 구독 호출 없음.
"""

import os
import re
import shutil
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.app import data  # noqa: E402
from hazop.shell import api, api_next  # noqa: E402
from tests.test_screen_words import BANNED  # noqa: E402
from tests.test_shell_auto_catch_up import Base as AutoBase  # noqa: E402
from tests.test_shell_catch_up import PID  # noqa: E402

SPEC_ORDER = ["apply_failed", "no_sheets", "recheck", "inputs_pending", "sheet_released", "sheet_choose", "sheet_skipped", "titleblock", "number_held", "ai_unreviewed", "ai_candidates", "sheet_confirm", "nodes_none", "nodes_draft",
              "nodes_unrun", "results_unjudged", "ie_none", "ie_draft"]
GO = re.compile(r"^(panel:[a-z]+(#[a-z_]+)?|queue:(ai|lost)|confirm:[a-z_]+\.[a-z_]+)$")


class RulesTest(unittest.TestCase):
    def test_the_order_matches_the_spec_table(self):
        self.assertEqual([r[0] for r in api_next.RULES], SPEC_ORDER)

    def test_everything_at_once_comes_in_that_order(self):
        f = {"apply_failed": True, "sheets": 0, "running": [], "lost_members": 2, "lost_refs": 1, "lost_nodes": ["S1"], "titleblock": 1, "inputs_pending": 1, "sheet_released": 1, "sheet_choose": 1, "sheet_skipped": 1, "number_held": 1,
             "ai_unreviewed": 2, "ai_candidates": 3, "sheet_confirm": 2, "sheets_confirmed": 1, "nodes_total": 0, "nodes_draft": 2, "nodes_unrun": 1,
             "results_unjudged": 4, "ie_none": 1, "ie_draft": 1}
        kinds = [i["kind"] for i in api_next.items(f)]
        self.assertEqual(kinds, [k for k in SPEC_ORDER if k not in ("sheet_confirm", "number_held")], "표제란이 남으면 쪽 확정·번호 보류는 아직 띄우지 않는다")
        rc = next(i for i in api_next.items(f) if i["kind"] == "recheck")
        # 알림 줄과 같은 단위(찾지 못한 구성요소 수, 실제 창 3차 결함 6)
        self.assertEqual((rc["count"], rc["text"], rc["tone"]), (2, "도면이 바뀌어 찾지 못한 구성요소 2개를 다시 확인해야 합니다", "warn"))
        only_refs = next(i for i in api_next.items({"sheets": 1, "running": [], "lost_refs": 4}) if i["kind"] == "recheck")
        self.assertEqual(only_refs["text"], "도면이 바뀌어 분석 결과 4곳을 다시 확인해야 합니다")
        self.assertIn("S1", rc["detail"])

    def test_before_sheet_confirmation_the_line_offers_confirm_first_and_ai_review_beside_it(self):
        """실제 창 5차 헤맴: 쪽 확정 전 맨 위가 'AI 검토 시작'뿐이라 AI를 안 쓰는 사람이 눌렀다 취소했다. 쪽 확정이 주 단추, AI 검토 시작이 곁 단추."""
        f = {"sheets": 2, "running": [], "ai_unreviewed": 2, "ai_unreviewed_first": "G1", "sheet_confirm": 2, "sheet_confirm_first": "G1", "nodes_unrun": 1}
        out = api_next.items(f)
        self.assertEqual([i["kind"] for i in out], ["sheet_confirm", "nodes_unrun"], "AI 검토 줄은 곁 단추로 들어간다")
        self.assertEqual((out[0]["action"]["label"], out[0]["alt"]["label"], out[0]["alt"]["go"]), ("쪽 확정", "AI 검토 시작", "confirm:aireview.run"))
        self.assertIn("AI 검토를 먼저", out[0]["text"])
        only_ai = api_next.items({"sheets": 2, "running": [], "ai_unreviewed": 1, "ai_unreviewed_first": "G1", "titleblock": 1})
        self.assertNotIn("alt", only_ai[1] if len(only_ai) > 1 else only_ai[0], "쪽 확정이 없으면(표제란 먼저) 짝짓지 않는다")

    def test_nothing_to_do(self):
        out = api_next.items({"sheets": 2, "running": []})
        self.assertEqual([i["kind"] for i in out], ["none"])
        self.assertEqual(out[0]["text"], "지금 할 일이 없습니다")

    def test_no_sheets_waits_while_a_drawing_is_being_read(self):
        self.assertNotIn("no_sheets", [i["kind"] for i in api_next.items({"sheets": 0, "running": [{"kind": "register"}]})])

    def test_texts_are_screen_words_and_targets_are_well_formed(self):
        f = {k: 1 for k in ("inputs_pending", "sheet_released", "sheet_choose", "sheet_skipped", "number_held", "titleblock", "ai_unreviewed", "ai_candidates", "nodes_draft", "nodes_unrun", "results_unjudged", "ie_none", "ie_draft", "lost_members")}
        f.update(apply_failed=True, sheets=0, running=[], sheets_confirmed=1, nodes_total=0)
        for i in api_next.items(f) + [api_next.NONE_ITEM]:
            for w in BANNED:
                self.assertNotIn(w, i["text"])
            self.assertRegex(i["action"]["go"], GO)



class _FakeEngine:
    def project_id(self):
        return "P"

    def job_progress(self):
        return []

    def graph_names(self):
        return {"G1": "a", "G2": "b", "G3": "c"}

    def catching(self, _pid):
        return False


class FactsTest(unittest.TestCase):
    """실제 창 3차(838c7f2): 3~7단계 내내 맨 위가 'AI 검토 시작'이었고, 판정이 끝난 뒤 '초기사건 초안 만들기'가 어디에도 없었다.
    총괄 결정: ai_unreviewed는 AI에게 물을 곳이 있고 아직 쪽을 확정하지 않은 도면만 센다. 초안이 없고 승인된 결과(후보)가 있으면 '초안 만들기'."""

    def facts(self, review, sheet_state, ie=None):
        from hazop.shell import api_aireview, api_drawings, api_ie
        rows = [{"graph_id": g, "drawing_number": g, "proposed": 0, "review": r} for g, r in review.items()]
        sc = {"drawings": [{"graph_id": g, "state": st} for g, st in sheet_state.items()]}
        with mock.patch.object(api_aireview, "overview", lambda e: {"drawings": rows}), \
                mock.patch.object(api_drawings, "exportable", lambda e: sc), \
                mock.patch.object(api_drawings, "labels", lambda e: {}), \
                mock.patch.object(api_next, "_conflicts", lambda e: []), \
                mock.patch.object(api_ie, "summary", lambda e: ie or {"available": False}):
            return api_next.facts(_FakeEngine())

    def test_a_confirmed_sheet_or_one_with_nothing_to_ask_is_not_an_unreviewed_drawing(self):
        f = self.facts({"G1": "not_run", "G2": "not_run", "G3": "nothing"}, {"G1": "confirmed", "G2": "ready", "G3": "open"})
        self.assertEqual((f["ai_unreviewed"], f["ai_unreviewed_first"]), (1, "G2"), "쪽을 확정한 G1·물을 곳이 없는 G3는 빠진다")
        f = self.facts({"G1": "not_run", "G2": "partial"}, {"G1": "confirmed", "G2": "confirmed"})
        self.assertEqual(f["ai_unreviewed"], 0)
        self.assertNotIn("ai_unreviewed", [i["kind"] for i in api_next.items(dict(f, sheets=2, running=[]))], "목록에도 남지 않는다")

    def test_a_chosen_source_is_no_longer_a_file_to_choose(self):
        """실제 창 3차 결함 5: 같은 번호 카드에서 고른 뒤에도 '쓸 파일을 고르세요'가 남았다."""
        from hazop.shell import api_aireview, api_drawings, api_ie
        cf = [{"graph_id": "G1", "reason": "same_number_other_file", "chosen": None, "chosen_material": "m2"},
              {"graph_id": "G2", "reason": "same_number_other_format", "chosen": "drawio", "chosen_material": None},
              {"graph_id": "G3", "reason": "same_number_other_format", "chosen": None, "chosen_material": None}]
        with mock.patch.object(api_aireview, "overview", lambda e: {"drawings": []}), \
                mock.patch.object(api_drawings, "exportable", lambda e: {"drawings": []}), \
                mock.patch.object(api_drawings, "labels", lambda e: {}), \
                mock.patch.object(api_next, "_conflicts", lambda e: cf), \
                mock.patch.object(api_ie, "summary", lambda e: {"available": False}):
            f = api_next.facts(_FakeEngine())
        self.assertEqual((f["sheet_choose"], f["sheet_choose_first"]), (1, "G3"))

    def test_a_confirmation_released_by_a_rebuilt_base_asks_to_check_again(self):
        """입력 연산 U2 §11.3 7: 쪽 확정이 기준 추출이 바뀌어(나누기를 다시 읽어) 풀렸으면 '다시 확인' 줄."""
        from hazop.extract import corrections
        from hazop.shell import api_aireview, api_drawings, api_ie
        st = {"G1": {"released": [{"what": "confirmed", "changed": ["base"]}]}, "G2": {"released": [{"what": "confirmed", "changed": ["edits"]}]}}
        with mock.patch.object(api_aireview, "overview", lambda e: {"drawings": []}),                 mock.patch.object(api_drawings, "exportable", lambda e: {"drawings": [{"graph_id": g, "state": "open"} for g in ("G1", "G2", "G3")]}),                 mock.patch.object(api_drawings, "labels", lambda e: {}),                 mock.patch.object(api_drawings, "status", lambda e, g: st.get(g, {"released": []})),                 mock.patch.object(corrections, "load", lambda n: {"ops": [{"op": "split"}]} if n in ("a", "b") else None),                 mock.patch.object(corrections, "is_input", lambda o: o.get("op") == "split"),                 mock.patch.object(api_next, "_conflicts", lambda e: []),                 mock.patch.object(api_ie, "summary", lambda e: {"available": False}):
            f = api_next.facts(_FakeEngine())
        self.assertEqual((f["sheet_released"], f["sheet_released_first"]), (1, "G1"))
        it = next(i for i in api_next.items(dict(f, sheets=3, running=[])) if i["kind"] == "sheet_released")
        self.assertIn("다시", it["text"])
        self.assertEqual((it["action"]["go"], it["action"]["target"]), ("panel:drawings#sheetconf", "G1"))

    def test_a_draft_to_make_shows_up_after_judging(self):
        ie = {"available": True, "kpi": {"candidates": 3, "groups": 0, "draft": 0}}
        f = self.facts({}, {}, ie)
        out = api_next.items(dict(f, sheets=3, running=[]))
        self.assertEqual(out[0]["kind"], "ie_none", out)
        self.assertEqual((out[0]["action"]["label"], out[0]["action"]["go"]), ("초안 만들기", "confirm:ie.suggest"))
        f = self.facts({}, {}, {"available": True, "kpi": {"candidates": 3, "groups": 2, "draft": 2}})
        self.assertEqual([i["kind"] for i in api_next.items(dict(f, sheets=3, running=[]))], ["ie_draft"], "초안이 있으면 '초안 보기'만")
        f = self.facts({}, {}, {"available": True, "kpi": {"candidates": 0, "groups": 0, "draft": 0}})
        self.assertEqual([i["kind"] for i in api_next.items(dict(f, sheets=3, running=[]))], ["none"], "승인된 결과가 없으면 초안 만들기를 띄우지 않는다")

class EmptyProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-next-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        p.start()
        self.addCleanup(p.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        self.events = []
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events.append)
        self.engine.settings.update(project_id="P-EMPTY", reviewer_name="검토자A")

    def read(self):
        import json
        r = api.ReadApi(self.engine).read(["next"], {})
        return json.loads(r.body.decode("utf-8"))

    def test_no_drawings_says_so_first(self):
        out = self.read()
        self.assertEqual(out["items"][0]["kind"], "no_sheets")
        self.assertIsNone(out["running"])

    def test_a_running_job_shows_its_progress(self):
        started, release = threading.Event(), threading.Event()

        def work(progress):
            progress("SNP-M-102를 읽고 있습니다", 2, 3)
            started.set()
            release.wait(5)
        self.engine.start_job("등록", work)
        self.assertTrue(started.wait(5))
        out = self.read()
        release.set()
        self.engine.wait_jobs(5)
        self.assertEqual((out["running"]["label"], out["running"]["done"], out["running"]["total"]), ("SNP-M-102를 읽고 있습니다", 2, 3))
        self.assertNotIn("no_sheets", [i["kind"] for i in out["items"]], "읽는 중에는 '도면이 없습니다'를 띄우지 않는다")

    def test_an_area_change_also_announces_next(self):
        self.engine.changed("nodes")
        topics = [e.get("topic") for e in self.events if e.get("t") == "changed"]
        self.assertEqual(topics, ["nodes", "next"])
        self.events.clear()
        self.engine.changed("chat")
        self.assertEqual([e.get("topic") for e in self.events if e.get("t") == "changed"], ["chat"])


class StudyProjectTest(AutoBase):
    def setUp(self):
        super().setUp()
        # 이 틀은 프로젝트 그래프만 바꿔 넣어 도면 그래프 폴더가 없다: 도면 한 장이 등록된 것으로 본다
        p = mock.patch.object(self.engine, "graph_names", lambda: {self.g["graph_id"]: "T-1"})
        p.start()
        self.addCleanup(p.stop)

    def kinds(self):
        return [i["kind"] for i in api_next.summary(self.engine)["items"]]

    def test_lost_members_after_a_re_extract_come_first(self):
        self.re_extract_losing_v2()
        data.notify_graph_changed(PID)
        out = api_next.summary(self.engine)["items"][0]
        self.assertEqual(out["kind"], "recheck")
        self.assertGreaterEqual(out["count"], 1)
        self.assertEqual(out["action"]["go"], "queue:lost")
        self.assertTrue(out["action"]["target"], "첫 구간으로 간다")

    def test_a_failed_automatic_migration_comes_before_everything(self):
        with mock.patch.object(data, "migrate_study", side_effect=OSError("디스크 가득")):
            self.re_extract()
            data.notify_graph_changed(PID)
        self.assertEqual(self.kinds()[0], "apply_failed")

    def test_waiting_for_an_ai_job_is_not_called_a_failure(self):
        self.re_extract()
        with self.engine._lock:
            self.engine._catching.add(PID)
        self.assertNotIn("apply_failed", self.kinds())

    def test_reading_writes_no_file(self):
        def snap():
            out = {}
            for d, _s, files in os.walk(self.tmp):
                for n in files:
                    p = os.path.join(d, n)
                    out[p] = os.stat(p).st_mtime_ns
            return out
        before = snap()
        api_next.summary(self.engine)
        self.assertEqual(snap(), before)


class RegisteredDrawingTest(unittest.TestCase):
    def test_right_after_registering_the_first_thing_is_the_title_block(self):
        from tests.test_shell_corrections import RegisteredPathTest
        t = RegisteredPathTest("test_a_web_edit_rebuilds_the_sheet_once")
        t.setUp()
        try:
            out = api_next.summary(t.engine)["items"]
            self.assertEqual(out[0]["kind"], "titleblock", out)
            self.assertEqual(out[0]["action"]["go"], "panel:drawings#titleblock")
            self.assertTrue(out[0]["action"]["target"], "한 장이면 그 자료의 표제란 카드로 바로 간다")
            self.assertNotIn("sheet_confirm", [i["kind"] for i in out], "표제란 전에는 쪽 확정을 띄우지 않는다")
        finally:
            t.doCleanups()


if __name__ == "__main__":
    unittest.main()
