"""추출 뒤 AI 검토(hazop.extract.ai_review) 시험. 실제 Claude를 부르지 않는다(가짜 클라이언트·고정 응답).

규격: docs/specs/extraction.md '읽기 품질 지표'의 AI 후보 규칙, INTENT.md §3.2(스크립트 우선, AI는 후보만).
작업 루트는 임시 폴더. 수락은 사람 수정 기록(hazop.extract.corrections)에 연산으로 들어가고 되돌리면 빠진다.
"""

import base64
import copy
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from hazop import paths
from hazop.extract import ai_review as ar
from hazop.extract import corrections
from hazop.study import providers

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))


def node(sid, kind, box, tag=None, **attrs):
    x0, y0, x1, y1 = box
    return {"local_id": "L" + sid, "source_object_id": sid, "kind": kind, "tag": tag, "label_text": "",
            "category": None, "attributes": attrs,
            "geometry": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}}


def text(t, x, y):
    return {"local_id": "T" + t, "source_object_id": "t-" + t, "text": t, "label": t,
            "geometry": {"x": x, "y": y, "width": 10, "height": 4}}


def ex_fixture():
    nodes = [node("n1", None, (100, 100, 110, 108)),                          # 미분류 → 종류
             node("n2", "manual_valve", (200, 100, 210, 108), normal_position="LO"),  # 태그 없음 → 태그
             node("n3", "motor_operated_valve", (300, 100, 310, 108), tag="V301"),  # 위치 없음 → 위치
             node("n4", "pump", (400, 90, 430, 120), tag="PP01"),
             node("n5", "continuation", (500, 100, 530, 110)),                 # 목적지 없음 → 도면 밖 연결
             node("n6", "check_valve", (150, 140, 160, 148), tag="V160")]
    rel_open = {"local_id": "Lr1", "source_object_id": "r1", "kind": "physical_connection",
                "endpoints": [{"end": "source", "node_local_id": "Ln4", "source_object_id": "n4", "point": [430, 105]},
                              {"end": "target", "node_local_id": None, "source_object_id": None, "point": [480, 105],
                               "status": "unconnected"}],
                "flow_direction": None, "waypoints": [], "attributes": {}}
    return {"drawing": {"drawing_number": "T-1"}, "nodes": nodes, "relations": [], "unresolved_connectors": [rel_open],
            "texts": [text("LO", 98, 92), text("V200", 201, 110), text("FAR", 900, 900)]}


class StubClient:
    """요청을 기록하고 answer(request) → output으로 답한다. errors가 있으면 순서대로 실패를 돌려준다."""

    def __init__(self, answer, errors=()):
        self.answer, self.errors, self.requests = answer, list(errors), []

    def analyze(self, request):
        self.requests.append(request)
        if self.errors:
            kind = self.errors.pop(0)
            if kind:
                return {"status": "api_error", "error_kind": kind, "error": kind, "output": None}
        return {"status": "completed", "error_kind": None, "output": self.answer(request), "via": "fixed"}

    def cancel(self):
        pass


def ids_in(request):
    return json.loads(request["context"])["items"]


def good_answers(request):
    out = []
    for it in ids_in(request):
        f = it["ask"][0]
        value = {"kind": "manual_valve", "tag": "V200", "normal_position": "NO", "fail_position": "FC",
                 "connection": (it.get("partners") or [{"id": "none"}])[0]["id"], "to_system": "CV"}[f]
        out.append({"item_id": it["item_id"], "field": f, "values": [value], "confidence": 0.9, "reason": "가까운 글자"})
    return {"answers": out}


class ItemsTest(unittest.TestCase):
    def test_collect_items_by_task(self):
        items = ar.collect_items(ex_fixture(), recheck=0)
        got = {(i["task"], i["target"], tuple(i["ask"])) for i in items}
        self.assertIn(("kind", "n1", ("kind",)), got)
        self.assertIn(("tag", "n2", ("tag",)), got)
        self.assertIn(("tag", "n3", ("normal_position", "fail_position")), got)
        self.assertIn(("connection", "r1", ("connection",)), got)
        self.assertIn(("connection", "n5", ("to_system",)), got)
        self.assertNotIn("n4", {i["target"] for i in items})

    def test_open_end_partners_are_nearby_nodes_only(self):
        item = next(i for i in ar.collect_items(ex_fixture(), recheck=0) if i["target"] == "r1")
        self.assertEqual([p["id"] for p in item["partners"]], ["n5"])  # 열린 끝(480,105)에서 가까운 기호, 붙은 n4 제외

    def test_recheck_sample_is_deterministic(self):
        a = ar.collect_items(ex_fixture(), recheck=2)
        b = ar.collect_items(ex_fixture(), recheck=2)
        self.assertEqual([i["item_id"] for i in a], [i["item_id"] for i in b])
        self.assertEqual(sum(1 for i in a if i["task"] == "recheck"), 2)

    def test_describe_lists_near_text_not_far(self):
        item = next(i for i in ar.collect_items(ex_fixture(), recheck=0) if i["target"] == "n1")
        d = ar.describe(ex_fixture(), item)
        self.assertIn("LO", json.dumps(d, ensure_ascii=False))
        self.assertNotIn("FAR", json.dumps(d, ensure_ascii=False))


class PlanTest(unittest.TestCase):
    def test_cap_and_left(self):
        items = [{"item_id": "x%d" % i, "task": "kind"} for i in range(45)]
        p = ar.plan(items, cap=2, batch=20)
        self.assertEqual([len(c) for c in p["calls"]], [20, 20])
        self.assertEqual(p["left"], 5)
        self.assertEqual(ar.plan(items, cap=10, batch=20)["left"], 0)

    def test_priority_order(self):
        items = [{"item_id": "r", "task": "recheck"}, {"item_id": "c", "task": "connection"},
                 {"item_id": "k", "task": "kind"}, {"item_id": "t", "task": "tag"}]
        self.assertEqual([i["item_id"] for i in ar.plan(items, cap=1, batch=4)["calls"][0]], ["k", "t", "c", "r"])

    def test_estimate(self):
        e = ar.estimate(ex_fixture(), cap=20)
        self.assertEqual(e["calls"], 1)
        self.assertEqual(e["items"], len(ar.collect_items(ex_fixture(), recheck=ar.DEFAULT_RECHECK)))
        self.assertGreater(e["seconds"], 0)


