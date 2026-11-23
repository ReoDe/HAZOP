"""판 이전을 빠르게 한 것이 결과를 바꾸지 않는지 본다(2026-11-24 성능 단위).

- 표시 색인(idmap._MarkIndex): 같은 표시(_same_mark) 찾기를 격자 칸으로 좁혔다. 전수 비교(이 파일의 LinearIndex, 고치기 전
  compute의 by_look·mark_hits 그대로)와 찾은 것과 차례가 같아야 하고, compute가 만든 표가 바이트 하나 다르지 않아야 한다.
  경계: 허용치와 정확히 같은 거리, 음수 좌표, 다른 도면, 상자 없음, 격자로 나눌 수 없는 좌표(무한·NaN·아주 큰 정수).
"""

import json
import random
import unittest
from unittest import mock

from hazop.study import idmap


class LinearIndex:
    """고치기 전 compute의 표시 찾기: 겉모습(앞 넷)의 json으로 묶고 그 안을 전수 비교."""

    def __init__(self, rows):
        self.by_look = {}
        for m, e in rows:
            self.by_look.setdefault(json.dumps(m[:4]), []).append((m, e))

    def hits(self, mark):
        return [e for m, e in self.by_look.get(json.dumps(mark[:4]), ()) if idmap._same_mark(mark, m)]


def dumps(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True).encode("utf-8")


ODD = [float("inf"), float("-inf"), float("nan"), 10 ** 400, -(10 ** 400), 2 ** 60, 2 ** 60 + 1]
STEPS = [0, 0.5, -0.5, 1.0, -1.0, 0.95, -0.95, 1.05, -1.05, 2.0, -2.0, 3.0]


def random_marks(rnd, n):
    out = []
    for _ in range(n):
        x, y = rnd.choice([-3.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 99.5, 100.0]) + rnd.choice(STEPS), rnd.choice([-2.0, 0.0, 1.0, 50.0])
        w, h = rnd.choice([0, 1.0, 2.0, 20.0]), rnd.choice([0, 1.0, 10.0])
        m = [rnd.choice(["drawing_object", None]), rnd.choice(["s1", "s2", None]), rnd.choice(["valve", None]),
             rnd.choice([None, "V-1"]), x, y, x + w, y + h]
        if rnd.random() < 0.1:
            m[4], m[5] = int(m[4]), int(m[5])
        if rnd.random() < 0.05:
            m[4 + rnd.randrange(4)] = rnd.choice(ODD)
        out.append(m)
    return out


def answer(index, q):
    """찾은 것, 또는 비교가 던진 오류의 이름(아주 큰 정수와 float의 뺄셈은 전수 비교에서도 OverflowError)."""
    try:
        return index.hits(q)
    except OverflowError as exc:
        return type(exc).__name__


class MarkIndexTest(unittest.TestCase):
    def check(self, rows, queries):
        fast, slow = idmap._MarkIndex(rows), LinearIndex(rows)
        for q in queries:
            self.assertEqual(answer(fast, q), answer(slow, q), q)

    def test_boundaries(self):
        base = ["drawing_object", "s1", "valve", None]
        rows = [(base + [0.0, 0.0, 10.0, 10.0], "a"), (base + [1.0, 1.0, 11.0, 11.0], "b"), (base + [-1.0, -1.0, 9.0, 9.0], "c"),
                (base + [2.0, 0.0, 12.0, 10.0], "d"), (base[:1] + ["s2"] + base[2:] + [0.0, 0.0, 10.0, 10.0], "e"),
                (base + [float("inf"), 0.0, 10.0, 10.0], "f"), (base + [10 ** 400, 0.0, 10.0, 10.0], "g"), (base + [2 ** 60, 0.0, 10.0, 10.0], "i"),
                (base + [-0.05, -0.95, 9.95, 9.05], "h")]
        queries = [m for m, _ in rows] + [base + [0.0, 0.0, 10.0, 10.0], base + [-1.0, 0.0, 9.0, 10.0],
                                         base + [1.0, -1.0, 11.0, 9.0], base + [float("nan"), 0, 10, 10], base + [2 ** 60 + 1, 0.0, 10.0, 10.0]]
        self.check(rows, queries)
        tame = [r for r in rows if r[1] != "g"]
        self.assertEqual(idmap._MarkIndex(tame).hits(base + [0.0, 0.0, 10.0, 10.0]), ["a", "b", "c", "h"],
                         "허용치와 정확히 같은 거리(1.0)는 같은 자리, 음수 좌표도 찾는다")
        self.assertEqual(answer(idmap._MarkIndex(rows), base + [0.0, 0.0, 10.0, 10.0]), "OverflowError", "전수 비교처럼 던진다")
        big = [(base + [2 ** 60 + 128, 0.0, 10.0, 10.0], "j")]
        self.assertEqual(idmap._MarkIndex(big).hits(base + [2 ** 60 + 129, 0.0, 10.0, 10.0]), ["j"],
                         "float로 나누면 반올림이 갈라 놓는 큰 정수도 1 차이면 같은 자리")
        self.assertEqual(idmap._MarkIndex(tame).hits(base + [2 ** 60 + 1, 0, 10, 10]), ["i"], "격자로 못 나누는 좌표도 전수 비교처럼")

    def test_random_marks_find_the_same_hits_in_the_same_order(self):
        for seed in range(60):
            rnd = random.Random(seed)
            marks = random_marks(rnd, 120)
            rows = [(m, "e%d" % i) for i, m in enumerate(marks)]
            queries = marks + random_marks(rnd, 60) + [m[:4] + [v + rnd.choice(STEPS) for v in m[4:]] for m in marks
                                                       if all(isinstance(v, float) and v == v and abs(v) < 1e9 for v in m[4:])]
            self.check(rows, queries)


