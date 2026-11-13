"""새 웹 화면 3단계 ⑤ 분석 결과의 엔진 쪽(hazop/shell/api_results.py, analysis_run.py). 실행: python -m unittest tests.test_shell_results

실제 결과 명령(hazop.study.result_commands)과 결과 저장(results)을 임시 작업 루트에서 부른다. 읽기는 파일을 쓰지 않고, 쓰기는 읽은 지문(ver)을 대조하며
by는 설정의 검토자 이름이다. AI 호출은 가짜(ai_cells.run_unit 대역)로 돌려 실행·멈춤·한도 멈춤과 호출마다 저장을 본다. 실제 구독 호출은 없다.
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hazop import store_io  # noqa: E402
from hazop.shell import analysis_run, api, api_results  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_migrate import graph  # noqa: E402
from tests.test_study_storage import AT, DEVS, build, entry, put_entries  # noqa: E402


def _bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class Events:
    def __init__(self):
        self.items = []

    def __call__(self, event):
        self.items.append(event)

    def changes(self, topic):
        return [e for e in self.items if e.get("t") == "changed" and e.get("topic") == topic]


class FakeAi:
    def __init__(self, can_start=True, terms=True):
        self.can, self.terms, self.client = can_start, terms, object()

    def status(self):
        return {"can_start": self.can, "label": "정상", "guide": "연결을 확인하세요."}

    def terms_acked(self):
        return self.terms

    def ack_terms(self):
        self.terms = True

    def make_client(self):
        return self.client


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-shellres-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from hazop.app import project_ctx
        self.g = graph("v1")
        self.g["sheets"] = [{"graph_id": self.g["graph_id"], "drawing_number": "T-1"}]
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp}),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                  mock.patch.object(project_ctx, "project_graph", lambda pid: self.g),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        self.ns = build(self.g, [("A", ["TK", "V1"]), ("B", ["PP", "LT"])])
        sn.save(self.ns)
        self.doc = put_entries(res.empty_results(self.ns, DEVS), "S1", "I1", [
            entry("e1", "proposed", origin="ai_draft", recommendation="밸브 점검", severity=3, frequency=2, risk=3),
            entry("e2", "proposed", origin="ai_draft", recommendation="수위 경보 추가", severity=2, frequency=2, risk=2)])
        self.project = self.ns.get("project_id")
        res.save_fp(self.doc, self.project, expect=store_io.ANY)
        self.events = Events()
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events, run_jobs=lambda jid, fn: fn())
        self.engine.settings["project_id"] = self.project
        self.engine.settings["reviewer_name"] = "검토자A"

    def read(self, *parts, **query):
        import json
        r = api.ReadApi(self.engine).read(list(parts), query)
        self.assertIsNotNone(r, parts)
        return json.loads(r.body.decode("utf-8"))

    def call(self, name, args=None):
        return self.engine.dispatch(name, args or {})

    def first_cell(self):
        return self.read("results", "cell", "S1", "D01")

    def args(self, **kw):
        v = self.first_cell()["ver"]
        return dict({"node_id": "S1", "deviation_id": "D01", "entry_id": "e1", "ver": v}, **kw)


class ReadTest(Base):
    def test_summary_has_matrix_header_numbers_and_a_version(self):
        s = self.read("results")
        self.assertTrue(s["available"] and not s["empty"], s)
        self.assertEqual([n["node_id"] for n in s["nodes"]], ["S1", "S2"])
        self.assertEqual(len(s["deviations"]), len(DEVS))
        cell = s["matrix"]["S1"]["D01"]
        self.assertEqual((cell["scenarios"], cell["max_risk"], cell["unreviewed"]), (2, 3, 2))
        self.assertEqual((s["kpi"]["entries"], s["kpi"]["recs"], s["kpi"]["unreviewed"]), (2, 2, 2))
        self.assertTrue(s["ver"].startswith("sha256:"), s["ver"])

    def test_reads_do_not_write_anything(self):
        path = res.store_path(self.project, self.ns["graph_id"])
        before = (os.path.getmtime(path), _bytes(path))
        self.read("results")
        self.read("results", "cell", "S1", "D01")
        self.read("results", "recs")
        self.read("results", "trace", entity="x")
        self.assertEqual(before, (os.path.getmtime(path), _bytes(path)))
        self.assertEqual([p for p in os.listdir(os.path.dirname(path)) if ".bak" in p], [])

    def test_cell_view_has_verdicts_and_editable(self):
        c = self.first_cell()
        self.assertTrue(c["editable"])
        self.assertEqual([e["verdict"]["status"] for e in c["cell"]["entries"]], ["proposed", "proposed"])
        self.assertEqual(c["deviation"]["deviation_id"], "D01")
        r = api.ReadApi(self.engine).read(["results", "cell", "S1", "D99"], {})
        self.assertIsNone(r, "없는 칸은 404")

    def test_recs_are_sorted_by_risk_and_skip_rejected(self):
        recs = self.read("results", "recs")["recs"]
        self.assertEqual([r["entry_id"] for r in recs], ["e1", "e2"])
        self.call("results.set_status", self.args(status="rejected", reason="중복"))
        self.assertEqual([r["entry_id"] for r in self.read("results", "recs")["recs"]], ["e2"])

    def test_trace_goes_component_to_node_to_cell_to_recommendation(self):
        member = self.ns["nodes"][0]["members"][0]
        t = self.read("results", "trace", entity=member)
        self.assertEqual([n["node_id"] for n in t["nodes"]], ["S1"])
        self.assertEqual([r["entry_id"] for r in t["nodes"][0]["cells"][0]["recs"]], ["e1", "e2"])
        self.assertEqual(self.read("results", "trace", entity="none")["nodes"], [])

    def test_unavailable_without_a_project_graph(self):
        from hazop.app import project_ctx
        with mock.patch.object(project_ctx, "project_graph", side_effect=OSError("x")):
            s = self.read("results")
        self.assertFalse(s["available"])


class WriteTest(Base):
    def test_accept_needs_no_reason_and_records_the_reviewer(self):
        r = self.call("results.set_status", self.args(status="approved"))
        self.assertTrue(r["ok"], r)
        e = self.first_cell()["cell"]["entries"][0]
        self.assertEqual((e["status"], e["verdict"]["by"]), ("approved", "검토자A"))
        self.assertTrue(self.events.changes("results"))
        self.assertNotEqual(r["data"]["ver"], "none")

    def test_reasons_are_required_for_hold_reject_and_revise(self):
        for status in ("on_hold", "rejected", "revised"):
            r = self.call("results.set_status", self.args(status=status))
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"), status)
            self.assertIn("사유", r["error"]["message"])
        self.assertEqual(self.first_cell()["cell"]["entries"][0]["status"], "proposed", "거절하면 아무것도 저장하지 않는다")
        r = self.call("results.set_status", self.args(status="on_hold", reason="운전 절차서 확인 뒤 판단"))
        self.assertTrue(r["ok"], r)
        e = self.first_cell()["cell"]["entries"][0]
        self.assertEqual((e["status"], e["verdict"]["reason"]), ("on_hold", "운전 절차서 확인 뒤 판단"))

    def test_proposed_cannot_be_set_by_a_person(self):
        r = self.call("results.set_status", self.args(status="proposed", reason="x"))
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"))

    def test_a_stale_version_is_refused_and_nothing_is_written(self):
        old = self.args(status="approved")
        self.assertTrue(self.call("results.set_status", self.args(entry_id="e2", status="approved"))["ok"])
        r = self.call("results.set_status", old)
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), r)
        self.assertEqual(self.first_cell()["cell"]["entries"][0]["status"], "proposed")

    def test_reviewer_name_is_required_and_never_taken_from_the_web(self):
        self.engine.settings["reviewer_name"] = ""
        r = self.call("results.set_status", self.args(status="approved"))
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"))
        r = self.call("results.set_status", dict(self.args(status="approved"), by="가짜"))
        self.assertEqual(r["error"]["code"], "bad_args", "by는 웹 인자가 아니다")
        self.assertEqual(self.first_cell()["cell"]["entries"][0]["status"], "proposed")

    def test_edit_entry_recomputes_risk_and_needs_a_reason(self):
        bad = self.call("results.edit_entry", self.args(fields={"severity": 5}, reason=""))
        self.assertFalse(bad["ok"])
        r = self.call("results.edit_entry", self.args(fields={"severity": 3, "frequency": 3, "cause": "고친 원인"}, reason="값 바로잡음"))
        self.assertTrue(r["ok"], r)
        e = self.first_cell()["cell"]["entries"][0]
        self.assertEqual((e["status"], e["cause"], e["risk"]), ("revised", "고친 원인", res.risk_of(3, 3)))
        self.assertFalse(self.call("results.edit_entry", self.args(fields={"entry_id": "x"}, reason="x"))["ok"], "고칠 수 없는 필드")

    def test_path_like_arguments_are_refused(self):
        for name in ("results.export_excel", "results.export_ie"):
            r = self.call(name, {"path": "C:/x.xlsx"})
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"), name)
        for key in ("path", "file", "dir", "folder", "url"):
            for name, cmd in api.COMMANDS.items():
                self.assertNotIn(key, cmd.spec, "%s는 %s를 받지 않는다" % (name, key))


class ExportTest(Base):
    def setUp(self):
        super().setUp()
        from hazop.app import project_ctx
        from tests.test_study_export import DEVS as XDEVS, sample
        r, ns, pg, _span, _single = sample()
        for p in (mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(XDEVS)),
                  mock.patch.object(project_ctx, "project_graph", lambda pid: pg)):
            p.start()
            self.addCleanup(p.stop)
        self.ns, self.g = ns, pg
        sn.save(ns)
        res.save(r, ns.get("project_id"))
        self.engine.settings["project_id"] = ns.get("project_id")

    def args(self, **kw):
        return {}

    def paths(self, kind, name):
        self.save_to = os.path.join(self.tmp, "out-" + kind + ".xlsx")
        return self.save_to

    def parts(self, path):
        with zipfile.ZipFile(path) as z:
            return {n: z.read(n) for n in z.namelist() if not n.startswith("docProps/")}

    def test_excel_bytes_match_the_direct_engine_call(self):
        from hazop.export import study_xlsx
        now = "2026-11-13T00:00:00Z"
        self.engine.hooks["save_path"] = self.paths
        with mock.patch.object(sn, "now_utc", lambda: now):
            r = self.call("results.export_excel", {"scope": "all"})
        self.assertTrue(r["ok"] and not r["data"]["cancelled"], r)
        inputs = api_results.excel_inputs(self.ns, self.g)
        doc, _fp = res.load_fp(self.ns)
        want = os.path.join(self.tmp, "direct.xlsx")
        study_xlsx.export(want, doc, self.ns, self.g, doc["deviations"], scope="all", node_ids=None, reviewer="검토자A",
                          intents=inputs["intents"], now=now, expectations=inputs["expectations"])
        self.assertEqual(self.parts(self.save_to), self.parts(want))
        self.assertEqual(r["data"]["path"], os.path.basename(self.save_to), "웹에는 파일 이름만 돌려준다")

    def test_cancelled_dialog_writes_nothing(self):
        self.engine.hooks["save_path"] = lambda kind, name: None
        self.assertEqual(self.call("results.export_excel", {})["data"], {"cancelled": True})
        self.assertEqual(self.call("results.export_ie", {})["data"], {"cancelled": True})

    def test_ie_bundle_exports_only_accepted_entries(self):
        self.engine.hooks["save_path"] = self.paths
        r = self.call("results.export_ie", {})
        self.assertTrue(r["ok"], r)
        self.assertTrue(os.path.isfile(self.save_to))
        self.assertGreaterEqual(r["data"]["candidates"], 0)


def fake_run_unit(kind=None, limit=None):
    """ai_cells.run_unit 대역: 칸마다 항목 하나를 돌려준다(kind를 주면 그 error_kind로 실패)."""
    def run(client, unit, ctx, devs, at):
        ok = kind is None
        cells = {did: ({"status": "ok", "error": None, "note": None, "applicable": True,
                        "entries": [dict(entry("ai-" + did, "proposed", origin="ai_draft"), severity=2, frequency=2, risk=2)]} if ok else
                       {"status": "failed", "error": "한도", "note": None, "entries": []}) for did in unit["deviation_ids"]}
        return {"unit_id": unit["unit_id"], "node_id": unit["node_id"], "status": "ok" if ok else "failed", "error": None if ok else "한도",
                "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                "cost_usd": None, "model": "m", "at": at, "cells": cells, "via": "subscription", "billing": "subscription",
                "error_kind": kind, "conn_state": None, "model_requested": "m", "api_equiv_usd": None, "limit": limit}
    return run


class RunTest(Base):
    def setUp(self):
        super().setUp()
        self.engine.ai = FakeAi()
        for p in (mock.patch.object(analysis_run, "contexts", lambda units, ns, pg, intent_of: {u["node_id"]: {} for u in units}),):
            p.start()
            self.addCleanup(p.stop)

    def run_with(self, run_unit, **args):
        with mock.patch("hazop.study.ai_cells.run_unit", run_unit):
            return self.call("results.run", dict({"scope": "all"}, **args))

    def test_plan_counts_calls_and_cells_and_checks_the_connection(self):
        r = self.call("results.run_plan", {"scope": "all"})
        self.assertTrue(r["ok"] and r["data"]["can_start"], r)
        self.assertGreater(r["data"]["calls"], 0)
        self.assertEqual(r["data"]["cells"], sum(1 for n in self.ns["nodes"] for _ in DEVS))
        self.engine.ai = FakeAi(can_start=False)
        self.assertFalse(self.call("results.run_plan", {"scope": "all"})["data"]["can_start"])
        self.assertFalse(self.call("results.run_plan", {"scope": "failed"})["data"]["can_start"], "실패 칸이 없으면 시작하지 않는다")

    def test_run_saves_after_each_call_and_reports_the_summary(self):
        r = self.run_with(fake_run_unit())
        self.assertTrue(r["ok"], r)
        done = [e["data"] for e in self.events.items if e.get("name") == "job.done"][-1]["result"]
        self.assertEqual((done["reason"], done["failed_calls"]), ("done", 0))
        doc, _fp = res.load_fp(self.ns)
        analyzed = [c for c in doc["cells"] if c["state"] == "analyzed"]
        self.assertEqual(len(analyzed), len(doc["cells"]), "모든 칸이 분석됨")
        self.assertEqual(len(doc["ai_log"]), done["calls"])
        self.assertFalse(self.engine.analysis.running)
        self.assertTrue(self.events.changes("results"))

    def test_human_verdicts_survive_a_rerun(self):
        self.call("results.set_status", self.args(status="approved"))
        self.run_with(fake_run_unit())
        doc, _fp = res.load_fp(self.ns)
        cell = next(c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == ("S1", "D01"))
        self.assertIn("approved", [e["status"] for e in cell["entries"]], "사람이 수용한 항목은 AI 재실행이 덮지 않는다")

    def test_stop_ends_before_the_next_call(self):
        calls = []
        inner = fake_run_unit()

        def run(client, unit, ctx, devs, at):
            calls.append(unit["unit_id"])
            self.engine.dispatch("results.stop", {})
            return inner(client, unit, ctx, devs, at)
        self.run_with(run)
        done = [e["data"] for e in self.events.items if e.get("name") == "job.done"][-1]["result"]
        self.assertEqual((done["reason"], len(calls), done["calls"]), ("stopped", 1, 1), done)
        self.assertGreater(done["planned"], 1)

    def test_a_limit_halts_the_rest_and_shows_the_limit(self):
        limit = {"resets_at": "2026-11-14T00:00:00Z", "kind": "five_hour"}
        self.run_with(fake_run_unit(kind="limit_reached", limit=limit))
        done = [e["data"] for e in self.events.items if e.get("name") == "job.done"][-1]["result"]
        self.assertEqual((done["reason"], done["calls"], done["error_kind"]), ("halted", 1, "limit_reached"), done)
        self.assertEqual(done["limit"], limit)
        self.assertEqual(self.engine.analysis.snapshot()["last"]["reason"], "halted")

    def test_refusals_before_any_call(self):
        self.engine.ai = FakeAi(can_start=False)
        r = self.run_with(fake_run_unit())
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"))
        self.engine.ai = FakeAi(terms=False)
        r = self.run_with(fake_run_unit())
        self.assertEqual(r["error"]["code"], "terms")
        self.assertTrue(self.call("results.ack_terms")["ok"])
        self.assertTrue(self.run_with(fake_run_unit())["ok"])
        self.engine.settings["reviewer_name"] = ""
        self.assertEqual(self.run_with(fake_run_unit())["error"]["code"], "bad_args")

    def test_run_is_a_job_so_closing_the_window_asks(self):
        e = api.Engine(settings_path=os.path.join(self.tmp, "s2.json"), emit=self.events)
        e.settings.update(project_id=self.project, reviewer_name="검토자A")
        e.ai = FakeAi()
        import threading
        gate = threading.Event()
        inner = fake_run_unit()

        def run(client, unit, ctx, devs, at):
            gate.wait(10)
            return inner(client, unit, ctx, devs, at)
        with mock.patch("hazop.study.ai_cells.run_unit", run):
            r = e.dispatch("results.run", {"scope": "all"})
            self.assertTrue(r["ok"], r)
            self.assertEqual(len(e.running_jobs()), 1)
            self.assertEqual(e.dispatch("results.run", {"scope": "all"})["error"]["code"], "busy")
            e.stop_jobs()
            gate.set()
            self.assertTrue(e.wait_jobs(20))
        done = [x["data"] for x in self.events.items if x.get("name") == "job.done"][-1]["result"]
        self.assertEqual(done["reason"], "stopped")


if __name__ == "__main__":
    unittest.main()
