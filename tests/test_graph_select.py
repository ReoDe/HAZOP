"""그래프 노드 선택 표시 렌더 검사 (docs/units/2026-11-05-design-system W7, D10). 실행: python -m unittest discover -s tests -t .

설비 노드(#1d4ed8)는 선택 테두리(#2563eb)와 1.30:1이라 테두리 색만 바꾸면 선택이 보이지 않는다(W5 §6.1).
W7은 노드 흰 테두리를 그대로 두고 바깥 --ui 고리를 노드 층과 라벨 층 사이에 그린다.

렌더 검사는 별도 프로세스(QT_QPA_PLATFORM=offscreen, QT_SCALE_FACTOR 1·1.25)에서 돌린다. 하위 프로세스는 SNP-M-102 뷰어를
독립 뷰어(템플릿만)와 앱 내장(HazopWebView, web_css 주입)으로 띄우고, 설비 노드를 좌표 클릭(QTest)으로 선택한 전후 화면을 잡아
고리 자리 8개 각도 구간 모두에 --ui 화소가 생기는지, 라벨 첫 글자가 가려지지 않는지 판정한다. 실패하면 화면 경로를 출력한다.
기다림은 신호(loadFinished·ready·runJavaScript 콜백)와 QTimer 확인(시간 상한)으로만 한다(sleep 없음). 네트워크 사용 없음.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from hazop import paths  # noqa: E402

NODE = "local-node-001"   # SNP-M-102의 설비 노드(RC-PZ01). 이 도면의 설비 노드는 하나
NODE_R = 7                # template.html NODE_R.equipment
RING_OFFSET = 4           # 선택 고리 반지름 = NODE_R + 4
RING_W = 2.5              # 선택 고리 선 굵기
TOL = 12                  # 화소 색 허용 차(채널별). 설비 채움과 --ui 차이는 (8, 21, 19)라 설비 채움은 세지 않는다
SECTORS = 8
SECTOR_MIN = 0.15         # 각 구간의 판정 고리 화소 중 --ui 화소 비율 하한(간선·라벨이 일부 지나감)
SCALES = ("1", "1.25")


def _rgb(hex_color):
    v = hex_color.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def css_rgb(hex_color):
    return "rgb(%d, %d, %d)" % _rgb(hex_color)


def build_viewer_html(out_dir):
    """SNP-M-102 추출·그래프로 뷰어 HTML을 만든다(저장소 output/은 건드리지 않음)."""
    import glob
    from hazop.extract import drawio, svg_align
    from hazop.graph import build as gbuild
    from hazop.viewer import build
    src = [p for p in glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio"))
           if "SNP-M-102" in p][0]
    r = drawio.extract(src, repo_root=REPO_ROOT)
    svg = glob.glob(os.path.join(os.path.dirname(src), "*.drawio.svg"))[0]
    r["coordinate_system"]["svg_alignment"] = svg_align.align(svg, r)
    with open(svg, encoding="utf-8") as fh:
        page = build.build_drawing_html(r, fh.read(), gbuild.build_graph(r))
    path = os.path.join(out_dir, "SNP-M-102.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return path


# ---------------------------------------------------------------- 하위 프로세스(Qt) 도구
def wait_signal(signal, timeout_ms=30000, start=None):
    """signal이 올 때까지 이벤트 루프를 돌린다(시간 상한 타이머). 받은 인자 목록, 시간 초과면 None."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop, got = QEventLoop(), []

    def on(*args):
        got.append(args)
        loop.quit()
    signal.connect(on)
    QTimer.singleShot(timeout_ms, loop.quit)
    if start:
        start()
    if not got:
        loop.exec()
    signal.disconnect(on)
    return got[0] if got else None


def js(view, code, timeout_ms=15000):
    from PySide6.QtCore import QEventLoop, QTimer
    loop, out = QEventLoop(), []

    def done(v):
        out.append(v)
        loop.quit()
    QTimer.singleShot(timeout_ms, loop.quit)
    view.page().runJavaScript(code, 0, done)
    if not out:
        loop.exec()
    if not out:
        raise AssertionError("JS 결과 없음: %s" % code[:80])
    return out[0]


