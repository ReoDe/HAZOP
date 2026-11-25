"""DEXPI 내보내기가 원래 값 표시(HZ-PLN-22 §6.9)를 싣는 시험. 실행: python -m unittest tests.test_dexpi_marks_export"""

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.export import dexpi_export as de, dexpi_screen as ds  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from hazop.extract.adapters import dexpi_import, dexpi_origin as origin, dexpi_read  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.kg import auto, claims  # noqa: E402
from tests.test_dexpi_export import SNP, dexpi_pair, snp_pair  # noqa: E402
from tests.test_dexpi_origin import Sheet, export, read  # noqa: E402

# 표시를 넣기 전(a6dfee3f)의 내보낸 바이트
BEFORE = {"SNP-M-101": "0236f4e5f05cef42b9872e94027ba637cd9d705b1f7d6ccd87a818d5fe672a31",
          "SNP-M-102": "c582b878a9035b56d151f9a5fcbb37351de21e7771f18b082eab922ff68041e8",
          "SNP-M-201": "492a97e5a34036e09ec9b1ae662f3b0d1a07dce13863b15db74ae1d32d915f1e",
          "SNP-M-301": "ecbc924e5c9c54a4e6aa6662fe308145c49b397cf2e4d1ad75ba0d39cd948f9b",
          "SNP-M-401": "aa3db5eb96186e0ac2db9e1d319377fec77fedf02948644a2d102bb19c59179f",
          "SNP-M-501": "9a44e92b17c17eac7876070d06f2a06ae449652746cd536f1d7d0d86288ab474",
          "small-pid-dexpi2.xml": "7e990528e975fa7b2fcca11baf30f89ee9b33137831faec4e5089c37da795a42",
          "small-pid-proteus.xml": "3ed22214340a37ad4d460eb50767c50c8d3954ec26be9a8a94c9777f0ab2a37d"}


def off():
    return mock.patch.object(de, "WRITE_MARKS", False)


def pairs():
    for path in SNP:
        yield os.path.basename(path)[:9], snp_pair(path)
    for name in ("small-pid-dexpi2.xml", "small-pid-proteus.xml"):
        yield name, dexpi_pair(name)


def marks_in(xml):
    return dexpi_read.read(xml).origins


def named(pair, tag):
    return next(n for n in pair[1]["nodes"] if n["tag"] == tag and n["node_type"] == "drawing_object")


def edited(pair, *rows):
    """사람 고침(auto면 자동 확정이 수락한 고침)을 얹은 (추출, 그래프). rows: (연산, 대상, 값, auto)."""
    ops = []
    for op, target, value, auto in rows:
        o = corrections.make_op(pair[0], op, target, value, "검토자", existing_ops=ops)
        ops.append(dict(o, accepted_by=corrections.AUTO_BY) if auto else o)
    ex = corrections.apply(pair[0], ops)
    assert len(ex["corrections"]["applied"]) == len(ops), ex["corrections"]
    return ex, build.build_graph(ex)


class SwitchTest(unittest.TestCase):

    def test_switched_off_the_files_are_byte_for_byte_those_of_before(self):
        with off():
            self.assertEqual({name: hashlib.sha256(export(pair).xml).hexdigest() for name, pair in pairs()}, BEFORE)

    def test_the_definition_check_changes_nothing_in_a_file_without_marks(self):
        with off():
            for name, pair in pairs():
                root = dexpi_read.parse_safely(export(pair).xml)
                self.assertEqual((dexpi_read.check_structure(root, definitions=True), dexpi_read.check_structure(root)), ([], []), name)

    def test_switched_on_the_standard_part_is_the_same(self):
        """표시와 그 정의를 빼면 표시 없이 낸 것과 같은 내용이다."""
        for name, pair in pairs():
            with off():
                plain = export(pair).xml
            root = dexpi_read.parse_safely(export(pair).xml)
            for el in list(root):
                if el.tag == "ConcreteClass" or el.get("type") == origin.TYPE:
                    root.remove(el)

            def flat(el):
                return el.tag, dict(el.attrib), (el.text or "").strip(), [flat(c) for c in el]
            self.assertEqual(flat(root), flat(dexpi_read.parse_safely(plain)), name)

    def test_the_other_files_say_the_same(self):
        for name, pair in pairs():
            with off():
                a = export(pair)
            b = export(pair)
            self.assertEqual(a.excluded, b.excluded, name)
            self.assertEqual(dict(a.sidecar, dexpi_sha256=0), dict(b.sidecar, dexpi_sha256=0), name)
            self.assertEqual(b.sidecar["dexpi_sha256"], hashlib.sha256(b.xml).hexdigest())
            self.assertEqual(dict(a.stats, bytes=0, dexpi_sha256=0), dict(b.stats, bytes=0, dexpi_sha256=0), name)


