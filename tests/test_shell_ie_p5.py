"""새 화면 ⑥ 초기사건 P5 명령(hazop/shell/api_ie.py: FMEA 입력·MLD 가지 대조, 설계 HZ-PLN-17 §8.2). 실행: python -m unittest tests.test_shell_ie_p5

실제 저장 길(임시 작업 루트의 ⑥·FMEA·MLD 파일)로 돈다. 파일 고르기는 창 훅(pick_import), 저장 위치는 save_path 훅을 시험이 꽂는다.
"""

import json
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.ie import fmea as fm  # noqa: E402
from hazop.ie import store as ie_store  # noqa: E402
from hazop.shell import api, api_ie  # noqa: E402
from tests.test_ie_p5 import MLD, VALVE  # noqa: E402
from tests.test_shell_ie_edit import EditBase  # noqa: E402


class P5Base(EditBase):
    def setUp(self):
        super().setUp()
        for n in self.pg["nodes"]:          # S2의 구성요소를 전동 밸브로(전기·제어 구간), S1 연결점 둘에 같은 태그
            if n["entity_id"] == "graph-SNP-M-102/E":
                n.update(kind="motor_operated_valve", category="valve")
            if n["entity_id"] in ("graph-SNP-M-101/C1", "graph-SNP-M-102/C1"):
                n["tag"] = "DUP-1"

    def seen_all(self):
        """요약·그룹 상세에 더해 MLD 가지의 판정 지문(화면의 완전성 대조 보기가 보는 것)."""
        out = super().seen_all()
        out.update({"coverage:MLD:" + b["id"]: b["fp"] for b in self.read("ie", "mld")["branches"]})
        return out

    def fview(self):
        return self.read("ie", "fmea")

    def xlsx(self, name, rows):
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active.title = "FMEA"
        wb.active.append(["행 ID", "기기 태그", "고장모드", "고장모드 코드", "원인", "Severity Class"])
        for r in rows:
            wb.active.append(r)
        path = os.path.join(self.tmp, name)
        wb.save(path)
        return path

    def import_fmea(self, path):
        self.engine.hooks["pick_import"] = lambda kind, filters=None: [path] if kind == "fmea" and filters == api_ie.PICK_FILTERS["fmea"] else []
        r = self.call("ie.fmea_import", {"fver": self.fview()["fver"]})
        self.assertTrue(r["ok"], r)
        return r["data"]

    def fdo(self, name, **a):
        v = self.fview()
        args = dict({"fver": v["fver"], "seen": {"fmea:" + r["row_id"]: r["fp"] for r in v["rows"]}}, **a)
        return self.call(name, args)


