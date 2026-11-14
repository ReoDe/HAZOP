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
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events, run_jobs=lambda job_id, fn: fn())
        self.engine.settings["reviewer_name"] = "검토자A"
        self.gid = {v: k for k, v in self.engine.graph_names().items()}[self.name]
        from hazop.app import data
        self.ex = data.read_json(data.extraction_path(self.name))
        self.nodes = {n["local_id"]: n for n in self.ex["nodes"]}
        self.rels = {r["local_id"]: r for r in self.ex["relations"]}

    # -------------------------------------------------------- 도우미
    def pid(self):
        """등록한 도면처럼 추출에 project_id를 넣고 그래프를 다시 만든다(지식그래프 다시 만들기·재확인이 도는 길)."""
        from hazop.app import data
        from hazop import paths
        ex = data.read_json(data.extraction_path(self.name))
        ex["project_id"] = self.engine.project_id()
        with open(data.extraction_path(self.name), "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)
        data.script_module("build_graph").build_one(data.extraction_path(self.name), paths.output_root("graph"))
        self.ex = ex

    def ver(self):
        return AC.view(self.engine, self.gid)["ver"]

    def edit(self, op, local_id=None, value=None, confirm=None, ver=None, base=None):
        """confirm=True면 사람이 확인 상자를 보고 누른 것처럼: 먼저 엔진이 묻는 확인 글을 받아 그 글을 그대로 보낸다."""
        if confirm is True:
            first = self.edit(op, local_id, value, ver=ver, base=base)
            if first["ok"] or first["error"]["code"] != "needs_confirm":
                return first
            confirm = first["error"]["message"]
        args = {"graph_id": self.gid, "op": op, "local_id": local_id, "value": value or {}, "ver": ver or self.ver()}
        if confirm:
            args["confirm"] = confirm
        if base:
            args["base"] = base
        return self.engine.dispatch("edit.apply", args, project=self.engine.project_id(), via_web=True)

    def undo(self, op_id, confirm=None):
        args = {"graph_id": self.gid, "op_id": op_id, "ver": self.ver()}
        if confirm:
            args["confirm"] = confirm
        return self.engine.dispatch("edit.undo", args, project=self.engine.project_id(), via_web=True)

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

    def test_the_web_command_answers_before_the_graph_is_rebuilt_and_the_job_finishes_it(self):
        n = self.tagged()
        started = []
        real = self.engine.start_job
        self.engine.start_job = lambda label, fn, kind="register": started.append((label, kind)) or "j-held"      # 작업이 아직 안 끝난 때
        r = self.edit("set_tag", n["local_id"], {"tag": "FAST-1"})
        self.assertTrue(r["ok"] and r["data"]["refreshing"] and r["data"]["graph_stale"], r)
        self.assertEqual(started, [("그래프 다시 만들기", "graph_refresh")])
        self.assertTrue(sheet_refresh.graph_stale(self.name))                              # 표시가 서 있다: 읽는 쪽이 낡은 그래프임을 안다
        self.assertEqual(len(corrections.load(self.name)["ops"]), 1)
        self.engine.start_job = real
        self.assertTrue(self.edit("set_tag", n["local_id"], {"tag": "FAST-2"})["ok"])       # 다음 동작이 먼저 다시 만든다
        self.assertFalse(sheet_refresh.graph_stale(self.name))
        self.assertEqual(self.graph_node(n["local_id"])["tag"], "FAST-2")

    def test_graph_rebuild_failure_keeps_the_save_and_reports_it_then_recovers(self):
        n = self.tagged()
        with mock.patch.object(sheet_refresh, "rebuild", side_effect=RuntimeError("빌드 실패")):
            r = self.edit("set_tag", n["local_id"], {"tag": "KEEP-1"})            # 웹 명령: 다시 만들기는 작업으로 넘어간다(여기서는 같은 스레드에서 돌고 실패)
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["data"]["graph_stale"] and r["data"]["refreshing"])
        self.assertTrue(sheet_refresh.graph_stale(self.name))
        self.assertEqual(len(corrections.load(self.name)["ops"]), 1)                      # 저장은 남음
        self.assertTrue(AC.view(self.engine, self.gid)["graph_stale"])
        r = self.edit("set_tag", n["local_id"], {"tag": "KEEP-2"})                        # 다음 동작이 다시 만든다
        self.assertFalse(sheet_refresh.graph_stale(self.name))
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


