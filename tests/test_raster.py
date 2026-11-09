"""T3 W4 래스터(PNG·JPG) 어댑터 테스트. 실행: python -m unittest tests.test_raster

합성 영상 시험(코드로 그린 선·사각형·원·점선, 글자는 OCR 대신 주어진 줄 목록)은 OpenCV가 있을 때만 돈다.
샘플 PNG 시험은 OpenCV와 rapidocr가 모두 있을 때만 돈다(결정 D7: packaging/requirements-raster.txt의 별도 venv).
배포 빌드에 OpenCV가 들어가지 않는지(정적 import 검사, 빌드 venv 설치 목록, 빌드 TOC)는 OpenCV 없이 돈다."""

import ast
import contextlib
import glob
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_adapter  # noqa: E402
import extract_raster  # noqa: E402
from hazop.extract.adapters import raster  # noqa: E402
from hazop.graph import build as graph_build  # noqa: E402

HAS_CV = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None
HAS_OCR = importlib.util.find_spec("rapidocr_onnxruntime") is not None
HEAVY = ("cv2", "numpy", "rapidocr_onnxruntime", "onnxruntime")  # 배포본에 넣지 않는 래스터 의존성(결정 D7)
BUILD_VENV = os.environ.get("HAZOP_VENV") or os.path.join(os.path.expanduser("~"), ".hazop", "venv-py312")
W, H = 1191, 842
# 샘플 PNG와 같은 배율(2.75 px/pt, 가는 선 2 px)이 되도록 공칭 페이지 폭을 맞춘다
SYN = {"nominal_page_width_pt": W / 2.75}


def canvas():
    import numpy as np
    return np.full((H, W), 255, np.uint8)


def run(img, lines=None, params=None):
    """합성 영상 → extraction(OCR 대신 lines 사용)."""
    params = dict(SYN, **(params or {}))
    w, h, words, prims, info = raster.detect(img, lines or [], params)
    return raster.build_extraction(w, h, words, prims, info, "ok" if lines else "disabled", "synthetic.png",
                                   "0" * 64, "raster_png", params)


def ev_dumps(ext):
    from hazop.extract.adapters import evaluation as ev
    return ev.dumps(ext)


def text(t, x0, top, x1, bottom):
    return {"text": t, "x0": float(x0), "x1": float(x1), "top": float(top), "bottom": float(bottom), "score": 0.99}


def rel_pairs(ext):
    by = {n["local_id"]: n for n in ext["nodes"]}
    out = []
    for r in ext["relations"]:
        a, b = (by[e["node_local_id"]] for e in r["endpoints"])
        out.append((r["kind"], tuple(sorted((a["kind"] or "?", b["kind"] or "?")))))
    return sorted(out)


