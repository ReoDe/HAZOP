"""채팅으로 앱 기능 실행(A11 1차): 표시 동작과 실행 동작의 새 화면 연결부. 실행: python -m unittest tests.test_shell_chat_run

가짜 클라이언트(세션)가 `actions`가 든 답을 내면 실제 동작 층·실제 엔진 함수로 판정·실행해, 웹으로 가는 사건과 저장·기록이 맞는지 본다.
실제 구독 호출은 하지 않는다(AI 분석 시작 함수는 가짜로 바꾼다). 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다.
각 실행 동작마다: 실행됨 · 확인 없이는 실행 안 됨 · 기록 남음 · 잠긴 구간·확정본 거부.
"""

import copy
import os
import unittest
from unittest import mock

from hazop import paths
from hazop.chat import actions as A
from hazop.shell import api_results, chat_actions
from hazop.study import node_tools as nt
from hazop.study import nodes as sn
from hazop.study import result_commands as rc
from hazop.study import results as res
from tests.test_shell_chat_actions import Base
from tests.test_study_node_tools import DEVS

AT = "2026-11-14T00:00:00Z"
PUMP = "graph-SNP-M-101/entity-node-003"     # RC-PP01, 도면 graph-SNP-M-101의 local-node-003


class RunBase(Base):
    """사람이 만든 확정 구간 S1·S2와, S1 칸에 AI 초안 항목 e1·사람 항목 e2가 든 결과 파일."""

    def setUp(self):
        super().setUp()
        with mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)):
            ns = sn.new_set(self.pg)
            cands = nt.make_candidates(self.pg, ns, granularity="normal", limit=30)["candidates"][:2]
            ns, _r, _b = nt.apply_nodes(ns, None, self.pg, [{"op": "add", "cand_id": c["cand_id"], "name": "구간 %d" % i}
                                                            for i, c in enumerate(cands)], {}, "user", ns["set_rev"], at=AT)
            ns = sn.confirm(ns, self.pg, "검토자", at=AT)
            sn.save(ns)
            doc = res.empty_results(ns, DEVS)
            cell = next(c for c in doc["cells"] if c["node_id"] == "S1")
            cell.update(state="analyzed", entries=[
                {"entry_id": "e1", "origin": "ai_draft", "status": "proposed", "cause": "원인 e1", "consequence": "결과", "safeguards": []},
                {"entry_id": "e2", "origin": "human", "status": "approved", "cause": "원인 e2", "consequence": "결과", "safeguards": []}])
            for c in doc["cells"]:
                if not c["entries"]:
                    c["state"] = "excluded"
            res.save(doc, ns["project_id"])
        self.names = {"graph-SNP-M-101": "SNP-M-101", "graph-SNP-M-102": "SNP-M-102"}
        p = mock.patch.object(self.engine, "graph_names", lambda: dict(self.names))
        p.start()
        self.addCleanup(p.stop)

    def act(self, action, **args):
        return {"action": action, "args": args, "why": "사용자가 시킴"}

    def one(self, action, text="해 줘", **args):
        out = self.ask([self.act(action, **args)], text)
        self.assertIsNotNone(out, "chat.actions 사건이 와야 한다")
        return out["items"][0]

    def entry(self, eid):
        doc = res.load(sn.load(self.pg))
        return next(e for c in doc["cells"] for e in c["entries"] if e["entry_id"] == eid)

    def approve(self, item):
        return self.engine.dispatch("chat.action.approve", {"token": item["token"]})

    def last_record(self, action):
        rows = [r for r in self.records if (r.get("proposal") or {}).get("action") == action]
        return rows[-1] if rows else None


# ---------------------------------------------------------------- 표시 동작

