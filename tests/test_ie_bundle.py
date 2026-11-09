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
from hazop.ie import model  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_export import KEY, NOW, _entry, sample  # noqa: E402

# §3.4 예시 Excel(make_ie_example.py)의 시트 순서·머리글 그대로. 예시 파일이 있으면 그것과도 맞춰 본다(IeExampleTest)
EXAMPLE_XLSX = os.environ.get("HAZOP_IE_EXAMPLE_XLSX", "")  # 설계 §3.4 예시 파일(없으면 IeExampleTest를 건너뜀)
EXPECTED = {
    "읽는 법": ["항목", "내용"],
    "IE 후보": ["후보 ID", "판정", "정상운전 교란", "안전기능 도전", "도전받는 안전기능", "원인", "원인 유형", "원인 위치",
              "고장모드", "구간", "편차", "비완화 결과", "일반 범주 제안", "그룹 ID", "제외·보류 사유", "식별 기법",
              "출처 항목 ID", "안정 참조", "작성", "⑤ 상태"],
    "IE 그룹": ["그룹 ID", "그룹 이름", "정의", "일반 범주", "범주 출처", "대표 후보", "대표 선정 이유", "소속 후보", "후보 수",
              "플랜트 응답", "영향받는 완화계통", "지원계통 IE", "표제 후보", "최종상태 후보", "작성", "상태", "PRA IE 이름",
              "성공기준", "빈도 근거"],
    "사건수목 표제 후보": ["표제 ID", "표제 이름(제안)", "출처 보호수단", "구현 대상", "관련 계통", "역할", "작동 방식",
                    "운전원 조치 단서", "적용 그룹", "출처 항목 ID", "작성", "PRA 표제 이름"],
    "최종상태 후보": ["ES ID", "비완화 결과(대표 문장)", "결과 범주 제안", "관련 그룹", "출처 항목 수", "작성", "PRA 최종상태"],
    "기본사건 후보": ["BE ID", "앱 제안 이름", "기기 태그", "기기 종류", "계통", "고장모드 코드", "고장모드 설명", "정상 위치",
                "고장 위치", "관련 표제·후보", "출처", "작성", "PRA 기본사건 이름"],
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


def synced(r):
    """⑥ 저장 파일이 없을 때의 문서: 빈 문서를 ⑤ 결과와 맞춘 것."""
    return model.sync(model.empty("P"), r, at=NOW)


def build(r, ns, pg, now=NOW, doc=None):
    return ib.build_bundle(r, ns, pg, doc if doc is not None else synced(r), now)


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
        self.b = build(self.r, self.ns, self.pg)

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
        again = build(copy.deepcopy(self.r), copy.deepcopy(self.ns), self.pg)
        self.assertEqual(ib.dumps(again), ib.dumps(self.b))
        later = build(self.r, self.ns, self.pg, LATER)
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
        b = build(r, self.ns, self.pg)
        ids = {c["entry_id"]: c["candidate_id"] for c in b["candidates"]}
        by = {x["code"]: x for x in b["completeness"]}
        self.assertEqual((by["LOMFW"]["status"], by["LOMFW"]["note"]), ("covered", "AI 초안 판정만 있음: " + ids["c1"]))
        self.assertIn("%s(기준표에 없는 코드 OLDCODE)" % ids["c4"], by[None]["note"])
        self.assertEqual(sum(x["candidate_count"] for x in b["completeness"]),
                         sum(c["judgement"] in ("yes", "undecided") for c in b["candidates"]))

    def test_source_ref_keeps_only_version_fields(self):
        r = copy.deepcopy(self.r)
        r["study_nodes_ref"] = dict(r["study_nodes_ref"], recommendation="권고 누출", extra={PATH: KEY})
        b = build(r, self.ns, self.pg)
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
        self.assertEqual(guide["시트"], " / ".join(list(EXPECTED)[1:]))
        self.assertNotIn("다음 단계", guide)
        self.assertIn("같은 원인은 같은 ID", guide["ID 규칙"])


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
            self.assertEqual(fh.read(), ib.dumps(build(self.r, self.ns, self.pg)))

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


class IeExampleTest(unittest.TestCase):
    """§3.4 예시 Excel과 시트 순서(0~9)·머리글이 같은지. 예시 파일이 없으면 위에 적어 둔 EXPECTED로만 본다."""

    def test_expected_matches_example_file(self):
        if not os.path.isfile(EXAMPLE_XLSX):
            self.skipTest("예시 Excel 없음: %s" % EXAMPLE_XLSX)
        wb = openpyxl.load_workbook(EXAMPLE_XLSX, read_only=True)
        self.assertEqual(wb.sheetnames, list(EXPECTED))
        for name in ("IE 그룹", "사건수목 표제 후보", "최종상태 후보", "기본사건 후보"):
            self.assertEqual([c.value for c in next(wb[name].iter_rows(max_row=1))], EXPECTED[name], name)

    def test_sheet_order_and_widths_follow_columns(self):
        self.assertEqual(ix.SHEETS, tuple(EXPECTED))
        for name, cols in (("IE 그룹", ix.GROUP_COLUMNS), ("사건수목 표제 후보", ix.HEADING_COLUMNS),
                           ("최종상태 후보", ix.END_STATE_COLUMNS), ("기본사건 후보", ix.BASIC_EVENT_COLUMNS)):
            self.assertEqual([t for t, _ in cols], EXPECTED[name], name)


class IeBundleP3Test(unittest.TestCase):
    """⑥ 문서에서 오는 시트 2~5와 그룹 정보(그룹 ID·표제·최종상태·완전성 대응 그룹·사람 판정)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-ie-p3-")
        self.r, self.ns, self.pg = ie_sample()
        doc = model.suggest(synced(self.r), self.r, self.pg, at=NOW)
        self.gid = next(g for g, v in doc["groups"].items() if v["categories"] == ["LOMFW"])
        self.h = doc["groups"][self.gid]["heading_ids"][0]
        doc = model.accept(doc, ("heading", self.h), at=NOW)
        doc, self.loose = model.create_group(doc, "사람이 만든 빈 그룹", at=NOW)
        doc = model.set_coverage(doc, "LOCHS", "not_applicable", "복수기 없음(가상)", "김검토", at=NOW)
        doc = model.set_coverage(doc, "LOOP", "other_method", "전력계통은 FMEA로 확인", "김검토", at=NOW)
        self.doc = doc
        self.b = build(self.r, self.ns, self.pg, doc=doc)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rows(self, sheet):
        wb = openpyxl.load_workbook(ix.export(os.path.join(self.tmp, "ie.xlsx"), self.b)[0])
        ws = wb[sheet]
        head = [c.value for c in ws[1]]
        return ws, [dict(zip(head, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]

    def test_group_sheet(self):
        ws, rows = self.rows("IE 그룹")
        by = {x["그룹 ID"]: x for x in rows}
        g = by[self.gid]
        c1 = next(c["candidate_id"] for c in self.b["candidates"] if c["entry_id"] == "c1")
        self.assertEqual((g["일반 범주"], g["범주 출처"], g["대표 후보"], g["소속 후보"], g["후보 수"]),
                         ("LOMFW", "INL 2015 IE 범주", c1, c1, 1))
        self.assertEqual((g["표제 후보"], g["작성"], g["상태"]), (self.h, "AI 초안", "초안"))
        self.assertEqual((by[self.loose]["작성"], by[self.loose]["후보 수"]), ("사람", 0))
        fills = [ws.cell(row=1, column=c).fill.fgColor.rgb[-6:] for c in range(1, ws.max_column + 1)]
        self.assertEqual(fills, ["E2EDFB"] * 16 + ["FDF0D2"] * 3)
        self.assertEqual([ws.cell(row=r, column=17).value for r in range(2, ws.max_row + 1)], [None] * len(rows))

    def test_candidate_and_trace_carry_group(self):
        c1 = next(c for c in self.b["candidates"] if c["entry_id"] == "c1")
        t1 = next(t for t in self.b["trace"] if t["entry_id"] == "c1")
        self.assertEqual((c1["group_id"], t1["group_id"], t1["top_event_ids"]), (self.gid, self.gid, [self.h]))
        self.assertEqual(t1["end_state_ids"], self.doc["groups"][self.gid]["end_state_ids"])

    def test_heading_end_state_and_basic_event_sheets(self):
        _, hs = self.rows("사건수목 표제 후보")
        self.assertEqual([(x["표제 ID"], x["표제 이름(제안)"], x["작동 방식"], x["적용 그룹"], x["출처 항목 ID"], x["작성"])
                          for x in hs], [(self.h, "PSV", "자체작동", self.gid, "c1", "사람")])
        _, es = self.rows("최종상태 후보")
        self.assertEqual([(x["비완화 결과(대표 문장)"], x["결과 범주 제안"], x["관련 그룹"], x["출처 항목 수"], x["작성"])
                          for x in es], [("급수가 끊겨 열제거 상실", "미분류", self.gid, 1, "AI 초안")])
        _, be = self.rows("기본사건 후보")
        ftr = next(x for x in be if x["고장모드 코드"] == "FTR")
        self.assertEqual((ftr["기기 태그"], ftr["출처"], ftr["작성"]), ("SNP-M-101-E", "HAZOP 원인", "AI 초안"))
        self.assertIn(next(c["candidate_id"] for c in self.b["candidates"] if c["entry_id"] == "c1"), ftr["관련 표제·후보"])

    def test_completeness_uses_groups_and_human_dispositions(self):
        by = {x["code"]: x for x in self.b["completeness"]}
        self.assertEqual(by["LOMFW"]["group_id"], self.gid)
        self.assertEqual((by["LOCHS"]["status"], by["LOCHS"]["note"]), ("not_applicable", "해당 없음(설계 특성): 복수기 없음(가상)"))
        self.assertEqual((by["LOOP"]["status"], by["LOOP"]["note"]), ("gap", "다른 기법으로 확인 예정: 전력계통은 FMEA로 확인"))
        _, rows = self.rows("완전성 대조")
        self.assertEqual(next(x for x in rows if x["범주 코드"] == "LOCHS")["상태"], "해당 없음")

    def test_group_status_is_effective_not_stored(self):
        doc = model.accept(self.doc, ("member", self.b["groups"][0]["members"][0]), at=NOW)
        for e in doc["groups"][self.gid]["end_state_ids"]:
            doc = model.accept(doc, ("end_state", e), at=NOW)
        doc = model.accept(doc, ("group", self.gid), at=NOW)
        doc = model.confirm(doc, self.gid, self.r, "김검토", at=NOW)
        self.assertEqual(next(g for g in build(self.r, self.ns, self.pg, doc=doc)["groups"]
                              if g["group_id"] == self.gid)["status"], "confirmed")
        r = res.edit_entry(self.r, *next((c["node_id"], c["deviation_id"], "c1") for c in self.b["candidates"]
                                         if c["entry_id"] == "c1"), {"cause": "바뀐 원인"}, at=NOW)
        r = res.set_status(r, *next((c["node_id"], c["deviation_id"], "c1") for c in self.b["candidates"]
                                    if c["entry_id"] == "c1"), "approved", at=NOW)
        g = next(g for g in build(r, self.ns, self.pg, doc=doc)["groups"] if g["group_id"] == self.gid)
        self.assertEqual(g["status"], "draft", "저장 상태는 확정이어도 ⑤ 내용이 바뀌면 묶음에는 초안으로 나간다")

    def where(self, r, entry_id):
        f = model.entry_facts(r)[model.key_of(r["graph_id"], entry_id)]
        return f["node_id"], f["deviation_id"], entry_id

    def test_unapproved_member_is_held_out_of_members_and_noted(self):
        iec = {model.entry_of_key(c["key"]): i for i, c in self.doc["candidates"].items()}
        doc, gid = model.create_group(self.doc, "사람 그룹", [iec["c4"], iec["b1c"]], at=NOW)
        r = res.set_status(self.r, *self.where(self.r, "b1c"), "revised", at=NOW)
        self.b = build(r, self.ns, self.pg, doc=model.sync(doc, r, at=NOW))
        g = next(x for x in self.b["groups"] if x["group_id"] == gid)
        self.assertEqual((g["members"], g["held_members"], g["member_count"]), ([iec["c4"]], [iec["b1c"]], 1))
        ws, rows = self.rows("IE 그룹")
        row = next(x for x in rows if x["그룹 ID"] == gid)
        self.assertEqual((row["소속 후보"], row["후보 수"]), (iec["c4"], 1))
        self.assertEqual(row["정의"], "승인 해제로 빠진 후보: " + iec["b1c"])
        self.assertEqual(ws.max_column, len(ix.GROUP_COLUMNS), "예시 Excel 열을 늘리지 않음")

    def test_records_without_an_approved_source_are_left_out(self):
        doc, hid = model.add_heading(self.doc, self.gid, {"name": "운전원 수동 급수"}, at=NOW)
        r = res.set_status(self.r, *self.where(self.r, "c1"), "revised", at=NOW)
        b = build(r, self.ns, self.pg, doc=model.sync(doc, r, at=NOW))
        self.assertEqual(([h["heading_id"] for h in b["top_events"]], b["end_states"], b["basic_events"]),
                         ([hid], [], []), "출처 없이 사람이 쓴 표제만 남음")
        g = next(x for x in b["groups"] if x["group_id"] == self.gid)
        self.assertEqual((g["members"], g["heading_ids"], g["end_state_ids"]), ([], [hid], []))
        text = ib.dumps(b)
        gone = [self.h] + list(doc["end_states"]) + list(doc["basic_events"])
        self.assertEqual([x for x in gone if '"%s"' % x in text], [], "빠진 기록의 ID가 묶음 어디에도 없음")

    def test_end_state_with_a_source_lacking_unmitigated_basis_is_marked(self):
        r = copy.deepcopy(self.r)
        c4 = entries_by_status(r)["c4"]
        c4["ie_hint"]["category"] = "LOMFW"
        c4["consequence"] = "급수가 끊겨 열제거 상실"  # c1과 같은 문장이지만 비완화 기준 표시가 없음
        doc = model.suggest(synced(r), r, self.pg, at=NOW)
        es = next(iter(doc["end_states"].values()))
        self.assertEqual(len(es["source_keys"]), 2)
        self.b = build(r, self.ns, self.pg, doc=doc)
        self.assertEqual([e["text"] for e in self.b["end_states"]], [ix.BASIS_UNKNOWN_PREFIX + "급수가 끊겨 열제거 상실"])
        _, rows = self.rows("최종상태 후보")
        self.assertEqual(rows[0]["비완화 결과(대표 문장)"], "[비완화 여부 미확인] 급수가 끊겨 열제거 상실")

    def test_split_and_deleted_groups_are_listed_as_retired(self):
        doc = model.delete_group(self.doc, self.loose, at=NOW)
        b = build(self.r, self.ns, self.pg, doc=doc)
        self.assertEqual(b["retired"], [{"id": self.loose, "status": "deleted", "split_into": []}])
        self.assertNotIn(self.loose, [g["group_id"] for g in b["groups"]])
        guide = dict(ix.guide_rows(b))
        self.assertIn("%s(삭제)" % self.loose, guide["나뉨·삭제 그룹"])


class IeKgProjectionTest(unittest.TestCase):
    """지식그래프 검토 층의 ⑥ 투영(kg/screen.ie_view). ⑥ 파일이 원본이고 그래프는 투영이다."""

    def test_projection_uses_only_registered_types_and_relations(self):
        from hazop.kg import screen
        from hazop.kg.schema import REGISTRY
        from tests.test_study_span import two_sheets
        r, ns, pg = ie_sample()
        doc = model.suggest(synced(r), r, pg, at=NOW)
        drawing = two_sheets()[0]  # SNP-M-101: c1의 원인 위치(graph-SNP-M-101#E)가 있는 도면
        nodes, links, info = screen.study_view({"node_set": ns, "results": r, "note": None,
                                                "ie": build(r, ns, pg, doc=doc)}, drawing)
        classes = {c["id"] for c in REGISTRY.data["classes"]}
        relations = {x["id"] for x in REGISTRY.data["relations"]}
        self.assertTrue({n["type"] for n in nodes} <= classes, {n["type"] for n in nodes} - classes)
        self.assertTrue({x["kind"] for x in links} <= relations, {x["kind"] for x in links} - relations)
        kinds = {x["kind"] for x in links}
        self.assertTrue({"derived_from", "member_of", "corresponds_to", "pivotal", "leads_to", "heading_from",
                         "basic_event_at"} <= kinds, kinds)
        ids = {n["id"] for n in nodes}
        self.assertTrue(all(x["s"] in ids for x in links if x["kind"] != "basic_event_at"))
        self.assertTrue(all(not n["v5"] for n in nodes) and info["ie"]["groups"] >= 1)
        self.assertTrue(next(n for n in nodes if n["type"] == "ie_group")["draft"])
        self.assertEqual(screen.study_view({"node_set": ns, "results": r, "note": None}, drawing)[2]["ie"], None)


if __name__ == "__main__":
    unittest.main()
