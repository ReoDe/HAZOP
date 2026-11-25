"""DEXPI 파일에 실은 원래 값 표시(HZ-PLN-22 §6.9)를 곁 파일 없이 되읽는 시험. 실행: python -m unittest tests.test_dexpi_origin

쓰기는 아직 내보내기에 붙지 않았으므로 시험용으로 표시를 얹은 파일(hazop.export.dexpi_marks)을 쓴다.
"""

import copy
import json
import os
import re
import sys
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.export import dexpi_export, dexpi_marks  # noqa: E402
from hazop.extract import corrections, dexpi_map  # noqa: E402
from hazop.extract.adapters import dexpi_import, dexpi_origin as origin, dexpi_read  # noqa: E402
from hazop.graph import build  # noqa: E402
from tests.test_dexpi_export import SNP, dexpi_pair, fixture, snp_pair  # noqa: E402

NODE_KEYS = ("kind", "tag", "label_text")


def canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def read(xml):
    return dexpi_import.extract_bytes(xml, "x.xml")[0]


def export(pair):
    ex, g = pair
    return dexpi_export.export_drawing(g, ex, require_confirmed_number=False, name="x")


class Sheet:
    """도면 하나를 내보낸 것: plain 바이트와 표시를 얹은 바이트, 그래프의 원래 값."""

    def __init__(self, pair):
        self.ex, self.g = pair
        self.export = export(pair)
        self.plain = self.export.xml
        self.marks = dexpi_marks.marks_of(self.export, self.g)
        self.marked = dexpi_marks.add(self.plain, self.marks)
        by_id = {n["entity_id"]: n for n in self.g["nodes"]}
        self.want = {e["dexpi_id"]: by_id[e["entity_id"]] for e in self.export.sidecar["entities"]}
        self.pipes = {p["dexpi_id"]: by_id[p["entity_id"]] for p in self.export.sidecar["pipes"]}
        self.dexpi_of = {e["entity_id"]: e["dexpi_id"] for e in self.export.sidecar["entities"]}

    def with_marks(self, change):
        marks = copy.deepcopy(self.marks)
        change(marks)
        return dexpi_marks.add(self.plain, marks)

    def differing(self, ex):
        """원래 값과 다른 것 [(id, 칸)]."""
        out = []
        got = {n["source_object_id"]: n for n in ex["nodes"]}
        for oid, w in self.want.items():
            out += [(oid, k) for k in NODE_KEYS if (w[k] or "") != (got[oid][k] or "")]
        soid = {n["local_id"]: n["source_object_id"] for n in ex["nodes"]}
        rels = {r["source_object_id"]: r for r in ex["relations"]}
        for oid, w in self.pipes.items():
            f, r = w["flow_direction"], rels[oid]
            g = r["flow_direction"]
            want = (self.dexpi_of[f["from"]], self.dexpi_of[f["to"]], f["basis"]) if f else None
            if want != ((soid[g["from"]], soid[g["to"]], g["basis"]) if g else None):
                out.append((oid, "flow"))
            if (w["label_text"] or "") != r["label_text"]:
                out.append((oid, "label_text"))
        return out

    def mismatches(self, ex):
        return [u for u in ex["validation"]["unknowns"] if u["check"] == origin.CHECK]


_SHEET = {}


def sheet():
    """SNP-M-101: 근사 클래스, 계기 태그, 원본 글자, 흐름이 모두 있다."""
    if "s" not in _SHEET:
        _SHEET["s"] = Sheet(snp_pair(next(p for p in SNP if "M-101" in p)))
    return _SHEET["s"]


