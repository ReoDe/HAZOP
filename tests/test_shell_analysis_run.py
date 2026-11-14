"""B4: 새 화면 분석 실행의 연결 방식(API 키·고정 응답), 예상 비용 확인, '이어서 실행'. 실행: python -m unittest tests.test_shell_analysis_run

결과 파일·구간은 tests.test_shell_results.Base의 임시 작업 루트를 쓰고, 연결은 실제 AiConnection(가짜 CLI·가짜 키·임시 키 보관)이다.
AI 호출(ai_cells.run_unit)은 대역이라 네트워크·요금이 없다. 본다:
- 과금 경로(API 키)는 실행 카드의 예상 비용을 확인(confirm_paid + conn_ver)해야만 돈다. 채팅 길처럼 확인 없이 오면 AI를 부르지 않는다.
- 구독 한도로 멈춘 뒤 '이어서 실행'은 남은 칸만 돈다. 다른 방식(API 키)으로 잇는 것은 그때 고르고 비용을 확인한 경우뿐이고 이번 실행만이다.
- 카드를 본 뒤 설정에서 방식·모델이 바뀌면 시작하지 않는다(conn_changed).
- 고정 응답(시험)은 설정에서 고른 경우에만, 결과는 시험 파일에만 쓴다.
"""

import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hazop.shell import analysis_run, api, api_settings as S  # noqa: E402
from hazop.study import claude_http  # noqa: E402
from hazop.study import results as res  # noqa: E402
from hazop.study.ai_settings import AiPrefs  # noqa: E402
from hazop.study.apikey import KeyStore  # noqa: E402
from tests.test_ai_connection_ui import FakeOpener, pump_until, qapp  # noqa: E402
from tests.test_shell_results import Base, fake_run_unit  # noqa: E402
from tests.test_shell_settings import FAKE_KEY, Adapter, FakeCli  # noqa: E402


class ConnAdapter(Adapter):
    def terms_acked(self):
        return self.conn.method != "subscription" or self.conn.terms_acked()

    def ack_terms(self):
        self.conn.prefs.ack_terms()


class RunBase(Base):
    cli_state = "ok"
    debug = False

    def setUp(self):
        super().setUp()
        from hazop.app.ai_conn import AiConnection
        qapp()
        if "aiconn.use" not in api.COMMANDS:
            S.register(api.COMMANDS)
        prefs = AiPrefs(self.engine.settings, None)
        prefs.ack_terms()
        self.conn = AiConnection(prefs, KeyStore(os.path.join(self.tmp, "api_keys.json")), debug=self.debug,
                                 cli_factory=lambda path, **kw: FakeCli(self.cli_state, **kw), opener=FakeOpener(), auto_api=False)
        self.addCleanup(self.conn.tasks.wait, 20000)
        self.engine.ai = ConnAdapter(self.conn)
        self.conn.check("subscription")
        pump_until(lambda: self.conn.status("subscription")["state"] != "checking", self.conn)
        for p in (mock.patch.object(analysis_run, "contexts", lambda units, ns, pg, intent_of: {u["node_id"]: {} for u in units}),):
            p.start()
            self.addCleanup(p.stop)
        self.clients = []
        self.units = []

    def recording(self, inner=None):
        inner = inner or fake_run_unit()

        def run(client, unit, ctx, devs, at):
            self.clients.append(client)
            self.units.append((unit["node_id"], tuple(unit["deviation_ids"])))
            return inner(client, unit, ctx, devs, at)
        return run

    def go(self, run_unit=None, **args):
        with mock.patch("hazop.study.ai_cells.run_unit", self.recording(run_unit)):
            return self.call("results.run", dict({"scope": "all"}, **args))

    def plan(self, **args):
        r = self.call("results.run_plan", dict({"scope": "all"}, **args))
        self.assertTrue(r["ok"], r)
        return r["data"]

    def done(self):
        return [e["data"] for e in self.events.items if e.get("name") == "job.done"][-1]["result"]

    def use_api(self):
        self.conn.keys.add("업무 키", FAKE_KEY, persist=False)
        self.assertTrue(self.call("aiconn.use", {"method": "api", "confirmed": True})["ok"])
        self.conn.keys.record_test(self.conn.keys.active()["id"], True, "ok", "2026-11-14T00:00:00Z", self.conn.keys.model)
        self.conn.refresh()


