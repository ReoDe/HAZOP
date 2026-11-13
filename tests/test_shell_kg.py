"""새 웹 화면 지식그래프 패널의 엔진 쪽(hazop/shell/api_kg.py, hazop/kg/screen.py 패널 부분). 실행: python -m unittest tests.test_shell_kg

시험용 가상 도면(tests.test_kg_expect.graph, 실제 설계자료 아님)으로 프로젝트 그래프를 짓고, 판단 파일은 임시 작업 루트에만 쓴다.
잠재 후보의 상태·재확인은 hazop.kg.expect가 정한 값을 그대로 보이는지, 판단·되돌리기·규칙 판 변경·낡은 판 거절·상한을 본다.
"""

import copy
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
sys.path.insert(0, os.path.join(REPO, "tests"))

import test_kg_expect as fx  # noqa: E402
from hazop.graph import project  # noqa: E402
from hazop.kg import expect, screen  # noqa: E402
from hazop.shell import api, api_kg  # noqa: E402

PID = "P-KG"


def project_graph():
    g = copy.deepcopy(fx.graph())
    g["source"] = {"drawing_number": "T-001"}
    for n in g["nodes"]:
        n["local_id"] = "L-" + n["entity_id"]
    return project.build(PID, [g])


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def files_under(root):
    return sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-shellkg-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from hazop.app import project_ctx
        self.pg = project_graph()
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp}),
                  mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.object(api_kg, "_load_kg", lambda pid: (fx.kg(), None)),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        if "kg.judge" not in api.COMMANDS:     # 등록 줄(api.py)이 들어오기 전에도 같은 표로 시험한다
            api_kg.register(api.COMMANDS)
        expect._EVALUATED[:] = []
        api_kg._CACHE.clear()
        self.events = []
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events.append)
        self.engine.settings.update(project_id=PID, reviewer_name="검토자A")

    def read(self, *parts, **query):
        r = api_kg.read(self.engine, ["kg"] + list(parts), query)
        self.assertIsNotNone(r, parts)
        return json.loads(r.body.decode("utf-8"))

    def call(self, name, args=None):
        return self.engine.dispatch(name, args or {}, project=PID, via_web=True)

    def exp_id(self, rule, tag):
        return next(i["id"] for i in self.read("search", q=rule)["hits"]
                    if i["layer"] == "exp" and self.read("node", id=i["id"])["expectation"]["target"]["label"] == tag)

    def detail(self, nid):
        return self.read("node", id=nid)

    def judge(self, nid, action, **kw):
        return self.call("kg.judge", dict({"id": nid, "action": action, "ver": self.read()["ver"]}, **kw))