class RoundTripTest(unittest.TestCase):

    def test_every_sample_reads_back_as_it_was_without_the_sidecar(self):
        for path in SNP:
            with self.subTest(path=os.path.basename(path)):
                s = Sheet(snp_pair(path))
                self.assertTrue(s.differing(read(s.plain)))
                ex = read(s.marked)
                self.assertEqual(s.differing(ex), [])
                self.assertEqual(s.mismatches(ex), [])
                self.assertEqual(ex["validation"]["blockers"], [])
                self.assertNotIn("dexpi_actuator_kind_unknown", {u["check"] for u in ex["validation"]["unknowns"]})

    def test_a_flow_against_the_order_of_the_drawing(self):
        ex = copy.deepcopy(sheet().ex)
        r = next(r for r in ex["relations"] if r["flow_direction"] and r["flow_direction"]["basis"] == "source_to_target"
                 and not any(n["kind"] in ("continuation", "check_valve") for n in ex["nodes"] if n["local_id"] in (r["flow_direction"]["from"], r["flow_direction"]["to"])))
        f = r["flow_direction"]
        r["flow_direction"] = {"from": f["to"], "to": f["from"], "from_end": f["to_end"], "to_end": f["from_end"], "basis": f["basis"]}
        s = Sheet((ex, build.build_graph(ex)))
        self.assertTrue(any(p["swapped"] for p in s.export.sidecar["pipes"]))
        self.assertEqual(s.differing(read(s.marked)), [])

    def test_a_marked_file_passes_the_checks(self):
        root = dexpi_read.parse_safely(sheet().marked)
        self.assertEqual((dexpi_read.check_structure(root, definitions=True), dexpi_read.check_references(root)), ([], []))

    def test_restored_values_are_used_for_everything_that_hangs_on_them(self):
        s = sheet()
        ex = read(s.marked)
        by_tag = {n["tag"]: n for n in ex["nodes"] if n["tag"]}
        sg = next(n for n in ex["nodes"] if n["kind"] == "steam_generator")
        self.assertEqual((sg["classification"], sg["category"], sg["attributes"]["kind"]), ("classified", "equipment", "steam_generator"))
        inst = next(n for n in ex["nodes"] if n["category"] == "instrument")
        self.assertEqual(inst["attributes"]["tag"], inst["tag"])
        self.assertIsNotNone(build.build_graph(ex)["nodes"][0])
        self.assertEqual(len(by_tag), len([n for n in ex["nodes"] if n["tag"]]))
        restored = {u["target"] for u in ex["validation"]["unknowns"] if u["check"] in ("dexpi_unmapped_class", "dexpi_tag_not_unique")}
        self.assertEqual(restored, set())

    def test_what_the_file_alone_says_is_kept_beside_only_where_the_mark_changed_it(self):
        s = sheet()
        plain, ex = read(s.plain), read(s.marked)
        self.assertEqual(canon([n for n in origin.plain_view(ex)["nodes"]][0]["kind"]), canon(plain["nodes"][0]["kind"]))
        back = [{k: n[k] for k in NODE_KEYS} for n in origin.plain_view(ex)["nodes"]]
        self.assertEqual(back, [{k: n[k] for k in NODE_KEYS} for n in plain["nodes"]])
        for n, p in zip(ex["nodes"], plain["nodes"]):
            self.assertEqual(origin.PLAIN in n, any(n[k] != p[k] for k in NODE_KEYS))

    def test_ids_and_places_are_the_same_as_without_marks(self):
        s = sheet()
        plain, ex = read(s.plain), read(s.marked)
        self.assertEqual(ex["source_locations"], plain["source_locations"])
        for key in ("nodes", "relations", "unresolved_connectors"):
            self.assertEqual([(x["local_id"], x["source_object_id"], x.get("geometry")) for x in ex[key]],
                             [(x["local_id"], x["source_object_id"], x.get("geometry")) for x in plain[key]])

    def test_a_person_beats_the_mark(self):
        s = sheet()
        ex = read(s.marked)
        n = next(n for n in ex["nodes"] if origin.PLAIN in n and n["category"] == "instrument")
        op = corrections.make_op(ex, "set_tag", n["source_object_id"], {"tag": "PT-999"}, "검토자", existing_ops=[])
        got = corrections.apply(ex, [op])
        self.assertEqual(next(x for x in got["nodes"] if x["local_id"] == n["local_id"])["tag"], "PT-999")


