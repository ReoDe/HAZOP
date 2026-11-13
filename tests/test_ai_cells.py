"""④→⑤ AI 칸 채우기 엔진(hazop.study.ai_cells)과 결과 저장·검토(hazop.study.results) 시험.
가짜 클라이언트만 쓴다(네트워크 없음). 파일은 임시 HAZOP_WORK_ROOT 아래에만 쓴다."""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_kg_context as chk  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.kg import build  # noqa: E402
from hazop.study import ai_cells as ac  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as sr  # noqa: E402

AT = "2026-11-07T00:00:00Z"
AT2 = "2026-11-07T01:00:00Z"
SECRET = "sk-ant-api03-SECRET-should-never-appear"
USAGE = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 3000,
         "cache_creation_input_tokens": 500}


def scenario(**kw):
    s = {"cause": "원인", "consequence": "결과", "safeguards": ["보호"], "recommendation": "권고",
         "severity": 3, "frequency": 2, "equipment_tags": [], "kg_paths": [], "sources": []}
    s.update(kw)
    return s


def answer(did, scenarios=None, applicable=True, note=""):
    return {"deviation_id": did, "applicable": applicable, "note": note,
            "scenarios": [scenario()] if scenarios is None else scenarios}


class FakeClient:
    """analyze(request)가 respond(request)를 돌려준다. 받은 요청을 기록한다."""

    def __init__(self, respond):
        self.respond = respond
        self.requests = []

    def analyze(self, request):
        self.requests.append(request)
        return self.respond(request)


def completed(answers):
    return lambda _req: {"status": "completed", "output": {"deviations": answers}, "usage": dict(USAGE),
                         "model": "claude-opus-5-5", "error_type": None, "status_code": 200, "error": None}


def asked_ids(request):
    return [d["deviation_id"] for d in json.loads(request["user"].split("\n", 1)[1])]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = chk.sample_graph()
        cls.kg = build.build_kg(chk.sample_knowledge(), [cls.graph])
        cls.devs = sr.load_deviations()
        cls.node_set = sn.confirm(sn.propose(cls.graph, at=AT), cls.graph, "김검토", at=AT)
        nid = sn.nodes_of(cls.node_set, "entity-node-001")[0]
        cls.node = next(n for n in cls.node_set["nodes"] if n["node_id"] == nid)
        cls.doc_id = next(n for n in cls.kg["nodes"] if n["node_type"] == "document")["source"]["document_id"]

    def ctx(self, kg="default"):
        return ac.node_context(self.node, self.graph, self.kg if kg == "default" else kg)

    def unit(self, *dids):
        return {"unit_id": "u", "node_id": self.node["node_id"], "deviation_ids": list(dids)}


class PlanTest(Base):
    def test_units_group_deviations_by_parameter_in_file_order(self):
        units = ac.plan_units(self.node_set, self.devs)
        params = list(dict.fromkeys(d["parameter"] for d in self.devs))
        self.assertEqual(len(units), len(self.node_set["nodes"]) * len(params))
        first = units[:len(params)]
        self.assertTrue(all(u["node_id"] == self.node_set["nodes"][0]["node_id"] for u in first))
        self.assertEqual([d for u in first for d in u["deviation_ids"]], [d["deviation_id"] for d in self.devs])
        by_id = {d["deviation_id"]: d["parameter"] for d in self.devs}
        for u in units:
            self.assertEqual(len({by_id[d] for d in u["deviation_ids"]}), 1, u)
        self.assertEqual(len({u["unit_id"] for u in units}), len(units))

    def test_retry_cells_become_single_cell_units(self):
        units = ac.plan_units(self.node_set, self.devs, cells=[("S1", "D03"), ("S2", "D10")])
        self.assertEqual([(u["node_id"], u["deviation_ids"]) for u in units], [("S1", ["D03"]), ("S2", ["D10"])])


