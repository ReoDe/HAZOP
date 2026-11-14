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



class WorksheetDetailTest(ExportTest):
    """B3(INTENT §3.6 상세 워크시트 열): 설계 의도·원인(유형·위치)·결과(비완화·영향 대상)·보호수단(역할·작동·구현 대상)·AI 근거(경로·출처·⚠).
    고치기는 엔진 edit_entry 그대로(위험도는 엔진 계산), Excel에도 같은 열이 나간다."""

    def span(self):
        from tests.test_study_export import sample
        return sample()[3]

    def cell(self, node, dev):
        return self.read("results", "cell", node, dev)

    def test_cell_view_has_the_detail_columns(self):
        for n in self.g["nodes"]:          # 실제 프로젝트 그래프처럼 도면 안 ID(local_id)를 준다(도면 강조에 쓴다)
            if n.get("sheet") and n.get("source_object_id"):
                n.setdefault("local_id", n["source_object_id"])
        c = self.cell(self.span(), "D01")
        a2 = next(e for e in c["cell"]["entries"] if e["entry_id"] == "a2")["detail"]
        self.assertEqual(len(a2["basis"]["paths"]), 1)
        path = a2["basis"]["paths"][0]
        self.assertEqual(len(path["labels"]), 2)
        self.assertTrue(path["marks"] and set(path["marks"]) <= {s["graph_id"] for s in self.g["sheets"]}, "경로는 도면별 강조 표시로 간다")
        self.assertEqual(path["sheet"], next(iter(path["marks"])))
        self.assertEqual(a2["basis"]["sources"], [{"doc": "DOC-1", "where": "p.3", "material_id": None}])
        self.assertIn("없는 ID 참조", a2["basis"]["warnings"])
        self.assertTrue(c["targets"] and c["targets"][0]["in_node"], "참조 고르기는 이 구간 구성요소가 먼저")
        self.assertEqual((set(c["roles"]), set(c["actuations"])), ({"preventive", "mitigative", "unknown"},
                                                                    {"automatic", "operator", "passive", "unknown"}))
        self.assertEqual(a2["safeguards"][0]["text"], "보호수단 1")

    def test_source_document_points_at_the_docs_panel_material(self):
        from hazop.shell import api_docs
        with mock.patch.object(api_docs, "summary", lambda engine, pid=None: {"docs": [{"material_id": "MAT-7", "doc_number": "DOC-1"}]}):
            c = self.cell(self.span(), "D01")
        a2 = next(e for e in c["cell"]["entries"] if e["entry_id"] == "a2")["detail"]
        self.assertEqual(a2["basis"]["sources"][0]["material_id"], "MAT-7")

    def test_edit_safeguards_refs_and_basis_through_the_engine_and_excel(self):
        span = self.span()
        ns = sn.load(self.g)
        node = next(n for n in ns["nodes"] if n["node_id"] == span)
        node["design_intent"] = {"text": "급수를 증기발생기로 보낸다", "by": "user"}
        sn.save(ns)
        c = self.cell(span, "D01")
        self.assertEqual(c["intent"]["text"], "급수를 증기발생기로 보낸다")
        target = c["targets"][0]["ref"]
        fields = {"safeguards": [{"text": "안전밸브 개방", "role": "mitigative", "actuation": "passive",
                                  "refs": [{"ref": target, "origin": "human"}], "ipl": None, "origin": "human"}],
                  "cause_kind": "equipment", "consequence_basis": "unmitigated",
                  "cause_refs": [{"ref": target, "failure_mode": "FTO", "origin": "human"}]}
        r = self.call("results.edit_entry", {"node_id": span, "deviation_id": "D01", "entry_id": "a1", "fields": fields,
                                             "reason": "보호수단 역할 정리", "ver": c["ver"]})
        self.assertTrue(r["ok"], r)
        a1 = next(e for e in self.cell(span, "D01")["cell"]["entries"] if e["entry_id"] == "a1")
        d = a1["detail"]
        self.assertEqual((a1["status"], d["cause_kind"], d["consequence_basis"]), ("revised", "equipment", "unmitigated"))
        self.assertEqual((d["safeguards"][0]["role"], d["safeguards"][0]["actuation"], d["safeguards"][0]["draft"]), ("mitigative", "passive", False))
        self.assertEqual(d["safeguards"][0]["refs"][0]["label"], c["targets"][0]["label"])
        self.assertEqual(d["cause_refs"][0]["failure_mode"], "FTO")
        self.assertEqual(a1["risk"], res.risk_of(a1["severity"], a1["frequency"]), "위험도는 엔진이 센 값 그대로")
        stale = self.call("results.edit_entry", {"node_id": span, "deviation_id": "D01", "entry_id": "a1", "fields": {"cause_kind": "human"},
                                                 "reason": "x", "ver": c["ver"]})
        self.assertEqual((stale["ok"], stale["error"]["code"]), (False, "stale"), "화면이 본 판과 다르면 저장하지 않는다")
        import openpyxl
        from hazop.export import study_xlsx
        self.engine.hooks["save_path"] = self.paths
        self.assertTrue(self.call("results.export_excel", {"scope": "all"})["ok"])
        ws = openpyxl.load_workbook(self.save_to)[study_xlsx.SHEETS[2]]
        head = [x.value for x in ws[1]]
        rows = [dict(zip(head, [x.value for x in row])) for row in ws.iter_rows(min_row=2)]
        row = next(x for x in rows if x["원인"] and "원인 a1" in x["원인"])
        self.assertIn("설계 의도", head)
        self.assertEqual(row["설계 의도"], "급수를 증기발생기로 보낸다")
        self.assertIn("[자체작동] 안전밸브 개방", row["보호수단"])
        self.assertEqual(row["결과 기준"], "비완화")
        self.assertIn(c["targets"][0]["label"].split(" ")[0], row["그래프 참조"])


