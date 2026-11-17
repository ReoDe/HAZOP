"""연결 묻기(hazop.extract.ai_connect) 시험. 실제 Claude를 부르지 않는다(가짜 클라이언트).

대상 고르기, 번호표 조각, 답 검사, 원시 선 확인, 후보 꼴과 수락(add_relation), ai_review.run의 연결 몫(connect).
"""

import glob
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from hazop import paths
from hazop.extract import ai_connect as ac
from hazop.extract import ai_images
from hazop.extract import ai_review as ar
from hazop.extract import corrections


def node(sid, kind, box, tag=None):
    x0, y0, x1, y1 = box
    return {"local_id": "L" + sid, "source_object_id": sid, "kind": kind, "tag": tag, "label_text": "", "attributes": {},
            "geometry": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}}


def rel(rid, kind, a, b):
    return {"local_id": "L" + rid, "source_object_id": rid, "kind": kind,
            "endpoints": [{"end": "source", "node_local_id": a and "L" + a}, {"end": "target", "node_local_id": b and "L" + b}]}


def line(*pts, dash=False):
    return {"fill": False, "stroke": True, "fill_white": False, "stroke_white": False, "dash": dash,
            "subpaths": [(list(pts), False, list(pts), False)], "width": 1.0}


def dash_piece(x0, x1, y):
    pts = [(x0, y - 0.5), (x1, y - 0.5), (x1, y + 0.5), (x0, y + 0.5)]
    return {"fill": True, "stroke": False, "fill_white": False, "stroke_white": False, "dash": False,
            "subpaths": [(pts, True, pts, False)], "width": None}


def ex_fixture():
    nodes = [node("v1", "manual_valve", (200, 200, 212, 208), tag="V1"),    # 관계 0 → 대상
             node("v2", "check_valve", (300, 200, 312, 208)),               # 관계 있음
             node("p1", "pump", (100, 190, 130, 220), tag="PP01"),
             node("t1", "tee", (250, 203, 252, 205)),
             node("i1", "transmitter", (210, 150, 222, 162)),               # 계기: 대상도 이웃도 아님
             node("a1", "alarm", (400, 400, 410, 410)),                     # 신호 쪽 종류
             node("c1", "continuation", (500, 500, 530, 510)),              # 신호선이 닿은 도면 밖 연결 표기
             node("c2", "continuation", (600, 200, 630, 210)),              # 배관 없는 도면 밖 연결 표기 → 대상
             node("u1", None, (230, 230, 236, 236))]                        # 종류 없음
    return {"drawing": {"drawing_number": "T-1"}, "nodes": nodes,
            "relations": [rel("r1", "physical_connection", "v2", "p1"), rel("r2", "signal_connection", "c1", "i1")],
            "unresolved_connectors": [], "texts": []}


class FakePage(ai_images.PageImages):
    """흰 쪽(1224×792pt) 그림. 선 확인용 PDF는 없다."""

    def __init__(self):
        super().__init__("fake.pdf", 0)

    def image(self):
        from PIL import Image
        if self._img is None:
            self._img = Image.new("RGB", (int(1224 * self.scale), int(792 * self.scale)), "white")
        return self._img


class StubClient:
    def __init__(self, answer):
        self.answer, self.requests = answer, []

    def describe(self):
        return {"via": "fixed"}

    def analyze(self, request):
        self.requests.append(request)
        return {"status": "completed", "error_kind": None, "output": self.answer(request), "via": "fixed"}

    def cancel(self):
        pass


class TargetsTest(unittest.TestCase):
    def test_only_symbols_without_pipe_and_with_pipe_kind(self):
        self.assertEqual([n["source_object_id"] for n in ac.targets(ex_fixture())], ["c2", "v1"])

    def test_legend_page_asks_nothing(self):
        ex = ex_fixture()
        ex["texts"] = [{"text": "Flow Diagram Symbols and Legend (2 of 4)"}]
        self.assertEqual(ac.targets(ex), [])
        ex["texts"] = [{"text": "MISCELLANEOUS PIPING SPECIALTY SYMBOLS"}]
        self.assertEqual(ac.targets(ex), [])

    def test_partners_are_near_pipe_nodes_numbered_by_distance(self):
        ex = ex_fixture()
        v1 = ex["nodes"][0]
        ps = ac.partners(ex, v1, [50, 50, 362, 358])
        self.assertEqual([(p["no"], p["id"]) for p in ps], [(1, "t1"), (2, "p1"), (3, "v2")])  # 계기·종류 없음·영역 밖 빠짐

    def test_items_skip_targets_without_partners_and_excluded(self):
        page = FakePage()
        got = ac.items(ex_fixture(), page)
        self.assertEqual([i["item_id"] for i in got], ["z-v1"])  # c2는 둘레 150pt 안에 이웃이 없다
        self.assertEqual(ac.items(ex_fixture(), page, exclude={"v1"}), [])


