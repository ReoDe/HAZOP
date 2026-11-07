"""내장 웹뷰 (기획서/인터페이스.md §2.2·§2.3).

- 기존 뷰어 HTML(hazop/viewer/build.py 결과)을 파일 경로로 로드한다(setHtml 크기 제한 회피).
- qwebchannel.js와 앱 연결 스크립트는 템플릿에 넣지 않고 QWebEngineScript로 실행 시점에 주입한다
  (hazop/viewer/check.py의 TEMPLATE_SCRIPT_COUNT = 3 유지). bridge가 없으면 뷰어는 단독 모드로 동작한다.
- 네트워크 차단: 요청 가로채기(file:·qrc:·data:·blob:·about: 외 차단), 탐색 제한(로드한 파일만),
  LocalContentCanAccessRemoteUrls 끔, 디스크 캐시·쿠키 저장 없음(off-the-record 프로필).
- 메시지는 JSON 문자열 하나: Python→웹 load/setView/highlight/clearHighlight/focus/setMode/segments/clearSegments(④ 구간 색)/
  editMode/editPreview/restoreView(② 도면 편집), 웹→Python ready/nodeSelected/highlightResult/editPick.
- ③ 지식그래프 페이지(hazop/kg/screen_template.html, window.hzKG)는 같은 주입 스크립트가 연결만 해 주고 메시지 처리는
  페이지가 한다: Python→웹 loadKnowledge/selectNode/algorithmResult, 웹→Python ready/nodeSelected/linkSelected/
  runAlgorithm(기획서/그래프활용.md §5.2, 인터페이스.md §2.3).
"""

import json
import logging
import math
import os
import re

from PySide6.QtCore import QFile, QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings,
                                     QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView

from hazop.app import tokens

ALLOWED_SCHEMES = frozenset({"file", "qrc", "data", "blob", "about"})
MAX_MESSAGE_CHARS = 64 * 1024   # 웹 → Python 메시지 길이 상한(웹 내용은 신뢰하지 않음)
MAX_ID_CHARS = 200              # 노드·관계·로컬 ID 길이 상한
ID_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,%d}$" % MAX_ID_CHARS)  # 제어 문자 없는 1~200자
LOG = logging.getLogger("hazop.app.webview")


def clean_id(v):
    """웹에서 온 ID: 문자열이고 길이·형식이 맞으면 그대로, 아니면 None. 있는 ID인지는 받는 화면이 확인한다."""
    return v if isinstance(v, str) and ID_RE.fullmatch(v) else None


MAX_COORD = 1e7  # 도면 좌표·보기 값 절댓값 상한


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= MAX_COORD


def clean_view(v):
    """웹에서 온 보기 {s, x, y}: 모두 유한한 수이고 s > 0이면 그 값, 아니면 None."""
    if not isinstance(v, dict) or not all(_finite(v.get(k)) for k in ("s", "x", "y")) or v["s"] <= 0:
        return None
    return {"s": float(v["s"]), "x": float(v["x"]), "y": float(v["y"])}


def clean_edit_pick(msg):
    """editPick 메시지 → {"point": [x, y], "local_id", "view"}. 점이 유한한 수 두 개가 아니면 None."""
    p = msg.get("point")
    if not isinstance(p, list) or len(p) != 2 or not all(_finite(c) for c in p):
        return None
    return {"point": [float(p[0]), float(p[1])], "local_id": clean_id(msg.get("local_id")),
            "view": clean_view(msg.get("view"))}


def url_allowed(url):
    """웹뷰 요청 허용 여부. 로컬 파일·내장 자원만 허용하고 http·https·ws·ftp 등 원격 요청은 막는다."""
    return QUrl(url).scheme().lower() in ALLOWED_SCHEMES