class WrittenTest(unittest.TestCase):

    def test_what_goes_out_is_read_back_as_it_was(self):
        for name, pair in pairs():
            x, s = export(pair), Sheet(pair)
            ex = read(x.xml)
            self.assertEqual([r for r in s.differing(ex) if r[1] != "flow"], [], name)
            self.assertEqual(s.mismatches(ex), [], name)
            root = dexpi_read.parse_safely(x.xml)
            self.assertEqual((dexpi_read.check_structure(root, definitions=True), dexpi_read.check_references(root)), ([], []), name)

    def test_the_samples_lose_nothing(self):
        for path in SNP:
            pair = snp_pair(path)
            self.assertEqual(Sheet(pair).differing(read(export(pair).xml)), [])

    def test_the_same_input_gives_the_same_bytes(self):
        pair = snp_pair(SNP[0])
        before = json.dumps(pair, sort_keys=True)
        self.assertEqual(export(pair).files, export(copy.deepcopy(pair)).files)
        self.assertEqual(json.dumps(pair, sort_keys=True), before)

    def test_every_component_and_pipe_has_one_mark_and_signal_lines_have_none(self):
        pair = snp_pair(SNP[0])
        x = export(pair)
        self.assertEqual(sorted(marks_in(x.xml)), sorted([e["dexpi_id"] for e in x.sidecar["entities"]] + [p["dexpi_id"] for p in x.sidecar["pipes"]]))

    def test_a_part_without_a_kind_and_one_that_needs_no_mark(self):
        pair = dexpi_pair("small-pid-dexpi2.xml")
        x = export(pair)
        marks = marks_in(x.xml)
        raw = next(e for e in x.sidecar["entities"] if e["kind"] is None)
        self.assertNotIn("Kind", marks[raw["dexpi_id"]])
        with off():
            plain = read(export(pair).xml)
        same = next(n for n in plain["nodes"] if n["kind"] == "tank")
        got = next(n for n in read(x.xml)["nodes"] if n["source_object_id"] == same["source_object_id"])
        self.assertEqual({k: v for k, v in got.items() if k != origin.PLAIN}, same)

    def test_a_tag_that_does_not_fit_the_parts_in_the_file_is_not_dropped_in_silence(self):
        """DEXPI에서 온 뒤 사람이나 자동 확정이 태그를 바꾼 계기: 파일의 세 조각은 옛 값이다. 값은 옛 글자로 읽히지만 미확인이 남는다."""
        for auto in (False, True):
            pair = edited(dexpi_pair("small-pid-dexpi2.xml"), ("set_tag", "PIF1", {"tag": "XX-999"}, auto))
            x = export(pair)
            self.assertEqual(marks_in(x.xml)["PIF1"]["Tag"], "XX-999")
            back = read(x.xml)
            self.assertEqual(self.refused(back), [("PIF1", "tag")])
            n = next(n for n in back["nodes"] if n["source_object_id"] == "PIF1")
            self.assertEqual((n["tag"], n["evidence"]["tag_basis"]), ("P101", "계측 기능 구분 문자와 번호"))     # 옛 글자는 자동으로 정한 값이 아니다
            self.assertNotIn("dexpi_origin", n["evidence"])
            self.assertEqual([a for a in x.excluded["approximations"] if a["reason"] == "origin_mark_not_accepted"],
                             [{"entity_id": next(e["entity_id"] for e in x.sidecar["entities"] if e["dexpi_id"] == "PIF1"), "reason": "origin_mark_not_accepted", "field": "tag"}])
            side = dexpi_import.extract_bytes(x.xml, "x.xml", sidecar=x.sidecar)[0]
            self.assertEqual((next(n for n in side["nodes"] if n["source_object_id"] == "PIF1")["tag"], self.refused(side)), ("XX-999", []))

    @staticmethod
    def refused(ex):
        return [(u["source_object_id"], u["field"]) for u in ex["validation"]["unknowns"] if u["check"] == origin.CHECK]

    def test_a_flow_a_person_turned_against_the_connector_is_not_turned_back_in_silence(self):
        for path in SNP:
            pair = snp_pair(path)
            by = {n["local_id"]: n for n in pair[0]["nodes"]}
            rel = next(r for r in pair[0]["relations"] if r["flow_direction"] and "continuation" in [by[e["node_local_id"]]["kind"] for e in r["endpoints"]])
            fd = rel["flow_direction"]
            pair = edited(pair, ("set_flow", rel["source_object_id"], {"from": by[fd["to"]]["source_object_id"], "to": by[fd["from"]]["source_object_id"]}, False))
            x = export(pair)
            pipe = next(p["dexpi_id"] for p in x.sidecar["pipes"] if p["local_id"] == rel["local_id"])
            self.assertEqual(marks_in(x.xml)[pipe]["Basis"], "human_elsewhere")
            self.assertEqual(self.refused(read(x.xml)), [(pipe, "flow_direction")])
            self.assertIn("origin_mark_not_accepted", {a["reason"] for a in x.excluded["approximations"]})
            side = dexpi_import.extract_bytes(x.xml, "x.xml", sidecar=x.sidecar)[0]
            so = {n["local_id"]: n["source_object_id"] for n in side["nodes"]}
            dx = {e["local_id"]: e["dexpi_id"] for e in x.sidecar["entities"]}
            f = next(r for r in side["relations"] if r["source_object_id"] == pipe)["flow_direction"]
            self.assertEqual((so[f["from"]], so[f["to"]], f["basis"], self.refused(side)), (dx[fd["to"]], dx[fd["from"]], "human_elsewhere", []))

    def test_a_sidecar_does_not_turn_a_flow_in_a_file_without_marks(self):
        pair = snp_pair(SNP[0])
        with off():
            x = export(pair)
        side = copy.deepcopy(x.sidecar)
        p = next(p for p in side["pipes"] if p["flow_direction"] and next(r for r in read(x.xml)["relations"] if r["source_object_id"] == p["dexpi_id"])["flow_direction"])
        fd = p["flow_direction"]
        p["flow_direction"] = dict(fd, **{"from": fd["to"], "to": fd["from"]})
        a, b = (dexpi_import.extract_bytes(x.xml, "x.xml", sidecar=s)[0] for s in (x.sidecar, side))
        self.assertEqual(a["relations"], b["relations"])


