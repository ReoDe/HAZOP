"""⑥ 초기사건 문서 전이(hazop.ie.model). 사람 확정 없이 '확정'이 되는 경로가 없는지, ID가 안정한지 본다.
상태 모델(초기사건 출력설계 §6.2)의 최단 반례 네 개를 실제 함수로 다시 밟고, 씨앗을 고정한 무작위 걸음으로 ⑥ 편집과
⑤ 편집(edit_entry·set_status·set_ie_hint)을 섞어 매 걸음 규칙을 확인한다. 표준 라이브러리만 쓴다.
실행: python -m unittest tests.test_ie_model
"""

import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop import store_io  # noqa: E402
from hazop.ie import bundle as ib  # noqa: E402
from hazop.ie import model  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_ie_bundle import ie_sample  # noqa: E402

AT = "2026-11-09T01:00:00Z"
HUMAN_YES = {"candidate": "yes", "disturbs": "yes", "challenges": "yes", "category": "LOMFW", "reason": ""}


def fresh():
    r, ns, pg = ie_sample()
    return r, ns, pg, model.sync(model.empty("P"), r, at=AT)


def iec(doc, r, entry_id):
    return model.iec_of(doc)[model.key_of(r["graph_id"], entry_id)]


def where(r, entry_id):
    f = model.entry_facts(r)[model.key_of(r["graph_id"], entry_id)]
    return f["node_id"], f["deviation_id"], entry_id


class BugPathTest(unittest.TestCase):
    """상태 모델이 찾은 반례 네 개. 고친 설계에서는 나쁜 상태에 닿지 않아야 한다."""

    def test_ai_member_moved_into_confirmed_group_makes_it_draft(self):
        r, _, _, doc = fresh()
        doc, gid = model.create_group(doc, "주급수 상실", [iec(doc, r, "c1")], at=AT)
        doc = model.confirm(doc, gid, r, "김검토", at=AT)
        self.assertEqual(model.effective_status(doc, gid, r), "confirmed")
        doc = model.place(doc, iec(doc, r, "c2"), gid, at=AT)  # c2는 AI 초안 판정
        self.assertEqual(model.effective_status(doc, gid, r), "draft")
        self.assertEqual(doc["groups"][gid]["status"], "draft")
        self.assertEqual(doc["history"][-1]["demoted"], [gid])
        with self.assertRaisesRegex(ValueError, "AI 초안"):
            model.confirm(doc, gid, r, "김검토", at=AT)

    def test_unapproved_member_cannot_be_confirmed(self):
        r, _, _, doc = fresh()
        doc, gid = model.create_group(doc, "주급수 상실", [iec(doc, r, "c1")], at=AT)
        r = res.edit_entry(r, *where(r, "c1"), {"cause": "다른 원인"}, at=AT)
        self.assertIn("%s: ⑤ 승인 풀림" % iec(doc, r, "c1"), model.confirm_problems(doc, gid, r))
        with self.assertRaisesRegex(ValueError, "승인 풀림"):
            model.confirm(doc, gid, r, "김검토", at=AT)
        self.assertEqual(model.effective_status(doc, gid, r), "draft")

    def test_member_content_change_after_confirm_needs_a_new_human_confirm(self):
        r, _, _, doc = fresh()
        doc, gid = model.create_group(doc, "주급수 상실", [iec(doc, r, "c1")], at=AT)
        doc = model.confirm(doc, gid, r, "김검토", at=AT)
        r = res.edit_entry(r, *where(r, "c1"), {"consequence": "증기발생기 수위 저하"}, at=AT)
        self.assertEqual(model.effective_status(doc, gid, r), "draft")
        r = res.set_status(r, *where(r, "c1"), "approved", at=AT)
        self.assertEqual(model.confirm_problems(doc, gid, r), [])
        self.assertEqual(model.effective_status(doc, gid, r), "draft", "다시 승인해도 사람이 다시 확정하기 전에는 초안")
        synced = model.sync(doc, r, at=AT)
        self.assertEqual((synced["groups"][gid]["status"], synced["history"][-1]["op"]), ("draft", "demote"))
        self.assertIs(model.sync(synced, r, at=AT), synced)
        again = model.confirm(synced, gid, r, "김검토", at=AT)
        self.assertEqual(model.effective_status(again, gid, r), "confirmed")

    def test_confirmed_group_cannot_be_deleted_and_ids_are_never_reused(self):
        r, _, _, doc = fresh()
        doc, gid = model.create_group(doc, "주급수 상실", [iec(doc, r, "c1")], at=AT)
        doc = model.confirm(doc, gid, r, "김검토", at=AT)
        with self.assertRaisesRegex(ValueError, "확정을 풀어야"):
            model.delete_group(doc, gid, at=AT)
        doc = model.delete_group(model.reopen(doc, gid, at=AT), gid, at=AT)
        self.assertEqual(doc["groups"][gid]["status"], "deleted")
        self.assertIsNone(doc["candidates"][iec(doc, r, "c1")]["group_id"])
        doc, new = model.create_group(doc, "다시 만든 그룹", [iec(doc, r, "c1")], at=AT)
        self.assertNotEqual(new, gid)
        self.assertIn(gid, doc["groups"])
        with self.assertRaises(ValueError):
            model.confirm(doc, gid, r, "김검토", at=AT)


    def test_rule_drafted_group_is_confirmed_only_as_a_human_group(self):
        r, ns, pg, doc = fresh()
        doc = model.suggest(doc, r, pg, at=AT)
        gid = doc["candidates"][iec(doc, r, "c1")]["group_id"]
        doc = model.accept(doc, ("member", iec(doc, r, "c1")), at=AT)
        for table, field in (("heading", "heading_ids"), ("end_state", "end_state_ids")):
            for rid in doc["groups"][gid][field]:
                doc = model.accept(doc, (table, rid), at=AT)
        self.assertEqual(doc["groups"][gid]["origin"], "ai_draft")
        doc = model.confirm(doc, gid, r, "김검토", at=AT)
        self.assertEqual(doc["groups"][gid]["origin"], "human", "확정한 검토자가 그룹 필드도 받아들인 것")
        g = next(x for x in ib.build_bundle(r, ns, pg, doc, AT)["groups"] if x["group_id"] == gid)
        self.assertEqual((g["origin"], g["status"]), ("human", "confirmed"))
        forged = dict(doc, groups=dict(doc["groups"], **{gid: dict(doc["groups"][gid], origin="ai_draft")}))
        self.assertEqual(model.effective_status(forged, gid, r), "draft", "AI 초안 그룹은 저장 상태가 확정이어도 초안")
        self.assertEqual(model.sync(forged, r, at=AT)["groups"][gid]["status"], "draft")
        g = next(x for x in ib.build_bundle(r, ns, pg, forged, AT)["groups"] if x["group_id"] == gid)
        self.assertEqual((g["origin"], g["status"]), ("ai_draft", "draft"))


