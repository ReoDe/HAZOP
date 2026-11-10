"""지식그래프 알고리즘 A1~A5·A1′ 테스트 (기획서/그래프활용.md §4, §7.1, §7.2).
실행: python -m unittest discover -s tests -t .

P&ID 그래프는 샘플 도면 SNP-M-102를 임시 폴더에서 빌드하고(tests.test_kg.pid_graph), 지식그래프는 정상 샘플 CSV로
메모리에서 빌드한다(output/ 폴더에 의존하지 않음).
"""

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import analyze_kg  # noqa: E402
import check_kg_algo  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.analysis import run  # noqa: E402
from hazop.graph.query import GraphQuery  # noqa: E402
from hazop.kg import algo, build  # noqa: E402
from tests import test_kg  # noqa: E402

REGION_FILE = check_kg_algo.REGION_FILE
_CACHE = {}


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def inputs():
    """(kg, graph, regions) 사본."""
    if not _CACHE:
        graph = test_kg.pid_graph()
        _CACHE["graph"] = graph
        _CACHE["kg"] = build.build_kg(test_kg.sample(), [graph])
        _CACHE["region"] = _load(REGION_FILE)
        with open(REGION_FILE, "rb") as fh:
            _CACHE["sha"] = hashlib.sha256(fh.read()).hexdigest()
    return (copy.deepcopy(_CACHE["kg"]), copy.deepcopy(_CACHE["graph"]),
            [(REGION_FILE, copy.deepcopy(_CACHE["region"]), _CACHE["sha"])])


def other_graph(graph, gid="graph-OTHER"):
    """다른 도면 복제(Codex 재현): graph_id만 바꾼 사본."""
    g = copy.deepcopy(graph)
    g["graph_id"] = gid
    return g


def bfs_hops(g, start, k):
    """networkx와 독립인 무방향 BFS(홉 <= k)."""
    adj = {}
    for a, b in g.edges():
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen, frontier = {start: 0}, [start]
    for d in range(1, k + 1):
        nxt = []
        for n in frontier:
            for m in sorted(adj.get(n, ())):
                if m not in seen:
                    seen[m] = d
                    nxt.append(m)
        frontier = nxt
    return seen