class DisplayTest(RunBase):
    def display(self, actions, text="보여 줘"):
        before = len(self.events.of("chat.display"))
        self.answers.append(self.answer(actions))
        self.assertTrue(self.chat.ask(text))
        got = self.events.of("chat.display")
        self.assertEqual(len(got), before + 1, "chat.display 사건이 하나 온다")
        return got[-1]["items"]

    def test_show_by_tag_opens_the_sheet_and_marks_it(self):
        item = self.display([self.act("show", ids=["rc-pp01"])], "RC-PP01 보여 줘")[0]
        self.assertEqual((item["op"], item["ok"], item["sheet"], item["ids"]), ("show", True, "graph-SNP-M-101", ["local-node-003"]))
        mark = item["marks"]["graph-SNP-M-101"][0]
        self.assertEqual((mark["op"], mark["groups"][0]["ids"], mark["dim_others"]), ("mark", ["local-node-003"], True))
        self.assertIn("RC-PP01", item["text"])
        self.assertIn("SNP-M-101", item["text"])

    def test_show_by_entity_id_and_unknown_ids(self):
        item = self.display([self.act("show", ids=[PUMP, "NO-SUCH-TAG"])])[0]
        self.assertEqual(item["ids"], ["local-node-003"])
        self.assertIn("찾지 못한 것: NO-SUCH-TAG", item["text"])
        none = self.display([self.act("show", ids=["NO-SUCH-TAG"])])[0]
        self.assertEqual((none["op"], none["ok"]), ("none", False))

    def test_display_is_not_recorded_and_changes_nothing(self):
        before = sn.load(self.pg)
        self.display([self.act("show", ids=["RC-PP01"]), self.act("fit"), self.act("layer", name="태그", on=False)])
        self.assertEqual(self.records, [], "표시는 실행 기록에 남기지 않는다(채팅 규격 §4.7)")
        self.assertEqual(sn.load(self.pg), before)

    def test_goto_select_layer_fit(self):
        items = self.display([self.act("goto", target="nodes", id="S1"), self.act("goto", target="⑤"),
                              self.act("goto", target="results", id="S1/D01"), self.act("goto", target="drawings", id="SNP-M-102"),
                              self.act("goto", target="kg"), self.act("goto", target="nodes", id="S99"),
                              self.act("select", ids=["RC-PP01"]), self.act("layer", name="배관", on=False),
                              self.act("fit", sheet="graph-SNP-M-101")])
        self.assertEqual((items[0]["op"], items[0]["panel"], items[0]["node_id"]), ("panel", "nodes", "S1"))
        self.assertEqual((items[1]["op"], items[1]["panel"]), ("panel", "results"))
        self.assertEqual(items[2]["cell"], ["S1", "D01"])
        self.assertEqual((items[3]["op"], items[3]["sheet"]), ("open", "graph-SNP-M-102"))
        self.assertEqual((items[4]["op"], items[4]["panel"]), ("panel", "kg"))
        self.assertEqual(items[5]["op"], "none")
        self.assertEqual((items[6]["op"], items[6]["marks"]["graph-SNP-M-101"][0]["dim_others"]), ("show", False))
        self.assertEqual((items[7]["op"], items[7]["layer"], items[7]["on"]), ("layer", "pipe", False))
        self.assertEqual((items[8]["op"], items[8]["sheet"]), ("fit", "graph-SNP-M-101"))

    def test_sheet_paths_are_refused_by_the_signature(self):
        out = self.ask([self.act("show", sheet="C:/Windows")], "보여 줘")
        self.assertEqual(out["items"][0]["status"], "rejected")


# ---------------------------------------------------------------- 실행 동작

