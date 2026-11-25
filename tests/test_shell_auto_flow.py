"""자동 확정의 흐름(C2, hazop/shell/auto_flow.py): 올리면 읽고 AI가 이어서 메우고 확정(미확인 n)까지.

설계: docs/units/2026-11-13-drawing-knowledge/evidence/auto-confirm-design.md 3·8·9·10.2·13장.
임시 작업 루트·임시 설정 파일과 고정 응답만 쓴다(구독 호출 없음). 자동 수락·자동 번호는 상수로 꺼진 채다.
실행: python -m unittest tests.test_shell_auto_flow
"""

import glob
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from hazop import paths
from hazop.extract import ai_images, ai_review as ar, confirmation as cf, corrections as co
from hazop.shell import api, api_aireview as AR, api_corrections as AC, auto_flow, clean_items, register_flow
from tests.test_ai_review import StubClient, node
from tests.test_shell_drawings import Events

PROJECT = "AUTO-P"
NONE = {"answers": []}


class FakeAi:
    def __init__(self, client, ready=True):
        self.client, self.ready = client, ready

    def status(self):
        return {"can_start": self.ready, "state": "ready" if self.ready else "not_ready"}

    def make_client(self):
        return self.client


class Page:
    def crop_box(self, bbox, pad=0):
        return bbox

    def crop_png(self, bbox, pad=0):
        return b"png"


def kinds(value, conf=0.95):
    """모든 항목의 종류를 value라 답한다."""
    return lambda request: {"answers": [{"item_id": it["item_id"], "field": "kind", "values": [value], "confidence": conf, "reason": "시험", "match": "legend"}
                                        for it in json.loads(request["context"])["items"]]}


def fake_images(*_a, **kw):
    """그림을 그리지 않는 그림 입력(호출 수·흐름만 본다). 프로젝트 도면을 주면 앱처럼 프로젝트 판이 된다."""
    source = "project" if kw.get("drawings") else "symbols"
    return ai_images.ImageInput(Page(), [b"legend"], legend_source=source)


def big(i, unread=250, fmt="pdf_vector", project=PROJECT):
    nodes = [node("pdf-p0-sym-%04d" % k, None, (20 + k * 12, 100, 30 + k * 12, 108)) for k in range(unread)]
    nodes.append(node("pdf-p0-sym-9999", "pump", (10, 10, 20, 20), tag="PP01"))
    for n in nodes:
        n["classification"] = "classified" if n["kind"] else "unclassified"
    unknowns = [{"check": "missing_kind", "target": n["local_id"], "source_object_id": n["source_object_id"], "field": "kind", "reason": "종류 미확인"}
                for n in nodes if not n["kind"]]
    return {"project_id": project, "drawing": {"drawing_number": None, "ignored_objects": []}, "source_locations": [], "nodes": nodes, "relations": [], "unresolved_connectors": [], "unclassified": [], "texts": [],
            "source": {"format": fmt, "file": os.path.abspath(__file__), "sha256": "s%d" % i, "material_id": "material-%012d" % i},
            "run": {"script_version": "x", "rules_version": "y", "settings": {"page_index": 0}}, "validation": {"status": "passed", "blockers": [], "unknowns": unknowns}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-autoflow-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")}),
                  mock.patch.object(ai_images, "image_input_for", side_effect=fake_images),
                  mock.patch.dict(ar.RETRY_DELAYS, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        self.client = StubClient(lambda request: NONE)
        self.jobs = None            # None이면 작업을 그 자리에서 돌린다. 목록이면 모아 둔다
        self.known = {}
        self.engine = self.make_engine()

    def make_engine(self, ready=True):
        def run_jobs(_id, fn):
            if self.jobs is None:
                fn()
            else:
                self.jobs.append(fn)
        e = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=Events(), run_jobs=run_jobs, ai=FakeAi(self.client, ready))
        e.settings.update(reviewer_name="검토자", project_id=PROJECT)
        e.graph_names = lambda: dict(self.known)
        e.spawn = lambda target, name: target()
        return e

    def consent(self, allow=True):
        out = self.engine.dispatch("aireview.consent", {"allow": allow})
        self.assertTrue(out["ok"], out)
        return out["data"]

    version = 1

    def name(self, i):
        return "%s__material-%012d-r%d-p0" % (PROJECT, i, self.version)

    def upload(self, *pages, outcome="registered", engine=None, number=None):
        """파일 올리기(engine.add_files). 등록과 추출은 대역이고 추출 결과 파일을 실제로 쓴다. pages: (번호, 추출 결과)."""
        engine = engine or self.engine
        files = {}
        for i, ex in pages:
            path = os.path.join(self.tmp, "f%d.pdf" % i)
            with open(path, "wb") as fh:
                fh.write(b"%PDF")
            files[path] = (i, ex)

        def register(path, *_a, **_k):
            i, _ex = files[path]
            return {"record": {"status": "registered", "material_id": "material-%012d" % i, "project_id": PROJECT}, "outcome": outcome,
                    "registration_file": path}

        def extract(path, progress=None):
            i, ex = files[path]
            return self.put(i, ex)
        got = {"confirmed": False, "why": number or "off"}
        with mock.patch.object(register_flow.registry, "register", side_effect=register), \
                mock.patch.object(register_flow.data, "extract_and_graph", side_effect=extract), \
                mock.patch.object(register_flow.titleblock, "auto_confirm_number",
                                  side_effect=lambda pid, mid, *_a: dict(got, registration_file=next(p for p, (i, _e) in files.items() if mid.endswith("%012d" % i)))):
            out = engine.add_files(list(files))
            while self.jobs:
                self.jobs.pop(0)()
            return out

    def put(self, i, ex):
        name = self.name(i)
        d = os.path.join(paths.output_root("extract"), name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "extraction.json"), "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)
        self.known["graph-%d" % i] = name
        return {"extraction": ex, "extract_dir": d}

    def cell(self, i):
        return cf.sheet_confirmation(self.name(i))["auto"]

    def level(self, i):
        return cf.sheet_confirmation(self.name(i))["level"]

    def state(self, i):
        c = self.cell(i) or {}
        return c.get("result"), c.get("why")

    def calls(self):
        return len(self.client.requests)

    def failed_jobs(self):
        return [e for e in self.engine._emit.items if e.get("name") == "job.failed"]


class ConsentTest(Base):
    def test_default_is_no_consent_and_nothing_is_sent(self):
        self.engine.settings["extract_ai_review"] = True          # 옛 토글은 동의가 아니다
        self.upload((1, big(1)))
        self.assertEqual(self.calls(), 0)
        self.assertEqual(self.state(1), ("waiting", "no_consent"))
        self.assertEqual(self.level(1), "extracted")
        self.assertEqual(self.failed_jobs(), [], "등록·추출은 완료로 둔다")

    def test_consent_is_written_to_the_user_settings_and_read_back(self):
        got = self.consent()
        self.assertEqual((got["allow"], got["asked"]), (True, True))
        again = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=Events(), run_jobs=lambda *_a: None)
        self.assertTrue(auto_flow.consent(again)["allow"])
        saved = paths.load_settings(os.path.join(self.tmp, "settings.json"))[auto_flow.CONSENT_KEY]
        self.assertEqual((saved["allow"], saved["notice"], saved["by"]), (True, auto_flow.CONSENT_NOTICE, "검토자"))
        self.assertTrue(saved["at"])

    def test_declined_is_remembered_and_sends_nothing(self):
        got = self.consent(False)
        self.assertEqual((got["allow"], got["asked"]), (False, True))
        self.upload((1, big(1)))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "no_consent")))

    def test_anything_but_a_full_record_is_no_consent(self):
        full = {"allow": True, "notice": auto_flow.CONSENT_NOTICE, "at": "2026-11-25T00:00:00Z", "by": None}
        for bad in (True, "yes", {}, dict(full, allow=1), dict(full, allow="true"), dict(full, notice="other"), dict(full, at=None), [full]):
            self.engine.settings[auto_flow.CONSENT_KEY] = bad
            self.assertFalse(auto_flow.consent(self.engine)["allow"], bad)
        self.engine.settings[auto_flow.CONSENT_KEY] = full
        self.assertTrue(auto_flow.consent(self.engine)["allow"])

    def test_a_failed_save_is_not_consent(self):
        with mock.patch.object(paths, "save_settings", side_effect=OSError("disk")):
            self.assertFalse(self.engine.dispatch("aireview.consent", {"allow": True})["ok"])
        self.assertFalse(auto_flow.consent(self.engine)["allow"])

    def test_a_withdrawal_that_cannot_be_saved_still_stops_sending(self):
        self.consent()
        with mock.patch.object(paths, "save_settings", side_effect=OSError("disk")):
            self.assertFalse(self.engine.dispatch("aireview.consent", {"allow": False})["ok"])
        self.upload((1, big(1, unread=5)))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "no_consent")))

    def test_consent_turns_the_picture_switch_on_and_a_later_off_wins(self):
        self.engine.settings["ai_review_images"] = False
        self.consent()
        self.assertIs(self.engine.settings["ai_review_images"], True)
        self.engine.dispatch("extract.set_ai_review", {"images": False})
        self.upload((1, big(1, unread=5)))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "images_off")))
        self.engine.dispatch("extract.set_ai_review", {"images": True})
        self.assertEqual((self.calls(), self.level(1)), (1, "auto"))

    def test_declining_leaves_the_picture_switch(self):
        self.engine.settings["ai_review_images"] = False
        self.consent(False)
        self.assertIs(self.engine.settings["ai_review_images"], False)

    def test_reserved_name_is_never_a_reviewer(self):
        self.assertFalse(self.engine.dispatch("settings.set_reviewer", {"name": "HAZOP:auto"})["ok"])
        self.assertEqual(self.engine.reviewer(), "검토자")
        path = os.path.join(self.tmp, "settings.json")
        paths.save_settings({"reviewer_name": "hazop:auto"}, path)
        e = api.Engine(settings_path=path, emit=Events(), run_jobs=lambda *_a: None)
        self.assertIsNone(e.reviewer())
        self.assertIsNone(e.settings["reviewer_name"], "열 때 비운다")
        e.settings["reviewer_name"] = " hazop:auto "
        self.assertIsNone(e.reviewer())

    def test_other_settings_commands_do_not_set_consent(self):
        self.engine.dispatch("extract.set_ai_review", {"enabled": True, "images": True})
        self.engine.dispatch("settings.set_reviewer", {"name": "다른 사람"})
        self.assertNotIn(auto_flow.CONSENT_KEY, self.engine.settings)

    def test_consent_starts_the_waiting_sheets(self):
        self.upload((1, big(1, unread=5)))
        self.assertEqual(self.state(1), ("waiting", "no_consent"))
        self.consent()
        self.assertEqual((self.calls(), self.level(1)), (1, "auto"))

    def test_withdrawing_stops_before_the_next_call(self):
        self.consent()
        self.client.answer = lambda request: self.consent(False) and NONE
        self.upload((1, big(1)), (2, big(2)))
        self.assertEqual(self.calls(), 1)
        self.assertEqual(self.state(2), ("waiting", "no_consent"))
        self.assertEqual(self.level(1), "extracted")

    def test_read_tells_the_screen_when_to_ask(self):
        self.upload((1, big(1)))
        got = json.loads(AR.read(self.engine, ["aireview", "auto"], {}).body.decode("utf-8"))
        self.assertTrue(got["ask"])
        self.assertEqual(got["gate"], "no_consent")
        self.assertEqual([(s["graph_id"], s["result"], s["why"]) for s in got["sheets"]], [("graph-1", "waiting", "no_consent")])
        self.consent(False)
        self.assertFalse(json.loads(AR.read(self.engine, ["aireview", "auto"], {}).body.decode("utf-8"))["ask"])


