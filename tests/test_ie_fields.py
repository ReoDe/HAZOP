"""초기사건 인계 P1(⑤ 보강) 시험: cause_kind·consequence_basis·ie_hint·보호수단 actuation, 품질 경고 2종,
고정 응답 → 저장 → Excel. 근거: 기획서/초기사건-출력설계.md §5, §8 P1. 가짜 클라이언트만 쓴다(네트워크 없음).
실행: python -m unittest tests.test_ie_fields
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl  # noqa: E402

from hazop.export import study_xlsx as sx  # noqa: E402
from hazop.study import ai_cells as ac  # noqa: E402
from hazop.study import refs  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests import test_study_export as tse  # noqa: E402
from tests.test_ai_cells import AT, Base, FakeClient, answer, completed, scenario  # noqa: E402

IE = {"candidate": "yes", "disturbs": "yes", "challenges": "yes", "safety_functions": ["노심 냉각"],
      "category": "LOCCW", "reason": "기기냉각수 전체 상실로 원자로 정지와 노심 냉각 도전"}


def new_scenario(**kw):
    s = scenario(cause="기기냉각수 펌프 정지", consequence="기기냉각수 전체 상실로 원자로냉각재펌프 밀봉 냉각 상실",
                 cause_kind="support", ie_hint=dict(IE),
                 safeguards=[{"text": "PSV 개방", "role": "mitigative", "actuation": "passive", "entity_ids": []},
                             {"text": "운전원 예비 펌프 기동", "role": "mitigative", "actuation": "operator",
                              "entity_ids": []}])
    s.update(kw)
    return s


class OldFileTest(unittest.TestCase):
    def test_old_entry_reads_as_unknown(self):
        e = tse._entry("x", "approved")
        self.assertEqual(res.cause_kind_label(e), "미확인")
        self.assertEqual(res.basis_label(e), "비완화 여부 미확인")
        self.assertEqual(refs.safeguard_items(e)[0]["actuation"], "unknown")
        self.assertEqual(sx.ie_columns(e), {"ie_judgement": "미판정", "ie_category": "", "ie_origin": ""})
        r, ns, *_ = tse.sample()
        self.assertEqual(res.validate(r, ns), [])

    def test_validate_flags_bad_values_but_not_table_changes(self):
        r, ns, *_ = tse.sample()
        e = next(c for c in r["cells"] if c["entries"])["entries"][0]
        e.update(cause_kind="nope", consequence_basis="mitigated",
                 ie_hint=dict(IE, category="OLDCODE", origin="ai_draft", status="draft"))
        bad = res.validate(r, ns)
        self.assertTrue(any("cause_kind" in p for p in bad), bad)
        self.assertTrue(any("consequence_basis" in p for p in bad), bad)
        self.assertFalse(any("category" in p for p in bad), bad)  # 기준표가 바뀌어도 저장본을 버리지 않게


class AiResponseTest(Base):
    def run_one(self, *scenarios):
        client = FakeClient(completed([answer("D01", list(scenarios))]))
        ur = ac.run_unit(client, self.unit("D01"), self.ctx(), self.devs, AT)
        self.assertEqual(ur["cells"]["D01"]["status"], "ok", ur)
        return client, ur["cells"]["D01"]["entries"]

    def test_prompt_and_schema_carry_table_codes(self):
        self.assertIn("LOCCW(기기냉각수 완전 상실)", ac.SYSTEM_PROMPT)
        self.assertIn("목록 밖 코드는 쓰지 않는다", ac.SYSTEM_PROMPT)
        self.assertIn("보호수단이 하나도 작동하지 않는다고 보고", ac.SYSTEM_PROMPT)
        props = ac.SCENARIO_SCHEMA["properties"]
        self.assertEqual(props["safeguards"]["items"]["properties"]["actuation"]["enum"], list(refs.ACTUATIONS))
        self.assertIn("LOCCW", props["ie_hint"]["properties"]["category"]["anyOf"][0]["enum"])
        self.assertEqual(set(ac.SCENARIO_SCHEMA["required"]), set(props))

    def test_new_fields_saved(self):
        _, (e,) = self.run_one(new_scenario())
        self.assertEqual(e["cause_kind"], "support")
        self.assertEqual(e["consequence_basis"], "unmitigated")
        self.assertEqual([s["actuation"] for s in e["safeguards"]], ["passive", "operator"])
        self.assertEqual(e["ie_hint"], dict(IE, origin="ai_draft", status="draft"))
        self.assertEqual(res.quality_warnings(e), [])

    def test_out_of_table_code_dropped_with_warning(self):
        _, (e,) = self.run_one(new_scenario(ie_hint=dict(IE, category="LOFW-X"), cause_kind="weather",
                                            safeguards=[{"text": "경보", "role": "preventive", "actuation": "remote",
                                                         "entity_ids": []}]))
        self.assertIsNone(e["ie_hint"]["category"])
        self.assertNotIn("cause_kind", e)
        self.assertEqual(e["safeguards"][0]["actuation"], "unknown")
        w = e["ai_basis"]["warnings"]
        self.assertIn("기준표에 없는 초기사건 범주 코드를 뺌: LOFW-X", w)
        self.assertIn("모르는 원인 유형을 뺌: weather", w)
        self.assertIn("모르는 보호수단 작동 방식을 미확인으로 둠: remote", w)

    def test_mitigated_consequence_not_marked_unmitigated(self):
        _, (e,) = self.run_one(new_scenario(consequence="경보 후 회복, 영향 없음"))
        self.assertNotIn("consequence_basis", e)
        self.assertEqual([k for k, _ in res.quality_warnings(e)], ["mitigated_consequence"])
        self.assertTrue(res.quality_line(*res.quality_warnings(e)[0]).startswith("완화 결과로 적힘: 결과에 '"))

    def test_malfunction_wording_is_not_mitigated(self):
        _, (e,) = self.run_one(new_scenario(consequence="제어밸브가 오작동하여 배관 과압"))
        self.assertEqual(e["consequence_basis"], "unmitigated")

    def test_old_response_shape_still_reads(self):
        _, (e,) = self.run_one(scenario())
        for k in ("cause_kind", "consequence_basis", "ie_hint"):
            self.assertNotIn(k, e)
        self.assertEqual(e["safeguards"], ["보호"])
        self.assertTrue(res.quality_line(*res.quality_warnings(e)[0]).startswith("작동 방식 미확인: 보호수단 1개"))
        self.assertEqual(res.quality_warnings(dict(e, safeguards=["", "  ", {"text": ""}])), [], "빈 줄은 보호수단이 아님")

    def test_saved_and_exported(self):
        _, (e,) = self.run_one(new_scenario(ie_hint=dict(IE, category="NOPE")))
        r, ns, pg, span_node, _ = tse.sample()
        cell = next(c for c in r["cells"] if c["node_id"] == span_node and c["deviation_id"] == "D01")
        cell["entries"].append(dict(e, entry_id="ie-1"))
        tmp = tempfile.mkdtemp(prefix="hazop-ie-")
        try:
            path = res.write(os.path.join(tmp, "r.json"), r)
            back = res.read(path)
            self.assertEqual(res.validate(back, ns), [])
            out, _ = sx.export(os.path.join(tmp, "o.xlsx"), back, ns, pg, tse.DEVS, now=tse.NOW)
            ws = openpyxl.load_workbook(out)[sx.SHEETS[2]]
            head = [c.value for c in ws[1]]
            rows = [dict(zip(head, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        for title in ("원인 유형", "결과 기준", "초기사건 판정", "일반 범주", "판정 작성"):
            self.assertIn(title, head)
        row = next(x for x in rows if x["원인"] == "기기냉각수 펌프 정지")
        self.assertEqual(row["원인 유형"], "지원계통 상실")
        self.assertEqual(row["결과 기준"], "비완화")
        self.assertTrue(row["초기사건 판정"].startswith("후보 · 교란 예 · 도전 예"))
        self.assertEqual(row["일반 범주"], "미분류")
        self.assertEqual(row["판정 작성"], "AI 초안")
        self.assertEqual(row["보호수단"], "[자체작동] PSV 개방\n[운전원] 운전원 예비 펌프 기동")
        self.assertIn("기준표에 없는 초기사건 범주 코드를 뺌: NOPE", row["근거 경고"])
        old = next(x for x in rows if x["원인"] == "원인 a1")
        self.assertEqual((old["원인 유형"], old["결과 기준"], old["초기사건 판정"]), ("미확인", "비완화 여부 미확인", "미판정"))
        self.assertEqual(old["보호수단"], "[미확인] 보호수단 1")


class EditTest(unittest.TestCase):
    def setUp(self):
        self.r, self.ns, _pg, self.node, _ = tse.sample()
        self.key = (self.node, "D01", "a1")  # 승인 항목

    def entry(self, r):
        return res._entry(r, *self.key)

    def test_set_ie_hint_keeps_approval(self):
        out = res.set_ie_hint(self.r, *self.key, dict(IE, category="SORV"), at=AT)
        e = self.entry(out)
        self.assertEqual(e["status"], "approved")
        self.assertEqual(e["ie_hint"]["origin"], "human")
        self.assertEqual(e["ie_hint"]["status"], "confirmed")
        self.assertEqual(e["history"][-1], {"at": AT, "op": "ie_hint", "status": "approved", "before": None})
        self.assertEqual(self.entry(res.set_ie_hint(out, *self.key, dict(IE), at=AT))["status"], "approved")
        self.assertNotIn("ie_hint", self.entry(self.r))
        self.assertEqual(sx.ie_columns(e)["ie_origin"], "사람 확정")
        self.assertIn("초기사건 판정", sx._history_text(e))

    def test_human_ie_hint_survives_rerun(self):
        key = (self.node, "D01", "a2")  # 제안 항목
        out = res.set_ie_hint(self.r, *key, dict(IE), at=AT)
        self.assertEqual(res._entry(out, *key)["status"], "revised")
        ur = {"unit_id": "u", "node_id": self.node, "status": "ok", "error": None, "usage": {}, "cost_usd": 0.0,
              "model": "m", "at": AT, "cells": {"D01": {"status": "ok", "error": None, "note": None, "entries": [],
                                                        "applicable": True}}}
        again = ac.apply_unit(out, ur)
        self.assertEqual(res._entry(again, *key)["ie_hint"]["origin"], "human")

    def test_set_ie_hint_rejects_unknown_code(self):
        with self.assertRaises(ValueError):
            res.set_ie_hint(self.r, *self.key, dict(IE, category="BOGUS"))
        with self.assertRaises(ValueError):
            res.set_ie_hint(self.r, *self.key, dict(IE, candidate="maybe"))

    def test_ie_hint_not_editable_via_edit_entry(self):
        with self.assertRaises(ValueError):
            res.edit_entry(self.r, *self.key, {"ie_hint": dict(IE)})

    def test_cause_kind_and_basis_edit_marks_revised(self):
        out = res.edit_entry(copy.deepcopy(self.r), *self.key, {"cause_kind": "human", "consequence_basis": "unmitigated"})
        e = self.entry(out)
        self.assertEqual((e["cause_kind"], e["consequence_basis"], e["status"]), ("human", "unmitigated", "revised"))
        with self.assertRaises(ValueError):
            res.edit_entry(self.r, *self.key, {"cause_kind": "weather"})

    def test_actuation_validated(self):
        with self.assertRaises(ValueError):
            res.edit_entry(self.r, *self.key, {"safeguards": [{"text": "a", "role": "unknown", "actuation": "x",
                                                                "refs": [], "ipl": None}]})
        out = res.edit_entry(self.r, *self.key, {"safeguards": [{"text": "PSV", "role": "mitigative",
                                                                  "actuation": "passive", "refs": [], "ipl": None,
                                                                  "origin": "human"}]})
        self.assertEqual(res.quality_warnings(self.entry(out)), [])


if __name__ == "__main__":
    unittest.main()
