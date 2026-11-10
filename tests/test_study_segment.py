"""④ 검토구간 분할(C6)·스크리닝(R0~R4) 시험. 근거: 기획서/검토구간-분할설계.md §3·§4.
공개 표면(nodes.propose·screens·편집 연산)으로 관찰할 수 있는 것만 본다."""

import copy
import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.study import nodes as sn, segment  # noqa: E402

AT = "2026-11-09T00:00:00Z"


class G:
    """작은 합성 그래프 만들기. 배관 구간(pipe_segment)이 두 요소를 잇는다."""

    def __init__(self, gid="graph-T", dn="T-1"):
        self.gid, self.dn, self.nodes, self.edges, self.n = gid, dn, [], [], 0

    def add(self, eid, kind, category, tag=None, **kw):
        self.nodes.append(dict({"entity_id": eid, "kind": kind, "category": category, "tag": tag,
                                "label_text": "", "position": None}, **kw))
        return eid

    def pipe(self, a, b, flow=None, **kw):
        self.n += 1
        seg = self.add("s%03d" % self.n, "pipe_segment", "pipe_segment",
                       flow_direction={"from": a, "to": b} if flow else None, **kw)
        for end in (a, b):
            self.edges.append({"entity_id": "e-%s-%s" % (seg, end), "kind": "has_endpoint", "nodes": [seg, end],
                               "segment": seg, "node": end})
        return seg

    def chain(self, start, count, prefix):
        """start에서 T(편차원 아님)를 count개 잇고 마지막 T를 돌려준다."""
        cur = start
        for i in range(count):
            tee = self.add("%s%03d" % (prefix, i), "tee", "piping_element")
            self.pipe(cur, tee)
            cur = tee
        return cur

    def graph(self):
        return {"project_id": None, "graph_id": self.gid, "graph_version": "v1",
                "source": {"drawing_number": self.dn}, "nodes": self.nodes, "edges": self.edges}


def by_member(ns, eid):
    return next(n for n in ns["nodes"] if eid in n["members"])


def kept(ns):
    return [n for n in ns["nodes"] if n["screen"]["status"] != "excluded"]


def phys_connected(ns, graph):
    by = {n["entity_id"]: n for n in graph["nodes"]}
    adj = {}
    for e in graph["edges"]:
        if e["kind"] == "has_endpoint":
            a, b = e["nodes"]
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    for n in kept(ns):
        core = {m for m in n["members"] if by[m]["category"] != "instrument"}
        if not core:
            continue
        start = min(core)
        seen, stack = {start}, [start]
        while stack:
            for x in adj.get(stack.pop(), ()):
                if x in core and x not in seen:
                    seen.add(x)
                    stack.append(x)
        if seen != core:
            return n["node_id"]
    return None


def exactly_once(ns, graph):
    members = [m for n in ns["nodes"] for m in n["members"]]
    return len(members) == len(set(members)) == len(graph["nodes"]) and set(members) == {
        n["entity_id"] for n in graph["nodes"]}


