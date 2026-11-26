"""원래 값 표시로 종류·태그·글자가 바뀐 노드를 옛 글자로 적힌 기록에서도 찾는 시험(HZ-PLN-22 §6.9.4).
지식 참조, 묘비, 고장모드 표, 사람이 지정한 도면 연결, 구간 확정. 실행: python -m unittest tests.test_dexpi_origin_names"""

import copy
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.extract import corrections  # noqa: E402
from hazop.extract.adapters import dexpi_origin as origin  # noqa: E402
from hazop.graph import build, old_names, project  # noqa: E402
from hazop.ie import fmea  # noqa: E402
from hazop.kg import auto, build as kg_build, link  # noqa: E402
from hazop.study import idmap, migrate, nodes  # noqa: E402
from tests.test_dexpi_edit_link import new_file  # noqa: E402
from tests.test_dexpi_origin import read, sheet  # noqa: E402

AT = "2026-11-25T00:00:00Z"


def numbered(ex):
    ex["drawing"]["drawing_number"] = ex["drawing"].get("drawing_number") or "SNP-M-101"
    return ex


def graphs():
    """(표시 없는 파일의 그래프, 표시 있는 파일의 그래프)"""
    return [build.build_graph(numbered(read(x))) for x in (sheet().plain, sheet().marked)]


def by_soid(g):
    return {n["source_object_id"]: n for n in g["nodes"] if n["node_type"] == "drawing_object"}


def named(g, **values):
    """작은 그래프의 노드에 {soid: {tag, read_as}}를 얹는다."""
    g = copy.deepcopy(g)
    for soid, v in values.items():
        by_soid(g)[soid].update(v)
    return g


def small():
    return build.build_graph(new_file())


class GraphTest(unittest.TestCase):

    def test_the_graph_carries_what_the_file_alone_says(self):
        old, new = graphs()
        self.assertTrue(any(origin.PLAIN in n for n in new["nodes"]))
        for soid, n in by_soid(new).items():
            w = by_soid(old)[soid]
            self.assertEqual(dict({k: n[k] for k in ("kind", "tag", "label_text")}, **n.get(origin.PLAIN, {})),
                             {k: w[k] for k in ("kind", "tag", "label_text")})

    def test_a_graph_without_marks_has_no_new_cell(self):
        for g in (graphs()[0], small(), sheet().g):
            self.assertNotIn('"%s"' % origin.PLAIN, json.dumps(g))

    def test_a_value_a_person_changed_has_no_old_name(self):
        ex = numbered(read(sheet().marked))
        sid = next(n["source_object_id"] for n in ex["nodes"] if n["category"] == "instrument" and origin.PLAIN in n)
        for op, value, gone, kept in (("set_tag", {"tag": "PT-999"}, "tag", "kind"), ("set_kind", {"kind": "recorder", "category": "instrument"}, "kind", "tag")):
            fixed = corrections.apply(ex, [corrections.make_op(ex, op, sid, value, "검토자", existing_ops=[])])
            n = by_soid(build.build_graph(fixed))[sid]
            self.assertNotIn(gone, n[origin.PLAIN])
            self.assertIsNone(old_names.old_tag(n) if gone == "tag" else None)
            self.assertIn(kept, n[origin.PLAIN])


