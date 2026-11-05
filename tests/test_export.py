"""Excel 워크시트 출력 테스트 (기획서/인터페이스.md §6, §8 Excel 행). 실행: python -m unittest discover -s tests -t .

입력: tests/run_fixture.py가 임시 폴더에 고정 응답으로 새로 만든 실행(scripts/analyze.py 하위 프로세스)을
임시 폴더에 복사해 쓴다. 검토 기록·출력은 임시 폴더에만 쓴다. 결과는 openpyxl로 다시 읽어 검사한다. 네트워크 사용 없음.
"""

import glob
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest import mock

import openpyxl

from hazop import review as rv
from hazop.export import FIRST_DATA_ROW, WORKSHEET_COLUMNS, ExportError, export_worksheet
from tests.run_fixture import REPO_ROOT, fresh_run_dir, python_exe

REGION = "region-SNP-M-102-pzr"
WHO = "검토자A"
T_EARLY = "2026-11-04T01:00:00Z"
T_LATE = "2026-11-04T16:30:00Z"   # KST 2026-11-05 01:30
NOW = "2026-11-05T00:00:00Z"
KEYS = [k for k, _h, _s in WORKSHEET_COLUMNS]
COL = {k: i for i, k in enumerate(KEYS, 1)}
LABEL = {"accept": "수용", "modify": "수정", "reject": "기각", "defer": "보류", None: "미검토"}


def read_rows(ws):
    """HAZOP 워크시트 시트의 데이터 행 → [{열 키: 값}] (셀 객체도 '_cells'로 함께)."""
    out = []
    for r in range(FIRST_DATA_ROW, ws.max_row + 1):
        cells = [ws.cell(row=r, column=c) for c in range(1, len(KEYS) + 1)]
        if cells[0].value is None:
            continue
        row = {k: c.value for k, c in zip(KEYS, cells)}
        row["_cells"] = dict(zip(KEYS, cells))
        out.append(row)
    return out


class ExportTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = fresh_run_dir()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-export-")
        self.store = os.path.join(self.tmp, "store")
        self.out = os.path.join(self.tmp, "워크시트")
        self.run_dir = os.path.join(self.tmp, "runs", os.path.basename(self.src))
        shutil.copytree(self.src, self.run_dir)
        self.run = rv.open_run(self.run_dir)
        self.doc = self.run["doc"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # 도우미 --------------------------------------------------------------
    def rc(self, sev, f):
        return rv.make_risk_confirmation(self.run, sev, "강도 근거", f, f, "빈도 근거")

    def scen(self, cid):
        return [s["scenario_id"] for s in self.doc["scenarios"] if s["candidate_id"] == cid]

    def scenario(self, sid):
        return next(s for s in self.doc["scenarios"] if s["scenario_id"] == sid)

    def dics_of(self, sid):
        return [d["dic_id"] for d in self.doc["design_improvement_candidates"] if d["scenario_id"] == sid]

    def save_d09(self, revised=None, recommendation="권고 %s", memo="가압기 설계압력 자료 요청"):
        """d09: 01 수정(부분), 02 수용, 03 보류(AI 제안 위험도 4), 04 기각, 05 수용. 설계보완 후보는 기각 연결분 외 수용."""
        s = self.scen("deviation-p86-d09")
        decs = [rv.scenario_decision(self.run, s[0], "modify", "결과 정정", WHO,
                                     revised=revised or {"consequence": "가압기 압력 상승(정정)"},
                                     risk_confirmation=self.rc(2, 1), now=T_LATE),
                rv.scenario_decision(self.run, s[1], "accept", "수용", WHO, risk_confirmation=self.rc(3, 2), now=T_LATE),
                rv.scenario_decision(self.run, s[2], "defer", "자료 대기", WHO, now=T_LATE),
                rv.scenario_decision(self.run, s[3], "reject", "도면 범위 밖", WHO, now=T_LATE),
                rv.scenario_decision(self.run, s[4], "accept", "수용", WHO, risk_confirmation=self.rc(4, 1), now=T_LATE)]
        ddecs = [rv.dic_decision(self.run, d, "accept", "권고 필요", WHO, recommendation=recommendation % d, now=T_LATE)
                 for sid in (s[0], s[1], s[2], s[4]) for d in self.dics_of(sid)]
        memos = [rv.memo_record("memo-001", memo, "확인 필요", WHO, ["hold-002"], now=T_LATE)]
        rec = rv.build_review(self.run, "deviation-p86-d09", WHO, "편차 검토 요약", decs, ddecs, memo_records=memos)
        return rv.save_review(self.store, self.run, rec, now=T_LATE)[1]

    def save_d12_defer(self):
        sid, = self.scen("deviation-p86-d12")
        did, = self.dics_of(sid)
        rec = rv.build_review(self.run, "deviation-p86-d12", WHO, "요약",
                              [rv.scenario_decision(self.run, sid, "defer", "대기", WHO, now=T_EARLY)],
                              [rv.dic_decision(self.run, did, "defer", "대기", WHO, now=T_EARLY)])
        return rv.save_review(self.store, self.run, rec, now=T_EARLY)[1]

    def save_d01_confirm(self):
        nsc = rv.no_scenario_confirmation("원인 설비 없음 확인", WHO, now=T_EARLY)
        rec = rv.build_review(self.run, "deviation-p86-d01", WHO, "요약", no_scenario=nsc)
        return rv.save_review(self.store, self.run, rec, now=T_EARLY)[1]

    def export(self, scope="all", now=NOW):
        res = export_worksheet(self.run_dir, self.store, self.out, scope=scope, now=now)
        return res, openpyxl.load_workbook(res["path"])

    def records(self):
        return rv.load_run_reviews(self.store, REGION, self.doc["analysis_run_id"])


class TestRowsMatchJson(ExportTestBase):
    """행의 편차·시나리오 ID와 값·상태가 JSON과 일치."""

    def test_rows_ids_values_and_status(self):
        self.save_d09()
        self.save_d12_defer()
        self.save_d01_confirm()
        res, wb = self.export()
        self.assertEqual(wb.sheetnames, ["분석 정보", "전체 편차 후보", "HAZOP 워크시트", "설계보완 후보", "개선 권고",
                                         "자료 요청 메모"])
        rows = read_rows(wb["HAZOP 워크시트"])
        recs = self.records()
        expected = []
        for c in self.doc["candidates"]:
            if c["selection_status"] == "selected":
                sids = self.scen(c["candidate_id"])
                expected += [(c["candidate_id"], s) for s in sids] or [(c["candidate_id"], "시나리오 없음")]
        self.assertEqual([(r["candidate_id"], r["scenario_id"]) for r in rows], expected)
        self.assertEqual([(x["candidate_id"], x["scenario_id"] or "시나리오 없음")
                          for x in res["record"]["rows"]["worksheet"]], expected)
        cands = {c["candidate_id"]: c for c in self.doc["candidates"]}
        for r in rows:
            self.assertEqual(r["deviation"], cands[r["candidate_id"]]["deviation"])
            if r["scenario_id"] == "시나리오 없음":
                nsc = (recs.get(r["candidate_id"]) or {}).get("no_scenario_confirmation")
                self.assertEqual(r["decision"], "시나리오 없음 확인" if nsc else "미검토")
                continue
            s = self.scenario(r["scenario_id"])
            sd = next((d for d in (recs.get(r["candidate_id"]) or {}).get("scenario_decisions", [])
                       if d["scenario_id"] == r["scenario_id"]), None)
            m = rv.merge_display(s, sd)
            self.assertEqual((r["cause"], r["consequence"]), (m["cause"]["value"], m["consequence"]["value"]))
            self.assertEqual(r["value_source"], rv.value_source_text(m))
            self.assertEqual(r["decision"], LABEL[(sd or {}).get("decision")])
            rc = (sd or {}).get("risk_confirmation")
            if rc:
                self.assertEqual((r["frequency"], r["severity"], r["risk"]), (rc["frequency"], rc["severity"], rc["risk"]))
                self.assertEqual(r["risk_name"], rc["risk_name"])
            for g in s["safeguards"] if "safeguards" not in ((sd or {}).get("revised") or {}) else []:
                self.assertIn(g["tag"], r["safeguards"])
        d01 = next(r for r in rows if r["candidate_id"] == "deviation-p86-d01")
        self.assertEqual((d01["scenario_id"], d01["decision"]), ("시나리오 없음", "시나리오 없음 확인"))
        # 전체 편차 후보: 44개, 판단·검토 상태가 JSON·판정 규칙과 같음
        cs = wb["전체 편차 후보"]
        crow = {cs.cell(row=r, column=1).value: [cs.cell(row=r, column=c).value for c in range(1, 9)]
                for r in range(2, cs.max_row + 1)}
        self.assertEqual(list(crow), [c["candidate_id"] for c in self.doc["candidates"]])
        summ = rv.review_summary(self.doc, recs)
        self.assertEqual(crow["deviation-p86-d09"][7], "보류 (deferred)")
        self.assertEqual(crow["deviation-p86-d01"][7], "확정 (confirmed)")
        for cid, st in summ["by_candidate"].items():
            self.assertTrue(crow[cid][7].endswith("(%s)" % st))
        for cid in summ["excluded"]:
            self.assertEqual((crow[cid][5], crow[cid][6]), ("제외", cands[cid]["reason"]))

    def test_partial_modify_matches_requery(self):
        """부분 수정(결과만) 저장 뒤 ⑤ 재조회(merge_display)와 Excel 2–4열·값 출처가 같다."""
        self.save_d09()
        sid = self.scen("deviation-p86-d09")[0]
        saved = rv.load_review(self.store, REGION, self.doc["analysis_run_id"], "deviation-p86-d09")
        sd = next(d for d in saved["scenario_decisions"] if d["scenario_id"] == sid)
        m = rv.merge_display(self.scenario(sid), sd)
        _, wb = self.export()
        row = next(r for r in read_rows(wb["HAZOP 워크시트"]) if r["scenario_id"] == sid)
        self.assertEqual(row["consequence"], "가압기 압력 상승(정정)")
        self.assertEqual((row["cause"], row["consequence"]), (m["cause"]["value"], m["consequence"]["value"]))
        self.assertEqual(row["value_source"], "원인=AI 해석 원안, 결과=사람 수정, 현재안전조치=그래프 확인")
        for g in m["safeguards"]["value"]:
            self.assertIn(g["tag"], row["safeguards"])
        self.assertIn("[적정성 미확인]", row["safeguards"])


class TestAiHypothesis(ExportTestBase):
    """AI 추가 가설: 4열에는 그래프 확인 보호수단만(없으면 '미확인 — …(없음이 아님)'), AI 제시는 추가 열에만."""

    def test_hypothesis_safeguards_only_in_ai_column(self):
        pat = next(x for x in self.doc["scenarios"] if x["candidate_id"] == "deviation-p86-d12")
        sg = [{"node_id": "entity-node-014", "tag": "RC-PSV101", "description": "AI가 제시한 과압 방출",
               "adequacy": "unknown"}]
        hyp = json.loads(json.dumps(pat))
        hyp.update(scenario_id="scenario-p86-d12-h-0000000000", origin="ai_additional_hypothesis", pattern_ref=None,
                   statement_type="additional_hypothesis", safeguards=sg,
                   ai_interpretation=dict(pat.get("ai_interpretation") or {}, cause="AI 가설 원인",
                                          consequence="AI 가설 결과", safeguards=sg))
        self.doc["scenarios"].append(hyp)
        with open(self.run["analysis_path"], "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.doc, fh, ensure_ascii=False, indent=2)
        self.run = rv.open_run(self.run_dir)
        _, wb = self.export()
        row = next(r for r in read_rows(wb["HAZOP 워크시트"]) if r["scenario_id"] == hyp["scenario_id"])
        self.assertEqual(row["safeguards"], "미확인 — 도면에서 확인된 보호수단을 찾지 못함(없음이 아님)")
        self.assertIn("RC-PSV101", row["ai_safeguards"])
        self.assertIn("현재안전조치=그래프 확인", row["value_source"])
        self.assertEqual((row["origin"], row["cause"]), ("AI 추가 가설", "AI 가설 원인"))


class TestFormulaInjection(ExportTestBase):
    def test_formula_like_strings_stay_text(self):
        bad = {"cause": "=1+1", "consequence": "@SUM(A1:A2)"}
        self.save_d09(revised=bad, recommendation="+cmd|' /C calc'!A0 %s", memo="-2+3")
        res, wb = self.export()
        row = next(r for r in read_rows(wb["HAZOP 워크시트"]) if r["scenario_id"] == self.scen("deviation-p86-d09")[0])
        for key, want in (("cause", "=1+1"), ("consequence", "@SUM(A1:A2)")):
            self.assertEqual(row[key], want)
            self.assertEqual(row["_cells"][key].data_type, "s")
        rec_ws = wb["개선 권고"]
        texts = [rec_ws.cell(row=r, column=4) for r in range(2, rec_ws.max_row + 1)]
        self.assertTrue(texts and all(c.value.startswith("+cmd") and c.data_type == "s" for c in texts))
        memo = wb["자료 요청 메모"].cell(row=2, column=4)
        self.assertEqual((memo.value, memo.data_type), ("-2+3", "s"))
        with zipfile.ZipFile(res["path"]) as z:  # 저장된 파일에 수식 요소가 하나도 없음
            for name in z.namelist():
                if name.startswith("xl/worksheets/"):
                    self.assertNotIn(b"<f>", z.read(name), name)
                    self.assertNotIn(b"<f ", z.read(name), name)


class TestRiskColumns(ExportTestBase):
    """빈 위험도가 0으로 나오지 않고, AI 제안이 5–7열·〈별표9〉에 들어가지 않음."""

    def test_unreviewed_export_has_no_risk_values(self):
        _, wb = self.export()
        rows = read_rows(wb["HAZOP 워크시트"])
        proposed = [s["scenario_id"] for s in self.doc["scenarios"] if s["risk_proposal"]["status"] == "proposed"]
        self.assertTrue(proposed)
        for r in rows:
            self.assertEqual((r["frequency"], r["severity"], r["risk"]), ("미확정", "미확정", "미확정"))
            if r["scenario_id"] in proposed:
                rp = self.scenario(r["scenario_id"])["risk_proposal"]
                self.assertIn("위험도 %d" % rp["risk"], r["ai_risk"])
        self.assertEqual(wb["개선 권고"].max_row, 1)  # 검토 없으면 개선 권고 없음

    def test_confirmed_values_only_and_never_zero(self):
        self.save_d09()
        _, wb = self.export()
        rows = read_rows(wb["HAZOP 워크시트"])
        for r in rows:
            for k in ("frequency", "severity", "risk"):
                v = r[k]
                self.assertTrue(v == "미확정" or (isinstance(v, int) and v >= 1), (r["scenario_id"], k, v))
        s = self.scen("deviation-p86-d09")
        by = {r["scenario_id"]: r for r in rows}
        self.assertEqual((by[s[0]]["frequency"], by[s[0]]["severity"], by[s[0]]["risk"]), (1, 2, 1))
        deferred = by[s[2]]  # AI 제안 강도 3·빈도 2·위험도 4가 있는 시나리오를 보류
        self.assertEqual(self.scenario(s[2])["risk_proposal"]["status"], "proposed")
        self.assertEqual((deferred["frequency"], deferred["severity"], deferred["risk"]), ("미확정",) * 3)
        self.assertIn("보류", deferred["risk_source"])
        self.assertIn("위험도 4", deferred["ai_risk"])
        self.assertEqual(by[s[3]]["risk"], "미확정")
        self.assertEqual(by[s[1]]["risk_source"], "사람 확정(직접 고름)")


class TestRecommendations(ExportTestBase):
    """〈별표9〉: 수용·수정 후보만, 위험등급·우선순위는 사람 확정값 또는 '미확정', 관리 열은 '관리 안 함'."""

    def test_only_accepted_and_human_risk(self):
        self.save_d09()
        self.save_d12_defer()
        _, wb = self.export()
        ws = wb["개선 권고"]
        self.assertEqual([ws.cell(row=1, column=c).value for c in range(1, 10)],
                         ["번호", "우선순위", "위험등급", "개선권고사항", "책임부서", "조치일정", "진행결과", "완료확인", "비고"])
        recs = self.records()
        want = [d["dic_id"] for d in recs["deviation-p86-d09"]["design_improvement_decisions"]
                if d["decision"] in ("accept", "modify")]
        rows = [[ws.cell(row=r, column=c).value for c in range(1, 10)] for r in range(2, ws.max_row + 1)]
        self.assertTrue(want)
        self.assertEqual([r[3] for r in rows], ["권고 %s" % d for d in want])
        self.assertEqual([r[0] for r in rows], list(range(1, len(want) + 1)))
        d12_dic = self.dics_of(self.scen("deviation-p86-d12")[0])[0]
        self.assertFalse(any(d12_dic in r[8] for r in rows))  # 보류 결정 후보는 없음
        s = self.scen("deviation-p86-d09")
        self.assertIn(self.dics_of(s[2])[0], want)  # AI 제안 위험도 4가 있는 보류 시나리오의 후보를 수용
        sc_rc = {d["scenario_id"]: d.get("risk_confirmation") for d in recs["deviation-p86-d09"]["scenario_decisions"]}
        dic_scen = {d["dic_id"]: d["scenario_id"] for d in self.doc["design_improvement_candidates"]}
        dic_basis = {d["dic_id"]: d["basis"].get("risk") for d in self.doc["design_improvement_candidates"]}
        for r in rows:
            did = next(d for d in want if d in r[8])
            rc = sc_rc[dic_scen[did]]
            self.assertEqual(r[2], rc["risk"] if rc else "미확정")
            self.assertEqual(r[4:8], ["관리 안 함"] * 4)
            if dic_scen[did] == s[2]:  # 보류 시나리오: AI 제안(basis.risk=4)이 있어도 미확정
                self.assertEqual(dic_basis[did], 4)
                self.assertEqual((r[1], r[2]), ("미확정", "미확정"))
        risks = sorted({r[2] for r in rows if isinstance(r[2], int)}, reverse=True)
        for r in rows:
            if isinstance(r[2], int):
                self.assertEqual(r[1], risks.index(r[2]) + 1)
        self.assertIn("&P/&N", ws.oddHeader.right.text)


class TestHeaderAndFiles(ExportTestBase):
    def test_review_date_and_page_header(self):
        self.save_d12_defer()   # 2026-11-04T01:00Z
        self.save_d09()         # 2026-11-04T16:30Z → KST 2026-11-05
        _, wb = self.export()
        ws = wb["HAZOP 워크시트"]
        head = [ws.cell(row=2, column=c).value for c in range(1, 11)]
        self.assertEqual(head[0::2], ["공정", "검토일", "도면", "쪽", "검토구간"])
        self.assertEqual(head[1], self.doc["analysis_run"]["region"]["name"])
        self.assertEqual(head[3], "2026-11-05")
        self.assertEqual(head[5], "SNP-M-102")
        self.assertEqual(head[9], REGION)
        self.assertEqual(ws.oddHeader.right.text, "&P/&N")
        self.assertEqual([ws.cell(row=4, column=c).value for c in range(1, 9)],
                         ["이탈", "원인", "결과", "현재안전조치", "위험도", None, None, "개선권고사항"])
        self.assertEqual([ws.cell(row=5, column=c).value for c in (5, 6, 7)], ["빈도", "강도", "위험도"])

    def test_no_overwrite_and_export_record(self):
        self.save_d09()
        res, _ = self.export()
        self.assertEqual(os.path.dirname(res["path"]),
                         os.path.join(self.out, REGION, self.doc["analysis_run_id"]))
        self.assertEqual(os.path.basename(res["path"]), "worksheet-20261105T000000Z.xlsx")
        with open(res["path"], "rb") as fh:
            before = fh.read()
        with self.assertRaises(ExportError):
            self.export()
        with open(res["path"], "rb") as fh:
            self.assertEqual(fh.read(), before)
        exp = os.path.join(self.store, "reviews", REGION, self.doc["analysis_run_id"], "exports",
                           "20261105T000000Z.json")
        self.assertEqual(res["export_record_path"], exp)
        with open(exp, encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual((rec["exported_at"], rec["scope"]), (NOW, "all"))
        self.assertEqual(rec["target"]["analysis_sha256"], self.run["analysis_sha256"])
        self.assertEqual(rec["target"]["reviews"], [{"candidate_id": "deviation-p86-d09", "review_version": 1,
                                                     "review_status": "deferred"}])
        self.assertIn({"row": FIRST_DATA_ROW, "candidate_id": "deviation-p86-d01", "scenario_id": None,
                       "decision": None}, rec["rows"]["worksheet"])
        self.assertTrue(rec["rows"]["recommendations"])
        res2, _ = self.export(now="2026-11-05T00:00:01Z")
        self.assertNotEqual(res2["path"], res["path"])
        self.assertEqual(rv.load_run_reviews(self.store, REGION, self.doc["analysis_run_id"]).keys(),
                         {"deviation-p86-d09"})  # exports/는 검토본으로 읽히지 않음

    def test_scope_accepted_modified(self):
        self.save_d09()
        self.save_d01_confirm()
        res, wb = self.export(scope="accepted_modified")
        rows = read_rows(wb["HAZOP 워크시트"])
        self.assertEqual({r["decision"] for r in rows}, {"수용", "수정"})
        s = self.scen("deviation-p86-d09")
        self.assertEqual([r["scenario_id"] for r in rows], [s[0], s[1], s[4]])
        self.assertEqual(res["record"]["scope"], "accepted_modified")
        _, wb_all = self.export(now="2026-11-05T00:00:01Z")
        decisions = {r["scenario_id"]: r["decision"] for r in read_rows(wb_all["HAZOP 워크시트"])}
        self.assertEqual((decisions[s[2]], decisions[s[3]]), ("보류", "기각"))
        self.assertEqual(decisions[self.scen("deviation-p86-d10")[0]], "미검토")
        with self.assertRaises(ExportError):
            export_worksheet(self.run_dir, self.store, self.out, scope="selected", now="2026-11-05T00:00:02Z")


class TestBlocked(ExportTestBase):
    def assertNoOutput(self):
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(os.path.join(self.store, "reviews", REGION, self.doc["analysis_run_id"],
                                                     "exports")))

    def test_blocked_result(self):
        self.doc["validation"]["status"] = "blocked"
        self.doc["validation"]["errors"] = ["모의 오류"]
        with open(self.run["analysis_path"], "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.doc, fh, ensure_ascii=False, indent=2)
        with self.assertRaises(ExportError) as cm:
            export_worksheet(self.run_dir, self.store, self.out, now=NOW)
        self.assertTrue(any("passed가 아님" in e for e in cm.exception.errors))
        self.assertNoOutput()

    def test_hash_mismatch(self):
        self.save_d09()
        with open(self.run["analysis_path"], "w", encoding="utf-8", newline="\n") as fh:  # --resume 재작성 모사
            json.dump(self.doc, fh, ensure_ascii=False, indent=1)
        with self.assertRaises(ExportError) as cm:
            export_worksheet(self.run_dir, self.store, self.out, now=NOW)
        self.assertTrue(any("analysis_sha256" in e for e in cm.exception.errors), cm.exception.errors)
        self.assertNoOutput()

    def test_deleted_analysis(self):
        self.save_d09()
        os.remove(self.run["analysis_path"])
        with self.assertRaises(rv.ReviewError):
            export_worksheet(self.run_dir, self.store, self.out, now=NOW)
        self.assertNoOutput()


class TestReworkExport(ExportTestBase):
    """재작업 1회차: 개선권고사항 '미확정', 제어문자 차단, 원자적 쓰기·실패 후 재시도, CLI --resume 해시 잠금."""

    def leftovers(self):
        found = []
        for root in (self.out, self.store):
            for dirpath, _d, files in os.walk(root):
                found += [f for f in files if f.endswith(".part")]
        return found

    def test_recommendation_unconfirmed_vs_not_applicable(self):
        _, wb = self.export()
        rows = {r["scenario_id"]: r for r in read_rows(wb["HAZOP 워크시트"])}
        with_dic = {d["scenario_id"] for d in self.doc["design_improvement_candidates"]}
        self.assertTrue(with_dic)
        for sid, r in rows.items():
            if sid in with_dic:
                self.assertTrue(r["recommendation"].startswith("미확정"), r["recommendation"])
            elif sid != "시나리오 없음":
                self.assertEqual(r["recommendation"], "해당 없음(연결된 설계보완 후보 없음)")
        self.save_d09()
        _, wb = self.export(now="2026-11-05T00:00:01Z")
        rows = {r["scenario_id"]: r for r in read_rows(wb["HAZOP 워크시트"])}
        s = self.scen("deviation-p86-d09")
        for sid in s:
            if self.dics_of(sid):
                want = "개선 권고 없음" if sid == s[3] else "권고 %s" % self.dics_of(sid)[0]
                self.assertTrue(rows[sid]["recommendation"].startswith(want), rows[sid]["recommendation"])

    def test_control_character_in_analysis_blocks_export(self):
        self.doc["candidates"][0]["reason"] = "사유\x01"
        with open(self.run["analysis_path"], "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.doc, fh, ensure_ascii=False, indent=2)
        with self.assertRaises(ExportError) as cm:
            export_worksheet(self.run_dir, self.store, self.out, now=NOW)
        self.assertTrue(any("제어문자" in e for e in cm.exception.errors))
        self.assertFalse(os.path.exists(self.out))

    def test_record_write_failure_removes_xlsx_and_retry_works(self):
        from hazop.review import store
        real, calls = store.write_exclusive, []

        def flaky(path, data):
            calls.append(path)
            if path.endswith(".json"):
                raise OSError("모의 쓰기 실패")
            return real(path, data)
        with mock.patch.object(store, "write_exclusive", side_effect=flaky):
            with self.assertRaises(ExportError) as cm:
                export_worksheet(self.run_dir, self.store, self.out, now=NOW)
        self.assertTrue(any("출력 기록 쓰기 실패" in e for e in cm.exception.errors))
        self.assertEqual(len(calls), 2)
        self.assertFalse(os.path.exists(calls[0]))  # 워크시트 파일을 지움
        self.assertEqual(self.leftovers(), [])
        res, _ = self.export()  # 같은 시각으로 다시 출력 가능
        self.assertEqual(res["path"], calls[0])

    def test_xlsx_write_failure_leaves_nothing(self):
        with mock.patch("os.link", side_effect=OSError("모의 링크 실패")):
            with self.assertRaises(ExportError):
                export_worksheet(self.run_dir, self.store, self.out, now=NOW)
        self.assertEqual(glob.glob(os.path.join(self.out, "*", "*", "*")), [])
        self.assertEqual(self.leftovers(), [])
        self.export()

    def test_cli_resume_rewrite_locks_edit_and_export(self):
        """§8: 정상 CLI --resume 실행 뒤 analysis.json 해시가 바뀌면 편집과 Excel 출력이 막힌다."""
        saved = self.save_d09()
        proc = subprocess.run([python_exe(), os.path.join(REPO_ROOT, "scripts", "analyze.py"), "--resume", self.run_dir],
                              cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", "replace"))
        self.assertNotEqual(rv.file_sha256(self.run["analysis_path"]), saved["analysis_ref"]["analysis_sha256"])
        reopened = rv.open_run(self.run_dir)
        self.assertFalse(rv.check_editable(reopened, saved)["editable"])
        with self.assertRaises(ExportError) as cm:
            export_worksheet(self.run_dir, self.store, self.out, now=NOW)
        self.assertTrue(any("analysis_sha256" in e for e in cm.exception.errors))
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
