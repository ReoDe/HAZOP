"""AI 검토 실행이 나누기(split) 후보를 묻고, 그 후보를 검토 목록에서 일부 수락·전부 수락·되돌리기까지 끝까지 하는 길(split 켜기, 2026-11-24).

앱 길 그대로: 등록·추출 → 검토구간 만들기 → api_aireview.run_review(가짜 구독 클라이언트, 그림 입력 켬)
→ 검토 목록(api_aireview.candidates) → api_aireview.accept → 짓기 작업(api_inputs) → 판 이전.
도면은 tests.test_corrections_inputs의 합성 1쪽 PDF(맞닿은 수동 밸브 셋이 한 덩어리). 덩어리가 60pt라 나누기 대상 하한(긴 변 100pt)만
시험에서 낮춘다. 실제 구독 호출은 없다.
앱은 아직 split을 묻지 않는다(엔진 결함이 고쳐질 때까지 꺼 둠, 2026-11-24). 이 시험은 그림 입력에 split=True를 직접 실어 켠 길을 미리 돌린다.
"""

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_titleblock import BY, P, Base  # noqa: E402
from tests.test_corrections_inputs import BLOB, GROUPS, HAS_PDFPLUMBER, page  # noqa: E402
from tests.test_ai_split import StubClient  # noqa: E402
from tests.test_shell_aireview import FakeAi  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.app import data, project_ctx  # noqa: E402
from hazop.extract import ai_images, ai_review, ai_split, corrections  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
from hazop.register import registry  # noqa: E402
from hazop.shell import ai_image_flow, api, api_aireview, api_inputs, api_nodes, sheet_refresh  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402