class ScreeningTest(unittest.TestCase):

    def test_tee_only_line_is_attached_to_the_tank(self):
        g = G()
        tank = g.add("a-tank", "tank", "equipment", "TK-1")
        end = g.chain(tank, 3, "t")
        g.add("z-cap", "pipe_cap", "piping_element")
        g.pipe(end, "z-cap")
        graph = g.graph()
        ns = sn.propose(graph, at=AT)
        self.assertEqual(len(ns["nodes"]), 1)
        node = ns["nodes"][0]
        self.assertEqual(node["screen"]["status"], "keep")
        self.assertTrue(node["absorbed"] and all(p["rule"] == "R2" for p in node["absorbed"]))
        self.assertTrue(all(set(p["members"]) <= set(node["members"]) for p in node["absorbed"]))
        sn.confirm(ns, graph, "검사", at=AT)

    def test_isolated_symbols_go_to_one_exclusion_bucket_and_confirm_passes(self):
        g = G()
        tank = g.add("a-tank", "tank", "equipment", "TK-1")
        valve = g.add("b-valve", "manual_valve", "valve", "V-1")
        g.pipe(tank, valve)
        g.add("x-tee", "tee", "piping_element")
        g.add("x-unknown", None, None)
        loop_a, loop_b = g.add("y-tee1", "tee", "piping_element"), g.add("y-tee2", "tee", "piping_element")
        g.pipe(loop_a, loop_b)
        graph = g.graph()
        ns = sn.propose(graph, at=AT)
        bucket = [n for n in ns["nodes"] if n["screen"]["status"] == "excluded"]
        self.assertEqual(len(bucket), 1)
        self.assertEqual(bucket[0]["screen"]["rule"], "R3")
        self.assertEqual(len(bucket[0]["parts"]), 3)
        by = {n["entity_id"]: n for n in graph["nodes"]}
        self.assertFalse(any(segment.is_source(by[m]) for m in bucket[0]["members"]))
        self.assertTrue(exactly_once(ns, graph))
        sn.confirm(ns, graph, "검사", at=AT)

    def test_long_line_beyond_the_cap_stays_as_a_low_segment(self):
        g = G()
        tank = g.add("a-tank", "tank", "equipment", "TK-1")
        g.chain(tank, 70, "t")
        graph = g.graph()
        ns = sn.propose(graph, at=AT)
        self.assertTrue(all(len(n["members"]) <= segment.MERGE_CAP for n in kept(ns)))
        low = [n for n in ns["nodes"] if n["screen"]["status"] == "low"]
        self.assertTrue(low)
        self.assertEqual({(n["screen"]["rule"], n["screen"]["grade"]) for n in low}, {("R4", "낮음")})
        self.assertIsNone(phys_connected(ns, graph))
        self.assertTrue(exactly_once(ns, graph))

    def test_line_goes_to_the_upstream_vessel(self):
        for flow_on_line in (True, False):
            g = G()
            a = g.add("a-tank", "tank", "equipment", "TK-A")
            b = g.add("b-tank", "tank", "equipment", "TK-B")
            tee = g.add("m-tee", "tee", "piping_element")
            g.pipe(a, tee)
            g.pipe(b, tee, flow=True)  # TK-B → T로 흐름(상류는 TK-B)
            ns = sn.propose(g.graph(), at=AT)
            self.assertEqual(by_member(ns, "m-tee"), by_member(ns, "b-tank"), flow_on_line)

    def test_marked_drawing_is_excluded_whole_and_unknown_ids_are_ignored(self):
        g = G()
        tank = g.add("a-tank", "tank", "equipment", "TK-1", sheet="graph-A")
        valve = g.add("b-valve", "manual_valve", "valve", "V-1", sheet="graph-L")
        g.pipe(tank, valve, sheet="graph-A")
        g.add("c-tank", "tank", "equipment", "TK-L", sheet="graph-L")
        graph = dict(g.graph(), sheets=[{"graph_id": "graph-A", "drawing_number": "A"},
                                        {"graph_id": "graph-L", "drawing_number": "L"}])
        ns = sn.propose(graph, at=AT, exclude_sheets={"graph-L", "graph-없음"})
        r0 = [n for n in ns["nodes"] if n["screen"]["rule"] == "R0"]
        self.assertEqual(len(r0), 1)
        self.assertEqual(r0[0]["members"], ["c-tank"])
        self.assertEqual(by_member(ns, "b-valve")["screen"]["status"], "keep")  # 표시 안 한 도면에 걸친 조각은 R0이 아님
        self.assertTrue(exactly_once(ns, graph))

    def test_many_valves_never_make_a_disconnected_segment(self):
        g = G()
        tank = g.add("a-tank", "tank", "equipment", "TK-1")
        hub = g.add("h-tee", "tee", "piping_element")
        g.pipe(tank, hub)
        for i in range(12):
            v = g.add("v%02d" % i, "manual_valve", "valve", "V-%d" % i)
            g.pipe(hub if i % 3 == 0 else "v%02d" % (i - 1), v)
        graph = g.graph()
        ns = sn.propose(graph, at=AT)
        by = {n["entity_id"]: n for n in graph["nodes"]}
        for n in ns["nodes"]:
            self.assertLessEqual(sum(segment.traits(by[m]).weighted for m in n["members"]), segment.MAX_ACTIVE)
        self.assertIsNone(phys_connected(ns, graph))

    def test_long_loop_without_branches_is_cut_into_connected_pieces(self):
        g = G()
        ids = [g.add("n%03d" % i, "manual_valve" if i == 0 else "tee", "valve" if i == 0 else "piping_element")
               for i in range(120)]
        for i in range(120):
            g.pipe(ids[i], ids[(i + 1) % 120])
        graph = g.graph()
        ns = sn.propose(graph, at=AT)
        self.assertIsNone(phys_connected(ns, graph))
        self.assertTrue(exactly_once(ns, graph))

    def test_unattached_instruments_follow_their_drawing_for_r0(self):
        g = G()
        g.add("a-ti", "indicator", "instrument", "TI-A", sheet="graph-A")
        g.add("b-ti", "indicator", "instrument", "TI-B", sheet="graph-B")
        ns = sn.propose(dict(g.graph(), sheets=[{"graph_id": "graph-A", "drawing_number": "A"},
                                               {"graph_id": "graph-B", "drawing_number": "B"}]),
                        at=AT, exclude_sheets={"graph-A"})
        self.assertEqual(by_member(ns, "a-ti")["screen"]["rule"], "R0")
        self.assertEqual(by_member(ns, "b-ti")["screen"]["status"], "keep")

    def test_same_result_regardless_of_input_order(self):
        g = G()
        tank = g.add("a-tank", "tank", "equipment", "TK-1")
        g.chain(tank, 50, "t")
        g.add("x-tee", "tee", "piping_element")
        graph = g.graph()
        base = json.dumps(sn.propose(graph, at=AT), ensure_ascii=False)
        rnd = random.Random(3)
        for _ in range(3):
            shuffled = copy.deepcopy(graph)
            rnd.shuffle(shuffled["nodes"])
            rnd.shuffle(shuffled["edges"])
            self.assertEqual(json.dumps(sn.propose(shuffled, at=AT), ensure_ascii=False), base)

    def test_every_equipment_kind_has_a_part(self):
        from hazop.extract.rules import KIND_CATEGORY
        with open(os.path.join(os.path.dirname(segment.__file__), "..", "kg", "schema", "registry.json"),
                  encoding="utf-8") as fh:
            classes = {c["id"]: c for c in json.load(fh)["classes"]}

        def is_equipment(cid):
            while cid:
                if cid == "equipment":
                    return True
                cid = classes[cid].get("parent")
            return False
        kinds = {c for c in classes if c != "equipment" and is_equipment(c)}
        kinds |= {k for k, c in KIND_CATEGORY.items() if c == "equipment"}
        self.assertEqual(sorted(kinds - set(segment.EQUIPMENT_PART)), [])


