"""기호 사전과 모양 서명 매칭(hazop/extract/symbols.py, 기획서/PID-기호사전.md §4)."""

import importlib.util
import json
import math
import os
import shutil
import tempfile
import unittest
from unittest import mock

from hazop import paths
from hazop.analysis import explore
from hazop.extract import symbols
from hazop.extract.adapters import pdf_vector
from hazop.graph.build import build_graph
from hazop.graph.query import GraphQuery
from hazop.study import segment

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def body(pts, solid=False, curved=False, pid="pdf-path-0001"):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"id": pid, "pts": list(pts), "closed": True, "curved": curved, "solid": solid,
            "bbox": (min(xs), min(ys), max(xs), max(ys))}


def sig_of(bodies=(), strokes=(), markers=(), dashes=()):
    items = list(bodies) + list(strokes) + list(markers) + list(dashes)
    box = (min(i["bbox"][0] for i in items), min(i["bbox"][1] for i in items),
           max(i["bbox"][2] for i in items), max(i["bbox"][3] for i in items))
    return symbols.signature(list(bodies), list(strokes), list(markers), list(dashes), box)


BOWTIE_H = [(0, 0), (6, 3), (6, 0), (0, 3), (0, 0)]          # 가로 나비(게이트 밸브 몸통)
BOWTIE_V = [(0, 0), (3, 6), (0, 6), (3, 0), (0, 0)]          # 세로로 놓인 같은 기호
TRI_RIGHT = [(0, 0), (6, 3), (0, 6), (0, 0)]                  # 오른쪽을 향한 검은 삼각형
TRI_LEFT = [(6, 0), (0, 3), (6, 6), (6, 0)]


def entry(eid, sig, rotations="dihedral8", text=None, role="symbol", kind="manual_valve", enabled=True, extra=None):
    e = {"id": eid, "revision": 1, "added": "2026-11-09", "updated": "2026-11-09",
         "name": {"en": eid, "ko": eid}, "category": "밸브", "role": role, "kind": kind, "enabled": enabled,
         "match": [{"shape": "grid", "composition": dict(zip(
             ("closed_curved", "closed_straight", "solid", "strokes", "markers", "dashes"),
             (int(p[1:]) for p in sig.comp_key.split(".")))), "size_pt": list(sig.size), "rotations": rotations,
             "grid": symbols.grid_text(sig.cells)}], "sources": []}
    if text:
        e["text"] = text
    e.update(extra or {})
    return e


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, entries, bundle="T"):
        os.makedirs(os.path.join(self.tmp, bundle), exist_ok=True)
        with open(os.path.join(self.tmp, symbols.BUNDLES_FILE), "w", encoding="utf-8") as f:
            json.dump({"margin": 0.1, "bundles": [{"name": bundle}]}, f)
        for e in entries:
            with open(os.path.join(self.tmp, bundle, e["id"].split(".", 1)[1] + ".json"), "w", encoding="utf-8") as f:
                json.dump(e, f, ensure_ascii=False)
        return symbols.Library.load(self.tmp)