class AnalysisRunTest(RunBase):
    def setUp(self):
        super().setUp()
        self.calls = []
        # 범위 지문(scope_fp)은 엔진 쪽 함수가 있을 때만 실린다. 다른 인자 대조는 지문을 빼고 본다(지문은 따로 시험)
        p = mock.patch.object(api_results, "_run", lambda engine, a: self.calls.append({k: v for k, v in a.items() if k != "scope_fp"})
                              or self.fps.append(a.get("scope_fp")) or {"job": "j1", "calls": 13})
        self.fps = []
        p.start()
        self.addCleanup(p.stop)

    def test_needs_confirmation_then_runs_once_and_is_recorded(self):
        item = self.one("analysis.run", "S1 구간 분석해 줘", node_ids=["S1"])
        self.assertEqual(item["status"], "confirm")
        self.assertIn("구독 한도", {r["label"]: r["after"] for r in item["details"]}["호출 수 어림"], "연결 설정이 없는 엔진은 구독")
        self.assertEqual(self.calls, [], "확인 전에는 시작하지 않는다")
        r = self.approve(item)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.calls, [{"scope": "node", "node_id": "S1"}])
        done = self.events.of("chat.action.result")[-1]["item"]
        self.assertEqual(done["status"], "applied")
        self.assertIn("S1", done["text"])
        self.assertIn("13", done["text"])
        rec = self.last_record("analysis.run")
        self.assertEqual((rec["result"], rec["klass"], rec["confirmed_by"]), ("ok", "confirm", "홍길동"))
        self.assertEqual(self.approve(item)["data"]["result"], "duplicate", "같은 확인을 두 번 실행하지 않는다")
        self.assertEqual(len(self.calls), 1)

    def test_paid_api_key_run_shows_the_cost_and_passes_the_confirmation(self):
        """API 키(과금) 연결이면 확인 상자에 실제 연결과 예상 비용을 보이고, 확인하면 본 연결 판과 비용 확인을 넘긴다(B4, e62bfeb)."""
        plan = {"via": "api", "method_name": "API 키", "model_name": "보통", "paid": True, "conn_ver": "cv-1",
                "confirm_text": "API 키(업무 키)로 호출마다 요금이 나갑니다. 예상 약 $0.42."}
        with mock.patch.object(api_results, "_run_conn", lambda engine, units, method=None: dict(plan)):
            item = self.one("analysis.run", node_ids=["S1"])
            rows = {r["label"]: r["after"] for r in item["details"]}
            self.assertNotIn("구독 한도", rows["호출 수 어림"])
            self.assertTrue(rows["연결"].startswith("API 키 · 보통"))
            self.assertEqual(rows["요금"], plan["confirm_text"])
            self.approve(item)
        self.assertEqual(self.calls, [{"scope": "node", "node_id": "S1", "conn_ver": "cv-1", "confirm_paid": True}])

    def test_subscription_run_passes_the_seen_connection_without_paying(self):
        plan = {"via": "subscription", "method_name": "Claude 구독", "model_name": "빠름", "paid": False, "conn_ver": "cv-s"}
        with mock.patch.object(api_results, "_run_conn", lambda engine, units, method=None: dict(plan)):
            item = self.one("analysis.run", node_ids=["S1"])
            self.assertNotIn("요금", {r["label"] for r in item["details"]})
            self.approve(item)
        self.assertEqual(self.calls, [{"scope": "node", "node_id": "S1", "conn_ver": "cv-s"}])

    def test_connection_changed_after_the_box_is_not_run(self):
        plan = {"via": "api", "method_name": "API 키", "model_name": "보통", "paid": True, "conn_ver": "cv-1", "confirm_text": "$0.42"}
        with mock.patch.object(api_results, "_run_conn", lambda engine, units, method=None: dict(plan)):
            item = self.one("analysis.run", node_ids=["S1"])
            plan["confirm_text"], plan["conn_ver"] = "$9.99", "cv-2"
            self.approve(item)
        self.assertEqual(self.calls, [], "상자에 보인 비용과 지금 비용이 다르면 실행하지 않는다")

    def test_the_scope_seen_in_the_box_is_passed_as_scope_fp(self):
        from hazop.shell import analysis_run
        if not hasattr(analysis_run, "scope_fp"):
            self.skipTest("엔진에 범위 지문(analysis_run.scope_fp)이 아직 없음")
        plan = {"via": "subscription", "method_name": "Claude 구독", "model_name": "빠름", "paid": False, "conn_ver": "cv-s", "model": "fast"}
        with mock.patch.object(api_results, "_run_conn", lambda engine, units, method=None: dict(plan)):
            self.approve(self.one("analysis.run", node_ids=["S1"]))
        self.assertEqual(len(self.fps), 1)
        self.assertTrue(self.fps[0], "구독이어도 확인한 범위 지문을 넘긴다")

    def test_decline_runs_nothing_and_is_recorded(self):
        item = self.one("analysis.run", node_ids=["S1"])
        self.engine.dispatch("chat.action.decline", {"token": item["token"]})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.last_record("analysis.run")["result"], "declined")

    def test_one_node_at_a_time_and_cells(self):
        item = self.one("analysis.run", node_ids=["S1", "S2"])
        self.assertEqual((item["status"], item["token"]), ("rejected", None), "여러 구간은 확인 상자를 띄우기 전에 거절")
        self.assertIn("한 구간씩", item["reason"])
        self.assertEqual(self.calls, [])
        item = self.one("analysis.run", node_ids=["S1"], cell_ids=["S1/D01", "S1/D02"])
        self.assertEqual(item["status"], "rejected")
        item = self.one("analysis.run", node_ids=["S1"], cell_ids=["S1/D01"])
        self.approve(item)
        self.assertEqual(self.calls, [{"scope": "cell", "node_id": "S1", "deviation_id": "D01"}])

    def test_locked_node_refused(self):
        with mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)):
            rc.execute(self.pg, "set_status", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e1", "status": "approved"}, "다른 창", None)
            ns = sn.load(self.pg)
            sn.save(sn.lock_node(ns, "S1", "다른 창", res.load(ns)))
        item = self.one("analysis.run", node_ids=["S1"])
        self.assertEqual(item["status"], "rejected")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.last_record("analysis.run")["result"], "rejected")


