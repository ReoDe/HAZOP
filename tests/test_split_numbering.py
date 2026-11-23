"""나누기로 다시 지은 기준 추출의 sym 번호와, 그 번호로 판 이전이 잇는 범위(2026-11-24).

- 기준 추출: 조각을 떼인 덩어리의 몸체는 덩어리 번호를 잇고 다른 기호는 제 번호를 지킨다(pdf_vector._sym_numbers).
  원본 추출과 지금 분석이 기호마다 같은 개체일 때만 '원본과 같은 뜻의 번호'다(corrections._numbering, build.numbering).
- 판 이전: 옛 사진과 새 그래프의 번호 기준(원본의 기준 판·끝 번호)이 같은 시트의 sym-n(n <= 끝 번호)만 기준 판이 달라도
  참조로 잇는다. 다른 원본, 끝 번호 뒤 번호, 자료가 바뀐 시트, 이음점·배관 순번은 전처럼 표시로만 잇는다(엉뚱한 기호로 잇지 않음).
"""

import copy
import os
import shutil
import tempfile
import unittest

from tests.test_corrections_inputs import BLOB, GROUPS, HAS_PDFPLUMBER, evidence, page

from hazop import paths
from hazop.extract import corrections
from hazop.extract.adapters import pdf_vector
from hazop.graph import build
from hazop.study import idmap

AT = "2026-11-24T00:00:00Z"
LUMP, BODY, FAR = [100, 145, 60, 10], [120, 145, 40, 10], [300, 145, 20, 10]
N1 = {"base": "b-orig1", "upto": 3}


def graph(version, base, nodes, numbering=None, material="m-1"):
    return {"graph_id": "graph-T", "graph_version": version, "source": {"material_id": material}, "edges": [],
            "base_version": base, **({"numbering": numbering} if numbering else {}),
            "nodes": [{"entity_id": e, "source_object_id": soid, "bbox": box, "node_type": "drawing_object", "kind": None,
                       "tag": None, "id_basis": "sequence"} for e, soid, box in nodes]}


def landed(old, new, drop=()):
    """옛 그래프의 판 사진에서 새 그래프로 간 곳 {옛 entity_id: 새 entity_id 또는 None(묘비)}."""
    ns = dict(idmap.snapshot(old), graph_id=old["graph_id"], graph_version=old["graph_version"], nodes=[])
    for k in drop:
        ns.pop(k)
    eid = idmap.compute(ns, new)["eid"]
    return {m: (None if idmap.is_tomb(v) else v) for m, v in eid.items()}


