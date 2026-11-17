"""AI 검토 그림 입력의 범례판 출처와 진입(ai_images.image_input_for) 시험. 실행: python -m unittest tests.test_ai_images_legend

범례판은 프로젝트 판(사람이 정했거나 스크립트가 사전 견본에 맞춘 기호의 조각, 프로젝트 작업 폴더에만 캐시)이 있으면 그것,
없으면 저장소의 표준 기호 판(resources/library/ai-legend, scripts/build_ai_legend.py), 그것도 없으면 범례판 없이 돈다.
"""

import glob
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from hazop import paths
from hazop.extract import ai_images
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
        self.assertEqual(sorted(index["cells"]), ai_images.answer_kinds())
        self.assertEqual(sorted(os.listdir(paths.folder("ai-legend"))), sorted(index["boards"] + [ai_images.LEGEND_INDEX]))


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
        self.assertEqual(got.legend_source, "project")
        self.assertTrue(got.legend and got.legend != ai_images.symbol_legend())
        index = [f for f in os.listdir(self.tmp) if f.endswith(".json")]
        self.assertEqual(len(index), 1)
        with open(os.path.join(self.tmp, index[0]), encoding="utf-8") as fh:
            self.assertEqual(sorted(json.load(fh)["kinds"]), ["manual_valve", "pump"], "답 목록 밖 종류(tank)는 싣지 않는다")
        with mock.patch.object(ai_images.PageImages, "image", side_effect=AssertionError("캐시가 있으면 쪽을 다시 그리지 않는다")):
            again = ai_images.image_input_for(snp_pdf(), 0, drawings=drawings, cache_dir=self.tmp)
        self.assertEqual(again.legend, got.legend)
        moved = project_ex()
        moved["nodes"][0]["geometry"]["x"] += 5
        third = ai_images.project_legend([(snp_pdf(), 0, moved)], self.tmp)
        self.assertTrue(third)
        self.assertEqual(len([f for f in os.listdir(self.tmp) if f.endswith(".json")]), 2, "견본 자리가 바뀌면 다시 만든다")

    def test_project_without_confirmed_symbols_falls_back_to_symbol_board(self):
        ex = {"nodes": [node("c", "check_valve", (300, 100, 320, 112), basis="lines+marker")]}
        got = ai_images.image_input_for(snp_pdf(), 0, drawings=[(snp_pdf(), 0, ex)], cache_dir=self.tmp)
        self.assertEqual(got.legend_source, "symbols")
        self.assertEqual(os.listdir(self.tmp), [])

    def test_unreadable_project_pdf_is_skipped(self):
        got = ai_images.project_legend([(os.path.join(self.tmp, "gone.pdf"), 0, project_ex())], self.tmp)
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
