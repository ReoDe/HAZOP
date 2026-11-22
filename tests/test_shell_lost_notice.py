"""다시 추출 뒤 찾지 못한 구성요소(묘비)의 확인 필요 알림(구간·결과 패널의 읽기). 실행: python -m unittest tests.test_shell_lost_notice

엔진(hazop.study.idmap.needs_check)이 센 값을 구간 목록 머리(check)·구간 행(lost)과 분석 결과 머리(check)·행(lost, lost_refs)이 그대로 싣고,
묘비 id(lost:…)는 응답 어디에도 날것으로 나가지 않는다.
"""

import json
import unittest

from hazop.study import idmap
from hazop.study import nodes as sn
from hazop.study import results as res
from hazop import store_io
from tests.test_shell_results import Base


class LostNoticeTest(Base):
    def setUp(self):
        super().setUp()
        self.tomb = idmap.tomb_id(self.ns["graph_id"], "v1", "x-1")
        ns = self.ns
        ns["tombstones"] = {self.tomb: {"entity_id": "entity-gone", "ref": None, "mark": None, "basis": None, "lost_from": "v0",
                                        "lost_at": "v1", "at": None, "legacy_key": None, "found": None}}
        ns["nodes"][0]["lost"] = [self.tomb]
        sn.save(ns)
        doc = self.doc
        cell = next(c for c in doc["cells"] if c["node_id"] == "S1" and c["entries"])
        cell["entries"][0]["cause_refs"] = [{"ref": self.tomb}]
        res.save_fp(doc, self.project, expect=store_io.ANY)

    def test_nodes_list_shows_the_lost_count_and_the_project_summary(self):
        s = self.read("nodes")
        rows = {n["node_id"]: n for n in s["nodes"]}
        self.assertEqual(rows["S1"]["lost"], 1)
        self.assertEqual(rows["S2"]["lost"], 0)
        self.assertTrue(s["check"]["needs_check"])
        self.assertEqual(s["check"]["lost_members"], {"S1": 1})

    def test_results_header_and_rows_show_lost_members_and_refs_to_check(self):
        s = self.read("results")
        rows = {n["node_id"]: n for n in s["nodes"]}
        self.assertEqual((rows["S1"]["lost"], rows["S1"]["lost_refs"]), (1, 1))
        self.assertEqual((rows["S2"]["lost"], rows["S2"]["lost_refs"]), (0, 0))
        self.assertTrue(s["check"]["needs_check"])
        self.assertEqual(s["check"]["lost_refs"], {"S1": 1})

    def test_no_tombstone_id_reaches_the_screen_data(self):
        for parts in (("nodes",), ("results",), ("nodes", "node", "S1")):
            raw = json.dumps(self.read(*parts), ensure_ascii=False)
            self.assertNotIn("lost:", raw, parts)

    def test_a_clean_project_asks_for_nothing(self):
        ns = self.ns
        ns["tombstones"] = {}
        ns["nodes"][0]["lost"] = []
        sn.save(ns)
        doc = self.doc
        for c in doc["cells"]:
            for e in c["entries"]:
                e["cause_refs"] = []
        res.save_fp(doc, self.project, expect=store_io.ANY)
        self.assertFalse(self.read("nodes")["check"]["needs_check"])
        self.assertFalse(self.read("results")["check"]["needs_check"])


if __name__ == "__main__":
    unittest.main()