class KnowledgeRefTest(unittest.TestCase):

    def resolve(self, g, key):
        end, err = kg_build._PidIndex([g]).resolve("%s:%s" % (g["graph_id"], key))
        return end["source_object_id"], err and err[0]

    def test_every_reference_still_reaches_its_object(self):
        old, new = graphs()
        targets, counts = link._targets([old])
        a, b = kg_build._PidIndex([old]), kg_build._PidIndex([new])
        self.assertTrue(any(by_soid(new)[n["source_object_id"]]["tag"] != n["tag"] for _g, n in targets if n["node_type"] == "drawing_object"))
        for _g, n in targets:
            ref = link.target_ref(old["graph_id"], n, counts)
            self.assertEqual((b.resolve(ref)[0]["source_object_id"], b.resolve(ref)[1]), (a.resolve(ref)[0]["source_object_id"], None), ref)

    def test_old_names_that_are_shared_are_not_resolved(self):
        g = named(small(), PIF1={"tag": "PIC-101", origin.PLAIN: {"tag": "P101"}}, Valve1={"tag": "PI-101", origin.PLAIN: {"tag": "P101"}})
        self.assertEqual(self.resolve(g, "P101"), (None, "ambiguous_tag"))

    def test_an_old_name_that_is_now_the_tag_of_another(self):
        g = named(small(), PIF1={"tag": "PIC-101", origin.PLAIN: {"tag": "T101"}}, Valve1={"tag": "T101"})
        self.assertEqual(self.resolve(g, "T101"), (None, "ambiguous_tag"))
        self.assertEqual(self.resolve(g, "PIC-101"), ("PIF1", None))

    def test_a_new_reference_never_looks_like_the_old_name_of_another(self):
        g = named(small(), PIF1={"tag": "PIC-101", origin.PLAIN: {"tag": "T101"}}, Valve1={"tag": "T101"})
        _t, counts = link._targets([g])
        self.assertEqual(link.target_ref(g["graph_id"], by_soid(g)["Valve1"], counts), g["graph_id"] + "#Valve1")
        self.assertEqual(link.target_ref(g["graph_id"], by_soid(g)["PIF1"], counts), g["graph_id"] + ":PIC-101")
        doc = {"nodes": [{"id": "dsn-1", "node_type": "design_spec"}], "tag_mentions": [{"node_id": "dsn-1", "tags": ["T101", "PIC-101"]}]}
        kinds = auto.APPLY_KIND
        auto.APPLY_KIND = dict(kinds, design_spec="applies_to")
        self.addCleanup(setattr, auto, "APPLY_KIND", kinds)
        links, _notes = auto.tag_links([doc], [g])
        self.assertEqual(sorted(x["from"] for x in links), sorted([g["graph_id"] + "#Valve1", g["graph_id"] + ":PIC-101"]))

    def linked(self, g, ref, soid=None):
        link_row = {"id": "krel-1", "kind": "has_setpoint", "from": ref, "to": "dsn-1", "method": "manual", "knowledge_status": "confirmed",
                    "link_status": "confirmed", "reviewed_by": "검토자", "source": {"document_id": "D-1"}, "mention": None}
        kg = kg_build.build_kg({"project_id": "p", "nodes": [{"id": "dsn-1", "node_type": "setpoint", "knowledge_status": "confirmed",
                                                              "source": {"document_id": "D-1"}}], "links": [link_row]}, [g])
        return kg["links"][0], kg["validation"]["unknowns"]

    def test_a_reference_by_an_old_name_is_kept_but_has_to_be_checked(self):
        """표시가 원래 태그 RC-FT101을 아는 설비에 옛 글자 F101로 적은 관계. 진짜 F101은 사라진 다른 설비일 수 있다."""
        g = named(small(), PIF1={"tag": "RC-FT101", origin.PLAIN: {"tag": "F101"}})
        row, unknowns = self.linked(g, g["graph_id"] + ":F101")
        self.assertEqual((row["ends"]["from"]["source_object_id"], row["recheck"]["changed"]), ("PIF1", ["old_tag"]))
        self.assertIn(("recheck_required", "krel-1"), {(u["check"], u["target"]) for u in unknowns})
        self.assertIn("recheck_required", row["compute_view"]["excluded_reasons"])
        row, _u = self.linked(g, g["graph_id"] + ":RC-FT101")
        self.assertIsNone(row["recheck"])

    def test_an_old_name_recorded_for_another_object(self):
        g = named(small(), PIF1={"tag": "RC-FT101", origin.PLAIN: {"tag": "F101"}})
        idx, ref = kg_build._PidIndex([g]), g["graph_id"] + ":F101"
        self.assertEqual(idx.resolve(ref, "PIF1")[0]["source_object_id"], "PIF1")
        self.assertEqual(idx.resolve(ref, "PIF9")[1][0], "pid_ref_not_found")

    def test_an_unknown_name_is_still_unknown(self):
        self.assertEqual(self.resolve(graphs()[1], "ZZ-1"), (None, "pid_ref_not_found"))


class TombTest(unittest.TestCase):

    def lost_and_back(self, change=None):
        """구성요소 하나를 잃은 뒤 표시 있는 파일에서 다시 나왔을 때 (잃음, 되찾은 묘비)."""
        old, new = graphs()
        sid = next(s for s, n in by_soid(new).items() if n["category"] == "instrument" and n.get(origin.PLAIN, {}).get("tag") not in (None, n["tag"]))
        ns = nodes.propose(old, at=AT)
        eid = by_soid(old)[sid]["entity_id"]
        without = copy.deepcopy(old)
        without["graph_version"] = "v-without"
        without["nodes"] = [n for n in without["nodes"] if n["entity_id"] != eid]
        without["edges"] = [e for e in without["edges"] if eid not in e["nodes"]]
        ns, _p = migrate.migrate_set(ns, without, at=AT)
        tombs = [t for t, r in ns["tombstones"].items() if r["entity_id"] == eid]
        self.assertEqual(len(tombs), 1)
        if change:
            change(by_soid(new)[sid])
        self.recheck = migrate.plan(ns, new)["recheck"]
        return tombs[0] in idmap.compute(ns, new)["found"]

    def test_a_lost_part_is_found_by_its_old_look(self):
        self.assertTrue(self.lost_and_back())
        self.assertTrue(any("되찾음" in x for x in self.recheck.values()), self.recheck)      # 되찾은 구간은 재확인으로 간다

    def test_another_part_at_the_same_id_is_not_found(self):
        self.assertFalse(self.lost_and_back(lambda n: n[origin.PLAIN].update(tag="P555")))
        self.assertFalse(self.lost_and_back(lambda n: n.pop(origin.PLAIN)))