class ReadTest(Base):
    def test_summary_counts_layers_and_expectation_states_from_engine(self):
        s = self.read()
        self.assertTrue(s["available"], s)
        self.assertEqual(s["mode"], "full")                    # 작은 프로젝트는 처음부터 다 펼친다
        self.assertEqual(s["expand"], ["graph-T-001"])
        ev = expect.evaluate(self.pg, fx.kg())
        by_state = {x["state"]: x["count"] for x in s["expect"]["states"]}
        for st in expect.STATES:
            self.assertEqual(by_state[st], sum(1 for i in ev["items"] if i["state"] == st), st)
        self.assertEqual(s["layers"]["exp"], len(ev["items"]))
        self.assertEqual(s["layers"]["kn"], 1)
        self.assertEqual(s["ver"], "none")

    def test_pipe_segments_fold_into_links_and_graph_has_no_dangling_ends(self):
        g = self.read("graph", expand="all")
        ids = {n["id"] for n in g["nodes"]}
        self.assertFalse(any(n["type"] == "pipe_segment" for n in g["nodes"]))   # 끝이 둘인 구간은 모두 접힘
        self.assertTrue(all(l["s"] in ids and l["t"] in ids for l in g["links"]))
        pipe = {(l["s"], l["t"]): l for l in g["links"] if l["kind"] == "pipe"}
        self.assertTrue(pipe[("graph-T-001/e-p1", "graph-T-001/e-cv1")]["flow"])     # 흐름을 아는 구간은 흐름 쪽으로
        self.assertFalse(pipe[("graph-T-001/e-cv1", "graph-T-001/e-tk1")]["flow"])

    def test_overview_when_over_cap_and_expanding_past_cap_is_refused(self):
        with mock.patch.object(screen, "PANEL_NODE_CAP", 5):
            api_kg._CACHE.clear()
            s = self.read()
            self.assertEqual((s["mode"], s["expand"]), ("overview", []))
            g = self.read("graph", expand="")
            self.assertEqual([n["id"] for n in g["nodes"]], ["grp:graph-T-001"])
            self.assertEqual(g["nodes"][0]["count"], s["total"])
            r = self.read("graph", expand="graph-T-001")
        self.assertIn("상한", r["refused"])
        self.assertEqual((r["count"], r["cap"]), (s["total"], 5))

    def test_search_puts_exact_tag_first_and_detail_has_evidence_and_sheet_spot(self):
        hits = self.read("search", q="p-1")["hits"]
        self.assertEqual(hits[0]["label"], "P-1")
        d = self.detail(hits[0]["id"])
        self.assertEqual(d["at"], {"sheet": "graph-T-001", "local_id": "L-e-p1"})   # 도면에서 보기는 이 자리로 간다
        self.assertIn(["도면", "T-001"], d["evidence"])
        self.assertIn(["원본 객체", "o-p1"], d["evidence"])
        self.assertTrue(any(x["label"].startswith("펌프 출구") for x in d["expectations"]))
        self.assertIsNone(api_kg.read(self.engine, ["kg", "node"], {"id": "없음"}))

    def test_reading_writes_no_file(self):
        before = files_under(self.tmp)
        self.read(); self.read("graph", expand="all"); self.read("search", q="P"); self.detail("graph-T-001/e-p1")
        self.assertEqual(files_under(self.tmp), before)

    def test_vendor_script_comes_from_bundled_force_graph(self):
        r = api_kg.read(self.engine, ["kg", "force-graph.js"], {})
        self.assertEqual(r.mime, "text/javascript")
        with open(screen.VENDOR_JS, "rb") as fh:
            self.assertEqual(r.body, fh.read())

    def test_no_project_graph_is_reported_not_raised(self):
        from hazop.app import project_ctx
        with mock.patch.object(project_ctx, "project_graph", side_effect=ValueError("x")):
            s = self.read()
        self.assertFalse(s["available"])
        self.assertIn("도면", s["reason"])


