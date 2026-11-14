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
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract.adapters import raster, raster_proc, raster_scan  # noqa: E402
from hazop.register import fileinfo  # noqa: E402

HAS_CV = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None
HAS_PDFIUM = importlib.util.find_spec("pypdfium2") is not None
HAS_PIL = importlib.util.find_spec("PIL") is not None
SNP_102 = paths.folder("references", "pid-samples", "SNP-M-102_RCS-pressurizer", "SNP-M-102_RCS-pressurizer.pdf")


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
    def test_scan_pdf_is_registered_when_reader_exists(self):
        one = scan_pdf_bytes(drawing_image(), 300)
        with mock.patch.object(raster_scan, "reader_available", return_value=True):
            info = fileinfo.inspect("scan.pdf", one)
        self.assertEqual(self.blockers(info), [])
        self.assertEqual(info["scan"]["kind"], "scan")
        self.assertAlmostEqual(info["scan"]["dpi"], 300, delta=1)
        self.assertEqual([p["page_id"] for p in info["pages"]], ["page-1"])

    @unittest.skipUnless(HAS_PDFIUM, "pypdfium2 없음")
    def test_scan_needs_reader_component(self):
        with mock.patch.object(raster_scan, "reader_available", return_value=False):
            info = fileinfo.inspect("scan.pdf", scan_pdf_bytes(drawing_image(), 300))
        self.assertEqual(self.blockers(info), ["scan_reader_unavailable"])
        self.assertIn("스캔 읽기 구성요소가 없어 읽을 수 없음", info["blockers"][0]["reason"])

    @unittest.skipUnless(HAS_PDFIUM, "pypdfium2 없음")
    def test_scan_is_held_when_switched_off(self):
        with mock.patch.object(fileinfo, "SCAN_REGISTRATION", False):
            info = fileinfo.inspect("scan.pdf", scan_pdf_bytes(drawing_image(), 300))
        self.assertEqual(self.blockers(info), ["scan_not_connected"])
        self.assertIn("300 dpi", info["blockers"][0]["reason"])

    def test_png_and_jpeg_are_recognised(self):
        for ext, fmt in ((".png", "PNG"), (".jpg", "JPEG"), (".jpeg", "JPEG")):
            with self.subTest(ext=ext), mock.patch.object(raster_scan, "reader_available", return_value=True):
                info = fileinfo.inspect("drawing" + ext, image_bytes(drawing_image(), fmt, 200))
                self.assertEqual(self.blockers(info), [])
                self.assertEqual(info["scan"]["level"], "low")
                self.assertEqual(len(info["pages"]), 1)
                self.assertIn(info["format"], fileinfo.NO_SVG_FORMATS)

    def test_png_with_wrong_extension_is_mismatch(self):
        info = fileinfo.inspect("drawing.jpg", image_bytes(drawing_image(), "PNG"))
        self.assertEqual(self.blockers(info), ["format_mismatch"])

    @unittest.skipUnless(HAS_PDFIUM, "pypdfium2 없음")
    def test_vector_pdf_has_no_scan_info(self):
        info = fileinfo.inspect("v.pdf", vector_pdf())
        self.assertFalse({"scan_not_connected", "scan_reader_unavailable"} & set(self.blockers(info)))
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


class WordCutTest(unittest.TestCase):
    """OCR 띄어쓰기 되살리기의 낱말 조각: 줄 높이의 0.21 이상 빈 열에서만 가른다."""

    def test_cut_only_at_wide_gaps(self):
        cols = [1, 1, 0, 1, 1, 0, 0, 0, 0, 1, 1]
        self.assertEqual(raster._word_cuts(cols, 10), [(0, 5), (9, 11)])

    def test_edges_and_empty(self):
        self.assertEqual(raster._word_cuts([0, 0, 1, 1, 0, 0], 10), [(2, 4)])
        self.assertEqual(raster._word_cuts([0, 0, 0], 10), [])