class TraceTest(Base):
    """구성요소 -> 소속 구간 -> 칸 -> 권고(INTENT §3.6): 태그·ID·도면에서 누른 구성요소(sheet+local) 어느 쪽으로 시작해도 같은 길이 나온다."""

    def setUp(self):
        super().setUp()
        from hazop.app import project_ctx
        from tests.test_study_export import DEVS as XDEVS, sample
        r, ns, pg, self.span, self.single = sample()
        for p in (mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(XDEVS)),
                  mock.patch.object(project_ctx, "project_graph", lambda pid: pg)):
            p.start()
            self.addCleanup(p.stop)
        self.ns, self.g = ns, pg
        sn.save(ns)
        res.save(r, ns.get("project_id"))
        self.engine.settings["project_id"] = ns.get("project_id")
        # 이 표본 그래프에는 도면 local_id가 없어 대응표를 대신 꽂는다(local_id = "L-" + 프로젝트 ID, 도면 = 구성요소가 놓인 도면)
        self.back = {(n.get("sheet") or "sheet-1", "L-" + n["entity_id"]): n["entity_id"] for n in pg["nodes"] if n.get("entity_id")}
        p = mock.patch("hazop.chat.view._locals", lambda graph: ({}, self.back))
        p.start()
        self.addCleanup(p.stop)

    def pick(self):
        """첫 구간의 구성요소 하나: (프로젝트 ID, 태그, 도면, local_id)."""
        node = next(n for n in self.ns["nodes"] if n["node_id"] == self.span)
        by_entity = {v: k for k, v in self.back.items()}
        for m in node["members"]:
            if m in by_entity:
                tag = next((n.get("tag") for n in self.g["nodes"] if n.get("entity_id") == m), None)
                return m, tag, by_entity[m][0], by_entity[m][1]
        self.fail("구간의 구성요소가 대응표에 없음")

    def test_entity_tag_and_sheet_local_reach_the_same_node_and_recommendations(self):
        ent, tag, sheet, local = self.pick()
        by_id = self.read("results", "trace", entity=ent)
        self.assertIn(self.span, [n["node_id"] for n in by_id["nodes"]], by_id)
        self.assertTrue(any(c["recs"] for n in by_id["nodes"] for c in n["cells"]), "권고까지 이어진다")
        by_local = self.read("results", "trace", sheet=sheet, local=local)
        self.assertEqual([n["node_id"] for n in by_local["nodes"]], [n["node_id"] for n in by_id["nodes"]])
        if tag:
            by_tag = self.read("results", "trace", entity=tag.lower())
            self.assertIn(self.span, [n["node_id"] for n in by_tag["nodes"]], "태그(대소문자 무관)로도 찾는다")
            self.assertEqual(by_local["entity"], tag)

    def test_unknown_component_and_excluded_node_give_no_nodes(self):
        self.assertEqual(self.read("results", "trace", entity="없는-태그")["nodes"], [])
        ent, _tag, _sheet, _local = self.pick()
        ns = sn.load(self.g)
        for n in ns["nodes"]:
            if n["node_id"] == self.span:
                n["screen"] = {"status": "excluded"}
        sn.save(ns)
        self.assertEqual(self.read("results", "trace", entity=ent)["nodes"], [], "스크리닝 제외 구간은 분석 범위가 아니다")


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

    def test_each_call_sends_only_the_changed_cells_not_the_whole_matrix(self):
        import json as _json
        self.run_with(fake_run_unit())
        done = [e["data"] for e in self.events.items if e.get("name") == "job.done"][-1]["result"]
        deltas = [e["data"] for e in self.events.items if e.get("name") == "results.cells"]
        self.assertEqual(len(deltas), done["calls"], "호출마다 바뀐 칸만 알린다")
        for d in deltas:
            self.assertLess(len(_json.dumps(d, ensure_ascii=False)), 4000, "알림은 작다")
            self.assertTrue(d["ver"].startswith("sha256:") and d["kpi"]["cells"] > 0)
            for cell in d["cells"].values():
                self.assertEqual(set(cell), {"state", "scenarios", "max_risk", "unreviewed"})
        self.assertEqual(len(self.events.changes("results")), 1, "행렬 전체를 다시 읽게 하는 알림은 끝에 한 번만")
        last = deltas[-1]
        full = self.read("results")
        self.assertEqual(full["ver"], last["ver"], "마지막 알림의 판 지문이 지금 파일의 것과 같다")
        self.assertEqual(full["kpi"], last["kpi"])
        for did, cell in last["cells"].items():
            self.assertEqual(full["matrix"][last["node_id"]][did], cell)
        self.assertIn("run", self.read("results", "run") and ["run"])

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



