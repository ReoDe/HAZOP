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
from hazop import paths  # noqa: E402
from hazop.graph import project  # noqa: E402
from hazop.kg import expect, screen  # noqa: E402
from hazop.shell import api, api_kg  # noqa: E402

PID = "P-KG"


def project_graph(pid=PID, mutate=None):
    g = copy.deepcopy(fx.graph())
    g["source"] = {"drawing_number": "T-001"}
    for n in g["nodes"]:
        n["local_id"] = "L-" + n["entity_id"]
    if mutate:
        mutate(g)
    return project.build(pid, [g])


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def files_under(root):
    return sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)


class Base(unittest.TestCase):
    FAKE_KG = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-shellkg-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from hazop.app import project_ctx
        self.pg = project_graph()
        self.pgs = {PID: self.pg}
        patches = [mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp}),
                   mock.patch.object(project_ctx, "project_graph", lambda pid: self.pgs[pid]),
                   mock.patch.dict(api.COMMANDS)]
        if self.FAKE_KG:
            patches.append(mock.patch.object(api_kg, "_load_kg", lambda pid: (fx.kg(), None)))
        for p in patches:
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
        """화면처럼: 상세를 읽고 그 항목의 지문·상태·판을 실어 보낸다."""
        d = api_kg.node(self.engine, nid) or {"ver": self.read()["ver"]}
        x = d.get("expectation") or {}
        return self.call("kg.judge", dict({"id": nid, "action": action, "ver": d["ver"], "digest": x.get("digest", "-"),
                                           "state": x.get("state", "expected")}, **kw))


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
        self.assertEqual(s["ver"], PID + "|none")

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
        x = self.detail(xid)["expectation"]
        r = self.call("kg.judge", {"id": xid, "action": "confirm", "ver": PID + "|0123456789abcdef", "digest": x["digest"], "state": x["state"]})
        self.assertEqual(r["error"]["code"], "stale")
        self.assertFalse(os.path.exists(expect.store_path(PID)))

    def test_reviewer_name_is_required_and_web_cannot_send_by(self):
        xid = self.exp_id("E01", "P-1")
        r = self.call("kg.judge", {"id": xid, "action": "confirm", "ver": PID + "|none", "by": "누군가"})
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
        x = self.detail(xid)["expectation"]
        out = api_kg.judge(self.engine, xid, "confirm", x["digest"], x["state"])
        self.assertEqual(out["state"], "confirmed_present")
        x = self.detail(xid)["expectation"]
        with self.assertRaises(api.CommandError):
            api_kg.judge(self.engine, xid, "confirm", x["digest"], x["state"])          # 확인됨에서는 되돌리기만 된다


