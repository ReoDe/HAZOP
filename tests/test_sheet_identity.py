"""시트 정체 규칙(hazop.graph.sheets)과 엔진이 돌려주는 값의 꼴 시험. 근거: docs/units/2026-11-13-drawing-knowledge/evidence/sheet-identity-design.md.
실행: python -m unittest tests.test_sheet_identity
"""

import os
import unittest

import pypdfium2 as pdfium

from tests.test_sheet_gid_paths import NUMBER, SheetCase
from tests.test_titleblock import P, sample

from hazop.app import project_ctx
from hazop.graph import sheets, sources


def f(**kw):
    base = {"material_id": "material-0123456789ab", "page_index": 0, "page_count": 1, "number": None,
            "page_name": "Page-1", "file": "a.pdf"}
    base.update(kw)
    return base


class RuleTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(sheets.natural(f(number="SNP-M-101")), "graph-SNP-M-101")
        self.assertEqual(sheets.natural(f()), "graph-material-0123456789ab-p0")
        self.assertEqual(sheets.natural(f(page_index=2, page_count=3, number="X")), "graph-material-0123456789ab-p2",
                         "여러 쪽 자료의 자료 단위 번호는 이름에 쓰지 않음")
        self.assertEqual(sheets.natural(f(material_id=None)), "graph-Page-1", "등록 밖 추출은 지금 규칙 그대로")
        self.assertEqual(sheets.natural(f(material_id=None, page_name=None)), "graph-drawing")
        self.assertEqual(sheets.legacy_name(f(page_count=3, number="X")), "graph-X")

    def test_legacy_seat_only_without_a_usable_number(self):
        seats = {"graph-drawing": {"material_id": "material-0123456789ab", "page": 0, "why": "legacy"}}
        self.assertEqual(sheets.sheet_id(f(), seats), "graph-drawing")
        self.assertEqual(sheets.sheet_id(f(page_index=1, page_count=2), seats), "graph-material-0123456789ab-p1")
        self.assertEqual(sheets.sheet_id(f(number="SNP-M-101"), seats), "graph-SNP-M-101", "번호를 확정하면 자연 이름")
        self.assertEqual(sheets.sheet_id(f(material_id="material-ffffffffffff"), seats), "graph-material-ffffffffffff-p0")

    def test_number_problems_are_codes(self):
        self.assertIsNone(sheets.number_problem("SNP-M-101", 1))
        self.assertEqual(sheets.number_problem("SNP-M-101", 3)["code"], "multi_page_number")
        self.assertEqual(sheets.number_problem("material-0123456789ab-p0", 1)["code"], "reserved_number")

    def test_describe(self):
        self.assertEqual(sheets.describe(f(number="SNP-M-101"), "graph-SNP-M-101"),
                         {"graph_id": "graph-SNP-M-101", "label": "SNP-M-101", "drawing_number": "SNP-M-101",
                          "number_state": "confirmed", "notice": None})
        d = sheets.describe(f(page_index=1, page_count=3, file="three.pdf"))
        self.assertEqual((d["label"], d["number_state"], d["notice"]["code"]), ("three.pdf · 2쪽", "unconfirmed",
                                                                                 "confirm_title_block_first"))
        d = sheets.describe(f(page_count=3, number="X"))
        self.assertEqual((d["number_state"], d["notice"]["code"], d["drawing_number"]), ("held", "multi_page_number", None))
        self.assertEqual(sheets.describe(f(material_id=None, number="SNP-M-101"))["notice"], None)


