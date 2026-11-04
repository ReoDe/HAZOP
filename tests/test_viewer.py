"""단계 ② 뷰어 빌드·검사 테스트. 실행: python -m unittest discover -s tests -t ."""

import glob
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.extract import drawio, svg_align  # noqa: E402
from hazop.viewer import build, check, sanitize  # noqa: E402

SAMPLES = sorted(glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*.drawio")))


def extraction_with_svg(path):
    r = drawio.extract(path, repo_root=REPO_ROOT)
    svg = glob.glob(os.path.join(os.path.dirname(path), "*.drawio.svg"))[0]
    al = svg_align.align(svg, r)
    al["svg_file"] = os.path.relpath(svg, REPO_ROOT).replace("\\", "/")
    r["coordinate_system"]["svg_alignment"] = al
    with open(svg, encoding="utf-8") as fh:
        return r, fh.read()


class ViewerBuildTest(unittest.TestCase):

    def test_all_samples_build_and_pass_checks(self):
        for path in SAMPLES:
            with self.subTest(sample=os.path.basename(path)):
                r, svg = extraction_with_svg(path)
                page = build.build_drawing_html(r, svg)
                self.assertEqual(check.check_drawing_html(page, r), [])
                data = check.embedded_data(page)
                self.assertEqual(len(data["nodes"]), len(r["nodes"]))
                self.assertEqual(data["coordinate_system"]["svg_alignment"]["offset"], [19.0, 19.0])

    def test_offset_read_from_data_not_hardcoded(self):
        with open(build.TEMPLATE, encoding="utf-8") as fh:
            tpl = fh.read()
        self.assertIn("svg_alignment", tpl)
        self.assertNotRegex(tpl, r"\b19\b")

    def test_svg_cleanup(self):
        _, svg = extraction_with_svg(SAMPLES[0])
        self.assertIn("drawio.com", svg)
        cleaned = build.prepare_svg(svg)
        self.assertTrue(cleaned.startswith("<svg"))
        self.assertNotIn("drawio.com", cleaned)
        self.assertNotIn(' content="', cleaned[:2000])
        self.assertEqual(set(re.findall(r'data-cell-id="([^"]+)"', svg)),
                         set(re.findall(r'data-cell-id="([^"]+)"', cleaned)))

    def test_missing_offset_is_rejected(self):
        r, svg = extraction_with_svg(SAMPLES[0])
        r["coordinate_system"]["svg_alignment"] = None
        with self.assertRaises(ValueError):
            build.build_drawing_html(r, svg)

    def test_check_detects_problems(self):
        r, svg = extraction_with_svg(SAMPLES[0])
        page = build.build_drawing_html(r, svg)
        # 외부 참조
        bad = page.replace("</head>", '<script src="https://cdn.example.com/x.js"></script></head>')
        self.assertTrue(any("외부 참조" in p for p in check.check_drawing_html(bad, r)))
        bad = page.replace("</body>", "<script>fetch('x.json')</script></body>")
        self.assertTrue(any("외부 참조" in p for p in check.check_drawing_html(bad, r)))
        # 데이터 누락
        r2, _ = extraction_with_svg(SAMPLES[0])
        r2["nodes"] = r2["nodes"][1:]
        short = build.build_drawing_html(r2, svg)
        self.assertTrue(any("nodes 누락" in p for p in check.check_drawing_html(short, r)))
        # viewBox 밖 좌표
        r3, _ = extraction_with_svg(SAMPLES[0])
        r3["source_locations"][0]["bbox"] = [5000, 5000, 10, 10]
        far = build.build_drawing_html(r3, svg)
        self.assertTrue(any("viewBox 밖" in p for p in check.check_drawing_html(far, r3)))

    def test_script_close_tag_in_data_is_escaped(self):
        r, svg = extraction_with_svg(SAMPLES[0])
        r["nodes"][0]["label_text"] = "</script><b>x"
        page = build.build_drawing_html(r, svg)
        self.assertEqual(check.embedded_data(page)["nodes"][0]["label_text"], "</script><b>x")

    # XML로는 올바르지만 실행 가능 요소를 담은 우회 사례: 정화 후 흔적이 없어야 한다
    WELL_FORMED_ATTACKS = [
        '<script>alert("a1")</script><script type="text/javascript"/>',
        '<g onload="alert(\'a2\')"><rect width="1" height="1"/></g>',
        '<a xlink:href="javascript:alert(\'a3\')"><rect width="1" height="1"/></a>',
        '<a href=\' JavaScript:alert(1)\'><rect width="1" height="1"/></a>',
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml"><script>alert("a4")</script>'
        '<img src="x" onerror="alert(\'a5\')"/><iframe srcdoc="&lt;script&gt;alert(\'a6\')&lt;/script&gt;"/></div></foreignObject>',
        '<image href="javascript&#58;alert(\'a7\')" width="1" height="1"/>',
        '<use xlink:href="java&#x09;script:alert(\'a8\')"/>',
        '<rect width="1" height="1"><animate attributeName="href" values="0;javascript:alert(\'a9\')"/></rect>',
        '<a xlink:href="#x"><set attributeName="href" to="javascript:alert(\'a10\')"/><text>t</text></a>',
        '<rect width="1" height="1" style="fill:url(https://evil.example/x)" fill="javascript:alert(\'a11\')"/>',
        '<image href="data:image/svg+xml;base64,PHN2Zy8+" width="1" height="1"/>',
    ]
    # XML로 읽을 수 없는 우회 사례: 정화기가 거부해야 한다
    MALFORMED_ATTACKS = [
        '<rect width="1""onerror="alert(1)"/>',
        '<rect width="1"onerror="alert(1)"/>',
        '<rect/onclick="alert(1)"/>',
        '<a href=javascript:alert(1)><rect/></a>',
    ]

    def inject_svg(self, svg, payload):
        self.assertIn('<g data-cell-id="0">', svg)
        return svg.replace('<g data-cell-id="0">', payload + '<g data-cell-id="0">', 1)

    def test_malicious_svg_is_sanitized(self):
        r, svg = extraction_with_svg(SAMPLES[0])
        for payload in self.WELL_FORMED_ATTACKS:
            with self.subTest(payload=payload[:50]):
                page = build.build_drawing_html(r, self.inject_svg(svg, payload))
                stage = check.stage_markup(page)
                self.assertNotIn("alert", stage)
                self.assertNotRegex(stage, r"(?i)javascript|evil\.example|svg\+xml|<(script|iframe|img|animate|set)\b")
                self.assertEqual(check.active_content(page), [])
                self.assertEqual(check.check_drawing_html(page, r), [])

    def test_svg_ids_are_prefixed_with_refs(self):
        r, svg = extraction_with_svg(SAMPLES[0])
        payload = ('<defs><linearGradient id="grad"><stop offset="0" stop-color="#000"/></linearGradient></defs>'
                   '<text id="extraction">x</text><rect id="graph" width="1" height="1" fill="url(#grad)" '
                   'style="fill:url(\'#grad\')"/><use href="#grad"/><g id="overlay"/><g id="panel"/>')
        page = build.build_drawing_html(r, self.inject_svg(svg, payload))
        stage = check.stage_markup(page)
        ids = re.findall(r'\sid="([^"]*)"', stage)
        self.assertTrue({"svg-extraction", "svg-graph", "svg-grad", "svg-overlay", "svg-panel"} <= set(ids))
        self.assertFalse(set(ids) & build.TEMPLATE_IDS)
        self.assertIn('fill="url(#svg-grad)"', stage)
        self.assertIn("url(&#x27;#svg-grad&#x27;)", stage)  # 속성 값 안의 따옴표는 이스케이프됨
        self.assertIn('href="#svg-grad"', stage)
        self.assertEqual(check.id_conflicts(page), [])
        self.assertEqual(check.check_drawing_html(page, r), [])
        # 정화를 거치지 않은 충돌 id는 검사가 잡아야 한다
        for raw in ('<text id="extraction">x</text>', '<g id="graph"/>', '<g id="no-prefix"/>'):
            bad = page.replace('<div id="stage">', '<div id="stage">' + raw, 1)
            self.assertTrue(check.id_conflicts(bad), raw)
            self.assertTrue(check.check_drawing_html(bad, r), raw)

    def test_template_ids_listed_in_one_place(self):
        with open(build.TEMPLATE, encoding="utf-8") as fh:
            tpl = fh.read()
        used = set(re.findall(r'\bid\s*[=:]\s*\\?["\']([A-Za-z][\w-]*)\\?["\']', tpl))
        used |= set(re.findall(r'getElementById\("([\w-]+)"\)', tpl))
        self.assertEqual(used - build.TEMPLATE_IDS, set())
        self.assertFalse(any(i.startswith(sanitize.ID_PREFIX) for i in build.TEMPLATE_IDS))

    def test_malformed_svg_is_rejected(self):
        r, svg = extraction_with_svg(SAMPLES[0])
        for payload in self.MALFORMED_ATTACKS:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    build.build_drawing_html(r, self.inject_svg(svg, payload))

    def test_check_flags_active_content(self):
        r, svg = extraction_with_svg(SAMPLES[0])
        page = build.build_drawing_html(r, svg)
        injects = ['<script>x()</script>', '<rect onclick="x()"/>', '<a href="javascript:x()">a</a>',
                   '<image href="javascript&#58;x()"/>', '<use href="java&#x09;script:x()"/>',
                   '<animate values="javascript:x()"/>', '<set attributeName="href" to="#a"/>',
                   '<foreignObject><iframe srcdoc="x"/></foreignObject>'] + self.MALFORMED_ATTACKS
        for inject in injects:
            with self.subTest(inject=inject):
                bad = page.replace("<div id=\"stage\">", "<div id=\"stage\">" + inject, 1)
                self.assertTrue(check.active_content(bad), inject)
                self.assertTrue(check.check_drawing_html(bad, r), inject)

    def test_json_is_fully_escaped(self):
        r, svg = extraction_with_svg(SAMPLES[0])
        tricky = "<!-- <script> </script> -->"
        r["nodes"][0]["label_text"] = tricky
        page = build.build_drawing_html(r, svg)
        m = re.search(r'<script type="application/json" id="extraction">(.*?)</script>', page, re.S)
        self.assertNotIn("<", m.group(1))
        self.assertEqual(check.embedded_data(page)["nodes"][0]["label_text"], tricky)
        self.assertEqual(check.active_content(page), [])

    def test_unverified_alignment_shows_warning(self):
        r, svg = extraction_with_svg(SAMPLES[0])
        page = build.build_drawing_html(r, svg)
        self.assertNotIn("SVG 좌표 정렬 미검증", page.split('<script type="application/json"')[0])
        r["coordinate_system"]["svg_alignment"]["status"] = "failed"
        r["coordinate_system"]["svg_alignment"]["reasons"] = ["테스트 사유"]
        page = build.build_drawing_html(r, svg)
        head = page.split('<script type="application/json"')[0]
        self.assertIn("SVG 좌표 정렬 미검증: 테스트 사유", head)
        problems = check.check_drawing_html(page, r)
        self.assertTrue(any("정렬 미검증" in p for p in problems))
        self.assertFalse(any("경고가 화면에 없음" in p for p in problems))

    def test_build_all_rejects_svg_outside_repo(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        r, _ = extraction_with_svg(SAMPLES[0])
        r["coordinate_system"]["svg_alignment"]["svg_file"] = "../../outside.svg"
        d = os.path.join(tmp, "ex", "X")
        os.makedirs(d)
        with open(os.path.join(d, "extraction.json"), "w", encoding="utf-8") as fh:
            json.dump(r, fh, ensure_ascii=False)
        with self.assertRaises(ValueError):
            build.build_all(os.path.join(tmp, "ex"), os.path.join(tmp, "out"), REPO_ROOT)

    def test_template_has_search_limit_and_direction_marks(self):
        with open(build.TEMPLATE, encoding="utf-8") as fh:
            tpl = fh.read()
        self.assertIn("SEARCH_LIMIT = 50", tpl)
        self.assertIn("r.flow_direction", tpl)  # 방향 있을 때만 화살표
        self.assertIn("@media (max-width: 760px)", tpl)
        # 층 순서: 배관 층이 심볼 층보다 먼저(아래) 만들어진다
        self.assertLess(tpl.index('id: "layer-pipe"'), tpl.index('id: "layer-symbol"'))

    def test_build_all_writes_index(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        ex_root = os.path.join(tmp, "ex")
        for path in SAMPLES[:2]:
            r, _ = extraction_with_svg(path)
            d = os.path.join(ex_root, r["drawing"]["drawing_number"])
            os.makedirs(d)
            with open(os.path.join(d, "extraction.json"), "w", encoding="utf-8") as fh:
                json.dump(r, fh, ensure_ascii=False)
        out = os.path.join(tmp, "out")
        entries = build.build_all(ex_root, out, REPO_ROOT)
        self.assertEqual(len(entries), 2)
        with open(os.path.join(out, "index.html"), encoding="utf-8") as fh:
            index = fh.read()
        for e in entries:
            self.assertIn('href="%s"' % e["file"], index)
            self.assertTrue(os.path.isfile(os.path.join(out, e["file"])))
        self.assertEqual(check.external_refs(index), [])


if __name__ == "__main__":
    unittest.main()