def wait_until(cond, timeout_ms=10000, every_ms=50):
    """cond()가 참이 될 때까지 이벤트 루프를 돌린다. QTimer로 every_ms마다 확인하고 timeout_ms에 끝낸다(sleep 없음).
    화면 잡기(grab)는 웹 엔진이 새 프레임을 넘겨준 뒤에야 바뀌므로, 그린 결과는 이렇게 상한을 두고 확인한다."""
    from PySide6.QtCore import QEventLoop, QTimer
    if cond():
        return True
    loop, ok = QEventLoop(), [False]
    tick = QTimer()

    def check():
        tick.stop()  # cond() 안의 js()가 이벤트 루프를 돌리는 동안 같은 확인이 겹쳐 불리지 않게 한다
        if cond():
            ok[0] = True
            loop.quit()
        else:
            tick.start(every_ms)
    tick.timeout.connect(check)
    tick.start(every_ms)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    tick.stop()
    return ok[0] or bool(cond())


def sector_counts(img, color, cx, cy, r_in, r_out, n=SECTORS):
    """(cx, cy) 중심 r_in~r_out(CSS px) 고리를 각도 n구간으로 나눠 구간별 [color 화소 수, 전체 화소 수]."""
    dpr = img.devicePixelRatio() or 1.0
    want = _rgb(color)
    out = [[0, 0] for _ in range(n)]
    for y in range(max(int((cy - r_out) * dpr), 0), min(int((cy + r_out) * dpr) + 1, img.height())):
        for x in range(max(int((cx - r_out) * dpr), 0), min(int((cx + r_out) * dpr) + 1, img.width())):
            dx, dy = (x + 0.5) / dpr - cx, (y + 0.5) / dpr - cy
            if not (r_in ** 2 <= dx * dx + dy * dy <= r_out ** 2):
                continue
            k = int((math.atan2(dy, dx) + math.pi) / (2 * math.pi) * n) % n
            out[k][1] += 1
            c = img.pixelColor(x, y)
            if all(abs(a - b) <= TOL for a, b in zip((c.red(), c.green(), c.blue()), want)):
                out[k][0] += 1
    return out


def dark_pixels(img, rect):
    """rect(x, y, w, h, CSS px) 안의 어두운 화소(라벨 글자 --ink-2, 채널 최댓값 < 120) 수. --ui·설비 채움은 세지 않는다."""
    dpr = img.devicePixelRatio() or 1.0
    x, y, w, h = rect
    n = 0
    for py in range(max(int(y * dpr), 0), min(int((y + h) * dpr) + 1, img.height())):
        for px in range(max(int(x * dpr), 0), min(int((x + w) * dpr) + 1, img.width())):
            c = img.pixelColor(px, py)
            if max(c.red(), c.green(), c.blue()) < 120:
                n += 1
    return n


Q_NODE = "#graphsvg [data-local-id=\"%s\"]" % NODE
ERR_JS = ("window.__hzErr=[]; window.addEventListener('error', function (e) { window.__hzErr.push(String(e.message)); });"
          "window.__hzClicks=0; window.addEventListener('click', function () { window.__hzClicks++; }); 1")
