"""정리된 보기를 DEXPI에서 그리기(HZ-PLN-22 §6.8, hazop/export/dexpi_screen.py) 시험. 실행: python -m unittest tests.test_dexpi_screen

지은 DEXPI를 되읽은 그림이 지금 정리된 보기와 같은지, 어긋나면 까닭을 내고 지금 길로 돌아가는지 본다. 임시 작업 루트만 쓴다.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hazop import paths, store_io  # noqa: E402
from hazop.export import dexpi_export, dexpi_screen as ds  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from hazop.extract.adapters import dexpi_import, pdf_vector  # noqa: E402
from hazop.graph import build as graph_build  # noqa: E402
from hazop.shell import clean_items, sheet_items  # noqa: E402
from tests.test_clean_items import SNP, snp_extractions  # noqa: E402
from tests.test_dexpi_picture import extract, fixture, usage, with_pump  # noqa: E402

FIXTURES = os.path.join(REPO, "tests", "fixtures", "dexpi")


def samples():
    with open(os.path.join(FIXTURES, "screen-view-samples.json"), encoding="utf-8") as fh:
        return json.load(fh)


def drawn(extraction):
    """정리된 보기가 그리는 자료(화면이 지금 부르는 두 함수)."""
    return [sheet_items.build_items(extraction), clean_items.build(extraction)]


def differences(a, b, path=""):
    """두 자료의 다른 곳."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b)) for d in differences(a.get(k), b.get(k), "%s/%s" % (path, k))]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, "%s/%d" % (path, i))]
    return [] if a == b else [(path, a, b)]


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-dexpi-screen-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        env.start()
        self.addCleanup(env.stop)
        self.page = samples()["page"]

    def same_picture(self, extraction, name="S"):
        before = copy.deepcopy(extraction)
        view = ds.prepare(name, extraction)
        self.assertTrue(view.ok, (view.code, view.detail))
        self.assertEqual(extraction, before)
        self.assertEqual(differences(drawn(extraction), drawn(view.extraction)), [])
        return view

    @staticmethod
    def quiet():
        return mock.patch.object(ds.LOG, "warning")

    def files(self):
        return {os.path.relpath(os.path.join(d, f), self.tmp): store_io.read_bytes(os.path.join(d, f))[1]
                for d, _dirs, fs in os.walk(self.tmp) for f in fs}

    def edit(self, change, name="S"):
        """캐시의 곁 파일을 고쳐 쓴다."""
        path = ds.cache_paths(name)[1]
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        change(doc)
        store_io.write_json(path, doc)

    def code(self, extraction=None, **kw):
        with self.quiet():
            view = ds.open_view("S", extraction or self.page, **kw)
        self.assertEqual(view.ok, view.code is None)
        self.assertEqual(view.ok, view.extraction is not None)
        return view.code


