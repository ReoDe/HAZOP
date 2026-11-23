"""검토 대기열 읽기(hazop/shell/api_queue.py, HZ-DSN-06 §3.3 U3). 실행: python -m unittest tests.test_shell_queue

대기열은 읽기만 하고, 판정은 지금 있는 명령(aireview.*·edit.*·nodes.*)을 그대로 부른다. 여기서는 대기열이 낸 항목의 판(ver·set_rev·target)으로
그 명령을 불러 저장 → 대기열을 다시 읽기 왕복을 본다. 저장은 임시 작업 루트에만 한다. AI·구독 호출 없음.
"""

import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hazop.extract import ai_review as ar  # noqa: E402
from hazop.shell import api_queue  # noqa: E402
from tests.test_screen_words import BANNED  # noqa: E402
from tests import test_shell_aireview as TA  # noqa: E402
from tests import test_shell_discard_lost as TD  # noqa: E402
from tests.test_shell_catch_up import PID  # noqa: E402


def tearDownModule():
    TA.tearDownModule()


class AiQueueTest(TA.Base):
    def queue(self):
        r = api_queue.read(self.engine, ["queue", "ai"], {})
        self.assertIsNotNone(r)
        return json.loads(r.body.decode("utf-8"))

    def kind(self, i, n, value, conf=0.97):
        return ar.make_candidate("k-%d" % i, "kind", n, "kind", [value], conf, "모양")

    def test_items_have_the_common_shape_and_screen_words(self):
        a, b = self.valves[:2]
        self.seed([self.tag(1, a, "V901"), self.kind(2, b, "manual_valve")])
        q = self.queue()
        self.assertEqual((q["kind"], q["total"]), ("ai", 2))
        it = {x["field"]: x for x in q["items"]}
        self.assertEqual(it["tag"]["proposal"], "V901")
        self.assertEqual(it["tag"]["local_id"], a["local_id"])
        self.assertEqual(it["tag"]["label"], a.get("tag") or it["tag"]["label"])
        self.assertTrue(it["tag"]["bulk"] and it["tag"]["edit_op"] == "set_tag")
        self.assertFalse(it["kind"]["bulk"], "기호 종류는 확신이 높아도 하나씩(ai_review.bulk_block)")
        self.assertNotEqual(it["kind"]["proposal"], "manual_valve", "종류는 한글 이름으로")
        self.assertEqual({x["graph_id"] for x in q["items"]}, {self.gid})
        self.assertEqual(q["bulk"], [{"graph_id": self.gid, "sheet": q["items"][0]["sheet"], "task": "tag", "label": ar.TASK_LABELS["tag"],
                                      "count": 1, "ver": q["items"][0]["ver"]}])
        text = json.dumps(q, ensure_ascii=False)
        for w in BANNED:
            self.assertNotIn(w, text)

    def test_the_queue_can_hold_one_drawing_only(self):
        self.seed([self.tag(1, self.valves[0], "V901")])
        one = json.loads(api_queue.read(self.engine, ["queue", "ai"], {"graph_id": self.gid}).body.decode("utf-8"))
        self.assertEqual((one["graph_id"], one["total"]), (self.gid, 1))
        other = json.loads(api_queue.read(self.engine, ["queue", "ai"], {"graph_id": "graph-없음"}).body.decode("utf-8"))
        self.assertEqual(other["total"], 0)

    def test_reading_the_queue_writes_no_correction(self):
        self.seed([self.tag(1, self.valves[0], "V901")])
        self.queue()
        self.assertEqual(self.ops(), [])

    def test_accept_with_the_item_ver_then_reopen_then_undo(self):
        self.seed([self.tag(1, self.valves[0], "V901"), self.tag(2, self.valves[1], "V902")])
        q = self.queue()
        first = q["items"][0]
        out = self.call("aireview.accept", graph_id=first["graph_id"], cand_ids=[first["cand_id"]], ver=first["ver"])
        self.assertTrue(out["ok"], out)
        again = self.queue()
        self.assertEqual([x["qid"] for x in again["items"]], [q["items"][1]["qid"]], "판정한 것은 다음 읽기에서 빠진다")
        self.assertNotEqual(again["ver"], q["ver"])
        self.assertNotEqual(again["items"][0]["ver"], first["ver"], "남은 항목은 새 판을 싣는다")
        back = self.call("aireview.revert", graph_id=first["graph_id"], cand_ids=[first["cand_id"]], ver=again["items"][0]["ver"])
        self.assertTrue(back["ok"], back)
        self.assertEqual(len(self.queue()["items"]), 2, "되돌리면 다시 대기열에 든다")

    def test_an_old_item_ver_is_refused_as_stale(self):
        self.seed([self.tag(1, self.valves[0], "V901"), self.tag(2, self.valves[1], "V902")])
        q = self.queue()
        a, b = q["items"]
        self.assertTrue(self.call("aireview.reject", graph_id=a["graph_id"], cand_ids=[a["cand_id"]], ver=a["ver"])["ok"])
        out = self.call("aireview.accept", graph_id=b["graph_id"], cand_ids=[b["cand_id"]], ver=b["ver"])
        self.assertEqual(out["error"]["code"], "stale", "같은 도면은 판정마다 판이 바뀐다: 화면은 다시 읽은 판을 써야 한다")

    def test_edit_then_reject_and_its_undo(self):
        n = self.valves[0]
        self.seed([self.tag(1, n, "V901")])
        it = self.queue()["items"][0]
        out = self.call("edit.apply", graph_id=it["graph_id"], op=it["edit_op"], local_id=it["local_id"], value={"tag": "V955"},
                        ver=it["ver"])
        self.assertTrue(out["ok"], out)
        rej = self.call("aireview.reject", graph_id=it["graph_id"], cand_ids=[it["cand_id"]], ver=out["data"]["ver"])
        self.assertTrue(rej["ok"], rej)
        self.assertEqual(self.queue()["items"], [])
        self.assertEqual([(o["op"], o.get("origin"), o["value"]["tag"]) for o in self.ops()], [("set_tag", None, "V955")])
        # 되돌리기: 후보 되돌리기 → 고침 빼기
        rv = self.call("aireview.revert", graph_id=it["graph_id"], cand_ids=[it["cand_id"]], ver=rej["data"]["ver"])
        self.assertTrue(rv["ok"], rv)
        un = self.call("edit.undo", graph_id=it["graph_id"], op_id=out["data"]["op_id"], ver=rv["data"]["ver"])
        self.assertTrue(un["ok"], un)
        self.assertEqual(self.ops(), [])
        self.assertEqual(len(self.queue()["items"]), 1)

    def test_bulk_then_one_undo_unit(self):
        a, b, c = self.valves[:3]
        self.seed([self.tag(1, a, "V901"), self.tag(2, b, "V902"), self.tag(3, c, "V903", conf=0.5)])
        q = self.queue()
        self.assertEqual(sorted(x["qid"] for x in q["items"] if x["bulk"]), sorted("ai|%s|t-%d:tag" % (self.gid, i) for i in (1, 2)))
        g = q["bulk"][0]
        out = self.call("aireview.accept_bulk", graph_id=g["graph_id"], task=g["task"], ver=g["ver"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(sorted(out["data"]["changed"]), ["t-1:tag", "t-2:tag"])
        self.assertEqual([x["cand_id"] for x in self.queue()["items"]], ["t-3:tag"])
        back = self.call("aireview.revert", graph_id=g["graph_id"], cand_ids=out["data"]["changed"], ver=out["data"]["ver"])
        self.assertTrue(back["ok"], back)
        self.assertEqual(len(self.queue()["items"]), 3)


class LostQueueTest(TD.Base):
    def queue(self):
        return self.read("queue", "lost")

    def test_lost_items_carry_the_node_and_its_version_without_internal_ids(self):
        q = self.queue()
        mine = [x for x in q["items"] if x["node_id"] == self.nid]
        self.assertEqual(len(mine), self.row()["lost"])
        self.assertEqual(q["set_rev"], self.read("nodes")["set_rev"])
        r = self.row()
        self.assertEqual(mine[0]["target"], {"node_id": r["node_id"], "rev": r["rev"], "state": r["state"]})
        self.assertEqual({x["key"] for x in mine}, {x["key"] for x in self.detail()["lost_items"]})
        text = json.dumps(q, ensure_ascii=False)
        self.assertNotIn("lost:", text, "묘비 id는 싣지 않는다")
        for w in BANNED:
            self.assertNotIn(w, text)

    def test_discard_with_the_item_version_then_undo_round_trip(self):
        self.unconfirm_if_needed()
        q = self.queue()
        it = next(x for x in q["items"] if x["node_id"] == self.nid)
        out = self.engine.dispatch("nodes.discard_lost", {"project_id": PID, "set_rev": q["set_rev"], "targets": [it["target"]],
                                                          "node_id": it["node_id"], "keys": [it["key"]]}, project=PID, via_web=True)
        self.assertTrue(out["ok"], out)
        after = self.queue()
        self.assertNotIn(it["qid"], [x["qid"] for x in after["items"]])
        self.assertNotEqual(after["ver"], q["ver"])
        undo = self.engine.dispatch("nodes.undo", {"project_id": PID, "set_rev": after["set_rev"], "batch_id": out["data"]["batch_id"]},
                                    project=PID, via_web=True)
        self.assertTrue(undo["ok"], undo)
        self.assertIn(it["qid"], [x["qid"] for x in self.queue()["items"]])


if __name__ == "__main__":
    unittest.main()