class NothingElseChangesTest(unittest.TestCase):
    """표시가 없거나 이 앱의 것이 아닌 파일은 바이트 그대로."""

    def same(self, marked, plain):
        a, b = read(marked), read(plain)
        for x in (a, b):
            x["source"].pop("sha256")
            x.pop("extraction_run_id")
        self.assertEqual(canon(a), canon(b))

    def test_the_exporter_does_not_write_marks_yet(self):
        self.assertNotIn(origin.CLASS.encode(), sheet().plain)

    def test_a_file_without_marks_has_no_new_cells(self):
        for xml in (sheet().plain, fixture("small-pid-dexpi2.xml"), fixture("small-pid-proteus.xml")):
            self.assertNotIn(origin.PLAIN, canon(read(xml)))

    def test_marks_in_a_file_of_another_uri_are_not_read(self):
        self.same(sheet().marked.replace(origin.OWN_URI.encode(), b"urn:other:"), sheet().plain.replace(origin.OWN_URI.encode(), b"urn:other:"))

    def test_marks_that_were_moved_are_not_read(self):
        root = dexpi_read.parse_safely(sheet().marked)
        plant = next(o for o in root.iter("Object") if o.get("type") == "Plant/PlantModel")
        home = ET.SubElement(plant, "Components", property="Notes")
        for o in [o for o in root.findall("Object") if o.get("type") == origin.TYPE]:
            root.remove(o)
            home.append(o)
        ex = read(ET.tostring(root))
        self.assertFalse(any(origin.PLAIN in n for n in ex["nodes"]))

    def test_the_graph_of_the_source_drawing_does_not_know_about_marks(self):
        s = sheet()
        before = canon((s.ex, s.g))
        dexpi_marks.add(s.export.xml, dexpi_marks.marks_of(s.export, s.g))
        self.assertEqual(canon((s.ex, s.g)), before)
        self.assertEqual(canon(build.build_graph(s.ex)), canon(s.g))