class RuleTest(unittest.TestCase):
    def test_confirm_needs_reviewer_and_human_parts(self):
        r, _, pg, doc = fresh()
        doc = model.suggest(doc, r, pg, at=AT)
        gid = doc["candidates"][iec(doc, r, "c1")]["group_id"]
        self.assertEqual(doc["groups"][gid]["origin"], "ai_draft")
        with self.assertRaisesRegex(ValueError, "검토자"):
            model.confirm(doc, gid, r, " ", at=AT)
        problems = model.confirm_problems(doc, gid, r)
        self.assertTrue(any("받아들이기 전" in p for p in problems), problems)
        doc = model.accept(doc, ("member", iec(doc, r, "c1")), at=AT)
        for h in doc["groups"][gid]["heading_ids"]:
            doc = model.accept(doc, ("heading", h), at=AT)
        for e in doc["groups"][gid]["end_state_ids"]:
            doc = model.edit(doc, ("end_state", e), {"category": "core_damage_possible"}, at=AT)
        self.assertEqual(model.confirm_problems(doc, gid, r), [])
        doc = model.confirm(doc, gid, r, "김검토", at=AT)
        self.assertEqual(model.effective_status(doc, gid, r), "confirmed")

    def test_suggest_only_drafts_never_touches_confirmed_and_is_idempotent(self):
        r, _, pg, doc = fresh()
        doc, gid = model.create_group(doc, "사람 그룹", [iec(doc, r, "c1")], at=AT)
        doc = model.confirm(doc, gid, r, "김검토", at=AT)
        r = res.set_ie_hint(r, *where(r, "c4"), dict(HUMAN_YES), at=AT)
        doc = model.sync(doc, r, at=AT)
        once = model.suggest(doc, r, pg, at=AT)
        self.assertEqual(once["groups"][gid], doc["groups"][gid])
        self.assertEqual(model.effective_status(once, gid, r), "confirmed")
        new = [g for g in once["groups"] if g not in doc["groups"]]
        self.assertEqual([once["groups"][g]["origin"] for g in new], ["ai_draft"])
        self.assertFalse(any(g["status"] == "confirmed" for k, g in once["groups"].items() if k != gid))
        self.assertIs(model.suggest(once, r, pg, at=AT), once)

    def test_split_records_new_higher_ids_and_starts_drafts(self):
        r, _, _, doc = fresh()
        r = res.set_ie_hint(r, *where(r, "c4"), dict(HUMAN_YES), at=AT)
        doc = model.sync(doc, r, at=AT)
        a, b = iec(doc, r, "c1"), iec(doc, r, "c4")
        doc, gid = model.create_group(doc, "묶음", [a, b], at=AT)
        doc = model.confirm(doc, gid, r, "김검토", at=AT)
        doc, (g1, g2) = model.split(doc, gid, [b], at=AT)
        old = doc["groups"][gid]
        self.assertEqual((old["status"], old["split_into"]), ("split", [g1, g2]))
        self.assertTrue(g1 > gid and g2 > g1)
        self.assertEqual((model.members_of(doc, g1), model.members_of(doc, g2)), ([a], [b]))
        self.assertEqual([doc["groups"][g]["status"] for g in (g1, g2)], ["draft", "draft"])
        with self.assertRaises(ValueError):
            model.split(doc, g1, [a], at=AT)

    def test_edit_validates_and_keeps_before_values(self):
        r, _, _, doc = fresh()
        doc, gid = model.create_group(doc, "그룹", [iec(doc, r, "c1")], at=AT)
        with self.assertRaises(ValueError):
            model.edit(doc, ("group", gid), {"status": "confirmed"}, at=AT)
        with self.assertRaises(ValueError):
            model.edit(doc, ("group", gid), {"support_ie": "maybe"}, at=AT)
        doc = model.edit(doc, ("group", gid), {"definition": "주급수 유량이 끊기는 사건"}, at=AT)
        self.assertEqual(doc["history"][-1]["before"], {"definition": ""})
        self.assertIs(model.edit(doc, ("group", gid), {"definition": "주급수 유량이 끊기는 사건"}, at=AT), doc)

    def test_coverage_needs_reason_and_reviewer(self):
        _, _, _, doc = fresh()
        with self.assertRaises(ValueError):
            model.set_coverage(doc, "LOCHS", "out_of_scope", " ", "김검토", at=AT)
        doc = model.set_coverage(doc, "LOCHS", "out_of_scope", "복수기 도면 미등록", "김검토", at=AT)
        self.assertEqual(doc["coverage"]["LOCHS"]["by"], "김검토")
        self.assertNotIn("LOCHS", model.set_coverage(doc, "LOCHS", None, "", "", at=AT)["coverage"])