class SamePictureTest(Base):

    def test_the_snp_drawio_sheets_look_the_same_as_now(self):
        for name, ex in snp_extractions().items():
            with self.subTest(name):
                self.same_picture(ex, name)
        self.assertGreaterEqual(len(SNP), 6)

    def test_snp_m_101_boxes_lines_and_names_come_from_the_file_and_the_rest_from_the_sidecar(self):
        view = self.same_picture(snp_extractions()["SNP-M-101"])
        extra = view.sidecar["solid_extra"]
        used = {k for group in extra.values() for e in group.values() for k in e}
        self.assertLessEqual(sum("box" in e for e in extra["nodes"].values()), 1, "되돌릴 수 없는 소수 상자 하나 말고는 DEXPI에서 온다")
        self.assertNotIn("turn", used)
        self.assertNotIn("points", used, "선은 모두 DEXPI에서 온다")
        items = {i["tag"]: i for i in sheet_items.build_items(view.extraction)["items"]}
        self.assertEqual(items["RC-V010"]["kind"], "motor_operated_valve")
        self.assertEqual(items["RC-SG01"]["kind"], "steam_generator")
        x0, y0, x1, y1 = items["RC-LT101"]["bbox"]
        self.assertEqual((round(x1 - x0, 1), round(y1 - y0, 1)), (40.0, 40.0))
        clean = clean_items.build(view.extraction)["items"]
        self.assertIn(["TO SNP-M-102", "RC-L010 SURGE LINE"], [e.get("label") for e in clean.values()])
        for line_no in ("RC-L001", "RC-L002", "RC-L011"):
            self.assertIn(line_no, items)

    def test_dexpi_drawings_look_the_same_as_now(self):
        with open(os.path.join(FIXTURES, "small-pid-proteus.xml"), encoding="utf-8") as fh:
            proteus = fh.read()
        for name, text in (("dexpi2", fixture()), ("proteus", proteus), ("turned", with_pump(usage(rot=90.0, mirrored="true", sx=2.0)))):
            with self.subTest(name):
                self.same_picture(extract(text), name)

    def test_an_exported_sheet_that_came_back_as_dexpi_looks_the_same_as_now(self):
        ex = snp_extractions()["SNP-M-102"]
        xml = dexpi_export.export_drawing(graph_build.build_graph(ex), ex, require_confirmed_number=False).xml
        view = self.same_picture(dexpi_import.extract_bytes(xml, "x.xml")[0])
        self.assertEqual(view.verdict()["ledger"]["component"]["solid"], len(ex["nodes"]))

    def test_the_contract_samples(self):
        doc = samples()
        view = self.same_picture(doc["page"])
        self.assertEqual(drawn(view.extraction), [doc["items"], doc["clean"]])
        self.assertEqual(json.loads(json.dumps(view.verdict())), doc["verdict"])
        self.assertEqual([v["code"] for v in doc["fallback_verdicts"]], list(ds.CODES))
        for v in doc["fallback_verdicts"]:
            self.assertEqual(ds.View(v["code"], v["detail"]).verdict(), v)

    def test_the_spec_lists_every_reason_code(self):
        with open(os.path.join(REPO, "docs", "specs", "dexpi-exchange.md"), encoding="utf-8") as fh:
            section = fh.read().split("### 6.8 ", 1)[1].split("\n## 7", 1)[0]
        for code in ds.CODES:
            self.assertIn("`%s`" % code, section)

    def test_review_marks_mean_the_same(self):
        ex = snp_extractions()["SNP-M-101"]
        a, b = (next(n for n in ex["nodes"] if n["tag"] == t) for t in ("RC-V010", "RC-LT101"))
        ops = [corrections.make_op(ex, "set_tag", a["source_object_id"], {"tag": "RC-V999"}, "검토자", at="2026-11-25T00:00:00Z", existing_ops=[])]
        ops.append(dict(corrections.make_op(ex, "set_kind", b["source_object_id"], {"kind": "indicator", "category": "instrument"}, "x",
                                            at="2026-11-25T00:00:00Z", existing_ops=ops), by=corrections.AUTO_BY, accepted_by=corrections.AUTO_BY))
        fixed = corrections.apply(ex, ops)
        self.assertEqual(len(fixed["corrections"]["applied"]), 2)
        fixed["nodes"][3]["origin"] = "ai"
        view = self.same_picture(fixed)
        items = clean_items.build(view.extraction)["items"]
        self.assertEqual([items[x]["review"] for x in (a["local_id"], b["local_id"], fixed["nodes"][3]["local_id"])], ["human", "ai_auto", "ai_accepted"])

    def test_a_person_moving_a_pipe_moves_it_in_the_picture(self):
        ex = snp_extractions()["SNP-M-101"]
        pipe = next(r for r in ex["relations"] if r["kind"] == "physical_connection" and r["waypoints"])
        op = corrections.make_op(ex, "set_path", pipe["source_object_id"], {"points": [[100, 100], [150, 120], [200, 100]]}, "검토자",
                                 at="2026-11-25T00:00:00Z", existing_ops=[])
        view = self.same_picture(corrections.apply(ex, [op]))
        item = next(i for i in sheet_items.build_items(view.extraction)["items"] if i["id"] == pipe["local_id"])
        self.assertEqual(len(item["polyline"]), 3)

    def test_a_relation_with_one_point_and_a_drawing_without_a_number_and_an_empty_sheet(self):
        self.page["drawing"]["drawing_number"] = None
        self.same_picture(self.page, "no-number")
        empty = dict(self.page, nodes=[], relations=[], unresolved_connectors=[], source_locations=[],
                     validation={"status": "passed", "blockers": [], "unknowns": []})
        self.assertEqual(self.same_picture(empty, "empty").verdict()["ledger"]["component"],
                         {"total": 0, "solid": 0, "dashed": 0, "unplaced": 0})

    def test_every_part_is_in_exactly_one_place_and_nothing_disappears(self):
        for name, ex in snp_extractions().items():
            view = ds.prepare(name, ex)
            s, v = view.sidecar, view.verdict()
            for group, key in (("nodes", "nodes"), ("relations", "relations"), ("unresolved", "unresolved_connectors")):
                places = [x for part in (s["solid_extra"].get(group, {}), s["dashed"][group], s["unplaced"][group]) for x in part]
                self.assertEqual(sorted(places), sorted(x["local_id"] for x in ex[key]), (name, group))
            self.assertEqual(sum(c["total"] for c in v["ledger"].values()), sum(len(ex[k]) for k in ("nodes", "relations", "unresolved_connectors")))
            shown = {i["id"] for i in sheet_items.build_items(view.extraction)["items"]}
            self.assertLessEqual({d["id"] for d in v["dashed"] if d["what"] != "unresolved"}, shown)


