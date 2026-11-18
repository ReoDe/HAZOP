"""다시 추출 직전 검토구간 표지 채우기(hazop.app.data.prepare_reextract). 실행: python -m unittest tests.test_prepare_reextract

표지(판 사진)가 없는 옛 0.2 검토구간 집합은 같은 판으로 한 번 읽혀야 표지가 채워진다. 그 전에 다시 추출이 먼저 일어나면 순번 구성요소가 모두 묘비가 된다.
그래서 추출 결과를 덮어쓰는 모든 길이 덮어쓰기 전에 한 번 채운다. 여기서는 (1) 채우면 묘비가 실제로 바뀐 것만 남는지, (2) 길마다 덮어쓰기 앞에서
부르는지(표제란 확정은 앞 그래프를 비켜 두기 앞에서 한 번만), (3) 실패·없음이 추출을 막지 않는지 본다. 저장은 임시 작업 루트 아래에만 한다.
"""

import contextlib
import copy
import os
import shutil
import tempfile
import unittest
from unittest import mock

from hazop import paths
from hazop.app import data
from hazop.study import nodes as sn
from hazop.study import results as res
from tests.test_study_migrate import AT, DEVS, PLACES, drawn

PID = "P-REEXTRACT"


def project_graph(version, places):
    g = drawn(version, places)
    g["project_id"] = PID
    return g


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-prep-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patch = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.tmp})
        patch.start()
        self.addCleanup(patch.stop)
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)


class MarkFillTest(Base):
    def saved_old_set(self):
        """이전 판 앱이 저장한 꼴: 표지·id 근거·묘비가 없는 0.2 집합."""
        g1 = project_graph("v-1", PLACES)
        ns = sn.confirm(sn.propose(g1, at=AT), g1, "김검토", at=AT)
        bare = {k: v for k, v in ns.items() if k not in ("graph_member_marks", "graph_member_basis", "tombstones")}
        sn.save(dict(bare, schema_version="0.2"))
        return g1, ns

    def moved(self):
        """다시 추출 뒤의 그래프: V2만 다른 자리로 갔다(나머지는 같은 자리)."""
        return project_graph("v-2", dict(PLACES, V2=[200, 0, 5, 5]))

    def test_without_filling_every_numbered_member_is_lost(self):
        self.saved_old_set()
        got = sn.load(self.moved())
        self.assertEqual([m for n in got["nodes"] for m in n["members"]], [], "표지 없이 다시 추출하면 순번 구성요소가 전부 묘비가 된다(이 시험의 전제)")

    def test_filling_before_the_re_extract_loses_only_what_really_changed(self):
        g1, ns = self.saved_old_set()
        self.assertTrue(data.prepare_reextract(PID, graph_fn=lambda pid: g1))
        got = sn.load(self.moved())
        holder = sn.nodes_of(ns, next(n["entity_id"] for n in g1["nodes"] if n["tag"] is None and n["source_object_id"].endswith("0003")))
        lost = sorted(n["node_id"] for n in got["nodes"] if n.get("lost"))
        self.assertEqual(lost, sorted(holder), "묘비는 실제로 자리가 바뀐 V2를 가진 구간에만")
        kept = [n for n in got["nodes"] if n["node_id"] not in holder]
        self.assertTrue(kept and all(n["members"] for n in kept), "나머지 구간은 구성요소를 그대로 갖는다")

    def test_marks_are_written_to_the_saved_set(self):
        g1, _ns = self.saved_old_set()
        data.prepare_reextract(PID, graph_fn=lambda pid: g1)
        doc = sn.load(g1)
        self.assertEqual(doc["schema_version"], sn.SCHEMA_VERSION)
        self.assertTrue(doc["graph_member_marks"])


class SkipTest(Base):
    def test_no_node_set_means_the_graph_is_not_even_built(self):
        calls = []
        self.assertFalse(data.prepare_reextract(PID, graph_fn=lambda pid: calls.append(pid)))
        self.assertEqual(calls, [])
        self.assertFalse(data.prepare_reextract(None, graph_fn=lambda pid: calls.append(pid)))
        self.assertEqual(calls, [])

    def test_a_failing_read_does_not_raise(self):
        g1 = project_graph("v-1", PLACES)
        sn.save(sn.confirm(sn.propose(g1, at=AT), g1, "김검토", at=AT))

        def boom(pid):
            raise OSError("그래프 파일 없음")
        with self.assertLogs("hazop.app.data", level="WARNING"):
            self.assertFalse(data.prepare_reextract(PID, graph_fn=boom))