class RefusedTest(unittest.TestCase):
    """어긋난 칸만 버리고 미확인으로 적는다."""

    def node(self, kind=None, instrument=False):
        for oid, n in sheet().want.items():
            if (instrument and n["category"] == "instrument" and n["tag"]) or (kind and n["kind"] == kind):
                return oid
        raise AssertionError(kind)

    def one(self, xml, oid, field, other_field_differs=()):
        """oid의 field 한 칸만 원래 값과 다르고 미확인이 한 건 있다."""
        s = sheet()
        ex = read(xml)
        self.assertEqual(sorted(s.differing(ex)), sorted([(oid, field)] + [(oid, f) for f in other_field_differs]))
        rows = s.mismatches(ex)
        self.assertEqual({u["source_object_id"] for u in rows}, {oid})
        return rows

    def test_a_kind_of_another_class_and_an_unknown_kind(self):
        oid = self.node("steam_generator")
        for bad in ("pump", "bomb", "indicator", "continuation"):
            rows = self.one(sheet().with_marks(lambda m: m[oid].update(Kind=bad)), oid, "kind")
            self.assertEqual([u["field"] for u in rows], ["kind"])

    def test_an_actuated_kind_without_an_actuator(self):
        s = sheet()
        oid = self.node("manual_valve")
        ex = read(s.with_marks(lambda m: m[oid].update(Kind="motor_operated_valve")))
        self.assertEqual((s.differing(ex), len(s.mismatches(ex))), ([], 1))

    def test_an_instrument_tag_that_does_not_fit_its_letters_and_number(self):
        oid = self.node(instrument=True)
        for bad in ("XX-999", "", sheet().want[oid]["tag"] + "9", "자유 글자"):
            self.one(sheet().with_marks(lambda m: m[oid].update(Tag=bad)), oid, "tag")

    def test_a_tag_on_something_that_is_not_an_instrument(self):
        s = sheet()
        oid = self.node("steam_generator")
        ex = read(s.with_marks(lambda m: m[oid].update(Tag="ZZ-9")))
        self.assertEqual((s.differing(ex), [u["field"] for u in s.mismatches(ex)]), ([], ["tag"]))
        self.assertIn("계기가 아닌", s.mismatches(ex)[0]["reason"])

    def test_a_text_whose_direction_is_not_that_of_the_connector(self):
        oid, n = next((o, n) for o, n in sheet().want.items() if n["kind"] == "continuation")
        word = {"TO": "FROM", "FROM": "TO"}[n["label_text"].split()[0].upper()]
        self.one(sheet().with_marks(lambda m: m[oid].update(Text=word + " X")), oid, "label_text")

    def test_a_hand_edited_standard_value_makes_only_that_mark_stale(self):
        s = sheet()
        oid = self.node("steam_generator")
        tag = s.want[oid]["tag"]
        ex = read(s.marked.replace(("<String>%s</String>" % tag).encode(), b"<String>SG-HAND</String>", 1))
        got = next(n for n in ex["nodes"] if n["source_object_id"] == oid)
        self.assertEqual(got["tag"], "SG-HAND")
        self.assertEqual({o for o, _f in s.differing(ex)}, {oid})
        self.assertEqual({u["source_object_id"] for u in s.mismatches(ex)}, {oid})

    def test_a_changed_class(self):
        s = sheet()
        oid = self.node("reactor_vessel")
        old = ('id="%s"' % oid).encode()
        head = re.search(rb'<Object [^>]*%s[^>]*>' % re.escape(old), s.marked).group(0)
        ex = read(s.marked.replace(head, head.replace(b"PressureVessel", b"Tank")))
        self.assertEqual(next(n for n in ex["nodes"] if n["source_object_id"] == oid)["kind"], "tank")
        self.assertEqual({u["source_object_id"] for u in s.mismatches(ex)}, {oid})

    def test_a_class_changed_to_a_narrower_one(self):
        s = sheet()
        oid = self.node("steam_generator")
        narrow = next(c for c in sorted(dexpi_map.classes()) if c != "HeatExchanger" and dexpi_map.derives_from(c, "HeatExchanger")
                      and not dexpi_map.classes()[c].get("abstract"))
        head = re.search(rb'<Object [^>]*id="%s"[^>]*>' % oid.encode(), s.marked).group(0)
        ex = read(s.marked.replace(head, head.replace(b"HeatExchanger", narrow.encode())))
        self.assertEqual(next(n for n in ex["nodes"] if n["source_object_id"] == oid)["kind"], "heat_exchanger")

    def test_a_flow_where_the_grounds_in_the_file_disagree(self):
        s = sheet()
        conns = dexpi_import.extract_bytes(s.marked, "x.xml")[1].connections
        idx, oid = next((i, r["source_object_id"]) for r in read(s.plain)["relations"] if r["flow_direction"]
                        for i, c in enumerate(conns) if c["id"] == r["source_object_id"])
        for arrow in ("forward", "backward"):
            with mock.patch.object(dexpi_import, "_arrow_flows", return_value=({idx: arrow}, [])):
                ex = read(s.marked)
            got = next(r for r in ex["relations"] if r["source_object_id"] == oid)["flow_direction"]
            self.assertEqual(got is None, bool(s.mismatches(ex)))
            if got is None:
                return
        self.fail("어긋난 화살표가 없음")

    def test_a_flow_where_two_arrows_disagree(self):
        s = sheet()
        conns = dexpi_import.extract_bytes(s.marked, "x.xml")[1].connections
        idx, oid = next((i, c["id"]) for i, c in enumerate(conns) if s.pipes[c["id"]]["flow_direction"]
                        and next(r for r in read(s.plain)["relations"] if r["source_object_id"] == c["id"])["flow_direction"] is None)
        with mock.patch.object(dexpi_import, "_arrow_flows", return_value=({idx: None}, [])):
            ex = read(s.marked)
        self.assertIsNone(next(r for r in ex["relations"] if r["source_object_id"] == oid)["flow_direction"])
        self.assertEqual([u["source_object_id"] for u in s.mismatches(ex)], [oid])

    def test_a_missing_or_wrong_echo(self):
        oid = self.node(instrument=True)
        for change in (lambda m: m[oid].pop("Echo"), lambda m: m[oid].update(Echo="0" * 16)):
            ex = read(sheet().with_marks(change))
            self.assertEqual({o for o, _f in sheet().differing(ex)}, {oid})

    def test_two_marks_for_one_object(self):
        s = sheet()
        oid = self.node("steam_generator")
        block = ET.tostring(next(o for o in dexpi_read.parse_safely(s.marked).findall("Object")
                                 if o.get("type") == origin.TYPE and o.find("References").get("objects") == "#" + oid))
        ex = read(s.marked.replace(b"</Model>", block + b"</Model>"))
        self.assertEqual({o for o, _f in s.differing(ex)}, {oid})
        self.assertEqual([u["source_object_id"] for u in s.mismatches(ex)], [oid])

    def test_a_cell_written_twice_is_not_read(self):
        oid = self.node("steam_generator")
        xml = sheet().with_marks(lambda m: m[oid].update(Kind="@@"))
        xml = xml.replace(b"<String>@@</String></Data>", b"<String>steam_generator</String></Data><Data property=\"Kind\"><String>condenser</String></Data>")
        ex = read(xml)
        self.assertEqual(sheet().differing(ex), [(oid, "kind")])
        self.assertEqual(next(n for n in ex["nodes"] if n["source_object_id"] == oid)["kind"], "heat_exchanger")

    def test_marks_whose_object_is_gone_are_counted(self):
        s = sheet()
        ex = read(s.with_marks(lambda m: m.update(Gone1={"Kind": "pump", "Echo": "0"}, Gone2={"Kind": "pump", "Echo": "0"})))
        rows = s.mismatches(ex)
        self.assertEqual((s.differing(ex), len(rows)), ([], 1))
        self.assertIn("2개", rows[0]["reason"])

    def test_removed_marks_leave_the_rest(self):
        s = sheet()
        oid = self.node("steam_generator")
        ex = read(s.with_marks(lambda m: m.pop(oid)))
        self.assertEqual({o for o, _f in s.differing(ex)}, {oid})
        self.assertEqual(s.mismatches(ex), [])

    def test_a_flow_against_the_off_page_connector(self):
        s = sheet()
        oid = next(r["source_object_id"] for r in read(s.plain)["relations"] if r["flow_direction"])
        rows = self.one(s.with_marks(lambda m: m[oid].update(Flow=origin.OTHER_END[m[oid]["Flow"]])), oid, "flow")
        self.assertEqual([u["field"] for u in rows], ["flow_direction"])

    def test_a_flow_that_is_not_an_end_and_a_flow_of_changed_ends(self):
        s = sheet()
        oid = next(r["source_object_id"] for r in read(s.plain)["relations"] if not r["flow_direction"] and s.pipes.get(r["source_object_id"], {}).get("flow_direction"))
        self.one(s.with_marks(lambda m: m[oid].update(Flow="up")), oid, "flow")
        pipe = re.search(rb'<Object [^>]*id="%s".*?</Object>' % oid.encode(), s.marked, re.S).group(0)
        turned = pipe.replace(b"Source", b"@@").replace(b"Target", b"Source").replace(b"@@", b"Target")
        ex = read(s.marked.replace(pipe, turned))
        self.assertIsNone(next(r for r in ex["relations"] if r["source_object_id"] == oid)["flow_direction"])
        self.assertEqual({u["source_object_id"] for u in s.mismatches(ex)}, {oid})

    def test_a_flow_in_a_two_way_segment(self):
        s = sheet()
        data = s.marked.replace(b"SingleFlowPipingNetworkSegment", b"DualFlowPipingNetworkSegment")
        self.assertNotEqual(data, s.marked)
        ex = read(data)
        self.assertEqual([r["source_object_id"] for r in ex["relations"] if r["flow_direction"] and r["flow_direction"]["basis"] != "dexpi_off_page_connector"], [])
        self.assertIn("flow_direction", {u["field"] for u in s.mismatches(ex)})

    def test_a_basis_that_is_not_a_name(self):
        s = sheet()
        oid = next(o for o, n in s.pipes.items() if n["flow_direction"])
        ex = read(s.with_marks(lambda m: m[oid].update(Basis="사람이 확인함 <b>")))
        self.assertEqual(next(r for r in ex["relations"] if r["source_object_id"] == oid)["flow_direction"]["basis"], origin.UNNAMED_BASIS)

    def test_a_forged_uri_gives_no_more_than_the_standard_values_allow(self):
        data = fixture("small-pid-dexpi2.xml")
        model = dexpi_import.extract_bytes(data, "x.xml")[1]
        forged = dexpi_marks.add(re.sub(rb'uri="[^"]*"', b'uri="' + origin.OWN_URI.encode() + b'x"', data, count=1), {
            i: {"Kind": "steam_generator", "Tag": "ZZ-9", "Echo": origin.node_echo(x)} for i, x in model.items.items()})
        ex, plain = read(forged), read(data)
        self.assertEqual([(n["kind"], n["tag"]) for n in ex["nodes"]], [(n["kind"], n["tag"]) for n in plain["nodes"]])
        self.assertTrue(sheet().mismatches(ex))


