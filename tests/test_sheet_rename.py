"""시트 정체 U5 재현 시험: 번호 없이 등록한 도면(임시 이름 graph-<자료>-p<쪽>)에 구간을 만든 뒤 표제란 번호를 확정·취소·바꾸면
같은 자료의 1:1 이름 바뀜을 판 이전이 잇는다. 근거: docs/units/2026-11-13-drawing-knowledge/evidence/sheet-rename-design.md.

가상 도면 SNP의 원본을 임시 작업 루트·저장 루트에 등록하고 실제로 추출한다. 판정은 '같은 자료의 같은 기호로 이어지고 묘비가 없으며
내용이 같으면 확정이 그대로'이고, 증명하지 못하면(짝 없음) 전처럼 묘비다. 자료가 다른 시트로는 잇지 않는다.
실행: python -m unittest tests.test_sheet_rename
"""

import json
import os
import unittest
from unittest import mock

from tests.test_sheet_guard import GuardCase
from tests.test_titleblock import BY, P

from hazop import paths, store_io
from hazop.app import data, project_ctx
from hazop.register import registry, titleblock as tb
from hazop.study import follow, idmap, migrate, nodes


class RenameCase(GuardCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(data.set_graph_listener, None)

    def set_path(self):
        return os.path.join(nodes.store_dir(), paths.safe_name(P), "project-%s.json" % paths.safe_name(P))

    def stored(self):
        with open(self.set_path(), encoding="utf-8") as fh:
            return json.load(fh)

    def confirm_node(self, i=0):
        n = nodes.load(project_ctx.project_graph(P))["nodes"][i]
        self.nodes_cmd("confirm", {"node_ids": [n["node_id"]], "targets": [{"node_id": n["node_id"], "rev": n["rev"], "state": n["state"]}]})
        return nodes.load(project_ctx.project_graph(P))["nodes"][i]

    def made(self, mid, confirm=True):
        """그 도면에 확정 구간 하나. 반환 (구간, 지금 시트 이름)."""
        self.make_nodes(mid)
        n = self.confirm_node() if confirm else nodes.load(project_ctx.project_graph(P))["nodes"][0]
        return n, self.sheet(mid)["graph_id"]

    def followed(self, before, old, new):
        """구간이 이름만 바뀐 같은 구성원으로 이어졌고 묘비가 없다."""
        pg, n = self.node()
        ids = {x["entity_id"] for x in pg["nodes"]}
        want = sorted(m.replace(old + "/", new + "/", 1) for m in before["members"])
        self.assertEqual((sorted(n["members"]), n.get("lost") or []), (want, []))
        self.assertTrue(set(want) <= ids, "새 이름의 살아 있는 구성요소")
        return n

    def last_line(self):
        return migrate.lines(nodes.load(project_ctx.project_graph(P)))[-1]


class RenameTest(RenameCase):
    def test_r1_numbering_an_unnumbered_pdf_keeps_its_confirmed_segment(self):
        a = self.add("SNP-M-101", "pdf")
        before, old = self.made(a)
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-101"})["ok"])
        n = self.followed(before, old, "graph-SNP-M-101")
        self.assertEqual((n["state"], n["rev"]), (before["state"], before["rev"]), "내용이 같으면 확정 그대로")
        self.assertEqual(self.last_line()["sheets"], {old: "graph-SNP-M-101"})
        text = migrate.notice(nodes.load(project_ctx.project_graph(P)))
        self.assertIn("번호 미확정 도면 → SNP-M-101", text)
        self.assertIn("확정은 그대로", text)

    def test_r2_drawio_refs_move_to_the_new_name(self):
        a = self.add("SNP-M-101", "drawio")
        before, old = self.made(a)
        refs = self.stored()["graph_member_refs"]
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-101"})["ok"])
        n = self.followed(before, old, "graph-SNP-M-101")
        self.assertEqual(n["state"], "confirmed")
        moved = self.last_line()["ref_moved"]
        for m in before["members"]:
            self.assertEqual(moved[refs[m]], refs[m].replace(old + "#", "graph-SNP-M-101#"))

    def test_r3_results_and_project_documents_follow_the_new_name(self):
        """⑤ 결과(원인 참조·근거 경로), ⑥ 초기사건 대상, FMEA 행, 잠재 후보 판단이 읽는 길(migrate_results·follow.catch_up)로 새 이름을 따라간다."""
        a = self.add("SNP-M-101", "pdf")
        before, old = self.made(a)
        ns = self.stored()
        ref = ns["graph_member_refs"][before["members"][0]]
        m0, m1 = before["members"][:2]
        mark = {ns["graph_id"]: {"graph_version": ns["graph_version"], "step": len(migrate.lines(ns))}}
        result = {"schema_version": "0.3", "graph_id": ns["graph_id"], "graph_version": ns["graph_version"],
                  "version_migrations": [{"step": len(migrate.lines(ns)), "to": ns["graph_version"]}],
                  "cells": [{"node_id": before["node_id"], "entries": [{"cause_refs": [{"ref": ref}, {"ref": old + "#pdf-p0-sym-9999"}],
                                                                       "ai_basis": {"kg_paths": [[m0, m1]]}}]}]}
        docs = {idmap.IE: {"headings": {"h1": {"targets": [ref]}}, "ref_versions": mark},
                idmap.FMEA: {"rows": {"r1": {"ref": ref, "entity_id": m0}}, "ref_versions": mark},
                idmap.LATENT: {"judgements": {"rule-1|" + ref: {"key": "rule-1|" + ref, "target": ref}}, "ref_versions": mark}}
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-101"})["ok"])
        self.followed(before, old, "graph-SNP-M-101")
        new_ref = ref.replace(old + "#", "graph-SNP-M-101#")
        new0, new1 = (m.replace(old + "/", "graph-SNP-M-101/") for m in (m0, m1))
        now = nodes.load(project_ctx.project_graph(P))
        got, _n = migrate.migrate_results(result, now)
        e = got["cells"][0]["entries"][0]
        self.assertEqual((e["cause_refs"][0]["ref"], e["ai_basis"]["kg_paths"]), (new_ref, [[new0, new1]]))
        self.assertTrue(idmap.is_tomb(e["cause_refs"][1]["ref"]), "판 사진에 없던 옛 이름 참조는 그대로 지나가지 않고 묘비")
        ie, _r = follow.catch_up(docs[idmap.IE], idmap.IE, P)
        fmea, _r = follow.catch_up(docs[idmap.FMEA], idmap.FMEA, P)
        latent, _r = follow.catch_up(docs[idmap.LATENT], idmap.LATENT, P)
        self.assertEqual(ie["headings"]["h1"]["targets"], [new_ref])
        self.assertEqual((fmea["rows"]["r1"]["ref"], fmea["rows"]["r1"]["entity_id"]), (new_ref, new0))
        self.assertEqual(list(latent["judgements"]), ["rule-1|" + new_ref])
        self.assertEqual(ie["ref_versions"][ns["graph_id"]]["graph_version"], now["graph_version"], "문서 판 표지가 따라옴")

    def test_r4_unconfirming_the_number_follows_back_to_the_temporary_name(self):
        a = self.numbered("SNP-M-101", "pdf")
        before, old = self.made(a)
        self.assertTrue(tb.unconfirm(P, a, ["drawing_number"], BY, ver=self.row(a)["ver"])["ok"])
        new = self.sheet(a)["graph_id"]
        self.assertEqual(new, "graph-%s-p0" % a)
        self.assertEqual(self.followed(before, old, new)["state"], "confirmed")

    def test_r5_changing_the_number_follows(self):
        a = self.numbered("SNP-M-101", "drawio")
        before, old = self.made(a)
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-555"})["ok"])
        self.assertEqual(self.followed(before, old, "graph-SNP-M-555")["state"], "confirmed")

    def test_r11_two_files_swapping_numbers_each_keep_their_own_segment(self):
        """두 파일이 번호를 맞바꾸고 그사이 집합을 읽지 않으면 한 판 이전에 A→B·B→A가 함께 든다. 한꺼번에 바꾸므로 각 구간이 제 자료를 따라간다."""
        a = self.numbered("SNP-M-101", "drawio")
        b = self.numbered("SNP-M-102", "drawio")
        first, _g = self.made(a)
        self.make_nodes(b)
        pg = project_ctx.project_graph(P)
        second = nodes.load(pg)["nodes"][1]
        data.set_graph_listener(None)   # 확정마다 이어서 하던 판 이전을 하지 않음(집합을 읽지 않음)
        for mid, number in ((a, "SNP-M-999"), (b, "SNP-M-101"), (a, "SNP-M-102")):
            self.assertTrue(self.confirm(mid, {"drawing_number": number})["ok"], number)
        self.assertEqual(self.stored()["graph_version"], pg["graph_version"], "시험 전제: 그사이 집합을 쓰지 않음")
        pg = project_ctx.project_graph(P)
        got = {n["node_id"]: n for n in nodes.load(pg)["nodes"]}
        swap = {"graph-SNP-M-101/": "graph-SNP-M-102/", "graph-SNP-M-102/": "graph-SNP-M-101/"}
        for before in (first, second):
            want = sorted(swap[m[:m.index("/") + 1]] + m.split("/", 1)[1] for m in before["members"])
            self.assertEqual((sorted(got[before["node_id"]]["members"]), got[before["node_id"]].get("lost") or []), (want, []))
        self.assertEqual(self.last_line()["sheets"], {"graph-SNP-M-101": "graph-SNP-M-102", "graph-SNP-M-102": "graph-SNP-M-101"})

    def test_a_new_file_in_the_place_of_a_vanished_sheet_is_not_a_pair(self):
        """이름만 보면 사라진 시트와 새로 들어온 시트가 1:1로 보여도, 자료가 다르면 짝이 아니다(다른 파일 기호로 잇지 않음)."""
        self.numbered("SNP-M-102", "drawio")
        a = self.add("SNP-M-101", "pdf")
        before, old = self.made(a)
        data.set_graph_listener(None)
        folder = os.path.join(paths.output_root("graph"), self.sheet(a)["name"])
        os.replace(os.path.join(folder, "graph.json"), os.path.join(folder, "graph.superseded.json"))
        self.numbered("SNP-M-201", "drawio")
        _pg, n = self.node()
        self.assertEqual(self.last_line()["sheets"], {})
        self.assertEqual((n["members"], len(n.get("lost") or [])), ([], len(before["members"])))

    def test_r16_old_snapshot_without_materials_has_no_proof(self):
        """판이 이미 다르고 판 사진에 시트 자료가 없는 옛 집합은 짝을 증명하지 못해 전처럼 묘비다(가드가 막는 경우를 엔진도 지킨다)."""
        a = self.add("SNP-M-101", "pdf")
        before, _old = self.made(a)
        ns = self.stored()
        ns.pop("graph_member_sheets")
        ns["graph_version"] = "pv-old"
        store_io.write_json(self.set_path(), ns, store_io.ANY, sort_keys=False)
        data.set_graph_listener(None)
        with mock.patch.object(tb, "_guard_number", lambda *a, **k: ([], [], {}, [], {})), \
                mock.patch.object(data, "prepare_reextract", lambda *a, **k: False):   # 가드·표지 채우기가 막거나 메우는 경우(test_sheet_guard R16): 엔진만 본다
            self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-101"})["ok"])
        _pg, n = self.node()
        self.assertEqual((n["members"], len(n.get("lost") or [])), ([], len(before["members"])))


class InterruptTest(RenameCase):
    """끊김 수렴(R8·R9): 표제란 확정 차례의 쓰기 직전·직후에 끊겨도 다시 읽으면 끊기지 않은 흐름과 같은 끝이고, 그 전에는 화면이 낡음으로 막는다."""

    def _confirmed_without_catch_up(self):
        a = self.add("SNP-M-101", "pdf")
        before, old = self.made(a)
        data.set_graph_listener(None)   # 판 이전 전에 끊김: 확정·다시 추출은 끝났고 집합은 옛 판
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-101"})["ok"])
        return before, old

    def _blocked_before_catch_up(self, before, old):
        """집합이 옛 판이면 화면(검토구간·⑤)이 낡음을 알리고 ⑥ 쓰기는 Stale로 거절한다. 옛 이름 참조는 어느 살아 있는 구성요소도 가리키지 않는다."""
        pg = project_ctx.project_graph(P)
        saved, _fp = nodes.load_fp(pg)
        self.assertTrue(migrate.unwritten(saved, pg), "화면이 '판 이전을 저장하지 못함'을 띄움")
        with self.assertRaises(follow.Stale):
            follow.mark_for({"ref_versions": {saved["graph_id"]: {"graph_version": saved["graph_version"], "step": 1}}},
                            saved["graph_id"], pg["graph_version"])
        ids = {x["entity_id"] for x in pg["nodes"]}
        self.assertFalse(set(before["members"]) & ids, "옛 이름 구성원이 다른 기호를 가리키지 않음")

    def test_r8_failing_right_before_writing_the_set_converges(self):
        before, old = self._confirmed_without_catch_up()
        real = store_io.write_json

        def boom(path, *a, **k):
            if path == self.set_path():
                raise OSError("쓰기 직전 끊김")
            return real(path, *a, **k)
        with mock.patch.object(store_io, "write_json", boom):
            pg = project_ctx.project_graph(P)
            nodes.load(pg)
            self._blocked_before_catch_up(before, old)
        self.followed(before, old, "graph-SNP-M-101")
        first = self.stored()
        self.node()
        self.assertEqual(self.stored(), first, "두 번 읽어도 한 번과 같음")
        self.assertEqual(self.stored()["nodes"][0]["state"], "confirmed")

    def test_r8_failing_right_after_writing_the_set_converges(self):
        before, old = self._confirmed_without_catch_up()
        real = store_io.write_json

        def written_then_boom(path, *a, **k):
            out = real(path, *a, **k)
            if path == self.set_path():
                raise OSError("쓰기 직후 끊김")
            return out
        with mock.patch.object(store_io, "write_json", written_then_boom):
            nodes.load(project_ctx.project_graph(P))
        n = self.followed(before, old, "graph-SNP-M-101")
        self.assertEqual((n["state"], len(migrate.lines(self.stored()))), ("confirmed", 1))
        first = self.stored()
        self.node()
        self.assertEqual(self.stored(), first, "두 번 읽어도 한 번과 같음")

    def test_r9_killed_while_reextracting_then_reextracted_recovers_the_members(self):
        """끊김 ③: 앞 그래프를 비켜 둔 뒤 다시 추출 중에 프로세스가 죽으면(_put_back이 돌지 않음) 그 시트 없이 집합을 읽어 구성원이 묘비가 된다.
        다시 추출하면 묘비 기록의 자료로 새 이름 시트에서 되찾는다(확정은 '되찾음' 재확인)."""
        self.numbered("SNP-M-201", "drawio")   # 프로젝트 그래프가 그 시트 없이도 지어지게
        a = self.add("SNP-M-101", "pdf")
        before, old = self.made(a)

        def killed(_path):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.confirm(a, {"drawing_number": "SNP-M-101"}, extract=killed)
        _pg, n = self.node()
        self.assertEqual((n["members"], len(n.get("lost") or [])), ([], len(before["members"])), "시험 전제: 시트가 빠져 묘비")
        rec, _p = registry.latest(P, a)
        data.extract_and_graph(registry.Store(paths.store_root(), P).snapshot_path(a, rec["registration_version"]))
        n = self.followed(before, old, "graph-SNP-M-101")
        self.assertIn("되찾음", self.last_line()["recheck"][n["node_id"]])


class OldTombTest(RenameCase):
    """R10: U2 시기(2e8aa24~U5)에 이름이 바뀌며 묘비가 된 되돌리기 묶음 구성원을 다음 판 이전이 되찾는다(그 이름이 사라졌으면 잃을 때 자료의 시트에서).
    자료가 다른 시트로는 옮기지 않는다."""

    def _u2_era(self, a, new_number, then=None):
        before, old = self.made(a, confirm=False)
        batch = self.remove_node()
        real = idmap.compute

        def u2_era(ns, graph, at=None):   # 2e8aa24: 짝이 없고, 이 묘비들은 자료로 옮겨 찾지 않음
            return real(dict(ns, tombstones={}), graph, at)
        with mock.patch.object(idmap, "sheet_pairs", lambda *a: {}), mock.patch.object(idmap, "compute", u2_era):
            self.assertTrue(self.confirm(a, {"drawing_number": new_number})["ok"])
            if then:
                then()
            ns = self.stored()
            for rec in ns["tombstones"].values():   # 2e8aa24는 표시 묘비에 자료를 적지 않았다
                if idmap.valid_mark(rec.get("mark")):
                    rec.pop("material", None)
            store_io.write_json(self.set_path(), ns, store_io.ANY, sort_keys=False)
            self.nodes_cmd("undo", {"batch_id": batch})
            _pg, n = self.node()
        self.assertEqual((n["members"], len(n.get("lost") or [])), ([], len(before["members"])), "시험 전제: U2 시기 묘비")
        self.add("SNP-M-201", "drawio")   # 다음 판 이전(프로젝트 그래프 판이 바뀜)
        return before, old

    def test_r10_sequence_tombs_on_the_temporary_name_come_back(self):
        a = self.add("SNP-M-101", "pdf")
        before, old = self._u2_era(a, "SNP-M-101")
        self.followed(before, old, "graph-SNP-M-101")

    def test_r10_source_tombs_never_attach_to_the_file_that_took_the_old_number(self):
        """옛 번호를 다른 파일이 받았으면 그 이름은 새 그래프에 있으므로 자료로 옮기지 않고(그 이름의 주인이 다르다), 자료 검사가 그 파일 기호에 붙지 않게
        막는다. 이 묘비는 사람이 버리거나 다시 고른다."""
        a = self.numbered("SNP-M-101", "drawio")

        def other_takes_the_old_number():
            b = self.add("SNP-M-102", "drawio")
            self.assertTrue(self.confirm(b, {"drawing_number": "SNP-M-101"})["ok"])
        before, _old = self._u2_era(a, "SNP-M-555", other_takes_the_old_number)
        _pg, n = self.node()
        self.assertEqual((n["members"], len(n.get("lost") or [])), ([], len(before["members"])), "101을 받은 다른 파일 기호에 붙지 않음")


class PairRuleTest(unittest.TestCase):
    """짝 규칙(idmap.sheet_pairs) 경계."""

    def graph(self, sheets):
        return {"sheets": [{"graph_id": g, "material_id": m} for g, m in sheets.items()]}

    def test_rename_swap_and_unchanged(self):
        old = {"graph_member_sheets": {"graph-A": "m1", "graph-B": "m2", "graph-C": "m3"}}
        self.assertEqual(idmap.sheet_pairs(old, self.graph({"graph-B": "m1", "graph-A": "m2", "graph-C": "m3"})),
                         {"graph-A": "graph-B", "graph-B": "graph-A"})

    def test_new_name_taken_from_a_name_left_without_a_pair_drops_only_that_pair(self):
        """B를 쓰던 자료가 빠진 자리에 A가 B로 들어오면 그 짝만 버린다(B의 기록이 A에 붙지 않게). 같은 판 이전의 다른 자료 짝 X→Y는 남는다."""
        old = {"graph_member_sheets": {"graph-A": "m1", "graph-B": "m2", "graph-X": "m3"}}
        self.assertEqual(idmap.sheet_pairs(old, self.graph({"graph-B": "m1", "graph-Y": "m3"})), {"graph-X": "graph-Y"})

    def test_a_dropped_pair_leaves_its_old_name_behind_for_the_next_check(self):
        """버린 짝의 옛 이름도 짝 없이 남는 이름이라, 그 이름으로 들어오는 다른 짝도 버린다."""
        old = {"graph_member_sheets": {"graph-A": "m1", "graph-B": "m2", "graph-C": "m3"}}
        self.assertEqual(idmap.sheet_pairs(old, self.graph({"graph-B": "m1", "graph-A": "m3"})), {})

    def test_new_name_seen_only_in_old_refs_drops_the_pairs(self):
        old = {"graph_member_sheets": {"graph-A": "m1"}, "graph_member_refs": {"graph-B/entity-1": "graph-B#x"}}
        self.assertEqual(idmap.sheet_pairs(old, self.graph({"graph-B": "m1"})), {})

    def test_a_material_on_two_sheets_has_no_pair(self):
        old = {"graph_member_sheets": {"graph-A": "m1", "graph-A2": "m1"}}
        self.assertEqual(idmap.sheet_pairs(old, self.graph({"graph-B": "m1"})), {})


class RelocatePageTest(unittest.TestCase):
    """자료로 옮겨 찾는 묘비(기록의 시트 이름이 사라짐)는 같은 쪽의 시트에서만 찾는다. 여러 쪽 자료의 한 쪽이 빠지면 남은 다른 쪽으로 옮기지 않는다."""
    MID = "material-aaaaaaaaaaaa"

    def compute(self, page_index):
        gid, old_sheet = "project-P", "graph-%s-p0" % self.MID
        mark = ["drawing_object", old_sheet, "pump", "P-1", 0.0, 0.0, 10.0, 10.0]
        ref, eid = old_sheet + "#pdf-p0-sym-0001", old_sheet + "/entity-node-001"
        t = idmap.tomb_id(gid, "v1", idmap.tomb_key(gid, "v0", "v1", eid, ref, mark))
        rec = {"entity_id": eid, "ref": ref, "mark": mark, "basis": "sequence", "lost_from": "v0", "lost_at": "v1", "at": None,
               "legacy_key": None, "found": None}
        ns = {"graph_id": gid, "graph_version": "v1", "graph_member_refs": {}, "tombstones": {t: rec},
              "nodes": [{"node_id": "S1", "members": [], "lost": [t]}]}
        sheet = "graph-SNP-M-101"
        graph = {"graph_id": gid, "graph_version": "v2", "edges": [],
                 "sheets": [{"graph_id": sheet, "material_id": self.MID, "page_index": page_index}],
                 "nodes": [{"entity_id": sheet + "/entity-node-001", "source_object_id": "pdf-p%d-sym-0001" % page_index, "id_basis": "sequence",
                            "node_type": "drawing_object", "sheet": sheet, "kind": "pump", "tag": "P-1", "bbox": [0, 0, 10, 10]}]}
        return t, idmap.compute(ns, graph)

    def test_same_page_is_found(self):
        t, table = self.compute(0)
        self.assertEqual(table["found"][t][0], "graph-SNP-M-101/entity-node-001")

    def test_another_page_of_the_same_material_is_not_found(self):
        _t, table = self.compute(1)
        self.assertEqual(table["found"], {})


if __name__ == "__main__":
    unittest.main()
