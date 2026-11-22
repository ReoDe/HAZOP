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
        bak = convert.backup_path(path, ".v0.2.bak.json")
        self.assertFalse(os.path.exists(bak), "읽기만으로는 보관하지 않음")
        self.assertEqual(res.matrix_summary(res.load_view(self.ns)), res.matrix_summary(loaded))
        self.assertTrue(rc.execute(self.g, "get_matrix", {}, by=None, fingerprint=None)["ok"])
        self.assertFalse(os.path.exists(bak), "읽기 명령도 보관하지 않음")
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


class FixedViewTest(Base):
    """시험용(고정 응답) 결과 파일이 옛 판(0.2)이어도 이전 화면이 사람 판정을 버리거나 빈 결과로 덮지 않는다."""

    def screen(self):
        import types
        from hazop.app.screens.results import ResultsScreen
        fake = types.SimpleNamespace(node_set=self.ns, deviations=DEVS, _fps={})
        return fake, ResultsScreen._test_results(fake)

    def test_02_fixed_file_keeps_verdicts_and_saves_with_backup(self):
        doc = res.set_status(self.doc, "S1", "D01", "e1", "approved", at=AT)
        doc = res.set_status(doc, "S1", "D01", "e2", "rejected", at=AT, reason="x")
        path = res.test_store_path(None, self.ns["graph_id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(doc, schema_version="0.2"), fh, ensure_ascii=False)
        with open(path, "rb") as fh:
            raw = fh.read()
        fake, shown = self.screen()
        self.assertEqual([e["status"] for e in shown["cells"][0]["entries"]], ["approved", "rejected"])
        self.assertFalse(shown.get("read_only"))
        self.assertFalse(os.path.exists(convert.backup_path(path, ".v0.2.bak.json")))
        res.write(path, shown, fake._fps[path])  # 화면의 _save와 같은 호출
        with open(convert.backup_path(path, ".v0.2.bak.json"), "rb") as fh:
            self.assertEqual(fh.read(), raw)
        with open(path, encoding="utf-8") as fh:
            disk = json.load(fh)
        self.assertEqual(disk["schema_version"], res.SCHEMA_VERSION)
        self.assertEqual(len(disk["cells"][0]["entries"]), 2)

    def test_unreadable_or_newer_fixed_file_is_never_blanked(self):
        path = res.test_store_path(None, self.ns["graph_id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for body in (json.dumps(dict(self.doc, schema_version="9.9")), "{망가진"):
            with self.subTest(body[:10]):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(body)
                fake, shown = self.screen()
                self.assertTrue(shown.get("read_only"))
                with self.assertRaises(Exception):
                    res.write(path, shown, fake._fps.get(path))
                with open(path, encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), body, "파일은 그대로")

    def test_writer_refuses_to_overwrite_a_newer_file(self):
        path = res.store_path(None, self.ns["graph_id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(self.doc, schema_version="9.9"), fh)
        with self.assertRaises(Exception):
            res.write(path, self.doc)


class EditHeldTest(Base):
    def test_editing_a_held_entry_keeps_it_on_hold(self):
        held = res.set_status(self.doc, "S1", "D01", "e1", "on_hold", at=AT, by="검토자", reason="확인 필요")
        edited = res.edit_entry(held, "S1", "D01", "e1", {"cause": "고친 원인"}, at=AT, by="검토자", reason="오탈자")
        e = edited["cells"][0]["entries"][0]
        self.assertEqual((e["status"], e["cause"]), ("on_hold", "고친 원인"))
        self.assertEqual(e["history"][-1]["from"], "on_hold")
        self.assertEqual(res.verdict(e)["reason"], "오탈자")
        self.assertTrue(any("보류" in p for p in sn.lock_problems(self.ns, "S1", edited)), "잠금은 여전히 막힘")
        approved = res.set_status(self.doc, "S1", "D01", "e2", "approved", at=AT)
        again = res.edit_entry(approved, "S1", "D01", "e2", {"cause": "x"}, at=AT, by="검토자", reason="r")
        self.assertEqual(again["cells"][0]["entries"][1]["status"], "revised", "승인 항목을 고치면 다시 승인")


class CommandTest(Base):
    def test_result_commands(self):
        sn.save(self.ns)
        res.save(self.doc, None)
        cell = rc.execute(self.g, "get_cell", {"node_id": "S1", "deviation_id": "D01"}, by="검토자", fingerprint=None)
        self.assertTrue(cell["ok"], cell)
        self.assertEqual([e["entry_id"] for e in cell["cell"]["entries"]], ["e1", "e2"])
        fp = cell["fingerprint"]
        bad = rc.execute(self.g, "set_status", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e1",
                                                  "status": "on_hold"}, by="검토자", fingerprint=fp)
        self.assertFalse(bad["ok"])
        self.assertIn("사유", bad["refused"][0]["reason"])
        ok = rc.execute(self.g, "set_status", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e1",
                                                 "status": "on_hold", "reason": "확인 필요"}, by="검토자", fingerprint=fp)
        self.assertTrue(ok["ok"], ok)
        stale = rc.execute(self.g, "set_status", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e2",
                                                    "status": "approved"}, by="검토자", fingerprint=fp)
        self.assertFalse(stale["ok"], "읽은 뒤 파일이 바뀌면 거절")
        edit = rc.execute(self.g, "edit_entry", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e2",
                                                   "fields": {"cause": "바뀐 원인"}, "reason": "현장 확인"},
                          by="검토자", fingerprint=ok["fingerprint"])
        self.assertTrue(edit["ok"], edit)
        self.assertEqual(res.load(self.ns)["cells"][0]["entries"][1]["cause"], "바뀐 원인")
        self.assertEqual(sorted(rc.COMMANDS), ["edit_entry", "export_excel", "export_ie_bundle", "get_cell",
                                               "get_matrix", "recheck_cell", "set_ie_hints", "set_status"])
        matrix = rc.execute(self.g, "get_matrix", {}, by="검토자", fingerprint=None)
        self.assertEqual(matrix["matrix"]["S1"]["D01"]["unreviewed"], 2)
        self.assertEqual(cell["node_rev"], self.ns["nodes"][0]["rev"])
        old_form = rc.execute(self.ns, "get_matrix", {}, by="검토자", fingerprint=None, pg=self.g)
        self.assertEqual(old_form["matrix"], matrix["matrix"], "옛 호출 꼴(집합, pg=)은 넘긴 집합을 쓰지 않고 그래프로 읽음")
        self.assertEqual(rc.execute(self.ns, "get_matrix", {}, by="검토자", fingerprint=None)["refused"][0]["code"],
                         "bad_actor", "집합만 넘기면 거절")

    def test_export_commands_on_a_project_graph(self):
        from tests.test_study_export import sample
        r, ns, pg, _span, single = sample()
        sn.save(ns)
        res.save(r, ns.get("project_id"))
        xlsx = rc.execute(pg, "export_excel", {"path": os.path.join(self.tmp, "w.xlsx")}, by="검토자",
                          fingerprint=None)
        self.assertTrue(xlsx["ok"] and os.path.isfile(xlsx["path"]), xlsx)
        ie = rc.execute(pg, "export_ie_bundle", {"path": os.path.join(self.tmp, "ie.xlsx")}, by="검토자",
                        fingerprint=None)
        self.assertTrue(ie["ok"] and os.path.isfile(ie["path"]), ie)
        for name in ("export_excel", "export_ie_bundle"):
            out = rc.execute(pg, name, {"path": os.path.join(self.tmp, "no-such-dir", "w.xlsx")}, by="검토자",
                             fingerprint=None)
            self.assertFalse(out["ok"], name)
            self.assertEqual(out["refused"][0]["code"], "io", out)
        bad = rc.execute(pg, "set_status", {"node_id": single, "deviation_id": "D01", "entry_id": "x",
                                            "status": "approved", "reason": 5}, by="검토자", fingerprint=None)
        self.assertEqual(bad["refused"][0]["code"], "rule")

    def test_stale_or_locked_node_set_is_refused(self):
        sn.save(self.ns)
        doc = put_entries(res.empty_results(self.ns, DEVS), "S1", "I1", [entry("e1", "approved"),
                                                                         entry("e2", "approved")])
        for c in doc["cells"]:
            if not c["entries"]:
                c["state"] = "excluded"
        res.save(doc, None)
        cell = rc.execute(self.g, "get_cell", {"node_id": "S1", "deviation_id": "D01"}, by="검토자", fingerprint=None)
        self.assertTrue(cell["ok"], cell)
        sn.save(sn.lock_node(sn.load(self.g), "S1", "다른 창", res.load(sn.load(self.g))))
        self.assertEqual(res.load_fp(sn.load(self.g))[1], cell["fingerprint"], "잠가도 결과 파일 지문은 그대로")
        args = {"node_id": "S1", "deviation_id": "D01", "entry_id": "e1", "status": "rejected", "reason": "낡은 화면"}
        locked = rc.execute(self.g, "set_status", args, by="검토자", fingerprint=cell["fingerprint"])
        self.assertFalse(locked["ok"])
        self.assertIn("잠긴", locked["refused"][0]["reason"])
        old_form = rc.execute(self.ns, "set_status", args, by="검토자", fingerprint=None, pg=self.g)
        self.assertFalse(old_form["ok"], "넘긴 낡은 집합이 아니라 지금 집합으로 막음")
        stale = rc.execute(self.g, "set_status", args, by="검토자", fingerprint=None, set_rev=cell["set_rev"])
        self.assertEqual(stale["refused"][0]["code"], "stale")
        node_rev = rc.execute(self.g, "set_status", dict(args, node_rev=cell["node_rev"] + 100), by="검토자",
                              fingerprint=None)
        self.assertEqual(node_rev["refused"][0]["code"], "stale")
        self.assertEqual(next(e["status"] for c in res.load(sn.load(self.g))["cells"] for e in c["entries"]
                              if e["entry_id"] == "e1"), "approved", "디스크의 판정은 그대로")



class SetIeHintsCommandTest(Base):
    """B5 set_ie_hints(후보 IE 판정)도 다른 쓰는 명령과 같은 판정 저장 규칙을 따른다: 결과 지문 대조, 누른 사람(by) 필수,
    AI가 쓴 판정은 author로 따로, 보류 항목은 보류·사유 그대로, 제안 항목만 수정이 된다(재실행이 덮지 않게)."""
    T = [{"node_id": "S1", "deviation_id": "D01", "entry_id": "e1"}]
    H = {"candidate": "no", "disturbs": "no", "challenges": "unknown", "category": None, "safety_functions": [], "reason": "범위 밖"}

    def setUp(self):
        super().setUp()
        sn.save(self.ns)
        res.save(self.doc, None)

    def fp(self):
        return rc.execute(self.g, "get_cell", {"node_id": "S1", "deviation_id": "D01"}, by="검토자", fingerprint=None)["fingerprint"]

    def e1(self):
        return res.load(self.ns)["cells"][0]["entries"][0]

    def run_(self, by="검토자", fingerprint="now", **a):
        fp = self.fp() if fingerprint == "now" else fingerprint
        return rc.execute(self.g, "set_ie_hints", dict({"targets": self.T, "hint": self.H}, **a), by=by, fingerprint=fp)

    def test_needs_the_reader_and_the_files_current_version(self):
        before = self.e1()
        self.assertEqual(self.run_(by="")["refused"][0]["code"], "bad_actor", "누른 사람이 없으면 거절")
        self.assertEqual(self.run_(fingerprint="sha256:old")["refused"][0]["code"], "stale", "읽은 뒤 바뀐 파일에는 쓰지 않음")
        self.assertFalse(self.run_(targets=[])["ok"], "판정할 항목이 없으면 거절")
        self.assertFalse(self.run_(hint=dict(self.H, candidate="maybe"))["ok"], "판정 값 오류")
        self.assertEqual(self.e1(), before)

    def test_proposed_entry_becomes_revised_and_the_person_and_ai_author_are_kept_apart(self):
        r = self.run_(author="ai")
        self.assertTrue(r["ok"], r)
        e = self.e1()
        self.assertEqual((e["status"], e["ie_hint"]["candidate"], e["ie_hint"]["origin"]), ("revised", "no", "human"))
        row = e["history"][-1]
        self.assertEqual((row["op"], row["by"], row["author"]), ("ie_hint", "검토자", "ai"), "글은 AI, 누른 사람은 검토자")
        self.assertFalse(self.run_(author="robot")["ok"], "모르는 글쓴이는 거절")
        r = self.run_()
        self.assertNotIn("author", self.e1()["history"][-1], "사람이 쓴 판정에는 글쓴이를 달지 않음")

    def test_held_entry_stays_on_hold_with_its_reason(self):
        held = rc.execute(self.g, "set_status", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e1", "status": "on_hold",
                                                 "reason": "현장 확인 필요"}, by="검토자", fingerprint=self.fp())
        self.assertTrue(held["ok"], held)
        self.assertTrue(self.run_()["ok"])
        e = self.e1()
        self.assertEqual(e["status"], "on_hold")
        self.assertEqual((res.verdict(e)["status"], res.verdict(e)["reason"]), ("on_hold", "현장 확인 필요"), "판정 사유는 그대로")


if __name__ == "__main__":
    unittest.main()