class ScreenRecordTest(unittest.TestCase):

    def setUp(self):
        g = G()
        tank = g.add("a-tank", "tank", "equipment", "TK-1")
        end = g.chain(tank, 2, "t")
        g.add("u-cap", "pipe_cap", "piping_element")
        g.pipe(end, "u-cap")
        g.pipe(g.add("c-tank", "tank", "equipment", "TK-2"), g.add("d-valve", "manual_valve", "valve", "V-1"))
        g.add("x-tee", "tee", "piping_element")
        self.graph = g.graph()
        self.ns = sn.propose(self.graph, at=AT)

    def test_old_files_without_screen_read_as_keep(self):
        old = copy.deepcopy(self.ns)
        for n in old["nodes"]:
            for key in ("screen", "absorbed", "parts"):
                n.pop(key, None)
        got = sn.screens(old, self.graph)
        self.assertEqual({s.status for s in got.values()}, {"keep"})
        self.assertTrue(all(s.score is not None for s in got.values()))

    def test_saved_file_from_the_old_proposer_loads_unchanged(self):
        import tempfile
        from hazop import paths
        old = copy.deepcopy(self.ns)
        old["proposer"] = {"name": "hazop.study.nodes", "version": "0.1.0", "max_active": 5}
        for n in old["nodes"]:
            for key in ("screen", "absorbed", "parts"):
                n.pop(key, None)
        old = sn.confirm(old, self.graph, "검토자", at=AT)
        tmp, env = tempfile.mkdtemp(), os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = tmp
        try:
            path = sn.save(old)
            before = open(path, "rb").read()
            self.assertEqual(sn.load(self.graph), old)
            self.assertEqual(open(path, "rb").read(), before)  # 읽기만 하고 다시 쓰지 않는다
        finally:
            if env is None:
                os.environ.pop(paths.ENV_WORK_ROOT, None)
            else:
                os.environ[paths.ENV_WORK_ROOT] = env

    def test_pieces_cut_from_a_long_line_keep_both_boundaries(self):
        from hazop.study import span
        g = G()
        a = g.add("a-tank", "tank", "equipment", "TK-A")
        end = g.chain(a, 100, "t")
        b = g.add("z-tank", "tank", "equipment", "TK-Z")
        g.pipe(end, g.add("v-valve", "manual_valve", "valve", "V-1"))
        g.pipe("v-valve", b)
        graph = dict(g.graph(), sheets=[{"graph_id": "graph-T", "drawing_number": "T-1"}], sheet_links=[])
        for n in span.annotate(sn.propose(graph, at=AT), graph)["nodes"]:
            self.assertTrue(n["boundary"]["start"] and n["boundary"]["end"], n["node_id"])

    def test_merge_with_an_exclusion_bucket_is_refused(self):
        ids = [n["node_id"] for n in self.ns["nodes"]]
        with self.assertRaises(ValueError):
            sn.merge(self.ns, ids, at=AT)

    def test_edits_keep_piece_records_inside_members_and_clear_scores(self):
        keep = next(n for n in self.ns["nodes"] if n["screen"]["status"] == "keep" and n.get("absorbed"))
        moved = keep["absorbed"][0]["members"]
        out = sn.split(self.ns, keep["node_id"], moved, at=AT)
        for n in out["nodes"]:
            for p in n.get("absorbed", []) + n.get("parts", []):
                self.assertTrue(set(p["members"]) <= set(n["members"]))
        changed = [n for n in out["nodes"] if n["node_id"] == keep["node_id"] or n["origin"] == "split"]
        self.assertEqual({n["screen"]["score"] for n in changed}, {None})
        self.assertTrue(all(s.score is not None for s in sn.screens(out, self.graph).values() if s.status != "excluded"))
        self.assertEqual(self.ns, sn.propose(self.graph, at=AT))  # 입력은 바뀌지 않는다

    def test_hand_edits_make_the_judgement_human_and_confirm_guards_rule_buckets(self):
        bucket = next(n for n in self.ns["nodes"] if n["screen"]["status"] == "excluded")
        valve_node = by_member(self.ns, "d-valve")
        moved = sn.add_member(sn.remove_member(self.ns, valve_node["node_id"], "d-valve", at=AT),
                              bucket["node_id"], "d-valve", at=AT)
        self.assertEqual(by_member(moved, "d-valve")["screen"]["by"], "human")
        sn.confirm(moved, self.graph, "검사", at=AT)  # 사람이 옮긴 것은 막지 않는다
        forged = copy.deepcopy(moved)
        by_member(forged, "d-valve")["screen"].update(by="rule", rule="R3")
        with self.assertRaises(ValueError):
            sn.confirm(forged, self.graph, "검사", at=AT)

    def test_malformed_screen_fields_are_rejected_on_load(self):
        import tempfile
        from hazop import paths
        tmp = tempfile.mkdtemp()
        old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = tmp
        try:
            for bad in ({"score": "bad"}, {"by": "robot"}, {"status": "maybe"}):
                doc = copy.deepcopy(self.ns)
                doc["nodes"][0]["screen"].update(bad)
                sn.save(doc)
                with self.assertRaises(ValueError):
                    sn.load(self.graph)
        finally:
            if old is None:
                os.environ.pop(paths.ENV_WORK_ROOT, None)
            else:
                os.environ[paths.ENV_WORK_ROOT] = old

    def test_people_can_override_take_out_and_detach(self):
        bucket = next(n for n in self.ns["nodes"] if n["screen"]["status"] == "excluded")
        with self.assertRaises(ValueError):
            sn.screen_override(self.ns, bucket["node_id"], "excluded", "")
        out = sn.take_out(self.ns, bucket["node_id"], [])
        taken = next(n for n in out["nodes"] if n["node_id"] == bucket["node_id"])
        self.assertEqual((taken["screen"]["status"], taken["screen"]["by"]), ("keep", "human"))
        self.assertIs(sn.screen_override(out, bucket["node_id"], "keep", "다시"), out)  # 같은 판정이면 그대로
        keep = next(n for n in self.ns["nodes"] if n.get("absorbed"))
        piece = keep["absorbed"][0]
        cut = sn.detach(self.ns, keep["node_id"], piece["members"][:1])
        new = by_member(cut, piece["members"][0])
        self.assertNotEqual(new["node_id"], keep["node_id"])
        self.assertEqual((new["screen"]["by"], new["screen"]["reason"]), ("human", "규칙이 붙인 조각을 뗌"))
        self.assertEqual(cut["history"][-1]["op"], "screen_override")
        moved = sn.screen_override(self.ns, keep["node_id"], "excluded", "검토 범위 밖")
        self.assertEqual(moved["history"][-1]["op"], "screen_override")
        sn.confirm(moved, self.graph, "검사", at=AT)  # 사람이 옮긴 제외는 확정을 막지 않는다

    def test_take_out_finds_pieces_by_members_not_by_label(self):
        g = G()
        for i in range(3):
            a, b = g.add("x%da" % i, "tee", "piping_element"), g.add("x%db" % i, "tee", "piping_element")
            g.pipe(a, b)
        g.pipe(g.add("k-tank", "tank", "equipment", "TK"), g.add("k-valve", "manual_valve", "valve", "V"))
        graph = g.graph()
        ns = sn.propose(graph, at=AT)
        bucket = next(n for n in ns["nodes"] if n["screen"]["status"] == "excluded")
        self.assertEqual(len(bucket["parts"]), 3)
        with self.assertRaises(ValueError):  # 서로 다른 조각의 구성요소를 고르면 묶음 전체를 꺼내지 않는다
            sn.take_out(ns, bucket["node_id"], ["x0a", "x1a"])
        first = bucket["parts"][0]
        out = sn.take_out(ns, bucket["node_id"], first["members"][:1])
        self.assertEqual(sorted(by_member(out, first["members"][0])["members"]), sorted(first["members"]))
        rest = by_member(out, bucket["parts"][1]["members"][0])["screen"]
        self.assertEqual((rest["status"], rest["rule"], rest["by"]), ("excluded", "R3", "rule"))  # 남은 묶음은 규칙 판정 그대로
        again, dropped = sn.reapply(out, sn.propose(graph, at=AT))  # 다시 제안해도 꺼낸 조각은 구성요소로 다시 꺼낸다
        self.assertEqual(dropped, [])
        self.assertEqual(by_member(again, first["members"][0])["screen"]["status"], "keep")
        self.assertEqual(by_member(again, bucket["parts"][1]["members"][0])["screen"]["status"], "excluded")
        keeps = [n["node_id"] for n in ns["nodes"] if n["screen"]["status"] == "keep"]
        merged = sn.merge(ns, keeps[:2], at=AT) if len(keeps) > 1 else ns
        self.assertEqual(sn.reapply(merged, sn.propose(graph, at=AT))[1], [])  # 병합은 스크리닝 판정이 아니다
        sn.confirm(out, graph, "검사", at=AT)

    def test_reproposal_reapplies_human_judgements_with_the_same_members(self):
        keep = next(n for n in self.ns["nodes"] if n["screen"]["status"] == "keep")
        moved = sn.screen_override(self.ns, keep["node_id"], "excluded", "검토 범위 밖")
        again, dropped = sn.reapply(moved, sn.propose(self.graph, at=AT))
        self.assertEqual(dropped, [])
        self.assertEqual(by_member(again, keep["members"][0])["screen"]["status"], "excluded")

    def test_map_members_renames_piece_records_too(self):
        keep = next(n for n in self.ns["nodes"] if n.get("absorbed"))
        old = keep["absorbed"][0]["members"][0]
        out = sn.map_members(self.ns, {old: "새-ID"})
        node = by_member(out, "새-ID")
        self.assertIn("새-ID", node["absorbed"][0]["members"])
        self.assertNotIn(old, json.dumps(out))


