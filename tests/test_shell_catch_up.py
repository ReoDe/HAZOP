"""다시 추출 뒤 검토구간 판 이전을 사용자가 시작하는 길(nodes.catch_up)과 그 전까지 ⑤·⑥이 보이는 것. 실행: python -m unittest tests.test_shell_catch_up

배경: 다시 추출하면 그래프 판이 바뀐다. 구간 집합은 읽기만 해서는 판 이전을 하지 않고(규격 §5.2), 쓰기 명령이 파일을 읽을 때 한다. 그래서 ⑥ 화면은 '④를 열어
판 이전을 마친 뒤 하세요'만 보이고 그 길이 없었다. 여기서는 (1) nodes.catch_up이 project_lock 안에서 판 이전만 하고 이어진 수·묘비 수를 돌려주는지,
(2) 같은 판이면 아무것도 쓰지 않는지, (3) 쓰다 실패하면 옛 파일이 그대로인지, (4) ⑥이 ④로 가는 action을 주는지, (5) ⑤가 판 이전 전에는 옛 참조의 자리를
확인하지 않고 '도면에서 보기'가 다른 기호를 강조하지 않는지를 본다. 저장은 임시 작업 루트에만 한다. 실제 구독 호출 없음.
"""

import copy
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop import store_io
from hazop.shell import api, api_ie, api_nodes, api_results
from hazop.study import nodes as sn
from hazop.study import results as res
from tests.test_study_migrate import AT, DEVS, PLACES, SID, drawn

PID = "P-CATCHUP"
V1_REF = "graph-T#" + SID["V1"]
STALE_LABEL = "위치 확인 전(도면 변경 반영 전)"


def world(version, places):
    """도면 한 장의 프로젝트 그래프(노드 id는 '<시트 graph_id>/…'). 시트의 순번 id는 places에 따라 다른 자리 기호를 가리킨다."""
    from hazop.graph import project
    g = drawn(version, places)
    g["project_id"] = PID
    g["source"] = {"drawing_number": "T-1"}
    for n in g["nodes"]:
        n["local_id"] = n["entity_id"]          # 도면 화면의 구성요소 id(도면에서 보기가 쓴다)
    return project.build(PID, [g])


class Base(unittest.TestCase):
    def setUp(self):
        from hazop.app import project_ctx
        self.tmp = tempfile.mkdtemp(prefix="hazop-catchup-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.g = world("v-1", PLACES)
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp}),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                  mock.patch.object(project_ctx, "project_graph", lambda pid: self.g),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        if "nodes.catch_up" not in api.COMMANDS:
            for name in [k for k in api.COMMANDS if k.startswith("nodes.")]:
                del api.COMMANDS[name]
            api_nodes.register(api.COMMANDS)
        self.ns = sn.confirm(sn.propose(self.g, at=AT), self.g, "김검토", at=AT)
        sn.save(self.ns)
        doc = res.empty_results(self.ns, DEVS)
        cell = doc["cells"][0]
        cell["state"] = "analyzed"
        v1 = next(n["entity_id"] for n in self.g["nodes"] if n["source_object_id"] == SID["V1"])
        cell["entries"] = [{"entry_id": "e1", "origin": "ai_draft", "status": "proposed", "cause": "V1 고착", "consequence": "x", "safeguards": [],
                            "recommendation": None, "severity": 2, "frequency": 2, "risk": 2, "cause_refs": [{"ref": V1_REF}],
                            "ai_basis": {"kg_paths": [[v1]], "sources": [], "equipment_tags": [], "warnings": []}, "history": []}]
        res.save_fp(doc, PID, expect=store_io.ANY)
        self.node, self.dev = cell["node_id"], cell["deviation_id"]
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=lambda e: None, run_jobs=lambda jid, fn: fn())
        self.engine.settings.update(project_id=PID, reviewer_name="검토자A")

    def read(self, *parts):
        r = api.ReadApi(self.engine).read(list(parts), {})
        self.assertIsNotNone(r, parts)
        return json.loads(r.body.decode("utf-8"))

    def re_extract(self):
        """다시 추출한 뒤의 그래프: 순번이 밀려 같은 id가 다른 자리 기호를 가리킨다."""
        g2 = world("v-2", dict(PLACES, V1=PLACES["V2"], V2=PLACES["V3"], V3=PLACES["V1"]))
        self.g.clear()
        self.g.update(g2)

    def catch_up(self):
        return self.engine.dispatch("nodes.catch_up", {"project_id": PID}, project=PID)

    def set_bytes(self):
        with open(self.set_path(), "rb") as fh:
            return fh.read()

    def set_path(self):
        return sn.store_path(PID, self.g["graph_id"])


