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


def build_real_kg(case):
    """도면 그래프와 가상 문서 지식으로 auto.build_project를 돌려 임시 작업 루트에 프로젝트 지식그래프를 만든다. -> 저장된 지식그래프."""
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
    case.assertIsNotNone(kg, note)
    return kg


def save_study(case, groups, entries):
    """확정 구간과 분석 결과를 임시 작업 루트에 저장한다(앱이 쓰는 hazop.study 저장 함수 그대로). -> (구간 집합, 결과)."""
    from hazop import store_io
    from hazop.study import nodes as sn
    from hazop.study import results as res
    from tests.test_study_storage import DEVS, build, put_entries
    p = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
    p.start()
    case.addCleanup(p.stop)
    ns = build(case.pg, groups)
    sn.save(ns)
    doc = res.empty_results(ns, DEVS)
    for node_id, item, es in entries:
        put_entries(doc, node_id, item, es)
    res.save_fp(doc, ns["project_id"], expect=store_io.ANY)
    return ns, doc


def sref(pg, tag):
    from hazop.study import migrate
    n = next(n for n in pg["nodes"] if n.get("tag") == tag)
    return migrate.ref_of(n, n["sheet"])


def nid_of(pg, tag):
    return next(n["entity_id"] for n in pg["nodes"] if n.get("tag") == tag)


class RealKgTest(Base):
    """가짜 _load_kg 없이 저장된 지식그래프를 읽는 길: 도면 그래프와 문서 지식으로 auto.build_project를 돌려 디스크에 만든다."""
    FAKE_KG = False

    def test_panel_reads_the_built_knowledge_graph(self):
        build_real_kg(self)
        s = self.read()
        self.assertTrue(s["has_kg"])
        self.assertGreaterEqual(s["layers"]["kn"], 16)
        hit = next(h for h in self.read("search", q="고압 트립")["hits"] if h["layer"] == "kn")
        d = self.detail(hit["id"])
        self.assertTrue(any(k == "쪽" for k, _ in d["evidence"]), d["evidence"])
        self.assertIn(["상태", "미확인(사람 확인 전)"], d["what"])


