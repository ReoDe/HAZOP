"""새 웹 화면 2단계(구간)의 엔진 쪽: 명령 `nodes.*`와 읽기 `nodes`(hazop/shell/api_nodes.py, docs/design/app-shell-web.md §2.1·§5.3).
실행: python -m unittest tests.test_shell_nodes

저장은 임시 HAZOP_WORK_ROOT 아래에만 한다. 그래프는 SNP 표본 6장으로 만든 프로젝트 그래프이고, 화면 명령은 웹이 보내는 모양(도면 local_id)으로 부른다.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.shell import api, api_nodes  # noqa: E402
from hazop.study import node_commands, nodes  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_node_tools import DEVS, snp_graph  # noqa: E402

S101, S102 = "graph-SNP-M-101", "graph-SNP-M-102"


def _rb(path):
    with open(path, "rb") as fh:
        return fh.read()


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-shellnodes-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for patcher in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work")}),
                        mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                        mock.patch.dict(api.COMMANDS)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        self.pg = snp_graph()
        from hazop.app import project_ctx
        patcher = mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.events = []
        self.engine = self.new_engine()
        self.engine.settings["reviewer_name"] = "홍길동"
        self.engine.settings["project_id"] = "SNP"
        self.by_sheet = {}
        for n in self.pg["nodes"]:
            if n.get("sheet"):
                self.by_sheet.setdefault(n["sheet"], []).append(n)

    def new_engine(self):
        return api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events.append)

    def local(self, sheet, a, b):
        return [n["local_id"] for n in self.by_sheet[sheet][a:b]]

    def rev(self):
        return api_nodes.summary(self.engine)["set_rev"]

    def call(self, name, args=None, **kw):
        """웹이 하듯 화면이 본 판(set_rev, 건드리는 구간의 rev·state)을 함께 보낸다. 시험이 따로 정하면 그것을 쓴다."""
        args = dict(args or {})
        args.setdefault("set_rev", self.rev())
        args.setdefault("project_id", self.engine.project_id())
        wanted = ([args["node_id"]] if args.get("node_id") else []) + list(args.get("node_ids") or [])
        if "targets" not in args and wanted:
            rows = {n["node_id"]: n for n in api_nodes.summary(self.engine)["nodes"]}
            args["targets"] = [{"node_id": i, "rev": rows[i]["rev"], "state": rows[i]["state"]} for i in wanted if i in rows]
        return self.engine.dispatch("nodes." + name, dict(args, **kw))

    def create(self, name="구간 가", a=0, b=6, sheet=S101, **kw):
        return self.call("create", {"sheet": sheet, "ids": self.local(sheet, a, b), "name": name}, **kw)


class CommandTest(Env):
    def test_create_reads_back_with_members_by_sheet_and_batch(self):
        r = self.create(design_intent="냉각재를 보냄")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["node_ids"], ["S1"])
        self.assertTrue(r["data"]["batch_id"].startswith("B"))
        s = api_nodes.summary(self.engine)
        n = s["nodes"][0]
        self.assertEqual((n["node_id"], n["name"], n["state"], n["origin"], n["name_by"], n["count"]), ("S1", "구간 가", "applied", "user", "user", 6))
        self.assertEqual(n["sheets"], [{"graph_id": S101, "n": 6}])
        self.assertEqual(n["design_intent"], {"text": "냉각재를 보냄", "by": "user"})
        self.assertEqual(s["set_rev"], r["data"]["set_rev"])
        self.assertIn("nodes", [e.get("topic") for e in self.events])

    def test_web_cannot_write_who_or_when(self):
        for key in ("by", "at", "author", "origin", "confirmed_by", "request"):
            r = self.create(**{key: "누군가"})
            self.assertFalse(r["ok"], key)
            self.assertEqual(r["error"]["code"], "bad_args", key)
        self.assertEqual(api_nodes.summary(self.engine)["nodes"], [])

    def test_reviewer_name_is_required_and_written_by_engine(self):
        self.engine.settings["reviewer_name"] = ""
        r = self.create()
        self.assertEqual(r["error"]["code"], "bad_args")
        self.assertIn("검토자", r["error"]["message"])
        self.engine.settings["reviewer_name"] = "홍길동"
        self.create()
        self.assertTrue(self.call("confirm", {"node_ids": ["S1"]})["ok"])
        n = api_nodes.summary(self.engine)["nodes"][0]
        self.assertEqual(n["state"], "confirmed")
        self.assertEqual(n["confirmed"]["by"], "홍길동")
        self.assertTrue(n["confirmed"]["at"])

    def test_stale_set_rev_writes_nothing(self):
        self.create()
        before = api_nodes.summary(self.engine)
        r = self.call("rename", {"node_id": "S1", "name": "새 이름", "set_rev": before["set_rev"] - 1})
        self.assertEqual(r["error"]["code"], "stale")
        self.assertEqual(api_nodes.summary(self.engine)["nodes"][0]["name"], "구간 가")

    def test_stale_target_rev_and_state_write_nothing(self):
        self.create()
        n = api_nodes.summary(self.engine)["nodes"][0]
        r = self.call("rename", {"node_id": "S1", "name": "새 이름", "targets": [{"node_id": "S1", "rev": n["rev"] + 1, "state": "applied"}]})
        self.assertEqual(r["error"]["code"], "stale")
        r = self.call("rename", {"node_id": "S1", "name": "새 이름", "targets": [{"node_id": "S1", "rev": n["rev"], "state": "confirmed"}]})
        self.assertEqual(r["error"]["code"], "stale")
        r = self.call("rename", {"node_id": "S1", "name": "새 이름", "targets": [{"node_id": "S1", "rev": n["rev"], "state": "applied"}, {"node_id": "S9", "rev": 1, "state": "applied"}]})
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(api_nodes.summary(self.engine)["nodes"][0]["name"], "구간 가")

    def test_edit_members_name_and_intent_bump_rev_once_each(self):
        self.create(a=0, b=4)
        rev0 = api_nodes.summary(self.engine)["nodes"][0]["rev"]
        extra = self.local(S101, 4, 7)
        self.assertTrue(self.call("add_members", {"node_id": "S1", "sheet": S101, "ids": extra})["ok"])
        self.assertEqual(api_nodes.summary(self.engine)["nodes"][0]["count"], 7)
        self.assertTrue(self.call("remove_members", {"node_id": "S1", "sheet": S101, "ids": extra[:1]})["ok"])
        self.assertTrue(self.call("rename", {"node_id": "S1", "name": "고친 이름"})["ok"])
        self.assertTrue(self.call("set_intent", {"node_id": "S1", "text": "의도"})["ok"])
        n = api_nodes.summary(self.engine)["nodes"][0]
        self.assertEqual((n["count"], n["name"], n["design_intent"]["text"]), (6, "고친 이름", "의도"))
        self.assertEqual(n["rev"], rev0 + 4)

    def test_foreign_ids_and_empty_name_are_refused(self):
        r = self.call("create", {"sheet": S101, "ids": ["없는-id"], "name": "x"})
        self.assertEqual(r["error"]["code"], "bad_args")
        mixed = self.local(S101, 0, 3) + ["신호선-id"]        # 그래프 구성요소가 아닌 선은 빼고 나머지로 만든다
        r = self.call("create", {"sheet": S101, "ids": mixed, "name": "섞음"})
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["data"]["skipped"], "1개는" in r["data"]["skipped_text"]), (1, True))
        self.assertEqual(api_nodes.summary(self.engine)["nodes"][0]["count"], 3)
        self.assertTrue(self.call("remove", {"node_id": "S1"})["ok"])
        r = self.call("create", {"sheet": S101, "ids": self.local(S101, 0, 2), "name": ""})
        self.assertEqual(r["error"]["code"], "bad_args")
        self.assertEqual(api_nodes.summary(self.engine)["nodes"], [])

    def test_locked_and_confirmed_refusals_carry_engine_reason(self):
        self.create()
        self.call("confirm", {"node_ids": ["S1"]})
        r = self.call("rename", {"node_id": "S1", "name": "x"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "locked")
        self.assertIn("확정 구간", r["error"]["message"])
        r = self.call("unlock", {"node_ids": ["S1"], "reason": "x"})
        self.assertFalse(r["ok"])
        self.assertTrue(self.call("unconfirm", {"node_ids": ["S1"]})["ok"])
        self.assertEqual(api_nodes.summary(self.engine)["nodes"][0]["state"], "applied")

    def test_lock_needs_reason_to_unlock_and_engine_checks_cells(self):
        self.create()
        self.call("confirm", {"node_ids": ["S1"]})
        r = self.call("lock", {"node_ids": ["S1"]})
        self.assertFalse(r["ok"])          # 분석 안 한 칸이 있어 잠글 수 없음(엔진 규칙)
        self.assertTrue(r["error"]["message"])
        self.assertEqual(api_nodes.summary(self.engine)["nodes"][0]["state"], "confirmed")
        r = self.call("unlock", {"node_ids": ["S1"]})
        self.assertEqual(r["error"]["code"], "bad_args")   # reason 빠짐

    def test_merge_split_remove_and_undo(self):
        self.create("가", 0, 4)
        self.create("나", 4, 8)
        self.assertTrue(self.call("merge", {"node_ids": ["S1", "S2"]})["ok"])
        s = api_nodes.summary(self.engine)
        self.assertEqual([n["node_id"] for n in s["nodes"]], ["S1"])
        self.assertEqual(s["nodes"][0]["count"], 8)
        r = self.call("split", {"node_id": "S1", "sheet": S101, "ids": self.local(S101, 4, 8), "name": "뗀 것"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(api_nodes.summary(self.engine)["nodes"]), 2)
        self.assertTrue(self.call("remove", {"node_id": r["data"]["node_ids"][0]})["ok"])
        s = api_nodes.summary(self.engine)
        self.assertEqual(len(s["nodes"]), 1)
        batch = s["batches"][0]
        self.assertEqual(batch["ops"], ["remove"])
        u = self.call("undo", {"batch_id": batch["batch_id"]})
        self.assertTrue(u["ok"], u)
        self.assertEqual(len(api_nodes.summary(self.engine)["nodes"]), 2)
        again = self.call("undo", {"batch_id": batch["batch_id"]})
        self.assertFalse(again["ok"])            # 이미 되돌린 묶음

    def test_overlap_is_reported_both_ways(self):
        self.create("가", 0, 5)
        self.create("나", 3, 8)
        s = api_nodes.summary(self.engine)
        self.assertEqual(s["nodes"][0]["overlaps"], [{"node_id": "S2", "shared": 2}])
        self.assertEqual(s["nodes"][1]["overlaps"], [{"node_id": "S1", "shared": 2}])
        d = api_nodes.detail(self.engine, "S1")
        self.assertEqual(sum(1 for m in d["members"] if m["shared"] == ["S2"]), 2)

    def test_chat_made_nodes_show_with_origin_batch_and_user_can_undo(self):
        pg = self.pg
        ids = [n["entity_id"] for n in self.by_sheet[S101][:5]]
        out = node_commands.execute(pg, "create", {"items": [{"members": ids, "name": "AI 구간", "design_intent": "초안"}]}, author="ai",
                                    confirmed_by=None, set_rev=0, request={"request_id": "q-1", "request_text": "구간 나눠 줘", "user_turn": "u-1"})
        self.assertTrue(out["ok"], out)
        s = api_nodes.summary(self.engine)
        n = s["nodes"][0]
        self.assertEqual((n["origin"], n["name_by"], n["design_intent"]["by"]), ("ai", "ai", "ai"))
        self.assertEqual(s["pending_ai"], 1)
        self.assertEqual(s["batches"][0]["origin"], "ai")
        self.assertEqual(s["batches"][0]["request_text"], "구간 나눠 줘")
        self.assertTrue(self.call("undo", {"batch_id": out["batch_id"]})["ok"])
        self.assertEqual(api_nodes.summary(self.engine)["nodes"], [])

    def test_suggest_gives_name_boundary_and_overlap_without_saving(self):
        self.create("가", 0, 5)
        eq = [n for n in self.by_sheet[S101] if n.get("category") == "equipment" and n.get("tag")]
        ids = [eq[0]["local_id"], eq[-1]["local_id"], self.by_sheet[S101][0]["local_id"]]
        r = self.engine.dispatch("nodes.suggest", {"project_id": "SNP", "sheet": S101, "ids": ids})
        self.assertTrue(r["ok"], r)
        d = r["data"]
        self.assertEqual(d["count"], len(set(ids)))
        self.assertTrue(d["name"])
        self.assertEqual(len(api_nodes.summary(self.engine)["nodes"]), 1)
        self.assertEqual(d["set_rev"], self.rev())


class ReadTest(Env):
    def test_sheet_view_lists_local_ids_per_node_and_outside(self):
        self.create("가", 0, 5)
        self.create("나", 3, 8, sheet=S101)
        v = api_nodes.sheet_view(self.engine, S101)
        self.assertEqual([s["node_id"] for s in v["segments"]], ["S1", "S2"])
        self.assertEqual(v["segments"][0]["ids"], self.local(S101, 0, 5))
        covered = set(self.local(S101, 0, 8))
        self.assertEqual(set(v["outside_ids"]), {n["local_id"] for n in self.by_sheet[S101]} - covered)
        other = api_nodes.sheet_view(self.engine, S102)
        self.assertEqual(other["segments"], [])
        self.assertEqual(len(other["outside_ids"]), len(self.by_sheet[S102]))

    def test_summary_outside_count_and_empty_state(self):
        s = api_nodes.summary(self.engine)
        self.assertEqual((s["set_rev"], s["nodes"], s["batches"], s["stale"]), (0, [], [], False))
        total = sum(len(v) for v in self.by_sheet.values())
        self.assertEqual(s["outside"], {"count": total, "total": total})
        self.create("가", 0, 5)
        self.assertEqual(api_nodes.summary(self.engine)["outside"]["count"], total - 5)

    def test_detail_caps_members_and_gives_majors(self):
        eq = [n for n in self.by_sheet[S101] if n.get("category") == "equipment" and n.get("tag")]
        ids = [n["local_id"] for n in self.by_sheet[S101]]
        self.assertTrue(self.call("create", {"sheet": S101, "ids": ids, "name": "전체"})["ok"])
        d = api_nodes.detail(self.engine, "S1")
        self.assertEqual(d["members_total"], len(ids))
        self.assertLessEqual(len(d["members"]), api_nodes.MEMBERS_SHOWN)
        self.assertEqual(d["majors"][0], eq[0]["tag"])
        self.assertEqual(len(d["boundary"]), 2)
        self.assertEqual(d["history"][0]["ops"], ["add"])
        self.assertIsNone(api_nodes.detail(self.engine, "S99"))

    def test_read_routes_through_json(self):
        self.create()
        body = json.loads(api_nodes.read(self.engine, ["nodes"], {}).body.decode("utf-8"))
        self.assertEqual(body["nodes"][0]["node_id"], "S1")
        body = json.loads(api_nodes.read(self.engine, ["nodes", "sheet", S101], {}).body.decode("utf-8"))
        self.assertEqual(body["segments"][0]["node_id"], "S1")
        self.assertIsNone(api_nodes.read(self.engine, ["nodes", "node", "S9"], {}))
        self.assertIsNone(api_nodes.read(self.engine, ["nodes", "zzz"], {}))
        self.assertIsNone(api_nodes.read(self.engine, ["nodes", "sheet", "../../x"], {}))
        self.assertIsNone(api_nodes.read(self.engine, ["nodes", "sheet", "graph-없는-도면"], {}))


class RoundTripTest(Env):
    def test_create_then_reopen_keeps_ids_rev_and_set_rev(self):
        self.create("가", 0, 5, design_intent="의도")
        self.create("나", 5, 9)
        self.call("rename", {"node_id": "S1", "name": "가 고침"})
        before = api_nodes.summary(self.engine)
        nodes_before = copy.deepcopy(before["nodes"])
        # 앱을 다시 연다: 새 엔진·새 읽기, 같은 작업 루트의 파일만 남음
        from hazop.study import node_tools
        node_tools.clear_cache()
        engine2 = self.new_engine()
        engine2.settings["project_id"] = "SNP"
        engine2.settings["reviewer_name"] = "홍길동"
        after = api_nodes.summary(engine2)
        self.assertEqual(after["set_rev"], before["set_rev"])
        self.assertEqual(after["nodes"], nodes_before)
        self.assertEqual([n["node_id"] for n in after["nodes"]], ["S1", "S2"])
        # 다시 연 뒤에도 같은 판으로 이어서 쓸 수 있다
        r = engine2.dispatch("nodes.rename", {"project_id": "SNP", "node_id": "S2", "name": "나 고침", "set_rev": after["set_rev"],
                                              "targets": [{"node_id": "S2", "rev": after["nodes"][1]["rev"], "state": "applied"}]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["set_rev"], after["set_rev"] + 1)

    def test_other_process_write_makes_old_screen_stale(self):
        self.create("가", 0, 5)
        seen = api_nodes.summary(self.engine)
        # 다른 곳(채팅)에서 구간 하나를 더 만든다
        ids = [n["entity_id"] for n in self.by_sheet[S101][5:9]]
        out = node_commands.execute(self.pg, "create", {"items": [{"members": ids, "name": "다른 곳"}]}, author="user", confirmed_by="누군가",
                                    set_rev=seen["set_rev"])
        self.assertTrue(out["ok"])
        r = self.call("rename", {"node_id": "S1", "name": "낡은 화면의 이름", "set_rev": seen["set_rev"]})
        self.assertEqual(r["error"]["code"], "stale")
        self.assertEqual(api_nodes.summary(self.engine)["nodes"][0]["name"], "가")


class CommandTableTest(unittest.TestCase):
    def test_all_commands_registered_with_set_rev_and_no_who_keys(self):
        if True:
            names = sorted(k for k in api.COMMANDS if k.startswith("nodes."))
            self.assertEqual(names, ["nodes." + x for x in sorted(
                ["create", "add_members", "remove_members", "rename", "set_intent", "merge", "split", "remove", "confirm", "unconfirm",
                 "lock", "unlock", "undo", "suggest", "migrate"])])
            for k in names:
                spec = api.COMMANDS[k].spec
                self.assertFalse({"by", "at", "author", "origin", "confirmed_by", "request"} & set(spec), k)
                self.assertTrue(spec["project_id"][1], k)
                if k not in ("nodes.suggest", "nodes.migrate"):
                    self.assertTrue(spec["set_rev"][1], k)
                    # 구간을 건드리는 명령은 대상의 판(targets)이 필수다(규격 §5.3). 만들기·묶음 되돌리기는 대상 구간이 없다
                    self.assertEqual(spec["targets"][1], k not in ("nodes.create", "nodes.undo"), k)


class BigSetTimingTest(Env):
    """525구간·구성요소 5,800개: 목록·도면 한 장 읽기 시간(조건은 출력에 적는다). 측정이 목적이라 상한은 넉넉히 둔다."""

    def test_525_nodes_5800_members(self):
        comps = []
        for i in range(5800):
            comps.append({"entity_id": "graph-BIG-%02d/e%d" % (i % 143, i), "sheet": "graph-BIG-%02d" % (i % 143), "local_id": "n%d" % i,
                          "category": "equipment" if i % 9 == 0 else "pipe", "tag": "T%d" % i if i % 9 == 0 else None, "kind": "tank"})
        pg = {"project_id": "BIG", "graph_id": None, "graph_version": "v-big", "nodes": comps, "edges": []}
        ns = nodes.new_set(pg)
        ns["nodes"] = [dict(nodes._v2_fields("user"), node_id="S%d" % (k + 1), name="구간 %d" % (k + 1), basis="x",
                            members=[comps[(k * 11 + j) % 5800]["entity_id"] for j in range(11)]) for k in range(525)]
        ns["graph_member_refs"] = {}
        self.pg = pg
        nodes.write(nodes.store_path("BIG", None), ns) if False else None
        with mock.patch.object(nodes, "read_as_is", lambda g: copy.deepcopy(ns)):
            t0 = time.perf_counter()
            s = api_nodes.summary(self.engine)
            t1 = time.perf_counter()
            v = api_nodes.sheet_view(self.engine, "graph-BIG-00")
            t2 = time.perf_counter()
            d = api_nodes.detail(self.engine, "S300")
            t3 = time.perf_counter()
        print("\n[525구간·구성요소 5,800개, 합성 그래프, 엔진 읽기(웹 없음), 1회 | summary %.0f ms · sheet_view %.0f ms · detail %.0f ms | 응답 %d·%d·%d KB]" % (
            (t1 - t0) * 1000, (t2 - t1) * 1000, (t3 - t2) * 1000, len(json.dumps(s)) // 1024, len(json.dumps(v)) // 1024, len(json.dumps(d)) // 1024))
        self.assertEqual(len(s["nodes"]), 525)
        self.assertTrue(v["segments"])
        self.assertEqual(d["members_total"], 11)
        self.assertLess(t1 - t0, 2.0)


if __name__ == "__main__":
    unittest.main()


class WiringTest(unittest.TestCase):
    def test_api_module_registers_nodes_commands_and_read_route_by_itself(self):
        """api.py를 새 프로세스에서 불러 register 호출과 읽기 길(TOPIC_OWNER)이 이어졌는지 본다(시험 쪽에서 register를 부르지 않는다)."""
        import subprocess
        code = ("from hazop.shell import api; e = api.Engine(); "
                "print('nodes.create' in api.COMMANDS and 'nodes.suggest' in api.COMMANDS and "
                "api.TOPIC_OWNER.get('nodes').__name__ == 'hazop.shell.api_nodes')")
        out = subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout.strip()
        self.assertEqual(out.splitlines()[-1], "True", out)


class ProjectSwitchTest(Env):
    """프로젝트를 바꾼 뒤 낡은 목록으로 보낸 쓰기 명령이 다른 프로젝트의 구간을 쓰지 않는다(3단계 검토 재현)."""

    def setUp(self):
        super().setUp()
        from hazop.app import project_ctx
        self.a = self.pg
        self.b = copy.deepcopy(self.a)
        self.b["project_id"] = "OTHER"
        patcher = mock.patch.object(project_ctx, "project_graph", lambda pid: self.b if pid == "OTHER" else self.a)
        patcher.start()
        self.addCleanup(patcher.stop)

    def switch(self, pid):
        self.engine.dispatch("project.set", {"project_id": pid})
        self.pg = self.b if pid == "OTHER" else self.a

    def test_old_list_of_project_a_cannot_confirm_in_project_b(self):
        self.create(name="A 구간")
        self.switch("OTHER")
        self.create(name="B 구간")
        self.switch("SNP")
        web = api_nodes.summary(self.engine)                     # 웹이 A에서 읽어 들고 있는 목록
        self.assertEqual((web["project_id"], web["nodes"][0]["name"]), ("SNP", "A 구간"))
        self.switch("OTHER")                                      # 위 막대에서 프로젝트를 바꿈
        n = web["nodes"][0]
        r = self.engine.dispatch("nodes.confirm", {"project_id": web["project_id"], "node_ids": [n["node_id"]], "set_rev": web["set_rev"],
                                                    "targets": [{"node_id": n["node_id"], "rev": n["rev"], "state": n["state"]}]})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "stale")
        self.assertIn("프로젝트가 바뀌어", r["error"]["message"])
        self.assertEqual([(x["name"], x["state"]) for x in api_nodes.summary(self.engine)["nodes"]], [("B 구간", "applied")])

    def test_project_id_is_required_on_every_write_and_suggest_and_migrate(self):
        self.create()
        for name, args in [("rename", {"node_id": "S1", "name": "x"}), ("confirm", {"node_ids": ["S1"]}), ("undo", {"batch_id": "B1"}),
                           ("create", {"sheet": S101, "ids": self.local(S101, 0, 2), "name": "x"}), ("suggest", {"sheet": S101, "ids": self.local(S101, 0, 2)}),
                           ("migrate", {})]:
            a = dict(args)
            if name not in ("suggest", "migrate"):
                a["set_rev"] = self.rev()
            r = self.engine.dispatch("nodes." + name, a)
            self.assertEqual(r["error"]["code"], "bad_args", name)
            self.assertIn("project_id", r["error"]["message"], name)
        r = self.engine.dispatch("nodes.suggest", {"project_id": "OTHER", "sheet": S101, "ids": self.local(S101, 0, 2)})
        self.assertEqual(r["error"]["code"], "stale")
        r = self.engine.dispatch("nodes.migrate", {"project_id": "OTHER"})
        self.assertEqual(r["error"]["code"], "stale")


class ReviewFixTest(Env):
    """총괄 검토(2026-11-13)에서 반려된 점의 재현: 말없이 뺌, 읽기가 쓰기, targets 선택, 문구 대조, 이름 겹침, 묶음 ID."""

    def test_targets_are_required_for_node_commands(self):
        self.create()
        pid = self.engine.project_id()
        r = self.engine.dispatch("nodes.rename", {"project_id": pid, "node_id": "S1", "name": "x", "set_rev": self.rev()})
        self.assertEqual(r["error"]["code"], "bad_args")
        self.assertIn("targets", r["error"]["message"])
        r = self.engine.dispatch("nodes.rename", {"project_id": pid, "node_id": "S1", "name": "x", "set_rev": self.rev(), "targets": []})
        self.assertEqual(r["error"]["code"], "bad_args")      # 건드리는 구간의 판이 빠짐
        r = self.engine.dispatch("nodes.rename", {"project_id": pid, "node_id": "S1", "name": "x"})
        self.assertEqual(r["error"]["code"], "bad_args")      # set_rev 빠짐
        self.assertEqual(api_nodes.summary(self.engine)["nodes"][0]["name"], "구간 가")

    def test_dropped_ids_are_counted_and_worded_in_the_answer(self):
        self.create(a=0, b=3)
        ids = self.local(S101, 3, 5) + ["sig-a", "sig-b"]
        for name in ("add_members", "remove_members"):
            r = self.call(name, {"node_id": "S1", "sheet": S101, "ids": ids})
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["data"]["skipped"], 2, name)
            self.assertIn("2개는 구성요소가 아닌 선", r["data"]["skipped_text"])
        r = self.call("split", {"node_id": "S1", "sheet": S101, "ids": self.local(S101, 0, 1) + ["sig-x"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["skipped"], 1)
        r = self.call("rename", {"node_id": "S2", "name": "나눈 구간"})
        self.assertEqual(r["data"]["skipped"], 0)
        self.assertNotIn("skipped_text", r["data"])

    def test_noop_edit_returns_no_batch_id(self):
        self.create("가", 0, 3)
        self.create("나", 3, 6)
        r = self.call("remove_members", {"node_id": "S1", "sheet": S101, "ids": self.local(S101, 3, 6)})   # S1에 없는 것을 뺌
        self.assertTrue(r["ok"], r)
        self.assertIsNone(r["data"]["batch_id"])

    def test_read_never_writes_and_legacy_is_converted_only_on_request(self):
        pg = self.pg
        path = nodes.store_path(pg.get("project_id"), pg.get("graph_id"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mem = [n["entity_id"] for n in self.by_sheet[S101][:5]]
        doc = {"schema_version": "0.1", "kind": "hazop_study_nodes", "project_id": pg.get("project_id"), "graph_id": pg["graph_id"],
               "graph_version": pg.get("graph_version"), "status": "confirmed", "confirmed_at": "2026-01-01T00:00:00Z",
               "confirmed_by": "hong", "nodes": [{"node_id": "S1", "name": "옛 구간", "origin": "rule", "members": mem}], "history": []}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        before = (sorted(os.listdir(os.path.dirname(path))), _rb(path))
        s = api_nodes.summary(self.engine)
        api_nodes.sheet_view(self.engine, S101)
        api_nodes.detail(self.engine, "S1")
        self.assertEqual((sorted(os.listdir(os.path.dirname(path))), _rb(path)), before)   # 읽기는 파일을 바꾸지 않는다
        self.assertTrue(s["legacy"])
        self.assertEqual(s["nodes"], [])
        r = self.create()
        self.assertEqual(r["error"]["code"], "failed")        # 변환 전에는 쓰지 않는다
        self.assertIn("새 판", r["error"]["message"])
        self.assertEqual(_rb(path), before[1])
        m = self.engine.dispatch("nodes.migrate", {"project_id": self.engine.project_id()})
        self.assertTrue(m["ok"], m)
        s2 = api_nodes.summary(self.engine)
        self.assertFalse(s2["legacy"])
        self.assertEqual([n["node_id"] for n in s2["nodes"]], ["S1"])
        self.assertEqual(json.loads(_rb(path).decode("utf-8"))["schema_version"], "0.2")

    def test_locked_is_decided_by_state_not_by_wording(self):
        self.create()
        self.call("confirm", {"node_ids": ["S1"]})
        with mock.patch.object(node_commands, "execute", lambda *a, **k: {"ok": False, "refused": [{"target": "x", "code": "rule", "reason": "전혀 다른 문장"}]}):
            r = self.call("rename", {"node_id": "S1", "name": "x"})
            self.assertEqual(r["error"]["code"], "locked")
            self.assertEqual(r["error"]["message"], "전혀 다른 문장")
        self.call("unconfirm", {"node_ids": ["S1"]})
        with mock.patch.object(node_commands, "execute", lambda *a, **k: {"ok": False, "refused": [{"target": "x", "code": "rule", "reason": "확정 구간은 이렇게 적혀도"}]}):
            r = self.call("rename", {"node_id": "S1", "name": "x"})
            self.assertEqual(r["error"]["code"], "failed")     # 문구에 '확정'이 있어도 적용됨 구간이면 locked가 아니다
        with mock.patch.object(node_commands, "execute", lambda *a, **k: {"ok": False, "refused": [{"target": "x", "code": "conflict", "reason": "x"}]}):
            self.assertEqual(self.call("rename", {"node_id": "S1", "name": "x"})["error"]["code"], "stale")

    def test_remove_with_judged_cells_asks_for_archive_and_saves_nothing(self):
        self.create("가", 0, 4)
        self.create("나", 4, 8)
        self.assertTrue(self.call("confirm", {"node_ids": ["S1"]})["ok"])
        ns = nodes.load(self.pg)
        doc, fp = res.load_fp(ns)
        if doc is None:
            doc = res.empty_results(ns, res.load_deviations())
        cells = [c for c in doc.get("cells") or [] if c.get("node_id") == "S1"]
        self.assertTrue(cells)
        cells[0].setdefault("entries", []).append({"entry_id": "E1", "status": "accepted", "by": "hong", "origin": "user", "cause": "x"})
        cells[0]["state"] = "analyzed"
        res.save_fp(doc, ns.get("project_id"), expect=fp)
        self.assertTrue(self.call("unconfirm", {"node_ids": ["S1"]})["ok"])
        before = api_nodes.summary(self.engine)
        r = self.call("remove", {"node_id": "S1"})
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["data"]["needs_archive"], r["data"]["batch_id"]), (True, None))
        self.assertEqual(api_nodes.summary(self.engine)["set_rev"], before["set_rev"])
        r = self.call("remove", {"node_id": "S1", "archive": True})
        self.assertTrue(r["ok"], r)
        self.assertEqual([n["node_id"] for n in api_nodes.summary(self.engine)["nodes"]], ["S2"])

    def test_register_refuses_a_name_that_exists(self):
        table = {}
        api_nodes.register(table)
        with self.assertRaises(ValueError) as cm:
            api_nodes.register(table)
        self.assertIn("nodes.create", str(cm.exception))
