"""새 웹 화면의 AI 검토 후보 영역(hazop/shell/api_aireview.py). 실행: python -m unittest tests.test_shell_aireview

가상 도면 SNP-M-101의 실제 추출·그래프를 임시 작업 루트에 두고 실제 엔진(ai_review·corrections·build_graph)을 부른다. AI는 부르지 않는다(가짜 클라이언트).
본다: 수락 → 수정 기록과 그래프에 바로 반영, 거절, 되돌리기, 확신 높은 묶음 수락, AI 수락과 사람 수정이 한 수정 기록에 함께 있는 경우,
낡은 판 거절, 호출 상한에서 멈춤, 도면별 예상 호출 수, 웹으로 경로가 나가지 않음.
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

from hazop import paths  # noqa: E402
from hazop.extract import ai_review as ar  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from hazop.shell import api, api_aireview as AR  # noqa: E402
from tests.test_ai_review import StubClient  # noqa: E402
from tests.test_shell_drawings import Events, template  # noqa: E402,F401  (template은 tearDownModule이 지운다)
from tests import test_shell_drawings as _tsd  # noqa: E402


def tearDownModule():
    _tsd.tearDownModule()
    _tsd._TPL.clear()      # 같은 실행에서 뒤에 도는 test_shell_drawings가 지운 틀을 다시 만들게


class FakeAi:
    def __init__(self, client):
        self.client = client

    def status(self):
        return {"can_start": True, "state": "ready"}

    def make_client(self):
        return self.client


def kind_answers(request):
    """항목마다 첫 필드에 답한다(종류는 manual_valve, 그 밖은 버려져도 된다). 호출 수만 세는 시험에 쓴다."""
    out = []
    for it in json.loads(request["context"])["items"]:
        out.append({"item_id": it["item_id"], "field": it["ask"][0], "values": ["manual_valve"], "confidence": 0.9, "reason": "시험"})
    return {"answers": out}


class Base(unittest.TestCase):
    def setUp(self):
        tpl = template()
        self.tmp = tempfile.mkdtemp(prefix="hazop-shellai-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(os.path.join(tpl["root"], "work"), os.path.join(self.tmp, "work"))
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"),
                                               "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")}),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        if "aireview.accept" not in api.COMMANDS:          # 등록 줄(api.MODULES)은 s-frame이 넣는다. 그 전에는 시험이 직접 올린다
            AR.register(api.COMMANDS)
        self.name = tpl["name"]
        self.events = Events()
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events,
                                 run_jobs=lambda job_id, fn: fn())
        self.engine.settings["reviewer_name"] = "검토자A"
        self.gid = {v: k for k, v in self.engine.graph_names().items()}[self.name]
        from hazop.app import data
        self.ex = data.read_json(data.extraction_path(self.name))
        self.valves = [n for n in self.ex["nodes"] if n.get("kind") and n.get("kind") != "tee"]

    # -------------------------------------------------------- 도우미
    def seed(self, cands):
        doc = ar.new_doc(self.name, self.ex)
        ar.merge_run(doc, {"candidates": cands, "stats": {"calls": 1, "left": 0}})
        ar.save_doc(doc)

    def tag(self, i, n, value, conf=0.95):
        return ar.make_candidate("t-%d" % i, "tag", n, "tag", [value], conf, "주변 글자 %s" % value)

    def view(self):
        r = AR.read(self.engine, ["aireview", self.gid], {})
        self.assertIsNotNone(r)
        return json.loads(r.body.decode("utf-8"))

    def call(self, name, **args):
        return self.engine.dispatch(name, args)

    def graph_text(self):
        with open(os.path.join(paths.output_root("graph"), self.name, "graph.json"), encoding="utf-8") as fh:
            return fh.read()

    def ops(self):
        return (corrections.load(self.name) or {}).get("ops") or []

    def changed(self, topic):
        return self.events.changes(topic)


class DecideTest(Base):
    def test_accept_reaches_graph_at_once(self):
        self.seed([self.tag(1, self.valves[0], "V901")])
        self.assertNotIn("V901", self.graph_text())
        v = self.view()
        out = self.call("aireview.accept", graph_id=self.gid, cand_ids=["t-1:tag"], ver=v["ver"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["changed"], ["t-1:tag"])
        self.assertEqual([(o["op"], o["origin"], o["accepted_by"]) for o in self.ops()], [("set_tag", "ai", "검토자A")])
        self.assertIn("V901", self.graph_text())                               # 다시 열지 않아도 그래프에 들어감
        self.assertTrue(self.changed("sheet") and self.changed("aireview") and self.changed("drawings"))
        row = self.view()["groups"][0]["items"][0]
        self.assertEqual((row["status"], row["current"], row["decided_by"]), ("accepted", "V901", "검토자A"))

    def test_reject_writes_no_correction_and_keeps_graph(self):
        self.seed([self.tag(1, self.valves[0], "V901")])
        before = os.stat(os.path.join(paths.output_root("graph"), self.name, "graph.json")).st_mtime_ns
        out = self.call("aireview.reject", graph_id=self.gid, cand_ids=["t-1:tag"], ver=self.view()["ver"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.ops(), [])
        self.assertEqual(self.view()["counts"]["rejected"], 1)
        self.assertEqual(os.stat(os.path.join(paths.output_root("graph"), self.name, "graph.json")).st_mtime_ns, before)
        self.assertFalse(self.changed("sheet"))

    def test_revert_takes_op_out_and_rebuilds(self):
        self.seed([self.tag(1, self.valves[0], "V901")])
        self.call("aireview.accept", graph_id=self.gid, cand_ids=["t-1:tag"], ver=self.view()["ver"])
        out = self.call("aireview.revert", graph_id=self.gid, cand_ids=["t-1:tag"], ver=self.view()["ver"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.ops(), [])
        self.assertNotIn("V901", self.graph_text())
        self.assertEqual(self.view()["groups"][0]["items"][0]["status"], "proposed")

    def test_stale_ver_is_refused_and_writes_nothing(self):
        self.seed([self.tag(1, self.valves[0], "V901")])
        v = self.view()["ver"]
        from hazop.app import data
        data.save_corrections(self.name, [corrections.make_op(self.ex, "set_tag", self.valves[1]["source_object_id"], {"tag": "V777"},
                                                              "다른 창", name=self.name)], "다른 창")
        out = self.call("aireview.accept", graph_id=self.gid, cand_ids=["t-1:tag"], ver=v)
        self.assertEqual(out["error"]["code"], "stale", out)
        self.assertEqual([o.get("origin") for o in self.ops()], [None])     # 다른 창의 사람 수정만
        self.assertEqual(self.view()["counts"]["proposed"], 1)

    def test_reviewer_name_is_required(self):
        self.seed([self.tag(1, self.valves[0], "V901")])
        self.engine.settings["reviewer_name"] = ""
        out = self.call("aireview.accept", graph_id=self.gid, cand_ids=["t-1:tag"], ver=self.view()["ver"])
        self.assertEqual(out["error"]["code"], "bad_args")
        self.assertEqual(self.ops(), [])


class BulkTest(Base):
    def test_bulk_accept_takes_only_safe_candidates(self):
        a, b, c = self.valves[:3]
        kind_low = ar.make_candidate("k-x", "kind", c, "kind", ["gate_valve" if "gate_valve" in ar.rules.KIND_CATEGORY else "manual_valve"],
                                     0.9, "모양")
        self.seed([self.tag(1, a, "V901"), self.tag(2, b, "V902", conf=0.5), kind_low])
        v = self.view()
        self.assertEqual({x["task"]: x["count"] for x in v["bulk"]}, {"tag": 1})          # 확신 0.5와 종류 0.9는 묶음에 없다
        kinds = next(g for g in v["groups"] if g["task"] == "kind")["items"]
        self.assertIn("0.95", kinds[0]["bulk_block"])
        out = self.call("aireview.accept_bulk", graph_id=self.gid, task="tag", ver=v["ver"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["changed"], ["t-1:tag"])
        self.assertEqual(self.view()["counts"], {"proposed": 2, "accepted": 1, "rejected": 0})
        self.assertIn("V901", self.graph_text())
        out = self.call("aireview.accept_bulk", graph_id=self.gid, task="tag", ver=self.view()["ver"])
        self.assertEqual(out["error"]["code"], "not_found")                                 # 남은 묶음 없음

    def test_human_and_ai_ops_share_one_record(self):
        a, b = self.valves[:2]
        from hazop.app import data
        data.save_corrections(self.name, [corrections.make_op(self.ex, "set_tag", a["source_object_id"], {"tag": "V500"}, "사람",
                                                              name=self.name)], "사람")
        self.seed([self.tag(1, a, "V901"), self.tag(2, b, "V902")])
        out = self.call("aireview.accept", graph_id=self.gid, cand_ids=["t-1:tag", "t-2:tag"], ver=self.view()["ver"])
        self.assertTrue(out["ok"], out)
        self.assertEqual([f["cand_id"] for f in out["data"]["failed"]], ["t-1:tag"])       # 사람이 고친 자리는 덮지 않음
        self.assertEqual([(o["op"], o.get("origin")) for o in self.ops()], [("set_tag", None), ("set_tag", "ai")])
        text = self.graph_text()
        self.assertIn("V500", text)
        self.assertIn("V902", text)
        self.assertNotIn("V901", text)
        out = self.call("aireview.revert", graph_id=self.gid, cand_ids=["t-2:tag"], ver=self.view()["ver"])
        self.assertTrue(out["ok"], out)
        self.assertEqual([o.get("origin") for o in self.ops()], [None])                     # 사람 수정은 남는다
        self.assertIn("V500", self.graph_text())
        self.assertNotIn("V902", self.graph_text())


class RunTest(Base):
    def test_estimate_per_drawing(self):
        r = json.loads(AR.read(self.engine, ["aireview", "estimate"], {"cap": "1"}).body.decode("utf-8"))
        page = next(p for p in r["pages"] if p["graph_id"] == self.gid)
        self.assertEqual(page["calls"], min(1, page["needed"]))
        self.assertEqual(r["calls"], sum(p["calls"] for p in r["pages"]))
        self.assertEqual(r["seconds"], r["calls"] * ar.SECONDS_PER_CALL)

    def test_run_stops_at_cap(self):
        client = StubClient(kind_answers)
        self.engine.ai = FakeAi(client)
        items = len(ar.collect_items(self.ex))
        with mock.patch.object(ar, "plan", lambda its, cap=ar.DEFAULT_CAP, batch=ar.DEFAULT_BATCH, _p=ar.plan: _p(its, cap, 2)):
            out = self.call("aireview.run", graph_ids=[self.gid], cap=2)
        self.assertTrue(out["ok"], out)
        done = next(e for e in self.events.items if e.get("name") == "job.done")["data"]["result"]
        self.assertEqual(len(client.requests), 2)                                           # 상한 2회에서 멈춤
        self.assertEqual(done["calls"], 2)
        self.assertEqual(done["drawings"][0]["left"], items - 4)
        self.assertTrue(self.view()["available"])
        self.assertTrue(self.changed("aireview"))

    def test_run_needs_connection(self):
        out = self.call("aireview.run", graph_ids=[self.gid])
        self.assertEqual(out["error"]["code"], "failed")


class ReadTest(Base):
    def test_no_candidates_yet(self):
        v = self.view()
        self.assertFalse(v["available"])
        self.assertIsNone(AR.read(self.engine, ["aireview", "no-such"], {}))

    def test_groups_by_task_and_no_paths(self):
        kind = ar.make_candidate("k-x", "kind", self.valves[2], "kind", ["manual_valve"], 0.99, "모양")
        self.seed([self.tag(1, self.valves[0], "V901"), kind])
        v = self.view()
        self.assertEqual([g["task"] for g in v["groups"]], ["kind", "tag"])
        self.assertEqual(v["groups"][0]["label"], "못 읽은 기호의 종류")
        body = json.dumps([v, AR.overview(self.engine)], ensure_ascii=False)
        self.assertNotIn(self.tmp.replace("\\", "\\\\"), body)
        self.assertNotIn(":\\\\", body)

    def test_chat_functions_do_not_raise(self):
        self.assertEqual(AR.accept(self.engine, "no-such", ["x"])["code"], "not_found")
        self.seed([self.tag(1, self.valves[0], "V901")])
        self.assertEqual(AR.reject(self.engine, self.gid, ["nope"])["code"], "not_found")
        self.assertTrue(AR.candidates(self.engine, self.gid)["ok"])
        self.assertTrue(AR.accept_bulk(self.engine, self.gid, "tag", by="채팅 검토자")["ok"])
        self.assertEqual(self.ops()[0]["accepted_by"], "채팅 검토자")


if __name__ == "__main__":
    unittest.main()