ZOOM_JS = """(function () {
  var b = document.querySelector('%s').getBoundingClientRect(), vp = document.getElementById('viewport');
  for (var i = 0; i < 8; i++) vp.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, clientX: b.x + b.width / 2,
    clientY: b.y + b.height / 2, bubbles: true, cancelable: true }));
  return 1;
})()""" % Q_NODE
# 노드 화면 중심·배율·뷰포트, 라벨 첫 글자 화면 상자, 고리 위 간선 한 점
GEOM_JS = """(function () {
  var e = document.querySelector('%(q)s'), b = e.getBoundingClientRect(), s = b.width / (2 * %(r)d);
  var cx = b.x + b.width / 2, cy = b.y + b.height / 2, v = document.getElementById('viewport').getBoundingClientRect();
  var lab = Array.prototype.filter.call(document.querySelectorAll('#graphsvg text.glabel'), function (t) {
    return t.textContent === 'RC-PZ01'; })[0];
  var ch = lab.getExtentOfChar(0), m = lab.getScreenCTM(), sp = document.querySelector('#graphsvg').createSVGPoint();
  sp.x = ch.x; sp.y = ch.y; var p0 = sp.matrixTransform(m); sp.x = ch.x + ch.width; sp.y = ch.y + ch.height;
  var p1 = sp.matrixTransform(m);
  var eid = e.getAttribute('data-entity-id'), edge = null;
  Array.prototype.forEach.call(document.querySelectorAll('#graphsvg g[data-nodes]'), function (g) {
    var ns = g.getAttribute('data-nodes').split(' ');
    if (edge || ns.indexOf(eid) < 0 || g.getAttribute('data-kind') === 'has_endpoint') return;
    var other = document.querySelector('#graphsvg [data-entity-id="' + ns[ns[0] === eid ? 1 : 0] + '"]').getBoundingClientRect();
    var dx = other.x + other.width / 2 - cx, dy = other.y + other.height / 2 - cy, d = Math.sqrt(dx * dx + dy * dy);
    var lid = g.querySelector('.gedge-hit').getAttribute('data-local-id');
    edge = { lid: lid, x: cx + dx / d * %(ro)s * s, y: cy + dy / d * %(ro)s * s };
  });
  return JSON.stringify({ cx: cx, cy: cy, s: s, vp: [v.x, v.y, v.width, v.height],
    label: [Math.min(p0.x, p1.x), Math.min(p0.y, p1.y), Math.abs(p1.x - p0.x), Math.abs(p1.y - p0.y)], edge: edge });
})()""" % {"q": Q_NODE, "r": NODE_R, "ro": NODE_R + RING_OFFSET}
PANEL_JS = ("JSON.stringify({empty: document.getElementById('panel').textContent.indexOf('클릭하면 속성이') >= 0,"
            " links: document.querySelectorAll('#panel [data-goto]').length, h2: !!document.querySelector('#panel h2')})")
STYLE_JS = """(function () {
  function cs(e, p) { return e ? getComputedStyle(e)[p] : null; }
  var rings = document.querySelectorAll('#graphsvg .gsel-ring'), ring = rings[0], node = document.querySelector('%(q)s');
  var layer = ring.parentNode, lab = document.querySelector('#graphsvg text.glabel').parentNode;
  var rb = ring.getBoundingClientRect(), nb = node ? node.getBoundingClientRect() : null;
  return JSON.stringify({
    count: rings.length, hidden: ring.classList.contains('hidden'), display: cs(ring, 'display'),
    stroke: cs(ring, 'stroke'), width: cs(ring, 'strokeWidth'), opacity: cs(ring, 'opacity'),
    events: cs(ring, 'pointerEvents'), r: +ring.getAttribute('r'),
    cx: +ring.getAttribute('cx'), cy: +ring.getAttribute('cy'),
    node_cx: node ? +node.getAttribute('cx') : null, node_cy: node ? +node.getAttribute('cy') : null,
    node_stroke: cs(node, 'stroke'), node_selected: node ? node.classList.contains('selected') : null,
    after_nodes: !!node && layer.previousElementSibling === node.parentNode, before_labels: layer.nextElementSibling === lab,
    centre_gap: nb && !ring.classList.contains('hidden') ? Math.max(Math.abs(rb.x + rb.width / 2 - nb.x - nb.width / 2),
      Math.abs(rb.y + rb.height / 2 - nb.y - nb.height / 2)) : null,
    ring_screen_r: rb.width / 2, node_screen_r: nb ? nb.width / 2 : null,
    sym_stroke: cs(document.querySelector('#overlay .selected.sym'), 'stroke'),
    sym_width: cs(document.querySelector('#overlay .selected.sym'), 'strokeWidth'),
    errors: window.__hzErr || []
  });
})()""" % {"q": Q_NODE}


