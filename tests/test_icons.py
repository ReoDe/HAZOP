"""화면 아이콘 검사 (Tabler Icons 3.51.0, MIT). 실행: python -m unittest tests.test_icons

저장소에는 쓰는 아이콘만 `resources/library/icons/tabler/`에 원본 그대로 넣는다. 이 검사는 ① 넣은 SVG가 목록(`manifest.json`)의
해시와 같고 목록 밖 파일이 없는지(받은 원본이 남아 있으면 원본과도 대조), ② README 사용처 표가 목록과 맞는지, ③ `hazop/app/icons.py`
(찾기·색 바꾸기·없는 이름·배율)와 웹용 SVG, ④ 배포본 묶음 목록·고지 등록·묶음 검사를 본다. 오프스크린, 네트워크 없음.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from hazop import paths  # noqa: E402

SOURCE_SVGS = os.path.join("D:\\", "HAZOP-trials", "2026-11-13-icons", "pkg", "package", "icons", "outline")  # 있을 때만 대조
TGZ_SHA256 = "b30108713d3fa60aee862c2a133225da8e0f309be0708fe2925763ff810c766c"
LICENSE_SHA256 = "b740a1d46122672da62833e97f7e7c8a13fa85cbc7445b584b297cc00dde93db"


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def icon_dir():
    return paths.folder("icons", "tabler")


def manifest():
    with open(os.path.join(icon_dir(), "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


class FilesTest(unittest.TestCase):
    def test_manifest_source_fields(self):
        m = manifest()
        self.assertEqual(m["package"], "@tabler/icons")
        self.assertEqual(m["version"], "3.51.0")
        self.assertEqual(m["license"], "MIT")
        self.assertEqual(m["archive_sha256"], TGZ_SHA256)
        self.assertTrue(m["source_url"].startswith("https://registry.npmjs.org/@tabler/icons/-/icons-3.51.0.tgz"))
        self.assertRegex(m["fetched"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(30 <= len(m["icons"]) <= 60)

    def test_files_match_manifest(self):
        m = manifest()
        on_disk = {f[:-4] for f in os.listdir(icon_dir()) if f.endswith(".svg")}
        self.assertEqual(on_disk, set(m["icons"]))
        for name, row in m["icons"].items():
            self.assertEqual(sha(os.path.join(icon_dir(), name + ".svg")), row["sha256"], name)
            self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_files_are_the_original_bytes(self):
        if not os.path.isdir(SOURCE_SVGS):
            self.skipTest("받은 원본 폴더가 없음(다시 받을 수 있음)")
        for name in manifest()["icons"]:
            self.assertEqual(sha(os.path.join(icon_dir(), name + ".svg")), sha(os.path.join(SOURCE_SVGS, name + ".svg")), name)

    def test_readme_usage_table_matches(self):
        with open(os.path.join(icon_dir(), "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        for head in ("## 무엇을 넣는가", "## 넣지 않는 것", "## 이름 형식", "## 주인", "## 폐기 기준"):
            self.assertEqual(text.count(head), 1, head)
        rows = [c for c in (re.findall(r"^\| `([a-z0-9-]+)` \| (.+?) \|$", text, re.M))]
        self.assertEqual(sorted(n for n, _ in rows), sorted(manifest()["icons"]))
        self.assertTrue(all(use.strip() for _, use in rows))

    def test_license_registered(self):
        lic = os.path.join(paths.licenses_dir(), "tabler-icons", "LICENSE")
        self.assertEqual(sha(lic), LICENSE_SHA256)
        with open(os.path.join(paths.licenses_dir(), "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("`tabler-icons/LICENSE`", text)
        self.assertIn(LICENSE_SHA256, text)


class LoaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    def test_names_are_the_manifest(self):
        from hazop.app import icons
        self.assertEqual(sorted(icons.names()), sorted(manifest()["icons"]))
        self.assertTrue(os.path.isfile(icons.icon_path("send")))
        self.assertIsNone(icons.icon_path("no-such-icon"))
        self.assertIsNone(icons.icon_path("../manifest"))      # 이름만 받는다(경로를 만들지 않음)

    def test_svg_text_colors_and_size(self):
        from hazop.app import icons, tokens
        s = icons.svg_text("send", color="ui", size=20)
        self.assertNotIn("currentColor", s)
        self.assertIn(tokens.c("ui"), s)
        self.assertIn('width="20"', s)
        self.assertIn(tokens.c("ink"), icons.svg_text("send"))          # 기본 색은 본문 글자색 토큰
        self.assertIn("#123456", icons.svg_text("send", color="#123456"))
        self.assertIn(tokens.c("ink"), icons.svg_text("send", color="no-such-token"))   # 모르는 색은 기본 색
        self.assertEqual(icons.svg_text("no-such-icon"), "")

    def test_qicon_found_missing_and_color(self):
        from PySide6.QtCore import QSize
        from hazop.app import icons, tokens
        ic = icons.icon("send", color="err-ink", size=16)
        self.assertFalse(ic.isNull())
        img = ic.pixmap(QSize(16, 16)).toImage()
        want = tuple(int(tokens.c("err-ink").lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        solid = []
        for x in range(img.width()):
            for y in range(img.height()):
                c = img.pixelColor(x, y)
                if c.alpha() > 200:       # 선 가장자리는 반투명이라 색이 조금 번진다
                    solid.append((c.red(), c.green(), c.blue()))
        self.assertTrue(solid, "그려진 화소가 없음")
        self.assertTrue(all(max(abs(a - b) for a, b in zip(px, want)) <= 12 for px in solid), "토큰 색과 다른 화소")
        with self.assertLogs("hazop.app.icons", level="WARNING") as cm:
            gone = icons.icon("no-such-icon")
        self.assertTrue(gone.isNull())
        self.assertIn("no-such-icon", cm.output[0])

    def test_crisp_at_125_percent(self):
        """125% 배율에서 16px 아이콘은 20 화소로 새로 그려진다(작은 그림을 늘리지 않는다)."""
        from PySide6.QtCore import QSize
        from hazop.app import icons
        ic = icons.icon("search", size=16)
        for ratio in (1.0, 1.25, 1.5, 2.0):
            pm = ic.pixmap(QSize(16, 16), ratio)
            self.assertEqual(pm.width(), round(16 * ratio), ratio)
            self.assertAlmostEqual(pm.devicePixelRatio(), ratio, places=2)

    def test_web_svg(self):
        from hazop.app import icons
        s = icons.svg_inline("zoom-in", size=16)
        self.assertTrue(s.startswith("<svg"))
        self.assertIn("currentColor", s)             # 웹에서는 CSS 글자색을 따른다
        self.assertNotIn("class=", s)
        self.assertNotIn("\n", s)
        self.assertNotIn("M0 0h24v24H0z", s)         # 받은 파일의 투명 바탕 경로는 뺀다
        self.assertIn('width="16"', s)
        self.assertEqual(icons.svg_inline("no-such-icon"), "")

    def test_every_icon_name_used_in_code_exists(self):
        """코드에서 icon("이름")·icons.icon("이름")으로 부르는 이름이 모두 넣은 아이콘이다."""
        from hazop.app import icons
        have = set(icons.names())
        pat = re.compile(r"""\bicons?\.(?:icon|svg_text|svg_inline|icon_path)\(\s*["']([a-z0-9-]+)["']""")
        bad = []
        for sub in ("hazop", "scripts"):
            for d, _, files in os.walk(os.path.join(REPO_ROOT, sub)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(d, f), encoding="utf-8") as fh:
                            bad += ["%s: %s" % (f, n) for n in pat.findall(fh.read()) if n not in have]
        self.assertEqual(bad, [])


class PackagingTest(unittest.TestCase):
    def test_icons_folder_is_a_resource_folder_and_bundled(self):
        self.assertEqual(paths.FOLDERS["icons"].root, "resource")
        import importlib.util
        spec = importlib.util.spec_from_file_location("bp_icons", os.path.join(REPO_ROOT, "scripts", "build_package.py"))
        bp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bp)
        srcs = {s for s, _ in bp.datas_list()}
        rel = paths.folder_rel("icons")
        self.assertIn(rel + "/tabler/manifest.json", srcs)
        self.assertIn(rel + "/tabler/send.svg", srcs)
        self.assertTrue(all(rel + "/tabler/%s.svg" % n in srcs for n in manifest()["icons"]))

    def test_verify_bundle_icons_problems(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("vb_icons", os.path.join(REPO_ROOT, "packaging", "verify_bundle.py"))
        vb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vb)
        tmp = tempfile.mkdtemp(prefix="hazop-icons-bundle-")
        self.addCleanup(shutil.rmtree, tmp, True)
        dest = paths.folder_in(os.path.join(tmp, "_internal"), "icons", "tabler")
        shutil.copytree(icon_dir(), dest)
        self.assertEqual(vb.icons_problems(tmp), [])
        os.remove(os.path.join(dest, "send.svg"))
        self.assertEqual(vb.icons_problems(tmp), ["아이콘 빠짐: send.svg"])
        with open(os.path.join(dest, "send.svg"), "w", encoding="utf-8") as fh:
            fh.write("<svg/>")
        self.assertEqual(vb.icons_problems(tmp), ["아이콘 바이트 다름: send.svg"])
        with open(os.path.join(dest, "extra.svg"), "w", encoding="utf-8") as fh:
            fh.write("<svg/>")
        self.assertIn("목록 밖 아이콘: extra.svg", vb.icons_problems(tmp))
        shutil.rmtree(os.path.join(tmp, "_internal"))
        self.assertEqual(vb.icons_problems(tmp), ["묶음에 아이콘 폴더가 없음"])


class ViewerAppliedTest(unittest.TestCase):
    """뷰어 도구 줄에 새 아이콘이 붙었다(Qt 단추와 웹 확대·축소·맞춤 단추)."""

    @classmethod
    def setUpClass(cls):
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    def test_edit_panel_buttons_have_icons(self):
        from PySide6.QtWidgets import QPushButton
        from hazop.app.screens import viewer
        b = viewer._ibtn("편집", "pencil")
        self.assertIsInstance(b, QPushButton)
        self.assertEqual(b.text(), "편집")                     # 글자는 그대로
        self.assertFalse(b.icon().isNull())
        self.assertEqual(set(viewer.TOOL_ICONS), {k for k, _ in viewer.TOOLS})
        from hazop.app import icons
        self.assertTrue(all(icons.icon_path(n) for n in viewer.TOOL_ICONS.values()))

    def test_web_zoom_buttons_become_icons(self):
        from tests.test_viewer_api import PAGE, js
        from tests.test_app import wait_for
        from hazop.app.webview import HazopWebView
        v = HazopWebView()
        v.resize(900, 700)
        self.addCleanup(v.dispose)
        tmp = tempfile.mkdtemp(prefix="hazop-icons-web-")
        self.addCleanup(shutil.rmtree, tmp, True)
        body = ('<foreignObject width="1" height="1"></foreignObject>')
        page = PAGE % {"body": body}
        page = page.replace("</body>", '<div class="float" id="zoom"><button id="zout" title="축소">&minus;</button>'
                            '<button id="zin" title="확대">+</button><button id="zfit" title="도면 전체 보기">맞춤</button></div></body>')
        path = os.path.join(tmp, "z.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)
        ready = []
        v.bridge.sheetReady.connect(ready.append)
        v.load_file(path, graph_id="G")
        v.show()
        self.assertTrue(wait_for(lambda: bool(ready)))
        self.assertTrue(wait_for(lambda: js(v, "document.querySelectorAll('#zoom svg').length") == 3))
        self.assertEqual(js(v, "document.getElementById('zout').getAttribute('aria-label')"), "축소")
        self.assertEqual(js(v, "document.getElementById('zfit').textContent.trim()"), "맞춤")   # 맞춤은 글자도 남긴다
        self.assertEqual(js(v, "document.getElementById('zin').getAttribute('title')"), "확대")


if __name__ == "__main__":
    unittest.main()