class GateTest(Base):
    def setUp(self):
        super().setUp()
        self.consent()

    def test_no_connection(self):
        self.engine.ai.ready = False
        self.upload((1, big(1)))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "no_connection")))

    def test_no_ai_at_all(self):
        self.engine.ai = None
        self.upload((1, big(1)))
        self.assertEqual(self.state(1), ("waiting", "no_connection"))

    def test_api_key_path_is_never_used(self):
        self.client.describe = lambda: {"via": "api"}
        self.upload((1, big(1)))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "no_connection")))

    def test_denied_project(self):
        out = self.engine.dispatch("aireview.send_policy", {"send": "deny", "reason": "보안 자료"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(ar.send_policy(PROJECT), "deny")
        self.upload((1, big(1)))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "ai_off")))
        self.assertTrue(self.engine.dispatch("aireview.send_policy", {"send": "allow"})["ok"])
        self.assertEqual(self.level(1), "auto", "보내기를 다시 허용하면 이어 한다")

    def test_policy_needs_a_person(self):
        self.engine.settings["reviewer_name"] = ""
        self.assertFalse(self.engine.dispatch("aireview.send_policy", {"send": "deny"})["ok"])
        self.assertIsNone(ar.send_policy(PROJECT))

    def test_drawio_dexpi_and_scan_never_call(self):
        self.upload((1, big(1, fmt="drawio")), (2, big(2, fmt="dexpi")), (3, big(3, fmt="raster")))
        self.assertEqual(self.calls(), 0)
        self.assertEqual([self.state(i) for i in (1, 2, 3)], [("confirmed", None), ("confirmed", None), ("waiting", "scan")])
        self.assertEqual([self.level(i) for i in (1, 2, 3)], ["auto", "auto", "extracted"])

    def test_drawio_needs_neither_consent_nor_connection(self):
        self.consent(False)
        self.engine.ai = None
        self.upload((1, big(1, fmt="drawio")))
        self.assertEqual(self.level(1), "auto")

    def test_original_pdf_missing(self):
        ex = big(1)
        ex["source"]["file"] = os.path.join(self.tmp, "gone.pdf")
        self.upload((1, ex))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "no_image")))

    def test_picture_failure_never_falls_back_to_text(self):
        with mock.patch.object(ai_images, "image_input_for", side_effect=RuntimeError("x")):
            self.upload((1, big(1)))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "no_image")))

    def test_every_call_carries_pictures_and_the_standard_legend(self):
        self.upload((1, big(1, unread=5)), (2, big(2, unread=5)))
        self.assertTrue(all(q.get("images") for q in self.client.requests))
        self.assertEqual({r["legend_source"] for i in (1, 2) for r in ar.load_doc(self.name(i))["runs"]}, {"symbols"})

    def test_pdf_gone_while_waiting_is_never_sent_as_text(self):
        ex = big(1, unread=5)
        src = os.path.join(self.tmp, "orig.pdf")
        open(src, "wb").close()
        ex["source"]["file"] = src
        real = ar.estimate_pages

        def est(*a, **k):
            if os.path.exists(src):
                os.remove(src)
            return real(*a, **k)
        with mock.patch.object(ar, "estimate_pages", side_effect=est):
            self.upload((1, ex))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "no_image")))

    def test_sheet_without_project_follows_the_current_projects_policy(self):
        self.put(1, big(1, unread=5, project=None))
        self.assertTrue(self.engine.dispatch("aireview.send_policy", {"send": "deny"})["ok"])
        AR.run_review(self.engine, ["graph-1"], 20, lambda *a, **k: None)
        self.assertEqual(self.calls(), 0, "수동도 지금 프로젝트의 정책")
        cf.record_auto(self.name(1), "waiting", "started")
        auto_flow.start_resume(self.engine)
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "ai_off")))

    def test_auto_sends_nothing_when_no_project_is_known(self):
        with mock.patch.object(self.engine, "project_id", return_value=None):
            self.assertEqual(auto_flow.gate(self.engine, None), "ai_off")

    def test_gate_looks_at_the_sheets_project_and_the_current_one(self):
        self.assertTrue(self.engine.dispatch("aireview.send_policy", {"send": "deny"})["ok"])
        for project in (None, PROJECT, "OTHER"):
            self.assertEqual(auto_flow.gate(self.engine, project), "ai_off", project)
        self.engine.settings["project_id"] = "OTHER"
        self.assertEqual(auto_flow.gate(self.engine, PROJECT), "ai_off")
        self.assertIsNone(auto_flow.gate(self.engine, "OTHER"))

    def test_deny_during_a_call_stops_every_sheet(self):
        self.client.answer = lambda q: self.engine.dispatch("aireview.send_policy", {"send": "deny"}) and NONE
        self.upload((1, big(1)), (2, big(2)))
        self.assertEqual((self.calls(), self.state(1), self.state(2)), (1, ("waiting", "ai_off"), ("waiting", "ai_off")))

    def test_taken_number_is_not_asked(self):
        self.upload((1, big(1)), number="taken")
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "taken")))
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.calls(), 0)


