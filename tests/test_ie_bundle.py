"""IE 인계 묶음(hazop.ie.bundle·bundle_xlsx)과 내보내기 진입점(⑤ 화면·scripts/export_ie_bundle.py).
두 도면 합성 그래프와 가짜 결과만 쓴다(네트워크·AI 호출 없음). 실행: python -m unittest tests.test_ie_bundle
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openpyxl  # noqa: E402

from hazop.ie import bundle as ib  # noqa: E402
from hazop.ie import bundle_xlsx as ix  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_export import KEY, NOW, _entry, sample  # noqa: E402

# §3.4 예시 Excel(make_ie_example.py)의 머리글 그대로
EXPECTED = {
    "읽는 법": ["항목", "내용"],
    "IE 후보": ["후보 ID", "판정", "정상운전 교란", "안전기능 도전", "도전받는 안전기능", "원인", "원인 유형", "원인 위치",
              "고장모드", "구간", "편차", "비완화 결과", "일반 범주 제안", "그룹 ID", "제외·보류 사유", "식별 기법",
              "출처 항목 ID", "안정 참조", "작성", "⑤ 상태"],
    "추적표": ["구간·편차", "출처 항목 ID", "원인", "후보 ID", "판정", "그룹 ID", "표제 ID", "ES ID", "근거 KG 경로",
            "출처 문서"],
    "완전성 대조": ["범주 코드", "범주 이름", "기준표 출처", "대응 그룹", "후보 수", "상태", "사유·처리"],
    "품질 경고": ["경고", "대상", "내용", "근거"],
    "용어·출처": ["용어", "뜻", "출처"],
}
PATH = "C:\\Users\\kim\\secret\\plant.json"
LATER = "2026-11-09T05:30:00Z"


def ie_sample():
    """(results, node_set, pg). sample()에 승인 항목을 더한다: 판정·원인 위치·작동 방식이 있는 항목, AI 초안 판정,
    제외 판정, 범주 없는 후보, 수식·경로·키 모양 글자가 든 b1의 승인 사본. 제안·수정·기각 항목은 그대로 둔다."""
    r, ns, pg, span_node, single = sample()
    cells = {(c["node_id"], c["deviation_id"]): c for c in r["cells"]}
    hint = {"candidate": "yes", "disturbs": "yes", "challenges": "yes", "safety_functions": ["2차측 열제거"],
            "category": "LOMFW", "reason": "", "origin": "human", "status": "confirmed"}
    psv = {"text": "PSV", "role": "mitigative", "actuation": "passive", "refs": [], "ipl": None}
    cells[(span_node, "D03")].update(state="analyzed", entries=[
        _entry("c1", "approved", cause="SNP-M-101-E 배출 펌프 정지", cause_kind="equipment",
               consequence="급수가 끊겨 열제거 상실", consequence_basis="unmitigated", safeguards=[psv],
               cause_refs=[{"ref": "graph-SNP-M-101#E", "failure_mode": "FTR"}, {"ref": "graph-SNP-M-999#X"}],
               ie_hint=hint,
               ai_basis={"kg_paths": [["graph-SNP-M-101/E", "graph-SNP-M-102/E"]],
                         "sources": [{"doc": "DOC-9", "where": "§3.2"}], "equipment_tags": [], "warnings": []}),
        _entry("c2", "approved", cause="공기 헤더 압력 낮음", consequence="경보 후 회복",
               ie_hint=dict(hint, candidate="undecided", challenges="unknown", category="LOIA", reason="응답 자료 없음",
                            origin="ai_draft", status="draft")),
        _entry("c3", "approved", cause="살수밸브 조금 열림", safeguards=[psv],
               ie_hint=dict(hint, candidate="no", category=None, reason="정상운전 범위 안에서 보상됨")),
        _entry("c4", "approved", cause="범주 없는 원인", safeguards=[psv], ie_hint=dict(hint, category=None)),
        _entry("p1", "proposed", cause="제안만-원인"),
    ])
    b1 = next(e for e in cells[(single, "D02")]["entries"] if e["entry_id"] == "b1")
    cells[(single, "D02")]["entries"].append(dict(copy.deepcopy(b1), entry_id="b1c", status="approved",
                                                  cause="=SUM(A1:A9)", consequence="%s 와 %s 확인" % (PATH, KEY)))
    assert res.validate(r, ns) == []
    return r, ns, pg


def all_strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, list):
        for v in x:
            yield from all_strings(v)
    elif isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from all_strings(v)


def all_keys(x):
    if isinstance(x, list):
        for v in x:
            yield from all_keys(v)
    elif isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from all_keys(v)


def entries_by_status(r):
    out = {}
    for c in r["cells"]:
        for e in c["entries"]:
            out[e["entry_id"]] = e
    return out


class IeBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-ie-")
        self.r, self.ns, self.pg = ie_sample()
        self.entries = entries_by_status(self.r)
        self.b = ib.build_bundle(self.r, self.ns, self.pg, NOW)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def export(self):
        xlsx, js = ix.export(os.path.join(self.tmp, ix.default_stem("P 1", NOW) + ".xlsx"), self.b)
        return openpyxl.load_workbook(xlsx), js

    def rows(self, wb, sheet):
        ws = wb[sheet]
        head = [c.value for c in ws[1]]
        return [dict(zip(head, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]

    def test_sheets_and_headers_match_example(self):
        wb, _ = self.export()
        self.assertEqual(wb.sheetnames, list(EXPECTED))
        for name, head in EXPECTED.items():
            self.assertEqual([c.value for c in wb[name][1]], head, name)

    def test_export_writes_xlsx_and_json_with_same_stem(self):
        _, js = self.export()
        self.assertEqual(os.path.basename(js), "IE-P_1-20261108-1200.json")
        self.assertTrue(os.path.isfile(js[:-5] + ".xlsx"))
        with open(js, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), ib.dumps(self.b))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["IE-P_1-20261108-1200.json", "IE-P_1-20261108-1200.xlsx"])

    def test_every_row_traces_to_an_approved_entry(self):
        wb, _ = self.export()
        approved = {k for k, e in self.entries.items() if e["status"] == "approved"}
        for sheet, col in (("IE 후보", "출처 항목 ID"), ("추적표", "출처 항목 ID"), ("품질 경고", "대상")):
            rows = self.rows(wb, sheet)
            self.assertTrue(rows, sheet)
            self.assertTrue(all(x[col] in approved for x in rows), sheet)
        self.assertEqual({x["출처 항목 ID"] for x in self.rows(wb, "IE 후보")}, approved)
        self.assertEqual((self.b["source"]["approved_entries"], self.b["source"]["left_out_unapproved"]),
                         (len(approved), len(self.entries) - len(approved)))

    def test_unapproved_entries_appear_nowhere(self):
        wb, _ = self.export()
        cells = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None]
        strings = list(all_strings(self.b))
        for eid, e in self.entries.items():
            if e["status"] == "approved":
                continue
            self.assertFalse(eid in strings or eid in cells, eid)
            self.assertFalse(any(e["cause"] in s for s in strings + cells), e["cause"])

    def test_no_hazop_risk_or_recommendation(self):
        wb, _ = self.export()
        self.assertFalse({"severity", "frequency", "risk", "recommendation"} & set(all_keys(self.b)))
        cells = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None]
        for text in ["권고 a1", "권고 c1", "4 조건부 수용", "조건부 수용"]:
            self.assertFalse(any(text in s for s in cells + list(all_strings(self.b))), text)

    def test_same_input_same_json_and_ids_new_time_changes_only_created_at(self):
        again = ib.build_bundle(copy.deepcopy(self.r), copy.deepcopy(self.ns), self.pg, NOW)
        self.assertEqual(ib.dumps(again), ib.dumps(self.b))
        later = ib.build_bundle(self.r, self.ns, self.pg, LATER)
        self.assertEqual(later["created_at"], LATER)
        self.assertEqual(dict(later, created_at=NOW), self.b)
        self.assertEqual([c["candidate_id"] for c in self.b["candidates"]],
                         ["IEC-%03d" % i for i in range(1, len(self.b["candidates"]) + 1)])

    def test_formula_path_and_key_text_is_safe(self):
        wb, js = self.export()
        with open(js, encoding="utf-8") as fh:
            text = fh.read()
        cells = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row]
        for needle in (KEY, "Users", "secret"):
            self.assertNotIn(needle, text)
            self.assertFalse(any(needle in str(c.value) for c in cells if c.value is not None), needle)
        self.assertTrue(all(c.data_type != "f" for c in cells))
        b1c = next(x for x in self.rows(wb, "IE 후보") if x["출처 항목 ID"] == "b1c")
        self.assertEqual(b1c["원인"], "=SUM(A1:A9)")
        self.assertEqual(b1c["비완화 결과"], "[비완화 여부 미확인] [가림] 와 [가림] 확인")

    def test_candidate_rows_read_like_the_example(self):
        wb, _ = self.export()
        rows = {x["출처 항목 ID"]: x for x in self.rows(wb, "IE 후보")}
        c1 = rows["c1"]
        self.assertEqual((c1["판정"], c1["정상운전 교란"], c1["안전기능 도전"], c1["도전받는 안전기능"]),
                         ("후보", "예", "예", "2차측 열제거"))
        self.assertEqual((c1["원인 유형"], c1["고장모드"], c1["일반 범주 제안"], c1["작성"], c1["⑤ 상태"]),
                         ("기기 고장", "FTR", "LOMFW", "사람", "승인"))
        self.assertEqual(c1["원인 위치"], "SNP-M-101-E, 대상 없음(재확인): graph-SNP-M-999#X")
        self.assertEqual(c1["안정 참조"], "graph-SNP-M-101#E, graph-SNP-M-999#X")
        self.assertEqual(c1["비완화 결과"], "급수가 끊겨 열제거 상실")
        self.assertEqual((c1["식별 기법"], c1["그룹 ID"]), ("HAZOP", None))
        a1 = rows["a1"]
        self.assertEqual((a1["판정"], a1["원인 유형"], a1["일반 범주 제안"], a1["제외·보류 사유"], a1["작성"]),
                         ("보류", "미확인", "미분류", "초기사건 판정 전", None))
        self.assertEqual(a1["비완화 결과"], "[비완화 여부 미확인] 결과")
        self.assertEqual((rows["c3"]["판정"], rows["c3"]["제외·보류 사유"]), ("제외", "정상운전 범위 안에서 보상됨"))
        self.assertEqual(rows["c2"]["작성"], "AI 초안")
        ws = wb["IE 후보"]
        fills = {ws.cell(row=r, column=17).value: ws.cell(row=r, column=1).fill.fgColor.rgb
                 for r in range(2, ws.max_row + 1)}
        self.assertEqual(fills["c2"][-6:], "EEF0F2")
        self.assertNotEqual(fills["c1"][-6:], "EEF0F2")
        self.assertEqual(ws.cell(row=1, column=1).fill.fgColor.rgb[-6:], "E2EDFB")

    def test_trace_rows(self):
        wb, _ = self.export()
        c1 = next(x for x in self.rows(wb, "추적표") if x["출처 항목 ID"] == "c1")
        node = next(c["node_id"] for c in self.b["candidates"] if c["entry_id"] == "c1")
        self.assertEqual(c1["구간·편차"], "%s · 온도 높음" % node)
        self.assertEqual(c1["근거 KG 경로"], "SNP-M-101-E(101) → SNP-M-102-E(102)")
        self.assertEqual(c1["출처 문서"], "DOC-9 (§3.2)")
        self.assertEqual((c1["판정"], c1["그룹 ID"], c1["표제 ID"], c1["ES ID"]), ("후보", None, None, None))

    def test_completeness_follows_table_and_shows_gaps(self):
        wb, _ = self.export()
        rows = self.rows(wb, "완전성 대조")
        codes = [c["code"] for c in res.ie_categories()]
        self.assertEqual([x["범주 코드"] for x in rows], codes + ["미분류"])
        by = {x["범주 코드"]: x for x in rows}
        ids = {c["entry_id"]: c["candidate_id"] for c in self.b["candidates"]}
        self.assertEqual((by["LOMFW"]["상태"], by["LOMFW"]["후보 수"], by["LOMFW"]["사유·처리"]),
                         ("대응 있음", 1, ids["c1"]))
        self.assertEqual((by["LOIA"]["상태"], by["LOIA"]["후보 수"], by["LOIA"]["사유·처리"]),
                         ("공백", 1, "%s 보류(판정 대기)" % ids["c2"]))
        self.assertEqual((by["TRANS"]["상태"], by["TRANS"]["후보 수"]), ("공백", 0))
        self.assertEqual(by["LOMFW"]["기준표 출처"], "INL 2015 IE 범주")
        loose = by["미분류"]
        self.assertEqual((loose["상태"], loose["후보 수"]), ("미분류", 3))  # a1·b1c 보류, c4 후보. c3 제외는 세지 않음
        self.assertNotIn(ids["c3"], loose["사유·처리"])

    def test_ai_draft_only_coverage_is_marked_and_unknown_code_counts_as_unclassified(self):
        r = copy.deepcopy(self.r)
        for c in r["cells"]:
            for e in c["entries"]:
                if e["entry_id"] == "c1":
                    e["ie_hint"] = dict(e["ie_hint"], origin="ai_draft", status="draft")
                if e["entry_id"] == "c4":
                    e["ie_hint"] = dict(e["ie_hint"], category="OLDCODE")
        b = ib.build_bundle(r, self.ns, self.pg, NOW)
        ids = {c["entry_id"]: c["candidate_id"] for c in b["candidates"]}
        by = {x["code"]: x for x in b["completeness"]}
        self.assertEqual((by["LOMFW"]["status"], by["LOMFW"]["note"]), ("covered", "AI 초안 판정만 있음: " + ids["c1"]))
        self.assertIn("%s(기준표에 없는 코드 OLDCODE)" % ids["c4"], by[None]["note"])
        self.assertEqual(sum(x["candidate_count"] for x in b["completeness"]),
                         sum(c["judgement"] in ("yes", "undecided") for c in b["candidates"]))

    def test_source_ref_keeps_only_version_fields(self):
        r = copy.deepcopy(self.r)
        r["study_nodes_ref"] = dict(r["study_nodes_ref"], recommendation="권고 누출", extra={PATH: KEY})
        b = ib.build_bundle(r, self.ns, self.pg, NOW)
        self.assertEqual(set(b["source"]["study_nodes_ref"]), {"graph_version", "confirmed_at"})

    def test_same_bundle_same_workbook_metadata(self):
        a, b = ix.build_workbook(self.b), ix.build_workbook(copy.deepcopy(self.b))
        self.assertEqual((a.properties.created, a.properties.modified), (b.properties.created, b.properties.modified))
        self.assertEqual(a.properties.created.strftime("%Y-%m-%dT%H:%M:%SZ"), NOW)

    def test_quality_warnings_only_for_approved(self):
        wb, _ = self.export()
        rows = self.rows(wb, "품질 경고")
        got = {(x["경고"], x["대상"], x["근거"]) for x in rows}
        self.assertIn(("완화 결과로 적힘", "c2", "PSAM14 382·383"), got)
        self.assertIn(("작동 방식 미확인", "c2", "PSAM14 383"), got)
        self.assertNotIn("c1", {x["대상"] for x in rows})
        self.assertEqual({w["kind"] for w in self.b["warnings"]}, set(res.QUALITY_KINDS))

    def test_guide_sheet(self):
        wb, _ = self.export()
        guide = {x["항목"]: x["내용"] for x in self.rows(wb, "읽는 법")}
        self.assertEqual(guide["만든 시각"], "2026-11-08 12:00 KST")
        self.assertIn("'승인' 항목 %d건" % self.b["source"]["approved_entries"], guide["입력"])
        self.assertIn("%d건" % self.b["source"]["left_out_unapproved"], guide["넣지 않은 항목"])
        self.assertEqual(guide["시트"], " / ".join(EXPECTED))
        self.assertIn("⑥ 화면", guide["다음 단계"])


class IeBundleCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-ie-cli-")
        self.r, self.ns, self.pg = ie_sample()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, doc):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        return path

    def run_cli(self, results):
        from scripts import export_ie_bundle as cli
        out = os.path.join(self.tmp, "out")
        code = cli.main(["--results", self.write("r.json", results), "--nodes", self.write("n.json", self.ns),
                         "--graph", self.write("g.json", self.pg), "--out", out, "--now", NOW])
        return code, out

    def test_round_trip(self):
        code, out = self.run_cli(self.r)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(out)), ["IE-P-20261108-1200.json", "IE-P-20261108-1200.xlsx"])
        with open(os.path.join(out, "IE-P-20261108-1200.json"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), ib.dumps(ib.build_bundle(self.r, self.ns, self.pg, NOW)))

    def test_mismatched_node_set_is_refused(self):
        r = dict(copy.deepcopy(self.r), graph_id="graph-OTHER")
        code, out = self.run_cli(r)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(out))

    def test_invalid_results_are_refused(self):
        r = copy.deepcopy(self.r)
        r["cells"].append(copy.deepcopy(next(c for c in r["cells"] if c["entries"])))
        code, out = self.run_cli(r)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(out))

    def test_no_approved_entries_writes_nothing(self):
        r = copy.deepcopy(self.r)
        for c in r["cells"]:
            for e in c["entries"]:
                e["status"] = "revised" if e["status"] == "approved" else e["status"]
        code, out = self.run_cli(r)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(out))


class IeBundleScreenTest(unittest.TestCase):
    """⑤ 화면의 IE 인계 묶음 내보내기(버튼·명령 팔레트·토스트). 합성 프로젝트를 임시 작업 루트에 둔다."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qapp = QApplication.instance() or QApplication(["test"])

    def setUp(self):
        from tests.test_project_graph import cont, sheet
        self.tmp = tempfile.mkdtemp(prefix="hazop-ie-ui-")
        self._env = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = self.tmp
        for g in (sheet("SNP-M-101", cont("C1", "TO SNP-M-102\nL-1")),
                  sheet("SNP-M-102", cont("C1", "FROM SNP-M-101\nL-1"))):
            d = os.path.join(self.tmp, "출력", "그래프", g["source"]["drawing_number"])
            os.makedirs(d)
            with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as fh:
                json.dump(g, fh)

    def tearDown(self):
        if self._env is None:
            os.environ.pop("HAZOP_WORK_ROOT", None)
        else:
            os.environ["HAZOP_WORK_ROOT"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def screen(self, status):
        from hazop.app import project_ctx
        from hazop.app.screens.results import ResultsScreen
        from hazop.study import nodes as sn
        from tests.test_results_project_ui import AT, StubApp
        ctx = project_ctx.load("SNP-M-102")
        sn.save(sn.confirm(ctx.load_set()[0], ctx.pg, "EJ", at=AT))
        app = StubApp()
        scr = ResultsScreen(app)
        self.addCleanup(scr.deleteLater)
        scr.combo.blockSignals(True)
        scr.combo.addItems(["SNP-M-101", "SNP-M-102"])
        scr.combo.setCurrentText("SNP-M-102")
        scr.combo.blockSignals(False)
        scr._load()
        doc = json.loads(json.dumps(scr.results))
        doc["cells"][0].update(state="analyzed", entries=[
            {"entry_id": "E1", "cause": "SNP-M-101-E 누설", "consequence": "c", "safeguards": [], "recommendation": "r",
             "severity": 4, "frequency": 3, "risk": 5, "origin": "ai_draft", "status": status}])
        scr.set_results(doc)
        return app, scr

    def test_button_palette_and_both_files(self):
        app, scr = self.screen("approved")
        self.assertTrue(scr.export_btn.isEnabled())
        self.assertIn("IE 인계 묶음 내보내기…", [a.text() for a in scr.export_btn.menu().actions()])
        self.assertIn("IE 인계 묶음 내보내기…", [c[0] for c in scr.commands()])
        out = os.path.join(self.tmp, "export", "ie.xlsx")
        os.makedirs(os.path.dirname(out))
        self.assertEqual(scr.export_ie_bundle(path=out), out)
        self.assertEqual(sorted(os.listdir(os.path.dirname(out))), ["ie.json", "ie.xlsx"])
        self.assertIn("후보 1건", app.toasts[-1])
        self.assertEqual(app.toast_actions, ["열기", "폴더 열기"])
        with open(os.path.join(self.tmp, "export", "ie.json"), encoding="utf-8") as fh:
            self.assertEqual([c["entry_id"] for c in json.load(fh)["candidates"]], ["E1"])

    def test_no_approved_entry_writes_nothing(self):
        app, scr = self.screen("proposed")
        out = os.path.join(self.tmp, "export", "ie.xlsx")
        self.assertIsNone(scr.export_ie_bundle(path=out))
        self.assertIn("승인한 항목이 없어", app.messages[-1])
        self.assertFalse(os.path.exists(os.path.dirname(out)))


if __name__ == "__main__":
    unittest.main()