class PaidConfirmTest(RunBase):
    def test_api_run_needs_the_cost_confirmed_on_the_card(self):
        self.use_api()
        p = self.plan()
        conn = p["conn"]
        self.assertEqual((conn["via"], conn["paid"], p["can_start"]), ("api", True, True), p)
        sections = len({n["node_id"] for n in self.ns["nodes"]})
        self.assertAlmostEqual(conn["usd"], round(sections * claude_http.MODELS[conn["model"]]["section_usd"], 2))
        self.assertIn("$", conn["confirm_text"])
        self.assertNotIn(FAKE_KEY[-12:], json.dumps(p, ensure_ascii=False))
        r = self.go()                                           # 채팅 길처럼 확인 없이
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "need_confirm"))
        self.assertIn("$", r["error"]["message"])
        r = self.go(conn_ver=conn["conn_ver"])                  # 판만 있고 확인이 없어도
        self.assertEqual(r["error"]["code"], "need_confirm")
        self.assertEqual(self.units, [], "확인 없이는 AI를 한 번도 부르지 않는다")
        r = self.go(conn_ver=conn["conn_ver"], confirm_paid=True)
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.units)
        self.assertTrue(all(isinstance(c, claude_http.ClaudeHttpClient) for c in self.clients))
        self.assertEqual(self.done()["method"], "api")

    def test_confirm_box_lines_show_method_model_and_cost(self):  # 채팅 확인 상자 줄(d-chat이 analysis_details에서 쓴다)
        rows = S.run_lines(self.plan()["conn"])
        self.assertEqual([r["label"] for r in rows], ["연결"])
        self.assertIn("Claude 구독", rows[0]["after"])
        self.use_api()
        rows = S.run_lines(self.plan()["conn"])
        self.assertEqual([r["label"] for r in rows], ["연결", "요금"])
        self.assertIn("$", rows[1]["after"])
        self.assertNotIn(FAKE_KEY[-12:], json.dumps(rows, ensure_ascii=False))
        self.assertEqual(S.run_lines(None)[0]["after"], "AI 연결이 없습니다")

    def test_subscription_run_needs_no_cost_confirmation(self):
        p = self.plan()
        self.assertEqual((p["conn"]["via"], p["conn"]["paid"], p["conn"]["confirm_text"]), ("subscription", False, ""))
        self.assertTrue(self.go(conn_ver=p["conn"]["conn_ver"])["ok"])
        self.assertTrue(all(isinstance(c, FakeCli) for c in self.clients))

    def test_switch_in_settings_after_seeing_the_card_is_asked_again(self):
        self.conn.keys.add("업무 키", FAKE_KEY, persist=False)
        seen = self.plan()["conn"]
        self.use_api()                                           # 카드를 본 뒤 설정에서 API로 바꿈
        r = self.go(conn_ver=seen["conn_ver"], confirm_paid=True)
        self.assertEqual(r["error"]["code"], "conn_changed")
        self.assertEqual(self.units, [])
        seen = self.plan()["conn"]
        self.call("aiconn.set_model", {"method": "api", "model": "claude-haiku-5-5"})
        self.assertEqual(self.go(conn_ver=seen["conn_ver"], confirm_paid=True)["error"]["code"], "conn_changed", "모델만 바뀌어도")