class LabelBridgeTest(unittest.TestCase):
    """배관 라벨 바로 앞에서 꺾이는 선: 라벨 건너편 상대 선 중심선까지 늘인다(SNP-M-301 SI-L002)."""

    def setUp(self):
        self.px = raster._px(dict(raster.PARAMS), 1.0)  # 배율 1: px = pt

    def test_vertical_end_reaches_corner_across_label(self):
        hs = [{"a": 31.0, "b": 66.0, "c": 10.0, "t": 1.5}]
        vs = [{"a": 40.0, "b": 100.0, "c": 31.0, "t": 1.5}]
        used = raster._bridge_label_ends(hs, vs, [(18.0, 16.0, 45.0, 38.0)], self.px)
        self.assertEqual(vs[0]["a"], 10.0)
        self.assertEqual(used, {0})

    def test_word_label_is_not_bridged(self):
        """배관이 'VENT' 같은 낱말에서 끝나고 그 옆을 다른 배관이 지나가면 잇지 않는다(가짜 분기, 검토 r5 case A)."""
        hs = [{"a": 31.0, "b": 66.0, "c": 10.0, "t": 1.5}]
        vs = [{"a": 40.0, "b": 100.0, "c": 31.0, "t": 1.5}]
        used = raster._bridge_label_ends(hs, vs, [(18.0, 16.0, 45.0, 38.0)], self.px, labels=["VENT"])
        self.assertEqual((vs[0]["a"], used), (40.0, set()))
        raster._bridge_label_ends(hs, vs, [(18.0, 16.0, 45.0, 38.0)], self.px, labels=["SI-L002"])
        self.assertEqual(vs[0]["a"], 10.0)

    def test_no_corner_no_change(self):
        hs = [{"a": 50.0, "b": 80.0, "c": 10.0, "t": 1.5}]
        vs = [{"a": 40.0, "b": 100.0, "c": 31.0, "t": 1.5}]
        raster._bridge_label_ends(hs, vs, [(18.0, 16.0, 45.0, 38.0)], self.px)
        self.assertEqual(vs[0]["a"], 40.0)


@unittest.skipUnless(HAS_CV, "OpenCV 없음(래스터 venv에서 실행)")
class ArrowShapeTest(unittest.TestCase):
    def _arrow(self):
        import numpy as np
        import cv2
        sub = np.zeros((30, 40), np.uint8)
        cv2.fillPoly(sub, [np.array([[2, 2], [2, 27], [30, 14]])], 1)
        sub[12:17, 28:38] = 1  # 화살촉 꼭짓점에 붙은 배관 토막(삼각형 맞춤 0.85 미만으로 떨어뜨림)
        return sub

    def test_arrowhead_with_stub_becomes_triangle(self):
        px = raster._px(dict(raster.PARAMS), 6.0)  # 40px = 6.7pt: 화살촉 크기
        pts, _ = raster._poly_of(*raster._cv(), self._arrow(), 0, 0, raster.PARAMS, px, arrow_ok=True)
        self.assertEqual(len(pts) - 1, 3)
        tip = max(pts, key=lambda p: p[0])
        self.assertGreater(tip[0], 25)  # 오른쪽을 가리킨다

    def test_strict_fit_without_arrow_ok(self):
        px = raster._px(dict(raster.PARAMS), 6.0)  # 40px = 6.7pt: 화살촉 크기
        pts, _ = raster._poly_of(*raster._cv(), self._arrow(), 0, 0, raster.PARAMS, px, arrow_ok=False)
        self.assertNotEqual(len(pts) - 1, 3)

    def test_label_stub_beside_text_box(self):
        import numpy as np
        rest = np.zeros((60, 120), np.uint8)
        rest[29:31, 30:40] = 1   # 라벨 왼쪽 2.5pt 토막(배율 4: 10px)
        rest[29:31, 80:88] = 1   # 라벨 오른쪽 토막
        px = raster._px(dict(raster.PARAMS), 4.0)
        segs = raster._label_stubs(*raster._cv(), rest, np.zeros_like(rest), [(41.0, 20.0, 79.0, 40.0)], px, True)
        self.assertEqual(sorted((s["a"], s["b"]) for s in segs), [(30.0, 39.0), (80.0, 87.0)])