class ParseTest(unittest.TestCase):
    item = {"partners": [{"no": 1, "id": "t1"}, {"no": 2, "id": "p1"}]}

    def test_none_numbers_and_bad_answers(self):
        self.assertEqual(ac.parse(self.item, {"links": ["none"], "confidence": 0.8}), ([], 0.8, ""))
        got = ac.parse(self.item, {"links": ["2", 1, "2"], "confidence": 0.7, "reason": "왼쪽"})
        self.assertEqual(([p["id"] for p in got[0]], got[1]), (["p1", "t1"], 0.7))
        for bad in ({"links": ["3"], "confidence": 0.9},           # 목록 밖 번호
                    {"links": ["none", "1"], "confidence": 0.9},   # none과 번호를 섞음
                    {"links": [], "confidence": 0.9},
                    {"links": ["1"], "confidence": 1.5},
                    {"links": "1", "confidence": 0.9}):
            self.assertIsNone(ac.parse(self.item, bad), bad)


class LinesTest(unittest.TestCase):
    A, B, C = [100, 100, 110, 110], [200, 100, 210, 110], [150, 100, 160, 110]

    def test_pipe_chain_with_bend_and_branch(self):
        L = ac.Lines([line((110, 105), (130, 105), (130, 150)), line((130, 150), (205, 150), (205, 110))])
        self.assertTrue(L.linked(self.A, self.B, area=[0, 0, 300, 300]))
        self.assertFalse(L.linked(self.A, self.B))  # 두 상자를 REACH만큼 넓힌 밖으로 돌아가는 사슬은 따라가지 않는다
        L = ac.Lines([line((110, 105), (140, 105)), line((140, 60), (140, 150)), line((140, 130), (200, 130), (205, 110))])
        self.assertTrue(L.linked(self.A, self.B))  # 내 끝이 남의 선 위(티)

    def test_one_pdf_line_through_several_symbols_keeps_pieces_between(self):
        L = ac.Lines([line((50, 105), (300, 105))])  # 한 줄이 A, C, B를 꿴다
        self.assertTrue(L.linked(self.A, self.C, blockers=[self.B]))
        self.assertFalse(L.linked(self.A, self.B, blockers=[self.C]))
        outline = ac.Lines([line((110, 105), (150, 105)), line((150, 100), (160, 100), (160, 110), (150, 110), (150, 100)),
                            line((160, 105), (200, 105))])
        self.assertFalse(outline.linked(self.A, self.B, blockers=[self.C]))  # 막는 기호의 테두리를 타고 넘지 않는다

    def test_other_symbol_on_the_way_cuts_the_chain(self):
        L = ac.Lines([line((110, 105), (200, 105))])
        self.assertTrue(L.linked(self.A, self.B))
        self.assertFalse(L.linked(self.A, self.B, blockers=[self.C]))

    def test_dash_pieces_join_only_across_small_gaps(self):
        near = ac.Lines([dash_piece(x, x + 4, 105) for x in range(110, 200, 5)])
        self.assertTrue(near.linked(self.A, self.B))
        far = ac.Lines([dash_piece(x, x + 4, 105) for x in range(110, 200, 8)])
        self.assertFalse(far.linked(self.A, self.B))
        stroke = ac.Lines([line((110, 105), (200, 105), dash=True)])
        self.assertTrue(stroke.linked(self.A, self.B))

    def test_no_chain_crossing_and_body_and_white_masks(self):
        self.assertFalse(ac.Lines([line((110, 105), (150, 105)), line((180, 105), (200, 105))]).linked(self.A, self.B))
        cross = ac.Lines([line((110, 105), (150, 105)), line((150, 105), (150, 300)), line((120, 200), (205, 200), (205, 110))])
        self.assertFalse(cross.linked(self.A, self.B))  # 끝이 닿지 않고 가로지르기만 한 선은 잇지 않는다
        body = ac.Lines([line((101, 101), (109, 109)), line((109, 109), (205, 109))])
        self.assertTrue(body.linked(self.A, self.B))  # 몸에서 이어진 바깥 선
        self.assertFalse(ac.Lines([line((101, 101), (109, 109))]).linked(self.A, self.B))
        white = dict(line((110, 105), (200, 105)), stroke_white=True)
        self.assertFalse(ac.Lines([white]).linked(self.A, self.B))


