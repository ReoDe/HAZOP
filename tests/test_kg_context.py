"""④ 근거 묶음 지식 맥락·kg_version 고정 테스트 C1~C9 (기획서/그래프활용.md §6.4, §7.2).
실행: python -m unittest discover -s tests

검사 본문은 scripts/check_kg_context.py의 c*_problems(빈 목록 = 통과)를 그대로 쓰고, 여기서는 규격의 세부 규칙을
작은 단위로 더 확인한다. 모든 파일은 임시 폴더에 만든다(output/·data/를 바꾸지 않음). 네트워크·실제 AI 호출 없음.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_kg_context as chk  # noqa: E402
from hazop.analysis import ai, run  # noqa: E402
from hazop.kg import build, context  # noqa: E402


class EnvCase(unittest.TestCase):
    def setUp(self):
        self.env = chk.Env()
        self.addCleanup(self.env.close)

    def assertNoProblems(self, fn):
        probs = fn(self.env)
        self.assertEqual(probs, [], "\n".join(probs))


class CheckTest(EnvCase):
    """C1~C9 검사 본문(scripts/check_kg_context.py)."""

    def test_c1_backward_compatible(self):
        self.assertNoProblems(chk.c1_problems)

    def test_c2_scope_schema(self):
        self.assertNoProblems(chk.c2_problems)

    def test_c3_excluded_from_compute(self):
        self.assertNoProblems(chk.c3_problems)

    def test_c4_deterministic(self):
        self.assertNoProblems(chk.c4_problems)

    def test_c5_limits(self):
        self.assertNoProblems(chk.c5_problems)

    def test_c6_input_blocking(self):
        self.assertNoProblems(chk.c6_problems)

    def test_c7_version_pinning(self):
        self.assertNoProblems(chk.c7_problems)

    def test_c8_citation_validation(self):
        self.assertNoProblems(chk.c8_problems)

    def test_c9_trust_boundary(self):
        self.assertNoProblems(chk.c9_problems)


class PointerTest(unittest.TestCase):
    """build.load_outputs_raw: 포인터 한 번 읽기, 필수 키·자료형 검사(ValueError), load_outputs 반환값 유지."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-kgptr-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.graph = chk.sample_graph()
        self.know = chk.sample_knowledge()
        self.kg = build.build_kg(self.know, [self.graph])
        self.root = os.path.join(self.tmp, "kg")
        build.write_outputs(self.root, self.know, self.kg)

    def test_raw_returns_bytes_dir_pointer_and_load_outputs_unchanged(self):
        knowledge, kg, gbytes, ver_dir, ptr = build.load_outputs_raw(self.root)
        self.assertEqual(gbytes, build.dump_bytes(self.kg))
        self.assertEqual(ver_dir, os.path.join(self.root, self.kg["kg_version"]))
        self.assertEqual(ptr["kg_version"], self.kg["kg_version"])
        out = build.load_outputs(self.root)
        self.assertEqual(len(out), 2)
        self.assertEqual(out, (knowledge, kg))

    def test_pointer_read_once(self):
        real_open = open
        seen = []

        def spy(path, *a, **kw):
            seen.append(os.path.basename(str(path)))
            return real_open(path, *a, **kw)
        from unittest import mock
        with mock.patch("builtins.open", spy):
            build.load_outputs_raw(self.root)
        self.assertEqual(seen.count(build.POINTER_FILE), 1)

    def test_missing_or_wrong_type_keys_are_value_errors(self):
        p = os.path.join(self.root, build.POINTER_FILE)
        with open(p, encoding="utf-8") as fh:
            good = json.load(fh)
        bad = [[], {k: v for k, v in good.items() if k != "kg_id"}, dict(good, kg_id=1),
               dict(good, knowledge_sha256="ABC"), dict(good, knowledge_graph_sha256=None),
               {k: v for k, v in good.items() if k != "kg_version"}, dict(good, kg_version=3)]
        for doc in bad:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            with self.assertRaises(ValueError, msg=doc):
                build.load_outputs_raw(self.root)
            with self.assertRaises(ValueError):
                build.load_outputs(self.root)


