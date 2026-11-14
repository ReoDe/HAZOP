"""뷰어 API 검사 (docs/specs/chat-panel.md §6, S-viewer). 실행: python -m unittest tests.test_viewer_api

세 층으로 나눈다. 모두 오프스크린이고 네트워크를 쓰지 않으며, 실제 창을 키보드·마우스로 움직이지 않는다
(마우스 조작은 페이지 안에서 MouseEvent를 보내 흉내 낸다).
1. 메시지: 각 API 호출이 맞는 형식의 웹 메시지를 보내는지, 웹 메시지가 Bridge 신호로 올라오는지(페이지 없이).
2. 페이지: 도면 모양을 흉내 낸 작은 HTML에서 표시·경로·고르기 동작. 큰 도면(수천 개) 시간 재기.
3. 실제 뷰어: SNP-M-102 뷰어 HTML에서 기존 강조(highlight·구간 색·pick)와 같이 있어도 서로 지우지 않는지.
"""

import json
import os
import shutil
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from tests.test_app import wait_for  # noqa: E402

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0} #viewport{position:absolute;left:0;top:0;width:800px;height:600px;overflow:hidden}
.sym{fill:#ddd;stroke:#333} .tagbox{fill:none;stroke:#333} .pipe-line{fill:none;stroke:#333;stroke-width:2.5}
.pipe-hit{fill:none;stroke:transparent;stroke-width:12}
</style></head><body><div id="viewport"><svg id="overlay" width="800" height="600"><g id="stage">%(body)s</g></svg></div>
<script>
var view = {s: 1, x: 0, y: 0};
function apply() { document.getElementById("stage").setAttribute("transform", "translate(" + view.x + "," + view.y + ") scale(" + view.s + ")"); }
window.hzView = {get: function () { return {s: view.s, x: view.x, y: view.y}; },
  set: function (v) { view.s = v.s; view.x = v.x; view.y = v.y; apply(); }};
window.__panned = 0; window.__clicked = 0;
document.getElementById("viewport").addEventListener("mousedown", function () { window.__panned++; });
document.getElementById("overlay").addEventListener("click", function () { window.__clicked++; });
function ev(t, type, x, y, alt) { t.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, altKey: !!alt, view: window})); }
window.drag = function (x0, y0, x1, y1, alt) {
  var t0 = performance.now();
  ev(document.elementFromPoint(x0, y0) || document.body, "mousedown", x0, y0, alt);
  ev(document.body, "mousemove", x1, y1, alt);
  ev(document.body, "mouseup", x1, y1, alt);
  return performance.now() - t0;
};
window.clickAt = function (x, y) {
  var t0 = performance.now(), t = document.elementFromPoint(x, y) || document.body;
  ev(t, "mousedown", x, y); ev(t, "mouseup", x, y); ev(t, "click", x, y);
  return performance.now() - t0;
};
window.classesOf = function (id) {
  return JSON.stringify(Array.prototype.map.call(document.querySelectorAll('#overlay [data-local-id="' + id + '"]'), function (e) {
    if (e.classList.contains("pipe-hit")) e = e.nextElementSibling;   // 배관은 보이는 선(pipe-line)의 클래스
    return e.getAttribute("class"); }));
};
</script></body></html>"""

SMALL = """
<rect class="sym" data-local-id="a1" x="100" y="100" width="40" height="40"/>
<rect class="tagbox" data-local-id="a1" x="100" y="145" width="40" height="10"/>
<rect class="sym" data-local-id="a2" x="200" y="100" width="40" height="40"/>
<rect class="sym" data-local-id="a3" x="400" y="400" width="40" height="40"/>
<path class="pipe-hit" data-local-id="p1" d="M140,120 H200"/><path class="pipe-line" d="M140,120 H200"/>
<path class="pipe-hit" data-local-id="p2" d="M240,120 H700"/><path class="pipe-line" d="M240,120 H700"/>
<path class="pipe-hit" data-local-id="p3" d="M240,140 V400 H400"/><path class="pipe-line" d="M240,140 V400 H400"/>
"""


def big_body(n_sym, n_pipe):
    """수천 개짜리 큰 도면 모양: 기호 n_sym개를 격자에, 이웃 기호 사이 배관 n_pipe개."""
    parts = []
    for i in range(n_sym):
        x, y = 4 + (i % 100) * 7.5, 4 + (i // 100) * 7.5
        parts.append('<rect class="sym" data-local-id="s%d" x="%.1f" y="%.1f" width="5" height="5"/>' % (i, x, y))
    for j in range(n_pipe):
        x, y = 4 + (j % 100) * 7.5 + 5, 4 + (j // 100) * 7.5 + 2.5
        d = "M%.1f,%.1f h2.5" % (x, y)
        parts.append('<path class="pipe-hit" data-local-id="p%d" d="%s"/><path class="pipe-line" d="%s"/>' % (j, d, d))
    return "".join(parts)


def js(view, code, timeout=30.0):
    out = []
    view.page().runJavaScript(code, 0, out.append)
    if not wait_for(lambda: bool(out), timeout):
        raise AssertionError("JS 결과 없음: %s" % code[:80])
    return out[0]


class Recorder:
    """bridge.toWeb으로 나가는 메시지를 모은다(페이지 없이 형식만 볼 때)."""

    def __init__(self, view):
        view.bridge.is_ready = True
        self.msgs = []
        view.bridge.toWeb.connect(lambda t: self.msgs.append(json.loads(t)))

    def last(self):
        return self.msgs[-1]


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hazop.app import make_application
        cls.qapp = make_application(["test"])
        cls.tmp = tempfile.mkdtemp(prefix="hazop-viewer-api-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def new_view(self):
        from hazop.app.webview import HazopWebView
        v = HazopWebView()
        v.resize(900, 700)
        self.addCleanup(v.dispose)
        return v

    def load(self, view, body, graph_id="G1"):
        path = os.path.join(self.tmp, "p%d.html" % int(time.monotonic() * 1e6))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(PAGE % {"body": body})
        ready = []
        view.bridge.sheetReady.connect(ready.append)
        view.load_file(path, graph_id=graph_id)
        view.show()
        self.assertTrue(wait_for(lambda: bool(ready)), "도면 읽기 신호(sheetReady) 없음")
        self.assertEqual(ready[0], graph_id)

    def wait_marks(self, view, n, cond="document.querySelectorAll('.hz-m').length"):
        self.assertTrue(wait_for(lambda: js(view, cond) == n), "표시 수가 %d가 되지 않음" % n)


class MessageTest(QtCase):
    def test_each_call_sends_matching_message(self):
        v = self.new_view()
        r = Recorder(v)
        groups = [{"ids": ["a", "b"], "style": "path", "label": "원인"}, {"ids": ["c"], "style": "seg:3"}]
        v.mark("r1", groups, dim_others=False, center=True)
        self.assertEqual(r.last(), {"type": "mark", "request_id": "r1", "dim_others": False, "center": True,
                                    "groups": [{"ids": ["a", "b"], "style": "path", "label": "원인"},
                                               {"ids": ["c"], "style": "seg:3", "label": None}]})
        v.clear_marks("r1")
        self.assertEqual(r.last(), {"type": "clearMarks", "request_id": "r1"})
        v.clear_marks()
        self.assertEqual(r.last(), {"type": "clearMarks", "request_id": None})
        v.draw_path("r2", [{"id": "a", "flow": None}, {"id": "p", "flow": "with"}, {"bad": 1}], style="warn", numbered=False)
        self.assertEqual(r.last(), {"type": "drawPath", "request_id": "r2", "style": "warn", "numbered": False,
                                    "steps": [{"id": "a", "flow": None}, {"id": "p", "flow": "with"}]})
        v.set_select_mode("pick")
        self.assertEqual(r.last(), {"type": "selectMode", "mode": "pick"})
        v.set_select_mode("nonsense")
        self.assertEqual(r.last(), {"type": "selectMode", "mode": "off"})
        v.set_selection(["a", 3, "b"])
        self.assertEqual(r.last(), {"type": "setSelection", "ids": ["a", "b"]})
        v.zoom_to(["a"], pad=0.3)
        self.assertEqual(r.last(), {"type": "zoomTo", "ids": ["a"], "pad": 0.3})

    def test_selection_request_and_answer(self):
        v = self.new_view()
        got = []
        v.selection(got.append)            # 페이지 준비 전: 빈 목록
        self.assertEqual(got, [[]])
        r = Recorder(v)
        v.selection(got.append)
        req = r.last()
        self.assertEqual(req["type"], "getSelection")
        v.bridge.fromWeb(json.dumps({"type": "selection", "request_id": req["request_id"], "selected": ["x", "y", 5]}))
        self.assertEqual(got[1], ["x", "y"])

    def test_select_mode_survives_reload(self):
        v = self.new_view()
        v.set_select_mode("pick")
        self.load(v, SMALL)
        self.assertEqual(js(v, "document.body.classList.contains('hz-selmode')"), True)

    def test_bridge_signals_from_web(self):
        from hazop.app.webview import Bridge
        b = Bridge()
        events, sel_for, sheets = [], [], []
        b.selectionChanged.connect(events.append)
        b.selectionFor.connect(lambda rid, ids: sel_for.append((rid, ids)))
        b.sheetReady.connect(sheets.append)
        b.graph_id = "G9"
        b.fromWeb(json.dumps({"type": "ready"}))
        self.assertEqual(sheets, ["G9"])
        b.fromWeb(json.dumps({"type": "selectionChanged", "selected": ["a", "b\x01", "c"], "added": ["c"], "removed": [],
                              "via": "box"}))
        self.assertEqual(events[0], {"selected": ["a", "c"], "added": ["c"], "removed": [], "via": "box", "truncated": False})
        b.fromWeb(json.dumps({"type": "selectionChanged", "selected": ["a"], "added": [], "removed": [], "via": "weird"}))
        self.assertEqual(events[1]["via"], "click")
        b.fromWeb(json.dumps({"type": "selectionChanged", "selected": ["a"], "truncated": True}))
        self.assertTrue(events[2]["truncated"])
        many = ["i%d" % i for i in range(2500)]
        b.fromWeb(json.dumps({"type": "selectionChanged", "selected": many, "via": "box"}))
        self.assertEqual(len(events[3]["selected"]), 2000)
        self.assertTrue(events[3]["truncated"])
        b.fromWeb(json.dumps({"type": "selectionChanged", "selected": "no"}))
        self.assertEqual(events[4]["selected"], [])
        b.fromWeb(json.dumps({"type": "selection", "request_id": "q", "selected": ["z"]}))
        self.assertEqual(sel_for, [("q", ["z"])])
        # highlightResult는 기존과 같이 두 신호로 올라온다
        res = []
        b.highlightResultFor.connect(lambda rid, miss: res.append((rid, miss)))
        b.fromWeb(json.dumps({"type": "highlightResult", "request_id": "m1", "missing": ["q", 3]}))
        self.assertEqual(res, [("m1", ["q"])])


class PageTest(QtCase):
    def setUp(self):
        self.v = self.new_view()
        self.load(self.v, SMALL)
        self.results, self.events, self.nodes = [], [], []
        self.v.bridge.highlightResultFor.connect(lambda rid, miss: self.results.append((rid, miss)))
        self.v.bridge.selectionChanged.connect(self.events.append)
        self.v.bridge.nodeSelected.connect(self.nodes.append)

    def classes(self, lid):
        return json.loads(js(self.v, "classesOf(%s)" % json.dumps(lid)))

    def test_mark_styles_missing_and_clear(self):
        self.v.mark("r1", [{"ids": ["a1", "p1", "nope"], "style": "cause", "label": "원인"}, {"ids": ["a2"], "style": "seg:7"}])
        self.assertTrue(wait_for(lambda: bool(self.results)))
        self.assertEqual(self.results[0], ("r1", ["nope"]))
        self.assertTrue(all("hz-m-cause" in c for c in self.classes("a1")))     # 기호·태그 상자 모두
        self.assertTrue(any("hz-m-cause" in c for c in self.classes("p1")))      # 배관은 선(pipe-line)에 칠한다
        self.assertTrue(any("hz-m-seg3" in c for c in self.classes("a2")))       # seg:7 → 5색 순환(7 % 5 + 1)
        self.assertEqual(js(self.v, "document.body.classList.contains('hz-mdim')"), True)
        self.assertEqual(js(self.v, "document.querySelectorAll('.hz-mbadge').length"), 1)   # 이름표
        self.assertEqual(js(self.v, "document.querySelector('.pipe-hit').getAttribute('class')"), "pipe-hit")
        self.v.clear_marks("r1")
        self.wait_marks(self.v, 0)
        self.assertEqual(js(self.v, "document.body.classList.contains('hz-mdim')"), False)
        self.assertEqual(js(self.v, "document.querySelectorAll('.hz-mbadge').length"), 0)

    def test_two_requests_clear_independently_and_same_id_replaces(self):
        self.v.mark("r1", [{"ids": ["a1"], "style": "focus"}], dim_others=False)
        self.v.mark("r2", [{"ids": ["a1", "a2"], "style": "warn"}])
        self.wait_marks(self.v, 3)                 # a1 기호·태그 상자, a2 기호
        self.v.clear_marks("r2")
        self.wait_marks(self.v, 2)
        self.assertTrue(all("hz-m-focus" in c for c in self.classes("a1")))   # r1 표시는 남는다
        self.assertEqual(js(self.v, "document.body.classList.contains('hz-mdim')"), False)
        self.v.mark("r1", [{"ids": ["a3"], "style": "focus"}])                  # 같은 id는 덮어쓴다
        self.wait_marks(self.v, 1)
        self.v.clear_marks()
        self.wait_marks(self.v, 0)

    def test_draw_path_badges_arrows_and_dashes(self):
        self.v.draw_path("path1", [{"id": "a1", "flow": None}, {"id": "p1", "flow": "with"}, {"id": "a2", "flow": None},
                                   {"id": "p2", "flow": "unknown"}, {"id": "gone", "flow": None}])
        self.assertTrue(wait_for(lambda: bool(self.results)))
        self.assertEqual(self.results[0], ("path1", ["gone"]))
        self.assertEqual(js(self.v, "document.querySelectorAll('.hz-mbadge text').length"), 2)
        self.assertEqual(js(self.v, "Array.prototype.map.call(document.querySelectorAll('.hz-mbadge text'), function (t) { return t.textContent; }).join()"), "1,2")
        self.assertEqual(js(self.v, "document.querySelectorAll('.hz-marrow').length"), 1)       # 흐름이 확인된 배관만
        self.assertEqual(js(self.v, "document.querySelectorAll('.pipe-line.hz-m-dash').length"), 1)  # unknown은 점선
        # 앞 단계(a1)가 왼쪽에 있으므로 화살표는 오른쪽(0도)을 본다. against이면 반대
        ang = "document.querySelector('.hz-marrow').getAttribute('transform')"
        self.assertIn("rotate(0)", js(self.v, ang))
        self.v.draw_path("path1", [{"id": "a1", "flow": None}, {"id": "p1", "flow": "against"}, {"id": "a2", "flow": None}])
        self.assertTrue(wait_for(lambda: "rotate(180)" in js(self.v, "(document.querySelector('.hz-marrow') || {getAttribute: function () { return ''; }}).getAttribute('transform')")))
        self.assertEqual(js(self.v, "document.querySelectorAll('.hz-marrow').length"), 1)       # 덮어써도 쌓이지 않는다

    def test_zoom_to_and_center(self):
        self.v.zoom_to(["a3"], pad=0.5)
        self.assertTrue(wait_for(lambda: js(self.v, "window.hzView.get().s") > 1.5))
        # a3(400~440, 400~440)가 가운데 근처로 온다
        c = json.loads(js(self.v, "(function () { var r = document.querySelector('[data-local-id=a3]').getBoundingClientRect(); return JSON.stringify([r.left + r.width / 2, r.top + r.height / 2]); })()"))
        self.assertAlmostEqual(c[0], 400, delta=2)
        self.assertAlmostEqual(c[1], 300, delta=2)
        js(self.v, "window.hzView.set({s: 1, x: 0, y: 0})")
        self.v.mark("c1", [{"ids": ["a1"], "style": "focus"}], center=True)
        self.assertTrue(wait_for(lambda: js(self.v, "window.hzView.get().s") > 1.5))

    def test_select_off_keeps_existing_behaviour(self):
        js(self.v, "drag(80, 80, 260, 200)")
        js(self.v, "clickAt(120, 120)")
        self.assertTrue(wait_for(lambda: bool(self.nodes)))       # 기존 클릭 동작(nodeSelected)
        self.assertEqual(js(self.v, "window.__panned"), 2)         # 템플릿의 끌기가 그대로 불린다
        self.assertEqual(js(self.v, "window.__clicked"), 1)
        self.assertEqual(self.events, [])
        self.assertEqual(js(self.v, "document.querySelectorAll('.hz-sel, .hz-rubber').length"), 0)

    def test_box_click_add_remove(self):
        self.v.set_select_mode("pick")
        self.assertTrue(wait_for(lambda: js(self.v, "document.body.classList.contains('hz-selmode')")))
        js(self.v, "drag(80, 80, 260, 200)")                      # 네모 안: a1(기호+태그 상자)·a2·p1(전부 안)
        self.assertTrue(wait_for(lambda: len(self.events) == 1))
        e = self.events[0]
        self.assertEqual((e["via"], sorted(e["selected"]), sorted(e["added"]), e["removed"]), ("box", ["a1", "a2", "p1"], ["a1", "a2", "p1"], []))
        # p2는 선의 일부(240~260)만 안이라 고르지 않는다
        self.assertEqual(js(self.v, "document.querySelectorAll('.hz-sel').length"), 4)
        js(self.v, "clickAt(420, 420)")                           # 하나 더하기
        self.assertTrue(wait_for(lambda: len(self.events) == 2))
        self.assertEqual((self.events[1]["via"], self.events[1]["added"]), ("click", ["a3"]))
        js(self.v, "clickAt(120, 120)")                           # 고른 것을 다시 누르면 빠진다
        self.assertTrue(wait_for(lambda: len(self.events) == 3))
        self.assertEqual((self.events[2]["removed"], sorted(self.events[2]["selected"])), (["a1"], ["a2", "a3", "p1"]))
        js(self.v, "drag(80, 80, 260, 200, true)")                # Alt+끌기: 네모 안 것을 뺀다
        self.assertTrue(wait_for(lambda: len(self.events) == 4))
        self.assertEqual((self.events[3]["via"], sorted(self.events[3]["removed"]), self.events[3]["selected"]), ("box_remove", ["a2", "p1"], ["a3"]))
        js(self.v, "drag(0, 0, 40, 40)")                          # 아무것도 없는 곳: 이벤트 없음
        js(self.v, "clickAt(700, 500)")
        self.assertEqual(js(self.v, "window.__panned"), 0)         # 고르기 중에는 화면 끌기가 시작되지 않는다
        self.assertEqual(js(self.v, "window.__clicked"), 0)        # 템플릿 클릭 선택도 새지 않는다
        self.assertEqual(self.nodes, [])
        self.assertEqual(len(self.events), 4)
        got = []
        self.v.selection(got.append)
        self.assertTrue(wait_for(lambda: bool(got)))
        self.assertEqual(got[0], ["a3"])

    def test_long_ids_never_exceed_message_limit(self):
        """ID가 길어 2,000개가 64KB를 넘어도 메시지가 버려지지 않고, 웹 쪽에서 잘라 truncated를 단다."""
        from hazop.app.webview import MAX_MESSAGE_CHARS
        v = self.new_view()
        body = "".join('<rect class="sym" data-local-id="%s" x="%d" y="%d" width="4" height="4"/>' % ("L" * 150 + str(i), 4 + (i % 100) * 7, 4 + (i // 100) * 7)
                       for i in range(1000))
        self.load(v, body)
        events, raw = [], []
        v.bridge.selectionChanged.connect(events.append)
        orig = v.bridge.fromWeb
        v.set_select_mode("pick")
        self.assertTrue(wait_for(lambda: js(v, "document.body.classList.contains('hz-selmode')")))
        js(v, "drag(0, 0, 800, 600)")
        self.assertTrue(wait_for(lambda: bool(events)), "메시지가 버려짐")
        self.assertTrue(events[0]["truncated"])
        self.assertTrue(0 < len(events[0]["selected"]) < 1000)
        self.assertLess(sum(len(i) + 4 for i in events[0]["selected"]), MAX_MESSAGE_CHARS)
        del orig, raw

    def test_selection_answer_is_capped_and_waiter_cleared(self):
        """ID 40자 1,800개: 응답이 64KB를 넘어 버려지면 안 된다. 잘라서 오고 대기 항목이 남지 않는다."""
        ids = ["%040d" % i for i in range(1800)]
        self.v.set_selection(ids)
        got = []
        self.v.selection(got.append)
        self.assertTrue(wait_for(lambda: bool(got)), "selection 응답이 버려짐")
        self.assertTrue(0 < len(got[0]) <= 2000)
        self.assertLess(sum(len(i) + 4 for i in got[0]), 64 * 1024)
        self.assertTrue(self.v.selection_truncated)
        self.assertEqual(self.v._selection_waiters, {})
        self.v.set_selection(["a1"])
        got2 = []
        self.v.selection(got2.append)
        self.assertTrue(wait_for(lambda: bool(got2)))
        self.assertEqual(got2[0], ["a1"])
        self.assertFalse(self.v.selection_truncated)

    def test_selection_waiter_times_out(self):
        got = []
        self.v.SELECTION_TIMEOUT_MS = 100
        self.v.bridge.toWeb.disconnect()          # 웹이 답하지 못하는 상황
        self.v.selection(got.append)
        self.assertTrue(wait_for(lambda: bool(got), 5.0))
        self.assertEqual(got[0], [])
        self.assertEqual(self.v._selection_waiters, {})

    def test_mark_missing_list_is_capped(self):
        miss = ["%040d" % i for i in range(1800)]
        self.v.mark("big-miss", [{"ids": miss, "style": "focus"}])
        self.assertTrue(wait_for(lambda: bool(self.results)), "highlightResult가 버려짐")
        self.assertEqual(self.results[0][0], "big-miss")
        self.assertTrue(0 < len(self.results[0][1]) <= 2000)

    def test_pick_outline_wins_over_mark(self):
        self.v.mark("r1", [{"ids": ["a1"], "style": "cause"}])
        self.v.pick("a1")
        self.wait_marks(self.v, 2)
        self.assertTrue(wait_for(lambda: js(self.v, "document.querySelector('.sym.hz-pick') !== null")))
        stroke = js(self.v, "getComputedStyle(document.querySelector('.sym.hz-pick')).stroke")
        self.assertEqual(stroke.replace(" ", ""), "rgb(10,95,194)")

    def test_chips_stay_clickable_in_pick_mode(self):
        chips = []
        self.v.bridge.chipClicked.connect(chips.append)
        self.v.set_chips([{"local_id": "a2", "text": "S1 → 다음 도면", "key": "k1", "kind": "link"}])
        self.assertTrue(wait_for(lambda: js(self.v, "document.querySelectorAll('.hz-chip').length") == 1))
        self.v.set_select_mode("pick")
        self.assertTrue(wait_for(lambda: js(self.v, "document.body.classList.contains('hz-selmode')")))
        js(self.v, "(function () { var r = document.querySelector('.hz-chip rect').getBoundingClientRect(); clickAt(r.left + r.width / 2, r.top + r.height / 2); })()")
        self.assertTrue(wait_for(lambda: chips == ["k1"]))
        self.assertEqual(self.events, [])

    def test_set_selection_is_silent_and_escape_clears(self):
        self.v.set_select_mode("pick")
        self.v.set_selection(["a1", "a2", "ghost"])
        self.assertTrue(wait_for(lambda: js(self.v, "document.querySelectorAll('.hz-sel').length") == 3))
        self.assertEqual(self.events, [])
        js(self.v, "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
        self.assertTrue(wait_for(lambda: len(self.events) == 1))
        self.assertEqual((self.events[0]["via"], sorted(self.events[0]["removed"]), self.events[0]["selected"]),
                         ("clear", ["a1", "a2", "ghost"], []))
        self.assertEqual(js(self.v, "document.querySelectorAll('.hz-sel').length"), 0)

    def test_selection_and_marks_do_not_erase_each_other(self):
        self.v.mark("r1", [{"ids": ["a1"], "style": "path"}])
        self.v.set_selection(["a1"])
        self.wait_marks(self.v, 2)
        self.assertTrue(wait_for(lambda: js(self.v, "document.querySelectorAll('.hz-sel').length") == 2))
        self.v.clear_marks()
        self.wait_marks(self.v, 0)
        self.assertEqual(js(self.v, "document.querySelectorAll('.hz-sel').length"), 2)
        self.v.set_selection([])
        self.assertTrue(wait_for(lambda: js(self.v, "document.querySelectorAll('.hz-sel').length") == 0))


class BigSheetTest(QtCase):
    """APR1400 쪽 크기(구성요소 수천 개)에서 강조와 네모 고르기 시간. 값은 출력으로 남기고, 상한은 느슨하게 둔다."""
    N_SYM, N_PIPE = 3000, 2800

    def test_large_sheet_timings(self):
        v = self.new_view()
        self.load(v, big_body(self.N_SYM, self.N_PIPE))
        ids = ["s%d" % i for i in range(self.N_SYM)] + ["p%d" % i for i in range(self.N_PIPE)]
        res, events = [], []
        v.bridge.highlightResultFor.connect(lambda rid, miss: res.append(rid))
        v.bridge.selectionChanged.connect(events.append)
        t0 = time.perf_counter()
        v.mark("big", [{"ids": ids, "style": "path", "label": "전체"}])
        self.assertTrue(wait_for(lambda: "big" in res))
        t_mark = time.perf_counter() - t0
        self.assertEqual(js(v, "document.querySelectorAll('.hz-m').length"), self.N_SYM + self.N_PIPE)
        t0 = time.perf_counter()
        v.clear_marks("big")
        self.wait_marks(v, 0)
        t_clear = time.perf_counter() - t0
        t0 = time.perf_counter()
        v.draw_path("bigpath", [{"id": i, "flow": "with" if i.startswith("p") else None} for i in ids])
        self.assertTrue(wait_for(lambda: "bigpath" in res))
        t_path = time.perf_counter() - t0
        v.clear_marks()
        self.wait_marks(v, 0)
        v.set_select_mode("pick")
        self.assertTrue(wait_for(lambda: js(v, "document.body.classList.contains('hz-selmode')")))
        t_box = js(v, "drag(0, 0, 800, 600)")         # 전체를 덮는 네모: 페이지 안 처리 시간(ms)
        self.assertTrue(wait_for(lambda: bool(events)))
        self.assertEqual(len(events[0]["selected"]), 2000)                # 앱 쪽은 2,000개까지만 받는다
        self.assertTrue(events[0]["truncated"])
        self.assertEqual(js(v, "document.querySelectorAll('.hz-sel').length"), self.N_SYM + self.N_PIPE)
        t_click = js(v, "clickAt(6, 6)")                # 전부 고른 뒤 기호 하나 누르기(빼기)
        self.assertTrue(wait_for(lambda: len(events) == 2))
        events.clear()
        t_box_remove = js(v, "drag(0, 0, 800, 600, true)")
        self.assertTrue(wait_for(lambda: len(events) == 1))
        self.assertEqual(js(v, "document.querySelectorAll('.hz-sel').length"), 0)
        print("\n[큰 도면 %d개 | 오프스크린 QtWebEngine, 800x600] mark+라벨 %.0fms · clear_marks %.0fms · draw_path(화살표 %d개) %.0fms · "
              "전체 네모 고르기 %.0fms · 하나 누르기 %.0fms · 전체 네모 빼기 %.0fms" % (
                  self.N_SYM + self.N_PIPE, t_mark * 1e3, t_clear * 1e3, self.N_PIPE, t_path * 1e3, t_box, t_click, t_box_remove))
        for name, t in (("mark", t_mark * 1e3), ("clear", t_clear * 1e3), ("path", t_path * 1e3), ("box", t_box), ("click", t_click), ("box_remove", t_box_remove)):
            self.assertLess(t, 3000, "%s가 3초를 넘음" % name)


class HostTest(QtCase):
    def make(self):
        v = self.new_view()
        rec = Recorder(v)
        v.current_graph_id = "G1"
        switched = []

        def switch(name):
            switched.append(name)
            v.bridge.is_ready = False
            v.current_graph_id = {"D2": "G2", "D1": "G1"}[name]

        from hazop.app.screens.viewer import ViewerHost
        host = ViewerHost(v, lambda: {"G1": "D1", "G2": "D2"}, switch)

        def finish():  # 화면이 도면을 다 읽었다
            v.bridge.is_ready = True
            v.bridge.sheetReady.emit(v.current_graph_id)
        return v, rec, host, switched, finish

    def test_show_sheet_same_and_other(self):
        v, rec, host, switched, finish = self.make()
        calls = []
        self.assertTrue(host.show_sheet("G1", lambda: calls.append("same")))
        self.assertEqual((calls, switched), (["same"], []))
        self.assertTrue(host.show_sheet("G2", lambda: calls.append("then")))
        self.assertEqual((calls, switched), (["same"], ["D2"]))      # 아직 읽는 중: then은 기다린다
        finish()
        self.assertEqual(calls, ["same", "then"])
        self.assertFalse(host.show_sheet("G404", lambda: calls.append("never")))   # 모르는 도면
        self.assertEqual(calls, ["same", "then"])

    def test_marks_follow_the_sheet(self):
        v, rec, host, switched, finish = self.make()
        m1 = {"op": "mark", "groups": [{"ids": ["a"], "style": "path"}]}
        m2 = {"op": "mark", "groups": [{"ids": ["b"], "style": "warn"}], "center": True}
        p2 = {"op": "path", "steps": [{"id": "b", "flow": None}], "style": "path"}
        host.show_marks("r1", {"G1": [m1], "G2": [m2, p2]})
        self.assertEqual([(m["type"], m["request_id"]) for m in rec.msgs], [("clearMarks", "r1"), ("mark", "r1")])
        self.assertEqual(rec.last()["groups"][0]["ids"], ["a"])
        n = len(rec.msgs)
        host.show_sheet("G2")
        finish()                                                     # 도면을 옮기면 맡긴 것을 그 도면에 다시 그린다
        got = [(m["type"], m["request_id"]) for m in rec.msgs[n:]]
        self.assertEqual(got, [("mark", "r1"), ("drawPath", "r1#1")])
        self.assertTrue(rec.msgs[n]["center"])
        n = len(rec.msgs)
        host.clear("r1")                                             # 둘 다 지운다
        self.assertEqual([(m["type"], m["request_id"]) for m in rec.msgs[n:]], [("clearMarks", "r1"), ("clearMarks", "r1#1")])
        n = len(rec.msgs)
        host.show_sheet("G1")
        finish()
        self.assertEqual([m["type"] for m in rec.msgs[n:]], [])      # 지운 뒤에는 다시 그리지 않는다

    def test_show_marks_with_sheet_switches_first(self):
        v, rec, host, switched, finish = self.make()
        host.show_marks("r2", {"G2": [{"op": "mark", "groups": [{"ids": ["z"], "style": "focus"}]}]}, sheet="G2")
        self.assertEqual(switched, ["D2"])
        self.assertNotIn("mark", [m["type"] for m in rec.msgs])
        finish()
        self.assertEqual(rec.last()["type"], "mark")


class SameFileTest(QtCase):
    def test_graph_id_given_after_plain_load_of_same_file(self):
        """④가 graph_id 없이 읽은 파일을 ②가 graph_id와 함께 다시 읽어도 graph_id가 남고 ViewerHost가 동작한다."""
        from hazop.app.screens.viewer import ViewerHost
        v = self.new_view()
        path = os.path.join(self.tmp, "same.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(PAGE % {"body": SMALL})
        ready = []
        v.bridge.sheetReady.connect(ready.append)
        v.load_file(path)
        v.show()
        self.assertTrue(wait_for(lambda: bool(ready)))
        self.assertEqual(ready, [""])
        self.assertFalse(v.load_file(path, graph_id="G1"))          # 다시 읽지는 않는다
        self.assertEqual(v.current_graph_id, "G1")
        self.assertEqual(v.bridge.graph_id, "G1")
        self.assertEqual(ready, ["", "G1"])                         # 알아낸 graph_id를 알린다
        self.assertFalse(v.load_file(path))                         # graph_id 없이 다시 불러도 지우지 않는다
        self.assertEqual(v.current_graph_id, "G1")
        host = ViewerHost(v, lambda: {"G1": "D1"}, lambda name: v.load_file(path, graph_id="G1"))
        called = []
        self.assertTrue(host.show_sheet("G1", lambda: called.append(1)))
        self.assertEqual(called, [1])
        host.show_marks("q", {"G1": [{"op": "mark", "groups": [{"ids": ["a1"], "style": "focus"}]}]})
        self.assertTrue(wait_for(lambda: js(v, "document.querySelectorAll('.hz-m').length") == 2))


class RealViewerTest(QtCase):
    """실제 뷰어 HTML(SNP-M-102): 기존 강조·구간 색·고른 것과 같이 있어도 서로 지우지 않는다."""

    def test_coexists_with_existing_highlights(self):
        from tests.test_graph_select import build_viewer_html
        v = self.new_view()
        path = build_viewer_html(self.tmp)
        ready = []
        v.bridge.sheetReady.connect(ready.append)
        v.load_file(path, graph_id="G102")
        v.show()
        self.assertTrue(wait_for(lambda: bool(ready)))
        self.assertEqual(ready[0], "G102")
        ids = json.loads(js(v, "JSON.stringify(Array.prototype.map.call(document.querySelectorAll('#overlay .sym[data-local-id]'), function (e) { return e.getAttribute('data-local-id'); }))"))
        self.assertGreaterEqual(len(ids), 3)
        a, b, c = ids[0], ids[1], ids[2]
        count = lambda sel: js(v, "document.querySelectorAll(%s).length" % json.dumps(sel))  # noqa: E731
        v.highlight({"request_id": "h1", "path": [a], "cause": [b], "estimated": [], "safeguards": []})
        v.set_segments([{"color": "var(--seg1)", "active": False, "label": "S1", "ids": [a, b, c]}])
        v.pick(c)
        v.mark("m1", [{"ids": [a, c], "style": "focus"}])
        self.assertTrue(wait_for(lambda: count(".hz-m") >= 2))
        self.assertGreaterEqual(count(".hz-on"), 2)
        self.assertGreaterEqual(count("[data-hz-seg]"), 3)
        self.assertGreaterEqual(count(".hz-pick"), 1)
        v.clear_highlight()                                          # 기존 강조를 지워도 표시는 남는다
        self.assertTrue(wait_for(lambda: count(".hz-on") == 0))
        self.assertGreaterEqual(count(".hz-m"), 2)
        v.clear_segments()
        v.pick(None)
        self.assertTrue(wait_for(lambda: count("[data-hz-seg]") == 0 and count(".hz-pick") == 0))
        self.assertGreaterEqual(count(".hz-m"), 2)
        v.highlight({"request_id": "h2", "path": [a], "cause": [], "estimated": [], "safeguards": []})
        v.set_selection([b])
        self.assertTrue(wait_for(lambda: count(".hz-sel") >= 1))
        v.clear_marks()                                              # 표시를 지워도 기존 강조·고른 것은 남는다
        self.assertTrue(wait_for(lambda: count(".hz-m") == 0))
        self.assertGreaterEqual(count(".hz-on"), 1)
        self.assertGreaterEqual(count(".hz-sel"), 1)
        self.assertEqual(js(v, "document.body.classList.contains('hz-dim')"), True)   # 기존 흐림은 기존 강조 몫


if __name__ == "__main__":
    unittest.main()
