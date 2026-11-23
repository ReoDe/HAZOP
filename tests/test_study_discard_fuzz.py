"""판 이전 퍼즈(tests.test_study_migrate_fuzz)에 사람이 묘비를 버리는 일(nodes.discard_lost)을 섞은 것. 실행:
python -m unittest tests.test_study_discard_fuzz (시드 수는 HAZOP_FUZZ_SEEDS)

판 이전마다 적용됨 구간 가운데 묘비가 남은 것을 골라 하나·여럿·전부를 버리고, 버린 구간을 사람이 병합·나누기·삭제하기도
한다. 퍼즈의 불변식 ①~⑧을 그대로 보되 버린 묘비는 '사람이 버림'으로 세어 사라짐이 아니다(①). 더 보는 것.
⑨ 버린 묘비는 닫힌 채다. 다음 판 이전과 병합·나누기·삭제 뒤에도 되찾지 않고(found가 차지 않음), 어느 구간의 lost로도
  돌아오지 않고, 버린 기록(구간 또는 집합 수준 discarded)이 사라지지 않는다. 퍼즈가 그 사이 집합을 백업으로 되돌리거나
  새로 제안했으면 보지 않는다.
⑩ 버린 뒤 needs_check의 lost_members는 남은 lost 수와 같고, 버린 묘비는 되찾지 못한 묘비 수에 들지 않는다.
⑪ 같은 버리기를 두 번 하면 같다(두 번째는 받은 집합 그대로).
⑫ AI는 사람 확인 없이 버린 묘비가 있는 구간을 병합·나누기·삭제하지 못한다.
"""

import copy
import os
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.study import idmap, node_tools  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from tests import test_study_migrate_fuzz as fz  # noqa: E402

STAMP = "c%02da5"  # 퍼즈 시각 차례(문서 c01a < 갈고리 < 새로 제안 c01b). 문서 판 추정이 집합 이력의 시각을 본다


