"""추출 뒤 AI 검토(hazop.extract.ai_review) 시험. 실제 Claude를 부르지 않는다(가짜 클라이언트·고정 응답).

규격: docs/specs/extraction.md '읽기 품질 지표'의 AI 후보 규칙, INTENT.md §3.2(스크립트 우선, AI는 후보만).
작업 루트는 임시 폴더. 수락은 사람 수정 기록(hazop.extract.corrections)에 연산으로 들어가고 되돌리면 빠진다.
"""

import copy
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

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
            "texts": [text("LO", 98, 92), text("FAR", 900, 900)]}


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
        groups = ar.bulk_groups(doc, threshold=0.8)
        self.assertNotIn(low["cand_id"], [c for v in groups.values() for c in v])
        self.assertIn("kind", groups)
        self.assertNotIn("tag", groups)

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


class AcceptTest(unittest.TestCase):
    """실제 SNP-M-102 PDF 추출(임시 작업 루트)에서 수락·되돌리기가 사람 수정 기록으로 들어가는지."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls._env = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop.extract.adapters import pdf_vector
        pdf = glob.glob(os.path.join(REPO, "resources", "references", "pid-samples", "SNP-M-102*", "*.pdf"))[0]
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

    def test_save_and_load_doc(self):
        doc = ar.new_doc("store-test", self.ex)
        ar.save_doc(doc)
        self.assertEqual(ar.load_doc("store-test")["extraction_name"], "store-test")
        self.assertTrue(ar.store_path("store-test").startswith(paths.work_root()))

    def test_rerun_without_ai_gives_same_script_result(self):
        from hazop.extract.adapters import pdf_vector
        pdf = glob.glob(os.path.join(REPO, "resources", "references", "pid-samples", "SNP-M-102*", "*.pdf"))[0]
        again = pdf_vector.extract(pdf, page=0, repo_root=os.environ["HAZOP_WORK_ROOT"])
        strip = lambda e: {k: e[k] for k in ("nodes", "relations", "unresolved_connectors")}
        self.assertEqual(strip(again), strip(self.ex))


if __name__ == "__main__":
    unittest.main()
