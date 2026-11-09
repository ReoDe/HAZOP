"""시작·③ 첫 진입을 빠르게 하는 것: 추출 요약 캐시 파일(data.extraction_brief), 도면 그래프 머리(kg.auto.graph_head),
시작할 때 Excel 라이브러리를 읽지 않음."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from hazop.app import data
from hazop.kg import auto, screen


def write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)


def bump(path):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))


class ExtractionBriefCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp})
        self.env.start()
        self.path = os.path.join(self.tmp, "출력", "추출", "D1", "extraction.json")
        write(self.path, {"source": {"file": "C:/어딘가/D1.drawio"}, "drawing": {"drawing_number": "101", "title": "급수"},
                          "summary": {"nodes": 3, "relations": 2, "unknowns": 1}})
        self.fresh_process()

    def tearDown(self):
        self.env.stop()
        self.fresh_process()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def fresh_process():
        data._SOURCE_CACHE.clear()
        data._DISK.update(file=None, entries={}, dirty=False)

    def test_a_new_process_reads_the_summary_from_the_cache_file(self):
        self.assertEqual(data.unregistered_extractions(), [("D1", "등록 없이 추출")])
        self.assertTrue(os.path.isfile(data._brief_file()), "처음 읽은 요약을 캐시 파일에 씀")
        self.fresh_process()
        with mock.patch.object(data, "read_json", wraps=data.read_json) as read:
            brief = data.extraction_brief(self.path)
        self.assertEqual((brief["drawing_number"], brief["unknowns"]), ("101", 1))
        self.assertNotIn(self.path, [c.args[0] for c in read.call_args_list], "추출 JSON은 다시 읽지 않음")

    def test_a_changed_extraction_is_read_again(self):
        data.unregistered_extractions()
        write(self.path, {"source": {"material_id": "M1"}, "drawing": {"drawing_number": "101"}, "summary": {"unknowns": 5}})
        bump(self.path)
        self.fresh_process()
        self.assertEqual(data.extraction_brief(self.path)["unknowns"], 5)
        self.assertEqual(data.unregistered_extractions(), [], "등록 자료로 바뀌면 목록에서 빠짐")

    def test_a_read_error_is_not_kept_in_the_cache(self):
        with mock.patch.object(data, "read_json", side_effect=PermissionError("잠김")):
            self.assertIsNone(data.extraction_brief(self.path))
        self.assertEqual(data.extraction_brief(self.path)["origin"], "등록 없이 추출", "풀리면 다시 읽음")

    def test_a_cached_summary_with_the_wrong_shape_is_read_again(self):
        st = os.stat(self.path)
        write(data._brief_file(), {"version": data.BRIEF_CACHE_VERSION,
                                   "entries": {self.path: {"stat": [st.st_mtime_ns, st.st_size], "brief": {"unknowns": "x"}}}})
        self.assertEqual(data.extraction_brief(self.path)["unknowns"], 1)

    def test_a_broken_cache_file_is_ignored(self):
        write(data._brief_file(), {"version": data.BRIEF_CACHE_VERSION, "entries": "깨짐"})
        self.assertEqual(data.extraction_brief(self.path)["title"], "급수")


class GraphForRefTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        auto._HEADS.clear()
        for name, ver in (("a-drawio", "v1"), ("b-pdf", "v2")):
            write(os.path.join(self.root, name, "graph.json"), {"graph_id": "G1", "graph_version": ver, "nodes": [name]})
        write(os.path.join(self.root, "c-other", "graph.json"), {"graph_id": "G2", "graph_version": "v2"})

    def tearDown(self):
        auto._HEADS.clear()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_prefers_the_same_version_then_the_first_folder(self):
        self.assertEqual(screen.graph_for_ref(self.root, "G1", "v2")[0], "b-pdf")
        self.assertEqual(screen.graph_for_ref(self.root, "G1", "v9")[0], "a-drawio")
        self.assertIsNone(screen.graph_for_ref(self.root, "G3", "v1"))

    def test_a_file_swapped_after_its_header_was_cached_is_not_returned(self):
        screen.graph_for_ref(self.root, "G1", "v2")
        p = os.path.join(self.root, "b-pdf", "graph.json")
        st = os.stat(p)
        with open(p, "w", encoding="utf-8") as fh:  # 같은 크기·같은 시각으로 다른 도면을 덮어씀
            fh.write(json.dumps({"graph_id": "G9", "graph_version": "v2", "nodes": ["b-pdx"]}).ljust(st.st_size))
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual(screen.graph_for_ref(self.root, "G1", "v2")[0], "a-drawio")

    def test_a_rewritten_graph_is_seen(self):
        self.assertEqual(screen.graph_for_ref(self.root, "G1", "v2")[1]["nodes"], ["b-pdf"])
        p = os.path.join(self.root, "a-drawio", "graph.json")
        write(p, {"graph_id": "G1", "graph_version": "v2", "nodes": ["새로"]})
        bump(p)
        self.assertEqual(screen.graph_for_ref(self.root, "G1", "v2")[1]["nodes"], ["새로"])


class StartupImportsTest(unittest.TestCase):
    def test_the_main_window_module_does_not_load_openpyxl_or_networkx(self):
        """openpyxl은 내보낼 때만, networkx는 그래프 계산 때만 읽는다(각각 시작이 0.5초 안팎 늦어져서)."""
        code = ("import sys\nfrom hazop.app import make_application\nfrom hazop.app.main_window import MainWindow\n"
                "print([m for m in ('openpyxl', 'networkx') if m in sys.modules])")
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), timeout=120)
        self.assertEqual(out.stdout.strip(), "[]", out.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