class Stubs:
    """추출 길 하나의 대역: 덮어쓰기(extract)가 일어난 순서를 log에 남긴다."""

    def __init__(self, test, fmt):
        self.log = []
        record = {"project_id": PID, "format": fmt}
        self.patches = [
            mock.patch.object(data.registry, "load_for_extraction", lambda path: (record, "orig")),
            mock.patch.object(data.raster_scan, "is_scan_record", lambda r, o: fmt == "scan"),
            mock.patch.object(data, "prepare_reextract", lambda pid, graph_fn=None: self.log.append(("prepare", pid)) or True),
            mock.patch.object(data, "_extract_scan_pages", lambda *a, **k: self.log.append(("extract", "scan")) or {}),
            mock.patch.object(data, "_extract_pdf_pages", lambda *a, **k: self.log.append(("extract", "pdf")) or {}),
            mock.patch.object(data, "script_module", lambda name: self),
            mock.patch.object(data.registry, "registered_svgs", lambda *a, **k: []),
            mock.patch.object(data, "_with_kg", lambda out, pid: out),
        ]
        for p in self.patches:
            p.start()
            test.addCleanup(p.stop)

    def run_one(self, *a, **k):
        self.log.append(("extract", "one"))
        return {}, "dir"

    def build_one(self, *a, **k):
        return {}, "gdir"


class PathsTest(Base):
    def test_every_extract_and_graph_branch_prepares_before_overwriting(self):
        for fmt, want in (("pdf", "pdf"), ("scan", "scan"), ("dexpi", "one"), ("drawio", "one")):
            with self.subTest(fmt=fmt):
                s = Stubs(self, fmt)
                data.extract_and_graph("reg.json")
                self.assertEqual(s.log, [("prepare", PID), ("extract", want)])

    def test_inside_prepared_for_reextract_extract_and_graph_does_not_prepare_again(self):
        s = Stubs(self, "pdf")
        with data.prepared_for_reextract(PID):
            s.log.append(("set_aside", None))          # 표제란 확정: 앞 그래프를 비켜 둔 뒤에 추출한다
            data.extract_and_graph("reg.json")
        self.assertEqual(s.log, [("prepare", PID), ("set_aside", None), ("extract", "pdf")], "채우기는 비키기 앞에서 한 번만")
        data.extract_and_graph("reg.json")             # 바깥으로 나오면 다시 평소대로
        self.assertEqual(s.log[-2:], [("prepare", PID), ("extract", "pdf")])

    def test_titleblock_confirm_job_prepares_before_the_extraction_it_starts(self):
        from hazop.shell import api, api_titleblock
        s = Stubs(self, "pdf")
        engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=lambda e: None, run_jobs=lambda job_id, fn: fn())
        engine.settings["project_id"] = PID

        def fn(pid, dry, progress):
            if dry:
                return {"ok": True, "changed": True, "re_extract": True}
            s.log.append(("set_aside", None))
            data.extract_and_graph("reg.json")
            return {"ok": True, "version": 2, "re_extracted": True, "carried": [], "released_sheet_confirmations": [], "notes": []}
        with mock.patch.object(api_titleblock.tb, "row", lambda pid, mid: {"name": "표제"}):
            api_titleblock._run(engine, {"material_id": "m1"}, fn)
        self.assertEqual(s.log, [("prepare", PID), ("set_aside", None), ("extract", "pdf")])

    def test_titleblock_confirm_without_re_extract_does_not_prepare(self):
        from hazop.shell import api, api_titleblock
        s = Stubs(self, "pdf")
        engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=lambda e: None, run_jobs=lambda job_id, fn: fn())
        engine.settings["project_id"] = PID

        def fn(pid, dry, progress):
            return {"ok": True, "changed": True, "re_extract": False, "version": 2, "re_extracted": False, "carried": [],
                    "released_sheet_confirmations": [], "notes": []}
        with mock.patch.object(api_titleblock.tb, "row", lambda pid, mid: {"name": "표제"}):
            api_titleblock._run(engine, {"material_id": "m1"}, fn)
        self.assertEqual(s.log, [])


if __name__ == "__main__":
    unittest.main()
