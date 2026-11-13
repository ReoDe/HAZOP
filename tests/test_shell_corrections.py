"""새 웹 화면의 도면 고치기(hazop/shell/api_corrections.py). 실행: python -m unittest tests.test_shell_corrections

가상 도면 SNP-M-101의 실제 추출·그래프를 임시 작업 루트에 두고 실제 엔진(corrections·build_graph)을 부른다.
본다: 연산마다 저장 → 다시 읽기 → 되돌리기 → 다시 하기, 그래프에 바로 반영, 낡은 판 거절, 검토자 이름 없으면 거절, 지우기·태그 겹침은 확인,
AI 수락과 사람 수정이 한 기록에 함께 있을 때, 그래프 다시 만들기 실패('저장됨, 그래프 갱신 실패'), 쪽 확정이 풀림, 다시 추출 뒤 다시 얹기.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from hazop.extract import corrections  # noqa: E402
from hazop.shell import api, sheet_refresh  # noqa: E402
from hazop.shell import api_corrections as AC  # noqa: E402
from tests.test_shell_drawings import Events, template  # noqa: E402
from tests import test_shell_drawings as _tsd  # noqa: E402


def tearDownModule():
    _tsd.tearDownModule()
    _tsd._TPL.clear()


class Base(unittest.TestCase):
    def setUp(self):
        tpl = template()
        self.tmp = tempfile.mkdtemp(prefix="hazop-shelledit-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(os.path.join(tpl["root"], "work"), os.path.join(self.tmp, "work"))
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"),
                                               "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")}),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        if "edit.apply" not in api.COMMANDS:          # 등록 줄(api.MODULES)은 s-frame이 넣는다. 그 전에는 시험이 직접 올리고 프로젝트에 묶는다
            AC.register(api.COMMANDS)
        if "edit." not in api.PROJECT_BOUND:
            p = mock.patch.object(api, "PROJECT_BOUND", api.PROJECT_BOUND + ("edit.",))
            p.start()
            self.addCleanup(p.stop)
        self.name = tpl["name"]
        self.events = Events()
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events)
        self.engine.settings["reviewer_name"] = "검토자A"
        self.gid = {v: k for k, v in self.engine.graph_names().items()}[self.name]
        from hazop.app import data
        self.ex = data.read_json(data.extraction_path(self.name))
        self.nodes = {n["local_id"]: n for n in self.ex["nodes"]}
        self.rels = {r["local_id"]: r for r in self.ex["relations"]}

    # -------------------------------------------------------- 도우미
    def ver(self):
        return AC.view(self.engine, self.gid)["ver"]

    def edit(self, op, local_id=None, value=None, confirm=False, ver=None):
        return self.engine.dispatch("edit.apply", {"graph_id": self.gid, "op": op, "local_id": local_id, "value": value or {},
                                                   "ver": ver or self.ver(), "confirm": confirm}, project=self.engine.project_id(), via_web=True)

    def undo(self, op_id):
        return self.engine.dispatch("edit.undo", {"graph_id": self.gid, "op_id": op_id, "ver": self.ver()}, project=self.engine.project_id(), via_web=True)

    def redo(self):
        return self.engine.dispatch("edit.redo", {"graph_id": self.gid, "ver": self.ver()}, project=self.engine.project_id(), via_web=True)

    def graph(self):
        from hazop.app import data
        from hazop import paths
        return data.read_json(os.path.join(paths.output_root("graph"), self.name, "graph.json"))

    def graph_node(self, local_id):
        return next(n for n in self.graph()["nodes"] if n.get("local_id") == local_id)

    def corrected(self):
        from hazop.app import data
        return corrections.apply_saved(data.read_json(data.extraction_path(self.name)), self.name)

    def tagged(self):
        return next(n for n in self.ex["nodes"] if n.get("tag") and n.get("kind") not in (None, "tee", "continuation"))

    def flow_rel(self):
        return next(r for r in self.ex["relations"] if r.get("flow_direction") and r["kind"] == "physical_connection"
                    and all(ep.get("node_local_id") for ep in r["endpoints"]))


class TagKindFlowTest(Base):
    def test_tag_is_saved_reread_shown_in_the_graph_and_undone_and_redone(self):
        n = self.tagged()
        r = self.edit("set_tag", n["local_id"], {"tag": "RC-NEW-01"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.graph_node(n["local_id"])["tag"], "RC-NEW-01")           # 그래프에 바로
        v = AC.view(self.engine, self.gid)
        self.assertEqual([(o["op"], o["local_id"], o["status"], o["by"]) for o in v["ops"]], [("set_tag", n["local_id"], "applied", "검토자A")])
        self.assertTrue(v["ops"][0]["at"])
        self.assertTrue(self.events.changes("sheet") and self.events.changes("edit"))
        u = self.undo(r["data"]["op_id"])
        self.assertTrue(u["ok"], u)
        self.assertEqual(self.graph_node(n["local_id"])["tag"], n["tag"])
        self.assertEqual(AC.view(self.engine, self.gid)["redo"]["op_id"], r["data"]["op_id"])
        d = self.redo()
        self.assertTrue(d["ok"], d)
        self.assertEqual(self.graph_node(n["local_id"])["tag"], "RC-NEW-01")
        self.assertIsNone(AC.view(self.engine, self.gid)["redo"])
        log = corrections.load(self.name)["log"]
        self.assertEqual([e["action"] for e in log], ["edit", "undo", "redo"])

    def test_kind_is_chosen_from_the_dictionary_and_category_comes_from_it(self):
        n = self.tagged()
        self.assertFalse(self.edit("set_kind", n["local_id"], {"kind": "no_such_kind"})["ok"])
        r = self.edit("set_kind", n["local_id"], {"kind": "check_valve"})
        self.assertTrue(r["ok"], r)
        g = self.graph_node(n["local_id"])
        self.assertEqual((g["kind"], g["category"]), ("check_valve", "valve"))
        self.assertIn({"kind": "check_valve", "label": "체크 밸브", "category": "valve"}, AC.view(self.engine, self.gid)["kinds"])

    def test_flow_flip_reverses_and_undo_restores(self):
        rel = self.flow_rel()
        before = rel["flow_direction"]
        r = self.edit("set_flow", rel["local_id"], {"flip": True})
        self.assertTrue(r["ok"], r)
        fd = next(x for x in self.corrected()["relations"] if x["local_id"] == rel["local_id"])["flow_direction"]
        self.assertEqual((fd["from"], fd["to"], fd["basis"]), (before["to"], before["from"], "human"))
        self.assertTrue(self.undo(r["data"]["op_id"])["ok"])
        fd = next(x for x in self.corrected()["relations"] if x["local_id"] == rel["local_id"])["flow_direction"]
        self.assertEqual((fd["from"], fd["to"]), (before["from"], before["to"]))

    def test_stale_version_reviewer_and_wrong_project_write_nothing(self):
        n = self.tagged()
        r = self.edit("set_tag", n["local_id"], {"tag": "X-1"}, ver="0" * 16)
        self.assertEqual(r["error"]["code"], "stale")
        self.engine.settings["reviewer_name"] = ""
        self.assertEqual(self.edit("set_tag", n["local_id"], {"tag": "X-1"})["error"]["code"], "bad_args")
        self.engine.settings["reviewer_name"] = "검토자A"
        r = self.engine.dispatch("edit.apply", {"graph_id": self.gid, "op": "set_tag", "local_id": n["local_id"], "value": {"tag": "X-1"}, "ver": self.ver()},
                                 project="other-project", via_web=True)
        self.assertEqual(r["error"]["code"], "wrong_project")
        self.assertIsNone(corrections.load(self.name))

    def test_a_change_by_someone_else_after_reading_makes_the_old_screen_stale(self):
        n = self.tagged()
        seen = self.ver()
        self.assertTrue(self.edit("set_tag", n["local_id"], {"tag": "A-1"})["ok"])       # 다른 창에서 먼저 고침
        r = self.edit("set_tag", n["local_id"], {"tag": "B-1"}, ver=seen)
        self.assertEqual(r["error"]["code"], "stale")
        self.assertEqual(self.graph_node(n["local_id"])["tag"], "A-1")

    def test_duplicate_tag_needs_confirmation(self):
        a, b = [n for n in self.ex["nodes"] if n.get("tag") and n.get("kind") not in (None, "tee", "continuation")][:2]
        r = self.edit("set_tag", a["local_id"], {"tag": b["tag"]})
        self.assertEqual(r["error"]["code"], "needs_confirm")
        self.assertIn(b["tag"], r["error"]["message"])
        self.assertIsNone(corrections.load(self.name))
        self.assertTrue(self.edit("set_tag", a["local_id"], {"tag": b["tag"]}, confirm=True)["ok"])

    def test_graph_rebuild_failure_keeps_the_save_and_reports_it_then_recovers(self):
        n = self.tagged()
        with mock.patch.object(sheet_refresh, "rebuild", side_effect=RuntimeError("빌드 실패")):
            r = self.edit("set_tag", n["local_id"], {"tag": "KEEP-1"})
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["data"]["graph_stale"])
        self.assertTrue(any("다시 만들지 못했습니다" in t for t in r["data"]["notes"]))
        self.assertEqual(len(corrections.load(self.name)["ops"]), 1)                      # 저장은 남음
        self.assertTrue(AC.view(self.engine, self.gid)["graph_stale"])
        r = self.edit("set_tag", n["local_id"], {"tag": "KEEP-2"})                        # 다음 동작이 다시 만든다
        self.assertFalse(r["data"]["graph_stale"])
        self.assertEqual(self.graph_node(n["local_id"])["tag"], "KEEP-2")

    def test_ai_accepted_op_and_human_edit_live_in_one_record(self):
        n = self.tagged()
        from hazop.app import data
        ai_op = corrections.make_op(self.ex, "set_kind", n["source_object_id"], {"kind": "check_valve", "category": "valve"}, "AI 수락: 검토자A",
                                    name=self.name)
        corrections.save_fp(self.name, [ai_op], "AI 수락: 검토자A", expect=None)
        r = self.edit("set_tag", n["local_id"], {"tag": "MIX-1"})
        self.assertTrue(r["ok"], r)
        ops = corrections.load(self.name)["ops"]
        self.assertEqual([o["op"] for o in ops], ["set_kind", "set_tag"])
        g = self.graph_node(n["local_id"])
        self.assertEqual((g["kind"], g["tag"]), ("check_valve", "MIX-1"))
        self.assertTrue(self.undo(r["data"]["op_id"])["ok"])
        self.assertEqual([o["op"] for o in corrections.load(self.name)["ops"]], ["set_kind"])   # 사람 고침만 빠지고 AI 수락은 남음
        self.assertEqual(data.read_json(data.extraction_path(self.name)), self.ex)          # 원본 추출은 그대로


class AddDeleteConnectPathTest(Base):
    def test_add_node_connect_and_undo_in_order(self):
        r = self.edit("add_node", None, {"kind": "manual_valve", "tag": "RC-V900", "at": [50, 50]})
        self.assertTrue(r["ok"], r)
        made = r["data"]["created"]
        self.assertTrue(made.startswith("manual-"))
        g = self.graph_node(made)
        self.assertEqual((g["kind"], g["tag"]), ("manual_valve", "RC-V900"))
        other = self.tagged()["local_id"]
        c = self.edit("add_relation", None, {"kind": "physical_connection", "from": made, "to": other})
        self.assertTrue(c["ok"], c)
        u = self.undo(r["data"]["op_id"])                                                 # 기기를 쓰는 연결이 뒤에 있으면 먼저 못 뺀다
        self.assertEqual(u["error"]["code"], "bad_args")
        self.assertTrue(self.undo(c["data"]["op_id"])["ok"])
        self.assertTrue(self.undo(r["data"]["op_id"])["ok"])
        self.assertFalse(any(n.get("local_id") == made for n in self.graph()["nodes"]))

    def test_delete_needs_confirmation_and_shows_what_it_touches(self):
        n = self.tagged()
        r = self.edit("delete_node", n["local_id"])
        self.assertEqual(r["error"]["code"], "needs_confirm")
        self.assertIsNone(corrections.load(self.name))
        r = self.edit("delete_node", n["local_id"], confirm=True)
        self.assertTrue(r["ok"], r)
        self.assertFalse(any(x.get("local_id") == n["local_id"] for x in self.graph()["nodes"]))
        self.assertTrue(self.undo(r["data"]["op_id"])["ok"])
        self.assertTrue(any(x.get("local_id") == n["local_id"] for x in self.graph()["nodes"]))

    def test_disconnect_and_reconnect_an_end(self):
        rel = self.flow_rel()
        tgt = next(ep for ep in rel["endpoints"] if ep["end"] == "target")["node_local_id"]
        r = self.edit("clear_endpoint", rel["local_id"], {"end": "target"})
        self.assertTrue(r["ok"], r)
        cur = next(x for x in self.corrected()["unresolved_connectors"] if x["local_id"] == rel["local_id"])
        self.assertEqual(next(ep for ep in cur["endpoints"] if ep["end"] == "target")["status"], "unconnected")
        self.assertIsNone(cur["flow_direction"])
        r = self.edit("set_endpoint", rel["local_id"], {"end": "target", "node": tgt})
        self.assertTrue(r["ok"], r)
        cur = next(x for x in self.corrected()["relations"] if x["local_id"] == rel["local_id"])
        self.assertEqual(next(ep for ep in cur["endpoints"] if ep["end"] == "target")["node_local_id"], tgt)

    def test_path_is_redrawn_in_screen_coordinates_and_undone(self):
        rel = self.flow_rel()
        from hazop.shell import sheet_items
        ox, oy = sheet_items._offset(self.ex)
        pts = [[100, 100], [100, 200], [300, 200]]
        r = self.edit("set_path", rel["local_id"], {"points": pts})
        self.assertTrue(r["ok"], r)
        items = {i["id"]: i for i in sheet_items.build_items(self.corrected())["items"]}
        self.assertEqual(items[rel["local_id"]]["polyline"], [[float(x), float(y)] for x, y in pts])
        self.assertTrue(self.undo(r["data"]["op_id"])["ok"])
        items = {i["id"]: i for i in sheet_items.build_items(self.corrected())["items"]}
        self.assertNotEqual(items[rel["local_id"]]["polyline"], pts)
        self.assertEqual((ox, oy), sheet_items._offset(self.ex))


class ReachTest(Base):
    def test_item_card_has_current_values_and_what_the_edit_touches(self):
        rel = self.flow_rel()
        it = AC.item(self.engine, self.gid, rel["local_id"])
        self.assertTrue(it["ok"], it)
        self.assertEqual(it["type"], "relation")
        self.assertEqual(it["flow"]["from"], rel["flow_direction"]["from"])
        self.assertTrue(it["flow_allowed"])
        self.assertIn("sheet", it["impact"])
        n = self.tagged()
        it = AC.item(self.engine, self.gid, n["local_id"])
        self.assertEqual((it["type"], it["tag"]), ("node", n["tag"]))
        self.assertEqual(AC.item(self.engine, self.gid, "no-such")["code"], "not_found")

    def test_reextraction_reapplies_human_edits_and_lists_what_could_not_be_reapplied(self):
        n = self.tagged()
        self.assertTrue(self.edit("set_tag", n["local_id"], {"tag": "RE-1"})["ok"])
        gone = next(x for x in self.ex["nodes"] if x["local_id"] != n["local_id"] and x.get("kind") not in (None, "tee"))
        self.assertTrue(self.edit("set_kind", gone["local_id"], {"kind": "check_valve"})["ok"])
        # 다시 추출: 같은 결과를 새로 쓰되, 한 기기는 원본에서 사라졌다고 본다
        from hazop.app import data
        fresh = json.loads(json.dumps(self.ex))
        fresh["nodes"] = [x for x in fresh["nodes"] if x["local_id"] != gone["local_id"]]
        with open(data.extraction_path(self.name), "w", encoding="utf-8") as fh:
            json.dump(fresh, fh, ensure_ascii=False)
        out = corrections.apply_saved(fresh, self.name)["corrections"]
        self.assertEqual(len(out["applied"]), 1)
        self.assertEqual([x["reason"] for x in out["not_applicable"]], ["대상 없음"])
        v = AC.view(self.engine, self.gid)
        self.assertEqual([o["status"] for o in v["ops"]], ["applied", "not_applicable"])
        self.assertEqual(v["ops"][1]["reason"], "대상 없음")
        self.assertEqual(next(x for x in corrections.apply_saved(fresh, self.name)["nodes"] if x["local_id"] == n["local_id"])["tag"], "RE-1")

    def test_a_confirmed_sheet_is_reported_as_released_by_an_edit(self):
        from hazop.extract import confirmation
        seq = iter([{"status": "confirmed"}, {"status": "released"}])
        with mock.patch.object(confirmation, "sheet_confirmation", lambda name: next(seq)):
            r = self.edit("set_tag", self.tagged()["local_id"], {"tag": "REL-1"})
        self.assertTrue(r["data"]["released"])
        self.assertTrue(any("확정이 풀렸습니다" in t for t in r["data"]["notes"]))

    def test_project_node_set_made_before_the_edit_asks_for_recheck(self):
        from hazop.study import nodes as study_nodes
        stale = {"schema_version": study_nodes.SCHEMA_VERSION, "graph_version": "old", "project_id": self.engine.project_id(), "graph_id": "pg", "nodes": [{"node_id": "S1", "members": [], "confirmed": {"by": "a"}}]}
        with mock.patch.object(study_nodes, "read_as_is", lambda pg: stale):
            notes = sheet_refresh.project_recheck(self.engine.project_id())
        self.assertTrue(notes and notes[0].startswith("④ 검토구간이 고치기 전 도면 기준입니다"), notes)

    def test_web_never_sends_or_receives_paths(self):
        n = self.tagged()
        r = self.edit("set_tag", n["local_id"], {"tag": "P-1"})
        text = json.dumps([r, AC.view(self.engine, self.gid), AC.item(self.engine, self.gid, n["local_id"])], ensure_ascii=False)
        self.assertNotIn(self.tmp.replace("\\", "/"), text.replace("\\\\", "/").replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