class NumberingLinkTest(unittest.TestCase):
    """idmap.compute만 본다. 옛 판은 원본 그대로(기준 판 = 원본의 기준 판), 새 판은 나누기로 기준 판이 바뀐 것이다."""

    def setUp(self):
        self.old = graph("v-1", "b-orig1", [("e1", "pdf-p0-sym-0001", LUMP), ("e2", "pdf-p0-sym-0002", FAR)], N1)

    def test_same_numbering_links_the_shrunk_body_by_its_number(self):
        new = graph("v-2", "b-split", [("e1", "pdf-p0-sym-0001", BODY), ("e2", "pdf-p0-sym-0002", FAR)], N1)
        self.assertEqual(landed(self.old, new), {"e1": "e1", "e2": "e2"})

    def test_without_proof_the_shrunk_body_is_lost(self):
        new = graph("v-2", "b-split", [("e1", "pdf-p0-sym-0001", BODY), ("e2", "pdf-p0-sym-0002", FAR)])
        self.assertEqual(landed(self.old, new), {"e1": None, "e2": "e2"}, "번호 기준이 없는 새 그래프는 표시로만 잇는다")

    def test_old_snapshot_without_numbering_links_only_when_it_was_the_original(self):
        new = graph("v-2", "b-split", [("e1", "pdf-p0-sym-0001", BODY), ("e2", "pdf-p0-sym-0002", FAR)], N1)
        self.assertEqual(landed(self.old, new, drop=["graph_member_numbering"])["e1"], "e1", "옛 기준 판이 원본의 기준 판")
        split_before = dict(self.old, base_version="b-other-split")
        self.assertIsNone(landed(split_before, new, drop=["graph_member_numbering"])["e1"],
                          "번호 기준을 남기기 전 다른 나누기 기준 추출의 사진은 증명이 없다")

    def test_another_original_with_the_same_number_is_not_linked(self):
        other = graph("v-2", "b-reex", [("e1", "pdf-p0-sym-0001", [200, 145, 20, 10]), ("e2", "pdf-p0-sym-0002", FAR)],
                      {"base": "b-orig2", "upto": 3})
        self.assertEqual(landed(self.old, other)["e1"], None, "다시 추출한 원본의 sym-0001은 다른 기호일 수 있다")

    def test_number_after_the_original_end_is_not_linked_by_number(self):
        old = graph("v-1", "b-split1", [("e1", "pdf-p0-sym-0001", BODY), ("e4", "pdf-p0-sym-0004", [10, 10, 5, 5])], N1)
        new = graph("v-2", "b-split2", [("e1", "pdf-p0-sym-0001", BODY), ("e4", "pdf-p0-sym-0004", [50, 50, 5, 5])], N1)
        self.assertEqual(landed(old, new), {"e1": "e1", "e4": None}, "끝 번호 뒤 번호는 나누기 기준 추출마다 다른 기호다")

    def test_sheet_with_another_material_is_not_linked_by_number(self):
        new = graph("v-2", "b-split", [("e1", "pdf-p0-sym-0001", BODY), ("e2", "pdf-p0-sym-0002", FAR)], N1, material="m-2")
        self.assertEqual(landed(self.old, new)["e1"], None)

    def test_junction_numbers_are_not_linked_by_number(self):
        old = graph("v-1", "b-orig1", [("e1", "pdf-p0-junction-0001", [10, 10, 2, 2])], N1)
        new = graph("v-2", "b-split", [("e1", "pdf-p0-junction-0001", [90, 90, 2, 2])], N1)
        self.assertEqual(landed(old, new), {"e1": None}, "이음점 순번은 나누기로 사슬을 다시 지으면 밀린다")

    def test_symbol_that_lost_its_number_is_still_linked_by_mark(self):
        new = graph("v-2", "b-split", [("e1", "pdf-p0-sym-0001", BODY), ("e5", "pdf-p0-sym-0005", FAR)], N1)
        self.assertEqual(landed(self.old, new), {"e1": "e1", "e2": "e5"},
                         "뒷 단계에서 개체가 바뀌어 끝 번호 뒤 번호를 받은 기호도 표시가 같으면 전처럼 잇는다")

    def test_mark_fallback_does_not_take_a_symbol_proven_by_number(self):
        new = graph("v-2", "b-split", [("e2", "pdf-p0-sym-0002", LUMP)], N1)
        self.assertEqual(landed(self.old, new), {"e1": None, "e2": "e2"},
                         "번호로 증명된 기호를 표시가 같은 다른 옛 기호가 잡지 않는다")

    def test_mark_fallback_keeps_the_two_into_one_guard(self):
        old = graph("v-1", "b-orig1", [("e1", "pdf-p0-sym-0001", LUMP), ("e2", "pdf-p0-sym-0002", LUMP)], N1)
        new = graph("v-2", "b-split", [("e9", "pdf-p0-sym-0009", LUMP)], N1)
        self.assertEqual(landed(old, new), {"e1": None, "e2": None}, "옛 기호 둘이 표시로 새 기호 하나에 모이면 둘 다 묘비")