class ResumeTest(RunBase):
    def halt_first(self):
        limit = {"status": "limit_reached", "resets_at": "2026-11-14T09:00:00Z", "window": "five_hour"}
        first = fake_run_unit(kind="limit_reached", limit=limit)
        r = self.go(first, conn_ver=self.plan()["conn"]["conn_ver"])
        self.assertTrue(r["ok"], r)
        done = self.done()
        self.assertEqual(done["reason"], "halted")
        return done

    def test_resume_runs_only_the_cells_left_by_the_limit(self):
        planned = self.plan()["cells"]
        done = self.halt_first()
        rest = done["rest"]
        self.assertEqual(len(rest), planned, "한도에 걸린 단위의 칸 + 부르지 않은 칸 = 계획한 칸 전부(첫 단위가 실패)")
        p = self.plan(scope="resume")
        self.assertEqual(p["cells"], len(rest))
        self.units.clear()
        self.assertTrue(self.go(scope="resume", conn_ver=p["conn"]["conn_ver"])["ok"])
        ran = {(n, d) for n, ds in self.units for d in ds}
        self.assertEqual(ran, {tuple(c) for c in rest})
        self.assertEqual(self.done()["rest"], [])
        p = self.plan(scope="resume")
        self.assertEqual((p["calls"], p["can_start"], p["empty_text"]), (0, False, "이어서 실행할 칸이 없습니다."))

    def test_rest_skips_cells_already_done(self):
        calls = []
        inner_ok, inner_bad = fake_run_unit(), fake_run_unit(kind="limit_reached", limit={"status": "limit_reached"})

        def second_fails(client, unit, ctx, devs, at):
            calls.append(unit["unit_id"])
            return (inner_ok if len(calls) == 1 else inner_bad)(client, unit, ctx, devs, at)
        self.go(second_fails, conn_ver=self.plan()["conn"]["conn_ver"])
        rest = {tuple(c) for c in self.done()["rest"]}
        first_cells = {(n, d) for n, ds in self.units[:1] for d in ds}
        self.assertTrue(rest and not (rest & first_cells), "이미 받은 칸은 다시 부르지 않는다")

    def test_resume_with_api_is_this_run_only_and_needs_confirmation(self):
        self.conn.keys.add("업무 키", FAKE_KEY, persist=False)
        self.halt_first()
        self.assertEqual(self.conn.method, "subscription", "한도에 닿아도 API로 넘어가지 않는다")
        p = self.plan(scope="resume", method="api")
        self.assertEqual((p["conn"]["via"], p["conn"]["paid"], p["conn"]["this_run"]), ("api", True, True))
        self.assertIn("이번 실행만", p["conn"]["cost_text"])
        self.units.clear()
        r = self.go(scope="resume", method="api", conn_ver=p["conn"]["conn_ver"])
        self.assertEqual(r["error"]["code"], "need_confirm")
        seen_override = []
        inner = fake_run_unit()

        def watch(client, unit, ctx, devs, at):
            seen_override.append(self.conn.run_override)
            return inner(client, unit, ctx, devs, at)
        r = self.go(watch, scope="resume", method="api", conn_ver=p["conn"]["conn_ver"], confirm_paid=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(set(seen_override), {"api"}, "실행 중에는 칩에 '이번 실행만'")
        self.assertIsNone(self.conn.run_override)
        self.assertEqual((self.conn.method, self.conn.is_chosen()), ("subscription", False), "고른 방식은 그대로")
        self.assertTrue(all(isinstance(c, claude_http.ClaudeHttpClient) for c in self.clients[-len(self.units):]))

    def test_fixed_cannot_be_picked_for_one_run(self):
        r = self.call("results.run_plan", {"scope": "all", "method": "fixed"})
        self.assertEqual(r["error"]["code"], "bad_args")


class FixedTest(RunBase):
    debug = True

    def test_fixed_writes_only_the_test_file(self):
        folder = os.path.join(self.tmp, "fixed")
        os.makedirs(folder)
        self.conn.prefs._set(fixed_response_dir=folder)
        self.assertTrue(self.call("aiconn.use", {"method": "fixed"})["ok"])
        self.conn.set_status({"via": "fixed", "state": "ok"})
        before = res.load_fp(self.ns)[1]
        p = self.plan()
        self.assertEqual((p["conn"]["via"], p["conn"]["test"], p["conn"]["paid"]), ("fixed", True, False))
        self.assertIn("시험", p["conn"]["cost_text"])
        self.assertTrue(self.go(conn_ver=p["conn"]["conn_ver"])["ok"])
        self.assertEqual(res.load_fp(self.ns)[1], before, "실제 결과 파일은 그대로")
        test_doc, _fp = res.load_test_fp(self.ns)
        self.assertTrue(any(c["state"] == "analyzed" for c in test_doc["cells"]))
        self.assertTrue(self.done()["test"])
        self.assertEqual([e for e in self.events.items if e.get("name") == "results.cells"], [], "시험 결과는 화면 결과로 알리지 않는다")


class SettingsUsageTest(RunBase):
    def test_usage_line_and_locate_only_when_missing(self):
        self.conn.set_status({"via": "subscription", "state": "ok",
                              "limit": {"status": "allowed", "window": "five_hour", "utilization": 0.42, "resets_at": 1794646800}})
        s = json.loads(S.read(self.engine, ["aisettings"], {}).body.decode("utf-8"))["subscription"]
        self.assertIn("42%", s["usage"])
        self.assertFalse(s["can_locate"])
        self.conn.set_status({"via": "subscription", "state": "not_installed"})
        s = json.loads(S.read(self.engine, ["aisettings"], {}).body.decode("utf-8"))["subscription"]
        self.assertTrue(s["can_locate"])

    def test_locate_cli_keeps_the_path_in_python(self):
        exe = os.path.join(self.tmp, "claude.exe")
        open(exe, "wb").close()
        self.engine.hooks["pick_cli"] = lambda: exe
        r = self.engine.dispatch("aiconn.locate_cli", {}, via_web=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.conn.prefs.cli_path, exe)
        self.assertNotIn(self.tmp, json.dumps(r, ensure_ascii=False), "경로는 웹으로 보내지 않는다")
        self.engine.hooks["pick_cli"] = lambda: os.path.join(self.tmp, "settings.json")
        self.assertEqual(self.engine.dispatch("aiconn.locate_cli", {}, via_web=True)["error"]["code"], "bad_args")
        self.engine.hooks["pick_cli"] = lambda: None
        self.assertFalse(self.engine.dispatch("aiconn.locate_cli", {}, via_web=True)["data"]["set"])


if __name__ == "__main__":
    unittest.main()
