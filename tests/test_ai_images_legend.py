"""AI 검토 그림 입력의 범례판 출처와 진입(ai_images.image_input_for) 시험. 실행: python -m unittest tests.test_ai_images_legend

범례판은 프로젝트 판(사람이 정했거나 스크립트가 사전 견본에 맞춘 기호의 조각, 프로젝트 작업 폴더에만 캐시)이 있으면 그것,
없으면 저장소의 표준 기호 판(resources/library/ai-legend, scripts/build_ai_legend.py), 그것도 없으면 범례판 없이 돈다.
"""

import glob
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from hazop import paths
from hazop.extract import ai_images, legend_page
from scripts import build_ai_legend


def snp_pdf():
    return glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]


def node(sid, kind, box, basis=None, ops=None):
    n = {"local_id": "L" + sid, "source_object_id": sid, "kind": kind,
         "geometry": {"x": box[0], "y": box[1], "width": box[2] - box[0], "height": box[3] - box[1]},
         "evidence": {"classification_basis": basis}}
    if ops:
        n["human_edit"] = {"op_ids": ["op-1"], "ops": list(ops)}
    return n


def project_ex():
    return {"nodes": [node("a", "manual_valve", (100, 100, 120, 112), basis="symbol:apr1400.gate_valve"),
                      node("b", "pump", (200, 100, 230, 130), basis="pump_circle", ops=["set_kind"]),
                      node("c", "check_valve", (300, 100, 320, 112), basis="lines+marker"),
                      node("d", "pump", (400, 100, 430, 130), basis="symbol:x", ops=["set_tag"]),
                      node("e", "tank", (500, 100, 600, 200), basis="symbol:apr1400.tank")]}


class SymbolBoardTest(unittest.TestCase):
    def test_stored_board_is_up_to_date(self):
        why = build_ai_legend.stale()
        self.assertEqual(why, [], "표준 기호 범례판이 낡았다: %s. python scripts/build_ai_legend.py로 다시 만든다" % why)

    def test_board_covers_answer_kinds_and_uses_no_drawing_crops(self):
        with open(paths.folder("ai-legend", ai_images.LEGEND_INDEX), encoding="utf-8") as fh:
            index = json.load(fh)
        self.assertEqual(index["source"], paths.folder_rel("drawing-symbols"))
        self.assertEqual(sorted(index["kinds"]), ai_images.answer_kinds())
        self.assertEqual(sorted(os.listdir(paths.folder("ai-legend"))),
                         sorted(index["boards"] + [ai_images.LEGEND_INDEX, "cells", "variants", build_ai_legend.VARIANTS]))
        self.assertEqual(sorted(os.listdir(paths.folder("ai-legend", "cells"))), sorted(c["file"][6:] for c in index["cells"]))
        self.assertTrue(all(f.endswith(".svg") for f in os.listdir(paths.folder("ai-legend", "variants"))),
                        "변형 그림은 직접 그린 SVG만 둔다")

    def test_variants_replace_or_join_standard_cells_and_boards_fit_image_limit(self):
        from PIL import Image
        import io
        with open(paths.folder("ai-legend", ai_images.LEGEND_INDEX), encoding="utf-8") as fh:
            cells = json.load(fh)["cells"]
        by = {}
        for c in cells:
            by.setdefault(c["kind"], []).append(c["from"])
        self.assertEqual(by["drain"], ["variants/drain-hub.svg", "variants/drain-cup.svg"], "표준 drain(다이오드 꼴)은 뺀다")
        self.assertEqual(by["transmitter"], ["variants/transmitter-letters.svg"], "글자 없는 빈 원 칸은 뺀다")
        self.assertEqual(by["check_valve"], ["standard", "variants/check-valve-flap.svg"])
        self.assertEqual(by["manual_valve"], ["standard"])
        for png in ai_images.symbol_legend():
            self.assertLessEqual(max(Image.open(io.BytesIO(png)).size), 1568)


class EntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-ai-legend-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_without_project_drawings_uses_symbol_board_and_answer_kinds(self):
        got = ai_images.image_input_for(snp_pdf(), 0)
        self.assertEqual(got.legend_source, "symbols")
        self.assertEqual(got.legend, ai_images.symbol_legend())
        self.assertTrue(got.legend and all(png.startswith(b"\x89PNG") for png in got.legend))
        self.assertEqual(got.kinds, ai_images.answer_kinds())
        self.assertEqual((got.page.pdf_path, got.page.page, got.wide, got.recheck, got.split), (snp_pdf(), 0, True, True, False))

    def test_without_any_board_runs_with_no_legend(self):
        with mock.patch.object(ai_images, "LEGEND_INDEX", "missing.json"):
            got = ai_images.image_input_for(snp_pdf(), 0, drawings=[(snp_pdf(), 0, {"nodes": []})])
        self.assertEqual((got.legend_source, got.legend, got.kinds), ("none", [], ai_images.answer_kinds()))

    def test_confirmed_samples_are_human_set_kind_or_dictionary_match(self):
        self.assertEqual([k for k, _ in ai_images.confirmed_samples(project_ex())], ["manual_valve", "pump", "pump", "tank"])

    def test_project_board_wins_and_is_cached_in_given_folder(self):
        drawings = [(snp_pdf(), 0, project_ex())]
        got = ai_images.image_input_for(snp_pdf(), 0, drawings=drawings, cache_dir=self.tmp)
        self.assertEqual(got.legend_source, "project+symbols")
        self.assertTrue(got.legend and got.legend != ai_images.symbol_legend())
        index = [f for f in os.listdir(self.tmp) if f.endswith(".json")]
        self.assertEqual(len(index), 1)
        with open(os.path.join(self.tmp, index[0]), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(sorted(doc["kinds"]), ai_images.answer_kinds(), "견본 없는 종류는 표준 칸으로 채운다")
        self.assertEqual(sorted(set(ai_images.answer_kinds()) - set(doc["from_symbols"])), ["manual_valve", "pump"],
                         "프로젝트 견본이 있는 종류는 표준 칸을 섞지 않고, 답 목록 밖 종류(tank)는 싣지 않는다")
        with mock.patch.object(ai_images.PageImages, "image", side_effect=AssertionError("캐시가 있으면 쪽을 다시 그리지 않는다")):
            again = ai_images.image_input_for(snp_pdf(), 0, drawings=drawings, cache_dir=self.tmp)
        self.assertEqual(again.legend, got.legend)
        moved = project_ex()
        moved["nodes"][0]["geometry"]["x"] += 5
        third, source = ai_images.project_legend([(snp_pdf(), 0, moved)], self.tmp)
        self.assertTrue(third and source == "project+symbols")
        self.assertEqual(len([f for f in os.listdir(self.tmp) if f.endswith(".json")]), 2, "견본 자리가 바뀌면 다시 만든다")

    def test_project_alone_when_symbol_cells_are_missing(self):
        with mock.patch.object(ai_images, "symbol_cells", return_value={}):
            boards, source = ai_images.project_legend([(snp_pdf(), 0, project_ex())])
        self.assertEqual((bool(boards), source), (True, "project"))

    def test_project_without_confirmed_symbols_falls_back_to_symbol_board(self):
        ex = {"nodes": [node("c", "check_valve", (300, 100, 320, 112), basis="lines+marker")]}
        got = ai_images.image_input_for(snp_pdf(), 0, drawings=[(snp_pdf(), 0, ex)], cache_dir=self.tmp)
        self.assertEqual(got.legend_source, "symbols")
        self.assertEqual(os.listdir(self.tmp), [])

    def test_unreadable_project_pdf_is_skipped(self):
        got = ai_images.project_legend([(os.path.join(self.tmp, "gone.pdf"), 0, project_ex())], self.tmp)
        self.assertEqual(got, ([], None))


# ---------------------------------------------------------------- 범례 쪽 판(합성 범례 쪽, 도면 조각 없음)

FONT = b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> "
W, H = 400, 300
VALVES = ("GATE", "GLOBE", "CHECK", "ANGLE CHECK VALVE", "STRAINER", "REDUCER", "ROOF VENTILATOR WITH PARALLEL BLADE DAMPER")
PIPES = ("WELDED CAP", "FLOOR DRAIN", "EXPANSION JOINT", "FLEXIBLE HOSE", "SILENCER", "SPRAY NOZZLE OR SPARGER", "FLAME ARRESTOR")


def make_pdf(content):
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R %s>>" % (W, H, FONT),
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def text(s, x, top, size=3.3):
    return b"BT /F1 %.1f Tf %.1f %.1f Td (%s) Tj ET\n" % (size, x, H - top - size, s.encode("ascii"))


def seg(x0, top0, x1, top1):
    return b"%.1f %.1f m %.1f %.1f l S\n" % (x0, H - top0, x1, H - top1)


def legend_sheet(heads=("VALVE SYMBOLS", "PIPE LINE SYMBOLS"), pictures=True, names=(VALVES, PIPES)):
    """두 판짜리 범례 쪽: 판 머리글 아래 줄마다 왼쪽에 기호 그림(작은 사각형과 선), 오른쪽에 이름 글자."""
    c = b"0.5 w\n"
    for x in (20, 200, 380):
        c += seg(x, 20, x, 280)
    for y in (20, 35, 280):
        c += seg(20, y, 380, y)
    for i, head in enumerate(heads):
        c += text(head, 60 + 180 * i, 25, size=6)
    for i, rows in enumerate(names):
        x0 = 20 + 180 * i
        for r, name in enumerate(rows):
            top = 50 + 30 * r
            if pictures:
                c += b"%.1f %.1f 14 6 re S\n" % (x0 + 20, H - top - 6) + seg(x0 + 14, top + 3, x0 + 40, top + 3)
            c += text(name, x0 + 70, top + 1)
    return make_pdf(c)


class LegendPageTest(unittest.TestCase):
    """범례 쪽 알아보기·칸 자르기·이름 잇기(hazop/extract/legend_page.py)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-legend-page-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def pdf(self, data, name="sheet.pdf"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_names_map_to_kinds_and_narrow_or_ambiguous_names_are_handled(self):
        cases = {"ANGLE CHECK VALVE": "check_valve", "GATE": "manual_valve", "SPRAY NOZZLE OR SPARGER (UPWARD)": "sparger",
                 "CONCENTRIC REDUCER OR ENLARGER": "reducer", "ANGLE SAFETY OR RELIEF": "psv",
                 "TRAP DT : DRAIN TRAP RT : RESIN TRAP": None, "ROOF VENTILATOR WITH PARALLEL BLADE DAMPER": None,
                 "COMPRESSION TANK VENT FITTING": None, "SHARED HSI (HAND SWITCH, INDICATOR, ALARM)": None,
                 "DUCTED AIR FLOW": "air_flow_arrow", "MOTOR OPERATOR AC MOTOR": "motor_operated_valve", "SWING PANEL": None}
        self.assertEqual({n: legend_page.kind_of(n) for n in cases}, cases)

    def test_legend_sheet_cells_pair_each_picture_with_its_name(self):
        cells = legend_page.legend_cells(self.pdf(legend_sheet()))
        got = {c["name"]: c["kind"] for c in cells}
        self.assertEqual(got, {n: legend_page.kind_of(n) for n in VALVES + PIPES if legend_page.kind_of(n)})
        self.assertNotIn("ROOF VENTILATOR WITH PARALLEL BLADE DAMPER", got, "이름이 애매한 칸은 버린다")
        for c in cells:
            row = (VALVES + PIPES).index(c["name"]) % 7
            self.assertTrue(50 + 30 * row - 1 <= c["box"][1] and c["box"][3] <= 50 + 30 * row + 7, c)
            self.assertLess(c["box"][2], 20 + 180 * ((VALVES + PIPES).index(c["name"]) // 7) + 70, "그림은 이름 왼쪽만")

    def test_not_a_legend_sheet_falls_back_to_no_cells(self):
        one_heading = legend_sheet(heads=("3. NOZZLE SYMBOLS :", "NOTES"))
        table = legend_sheet(heads=("LEGEND", "ABBREVIATIONS"), pictures=False,
                             names=(["AC = ACCUMULATOR", "CD = CONDENSER", "PP = PUMP"] * 2, ["TK = TANK", "SG = STEAM GENERATOR"] * 3))
        few = legend_sheet(names=(VALVES[:3], PIPES[:3]))
        for name, data in (("one-heading", one_heading), ("text-table", table), ("few-cells", few)):
            self.assertEqual(legend_page.legend_cells(self.pdf(data, name + ".pdf")), [], name)
        self.assertEqual(legend_page.legend_cells(os.path.join(self.tmp, "gone.pdf")), [])

    def test_legend_cells_come_first_and_legend_page_extraction_is_not_a_sample(self):
        sheet = self.pdf(legend_sheet())
        on_sheet = {"nodes": [node("p", "pump", (40, 50, 60, 60), basis="symbol:apr1400.pump")]}
        drawings = [(sheet, 0, on_sheet), (snp_pdf(), 0, project_ex())]
        cache = os.path.join(self.tmp, "cache")
        got = ai_images.image_input_for(snp_pdf(), 0, drawings=drawings, cache_dir=cache, with_legend_pages=True)
        self.assertEqual(got.legend_source, "legend+project+symbols")
        self.assertIn(got.legend_source, ai_images.LEGEND_SOURCES)
        index = [f for f in os.listdir(cache) if f.endswith(".json")]
        with open(os.path.join(cache, index[0]), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertIn("manual_valve", doc["from_legend"], "범례 쪽 칸과 확정 견본이 겹치면 범례 쪽 칸")
        self.assertEqual(sorted(set(ai_images.answer_kinds()) - set(doc["from_legend"]) - set(doc["from_symbols"])), ["pump"],
                         "범례 쪽에 없는 종류만 확정 견본(project_ex의 pump), 범례 쪽 추출의 pump는 견본이 아니다")
        self.assertEqual(len(os.listdir(os.path.join(cache, ai_images.LEGEND_PAGE_DIR))), 2, "쪽마다 범례 쪽 판정을 남긴다")
        with mock.patch.object(legend_page, "legend_cells", side_effect=AssertionError("캐시가 있으면 PDF를 다시 자르지 않는다")), \
                mock.patch.object(ai_images.PageImages, "image", side_effect=AssertionError("판 캐시")):
            again = ai_images.image_input_for(snp_pdf(), 0, drawings=drawings, cache_dir=cache, with_legend_pages=True)
        self.assertEqual(again.legend, got.legend)

    def test_legend_pages_off_by_default_keeps_board_source_and_cache_key(self):
        sheet = self.pdf(legend_sheet())
        on_sheet = {"nodes": [node("p", "pump", (40, 50, 60, 60), basis="symbol:apr1400.pump")]}
        drawings = [(sheet, 0, on_sheet), (snp_pdf(), 0, project_ex())]
        cache = os.path.join(self.tmp, "cache")
        with mock.patch.object(legend_page, "legend_cells", side_effect=AssertionError("끄면 범례 쪽을 읽지 않는다")):
            got = ai_images.image_input_for(snp_pdf(), 0, drawings=drawings, cache_dir=cache)
        self.assertEqual(got.legend_source, "project+symbols")
        sig = [[ai_images._stamp(p), 0, [(k, b) for k, b in ai_images.confirmed_samples(ex) if k in ai_images.answer_kinds()]]
               for p, _, ex in drawings]
        key = hashlib.sha256(json.dumps([2, ai_images.PROJECT_PER_KIND, ai_images.answer_kinds(), sig,
                                         ai_images._symbol_index().get("inputs_sha256")], sort_keys=True).encode("utf-8")).hexdigest()[:16]
        self.assertEqual(sorted(os.listdir(cache)), sorted([key + ".json"] + ["%s-%02d.png" % (key, i + 1) for i in range(len(got.legend))]),
                         "끈 판의 캐시 열쇠·파일은 범례 쪽 판을 들이기 전과 같다")
        with open(os.path.join(cache, key + ".json"), encoding="utf-8") as fh:
            self.assertEqual(sorted(json.load(fh)), ["boards", "from_symbols", "kinds", "per_kind", "source"])
        self.assertEqual(ai_images.project_legend(drawings, cache), (got.legend, "project+symbols"))

    def test_valve_cell_with_open_and_closed_pictures_gives_first_pictures_first(self):
        crops = ai_images.legend_page_cells([], pages=[(snp_pdf(), 0, None, [
            {"kind": "manual_valve", "parts": [[10, 10, 20, 20], [60, 10, 70, 20]]},
            {"kind": "manual_valve", "parts": [[10, 40, 20, 50], [60, 40, 70, 50]]}])], per_kind=3)
        self.assertEqual(len(crops["manual_valve"]), 3)
        with mock.patch.object(ai_images.PageImages, "crop", side_effect=lambda b, **k: tuple(b)):
            order = ai_images.legend_page_cells([], pages=[(snp_pdf(), 0, None, [
                {"kind": "manual_valve", "parts": [[10, 10, 20, 20], [60, 10, 70, 20]]},
                {"kind": "manual_valve", "parts": [[10, 40, 20, 50]]}, {"kind": "tank", "parts": [[1, 1, 9, 9]]}])])
        self.assertEqual(order, {"manual_valve": [(10, 10, 20, 20), (10, 40, 20, 50), (60, 10, 70, 20)]},
                         "칸마다 첫 그림 먼저, 답 목록 밖 종류는 싣지 않는다")


if __name__ == "__main__":
    unittest.main()
