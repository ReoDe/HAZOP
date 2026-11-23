"""② AI split 후보 수락·결정·되돌리기(입력 연산 U2). 합성 1쪽(tests.test_corrections_inputs의 맞닿은 밸브 셋 덩어리)에
AI split 후보 셋을 두고 수락이 split 입력 연산으로 들어가 다시 추출로 살아남는지 본다. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다.
근거: docs/units/2026-11-13-drawing-knowledge/evidence/fix-input-ops-design.md §8 U2."""

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import ai_review, ai_split, corrections  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
from tests import test_screen_words  # noqa: E402
from tests.test_corrections_inputs import BLOB, GROUPS, HAS_PDFPLUMBER, page  # noqa: E402

NAME = "SYN-1"
BY = "김검토"
AT = "2026-11-23T00:00:00Z"


def data_load(name):
    from hazop.app import data
    return data.load_extraction(name)


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

    def revert(self, ids, confirm=None):
        return ai_review.revert(ai_review.load_doc(NAME), ids, NAME, by=BY, at=AT, confirm=confirm)

    def ops(self):
        return (corrections.load(NAME) or {}).get("ops") or []

    def test_accepted_split_takes_the_pipe_end_off_the_lump(self):
        self.accept(self.cands[:1])
        self.assertEqual([o["op"] for o in self.ops()], ["split"], "AI split 수락은 split 입력 연산으로 들어간다")
        corrected = corrections.resolve(NAME, allow_extract=True)["corrected"]
        new = [n for n in corrected["nodes"]
               if tuple(sorted((n.get("evidence") or {}).get("pdf_objects") or ())) == tuple(GROUPS[0])]
        ends = {e.get("node_local_id") for r in corrected["relations"] + corrected["unresolved_connectors"]
                for e in r.get("endpoints") or []}  # 왼쪽 배관은 바깥 끝이 열려 있어 미해결 커넥터다
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
        self.revert(self.cands[:1], confirm=[tag["op_id"]])
        self.assertEqual(self.ops(), [], "수락을 되돌리면 그 기호에 기댄 사람 고침도 함께 빠진다(미리 알린 뒤)")

    def test_accept_then_revert_then_accept_restores_the_same_split(self):
        self.accept(self.cands[:1])
        first = copy.deepcopy(self.ops())
        self.revert(self.cands[:1])
        self.accept(self.cands[:1])
        self.assertEqual(self.ops(), first, "다시 수락하면 지운 연산을 그대로 되살린다(나눈 기호 id가 같다)")

    def test_second_acceptance_after_the_lump_was_rebuilt_still_splits(self):
        self.accept(self.cands[:1])
        self.assertEqual(corrections.ensure_base(NAME), "ready")
        self.accept(self.cands[1:2])
        got = corrections.resolve(NAME, allow_extract=True)
        self.assertEqual(got["inputs"]["applied"], [o["op_id"] for o in self.ops()], "덩어리 번호가 바뀐 뒤 수락도 나눈다")
        self.assertEqual(len(got["inputs"]["applied"]), 2)

    def test_split_overlapping_an_earlier_split_is_refused(self):
        self.accept(self.cands[:1])
        doc = ai_review.load_doc(NAME)
        blob = next(n for n in self.original["nodes"] if n["source_object_id"] == BLOB)
        twin = self.candidate(blob, GROUPS[0] + GROUPS[1][:1], pdf_vector.member_shapes(self.pdf, 0))
        doc["candidates"].append(twin)
        ai_review.save_doc(doc)
        failed = ai_review.accept(ai_review.load_doc(NAME), [twin["cand_id"]], self.original, NAME, by=BY, at=AT)
        self.assertEqual([c for c, _ in failed], [twin["cand_id"]])
        self.assertIn("이미 나눈 부분과 겹침", failed[0][1])
        self.assertEqual(len(self.ops()), 1)

    def test_lump_closes_only_when_every_split_candidate_is_decided(self):
        self.accept(self.cands[:2])
        self.assertNotIn(BLOB, ai_review.decided_targets(NAME))
        ai_review.reject(ai_review.load_doc(NAME), self.cands[2:], by=BY, at=AT)
        self.assertIn(BLOB, ai_review.decided_targets(NAME))

    def test_remaining_candidates_go_stale_and_a_new_answer_replaces_them(self):
        self.accept(self.cands[:1])
        doc = ai_review.load_doc(NAME)
        self.assertEqual(ai_review.stale_candidates(doc), set(self.cands[1:]))
        lump = dict(next(n for n in self.original["nodes"] if n["source_object_id"] == BLOB), source_object_id="pdf-p0-sym-0004")
        members = pdf_vector.member_shapes(self.pdf, 0)
        again = [self.candidate(lump, GROUPS[0], members), self.candidate(lump, GROUPS[1] + GROUPS[2], members)]
        ai_review.merge_run(doc, {"candidates": again, "stats": {}})
        kept = [(c["cand_id"], c["status"]) for c in doc["candidates"]]
        self.assertEqual(kept, [(self.cands[0], "accepted"), (again[1]["cand_id"], "proposed")],
                         "정한 묶음은 다시 넣지 않고, 새 답과 겹치는 오래된 제안은 뺀다")

    def test_read_quality_measures_splits_the_way_acceptance_builds_them(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import check_read_quality as rq
        blob = next(n for n in self.original["nodes"] if n["source_object_id"] == BLOB)
        check = {"candidates": [{"node_local_id": blob["local_id"], "field": "split", "values": ["manual_valve"],
                                 "match": "legend", "pdf_objects": GROUPS[0]}]}
        measured = rq.apply_with_splits(self.original, check, self.pdf, self.tmp)
        self.accept(self.cands[:1])
        accepted = corrections.resolve(NAME, allow_extract=True)["corrected"]
        shape = lambda ex: sorted((rq._evidence(n), n["kind"]) for n in ex["nodes"])  # noqa: E731
        self.assertEqual(shape(measured), shape(accepted))
        self.assertEqual(json.dumps(rq.apply_with_splits(self.original, {"candidates": []}, self.pdf, self.tmp), sort_keys=True),
                         json.dumps(rq.apply_candidates(self.original, {"candidates": []}), sort_keys=True),
                         "split 후보가 없으면 예전과 같다")

    def test_sheet_is_not_confirmable_while_a_split_waits(self):
        from hazop.extract import confirmation
        self.accept(self.cands[:1])
        count = lambda: confirmation.sheet_confirmation(NAME)["counts"]["input_waiting"]  # noqa: E731
        self.assertEqual(count(), 1, "반영 전 나누기는 미확인으로 센다")
        corrections.ensure_base(NAME)
        self.assertEqual(count(), 0)
        _, corrected = data_load(NAME)
        self.assertIn("pdf-p0-split-" + self.ops()[0]["op_id"], {n["source_object_id"] for n in corrected["nodes"]},
                      "앱이 읽는 고친 추출도 지어 둔 기준 추출 위다")

    def tag_split(self):
        """수락 하나를 짓고 나눈 기호에 태그를 단 기록. → (split 연산, 태그 연산)."""
        self.accept(self.cands[:1])
        ops = self.ops()
        base = corrections.resolve(NAME, allow_extract=True)["base"]
        tag = corrections.make_op(base, "set_tag", "pdf-p0-split-" + ops[0]["op_id"], {"tag": "V-101"}, BY, at=AT,
                                  existing_ops=ops, name=NAME)
        corrections.save(NAME, ops + [tag], BY, at=AT)
        return ops[0], tag

    def test_built_split_stays_on_screen_while_a_later_acceptance_waits(self):
        self.accept(self.cands[:1])
        self.assertEqual(corrections.ensure_base(NAME), "ready")
        self.accept(self.cands[1:2])
        first, second = self.ops()
        got = corrections.resolve(NAME)
        st = got["inputs"]
        self.assertEqual((st["state"], st["applied"], st["waiting"]), ("partial", [first["op_id"]], [second["op_id"]]))
        self.assertIn("pdf-p0-split-" + first["op_id"], {n["source_object_id"] for n in got["corrected"]["nodes"]},
                      "앞서 지은 나눔은 버리지 않는다")
        shapes = pdf_vector.object_shapes(self.pdf, 0)
        x0, y0 = min(shapes[p][0] for p in GROUPS[1]), min(shapes[p][1] for p in GROUPS[1])
        x1, y1 = max(shapes[p][2] for p in GROUPS[1]), max(shapes[p][3] for p in GROUPS[1])
        self.assertEqual(corrections.pending_inputs(NAME), [
            {"op_id": second["op_id"], "op": "split", "target": BLOB, "kind": "manual_valve",
             "bbox": [x0, y0, round(x1 - x0, 1), round(y1 - y0, 1)], "objects": 2, "candidate": self.cands[1],
             "by": BY, "at": AT}])
        self.assertEqual([(i["op_id"], i["state"], i["code"], i["candidate"]) for i in corrections.input_items(got)],
                         [(second["op_id"], "waiting", "waiting", self.cands[1])])

    def test_edit_on_a_waiting_split_is_waiting_not_failed(self):
        split, tag = self.tag_split()
        os.remove(corrections.base_path(NAME))
        got = corrections.resolve(NAME)
        st, c = got["inputs"], got["corrected"]["corrections"]
        self.assertEqual((st["state"], st["waiting"], st["waiting_on"]), ("pending", [split["op_id"]], {tag["op_id"]: [split["op_id"]]}))
        self.assertEqual(c["not_applicable"], [], "대기 중 나눔에 기댄 고침은 적용 불가로 내지 않는다")
        self.assertEqual(c["waiting_on"], [{"op_id": tag["op_id"], "inputs": [split["op_id"]]}])
        items = corrections.input_items(got)
        self.assertEqual([(i["op_id"], i["state"], i["code"], i["inputs"]) for i in items],
                         [(split["op_id"], "waiting", "waiting", []), (tag["op_id"], "waiting", "waiting_on", [split["op_id"]])])
        for i in items:
            self.assertFalse([w for w in test_screen_words.BANNED + ("op", "pdf", "기준 추출") if w in i["text"]], i["text"])

    def test_reverted_split_does_not_come_back_from_an_older_file(self):
        self.accept(self.cands[:2])
        self.assertEqual(corrections.ensure_base(NAME), "ready")
        self.revert(self.cands[1:2])
        got = corrections.resolve(NAME)
        self.assertEqual(got["inputs"]["state"], "pending", "지운 나눔이 든 파일은 쓰지 않는다")
        self.assertFalse([n for n in got["corrected"]["nodes"] if "-split-" in n["source_object_id"]])

    def test_ready_output_keeps_its_old_shape(self):
        self.accept(self.cands[:1])
        corrected = corrections.resolve(NAME, allow_extract=True)["corrected"]
        self.assertEqual(set(corrected["corrections"]["inputs"]), {"state", "applied", "not_applicable"})
        self.assertNotIn("waiting_on", corrected["corrections"])

    def test_stopped_build_writes_nothing(self):
        self.accept(self.cands[:1])
        calls = []
        self.assertEqual(corrections.ensure_base(NAME, should_stop=lambda: calls.append(1) or len(calls) > 1), "pending")
        self.assertFalse(os.path.exists(corrections.base_path(NAME)), "더 새 판이 들어오면 지은 것을 버린다")
        self.assertEqual(corrections.ensure_base(NAME), "ready")

    def stop_at(self, k):
        """k번째 확인에서 멈추라고 하는 should_stop과 그 확인 수."""
        calls = []
        return (lambda: calls.append(1) or len(calls) >= k), calls

    def folder(self):
        return sorted(os.listdir(os.path.dirname(corrections.base_path(NAME))))

    def test_build_stopped_inside_the_analysis_leaves_no_file_and_the_same_result_later(self):
        self.accept(self.cands[:1])
        stop, calls = self.stop_at(6)
        self.assertEqual(corrections.ensure_base(NAME, should_stop=stop), "pending")
        self.assertEqual(len(calls), 6, "분석 단계 사이에서 멈춘다(짓기를 끝까지 돌지 않음)")
        self.assertEqual(self.folder(), ["extraction.json"], "멈춘 짓기는 반쯤 쓴 파일을 남기지 않는다")
        self.assertEqual(corrections.resolve(NAME)["inputs"]["state"], "pending")
        self.assertEqual(corrections.ensure_base(NAME), "ready")
        with open(corrections.base_path(NAME), "rb") as fh:
            after_stop = fh.read()
        os.remove(corrections.base_path(NAME))
        with pdf_vector._cache_lock:
            pdf_vector._cache.clear()
        corrections.ensure_base(NAME)
        with open(corrections.base_path(NAME), "rb") as fh:
            self.assertEqual(fh.read(), after_stop, "멈춘 뒤 다시 지은 결과가 멈추지 않고 지은 것과 같다")

    def test_build_stopped_on_top_of_an_older_file_stays_partial(self):
        self.accept(self.cands[:1])
        corrections.ensure_base(NAME)
        with open(corrections.base_path(NAME), "rb") as fh:
            older = fh.read()
        self.accept(self.cands[1:2])
        stop, calls = self.stop_at(4)
        self.assertEqual(corrections.ensure_base(NAME, should_stop=stop), "pending")
        with open(corrections.base_path(NAME), "rb") as fh:
            self.assertEqual(fh.read(), older, "앞서 지은 기준 추출은 그대로")
        self.assertEqual(self.folder(), ["extraction.inputs.json", "extraction.json"])
        st = corrections.resolve(NAME)["inputs"]
        self.assertEqual((st["state"], st["waiting"]), ("partial", [self.ops()[1]["op_id"]]))

    def test_failed_split_gets_a_reason_code_for_the_queue(self):
        ops = []
        for g in (GROUPS[0], GROUPS[0][1:] + GROUPS[1][:1]):
            ops.append(corrections.make_op(self.original, "split", BLOB, corrections.input_value(self.original, g),
                                           BY, at=AT, existing_ops=ops, name=NAME))
        corrections.save(NAME, ops, BY, at=AT)
        items = corrections.input_items(corrections.resolve(NAME, allow_extract=True))
        self.assertEqual([(i["op_id"], i["state"], i["code"]) for i in items], [(ops[1]["op_id"], "not_applicable", "overlap")])
        self.assertEqual(items[0]["text"], "다른 나누기와 같은 부분을 골라 나누지 않았습니다.")

    def test_revert_preview_names_the_edit_that_goes_with_it_and_log_says_what_happened(self):
        self.accept(self.cands[:1])
        ops = self.ops()
        base = corrections.resolve(NAME, allow_extract=True)["base"]
        tag = corrections.make_op(base, "set_tag", "pdf-p0-split-" + ops[0]["op_id"], {"tag": "V-101"}, BY, at=AT,
                                  existing_ops=ops, name=NAME)
        corrections.save(NAME, ops + [tag], BY, at=AT)
        doc = ai_review.load_doc(NAME)
        self.assertEqual(ai_review.revert_preview(doc, self.cands[:1], NAME),
                         {"ops": [ops[0]["op_id"]],
                          "dependents": [{"op_id": tag["op_id"], "op": "set_tag", "target": tag["target"], "candidate": None}]})
        self.assertEqual(self.revert(self.cands[:1], confirm=[tag["op_id"]]), [ops[0]["op_id"], tag["op_id"]])
        self.assertEqual([e["action"] for e in corrections.load(NAME)["log"]], ["ai_accept", "save", "ai_revert"])


    # ---------------------------------------------------------------- 검토(hazop-reviewer, 2026-11-23) 지적

    def test_rebuilt_base_releases_the_sheet_fingerprint(self):
        """(1) 코드가 바뀌어 기준 추출을 다시 지으면 쪽 내용을 지금 코드로 다시 읽은 것이라 확정 지문이 바뀐다."""
        from hazop.extract import confirmation
        self.accept(self.cands[:1])
        corrections.ensure_base(NAME)
        before = confirmation.sheet_confirmation(NAME)["fingerprint"]
        with unittest.mock.patch.object(corrections, "code_fingerprint", lambda: "other-code"):
            self.assertEqual(corrections.ensure_base(NAME), "ready")
            after = confirmation.sheet_confirmation(NAME)
        self.assertNotEqual(after["fingerprint"], before, "다시 지은 기준 추출은 확정을 푼다")

    def test_sheet_fingerprint_without_input_ops_stays_the_three_files(self):
        from hazop.extract import confirmation
        st = confirmation.sheet_confirmation(NAME)
        text = "|".join("%s=%s" % (k, st["files"][k] or "-") for k in ("extraction", "edits", "ai_review"))
        self.assertEqual(st["fingerprint"], "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                         "입력 연산이 없는 쪽의 확정 지문은 예전과 같다")

    def test_reaccepting_keeps_the_op_id_but_records_who_accepted_it_now(self):
        """(2) 되살린 연산의 누가·언제는 지금 수락한 사람·시각이다."""
        ai_review.accept(ai_review.load_doc(NAME), self.cands[:1], self.original, NAME, by="가", at="2026-11-23T00:00:00Z")
        first = self.ops()[0]
        ai_review.revert(ai_review.load_doc(NAME), self.cands[:1], NAME, by="나", at="2026-11-24T00:00:00Z")
        ai_review.accept(ai_review.load_doc(NAME), self.cands[:1], self.original, NAME, by="다", at="2026-12-01T00:00:00Z")
        again = self.ops()[0]
        self.assertEqual(again["op_id"], first["op_id"])
        self.assertEqual((again["by"], again["at"], again["accepted_by"], again["accepted_at"]),
                         ("다", "2026-12-01T00:00:00Z", "다", "2026-12-01T00:00:00Z"))

    def test_edit_on_the_renumbered_lump_waits_with_its_split(self):
        """(3) 나뉜 뒤 번호가 바뀐 덩어리 나머지에 단 고침도 기준 추출이 낡으면 대기다."""
        self.accept(self.cands[:1])
        split = self.ops()[0]
        base = corrections.resolve(NAME, allow_extract=True)["base"]
        rest = next(n["source_object_id"] for n in base["nodes"]
                    if set(GROUPS[1]) <= set((n.get("evidence") or {}).get("pdf_objects") or ()))
        self.assertNotIn(rest, {n["source_object_id"] for n in self.original["nodes"]}, "덩어리 나머지는 새 번호")
        kind = corrections.make_op(base, "set_kind", rest, {"kind": "manual_valve", "category": "valve"}, BY, at=AT,
                                   existing_ops=[split], name=NAME)
        corrections.save(NAME, [split, kind], BY, at=AT)
        os.remove(corrections.base_path(NAME))
        got = corrections.resolve(NAME)
        self.assertEqual(got["inputs"]["waiting_on"], {kind["op_id"]: [split["op_id"]]})
        self.assertEqual(got["corrected"]["corrections"]["not_applicable"], [])
        self.assertIn((kind["op_id"], "waiting_on"), [(i["op_id"], i["code"]) for i in corrections.input_items(got)])

    def test_split_overlapping_an_old_add_node_acceptance_is_refused(self):
        """(4) 옛 판에서 add_node로 수락한 split이 차지한 개체와 겹치는 새 split 후보는 받지 않는다."""
        doc = ai_review.load_doc(NAME)
        old = doc["candidates"][0]
        b = old["new_bbox"]
        op = corrections.make_op(self.original, "add_node", None,
                                 {"kind": "manual_valve", "category": "valve", "bbox": [b[0], b[1], b[2] - b[0], b[3] - b[1]]},
                                 BY, at=AT, name=NAME)
        op.update(origin="ai", ai_candidate=old["cand_id"], accepted_by=BY, accepted_at=AT)
        corrections.save(NAME, [op], BY, at=AT)
        old.update(status="accepted", op_id=op["op_id"], decided_at=AT, decided_by=BY)
        lump = next(n for n in self.original["nodes"] if n["source_object_id"] == BLOB)
        twin = self.candidate(lump, GROUPS[0][1:] + GROUPS[1], pdf_vector.member_shapes(self.pdf, 0))
        doc["candidates"].append(twin)
        ai_review.save_doc(doc)
        failed = ai_review.accept(ai_review.load_doc(NAME), [twin["cand_id"]], self.original, NAME, by=BY, at=AT)
        self.assertEqual([c for c, _ in failed], [twin["cand_id"]])
        self.assertIn("이미 나눈 부분과 겹침", failed[0][1])
        self.assertEqual([o["op"] for o in self.ops()], ["add_node"], "같은 자리에 밸브 둘을 만들지 않는다")

    def test_pdf_replaced_with_the_same_size_and_time_is_not_built(self):
        """(5) 크기·수정 시각이 같은 채 내용이 바뀐 PDF는 같은 프로세스에서도 다시 읽기 전에 알아챈다."""
        self.accept(self.cands[:1])
        st = os.stat(self.pdf)
        with open(self.pdf, "rb") as fh:
            data = fh.read()
        self.assertEqual(data.count(b"1 w"), 1)
        with open(self.pdf, "wb") as fh:
            fh.write(data.replace(b"1 w", b"2 w"))
        os.utime(self.pdf, ns=(st.st_atime_ns, st.st_mtime_ns))
        corrections.ensure_base(NAME)
        got = corrections.resolve(NAME)["inputs"]
        self.assertEqual((got["applied"], [x["reason"] for x in got["not_applicable"]]), ([], [corrections.PDF_CHANGED]))

    def test_lump_a_person_edited_stays_closed(self):
        """(6) 사람이 고친 덩어리는 split 후보가 남아 있어도 다시 묻지 않는다(ba5c2f4와 같음)."""
        op = corrections.make_op(self.original, "set_kind", BLOB, {"kind": "package", "category": "equipment"},
                                 BY, at=AT, name=NAME)
        corrections.save(NAME, [op], BY, at=AT)
        self.assertIn(BLOB, ai_review.decided_targets(NAME))

    def test_revert_that_would_drop_a_human_edit_needs_the_preview(self):
        """(7) 기댄 사람 고침이 있으면 미리 알림의 op_id를 넘긴 호출만 지운다."""
        split, tag = self.tag_split()
        doc = ai_review.load_doc(NAME)
        with self.assertRaises(ai_review.RevertNeedsConfirm) as cm:
            ai_review.revert(doc, self.cands[:1], NAME, by=BY, at=AT)
        self.assertEqual(cm.exception.dependents, [tag["op_id"]])
        self.assertEqual([o["op_id"] for o in self.ops()], [split["op_id"], tag["op_id"]], "알림 없이는 아무것도 지우지 않는다")
        preview = ai_review.revert_preview(doc, self.cands[:1], NAME)
        removed = ai_review.revert(doc, self.cands[:1], NAME, by=BY, at=AT,
                                   confirm=[d["op_id"] for d in preview["dependents"]])
        self.assertEqual(removed, [split["op_id"], tag["op_id"]])

    def test_waiting_pipe_is_called_a_pipe(self):
        """(8) 배관 지정이 기다릴 때 글은 '나누기'가 아니다."""
        value = corrections.input_value(self.original, ["pdf-path-0001"], ring=False, line_type="process")
        op = corrections.make_op(self.original, "pipe", None, value, BY, at=AT, name=NAME)
        corrections.save(NAME, [op], BY, at=AT)
        items = corrections.input_items(corrections.resolve(NAME))
        self.assertEqual([i["code"] for i in items], ["waiting"])
        self.assertIn("배관 지정", items[0]["text"])
        self.assertNotIn("나누기", items[0]["text"])


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 필요")
class ObjectShapesCacheTest(unittest.TestCase):
    def test_page_is_read_once_and_analysis_fills_the_shapes(self):
        tmp = tempfile.mkdtemp()
        try:
            pdf = os.path.join(tmp, "syn.pdf")
            with open(pdf, "wb") as fh:
                fh.write(page(extra_line=True))
            with pdf_vector._cache_lock:
                pdf_vector._cache.clear()
                pdf_vector._shapes_cache.clear()
            reads = []
            real = pdf_vector.load_page
            with unittest.mock.patch.object(pdf_vector, "load_page", lambda *a: reads.append(1) or real(*a)):
                first = pdf_vector.object_shapes(pdf, 0)
                self.assertEqual(pdf_vector.object_shapes(pdf, 0), first)
                self.assertEqual(len(reads), 1, "같은 쪽은 한 번만 읽는다")
                with pdf_vector._cache_lock:
                    pdf_vector._shapes_cache.clear()
                pdf_vector.member_shapes(pdf, 0)
                self.assertEqual(pdf_vector.object_shapes(pdf, 0), first)
                self.assertEqual(len(reads), 2, "분석이 읽은 쪽의 모양을 함께 둔다")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
