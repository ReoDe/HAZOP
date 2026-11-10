"""② 도면 편집 모드(drawing-edit-spec.md '화면'). 실행: python -m unittest discover -s tests -t .

순수 부분(EditSession·도구 상태 기계·흐름 요청)은 웹뷰 없이, 화면·브리지는 QT_QPA_PLATFORM=offscreen에서 검사한다.
작업 루트·저장 루트·설정은 임시 폴더만 쓴다(실제 store·data/ 미사용). 네트워크 사용 없음.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from tests.test_app import pump, wait_for  # noqa: E402
from scripts.check_edit_screen import install_sample  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.app.screens import viewer  # noqa: E402
from hazop.app.screens.viewer import EditSession, ToolState, choose_end, finish_path, flow_request, start_tool, tool_pick  # noqa: E402,E501

ITEMS = {
    "n1": ("node", {"local_id": "n1", "source_object_id": "s-n1", "tag": "P-1"}),
    "n2": ("node", {"local_id": "n2", "source_object_id": "s-n2", "tag": "V-2"}),
    "r1": ("relation", {"local_id": "r1", "source_object_id": "s-r1", "kind": "physical_connection",
                        "endpoints": [{"end": "source", "node_local_id": "n1"}, {"end": "target", "node_local_id": "n2"}],
                        "flow_direction": None}),
}
DEFAULTS = {"kind": "pump", "tag": " P-9 ", "relation_kind": "signal_connection"}


def pick(local_id=None, point=(10.0, 20.0)):
    return {"point": list(point), "local_id": local_id, "view": None}


class EditSessionTest(unittest.TestCase):
    def test_undo_redo_revert(self):
        s = EditSession([{"op_id": "c-0001"}])
        self.assertFalse(s.dirty)
        s.add({"op_id": "c-0002"})
        s.add({"op_id": "c-0003"})
        self.assertTrue(s.dirty)
        self.assertTrue(s.undo())
        self.assertEqual([o["op_id"] for o in s.ops], ["c-0001", "c-0002"])
        self.assertTrue(s.redo())
        self.assertEqual(len(s.ops), 3)
        self.assertFalse(s.redo())
        s.undo()
        s.add({"op_id": "c-0004"})                                   # 새 수정은 다시 실행 기록을 지운다
        self.assertFalse(s.redo())
        self.assertTrue(s.revert())
        self.assertEqual(s.ops, s.saved)
        self.assertFalse(s.dirty)
        self.assertTrue(s.undo())                                     # 되돌리기도 실행 취소 가능
        self.assertTrue(s.dirty)
        s.mark_saved()
        self.assertFalse(s.dirty)
        self.assertFalse(s.revert())


class ToolMachineTest(unittest.TestCase):
    def test_add_node_centers_box_on_click(self):
        st, msg = start_tool("add_node", None, ITEMS)
        st, req, _ = tool_pick(st, pick(point=(100, 50)), ITEMS, DEFAULTS)
        self.assertEqual(req, {"op": "add_node", "target": None,
                               "value": {"category": "equipment", "kind": "pump", "tag": "P-9",
                                         "bbox": [80.0, 30.0, 40, 40]}})
        self.assertEqual(st.tool, "add_node")                         # 여러 개를 이어서 놓을 수 있다

    def test_connect_needs_two_different_nodes(self):
        st, _ = start_tool("connect", None, ITEMS)
        st, req, msg = tool_pick(st, pick(None), ITEMS, DEFAULTS)
        self.assertIsNone(req)
        self.assertIn("기기를 클릭", msg)
        st, req, _ = tool_pick(st, pick("r1"), ITEMS, DEFAULTS)      # 연결선은 기기가 아님
        self.assertIsNone(st.first)
        st, req, _ = tool_pick(st, pick("n1"), ITEMS, DEFAULTS)
        self.assertEqual((st.first, req), ("n1", None))
        st, req, msg = tool_pick(st, pick("n1"), ITEMS, DEFAULTS)
        self.assertIsNone(req)
        self.assertIn("같은 기기", msg)
        st, req, _ = tool_pick(st, pick("n2"), ITEMS, DEFAULTS)
        self.assertEqual(req, {"op": "add_relation", "target": None,
                               "value": {"kind": "signal_connection", "line_type": "signal", "line_no": None,
                                         "from": "s-n1", "to": "s-n2"}})
        self.assertEqual(st, ToolState("connect"))

    def test_endpoint_needs_relation_then_end_then_node(self):
        st, msg = start_tool("endpoint", "n1", ITEMS)
        self.assertEqual(st.tool, "select")
        self.assertIn("연결", msg)
        st, _ = start_tool("endpoint", "r1", ITEMS)
        st, req, _ = tool_pick(st, pick("n2"), ITEMS, DEFAULTS)
        self.assertIsNone(req)                                        # 끝을 먼저 골라야 함
        st, _ = choose_end(st, "target")
        st, req, _ = tool_pick(st, pick("n1"), ITEMS, DEFAULTS)
        self.assertEqual(req, {"op": "set_endpoint", "target": "s-r1", "value": {"end": "target", "node": "s-n1"}})
        self.assertEqual(st.tool, "select")

    def test_path_collects_points_until_finish(self):
        st, _ = start_tool("path", "r1", ITEMS)
        st, req, _ = tool_pick(st, pick(point=(1, 2)), ITEMS, DEFAULTS)
        self.assertIsNone(req)
        st, req, msg = finish_path(st, ITEMS)
        self.assertIsNone(req)
        self.assertIn("2개 이상", msg)
        st, _, _ = tool_pick(st, pick("n1", point=(3, 4)), ITEMS, DEFAULTS)  # 항목 위를 눌러도 점으로 쓴다
        st, _, _ = tool_pick(st, pick(point=(5, 6)), ITEMS, DEFAULTS)
        st, req, _ = finish_path(st, ITEMS)
        self.assertEqual(req, {"op": "set_path", "target": "s-r1", "value": {"points": [[1, 2], [3, 4], [5, 6]]}})
        self.assertEqual(st, ToolState())

    def test_flow_set_and_flip(self):
        req, why = flow_request(ITEMS, "r1", flip=False)
        self.assertIsNone(why)
        self.assertEqual(req["value"], {"from": "s-n1", "to": "s-n2"})
        req, _ = flow_request(ITEMS, "r1", flip=True)                 # 방향이 없으면 target → source
        self.assertEqual(req["value"], {"from": "s-n2", "to": "s-n1"})
        items = dict(ITEMS)
        items["r1"] = ("relation", dict(ITEMS["r1"][1], flow_direction={"from": "n2", "to": "n1"}))
        req, _ = flow_request(items, "r1", flip=True)
        self.assertEqual(req["value"], {"from": "s-n1", "to": "s-n2"})
        items["r1"] = ("relation", dict(ITEMS["r1"][1], endpoints=[{"end": "source", "node_local_id": None},
                                                                   {"end": "target", "node_local_id": "n2"}]))
        req, why = flow_request(items, "r1", flip=False)
        self.assertIsNone(req)
        self.assertIn("끝점 잇기", why)


class EditPickBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    def test_edit_pick_validation(self):
        from hazop.app.webview import Bridge
        b = Bridge()
        got = []
        b.editPick.connect(got.append)
        b.fromWeb(json.dumps({"type": "editPick", "point": [1.5, -2], "local_id": "local-node-001",
                              "view": {"s": 2, "x": 10, "y": -5}}))
        self.assertEqual(got[-1], {"point": [1.5, -2.0], "local_id": "local-node-001",
                                   "view": {"s": 2.0, "x": 10.0, "y": -5.0}})
        b.fromWeb(json.dumps({"type": "editPick", "point": [0, 0], "local_id": "x\u0001", "view": {"s": 0, "x": 0, "y": 0}}))
        self.assertEqual(got[-1], {"point": [0.0, 0.0], "local_id": None, "view": None})
        n = len(got)
        for bad in ('{"type": "editPick", "point": [NaN, 1]}', '{"type": "editPick", "point": [Infinity, 1]}',
                    json.dumps({"type": "editPick", "point": [True, 1]}),
                    json.dumps({"type": "editPick", "point": ["1", 2]}),
                    json.dumps({"type": "editPick", "point": [1, 2, 3]}),
                    json.dumps({"type": "editPick", "point": [1e9, 2]}),
                    json.dumps({"type": "editPick"})):
            b.fromWeb(bad)
        self.assertEqual(len(got), n)


class EditScreenTest(unittest.TestCase):
    """임시 작업 루트에 샘플 도면(SNP-M-101, 미확인 있음)을 추출해 ②에서 편집한다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-edit-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop.app import make_application
        cls.qapp = make_application(["test"])
        cls.name = install_sample(os.environ["HAZOP_WORK_ROOT"])

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from hazop.app.main_window import MainWindow
        shutil.rmtree(paths.folder_in(os.environ["HAZOP_WORK_ROOT"], "drawing-edits"), ignore_errors=True)
        win = MainWindow(settings_path=os.path.join(tempfile.mkdtemp(dir=self.tmp), "settings.json"), ask_reviewer=False)
        win.set_reviewer_name("검토자A")
        win.resize(1440, 860)
        win.show()
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.webview.dispose)
        self.win = win
        win.go(1)
        self.scr = win.screens[1]
        self.scr.select_drawing(self.name)
        self.assertTrue(self.scr.editable())
        self.scr.edit_btn.setChecked(True)
        self.settle()

    def tearDown(self):
        if self.scr.session is not None:
            self.scr.session.mark_saved()                             # 닫을 때 묻지 않게
        self.win.close()

    def settle(self):
        self.assertTrue(wait_for(lambda: self.win.webview.bridge.is_ready), "웹뷰 준비 안 됨")
        pump(seconds=0.2)

    def item_with_unknown(self):
        return next(u["target"] for u in self.scr.info["corrected"]["validation"]["unknowns"]
                    if u.get("target") in self.scr.items)

    def test_tag_edit_undo_redo_and_leave_prompt(self):
        scr = self.scr
        self.assertTrue(scr.edit_panel.isVisible())
        node = scr.info["corrected"]["nodes"][0]
        scr.on_node({"local_id": node["local_id"], "entity_id": None})
        self.assertEqual(scr.tag_edit.text(), node.get("tag") or "")
        scr.tag_edit.setText("ZZ-EDIT-1")
        with mock.patch.object(viewer, "ask_choice") as ask:
            scr.tag_apply.click()
            ask.assert_not_called()                                   # 프로젝트에 없는 태그는 묻지 않음
        self.settle()
        self.assertEqual([o["op"] for o in scr.session.ops], ["set_tag"])
        self.assertEqual(scr.items[node["local_id"]][1]["tag"], "ZZ-EDIT-1")
        self.assertIn("적용", scr.op_list.item(0).text())
        scr.undo_btn.click()
        self.settle()
        self.assertEqual(scr.session.ops, [])
        self.assertEqual(scr.items[node["local_id"]][1].get("tag"), node.get("tag"))
        scr.redo_btn.click()
        self.settle()
        self.assertTrue(scr.session.dirty)
        with mock.patch.object(viewer, "ask_choice", return_value="cancel"):
            self.assertFalse(self.win.go(0))
        self.assertEqual(self.win.stack.currentIndex(), 1)
        with mock.patch.object(viewer, "ask_choice", return_value="discard"):
            self.assertTrue(self.win.go(0))
        self.assertEqual(self.win.stack.currentIndex(), 0)
        self.assertFalse(self.win.webview.edit["on"])                 # 다른 화면에서는 편집 모드 꺼짐

    def test_new_op_after_undoing_saved_op_gets_new_id(self):
        """저장한 추가를 실행 취소하고 새로 추가하면 op_id·manual- ID가 겹치지 않고, 지운 추가 내용은 기록에 남는다."""
        from hazop.extract import corrections
        scr = self.scr

        def add(tag, x):
            ok = scr.commit({"op": "add_node", "target": None,
                             "value": {"category": "equipment", "kind": "pump", "tag": tag, "bbox": [x, 10, 40, 40]}})
            self.settle()
            self.assertTrue(ok)
            return dict(scr.session.ops[-1])
        with mock.patch.object(viewer, "notify"):
            first = add("ZZ-P-100", 100)
            self.assertTrue(scr.save())
            self.settle()
            scr.undo_btn.click()
            self.settle()
            second = add("ZZ-V-200", 300)
            self.assertTrue(scr.save())
        self.assertNotEqual(second["op_id"], first["op_id"])
        self.assertEqual(scr.selected, "manual-" + second["op_id"])
        doc = corrections.load(self.name)
        self.assertEqual([o["op_id"] for o in doc["ops"]], [second["op_id"]])
        self.assertEqual(doc["log"][-1]["removed_ops"], [first])

    def test_new_op_does_not_reuse_id_still_on_undo_stack(self):
        """저장하지 않고 되돌린 추가도 실행 취소로 되살아날 수 있으므로, 그 번호를 새 추가에 다시 주지 않는다."""
        scr = self.scr

        def add(tag, x):
            ok = scr.commit({"op": "add_node", "target": None,
                             "value": {"category": "equipment", "kind": "pump", "tag": tag, "bbox": [x, 10, 40, 40]}})
            self.settle()
            self.assertTrue(ok)
            return dict(scr.session.ops[-1])
        with mock.patch.object(viewer, "notify"):
            unsaved = add("ZZ-P-101", 100)
            scr.revert()
            self.settle()
            saved = add("ZZ-P-102", 300)
            self.assertTrue(scr.save())
        self.assertNotEqual(saved["op_id"], unsaved["op_id"])

    def test_duplicate_tag_asks(self):
        scr = self.scr
        tagged = [n for n in scr.info["corrected"]["nodes"] if n.get("tag")]
        a, b = tagged[0], tagged[1]
        scr.on_node({"local_id": a["local_id"], "entity_id": None})
        scr.tag_edit.setText(b["tag"])
        with mock.patch.object(viewer, "ask_choice", return_value="cancel") as ask:
            scr.tag_apply.click()
        self.assertIn(b["tag"], ask.call_args[0][2])
        self.assertEqual(scr.session.ops, [])
        add = {"op": "add_node", "target": None,
               "value": {"category": "equipment", "kind": "pump", "tag": "ZZ-NEW", "bbox": [10, 10, 40, 40]}}
        with mock.patch.object(viewer, "ask_choice", return_value="cancel") as ask:
            self.assertTrue(scr.commit(add))
            self.settle()
            ask.assert_not_called()
            self.assertFalse(scr.commit(add))                         # 저장 전 작업 중 태그와도 겹침을 본다
            ask.assert_called_once()

    def test_connect_via_bridge_and_confirm_then_save(self):
        scr = self.scr
        nodes = scr.info["corrected"]["nodes"]
        scr.set_tool("connect")
        bridge = self.win.webview.bridge
        for n in nodes[:2]:
            bridge.fromWeb(json.dumps({"type": "editPick", "point": [1, 1], "local_id": n["local_id"]}))
        self.settle()
        self.assertEqual([o["op"] for o in scr.session.ops], ["add_relation"])
        new_id = "manual-" + scr.session.ops[0]["op_id"]
        self.assertEqual(scr.selected, new_id)
        self.assertIn(new_id, scr.items)
        target = self.item_with_unknown()
        before = scr.info["corrected"]["summary"]["unknowns"]
        scr.set_tool("select")
        scr.on_node({"local_id": target, "entity_id": None})
        self.assertGreater(scr.unknown_list.count(), 0)
        scr.confirm_btn.click()
        self.settle()
        self.assertLess(scr.info["corrected"]["summary"]["unknowns"], before)
        with mock.patch.object(viewer, "notify") as note:
            self.assertTrue(scr.save())
        self.assertFalse(scr.session.dirty)
        self.assertIn("저장", note.call_args[0][2])
        saved = paths.folder_in(os.environ["HAZOP_WORK_ROOT"], "drawing-edits")
        self.assertTrue(os.listdir(saved))
        self.settle()
        self.assertIn("미확인 %d" % len(scr.info["graph"]["validation"]["unknowns"]), scr.chip_stats.text())
        self.assertNotIn("저장 전", scr.chip_stats.text())

    def js(self, expr):
        out = []
        self.win.webview.page().runJavaScript(expr, 0, out.append)
        self.assertTrue(wait_for(lambda: out, 10), "runJavaScript 결과 없음: %s" % expr)
        return out[0]

    def test_chrome_shown_once_and_palette_commands(self):
        """② 보기 모드: 검증 칩은 도구줄(Qt)에만, 경로 질의는 접힌 채 시작하고 명령으로 연다. 고른 항목은 관련 항목 선택이 된다."""
        scr = self.scr
        scr.edit_btn.setChecked(False)
        self.settle()
        display = "getComputedStyle(document.getElementById('%s')).display"
        # 편집을 끈 뒤 다시 그리는 동안에는 값이 ''로 온다(CI run 42795547168에서 두 번). 그려질 때까지 기다린다
        self.assertTrue(wait_for(lambda: self.js(display % "status") == "none", 10))
        self.assertIn("구조 검증", scr.chip_valid.text())
        self.assertEqual(self.js(display % "pathq"), "none")
        self.assertNotEqual(self.js(display % "pq-chip"), "none")
        cmds = {label: fn for label, _, fn in scr.commands()}
        cmds["경로 질의 열기"]()
        self.assertTrue(wait_for(lambda: self.js(display % "pathq") == "block", 10))
        cmds["레이어: 태그 보이기/숨기기"]()
        self.assertTrue(wait_for(lambda: self.js("document.getElementById('layer-tag').classList.contains('hidden')"), 10))
        g = next(n for n in scr.info["graph"]["nodes"] if n.get("local_id"))
        scr.on_node({"local_id": g["local_id"], "entity_id": None})
        self.assertEqual(self.win.selection, {"kind": "component", "drawing": self.name, "entity_id": g["entity_id"],
                                              "local_id": g["local_id"]})

    def test_web_click_sends_drawing_coordinates(self):
        """웹 클릭 → editPick: 오버레이 좌표 + offset이 노드 bbox 중심(도면 좌표)과 같다. 끌어서 이동한 클릭은 버린다."""
        scr = self.scr
        node = scr.info["corrected"]["nodes"][0]
        loc = next(l for l in scr.info["corrected"]["source_locations"] if l["local_id"] == node["local_id"])
        cx, cy = loc["bbox"][0] + loc["bbox"][2] / 2, loc["bbox"][1] + loc["bbox"][3] / 2
        scr.set_tool("add_node")
        self.settle()
        got = []
        self.win.webview.bridge.editPick.connect(got.append)
        js = ("(function(){var e=document.querySelector('#overlay .sym[data-local-id=\"%s\"]');var r=e.getBoundingClientRect();"
              "var x=r.left+r.width/2,y=r.top+r.height/2;"
              "e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,clientX:x+%d,clientY:y,button:0}));"
              "e.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:x,clientY:y}));})()")
        with mock.patch.object(scr, "commit"):
            self.win.webview.page().runJavaScript(js % (node["local_id"], 40))
            pump(seconds=0.5)
            self.assertEqual(got, [])
            self.win.webview.page().runJavaScript(js % (node["local_id"], 0))
            self.assertTrue(wait_for(lambda: got, 10), "editPick 없음")
        self.assertEqual(got[0]["local_id"], node["local_id"])
        self.assertIsNotNone(got[0]["view"])
        tol = 1.5 / got[0]["view"]["s"]                               # MouseEvent clientX·Y는 정수 화면 픽셀
        self.assertAlmostEqual(got[0]["point"][0], cx, delta=tol)
        self.assertAlmostEqual(got[0]["point"][1], cy, delta=tol)


if __name__ == "__main__":
    unittest.main()
