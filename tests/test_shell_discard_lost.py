"""찾지 못한 구성요소 버리기(구간 패널 단추 → nodes.discard_lost). 실행: python -m unittest tests.test_shell_discard_lost

다시 추출 뒤 판 이전이 찾지 못한 구성요소(묘비)를 남기면 구간 상세가 그 목록(key·이름)을 주고, 사람이 확인하고 고른 것(또는 모두)을 버린다. 버린 것은
확인 필요에서 빠지고 되돌리기 묶음으로 되살릴 수 있다. 확정·잠금 구간은 locked로 거절하고, 엔진의 거절 글에 든 내부 말(묘비)은 화면에 내보내지 않는다.
저장은 임시 작업 루트에만 한다. 실제 구독 호출 없음.
"""

import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.app import data  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from tests.test_screen_words import BANNED  # noqa: E402
from tests.test_shell_auto_catch_up import Base as AutoBase  # noqa: E402
from tests.test_shell_catch_up import PID  # noqa: E402


class Base(AutoBase):
    def setUp(self):
        super().setUp()
        self.re_extract_losing_v2()
        data.notify_graph_changed(PID)
        s = self.read("nodes")
        self.nid = next(n["node_id"] for n in s["nodes"] if n["lost"])

    def detail(self):
        return self.read("nodes", "node", self.nid)

    def row(self):
        return next(n for n in self.read("nodes")["nodes"] if n["node_id"] == self.nid)

    def cmd(self, name, args, targets=True):
        s = self.read("nodes")
        a = dict(args, project_id=PID, set_rev=s["set_rev"])
        if targets:
            r = self.row()
            a["targets"] = [{"node_id": r["node_id"], "rev": r["rev"], "state": r["state"]}]
        return self.engine.dispatch("nodes." + name, a, project=PID, via_web=True)

    def unconfirm_if_needed(self):
        if self.row()["state"] != "applied":
            out = self.cmd("unconfirm", {"node_ids": [self.nid]})
            self.assertTrue(out["ok"], out)


class DetailTest(Base):
    def test_the_detail_lists_what_was_not_found_without_internal_ids(self):
        d = self.detail()
        self.assertEqual(len(d["lost_items"]), self.row()["lost"])
        text = json.dumps(d["lost_items"], ensure_ascii=False)
        self.assertNotIn("lost:", text, "묘비 id는 화면에 싣지 않는다")
        for x in d["lost_items"]:
            self.assertTrue(x["key"] and x["name"])
        self.assertEqual(d["discarded"], 0)
        for x in d["lost_items"]:
            self.assertNotIn("#", x["name"], "안정 참조(graph-…#n16) 같은 내부 ID를 이름으로 쓰지 않는다")
            self.assertNotIn("lost_at", x, "판 이름(pv-…)은 화면에 내지 않는다")

    def test_a_reference_name_becomes_the_drawing_number(self):
        from hazop.shell import api_nodes
        self.assertEqual(api_nodes.lost_name("graph-SNP-M-102#n16", "graph-SNP-M-102#n16"), "SNP-M-102 도면의 구성요소(이름 모름)")
        self.assertEqual(api_nodes.lost_name("밸브 RC-V010", "graph-SNP-M-102#n16"), "밸브 RC-V010")


class DiscardTest(Base):
    def test_discarding_picked_items_leaves_the_rest_and_can_be_undone(self):
        self.unconfirm_if_needed()
        items = self.detail()["lost_items"]
        out = self.cmd("discard_lost", {"node_id": self.nid, "keys": [items[0]["key"]]})
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"]["batch_id"], "되돌리기 묶음으로 남는다")
        d = self.detail()
        self.assertEqual(len(d["lost_items"]), len(items) - 1)
        self.assertEqual(d["discarded"], 1)
        self.assertEqual(self.read("nodes")["check"]["discarded"].get(self.nid), 1)
        undo = self.cmd("undo", {"batch_id": out["data"]["batch_id"]}, targets=False)
        self.assertTrue(undo["ok"], undo)
        self.assertEqual(len(self.detail()["lost_items"]), len(items), "되돌리면 다시 찾지 못한 목록에 든다")

    def test_without_keys_everything_left_is_discarded(self):
        self.unconfirm_if_needed()
        out = self.cmd("discard_lost", {"node_id": self.nid})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.detail()["lost_items"], [])
        self.assertEqual(self.row()["lost"], 0)
        history = sn.read_as_is(self.g)["history"]
        self.assertEqual(history[-1]["op"], "discard_lost")
        self.assertEqual(history[-1]["detail"]["by"], "검토자A", "버린 사람은 설정의 검토자")


class RefusalTest(Base):
    def test_a_confirmed_section_is_refused_as_locked_with_screen_words(self):
        self.unconfirm_if_needed()
        out = self.cmd("confirm", {"node_ids": [self.nid]})
        self.assertTrue(out["ok"], out)
        key = self.detail()["lost_items"][0]["key"]
        out = self.cmd("discard_lost", {"node_id": self.nid, "keys": [key]})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "locked")
        self.assertIn("확정을 해제한 뒤", out["error"]["message"])
        self.assertEqual(len(self.detail()["lost_items"]), self.row()["lost"])

    def test_an_unknown_key_is_refused_without_internal_words(self):
        self.unconfirm_if_needed()
        out = self.cmd("discard_lost", {"node_id": self.nid, "keys": ["없는-key"]})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "failed")
        for w in BANNED:
            self.assertNotIn(w, out["error"]["message"])

    def test_an_engine_bad_args_refusal_stays_bad_args(self):
        from unittest import mock
        from hazop.study import node_commands
        self.unconfirm_if_needed()
        refused = {"ok": False, "command": "discard_lost", "set_rev": 0, "batch_id": None, "node_ids": [],
                   "refused": [{"target": "keys", "code": "bad_args", "reason": "keys는 lost_items가 준 key 글자의 목록이어야 함"}]}
        with mock.patch.object(node_commands, "execute", lambda *a, **k: refused):
            out = self.cmd("discard_lost", {"node_id": self.nid, "keys": ["x"]})
        self.assertEqual(out["error"]["code"], "bad_args", "엔진의 bad_args는 failed로 바꾸지 않는다")


if __name__ == "__main__":
    unittest.main()
