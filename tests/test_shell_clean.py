"""새 화면의 정리된 보기(hazop/shell/web/js/canvas/clean_view.js·core.js·clean_ui.js, docs/design/app-shell-web.md §10) 오프스크린 시험.
실행: python -m unittest tests.test_shell_clean

SNP-M-101 표본에 미확인 넷(못 읽은 기호, 열린 끝, 태그 없음, 그림 없는 kind)을 섞어 실제 `build_items`·`clean_items.build` 자료로 그린다. 원본 보기와
정리된 보기의 좌표가 같은지, 자리표가 그려지는지, 표시가 그 객체의 색을 바꾸는지, 글이 텍스트로만 들어가는지, 5,800개 쪽의 시간을 본다.
Chromium은 file://의 ES 모듈을 막으므로 별도 프로세스에서 `--allow-file-access-from-files`로 띄운다(tests/test_shell_canvas.py와 같은 방식).

    python tests/test_shell_clean.py --child <결과 파일>    (내부용)
"""

import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

CANVAS = os.path.join(REPO, "hazop", "shell", "web", "js", "canvas")


def file_url(path):
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def mix_unknowns(ex):
    """추출 결과(고친 것)에 미확인 넷을 섞는다: 못 읽은 기호, 그림 없는 kind, 태그 없는 밸브, 열린 끝 배관, HTML처럼 보이는 태그."""
    nodes = ex["nodes"]
    # 섞기: ① 못 읽은 기호 ② 그림 없는 kind ③ 태그 없는 밸브 ④ 한쪽 끝이 열린 배관 ⑤ HTML처럼 보이는 태그. 기존 요소와 겹치지 않는 빈 자리에 놓는다
    taken = []
    for n in nodes:
        g = n.get("geometry") or {}
        if g.get("width") is not None:
            taken.append((g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"]))
    for r in ex["relations"]:
        pts = [e["point"] for e in r.get("endpoints") or [] if e.get("point")] + [tuple(w) for w in r.get("waypoints") or []]
        if pts:
            taken.append((min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)))
    free = []

    def slot(w, h):
        for y in range(40, 900, 30):
            for x in range(40, 1400, 30):
                box = (x, y, x + w, y + h)
                if all(box[2] + 20 < t[0] or box[0] - 20 > t[2] or box[3] + 60 < t[1] or box[1] - 60 > t[3] for t in taken + free):
                    free.append(box)
                    return x, y
        raise RuntimeError("빈 자리가 없음")
    x, y = slot(40, 40)
    nodes.append({"local_id": "x-unknown", "classification": "unclassified", "category": None, "kind": None, "tag": "", "style": "",
                  "geometry": {"x": x, "y": y, "width": 40, "height": 40}})
    x, y = slot(50, 40)
    nodes.append({"local_id": "x-weird", "classification": "classified", "category": "equipment", "kind": "weird_kind", "tag": "W-1", "style": "",
                  "geometry": {"x": x, "y": y, "width": 50, "height": 40}})
    x, y = slot(30, 120)
    nodes.append({"local_id": "x-notag", "classification": "classified", "category": "valve", "kind": "manual_valve", "tag": "", "style": "",
                  "geometry": {"x": x, "y": y + 70, "width": 30, "height": 50}})
    ex["relations"].append({"local_id": "x-open", "kind": "physical_connection", "line_type": "process", "line_no": "X-1", "waypoints": [],
                            "endpoints": [{"end": "source", "node_local_id": "x-notag", "point": [x + 15, y + 70], "status": "connected"},
                                          {"end": "target", "node_local_id": None, "point": [x + 15, y], "status": "unknown"}],
                            "flow_direction": {"basis": "source_to_target"}})
    x, y = slot(60, 80)
    nodes.append({"local_id": "x-html", "classification": "classified", "category": "equipment", "kind": "tank", "tag": "<img src=x onerror=window.__pwned=1>", "style": "",
                  "geometry": {"x": x, "y": y, "width": 60, "height": 80}})
    return ex


def sample_payload():
    """SNP-M-101 + 섞은 미확인 → {sheet(items), clean(extras), symbols, svg}. 엔진이 줄 모양과 같다."""
    from hazop import paths
    from hazop.shell import clean_items, sheet_items
    from tests.test_clean_items import snp_extractions
    ex = mix_unknowns(snp_extractions()["SNP-M-101"])
    built = sheet_items.build_items(ex)
    svg = [p for p in glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio.svg")) if "SNP-M-101" in p][0]
    with open(os.path.join(CANVAS, "symbols.json"), encoding="utf-8") as fh:
        symbols = json.load(fh)["symbols"]
    sheet = {"graph_id": "graph-SNP-M-101", "rev": 1, "width": built["width"], "height": built["height"], "svg": file_url(svg), "items": built["items"], "links": []}
    return {"sheet": sheet, "clean": clean_items.build(ex), "symbols": symbols}


HARNESS = """<!doctype html><html><head><meta charset="utf-8"><title>clean</title>
<style>html,body{margin:0;padding:0;background:#f4f5f7}</style></head><body>
<script id="data" type="application/json">%(data)s</script>
<script type="module">
import * as CV from "%(clean_view)s";
import * as MK from "%(marks)s";
import { SheetCore } from "%(core)s";
import { run } from "%(cases)s";
window.__res = null;
const data = JSON.parse(document.getElementById("data").textContent);
run({ CV, MK, SheetCore }, data).then((r) => { window.__res = JSON.stringify(r); })
  .catch((e) => { window.__res = JSON.stringify({ error: String((e && e.stack) || e) }); });
</script></body></html>"""


def child_main(out_path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --disable-gpu-compositing --log-level=3 --allow-file-access-from-files"
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication
    app = QApplication(["clean-test"])
    data = sample_payload()
    tmp = tempfile.mkdtemp(prefix="hazop-clean-")
    page = os.path.join(tmp, "harness.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(HARNESS % {"data": json.dumps(data).replace("</", "<\\/"), "clean_view": file_url(os.path.join(CANVAS, "clean_view.js")),
                            "marks": file_url(os.path.join(CANVAS, "marks.js")), "core": file_url(os.path.join(CANVAS, "core.js")),
                            "cases": file_url(os.path.join(REPO, "tests", "shell_clean_cases.js"))})
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
        if state["tries"] > 900:
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
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    os._exit(0)


class CleanViewWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = os.path.join(tempfile.mkdtemp(prefix="hazop-clean-out-"), "result.json")
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", out], cwd=REPO, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                              capture_output=True, text=True, timeout=300)
        cls.stderr = proc.stderr[-800:]
        with open(out, encoding="utf-8") as fh:
            cls.result = json.load(fh)

    def test_web_cases_all_pass(self):
        self.assertNotIn("error", self.result, self.result.get("error"))
        rows = self.result["results"]
        failed = [r for r in rows if not r[1]]
        self.assertEqual(failed, [], "\n".join("%s — %s" % (n, d) for n, _ok, d in failed))
        self.assertGreaterEqual(len(rows), 25, "웹 시험 항목이 모자람")

    def test_timings_are_printed_and_within_the_spec_targets(self):
        self.assertNotIn("error", self.result, self.result.get("error"))
        t = self.result["timings"]
        print("\n[정리된 보기 구성요소 %(items)d개(기호 %(symbols)d·배관 %(pipes)d, 합성) | 오프스크린 QtWebEngine 1000x700, %(runs)d회 중앙값] 처음 그리기 %(first_ms).0fms · "
              "원본↔정리 바꾸기 %(switch_ms).1fms · 경로 색 바꾸기(표시 200개) %(path200_ms).1fms · 표시 3,000개 %(marks3000_ms).0fms · 그려진 요소 %(elements)d개" % t)
        self.assertLess(t["first_ms"], 1500)        # 규격 §10.8: 정리된 SVG 처음 만들기 1.5초 이하
        self.assertLess(t["switch_ms"], 100)        # 원본 ↔ 정리 바꾸기 100ms 이하
        self.assertLess(t["path200_ms"], 100)       # 표시 색 바꾸기(200개) 100ms 이하

    def test_no_unsafe_html_in_clean_modules(self):
        bad = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "dangerouslySetInnerHTML")
        for name in ("clean_view.js", "clean_ui.js"):
            with open(os.path.join(CANVAS, name), encoding="utf-8") as fh:
                text = fh.read()
            for b in bad:
                self.assertNotIn(b, text, "%s: %s" % (name, b))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        child_main(sys.argv[2])
    else:
        unittest.main()