class RequestTest(Base):
    def test_same_node_gives_same_context_bytes(self):
        a = ac.build_request(self.unit("D01", "D02"), self.ctx(), self.devs)
        b = ac.build_request(self.unit("D09"), self.ctx(), self.devs)
        self.assertEqual(a["context"].encode("utf-8"), b["context"].encode("utf-8"))
        self.assertNotEqual(a["user"], b["user"])
        self.assertEqual(asked_ids(a), ["D01", "D02"])
        self.assertEqual(set(a), {"system", "context", "user", "schema"})
        self.assertIs(a["schema"], ac.RESPONSE_SCHEMA)

    def test_context_carries_members_knowledge_and_no_secret(self):
        os.environ["ANTHROPIC_API_KEY_TEST_ONLY"] = SECRET
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY_TEST_ONLY", None)
        req = ac.build_request(self.unit("D01"), self.ctx(), self.devs)
        text = json.dumps(req, ensure_ascii=False)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("api_key", text.lower())
        prompt = json.loads(req["context"].split("\n", 1)[1])
        self.assertEqual([c["entity_id"] for c in prompt["components"]], sorted(self.node["members"]))
        self.assertIn("req-001", [it["knowledge_id"] for it in prompt["knowledge"]["items"]])
        self.assertNotIn("allowed", prompt)

    def test_without_kg_context_says_so(self):
        ctx = self.ctx(kg=None)
        self.assertIsNone(ctx["prompt"]["knowledge"])
        self.assertEqual(ctx["kg_note"], ac.NO_KG_NOTE)
        self.assertEqual(ctx["allowed"]["kg_ids"], set())

    def test_kg_for_other_graph_version_is_not_used(self):
        other = dict(self.graph, graph_version="v-other")
        ctx = ac.node_context(self.node, other, self.kg)
        self.assertIsNone(ctx["prompt"]["knowledge"])
        self.assertIn("지식그래프를 쓰지 않음", ctx["kg_note"])


class RunUnitTest(Base):
    def run_with(self, respond, *dids):
        return ac.run_unit(FakeClient(respond), self.unit(*dids), self.ctx(), self.devs, AT)

    def test_ok_builds_draft_entries_with_risk_and_cost(self):
        r = self.run_with(completed([answer("D01", [scenario(), scenario(severity=None)]), answer("D02")]),
                          "D01", "D02")
        self.assertEqual((r["status"], r["error"], r["at"], r["model"]), ("ok", None, AT, "claude-opus-5-5"))
        self.assertEqual(r["usage"], USAGE)
        self.assertGreater(r["cost_usd"], 0)
        e1, e2 = r["cells"]["D01"]["entries"]
        self.assertEqual((e1["origin"], e1["status"], e1["risk"], e2["risk"]), ("ai_draft", "proposed", 4, None))
        self.assertEqual(set(e1["ai_basis"]), {"kg_paths", "sources", "equipment_tags", "warnings"})
        self.assertNotEqual(e1["entry_id"], e2["entry_id"])

    def test_missing_deviation_fails_only_that_cell(self):
        r = self.run_with(completed([answer("D01")]), "D01", "D02")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["cells"]["D01"]["status"], "ok")
        self.assertEqual((r["cells"]["D02"]["status"], r["cells"]["D02"]["error"]), ("failed", ac.MISSING_DEVIATION))

    def test_not_applicable_is_ok_with_note_and_no_entries(self):
        r = self.run_with(completed([answer("D01", [scenario()], applicable=False, note="해당 변수 없음")]), "D01")
        self.assertEqual(r["cells"]["D01"], {"status": "ok", "error": None, "note": "해당 변수 없음", "entries": [],
                                             "applicable": False})
        r = self.run_with(completed([answer("D01", [], applicable=True)]), "D01")
        self.assertIs(r["cells"]["D01"]["applicable"], True, "해당하나 시나리오 없음은 따로 구분")

    def test_refused_and_api_error_fail_every_cell(self):
        for status, error in (("refused", None), ("api_error", "AI 서버 오류(500)")):
            r = self.run_with(lambda _req: {"status": status, "output": None, "usage": None, "model": None,
                                            "error": error}, "D01", "D02")
            self.assertEqual(r["status"], "failed", status)
            self.assertEqual(r["error"], error or ac.STATUS_ERRORS["refused"])
            self.assertEqual({c["status"] for c in r["cells"].values()}, {"failed"})
            self.assertEqual(r["cost_usd"], 0)

    def test_parse_error_and_bad_shape_fail(self):
        r = self.run_with(lambda _req: {"status": "parse_error", "error": "JSON 파싱 실패"}, "D01")
        self.assertEqual((r["status"], r["error"]), ("failed", "JSON 파싱 실패"))
        r = self.run_with(lambda _req: {"status": "completed", "output": {"rows": []}}, "D01")
        self.assertEqual((r["status"], r["error"]), ("failed", ac.BAD_RESPONSE))
        r = self.run_with(completed([answer("D01", [scenario(severity=9)])]), "D01")
        self.assertEqual((r["status"], r["cells"]["D01"]["error"]), ("ok", ac.BAD_RESPONSE))

    def test_client_exception_does_not_escape(self):
        def boom(_req):
            raise RuntimeError(SECRET)
        r = self.run_with(boom, "D01")
        self.assertEqual(r["status"], "failed")
        self.assertNotIn(SECRET, json.dumps(r, ensure_ascii=False))