class SampleExpectedTest(unittest.TestCase):
    """A1~A5가 정답 파일과 같음(A2는 §7.1 기대값 표 포함)."""

    def test_expected_file(self):
        kg, graph, regions = inputs()
        self.assertEqual(kg["validation"]["status"], "passed")
        exp = check_kg_algo.load_expected()
        probs, _ = check_kg_algo.expected_problems(kg, graph, regions, exp)
        self.assertEqual(probs, {k: [] for k in ("A1", "A2", "A3", "A4", "A5")})

    def test_a2_table_7_1(self):
        """§7.1 A2 기대값 표: RC-PT110 고아·공백 아님, RC-PV101 근거 공백, 언급 없는 설비는 지식 입력 없음,
        governed_by 없는 요건 1개 고아(같은 조각이 언급한 설비 힌트)."""
        kg, graph, _ = inputs()
        a2 = algo.a2_orphans_gaps(kg, graph)
        gaps = [g["tag"] for g in a2["evidence_gaps"]]
        none = [g["tag"] for g in a2["no_knowledge_input"]]
        self.assertEqual(gaps, ["RC-PV101"])
        self.assertNotIn("RC-PT110", gaps + none)
        self.assertIn("RC-PSV102", none)
        self.assertNotIn(None, none)  # 도면 연결점은 따로 표시
        self.assertEqual([g["entity_id"] for g in a2["no_knowledge_input_continuations"]],
                         ["entity-node-002", "entity-node-006", "entity-node-017"])
        req = [o for o in a2["orphans"] if o["node_type"] == "requirement"]
        self.assertEqual([o["id"] for o in req], ["req-003"])
        self.assertEqual([(h["chunk"], h["tag"]) for h in req[0]["link_hints"]], [("chunk-001", "RC-PV101")])

    def test_a2_candidate_only_mention_is_orphan(self):
        """mentions가 candidate로만 있는 조각은 고아(후보는 세지 않음). 언급 대상도 근거 공백으로 세지 않음."""
        kg, graph, _ = inputs()
        base = next(l for l in kg["links"] if l["id"] == "krel-m-114485f2")
        cand = copy.deepcopy(base)
        cand.update(id="krel-m-cand0001", **{"from": "chunk-004"}, link_status="candidate",
                    compute_view={"v4": False, "excluded_reasons": ["link_status=candidate"]})
        cand["ends"]["from"]["ref"] = "chunk-004"
        cand["ends"]["to"] = dict(base["ends"]["to"], entity_id="entity-node-015", tag="RC-PSV102")
        kg["links"].append(cand)
        a2 = algo.a2_orphans_gaps(kg, graph)
        self.assertIn("chunk-004", [o["id"] for o in a2["orphans"]])
        self.assertNotIn("entity-node-015", [g["entity_id"] for g in a2["evidence_gaps"]])
        self.assertIn("entity-node-015", [g["entity_id"] for g in a2["no_knowledge_input"]])
        _, _, excl = algo.v4_items(kg, graph)
        self.assertEqual(excl["kg_candidate_links"], 1)


    def test_a2_orphan_uses_whole_kg(self):
        """Codex 재현: graph-OTHER(복제 도면)에 req-003을 governed_by로 적용하면, SNP-M-102를 골라도 req-003은 고아가
        아님. 다른 도면만 언급한 조각도 고아가 아님. 근거 공백·지식 입력 없음은 선택 도면 기준 그대로."""
        _, graph, _ = inputs()
        other = other_graph(graph)
        k = test_kg.sample()
        k["links"].append(test_kg.link("krel-x-other", "governed_by", "graph-OTHER:RC-PZ01", "req-003"))
        kg = build.build_kg(k, [graph, other])
        self.assertEqual(kg["validation"]["status"], "passed")
        base = next(l for l in kg["links"] if l["id"] == "krel-m-114485f2")
        m = copy.deepcopy(base)
        m.update(id="krel-m-other001", **{"from": "chunk-003"})
        m["ends"]["from"]["ref"] = "chunk-003"
        m["ends"]["to"] = dict(base["ends"]["to"], graph_id="graph-OTHER", ref="graph-OTHER:RC-PV101")
        kg["links"].append(m)
        a2 = algo.a2_orphans_gaps(kg, graph)
        orphans = [o["id"] for o in a2["orphans"]]
        self.assertEqual(orphans, ["chunk-004"])  # req-003·chunk-003은 다른 도면 연결로 고아 아님
        self.assertEqual([g["tag"] for g in a2["evidence_gaps"]], ["RC-PV101"])  # 선택 도면 기준
        a2o = algo.a2_orphans_gaps(kg, other)  # 다른 도면을 고르면 그 도면 기준
        self.assertNotIn("entity-node-001", [g["entity_id"] for g in a2o["no_knowledge_input"]])
        self.assertEqual([g["entity_id"] for g in a2o["evidence_gaps"]], ["entity-node-008"])
        v5 = algo.view_v5(kg, graph)  # 다른 도면 관계는 선택 도면 V5에 넣지 않음
        self.assertNotIn("krel-x-other", {key for _, _, key in v5.edges(keys=True)})

    def test_l3_rejected_and_unknown_links_excluded(self):
        """L3: rejected 관계·unknown 관계는 V4·V5와 A2 판정에 들어가지 않음."""
        _, graph, regions = inputs()
        k = test_kg.sample()
        k["links"].append(test_kg.link("krel-x-rej", "governed_by", "graph-SNP-M-102:RC-PSV102", "req-003",
                                       link_status="rejected"))
        k["links"].append(test_kg.link("krel-x-unk", "has_setpoint", "graph-SNP-M-102:RC-PV101", "setpt-001",
                                       knowledge_status="unknown"))
        kg = build.build_kg(k, [graph])
        self.assertEqual(kg["validation"]["status"], "passed")
        a2 = algo.a2_orphans_gaps(kg, graph)
        self.assertIn("req-003", [o["id"] for o in a2["orphans"]])
        self.assertIn("entity-node-015", [g["entity_id"] for g in a2["no_knowledge_input"]])
        self.assertEqual([g["entity_id"] for g in a2["evidence_gaps"]], ["entity-node-008"])
        for g in (algo.view_v4(kg, graph), algo.view_v5(kg, graph)):
            self.assertFalse({"krel-x-rej", "krel-x-unk"} & {key for _, _, key in g.edges(keys=True)})
        text = json.dumps(algo.analyze(kg, graph, regions, "entity-node-001", 3)["results"], ensure_ascii=False)
        self.assertNotIn("krel-x-rej", text)
        self.assertNotIn("krel-x-unk", text)


