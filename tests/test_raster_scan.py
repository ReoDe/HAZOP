"""스캔 도면 읽기(HZ-PLN-23) 시험. 실행: python -m unittest tests.test_raster_scan

입력 판별·해상도 등급·좌표 환산·OCR 타일 합치기·등록 판별은 OpenCV 없이 돈다(시험 venv).
기울기 보정은 OpenCV가 있을 때만, 스캔 PDF를 끝까지 읽는 시험은 래스터 venv Python(HAZOP_RASTER_PYTHON 또는
%USERPROFILE%\\.hazop\\venv-raster-py312)이 있을 때만 돈다. 없으면 건너뛴다."""

import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.extract.adapters import raster, raster_scan  # noqa: E402
from hazop.register import fileinfo  # noqa: E402

HAS_CV = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None
HAS_PDFIUM = importlib.util.find_spec("pypdfium2") is not None
HAS_PIL = importlib.util.find_spec("PIL") is not None
SNP_102 = os.path.join(REPO_ROOT, "resources", "references", "pid-samples", "SNP-M-102_RCS-pressurizer",
                       "SNP-M-102_RCS-pressurizer.pdf")


def vector_pdf():
    """선 두 줄과 글자 한 줄이 있는 최소 벡터 PDF(쪽 400×300pt)."""
    content = b"BT /F1 12 Tf 50 250 Td (P-101) Tj ET\n2 w 50 100 m 350 100 l S\n50 50 m 50 200 l S\n"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for o in offs:
        out.write(b"%010d 00000 n \n" % o)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def drawing_image(w=1650, h=1100):
    """흰 바탕에 검은 선 몇 줄을 그린 회색조 그림(Pillow)."""
    from PIL import Image, ImageDraw
    im = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(im)
    d.line([(100, 300), (1500, 300)], fill=0, width=4)
    d.line([(300, 100), (300, 900)], fill=0, width=4)
    d.rectangle([600, 250, 700, 350], outline=0, width=4)
    return im


def scan_pdf_bytes(im, dpi):
    """그림 한 장을 쪽 전체로 담은 PDF(Pillow PDF 저장, 스캐너가 만드는 꼴과 같다)."""
    buf = io.BytesIO()
    im.save(buf, "PDF", resolution=float(dpi))
    return buf.getvalue()


def image_bytes(im, fmt, dpi=None):
    buf = io.BytesIO()
    kw = {"dpi": (dpi, dpi)} if dpi else {}
    im.save(buf, fmt, **kw)
    return buf.getvalue()


