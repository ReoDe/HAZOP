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
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import ai_review, confirmation, corrections, edit_link  # noqa: E402
from hazop.extract.adapters import dexpi_import  # noqa: E402
from scripts import link_dexpi_edits  # noqa: E402

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
        tmp = tempfile.mkdtemp(prefix="hazop-edit-link-")
        env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": tmp})     # subTest가 다시 불러도 만든 폴더를 모두 지운다
        env.start()
        self.addCleanup(shutil.rmtree, tmp)
        self.addCleanup(env.stop)
        self.old, self.new = old_file(), new_file()

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

    # ----- 사람이 더한 것이 이미 새 파일에 있음
    def add(self, op, **value):
        return self.edit(op, None, value)

    def outcomes(self):
        return [(r["op_id"], r["outcome"], r["why"]) for r in self.carry()["rows"]]

    def tank(self, tag="TK-900", box=(300, 200, 10, 10)):
        return self.add("add_node", kind="tank", category="equipment", tag=tag, bbox=list(box))

    def test_an_added_part_that_the_new_file_has_is_not_added_again(self):
        oid = self.tank()
        extra(self.new, "HZ_TK", "Tank1", [305, 205, 0, 0], tag="tk-900")
        self.assertEqual(self.outcomes(), [(oid, "left", "in_file")])
        doc = self.resolved()
        self.assertEqual([n["source_object_id"] for n in doc["nodes"] if (n["tag"] or "").upper() == "TK-900"], ["HZ_TK"])
        self.assertEqual(corrections.load(NEW)["ops"][0]["value"]["tag"], "TK-900")

    def test_an_added_part_without_a_tag_is_known_by_its_place_and_kind(self):
        self.tank(tag=None)
        extra(self.new, "HZ_TK", "Tank1", [305, 205, 0, 0], tag=None)
        self.assertEqual(self.outcomes()[0][1:], ("left", "in_file"))

    def test_another_kind_in_the_place_of_an_added_part_is_not_the_added_part(self):
        self.tank(tag=None)
        extra(self.new, "HZ_P", "Pump1", [305, 205, 0, 0], tag="P-9")
        self.assertEqual(self.outcomes()[0][1:], ("same", None))

    def test_an_added_part_is_known_by_the_tag_it_was_given_later(self):
        oid = self.tank(tag=None)
        self.edit("set_tag", "manual-" + oid, {"tag": "TK-901"})
        extra(self.new, "HZ_TK", "Tank1", [1, 1, 0, 0], tag="TK-901")
        self.assertEqual([r[1:] for r in self.outcomes()], [("left", "in_file"), ("left", "needs_left")])

    def test_an_added_part_whose_tag_the_old_file_already_had_is_added_again(self):
        oid = self.tank(tag="T-101")
        self.assertEqual(self.outcomes(), [(oid, "same", None)])
        self.assertIn(oid, self.applied())

    def test_what_hangs_on_a_part_that_stayed_behind_stays_too(self):
        tank = self.tank()
        line = self.add("add_relation", kind="physical_connection", line_type="process", **{"from": "manual-" + tank, "to": "Valve1"})
        flow = self.edit("set_flow", "manual-" + line, {"from": "Valve1", "to": "manual-" + tank})
        end = self.edit("set_endpoint", "Pipe1", {"end": "target", "node": "manual-" + tank})
        extra(self.new, "HZ_TK", "Tank1", [305, 205, 0, 0], tag="TK-900")
        self.assertEqual(self.outcomes(), [(tank, "left", "in_file")] + [(x, "left", "needs_left") for x in (line, flow, end)])
        doc = self.resolved()
        self.assertEqual((doc["corrections"]["applied"], len(doc["corrections"]["not_applicable"])), ([], 4))
        ids_ = {n["local_id"] for n in doc["nodes"]}
        self.assertTrue(all(e["node_local_id"] in ids_ for r in doc["relations"] for e in r["endpoints"]))

    def test_an_added_pipe_that_the_new_file_has(self):
        self.old = old_file(("PIF1",))
        oid = self.add("add_relation", kind="physical_connection", line_type="process", **{"from": "Pump1", "to": "Tank1"})
        r = copy.deepcopy(next(x for x in self.new["relations"] if x["source_object_id"] == "Pipe1"))
        r.update(source_object_id="HZ_Pipe", local_id="dx-HZ_Pipe")
        for e, sid in zip(r["endpoints"], ("Tank1", "Pump1")):       # 내보낼 때 앞뒤가 바뀔 수 있다
            e["node_local_id"] = node(self.new, sid)["local_id"]
        self.new["relations"].append(r)
        self.assertEqual(self.outcomes(), [(oid, "left", "in_file")])

    def test_an_added_pipe_that_the_new_file_has_not(self):
        self.old = old_file(("PIF1",))
        oid = self.add("add_relation", kind="physical_connection", line_type="process", **{"from": "Pump1", "to": "Tank1"})
        self.assertEqual(self.outcomes(), [(oid, "same", None)])
        self.assertIn(oid, self.applied())

    # ----- 사람이 정한 후보의 대상
    def test_a_decided_candidate_of_an_object_that_became_another_is_frozen(self):
        self.edit("confirm", "Valve1", CONFIRM)
        self.ai({"status": "rejected", "decided_at": "t", "decided_by": "검토자", "target": "Tank1"},
                {"status": "rejected", "decided_at": "t", "decided_by": "검토자", "target": "Pump1"})
        node(self.new, "Tank1").update(tag="T-222")
        self.assertEqual(self.carry()["candidates"], "carried")
        doc = ai_review.load_doc(NEW)
        self.assertEqual(([c["cand_id"] for c in doc["candidates"]], [c["cand_id"] for c in doc["frozen"]]), (["a2"], ["a1"]))
        self.assertNotIn("Tank1", ai_review.decided_targets(NEW))
        self.assertEqual(ai_review.reconcile(NEW), [])
        ai_review.reject(ai_review.load_doc(NEW), {"a1"}, "검토자")
        again = {"candidates": [dict(doc["frozen"][0], status="proposed", decided_at=None, decided_by=None)], "stats": {}}
        ai_review.merge_and_save(NEW, self.new, again)
        doc = ai_review.load_doc(NEW)
        self.assertEqual({c["cand_id"]: c["status"] for c in doc["candidates"]}, {"a1": "proposed", "a2": "rejected"})
        self.assertEqual(doc["frozen"][0]["status"], "rejected")    # 저장을 거쳐도 남는다

    def test_a_connection_candidate_is_judged_by_both_ends(self):
        self.edit("confirm", "Valve1", CONFIRM)
        self.ai({"status": "rejected", "decided_at": "t", "decided_by": "검토자", "target": "Pipe1", "field": "connection", "values": ["Tank1"]})
        node(self.new, "Tank1").update(tag="T-222")
        self.carry()
        self.assertEqual([c["cand_id"] for c in ai_review.load_doc(NEW)["frozen"]], ["a1"])

    def test_an_accepted_candidate_whose_edit_stayed_behind_is_frozen(self):
        op = corrections.make_op(self.old, "set_tag", "Tank1", {"tag": "V-777"}, "검토자", name=OLD)
        corrections.save_fp(OLD, [dict(op, origin="ai", ai_candidate="a1", accepted_by="검토자")], "검토자", action="ai_accept")
        self.ai({"status": "accepted", "decided_at": "t", "decided_by": "검토자", "target": "Pump1", "op_id": op["op_id"]})
        node(self.new, "Tank1").update(tag="T-222")
        self.carry()
        kept = corrections.load(NEW)["ops"][0]
        self.assertEqual(("ai_candidate" in kept, kept["held"]["ai_candidate"]), (False, "a1"))
        self.assertEqual(ai_review.load_doc(NEW)["candidates"], [])
        fresh = {"candidates": [dict(ai_review.load_doc(NEW)["frozen"][0], status="proposed", op_id=None, decided_at=None, decided_by=None)], "stats": {}}
        ai_review.merge_and_save(NEW, self.new, fresh)
        self.assertEqual(ai_review.reconcile(NEW), [])      # 새 후보가 남긴 고침으로 수락된 것이 되지 않는다

    # ----- 남긴 고침의 자리
    def accept_at(self, target, where):
        """where 자리의 기호 target에 기계 후보를 두고 자동 수락을 켜서 돌린다."""
        rules_ = ai_review.AUTO_RULES
        place(self.new, target, [where[0], where[1], 0, 0])
        node(self.new, target).update(kind=None, classification="unclassified", tag=None,
                                      geometry={"x": where[0] - 5, "y": where[1] - 5, "width": 10, "height": 10})
        node(self.new, target)["attributes"].pop("kind", None)
        self.write()
        doc = ai_review.load_doc(NEW) or ai_review.new_doc(NEW, self.new)
        doc["candidates"].append({"cand_id": "m1", "task": "kind", "field": "kind", "target": target, "values": ["tank"], "confidence": 1.0,
                                  "bbox": [where[0] - 5, where[1] - 5, where[0] + 5, where[1] + 5], "status": "proposed", "op_id": None,
                                  "decided_at": None, "decided_by": None, "input": rules_.inputs[0], "legend_source": rules_.legends[0]})
        doc["candidates"][-1]["bbox"] = ai_review._box(node(self.new, target))
        ai_review.save_doc(doc)
        with mock.patch.object(ai_review, "AUTO_ACCEPT_ENABLED", True):
            return ai_review._auto_accept(NEW, self.new, {"state": "open", "auto": None})

    def moved_mixer(self):
        place(self.new, "Mixer1", [1, 1, 0, 0])

    def test_automatic_acceptance_works_where_no_person_was(self):
        self.edit("confirm", "Valve1", CONFIRM)
        self.carry()
        self.assertEqual(self.accept_at("Tank1", (190, 120))["accepted"], ["m1"])

    def test_the_place_of_an_edit_that_stayed_behind_is_still_protected(self):
        self.edit("set_tag", "Mixer1", {"tag": "ZZ"})
        self.moved_mixer()
        self.carry()
        self.assertEqual(self.accept_at("Tank1", (230, 120)), {"accepted": [], "blocked": {"protected": 1}})

    def test_the_place_of_a_part_an_edit_pointed_at_is_still_protected(self):
        self.edit("set_endpoint", "Pipe2", {"end": "source", "node": "Mixer1"})
        self.moved_mixer()
        self.carry()
        self.assertEqual(self.accept_at("Tank1", (230, 120))["blocked"], {"protected": 1})

    def undone_ai(self, target):
        op = corrections.make_op(self.old, "set_tag", target, {"tag": "AI-1"}, "검토자", name=OLD)
        corrections.save_fp(OLD, [dict(op, origin="ai", ai_candidate="a1", accepted_by="검토자")], "검토자", action="ai_accept")
        corrections.save_fp(OLD, [], "검토자", action="ai_revert")

    def test_the_place_of_an_undone_ai_value_that_stayed_behind_is_still_protected(self):
        self.undone_ai("Mixer1")
        self.moved_mixer()
        self.carry()
        self.assertEqual(self.accept_at("Tank1", (230, 120))["blocked"], {"protected": 1})

    def test_an_undone_ai_value_without_a_place_protects_its_id(self):
        self.undone_ai("PIF1")
        node(self.new, "PIF1")["tag"] = "P102"
        self.carry()
        self.assertEqual(self.accept_at("PIF1", (150, 60))["blocked"], {"protected": 1})

    # ----- 중간에 끊김
    def cut(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        self.ai({"status": "rejected", "decided_at": "t", "decided_by": "검토자"})
        with mock.patch.object(ai_review, "save_doc", side_effect=OSError("끊김")), self.assertRaises(OSError):
            self.carry()

    def test_a_carry_that_was_cut_short_is_finished_the_next_time(self):
        self.cut()
        self.assertIsNone(ai_review.load_doc(NEW))
        first = self.raw(NEW)
        out = self.carry()
        self.assertEqual((out["state"], out["candidates"], self.raw(NEW)), ("already", "carried", first))
        self.assertEqual([c["cand_id"] for c in ai_review.load_doc(NEW)["candidates"]], ["a1"])
        with open(ai_review.store_path(NEW), "rb") as fh:
            before = fh.read()
        self.assertEqual(self.carry()["candidates"], "already")
        with open(ai_review.store_path(NEW), "rb") as fh:
            self.assertEqual(fh.read(), before)

    def test_what_a_person_did_after_the_cut_is_kept(self):
        self.cut()
        ops = corrections.load(NEW)["ops"]
        mine = corrections.make_op(self.new, "set_tag", "Valve1", {"tag": "MINE"}, "검토자", existing_ops=ops, name=NEW)
        self.assertEqual(mine["op_id"], "c-0002")
        corrections.save_fp(NEW, ops + [mine], "검토자")
        self.assertEqual(self.carry()["candidates"], "carried")
        self.assertEqual([o["op_id"] for o in corrections.load(NEW)["ops"]], ["c-0001", "c-0002"])
        self.assertEqual(node(self.resolved(), "Valve1")["tag"], "MINE")

    def test_candidates_a_person_decided_after_the_cut_are_not_touched(self):
        self.cut()
        doc = ai_review.new_doc(NEW, self.new)
        doc["candidates"] = [dict(ai_review.load_doc(OLD)["candidates"][0], cand_id="n1")]
        ai_review.save_doc(doc)
        self.assertEqual(self.carry()["candidates"], "refused")
        self.assertEqual([c["cand_id"] for c in ai_review.load_doc(NEW)["candidates"]], ["n1"])

    def test_the_old_record_changed_after_the_carry(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        self.carry()
        first = self.raw(NEW)
        self.edit("set_tag", "Valve1", {"tag": "V-2"})
        out = self.carry()
        self.assertEqual((out["state"], out["changed"], self.raw(NEW)), ("already_stale", 1, first))

    # ----- 기계 후보만 있는 새 도면
    def machine(self, *cands):
        doc = ai_review.new_doc(NEW, self.new)
        doc["candidates"] = [dict({"cand_id": "m%d" % n, "field": "tag", "values": ["X"], "status": "proposed", "decided_at": None, "decided_by": None,
                                   "op_id": None, "bbox": [0, 0, 1, 1]}, **c) for n, c in enumerate(cands, 1)]
        ai_review.save_doc(doc)

    def test_machine_proposals_stay_unless_a_person_already_settled_the_object(self):
        self.edit("set_tag", "Valve1", {"tag": "V-900"})
        self.edit("set_tag", "Mixer1", {"tag": "ZZ"})
        self.moved_mixer()
        self.ai({"status": "rejected", "decided_at": "t", "decided_by": "검토자", "target": "Tank1"})
        self.machine({"target": "Valve1"}, {"target": "Tank1"}, {"target": "Tee1"}, {"target": "Mixer1"})
        self.assertEqual(self.carry()["candidates"], "carried")
        self.assertEqual([c["cand_id"] for c in ai_review.load_doc(NEW)["candidates"]], ["a1", "m3", "m4"])

    def test_candidates_a_person_decided_in_the_new_sheet_refuse_the_carry(self):
        self.edit("set_tag", "Valve1", {"tag": "V-900"})
        for change in ({"status": "rejected"}, {"status": "accepted"}, {"decided_at": "t"}):
            with self.subTest(change=change):
                self.machine(dict({"target": "Tee1"}, **change))
                with self.assertRaises(edit_link.Refused) as got:
                    self.carry()
                self.assertEqual(got.exception.code, "new_has_edits")
                os.remove(ai_review.store_path(NEW))
        self.assertFalse(os.path.exists(corrections.store_path(NEW)))

    def test_decisions_are_carried_even_without_any_edit(self):
        self.ai({"status": "rejected", "decided_at": "t", "decided_by": "검토자", "target": "Tank1"})
        self.assertEqual(self.carry()["state"], "carried")
        self.assertEqual(self.carry()["state"], "already")
        self.assertFalse(os.path.exists(corrections.store_path(NEW)))

    # ----- 자동 확정을 통째로 되돌림
    def auto(self, name, result, by="검토자", **more):
        return confirmation.record_auto(name, result, by=by if result == "reverted" or more else corrections.AUTO_BY, key="rk", **more)

    def test_a_sheet_a_person_reverted_stays_reverted_once(self):
        self.edit("set_tag", "Valve1", {"tag": "V-900"})
        self.auto(OLD, "reverted")
        self.carry()
        self.assertEqual(confirmation.auto_record(NEW)["result"], "reverted")
        self.auto(NEW, "waiting", why="started", restart=True)
        self.carry()
        self.assertEqual(confirmation.auto_record(NEW)["result"], "waiting")    # 사람이 다시 시킨 것을 덮지 않는다

    def test_an_automatic_confirmation_is_not_carried(self):
        self.edit("set_tag", "Valve1", {"tag": "V-900"})
        self.auto(OLD, "confirmed")
        self.carry()
        self.assertIsNone(confirmation.auto_record(NEW))

    def test_a_reverted_sheet_without_edits(self):
        self.auto(OLD, "reverted")
        self.assertEqual(self.carry()["state"], "carried")
        self.assertEqual(confirmation.auto_record(NEW)["result"], "reverted")

    # ----- 같은 자리의 다른 것
    def test_a_neighbour_whose_tag_was_not_read_before(self):
        """옛 파일의 V는 태그를 몰랐고(None), 새 파일에서는 그 자리에 태그 있는 다른 밸브의 id가 밀려 들어왔다."""
        for ex in (self.old, self.new):
            node(ex, "Valve1")["tag"] = None
        node(self.new, "Valve1")["tag"] = "V-222"
        extra(self.old, "Valve2", "Valve1", [100, 120, 0, 0], tag="V-222")
        extra(self.new, "Valve0", "Valve1", [100, 120, 0, 0], tag=None)
        self.assertEqual(self.outcome(target="Valve1"), (False, "left", "not_alone"))

    def test_a_neighbour_whose_kind_was_not_read_before(self):
        for ex in (self.old, self.new):
            node(ex, "Valve1").update(tag=None, kind=None)
        node(self.new, "Valve1")["kind"] = "check_valve"
        extra(self.old, "Valve2", "Valve1", [100, 120, 0, 0], kind="check_valve")
        extra(self.new, "Valve0", "Valve1", [100, 120, 0, 0], kind=None)
        self.assertEqual(self.outcome(target="Valve1"), (False, "left", "not_alone"))

    def test_a_tag_that_is_read_for_the_first_time_is_still_the_same_object(self):
        node(self.old, "Valve1")["tag"] = None
        self.assertEqual(self.outcome(target="Valve1"), (True, "same", None))

    def test_two_lines_in_one_place(self):
        oid = self.edit("confirm", "Pipe1", CONFIRM)
        r = copy.deepcopy(next(x for x in self.new["relations"] if x["source_object_id"] == "Pipe1"))
        r.update(source_object_id="Pipe0", local_id="dx-Pipe0")
        self.new["relations"].append(r)
        place(self.new, "Pipe0", [82, 120, 0, 0])
        self.assertEqual(self.outcomes(), [(oid, "left", "not_alone")])

    def test_a_measuring_line_that_moved_next_to_a_pipe_is_not_the_pipe(self):
        """두 파일에 모두 있는 측정선의 중점만 배관 자리로 옮겨 왔다(배관이 측정선으로 밝혀질 수 있다는 지금 비교의 관용에 걸림)."""
        oid = self.edit("confirm", "Pipe1", CONFIRM)
        place(self.new, "ML1", [82, 120, 0, 0])
        self.assertEqual(self.outcomes(), [(oid, "same", None)])

    def test_a_measuring_line_that_moved_away_from_a_pipe_is_not_the_pipe(self):
        place(self.old, "ML1", [82, 120, 0, 0])
        oid = self.edit("confirm", "Pipe1", CONFIRM)
        self.assertEqual(self.outcomes(), [(oid, "same", None)])

    def test_a_pipe_that_may_have_become_another_measuring_line(self):
        oid = self.edit("confirm", "Pipe1", CONFIRM)
        place(self.new, "ML1", [82, 120, 0, 0])
        next(r for r in self.new["relations"] if r["source_object_id"] == "ML1")["endpoints"][0]["source_object_id"] = "Valve1"
        self.assertEqual(self.outcomes(), [(oid, "left", "not_alone")])

    # ----- 같은 도면의 최소
    def keep_only(self, *sids):
        for ex in (self.old, self.new):
            ex["nodes"] = [n for n in ex["nodes"] if n["source_object_id"] in sids]
            ex["relations"], ex["unresolved_connectors"] = [], []

    def test_two_known_parts_are_too_few(self):
        self.keep_only("Valve1", "Tank1")
        self.edit("confirm", "Valve1", CONFIRM)
        with self.assertRaises(edit_link.Refused) as got:
            self.carry()
        self.assertEqual(got.exception.code, "other_drawing")

    def test_three_known_parts_are_enough(self):
        self.keep_only("Valve1", "Tank1", "Mixer1")
        self.edit("confirm", "Valve1", CONFIRM)
        self.assertEqual(self.carry()["state"], "carried")

    def test_exactly_half_is_not_enough(self):
        for n, sid in enumerate(("Pump1", "Tank1", "Mixer1")):
            node(self.new, sid)["tag"] = "Q-%d" % n
        for ex in (self.old, self.new):
            ex["nodes"] = [n for n in ex["nodes"] if n["tag"]]
            extra(ex, "Valve3", "Valve1", [9, 9, 0, 0], tag="V-103")
        # 옛 파일 6: 맞는 것 Valve1·PIF1·Valve3 = 3
        with self.assertRaises(edit_link.Refused):
            edit_link.check_same_drawing(self.old, self.new)

    # ----- 두 번째로 옮기기
    THIRD = "p__material-cccccccccccc-r1-p0"

    def on_to_the_third(self):
        folder = os.path.join(paths.output_root("extract"), self.THIRD)
        os.makedirs(folder)
        with open(os.path.join(folder, "extraction.json"), "w", encoding="utf-8") as fh:
            json.dump(self.new, fh)
        edit_link.carry(NEW, self.THIRD, "검토자")
        return corrections.load(self.THIRD)

    def test_what_stayed_behind_stays_behind_the_second_time(self):
        self.edit("set_tag", "Mixer1", {"tag": "ZZ"})
        self.moved_mixer()
        self.tank()
        extra(self.new, "HZ_TK", "Tank1", [305, 205, 0, 0], tag="TK-900")
        self.carry()
        self.assertEqual(self.on_to_the_third()["ops"], corrections.load(NEW)["ops"])

    def test_the_first_fingerprint_is_remembered_the_second_time(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        first = corrections.load(OLD)["ops"][0]["base"]
        self.carry()
        op = self.on_to_the_third()["ops"][0]
        self.assertEqual((op["base_before"], op["base"]["at"]), ({"PIF1": first}, [150, 60]))

    def test_an_unknown_reason_of_an_edit_that_stayed_behind(self):
        for held in ({"why": "later"}, "x", {"base": None}):
            with self.subTest(held=held):
                self.setUp()
                self.edit("set_tag", "Valve1", {"tag": "B"}, held=held)
                out = self.carry()
                self.assertEqual((out["rows"][0]["outcome"], out["rows"][0]["why"]), ("left", "unknown"))
                self.assertIn(out["rows"][0]["why"], edit_link.WHY)

    def test_links_made_in_two_steps_are_all_remembered(self):
        """첫 번째 파일에서 대상이, 두 번째 파일에서 참조가 이어진다."""
        place(self.old, "SC1", None)
        mid = self.new
        place(mid, "PIF1", None)
        self.old = old_file(("Pump1", "PIF1"))
        line = self.add("add_relation", kind="signal_connection", line_type="signal", points=[[1, 1], [2, 2]], **{"from": "PIF1", "to": "Pump1"})
        self.carry()
        self.new = new_file()
        op = next(o for o in self.on_to_the_third()["ops"] if o["op_id"] == line)
        self.assertEqual({k: v["at"] for k, v in op["base_before"].items()}, {"PIF1": None, "Pump1": None})

    def test_only_one_number_is_known(self):
        for ex in ("old", "new"):
            with self.subTest(ex=ex):
                self.setUp()
                getattr(self, ex)["drawing"]["drawing_number"] = None
                self.assertEqual(self.refused(), "number_unknown")

    def test_the_same_tags_on_other_kinds(self):
        for n in self.new["nodes"]:
            if n["source_object_id"] != "PIF1":
                n["kind"] = "filter"
        self.assertEqual(self.refused(), "other_drawing")

    def test_without_a_place_on_both_sides_a_tagged_object_is_the_same(self):
        place(self.new, "PIF1", None)
        self.assertEqual(self.outcome(), (True, "same", None))

    def test_a_part_in_the_middle_of_a_line_is_not_another_line(self):
        oid = self.edit("confirm", "Pipe1", CONFIRM)
        extra(self.new, "Odd", "Mixer1", [82, 120, 0, 0], tag="X-1")
        self.assertEqual(self.outcomes(), [(oid, "same", None)])

    def test_an_untagged_part_elsewhere_is_not_the_added_part(self):
        oid = self.tank(tag=None)
        extra(self.new, "Tee9", "Tee1", [5, 5, 0, 0])
        self.assertEqual(self.outcomes(), [(oid, "same", None)])

    def test_the_end_of_an_added_pipe_is_not_moved_to_what_stands_there_now(self):
        self.old = old_file(("PIF1",))
        line = self.add("add_relation", kind="physical_connection", line_type="process", **{"from": "Pump1", "to": "Tank1"})
        end = self.edit("set_endpoint", "manual-" + line, {"end": "target", "node": "Valve1"})
        place(self.new, "Valve1", [10, 10, 0, 0])
        extra(self.new, "Valve2", "Valve1", [100, 120, 0, 0])
        self.assertEqual(self.outcomes(), [(line, "same", None), (end, "left", "moved")])
        self.assertEqual(self.applied(), [line])

    # ----- 망가진 기록과 명령
    def test_broken_records_are_refused(self):
        self.edit("set_tag", "Valve1", {"tag": "B"})
        good = corrections.load(OLD)
        self.write()
        for bad in (dict(good, ops=[5]), dict(good, ops=5), dict(good, log=["x"]), dict(good, kind="other"), [1],
                    dict(good, ops=[dict(good["ops"][0], target=["a"])]), dict(good, ops=[dict(good["ops"][0], base="x")])):
            with open(corrections.store_path(OLD), "w", encoding="utf-8") as fh:
                json.dump(bad, fh)
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(edit_link.Refused) as got:
                edit_link.carry(OLD, NEW, "검토자")
            self.assertEqual(got.exception.code, "corrupt")
            with mock.patch("builtins.print"):
                self.assertEqual(link_dexpi_edits.main([OLD, NEW, "--by", "검토자"]), 1)
        self.assertFalse(os.path.exists(corrections.store_path(NEW)))

    def test_a_name_is_needed(self):
        self.edit("set_tag", "Valve1", {"tag": "B"})
        self.write()
        for by in ("", "  ", None, "hazop:auto"):
            with self.subTest(by=by), self.assertRaises(ValueError):
                edit_link.carry(OLD, NEW, by)
        self.assertFalse(os.path.exists(corrections.store_path(NEW)))

    def test_the_command(self):
        self.edit("set_tag", "PIF1", {"tag": "ZZ-9"})
        self.edit("set_tag", "Mixer1", {"tag": "ZZ"})
        self.moved_mixer()
        self.write()
        seen = []
        with mock.patch("builtins.print", side_effect=lambda *a: seen.append(a[0])):
            self.assertEqual(link_dexpi_edits.main([OLD, NEW, "--by", "검토자"]), 0)
            self.edit("set_tag", "Valve1", {"tag": "B"})
            self.assertEqual(link_dexpi_edits.main([OLD, NEW, "--by", "검토자"]), 1)
        self.assertEqual(seen, ["옮김: 그대로 적용 0, 이어짐 1, 적용 안 됨 1", "  c-0002 Mixer1: 자리나 내용이 달라짐",
                                "이미 옮겼고 그 뒤 옛 기록이 바뀜(덮거나 합치지 않음): 바뀐 고침 1"])


if __name__ == "__main__":
    unittest.main()
