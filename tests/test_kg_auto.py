"""지식그래프 자동 생성(hazop.kg.auto)과 문서 지식 추출(hazop.kg.docextract) 시험. 임시 폴더에만 쓴다.

입력: 샘플 도면 SNP-M-102(tests/test_kg.pid_graph)와 가상 설계 문서 PDF(tests/fixtures/docextract, 실제 설계자료 아님).
"""

import copy
import glob
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.kg import auto, build, docextract, screen  # noqa: E402

DOC_PDF = glob.glob(os.path.join(REPO_ROOT, "tests", "fixtures", "docextract", "*.pdf"))[0]
HAS_PDFPLUMBER = importlib.util.find_spec("pdfplumber") is not None
PROJECT = "auto-test"
MATERIAL = "material-0123456789ab"


def pid_graph():
    import test_kg
    g = test_kg.pid_graph()
    g["project_id"] = PROJECT
    return g


def document():
    d = docextract.extract_pdf(DOC_PDF, MATERIAL, 1, "document-001", "가압기 설계 설명서(가상)")
    d["project_id"] = PROJECT
    return d


def by_type(d, t):
    return [n for n in d["nodes"] if n["node_type"] == t]


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(전용 venv에서 실행)")
class DocExtractTest(unittest.TestCase):
    def test_values_requirements_and_evidence(self):
        d = document()
        self.assertEqual(d["validation"]["status"], "passed")
        values = {(n["node_type"], n["item"], n["value"], n["unit"], n["pressure_basis"])
                  for n in d["nodes"] if n["node_type"] in ("setpoint", "condition")}
        self.assertIn(("condition", "운전압력", "15.5", "MPa", "absolute"), values)
        self.assertIn(("condition", "설계압력", "17.2", "MPa", "gauge"), values)
        self.assertIn(("setpoint", "설정압력", "17.2", "MPa", "gauge"), values)
        self.assertIn(("setpoint", "고압 트립 설정치", "16.6", "MPa", None), values)  # 압력 기준 원문에 없음 -> 미확인
        reqs = [n["text"] for n in by_type(d, "requirement")]
        self.assertTrue(any("닫힘 위치로 가야 한다" in t for t in reqs))
        self.assertTrue(any(n["item"] == "설계 의도" for n in by_type(d, "requirement")))
        for n in d["nodes"]:
            if n["node_type"] == "document":
                continue
            self.assertEqual((n["method"], n["knowledge_status"]), ("extractor", "unknown"))
            self.assertEqual(n["source"]["material_id"], MATERIAL)
            self.assertTrue(n["source"]["page"] and n["source"]["locator"])
        trip = next(n for n in d["nodes"] if n.get("item") == "고압 트립 설정치")
        self.assertEqual(trip["source"]["page"], "2")
        self.assertIn("'3. 설정치'", trip["source"]["locator"])
        self.assertIn("pressure_basis", trip["null_reasons"])

    def test_number_without_keyword_makes_no_value(self):
        d = docextract.extract([(1, ["1. 개요", "이 문서는 2026년에 12 mm 도면을 다룬다."])], MATERIAL, 1, "document-001")
        self.assertEqual(by_type(d, "setpoint") + by_type(d, "condition"), [])

    def test_text_less_pdf_is_blocked(self):
        d = docextract.extract([(1, []), (2, [])], MATERIAL, 1, "document-001")
        self.assertEqual(d["validation"]["status"], "blocked")
        self.assertEqual(d["validation"]["blockers"][0]["check"], "no_text")

    def test_deterministic(self):
        self.assertEqual(json.dumps(document(), sort_keys=True), json.dumps(document(), sort_keys=True))


class DrawingOnlyTest(unittest.TestCase):
    def test_drawing_without_knowledge_input_builds_and_shows(self):
        g = pid_graph()
        knowledge, _ = auto.assemble(PROJECT, [g], [])
        kg = build.build_kg(knowledge, [g])
        self.assertEqual(kg["validation"]["status"], "passed")
        self.assertEqual(kg["graph_refs"], [{"graph_id": g["graph_id"], "graph_version": g["graph_version"]}])
        data = screen.screen_data(kg, g)
        self.assertEqual(len(data["nodes"]), len(g["nodes"]))
        self.assertTrue(data["algo"]["enabled"], data["algo"]["reason"])

    def test_missing_project_graph_blocks(self):
        g = pid_graph()
        knowledge, _ = auto.assemble(PROJECT, [g], [])
        kg = build.build_kg(knowledge, [])
        self.assertEqual([b["check"] for b in kg["validation"]["blockers"]], ["graph_not_found"])


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(전용 venv에서 실행)")
class DocumentLinkTest(unittest.TestCase):
    def test_document_knowledge_joins_drawing_as_candidates(self):
        g, d = pid_graph(), document()
        knowledge, notes = auto.assemble(PROJECT, [g], [d])
        kg = build.build_kg(knowledge, [g])
        self.assertEqual(kg["validation"]["status"], "passed", kg["validation"]["blockers"])
        applied = {(l["kind"], l["from"]) for l in kg["links"] if l["kind"] in auto.APPLY_KIND.values()}
        self.assertIn(("has_setpoint", "graph-SNP-M-102:RC-PIC110"), applied)
        self.assertIn(("has_setpoint", "graph-SNP-M-102:RC-PSV101"), applied)
        self.assertIn(("governed_by", "graph-SNP-M-102:RC-PV101"), applied)
        self.assertTrue(all(l["link_status"] == "candidate" for l in kg["links"]))
        self.assertEqual(kg["summary"]["v4_links"], 0)  # 사람 확인 전 항목은 계산에 넣지 않는다
        data = screen.screen_data(kg, g)
        shown = {n["id"] for n in data["nodes"] if n["layer"] == "kn"}
        self.assertTrue({n["id"] for n in d["nodes"]} <= shown)
        self.assertTrue(any(l["st"] == "candidate" and l["kind"] == "has_setpoint" for l in data["links"]))

    def test_tag_missing_from_drawing_is_noted_not_linked(self):
        g, d = pid_graph(), copy.deepcopy(document())
        d["tag_mentions"].append({"node_id": by_type(d, "requirement")[0]["id"], "tags": ["RC-V999"]})
        _, notes = auto.assemble(PROJECT, [g], [d])
        self.assertTrue(any("RC-V999" in n for n in notes))

    def test_build_project_writes_same_version_twice(self):
        tmp = tempfile.mkdtemp()
        try:
            groot, droot, out = (os.path.join(tmp, x) for x in ("graph", "doc", "kg"))
            os.makedirs(os.path.join(groot, "g1"))
            os.makedirs(os.path.join(droot, "d1"))
            with open(os.path.join(groot, "g1", "graph.json"), "w", encoding="utf-8") as fh:
                json.dump(pid_graph(), fh, ensure_ascii=False)
            with open(os.path.join(droot, "d1", auto.DOC_FILE), "w", encoding="utf-8") as fh:
                json.dump(document(), fh, ensure_ascii=False)
            self.assertEqual(auto.project_ids(groot, droot), [PROJECT])
            a = auto.build_project(PROJECT, groot, droot, os.path.join(tmp, "csv"), out)
            b = auto.build_project(PROJECT, groot, droot, os.path.join(tmp, "csv"), out)
            self.assertEqual(a["kg"]["kg_version"], b["kg"]["kg_version"])
            _, kg = build.load_outputs(os.path.join(out, "kg-" + PROJECT))
            self.assertEqual(kg["kg_version"], a["kg"]["kg_version"])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
