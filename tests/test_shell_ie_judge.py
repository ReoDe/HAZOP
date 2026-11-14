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
        self.assertIn("후보 · 교란 예 · 도전 예", self.view(iec)["trace"][3]["label"])
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


class TwinJudgeTest(OverlapTwinTest):
    def test_one_judgement_goes_to_both_twin_entries(self):
        s = self.read("ie")
        c = s["unassigned"][0]
        v = self.read("ie", "candidate", c["candidate_id"])
        self.assertEqual(len(v["targets"]), 2, "겹친 구간의 같은 원인 항목 둘")
        r = self.engine.dispatch("ie.judge", {"iec": c["candidate_id"], "hint": dict(HINT, category="LOMFW"), "rver": v["rver"],
                                              "seen": {"member:" + c["candidate_id"]: v["fp"]}})
        self.assertTrue(r["ok"], r)
        doc, _fp = res.load_fp(sn.load(self.g))
        hints = [e["ie_hint"] for cell in doc["cells"] for e in cell["entries"]]
        self.assertEqual({(h["category"], h["origin"]) for h in hints}, {("LOMFW", "human")})
        self.assertEqual(len(self.read("ie")["unassigned"]), 1, "같은 판정이라 여전히 한 후보로 묶인다")


if __name__ == "__main__":
    unittest.main()
