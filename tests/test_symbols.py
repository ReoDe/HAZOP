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
from hazop.extract import symbols
from hazop.extract.adapters import pdf_vector

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
        """기존 규칙이 정한 기호(삼각형 둘 = 수동 밸브)는 사전을 보지 않는다."""
        ex = extract([prim([(0, 0), (5, 3), (0, 6), (0, 0)]), prim([(10, 0), (5, 3), (10, 6), (10, 0)])])
        self.assertEqual(ex["nodes"][0]["kind"], "manual_valve")
        self.assertNotIn("symbol_id", ex["nodes"][0]["evidence"])

    def test_dictionary_kind_outside_registry_fails_loudly(self):
        tmp = tempfile.mkdtemp()
        try:
            shutil.copytree(paths.folder("기호"), os.path.join(tmp, "기호"))
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

    def test_one_pair_or_perpendicular_marks_are_not_ticks(self):
        one = extract([prim([(50, 100), (100, 100)], False)] + ticks_at((60,)))
        self.assertFalse(any(r["line_type"] == "pdf_pneumatic" for r in one["relations"] + one["unresolved_connectors"]))
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


class RepoLibraryTest(unittest.TestCase):
    def test_repo_library_loads_and_checks(self):
        root = paths.folder("기호")
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


if __name__ == "__main__":
    unittest.main()
