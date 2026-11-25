"""원래 값 표시가 있는 파일로, 또는 그 파일에서 바꿔 들일 때 사람 고침을 잇는 시험(HZ-PLN-22 §6.9.4). 실행: python -m unittest tests.test_dexpi_origin_edits"""

import copy
import json
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.export import dexpi_marks  # noqa: E402
from hazop.extract import corrections, edit_link  # noqa: E402
from hazop.extract.adapters import dexpi_origin as origin  # noqa: E402
from hazop.graph import build  # noqa: E402
from tests.test_dexpi_edit_link import extra, new_file, node, place  # noqa: E402
from tests.test_dexpi_origin import Sheet, read, sheet  # noqa: E402


def numbered(ex):
    ex["drawing"]["drawing_number"] = ex["drawing"].get("drawing_number") or "T"
    return ex


def ops_of(ex):
    """대상마다 할 수 있는 고침."""
    rows = []
    for n in ex["nodes"]:
        sid = n["source_object_id"]
        rows += [("set_tag", sid, {"tag": "ZZ-1"}), ("set_kind", sid, {"kind": "pump", "category": "equipment"}), ("delete_node", sid, {}),
                 ("confirm", sid, {"items": [{"check": "unplaced", "reason": "그대로"}]})]
    for r in ex["relations"]:
        rows += [("set_path", r["source_object_id"], {"points": [[1, 1], [2, 2]]}),
                 ("set_endpoint", r["source_object_id"], {"end": "source", "node": ex["nodes"][0]["source_object_id"]})]
    out = []
    for row in rows:
        try:
            out.append(corrections.make_op(ex, row[0], row[1], row[2], "검토자", existing_ops=[]))
        except ValueError:
            pass
    return out


def applies(ex, op):
    return bool(corrections.apply(ex, [op])["corrections"]["applied"])


def mark(ex, sid, **values):
    """읽은 추출의 노드에 표시가 바꾼 값을 얹는다."""
    n = node(ex, sid)
    n[origin.PLAIN] = {k: n[k] for k in ("kind", "tag", "label_text")}
    n.update(values)
    return ex


class WholeSheetTest(unittest.TestCase):
    """SNP-M-101의 모든 대상에 할 수 있는 고침 전부가 표시를 빼고 견준 대로 이어지고 적용된다."""

    def check(self, old, new):
        ops = ops_of(old)
        self.assertGreater(len(ops), 100)
        edit_link.check_same_drawing(old, new)
        lost = []
        for op in ops:
            before = copy.deepcopy(op)
            (moved,), (row,) = edit_link.move_ops([op], old, new)
            self.assertEqual(op, before)
            if row["outcome"] == "left" or not applies(new, moved):
                lost.append((op["op"], op["target"], row["why"]))
        self.assertEqual(lost, [])

    def test_from_a_file_without_marks_to_a_file_with_marks(self):
        self.check(numbered(read(sheet().plain)), numbered(read(sheet().marked)))

    def test_from_a_file_with_marks_to_a_file_with_marks(self):
        self.check(numbered(read(sheet().marked)), numbered(read(sheet().marked)))

    def test_from_a_file_with_marks_back_to_a_file_without_marks(self):
        self.check(numbered(read(sheet().marked)), numbered(read(sheet().plain)))

    def test_to_a_file_whose_marks_say_something_else(self):
        s = sheet()
        oid = next(o for o, n in s.want.items() if n["kind"] == "steam_generator")
        old, new = numbered(read(s.marked)), numbered(read(s.with_marks(lambda m: m[oid].update(Kind="condenser"))))
        for op in ops_of(old):
            if op["target"] == oid:
                (moved,), (row,) = edit_link.move_ops([op], old, new)
                self.assertEqual((row["outcome"], row["why"], applies(new, moved)), ("left", "kind_changed", False), op["op"])
        self.assertEqual({o["op"] for o in ops_of(old) if o["target"] == oid}, {"set_tag", "set_kind", "delete_node", "confirm"})

    def test_a_file_exported_after_the_edit(self):
        """표시 있는 파일에서 고친 것이 새 파일의 표시로 들어와도 고침은 남는다."""
        old = numbered(read(sheet().marked))
        n = next(x for x in old["nodes"] if x["kind"] == "steam_generator")
        op = corrections.make_op(old, "set_kind", n["source_object_id"], {"kind": "condenser", "category": "equipment"}, "검토자", existing_ops=[])
        fixed = corrections.apply(old, [op])
        new = numbered(read(Sheet((fixed, build.build_graph(fixed))).marked))
        self.assertEqual(node(new, n["source_object_id"])["kind"], "condenser")
        (moved,), (row,) = edit_link.move_ops([op], old, new)
        self.assertEqual((row["outcome"], applies(new, moved)), ("linked", True))

    def test_what_was_linked_says_what_it_was(self):
        old, new = numbered(read(sheet().plain)), numbered(read(sheet().marked))
        sid = next(n["source_object_id"] for n in new["nodes"] if n["category"] == "instrument" and origin.PLAIN in n)
        op = corrections.make_op(old, "set_tag", sid, {"tag": "ZZ-1"}, "검토자", existing_ops=[])
        (moved,), (row,) = edit_link.move_ops([op], old, new)
        self.assertEqual((row["outcome"], moved["base_before"][sid], moved["base"]),
                         ("linked", op["base"], corrections._fingerprints(new)[sid]))