class JudgeTest(Base):
    def test_confirm_then_undo_returns_to_engine_state(self):
        xid = self.exp_id("E01", "P-1")
        self.assertEqual(self.detail(xid)["expectation"]["state"], "candidate_found")
        r = self.judge(xid, "confirm")
        self.assertTrue(r["ok"], r)
        d = self.detail(xid)["expectation"]
        self.assertEqual((d["state"], d["judgement"]["by"]), ("confirmed_present", "검토자A"))
        self.assertEqual([a["action"] for a in d["actions"]], ["undo"])
        self.assertTrue(r["data"]["ver"] != "none")
        r = self.judge(xid, "undo")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.detail(xid)["expectation"]["state"], "candidate_found")   # 되돌리면 자동 판정으로
        self.assertIn(("changed", "kg"), [(e.get("t"), e.get("topic")) for e in self.events])

    def test_absent_needs_reason_and_evidence_and_saves_nothing_without_them(self):
        xid = self.exp_id("E01", "P-2")
        d = self.detail(xid)["expectation"]
        self.assertEqual(d["state"], "expected")
        needs = {a["action"]: [k for k, _ in a["needs"]] for a in d["actions"]}
        self.assertEqual(needs, {"absent": ["reason", "evidence"], "not_applicable": ["reason"]})
        r = self.judge(xid, "absent", reason="체크밸브 없음")
        self.assertEqual(r["error"]["code"], "failed")
        self.assertFalse(os.path.exists(expect.store_path(PID)))
        r = self.judge(xid, "absent", reason="체크밸브 없음", evidence="계통설계기술서 3.2절")
        self.assertTrue(r["ok"], r)
        d = self.detail(xid)["expectation"]
        self.assertEqual((d["state"], d["judgement"]["evidence"]), ("confirmed_absent", "계통설계기술서 3.2절"))

    def test_not_allowed_transition_is_refused(self):
        xid = self.exp_id("E01", "P-1")      # 후보 발견에서는 무관을 고를 수 없다(전이 표)
        r = self.judge(xid, "not_applicable", reason="x")
        self.assertEqual(r["error"]["code"], "failed")
        self.assertFalse(os.path.exists(expect.store_path(PID)))

    def test_rule_version_change_sends_not_applicable_back_to_recheck(self):
        xid = self.exp_id("E01", "P-2")
        self.assertTrue(self.judge(xid, "not_applicable", reason="예비 펌프라 대상 아님")["ok"])
        self.assertEqual(self.detail(xid)["expectation"]["state"], "not_applicable")
        data = copy.deepcopy(expect.RULES.data)
        next(r for r in data["rules"] if r["id"] == "E01")["version"] += 1
        saved = read_bytes(expect.store_path(PID))
        with mock.patch.object(expect, "RULES", expect.Rules(data)):
            expect._EVALUATED[:] = []
            api_kg._CACHE.clear()
            d = self.detail(xid)["expectation"]
            self.assertEqual((d["state"], d["recheck"], d["previous_label"]), ("expected", True, "무관"))
            self.assertEqual({a["action"] for a in d["actions"]}, {"absent", "not_applicable"})
            self.assertEqual(self.read()["expect"]["recheck"], 1)
        self.assertEqual(read_bytes(expect.store_path(PID)), saved)   # 판단 기록은 지우지 않는다

    def test_stale_version_saves_nothing(self):
        xid = self.exp_id("E01", "P-1")
        r = self.call("kg.judge", {"id": xid, "action": "confirm", "ver": "0123456789abcdef"})
        self.assertEqual(r["error"]["code"], "stale")
        self.assertFalse(os.path.exists(expect.store_path(PID)))

    def test_reviewer_name_is_required_and_web_cannot_send_by(self):
        xid = self.exp_id("E01", "P-1")
        r = self.call("kg.judge", {"id": xid, "action": "confirm", "ver": "none", "by": "누군가"})
        self.assertEqual(r["error"]["code"], "bad_args")
        self.engine.settings["reviewer_name"] = ""
        r = self.judge(xid, "confirm")
        self.assertEqual(r["error"]["code"], "bad_args")
        self.assertFalse(os.path.exists(expect.store_path(PID)))

    def test_unknown_expectation_and_action(self):
        self.assertEqual(self.judge("exp-E99-0", "confirm")["error"]["code"], "not_found")
        self.assertEqual(self.judge(self.exp_id("E01", "P-1"), "delete")["error"]["code"], "bad_args")


class ChatFunctionTest(Base):
    def test_open_find_and_judge_run_without_web(self):
        api_kg.open_panel(self.engine, "graph-T-001/e-p1")
        self.assertIn({"t": "event", "name": "kg.open", "data": {"focus": "graph-T-001/e-p1"}}, self.events)
        hits = api_kg.find_nodes(self.engine, "CV-1")
        self.assertEqual(hits[0]["id"], "graph-T-001/e-cv1")
        xid = self.exp_id("E01", "P-1")
        out = api_kg.judge(self.engine, xid, "confirm")
        self.assertEqual(out["state"], "confirmed_present")
        with self.assertRaises(api.CommandError):
            api_kg.judge(self.engine, xid, "confirm")          # 확인됨에서는 되돌리기만 된다


if __name__ == "__main__":
    unittest.main()