class VectorPdfTest(Base):

    def test_the_vector_pdf_output_is_byte_for_byte_the_same_and_nothing_is_written(self):
        folder = next(d for d in sorted(os.listdir(paths.folder("references", "pid-samples"))) if d.startswith("SNP-M-401"))
        ex = pdf_vector.extract(paths.folder("references", "pid-samples", folder, folder + ".pdf"), page=0, repo_root=REPO)
        waiting = dict(copy.deepcopy(ex), corrections={"inputs": {"waiting": ["c-0001"], "state": "waiting"}})
        for page in (ex, waiting):
            before = json.dumps([page, drawn(page)], ensure_ascii=False).encode("utf-8")
            for fn in (ds.prepare, ds.open_view):
                view = fn("S", page)
                self.assertEqual((view.ok, view.code, view.extraction), (False, "format", None))
                self.assertEqual(view.verdict()["source"], "extraction")
            self.assertEqual(json.dumps([page, drawn(page)], ensure_ascii=False).encode("utf-8"), before)
        self.assertEqual(self.files(), {})

    def test_only_drawio_and_dexpi_are_drawn_from_the_file(self):
        for fmt in ("pdf", "pdf_vector", "raster", "", None):
            self.assertEqual(ds.prepare("S", dict(self.page, source={"format": fmt})).code, "format")


