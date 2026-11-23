"""판 이전 퍼즈(tests.test_study_migrate_fuzz)에 사람이 묘비를 버리는 일(nodes.discard_lost)을 섞은 것. 실행:
python -m unittest tests.test_study_discard_fuzz (시드 수는 HAZOP_FUZZ_SEEDS)

판 이전마다 적용됨 구간 가운데 묘비가 남은 것을 골라 하나·여럿·전부를 버린다. 퍼즈의 불변식 ①~⑧을 그대로 보되 버린
묘비는 '사람이 버림'으로 세어 사라짐이 아니다(①). 더 보는 것.
⑨ 버린 묘비는 되찾지 않는다(다음 판 이전에서 found가 차지 않고 구간 members로 돌아오지 않음).
⑩ 버린 뒤 needs_check의 lost_members는 남은 lost 수와 같고, 버린 묘비는 되찾지 못한 묘비 수에 들지 않는다.
⑪ 같은 버리기를 두 번 하면 같다(두 번째는 받은 집합 그대로).
"""

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
from hazop.study import idmap  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from tests import test_study_migrate_fuzz as fz  # noqa: E402


class Discarder:
    """판 이전마다 묘비를 버리는 갈고리. 퍼즈의 난수(r)를 쓰지 않아 사슬은 퍼즈 그대로다."""

    def __init__(self, judge):
        self.j = judge
        self.gone = {}  # 시드 → 앞 갈고리 뒤 버렸고 되찾지 않은 묘비

    def __call__(self, seed, i, ns, track, truth):
        gone_before = self.gone.get(seed, set()) & idmap.discarded_tombs(ns)
        for t in gone_before:
            if (ns.get("tombstones") or {}).get(t, {}).get("found") is not None:
                self.j.note("⑨ 버린 묘비를 되찾음", (seed, i, t))
            if any(t in (n.get("lost") or []) for n in ns["nodes"]):
                self.j.note("⑨ 버린 묘비가 lost로 돌아옴", (seed, i, t))
        r = random.Random(seed * 7919 + i)
        open_nodes = [n for n in ns["nodes"] if n.get("lost") and sn.node_state(n) == "applied"]
        if open_nodes and r.random() < 0.6:
            n = r.choice(open_nodes)
            lost = list(n["lost"])
            pick = None if r.random() < 0.3 else r.sample(lost, r.randint(1, len(lost)))
            out = sn.discard_lost(ns, n["node_id"], pick, by="퍼즈", at="d%02d" % i)
            if sn.discard_lost(out, n["node_id"], pick, by="퍼즈", at="d%02d" % i) is not out:
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
        self.gone[seed] = {t for t in idmap.discarded_tombs(ns) if (tombs.get(t) or {}).get("found") is None}
        if gone_before:
            self.j.stats["버린 묘비 되찾기 점검"] += len(gone_before)
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
        for k in ("사람이 버린 묘비", "버리기 전부", "버리기 일부", "버린 묘비 되찾기 점검", "되돌림"):
            self.assertGreater(s[k], fz.SEEDS // 20, k)
        bad = {k: v for k, v in s.items() if k[0] in "①②③④⑤⑥⑦⑧⑨⑩⑪"}
        self.assertEqual(bad, {}, fz.report(judge))


if __name__ == "__main__":
    j = fz.Judge()
    print(fz.report(fz.run(range(int(sys.argv[1]) if len(sys.argv) > 1 else fz.SEEDS), j, Discarder(j))))