class RunConnTest(RunTest):
    """A8 검토 R1: 실행 카드는 실제로 쓸 연결(방식·모델·요금)을 보이고, 실행은 카드가 본 연결(conn_ver)과 지금 연결이 같을 때만 돈다."""

    CONN = {"kind": "analysis", "via": "api", "method_name": "API 키(과금)", "model": "m", "model_name": "모델 M", "can_start": True,
            "label": "정상", "guide": "", "paid": True, "usd": 0.4, "cost_text": "예상 요금 약 $0.40", "conn_ver": "cv-1"}

    def setUp(self):
        super().setUp()
        self.engine.ai.conn = object()      # 연결 설정이 있는 엔진(실제 앱)처럼
        from hazop.shell import api_settings
        self.api_settings = api_settings
        for p in (mock.patch.object(api_settings, "run_conn", lambda engine, kind, calls=0, sections=0: dict(self.CONN, calls=calls)),):
            p.start()
            self.addCleanup(p.stop)

    def test_plan_shows_the_connection_that_will_actually_be_used(self):
        r = self.call("results.run_plan", {"scope": "all"})
        self.assertTrue(r["ok"], r)
        conn = r["data"]["conn"]
        self.assertEqual((conn["method_name"], conn["paid"], conn["conn_ver"]), ("API 키(과금)", True, "cv-1"))
        self.assertEqual(conn["calls"], r["data"]["calls"])
        with mock.patch.object(self.api_settings, "run_conn", lambda engine, kind, calls=0, sections=0: dict(self.CONN, can_start=False, label="키 없음")):
            r2 = self.call("results.run_plan", {"scope": "all"})
        self.assertEqual((r2["data"]["can_start"], r2["data"]["state"]), (False, "키 없음"), "시작 가능 여부도 그 연결로 정한다")

    def test_a_changed_connection_is_refused_before_any_call(self):
        def changed(engine, kind, ver):
            raise self.api_settings.Refused("conn_changed", "AI 연결이 화면에 보인 것과 달라졌습니다")
        calls = []
        with mock.patch.object(self.api_settings, "same_conn", changed):
            r = self.run_with(lambda *x: calls.append(x), conn_ver="cv-old")
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "conn_changed"))
        self.assertEqual(calls, [], "AI를 부르지 않는다")
        self.assertFalse(self.engine.analysis.running)
        with mock.patch.object(self.api_settings, "same_conn", lambda engine, kind, ver: self.CONN):
            r = self.run_with(fake_run_unit(), conn_ver="cv-1")
        self.assertTrue(r["ok"], r)


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