class FallBackTest(Base):
    """무엇이 틀려도 지금 길로 돌아간다."""

    def setUp(self):
        Base.setUp(self)
        self.assertTrue(ds.prepare("S", self.page).ok)

    def test_nothing_built_and_missing_files(self):
        self.assertEqual(ds.open_view("other", self.page).code, "no_cache")
        xml, side = ds.cache_paths("S")
        with open(xml, "rb") as fh:
            data = fh.read()
        os.remove(xml)
        self.assertEqual(self.code(), "no_cache")
        store_io.write_bytes(xml, data)
        os.remove(side)
        self.assertEqual(self.code(), "no_sidecar")
        self.assertTrue(ds.prepare("S", self.page).ok)

    def test_a_changed_drawing_a_changed_key_and_another_version_are_stale(self):
        changed = copy.deepcopy(self.page)
        changed["nodes"][0]["tag"] = "OTHER"
        self.assertEqual(self.code(changed), "stale")
        self.assertEqual(self.code(ver="v2"), "stale")
        self.assertEqual(self.code(symbols="s2"), "stale")
        with mock.patch.object(ds, "WRITER", "next"):
            self.assertEqual(self.code(), "stale")
            self.assertTrue(ds.prepare("S", self.page).ok)
        self.edit(lambda d: d.update(schema="hazop_dexpi_screen/9"))
        self.assertEqual(self.code(), "stale")

    def test_a_sheet_whose_name_becomes_the_same_file_name_does_not_get_this_picture(self):
        self.assertEqual(paths.safe_name("S "), paths.safe_name("S"))
        self.assertEqual(ds.open_view("S ", self.page).code, "no_cache")

    def test_sheets_whose_names_become_the_same_file_name_keep_their_own_pictures(self):
        for name in ("S ", "s"):    # 파일 이름으로 바꾸면 같아지는 이름, Windows에서 같은 파일인 이름
            self.assertTrue(ds.prepare(name, self.page).ok)
            self.assertEqual([ds.open_view(n, self.page).code for n in ("S", name)], [None, None])

    def test_a_changed_file_does_not_match_its_sidecar(self):
        xml = ds.cache_paths("S")[0]
        with open(xml, "rb") as fh:
            data = fh.read()
        store_io.write_bytes(xml, data.replace(b"RC-V010", b"RC-V011"))
        self.assertEqual(self.code(), "sidecar_mismatch")

    def test_broken_files_are_unreadable(self):
        side = ds.cache_paths("S")[1]
        for text in (b"", b"{", b"[]", b"\xff\xfe", b'{"name": "S"'):
            store_io.write_bytes(side, text)
            self.assertEqual(self.code(), "unreadable", text)
        with self.quiet():
            ds.prepare("S", self.page)
        self.edit(lambda d: d.pop("ids"))
        self.assertEqual(self.code(), "unreadable")

    def test_a_part_gone_from_the_file_is_noticed_even_when_the_hash_fits(self):
        def put(data):
            store_io.write_bytes(ds.cache_paths("S")[0], data)
            self.edit(lambda d: d.update(dexpi_sha256=store_io.fingerprint_of(data).split(":")[1]))
        with open(ds.cache_paths("S")[0], encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("HZ_entity_node_006", text)
        put(text.replace("HZ_entity_node_006", "HZ_entity_node_666").encode("utf-8"))
        self.assertEqual(self.code(), "missing_part")
        self.edit(lambda d: d["in_file"]["nodes"].remove("HZ_entity_node_006"))
        self.assertEqual(self.code(), "extra_part")

    def mutant(self, change):
        """곁 파일을 고친 뒤의 까닭 코드. 캐시는 그 뒤 되돌린다."""
        with open(ds.cache_paths("S")[1], "rb") as fh:
            keep = fh.read()
        self.edit(change)
        got = self.code()
        store_io.write_bytes(ds.cache_paths("S")[1], keep)
        self.assertIsNone(self.code())
        return got

    def test_dropping_one_id_is_caught_in_every_group(self):
        dashed = [("nodes", "local-node-004"), ("nodes", "local-node-005"), ("nodes", "local-node-007"), ("relations", "local-rel-003"),
                  ("relations", "local-rel-005"), ("unresolved", "local-rel-007")]
        for group, lid in dashed:
            self.assertEqual(self.mutant(lambda d: d["dashed"][group].pop(lid)), "ledger", lid)
        for group, lid in (("nodes", "local-node-008"), ("relations", "local-rel-006")):
            self.assertEqual(self.mutant(lambda d: d["unplaced"][group].pop(lid)), "ledger", lid)
        for group, lid in (("nodes", "local-node-002"), ("relations", "local-rel-001"), ("relations", "local-rel-004")):
            self.assertEqual(self.mutant(lambda d: d["solid_extra"][group].pop(lid)), "ledger", lid)

    def test_replacing_one_id_is_caught_although_the_counts_stay(self):
        for part, group, lid in (("dashed", "nodes", "local-node-004"), ("dashed", "relations", "local-rel-003"), ("dashed", "unresolved", "local-rel-007"),
                                 ("unplaced", "nodes", "local-node-008"), ("solid_extra", "nodes", "local-node-002"),
                                 ("solid_extra", "relations", "local-rel-002")):
            def change(d):
                d[part][group]["x-999"] = d[part][group].pop(lid)
            self.assertEqual(self.mutant(change), "ledger", (part, lid))

    def test_a_part_counted_twice_is_caught(self):
        def change(d):
            d["unplaced"]["nodes"]["local-node-004"] = d["dashed"]["nodes"]["local-node-004"]
            d["ledger"]["component"]["unplaced"] += 1
        self.assertEqual(self.mutant(change), "ledger")

    def test_a_wrong_count_is_caught(self):
        self.assertEqual(self.mutant(lambda d: d["ledger"]["pipe"].update(solid=9)), "ledger")

    def test_swapped_or_missing_links_to_the_file_are_caught(self):
        def swap(d, table, a, b):
            d["ids"][table][a], d["ids"][table][b] = d["ids"][table][b], d["ids"][table][a]
        self.assertEqual(self.mutant(lambda d: swap(d, "symbols", "HZ_entity_node_001", "HZ_entity_node_002")), "differs")
        self.assertEqual(self.mutant(lambda d: swap(d, "lines", "HZ_entity_seg_001", "HZ_entity_seg_002")), "differs")
        self.assertEqual(self.mutant(lambda d: swap(d, "nodes", "HZ_entity_node_002", "HZ_entity_node_003")), "differs")
        self.assertEqual(self.mutant(lambda d: d["ids"]["symbols"].pop("HZ_entity_node_003")), "missing_part")
        self.assertEqual(self.mutant(lambda d: d["ids"]["lines"].pop("HZ_entity_seg_002")), "missing_part")

    def test_a_changed_value_of_the_sidecar_is_caught(self):
        for change in (lambda d: d["solid_extra"]["nodes"]["local-node-002"].update(kind="manual_valve"),
                       lambda d: d["solid_extra"]["nodes"]["local-node-002"].pop("human_edit"),
                       lambda d: d["solid_extra"]["relations"]["local-rel-001"].pop("flow"),
                       lambda d: d["dashed"]["nodes"]["local-node-004"]["value"].update(box=[0, 0, 1, 1]),
                       lambda d: d["dashed"]["unresolved"]["local-rel-007"]["value"].update(line_no="X"),
                       lambda d: d["scale"].update(dx=12.0), lambda d: d["rest"].update(texts=[]), lambda d: d["rest"].update(unknowns=[])):
            self.assertEqual(self.mutant(change), "differs")

    def test_two_parts_with_one_id_are_not_drawn_from_the_file(self):
        self.page["nodes"].append(dict(self.page["nodes"][0]))
        self.assertEqual(ds.prepare("S", self.page).code, "ledger")


class BuildTest(Base):

    def test_a_build_that_raises_is_reported_and_not_tried_again_until_the_drawing_changes(self):
        with mock.patch.object(dexpi_export, "export_drawing", side_effect=dexpi_export.ExportError("검사")) as fn:
            self.assertEqual([ds.prepare("S", self.page).code for _ in range(2)], ["build_failed"] * 2)
            self.assertEqual(fn.call_count, 1)
        self.assertEqual(ds.open_view("S", self.page).code, "build_failed")
        self.page["nodes"][0]["tag"] = "RC-SG02"
        self.assertTrue(ds.prepare("S", self.page).ok)

    def test_a_drawing_that_fails_its_own_check_is_not_built(self):
        self.page["validation"].update(status="blocked", blockers=[{"check": "duplicate_id", "reason": "x"}])
        self.assertEqual(ds.prepare("S", self.page).code, "build_failed")

    def test_a_build_that_never_ends_in_files_leaves_the_old_way(self):
        with mock.patch.object(store_io, "write_bytes", side_effect=OSError("디스크")), self.quiet():
            self.assertEqual(ds.prepare("S", self.page).code, "build_failed")
        self.assertEqual(self.files(), {})

    def test_stopping_between_the_two_files_is_safe(self):
        self.assertTrue(ds.prepare("S", self.page).ok)
        old = copy.deepcopy(self.page)
        self.page["nodes"][0]["tag"] = "RC-SG02"
        with mock.patch.object(store_io, "write_json", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                ds.prepare("S", self.page)
        self.assertEqual(ds.open_view("S", self.page).code, "stale")
        self.assertEqual(ds.open_view("S", old).code, "sidecar_mismatch")
        self.assertTrue(ds.prepare("S", self.page).ok)

    def test_the_same_drawing_is_not_built_twice_and_gives_the_same_bytes(self):
        ds.prepare("S", self.page)
        first = self.files()
        with mock.patch.object(ds, "build", side_effect=AssertionError):
            self.assertTrue(ds.prepare("S", self.page).ok)
        shutil.rmtree(paths.folder("cache"))
        ds.prepare("S", self.page)
        self.assertEqual(self.files(), first)

    def test_only_the_cache_is_written_and_losing_it_changes_nothing_else(self):
        keep = paths.folder("drawing-edits", "S.json"), paths.folder("sheet-confirmations", "S.json"), os.path.join(paths.output_root("exports"), "manifest.json")
        for path in keep:
            store_io.write_json(path, {"a": 1})
        before = self.files()
        ds.prepare("S", self.page)
        after = self.files()
        self.assertEqual({k: after[k] for k in before}, before)
        new = [os.path.join(self.tmp, k) for k in set(after) - set(before)]
        self.assertEqual(sorted(new), sorted(ds.cache_paths("S")))
        shutil.rmtree(paths.folder("cache"))
        self.assertEqual(self.files(), before)
        self.assertTrue(ds.prepare("S", self.page).ok)

    def test_the_exported_files_do_not_carry_the_screen_data(self):
        x = dexpi_export.export_drawing(graph_build.build_graph(self.page), self.page, require_confirmed_number=False)
        self.assertEqual(len(x.files), 3)
        for data in x.files.values():
            self.assertNotIn(b"hazop_dexpi_screen", data)

    def test_a_place_the_file_cannot_hold_comes_from_the_sidecar(self):
        self.page["nodes"][0]["geometry"].update(x=100.123456)
        self.page["relations"][0]["waypoints"] = [[200.00001, 160]]
        self.page["nodes"][1]["style"] = "rotation=90"  # drawio의 rotation은 상자째 돌아 놓인 상자가 지금 정리 보기의 상자와 다르다
        view = self.same_picture(self.page)
        extra = view.sidecar["solid_extra"]
        for lid in ("local-node-001", "local-node-002"):
            self.assertIn("box", extra["nodes"][lid])
        self.assertIn("points", extra["relations"]["local-rel-001"])
        self.assertNotIn("box", extra["nodes"]["local-node-003"])

    def test_a_pipe_written_backwards_still_comes_from_the_file(self):
        self.page["relations"][0]["flow_direction"] = {"from": "local-node-002", "to": "local-node-001", "from_end": "target", "to_end": "source", "basis": "arrow"}
        view = self.same_picture(self.page)
        extra = view.sidecar["solid_extra"]["relations"]["local-rel-001"]
        self.assertTrue(extra["reverse"])
        self.assertNotIn("points", extra)

    def test_a_symbol_whose_direction_is_unknown_is_dashed_with_its_reason(self):
        self.page["nodes"][1]["style"] = "direction=south;flipH=1"
        view = self.same_picture(self.page)
        self.assertEqual([d["reason"] for d in view.verdict()["dashed"] if d["id"] == "local-node-002"], ["orientation_unknown"])


if __name__ == "__main__":
    unittest.main()