OTHERS = ["pdf-p0-sym-0002", "pdf-p0-sym-0003"]
INNER = ("split", "pdf-", "sym-", "None", "null", "undefined")


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 필요")
class SplitEnabledFlow(Base):
    def setUp(self):
        super().setUp()
        with pdf_vector._cache_lock:
            pdf_vector._cache.clear()
        src = os.path.join(self.tmp, "in", "SYN-LUMP-001.pdf")
        os.makedirs(os.path.dirname(src))
        with open(src, "wb") as fh:
            fh.write(page())
        res = registry.register(src, P, "P&ID", paths.store_root(), None, BY)
        self.assertEqual(res["outcome"], "registered", res.get("notes"))
        data.extract_and_graph(res["registration_file"])
        s = self.sheet(res["record"]["material_id"])
        self.name, self.gid = s["name"], s["graph_id"]
        ex = corrections.resolve(self.name)["base"]
        pdf = paths.resolve_rel(ex["source"]["file"], paths.work_root())
        by = {n["source_object_id"]: n for n in ex["nodes"]}
        self.blob = ai_split._box(by[BLOB])
        shapes = pdf_vector.member_shapes(pdf, 0)
        self.boxes = [ai_split._union([shapes[p][0] for p in g]) for g in GROUPS]
        self.eng = api.Engine(settings_path=os.path.join(self.tmp, "eng.json"), emit=lambda *a, **k: None, run_jobs=lambda jid, fn: fn())
        self.eng.settings.update(reviewer_name=BY, project_id=P)
        self.addCleanup(lambda: api_inputs.of(self.eng).stop())
        cmds = {}
        api_nodes.register(cmds)
        c = cmds["nodes.create"]
        out = c.handler(self.eng, api.check_args(c.spec, {"project_id": P, "set_rev": (sn.load(self.pg()) or {}).get("set_rev") or 0,
                                                          "sheet": self.gid, "ids": [by[s]["local_id"] for s in [BLOB] + OTHERS],
                                                          "name": "S-probe"}))
        self.assertNotEqual((out or {}).get("ok"), False, out)
        self.client = StubClient(self.answer)
        self.eng.ai = FakeAi(self.client)

    def pg(self):
        return project_ctx.project_graph(P)

    def sids(self, eids):
        by = {n["entity_id"]: n.get("source_object_id") for n in self.pg()["nodes"]}
        return sorted(by[e] for e in eids)

    def answer(self, req):
        """나누기 요청에는 밸브 셋을 각각 상자로 답한다(빨간 테두리 = 덩어리 상자에서 쪽 좌표 → 그림 픽셀). 다른 과제는 답하지 않는다."""
        if "symbols" not in req["schema"]["properties"]:
            return {"answers": []}
        red = json.loads(req["context"])["red_box"]
        k = (red[2] - red[0]) / (self.blob[2] - self.blob[0])

        def px(b):
            return [red[0] + (b[0] - self.blob[0]) * k, red[1] + (b[1] - self.blob[1]) * k,
                    red[0] + (b[2] - self.blob[0]) * k, red[1] + (b[3] - self.blob[1]) * k]
        return {"symbols": [{"box": px(b), "kind": "manual_valve", "match": "legend", "confidence": 0.9, "reason": "수동 밸브 칸과 같은 모양"}
                            for b in self.boxes]}

    def run_review(self):
        real = ai_images.image_input_for

        def with_split(*a, **k):
            return real(*a, **dict(k, split=True))
        with mock.patch.object(ai_split, "LONG_MIN", 50.0), mock.patch.object(ai_images, "image_input_for", with_split), \
                mock.patch.object(ai_image_flow, "estimate_input", lambda: ai_images.ImageInput(None, wide=True, recheck=True, split=True)):
            return api_aireview.run_review(self.eng, [self.gid], ai_review.DEFAULT_CAP, lambda *a: None)

    def rows(self):
        view = api_aireview.candidates(self.eng, self.gid)
        self.assertTrue(view.get("ok", True), view)
        return [r for g in view["groups"] for r in g["items"] if r["task"] == "split"]

    def build(self):
        self.assertEqual(api_inputs.of(self.eng).flush([self.name]), [self.name])
        ns = sn.read_as_is(self.pg())
        self.assertFalse(sn.is_stale(ns, self.pg()))
        return ns

    def accept(self, ids):
        r = api_aireview.accept(self.eng, self.gid, ids, sheet_refresh.ver_of(self.name))
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r["failed"], [], r)
        return self.build()

    def test_run_asks_split_and_queue_rows_read_as_plain_words(self):
        done = self.run_review()
        self.assertLessEqual(done["calls"], ai_review.DEFAULT_CAP)
        self.assertEqual((ai_review.DEFAULT_CAP, ai_review.RUN_CAP), (20, 300), "호출 상한은 그대로")
        asked = [q for q in self.client.requests if "symbols" in q["schema"]["properties"]]
        self.assertEqual(len(asked), 1, "덩어리 하나를 한 번 묻는다")
        rows = self.rows()
        self.assertEqual(len(rows), 3, rows)
        for r in rows:
            shown = [r["field_label"], r["status_label"], r["reason"], r["current_text"]] + r["values_text"]
            for text in shown:
                self.assertFalse(any(w in str(text) for w in INNER), "화면 글에 내부 이름: %r" % text)
            self.assertEqual(r["values_text"], [r["values_text"][0]])
            self.assertIsNotNone(r["local_id"], "후보 자리를 찾는다")

    def revert(self, ids):
        r = api_aireview._decide(self.eng, self.gid, ids, "revert", sheet_refresh.ver_of(self.name))
        self.assertTrue(r.get("ok"), r)
        return self.build()["nodes"][0]

    def whole(self, seg, why):
        self.assertEqual((seg.get("lost") or [], self.sids(seg["members"])), ([], sorted([BLOB] + OTHERS)), why)

    def accept_one_then_rest(self):
        self.run_review()
        ids = [r["cand_id"] for r in self.rows()]
        self.whole(self.accept(ids[:1])["nodes"][0], "일부 수락")
        left = [r for r in self.rows() if r["status"] == "proposed"]
        self.assertEqual(len(left), 2)
        self.assertTrue(all(r["local_id"] for r in left), "남은 후보는 몸체 자리로 다시 찾는다")
        seg = self.accept([r["cand_id"] for r in left])["nodes"][0]
        self.assertEqual(self.sids(seg["members"]), sorted(OTHERS), "전부 수락하면 덩어리만 빠진다")
        self.assertEqual(len(seg.get("lost") or []), 1)
        return ids

    def test_accept_one_then_the_rest_and_revert_step_by_step(self):
        ids = self.accept_one_then_rest()
        self.whole(self.revert(ids[1:]), "나중 수락을 되돌리면 몸체가 돌아온다")
        self.whole(self.revert(ids[:1]), "처음 수락까지 되돌린다")

    def test_accept_all_at_once_then_revert(self):
        self.run_review()
        ids = [r["cand_id"] for r in self.rows()]
        self.accept(ids)
        self.whole(self.revert(ids), "되돌리면 돌아온다")

    def test_accept_one_then_the_rest_and_revert_all_at_once(self):
        # 엔진 결함(2026-11-24, R3b에 넘김): 두 번에 걸쳐 전부 수락한 뒤 셋을 한꺼번에 되돌리면 덩어리는 돌아오지만
        # 검토구간 구성원으로 다시 들지 않고 '찾지 못한 구성요소'로 남는다. 한 번에 전부 수락·되돌리기, 차례로 되돌리기는 돌아온다.
        ids = self.accept_one_then_rest()
        self.whole(self.revert(ids), "한꺼번에 되돌려도 돌아온다")


del Base

if __name__ == "__main__":
    unittest.main()