class CatchUpCommandTest(Base):
    def test_the_command_exists_and_the_set_is_stale_until_it_runs(self):
        self.re_extract()
        self.assertTrue(self.read("nodes")["stale"])
        out = self.catch_up()
        self.assertTrue(out["ok"], out)
        self.assertFalse(self.read("nodes")["stale"], "판 이전을 마친 집합은 지금 그래프 판과 같다")

    def test_it_reports_how_many_were_followed_and_how_many_are_lost(self):
        self.re_extract()
        d = self.catch_up()["data"]
        self.assertTrue(d["changed"])
        self.assertEqual({"matched", "tombstones", "lost_members"} <= set(d), True, d)
        self.assertIsInstance(d["matched"], int)
        self.assertIsInstance(d["tombstones"], int)

    def test_the_same_version_writes_nothing(self):
        before = self.set_bytes()
        mtime = os.path.getmtime(self.set_path())
        out = self.catch_up()
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["data"]["changed"])
        self.assertEqual(self.set_bytes(), before)
        self.assertEqual(os.path.getmtime(self.set_path()), mtime)

    def test_a_failed_write_keeps_the_old_file_and_a_retry_works(self):
        self.re_extract()
        before = self.set_bytes()
        with mock.patch("hazop.store_io.write_bytes", side_effect=OSError("디스크 가득")):
            out = self.catch_up()
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["error"]["code"], "failed")
        self.assertEqual(self.set_bytes(), before, "실패하면 옛 파일이 그대로다")
        self.assertTrue(self.read("nodes")["stale"])
        self.assertTrue(self.catch_up()["ok"], "다시 누르면 된다")
        self.assertFalse(self.read("nodes")["stale"])

    def test_the_command_refuses_another_project_and_asks_for_no_reviewer_name(self):
        self.re_extract()
        out = self.engine.dispatch("nodes.catch_up", {"project_id": "다른"}, project="다른")
        self.assertFalse(out["ok"])
        self.assertTrue(self.read("nodes")["stale"], "다른 프로젝트 ID로는 아무것도 하지 않는다")


class GuideTest(Base):
    def test_the_reason_text_names_the_real_way(self):
        from hazop.study import follow
        self.assertIn("도면 변경 반영하기", follow.STALE)
        self.assertIn("검토구간", follow.STALE)

    def test_ie_tells_the_screen_where_to_go(self):
        self.re_extract()
        s = self.read("ie")
        self.assertFalse(s["available"])
        self.assertEqual(s.get("action"), "nodes", s)
        self.assertIn("도면 변경 반영하기", s["reason"])

    def test_ie_without_a_stale_set_has_no_action(self):
        s = self.read("ie")
        self.assertNotIn("action", s)


class ResultsStaleTest(Base):
    def cell(self):
        return self.read("results", "cell", self.node, self.dev)

    def entry_detail(self):
        return self.cell()["cell"]["entries"][0]["detail"]

    def test_the_summary_says_when_the_graph_is_newer_than_the_set(self):
        self.assertFalse(self.read("results")["stale"])
        self.re_extract()
        self.assertTrue(self.read("results")["stale"])

    def test_old_refs_are_not_shown_against_the_new_graph(self):
        self.assertNotEqual(self.entry_detail()["cause_refs"][0]["label"], STALE_LABEL)
        self.re_extract()
        ref = self.entry_detail()["cause_refs"][0]
        self.assertEqual(ref["label"], STALE_LABEL)
        self.assertEqual(ref["ref"], V1_REF, "저장된 참조 값은 그대로다")
        self.assertFalse(ref["missing"])
        self.assertTrue(self.cell()["stale"])

    def test_show_on_sheet_does_not_highlight_another_symbol_before_catch_up(self):
        path = self.entry_detail()["basis"]["paths"][0]
        self.assertTrue(path["sheet"], "판이 같으면 도면에서 볼 수 있다")
        self.re_extract()
        path = self.entry_detail()["basis"]["paths"][0]
        self.assertIsNone(path["sheet"])
        self.assertEqual(path["marks"], {})
        self.assertTrue(path.get("stale"))

    def test_after_catch_up_refs_follow_the_symbol_again(self):
        self.re_extract()
        self.assertTrue(self.catch_up()["ok"])
        self.assertFalse(self.read("results")["stale"])
        ref = self.entry_detail()["cause_refs"][0]
        self.assertNotEqual(ref["label"], STALE_LABEL)


