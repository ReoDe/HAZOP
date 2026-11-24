"""큰 미분류 덩어리 나누기(hazop.extract.ai_split, AI 검토 과제 split) 시험. 실제 Claude를 부르지 않는다(가짜 클라이언트).

AI 상자는 찾는 범위일 뿐이고 새 노드는 덩어리의 pdf 개체로 묶인다. 겹친 개체는 가운데가 든 상자 하나에만 들어가고,
개체가 없거나 덩어리를 통째로 가져가는 답은 버린다. 나눔 입력이 없으면 추출은 그대로다.
"""

import os
import sys
import unittest
from unittest import mock

from hazop.extract import ai_images, ai_review, ai_split
from hazop.extract.adapters import pdf_vector
from hazop.extract.adapters.pdf_vector_grouping import _Sym

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

BIG = (100.0, 50.0, 260.0, 90.0)  # 160 x 40 pt 덩어리
MEMBERS = {"pdf-path-0001": ((110.0, 60.0, 120.0, 70.0), "bodies"),   # 왼쪽 밸브
           "pdf-path-0002": ((112.0, 52.0, 118.0, 59.0), "bodies"),   # 왼쪽 밸브 구동부
           "pdf-path-0003": ((200.0, 58.0, 230.0, 82.0), "bodies"),   # 오른쪽 펌프
           "pdf-path-0004": ((120.0, 65.0, 200.0, 65.5), "strokes"),  # 둘 사이 배관
           "pdf-path-0005": ((240.0, 60.0, 240.5, 61.0), "dashes")}   # 점선 조각 하나


def node(lid, kind, box, objs=(), sid=None):
    return {"local_id": lid, "source_object_id": sid or "s-" + lid, "kind": kind, "label_text": "",
            "geometry": {"x": box[0], "y": box[1], "width": box[2] - box[0], "height": box[3] - box[1]},
            "evidence": {"pdf_objects": list(objs)}}


def rel(*ends):
    return {"local_id": "r-" + "-".join(ends), "endpoints": [{"node_local_id": e} for e in ends]}


def ex_fixture():
    nodes = [node("big", None, BIG, sorted(MEMBERS)),
             node("lone", None, (300, 300, 420, 340), ["pdf-path-0009", "pdf-path-0010"]),      # 선이 닿지 않음
             node("small", None, (10, 10, 60, 30), ["pdf-path-0011", "pdf-path-0012"]),         # 긴 변 100pt 아래
             node("kinded", "tank", (500, 10, 700, 200), ["pdf-path-0013", "pdf-path-0014"]),  # 종류가 있음
             node("one", None, (10, 400, 200, 440), ["pdf-path-0015", "pdf-path-0015-1"]),     # 원시 요소 하나
             node("wide", None, (0, 500, 600, 700), ["pdf-path-0016", "pdf-path-0017"])]       # 더 넓은 덩어리
    return {"drawing": {"drawing_number": "T-1"}, "nodes": nodes,
            "relations": [rel("big", "x"), rel("small", "x"), rel("kinded", "x"), rel("one", "x"), rel("wide", "x")]}


def page():
    from PIL import Image
    p = ai_images.PageImages(None, scale=2.0)
    p._img = Image.new("RGB", (2000, 1600), "white")  # 쪽 1000 x 800 pt
    return p


def px(crop, box):
    """쪽 좌표 상자 → 조각 그림 픽셀(가짜 AI가 답하는 꼴)."""
    k = crop.px_per_pt
    return [(box[0] - crop.area[0]) * k, (box[1] - crop.area[1]) * k, (box[2] - crop.area[0]) * k, (box[3] - crop.area[1]) * k]


class StubClient:
    def __init__(self, answer):
        self.answer, self.requests = answer, []

    def describe(self):
        return {"via": "fixed"}  # 시험용 가짜: ai_review.refuse_reason이 구독·고정 응답만 통과시킨다

    def analyze(self, request):
        self.requests.append(request)
        return {"status": "completed", "error_kind": None, "output": self.answer(request), "via": "fixed"}


class TargetTest(unittest.TestCase):
    def test_picks_big_unclassified_touched_multi_primitive_nodes_largest_first(self):
        self.assertEqual([n["local_id"] for n in ai_split.targets(ex_fixture())], ["wide", "big"])