class ExploreTest(Base):
    """완료 목록 3 B6 '살펴보기': 도달 범위(A1)·고아·근거 공백(A2)을 엔진(hazop.kg.algo)에 그대로 맡긴다. 저장된 실제 지식그래프로 본다."""
    FAKE_KG = False

    def setUp(self):
        super().setUp()
        built = build_real_kg(self)
        # 가상 문서의 지식은 모두 '사람 확인 전'이라 계산 뷰(V4)에 들지 않는다. 사람이 확인한 상태를 흉내 내려고 조각 하나·설정치 하나를
        # 확인으로 두고, 그 조각이 P-1을 언급한다고 확정한다(P-1은 설정치·요건이 없으니 근거 공백, 설정치는 어디에도 적용되지 않으니 고아).
        self.kg = copy.deepcopy(built)
        chunk = next(n for n in self.kg["nodes"] if n["node_type"] == "doc_chunk")
        setp = next(n for n in self.kg["nodes"] if n["node_type"] == "setpoint")
        for n in (chunk, setp):
            n["knowledge_status"] = "confirmed"
            n["compute_view"] = {"v4": True, "excluded_reasons": []}
        self.kg["links"].append({"id": "krel-test-mention", "kind": "mentions", "link_status": "confirmed", "method": "exact_norm",
                                 "reviewed_by": "검토자A", "compute_view": {"v4": True, "excluded_reasons": []},
                                 "ends": {"from": {"layer": "knowledge", "ref": chunk["id"]},
                                          "to": {"layer": "pid", "graph_id": "graph-T-001", "entity_id": "e-p1", "source_object_id": "o-p1"}}})
        self.chunk, self.setp = chunk["id"], setp["id"]
        p = mock.patch.object(api_kg, "_load_kg", lambda pid: (self.kg, None))
        p.start()
        self.addCleanup(p.stop)
        # 가상 도면의 배관 끝(has_endpoint)에 실제 추출처럼 end(source/target)를 단다. A1 흐름 판정이 이 값을 읽는다
        seen = set()
        for e in self.pg["edges"]:
            if e["kind"] == "has_endpoint":
                e["end"] = "target" if e["segment"] in seen else "source"
                seen.add(e["segment"])
        by = {n["entity_id"]: n for n in self.pg["nodes"]}
        for e in self.pg["edges"]:
            fd = (by.get(e.get("segment")) or {}).get("flow_direction")
            if e["kind"] == "has_endpoint" and isinstance(fd, dict):
                if e["node"] == fd.get("from"):
                    fd["from_end"] = e["end"]
                if e["node"] == fd.get("to"):
                    fd["to_end"] = e["end"]

    def engine_a2(self):
        from hazop.kg import algo
        return algo.a2_orphans_gaps(project.kg_view(self.kg, self.pg), self.pg)

    def test_gaps_are_the_engines_evidence_gaps(self):
        r = self.read("explore", what="gaps")
        self.assertTrue(r["active"], r)
        want = {g["entity_id"] for g in self.engine_a2()["evidence_gaps"]}
        self.assertEqual(want, {nid_of(self.pg, "P-1")})
        self.assertEqual(set(r["ids"]), want)
        self.assertEqual(r["count"], len(want))
        model = api_kg._context(self.engine)[0]["model"]
        self.assertTrue(set(r["ids"]) <= set(model["nodes"]), "강조할 ID는 패널 그림의 노드 ID여야 함")
        self.assertTrue(r["note"])

    def test_orphans_are_the_engines_orphans_on_knowledge_nodes(self):
        r = self.read("explore", what="orphans")
        self.assertTrue(r["active"], r)
        want = {screen.KN_PREFIX + o["id"] for o in self.engine_a2()["orphans"]}
        self.assertIn(screen.KN_PREFIX + self.setp, want)
        self.assertNotIn(screen.KN_PREFIX + self.chunk, want)
        self.assertEqual(set(r["ids"]), want)
        self.assertEqual(r["count"], len(want))

    def test_reach_runs_the_engine_from_a_component_in_one_study_node(self):
        from hazop.kg import algo
        save_study(self, [("A", ["o-p1", "o-cv1", "o-tk1", "o-psv1", "o-lt1"])], [])
        start = nid_of(self.pg, "P-1")
        r = self.read("explore", what="reach", start=start)
        self.assertTrue(r["active"], r)
        ns = __import__("hazop.study.nodes", fromlist=["x"]).load(self.pg)
        region = screen.reach_region(self.pg, ns, start)
        a1 = algo.a1_propagation(self.pg, [("S", region, None)], start)
        self.assertTrue(a1["active"], a1)
        model = api_kg._context(self.engine)[0]["model"]
        want = {x["entity_id"] for x in a1["exploration"]["reached"]} & set(model["nodes"])
        self.assertTrue(want)
        self.assertEqual(set(r["ids"]), want | {start})
        self.assertEqual(r["start"], start)
        self.assertIn(nid_of(self.pg, "CV-1"), r["ids"])

    def test_reach_count_is_the_engines_count_and_says_what_is_not_drawn(self):
        """검토 B6-R1: 건수를 그림에 있는 노드로 다시 세면 접힌 배관 구간만큼 줄었다. 건수는 엔진 값 그대로, 차이는 글로."""
        from hazop.kg import algo
        save_study(self, [("A", ["o-p1", "o-cv1", "o-tk1", "o-psv1", "o-lt1"])], [])
        start = nid_of(self.pg, "P-1")
        r = self.read("explore", what="reach", start=start)
        ns = __import__("hazop.study.nodes", fromlist=["x"]).load(self.pg)
        a1 = algo.a1_propagation(self.pg, [("S", screen.reach_region(self.pg, ns, start), None)], start)
        reached = [x["entity_id"] for x in a1["exploration"]["reached"]]
        by = {n["entity_id"]: n for n in self.pg["nodes"]}
        segs = sum(1 for i in reached if by[i].get("node_type") == "pipe_segment")
        self.assertGreater(segs, 0, "시험 자료에 접힌 배관 구간이 닿아야 차이를 본다")
        self.assertEqual(r["count"], len(reached))
        self.assertEqual(r["drawn"], len(reached) - segs)
        self.assertEqual(r["hidden"]["pipe_segments"], segs)
        self.assertIn("배관 구간 %d개는 접혀 있음" % segs, r["drawn_note"])
        self.assertIn(start, r["ids"], "시작점은 강조하되 세지 않는다")

    def test_reach_says_why_it_cannot_run(self):
        save_study(self, [("A", ["o-p1", "o-cv1"])], [])
        outside = self.read("explore", what="reach", start=nid_of(self.pg, "TK-1"))
        self.assertFalse(outside["active"])
        self.assertIn("구간", outside["reason"])
        none = self.read("explore", what="reach")
        self.assertFalse(none["active"])
        self.assertIn("고르", none["reason"])
        kn = next(i for i in api_kg._context(self.engine)[0]["model"]["nodes"] if i.startswith(screen.KN_PREFIX))
        self.assertFalse(self.read("explore", what="reach", start=kn)["active"])

    def test_blocked_knowledge_graph_runs_nothing(self):
        bad = copy.deepcopy(self.kg)
        bad["validation"]["status"] = "blocked"
        with mock.patch.object(api_kg, "_load_kg", lambda pid: (bad, None)):
            api_kg._CACHE.clear()
            r = self.read("explore", what="gaps")
        self.assertFalse(r["active"])
        self.assertIn("passed", r["reason"])
        self.assertEqual(r["ids"], [])

    def test_unknown_explore_is_404_and_reads_write_nothing(self):
        before = files_under(self.tmp)
        self.assertIsNone(api_kg.read(self.engine, ["kg", "explore"], {"what": "../x"}))
        for what in ("gaps", "orphans", "reach"):
            self.read("explore", what=what, start=nid_of(self.pg, "P-1"))
        self.assertEqual(files_under(self.tmp), before)


