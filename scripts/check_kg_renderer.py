"""지식그래프 렌더러(force-graph) 오프라인 확인 (기획서/그래프활용.md §5.2, §7.2 V2 일부, §8.1 WP0). 네트워크·AI 호출 없음.

1) vendor 무결성(V2 일부): hazop/kg/vendor/force-graph-1.52.0의 SHA-256이 SOURCE.md 기록값과 같고 LICENSE가 있음
2) 외부 URL 규칙(V2 일부, 오프라인 판정의 1차 근거): 생성 HTML에서 vendor 본문을 뺀 나머지에 GENERATED_URL_RE
   (http·https·ws·wss·ftp 주소, 따옴표·괄호·= 뒤의 //host)가 하나도 없어야 하고, vendor 본문의 http(s) URL은
   VENDOR_URL_ALLOWLIST(반입 시 확인한 XML 이름공간·명세 문자열과 저장소 주소)에 든 것만 허용
3) 렌더링: hazop/app/webview.py의 HazopWebView(요청 가로채기·탐색 제한·원격 접근 끔)로 임시 폴더의 HTML을 열어
   가상 그래프(노드 40개)를 그리고 판정 — 페이지 오류·리소스 로드 실패·console.error·Qt 콘솔 error 0건, canvas 존재와
   그려진 픽셀(alpha>0) 1개 이상, 노드·링크 수 일치, 좌표 계산, 로컬이 아닌 주소 요청 시도 0건, 가로채기·탐색 차단 기록 0건
4) 성능 참고치(합격 기준 아님): 노드 1,000·5,000개 가상 그래프의 첫 프레임까지 시간

외부 요청 감지의 한계: 원격 요청은 웹뷰 설정(LocalContentCanAccessRemoteUrls 끔)이 가로채기보다 먼저 막으므로
interceptor.blocked는 보통 비어 있고 판정 근거가 되지 못한다. Qt 콘솔(javaScriptConsoleMessage)에도 네트워크 실패가
전달되지 않는다. 그래서 동적 판정은 페이지 계측(fetch·XHR·WebSocket·EventSource·Worker·sendBeacon 감싸기, 리소스
error 이벤트, Resource Timing, 문서 src·href 속성)에 기댄다. 계측 전에 시작된 요청, CSS 안 url(), 계측을 우회한
요청은 놓칠 수 있다. 따라서 1차 근거는 2)의 정적 검사이고 3)은 보조다.
vendor JS는 생성 HTML에 인라인으로 넣는다(웹뷰가 LocalContentCanAccessFileUrls를 끄므로 <script src="파일">은 읽히지 않음).
종료 코드 0 = 1)~3) 통과.
"""

import hashlib
import json
import os
import random
import re
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

VENDOR_DIR = os.path.join(REPO_ROOT, "hazop", "kg", "vendor", "force-graph-1.52.0")
VENDOR_JS = os.path.join(VENDOR_DIR, "force-graph.min.js")
VENDOR_LICENSE = os.path.join(VENDOR_DIR, "LICENSE")
VENDOR_SOURCE = os.path.join(VENDOR_DIR, "SOURCE.md")

# vendor 본문에 들어 있는 URL 문자열 중 허용하는 것(요청 대상이 아닌 이름공간·명세 식별자, 머리 주석의 저장소 주소).
VENDOR_URL_ALLOWLIST = frozenset({
    "http://www.w3.org/1998/Math/MathML",
    "http://www.w3.org/1999/xhtml",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/2000/xmlns/",
    "http://www.w3.org/XML/1998/namespace",
    "http://www.w3.org/TR/2008/REC-WCAG20-20081211/#contrast-ratiodef",
    "https://github.com/vasturiano/force-graph",
})
URL_RE = re.compile(r"""https?://[^\s"'`<>()\\]*""", re.IGNORECASE)
# 생성 부분(vendor 밖)에만 쓰는 넓은 규칙: http·https·ws·wss·ftp 주소와, 따옴표·괄호·= 바로 뒤(공백 허용)의
# 프로토콜 상대 주소(//host). JS 주석의 //는 앞 글자가 따옴표·괄호·=가 아니므로 잡지 않는다.
GENERATED_URL_RE = re.compile(r"""(?:https?|wss?|ftp)://[^\s"'`<>()\\]*|["'`(=]\s*//[^\s"'`<>()\\/]+""",
                              re.IGNORECASE)

SMALL_NODES = 40
PERF_SIZES = (1000, 5000)


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def recorded_hashes():
    """SOURCE.md에서 '파일명: <64자리 hex>' 기록을 읽는다."""
    with open(VENDOR_SOURCE, encoding="utf-8") as fh:
        text = fh.read()
    return {m.group(1): m.group(2) for m in re.finditer(r"([\w.\-]+):\s*([0-9a-f]{64})", text)}