class ExcludedDrawingsTest(unittest.TestCase):

    def setUp(self):
        import tempfile
        from hazop import paths
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp

    def tearDown(self):
        import shutil
        from hazop import paths
        if self.old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pg(self):
        g = G("project-P")
        g.add("a-tank", "tank", "equipment", "TK-1", sheet="graph-A")
        g.add("l-valve", "manual_valve", "valve", "V-L", sheet="graph-L")
        return dict(g.graph(), project_id="P", sheets=[{"graph_id": "graph-A", "drawing_number": "A-1"},
                                                       {"graph_id": "graph-L", "drawing_number": "1.7-1-S1"}])

    def test_marked_drawing_number_maps_to_its_sheet_and_feeds_r0(self):
        pg = self.pg()
        self.assertEqual(sn.exclusion_for(pg), (frozenset(), None))
        sn.set_excluded("P", "1.7-1-S1", True, "검토자", "범례 도면", at=AT)
        before = open(sn.excluded_path("P"), "rb").read()
        sn.set_excluded("P", "1.7-1-S1", True, "검토자", "다른 사유", at=AT)  # 같은 상태면 파일을 바꾸지 않음
        self.assertEqual(open(sn.excluded_path("P"), "rb").read(), before)
        self.assertEqual(sn.load_excluded("P")["1.7-1-S1"], {"by": "검토자", "reason": "범례 도면", "at": AT})
        self.assertEqual(sn.exclusion_for(pg), (frozenset({"graph-L"}), None))
        ns = sn.propose(pg, at=AT, exclude_sheets=sn.exclusion_for(pg)[0])
        self.assertEqual(by_member(ns, "l-valve")["screen"]["rule"], "R0")
        sn.set_excluded("P", "1.7-1-S1", False, "검토자", at=AT)
        self.assertEqual(sn.exclusion_for(pg), (frozenset(), None))

    def test_marking_every_linked_drawing_excludes_the_link_piece_too(self):
        from tests.test_study_span import two_sheets
        _a, _b, pg, _s = two_sheets()
        ns = sn.propose(pg, at=AT, exclude_sheets={s["graph_id"] for s in pg["sheets"]})
        self.assertEqual({n["screen"]["status"] for n in ns["nodes"]}, {"excluded"})

    def test_marking_needs_a_drawing_number_and_a_name(self):
        with self.assertRaises(ValueError):
            sn.set_excluded("P", "", True, "검토자")
        with self.assertRaises(ValueError):
            sn.set_excluded("P", "A-1", True, " ")

    def test_broken_file_is_reported_not_silently_ignored(self):
        os.makedirs(os.path.dirname(sn.excluded_path("P")), exist_ok=True)
        for text in ("[1]", "{", "", "[" * 100000):
            with open(sn.excluded_path("P"), "w", encoding="utf-8") as fh:
                fh.write(text)
            with self.assertRaises(ValueError):
                sn.load_excluded("P")
            sheets, problem = sn.exclusion_for(self.pg())
            self.assertEqual(sheets, frozenset())
            self.assertIn("읽지 못해", problem)
            self.assertFalse(sn.any_confirmed(project_only=True))  # 다른 파일을 훑는 코드도 깨지지 않는다

    def test_drawing_numbers_are_compared_without_surrounding_spaces(self):
        pg = self.pg()
        pg["sheets"][1]["drawing_number"] = " 1.7-1-s1 "
        sn.set_excluded("P", "1.7-1-S1 ", True, "검토자", at=AT)
        self.assertEqual(sn.exclusion_for(pg)[0], frozenset({"graph-L"}))  # 프로젝트 그래프와 같은 도면 규칙
        self.assertIsNotNone(sn.excluded_mark("P", "1.7-1-s1"))
        sn.set_excluded("P", "1.7-1-s1", False, "검토자", at=AT)
        self.assertEqual(sn.load_excluded("P"), {})

    def test_legend_words_only_suggest(self):
        self.assertTrue(sn.looks_like_legend("001_Ch01_Fig1.7-1_s1of4_Flow_Diagram_Symbols_and_Legend.pdf"))
        self.assertTrue(sn.looks_like_legend(None, "흐름도 기호 및 범례"))
        self.assertFalse(sn.looks_like_legend("025_Ch09_Fig9.2.2-1_s1of4_Component_Cooling_Water_System.pdf"))


if __name__ == "__main__":
    unittest.main()