class SignatureTest(unittest.TestCase):
    def test_deterministic(self):
        a = sig_of([body(BOWTIE_H)])
        b = sig_of([body(BOWTIE_H)])
        self.assertEqual(a, b)
        self.assertEqual(a.comp_key, "C0.P1.F0.S0.M0.D0")
        self.assertEqual(a.size, (3, 6))

    def test_filled_outline_keeps_direction(self):
        """채운 도형은 상자가 아니라 윤곽 안을 칠한다. 방향만 다른 검은 삼각형은 서명이 다르다(검토 지적)."""
        right = sig_of(markers=[body(TRI_RIGHT, solid=True)])
        left = sig_of(markers=[body(TRI_LEFT, solid=True)])
        self.assertNotEqual(right.cells, left.cells)
        self.assertLess(len(right.cells), symbols.GRID * symbols.GRID // 2 + symbols.GRID * 2)

    def test_zero_size(self):
        z = sig_of([body([(5, 5), (5, 5), (5, 5), (5, 5)])])
        self.assertTrue(z.zero)

    def test_sample_subpaths_matches_extractor_split(self):
        obj = {"path": [("m", (0, 0)), ("c", (0, 2), (2, 4), (4, 4)), ("l", (4, 0)), ("h",), ("m", (9, 9)), ("l", (10, 9))]}
        fine = symbols.sample_subpaths(obj)
        self.assertEqual(len(fine), len(pdf_vector._subpaths(obj)))
        self.assertEqual(len(fine[0]), 1 + symbols.CURVE_SAMPLES + 1 + 1)
        self.assertEqual(fine[0][-1], fine[0][0])


class MatchTest(LibraryCase):
    def test_rotated_symbol_matches(self):
        lib = self.write([entry("t.gate", sig_of([body(BOWTIE_H)]))])
        m = lib.match(sig_of([body(BOWTIE_V)]))
        self.assertEqual((m.outcome, m.entry.id), ("matched", "t.gate"))
        self.assertLess(m.distance, 0.3)

    def test_rotation_none_rejects_other_direction(self):
        lib = self.write([entry("t.arrow", sig_of(markers=[body(TRI_RIGHT, solid=True)]), rotations="none")])
        self.assertEqual(lib.match(sig_of(markers=[body(TRI_RIGHT, solid=True)])).outcome, "matched")
        self.assertEqual(lib.match(sig_of(markers=[body(TRI_LEFT, solid=True)])).outcome, "none")

    def test_rotation_reported_or_symmetric(self):
        lib = self.write([entry("t.arrow", sig_of(markers=[body(TRI_RIGHT, solid=True)]))])
        m = lib.match(sig_of(markers=[body(TRI_RIGHT, solid=True)]))
        self.assertIn(m.rotation, ("r0", "symmetric"))
        self.assertEqual(m, lib.match(sig_of(markers=[body(TRI_RIGHT, solid=True)])))

    def test_identical_entries_are_ambiguous(self):
        s = sig_of([body(BOWTIE_H)])
        lib = self.write([entry("t.a", s), entry("t.b", s)])
        m = lib.match(s)
        self.assertEqual(m.outcome, "ambiguous")
        self.assertIsNone(m.entry)
        self.assertEqual([c for c, _ in m.candidates], ["t.a", "t.b"])

    def test_text_filters_candidates_before_ranking(self):
        s = sig_of([body(BOWTIE_H)])
        lib = self.write([entry("t.number", s, text={"inside": r"^\d{1,4}$"}),
                          entry("t.letters", s, text={"forbid_inside": r"^\d"})])
        self.assertEqual(lib.match(s, ["430"]).entry.id, "t.number")
        self.assertEqual(lib.match(s, ["FE"]).entry.id, "t.letters")
        self.assertEqual(lib.match(s).entry.id, "t.letters")

    def test_size_outside_ratio_is_none(self):
        lib = self.write([entry("t.gate", sig_of([body(BOWTIE_H)]))])
        big = sig_of([body([(x * 3, y * 3) for x, y in BOWTIE_H])])
        self.assertEqual(lib.match(big).outcome, "none")

    def test_disabled_entry_is_skipped(self):
        s = sig_of([body(BOWTIE_H)])
        lib = self.write([entry("t.gate", s, enabled=False)])
        self.assertEqual(lib.match(s).outcome, "none")

    def test_zero_size_entry(self):
        lib = self.write([dict(entry("t.zero", sig_of([body(BOWTIE_H)]), role="drop", kind=None),
                               match=[{"shape": "zero_size"}])])
        m = lib.match(sig_of([body([(5, 5), (5, 5), (5, 5), (5, 5)])]))
        self.assertEqual((m.outcome, m.entry.id), ("matched", "t.zero"))


class ReviewCaseTest(LibraryCase):
    """1단계 검토(Codex) 지적의 재현 사례."""

    def test_two_zero_size_entries_are_ambiguous(self):
        zero = [{"shape": "zero_size"}]
        lib = self.write([dict(entry("t.za", sig_of([body(BOWTIE_H)]), role="drop", kind=None), match=zero),
                          dict(entry("t.zb", sig_of([body(BOWTIE_H)]), role="drop", kind=None), match=zero)])
        m = lib.match(sig_of([body([(5, 5), (5, 5), (5, 5), (5, 5)])]))
        self.assertEqual((m.outcome, m.entry), ("ambiguous", None))

    def test_enabled_must_be_boolean(self):
        with self.assertRaises(symbols.SymbolLibraryError):
            self.write([entry("t.gate", sig_of([body(BOWTIE_H)]), enabled="false")])

    def test_non_finite_numbers_rejected(self):
        e = entry("t.gate", sig_of([body(BOWTIE_H)]))
        e["match"][0]["max_distance"] = float("nan")
        with self.assertRaises(symbols.SymbolLibraryError):
            self.write([e])

    def test_id_must_be_plain(self):
        self.write([])
        with open(os.path.join(self.tmp, "T", "victim.json"), "w", encoding="utf-8") as f:
            json.dump(entry("t.../../victim", sig_of([body(BOWTIE_H)])), f)
        with self.assertRaises(symbols.SymbolLibraryError):
            symbols.Library.load(self.tmp)

    def test_match_carries_template_attributes(self):
        white = sig_of([body(BOWTIE_H)])
        black = sig_of([body(BOWTIE_H, solid=True)])
        e = entry("t.gate", white, extra={"attributes": {"valve_type": "gate"}})
        e["match"].append(dict(entry("t.gate", black)["match"][0], set_attributes={"normal_position": "NC"}))
        lib = self.write([e])
        self.assertEqual(lib.match(white).attributes, {"valve_type": "gate"})
        self.assertEqual(lib.match(black).attributes, {"valve_type": "gate", "normal_position": "NC"})

    def test_version_follows_margin(self):
        s = sig_of([body(BOWTIE_H)])
        v1 = self.write([entry("t.gate", s)]).versions
        with open(os.path.join(self.tmp, symbols.BUNDLES_FILE), "w", encoding="utf-8") as f:
            json.dump({"margin": 0.0, "bundles": [{"name": "T"}]}, f)
        self.assertNotEqual(v1, symbols.Library.load(self.tmp).versions)


class AdversaryCaseTest(LibraryCase):
    """1단계 적대 검토 지적의 재현 사례."""

    def test_mirrored_templates_do_not_make_symmetric(self):
        corner = [(0, 0), (6, 0), (0, 4), (0, 0)]               # 직각삼각형: 어떤 회전·뒤집기에도 대칭이 아님
        s = sig_of(markers=[body(corner, solid=True)])
        mirrored = sig_of(markers=[body([(6 - x, y) for x, y in corner], solid=True)])
        e = entry("t.arrow", s)
        e["match"].append(entry("t.arrow", mirrored)["match"][0])
        m = self.write([e]).match(s)
        self.assertEqual(m.rotation, "r0")

    def test_fill_without_closepath_closes_outline(self):
        open_tri = dict(body(TRI_LEFT, solid=True), pts=TRI_LEFT[:-1], closed=False)
        self.assertEqual(sig_of(markers=[open_tri]).cells, sig_of(markers=[body(TRI_LEFT, solid=True)]).cells)

    def test_unknown_keys_and_ranges_rejected(self):
        s = sig_of([body(BOWTIE_H)])
        bad = []
        for comp in ({"filled": 1}, {"closed_stright": 1}, {"strokes": 7}):
            e = entry("t.gate", s)
            e["match"][0]["composition"] = comp
            bad.append(e)
        bad.append(entry("t.gate", s, text={"insde": "^M$"}))
        e = entry("t.gate", s)
        e["match"][0]["size_ratio"] = 0
        bad.append(e)
        for b in bad:
            shutil.rmtree(self.tmp)
            os.makedirs(self.tmp)
            with self.assertRaises(symbols.SymbolLibraryError, msg=json.dumps(b["match"][0].get("composition"))):
                self.write([b])

    def test_manifest_values_checked(self):
        s = sig_of([body(BOWTIE_H)])
        for meta in ({"margin": -1, "bundles": [{"name": "T"}]}, {"bundles": [{"name": "T", "active": "false"}]}):
            self.write([entry("t.gate", s)])
            with open(os.path.join(self.tmp, symbols.BUNDLES_FILE), "w", encoding="utf-8") as f:
                json.dump(meta, f)
            with self.assertRaises(symbols.SymbolLibraryError):
                symbols.Library.load(self.tmp)

    def test_gap_equal_to_margin_is_not_ambiguous(self):
        lib = self.write([entry("t.a", sig_of([body(BOWTIE_H)]))])
        ranked_gap = round(0.3 - 0.2, 6)
        self.assertFalse(ranked_gap < round(lib.margin, 6))


class LoadTest(LibraryCase):
    def test_missing_manifest_fails_loudly(self):
        with self.assertRaises(symbols.SymbolLibraryError):
            symbols.Library.load(self.tmp)

    def test_bad_entries_fail_loudly(self):
        s = sig_of([body(BOWTIE_H)])
        bad_grid = entry("t.gate", s)
        bad_grid["match"][0]["grid"] = ["#"]
        for bad in (bad_grid, dict(entry("t.gate", s), role="valve"), dict(entry("t.gate", s), id="x.gate")):
            shutil.rmtree(self.tmp)
            os.makedirs(self.tmp)
            with self.assertRaises(symbols.SymbolLibraryError):
                self.write([bad])

    def test_file_name_must_follow_id(self):
        self.write([entry("t.gate", sig_of([body(BOWTIE_H)]))])
        os.rename(os.path.join(self.tmp, "T", "gate.json"), os.path.join(self.tmp, "T", "other.json"))
        with self.assertRaises(symbols.SymbolLibraryError):
            symbols.Library.load(self.tmp)

    def test_version_follows_content(self):
        s = sig_of([body(BOWTIE_H)])
        v1 = self.write([entry("t.gate", s)]).versions
        self.assertEqual(v1, symbols.Library.load(self.tmp).versions)
        v2 = self.write([dict(entry("t.gate", s), revision=2)]).versions
        self.assertNotEqual(v1, v2)


def prim(pts, closed=True):
    return {"fill": False, "stroke": True, "fill_white": False, "stroke_white": False, "dash": None,
            "subpaths": [(pts, closed, pts, False)]}


GATE = [(100, 100), (106, 103), (106, 100), (100, 103), (100, 100)]     # APR1400 게이트 밸브: 나비 모양 한 경로
DOT = [(200, 200), (200, 200.27), (200, 200), (200, 200)]                # 탱크 무늬 점: 폭 0, 길이 0.27pt


def extract(prims):
    a = pdf_vector.analyze(400, 300, [], prims)
    return pdf_vector.build_extraction(a, 400, 300, 1, 0, "t.pdf", "0" * 64)


class PdfVectorLinkTest(unittest.TestCase):
    """추출기 연결(2단계): 기존 규칙이 못 정한 기호만 사전으로 정한다."""

    def test_unclassified_gate_valve_gets_kind_from_dictionary(self):
        ex = extract([prim(GATE), prim([(80, 101.5), (100, 101.5)], False), prim([(106, 101.5), (126, 101.5)], False)])
        valve = ex["nodes"][0]
        self.assertEqual((valve["kind"], valve["attributes"]), ("manual_valve", {"valve_type": "gate"}))
        self.assertEqual(valve["evidence"]["symbol_id"], "apr1400.gate_valve")
        self.assertEqual(valve["evidence"]["classification_basis"], "symbol:apr1400.gate_valve")

    def test_dropped_dot_keeps_other_node_numbers(self):
        ex = extract([prim(DOT), prim(GATE)])
        self.assertEqual([(n["local_id"], n["kind"]) for n in ex["nodes"]], [("local-node-001", "manual_valve")])
        self.assertEqual(ex["drawing"]["ignored_objects"][-1]["reason"], "symbol:common.pattern_dot")

    def test_pipe_cap_fallback_yields_to_dictionary(self):
        """연결 하나·글자 없는 작은 몸체(끝막음 뒤처리 규칙)라도 사전에 맞으면 사전이 정한다(2단계 검토)."""
        ex = extract([prim(GATE), prim([(80, 101.5), (100, 101.5)], False)])
        self.assertEqual(ex["nodes"][0]["kind"], "manual_valve")
        self.assertEqual(ex["nodes"][0]["evidence"]["symbol_id"], "apr1400.gate_valve")

    def test_dropped_dot_does_not_swallow_text(self):
        word = {"text": "TANK-NOTE", "x0": 202.0, "x1": 230.0, "top": 199.0, "bottom": 203.0, "size": 4.0, "upright": True}
        a = pdf_vector.analyze(400, 300, [word], [prim(DOT), prim(GATE)])
        ex = pdf_vector.build_extraction(a, 400, 300, 1, 0, "t.pdf", "0" * 64)
        self.assertIn("TANK-NOTE", [t.get("text") for t in ex["texts"]])

    def test_existing_rule_wins(self):
        """구조 규칙이 정한 기호(삼각형 둘 = 수동 밸브)는 격자 견본에 대 보지 않고, 근거에 symbol_id를 남기지 않는다."""
        ex = extract([prim([(0, 0), (5, 3), (0, 6), (0, 0)]), prim([(10, 0), (5, 3), (10, 6), (10, 0)])])
        self.assertEqual(ex["nodes"][0]["kind"], "manual_valve")
        self.assertNotIn("symbol_id", ex["nodes"][0]["evidence"])

    def test_dictionary_kind_outside_registry_fails_loudly(self):
        tmp = tempfile.mkdtemp()
        try:
            shutil.copytree(paths.folder("symbols"), os.path.join(tmp, "기호"))
            p = os.path.join(tmp, "기호", "APR1400", "gate_valve.json")
            with open(p, encoding="utf-8") as f:
                e = json.load(f)
            e["kind"] = "manual_valvee"
            with open(p, "w", encoding="utf-8") as f:
                json.dump(e, f, ensure_ascii=False)
            with mock.patch.object(pdf_vector, "_symbol_library", None), \
                    mock.patch.object(symbols.Library, "load", classmethod(
                        lambda cls, root=None, _load=symbols.Library.load.__func__: _load(cls, os.path.join(tmp, "기호")))):
                with self.assertRaises(symbols.SymbolLibraryError):
                    extract([prim(GATE)])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_dictionary_fails_loudly(self):
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.object(pdf_vector, "_symbol_library", None), \
                    mock.patch.dict(os.environ, {"HAZOP_RESOURCE_ROOT": tmp}):
                with self.assertRaises(symbols.SymbolLibraryError):
                    extract([prim(GATE)])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def ticks_at(xs, y=100.0, slant=1.0):
    """가로선 y 위 x마다 빗금 둘(//)을 1pt 간격으로 그린다."""
    out = []
    for x in xs:
        for dx in (0.0, 1.0):
            out.append(prim([(x + dx - 0.6 * slant, y + 1.0), (x + dx + 0.6 * slant, y - 1.0)], False))
    return out


class LineTickTest(unittest.TestCase):
    """신호선 빗금(//, 범례 1.7-1 4/4): 배관 위상에 넣지 않고 그 선을 공압 신호선으로 본다(3단계)."""

    def test_ticked_line_is_pneumatic_signal_without_junctions(self):
        ex = extract([prim(GATE, True), prim([(50, 100), (100, 100)], False)] + ticks_at((60, 80)))
        rels = [r for r in ex["relations"] + ex["unresolved_connectors"]]
        self.assertEqual({r["line_type"] for r in rels}, {"pdf_pneumatic"})
        self.assertEqual([n for n in ex["nodes"] if n["kind"] == "tee"], [])
        self.assertEqual(sum(1 for o in ex["drawing"]["ignored_objects"] if o.get("reason") == "line_tick"), 4)

    def test_perpendicular_marks_are_not_ticks(self):
        plates = [prim([(x, 98), (x, 102)], False) for x in (60, 61, 80, 81)]
        perp = extract([prim([(50, 100), (100, 100)], False)] + plates)
        self.assertFalse(any(o.get("reason") == "line_tick" for o in perp["drawing"]["ignored_objects"]))

    def test_touching_taps_are_not_ticks(self):
        """선에 한 끝만 닿은 45° 짧은 탭(계기 탭·가지)은 가로지르지 않으므로 빗금이 아니다(3a 검토)."""
        taps = [prim([(x, 100.0), (x + 1.2, 98.8)], False) for x in (60, 61, 80, 81)]
        ex = extract([prim([(50, 100), (100, 100)], False)] + taps)
        self.assertFalse(any(o.get("reason") == "line_tick" for o in ex["drawing"]["ignored_objects"]))
        self.assertFalse(any(r["line_type"] == "pdf_pneumatic" for r in ex["relations"] + ex["unresolved_connectors"]))

    def test_one_crowded_group_is_not_two_pairs(self):
        """빗금 넷이 한 자리에 몰리면(해칭) 독립된 // 묶음 둘이 아니다(3a 검토)."""
        crowd = [prim([(x - 0.6, 101.0), (x + 0.6, 99.0)], False) for x in (60, 60.8, 61.6, 62.4)]
        ex = extract([prim([(50, 100), (100, 100)], False)] + crowd)
        self.assertFalse(any(o.get("reason") == "line_tick" for o in ex["drawing"]["ignored_objects"]))

    def test_split_path_marks_only_the_ticked_piece(self):
        """빗금은 앞쪽에만 있는 꺾인 경로가 분기점에서 나뉘면 빗금 없는 뒤쪽 토막은 배관이다(3a 검토)."""
        path = prim([(50, 100), (100, 100), (100, 150)], False)
        branch = prim([(100, 120), (130, 120)], False)
        ex = extract([path, branch] + ticks_at((60, 80)))
        kinds = {}
        for r in ex["relations"] + ex["unresolved_connectors"]:
            pts = r["evidence"]["pdf_path"]
            kinds[(round(pts[0][1]), round(pts[-1][1]))] = r["line_type"]
        self.assertEqual(kinds.get((100, 120)) or kinds.get((120, 100)), "pdf_pneumatic")
        self.assertNotEqual(kinds.get((120, 150)) or kinds.get((150, 120)), "pdf_pneumatic")

    def test_junctions_have_no_missing_tag(self):
        ex = extract([prim([(0, 50), (100, 50)], False), prim([(50, 50), (50, 0)], False)])
        tees = {n["local_id"] for n in ex["nodes"] if n["kind"] == "tee"}
        self.assertTrue(tees)
        self.assertFalse([u for u in ex["validation"]["unknowns"] if u["check"] == "missing_tag" and u["target"] in tees])


def ticked(ex):
    return [o["source_object_id"] for o in ex["drawing"]["ignored_objects"] if o.get("reason") == "line_tick"]


def line_types(ex):
    return {r["line_type"] for r in ex["relations"] + ex["unresolved_connectors"]}


# APR1400 104쪽 (601.4,140.5)의 안전밸브 기호 그대로: 앵글 몸통, 몸통을 지나 모관까지 내려가는 줄기, 방출선, 모관.
# 같은 쪽의 주증기 안전밸브(MSSV)·주증기 대기방출밸브(MSADV) 기호도 같은 모양이다
SAFETY_VALVE = [prim([(599.81, 148.06), (601.45, 144.81), (604.72, 143.18), (604.72, 146.43), (601.45, 144.81), (603.09, 148.06)]),
        prim([(601.41, 136.98), (601.44, 156.21)], False),
        prim([(608.81, 144.81), (604.72, 144.81)], False), prim([(608.81, 139.47), (608.81, 144.81)], False),
        prim([(560.0, 156.21), (640.0, 156.21)], False)]
SAFETY_VALVE_SPRING = [prim([(599.81, 143.39), (603.09, 141.36)], False), prim([(599.81, 141.36), (603.09, 139.33)], False),
               prim([(599.81, 139.74), (603.09, 137.70)], False)]
# APR1400 023쪽 방출 밸브(번호 원 1014) 그대로: 삼각형 몸통, 짧은 줄기(2.65pt), 아래 플랜지 판과 배관
RELIEF = [prim([(340.05, 542.96), (343.85, 542.96), (343.85, 539.17), (340.05, 542.96)]),
          prim([(341.95, 538.41), (341.95, 541.06)], False),
          prim([(340.43, 544.86), (343.47, 544.86)], False), prim([(341.95, 560.03), (341.95, 544.85)], False)]
RELIEF_SPRING = [prim([(341.19, 539.88), (342.71, 538.41)], False), prim([(341.19, 540.47), (342.71, 539.0)], False),
                 prim([(341.19, 541.06), (342.71, 539.59)], False)]


class SafetyValveSpringTest(unittest.TestCase):
    """안전밸브 줄기를 가로지르는 스프링선 셋은 신호선 빗금이 아니다(범례 1.7-1 1/4). 바뀌면 안 되는 표본이다.
    3f에서 선에 하나뿐인 빗금 묶음을 모두 신호 표시로 지웠을 때 104쪽 안전밸브의 스프링선 둘이 지워졌고, 밸브는 연결을
    잃고 줄기는 공압 신호선이 됐다(docs/2026-11-11-unit-f1/README.md F1-4)."""

    def test_spring_on_a_long_stem_is_not_removed(self):
        ex = extract(SAFETY_VALVE + SAFETY_VALVE_SPRING)
        self.assertEqual(ticked(ex), [])
        self.assertNotIn("pdf_pneumatic", line_types(ex))
        self.assertNotIn("pipe_cap", [n["kind"] for n in ex["nodes"]])

    def test_relief_valve_keeps_its_spring_and_kind(self):
        ex = extract(RELIEF + RELIEF_SPRING)
        self.assertEqual(ticked(ex), [])
        valve = max(ex["nodes"], key=lambda n: len(n["evidence"]["pdf_objects"]))
        self.assertEqual((valve["kind"], valve["evidence"]["classification_basis"]), ("psv", "body+spring"))
        springs = {"pdf-path-%04d" % i for i in range(len(RELIEF), len(RELIEF) + len(RELIEF_SPRING))}
        self.assertLessEqual(springs, set(valve["evidence"]["pdf_objects"]))

    def test_three_strokes_on_one_line_are_left_alone(self):
        three = [prim([(x - 0.6, 101.0), (x + 0.6, 99.0)], False) for x in (60, 61, 62)]
        ex = extract([prim(GATE, True), prim([(50, 100), (100, 100)], False)] + three)
        self.assertEqual(ticked(ex), [])
        self.assertNotIn("pdf_pneumatic", line_types(ex))


class LoneTickTest(unittest.TestCase):
    """선에 빗금 묶음이 하나뿐일 때(F1-4): 빗금이 정확히 둘(//)이고 선이 빗금보다 길면 공압 신호 표시다(범례 1.7-1 4/4).
    계기 공기 공급선, I/P 변환기에서 구동부로 가는 선처럼 짧은 공압선에는 // 가 한 묶음만 들어간다."""

    def test_one_pair_marks_the_line_as_pneumatic(self):
        ex = extract([prim(GATE, True), prim([(50, 100), (100, 100)], False)] + ticks_at((60,)))
        self.assertEqual(line_types(ex), {"pdf_pneumatic"})
        self.assertEqual(len(ticked(ex)), 2)
        self.assertEqual([n for n in ex["nodes"] if n["kind"] == "tee"], [])

    def test_pair_on_a_line_shorter_than_ten_points_is_a_mark_too(self):
        """APR1400 028쪽 I/P 변환기(TY 970) 그대로: 계기 원과 구동부 쪽 삼각형을 잇는 6pt 공압선 위 // 한 묶음.
        신호선 빗금은 10pt 이상 선에서만 찾지만 이 묶음은 남겨 두면 선을 잘라 고리를 만든다."""
        air_line = [ring(465.28, 287.68, 5.27),
                    prim([(479.22, 290.32), (479.22, 285.05), (476.58, 287.69), (479.22, 290.32)]),
                    prim([(476.58, 287.69), (470.55, 287.69)], False)]
        pair = [prim([(474.46, 287.09), (473.27, 288.28)], False), prim([(473.87, 287.09), (472.67, 288.28)], False)]
        ex = extract(air_line + pair)
        self.assertEqual(len(ticked(ex)), 2)
        self.assertEqual(line_types(ex), {"pdf_pneumatic"})
        self.assertFalse([u for u in ex["validation"]["unknowns"] if u["check"] == "self_loop"])

    def test_pair_longer_than_the_line_it_crosses_is_not_a_mark(self):
        """143쪽 증기 트랩 기호: 2.7pt 선을 3.3pt 사선 둘이 가로지른다. 기호의 일부다."""
        strokes = [prim([(x - 1.2, 101.2), (x + 1.2, 98.8)], False) for x in (60.9, 61.7)]
        ex = extract([prim(GATE, True), prim([(60, 100), (62.7, 100)], False)] + strokes)
        self.assertEqual(ticked(ex), [])


def slash(x, y=100.0, half=0.6):
    """가로선 y를 x에서 가로지르는 빗금 하나(ticks_at의 한 줄과 같은 모양)."""
    return prim([(x - half, y + 1.0), (x + half, y - 1.0)], False)


def slanted(x, degrees, y=100.0, length=2.0):
    """가로선 y를 x에서 degrees 각도로 가로지르는 길이 length인 빗금."""
    dx = length / 2 * math.cos(math.radians(degrees))
    dy = length / 2 * math.sin(math.radians(degrees))
    return prim([(x - dx, y + dy), (x + dx, y - dy)], False)


LINE_TO_GATE = [prim(GATE, True), prim([(50, 100), (100, 100)], False)]


class LoneTickGuardTest(unittest.TestCase):
    """외톨이 // 판정이 넘어가면 안 되는 자리(F1-4 검토 지적). 헷갈리면 판정하지 않고 선을 그대로 둔다.
    스프링선이 하나 덜 읽히거나 둘로 그려져도 안전밸브 줄기가 공압 신호선이 되면 안 된다."""

    def test_stroke_on_a_crossing_of_two_lines_is_not_given_to_either(self):
        """두 선이 만나는 점 위의 빗금은 두 선에서 똑같이 가깝다. 먼저 그린 선에 붙이면 그리는 순서에 따라 판정이 달라진다."""
        a, b = prim([(50, 100), (100, 100)], False), prim([(60, 90), (60, 110)], False)
        strokes = [prim([(59, 101), (61, 99)], False), prim([(60, 101), (62, 99)], False)]
        results = [extract([prim(GATE, True)] + lines + strokes) for lines in ([a, b], [b, a])]
        self.assertEqual([len(ticked(ex)) for ex in results], [0, 0])
        self.assertEqual([("pdf_pneumatic" in line_types(ex)) for ex in results], [False, False])

    def test_strokes_beyond_the_end_of_a_line_do_not_mark_it(self):
        """선 끝점 밖(연장선 위)을 지나는 빗금은 그 선을 가로지르지 않는다."""
        ex = extract([prim(GATE, True), prim([(90, 100), (100, 100)], False), slash(89.9), slash(89.2)])
        self.assertEqual(ticked(ex), [])
        self.assertNotIn("pdf_pneumatic", line_types(ex))

    def test_third_stroke_a_little_further_along_is_still_a_third_stroke(self):
        """셋째 빗금이 묶음 거리(3pt)를 살짝 넘어 따로 떨어져도 그 선의 빗금은 셋이다."""
        ex = extract(LINE_TO_GATE + [slash(60), slash(61), slash(64.01)])
        self.assertEqual(ticked(ex), [])
        self.assertNotIn("pdf_pneumatic", line_types(ex))

    def test_third_stroke_too_long_to_be_a_tick_still_counts(self):
        """셋째 사선이 빗금 길이 상한(4pt)을 넘어 후보에서 빠져도 선 위에 사선이 셋 있는 것은 같다."""
        ex = extract(LINE_TO_GATE + [slash(60), slash(61), prim([(60.9, 102), (63.1, 98)], False)])
        self.assertEqual(ticked(ex), [])
        self.assertNotIn("pdf_pneumatic", line_types(ex))

    def test_third_stroke_at_another_angle_or_only_touching_still_counts(self):
        for third in (slanted(62, 88), slanted(62, 20), prim([(62.0, 100.0), (63.0, 98.6)], False)):
            ex = extract(LINE_TO_GATE + [slash(60), slash(61), third])
            self.assertEqual(ticked(ex), [], third["subpaths"][0][0])

    def test_four_strokes_beside_a_pair_block_it(self):
        """한 선에 // 한 묶음과 해칭(넷 이상)이 같이 있으면 판정하지 않는다."""
        hatch = [slash(x) for x in (80, 80.8, 81.6, 82.4)]
        ex = extract(LINE_TO_GATE + [slash(60), slash(61)] + hatch)
        self.assertEqual(ticked(ex), [])

    def test_line_joined_at_the_end_of_the_marked_line_does_not_block_it(self):
        """꺾이는 자리에서 끝을 맞댄 짧은 선은 빗금 비슷한 획이 아니다(솔레노이드 밸브 공기선의 ㄱ자 경로).
        116쪽처럼 맞댄 끝이 0.07pt 삐져나와 선을 넘어도 같다."""
        for corner in (prim([(50, 100), (50, 94)], False), prim([(50.06, 100.07), (50.06, 94.5)], False)):
            ex = extract(LINE_TO_GATE + [corner, slash(60), slash(61)])
            self.assertEqual(len(ticked(ex)), 2)

    def test_pair_drawn_across_a_corner_of_its_line_is_still_a_mark(self):
        """120쪽의 꼭짓점과 빗금 그대로(선의 왼쪽만 늘림): ㄱ자로 꺾인 공압선의 꼭짓점에 // 가 걸쳐 있다.
        한 줄은 꼭짓점 바로 밖을 지나 다음 선분과 만난다."""
        line = prim([(950.0, 259.26), (962.51, 259.26), (962.51, 252.62)], False)
        ends = [ring(962.51, 247.62, 5.0), ring(945.0, 259.26, 5.0)]
        pair = [prim([(963.15, 260.18), (961.85, 258.88)], False), prim([(963.15, 259.54), (961.85, 258.23)], False)]
        ex = extract(ends + [line] + pair)
        self.assertEqual(len(ticked(ex)), 2)
        self.assertEqual(line_types(ex), {"pdf_pneumatic"})

    def test_two_stroke_spring_on_a_safety_valve_stem_is_not_a_mark(self):
        """스프링선을 둘만 그린 안전밸브: 빗금이 밸브 몸통에 붙어 있으면 스프링 자리다."""
        ex = extract(SAFETY_VALVE + SAFETY_VALVE_SPRING[:2])
        self.assertEqual(ticked(ex), [])
        self.assertNotIn("pdf_pneumatic", line_types(ex))
        whole = extract(SAFETY_VALVE + SAFETY_VALVE_SPRING)
        self.assertEqual(len(ex["relations"]) + len(ex["unresolved_connectors"]),
                         len(whole["relations"]) + len(whole["unresolved_connectors"]) - 2)

    def test_two_stroke_spring_on_a_relief_valve_is_not_a_mark(self):
        ex = extract(RELIEF + RELIEF_SPRING[:2])
        self.assertEqual(ticked(ex), [])
        self.assertNotIn("pdf_pneumatic", line_types(ex))

    def test_two_strokes_drawn_on_top_of_each_other_are_not_a_pair(self):
        """141쪽 V1008 구동부 그대로: 같은 자리에 겹쳐 그린 줄기 두 줄이 V자 선의 꼭짓점을 지난다.
        나란히 떨어져 있지 않으면 // 가 아니다."""
        stems = [prim([(212.21, 276.44), (212.21, 273.41)], False), prim([(212.21, 275.93), (212.21, 273.48)], False)]
        rest = [prim([(212.21, 270.83), (212.21, 268.38)], False),
                prim([(214.01, 273.41), (212.21, 274.93), (210.4, 273.41)], False),
                prim([(208.82, 272.34), (208.82, 270.83), (215.6, 270.83), (215.6, 272.34)], False),
                prim([(208.82, 272.34), (209.95, 273.48), (211.08, 272.34)], False),
                prim([(211.08, 272.34), (212.21, 273.48), (213.34, 272.34)], False),
                prim([(213.34, 272.34), (214.47, 273.48), (215.6, 272.34)], False)]
        ex = extract(stems + rest)
        self.assertEqual(ticked(ex), [])
        self.assertNotIn("pdf_pneumatic", line_types(ex))


class TickBoundaryTest(unittest.TestCase):
    """빗금 판정의 경계값(F1-4 검토): 묶음 거리 3pt, 각도 30~80도는 경계를 포함한다."""

    def marked(self, strokes):
        return len(ticked(extract(LINE_TO_GATE + strokes)))

    def test_pair_gap_boundary(self):
        self.assertEqual(self.marked([slash(60), slash(63.0)]), 2)
        self.assertEqual(self.marked([slash(60), slash(63.01)]), 0)

    def test_angle_boundaries_are_inclusive(self):
        self.assertEqual(self.marked([slanted(60, 80.0), slanted(61, 80.0)]), 2)
        self.assertEqual(self.marked([slanted(60, 80.5), slanted(61, 80.5)]), 0)
        self.assertEqual(self.marked([slanted(60, 30.0), slanted(62, 30.0)]), 2)
        self.assertEqual(self.marked([slanted(60, 29.5), slanted(62, 29.5)]), 0)


def plate(x, y=100.0, half=1.5):
    return prim([(x, y - half), (x, y + half)], False)


def disc(x, y, r=0.95):
    pts = [(x + r, y), (x, y + r), (x - r, y), (x, y - r), (x + r, y)]
    return {"fill": True, "stroke": False, "fill_white": False, "stroke_white": False, "dash": None,
            "subpaths": [(pts, True, pts, True)]}


def butterfly(x0=70.0, y=100.0):
    """APR1400 028쪽 V1681 그대로: 플랜지 판 | 밸브 판 | 빗금·점 | 밸브 판 | 플랜지 판."""
    return [plate(x0, y), plate(x0 + 1.88, y), prim([(x0 + 2.64, y - 1.14), (x0 + 7.16, y + 1.12)], False),
            disc(x0 + 4.9, y), plate(x0 + 7.91, y), plate(x0 + 9.79, y)]


class PlateAssemblyTest(unittest.TestCase):
    """배관을 가로지르는 판(범례 1.7-1 FLANGED CONNECTION, BUTTERFLY·BALL): 판 조각이 배관을 자르지 않는다(3f)."""

    def rels(self, ex):
        return ex["relations"] + ex["unresolved_connectors"]

    def test_flanged_connection_joins_the_pipe(self):
        ex = extract([prim([(0, 100), (70, 100)], False), plate(70), plate(72), prim([(72, 100), (200, 100)], False)])
        self.assertEqual([n for n in ex["nodes"] if n["kind"] == "tee"], [])
        self.assertEqual(len(self.rels(ex)), 1)
        self.assertEqual(sum(o.get("reason") == "flange_plate" for o in ex["drawing"]["ignored_objects"]), 2)

    def test_butterfly_valve_is_one_symbol_between_two_pipes(self):
        ex = extract([prim([(50, 100), (70, 100)], False)] + butterfly() + [prim([(79.79, 100), (100, 100)], False)])
        valves = [n for n in ex["nodes"] if n["kind"] == "manual_valve"]
        self.assertEqual(len(valves), 1)
        self.assertEqual(valves[0]["attributes"], {"valve_type": "butterfly"})
        self.assertEqual([n for n in ex["nodes"] if n["kind"] == "tee"], [])
        ends = [e["node_local_id"] for r in self.rels(ex) for e in r["endpoints"]]
        self.assertEqual(ends.count(valves[0]["local_id"]), 2)
        self.assertFalse([u for u in ex["validation"]["unknowns"] if u["check"] == "self_loop"])

    def test_ball_valve_with_open_circle(self):
        ring = [(76 + 1.5 * math.cos(t / 8 * math.pi), 100 + 1.5 * math.sin(t / 8 * math.pi)) for t in range(17)]
        circle = {"fill": False, "stroke": True, "fill_white": False, "stroke_white": False, "dash": None,
                  "subpaths": [(ring, True, ring, True)]}
        ex = extract([prim([(50, 100), (73, 100)], False), plate(73), circle, plate(79), prim([(79, 100), (100, 100)], False)])
        valves = [n for n in ex["nodes"] if n["kind"] == "manual_valve"]
        self.assertEqual([v["attributes"] for v in valves], [{"valve_type": "ball"}])

    def test_orifice_stub_and_tapped_plates_are_left_alone(self):
        """판 사이에 짧은 선이 있으면(오리피스) 밸브도 플랜지도 아니고, 판 끝에 선이 닿으면(계기 탭) 잇지 않는다."""
        orifice = extract([prim([(50, 100), (70, 100)], False), plate(70), prim([(71.5, 100), (72.5, 100)], False),
                           plate(74), prim([(74, 100), (100, 100)], False)])
        self.assertFalse(any(o.get("reason") == "flange_plate" for o in orifice["drawing"]["ignored_objects"]))
        self.assertFalse(any(n["kind"] == "manual_valve" for n in orifice["nodes"]))
        tapped = extract([prim([(50, 100), (70, 100)], False), plate(70), plate(72), prim([(72, 100), (100, 100)], False),
                          prim([(72, 101.5), (72, 120)], False)])
        self.assertFalse(any(o.get("reason") == "flange_plate" for o in tapped["drawing"]["ignored_objects"]))

    def test_slash_drawn_in_two_halves_is_still_butterfly(self):
        parts = butterfly()
        parts[2] = prim([(72.64, 98.86), (74.9, 100)], False)
        parts.insert(3, prim([(74.9, 100), (77.16, 101.12)], False))
        ex = extract([prim([(0, 100), (70, 100)], False)] + parts + [prim([(79.79, 100), (200, 100)], False)])
        self.assertEqual([n["attributes"] for n in ex["nodes"] if n["kind"] == "manual_valve"],
                         [{"valve_type": "butterfly"}])

    def test_actuator_box_on_a_stem_is_not_a_pipe_cap(self):
        box = prim([(72, 86), (78, 86), (78, 90), (72, 90), (72, 86)])
        ex = extract([prim([(0, 100), (70, 100)], False)] + butterfly() + [prim([(79.79, 100), (200, 100)], False),
                                                                           prim([(74.9, 100), (74.9, 90)], False), box])
        self.assertFalse(any(n["kind"] == "pipe_cap" for n in ex["nodes"]))

    def test_actuator_stem_on_the_disc_does_not_break_the_valve(self):
        stem = prim([(74.9, 100), (74.9, 90)], False)
        m = [(74.9 + 3 * math.cos(t / 8 * math.pi), 87 + 3 * math.sin(t / 8 * math.pi)) for t in range(17)]
        motor = {"fill": False, "stroke": True, "fill_white": False, "stroke_white": False, "dash": None,
                 "subpaths": [(m, True, m, True)]}
        ex = extract([prim([(50, 100), (70, 100)], False)] + butterfly() + [prim([(79.79, 100), (100, 100)], False),
                                                                            stem, motor])
        valve = next(n for n in ex["nodes"] if n["attributes"] == {"valve_type": "butterfly"})
        self.assertIsNone(valve["kind"])  # 축 끝에 구동부(원)가 있으면 수동으로 정하지 않는다
        self.assertTrue(any(u["check"] == "actuated_valve_pending" and u["target"] == valve["local_id"]
                            for u in ex["validation"]["unknowns"]))

    def test_review_cases(self):
        """3f 검토(Codex)가 재현한 입력: 채운 마름모·판 사이 채운 조각·뒤집힌 판·밸브 뒤 진짜 끝막음."""
        pipe_l, pipe_r = prim([(0, 100), (73, 100)], False), prim([(79, 100), (200, 100)], False)
        diamond = [(76, 98.6), (77.4, 100), (76, 101.4), (74.6, 100), (76, 98.6)]
        filled = {"fill": True, "stroke": False, "fill_white": False, "stroke_white": False, "dash": None,
                  "subpaths": [(diamond, True, diamond, False)]}
        ex = extract([pipe_l, plate(73), filled, plate(79), pipe_r])
        self.assertFalse(any(n["attributes"].get("valve_type") == "ball" for n in ex["nodes"]))
        bar = {"fill": True, "stroke": False, "fill_white": False, "stroke_white": False, "dash": None,
               "subpaths": [([(70.8, 99.8), (71.2, 99.8), (71.2, 100.2), (70.8, 100.2), (70.8, 99.8)], True,
                             [(70.8, 99.8), (71.2, 99.8), (71.2, 100.2), (70.8, 100.2), (70.8, 99.8)], False)]}
        ex = extract([prim([(0, 100), (70, 100)], False), plate(70), bar, plate(72), prim([(72, 100), (200, 100)], False)])
        self.assertFalse(any(o.get("reason") == "flange_plate" for o in ex["drawing"]["ignored_objects"]))
        flipped = prim([(72, 101.5), (72, 98.5)], False)
        ex = extract([prim([(0, 100), (70, 100)], False), plate(70), flipped, prim([(72, 100), (200, 100)], False)])
        self.assertEqual(len(self.rels(ex)), 1)
        cap = prim([(110, 98), (113, 98), (113, 102), (110, 102), (110, 98)])
        after_valve = extract([prim([(0, 100), (70, 100)], False)] + butterfly()
                              + [prim([(79.79, 100), (110, 100)], False), cap])
        plain = extract([prim([(0, 100), (110, 100)], False), cap])
        end = lambda ex: [n["kind"] for n in ex["nodes"] if n["geometry"]["x"] >= 109]  # noqa: E731
        self.assertEqual(end(after_valve), end(plain))  # 배관 끝 기호는 앞의 판 밸브 때문에 종류가 바뀌지 않는다


def dot(x, y, r=0.55):
    pts = [(x - r, y - r), (x + r, y - r), (x + r, y + r), (x - r, y + r), (x - r, y - r)]
    return {"fill": True, "stroke": False, "fill_white": False, "stroke_white": False, "dash": None,
            "subpaths": [(pts, True, pts, False)]}


def dashed(pts, pattern=(5.867, 2.933)):
    return dict(prim(pts, False), dash=[list(pattern), 0.0])


class BuriedPipeTest(unittest.TestCase):
    """매설 배관 무늬(선 위 점, 범례 1.7-1 1/4 BURIED PIPE): 실선 위 점은 점선 조각이 아니다(3c)."""

    def test_dots_on_solid_line_are_dropped(self):
        ex = extract([prim([(50, 100), (150, 100)], False)] + [dot(x, 100) for x in (60, 70, 80, 90)])
        self.assertFalse([r for r in ex["relations"] + ex["unresolved_connectors"] if r["line_type"] == "pdf_dashed"])
        self.assertEqual(sum(1 for o in ex["drawing"]["ignored_objects"] if o.get("reason") == "line_dot"), 4)

    def test_lone_dot_and_offset_heat_tracing_dots_are_kept(self):
        lone = extract([prim([(50, 100), (150, 100)], False), dot(60, 100)])
        self.assertFalse(any(o.get("reason") == "line_dot" for o in lone["drawing"]["ignored_objects"]))
        tracing = extract([prim([(50, 100), (150, 100)], False)] + [dot(x, 102.5) for x in (60, 70, 80, 90)])
        self.assertFalse(any(o.get("reason") == "line_dot" for o in tracing["drawing"]["ignored_objects"]))

    def test_thin_diagonal_dashes_are_not_dots(self):
        """상자만 정사각형인 가는 대각 대시(점선 신호선 조각)는 점이 아니다(3c 검토)."""
        thin = []
        for x in (60, 70, 80):
            pts = [(x - 0.6, 100.6), (x - 0.5, 100.6), (x + 0.6, 99.4), (x + 0.5, 99.4), (x - 0.6, 100.6)]
            thin.append({"fill": True, "stroke": False, "fill_white": False, "stroke_white": False, "dash": None,
                         "subpaths": [(pts, True, pts, False)]})
        ex = extract([prim([(50, 100), (150, 100)], False)] + thin)
        self.assertFalse(any(o.get("reason") == "line_dot" for o in ex["drawing"]["ignored_objects"]))

    def test_dots_on_dashed_signal_line_are_kept(self):
        """점선 신호선의 분기점 점은 매설 배관 무늬가 아니다. 점선 위 점은 지우지 않고 선 종류도 그대로다(3c 검토)."""
        ex = extract([prim(GATE), prim([(130, 100), (136, 103), (136, 100), (130, 103), (130, 100)]),
                      dashed([(106, 101.5), (130, 101.5)])] + [dot(x, 101.5) for x in (113.3, 122.1)])
        self.assertFalse(any(o.get("reason") == "line_dot" for o in ex["drawing"]["ignored_objects"]))
        self.assertNotIn("physical_connection", {r["kind"] for r in ex["relations"] + ex["unresolved_connectors"]
                                                 if r["line_type"] == "pdf_dashed"})


def word(text, x0, top, size=3.0):
    return {"text": text, "x0": x0, "x1": x0 + 0.6 * size * len(text), "top": top, "bottom": top + size,
            "size": size, "upright": True}


class ArrowLabelTest(unittest.TestCase):
    """연결 표시 화살표와 겹치고 'SHEET'가 든 문단은 화살표로 들어가는 배관이 지나도 배관 글자가 아니다(3d, 10.3.2-1 S1)."""

    def test_arrow_keeps_its_sheet_paragraph(self):
        arrow = [(100, 100), (126, 100), (130, 103.5), (126, 107), (100, 107), (96, 103.5), (100, 100)]
        pipe = prim([(60, 103.5), (118, 103.5)], False)  # 실제 도면처럼 배관이 화살표 안 글자 밑까지 들어간다
        words = [word("DRAIN", 101, 96.2), word("TO", 111, 96.2), word("SHEET", 101, 102.0), word('2"K"', 112, 102.0),
                 word('2"', 88, 100.0)]
        a = pdf_vector.analyze(400, 300, words, [prim(arrow), pipe])
        ex = pdf_vector.build_extraction(a, 400, 300, 1, 0, "t.pdf", "0" * 64)
        arrows = [n for n in ex["nodes"] if n["kind"] == "continuation"]
        self.assertEqual(len(arrows), 1)
        self.assertIn("SHEET", arrows[0]["label_text"])


class IsaBubbleKindTest(unittest.TestCase):
    """기존 마지막 글자 규칙이 못 정한 계기 원만 ISA 기능 문자로 정한다(3e)."""

    def test_function_letters(self):
        cases = {"ZL\n202C": "indicator", "LG\n5": "indicator", "FICKS\n101": "controller",
                 "PISL\n101": "switch", "LEITS\n2": "transmitter", "PTAL\n3110A": "transmitter"}
        for text, kind in cases.items():
            self.assertEqual(pdf_vector._instrument_kind(text, 12.0)[0], kind, text)

    def test_thermowell_alarm_and_annotation_get_no_kind(self):
        # FE(원 안 검출부)는 배관 부품 kind로 두지 않는다. V(밸브)·설비 번호(RCP 1A)·PSE(파열판)도 계기 kind가 아니다(3e 검토)
        for text in ("TEW\n4", "TEWIS\n1", "PDAH\n032", "LL", "HHL", "NO", "SY\n019", "RE\n073A", "FE\n341A",
                     "PSV\n101", "PSE\n101", "PCV\n101", "FCV\n101", "RCP\n1A"):
            self.assertIsNone(pdf_vector._instrument_kind(text, 12.0)[0], text)

    def test_small_circle_and_existing_rule_unchanged(self):
        self.assertIsNone(pdf_vector._instrument_kind("ZL\n202C", 6.0)[0])
        self.assertEqual(pdf_vector._instrument_kind("TIS\n5", 12.0), ("switch", "isa_letters:TIS"))
        self.assertEqual(pdf_vector._instrument_kind("PT\n101"), ("transmitter", "isa_letters:PT"))


def rule_entry(eid, kind, match, role="symbol", extra=None):
    e = {"id": eid, "revision": 1, "added": "2026-11-11", "updated": "2026-11-11", "name": {"en": eid, "ko": eid},
         "category": "밸브", "role": role, "kind": kind, "match": match, "sources": []}
    e.update(extra or {})
    return e


def structure(requires, order, basis):
    return {"shape": "structure", "requires": list(requires), "order": order, "basis": basis}


def label_words(words, order):
    return {"shape": "label_words", "words": list(words), "order": order}


class RuleTemplateTest(LibraryCase):
    """구조 규칙·이름 낱말 규칙 견본(S7): 격자 대신 추출기가 본 구조 특징이나 라벨 낱말로 맞히고, order가 작은 것이 이긴다."""

    def test_lowest_order_whose_features_all_present_wins(self):
        lib = self.write([rule_entry("t.plain", "manual_valve", [structure(["bowtie"], 20, "valve_body")]),
                          rule_entry("t.motor", "motor_operated_valve",
                                     [structure(["bowtie", "outside_circle"], 10, "valve_body+circle_actuator")])])
        entry_, basis = lib.shape_rule({"bowtie", "outside_circle", "markers"})
        self.assertEqual((entry_.id, basis), ("t.motor", "valve_body+circle_actuator"))
        entry_, basis = lib.shape_rule({"bowtie"})
        self.assertEqual((entry_.id, basis), ("t.plain", "valve_body"))
        self.assertEqual(lib.shape_rule({"markers"}), (None, None))

    def test_label_words_need_every_word(self):
        lib = self.write([rule_entry("t.sg", "steam_generator", [label_words(["STEAM", "GENERATOR"], 10)]),
                          rule_entry("t.pump", "pump", [label_words(["PUMP"], 20)])])
        self.assertEqual(lib.word_rule(["STEAM", "GENERATOR", "FEED", "PUMP"])[0].id, "t.sg")
        self.assertEqual(lib.word_rule(["STEAM", "PUMP"])[0].id, "t.pump")
        self.assertEqual(lib.word_rule(["PUMP"])[1], ("PUMP",))
        self.assertEqual(lib.word_rule(["PUMPS"]), (None, None))

    def test_rule_templates_do_not_join_grid_matching(self):
        lib = self.write([rule_entry("t.plain", "manual_valve", [structure(["bowtie"], 20, "valve_body")])])
        self.assertEqual(lib.match(sig_of([body(BOWTIE_H)])).outcome, "none")

    def test_disabled_rule_is_skipped(self):
        lib = self.write([rule_entry("t.plain", "manual_valve", [structure(["bowtie"], 20, "valve_body")],
                                     extra={"enabled": False})])
        self.assertEqual(lib.shape_rule({"bowtie"}), (None, None))

    def test_bad_rule_templates_fail_loudly(self):
        bad = [structure(["bowtye"], 10, "valve_body"),          # 추출기가 내지 않는 특징 이름
               structure([], 10, "valve_body"),
               structure(["bowtie"], 10, ""),
               structure(["bowtie"], "10", "valve_body"),
               structure(["bowtie"], True, "valve_body"),
               label_words([], 10), label_words(["pump"], 10), label_words(["PUMP 1"], 10)]
        for template in bad:
            with self.assertRaises(symbols.SymbolLibraryError, msg=template):
                self.write([rule_entry("t.bad", "manual_valve", [template])])

    def test_same_basis_twice_fails_loudly(self):
        """노드에는 근거 글자(classification_basis)만 남는다. 두 구조 견본의 근거가 같으면 어느 항목이 정했는지 되짚을 수 없다."""
        with self.assertRaises(symbols.SymbolLibraryError) as ctx:
            self.write([rule_entry("t.a", "manual_valve", [structure(["bowtie"], 10, "valve_body")]),
                        rule_entry("t.b", "psv", [structure(["body_with_springs"], 20, "valve_body")])])
        self.assertIn("valve_body", str(ctx.exception))
        with self.assertRaises(symbols.SymbolLibraryError):
            self.write([rule_entry("t.a", "manual_valve", [structure(["bowtie"], 10, "valve_body"),
                                                           structure(["chevrons"], 20, "valve_body")])])
        lib = self.write([rule_entry("t.a", "manual_valve", [structure(["bowtie"], 10, "valve_body")]),
                          rule_entry("t.b", "psv", [structure(["body_with_springs"], 20, "valve_body")],
                                     extra={"enabled": False})])
        self.assertEqual(lib.shape_rule({"body_with_springs"}), (None, None))

    def test_missing_rule_shapes_names_what_the_dictionary_lacks(self):
        lib = self.write([entry("t.gate", sig_of([body(BOWTIE_H)]))])
        self.assertEqual(lib.missing_rule_shapes(), ["structure", "label_words"])
        lib = self.write([rule_entry("t.plain", "manual_valve", [structure(["bowtie"], 20, "valve_body")]),
                          rule_entry("t.off", "pump", [label_words(["PUMP"], 10)], extra={"enabled": False})])
        self.assertEqual(lib.missing_rule_shapes(), ["label_words"])
        lib = self.write([rule_entry("t.plain", "manual_valve", [structure(["bowtie"], 20, "valve_body")]),
                          rule_entry("t.pump", "pump", [label_words(["PUMP"], 10)])])
        self.assertEqual(lib.missing_rule_shapes(), [])

    def test_same_order_twice_fails_loudly(self):
        with self.assertRaises(symbols.SymbolLibraryError):
            self.write([rule_entry("t.a", "manual_valve", [structure(["bowtie"], 10, "valve_body")]),
                        rule_entry("t.b", "psv", [structure(["body_with_springs"], 10, "body+spring")])])
        with self.assertRaises(symbols.SymbolLibraryError):
            self.write([rule_entry("t.a", "pump", [label_words(["PUMP"], 10)]),
                        rule_entry("t.b", "tank", [label_words(["TANK"], 10)])])


class CommonRuleTest(unittest.TestCase):
    """공통 묶음으로 옮긴 형상 규칙과 장비 이름 낱말(S7). 기대값은 옮기기 전 코드(`_shape_kind`, `EQUIPMENT_WORDS`)가 내던 값이다."""

    SHAPES = [
        ({"plate_valve:butterfly"}, ("manual_valve", "plates+butterfly")),
        ({"plate_valve:ball", "bowtie", "outside_circle", "outside_body"}, ("manual_valve", "plates+ball")),
        ({"bowtie", "outside_circle", "outside_body"}, ("motor_operated_valve", "valve_body+circle_actuator")),
        ({"bowtie", "outside_body"}, ("control_valve", "valve_body+diaphragm_actuator")),
        ({"bowtie", "body_with_springs", "markers"}, ("manual_valve", "valve_body")),
        ({"body_with_springs", "single_circle"}, ("psv", "body+spring")),
        ({"stroke_only", "markers", "parallel_plates"}, ("check_valve", "lines+marker")),
        ({"stroke_only", "parallel_plates"}, ("orifice", "parallel_plates")),
        ({"single_circle", "single_tombstone", "chevrons"}, ("instrument", "circle")),
        ({"single_tombstone", "chevrons"}, ("instrument", "tombstone")),
        ({"chevrons", "markers"}, ("continuation", "chevron_arrow")),
        ({"stroke_only"}, (None, None)),
        ({"markers"}, (None, None)),
        (set(), (None, None)),
    ]
    WORDS = [
        (("REACTOR", "VESSEL"), "reactor_vessel"), (("STEAM", "GENERATOR"), "steam_generator"),
        (("PRESSURIZER",), "pressurizer"), (("CONDENSER",), "condenser"), (("TURBINE",), "turbine"),
        (("DEMINERALIZER",), "demineralizer"), (("FILTER",), "filter"), (("EXCHANGER",), "heat_exchanger"),
        (("HX",), "heat_exchanger"), (("COOLER",), "heat_exchanger"), (("PUMP",), "pump"), (("TANK",), "tank"),
        (("VENT",), "vent"), (("ATM",), "vent"),
    ]

    def old_word_rule(self, tokens):
        for words, kind in self.WORDS:
            if all(w in tokens for w in words):
                return kind, "text_word:%s" % "+".join(words)
        return None, None

    def test_shape_rules(self):
        lib = pdf_vector.symbol_library()
        for features, want in self.SHAPES:
            entry_, basis = lib.shape_rule(features)
            kind = None if entry_ is None else ("instrument" if entry_.kind_from == "isa_letters" else entry_.kind)
            self.assertEqual((kind, basis), want, sorted(features))

    def test_every_word_combination_gives_the_old_kind(self):
        vocab = sorted({w for words, _ in self.WORDS for w in words}) + ["FEED"]
        for mask in range(1 << len(vocab)):
            tokens = [w for i, w in enumerate(vocab) if mask >> i & 1]
            self.assertEqual(pdf_vector._kind_from_text(" ".join(tokens)), self.old_word_rule(tokens), tokens)

    def test_text_rules_through_the_adapter(self):
        self.assertEqual(pdf_vector._kind_from_text("Steam Generator\nfeed pump"),
                         ("steam_generator", "text_word:STEAM+GENERATOR"))
        self.assertEqual(pdf_vector._kind_from_text("TO M-102"), ("continuation", "text_to_from"))
        self.assertEqual(pdf_vector._kind_from_text("PUMPS"), (None, None))

    def test_adapter_features_are_the_dictionary_vocabulary(self):
        a = pdf_vector.analyze(400, 300, [], [prim([(0, 0), (5, 3), (0, 6), (0, 0)]),
                                              prim([(10, 0), (5, 3), (10, 6), (10, 0)])])
        features = pdf_vector._shape_features(a["symbols"][0], a["params"])
        self.assertEqual(features, {"bowtie"})
        self.assertLessEqual(features, set(symbols.STRUCTURE_FEATURES))
        self.assertEqual(pdf_vector._shape_rule(a["symbols"][0], a["params"]), ("manual_valve", "valve_body"))


def _member(pts, closed=True, curved=False, kind="body"):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"id": "pdf-path-0001", "pts": list(pts), "closed": closed, "curved": curved, "kind_": kind,
            "bbox": (min(xs), min(ys), max(xs), max(ys))}