class FmeaTest(unittest.TestCase):

    NS = {"nodes": []}

    def match(self, g, tag):
        pg = project.build("p", [g])
        got = fmea.match_tag(pg, self.NS, tag)
        return got["match"], got["ref"] and got["ref"].partition("#")[2]

    def test_a_row_with_the_old_name(self):
        g = named(small(), PIF1={"tag": "PIC-101", "label_text": "PIC-101", origin.PLAIN: {"tag": "P101", "label_text": "P101"}})
        self.assertEqual(self.match(g, "p101"), ("old_tag", None))     # 같은 글자의 다른 설비일 수 있어 사람이 고른다
        self.assertEqual(self.match(g, "PIC-101"), ("ok", "PIF1"))
        self.assertEqual(self.match(g, "P102"), ("none", None))

    def test_a_row_with_the_old_name_is_kept_and_cannot_be_approved(self):
        g = named(small(), PIF1={"tag": "RC-FT101", "label_text": "RC-FT101", origin.PLAIN: {"tag": "F101", "label_text": "F101"}})
        pg = project.build("p", [g])
        doc = fmea.empty("p")
        doc, report = fmea.import_rows(doc, [{"tag": "F101", "failure_mode": "FTO", "line": 2}], pg, self.NS, "a.xlsx", "검토자", at=AT)
        (rid, row), = doc["rows"].items()
        self.assertEqual((row["tag"], row["match"], row["ref"], report["unmatched"]), ("F101", "old_tag", None, [rid]))
        self.assertEqual(fmea.problems(doc), [])
        picked = fmea.edit_row(doc, rid, {"entity_id": project.nid(g["graph_id"], by_soid(g)["PIF1"]["entity_id"])}, pg, self.NS, at=AT)
        self.assertEqual(picked["rows"][rid]["match"], "human")

    def test_old_names_that_are_shared_and_the_tag_of_another(self):
        one = {"tag": "PIC-101", "label_text": "PIC-101", origin.PLAIN: {"tag": "P101", "label_text": "P101"}}
        self.assertEqual(self.match(named(small(), PIF1=one, Valve1=dict(one, tag="PI-101", label_text="PI-101")), "P101"), ("many", None))
        self.assertEqual(self.match(named(small(), PIF1=one, Valve1={"tag": "P101", "label_text": "P101"}), "P101"), ("many", None))

    def test_rows_of_the_whole_sheet(self):
        old, new = graphs()
        bad = []
        for n in by_soid(old).values():
            was = self.match(old, n["tag"]) if n["tag"] else ("none", None)
            if was[0] == "ok" and self.match(new, n["tag"]) not in (was, ("old_tag", None)):
                bad.append(n["tag"])
        self.assertEqual(bad, [])


class SheetLinkTest(unittest.TestCase):

    def test_a_link_a_person_made_is_still_made(self):
        old, new = graphs()
        end = next(n for n in old["nodes"] if n["kind"] == "continuation" and by_soid(new)[n["source_object_id"]]["label_text"] != n["label_text"])
        op = {"op_id": "l-1", "op": "unlink", "ends": [project.end_ref(old, end)], "by": "검토자", "at": AT}
        for g in (old, new):
            links, skipped = project.match([g], [op])
            self.assertEqual((skipped, [x["op_id"] for x in links if x["op_id"]]), ([], ["l-1"]))
            self.assertEqual([x.get("check") for x in links if x["op_id"]], [None if g is old else "old_label"])   # 옛 글자로 붙인 것은 확인 필요로 남음

    def test_a_connector_whose_text_in_the_file_changed(self):
        old, new = graphs()
        end = next(n for n in old["nodes"] if n["kind"] == "continuation" and by_soid(new)[n["source_object_id"]]["label_text"] != n["label_text"])
        op = {"op_id": "l-1", "op": "unlink", "ends": [project.end_ref(old, end)], "by": "검토자", "at": AT}
        by_soid(new)[end["source_object_id"]].pop(origin.PLAIN)
        self.assertEqual([x["op_id"] for x in project.match([new], [op])[1]], ["l-1"])


