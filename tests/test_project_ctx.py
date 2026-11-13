"""앱 프로젝트 맥락(hazop.app.project_ctx): 표기, 도면별 칩, 옛 도면별 저장본 이전(백업·사람 결과 보존). 임시 작업 루트만 쓴다."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop import paths  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_project_graph import cont, sheet  # noqa: E402

AT = "2026-11-07T00:00:00Z"


class ProjectCtxTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-pctx-")
        self._env = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = self.tmp
        self.a = sheet("SNP-M-101", cont("C1", "TO SNP-M-102\nL-1"))
        self.b = sheet("SNP-M-102", cont("C1", "FROM SNP-M-101\nL-1"))
        for g in (self.a, self.b):
            for n in g["nodes"]:
                if n.get("node_type") == "drawing_object":
                    n["local_id"] = "local-" + n["entity_id"]
            d = paths.output_in(self.tmp, "graph", g["source"]["drawing_number"])
            os.makedirs(d)
            with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as fh:
                json.dump(g, fh)
        from hazop.app import project_ctx
        self.pc = project_ctx

    def test_project_graph_is_reused_until_a_graph_file_changes(self):
        first = self.pc.project_graph("P")
        self.assertIs(self.pc.project_graph("P"), first, "입력이 같으면 다시 짓지 않음")
        p = paths.output_in(self.tmp, "graph", "SNP-M-102", "graph.json")
        g = dict(self.b, graph_version="v2")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(g, fh)
        os.utime(p, ns=(os.stat(p).st_atime_ns, os.stat(p).st_mtime_ns + 10 ** 9))
        again = self.pc.project_graph("P")
        self.assertIsNot(again, first, "도면 그래프 파일이 바뀌면 다시 짓는다")
        self.assertIn("v2", [s["graph_version"] for s in again["sheets"]])

    def test_view_is_shared_for_the_same_content_only(self):
        ctx = self.pc.load("SNP-M-102")
        ns, _ = ctx.load_set()
        v = ctx.view(ns)
        self.assertIs(ctx.view(json.loads(json.dumps(ns))), v, "내용이 같으면 같은 표기 사본")
        renamed = json.loads(json.dumps(ns))
        renamed["nodes"][0]["name"] = "다른 이름"
        self.assertIsNot(ctx.view(renamed), v)

    def tearDown(self):
        if self._env is None:
            os.environ.pop("HAZOP_WORK_ROOT", None)
        else:
            os.environ["HAZOP_WORK_ROOT"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def old_set_with_result(self, status="approved"):
        """0.1 도면별 확정본과 그 결과(옛 앱이 쓴 모양)."""
        from hazop.study import remap
        old = dict(sn.propose(self.a, at=AT), schema_version="0.1", status="confirmed", confirmed_at=AT,
                   confirmed_by="EJ")
        sn.write(sn.store_path(old["project_id"], old["graph_id"]), old)
        r = remap.empty_legacy(old, res.load_deviations())
        cell = r["cells"][0]
        cell.update(state="analyzed", entries=[{"entry_id": "e1", "origin": "ai_draft", "status": status, "cause": "c"}])
        res.write(res.store_path(old["project_id"], old["graph_id"]), r)
        return old

    def test_label_counts_and_chip_on_viewed_drawing_only(self):
        ctx = self.pc.load("SNP-M-102")
        ns, saved = ctx.load_set()
        self.assertFalse(saved)
        n = next(x for x in ctx.view(ns)["nodes"] if x["spans_drawings"])
        self.assertTrue(self.pc.node_label(n).endswith("[101 → 102] ⇄"))
        self.assertRegex(self.pc.counts_text(n, "SNP-M-102"), r"^이 도면 \d+ / 전체 \d+$")
        self.assertIn("(101)", self.pc.boundary_text(n))
        chips = ctx.chips(n)
        self.assertEqual([(c["text"], c["name"], c["local_id"]) for c in chips],
                         [("%s → SNP-M-101에서 계속" % n["node_id"], "SNP-M-101", "local-C1")])
        self.assertEqual(ctx.coverage_text(ns)[0], "프로젝트 100% · 이 도면 100%")

    def test_old_sets_move_with_backup_and_old_file_untouched(self):
        self.old_set_with_result()
        old_path = sn.store_path("P", "graph-SNP-M-101")
        with open(old_path, "rb") as fh:
            before = fh.read()
        ctx = self.pc.load("SNP-M-101")
        ns, saved = ctx.load_set()
        self.assertTrue(saved)
        self.assertEqual({n["state"] for n in ns["nodes"]}, {"applied"})  # 범위가 넓어진 구간이 있어 사람이 다시 확정
        self.assertIn("graph-SNP-M-101:S1", [i for n in ns["nodes"] for i in n.get("legacy_ids", [])])
        self.assertEqual(ns["legacy_sources"][0]["confirmed_by"], "EJ")
        self.assertIn("백업", ctx.notice)
        with open(old_path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        backups = os.listdir(paths.folder_in(self.tmp, "backup"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(os.path.isfile(paths.folder_in(self.tmp, "backup", backups[0], *paths.FOLDERS["study-nodes"].rel,
                                                    "P", "graph-SNP-M-101.json")))
        again, _ = self.pc.load("SNP-M-101").load_set()  # 두 번째는 저장본을 읽고 다시 옮기지 않음
        self.assertEqual(again, ns)

    def test_results_move_only_after_confirm_and_keep_human_status(self):
        self.old_set_with_result("approved")
        ctx = self.pc.load("SNP-M-101")
        ns, _ = ctx.load_set()
        self.assertIsNone(self.pc.migrate_results(ctx.pg, ns))  # 제안 상태에서는 옮기지 않음
        confirmed = sn.confirm(ns, ctx.pg, "EJ", at=AT)
        sn.save(confirmed)
        doc, text = self.pc.migrate_results(ctx.pg, confirmed)
        entries = [e for c in doc["cells"] for e in c["entries"]]
        self.assertEqual([(e["status"], e["legacy"]["entry_id"]) for e in entries], [("approved", "e1")])
        self.assertIn("사람 검토 1건", text)
        self.assertEqual(res.validate(doc, confirmed), [])
        self.assertIsNone(self.pc.migrate_results(ctx.pg, confirmed))  # 프로젝트 결과가 있으면 덮어쓰지 않음


    def test_unreadable_old_result_stops_whole_results_move(self):
        self.old_set_with_result("approved")
        b_old = sn.confirm(sn.propose(self.b, at=AT), self.b, "EJ", at=AT)
        sn.save(b_old)
        with open(res.store_path("P", "graph-SNP-M-102"), "w", encoding="utf-8") as fh:
            fh.write("{깨진 파일")
        ctx = self.pc.load("SNP-M-101")
        ns, _ = ctx.load_set()
        confirmed = sn.confirm(ns, ctx.pg, "EJ", at=AT)
        doc, reason = self.pc.migrate_results(ctx.pg, confirmed)
        self.assertIsNone(doc)
        self.assertIn("graph-SNP-M-102", reason)
        self.assertFalse(os.path.isfile(res.store_path("P", confirmed["graph_id"])), "일부만 옮기지 않음")

    def test_older_copy_of_same_sheet_is_blocked(self):
        old_dir = paths.output_in(self.tmp, "graph", "SNP-M-101-old")
        shutil.copytree(paths.output_in(self.tmp, "graph", "SNP-M-101"), old_dir)
        os.utime(os.path.join(old_dir, "graph.json"), (1, 1))  # 더 오래된 판: 프로젝트 그래프는 SNP-M-101 쪽을 쓴다
        ctx = self.pc.load("SNP-M-101-old")
        self.assertIsNone(ctx.pg)
        self.assertIn("판이 프로젝트 그래프에 쓰인 판", ctx.error)
        self.assertIsNotNone(self.pc.load("SNP-M-101").pg)

    def test_other_project_with_same_graph_id_not_offered(self):
        q = sheet("SNP-M-102", cont("C1", "FROM SNP-M-101 L-1"))
        q["project_id"] = "Q"
        d = paths.output_in(self.tmp, "graph", "Q-SNP-M-102")
        os.makedirs(d)
        with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as fh:
            json.dump(q, fh)
        ctx = self.pc.load("SNP-M-101")
        self.assertEqual(ctx.drawing_names["SNP-M-102"], "SNP-M-102")


if __name__ == "__main__":
    unittest.main()