class NotTheSameTest(unittest.TestCase):
    """표시가 같은 대상으로 보이게 하지 않는다."""

    def setUp(self):
        self.old, self.new = new_file(), new_file()

    def move(self, op="set_tag", sid="PIF1", value=None):
        o = corrections.make_op(self.old, op, sid, value or {"tag": "ZZ-9"}, "검토자", existing_ops=[])
        (moved,), (row,) = edit_link.move_ops([o], self.old, self.new)
        return row["outcome"], row["why"], applies(self.new, moved)

    def test_a_marked_value_is_linked(self):
        mark(self.new, "PIF1", tag="PIC-101")
        self.assertEqual(self.move(), ("linked", None, True))

    def test_a_drawing_most_of_whose_tags_the_marks_changed_is_the_same_drawing(self):
        for n in self.new["nodes"]:
            mark(self.new, n["source_object_id"], tag="X-" + n["source_object_id"])
        edit_link.check_same_drawing(self.old, self.new)
        edit_link.check_same_drawing(self.new, self.old)
        for n in self.new["nodes"]:
            n.pop(origin.PLAIN)
        with self.assertRaises(edit_link.Refused):
            edit_link.check_same_drawing(self.old, self.new)

    def test_both_files_are_marked_and_the_marks_say_different_things(self):
        for placed in (True, False):
            for field, a, b, why in (("tag", "RC-FT101", "SI-FT101", "tag_changed"), ("kind", "switch", "recorder", "kind_changed"),
                                     ("label_text", "FT 101", "FT 101 A", "text_changed")):
                for op, value in (("delete_node", {}), ("set_tag", {"tag": "ZZ-9"}), ("confirm", {"items": [{"check": "unplaced", "reason": "그대로"}]})):
                    self.setUp()
                    mark(self.old, "PIF1", **{field: a})
                    mark(self.new, "PIF1", **{field: b})
                    if not placed:
                        place(self.old, "PIF1", None)
                    with self.subTest(op=op, field=field, placed=placed):
                        o = corrections.make_op(self.old, op, "PIF1", value, "검토자", existing_ops=[])
                        (moved,), (row,) = edit_link.move_ops([o], self.old, self.new)
                        self.assertEqual((row["outcome"], row["why"], applies(self.new, moved)), ("left", why, False))

    def test_a_mark_that_became_what_the_file_itself_says_is_different_too(self):
        n = node(self.old, "PIF1")
        mark(self.old, "PIF1", tag="RC-FT101")
        mark(self.new, "PIF1", tag=n[origin.PLAIN]["tag"])
        self.assertEqual(self.move()[:2], ("left", "tag_changed"))

    def test_the_new_mark_is_what_the_person_made_of_it(self):
        mark(self.old, "PIF1", kind="switch")
        mark(self.new, "PIF1", kind="recorder")
        ops = []
        for op, value in (("set_kind", {"kind": "recorder", "category": "instrument"}), ("confirm", {"items": [{"check": "unplaced", "reason": "그대로"}]})):
            ops.append(corrections.make_op(self.old, op, "PIF1", value, "검토자", existing_ops=ops))
        moved, rows = edit_link.move_ops(ops, self.old, self.new)
        self.assertEqual([r["outcome"] for r in rows], ["linked", "linked"])
        self.assertEqual(corrections.apply(self.new, moved)["corrections"]["not_applicable"], [])

    def test_shared_old_names_with_marks_on_both_sides(self):
        """옛 글자가 겹쳐도 자리가 있고 표시가 같으면 잇고, 자리가 없으면 잇지 않는다."""
        for ex in (self.old, self.new):
            extra(ex, "PIF2", "PIF1", [10, 10, 0, 0])
            mark(ex, "PIF1", tag="PIC-101")
            mark(ex, "PIF2", tag="PI-101")
        self.assertEqual(self.move(), ("same", None, True))
        place(self.old, "PIF1", None)
        self.assertEqual(self.move()[:2], ("left", "tag_not_unique"))

    def test_the_value_of_the_file_itself_changed(self):
        mark(self.new, "PIF1", tag="PIC-101")
        node(self.new, "PIF1")[origin.PLAIN]["tag"] = "T101"
        self.assertEqual(self.move(), ("left", "moved", False))

    def test_the_mark_equals_the_old_value_but_the_file_does_not(self):
        n = node(self.new, "PIF1")
        n[origin.PLAIN] = {"kind": n["kind"], "tag": "T101", "label_text": "T101"}
        self.assertEqual(self.move()[:2], ("left", "moved"))

    def test_an_edit_that_never_fitted_the_old_file(self):
        mark(self.old, "PIF1", tag="PIC-101")
        op = corrections.make_op(new_file(), "set_tag", "PIF1", {"tag": "ZZ-9"}, "검토자", existing_ops=[])    # 표시를 뺀 값에 남긴 지문
        (_m,), (row,) = edit_link.move_ops([op], self.old, self.new)
        self.assertEqual((row["outcome"], row["why"]), ("left", "not_of_old_file"))

    def test_tags_that_the_file_alone_cannot_tell_apart(self):
        """옛 글자가 겹치는 계기(T101 뭉침)는 자리가 없으면 표시된 태그가 달라도 잇지 않는다."""
        for ex in (self.old, self.new):
            extra(ex, "PIF2", "PIF1", [10, 10, 0, 0])
        place(self.old, "PIF1", None)
        place(self.old, "PIF2", None)
        mark(self.new, "PIF1", tag="PIC-101")
        mark(self.new, "PIF2", tag="PI-101")
        self.assertEqual(self.move()[:2], ("left", "tag_not_unique"))

    def added(self, tag, kind="controller", box=(300, 200, 10, 10)):
        op = corrections.make_op(self.old, "add_node", None, {"kind": kind, "category": "instrument", "tag": tag, "bbox": list(box)}, "검토자", existing_ops=[])
        (_m,), (row,) = edit_link.move_ops([op], self.old, self.new)
        return row["outcome"], row["why"]

    def test_an_added_instrument_that_comes_back_with_its_marked_tag(self):
        extra(self.new, "HZ_I", "PIF1", [305, 205, 0, 0], kind=None, tag="P500")
        mark(self.new, "HZ_I", tag="PIC-500", kind="controller")
        self.assertEqual(self.added("PIC-500"), ("left", "in_file"))
        self.assertEqual(self.added(None), ("left", "in_file"))

    def test_a_part_the_old_file_had_is_not_the_added_one_because_of_its_mark(self):
        mark(self.new, "PIF1", tag="PIC-500")
        self.assertEqual(self.added("PIC-500"), ("same", None))


