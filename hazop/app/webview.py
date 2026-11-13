"""내장 웹뷰 (기획서/인터페이스.md §2.2·§2.3).

- 기존 뷰어 HTML(hazop/viewer/build.py 결과)을 파일 경로로 로드한다(setHtml 크기 제한 회피).
- qwebchannel.js와 앱 연결 스크립트는 템플릿에 넣지 않고 QWebEngineScript로 실행 시점에 주입한다
  (hazop/viewer/check.py의 TEMPLATE_SCRIPT_COUNT = 3 유지). bridge가 없으면 뷰어는 단독 모드로 동작한다.
- 네트워크 차단: 요청 가로채기(file:·qrc:·data:·blob:·about: 외 차단), 탐색 제한(로드한 파일만),
  LocalContentCanAccessRemoteUrls 끔, 디스크 캐시·쿠키 저장 없음(off-the-record 프로필).
- 메시지는 JSON 문자열 하나: Python→웹 load/setView/highlight/clearHighlight/focus/setMode/segments/clearSegments(④ 구간 색)/
  editMode/editPreview/restoreView(② 도면 편집)/openPathQuery/toggleLayer(② 명령), 웹→Python ready/nodeSelected/highlightResult/editPick.
- ③ 지식그래프 페이지(hazop/kg/screen_template.html, window.hzKG)는 같은 주입 스크립트가 연결만 해 주고 메시지 처리는
  페이지가 한다: Python→웹 loadKnowledge/selectNode/algorithmResult, 웹→Python ready/nodeSelected/linkSelected/
  runAlgorithm(기획서/그래프활용.md §5.2, 인터페이스.md §2.3).
"""

import json
import logging
import math
import os
import re

from PySide6.QtCore import QFile, QIODevice, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings,
                                     QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView

from hazop.app import icons, tokens

ALLOWED_SCHEMES = frozenset({"file", "qrc", "data", "blob", "about"})
MAX_MESSAGE_CHARS = 64 * 1024   # 웹 → Python 메시지 길이 상한(웹 내용은 신뢰하지 않음)
MAX_ID_CHARS = 200              # 노드·관계·로컬 ID 길이 상한
ID_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,%d}$" % MAX_ID_CHARS)  # 제어 문자 없는 1~200자
LOG = logging.getLogger("hazop.app.webview")


def clean_id(v):
    """웹에서 온 ID: 문자열이고 길이·형식이 맞으면 그대로, 아니면 None. 있는 ID인지는 받는 화면이 확인한다."""
    return v if isinstance(v, str) and ID_RE.fullmatch(v) else None


MAX_SELECTION = 2000            # 한 번에 받는 고른 구성요소 수 상한(chat-panel.md §6.2)
MAX_COORD = 1e7  # 도면 좌표·보기 값 절댓값 상한


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= MAX_COORD


def clean_id_list(v, limit=MAX_SELECTION):
    """웹에서 온 ID 목록 → (형식이 맞는 ID만 앞에서 limit개, 잘렸는지). 목록이 아니면 ([], False)."""
    if not isinstance(v, list):
        return [], False
    ids = [i for i in map(clean_id, v[:limit]) if i is not None]
    return ids, len(v) > limit