class ReasonAndGuidewordTest(Base):
    """A9 ① 행렬 칸: '적용 불가'와 '아직 분석 안 함'을 가르고 이유를 준다. ③ 가이드워드 옆 영문."""

    def mark(self, node, dev, **cell):
        doc, _fp = res.load_fp(self.ns)
        c = next(c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == (node, dev))
        c.update(cell)
        res.save_fp(doc, self.project, expect=store_io.ANY)

    def test_not_applicable_cell_carries_its_reason_and_kind(self):
        ok = {"status": "ok", "error": None, "at": "2026-11-13T00:00:00Z", "model": "m", "note": "이 구간에는 배관이 없어 흐름이 없을 수 없다", "applicable": False}
        self.mark("S2", "D01", state="analyzed", entries=[], ai_run=ok)
        cell = self.read("results")["matrix"]["S2"]["D01"]
        self.assertEqual((cell["kind"], cell["reason"]), ("not_applicable", ok["note"]))
        self.assertEqual(cell["scenarios"], 0)

    def test_not_analyzed_has_no_kind_and_is_told_apart_from_not_applicable(self):
        m = self.read("results")["matrix"]
        self.assertEqual(m["S2"]["D01"]["state"], "not_analyzed")
        self.assertNotIn("kind", m["S2"]["D01"])
        self.assertNotIn("kind", m["S1"]["D01"])      # 항목이 있는 칸

    def test_analyzed_without_scenarios_and_failed_and_excluded_cells_each_have_their_kind(self):
        ok = {"status": "ok", "error": None, "at": "t", "model": "m", "note": "시나리오가 없다", "applicable": True}
        self.mark("S2", "D01", state="analyzed", entries=[], ai_run=ok)
        self.mark("S2", "D02", ai_run=dict(ok, status="failed", error="AI 호출 중 오류(Timeout)", note=None))
        self.mark("S1", "D02", state="excluded", entries=[], ai_run=dict(ok, note="사람이 뺐다"))
        m = self.read("results")["matrix"]
        self.assertEqual((m["S2"]["D01"]["kind"], m["S2"]["D01"]["reason"]), ("no_scenario", "시나리오가 없다"))
        self.assertEqual((m["S2"]["D02"]["kind"], m["S2"]["D02"]["reason"]), ("failed", "AI 호출 중 오류(Timeout)"))
        self.assertEqual(m["S1"]["D02"]["kind"], "excluded")

    def test_excluded_and_failed_cell_shows_both(self):
        """재현 A3: 제외이면서 실패한 칸은 '제외'를 앞에 두고 실패도 함께 알린다."""
        self.mark("S2", "D01", state="excluded", entries=[], ai_run={"status": "failed", "error": "Timeout", "note": None})
        c = self.read("results")["matrix"]["S2"]["D01"]
        self.assertEqual((c["kind"], c["also"]), ("excluded", ["failed"]))
        self.assertIn("Timeout", c["reason"])

    def test_moved_cell_reads_the_old_verdict_from_legacy_cells(self):
        """재현 A4: 옛 ID 이전으로 ai_run 없이 '분석함·항목 없음'이 된 칸은 legacy_cells의 옛 판정과 이유를 보인다."""
        self.mark("S2", "D01", state="analyzed", entries=[],
                  legacy_cells=[{"from": "OLD", "state": "analyzed", "ai_run": {"status": "ok", "applicable": False, "note": "no pipe"}}])
        c = self.read("results")["matrix"]["S2"]["D01"]
        self.assertEqual(c["kind"], "not_applicable")
        self.assertIn("no pipe", c["reason"])
        self.assertIn("OLD", c["reason"], "옛 구간에서 온 판정이라고 적는다")

    def test_analyzed_empty_without_any_record_says_no_record(self):
        self.mark("S2", "D01", state="analyzed", entries=[])
        c = self.read("results")["matrix"]["S2"]["D01"]
        self.assertEqual(c["kind"], "no_record")
        self.assertIn("이유 기록 없음", c["reason"])

    def test_rejected_only_cell_is_counted_for_export(self):
        self.mark("S2", "D01", state="analyzed", entries=[entry("r1", "rejected")])
        c = self.read("results")["matrix"]["S2"]["D01"]
        self.assertEqual((c["scenarios"], c["rejected"]), (0, 1))

    def test_a_blank_reason_still_says_something(self):
        ok = {"status": "ok", "error": None, "at": "t", "model": "m", "note": None, "applicable": False}
        self.mark("S2", "D01", state="analyzed", entries=[], ai_run=ok)
        self.assertTrue(self.read("results")["matrix"]["S2"]["D01"]["reason"])

    def test_delta_after_a_call_has_the_same_kind_and_reason(self):
        ok = {"status": "ok", "error": None, "at": "t", "model": "m", "note": "해당 없음 이유", "applicable": False}
        self.mark("S2", "D01", state="analyzed", entries=[], ai_run=ok)
        doc, fp = res.load_fp(self.ns)
        d = api_results.cells_delta(doc, {"node_id": "S2", "cells": ["D01"]}, fp)
        self.assertEqual((d["cells"]["D01"]["kind"], d["cells"]["D01"]["reason"]), ("not_applicable", "해당 없음 이유"))

    def test_deviation_headers_carry_the_english_guideword_by_item_id(self):
        en = {"I1": {"guideword_en": "No", "label_en": "No flow"}}
        with mock.patch.object(api_results, "deviation_names_en", lambda: en):
            s = self.read("results")
            c = self.read("results", "cell", "S1", "D01")
        d1, d2 = s["deviations"][0], s["deviations"][1]
        self.assertEqual((d1["guideword_en"], d1["label_en"]), ("No", "No flow"))
        self.assertEqual((d2["guideword_en"], d2["label_en"]), ("", ""))     # 표에 없으면 빈 글자(화면이 한국어만 보인다)
        self.assertEqual(c["deviation"]["guideword_en"], "No")

    def test_english_comes_only_from_the_kosha_table_and_is_never_invented(self):
        """표(deviation_en·guide_word_en)에 출처와 함께 적힌 영문만 보인다. 비어 있는 항목은 빈 글자로 둔다(번역을 지어 넣지 않음)."""
        import json
        from hazop import paths
        with open(paths.folder("deviations", res.DEVIATION_CHART), encoding="utf-8") as fh:
            items = json.load(fh)["items"]
        en = api_results.deviation_names_en()
        self.assertEqual(set(en), {i["item_id"] for i in items})
        for i in items:
            self.assertEqual(en[i["item_id"]], {"guideword_en": (i.get("guide_word_en") or "").strip(),
                                               "label_en": (i.get("deviation_en") or "").strip()}, i["item_id"])
        self.assertEqual(en["p86-d01"], {"guideword_en": "More", "label_en": "More flow"})
        self.assertGreaterEqual(sum(1 for n in en.values() if n["guideword_en"]), 40)