class ResolutionTest(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(raster_scan.resolution_level(600), "ok")
        self.assertEqual(raster_scan.resolution_level(300), "ok")
        self.assertEqual(raster_scan.resolution_level(299.9), "low")
        self.assertEqual(raster_scan.resolution_level(200), "low")
        self.assertEqual(raster_scan.resolution_level(199), "too_low")

    def test_guidance_names_dpi(self):
        self.assertIsNone(raster_scan.resolution_guidance(300))
        self.assertIn("150 dpi", raster_scan.resolution_guidance(150))
        self.assertIn("300dpi", raster_scan.resolution_guidance(250))

    def test_read_dpi_cap(self):
        self.assertEqual(raster_scan.read_dpi(600), 400)
        self.assertEqual(raster_scan.read_dpi(250), 250)

    def test_trusted_image_dpi(self):
        """그림 파일의 dpi는 150~1200만 믿는다. 72·96 같은 화면 값과 비율만 적힌 값(1)은 A3 가정으로 간다."""
        self.assertEqual(raster_scan.trusted_dpi(300), 300)
        self.assertIsNone(raster_scan.trusted_dpi(96))
        self.assertIsNone(raster_scan.trusted_dpi(1))
        self.assertIsNone(raster_scan.trusted_dpi(None))
        self.assertIsNone(raster_scan.trusted_dpi(5000))


@unittest.skipUnless(HAS_PDFIUM and HAS_PIL, "pypdfium2·Pillow 없음")
class ClassifyTest(unittest.TestCase):
    def test_scan_pdf(self):
        info = raster_scan.classify_pdf_page(scan_pdf_bytes(drawing_image(), 300))
        self.assertEqual(info["kind"], "scan")
        self.assertAlmostEqual(info["dpi"], 300, delta=1)
        self.assertAlmostEqual(info["px_per_pt"], 300 / 72, delta=0.02)
        self.assertEqual(info["level"], "ok")
        self.assertEqual(info["image_px"], [1650, 1100])
        self.assertFalse(info["text_layer"])

    def test_low_resolution_scan_pdf(self):
        info = raster_scan.classify_pdf_page(scan_pdf_bytes(drawing_image(), 150))
        self.assertEqual(info["kind"], "scan")
        self.assertEqual(info["level"], "too_low")

    def test_vector_pdf(self):
        info = raster_scan.classify_pdf_page(vector_pdf())
        self.assertEqual(info["kind"], "vector")
        self.assertIsNone(info["dpi"])

    def test_image_file_scale(self):
        im = drawing_image()
        with_dpi = raster_scan.image_scale(image_bytes(im, "PNG", 300))
        self.assertEqual(with_dpi["dpi_source"], "file")
        self.assertAlmostEqual(with_dpi["dpi"], 300, delta=0.5)
        no_dpi = raster_scan.image_scale(image_bytes(im, "PNG"))
        self.assertEqual(no_dpi["dpi_source"], "assumed_a3")
        self.assertAlmostEqual(no_dpi["px_per_pt"], 1650 / raster.PARAMS["nominal_page_width_pt"], places=4)


class PagePointsTest(unittest.TestCase):
    def test_coordinates_scale_to_points(self):
        ex = {"nodes": [{"local_id": "n1", "geometry": {"x": 300.0, "y": 600.0, "width": 30.0, "height": 60.0}},
                        {"local_id": "n2", "geometry": None}],
              "relations": [{"local_id": "r1", "endpoints": [{"point": [0.0, 30.0]}, {"point": [300.0, 30.0]}],
                             "waypoints": [[150.0, 30.0]]}],
              "coordinate_system": {"coordinate_space": "image_px", "unit": "px"}}
        out = raster_scan.to_page_points(ex, 3.0)
        self.assertEqual(out["nodes"][0]["geometry"], {"x": 100.0, "y": 200.0, "width": 10.0, "height": 20.0})
        self.assertIsNone(out["nodes"][1]["geometry"])
        self.assertEqual(out["relations"][0]["endpoints"][1]["point"], [100.0, 10.0])
        self.assertEqual(out["relations"][0]["waypoints"], [[50.0, 10.0]])
        self.assertEqual(out["coordinate_system"]["unit"], "pt")
        self.assertEqual(ex["nodes"][0]["geometry"]["x"], 300.0)  # 원본은 그대로


class OcrTileTest(unittest.TestCase):
    def test_tiles_cover_image_within_limit(self):
        tiles = raster.ocr_tiles(5100, 3300)
        self.assertTrue(all(x1 - x0 <= raster.OCR_TILE_MAX and y1 - y0 <= raster.OCR_TILE_MAX
                            for x0, y0, x1, y1 in tiles))
        self.assertEqual(min(t[0] for t in tiles), 0)
        self.assertEqual(max(t[2] for t in tiles), 5100)
        self.assertEqual(max(t[3] for t in tiles), 3300)
        self.assertEqual(raster.ocr_tiles(1800, 1200), [(0, 0, 1800, 1200)])

    def test_merge_drops_cut_duplicate(self):
        """두 타일에 걸친 줄: 한 타일 가장자리에서 잘린 조각은 버리고 온전한 줄을 남긴다."""
        def line(t, x0, x1, score=0.9):
            return {"text": t, "x0": x0, "x1": x1, "top": 100.0, "bottom": 120.0, "score": score}
        tile_a, tile_b = (0, 0, 1000, 1000), (700, 0, 1700, 1000)
        got = raster.merge_tile_lines([
            (tile_a, [line("P-1", 100.0, 160.0), line("LINE-20", 950.0, 1000.0)]),
            (tile_b, [line("LINE-2001", 950.0, 1100.0)])])
        self.assertEqual(sorted(o["text"] for o in got), ["LINE-2001", "P-1"])

    def test_merge_keeps_one_of_identical(self):
        a = {"text": "TT", "x0": 800.0, "x1": 820.0, "top": 10.0, "bottom": 20.0, "score": 0.8}
        b = dict(a, x0=800.5, x1=820.5, score=0.95)
        got = raster.merge_tile_lines([((0, 0, 1000, 1000), [a]), ((700, 0, 1700, 1000), [b])])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["score"], 0.95)

    def test_fine_lines_only_fill_gaps(self):
        """낮은 배율 줄(띄어쓰기 있음)을 남기고, 원래 해상도 줄은 겹치지 않는 것만 더한다."""
        coarse = [{"text": "TO SNP-M-102", "x0": 10.0, "x1": 110.0, "top": 10.0, "bottom": 22.0, "score": 0.9}]
        fine = [dict(coarse[0], text="TOSNP-M-102", score=0.99),
                {"text": "V-12", "x0": 300.0, "x1": 330.0, "top": 50.0, "bottom": 60.0, "score": 0.9}]
        self.assertEqual([o["text"] for o in raster.add_fine_lines(coarse, fine)], ["TO SNP-M-102", "V-12"])