class PersonAndAutoTest(unittest.TestCase):
    """사람이 고친 값은 고친 값으로, 자동 확정이 정한 값은 자동이라는 표시와 함께 실린다."""

    def setUp(self):
        self.pair = snp_pair(next(p for p in SNP if "M-101" in p))
        self.sg, self.inst = named(self.pair, "RC-SG01"), named(self.pair, "RC-LT101")

    def back(self, pair):
        x = export(pair)
        oid = {e["entity_id"]: e["dexpi_id"] for e in x.sidecar["entities"]}
        nodes = {n["source_object_id"]: n for n in read(x.xml)["nodes"]}
        return x, lambda n: (marks_in(x.xml)[oid[n["entity_id"]]], nodes[oid[n["entity_id"]]])

    def test_a_person(self):
        pair = edited(self.pair, ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, False),
                      ("set_tag", self.inst["source_object_id"], {"tag": "RC-LT777"}, False))
        _x, of = self.back(pair)
        (m, n), (mi, ni) = of(self.sg), of(self.inst)
        self.assertEqual((m["Kind"], n["kind"], mi["Tag"], ni["tag"]), ("condenser", "condenser", "RC-LT777", "RC-LT777"))
        for mark, node, name in ((m, n, "kind"), (mi, ni, "tag")):
            self.assertEqual((mark.get("Auto"), mark["Edited"], node["evidence"]["dexpi_origin"]), (None, name, {"edited": [name]}))
            self.assertNotIn("human_edit", node)        # 되읽은 값은 이 프로젝트의 사람이 고친 것이 아니다

    def test_automatic_confirmation(self):
        pair = edited(self.pair, ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, True),
                      ("set_tag", self.inst["source_object_id"], {"tag": "RC-LT777"}, True))
        x, of = self.back(pair)
        (m, n), (mi, ni) = of(self.sg), of(self.inst)
        self.assertEqual((m["Kind"], m["Auto"], n["kind"], n["evidence"]["dexpi_origin"]), ("condenser", "kind", "condenser", {"auto": ["kind"]}))
        self.assertNotIn("TagBasis", m)
        self.assertEqual((mi["Auto"], ni["tag"]), ("tag", "RC-LT777"))
        g = build.build_graph(read(x.xml))
        got = next(a for a in g["nodes"] if a["tag"] == "RC-LT777")
        self.assertEqual((got["auto"], got["origin"]), (["tag"], "ai_auto"))
        (c,) = [c for c in claims.drawing_claims(g) if c["value"] == "RC-LT777"]
        self.assertEqual((c["knowledge_status"], c["origin"]), ("hypothesis", "ai_auto"))

    def test_an_automatic_value_a_person_then_set_is_a_persons(self):
        pair = edited(self.pair, ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, True),
                      ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, False))
        mark = self.back(pair)[1](self.sg)[0]
        self.assertEqual((mark.get("Auto"), mark["Edited"]), (None, "kind"))

    def test_an_automatic_flow_does_not_say_human(self):
        rel = next(r for r in self.pair[0]["relations"] if r["flow_direction"] and r["flow_direction"]["basis"] == "source_to_target"
                   and not any(n["kind"] == "continuation" for n in self.pair[0]["nodes"] if n["local_id"] in (r["flow_direction"]["from"], r["flow_direction"]["to"])))
        a, b = (e["source_object_id"] for e in rel["endpoints"])
        for auto, basis in ((True, "ai_auto"), (False, "human_elsewhere")):
            pair = edited(self.pair, ("set_flow", rel["source_object_id"], {"from": a, "to": b}, auto))
            x = export(pair)
            oid = next(p["dexpi_id"] for p in x.sidecar["pipes"] if p["local_id"] == rel["local_id"])
            self.assertEqual((marks_in(x.xml)[oid]["Basis"], marks_in(x.xml)[oid].get("Auto")), (basis, "flow" if auto else None))
            self.assertEqual(next(r for r in read(x.xml)["relations"] if r["source_object_id"] == oid)["flow_direction"]["basis"], basis)

    def test_names_that_are_not_ours_in_the_cell(self):
        self.assertEqual(origin.grades_of({"Auto": "kind human tag kind x", "Edited": "tag flow y"}), {"auto": ["kind", "tag"], "edited": ["flow"]})
        self.assertEqual(origin.grades_of({}), {})

    def test_a_stale_mark_still_lowers_the_standing(self):
        pair = edited(self.pair, ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, True))
        xml = export(pair).xml.replace(b"<String>RC-SG01</String>", b"<String>RC-SG99</String>", 1)
        n = next(n for n in read(xml)["nodes"] if n["tag"] == "RC-SG99")
        self.assertEqual((n["kind"], n["evidence"].get("dexpi_origin")), ("heat_exchanger", None))      # 버린 종류의 등급은 지금 종류의 것이 아니다
        pair = edited(self.pair, ("set_tag", self.sg["source_object_id"], {"tag": "RC-SG98"}, True))
        xml = export(pair).xml.replace(b"<String>RC-SG98</String>", b"<String>RC-SG99</String>", 1)
        n = next(n for n in read(xml)["nodes"] if n["tag"] == "RC-SG99")
        self.assertEqual(n["evidence"]["dexpi_origin"], {"auto": ["tag"]})