def vendor_text():
    with open(VENDOR_JS, encoding="utf-8") as fh:
        return fh.read()


def synthetic_graph(n, seed=0):
    """가상 그래프(실제 설비 아님): 무작위 트리에 추가 링크를 n/5개 더한다. seed 고정으로 결정적."""
    rnd = random.Random(seed)
    kinds = ["equipment", "pipe_segment", "instrument", "document", "requirement"]
    nodes = [{"id": "n%d" % i, "kind": kinds[i % len(kinds)]} for i in range(n)]
    links = [{"source": "n%d" % rnd.randrange(i), "target": "n%d" % i} for i in range(1, n)]
    for _ in range(n // 5):
        a, b = rnd.randrange(n), rnd.randrange(n)
        if a != b:
            links.append({"source": "n%d" % a, "target": "n%d" % b})
    return {"nodes": nodes, "links": links}


PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>kg renderer probe</title>
<style>html,body{margin:0;height:100%%;overflow:hidden}#graph{width:100%%;height:100%%}</style>
<script>
window.__kg = {errors: [], net: [], done: false};
(function () {
  var r = window.__kg, LOCAL = {"file:": 1, "data:": 1, "blob:": 1, "about:": 1};
  function abs(u) { try { return new URL(String(u), location.href).href; } catch (e) { return String(u); } }
  function note(how, u) { u = abs(u); var p = u.split(":")[0] + ":"; if (!LOCAL[p.toLowerCase()]) r.net.push(how + " " + u); }
  r.note = note;
  window.addEventListener("error", function (e) {
    var t = e.target;
    if (t && t !== window && (t.src || t.href)) { r.errors.push("resource error: " + (t.src || t.href)); note("element", t.src || t.href); }
    else r.errors.push("error: " + (e.message || e.type));
  }, true);
  window.addEventListener("unhandledrejection", function (e) { r.errors.push("rejection: " + String(e.reason)); });
  var ce = console.error; console.error = function () {
    r.errors.push("console.error: " + Array.prototype.join.call(arguments, " ")); return ce.apply(console, arguments); };
  if (window.fetch) { var f = window.fetch; window.fetch = function (u) { note("fetch", u && u.url ? u.url : u); return f.apply(this, arguments); }; }
  var xo = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u) { note("xhr", u); return xo.apply(this, arguments); };
  ["WebSocket", "EventSource", "Worker", "SharedWorker"].forEach(function (k) {
    var C = window[k]; if (!C) return;
    window[k] = function (u) { note(k, u); return new (Function.prototype.bind.apply(C, [null].concat([].slice.call(arguments))))(); };
  });
  if (navigator.sendBeacon) { var sb = navigator.sendBeacon.bind(navigator); navigator.sendBeacon = function (u, d) { note("beacon", u); return sb(u, d); }; }
  // 실행 끝에 부르는 정리: 문서 안 src·href 속성과 Resource Timing 항목 중 로컬이 아닌 주소를 기록
  r.finalize = function () {
    Array.prototype.forEach.call(document.querySelectorAll("[src],[href]"), function (el) {
      ["src", "href"].forEach(function (a) { var v = el.getAttribute(a); if (v) note("attr", v); }); });
    (performance.getEntriesByType("resource") || []).forEach(function (e) { note("timing", e.name); });
    var seen = {}; r.net = r.net.filter(function (x) { return seen[x] ? false : (seen[x] = 1); });
  };
})();
</script>
<script>%(vendor)s</script>
</head><body><div id="graph"></div>
<script>
(function () {
  var r = window.__kg, data = %(data)s, frames = 0, t0;
  try {
    t0 = performance.now();
    var g = ForceGraph()(document.getElementById("graph"))
      .nodeId("id").nodeAutoColorBy("kind")
      .onRenderFramePost(function () {
        frames += 1;
        if (frames === 1) r.first_frame_ms = performance.now() - t0;
        if (frames === %(frames)d) {
          var c = document.querySelector("#graph canvas"), d = g.graphData();
          r.canvas = !!c; r.canvas_size = c ? [c.width, c.height] : null;
          r.painted = 0;
          if (c) { var px = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
            for (var i = 3; i < px.length; i += 4) if (px[i] > 0) r.painted += 1; }
          r.nodes = d.nodes.length; r.links = d.links.length;
          r.positioned = d.nodes.filter(function (n) { return isFinite(n.x) && isFinite(n.y); }).length;
          r.frames_ms = performance.now() - t0;
          r.done = true;
        }
      })
      .graphData(data);
    r.setup_ms = performance.now() - t0;
  } catch (e) { r.errors.push("exception: " + e); r.done = true; }
})();
</script></body></html>
"""


def build_page(graph, frames=10):
    """임시 폴더에 둘 HTML 문자열. vendor JS는 인라인으로 넣는다."""
    data = json.dumps(graph, separators=(",", ":")).replace("</", "<\\/")
    return PAGE % {"vendor": vendor_text(), "data": data, "frames": frames}


# 음성 대조용 위반 삽입: 루프백 주소(포트 9, 응답 없음)로 이미지·fetch 요청. 실제 외부 주소는 쓰지 않는다.
LOOPBACK_INJECTION = ('<img src="https://127.0.0.1:9/hz-probe.png"><script>'
                      'fetch("https://127.0.0.1:9/hz-probe").catch(function () {});</script>')


def violating_page(graph):
    """정상 페이지 <body> 바로 뒤에 LOOPBACK_INJECTION을 넣은 HTML(판정 장치가 실패로 잡는지 확인용)."""
    return build_page(graph).replace("<body>", "<body>" + LOOPBACK_INJECTION, 1)


def url_violations(html, vendor):
    """V2 외부 URL 규칙 위반 목록. vendor 본문은 SHA-256으로 고정되어 있으므로 허용 목록과 대조하고,
    나머지(생성 부분)에는 URL이 하나도 없어야 한다."""
    bad = []
    if vendor not in html:
        bad.append("vendor 본문이 HTML에 그대로 들어 있지 않음")
    rest = html.replace(vendor, "")
    bad += ["생성 부분: " + u for u in GENERATED_URL_RE.findall(rest)]
    bad += ["vendor 허용 목록 밖: " + u for u in sorted(set(URL_RE.findall(vendor)) - VENDOR_URL_ALLOWLIST)]
    return bad


def pump_until(cond, timeout):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


def js_value(view, expr, timeout=10.0):
    out = []
    view.page().runJavaScript(expr, 0, out.append)
    pump_until(lambda: out, timeout)
    return out[0] if out else None


def _probe_page_class():
    """hazop.app.webview.LocalPage에 콘솔 메시지 기록만 더한 하위 클래스(설정·탐색 제한은 그대로 상속)."""
    from PySide6.QtWebEngineCore import QWebEnginePage
    from hazop.app import webview

    class ConsoleRecordingPage(webview.LocalPage):
        def __init__(self, profile, parent=None):
            super().__init__(profile, parent)
            self.console = []

        def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802 (Qt 이름)
            name = {QWebEnginePage.InfoMessageLevel: "info", QWebEnginePage.WarningMessageLevel: "warning",
                    QWebEnginePage.ErrorMessageLevel: "error"}.get(level, str(level))
            self.console.append({"level": name, "message": message, "line": line})

    return ConsoleRecordingPage


def render(html, workdir, timeout=120.0, page_attrs=None):
    """HazopWebView(앱과 같은 차단 설정)로 HTML을 열고 window.__kg 결과·콘솔 메시지·차단 기록 증가분을 돌려준다.
    콘솔을 받기 위해 생성 중에만 hazop.app.webview.LocalPage를 기록용 하위 클래스로 바꿔 끼운다(앱 코드는 그대로).
    page_attrs: {QWebEngineSettings 속성: 값} — 원인 대조 실험용. 기본(None)은 앱 설정 그대로."""
    from hazop.app import make_application, webview
    make_application(["check_kg_renderer"])
    path = os.path.join(workdir, "kg-probe-%d.html" % int(time.monotonic() * 1000))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    original = webview.LocalPage
    webview.LocalPage = _probe_page_class()
    try:
        v = webview.HazopWebView()
    finally:
        webview.LocalPage = original
    try:
        for attr, value in (page_attrs or {}).items():
            v.page().settings().setAttribute(attr, value)
        v.resize(900, 700)
        v.show()
        before = len(v.interceptor.blocked)
        start = time.monotonic()
        v.load_file(path)
        state = {}

        def read():
            s = js_value(v, "JSON.stringify(window.__kg || null)")
            if s and s != "null":
                state.update(json.loads(s))
            return state.get("done", False)

        finished = pump_until(read, timeout)
        state["wall_s"] = round(time.monotonic() - start, 2)
        state["timed_out"] = not finished
        pump_until(lambda: False, 0.5)   # 늦게 오는 요청·오류도 기록되게 잠시 더 돈다
        js_value(v, "window.__kg && window.__kg.finalize && window.__kg.finalize(), 1")
        read()
        state["console"] = list(v.page().console)
        state["blocked_requests"] = v.interceptor.blocked[before:]
        state["blocked_navigation"] = list(v.page().blocked_navigation)
        return state
    finally:
        v.dispose()
        v.close()
        v.deleteLater()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QCoreApplication.processEvents()


def render_problems(state, graph):
    """렌더링 판정. 빈 목록이면 통과."""
    p = []
    if state.get("timed_out"):
        p.append("시간 초과(렌더 프레임 미도달)")
    if state.get("errors"):
        p.append("페이지 오류: %r" % state["errors"])
    if not state.get("canvas"):
        p.append("canvas 없음")
    if state.get("nodes") != len(graph["nodes"]) or state.get("links") != len(graph["links"]):
        p.append("노드·링크 수 불일치: %s/%s" % (state.get("nodes"), state.get("links")))
    if state.get("positioned") != len(graph["nodes"]):
        p.append("좌표 미계산 노드 있음: %s" % state.get("positioned"))
    if not state.get("painted"):
        p.append("canvas에 그려진 픽셀 없음")
    cons = [c for c in state.get("console") or [] if c.get("level") == "error"]
    if cons:
        p.append("콘솔 오류: %r" % cons)
    if state.get("net"):
        p.append("로컬이 아닌 주소 요청 시도(페이지 계측): %r" % state["net"])
    if state.get("blocked_requests"):
        p.append("외부 요청 시도(가로채기 기록): %r" % state["blocked_requests"])
    if state.get("blocked_navigation"):
        p.append("탐색 차단 기록: %r" % state["blocked_navigation"])
    return p


def ok(label, cond, failures):
    print("  [%s] %s" % ("OK" if cond else "FAIL", label))
    if not cond:
        failures.append(label)


def main():
    from hazop.console import safe_console
    safe_console()
    failures = []
    print("1) vendor 무결성")
    rec = recorded_hashes()
    for name, path in (("force-graph.min.js", VENDOR_JS), ("LICENSE", VENDOR_LICENSE)):
        got = sha256(path) if os.path.isfile(path) else None
        ok("%s SHA-256 = SOURCE.md 기록값 (%s)" % (name, got), got is not None and got == rec.get(name), failures)
    ok("LICENSE 존재", os.path.isfile(VENDOR_LICENSE), failures)

    vendor = vendor_text()
    small = synthetic_graph(SMALL_NODES)
    html = build_page(small)
    print("2) 외부 URL 규칙")
    bad = url_violations(html, vendor)
    ok("생성 HTML 외부 URL 위반 없음 (vendor URL %d종은 허용 목록 대조)%s"
       % (len(set(URL_RE.findall(vendor))), (" — %r" % bad) if bad else ""), not bad, failures)

    with tempfile.TemporaryDirectory(prefix="kg-renderer-") as tmp:
        print("3) 렌더링 (HazopWebView, 외부 요청 차단)")
        st = render(html, tmp)
        probs = render_problems(st, small)
        print("     노드 %s, 링크 %s, canvas %s, 그린 픽셀 %s, 페이지 오류 %d건, Qt 콘솔 %d건, 요청 시도(계측) %d건, "
              "가로채기 차단 %d건, 첫 프레임 %.0f ms"
              % (st.get("nodes"), st.get("links"), st.get("canvas_size"), st.get("painted"), len(st.get("errors") or []),
                 len(st.get("console") or []), len(st.get("net") or []), len(st.get("blocked_requests") or []),
                 st.get("first_frame_ms") or -1))
        ok("가상 그래프 %d노드 렌더링%s" % (SMALL_NODES, (" — " + "; ".join(probs)) if probs else ""), not probs, failures)
        st = render(violating_page(small), tmp, timeout=30)
        neg = render_problems(st, small)
        ok("음성 대조: 루프백 img·fetch 삽입 페이지를 실패로 판정 (요청 시도 %d건, 가로채기 차단 %d건 — 가로채기는 근거가 못 됨)"
           % (len(st.get("net") or []), len(st.get("blocked_requests") or [])),
           any("요청 시도" in x for x in neg), failures)
        ok("음성 대조: 같은 페이지를 정적 URL 규칙도 위반으로 판정", bool(url_violations(violating_page(small), vendor)),
           failures)

        print("4) 성능 참고치 (합격 기준 아님)")
        for n in PERF_SIZES:
            g = synthetic_graph(n)
            st = render(build_page(g), tmp)
            probs = render_problems(st, g)
            print("     노드 %d·링크 %d: 그래프 설정 %.0f ms, 첫 프레임 %.0f ms, 10프레임 %.0f ms, 전체(로드 포함) %.2f s%s"
                  % (n, len(g["links"]), st.get("setup_ms") or -1, st.get("first_frame_ms") or -1,
                     st.get("frames_ms") or -1, st["wall_s"], (" — " + "; ".join(probs)) if probs else ""))

    print("결과: %s" % ("통과" if not failures else "실패 %d건" % len(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
