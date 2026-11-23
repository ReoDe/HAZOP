"""source 구성요소 묘비(f945ff2)의 검토 지적 재현 시험. 근거: docs/specs/study-node-segmentation.md §2.6,
docs/units/2026-11-13-drawing-knowledge/evidence/sheet-identity-design.md §5.

- 묘비 id는 기록의 겉모습(look) 유무와 상관없이 같다(백업에서 되돌린 집합과 ⑤ 결과가 한 묘비를 듦).
- 같은 파일 id로 되찾은 구간의 재확인 사유는 '같은 자리'가 아니다.
- 집합 수준에서 버린 source 묘비는 되찾지 않는다. 태그 규칙: 기록한 태그가 바뀌면 묘비, 기록에 태그가 없으면 종류만 본다.
- 겉모습 칸이 없는 옛 집합은 열기만으로 다시 쓰지 않고, 다시 추출 직전 표지 채우기(웹 고침 길 포함)에서 채운다.
- 실제 drawio 어댑터 길: 사람 수정으로 지운 기호를 되돌리면 구간이 되찾는다.
실행: python -m unittest tests.test_study_source_tombs
"""

import copy
import json
import unittest

from tests.test_study_idmap import AT, StoreCase, eid, source_drawing
from tests.test_titleblock import BY, P, Base

from hazop.study import migrate
from hazop.study import nodes as sn


NEW_FIELDS = ("graph_member_looks", "graph_member_sheets")   # 나중에 들인 판 사진 칸(idmap.OPTIONAL_SNAPSHOT)


def lost(g1, g2):
    ns = sn.propose(g1, at=AT)
    ns["nodes"] = [dict({"node_id": "S1", "name": "a", "basis": "b", "members": [eid(g1, "TK"), eid(g1, "V1")]},
                        **sn._v2_fields("script"))]
    return ns, migrate.migrate_set(ns, g2, at=AT)[0]


def tagged(version, tag, gone=()):
    g = source_drawing(version, gone=gone)
    for n in g["nodes"]:
        if n.get("_name") == "V1":
            n["tag"] = tag
    return g


class SourceTombReviewTest(StoreCase):
    def test_tomb_id_does_not_depend_on_the_recorded_look(self):
        """겉모습 칸을 채우기 전의 백업으로 집합을 되돌려 다시 셈해도 같은 잃은 기호는 같은 묘비 id다."""
        g1, g2 = source_drawing("v-1"), source_drawing("v-2", gone=("V1",))
        ns, with_look = lost(g1, g2)
        old = copy.deepcopy(ns)
        old.pop("graph_member_looks")
        without = migrate.migrate_set(old, g2, at=AT)[0]
        self.assertEqual(with_look["nodes"][0]["lost"], without["nodes"][0]["lost"], "같은 잃은 기호가 묘비 id 둘로 갈림")

    def test_source_refound_reason_is_not_the_same_place(self):
        _ns, gone = lost(source_drawing("v-1"), source_drawing("v-2", gone=("V1",)))
        why = migrate.plan(gone, source_drawing("v-3"))["recheck"]["S1"]
        self.assertNotIn("같은 자리", why)
        self.assertIn("같은 파일 id", why)

    def test_set_level_discarded_source_tomb_is_not_refound(self):
        _ns, gone = lost(source_drawing("v-1"), source_drawing("v-2", gone=("V1",)))
        t = gone["nodes"][0]["lost"][0]
        gone["nodes"][0]["lost"] = []
        gone["discarded"] = [t]
        out = migrate.migrate_set(gone, source_drawing("v-3"), at=AT)[0]
        self.assertIsNone(out["tombstones"][t]["found"], "집합에서 버린 묘비를 되찾음")

    def test_recorded_tag_that_changed_stays_a_tomb(self):
        _ns, gone = lost(tagged("v-1", "XV-1"), tagged("v-2", "XV-1", gone=("V1",)))
        out = migrate.migrate_set(gone, tagged("v-3", "XV-9"), at=AT)[0]
        self.assertEqual(out["nodes"][0]["lost"], gone["nodes"][0]["lost"], "기록한 태그와 다른 태그로 되찾음")

    def test_tomb_without_a_recorded_tag_looks_at_the_kind(self):
        _ns, gone = lost(tagged("v-1", None), tagged("v-2", None, gone=("V1",)))
        out = migrate.migrate_set(gone, tagged("v-3", "XV-9"), at=AT)[0]
        self.assertFalse(out["nodes"][0].get("lost"), "기록에 태그가 없으면 같은 종류로 되찾음")


class OldSetFillTest(Base):
    def strip(self, mid):
        """f945ff2 전에 저장한 0.3 집합처럼 겉모습·시트 자료 칸을 뺀다."""
        from hazop.app import project_ctx
        path = sn.store_path(P, "project-" + P)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        for k in NEW_FIELDS:
            doc.pop(k, None)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        project_ctx._PROJECT_GRAPHS.clear()
        with open(path, "rb") as fh:
            return path, fh.read()

    def test_opening_does_not_fill_and_reextract_prep_does(self):
        from hazop.app import data, project_ctx
        mid = self.add()
        self.make_nodes(mid)
        path, before = self.strip(mid)
        sn.load(project_ctx.project_graph(P))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before, "같은 판을 열기만 했는데 집합을 다시 씀")
        self.assertTrue(data.prepare_reextract(P))
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertTrue(all(doc.get(k) for k in NEW_FIELDS), "다시 추출 직전에 새 칸을 채우지 않음")

    def test_web_edit_path_fills_before_rebuilding(self):
        from hazop.app import project_ctx
        from hazop.shell import sheet_refresh
        mid = self.add()
        self.make_nodes(mid)
        path, _ = self.strip(mid)
        sheet_refresh.rebuild(self.sheet(mid)["name"])
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertTrue(all(k in doc for k in NEW_FIELDS), "웹 고침 길이 다시 짓기 전에 새 칸을 채우지 않음")
        project_ctx._PROJECT_GRAPHS.clear()

    def test_drawio_symbol_deleted_and_restored_by_a_correction_comes_back(self):
        """실제 drawio 어댑터 길: 구간 구성요소 기호를 사람 수정으로 지웠다가 수정을 되돌리면 같은 파일 id·같은 종류로 되찾는다."""
        from hazop.app import data, project_ctx
        from hazop.extract import confirmation, corrections
        mid = self.add()
        _pg, ns = self.make_nodes(mid)
        members = ns["nodes"][0]["members"]
        name = self.sheet(mid)["name"]
        with open(confirmation.extraction_path(name), encoding="utf-8") as fh:
            ex = json.load(fh)
        target = ex["nodes"][1]["source_object_id"]
        data.save_corrections(name, [corrections.make_op(ex, "delete_node", target, {}, BY, name=name)], BY)
        n = sn.load(project_ctx.project_graph(P))["nodes"][0]
        self.assertEqual(len(n.get("lost") or []), 1, "지운 기호가 묘비가 됨")
        data.save_corrections(name, [], BY)
        n = sn.load(project_ctx.project_graph(P))["nodes"][0]
        self.assertEqual((sorted(n["members"]), n.get("lost") or []), (sorted(members), []), "수정을 되돌리면 되찾음")


if __name__ == "__main__":
    unittest.main()
