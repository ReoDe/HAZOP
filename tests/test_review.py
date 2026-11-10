"""단계 ⑤ 검토 확정 기록 테스트 (기획서/인터페이스.md §5, §8 ⑤ 행). 실행: python -m unittest discover -s tests

입력: tests/run_fixture.py가 임시 폴더에 고정 응답으로 새로 만든 실행(scripts/analyze.py 하위 프로세스)을
다시 임시 폴더에 복사해 쓴다(원본은 읽기만 함). output/(git 제외 폴더)의 기존 실행에 의존하지 않는다. 검토 기록은 임시 저장 루트에만 쓴다(store/에 쓰지 않음). 네트워크 사용 없음.
"""

import copy
import json
import os
import shutil
import tempfile
import unittest

from hazop import review as rv
from hazop.review import store
from hazop.analysis.risk import MATRIX_P86
from tests.run_fixture import fresh_run_dir

REVIEWER = "검토자A"
T = "2026-11-04T05:12:00Z"
BASIS = {"reference": "RC-PSV101 설정압력·용량 계산서 DOC-001 rev.0", "description": "용량·설정·독립성 확인"}


def copy_run(src, dst_root, run_id=None):
    """실행 폴더를 임시 위치에 복사. run_id를 주면 analysis_run_id를 바꾼 새 실행처럼 만든다."""
    with open(os.path.join(src, "analysis.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    run_id = run_id or doc["analysis_run_id"]
    dst = os.path.join(dst_root, run_id)
    shutil.copytree(src, dst)
    if run_id != doc["analysis_run_id"]:
        doc["analysis_run_id"] = run_id
        with open(os.path.join(dst, "analysis.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return dst


class ReviewTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = fresh_run_dir()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-review-")
        self.store = os.path.join(self.tmp, "store")
        self.run_dir = copy_run(self.src, os.path.join(self.tmp, "runs"))
        self.run = rv.open_run(self.run_dir)
        self.doc = self.run["doc"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # 도우미 --------------------------------------------------------------
    def rc(self, sev=3, f0=2, f=2, credited=(), source="human"):
        return rv.make_risk_confirmation(self.run, sev, "강도 근거", f0, f, "빈도 근거", credited, source)

    def accept(self, sid, rc=None, reason="원안 수용"):
        return rv.scenario_decision(self.run, sid, "accept", reason, REVIEWER,
                                    risk_confirmation=rc or self.rc(), now=T)

    def scen(self, cid):
        return [s["scenario_id"] for s in self.doc["scenarios"] if s["candidate_id"] == cid]

    def dics(self, cid):
        return [d["dic_id"] for d in self.doc["design_improvement_candidates"] if d["candidate_id"] == cid]

    def full_d12(self, sdec=None, ddec=None):
        sid, = self.scen("deviation-p86-d12")
        did, = self.dics("deviation-p86-d12")
        sdec = sdec or self.accept(sid)
        ddec = ddec if ddec is not None else [rv.dic_decision(self.run, did, "accept", "권고 필요", REVIEWER,
                                                              recommendation="가압기 고온 경보 추가 검토", now=T)]
        return rv.build_review(self.run, "deviation-p86-d12", REVIEWER, "편차 검토 요약", [sdec], ddec)

    def assertBlocked(self, record, fragment, run=None):
        errs = rv.validate_review(run or self.run, record)
        self.assertTrue(any(fragment in e for e in errs), "기대한 차단 '%s' 없음: %s" % (fragment, errs))
        with self.assertRaises(rv.ReviewError):
            rv.save_review(self.store, run or self.run, record)


class TestSample(ReviewTestBase):
    def test_sample_shape(self):
        self.assertEqual(self.doc["validation"]["status"], "passed")
        self.assertEqual(len(self.scen("deviation-p86-d09")), 5)
        self.assertEqual(len(self.dics("deviation-p86-d12")), 1)
        self.assertEqual(self.scen("deviation-p86-d01"), [])


class TestStorage(ReviewTestBase):
    """1. 버전 파일 저장, 이전 파일 불변, 원자적 쓰기."""

    def test_new_version_each_save_and_previous_unchanged(self):
        p1, r1 = rv.save_review(self.store, self.run, self.full_d12(), now=T)
        with open(p1, "rb") as fh:
            before = fh.read()
        p2, r2 = rv.save_review(self.store, self.run, self.full_d12(), now="2026-11-04T06:00:00Z")
        self.assertEqual((r1["review_version"], r2["review_version"]), (1, 2))
        self.assertEqual((r1["previous_review_version"], r2["previous_review_version"]), (None, 1))
        self.assertTrue(p1.endswith(os.path.join("deviation-p86-d12", "v1.json")))
        self.assertIn(os.path.join("reviews", "region-SNP-M-102-pzr", self.doc["analysis_run_id"]), p1)
        with open(p1, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(rv.list_versions(self.store, "region-SNP-M-102-pzr", self.doc["analysis_run_id"],
                                          "deviation-p86-d12"), [1, 2])
        self.assertEqual(rv.load_review(self.store, "region-SNP-M-102-pzr", self.doc["analysis_run_id"],
                                        "deviation-p86-d12")["review_version"], 2)
        self.assertFalse([n for n in os.listdir(os.path.dirname(p1)) if n.endswith(".tmp")])

    def test_failed_save_writes_nothing(self):
        rec = self.full_d12()
        rec["reviewer_id"] = ""
        with self.assertRaises(rv.ReviewError):
            rv.save_review(self.store, self.run, rec)
        self.assertFalse(os.path.exists(os.path.join(self.store, "reviews")))

    def test_existing_version_not_overwritten(self):
        _, rec = rv.save_review(self.store, self.run, self.full_d12(), now=T)
        with self.assertRaises(rv.ReviewError):
            store.write_new_version(self.store, rec)


class TestDecisionRecord(ReviewTestBase):
    """2. 결정값·사유·검토자·시각·ai_original·revised."""

    def test_reason_required_for_all_four_decisions(self):
        sid = self.scen("deviation-p86-d12")[0]
        for dec in rv.SCENARIO_DECISIONS:
            rc = self.rc() if dec in ("accept", "modify") else None
            d = rv.scenario_decision(self.run, sid, dec, "  ", REVIEWER, risk_confirmation=rc, now=T)
            rec = rv.build_review(self.run, "deviation-p86-d12", REVIEWER, "요약", [d])
            self.assertBlocked(rec, "사유 없음")

    def test_reviewer_required(self):
        rec = self.full_d12()
        rec["reviewer_id"] = None
        self.assertBlocked(rec, "검토자 이름")

    def test_reviewer_and_time_recorded(self):
        _, saved = rv.save_review(self.store, self.run, self.full_d12())
        self.assertEqual(saved["reviewer_id"], REVIEWER)
        self.assertRegex(saved["reviewed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(saved["scenario_decisions"][0]["decided_by"], REVIEWER)
        self.assertEqual(saved["action_ids"], ["action-dic-scenario-p86-d12-01"])

    def test_modify_keeps_ai_original_and_only_changed_fields(self):
        sid = "scenario-p86-d09-01"
        orig = next(s for s in self.doc["scenarios"] if s["scenario_id"] == sid)
        shown = rv.merge_display(orig)
        d = rv.scenario_decision(self.run, sid, "modify", "결과 정정", REVIEWER,
                                 revised={"cause": shown["cause"]["value"], "consequence": "가압기 압력 상승(정정)",
                                          "safeguards": shown["safeguards"]["value"]},
                                 risk_confirmation=self.rc(), now=T)
        self.assertEqual(d["revised"], {"consequence": "가압기 압력 상승(정정)"})
        rec = rv.build_review(self.run, "deviation-p86-d09", REVIEWER, "요약", [d])
        _, saved = rv.save_review(self.store, self.run, rec)
        ao = saved["scenario_decisions"][0]["ai_original"]
        self.assertEqual(ao["pattern"]["cause"], orig["cause"])
        self.assertEqual(ao["pattern"]["consequence"], orig["consequence"])
        self.assertEqual(ao["ai_interpretation"], orig["ai_interpretation"])
        self.assertEqual(ao["safeguards"], orig["safeguards"])
        self.assertEqual(ao["risk_proposal"], orig["risk_proposal"])
        self.assertEqual(ao["sha256"], store.obj_sha256(orig))

    def test_tampered_ai_original_or_unchanged_revised_blocked(self):
        rec = self.full_d12()
        rec["scenario_decisions"][0]["ai_original"]["pattern"]["cause"] = "바꿈"
        self.assertBlocked(rec, "ai_original")
        sid = self.scen("deviation-p86-d12")[0]
        d = rv.scenario_decision(self.run, sid, "modify", "정정", REVIEWER, risk_confirmation=self.rc(), now=T)
        orig = next(s for s in self.doc["scenarios"] if s["scenario_id"] == sid)
        d["revised"] = {"cause": rv.merge_display(orig)["cause"]["value"]}
        self.assertBlocked(rv.build_review(self.run, "deviation-p86-d12", REVIEWER, "요약", [d]), "바뀌지 않은 필드")

    def test_invalid_decision_value_blocked(self):
        sid = self.scen("deviation-p86-d12")[0]
        d = rv.scenario_decision(self.run, sid, "approve", "사유", REVIEWER, now=T)
        self.assertBlocked(rv.build_review(self.run, "deviation-p86-d12", REVIEWER, "요약", [d]), "결정값 오류")

    def test_dic_accept_requires_recommendation(self):
        did, = self.dics("deviation-p86-d12")
        dd = rv.dic_decision(self.run, did, "accept", "권고 필요", REVIEWER, recommendation="", now=T)
        self.assertBlocked(self.full_d12(ddec=[dd]), "개선 권고 문안")


class TestRiskConfirmation(ReviewTestBase):
    """3. 위험도 확정 검사(§5.2 1·3·4·5, 필수 항목, source)."""

    def test_risk_computed_from_table5(self):
        for sev in (1, 2, 3, 4):
            for f in (1, 2, 3):
                rc = self.rc(sev, f, f)
                self.assertEqual(rc["risk"], MATRIX_P86[sev][f])
        rc = self.rc(4, 1, 1)
        self.assertEqual((rc["risk"], rc["risk_name"]), (3, "상당한 위험"))
        self.assertEqual(rc["criteria_id"], self.doc["analysis_run"]["versions"]["risk_criteria"]["id"])
        self.assertEqual(rc["criteria_version"], self.doc["analysis_run"]["versions"]["risk_criteria"]["version"])
        self.assertEqual(rc["criteria_file_version"], 1)

    def test_human_entered_grade_blocked(self):
        rc = self.rc(3, 2, 2)
        rc["risk"] = 1
        sid = self.scen("deviation-p86-d12")[0]
        self.assertBlocked(self.full_d12(sdec=self.accept(sid, rc)), "〈표5〉 계산과 다름")

    def test_missing_severity_or_frequency_or_basis_blocked(self):
        sid = self.scen("deviation-p86-d12")[0]
        with self.assertRaises(rv.ReviewError):
            rv.make_risk_confirmation(self.run, None, "b", 2, 2, "b")
        for key, frag in (("severity", "강도"), ("frequency", "빈도"), ("severity_basis", "강도 근거"),
                          ("frequency_basis", "빈도 근거")):
            rc = self.rc()
            rc[key] = None
            self.assertBlocked(self.full_d12(sdec=self.accept(sid, rc)), frag)
        d = rv.scenario_decision(self.run, sid, "accept", "수용", REVIEWER, risk_confirmation=None, now=T)
        self.assertBlocked(self.full_d12(sdec=d), "위험도 확정값 없음")

    def test_ai_proposal_adopted_only_by_button(self):
        sid = "scenario-p86-d09-03"
        vals = rv.adopt_ai_proposal(self.run, sid)
        self.assertEqual((vals["severity"], vals["frequency"], vals["source"]), (3, 2, "ai_proposal_adopted"))
        self.assertEqual(vals["credited_safeguards"], [])
        self.assertIsNone(vals["severity_basis"])
        rc = rv.make_risk_confirmation(self.run, vals["severity"], "검토자 확인 근거", vals["frequency_without_safeguards"],
                                       vals["frequency"], "검토자 확인 근거", vals["credited_safeguards"], vals["source"])
        self.assertEqual(rc["source"], "ai_proposal_adopted")
        self.assertEqual(rv.check_risk_confirmation(self.run, self._s(sid), rc), [])
        human = self.rc()
        self.assertEqual(human["source"], "human")
        with self.assertRaises(rv.ReviewError):  # 제안이 보류(deferred)면 가져올 값 없음
            rv.adopt_ai_proposal(self.run, "scenario-p86-d09-01")
        bad = self.rc(source="ai_proposal_adopted")
        self.assertTrue(rv.check_risk_confirmation(self.run, self._s("scenario-p86-d09-01"), bad))
        bad = self.rc(source="ai")
        self.assertTrue(any("source" in e for e in rv.check_risk_confirmation(self.run, self._s(sid), bad)))

    def _s(self, sid):
        return next(s for s in self.doc["scenarios"] if s["scenario_id"] == sid)

    def test_frequency_reduction_needs_credited_safeguard_with_basis(self):
        sid = "scenario-p86-d09-03"
        s = self._s(sid)
        errs = rv.check_risk_confirmation(self.run, s, self.rc(3, 2, 1))
        self.assertTrue(any("보호수단 없이 빈도를 낮춤" in e for e in errs), errs)
        no_basis = self.rc(3, 2, 1, [{"node_id": "entity-node-014", "basis": {"reference": "", "description": ""}}])
        self.assertTrue(any("확인 근거" in e for e in rv.check_risk_confirmation(self.run, s, no_basis)))
        missing = self.rc(3, 2, 1, [{"node_id": "entity-node-014"}])
        self.assertTrue(any("확인 근거" in e for e in rv.check_risk_confirmation(self.run, s, missing)))
        not_in_graph = self.rc(3, 2, 1, [{"node_id": "entity-node-999", "basis": BASIS}])
        self.assertTrue(any("그래프에 없음" in e for e in rv.check_risk_confirmation(self.run, s, not_in_graph)))
        good = self.rc(3, 2, 1, [{"node_id": "entity-node-014", "basis": BASIS}])
        self.assertEqual(rv.check_risk_confirmation(self.run, s, good), [])
        self.assertEqual(good["risk"], 2)

    def test_criteria_mismatch_blocked(self):
        rc = self.rc()
        rc["criteria_version"] = "다른 기준표"
        self.assertTrue(any("기준표 식별자" in e for e in
                            rv.check_risk_confirmation(self.run, self._s("scenario-p86-d09-03"), rc)))

    def test_defer_and_reject_have_null_risk(self):
        sid = self.scen("deviation-p86-d12")[0]
        d = rv.scenario_decision(self.run, sid, "defer", "운전조건 자료 대기", REVIEWER,
                                 risk_confirmation=self.rc(), now=T)
        self.assertIsNone(d["risk_confirmation"])
        d["risk_confirmation"] = self.rc()
        self.assertBlocked(self.full_d12(sdec=d, ddec=[]), "null")


class TestCombination(ReviewTestBase):
    """4. 시나리오 기각 → 설계보완 후보 not_applicable, confirm_no_scenario 범위."""

    def test_reject_makes_dic_not_applicable(self):
        sid, = self.scen("deviation-p86-d12")
        d = rv.scenario_decision(self.run, sid, "reject", "도면 범위 밖 원인", REVIEWER, now=T)
        rec = rv.build_review(self.run, "deviation-p86-d12", REVIEWER, "요약", [d], [])
        dd, = rec["design_improvement_decisions"]
        self.assertEqual((dd["decision"], dd["reason"], dd["inherited_from"]),
                         ("not_applicable", "도면 범위 밖 원인", sid))
        self.assertEqual(rec["review_status"], "confirmed")
        self.assertIsNone(rec["risk_confirmation"])
        rv.save_review(self.store, self.run, rec)

    def test_reject_with_dic_accept_blocked(self):
        sid, = self.scen("deviation-p86-d12")
        d = rv.scenario_decision(self.run, sid, "reject", "기각", REVIEWER, now=T)
        self.assertBlocked(self.full_d12(sdec=d), "함께 저장할 수 없음")

    def test_not_applicable_not_selectable(self):
        did, = self.dics("deviation-p86-d12")
        with self.assertRaises(rv.ReviewError):
            rv.dic_decision(self.run, did, "not_applicable", "x", REVIEWER)
        rec = self.full_d12()
        rec["design_improvement_decisions"][0].update(decision="not_applicable", recommendation=None)
        rec["action_ids"] = []
        self.assertBlocked(rec, "자동 지정만")

    def test_confirm_no_scenario_only_for_zero_scenarios(self):
        nsc = rv.no_scenario_confirmation("그래프에서 원인 설비 없음 확인", REVIEWER, now=T)
        ok = rv.build_review(self.run, "deviation-p86-d01", REVIEWER, "요약", no_scenario=nsc)
        self.assertEqual(ok["review_status"], "confirmed")
        rv.save_review(self.store, self.run, ok)
        bad = rv.build_review(self.run, "deviation-p86-d12", REVIEWER, "요약",
                              [self.accept(self.scen("deviation-p86-d12")[0])], no_scenario=nsc)
        self.assertBlocked(bad, "시나리오 없음 확인")
        nsc_empty = rv.no_scenario_confirmation("", REVIEWER, now=T)
        self.assertBlocked(rv.build_review(self.run, "deviation-p86-d01", REVIEWER, "요약", no_scenario=nsc_empty),
                           "사유 없음")

    def test_excluded_candidate_not_saved(self):
        cid = next(c["candidate_id"] for c in self.doc["candidates"] if c["selection_status"] == "excluded")
        nsc = rv.no_scenario_confirmation("x", REVIEWER, now=T)
        self.assertBlocked(rv.build_review(self.run, cid, REVIEWER, "요약", no_scenario=nsc), "선택(selected)")


class TestReviewStatus(ReviewTestBase):
    """5. review_status 판정 순서와 집계."""

    def test_order(self):
        cid = "deviation-p86-d09"
        sids, dids = self.scen(cid), self.dics(cid)
        self.assertEqual(rv.compute_review_status(self.doc, cid, None), "not_reviewed")
        part = rv.build_review(self.run, cid, REVIEWER, "요약", [self.accept(sids[0])])
        self.assertEqual(part["review_status"], "reviewing")
        decs = [self.accept(s) for s in sids[:-1]] + [
            rv.scenario_decision(self.run, sids[-1], "defer", "자료 대기", REVIEWER, now=T)]
        ddecs = [rv.dic_decision(self.run, d, "accept", "필요", REVIEWER, recommendation="권고", now=T) for d in dids]
        self.assertEqual(rv.build_review(self.run, cid, REVIEWER, "요약", decs, ddecs)["review_status"], "deferred")
        self.assertEqual(rv.build_review(self.run, cid, REVIEWER, "요약", decs[:-1] + [self.accept(sids[-1])],
                                         ddecs[:-1])["review_status"], "reviewing")  # 설계보완 후보 미결정
        full = rv.build_review(self.run, cid, REVIEWER, "요약", decs[:-1] + [self.accept(sids[-1])], ddecs)
        self.assertEqual(full["review_status"], "confirmed")
        rv.save_review(self.store, self.run, full)

    def test_zero_scenario_not_confirmed_without_confirmation(self):
        memo = rv.memo_record("memo-001", "운전압력 자료 요청", "확인 필요", REVIEWER, ["hold-001"], now=T)
        rec = rv.build_review(self.run, "deviation-p86-d01", REVIEWER, "요약", memo_records=[memo])
        self.assertEqual(rec["review_status"], "reviewing")
        self.assertEqual(rec["material_request_memos"], ["운전압력 자료 요청"])
        rv.save_review(self.store, self.run, rec)
        rec["review_status"] = "confirmed"
        self.assertBlocked(rec, "review_status")

    def test_summary_excludes_excluded(self):
        _, saved = rv.save_review(self.store, self.run, self.full_d12())
        recs = rv.load_run_reviews(self.store, "region-SNP-M-102-pzr", self.doc["analysis_run_id"])
        summ = rv.review_summary(self.doc, recs)
        self.assertEqual(len(summ["excluded"]), 19)
        self.assertEqual(sum(summ["counts"].values()), 25)
        self.assertEqual(summ["counts"]["confirmed"], 1)
        self.assertEqual(summ["counts"]["not_reviewed"], 24)
        self.assertNotIn(summ["excluded"][0], summ["by_candidate"])


class TestHashLock(ReviewTestBase):
    """6. analysis.json 삭제·해시 변경 시 편집·저장 불가(열람만)."""

    def test_deleted_analysis(self):
        rec = self.full_d12()
        os.remove(self.run["analysis_path"])
        self.assertFalse(rv.check_editable(self.run, rec)["editable"])
        self.assertBlocked(rec, "analysis.json이 없음")

    def test_rewritten_analysis(self):
        _, saved = rv.save_review(self.store, self.run, self.full_d12())
        # CLI --resume이 파일을 다시 쓴 상황을 모사: 내용은 같아도 바이트가 바뀜
        with open(self.run["analysis_path"], "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.doc, fh, ensure_ascii=False, indent=1)
        self.assertFalse(rv.check_editable(self.run, saved)["editable"])
        self.assertBlocked(self.full_d12(), "연 뒤에 바뀜")
        reopened = rv.open_run(self.run_dir)  # 다시 열어도 이전 검토본이 다른 해시를 가리키면 잠김
        lock = rv.check_editable(reopened, saved)
        self.assertFalse(lock["editable"])
        self.assertTrue(any("analysis_sha256" in r for r in lock["reasons"]))
        rec = rv.build_review(reopened, "deviation-p86-d12", REVIEWER, "요약",
                              self.full_d12()["scenario_decisions"], self.full_d12()["design_improvement_decisions"])
        with self.assertRaises(rv.ReviewError) as cm:
            rv.save_review(self.store, reopened, rec)
        self.assertTrue(any("이전 검토본" in e for e in cm.exception.errors), cm.exception.errors)
        self.assertEqual(rv.load_review(self.store, "region-SNP-M-102-pzr", self.doc["analysis_run_id"],
                                        "deviation-p86-d12")["review_version"], 1)  # 열람은 가능

    def test_editable_when_unchanged(self):
        self.assertTrue(rv.check_editable(self.run, None)["editable"])


class TestPriorImport(ReviewTestBase):
    """7. 이전 실행 검토 대응·가져오기, 재분석 시 자동 승계 없음."""

    def setUp(self):
        super().setUp()
        _, self.saved = rv.save_review(self.store, self.run, self.full_d12(), now=T)
        self.new_dir = copy_run(self.src, os.path.join(self.tmp, "runs"), "analysis-29991231T000000Z-test")
        self.new = rv.open_run(self.new_dir)

    def test_no_automatic_carry_over(self):
        self.assertIsNone(rv.load_review(self.store, "region-SNP-M-102-pzr", self.new["doc"]["analysis_run_id"],
                                         "deviation-p86-d12"))
        self.assertEqual(rv.compute_review_status(self.new["doc"], "deviation-p86-d12", None), "not_reviewed")

    def test_single_match_import(self):
        priors = rv.find_prior_reviews(self.store, "region-SNP-M-102-pzr", self.new["doc"]["analysis_run_id"],
                                       "deviation-p86-d12")
        self.assertEqual(len(priors), 1)
        prior = priors[0]
        sid, = self.scen("deviation-p86-d12")
        s = next(x for x in self.new["doc"]["scenarios"] if x["scenario_id"] == sid)
        self.assertEqual(rv.match_status(rv.match_scenario(prior["record"], s)), "single")
        d = rv.import_scenario_decision(self.new, sid, prior, "재확인 후 가져옴", "검토자B", now="2026-11-05T00:00:00Z")
        self.assertEqual(d["imported_from"], {"analysis_run_id": self.doc["analysis_run_id"], "review_version": 1,
                                              "scenario_id": sid})
        self.assertEqual((d["reason"], d["decided_by"], d["decided_at"]),
                         ("재확인 후 가져옴", "검토자B", "2026-11-05T00:00:00Z"))
        did, = self.dics("deviation-p86-d12")
        dd = rv.import_dic_decision(self.new, did, prior, "가져옴", "검토자B")
        self.assertEqual(dd["recommendation"], "가압기 고온 경보 추가 검토")
        rec = rv.build_review(self.new, "deviation-p86-d12", "검토자B", "가져온 검토", [d], [dd])
        _, saved = rv.save_review(self.store, self.new, rec)
        self.assertEqual(saved["review_version"], 1)
        with self.assertRaises(rv.ReviewError):  # 가져와도 사유는 새로 필요
            rv.save_review(self.store, self.new, rv.build_review(
                self.new, "deviation-p86-d12", "검토자B", "x",
                [rv.import_scenario_decision(self.new, sid, prior, "", "검토자B")], [dd]))

    def test_zero_and_multiple_matches(self):
        prior = rv.find_prior_reviews(self.store, "region-SNP-M-102-pzr", self.new["doc"]["analysis_run_id"],
                                      "deviation-p86-d12")[0]
        other = next(x for x in self.new["doc"]["scenarios"] if x["scenario_id"] == "scenario-p86-d09-01")
        self.assertEqual(rv.match_status(rv.match_scenario(prior["record"], other)), "none")
        with self.assertRaises(rv.ReviewError):
            rv.import_scenario_decision(self.new, "scenario-p86-d09-01", prior, "r", "검토자B")
        dup = copy.deepcopy(prior)
        extra = copy.deepcopy(dup["record"]["scenario_decisions"][0])
        extra["scenario_id"] = "scenario-p86-d12-99"
        extra["decision"] = "defer"
        dup["record"]["scenario_decisions"].append(extra)
        sid, = self.scen("deviation-p86-d12")
        s = next(x for x in self.new["doc"]["scenarios"] if x["scenario_id"] == sid)
        self.assertEqual(rv.match_status(rv.match_scenario(dup["record"], s)), "multiple")
        with self.assertRaises(rv.ReviewError):
            rv.import_scenario_decision(self.new, sid, dup, "r", "검토자B")
        d = rv.import_scenario_decision(self.new, sid, dup, "골라서 가져옴", "검토자B", choice="scenario-p86-d12-99")
        self.assertEqual((d["decision"], d["imported_from"]["scenario_id"]), ("defer", "scenario-p86-d12-99"))

    def test_match_keys(self):
        pat = {"scenario_id": "s1", "origin": "pattern", "pattern_ref": {"match_id": "m-1"}, "cause_group": "g"}
        hyp = {"scenario_id": "scenario-x-h-abc", "origin": "ai_additional_hypothesis", "pattern_ref": None,
               "cause_group": "g"}
        self.assertEqual(rv.scenario_match_key(pat), ["match", "m-1"])
        self.assertEqual(rv.scenario_match_key(hyp), ["scenario", "scenario-x-h-abc"])

    def test_no_scenario_import(self):
        nsc = rv.no_scenario_confirmation("원인 설비 없음", REVIEWER, now=T)
        rv.save_review(self.store, self.run, rv.build_review(self.run, "deviation-p86-d01", REVIEWER, "s",
                                                             no_scenario=nsc))
        prior = rv.find_prior_reviews(self.store, "region-SNP-M-102-pzr", self.new["doc"]["analysis_run_id"],
                                      "deviation-p86-d01")[0]
        got = rv.import_no_scenario_confirmation(prior, "재확인", "검토자B")
        self.assertEqual(got["imported_from"]["analysis_run_id"], self.doc["analysis_run_id"])
        with self.assertRaises(rv.ReviewError):
            rv.import_no_scenario_confirmation(
                rv.find_prior_reviews(self.store, "region-SNP-M-102-pzr", self.new["doc"]["analysis_run_id"],
                                      "deviation-p86-d12")[0], "r", "b")


class TestMerge(ReviewTestBase):
    """8. §6.2 병합 규칙과 필드별 값 출처."""

    def test_partial_modify(self):
        sid = "scenario-p86-d09-01"
        s = next(x for x in self.doc["scenarios"] if x["scenario_id"] == sid)
        d = rv.scenario_decision(self.run, sid, "modify", "결과만 정정", REVIEWER,
                                 revised={"consequence": "정정된 결과"}, risk_confirmation=self.rc(), now=T)
        m = rv.merge_display(s, d)
        self.assertEqual(m["consequence"], {"value": "정정된 결과", "source": "revised"})
        self.assertEqual(m["cause"], {"value": s["ai_interpretation"]["cause"], "source": "ai_interpretation"})
        self.assertEqual(m["safeguards"], {"value": s["safeguards"], "source": "graph"})
        self.assertEqual(rv.value_source_text(m), "원인=AI 해석 원안, 결과=사람 수정, 현재안전조치=그래프 확인")

    def test_pattern_fallback_and_revised_safeguards(self):
        s = next(x for x in self.doc["scenarios"] if not x.get("ai_interpretation"))
        m = rv.merge_display(s)
        self.assertEqual((m["cause"]["source"], m["cause"]["value"]), ("pattern", s["cause"]))
        m2 = rv.merge_display(s, {"revised": {"safeguards": [{"node_id": "entity-node-014"}]}})
        self.assertEqual(m2["safeguards"]["source"], "revised")
        self.assertNotIn(None, [m[k]["value"] for k in ("cause", "consequence")])

    def test_ai_hypothesis_has_no_graph_safeguards(self):
        """AI 추가 가설의 scenarios[].safeguards는 AI 제시 보호수단 — 현재안전조치(그래프 확인) 값에 넣지 않는다."""
        pat = next(x for x in self.doc["scenarios"] if x["origin"] == "pattern" and x["safeguards"])
        self.assertEqual(rv.merge_display(pat)["safeguards"], {"value": pat["safeguards"], "source": "graph"})
        hyp = copy.deepcopy(pat)
        hyp.update(scenario_id="scenario-p86-d09-h-0000000000", origin="ai_additional_hypothesis", pattern_ref=None,
                   statement_type="additional_hypothesis")
        m = rv.merge_display(hyp)
        self.assertEqual(m["safeguards"], {"value": [], "source": "graph"})
        self.assertIn("현재안전조치=그래프 확인", rv.value_source_text(m))
        m2 = rv.merge_display(hyp, {"revised": {"safeguards": [{"node_id": "entity-node-014"}]}})
        self.assertEqual(m2["safeguards"], {"value": [{"node_id": "entity-node-014"}], "source": "revised"})


class TestBlocked(ReviewTestBase):
    """9. blocked 결과에서 저장·확정 차단."""

    def test_blocked_run(self):
        self.doc["validation"]["status"] = "blocked"
        self.doc["validation"]["errors"] = ["모의 오류"]
        with open(self.run["analysis_path"], "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.doc, fh, ensure_ascii=False, indent=2)
        run = rv.open_run(self.run_dir)
        self.assertTrue(run["blocked"])
        self.assertFalse(rv.check_editable(run)["editable"])
        rec = rv.build_review(run, "deviation-p86-d12", REVIEWER, "요약",
                              [rv.scenario_decision(run, self.scen("deviation-p86-d12")[0], "defer", "대기",
                                                    REVIEWER, now=T)])
        self.assertBlocked(rec, "passed가 아님", run=run)


class TestSourceUntouched(ReviewTestBase):
    def test_source_run_unchanged(self):
        before = rv.file_sha256(os.path.join(self.src, "analysis.json"))
        rv.save_review(self.store, self.run, self.full_d12())
        self.assertEqual(rv.file_sha256(os.path.join(self.src, "analysis.json")), before)


class TestReworkChecks(ReviewTestBase):
    """재작업 1회차: 수정 보호수단 그래프 검사, 제어문자, 가져온 AI 제안 위험도, 바뀐 내용 없는 수정, 배타적 쓰기."""

    def new_run(self, run_id="analysis-29991231T000000Z-rework", edit=None):
        """복사한 새 실행. edit(doc, graph)로 analysis.json·inputs/graph.json을 고친 뒤 연다."""
        d = copy_run(self.src, os.path.join(self.tmp, "runs"), run_id)
        if edit:
            ap, gp = os.path.join(d, "analysis.json"), os.path.join(d, "inputs", "graph.json")
            with open(ap, encoding="utf-8") as fh:
                doc = json.load(fh)
            with open(gp, encoding="utf-8") as fh:
                graph = json.load(fh)
            edit(doc, graph)
            for path, obj in ((ap, doc), (gp, graph)):
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(obj, fh, ensure_ascii=False, indent=2)
        return rv.open_run(d)

    def modify_sg(self, run, node_id):
        sid, = [s["scenario_id"] for s in run["doc"]["scenarios"] if s["candidate_id"] == "deviation-p86-d12"]
        d = rv.scenario_decision(run, sid, "modify", "보호수단 정정", REVIEWER, revised={"safeguards": [{"node_id": node_id}]},
                                 risk_confirmation=rv.make_risk_confirmation(run, 3, "근거", 2, 2, "근거"), now=T)
        return rv.build_review(run, "deviation-p86-d12", REVIEWER, "요약", [d])

    def test_revised_safeguard_must_be_in_graph(self):
        self.assertBlocked(self.modify_sg(self.run, "entity-node-999"), "수정 보호수단: entity-node-999가 분석 당시 그래프에 없음")
        rv.save_review(self.store, self.run, self.modify_sg(self.run, "entity-node-014"))

    def test_imported_revised_safeguard_checked_against_new_graph(self):
        rv.save_review(self.store, self.run, self.modify_sg(self.run, "entity-node-014"))

        def drop(doc, graph):
            graph["nodes"] = [n for n in graph["nodes"] if n["entity_id"] != "entity-node-014"]
        new = self.new_run(edit=drop)
        prior = rv.find_prior_reviews(self.store, "region-SNP-M-102-pzr", new["doc"]["analysis_run_id"],
                                      "deviation-p86-d12")[0]
        sid, = self.scen("deviation-p86-d12")
        d = rv.import_scenario_decision(new, sid, prior, "가져옴", "검토자B", now=T)
        self.assertEqual(d["revised"], {"safeguards": [{"node_id": "entity-node-014"}]})
        self.assertBlocked(rv.build_review(new, "deviation-p86-d12", "검토자B", "요약", [d]), "그래프에 없음", run=new)

    def test_control_characters_blocked_with_field_name(self):
        sid, = self.scen("deviation-p86-d12")
        did, = self.dics("deviation-p86-d12")
        cases = (
            (self.full_d12(sdec=self.accept(sid, reason="사유\x01")), "scenario_decisions[0].reason"),
            (self.full_d12(ddec=[rv.dic_decision(self.run, did, "accept", "필요", REVIEWER,
                                                 recommendation="권고\x0b문안", now=T)]),
             "design_improvement_decisions[0].recommendation"),
            (rv.build_review(self.run, "deviation-p86-d01", REVIEWER, "요약", memo_records=[
                rv.memo_record("memo-001", "자료\x1f요청", "확인", REVIEWER, now=T)]), "memo_records[0].content"),
        )
        for rec, field in cases:
            self.assertBlocked(rec, field + ": 쓸 수 없는 제어문자")
        ok = self.full_d12(sdec=self.accept(sid, reason="여러 줄\n사유\t탭\r"))
        self.assertEqual(rv.validate_review(self.run, ok), [])

    def test_imported_ai_adopted_risk_allowed_without_current_proposal(self):
        sid = "scenario-p86-d09-03"
        vals = rv.adopt_ai_proposal(self.run, sid)
        rc = rv.make_risk_confirmation(self.run, vals["severity"], "검토자 확인", vals["frequency_without_safeguards"],
                                       vals["frequency"], "검토자 확인", [], vals["source"])
        d = rv.scenario_decision(self.run, sid, "accept", "AI 제안 확인 후 수용", REVIEWER, risk_confirmation=rc, now=T)
        rv.save_review(self.store, self.run, rv.build_review(self.run, "deviation-p86-d09", REVIEWER, "요약", [d]))

        def no_proposal(doc, graph):
            s = next(x for x in doc["scenarios"] if x["scenario_id"] == sid)
            s["risk_proposal"] = dict(s["risk_proposal"], status="deferred", reason="모의: 제안 없음")
        new = self.new_run(edit=no_proposal)
        prior = rv.find_prior_reviews(self.store, "region-SNP-M-102-pzr", new["doc"]["analysis_run_id"],
                                      "deviation-p86-d09")[0]
        got = rv.import_scenario_decision(new, sid, prior, "이전 결정 재확인", "검토자B", now=T)
        self.assertEqual(got["risk_confirmation"]["source"], "ai_proposal_adopted")
        _, saved = rv.save_review(self.store, new, rv.build_review(new, "deviation-p86-d09", "검토자B", "요약", [got]))
        self.assertEqual(saved["scenario_decisions"][0]["imported_from"]["scenario_id"], sid)
        direct = rv.scenario_decision(new, sid, "accept", "수용", REVIEWER, risk_confirmation=rc, now=T)
        self.assertBlocked(rv.build_review(new, "deviation-p86-d09", REVIEWER, "요약", [direct]), "AI 제안이 없는데",
                           run=new)
        no_reason = rv.import_scenario_decision(new, sid, prior, "", "검토자B", now=T)
        self.assertBlocked(rv.build_review(new, "deviation-p86-d09", "검토자B", "요약", [no_reason]), "사유 없음", run=new)

    def test_modify_without_change_blocked(self):
        sid, = self.scen("deviation-p86-d12")
        base = rv.merge_display(next(s for s in self.doc["scenarios"] if s["scenario_id"] == sid))
        for revised in (None, {"cause": base["cause"]["value"]}):
            d = rv.scenario_decision(self.run, sid, "modify", "정정", REVIEWER, revised=revised,
                                     risk_confirmation=self.rc(), now=T)
            self.assertIsNone(d["revised"])
            self.assertBlocked(self.full_d12(sdec=d), "바뀐 내용이 없으면 수용으로")

    def test_version_file_exclusive_and_no_temp_left(self):
        p1, rec = rv.save_review(self.store, self.run, self.full_d12(), now=T)
        with open(p1, "rb") as fh:
            before = fh.read()
        changed = dict(rec, reason="다른 내용")
        with self.assertRaises(rv.ReviewError):
            store.write_new_version(self.store, changed)
        with open(p1, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(sorted(os.listdir(os.path.dirname(p1))), ["v1.json"])


if __name__ == "__main__":
    unittest.main()
