"""지식 레이어 입력·빌더 테스트 (기획서/그래프활용.md §7.2 K1~K8). 실행: python -m unittest discover -s tests -t .

P&ID 그래프는 샘플 도면 SNP-M-102를 임시 폴더에서 추출·빌드해 쓴다(출력/ 폴더에 의존하지 않음).
"""

import copy
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import build_kg  # noqa: E402
import check_kg  # noqa: E402
import extract_drawio  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.graph import build as gbuild  # noqa: E402
from hazop.kg import build, inputs  # noqa: E402

SAMPLE_DIR = paths.folder("표본", "지식", "SNP-SAMPLE")
_DRAWIO = [p for p in glob.glob(paths.folder("참고", "P&ID 도면 샘플", "*", "*.drawio"))
           if os.path.basename(os.path.dirname(p)).startswith("SNP-M-102")]
_GRAPH = None


def pid_graph():
    """샘플 도면 SNP-M-102를 ③ 파이프라인(extract_drawio.run_one: SVG 정렬 포함)과 같은 방식으로 임시 폴더에서 빌드.
    정상 샘플의 mentions 행 graph_version이 이 값과 같아야 재확인 대상이 되지 않는다."""
    global _GRAPH
    if _GRAPH is None:
        tmp = tempfile.mkdtemp()
        try:
            ex, _ = extract_drawio.run_one(_DRAWIO[0], tmp)
        finally:
            shutil.rmtree(tmp)
        _GRAPH = gbuild.build_graph(ex)
    return copy.deepcopy(_GRAPH)


def sample():
    return check_kg.load_dir(SAMPLE_DIR, "SNP-SAMPLE")


def link(id, kind, frm, to, **kw):
    d = {"id": id, "kind": kind, "from": frm, "to": to, "method": "manual", "extractor": None, "confidence": None,
         "knowledge_status": "confirmed", "link_status": "confirmed",
         "source": {"material_id": "MAT-KG-001", "registration_version": "1", "document_id": "DOC-KG-001",
                    "page": "1", "locator": None, "unregistered_reason": None},
         "author": "t", "reviewed_by": "r", "reviewed_at": None, "reason": None, "mention": None}
    d.update(kw)
    return d


NO_SOURCE = {"material_id": None, "registration_version": None, "document_id": None, "page": None, "locator": None,
             "unregistered_reason": inputs.UNREGISTERED_REASON}


def keys(kg):
    return check_kg.blocker_keys(kg)


class SampleTest(unittest.TestCase):

    def test_sample_passes_with_expected_shape(self):
        kg = build.build_kg(sample(), [pid_graph()])
        self.assertEqual(kg["validation"]["status"], "passed", kg["validation"]["blockers"])
        self.assertEqual(kg["graph_refs"], [{"graph_id": "graph-SNP-M-102", "graph_version": pid_graph()["graph_version"]}])
        self.assertRegex(kg["kg_version"], r"^v-[0-9a-f]{12}$")
        v4 = {x["id"] for x in kg["nodes"] + kg["links"] if x["compute_view"]["v4"]}
        # 계산 제외: unknown 노드·hypothesis 노드와 관계, V4 밖 노드에 닿는 관계
        for i in ("setpt-003", "case-001", "krel-015", "krel-012"):
            self.assertNotIn(i, v4)
        self.assertIn("krel-008", v4)
        # 상속: 근거 열을 비운 governed_by는 요건 노드 근거를 상속
        l8 = next(l for l in kg["links"] if l["id"] == "krel-008")
        self.assertEqual(l8["source_inherited_from"], "req-001")
        self.assertEqual(l8["source"]["document_id"], "DOC-KG-001")
        self.assertEqual(l8["ends"]["from"]["entity_id"], "entity-node-001")

    def test_pid_layer_unchanged(self):
        g = pid_graph()
        before = json.dumps(g, sort_keys=True)
        build.build_kg(sample(), [g])
        self.assertEqual(json.dumps(g, sort_keys=True), before)

    def test_sample_header_comments_skipped(self):
        k = sample()
        self.assertEqual([n["id"] for n in k["nodes"]][:3], ["doc-001", "chunk-001", "chunk-002"])
        self.assertEqual(len(k["nodes"]), 14)
        self.assertEqual(len(k["links"]), 17)
        self.assertTrue(k["nodes"][1]["text"].startswith("3.1절(가상)."))
        self.assertFalse(any(x["id"].startswith("#") for x in k["nodes"] + k["links"]))

    def _write(self, text):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        p = os.path.join(tmp, "n.csv")
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(text)
        return p

    def test_csv_blank_and_comment_lines_before_header_only(self):
        header = ",".join(inputs.NODE_COLUMNS)
        row = ["req-1", "requirement", "", '"첫 줄\n# 둘째 줄도 원문\n\n셋째 줄"'] + [""] * (len(inputs.NODE_COLUMNS) - 4)
        p = self._write("\n# 가상 자료 주석\n\n   \n" + header + "\n" + ",".join(row) + "\n")
        rows = inputs.read_csv(p, inputs.NODE_COLUMNS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "req-1")
        self.assertEqual(rows[0]["text"], "첫 줄\n# 둘째 줄도 원문\n\n셋째 줄")
        self.assertIsNone(rows[0]["item"])

    def test_csv_column_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            inputs.read_csv(self._write("# 주석\nid,node_type\nreq-1,requirement\n"), inputs.NODE_COLUMNS)


