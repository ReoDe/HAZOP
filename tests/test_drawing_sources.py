"""같은 도면 번호의 drawio·PDF·DEXPI 원본이 서로 덮어쓰지 않는다(HZ-PLN-22 §4.2 (나), DEXPI 검토 4번 차단).
고치기 전: 같은 번호로 추출하면 폴더(=사람 수정 기록 이름)가 같고, 프로젝트 그래프는 마지막에 추출한 형식을 말없이 골랐다.
실행: python -m unittest tests.test_drawing_sources
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import extract_dexpi  # noqa: E402
import extract_drawio  # noqa: E402
from hazop import paths, store_io  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from hazop.graph import build, project, sources  # noqa: E402
from hazop.kg import auto  # noqa: E402
from hazop.register import registry  # noqa: E402

SNP = sorted(glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio")))
DEXPI = os.path.join(REPO_ROOT, "tests", "fixtures", "dexpi", "small-pid-dexpi2.xml")
DWG = "SNP-M-101"
PROJECT = "P-SRC"


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work")
        patcher = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.work, "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.extract_root = paths.output_root("extract")
        self.graph_root = paths.output_root("graph")

    def dexpi_file(self, number=DWG):
        with open(DEXPI, encoding="utf-8") as fh:
            text = fh.read().replace("TEST-1", number)
        path = os.path.join(self.tmp, "in", number + ".xml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def make_graph(self, extraction, out_dir, project_id=PROJECT, age=0.0):
        """extraction.json과 graph.json을 폴더 이름대로 쓴다(그래프 폴더는 추출 폴더의 짝). age초 전에 쓴 것처럼 시각을 맞춘다."""
        name = os.path.basename(out_dir)
        extraction = dict(extraction, project_id=project_id)
        graph = build.build_graph(extraction)
        for root, doc, fname in ((self.extract_root, extraction, "extraction.json"), (self.graph_root, graph, "graph.json")):
            folder = os.path.join(root, name)
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, fname)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            when = time.time() - age
            os.utime(path, (when, when))
        return name

    def drawio_pair(self, age):
        res, out = extract_drawio.run_one(SNP[0], self.extract_root, svg=None)
        return self.make_graph(res, out, age=age)

    def dexpi_pair(self, age):
        res, out = extract_dexpi.run_one(self.dexpi_file(), self.extract_root)
        return self.make_graph(res, out, age=age)


class FolderCollisionTest(Base):

    def test_dexpi_and_drawio_with_the_same_number_use_different_folders_and_edit_files(self):
        r1, d1 = extract_drawio.run_one(SNP[0], self.extract_root, svg=None)
        self.assertEqual(r1["drawing"]["drawing_number"], DWG)
        r2, d2 = extract_dexpi.run_one(self.dexpi_file(), self.extract_root)
        self.assertEqual(r2["drawing"]["drawing_number"], DWG)
        self.assertNotEqual(os.path.normcase(d1), os.path.normcase(d2))
        self.assertNotEqual(corrections.store_path(os.path.basename(d1)), corrections.store_path(os.path.basename(d2)))
        with open(os.path.join(d1, "extraction.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["source"]["format"], "drawio")  # drawio 쪽이 덮어써지지 않았다


class SelectionTest(Base):

    def test_the_last_extracted_format_does_not_silently_win(self):
        old = self.drawio_pair(age=100.0)
        self.dexpi_pair(age=0.0)  # 더 최근에 추출한 DEXPI
        picked = project.pick_graphs(PROJECT)
        self.assertEqual({v[2] for v in picked.values()}, {old})
        graphs, notes = auto.project_graphs(PROJECT, self.graph_root)
        self.assertEqual(len(graphs), 1)
        self.assertIn("-drawio-", graphs[0]["source"]["extraction_run_id"])
        self.assertTrue(any("사람이 고르기 전에는" in n for n in notes))

    def test_conflict_is_reported_with_both_candidates(self):
        old, new = self.drawio_pair(age=100.0), self.dexpi_pair(age=0.0)
        found = sources.conflicts(PROJECT)
        self.assertEqual(len(found), 1)
        c = found[0]
        self.assertEqual((c["drawing_number"], c["formats"], c["in_use"], c["in_use_format"], c["chosen"]),
                         (DWG, ["dexpi", "drawio"], old, "drawio", None))
        self.assertEqual(sorted(x["name"] for x in c["candidates"]), sorted([old, new]))
        self.assertEqual(sorted(x["format"] for x in c["candidates"]), ["dexpi", "drawio"])

    def test_the_choice_is_taken_saved_and_followed(self):
        old, new = self.drawio_pair(age=100.0), self.dexpi_pair(age=0.0)
        record = sources.choose(PROJECT, DWG, "dexpi", "홍길동", at="2026-11-14T00:00:00+00:00")
        self.assertEqual(record, {"format": "dexpi", "by": "홍길동", "at": "2026-11-14T00:00:00+00:00"})
        self.assertEqual({v[2] for v in project.pick_graphs(PROJECT).values()}, {new})
        graphs, notes = auto.project_graphs(PROJECT, self.graph_root)
        self.assertEqual(len(graphs), 1)
        self.assertFalse([n for n in notes if "사람이 고르기" in n])
        self.assertEqual(sources.conflicts(PROJECT)[0]["chosen"], "dexpi")
        with open(sources.choices_path(PROJECT), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["kind"], doc["chosen"][DWG]["format"]), (sources.KIND, "dexpi"))
        sources.choose(PROJECT, DWG, "drawio", "홍길동")  # 되돌리면 옛 원본이 그대로 다시 쓰인다
        self.assertEqual({v[2] for v in project.pick_graphs(PROJECT).values()}, {old})
        # 두 형식의 추출 결과 폴더는 둘 다 그대로 남아 있다
        self.assertTrue(os.path.isfile(os.path.join(self.extract_root, old, "extraction.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.extract_root, new, "extraction.json")))

    def test_choose_refuses_what_it_cannot_follow(self):
        self.drawio_pair(age=100.0)
        with self.assertRaises(ValueError):  # 충돌이 없다
            sources.choose(PROJECT, DWG, "drawio", "홍길동")
        self.dexpi_pair(age=0.0)
        with self.assertRaises(ValueError):
            sources.choose(PROJECT, DWG, "pdf_vector", "홍길동")  # 그 형식의 그래프가 없다
        with self.assertRaises(ValueError):
            sources.choose(PROJECT, DWG, "dexpi", "")
        with self.assertRaises(ValueError):
            sources.choose(PROJECT, "NO-SUCH", "dexpi", "홍길동")
        self.assertFalse(os.path.exists(sources.choices_path(PROJECT)))

    def test_choice_write_is_atomic_and_a_changed_file_is_not_overwritten(self):
        self.drawio_pair(age=100.0)
        self.dexpi_pair(age=0.0)
        sources.choose(PROJECT, DWG, "dexpi", "a")
        path = sources.choices_path(PROJECT)
        real = store_io.write_json

        def raced(p, obj, expect=store_io.ANY, **kw):
            with open(path, "w", encoding="utf-8") as fh:  # 읽은 뒤 다른 쪽이 파일을 바꿈
                json.dump({"chosen": {}}, fh)
            return real(p, obj, expect=expect, **kw)
        with mock.patch.object(sources.store_io, "write_json", side_effect=raced):
            with self.assertRaises(store_io.Conflict):
                sources.choose(PROJECT, DWG, "drawio", "b")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"chosen": {}})
        self.assertEqual([n for n in os.listdir(os.path.dirname(path)) if n.endswith(".tmp")], [])

    def test_a_broken_choice_file_falls_back_to_the_default(self):
        old = self.drawio_pair(age=100.0)
        self.dexpi_pair(age=0.0)
        os.makedirs(os.path.dirname(sources.choices_path(PROJECT)), exist_ok=True)
        with open(sources.choices_path(PROJECT), "w", encoding="utf-8") as fh:
            fh.write("{깨짐")
        self.assertEqual({v[2] for v in project.pick_graphs(PROJECT).values()}, {old})

    def test_a_choice_for_a_format_that_is_gone_is_ignored(self):
        old = self.drawio_pair(age=100.0)
        new = self.dexpi_pair(age=0.0)
        sources.choose(PROJECT, DWG, "dexpi", "a")
        shutil.rmtree(os.path.join(self.graph_root, new))
        self.assertEqual({v[2] for v in project.pick_graphs(PROJECT).values()}, {old})
        self.assertEqual(sources.conflicts(PROJECT), [])

    def test_same_format_keeps_the_existing_rule_latest_wins(self):
        """기존 프로젝트(drawio만)의 선택은 바뀌지 않는다: 같은 형식이면 가장 최근 것, 형식을 읽지도 않는다."""
        a = self.drawio_pair(age=100.0)
        res, out = extract_drawio.run_one(SNP[0], self.extract_root, svg=None)
        os.rename(out, out + "-again")
        b = self.make_graph(res, out + "-again", age=0.0)
        self.assertEqual({v[2] for v in project.pick_graphs(PROJECT).values()}, {b})
        self.assertNotEqual(a, b)
        self.assertEqual(sources.conflicts(PROJECT), [])

    def test_six_sample_drawings_are_selected_exactly_as_before(self):
        names = {}
        for path in SNP:
            res, out = extract_drawio.run_one(path, self.extract_root, svg=None)
            names[res["drawing"]["drawing_number"]] = self.make_graph(res, out)
        picked = project.pick_graphs(PROJECT)
        self.assertEqual(sorted(v[2] for v in picked.values()), sorted(names.values()))
        graphs, notes = auto.project_graphs(PROJECT, self.graph_root)
        self.assertEqual((len(graphs), notes), (6, []))
        # 프로젝트 그래프 판은 고른 도면 그래프만으로 정해진다(선택 규칙이 판에 끼어들지 않는다)
        versions = {g["graph_id"]: g["graph_version"] for g in graphs}
        self.assertEqual(versions, {v[1]["graph_id"]: v[1]["graph_version"] for v in picked.values()})


class RegistrationNoticeTest(Base):

    def test_registering_another_format_with_the_same_confirmed_number_reports_the_conflict(self):
        store = os.path.join(self.tmp, "store")
        meta = {"drawing_number": DWG, "title": "t", "design_revision": "0", "by": "tester", "reason": "시험"}
        first = registry.register(SNP[0], PROJECT, store_root=store, actor="tester", metadata=meta)
        self.assertEqual(first["outcome"], "registered")
        self.assertNotIn("conflicts", first)
        second = registry.register(self.dexpi_file(), PROJECT, store_root=store, actor="tester", metadata=meta)
        self.assertEqual(second["outcome"], "registered")
        self.assertEqual([(c["drawing_number"], sorted(m["format"] for m in c["materials"])) for c in second["conflicts"]],
                         [(DWG, ["dexpi", "drawio"])])
        self.assertTrue(any("사람이 골라야" in n for n in second["notes"]))
        other = dict(meta, drawing_number="SNP-OTHER")
        third = registry.register(self.dexpi_file("SNP-OTHER"), PROJECT, store_root=store, actor="tester", metadata=other)
        self.assertNotIn("conflicts", third)  # 번호가 다르면 충돌이 아니다


if __name__ == "__main__":
    unittest.main()