class ViewTest(unittest.TestCase):

    def test_excluded_end_node_not_readded(self):
        """V4 관계라도 지식 끝 노드가 V4 밖이면 엣지로 다시 들어오지 않음(포함 플래그 일관성)."""
        kg, graph, _ = inputs()
        next(n for n in kg["nodes"] if n["id"] == "req-001")["compute_view"] = {"v4": False, "excluded_reasons": ["x"]}
        for g in (algo.view_v4(kg, graph), algo.view_v5(kg, graph)):
            self.assertNotIn("req-001", g)
            self.assertFalse({"krel-005", "krel-008"} & {key for _, _, key in g.edges(keys=True)})

    def test_excluded_items_not_in_views(self):
        """unknown·hypothesis 노드와 그 관계(setpt-003, case-001, krel-012, krel-015)는 V4·V5와 결과에 없음."""
        kg, graph, regions = inputs()
        out = {n["id"] for n in kg["nodes"] if not n["compute_view"]["v4"]}
        out_links = {l["id"] for l in kg["links"] if not l["compute_view"]["v4"]}
        self.assertEqual(out, {"setpt-003", "case-001"})
        self.assertEqual(out_links, {"krel-012", "krel-015"})
        for g in (algo.view_v4(kg, graph), algo.view_v5(kg, graph)):
            self.assertFalse(out & set(g.nodes))
            self.assertFalse(out_links & {k for _, _, k in g.edges(keys=True)})
        text = json.dumps(algo.analyze(kg, graph, regions, "entity-node-001", 3)["results"], ensure_ascii=False)
        for i in out | out_links:
            self.assertNotIn('"%s"' % i, text)

    def test_v5_is_union(self):
        kg, graph, _ = inputs()
        v1, v3, v4, v5 = algo.view_v1(graph), algo.view_v3(graph), algo.view_v4(kg, graph), algo.view_v5(kg, graph)
        keys = lambda g: {k for _, _, k in g.edges(keys=True)}  # noqa: E731
        self.assertEqual(keys(v5), keys(v1) | keys(v3) | keys(v4))
        self.assertEqual(set(v5.nodes), set(v1.nodes) | set(v4.nodes))
        self.assertTrue(all(d["kind"] == "has_endpoint" for _, _, d in v1.edges(data=True)))

    def test_blocked_or_version_mismatch_refused(self):
        kg, graph, regions = inputs()
        bad = copy.deepcopy(kg)
        bad["validation"]["status"] = "blocked"
        with self.assertRaises(algo.AlgoError):
            algo.analyze(bad, graph, regions, "entity-node-001")
        g2 = dict(graph, graph_version="v-000000000000")
        with self.assertRaises(algo.AlgoError):
            algo.analyze(kg, g2, regions, "entity-node-001")
        with self.assertRaises(algo.AlgoError):  # 지식그래프가 참조하지 않은 도면
            algo.analyze(kg, other_graph(graph), regions, "entity-node-001")
        with self.assertRaises(algo.AlgoError):
            analyze_kg.pick_graph(kg, [other_graph(graph)], "graph-OTHER")
        with self.assertRaises(algo.AlgoError):
            analyze_kg.pick_graph(kg, [g2], None)


class A1Test(unittest.TestCase):

    def test_a1_prime_matches_analysis_run(self):
        """A1′: focus_entities[0]에서 A1 탐색 = ④ 분석 실행(prepare_doc) 탐색, 전체 일치."""
        kg, graph, regions = inputs()
        region = regions[0][1]
        files = {k: paths.resolve_rel(v, REPO_ROOT) for k, v in region["inputs"].items()}
        prepared = run.prepare(region, graph, _load(files["candidate_catalog"]), _load(files["applicability"]),
                               _load(files["patterns"]), _load(files["risk_criteria"]))
        self.assertEqual(prepared["blockers"], [])
        ref = run.prepare_doc(prepared, None)["explorations"][0]
        a1 = algo.a1_propagation(graph, regions, region["focus_entities"][0])
        self.assertTrue(a1["active"])
        self.assertEqual(a1["exploration"], ref)

    def test_a1_prime_detects_different_arguments(self):
        """일치 검사가 실제로 차이를 잡는지: 다른 max_depth로 A1을 돌리면 ④ 결과와 달라야 함."""
        kg, graph, regions = inputs()
        ref = algo.a1_propagation(graph, regions, "entity-node-001")["exploration"]
        regions[0][1]["exploration"]["max_depth"] = 2
        other = algo.a1_propagation(graph, regions, "entity-node-001")["exploration"]
        self.assertNotEqual(other, ref)
        self.assertIn("max_depth", other["limits_hit"])

    def test_a1_inactive_cases(self):
        kg, graph, regions = inputs()
        self.assertEqual(algo.a1_propagation(graph, regions, "req-001")["active"], False)
        small = copy.deepcopy(regions)
        small[0][1]["members"] = [m for m in small[0][1]["members"] if m["entity_id"] != "entity-node-015"]
        r = algo.a1_propagation(graph, small, "entity-node-015")
        self.assertEqual((r["active"], r["reason"]), (False, "검토 구간 미지정"))
        two = regions + [("other.json", copy.deepcopy(regions[0][1]), "0" * 64)]
        r = algo.a1_propagation(graph, two, "entity-node-001")
        self.assertFalse(r["active"])
        self.assertEqual([x["file"] for x in r["regions"]], sorted([REGION_FILE, "other.json"]))
        stale = copy.deepcopy(regions)
        stale[0][1]["graph_ref"]["graph_version"] = "v-000000000000"
        r = algo.a1_propagation(graph, stale, "entity-node-001")
        self.assertEqual((r["active"], r["reason"]), (False, "검토 구간 입력 오류"))
        doc = algo.analyze(kg, graph, small, "entity-node-015", 1)
        self.assertFalse(doc["results"]["A1"]["result"]["active"])
        self.assertEqual(doc["limits"]["a1_truncations"], [])