class VerdictTest(RunBase):
    def test_verdict_needs_confirmation_and_saves_with_the_reviewer(self):
        with mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)):
            item = self.one("results.set_status", "e1 기각해 줘", node_id="S1", deviation_id="D01", entry_id="e1", status="rejected",
                            reason="같은 원인 중복")
            self.assertEqual(item["status"], "confirm")
            self.assertEqual(self.entry("e1")["status"], "proposed", "확인 전에는 바꾸지 않는다")
            self.assertTrue(self.approve(item)["ok"])
            v = res.verdict(self.entry("e1"))
        self.assertEqual((v["status"], v["reason"], v["by"]), ("rejected", "같은 원인 중복", "홍길동"))
        done = self.events.of("chat.action.result")[-1]["item"]
        self.assertEqual(done["status"], "applied")
        self.assertIn("기각", done["text"])
        self.assertTrue(self.events.changes("results"), "분석 결과 패널이 다시 읽도록 changed(results)")
        self.assertEqual(self.last_record("results.set_status")["confirmed_by"], "홍길동")

    def test_edit_entry(self):
        with mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)):
            item = self.one("results.edit", node_id="S1", deviation_id="D01", entry_id="e1", fields={"cause": "고친 원인"}, reason="태그 바로잡음")
            self.assertTrue(self.approve(item)["ok"])
            e = self.entry("e1")
        self.assertEqual((e["cause"], e["status"]), ("고친 원인", "revised"))

    def test_reason_required_and_locked_refused(self):
        with mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)):
            item = self.one("results.set_status", node_id="S1", deviation_id="D01", entry_id="e1", status="on_hold")
            self.assertEqual(item["status"], "rejected")
            self.assertIn("사유", item["reason"])
            rc.execute(self.pg, "set_status", {"node_id": "S1", "deviation_id": "D01", "entry_id": "e1", "status": "approved"}, "다른 창", None)
            ns = sn.load(self.pg)
            sn.save(sn.lock_node(ns, "S1", "다른 창", res.load(ns)))
            item = self.one("results.set_status", node_id="S1", deviation_id="D01", entry_id="e2", status="rejected", reason="잠긴 뒤")
        self.assertEqual(item["status"], "rejected")
        self.assertIn("잠긴", item["reason"])
        self.assertEqual(self.entry("e2")["status"], "approved")