class RunTest(unittest.TestCase):
    def test_candidates_from_answers_and_script_untouched(self):
        ex = ex_fixture()
        before = copy.deepcopy(ex)
        doc = ar.run(ex, StubClient(good_answers), cap=5, recheck=0)
        self.assertEqual(ex, before)  # 스크립트 결과는 바꾸지 않는다
        fields = sorted((c["target"], c["field"]) for c in doc["candidates"])
        self.assertIn(("n1", "kind"), fields)
        self.assertIn(("r1", "connection"), fields)
        c = doc["candidates"][0]
        self.assertEqual((c["origin"], c["status"]), ("ai", "proposed"))
        self.assertEqual(doc["stats"]["calls"], 1)

    def test_invalid_answers_are_dropped(self):
        def bad(request):
            return {"answers": [{"item_id": "nope", "field": "kind", "values": ["pump"], "confidence": 1, "reason": ""},
                                {"item_id": ids_in(request)[0]["item_id"], "field": "kind", "values": ["not_a_kind"],
                                 "confidence": 1, "reason": ""},
                                {"item_id": ids_in(request)[0]["item_id"], "field": "tag", "values": ["X"],
                                 "confidence": 1, "reason": ""}]}
        doc = ar.run(ex_fixture(), StubClient(bad), cap=5, recheck=0)
        self.assertEqual(doc["candidates"], [])
        self.assertEqual(doc["stats"]["dropped"], 3)

    def test_connection_must_be_listed_partner(self):
        def ans(request):
            it = next(i for i in ids_in(request) if i["target"] == "r1")
            return {"answers": [{"item_id": it["item_id"], "field": "connection", "values": ["n1"], "confidence": 1,
                                 "reason": ""}]}
        self.assertEqual(ar.run(ex_fixture(), StubClient(ans), cap=5, recheck=0)["candidates"], [])

    def test_recheck_same_value_is_not_a_candidate(self):
        def ans(request):
            return {"answers": [{"item_id": i["item_id"], "field": "kind", "values": [i["current"]["kind"]],
                                 "confidence": 1, "reason": ""} for i in ids_in(request) if i["task"] == "recheck"]}
        doc = ar.run(ex_fixture(), StubClient(ans), cap=5, recheck=2)
        self.assertEqual(doc["candidates"], [])
        self.assertEqual(doc["stats"]["confirmed"], 2)

    def test_halting_error_stops_and_leaves_rest(self):
        items = ar.collect_items(ex_fixture(), recheck=0)
        doc = ar.run(ex_fixture(), StubClient(good_answers, errors=["limit_reached"]), cap=5, recheck=0, batch=2)
        self.assertEqual(doc["stats"]["calls"], 1)
        self.assertTrue(doc["stats"]["halted"])
        self.assertEqual(doc["stats"]["left"], len(items))
        self.assertTrue(providers.ERROR_KINDS["limit_reached"])

    def test_stop_flag_and_progress(self):
        seen = []
        doc = ar.run(ex_fixture(), StubClient(good_answers), cap=5, recheck=0, batch=2,
                     on_progress=lambda done, total, left: seen.append((done, total)), should_stop=lambda: len(seen) >= 1)
        self.assertEqual(doc["stats"]["calls"], 1)
        self.assertTrue(doc["stats"]["stopped"])
        self.assertGreater(doc["stats"]["left"], 0)
        self.assertEqual(seen[0], (1, 3))

    def test_cap_leaves_unchecked_count(self):
        doc = ar.run(ex_fixture(), StubClient(good_answers), cap=1, recheck=0, batch=2)
        self.assertEqual(doc["stats"]["calls"], 1)
        self.assertEqual(doc["stats"]["left"], len(ar.collect_items(ex_fixture(), recheck=0)) - 2)

    def test_bulk_groups(self):
        doc = ar.run(ex_fixture(), StubClient(good_answers), cap=5, recheck=0)
        low = next(c for c in doc["candidates"] if c["field"] == "tag")
        low["confidence"] = 0.4
        next(c for c in doc["candidates"] if c["field"] == "kind")["confidence"] = 0.99
        groups = ar.bulk_groups(doc, threshold=0.8)
        self.assertNotIn(low["cand_id"], [c for v in groups.values() for c in v])
        self.assertNotIn("kind", groups)                  # 기호 종류는 확신과 관계없이 하나씩 확정(검토 차단 1)
        self.assertIn("normal_position", groups)
        self.assertNotIn("tag", groups)


CUT = os.path.join(REPO, "tests", "fixtures", "ai-review", "apr1400-063-cut.json")


class RealCutTest(unittest.TestCase):
    """실제 추출 형식(APR1400 063쪽 조각, 공개 자료). 검토 차단 1: 스크립트가 일부러 종류를 비운 노드(안전등급 경계 마름모,
    classification_basis safety_class_boundary, missing_kind 미확인 없음)에는 종류를 묻지 않는다."""

    def ex(self):
        with open(CUT, encoding="utf-8") as fh:
            return json.load(fh)

    def test_kind_asked_only_where_missing_kind(self):
        ex = self.ex()
        kinds = {i["local_id"] for i in ar.collect_items(ex, recheck=0) if i["task"] == "kind"}
        self.assertEqual(kinds, {"local-node-001", "local-node-144"})
        self.assertNotIn("local-node-010", kinds)                     # 안전등급 경계: 스크립트가 무엇인지 안다

    def test_no_bulk_kind_on_real_cut(self):
        ex = self.ex()
        def answers(req):
            return {"answers": [{"item_id": it["item_id"], "field": it["ask"][0], "values": ["blind_flange"], "confidence": 0.99,
                                 "reason": "시험"} for it in ids_in(req) if it["ask"][0] == "kind"]}
        doc = ar.run(ex, StubClient(answers), cap=5, recheck=0)
        self.assertEqual({c["local_id"] for c in doc["candidates"]}, {"local-node-001", "local-node-144"})
        self.assertEqual(ar.bulk_groups(doc), {})