class StaleBlocksAnalysisAndExportTest(Base):
    """판 이전 전에는 ⑤ 분석 실행·Excel 내보내기가 옛 집합과 새 그래프를 섞어 쓰지 않는다(옛 참조가 새 그래프의 다른 기호로 저장·내보내짐)."""

    def stale_code(self, name, args):
        out = self.engine.dispatch(name, args, project=PID)
        return None if out["ok"] else out["error"]["code"]

    def test_run_plan_run_and_export_are_refused_until_catch_up(self):
        self.re_extract()
        for name, args in (("results.run_plan", {"scope": "all"}), ("results.run", {"scope": "all"}), ("results.export_excel", {"scope": "all"})):
            self.assertEqual(self.stale_code(name, args), "stale", name)

    def test_the_refusal_names_the_real_way(self):
        self.re_extract()
        out = self.engine.dispatch("results.run_plan", {"scope": "all"}, project=PID)
        self.assertIn("도면 변경 반영하기", out["error"]["message"])

    def test_chat_analysis_goes_through_the_same_guard(self):
        self.re_extract()
        with self.assertRaises(api.CommandError) as cm:
            api_results._run(self.engine, {"scope": "node", "node_id": self.node})
        self.assertEqual(cm.exception.code, "stale")

    def test_after_catch_up_the_plan_and_export_work_again(self):
        self.re_extract()
        self.assertTrue(self.catch_up()["ok"])
        self.assertIsNone(self.stale_code("results.run_plan", {"scope": "all"}))

    def test_a_project_without_a_node_set_is_not_blocked(self):
        os.remove(self.set_path())
        self.re_extract()
        self.assertNotEqual(self.stale_code("results.run_plan", {"scope": "all"}), "stale")


class AfterCatchUpTest(Base):
    def test_ie_opens_and_accepts_a_write_after_catch_up(self):
        self.re_extract()
        self.assertFalse(self.read("ie")["available"])
        self.assertTrue(self.catch_up()["ok"])
        s = self.read("ie")
        self.assertTrue(s["available"], s)
        out = self.engine.dispatch("ie.create_group", {"name": "그룹A", "ver": s["ver"], "rver": s.get("rver")}, project=PID)
        self.assertTrue(out["ok"], out)

    def test_a_failed_result_write_leaves_the_set_migrated_and_the_screen_follows_through_the_history(self):
        """결과 파일 쓰기만 실패하면 집합은 옮겨졌고 결과 파일은 옛 참조 그대로다. ⑤ 화면은 집합 이력으로 메모리에서 옮겨 맞게 보인다(다음 쓰기가 파일을 옮김)."""
        self.re_extract()
        rpath = res.store_path(PID, self.g["graph_id"])
        with open(rpath, "rb") as fh:
            old = fh.read()
        with mock.patch.object(res, "write", side_effect=OSError("결과 쓰기 실패")):
            self.assertTrue(self.catch_up()["ok"])
        with open(rpath, "rb") as fh:
            self.assertEqual(fh.read(), old, "결과 파일은 그대로")
        self.assertFalse(self.read("results")["stale"])
        ref = self.read("results", "cell", self.node, self.dev)["cell"]["entries"][0]["detail"]["cause_refs"][0]
        self.assertNotEqual(ref["ref"], V1_REF, "화면은 옮긴 참조를 보인다")
        self.assertNotEqual(ref["label"], STALE_LABEL)
        self.assertFalse(ref["missing"])


class ConfirmedLostTest(Base):
    def test_a_node_confirmed_with_lost_members_says_so(self):
        """확정 기록 confirmed.lost가 구간 행에 실려 화면이 '잃은 구성요소를 둔 채 확정함'을 보일 수 있다."""
        ns = sn.load(self.g)
        tomb = "lost:%s:x:1" % ns["graph_id"]
        ns["tombstones"] = {tomb: {"entity_id": "gone", "ref": None, "mark": None, "basis": None, "lost_from": "v0", "lost_at": "v1", "at": None,
                                   "legacy_key": None, "found": None}}
        ns["nodes"][0]["lost"] = [tomb]
        ns["nodes"][0]["confirmed"]["lost"] = 1
        sn.save(ns)
        row = self.read("nodes")["nodes"][0]
        self.assertEqual(row["confirmed"]["lost"], 1)
        self.assertEqual(row["lost"], 1)


if __name__ == "__main__":
    unittest.main()
