"""원래 값 표시가 있는 파일로, 또는 그 파일에서 바꿔 들일 때 사람 고침을 잇는 시험(HZ-PLN-22 §6.9.4). 실행: python -m unittest tests.test_dexpi_origin_edits"""

import copy
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.export import dexpi_marks  # noqa: E402
from hazop.extract import corrections, edit_link  # noqa: E402
from hazop.extract.adapters import dexpi_origin as origin  # noqa: E402
from hazop.graph import build  # noqa: E402
from tests.test_dexpi_edit_link import new_file, node  # noqa: E402
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
        self.check(numbered(read(s.marked)), numbered(read(s.with_marks(lambda m: m[oid].update(Kind="condenser")))))

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
        from tests.test_dexpi_edit_link import extra, place
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
        from tests.test_dexpi_edit_link import extra
        extra(self.new, "HZ_I", "PIF1", [305, 205, 0, 0], kind=None, tag="P500")
        mark(self.new, "HZ_I", tag="PIC-500", kind="controller")
        self.assertEqual(self.added("PIC-500"), ("left", "in_file"))
        self.assertEqual(self.added(None), ("left", "in_file"))

    def test_a_part_the_old_file_had_is_not_the_added_one_because_of_its_mark(self):
        mark(self.new, "PIF1", tag="PIC-500")
        self.assertEqual(self.added("PIC-500"), ("same", None))


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
