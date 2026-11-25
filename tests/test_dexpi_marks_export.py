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

    def test_a_tag_that_does_not_fit_the_parts_in_the_file_is_not_written(self):
        """DEXPI에서 온 뒤 사람이 태그를 바꾼 계기: 파일의 세 조각은 옛 값이다. 되읽을 때 버려질 칸은 싣지 않는다."""
        pair = dexpi_pair("small-pid-dexpi2.xml")
        pair = edited(pair, ("set_tag", "PIF1", {"tag": "XX-999"}, False))
        x = export(pair)
        self.assertNotIn("Tag", marks_in(x.xml)["PIF1"])
        self.assertIn("Kind", marks_in(x.xml)["PIF1"])
        back = read(x.xml)
        self.assertEqual([u for u in back["validation"]["unknowns"] if u["check"] == origin.CHECK], [])
        self.assertEqual(next(n for n in dexpi_import.extract_bytes(x.xml, "x.xml", sidecar=x.sidecar)[0]["nodes"] if n["source_object_id"] == "PIF1")["tag"], "XX-999")


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
        for mark, node in ((m, n), (mi, ni)):
            self.assertNotIn("Auto", mark)
            self.assertNotIn("dexpi_origin", node["evidence"])
            self.assertNotIn("human_edit", node)        # 되읽은 값은 사람이 고친 것이 아니라 파일에서 읽은 값이다

    def test_automatic_confirmation(self):
        pair = edited(self.pair, ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, True),
                      ("set_tag", self.inst["source_object_id"], {"tag": "RC-LT777"}, True))
        x, of = self.back(pair)
        (m, n), (mi, ni) = of(self.sg), of(self.inst)
        self.assertEqual((m["Kind"], m["Auto"], n["kind"], n["evidence"]["dexpi_origin"]), ("condenser", "kind", "condenser", {"auto": ["kind"]}))
        self.assertEqual((mi["Auto"], ni["tag"], ni["evidence"]["tag_basis"]), ("tag", "RC-LT777", "ai_auto"))
        g = build.build_graph(read(x.xml))
        got = next(a for a in g["nodes"] if a["tag"] == "RC-LT777")
        self.assertEqual((got["tag_basis"], got["origin"]), ("ai_auto [추론]", "pid_extract"))        # ③ 자동 연결이 추정 태그로 다룬다

    def test_an_automatic_value_a_person_then_set_is_a_persons(self):
        pair = edited(self.pair, ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, True),
                      ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, False))
        self.assertNotIn("Auto", self.back(pair)[1](self.sg)[0])

    def test_an_automatic_flow_does_not_say_human(self):
        rel = next(r for r in self.pair[0]["relations"] if r["flow_direction"] and r["flow_direction"]["basis"] == "source_to_target"
                   and not any(n["kind"] == "continuation" for n in self.pair[0]["nodes"] if n["local_id"] in (r["flow_direction"]["from"], r["flow_direction"]["to"])))
        a, b = (e["source_object_id"] for e in rel["endpoints"])
        for auto, basis in ((True, "ai_auto"), (False, "human")):
            pair = edited(self.pair, ("set_flow", rel["source_object_id"], {"from": a, "to": b}, auto))
            x = export(pair)
            oid = next(p["dexpi_id"] for p in x.sidecar["pipes"] if p["local_id"] == rel["local_id"])
            self.assertEqual((marks_in(x.xml)[oid]["Basis"], marks_in(x.xml)[oid].get("Auto")), (basis, "flow" if auto else None))
            self.assertEqual(next(r for r in read(x.xml)["relations"] if r["source_object_id"] == oid)["flow_direction"]["basis"], basis)

    def test_names_that_are_not_ours_in_the_cell(self):
        self.assertEqual(origin.auto_of({"Auto": "kind human tag kind x"}), ["kind", "tag"])
        self.assertEqual(origin.auto_of({}), [])

    def test_a_stale_mark_says_nothing_about_auto(self):
        pair = edited(self.pair, ("set_kind", self.sg["source_object_id"], {"kind": "condenser", "category": "equipment"}, True))
        xml = export(pair).xml.replace(b"<String>RC-SG01</String>", b"<String>RC-SG99</String>", 1)
        n = next(n for n in read(xml)["nodes"] if n["tag"] == "RC-SG99")
        self.assertNotIn("dexpi_origin", n["evidence"])


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

    def test_marks_that_change_the_ids_or_places_stop_the_page(self):
        real = de.dexpi_marks.write

        def moved(xml, *a):
            out, again = real(xml, *a)
            again["nodes"][0]["geometry"] = None
            return out, again
        with mock.patch.object(de.dexpi_marks, "write", moved), self.assertRaises(de.ExportError) as cm:
            export(snp_pair(SNP[0]))
        self.assertIn("자리가 다름", " ".join(cm.exception.reasons))


if __name__ == "__main__":
    unittest.main()