def image_pdf_bytes(page_w, page_h, img_w, img_h, text=None, extra_paths=0):
    """쪽을 덮는 회색조 그림 하나(+ 보이지 않는 글자층, + 선 경로)의 PDF. 그림 데이터는 흰색 한 줄만 넣는다(쪽을 그리지 않는 시험용)."""
    import zlib
    data = zlib.compress(b"\xff" * img_w)
    content = "q %g 0 0 %g 0 0 cm /Im0 Do Q\n" % (page_w, page_h)
    content += "".join("%d %d m %d %d l S\n" % (10, 10 + i * 5, 100, 10 + i * 5) for i in range(extra_paths))
    if text:
        content += "BT 3 Tr /F1 12 Tf 50 50 Td (%s) Tj ET\n" % text
    c = content.encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g] /Resources << /XObject << /Im0 4 0 R >> "
             "/Font << /F1 6 0 R >> >> /Contents 5 0 R >>" % (page_w, page_h)).encode(),
            ("<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray /BitsPerComponent 8 "
             "/Filter /FlateDecode /Length %d >>\nstream\n" % (img_w, img_h, len(data))).encode() + data + b"\nendstream",
            ("<< /Length %d >>\nstream\n" % len(c)).encode() + c + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


class ProcessBoundaryTest(unittest.TestCase):
    """스캔 읽기 하위 프로세스(raster_proc): 고정 인터프리터·고정 스크립트·임시 이름만, 셸 없음, 시간 한도."""

    def test_command_takes_only_temp_names(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        img, out = os.path.join(tmp, "page.png"), os.path.join(tmp, "extraction.json")
        cmd = raster_proc.command("py.exe", img, out, px_per_pt=4.1667, use_ocr=False)
        self.assertEqual(cmd[:3], ["py.exe", raster_proc.SCRIPT, os.path.abspath(img)])
        self.assertIn("--no-ocr", cmd)
        for bad in ("& calc.png", "도면.png", "-x.png", "page.png.exe"):
            with self.assertRaises(ValueError):
                raster_proc.command("py.exe", os.path.join(tmp, bad), out)
        with self.assertRaises(ValueError):  # 결과 파일이 다른 폴더
            raster_proc.command("py.exe", img, os.path.join(tmp, "sub", "extraction.json"))

    def test_env_interpreter_must_be_python(self):
        with mock.patch.dict(os.environ, {"HAZOP_RASTER_PYTHON": os.path.abspath(__file__)}):
            self.assertIsNone(raster_proc.interpreter())
        with mock.patch.dict(os.environ, {"HAZOP_RASTER_PYTHON": "python.exe"}):
            self.assertIsNone(raster_proc.interpreter())  # 상대 경로는 받지 않는다

    def test_timeout_raises(self):
        import subprocess
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        img = os.path.join(tmp, "page.png")
        with mock.patch.object(raster_proc, "interpreter", return_value=sys.executable), \
                mock.patch.object(raster_proc.subprocess, "run",
                                  side_effect=subprocess.TimeoutExpired(["x"], raster_proc.TIMEOUT_S)) as run:
            with self.assertRaises(raster_proc.ScanTimeout):
                raster_proc.run(img, os.path.join(tmp, "extraction.json"))
        self.assertEqual(run.call_args.kwargs["timeout"], raster_proc.TIMEOUT_S)
        self.assertFalse(run.call_args.kwargs["shell"])


class SizeLimitTest(unittest.TestCase):
    def test_render_dpi_lowers_or_refuses_before_drawing(self):
        a1 = (2384, 1684)  # A1 가로(pt)
        self.assertEqual(raster_scan.render_dpi(a1, 300), (300.0, False))  # 약 70 MP: 그대로 읽는다
        dpi, lowered = raster_scan.render_dpi((4000, 4000), 400)
        self.assertTrue(lowered)
        self.assertGreaterEqual(dpi, raster_scan.DPI_RENDER_MIN)
        self.assertLessEqual(4000 * 4000 * (dpi / 72) ** 2, raster.MAX_PIXELS)
        with self.assertRaises(ValueError):  # 낮춰도 150dpi 미만이면 거절
            raster_scan.render_dpi((14400, 14400), 400)

    def test_file_size_checked_before_reading(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "big.png")
        with open(p, "wb") as fh:
            fh.write(b"\x89PNG" + b"0" * 100)
        with mock.patch.object(raster, "MAX_FILE_BYTES", 50), \
                mock.patch("builtins.open", side_effect=AssertionError("파일을 읽으면 안 됨")):
            with self.assertRaises(raster.RasterInputError):
                raster.extract(p)


class CoordinateTest(unittest.TestCase):
    def test_undo_deskew_inverts_rotation(self):
        import math
        a, W, H = 1.5, 1000.0, 600.0
        al, be = math.cos(math.radians(a)), math.sin(math.radians(a))
        cx, cy = W / 2, H / 2

        def fwd(x, y):  # cv2.getRotationMatrix2D((cx, cy), a, 1)을 적용한 점
            return al * x + be * y + (1 - al) * cx - be * cy, -be * x + al * y + be * cx + (1 - al) * cy
        p = fwd(100.0, 50.0)
        ex = {"nodes": [{"geometry": {"x": p[0], "y": p[1], "width": 0, "height": 0}}],
              "relations": [{"endpoints": [{"point": list(fwd(800.0, 500.0))}], "waypoints": [list(fwd(10.0, 20.0))]}],
              "source_locations": [{"bbox": [p[0], p[1], 0, 0]}]}
        raster.undo_deskew(ex, a, W, H)
        self.assertAlmostEqual(ex["nodes"][0]["geometry"]["x"], 100.0, places=2)
        self.assertAlmostEqual(ex["nodes"][0]["geometry"]["y"], 50.0, places=2)
        self.assertEqual([round(v, 1) for v in ex["relations"][0]["endpoints"][0]["point"]], [800.0, 500.0])
        self.assertEqual([round(v, 1) for v in ex["relations"][0]["waypoints"][0]], [10.0, 20.0])
        self.assertEqual([round(v, 1) for v in ex["source_locations"][0]["bbox"][:2]], [100.0, 50.0])

    def test_page_points_cover_boxes(self):
        ex = {"nodes": [{"geometry": {"x": 30, "y": 60, "width": 3, "height": 6},
                         "label_location": {"bbox": [3, 3, 6, 6]}}],
              "texts": [{"geometry": {"x": 9, "y": 9, "width": 3, "height": 3}}],
              "source_locations": [{"bbox": [3, 6, 9, 12]}], "relations": []}
        out = raster_scan.to_page_points(ex, 3.0)
        self.assertEqual(out["nodes"][0]["geometry"], {"x": 10, "y": 20, "width": 1, "height": 2})
        self.assertEqual(out["nodes"][0]["label_location"]["bbox"], [1, 1, 2, 2])
        self.assertEqual(out["source_locations"][0]["bbox"], [1, 2, 3, 4])
        self.assertEqual(out["texts"][0]["geometry"]["x"], 3)


class ScanEvidenceTest(unittest.TestCase):
    def test_tag_score(self):
        scores = [("SI-V003", 0.98), ("PT", 0.95), ("302", 0.7), ("SAFETY PUMP", 0.99)]
        self.assertEqual(raster.tag_score("SI-V003", scores), 0.98)
        self.assertEqual(raster.tag_score("PT-302", scores), 0.7)   # 두 줄 이름표: 낮은 쪽
        self.assertIsNone(raster.tag_score("XX-9", scores))

    def test_low_confidence_tag_is_unknown(self):
        res = {"nodes": [{"local_id": "n1", "tag": "PT-302", "evidence": {}}, {"local_id": "n2", "tag": "SI-V003"}],
               "relations": [{"local_id": "r1"}], "validation": {"unknowns": []}}
        added = raster.mark_scan_evidence(res, [("SI-V003", 0.98), ("PT", 0.95), ("302", 0.7)])
        self.assertEqual(added, 1)
        self.assertEqual([(u["check"], u["target"]) for u in res["validation"]["unknowns"]],
                         [("low_ocr_confidence", "n1")])
        self.assertEqual(res["nodes"][1]["evidence"], {"read_from": "scan_image", "ocr_score": 0.98})
        self.assertEqual(res["relations"][0]["evidence"]["read_from"], "scan_image")


@unittest.skipUnless(HAS_PDFIUM, "pypdfium2 없음")
class SearchableScanTest(unittest.TestCase):
    """글자층(OCR)을 덧입힌 스캔 PDF도 스캔으로 판별해 스캔 경로로 등록한다(검토 2026-11-14 repro_searchable)."""

    def test_searchable_scan_registers_as_scan(self):
        data = image_pdf_bytes(612, 792, 850, 1100, text="P-101 TO SNP-M-102")
        with mock.patch.object(raster_scan, "reader_available", return_value=True):
            info = fileinfo.inspect("searchable.pdf", data)
        self.assertEqual(info["blockers"], [])
        self.assertEqual((info["scan"]["kind"], info["scan"]["text_layer"]), ("scan", True))

    def test_border_paths_and_real_vector(self):
        self.assertEqual(raster_scan.classify_pdf_page(image_pdf_bytes(612, 792, 850, 1100, extra_paths=8))["kind"],
                         "scan")
        self.assertNotEqual(raster_scan.classify_pdf_page(image_pdf_bytes(612, 792, 850, 1100, extra_paths=40))["kind"],
                            "scan")


@unittest.skipUnless(HAS_PDFIUM and HAS_PIL, "pypdfium2·Pillow 없음")
class RegisteredPagesTest(unittest.TestCase):
    """run_registered·data의 스캔 갈래: 쪽 하나가 실패해도 나머지를 읽고, 미추출이 된 쪽의 옛 그래프는 지운다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        im = drawing_image()
        buf = io.BytesIO()
        im.save(buf, "PDF", resolution=300.0, save_all=True, append_images=[im])
        self.pdf = os.path.join(self.tmp, "two.pdf")
        with open(self.pdf, "wb") as fh:
            fh.write(buf.getvalue())
        self.record = {"format": "pdf", "project_id": "p", "material_id": "m", "registration_version": 1,
                       "documents": [{"page_ids": ["page-1", "page-2"]}]}

    def test_failure_in_one_page_keeps_the_rest(self):
        ok = {"validation": {"blockers": []}}
        calls = []

        def finish(original, record, page, work, out_dir, *a):
            calls.append(page)
            if page == 0:
                raise OSError("디스크 가득 참")
            return ok
        out = os.path.join(self.tmp, "out")
        with mock.patch.object(raster_scan, "reader_available", return_value=True), \
                mock.patch.object(raster_scan, "_finish_page", side_effect=finish):
            done, skipped = raster_scan.run_registered(self.pdf, out, self.record, lambda i: "p%d" % i)
        self.assertEqual(calls, [0, 1])
        self.assertEqual([d[0] for d in done], [1])
        self.assertEqual([(s["page_id"], "디스크 가득 참" in s["reason"]) for s in skipped], [("page-1", True)])
        self.assertTrue(os.path.isfile(os.path.join(out, "p0", raster_scan.NOT_EXTRACTED)))

    def test_stale_graph_of_skipped_page_is_removed(self):
        from hazop import paths
        from hazop.app import data
        work = os.path.join(self.tmp, "work")
        ex = data.script_module("extract_drawio")
        record = dict(self.record, project_id="proj-1")
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": work}):
            stale = os.path.join(paths.output_root("graph"), ex.registered_out_name(record, 1), "graph.json")
            os.makedirs(os.path.dirname(stale))
            with open(stale, "w", encoding="utf-8") as fh:
                fh.write("{}")
            skipped = [{"page_index": 1, "page_id": "page-2", "reason": "스캔 읽기 오류"}]
            with mock.patch.object(raster_scan, "run_registered", return_value=([], skipped)):
                with self.assertRaises(ValueError):
                    data._extract_scan_pages(record, self.pdf, ex, data.script_module("build_graph"))
            self.assertFalse(os.path.exists(stale))


@unittest.skipUnless(HAS_CV and HAS_PIL, "OpenCV 없음(래스터 venv에서 실행)")
class DeskewCoordinatesTest(unittest.TestCase):
    """기운 그림: 바로잡아 읽은 뒤 좌표를 원래 그림으로 되돌려, 원본 보기와 겹친다(검토 r4_deskew)."""

    def test_box_lands_on_original_ink(self):
        """곧은 그림에서 읽은 상자를 2° 돌린 자리와, 2° 기운 그림을 바로잡아 읽고 되돌린 상자가 겹친다."""
        import math
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)

        def read(im, name):
            p = os.path.join(tmp, name)
            im.save(p)
            return raster.extract(p, use_ocr=False, params={"px_per_pt": 1.5})
        straight = read(drawing_image(), "straight.png")
        tilted = drawing_image().rotate(2.0, resample=3, fillcolor=255)  # Pillow: 가운데 기준 반시계
        ex = read(tilted, "tilted.png")
        self.assertEqual(ex["run"]["settings"]["deskew"]["state"], "corrected")
        self.assertTrue(ex["coordinate_system"]["deskew_undone"])
        g0, g1 = straight["nodes"][0]["geometry"], ex["nodes"][0]["geometry"]
        th, cx, cy = math.radians(2.0), tilted.size[0] / 2, tilted.size[1] / 2
        rot = [(cx + (x - cx) * math.cos(th) + (y - cy) * math.sin(th), cy - (x - cx) * math.sin(th) + (y - cy) * math.cos(th))
               for x in (g0["x"], g0["x"] + g0["width"]) for y in (g0["y"], g0["y"] + g0["height"])]
        want = (min(q[0] for q in rot), min(q[1] for q in rot), max(q[0] for q in rot), max(q[1] for q in rot))
        got = (g1["x"], g1["y"], g1["x"] + g1["width"], g1["y"] + g1["height"])
        for a, b in zip(got, want):
            self.assertLess(abs(a - b), 6, (got, want))


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
            self.assertEqual((ex["source"]["format"], ex["source"]["scan_input"]), ("raster", "pdf"))
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



@unittest.skipUnless(HAS_PDFIUM and HAS_PIL and RASTER_PY, "래스터 venv Python 없음")
@unittest.skipUnless(os.path.isfile(SNP_102), "SNP 표본 PDF 없음")
class AppScanFlowTest(unittest.TestCase):
    """앱 경로: 스캔 PDF 등록 → data.extract_and_graph(진행 알림) → 원본 그림을 넣은 page.svg와 그래프, 뷰어."""

    def test_register_extract_and_view_scan_pdf(self):
        import json
        import pypdfium2
        from hazop import paths
        from hazop.app import data
        from hazop.register import registry
        tmp = tempfile.mkdtemp(prefix="hazop-scan-app-")
        self.addCleanup(shutil.rmtree, tmp, True)
        im = pypdfium2.PdfDocument(SNP_102)[0].render(scale=300 / 72, grayscale=True).to_pil()
        src = os.path.join(tmp, "in", "SNP-M-102-scan.pdf")
        os.makedirs(os.path.dirname(src))
        with open(src, "wb") as fh:
            fh.write(scan_pdf_bytes(im, 300))
        work, store = os.path.join(tmp, "work"), os.path.join(tmp, "store")
        calls = []
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": work, "HAZOP_STORE_ROOT": store}):
            r = registry.register(src, "proj-1", store_root=store, actor="tester")
            self.assertEqual(r["record"]["status"], "registered", r["record"].get("validation"))
            out = data.extract_and_graph(r["registration_file"], progress=lambda *a: calls.append(a))
            self.assertTrue(out["scan"])
            self.assertEqual(calls[0][:2], (0, 1))
            self.assertEqual(calls[-1][:2], (1, 1))
            with open(os.path.join(out["extract_dir"], "extraction.json"), encoding="utf-8") as fh:
                ex = json.load(fh)
            al = ex["coordinate_system"]["svg_alignment"]
            self.assertEqual((al["source"], al["offset"]), ("scan_image", [0, 0]))
            self.assertEqual((ex["source"]["format"], ex["source"]["scan_input"]), ("raster", "pdf"))
            self.assertEqual(ex["source"]["sha256"], r["record"]["sha256"])
            from hazop.extract import confirmation
            st = confirmation.check(ex)
            self.assertEqual(st["read_method"], "raster")
            self.assertIsNone(st["leftovers"])  # 원본에 남은 것을 세지 못하는 읽은 방법이라 이 쪽은 확정할 수 없다
            self.assertIn("scan_input", {u["reason"] for u in st["unconfirmed"]})
            self.assertTrue(all(n["evidence"].get("read_from") == "scan_image" for n in ex["nodes"]))
            self.assertIn("scan_input", {u["check"] for u in ex["validation"]["unknowns"]})
            with open(os.path.join(out["extract_dir"], "page.svg"), encoding="utf-8") as fh:
                self.assertIn("data:image/png;base64,", fh.read())
            self.assertEqual(out["graph"]["validation"]["status"], "passed")
            name = os.path.basename(out["extract_dir"])
            self.assertIsNone(data.viewer_html_for(name)["error"])
            rows = data.list_registrations()
            self.assertEqual([(e["extracted"], e["graphed"]) for e in rows], [(True, True)])
            self.assertEqual(rows[0]["pages"], {"total": 1, "extracted": 1, "skipped": 0})
        self.assertFalse(os.path.exists(paths.output_in(paths.DEV_WORK_ROOT, "extract", name)))


if __name__ == "__main__":
    unittest.main()