class EvidenceTest(Base):
    def test_valid_evidence_has_no_warning(self):
        s = scenario(equipment_tags=["RC-PZ01"],
                     kg_paths=[["entity-node-001", "req-001", "chunk-001"], ["entity-seg-002", "entity-node-001"]],
                     sources=[{"doc": self.doc_id, "where": "3쪽"}])
        self.assertEqual(ac.check_evidence(s, self.ctx()), [])

    def test_each_kind_of_bad_evidence_is_flagged(self):
        s = scenario(equipment_tags=["RC-PZ01", "XX-999"],
                     kg_paths=[["entity-node-001", "entity-node-999"], ["entity-node-001", "entity-node-012"]],
                     sources=[{"doc": "DOC-NOWHERE", "where": ""}])
        self.assertEqual(ac.check_evidence(s, self.ctx()), [
            "도면에 없는 태그: XX-999", "그래프에 없는 ID: entity-node-999",
            "이어지지 않는 경로 단계: entity-node-001 → entity-node-012", "확인 안 되는 출처 문서: DOC-NOWHERE"])

    def test_warnings_live_in_entry_and_do_not_block(self):
        r = ac.run_unit(FakeClient(completed([answer("D01", [scenario(equipment_tags=["XX-999"])])])),
                        self.unit("D01"), self.ctx(), self.devs, AT)
        e = r["cells"]["D01"]["entries"][0]
        self.assertEqual((r["cells"]["D01"]["status"], e["ai_basis"]["warnings"]), ("ok", ["도면에 없는 태그: XX-999"]))

    def test_without_kg_doc_and_knowledge_ids_are_unconfirmed(self):
        s = scenario(kg_paths=[["entity-node-001", "req-001"]], sources=[{"doc": self.doc_id, "where": ""}])
        self.assertEqual(ac.check_evidence(s, self.ctx(kg=None)),
                         ["그래프에 없는 ID: req-001", "확인 안 되는 출처 문서: %s" % self.doc_id])


class RiskTest(unittest.TestCase):
    def test_risk_from_matrix_and_null(self):
        self.assertEqual([sr.risk_of(4, 3), sr.risk_of(3, 1), sr.risk_of(1, 1)], [5, 2, 1])
        self.assertEqual([sr.risk_of(None, 2), sr.risk_of(2, None), sr.risk_of(None, None), sr.risk_of(5, 1)],
                         [None] * 4)