def static_imports(path):
    """파일 안 모든 import 문(함수 안 포함)의 최상위 모듈 이름. PyInstaller는 함수 안 import도 따라간다."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


class DistributionExclusionTest(unittest.TestCase):
    """배포 빌드(PyInstaller)가 OpenCV·numpy·rapidocr를 끌어오지 않는다(결정 D7)."""

    def test_no_static_import_of_raster_dependencies(self):
        files = glob.glob(os.path.join(REPO_ROOT, "hazop", "**", "*.py"), recursive=True)
        files += [os.path.join(REPO_ROOT, p) for p in ("scripts/run_app.py", "packaging/check_entry.py",
                                                       "scripts/extract_drawio.py", "scripts/build_graph.py")]
        self.assertIn(os.path.join(REPO_ROOT, "hazop", "extract", "adapters", "raster.py"), files)
        for path in files:
            with self.subTest(path=os.path.relpath(path, REPO_ROOT)):
                self.assertEqual(static_imports(path) & set(HEAVY), set())

    def test_raster_module_imports_without_opencv(self):
        """cv2·numpy·rapidocr를 import할 수 없는 상태(sys.modules 차단)에서 모듈을 새로 import해도 되고,
        사용 가능 여부는 False, 실제 영상 처리는 ImportError로 끝난다. CLI는 종료 코드 2."""
        name = "hazop.extract.adapters.raster"
        blocked = {m: None for m in HEAVY}  # None = import 차단(ImportError)
        with mock.patch.dict(sys.modules, blocked):
            saved = sys.modules.pop(name)
            try:
                fresh = importlib.import_module(name)
                self.assertIsNot(fresh, saved)
                self.assertEqual(fresh.available(), (False, False))
                with self.assertRaises(ImportError):
                    fresh._cv()
                with mock.patch.object(extract_raster, "raster", fresh):
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        rc = extract_raster.main(["x.png"])
            finally:
                sys.modules[name] = saved
        self.assertEqual(rc, 2)
        self.assertIn("OpenCV", buf.getvalue())

    @unittest.skipUnless(os.path.isdir(BUILD_VENV), "빌드 venv 없음")
    def test_build_venv_has_no_raster_dependencies(self):
        site = os.path.join(BUILD_VENV, "Lib", "site-packages")
        for mod in HEAVY:
            with self.subTest(module=mod):
                self.assertFalse(os.path.exists(os.path.join(site, mod)), "빌드 venv에 %s가 있음(D7: 별도 venv)" % mod)

    def test_build_tocs_have_no_raster_dependencies(self):
        """HAZOP_BUILD_OUT(또는 임시 폴더의 hazop-*·저장소 밖 빌드 출력)에 남은 빌드 TOC를 검사한다. 없으면 건너뛴다."""
        import build_package
        outs = [os.environ["HAZOP_BUILD_OUT"]] if os.environ.get("HAZOP_BUILD_OUT") else \
            glob.glob(os.path.join(tempfile.gettempdir(), "hazop-*"))
        tocs = [p for o in outs for p in glob.glob(os.path.join(o, "build", build_package.APP_NAME, "PYZ-00.toc"))]
        if not tocs:
            self.skipTest("빌드 TOC 없음")
        for toc in tocs:
            with self.subTest(toc=toc):
                mods = build_package.pyz_modules(toc)
                self.assertEqual({m for m in mods if m.split(".")[0] in HEAVY}, set())
                coll = build_package.collect_toc_path(os.path.dirname(os.path.dirname(os.path.dirname(toc))))
                if os.path.isfile(coll):
                    names = [n.replace("\\", "/").lower() for n, _, _ in build_package.read_toc(coll)]
                    self.assertEqual([n for n in names if n.startswith(("cv2/", "numpy", "onnxruntime"))], [])


class SampleSelectionTest(unittest.TestCase):
    def test_blind_rule_excludes_drawio_png(self):
        samples = check_adapter.raster_samples()
        self.assertEqual(len(samples), 6)
        for _, _, png in samples:
            self.assertFalse(png.lower().endswith(".drawio.png"), png)
        self.assertTrue(all(not p.lower().endswith(".drawio.png") for p in extract_raster.sample_images()))
        errs, row, _ = check_adapter.evaluate_raster("x", samples[0][1], samples[0][2][:-4] + ".drawio.png")
        self.assertIsNone(row)
        self.assertIn("블라인드", errs[0])


@unittest.skipUnless(HAS_CV, "OpenCV 없음(결정 D7: packaging/requirements-raster.txt의 venv에서 실행)")
class SyntheticImageTest(unittest.TestCase):
    def test_two_boxes_joined_by_pipe(self):
        import cv2
        img = canvas()
        cv2.rectangle(img, (100, 100), (180, 160), 0, 2)
        cv2.rectangle(img, (400, 100), (480, 160), 0, 2)
        cv2.line(img, (181, 130), (399, 130), 0, 2)
        ext = run(img)
        self.assertEqual(ext["validation"]["blockers"], [])
        self.assertEqual(len(ext["nodes"]), 2)
        self.assertEqual(rel_pairs(ext), [("physical_connection", ("?", "?"))])
        self.assertEqual(ext["unresolved_connectors"], [])
        self.assertEqual(ext["coordinate_system"]["coordinate_space"], "image_px")
        self.assertEqual(ext["source"]["format"], "raster_png")
        self.assertTrue(all(n["source_object_id"].startswith("img-") for n in ext["nodes"]))
        self.assertIn("ocr_disabled", [u["check"] for u in ext["validation"]["unknowns"]])
        graph = graph_build.build_graph(ext)  # 그래프 단계(③) 호환
        self.assertEqual(graph["validation"]["status"], "passed")

    def test_tee_and_crossing(self):
        import cv2
        img = canvas()
        for x in (100, 400, 700):
            cv2.rectangle(img, (x, 100), (x + 60, 150), 0, 2)
        cv2.rectangle(img, (400, 400), (460, 450), 0, 2)
        cv2.line(img, (161, 125), (399, 125), 0, 2)    # 왼쪽 상자 → 가운데 상자
        cv2.line(img, (280, 125), (280, 300), 0, 2)    # 위 선 중간에서 아래로(분기)
        cv2.line(img, (280, 300), (430, 300), 0, 2)    # 꺾여서
        cv2.line(img, (430, 300), (430, 399), 0, 2)    # 아래 상자로
        cv2.line(img, (461, 125), (699, 125), 0, 2)    # 가운데 → 오른쪽
        cv2.line(img, (600, 60), (600, 250), 0, 2)     # 위 선과 교차만(연결 아님)
        ext = run(img)
        kinds = sorted(n["kind"] or "?" for n in ext["nodes"])
        self.assertEqual(kinds.count("tee"), 1)
        self.assertEqual(len(ext["relations"]), 4)  # 왼-분기, 분기-가운데, 분기-아래, 가운데-오른쪽(교차로 나뉘지 않음)
        self.assertEqual(len([r for r in ext["unresolved_connectors"]]), 1)  # 교차선 자체는 미해결

    def test_dashed_signal_and_instrument_text(self):
        import cv2
        img = canvas()
        cv2.circle(img, (150, 150), 30, 0, 2)
        cv2.line(img, (120, 150), (180, 150), 0, 2)   # 계기 원 가운데 선
        cv2.circle(img, (450, 150), 30, 0, 2)
        for x in range(184, 416, 18):                 # 점선 조각 12 px, 빈칸 6 px
            cv2.line(img, (x, 150), (min(x + 11, 415), 150), 0, 2)
        # OCR 줄 상자처럼 위아래 여백을 둔 상자(샘플 OCR: 'PIC' 119~144, '110' 144~164)
        lines = [text("PT", 138, 124, 162, 150), text("101", 135, 148, 165, 174),
                 text("PIC", 434, 124, 466, 150), text("101", 435, 148, 465, 174)]
        ext = run(img, lines)
        kinds = sorted(n["kind"] for n in ext["nodes"])
        self.assertEqual(kinds, ["controller", "transmitter"])
        self.assertEqual(rel_pairs(ext), [("signal_connection", ("controller", "transmitter"))])
        labels = sorted(n["label_text"] for n in ext["nodes"])
        self.assertEqual(labels, ["PIC\n101", "PT\n101"])

    def test_line_label_gap_is_bridged_and_arrowhead_attaches(self):
        import cv2
        import numpy as np
        img = canvas()
        cv2.rectangle(img, (100, 100), (160, 160), 0, 2)
        cv2.rectangle(img, (600, 100), (660, 160), 0, 2)
        cv2.line(img, (161, 130), (330, 130), 0, 2)   # 선 라벨 자리(330~400)에서 끊김
        cv2.line(img, (400, 130), (585, 130), 0, 2)
        tri = np.array([[585, 123], [599, 130], [585, 137]], np.int32)  # 오른쪽 상자로 들어가는 화살촉
        cv2.fillPoly(img, [tri], 0)
        ext = run(img, [text("L-001", 338, 122, 392, 138)])
        self.assertEqual(len(ext["relations"]), 1, ext["unresolved_connectors"])
        self.assertEqual(ext["unresolved_connectors"], [])
        self.assertEqual([t["text"] for t in ext["texts"]], ["L-001"])
        self.assertIn("선 라벨", ext["texts"][0]["note"])
        bases = sorted(e["point_basis"] for e in ext["relations"][0]["endpoints"])
        self.assertIn("raster_arrowhead", bases)

    def test_bow_tie_valve(self):
        import cv2
        import numpy as np
        img = canvas()
        cv2.polylines(img, [np.array([[300, 110], [340, 130], [300, 150]], np.int32)], True, 0, 2)
        cv2.polylines(img, [np.array([[380, 110], [340, 130], [380, 150]], np.int32)], True, 0, 2)
        cv2.rectangle(img, (100, 100), (160, 160), 0, 2)
        cv2.line(img, (161, 130), (299, 130), 0, 2)
        ext = run(img)
        self.assertIn("manual_valve", [n["kind"] for n in ext["nodes"]])

    def test_blank_image_is_blocked_and_deterministic(self):
        ext = run(canvas())
        self.assertEqual(ext["validation"]["status"], "blocked")
        self.assertEqual([b["check"] for b in ext["validation"]["blockers"]], ["no_image_content"])
        import cv2
        img = canvas()
        cv2.rectangle(img, (100, 100), (180, 160), 0, 2)
        cv2.line(img, (181, 130), (400, 130), 0, 2)
        from hazop.extract.adapters import evaluation as ev
        self.assertEqual(ev.dumps(run(img)), ev.dumps(run(img.copy())))

    def test_body_at_image_edge(self):
        """영상 경계에 붙은 몸체(잘라내기 범위가 영상 밖으로 나가는 경우)도 오류 없이 처리한다(Codex 재현 사례)."""
        import numpy as np
        img = np.full((100, 100), 255, np.uint8)
        img[8:18, 92:100] = 0
        img[10:16, 94:99] = 255  # 몸체 구멍 [94, 10, 99, 15]: 오른쪽 경계까지 1픽셀
        w, h, words, prims, info = raster.detect(img, [], {"nominal_page_width_pt": 100 / 2.75})
        self.assertEqual((w, h), (100, 100))
        for pr in prims:
            for x, y in pr["subpaths"][0][0]:
                self.assertTrue(0 <= x <= 100 and 0 <= y <= 100)
        big = canvas()
        big[0:40, W - 30:W] = 0
        big[5:35, W - 25:W - 1] = 255  # 오른쪽 경계까지 구멍
        run(big)

    def test_ids_are_retagged_everywhere(self):
        import cv2
        img = canvas()
        cv2.rectangle(img, (100, 100), (180, 160), 0, 2)
        cv2.rectangle(img, (400, 100), (480, 160), 0, 2)
        cv2.line(img, (181, 130), (399, 130), 0, 2)
        cv2.rectangle(img, (5, 5), (W - 6, H - 6), 0, 2)  # 페이지 테두리(버리는 선)
        # 표제란처럼 글자가 든 칸 두 개 → ignored_objects
        cv2.rectangle(img, (800, 700), (900, 740), 0, 2)
        cv2.rectangle(img, (900, 700), (1100, 740), 0, 2)
        ext = run(img, [text("DWG NO.", 810, 708, 890, 732), text("X-1", 910, 708, 960, 732)])
        dump = ev_dumps(ext)
        self.assertNotIn("pdf-p0-", dump)
        self.assertNotIn("pdf-path-", dump)
        self.assertTrue(ext["drawing"]["ignored_objects"])
        self.assertTrue(all(o["source_object_id"].startswith("img-prim-") for o in ext["drawing"]["ignored_objects"]))

    def test_processing_limits_are_recorded(self):
        import cv2
        img = canvas()
        for k in range(6):
            cv2.rectangle(img, (100 + 120 * k, 100), (180 + 120 * k, 160), 0, 2)
        for k in range(4):
            cv2.line(img, (100 + 30 * k, 400), (130 + 30 * k, 440), 0, 2)
        ext = run(img, params={"max_merge_items": 2, "max_spring_items": 1})
        checks = [u["reason"] for u in ext["validation"]["unknowns"] if u["check"] == "processing_limit"]
        self.assertTrue(any("body_merge_skipped" in r for r in checks), checks)
        self.assertTrue(any("spring_regularize_skipped" in r for r in checks), checks)
        self.assertEqual(ext["validation"]["blockers"], [])

    def test_extract_file_and_cli(self):
        import cv2
        img = canvas()
        cv2.rectangle(img, (100, 100), (180, 160), 0, 2)
        cv2.rectangle(img, (400, 100), (480, 160), 0, 2)
        cv2.line(img, (181, 130), (399, 130), 0, 2)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "그림.png")  # 한글 경로
            cv2.imencode(".png", img)[1].tofile(path)
            ext = raster.extract(path, use_ocr=False, params=SYN)
            self.assertEqual(ext["run"]["settings"]["ocr"], "disabled")
            self.assertEqual(len(ext["relations"]), 1)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = extract_raster.main([path, "--no-ocr", "--out-root", os.path.join(d, "out")])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(os.path.join(d, "out", "그림", "extraction.json")))
            with self.assertRaises(ValueError):
                raster.extract(os.path.join(d, "a.bmp"))


@unittest.skipUnless(HAS_CV, "OpenCV 없음(결정 D7)")
class InputLimitTest(unittest.TestCase):
    """빈·손상·너무 큰 입력은 blocker가 아니라 형식 오류(RasterInputError, CLI 종료 코드 2)."""

    def write(self, d, name, data):
        path = os.path.join(d, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_empty_corrupt_and_oversized(self):
        import cv2
        with tempfile.TemporaryDirectory() as d:
            empty = self.write(d, "empty.png", b"")
            corrupt = self.write(d, "bad.png", b"\x89PNG\r\n\x1a\nnot really a png")
            ok = os.path.join(d, "ok.png")
            cv2.imencode(".png", canvas())[1].tofile(ok)
            for path in (empty, corrupt):
                with self.subTest(path=os.path.basename(path)):
                    with self.assertRaises(raster.RasterInputError):
                        raster.load_image(path)
            with self.assertRaisesRegex(raster.RasterInputError, "너무 큼"):
                raster.load_image(ok, max_pixels=1000)
            with self.assertRaisesRegex(raster.RasterInputError, "너무 큼"):
                raster.load_image(ok, max_bytes=10)
            self.assertEqual(raster.load_image(ok).shape, (H, W))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = extract_raster.main([empty, corrupt, ok, "--no-ocr", "--out-root", os.path.join(d, "out")])
            self.assertEqual(rc, 2)
            self.assertEqual(buf.getvalue().count("입력 형식 오류"), 2)

    def test_header_pixel_limit_before_decode(self):
        """머리말의 폭·높이로 해독 전에 막는다(50 MP 상한, 실제 큰 영상을 만들지 않고 머리말만 바꿔 시험)."""
        import struct
        import zlib
        w, h = 10000, 6000  # 60 MP
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)

        def chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")
        with self.assertRaisesRegex(raster.RasterInputError, "너무 큼"):
            raster.check_header(png)


@unittest.skipUnless(HAS_CV and HAS_OCR, "OpenCV·rapidocr 없음(결정 D7)")
class RasterSampleTest(unittest.TestCase):
    def test_samples_contract_alignment_and_evaluation(self):
        for name, drawio_path, png_path in check_adapter.raster_samples():
            with self.subTest(name=name):
                errs, row, outputs = check_adapter.evaluate_raster(name, drawio_path, png_path)
                self.assertEqual(errs, [])
                self.assertEqual(row["blockers"], 0)
                self.assertEqual(outputs["evaluation"]["status"], "ok")
                self.assertIsNotNone(outputs["extraction"]["drawing"]["drawing_number"])

    def test_quality_floor_catches_relation_drop(self):
        name, drawio_path, png_path = check_adapter.raster_samples()[0]

        def drop(ext):
            ext["relations"] = ext["relations"][5:]
            return ext
        errs, row, _ = check_adapter.evaluate_raster(name, drawio_path, png_path, mutate=drop)
        self.assertTrue(any("relations_f1" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
