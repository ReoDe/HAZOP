"""AI(채팅)가 실행한 일의 기록 보기(hazop/shell/api_actionlog.py, A12). 실행: python -m unittest tests.test_shell_actionlog

임시 HAZOP_WORK_ROOT에 actions_log.record로 기록을 쓰고 읽기 API가 최근 순·날짜별로 화면 줄을 만드는지, 질문 원문을 웹으로 보내지 않는지,
대상을 구간·칸·도면·구성요소로 풀어 이동할 수 있게 하는지 본다.
"""

import copy
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from hazop.chat import actions_log
from hazop.shell import api, api_actionlog
from hazop.study import node_tools as nt
from hazop.study import nodes as sn
from hazop.study import results as res
from tests.test_study_node_tools import DEVS, snp_graph

SECRET = "비밀 질문 원문: 펌프 RC-PP01 근처 배관을 모두 지워 줘"
NOW = datetime(2026, 11, 14, 15, 30, tzinfo=actions_log.KST)


class ActionLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-actionlog-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "w"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "s")}),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))):
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        self.pg = snp_graph()
        from hazop.app import project_ctx
        p = mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg)
        p.start()
        self.addCleanup(p.stop)
        ns = sn.new_set(self.pg)
        cands = nt.make_candidates(self.pg, ns, granularity="normal", limit=30)["candidates"][:1]
        ns, _r, _b = nt.apply_nodes(ns, None, self.pg, [{"op": "add", "cand_id": cands[0]["cand_id"], "name": "가압기 구간"}], {}, "user",
                                    ns["set_rev"])
        sn.save(ns)
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"))
        self.engine.settings["project_id"] = "SNP"
        p = mock.patch.object(self.engine, "graph_names", lambda: {"graph-SNP-M-101": "SNP-M-101"})
        p.start()
        self.addCleanup(p.stop)

    def rec(self, answer, action, result, klass="auto", targets=(), at=NOW, args=None, **kw):
        return actions_log.record("SNP", answer_id=answer, index=0, request_id="q-1", request_text=SECRET,
                                  proposal={"action": action, "args": args or {}, "why": "사용자가 시킴"}, klass=klass, result=result,
                                  targets=list(targets), now=at, **kw)

    def test_recent_rows_newest_first_with_who_what_when_and_result(self):
        self.rec("a-1", "export.excel", "ok", at=NOW.replace(hour=9))
        self.rec("a-2", "analysis.run", "ok", klass="confirm", targets=["S1"], confirmed_by="홍길동",
                 confirmed_at=NOW.isoformat(), approval_digest="d" * 64)
        self.rec("a-3", "results.set_status", "declined", klass="confirm", targets=["S1/D01/e1"])
        self.rec("a-0", "kg.rebuild", "rejected", at=NOW.replace(day=12), error="아직 채팅으로 할 수 없는 동작입니다")
        out = api_actionlog.recent(self.engine, today=NOW)
        self.assertEqual([r["action"] for r in out["rows"]], ["results.set_status", "analysis.run", "export.excel", "kg.rebuild"])
        run = out["rows"][1]
        self.assertEqual((run["title"], run["by"], run["class_label"], run["confirmed_by"], run["result_label"], run["time"]),
                         ("AI 분석 실행", "채팅 AI", "사람 확인 뒤", "홍길동", "실행함", "15:30"))
        self.assertEqual(out["rows"][0]["result_label"], "사람이 하지 않음")
        self.assertEqual(out["rows"][3]["error"], "아직 채팅으로 할 수 없는 동작입니다")
        self.assertEqual(out["rows"][3]["title"], "지식그래프 다시 만들기")
        self.assertEqual(out["counts"], {"ok": 2, "declined": 1, "rejected": 1})

    def test_question_text_and_approval_digest_never_reach_the_web(self):
        self.rec("a-2", "analysis.run", "ok", klass="confirm", targets=["S1"], confirmed_by="홍길동", approval_digest="d" * 64)
        raw = api_actionlog.read(self.engine, ["actionlog"], {}).body.decode("utf-8")
        self.assertNotIn("비밀 질문", raw)
        self.assertNotIn("request_text", raw)
        self.assertNotIn("d" * 64, raw)
        self.assertNotIn("conversation_id", raw)
        # 기록 파일에는 규격대로 질문 한 개가 들어 있다(화면에만 싣지 않는다)
        with open(actions_log.day_path("SNP", NOW), encoding="utf-8") as fh:
            self.assertIn("비밀 질문", fh.read())

    def test_targets_resolve_to_node_cell_sheet_and_component(self):
        self.rec("a-1", "results.set_status", "ok", klass="confirm", confirmed_by="홍길동",
                 targets=["S1", "S1/D01/e1", "graph-SNP-M-101", "graph-SNP-M-101/entity-node-003", "M-101"])
        row = api_actionlog.recent(self.engine, today=NOW)["rows"][0]
        kinds = [(t["kind"], t["label"]) for t in row["targets"]]
        self.assertEqual(kinds, [("node", "S1 가압기 구간"), ("cell", "S1 편차 D01 항목 e1"), ("sheet", "도면 SNP-M-101"),
                                 ("component", "RC-PP01"), ("other", "M-101")])
        self.assertEqual(row["targets"][1]["cell"], ["S1", "D01"])
        self.assertEqual((row["targets"][3]["sheet"], row["targets"][3]["local_id"]), ("graph-SNP-M-101", "local-node-003"))

    def test_one_day_and_bad_dates(self):
        self.rec("a-1", "export.excel", "ok")
        self.rec("a-0", "export.excel", "ok", at=NOW.replace(day=13))
        day = json.loads(api_actionlog.read(self.engine, ["actionlog", "2026-11-13"], {}).body)
        self.assertEqual((day["day"], len(day["rows"])), ("2026-11-13", 1))
        self.assertIsNone(api_actionlog.read(self.engine, ["actionlog", "2026-13-40"], {}))
        self.assertIsNone(api_actionlog.read(self.engine, ["actionlog", "..%2F..%2Fsecret"], {}))
        empty = json.loads(api_actionlog.read(self.engine, ["actionlog", "2026-01-01"], {}).body)
        self.assertEqual(empty["rows"], [])

    def test_days_are_clamped_and_broken_lines_are_counted(self):
        self.rec("a-1", "export.excel", "ok")
        with open(actions_log.day_path("SNP", NOW), "a", encoding="utf-8") as fh:
            fh.write("{깨진 줄\n")
        out = json.loads(api_actionlog.read(self.engine, ["actionlog"], {"days": "9999"}).body)
        self.assertEqual((out["days"], out["bad"], len(out["rows"])), (api_actionlog.MAX_DAYS, 1, 1))
        out = json.loads(api_actionlog.read(self.engine, ["actionlog"], {"days": "x"}).body)
        self.assertEqual(out["days"], api_actionlog.DEFAULT_DAYS)

    def test_node_apply_title_counts_new_nodes(self):
        self.rec("a-1", "nodes.apply", "ok", args={"set_rev": 1, "ops": [{"op": "add"}, {"op": "add"}]}, batch_id="B3")
        row = api_actionlog.recent(self.engine, today=NOW)["rows"][0]
        self.assertEqual((row["title"], row["batch_id"]), ("구간 2개 만들기", "B3"))

    # ---- A12 검토 반영(재현 repro_review.py B1b·B2·B3)
    def test_B1b_wrong_typed_rows_are_skipped_and_counted(self):
        self.rec("a-1", "export.excel", "ok")
        path = actions_log.day_path("SNP", NOW)
        with open(path, "a", encoding="utf-8") as fh:
            for line in ('{"model_proposal":"x"}', '{"targets":5}', '{"model_proposal":{"action":"nodes.apply","args":[1]}}',
                         '{"model_proposal":{"action":"x"},"targets":[],"error":["a"]}'):
                fh.write(line[:-1] + ',"project_id":"SNP"}\n')
        out = api_actionlog.recent(self.engine, today=NOW)
        self.assertEqual((len(out["rows"]), out["bad"]), (1, 4))

    def test_B2_error_shows_file_names_not_local_paths(self):
        perm = "[Errno 13] Permission denied: '" + "C:\\Users\\someone\\x.xlsx" + "'"
        self.rec("a-9", "export.excel", "failed", error="save failed. " + perm)
        err = api_actionlog.recent(self.engine, today=NOW)["rows"][0]["error"]
        self.assertEqual(err, "save failed. [Errno 13] Permission denied: 'x.xlsx'")
        s = api_actionlog.strip_paths
        self.assertEqual(s("unc \\\\srv\\share\\d\\f.json end"), "unc f.json end")
        self.assertEqual(s("posix /home/u/w/data/x.json!"), "posix x.json!")
        self.assertEqual(s("D:/HAZOP/work/out.xlsx"), "out.xlsx")
        self.assertEqual(s("50%~100% a/b 구간"), "50%~100% a/b 구간", "경로가 아닌 글은 그대로")

    def test_B3_rows_of_a_project_with_the_same_folder_name_are_not_shown(self):
        actions_log.record("P A", answer_id="a-1", index=0, request_id="q-1", request_text="x", proposal={"action": "export.excel"},
                           klass="auto", result="ok", now=NOW)
        self.assertEqual(actions_log.day_path("P A", NOW), actions_log.day_path("P_A", NOW), "폴더가 같다(safe_name)")
        self.engine.settings["project_id"] = "P_A"
        self.assertEqual(api_actionlog.recent(self.engine, today=NOW)["rows"], [])
        self.assertEqual(len(actions_log.read_day("P A", NOW)[0]), 1)



class ChatConnTest(unittest.TestCase):
    """채팅 창 아래 줄: 분석 연결이 아니라 채팅이 실제로 쓰는 연결(구독)을 보인다(A8 검토 지적 2)."""

    def test_chat_line_shows_the_chat_connection_not_the_analysis_one(self):
        got = {"via": "subscription", "chip": "구독 · 빠름 · 연결됨", "tone": "ok", "can_start": True}
        self.assertIn("chatconn", api_actionlog.TOPICS)
        with mock.patch("hazop.shell.api_settings.chat_connection", lambda engine: dict(got)):
            out = json.loads(api_actionlog.read(object(), ["chatconn"], {}).body)
        self.assertEqual(out, got)
        self.assertIsNone(api_actionlog.read(object(), ["chatconn", "x"], {}))

    def test_a_broken_settings_module_does_not_break_the_chat_line(self):
        with mock.patch("hazop.shell.api_settings.chat_connection", mock.Mock(side_effect=RuntimeError("x"))):
            out = json.loads(api_actionlog.read(object(), ["chatconn"], {}).body)
        self.assertEqual((out["via"], out["can_start"]), ("subscription", False))
        self.assertNotIn("key", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