class CropTest(unittest.TestCase):
    def test_numbered_partners_are_drawn_in_blue(self):
        page = FakePage()
        item = ac.items(ex_fixture(), page)[0]
        img = ac.crop_image(page, item)
        ax, ay = item["area"][:2]
        blue = [(x, y) for x in range(img.width) for y in range(img.height) if img.getpixel((x, y)) == ac.BLUE]
        red = [1 for x in range(img.width) for y in range(img.height) if img.getpixel((x, y)) == ai_images.OUTLINE]
        self.assertTrue(red)
        p = item["partners"][1]  # p1 펌프
        b = [(v - o) * page.scale for v, o in zip(p["bbox"], (ax, ay, ax, ay))]
        self.assertTrue(any(abs(x - (b[0] - 2)) <= 1 and b[1] - 2 <= y <= b[3] + 2 for x, y in blue))
        req = ac.build_request(ex_fixture(), [item], page)
        ctx = json.loads(req["context"])["items"][0]
        self.assertEqual([q["no"] for q in ctx["partners"]], [1, 2, 3])
        self.assertNotIn("id", ctx["partners"][0])  # 번호만 보인다
        self.assertEqual(req["images"][0]["label"], "그림 z-v1")
        self.assertNotIn("tools", req)


def answers(links):
    def answer(req):
        return {"answers": [{"item_id": it["item_id"], "links": links, "confidence": 0.9, "reason": "오른쪽"}
                            for it in json.loads(req["context"])["items"]]}
    return answer