class CapTest(Base):
    def setUp(self):
        super().setUp()
        self.consent()

    def test_thirty_files_stop_at_300_calls(self):
        self.upload(*[(i, big(i)) for i in range(1, 31)])
        self.assertEqual(self.calls(), 300)
        states = [self.state(i) for i in range(1, 31)]
        self.assertEqual(states.count(("confirmed", None)), 15)
        self.assertEqual(states.count(("waiting", "run_cap")), 15)
        self.assertEqual({(self.cell(i)["ai"] or {}).get("status") for i in range(1, 16)}, {"capped"})

    def test_143_files_dropped_together_stop_at_300_calls(self):
        self.upload(*[(i, big(i, unread=25)) for i in range(1, 144)])
        self.assertEqual(self.calls(), 300)
        self.assertEqual(sum(1 for i in range(1, 144) if self.level(i) == "auto"), 100)

    def test_each_resume_spends_at_most_300_more_and_finishes(self):
        self.upload(*[(i, big(i)) for i in range(1, 31)])
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.calls(), 600)
        self.assertTrue(all(self.level(i) == "auto" for i in range(1, 31)))
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.calls(), 600, "다 끝났으면 부르지 않는다")

    def test_files_added_while_jobs_run_share_the_budget(self):
        self.jobs = []
        with mock.patch.object(ar, "RUN_CAP", 25):
            # 앞 작업이 도는 사이 들어온 올리기: 예산은 하나
            first = self.engine.auto_budget
            first.enter()
            for _ in range(5):
                first.spend()
            self.upload((1, big(1)), (2, big(2)))
            first.leave()
        self.assertEqual(self.calls(), 20)

    def test_five_resumes_never_pass_20_calls_for_one_sheet(self):
        self.client.errors = ["transient"] * 2
        ex = big(1)
        self.upload((1, ex))
        for _ in range(5):
            auto_flow.start_resume(self.engine)
        self.assertEqual(self.calls(), 20)
        self.assertEqual(self.state(1), ("confirmed", None))

    def test_setting_does_not_raise_the_material_cap(self):
        self.engine.settings["extract_ai_cap"] = 200
        self.upload((1, big(1)))
        self.assertEqual(self.calls(), 20)

    def test_manual_calls_count_toward_the_material_cap(self):
        self.put(1, big(1))
        ar.merge_and_save(self.name(1), big(1), {"candidates": [], "stats": {"calls": 15, "left": 100, "errors": 0}}, via="fixed")
        self.upload((1, big(1)))
        self.assertEqual(self.calls(), 0, "앞서 추출한 옛 쪽은 다시 올려도 저절로 돌지 않는다")
        cf.record_auto(self.name(1), "waiting", "started")
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.calls(), 5)

    def test_third_failure_is_final(self):
        self.client.errors = ["transient"] * 9
        self.upload((1, big(1, unread=5)))
        self.assertEqual(self.state(1), ("waiting", "error"))
        auto_flow.start_resume(self.engine)
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.state(1), ("waiting", "error_final"))
        spent = self.calls()
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.calls(), spent)

    def test_usage_limit_stops_the_whole_batch(self):
        self.client.errors = [None, "limit_reached"]
        self.upload((1, big(1, unread=25)), (2, big(2, unread=25)))
        self.assertEqual(self.calls(), 2)
        self.assertEqual([self.state(i) for i in (1, 2)], [("waiting", "limit"), ("waiting", "limit")])
        self.assertEqual(len(ar.load_doc(self.name(1))["runs"]), 1, "받은 답은 저장한다")
        auto_flow.start_resume(self.engine)
        self.assertEqual([self.level(i) for i in (1, 2)], ["auto", "auto"])

    def test_the_next_upload_resumes_what_waited_within_one_budget(self):
        self.client.errors = ["limit_reached"]
        self.upload((1, big(1, unread=25)))
        self.upload((2, big(2, unread=25)))
        self.assertEqual([self.level(i) for i in (1, 2)], ["auto", "auto"])

    def test_calls_spent_on_an_older_reading_leave_the_rest_unconfirmed(self):
        self.upload((1, big(1)))
        self.assertEqual(self.calls(), 20)
        ex = big(1)
        ex["run"]["rules_version"] = "z"
        self.put(1, ex)
        auto_flow.start_resume(self.engine)
        self.assertEqual((self.calls(), self.level(1), self.cell(1)["ai"]["status"]), (20, "auto", "capped"))

    def test_three_same_errors_stop_the_batch(self):
        self.client.errors = ["timeout"] * 9
        self.upload(*[(i, big(i, unread=5)) for i in range(1, 7)])
        self.assertEqual(self.calls(), 3)
        self.assertEqual([self.state(i)[1] for i in range(1, 7)], ["error"] * 3 + ["stopped"] * 3, "묻지 않은 쪽은 실패가 아니다")

    def test_limit_after_the_last_answer_still_names_the_limit(self):
        self.client.answer = kinds("manual_valve")
        self.client.errors = [None, "limit_reached"]         # 첫 묻기는 다 받고 넓혀 묻기에서 한도
        wide = ai_images.ImageInput(Page(), [b"legend"], legend_source="symbols", wide=True)
        with mock.patch.object(ai_images, "image_input_for", return_value=wide):
            self.upload((1, big(1, unread=5)), (2, big(2, unread=5)))
        self.assertEqual((self.state(1), self.state(2), self.calls()), (("confirmed", None), ("waiting", "limit"), 2))

    def test_a_lower_user_cap_is_followed(self):
        self.engine.settings["extract_ai_cap"] = 5
        self.upload((1, big(1)))
        self.assertEqual((self.calls(), self.state(1), self.cell(1)["ai"]["status"]), (5, ("confirmed", None), "capped"))
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.calls(), 5)

    def test_a_job_that_cannot_start_gives_its_share_back(self):
        real, n = self.engine.start_job, []

        def boom(*a, **k):
            n.append(1)
            if len(n) == 2:
                raise RuntimeError("no thread")
            return real(*a, **k)
        self.engine.start_job = boom
        with self.assertRaises(RuntimeError):
            self.upload((1, big(1, unread=5)), (2, big(2, unread=5)), (3, big(3, unread=5)))
        self.assertEqual((self.engine.auto_budget._users, self.engine.auto_budget._files), (0, 0))

    def test_calls_of_every_version_of_the_sheet_count(self):
        self.put(1, big(1))
        ar.merge_and_save(self.name(1), big(1), {"candidates": [], "stats": {"calls": 15, "left": 9, "errors": 0, "at_id": 1}}, via="fixed")
        self.version = 2
        self.put(1, big(1))
        cf.record_auto(self.name(1), "waiting", "started")
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.calls(), 5)
        self.assertEqual(ar.calls_of(self.name(1)), 20)

    def test_a_failed_sheet_is_not_retried_by_its_own_upload(self):
        self.client.errors = ["transient"]
        self.upload((1, big(1, unread=5)))
        self.assertEqual((self.calls(), self.state(1)), (1, ("waiting", "error")))