def _line(a, b):
    return _member([a, b], closed=False, kind="poly")


def _sym(members, stroke_only=False, markers=(), plate_valve=None):
    sym = pdf_vector._Sym(list(members), stroke_only)
    if markers:
        sym.add(list(markers), "markers")
    if plate_valve:
        sym.plate_valve = plate_valve
    return sym


TRI_A = _member([(0, 0), (5, 3), (0, 6), (0, 0)])
TRI_B = _member([(10, 0), (5, 3), (10, 6), (10, 0)])
CIRCLE_ABOVE = _member([(3, -8), (7, -8), (7, -4), (3, -4), (3, -8)], curved=True)      # 나비 몸통 상자 밖의 원
CIRCLE_INSIDE = _member([(4, 2), (6, 2), (6, 4), (4, 4), (4, 2)], curved=True)          # 몸통 안 원(글로브 표시)
BOX_ABOVE = _member([(2, -8), (8, -8), (8, -5), (2, -5), (2, -8)])
BOX = _member([(0, 0), (8, 0), (8, 5), (0, 5), (0, 0)])
CIRCLE = _member([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)], curved=True)
TOMBSTONE = _member([(0, 13), (0, 5), (5, 0), (10, 5), (10, 13), (0, 13)], curved=True)  # 높이/폭 1.3
CHEVRON = _member([(0, 0), (20, 0), (25, 3), (20, 6), (0, 6), (5, 3), (0, 0)])
MARKER = _member([(4, 0), (6, 1), (4, 2), (4, 0)])


