"""⑥ 초기사건 화면(hazop.app.screens.initiating)과 ⑤ 내보내기 경로. 두 도면 합성 프로젝트를 임시 작업 루트에 두고,
⑤ 결과는 파일로 저장한 것만 읽는다(화면이 보는 것과 같은 길). 네트워크·AI 호출 없음.
실행: python -m unittest tests.test_ie_screen
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openpyxl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.ie import bundle as ib  # noqa: E402
from hazop.ie import model, store  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_results_project_ui import StubApp  # noqa: E402

AT = "2026-11-09T01:00:00Z"
HINT = {"candidate": "yes", "disturbs": "yes", "challenges": "yes", "safety_functions": [], "category": "LOMFW",
        "reason": "", "origin": "human", "status": "confirmed"}


class App(StubApp):
    def __init__(self, tmp):
        super().__init__()
        self.drawing, self.reviewer, self.screens, self.went = "SNP-M-102", "김검토", {}, []

    def reviewer_name(self):
        return self.reviewer

    def go(self, index):
        self.went.append(index)
        return True


def entry(eid, status="approved", hint=None, cause="급수펌프 FW-P01A 정지"):
    e = {"entry_id": eid, "cause": cause, "consequence": "SG 수위 저하, 열제거 상실",
         "safeguards": [{"text": "보조급수 자동 기동", "role": "mitigative", "actuation": "automatic", "refs": [],
                         "ipl": None}], "recommendation": "", "severity": None, "frequency": None, "risk": None,
         "origin": "ai_draft", "status": status}
    if hint is not None:
        e["ie_hint"] = hint
    return e


class InitiatingScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication(["test"])

    def setUp(self):
        from hazop.app import project_ctx
        from hazop.study import nodes as sn
        from tests.test_project_graph import cont, sheet
        self.tmp = tempfile.mkdtemp(prefix="hazop-ie-scr-")
        self._env = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = self.tmp
        for g in (sheet("SNP-M-101", cont("C1", "TO SNP-M-102\nL-1")),
                  sheet("SNP-M-102", cont("C1", "FROM SNP-M-101\nL-1"))):
            d = paths.output_in(self.tmp, "graph", g["source"]["drawing_number"])
            os.makedirs(d)
            with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as fh:
                json.dump(g, fh)
        ctx = project_ctx.load("SNP-M-102")
        self.ns = sn.confirm(ctx.load_set()[0], ctx.pg, "EJ", at=AT)
        sn.save(self.ns)
        r = res.empty_results(self.ns, res.load_deviations())
        r["cells"][0].update(state="analyzed", entries=[
            entry("E1", hint=HINT), entry("E2", hint=dict(HINT, origin="ai_draft", status="draft")),
            entry("E3", status="proposed", hint=HINT)])
        self.write_results(r)
        self.app = App(self.tmp)
        from hazop.app.screens.initiating import InitiatingScreen
        self.scr = InitiatingScreen(self.app)
        self.addCleanup(self.scr.deleteLater)
        self.app.screens[7] = self.scr

    def tearDown(self):
        if self._env is None:
            os.environ.pop("HAZOP_WORK_ROOT", None)
        else:
            os.environ["HAZOP_WORK_ROOT"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_results(self, r):
        self.results = r
        res.save(r, self.ns.get("project_id"))

    def iec(self, eid):
        return model.iec_of(self.scr.doc)[model.key_of(self.results["graph_id"], eid)]

    def stored(self):
        return store.load(self.scr.project_id)[0]

    def test_enter_syncs_approved_entries_and_saves(self):
        self.assertTrue(self.scr.load("SNP-M-102"))
        self.assertEqual(self.scr.stack.currentIndex(), 1)
        doc = self.stored()
        self.assertEqual([c["key"].rpartition("/")[2] for c in doc["candidates"].values()], ["E1", "E2"])
        self.assertEqual(self.scr.cand_table.rowCount(), 2)
        self.assertEqual([self.scr.tabs.tabText(i) for i in range(7)],
                         ["후보 2", "그룹 0", "사건수목 표제 0", "최종상태 0", "기본사건 0", "완전성 대조", "품질 경고 0"])
        self.assertEqual(self.scr.warning_summary.text(), ib.warning_summary_text(self.scr.view))
        self.assertIn("구간 경계 결과 끊김 0건", self.scr.warning_summary.text())
        self.assertIn("완전성을 뜻하지 않음", self.scr.scope_chip.text())
        self.assertIn("⑤ 결과 기준", self.scr.basis.text())
        fp = self.scr.fp
        self.scr.load("SNP-M-102")
        self.assertEqual(self.scr.fp, fp, "다시 열어도 할 일이 없으면 저장하지 않음")

    def test_confirm_button_follows_the_same_rule_as_confirm(self):
        self.scr.load("SNP-M-102")
        e1, e2 = self.iec("E1"), self.iec("E2")
        gid = self.scr.create_group("주급수 상실", [e1])
        self.assertEqual(self.scr.group_id, gid)
        self.assertTrue(self.scr.confirm_btn.isEnabled())
        self.assertTrue(self.scr.move_selected(gid, [e2]))
        self.assertFalse(self.scr.confirm_btn.isEnabled())
        problems = [self.scr.problem_list.item(i).text() for i in range(self.scr.problem_list.count())]
        self.assertTrue(any("AI 초안" in p for p in problems), problems)
        self.assertFalse(self.scr.confirm_group())
        self.assertIn("AI 초안", self.app.messages[-1])
        self.assertTrue(self.scr.move_selected(None, [e2]))
        self.assertTrue(self.scr.confirm_group())
        self.assertEqual(self.stored()["groups"][gid]["confirmation"]["by"], "김검토")
        self.assertIn("확정 · 검토자 김검토", self.scr.group_chip.text())
        self.assertFalse(self.scr.confirm_btn.isEnabled())
        self.assertTrue(self.scr.reopen_btn.isEnabled() and not self.scr.delete_btn.isEnabled())

    def test_results_change_on_disk_demotes_on_next_enter(self):
        self.scr.load("SNP-M-102")
        gid = self.scr.create_group("주급수 상실", [self.iec("E1")])
        self.assertTrue(self.scr.confirm_group())
        r = res.edit_entry(self.results, self.results["cells"][0]["node_id"], self.results["cells"][0]["deviation_id"],
                           "E1", {"cause": "주급수 조절밸브 닫힘"}, at=AT)
        self.write_results(res.set_status(r, r["cells"][0]["node_id"], r["cells"][0]["deviation_id"], "E1", "approved",
                                          at=AT))
        self.scr.load("SNP-M-102")
        doc = self.stored()
        self.assertEqual((doc["groups"][gid]["status"], doc["history"][-1]["op"]), ("draft", "demote"))
        self.assertEqual(self.scr.view["groups"][0]["status"], "draft")

    def unapprove_on_disk(self, eid):
        cell = self.results["cells"][0]
        self.write_results(res.set_status(self.results, cell["node_id"], cell["deviation_id"], eid, "revised", at=AT))

    def test_export_rereads_results_saved_in_five_after_entering_six(self):
        self.scr.load("SNP-M-102")
        gid = self.scr.create_group("주급수 상실", [self.iec("E1")])
        self.assertTrue(self.scr.confirm_group())
        self.unapprove_on_disk("E1")  # 분할 화면 ⑤에서 승인을 풀고 저장
        out = os.path.join(self.tmp, "export", "ie.xlsx")
        os.makedirs(os.path.dirname(out))
        self.assertEqual(self.scr.export_bundle(path=out), out)
        self.assertIn("⑥을 다시 읽었습니다", self.app.messages[-1])
        with open(os.path.join(self.tmp, "export", "ie.json"), encoding="utf-8") as fh:
            b = json.load(fh)
        self.assertEqual([c["entry_id"] for c in b["candidates"]], ["E2"])
        g = next(x for x in b["groups"] if x["group_id"] == gid)
        self.assertEqual((g["status"], g["members"], g["member_count"]), ("draft", [], 0))
        self.assertEqual(self.stored()["groups"][gid]["status"], "draft", "다시 읽으며 맞춘 판을 저장")

    def test_confirm_rereads_results_and_stops_when_five_changed(self):
        self.scr.load("SNP-M-102")
        gid = self.scr.create_group("주급수 상실", [self.iec("E1")])
        self.assertTrue(self.scr.confirm_btn.isEnabled())
        self.unapprove_on_disk("E1")
        self.assertFalse(self.scr.confirm_group())
        self.assertIn("다시 확정하세요", self.app.messages[-1])
        self.assertEqual(self.stored()["groups"][gid]["status"], "draft")
        self.assertFalse(self.scr.confirm_btn.isEnabled())

    def test_split_delete_and_records(self):
        r = json.loads(json.dumps(self.results))
        r["cells"][0]["entries"].append(entry("E4", hint=HINT, cause="급수 조절밸브 오동작"))
        self.write_results(r)
        self.scr.load("SNP-M-102")
        gid = self.scr.create_group("묶음", [self.iec("E1"), self.iec("E4")])
        a, b = self.scr.split_group([self.iec("E4")])
        self.assertEqual(self.stored()["groups"][gid]["split_into"], [a, b])
        self.assertEqual(self.scr.group_id, b)
        hid = self.scr.add_heading({"name": "보조급수 기동", "actuation": "automatic"})
        self.assertTrue(hid)
        self.assertEqual(self.scr.heading_table.rowCount(), 1)
        self.assertTrue(self.scr.edit_record("heading", "H-01", {"operator_cue": "경보 FW-FAL-01"}))
        self.assertTrue(self.scr.remove_record("heading", "H-01"))
        self.assertEqual(self.scr.heading_table.rowCount(), 0)
        self.assertTrue(self.scr.delete_group(ask=False))
        self.assertEqual(self.stored()["groups"][b]["status"], "deleted")

    def test_suggest_makes_drafts_shown_hatched(self):
        self.scr.load("SNP-M-102")
        self.assertTrue(self.scr.suggest())
        g = self.scr.view["groups"][0]
        self.assertEqual((g["origin"], g["status"]), ("ai_draft", "draft"))
        from hazop.app.screens.initiating import ORIGIN_ROLE
        self.assertEqual(self.scr.heading_table.item(0, 7).data(ORIGIN_ROLE), "ai_draft")
        self.assertFalse(self.scr.suggest(), "두 번째는 더할 것이 없음")

    def test_coverage_disposition(self):
        self.scr.load("SNP-M-102")
        codes = [r["code"] for r in self.scr.view["completeness"]]
        self.scr.coverage_table.selectRow(codes.index("LOCHS"))
        self.assertTrue(self.scr.coverage_save.isEnabled())
        self.assertFalse(self.scr.set_coverage("out_of_scope", " "))
        self.assertTrue(self.scr.set_coverage("out_of_scope", "복수기 도면 미등록"))
        self.assertEqual(self.stored()["coverage"]["LOCHS"]["by"], "김검토")
        row = next(r for r in self.scr.view["completeness"] if r["code"] == "LOCHS")
        self.assertTrue(row["note"].startswith("범위 밖: 복수기 도면 미등록"))

    def test_coverage_asks_for_the_reviewer_name_when_it_is_not_set(self):
        self.scr.load("SNP-M-102")
        self.app.reviewer = ""
        self.app.set_reviewer_name = lambda name: setattr(self.app, "reviewer", name)
        with mock.patch("hazop.app.screens.initiating.QInputDialog.getText", return_value=("", False)) as ask:
            self.assertFalse(self.scr.set_coverage("out_of_scope", "복수기 도면 미등록", code="LOCHS"))
        ask.assert_called_once()
        self.assertNotIn("LOCHS", self.stored()["coverage"])
        with mock.patch("hazop.app.screens.initiating.QInputDialog.getText", return_value=(" 박검토 ", True)):
            self.assertTrue(self.scr.set_coverage("out_of_scope", "복수기 도면 미등록", code="LOCHS"))
        self.assertEqual((self.stored()["coverage"]["LOCHS"]["by"], self.app.reviewer), ("박검토", "박검토"))
        with mock.patch("hazop.app.screens.initiating.QInputDialog.getText") as ask:
            self.assertTrue(self.scr.set_coverage(None, "", code="LOCHS"), "지울 때는 이름을 묻지 않음")
        ask.assert_not_called()

    def test_export_writes_ten_sheets_and_results_menu_routes_here(self):
        from hazop.app.screens.results import ResultsScreen
        self.scr.load("SNP-M-102")
        self.scr.create_group("주급수 상실", [self.iec("E1")])
        out = os.path.join(self.tmp, "export", "ie.xlsx")
        os.makedirs(os.path.dirname(out))
        rs = ResultsScreen(self.app)
        self.addCleanup(rs.deleteLater)
        self.assertEqual(rs.export_ie_bundle(path=out), out)
        self.assertEqual(self.app.went, [7])
        self.assertEqual(sorted(os.listdir(os.path.dirname(out))), ["ie.json", "ie.xlsx"])
        self.assertIn("그룹 1건", self.app.toasts[-1])
        wb = openpyxl.load_workbook(out)
        self.assertEqual(len(wb.sheetnames), 10)
        self.assertEqual(wb["IE 그룹"]["A2"].value, "IEG-01")
        with open(os.path.join(self.tmp, "export", "ie.json"), encoding="utf-8") as fh:
            self.assertEqual([c["entry_id"] for c in json.load(fh)["candidates"]], ["E1", "E2"])

    def test_no_approved_entry_writes_nothing(self):
        r = json.loads(json.dumps(self.results))
        for e in r["cells"][0]["entries"]:
            e["status"] = "proposed"
        self.write_results(r)
        self.scr.load("SNP-M-102")
        out = os.path.join(self.tmp, "export", "ie.xlsx")
        self.assertIsNone(self.scr.export_bundle(path=out))
        self.assertIn("승인한 항목이 없어", self.app.messages[-1])
        self.assertFalse(os.path.exists(os.path.dirname(out)))

    def test_external_change_is_not_overwritten(self):
        self.scr.load("SNP-M-102")
        other, _ = model.create_group(self.stored(), "다른 창에서 만든 그룹", at=AT)
        store.save(other, expect=self.scr.fp)
        self.assertIsNone(self.scr.create_group("이 화면의 그룹", [self.iec("E1")]))
        self.assertIn("다른 곳에서 바뀌어", self.app.messages[-1])
        self.assertEqual(self.stored(), other)
        self.assertEqual([g["name"] for g in self.scr.view["groups"]], ["다른 창에서 만든 그룹"], "다시 읽은 판을 보여 줌")

    def test_unreadable_file_asks_and_backs_up_before_replacing(self):
        path = store.store_path("P")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"{broken")
        self.assertFalse(self.scr.load("SNP-M-102"))
        self.assertTrue(self.scr.banner.isVisibleTo(self.scr) and self.scr.replace_btn.isVisibleTo(self.scr))
        self.assertIsNone(self.scr.doc)
        with mock.patch("shutil.copyfileobj", side_effect=OSError("denied")):
            self.assertFalse(self.scr.replace_unreadable(ask=False))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), b"{broken")
        self.assertTrue(self.scr.replace_unreadable(ask=False))
        self.assertIn("백업했습니다", self.app.toasts[-1])
        self.assertEqual(len(self.stored()["candidates"]), 2)


if __name__ == "__main__":
    unittest.main()