class ContextUnitTest(unittest.TestCase):
    """context.build_context 세부 규칙(합성 지식그래프)."""

    def test_sort_rank_then_type_then_id(self):
        k, _ = chk.syn_context([("setpt-z", "setpoint", [0], None, 0, []), ("cond-a", "condition", [0], None, 0, []),
                                ("req-b", "requirement", [1], "b", 0, []), ("req-a", "requirement", [0], "a", 0, [])])
        self.assertEqual([it["knowledge_id"] for it in k["items"]], ["req-a", "setpt-z", "cond-a", "req-b"])

    def test_one_item_per_node_with_applies_to_grouped(self):
        k, _ = chk.syn_context([("req-a", "requirement", [3, 1, 2], "a", 2, [])])
        self.assertEqual(len(k["items"]), 1)
        it = k["items"][0]
        self.assertEqual([a["entity_id"] for a in it["applies_to"]],
                         ["entity-s-00001", "entity-s-00002", "entity-s-00003"])
        self.assertEqual([c["chunk_id"] for c in it["specified_in"]], ["chunk-req-a-00", "chunk-req-a-01"])
        self.assertNotIn("text", it["specified_in"][0])
        self.assertEqual(it["evidence_id"], "ev-kg-req-a")
        self.assertEqual(it["knowledge_status"], "confirmed")
        self.assertIsNone(k["truncated"])

    def test_unknown_fields_kept_as_null(self):
        g = chk.syn_graph(2)
        kg = chk.syn_kg(g, [("setpt-a", "setpoint", [0], None, 0, [])])
        kg["nodes"][0].update(value=None, unit=None)
        k, _ = context.build_context(kg, g, [n["entity_id"] for n in g["nodes"]])
        it = k["items"][0]
        self.assertEqual(it["unknown_fields"], ["value", "unit"])
        self.assertIsNone(it["value"])
        self.assertIsNone(it["unit"])

    def test_out_of_scope_conflict_partner(self):
        k, _ = chk.syn_context([("setpt-a", "setpoint", [0], None, 0, ["setpt-b"]),
                                ("setpt-b", "setpoint", [], None, 0, ["setpt-a"])])
        self.assertEqual(k["items"][0]["conflict_outside"], [{"id": "setpt-b", "reason": "out_of_scope"}])

    def test_nodes_outside_scope_ignored(self):
        g = chk.syn_graph(5)
        kg = chk.syn_kg(g, [("req-a", "requirement", [4], "a", 0, [])])
        k, _ = context.build_context(kg, g, ["entity-s-00000", "entity-s-00001"])
        self.assertEqual(k["items"], [])
        self.assertEqual(k["nodes_without_knowledge"], ["entity-s-00000", "entity-s-00001"])

    def test_size_within_limit_after_byte_truncation(self):
        k, too = chk.syn_context([("req-%02d" % i, "requirement", [i], "다" * 5000, 0, []) for i in range(20)])
        self.assertFalse(too)
        self.assertLessEqual(context.serialized_size(k), context.LIMITS["max_bytes"])
        self.assertEqual(k["truncated"]["reason"], "max_bytes")


class ExportTest(EnvCase):
    def test_export_manifest_records_knowledge_graph_and_same_hash(self):
        """근거 묶음 내보내기는 같은 prepare_doc 경로: 묶음 해시가 분석과 같고 manifest input_files에 지식그래프가 남음
        (bundle_export.py는 고치지 않음, 그래프활용 §6.4.3)."""
        from hazop.analysis import bundle_export
        self.env.build_kg()
        ins = self.env.inputs(self.env.region())
        t, selected, bundles = bundle_export.build_export(ins, now=chk.now)
        doc = run.analyze(self.env.inputs(self.env.region()), None, run_id="x", now=chk.now)
        self.assertEqual({c: ai.bundle_sha256(b) for c, b in bundles.items()},
                         {c: ai.bundle_sha256(b) for c, b in doc["evidence_bundles"].items()})
        out = os.path.join(self.env.root, "export")
        manifest = bundle_export._write_export(out, t, ins, selected, bundles,
                                               {c["candidate_id"]: c["candidate_id"] for c in selected})
        self.assertIn("knowledge_graph", [f["role"] for f in manifest["input_files"]])