class OldShapeBranchTest(unittest.TestCase):
    """옛 `_shape_kind`의 가지마다 기호 하나를 만들어, 추출기의 구조 판정과 공통 묶음 견본이 함께 내는 (종류, 근거)가
    옮기기 전과 같은지 본다. 기대값은 옮기기 전 코드(ddb4c46)의 return 값을 그대로 적은 것이다."""

    CASES = [
        ("판 사이 원판", lambda: _sym([_line((0, 0), (0, 6))], True, plate_valve="butterfly"),
         ("manual_valve", "plates+butterfly")),
        ("판 사이 공", lambda: _sym([_line((0, 0), (0, 6))], True, plate_valve="ball"), ("manual_valve", "plates+ball")),
        ("나비 몸통 + 바깥 원", lambda: _sym([TRI_A, TRI_B, CIRCLE_ABOVE]),
         ("motor_operated_valve", "valve_body+circle_actuator")),
        ("나비 몸통 + 바깥 몸체", lambda: _sym([TRI_A, TRI_B, BOX_ABOVE]),
         ("control_valve", "valve_body+diaphragm_actuator")),
        ("나비 몸통", lambda: _sym([TRI_A, TRI_B]), ("manual_valve", "valve_body")),
        ("나비 몸통 + 안쪽 원", lambda: _sym([TRI_A, TRI_B, CIRCLE_INSIDE]), ("manual_valve", "valve_body")),
        ("몸체 + 같은 기울기 사선 둘", lambda: _sym([BOX, _line((1, 6), (3, 9)), _line((4, 6), (6, 9))]),
         ("psv", "body+spring")),
        ("몸체 + 기울기가 다른 사선 둘", lambda: _sym([BOX, _line((1, 6), (3, 9)), _line((4, 6), (6, 10))]), (None, None)),
        ("선 + 표식", lambda: _sym([_line((0, 0), (0, 6)), _line((0, 0), (4, 6))], True, markers=[MARKER]),
         ("check_valve", "lines+marker")),
        ("세로선 둘", lambda: _sym([_line((0, 0), (0, 6)), _line((2, 0), (2, 6))], True), ("orifice", "parallel_plates")),
        ("가로선 둘", lambda: _sym([_line((0, 0), (6, 0)), _line((0, 2), (6, 2))], True), ("orifice", "parallel_plates")),
        ("세로선 하나와 가로선 하나", lambda: _sym([_line((0, 0), (0, 6)), _line((0, 3), (6, 3))], True), (None, None)),
        ("원 하나", lambda: _sym([CIRCLE]), ("instrument", "circle")),
        ("비석 모양 하나", lambda: _sym([TOMBSTONE]), ("instrument", "tombstone")),
        ("오각 화살표", lambda: _sym([CHEVRON]), ("continuation", "chevron_arrow")),
        ("네모 하나", lambda: _sym([BOX]), (None, None)),
    ]

    def test_every_old_branch(self):
        for name, make, want in self.CASES:
            self.assertEqual(pdf_vector._shape_rule(make(), pdf_vector.PARAMS), want, name)