class GroupTest(unittest.TestCase):
    def test_member_goes_to_the_box_holding_its_center_and_is_left_out_when_ambiguous(self):
        members = {"a": ((18.5, 10, 22.5, 14), "bodies"),  # 두 상자 여유 안, 가운데는 첫 상자에만
                   "b": ((25, 22.5, 26, 24.5), "bodies"),  # 두 상자 여유 안, 가운데는 어느 상자에도 없음
                   "c": ((0, 0, 100, 2), "strokes")}    # 어느 상자에도 통째로 들지 않는 긴 선
        boxes = [[8, 8, 29, 22], [21, 8, 40, 22]]
        self.assertEqual(ai_split.group(members, boxes), [["a"], []])

    def test_box_covering_part_of_a_symbol_takes_its_body_but_not_a_pipe_passing_through(self):
        members = {"casing": ((0, 0, 30, 25), "bodies"),     # 상자가 일부만 감싼 펌프 몸통(가운데는 상자 안)
                   "pipe": ((-80, 12, 20, 13), "strokes"),   # 상자로 들어오는 긴 배관(가운데는 상자 밖)
                   "huge": ((-40, -40, 60, 60), "bodies")}   # 가운데는 상자 안이지만 상자보다 훨씬 큰 외곽
        self.assertEqual(ai_split.group(members, [[10, 5, 30, 25]]), [["casing"]])

    def test_short_piece_left_outside_joins_the_nearest_new_symbol_but_dashes_and_far_pieces_do_not(self):
        members = {"pump": ((0, 0, 30, 25), "bodies"),
                   "flange": ((34, 20, 34.2, 23), "strokes"),    # 펌프 출구 막대, 상자 밖 4pt
                   "dash": ((33, 10, 35, 10.2), "dashes"),       # 점선 배관 조각은 배관이다
                   "far": ((60, 10, 61, 12), "strokes")}         # 멀리 떨어진 작은 조각
        self.assertEqual(ai_split.group(members, [[0, 0, 30, 25]]), [["flange", "pump"]])


class CropTest(unittest.TestCase):
    def test_page_to_pixel_round_trip_and_shrinks_images_the_receiver_would_resize(self):
        crop = ai_split.Crop(page(), [0, 0, 950, 300])
        self.assertLessEqual(max(crop.img.size), ai_split.API_LONG)
        self.assertLess(crop.px_per_pt, 2.0)
        back = crop.to_page(px(crop, [100, 50, 260, 90]))
        for got, want in zip(back, [100, 50, 260, 90]):
            self.assertAlmostEqual(got, want, places=6)


