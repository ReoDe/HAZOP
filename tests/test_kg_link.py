"""엔티티 연결 후보·확인 흐름 테스트 (기획서/그래프활용.md §3, §7.2 L1~L4). 실행: python -m unittest discover -s tests -t .

P&ID 그래프는 tests.test_kg.pid_graph()(샘플 도면 SNP-M-102를 임시 폴더에서 추출·빌드)를 쓴다(출력/ 폴더에 의존하지 않음).
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_kg_link  # noqa: E402
import link_kg  # noqa: E402
from hazop.kg import inputs, link  # noqa: E402
from tests.test_kg import SAMPLE_DIR, pid_graph  # noqa: E402


def chunk(id, text, material_id="MAT-1", registration_version="1"):
    return {"id": id, "node_type": "doc_chunk", "text": text, "material_id": material_id,
            "registration_version": registration_version}


class SampleChecks(unittest.TestCase):
    """check_kg_link의 L1~L4 판정을 테스트에서 만든 그래프로 다시 실행."""

    def test_l1_to_l4(self):
        for k, label, ok in check_kg_link.link_checks(SAMPLE_DIR, [pid_graph()]):
            with self.subTest(check=k, label=label):
                self.assertTrue(ok)

    def test_sample_candidates_csv_is_current(self):
        """저장소의 link_candidates.csv는 현재 생성 결과와 같고, 확인 2건은 knowledge_links의 W3 mentions와 같은 ID."""
        rows = link.read_candidates(os.path.join(SAMPLE_DIR, link.CANDIDATES_CSV))
        gen = link.generate(inputs.read_csv(os.path.join(SAMPLE_DIR, link.NODES_CSV), inputs.NODE_COLUMNS),
                            [pid_graph()])["candidates"]
        self.assertEqual([r["candidate_key"] for r in rows], [r["candidate_key"] for r in gen])
        linked = {r["id"] for r in inputs.read_csv(os.path.join(SAMPLE_DIR, link.LINKS_CSV), inputs.LINK_COLUMNS)
                  if r["kind"] == "mentions"}
        conf = {link.relation_id(r["candidate_key"]) for r in rows if r["link_status"] == "confirmed"}
        self.assertEqual(conf, linked)
        self.assertEqual(conf, {"krel-m-8d0c926c", "krel-m-7c52c0fd"})


class Generate(unittest.TestCase):

    def test_normalized_variants_are_exact_norm(self):
        nodes = [chunk("chunk-1", "소문자 rc-pv101와 en dash RC–PT110, 영숫자에 붙은 1RC-PV101은 태그 아님.")]
        c = link.generate(nodes, [pid_graph()])["candidates"]
        self.assertEqual([(r["match_text"], r["method"], r["target_tag"]) for r in c],
                         [("rc-pv101", "exact_norm", "RC-PV101"), ("RC–PT110", "exact_norm", "RC-PT110")])

    def test_typo_token_is_fuzzy_not_exact(self):
        c = link.generate([chunk("chunk-1", "XRC-PV101")], [pid_graph()])["candidates"]
        self.assertEqual(sorted((r["method"], r["target_tag"], r["ambiguous"]) for r in c),
                         [("fuzzy", "RC-PSV101", "true"), ("fuzzy", "RC-PV101", "true")])

    def test_exact_match_suppresses_fuzzy(self):
        c = link.generate([chunk("chunk-1", "RC-PT110")], [pid_graph()])["candidates"]
        self.assertEqual([r["target_tag"] for r in c], ["RC-PT110"])

    def test_position_on_normalized_text(self):
        raw = "  앞   공백\n\n줄바꿈  RC-PV101 "
        c = link.generate([chunk("chunk-1", raw)], [pid_graph()])["candidates"]
        norm = inputs.normalize_text(raw)
        self.assertEqual(norm[int(c[0]["match_start"]):int(c[0]["match_end"])], "RC-PV101")
        self.assertEqual(c[0]["text_sha256"], inputs.text_sha256(raw))

    def test_pipe_in_key_field_becomes_review_item(self):
        res = link.generate([chunk("chunk-1", "RC-PV101", material_id="MAT|1")], [pid_graph()])
        self.assertEqual(res["candidates"], [])
        self.assertEqual([(i["check"], i["match_text"]) for i in res["review_items"]],
                         [("pipe_in_key_field", "RC-PV101")])

    def test_same_tag_in_two_graphs_is_ambiguous(self):
        g1, g2 = pid_graph(), pid_graph()
        g2["graph_id"] = "graph-OTHER"
        c = link.generate([chunk("chunk-1", "RC-PV101")], [g2, g1])["candidates"]
        self.assertEqual([r["target_ref"] for r in c], ["graph-OTHER:RC-PV101", "graph-SNP-M-102:RC-PV101"])
        self.assertTrue(all(r["ambiguous"] == "true" for r in c))

    def test_blocked_graph_rejected(self):
        g = pid_graph()
        g["validation"]["status"] = "blocked"
        with self.assertRaises(link.LinkError):
            link.generate([chunk("chunk-1", "RC-PV101")], [g])


class Judgements(unittest.TestCase):

    def setUp(self):
        self.chunks = [chunk("chunk-1", "RC-PV101, rc-pt110, RC-PZ1, RC-L011")]
        self.rows = link.generate(self.chunks, [pid_graph()])["candidates"]

    def _tampered_fuzzy(self):
        """재현 사례(Codex P1): RC-PZ1 -> RC-PZ01 fuzzy 후보의 CSV 열을 정확 일치처럼 고친 행."""
        rows = [dict(r) for r in self.rows]
        pz = next(r for r in rows if r["match_text"] == "RC-PZ1")
        pz.update(method="exact_norm", target_tag="RC-PZ1", confidence="1.000")
        return rows, pz

    def test_confirm_exact_uses_recomputed_candidates(self):
        rows, pz = self._tampered_fuzzy()
        current = link.generate(self.chunks, [pid_graph()])["candidates"]
        link.confirm_exact(rows, current, "검토자", "일괄", "2026-11-05")
        self.assertEqual(pz["link_status"], "candidate")
        self.assertEqual([r["match_text"] for r in rows if r["link_status"] == "confirmed"], ["RC-PV101"])

    def test_apply_refuses_tampered_confirmed_row(self):
        rows, pz = self._tampered_fuzzy()
        pz.update(link_status="confirmed", reviewed_by="검토자", reason="일괄")
        with self.assertRaises(link.LinkError):
            link.apply_confirmed(rows, self.rows, [])

    def test_honest_fuzzy_confirmed_one_by_one_is_applied(self):
        rows = [dict(r) for r in self.rows]
        pz = next(r for r in rows if r["match_text"] == "RC-PZ1")
        pz.update(link_status="confirmed", reviewed_by="검토자", reason="한 건 확인")
        add = link.apply_confirmed(rows, self.rows, [])["add"]
        self.assertEqual([(a["method"], a["to"]) for a in add], [("fuzzy", "graph-SNP-M-102:RC-PZ01")])

    def test_confirm_exact_skips_recheck_candidates(self):
        for prev in ("confirmed", "rejected"):
            rows = [dict(r) for r in self.rows]
            pv = next(r for r in rows if r["match_text"] == "RC-PV101")
            pv["previous_status"] = prev
            self.assertEqual(link.confirm_exact(rows, self.rows, "검토자", "일괄", "2026-11-05"), 0)
            self.assertEqual(pv["link_status"], "candidate")

    def test_confirm_exact_requires_reviewer_and_reason(self):
        with self.assertRaises(link.LinkError):
            link.confirm_exact(self.rows, self.rows, "검토자", " ", "2026-11-05")
        with self.assertRaises(link.LinkError):
            link.confirm_exact(self.rows, self.rows, None, "사유", "2026-11-05")
        self.assertTrue(all(r["link_status"] == "candidate" for r in self.rows))

    def test_confirm_exact_only_literal_unambiguous(self):
        n = link.confirm_exact(self.rows, link.generate(self.chunks, [pid_graph()])["candidates"],
                               "검토자", "일괄 확인", "2026-11-05")
        done = [(r["match_text"], r["reviewed_by"], r["reason"]) for r in self.rows if r["link_status"] == "confirmed"]
        self.assertEqual(n, 1)
        self.assertEqual(done, [("RC-PV101", "검토자", "일괄 확인")])  # 대소문자 변형·유사·모호(RC-L011)는 제외

    def test_invalid_judgement_rejected(self):
        bad = [dict(self.rows[0], link_status="Confirmed")]
        with self.assertRaises(link.LinkError):
            link.merge(self.rows, bad)
        bad = [dict(self.rows[0], link_status="rejected", reviewed_by=None)]
        with self.assertRaises(link.LinkError):
            link.apply_confirmed(bad, self.rows, [])

    def test_apply_refuses_edited_columns(self):
        edited = [dict(self.rows[0], link_status="confirmed", reviewed_by="r", target_ref="graph-X:Y", chunk_id="z")]
        with self.assertRaises(link.LinkError):
            link.apply_confirmed(edited, self.rows, [])

    def test_reference_columns_may_differ(self):
        edited = [dict(self.rows[0], link_status="confirmed", reviewed_by="r", confidence="0.5", target_entity_id="x")]
        add = link.apply_confirmed(edited, self.rows, [])["add"]
        self.assertEqual((add[0]["to"], add[0]["from"]), ("graph-SNP-M-102:RC-PV101", "chunk-1"))

    def test_relation_id_collision_stops(self):
        conf = [dict(self.rows[0], link_status="confirmed", reviewed_by="r")]
        other = {c: None for c in inputs.LINK_COLUMNS}
        other.update(id=link.relation_id(self.rows[0]["candidate_key"]), kind="part_of")
        with self.assertRaises(link.LinkError):
            link.apply_confirmed(conf, self.rows, [other])

    def test_rejected_but_linked_reported(self):
        rej = [dict(self.rows[0], link_status="rejected", reviewed_by="r")]
        linked = [link.mention_row(dict(self.rows[0], reviewed_by="r"))]
        res = link.apply_confirmed(rej, self.rows, linked)
        self.assertEqual(res["rejected_but_linked"], [self.rows[0]["candidate_key"]])
        self.assertEqual(res["add"], [])

    def test_previous_status_follows_latest_judgement(self):
        """원문이 두 번 바뀌어도 가장 최근 판단(rejected)이 previous_status로 이어진다."""
        g = [pid_graph()]
        k1 = link.generate([chunk("chunk-1", "RC-PV101")], g)["candidates"]
        k1[0].update(link_status="confirmed", reviewed_by="r")
        k2 = link.merge(link.generate([chunk("chunk-1", "개정 RC-PV101")], g)["candidates"], k1)
        self.assertEqual([(r["link_status"], r["previous_status"]) for r in k2],
                         [("candidate", "confirmed"), ("confirmed", None)])
        k2[0].update(link_status="rejected", reviewed_by="r")
        k3 = link.merge(link.generate([chunk("chunk-1", "재개정 RC-PV101")], g)["candidates"], k2)
        self.assertEqual([(r["link_status"], r["previous_status"]) for r in k3],
                         [("candidate", "rejected"), ("rejected", "confirmed"), ("confirmed", None)])

    def test_unjudged_stale_candidate_dropped(self):
        g = [pid_graph()]
        old = link.generate([chunk("chunk-1", "RC-PV101")], g)["candidates"]
        new = link.merge(link.generate([chunk("chunk-1", "개정 RC-PV101")], g)["candidates"], old)
        self.assertEqual(len(new), 1)
        self.assertIsNone(new[0]["previous_status"])

    def _graph(self, version):
        g = pid_graph()
        g["graph_version"] = version
        return [g]

    def test_previous_status_latest_across_graph_versions(self):
        """회귀(Claude 4): v1 confirmed -> v2에서 rejected -> v3의 previous_status는 rejected(옛 confirmed가 아님)."""
        c = [chunk("chunk-1", "RC-PV101")]
        k1 = link.generate(c, self._graph("v-111111111111"))["candidates"]
        k1[0].update(link_status="confirmed", reviewed_by="r")
        k2 = link.merge(link.generate(c, self._graph("v-222222222222"))["candidates"], k1)
        self.assertEqual(k2[0]["previous_status"], "confirmed")
        k2[0].update(link_status="rejected", reviewed_by="r")
        k3 = link.merge(link.generate(c, self._graph("v-333333333333"))["candidates"], k2)
        self.assertEqual([(r["link_status"], r["previous_status"]) for r in k3],
                         [("candidate", "rejected"), ("rejected", "confirmed"), ("confirmed", None)])

    def test_blanked_previous_status_is_recomputed_from_history(self):
        """Codex 재현: 기각 후보를 도면 버전 변경으로 다시 생성하고 새 행의 previous_status만 비우면
        일괄 확인 대상에서 빠지고, 사람이 confirmed로 바꿔도 반영이 거부된다."""
        c = [chunk("chunk-1", "RC-PV101")]
        k1 = link.generate(c, self._graph("v-111111111111"))["candidates"]
        k1[0].update(link_status="rejected", reviewed_by="r")
        cur = link.generate(c, self._graph("v-222222222222"))["candidates"]
        k2 = link.merge(cur, k1)
        self.assertEqual(link.history_status(k2)[0], "rejected")
        k2[0]["previous_status"] = None
        self.assertEqual(link.confirm_exact(k2, cur, "검토자", "일괄", "2026-11-05"), 0)
        self.assertEqual(k2[0]["link_status"], "candidate")
        k2[0].update(link_status="confirmed", reviewed_by="검토자", reason="일괄")
        with self.assertRaises(link.LinkError):
            link.apply_confirmed(k2, cur, [])
        k2[0]["previous_status"] = "rejected"  # 이력과 같으면 한 건씩 확인한 것으로 반영
        self.assertEqual(len(link.apply_confirmed(k2, cur, [])["add"]), 1)

    def test_stale_not_repeated_after_reconfirmation(self):
        c = [chunk("chunk-1", "RC-PV101")]
        k1 = link.generate(c, self._graph("v-111111111111"))["candidates"]
        k1[0].update(link_status="confirmed", reviewed_by="r")
        cur = link.generate(c, self._graph("v-222222222222"))["candidates"]
        k2 = link.merge(cur, k1)
        self.assertEqual(link.apply_confirmed(k2, cur, [])["stale"], [k1[0]["candidate_key"]])
        k2[0].update(link_status="confirmed", reviewed_by="r")
        res = link.apply_confirmed(k2, cur, [])
        self.assertEqual((res["stale"], len(res["add"])), ([], 1))


class Cli(unittest.TestCase):

    def test_rejected_but_linked_exit_code_and_row_kept(self):
        """기각했는데 이미 반영된 관계: 행은 지우지 않고 종료 코드 1과 조치 안내."""
        tmp = tempfile.mkdtemp()
        try:
            shutil.copytree(SAMPLE_DIR, os.path.join(tmp, "in", "P"))
            gdir = os.path.join(tmp, "graphs", "SNP-M-102")
            os.makedirs(gdir)
            with open(os.path.join(gdir, "graph.json"), "w", encoding="utf-8") as fh:
                json.dump(pid_graph(), fh, ensure_ascii=False)
            d = os.path.join(tmp, "in", "P")
            cpath = os.path.join(d, link.CANDIDATES_CSV)
            rows = link.read_candidates(cpath)
            for r in rows:
                if r["match_text"] == "RC-PV101":
                    r.update(link_status="rejected", reason="재검토 결과 기각")
            link.write_candidates(cpath, rows)
            lpath = os.path.join(d, link.LINKS_CSV)
            with open(lpath, "rb") as fh:
                before = fh.read()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = link_kg.main(["apply", "P", "--input-root", os.path.join(tmp, "in"),
                                   "--graph-root", os.path.join(tmp, "graphs"), "--graph-id", "graph-SNP-M-102"])
            self.assertEqual(rc, 1)
            self.assertIn("krel-m-8d0c926c", out.getvalue())
            self.assertIn("rejected로 고칠 것", out.getvalue())
            with open(lpath, "rb") as fh:
                self.assertEqual(fh.read(), before)
            # 안내대로 knowledge_links.csv의 해당 행 link_status를 rejected로 고치면 조치 대상이 아님(rc=0)
            fixed = before.replace(b"krel-m-8d0c926c,mentions,chunk-001,graph-SNP-M-102:RC-PV101,exact_norm,confirmed,confirmed,",
                                   b"krel-m-8d0c926c,mentions,chunk-001,graph-SNP-M-102:RC-PV101,exact_norm,confirmed,rejected,")
            self.assertNotEqual(fixed, before)
            with open(lpath, "wb") as fh:
                fh.write(fixed)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = link_kg.main(["apply", "P", "--input-root", os.path.join(tmp, "in"),
                                   "--graph-root", os.path.join(tmp, "graphs"), "--graph-id", "graph-SNP-M-102"])
            self.assertEqual(rc, 0)
            self.assertNotIn("rejected로 고칠 것", out.getvalue())
            with open(lpath, "rb") as fh:
                self.assertEqual(fh.read(), fixed)
        finally:
            shutil.rmtree(tmp)


class Files(unittest.TestCase):

    def test_atomic_write_and_append_keep_existing_bytes(self):
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(SAMPLE_DIR, link.LINKS_CSV)
            dst = os.path.join(tmp, link.LINKS_CSV)
            shutil.copy(src, dst)
            with open(src, "rb") as fh:
                before = fh.read()
            link.append_links(dst, [])
            with open(dst, "rb") as fh:
                self.assertEqual(fh.read(), before)
            rows = link.generate([chunk("chunk-1", "RC-PV101")], [pid_graph()])["candidates"]
            link.append_links(dst, [link.mention_row(dict(rows[0], reviewed_by="r"))])
            with open(dst, "rb") as fh:
                after = fh.read()
            self.assertTrue(after.startswith(before) and after.endswith(b"\n") and b"\r\n" not in after)
            self.assertEqual(os.listdir(tmp), [link.LINKS_CSV])  # 임시 파일 남지 않음
            path = os.path.join(tmp, link.CANDIDATES_CSV)
            link.write_candidates(path, rows)
            self.assertEqual(link.read_candidates(path), rows)
        finally:
            shutil.rmtree(tmp)

    def test_append_follows_header_order_crlf_no_bom(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, link.LINKS_CSV)
            cols = list(reversed(inputs.LINK_COLUMNS))
            before = ("# 주석\r\n" + ",".join(cols) + "\r\n").encode("utf-8")
            with open(path, "wb") as fh:
                fh.write(before)
            rows = link.generate([chunk("chunk-1", "RC-PV101")], [pid_graph()])["candidates"]
            m = link.mention_row(dict(rows[0], reviewed_by="r"))
            link.append_links(path, [m])
            with open(path, "rb") as fh:
                after = fh.read()
            self.assertTrue(after.startswith(before) and after.endswith(b"\r\n"))
            self.assertEqual(after.count(b"\n"), after.count(b"\r\n"))
            self.assertEqual(inputs.read_csv(path, inputs.LINK_COLUMNS), [m])
        finally:
            shutil.rmtree(tmp)

    def test_write_candidates_keeps_head_comment(self):
        with open(os.path.join(SAMPLE_DIR, link.CANDIDATES_CSV), encoding="utf-8-sig") as fh:
            self.assertTrue(fh.readline().startswith("# 가상(fictitious) 샘플"))
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, link.CANDIDATES_CSV)
            shutil.copy(os.path.join(SAMPLE_DIR, link.CANDIDATES_CSV), path)
            rows = link.generate([chunk("chunk-1", "RC-PV101")], [pid_graph()])["candidates"]
            link.write_candidates(path, rows)
            with open(path, encoding="utf-8-sig") as fh:
                self.assertTrue(fh.readline().startswith("# 가상(fictitious) 샘플"))
            new = os.path.join(tmp, "new.csv")
            link.write_candidates(new, rows)
            with open(new, encoding="utf-8-sig") as fh:
                self.assertEqual(fh.read(len(link.HEADER_COMMENT)), link.HEADER_COMMENT)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