class EngineValueTest(SheetCase):
    def test_multi_page_pdf_rows_and_graph_source(self):
        """여러 쪽 PDF의 쪽마다 graph.json source에 (자료, 쪽)·쪽 수·파일 이름이 있고, 도면 목록 행 이름은 '파일 이름 · n쪽'이다."""
        doc = pdfium.PdfDocument.new()
        for d in ("SNP-M-101", "SNP-M-102"):
            doc.import_pages(pdfium.PdfDocument(sample(d, "pdf")))
        dst = os.path.join(self.tmp, "in2", "two.pdf")
        os.makedirs(os.path.dirname(dst))
        doc.save(dst)
        mid = self.register(dst, dict(NUMBER))
        rows = sources.sheet_rows(P)
        self.assertEqual([(r["graph_id"], r["label"], r["number_state"], (r["notice"] or {}).get("code")) for r in rows],
                         [("graph-%s-p0" % mid, "two.pdf · 1쪽", "held", "multi_page_number"),
                          ("graph-%s-p1" % mid, "two.pdf · 2쪽", "held", "multi_page_number")])
        self.assertEqual(sorted(project_ctx.graph_names(P)), [r["graph_id"] for r in rows])
        pg = project_ctx.project_graph(P)
        self.assertEqual([s["drawing_number"] for s in pg["sheets"]], [None, None], "쓰지 않는 번호는 시트 번호가 아님")
        self.assertEqual([(s["material_id"], s["page_index"]) for s in pg["sheets"]], [(mid, 0), (mid, 1)])

    def test_conflict_and_choose_shapes(self):
        a = self.register(self.copy_in("SNP-M-101", "pdf", "in-a"), NUMBER)
        b = self.register(self.copy_in("SNP-M-102", "pdf", "in-b"), dict(NUMBER))
        rows = sources.conflicts(P)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual({k: row[k] for k in ("kind", "reason", "graph_id", "drawing_number", "in_use_material", "chosen",
                                              "chosen_material", "formats")},
                         {"kind": "file", "reason": "same_number_other_file", "graph_id": "graph-SNP-M-101",
                          "drawing_number": "SNP-M-101", "in_use_material": a, "chosen": None, "chosen_material": None,
                          "formats": ["pdf_vector"]})
        self.assertIn("SNP-M-101", row["text"])
        self.assertEqual(row["in_use"], self.sheet(a)["name"], "셸이 읽던 in_use(폴더 이름)는 그대로")
        self.assertEqual([(c["material_id"], c["in_use"], c["file"]) for c in row["candidates"]],
                         sorted([(a, True, "SNP-M-101_RCS-main-loop.pdf"), (b, False, "SNP-M-102_RCS-pressurizer.pdf")],
                                key=lambda x: self.sheet(x[0])["name"]))
        rec = sources.choose(P, "SNP-M-101", None, BY_NAME, material_id=b)
        self.assertEqual({k: rec[k] for k in ("material_id", "why", "by")}, {"material_id": b, "why": "chosen", "by": BY_NAME})
        row = sources.conflicts(P)[0]
        self.assertEqual((row["in_use_material"], row["chosen_material"]), (b, b))


BY_NAME = "검토자"


class MaterialSwitchIdmapTest(unittest.TestCase):
    """판 이전(hazop.study.idmap.compute)은 시트 자료가 바뀌면 파일 id가 같아도 잇지도, source 묘비로 되찾지도 않는다."""
    M = "graph-X/entity-node-001"

    def graph(self, mid, ver, tag="P-1"):
        return {"graph_id": "project-P1", "graph_version": ver, "sheets": [{"graph_id": "graph-X", "material_id": mid}],
                "nodes": [{"entity_id": self.M, "source_object_id": "cell-5", "sheet": "graph-X", "id_basis": "source",
                           "node_type": "drawing_object", "kind": "pump", "tag": tag}], "edges": []}

    def node_set(self, graph, members, tombs=None):
        from hazop.study import idmap
        return dict(idmap.snapshot(graph), graph_version=graph["graph_version"], tombstones=tombs or {},
                    nodes=[{"node_id": "S1", "members": members}])

    def test_same_material_links_by_id(self):
        from hazop.study import idmap
        table = idmap.compute(self.node_set(self.graph("material-aaaaaaaaaaaa", "v1"), [self.M]),
                              self.graph("material-aaaaaaaaaaaa", "v2"))
        self.assertEqual(table["eid"][self.M], self.M)

    def test_other_material_makes_a_tomb_and_never_recovers_it(self):
        from hazop.study import idmap
        a, b = "material-aaaaaaaaaaaa", "material-bbbbbbbbbbbb"
        table = idmap.compute(self.node_set(self.graph(a, "v1"), [self.M]), self.graph(b, "v2"))
        tomb = table["eid"][self.M]
        self.assertTrue(idmap.is_tomb(tomb), "다른 파일의 같은 id 기호로 이어짐")
        self.assertEqual(table["new_tombs"][tomb]["material"], a)
        later = idmap.compute(self.node_set(self.graph(b, "v2"), [], table["new_tombs"]), self.graph(b, "v3"))
        self.assertEqual(later["found"], {}, "다른 파일에서 잃은 묘비를 같은 id·같은 겉모습으로 되찾음")
        back = idmap.compute(self.node_set(self.graph(b, "v2"), [], table["new_tombs"]), self.graph(a, "v3"))
        self.assertEqual(list(back["found"]), [tomb], "잃을 때의 파일로 돌아가면 되찾음")


if __name__ == "__main__":
    unittest.main()