class WriteTest(unittest.TestCase):

    def test_text_that_would_not_come_back_is_not_written(self):
        s = sheet()
        g = copy.deepcopy(s.g)
        oid, n = next((o, n) for o, n in s.want.items() if n["kind"] == "pump")
        next(x for x in g["nodes"] if x["entity_id"] == n["entity_id"])["label_text"] = "A\x07B"
        marks = dexpi_marks.marks_of(s.export, g)
        self.assertNotIn("Text", marks[oid])
        self.assertIn("Kind", marks[oid])

    def test_the_same_input_gives_the_same_bytes(self):
        s = sheet()
        self.assertEqual(dexpi_marks.add(s.plain, dexpi_marks.marks_of(s.export, s.g)), s.marked)

    def test_a_marked_drawing_that_comes_back_is_exported_the_same(self):
        ex = read(sheet().marked)
        again = Sheet((ex, build.build_graph(ex)))
        self.assertEqual(again.differing(read(again.marked)), [])
        self.assertEqual({k: v.get("Kind") for k, v in again.marks.items()}, {k: v.get("Kind") for k, v in sheet().marks.items()})

    def test_every_exported_kind_is_allowed_on_its_own_class(self):
        for kind, (cls, _how) in dexpi_map.EXPORT_CLASS.items():
            item = {"group": dexpi_map.group_of(cls), "cls": cls, "attrs": {}, "id": "a"}
            got = origin.claim_node({"Kind": kind, "Echo": origin.node_echo(item)}, item, {"kind": None, "tag": None, "label_text": ""}, True)
            self.assertEqual((got.values, got.problems), ({"kind": kind}, []), kind)