class SplitIdKeepsItsPieceTest(unittest.TestCase):
    """나눈 id(pdf-p<쪽>-split-<op_id>)는 연산 하나가 만든 조각 하나이고 개체도 연산에 고정이다. op_id는 다시 쓰지 않는다
    (corrections.issued_op_ids). 그래서 같은 나눈 id는 같은 조각이고, 종류만 바뀐 것(분류 규칙 변경·set_kind)은 같은 기호로 잇는다
    (판 이전 퍼즈 시드 248, 2026-11-24 검토 판정)."""

    def test_split_id_returning_with_another_kind_is_the_same_piece(self):
        old = graph("v-1", "b-1", [("e1", "pdf-p0-split-c-0003", BODY)])
        new = graph("v-2", "b-2", [("e1", "pdf-p0-split-c-0003", BODY)])
        for g, kind in ((old, "manual_valve"), (new, "pump")):
            g["nodes"][0].update(kind=kind, id_basis="source")
        self.assertEqual(landed(old, new), {"e1": "e1"})


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 필요")
class NumberingFromExtractionTest(unittest.TestCase):
    """합성 1쪽 PDF(맞닿은 밸브 셋이 한 덩어리)를 실제로 추출하고 기준 추출을 짓는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp
        self.original = self.extract("syn.pdf", page())

    def tearDown(self):
        if self._old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self._old
        shutil.rmtree(self.tmp)

    def extract(self, name, data):
        with pdf_vector._cache_lock:
            pdf_vector._cache.clear()
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return pdf_vector.extract(path, page=0, repo_root=self.tmp)

    def split(self, original, groups):
        ops = []
        for g in groups:
            ops.append(corrections.make_op(original, "split", BLOB, corrections.input_value(original, g), "김고침", at=AT,
                                           existing_ops=ops))
        base, status = corrections.build_base(original, ops)
        return {"original": original, "base": base, "inputs": {"numbering": status["numbering"]}}

    def test_body_keeps_the_lump_number_and_the_others_keep_theirs(self):
        got = self.split(self.original, GROUPS[:1])
        before, after = evidence(self.original), evidence(got["base"])
        self.assertEqual(after[BLOB], tuple(GROUPS[1] + GROUPS[2]), "몸체가 덩어리 번호를 잇는다")
        for sid in ("pdf-p0-sym-0002", "pdf-p0-sym-0003"):
            self.assertEqual(after[sid], before[sid])
        self.assertTrue(got["inputs"]["numbering"])
        plain = {"original": self.original, "base": self.original, "inputs": {}}
        self.assertEqual(build.numbering(got), build.numbering(plain), "원본 그대로인 판과 번호 기준이 같다")
        self.assertEqual(build.numbering(plain), {"base": build.base_version(self.original), "upto": 3})

    def test_whole_lump_split_frees_the_lump_number(self):
        got = self.split(self.original, GROUPS)
        self.assertNotIn(BLOB, evidence(got["base"]), "몸체가 남지 않은 덩어리 번호는 아무도 받지 않는다")

    def test_original_read_differently_gives_no_numbering_proof(self):
        drifted = copy.deepcopy(self.original)
        n2 = next(n for n in drifted["nodes"] if n["source_object_id"] == "pdf-p0-sym-0002")
        n2["evidence"]["pdf_objects"] = ["pdf-path-0011", "pdf-path-0012"]   # 다른 읽기 판이 개체 번호를 하나 밀었을 때
        got = self.split(drifted, GROUPS[:1])
        self.assertFalse(got["inputs"]["numbering"])
        self.assertIsNone(build.numbering(got), "원본과 지금 분석이 다르면 번호로 잇는 근거를 주지 않는다")

    def test_reextracted_drawing_where_the_same_number_is_another_symbol_is_not_linked_by_number(self):
        moved = self.extract("syn2.pdf", page(extra_line=True))
        lump = "pdf-p0-sym-0002"
        self.assertEqual(evidence(moved)[lump], tuple("pdf-path-%04d" % k for k in range(5, 11)),
                         "시험 전제: 먼 곳의 선 하나가 sym-0001을 받아 덩어리가 sym-0002, 원본의 sym-0002 밸브는 sym-0003")
        a = self.split(self.original, GROUPS[:1])
        ops = [corrections.make_op(moved, "split", lump, corrections.input_value(moved, ["pdf-path-0005", "pdf-path-0006"]),
                                   "김고침", at=AT)]
        base, status = corrections.build_base(moved, ops)
        b = {"original": moved, "base": base, "inputs": {"numbering": status["numbering"]}}
        g1, g2 = (dict(build.build_graph(x["base"], graph_id="graph-T"), base_version=build.base_version(x["base"]),
                       numbering=build.numbering(x)) for x in (a, b))
        self.assertTrue(g1["numbering"] and g2["numbering"])
        self.assertNotEqual(g1["numbering"]["base"], g2["numbering"]["base"], "다시 추출한 원본은 번호 기준이 다르다")
        at = {n["source_object_id"]: n["entity_id"] for n in g2["nodes"]}
        old = next(n["entity_id"] for n in g1["nodes"] if n["source_object_id"] == "pdf-p0-sym-0002")
        self.assertEqual(landed(g1, g2)[old], at["pdf-p0-sym-0003"], "원본의 sym-0002 밸브는 같은 자리 밸브로 가고 같은 번호의 덩어리로 가지 않는다")


if __name__ == "__main__":
    unittest.main()