class RunTest(unittest.TestCase):
    def run_split(self, answer, limit=20, used=0):
        images = ai_images.ImageInput(page(), [b"legend"], kinds=["manual_valve", "pump"], split=True)
        stats = {"calls": used, "errors": 0, "error_kinds": [], "legacy_key_hits": 0}
        client = StubClient(answer)
        with mock.patch.object(pdf_vector, "member_shapes", return_value=MEMBERS):
            cands = ai_split.run(ex_fixture(), client, images, stats, [], limit)
        return cands, stats, client

    def answer_for_big(self, symbols):
        def answer(req):
            import json
            ctx = json.loads(req["context"])
            if ctx["node"] != "big":
                return {"symbols": []}
            crop = ai_split.Crop(page(), list(BIG))
            return {"symbols": [dict(s, box=px(crop, s["box"])) for s in symbols]}
        return answer

    def test_boxes_regroup_primitives_and_bbox_comes_from_them(self):
        cands, stats, client = self.run_split(self.answer_for_big([
            {"box": [108, 50, 122, 72], "kind": "manual_valve", "match": "legend", "confidence": 0.9, "reason": "밸브 칸"},
            {"box": [198, 56, 232, 84], "kind": "pump", "match": "other", "confidence": 0.7, "reason": "펌프"},
            {"box": [400, 400, 420, 420], "kind": "pump", "match": "other", "confidence": 0.9, "reason": "빈 자리"}]))
        self.assertEqual(stats["split_calls"], 2)
        self.assertEqual(stats["split_new"], 2)
        self.assertEqual(stats["split_dropped"], 1)
        valve, pump = cands
        self.assertEqual(valve["pdf_objects"], ["pdf-path-0001", "pdf-path-0002"])
        self.assertEqual(valve["new_bbox"], [110.0, 52.0, 120.0, 70.0])
        self.assertEqual((valve["task"], valve["field"], valve["values"], valve["match"]), ("split", "split", ["manual_valve"], "legend"))
        self.assertEqual((valve["target"], valve["local_id"], valve["origin"]), ("s-big", "big", "ai"))
        self.assertEqual(pump["pdf_objects"], ["pdf-path-0003"])
        self.assertNotEqual(valve["cand_id"], pump["cand_id"])
        self.assertIn("images", client.requests[0])
        self.assertEqual(client.requests[0]["schema"]["properties"]["symbols"]["items"]["properties"]["kind"]["enum"],
                         ["manual_valve", "pump"])

    def test_answer_taking_the_whole_lump_is_not_a_split(self):
        cands, stats, _ = self.run_split(self.answer_for_big([
            {"box": [100, 50, 260, 90], "kind": "pump", "match": "other", "confidence": 0.9, "reason": "전부"}]))
        self.assertEqual(cands, [])
        self.assertEqual(stats["split_dropped"], 1)

    def test_kind_outside_the_list_and_bad_boxes_are_dropped(self):
        cands, stats, _ = self.run_split(self.answer_for_big([
            {"box": [108, 50, 122, 72], "kind": "tank", "match": "other", "confidence": 0.9, "reason": ""},
            {"box": [108, 50, 108, 72], "kind": "pump", "match": "other", "confidence": 0.9, "reason": ""}]))
        self.assertEqual((cands, stats["split_dropped"]), ([], 2))

    VALVE = {"box": [108, 50, 122, 72], "kind": "manual_valve", "match": "legend", "confidence": 0.9, "reason": "밸브"}
    PUMP = {"box": [198, 56, 232, 84], "kind": "pump", "match": "other", "confidence": 0.7, "reason": "펌프"}

    def test_accepted_candidate_survives_a_rerun_whose_answers_come_in_another_order(self):
        first, _, _ = self.run_split(self.answer_for_big([self.VALVE]))
        doc = ai_review.merge_run(ai_review.new_doc("T-1", ex_fixture()), {"candidates": first, "stats": {}})
        doc["candidates"][0]["status"] = "accepted"
        again, _, _ = self.run_split(self.answer_for_big([self.PUMP, self.VALVE]))
        ai_review.merge_run(doc, {"candidates": again, "stats": {}})
        got = sorted((c["values"][0], c["status"]) for c in doc["candidates"])
        self.assertEqual(got, [("manual_valve", "accepted"), ("pump", "proposed")])

    def test_candidate_id_comes_from_the_lump_and_its_grouped_objects(self):
        a, _, _ = self.run_split(self.answer_for_big([self.VALVE, self.PUMP]))
        b, _, _ = self.run_split(self.answer_for_big([self.PUMP, dict(self.VALVE, box=[109, 51, 121, 71])]))
        self.assertEqual({c["cand_id"]: c["pdf_objects"] for c in a}, {c["cand_id"]: c["pdf_objects"] for c in b})

    def test_huge_box_drops_only_that_symbol_and_the_review_goes_on(self):
        def answer(req):
            crop = ai_split.Crop(page(), list(BIG))
            return {"symbols": [dict(self.PUMP, box=[0, 0, 10 ** 400, 10]), dict(self.PUMP, box=[0, 0, 1e999, 1e999]),
                                dict(self.PUMP, box=px(crop, self.PUMP["box"]))]}
        cands, stats, client = self.run_split(answer)
        self.assertEqual([c["pdf_objects"] for c in cands], [["pdf-path-0003"]])
        self.assertEqual(stats["split_calls"], 2)

    def test_boxes_that_are_not_finite_or_outside_the_picture_are_dropped_without_stopping(self):
        crop = ai_split.Crop(page(), list(BIG))
        w, h = crop.img.size
        bad = [[0, 0, 10 ** 400, 10], [0, 0, float("inf"), 10], [0, 0, float("nan"), 10], [-3 * w, 0, 10, 10],
               [0, 0, 10, 5 * h]]
        res = {"output": {"symbols": [dict(self.PUMP, box=b) for b in bad]
                          + [dict(self.PUMP, kind=["pump"]), dict(self.PUMP, box=px(crop, self.PUMP["box"]))]}}
        answers, dropped = ai_split._answers(res, {"pump"}, crop)
        self.assertEqual((len(answers), dropped), (1, len(bad) + 1))
        for odd in ({"symbols": {"box": [0, 0, 1, 1]}}, {"symbols": "x"}, ["symbols"], None):
            self.assertEqual(ai_split._answers({"output": odd}, {"pump"}, crop)[0], [])

    def test_stays_inside_the_remaining_call_budget(self):
        _, stats, client = self.run_split(lambda req: {"symbols": []}, limit=20, used=19)
        self.assertEqual((stats["split_calls"], stats["calls"], len(client.requests)), (1, 20, 1))
        _, stats, client = self.run_split(lambda req: {"symbols": []}, limit=20, used=20)
        self.assertEqual((stats["split_calls"], len(client.requests)), (0, 0))