class BulkSafetyTest(unittest.TestCase):
    """AI 종류 후보의 오검출(읽기 품질 기록 'AI 후보 포함', @1731277: 28 → 63)을 줄이는 규칙."""

    def ex(self):
        ex = ex_fixture()
        ex["nodes"].append(node("n7", None, (304, 92, 309, 97)))      # 이름 있는 밸브 n3(300~310, 100~108) 위에 붙은 작은 상자
        return ex

    def test_kind_item_knows_attached_symbol(self):
        items = {i["target"]: i for i in ar.collect_items(self.ex(), recheck=0)}
        self.assertEqual(items["n7"]["near_symbol"], "motor_operated_valve")
        self.assertIsNone(items["n1"]["near_symbol"])

    def test_not_symbol_answer_makes_no_candidate(self):
        def answers(req):
            out = good_answers(req)
            for a in out["answers"]:
                if a["item_id"] == "k-n7":
                    a["values"] = ["not_symbol"]
            return out
        doc = ar.run(self.ex(), StubClient(answers), cap=5, recheck=0)
        self.assertNotIn("n7", {c["target"] for c in doc["candidates"]})
        self.assertEqual(doc["stats"]["not_symbol"], 1)
        self.assertIn("not_symbol", ar.system_text())

    def test_kind_is_never_bulk(self):
        doc = ar.run(self.ex(), StubClient(good_answers), cap=5, recheck=0)
        kinds = {c["target"]: c for c in doc["candidates"] if c["field"] == "kind"}
        self.assertEqual(kinds["n7"]["near_symbol"], "motor_operated_valve")
        for c in kinds.values():
            c["confidence"] = 1.0
        self.assertNotIn("kind", ar.bulk_groups(doc))
        self.assertNotIn("kind", ar.bulk_groups(doc, by="task"))
        self.assertIn("하나씩", ar.bulk_block(kinds["n1"]))
        self.assertIn("이웃 기호", ar.bulk_block(kinds["n7"]))
        self.assertIn("tag", ar.bulk_groups(doc))                     # 태그는 0.85 그대로

    def test_recheck_disagreement_is_not_bulk(self):
        c = ar.make_candidate("r-n4", "recheck", node("n4", "pump", (0, 0, 9, 9), tag="PP01"), "tag", ["PP02"], 0.99, "")
        self.assertIn("다시 확인", ar.bulk_block(c))

    def test_validation_without_missing_kind_asks_nothing(self):
        ex = self.ex()
        ex["validation"] = {"unknowns": [{"check": "missing_kind", "target": "Ln1"}]}
        kinds = {i["target"] for i in ar.collect_items(ex, recheck=0) if i["task"] == "kind"}
        self.assertEqual(kinds, {"n1"})                              # n7은 missing_kind 미확인이 없음

    def test_annotate_fills_old_candidates(self):
        ex = self.ex()
        c = ar.make_candidate("k-n7", "kind", next(n for n in ex["nodes"] if n["source_object_id"] == "n7"), "kind",
                              ["solenoid_valve"], 0.99, "")
        doc = {"candidates": [c]}
        self.assertNotIn("near_symbol", c)
        ar.annotate(doc, ex)
        self.assertEqual(c["near_symbol"], "motor_operated_valve")

    def test_check_format_uses_first_value(self):
        doc = ar.run(ex_fixture(), StubClient(good_answers), cap=5, recheck=0)
        fmt = ar.to_check_candidates(doc)
        kinds = [c for c in fmt["candidates"] if c["field"] == "kind"]
        self.assertEqual(kinds[0]["node_local_id"], "Ln1")
        conn = [c for c in fmt["candidates"] if c["field"] == "connection"]
        self.assertEqual((conn[0]["a"], conn[0]["b"]), ("Ln4", "Ln5"))


