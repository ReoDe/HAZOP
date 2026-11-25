"""등록된 DEXPI 도면을 새로 내보낸 파일로 바꿀 때 사람 고침을 잇는 일(hazop.extract.edit_link, HZ-PLN-22 §4.2.1) 시험.

손으로 만든 작은 DEXPI 파일을 두 벌 쓴다. 옛 파일은 계기와 노즐 없는 설비에 자리가 없던 모양(사람 고침의 지문에 at이 없음)이다.
실행: python -m unittest tests.test_dexpi_edit_link
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import ai_review, corrections, edit_link  # noqa: E402
from hazop.extract.adapters import dexpi_import  # noqa: E402

OLD, NEW = "p__material-aaaaaaaaaaaa-r1-p0", "p__material-bbbbbbbbbbbb-r1-p0"
CONFIRM = {"items": [{"check": "unplaced", "reason": "그대로"}]}


def new_file():
    """자리가 모두 있는 새 파일의 추출 결과. 계기 PIF1(controller P101)의 자리를 채운다."""
    with open(os.path.join(REPO_ROOT, "tests", "fixtures", "dexpi", "small-pid-dexpi2.xml"), "rb") as fh:
        ex = dexpi_import.extract_bytes(fh.read(), "new.xml")[0]
    place(ex, "PIF1", [150, 60, 0, 0])
    return ex


def node(ex, sid):
    return next(n for n in ex["nodes"] if n["source_object_id"] == sid)


def place(ex, sid, box):
    local = next(x["local_id"] for k in ("nodes", "relations", "unresolved_connectors") for x in ex[k] if x["source_object_id"] == sid)
    ex["source_locations"] = [loc for loc in ex["source_locations"] if loc["local_id"] != local]
    if box is not None:
        ex["source_locations"].append({"object_id": sid, "local_id": local, "coordinate_space": "dexpi_diagram", "unit": "mm", "bbox": list(box),
                                       "approximate": True, "method": "dexpi_positions"})


def old_file(placeless=("PIF1", "Pump1")):
    ex = new_file()
    for sid in placeless:
        place(ex, sid, None)
    return ex


def extra(ex, sid, like, box, **change):
    """like를 베낀 구성요소를 하나 더한다."""
    n = copy.deepcopy(node(ex, like))
    n.update(source_object_id=sid, local_id="dx-" + sid, **change)
    ex["nodes"].append(n)
    place(ex, sid, box)


class LinkTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-edit-link-")
        self.env = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = self.tmp
        self.old, self.new = old_file(), new_file()

    def tearDown(self):
        if self.env is None:
            os.environ.pop("HAZOP_WORK_ROOT", None)
        else:
            os.environ["HAZOP_WORK_ROOT"] = self.env
        shutil.rmtree(self.tmp)

    # ----- 도움
    def write(self):
        for name, ex in ((OLD, self.old), (NEW, self.new)):
            folder = os.path.join(paths.output_root("extract"), name)
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "extraction.json"), "w", encoding="utf-8") as fh:
                json.dump(ex, fh, ensure_ascii=False)

    def edit(self, op, target, value, **more):
        rec = corrections.load(OLD)
        ops = list((rec or {}).get("ops") or [])
        ops.append(dict(corrections.make_op(self.old, op, target, value, "검토자", existing_ops=ops, name=OLD), **more))
        corrections.save_fp(OLD, ops, "검토자", drawing_number=self.old["drawing"]["drawing_number"])
        return ops[-1]["op_id"]

    def carry(self):
        self.write()
        return edit_link.carry(OLD, NEW, "검토자", at="2026-11-25T00:00:00+00:00")

    def resolved(self):
        return corrections.resolve(NEW)["corrected"]

    def applied(self):
        return (self.resolved().get("corrections") or {}).get("applied") or []

    def raw(self, name):
        with open(corrections.store_path(name), "rb") as fh:
            return fh.read()

    def outcome(self, change=None, target="PIF1", op="set_tag", value=None):
        """고침 하나를 남기고 이은 뒤 (적용됨, 갈래, 사유)."""
        oid = self.edit(op, target, value or {"tag": "ZZ-9"})
        if change:
            change()
        row = next(r for r in self.carry()["rows"] if r["op_id"] == oid)
        return oid in self.applied(), row["outcome"], row["why"]

    # ----- 잇기
    def test_an_edit_on_a_placeless_target_reaches_the_same_object(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        self.edit("set_kind", "Pump1", {"kind": "tank", "category": "equipment"})
        self.assertEqual([x["op_id"] for x in corrections.apply(self.new, corrections.load(OLD)["ops"])["corrections"]["not_applicable"]],
                         ["c-0001", "c-0002"])      # 잇기 전: 자리가 '없음 → 있음'이라 다른 대상으로 본다
        out = self.carry()
        self.assertEqual([r["outcome"] for r in out["rows"]], ["linked", "linked"])
        doc = self.resolved()
        self.assertEqual((node(doc, "PIF1")["tag"], node(doc, "Pump1")["kind"]), ("ZZ-9", "tank"))
        self.assertEqual(doc["corrections"]["not_applicable"], [])

    def test_an_edit_that_applies_as_it_is_stays_as_it_is(self):
        self.edit("set_tag", "Valve1", {"tag": "V-900"})
        before = corrections.load(OLD)["ops"]
        out = self.carry()
        self.assertEqual([r["outcome"] for r in out["rows"]], ["same"])
        self.assertEqual(corrections.load(NEW)["ops"], before)
        self.assertEqual(node(self.resolved(), "Valve1")["tag"], "V-900")

    def test_an_edit_that_points_at_a_placeless_part_is_linked_too(self):
        oid = self.edit("set_endpoint", "Pipe2", {"end": "source", "node": "Pump1"})
        out = self.carry()
        self.assertEqual(out["rows"][0]["outcome"], "linked")
        self.assertIn(oid, self.applied())
        self.assertEqual(corrections.load(NEW)["ops"][0]["refs"]["Pump1"]["at"], [60, 120])

    def test_what_was_linked_can_be_read_back(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        base = corrections.load(OLD)["ops"][0]["base"]
        self.carry()
        self.assertEqual(corrections.load(NEW)["ops"][0]["base_before"], {"PIF1": base})

    # ----- 잇지 않음
    def test_same_tag_twice_in_the_new_file(self):
        self.assertEqual(self.outcome(lambda: extra(self.new, "PIF2", "PIF1", [10, 10, 0, 0])), (False, "left", "tag_not_unique"))

    def test_same_tag_twice_in_the_old_file(self):
        extra(self.old, "PIF2", "PIF1", None)
        self.assertEqual(self.outcome(), (False, "left", "tag_not_unique"))

    def test_same_tag_on_another_kind(self):
        self.assertEqual(self.outcome(lambda: extra(self.new, "Tank9", "Tank1", [10, 10, 0, 0], tag=" p 101")), (False, "left", "tag_not_unique"))

    def test_two_in_the_old_file_and_three_in_the_new(self):
        extra(self.old, "PIF2", "PIF1", None)

        def change():
            extra(self.new, "PIF2", "PIF1", [10, 10, 0, 0])
            extra(self.new, "PIF3", "PIF1", [20, 20, 0, 0])
        self.assertEqual(self.outcome(change), (False, "left", "tag_not_unique"))

    def test_an_empty_tag(self):
        for tag in (None, "", "  "):
            with self.subTest(tag=tag):
                self.setUp()
                for ex in (self.old, self.new):
                    node(ex, "PIF1")["tag"] = tag
                self.assertEqual(self.outcome(op="confirm", value=CONFIRM), (False, "left", "no_tag"))

    def test_an_unknown_kind_is_not_linked_even_with_a_tag(self):
        place(self.old, "Mixer1", None)
        self.assertEqual(self.outcome(target="Mixer1"), (False, "left", "no_kind"))

    def test_neither_kind_nor_tag(self):
        for ex in (self.old, self.new):
            node(ex, "PIF1").update(kind=None, tag=None)
        self.assertFalse(self.outcome(op="confirm", value=CONFIRM)[0])

    def test_another_kind(self):
        self.assertEqual(self.outcome(lambda: node(self.new, "PIF1").update(kind="transmitter")), (False, "left", "kind_changed"))

    def test_another_tag(self):
        self.assertEqual(self.outcome(lambda: node(self.new, "PIF1").update(tag="P102")), (False, "left", "tag_changed"))

    def test_the_object_is_gone_and_another_has_its_tag(self):
        def change():
            node(self.new, "PIF1").update(source_object_id="PIF7")
        self.assertEqual(self.outcome(change), (False, "left", "gone"))

    def test_an_object_that_had_a_place_and_moved(self):
        self.old = old_file(("PIF1",))
        self.assertEqual(self.outcome(lambda: place(self.new, "Pump1", [10, 10, 0, 0]), target="Pump1"), (False, "left", "moved"))

    def test_a_moved_object_is_not_passed_on_to_what_now_stands_in_its_place(self):
        """지금 엔진은 같은 자리·같은 종류가 하나면 옮겨 붙인다. 다른 파일에서는 그것이 다른 설비다."""
        def change():
            place(self.new, "Valve1", [10, 10, 0, 0])
            extra(self.new, "Valve2", "Valve1", [100, 120, 0, 0])
        oid = self.edit("set_tag", "Valve1", {"tag": "V-900"})
        change()
        self.assertEqual(corrections.apply(self.new, corrections.load(OLD)["ops"])["corrections"]["retargeted"][0]["to"], "Valve2")
        self.carry()
        self.assertNotIn(oid, self.applied())
        self.assertEqual(node(self.resolved(), "Valve2")["tag"], "V-101")

    def test_two_that_look_alike_in_one_place_and_the_ids_moved_on(self):
        """태그 없는 티 둘이 (반올림해) 같은 자리에 있는데 앞의 하나가 빠져 순번이 밀린 파일. 지금 비교로는 같은 대상으로 보인다."""
        def change():
            extra(self.new, "Tee0", "Tee1", [140, 110, 0, 0])
        extra(self.old, "Tee2", "Tee1", [140, 110, 0, 0])
        self.assertEqual(self.outcome(change, target="Tee1", op="confirm", value=CONFIRM), (False, "left", "not_alone"))

    def test_two_that_look_alike_in_one_place_with_the_same_ids_stay(self):
        for ex in (self.old, self.new):
            extra(ex, "Tee2", "Tee1", [140, 110, 0, 0])
        self.assertEqual(self.outcome(target="Tee1", op="confirm", value=CONFIRM), (True, "same", None))

    def test_a_relation_without_a_place(self):
        place(self.old, "SC1", None)
        self.assertEqual(self.outcome(target="SC1", op="confirm", value=CONFIRM), (False, "left", "relation"))

    def test_an_id_the_reader_made_up(self):
        for ex in (self.old, self.new):
            ex["validation"]["unknowns"].append({"check": "dexpi_item_without_id", "source_object_id": "PIF1", "target": None, "field": None, "reason": ""})
        self.assertEqual(self.outcome(), (False, "left", "made_id"))

    def test_an_id_that_is_used_twice(self):
        self.assertEqual(self.outcome(lambda: self.new["nodes"].append(copy.deepcopy(node(self.new, "PIF1")))), (False, "left", "duplicate_id"))

    def test_an_edit_that_did_not_apply_before_does_not_start_to_apply(self):
        oid = self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        node(self.old, "PIF1")["kind"] = node(self.new, "PIF1")["kind"] = "transmitter"
        self.old["nodes"], rest = self.old["nodes"], None   # noqa: F841
        row = self.carry()["rows"][0]
        self.assertEqual((row["outcome"], row["why"]), ("left", "not_of_old_file"))
        self.assertNotIn(oid, self.applied())

    def test_without_a_place_on_both_sides_a_tag_is_still_needed(self):
        for ex in (self.old, self.new):
            place(ex, "PIF1", None)
            node(ex, "PIF1")["tag"] = None
        self.assertEqual(self.outcome(op="confirm", value=CONFIRM), (False, "left", "no_tag"))

    def test_an_edit_that_stayed_behind_is_kept_whole(self):
        self.edit("set_tag", "Mixer1", {"tag": "ZZ"})
        place(self.new, "Mixer1", [1, 1, 0, 0])
        op = corrections.load(OLD)["ops"][0]
        self.carry()
        kept = corrections.load(NEW)["ops"][0]
        self.assertEqual(kept["held"], {"why": "moved", "base": op["base"], "refs": op["refs"]})
        self.assertEqual({k: kept[k] for k in ("op_id", "op", "target", "value")}, {k: op[k] for k in ("op_id", "op", "target", "value")})
        self.assertEqual([x["op_id"] for x in self.resolved()["corrections"]["not_applicable"]], ["c-0001"])

    # ----- 다른 도면
    def refused(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        with self.assertRaises(edit_link.Refused) as got:
            self.carry()
        self.assertFalse(os.path.exists(corrections.store_path(NEW)))
        return got.exception.code

    def test_another_drawing_number(self):
        self.new["drawing"]["drawing_number"] = "TEST-2"
        self.assertEqual(self.refused(), "other_drawing")

    def test_an_unknown_drawing_number(self):
        for ex in (self.old, self.new):
            ex["drawing"]["drawing_number"] = None
        self.assertEqual(self.refused(), "number_unknown")

    def register(self, ex, confirmed, in_file):
        ex["drawing"].update(identification_basis="registration_confirmed", drawing_number=confirmed,
                             title_block_candidates={"drawing_number": in_file, "revision": None, "title": "Small test P&ID"})

    def test_a_confirmed_number_does_not_hide_the_number_in_the_file(self):
        self.register(self.old, "TEST-1", "TEST-1")
        self.register(self.new, "TEST-1", "TEST-2")
        self.assertEqual(self.refused(), "other_drawing")

    def test_the_number_in_the_file_does_not_hide_the_confirmed_number(self):
        self.register(self.old, "TEST-1", "TEST-1")
        self.register(self.new, "TEST-9", "TEST-1")
        self.assertEqual(self.refused(), "other_drawing")

    def test_a_number_that_is_not_confirmed_yet_is_read_from_the_file(self):
        self.register(self.old, "TEST-1", "TEST-1")
        self.register(self.new, None, "TEST-1")
        self.assertTrue(self.outcome()[0])

    def test_another_title(self):
        self.new["drawing"]["title"] = "Another"
        self.assertEqual(self.refused(), "other_drawing")

    def test_the_same_number_on_a_file_with_other_parts(self):
        for n in self.new["nodes"]:
            if n["tag"] and n["source_object_id"] != "PIF1":
                n["tag"] += "-X"
        self.assertEqual(self.refused(), "other_drawing")

    def untagged(self):
        for ex in (self.old, self.new):
            for n in ex["nodes"]:
                n["tag"] = None
        self.edit("confirm", "Valve1", CONFIRM)

    def test_a_drawing_without_any_tag_is_known_by_its_places(self):
        self.untagged()
        self.assertEqual(self.carry()["rows"][0]["outcome"], "same")

    def test_a_drawing_without_any_tag_whose_parts_stand_elsewhere(self):
        self.untagged()
        for n in self.new["nodes"]:
            place(self.new, n["source_object_id"], [5, 5, 0, 0])
        with self.assertRaises(edit_link.Refused) as got:
            self.carry()
        self.assertEqual(got.exception.code, "other_drawing")

    def test_another_project_or_page(self):
        self.old["project_id"], self.new["project_id"] = "a", "b"
        self.assertEqual(self.refused(), "other_project")

    def test_another_page(self):
        self.new["run"]["settings"]["page_index"] = 1
        self.assertEqual(self.refused(), "other_page")

    def test_other_formats_are_refused(self):
        for fmt in ("drawio", "pdf_vector"):
            with self.subTest(fmt=fmt):
                self.setUp()
                self.old["source"]["format"] = fmt
                self.assertEqual(self.refused(), "not_dexpi")

    # ----- 저장
    def test_the_old_record_does_not_change_by_a_byte(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        before = self.raw(OLD)
        self.carry()
        self.assertEqual(self.raw(OLD), before)

    def test_doing_it_twice_gives_the_same_file(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        self.carry()
        first = self.raw(NEW)
        out = edit_link.carry(OLD, NEW, "다른 사람")
        self.assertEqual((out["state"], self.raw(NEW)), ("already", first))

    def test_an_edit_undone_after_the_carry_stays_undone(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        self.carry()
        corrections.save_fp(NEW, [], "검토자", action="undo")
        edit_link.carry(OLD, NEW, "검토자")
        self.assertEqual(corrections.load(NEW)["ops"], [])

    def test_an_edit_undone_before_the_carry_stays_undone_but_can_be_redone(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        corrections.save_fp(OLD, [], "검토자", action="undo")
        self.carry()
        rec = corrections.load(NEW)
        self.assertEqual(rec["ops"], [])
        gone = rec["log"][-2]["removed_ops"]
        corrections.save_fp(NEW, gone, "검토자", action="redo")
        self.assertEqual(node(self.resolved(), "PIF1")["tag"], "ZZ-9")

    def test_op_numbers_are_not_used_again(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        corrections.save_fp(OLD, [], "검토자", action="undo")
        self.carry()
        self.assertEqual(corrections.make_op(self.new, "set_tag", "PIF1", {"tag": "B"}, "검토자", name=NEW)["op_id"], "c-0002")

    def test_a_sheet_that_already_has_edits_is_left_alone(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        self.write()
        corrections.save_fp(NEW, [corrections.make_op(self.new, "set_tag", "Valve1", {"tag": "B"}, "검토자", name=NEW)], "검토자")
        before = self.raw(NEW)
        with self.assertRaises(edit_link.Refused) as got:
            self.carry()
        self.assertEqual((got.exception.code, self.raw(NEW)), ("new_has_edits", before))

    def test_nothing_to_carry(self):
        self.assertEqual(self.carry()["state"], "none")
        self.assertFalse(os.path.exists(corrections.store_path(NEW)))

    def test_preview_writes_nothing(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        self.write()
        out = edit_link.carry(OLD, NEW, "검토자", dry_run=True)
        self.assertEqual((out["state"], out["rows"][0]["outcome"]), ("preview", "linked"))
        self.assertFalse(os.path.exists(corrections.store_path(NEW)))

    # ----- AI
    def ai(self, *cands):
        doc = ai_review.new_doc(OLD, self.old)
        doc["candidates"] = [dict({"cand_id": "a%d" % n, "field": "tag", "target": "PIF1", "values": ["X%d" % n], "bbox": [140, 50, 20, 20],
                                   "decided_at": None, "decided_by": None, "op_id": None}, **c) for n, c in enumerate(cands, 1)]
        ai_review.save_doc(doc)

    def test_a_rejected_candidate_does_not_come_back(self):
        self.edit("set_tag", "Valve1", {"tag": "V-900"})
        self.ai({"status": "rejected", "decided_at": "t", "decided_by": "검토자"}, {"status": "proposed"},
                {"status": "proposed", "decided_at": "t", "decided_by": "검토자"})
        self.carry()
        got = {c["cand_id"]: c["status"] for c in ai_review.load_doc(NEW)["candidates"]}
        self.assertEqual(got, {"a1": "rejected", "a3": "proposed"})    # 정한 적 없는 제안은 옛 그림에 대한 것이라 옮기지 않는다
        again = {"candidates": [dict(ai_review.load_doc(OLD)["candidates"][0], status="proposed", decided_at=None, decided_by=None)], "stats": {}}
        self.assertEqual(ai_review.merge_and_save(NEW, self.new, again)["candidates"][0]["status"], "rejected")
        self.assertIn("PIF1", ai_review.decided_targets(NEW))

    def test_an_undone_ai_value_is_protected_at_its_new_place(self):
        op = corrections.make_op(self.old, "set_tag", "PIF1", {"tag": "AI-1"}, "검토자", name=OLD)
        corrections.save_fp(OLD, [dict(op, origin="ai", ai_candidate="a1", accepted_by="검토자")], "검토자", action="ai_accept")
        corrections.save_fp(OLD, [], "검토자", action="ai_revert")
        self.carry()
        self.assertEqual(self.applied(), [])
        new = corrections.resolve(NEW)
        node(new["corrected"], "PIF1")["geometry"] = {"x": 145, "y": 55, "width": 10, "height": 10}
        self.assertIn("PIF1", ai_review.protected_targets(NEW, new, {"candidates": []}))

    def test_an_automatic_value_stays_automatic_and_a_human_value_stays_human(self):
        op = corrections.make_op(self.old, "set_kind", "PIF1", {"kind": "transmitter", "category": "instrument"}, corrections.AUTO_BY, name=OLD, auto=True)
        auto = dict(op, origin="ai", ai_candidate="a1", accepted_by=corrections.AUTO_BY)
        corrections.save_fp(OLD, [auto], corrections.AUTO_BY, action="ai_accept", auto=True)
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        self.carry()
        n = node(self.resolved(), "PIF1")
        self.assertEqual((n["kind"], n["tag"], n["human_edit"]["auto"]), ("transmitter", "ZZ-9", ["set_kind"]))
        ops = corrections.load(NEW)["ops"]
        self.assertEqual([corrections.is_auto(o) for o in ops], [True, False])
        corrections.save_fp(NEW, ops, "검토자")     # 사람이 이어서 저장해도 자동 값이 섞였다고 막히지 않는다


if __name__ == "__main__":
    unittest.main()