class ReworkTest(EnvCase):
    """W7 재작업 1회차 지적: CRLF 사본 resume, 구조 오류, 그래프 차단 중복, 목록만 잘린 경우."""

    def test_crlf_copy_resume(self):
        """지식그래프 파일이 CRLF여도(포인터 해시가 그 바이트와 같으면) 사본 바이트 그대로 저장·해시·resume."""
        self.env.build_kg()
        root = self.env.kg_root()
        ptr = chk.load(os.path.join(root, build.POINTER_FILE))
        with open(os.path.join(root, ptr["kg_version"], build.KG_FILE), "rb") as fh:
            data = fh.read().replace(b"\n", b"\r\n")
        chk._replace_kg_file(root, data)
        doc, run_dir = self.env.execute(self.env.region(), run_id="analysis-crlf")
        with open(os.path.join(run_dir, "inputs", "knowledge_graph.json"), "rb") as fh:
            self.assertEqual(fh.read(), data)
        f = next(x for x in doc["analysis_run"]["input_files"] if x["role"] == "knowledge_graph")
        self.assertEqual(f["sha256"], hashlib.sha256(data).hexdigest())
        run.resume(run_dir, ai.FixedResponseClient(chk.KG_RESPONSES), now=chk.now)  # 예외 없음

    def test_structure_errors(self):
        self.env.build_kg()
        root = self.env.kg_root()
        chk._replace_kg_file(root, b"[]")
        with self.assertRaises(ValueError):
            build.load_outputs_raw(root)
        with self.assertRaises(run.InputError):
            self.env.inputs(self.env.region())
        self.assertEqual(context.structure_problems([]), ["최상위가 JSON 객체가 아님(list)"])
        for broken in ({"kg_id": "k"}, {"kg_id": "k", "validation": {"status": "passed"}, "graph_refs": [],
                                         "nodes": [{"id": "x"}], "links": []}):
            ins = run.prepare(*chk._plain_inputs(self.env), knowledge_graph=broken)
            self.assertTrue(ins["blockers"] and all(b.startswith("지식그래프 구조 오류") for b in ins["blockers"]),
                            ins["blockers"])

    def test_blocked_graph_reported_once(self):
        kg = build.build_kg(chk.sample_knowledge(), [self.env.graph])
        args = list(chk._plain_inputs(self.env))
        args[1] = dict(args[1], validation=dict(args[1]["validation"], status="blocked"))
        blockers = run.prepare(*args, knowledge_graph=kg)["blockers"]
        self.assertEqual(sum("passed가 아님" in b for b in blockers), 1, blockers)
        self.assertFalse([b for b in blockers if b.startswith("지식그래프")], blockers)

    def test_list_only_truncation_recorded(self):
        k, _ = chk.syn_context([], n_objects=250)
        t = k["truncated"]
        self.assertEqual((t["reason"], t["reasons"], t["omitted_count"], t["total"]), ("max_list", ["max_list"], 0, 0))
        self.assertEqual(t["affected_entity_ids"], ["entity-s-%05d" % i for i in range(200, 250)])
        self.assertEqual(context.omission_missing(k)["reason"], "범위 노드 분류 목록 일부 생략(max_list)")


class NestedStructureTest(EnvCase):
    """재작업 2회차: 중첩 구조 오류는 예외가 아니라 blockers '지식그래프 구조 오류: …'."""

    CASES = {
        "node source=[1]": lambda kg: _node(kg, "req-001").update(source=[1]),
        "node compute_view={}": lambda kg: _node(kg, "req-001").update(compute_view={}),
        "link ends.from 없음": lambda kg: _link(kg, "krel-009")["ends"].pop("from"),
        "link ends.from=[1]": lambda kg: _link(kg, "krel-009")["ends"].update({"from": [1]}),
        "node node_type 없음": lambda kg: _node(kg, "req-001").pop("node_type"),
    }

    def blockers(self, kg):
        return run.prepare(*chk._plain_inputs(self.env), knowledge_graph=kg)["blockers"]

    def test_cases_become_blockers(self):
        base = build.build_kg(chk.sample_knowledge(), [self.env.graph])
        self.assertEqual(self.blockers(json.loads(json.dumps(base))), [])
        for label, mutate in self.CASES.items():
            kg = json.loads(json.dumps(base))
            mutate(kg)
            bl = self.blockers(kg)
            self.assertTrue(bl and all(b.startswith("지식그래프 구조 오류: ") for b in bl), (label, bl))

    def test_fallback_catches_missed_errors(self):
        """구조 검사가 놓쳐도 build_context 예외(KeyError·TypeError·AttributeError)를 같은 blockers로 바꾼다."""
        from unittest import mock
        base = build.build_kg(chk.sample_knowledge(), [self.env.graph])
        for label, mutate in self.CASES.items():
            kg = json.loads(json.dumps(base))
            mutate(kg)
            with mock.patch.object(context, "structure_problems", lambda kg: []):
                bl = self.blockers(kg)
            self.assertTrue(bl and all(b.startswith("지식그래프 구조 오류: ") for b in bl), (label, bl))


def _node(kg, nid):
    return next(n for n in kg["nodes"] if n["id"] == nid)


def _link(kg, lid):
    return next(l for l in kg["links"] if l["id"] == lid)