class ProvenanceTest(unittest.TestCase):
    """추정한 태그와 자동으로 정한 값은 세 번 왕복해도 확정이 되지 않는다."""

    def setUp(self):
        self.pair = snp_pair(next(p for p in SNP if "M-101" in p))
        self.sg, self.inst = named(self.pair, "RC-SG01"), named(self.pair, "RC-LT101")

    def trips(self, pair, sidecar=False):
        for _ in range(3):
            x = export(pair)
            ex = dexpi_import.extract_bytes(x.xml, "x.xml", sidecar=x.sidecar if sidecar else None)[0]
            ex["drawing"]["drawing_number"] = "SNP-M-101"
            pair = ex, build.build_graph(ex)
            yield x, pair

    def status(self, g, tag):
        return {c["knowledge_status"] for c in claims.drawing_claims(g) if c["property"] in ("tag", "line_no") and c["value"] == tag}

    def inferred(self, basis="isa_label+page_prefix:RC [추론]"):
        ex = copy.deepcopy(self.pair[0])
        for n in ex["nodes"]:
            if n["tag"] in ("RC-LT101", "RC-SG01"):
                n["evidence"] = dict(n.get("evidence") or {}, tag_basis=basis)
        return ex, build.build_graph(ex)

    def test_an_inferred_tag_stays_a_hypothesis(self):
        for sidecar in (False, True):
            for x, (_ex, g) in self.trips(self.inferred(), sidecar):
                for tag in ("RC-LT101", "RC-SG01"):
                    n = next(n for n in g["nodes"] if n["tag"] == tag)
                    self.assertEqual((n["tag_basis"], self.status(g, tag)), ("isa_label+page_prefix:RC [추론]", {"hypothesis"}))
                doc = {"nodes": [{"id": "d", "node_type": next(iter(auto.APPLY_KIND))}], "tag_mentions": [{"node_id": "d", "tags": ["RC-LT101"]}]}
                (row,), _notes = auto.tag_links([doc], [g])
                self.assertIn("[추론]", row["reason"])

    def test_the_sidecar_alone_keeps_it_when_the_marks_are_off(self):
        with off():
            for _x, (_ex, g) in self.trips(self.inferred(), True):
                self.assertEqual(self.status(g, "RC-LT101") | self.status(g, "RC-SG01"), {"hypothesis"})

    def test_an_old_sidecar_is_read_as_before(self):
        x = export(self.inferred())
        side = copy.deepcopy(x.sidecar)
        for e in side["entities"]:
            e.pop("grade", None)
        with off():
            plain = export(self.inferred())
        old = dict(side, dexpi_sha256=plain.sidecar["dexpi_sha256"])
        n = next(n for n in dexpi_import.extract_bytes(plain.xml, "x.xml", sidecar=old)[0]["nodes"] if n["tag"] == "RC-SG01")
        self.assertNotIn("tag_basis", n["evidence"])

    def test_a_confirmed_tag_is_not_made_a_hypothesis(self):
        for _x, (_ex, g) in self.trips(self.pair):
            self.assertEqual(self.status(g, "RC-LT101"), {"confirmed"})
        for basis, want in (("isa_label", "confirmed"), ("human", "hypothesis")):
            for _x, (_ex, g) in self.trips(self.inferred(basis)):
                self.assertEqual(self.status(g, "RC-LT101"), {want})

    def test_a_person_settles_an_inferred_tag_that_came_back(self):
        _x, pair = next(self.trips(self.inferred()))
        oid = next(n["source_object_id"] for n in pair[0]["nodes"] if n["tag"] == "RC-LT101")
        pair = edited(pair, ("set_tag", oid, {"tag": "RC-LT101"}, False))
        self.assertEqual(self.status(pair[1], "RC-LT101"), {"confirmed"})
        for sidecar in (False, True):
            for _x, (_ex, g) in self.trips(pair, sidecar):      # 다른 프로젝트의 사람이 정한 값은 여기서 확정이 아니다
                n = next(n for n in g["nodes"] if n["tag"] == "RC-LT101")
                self.assertEqual((self.status(g, "RC-LT101"), n["edited_elsewhere"], "human_edit" in n), ({"hypothesis"}, ["tag"], False))
                doc = {"nodes": [{"id": "d", "node_type": next(iter(auto.APPLY_KIND))}], "tag_mentions": [{"node_id": "d", "tags": ["RC-LT101"]}]}
                self.assertIn("들여온 파일에서", auto.tag_links([doc], [g])[0][0]["reason"])

    def test_a_position_keeps_its_standing(self):
        valve = next(n for n in self.pair[1]["nodes"] if n["kind"] == "motor_operated_valve")
        for by_auto, origin_, key in ((True, "ai_auto", "auto"), (False, "pid_extract", "edited_elsewhere")):
            pair = edited(self.pair, ("set_fail_position", valve["source_object_id"], {"value": "FO"}, by_auto),
                          ("set_normal_position", valve["source_object_id"], {"value": "NC"}, by_auto))
            for sidecar in (False, True):
                for _x, (_ex, g) in self.trips(pair, sidecar):
                    n = next(n for n in g["nodes"] if n["tag"] == valve["tag"])
                    self.assertEqual(n[key], ["normal_position", "fail_position"])
                    got = {c["property"]: (c["knowledge_status"], c["origin"]) for c in claims.drawing_claims(g) if c["value"] in ("FO", "NC") and c["source"]["source_object_id"] == n["source_object_id"]}
                    self.assertEqual(got, dict({"fail_position": ("hypothesis", origin_)}, **({"normal_position": ("hypothesis", origin_)} if sidecar else {})))

    def automatic(self):
        rel = next(r for r in self.pair[0]["relations"] if r["line_no"] and r["flow_direction"] and r["flow_direction"]["basis"] == "source_to_target"
                   and not any(n["kind"] == "continuation" for n in self.pair[0]["nodes"] if n["local_id"] in (r["flow_direction"]["from"], r["flow_direction"]["to"])))
        a, b = (e["source_object_id"] for e in rel["endpoints"])
        return edited(self.pair, ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, True),
                      ("set_tag", self.inst["source_object_id"], {"tag": "RC-LT777"}, True), ("set_tag", self.sg["source_object_id"], {"tag": "RC-ZZ99"}, True),
                      ("set_flow", rel["source_object_id"], {"from": a, "to": b}, True), ("set_tag", rel["source_object_id"], {"tag": "LINE-9"}, True))

    def test_automatic_values_stay_automatic(self):
        for sidecar in (False, True):
            for x, (ex, g) in self.trips(self.automatic(), sidecar):
                for tag in ("RC-LT777", "RC-ZZ99", "LINE-9"):
                    self.assertEqual(self.status(g, tag), {"hypothesis"}, (tag, sidecar))
                marks = marks_in(x.xml)
                oid = {n["tag"]: n["source_object_id"] for n in ex["nodes"]}
                self.assertFalse(any(m.get("Edited") for m in marks.values()))
                self.assertEqual((marks[oid["RC-ZZ99"]]["Auto"], marks[oid["RC-LT777"]]["Auto"]), ("kind tag", "tag"))
                pipe = next(m for m in marks.values() if m.get("Basis") == "ai_auto")
                self.assertEqual(pipe["Auto"], "tag flow")

    def test_an_automatic_connection_and_an_added_part_stay_automatic(self):
        rel = next(r for r in self.pair[0]["relations"] if r["kind"] == "physical_connection" and r["flow_direction"])
        end = next(e for e in rel["endpoints"] if e["end"] == "target")
        for by_auto in (True, False):
            pair = edited(self.pair, ("set_endpoint", rel["source_object_id"], {"end": "target", "node": end["source_object_id"]}, by_auto),
                          ("add_node", None, {"kind": "pump", "category": "equipment", "tag": "RC-P99", "bbox": [5, 5, 30, 30]}, by_auto))
            for _x, (_ex, g) in self.trips(pair):
                pump = next(n for n in g["nodes"] if n["tag"] == "RC-P99")
                pipes = [n for n in g["nodes"] if n["node_type"] == "pipe_segment" and "endpoint" in (n.get("auto") or n.get("edited_elsewhere") or ())]
                key, origin_ = ("auto", "ai_auto") if by_auto else ("edited_elsewhere", "pid_extract")
                self.assertEqual((pump[key], pump["origin"], len(pipes), pipes[0]["origin"]), (["add_node"], origin_, 1, origin_))
                self.assertEqual({e["origin"] for e in g["edges"] if e.get("segment") == pipes[0]["entity_id"]}, {origin_})

    def test_what_a_person_sets_afterwards_is_not_automatic(self):
        _x, (ex, g) = next(self.trips(self.automatic()))
        oid = next(n["source_object_id"] for n in ex["nodes"] if n["tag"] == "RC-ZZ99")
        rel = next(r for r in ex["relations"] if r["line_no"] == "LINE-9")
        ends = {n["local_id"]: n["source_object_id"] for n in ex["nodes"]}
        fd = rel["flow_direction"]
        pair = edited((ex, g), ("set_kind", oid, {"kind": "condenser", "category": "equipment"}, False), ("set_tag", oid, {"tag": "RC-ZZ99"}, False),
                      ("set_tag", rel["source_object_id"], {"tag": "LINE-9"}, False),
                      ("set_flow", rel["source_object_id"], {"from": ends[fd["from"]], "to": ends[fd["to"]]}, False))
        for x, (ex2, g2) in self.trips(pair):
            marks = marks_in(x.xml)
            self.assertEqual((marks[oid].get("Auto"), marks[oid]["Edited"]), (None, "kind tag"))
            m = marks[rel["source_object_id"]]
            self.assertEqual((m.get("Auto"), m["Edited"], m["Basis"]), (None, "tag flow", "human_elsewhere"))
            self.assertEqual((self.status(g2, "RC-ZZ99"), self.status(g2, "LINE-9")), ({"hypothesis"}, {"hypothesis"}))
        self.assertEqual((self.status(pair[1], "RC-ZZ99"), self.status(pair[1], "LINE-9")), ({"confirmed"}, {"confirmed"}))

    def test_a_basis_cell_can_only_lower_the_standing(self):
        self.assertEqual([origin.tag_basis_of({"TagBasis": x}) for x in ("human", "x [추론]", "ai_auto [추론]", "", "y" * 300 + "[추론]")],
                         [None, "x [추론]", "ai_auto", None, "[추론]"])
        self.assertIsNone(origin.tag_basis_of({}))


class ThreeWaysTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-dexpi-marks-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work")})
        env.start()
        self.addCleanup(env.stop)
        self.pairs = {}
        for key in ("SNP-M-101", "SNP-M-102"):
            self.pairs[key] = ex, g = snp_pair(next(p for p in SNP if key in p))
            for root, doc, fname in (("graph", g, "graph.json"), ("extract", ex, "extraction.json")):
                os.makedirs(os.path.join(self.tmp, root, key))
                with open(os.path.join(self.tmp, root, key, fname), "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, ensure_ascii=False)

    def names(self, out, **kw):
        return de.export_names(None, os.path.join(self.tmp, out), graph_root=os.path.join(self.tmp, "graph"), extract_root=os.path.join(self.tmp, "extract"),
                               confirmation="assume", require_confirmed_number=False, now="2026-11-26T00:00:00+00:00", **kw)

    def xml(self, out, key):
        with open(os.path.join(self.tmp, out, key + ".dexpi.xml"), "rb") as fh:
            return fh.read()

    def test_the_folder_export_writes_the_same_marks_and_the_manifest_stays(self):
        on = self.names("on")
        with off():
            away = self.names("off")
        for key, (ex, g) in self.pairs.items():
            self.assertEqual(self.xml("on", key), de.export_drawing(g, ex, require_confirmed_number=False).xml)
            self.assertFalse(marks_in(self.xml("off", key)))
        a, b = ({k: v for k, v in r.items() if k not in ("manifest",)} for r in (on, away))
        for r in (a, b):
            for d in r["drawings"]:
                d["stats"] = dict(d["stats"], bytes=0, dexpi_sha256=0)
                d.pop("sha256", None)
        strip = lambda r: json.loads(json.dumps(r, default=str).replace(os.path.join(self.tmp, "on").replace("\\", "\\\\"), "").replace(os.path.join(self.tmp, "off").replace("\\", "\\\\"), ""))  # noqa: E731
        self.assertEqual(strip(a), strip(b))

    def test_one_page_that_fails_does_not_stop_the_rest(self):
        real = de.dexpi_marks.write

        def broken(xml, *a):
            if b"SNP-M-101" in xml[:400] or b"SNP_M_101" in xml[:400]:
                raise ValueError("표시 쓰기 실패")
            return real(xml, *a)
        with mock.patch.object(de.dexpi_marks, "write", broken):
            res = self.names("part")
        self.assertEqual(([d["name"] for d in res["drawings"]], [n["name"] for n in res["not_exported"]]), (["SNP-M-102"], ["SNP-M-101"]))

    def test_the_screen_is_built_with_the_same_marks(self):
        ex, _g = self.pairs["SNP-M-101"]
        screen = ds.build(ex, "S")
        self.assertEqual(sorted(marks_in(screen.xml)), sorted(marks_in(de.export_drawing(build.build_graph(ex), ex, require_confirmed_number=False).xml)))
        self.assertTrue(ds.prepare("S", ex).ok)
        for rec in screen.sidecar["solid_extra"]["nodes"].values():
            self.assertFalse({"kind", "tag", "label_text", "category"} & set(rec))       # 이제 파일에서 온다

    def test_a_cache_of_the_writer_before_is_stale_and_is_built_again(self):
        ex, _g = self.pairs["SNP-M-101"]
        with off(), mock.patch.object(ds, "WRITER", "1"):
            self.assertTrue(ds.prepare("S", ex).ok)
        self.assertEqual(ds.WRITER, "2")
        with mock.patch.object(ds, "WRITER", "1"):      # 판이 같아도 표시를 켜고 끈 것은 다른 그림이다
            self.assertEqual(ds.open_view("S", ex).code, "stale")
            with off():
                self.assertTrue(ds.open_view("S", ex).ok)
        self.assertEqual(ds.open_view("S", ex).code, "stale")
        self.assertTrue(ds.prepare("S", ex).ok)
        self.assertTrue(marks_in(ds._load("S").xml))


class CheckedBeforeWritingTest(unittest.TestCase):

    def test_a_mark_that_would_not_be_read_stops_the_page(self):
        real = de.dexpi_marks.write

        def twice(xml, *a):
            out, _again = real(xml, *a)
            block = out[out.index(b'<Object type="/HazopOrigin">'):]
            block = block[:block.index(b"</Object>") + 9]
            out = out.replace(b"</Model>", block + b"</Model>")
            return out, read(out)
        with mock.patch.object(de.dexpi_marks, "write", twice), self.assertRaises(de.ExportError) as cm:
            export(snp_pair(SNP[0]))
        self.assertIn("표시", " ".join(cm.exception.reasons))

    def stopped(self, change):
        real = de.dexpi_marks.write

        def changed(xml, *a):
            out, again = real(xml, *a)
            return change(out, again)
        with mock.patch.object(de.dexpi_marks, "write", changed), self.assertRaises(de.ExportError) as cm:
            export(snp_pair(SNP[0]))
        return " ".join(cm.exception.reasons)

    def test_marks_that_change_the_ids_or_places_stop_the_page(self):
        def node(out, again):
            again["nodes"][0]["geometry"] = None
            return out, again

        def relation(out, again):
            again["relations"][0]["source_object_id"] = "Other"
            return out, again

        def way(out, again):
            again["relations"][0]["geometry"] = {"x": 1}
            return out, again
        for change in (node, relation, way):
            self.assertIn("자리가 다름", self.stopped(change))

    def test_marks_that_break_the_schema_stop_the_page(self):
        self.assertIn("oppositeLower", self.stopped(lambda out, again: (out.replace(b' oppositeLower="0"', b""), again)))
        self.assertIn("없는 객체", self.stopped(lambda out, again: (out.replace(b'objects="#HZ_', b'objects="#ZZ_', 1), again)))

    def test_a_sidecar_that_gives_another_tag_stops_the_page(self):
        real = dexpi_import.apply_sidecar

        def other(ex, sidecar, sha):
            got = real(ex, sidecar, sha)
            ex["nodes"][0]["tag"] = "ZZ-1"
            return got
        with mock.patch.object(dexpi_import, "apply_sidecar", other), self.assertRaises(de.ExportError) as cm:
            export(snp_pair(SNP[0]))
        self.assertIn("곁 파일", " ".join(cm.exception.reasons))


if __name__ == "__main__":
    unittest.main()
