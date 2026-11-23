"""AI 검토 실행의 그림 입력 연결(hazop/shell/ai_image_flow.py). 실행: python -m unittest tests.test_shell_aireview_images

벡터 PDF 도면은 조각 그림과 범례판을 싣고, drawio 도면은 글만, 끄면 모두 글만 보낸다. 예상 호출 수는 그림 몫을 넣은 값이고 실제 호출은 그 안이다.
가짜 클라이언트만 쓴다(실제 구독 호출 없음). 가상 도면 SNP-M-102 PDF를 임시 작업 루트에 추출해 쓴다(APR1400 자료는 쓰지 않음).
"""

import glob
import json
import os
import unittest
from unittest import mock

from hazop import paths
from hazop.extract import ai_review as ar
from hazop.shell import api_aireview as AR
from tests.test_ai_review import StubClient
from tests.test_shell_aireview import Base, FakeAi, kind_answers, tearDownModule  # noqa: F401  (tearDownModule: 틀 정리)


class PdfBase(Base):
    """준비: 임시 작업 루트에 SNP-M-102 PDF 도면을 추출해 더하고 가짜 AI를 단다."""

    def setUp(self):
        super().setUp()
        from hazop.app import data
        from hazop.extract.adapters import pdf_vector
        pdf = glob.glob(os.path.join(paths.folder("references", "pid-samples"), "SNP-M-102*", "*.pdf"))[0]
        ex = pdf_vector.extract(pdf, page=0, repo_root=self.tmp)
        ex["project_id"] = self.ex["project_id"]
        ex["drawing"]["drawing_number"] = "SNP-PDF-1"
        self.pname = "SNP-PDF-1-p0"
        os.makedirs(os.path.dirname(data.extraction_path(self.pname)), exist_ok=True)
        with open(data.extraction_path(self.pname), "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)
        data.script_module("build_graph").build_one(data.extraction_path(self.pname), paths.output_root("graph"))
        self.pgid = {v: k for k, v in self.engine.graph_names().items()}[self.pname]
        self.client = StubClient(kind_answers)
        self.engine.ai = FakeAi(self.client)

    def estimate(self, cap=20):
        return json.loads(AR.read(self.engine, ["aireview", "estimate"], {"cap": str(cap)}).body.decode("utf-8"))

    def run_job(self, gids, cap=20):
        self.events.items.clear()
        out = self.call("aireview.run", graph_ids=gids, cap=cap, conn_ver=self.estimate(cap)["conn"]["conn_ver"])
        self.assertTrue(out["ok"], out)
        return next(e for e in self.events.items if e.get("name") == "job.done")["data"]["result"]

    def view_of(self, gid):
        return json.loads(AR.read(self.engine, ["aireview", gid], {}).body.decode("utf-8"))


class ImageRunTest(PdfBase):
    def test_estimate_marks_which_drawings_send_pictures(self):
        r = self.estimate()
        by = {p["graph_id"]: p for p in r["pages"]}
        self.assertTrue(by[self.pgid]["image"])
        self.assertFalse(by[self.gid]["image"])                      # drawio에서 온 도면은 글만
        self.assertEqual(r["images"], {"on": True, "pages": 1})

    def test_pdf_drawing_sends_pictures_and_drawio_sends_text(self):
        done = self.run_job([self.gid, self.pgid])
        with_images = [q for q in self.client.requests if q.get("images")]
        self.assertTrue(with_images, "PDF 도면은 그림을 싣는다")
        self.assertLess(len(with_images), len(self.client.requests), "drawio 도면 요청은 글만이다")
        for q in with_images:
            self.assertTrue(all(q["images"]))
        by = {d["graph_id"]: d for d in done["drawings"]}
        self.assertTrue(by[self.pgid]["images"])
        self.assertFalse(by[self.gid]["images"])
        self.assertIn(by[self.pgid]["legend_source"], ("project", "symbols", "none"))

    def test_actual_calls_never_exceed_the_estimate_or_the_caps(self):
        for cap in (1, 2, 20):
            self.client.requests.clear()
            est = self.estimate(cap)
            done = self.run_job([self.gid, self.pgid], cap)
            self.assertLessEqual(done["calls"], est["calls"], cap)
            self.assertEqual(done["calls"], len(self.client.requests))
            for d in done["drawings"]:
                self.assertLessEqual(d["calls"], cap)
            self.assertLessEqual(done["calls"], ar.RUN_CAP)

    def test_run_cap_limits_the_estimate_and_the_run(self):
        with mock.patch.object(ar, "RUN_CAP", 1):
            est = self.estimate(20)
            done = self.run_job([self.gid, self.pgid], 20)
        self.assertEqual(est["run_cap"], 1)
        self.assertLessEqual(est["calls"], 1)
        self.assertLessEqual(done["calls"], est["calls"])

    def test_turning_pictures_off_sends_text_only_and_is_the_only_toggle(self):
        out = self.call("extract.set_ai_review", images=False)
        self.assertTrue(out["ok"], out)
        self.assertTrue(self.changed("aireview"))
        r = self.estimate()
        self.assertEqual(r["images"], {"on": False, "pages": 0})
        self.assertFalse(any(p["image"] for p in r["pages"]))
        done = self.run_job([self.gid, self.pgid])
        self.assertFalse(any(q.get("images") for q in self.client.requests))
        self.assertFalse(any(d["images"] for d in done["drawings"]))
        self.assertTrue(self.call("extract.set_ai_review", images=True)["ok"])
        self.assertTrue(self.estimate()["images"]["on"])

    def test_last_run_line_says_which_legend_was_used_and_cache_stays_in_cache_folder(self):
        before = {os.path.join(d, f) for d, _s, fs in os.walk(paths.work_root()) for f in fs}
        self.run_job([self.pgid])
        last = self.view_of(self.pgid)["last_run"]
        self.assertIn(last["legend"], ("범례판: 이 프로젝트 도면에서 만든 견본", "범례판: 표준 기호 그림", "범례판: 범례판 없이"))
        made = {os.path.join(d, f) for d, _s, fs in os.walk(paths.work_root()) for f in fs} - before
        cache = os.path.normcase(paths.folder("cache", "ai-legend"))
        for f in made:
            if f.endswith(".png"):
                self.assertTrue(os.path.normcase(f).startswith(cache), f)

    def test_failing_picture_input_falls_back_to_text_for_that_drawing(self):
        from hazop.extract import ai_images
        with mock.patch.object(ai_images, "image_input_for", side_effect=RuntimeError("그림 실패")):
            done = self.run_job([self.pgid])
        self.assertEqual(done["image_failed"], [self.pname])
        self.assertTrue(self.client.requests)
        self.assertFalse(any(q.get("images") for q in self.client.requests))

    def test_api_connection_is_refused_before_any_picture_is_sent(self):
        client = StubClient(kind_answers)
        client.describe = lambda: {"via": "api"}

        class ApiAi(FakeAi):
            def status(self):
                return {"can_start": True, "state": "ok", "via": "api", "model": "claude-opus-5-5"}
        self.engine.ai = ApiAi(client)
        with self.assertRaises(RuntimeError):
            AR.run_review(self.engine, [self.pgid], 20, lambda *a: None)
        self.assertEqual(client.requests, [])

    def test_recheck_row_shows_script_and_ai_values_and_is_not_bulk(self):
        node = self.valves[0]
        cand = ar.make_candidate("rr-%s" % node["source_object_id"], "recheck", node, "kind", ["check_valve"], 0.97, "규칙 다시 확인",
                                 extra={"rule": "x", "script_value": "manual_valve"})
        self.seed([cand])
        row = self.view()["groups"][0]["items"][0]
        self.assertEqual((row["task"], row["script_value"], row["values"][0]), ("recheck", "manual_valve", "check_valve"))
        self.assertFalse(row["bulk_ok"])
        self.assertEqual(self.view()["bulk"], [])

    def test_split_row_reads_as_plain_words(self):
        node = self.valves[0]
        cand = ar.make_candidate("split:%s:x" % node["source_object_id"], "split", dict(node, bbox=[0, 0, 1, 1]), "split",
                                 ["manual_valve"], 0.9, "수동 밸브 칸과 같은 모양", {"match": "legend", "pdf_objects": ["pdf-path-0001"]})
        self.seed([cand])
        row = next(r for g in self.view()["groups"] for r in g["items"] if r["task"] == "split")
        self.assertEqual((row["field_label"], row["current_text"]), ("덩어리 나누기", "한 덩어리"), "내부 이름 split·종류 없음 대신 사람 말")
        self.assertNotIn("manual_valve", row["values_text"])

    def test_auto_review_after_extraction_uses_the_same_picture_input(self):
        from hazop.app import data
        from hazop.shell import register_flow
        self.engine.settings["extract_ai_review"] = True
        self.engine.settings["ai_review_images"] = True      # 자동 검토는 명시적으로 켠 경우에만 그림을 싣는다
        pages = [(self.pname, data.read_json(data.extraction_path(self.pname))), (self.name, self.ex)]
        out = register_flow.review_if_wanted(self.engine, pages, lambda *a: None)
        self.assertTrue(out["ran"], out)
        self.assertLessEqual(out["calls"], out["estimate"])
        self.assertTrue(any(q.get("images") for q in self.client.requests))
        self.engine.settings["ai_review_images"] = False
        self.client.requests.clear()
        register_flow.review_if_wanted(self.engine, pages, lambda *a: None)
        self.assertFalse(any(q.get("images") for q in self.client.requests))


if __name__ == "__main__":
    unittest.main()
