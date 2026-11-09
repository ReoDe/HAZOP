"""④ 검토구간 화면이 프로젝트 그래프(도면 2장을 이은 것)와 프로젝트 구간 집합을 쓰는지. 실행:
QT_QPA_PLATFORM=offscreen python -m unittest tests.test_study_project_ui

임시 작업 루트에 도면 SNP-M-101·102(서로 TO/FROM 연결점으로 이어짐)의 최소 추출·그래프를 만든다(SVG 없음, 그래프 보기).
실제 데이터 폴더에 쓰지 않는다. 네트워크·AI 호출 없음.
"""

import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from tests.test_app import tearDownModule  # noqa: E402,F401
from tests.test_project_graph import cont, sheet  # noqa: E402

STUDY = 5
A, B = "SNP-M-101", "SNP-M-102"


# 배관에 이어지지 않은 T: 스크리닝 제외 구간 하나를 만든다(④ 접기·꺼내기 시험)
LONE_TEE = {"entity_id": "T9", "node_type": "drawing_object", "kind": "tee", "category": "piping_element",
            "tag": None, "label_text": "", "attributes": {}, "source_object_id": "T9"}


def write_drawing(work, dn, graph):
    """출력/추출/<dn>/extraction.json(SVG 없음)과 출력/그래프/<dn>/graph.json. 추출 이름 = 도면번호."""
    for i, n in enumerate(graph["nodes"]):
        n["local_id"] = "L-" + n["entity_id"]
        n["position"] = [40 + 60 * i, 80]
    for sub, doc in (("추출", {"drawing": {"drawing_number": dn}, "coordinate_system": {}, "objects": []}),
                     ("그래프", graph)):
        folder = os.path.join(work, "출력", sub, dn)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "extraction.json" if sub == "추출" else "graph.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)


class StudyProjectUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-study-project-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        cls.sheets = {A: sheet(A, cont("C1", "TO %s\nL-1" % B), valve=True, extra=[LONE_TEE]), B: sheet(B, cont("C1", "FROM %s\nL-1" % A), valve=True)}
        for dn, g in cls.sheets.items():
            write_drawing(os.environ["HAZOP_WORK_ROOT"], dn, g)
        from hazop.app import make_application
        cls.qapp = make_application(["test"])
        cls.settings = os.path.join(cls.tmp, "settings.json")

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tearDown(self):
        from hazop.study import nodes
        shutil.rmtree(nodes.store_dir(), ignore_errors=True)

    def open_study(self, drawing):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=self.settings, ask_reviewer=False)
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        win.resize(1440, 860)
        win.show()
        win.go(STUDY)
        scr = win.screens[STUDY]
        scr.select_drawing(drawing)
        self.assertEqual(scr.combo.currentText(), drawing)
        self.assertEqual(scr.stack.currentIndex(), 1, scr.warn.label.text())
        return win, scr

    @staticmethod
    def rows(scr):
        return {scr.node_list.item(i).data(0x0100): scr.node_list.item(i) for i in range(scr.node_list.count())}

    def spanning(self, scr):
        return next(n for n in scr.view["nodes"] if n["spans_drawings"])

    def test_cross_drawing_node_label_counts_and_filter(self):
        from hazop.app import project_ctx
        _win, scr = self.open_study(B)
        self.assertEqual(scr.ctx.drawing_number, B)
        node = self.spanning(scr)
        row = self.rows(scr)[node["node_id"]]
        self.assertIn("[101 → 102]", row.text())
        self.assertTrue(row.text().endswith("⇄"), "여러 도면에 걸친 구간은 ⇄")
        here, total = node["members_by_drawing"][B], node["member_count"]
        self.assertLess(here, total)
        self.assertEqual(row.data(0x0101), "%d/%d" % (here, total), "개수 칸 = 이 도면 / 전체")
        self.assertIn("이 도면 %d / 전체 %d" % (here, total), row.toolTip())
        self.assertIn(project_ctx.boundary_text(node), row.toolTip())
        self.assertIn("프로젝트 100% · 이 도면 100%", scr.kpi.text())

        only_a = [n["node_id"] for n in scr.view["nodes"] if n["drawings"] == [A]]
        self.assertTrue(only_a, "픽스처에 101에만 있는 구간이 있어야 함")
        self.assertEqual(scr.scope.currentText(), "이 도면 구간")
        self.assertFalse(set(only_a) & set(self.rows(scr)), "이 도면 구간에는 101 전용 구간이 없음")
        scr.scope.setCurrentIndex(1)
        self.assertEqual(set(self.rows(scr)), {n["node_id"] for n in scr.node_set["nodes"]
                                               if n["screen"]["status"] != "excluded"},
                         "프로젝트 전체 = 모든 구간(스크리닝 제외 구간은 접음)")
        self.assertEqual([k for _t, k in scr.explorer_items()], [n["node_id"] for n in scr.node_set["nodes"]])
        self.assertTrue(any("⇄" in t for t, _k in scr.explorer_items()))

        self.assertTrue(scr.select_node(only_a[0]))
        self.assertFalse(scr.node_card.isHidden())
        self.assertIn("이 도면에는 이 구간의 구성요소가 없습니다", scr.node_text.text())
        self.assertEqual([b.text() for b in scr.jump_buttons], ["%s에서 보기" % A])
        scr.jump_buttons[0].click()
        self.assertEqual(scr.combo.currentText(), A)
        self.assertEqual(scr.current_node_id(), only_a[0], "다른 도면에서 보기 = 그 도면에서 같은 구간")

    def test_chip_switches_drawing_and_keeps_node(self):
        win, scr = self.open_study(A)
        node = self.spanning(scr)
        self.assertEqual(scr.drawing_chips()[0]["text"], "%s → %s에서 계속" % (node["node_id"], B), "전체 보기에도 칩")
        self.assertTrue(scr.select_node(node["node_id"]))
        self.assertIn(node["node_id"], scr.node_text.text() + " ".join(b.text() for b in scr.jump_buttons))
        chips = scr.drawing_chips()
        self.assertEqual(len(chips), 1)
        self.assertEqual(chips[0]["local_id"], "L-C1")
        self.assertEqual(chips[0]["kind"], "link")
        win._chip_clicked(chips[0]["key"])
        self.assertEqual(scr.combo.currentText(), B)
        self.assertEqual(scr.current_node_id(), node["node_id"], "상대 도면에서 같은 구간이 선택된 채로 열림")
        self.assertEqual([b.text() for b in scr.jump_buttons], ["%s → %s에서 계속" % (node["node_id"], A)])
        self.assertTrue(all(b.isEnabled() for b in scr.jump_buttons))
        scr.jump_buttons[0].click()
        self.assertEqual((scr.combo.currentText(), scr.current_node_id()), (A, node["node_id"]))

        name, why = scr._chip_target({"name": None, "drawing": "SNP-M-201"})
        self.assertIsNone(name)
        self.assertIn("SNP-M-201 추출 결과가 없어", why)
        self.assertFalse(scr.on_chip("S1|"))
        self.assertFalse(scr.on_chip("%s|다른프로젝트-%s" % (node["node_id"], B)), "이 화면이 달지 않은 칩 key는 무시")
        self.assertEqual(scr.combo.currentText(), A)

    def test_edit_on_project_set_and_component_click(self):
        from hazop.study import nodes
        _win, scr = self.open_study(A)
        node = self.spanning(scr)
        scr.select_node(node["node_id"])
        self.assertTrue(scr.rename_current("써지 배관"))
        saved = nodes.load(scr.graph)
        self.assertEqual(saved["graph_id"], "project-P", "저장은 프로젝트 집합")
        self.assertNotIn("display_name", saved["nodes"][0], "저장본에 표기 사본이 섞이지 않음")
        self.assertIn("써지 배관", self.rows(scr)[node["node_id"]].text())
        other = next(m for m in node["members"] if scr._drawing_of(m) == B)
        texts = [scr.member_list.item(i).text() for i in range(scr.member_list.count())]
        self.assertTrue(any(t.endswith("(102)") for t in texts), "다른 도면 구성요소는 (102)")
        self.assertIn(other, [scr.member_list.item(i).data(0x0100) for i in range(scr.member_list.count())])
        scr.on_node({"entity_id": "E", "local_id": "L-E"})
        self.assertEqual(scr.picked_entity, "graph-%s/E" % A, "뷰어의 도면 안 ID를 프로젝트 ID로")

    def test_repropose_after_reopen_keeps_the_confirmed_snapshot(self):
        from hazop.study import nodes
        _win, scr = self.open_study(A)
        nodes.save(nodes.reopen(nodes.confirm(scr.node_set, scr.graph, "EJ"), at="2026-11-09T00:00:00Z"))
        _win, scr = self.open_study(A)
        self.assertTrue(scr.repropose(ask=False))
        prev = nodes.load(scr.graph)["previous"][-1]
        self.assertTrue(prev["study_nodes_ref"]["confirmed_at"])
        self.assertTrue(prev["nodes"])

    def test_confirm_after_reopen_saves_the_carried_results_for_every_screen(self):
        from hazop.study import nodes, results as res
        _win, scr = self.open_study(A)
        first = nodes.confirm(scr.node_set, scr.graph, "EJ", at="2026-11-09T00:00:00Z")
        nodes.save(first)
        r = res.empty_results(first, res.load_deviations())
        r["cells"][0].update(state="analyzed", entries=[
            {"entry_id": "e1", "origin": "ai_draft", "status": "approved", "cause": "c"}])
        res.save(r, first["project_id"])
        nodes.save(nodes.reopen(first, at="2026-11-09T00:00:00Z"))
        _win, scr = self.open_study(A)
        self.assertTrue(scr.confirm("EJ", ack=True))
        now = nodes.load(scr.graph)
        saved = res.load(now)
        self.assertFalse(res.is_stale(saved, now), "⑤를 열기 전에도 디스크 결과가 새 확정본 것")
        self.assertEqual([e["status"] for c in saved["cells"] for e in c["entries"]], ["approved"])

    def test_exclusion_bucket_is_folded_taken_out_and_acknowledged(self):
        from hazop.study import nodes
        _win, scr = self.open_study(A)
        self.assertIn("제외 1개 접음", scr.list_head.text())
        self.assertNotIn(self.bucket_id(scr), self.rows(scr))
        scr.show_excluded.setChecked(True)
        self.assertIn(self.bucket_id(scr), self.rows(scr))
        self.assertFalse(scr.confirm("EJ", ack=False), "제외 구간을 확인하지 않으면 확정하지 않는다")
        scr.select_node(self.bucket_id(scr))
        self.assertTrue(scr.take_out_act.isEnabled())
        self.assertTrue(scr.take_out_selected())
        self.assertEqual([n for n in scr.node_set["nodes"] if n["screen"]["status"] == "excluded"], [])
        keep = scr.node_set["nodes"][0]["node_id"]
        scr.select_node(keep)
        self.assertFalse(scr.exclude_current(" "), "이유 없이 제외로 옮기지 않는다")
        self.assertTrue(scr.exclude_current("검토 범위 밖"))
        self.assertTrue(scr.confirm("EJ", ack=True))
        self.assertEqual(nodes.load(scr.graph)["status"], "confirmed")

    def test_selecting_a_folded_bucket_unfolds_it(self):
        _win, scr = self.open_study(A)
        scr.scope.setCurrentIndex(1)
        scr.select_node(scr.node_set["nodes"][0]["node_id"])
        self.assertTrue(scr.select_node(self.bucket_id(scr)))
        self.assertEqual(scr.current_node_id(), self.bucket_id(scr))
        self.assertTrue(scr.show_excluded.isChecked())

    @staticmethod
    def bucket_id(scr):
        return next(n["node_id"] for n in scr.node_set["nodes"] if n["screen"]["status"] == "excluded")

    def test_migration_notice_from_old_per_drawing_set(self):
        from hazop.study import nodes
        nodes.save(nodes.propose(self.sheets[A]))
        win, scr = self.open_study(A)
        self.assertFalse(scr.notice_bar.isHidden())
        self.assertIn("프로젝트 구간 ID로 옮겼습니다", scr.notice_bar.label.text())
        self.assertIn("옮겼습니다", win.toast_box.label.text())
        self.assertTrue(scr.saved)
        self.assertEqual(nodes.load(scr.graph)["graph_id"], "project-P")
        self.assertTrue(scr.confirm("검토자A", ack=True))
        self.assertTrue(scr.notice_bar.isHidden(), "다시 확정하면 알림을 내림")


if __name__ == "__main__":
    unittest.main()