def study_fixture(case):
    """구간 S1(P-1·CV-1·TK-1·PSV-1)과 시나리오 e1: 원인 위치 P-1, 영향 대상 TK-1, 보호수단 PSV-1. 원인 글에는 HTML 모양 글을 넣는다."""
    from tests.test_study_storage import entry
    case.evil = "<img src=x onerror=alert(1)> 넘침"
    e1 = entry("e1", cause=case.evil, cause_refs=[{"ref": sref(case.pg, "P-1")}],
               consequence_refs=[{"ref": sref(case.pg, "TK-1")}],
               safeguards=[{"text": "고압 트립", "role": "preventive", "refs": [{"ref": sref(case.pg, "PSV-1")}]}])
    case.ns, case.doc = save_study(case, [("A", ["o-p1", "o-cv1", "o-tk1", "o-psv1"])], [("S1", "I1", [e1])])


class StudyLayerTest(Base):
    """완료 목록 3 B6 '검토 층': 분석 결과(시나리오·보호수단)와 초기사건 후보를 그래프에 투영해 켜고 끈다. 원본은 결과 파일이고 읽기만 한다."""

    def setUp(self):
        super().setUp()
        study_fixture(self)

    def test_layer_is_off_until_asked(self):
        s = self.read()
        self.assertNotIn("study", s["layers"])
        g = self.read("graph", expand="all")
        self.assertFalse([n for n in g["nodes"] if n["layer"] == "study"])

    def test_layer_projects_scenarios_and_safeguards_onto_components(self):
        s = self.read(study="1")
        self.assertGreater(s["layers"]["study"], 0, s["layers"])
        self.assertEqual(s["study"]["scenarios"], 1)
        g = self.read("graph", expand="all", study="1")
        ids = {n["id"]: n for n in g["nodes"]}
        self.assertIn("st-S1", ids)
        self.assertIn("st-e1", ids)
        self.assertIn(self.evil[:10], ids["st-e1"]["label"], "글은 그대로 글이다(HTML로 바꾸지 않는다)")
        rel = {(l["kind"], l["s"], l["t"]) for l in g["links"]}
        self.assertIn(("cause_at", "st-e1-c", nid_of(self.pg, "P-1")), rel)
        self.assertIn(("affects", "st-e1-q", nid_of(self.pg, "TK-1")), rel)
        self.assertIn(("safeguard_by", "st-e1-g1", nid_of(self.pg, "PSV-1")), rel)
        self.assertEqual(ids["st-e1"]["group"], "graph-T-001")

    def test_study_node_detail_is_read_only_and_comes_from_the_results(self):
        d = self.read("node", id="st-e1", study="1")
        self.assertEqual(d["layer"], "study")
        self.assertTrue(d["read_only"])
        self.assertIn(self.evil, [v for _, v in d["what"]])
        self.assertEqual(api_kg.node(self.engine, "st-e1"), None, "층을 끄면 검토 노드는 없다")

    def test_link_detail_explains_where_the_line_comes_from(self):
        g = self.read("graph", expand="all", study="1")
        cause = next(l for l in g["links"] if l["kind"] == "cause_at")
        d = self.read("link", id=cause["id"], study="1")
        self.assertEqual((d["from"]["id"], d["to"]["id"]), (cause["s"], cause["t"]))
        self.assertTrue(d["what"])
        self.assertTrue(any("분석 결과" in v for _, v in d["evidence"]), d["evidence"])
        kn = next(l for l in self.read("graph", expand="all")["links"] if l["id"].startswith(screen.KN_PREFIX))
        dk = self.read("link", id=kn["id"])
        self.assertTrue(any(k == "상태" for k, _ in dk["what"]), dk)
        pipe = next(l for l in self.read("graph", expand="all")["links"] if l["kind"] == "pipe")
        self.assertTrue(self.read("link", id=pipe["id"])["what"])
        self.assertIsNone(api_kg.read(self.engine, ["kg", "link"], {"id": "nope"}))

    def test_unapproved_and_ai_draft_scenarios_do_not_look_confirmed(self):
        """검토 B6-3: 승인한 것만 확정처럼(속 찬 원) 그린다. 승인 전은 pending, AI 초안은 draft도, 기각은 넣지 않는다."""
        from hazop import store_io
        from hazop.study import results as res
        from tests.test_study_storage import entry, put_entries
        doc = res.load(self.ns)
        put_entries(doc, "S1", "I1", [entry("ap", "approved"), entry("ai", "proposed", origin="ai_draft"), entry("hold", "on_hold"),
                                      entry("rej", "rejected"), entry("ai_ok", "approved", origin="ai_draft")])
        res.save_fp(doc, self.ns["project_id"], expect=store_io.ANY)
        nodes = {n["id"]: n for n in self.read("graph", expand="all", study="1")["nodes"]}
        flags = {k: (nodes["st-" + k]["pending"], nodes["st-" + k]["draft"]) for k in ("ap", "ai", "hold", "ai_ok")}
        self.assertEqual(flags, {"ap": (False, False), "ai": (True, True), "hold": (True, False), "ai_ok": (False, False)})
        self.assertNotIn("st-rej", nodes)
        self.assertIn(["작성", "승인 전"], self.read("node", id="st-hold", study="1")["evidence"])

    def test_layer_shows_the_same_sections_as_the_results_table(self):
        """검토 B6·B7-2: 검토 층의 구간은 분석 결과 표의 행(api_results.scope_rows)과 같다. 결과 표가 빼는 구간은 층에도 없다."""
        from hazop.shell import api_results
        from hazop.study import nodes as sn
        from tests.test_study_storage import entry
        e2 = entry("e2", consequence_refs=[{"ref": sref(self.pg, "P-1")}])
        save_study(self, [("A", ["o-p1", "o-cv1"]), ("B", ["o-tk1", "o-psv1"])], [("S2", "I1", [e2])])
        ns = sn.load(self.pg)
        ns["nodes"][1]["screen"] = {"status": "excluded", "reason": "검토"}
        sn.save(ns)
        rows = {n["node_id"] for n in api_results.scope_rows(sn.load(self.pg))}
        shown = {n["id"][3:] for n in self.read("graph", expand="all", study="1")["nodes"] if n.get("type") == "study_node"}
        self.assertEqual(shown, rows)
        ids = {n["id"] for n in self.read("graph", expand="all", study="1")["nodes"]}
        self.assertEqual("st-e2" in ids, "S2" in rows)

    def test_turning_the_layer_on_leaves_the_plain_model_alone(self):
        self.read("graph", expand="all", study="1")
        d = self.read("node", id=nid_of(self.pg, "P-1"))
        self.assertFalse([nb for nb in d["neighbors"] if nb["id"].startswith("st-")], "층을 켠 읽기가 기본 모델의 이웃 목록을 바꾸면 안 됨")
        self.assertTrue([nb for nb in self.read("node", id=nid_of(self.pg, "P-1"), study="1")["neighbors"] if nb["id"].startswith("st-")])

    def test_reads_reuse_the_layer_while_files_are_the_same(self):
        """검토 B6-4: 결과·구간·초기사건 파일이 그대로면 읽기마다 결과를 다시 읽고 묶음을 다시 만들지 않는다."""
        calls = []
        real = api_kg._study
        with mock.patch.object(api_kg, "_study", lambda pg: calls.append(1) or real(pg)):
            for _ in range(3):
                self.read("graph", expand="all", study="1")
                self.read(study="1")
        self.assertEqual(len(calls), 1)

    def test_results_change_is_seen_without_restart(self):
        from hazop import store_io
        from hazop.study import results as res
        from tests.test_study_storage import entry, put_entries
        self.read("graph", expand="all", study="1")
        doc = res.load(self.ns)
        put_entries(doc, "S1", "I1", [entry("e2", cause="새 원인")])
        res.save_fp(doc, self.ns["project_id"], expect=store_io.ANY)
        ids = {n["id"] for n in self.read("graph", expand="all", study="1")["nodes"]}
        self.assertIn("st-e2", ids)
        self.assertNotIn("st-e1", ids)