class OmissionTextTest(unittest.TestCase):
    def test_items_and_links_both_cut(self):
        """항목 41개(상한 40)와 한 항목의 연결 21개(상한 20): '항목은 모두 포함'을 붙이지 않음."""
        knodes = [("req-000", "requirement", list(range(21)), "a", 0, [])] + chk.reqs(40, prefix="req-x")
        k, _ = chk.syn_context(knodes)
        t = k["truncated"]
        self.assertEqual(t["reasons"], ["max_items", "per_item_limits"])
        self.assertEqual(context.omission_missing(k)["reason"],
                         "항목 41개 중 40개만 포함(max_items); 적용 설비·인용 연결 일부 생략(per_item_limits)")

    def test_links_only_cut(self):
        k, _ = chk.syn_context([("req-000", "requirement", list(range(21)), "a", 0, [])])
        self.assertEqual(context.omission_missing(k)["reason"], "항목은 모두 포함, 적용 설비·인용 연결 일부 생략(per_item_limits)")


class ClassificationTest(unittest.TestCase):
    """범위 노드 분류(§6.4.2): analyzed_in만 있는 노드, mentions만 있는 노드, out_of_scope 충돌 상대."""

    def test_analyzed_in_only_and_mentions_only(self):
        g = chk.syn_graph(3)
        kg = chk.syn_kg(g, [])
        v4 = {"v4": True, "excluded_reasons": []}

        def pid(i):
            return {"layer": "pid", "graph_id": g["graph_id"], "entity_id": "entity-s-%05d" % i, "tag": "T"}
        kg["nodes"] += [{"id": "case-1", "node_type": "analysis_case", "compute_view": dict(v4), "conflict_with": []},
                        {"id": "chunk-1", "node_type": "doc_chunk", "compute_view": dict(v4), "conflict_with": []}]
        kg["links"] += [
            {"id": "krel-a", "kind": "analyzed_in", "compute_view": dict(v4),
             "ends": {"from": pid(0), "to": {"layer": "knowledge", "ref": "case-1", "node_type": "analysis_case"}}},
            {"id": "krel-m", "kind": "mentions", "compute_view": dict(v4),
             "ends": {"from": {"layer": "knowledge", "ref": "chunk-1", "node_type": "doc_chunk"}, "to": pid(1)}}]
        k, _ = context.build_context(kg, g, [n["entity_id"] for n in g["nodes"]])
        self.assertEqual(k["items"], [])                                   # analyzed_in은 항목이 아님
        self.assertEqual(k["nodes_without_knowledge"], ["entity-s-00002"])  # analyzed_in만 있으면 '입력 없음' 아님
        self.assertEqual(k["nodes_with_gap"], ["entity-s-00001"])           # mentions만 있으면 적용 근거 공백
        self.assertEqual(k["excluded"]["links_not_in_v4"], 0)

    def test_out_of_scope_and_not_in_v4_partners(self):
        k, _ = chk.syn_context([("setpt-a", "setpoint", [0], None, 0, ["setpt-b", "setpt-c"]),
                                ("setpt-b", "setpoint", [], None, 0, ["setpt-a"]),
                                ("setpt-c", "setpoint", [0], None, 0, ["setpt-a"])])
        self.assertEqual([it["knowledge_id"] for it in k["items"]], ["setpt-a", "setpt-c"])
        a = k["items"][0]
        self.assertEqual(a["conflict_with"], ["setpt-c"])
        self.assertEqual(a["conflict_outside"], [{"id": "setpt-b", "reason": "out_of_scope"}])


class PromptTest(unittest.TestCase):
    def test_rule_11_and_template_version(self):
        self.assertEqual(ai.TEMPLATE_VERSION, "4")
        self.assertIn("11. knowledge_context가 있으면", ai.SYSTEM_PROMPT)
        self.assertEqual(ai.template_info()["template_version"], "4")

    def test_kg_ids_not_in_node_lists(self):
        """지식 노드 ID는 node_ids·safeguard_node_ids·equipment_node_ids에 넣지 않는다."""
        env = chk.Env()
        self.addCleanup(env.close)
        kg = build.build_kg(chk.sample_knowledge(), [env.graph])
        doc = run.prepare_doc(run.prepare(*chk._plain_inputs(env), knowledge_graph=kg), None, run_id="t", now=chk.now)
        kids = {n["id"] for n in kg["nodes"]}
        for b in doc["evidence_bundles"].values():
            for key in ("node_ids", "safeguard_node_ids", "equipment_node_ids", "relation_ids"):
                self.assertFalse(set(b["allowed_ids"][key]) & kids, key)


if __name__ == "__main__":
    unittest.main()