class K1WhitelistTest(unittest.TestCase):

    def test_unknown_kind_and_type_pair_blocked(self):
        for case, check in (("k1_unknown_relation_kind", "unknown_relation_kind"),
                            ("k1_type_pair_not_allowed", "type_pair_not_allowed")):
            with self.subTest(case=case):
                self.assertEqual(check_kg.fixture_problems(os.path.join(check_kg.FIXTURE_ROOT, case), [pid_graph()]), [])

    def test_unknown_node_type_and_status_blocked(self):
        k = sample()
        k["nodes"][0]["node_type"] = "support"
        k["links"][0]["link_status"] = "maybe"
        # doc-001을 끝으로 쓰는 part_of 4개는 타입 쌍도 맞지 않아 함께 차단(연쇄), 근거 상속 K6는 중복 보고하지 않음
        self.assertEqual(keys(build.build_kg(k, [pid_graph()])),
                         [("K1", "invalid_link_status", "krel-001")]
                         + [("K1", "type_pair_not_allowed", "krel-00%d" % i) for i in range(1, 5)]
                         + [("K1", "unknown_node_type", "doc-001")])


class K2ReferenceTest(unittest.TestCase):

    def test_ambiguous_tag_fixture(self):
        self.assertEqual(check_kg.fixture_problems(os.path.join(check_kg.FIXTURE_ROOT, "k2_ambiguous_tag"),
                                                   [pid_graph()]), [])

    def test_source_object_id_ref_resolves_same_name_segment(self):
        k = sample()
        k["links"].append(link("krel-090", "has_condition", "graph-SNP-M-102#e14", "cond-002"))
        kg = build.build_kg(k, [pid_graph()])
        self.assertEqual(kg["validation"]["status"], "passed")
        end = kg["links"][-1]["ends"]["from"]
        self.assertEqual((end["entity_id"], end["tag"], end["node_type"]), ("entity-seg-004", "RC-L011", "pipe_segment"))

    def test_missing_tag_graph_and_node_blocked(self):
        k = sample()
        k["links"] += [link("krel-091", "governed_by", "graph-SNP-M-102:RC-V999", "req-003"),
                       link("krel-092", "governed_by", "graph-SNP-X-999:RC-PZ01", "req-003"),
                       link("krel-093", "governed_by", "graph-SNP-M-102:RC-PZ01", "req-999")]
        kg = build.build_kg(k, [pid_graph()])
        self.assertEqual(keys(kg), [("K2", "graph_not_found", "krel-092"), ("K2", "pid_ref_not_found", "krel-091"),
                                    ("K2", "unknown_node_reference", "krel-093")])
        self.assertFalse(any(l["compute_view"]["v4"] for l in kg["links"][-3:]))


class K3IdTest(unittest.TestCase):

    def test_duplicate_fixture(self):
        self.assertEqual(check_kg.fixture_problems(os.path.join(check_kg.FIXTURE_ROOT, "k3_duplicate_id"),
                                                   [pid_graph()]), [])

    def test_pid_prefix_conflict_and_node_link_duplicate(self):
        k = sample()
        k["nodes"][0]["id"] = "entity-node-001"
        k["links"].append(link("req-001", "governed_by", "graph-SNP-M-102:RC-PZ01", "req-002"))
        kg = build.build_kg(k, [pid_graph()])
        self.assertIn(("K3", "id_prefix_conflict", "entity-node-001"), keys(kg))
        self.assertIn(("K3", "duplicate_id", "req-001"), keys(kg))