class FollowupTest(unittest.TestCase):
    """P3 후속(경미)으로 남겼던 저장·출처 경로 결함의 재현."""

    def test_group_is_not_confirmed_once_every_source_of_its_heading_is_unapproved(self):
        r, ns, pg, doc = fresh()
        doc = model.suggest(doc, r, pg, at=AT)
        h = doc["groups"][doc["candidates"][iec(doc, r, "c1")]["group_id"]]["heading_ids"][0]
        self.assertEqual([model.entry_of_key(s["key"]) for s in doc["headings"][h]["sources"]], ["c1"])
        doc = model.accept(doc, ("heading", h), at=AT)
        doc, gid = model.create_group(doc, "범주 없는 그룹", [iec(doc, r, "c4")], at=AT)
        doc = model.attach(doc, gid, ("heading", h), at=AT)
        doc = model.confirm(doc, gid, r, "김검토", at=AT)
        self.assertEqual(model.effective_status(doc, gid, r), "confirmed")
        r = res.set_status(r, *where(r, "c1"), "revised", at=AT)
        self.assertTrue(any(h in p and "승인" in p for p in model.confirm_problems(doc, gid, r)))
        self.assertEqual(model.effective_status(doc, gid, r), "draft")
        g = next(x for x in ib.build_bundle(r, ns, pg, model.sync(doc, r, at=AT), AT)["groups"] if x["group_id"] == gid)
        self.assertEqual((g["status"], g["heading_ids"]), ("draft", []))

    def test_heading_written_by_a_person_without_sources_does_not_block_confirm(self):
        r, _, _, doc = fresh()
        doc, gid = model.create_group(doc, "주급수 상실", [iec(doc, r, "c1")], at=AT)
        doc, _ = model.add_heading(doc, gid, {"name": "운전원 수동 급수"}, at=AT)
        self.assertEqual(model.confirm_problems(doc, gid, r), [])

    def test_moving_the_representative_out_clears_it_in_the_old_group(self):
        r, _, _, doc = fresh()
        a, b = sorted((iec(doc, r, "c1"), iec(doc, r, "c4")))
        doc, old = model.create_group(doc, "옛 그룹", [a, b], at=AT)
        self.assertEqual(doc["groups"][old]["representative"], a)
        doc, new = model.create_group(doc, "새 그룹", at=AT)
        moved = model.place(doc, a, new, at=AT)
        self.assertIsNone(moved["groups"][old]["representative"])
        self.assertEqual(model.confirm_problems(moved, old, r), [])
        pulled, _ = model.create_group(doc, "후보를 데려가는 그룹", [a], at=AT)
        self.assertIsNone(pulled["groups"][old]["representative"])

    def test_history_row_has_the_shape_of_the_0_1_file(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "store-0.1",
                               "initiating-events.json"), encoding="utf-8") as fh:
            old = next(h for h in json.load(fh)["history"] if h["op"] == "create_group")
        doc, _ = model.create_group(model.empty("P"), "그룹", at=old["at"])
        row = doc["history"][-1]
        self.assertEqual(list(row), ["at", "op", "ids"])
        self.assertEqual(store_io.dump_bytes(dict(row, ids=old["ids"])), store_io.dump_bytes(old))

    def test_move_history_names_the_old_group_and_the_cleared_representative(self):
        r, _, _, doc = fresh()
        a, b = sorted((iec(doc, r, "c1"), iec(doc, r, "c4")))
        doc, old = model.create_group(doc, "옛 그룹", [a, b], at=AT)
        doc, new = model.create_group(doc, "새 그룹", at=AT)
        row = model.place(doc, a, new, at=AT)["history"][-1]
        self.assertEqual((row["from"], row["to"], row["representative_cleared"]), (old, new, [old]))
        row = model.place(doc, b, new, at=AT)["history"][-1]
        self.assertEqual((row["from"], row["to"]), (old, new))
        self.assertNotIn("representative_cleared", row)
        pulled, made = model.create_group(doc, "데려가는 그룹", [a], at=AT)
        self.assertEqual(pulled["history"][-1]["representative_cleared"], [old])

    def test_reapproving_the_same_content_between_syncs_keeps_the_confirmation(self):
        """Codex 지적의 재현: ⑥을 열지 않은 사이 승인을 풀었다가 같은 내용으로 다시 승인하면 확정이 유지되고 ⑥ 이력에
        강등이 남지 않는다. 확정 지문이 내용만 보기 때문이다. 지금은 이 동작을 그대로 둔다(보고에 남김)."""
        r, _, _, doc = fresh()
        doc, gid = model.create_group(doc, "주급수 상실", [iec(doc, r, "c1")], at=AT)
        doc = model.confirm(doc, gid, r, "김검토", at=AT)
        r = res.set_status(r, *where(r, "c1"), "revised", at=AT)
        self.assertEqual(model.effective_status(doc, gid, r), "draft")
        r = res.set_status(r, *where(r, "c1"), "approved", at=AT)
        self.assertEqual(model.effective_status(doc, gid, r), "confirmed")
        self.assertIs(model.sync(doc, r, at=AT), doc)

    def test_moving_a_non_representative_keeps_the_old_representative(self):
        r, _, _, doc = fresh()
        a, b = sorted((iec(doc, r, "c1"), iec(doc, r, "c4")))
        doc, old = model.create_group(doc, "옛 그룹", [a, b], at=AT)
        doc, new = model.create_group(doc, "새 그룹", at=AT)
        self.assertEqual(model.place(doc, b, new, at=AT)["groups"][old]["representative"], a)


