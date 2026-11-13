"""초기사건 P5: FMEA 입력과 주논리도(MLD) 가지 대조(설계 HZ-PLN-17 §8.2). 실행: python -m unittest tests.test_ie_p5

엔진(hazop.ie.fmea·mld·store·bundle)만 본다. 화면 명령은 tests.test_shell_ie_p5. 표본은 tests.test_ie_bundle.ie_sample()에
전기·제어 구성요소와 같은 태그 둘을 더한 것이다. MLD는 '시험용 가상 MLD'다(앱에는 MLD 자료를 넣지 않는다, §8.2 질문 6).
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.ie import bundle as ib  # noqa: E402
from hazop.ie import bundle_xlsx as ix  # noqa: E402
from hazop.ie import fmea as fm  # noqa: E402
from hazop.ie import mld as ml  # noqa: E402
from hazop.ie import model  # noqa: E402
from hazop.ie import store  # noqa: E402
from tests.test_ie_bundle import NOW, ie_sample  # noqa: E402

AT = "2026-11-14T01:00:00Z"
VALVE = "SNP-M-102-E"          # 표본에서 S2 구간의 유일한 구성요소(승인 항목 b1c가 있는 구간)


def sample():
    """(results, node_set, pg). S2의 구성요소를 전동 밸브로 바꿔 전기·제어 구간이 되게 하고, S1의 연결점 둘에 같은 태그를 준다."""
    r, ns, pg = ie_sample()
    pg = copy.deepcopy(pg)
    for n in pg["nodes"]:
        if n["entity_id"] == "graph-SNP-M-102/E":
            n.update(kind="motor_operated_valve", category="valve")
        if n["entity_id"] in ("graph-SNP-M-101/C1", "graph-SNP-M-102/C1"):
            n["tag"] = "DUP-1"
    return r, ns, pg


def rows(*items):
    """양식 한 줄들(가져오기 입력 꼴)."""
    out = []
    for i, it in enumerate(items, 2):
        out.append(dict({"tag": VALVE, "failure_mode": "열림 실패", "failure_code": "FTO", "cause": "구동기 고장"}, line=i, **it))
    return out


MLD = {"kind": "hazop_mld", "schema_version": "0.1", "mld_id": "TEST-MLD", "title": "시험용 가상 MLD", "revision": "A",
       "reactor_type": "PWR(시험)", "source": "시험 자료",
       "branches": [{"id": "B0", "name": "노심 손상", "parent": None, "categories": []},
                    {"id": "B1", "name": "열제거 상실", "parent": "B0", "categories": []},
                    {"id": "B11", "name": "주급수 상실", "parent": "B1", "categories": ["LOMFW"]},
                    {"id": "B12", "name": "계측용 공기 상실", "parent": "B1", "categories": ["LOIA"]},
                    {"id": "B2", "name": "외부 요인", "parent": "B0", "categories": []}]}


class FmeaRowsTest(unittest.TestCase):
    def setUp(self):
        self.r, self.ns, self.pg = sample()
        self.doc = fm.empty("P")

    def imp(self, doc, items, name="fmea.xlsx"):
        return fm.import_rows(doc, items, self.pg, self.ns, name, "검토자A", at=AT)

    def test_import_matches_tags_and_ids_stay_on_reimport(self):
        doc, rep = self.imp(self.doc, rows({}, {"failure_mode": "닫힘 실패", "failure_code": "FTC"}, {"tag": "DUP-1"}, {"tag": "NO-SUCH"}))
        self.assertEqual(rep["new"], ["FM-001", "FM-002", "FM-003", "FM-004"])
        r1 = doc["rows"]["FM-001"]
        self.assertEqual((r1["match"], r1["ref"], r1["node_id"], r1["equipment_kind"]), ("ok", "graph-SNP-M-102#E", "S2", "motor_operated_valve"))
        self.assertEqual(doc["rows"]["FM-003"]["match"], "many")
        self.assertEqual(doc["rows"]["FM-004"]["match"], "none")
        self.assertEqual(rep["unmatched"], ["FM-003", "FM-004"])
        again, rep2 = self.imp(doc, rows({}, {"failure_mode": "닫힘 실패", "failure_code": "FTC"}, {"tag": "DUP-1"}, {"tag": "NO-SUCH"},
                                         {"failure_mode": "오동작", "failure_code": "SO"}))
        self.assertEqual(rep2["new"], ["FM-005"], "같은 행은 같은 ID, 새 행만 새 번호")
        self.assertEqual(rep2["same"], ["FM-001", "FM-002", "FM-003", "FM-004"])
        by_id, rep3 = self.imp(again, [dict(rows({"cause": "구동기 고장(고침)"})[0], row_id="FM-001")])
        self.assertEqual(rep3["changed"], ["FM-001"], "행 ID 칸이 있으면 그 행을 고친다")
        self.assertEqual(sorted(rep3["missing"]), ["FM-002", "FM-003", "FM-004", "FM-005"])
        self.assertFalse(by_id["rows"]["FM-002"]["in_last_import"], "이번 파일에 없는 행은 지우지 않고 표시만")
        self.assertEqual(fm.problems(by_id), [])

    def test_approve_needs_a_match_and_a_changed_row_reopens(self):
        doc, _ = self.imp(self.doc, rows({}, {"tag": "NO-SUCH"}))
        with self.assertRaises(ValueError):
            fm.set_status(doc, ["FM-002"], "approved", "검토자A")
        with self.assertRaises(ValueError):
            fm.set_status(doc, ["FM-001"], "approved", "")
        doc = fm.set_status(doc, ["FM-001"], "approved", "검토자A", at=AT)
        self.assertEqual(doc["history"][-1]["by"], "검토자A")
        doc2, rep = self.imp(doc, rows({"effect": "급수 차단"}))
        self.assertEqual((rep["reopened"], doc2["rows"]["FM-001"]["status"]), (["FM-001"], "imported"),
                         "승인한 행의 내용이 다시 가져오기로 바뀌면 가져옴으로 돌아간다")

    def test_person_picks_the_component_for_an_unmatched_row(self):
        doc, _ = self.imp(self.doc, rows({"tag": "DUP-1"}))
        doc = fm.edit_row(doc, "FM-001", {"entity_id": "graph-SNP-M-101/C1"}, self.pg, self.ns, at=AT)
        r = doc["rows"]["FM-001"]
        self.assertEqual((r["match"], r["ref"], r["node_id"]), ("human", "graph-SNP-M-101#C1", "S1"))
        again, _rep = self.imp(doc, rows({"tag": "DUP-1"}))
        self.assertEqual(again["rows"]["FM-001"]["match"], "human", "다시 가져와도 사람이 고른 대응은 남는다")
        with self.assertRaises(ValueError):
            fm.edit_row(doc, "FM-001", {"entity_id": "없는-구성요소"}, self.pg, self.ns)
        with self.assertRaises(ValueError):
            fm.edit_row(doc, "FM-001", {"failure_code": "XYZ"}, self.pg, self.ns)

    def test_template_round_trip_keeps_ids_and_never_runs_formulas(self):
        tmp = tempfile.mkdtemp(prefix="hazop-fmea-")
        self.addCleanup(shutil.rmtree, tmp, True)
        doc, _ = self.imp(self.doc, rows({}, {"failure_mode": "=1+1", "failure_code": ""}))
        path = os.path.join(tmp, "t.xlsx")
        fm.template_workbook(doc, [("S2", VALVE, "motor_operated_valve")]).save(path)
        got, bad = fm.read_rows(path)
        self.assertEqual(bad, [])
        self.assertEqual([g["row_id"] for g in got], ["FM-001", "FM-002"])
        self.assertTrue(got[1]["failure_mode"].endswith("=1+1"), "수식 모양 글자는 글로 남는다")
        again, rep = self.imp(doc, got)
        self.assertEqual(rep["new"], [])

    def test_english_headers_are_read_and_missing_headers_are_refused(self):
        import openpyxl
        tmp = tempfile.mkdtemp(prefix="hazop-fmea-")
        self.addCleanup(shutil.rmtree, tmp, True)
        wb = openpyxl.Workbook()
        wb.active.append(["Component", "Failure Mode", "Cause"])
        wb.active.append([VALVE, "FTO fail to open", "actuator"])
        p = os.path.join(tmp, "en.xlsx")
        wb.save(p)
        got, bad = fm.read_rows(p)
        self.assertEqual((bad, got[0]["tag"], fm.code_of(got[0]["failure_mode"])), ([], VALVE, "FTO"))
        wb = openpyxl.Workbook()
        wb.active.append(["아무 열"])
        wb.save(p)
        self.assertEqual(fm.read_rows(p)[0], [])
        self.assertTrue(fm.read_rows(p)[1])


class FmeaBundleTest(unittest.TestCase):
    def setUp(self):
        self.r, self.ns, self.pg = sample()
        doc, _ = fm.import_rows(fm.empty("P"), rows({}, {"failure_mode": "닫힘 실패", "failure_code": "FTC"}), self.pg, self.ns, "f.xlsx",
                                "검토자A", at=AT)
        self.fdoc = fm.set_status(doc, ["FM-001"], "approved", "검토자A", at=AT)      # FM-002는 가져옴 상태로 둔다

    def bundle(self, fdoc=None, ie_doc=None, mld=None):
        fdoc = self.fdoc if fdoc is None else fdoc
        ie = store.sync_all(ie_doc or model.empty("P"), self.r, self.ns, fdoc)
        return ib.build_bundle(self.r, self.ns, self.pg, ie, NOW, fmea=fdoc, mld=mld), ie

    def test_approved_rows_become_basic_event_sources_and_others_are_nowhere(self):
        b, ie = self.bundle()
        be = [x for x in b["basic_events"] if "fmea" in x["source_kinds"]]
        self.assertEqual(len(be), 1)
        self.assertEqual((be[0]["fmea_rows"], be[0]["tag"], be[0]["failure_mode"]), (["FM-001"], VALVE, "FTO"))
        self.assertNotIn("FM-002", ib.dumps(b), "승인하지 않은 FMEA 행은 묶음 어디에도 없다")
        self.assertEqual((b["schema_version"], b["fmea"]["rows_approved"], b["fmea"]["rows_total"]), ("0.3", 1, 2))
        row = ix.basic_event_row(be[0])
        self.assertIn("FMEA 행(FM-001)", row[10])
        text = ib.dumps(b)
        self.assertNotIn("구동기 고장", text, "FMEA 행 내용(원인 등)은 묶음에 넣지 않는다(질문 5)")

    def test_basic_event_id_is_kept_when_approval_is_lifted_and_given_back(self):
        _b, ie = self.bundle()
        bid = next(k for k, v in ie["basic_events"].items() if {"kind": "fmea", "key": "fmea:FM-001"} in v["sources"])
        off = fm.set_status(self.fdoc, ["FM-001"], "imported", "검토자A", at=AT)
        b2, ie2 = self.bundle(off, ie)
        self.assertNotIn(bid, [x["be_id"] for x in b2["basic_events"]], "승인이 풀리면 묶음에서 빠진다")
        on = fm.set_status(off, ["FM-001", "FM-002"], "approved", "검토자A", at=AT)
        b3, ie3 = self.bundle(on, ie2)
        self.assertIn(bid, [x["be_id"] for x in b3["basic_events"]], "다시 승인하면 같은 기본사건 ID")
        new = [x["be_id"] for x in b3["basic_events"] if x["fmea_rows"] == ["FM-002"]]
        self.assertTrue(new and new[0] != bid)

    def test_same_component_and_mode_merges_with_the_hazop_basic_event(self):
        ie = model.sync(model.empty("P"), self.r, node_set=self.ns, at=AT)
        ie["basic_events"]["BE-001"] = {"key": "graph-SNP-M-102#E|FTO", "ref": "graph-SNP-M-102#E", "tag": VALVE, "name": "x",
                                        "equipment_kind": "", "system": "", "failure_mode": "FTO", "failure_text": "",
                                        "sources": [], "heading_ids": [], "origin": "ai_draft", "status": "live"}
        ie["counters"]["BE"] = 1
        synced = fm.sync_basic_events(ie, self.fdoc, at=AT)
        self.assertEqual(len(synced["basic_events"]), 1)
        self.assertEqual(synced["basic_events"]["BE-001"]["sources"], [{"kind": "fmea", "key": "fmea:FM-001"}])
        self.assertIs(fm.sync_basic_events(synced, self.fdoc), synced, "두 번 돌려도 더하는 것이 없다")

    def test_fmea_pending_follows_approved_rows_and_person_marks(self):
        nothing, _ = self.bundle(fm.empty("P"))
        self.assertEqual(next(w for w in nothing["warnings"] if w["kind"] == "fmea_pending")["target"], "S2")
        b, _ = self.bundle()
        self.assertFalse([w for w in b["warnings"] if w["kind"] == "fmea_pending"], "승인 FMEA 행이 있는 구간은 빠진다")
        shared = copy.deepcopy(self.ns)          # 구성요소가 두 구간에 걸치면 행 하나가 두 구간을 모두 채운다
        for n in shared["nodes"]:
            if n["node_id"] == "S1":
                n["members"] = n["members"] + ["graph-SNP-M-102/E"]
        self.assertEqual(fm.done_nodes(shared, self.fdoc), {"S1", "S2"})
        marked = fm.set_node_mark(fm.set_node_mark(fm.empty("P"), "S2", "exclude"), "S1", "include")
        b2, _ = self.bundle(marked)
        self.assertEqual(next(w for w in b2["warnings"] if w["kind"] == "fmea_pending")["target"], "S1",
                         "사람 표시가 규칙보다 앞선다(S2 뺌, S1 넣음)")

    def test_mld_columns_and_branch_status(self):
        sdoc = ml.import_mld(ml.empty("P"), MLD, "test-mld.json", "검토자A", {"LOMFW", "LOIA", "LOOP"}, at=AT)
        b, ie = self.bundle(mld=sdoc)
        rows_ = {r["code"]: r for r in b["completeness"]}
        self.assertEqual([x["id"] for x in rows_["LOMFW"]["mld_branches"]], ["B11"])
        st = {x["id"]: x["status"] for x in b["mld"]["branches"]}
        self.assertEqual(set(st), {"B11", "B12", "B2"}, "잎 가지만 대조한다")
        self.assertEqual(st["B2"], "unmapped")
        self.assertEqual(rows_["LOMFW"]["mld_status"], "covered" if st["B11"] == "covered" else "gap")
        tail = b["completeness"][-1]
        self.assertEqual((tail["name_ko"], [x["id"] for x in tail["mld_branches"]]), ("범주 없는 MLD 가지", ["B2"]))
        linked = ml.set_links(sdoc, "B2", [], at=AT)
        self.assertIs(linked, sdoc)
        ie2 = model.set_coverage(ie, "MLD:B2", "not_applicable", "외부 요인은 별도 PSA", "검토자A", at=AT)
        b2 = ib.build_bundle(self.r, self.ns, self.pg, ie2, NOW, fmea=self.fdoc, mld=sdoc)
        self.assertEqual({x["id"]: x["status"] for x in b2["mld"]["branches"]}["B2"], "not_applicable")
        row = ix.completeness_row(rows_["LOMFW"], ix._mld_source(b))
        self.assertEqual(row[7:], ("B11 주급수 상실", ix.MLD_STATUS[rows_["LOMFW"]["mld_status"]], "test-mld.json 판 A"))

    def test_without_mld_the_columns_are_empty_and_the_guide_says_so(self):
        b, _ = self.bundle()
        self.assertIsNone(b["mld"])
        self.assertTrue(all(r["mld_branches"] == [] and r["mld_status"] is None for r in b["completeness"]))
        guide = dict(ix.guide_rows(b))
        self.assertIn("MLD를 받지 않아", guide["MLD"])
        self.assertIn("승인한 FMEA 행 1건", guide["FMEA"])

    def test_old_bundle_is_read_with_upgrade(self):
        b, _ = self.bundle()
        old = json.loads(ib.dumps(b))
        old["schema_version"] = "0.2"
        for x in old["basic_events"]:
            x.pop("fmea_rows")
        for r in old["completeness"]:
            r.pop("mld_branches")
            r.pop("mld_status")
        old.pop("mld")
        old.pop("fmea")
        up = ib.upgrade(old)
        self.assertEqual((up["schema_version"], up["upgraded_from"], up["mld"], up["fmea"]), ("0.3", "0.2", None, None))
        self.assertTrue(all("fmea_rows" in x for x in up["basic_events"]))
        self.assertIs(ib.upgrade(b), b)
        with self.assertRaises(ValueError):
            ib.upgrade(dict(old, schema_version="9.9"))


class MldValidateTest(unittest.TestCase):
    def test_bad_files_are_refused_with_reasons(self):
        codes = {"LOMFW", "LOIA"}
        self.assertEqual(ml.validate(MLD, codes | {"LOOP"}), [])
        bad = copy.deepcopy(MLD)
        bad["branches"] += [{"id": "B11", "name": "중복", "parent": None, "categories": []},
                            {"id": "X", "name": "고아", "parent": "없음", "categories": ["NOPE"]}]
        msgs = " ".join(ml.validate(bad, codes))
        for word in ("중복", "없는 부모", "기준표에 없는 범주 코드"):
            self.assertIn(word, msgs)
        loop = {"kind": "hazop_mld", "branches": [{"id": "A", "name": "a", "parent": "B"}, {"id": "B", "name": "b", "parent": "A"}]}
        self.assertIn("순환", " ".join(ml.validate(loop)))
        with self.assertRaises(ValueError):
            ml.import_mld(ml.empty("P"), bad, "x.json", "검토자A", codes)
        self.assertTrue(ml.validate({"kind": "other"}))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-p5store-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp})
        p.start()
        self.addCleanup(p.stop)

    def test_files_sit_next_to_the_ie_file_and_stale_writes_are_refused(self):
        doc, fp = store.load_fmea("P")
        self.assertIsNone(fp)
        fp1 = store.save_fmea(doc, expect=None)
        self.assertEqual(os.path.dirname(store.fmea_path("P")), os.path.dirname(store.store_path("P")))
        self.assertTrue(store.fmea_path("P").endswith("P.fmea.json"))
        changed = fm.set_node_mark(doc, "S1", "include")
        store.save_fmea(changed, expect=fp1)
        with self.assertRaises(store.Conflict):
            store.save_fmea(fm.set_node_mark(doc, "S2", "include"), expect=fp1)
        m, mfp = store.load_mld("P")
        self.assertIsNone(m["mld"])
        store.save_mld(m, expect=mfp)
        with open(store.fmea_path("P"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        with self.assertRaises(store.Unreadable):
            store.load_fmea("P")


if __name__ == "__main__":
    unittest.main()