def world(rnd, version, n, prev=None):
    """도면 하나(시트 둘)의 그래프. prev가 있으면 그 기호를 흔들어(자리 0~3pt, 순번 다시 매김, 지우기·더하기) 다음 판을 만든다."""
    if prev is None:
        syms = [{"kind": rnd.choice(["valve", "pump", None]), "tag": rnd.choice([None, "V-1", "P-2"]), "sheet": rnd.choice(["s1", "s2"]),
                 "box": [rnd.choice([-20.0, -1.0, 0.0, 1.0, 40.0]) + rnd.choice(STEPS), rnd.choice([-5.0, 0.0, 30.0]), 20.0, 10.0]}
                for _ in range(n)]
    else:
        syms = []
        for s in prev:
            if rnd.random() < 0.1:
                continue
            b = list(s["box"])
            b[0] += rnd.choice(STEPS)
            b[1] += rnd.choice([0.0, 0.0, 1.0, -1.0, 1.05])
            syms.append(dict(s, box=b))
        syms += world(rnd, version, rnd.randrange(4))["syms"]
        rnd.shuffle(syms)
    nodes = []
    for i, s in enumerate(syms):
        nodes.append({"entity_id": "graph-T/entity-node-%03d" % (i + 1), "source_object_id": "pdf-p0-sym-%04d" % (i + 1),
                      "node_type": "drawing_object", "kind": s["kind"], "tag": s["tag"], "sheet": s["sheet"],
                      "bbox": None if rnd.random() < 0.05 else s["box"], "id_basis": "sequence"})
    return {"graph_id": "graph-T", "graph_version": version, "nodes": nodes, "edges": [], "syms": syms}


def chain(seed):
    """옛 판 사진(묘비 포함)과 새 그래프. 첫 판 이전의 묘비를 둘째 판 이전이 되찾을 수 있게 세 판을 잇는다."""
    rnd = random.Random(seed)
    g0 = world(rnd, "v-0", rnd.randrange(10, 60))
    g1 = world(rnd, "v-1", 0, g0["syms"])
    g2 = world(rnd, "v-2", 0, g1["syms"] + (g0["syms"][:3] if rnd.random() < 0.5 else []))
    ns0 = dict(idmap.snapshot(g0), graph_id="graph-T", graph_version="v-0", nodes=[])
    t1 = idmap.compute(ns0, g1, at="2026-11-24T00:00:00Z")
    ns1 = dict(idmap.snapshot(g1), graph_id="graph-T", graph_version="v-1", nodes=[], tombstones=t1["new_tombs"])
    return ns0, g1, ns1, g2


class SameTableTest(unittest.TestCase):
    """색인을 바꿔 끼워도 compute 표가 바이트로 같다(고치기 전 찾기 = LinearIndex)."""

    def test_compute_table_is_byte_identical_with_the_linear_search(self):
        found = linked = 0
        for seed in range(150):
            ns0, g1, ns1, g2 = chain(seed)
            for ns, g in ((ns0, g1), (ns1, g2)):
                fast = idmap.compute(ns, g, at="x")
                with mock.patch.object(idmap, "_MarkIndex", LinearIndex):
                    slow = idmap.compute(ns, g, at="x")
                self.assertEqual(dumps(fast), dumps(slow), "seed %d" % seed)
                found += len(fast["found"])
                linked += sum(1 for v in fast["eid"].values() if not idmap.is_tomb(v))
        self.assertGreater(found, 20, "묘비 되찾기 길도 실제로 돈다")
        self.assertGreater(linked, 1000, "표시로 잇기가 실제로 돈다")


if __name__ == "__main__":
    unittest.main()
