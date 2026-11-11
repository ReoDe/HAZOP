"""② 도면 연결점: 칩·'도면 연결점' 패널·사람 짝 지정(project.save_manual). 실행: python -m unittest discover -s tests -t .

임시 작업 루트에 샘플 도면 SNP-M-101·SNP-M-102 두 장을 추출해 프로젝트 그래프(SNP-SAMPLE)를 만든다. RC-L010·RC-L011은
자동으로 이어지고, 101의 다른 연결점은 상대 도면이 없어 미연결이다. 실제 데이터 폴더는 쓰지 않는다. 네트워크 사용 없음.
"""

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
from hazop.app import project_ctx  # noqa: E402
from hazop.app.screens import viewer  # noqa: E402
from hazop.graph import project  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402


class LinkTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-links-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop.app import make_application
        cls.qapp = make_application(["test"])
        cls.n101 = install_sample(os.environ["HAZOP_WORK_ROOT"], "SNP-M-101")
        cls.n102 = install_sample(os.environ["HAZOP_WORK_ROOT"], "SNP-M-102")

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(paths.folder_in(os.environ["HAZOP_WORK_ROOT"], "data"), ignore_errors=True)


class LinkDataTest(LinkTestBase):
    def test_points_and_plain_chips(self):
        ctx = project_ctx.load(self.n101)
        pts = {p["line_no"]: p for p in viewer.link_points(ctx)}
        self.assertEqual(pts["RC-L011"]["peer"]["drawing"], "SNP-M-102")
        self.assertEqual(pts["MS-L001"]["reason"], "unregistered_drawing")
        every = viewer.drawing_chips(ctx)
        chips = {c["text"]: c for c in every}
        link = chips["→ SNP-M-102 (RC-L011)"]
        self.assertEqual((link["kind"], link["local_id"]), ("link", pts["RC-L011"]["local_id"]))
        self.assertTrue(link["key"].startswith("link|SNP-M-102||graph-SNP-M-102/"))
        warn = [c for c in every if c["kind"] == "unlinked"]
        self.assertTrue(warn and all(c["text"] == "미연결 · 상대 도면 없음" for c in warn))
        self.assertIn("unlinked|%s" % pts["MS-L001"]["entity_id"], {c["key"] for c in warn})

    def test_node_set_chips_name_the_node(self):
        ctx = project_ctx.load(self.n101)
        chips = viewer.drawing_chips(ctx, ctx.view(sn.propose(ctx.pg)))
        node_chips = [c for c in chips if c["text"].endswith("SNP-M-102에서 계속")]
        self.assertEqual(len(node_chips), 2)
        for c in node_chips:
            self.assertRegex(c["text"], r"^S\d+ → SNP-M-102에서 계속$")
            self.assertEqual(c["key"].split("|")[2], c["text"].split()[0])

    def test_replace_link_ops_drops_earlier_ops_on_same_point(self):
        a = {"drawing_number": "A", "source_object_id": "c1"}
        old = [{"op_id": "1", "op": "unlink", "ends": [a]},
               {"op_id": "2", "op": "unlink", "ends": [{"drawing_number": "B", "source_object_id": "c9"}]}]
        new = viewer.new_link_op("link", [{"drawing_number": "a ", "source_object_id": "c1"},
                                          {"drawing_number": "C", "source_object_id": "c2"}], "kim")
        self.assertEqual([o["op_id"] for o in viewer.replace_link_ops(old, new)], ["2", new["op_id"]])