class DefinitionCheckTest(unittest.TestCase):
    """앱 검사가 정의 요소의 안쪽도 XSD와 같은 규칙으로 본다."""

    XSD = paths.folder("references", "dexpi-schema", "dexpi-xml-schema-2-0-1.xsd")
    NS = "{http://www.w3.org/2001/XMLSchema}"

    def test_the_table_matches_the_xsd(self):
        types = {t.get("name"): t for t in ET.parse(self.XSD).getroot().findall(self.NS + "complexType")}
        self.assertEqual(sorted(set(types) - set(dexpi_read.STRUCTURE) - set(dexpi_read.DEFINITIONS)), ["Undefined"])
        for name, rule in dexpi_read.DEFINITIONS.items():
            t = types[name]
            self.assertEqual(sorted(e.get("name") for e in t.iter(self.NS + "element")), sorted(rule["children"]), name)
            attrs = t.findall(self.NS + "attribute")
            self.assertEqual({a.get("name"): (a.get("type"), a.get("use") == "required") for a in attrs}, rule["attributes"], name)
            heads = [e for e in t.iter(self.NS + "element") if e.get("name") != "Data"]
            group = t.find(".//" + self.NS + "choice")
            low = 0 if not heads else int((group if group is not None else heads[0]).get("minOccurs", "1"))
            high = None if group is None or group.get("maxOccurs") == "unbounded" else 1
            if name not in ("BoundClass", "BoundDataType", "Enumeration"):
                self.assertEqual((rule["low"], rule["high"]), (low, high if heads else None), name)

    def problems(self, old, new):
        text = sheet().marked
        self.assertIn(old, text)
        return dexpi_read.check_structure(dexpi_read.parse_safely(text.replace(old, new)), definitions=True)

    def test_broken_definitions_are_flagged(self):
        for old, new, word in ((b' oppositeLower="0"', b"", "oppositeLower"), (b'<DataTypeReference type="Core/DataTypes.String" />', b"", "DataProperty"),
                               (b'lower="1" upper="1" opposite', b'lower="one" upper="1" opposite', "lower"),
                               (b'<DataProperty name="Kind"', b'<DataProperty name="Ki nd"', "name"),
                               (b'<ConcreteClass name="HazopOrigin">', b'<ConcreteClass name="HazopOrigin"><Bogus />', "Bogus"),
                               (b'isUnique="true"', b'isUnique="yes"', "isUnique"), (b'<ConcreteClass name=', b'<ConcreteClass title=', "title")):
            got = self.problems(old, new)
            self.assertTrue(any(word in x for x in got), (word, got[:3]))

    def test_data_comes_after_the_properties(self):
        got = self.problems(b'<ConcreteClass name="HazopOrigin">', b'<ConcreteClass name="HazopOrigin"><Data property="N"><String>x</String></Data>')
        self.assertTrue(any("Data" in x for x in got), got)

    def test_registering_a_file_of_another_program_is_not_stricter_than_before(self):
        text = sheet().marked.replace(b' oppositeLower="0"', b"")
        self.assertEqual(dexpi_read.check_structure(dexpi_read.parse_safely(text)), [])

    def test_the_schema_still_describes_undefined_only_by_name(self):
        good = dexpi_read.parse_safely(dexpi_pair and fixture("small-pid-dexpi2.xml"))
        self.assertEqual(dexpi_read.check_structure(good, definitions=True), [])


if __name__ == "__main__":
    unittest.main()