def clean_selection_changed(msg):
    """selectionChanged 메시지 → {"selected", "added", "removed", "via", "truncated"}. ID는 clean_id로 거르고 2,000개를 넘으면 자른다."""
    selected, cut = clean_id_list(msg.get("selected"))
    added, cut2 = clean_id_list(msg.get("added"))
    removed, cut3 = clean_id_list(msg.get("removed"))
    via = msg.get("via")
    return {"selected": selected, "added": added, "removed": removed,
            "via": via if via in ("click", "box", "box_remove", "clear") else "click",
            "truncated": bool(cut or cut2 or cut3 or msg.get("truncated") is True)}


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
    chipClicked = Signal(str)      # ②④ 도면 연결점 칩: 앱이 준 key
    selectionChanged = Signal(dict)  # 고르기: {"selected", "added", "removed", "via", "truncated"}(사용자 조작에서만)
    selectionFor = Signal(str, list)  # (request_id, 지금 고른 local_id) — selection() 응답
    sheetReady = Signal(str)       # 도면 HTML을 읽고 ready를 받은 뒤, 그 도면의 graph_id("" = 모름)
    ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_ready = False
        self.selection_truncated = False  # 마지막 selection 응답이 잘렸는지
        self.graph_id = ""          # 지금 읽는 도면의 graph_id(HazopWebView.load_file이 정함)
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
            self.sheetReady.emit(self.graph_id)
        elif kind == "selectionChanged":
            self.selectionChanged.emit(clean_selection_changed(msg))
        elif kind == "selection":
            rid = msg.get("request_id")
            ids, cut = clean_id_list(msg.get("selected"))
            self.selection_truncated = bool(cut or msg.get("truncated") is True)
            self.selectionFor.emit(rid if isinstance(rid, str) else "", ids)
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
        elif kind == "chip":
            key = clean_id(msg.get("key"))
            if key:
                self.chipClicked.emit(key)
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
  var ICONS = %(icons)s;  /* 화면 아이콘(hazop/app/icons.py svg_inline, 글자색을 따름) */
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
    [["zout", "zoom-out"], ["zin", "zoom-in"], ["zfit", "arrows-maximize"]].forEach(function (p) {  // 확대·축소·맞춤 단추를 아이콘으로(이름은 title·aria-label 그대로)
      var b = document.getElementById(p[0]); if (!b || !ICONS[p[1]]) return;
      b.setAttribute("aria-label", b.getAttribute("title") || b.textContent);
      b.innerHTML = ICONS[p[1]] + (p[0] === "zfit" ? '<span class="hz-ilabel">맞춤</span>' : "");
    });
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
      Array.prototype.forEach.call(document.querySelectorAll(".hz-seg-in, .hz-pick"), function (e) { e.classList.remove("hz-seg-in", "hz-pick"); });
      document.body.classList.remove("hz-segfocus");
      segEls = []; segMarks = [];
      refreshTags();
    }
    function refreshTags() { if (window.hzView) window.hzView.set(window.hzView.get()); }  // 태그 글자 층을 다시 그린다
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
    function segLegend(groups, uncovered) { if (window.hzSegLegend) window.hzSegLegend(groups, uncovered); }
    // 구간 하나를 고르면(active) 그 구간만 칠하고 나머지 요소는 흐리게 한다(hz-segfocus). 고른 구간이 없으면 전체 보기.
    function segments(m) {
      clearSegments();
      var groups = m.groups || [], focused = groups.some(function (g) { return g.active; });
      segLegend(groups, (m.uncovered || []).length);
      document.body.classList.toggle("hz-segfocus", focused);
      groups.forEach(function (g) {
        if (focused && !g.active) return;
        var first = null, label = String(g.label || "");
        (g.ids || []).forEach(function (lid) {
          els(lid).forEach(function (e) {
            if (focused) e.classList.add("hz-seg-in");
            if (e.getAttribute("data-hz-seg")) return;
            paintSeg(e, g.color, !!g.active, label);
            if (!first || (!first.classList.contains("sym") && e.classList.contains("sym"))) first = e;
          });
        });
        if (first && label) segBadge(first, g.color, label);
      });
      if (!focused) (m.uncovered || []).forEach(function (lid) {
        els(lid).forEach(function (e) { paintSeg(e, "var(--warn-line)", false, "uncovered"); e.style.setProperty("stroke-dasharray", "5 3"); e.style.setProperty("fill-opacity", "0"); });
      });
      refreshTags();
    }
    // ④ 고른 구성요소 하나: 구간 색 위에 따로 강조(hz-pick). center면 화면 가운데로 옮기고 확대한다.
    function pick(lid, center) {
      // 템플릿 클릭이 남긴 선택 표시(.selected)도 지운다. ④에서 고른 구성요소 표시는 hz-pick 하나뿐이다.
      Array.prototype.forEach.call(document.querySelectorAll(".hz-pick, .selected"), function (e) { e.classList.remove("hz-pick", "selected"); });
      var found = lid ? els(lid) : [];
      found.forEach(function (e) { e.classList.add("hz-pick"); });
      refreshTags();  // 겹쳐서 숨겼던 태그 글자라도 고른 것은 보인다(템플릿이 hz-pick을 먼저 놓는다)
      if (!lid) return;
      var shown = found.filter(function (e) { var r = e.getBoundingClientRect(); return r.width || r.height; })[0];
      if (!center || !shown || !vp || !window.hzView) return;
      var v = window.hzView.get(), vr = vp.getBoundingClientRect(), b = shown.getBoundingClientRect(), s = Math.max(v.s, 1.5);
      var cx = (b.left + b.width / 2 - vr.left - v.x) / v.s, cy = (b.top + b.height / 2 - vr.top - v.y) / v.s;
      window.hzView.set({ s: s, x: vr.width / 2 - cx * s, y: vr.height / 2 - cy * s });
    }
    // ②④ 도면 연결점 칩: 연결점 아래에 "S7 → SNP-M-101에서 계속"(link) 또는 "미연결 · 사유"(unlinked). 누르면 key를 앱에 보낸다.
    // 칩은 도면 좌표계 안에 있지만 확대 배율과 상관없이 화면에서 같은 크기(글자 12px)로 보이게 배율이 바뀌면 다시 그린다.
    var chipMarks = [], chipList = [], chipScale = 0;
    function chipPx(e) { var m = e.parentNode && e.parentNode.getScreenCTM ? e.parentNode.getScreenCTM() : null; return m ? Math.hypot(m.a, m.b) || 1 : 1; }
    function chips(list) {
      chipList = list || [];
      chipMarks.forEach(function (m) { if (m.parentNode) m.parentNode.removeChild(m); });
      chipMarks = [];
      chipList.forEach(function (c) {
        var e = els(c.local_id).filter(function (x) { return x.closest && x.closest("#overlay"); })[0] || els(c.local_id)[0];
        if (!e) return;
        var bb; try { bb = e.getBBox(); } catch (x) { return; }
        var k = 1 / chipPx(e);
        chipScale = chipPx(e);
        var g = document.createElementNS(NS, "g"), r = document.createElementNS(NS, "rect"), t = document.createElementNS(NS, "text");
        var text = String(c.text || ""), h = 18 * k, w = (text.length * 8 + 16) * k, y = bb.y + bb.height + 16 * k + (c.row || 0) * (h + 2 * k);  // 태그 글자 한 줄 아래
        g.setAttribute("class", "hz-chip " + (c.kind === "unlinked" ? "hz-chip-warn" : "hz-chip-link"));
        g.setAttribute("data-chip-key", String(c.key || ""));
        g.setAttribute("role", "button"); g.setAttribute("aria-label", text);
        r.setAttribute("x", bb.x); r.setAttribute("y", y); r.setAttribute("width", w); r.setAttribute("height", h); r.setAttribute("rx", h / 2);
        r.style.setProperty("stroke-width", 1.2 * k);
        t.setAttribute("x", bb.x + 8 * k); t.setAttribute("y", y + 13 * k); t.textContent = text;
        t.style.setProperty("font-size", (12 * k) + "px");
        var tip = document.createElementNS(NS, "title"); tip.textContent = String(c.tip || text); g.appendChild(tip);
        g.appendChild(r); g.appendChild(t);
        g.addEventListener("click", function (ev) { ev.stopPropagation(); send({ type: "chip", key: String(c.key || "") }); }, true);
        g.addEventListener("mousedown", function (ev) { ev.stopPropagation(); }, true);
        e.parentNode.appendChild(g); chipMarks.push(g);
        try { r.setAttribute("width", t.getComputedTextLength() + 16 * k); } catch (x) { /* 글자 폭을 못 재면 어림 폭 */ }
      });
    }
    (function watchChipZoom() {  // 확대·축소(휠·버튼·맞춤)는 여러 길로 오므로 화면 배율을 매 프레임 비교한다(칩이 있을 때만 다시 그림)
      if (chipMarks.length && chipMarks[0].parentNode) {
        var now = chipPx(chipMarks[0]);
        if (Math.abs(now - chipScale) / chipScale > 0.02) chips(chipList);
      }
      requestAnimationFrame(watchChipZoom);
    })();
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
    // ---- S-viewer: 근거 표시(mark·drawPath)와 고르기. 기존 강조(hz-on)·구간 색(inline style)·hz-pick과 클래스를 따로 쓴다. ----
    var idxCache = null, idxObs = null;
    function index() {  // local_id → 요소들. 도면이 바뀌지 않았으면 캐시를 쓴다(ID마다 querySelectorAll을 부르면 O(N²))
      if (idxObs && idxObs.takeRecords().length) idxCache = null;
      if (idxCache) return idxCache;
      var map = Object.create(null);
      ["overlay", "graphsvg"].forEach(function (id) {
        var s = document.getElementById(id); if (!s) return;
        if (!idxObs && window.MutationObserver) idxObs = new MutationObserver(function () { idxCache = null; });
        if (idxObs) idxObs.observe(s, { childList: true, subtree: true });
        var all = s.querySelectorAll("[data-local-id]");
        for (var i = 0; i < all.length; i++) {
          var e = all[i], lid = e.getAttribute("data-local-id");
          if (e.classList.contains("pipe-hit") || e.classList.contains("gedge-hit")) { e = e.nextElementSibling; if (!e) continue; }
          (map[lid] || (map[lid] = [])).push(e);
        }
      });
      if (idxObs) idxObs.takeRecords();
      return (idxCache = map);
    }
    // 웹 → 앱 메시지는 64KB를 넘으면 통째로 버려진다. 목록은 2,000개·글자 수 안으로 잘라 truncated를 단다.
    function capList(msg, key, dropFirst) {
      var cut = false;
      if (msg[key].length > 2000) { msg[key] = msg[key].slice(0, 2000); cut = true; }
      if (JSON.stringify(msg).length > 60000) { (dropFirst || []).forEach(function (k) { msg[k] = []; }); cut = true; }
      while (JSON.stringify(msg).length > 60000 && msg[key].length) { msg[key] = msg[key].slice(0, Math.floor(msg[key].length * 0.8)); cut = true; }
      if (cut) msg.truncated = true;
      return msg;
    }
    function shownRect(e) { var r = e.getBoundingClientRect(); return (r.width || r.height) ? r : null; }
    function isLine(e) { return e.classList.contains("pipe-line") || e.classList.contains("gedge"); }
    var MSTYLE = /^(focus|path|cause|safeguard|warn|muted|seg:\d{1,2})$/;
    function styleClass(st) {
      st = MSTYLE.test(String(st)) ? String(st) : "focus";
      return st.indexOf("seg:") === 0 ? "hz-m-seg" + (Number(st.slice(4)) %% 5 + 1) : "hz-m-" + st;
    }
    var reqs = Object.create(null);  // request_id → {items: [{e, cls}], extras: [노드], dim, style}
    function flush(r) { r.later.forEach(function (x) { x[0].appendChild(x[1]); }); r.later = []; }  // 크기를 잴 때마다 레이아웃이 다시 돌지 않게 붙이기는 맨 끝에
    function dropExtras(r) { r.extras.forEach(function (x) { if (x.parentNode) x.parentNode.removeChild(x); }); r.extras = []; }
    function paintMarks(touched) {  // 남은 요청들로 touched 요소의 표시 클래스를 다시 만든다
      var set = new Set(touched);
      touched.forEach(function (e) {
        Array.prototype.slice.call(e.classList).forEach(function (c) { if (c === "hz-m" || c.indexOf("hz-m-") === 0) e.classList.remove(c); });
      });
      Object.keys(reqs).forEach(function (rid) {
        reqs[rid].items.forEach(function (it) { if (set.has(it.e)) { it.e.classList.add("hz-m"); it.cls.forEach(function (c) { it.e.classList.add(c); }); } });
      });
      document.body.classList.toggle("hz-mdim", Object.keys(reqs).some(function (rid) { return reqs[rid].dim; }));
    }
    function clearMarks(rid) {
      var ids = rid == null ? Object.keys(reqs) : (reqs[rid] ? [rid] : []), touched = [];
      ids.forEach(function (k) { reqs[k].items.forEach(function (it) { touched.push(it.e); }); dropExtras(reqs[k]); delete reqs[k]; });
      paintMarks(touched);
    }
    function newReq(rid, dim) { rid = String(rid == null ? "" : rid); clearMarks(rid); return (reqs[rid] = { items: [], extras: [], later: [], dim: !!dim, style: "path" }); }
    function badge(r, e, text, color) {  // 도면 좌표계 안의 작은 꼬리표(순번·이름)
      var bb; try { bb = e.getBBox(); } catch (x) { return; }
      var g = document.createElementNS(NS, "g"), c = document.createElementNS(NS, "rect"), t = document.createElementNS(NS, "text");
      var w = String(text).length * 8 + 8;
      g.setAttribute("class", "hz-mbadge"); g.setAttribute("pointer-events", "none"); g.style.setProperty("--mc", color);
      c.setAttribute("x", bb.x - 4); c.setAttribute("y", bb.y - 18); c.setAttribute("width", w); c.setAttribute("height", 15); c.setAttribute("rx", 7);
      t.setAttribute("x", bb.x); t.setAttribute("y", bb.y - 7); t.textContent = String(text);
      g.appendChild(c); g.appendChild(t); r.later.push([e.parentNode, g]); r.extras.push(g);
    }
    var COLORS_BY = { focus: "var(--hl-focus)", path: "var(--hl-path)", cause: "var(--hl-cause)", safeguard: "var(--hl-safeguard)", warn: "var(--hl-mwarn)", muted: "var(--hl-muted)" };
    function colorOf(st) { var m = /^seg:(\d+)$/.exec(String(st)); return m ? "var(--seg" + (Number(m[1]) %% 5 + 1) + ")" : (COLORS_BY[st] || COLORS_BY.focus); }
    function doMark(m) {
      var map = index(), r = newReq(m.request_id, m.dim_others !== false), missing = [], ids = [];
      (m.groups || []).forEach(function (g) {
        var cls = [styleClass(g.style)], first = null;
        (g.ids || []).forEach(function (lid) {
          var found = map[lid];
          if (!found) { missing.push(lid); return; }
          ids.push(lid);
          found.forEach(function (e) { r.items.push({ e: e, cls: cls }); if (!first || (!first.classList.contains("sym") && e.classList.contains("sym"))) first = e; });
        });
        if (first && g.label) badge(r, first, g.label, colorOf(g.style));
      });
      flush(r); paintMarks(r.items.map(function (it) { return it.e; }));
      if (m.center) zoomTo(ids, 0.15, map);
      send(capList({ type: "highlightResult", request_id: m.request_id || null, missing: missing }, "missing"));
    }
    function lineGeo(e) {  // 배관 선의 시작점·끝점·가운데와 가운데에서의 진행 각도(도면 좌표)
      if (!e.getTotalLength) return null;
      var L = e.getTotalLength(); if (!(L > 0)) return null;
      var a = e.getPointAtLength(0), b = e.getPointAtLength(L), c = e.getPointAtLength(L / 2);
      var d = e.getPointAtLength(Math.min(L, L / 2 + 2)), p = e.getPointAtLength(Math.max(0, L / 2 - 2));
      return { a: a, b: b, c: c, ang: Math.atan2(d.y - p.y, d.x - p.x) };
    }
    function centerOf(e) { try { var b = e.getBBox(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; } catch (x) { return null; } }
    function arrow(r, e, geo, prevC, nextC, flow) {
      // 경로를 지나가는 방향: 앞 단계에 가까운 끝에서 반대 끝으로(앞이 없으면 뒤 단계 기준, 둘 다 없으면 선이 그려진 방향)
      var fwd = true;
      function dist(p, q) { return Math.hypot(p.x - q.x, p.y - q.y); }
      if (prevC) fwd = dist(prevC, geo.a) <= dist(prevC, geo.b);
      else if (nextC) fwd = dist(nextC, geo.b) <= dist(nextC, geo.a);
      var ang = geo.ang + (fwd ? 0 : Math.PI) + (flow === "against" ? Math.PI : 0);
      var poly = document.createElementNS(NS, "polygon");
      poly.setAttribute("points", "-8,-6 8,0 -8,6");
      poly.setAttribute("transform", "translate(" + geo.c.x + "," + geo.c.y + ") rotate(" + (ang * 180 / Math.PI) + ")");
      poly.setAttribute("class", "hz-marrow"); poly.setAttribute("pointer-events", "none"); poly.style.setProperty("--mc", colorOf(r.style));
      r.later.push([e.parentNode, poly]); r.extras.push(poly);
    }
    function doPath(m) {
      var map = index(), r = newReq(m.request_id, true), missing = [], steps = Array.isArray(m.steps) ? m.steps : [], n = 0;
      r.style = m.style || "path";
      var cls = styleClass(r.style), found = steps.map(function (s) { return map[s.id] || null; });
      function objCenter(j) { var f = found[j], o = f && f.filter(function (e) { return !isLine(e); })[0]; return o ? centerOf(o) : null; }
      steps.forEach(function (s, i) {
        var f = found[i];
        if (!f) { missing.push(s.id); return; }
        var line = f.filter(isLine)[0], obj = f.filter(function (e) { return !isLine(e); });
        f.forEach(function (e) {
          var c = [cls]; if (isLine(e) && s.flow === "unknown") c.push("hz-m-dash");
          r.items.push({ e: e, cls: c });
        });
        if (line && (s.flow === "with" || s.flow === "against")) {
          var geo = lineGeo(line);
          if (geo) arrow(r, line, geo, i > 0 ? objCenter(i - 1) : null, i + 1 < steps.length ? objCenter(i + 1) : null, s.flow);
        }
        if (m.numbered !== false && obj.length) {
          n++; badge(r, obj.filter(function (e) { return e.classList.contains("sym"); })[0] || obj[0], String(n), colorOf(r.style));
        }
      });
      flush(r); paintMarks(r.items.map(function (it) { return it.e; }));
      send(capList({ type: "highlightResult", request_id: m.request_id || null, missing: missing }, "missing"));
    }
    function zoomTo(ids, pad, map) {
      map = map || index();
      var l = Infinity, t = Infinity, rr = -Infinity, bb = -Infinity, v = curView(), vr = vp && vp.getBoundingClientRect();
      if (!v || !vr) return;
      (ids || []).forEach(function (lid) {
        (map[lid] || []).forEach(function (e) {
          var q = shownRect(e); if (!q) return;
          l = Math.min(l, q.left); t = Math.min(t, q.top); rr = Math.max(rr, q.right); bb = Math.max(bb, q.bottom);
        });
      });
      if (!isFinite(l)) return;
      pad = (typeof pad === "number" && pad >= 0 && pad < 5) ? pad : 0.15;
      var dl = (l - vr.left - v.x) / v.s, dt = (t - vr.top - v.y) / v.s, dw = Math.max((rr - l) / v.s, 20), dh = Math.max((bb - t) / v.s, 20);
      var s = Math.min(Math.max(Math.min(vr.width / (dw * (1 + 2 * pad)), vr.height / (dh * (1 + 2 * pad))), 0.1), 12);
      window.hzView.set({ s: s, x: vr.width / 2 - (dl + dw / 2) * s, y: vr.height / 2 - (dt + dh / 2) * s });
    }
    // 고르기: "off"는 템플릿 동작 그대로, "pick"은 클릭 = 더하기·빼기, 끌기 = 네모로 더하기(Alt는 빼기).
    var selMode = "off", sel = new Set(), sdown = null, rubber = null;
    function paintSel(add, rem) {  // 바뀐 것만 칠한다
      var map = index();
      add.forEach(function (lid) { (map[lid] || []).forEach(function (e) { e.classList.add("hz-sel"); }); });
      rem.forEach(function (lid) { (map[lid] || []).forEach(function (e) { e.classList.remove("hz-sel"); }); });
      refreshTags();
    }
    function sendSel(added, removed, via) {
      send(capList({ type: "selectionChanged", selected: Array.from(sel), added: added.slice(0, 2000), removed: removed.slice(0, 2000), via: via },
                   "selected", ["added", "removed"]));
    }
    function change(addIds, removeIds, via) {
      var add = addIds.filter(function (i) { return !sel.has(i); }), rem = removeIds.filter(function (i) { return sel.has(i); });
      if (!add.length && !rem.length) return;
      add.forEach(function (i) { sel.add(i); }); rem.forEach(function (i) { sel.delete(i); });
      paintSel(add, rem);
      sendSel(add, rem, via);
    }
    function lineMostlyIn(e, bx) {
      if (!e.getTotalLength || !e.getScreenCTM) return true;
      var L = e.getTotalLength(), m = e.getScreenCTM(), n = 16, k, inn = 0;
      if (!m || !(L > 0)) return true;
      for (k = 0; k <= n; k++) {
        var p = e.getPointAtLength(L * k / n), x = m.a * p.x + m.c * p.y + m.e, y = m.b * p.x + m.d * p.y + m.f;
        if (x >= bx.l && x <= bx.r && y >= bx.t && y <= bx.b) inn++;
      }
      return inn / (n + 1) >= 0.5;
    }
    function inBox(bx) {  // 네모와 겹치는 구성요소. 기호·태그 상자는 겹치면, 배관은 선의 절반 이상이 안일 때만
      var map = index(), out = [], lid, i;
      for (lid in map) {
        var list = map[lid], hit = false;
        for (i = 0; i < list.length && !hit; i++) {
          var e = list[i], q = shownRect(e);
          if (!q || q.right < bx.l || q.left > bx.r || q.bottom < bx.t || q.top > bx.b) continue;
          hit = isLine(e) ? lineMostlyIn(e, bx) : true;
        }
        if (hit) out.push(lid);
      }
      return out;
    }
    function rubberTo(x0, y0, x1, y1, minus) {
      var r = vp.getBoundingClientRect();
      if (!rubber) { rubber = document.createElement("div"); rubber.className = "hz-rubber"; vp.appendChild(rubber); }
      rubber.classList.toggle("minus", !!minus);
      rubber.style.left = (Math.min(x0, x1) - r.left) + "px"; rubber.style.top = (Math.min(y0, y1) - r.top) + "px";
      rubber.style.width = Math.abs(x1 - x0) + "px"; rubber.style.height = Math.abs(y1 - y0) + "px";
    }
    function endDrag() { if (rubber && rubber.parentNode) rubber.parentNode.removeChild(rubber); rubber = null; sdown = null; }
    if (vp) {
      vp.addEventListener("mousedown", function (e) {
        if (selMode !== "pick" || e.button !== 0 || (e.target.closest && e.target.closest(".float, .hz-legend, .hz-chip"))) return;
        e.stopImmediatePropagation();  // 템플릿의 화면 끌기를 막는다
        sdown = { x: e.clientX, y: e.clientY, t: e.target, moved: false };
      }, true);
      window.addEventListener("mousemove", function (e) {
        if (!sdown) return;
        if (Math.abs(e.clientX - sdown.x) + Math.abs(e.clientY - sdown.y) > 3) sdown.moved = true;
        if (sdown.moved) rubberTo(sdown.x, sdown.y, e.clientX, e.clientY, e.altKey);
      }, true);
      window.addEventListener("mouseup", function (e) {
        var d = sdown; if (!d) return;
        endDrag();
        if (d.moved) {
          var ids = inBox({ l: Math.min(d.x, e.clientX), r: Math.max(d.x, e.clientX), t: Math.min(d.y, e.clientY), b: Math.max(d.y, e.clientY) });
          if (e.altKey) change([], ids, "box_remove"); else change(ids, [], "box");
        } else {
          var t = d.t && d.t.closest ? d.t.closest("#overlay [data-local-id], #graphsvg [data-local-id]") : null;
          if (t) { var lid = t.getAttribute("data-local-id"); if (sel.has(lid)) change([], [lid], "click"); else change([lid], [], "click"); }
        }
      }, true);
      vp.addEventListener("click", function (e) {  // 고르기 중의 클릭은 템플릿 선택·nodeSelected로 새지 않게 한다
        if (selMode === "pick" && !(e.target.closest && e.target.closest(".float, .hz-legend, .hz-chip"))) { e.stopPropagation(); e.preventDefault(); }
      }, true);
      window.addEventListener("keydown", function (e) {
        if (selMode === "pick" && e.key === "Escape" && sel.size) change([], Array.from(sel), "clear");
      });
    }
    function setSelMode(mode) {
      selMode = mode === "pick" ? "pick" : "off";
      document.body.classList.toggle("hz-selmode", selMode === "pick");
      if (selMode !== "pick") endDrag();
    }
    function setSelection(ids) {
      var next = new Set((ids || []).filter(function (i) { return typeof i === "string"; }));
      var add = Array.from(next).filter(function (i) { return !sel.has(i); }), rem = Array.from(sel).filter(function (i) { return !next.has(i); });
      sel = next;
      paintSel(add, rem);
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
        // 도구줄(Qt)에 같은 검증 칩이 있는 화면은 웹 머리줄 칩을 숨긴다(E-2: 한 번만 보이기)
        document.body.classList.toggle("hz-hide-status", !!m.hide_status);
        window.dispatchEvent(new Event("resize"));
      } else if (m.type === "segments") segments(m);
      else if (m.type === "clearSegments") { clearSegments(); segLegend([], 0); }
      else if (m.type === "chips") chips(m.chips);
      else if (m.type === "openPathQuery") { if (window.openPathQuery) window.openPathQuery(); }
      else if (m.type === "toggleLayer") { if (window.hzToggleLayer) window.hzToggleLayer(m.layer); }
      else if (m.type === "mark") doMark(m);
      else if (m.type === "clearMarks") clearMarks(m.request_id);
      else if (m.type === "drawPath") doPath(m);
      else if (m.type === "selectMode") setSelMode(m.mode);
      else if (m.type === "setSelection") setSelection(m.ids);
      else if (m.type === "getSelection") send(capList({ type: "selection", request_id: m.request_id || null, selected: Array.from(sel) }, "selected"));
      else if (m.type === "zoomTo") zoomTo(m.ids, m.pad);
      else if (m.type === "clearHighlight") clear();
      else if (m.type === "focus") focus(m.local_id);
      else if (m.type === "pick") pick(m.local_id, !!m.center);
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


# 뷰어 템플릿의 앱 전용 표시 규칙(색 토큰은 tokens.web_css). ④⑤(hz-hide-panel)에서는 경로 질의를 쓰지 않는다.
VIEWER_CSS = """
body.hz-hide-status #status { display: none; }
body.hz-hide-panel #pq-chip { display: none; }
body.hz-segfocus #overlay .sym:not(.hz-seg-in), body.hz-segfocus #overlay .tagbox:not(.hz-seg-in),
body.hz-segfocus #overlay .pipe-line:not(.hz-seg-in), body.hz-segfocus #graphsvg .gnode:not(.hz-seg-in),
body.hz-segfocus #graphsvg .gedge:not(.hz-seg-in), body.hz-segfocus #graphsvg .glabel,
body.hz-segfocus #taglabels span:not(.hz-seg-in), body.hz-segfocus .segchip:not(.active) { opacity: var(--hl-dim); }
#zoom button svg { vertical-align: middle; }
#zoom .hz-ilabel { margin-left: 4px; vertical-align: middle; }
.hz-chip { cursor: pointer; opacity: 1 !important; }
.hz-chip rect { fill: var(--card); stroke: var(--ui); }
.hz-chip text { fill: var(--ui); font-weight: 700; }
.hz-chip-warn rect { fill: var(--warn-bg); stroke: var(--warn-line); stroke-dasharray: 4 2; }
.hz-chip-warn text { fill: var(--warn-ink); }
.hz-chip:hover rect { fill: var(--line); }
.hz-pick { opacity: 1 !important; stroke: var(--ui) !important; filter: drop-shadow(0 0 3px var(--ui)) drop-shadow(0 0 3px var(--ui));
  animation: hz-pulse 1.2s ease-in-out 3; }
@keyframes hz-pulse { 50% { stroke-width: 7; } }
/* S-viewer: 근거 표시(hz-m*)와 고르기(hz-sel). 기존 강조(hz-on)·구간 색·hz-pick과 클래스가 달라 서로 지우지 않는다. */
.hz-m-focus { --mc: var(--hl-focus); } .hz-m-path { --mc: var(--hl-path); } .hz-m-cause { --mc: var(--hl-cause); }
.hz-m-safeguard { --mc: var(--hl-safeguard); } .hz-m-warn { --mc: var(--hl-mwarn); } .hz-m-muted { --mc: var(--hl-muted); }
.hz-m-seg1 { --mc: var(--seg1); } .hz-m-seg2 { --mc: var(--seg2); } .hz-m-seg3 { --mc: var(--seg3); }
.hz-m-seg4 { --mc: var(--seg4); } .hz-m-seg5 { --mc: var(--seg5); }
.hz-m.sym, .hz-m.tagbox, .hz-m.gnode { stroke: var(--mc) !important; stroke-width: 3.5; fill: var(--mc) !important; fill-opacity: .18 !important; opacity: 1 !important; }
.hz-m.pipe-line, .hz-m.gedge { stroke: var(--mc) !important; stroke-width: 5; stroke-opacity: 1; opacity: 1 !important; }
.hz-m-warn.pipe-line, .hz-m-warn.gedge, .hz-m-dash { stroke-dasharray: 9 6 !important; }
.hz-m-muted.sym, .hz-m-muted.tagbox, .hz-m-muted.gnode { stroke-width: 1.5; fill-opacity: .05 !important; }
.hz-m-muted.pipe-line, .hz-m-muted.gedge { stroke-width: 2.5; stroke-opacity: .6; }
body.hz-mdim #overlay .sym:not(.hz-m), body.hz-mdim #overlay .tagbox:not(.hz-m), body.hz-mdim #overlay .pipe-line:not(.hz-m),
body.hz-mdim #graphsvg .gnode:not(.hz-m), body.hz-mdim #graphsvg .gedge:not(.hz-m) { opacity: var(--hl-dim); }
.hz-mbadge rect { fill: var(--mc); } .hz-mbadge text { fill: var(--on-seg); font-size: 11px; font-weight: 700; }
.hz-marrow { fill: var(--mc); stroke: var(--card); stroke-width: 1; }
body .hz-pick.hz-m, body .hz-pick.hz-sel { stroke: var(--ui) !important; }  /* 고른 태그의 선 색이 표시·고르기에 가려지지 않게 */
.hz-sel.sym, .hz-sel.tagbox, .hz-sel.gnode { stroke: var(--ui) !important; stroke-width: 3.5; fill: rgba(10,95,194,.16) !important; }
.hz-sel.pipe-line, .hz-sel.gedge { stroke: var(--ui) !important; stroke-width: 5; stroke-opacity: 1; }
body.hz-selmode #viewport { cursor: crosshair; }
.hz-rubber { position: absolute; z-index: 20; pointer-events: none; border: 1.5px solid var(--ui); background: rgba(10,95,194,.10); box-sizing: border-box; }
.hz-rubber.minus { border-style: dashed; background: rgba(166,30,77,.08); }
"""


WEB_ICONS = ("zoom-in", "zoom-out", "arrows-maximize")   # 뷰어 확대·축소·맞춤 단추에 넣는 아이콘


def bridge_js():
    web_icons = {n: icons.svg_inline(n, size=16) for n in WEB_ICONS}
    return BRIDGE_JS % {"css": json.dumps(tokens.web_css() + VIEWER_CSS, ensure_ascii=False),
                        "icons": json.dumps(web_icons, ensure_ascii=False)}


class HazopWebView(QWebEngineView):
    """②④⑤가 공유하는 웹뷰 하나. 화면을 바꿀 때 해당 화면의 캔버스 자리로 옮긴다."""

    SELECTION_TIMEOUT_MS = 5000   # selection() 응답을 기다리는 한도

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
        self.hide_status = False
        self.drawing_enabled = True
        self.edit = {"on": False, "tool": "select"}
        self.select_mode = "off"
        self.current_graph_id = ""
        self._selection_waiters = {}
        self._selection_seq = 0
        self.bridge.selectionFor.connect(self._selection_answer)

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

    def load_file(self, path, graph_id=""):
        """뷰어 HTML 파일 로드(Python → 웹 'load'). 같은 경로라도 파일이 다시 만들어졌으면(mtime·크기 변경) 다시 읽는다.
        graph_id는 이 도면의 graph_id로, 읽기를 마치면 bridge.sheetReady(graph_id)로 알린다."""
        path = os.path.abspath(path)
        stamp = self._stamp(path)
        if self.current_file == path and self.current_stamp == stamp:
            if graph_id and graph_id != self.current_graph_id:  # 같은 파일을 graph_id 없이 읽은 뒤 알게 된 경우: 다시 읽지 않고 이름만 붙인다
                self.current_graph_id = self.bridge.graph_id = graph_id
                if self.bridge.is_ready:
                    self.bridge.sheetReady.emit(graph_id)
            return False
        self.current_file = path
        self.current_stamp = stamp
        self.page().allowed_file = path
        self.bridge.reset()
        self.bridge.graph_id = graph_id or ""
        self.current_graph_id = self.bridge.graph_id
        self.bridge.send("setMode", hide_panel=self.hide_panel, hide_graph=self.hide_graph, hide_status=self.hide_status)
        # 도면 탭 잠금은 페이지를 새로 읽을 때마다(loadFinished 후 브리지 ready 시점) 다시 적용한다
        self.bridge.send("setDrawingEnabled", enabled=self.drawing_enabled)
        self.bridge.send("editMode", **self.edit)
        self.bridge.send("selectMode", mode=self.select_mode)
        self.load(QUrl.fromLocalFile(path))
        return True

    def set_drawing_enabled(self, enabled):
        """그래프 버전 불일치 등: 도면 탭을 끄고 그래프 탭만 쓰게 한다. 상태를 기억해 다시 읽을 때도 적용한다."""
        self.drawing_enabled = bool(enabled)
        self.bridge.send("setDrawingEnabled", enabled=self.drawing_enabled)

    def set_mode(self, hide_panel, hide_graph=False, hide_status=False):
        """②: 웹 속성 패널 사용·그래프 탭 숨김(hide_graph), ④⑤: 웹 패널 숨기고 Qt 상세 패널 사용(§2.2).
        hide_status: 도구줄에 같은 검증 칩이 있어 웹 머리줄 검증 칩을 숨긴다(②)."""
        self.hide_panel = bool(hide_panel)
        self.hide_graph = bool(hide_graph)
        self.hide_status = bool(hide_status)
        self.bridge.send("setMode", hide_panel=self.hide_panel, hide_graph=self.hide_graph, hide_status=self.hide_status)

    def set_view(self, view):
        self.bridge.send("setView", view=view)

    def highlight(self, spec):
        self.bridge.send("highlight", **spec)

    def clear_highlight(self):
        self.bridge.send("clearHighlight")

    def set_segments(self, groups, uncovered=()):
        """④ 검토구간 색. groups = [{"color", "active", "label"(S 번호), "ids": [local_id]}] 순서대로, 한 요소는 첫 구간 색만.
        active인 구간이 있으면 그 구간만 칠하고 나머지는 흐리게, 없으면 모든 구간을 칠한다.
        uncovered = 어느 구간에도 없는 요소의 local_id(점선, 전체 보기에서만)."""
        self.bridge.send("segments", groups=list(groups), uncovered=list(uncovered))

    def clear_segments(self):
        self.bridge.send("clearSegments")

    def set_chips(self, chips):
        """②④ 도면 연결점 칩 [{"local_id", "text", "key", "kind": "link"|"unlinked", "tip", "row"}]. 빈 목록이면 지운다.
        누르면 bridge.chipClicked(key)."""
        self.bridge.send("chips", chips=[dict(c) for c in chips if c.get("local_id")])

    def focus(self, local_id):
        self.bridge.send("focus", local_id=local_id)

    def pick(self, local_id, center=False):
        """④ 고른 구성요소 하나를 따로 강조한다(None이면 지움). center면 가운데로 옮겨 확대한다."""
        self.bridge.send("pick", local_id=local_id, center=bool(center))

    def open_path_query(self):
        """도면 뷰어의 접힌 경로 질의 상자를 연다(② 명령 팔레트)."""
        self.bridge.send("openPathQuery")

    def toggle_layer(self, layer):
        """도면 오버레이 층(symbol·pipe·tag)을 켜고 끈다."""
        self.bridge.send("toggleLayer", layer=layer)

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

    # ---- S-viewer 뷰어 API (docs/specs/chat-panel.md §6.1). ID는 모두 이 도면 안 local_id ----

    @staticmethod
    def _groups(groups):
        out = []
        for g in groups or []:
            ids = [i for i in (g.get("ids") or []) if isinstance(i, str)]
            label = g.get("label")
            out.append({"ids": ids, "style": g.get("style") or "focus", "label": label if isinstance(label, str) else None})
        return out

    def mark(self, request_id, groups, dim_others=True, center=False):
        """구성요소 묶음을 스타일(focus|path|cause|safeguard|warn|muted|seg:<n>)별로 겹쳐 그린다. 기존 강조·구간 색·고른 것은 지우지 않는다.
        응답은 bridge.highlightResultFor(request_id, 그리지 못한 local_id)."""
        self.bridge.send("mark", request_id=request_id, groups=self._groups(groups), dim_others=bool(dim_others), center=bool(center))

    def clear_marks(self, request_id=None):
        """mark·draw_path로 그린 것을 지운다(None이면 전부). 구간 색(segments)·고른 것(pick)은 지우지 않는다."""
        self.bridge.send("clearMarks", request_id=request_id)

    def draw_path(self, request_id, steps, style="path", numbered=True):
        """경로를 배관 선과 기호 강조로 그린다. steps = [{"id", "flow": "with"|"against"|"unknown"|None}] 경로 순서(객체·배관 섞임).
        객체에 순번 배지, 흐름이 확인된 배관에 화살표, unknown 배관은 점선."""
        clean = [{"id": s["id"], "flow": s.get("flow")} for s in steps or [] if isinstance(s, dict) and isinstance(s.get("id"), str)]
        self.bridge.send("drawPath", request_id=request_id, steps=clean, style=style, numbered=bool(numbered))

    def set_select_mode(self, mode):
        """"off"(끌기 = 화면 이동, 기존 동작) | "pick"(클릭 = 더하기·빼기, 끌기 = 네모로 더하기, Alt+끌기 = 네모로 빼기).
        상태를 기억해 다시 읽을 때도 적용한다."""
        self.select_mode = "pick" if mode == "pick" else "off"
        self.bridge.send("selectMode", mode=self.select_mode)

    def set_selection(self, ids):
        """고른 것 표시를 이 목록으로 바꾼다(selectionChanged를 내지 않는다)."""
        self.bridge.send("setSelection", ids=[i for i in ids or [] if isinstance(i, str)])

    def selection(self, callback):
        """지금 고른 local_id 목록을 callback으로 넘긴다(페이지가 준비되지 않았으면 빈 목록)."""
        if not self.bridge.is_ready:
            callback([])
            return
        self._selection_seq += 1
        rid = "sel-%d" % self._selection_seq
        self._selection_waiters[rid] = callback
        self.bridge.send("getSelection", request_id=rid)
        QTimer.singleShot(self.SELECTION_TIMEOUT_MS, lambda: self._selection_answer(rid, []))  # 끝내 답이 없으면 빈 목록

    @property
    def selection_truncated(self):
        """마지막 selection() 응답이 2,000개·메시지 크기 때문에 잘렸는지."""
        return self.bridge.selection_truncated

    def _selection_answer(self, rid, ids):
        cb = self._selection_waiters.pop(rid, None)
        if cb:
            cb(ids)

    def zoom_to(self, ids, pad=0.15):
        """ids를 모두 담도록 화면을 옮기고 확대한다. pad는 둘레 여유 비율."""
        self.bridge.send("zoomTo", ids=[i for i in ids or [] if isinstance(i, str)], pad=float(pad))