class LocalOnlyInterceptor(QWebEngineUrlRequestInterceptor):
    """원격 URL 요청 차단. blocked에 막은 URL을 남긴다(검사용)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.blocked = []

    def interceptRequest(self, info):  # noqa: N802 (Qt 이름)
        url = info.requestUrl()
        if not url_allowed(url):
            self.blocked.append(url.toString())
            info.block(True)


_INTERCEPTOR = []


def _shared_interceptor(profile):
    if not _INTERCEPTOR:
        _INTERCEPTOR.append(LocalOnlyInterceptor(profile))
        profile.setUrlRequestInterceptor(_INTERCEPTOR[0])
    return _INTERCEPTOR[0]


class LocalPage(QWebEnginePage):
    """탐색 제한: 앱이 로드한 파일 외의 이동(링크 클릭 등)을 막는다."""

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self.allowed_file = None
        self.blocked_navigation = []

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
        """주 프레임은 앱이 로드한 파일(allowed_file)로만 이동할 수 있다(data:·blob:·다른 파일·원격 주소 금지).
        하위 프레임은 로컬 스킴만 허용한다(뷰어는 하위 프레임을 쓰지 않음)."""
        ok = url_allowed(url)
        if is_main_frame:
            ok = (url.scheme() == "file" and self.allowed_file is not None and
                  os.path.normcase(os.path.abspath(url.toLocalFile())) == os.path.normcase(self.allowed_file))
        if not ok:
            self.blocked_navigation.append(url.toString())
        return ok


class Bridge(QObject):
    """QWebChannel로 웹에 노출하는 객체(bridge). 메시지는 JSON 문자열 하나."""

    toWeb = Signal(str)            # Python → 웹
    nodeSelected = Signal(dict)    # {"local_id", "entity_id"}
    highlightResult = Signal(list)  # 그리지 못한 local_id 목록
    highlightResultFor = Signal(str, list)  # (request_id, 그리지 못한 local_id 목록) — 이전 요청 응답 구분용
    linkSelected = Signal(str)     # ③ 지식그래프: 클릭한 관계 ID
    algorithmRequested = Signal(dict)  # ③ 지식그래프 runAlgorithm: {"algorithm", "start"}
    editPick = Signal(dict)        # ② 편집: {"point": 도면 좌표 [x, y], "local_id"(없으면 None), "view"(없으면 None)}
    ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_ready = False
        self._pending = []

    def send(self, msg_type, **payload):
        payload["type"] = msg_type
        text = json.dumps(payload, ensure_ascii=False)
        if self.is_ready:
            self.toWeb.emit(text)
        else:
            self._pending.append(text)

    def reset(self):
        self.is_ready = False
        self._pending = []

    @Slot(str)
    def fromWeb(self, text):  # noqa: N802 (웹에서 부르는 이름)
        """웹 → Python. 형식이 맞지 않는 메시지는 버린다(웹 내용은 신뢰하지 않음).
        길이 상한(MAX_MESSAGE_CHARS) 초과·파싱 실패·너무 깊은 중첩(RecursionError)은 로그만 남기고 무시한다."""
        if not isinstance(text, str) or len(text) > MAX_MESSAGE_CHARS:
            LOG.warning("웹 메시지 무시: 문자열이 아니거나 길이 상한 %d자 초과", MAX_MESSAGE_CHARS)
            return
        try:
            msg = json.loads(text)
        except (TypeError, ValueError, RecursionError) as exc:
            LOG.warning("웹 메시지 무시: JSON 파싱 실패(%s)", type(exc).__name__)
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "ready":
            self.is_ready = True
            pending, self._pending = self._pending, []
            for p in pending:
                self.toWeb.emit(p)
            self.ready.emit()
        elif kind == "nodeSelected":
            self.nodeSelected.emit({"local_id": clean_id(msg.get("local_id")),
                                    "entity_id": clean_id(msg.get("entity_id"))})
        elif kind == "highlightResult":
            missing = msg.get("missing")
            missing = [m for m in missing if isinstance(m, str)] if isinstance(missing, list) else []
            rid = msg.get("request_id")
            self.highlightResult.emit(missing)
            self.highlightResultFor.emit(rid if isinstance(rid, str) else "", missing)
        elif kind == "linkSelected":
            lid = clean_id(msg.get("id"))
            if lid:
                self.linkSelected.emit(lid)
        elif kind == "runAlgorithm":
            alg, start = msg.get("algorithm"), clean_id(msg.get("start"))
            if alg in ("A1",) and start:
                self.algorithmRequested.emit({"algorithm": alg, "start": start})
        elif kind == "editPick":
            pick = clean_edit_pick(msg)
            if pick:
                self.editPick.emit(pick)


def _qwebchannel_js():
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.ReadOnly):
        raise RuntimeError("qwebchannel.js 자원을 열 수 없음")
    try:
        return bytes(f.readAll()).decode("utf-8")
    finally:
        f.close()


# 앱 연결 스크립트(템플릿 밖, 실행 시점 주입). DOM의 data-local-id만 쓰고 템플릿 내부 함수에 기대지 않는다.
BRIDGE_JS = r"""
(function () {
  "use strict";
  if (!window.qt || !window.qt.webChannelTransport || !window.QWebChannel) return;  // 단독 모드
  var CSS = %(css)s;
  new QWebChannel(qt.webChannelTransport, function (ch) {
    var b = ch.objects.bridge;
    function send(o) { b.fromWeb(JSON.stringify(o)); }
    if (window.hzKG && window.hzKG.attach) {  /* ③ 지식그래프 페이지: 연결만 하고 처리는 페이지(hzKG)가 함 */
      window.hzKG.attach(send);
      b.toWeb.connect(function (text) { try { window.hzKG.handle(JSON.parse(text)); } catch (x) { /* 형식 오류 무시 */ } });
      send({ type: "ready" });
      return;
    }
    var st = document.createElement("style"); st.textContent = CSS; document.head.appendChild(st);
    document.body.classList.add("hz-embedded");
    var vp = document.getElementById("viewport");
    var legend = document.createElement("div"); legend.className = "hz-legend";
    // 범례는 줌·맞춤 버튼(#zoom) 바로 위 왼쪽에 둔다(design-system W10, D16). 항목 단위로만 줄을 바꾼다.
    legend.innerHTML = '<span><i style="border-color:var(--hl-cause)"></i>원인 설비(채움)</span><span><i style="border-color:var(--hl-path)"></i>경로(굵은 선)</span>' +
      '<span><i style="border-color:var(--hl-path);border-top-style:dashed"></i>추정 경로(실제 흐름 경로 아님)</span><span><i style="border-color:var(--hl-safeguard)"></i>보호수단(이중 테두리)</span>';
    // 범례 안의 휠·드래그는 도면 확대·이동으로 넘기지 않는다(범례가 넘쳐 스크롤할 때).
    legend.addEventListener("wheel", function (e) { e.stopPropagation(); });
    legend.addEventListener("mousedown", function (e) { e.stopPropagation(); });
    if (vp) vp.appendChild(legend);
    function onClick(e) {
      var t = e.target.closest ? e.target.closest("[data-local-id]") : null;
      if (t) send({ type: "nodeSelected", local_id: t.getAttribute("data-local-id"), entity_id: t.getAttribute("data-entity-id") });
    }
    ["overlay", "graphsvg"].forEach(function (id) { var s = document.getElementById(id); if (s) s.addEventListener("click", onClick, true); });
    function els(lid) {
      var out = [];
      ["overlay", "graphsvg"].forEach(function (id) {
        var s = document.getElementById(id); if (!s) return;
        Array.prototype.forEach.call(s.querySelectorAll('[data-local-id="' + String(lid).replace(/["\\]/g, "") + '"]'), function (e) {
          if (e.classList.contains("pipe-hit") || e.classList.contains("gedge-hit")) {
            if (e.nextElementSibling) out.push(e.nextElementSibling);
          } else out.push(e);
        });
      });
      return out;
    }
    var marks = [];
    function clear() {
      Array.prototype.forEach.call(document.querySelectorAll(".hz-on"), function (e) {
        e.classList.remove("hz-on", "hz-cause", "hz-path", "hz-sg", "hz-est");
      });
      marks.forEach(function (m) { if (m.parentNode) m.parentNode.removeChild(m); });
      marks = [];
      document.body.classList.remove("hz-dim");
    }
    var NS = "http://www.w3.org/2000/svg";
    function ring(e, counted) {
      var bb; try { bb = e.getBBox(); } catch (x) { return; }
      var p = e.parentNode, pad = [6, 10], i;
      for (i = 0; i < (counted ? 2 : 1); i++) {
        var r = document.createElementNS(NS, "rect");
        r.setAttribute("x", bb.x - pad[i]); r.setAttribute("y", bb.y - pad[i]);
        r.setAttribute("width", bb.width + 2 * pad[i]); r.setAttribute("height", bb.height + 2 * pad[i]);
        r.setAttribute("rx", 6); r.setAttribute("class", "hz-ring"); p.appendChild(r); marks.push(r);
      }
      var label = counted ? "보호수단" : "보호수단 · 미계수", w = label.length * 11 + 10;
      var g = document.createElementNS(NS, "g"); g.setAttribute("class", "hz-badge" + (counted ? "" : " weak"));
      var br = document.createElementNS(NS, "rect");
      br.setAttribute("x", bb.x - 10); br.setAttribute("y", bb.y - 30); br.setAttribute("width", w); br.setAttribute("height", 16); br.setAttribute("rx", 8);
      var tx = document.createElementNS(NS, "text"); tx.setAttribute("x", bb.x - 5); tx.setAttribute("y", bb.y - 18); tx.textContent = label;
      g.appendChild(br); g.appendChild(tx); p.appendChild(g); marks.push(g);
    }
    function mark(ids, cls, extra) {
      var missing = [];
      (ids || []).forEach(function (lid) {
        var found = els(lid);
        if (!found.length) { missing.push(lid); return; }
        found.forEach(function (e) { e.classList.add("hz-on", cls); if (extra) e.classList.add(extra); });
      });
      return missing;
    }
    function setView(name) {
      if (name === "graph" && document.body.classList.contains("hz-no-graph")) return;  // ②에는 그래프 보기 없음
      var btn = document.getElementById(name === "graph" ? "tab-graph" : "tab-drawing");
      if (btn && !btn.disabled) btn.click();
    }
    function focus(lid) {
      var e = els(lid)[0];
      if (e && e.scrollIntoView) e.scrollIntoView({ block: "center", inline: "center" });
    }
    // ④ 검토구간 색: 강조(hz-*)와 따로 인라인 style로 칠한다. !important 강조·선택 규칙이 그 위에 그대로 이긴다.
    var segEls = [], segMarks = [], SEG_PROPS = ["stroke", "stroke-width", "stroke-dasharray", "fill", "fill-opacity", "stroke-opacity"];
    function clearSegments() {
      segEls.forEach(function (e) { SEG_PROPS.forEach(function (p) { e.style.removeProperty(p); }); e.removeAttribute("data-hz-seg"); });
      segMarks.forEach(function (m) { if (m.parentNode) m.parentNode.removeChild(m); });
      segEls = []; segMarks = [];
    }
    function segBadge(e, color, text) {  // 구간 번호 꼬리표: 색만으로 구분하지 않도록 도면에도 S 번호를 적는다
      var bb; try { bb = e.getBBox(); } catch (x) { return; }
      var g = document.createElementNS(NS, "g"), r = document.createElementNS(NS, "rect"), t = document.createElementNS(NS, "text");
      g.setAttribute("class", "hz-seg-badge"); g.setAttribute("pointer-events", "none");
      r.setAttribute("x", bb.x); r.setAttribute("y", bb.y - 17); r.setAttribute("width", text.length * 8 + 8); r.setAttribute("height", 14); r.setAttribute("rx", 3);
      r.style.setProperty("fill", color);
      t.setAttribute("x", bb.x + 4); t.setAttribute("y", bb.y - 6); t.textContent = text;
      t.style.setProperty("fill", "var(--on-seg)"); t.style.setProperty("font-size", "11px"); t.style.setProperty("font-weight", "700");
      g.appendChild(r); g.appendChild(t); e.parentNode.appendChild(g); segMarks.push(g);
    }
    function paintSeg(e, color, active, tag) {
      var c = e.classList, line = c.contains("pipe-line") || c.contains("gedge");
      e.style.setProperty("stroke", color);
      e.style.setProperty("stroke-opacity", "1");
      if (line) e.style.setProperty("stroke-width", active ? "7" : "4.5");
      else if (c.contains("tagbox")) e.style.setProperty("stroke-width", active ? "2" : "1.2");
      else { e.style.setProperty("stroke-width", active ? "4" : "2.5"); e.style.setProperty("fill", color); e.style.setProperty("fill-opacity", active ? ".22" : ".1"); }
      e.setAttribute("data-hz-seg", tag);
      segEls.push(e);
    }
    function segments(m) {
      clearSegments();
      (m.groups || []).forEach(function (g) {
        var first = null, label = String(g.label || "");
        (g.ids || []).forEach(function (lid) {
          els(lid).forEach(function (e) {
            if (e.getAttribute("data-hz-seg")) return;
            paintSeg(e, g.color, !!g.active, label);
            if (!first || (!first.classList.contains("sym") && e.classList.contains("sym"))) first = e;
          });
        });
        if (first && label) segBadge(first, g.color, label);
      });
      (m.uncovered || []).forEach(function (lid) {
        els(lid).forEach(function (e) { paintSeg(e, "var(--warn-line)", false, "uncovered"); e.style.setProperty("stroke-dasharray", "5 3"); e.style.setProperty("fill-opacity", "0"); });
      });
    }
    // ② 편집: 선택 외 도구에서는 클릭을 도면 좌표로 바꿔 editPick만 보낸다(템플릿 선택·nodeSelected는 막음).
    // 도면 좌표 = 오버레이 SVG 사용자 좌표 + svg_alignment.offset. 끌어서 이동을 끝낸 클릭은 버린다.
    var edit = { on: false, tool: "select" }, down = null, preview = null, OFF = [0, 0];
    try {
      var exd = JSON.parse(document.getElementById("extraction").textContent);
      var o = exd.coordinate_system.svg_alignment.offset;
      if (o && isFinite(o[0]) && isFinite(o[1])) OFF = [Number(o[0]), Number(o[1])];
    } catch (x) { /* 오프셋 없음: 0 */ }
    var ovl = document.getElementById("overlay");
    function curView() { return window.hzView && window.hzView.get ? window.hzView.get() : null; }
    if (vp && ovl) {
      vp.addEventListener("mousedown", function (e) { down = [e.clientX, e.clientY]; }, true);
      vp.addEventListener("click", function (e) {
        if (!edit.on || edit.tool === "select") return;
        if (e.target.closest && e.target.closest(".float, .hz-legend")) return;
        e.stopPropagation();
        if (down && Math.abs(e.clientX - down[0]) + Math.abs(e.clientY - down[1]) > 3) return;
        var m = ovl.getScreenCTM(); if (!m) return;
        var p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
        var t = e.target.closest ? e.target.closest("#overlay [data-local-id]") : null;
        send({ type: "editPick", point: [p.x + OFF[0], p.y + OFF[1]], local_id: t ? t.getAttribute("data-local-id") : null, view: curView() });
      }, true);
    }
    function editPreview(points) {
      if (preview && preview.parentNode) preview.parentNode.removeChild(preview);
      preview = null;
      if (!ovl || !Array.isArray(points) || !points.length) return;
      preview = document.createElementNS(NS, "g");
      preview.setAttribute("class", "hz-preview"); preview.setAttribute("pointer-events", "none");
      preview.setAttribute("transform", "translate(" + (-OFF[0]) + "," + (-OFF[1]) + ")");
      var pts = points.filter(function (p) { return Array.isArray(p) && isFinite(p[0]) && isFinite(p[1]); });
      var pl = document.createElementNS(NS, "polyline");
      pl.setAttribute("points", pts.map(function (p) { return Number(p[0]) + "," + Number(p[1]); }).join(" "));
      preview.appendChild(pl);
      pts.forEach(function (p) {
        var c = document.createElementNS(NS, "circle");
        c.setAttribute("cx", Number(p[0])); c.setAttribute("cy", Number(p[1])); c.setAttribute("r", 4);
        preview.appendChild(c);
      });
      ovl.appendChild(preview);
    }
    function handle(m) {
      if (!m || typeof m !== "object") return;
      if (m.type === "editMode") {
        edit.on = !!m.on; edit.tool = typeof m.tool === "string" ? m.tool : "select";
        document.body.classList.toggle("hz-editing", edit.on && edit.tool !== "select");
        if (!edit.on) editPreview(null);
      } else if (m.type === "editPreview") editPreview(m.points);
      else if (m.type === "restoreView") { if (window.hzView && m.view) window.hzView.set(m.view); }
      else if (m.type === "setView") setView(m.view);
      else if (m.type === "setDrawingEnabled") {
        var dt = document.getElementById("tab-drawing");
        if (dt) dt.disabled = !m.enabled;
        if (!m.enabled) { var gt = document.getElementById("tab-graph"); if (gt && !gt.disabled) gt.click(); }
      } else if (m.type === "setMode") {
        document.body.classList.toggle("hz-hide-panel", !!m.hide_panel);
        // ②: 도면 기준 추출만 보인다('P&ID 구조' 그래프 탭 없음, 결정로그 2026-11-06). ④⑤는 그래프 탭을 그대로 쓴다.
        document.body.classList.toggle("hz-no-graph", !!m.hide_graph);
        if (m.hide_graph && document.body.classList.contains("tab-graph")) setView("drawing");
        window.dispatchEvent(new Event("resize"));
      } else if (m.type === "segments") segments(m);
      else if (m.type === "clearSegments") clearSegments();
      else if (m.type === "clearHighlight") clear();
      else if (m.type === "focus") focus(m.local_id);
      else if (m.type === "highlight") {
        clear();
        var missing = [];
        document.body.classList.add("hz-dim");
        missing = missing.concat(mark(m.path, "hz-path"));
        missing = missing.concat(mark(m.estimated, "hz-path", "hz-est"));
        missing = missing.concat(mark(m.cause, "hz-cause"));
        (m.safeguards || []).forEach(function (s) {
          var f = els(s.local_id);
          if (!f.length) { missing.push(s.local_id); return; }
          f.forEach(function (e) { e.classList.add("hz-on", "hz-sg"); if (e.closest && e.closest("#overlay") && e.classList.contains("sym")) ring(e, !!s.counted); });
        });
        send({ type: "highlightResult", request_id: m.request_id || null, missing: missing });
      }
    }
    b.toWeb.connect(function (text) { try { handle(JSON.parse(text)); } catch (x) { /* 형식 오류 무시 */ } });
    send({ type: "ready" });
  });
})();
"""


def bridge_js():
    return BRIDGE_JS % {"css": json.dumps(tokens.web_css(), ensure_ascii=False)}


class HazopWebView(QWebEngineView):
    """②④⑤가 공유하는 웹뷰 하나. 화면을 바꿀 때 해당 화면의 캔버스 자리로 옮긴다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Qt 6의 기본 프로필은 off-the-record(디스크 캐시·쿠키 저장 없음). 프로필을 직접 만들면 종료 시 페이지보다 먼저
        # 지워져 프로세스가 비정상 종료되므로 기본 프로필을 쓰고, 요청 가로채기는 프로필에 한 번만 붙인다.
        self.profile = QWebEngineProfile.defaultProfile()
        self.profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        self.interceptor = _shared_interceptor(self.profile)
        page = LocalPage(self.profile, self)
        self.setPage(page)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)  # 로드한 HTML은 다른 파일을 읽지 않음
        s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.DnsPrefetchEnabled, False)
        s.setAttribute(QWebEngineSettings.AutoLoadIconsForPage, False)
        self.bridge = Bridge(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel)
        for name, source, point in (("hazop-qwebchannel", _qwebchannel_js(), QWebEngineScript.DocumentCreation),
                                    ("hazop-bridge", bridge_js(), QWebEngineScript.DocumentReady)):
            sc = QWebEngineScript()
            sc.setName(name)
            sc.setSourceCode(source)
            sc.setInjectionPoint(point)
            sc.setWorldId(QWebEngineScript.MainWorld)
            sc.setRunsOnSubFrames(False)
            page.scripts().insert(sc)
        self.current_file = None
        self.current_stamp = None
        self.hide_panel = False
        self.hide_graph = False
        self.drawing_enabled = True
        self.edit = {"on": False, "tool": "select"}

    def dispose(self):
        """종료 전에 페이지를 먼저 지운다(웹 렌더 프로세스가 남은 채 인터프리터가 끝나면 비정상 종료될 수 있음)."""
        import shiboken6
        page = self.page()
        if page is not None and shiboken6.isValid(page):
            page.setWebChannel(None)
            shiboken6.delete(page)

    @staticmethod
    def _stamp(path):
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)

    def load_file(self, path):
        """뷰어 HTML 파일 로드(Python → 웹 'load'). 같은 경로라도 파일이 다시 만들어졌으면(mtime·크기 변경) 다시 읽는다."""
        path = os.path.abspath(path)
        stamp = self._stamp(path)
        if self.current_file == path and self.current_stamp == stamp:
            return False
        self.current_file = path
        self.current_stamp = stamp
        self.page().allowed_file = path
        self.bridge.reset()
        self.bridge.send("setMode", hide_panel=self.hide_panel, hide_graph=self.hide_graph)
        # 도면 탭 잠금은 페이지를 새로 읽을 때마다(loadFinished 후 브리지 ready 시점) 다시 적용한다
        self.bridge.send("setDrawingEnabled", enabled=self.drawing_enabled)
        self.bridge.send("editMode", **self.edit)
        self.load(QUrl.fromLocalFile(path))
        return True

    def set_drawing_enabled(self, enabled):
        """그래프 버전 불일치 등: 도면 탭을 끄고 그래프 탭만 쓰게 한다. 상태를 기억해 다시 읽을 때도 적용한다."""
        self.drawing_enabled = bool(enabled)
        self.bridge.send("setDrawingEnabled", enabled=self.drawing_enabled)

    def set_mode(self, hide_panel, hide_graph=False):
        """②: 웹 속성 패널 사용·그래프 탭 숨김(hide_graph), ④⑤: 웹 패널 숨기고 Qt 상세 패널 사용(§2.2)."""
        self.hide_panel = bool(hide_panel)
        self.hide_graph = bool(hide_graph)
        self.bridge.send("setMode", hide_panel=self.hide_panel, hide_graph=self.hide_graph)

    def set_view(self, view):
        self.bridge.send("setView", view=view)

    def highlight(self, spec):
        self.bridge.send("highlight", **spec)

    def clear_highlight(self):
        self.bridge.send("clearHighlight")

    def set_segments(self, groups, uncovered=()):
        """④ 검토구간 색. groups = [{"color", "active", "label"(S 번호), "ids": [local_id]}] 순서대로, 한 요소는 첫 구간 색만.
        uncovered = 어느 구간에도 없는 요소의 local_id(점선)."""
        self.bridge.send("segments", groups=list(groups), uncovered=list(uncovered))

    def clear_segments(self):
        self.bridge.send("clearSegments")

    def focus(self, local_id):
        self.bridge.send("focus", local_id=local_id)

    def set_edit_mode(self, on, tool="select"):
        """② 편집 모드와 도구. 상태를 기억해 다시 읽을 때도 적용한다(다른 화면으로 가면 main_window.go가 끈다)."""
        self.edit = {"on": bool(on), "tool": tool}
        self.bridge.send("editMode", **self.edit)

    def edit_preview(self, points):
        """경로 그리기 중인 점들(도면 좌표)을 임시 선으로 보인다. 빈 목록이면 지운다."""
        self.bridge.send("editPreview", points=[list(p) for p in points])

    def restore_view(self, view):
        self.bridge.send("restoreView", view=view)

    def current_view(self, callback):
        """지금 확대·위치 {s, x, y}를 callback으로 넘긴다(페이지가 준비되지 않았거나 값이 이상하면 None)."""
        if not self.bridge.is_ready:
            callback(None)
            return
        self.page().runJavaScript("window.hzView ? window.hzView.get() : null", 0, lambda v: callback(clean_view(v)))
