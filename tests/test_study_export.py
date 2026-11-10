"""⑤ 결과 Excel 내보내기(hazop.export.study_xlsx). 두 도면 합성 그래프와 가짜 결과만 쓴다(네트워크·AI 호출 없음).
실행: python -m unittest tests.test_study_export
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl  # noqa: E402

from hazop.export import study_xlsx as sx  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_span import AT, two_sheets  # noqa: E402

NOW = "2026-11-08T03:00:00Z"
DEVS = [{"deviation_id": "D01", "item_id": "i1", "parameter": "흐름", "guideword": "없음", "label": "흐름 없음"},
        {"deviation_id": "D02", "item_id": "i2", "parameter": "압력", "guideword": "높음", "label": "압력 높음"},
        {"deviation_id": "D03", "item_id": "i3", "parameter": "온도", "guideword": "높음", "label": "온도 높음"}]
KEY = "sk-ant-api03-" + "x" * 20


def _entry(eid, status, origin="ai_draft", **kw):
    e = {"entry_id": eid, "origin": origin, "status": status, "cause": "원인 " + eid, "consequence": "결과",
         "safeguards": ["보호수단 1"], "recommendation": "권고 " + eid, "severity": 3, "frequency": 2,
         "risk": res.risk_of(3, 2), "ai_basis": {"kg_paths": [], "sources": [], "equipment_tags": [], "warnings": []},
         "history": []}
    e.update(kw)
    return e


def sample():
    """(results, node_set, pg). 걸친 구간 S_a: 승인 1·제안 1(다른 도면 태그·근거·경고) + 해당 없음 칸.
    단일 구간 S_b: 실패 칸 + 수정 1(수식 모양·경로·키 모양 글자) + 기각 1."""
    _, _, pg, ns = two_sheets()
    span_node = next(n["node_id"] for n in sx.span.annotate(ns, pg)["nodes"] if n["spans_drawings"])
    single = next(n["node_id"] for n in ns["nodes"] if n["node_id"] != span_node)
    r = res.empty_results(ns, DEVS)
    cells = {(c["node_id"], c["deviation_id"]): c for c in r["cells"]}
    ok = {"status": "ok", "error": None, "at": AT, "model": "m", "note": None, "applicable": True}
    cells[(span_node, "D01")].update(state="analyzed", ai_run=ok, entries=[
        _entry("a1", "approved", history=[{"at": AT, "op": "status", "from": "proposed", "to": "approved"}]),
        _entry("a2", "proposed", cause="SNP-M-101-E 펌프 정지",
               ai_basis={"kg_paths": [["graph-SNP-M-101/E", "graph-SNP-M-102/E"]],
                         "sources": [{"doc": "DOC-1", "where": "p.3"}], "equipment_tags": [],
                         "warnings": ["없는 ID 참조"]})])
    cells[(span_node, "D02")].update(state="analyzed", entries=[], ai_run=dict(ok, applicable=False, note="흐름 없음"))
    cells[(single, "D01")].update(ai_run=dict(ok, status="failed", error="AI 호출 중 오류(Timeout)"))
    cells[(single, "D02")].update(state="analyzed", ai_run=ok, entries=[
        _entry("b1", "revised", cause="=1+1", recommendation="C:\\Users\\kim\\x.json 와 %s 확인" % KEY,
               history=[{"at": AT, "op": "edit", "from": "proposed", "before": {"cause": "x"}}]),
        _entry("b2", "rejected")])
    assert res.validate(r, ns) == []
    return r, ns, pg, span_node, single


class StudyExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-xlsx-")
        self.r, self.ns, self.pg, self.span_node, self.single = sample()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read(self, **kw):
        path, n = sx.export(os.path.join(self.tmp, "out.xlsx"), self.r, self.ns, self.pg, DEVS, now=NOW, **kw)
        wb = openpyxl.load_workbook(path)
        ws = wb[sx.SHEETS[2]]
        head = [c.value for c in ws[1]]
        rows = [dict(zip(head, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]
        return wb, rows, n

    def test_sheets_and_one_row_per_scenario_plus_cell_rows(self):
        wb, rows, n = self._read()
        self.assertEqual(wb.sheetnames, list(sx.SHEETS))
        entries = [x for x in rows if x["상태"].split(" · ")[0] in sx.STATUS_LABELS.values()]
        self.assertEqual(len(entries), sx.counts(self.r)["scenarios"])
        self.assertEqual(len(rows), n)
        states = {x["상태"] for x in rows}
        self.assertTrue({"해당 없음(AI 판단)", "실패(AI 실행)", "승인", "제안 · AI 초안", "기각", "수정 · AI 초안"} <= states,
                        states)

    def test_cell_rows_keep_detail_out_of_cause(self):
        _, rows, _ = self._read()
        failed = next(x for x in rows if x["상태"] == "실패(AI 실행)")
        self.assertEqual((failed["원인"], failed["근거 경고"]), (None, "⚠ AI 호출 중 오류(Timeout)"))
        na = next(x for x in rows if x["상태"] == "해당 없음(AI 판단)")
        self.assertEqual((na["원인"], na["AI 근거(KG 경로·출처 문서)"]), (None, "AI 메모: 흐름 없음"))

    def test_drawing_numbers_tags_and_risk_text(self):
        _, rows, _ = self._read()
        spanning = [x for x in rows if x["구간"].endswith("[101 → 102]")]
        self.assertTrue(spanning)
        self.assertTrue(all(x["도면 번호"] == "SNP-M-101, SNP-M-102" for x in spanning))
        a2 = next(x for x in rows if (x["원인"] or "").endswith("펌프 정지"))
        self.assertEqual(a2["원인"], "SNP-M-101-E(101) 펌프 정지")
        self.assertIn("KG: SNP-M-101-E(101) → SNP-M-102-E(102)", a2["AI 근거(KG 경로·출처 문서)"])
        self.assertIn("문서: DOC-1 (p.3)", a2["AI 근거(KG 경로·출처 문서)"])
        self.assertEqual(a2["근거 경고"].splitlines()[0], "⚠ 없는 ID 참조")
        self.assertIn("⚠ 작동 방식 미확인: 보호수단 1개", a2["근거 경고"])
        self.assertEqual(a2["위험도"], "4 조건부 수용")

    def test_status_filters(self):
        _, rows, _ = self._read(scope="approved")
        self.assertEqual([x["상태"] for x in rows], ["승인"])
        _, rows, _ = self._read(scope="nodes", node_ids=[self.single])
        self.assertTrue(rows and all(x["구간"].startswith(self.single + " ") for x in rows))
        with self.assertRaises(ValueError):
            sx.build_workbook(self.r, self.ns, self.pg, DEVS, scope="nodes", node_ids=[])

    def test_no_formula_paths_or_keys(self):
        wb, rows, _ = self._read()
        b1 = next(x for x in rows if x["원인"] == "=1+1")
        self.assertNotIn("Users", b1["권고"])
        self.assertNotIn(KEY, b1["권고"])
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    self.assertNotEqual(c.data_type, "f", c.coordinate)

    def test_recommendations_skip_rejected_and_summary_counts(self):
        wb, _, _ = self._read()
        recs = [r[3] for r in wb[sx.SHEETS[3]].iter_rows(min_row=2, values_only=True)]
        self.assertEqual(sorted(recs), sorted(["권고 a1", "권고 a2", "[가림] 와 [가림] 확인"]))
        summary = {r[0]: r[1] for r in wb[sx.SHEETS[0]].iter_rows(values_only=True)}
        self.assertEqual((summary["시나리오 수"], summary["상태별: 승인"], summary["실패 칸"]), (4, 1, 1))
        self.assertEqual(summary["미검토 시나리오"], 2)
        self.assertIn("초안", summary["고지"])
        nodes = list(wb[sx.SHEETS[1]].iter_rows(min_row=2, values_only=True))
        self.assertIn("[101 → 102]", [n[2] for n in nodes])

    def test_print_and_filter_setup(self):
        wb, _, _ = self._read()
        ws = wb[sx.SHEETS[2]]
        self.assertEqual(ws.freeze_panes, "A2")
        self.assertTrue(ws.auto_filter.ref.startswith("A1:"))
        self.assertEqual(ws.page_setup.orientation, "landscape")
        self.assertEqual(ws.print_title_rows, "$1:$1")

    def test_scrub_keeps_words_and_masks_whole_paths(self):
        self.assertEqual(sx.scrub("risk-informed"), "risk-informed")
        self.assertEqual(sx.scrub("C:\\Program Files\\HAZOP\\a.json 확인"), "[가림] 확인")
        self.assertEqual(sx.scrub("키 %s 끝" % KEY), "키 [가림] 끝")
        for key in ("sk-proj-" + "a1B2" * 10, "sk-" + "Ab3" * 16, "AIza" + "Sy0_-" * 7, "ghp_" + "Z9" * 18,
                    "github_pat_" + "a1_" * 10, "AKIA" + "ABCD1234" * 2):
            self.assertEqual(sx.scrub("키 %s 끝" % key), "키 [가림] 끝", key)
        for plain in ("task-force", "SK-101 밸브", "AIzawa 보고서", "risk-based-inspection-and-maintenance-plan",
                      "AKIAGE", "ghp_short"):
            self.assertEqual(sx.scrub(plain), plain)

    def test_default_filename(self):
        self.assertEqual(sx.default_filename("P 1", NOW), "HAZOP-P_1-20261108-1200.xlsx")


if __name__ == "__main__":
    unittest.main()