class FixedResponseTest(unittest.TestCase):
    """고정 응답 클라이언트(providers.FixedCellsClient)로 같은 요청 → 같은 후보."""

    def test_fixed_client_round_trip(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        ex = ex_fixture()
        for call in ar.plan(ar.collect_items(ex, recheck=0), cap=5, batch=20)["calls"]:
            req = ar.build_request(ex, call)
            with open(os.path.join(tmp, providers.fixed_key(req) + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"output": good_answers(req)}, fh, ensure_ascii=False)
        doc = ar.run(ex, providers.FixedCellsClient(tmp), cap=5, recheck=0)
        self.assertEqual(doc["stats"]["errors"], 0)
        self.assertEqual(len(doc["candidates"]), 5)

    def test_request_has_no_tools_and_strict_schema(self):
        req = ar.build_request(ex_fixture(), ar.collect_items(ex_fixture(), recheck=0))
        self.assertFalse(req["schema"]["additionalProperties"])
        self.assertIn("answers", req["schema"]["required"])
        self.assertIn("후보", req["system"])


class StubPage:
    """조각 그림 대신 상자 좌표를 글자로 담은 바이트(요청에 어느 자리가 실렸는지 본다).
    off에 든 상자는 쪽 밖이라 자를 수 없는 것으로 본다."""

    def __init__(self, off=()):
        self.off = [list(b) for b in off]

    def crop_box(self, bbox):
        return None if list(bbox) in self.off else list(bbox)

    def crop_png(self, bbox, pad=25.0):
        assert self.crop_box(bbox) is not None, "자를 수 없는 상자를 요청에 실음"
        return ("crop:%s:pad%g" % (",".join("%g" % v for v in bbox), pad)).encode("ascii")


class CropEdgeTest(unittest.TestCase):
    """쪽 밖으로 삐져나간 상자: 자를 영역을 쪽 안으로 맞추고, 쪽과 겹치지 않거나 너무 좁으면 그림 없이 건너뛴다."""

    def page(self):
        from PIL import Image
        from hazop.extract import ai_images
        p = ai_images.PageImages(None, scale=2.0)
        p._img = Image.new("RGB", (400, 200), "white")  # 쪽 200 x 100 pt
        return p

    def test_boxes_outside_each_side_are_skipped_without_error(self):
        p = self.page()
        for bbox in ([240, 40, 250, 50], [-60, 40, -50, 50], [40, -60, 50, -50], [40, 140, 50, 150]):
            self.assertIsNone(p.crop_box(bbox), bbox)
            self.assertIsNone(p.crop(bbox), bbox)
            self.assertIsNone(p.crop_png(bbox), bbox)

    def test_partly_outside_box_is_cut_inside_page(self):
        p = self.page()
        box = p.crop_box([190, 90, 210, 110])
        self.assertEqual(box, [165.0, 65.0, 200.0, 100.0])
        self.assertEqual(p.crop([190, 90, 210, 110]).size, (70, 70))

    def test_zero_area_box(self):
        p = self.page()
        self.assertEqual(p.crop([50, 50, 50, 50]).size, (100, 100), "쪽 안의 점 상자는 둘레를 잘라 보낸다")
        self.assertIsNone(p.crop_box([250, 50, 250, 50]), "쪽 밖의 점 상자는 건너뜀")
        self.assertIsNone(p.crop_box([200, 50, 200, 50], pad=1.0), "쪽 끝에 닿아 너무 좁은 영역은 건너뜀")

    def test_run_skips_uncroppable_items_and_counts_them(self):
        from hazop.extract import ai_images
        ex = ex_fixture()
        items = [i for i in ar.collect_items(ex, 0) if i["task"] in ar.IMAGE_TASKS]
        off = items[0]["bbox"]
        stub = StubClient(good_answers)
        doc = ar.run(ex, stub, cap=5, images=ai_images.ImageInput(StubPage([off]), [b"legend-1"], kinds=["pump"]))
        asked = [it["item_id"] for req in stub.requests for it in ids_in(req)]
        self.assertNotIn(items[0]["item_id"], asked)
        self.assertEqual(doc["stats"]["no_image"], sum(1 for i in items if i["bbox"] == off))
        self.assertEqual(doc["stats"]["items"], len(items) - doc["stats"]["no_image"])

    def test_legend_skips_sample_outside_page(self):
        from hazop.extract import ai_images
        p = self.page()
        spots = [("pump", [20, 20, 30, 30]), ("manual_valve", [260, 20, 270, 30])]
        boards, order = ai_images.legend_boards([(p, spots)], kinds=["pump", "manual_valve"])
        self.assertEqual((len(boards), order), (1, ["pump"]))


class ImageInputTest(unittest.TestCase):
    """그림 입력(ai_images.ImageInput): kind·tag만, 항목마다 조각, 종류를 물을 때만 범례판, 종류는 목록 안에서만."""

    def images(self, kinds=("manual_valve", "pump"), wide=False):
        from hazop.extract import ai_images
        return ai_images.ImageInput(StubPage(), [b"legend-1"], kinds=list(kinds), wide=wide)

    def test_unknown_and_not_symbol_make_no_candidate(self):
        def answers(req):
            return {"answers": [{"item_id": it["item_id"], "field": "kind", "values": [v], "confidence": 0.9,
                                 "reason": "x"} for it, v in zip(ids_in(req), ("unknown", "not_symbol"))
                                if it["task"] == "kind"]}
        ex = ex_fixture()
        ex["nodes"].append(node("n8", None, (600, 100, 610, 108)))
        doc = ar.run(ex, StubClient(answers), cap=5, recheck=0, images=self.images())
        self.assertEqual([c for c in doc["candidates"] if c["field"] == "kind"], [])
        self.assertEqual((doc["stats"]["kind_items"], doc["stats"]["unknown"], doc["stats"]["not_symbol"]), (2, 1, 1))
        self.assertIn("'unknown'", ar.system_text(self.images()))

    def test_wide_pass_reasks_valve_kinds_with_wider_crop(self):
        seen = []

        def answers(req):
            wide = req["user"] == ar.WIDE_USER
            seen.append((wide, [im["data"] for im in req["images"] if im["label"].startswith("그림 ")]))
            out = []
            for it in ids_in(req):
                if it["task"] != "kind":
                    continue
                if not wide:
                    out.append({"item_id": it["item_id"], "field": "kind", "confidence": 0.9, "reason": "x",
                                "values": ["pump" if it["target"] == "n9" else "manual_valve"]})
                elif it["target"] == "n1":
                    out.append({"item_id": it["item_id"], "field": "kind", "values": ["control_valve"],
                                "confidence": 0.9, "reason": "구동부"})
                else:
                    out.append({"item_id": it["item_id"], "field": "kind", "values": ["unknown"], "confidence": 0.5,
                                "reason": "x"})
            return {"answers": out}
        ex = ex_fixture()
        ex["nodes"] += [node("n8", None, (600, 100, 610, 108)), node("n9", None, (700, 100, 730, 130))]
        kinds = ("manual_valve", "control_valve", "pump")
        doc = ar.run(ex, StubClient(answers), cap=5, recheck=0, images=self.images(kinds, wide=True))
        got = {c["target"]: c for c in doc["candidates"] if c["field"] == "kind"}
        self.assertEqual({t: c["values"][0] for t, c in got.items()}, {"n1": "control_valve", "n9": "pump"})
        self.assertEqual(got["n1"]["first_values"], ["manual_valve"])
        st = doc["stats"]
        self.assertEqual((st["wide_calls"], st["wide_changed"], st["wide_dropped"]), (1, 1, 1))
        wide_crops = [d for w, crops in seen if w for d in crops]
        self.assertEqual(len(wide_crops), 2, "밸브 답 둘만 다시 묻는다")
        self.assertTrue(all(b"pad60" in base64.b64decode(d) for d in wide_crops))
        plain = ar.run(ex, StubClient(answers), cap=5, recheck=0, images=self.images(kinds))
        self.assertEqual(plain["stats"]["wide_calls"], 0)

    def test_answer_kinds_are_fixed_shape_viewer_kinds(self):
        from hazop.extract import ai_images
        kinds = ai_images.answer_kinds()
        self.assertTrue(set(kinds) <= set(ai_images.viewer_kinds()))
        self.assertIn("manual_valve", kinds)
        for stretched in ("tank", "vessel", "continuation", "heat_exchanger"):
            self.assertNotIn(stretched, kinds)

    def test_legend_sample_is_median_size_and_answers_follow_board(self):
        from hazop.extract import ai_images

        class Page:
            def crop(self, bbox, pad=0, outline=True):
                from PIL import Image
                return Image.new("RGB", (max(1, int(bbox[2] - bbox[0])), max(1, int(bbox[3] - bbox[1]))), "white")

        page = Page()
        spots = [("manual_valve", [0, 0, w, w]) for w in (2, 10, 40)] + [("tank", [0, 0, 50, 80]),
                                                                          ("check_valve", None)]
        picked = ai_images.pick_samples([(page, spots)], {"manual_valve", "tank", "check_valve"})
        self.assertEqual([b for _, b in picked["manual_valve"]], [[0, 0, 10, 10]])
        self.assertNotIn("check_valve", picked)
        boards, kinds = ai_images.legend_boards([(page, spots)])
        self.assertEqual((len(boards), kinds), (1, ["manual_valve"]))  # tank는 늘려 그리는 종류라 답 목록에 없다

    def test_extra_samples_differ_in_shape_or_size(self):
        from hazop.extract import ai_images
        square = [("fan", [0, 0, w, w]) for w in (8, 9, 10, 11, 30, 32)]
        wide = [("fan", [0, 0, 3 * h, h]) for h in (5, 6, 7)]
        lone_tall = [("fan", [0, 0, 4, 20])]
        page = object()
        pick = lambda n: [b for _, b in ai_images.pick_samples([(page, square + wide + lone_tall)], {"fan"}, n)["fan"]]
        self.assertEqual(pick(1), [[0, 0, 10, 10]])
        self.assertEqual(pick(2), [[0, 0, 10, 10], [0, 0, 18, 6]], "둘째는 다른 가로세로비 무리의 가운데 크기")
        three = pick(3)
        self.assertEqual(three[:2], pick(2))
        self.assertNotIn([0, 0, 4, 20], three, "한 번만 나온 모양은 견본으로 싣지 않는다")
        self.assertEqual(len(three), 3)
        area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
        self.assertTrue(all(max(area(three[2]), area(b)) > 2 * min(area(three[2]), area(b)) for b in three[:2]))

    def test_legend_cells_repeat_kind_for_each_sample(self):
        from hazop.extract import ai_images

        class Page:
            def crop(self, bbox, pad=0, outline=True):
                from PIL import Image
                return Image.new("RGB", (max(1, int(bbox[2] - bbox[0])), max(1, int(bbox[3] - bbox[1]))), "white")

        spots = [("fan", [0, 0, w, w]) for w in (8, 10, 12)] + [("fan", [0, 0, 3 * h, h]) for h in (5, 6)]
        with mock.patch.object(ai_images, "board", side_effect=lambda cells: [n for n, _ in cells]):
            one, kinds = ai_images.legend_boards([(Page(), spots)], kinds=["fan"])
            two, kinds2 = ai_images.legend_boards([(Page(), spots)], kinds=["fan"], per_kind=2)
        self.assertEqual((one, kinds), ([["fan"]], ["fan"]))
        self.assertEqual((two, kinds2), ([["fan", "fan"]], ["fan"]))

    def test_match_marks_kind_candidates_high_or_normal(self):
        def answers(req):
            self.assertIn("match", req["schema"]["properties"]["answers"]["items"]["required"])
            out = []
            for it in ids_in(req):
                if it["task"] == "kind":
                    out.append({"item_id": it["item_id"], "field": "kind", "values": ["manual_valve"],
                                "confidence": 0.9, "reason": "x",
                                "match": "legend" if it["target"] == "n1" else "other"})
            return {"answers": out}
        ex = ex_fixture()
        ex["nodes"].append(node("n8", None, (600, 100, 610, 108)))
        doc = ar.run(ex, StubClient(answers), cap=5, recheck=0, images=self.images())
        got = {c["target"]: c["match"] for c in doc["candidates"] if c["field"] == "kind"}
        self.assertEqual(got, {"n1": "legend", "n8": "other"})
        check = ar.to_check_candidates(doc)["candidates"]
        self.assertEqual(sorted(c["match"] for c in check if c["field"] == "kind"), ["legend", "other"])
        self.assertNotIn("match", ar.schema()["properties"]["answers"]["items"]["properties"], "글 입력 스키마는 그대로")

    def test_missing_match_counts_as_normal(self):
        doc = ar.run(ex_fixture(), StubClient(good_answers), cap=5, recheck=0, images=self.images())
        self.assertTrue(all(c["match"] == "other" for c in doc["candidates"] if c["field"] == "kind"))
        self.assertTrue(all("match" not in c for c in doc["candidates"] if c["field"] != "kind"))

    def test_only_kind_tag_and_crop_per_item(self):
        stub = StubClient(good_answers)
        ar.run(ex_fixture(), stub, cap=5, images=self.images())
        asked = [it for req in stub.requests for it in ids_in(req)]
        self.assertEqual({it["task"] for it in asked}, {"kind", "tag"})
        for req in stub.requests:
            labels = [im["label"] for im in req["images"]]
            crops = [lb for lb in labels if lb.startswith("그림 ")]
            self.assertEqual(crops, ["그림 " + it["item_id"] for it in ids_in(req)])
            has_kind = any("kind" in it["ask"] for it in ids_in(req))
            self.assertEqual(any(lb.startswith("범례판") for lb in labels), has_kind)
            self.assertIn("범례판", req["system"])
            self.assertTrue(all(im["media_type"] == "image/png" for im in req["images"]))
        self.assertTrue(all(len(ids_in(r)) <= ar.IMAGE_BATCH for r in stub.requests))

    def test_kind_outside_viewer_list_is_dropped(self):
        def answers(req):
            return {"answers": [{"item_id": it["item_id"], "field": "kind", "values": ["check_valve"], "confidence": 0.9,
                                 "reason": "x"} for it in ids_in(req) if it["task"] == "kind"]}
        doc = ar.run(ex_fixture(), StubClient(answers), cap=5, recheck=0, images=self.images())
        self.assertEqual(doc["candidates"], [])
        self.assertGreater(doc["stats"]["dropped"], 0)
        doc = ar.run(ex_fixture(), StubClient(answers), cap=5, recheck=0, images=self.images(("check_valve",)))
        self.assertEqual([c["values"][0] for c in doc["candidates"]], ["check_valve"])

    def test_recorded_responses_replay_to_same_candidates(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        rec = providers.RecordingClient(StubClient(good_answers), tmp)
        first = ar.run(ex_fixture(), rec, cap=5, images=self.images())
        self.assertEqual(len(rec.calls), first["stats"]["calls"])
        self.assertTrue(all(c["images"] >= 1 for c in rec.calls))
        again = ar.run(ex_fixture(), providers.FixedCellsClient(tmp), cap=5, images=self.images())
        self.assertEqual(again["stats"]["errors"], 0)
        self.assertEqual(again["candidates"], first["candidates"])
        dead = StubClient(good_answers, errors=["limit_reached"] * 9)  # 다시 부르면 실패하는 안쪽
        resumed = providers.RecordingClient(dead, tmp)
        third = ar.run(ex_fixture(), resumed, cap=5, images=self.images())
        self.assertEqual((dead.requests, third["candidates"]), ([], first["candidates"]), "저장한 응답을 다시 씀")
        self.assertTrue(all(c["cached"] for c in resumed.calls))

    def test_fixed_key_follows_image_content(self):
        req = {"context": "c", "user": "u"}
        img = {"label": "그림 k-1", "media_type": "image/png", "data": "QUJD"}
        self.assertNotEqual(providers.fixed_key(req), providers.fixed_key(dict(req, images=[img])))
        self.assertNotEqual(providers.fixed_key(dict(req, images=[img])),
                            providers.fixed_key(dict(req, images=[dict(img, data="QUJE")])))

    def test_saved_response_is_not_reused_after_prompt_or_schema_change(self):
        """프롬프트(system)나 답 스키마가 바뀌면 같은 맥락이라도 저장한 응답을 다시 쓰지 않고 새로 묻는다."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        req = {"system": "판 1", "context": "c", "user": "u", "schema": {"type": "object"},
               "images": [{"label": "범례판 1/1", "media_type": "image/png", "data": "QUJD"}]}
        inner = StubClient(lambda r: {"answers": [r["system"]]})
        rec = providers.RecordingClient(inner, tmp)
        rec.analyze(req)
        for changed in (dict(req, system="판 2"), dict(req, schema={"type": "object", "required": ["match"]}),
                        dict(req, images=[dict(req["images"][0], data="QUJE")])):
            before = len(inner.requests)
            out = rec.analyze(changed)
            self.assertEqual(len(inner.requests), before + 1, "바뀐 요청은 새로 부름: %r" % sorted(changed))
            self.assertFalse(rec.calls[-1]["cached"])
            self.assertEqual(out["output"]["answers"], [changed["system"]])
        self.assertEqual(providers.FixedCellsClient(tmp).analyze(dict(req, system="판 3"))["error_kind"], "not_ready")
        again = rec.analyze(req)
        self.assertTrue(rec.calls[-1]["cached"])
        self.assertEqual(again["output"]["answers"], ["판 1"])

    def write_legacy(self, folder, request, output):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, providers.legacy_key(request) + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"output": output}, fh)

    def test_text_request_reads_folder_saved_with_previous_key(self):
        """사용자가 예전에 받아 둔 글 요청 고정 응답(이전 판 열쇠)은 그대로 읽히고, 이전 판 열쇠로 찾았다고 표시한다."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        req = {"system": "s", "context": "c", "user": "u", "schema": {"type": "object"}}
        self.write_legacy(tmp, req, {"answers": ["예전"]})
        res = providers.FixedCellsClient(tmp).analyze(req)
        self.assertEqual((res["status"], res["output"], res["legacy_key"]), ("completed", {"answers": ["예전"]}, True))
        self.assertEqual(providers.stored_keys(req), [providers.fixed_key(req), providers.legacy_key(req)])
        inner = StubClient(lambda r: {"answers": ["새로"]})
        rec = providers.RecordingClient(inner, tmp)
        self.assertEqual(rec.analyze(req)["output"], {"answers": ["예전"]})
        self.assertEqual((inner.requests, rec.calls[-1]["cached"], rec.calls[-1]["legacy_key"]), ([], True, True))

    def test_image_request_never_reads_previous_key(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        req = {"system": "s", "context": "c", "user": "u", "schema": {"type": "object"},
               "images": [{"label": "그림 k-1", "media_type": "image/png", "data": "QUJD"}]}
        self.write_legacy(tmp, req, {"answers": ["예전"]})
        self.assertEqual(providers.stored_keys(req), [providers.fixed_key(req)])
        self.assertEqual(providers.FixedCellsClient(tmp).analyze(req)["error_kind"], "not_ready")
        inner = StubClient(lambda r: {"answers": ["새로"]})
        rec = providers.RecordingClient(inner, tmp)
        self.assertEqual(rec.analyze(req)["output"], {"answers": ["새로"]})
        self.assertEqual(len(inner.requests), 1)
        self.assertTrue(os.path.isfile(os.path.join(tmp, providers.fixed_key(req) + ".json")), "저장은 새 열쇠로")

    def test_new_saves_use_new_key_and_run_counts_previous_key_hits(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        ex = ex_fixture()
        first = StubClient(good_answers)
        ar.run(ex, providers.RecordingClient(first, tmp), cap=5)
        names = sorted(n[:-5] for n in os.listdir(tmp))
        self.assertEqual(names, sorted(providers.fixed_key(r) for r in first.requests))
        for r in first.requests:  # 같은 응답을 이전 판 열쇠 이름으로만 남긴 폴더
            os.replace(os.path.join(tmp, providers.fixed_key(r) + ".json"), os.path.join(tmp, providers.legacy_key(r) + ".json"))
        doc = ar.run(ex, providers.FixedCellsClient(tmp), cap=5)
        self.assertEqual((doc["stats"]["errors"], doc["stats"]["legacy_key_hits"]), (0, len(first.requests)))


class AcceptTest(unittest.TestCase):
    """실제 SNP-M-102 PDF 추출(임시 작업 루트)에서 수락·되돌리기가 사람 수정 기록으로 들어가는지."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls._env = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop.extract.adapters import pdf_vector
        pdf = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]
        cls.ex = pdf_vector.extract(pdf, page=0, repo_root=os.environ["HAZOP_WORK_ROOT"])

    @classmethod
    def tearDownClass(cls):
        if cls._env is None:
            os.environ.pop("HAZOP_WORK_ROOT", None)
        else:
            os.environ["HAZOP_WORK_ROOT"] = cls._env
        shutil.rmtree(cls.tmp, True)

    def test_accept_then_revert(self):
        target = next(n for n in self.ex["nodes"] if n.get("kind") == "manual_valve")
        tag_before = target.get("tag")
        doc = ar.new_doc("acc-test", self.ex)
        doc["candidates"].append(ar.make_candidate("t-1", "tag", target, "tag", ["V999"], 0.95, "시험"))
        cid = doc["candidates"][0]["cand_id"]
        ar.accept(doc, [cid], self.ex, "acc-test", by="시험")
        self.assertEqual(doc["candidates"][0]["status"], "accepted")
        ops = corrections.load("acc-test")["ops"]
        self.assertEqual([o["op"] for o in ops], ["set_tag"])
        applied = corrections.apply(self.ex, ops)
        self.assertEqual(next(n for n in applied["nodes"] if n["source_object_id"] == target["source_object_id"])["tag"],
                         "V999")
        self.assertEqual(target.get("tag"), tag_before)  # 원본 추출은 그대로
        ar.revert(doc, [cid], "acc-test", by="시험")
        self.assertEqual(doc["candidates"][0]["status"], "proposed")
        self.assertEqual(corrections.load("acc-test")["ops"], [])

    def cand(self, i, n, tag):
        return ar.make_candidate("t-%d" % i, "tag", n, "tag", [tag], 0.95, "시험")

    def valves(self, k=3):
        return [n for n in self.ex["nodes"] if n.get("kind") and n.get("kind") != "tee"][:k]

    def test_decided_places_are_not_asked_again(self):  # 검토 8: 수락·거절한 자리는 다시 묻지 않는다
        name = "decided"
        items = [i for i in ar.collect_items(self.ex) if i["task"] in ("tag", "kind")][:2]
        self.assertEqual(len(items), 2)
        vals = {"kind": "manual_valve", "tag": "V990", "normal_position": "NO", "fail_position": "FC"}
        cands = [ar.make_candidate(i["item_id"], i["task"], i, i["ask"][0], [vals[i["ask"][0]]], 0.9, "") for i in items]
        doc = ar.new_doc(name, self.ex)
        ar.merge_run(doc, {"candidates": cands, "stats": {}})
        ar.save_doc(doc)
        before = ar.estimate_pages([(name, self.ex)])["pages"][0]["items"]
        ar.accept(doc, [cands[0]["cand_id"]], self.ex, name, by="시험")
        ar.reject(doc, [cands[1]["cand_id"]], by="시험")
        self.assertEqual(ar.decided_targets(name), {items[0]["target"], items[1]["target"]})
        self.assertEqual(ar.estimate_pages([(name, self.ex)])["pages"][0]["items"], before - 2)
        ar.revert(doc, [cands[1]["cand_id"]], name, by="시험")          # 되돌린 거절은 다시 물을 수 있다
        self.assertEqual(ar.decided_targets(name), {items[0]["target"]})

    def test_reconcile_follows_the_edit_record(self):  # A5 검토 R2: 사람이 도면 고치기에서 AI 연산을 되돌림·다시 함
        name, target = "reconcile", self.valves(1)[0]
        doc = ar.new_doc(name, self.ex)
        doc["candidates"].append(self.cand(1, target, "V951"))
        ar.save_doc(doc)
        ar.accept(doc, ["t-1:tag"], self.ex, name, by="시험")
        accepted = corrections.load(name)["ops"]
        corrections.save(name, [], "사람")                                # 도면 고치기의 되돌리기가 AI 연산을 뺌
        self.assertEqual(ar.reconcile(name), ["t-1:tag"])
        c = ar.load_doc(name)["candidates"][0]
        self.assertEqual((c["status"], c["op_id"], c["decided_by"]), ("proposed", None, ar.RECONCILED_BY))
        self.assertEqual(ar.reconcile(name), [])                         # 두 번째는 쓰지 않음
        corrections.save(name, accepted, "사람")                          # 다시 하기가 그 연산을 되살림
        self.assertEqual(ar.reconcile(name), ["t-1:tag"])
        c = ar.load_doc(name)["candidates"][0]
        self.assertEqual((c["status"], c["op_id"]), ("accepted", accepted[0]["op_id"]))
        self.assertEqual(ar.reconcile("no-such-doc"), [])

    def test_stale_window_accept_is_refused_and_keeps_new_run(self):  # 재현 [A]
        from hazop import store_io
        vs, name = self.valves(), "race-a"
        doc = ar.new_doc(name, self.ex)
        ar.merge_run(doc, {"candidates": [self.cand(1, vs[0], "V901"), self.cand(2, vs[1], "V902")], "stats": {}})
        ar.save_doc(doc)
        window = ar.load_doc(name)
        ar.merge_and_save(name, self.ex, {"candidates": [self.cand(3, vs[2], "V903")], "stats": {"calls": 1}})
        with self.assertRaises(store_io.Conflict):
            ar.accept(window, ["t-1:tag"], self.ex, name, by="시험")
        disk = ar.load_doc(name)
        self.assertEqual((len(disk["candidates"]), len(disk["runs"])), (3, 2))
        self.assertIsNone(corrections.load(name))  # 수정 기록도 쓰지 않았다

    def test_stale_worker_save_is_refused_and_merge_retries(self):  # 재현 [B]
        from hazop import store_io
        vs, name = self.valves(), "race-b"
        doc = ar.new_doc(name, self.ex)
        ar.merge_run(doc, {"candidates": [self.cand(1, vs[0], "V901"), self.cand(2, vs[1], "V902")], "stats": {}})
        ar.save_doc(doc)
        window, worker = ar.load_doc(name), ar.load_doc(name)
        ar.accept(window, ["t-2:tag"], self.ex, name, by="시험")
        ar.merge_run(worker, {"candidates": [], "stats": {"calls": 1}})
        with self.assertRaises(store_io.Conflict):
            ar.save_doc(worker)
        ar.merge_and_save(name, self.ex, {"candidates": [], "stats": {"calls": 1}})
        disk = ar.load_doc(name)
        c2 = next(c for c in disk["candidates"] if c["cand_id"] == "t-2:tag")
        self.assertEqual(c2["status"], "accepted")
        ops = corrections.load(name)["ops"]
        self.assertEqual([o["op_id"] for o in ops], [c2["op_id"]])
        ar.revert(disk, ["t-2:tag"], name, by="시험")
        self.assertEqual(corrections.load(name)["ops"], [])
        ar.accept(disk, ["t-2:tag"], self.ex, name, by="시험")
        self.assertEqual(len(corrections.load(name)["ops"]), 1)

    def test_accepted_op_is_marked_ai_with_who_and_when(self):  # 지적 11
        vs, name = self.valves(1), "mark"
        doc = ar.new_doc(name, self.ex)
        doc["candidates"].append(self.cand(1, vs[0], "V901"))
        ar.accept(doc, ["t-1:tag"], self.ex, name, by="검토자", at="2026-11-13T00:00:00Z")
        op = corrections.load(name)["ops"][0]
        self.assertEqual((op["origin"], op["accepted_by"], op["accepted_at"], op["ai_candidate"]),
                         ("ai", "검토자", "2026-11-13T00:00:00Z", "t-1:tag"))

    def test_human_correction_is_not_overwritten_or_reviewed(self):  # 재현 [C]
        n, name = self.valves(1)[0], "ovr"
        op = corrections.make_op(self.ex, "set_tag", n["source_object_id"], {"tag": "HUMAN1"}, "human", name=name)
        corrections.save(name, [op], "human")
        doc = ar.new_doc(name, self.ex)
        doc["candidates"].append(self.cand(1, n, "V777"))
        failed = ar.accept(doc, ["t-1:tag"], self.ex, name, by="시험")
        self.assertTrue(failed and "사람이 고친" in failed[0][1])
        applied = corrections.apply(self.ex, corrections.load(name)["ops"])
        self.assertEqual(next(x for x in applied["nodes"] if x["source_object_id"] == n["source_object_id"])["tag"],
                         "HUMAN1")
        self.assertIn(n["source_object_id"], ar.human_targets(name))
        asked = []
        client = StubClient(lambda req: (asked.extend(i["target"] for i in ids_in(req)), {"answers": []})[1])
        ar.run_many([(name, self.ex)], client, cap=5, save=False)
        self.assertNotIn(n["source_object_id"], asked)

    def test_save_and_load_doc(self):
        doc = ar.new_doc("store-test", self.ex)
        ar.save_doc(doc)
        self.assertEqual(ar.load_doc("store-test")["extraction_name"], "store-test")
        self.assertTrue(ar.store_path("store-test").startswith(paths.work_root()))

    def test_rerun_without_ai_gives_same_script_result(self):
        from hazop.extract.adapters import pdf_vector
        pdf = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]
        again = pdf_vector.extract(pdf, page=0, repo_root=os.environ["HAZOP_WORK_ROOT"])
        strip = lambda e: {k: e[k] for k in ("nodes", "relations", "unresolved_connectors")}
        self.assertEqual(strip(again), strip(self.ex))


class ReviewFixTest(unittest.TestCase):
    """R2 검토 반려 지적(2026-11-13) 재현을 시험으로 둔다."""

    def big_ex(self, n=60):
        ex = ex_fixture()
        for i in range(n):
            ex["nodes"].append(node("u%03d" % i, None, (1000 + i * 30, 100, 1010 + i * 30, 108)))
        return ex

    def test_completed_with_overage_or_limit_halts_but_keeps_answers(self):
        for ek in ("overage", "limit_reached"):
            class C:
                calls = 0

                def analyze(self, req):
                    C.calls += 1
                    return {"status": "completed", "error_kind": ek, "output": good_answers(req)}
            r = ar.run(self.big_ex(), C(), cap=20)
            self.assertEqual(r["stats"]["calls"], 1, ek)
            self.assertTrue(r["stats"]["halted"], ek)
            self.assertTrue(r["candidates"], ek)  # 받은 답은 반영한다

    def test_run_cap_over_pages_and_estimate(self):
        pages = [("p%d" % i, self.big_ex(60)) for i in range(3)]
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        old = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = tmp
        self.addCleanup(lambda: os.environ.__setitem__("HAZOP_WORK_ROOT", old) if old else os.environ.pop("HAZOP_WORK_ROOT"))
        client = StubClient(good_answers)
        done = ar.run_many(pages, client, cap=20, run_cap=5, save=False)
        self.assertEqual(sum(st["calls"] for _, _, st in done), 5)
        self.assertEqual(len(client.requests), 5)
        est = ar.estimate_pages(pages, cap=20, run_cap=5)
        self.assertEqual(est["calls"], 5)
        self.assertTrue(est["capped"])
        self.assertEqual(ar.RUN_CAP, 300)

    def test_estimate_from_real_pdf(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        pdf = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]
        est = ar.estimate_pdf(pdf, [0], cap=20)
        self.assertEqual(len(est["pages"]), 1)
        self.assertGreater(est["pages"][0]["items"], 0)
        self.assertGreaterEqual(est["calls"], 1)

    def test_bad_answers_are_dropped_without_stopping(self):
        def bad(req):
            out = []
            for it in ids_in(req):
                f = it["ask"][0]
                out.append({"item_id": it["item_id"], "field": f, "values": ["V200" + "X" * 50], "confidence": 0.9,
                            "reason": "R" * 5000})
                out.append({"item_id": it["item_id"], "field": f, "values": ["manual_valve"], "confidence": 7,
                            "reason": ""})
                out.append({"item_id": it["item_id"], "field": f, "values": ["manual_valve"], "confidence": "high",
                            "reason": ""})
                out.append({"item_id": it["item_id"], "field": "tag", "values": ["V999"], "confidence": 0.9,
                            "reason": ""})  # 주변 글자에 없는 태그
            return {"answers": out}
        r = ar.run(ex_fixture(), StubClient(bad), cap=5, recheck=0)
        self.assertEqual(r["candidates"], [])
        self.assertGreater(r["stats"]["dropped"], 0)

    def test_client_exception_does_not_lose_candidates(self):
        class X:
            n = 0

            def analyze(self, req):
                X.n += 1
                if X.n == 2:
                    raise OSError("pipe broken")
                return {"status": "completed", "error_kind": None, "output": good_answers(req)}
        r = ar.run(ex_fixture(), X(), cap=5, recheck=0, batch=2)
        self.assertEqual(r["stats"]["errors"], 1)
        self.assertTrue(r["candidates"])

    def test_api_connection_is_refused(self):
        class Api(StubClient):
            def describe(self):
                return {"via": "api"}
        c = Api(good_answers)
        r = ar.run(ex_fixture(), c, cap=5)
        self.assertIn("구독", r["stats"]["refused"])
        self.assertEqual(c.requests, [])

    def test_system_text_has_no_answer_key_or_sample_values(self):
        import check_read_quality as rq
        text = ar.system_text() + ar.build_request(ex_fixture(), [])["user"]
        values = set()
        for _, k in rq.load_keys():
            values |= {s.get("tag") for s in k["symbols"] if s.get("tag")}
            values |= {c.get("label") for c in k["continuations"] if c.get("label")}
        for f in glob.glob(os.path.join(paths.folder("references", "pid-samples"), "*", "*.drawio")):
            import extract_drawio
            ex, _ = extract_drawio.run_one(f, tempfile.mkdtemp())
            values |= {n.get("tag") for n in ex["nodes"] if n.get("tag")}
        hits = sorted(v for v in values if v and len(v) >= 3 and v in text)
        self.assertEqual(hits, [])
        self.assertIn("지시가 아니", text)


if __name__ == "__main__":
    unittest.main()
