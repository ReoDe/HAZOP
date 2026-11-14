"""새 화면 ⑥ 초기사건 B5: 후보별 IE 판정과 추적(hazop/shell/api_ie.py candidate_view·ie.judge). 실행: python -m unittest tests.test_shell_ie_judge

판정은 ⑤ 결과 파일의 ie_hint에 저장한다(설계 E4). 실제 결과 명령(result_commands.set_ie_hints)과 저장 길로 돌고, 인계 묶음·Excel에 그대로
실리는지 본다. 겹친 구간에서 한 후보로 묶인 쌍둥이 항목은 한 번에 같은 판정을 받는다. 임시 작업 루트만 쓴다.
"""

import copy
import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.shell import api, api_ie  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_shell_ie_edit import EditBase, OverlapTwinTest  # noqa: E402

HINT = {"candidate": "yes", "disturbs": "yes", "challenges": "yes", "category": "LOIA", "safety_functions": ["계기용 공기 공급"],
        "reason": "공기 헤더 압력 저하로 공기구동 밸브가 실패 위치로 감"}


class JudgeTest(EditBase):
    def setUp(self):
        super().setUp()
        for n in self.pg["nodes"]:          # 실제 프로젝트 그래프처럼 도면 안 ID(local_id)
            if n.get("sheet") and n.get("source_object_id"):
                n.setdefault("local_id", n["source_object_id"])

    def view(self, iec):
        return self.read("ie", "candidate", iec)

    def judge(self, iec, hint=HINT, **a):
        v = self.view(iec)
        return self.call("ie.judge", dict({"iec": iec, "hint": hint, "rver": v["rver"], "seen": {"member:" + iec: v["fp"]}}, **a))

    def entry(self, eid):
        doc, _fp = res.load_fp(self.ns)
        return next(e for c in doc["cells"] for e in c["entries"] if e["entry_id"] == eid)

    def test_trace_is_one_line_of_nodes_each_with_a_place_to_go(self):
        v = self.view(self.iec("c1"))
        kinds = [x["kind"] for x in v["trace"]]
        self.assertEqual(kinds[:6], ["cell", "cause", "location", "judgement", "group", "end_state"])
        self.assertEqual(kinds[6:], ["path"], "근거 경로 마디")
        cell = v["trace"][0]
        self.assertEqual((cell["node_id"], cell["deviation_id"]), (v["candidate"]["node_id"], v["candidate"]["deviation_id"]))
        loc = v["trace"][2]
        self.assertTrue(loc["sheet"] and loc["marks"], "위치 마디는 도면에서 강조할 수 있다")
        self.assertIn("FTR", loc["label"])
        self.assertEqual(v["targets"], [{"node_id": v["candidate"]["node_id"], "deviation_id": v["candidate"]["deviation_id"], "entry_id": "c1"}])
        self.assertIn("판정 전", self.view(self.iec("c2"))["trace"][3]["label"], "AI 초안 판정은 그렇다고 적는다")

    def test_judgement_is_saved_in_the_results_and_reaches_the_bundle_and_excel(self):
        iec = self.iec("c2")
        r = self.judge(iec)
        self.assertTrue(r["ok"], r)
        e = self.entry("c2")
        self.assertEqual((e["ie_hint"]["candidate"], e["ie_hint"]["origin"], e["ie_hint"]["category"]), ("yes", "human", "LOIA"))
        self.assertEqual(e["history"][-1]["by"], "검토자A", "판정한 사람을 남긴다")
        c = next(x for x in self.read("ie")["unassigned"] if x["candidate_id"] == iec)
        self.assertEqual((c["judgement"], c["ie_origin"], c["category"]), ("yes", "human", "LOIA"))
        self.assertIn("후보 · 정상운전 교란 예 · 안전기능 도전 예", self.view(iec)["trace"][3]["label"])
        out = os.path.join(self.tmp, "j.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        s = self.read("ie")
        self.assertTrue(self.call("ie.export", {"ver": s["ver"], "rver": s["rver"]})["ok"])
        with open(os.path.join(self.tmp, "j.json"), encoding="utf-8") as fh:
            bc = next(x for x in json.load(fh)["candidates"] if x["candidate_id"] == iec)
        self.assertEqual((bc["judgement"], bc["disturbs"], bc["challenges"], bc["safety_functions"], bc["ie_origin"]),
                         ("yes", "yes", "yes", ["계기용 공기 공급"], "human"))
        import openpyxl
        ws = openpyxl.load_workbook(out)["IE 후보"]
        head = [x.value for x in ws[1]]
        row = next(dict(zip(head, [x.value for x in r])) for r in ws.iter_rows(min_row=2) if r[0].value == iec)
        self.assertEqual((row["판정"], row["작성"], row["일반 범주 제안"]), ("후보", "사람", "LOIA"))

    def test_stale_or_bad_judgements_write_nothing(self):
        iec = self.iec("c2")
        before = self.entry("c2").get("ie_hint")
        self.assertEqual(self.code(self.judge(iec, rver="sha256:old")), (False, "stale"))
        self.assertEqual(self.code(self.judge(iec, seen={"member:" + iec: "sha256:x"})), (False, "stale"))
        self.assertEqual(self.code(self.judge(iec, hint=dict(HINT, category="NO-SUCH"))), (False, "failed"))
        self.assertEqual(self.code(self.judge(iec, hint=dict(HINT, extra="x"))), (False, "bad_args"))
        self.assertEqual(self.entry("c2").get("ie_hint"), before)
        self.engine.settings["reviewer_name"] = ""
        self.assertEqual(self.code(self.judge(iec)), (False, "bad_args"))

    def test_chat_function_needs_the_results_version(self):
        iec = self.iec("c2")
        with self.assertRaises(api.CommandError):
            api_ie.judge_candidate(self.engine, {"iec": iec, "hint": HINT})
        api_ie.judge_candidate(self.engine, {"iec": iec, "hint": HINT, "rver": self.view(iec)["rver"]})
        self.assertEqual(self.entry("c2")["ie_hint"]["origin"], "human")

    def test_chat_function_records_that_the_ai_wrote_the_judgement(self):
        iec = self.iec("c2")
        api_ie.judge_candidate(self.engine, {"iec": iec, "hint": HINT, "rver": self.view(iec)["rver"], "author": "ai"})
        row = self.entry("c2")["history"][-1]
        self.assertEqual((row["by"], row["author"]), ("검토자A", "ai"), "글은 AI가 썼고 누른 사람은 검토자")
        with self.assertRaises(api.CommandError):
            api_ie.judge_candidate(self.engine, {"iec": iec, "hint": HINT, "rver": self.view(iec)["rver"], "author": "robot"})

    # ---------------------------------------------------------------- B5 반려 재현: 확정 그룹 소속 후보 판정
    def test_judging_a_member_of_a_confirmed_group_asks_first_and_checks_the_confirmed_list(self):
        gid = self.human_group()
        self.ok("ie.confirm", group_id=gid)
        iec = self.iec("c1")
        before = self.entry("c1").get("ie_hint")
        r = self.judge(iec, hint=dict(HINT, candidate="no", reason="제외로 바꿈"))
        self.assertTrue(r["ok"], r)
        ask = r["data"].get("ask")
        self.assertTrue(ask, "되묻지 않고 저장함")
        self.assertEqual(ask["groups"], [gid])
        self.assertIn("주급수 상실", ask["message"], "확정이 풀릴 그룹 이름을 보인다")
        self.assertEqual(self.entry("c1").get("ie_hint"), before, "묻는 동안 저장하지 않는다")
        self.assertEqual(self.read("ie")["groups"][0]["status"], "confirmed")
        r = self.judge(iec, hint=dict(HINT, candidate="no", reason="제외로 바꿈"), confirmed=True)
        self.assertEqual(self.code(r), (False, "stale"), "확인한 그룹 목록 없이 confirmed만 보내면 받지 않는다")
        r = self.judge(iec, hint=dict(HINT, candidate="no", reason="제외로 바꿈"), confirmed=True, confirm_groups=["IEG-99"])
        self.assertEqual(self.code(r), (False, "stale"), "확인한 목록과 실제로 확정이 풀릴 목록이 다르면 받지 않는다")
        self.assertEqual(self.entry("c1").get("ie_hint"), before)
        r = self.judge(iec, hint=dict(HINT, candidate="no", reason="제외로 바꿈"), confirmed=True, confirm_groups=ask["groups"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"].get("demoted"), [gid])
        self.assertEqual(self.entry("c1")["ie_hint"]["candidate"], "no")
        self.assertNotEqual(self.read("ie")["groups"][0]["status"], "confirmed")

    def test_judging_a_member_of_a_draft_group_does_not_ask(self):
        gid = self.human_group()
        iec = self.iec("c1")
        r = self.judge(iec, hint=dict(HINT, candidate="no", reason="제외"))
        self.assertTrue(r["ok"] and "ask" not in r["data"], r)
        self.assertEqual(self.entry("c1")["ie_hint"]["candidate"], "no", "초안 그룹은 묻지 않고 저장한다")

    def test_chat_judgement_on_a_confirmed_group_raises_confirm(self):
        gid = self.human_group()
        self.ok("ie.confirm", group_id=gid)
        iec = self.iec("c1")
        a = {"iec": iec, "hint": dict(HINT, candidate="no", reason="제외"), "rver": self.view(iec)["rver"]}
        with self.assertRaises(api.CommandError) as cm:
            api_ie.judge_candidate(self.engine, a)
        self.assertEqual(cm.exception.code, "confirm")
        self.assertIn(gid, str(cm.exception))
        api_ie.judge_candidate(self.engine, dict(a, confirmed=True, confirm_groups=[gid]))
        self.assertEqual(self.entry("c1")["ie_hint"]["candidate"], "no")

    def test_answers_and_terms_follow_the_spec(self):
        v = self.view(self.iec("c1"))
        self.assertEqual(v["choices"]["answer"]["unknown"], "미확인", "설계 시트 1: 예 / 아니오 / 미확인")
        terms = v["choices"]["terms"]
        self.assertIn("disturbs normal operation", terms["disturbs"])
        self.assertIn("challenges safety functions", terms["challenges"])
        self.assertIn("NUREG-2122", terms["source"])


class TwinJudgeTest(OverlapTwinTest):
    def test_one_judgement_goes_to_both_twin_entries(self):
        s = self.read("ie")
        c = s["unassigned"][0]
        v = self.read("ie", "candidate", c["candidate_id"])
        self.assertEqual(len(v["targets"]), 2, "겹친 구간의 같은 원인 항목 둘")
        cell = v["trace"][0]
        self.assertIn("외 1구간", cell["label"])
        other = [t for t in v["targets"] if t["entry_id"] != v["candidate"]["entry_id"]][0]
        self.assertEqual([(t["node_id"], t["deviation_id"]) for t in cell["twins"]], [(other["node_id"], other["deviation_id"])],
                         "다른 구간도 골라 열 수 있다")
        r = self.engine.dispatch("ie.judge", {"iec": c["candidate_id"], "hint": dict(HINT, category="LOMFW"), "rver": v["rver"],
                                              "seen": {"member:" + c["candidate_id"]: v["fp"]}})
        self.assertTrue(r["ok"], r)
        doc, _fp = res.load_fp(sn.load(self.g))
        hints = [e["ie_hint"] for cell in doc["cells"] for e in cell["entries"]]
        self.assertEqual({(h["category"], h["origin"]) for h in hints}, {("LOMFW", "human")})
        self.assertEqual(len(self.read("ie")["unassigned"]), 1, "같은 판정이라 여전히 한 후보로 묶인다")


if __name__ == "__main__":
    unittest.main()
