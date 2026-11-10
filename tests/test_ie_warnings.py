"""IE 인계 묶음 품질 경고 5종(specs/ie-output-design.md §3.2 시트 8)과 요약. 경고마다 걸리는 예와 안 걸리는 예를 둔다.
두 도면 합성 그래프와 가짜 결과만 쓴다. 실행: python -m unittest tests.test_ie_warnings
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl  # noqa: E402

from hazop.ie import bundle as ib  # noqa: E402
from hazop.ie import bundle_xlsx as ix  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_ie_bundle import build, entries_by_status, ie_sample  # noqa: E402

SHEET = "graph-SNP-M-102"
TANK_101, TANK_102 = "graph-SNP-M-101#E", "graph-SNP-M-102#E"


def add_node(pg, ns, soid, kind, category, tag, node_id=None):
    """그래프에 구성요소를 더하고(node_id를 주면 그 구간에도 넣고) 안정 참조를 돌려준다."""
    pg["nodes"].append({"entity_id": "%s/%s" % (SHEET, soid), "sheet": SHEET, "source_object_id": soid, "kind": kind,
                        "category": category, "tag": tag})
    if node_id:
        next(n for n in ns["nodes"] if n["node_id"] == node_id)["members"].append("%s/%s" % (SHEET, soid))
    return "%s#%s" % (SHEET, soid)


class Case(unittest.TestCase):
    def setUp(self):
        self.r, self.ns, self.pg = ie_sample()
        self.e = entries_by_status(self.r)
        self.home = {e["entry_id"]: c["node_id"] for c in self.r["cells"] for e in c["entries"]}
        self.other = next(n["node_id"] for n in self.ns["nodes"] if n["node_id"] != self.home["c1"])

    def warnings(self, kind):
        self.assertEqual(res.validate(self.r, self.ns), [])
        b = build(self.r, self.ns, self.pg)
        return [w for w in b["warnings"] if w["kind"] == kind]

    def count(self, kind):
        b = build(self.r, self.ns, self.pg)
        return next(s["count"] for s in b["warning_summary"] if s["kind"] == kind)


class SafeguardAsCauseTest(Case):
    def test_pump_cause_that_nothing_relies_on_is_quiet(self):
        self.assertEqual(self.warnings("safeguard_as_cause"), [])

    def test_self_acting_protective_device_as_cause_warns(self):
        psv = add_node(self.pg, self.ns, "PSV1", "psv", "valve", "PSV-1", self.other)
        self.e["c4"]["cause_refs"] = [{"ref": psv, "failure_mode": "FTO"}]
        (w,) = self.warnings("safeguard_as_cause")
        self.assertEqual((w["target"], w["basis"]), ("c4", "IChemE Hazards 26"))
        self.assertIn("PSV-1", w["text"])

    def test_cause_at_another_entrys_safeguard_target_warns_and_names_that_entry(self):
        self.e["c3"]["safeguards"] = [{"text": "탱크 수위 여유", "role": "mitigative", "actuation": "passive",
                                       "refs": [{"ref": TANK_101}], "ipl": None}]
        (w,) = self.warnings("safeguard_as_cause")
        self.assertEqual(w["target"], "c1")
        self.assertIn("SNP-M-101-E", w["text"])
        self.assertIn("c3", w["text"])

    def test_unapproved_entrys_safeguard_target_does_not_count(self):
        self.e["p1"]["safeguards"] = [{"text": "탱크", "role": "mitigative", "refs": [{"ref": TANK_101}], "ipl": None}]
        self.assertEqual(self.warnings("safeguard_as_cause"), [])


class BoundaryCutTest(Case):
    def test_consequence_inside_its_own_node_is_quiet(self):
        self.e["c1"]["consequence_refs"] = [{"ref": TANK_101}]
        self.assertEqual(self.warnings("boundary_cut"), [])

    def test_consequence_into_a_node_whose_approved_entry_covers_the_target_is_quiet(self):
        self.e["c1"]["consequence_refs"] = [{"ref": TANK_102}]
        self.e["b1c"]["cause_refs"] = [{"ref": TANK_102}]
        self.assertEqual(self.home["b1c"], self.other)
        self.assertEqual(self.warnings("boundary_cut"), [])

    def test_consequence_into_a_node_without_approved_entries_warns(self):
        self.e["c1"]["consequence_refs"] = [{"ref": TANK_102}]
        self.e["b1c"]["status"] = "revised"
        (w,) = self.warnings("boundary_cut")
        self.assertEqual((w["target"], w["basis"]), ("c1", "IChemE Hazards 26, PSAM14 383"))
        self.assertIn("SNP-M-102-E", w["text"])
        self.assertIn(self.other, w["text"])

    def test_consequence_at_a_component_outside_every_node_warns(self):
        loose = add_node(self.pg, self.ns, "V9", "manual_valve", "valve", "V-9")
        self.e["c1"]["consequence_refs"] = [{"ref": loose}]
        (w,) = self.warnings("boundary_cut")
        self.assertIn("V-9", w["text"])
        self.assertIn("검토구간 없음", w["text"])

    def test_target_missing_from_the_graph_is_reported_for_recheck(self):
        self.e["c1"]["consequence_refs"] = [{"ref": "graph-SNP-M-999#X"}]
        (w,) = self.warnings("boundary_cut")
        self.assertIn("대상 없음(재확인): graph-SNP-M-999#X", w["text"])

    def test_unrelated_approved_entry_in_the_receiving_node_does_not_silence_it(self):
        self.e["c1"]["consequence_refs"] = [{"ref": TANK_102}]
        self.assertEqual((self.home["b1c"], self.e["b1c"]["status"]), (self.other, "approved"))
        (w,) = self.warnings("boundary_cut")
        self.assertIn("그 대상을 다룬 승인 항목이 없", w["text"])
        self.e["b1c"]["consequence_refs"] = [{"ref": TANK_102}]
        self.assertEqual(self.warnings("boundary_cut"), [])


class FmeaPendingTest(Case):
    def test_no_instrument_in_analysed_nodes_no_row_and_zero_in_summary(self):
        self.assertEqual(self.warnings("fmea_pending"), [])
        self.assertEqual(self.count("fmea_pending"), 0)

    def test_one_row_for_the_bundle_listing_nodes_with_instruments(self):
        for nid in (self.home["c1"], self.other):
            add_node(self.pg, self.ns, "PT-" + nid, "transmitter", "instrument", "PT-" + nid, nid)
        (w,) = self.warnings("fmea_pending")
        self.assertEqual(w["target"], ", ".join(sorted((self.home["c1"], self.other))))
        self.assertIn("전기·제어 구간 2개: FMEA 대조 전", w["text"])
        self.assertEqual(self.count("fmea_pending"), 2)

    def test_electrically_driven_valve_counts_and_a_spanning_node_counts_once(self):
        add_node(self.pg, self.ns, "MOV1", "motor_operated_valve", "valve", "MOV-1", self.home["c1"])
        self.pg["nodes"].append({"entity_id": "graph-SNP-M-101/PT9", "sheet": "graph-SNP-M-101",
                                 "source_object_id": "PT9", "kind": "transmitter", "category": "instrument",
                                 "tag": "PT-9"})
        next(n for n in self.ns["nodes"] if n["node_id"] == self.home["c1"])["members"].append("graph-SNP-M-101/PT9")
        (w,) = self.warnings("fmea_pending")
        self.assertEqual((w["target"], self.count("fmea_pending")), (self.home["c1"], 1))

    def test_manual_valves_and_tanks_alone_are_not_electrical(self):
        add_node(self.pg, self.ns, "V1", "manual_valve", "valve", "V-1", self.home["c1"])
        self.assertEqual(self.warnings("fmea_pending"), [])

    def test_instrument_node_without_approved_entries_is_not_counted(self):
        add_node(self.pg, self.ns, "PT1", "transmitter", "instrument", "PT-1", self.other)
        self.e["b1c"]["status"] = "revised"
        self.assertEqual(self.warnings("fmea_pending"), [])


class SummaryAndGuideTest(Case):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="hazop-ie-warn-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        psv = add_node(self.pg, self.ns, "PSV1", "psv", "valve", "PSV-1", self.other)
        add_node(self.pg, self.ns, "PT1", "transmitter", "instrument", "PT-1", self.home["c1"])
        loose = add_node(self.pg, self.ns, "V9", "manual_valve", "valve", "V-9")
        self.e["c4"]["cause_refs"] = [{"ref": psv}]
        self.e["c1"]["consequence_refs"] = [{"ref": loose}]
        self.b = build(self.r, self.ns, self.pg)

    def test_all_five_kinds_in_sheet_order_with_counts(self):
        self.assertEqual(list(ib.WARNING_KINDS), ["safeguard_as_cause", "mitigated_consequence", "actuation_unknown",
                                                  "boundary_cut", "fmea_pending"])
        self.assertEqual([s["kind"] for s in self.b["warning_summary"]], list(ib.WARNING_KINDS))
        self.assertEqual({w["kind"] for w in self.b["warnings"]}, set(ib.WARNING_KINDS))
        rows = {k: sum(w["kind"] == k for w in self.b["warnings"]) for k in ib.WARNING_KINDS}
        got = {s["kind"]: s["count"] for s in self.b["warning_summary"]}
        self.assertEqual({k: got[k] for k in got if k != "fmea_pending"},
                         {k: rows[k] for k in rows if k != "fmea_pending"})
        self.assertEqual((rows["fmea_pending"], got["fmea_pending"]), (1, 1))

    def test_summary_line_counts_by_kind(self):
        line = ib.warning_summary_text(self.b)
        self.assertIn("보호설비 고장이 원인 칸에 있음 1건", line)
        self.assertIn("구간 경계 결과 끊김 1건", line)
        self.assertTrue(line.endswith("전기·제어 구간 1개: FMEA 대조 전"), line)

    def test_sheet_names_every_kind_and_guide_explains_them(self):
        wb = openpyxl.load_workbook(ix.export(os.path.join(self.tmp, "ie.xlsx"), self.b)[0])
        names = {row[0].value for row in wb["품질 경고"].iter_rows(min_row=2)}
        self.assertEqual(names, {label for label, _ in ib.WARNING_KINDS.values()})
        guide = {row[0].value: row[1].value for row in wb["읽는 법"].iter_rows(min_row=2)}
        self.assertEqual(guide["품질 경고 요약"], ib.warning_summary_text(self.b))
        for label, _ in ib.WARNING_KINDS.values():
            self.assertIn(label, guide["품질 경고 읽는 법"])
        self.assertIn("막지 않", guide["품질 경고 읽는 법"])
        self.assertIn("원인 문장에만 적은", guide["품질 경고 읽는 법"])
        self.assertIn("전동기", guide["품질 경고 읽는 법"])
        psv_warning = next(w["text"] for w in self.b["warnings"] if w["kind"] == "safeguard_as_cause")
        self.assertIn("[추론]", psv_warning)

    def test_summary_counts_against_hand_counted_values(self):
        self.assertEqual({s["kind"]: s["count"] for s in self.b["warning_summary"]},
                         {"safeguard_as_cause": 1, "mitigated_consequence": 1, "actuation_unknown": 3,
                          "boundary_cut": 1, "fmea_pending": 1})
        self.assertEqual(ib.warning_summary_text(self.b),
                         "보호설비 고장이 원인 칸에 있음 1건 · 완화 결과로 적힘 1건 · 작동 방식 미확인 3건 · "
                         "구간 경계 결과 끊김 1건 · 전기·제어 구간 1개: FMEA 대조 전")

    def test_same_input_same_warnings(self):
        self.assertEqual(ib.dumps(build(self.r, self.ns, self.pg)), ib.dumps(self.b))

    def test_summary_is_zero_everywhere_when_nothing_is_wrong(self):
        for e in self.e.values():
            e["status"] = "approved" if e["entry_id"] == "c1" else "revised"
        self.e["c1"]["consequence_refs"] = []
        self.pg["nodes"] = [n for n in self.pg["nodes"] if n.get("category") != "instrument"]
        b = build(self.r, self.ns, self.pg)
        self.assertEqual(b["warnings"], [])
        self.assertEqual([s["count"] for s in b["warning_summary"]], [0] * 5)
        self.assertTrue(ib.warning_summary_text(b).endswith("전기·제어 구간 없음"))


if __name__ == "__main__":
    unittest.main()