class ExportTest(RunBase):
    def exports(self):
        folder = paths.output_root("exports")
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def test_excel_runs_without_a_dialog_and_never_overwrites(self):
        self.assertNotIn("save_path", self.engine.hooks, "대화상자 없이 쓴다")
        with mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)):
            first = self.one("export.excel", "결과를 Excel로 내보내 줘")
            second = self.one("export.excel", "한 번 더")
        self.assertEqual((first["status"], second["status"]), ("applied", "applied"), (first, second))
        files = self.exports()
        self.assertEqual(len(files), 2, "같은 분에 두 번 내보내도 앞 파일을 덮어쓰지 않는다")
        self.assertTrue(all(f.endswith(".xlsx") for f in files))
        self.assertIn(files[0], first["text"] + second["text"])
        self.assertNotIn(os.environ["HAZOP_WORK_ROOT"], first["text"], "전체 경로를 화면에 싣지 않는다")
        rec = self.last_record("export.excel")
        self.assertEqual((rec["result"], rec["klass"]), ("ok", "auto"))

    def test_ie_bundle(self):
        with mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)):
            item = self.one("export.ie_bundle", "인계 묶음 내보내 줘")
        self.assertEqual(item["status"], "applied", item)
        self.assertTrue(any(f.startswith("IE-") for f in self.exports()))

    def test_save_path_never_reuses_a_file_name(self):
        folder = os.path.join(self.tmp, "x")
        os.makedirs(folder)
        open(os.path.join(folder, "a.xlsx"), "w").close()
        open(os.path.join(folder, "a-2.xlsx"), "w").close()
        self.assertEqual(os.path.basename(chat_actions._unique(folder, "a.xlsx")), "a-3.xlsx")


class SheetTest(RunBase):
    def state(self, **by_gid):
        return mock.patch.object(chat_actions, "sheet_state", lambda name: by_gid.get(name.replace("-", "_"), {
            "state": "open", "fingerprint": "sha256:x", "rev": 0, "reason": "미확인 3곳"}))

    def test_open_sheet_is_refused_with_the_reason(self):
        with self.state():
            item = self.one("sheet.confirm", "SNP-M-101 확정해 줘", graph_id="graph-SNP-M-101")
        self.assertEqual(item["status"], "rejected")
        self.assertIn("미확인 3곳", item["reason"])
        self.assertEqual(self.last_record("sheet.confirm")["result"], "rejected")

    def test_ready_sheet_needs_confirmation_and_calls_the_engine(self):
        ready = {"state": "ready", "fingerprint": "sha256:a", "rev": 2, "reason": None}
        calls = []

        def confirm(engine, a):
            calls.append(a)
            return {"changed": True, "status": None}
        with self.state(SNP_M_101=ready), \
                mock.patch("hazop.shell.api_drawings.status", lambda engine, gid: {"available": True, "ver": "sha256:a", "rev": 2}), \
                mock.patch("hazop.shell.api_drawings._sheet_command", lambda command: confirm):
            item = self.one("sheet.confirm", graph_id="graph-SNP-M-101")
            self.assertEqual(item["status"], "confirm")
            self.assertEqual(calls, [])
            self.assertTrue(self.approve(item)["ok"])
        self.assertEqual(calls, [{"graph_id": "graph-SNP-M-101", "ver": "sha256:a", "rev": 2}])
        self.assertIn("확정했습니다", self.events.of("chat.action.result")[-1]["item"]["text"])
        self.assertEqual(self.last_record("sheet.confirm")["confirmed_by"], "홍길동")

    def test_sheet_changed_after_the_box_is_stale(self):
        ready = {"state": "ready", "fingerprint": "sha256:a", "rev": 2, "reason": None}
        with self.state(SNP_M_101=ready):
            item = self.one("sheet.confirm", graph_id="graph-SNP-M-101")
        with self.state(SNP_M_101=dict(ready, fingerprint="sha256:b")):
            self.approve(item)
        self.assertEqual(self.events.of("chat.action.result")[-1]["item"]["status"], "stale")

    def test_dexpi_needs_a_confirmed_sheet(self):
        with self.state():
            item = self.one("dexpi.export", graph_ids=["graph-SNP-M-101"])
        self.assertEqual(item["status"], "rejected")
        self.assertIn("확정된 쪽", item["reason"])

    def test_dexpi_writes_a_new_folder_without_asking(self):
        done = {"state": "confirmed", "fingerprint": "sha256:a", "rev": 3, "reason": None}
        seen = {}

        def export(engine, a):
            seen["dir"] = engine.hooks["save_dir"]("dexpi")
            seen["overwrite"] = engine.hooks["confirm_overwrite_files"](["x.dexpi.xml"])
            return {"cancelled": False, "folder": os.path.basename(seen["dir"]), "drawings": [{"graph_id": "graph-SNP-M-101"}], "not_exported": []}
        with self.state(SNP_M_101=done), mock.patch("hazop.shell.api_drawings._export", export):
            item = self.one("dexpi.export", "DEXPI로 내보내 줘", graph_ids=["graph-SNP-M-101"])
        self.assertEqual(item["status"], "applied", item)
        self.assertTrue(os.path.isdir(seen["dir"]))
        self.assertFalse(seen["overwrite"], "채팅 내보내기는 덮어쓰지 않는다")
        self.assertIn("도면 1장", item["text"])