class LinkScreenTest(LinkTestBase):
    def setUp(self):
        super().setUp()
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=os.path.join(tempfile.mkdtemp(dir=self.tmp), "settings.json"), ask_reviewer=False)
        win.set_reviewer_name("검토자A")
        win.resize(1440, 860)
        win.show()
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.webview.dispose)
        self.addCleanup(win.close)
        self.win = win
        win.go(1)
        self.scr = win.screens[1]
        self.scr.select_drawing(self.n101)
        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready), "웹뷰 준비 안 됨")
        pump(seconds=0.2)

    def point(self, line_no):
        return next(p for p in self.scr.points if p["line_no"] == line_no)

    def chip_count(self):
        out = []
        self.win.webview.page().runJavaScript("document.querySelectorAll('.hz-chip').length", 0, out.append)
        wait_for(lambda: out, 10)
        return out[0] if out else None

    def test_panel_chips_and_accessible_names(self):
        scr = self.scr
        self.assertTrue(scr.link_panel.isVisible())
        self.assertTrue(scr.link_counts.text().startswith("짝 2 · 미연결 "))
        self.assertTrue(wait_for(lambda: self.chip_count() == len(scr.points), 10), "칩이 도면에 없음")
        self.assertIs(scr.main_focus(), self.win.webview)
        for w in (scr.combo, scr.new_kind, scr.new_tag, scr.new_rel, scr.tag_edit, scr.kind_combo):
            self.assertTrue(w.accessibleName(), w)
        scr.edit_btn.setChecked(True)
        pump(seconds=0.2)
        self.assertFalse(scr.link_panel.isVisible())
        scr.edit_btn.setChecked(False)
        pump(seconds=0.2)
        self.assertTrue(scr.link_panel.isVisible())

    def test_linked_chip_goes_to_other_drawing_and_selects_node(self):
        scr = self.scr
        peer = self.point("RC-L011")["peer"]["entity_id"]
        scr.on_chip("link|SNP-M-102|S3|%s" % peer)
        self.assertEqual(scr.combo.currentText(), self.n102)
        self.assertEqual(self.win.selection, {"kind": "node", "drawing": self.n102, "node_id": "S3"})
        scr.on_chip("link|NOPE||x")                                     # 모르는 도면: 그대로
        self.assertEqual(scr.combo.currentText(), self.n102)

    def test_pair_dialog_saves_manual_link_and_undo_restores(self):
        scr = self.scr
        ms = self.point("MS-L001")
        cands = viewer.pair_candidates(scr.ctx, ms["entity_id"])
        self.assertTrue(all(c["drawing_number"] == "SNP-M-102" for c in cands))
        self.assertFalse(cands[0]["linked"])
        target = cands[0]

        def accept(dlg):
            dlg.list.setCurrentRow(0)
            dlg.reason.setText("도면 개정")
            return viewer.QDialog.Accepted
        with mock.patch.object(viewer.PairDialog, "exec", accept):
            scr.on_chip("unlinked|%s" % ms["entity_id"])
        doc = project.load_manual("SNP-SAMPLE")
        self.assertTrue(doc["ops"][0]["op_id"].startswith("sl-"))
        self.assertEqual((doc["ops"][0]["op"], doc["ops"][0]["by"], doc["ops"][0]["reason"]), ("link", "검토자A", "도면 개정"))
        self.assertTrue(os.path.realpath(project.manual_path("SNP-SAMPLE")).startswith(os.path.realpath(self.tmp)))
        p = self.point("MS-L001")
        self.assertEqual((p["status"], p["origin"], p["peer"]["entity_id"]), ("linked", "manual", target["entity_id"]))
        pg = project.load("SNP-SAMPLE")                                  # 다시 만든 프로젝트 그래프도 이어짐
        link = next(l for l in pg["sheet_links"] if l["origin"] == "manual")
        self.assertEqual(link["status"], "linked")
        self.assertIn("사람 지정 · 검토자A", "\n".join(scr.link_list.item(i).text() for i in range(scr.link_list.count())))
        self.assertIsNotNone(self.win.toast_box.undo)
        self.win.toast_box.run_undo()
        self.assertEqual(project.load_manual("SNP-SAMPLE")["ops"], [])
        self.assertEqual(self.point("MS-L001")["status"], "unlinked")

    def test_unlink_then_pair_again_replaces_earlier_op(self):
        scr = self.scr
        rc = self.point("RC-L011")
        self.assertTrue(scr.unlink(rc["entity_id"]))
        self.assertEqual((self.point("RC-L011")["reason"], self.point("RC-L011")["origin"]), ("manual_unlink", "manual"))
        cand = next(c for c in viewer.pair_candidates(scr.ctx, rc["entity_id"]) if c["entity_id"] == rc["peer"]["entity_id"])
        self.assertTrue(scr.pair(rc["entity_id"], cand))
        self.assertEqual([o["op"] for o in project.load_manual("SNP-SAMPLE")["ops"]], ["link"])
        self.assertEqual(self.point("RC-L011")["status"], "linked")


if __name__ == "__main__":
    unittest.main()