class OtherAlgoTest(unittest.TestCase):

    def test_a3_fold(self):
        kg, graph, _ = inputs()
        v5 = algo.view_v5(kg, graph)
        a3 = algo.a3_degree(v5, graph)
        segs = {n["entity_id"] for n in graph["nodes"] if n["node_type"] == "pipe_segment"}
        self.assertFalse(segs & set(a3["degree_segments_folded"]))
        self.assertTrue(segs <= set(a3["degree"]))
        for n, d in a3["degree_segments_folded"].items():  # 양 끝이 있는 구간 1개 = 엣지 1개이므로 차수는 같음
            self.assertEqual(d["degree"], a3["degree"][n]["degree"])
        n = v5.number_of_nodes()
        self.assertAlmostEqual(a3["degree"]["entity-node-001"]["centrality"], round(8 / (n - 1), 6))

    def test_a3_segment_without_two_ends_not_folded(self):
        kg, graph, _ = inputs()
        drop = next(e for e in graph["edges"] if e["kind"] == "has_endpoint" and e["segment"] == "entity-seg-001")
        graph["edges"].remove(drop)
        a3 = algo.a3_degree(algo.view_v5(kg, graph), graph)
        self.assertIn({"segment": "entity-seg-001", "reason": "끝점 1개(2개 아님)"}, a3["segments_not_folded"])
        self.assertIn("entity-seg-001", a3["degree_segments_folded"])

    def test_a4_matches_independent_bfs(self):
        kg, graph, _ = inputs()
        v5 = algo.view_v5(kg, graph)
        for center in ("entity-node-001", "entity-node-014", "req-003", "doc-001"):
            for k in (0, 1, 2, 3):
                got = algo.a4_ego(v5, center, k)
                want = bfs_hops(v5, center, k)
                self.assertEqual(got["nodes"], sorted(want))
                self.assertEqual(got["hops"], {n: want[n] for n in sorted(want)})
        self.assertFalse(algo.a4_ego(v5, "case-001", 2)["active"])

    def test_a5_v1_matches_graph_query(self):
        kg, graph, _ = inputs()
        a5 = algo.a5_components(algo.view_v1(graph), algo.view_v5(kg, graph))
        c = GraphQuery(graph).components()
        self.assertEqual(a5["V1"]["count"], len(c["physical_components"]) + len(c["not_physically_connected"]))
        self.assertEqual(a5["V1"]["singletons"], len(c["not_physically_connected"]))
        self.assertEqual(sum(a5["V5"]["sizes"]), algo.view_v5(kg, graph).number_of_nodes())


class OutputTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_deterministic_atomic_write(self):
        kg, graph, regions = inputs()
        doc = algo.analyze(kg, graph, regions, "entity-node-001", 2)
        again = algo.analyze(*inputs(), "entity-node-001", 2)
        self.assertEqual(build.dump_bytes(doc), build.dump_bytes(again))
        path = algo.write_result(self.tmp, doc)
        out = os.path.dirname(path)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), build.dump_bytes(doc))
        self.assertEqual(sorted(os.listdir(out)), sorted([algo.RESULT_FILE, algo.REPORT_FILE]))
        self.assertEqual(doc["inputs"]["kg_version"], kg["kg_version"])
        self.assertEqual(doc["inputs"]["region_ref"]["sha256"], regions[0][2])
        rel = os.path.relpath(out, os.path.realpath(self.tmp)).replace(os.sep, "/")
        self.assertEqual(rel, "%s/algo/%s/%s@%s/region-SNP-M-102-pzr-%s/entity-node-001-r2-c-none-h%s" % (
            kg["kg_id"], kg["kg_version"], graph["graph_id"], graph["graph_version"], regions[0][2][:12],
            algo._content_id(doc)))
        with open(os.path.join(out, algo.REPORT_FILE), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("RC-PV101", text)
        self.assertIn("kg 내 candidate 관계: 0", text)
        self.assertIn("후보 CSV의 미확인 후보: 파일 없음", text)
        # 같은 입력으로 다시 쓰면 파일을 건드리지 않음(수정 시각 그대로)
        mtimes = {n: os.stat(os.path.join(out, n)).st_mtime_ns for n in os.listdir(out)}
        time.sleep(0.05)
        self.assertEqual(algo.write_result(self.tmp, again), path)
        self.assertEqual({n: os.stat(os.path.join(out, n)).st_mtime_ns for n in os.listdir(out)}, mtimes)
        # 후보 CSV가 다르면 다른 경로(같은 경로에 다른 내용을 쓰지 않음)
        doc2 = algo.analyze(kg, graph, regions, "entity-node-001", 2,
                            {"file": "x.csv", "sha256": "0" * 64, "unconfirmed_candidates": 5})
        path2 = algo.write_result(self.tmp, doc2)
        self.assertNotEqual(path2, path)
        with open(os.path.join(os.path.dirname(path2), algo.REPORT_FILE), encoding="utf-8") as fh:
            self.assertIn("후보 CSV의 미확인 후보: 5", fh.read())
        self.assertEqual(sorted(os.listdir(os.path.dirname(out))), sorted(
            [os.path.basename(out), os.path.basename(os.path.dirname(path2))]))
        # 같은 경로에 다른 내용이 있으면 멈추고 기존 파일을 건드리지 않음
        with open(path, "ab") as fh:
            fh.write(b" ")
        with open(path, "rb") as fh:
            tampered = fh.read()
        with self.assertRaises(algo.AlgoError):
            algo.write_result(self.tmp, doc)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), tampered)

    def test_label_or_generator_change_gets_new_path_not_error(self):
        """경로 앞 칸에 없는 값(구간 파일 라벨, 생성기·networkx 버전)만 바뀌어도 새 경로에 써서 AlgoError가 나지 않음."""
        kg, graph, regions = inputs()
        doc = algo.analyze(kg, graph, regions, "entity-node-001", 2)
        p1 = algo.write_result(self.tmp, doc)
        relabeled = [("other-label.json",) + tuple(regions[0][1:])]
        p2 = algo.write_result(self.tmp, algo.analyze(kg, graph, relabeled, "entity-node-001", 2))
        doc3 = json.loads(build.dump_bytes(doc).decode("utf-8"))
        doc3["generator"]["networkx"] = "0.0-test"
        p3 = algo.write_result(self.tmp, doc3)
        self.assertEqual(len({p1, p2, p3}), 3)
        self.assertEqual(algo.write_result(self.tmp, doc), p1)

    def test_rename_failure_keeps_existing(self):
        """새 결과 폴더의 rename이 실패해도 기존 결과(다른 입력 경로)와 정식 경로가 망가지지 않고, 다음 실행에서 정리됨."""
        kg, graph, regions = inputs()
        doc = algo.analyze(kg, graph, regions, "entity-node-001", 2)
        path = algo.write_result(self.tmp, doc)
        with open(path, "rb") as fh:
            before = fh.read()
        doc2 = algo.analyze(kg, graph, regions, "entity-node-001", 1)
        target = algo.output_dir(self.tmp, doc2)
        with mock.patch.object(algo.os, "rename", side_effect=OSError("주입한 rename 실패")):
            with self.assertRaises(OSError):
                algo.write_result(self.tmp, doc2)
            self.assertEqual(algo.write_result(self.tmp, doc), path)  # 기존 결과가 있으면 rename 자체를 하지 않음
        self.assertFalse(os.path.exists(target))
        self.assertTrue(os.path.isdir(target + ".partial"))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(sorted(os.listdir(os.path.dirname(path))), sorted([algo.RESULT_FILE, algo.REPORT_FILE]))
        p2 = algo.write_result(self.tmp, doc2)  # 다음 실행: 남은 .partial 정리 후 정상 생성
        self.assertTrue(os.path.isfile(p2))
        self.assertFalse(os.path.exists(target + ".partial"))

    def test_different_inputs_different_paths(self):
        kg, graph, regions = inputs()
        changed = [(regions[0][0], dict(regions[0][1], note="changed"), "f" * 64)]
        docs = [algo.analyze(kg, graph, regions, "entity-node-001", 2),
                algo.analyze(kg, graph, changed, "entity-node-001", 2),   # 구간 파일 내용
                algo.analyze(kg, graph, regions, "entity-node-001", 1),   # 깊이
                algo.analyze(kg, graph, regions, "entity-node-009", 2),   # 시작 노드
                algo.analyze(kg, graph, [], "entity-node-001", 2),        # 구간 없음
                algo.analyze(kg, graph, regions + [("b.json", regions[0][1], "e" * 64)], "entity-node-001", 2)]
        g2 = dict(graph, graph_version="v-111111111111")
        kg2 = dict(kg, kg_version="v-222222222222", graph_refs=[{"graph_id": graph["graph_id"],
                                                                 "graph_version": g2["graph_version"]}])
        r2 = [(regions[0][0], dict(regions[0][1], graph_ref=dict(regions[0][1]["graph_ref"],
                                                                   graph_version=g2["graph_version"])), "d" * 64)]
        docs.append(algo.analyze(kg2, g2, r2, "entity-node-001", 2))  # kg·그래프 버전
        dirs = [algo.output_dir(self.tmp, d) for d in docs]
        self.assertEqual(len(set(dirs)), len(dirs))

    def _link_dir(self, link, target):
        try:
            import _winapi
            _winapi.CreateJunction(target, link)
            return
        except (ImportError, OSError, AttributeError):
            pass
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("junction·심볼릭 링크를 만들 수 없음")

    def test_junction_escape_refused(self):
        kg, graph, regions = inputs()
        doc = algo.analyze(kg, graph, regions, "entity-node-001", 2)
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        root = os.path.join(self.tmp, "root")
        os.makedirs(root)
        self._link_dir(os.path.join(root, kg["kg_id"]), outside)  # 첫 중간 디렉터리가 루트 밖을 가리킴
        with self.assertRaises(algo.AlgoError):
            algo.write_result(root, doc)
        self.assertEqual(os.listdir(outside), [])
        root2 = os.path.join(self.tmp, "root2")
        os.makedirs(os.path.join(root2, kg["kg_id"], "algo"))
        self._link_dir(os.path.join(root2, kg["kg_id"], "algo", kg["kg_version"]), outside)  # 더 깊은 중간 디렉터리
        with self.assertRaises(algo.AlgoError):
            algo.write_result(root2, doc)
        self.assertEqual(os.listdir(outside), [])
        for link in (os.path.join(root, kg["kg_id"]), os.path.join(root2, kg["kg_id"], "algo", kg["kg_version"])):
            os.rmdir(link) if os.path.isdir(link) and not os.path.islink(link) else os.unlink(link)

    def test_count_candidates(self):
        self.assertIsNone(analyze_kg.count_candidates(os.path.join(self.tmp, "none.csv")))
        p = os.path.join(self.tmp, "c.csv")
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("# 머리 주석\ncandidate_key,link_status\na,candidate\nb,confirmed\nc,rejected\nd,candidate\n")
        c = analyze_kg.count_candidates(p)
        self.assertEqual(c["unconfirmed_candidates"], 2)
        self.assertEqual(len(c["sha256"]), 64)


class SyntheticTest(unittest.TestCase):

    def test_synthetic_size_and_run(self):
        for total in (500, 1000):
            graph, kg, regions = check_kg_algo.synthetic(total)
            self.assertEqual(len(graph["nodes"]) + len(kg["nodes"]), total)
            doc = algo.analyze(kg, graph, regions, regions[0][1]["focus_entities"][0], 2)
            self.assertTrue(doc["results"]["A1"]["result"]["active"])
            v5 = algo.view_v5(kg, graph)
            v4_ids = {n["id"] for n in kg["nodes"] if n["compute_view"]["v4"]}
            self.assertEqual(set(v5.nodes) - {n["entity_id"] for n in graph["nodes"]}, v4_ids)


if __name__ == "__main__":
    unittest.main()