class ApplyTest(Base):
    def setUp(self):
        self.res = sr.empty_results(self.node_set, self.devs)
        self.nid = self.node["node_id"]

    def apply(self, results, respond, at, *dids):
        ur = ac.run_unit(FakeClient(respond), self.unit(*dids), self.ctx(), self.devs, at)
        return ac.apply_unit(results, ur)

    def cell(self, results, did):
        return next(c for c in results["cells"] if c["node_id"] == self.nid and c["deviation_id"] == did)

    def test_rerun_replaces_only_untouched_ai_drafts(self):
        four = [scenario(cause="원인%d" % i) for i in range(4)]
        r1 = self.apply(self.res, completed([answer("D01", four)]), AT, "D01")
        self.assertEqual(self.res["cells"], sr.empty_results(self.node_set, self.devs)["cells"], "입력 불변")
        ids = [e["entry_id"] for e in self.cell(r1, "D01")["entries"]]
        r1 = sr.edit_entry(r1, self.nid, "D01", ids[0], {"cause": "고친 원인"}, at=AT)
        r1 = sr.set_status(r1, self.nid, "D01", ids[1], "approved", at=AT)
        r1 = sr.set_status(r1, self.nid, "D01", ids[2], "rejected", at=AT)
        r2 = self.apply(r1, completed([answer("D01", [scenario(cause="새 원인")])]), AT2, "D01")
        got = [(e["cause"], e["status"]) for e in self.cell(r2, "D01")["entries"]]
        self.assertEqual(got, [("고친 원인", "revised"), ("원인1", "approved"), ("원인2", "rejected"),
                               ("새 원인", "proposed")])
        self.assertEqual(self.cell(r2, "D01")["ai_run"], {"status": "ok", "error": None, "at": AT2,
                                                         "model": "claude-opus-5-5", "note": None,
                                                         "applicable": True, "via": "api", "error_kind": None,
                                                         "model_requested": "claude-opus-5-5"})
        self.assertEqual(sr.validate(r2, self.node_set), [])

    def test_failure_keeps_entries_and_marks_failed(self):
        r1 = self.apply(self.res, completed([answer("D01")]), AT, "D01")
        before = copy.deepcopy(self.cell(r1, "D01")["entries"])
        r2 = self.apply(r1, lambda _req: {"status": "api_error", "error": "연결 실패"}, AT2, "D01", "D02")
        self.assertEqual(self.cell(r2, "D01")["entries"], before)
        self.assertEqual(self.cell(r2, "D01")["state"], "analyzed")
        self.assertEqual(self.cell(r2, "D02")["state"], "not_analyzed")
        self.assertEqual(self.cell(r2, "D01")["ai_run"]["status"], "failed")
        self.assertEqual(ac.failed_cells(r2), [(self.nid, "D01"), (self.nid, "D02")])
        self.assertEqual(sr.validate(r2, self.node_set), [])
        r3 = self.apply(r2, completed([answer("D01"), answer("D02")]), AT2, "D01", "D02")
        self.assertEqual(ac.failed_cells(r3), [])

    def test_usage_is_logged_per_unit_and_summed(self):
        r = self.apply(self.res, completed([answer("D01")]), AT, "D01")
        r = self.apply(r, completed([answer("D02")]), AT2, "D02")
        r = self.apply(r, lambda _req: {"status": "no_key"}, AT2, "D03")
        self.assertEqual(len(r["ai_log"]), 3)
        self.assertNotIn("usage", self.cell(r, "D01")["ai_run"])
        total = ac.usage_total(r)
        self.assertEqual({k: total[k] for k in ac.USAGE_KEYS}, {k: 2 * v for k, v in USAGE.items()})
        self.assertEqual(total["calls"], 3)
        self.assertAlmostEqual(total["cost_usd"], sum(x["cost_usd"] for x in r["ai_log"]))
        self.assertEqual(r["ai_log"][2]["error"], ac.STATUS_ERRORS["no_key"])