class IdStabilityTest(unittest.TestCase):
    def test_same_entry_keeps_iec_while_other_approvals_come_and_go(self):
        r, ns, pg, doc = fresh()
        target = iec(doc, r, "c4")
        b0 = ib.build_bundle(r, ns, pg, doc, AT)
        r = res.set_status(r, *where(r, "a1"), "revised", at=AT)       # 앞쪽 승인이 풀림
        r = res.set_status(r, *where(r, "a2"), "approved", at=AT)      # 다른 항목이 새로 승인
        doc = model.sync(doc, r, at=AT)
        self.assertEqual(iec(doc, r, "c4"), target)
        self.assertEqual(iec(doc, r, "a2"), "IEC-%03d" % len(doc["candidates"]))
        b1 = ib.build_bundle(r, ns, pg, doc, AT)
        pick = lambda b: next(c["candidate_id"] for c in b["candidates"] if c["entry_id"] == "c4")  # noqa: E731
        self.assertEqual(pick(b0), pick(b1))
        r = res.set_status(r, *where(r, "a1"), "approved", at=AT)
        doc2 = model.sync(doc, r, at=AT)
        self.assertIs(doc2, doc, "다시 승인된 항목은 옛 IEC를 그대로 쓴다")
        rebuilt = model.sync(model.empty("P"), r, at=AT)
        self.assertNotEqual(model.iec_of(rebuilt), model.iec_of(doc), "저장 파일 없이 새로 매기면 번호가 달라질 수 있음")

    def test_bundle_refuses_unsynced_doc(self):
        r, ns, pg, doc = fresh()
        r = res.set_status(r, *where(r, "a2"), "approved", at=AT)
        with self.assertRaisesRegex(ValueError, "⑥"):
            ib.build_bundle(r, ns, pg, doc, AT)