class ComponentTest(Base):
    """완료 목록 3 B7: 도면 구성요소 말풍선에 넣을 읽기(지식그래프 노드, 걸린 지식 요약, 이 구성요소를 쓰는 분석 칸)."""

    def setUp(self):
        super().setUp()
        study_fixture(self)

    def comp(self, tag):
        n = next(n for n in self.pg["nodes"] if n.get("tag") == tag)
        return self.read("component", sheet=n["sheet"], local=n["local_id"])

    def test_cells_that_point_at_the_component_with_their_role(self):
        p1 = self.comp("P-1")
        self.assertTrue(p1["found"])
        self.assertEqual(p1["id"], nid_of(self.pg, "P-1"))
        self.assertTrue(p1["in_graph"])
        self.assertEqual(p1["cells"]["count"], 1)
        item = p1["cells"]["items"][0]
        self.assertEqual((item["node_id"], item["deviation_id"], item["roles"]), ("S1", "D01", ["원인 위치"]))
        self.assertTrue(item["label"].startswith("S1 × "))
        self.assertEqual(self.comp("TK-1")["cells"]["items"][0]["roles"], ["영향 대상"])
        self.assertEqual(self.comp("PSV-1")["cells"]["items"][0]["roles"], ["보호수단"])
        self.assertEqual(self.comp("CV-1")["cells"]["count"], 0, "구간 안에 있어도 항목이 가리키지 않으면 세지 않는다")

    def test_rejected_entries_do_not_count(self):
        from hazop import store_io
        from hazop.study import results as res
        doc = res.load(self.ns)
        for c in doc["cells"]:
            for e in c.get("entries") or []:
                e["status"] = "rejected"
        res.save_fp(doc, self.ns["project_id"], expect=store_io.ANY)
        self.assertEqual(self.comp("P-1")["cells"]["count"], 0)

    def test_knowledge_summary_counts_linked_knowledge(self):
        psh = self.comp("PSH-1")
        self.assertEqual(psh["knowledge"]["count"], 1)
        self.assertIn("설정치 1", psh["knowledge"]["text"])
        self.assertEqual(self.comp("P-2")["knowledge"]["count"], 0)

    def test_cells_come_from_the_results_table_rows(self):
        """검토 B7-R1: 결과 표가 빼는 구간의 칸은 '쓰는 칸'으로 세지 않는다(같은 함수 scope_rows)."""
        from hazop.shell import api_results
        from hazop.study import nodes as sn
        from tests.test_study_storage import entry
        e1 = entry("e1", cause_refs=[{"ref": sref(self.pg, "P-1")}])
        e2 = entry("e2", consequence_refs=[{"ref": sref(self.pg, "P-1")}])
        save_study(self, [("A", ["o-p1", "o-cv1"]), ("B", ["o-tk1", "o-psv1"])], [("S1", "I1", [e1]), ("S2", "I1", [e2])])
        self.assertEqual({i["node_id"] for i in self.comp("P-1")["cells"]["items"]}, {"S1", "S2"})
        ns = sn.load(self.pg)
        ns["nodes"][1]["screen"] = {"status": "excluded", "reason": "검토"}
        sn.save(ns)
        rows = {n["node_id"] for n in api_results.scope_rows(sn.load(self.pg))}
        self.assertEqual({i["node_id"] for i in self.comp("P-1")["cells"]["items"]}, {"S1", "S2"} & rows)

    def test_unknown_component_is_not_found_and_reads_write_nothing(self):
        before = files_under(self.tmp)
        self.assertFalse(self.read("component", sheet="graph-T-001", local="../../etc")["found"])
        self.assertFalse(self.read("component")["found"])
        self.comp("P-1")
        self.assertEqual(files_under(self.tmp), before)


if __name__ == "__main__":
    unittest.main()