class KindOfTheEditTest(unittest.TestCase):
    """옛 파일에서 적용되던 고침이 표시된 종류에는 할 수 없으면 남긴다(not_for_kind)."""

    def setUp(self):
        self.old, self.new = new_file(), new_file()

    def arrestor(self, kind="flame_arrestor", category="inline_component"):
        """파일만 읽으면 psv인 것이 표시로 kind가 된다. 옛 파일은 표시가 없다."""
        for ex in (self.old, self.new):
            node(ex, "Valve1").update(kind="psv", category="valve")
        mark(self.new, "Valve1", kind=kind, category=category)

    def ops(self, *rows):
        out = []
        for op, target, value in rows:
            out.append(corrections.make_op(self.old, op, target, value, "검토자", existing_ops=out))
        return out

    def move(self, ops):
        moved, rows = edit_link.move_ops(ops, self.old, self.new)
        return moved, [(r["outcome"], r["why"]) for r in rows], corrections.apply(self.new, moved)["corrections"]["applied"]

    NC, KIND = ("set_normal_position", "Valve1", {"value": "NC"}), ("set_kind", "Valve1", {"kind": "manual_valve", "category": "valve"})

    def test_a_normal_position_given_to_what_was_read_as_a_valve(self):
        self.arrestor()
        ops = self.ops(self.NC)
        before = copy.deepcopy(ops)
        (m,), verdict, done = self.move(ops)
        self.assertEqual((verdict, done), ([("left", "not_for_kind")], []))
        self.assertEqual((m["held"], m["base"], m["value"], m["target"]),
                         ({"why": "not_for_kind", "base": before[0]["base"], "refs": {}}, None, {"value": "NC"}, "Valve1"))
        self.assertEqual(ops, before)

    def test_a_fail_position(self):
        for ex in (self.old, self.new):
            node(ex, "Valve1").update(kind="control_valve", category="valve")
        mark(self.new, "Valve1", kind="flame_arrestor", category="inline_component")
        ops = self.ops(("set_fail_position", "Valve1", {"value": "FO"}))
        self.assertEqual(self.move(ops)[1:], ([("left", "not_for_kind")], []))

    def test_an_edit_the_marked_kind_allows_is_linked(self):
        self.arrestor("relief_valve", "valve")
        self.assertEqual(self.move(self.ops(self.NC))[1:], ([("linked", None)], ["c-0001"]))

    def test_a_person_gave_the_kind_first(self):
        self.arrestor()
        _m, verdict, done = self.move(self.ops(self.KIND, self.NC))
        self.assertEqual((verdict, done), ([("linked", None), ("linked", None)], ["c-0001", "c-0002"]))

    def test_a_person_gave_the_kind_afterwards(self):
        self.arrestor()
        _m, verdict, done = self.move(self.ops(self.NC, self.KIND))
        self.assertEqual((verdict, done), ([("left", "not_for_kind"), ("linked", None)], ["c-0002"]))

    def test_an_edit_that_did_not_apply_before_is_not_judged_by_this(self):
        self.arrestor()
        ops = self.ops(self.NC)
        node(self.old, "Valve1").update(kind="tank", category="equipment")
        self.assertEqual(self.move(ops)[1], [("left", "not_of_old_file")])
        self.arrestor()
        tee = next(n["source_object_id"] for n in self.old["nodes"] if n["kind"] == "tee")
        bad = dict(copy.deepcopy(ops[0]), target=tee, base=corrections._fingerprints(self.old)[tee])      # 분기에는 옛 파일에서도 정상 위치를 두지 않는다
        mark(self.new, tee, kind="reducer")
        self.assertEqual([v[0] for v in self.move([bad])[1]], ["linked"])

    def test_going_back_to_a_file_without_marks_is_not_judged_by_this(self):
        self.arrestor("relief_valve", "valve")
        self.old, self.new = self.new, self.old
        node(self.new, "Valve1").update(kind=None)
        node(self.old, "Valve1")[origin.PLAIN]["kind"] = None
        self.assertEqual(self.move(self.ops(self.NC))[1:], ([("same", None)], []))

    def test_without_marks_nothing_is_applied_to_find_out(self):
        with mock.patch.object(edit_link.corrections, "apply", side_effect=AssertionError("부르지 않음")):
            ops = [{"op_id": "c-0001", "op": "set_normal_position", "target": "Valve1", "base": corrections._fingerprints(self.old)["Valve1"], "refs": {},
                    "value": {"value": "NC"}}]
            self.assertEqual(edit_link.move_ops(ops, self.old, self.new)[1][0]["outcome"], "same")

    def test_an_undone_edit_is_judged_too(self):
        self.arrestor()
        (undone,) = self.ops(self.NC)
        old, new = edit_link._Sheet(self.old), edit_link._Sheet(self.new)
        moves = edit_link._Moves([], [undone], old, new)
        self.assertEqual(moves.rows([undone])[0]["why"], "not_for_kind")
        self.assertEqual(moves.move([undone])[0]["held"]["why"], "not_for_kind")

    def test_held_again_the_next_time(self):
        self.arrestor()
        moved, _v, _d = self.move(self.ops(self.NC))
        again, rows = edit_link.move_ops(moved, self.new, self.new)
        self.assertEqual((again, rows[0]["why"]), (moved, "not_for_kind"))


class UnmarkedTest(unittest.TestCase):

    def test_without_marks_the_plain_view_is_the_extraction_itself(self):
        ex = new_file()
        self.assertIs(origin.plain_view(ex), ex)
        s = edit_link._Sheet(ex)
        self.assertEqual(json.dumps(s.fp, sort_keys=True), json.dumps(s.plain, sort_keys=True))

    def test_marks_are_not_written_by_the_exporter(self):
        self.assertNotEqual(dexpi_marks.add(sheet().plain, sheet().marks), sheet().plain)
        self.assertFalse(any(origin.PLAIN in n for n in read(sheet().plain)["nodes"]))


if __name__ == "__main__":
    unittest.main()