@unittest.skipUnless(HAS_PIL, "Pillow 없음")
class RegistrationTest(unittest.TestCase):
    def blockers(self, info):
        return [b["check"] for b in info["blockers"]]

    @unittest.skipUnless(HAS_PDFIUM, "pypdfium2 없음")
    def test_scan_pdf_is_recognised_and_held(self):
        info = fileinfo.inspect("scan.pdf", scan_pdf_bytes(drawing_image(), 300))
        self.assertEqual(self.blockers(info), ["scan_not_connected"])
        self.assertEqual(info["scan"]["kind"], "scan")
        self.assertAlmostEqual(info["scan"]["dpi"], 300, delta=1)
        self.assertIn("300 dpi", info["blockers"][0]["reason"])

    def test_png_and_jpeg_are_recognised_and_held(self):
        for ext, fmt in ((".png", "PNG"), (".jpg", "JPEG"), (".jpeg", "JPEG")):
            with self.subTest(ext=ext):
                info = fileinfo.inspect("drawing" + ext, image_bytes(drawing_image(), fmt, 200))
                self.assertEqual(self.blockers(info), ["scan_not_connected"])
                self.assertEqual(info["scan"]["level"], "low")

    def test_png_with_wrong_extension_is_mismatch(self):
        info = fileinfo.inspect("drawing.jpg", image_bytes(drawing_image(), "PNG"))
        self.assertEqual(self.blockers(info), ["format_mismatch"])

    @unittest.skipUnless(HAS_PDFIUM, "pypdfium2 없음")
    def test_vector_pdf_has_no_scan_info(self):
        info = fileinfo.inspect("v.pdf", vector_pdf())
        self.assertNotIn("scan_not_connected", self.blockers(info))
        self.assertNotIn("scan", info)

    def test_design_document_does_not_take_images(self):
        info = fileinfo.inspect("a.png", image_bytes(drawing_image(), "PNG"), material_type="design_document")
        self.assertIn("unsupported_extension", self.blockers(info))


@unittest.skipUnless(HAS_CV, "OpenCV 없음(래스터 venv에서 실행)")
class DeskewTest(unittest.TestCase):
    def test_small_skew_is_measured_and_corrected(self):
        import numpy as np
        im = drawing_image().rotate(1.5, resample=3, fillcolor=255)
        gray = np.array(im)
        fixed, angle, state = raster.deskew(gray)
        self.assertEqual(state, "corrected")
        self.assertAlmostEqual(abs(angle), 1.5, delta=0.15)
        self.assertEqual(fixed.shape, gray.shape)
        _, again, state2 = raster.deskew(fixed)
        self.assertLess(abs(again), 0.15)

    def test_straight_image_is_left(self):
        import numpy as np
        gray = np.array(drawing_image())
        out, angle, state = raster.deskew(gray)
        self.assertEqual(state, "straight")
        self.assertIs(out, gray)

    def test_large_skew_is_not_rotated(self):
        import numpy as np
        gray = np.array(drawing_image().rotate(8, resample=3, fillcolor=255))
        out, _, state = raster.deskew(gray)
        self.assertIn(state, ("too_large", "unknown"))
        self.assertIs(out, gray)


RASTER_PY = raster_scan.raster_python()


@unittest.skipUnless(HAS_PDFIUM and HAS_PIL and RASTER_PY, "래스터 venv Python 없음")
@unittest.skipUnless(os.path.isfile(SNP_102), "SNP 표본 PDF 없음")
class ScanPdfEndToEndTest(unittest.TestCase):
    """SNP-M-102 벡터 PDF를 300dpi 스캔 PDF로 바꿔 끝까지 읽는다: 추출 → 그래프. 못 읽은 것은 미확인으로 남는다."""

    def test_scan_pdf_to_graph(self):
        import pypdfium2
        from hazop.graph import build as graph_build
        work = tempfile.mkdtemp(prefix="hazop-scan-test-")
        try:
            pg = pypdfium2.PdfDocument(SNP_102)[0]
            im = pg.render(scale=300 / 72, grayscale=True).to_pil()
            scan = os.path.join(work, "SNP-M-102-scan.pdf")
            with open(scan, "wb") as fh:
                fh.write(scan_pdf_bytes(im, 300))
            ex = raster_scan.extract_scan_pdf(scan, page=0, repo_root=work)
            self.assertEqual(ex["source"]["format"], "raster_scan_pdf")
            self.assertAlmostEqual(ex["coordinate_system"]["px_per_pt"], 300 / 72, delta=0.02)
            self.assertEqual(ex["validation"]["status"], "passed")
            checks = {u["check"] for u in ex["validation"]["unknowns"]}
            self.assertIn("scan_input", checks)
            self.assertGreaterEqual(ex["summary"]["nodes"], 12)
            self.assertGreaterEqual(ex["summary"]["texts"] + sum(1 for n in ex["nodes"] if n.get("tag")), 10)
            graph = graph_build.build_graph(ex)
            self.assertGreaterEqual(len(graph["nodes"]), 12)
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