class Discarder:
    """판 이전마다 묘비를 버리는 갈고리. 퍼즈의 난수(r)를 쓰지 않아 사슬은 퍼즈 그대로다."""

    def __init__(self, judge):
        self.j = judge
        self.gone = {}  # 시드 → (앞 갈고리 뒤 버렸고 되찾지 않은 묘비, 그때의 집합 바꿈 표지)

    def marks(self):
        """퍼즈가 갈고리 뒤에 집합을 바꾼 횟수(백업으로 되돌림·새로 제안). 바뀌었으면 앞 갈고리의 버림은 이 집합의 것이 아니다."""
        return self.j.stats["집합을 백업으로 되돌림"], self.j.stats["구간을 새로 제안"]

    def still_closed(self, seed, i, ns, gone, where):
        """⑨ 앞에서 버린 묘비가 그대로 닫혀 있다: 되찾지 않고, lost로 돌아오지 않고, 버린 기록이 사라지지 않는다."""
        tombs = ns.get("tombstones") or {}
        lost = {t for n in ns["nodes"] for t in n.get("lost") or []}
        shut = idmap.discarded_tombs(ns)
        for t in gone:
            if (tombs.get(t) or {}).get("found") is not None:
                self.j.note("⑨ 버린 묘비를 되찾음(%s)" % where, (seed, i, t))
            if t in lost:
                self.j.note("⑨ 버린 묘비가 lost로 돌아옴(%s)" % where, (seed, i, t))
            if t not in shut:
                self.j.note("⑨ 버린 기록이 사라짐(%s)" % where, (seed, i, t))
            self.j.stats["버린 묘비 닫힘 점검"] += 1

    def edit_after(self, seed, i, r, ns, truth):
        """버린 구간을 병합·나누기·삭제한다(사람). AI는 확인 없이 지우지 못한다(⑫). 고친 집합 또는 None."""
        held = [n for n in ns["nodes"] if n.get("discarded") and sn.node_state(n) == "applied"]
        if not held or r.random() < 0.4:
            return None
        n = r.choice(held)
        pg = {"nodes": [{"entity_id": e} for e in truth.eid]}
        others = [m for m in ns["nodes"] if m is not n and sn.node_state(m) == "applied"]
        kind = r.choice(["merge", "split", "remove"])
        if kind == "merge" and others:
            ops = [{"op": "merge", "node_ids": [n["node_id"], r.choice(others)["node_id"]][::r.choice([1, -1])]}]
        elif kind == "split" and len(n["members"]) >= 2:
            ops = [{"op": "split", "node_id": n["node_id"], "members": [r.choice(n["members"])]}]
        else:
            kind, ops = "remove", [{"op": "remove", "node_id": n["node_id"]}]
        as_ai = copy.deepcopy(ns)  # AI가 만든 구간이어도(그래서 사람 확인 규칙에 걸리지 않아도) 버린 묘비가 있으면 막힌다
        for m in as_ai["nodes"]:
            m["origin"] = "ai"
        try:
            node_tools.apply_nodes(as_ai, {"cells": []}, pg, ops, {}, "ai", ns["set_rev"], at=STAMP % i)
            self.j.note("⑫ AI가 확인 없이 버린 구간을 고침", (seed, i, kind))
        except node_tools.Refused:
            self.j.stats["AI의 버린 구간 고치기를 거절함"] += 1
        try:
            out, _res, _bid = node_tools.apply_nodes(ns, {"cells": []}, pg, ops, {}, "user", ns["set_rev"], at=STAMP % i)
        except node_tools.Refused:
            return None
        self.j.stats["버린 뒤 " + kind] += 1
        return out

    def __call__(self, seed, i, ns, track, truth):
        gone, marks = self.gone.get(seed, (set(), None))
        if marks == self.marks():
            self.still_closed(seed, i, ns, gone, "판 이전 뒤")
        r = random.Random(seed * 7919 + i)
        open_nodes = [n for n in ns["nodes"] if n.get("lost") and sn.node_state(n) == "applied"]
        if open_nodes and r.random() < 0.6:
            n = r.choice(open_nodes)
            lost = list(n["lost"])
            pick = None if r.random() < 0.3 else r.sample(lost, r.randint(1, len(lost)))
            out = sn.discard_lost(ns, n["node_id"], pick, by="퍼즈", at=STAMP % i)
            if sn.discard_lost(out, n["node_id"], pick, by="퍼즈", at=STAMP % i) is not out:
                self.j.note("⑪ 같은 버리기를 두 번 하면 다름", (seed, i))
            check = idmap.needs_check(out)
            want = {m["node_id"]: len(m["lost"]) for m in out["nodes"] if m.get("lost")}
            if check["lost_members"] != want:
                self.j.note("⑩ 찾지 못한 구성요소 수가 남은 lost와 다름", (seed, i, check["lost_members"], want))
            gone = idmap.discarded_tombs(out)
            opened = sum(1 for t, rec in out["tombstones"].items() if rec.get("found") is None and t not in gone)
            if check["tombstones"] != opened:
                self.j.note("⑩ 되찾지 못한 묘비 수에 버린 묘비가 듦", (seed, i))
            self.j.stats["사람이 버린 묘비"] += len(pick or lost)
            self.j.stats["버리기 전부" if pick is None else "버리기 일부"] += 1
            track.adopt_set(out, truth)
            ns = out
        tombs = ns.get("tombstones") or {}  # 겹친 구간의 열린 쪽으로 먼저 되찾은 묘비는 버린 묘비가 아니었다
        shut = {t for t in idmap.discarded_tombs(ns) if (tombs.get(t) or {}).get("found") is None}
        out = self.edit_after(seed, i, r, ns, truth)
        if out is not None:
            self.still_closed(seed, i, out, shut, "병합·나누기·삭제 뒤")
            track.sets = {}  # 구간 수·차례가 바뀌어 자리를 새로 잡는다(퍼즈가 집합을 바꿀 때와 같음)
            track.adopt_set(out, truth)
            ns = out
        self.gone[seed] = (shut, self.marks())
        return ns


class DiscardFuzzTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_invariants_hold_when_people_discard_tombs_between_reextractions(self):
        judge = fz.Judge()
        fz.run(range(fz.SEEDS), judge, Discarder(judge))
        s = judge.stats
        for k in ("사람이 버린 묘비", "버리기 전부", "버리기 일부", "버린 묘비 닫힘 점검", "되돌림", "버린 뒤 merge",
                  "버린 뒤 split", "버린 뒤 remove", "AI의 버린 구간 고치기를 거절함"):
            self.assertGreater(s[k], fz.SEEDS // 20, k)
        bad = {k: v for k, v in s.items() if k[0] in "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"}
        self.assertEqual(bad, {}, fz.report(judge))


if __name__ == "__main__":
    j = fz.Judge()
    print(fz.report(fz.run(range(int(sys.argv[1]) if len(sys.argv) > 1 else fz.SEEDS), j, Discarder(j))))
