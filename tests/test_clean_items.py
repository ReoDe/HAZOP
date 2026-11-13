"""정리된 보기가 그리는 데 더 쓰는 자료(hazop/shell/clean_items.py, docs/design/app-shell-web.md §10.1) 시험. 실행: python -m unittest tests.test_clean_items

가상 도면 SNP 6장에서 새 필드가 채워지는지, 방향·열린 끝·미확인 순서·AI 후보가 규격대로인지, 원래 `items`를 바꾸지 않는지 본다.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

from hazop.shell import clean_items, sheet_items  # noqa: E402

SNP = ("SNP-M-101", "SNP-M-102", "SNP-M-201", "SNP-M-301", "SNP-M-401", "SNP-M-501")
_CACHE = {}


def snp_extractions():
    if "ex" not in _CACHE:
        from scripts.check_edit_screen import install_sample
        tmp = tempfile.mkdtemp(prefix="hazop-clean-")
        old = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        try:
            from hazop.app import data
            out = {}
            for d in SNP:
                name = install_sample(os.environ["HAZOP_WORK_ROOT"], d)
                out[d] = data.load_extraction(name)[1]
            _CACHE["ex"] = out
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(tmp, ignore_errors=True)
    return copy.deepcopy(_CACHE["ex"])


def node(lid, kind, x, y, w, h, tag="T1", cat="valve", style="", cls="classified"):
    return {"local_id": lid, "classification": cls, "category": cat, "kind": kind, "tag": tag, "style": style,
            "geometry": {"x": x, "y": y, "width": w, "height": h}}


def rel(lid, a, b, status="connected", line_type="process", basis="source_to_target", way=()):
    return {"local_id": lid, "kind": "physical_connection", "line_type": line_type, "line_no": "L1", "waypoints": [list(p) for p in way],
            "endpoints": [{"end": "source", "node_local_id": a[0], "point": a[1], "status": "connected"},
                          {"end": "target", "node_local_id": b[0], "point": b[1], "status": status}],
            "flow_direction": {"basis": basis} if basis else None}


def extraction(nodes, relations, fmt="drawio"):
    return {"source": {"format": fmt}, "coordinate_system": {"svg_alignment": {"offset": [0, 0], "viewBox": "0 0 500 500"}}, "nodes": nodes,
            "relations": relations}


class SnpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ex = snp_extractions()
        cls.built = {d: clean_items.build(e) for d, e in cls.ex.items()}

    def test_every_symbol_and_pipe_item_has_its_new_fields_and_same_ids(self):
        for d, e in self.ex.items():
            items = sheet_items.build_items(e)["items"]
            extra = self.built[d]["items"]
            self.assertEqual({i["id"] for i in items}, set(extra), d)          # 같은 ID로 잇는다
            for it in items:
                x = extra[it["id"]]
                self.assertIn(x["review"], ("script", "human", "ai_candidate", "ai_accepted"))
                if it["layer"] == "symbol":
                    self.assertEqual(set(x["orient"]), {"rot", "flip_h", "flip_v", "basis"})
                else:
                    self.assertIn("line_type", x)
                    self.assertTrue(x["ends"])
                    self.assertIn(x["flow"], ("source_to_target", "target_to_source", None))

    def test_drawio_orient_comes_from_style_direction_and_flip(self):
        got = {}
        for d, e in self.ex.items():
            for n in e["nodes"]:
                o = self.built[d]["items"][n["local_id"]]["orient"]
                if "direction=south" in (n.get("style") or ""):
                    got["south"] = o
                if "direction=north" in (n.get("style") or ""):
                    got["north"] = o
                if "flipH=1" in (n.get("style") or "") and n.get("kind") == "continuation":
                    got["flip"] = o
        self.assertEqual(got["south"]["rot"], 90)
        self.assertEqual(got["north"]["rot"], 270)
        self.assertTrue(got["flip"]["flip_h"])
        self.assertEqual({o["basis"] for o in (got["south"], got["north"], got["flip"])}, {"drawio"})

    def test_pipe_line_types_flow_and_counts(self):
        types, flows = set(), set()
        for d in SNP:
            for i in self.built[d]["items"].values():
                if "line_type" in i:
                    types.add(i["line_type"])
                    flows.add(i["flow"])
        self.assertEqual(types, {"process", "process_secondary", "instrument_tap", "signal_electric"})
        self.assertIn("source_to_target", flows)
        self.assertIn(None, flows)
        for d in SNP:
            self.assertEqual(self.built[d]["source_format"], "drawio")
            c = self.built[d]["counts"]
            self.assertEqual(c["total"], sum(c[r] for r in clean_items.REASONS))

    def test_extraction_is_not_changed_and_build_items_is_unchanged(self):
        e = self.ex["SNP-M-101"]
        before, items = copy.deepcopy(e), sheet_items.build_items(e)
        clean_items.build(e)
        self.assertEqual(e, before)
        self.assertEqual(sheet_items.build_items(e), items)


class RuleTest(unittest.TestCase):
    def test_pdf_two_port_symbol_orient_from_pipe_axis(self):
        e = extraction([node("v", "manual_valve", 100, 100, 30, 50), node("a", "tee", 100, 0, 2, 2), node("b", "tee", 100, 300, 2, 2)],
                       [rel("p1", ("a", [115, 20]), ("v", [115, 100])), rel("p2", ("v", [115, 150]), ("b", [115, 300]))], fmt="pdf")
        b = clean_items.build(e)
        self.assertEqual(b["source_format"], "pdf_vector")
        self.assertEqual(b["items"]["v"]["orient"], {"rot": 90, "flip_h": False, "flip_v": False, "basis": "pipes"})
        h = extraction([node("v", "check_valve", 100, 100, 50, 30), node("a", "tee", 0, 110, 2, 2), node("b", "tee", 300, 110, 2, 2)],
                       [rel("p1", ("a", [10, 115]), ("v", [100, 115])), rel("p2", ("v", [150, 115]), ("b", [300, 115]))], fmt="pdf")
        self.assertEqual(clean_items.build(h)["items"]["v"]["orient"]["rot"], 0)

    def test_no_rotation_info_and_no_pipes_is_basis_none(self):
        e = extraction([node("v", "manual_valve", 100, 100, 30, 50)], [])
        self.assertEqual(clean_items.build(e)["items"]["v"]["orient"], {"rot": 0, "flip_h": False, "flip_v": False, "basis": "none"})
        t = extraction([node("v", "tank", 100, 100, 30, 50, cat="equipment", style="rotation=45;")], [])
        self.assertEqual(clean_items.build(t)["items"]["v"]["orient"]["rot"], 45)

    def test_unconfirmed_four_kinds_in_reading_order(self):
        e = extraction([node("u", None, 300, 40, 20, 20, cls="unclassified", cat=None, tag=""),
                        node("t", "manual_valve", 50, 200, 30, 30, tag=""),            # 태그 없음(밸브)
                        node("ok", "pump", 10, 10, 30, 30, tag="P1", cat="equipment"),
                        node("tee", "tee", 200, 300, 2, 2, tag="", cat="piping_element"),   # 태그 없는 tee는 세지 않는다
                        node("a", "pump", 10, 400, 30, 30, tag="P2", cat="equipment")],
                       [rel("open", ("ok", [40, 25]), ("a", [100, 100]), status="unknown")])
        with mock.patch.object(clean_items, "_ai_pending", lambda name: {"a": ["c1"]}):
            b = clean_items.build(e, "x")
        self.assertEqual([(u["id"], u["reason"]) for u in b["unconfirmed"]],
                         [("open", "open_end"), ("u", "unknown_symbol"), ("t", "missing_tag"), ("a", "ai_candidate")])   # 위→아래, 왼→오른
        self.assertEqual(b["counts"], {"unknown_symbol": 1, "open_end": 1, "missing_tag": 1, "ai_candidate": 1, "total": 4})
        self.assertEqual(b["items"]["a"]["review"], "ai_candidate")
        ends = {e["end"]: e["status"] for e in b["items"]["open"]["ends"]}
        self.assertEqual(ends, {"source": "connected", "target": "open"})      # 어느 끝이 열렸는지 안다

    def test_human_and_ai_accepted_review_and_independent_text(self):
        e = extraction([dict(node("h", "pump", 0, 0, 10, 10, tag="P", cat="equipment"), human_edit={"op_ids": ["o1"]}),
                        dict(node("g", "pump", 20, 0, 10, 10, tag="Q", cat="equipment"), origin="ai")], [])
        e["texts"] = [{"text": "NOTE 1", "bbox": [5, 5, 40, 10]}, {"text": "붙은 글자", "owner": "h", "bbox": [0, 0, 1, 1]}]
        b = clean_items.build(e)
        self.assertEqual((b["items"]["h"]["review"], b["items"]["g"]["review"]), ("human", "ai_accepted"))
        self.assertEqual(b["text_items"], [{"text": "NOTE 1", "bbox": [5, 5, 45, 15]}])

    def test_offset_is_subtracted_like_the_original_items(self):
        e = extraction([node("v", "manual_valve", 119, 119, 30, 50)], [])
        e["coordinate_system"]["svg_alignment"]["offset"] = [19, 19]
        e["texts"] = [{"text": "N", "bbox": [119, 119, 10, 10]}]
        self.assertEqual(clean_items.build(e)["text_items"][0]["bbox"], [100, 100, 110, 110])
        self.assertEqual(sheet_items.build_items(e)["items"][0]["bbox"], [100, 100, 130, 150])


class ReadRouteTest(unittest.TestCase):
    def test_read_route_gives_json_and_404_for_unknown_sheet(self):
        class Eng:
            def graph_names(self):
                return {"graph-A": "A"}
        e = extraction([node("v", "manual_valve", 0, 0, 10, 10)], [])
        with mock.patch("hazop.app.data.load_extraction", lambda name: (e, e)):
            r = clean_items.read(Eng(), ["clean", "graph-A"], {})
            self.assertEqual(json.loads(r.body.decode("utf-8"))["items"]["v"]["orient"]["basis"], "none")
            self.assertIsNone(clean_items.read(Eng(), ["clean", "graph-없음"], {}))
            self.assertIsNone(clean_items.read(Eng(), ["clean"], {}))


if __name__ == "__main__":
    unittest.main()