class ReextractTest(RunBase):
    def test_reextract_needs_confirmation_and_starts_a_job(self):
        jobs = []
        regs = {"M-101": {"has_result": True, "excluded": False, "path": "reg.json"}}
        with mock.patch.object(chat_actions.ChatActions, "_registrations", lambda self_, pid: regs), \
                mock.patch.object(self.engine, "start_job", lambda label, fn, kind="register": jobs.append(label) or "j7"):
            item = self.one("register.reextract", "M-101 다시 추출해 줘", registration_id="M-101")
            self.assertEqual(item["status"], "confirm")
            self.assertEqual(jobs, [])
            self.assertTrue(self.approve(item)["ok"])
            self.assertEqual(jobs, ["다시 추출: M-101"])
            self.assertIn("j7", self.events.of("chat.action.result")[-1]["item"]["text"])
            again = self.one("register.extract", registration_id="M-101")
        self.assertEqual(again["status"], "rejected", "결과가 있으면 '추출'은 거절(다시 추출은 확인 필요)")


class NotYetTest(RunBase):
    def test_phase_two_actions_answer_not_yet(self):
        for name, args in (("kg.rebuild", {}), ("ie.reset", {}), 
                           ("settings.connection", {}), ("kg.algorithm", {"name": "x"})):
            with self.subTest(name):
                item = self.one(name, **args)
                self.assertEqual(item["status"], "rejected")
                self.assertIn("아직 채팅으로 할 수 없는", item["reason"])
                self.assertTrue(item["where"])
                self.assertEqual(self.last_record(name)["result"], "rejected")

    def test_without_an_engine_run_actions_are_not_offered(self):
        acts = chat_actions.ChatActions(lambda n, d: None, lambda: "SNP", lambda: self.pg, lambda: "홍길동", lambda t, r=None: None,
                                        record=lambda pid, **kw: {"status": "written"})
        self.assertIsNone(acts._engine)
        planner = acts._get()
        plan = planner.plan("a-x", [self.act("export.excel")], 1, "q-x")
        self.assertEqual(len(plan.rejected), 1)
        self.assertIn("아직", plan.rejected[0].reason)

    def test_card_schema_and_table_agree(self):
        for name in chat_actions.RUN_ACTIONS + chat_actions.DISPLAY_ACTIONS:
            self.assertIn(name, A.ACTIONS)
        for name in chat_actions.NOT_YET:
            self.assertIn(name, A.ACTIONS)
            self.assertNotIn(name, chat_actions.RUN_ACTIONS)


if __name__ == "__main__":
    unittest.main()