class ReviewReproTest(Base):
    """2026-11-14 검토 재현(R1~R9)을 시험으로 옮긴 것. 고치기 전에는 실패한다."""

    def tags(self):
        return [n for n in self.ex["nodes"] if n.get("tag") and n.get("kind") not in (None, "tee", "continuation")]

    def cur_tag(self, lid):
        return next(n for n in self.corrected()["nodes"] if n["local_id"] == lid)["tag"]

    def test_r1_redo_puts_the_op_back_where_it_was_and_a_new_edit_clears_redo(self):
        n = self.tagged()
        a = self.edit("set_tag", n["local_id"], {"tag": "FIRST"})
        self.edit("set_tag", n["local_id"], {"tag": "SECOND"})
        self.assertTrue(self.undo(a["data"]["op_id"])["ok"])
        self.assertEqual(self.cur_tag(n["local_id"]), "SECOND")
        self.assertTrue(self.redo()["ok"])
        self.assertEqual(self.cur_tag(n["local_id"]), "SECOND")                         # 되살린 FIRST가 뒤의 SECOND를 덮지 않는다
        self.assertEqual([o["value"]["tag"] for o in corrections.load(self.name)["ops"]], ["FIRST", "SECOND"])
        self.assertTrue(self.undo(a["data"]["op_id"])["ok"])
        self.edit("set_tag", n["local_id"], {"tag": "THIRD"})                           # 되돌린 뒤 새로 고치면 다시 하기는 없다
        self.assertIsNone(AC.view(self.engine, self.gid)["redo"])
        self.assertEqual(self.redo()["error"]["code"], "not_found")

    def test_r2_an_ai_accepted_op_is_undone_only_in_the_ai_review_panel(self):
        from hazop.extract import ai_review
        n = self.tagged()
        doc = ai_review.new_doc(self.name, self.ex)
        doc["candidates"].append({"cand_id": "k1", "status": "proposed", "target": n["source_object_id"], "local_id": n["local_id"], "field": "tag",
                                  "values": ["AI-TAG"], "confidence": 0.9, "task": "fill", "op_id": None})
        ai_review.save_doc(doc)
        self.assertEqual(ai_review.accept(ai_review.load_doc(self.name), ["k1"], self.ex, self.name, "검토자A"), [])
        v = AC.view(self.engine, self.gid)
        ai_op = corrections.load(self.name)["ops"][-1]["op_id"]
        self.assertNotIn(ai_op, v["undoable"])
        self.assertTrue(next(o for o in v["ops"] if o["op_id"] == ai_op)["ai"])
        u = self.undo(ai_op)
        self.assertEqual(u["error"]["code"], "bad_args")
        self.assertIn("AI 검토 패널", u["error"]["message"])
        self.assertEqual(ai_review.load_doc(self.name)["candidates"][0]["status"], "accepted")
        self.assertEqual(self.cur_tag(n["local_id"]), "AI-TAG")

    def test_a_human_delete_of_an_ai_accepted_target_returns_the_candidate_to_proposed(self):
        from hazop.extract import ai_review
        n = self.tagged()
        doc = ai_review.new_doc(self.name, self.ex)
        doc["candidates"].append({"cand_id": "k1", "status": "proposed", "target": n["source_object_id"], "local_id": n["local_id"], "field": "tag",
                                  "values": ["AI-TAG"], "confidence": 0.9, "task": "fill", "op_id": None})
        ai_review.save_doc(doc)
        ai_review.accept(ai_review.load_doc(self.name), ["k1"], self.ex, self.name, "검토자A")
        self.assertEqual(ai_review.load_doc(self.name)["candidates"][0]["status"], "accepted")
        r = self.edit("delete_node", n["local_id"], confirm=True)                       # 기기를 지우면 대상 없는 AI 연산도 기록에서 정리된다
        self.assertTrue(r["ok"], r)
        c = ai_review.load_doc(self.name)["candidates"][0]
        self.assertEqual(c["status"] == "accepted", bool(c.get("op_id")), c)            # 후보 상태와 기록이 어긋나지 않는다
        self.assertTrue(self.undo(r["data"]["op_id"])["ok"])

    def test_r3_the_version_is_checked_against_the_bytes_that_are_edited(self):
        from hazop.app import data
        a, b = self.tags()[:2]
        seen = self.ver()

        def swap(name):                     # 판을 대조한 뒤·파일을 읽기 전에 다시 추출이 끼어 두 기기가 자리를 바꿈
            ex = json.loads(json.dumps(self.ex))
            na = next(x for x in ex["nodes"] if x["local_id"] == a["local_id"])
            nb = next(x for x in ex["nodes"] if x["local_id"] == b["local_id"])
            for k in ("tag", "kind", "category", "attributes"):
                na[k], nb[k] = nb.get(k), na.get(k)
            with open(data.extraction_path(self.name), "w", encoding="utf-8") as fh:
                json.dump(ex, fh, ensure_ascii=False)
            return False, [], []
        with mock.patch.object(sheet_refresh, "ensure_graph", swap):
            r = self.edit("set_tag", a["local_id"], {"tag": "MEANT-" + str(a["tag"])}, ver=seen)
        self.assertEqual(r["error"]["code"], "stale")
        self.assertIsNone(corrections.load(self.name))

    def test_r3b_a_target_that_changed_under_the_same_id_is_refused(self):
        a = self.tagged()
        base = AC.item(self.engine, self.gid, a["local_id"])["base"]
        self.assertTrue(self.edit("set_kind", a["local_id"], {"kind": "check_valve"})["ok"])     # 다른 창에서 종류가 바뀜
        r = self.edit("set_tag", a["local_id"], {"tag": "X-9"}, base=base)
        self.assertEqual(r["error"]["code"], "stale")
        self.assertIn("화면에서 본 항목", r["error"]["message"])

    def test_r5_a_knowledge_graph_failure_keeps_the_stale_mark_and_is_retried(self):
        from hazop.app import data
        self.pid()
        with mock.patch.object(data, "build_project_kg", side_effect=OSError("kg disk")):
            r = self.edit("set_tag", self.tagged()["local_id"], {"tag": "KG-1"})
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["data"]["graph_stale"])
        self.assertTrue(sheet_refresh.graph_stale(self.name))
        from hazop.app import project_ctx
        project_ctx.project_graph(self.engine.project_id())                         # 프로젝트 그래프를 짓는 곳이 먼저 다시 만든다
        self.assertFalse(sheet_refresh.graph_stale(self.name))

    def test_r6_two_threads_with_the_same_version_do_not_lose_an_edit(self):
        import threading
        a, b = self.tags()[:2]
        seen = self.ver()
        out = []

        def go(n, t):
            out.append(self.edit("set_tag", n["local_id"], {"tag": t}, ver=seen))
        ts = [threading.Thread(target=go, args=(a, "T-A")), threading.Thread(target=go, args=(b, "T-B"))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        oks = [x for x in out if x.get("ok")]
        stale = [x for x in out if not x.get("ok") and x["error"]["code"] == "stale"]
        self.assertEqual((len(oks), len(stale)), (1, 1), out)
        self.assertEqual(len(corrections.load(self.name)["ops"]), 1)

    def test_r8_path_points_are_validated(self):
        rel = self.flow_rel()
        for pts in ([["a", "b"], [1, 2]], [[1, 2], "x"], [[1, 2]], "xy"):
            r = self.edit("set_path", rel["local_id"], {"points": pts})
            self.assertEqual(r["error"]["code"], "bad_args", pts)
            self.assertIn("경로 점", r["error"]["message"])

    def test_r9_deleting_a_node_names_the_pipes_that_go_with_it_and_a_changed_impact_asks_again(self):
        rel = self.flow_rel()
        node_lid = next(ep for ep in rel["endpoints"] if ep["end"] == "source")["node_local_id"]
        r = self.edit("delete_node", node_lid)
        self.assertEqual(r["error"]["code"], "needs_confirm")
        self.assertIn(rel["local_id"], r["error"]["message"])                         # 함께 지워지는 배관
        stale_text = r["error"]["message"].replace("지웁니다", "지웁니다(옛 확인)")
        self.assertEqual(self.edit("delete_node", node_lid, confirm=stale_text)["error"]["code"], "needs_confirm")
        self.assertTrue(self.edit("delete_node", node_lid, confirm=r["error"]["message"])["ok"])


class RegisteredPathTest(unittest.TestCase):
    """실제 길: 등록 → 추출 → 구간 만들기(api_nodes, 잠금) → 고치기. 시험 자료에 project_id를 넣지 않고 등록이 넣게 둔다(검토 12)."""

    def setUp(self):
        import glob
        from hazop import paths
        self.tmp = tempfile.mkdtemp(prefix="hazop-shelledit-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")}),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        if "edit.apply" not in api.COMMANDS:
            AC.register(api.COMMANDS)
        if "edit." not in api.PROJECT_BOUND:
            p = mock.patch.object(api, "PROJECT_BOUND", api.PROJECT_BOUND + ("edit.",))
            p.start()
            self.addCleanup(p.stop)
        self.events = Events()
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events, run_jobs=lambda job_id, fn: fn())
        self.engine.settings.update(reviewer_name="검토자A", project_id="REG-P")
        from hazop.shell import register_flow
        folder = [p for p in glob.glob(paths.folder("references", "pid-samples", "*")) if "SNP-M-101" in p][0]
        src = shutil.copy(glob.glob(os.path.join(folder, "*.drawio"))[0], self.tmp)        # 등록은 원본을 저장소에 복사한다(원본 폴더는 건드리지 않음)
        register_flow.register_and_extract(self.engine, src, lambda *a, **k: None)
        self.gid = next(g for g in self.engine.graph_names() if "101" in g)
        self.name = self.engine.graph_names()[self.gid]

    def call_nodes(self, name, args):
        from hazop.shell import api_nodes
        s = api_nodes.summary(self.engine)
        args = dict(args, set_rev=s["set_rev"], project_id=self.engine.project_id())
        if args.get("node_id"):
            row = next(n for n in s["nodes"] if n["node_id"] == args["node_id"])
            args["targets"] = [{"node_id": row["node_id"], "rev": row["rev"], "state": row["state"]}]
        if args.get("node_ids"):
            rows = {n["node_id"]: n for n in s["nodes"]}
            args["targets"] = [{"node_id": i, "rev": rows[i]["rev"], "state": rows[i]["state"]} for i in args["node_ids"]]
        r = self.engine.dispatch("nodes." + name, args, project=self.engine.project_id(), via_web=True)
        self.assertTrue(r["ok"], r)
        return r

    def edit(self, op, local_id=None, value=None, confirm=None):
        v = AC.view(self.engine, self.gid)["ver"]
        args = {"graph_id": self.gid, "op": op, "local_id": local_id, "value": value or {}, "ver": v}
        if confirm:
            args["confirm"] = confirm
        return self.engine.dispatch("edit.apply", args, project=self.engine.project_id(), via_web=True)

    def test_a_web_edit_rebuilds_the_sheet_once(self):
        """웹 고치기는 낡은 표시를 세우고 작업에서 다시 만든다. 다시 만들기 안에서 짓는 프로젝트 그래프가 그 표시를 보고
        같은 쪽을 또 다시 만들면 안 된다(APR1400에서 저장 뒤 다시 만들기가 두 번 돌아 8~10초 걸렸다)."""
        from hazop.app import data
        lid = next(n["local_id"] for n in data.read_json(data.extraction_path(self.name))["nodes"] if n.get("tag"))
        with mock.patch.object(sheet_refresh, "rebuild", wraps=sheet_refresh.rebuild) as rb:
            r = self.edit("set_tag", lid, {"tag": "ONCE-1"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(rb.call_count, 1)
        self.assertFalse(sheet_refresh.graph_stale(self.name))

    def test_registered_drawing_edit_rebuilds_the_knowledge_graph_and_names_the_confirmed_segment(self):
        from hazop.app import data
        ex = data.read_json(data.extraction_path(self.name))
        self.assertEqual(ex.get("project_id"), "REG-P")
        rel = next(r for r in ex["relations"] if r["kind"] == "physical_connection" and all(ep.get("node_local_id") for ep in r["endpoints"]))
        node_lid = next(ep for ep in rel["endpoints"] if ep["end"] == "source")["node_local_id"]
        self.call_nodes("create", {"sheet": self.gid, "ids": [rel["local_id"]], "name": "확정할 구간"})
        self.call_nodes("confirm", {"node_ids": ["S1"]})
        with mock.patch.object(data, "build_project_kg", wraps=data.build_project_kg) as kg:
            r = AC.apply_edit(self.engine, self.gid, "set_tag", node_lid, {"tag": "REG-TAG-1"}, AC.view(self.engine, self.gid)["ver"])      # 채팅 길: 같은 스레드에서 끝까지
        self.assertTrue(r["ok"], r)
        self.assertTrue(kg.called, "등록된 도면이면 지식그래프를 다시 만든다")
        self.assertTrue(any(t.startswith("④ 검토구간이 고치기 전 도면 기준입니다") and "S1" in t for t in r["recheck"]), r["recheck"])
        d = self.edit("delete_node", node_lid)                                            # 기기와 함께 지워지는 배관이 확정 구간 S1에 든다
        self.assertEqual(d["error"]["code"], "needs_confirm")
        self.assertIn("S1", d["error"]["message"])
        self.assertIn(rel["local_id"], d["error"]["message"])

    def test_undoing_an_added_node_that_a_confirmed_segment_holds_asks_first_and_the_list_shows_the_broken_member(self):
        r = self.edit("add_node", None, {"kind": "manual_valve", "tag": "RC-V901", "at": [60, 60]})
        self.assertTrue(r["ok"], r)
        made = r["data"]["created"]
        self.call_nodes("create", {"sheet": self.gid, "ids": [made], "name": "새 기기 구간"})
        self.call_nodes("confirm", {"node_ids": ["S1"]})
        u = self.engine.dispatch("edit.undo", {"graph_id": self.gid, "op_id": r["data"]["op_id"], "ver": AC.view(self.engine, self.gid)["ver"]},
                                 project=self.engine.project_id(), via_web=True)
        self.assertEqual(u["error"]["code"], "needs_confirm")
        self.assertIn("S1", u["error"]["message"])
        u = self.engine.dispatch("edit.undo", {"graph_id": self.gid, "op_id": r["data"]["op_id"], "ver": AC.view(self.engine, self.gid)["ver"],
                                               "confirm": u["error"]["message"]}, project=self.engine.project_id(), via_web=True)
        self.assertTrue(u["ok"], u)
        from hazop.shell import api_nodes
        row = api_nodes.summary(self.engine)["nodes"][0]
        self.assertEqual(row["broken"], 1)                                                # 구간 화면에 '끊긴 구성원'으로 보인다


if __name__ == "__main__":
    unittest.main()
