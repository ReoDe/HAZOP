"""추출 실행 정보 곁 파일(extraction_run.json, hazop/extract/runinfo.py, 기획서 specs/pid-symbol-dictionary.md D8).

추출 단계가 추출 결과 폴더에 기호 사전 판을 남긴다. 그래프는 extraction.json만 읽으므로 이 파일은 graph_version과 무관하다.
"""

import glob
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import build_graph
import extract_drawio
import extract_pdf
import extract_raster

from hazop import paths
from hazop.app import data
from hazop.extract import runinfo
from hazop.extract.adapters import pdf_vector

SAMPLE = paths.folder("references", "pid-samples", "SNP-M-102_RCS-pressurizer", "SNP-M-102_RCS-pressurizer")
HAS_PDF = importlib.util.find_spec("pdfplumber") is not None


def read_run(out_dir):
    with open(os.path.join(out_dir, runinfo.FILE_NAME), encoding="utf-8") as fh:
        return json.load(fh)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class WorkRootCase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="hazop-runinfo-")
        self.addCleanup(shutil.rmtree, self.work, True)
        patch = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.work})
        patch.start()
        self.addCleanup(patch.stop)
        self.out = paths.output_root("extract")


@unittest.skipUnless(HAS_PDF, "pdfplumber 없음(전용 venv에서 실행)")
class PdfRunInfoTest(WorkRootCase):
    pdf = SAMPLE + ".pdf"

    def test_extraction_leaves_the_dictionary_versions_beside_the_result(self):
        result, out_dir = extract_pdf.run_one(self.pdf, self.out)
        doc = read_run(out_dir)
        self.assertEqual(sorted(doc), ["extracted", "extraction_run_id", "extractor", "schema_version",
                                       "symbol_dictionary_versions", "written_at"])
        self.assertEqual((doc["schema_version"], doc["extractor"], doc["extracted"]), ("1", "pdf_vector", True))
        self.assertEqual(doc["extraction_run_id"], result["extraction_run_id"])
        self.assertEqual(doc["symbol_dictionary_versions"], pdf_vector.symbol_library().versions)
        self.assertEqual(sorted(doc["symbol_dictionary_versions"]), ["APR1400", "공통"])
        self.assertRegex(doc["written_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_reextraction_overwrites_with_the_new_run(self):
        with mock.patch.object(runinfo.store_io, "now_utc", return_value="2026-11-11T00:00:00Z"):
            _, out_dir = extract_pdf.run_one(self.pdf, self.out)
        self.assertEqual(read_run(out_dir)["written_at"], "2026-11-11T00:00:00Z")
        changed = dict(pdf_vector.symbol_library().versions, 공통="000000000000")
        with mock.patch.object(runinfo.store_io, "now_utc", return_value="2026-11-12T00:00:00Z"), \
                mock.patch.object(pdf_vector.symbol_library(), "versions", changed):
            _, again = extract_pdf.run_one(self.pdf, self.out)
        self.assertEqual(again, out_dir)
        doc = read_run(out_dir)
        self.assertEqual((doc["written_at"], doc["symbol_dictionary_versions"]["공통"]),
                         ("2026-11-12T00:00:00Z", "000000000000"))
        self.assertEqual(sorted(os.listdir(out_dir)), ["extraction.json", runinfo.FILE_NAME, "validation_report.md"])

    def test_page_that_could_not_be_extracted_also_gets_the_record(self):
        name = lambda _p: "page"  # noqa: E731
        with mock.patch.object(extract_pdf.pdf_vector, "extract", side_effect=ValueError("읽기 실패")):
            done, skipped = extract_pdf.run_pages(self.pdf, self.out, [0], out_name=name)
        self.assertEqual((done, len(skipped)), ([], 1))
        out_dir = os.path.join(self.out, "page")
        self.assertEqual(sorted(os.listdir(out_dir)), [runinfo.FILE_NAME, extract_pdf.NOT_EXTRACTED])
        doc = read_run(out_dir)
        self.assertEqual((doc["extractor"], doc["extracted"], doc["extraction_run_id"]), ("pdf_vector", False, None))
        self.assertEqual(doc["symbol_dictionary_versions"], pdf_vector.symbol_library().versions)

    def test_record_follows_the_page_state_across_reextraction(self):
        name = lambda _p: "page"  # noqa: E731
        out_dir = os.path.join(self.out, "page")
        extract_pdf.run_pages(self.pdf, self.out, [0], out_name=name)
        self.assertTrue(read_run(out_dir)["extracted"])
        with mock.patch.object(extract_pdf.pdf_vector, "extract", side_effect=ValueError("읽기 실패")):
            extract_pdf.run_pages(self.pdf, self.out, [0], out_name=name)
        self.assertFalse(read_run(out_dir)["extracted"])
        done, _ = extract_pdf.run_pages(self.pdf, self.out, [0], out_name=name)
        self.assertEqual(read_run(out_dir)["extraction_run_id"], done[0][1]["extraction_run_id"])

    def test_extraction_bytes_and_graph_version_do_not_depend_on_the_record(self):
        _, out_dir = extract_pdf.run_one(self.pdf, self.out)
        extraction = os.path.join(out_dir, "extraction.json")
        with_record = read_bytes(extraction)
        graph, _ = build_graph.build_one(extraction, paths.output_root("graph"))
        os.remove(os.path.join(out_dir, runinfo.FILE_NAME))
        without, _ = build_graph.build_one(extraction, paths.output_root("graph"))
        self.assertEqual(without["graph_version"], graph["graph_version"])
        with mock.patch.object(runinfo, "write"):
            _, plain_dir = extract_pdf.run_one(self.pdf, self.out)
        self.assertEqual(plain_dir, out_dir)
        self.assertFalse(os.path.exists(os.path.join(out_dir, runinfo.FILE_NAME)))
        self.assertEqual(read_bytes(extraction), with_record)

    def test_folder_from_before_the_record_existed_is_still_read(self):
        _, out_dir = extract_pdf.run_one(self.pdf, self.out)
        os.remove(os.path.join(out_dir, runinfo.FILE_NAME))
        name = os.path.basename(out_dir)
        self.assertEqual([e["name"] for e in data.list_extractions()], [name])
        graph, _ = build_graph.build_one(os.path.join(out_dir, "extraction.json"), paths.output_root("graph"))
        self.assertTrue(graph["graph_version"])


class DrawioRunInfoTest(WorkRootCase):
    def test_extractor_without_a_dictionary_records_no_versions(self):
        result, out_dir = extract_drawio.run_one(SAMPLE + ".drawio", self.out)
        doc = read_run(out_dir)
        self.assertEqual((doc["extractor"], doc["extracted"], doc["symbol_dictionary_versions"]), ("drawio", True, None))
        self.assertEqual(doc["extraction_run_id"], result["extraction_run_id"])

    def test_extraction_bytes_do_not_depend_on_the_record(self):
        _, out_dir = extract_drawio.run_one(SAMPLE + ".drawio", self.out)
        with_record = read_bytes(os.path.join(out_dir, "extraction.json"))
        with mock.patch.object(runinfo, "write"):
            extract_drawio.run_one(SAMPLE + ".drawio", self.out)
        self.assertEqual(read_bytes(os.path.join(out_dir, "extraction.json")), with_record)


class RasterRunInfoTest(WorkRootCase):
    def test_raster_extraction_records_the_dictionary_versions(self):
        """래스터 추출도 pdf_vector.build_extraction으로 기호를 정하므로 사전 판을 남긴다(OpenCV 없이 대역으로 확인)."""
        fake = {"extraction_run_id": "extract-raster-x", "drawing": {"drawing_number": "R-1"}}
        with mock.patch.object(extract_raster.raster, "extract", return_value=fake), \
                mock.patch.object(extract_raster.report, "render", return_value=""):
            _, out_dir = extract_raster.run_one(glob.glob(SAMPLE + ".*")[0], self.out)
        doc = read_run(out_dir)
        self.assertEqual((doc["extractor"], doc["extracted"], doc["extraction_run_id"]),
                         ("raster", True, "extract-raster-x"))
        self.assertEqual(doc["symbol_dictionary_versions"], pdf_vector.symbol_library().versions)


if __name__ == "__main__":
    unittest.main()