class ReviewEditTest(Base):
    def setUp(self):
        res = sr.empty_results(self.node_set, self.devs)
        ur = ac.run_unit(FakeClient(completed([answer("D01")])), self.unit("D01"), self.ctx(), self.devs, AT)
        self.res = ac.apply_unit(res, ur)
        self.nid = self.node["node_id"]
        self.eid = ur["cells"]["D01"]["entries"][0]["entry_id"]

    def entry(self, results):
        cell = next(c for c in results["cells"] if c["node_id"] == self.nid and c["deviation_id"] == "D01")
        return cell["entries"][0]

    def test_edit_after_approve_returns_to_revised_and_recomputes_risk(self):
        approved = sr.set_status(self.res, self.nid, "D01", self.eid, "approved", at=AT)
        edited = sr.edit_entry(approved, self.nid, "D01", self.eid, {"severity": 4, "frequency": 3}, at=AT2)
        e = self.entry(edited)
        self.assertEqual((e["status"], e["risk"], e["origin"]), ("revised", 5, "ai_draft"))
        self.assertEqual([h["op"] for h in e["history"]], ["status", "edit"])
        self.assertEqual(e["history"][1]["before"], {"severity": 3, "frequency": 2})
        self.assertEqual(self.entry(approved)["status"], "approved", "입력 불변")
        self.assertTrue(sr.is_ai_draft(e))

    def test_bad_edits_are_refused(self):
        for args in (("proposed",), ("maybe",)):
            with self.assertRaises(ValueError):
                sr.set_status(self.res, self.nid, "D01", self.eid, *args)
        for fields in ({"severity": 5}, {"frequency": 0}, {"risk": 1}, {"safeguards": "문자열"}):
            with self.assertRaises(ValueError):
                sr.edit_entry(self.res, self.nid, "D01", self.eid, fields)
        with self.assertRaises(ValueError):
            sr.set_status(self.res, self.nid, "D01", "no-such-entry", "approved")

    def test_validate_checks_new_fields(self):
        bad = copy.deepcopy(self.res)
        e = self.entry(bad)
        e.update(severity=5, frequency=True)
        next(c for c in bad["cells"] if c.get("ai_run"))["ai_run"]["status"] = "weird"
        problems = "\n".join(sr.validate(bad, self.node_set))
        for needle in ("severity 값", "frequency 값", "ai_run.status 값"):
            self.assertIn(needle, problems)


class StoreTest(Base):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-ai-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp
        self.addCleanup(lambda: os.environ.pop(paths.ENV_WORK_ROOT, None) if old is None
                        else os.environ.__setitem__(paths.ENV_WORK_ROOT, old))

    def test_save_load_round_trip_reads_disk(self):
        self.assertIsNone(sr.load(self.node_set))
        ur = ac.run_unit(FakeClient(completed([answer("D01")])), self.unit("D01"), self.ctx(), self.devs, AT)
        res = ac.apply_unit(sr.empty_results(self.node_set, self.devs), ur)
        path = sr.save(res, self.node_set.get("project_id"))
        self.assertEqual(path, paths.folder_in(self.tmp, "analysis-results", "SNP-SAMPLE", "graph-SNP-M-102.json"))
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), res)
        self.assertEqual(sr.load(self.node_set), res)
        self.assertEqual(os.listdir(os.path.dirname(path)), ["graph-SNP-M-102.json"])
        self.assertFalse(sr.is_stale(res, self.node_set))
        reconfirmed = sn.confirm(sn.reopen(self.node_set, at=AT2), self.graph, "김검토", at=AT2)
        self.assertFalse(sr.is_stale(res, reconfirmed), "v2: 구간을 다시 확정해도 결과 전체가 옛것이 되지 않음")
        self.assertIs(sr.reconcile(res, reconfirmed, self.devs), res, "구성요소가 같으면 칸도 그대로")

    def test_load_rejects_foreign_file(self):
        path = sr.store_path(None, self.node_set["graph_id"])
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(sr.empty_results(self.node_set, self.devs), graph_id="graph-OTHER"), fh)
        with self.assertRaises(ValueError):
            sr.load(self.node_set)

    def test_load_kg_for_finds_project_or_referring_kg(self):
        kg, why = ac.load_kg_for(self.node_set)
        self.assertIsNone(kg)
        self.assertIn("지식그래프가 없음", why)
        root = paths.output_root("knowledge-graph")
        build.write_outputs(os.path.join(root, "kg-SNP-SAMPLE"), chk.sample_knowledge(), self.kg)
        kg, why = ac.load_kg_for(self.node_set)
        self.assertEqual((kg["kg_id"], why), (self.kg["kg_id"], None))
        kg, why = ac.load_kg_for(dict(self.node_set, project_id="P-NONE"))
        self.assertEqual((kg, why), (None, "프로젝트 P-NONE의 지식그래프가 없음"))
        build.write_outputs(os.path.join(root, "kg-COPY"), chk.sample_knowledge(), self.kg)
        kg, why = ac.load_kg_for(self.node_set)
        self.assertIsNone(kg)
        self.assertIn("2개", why)


if __name__ == "__main__":
    unittest.main()
