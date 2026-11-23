"""② AI split 후보 수락·결정·되돌리기(입력 연산 U2). 합성 1쪽(tests.test_corrections_inputs의 맞닿은 밸브 셋 덩어리)에
AI split 후보 셋을 두고 수락이 split 입력 연산으로 들어가 다시 추출로 살아남는지 본다. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다.
근거: docs/units/2026-11-13-drawing-knowledge/evidence/fix-input-ops-design.md §8 U2."""

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
from hazop.extract import ai_review, ai_split, corrections  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
from tests.test_corrections_inputs import BLOB, GROUPS, HAS_PDFPLUMBER, page  # noqa: E402

NAME = "SYN-1"
BY = "김검토"
AT = "2026-11-23T00:00:00Z"


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 필요")
class SplitAcceptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp
        self.pdf = os.path.join(self.tmp, "syn.pdf")
        with pdf_vector._cache_lock:
            pdf_vector._cache.clear()
        with open(self.pdf, "wb") as fh:
            fh.write(page())
        self.original = pdf_vector.extract(self.pdf, page=0, repo_root=self.tmp)
        out = os.path.join(paths.output_root("extract"), NAME)
        os.makedirs(out)
        with open(os.path.join(out, "extraction.json"), "w", encoding="utf-8") as fh:
            json.dump(self.original, fh, ensure_ascii=False)
        blob = next(n for n in self.original["nodes"] if n["source_object_id"] == BLOB)
        members = pdf_vector.member_shapes(self.pdf, 0)
        doc = ai_review.new_doc(NAME, self.original)
        for g in GROUPS:
            doc["candidates"].append(self.candidate(blob, g, members))
        ai_review.save_doc(doc)
        self.cands = [c["cand_id"] for c in doc["candidates"]]

    def tearDown(self):
        if self._old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self._old
        shutil.rmtree(self.tmp)

    @staticmethod
    def candidate(blob, g, members):
        box = ai_split._union([members[p][0] for p in g])
        item = {"target": blob["source_object_id"], "local_id": blob["local_id"], "bbox": box}
        return ai_review.make_candidate(
            ai_split.item_id(blob, g), "split", item, "split", ["manual_valve"], 0.9, "범례 수동 밸브",
            {"match": "legend", "pdf_objects": list(g), "new_bbox": box, "ai_box": box, "node_bbox": ai_split._box(blob)})

    def accept(self, ids):
        doc = ai_review.load_doc(NAME)
        failed = ai_review.accept(doc, ids, self.original, NAME, by=BY, at=AT)
        self.assertEqual(failed, [])

    def revert(self, ids):
        return ai_review.revert(ai_review.load_doc(NAME), ids, NAME, by=BY, at=AT)

    def ops(self):
        return (corrections.load(NAME) or {}).get("ops") or []

    def test_accepted_split_takes_the_pipe_end_off_the_lump(self):
        self.accept(self.cands[:1])
        self.assertEqual([o["op"] for o in self.ops()], ["split"], "AI split 수락은 split 입력 연산으로 들어간다")
        corrected = corrections.resolve(NAME, allow_extract=True)["corrected"]
        new = [n for n in corrected["nodes"]
               if tuple(sorted((n.get("evidence") or {}).get("pdf_objects") or ())) == tuple(GROUPS[0])]
        ends = {e.get("node_local_id") for r in corrected["relations"] for e in r.get("endpoints") or []}
        self.assertEqual(len(new), 1, "나눈 개체가 새 기호 하나가 된다")
        self.assertEqual(new[0]["kind"], "manual_valve")
        self.assertIn(new[0]["local_id"], ends, "왼쪽 배관 끝이 덩어리에서 새 기호로 옮겨진다")

    def test_one_acceptance_keeps_the_rest_of_the_lump_askable(self):
        self.accept(self.cands[:1])
        self.assertNotIn(BLOB, ai_review.decided_targets(NAME), "남은 후보가 제안 상태면 덩어리는 다시 물을 수 있다")

    def test_one_rejection_keeps_the_rest_of_the_lump_askable(self):
        ai_review.reject(ai_review.load_doc(NAME), self.cands[:1], by=BY, at=AT)
        self.assertNotIn(BLOB, ai_review.decided_targets(NAME), "후보 하나를 거절해도 덩어리 전체를 닫지 않는다")

    def test_accepting_two_at_once_is_one_step_back_to_the_original(self):
        self.accept(self.cands[:2])
        log = corrections.load(NAME)["log"]
        self.assertEqual([e["added"] for e in log], [[o["op_id"] for o in self.ops()]], "함께 수락한 둘은 기록 한 줄")
        self.revert(self.cands[:2])
        log = corrections.load(NAME)["log"]
        self.assertEqual(self.ops(), [])
        self.assertEqual(len(log), 2, "되돌리기도 한 줄")
        got = corrections.resolve(NAME, allow_extract=True)
        self.assertEqual(json.dumps(got["corrected"], sort_keys=True), json.dumps(self.original, sort_keys=True),
                         "되돌리면 원본 추출 그대로")

    def test_reverting_an_acceptance_takes_the_dependent_human_edit_with_it(self):
        self.accept(self.cands[:1])
        ops = self.ops()
        made = corrections.resolve(NAME, allow_extract=True)
        target = "pdf-p0-split-" + ops[0]["op_id"]
        self.assertIn(target, {n["source_object_id"] for n in made["base"]["nodes"]})
        tag = corrections.make_op(made["base"], "set_tag", target, {"tag": "V-101"}, BY, at=AT, existing_ops=ops, name=NAME)
        corrections.save(NAME, ops + [tag], BY, at=AT)
        self.revert(self.cands[:1])
        self.assertEqual(self.ops(), [], "수락을 되돌리면 그 기호에 기댄 사람 고침도 함께 빠진다")

    def test_accept_then_revert_then_accept_restores_the_same_split(self):
        self.accept(self.cands[:1])
        first = copy.deepcopy(self.ops())
        self.revert(self.cands[:1])
        self.accept(self.cands[:1])
        self.assertEqual(self.ops(), first, "다시 수락하면 지운 연산을 그대로 되살린다(나눈 기호 id가 같다)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
