"""새 화면의 도면 구성요소(hazop/shell/web/js/canvas/) 시험. 실행: python -m unittest tests.test_shell_canvas

웹 쪽 단위 시험(tests/shell_canvas_cases.js)을 오프스크린 웹뷰에서 돈다. Chromium은 file://의 ES 모듈을 막으므로(규격 §5.1) 이 시험은
별도 프로세스에서 `--allow-file-access-from-files`로 띄운다. 새 틀의 hazop-app:// 처리기가 생기면 그쪽 시험으로 옮길 수 있다.
표본은 resources/samples의 SNP 도면(SNP-M-102)이고 도면 자료(JSON)는 README의 모양으로 이 파일이 만든다(엔진의 api.py가 만들 모양의 기준).
큰 도면 시간은 합성 자료(기호 3,000 + 배관 2,800)다. 네트워크 사용 없음. 시험 하나가 별도 프로세스를 한 번만 띄운다.

    python tests/test_shell_canvas.py --child <결과 파일>    (내부용)
"""

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

CANVAS = os.path.join(REPO, "hazop", "shell", "web", "js", "canvas")
BIG = {"symbols": 3000, "pipes": 2800}


def file_url(path):
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def sample_sheet():
    """SNP-M-102 추출 + 바탕 SVG로 도면 자료(README의 api/sheet 모양)를 만든다. 배관은 끝점·경유점을 이은 선이다."""
    from hazop import paths
    from hazop.extract import drawio, svg_align
    src = [p for p in glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio")) if "SNP-M-102" in p][0]
    r = drawio.extract(src, repo_root=REPO)
    svg = glob.glob(os.path.join(os.path.dirname(src), "*.drawio.svg"))[0]
    r["coordinate_system"]["svg_alignment"] = svg_align.align(svg, r)
    off = r["coordinate_system"]["svg_alignment"]["offset"]
    with open(svg, encoding="utf-8") as fh:
        text = fh.read()
    vb = [float(x) for x in re.search(r'viewBox="([^"]+)"', text).group(1).replace(",", " ").split()]
    loc = {l["local_id"]: l for l in r["source_locations"]}
    items = []
    for n in r["nodes"]:
        l = loc.get(n["local_id"])
        if not l:
            continue
        b = l["bbox"]
        x0, y0 = b[0] - off[0], b[1] - off[1]
        items.append({"id": n["local_id"], "kind": n.get("kind"), "category": n.get("category"), "tag": n.get("tag"), "layer": "symbol",
                      "bbox": [x0, y0, x0 + max(b[2], 8), y0 + max(b[3], 8)], "polyline": None,
                      "classification": n.get("classification"), "unknown": n.get("classification") != "classified", "node_id": None})
        ll = n.get("label_location")
        if ll:
            t = ll["bbox"]
            items.append({"id": n["local_id"], "kind": n.get("kind"), "category": n.get("category"), "tag": n.get("tag") or "", "layer": "tag",
                          "bbox": [t[0] - off[0], t[1] - off[1], t[0] - off[0] + t[2], t[1] - off[1] + t[3]], "polyline": None,
                          "classification": n.get("classification"), "unknown": False, "node_id": None})
    for rel in r["relations"] + r["unresolved_connectors"]:
        pts = [e["point"] for e in rel["endpoints"][:1] if e.get("point")] + list(rel.get("waypoints") or []) + \
              [e["point"] for e in rel["endpoints"][1:] if e.get("point")]
        if len(pts) < 2:
            continue
        line = [[p[0] - off[0], p[1] - off[1]] for p in pts]
        xs, ys = [p[0] for p in line], [p[1] for p in line]
        items.append({"id": rel["local_id"], "kind": rel.get("kind"), "category": None, "tag": None, "layer": "pipe",
                      "bbox": [min(xs), min(ys), max(xs), max(ys)], "polyline": line, "classification": None, "unknown": False, "node_id": None})
    return {"graph_id": "graph-SNP-M-102", "rev": 1, "width": vb[2], "height": vb[3], "svg": file_url(svg), "items": items, "links": []}


HARNESS = """<!doctype html><html><head><meta charset="utf-8"><title>canvas</title>
<style>html,body{margin:0;padding:0;background:#f4f5f7}</style></head><body>
<script id="data" type="application/json">%(data)s</script>
<script type="module">
import * as IDX from "%(index)s";
import * as MK from "%(marks)s";
import { SheetCore } from "%(core)s";
import { run } from "%(cases)s";
import * as SheetMod from "%(sheet)s";
import * as HooksStub from "%(hooks)s";
window.__res = null;
const data = JSON.parse(document.getElementById("data").textContent);
run({ IDX, MK, SheetCore, SheetMod, HooksStub }, data, %(big)s).then((r) => { window.__res = JSON.stringify(r); })
  .catch((e) => { window.__res = JSON.stringify({ error: String((e && e.stack) || e) }); });
</script></body></html>"""


def child_main(out_path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --disable-gpu-compositing --log-level=3 --allow-file-access-from-files"
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication
    app = QApplication(["canvas-test"])
    data = sample_sheet()
    tmp = tempfile.mkdtemp(prefix="hazop-canvas-")
    page = os.path.join(tmp, "harness.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(HARNESS % {"data": json.dumps(data).replace("</", "<\\/"), "index": file_url(os.path.join(CANVAS, "index.js")),
                            "marks": file_url(os.path.join(CANVAS, "marks.js")), "core": file_url(os.path.join(CANVAS, "core.js")),
                            "cases": file_url(os.path.join(REPO, "tests", "shell_canvas_cases.js")), "big": json.dumps(BIG),
                            "sheet": "%(sheet)s", "hooks": "%(hooks)s"})
    # sheet.js(Preact 쪽 포장)는 vendor가 아직 없어도 확인하도록, 임시 폴더에 canvas 사본과 아주 작은 대역(h·useRef·useEffect)을 둔다
    import shutil
    stub_root = os.path.join(tmp, "web")
    shutil.copytree(CANVAS, os.path.join(stub_root, "js", "canvas"), ignore=shutil.ignore_patterns("README.md"))
    os.makedirs(os.path.join(stub_root, "vendor"))
    with open(os.path.join(stub_root, "vendor", "preact.module.js"), "w", encoding="utf-8") as fh:
        fh.write("export const h = (tag, props, ...kids) => ({ tag, props: props || {}, kids });\n")
    with open(os.path.join(stub_root, "vendor", "hooks.module.js"), "w", encoding="utf-8") as fh:
        fh.write("let refs = [], effects = [], i = 0;\n"
                 "export function begin() { i = 0; effects = []; }\n"
                 "export function useRef(v) { if (!refs[i]) refs[i] = { current: v }; return refs[i++]; }\n"
                 "export function useEffect(fn, deps) { effects.push([fn, deps]); }\n"
                 "export function flush() { const es = effects; effects = []; return es.map(([f]) => f()); }\n")
    sheet_url = file_url(os.path.join(stub_root, "js", "canvas", "sheet.js"))
    hooks_url = file_url(os.path.join(stub_root, "vendor", "hooks.module.js"))
    html = open(page, encoding="utf-8").read().replace("%(sheet)s", sheet_url).replace("%(hooks)s", hooks_url)
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(html)
    view = QWebEngineView()
    s = view.page().settings()
    s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
    s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
    view.resize(1000, 700)
    view.show()
    result = {"error": "시간 초과"}
    state = {"tries": 0}

    def poll():
        state["tries"] += 1
        if state["tries"] > 600:
            app.quit()
            return

        def got(v):
            if v:
                result.clear()
                result.update(json.loads(v))
                app.quit()
            else:
                QTimer.singleShot(100, poll)
        view.page().runJavaScript("window.__res", 0, got)

    view.loadFinished.connect(lambda ok: poll() if ok else (result.update(error="페이지를 읽지 못함"), app.quit()))
    view.load(QUrl.fromLocalFile(page))
    app.exec()
    result["items"] = len(data["items"])
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    os._exit(0)   # 웹 엔진 프로세스가 남아 종료가 막히지 않게


class CanvasWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = os.path.join(tempfile.mkdtemp(prefix="hazop-canvas-out-"), "result.json")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", out], cwd=REPO, env=env, capture_output=True, text=True,
                              timeout=240)
        cls.stderr = proc.stderr[-800:]
        with open(out, encoding="utf-8") as fh:
            cls.result = json.load(fh)

    def test_web_cases_all_pass(self):
        self.assertNotIn("error", self.result, self.result.get("error"))
        rows = self.result["results"]
        self.assertGreaterEqual(len(rows), 60, "웹 시험 항목이 모자람")
        failed = [r for r in rows if not r[1]]
        self.assertEqual(failed, [], "\n".join("%s — %s" % (n, d) for n, _ok, d in failed))

    def test_big_sheet_timings(self):
        """합성 자료(기호 3,000 + 배관 2,800, 태그 상자 3,000). 값은 출력에 남기고 상한은 규격 §5.4 목표(네모 고르기 100ms)보다 넉넉하게 둔다."""
        self.assertNotIn("error", self.result, self.result.get("error"))
        t = self.result["timings"]
        print("\n[큰 도면 항목 %(items)d개(기호 %(symbols)d·배관 %(pipes)d) | 오프스크린 QtWebEngine 1000x700, 1회 실행] 자료 넣기 %(setData_ms).0fms · "
              "전체 네모 질의 %(queryBox_all_ms).1fms · 작은 네모 질의 %(queryBox_small_ms).3fms · 누르기 판정 평균 %(hitTest_avg_ms).4fms · "
              "표시 3,000개 %(mark_3000_ms).0fms · 경로 600단계 %(path_600_ms).0fms · 구간 3겹 칠하기 %(segments_3overlap_ms).0fms · "
              "전체 네모 고르기(이벤트부터 고른 2,000개 그리기까지) %(boxSelect_all_ms).0fms · "
              "525구간 칠하기 %(segments_525_ms).0fms · 구간 하나 강조 %(segments_focus_ms).0fms · 구간 밖 5,000개 흐리게 %(outside_5000_ms).0fms" % t)
        self.assertLess(t["queryBox_all_ms"], 100)
        self.assertLess(t["queryBox_small_ms"], 5)
        self.assertLess(t["hitTest_avg_ms"], 2)
        self.assertLess(t["boxSelect_all_ms"], 500)
        self.assertLess(t["mark_3000_ms"], 1500)
        self.assertLess(t["setData_ms"], 1500)

    def test_no_unsafe_html_in_canvas_modules(self):
        """도면·모델에서 온 글을 HTML로 넣는 길이 없다(규격 §5.5): innerHTML·outerHTML·insertAdjacentHTML·dangerouslySetInnerHTML·eval·new Function."""
        bad = []
        for path in glob.glob(os.path.join(CANVAS, "*.js")):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            text = re.sub(r"//[^\n]*", "", text)
            for pat in (r"\binnerHTML\b", r"\bouterHTML\b", r"insertAdjacentHTML", r"dangerouslySetInnerHTML", r"\beval\s*\(", r"new\s+Function\b", r"document\.write"):
                if re.search(pat, text):
                    bad.append("%s: %s" % (os.path.basename(path), pat))
        self.assertEqual(bad, [])

    def test_no_network_requests_in_canvas_modules(self):
        for path in glob.glob(os.path.join(CANVAS, "*.js")):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotRegex(re.sub(r"//[^\n]*", "", text), r"https?://", os.path.basename(path))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        child_main(sys.argv[2])
    else:
        unittest.main()