class ReviewRunTest(unittest.TestCase):
    def test_review_asks_split_after_kind_and_tag_within_the_same_cap(self):
        def answer(req):
            if "symbols" in req["schema"]["properties"]:
                crop = ai_split.Crop(page(), list(BIG))
                return {"symbols": [{"box": px(crop, [198, 56, 232, 84]), "kind": "pump", "match": "legend",
                                     "confidence": 0.8, "reason": "펌프 칸"}]}
            return {"answers": []}
        client = StubClient(answer)
        images = ai_images.ImageInput(page(), [b"legend"], kinds=["manual_valve", "pump"], split=True)
        with mock.patch.object(pdf_vector, "member_shapes", return_value=MEMBERS):
            doc = ai_review.run(ex_fixture(), client, cap=2, images=images)
        st = doc["stats"]
        self.assertEqual((st["calls"], st["split_calls"], st["split_targets"]), (2, 1, 2))
        self.assertEqual([c["task"] for c in doc["candidates"]], [])
        with mock.patch.object(pdf_vector, "member_shapes", return_value=MEMBERS):
            doc = ai_review.run(ex_fixture(), StubClient(answer), cap=20, images=images)
        self.assertEqual([(c["task"], c["values"], c["pdf_objects"]) for c in doc["candidates"]],
                         [("split", ["pump"], ["pdf-path-0003"])])

    def test_split_is_off_unless_asked(self):
        client = StubClient(lambda req: {"answers": []})
        images = ai_images.ImageInput(page(), [b"legend"], kinds=["pump"])
        doc = ai_review.run(ex_fixture(), client, cap=20, images=images)
        self.assertNotIn("split_calls", doc["stats"])
        self.assertFalse(any("symbols" in r["schema"]["properties"] for r in client.requests))


class ReviewFlowTest(unittest.TestCase):
    def test_check_form_and_accept_op_is_a_split_input_on_vector_pdf_only(self):
        c = ai_review.make_candidate("split:big:0", "split", {"target": "s-big", "local_id": "big", "bbox": [110, 52, 120, 70]},
                                     "split", ["manual_valve"], 0.9, "", {"match": "legend", "pdf_objects": ["pdf-path-0001"],
                                                                          "new_bbox": [110, 52, 120, 70]})
        self.assertEqual(ai_review.to_check_candidates({"candidates": [c]})["candidates"],
                         [{"node_local_id": "big", "field": "split", "values": ["manual_valve"], "match": "legend",
                           "pdf_objects": ["pdf-path-0001"], "bbox": [110, 52, 120, 70]}])
        with self.assertRaisesRegex(ValueError, "벡터 PDF 도면만"):  # 수락은 나누기 입력 연산(tests.test_ai_split_accept)
            ai_review._op_for(c, {"source": {"format": "drawio"}})
        self.assertIsNotNone(ai_review.bulk_block(dict(c, confidence=1.0)))
        self.assertIn("split", ai_review.TASK_ORDER)
        self.assertIn("split", ai_review.TASK_LABELS)

    def test_split_inputs_list_whole_node_and_groups(self):
        ex = ex_fixture()
        cands = [{"node_local_id": "big", "field": "split", "values": ["pump"], "pdf_objects": ["pdf-path-0003"]},
                 {"node_local_id": "big", "field": "kind", "values": ["pump"]}]
        self.assertEqual(ai_split.split_inputs(ex, cands), [{"node": sorted(MEMBERS), "groups": [["pdf-path-0003"]]}])


def body(pid, box):
    x0, y0, x1, y1 = box
    return {"id": pid, "pts": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "bbox": box, "closed": True, "kind_": "body"}


def stroke(pid, box):
    return {"id": pid, "pts": [(box[0], box[1]), (box[2], box[3])], "bbox": box, "kind_": "poly"}


class CarveTest(unittest.TestCase):
    def test_group_becomes_its_own_symbol_and_lump_lines_are_released(self):
        lump = _Sym([body("a", (0, 0, 10, 10)), body("b", (50, 0, 60, 10)), stroke("p", (10, 5, 50, 5))])
        other = _Sym([body("z", (100, 100, 110, 110))])
        syms, polys, markers, dashes = pdf_vector._carve_splits([lump, other], [], [], [],
                                                                [{"node": ["a", "b", "p"], "groups": [["b"]]}])
        self.assertEqual([s.evidence() for s in syms], [["a"], ["z"], ["b"]])
        self.assertEqual([p["id"] for p in polys], ["p"])
        self.assertEqual(syms[0].bbox, (0, 0, 10, 10))

    def test_group_without_body_or_line_is_skipped(self):
        lump = _Sym([body("a", (0, 0, 10, 10)), stroke("p", (10, 5, 50, 5))])
        lump.add([{"id": "d", "bbox": (20, 0, 21, 1)}], "dashes")
        syms, polys, _, dashes = pdf_vector._carve_splits([lump], [], [], [], [{"node": ["a", "d", "p"], "groups": [["d"]]}])
        self.assertEqual(([s.evidence() for s in syms], polys, dashes), ([["a", "d", "p"]], [], []))


class CheckApplyTest(unittest.TestCase):
    def test_without_split_candidates_the_check_applies_candidates_as_before(self):
        import check_read_quality as crq
        ex = ex_fixture()
        cands = {"candidates": [{"node_local_id": "big", "field": "kind", "values": ["pump"]}]}
        self.assertEqual(crq.apply_with_splits(ex, cands, None, None), crq.apply_candidates(ex, cands))


if __name__ == "__main__":
    unittest.main()