class ReviewReproTest(Base):
    """검토 1회(2026-11-14) 재현: R3 보던 사이 도면이 바뀜, R2 프로젝트가 바뀜, 캐시, 차단 띠, 관계 상태, 한글 상세."""

    def swap_cv1(self, g):
        for n in g["nodes"]:
            if n["entity_id"] == "e-cv1":
                n["tag"], n["source_object_id"] = "CV-9", "o-cv9"

    def test_r3_candidate_changed_after_view_is_not_saved(self):
        xid = self.exp_id("E01", "P-1")
        seen = self.detail(xid)
        self.assertEqual([f["label"] for f in seen["expectation"]["found"]], ["CV-1"])
        self.pgs[PID] = project_graph(mutate=self.swap_cv1)         # 화면을 연 뒤 도면을 다시 추출함
        r = self.call("kg.judge", {"id": xid, "action": "confirm", "ver": seen["ver"], "digest": seen["expectation"]["digest"],
                                   "state": seen["expectation"]["state"]})
        self.assertEqual(r["error"]["code"], "stale", r)
        self.assertFalse(os.path.exists(expect.store_path(PID)))
        now = self.detail(xid)["expectation"]
        self.assertEqual([f["label"] for f in now["found"]], ["CV-9"])        # 다시 읽으면 바뀐 후보가 보이고, 그것으로 판단할 수 있다
        self.assertTrue(self.judge(xid, "confirm")["ok"])

    def test_r3_state_changed_elsewhere_is_not_saved(self):
        xid = self.exp_id("E01", "P-1")
        seen = self.detail(xid)
        api_kg.judge(self.engine, xid, "confirm", seen["expectation"]["digest"], "candidate_found")   # 다른 곳(채팅)에서 먼저 판단
        r = self.call("kg.judge", {"id": xid, "action": "reject", "ver": api_kg.node(self.engine, xid)["ver"],
                                   "digest": seen["expectation"]["digest"], "state": "candidate_found"})
        self.assertEqual(r["error"]["code"], "stale")

    def test_r2_web_project_differs_from_engine_project(self):
        other = "P-OTHER"
        self.pgs[other] = project_graph(other)
        xid = self.exp_id("E01", "P-2")
        seen = self.detail(xid)
        self.engine.settings["project_id"] = other
        r = self.engine.dispatch("kg.judge", {"id": xid, "action": "not_applicable", "reason": "x", "ver": seen["ver"],
                                              "digest": seen["expectation"]["digest"], "state": "expected"}, project=PID, via_web=True)
        self.assertEqual(r["error"]["code"], "wrong_project", r)
        with self.assertRaises(api.CommandError) as cm:            # 명령 길을 거치지 않는 호출도 ver의 프로젝트로 막힌다
            api_kg.judge(self.engine, xid, "not_applicable", seen["expectation"]["digest"], "expected", reason="x", ver=seen["ver"])
        self.assertEqual(cm.exception.code, "stale")
        self.assertFalse(os.path.exists(expect.store_path(other)))
        self.assertNotEqual(seen["ver"], other + "|none")

    def test_cache_follows_file_content_not_object_identity(self):
        xid = self.exp_id("E01", "P-2")
        self.read()
        it = fx.item(expect.evaluate(self.pg, fx.kg(), {}), "E01", "P-2")
        expect.save_judgement(expect.store_path(PID), PID, expect.apply_action(it, "not_applicable", "OLD", "r", at="t"))
        self.assertEqual(self.detail(xid)["expectation"]["state"], "not_applicable")   # 캐시를 지우지 않아도 바뀐 판단이 보인다

    def test_block_band_for_blocked_kg_and_changed_drawings(self):
        bad = fx.kg()
        bad["validation"] = {"status": "blocked", "blockers": [{"reason": "x"}]}
        bad["graph_refs"] = [{"graph_id": "graph-T-001", "graph_version": "v-old"}]
        with mock.patch.object(api_kg, "_load_kg", lambda pid: (bad, None)):
            api_kg._CACHE.clear()
            kinds = [b["kind"] for b in self.read()["blocks"]]
        self.assertEqual(kinds, ["kg_blocked", "graph_mismatch"])

    def test_link_states_and_korean_detail(self):
        self.assertEqual(screen.kg_link_state({"recheck": True, "link_status": "confirmed"}), "recheck")
        self.assertEqual(screen.kg_link_state({"link_status": "candidate"}), "candidate")
        self.assertEqual(screen.kg_link_state({"link_status": "confirmed", "knowledge_status": "hypothesis"}), "excluded")
        self.assertEqual(screen.kg_link_state({"link_status": "confirmed", "knowledge_status": "confirmed"}), "confirmed")
        d = self.detail("kn:setpt-1")
        self.assertIn(["종류", "설정치"], d["what"])
        self.assertIn(["상태", "확인"], d["what"])
        self.assertIn(["항목", "고압 트립"], d["what"])
        nb = self.detail("graph-T-001/e-psh1")["neighbors"]
        self.assertTrue(any(n["st"] == "확정" for n in nb if n["kind"] == "has_setpoint"), nb)


class RealKgTest(Base):
    """가짜 _load_kg 없이 저장된 지식그래프를 읽는 길: 도면 그래프와 문서 지식으로 auto.build_project를 돌려 디스크에 만든다."""
    FAKE_KG = False

    def test_panel_reads_the_built_knowledge_graph(self):
        import glob
        from hazop.kg import auto, docextract
        g = copy.deepcopy(fx.graph())
        g["source"] = {"drawing_number": "T-001"}
        g["project_id"] = PID
        gdir = os.path.join(paths.output_root("graph"), "T-001")
        os.makedirs(gdir)
        with open(os.path.join(gdir, "graph.json"), "w", encoding="utf-8") as fh:
            json.dump(g, fh, ensure_ascii=False)
        pdf = glob.glob(os.path.join(REPO, "tests", "fixtures", "docextract", "*.pdf"))[0]
        doc = docextract.extract_pdf(pdf, "mat-1", 1, "document-001", title="가상 설계 문서")
        doc["project_id"] = PID
        ddir = os.path.join(paths.output_root("document-knowledge"), "doc-1")
        os.makedirs(ddir)
        with open(os.path.join(ddir, auto.DOC_FILE), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        auto.build_project(PID, paths.output_root("graph"), paths.output_root("document-knowledge"), paths.folder("knowledge-graph"),
                           paths.output_root("knowledge-graph"))
        kg, note = api_kg._load_kg(PID)
        self.assertIsNotNone(kg, note)
        s = self.read()
        self.assertTrue(s["has_kg"])
        self.assertGreaterEqual(s["layers"]["kn"], 16)
        hit = next(h for h in self.read("search", q="고압 트립")["hits"] if h["layer"] == "kn")
        d = self.detail(hit["id"])
        self.assertTrue(any(k == "쪽" for k, _ in d["evidence"]), d["evidence"])
        self.assertIn(["상태", "미확인(사람 확인 전)"], d["what"])


if __name__ == "__main__":
    unittest.main()