def _old_dictionary(dest, drop):
    """저장소 사전의 사본에서 drop 종류의 견본이 든 항목 파일을 뺀다(형상 규칙을 사전으로 옮기기 전 판의 꼴)."""
    shutil.copytree(paths.folder("symbols"), dest)
    removed = 0
    for folder, _, files in os.walk(dest):
        for fn in files:
            if not fn.endswith(".json") or fn == symbols.BUNDLES_FILE:
                continue
            with open(os.path.join(folder, fn), encoding="utf-8") as f:
                shapes = {t.get("shape") for t in json.load(f)["match"]}
            if shapes & set(drop):
                os.remove(os.path.join(folder, fn))
                removed += 1
    return removed


def _load_extract_pdf():
    spec = importlib.util.spec_from_file_location("extract_pdf_for_symbols",
                                                  os.path.join(REPO_ROOT, "scripts", "extract_pdf.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OldDictionaryTest(unittest.TestCase):
    """코드보다 옛 판 사전(구조·낱말 견본이 없음)을 읽으면 밸브·계기·설비 분류가 오류 없이 모두 빠진다(F1-1 검토 차단).
    추출기는 그런 사전으로는 시작하지 않는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def old_dictionary(self, drop):
        self.assertGreater(_old_dictionary(paths.folder_in(self.tmp, "symbols"), drop), 0)
        for patch in (mock.patch.object(pdf_vector, "_symbol_library", None),
                      mock.patch.dict(os.environ, {"HAZOP_RESOURCE_ROOT": self.tmp})):
            patch.start()
            self.addCleanup(patch.stop)

    def failure(self):
        with self.assertRaises(symbols.SymbolLibraryError) as ctx:
            extract([prim([(0, 0), (5, 3), (0, 6), (0, 0)]), prim([(10, 0), (5, 3), (10, 6), (10, 0)])])
        return str(ctx.exception)

    def test_dictionary_from_before_the_rules_moved_stops_extraction(self):
        self.old_dictionary(symbols.RULE_SHAPES)
        message = self.failure()
        self.assertIn("옛 판", message)
        self.assertIn("structure", message)
        self.assertIn("label_words", message)

    def test_missing_structure_rules_stop_extraction(self):
        self.old_dictionary(("structure",))
        self.assertIn("structure", self.failure())

    def test_missing_label_word_rules_stop_extraction(self):
        self.old_dictionary(("label_words",))
        self.assertIn("label_words", self.failure())

    def test_message_names_the_folder_that_was_read(self):
        root = os.path.join(self.tmp, "elsewhere")
        _old_dictionary(root, symbols.RULE_SHAPES)
        with self.assertRaises(symbols.SymbolLibraryError) as ctx:
            pdf_vector._check_has_rules(symbols.Library.load(root))
        self.assertIn(root, str(ctx.exception))
        self.assertNotIn(paths.folder("symbols"), str(ctx.exception))

    def test_multi_page_run_stops_before_touching_previous_results(self):
        self.old_dictionary(symbols.RULE_SHAPES)
        out = os.path.join(self.tmp, "out")
        kept = os.path.join(out, "page", "extraction.json")
        os.makedirs(os.path.dirname(kept))
        with open(kept, "w", encoding="utf-8") as f:
            f.write("{}")
        with self.assertRaises(symbols.SymbolLibraryError):
            _load_extract_pdf().run_pages(os.path.join(self.tmp, "none.pdf"), out, [0], out_name=lambda i: "page")
        with open(kept, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{}")


class RepoLibraryTest(unittest.TestCase):
    def test_repo_library_loads_and_checks(self):
        root = paths.folder("symbols")
        lib = symbols.Library.load(root)
        self.assertIn("APR1400", lib.versions)
        spec = importlib.util.spec_from_file_location("check_symbols", os.path.join(REPO_ROOT, "scripts", "check_symbols.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        errors, _, _ = mod.check(root)
        self.assertEqual(errors, [])



def ring(cx, cy, r):
    pts = [(cx + r * math.cos(t / 16 * math.pi), cy + r * math.sin(t / 16 * math.pi)) for t in range(33)]
    return {"fill": False, "stroke": True, "fill_white": False, "stroke_white": False, "dash": None,
            "subpaths": [(pts, True, pts, True)]}


class ActuatorMergeTest(unittest.TestCase):
    """S5(D6): 사전 구동부와 밸브 번호 원은 노드가 아니라 축·지시선으로 이어진 밸브 하나의 속성·근거다."""

    def run_page(self, extra_prims, words):
        prims = [prim(GATE, True), prim([(0, 101.5), (100, 101.5)], False),
                 prim([(106, 101.5), (200, 101.5)], False)] + extra_prims
        a = pdf_vector.analyze(400, 300, words, prims)
        return pdf_vector.build_extraction(a, 400, 300, 1, 0, "t.pdf", "0" * 64)

    def test_motor_operator_makes_motor_operated_valve(self):
        ex = self.run_page([ring(103, 94, 1.85), prim([(103, 95.85), (103, 101.5)], False)], [word("M", 102.4, 93.0, 2.0)])
        valves = [n for n in ex["nodes"] if n["kind"] == "motor_operated_valve"]
        self.assertEqual(len(valves), 1)
        self.assertEqual(valves[0]["attributes"].get("motive_power"), "electric")
        self.assertFalse([n for n in ex["nodes"] if n["evidence"].get("symbol_id") == "apr1400.motor_operator"])
        reasons = [o.get("reason") for o in ex["drawing"]["ignored_objects"]]
        self.assertIn("actuator_merged", reasons)
        self.assertFalse([u for u in ex["validation"]["unknowns"] if u["check"] == "actuated_valve_pending"])

    def test_valve_number_circle_becomes_evidence(self):
        ex = self.run_page([ring(90, 88, 4.5), prim([(93.2, 91.2), (99.6, 99.6)], False)], [word("302", 87.3, 86.5, 3.0)])
        self.assertTrue(any(n["evidence"].get("ident_number") == "302" for n in ex["nodes"]))
        self.assertFalse([n for n in ex["nodes"] if n["label_text"] == "302"])
        self.assertFalse([u for u in ex["validation"]["unknowns"] if u["check"] == "unconnected_endpoint"
                          and u["source_object_id"] and "conn" in u["source_object_id"]
                          and any(o["source_object_id"] == u["source_object_id"]
                                  for o in ex["drawing"]["ignored_objects"])])

    def test_number_circle_between_two_valves_is_left_alone(self):
        second = [(100, 80), (106, 83), (106, 80), (100, 83), (100, 80)]
        ex = self.run_page([prim(second, True), ring(90, 88, 4.5), prim([(93.2, 91.2), (95, 93)], False)],
                           [word("302", 87.3, 86.5, 3.0)])
        self.assertFalse(any(n["evidence"].get("ident_number") for n in ex["nodes"]))

    def test_solenoid_alone_is_not_merged(self):
        """솔레노이드 혼자는 스프링 복귀·복동 실린더의 파일럿일 수 있어 kind를 올리지 않는다(범례 4/4, S5 검토)."""
        box = prim([(101.5, 92.5), (104.5, 92.5), (104.5, 95.5), (101.5, 95.5), (101.5, 92.5)])
        ex = self.run_page([box, prim([(103, 95.5), (103, 101.5)], False)], [word("S", 102.5, 93.0, 2.0)])
        self.assertFalse(any(n["kind"] == "solenoid_valve" for n in ex["nodes"]))
        self.assertNotIn("actuator_merged", [o.get("reason") for o in ex["drawing"]["ignored_objects"]])

    def test_two_numbers_on_one_valve_are_left_alone(self):
        ex = self.run_page([ring(90, 88, 4.5), prim([(93.2, 91.2), (99.6, 99.6)], False),
                            ring(116, 88, 4.5), prim([(112.8, 91.2), (106.4, 99.6)], False)],
                           [word("302", 87.3, 86.5, 3.0), word("303", 113.3, 86.5, 3.0)])
        self.assertFalse(any(n["evidence"].get("ident_number") for n in ex["nodes"]))
        self.assertEqual(sorted(n["label_text"] for n in ex["nodes"] if n["label_text"] in ("302", "303")),
                         ["302", "303"])


def filled(pts, curved=False):
    return {"fill": True, "stroke": False, "fill_white": False, "stroke_white": False, "dash": None,
            "subpaths": [(pts, True, pts, curved)]}


def filled_dot(cx, cy, r):
    return filled([(cx + r * math.cos(t / 16 * math.pi), cy + r * math.sin(t / 16 * math.pi)) for t in range(33)], True)


def pipe(a, b):
    return prim([a, b], False)


BLACK_GATE = [(100, 100), (106, 103), (106, 100), (100, 103)]           # 채운 나비 하나(6×3pt): 표식 크기
GATE_PIPES = [pipe((80, 101.5), (100, 101.5)), pipe((106, 101.5), (126, 101.5))]
# 012쪽 418번 밸브: 채운 삼각형 둘과 가운데 점
BLACK_GLOBE = [filled([(181.6, 270.3), (179.3, 265.6), (183.9, 265.6)]),
               filled([(179.3, 274.9), (181.6, 270.3), (183.9, 274.9)]), filled_dot(181.6, 270.3, 1.2)]
GLOBE_PIPES = [pipe((181.6, 250.0), (181.6, 265.6)), pipe((181.6, 274.9), (181.6, 290.0))]


# 닫힌 밸브 양옆의 열린 게이트 밸브. 경로 분석의 출발점과 도착점으로 쓴다
OPEN_LEFT = prim([(60, 100), (66, 103), (66, 100), (60, 103), (60, 100)])
OPEN_RIGHT = prim([(140, 100), (146, 103), (146, 100), (140, 103), (140, 100)])
OUTER_PIPES = [pipe((66, 101.5), (100, 101.5)), pipe((106, 101.5), (140, 101.5))]


def closed_nodes(ex):
    return [n for n in ex["nodes"] if n["attributes"].get("normal_position") == "NC"]


def node_at_x(ex, x):
    (n,) = [n for n in ex["nodes"] if n["geometry"]["x"] <= x <= n["geometry"]["x"] + n["geometry"]["width"]
            and "-sym-" in n["source_object_id"]]
    return n


def path_between_open_valves(ex):
    """왼쪽 열린 밸브에서 오른쪽 열린 밸브까지의 경로 분석 결과(⑤ 분석이 쓰는 hazop.analysis.explore)."""
    graph = build_graph(ex)
    query = GraphQuery(graph)
    start, goal = (query.resolve(node_at_x(ex, x)["local_id"]) for x in (63, 143))
    members = explore.region_members(graph, [n["entity_id"] for n in graph["nodes"] if n["node_type"] != "pipe_segment"])
    found = explore.explore(query, start, members, ["has_endpoint"], 20, 100)
    return next(r for r in found["reached"] if r["entity_id"] == goal), graph


def pipe_ends_on(ex, node):
    """이 노드에 닿은 배관 끝. 반대쪽 끝이 뜬 배관은 미해결 연결로 남는다."""
    return [e for r in ex["relations"] + ex["unresolved_connectors"] if r["kind"] == "physical_connection"
            for e in r["endpoints"] if e["node_local_id"] == node["local_id"]]


class FarApartTrianglesTest(unittest.TestCase):
    """나비 구조 규칙(삼각형 몸체 둘 = 밸브 몸통)은 두 삼각형이 붙어 있을 때만 쓴다. 큰 묶음 기호 안에 멀리 떨어진 삼각형이
    우연히 둘 남으면 그 기호가 밸브가 되고, 밸브 상자 안 글자를 표기로 가져가 안쪽 계기의 글자를 빼앗는다(132쪽)."""

    FRAME = prim([(20, 20), (220, 20), (220, 120), (20, 120), (20, 20)])
    FAR = [prim([(20, 20), (26, 23), (20, 26), (20, 20)]), prim([(220, 114), (214, 117), (220, 120), (220, 114)])]
    LETTERS = [word("TI", 118.2, 65.0), word("101", 117.3, 68.5)]

    def run_page(self, prims):
        a = pdf_vector.analyze(400, 300, self.LETTERS, prims)
        return pdf_vector.build_extraction(a, 400, 300, 1, 0, "t.pdf", "0" * 64)

    def test_two_triangles_far_apart_in_one_large_symbol_are_not_a_valve_body(self):
        (big,) = self.run_page([self.FRAME] + self.FAR)["nodes"]
        self.assertIsNone(big["kind"])

    def test_letters_inside_that_symbol_are_not_taken_as_valve_marks(self):
        """밸브로 읽히면 상자 안 글자가 모두 밸브 표기(symbol_marks)가 되어 다른 기호의 라벨·태그로 쓰이지 못한다."""
        (big,) = self.run_page([self.FRAME] + self.FAR)["nodes"]
        self.assertEqual((big["evidence"]["symbol_marks"], big["label_text"].split()), ([], ["TI", "101"]))

    def test_triangles_with_a_ball_between_them_are_still_a_valve_body(self):
        """글로브·볼 밸브는 두 삼각형 사이에 점이 끼어 꼭짓점이 떨어져 있다. 간격이 삼각형 크기보다 작으면 나비다."""
        ex = extract([prim([(0, 0), (4, 3), (0, 6), (0, 0)]), prim([(10, 0), (6, 3), (10, 6), (10, 0)]), ring(5, 3, 1.0)])
        self.assertEqual([n["kind"] for n in ex["nodes"]], ["manual_valve"])


class ClosedValveTest(unittest.TestCase):
    """검게 칠한 밸브 몸통은 정상 운전 중 닫힘이다(APR1400 범례 1.7-1 1/4). 작은 검은 채움을 화살촉으로만 보면 그 자리에
    밸브 없이 배관이 이어진다. 사전의 검정 견본에 맞는 묶음만 밸브로 읽고, 그 밖의 검은 채움은 그대로 둔다."""

    def test_small_filled_bowtie_is_a_closed_gate_valve_between_its_pipes(self):
        ex = extract([filled(BLACK_GATE)] + GATE_PIPES)
        (valve,) = closed_nodes(ex)
        self.assertEqual((valve["kind"], valve["attributes"]),
                         ("manual_valve", {"normal_position": "NC", "valve_type": "gate"}))
        self.assertEqual(valve["evidence"]["symbol_id"], "apr1400.gate_valve")
        self.assertEqual(len(pipe_ends_on(ex, valve)), 2)
        self.assertEqual(len(ex["relations"] + ex["unresolved_connectors"]), 2)  # 밸브를 건너뛰어 이어진 배관이 없다

    def test_two_filled_triangles_with_a_dot_are_a_closed_globe_valve(self):
        ex = extract(BLACK_GLOBE + GLOBE_PIPES)
        (valve,) = closed_nodes(ex)
        self.assertEqual((valve["kind"], valve["attributes"]),
                         ("manual_valve", {"normal_position": "NC", "valve_type": "globe"}))
        self.assertEqual(len(pipe_ends_on(ex, valve)), 2)

    def test_outline_drawn_over_the_filled_body_does_not_become_a_second_symbol(self):
        outline = prim([(179.3, 274.9), (183.9, 274.9), (179.3, 265.6), (183.9, 265.6), (179.3, 274.9)])
        ex = extract(BLACK_GLOBE + [outline] + GLOBE_PIPES)
        self.assertEqual([n["kind"] for n in ex["nodes"]], ["manual_valve"])
        self.assertEqual(len(closed_nodes(ex)), 1)

    def test_arrowhead_between_two_pipe_ends_is_not_a_valve(self):
        head = filled([(100, 100), (104, 101.5), (100, 103)])
        ex = extract([head, pipe((80, 101.5), (100, 101.5)), pipe((104, 101.5), (126, 101.5))])
        self.assertEqual(closed_nodes(ex), [])
        self.assertEqual([n["kind"] for n in ex["nodes"] if n["category"] == "valve"], [])

    def test_building_transition_arrows_are_not_a_valve(self):
        """건물 경계 표시(범례 BUILDING TRANSITION)는 가는 화살촉 둘이 꼭짓점을 맞댄 모양이다. 나비 밸브와 닮았지만 납작하다."""
        thin = [filled([(100, 100), (103, 100.8), (100, 101.6)]), filled([(106, 100), (103, 100.8), (106, 101.6)])]
        ex = extract(thin + [pipe((80, 100.8), (100, 100.8)), pipe((106, 100.8), (126, 100.8))])
        self.assertEqual(closed_nodes(ex), [])
        self.assertEqual([n["kind"] for n in ex["nodes"] if n["category"] == "valve"], [])

    def test_half_filled_valve_is_not_closed(self):
        """한쪽 삼각형만 칠한 밸브(LT 표기)는 닫힘이 아니다."""
        half = [filled([(181.6, 270.3), (179.3, 265.6), (183.9, 265.6)]), filled_dot(181.6, 270.3, 1.2),
                prim([(179.3, 274.9), (181.6, 270.3), (183.9, 274.9), (179.3, 274.9)])]
        self.assertEqual(closed_nodes(extract(half + GLOBE_PIPES)), [])

    def test_closed_valve_is_not_merged_with_the_body_touching_it(self):
        reducer = prim([(106, 100.5), (109, 101), (109, 102), (106, 102.5), (106, 100.5)])
        ex = extract([filled(BLACK_GATE), reducer, pipe((80, 101.5), (100, 101.5)), pipe((109, 101.5), (126, 101.5))])
        (valve,) = closed_nodes(ex)
        self.assertEqual(valve["kind"], "manual_valve")
        self.assertEqual([round(valve["geometry"][k], 1) for k in ("x", "width")], [100.0, 6.0])
        self.assertEqual(len(ex["nodes"]), 2)
        self.assertNotIn("pipe_cap", [n["kind"] for n in ex["nodes"]])  # 밸브에 붙여 그린 축소관은 끝막음이 아니다

    def test_closed_valve_and_the_reducer_drawn_against_it_are_joined(self):
        """밸브에 축소관을 붙여 그리면 둘 사이에 선이 없다. 두 기호로 읽으면서 관계를 만들지 않으면 배관이 거기서 끊긴다."""
        reducer = prim([(106, 100.5), (109, 101), (109, 102), (106, 102.5), (106, 100.5)])
        ex = extract([OPEN_LEFT, OPEN_RIGHT, filled(BLACK_GATE), reducer,
                      pipe((66, 101.5), (100, 101.5)), pipe((109, 101.5), (140, 101.5))])
        (valve,) = closed_nodes(ex)
        other = node_at_x(ex, 108)
        joint = [r for r in ex["relations"]
                 if {e["node_local_id"] for e in r["endpoints"]} == {valve["local_id"], other["local_id"]}]
        self.assertEqual([(r["kind"], r["line_type"], r["evidence"]["classification_basis"]) for r in joint],
                         [("physical_connection", "pdf_touching", "touching_bodies")])
        path, _ = path_between_open_valves(ex)
        self.assertEqual((path["material_flow_path"], path["valve_state"]), (True, "closed_valve_on_path"))

    def test_body_touching_the_side_of_a_closed_valve_is_not_joined_as_pipe(self):
        """몸통 옆(배관 방향이 아닌 쪽)에 붙은 기호는 구동부 같은 것이다. 배관으로 잇지 않는다."""
        dome = prim([(101, 96), (105, 96), (105, 100), (101, 100), (101, 96)])
        ex = extract([filled(BLACK_GATE), dome] + GATE_PIPES)
        (valve,) = closed_nodes(ex)
        self.assertEqual([r["line_type"] for r in ex["relations"] + ex["unresolved_connectors"]
                          if r["line_type"] == "pdf_touching"], [])
        self.assertEqual(len(pipe_ends_on(ex, valve)), 2)

    def test_closed_valve_is_not_swallowed_by_a_large_symbol_whose_line_reaches_it(self):
        """큰 기호 상자 안에서 나온 선이 밸브에 닿아도 밸브는 제 노드로 남는다(115쪽 복수기 옆 밸브)."""
        tank = prim([(20, 60), (90, 60), (90, 140), (20, 140), (20, 60)])
        ex = extract([tank, filled(BLACK_GATE), pipe((60, 101.5), (100, 101.5)), pipe((106, 101.5), (126, 101.5))])
        (valve,) = closed_nodes(ex)
        self.assertEqual(valve["kind"], "manual_valve")
        self.assertEqual(len(pipe_ends_on(ex, valve)), 2)

    def test_equipment_word_in_the_label_does_not_rename_a_closed_valve(self):
        a = pdf_vector.analyze(400, 300, [word("PUMP", 100.0, 105.0)], [filled(BLACK_GATE)] + GATE_PIPES)
        ex = pdf_vector.build_extraction(a, 400, 300, 1, 0, "t.pdf", "0" * 64)
        self.assertEqual([(n["kind"], n["label_text"]) for n in closed_nodes(ex)], [("manual_valve", "PUMP")])

    def test_filled_body_with_other_lines_attached_keeps_closed_but_not_the_kind(self):
        """몸통에 벨로스 같은 다른 선이 붙으면 기호 전체는 사전에 없다. 종류는 비워 두고 닫힘만 남긴다."""
        bonnet = [pipe((103, 101.5), (103, 98.5)), pipe((101.5, 98.5), (104.5, 98.5))]
        ex = extract([filled(BLACK_GATE)] + bonnet + GATE_PIPES)
        (valve,) = closed_nodes(ex)
        self.assertEqual((valve["kind"], valve["attributes"]), (None, {"normal_position": "NC"}))
        self.assertEqual(valve["evidence"]["classification_basis"], "black_body:apr1400.gate_valve")
        self.assertNotIn("symbol_id", valve["evidence"])
        self.assertIn("missing_kind", [u["check"] for u in ex["validation"]["unknowns"]
                                       if u["target"] == valve["local_id"]])

    def test_closed_body_of_unknown_kind_still_closes_the_path(self):
        """종류를 못 정한 닫힌 몸통도 경로 분석에서는 닫힌 밸브다. 아니면 닫힌 밸브가 있는 길이 정상 유로가 된다."""
        bonnet = [pipe((103, 101.5), (103, 98.5)), pipe((101.5, 98.5), (104.5, 98.5))]
        ex = extract([OPEN_LEFT, OPEN_RIGHT, filled(BLACK_GATE)] + bonnet + OUTER_PIPES)
        (valve,) = closed_nodes(ex)
        self.assertEqual((valve["kind"], valve["category"], valve["classification"]), (None, "valve", "unclassified"))
        path, graph = path_between_open_valves(ex)
        self.assertEqual((path["valve_state"], path["normal_operation_flow"]), ("closed_valve_on_path", False))
        node = next(n for n in graph["nodes"] if n.get("local_id") == valve["local_id"])
        self.assertEqual(segment.part_of(node), segment.Part.VALVE)
        self.assertTrue(segment.traits(node).source)

    def test_valve_body_waiting_for_its_actuator_is_still_a_valve(self):
        """구동부가 붙어 구동 방식을 정하지 못한 몸통(actuated_valve_pending)도 종류만 비고 밸브로 남는다."""
        motor = ring(103, 94, 1.85)  # 전동 구동부 원이 몸통 가까이 있지만 축으로 이어지지 않았다
        prims = [OPEN_LEFT, OPEN_RIGHT, filled(BLACK_GATE), motor] + OUTER_PIPES
        a = pdf_vector.analyze(400, 300, [word("M", 102.4, 93.0, 2.0)], prims)
        ex = pdf_vector.build_extraction(a, 400, 300, 1, 0, "t.pdf", "0" * 64)
        (valve,) = closed_nodes(ex)
        self.assertEqual((valve["kind"], valve["category"]), (None, "valve"))
        self.assertIn("actuated_valve_pending", [u["check"] for u in ex["validation"]["unknowns"]
                                                 if u["target"] == valve["local_id"]])
        path, _ = path_between_open_valves(ex)
        self.assertEqual(path["valve_state"], "closed_valve_on_path")

    def test_pipe_drawn_straight_under_a_closed_valve_is_cut_at_the_valve(self):
        """검은 몸통 밑으로 배관을 끊지 않고 그린 도면이 있다. 선을 몸통에서 나누지 않으면 양쪽이 밸브를 건너 이어진다."""
        ex = extract([OPEN_LEFT, OPEN_RIGHT, filled(BLACK_GATE), pipe((66, 101.5), (140, 101.5))])
        (valve,) = closed_nodes(ex)
        self.assertEqual(len(pipe_ends_on(ex, valve)), 2)
        direct = [r for r in ex["relations"]
                  if {e["node_local_id"] for e in r["endpoints"]} == {node_at_x(ex, 63)["local_id"],
                                                                     node_at_x(ex, 143)["local_id"]}]
        self.assertEqual(direct, [])
        path, _ = path_between_open_valves(ex)
        self.assertEqual((path["valve_state"], path["normal_operation_flow"]), ("closed_valve_on_path", False))

    def test_dashed_line_drawn_straight_under_a_closed_valve_ends_at_the_valve(self):
        ex = extract([OPEN_LEFT, OPEN_RIGHT, filled(BLACK_GATE), dashed([(66, 101.5), (140, 101.5)])])
        (valve,) = closed_nodes(ex)
        ends = [e for r in ex["relations"] for e in r["endpoints"] if e["node_local_id"] == valve["local_id"]]
        self.assertEqual(len(ends), 2)
        self.assertEqual(sorted({e["node_local_id"] for r in ex["relations"] for e in r["endpoints"]}),
                         sorted(n["local_id"] for n in ex["nodes"]))

    def test_pipe_ends_on_a_closed_valve_inside_a_larger_symbol_attach_to_the_valve(self):
        """큰 기호의 상자 안에 닫힌 밸브가 있어도, 밸브에 닿은 배관 끝은 큰 기호가 아니라 밸브에 붙는다(023쪽).
        선 끝이 몸통 변에서 0.01pt 떨어져 있으면 상자 거리로는 선 끝을 품은 큰 기호(거리 0)가 이긴다."""
        frame = prim([(40, 60), (160, 60), (160, 140), (40, 140), (40, 60)])
        ex = extract([frame, filled(BLACK_GATE), pipe((40, 101.5), (99.99, 101.5)), pipe((106.01, 101.5), (160, 101.5))])
        (valve,) = closed_nodes(ex)
        self.assertEqual(len(pipe_ends_on(ex, valve)), 2)

    def test_pipe_under_a_closed_valve_inside_a_larger_symbol_is_still_cut(self):
        """큰 기호 상자 안을 지나는 선은 그 기호의 내부선으로 흡수되곤 한다. 밸브 밑을 지나는 배관은 그 전에 나눈다(128쪽)."""
        frame = prim([(40, 60), (160, 60), (160, 140), (40, 140), (40, 60)])
        ex = extract([frame, filled(BLACK_GATE), pipe((60, 101.5), (140, 101.5))])
        (valve,) = closed_nodes(ex)
        self.assertEqual(len(pipe_ends_on(ex, valve)), 2)

    def test_line_crossing_a_closed_valve_sideways_is_not_cut(self):
        """몸통을 옆으로 가로지르는 선(다른 배관이 겹쳐 지나감)은 이 밸브의 배관이 아니다."""
        ex = extract([filled(BLACK_GATE), pipe((103, 80), (103, 120))] + GATE_PIPES)
        (valve,) = closed_nodes(ex)
        self.assertEqual(len(pipe_ends_on(ex, valve)), 2)

    def test_closed_valve_inside_a_larger_outline_keeps_its_own_node(self):
        """배관이 닿지 않은 닫힌 밸브가 큰 외곽 사각형 안에 있어도 그 사각형의 부속으로 합치지 않는다."""
        frame = prim([(90, 90), (120, 90), (120, 120), (90, 120), (90, 90)])
        ex = extract([frame, filled(BLACK_GATE)])
        (valve,) = closed_nodes(ex)
        self.assertEqual((valve["kind"], round(valve["geometry"]["width"], 1)), ("manual_valve", 6.0))

    def test_body_drawn_as_four_thin_fills_is_left_alone(self):
        """좌우 삼각형을 다시 반으로 나눠 네 조각으로 칠한 몸통은 조각마다 점선 조각으로 분류돼 견본에 대 보지 않는다.
        APR1400 143쪽에는 이런 표현이 없다(F1-3 검토). 밸브로 읽지 못한다는 것과, 그 자리를 건너 배관을 잇지도 않는다는
        것을 고정한다."""
        quarters = [filled([(100, 100), (103, 101.5), (100, 101.5)]), filled([(100, 101.5), (103, 101.5), (100, 103)]),
                    filled([(106, 100), (103, 101.5), (106, 101.5)]), filled([(106, 101.5), (103, 101.5), (106, 103)])]
        ex = extract([OPEN_LEFT, OPEN_RIGHT] + quarters + OUTER_PIPES)
        self.assertEqual(closed_nodes(ex), [])
        self.assertEqual(ex["relations"], [])

    def test_two_filled_triangles_meeting_at_a_point_read_as_a_valve_even_if_meant_as_arrowheads(self):
        """마주 보는 화살촉 둘이 밸브와 같은 크기·비율로 꼭짓점을 맞대면 모양으로는 가를 수 없다. APR1400 143쪽에서 삼각형
        둘로만 된 묶음 19개는 모두 밸브였다(F1-3 검토). 가는 화살촉(건물 경계 표시)은 위 시험대로 올리지 않는다."""
        heads = [filled([(100, 100), (103, 101.5), (100, 103)]), filled([(106, 100), (103, 101.5), (106, 103)])]
        (valve,) = closed_nodes(extract(heads + GATE_PIPES))
        self.assertEqual(valve["attributes"]["valve_type"], "gate")

    def test_template_distance_limit_for_promotion_is_tighter_than_the_template(self):
        """견본의 max_distance가 느슨해도, 검은 채움을 몸체로 올리는 문턱(BLACK_SEED_DISTANCE)을 넘으면 올리지 않는다."""
        lib = pdf_vector.symbol_library()
        loose = symbols.Match("matched", lib.entries["apr1400.gate_valve"], pdf_vector.BLACK_SEED_DISTANCE + 0.01,
                              "symmetric", (), {"valve_type": "gate", "normal_position": "NC"})
        with mock.patch.object(type(lib), "match", return_value=loose):
            cls = pdf_vector._classify_primitives(400, 300, [filled(BLACK_GATE)], pdf_vector.PARAMS)
            pdf_vector._promote_black_symbols(cls, pdf_vector.PARAMS)
        self.assertEqual((len(cls["markers"]), [b for b in cls["bodies"] if b.get("solid")], cls["seeds"]), (1, [], {}))


def turned_word(text, x0, top, size=3.0):
    """아래에서 위로 읽는 90도 돌린 낱말(pdf_vector.load_page의 btt). 상자는 세로로 길다."""
    return {"text": text, "x0": x0, "x1": x0 + size, "top": top, "bottom": top + 0.6 * size * len(text),
            "size": size, "upright": False, "direction": "btt"}


def extract_with_words(prims, words):
    a = pdf_vector.analyze(400, 300, words, prims)
    return pdf_vector.build_extraction(a, 400, 300, 1, 0, "t.pdf", "0" * 64)


def valve_node(ex):
    (valve,) = [n for n in ex["nodes"] if n["category"] == "valve"]
    return valve


class ValveLabelTest(unittest.TestCase):
    """밸브 라벨 고르기(F1-5). APR1400은 수동 밸브 번호('V1681')를 밸브 아래·옆에 쓰고, 정상·고장 위치 약어(LO·NC·'LC,FC')를
    그보다 가까이 쓴다. 약어는 태그가 아니라 속성이고, 밸브 번호가 그 밸브의 태그다."""

    GATE_LINE = [prim(GATE, True), pipe((80, 101.5), (100, 101.5)), pipe((106, 101.5), (126, 101.5))]

    def test_number_further_than_the_position_word_becomes_the_tag(self):
        """028쪽 V1681처럼 위치 약어가 몸통 바로 위, 번호가 그 아래에 있다."""
        ex = extract_with_words(self.GATE_LINE, [word("LO", 101.0, 96.0), word("V1681", 98.0, 106.0)])
        valve = valve_node(ex)
        self.assertEqual((valve["tag"], valve["label_text"]), ("V1681", "V1681"))
        self.assertEqual(valve["attributes"].get("normal_position"), "LO")
        self.assertEqual(valve["evidence"]["position_text"], ["LO"])
        self.assertNotIn("missing_tag", [u["check"] for u in ex["validation"]["unknowns"] if u["target"] == valve["local_id"]])

    def test_turned_number_beside_a_vertical_valve_becomes_the_tag(self):
        """세로 배관의 밸브 번호는 돌려 쓴다(062쪽 V1062). 돌린 글자는 다른 기호의 라벨 후보가 아니어도 밸브 번호는 받는다."""
        body = prim([(100, 100), (103, 106), (100, 106), (103, 100), (100, 100)])
        lines = [pipe((101.5, 80), (101.5, 100)), pipe((101.5, 106), (101.5, 126))]
        ex = extract_with_words([body] + lines, [turned_word("V1062", 105.0, 99.0)])
        self.assertEqual(valve_node(ex)["tag"], "V1062")

    def test_position_words_set_normal_and_fail_position(self):
        ex = extract_with_words(self.GATE_LINE, [word("NC,FO", 99.0, 96.0)])
        self.assertEqual({k: v for k, v in valve_node(ex)["attributes"].items() if k.endswith("_position")},
                         {"normal_position": "NC", "fail_position": "FO"})

    def test_number_nearer_to_another_valve_is_left_to_that_valve(self):
        """번호는 가장 가까운 밸브의 것이다. 위치 약어 라벨인 밸브가 더 먼 번호를 가져가지 않는다."""
        other = prim([(150, 100), (156, 103), (156, 100), (150, 103), (150, 100)])
        words = [word("LO", 101.0, 96.0), word("V2001", 148.0, 105.0)]
        ex = extract_with_words(self.GATE_LINE + [other, pipe((126, 101.5), (150, 101.5))], words)
        tags = {round(n["geometry"]["x"]): n["tag"] for n in ex["nodes"] if n["category"] == "valve"}
        self.assertEqual(tags, {100: None, 150: "V2001"})

    def test_number_nearest_to_an_unread_symbol_is_not_given_to_a_valve(self):
        """063쪽 V714: 번호에 가장 가까운 기호는 밸브로 읽지 못한 몸통이다. 옆의 밸브가 그 번호를 가져가면 틀린 태그다."""
        unread = prim([(150, 100), (152, 98), (154, 100), (152, 102), (150, 100)])  # 밸브로 읽지 못하는 작은 마름모 몸통
        words = [word("LO", 101.0, 96.0), word("V714", 147.0, 104.0)]
        ex = extract_with_words(self.GATE_LINE + [unread, pipe((126, 101.5), (150, 101.5))], words)
        self.assertEqual([n["tag"] for n in ex["nodes"] if n["category"] == "valve"], [None])

    def test_lettered_diamond_does_not_take_a_valve_number(self):
        """품질 등급 마름모('BI|CI')는 삼각형 둘이라 나비 규칙으로 밸브가 된다. 안에 글자가 든 몸통은 밸브 번호를 받지 않는다
        (063쪽 V751·V713·V366)."""
        diamond = [prim([(100, 100), (106, 97), (106, 103), (100, 100)]), prim([(112, 100), (106, 97), (106, 103), (112, 100)])]
        words = [word("B", 102.5, 98.5, 2.0), word("I", 103.7, 98.5, 2.0), word("C", 107.0, 98.5, 2.0),
                 word("I", 108.2, 98.5, 2.0), word("V751", 101.0, 106.0)]
        ex = extract_with_words(diamond, words)
        self.assertEqual([(n["kind"], n["tag"]) for n in ex["nodes"] if n["category"] == "valve"], [("manual_valve", None)])

    def test_labels_of_other_symbols_do_not_change(self):
        """위치 약어가 다른 기호의 라벨이면 그대로 둔다(밸브만 손본다)."""
        ring_word = [ring(200, 150, 5.0)]
        ex = extract_with_words(ring_word, [word("NO", 198.0, 147.0)])
        (node,) = ex["nodes"]
        self.assertEqual((node["label_text"], node["attributes"]), ("NO", {}))

    def test_closed_body_and_a_different_position_word_are_both_kept(self):
        """검게 칠한 몸통(NC) 옆에 'NO'라고 쓰여 있으면 어느 쪽도 버리지 않는다(충돌은 둘 다 보존)."""
        ex = extract_with_words([filled(BLACK_GATE)] + GATE_PIPES, [word("NO", 101.0, 96.0)])
        valve = valve_node(ex)
        self.assertEqual(valve["attributes"]["normal_position"], "NC")
        self.assertEqual(valve["evidence"]["position_text"], ["NO"])
        conflicts = [u for u in ex["validation"]["unknowns"] if u["check"] == "position_conflict"]
        self.assertEqual([(u["target"], u["field"]) for u in conflicts], [(valve["local_id"], "normal_position")])

    def test_locked_closed_word_refines_a_closed_body(self):
        """검은 몸통(NC) 옆의 'LC'는 같은 닫힘을 더 자세히 쓴 것이다(062쪽 V2132)."""
        ex = extract_with_words([filled(BLACK_GATE)] + GATE_PIPES, [word("LC", 101.0, 96.0)])
        valve = valve_node(ex)
        self.assertEqual((valve["attributes"]["normal_position"], valve["evidence"]["position_from_body"]), ("LC", "NC"))
        self.assertNotIn("position_conflict", [u["check"] for u in ex["validation"]["unknowns"]])

    def test_valve_numbers_do_not_lend_a_prefix_to_instruments(self):
        """같은 밸브 번호가 두 밸브에 나와도(둘 다 비움) 계기 태그의 계통 접두로 쓰지 않는다."""
        nodes = [{"kind": "manual_valve", "category": "valve", "label_text": "V1681", "source_object_id": "s%d" % i,
                  "local_id": "n%d" % i, "evidence": {}, "geometry": {"x": 0, "y": 0, "width": 6, "height": 3}}
                 for i in range(2)]
        nodes.append({"kind": "transmitter", "category": "instrument", "label_text": "PT\n110", "source_object_id": "s2",
                      "local_id": "n2", "evidence": {}, "geometry": {"x": 0, "y": 0, "width": 12, "height": 12}})
        unknowns = []
        pdf_vector._assign_tags(nodes, unknowns, {"n2"}, {"n0", "n1"})
        self.assertEqual([n["tag"] for n in nodes], [None, None, "PT-110"])
        self.assertEqual([u["check"] for u in unknowns], ["duplicate_tag", "duplicate_tag"])


# APR1400 043쪽 (702.4,139.0)의 앵글형 방출 밸브 그대로: 삼각형 몸통, 줄기, 줄기 위 스프링선 셋, 방출구, 받침 판
ANGLE_RELIEF = [prim([(700.6, 140.78), (704.26, 140.78), (704.26, 137.12), (700.6, 140.78)]),
                pipe((704.26, 140.78), (702.43, 138.95)), pipe((702.43, 136.39), (702.43, 138.95)),
                pipe((706.09, 140.41), (706.09, 137.48)), pipe((700.97, 142.61), (703.89, 142.61))]
ANGLE_RELIEF_SPRING = [pipe((701.7, 137.81), (703.16, 136.39)), pipe((701.7, 138.38), (703.16, 136.95)),
                       pipe((701.7, 138.95), (703.16, 137.52))]


def extract_wide(prims):
    a = pdf_vector.analyze(1224, 792, [], prims)
    return pdf_vector.build_extraction(a, 1224, 792, 1, 0, "t.pdf", "0" * 64)


class DictionaryAdditionTest(unittest.TestCase):
    """F1-6에서 사전에 더한 앵글형 안전·방출 밸브(apr1400.angle_relief_valve)."""

    def test_angle_relief_valve_is_a_psv(self):
        (node,) = extract_wide(ANGLE_RELIEF + ANGLE_RELIEF_SPRING)["nodes"]
        self.assertEqual((node["kind"], node["evidence"].get("symbol_id")), ("psv", "apr1400.angle_relief_valve"))

    def test_angle_shape_without_a_spring_is_not_a_psv(self):
        """격자 견본은 비슷한 모양에도 맞는다. 스프링선 자리에 가로선을 그은 도형이나 스프링선이 없는 도형은 psv가 아니다
        (F1-6 Codex 검토)."""
        level = [pipe((701.7, 137.6 + 0.57 * k), (703.16, 137.6 + 0.57 * k)) for k in range(3)]
        for prims in (ANGLE_RELIEF, ANGLE_RELIEF + level, ANGLE_RELIEF + ANGLE_RELIEF_SPRING[:1]):
            self.assertNotIn("psv", [n["kind"] for n in extract_wide(prims)["nodes"]])

    def test_each_new_template_matches_its_own_entry(self):
        """F1-6 견본(검게 칠한 플러그 3개, 앵글형 방출 밸브 8개)은 문턱을 조인 뒤에도 자기 격자에는 맞는다. 플러그는 NC다."""
        lib = pdf_vector.symbol_library()
        for eid, first, attrs in (("apr1400.plug_valve", 5, {"normal_position": "NC"}),
                                  ("apr1400.angle_relief_valve", 0, {})):
            for t in lib.entries[eid].templates[first:]:
                cells = t.variants[0][1]
                hit = lib.match(symbols.Signature(t.comp_key, (t.size, t.size), cells, False))
                self.assertEqual((hit.outcome, hit.entry.id), ("matched", eid), t.comp_key)
                for k, v in attrs.items():
                    self.assertEqual(hit.attributes.get(k), v)

    def test_filled_triangle_with_two_bars_is_not_a_plug_valve(self):
        """검게 칠한 삼각형 하나와 양끝 막대는 플러그 밸브(검은 마름모)가 아니다. 문턱 0.8에서는 0.3~0.4로 맞았다(F1-6 검토)."""
        size, half = 7.3, 3.65
        tri = filled([(100, 100), (100 + size, 100 + half / 2), (100, 100 + half)])
        bars = [pipe((100, 100), (100, 100 + half)), pipe((100 + size, 100), (100 + size, 100 + half))]
        pipes = [pipe((80, 100 + half / 2), (100, 100 + half / 2)), pipe((100 + size, 100 + half / 2), (120, 100 + half / 2))]
        nodes = extract_wide([tri] + bars + pipes)["nodes"]
        self.assertNotIn("apr1400.plug_valve", [n["evidence"].get("symbol_id") for n in nodes])

    def test_relief_valve_the_size_of_an_end_cap_is_a_psv(self):
        """044쪽 sym-0059(484.4,300.1): 전에는 끝막음이던 5.9×6.7pt 앵글형 방출 밸브. 같은 쪽 psv와 크기가 같다."""
        body = [(482.47, 302.54), (486.41, 302.54), (486.41, 298.59), (482.47, 302.54)]
        prims = [prim(body), pipe((486.41, 302.54), (484.44, 300.57)), pipe((484.44, 297.81), (484.44, 300.57)),
                 pipe((483.65, 299.34), (485.23, 297.81)), pipe((483.65, 299.95), (485.23, 298.42)),
                 pipe((483.65, 300.57), (485.23, 299.03)), pipe((488.38, 302.14), (488.38, 298.99)),
                 pipe((482.86, 304.51), (486.02, 304.51))]
        (node,) = extract_wide(prims)["nodes"]
        self.assertEqual((node["kind"], node["evidence"].get("symbol_id")), ("psv", "apr1400.angle_relief_valve"))

    def test_black_fill_alone_is_not_promoted(self):
        """양끝 막대 없이 검은 마름모만 있으면 밸브로 올리지 않는다. 검정 견본 승격(_promote_black_symbols)에는 플러그
        견본이 없어서다. 7pt 이하 작은 검은 플러그가 표식으로 남는 한계와 같은 길이다(F1-6 검토, 후속)."""
        for size in (6.5, 7.28):
            half = size / 2
            diamond = filled([(100, 100 + half / 2), (100 + size / 2, 100), (100 + size, 100 + half / 2),
                              (100 + size / 2, 100 + half)])
            pipes = [pipe((80, 100 + half / 2), (100, 100 + half / 2)),
                     pipe((100 + size, 100 + half / 2), (120, 100 + half / 2))]
            nodes = extract_wide([diamond] + pipes)["nodes"]
            self.assertEqual([n["kind"] for n in nodes if n["kind"]], [], size)


class AddSymbolsSourcesTest(unittest.TestCase):
    """add_symbols.py는 견본을 더할 때 앞서 더한 견본의 출처 줄을 지우지 않는다(F1-6에서 plug_valve의 13쪽·57기호 줄이
    새 줄로 바뀌어 견본 5개의 출처가 없어졌다)."""

    def setUp(self):
        folder = os.path.join(REPO_ROOT, "scripts", "symbols")
        spec = importlib.util.spec_from_file_location("add_symbols", os.path.join(folder, "add_symbols.py"))
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_earlier_source_lines_are_kept(self):
        legend = {"set": "APR1400 DCD Rev.3", "legend": "1.7-1 1/4 VALVE SYMBOLS"}
        first = {"set": "APR1400 DCD Rev.3", "pages": ["023", "029"], "symbols": 57, "template_parity": "all"}
        second = {"set": "APR1400 DCD Rev.3", "pages": ["061", "127"], "symbols": 42, "template_parity": "all"}
        sources = self.mod.add_source([legend, first], second)
        self.assertEqual(sources, [legend, first, second])
        self.assertEqual(self.mod.add_source(sources, dict(second)), sources)



if __name__ == "__main__":
    unittest.main()