class RunTest(unittest.TestCase):
    def images(self):
        return ai_images.ImageInput(FakePage(), [b"legend"], kinds=["manual_valve", "pump"])

    def lines(self):
        # v1 → 오른쪽 티(t1)까지 배관, v1 → 펌프는 선 없음
        return ac.Lines([line((212, 204), (250, 204))])

    def run_ar(self, links, connect=4, ex=None):
        client = StubClient(lambda req: answers(links)(req) if "links" in json.dumps(req["schema"]) else {"answers": []})
        with mock.patch.object(ac.Lines, "from_pdf", return_value=self.lines()):
            doc = ar.run(ex or ex_fixture(), client, cap=5, recheck=0, images=self.images(), connect=connect)
        return doc, client

    def test_only_line_linked_neighbors_are_numbered_and_answer_becomes_candidate(self):
        doc, client = self.run_ar(["1"])
        req = next(r for r in client.requests if "links" in json.dumps(r["schema"]))
        self.assertEqual([p["no"] for p in json.loads(req["context"])["items"][0]["partners"]], [1])  # 펌프는 선이 없어 번호 없음
        conn = [c for c in doc["candidates"] if c["field"] == "connection"]
        self.assertEqual([(c["target"], c["values"], c["partner_local"]) for c in conn], [("v1", ["t1"], "Lt1")])
        self.assertEqual(conn[0]["attached_local"], ["Lv1"])
        self.assertNotIn("open_end", conn[0])
        st = doc["stats"]
        self.assertEqual((st["connect_items"], st["connect_calls"], st["connect_asked"], st["connect_links"]), (1, 1, 1, 1))
        fmt = ar.to_check_candidates(doc)["candidates"]
        self.assertIn({"field": "connection", "a": "Lv1", "b": "Lt1", "values": ["connected"]}, fmt)
        self.assertEqual(ar._op_for(conn[0]), ("add_relation", {"kind": "physical_connection", "line_type": "process",
                                                                "from": "v1", "to": "t1"}))

    def test_connect_candidate_is_never_bulk_but_open_end_still_is(self):
        doc, _ = self.run_ar(["1"])
        conn = next(c for c in doc["candidates"] if c["field"] == "connection")
        self.assertEqual(ar.bulk_block(dict(conn, confidence=0.99)), "연결 묻기 후보는 하나씩 확정함")
        self.assertNotIn(conn["cand_id"], sum(ar.bulk_groups({"candidates": [conn]}).values(), []))
        open_end = dict(conn, cand_id="c-r1:connection", open_end="target", confidence=0.99)
        self.assertIsNone(ar.bulk_block(open_end))

    def test_target_without_line_linked_neighbor_is_not_asked(self):
        with mock.patch.object(ac.Lines, "from_pdf", return_value=ac.Lines([])):
            self.assertEqual(ac.page_items(ex_fixture(), FakePage()), [])
        with mock.patch.object(ac.Lines, "from_pdf", side_effect=AssertionError("대상이 없으면 PDF를 읽지 않는다")):
            self.assertEqual(ac.page_items(ex_fixture(), FakePage(), exclude={"v1", "c2"}), [])

    def test_none_and_out_of_list_make_no_candidate(self):
        doc, _ = self.run_ar(["none"])
        self.assertEqual([c for c in doc["candidates"] if c["field"] == "connection"], [])
        self.assertEqual(doc["stats"]["connect_none"], 1)
        doc, _ = self.run_ar(["2"])  # 선이 없는 펌프는 번호가 없어 목록 밖
        self.assertEqual([c for c in doc["candidates"] if c["field"] == "connection"], [])
        self.assertEqual(doc["stats"]["dropped"], 1)

    def test_connect_off_keeps_requests_and_on_takes_share_from_first_pass(self):
        ex = ex_fixture()
        ex["nodes"] += [node("k%d" % i, None, (100 + 20 * i, 600, 108 + 20 * i, 608)) for i in range(30)]  # 종류 묻기 3묶음
        cap_calls = []
        for connect in (None, 0, 2):
            client = StubClient(lambda req: {"answers": []})
            kw = {} if connect is None else {"connect": connect}
            with mock.patch.object(ac.Lines, "from_pdf", return_value=self.lines()):
                doc = ar.run(ex, client, cap=3, recheck=0, images=self.images(), **kw)
            cap_calls.append((client.requests, doc["stats"]))
        (r_none, s_none), (r_off, s_off), (r_on, s_on) = cap_calls
        self.assertEqual(r_none, r_off)
        self.assertEqual(s_none, s_off)
        self.assertNotIn("connect_items", s_off)
        self.assertEqual(len(r_on), 3)
        self.assertEqual(s_on["planned_calls"], 2)  # 연결 묻기에 필요한 호출은 1이라 몫 2를 다 떼지 않는다
        self.assertEqual(s_on["connect_calls"], 1)
        self.assertEqual(r_on[:2], r_off[:2])


class AcceptTest(unittest.TestCase):
    """실제 SNP-M-102 추출에서 연결 후보 수락이 add_relation으로 들어가고 되돌리면 빠지는지."""

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

    def test_accept_adds_relation_and_revert_removes_it(self):
        a, b = [n for n in self.ex["nodes"] if n.get("kind") not in (None, "tee")][:2]
        item = {"target": a["source_object_id"], "local_id": a["local_id"], "bbox": ac._box(a)}
        cand = ar.make_candidate("z-x", "connection", item, "connection", [b["source_object_id"]], 0.9, "시험",
                                 {"cand_id": "z-x~y:connection", "attached_local": [a["local_id"]],
                                  "partner_local": b["local_id"]})
        doc = ar.new_doc("conn-test", self.ex)
        doc["candidates"].append(cand)
        self.assertEqual(ar.accept(doc, [cand["cand_id"]], self.ex, "conn-test", by="시험"), [])
        ops = corrections.load("conn-test")["ops"]
        self.assertEqual([(o["op"], o["target"], o["origin"]) for o in ops], [("add_relation", None, "ai")])
        applied = corrections.apply(self.ex, ops)
        new = [r for r in applied["relations"] if r["source_object_id"].startswith("manual-")]
        self.assertEqual([sorted(e["node_local_id"] for e in r["endpoints"]) for r in new],
                         [sorted([a["local_id"], b["local_id"]])])
        self.assertEqual(new[0]["kind"], "physical_connection")
        self.assertIn(a["source_object_id"], ar.decided_targets("conn-test"))
        ar.revert(doc, [cand["cand_id"]], "conn-test", by="시험")
        self.assertEqual(corrections.load("conn-test")["ops"], [])


if __name__ == "__main__":
    unittest.main()
