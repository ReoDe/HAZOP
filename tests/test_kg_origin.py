"""M1: 생성 주체 origin, ② 사람 수정 표시의 그래프 전달, 문서 조각 mentions 후보 시험 (기획서/지식그래프-스키마.md §3, §8.2 M1).

임시 폴더에만 쓴다. 도면은 샘플 SNP-M-102, 문서는 가상 설계 문서 PDF(tests/fixtures/docextract, 실제 설계자료 아님).
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import extract_drawio  # noqa: E402
import test_kg  # noqa: E402
import test_kg_auto  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from hazop.graph import build as gbuild  # noqa: E402
from hazop.graph import project  # noqa: E402
from hazop.kg import algo, auto, build, link, screen  # noqa: E402
from hazop.kg.schema import REGISTRY  # noqa: E402
from hazop.study import migrate  # noqa: E402

PROJECT = test_kg_auto.PROJECT
_EXTRACTION = None


def extraction():
    global _EXTRACTION
    if _EXTRACTION is None:
        tmp = tempfile.mkdtemp()
        try:
            _EXTRACTION, _ = extract_drawio.run_one(test_kg._DRAWIO[0], tmp)
        finally:
            shutil.rmtree(tmp)
    return copy.deepcopy(_EXTRACTION)


def kn_node(nid, ntype="requirement", **kw):
    d = {"id": nid, "node_type": ntype, "name": None, "text": "가상 문장", "item": None, "value": None, "unit": None,
         "pressure_basis": None, "operating_mode": None,
         "source": {"material_id": "MAT-KG-001", "registration_version": "1", "document_id": "DOC-KG-001",
                    "page": "1", "locator": None, "unregistered_reason": None},
         "method": "manual", "extractor": None, "confidence": None, "knowledge_status": "confirmed",
         "author": "t", "reason": None, "null_reasons": {}}
    d.update(kw)
    return d


def knowledge(nodes, links=()):
    return {"schema_version": "0.1", "project_id": "P", "kg_id": "kg-P", "inputs": {}, "nodes": list(nodes),
            "links": list(links)}


class RegistryOriginTest(unittest.TestCase):
    def test_origins_and_legacy_methods(self):
        self.assertEqual(list(REGISTRY.origins),
                         ["pid_extract", "human_edit", "doc_rule", "human", "ai_draft", "expectation_rule"])
        self.assertEqual(REGISTRY.origin_of_method(), {"extractor": "doc_rule", "regex": "doc_rule",
                                                       "exact_norm": "doc_rule", "fuzzy": "doc_rule", "manual": "human"})
        self.assertEqual(REGISTRY.origins_needing_reviewer(), ("ai_draft",))
        self.assertEqual(REGISTRY.origins["human_edit"]["label_ko"], "사람 수정")
        self.assertEqual(REGISTRY.origins["ai_draft"]["label_ko"], "AI 초안")

    def test_method_in_two_origins_is_rejected(self):
        from hazop.kg import schema
        d = copy.deepcopy(REGISTRY.data)
        d["origins"][3]["legacy_methods"].append("fuzzy")
        self.assertIn("method fuzzy가 생성 주체 둘 이상의 legacy_methods에 있음", schema.validate(d))


class GraphOriginTest(unittest.TestCase):
    def test_extracted_objects_are_pid_extract(self):
        g = gbuild.build_graph(extraction())
        self.assertEqual({n["origin"] for n in g["nodes"]} | {e["origin"] for e in g["edges"]}, {"pid_extract"})
        self.assertFalse(any("human_edit" in n for n in g["nodes"]))

    def test_old_graph_without_origin_is_read_by_edit_mark(self):
        self.assertEqual(gbuild.node_origin({"entity_id": "entity-node-001"}), "pid_extract")
        self.assertEqual(gbuild.node_origin({"entity_id": "entity-node-001", "human_edit": {"op_ids": ["c-0001"]}}),
                         "human_edit")

    def test_human_edit_reaches_graph_and_screen(self):
        base = extraction()
        node = next(n for n in base["nodes"] if n.get("tag"))
        rel = next(r for r in base["relations"] if r["kind"] == "physical_connection")
        pts = [ep["point"] for ep in rel["endpoints"]]
        ops = [corrections.make_op(base, "set_tag", node["source_object_id"], {"tag": node["tag"] + "A"}, "검토자",
                                   at="2026-11-08T00:00:00Z")]
        ops.append(corrections.make_op(base, "set_path", rel["source_object_id"],
                                       {"points": [pts[0], [pts[0][0] + 5, pts[1][1]], pts[1]]}, "검토자",
                                       at="2026-11-08T00:00:00Z", existing_ops=ops))
        g = gbuild.build_graph(corrections.apply(base, ops))
        edited = {n["source_object_id"]: n for n in g["nodes"] if n["origin"] == "human_edit"}
        self.assertEqual(sorted(edited), sorted([node["source_object_id"], rel["source_object_id"]]))
        self.assertEqual(edited[node["source_object_id"]]["human_edit"],
                         {"op_ids": ["c-0001"], "ops": ["set_tag"], "by": "검토자", "at": "2026-11-08T00:00:00Z"})
        self.assertEqual(edited[rel["source_object_id"]]["human_edit"]["ops"], ["set_path"])
        seg_id = edited[rel["source_object_id"]]["entity_id"]
        self.assertEqual({e["origin"] for e in g["edges"] if e.get("segment") == seg_id}, {"human_edit"})
        kg = build.build_kg(knowledge([]), [g])
        data = screen.screen_data(kg, g)
        hedit = sorted(n["id"] for n in data["nodes"] if n.get("hedit"))
        self.assertEqual(hedit, sorted(n["entity_id"] for n in edited.values()))

    def test_edit_mark_does_not_change_member_digest(self):
        """판 이전 판정(member_digest)은 종류·태그·배관 번호·흐름·연결만 본다. 수정 표시·origin은 넣지 않는다."""
        base = extraction()
        rel = next(r for r in base["relations"] if r["kind"] == "physical_connection")
        pts = [ep["point"] for ep in rel["endpoints"]]
        op = corrections.make_op(base, "set_path", rel["source_object_id"],
                                 {"points": [pts[0], [pts[0][0] + 5, pts[1][1]], pts[1]]}, "검토자")
        before, after = gbuild.build_graph(base), gbuild.build_graph(corrections.apply(base, [op]))
        self.assertNotEqual(before["graph_version"], after["graph_version"])
        self.assertEqual(migrate.member_digest(before), migrate.member_digest(after))
        stripped = copy.deepcopy(after)
        for n in stripped["nodes"] + stripped["edges"]:
            n.pop("origin", None)
            n.pop("human_edit", None)
        self.assertEqual(migrate.member_digest(stripped), migrate.member_digest(after))

    def test_project_sheet_link_segment_has_origin(self):
        g = gbuild.build_graph(extraction())
        pg = project.build("P", [g])
        self.assertTrue(all(n.get("origin") for n in pg["nodes"]))


class KnowledgeOriginTest(unittest.TestCase):
    def test_origin_inferred_from_method_for_old_inputs(self):
        k = knowledge([kn_node("req-001"), kn_node("req-002", method="extractor", knowledge_status="unknown")])
        kg = build.build_kg(k, [])
        self.assertEqual({n["id"]: n["origin"] for n in kg["nodes"]}, {"req-001": "human", "req-002": "doc_rule"})
        self.assertEqual(kg["validation"]["status"], "passed")

    def test_sample_csv_links_get_origin(self):
        kg = build.build_kg(test_kg.sample(), [test_kg.pid_graph()])
        self.assertEqual(kg["validation"]["status"], "passed", kg["validation"]["blockers"])
        self.assertEqual({l["origin"] for l in kg["links"] if l["method"] == "manual"}, {"human"})
        self.assertEqual({l["origin"] for l in kg["links"] if l["method"] in ("exact_norm", "fuzzy")}, {"doc_rule"})

    def test_invalid_origin_is_blocked(self):
        k = knowledge([kn_node("req-001", origin="pid_extract")])
        self.assertEqual(test_kg.keys(build.build_kg(k, [])), [("K1", "invalid_origin", "req-001")])

    def test_ai_draft_confirmed_without_reviewer_is_blocked(self):
        k = knowledge([kn_node("req-001", origin="ai_draft")])
        self.assertEqual(test_kg.keys(build.build_kg(k, [])), [("K1", "ai_draft_confirmed_without_reviewer", "req-001")])
        g = test_kg.pid_graph()
        lk = test_kg.link("krel-001", "governed_by", "graph-SNP-M-102:RC-PIC110", "req-001", origin="ai_draft",
                          link_status="candidate", reviewed_by=None)
        kg = build.build_kg(knowledge([kn_node("req-001")], [lk]), [g])
        self.assertEqual(test_kg.keys(kg), [("K1", "ai_draft_confirmed_without_reviewer", "krel-001")])

    def test_ai_draft_with_reviewer_or_as_hypothesis_passes(self):
        reviewed = kn_node("req-001", origin="ai_draft", reviewed_by="검토자")
        draft = kn_node("req-002", origin="ai_draft", knowledge_status="hypothesis")
        kg = build.build_kg(knowledge([reviewed, draft]), [])
        self.assertEqual(kg["validation"]["status"], "passed", kg["validation"]["blockers"])
        v4 = {n["id"]: n["compute_view"]["v4"] for n in kg["nodes"]}
        self.assertEqual(v4, {"req-001": True, "req-002": False})
        data = screen.screen_data(kg, test_kg.pid_graph())
        self.assertEqual(sorted(n["id"] for n in data["nodes"] if n.get("ai")), ["req-001", "req-002"])


@unittest.skipUnless(test_kg_auto.HAS_PDFPLUMBER, "pdfplumber 없음(전용 venv에서 실행)")
class MentionCandidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.g = test_kg_auto.pid_graph()
        self.doc = test_kg_auto.document()

    def build(self, doc=None, csv_dir=None):
        k, notes = auto.assemble(PROJECT, [self.g], [doc or self.doc], csv_dir)
        return build.build_kg(k, [self.g]), notes

    def chunk_orphans(self, kg):
        return sorted(o["id"] for o in algo.a2_orphans_gaps(kg, self.g)["orphans"] if o["node_type"] == "doc_chunk")

    def judge(self, status):
        rows = [dict(r, link_status=status, reviewed_by="검토자", reviewed_at="2026-11-08", reason="시험")
                for r in link.generate([{"id": n["id"], "node_type": "doc_chunk", "text": n["text"],
                                         "material_id": n["source"]["material_id"],
                                         "registration_version": n["source"]["registration_version"]}
                                        for n in self.doc["nodes"] if n["node_type"] == "doc_chunk"],
                                       [self.g])["candidates"]]
        link.write_candidates(os.path.join(self.tmp, link.CANDIDATES_CSV), rows)
        return rows

    def test_candidates_are_made_and_stay_out_of_v4(self):
        kg, _ = self.build()
        self.assertEqual(kg["validation"]["status"], "passed", kg["validation"]["blockers"])
        men = [l for l in kg["links"] if l["kind"] == "mentions"]
        self.assertTrue(men)
        self.assertEqual({(l["link_status"], l["knowledge_status"], l["origin"]) for l in men},
                         {("candidate", "unknown", "doc_rule")})
        self.assertFalse(any(l["compute_view"]["v4"] for l in men))
        self.assertEqual({l["ends"]["to"]["graph_id"] for l in men}, {"graph-SNP-M-102"})
        self.assertTrue({"RC-PIC110", "RC-PV101"} <= {l["ends"]["to"]["tag"] for l in men})
        k1, _ = auto.assemble(PROJECT, [self.g], [self.doc])
        k2, _ = auto.assemble(PROJECT, [self.g], [self.doc])
        self.assertEqual(build.kg_version(k1, []), build.kg_version(k2, []))

    def test_confirmed_judgement_reduces_chunk_orphans(self):
        doc = copy.deepcopy(self.doc)
        for n in doc["nodes"]:
            if n["node_type"] == "doc_chunk":  # 사람이 조각을 확인했다고 가정(조각이 V4에 있어야 A2가 판정함)
                n["knowledge_status"] = "confirmed"
        before, _ = self.build(doc)
        self.judge("confirmed")
        after, _ = self.build(doc, self.tmp)
        self.assertEqual(after["validation"]["status"], "passed", after["validation"]["blockers"])
        men = [l for l in after["links"] if l["kind"] == "mentions"]
        self.assertEqual({(l["link_status"], l["reviewed_by"]) for l in men}, {("confirmed", "검토자")})
        self.assertTrue(all(l["compute_view"]["v4"] for l in men))
        self.assertLess(len(self.chunk_orphans(after)), len(self.chunk_orphans(before)))

    def test_confirmed_judgement_lost_by_new_version_is_noted(self):
        rows = self.judge("confirmed")
        for r in rows:
            r["candidate_key"] = r["candidate_key"].replace(self.g["graph_version"], "v-old")
        link.write_candidates(os.path.join(self.tmp, link.CANDIDATES_CSV), rows)
        kg, notes = self.build(csv_dir=self.tmp)
        self.assertEqual({l["link_status"] for l in kg["links"] if l["kind"] == "mentions"}, {"candidate"})
        self.assertTrue(any("다시 후보가 됨" in n for n in notes), notes)
        _, quiet = self.build()
        self.assertFalse(any("다시 후보가 됨" in n for n in quiet))

    def test_rejected_judgement_drops_candidate(self):
        self.judge("rejected")
        kg, _ = self.build(csv_dir=self.tmp)
        self.assertEqual([l for l in kg["links"] if l["kind"] == "mentions"], [])

    def test_bad_judgement_file_keeps_candidates_and_notes(self):
        rows = self.judge("confirmed")
        rows[0]["reviewed_by"] = None
        link.write_candidates(os.path.join(self.tmp, link.CANDIDATES_CSV), rows)
        kg, notes = self.build(csv_dir=self.tmp)
        self.assertEqual({l["link_status"] for l in kg["links"] if l["kind"] == "mentions"}, {"candidate"})
        self.assertTrue(any("link_candidates.csv 판단을 읽지 못함" in n for n in notes))

    def test_screen_does_not_repeat_csv_candidate_row(self):
        rows = self.judge("candidate")
        kg, _ = self.build(csv_dir=self.tmp)
        data = screen.screen_data(kg, self.g, candidates=rows)
        self.assertFalse(any(l["id"].startswith("cand:") for l in data["links"]))
        self.assertEqual(sum(l["st"] == "candidate" and l["kind"] == "mentions" for l in data["links"]), len(rows))


if __name__ == "__main__":
    unittest.main()