class K4DeterminismTest(unittest.TestCase):

    def test_same_input_same_version_and_bytes(self):
        a = build.build_kg(sample(), [pid_graph()])
        b = build.build_kg(sample(), [pid_graph()])
        self.assertEqual(a["kg_version"], b["kg_version"])
        self.assertEqual(build.dump_bytes(a), build.dump_bytes(b))
        ids = [x["id"] for x in a["nodes"] + a["links"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_cli_writes_atomically_and_identically(self):
        tmp = tempfile.mkdtemp()
        try:
            groot = os.path.join(tmp, "graph")
            os.makedirs(os.path.join(groot, "SNP-M-102"))
            with open(os.path.join(groot, "SNP-M-102", "graph.json"), "w", encoding="utf-8") as fh:
                json.dump(pid_graph(), fh, ensure_ascii=False)
            out = os.path.join(tmp, "out")
            argv = ["SNP-SAMPLE", "--input-root", os.path.dirname(SAMPLE_DIR), "--graph-root", groot, "--out-root", out]
            raw = io.BytesIO()
            stream = io.TextIOWrapper(raw, encoding="cp949", errors="strict", newline="\n")
            with mock.patch.object(sys, "stdout", stream):
                self.assertEqual(build_kg.main(argv), 0)
                root = os.path.join(out, "kg-SNP-SAMPLE")
                ver = build.current_dir(root)
                first = {}
                for f in ("knowledge.json", "knowledge_graph.json"):
                    with open(os.path.join(ver, f), "rb") as fh:
                        first[f] = fh.read()
                self.assertEqual(build_kg.main(argv), 0)
                stream.flush()
            self.assertEqual(build.current_dir(root), ver)
            for f, data in first.items():
                with open(os.path.join(ver, f), "rb") as fh:
                    self.assertEqual(fh.read(), data)
            # .tmp 남지 않음
            self.assertEqual(sorted(os.listdir(root)), sorted(["current.json", os.path.basename(ver)]))
            self.assertEqual(sorted(os.listdir(ver)), ["knowledge.json", "knowledge_graph.json"])
            build.load_outputs(root)
        finally:
            shutil.rmtree(tmp)


    def test_key_order_does_not_change_bytes(self):
        def reorder(x):
            if isinstance(x, dict):
                return {k: reorder(x[k]) for k in reversed(list(x))}
            if isinstance(x, list):
                return [reorder(v) for v in x]
            return x
        k1 = sample()
        k2 = reorder(sample())
        self.assertNotEqual(list(k1), list(k2))
        self.assertEqual(build.dump_bytes(k1), build.dump_bytes(k2))
        a, b = build.build_kg(k1, [pid_graph()]), build.build_kg(k2, [reorder(pid_graph())])
        self.assertEqual(a["kg_version"], b["kg_version"])
        self.assertEqual(build.dump_bytes(a), build.dump_bytes(b))

    def test_outputs_hash_link_and_interrupted_write_detected(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        k = sample()
        build.write_outputs(tmp, k, build.build_kg(k, [pid_graph()]))
        loaded_k, loaded_kg = build.load_outputs(tmp)
        self.assertEqual(loaded_kg["knowledge_sha256"], build.build_kg(k, [pid_graph()])["knowledge_sha256"])
        self.assertEqual(build.dump_bytes(loaded_k), build.dump_bytes(k))
        v1 = build.build_kg(k, [pid_graph()])["kg_version"]
        # 새 입력으로 다시 쓰다가 knowledge.json만 쓰고 knowledge_graph.json 쓰기에서 실패
        k2 = sample()
        k2["nodes"][0]["reason"] = "변경"
        kg2 = build.build_kg(k2, [pid_graph()])
        self.assertNotEqual(kg2["kg_version"], v1)
        real = build.write_json_atomic
        calls = []

        def flaky(path, obj):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("모의 쓰기 실패")
            return real(path, obj)
        with mock.patch.object(build, "write_json_atomic", side_effect=flaky):
            with self.assertRaises(OSError):
                build.write_outputs(tmp, k2, kg2)
        self.assertEqual([os.path.basename(c) for c in calls], ["knowledge.json", "knowledge_graph.json"])
        # 포인터는 이전 버전 그대로, 읽기 결과도 이전 버전(새·옛 파일이 섞이지 않음)
        self.assertEqual(build.current_dir(tmp), os.path.join(tmp, v1))
        old_k, old_kg = build.load_outputs(tmp)
        self.assertEqual((old_kg["kg_version"], build.dump_bytes(old_k)), (v1, build.dump_bytes(k)))
        # 다시 성공하면 포인터가 새 버전으로 바뀌고 이전 버전 폴더는 남음
        build.write_outputs(tmp, k2, kg2)
        self.assertEqual(build.load_outputs(tmp)[1]["kg_version"], kg2["kg_version"])
        self.assertTrue(os.path.isdir(os.path.join(tmp, v1)))
        # 포인터와 파일 해시가 다르면 오류
        with open(os.path.join(tmp, kg2["kg_version"], "knowledge.json"), "ab") as fh:
            fh.write(b" ")
        with self.assertRaises(ValueError):
            build.load_outputs(tmp)


class K5VersionTest(unittest.TestCase):

    def test_graph_version_change_changes_kg_version_and_rechecks_mentions(self):
        g2 = pid_graph()
        g2["graph_version"] = "v-000000000000"
        a = build.build_kg(sample(), [pid_graph()])
        b = build.build_kg(sample(), [g2])
        self.assertNotEqual(a["kg_version"], b["kg_version"])
        self.assertEqual(b["validation"]["status"], "passed")
        for l in (l for l in b["links"] if l["kind"] == "mentions"):
            self.assertEqual(l["recheck"]["changed"], ["graph_version"])
            self.assertIn("recheck_required", l["compute_view"]["excluded_reasons"])
        self.assertTrue(any(u["check"] == "recheck_required" for u in b["validation"]["unknowns"]))

    def test_input_change_changes_kg_version_and_chunk_text_rechecks(self):
        k = sample()
        k["nodes"][1]["text"] += " 추가 문장."
        a = build.build_kg(sample(), [pid_graph()])
        b = build.build_kg(k, [pid_graph()])
        self.assertNotEqual(a["kg_version"], b["kg_version"])
        rc = {l["id"]: l["recheck"] for l in b["links"] if l["kind"] == "mentions"}
        self.assertEqual(sorted(r["changed"][0] for r in rc.values() if r), ["text_sha256"])


    def test_chunk_material_or_registration_change_rechecks(self):
        for field, value in (("material_id", "MAT-KG-002"), ("registration_version", "2")):
            with self.subTest(field=field):
                k = sample()
                k["nodes"][1]["source"][field] = value  # chunk-001
                kg = build.build_kg(k, [pid_graph()])
                rc = {l["from"]: l["recheck"] for l in kg["links"] if l["kind"] == "mentions"}
                self.assertEqual(rc["chunk-001"]["changed"], [field])
                self.assertIsNone(rc["chunk-002"])

    def test_target_gone_after_reextraction_rechecks_not_blocks(self):
        mid = next(l["id"] for l in sample()["links"] if l["kind"] == "mentions" and l["to"].endswith(":RC-PV101"))
        g = pid_graph()
        g["nodes"] = [n for n in g["nodes"] if n["source_object_id"] != "n12"]  # RC-PV101 사라짐
        g["graph_version"] = "v-111111111111"  # 재추출로 버전도 바뀜
        kg = build.build_kg(sample(), [g])
        self.assertEqual(kg["validation"]["status"], "passed")
        l = next(x for x in kg["links"] if x["id"] == mid)
        self.assertEqual(l["recheck"]["changed"], ["graph_version", "target_source_object_id"])
        self.assertFalse(l["compute_view"]["v4"])
        self.assertIn(("recheck_required", mid), [(u["check"], u["target"]) for u in kg["validation"]["unknowns"]])
        # 같은 graph_version인데 대상이 없으면 작성 오류 -> K2 차단
        g2 = pid_graph()
        g2["nodes"] = [n for n in g2["nodes"] if n["source_object_id"] != "n12"]
        self.assertEqual(keys(build.build_kg(sample(), [g2])), [("K2", "pid_ref_not_found", mid)])


class K6SourceTest(unittest.TestCase):

    def test_fixtures(self):
        for case in ("k6_confirmed_node_without_source", "k6_depends_on_confirmed_no_source",
                     "k6_depends_on_hypothesis_no_source"):
            with self.subTest(case=case):
                self.assertEqual(check_kg.fixture_problems(os.path.join(check_kg.FIXTURE_ROOT, case), [pid_graph()]), [])

    def test_depends_on_with_source_passes(self):
        k = sample()
        k["links"].append(link("krel-094", "depends_on", "graph-SNP-M-102:RC-PV101", "graph-SNP-M-102:RC-PIC110"))
        kg = build.build_kg(k, [pid_graph()])
        self.assertEqual(kg["validation"]["status"], "passed")
        self.assertTrue(kg["links"][-1]["compute_view"]["v4"])

    def test_confirmed_link_inheriting_nothing_blocked_hypothesis_allowed(self):
        k = sample()
        k["links"].append(link("krel-095", "analyzed_in", "graph-SNP-M-102:RC-PV101", "case-001", source=dict(NO_SOURCE)))
        self.assertEqual(keys(build.build_kg(k, [pid_graph()])), [("K6", "confirmed_without_source", "krel-095")])
        k["links"][-1]["knowledge_status"] = "hypothesis"
        self.assertEqual(build.build_kg(k, [pid_graph()])["validation"]["status"], "passed")

    def test_mentions_need_chunk_hash_and_match_position(self):
        self.assertEqual(check_kg.fixture_problems(
            os.path.join(check_kg.FIXTURE_ROOT, "k6_mention_without_match_position"), [pid_graph()]), [])
        for field in ("chunk_id", "text_sha256", "match_start", "match_end"):
            with self.subTest(field=field):
                k = sample()
                m = next(l for l in k["links"] if l["kind"] == "mentions")
                m["mention"][field] = None
                self.assertEqual(keys(build.build_kg(k, [pid_graph()])), [("K6", "confirmed_without_source", m["id"])])
                m["knowledge_status"] = "hypothesis"  # 확인 전 상태면 차단 대신 근거 없음
                kg = build.build_kg(k, [pid_graph()])
                self.assertEqual(kg["validation"]["status"], "passed")
                self.assertIn(("no_source", m["id"]), [(u["check"], u["target"]) for u in kg["validation"]["unknowns"]])

    def test_match_position_must_lie_in_text_and_match_tag(self):
        def with_key(start, end, method="exact_norm"):
            k = sample()
            m = next(l for l in k["links"] if l["kind"] == "mentions" and l["from"] == "chunk-001")
            parts = m["mention"]["candidate_key"].split("|")
            parts[4], parts[5] = str(start), str(end)
            m["mention"]["candidate_key"] = "|".join(parts)
            m["mention"]["match_start"], m["mention"]["match_end"] = inputs.candidate_match(m["mention"]["candidate_key"])
            m["method"] = method
            return k, m["id"]
        for start, end in ((999999, 1000000), (47, 1000), (46, 54)):  # 범위 밖, 끝만 밖, 태그와 다른 문자열
            with self.subTest(pos=(start, end)):
                k, mid = with_key(start, end)
                self.assertEqual(keys(build.build_kg(k, [pid_graph()])), [("K6", "invalid_match_position", mid)])
        k, _ = with_key(46, 54, method="fuzzy")  # 유사 일치는 조건 2 미적용(범위만 확인)
        self.assertEqual(build.build_kg(k, [pid_graph()])["validation"]["status"], "passed")
        k, _ = with_key(47, 55)
        self.assertEqual(build.build_kg(k, [pid_graph()])["validation"]["status"], "passed")
        # 위치는 정규화 원문 기준: 원문에 공백을 덧대도(text_sha256 불변) 같은 위치가 유효
        k, mid = with_key(47, 55)
        k["nodes"][1]["text"] = "  " + k["nodes"][1]["text"].replace(" ", "   ")
        kg = build.build_kg(k, [pid_graph()])
        self.assertEqual(kg["validation"]["status"], "passed")
        self.assertIsNone(next(l for l in kg["links"] if l["id"] == mid)["recheck"])

    def test_candidate_key_match_positions_parsed(self):
        m = next(l for l in sample()["links"] if l["kind"] == "mentions")
        self.assertEqual((m["mention"]["match_start"], m["mention"]["match_end"]), (47, 55))
        self.assertEqual(inputs.candidate_match("a|b|c|d|x|9|g|v|r|s"), (None, None))
        self.assertEqual(inputs.candidate_match(None), (None, None))

    def test_inherit_only_from_node_with_source(self):
        kg = build.build_kg(sample(), [pid_graph()])
        lk = {l["id"]: l for l in kg["links"]}
        self.assertEqual(lk["krel-008"]["source_inherited_from"], "req-001")
        self.assertIsNone(lk["krel-015"]["source_inherited_from"])  # case-001은 근거 없음
        self.assertIsNone(lk["krel-015"]["source"]["material_id"])


def doc_conflicts(kg):
    """문서 값끼리의 충돌 members(도면 주장 충돌 제외). 샘플은 RC-PSV101 도면 설정압력 17.2 MPa와 setpt-003(9)도 충돌한다."""
    return [c["members"] for c in kg["conflicts"] if not any(m.startswith("graph-") for m in c["members"])]


class K7ConflictTest(unittest.TestCase):

    def test_both_values_kept_and_flagged(self):
        kg = build.build_kg(sample(), [pid_graph()])
        self.assertEqual(doc_conflicts(kg), [["setpt-001", "setpt-002"]])
        vals = {n["id"]: n["value"] for n in kg["nodes"]}
        self.assertEqual((vals["setpt-001"], vals["setpt-002"]), ("8", "8.5"))
        c = next(c for c in kg["conflicts"] if c["members"] == ["setpt-001", "setpt-002"])
        self.assertEqual(c["entity_id"], "entity-node-009")  # RC-PT110
        self.assertEqual((c["node_type"], c["item"], c["property"]), ("setpoint", "고압 트립", None))
        self.assertFalse(any("cond-" in i for c in kg["conflicts"] for i in c["members"]))  # 운전압력≠설계압력 항목

    def test_blank_operating_mode_compared_with_all_modes(self):
        k = sample()
        sp = {n["id"]: n for n in k["nodes"]}
        sp["setpt-002"]["operating_mode"] = "정상 운전"  # setpt-001은 빈 칸
        kg = build.build_kg(k, [pid_graph()])
        self.assertEqual(doc_conflicts(kg), [["setpt-001", "setpt-002"]])
        sp["setpt-001"]["operating_mode"] = "기동"  # 둘 다 적혀 있고 다르면 비교하지 않음
        self.assertEqual(doc_conflicts(build.build_kg(k, [pid_graph()])), [])

    def test_numeric_equal_values_not_conflict(self):
        k = sample()
        next(n for n in k["nodes"] if n["id"] == "setpt-002")["value"] = "8.0"
        self.assertEqual(doc_conflicts(build.build_kg(k, [pid_graph()])), [])


class K8UnknownValueTest(unittest.TestCase):

    def test_blank_stays_null_with_reason_and_zero_stays_text(self):
        kg = build.build_kg(sample(), [pid_graph()])
        sp = next(n for n in kg["nodes"] if n["id"] == "setpt-003")
        self.assertIsNone(sp["unit"])
        self.assertIsNone(sp["pressure_basis"])
        self.assertEqual(sp["null_reasons"]["unit"], inputs.BLANK_REASON)
        self.assertIn(("unknown_value", "setpt-003", "unit"),
                      [(u["check"], u["target"], u["field"]) for u in kg["validation"]["unknowns"]])
        case = next(n for n in kg["nodes"] if n["id"] == "case-001")
        self.assertIsNone(case["source"]["material_id"])
        self.assertEqual(case["source"]["unregistered_reason"], inputs.UNREGISTERED_REASON)
        rec = inputs.node_record({c: None for c in inputs.NODE_COLUMNS} | {"value": "0"})
        self.assertEqual(rec["value"], "0")
        rec = inputs.node_record({c: None for c in inputs.NODE_COLUMNS})
        self.assertIsNone(rec["value"])


class OtherPathsTest(unittest.TestCase):
    """아직 테스트가 없던 판정 경로."""

    def test_confirmed_without_reviewer(self):
        k = sample()
        k["links"][0]["reviewed_by"] = None
        self.assertEqual(keys(build.build_kg(k, [pid_graph()])), [("K1", "confirmed_without_reviewer", "krel-001")])

    def test_missing_value(self):
        k = sample()
        k["links"][0]["to"] = None
        self.assertEqual(keys(build.build_kg(k, [pid_graph()])), [("K1", "missing_value", "krel-001")])

    def test_graph_blocked(self):
        g = pid_graph()
        g["validation"]["status"] = "blocked"
        ks = keys(build.build_kg(sample(), [g]))
        self.assertTrue(ks)
        self.assertEqual({(r, c) for r, c, _ in ks}, {("K2", "graph_blocked")})

    def test_graph_ambiguous(self):
        g2 = pid_graph()
        g2["graph_version"] = "v-222222222222"
        ks = keys(build.build_kg(sample(), [pid_graph(), g2]))
        self.assertTrue(ks)
        self.assertEqual({(r, c) for r, c, _ in ks}, {("K2", "graph_ambiguous")})

    def test_mention_chunk_mismatch(self):
        k = sample()
        m = next(l for l in k["links"] if l["kind"] == "mentions" and l["from"] == "chunk-001")
        m["mention"]["chunk_id"] = "chunk-002"
        # 행의 chunk_id만 바뀌면 from과도, 후보 키와도 어긋남 -> K2와 K6(mention_key_mismatch) 모두 차단
        self.assertEqual(sorted(keys(build.build_kg(k, [pid_graph()]))),
                         sorted([("K2", "mention_chunk_mismatch", m["id"]), ("K6", "mention_key_mismatch", m["id"])]))

    def test_review_items(self):
        k = sample()
        k["nodes"].append(dict(k["nodes"][5], id="rq-009"))
        row = {c: None for c in inputs.LINK_COLUMNS}
        row.update({"id": "link-009", "kind": "governed_by", "from": "graph-SNP-M-102:RC-PZ01", "to": "rq-009",
                    "method": "manual", "knowledge_status": "confirmed", "link_status": "confirmed",
                    "reviewed_by": "r", "chunk_id": "chunk-001"})
        k["links"].append(inputs.link_record(row))
        kg = build.build_kg(k, [pid_graph()])
        self.assertEqual(kg["validation"]["status"], "passed")
        self.assertEqual(sorted((r["check"], r["target"]) for r in kg["review_items"]),
                         [("id_prefix_not_recommended", "link-009"), ("id_prefix_not_recommended", "rq-009"),
                          ("unused_mention_columns", "link-009")])



def pv101_mention(k):
    return next(l for l in k["links"] if l["kind"] == "mentions" and l["from"] == "chunk-001")


def set_key(m, **fields):
    """후보 키 필드를 바꾸고 일치 위치를 다시 읽는다."""
    parts = dict(zip(inputs.CANDIDATE_KEY_FIELDS, m["mention"]["candidate_key"].split("|")))
    parts.update({k: str(v) for k, v in fields.items()})
    m["mention"]["candidate_key"] = "|".join(parts[f] for f in inputs.CANDIDATE_KEY_FIELDS)
    m["mention"]["match_start"], m["mention"]["match_end"] = inputs.candidate_match(m["mention"]["candidate_key"])


class Rework3Test(unittest.TestCase):

    def test_same_csv_other_location_same_version_and_bytes(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        other = os.path.join(tmp, "다른위치", "SNP-SAMPLE")
        shutil.copytree(SAMPLE_DIR, other)
        k1, k2 = sample(), check_kg.load_dir(other, "SNP-SAMPLE")
        self.assertEqual(build.dump_bytes(k1), build.dump_bytes(k2))
        a, b = build.build_kg(k1, [pid_graph()]), build.build_kg(k2, [pid_graph()])
        self.assertEqual(a["kg_version"], b["kg_version"])
        self.assertEqual(build.dump_bytes(a), build.dump_bytes(b))
        self.assertNotIn(SAMPLE_DIR, build.dump_bytes(a).decode("utf-8"))

    def test_existing_version_folder_not_overwritten(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        k1 = sample()
        kg1 = build.build_kg(k1, [pid_graph()])
        k2 = sample()
        k2["nodes"][0]["reason"] = "변경"
        kg2 = build.build_kg(k2, [pid_graph()])
        build.write_outputs(tmp, k1, kg1)
        build.write_outputs(tmp, k2, kg2)
        self.assertEqual(build.load_outputs(tmp)[1]["kg_version"], kg2["kg_version"])
        # 같은 내용으로 v1을 다시 쓰면 폴더는 그대로 두고 포인터만 v1로
        v1_file = os.path.join(tmp, kg1["kg_version"], "knowledge_graph.json")
        mtime = os.stat(v1_file).st_mtime_ns
        with mock.patch.object(build, "write_json_atomic", wraps=build.write_json_atomic) as w:
            build.write_outputs(tmp, k1, kg1)
        self.assertEqual([os.path.basename(c.args[0]) for c in w.call_args_list], ["current.json"])
        self.assertEqual(os.stat(v1_file).st_mtime_ns, mtime)
        self.assertEqual(build.load_outputs(tmp)[1]["kg_version"], kg1["kg_version"])
        # 같은 버전 폴더에 다른 내용이 있으면 오류, 파일·포인터는 그대로
        with open(v1_file, "ab") as fh:
            fh.write(b" ")
        with open(v1_file, "rb") as fh:
            tampered = fh.read()
        build.write_outputs(tmp, k2, kg2)  # 포인터를 v2로
        with self.assertRaises(ValueError):
            build.write_outputs(tmp, k1, kg1)
        with open(v1_file, "rb") as fh:
            self.assertEqual(fh.read(), tampered)
        self.assertEqual(build.load_outputs(tmp)[1]["kg_version"], kg2["kg_version"])
        self.assertFalse(any(n.endswith(".partial") for n in os.listdir(tmp)))

    def test_codex_repro_target_ref_by_source_object_id_position_checked(self):
        # to = graph:RC-PV101, 후보 키 target_ref = graph#n12(같은 대상), 위치 0:1 -> 태그와 다름 -> K6 차단
        k = sample()
        m = pv101_mention(k)
        set_key(m, target_ref="graph-SNP-M-102#n12", match_start=0, match_end=1)
        self.assertEqual(keys(build.build_kg(k, [pid_graph()])), [("K6", "invalid_match_position", m["id"])])
        # #source_object_id 참조만 있어도 노드 태그(RC-PV101)를 찾아 위치 문자열과 비교: 올바른 위치면 통과
        k = sample()
        m = pv101_mention(k)
        m["to"] = "graph-SNP-M-102#n12"
        set_key(m, target_ref="graph-SNP-M-102#n12")
        self.assertEqual(build.build_kg(k, [pid_graph()])["validation"]["status"], "passed")
        set_key(m, match_start=0, match_end=1)
        self.assertEqual(keys(build.build_kg(k, [pid_graph()])), [("K6", "invalid_match_position", m["id"])])

    def test_target_mismatch_between_to_and_candidate_key(self):
        cases = {
            "키 target_ref가 다른 설비": dict(target_ref="graph-SNP-M-102:RC-PT110"),
            "키 #참조가 다른 객체": dict(target_ref="graph-SNP-M-102#n16"),
            "키 target_graph_id가 다름": dict(target_graph_id="graph-SNP-M-101"),
        }
        for label, fields in cases.items():
            with self.subTest(case=label):
                k = sample()
                m = pv101_mention(k)
                set_key(m, **fields)
                self.assertEqual(keys(build.build_kg(k, [pid_graph()])), [("K6", "mention_target_mismatch", m["id"])])
                m["knowledge_status"] = "hypothesis"
                self.assertEqual(build.build_kg(k, [pid_graph()])["validation"]["status"], "passed")

    def test_candidate_key_must_agree_with_row_values(self):
        # Codex 4차 재현: 키의 target_graph_version만 다르고 to는 #n12, 키 target_ref는 다른 설비 -> 차단
        k = sample()
        m = pv101_mention(k)
        m["to"] = "graph-SNP-M-102#n12"
        set_key(m, target_ref="graph-SNP-M-102:RC-PIC110", target_graph_version="v-000000000000")
        self.assertEqual(keys(build.build_kg(k, [pid_graph()])), [("K6", "mention_key_mismatch", m["id"])])
        for field, value in (("chunk_id", "chunk-999"), ("text_sha256", "0" * 64), ("material_id", "mat-x"),
                             ("registration_version", "r9"), ("target_source_object_id", "n16")):
            with self.subTest(field=field):
                k = sample()
                m = pv101_mention(k)
                set_key(m, **{field: value})
                got = keys(build.build_kg(k, [pid_graph()]))
                self.assertIn(("K6", "mention_key_mismatch", m["id"]), got)

    def test_changed_chunk_text_rechecks_before_position_check(self):
        k = sample()
        k["nodes"][1]["text"] = "짧은 문장(가상)."  # chunk-001: 기록 위치 47:55가 원문 밖이 됨
        kg = build.build_kg(k, [pid_graph()])
        self.assertEqual(kg["validation"]["status"], "passed")
        l = next(x for x in kg["links"] if x["kind"] == "mentions" and x["from"] == "chunk-001")
        self.assertEqual(l["recheck"]["changed"], ["text_sha256"])
        self.assertIn("recheck_required", l["compute_view"]["excluded_reasons"])
        self.assertFalse(l["compute_view"]["v4"])
        self.assertIn(("recheck_required", l["id"]), [(u["check"], u["target"]) for u in kg["validation"]["unknowns"]])


if __name__ == "__main__":
    unittest.main()
