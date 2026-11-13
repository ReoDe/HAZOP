"""⑤ 결과 판정의 보류와 사유(INTENT §3.6, 웹 화면 규격 §6 'E. 결과 판정 보강', §8 UW11) 시험.
기각·보류·수정은 사유가 없으면 저장하지 않고, 수용(승인)은 사유를 받되 비워도 된다. 옛 결과 파일(0.2, 보류·사유 없음)을
그대로 읽고 옛 판정은 바꾸지 않으며, 처음 저장하기 전에 원본을 .v0.2.bak.json으로 보관한다.
실행: python -m unittest tests.test_results_hold
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.ie import bundle as ib  # noqa: E402
from hazop.ie import model  # noqa: E402
from hazop.study import convert  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from hazop.study import result_commands as rc  # noqa: E402
from tests.test_study_migrate import graph  # noqa: E402
from tests.test_study_storage import AT, DEVS, HINT, build, entry, put_entries, sref  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-hold-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)
        self.g = graph("v1")
        self.g["sheets"] = [{"graph_id": self.g["graph_id"], "drawing_number": "T-1"}]  # 내보내기가 쓰는 도면 목록
        self.ns = build(self.g, [("A", ["TK", "V1"])])
        self.doc = put_entries(res.empty_results(self.ns, DEVS), "S1", "I1", [
            entry("e1", "proposed", origin="ai_draft", recommendation="밸브 점검",
                  cause_refs=[{"ref": sref(self.g, "V1"), "failure_mode": "FTC"}], ie_hint=dict(HINT)),
            entry("e2", "proposed", origin="ai_draft")])


class VerdictTest(Base):
    def test_reasons_are_required_except_for_accept(self):
        for status in ("rejected", "on_hold", "revised"):
            with self.subTest(status):
                with self.assertRaisesRegex(ValueError, "사유"):
                    res.set_status(self.doc, "S1", "D01", "e1", status, at=AT, by="검토자")
                with self.assertRaisesRegex(ValueError, "사유"):
                    res.set_status(self.doc, "S1", "D01", "e1", status, at=AT, by="검토자", reason="   ")
        ok = res.set_status(self.doc, "S1", "D01", "e1", "approved", at=AT, by="검토자")
        self.assertEqual(ok["cells"][0]["entries"][0]["history"][-1],
                         {"at": AT, "op": "status", "from": "proposed", "to": "approved", "by": "검토자"})
        held = res.set_status(self.doc, "S1", "D01", "e1", "on_hold", at=AT, by="검토자", reason="운전 절차서 확인 뒤 판단")
        e = held["cells"][0]["entries"][0]
        self.assertEqual((e["status"], e["history"][-1]["reason"], e["history"][-1]["by"]),
                         ("on_hold", "운전 절차서 확인 뒤 판단", "검토자"))
        self.assertEqual(res.verdict(e), {"status": "on_hold", "reason": "운전 절차서 확인 뒤 판단", "by": "검토자", "at": AT})
        self.assertEqual(res.validate(held, self.ns), [])
        with self.assertRaisesRegex(ValueError, "사유"):
            res.edit_entry(self.doc, "S1", "D01", "e1", {"cause": "고친 원인"}, at=AT, by="검토자")
        edited = res.edit_entry(self.doc, "S1", "D01", "e1", {"cause": "고친 원인"}, at=AT, by="검토자", reason="태그 바로잡음")
        self.assertEqual(edited["cells"][0]["entries"][0]["history"][-1]["reason"], "태그 바로잡음")
        with self.assertRaises(ValueError):
            res.set_status(self.doc, "S1", "D01", "e1", "proposed", at=AT, reason="x")

    def test_hold_is_unreviewed_blocks_lock_and_is_not_handed_to_ie(self):
        doc = res.set_status(self.doc, "S1", "D01", "e1", "on_hold", at=AT, by="검토자", reason="보류 사유")
        doc = res.set_status(doc, "S1", "D01", "e2", "rejected", at=AT, by="검토자", reason="중복")
        self.assertEqual(res.matrix_summary(doc)["S1"]["D01"]["unreviewed"], 1)
        self.assertEqual(res.matrix_summary(doc)["S1"]["D01"]["scenarios"], 1, "보류는 살아 있는 시나리오")
        self.assertTrue(any("보류" in p for p in sn.lock_problems(self.ns, "S1", doc)))
        picked, left = ib.approved_entries(doc, self.ns)
        self.assertEqual((picked, left), ([], 2))
        facts = model.entry_facts(doc, self.ns)
        self.assertFalse(any(f["approved"] for f in facts.values()))

    def test_excel_shows_hold_and_reason(self):
        import openpyxl
        from hazop.export import study_xlsx as sx
        from tests.test_study_export import DEVS as XDEVS, NOW, sample
        r, ns, pg, span_node, _single = sample()
        r = res.set_status(r, span_node, "D01", "a2", "on_hold", at=AT, by="검토자", reason="절차서 확인 뒤")
        path, _n = sx.export(os.path.join(self.tmp, "out.xlsx"), r, ns, pg, XDEVS, now=NOW)
        wb = openpyxl.load_workbook(path)
        ws = wb[sx.SHEETS[2]]
        head = [c.value for c in ws[1]]
        rows = [dict(zip(head, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]
        held = next(row for row in rows if row["상태"] and row["상태"].startswith("보류"))
        self.assertEqual((held["상태"], held["판정 사유"]), ("보류 · AI 초안", "절차서 확인 뒤"))
        summary = {row[0].value: row[1].value for row in wb[sx.SHEETS[0]].iter_rows()}
        self.assertEqual(summary["상태별: 보류"], 1)


class OldFileTest(Base):
    def test_02_file_is_read_as_is_backed_up_and_round_trips(self):
        doc = res.set_status(self.doc, "S1", "D01", "e1", "approved", at=AT)
        doc = res.set_status(doc, "S1", "D01", "e2", "rejected", at=AT, reason="x")
        old = copy.deepcopy(doc)
        old["schema_version"] = "0.2"
        for e in old["cells"][0]["entries"]:  # 옛 판의 기록에는 사유·누가가 없다
            for h in e["history"]:
                h.pop("reason", None)
                h.pop("by", None)
        sn.save(self.ns)
        path = res.store_path(None, self.ns["graph_id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(old, fh, ensure_ascii=False)
        with open(path, "rb") as fh:
            raw = fh.read()
        loaded, fp = res.load_fp(self.ns)
        self.assertEqual(loaded["schema_version"], res.SCHEMA_VERSION)
        self.assertEqual(loaded["cells"][0]["entries"], old["cells"][0]["entries"], "옛 판정·이력은 그대로")
        self.assertEqual(res.verdict(loaded["cells"][0]["entries"][1])["reason"], None)
        res.save_fp(loaded, None, expect=fp)
        with open(convert.backup_path(path, ".v0.2.bak.json"), "rb") as fh:
            self.assertEqual(fh.read(), raw, "처음 저장 전에 원본 보관")
        again = res.load(self.ns)
        self.assertEqual(again["cells"][0]["entries"], old["cells"][0]["entries"])

    def test_newer_file_is_refused(self):
        sn.save(self.ns)
        path = res.store_path(None, self.ns["graph_id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(self.doc, schema_version="9.9"), fh)
        with self.assertRaises(ValueError):
            res.load(self.ns)


class CommandTest(Base):
    def test_result_commands(self):
        sn.save(self.ns)
        res.save(self.doc, None)
        cell = rc.execute(self.ns, "get_cell", {"node_id": "S1", "deviation_id": "D01"}, by="검토자", fingerprint=None)
        self.assertTrue(cell["ok"], cell)
        self.assertEqual([e["entry_id"] for e in cell["cell"]["entries"]], ["e1", "e2"])
        fp = cell["fingerprint"]
        bad = rc.execute(self.ns, "set_status", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e1",
                                                  "status": "on_hold"}, by="검토자", fingerprint=fp)
        self.assertFalse(bad["ok"])
        self.assertIn("사유", bad["refused"][0]["reason"])
        ok = rc.execute(self.ns, "set_status", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e1",
                                                 "status": "on_hold", "reason": "확인 필요"}, by="검토자", fingerprint=fp)
        self.assertTrue(ok["ok"], ok)
        stale = rc.execute(self.ns, "set_status", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e2",
                                                    "status": "approved"}, by="검토자", fingerprint=fp)
        self.assertFalse(stale["ok"], "읽은 뒤 파일이 바뀌면 거절")
        edit = rc.execute(self.ns, "edit_entry", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e2",
                                                   "fields": {"cause": "바뀐 원인"}, "reason": "현장 확인"},
                          by="검토자", fingerprint=ok["fingerprint"])
        self.assertTrue(edit["ok"], edit)
        self.assertEqual(res.load(self.ns)["cells"][0]["entries"][1]["cause"], "바뀐 원인")
        self.assertEqual(sorted(rc.COMMANDS), ["edit_entry", "export_excel", "export_ie_bundle", "get_cell",
                                               "get_matrix", "recheck_cell", "set_status"])
        matrix = rc.execute(self.ns, "get_matrix", {}, by="검토자", fingerprint=None)
        self.assertEqual(matrix["matrix"]["S1"]["D01"]["unreviewed"], 2)
        nopg = rc.execute(self.ns, "export_excel", {"path": os.path.join(self.tmp, "w.xlsx")}, by="검토자",
                          fingerprint=None)
        self.assertFalse(nopg["ok"])

    def test_export_commands_on_a_project_graph(self):
        from tests.test_study_export import sample
        r, ns, pg, _span, _single = sample()
        sn.save(ns)
        res.save(r, ns.get("project_id"))
        xlsx = rc.execute(ns, "export_excel", {"path": os.path.join(self.tmp, "w.xlsx")}, by="검토자",
                          fingerprint=None, pg=pg)
        self.assertTrue(xlsx["ok"] and os.path.isfile(xlsx["path"]), xlsx)
        ie = rc.execute(ns, "export_ie_bundle", {"path": os.path.join(self.tmp, "ie.xlsx")}, by="검토자",
                        fingerprint=None, pg=pg)
        self.assertTrue(ie["ok"] and os.path.isfile(ie["path"]), ie)


if __name__ == "__main__":
    unittest.main()