class FinishTest(Base):
    def setUp(self):
        super().setUp()
        self.consent()

    def test_no_person_is_needed_and_nothing_is_accepted_while_off(self):
        self.client.answer = lambda request: {"answers": [
            {"item_id": it["item_id"], "field": "kind", "values": ["pump"], "confidence": 0.95, "reason": "시험", "match": "legend"}
            for it in json.loads(request["context"])["items"]]}
        self.upload((1, big(1, unread=5)))
        st = cf.sheet_confirmation(self.name(1))
        self.assertEqual((st["level"], st["state"], st["auto_accepted"], st["unconfirmed_targets"]), ("auto", "open", 0, 5))
        self.assertEqual(len(ar.load_doc(self.name(1))["candidates"]), 5, "꺼져 있으면 후보만 남는다")
        self.assertIsNone(co.load(self.name(1)))

    def test_one_constant_turns_acceptance_on(self):
        self.client.answer = lambda request: {"answers": [
            {"item_id": it["item_id"], "field": "kind", "values": ["pump"], "confidence": 0.95, "reason": "시험", "match": "legend"}
            for it in json.loads(request["context"])["items"]]}
        noted = []
        with mock.patch.object(ar, "AUTO_ACCEPT_ENABLED", True), mock.patch("hazop.shell.api_inputs.note", lambda e, n: noted.append(n)):
            self.upload((1, big(1, unread=5)))
        st = cf.sheet_confirmation(self.name(1))
        self.assertEqual((st["level"], st["auto_accepted"]), ("auto", 5))
        self.assertEqual(noted, [self.name(1)], "그래프 다시 짓기는 짓기 차례에 맡긴다")

    def test_old_sheets_are_never_started_by_themselves(self):
        self.put(1, big(1))
        auto_flow.start_resume(self.engine)
        self.upload((1, big(1)), outcome="reused")
        self.assertEqual((self.calls(), self.cell(1)), (0, None))

    def test_reupload_of_a_finished_sheet_calls_nothing(self):
        self.upload((1, big(1, unread=5)))
        spent = self.calls()
        self.upload((1, big(1, unread=5)), outcome="reused")
        self.assertEqual((self.calls(), self.level(1)), (spent, "auto"))

    def test_changed_reading_is_asked_again_within_the_cap(self):
        self.upload((1, big(1, unread=100)))
        self.assertEqual(self.calls(), 10)
        ex = big(1, unread=150)
        ex["run"]["rules_version"] = "z"
        os.utime(os.path.join(paths.output_root("extract"), self.name(1), "extraction.json"))
        self.put(1, ex)
        self.assertEqual(self.level(1), "extracted")
        auto_flow.start_resume(self.engine)
        self.assertEqual((self.calls(), self.state(1)), (20, ("confirmed", None)))

    def test_reverted_sheet_stays_reverted(self):
        self.upload((1, big(1, unread=5)))
        ar.auto_revert(self.name(1), "검토자")
        self.upload((1, big(1, unread=5)), outcome="reused")
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.state(1), ("reverted", None))

    def test_manual_run_and_auto_run_do_not_overlap(self):
        held = self.engine.reserve_review([self.name(1)])
        self.upload((1, big(1, unread=5)))
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "started")))
        self.engine.release_review(held)
        auto_flow.start_resume(self.engine)
        self.assertEqual((self.calls(), self.level(1)), (1, "auto"))

    def test_manual_run_is_refused_while_auto_holds_the_sheet(self):
        seen = []
        self.client.answer = lambda request: seen.append(self.engine.reserve_review([self.name(1)])) or NONE
        self.upload((1, big(1, unread=5)))
        self.assertEqual(seen, [[]])
        self.assertEqual(self.engine._reviewing, set(), "끝나면 놓는다")

    def test_number_confirm_waits_for_the_auto_run(self):
        from hazop.shell import api_titleblock
        got = []

        def ask(request):
            try:
                api_titleblock._busy_check(self.engine, "material-%012d" % 1)
            except api.CommandError as exc:
                got.append(exc.code)
            return NONE
        self.client.answer = ask
        self.upload((1, big(1, unread=5)))
        self.assertEqual(got, ["busy"])
        api_titleblock._busy_check(self.engine, "material-%012d" % 1)

    def test_auto_run_waits_while_the_number_is_being_changed(self):
        from hazop.shell import api_titleblock
        self.put(1, big(1, unread=5))
        cf.record_auto(self.name(1), "waiting", "started")
        with api_titleblock._hold(self.engine, "material-%012d" % 1):
            auto_flow.start_resume(self.engine)
            self.assertEqual(self.calls(), 0)
            with self.assertRaises(RuntimeError), api_titleblock._hold(self.engine, "material-%012d" % 1):
                pass
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.calls(), 1)

    def test_extracting_from_chat_also_goes_on_to_auto(self):
        from types import SimpleNamespace as NS
        from hazop.shell import chat_actions
        path = os.path.join(self.tmp, "r.json")
        regs = {"material-%012d" % 1: {"path": path, "has_result": False, "material_id": "material-%012d" % 1}}
        runner = chat_actions.RunExecutors(self.engine, lambda: None, lambda: regs, watch=False)
        with mock.patch("hazop.app.data.extract_and_graph", side_effect=lambda p: self.put(1, big(1, unread=5))):
            out = runner.extract({"registration_id": "material-%012d" % 1}, NS(action="register.extract"))
        self.assertTrue(out["ok"], out)
        self.assertEqual((self.calls(), self.level(1)), (1, "auto"))

    def on(self):
        for p in (mock.patch.object(ar, "AUTO_ACCEPT_ENABLED", True), mock.patch("hazop.shell.api_inputs.note")):
            p.start()
            self.addCleanup(p.stop)

    def test_an_answer_of_not_a_symbol_takes_the_old_proposal_away(self):
        self.on()
        self.client.errors, self.client.answer = [None, "transient"], kinds("pump")
        self.upload((1, big(1, unread=15)))
        self.assertEqual(self.state(1), ("waiting", "error"))
        self.client.answer = kinds("not_symbol")
        auto_flow.start_resume(self.engine)
        self.assertEqual(self.state(1), ("confirmed", None))
        self.assertEqual((cf.sheet_confirmation(self.name(1))["auto_accepted"], ar.load_doc(self.name(1))["candidates"]), (0, []))

    def test_old_proposals_are_not_accepted_after_a_new_reading_says_unknown(self):
        self.client.answer = kinds("pump")
        self.upload((1, big(1, unread=5)))
        ex = big(1, unread=5)
        ex["run"]["rules_version"] = "z"
        self.put(1, ex)
        self.client.answer = kinds("unknown")
        self.on()
        auto_flow.start_resume(self.engine)
        self.assertEqual((self.level(1), cf.sheet_confirmation(self.name(1))["auto_accepted"]), ("auto", 0))

    def test_what_a_person_decided_stays_when_the_answer_changes(self):
        self.client.answer = kinds("pump")
        ex = big(1, unread=3)
        self.upload((1, ex))
        doc = ar.load_doc(self.name(1))
        ids = [c["cand_id"] for c in doc["candidates"]]
        ar.reject(doc, ids[:1], "사람")
        ar.save_doc(doc)
        doc = ar.load_doc(self.name(1))
        self.assertEqual(ar.accept(doc, ids[1:2], ex, self.name(1), "사람"), [])
        doc = ar.load_doc(self.name(1))
        targets = [c["target"] for c in doc["candidates"]]
        ar.merge_and_save(self.name(1), ex, {"candidates": [], "answered": [[t, "kind"] for t in targets], "stats": {"calls": 1, "left": 0}}, auto=True)
        self.assertEqual([c["status"] for c in ar.load_doc(self.name(1))["candidates"]], ["rejected", "accepted"])

    def test_a_manual_run_never_takes_proposals_away(self):
        ex = big(1, unread=2)
        self.put(1, ex)
        c = ar.make_candidate("k", "kind", ex["nodes"][0], "kind", ["pump"], 0.9, "r")
        ar.merge_and_save(self.name(1), ex, {"candidates": [c], "stats": {"calls": 1, "left": 0}}, via="fixed")
        ar.merge_and_save(self.name(1), ex, {"candidates": [], "answered": [[c["target"], "kind"]], "stats": {"calls": 1, "left": 0}}, via="fixed")
        self.assertEqual(len(ar.load_doc(self.name(1))["candidates"]), 1)

    def test_stop_before_the_start_sends_nothing(self):
        self.put(1, big(1))
        cf.record_auto(self.name(1), "waiting", "started")
        self.engine._stop.set()
        auto_flow.run_budgeted(self.engine, [self.name(1)], lambda *a, **k: None)
        self.assertEqual((self.calls(), self.state(1)), (0, ("waiting", "stopped")))

    def test_a_batch_mixed_with_a_manually_held_sheet(self):
        for i in (1, 2):
            self.put(i, big(i, unread=5))
            cf.record_auto(self.name(i), "waiting", "started")
        held = self.engine.reserve_review([self.name(1)])
        out = auto_flow.run_budgeted(self.engine, [self.name(1), self.name(2)], lambda *a, **k: None)
        self.assertEqual((out["done"], self.state(1), self.level(2)), ([self.name(2)], ("waiting", "started"), "auto"))
        self.assertEqual(self.engine._reviewing, set(held), "남이 잡은 도면은 놓지 않는다")
        self.engine.release_review(held)

    def test_a_next_version_of_an_old_sheet_is_not_new(self):
        self.put(1, big(1, unread=5))
        self.version = 2
        self.upload((1, big(1, unread=5)), outcome="reused")
        self.assertEqual((self.calls(), self.cell(1)), (0, None), "소급 없음")

    def test_a_next_version_killed_before_the_record_is_not_new_either(self):
        self.put(1, big(1, unread=5))
        self.version = 2
        with mock.patch.object(auto_flow.Intake, "start", side_effect=Killed()), self.assertRaises(Killed):
            self.upload((1, big(1, unread=5)), outcome="reused")
        self.engine = self.make_engine()
        auto_flow.start_resume(self.engine)
        self.assertEqual((self.calls(), self.cell(1)), (0, None))

    def test_sheets_confirmed_while_off_stay_out_after_turning_on(self):
        self.client.answer = kinds("pump")
        self.upload((1, big(1, unread=5)))
        self.on()
        auto_flow.start_resume(self.engine)
        self.assertEqual(auto_flow.restart_names(self.engine, ["graph-1"]), [], "이미 이 읽기로 자동 확정된 쪽은 다시 하기 대상이 아니다")
        self.assertEqual(cf.sheet_confirmation(self.name(1))["auto_accepted"], 0)

    def test_human_fixed_spots_are_not_asked(self):
        ex = big(1, unread=5)
        self.put(1, ex)
        co.save(self.name(1), [co.make_op(ex, "set_tag", "pdf-p0-sym-0002", {"tag": "HUMAN1"}, "사람", name=self.name(1))], "사람")
        cf.record_auto(self.name(1), "waiting", "started")
        auto_flow.start_resume(self.engine)
        asked = [i["target"] if "target" in i else i["item_id"] for q in self.client.requests for i in json.loads(q["context"])["items"]]
        self.assertTrue(asked)
        self.assertFalse([a for a in asked if a.endswith("0002")], asked)

    def test_an_unexpected_error_leaves_the_registration_done_and_the_sheet_waiting(self):
        with mock.patch.object(ar, "run", side_effect=RuntimeError("C:\\secret")):
            self.upload((1, big(1, unread=5)))
        self.assertEqual(self.failed_jobs(), [])
        self.assertEqual(self.state(1), ("waiting", "error"))
        done = [e for e in self.engine._emit.items if e.get("name") == "job.done"]
        self.assertNotIn("secret", json.dumps(done, ensure_ascii=False))

    def test_two_threads_resume_once(self):
        self.jobs = []
        self.upload((1, big(1, unread=5)), number="off")
        cf.record_auto(self.name(1), "waiting", "started")
        doc = ar.load_doc(self.name(1))
        doc["runs"] = []
        ar.save_doc(doc)
        self.client.requests.clear()
        self.jobs = None
        ts = [threading.Thread(target=auto_flow.start_resume, args=(self.engine,)) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
        self.assertEqual(self.calls(), 1)

    def test_unread_answers_are_kept_for_the_drawing_tab_only(self):
        self.client.answer = lambda request: {"answers": [
            {"item_id": it["item_id"], "field": "kind", "values": ["not_symbol" if n < 2 else "unknown"], "confidence": 0.9, "reason": "시험", "match": "other"}
            for n, it in enumerate(json.loads(request["context"])["items"])]}
        before = None
        self.put(1, big(1, unread=3))
        before = cf.sheet_confirmation(self.name(1))["unconfirmed_targets"]
        os.remove(os.path.join(paths.output_root("extract"), self.name(1), "extraction.json"))
        self.upload((1, big(1, unread=3)))
        st = cf.sheet_confirmation(self.name(1))
        self.assertEqual((st["unconfirmed_targets"], st["counts"]["ai_pending"]), (before, 0), "미확인 수에서 빼지 않는다")
        _orig, corrected = big(1, unread=3), co.resolve(self.name(1), big(1, unread=3))["corrected"]
        items = clean_items.build(corrected, self.name(1))["items"]
        self.assertEqual([items["Lpdf-p0-sym-%04d" % k].get("ai_answer") for k in range(3)], ["not_symbol", "not_symbol", "unknown"])
        self.assertNotIn("ai_answer", items["Lpdf-p0-sym-9999"])
        corrected["nodes"][0]["geometry"]["x"] += 50           # 번호가 밀려 다른 자리가 된 기호에는 붙지 않는다
        self.assertNotIn("ai_answer", clean_items.build(corrected, self.name(1))["items"]["Lpdf-p0-sym-0000"])
        corrected["nodes"][1]["kind"] = "pump"                 # 사람이 종류를 정한 기호에도 붙지 않는다
        self.assertNotIn("ai_answer", clean_items.build(corrected, self.name(1))["items"]["Lpdf-p0-sym-0001"])


class Killed(BaseException):
    pass


class RestartTest(Base):
    """앱 닫기·강제 종료 뒤 이어 하기. 호출을 두 번 쓰지 않는다."""

    def setUp(self):
        super().setUp()
        self.consent()

    def reopen(self):
        self.engine = self.make_engine()
        self.assertTrue(auto_flow.consent(self.engine)["allow"] or self.consent())
        auto_flow.start_resume(self.engine)

    def test_close_during_a_call_keeps_answers_and_resumes(self):
        def ask(request):
            if self.calls() == 3:
                self.engine.stop_jobs()
            return NONE
        self.client.answer = ask
        self.jobs = []                      # 창을 닫을 때처럼 두 작업이 함께 서 있다
        self.upload((1, big(1, unread=100)), (2, big(2, unread=20)))
        self.jobs = None
        self.assertEqual(self.calls(), 3)
        self.assertEqual(self.state(1), ("waiting", "stopped"))
        self.assertNotIn("graph-2", self.known, "멈춘 뒤 시작할 파일은 추출하지 않는다")
        self.reopen()
        self.assertEqual(self.level(1), "auto")
        self.assertEqual(sum(r["calls"] for r in ar.load_doc(self.name(1))["runs"]), 13)

    def test_kill_during_a_call_still_counts_the_calls(self):
        def ask(request):
            if self.calls() == 15:
                raise Killed()
            return NONE
        self.client.answer = ask
        with self.assertRaises(Killed):
            self.upload((1, big(1)))
        self.assertIsNone(ar.load_doc(self.name(1)), "죽으면 받은 답은 없다")
        self.client.answer = lambda request: NONE
        for _ in range(3):
            self.reopen()
        self.assertEqual(self.calls(), 20, "죽기 전에 쓴 15회까지 세어 20회를 넘지 않는다")
        self.assertEqual(self.state(1), ("confirmed", None))

    def test_calls_already_in_a_run_are_not_counted_again(self):
        self.upload((1, big(1, unread=25)))
        run = ar.load_doc(self.name(1))["runs"][-1]
        self.assertTrue(run["auto_id"])
        from hazop import store_io
        store_io.write_json(auto_flow._call_path(big(1)), {"auto_id": run["auto_id"], "calls": 3, "items": 25})      # 저장 뒤 표지를 지우기 전에 죽음
        auto_flow._recover(self.name(1), big(1))
        self.assertEqual((ar.calls_of(self.name(1)), os.path.exists(auto_flow._call_path(big(1)))), (3, False))

    def test_the_same_pdf_in_two_projects_keeps_separate_counts(self):
        def ask(request):
            if self.calls() == 15:
                raise Killed()
            return NONE
        self.client.answer = ask
        with self.assertRaises(Killed):
            self.upload((1, big(1)))
        self.client.answer = lambda q: NONE
        other = "OTHER__material-%012d-r1-p0" % 1
        d = os.path.join(paths.output_root("extract"), other)
        os.makedirs(d)
        with open(os.path.join(d, "extraction.json"), "w", encoding="utf-8") as fh:
            json.dump(big(1, project="OTHER"), fh)
        e = self.make_engine()
        e.settings["project_id"] = "OTHER"
        e.graph_names = lambda: {"gb": other}
        cf.record_auto(other, "waiting", "started")
        auto_flow.start_resume(e)
        self.assertEqual(self.calls() - 15, 20)
        self.reopen()
        self.assertEqual(self.calls(), 40, "A도 죽기 전 15회를 세어 20회까지")

    def test_kill_after_saving_the_answers_does_not_call_again(self):
        with mock.patch.object(ar, "auto_finish", side_effect=Killed()), self.assertRaises(Killed):
            self.upload((1, big(1, unread=25)))
        self.assertEqual(self.calls(), 3)
        self.reopen()
        self.assertEqual((self.calls(), self.level(1)), (3, "auto"))

    def test_kill_after_extraction_before_the_record_is_picked_up(self):
        with mock.patch.object(cf, "record_auto", side_effect=Killed()), self.assertRaises(Killed):
            self.upload((1, big(1, unread=5)))
        self.assertIsNone(self.cell(1))
        self.reopen()
        self.assertEqual(self.level(1), "auto")

    def test_resume_twice_calls_once(self):
        self.engine.ai.ready = False
        self.upload((1, big(1, unread=25)))
        self.engine.ai.ready = True
        self.engine.on_connection()
        self.engine.on_connection()
        auto_flow.start_resume(self.engine)
        self.assertEqual((self.calls(), self.level(1)), (3, "auto"))

    def test_opening_the_app_resumes(self):
        self.engine.ai.ready = False
        self.upload((1, big(1, unread=5)))
        self.engine = self.make_engine()
        self.consent_again = auto_flow.consent(self.engine)
        with mock.patch.object(self.engine, "settle_on_open"), mock.patch.object(self.engine, "auto_catch_up", return_value=False):
            self.engine.catch_up_on_open()
        self.assertEqual(self.level(1), "auto")


class ChatTest(Base):
    def setUp(self):
        super().setUp()
        self.consent()
        from hazop.shell import chat_actions
        self.chat = chat_actions
        self.upload((1, big(1, unread=5)))

    def run_action(self, action, **args):
        from types import SimpleNamespace as NS
        item = NS(action=action, args=args, targets=[], basis=None)
        why = self.chat.auto_checks(self.engine)[action](item, None)
        if why:
            return why
        self.details = self.chat.auto_details(self.engine)[action](item, None)
        return self.chat.auto_executors(self.engine)[action](args, NS(basis=item.basis, confirmed_by="홍길동", action=action))

    def accepted(self):
        self.client.answer = lambda request: {"answers": [
            {"item_id": it["item_id"], "field": "kind", "values": ["pump"], "confidence": 0.95, "reason": "시험", "match": "legend"}
            for it in json.loads(request["context"])["items"]]}
        p = mock.patch.object(ar, "AUTO_ACCEPT_ENABLED", True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("hazop.shell.api_inputs.note")
        self.note = p.start()
        self.addCleanup(p.stop)
        self.upload((2, big(2, unread=5)))
        return co.load(self.name(2))["ops"]

    def test_actions_are_confirm_actions_known_to_the_model(self):
        from hazop.chat import actions as A, card
        for name in ("aireview.auto_run", "aireview.auto_revert"):
            self.assertEqual(A.ACTIONS[name].klass, A.CONFIRM)
            self.assertIn(name, card.PROMPT_ACTIONS)
            self.assertIn(name, self.chat.RUN_ACTIONS)
            self.assertIn(name, self.chat.TITLES)

    def test_revert_takes_out_every_auto_value_of_the_sheet(self):
        self.assertEqual(len(self.accepted()), 5)
        out = self.run_action("aireview.auto_revert", graph_id="graph-2")
        self.assertTrue(out["ok"], out)
        self.assertEqual((co.load(self.name(2))["ops"], self.state(2)), ([], ("reverted", None)))
        self.assertIn("5", " ".join(str(r["after"]) for r in self.details))
        self.assertEqual(self.level(2), "extracted")

    def test_revert_names_dependent_human_edits_and_takes_the_seen_list(self):
        ops = self.accepted()
        with mock.patch.object(co, "dependents", side_effect=lambda all_, oid: ["h1"] if oid == ops[0]["op_id"] else []), \
                mock.patch.object(co, "load", side_effect=lambda n: {"ops": ops + [{"op_id": "h1", "op": "set_tag", "origin": "human"}]}):
            got = auto_flow.revert_preview(self.name(2))
        self.assertEqual((got["confirm"], got["count"]), (["h1"], 5))

    def test_revert_needs_something_to_revert_and_the_seen_version(self):
        self.put(3, big(3))
        self.assertIsInstance(self.run_action("aireview.auto_revert", graph_id="graph-3"), str)
        self.assertIsInstance(self.run_action("aireview.auto_revert", graph_id="graph-9"), str)
        out = AR.auto_revert(self.engine, "graph-1", "낡은 판", by="홍길동")
        self.assertEqual(out["code"], "stale")

    def test_run_again_restarts_a_reverted_sheet_as_the_person(self):
        self.accepted()
        self.run_action("aireview.auto_revert", graph_id="graph-2")
        out = self.run_action("aireview.auto_run", graph_ids=["graph-2"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.state(2), ("confirmed", None))
        self.assertEqual(co.load(self.name(2))["ops"], [], "사람이 물린 자리는 다시 받지 않는다")

    def test_run_starts_an_old_sheet_and_refuses_without_consent(self):
        self.put(3, big(3, unread=5))
        self.assertTrue(self.run_action("aireview.auto_run", graph_ids=["graph-3"])["ok"])
        self.assertEqual(self.level(3), "auto")
        self.consent(False)
        self.put(4, big(4))
        self.assertIsInstance(self.run_action("aireview.auto_run", graph_ids=["graph-4"]), str)
        self.assertIsNone(self.cell(4))

    def test_undo_of_an_auto_value_points_to_the_chat_action(self):
        op = self.accepted()[0]["op_id"]
        out = AC.undo(self.engine, "graph-2", op, AC.view(self.engine, "graph-2")["ver"])
        self.assertEqual(out["code"], "bad_args")
        self.assertIn("채팅", out["message"])
        self.assertNotIn("패널", out["message"])


class DefectTest(Base):
    """같이 고치는 기존 결함 둘."""

    def one(self, unread=0):
        ex = big(1, unread=unread)
        self.put(1, ex)
        return ex

    def test_a_confirmed_sheet_warns_that_an_edit_releases_it(self):
        ex = self.one()
        ex["leftovers"] = {"paths": [], "texts": []}
        self.put(1, ex)
        for cmd in ("compare", "confirm"):
            st = cf.sheet_confirmation(self.name(1))
            out = cf.execute(self.name(1), cmd, {}, "검토자", st["fingerprint"], st["rev"])
            self.assertTrue(out["ok"], out)
            got = AC._impact(self.engine, "graph-1", self.name(1), ["x"])["sheet"]
            self.assertEqual(got, {"compare": "compared", "confirm": "confirmed"}[cmd])
        self.assertIn("확정이 풀립니다", AC._confirm_text("지우기", ["x"], {"nodes": [], "sheet": got}))
        with mock.patch.object(AC.sheet_refresh, "refresh", return_value=(False, [], [])):
            out = AC.apply_edit(self.engine, "graph-1", "set_tag", "Lpdf-p0-sym-9999", {"tag": "PP02"}, AC.view(self.engine, "graph-1")["ver"])
        self.assertTrue(out["released"], out)

    def test_a_auto_level_is_not_reported_as_released(self):
        self.consent()
        self.upload((1, big(1, unread=2)))
        self.assertEqual(self.level(1), "auto")
        self.assertIsNone(AC._impact(self.engine, "graph-1", self.name(1), ["x"])["sheet"])

    def test_b_pending_candidate_shows_on_its_symbol(self):
        ex = self.one(unread=2)
        n = ex["nodes"][0]
        c = ar.make_candidate("k", "kind", n, "kind", ["pump"], 0.5, "r")
        ar.merge_and_save(self.name(1), ex, {"candidates": [c], "stats": {"calls": 1, "left": 0}}, via="fixed")
        out = clean_items.build(ex, self.name(1))
        self.assertEqual(out["items"][n["local_id"]]["review"], "ai_candidate")
        self.assertEqual(out["counts"]["ai_candidate"], 1)
        self.assertEqual(out["items"][ex["nodes"][1]["local_id"]]["review"], "script")

    def test_b_auto_value_is_marked_apart_from_a_person(self):
        ex = self.one(unread=2)
        ex["nodes"][0]["human_edit"] = {"op_ids": ["a"], "ops": ["set_kind"], "auto": ["set_kind"], "by": "hazop:auto"}
        ex["nodes"][1]["human_edit"] = {"op_ids": ["b"], "ops": ["set_kind"], "by": "검토자"}
        items = clean_items.build(ex, self.name(1))["items"]
        self.assertEqual([items[n["local_id"]]["review"] for n in ex["nodes"][:2]], ["ai_auto", "human"])


class RealUploadTest(unittest.TestCase):
    """대역 없이: 실제 등록·추출·그래프·그림 입력, 가짜 AI만."""

    def test_one_upload_reaches_auto_and_the_knowledge_graph(self):
        tmp = tempfile.mkdtemp(prefix="hazop-autoflow-real-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(tmp, "store")}):
            os.makedirs(os.environ["HAZOP_WORK_ROOT"])
            client = StubClient(lambda request: NONE)
            e = api.Engine(settings_path=os.path.join(tmp, "settings.json"), emit=Events(), run_jobs=lambda _i, fn: fn(), ai=FakeAi(client))
            e.settings.update(reviewer_name="검토자", project_id="REAL-P")
            self.assertTrue(e.dispatch("aireview.consent", {"allow": True})["ok"])
            src = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]
            e.add_files([src])
            self.assertEqual([x for x in e._emit.items if x.get("name") == "job.failed"], [])
            (gid, name), = e.graph_names().items()
            st = cf.sheet_confirmation(name)
            self.assertEqual((st["level"], st["auto"]["result"], st["auto_accepted"]), ("auto", "confirmed", 0))
            self.assertTrue(client.requests and all(q.get("images") for q in client.requests))
            from hazop.app import project_ctx
            self.assertTrue(project_ctx.project_graph("REAL-P")["nodes"])
            spent = len(client.requests)
            from hazop.shell import api_titleblock as T
            mid = st["auto"] and next(r["material_id"] for r in T.summary(e)["rows"])
            row = next(r for r in T.summary(e)["rows"])
            self.assertEqual(row["material_id"], mid)
            out = e.dispatch("titleblock.confirm", {"material_id": mid, "ver": row["ver"], "fields": {"drawing_number": "SNP-M-102X"}})
            self.assertTrue(out["ok"], out)
            new = list(e.graph_names().values())[0]
            self.assertNotEqual(new, name)
            auto_flow.start_resume(e)
            self.assertEqual((len(client.requests), cf.sheet_confirmation(new)["level"]), (spent, "auto"), "번호 확정 뒤 새 호출 0")
            e.wait_jobs(20)


class NextVersionTest(unittest.TestCase):
    """등록판이 올라간 뒤 번호 확정 길 밖에서 추출되는 길(대역 없는 등록·추출). 되돌림과 누적 호출이 남아야 한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-autoflow-next-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")}),
                  mock.patch.object(ar, "AUTO_ACCEPT_ENABLED", True), mock.patch.object(ar, "IMAGE_BATCH", 1), mock.patch("hazop.shell.api_inputs.note")):
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        self.client = StubClient(kinds("pump"))
        self.e = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=Events(), run_jobs=lambda _i, fn: fn(), ai=FakeAi(self.client))
        self.e.settings.update(reviewer_name="검토자", project_id="REAL-P")
        self.addCleanup(self.e.wait_jobs, 20)
        self.assertTrue(self.e.dispatch("aireview.consent", {"allow": True})["ok"])
        self.src = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]
        self.e.add_files([self.src])
        (self.name,) = self.e.graph_names().values()
        self.assertEqual(cf.sheet_confirmation(self.name)["level"], "auto")
        self.assertTrue(self.client.requests)
        ar.auto_revert(self.name, "검토자")
        self.spent = len(self.client.requests)
        from hazop.shell import api_titleblock
        self.row = api_titleblock.summary(self.e)["rows"][0]

    def check(self):
        (new,) = self.e.graph_names().values()
        self.assertNotEqual(new, self.name)
        st = cf.sheet_confirmation(new)
        self.assertEqual((st["auto"]["result"], st["auto_accepted"], len(self.client.requests)), ("reverted", 0, self.spent))
        self.assertEqual(ar.calls_of(new), self.spent)
        auto_flow.start_resume(self.e)
        self.assertEqual(len(self.client.requests), self.spent)
        return new

    def failed_confirm(self):
        from hazop.app import data
        with mock.patch.object(data, "extract_and_graph", side_effect=OSError("disk full")):
            self.e.dispatch("titleblock.confirm", {"material_id": self.row["material_id"], "ver": self.row["ver"], "fields": {"title": "T2"}})

    def test_reupload_after_a_failed_confirm(self):
        self.failed_confirm()
        self.e.add_files([self.src])
        self.check()

    def test_chat_reextract_after_a_failed_confirm(self):
        from types import SimpleNamespace as NS
        from hazop.register import registry
        from hazop.shell import chat_actions
        self.failed_confirm()
        _rec, path = registry.latest("REAL-P", self.row["material_id"])
        regs = {self.row["material_id"]: {"path": path, "has_result": True, "material_id": self.row["material_id"]}}
        runner = chat_actions.RunExecutors(self.e, lambda: None, lambda: regs, watch=False)
        self.assertTrue(runner.extract({"registration_id": self.row["material_id"]}, NS(action="register.reextract"))["ok"])
        self.check()

    def classic_register(self):
        """이전 화면이 쪽 제목·개정을 적어 다시 등록하면 새 등록판이 된다."""
        from hazop.register import registry
        res = registry.register(self.src, "REAL-P", "P&ID", paths.store_root(), {"title": "옛 화면 제목", "design_revision": "1", "by": "사람"}, "사람")
        self.assertEqual(res["outcome"], "new_version")
        return res

    def test_classic_registration_then_reupload(self):
        self.classic_register()
        self.e.add_files([self.src])
        self.check()

    def test_classic_registration_and_extraction_then_reupload(self):
        from hazop.app import data
        data.extract_and_graph(self.classic_register()["registration_file"])
        self.e.add_files([self.src])
        self.check()

    def test_classic_extraction_then_the_person_restarts(self):
        from hazop.app import data
        ex = data.read_json(data.extraction_path(self.name))
        mine = co.make_op(ex, "set_tag", ex["nodes"][0]["source_object_id"], {"tag": "HUMAN-9"}, "검토자", name=self.name)
        co.save(self.name, ((co.load(self.name) or {}).get("ops") or []) + [mine], "검토자")
        data.extract_and_graph(self.classic_register()["registration_file"])
        (gid, new), = self.e.graph_names().items()
        auto_flow.restart(self.e, [gid], "검토자")
        st = cf.sheet_confirmation(new)
        self.assertEqual((st["auto_accepted"], ar.calls_of(new) <= 20), (0, True), "사람이 물린 자리는 다시 받지 않고 호출도 이어서 센다")
        self.assertEqual(ar.calls_of(new), len(self.client.requests))
        self.assertIn("HUMAN-9", [(o.get("value") or {}).get("tag") for o in co.load(new)["ops"]], "사람 고침도 앞 판에서 따라온다")

    def test_a_failed_extraction_leaves_no_copy(self):
        from hazop.app import data
        self.failed_confirm()
        before = {os.path.join(d, f) for d, _s, fs in os.walk(os.path.join(os.environ["HAZOP_WORK_ROOT"], "data")) for f in fs if "-r2-" in f}
        with mock.patch.object(data, "extract_and_graph", side_effect=OSError("x")), mock.patch.object(register_flow.data, "extract_and_graph", side_effect=OSError("x")):
            self.e.add_files([self.src])
        after = {os.path.join(d, f) for d, _s, fs in os.walk(os.path.join(os.environ["HAZOP_WORK_ROOT"], "data")) for f in fs if "-r2-" in f}
        self.assertEqual(after, before)


class OpenFolderTest(unittest.TestCase):
    """'내보낸 폴더 열기'(export.open_folder): 화면은 종류만 보내고 폴더는 앱이 실제로 내보낸 기록에서 정한다."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="hazop-openfolder-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        p.start()
        self.addCleanup(p.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        self.e = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=Events(), run_jobs=lambda _i, fn: fn())
        self.e.settings["project_id"] = "P"
        self.opened = []
        self.e.hooks["explore"] = self.opened.append
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)

    def open(self, kind):
        return self.e.dispatch("export.open_folder", {"kind": kind}, project="P", via_web=True)

    def exported(self, kind="excel", name="a.xlsx", folder=None):
        """저장 대화상자가 고른 자리에 앱이 실제로 쓴 것처럼."""
        folder = folder or self.out
        path = folder if kind == "dexpi" else os.path.join(folder, name)
        if kind == "dexpi":
            self.e.hooks["save_dir"] = lambda k: path
            self.e.hooks["save_dir"]("dexpi")
            path = os.path.join(path, "manifest.json")
        else:
            self.e.hooks["save_path"] = lambda k, d: path
            self.e.hooks["save_path"](kind, "x")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x")

    def test_opens_what_was_exported_per_kind(self):
        self.exported("excel")
        self.assertTrue(self.open("excel")["ok"])
        self.exported("dexpi")
        self.assertTrue(self.open("dexpi")["ok"])
        self.assertEqual(self.opened, [self.out, self.out])
        self.assertFalse(self.open("ie")["ok"])

    def test_chat_exports_folder(self):
        self.assertFalse(self.open("chat")["ok"])
        d = paths.output_root("exports")
        os.makedirs(d)
        self.assertTrue(self.open("chat")["ok"])
        self.assertEqual(self.opened, [os.path.realpath(d)])

    def test_the_screen_cannot_name_a_path(self):
        for args in ({"kind": "excel", "path": self.out}, {"path": self.out}, {"kind": self.out}, {"kind": "..\\.."}, {}):
            self.assertFalse(self.e.dispatch("export.open_folder", args, project="P", via_web=True)["ok"], args)
        self.assertEqual(self.opened, [])

    def test_needs_a_real_export(self):
        self.e.hooks["save_path"] = lambda k, d: os.path.join(self.out, "never.xlsx")
        self.e.hooks["save_path"]("excel", "x")                 # 자리만 고르고 쓰지 않음
        self.assertFalse(self.open("excel")["ok"])
        self.e.hooks["save_path"] = lambda k, d: None           # 취소
        self.e.hooks["save_path"]("excel", "x")
        self.assertFalse(self.open("excel")["ok"])

    def test_a_cancel_keeps_the_last_export(self):
        self.exported("excel")
        self.e.hooks["save_path"] = lambda k, d: None
        self.e.hooks["save_path"]("excel", "x")
        self.assertTrue(self.open("excel")["ok"])

    def test_other_project_and_gone_folder(self):
        self.exported("excel")
        self.e.settings["project_id"] = "Q"
        self.assertFalse(self.e.dispatch("export.open_folder", {"kind": "excel"}, project="Q", via_web=True)["ok"])
        self.e.settings["project_id"] = "P"
        shutil.rmtree(self.out)
        self.assertFalse(self.open("excel")["ok"])
        with open(self.out, "w", encoding="utf-8") as fh:       # 그 자리에 파일이 들어와도 열지 않는다
            fh.write("x")
        self.assertFalse(self.open("excel")["ok"])
        self.assertEqual(self.opened, [])

    def test_unc_and_links_are_refused(self):
        self.e.hooks["save_path"] = lambda k, d: r"\\server\share\a.xlsx"
        self.e.hooks["save_path"]("excel", "x")
        with mock.patch("os.path.isfile", return_value=True), mock.patch("os.path.getmtime", return_value=9e12), mock.patch("os.path.isdir", return_value=True):
            self.assertFalse(self.open("excel")["ok"])
        link = os.path.join(self.tmp, "link")
        import _winapi
        _winapi.CreateJunction(self.out, link)
        self.exported("excel", folder=link)
        self.assertFalse(self.open("excel")["ok"])
        os.rmdir(link)
        self.assertEqual(self.opened, [])

    def test_exports_folder_turned_into_a_link_is_refused(self):
        import _winapi
        d = paths.output_root("exports")
        os.makedirs(os.path.dirname(d))
        _winapi.CreateJunction(self.out, d)
        self.assertFalse(self.open("chat")["ok"])
        os.rmdir(d)

    def test_only_folders_are_explored(self):
        self.exported("excel")
        del self.e.hooks["explore"]
        with mock.patch("os.startfile") as start:
            self.assertTrue(self.open("excel")["ok"])
        start.assert_called_once_with(self.out, "explore")


if __name__ == "__main__":
    unittest.main()