class RenderChecks:
    """하위 프로세스에서만 TestCase로 묶는다(부모 프로세스의 discover가 Qt를 띄우지 않게)."""
    OUT = None
    SCALE = "1"
    views = []

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.mkdtemp(prefix="hz-gsel-")
        cls.html = build_viewer_html(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        from PySide6.QtCore import QCoreApplication, QEvent
        from hazop.app.webview import HazopWebView
        for v in cls.views:
            if isinstance(v, HazopWebView):
                v.dispose()
            v.close()
            v.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QCoreApplication.processEvents()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- 열기
    def open_standalone(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
        v = QWebEngineView()
        self.views.append(v)
        v.resize(1200, 800)
        v.show()
        got = wait_signal(v.loadFinished, 60000, lambda: v.load(QUrl.fromLocalFile(self.html)))
        self.assertTrue(got and got[0], "뷰어 로드 실패")
        return v

    def open_embedded(self):
        from hazop.app.webview import HazopWebView
        v = HazopWebView()
        self.views.append(v)
        v.resize(1200, 800)
        v.show()
        self.assertTrue(wait_signal(v.bridge.ready, 60000, lambda: v.load_file(self.html)) is not None,
                        "내장 웹뷰 브리지 ready 없음")
        self.assertTrue(js(v, "document.body.classList.contains('hz-embedded')"))
        return v

    # ---- 도구
    def shot(self, v, name):
        img = v.grab().toImage()
        if self.OUT:
            img.save(os.path.join(self.OUT, "s%s-%s.png" % (self.SCALE.replace(".", ""), name)))
        return img

    def click(self, v, x, y):
        """좌표 클릭(QTest). 웹 페이지 입력은 focusProxy가 받는다."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        n = js(v, "window.__hzClicks")
        QTest.mouseClick(v.focusProxy() or v, Qt.LeftButton, Qt.NoModifier, QPoint(round(x), round(y)), 400)
        # 입력은 비동기로 전달된다: 페이지가 click을 처리한 뒤(창 수준 리스너는 페이지 처리 다음)로 순서를 맞춘다
        self.assertTrue(wait_until(lambda: js(v, "window.__hzClicks") > n), "좌표 클릭이 페이지에 닿지 않음")

    def fill_ready(self, v, g):
        """설비 노드 안쪽이 설비 색으로 그려졌는지(새 프레임이 넘어왔는지)."""
        from hazop.app import tokens
        sec = sector_counts(v.grab().toImage(), tokens.COLORS["equipment"], g["cx"], g["cy"], 0, (NODE_R - 2) * g["s"], 1)
        return sec[0][1] and sec[0][0] > sec[0][1] * 0.8

    def style(self, v):
        return json.loads(js(v, STYLE_JS))

    def sectors(self, img, g):
        from hazop.app import tokens
        s = g["s"]
        return sector_counts(img, tokens.COLORS["ui"], g["cx"], g["cy"],
                             (NODE_R + RING_OFFSET - RING_W / 2) * s, (NODE_R + RING_OFFSET + RING_W / 2) * s)

    def bad_sectors(self, v, g):
        sec = self.sectors(v.grab().toImage(), g)
        return [k for k, (h, t) in enumerate(sec) if not t or h < t * SECTOR_MIN], sec

    def assert_ring_drawn(self, v, g, name):
        wait_until(lambda: not self.bad_sectors(v, g)[0])
        img = self.shot(v, name)
        sec = self.sectors(img, g)
        bad = [k for k, (h, t) in enumerate(sec) if not t or h < t * SECTOR_MIN]
        self.assertFalse(bad, "%s: --ui 화소가 모자란 구간 %s / 구간별 %s / 화면 %s" % (name, bad, sec, self.OUT))
        return img

    def assert_visible_at_node(self, v, what):
        from hazop.app import tokens
        st = self.style(v)
        self.assertEqual(st["count"], 1, what)
        self.assertFalse(st["hidden"], what)
        self.assertEqual((st["cx"], st["cy"]), (st["node_cx"], st["node_cy"]), what)
        self.assertEqual(st["r"], NODE_R + RING_OFFSET, what)
        self.assertLess(st["centre_gap"], 0.5, what)
        self.assertAlmostEqual(st["ring_screen_r"] / st["node_screen_r"], (NODE_R + RING_OFFSET) / NODE_R, 2, what)
        self.assertEqual(st["stroke"], css_rgb(tokens.COLORS["ui"]), what)
        return st

    def assert_hidden(self, v, what):
        st = self.style(v)
        self.assertEqual(st["count"], 1, what)
        self.assertTrue(st["hidden"], what)
        self.assertEqual(st["display"], "none", what)
        return st

    # ---- 공통 흐름
    def run_common(self, v, kind):
        from hazop.app import tokens
        js(v, ERR_JS)
        js(v, "document.getElementById('tab-graph').click(); 1")
        js(v, ZOOM_JS)
        g = json.loads(js(v, GEOM_JS))
        self.assertTrue(wait_until(lambda: self.fill_ready(v, g)), "확대한 설비 노드가 그려지지 않음")
        s, ro = g["s"], (NODE_R + RING_OFFSET + 2) * g["s"]
        vx, vy, vw, vh = g["vp"]
        self.assertGreater(s, 1.0, "확대 실패")
        self.assertTrue(vx <= g["cx"] - ro and g["cx"] + ro <= vx + vw and vy <= g["cy"] - ro and g["cy"] + ro <= vy + vh,
                        "고리 영역이 화면 밖: %s" % g)
        before = self.shot(v, kind + "-1before")
        sec0 = self.sectors(before, g)
        self.assertLessEqual(sum(h for h, _t in sec0), 5, "선택 전 고리 자리에 --ui 화소: %s" % sec0)
        lab0 = dark_pixels(before, g["label"])
        self.assertGreater(lab0, 0, "라벨 첫 글자 화소 없음: %s" % g["label"])
        self.assert_hidden(v, "선택 전")

        # 좌표 클릭으로 선택: 노드 중심의 맨 위 요소는 노드(고리는 pointer-events none)
        self.assertEqual(js(v, "document.elementFromPoint(%f,%f).getAttribute('data-local-id')" % (g["cx"], g["cy"])), NODE)
        self.click(v, g["cx"], g["cy"])
        after = self.assert_ring_drawn(v, g, kind + "-2after")
        lab1 = dark_pixels(after, g["label"])
        if self.OUT:
            from PySide6.QtCore import QRect
            d = after.devicePixelRatio() or 1.0
            after.copy(QRect(int((g["cx"] - 40) * d), int((g["cy"] - 40) * d), int(120 * d), int(80 * d))).save(
                os.path.join(self.OUT, "s%s-%s-3label.png" % (self.SCALE.replace(".", ""), kind)))
        self.assertGreaterEqual(lab1, lab0 * 0.9, "라벨 첫 글자가 가려짐: 전 %d, 후 %d / 화면 %s" % (lab0, lab1, self.OUT))
        st = self.assert_visible_at_node(v, "선택 후")
        self.assertTrue(st["node_selected"])
        self.assertEqual(st["width"], "2.5px")
        self.assertEqual(st["events"], "none")
        self.assertEqual(st["node_stroke"], css_rgb(tokens.COLORS["card"]))            # 흰 띠 유지
        self.assertTrue(st["after_nodes"], "고리 층이 노드 층 바로 다음이 아님")
        self.assertTrue(st["before_labels"], "고리 층이 라벨 층 바로 앞이 아님")
        self.assertEqual(st["sym_stroke"], css_rgb(tokens.COLORS["ui"]))               # 도면 선택 표시 그대로
        self.assertEqual(st["sym_width"], "3px")

        # 줌·이동 뒤에도 고리 중심·반경이 노드를 따른다
        js(v, ZOOM_JS.replace("deltaY: -100", "deltaY: 100").replace("i < 8", "i < 2"))
        js(v, "var vp=document.getElementById('viewport');"
              "vp.dispatchEvent(new MouseEvent('mousedown',{button:0,clientX:300,clientY:300,bubbles:true}));"
              "window.dispatchEvent(new MouseEvent('mousemove',{clientX:340,clientY:320}));"
              "window.dispatchEvent(new MouseEvent('mouseup',{})); 1")
        self.assert_visible_at_node(v, "줌·이동 뒤")
        # 배치 전환(placeAll) 뒤에도 노드 좌표와 같다. 되돌린다
        js(v, "document.getElementById('g-layout').click(); 1")
        self.assert_visible_at_node(v, "힘 기반 배치 뒤")
        js(v, "document.getElementById('g-layout').click(); 1")
        self.assert_visible_at_node(v, "도면 좌표 배치로 되돌린 뒤")
        # 범례 필터로 숨기면 감추고, 복원하면 다시 보인다
        filt = ("var k=document.querySelector('%s').getAttribute('data-kind'), cb=document.querySelector("
                "'#glegend [data-gnode=\"'+k+'\"]'); cb.checked=%%s; cb.dispatchEvent(new Event('change',{bubbles:true})); 1"
                % Q_NODE)
        js(v, filt % "false")
        self.assert_hidden(v, "필터 숨김")
        js(v, filt % "true")
        self.assert_visible_at_node(v, "필터 복원")

        # 고리 위 간선 좌표 클릭: 고리가 클릭을 가로채지 않고 간선이 선택된다
        js(v, "document.getElementById('zfit').click(); 1")
        js(v, ZOOM_JS)
        g = json.loads(js(v, GEOM_JS))
        e = g["edge"]
        self.assertIsNotNone(e, "설비 노드에 계장·계측 간선 없음")
        hit = js(v, "(function(){var t=document.elementFromPoint(%f,%f);return t.getAttribute('class')+'|'+"
                    "t.getAttribute('data-local-id');})()" % (e["x"], e["y"]))
        self.assertEqual(hit, "gedge-hit|" + e["lid"])
        self.click(v, e["x"], e["y"])
        self.assertTrue(js(v, "document.querySelector('#graphsvg .gedge-hit[data-local-id=\"%s\"]')"
                              ".nextElementSibling.classList.contains('selected')" % e["lid"]))
        self.assert_hidden(v, "간선 선택")

        # 없는 ID(삭제된 대상) 선택: 예외 없이 선택 해제·고리 숨김. 노드를 다시 고른 뒤 ID를 바꿔 클릭한다
        self.click(v, g["cx"], g["cy"])
        self.assert_visible_at_node(v, "다시 선택")
        js(v, "document.querySelector('%s').setAttribute('data-local-id','gone-id'); 1" % Q_NODE)
        self.click(v, g["cx"], g["cy"])
        js(v, "document.querySelector('#graphsvg [data-local-id=\"gone-id\"]').setAttribute('data-local-id','%s'); 1" % NODE)
        st = self.assert_hidden(v, "없는 ID 선택")
        self.assertFalse(st["node_selected"])
        self.assertEqual(st["errors"], [])
        self.assertEqual(json.loads(js(v, PANEL_JS)), {"empty": True, "links": 0, "h2": False}, "없는 ID: 패널이 빈 상태가 아님")

        # select(undefined) 호출: select()는 IIFE 안의 비공개 함수라 페이지 밖에서 직접 부를 수 없다. 속성 패널 링크의
        # 실제 처리기 `select(a.dataset.goto, true)`가 data-goto 속성이 없을 때 select(undefined, true)를 부르는 것을 이용한다
        # (null과 undefined는 select() 안에서 같은 길: byLocal[id]가 없음). 노드를 고른 뒤 패널 링크의 data-goto를 지우고 누른다.
        self.click(v, g["cx"], g["cy"])
        self.assert_visible_at_node(v, "패널 링크 전 선택")
        before = json.loads(js(v, PANEL_JS))
        self.assertTrue(before["h2"] and before["links"] > 0, before)
        js(v, "var a=document.querySelector('#panel [data-goto]'); a.removeAttribute('data-goto'); a.click(); 1")
        st = self.assert_hidden(v, "select(undefined)")
        self.assertFalse(st["node_selected"])
        self.assertEqual(st["errors"], [])
        self.assertEqual(json.loads(js(v, PANEL_JS)), {"empty": True, "links": 0, "h2": False},
                         "select(undefined): 패널·링크가 빈 상태로 돌아가지 않음")
        # 해제 뒤 다시 선택하면 정상 동작(이전 선택 정리에서 예외 없음)
        self.click(v, g["cx"], g["cy"])
        self.assert_visible_at_node(v, "해제 뒤 다시 선택")
        self.assertTrue(json.loads(js(v, PANEL_JS))["h2"])
        # 상속 속성 이름을 ID로 넘겨도 없는 ID와 같이 해제된다(byLocal은 프로토타입 없는 사전, Codex 최종 재검토)
        for bad in ("toString", "__proto__", "constructor"):
            js(v, "var a=document.querySelector('#panel [data-goto]'); a.setAttribute('data-goto', %s); a.click(); 1"
               % json.dumps(bad))
            st = self.assert_hidden(v, "상속 속성 ID " + bad)
            self.assertEqual(st["errors"], [], bad)
            self.assertEqual(json.loads(js(v, PANEL_JS)), {"empty": True, "links": 0, "h2": False}, bad)
            self.click(v, g["cx"], g["cy"])
            self.assert_visible_at_node(v, "상속 속성 ID 뒤 다시 선택 " + bad)
        return g

    def run_detached(self, v, g):
        """방어 확인: 선택한 노드 요소가 DOM에서 빠진 뒤 고리를 갱신하면 숨긴다(selMark의 isConnected 확인). 파괴적이라 마지막에 한다.

        템플릿에는 그래프 노드를 지우거나 다시 만드는 경로가 없다(노드는 그래프 절에서 한 번 만들고 placeAll은 좌표만 옮긴다,
        evidence w7 §8). 그래서 실제 경로로 재현할 수 없어, 노드를 직접 지운 뒤 selMark()를 부르는 기존 경로 중 하나인
        범례 필터 change 처리(applyFilter)를 일으켜 확인한다. 이 테스트는 실제 결함 재현이 아니라 방어 코드의 회귀 확인이다."""
        self.click(v, g["cx"], g["cy"])
        self.assert_visible_at_node(v, "분리 전")
        js(v, "document.querySelector('%s').remove();"
              "document.querySelector('#glegend input').dispatchEvent(new Event('change',{bubbles:true})); 1" % Q_NODE)
        st = json.loads(js(v, "(function(){var r=document.querySelector('#graphsvg .gsel-ring');return JSON.stringify("
                              "{count:document.querySelectorAll('#graphsvg .gsel-ring').length,hidden:r.classList.contains('hidden'),"
                              "errors:window.__hzErr}); })()"))
        self.assertEqual(st, {"count": 1, "hidden": True, "errors": []})

    def test_standalone_viewer(self):
        from hazop.app import tokens
        v = self.open_standalone()
        g = self.run_common(v, "standalone")
        # 경로 강조(onpath) 중: 노드 테두리는 hl-path, 고리는 그대로
        self.click(v, g["cx"], g["cy"])
        js(v, "document.getElementById('pq-a').value='RC-PZ01';"
              "document.getElementById('pq-b').value='RC-PSV101';"
              "document.getElementById('pq-go').click(); 1")
        self.assertGreater(js(v, "document.querySelectorAll('#graphsvg .onpath.gnode').length"), 0, "경로 없음")
        st = self.assert_visible_at_node(v, "경로 강조")
        self.assertEqual(st["node_stroke"], css_rgb(tokens.COLORS["hl-path"]))
        self.assert_ring_drawn(v, g, "standalone-4onpath")
        self.run_detached(v, g)

    def test_embedded_viewer(self):
        v = self.open_embedded()
        g = self.run_common(v, "embedded")
        # 강조 중 흐림(hz-dim) + 원인: 고리는 흐려지지 않는다
        self.click(v, g["cx"], g["cy"])
        js(v, "document.body.classList.add('hz-dim'); document.querySelector('%s').classList.add('hz-on','hz-cause'); 1"
           % Q_NODE)
        st = self.assert_visible_at_node(v, "흐림·원인")
        self.assertEqual(st["opacity"], "1")
        self.assert_ring_drawn(v, g, "embedded-4dim-cause")
        self.run_detached(v, g)


def _child(out_dir):
    """하위 프로세스: RenderChecks를 TestCase로 묶어 돌린다. 화면은 out_dir에 남긴다."""
    class GraphSelectRender(RenderChecks, unittest.TestCase):
        OUT = out_dir
        SCALE = os.environ.get("QT_SCALE_FACTOR", "1")
    os.makedirs(out_dir, exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GraphSelectRender))
    return 0 if result.wasSuccessful() else 1


class GraphSelectRenderTest(unittest.TestCase):
    """렌더 검사를 별도 프로세스로 돌린다(플랫폼 offscreen, 배율 1·1.25 명시)."""

    def test_render_subprocess(self):
        for scale in SCALES:
            with self.subTest(scale=scale):
                out = tempfile.mkdtemp(prefix="hz-gsel-shots-")
                env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=scale, PYTHONIOENCODING="utf-8",
                           QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --disable-gpu-compositing --log-level=3")
                p = subprocess.run([sys.executable, "-m", "tests.test_graph_select", "--child", out], cwd=REPO_ROOT,
                                   env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                if p.returncode == 0:
                    shutil.rmtree(out, ignore_errors=True)
                self.assertEqual(p.returncode, 0, "렌더 검사 실패(배율 %s). 화면: %s\n%s" % (scale, out, p.stderr[-4000:]))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        sys.exit(_child(sys.argv[2]))
    unittest.main()
