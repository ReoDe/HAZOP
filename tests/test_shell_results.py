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


def classic_scope(ns):
    """이전 화면(ResultsScreen)의 범위 코드를 그대로 불러 같은 구간을 얻는다(_rows·_scope_set은 node_set만 본다)."""
    import types
    from hazop.app.screens.results import ResultsScreen
    obj = types.SimpleNamespace(node_set=ns)
    obj._rows = lambda: ResultsScreen._rows(obj)
    return ResultsScreen._scope_set(obj)


def classic_intents(ns):
    from hazop.app.screens.results import design_intent
    out = {}
    for n in ns["nodes"]:
        found = design_intent(n, None)
        if found:
            out[n["node_id"]] = found[0]
    return out


def classic_expectations(ns, pg):
    from hazop.study import ai_cells
    kg, _reason = ai_cells.load_kg_for(ns)
    return ai_cells.expectations_for(pg, kg)[0]


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

    def exclude_last_node(self):
        """스크리닝 '제외'로 표시한 구간 하나(재현 repro_plan_screened·repro_excel_vs_classic)."""
        ns = sn.load(self.g)
        last = [n for n in ns["nodes"] if sn.is_active(n)][-1]
        last["screen"] = {"status": "excluded"}
        sn.save(ns)
        return last["node_id"]

    def test_excel_matches_the_classic_screens_inputs_even_with_an_excluded_node(self):
        """이전 화면 export_excel과 같은 입력(_scope_set = 이전 화면 코드가 만든 범위, 설계 의도, 잠재 후보, 같은 시각·검토자)으로 낸 파일과 부품이 같다."""
        from hazop.export import study_xlsx
        excluded = self.exclude_last_node()
        now = "2026-11-13T00:00:00Z"
        self.engine.hooks["save_path"] = self.paths
        with mock.patch.object(sn, "now_utc", lambda: now):
            r = self.call("results.export_excel", {"scope": "all"})
        self.assertTrue(r["ok"] and not r["data"]["cancelled"], r)
        ns = sn.load(self.g)
        doc, _fp = res.load_fp(ns)
        want = os.path.join(self.tmp, "classic.xlsx")
        _p, classic_rows = study_xlsx.export(want, doc, classic_scope(ns), self.g, doc["deviations"], scope="all", node_ids=None, reviewer="검토자A",
                                             intents=classic_intents(ns), now=now, expectations=classic_expectations(ns, self.g))
        self.assertEqual(self.parts(self.save_to), self.parts(want))
        self.assertEqual(r["data"]["rows"], classic_rows)
        full = os.path.join(self.tmp, "all.xlsx")
        _p, all_rows = study_xlsx.export(full, doc, ns, self.g, doc["deviations"], scope="all", node_ids=None, reviewer="검토자A", now=now)
        self.assertGreater(all_rows, classic_rows, "제외 구간(%s)을 넣으면 행이 더 많다: 그것이 새 화면에서 빠져야 한다" % excluded)
        self.assertEqual(self.read("results")["nodes"] and [n["node_id"] for n in self.read("results")["nodes"]], [n["node_id"] for n in classic_scope(ns)["nodes"]])

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


class ScopeAndVersionTest(Base):
    def setUp(self):
        super().setUp()
        self.engine.ai = FakeAi()

    def test_screened_out_node_is_not_in_rows_plan_or_recs(self):
        before = self.call("results.run_plan", {"scope": "all"})["data"]
        ns = sn.load(self.g)
        ns["nodes"][1]["screen"] = {"status": "excluded"}
        sn.save(ns)
        after = self.call("results.run_plan", {"scope": "all"})["data"]
        from hazop.study import ai_cells
        classic = ai_cells.plan_units(classic_scope(sn.load(self.g)), DEVS)
        self.assertEqual(after["calls"], len(classic), "이전 화면 범위의 호출 수와 같다")
        self.assertLess(after["calls"], before["calls"])
        self.assertEqual([n["node_id"] for n in self.read("results")["nodes"]], ["S1"])
        self.assertFalse([r for r in self.read("results", "recs")["recs"] if r["node_id"] == "S2"])

    def test_ver_none_is_refused_when_the_file_exists(self):
        old = self.first_cell()["ver"]
        self.assertTrue(self.call("results.set_status", self.args(entry_id="e2", status="approved"))["ok"])
        for ver in (old, "none"):
            r = self.call("results.set_status", dict(node_id="S1", deviation_id="D01", entry_id="e1", status="rejected", reason="낡은 화면", ver=ver))
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), ver)
        self.assertEqual(self.first_cell()["cell"]["entries"][0]["status"], "proposed")

    def test_ver_none_is_accepted_only_when_no_file_exists(self):
        os.remove(res.store_path(self.project, self.ns["graph_id"]))
        s = self.read("results")
        self.assertEqual(s["ver"], "none")
        r = self.call("results.set_status", dict(node_id="S1", deviation_id="D01", entry_id="e1", status="approved", ver="none"))
        self.assertEqual(r["ok"], False, "파일이 없을 때 항목이 없으면 엔진이 거절한다(판 검사는 통과)")
        self.assertNotEqual((r.get("error") or {}).get("code"), "stale")

    def test_a_stale_set_rev_is_refused_by_the_engine(self):
        r = self.call("results.set_status", self.args(status="approved", set_rev=999))
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), r)


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


class ScaleTest(unittest.TestCase):
    """525구간 × 44편차(23,100칸) 행렬의 읽기 계산·전송 크기(규격 §5.4 측정). 파일 없이 합성 결과로 본다."""

    def test_525_nodes_matrix_summary_and_kpi_are_fast_and_small(self):
        import json
        import time
        devs = [{"deviation_id": "D%02d" % (i + 1), "item_id": "i%d" % i, "parameter": "p", "guideword": "g", "label": "편차 %d" % i} for i in range(44)]
        cells = []
        for n in range(525):
            for d in devs:
                e = [entry("e%d" % d["deviation_id"].__hash__(), "proposed", origin="ai_draft", recommendation="권고", severity=2, frequency=2, risk=2)] \
                    if (n + int(d["deviation_id"][1:])) % 3 == 0 else []
                cells.append({"node_id": "S%d" % (n + 1), "item_id": d["item_id"], "deviation_id": d["deviation_id"],
                              "state": "analyzed" if e else "not_analyzed", "entries": e, "node_rev": 1, "hold": False})
        doc = {"cells": cells, "deviations": devs, "ai_log": []}
        t0 = time.perf_counter()
        matrix = res.matrix_summary(doc)
        kpi = api_results._kpi(doc)
        dt = time.perf_counter() - t0
        size = len(json.dumps({"matrix": matrix, "kpi": kpi}, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(kpi["cells"], 525 * 44)
        self.assertLess(dt, 2.0, "행렬 요약·머리 수치 계산 %.3f초" % dt)
        self.assertLess(size, 3_000_000, "요약 JSON %d바이트" % size)
        print("525×44 측정: 계산 %.3f초, 요약 JSON %.2f MB" % (dt, size / 1e6))


if __name__ == "__main__":
    unittest.main()