class SegmentTest(unittest.TestCase):

    def confirmed(self, g):
        ns = nodes.propose(g, at=AT)
        for n in ns["nodes"]:
            n.update(state="confirmed", confirmed={"by": "검토자", "at": AT})
        ns["member_digest"] = migrate.node_digests(g, {n["node_id"]: n["members"] for n in ns["nodes"]})
        return ns

    def after(self, old, new):
        new["graph_version"] = "v-new"
        out, p = migrate.migrate_set(self.confirmed(old), new, at=AT)
        return {n["node_id"]: n["state"] for n in out["nodes"]}, p["recheck"], out

    def test_only_tags_and_texts_changed(self):
        old = small()
        new = named(old, PIF1={"tag": "PIC-101", "label_text": "PIC-101", origin.PLAIN: {"tag": by_soid(old)["PIF1"]["tag"]}})
        states, recheck, out = self.after(old, new)
        self.assertEqual((set(states.values()), recheck), ({"confirmed"}, {}))
        self.assertEqual(out["member_digest"], migrate.node_digests(new, {n["node_id"]: n["members"] for n in out["nodes"]}))

    def test_the_tag_in_the_file_itself_changed(self):
        old = small()
        new = named(old, PIF1={"tag": "PIC-101", origin.PLAIN: {"tag": "T999"}})
        self.assertTrue(self.after(old, new)[1], "재확인(상태는 그대로, 분석 판을 올림: 구간 확정 단계를 없앰, 구간 규격 §0.2)")

    def test_the_kind_changed(self):
        old = small()
        new = named(old, Pump1={"kind": "compressor", origin.PLAIN: {"kind": "pump"}})
        self.assertTrue(self.after(old, new)[1], "재확인(상태는 그대로, 분석 판을 올림: 구간 확정 단계를 없앰, 구간 규격 §0.2)")

    REASON = "구성요소의 종류·태그·흐름·연결·정상 위치·고장 위치가 바뀜"

    def filled(self, g, soid=None):
        seg = next(n for n in g["nodes"] if n["node_type"] == "pipe_segment" and not n["flow_direction"])
        a, b = [e["node"] for e in g["edges"] if e.get("segment") == seg["entity_id"]]
        seg.update(flow_direction={"from": a, "to": b, "from_end": "source", "to_end": "target", "basis": "human"})
        seg[origin.PLAIN] = {"flow_direction": None}
        return g

    def test_the_reason_says_what_the_marks_changed(self):
        old = small()
        kind = {"Pump1": {"kind": "compressor", origin.PLAIN: {"kind": "pump"}}}
        for new, what in ((named(old, **kind), "종류 바뀜"), (self.filled(named(old)), "흐름 채워짐"), (self.filled(named(old, **kind)), "종류 바뀜, 흐름 채워짐")):
            _s, recheck, out = self.after(old, new)
            self.assertIn(self.REASON + " (원래 값 표시: %s)" % what, set(recheck.values()))
            self.assertIn(self.REASON + " (원래 값 표시: %s)" % what, set(out["history"][-1]["detail"]["recheck"].values()))

    def test_the_reason_of_a_change_that_is_not_only_the_marks(self):
        old = small()
        new = named(old, Pump1={"kind": "compressor", origin.PLAIN: {"kind": "pump"}}, PIF1={"tag": "XX-1"}, Valve1={"tag": "YY-1"})
        self.assertEqual(set(self.after(old, new)[1].values()), {self.REASON})
        self.assertEqual(set(self.after(old, named(old, Pump1={"kind": "compressor"}))[1].values()), {self.REASON})

    def test_the_flow_changed(self):
        old = small()
        new = named(old, PIF1={"tag": "PIC-101", origin.PLAIN: {"tag": by_soid(old)["PIF1"]["tag"]}})
        seg = next(n for n in new["nodes"] if n["node_type"] == "pipe_segment" and not n["flow_direction"])
        a, b = [e["node"] for e in new["edges"] if e.get("segment") == seg["entity_id"]]
        seg["flow_direction"] = {"from": a, "to": b, "from_end": "source", "to_end": "target", "basis": "human"}
        self.assertTrue(self.after(old, new)[1], "재확인(상태는 그대로, 분석 판을 올림: 구간 확정 단계를 없앰, 구간 규격 §0.2)")

    def test_a_changed_tag_without_a_mark(self):
        old = small()
        self.assertTrue(self.after(old, named(old, PIF1={"tag": "PIC-101"}))[1], "재확인(구간 확정 단계를 없앰, 구간 규격 §0.2)")

    def test_the_sheet_it_was_exported_from_is_not_touched(self):
        s = sheet()
        g = copy.deepcopy(s.g)
        ns = self.confirmed(s.g)
        self.assertEqual(json.dumps(build.build_graph(s.ex), sort_keys=True), json.dumps(g, sort_keys=True))
        self.assertIs(migrate.migrate_set(ns, build.build_graph(s.ex), at=AT)[0], ns)


if __name__ == "__main__":
    unittest.main()
