"""큰 프로젝트 열기 성능: 도면 이름 사전(project_ctx.graph_names)과 쪽 요약(data.extraction_brief)의 디스크 캐시. 실행: python -m unittest tests.test_graph_names_cache

앱을 새로 켤 때 143쪽 graph.json(수십 MB)·extraction.json을 모두 다시 읽지 않게 하는 캐시다. 입력 파일이 바뀌면 캐시를 쓰지 않고 다시 읽는지,
캐시가 깨져도 읽기가 그대로 되는지를 본다.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop import paths  # noqa: E402
from hazop.app import data, project_ctx  # noqa: E402
from hazop.graph import project  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NamesCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-namescache-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        from scripts.check_edit_screen import install_sample
        cls.names = [install_sample(os.environ["HAZOP_WORK_ROOT"], d) for d in ("SNP-M-101", "SNP-M-102")]

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        project_ctx._NAMES.clear()
        self.cache = paths.folder("cache", "graph-names.json")
        if os.path.exists(self.cache):
            os.remove(self.cache)

    def _pid(self):
        """샘플이 속한 프로젝트 ID(샘플 도면의 그래프에서 읽는다)."""
        from hazop.app import data as d
        g = d.viewer_build.load_graph(paths.output_root("graph"), self.names[0])
        return project.project_id_of(g)

    def test_second_start_reads_names_from_file_not_graphs(self):
        pid = self._pid()
        first = project_ctx.graph_names(pid)
        self.assertEqual(len(first), 2)
        self.assertTrue(os.path.isfile(self.cache), "이름 사전이 캐시 파일로 남아야 한다")
        project_ctx._NAMES.clear()                       # 앱을 새로 켠 것과 같다
        with mock.patch.object(project_ctx, "_read_graph_names", side_effect=AssertionError("graph.json을 다시 읽으면 안 된다")):
            self.assertEqual(project_ctx.graph_names(pid), first)

    def test_changed_graph_file_rereads(self):
        pid = self._pid()
        project_ctx.graph_names(pid)
        project_ctx._NAMES.clear()
        gp = os.path.join(paths.output_root("graph"), self.names[0], "graph.json")
        st = os.stat(gp)
        os.utime(gp, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))      # 바뀐 시각이 달라지면 지문이 달라진다
        with mock.patch.object(project_ctx, "_read_graph_names", wraps=project_ctx._read_graph_names) as read:
            self.assertEqual(len(project_ctx.graph_names(pid)), 2)
        read.assert_called_once()

    def test_changed_extraction_format_rereads(self):
        """같은 번호의 어느 형식을 쓸지는 추출 결과(extraction.json)의 형식으로 고르므로, 그 파일이 바뀌어도 다시 읽는다."""
        pid = self._pid()
        project_ctx.graph_names(pid)
        project_ctx._NAMES.clear()
        ep = data.extraction_path(self.names[0])
        st = os.stat(ep)
        os.utime(ep, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        with mock.patch.object(project_ctx, "_read_graph_names", wraps=project_ctx._read_graph_names) as read:
            project_ctx.graph_names(pid)
        read.assert_called_once()

    def test_broken_cache_file_is_ignored(self):
        pid = self._pid()
        first = project_ctx.graph_names(pid)
        for broken in ("{깨짐", json.dumps({"version": 99, "entries": {pid: {"fp": "x", "names": {"a": "b"}}}}), "[]"):
            project_ctx._NAMES.clear()
            with open(self.cache, "w", encoding="utf-8") as fh:
                fh.write(broken)
            self.assertEqual(project_ctx.graph_names(pid), first, broken)

    def test_empty_names_are_not_cached(self):
        project_ctx._names_to_disk("NOPE", "fp", {})
        self.assertFalse(os.path.exists(self.cache) and "NOPE" in (json.load(open(self.cache, encoding="utf-8")).get("entries") or {}))

    def test_drawings_read_saves_brief_cache(self):
        """도면 목록 읽기가 쪽 요약을 캐시 파일에 남겨, 다음 실행이 extraction.json을 다시 열지 않는다."""
        from hazop.shell import api
        brief_file = paths.folder("cache", "추출요약.json")
        if os.path.exists(brief_file):
            os.remove(brief_file)
        data._SOURCE_CACHE.clear()
        data._DISK.update(file=None, entries={}, dirty=False)

        class E:
            def graph_names(self_):
                return {"g%d" % i: n for i, n in enumerate(self.names)}

            def project_id(self_):
                return "P"

        api.ReadApi(E()).drawings()
        self.assertTrue(os.path.isfile(brief_file))
        data._SOURCE_CACHE.clear()
        data._DISK.update(file=None, entries={}, dirty=False)
        with mock.patch.object(data, "_read_brief", side_effect=AssertionError("extraction.json을 다시 읽으면 안 된다")):
            rows = api.ReadApi(E()).drawings()["drawings"]
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