class ExportScopeTest(ExportTest):
    """A9 ② Excel 범위: 승인 항목만, 고른 구간만. 덮어쓰기 확인은 창(window._save_path)이 한다(tests/test_shell_web.py)."""

    def sheet_rows(self, path):
        import openpyxl
        from hazop.export import study_xlsx
        ws = openpyxl.load_workbook(path)[study_xlsx.SHEETS[2]]
        head = [c.value for c in ws[1]]
        return [dict(zip(head, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]

    def export(self, **a):
        self.engine.hooks["save_path"] = self.paths
        r = self.call("results.export_excel", a)
        self.assertTrue(r["ok"] and not r["data"]["cancelled"], r)
        return r["data"], self.sheet_rows(self.save_to)

    def test_approved_scope_has_only_approved_entries_and_no_cell_rows(self):
        data, rows = self.export(scope="approved")
        self.assertEqual(data["rows"], len(rows))
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual({r["상태"] for r in rows}, {"승인"})
        _d, full = self.export(scope="all")
        self.assertGreater(len(full), len(rows))

    def test_nodes_scope_has_only_the_chosen_nodes_and_needs_a_choice(self):
        scope = api_results.scope_rows(sn.load(self.g))
        pick = scope[0]["node_id"]
        data, rows = self.export(scope="nodes", node_ids=[pick])
        self.assertEqual(data["rows"], len(rows))
        self.assertTrue(rows)
        names = {r["구간"] for r in rows}
        self.assertEqual(len(names), 1, names)
        _d, full = self.export(scope="all")
        self.assertLess(len(rows), len(full))
        self.engine.hooks["save_path"] = self.paths
        r = self.call("results.export_excel", {"scope": "nodes"})
        self.assertFalse(r["ok"], "구간을 고르지 않으면 내보내지 않는다")

    def test_nodes_outside_the_screens_scope_are_refused(self):
        """재현 A2: 행렬에 없는 구간(스크리닝 제외)을 직접 명령으로 보내면 거절한다(빈 파일을 쓰지 않는다)."""
        gone = self.exclude_last_node()
        self.engine.hooks["save_path"] = self.paths
        self.save_to = None
        r = self.call("results.export_excel", {"scope": "nodes", "node_ids": [gone]})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"), r)
        self.assertIn(gone, r["error"]["message"])
        self.assertIsNone(self.save_to, "거절할 때는 저장 대화상자도 열지 않는다")

    def summary_sheet(self):
        import openpyxl
        from hazop.export import study_xlsx
        ws = openpyxl.load_workbook(self.save_to)[study_xlsx.SHEETS[0]]
        return {r[0].value: r[1].value for r in ws.iter_rows() if r[0].value}

    def test_approved_scope_cover_counts_only_what_was_exported(self):
        """재현 A1: '승인 항목만'이면 표지 수치도 승인 항목만 센다(워크시트 1행인데 표지가 시나리오 4·기각 1이던 것)."""
        _d, rows = self.export(scope="approved")
        s = self.summary_sheet()
        self.assertEqual(s["내보낸 범위"], "승인 항목만")
        self.assertEqual(s["시나리오 수"], len(rows))
        self.assertEqual((s["상태별: 승인"], s["상태별: 기각"], s["상태별: 제안"], s["상태별: 수정"], s["상태별: 보류"]), (len(rows), 0, 0, 0, 0))
        self.assertEqual(s["미검토 시나리오"], 0)

    def test_nodes_scope_cover_names_the_chosen_nodes(self):
        pick = api_results.scope_rows(sn.load(self.g))[0]["node_id"]
        self.export(scope="nodes", node_ids=[pick])
        s = self.summary_sheet()
        self.assertEqual(s["내보낸 범위"], "고른 구간: " + pick)
        self.assertEqual(s["구간 수"], 1)

    def test_excel_guideword_column_has_the_english_and_cell_rows_use_the_screen_names(self):
        en = {"i1": {"guideword_en": "No, Not, or None", "label_en": ""}, "i2": {"guideword_en": "More", "label_en": "More pressure"}}
        from hazop.export import study_xlsx
        with mock.patch.object(study_xlsx, "deviation_names_en", lambda: en):
            _d, rows = self.export(scope="all")
        self.assertEqual({r["가이드워드"] for r in rows if r["편차"] == "흐름 없음"}, {"없음 (No, Not, or None)"})
        self.assertEqual({r["가이드워드"] for r in rows if r["편차"] == "압력 높음"}, {"높음 (More)"})
        self.assertEqual(study_xlsx.guideword_text({"item_id": "i3", "guideword": "높음"}, en), "높음", "표에 영문이 없으면 한국어만")
        na = [r for r in rows if r["상태"] == "해당 없음(AI 판단)"]
        self.assertTrue(na and "흐름 없음" in (na[0]["AI 근거(KG 경로·출처 문서)"] or ""))
        m = self.read("results")["matrix"]
        labels = {c.get("label") for row in m.values() for c in row.values() if c.get("kind")}
        self.assertTrue(labels <= set(study_xlsx.CELL_ROW_LABELS.values()), labels)

    def test_unknown_scope_is_refused(self):
        self.engine.hooks["save_path"] = self.paths
        self.assertFalse(self.call("results.export_excel", {"scope": "everything"})["ok"])