# ---------------------------------------------------------------- 무작위 걸음

class Walk:
    """⑥ 편집과 ⑤ 편집을 섞어 걷는다. 걸음마다 check()가 규칙을 본다."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.r, _, self.pg, self.doc = fresh()
        self.entries = list(model.entry_facts(self.r))
        self.seen_iec = dict(model.iec_of(self.doc))
        self.seen_ids = {t: set(self.doc[t])
                         for t in ("candidates", "groups", "headings", "end_states", "basic_events")}
        self.counters = dict(self.doc["counters"])
        self.snapshots = {}
        self.confirms = 0

    def pick(self, xs):
        return self.rng.choice(sorted(xs)) if xs else None

    def live(self):
        return model.live_groups(self.doc)

    def six(self):
        d, rng = self.doc, self.rng
        iecs = list(d["candidates"])
        op = rng.choice(("create", "place", "place", "accept", "accept_parts", "edit", "heading", "attach", "remove",
                         "confirm", "confirm", "confirm", "reopen", "split", "delete", "suggest", "end_state"))
        g = self.pick(self.live())
        if op == "create":
            d, _ = model.create_group(d, "그룹", rng.sample(iecs, min(len(iecs), rng.randint(0, 2))), at=AT)
        elif op == "place" and iecs:
            d = model.place(d, self.pick(iecs), rng.choice(self.live() + [None]), at=AT)
        elif op == "accept":
            refs_ = [("member", i) for i, c in d["candidates"].items() if c["group_id"]]
            refs_ += [("heading", h) for h in d["headings"]] + [("end_state", e) for e in d["end_states"]]
            if refs_:
                d = model.accept(d, rng.choice(sorted(refs_)), at=AT)
        elif op == "accept_parts" and g:  # 표제·최종상태만 받아들이고 규칙이 넣은 소속은 그대로 둔다
            for field, kind in (("heading_ids", "heading"), ("end_state_ids", "end_state")):
                for rid in d["groups"][g][field]:
                    d = model.accept(d, (kind, rid), at=AT)
        elif op == "edit" and g:
            d = model.edit(d, ("group", g), {"definition": "정의 %d" % rng.randint(0, 3)}, at=AT)
        elif op == "heading" and g:
            d, _ = model.add_heading(d, g, {"name": "원자로 정지"}, at=AT)
        elif op == "end_state" and g:
            d, _ = model.add_end_state(d, g, {"text": "노심 냉각 위협"}, at=AT)
        elif op == "attach" and g:
            hs = [h for h, v in d["headings"].items() if v["status"] == "live"]
            if hs:
                d = model.attach(d, g, ("heading", self.pick(hs)), on=rng.random() < 0.6, at=AT)
        elif op == "remove":
            recs = [("heading", h) for h in d["headings"]] + [("end_state", e) for e in d["end_states"]]
            if recs:
                d = model.remove(d, rng.choice(sorted(recs)), at=AT)
        elif op == "confirm" and g:
            try:
                d = model.confirm(d, g, self.r, "김검토", at=AT)
            except ValueError:
                pass
            else:
                facts = model.entry_facts(self.r)
                self.snapshots[g] = {m: facts[d["candidates"][m]["key"]]["fp"] for m in model.members_of(d, g)}
                self.confirms += 1
        elif op == "reopen" and g:
            d = model.reopen(d, g, at=AT)
        elif op == "split" and g:
            members = model.members_of(d, g)
            if len(members) >= 2:
                d, _ = model.split(d, g, rng.sample(members, rng.randint(1, len(members) - 1)), at=AT)
        elif op == "delete" and g and d["groups"][g]["status"] == "draft":
            d = model.delete_group(d, g, at=AT)
        elif op == "suggest":
            d = model.suggest(d, self.r, self.pg, at=AT)
        self.doc = d

    def five(self):
        rng = self.rng
        placed = [c["key"] for c in self.doc["candidates"].values()
                  if c["group_id"] and self.doc["groups"][c["group_id"]]["status"] == "confirmed"]
        key = rng.choice(placed if placed and rng.random() < 0.6 else self.entries)  # 소속 후보를 자주 건드려야 반례에 닿음
        f = model.entry_facts(self.r)[key]
        loc = (f["node_id"], f["deviation_id"], model.entry_of_key(key))
        op = rng.choice(("edit", "approve", "approve", "revise", "hint"))
        if op == "edit":
            self.r = res.edit_entry(self.r, *loc, {"cause": "원인 %d" % rng.randint(0, 9)}, at=AT)
        elif op in ("approve", "revise"):
            self.r = res.set_status(self.r, *loc, "approved" if op == "approve" else "revised", at=AT)
        else:
            self.r = res.set_ie_hint(self.r, *loc, dict(HUMAN_YES, candidate=rng.choice(("yes", "yes", "undecided")),
                                                        category=rng.choice(("LOMFW", "LOIA"))), at=AT)
        if rng.random() < 0.5:  # ⑥을 열 때마다 맞춘다. 열지 않은 채로도 파생 상태가 맞아야 한다
            self.doc = model.sync(self.doc, self.r, at=AT)

    def check(self, t):
        d, r = self.doc, self.r
        t.assertEqual(model.problems(d), [])
        facts = model.entry_facts(r)
        for g in model.live_groups(d):
            if model.effective_status(d, g, r, facts) != "confirmed":
                continue
            members = model.members_of(d, g)
            t.assertTrue(members)
            t.assertEqual(d["groups"][g]["origin"], "human", g)
            for m in members:
                c = d["candidates"][m]
                f = facts[c["key"]]
                t.assertTrue(f["approved"] and f["ie_human"] and c["placed_by"] == "human", (g, m))
                t.assertEqual(f["fp"], self.snapshots[g][m], "확정 뒤 바뀐 후보가 확정 그룹에 있음")
            t.assertEqual(set(members), set(self.snapshots[g]))
            for table, field in (("headings", "heading_ids"), ("end_states", "end_state_ids")):
                for rid in d["groups"][g][field]:
                    t.assertEqual((d[table][rid]["origin"], d[table][rid]["status"]), ("human", "live"))
        for p, n in d["counters"].items():
            t.assertGreaterEqual(n, self.counters[p])
        self.counters = dict(d["counters"])
        for table, ids in self.seen_ids.items():
            t.assertTrue(ids <= set(d[table]), "ID가 사라짐: %s" % (ids - set(d[table])))
            ids.update(d[table])
        for k, v in model.iec_of(d).items():
            t.assertEqual(self.seen_iec.setdefault(k, v), v, "같은 항목의 IEC가 바뀜")
        for g, v in d["groups"].items():
            if v["status"] == "split":
                t.assertEqual(len(v["split_into"]), 2)
                t.assertTrue(all(s in d["groups"] and s > g for s in v["split_into"]))
        once = model.sync(d, r, at=AT)
        t.assertIs(model.sync(once, r, at=AT), once)


class RandomWalkTest(unittest.TestCase):
    SEEDS = range(16)
    STEPS = 300

    def test_no_confirmed_without_human_and_ids_stable(self):
        confirms = 0
        for seed in self.SEEDS:
            with self.subTest(seed=seed):
                w = Walk(seed)
                for _ in range(self.STEPS):
                    (w.six if w.rng.random() < 0.7 else w.five)()
                    w.check(self)
                confirms += w.confirms
        self.assertGreater(confirms, 20, "걸음이 확정에 거의 닿지 않으면 규칙을 시험하지 못한 것")


if __name__ == "__main__":
    unittest.main()
