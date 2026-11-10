"""③ 지식그래프 화면 검사 (기획서/그래프활용.md §5·§7.2 V1·V2·S1, 디자인/지식그래프화면.md). 네트워크·AI 호출 없음.

입력은 저장소 안 샘플만 쓴다: 샘플 도면 SNP-M-102를 임시 폴더에서 추출·그래프 빌드(tests/test_kg.pid_graph와 같은 방식),
데이터/지식/SNP-SAMPLE CSV로 지식그래프 빌드, 데이터/구간 구간 JSON, link_candidates.csv. 출력/ 폴더에 의존하지 않는다.

1) V2 오프라인: 생성 HTML(단독·앱 셸)에서 vendor 본문을 뺀 생성 부분에 외부 URL 없음, vendor URL은 허용 목록,
   vendor SHA-256 = SOURCE.md 기록, LICENSE 있음, <script src> 없음(scripts/check_kg_renderer.py 규칙 재사용)
2) 렌더링: HazopWebView(외부 요청 차단 설정 그대로)로 단독 HTML을 열어 페이지 오류·Qt 콘솔 error 0건, canvas 픽셀 > 0,
   노드·관계 수 = 화면 데이터, 로컬이 아닌 요청 시도 0건
3) V1: 후보·미확인·가설 표시를 끈 상태에서 웹 로컬 보기(깊이 1~3)의 표시 노드 집합 = Python V5 ego_graph(algo.a4_ego)
4) S1: 합성 5,001노드(check_kg_algo.synthetic)에서 화면 데이터 s1=true, 웹 경고 표시, ③ 화면 경고 띠. 5,000노드는 경고 없음
5) ③ 탭: 임시 작업 루트(HAZOP_WORK_ROOT·HAZOP_STORE_ROOT 모두 임시)에서 주 창을 열고 ③으로 이동 → loadKnowledge 수신,
   노드 클릭 → Qt 상세 패널, runAlgorithm(A1) → algorithmResult, 1366×768에서 창 최소 폭·캔버스·상세 폭 확인
6) tests/test_kg_screen.py
옵션 --screenshots <폴더>: ③ 화면을 1440×860·1366×768로 찍어 저장(기본은 찍지 않음).
종료 코드 0 = 전부 통과.
"""

import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402

import check_kg  # noqa: E402
import check_kg_algo  # noqa: E402
import check_kg_renderer as kr  # noqa: E402
import extract_drawio  # noqa: E402
from hazop.graph import build as gbuild  # noqa: E402
from hazop.kg import build, screen  # noqa: E402

SAMPLE_PROJECT = "SNP-SAMPLE"
SAMPLE_DIR = paths.folder_in(REPO_ROOT, "samples", "knowledge-graph", SAMPLE_PROJECT)  # 묶음 검사에서는 REPO_ROOT = 검사 입력 사본
REGION_FILE = check_kg_algo.REGION_FILE
DRAWING = "SNP-M-102"
V1_CASES = (("entity-node-001", (1, 2, 3)), ("entity-node-008", (1, 2, 3)), ("entity-seg-004", (1, 2)),
            ("req-001", (1, 2, 3)), ("chunk-003", (1, 2)), ("entity-node-018", (1, 3)))
PROTO_IDS = {"entity-node-003": "constructor", "entity-seg-002": "__proto__", "entity-node-009": "toString",
             "req-001": "hasOwnProperty"}  # JS 프로토타입 키와 같은 ID(일반 객체를 표로 쓰면 BFS에서 빠짐)
PROTO_CASES = (("entity-node-001", (1, 2, 3)), ("__proto__", (1, 2)), ("constructor", (1, 2)), ("toString", (1, 2)),
               ("hasOwnProperty", (1, 2)))
_CACHE = {}