class FmeaCommandTest(P5Base):
    def test_import_reimport_and_template_keep_row_ids(self):
        path = self.xlsx("a.xlsx", [["", VALVE, "열림 실패", "FTO", "구동기 고장", "II"], ["", "DUP-1", "닫힘 실패", "FTC", "x", ""],
                                    ["", "NO-SUCH", "오동작", "SO", "y", ""]])
        d = self.import_fmea(path)
        self.assertEqual((d["report"]["new"], d["report"]["unmatched"], d["unmatched"]), (3, 2, ["FM-002", "FM-003"]))
        self.assertTrue(os.path.exists(ie_store.fmea_path(self.project)))
        v = self.fview()
        self.assertEqual([r["row_id"] for r in v["rows"]], ["FM-001", "FM-002", "FM-003"])
        self.assertEqual(v["counts"]["unmatched"], 2)
        self.assertEqual([n["node_id"] for n in v["ec_nodes"] if n["ec"]], ["S2"])
        out = os.path.join(self.tmp, "tpl.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out if kind == "fmea" else None
        self.assertTrue(self.call("ie.fmea_template", {})["ok"])
        d2 = self.import_fmea(out)
        self.assertEqual((d2["report"]["new"], d2["report"]["same"]), (0, 3), "내보낸 양식을 그대로 가져오면 같은 행·같은 ID")

    def test_import_needs_the_window_hook_and_a_fresh_version(self):
        self.engine.hooks.pop("pick_import", None)
        r = self.call("ie.fmea_import", {"fver": "none"})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"))
        path = self.xlsx("a.xlsx", [["", VALVE, "열림 실패", "FTO", "c", ""]])
        self.import_fmea(path)
        self.engine.hooks["pick_import"] = lambda kind, filters=None: [path]
        r = self.call("ie.fmea_import", {"fver": "none"})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), "파일이 생긴 뒤의 'none'은 낡은 판")
        self.engine.hooks["pick_import"] = lambda kind, filters=None: []
        self.assertTrue(self.call("ie.fmea_import", {"fver": self.fview()["fver"]})["data"]["cancelled"])

    def test_approve_pick_and_seen_checks(self):
        self.import_fmea(self.xlsx("a.xlsx", [["", VALVE, "열림 실패", "FTO", "c", ""], ["", "DUP-1", "닫힘 실패", "FTC", "x", ""]]))
        r = self.fdo("ie.fmea_status", row_ids=["FM-002"], status="approved")
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"), "대응하지 않은 행은 승인 못 함")
        self.assertTrue(self.fdo("ie.fmea_edit", row_id="FM-002", fields={"entity_id": "graph-SNP-M-101/C1"})["ok"])
        old = self.fview()
        self.assertTrue(self.fdo("ie.fmea_status", row_ids=["FM-001", "FM-002"], status="approved")["ok"])
        stale = self.call("ie.fmea_status", {"fver": self.fview()["fver"], "row_ids": ["FM-001"], "status": "excluded",
                                             "seen": {"fmea:FM-001": next(r["fp"] for r in old["rows"] if r["row_id"] == "FM-001")}})
        self.assertEqual((stale["ok"], stale["error"]["code"]), (False, "stale"), "화면이 본 행과 다르면 저장하지 않는다")
        doc = ie_store.load_fmea(self.project)[0]
        self.assertEqual({r["status"] for r in doc["rows"].values()}, {"approved"})
        self.assertEqual(doc["history"][-1]["by"], "검토자A")
        self.engine.settings["reviewer_name"] = ""
        r = self.fdo("ie.fmea_status", row_ids=["FM-001"], status="excluded")
        self.assertEqual(r["error"]["code"], "bad_args")

    def test_mark_and_pending_warning_and_export(self):
        self.import_fmea(self.xlsx("a.xlsx", [["", VALVE, "열림 실패", "FTO", "c", "III"]]))
        warn = lambda: [w for w in self.read("ie")["warnings"] if w["kind"] == "fmea_pending"]  # noqa: E731
        self.assertEqual(warn()[0]["target"], "S2")
        self.assertTrue(self.fdo("ie.fmea_status", row_ids=["FM-001"], status="approved")["ok"])
        self.assertEqual(warn(), [], "승인 FMEA 행이 생기면 그 구간은 경고에서 빠진다")
        self.assertTrue(self.fdo("ie.fmea_mark", node_id="S1", mark="include")["ok"])
        self.assertEqual(warn()[0]["target"], "S1")
        self.assertEqual(self.fdo("ie.fmea_mark", node_id="S9", mark="include")["error"]["code"], "failed")
        out = os.path.join(self.tmp, "b.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        s = self.read("ie")
        self.assertTrue(self.call("ie.export", {"ver": s["ver"], "rver": s["rver"]})["ok"])
        with open(os.path.join(self.tmp, "b.json"), encoding="utf-8") as fh:
            b = json.load(fh)
        be = [x for x in b["basic_events"] if x["fmea_rows"]]
        self.assertEqual((len(be), be[0]["fmea_rows"], b["schema_version"]), (1, ["FM-001"], "0.3"))
        self.assertNotIn("III", json.dumps(b, ensure_ascii=False), "Severity Class는 묶음에 넣지 않는다")
        stored = ie_store.load(self.project)[0]
        self.assertTrue(any({"kind": "fmea", "key": "fmea:FM-001"} in v["sources"] for v in stored["basic_events"].values()),
                        "내보내기 전에 FMEA 기본사건 대응도 ⑥ 파일에 저장한다")

    def test_results_panel_bundle_has_the_fmea_basic_events_too(self):
        """분석 결과 패널의 인계 묶음(results.export_ie)도 같은 FMEA·MLD를 넣는다(두 내보내기 길이 같은 묶음)."""
        self.import_fmea(self.xlsx("a.xlsx", [["", VALVE, "열림 실패", "FTO", "c", ""]]))
        self.assertTrue(self.fdo("ie.fmea_status", row_ids=["FM-001"], status="approved")["ok"])
        out = os.path.join(self.tmp, "r.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        self.assertTrue(self.call("results.export_ie", {})["ok"])
        with open(os.path.join(self.tmp, "r.json"), encoding="utf-8") as fh:
            b = json.load(fh)
        self.assertEqual([x["fmea_rows"] for x in b["basic_events"] if x["fmea_rows"]], [["FM-001"]])
        self.assertEqual(b["fmea"]["rows_approved"], 1)

    def test_chat_functions_need_the_fmea_version(self):
        self.import_fmea(self.xlsx("a.xlsx", [["", VALVE, "열림 실패", "FTO", "c", ""]]))
        self.assertEqual(len(api_ie.view_fmea(self.engine)["rows"]), 1)
        with self.assertRaises(api.CommandError):
            api_ie.set_fmea_status(self.engine, {"row_ids": ["FM-001"], "status": "approved"})
        api_ie.set_fmea_status(self.engine, {"row_ids": ["FM-001"], "status": "approved", "fver": self.fview()["fver"]})
        with self.assertRaises(api.CommandError):
            api_ie.mark_ec_node(self.engine, {"node_id": "S1", "mark": "include"})
        api_ie.mark_ec_node(self.engine, {"node_id": "S1", "mark": "include", "fver": self.fview()["fver"]})
        self.assertEqual(ie_store.load_fmea(self.project)[0]["node_marks"], {"S1": "include"})


class MldCommandTest(P5Base):
    def import_mld(self, data=MLD):
        path = os.path.join(self.tmp, "mld.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        self.engine.hooks["pick_import"] = lambda kind, filters=None: [path] if kind == "mld" else []
        return self.call("ie.mld_import", {"mver": self.read("ie", "mld")["mver"]})

    def test_without_mld_nothing_is_loaded(self):
        v = self.read("ie", "mld")
        self.assertEqual((v["loaded"], v["branches"]), (False, []))

    def test_import_judge_link_and_export(self):
        r = self.import_mld()
        self.assertTrue(r["ok"], r)
        v = self.read("ie", "mld")
        st = {b["id"]: b for b in v["branches"]}
        self.assertEqual(set(st), {"B11", "B12", "B2"})
        self.assertEqual(st["B2"]["status"], "unmapped")
        self.assertEqual(self.do("ie.set_coverage", code="MLD:B9", disposition="out_of_scope", reason="x")["error"]["code"], "failed")
        self.ok("ie.set_coverage", code="MLD:B2", disposition="not_applicable", reason="외부 요인은 별도 PSA에서 다룸")
        self.assertEqual({b["id"]: b["status"] for b in self.read("ie", "mld")["branches"]}["B2"], "not_applicable")
        gid = self.make_group("주급수 상실", "c1")
        v = self.read("ie", "mld")
        seen = {"coverage:MLD:" + b["id"]: b["fp"] for b in v["branches"]}
        r = self.call("ie.mld_link", {"mver": v["mver"], "seen": seen, "branch_id": "B12", "group_ids": [gid]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(ie_store.load_mld(self.project)[0]["links"], {"B12": [gid]})
        stale = self.call("ie.mld_link", {"mver": v["mver"], "seen": seen, "branch_id": "B12", "group_ids": []})
        self.assertEqual(stale["error"]["code"], "stale")
        out = os.path.join(self.tmp, "m.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        s = self.read("ie")
        self.assertTrue(self.call("ie.export", {"ver": s["ver"], "rver": s["rver"]})["ok"])
        with open(os.path.join(self.tmp, "m.json"), encoding="utf-8") as fh:
            b = json.load(fh)
        self.assertEqual(b["mld"]["source"]["mld_id"], "TEST-MLD")
        self.assertEqual({x["id"]: x["status"] for x in b["mld"]["branches"]}["B12"], "covered", "그룹을 이은 가지는 '있음'")
        import openpyxl
        ws = openpyxl.load_workbook(out)["완전성 대조"]
        head = [c.value for c in ws[1]]
        self.assertEqual(head[-3:], ["MLD 가지", "MLD 대응", "MLD 출처"])

    def test_bad_mld_is_refused_and_nothing_is_written(self):
        bad = dict(MLD, branches=MLD["branches"] + [{"id": "Z", "name": "z", "parent": "NONE", "categories": []}])
        r = self.import_mld(bad)
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"))
        self.assertIn("없는 부모", r["error"]["message"])
        self.assertFalse(os.path.exists(ie_store.mld_path(self.project)))


if __name__ == "__main__":
    unittest.main()
