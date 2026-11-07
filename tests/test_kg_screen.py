"""③ 지식그래프 화면 테스트 (기획서/그래프활용.md §5·§7.2 V1·V2·S1, 인터페이스.md §2.3·§3.5, 디자인/지식그래프화면.md).
실행: python -m unittest discover -s tests -t .

입력은 저장소 샘플만 쓴다(scripts/check_kg_screen.sample_inputs: 샘플 도면을 임시 폴더에서 추출·빌드, 정상 샘플 CSV).
창 테스트는 HAZOP_WORK_ROOT·HAZOP_STORE_ROOT를 임시 폴더로 바꿔 출력/·자료저장소/를 건드리지 않는다.
웹뷰는 QT_QPA_PLATFORM=offscreen. 네트워크 사용 없음.
"""

import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from scripts import check_kg_renderer as kr  # noqa: E402
from scripts import check_kg_screen as ks  # noqa: E402
from hazop.kg import algo, build, screen  # noqa: E402

_INP = {}


def inputs():
    """정상 샘플 사본. 작업 루트를 바꾸기 전에 한 번 만든다(추출 기록 경로가 graph_version에 들어감)."""
    if not _INP:
        _INP.update(ks.sample_inputs())
    return copy.deepcopy(_INP)


def tearDownModule():
    """남은 창·웹뷰 페이지를 인터프리터 종료 전에 정리한다(tests/test_app.py와 같은 방식)."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from hazop.app.webview import HazopWebView
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        if isinstance(w, HazopWebView):
            w.dispose()
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()


# ---------------------------------------------------------------- 화면 데이터(계산은 Python)
class ScreenDataTest(unittest.TestCase):
    def setUp(self):
        self.inp = inputs()
        self.kg, self.graph = self.inp["kg"], self.inp["graph"]
        self.data = screen.screen_data(self.kg, self.graph, self.inp["regions"], self.inp["candidates"])
        self.links = {l["id"]: l for l in self.data["links"]}
        self.nodes = {n["id"]: n for n in self.data["nodes"]}

    def test_v5_flags_match_python_view(self):
        v5 = algo.view_v5(self.kg, self.graph)
        self.assertEqual({l["id"] for l in self.data["links"] if l["v5"]}, {k for _, _, k in v5.edges(keys=True)})
        self.assertEqual({n["id"] for n in self.data["nodes"] if n["v5"]}, set(v5.nodes))

    def test_excluded_and_candidates_display_only(self):
        self.assertFalse(self.nodes["case-001"]["v5"])
        self.assertTrue(self.nodes["case-001"]["nosrc"])
        self.assertEqual(self.links["krel-015"]["st"], "excluded")
        self.assertEqual(self.links["krel-012"]["st"], "excluded")
        cands = [l for l in self.data["links"] if l["st"] == "candidate"]
        self.assertEqual(len(cands), 5)
        self.assertTrue(all(not l["v5"] and l["kind"] == "mentions" for l in cands))
        self.assertEqual(sorted(l["t"] for l in cands if l["s"] == "chunk-004"),
                         ["entity-seg-003", "entity-seg-004", "entity-seg-005"])     # 동명 태그 후보 3개
        self.assertFalse(any((n.get("tag") or "") == "RC-V999" for n in self.data["nodes"]))  # 도면에 없는 언급 미표시
        self.assertTrue(self.nodes["setpt-001"]["conflict"])
        self.assertTrue(self.nodes["setpt-003"]["unit_unknown"])

    def test_candidate_rows_filtered(self):
        rows = copy.deepcopy(self.inp["candidates"])
        rows[0]["link_status"] = "rejected"
        rows[2]["target_graph_version"] = "v-other"
        d = screen.screen_data(self.kg, self.graph, self.inp["regions"], rows)
        c = d["meta"]["candidates"]
        self.assertEqual((c["rows"], c["shown"], c["not_shown"]), (4, 3, 1))
        d = screen.screen_data(self.kg, self.graph, self.inp["regions"], None)
        self.assertFalse(d["meta"]["candidates"]["file"])
        self.assertFalse(any(l["st"] == "candidate" for l in d["links"]))

    def test_recheck_status(self):
        kg = copy.deepcopy(self.kg)
        l = next(x for x in kg["links"] if x["id"] == "krel-m-114485f2")
        l["recheck"] = "graph_version 변경"
        l["compute_view"] = {"v4": False, "excluded_reasons": ["재확인 필요"]}
        d = screen.screen_data(kg, self.graph, self.inp["regions"], None)
        self.assertEqual({x["id"]: x["st"] for x in d["links"]}["krel-m-114485f2"], "recheck")
        self.assertEqual(d["meta"]["recheck"], 1)

    def test_algorithm_results_from_algo(self):
        a = self.data["algo"]
        self.assertTrue(a["enabled"])
        self.assertEqual(sorted(a["A2"]["orphans"]), ["chunk-003", "chunk-004", "req-003"])
        self.assertEqual(sorted(a["A2"]["gaps"]), ["entity-node-008"])
        v5 = algo.view_v5(self.kg, self.graph)
        self.assertEqual(a["A3"], {k: v["degree"] for k, v in algo.a3_degree(v5, self.graph)["degree"].items()})
        self.assertEqual(a["A5"]["V5_count"], algo.a5_components(algo.view_v1(self.graph), v5)["V5"]["count"])
        self.assertEqual(a["A1"]["start"], "entity-node-001")                      # 구간 focus_entities[0]
        full = algo.a1_propagation(self.graph, self.inp["regions"], "entity-node-001")
        self.assertEqual(sorted(a["A1"]["reached"]), sorted(r["entity_id"] for r in full["exploration"]["reached"]))
        self.assertTrue(a["A1"]["reached"]["entity-seg-004"]["nnf"])                # RC-PV101 NC 경유
        self.assertEqual(a["A1"]["reached"]["entity-node-013"]["dir"], "downstream")

    def test_a2_no_input_and_a1_truncations(self):
        a = self.data["algo"]
        a2 = algo.a2_orphans_gaps(self.kg, self.graph)
        self.assertEqual(a["A2"]["no_input"], sorted(x["entity_id"] for x in a2["no_knowledge_input"]))
        self.assertEqual(a["A2"]["no_input_cont"], ["entity-node-002", "entity-node-006", "entity-node-017"])
        self.assertEqual(a["A1"]["truncated"], {"entity-node-002": "도면 경계에서 멈춤",
                                                "entity-node-006": "도면 경계에서 멈춤",
                                                "entity-node-017": "도면 경계에서 멈춤"})
        self.assertEqual(self.nodes["entity-node-008"]["np"], "NC")

    def test_flow_arrows_only_with_direction(self):
        segs = {n["entity_id"]: n for n in self.graph["nodes"] if n["node_type"] == "pipe_segment"}
        for e in self.graph["edges"]:
            if e["kind"] != "has_endpoint":
                self.assertEqual(self.links[e["entity_id"]]["a"], 0)                # 신호·계측 화살표 없음
                continue
            fd = segs[e["segment"]]["flow_direction"]
            want = 1 if fd["to"] == e["node"] else -1                                 # 1 = 구간 -> 노드
            self.assertEqual(self.links[e["entity_id"]]["a"], want, e["entity_id"])
        g = copy.deepcopy(self.graph)
        for n in g["nodes"]:
            if n["node_type"] == "pipe_segment":
                n["flow_direction"] = None
        d = screen.screen_data(self.kg, g, self.inp["regions"], None)
        self.assertTrue(all(l["a"] == 0 for l in d["links"]))

    def test_blocked_or_version_mismatch_disables_algorithms(self):
        kg = copy.deepcopy(self.kg)
        kg["validation"]["status"] = "blocked"
        d = screen.screen_data(kg, self.graph, self.inp["regions"], None)
        self.assertFalse(d["algo"]["enabled"])
        self.assertNotIn("A2", d["algo"])
        self.assertIn("passed", d["algo"]["reason"])
        with self.assertRaises(algo.AlgoError):
            screen.run_a1(kg, self.graph, self.inp["regions"], "entity-node-001")
        g = copy.deepcopy(self.graph)
        g["graph_version"] = "v-000000000000"
        d = screen.screen_data(self.kg, g, self.inp["regions"], None)
        self.assertFalse(d["algo"]["enabled"])
        self.assertIn("graph_version", d["algo"]["reason"])

    def test_run_a1(self):
        full, c = screen.run_a1(self.kg, self.graph, self.inp["regions"], "entity-node-008")
        self.assertTrue(c["active"])
        self.assertEqual(c["start"], "entity-node-008")
        self.assertEqual(sorted(c["reached"]), sorted(r["entity_id"] for r in full["exploration"]["reached"]))
        _, c = screen.run_a1(self.kg, self.graph, self.inp["regions"], "req-001")
        self.assertFalse(c["active"])
        self.assertEqual(c["start"], "req-001")
        _, c = screen.run_a1(self.kg, self.graph, [], "entity-node-008")
        self.assertEqual(c["reason"], "검토 구간 미지정")

    def test_s1_limit(self):
        for total, want in ((screen.NODE_LIMIT + 1, True), (screen.NODE_LIMIT, False)):
            g, k, r = ks.synthetic_inputs(total)
            d = screen.screen_data(k, g, r, None)
            self.assertEqual(d["meta"]["global_count"], total)
            self.assertIs(d["meta"]["s1"], want)
            msg = screen.s1_message(d)
            self.assertEqual(bool(msg), want)
            if want:
                self.assertIn("5,001", msg)
                self.assertIn("로컬 보기를 권장", msg)

    def test_previous_passed(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        for ver, st in (("v-aaaaaaaaaaaa", "passed"), ("v-bbbbbbbbbbbb", "blocked"), ("v-cccccccccccc", "passed")):
            os.makedirs(os.path.join(tmp, ver))
            with open(os.path.join(tmp, ver, build.KG_FILE), "w", encoding="utf-8") as fh:
                json.dump({"kg_version": ver, "validation": {"status": st}}, fh)
        os.utime(os.path.join(tmp, "v-aaaaaaaaaaaa"), (2000000000, 2000000000))
        os.utime(os.path.join(tmp, "v-cccccccccccc"), (1000000000, 1000000000))
        self.assertEqual(screen.previous_passed(tmp, "v-bbbbbbbbbbbb")[0], "v-aaaaaaaaaaaa")
        self.assertIsNone(screen.previous_passed(tmp + "-none", "v-x"))


class HtmlTest(unittest.TestCase):
    def setUp(self):
        inp = inputs()
        self.data = screen.screen_data(inp["kg"], inp["graph"], inp["regions"], inp["candidates"])

    def test_v2_offline_rules(self):
        for html in (screen.build_html(self.data), screen.build_html(None)):
            self.assertEqual(ks.html_problems(html), [])
            self.assertIn(kr.vendor_text(), html)
            self.assertNotIn("<script src", html.lower())
        self.assertIn("window.__KG_DATA__ = null;", screen.build_html(None))

    def test_data_strings_cannot_add_urls_or_close_script(self):
        d = copy.deepcopy(self.data)
        d["nodes"][0]["label"] = "http://evil.example/a.js </script><script>alert(1)</script> //h.example"
        html = screen.build_html(d)
        self.assertEqual(ks.html_problems(html), [])
        self.assertIn("http:\\/\\/evil.example", html)
        self.assertEqual(html.lower().count("</script>"), screen.build_html(self.data).lower().count("</script>"))

    def test_lt_escaped_in_data(self):
        """'<!--<script'처럼 HTML 파서 상태를 바꾸는 문자열도 데이터 안에서는 '<'가 없어야 한다."""
        d = copy.deepcopy(self.data)
        d["nodes"][0]["label"] = "<!--<script>x</script>"
        js = screen.data_js(d)
        self.assertNotIn("<", js)
        self.assertEqual(json.loads(js)["nodes"][0]["label"], "<!--<script>x</script>")
        html = screen.build_html(d)
        self.assertEqual(html.count("<!--<script"), 0)
        self.assertEqual(ks.html_problems(html), [])

    def test_url_rule_still_catches_template_urls(self):
        html = screen.build_html(self.data).replace("<title>", '<link href="https://cdn.example/x.css"><title>', 1)
        self.assertTrue(ks.html_problems(html))

    def test_tokens_from_single_source(self):
        from hazop.app import tokens
        css = tokens.kg_css_vars()
        for k, v in (("kg-setpoint", "#be185d"), ("kg-requirement", "#a16207"), ("a1-down", "#0072b2"),
                     ("comp-1", "#0072b2"), ("valve", "#0f766e"), ("kg-pipe_segment", tokens.COLORS["physical_connection"])):
            self.assertIn("--%s: %s" % (k, v), css)
        self.assertIn("--kg-excl-opacity: 0.5", css)
        self.assertIn(css, screen.build_html(None))


class BridgeLimitTest(unittest.TestCase):
    """웹 -> Python 메시지 제한: 길이 상한·파싱 실패·깊은 중첩은 로그만 남기고 무시."""

    def test_oversize_and_bad_json_ignored(self):
        from hazop.app import webview
        b = webview.Bridge()
        links = []
        b.linkSelected.connect(links.append)
        big = json.dumps({"type": "linkSelected", "id": "krel-001", "pad": "x" * webview.MAX_MESSAGE_CHARS})
        with self.assertLogs("hazop.app.webview", "WARNING") as cm:
            b.fromWeb(big)
            b.fromWeb("[" * 30000)                        # 길이 상한 안, 깊은 중첩
            b.fromWeb("{not json")
        self.assertEqual(links, [])
        self.assertEqual(len(cm.output), 3)
        self.assertIn("길이 상한", cm.output[0])
        b.fromWeb(json.dumps({"type": "linkSelected", "id": "krel-001"}))
        self.assertEqual(links, ["krel-001"])

    def test_recursion_error_caught(self):
        from unittest import mock
        from hazop.app import webview
        b = webview.Bridge()
        with mock.patch.object(webview.json, "loads", side_effect=RecursionError):
            with self.assertLogs("hazop.app.webview", "WARNING") as cm:
                b.fromWeb("[]")
        self.assertIn("RecursionError", cm.output[0])


class PointerTest(unittest.TestCase):
    """current.json의 kg_version은 열기 전에 형식·위치를 검사한다(build.py, T1 D10)."""

    def test_bad_pointer_rejected(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        root = os.path.join(tmp, "kg", "kg-X")
        os.makedirs(root)
        os.makedirs(os.path.join(tmp, "outside"))
        for bad in ("../../outside", "..", "v-ABCDEF000000", "v-0123", "v-0123456789ab/../../outside", None, 3):
            with open(os.path.join(root, build.POINTER_FILE), "w", encoding="utf-8") as fh:
                json.dump({"kg_id": "kg-X", "kg_version": bad, "knowledge_sha256": "", "knowledge_graph_sha256": ""}, fh)
            with self.assertRaises(ValueError, msg=repr(bad)):
                build.load_outputs(root)
            with self.assertRaises(ValueError, msg=repr(bad)):
                build.current_dir(root)
        with open(os.path.join(root, build.POINTER_FILE), "w", encoding="utf-8") as fh:
            json.dump({"kg_version": "v-0123456789ab"}, fh)
        self.assertEqual(build.current_dir(root), os.path.join(root, "v-0123456789ab"))


class BridgeMessageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    def test_new_messages(self):
        from hazop.app.webview import Bridge
        b = Bridge()
        links, reqs, sent = [], [], []
        b.linkSelected.connect(links.append)
        b.algorithmRequested.connect(reqs.append)
        b.toWeb.connect(sent.append)
        b.fromWeb(json.dumps({"type": "ready"}))
        b.fromWeb(json.dumps({"type": "linkSelected", "id": "krel-001"}))
        b.fromWeb(json.dumps({"type": "linkSelected", "id": 3}))
        b.fromWeb(json.dumps({"type": "runAlgorithm", "algorithm": "A1", "start": "entity-node-001", "x": 1}))
        b.fromWeb(json.dumps({"type": "runAlgorithm", "algorithm": "A1", "start": None}))
        self.assertEqual(links, ["krel-001"])
        self.assertEqual(reqs, [{"algorithm": "A1", "start": "entity-node-001"}])
        b.fromWeb(json.dumps({"type": "runAlgorithm", "algorithm": "A2", "start": "entity-node-001"}))
        b.fromWeb(json.dumps({"type": "runAlgorithm", "algorithm": "A1", "start": "x" * 201}))
        b.fromWeb(json.dumps({"type": "linkSelected", "id": "krel" + chr(10)}))
        self.assertEqual(len(reqs), 1)
        self.assertEqual(links, ["krel-001"])
        nodes = []
        b.nodeSelected.connect(nodes.append)
        b.fromWeb(json.dumps({"type": "nodeSelected", "local_id": "a" + chr(0), "entity_id": "e" * 300}))
        self.assertEqual(nodes[-1], {"local_id": None, "entity_id": None})
        b.send("loadKnowledge", data={"a": 1})
        self.assertEqual(json.loads(sent[-1]), {"type": "loadKnowledge", "data": {"a": 1}})


# ---------------------------------------------------------------- 렌더링(웹)
class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kg-screen-test-")
        cls.inp = inputs()
        cls.data = screen.screen_data(cls.inp["kg"], cls.inp["graph"], cls.inp["regions"], cls.inp["candidates"])
        cls.page = ks.Page(screen.build_html(cls.data), cls.tmp)
        cls.probs, cls.st, cls.painted = ks.render_problems(cls.page, cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.page.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_renders_offline_without_errors(self):
        self.assertEqual(self.probs, [], self.st)
        self.assertGreater(self.painted, 0)
        self.assertEqual(self.st["errors"], [])
        self.assertEqual(self.st["visible"], sum(1 for n in self.data["nodes"] if n["v5"]))  # 기본: 계산 제외 숨김

    def test_v1_local_depth_equals_ego_graph(self):
        probs, n = ks.v1_problems(self.page, self.inp["kg"], self.inp["graph"])
        self.assertEqual(probs, [])
        self.assertGreaterEqual(n, 10)

    def test_v1_with_prototype_key_ids(self):
        """constructor·__proto__·toString·hasOwnProperty 같은 ID도 BFS·표시에서 빠지지 않는다."""
        kg_p, graph_p = ks.proto_inputs(self.inp)
        d = screen.screen_data(kg_p, graph_p, self.inp["regions"], None)
        p = self.page
        try:
            p.js("window.hzKG.handle(%s), 1" % json.dumps({"type": "loadKnowledge", "data": d}))
            self.assertTrue(kr.pump_until(lambda: p.js("window.hzKG.ready === true") is True, 30))
            self.assertIn("__proto__", screen.ego_nodes(kg_p, graph_p, "__proto__", 1))
            probs, n = ks.v1_problems(p, kg_p, graph_p, ks.PROTO_CASES)
            self.assertEqual(probs, [])
            self.assertEqual(n, 11)
            self.assertTrue({"__proto__", "constructor", "toString", "hasOwnProperty"} <=
                            set(json.loads(p.js("JSON.stringify(window.hzKG.visibleIds())"))))
            self.assertEqual(json.loads(p.js("JSON.stringify(window.hzKG.state())"))["errors"], [])
        finally:
            p.js("window.hzKG.handle(%s), 1" % json.dumps({"type": "loadKnowledge", "data": self.data}))
            kr.pump_until(lambda: p.js("window.hzKG.ready === true") is True, 30)

    def test_no_input_toggle_and_a1_view_draw_without_errors(self):
        p = self.page
        p.js("window.hzKG.setToggles({noInput: true}), document.querySelector('#cmode [data-c=a1]').click(), 1")
        kr.pump_until(lambda: False, 0.5)
        self.assertTrue(p.js("document.getElementById('o-noinput').checked"))
        self.assertIn("연결점 3", p.js("document.getElementById('c-noinput').textContent"))
        self.assertIn("도면 경계", p.js("document.getElementById('a1-info').textContent"))
        self.assertEqual(json.loads(p.js("JSON.stringify(window.hzKG.state())"))["errors"], [])
        p.js("window.hzKG.setToggles({noInput: false}), document.querySelector('#cmode [data-c=type]').click(), 1")

    def test_toggles_show_excluded_only_for_display(self):
        p = self.page
        p.js("window.hzKG.setGlobal(), window.hzKG.setToggles({showCand: true, showExcl: true}), 1")
        ids = json.loads(p.js("JSON.stringify(window.hzKG.visibleIds())"))
        links = json.loads(p.js("JSON.stringify(window.hzKG.visibleLinkIds())"))
        self.assertIn("case-001", ids)
        self.assertTrue(any(l.startswith("cand:") for l in links))
        bfs = json.loads(p.js("JSON.stringify(window.hzKG.bfs('entity-node-001', 1))"))
        self.assertNotIn("case-001", bfs)                                           # BFS는 V5 관계만
        p.js("window.hzKG.setToggles({showCand: false, showExcl: false}), 1")
        self.assertNotIn("case-001", json.loads(p.js("JSON.stringify(window.hzKG.visibleIds())")))

    def test_fold_keeps_segments_out_of_hops(self):
        p = self.page
        p.js("window.hzKG.setToggles({fold: true}), window.hzKG.setLocal('entity-node-001', 1), 1")
        ids = json.loads(p.js("JSON.stringify(window.hzKG.visibleIds())"))
        p.js("window.hzKG.setToggles({fold: false}), window.hzKG.setGlobal(), 1")
        self.assertIn("entity-node-003", ids)                                       # 구간 건너 바로 이웃 설비
        self.assertIn("entity-node-008", ids)

    def test_standalone_mode_without_bridge(self):
        """브리지가 없는 웹뷰(브라우저와 같음): 미리 계산된 결과만, A1 재계산 버튼 비활성."""
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
        path = os.path.join(self.tmp, "standalone.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(screen.build_html(self.data))
        v = QWebEngineView()
        self.addCleanup(v.deleteLater)
        v.resize(900, 600)
        v.show()
        v.load(QUrl.fromLocalFile(path))
        self.assertTrue(kr.pump_until(lambda: kr.js_value(v, "window.hzKG && window.hzKG.ready === true") is True, 60))
        st = json.loads(kr.js_value(v, "JSON.stringify(window.hzKG.state())"))
        self.assertFalse(st["app"])
        self.assertEqual(st["a1start"], "entity-node-001")
        self.assertTrue(kr.js_value(v, "document.getElementById('a1-run').disabled"))
        self.assertIn("단독 모드", kr.js_value(v, "document.getElementById('mode-chip').textContent"))
        v.page().deleteLater()


# ---------------------------------------------------------------- 주 창
class WindowTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inp = inputs()
        cls.roots = ks.TempRoots().__enter__()
        ks.prepare_work_root(cls.roots.work, cls.inp)

    @classmethod
    def tearDownClass(cls):
        cls.roots.__exit__(None, None, None)

    def open(self, size=(1440, 860)):
        win = ks.open_window(tempfile.mkdtemp(dir=self.roots.tmp), size)
        self.addCleanup(ks.close_window, win)
        return win


class KnowledgeTabTest(WindowTestBase):
    def test_step_tabs_order_and_indexes(self):
        from hazop.app.main_window import STEPS
        win = self.open()
        rail = win.rail.layout()
        shown = [rail.itemAt(i).widget() for i in range(rail.count())
                 if rail.itemAt(i).widget() in win.step_buttons]
        self.assertEqual([b.accessibleName() for b in shown],
                         ["① 자료 등록", "② 도면 추출", "③ 지식그래프", "④ 검토구간", "⑤ 분석 결과"])
        self.assertEqual([b.text() for b in shown], ["등록", "추출", "그래프", "구간", "결과"])  # 번호는 원 아이콘(U-05)
        self.assertEqual(STEPS, ("① 자료 등록", "② 도면 추출", "고정 응답 분석(이전 ④)", "설계보완·확정(이전 ⑤)",
                                 "③ 지식그래프", "④ 검토구간", "⑤ 분석 결과"))  # 기존 index 유지, 뒤에 추가
        self.assertEqual([i for i, b in enumerate(win.step_buttons) if not b.isHidden()], [0, 1, 4, 5, 6])
        win.go(2)  # 이전 ④는 ⑤ 결과 단계 아래: 숨은 버튼이 눌리고 레일은 ⑤가 현재
        self.assertTrue(win.step_buttons[2].isChecked())
        self.assertEqual(win.step_buttons[6].property("state"), "now")
        self.assertEqual(win.step_buttons[0].property("state"), "todo")

    def test_open_select_run_algorithm_and_layout(self):
        win = self.open()
        probs, info = ks.tab_problems(win, self.inp)
        self.assertEqual(probs, [], info)
        scr = win.current_screen()
        # 관계 클릭(웹 → linkSelected) → 관계 상세, 후보는 CSV에서 판단 안내
        cand = next(l["id"] for l in scr.data["links"] if l["st"] == "candidate")
        win.webview.bridge.fromWeb(json.dumps({"type": "linkSelected", "id": cand}))
        self.assertIn("link_candidates.csv", scr.detail.toPlainText())
        win.webview.bridge.fromWeb(json.dumps({"type": "linkSelected", "id": "krel-001"}))
        self.assertIn("근거 상속", scr.detail.toPlainText())
        # 상세 연결 목록 클릭 → selectNode 메시지 + 그 노드 상세
        sent = []
        win.webview.bridge.toWeb.connect(sent.append)
        from PySide6.QtCore import QUrl
        scr._anchor(QUrl("node:req-001"))
        self.assertEqual(json.loads(sent[-1]), {"type": "selectNode", "id": "req-001"})
        self.assertIn("req-001", scr.detail.toPlainText())
        # 현재 그래프에 없는 ID는 처리하지 않음
        before_a1, before_detail = dict(scr.data["algo"]["A1"]), scr.detail.toHtml()
        win.webview.bridge.fromWeb(json.dumps({"type": "runAlgorithm", "algorithm": "A1", "start": "no-such-node"}))
        win.webview.bridge.fromWeb(json.dumps({"type": "linkSelected", "id": "no-such-link"}))
        win.webview.bridge.fromWeb(json.dumps({"type": "nodeSelected", "local_id": None, "entity_id": "no-such-node"}))
        self.assertEqual(scr.data["algo"]["A1"], before_a1)
        self.assertEqual(scr.detail.toHtml(), before_detail)
        # A1 비활성 사유(지식 노드 시작)도 화면에 남김
        win.webview.bridge.fromWeb(json.dumps({"type": "runAlgorithm", "algorithm": "A1", "start": "req-001"}))
        self.assertEqual(scr.data["algo"]["A1"]["start"], "req-001")
        self.assertFalse(scr.data["algo"]["A1"]["active"])
        # 단독 모드 HTML도 작업 루트 출력/ 아래에 씀
        self.assertTrue(scr.standalone.startswith(os.path.join(self.roots.work, "출력", "지식그래프")))
        self.assertTrue(os.path.isfile(scr.standalone))

    def test_toolbar_hides_versions_and_selection_follows(self):
        win = self.open()
        probs, info = ks.tab_problems(win, self.inp)
        self.assertEqual(probs, [], info)
        scr = win.current_screen()
        bar = " ".join(c.text() for c in scr.chips.values() if not c.isHidden())
        self.assertNotIn("kg_version", bar)
        self.assertNotIn("graph_version", bar)
        self.assertTrue(scr.chips["graph"].isHidden())  # 도면 그래프 버전이 지식그래프 기준과 같음
        self.assertIn(self.inp["kg"]["kg_version"], scr.info_chip.toolTip())
        self.assertIn(scr.standalone, scr.info_chip.toolTip())
        scr._clear_detail()
        self.assertIs(scr.detail_stack.currentWidget(), scr.detail_empty)
        self.assertIn("선택한 항목 없음", scr.detail_empty.text())
        self.assertNotIn(scr.standalone, scr.detail_empty.text())
        win.webview.bridge.fromWeb(json.dumps({"type": "nodeSelected", "local_id": "local-node-001",
                                               "entity_id": "entity-node-001"}))
        self.assertEqual(win.selection, {"kind": "component", "drawing": scr.graph_dir, "entity_id": "entity-node-001"})
        win.webview.bridge.fromWeb(json.dumps({"type": "nodeSelected", "local_id": None, "entity_id": "req-001"}))
        self.assertIsNone(win.selection)

    def test_s1_band_on_synthetic(self):
        win = self.open()
        ks.write_synthetic_kg(self.roots.work, screen.NODE_LIMIT + 1)
        win.go(ks.knowledge_index())
        scr = win.current_screen()
        scr.kg_combo.setCurrentIndex(scr.kg_combo.findText("kg-SYN-S1"))
        self.assertEqual(ks.s1_window_problem(win), [])
        self.assertTrue(scr.data["algo"]["enabled"])
        shutil.rmtree(os.path.join(self.roots.work, "출력", "지식그래프", "kg-SYN-S1"))

    def test_blocked_shows_blockers_and_previous_version(self):
        win = self.open()
        kg_root = os.path.join(self.roots.work, "출력", "지식그래프", self.inp["kg"]["kg_id"])
        ptr = os.path.join(kg_root, build.POINTER_FILE)
        with open(ptr, "rb") as fh:
            old_ptr = fh.read()
        def restore():
            with open(ptr, "wb") as fh:
                fh.write(old_ptr)
        self.addCleanup(restore)
        kg = copy.deepcopy(self.inp["kg"])
        kg["kg_version"] = "v-b10c4ed00001"
        kg["validation"] = {"status": "blocked", "unknowns": [],
                            "blockers": [{"rule": "K6", "check": "no_source", "target": "req-009", "reason": "출처 없음"}]}
        kb = build.dump_bytes(self.inp["knowledge"])
        gb = build.dump_bytes(kg)
        os.makedirs(os.path.join(kg_root, kg["kg_version"]), exist_ok=True)
        for name, b in ((build.KNOWLEDGE_FILE, kb), (build.KG_FILE, gb)):
            with open(os.path.join(kg_root, kg["kg_version"], name), "wb") as fh:
                fh.write(b)
        build.write_json_atomic(ptr, {"kg_id": kg["kg_id"], "kg_version": kg["kg_version"],
                                      "knowledge_sha256": hashlib.sha256(kb).hexdigest(),
                                      "knowledge_graph_sha256": hashlib.sha256(gb).hexdigest()})
        win.go(ks.knowledge_index())
        scr = win.current_screen()
        self.assertFalse(scr.blockers.isHidden())
        self.assertIn("[K6] no_source req-009", " ".join(scr.blockers.messages))
        self.assertFalse(scr.data["algo"]["enabled"])
        self.assertNotIn("A2", scr.data["algo"])
        self.assertFalse(scr.prev_btn.isHidden())
        self.assertIn(self.inp["kg"]["kg_version"], scr.prev_btn.text())
        scr.prev_btn.click()
        self.assertTrue(scr.showing_prev)
        self.assertEqual(scr.data["meta"]["kg_version"], self.inp["kg"]["kg_version"])
        self.assertTrue(scr.data["algo"]["enabled"])
        self.assertIn("이전 버전", scr.info_chip.text())
        scr.prev_btn.click()
        self.assertFalse(scr.showing_prev)
        shutil.rmtree(os.path.join(kg_root, kg["kg_version"]))

    def test_empty_state(self):
        win = self.open()
        root = os.path.join(self.roots.work, "출력", "지식그래프")
        hidden = root + "-hidden"
        os.rename(root, hidden)
        self.addCleanup(os.rename, hidden, root)
        win.go(ks.knowledge_index())
        scr = win.current_screen()
        self.assertEqual(scr.stack.currentIndex(), 0)
        self.assertIn("지식그래프가 없습니다", scr.empty.text())


class ShowInDrawingTest(unittest.TestCase):
    """'도면에서 보기': ②로 전환하고 기존 focus 메시지를 보낸다. 작업 루트 안으로 복사한 도면을 추출하므로
    graph_version이 샘플 CSV 기록과 달라 mentions는 재확인 필요, 후보는 미표시가 된다(재확인 표시 확인 겸)."""

    @classmethod
    def setUpClass(cls):
        cls.base_inp = inputs()
        cls.roots = ks.TempRoots().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.roots.__exit__(None, None, None)

    def test_show_in_drawing_and_recheck(self):
        from tests.test_app import build_temp_drawing
        from hazop.app import make_application
        make_application(["test"])
        work = self.roots.work
        out_dir, graph = build_temp_drawing(work)
        knowledge = self.base_inp["knowledge"]
        kg = build.build_kg(knowledge, [graph])
        build.write_outputs(os.path.join(work, "출력", "지식그래프", kg["kg_id"]), knowledge, kg)
        kdir = os.path.join(work, "데이터", "지식", ks.SAMPLE_PROJECT)
        os.makedirs(kdir, exist_ok=True)
        shutil.copy(os.path.join(ks.SAMPLE_DIR, screen.CANDIDATES_CSV), kdir)
        win = ks.open_window(self.roots.tmp)
        self.addCleanup(ks.close_window, win)
        win.go(ks.knowledge_index())
        scr = win.current_screen()
        self.assertEqual(scr.graph_dir, os.path.basename(out_dir))
        self.assertEqual(scr.data["meta"]["recheck"], 2)
        self.assertFalse(scr.recheck_band.isHidden())
        self.assertFalse(scr.chips["recheck"].isHidden())
        self.assertEqual(scr.data["meta"]["candidates"]["shown"], 0)               # 대상 도면 버전이 다름
        self.assertTrue(ks.wait_knowledge(win))
        win.webview.bridge.fromWeb(json.dumps({"type": "nodeSelected", "local_id": "local-node-008",
                                               "entity_id": "entity-node-008"}))
        self.assertTrue(scr.goto_btn.isEnabled())
        sent = []
        win.webview.bridge.toWeb.connect(sent.append)
        scr.goto_btn.click()
        self.assertEqual(win.stack.currentIndex(), 1)
        self.assertEqual(win.screens[1].combo.currentText(), os.path.basename(out_dir))
        self.assertTrue(kr.pump_until(lambda: any(json.loads(s).get("type") == "focus" for s in sent), 40), sent)
        focus = [json.loads(s) for s in sent if json.loads(s).get("type") == "focus"][-1]
        self.assertEqual(focus["local_id"], "local-node-008")
        self.assertTrue(any(json.loads(s) == {"type": "setView", "view": "drawing"} for s in sent))


if __name__ == "__main__":
    unittest.main()