# ---------------------------------------------------------------- 샘플 입력
def sample_graph():
    """샘플 도면을 임시 폴더에서 추출·빌드(원본 위치 그대로 읽으므로 graph_version이 샘플 CSV의 기록과 같다)."""
    if "graph" not in _CACHE:
        # 저장소에서는 참고 폴더, 묶음 검사의 입력 사본(verify_bundle.make_inputs)에서는 기록 경로 자리에 샘플 도면이 있다
        found = (glob.glob(paths.folder_in(REPO_ROOT, "references", "pid-samples", "*", "*.drawio"))
                 or glob.glob(paths.logical_dir(REPO_ROOT, "references", "pid-samples", "*", "*.drawio")))
        drawio = [p for p in found
                  if os.path.basename(os.path.dirname(p)).startswith(DRAWING)][0]
        tmp = tempfile.mkdtemp(prefix="kg-screen-graph-")
        try:
            ex, _ = extract_drawio.run_one(drawio, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        _CACHE["graph"] = gbuild.build_graph(ex)
    return json.loads(json.dumps(_CACHE["graph"]))


def sample_inputs():
    """{"knowledge", "kg", "graph", "regions", "candidates"} — 정상 샘플(가상 자료)."""
    graph = sample_graph()
    knowledge = check_kg.load_dir(SAMPLE_DIR, SAMPLE_PROJECT)
    kg = build.build_kg(knowledge, [graph])
    with open(REGION_FILE, "rb") as fh:
        raw = fh.read()
    regions = [(os.path.basename(REGION_FILE), json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest())]
    return {"knowledge": knowledge, "kg": kg, "graph": graph, "regions": regions,
            "candidates": screen.read_candidates(SAMPLE_DIR)}


def prepare_work_root(work, inp):
    """임시 작업 루트에 화면 입력을 둔다(inp = sample_inputs(), 작업 루트를 바꾸기 전에 만든 것): 출력/그래프/<도면>/graph.json, 출력/지식그래프/kg-…(write_outputs),
    데이터/지식/<project>/link_candidates.csv, 데이터/구간/<구간>.json."""
    gdir = paths.output_in(work, "graph", DRAWING)
    os.makedirs(gdir, exist_ok=True)
    with open(os.path.join(gdir, "graph.json"), "w", encoding="utf-8") as fh:
        json.dump(inp["graph"], fh, ensure_ascii=False)
    build.write_outputs(paths.output_in(work, "knowledge-graph", inp["kg"]["kg_id"]), inp["knowledge"], inp["kg"])
    kdir = paths.folder_in(work, "knowledge-graph", SAMPLE_PROJECT)
    os.makedirs(kdir, exist_ok=True)
    shutil.copy(os.path.join(SAMPLE_DIR, screen.CANDIDATES_CSV), kdir)
    rdir = paths.folder_in(work, "regions")
    os.makedirs(rdir, exist_ok=True)
    shutil.copy(REGION_FILE, rdir)
    return inp


def proto_inputs(inp):
    """샘플의 일부 ID를 PROTO_IDS로 바꾼 (kg, graph) 사본(검사 전용). JSON 문자열에서 따옴표로 감싼 ID만 바꾼다."""
    def ren(obj):
        text = json.dumps(obj, ensure_ascii=False)
        for old, new in PROTO_IDS.items():
            text = text.replace('"%s"' % old, '"%s"' % new)
        return json.loads(text)
    return ren(inp["kg"]), ren(inp["graph"])


def synthetic_inputs(total):
    """합성 그래프(check_kg_algo.synthetic, 가상 구조) — S1 상한 확인용."""
    graph, kg, regions = check_kg_algo.synthetic(total, graph_id="graph-SYN-S1")
    return graph, kg, regions


# ---------------------------------------------------------------- 웹뷰
class Page:
    """HazopWebView(앱과 같은 차단 설정)에 콘솔 기록만 더해 HTML 파일을 연다(check_kg_renderer.render와 같은 방식)."""

    def __init__(self, html, workdir, size=(1100, 700)):
        from hazop.app import make_application, webview
        make_application(["check_kg_screen"])
        self.path = os.path.join(workdir, "kg-screen-%d.html" % int(time.monotonic() * 1000))
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(html)
        original = webview.LocalPage
        webview.LocalPage = kr._probe_page_class()
        try:
            self.view = webview.HazopWebView()
        finally:
            webview.LocalPage = original
        self.view.resize(*size)
        self.view.show()
        self.before = len(self.view.interceptor.blocked)
        self.view.load_file(self.path)

    def js(self, expr, timeout=10.0):
        return kr.js_value(self.view, expr, timeout)

    def wait_ready(self, timeout=60.0):
        ok = kr.pump_until(lambda: self.js("window.hzKG && window.hzKG.ready === true") is True, timeout)
        kr.pump_until(lambda: False, 1.5)  # 첫 프레임들이 그려지도록 잠시 더 돈다
        return ok

    def state(self):
        s = self.js("JSON.stringify(window.hzKG ? window.hzKG.state() : null)")
        return json.loads(s) if s else None

    def close(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        self.view.dispose()
        self.view.close()
        self.view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QCoreApplication.processEvents()


NET_PROBE = """(function () {
  var out = [], LOCAL = {"file:": 1, "data:": 1, "blob:": 1, "about:": 1, "qrc:": 1};
  function chk(u) { try { var p = new URL(String(u), location.href).protocol; if (!LOCAL[p]) out.push(String(u)); } catch (e) {} }
  Array.prototype.forEach.call(document.querySelectorAll("[src],[href]"), function (el) {
    ["src", "href"].forEach(function (a) { var v = el.getAttribute(a); if (v) chk(v); }); });
  (performance.getEntriesByType("resource") || []).forEach(function (e) { chk(e.name); });
  return JSON.stringify(out);
})()"""


def render_problems(page, data):
    """렌더링 판정(빈 목록이면 통과): 준비·오류·콘솔·픽셀·수·요청."""
    p = []
    if not page.wait_ready():
        p.append("hzKG.ready 미도달(시간 초과)")
    st = page.state() or {}
    if st.get("errors"):
        p.append("페이지 오류: %r" % st["errors"])
    cons = [c for c in page.view.page().console if c.get("level") == "error"]
    if cons:
        p.append("Qt 콘솔 오류: %r" % cons)
    painted = page.js("window.hzKG.painted()")
    if not painted or painted <= 0:
        p.append("canvas에 그려진 픽셀 없음(%r)" % painted)
    if st.get("nodes") != len(data["nodes"]):
        p.append("노드 수 불일치: 웹 %s, 데이터 %d" % (st.get("nodes"), len(data["nodes"])))
    net = json.loads(page.js(NET_PROBE) or "[]")
    if net:
        p.append("로컬이 아닌 주소 참조·요청: %r" % net)
    blocked = page.view.interceptor.blocked[page.before:]
    if blocked:
        p.append("외부 요청 시도(가로채기 기록): %r" % blocked)
    if page.view.page().blocked_navigation:
        p.append("탐색 차단 기록: %r" % page.view.page().blocked_navigation)
    return p, st, painted


def v1_problems(page, kg, graph, cases=V1_CASES):
    """V1: 웹 로컬 보기 표시 노드 = Python V5 ego_graph. 표시 토글(후보·미확인·가설·재확인·구간 접기)은 끈다."""
    probs, n = [], 0
    page.js("window.hzKG.setToggles({showCand: false, showExcl: false, showRechk: false, fold: false}), 1")
    for center, depths in cases:
        for d in depths:
            page.js("window.hzKG.setLocal(%s, %d), 1" % (json.dumps(center), d))
            web = json.loads(page.js("JSON.stringify(window.hzKG.visibleIds())") or "[]")
            py = sorted(screen.ego_nodes(kg, graph, center, d))
            n += 1
            if web != py:
                probs.append("%s 깊이 %d: 웹만 %s, Python만 %s" % (center, d, sorted(set(web) - set(py)),
                                                               sorted(set(py) - set(web))))
    page.js("window.hzKG.setGlobal(), 1")
    return probs, n


def html_problems(html):
    """V2 정적 검사(check_kg_renderer.url_violations) + <script src> 금지."""
    bad = kr.url_violations(html, kr.vendor_text())
    if "<script src" in html.lower():
        bad.append("<script src> 있음(인라인만 허용)")
    return bad


# ---------------------------------------------------------------- 주 창(③ 탭)
class TempRoots:
    """HAZOP_WORK_ROOT·HAZOP_STORE_ROOT를 임시 폴더로 바꾸고 끝나면 되돌린다(실제 자료저장소·출력 미사용)."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="kg-screen-app-")
        self.work = os.path.join(self.tmp, "work")
        self.old = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}

    def __enter__(self):
        os.environ["HAZOP_WORK_ROOT"] = self.work
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(self.tmp, "store")
        os.makedirs(self.work)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)


def open_window(settings_dir, size=(1440, 860)):
    from hazop.app import make_application
    make_application(["check_kg_screen"])
    from hazop.app.main_window import MainWindow
    win = MainWindow(settings_path=os.path.join(settings_dir, "settings.json"), ask_reviewer=False)
    win.resize(*size)
    win.show()
    return win


def knowledge_index():
    from hazop.app.main_window import STEPS
    return STEPS.index("③ 지식그래프")


def wait_knowledge(win, timeout=60.0):
    """③ 웹 페이지가 loadKnowledge를 받아 그릴 때까지."""
    def ready():
        v = kr.js_value(win.webview, "window.hzKG && window.hzKG.ready === true", 5)
        return v is True
    ok = kr.pump_until(ready, timeout)
    kr.pump_until(lambda: False, 1.0)
    return ok


def close_window(win):
    from PySide6.QtCore import QCoreApplication, QEvent
    win.close()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()


def tab_problems(win, inp):
    """③ 탭 열기·클릭·A1 재실행·1366×768 배치. (문제 목록, 측정값)."""
    p, info = [], {}
    win.go(knowledge_index())
    scr = win.current_screen()
    if scr.title != "③ 지식그래프":
        p.append("③ 탭으로 이동하지 않음")
        return p, info
    if not win.step_buttons[knowledge_index()].isChecked():
        p.append("③ 단계 탭이 선택 상태가 아님")
    if not wait_knowledge(win):
        p.append("③ 웹 페이지 준비 안 됨(loadKnowledge 미수신)")
        return p, info
    st = json.loads(kr.js_value(win.webview, "JSON.stringify(window.hzKG.state())") or "{}")
    info["web_state"] = st
    if st.get("nodes") != len(scr.data["nodes"]) or not st.get("app") or st.get("errors"):
        p.append("웹 상태 이상: %r" % st)
    painted = kr.js_value(win.webview, "window.hzKG.painted()")
    info["painted"] = painted
    if not painted or painted <= 0:
        p.append("③ canvas 픽셀 없음")
    if not kr.js_value(win.webview, "document.getElementById('legend').classList.contains('min')"):
        p.append("③ 범례가 처음부터 펼쳐짐(U-12: 기본 접힘)")
    fit_lines = kr.js_value(win.webview, "(function(){var r=document.createRange();"
                                         "r.selectNodeContents(document.getElementById('z-fit'));return r.getClientRects().length;})()")
    if fit_lines != 1:
        p.append("③ '맞춤' 버튼 글자가 %s줄(K-5: 한 줄)" % fit_lines)
    if scr.data["meta"]["kg_version"] != inp["kg"]["kg_version"]:
        p.append("kg_version 칩 데이터 불일치")
    if scr.chips["valid"].isHidden() or not scr.chips["valid"].text():
        p.append("도구줄 검증 칩 비어 있음")
    if scr.info_chip.isHidden() or inp["kg"]["kg_version"] not in scr.info_chip.toolTip():
        p.append("버전 정보 칩 툴팁에 kg_version 없음")
    bar = " ".join(w.text() for w in list(scr.chips.values()) + [scr.info_chip] if not w.isHidden())
    if "kg_version" in bar or "graph_version" in bar or inp["kg"]["kg_version"] in bar:
        p.append("도구줄 글자에 내부 버전 해시가 보임(U-15): %s" % bar)
    if scr.detail_stack.currentWidget() is not scr.detail_empty or ":\\" in scr.detail_empty.text():
        p.append("선택 전 상세 패널이 빈 상태 안내가 아니거나 파일 경로를 보임(K-2)")
    # 노드 클릭(웹 → nodeSelected) → Qt 상세
    win.webview.page().runJavaScript("window.hzKG.handle({type:'selectNode', id:'entity-node-001'});")
    win.webview.bridge.fromWeb(json.dumps({"type": "nodeSelected", "local_id": "local-node-001",
                                           "entity_id": "entity-node-001"}))
    text = scr.detail.toPlainText()
    if "RC-PZ01" not in text or "연결 목록" not in text:
        p.append("노드 선택 후 Qt 상세 패널에 속성·연결 목록 없음")
    if not scr.goto_btn.isEnabled():
        p.append("P&ID 노드인데 '도면에서 보기' 비활성")
    # 지식 노드 상세(근거)
    win.webview.bridge.fromWeb(json.dumps({"type": "nodeSelected", "local_id": None, "entity_id": "setpt-001"}))
    text = scr.detail.toPlainText()
    if "근거(출처)" not in text or "MAT-KG-001" not in text or "충돌" not in text:
        p.append("지식 노드 상세에 근거·충돌 없음")
    # runAlgorithm(A1) → algorithmResult
    win.webview.bridge.fromWeb(json.dumps({"type": "runAlgorithm", "algorithm": "A1", "start": "entity-node-008"}))
    ok = kr.pump_until(lambda: kr.js_value(win.webview, "window.hzKG.state().a1start", 5) == "entity-node-008", 20)
    if not ok:
        p.append("runAlgorithm(A1) 결과가 웹에 반영되지 않음(algorithmResult)")
    # 1366×768 배치
    win.showNormal()
    win.resize(1366, 768)
    kr.pump_until(lambda: False, 1.0)
    info["min_width"] = win.minimumSizeHint().width()
    info["window"] = [win.width(), win.height()]
    info["canvas"] = [scr.canvas_host.width(), scr.canvas_host.height()]
    info["detail"] = scr.detail_box.width()
    if win.width() > 1366 or info["min_width"] > 1366:
        p.append("1366 폭에 맞지 않음: 창 %d, 최소 폭 %d" % (win.width(), info["min_width"]))
    if not (320 <= info["detail"] <= 420):
        p.append("상세 패널 폭 %d가 clamp(320, 24vw, 420) 밖" % info["detail"])
    if info["canvas"][0] < 600 or info["canvas"][1] < 300:
        p.append("1366×768에서 캔버스가 너무 작음: %r" % info["canvas"])
    web_left = kr.js_value(win.webview, "document.getElementById('left').getBoundingClientRect().width")
    info["web_left"] = web_left
    if not web_left or not (232 <= web_left <= 300):
        p.append("좌측 필터 폭 %r가 clamp(232, 18vw, 300) 밖" % web_left)
    return p, info


def s1_window_problem(win):
    """③ 화면 S1 띠가 보이는지(합성 5,001노드 지식그래프를 연 상태)."""
    scr = win.current_screen()
    msg = scr.s1_band.label.text()
    return [] if (not scr.s1_band.isHidden() and "상한 초과" in msg and "5,001" in msg) else \
        ["③ S1 경고 띠 없음: %r" % msg]


def write_synthetic_kg(work, total):
    """합성 그래프·지식그래프(가상)를 임시 작업 루트 출력/ 아래에 둔다(S1 확인용)."""
    graph, kg, regions = synthetic_inputs(total)
    gdir = paths.output_in(work, "graph", "SYN-S1")
    os.makedirs(gdir, exist_ok=True)
    with open(os.path.join(gdir, "graph.json"), "w", encoding="utf-8") as fh:
        json.dump(graph, fh)
    kg = dict(kg, kg_id="kg-SYN-S1", project_id="SYN-S1", kg_version="v-5e1000000001")  # 포인터 형식(build D10)
    kg_root = paths.output_in(work, "knowledge-graph", "kg-SYN-S1")
    ver = os.path.join(kg_root, kg["kg_version"])
    os.makedirs(ver, exist_ok=True)
    kb = build.dump_bytes({})
    kg["knowledge_sha256"] = hashlib.sha256(kb).hexdigest()
    gb = build.dump_bytes(kg)
    with open(os.path.join(ver, build.KNOWLEDGE_FILE), "wb") as fh:
        fh.write(kb)
    with open(os.path.join(ver, build.KG_FILE), "wb") as fh:
        fh.write(gb)
    build.write_json_atomic(os.path.join(kg_root, build.POINTER_FILE),
                            {"kg_id": kg["kg_id"], "kg_version": kg["kg_version"],
                             "knowledge_sha256": hashlib.sha256(kb).hexdigest(),
                             "knowledge_graph_sha256": hashlib.sha256(gb).hexdigest()})
    return kg


def take_screenshots(out_dir):
    """③ 화면 스크린샷 2장(1440×860, 1366×768). 임시 작업·저장 루트에서 샘플로 만든다."""
    files = []
    os.makedirs(out_dir, exist_ok=True)
    inp = sample_inputs()  # 작업 루트를 바꾸기 전에 만든다(추출 기록 경로가 graph_version에 들어감)
    with TempRoots() as roots:
        prepare_work_root(roots.work, inp)
        win = open_window(roots.tmp)
        try:
            win.go(knowledge_index())
            wait_knowledge(win)
            kr.pump_until(lambda: False, 4.0)
            win.webview.page().runJavaScript("document.getElementById('z-fit').click();")
            win.webview.bridge.fromWeb(json.dumps({"type": "nodeSelected", "local_id": "local-node-001",
                                                   "entity_id": "entity-node-001"}))
            win.webview.page().runJavaScript("window.hzKG.handle({type:'selectNode', id:'entity-node-001'});")
            kr.pump_until(lambda: False, 1.5)
            for name, size in (("03-knowledge.png", (1440, 860)), ("03-knowledge-1366.png", (1366, 768))):
                win.showNormal()
                win.resize(*size)
                kr.pump_until(lambda: False, 1.2)
                win.webview.page().runJavaScript("document.getElementById('z-fit').click();")
                kr.pump_until(lambda: False, 1.2)
                path = os.path.join(out_dir, name)
                win.grab().save(path)
                files.append(os.path.abspath(path))
        finally:
            close_window(win)
    return files


# ---------------------------------------------------------------- 실행
def ok(label, cond, failures):
    print("  [%s] %s" % ("OK" if cond else "FAIL", label))
    if not cond:
        failures.append(label)


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--screenshots", help="③ 화면 스크린샷을 저장할 폴더")
    ap.add_argument("--skip-tests", action="store_true", help="tests/test_kg_screen.py 생략")
    args = ap.parse_args(argv)
    failures = []
    inp = sample_inputs()
    kg, graph = inp["kg"], inp["graph"]
    data = screen.screen_data(kg, graph, inp["regions"], inp["candidates"])
    m = data["meta"]
    print("샘플: %s %s, 도면 %s %s, 노드 %d·관계 %d(후보 표시 %d), 검증 %s"
          % (m["kg_id"], m["kg_version"], m["graph_id"], m["graph_version"], len(data["nodes"]), len(data["links"]),
             m["candidates"]["shown"], m["status"]))

    print("1) V2 오프라인(정적)")
    rec = kr.recorded_hashes()
    got = kr.sha256(kr.VENDOR_JS)
    ok("vendor force-graph.min.js SHA-256 = SOURCE.md 기록 (%s)" % got, got == rec.get("force-graph.min.js"), failures)
    ok("vendor LICENSE SHA-256 일치·존재", os.path.isfile(kr.VENDOR_LICENSE) and
       kr.sha256(kr.VENDOR_LICENSE) == rec.get("LICENSE"), failures)
    for label, html in (("단독 HTML(데이터 포함)", screen.build_html(data)), ("앱 셸 HTML", screen.build_html(None))):
        bad = html_problems(html)
        ok("%s: 생성 부분 외부 URL·<script src> 없음, vendor URL 허용 목록 대조%s"
           % (label, (" — %r" % bad) if bad else ""), not bad, failures)

    with tempfile.TemporaryDirectory(prefix="kg-screen-") as tmp:
        print("2) 렌더링(HazopWebView, 외부 요청 차단)")
        page = Page(screen.build_html(data), tmp)
        try:
            probs, st, painted = render_problems(page, data)
            print("     노드 %s·관계 %s, 표시 %s·%s, 그린 픽셀 %s, 페이지 오류 %d, Qt 콘솔 %d"
                  % (st.get("nodes"), st.get("links"), st.get("visible"), st.get("visibleLinks"), painted,
                     len(st.get("errors") or []), len(page.view.page().console)))
            ok("샘플 단독 HTML 렌더링%s" % ((" — " + "; ".join(probs)) if probs else ""), not probs, failures)
            print("3) V1 JS 로컬 깊이 = Python ego_graph(V5)")
            probs, n = v1_problems(page, kg, graph)
            ok("%d건(노드 %d개 × 깊이) 일치%s" % (n, len(V1_CASES), (" — " + "; ".join(probs)) if probs else ""),
               not probs, failures)
            kg_p, graph_p = proto_inputs(inp)
            d_p = screen.screen_data(kg_p, graph_p, inp["regions"], None)
            page.js("window.hzKG.handle(%s), 1" % json.dumps({"type": "loadKnowledge", "data": d_p}))
            kr.pump_until(lambda: page.js("window.hzKG.ready === true") is True, 30)
            probs, n = v1_problems(page, kg_p, graph_p, PROTO_CASES)
            ok("프로토타입 이름 ID(%s) %d건 일치%s" % (", ".join(sorted(PROTO_IDS.values())), n,
                                               (" — " + "; ".join(probs)) if probs else ""), not probs, failures)
            page.js("window.hzKG.handle(%s), 1" % json.dumps({"type": "loadKnowledge", "data": data}))
            kr.pump_until(lambda: page.js("window.hzKG.ready === true") is True, 30)
            page.js("window.hzKG.setToggles({showCand: true, showExcl: true}), 1")
            page.js("window.hzKG.setLocal('entity-node-001', 1), 1")
            extra = json.loads(page.js("JSON.stringify(window.hzKG.visibleIds())") or "[]")
            ok("표시 토글을 켜면 계산 제외 항목(case-001, 후보 대상 chunk-002)이 추가로 보임(표시만)",
               "case-001" in extra and "chunk-002" in extra, failures)
        finally:
            page.close()

        print("4) S1 전역 노드 상한(%d)" % screen.NODE_LIMIT)
        for total, expect in ((screen.NODE_LIMIT + 1, True), (screen.NODE_LIMIT, False)):
            g2, k2, r2 = synthetic_inputs(total)
            d2 = screen.screen_data(k2, g2, r2, None)
            ok("합성 %d노드: 전역 노드 %d, s1=%s (기대 %s)" % (total, d2["meta"]["global_count"], d2["meta"]["s1"], expect),
               d2["meta"]["s1"] is expect and d2["meta"]["global_count"] == total, failures)
            if expect:
                t0 = time.monotonic()
                page = Page(screen.build_html(d2), tmp)
                try:
                    probs, st, painted = render_problems(page, d2)
                    shown = page.js("document.getElementById('s1').style.display !== 'none' && "
                                    "document.getElementById('s1').textContent")
                    ok("웹 경고 표시 '%s', 렌더링 %.1f s%s" % (shown, time.monotonic() - t0,
                                                         (" — " + "; ".join(probs)) if probs else ""),
                       bool(shown) and "로컬 보기 권장" in shown and not probs, failures)
                finally:
                    page.close()

    print("5) ③ 탭(임시 작업·저장 루트)")
    with TempRoots() as roots:
        prepare_work_root(roots.work, inp)
        win = open_window(roots.tmp)
        try:
            probs, info = tab_problems(win, inp)
            print("     창 %s, 최소 폭 %s, 캔버스 %s, 상세 폭 %s, 좌측 필터 %s, 픽셀 %s"
                  % (info.get("window"), info.get("min_width"), info.get("canvas"), info.get("detail"),
                     info.get("web_left"), info.get("painted")))
            ok("③ 열기·노드 상세·A1 재실행·1366×768 배치%s" % ((" — " + "; ".join(probs)) if probs else ""), not probs,
               failures)
            write_synthetic_kg(roots.work, screen.NODE_LIMIT + 1)
            scr = win.current_screen()
            scr.on_enter()
            i = scr.kg_combo.findText("kg-SYN-S1")
            scr.kg_combo.setCurrentIndex(i)
            probs = s1_window_problem(win)
            ok("③ S1 경고 띠(합성 5,001노드)%s" % ((" — " + "; ".join(probs)) if probs else ""), not probs, failures)
        finally:
            close_window(win)

    if args.screenshots:
        print("스크린샷")
        for f in take_screenshots(args.screenshots):
            print("    ", f)

    if not args.skip_tests:
        print("6) tests/test_kg_screen.py")
        suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_kg_screen")
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        ok("단위·Qt 테스트 %d개" % result.testsRun, result.wasSuccessful(), failures)

    print("결과: %s" % ("통과" if not failures else "실패 %d건: %s" % (len(failures), failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
