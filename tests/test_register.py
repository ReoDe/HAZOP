"""단계 ① 자료 등록 테스트(기획서/자료등록.md 독립 검증 MVP 8사례 + 추출 연결 + 대상 매핑).
실행: python -m unittest discover -s tests -t .  샘플 파일과 임시 저장 폴더만 쓴다.
"""

import glob
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import build_graph  # noqa: E402
import extract_drawio  # noqa: E402
import register as register_cli  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.register import registry  # noqa: E402
from tests.test_extract_drawio import compress  # noqa: E402

SAMPLES = sorted(glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*.drawio")))
SAMPLE_101 = [p for p in SAMPLES if "SNP-M-101" in p][0]
PDF_101 = glob.glob(os.path.join(os.path.dirname(SAMPLE_101), "*.pdf"))[0]
NOW = lambda: "2026-11-04T00:00:00+00:00"  # noqa: E731


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class RegisterBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = os.path.join(self.tmp, "store")

    def put(self, data, name="sample.drawio", sub="in"):
        d = os.path.join(self.tmp, sub)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def reg(self, path, **kw):
        kw.setdefault("store_root", self.store)
        kw.setdefault("actor", "tester")
        kw.setdefault("now", NOW)
        return registry.register(path, "proj-1", **kw)

    def index(self):
        with open(os.path.join(self.store, "proj-1", "registry.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def stored_files(self):
        root = os.path.join(self.store, "proj-1", "originals")
        return sorted(os.path.relpath(os.path.join(d, f), root).replace("\\", "/")
                      for d, _, fs in os.walk(root) for f in fs)

    def assert_failed_not_stored(self, result, check):
        rec = result["record"]
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(rec["status"], "failed")
        self.assertEqual(rec["validation"]["status"], "blocked")
        self.assertIn(check, [b["check"] for b in rec["validation"]["blockers"]])
        self.assertIsNone(rec["material_id"])
        self.assertFalse(os.path.exists(os.path.join(self.store, "proj-1")))  # 아무것도 저장·발급하지 않음


class MvpCaseTest(RegisterBase):
    """자료등록.md 독립 검증 MVP 사례."""

    def test_1_normal_drawio(self):
        before = read_bytes(SAMPLE_101)
        r = self.reg(SAMPLE_101)
        rec = r["record"]
        self.assertEqual((r["outcome"], rec["status"], rec["validation"]["status"]),
                         ("registered", "registered", "passed"))
        sha = registry.sha256_of(before)
        self.assertEqual(rec["sha256"], sha)
        self.assertEqual(rec["material_id"], "material-" + sha[:12])  # 결정적 발급
        self.assertEqual(rec["registration_version"], 1)
        self.assertEqual((rec["format"], rec["material_type"], rec["project_id"]), ("drawio", "P&ID", "proj-1"))
        self.assertEqual(rec["storage_ref"], "originals/%s/1/%s" % (rec["material_id"], os.path.basename(SAMPLE_101)))
        self.assertEqual(rec["documents"], [{"document_id": "document-001", "page_ids": ["p1"],
                                             "pages": [{"page_id": "p1", "page_name": "SNP-M-101",
                                                        "compressed": False}]}])
        # 등록정보 파일 = 반환값, 다음 단계 참조로 사용 가능
        with open(r["registration_file"], encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), rec)
        got, original = registry.load_for_extraction(r["registration_file"])
        self.assertEqual(read_bytes(original), before)
        self.assertEqual(read_bytes(SAMPLE_101), before)  # 원본 변경 없음
        self.assertEqual([h["action"] for h in rec["history"]], ["register", "storage_verified"])
        self.assertEqual(rec["history"][0]["by"], "tester")
        self.assertEqual(self.index()["materials"], [{"material_id": rec["material_id"], "sha256": sha,
                                                      "original_name": rec["original_name"],
                                                      "status": "registered", "versions": [1]}])

    def test_2_compressed_drawio(self):
        with open(SAMPLE_101, encoding="utf-8") as fh:
            plain = fh.read()
        r = self.reg(self.put(compress(plain)))
        rec = r["record"]
        self.assertEqual(rec["status"], "registered")
        self.assertTrue(rec["compressed"])
        self.assertEqual(rec["documents"][0]["page_ids"], ["p1"])
        normal = self.reg(SAMPLE_101)["record"]
        self.assertEqual(rec["auto_candidates"], normal["auto_candidates"])  # 같은 표제란 후보를 읽음

    def test_3_damaged_or_empty(self):
        self.assert_failed_not_stored(self.reg(self.put(b"")), "empty_file")
        text = read_bytes(SAMPLE_101)
        self.assert_failed_not_stored(self.reg(self.put(text[: len(text) // 2], "half.drawio")), "unreadable")
        bad_zip = '<mxfile><diagram id="p1" name="x">bm90LWRlZmxhdGU=</diagram></mxfile>'
        self.assert_failed_not_stored(self.reg(self.put(bad_zip, "badzip.drawio")), "unreadable")
        self.assert_failed_not_stored(self.reg(self.put(b"\x00\x01garbage", "bin.drawio")), "unreadable")

    def test_4_extension_format_mismatch(self):
        self.assert_failed_not_stored(self.reg(self.put(read_bytes(PDF_101), "pdf_as.drawio")), "format_mismatch")
        self.assert_failed_not_stored(self.reg(self.put(read_bytes(SAMPLE_101), "drawio_as.xml")),
                                      "format_mismatch")
        self.assert_failed_not_stored(self.reg(self.put(b"<svg xmlns='x'/>", "svg_as.drawio")), "format_mismatch")

    def test_5_same_original_reused(self):
        first = self.reg(SAMPLE_101)
        again = self.reg(SAMPLE_101)
        renamed = self.reg(self.put(read_bytes(SAMPLE_101), "other-name.drawio"))  # 이름이 달라도 같은 내용
        for r in (again, renamed):
            self.assertEqual(r["outcome"], "reused")
            self.assertEqual(r["record"]["material_id"], first["record"]["material_id"])
            self.assertEqual(r["record"]["registration_version"], 1)
            self.assertEqual(r["registration_file"], first["registration_file"])
        self.assertEqual(len(self.index()["materials"]), 1)
        self.assertEqual(len(self.stored_files()), 1)

    def test_5b_reuse_checks_stored_original(self):
        r = self.reg(SAMPLE_101)
        _, stored = registry.load_for_extraction(r["registration_file"])
        with open(stored, "ab") as fh:
            fh.write(b"tampered")
        again = self.reg(SAMPLE_101)
        self.assertEqual((again["outcome"], again["record"]["status"]), ("failed", "failed"))  # 일치
        self.assertEqual(again["record"]["validation"]["blockers"][0]["check"], "stored_hash_mismatch")
        self.assertTrue(read_bytes(stored).endswith(b"tampered"))  # 덮어쓰지 않음
        entry = self.index()["materials"][0]
        self.assertEqual((entry["status"], entry["problems"][0]["check"]), ("failed", "stored_hash_mismatch"))
        with open(r["registration_file"], encoding="utf-8") as fh:  # 완료된 버전 스냅샷은 불변
            self.assertEqual(json.load(fh), r["record"])
        with self.assertRaises(ValueError):
            registry.load_for_extraction(r["registration_file"])

    def test_5c_missing_stored_original_is_restored(self):
        r = self.reg(SAMPLE_101)
        _, stored = registry.load_for_extraction(r["registration_file"])
        os.remove(stored)
        again = self.reg(SAMPLE_101)
        self.assertEqual((again["outcome"], again["record"]["status"]), ("reused", "registered"))
        self.assertTrue(any("복구" in n for n in again["notes"]))
        self.assertEqual(read_bytes(stored), read_bytes(SAMPLE_101))
        self.assertEqual(self.index()["materials"][0]["status"], "registered")

    def test_5d_missing_original_restore_failure_is_recorded(self):
        r = self.reg(SAMPLE_101)
        _, stored = registry.load_for_extraction(r["registration_file"])
        os.remove(stored)
        with mock.patch.object(registry, "_write_new", mock.Mock(side_effect=OSError("모의"))):
            again = self.reg(SAMPLE_101)
        self.assertEqual((again["outcome"], again["record"]["status"]), ("failed", "failed"))
        self.assertEqual(self.index()["materials"][0]["status"], "failed")
        fixed = self.reg(SAMPLE_101)  # 복구 후 재등록: 같은 ID·버전, 상태 복원
        self.assertEqual((fixed["outcome"], fixed["record"]["registration_version"]), ("reused", 1))
        self.assertEqual(self.index()["materials"][0]["status"], "registered")
        self.assertNotIn("problems", self.index()["materials"][0])

    def test_storage_conflict_not_overwritten(self):
        data = read_bytes(SAMPLE_101)
        mid = "material-" + registry.sha256_of(data)[:12]
        dest = os.path.join(self.store, "proj-1", "originals", mid, "1", os.path.basename(SAMPLE_101))
        os.makedirs(os.path.dirname(dest))
        with open(dest, "wb") as fh:
            fh.write(b"other content")
        r = self.reg(SAMPLE_101)
        self.assertEqual((r["outcome"], r["record"]["status"]), ("failed", "failed"))
        self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "storage_conflict")
        self.assertEqual(read_bytes(dest), b"other content")

    def test_id_collision_is_on_hold(self):
        real = registry.sha256_of
        fake = lambda d: "0" * 12 + real(d)[12:]  # noqa: E731  앞 12자리를 강제로 같게
        text = read_bytes(SAMPLE_101)
        with mock.patch.object(registry, "sha256_of", fake):
            a = self.reg(SAMPLE_101)
            b = self.reg(self.put(text.replace(b"RC-PP01", b"RC-PP09")))
        self.assertEqual(a["record"]["material_id"], "material-000000000000")
        self.assertEqual((b["outcome"], b["record"]["status"]), ("on_hold", "on_hold"))
        self.assertEqual(b["record"]["validation"]["blockers"][0]["check"], "id_collision")
        self.assertEqual(len(self.index()["materials"]), 1)
        with open(a["registration_file"], encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["sha256"], a["record"]["sha256"])  # 기존 등록 그대로
        self.assertEqual(len(self.stored_files()), 1)

    def test_registered_snapshot_is_immutable(self):
        r = self.reg(SAMPLE_101)
        store = registry.Store(self.store, "proj-1")
        with self.assertRaises(RuntimeError):
            registry._write_snapshot(store, dict(r["record"], title="변경"))

    def test_6_same_name_different_content(self):
        text = read_bytes(SAMPLE_101)
        a = self.reg(self.put(text, "sample.drawio", "a"))
        b = self.reg(self.put(text.replace(b"RC-PP01", b"RC-PP09"), "sample.drawio", "b"))
        self.assertEqual((a["outcome"], b["outcome"]), ("registered", "registered"))
        self.assertNotEqual(a["record"]["material_id"], b["record"]["material_id"])
        self.assertEqual(len(self.index()["materials"]), 2)
        files = self.stored_files()
        self.assertEqual(len(files), 2)
        self.assertTrue(all(f.endswith("/sample.drawio") for f in files))
        for r in (a, b):  # 서로 덮어쓰지 않음
            _, stored = registry.load_for_extraction(r["registration_file"])
            self.assertEqual(registry.sha256_of(read_bytes(stored)), r["record"]["sha256"])

    def test_7_unknown_numbers(self):
        # 표제란이 없는 도면: 후보 없음, 내부 ID로 등록, 미확인 전달
        text = re.sub(r'<mxCell id="tb\d+"[^>]*>.*?</mxCell>', "", read_bytes(SAMPLE_101).decode("utf-8"),
                      flags=re.S)
        r = self.reg(self.put(text, "SNP-M-101.drawio"))  # 파일명에 번호가 있어도 확정하지 않음
        rec = r["record"]
        self.assertEqual(rec["status"], "registered")
        self.assertEqual(rec["auto_candidates"], {})
        self.assertEqual((rec["drawing_number"], rec["design_revision"], rec["title"]), (None, None, None))
        self.assertEqual(sorted(u["field"] for u in rec["validation"]["unknowns"]),
                         ["design_revision", "drawing_number", "title"])
        self.assertTrue(all("후보 없음" in u["reason"] for u in rec["validation"]["unknowns"]))
        # 표제란이 있으면 자동 후보로만 기록, 확정값은 미확인
        rec = self.reg(SAMPLE_101)["record"]
        self.assertIsNone(rec["drawing_number"])
        self.assertEqual(rec["auto_candidates"]["drawing_number"],
                         {"value": "SNP-M-101", "source": "title_block", "page_id": "p1",
                          "key_object_id": "tb10", "value_object_id": "tb11"})
        self.assertEqual(rec["auto_candidates"]["design_revision"]["value"], "0")

    def test_8_storage_failure_then_retry(self):
        def boom(path, data):
            raise OSError("디스크 가득 참(모의)")
        with mock.patch.object(registry, "_write_new", boom):
            r = self.reg(SAMPLE_101)
        rec = r["record"]
        self.assertEqual((r["outcome"], rec["status"]), ("failed", "failed"))
        self.assertEqual(rec["validation"]["blockers"][0]["check"], "storage_failed")
        self.assertEqual(self.index()["materials"][0]["status"], "failed")  # 미완료 기록
        with self.assertRaises(ValueError):
            registry.load_for_extraction(r["registration_file"])  # 추출 전달 금지
        retry = self.reg(SAMPLE_101)
        self.assertEqual(retry["outcome"], "registered")
        self.assertEqual((retry["record"]["material_id"], retry["record"]["registration_version"]),
                         (rec["material_id"], 1))  # 재시도로 중복 없음
        self.assertEqual(self.index()["materials"][0]["versions"], [1])
        self.assertEqual(len(self.index()["materials"]), 1)
        self.assertIn("retry", [h["action"] for h in retry["record"]["history"]])
        registry.load_for_extraction(retry["registration_file"])

    def test_8b_hash_mismatch_after_store_then_retry(self):
        real = registry._write_new

        def corrupt(path, data):
            real(path, data + b"x")
        with mock.patch.object(registry, "_write_new", corrupt):
            r = self.reg(SAMPLE_101)
        self.assertEqual(r["record"]["status"], "failed")
        self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "stored_hash_mismatch")
        self.assertEqual(self.stored_files(), [])  # 잘못된 사본은 남기지 않음
        with self.assertRaises(ValueError):
            registry.load_for_extraction(r["registration_file"])
        retry = self.reg(SAMPLE_101)
        self.assertEqual(retry["record"]["status"], "registered")
        self.assertEqual(len(self.stored_files()), 1)
        self.assertEqual(len(self.index()["materials"]), 1)


class MetadataTest(RegisterBase):

    def test_human_confirmation_creates_version_with_history(self):
        v1 = self.reg(SAMPLE_101)
        meta = {"drawing_number": "SNP-M-101", "design_revision": "0", "by": "검토자", "reason": "표제란 대조"}
        v2 = self.reg(SAMPLE_101, metadata=meta)
        rec = v2["record"]
        self.assertEqual((v2["outcome"], rec["registration_version"]), ("new_version", 2))
        self.assertEqual(rec["storage_ref"], v1["record"]["storage_ref"])  # 같은 원본·해시 사용
        self.assertEqual((rec["drawing_number"], rec["design_revision"], rec["title"]), ("SNP-M-101", "0", None))
        self.assertEqual([u["field"] for u in rec["validation"]["unknowns"]], ["title"])
        hist = [h for h in rec["history"] if h["action"] == "confirm_metadata"]
        self.assertEqual(hist[0], {"at": NOW(), "by": "검토자", "action": "confirm_metadata",
                                   "field": "drawing_number", "before": None, "after": "SNP-M-101",
                                   "reason": "표제란 대조"})
        with open(v1["registration_file"], encoding="utf-8") as fh:  # 이전 버전은 그대로
            self.assertIsNone(json.load(fh)["drawing_number"])
        again = self.reg(SAMPLE_101, metadata=meta)
        self.assertEqual((again["outcome"], again["record"]["registration_version"]), ("reused", 2))
        self.assertEqual(self.index()["materials"][0]["versions"], [1, 2])

    def test_invalid_input_is_on_hold(self):
        for kw in ({"metadata": {"drawing_no": "X"}}, {"metadata": {"title": ""}},
                   {"material_type": "PFD"}):
            r = self.reg(SAMPLE_101, **kw)
            self.assertEqual((r["outcome"], r["record"]["status"]), ("on_hold", "on_hold"))
        for pid in ("../bad", os.path.join(self.tmp, "abs"), "C:/abs", ".", "", None, "CON"):
            r = registry.register(SAMPLE_101, pid, store_root=self.store, actor="t")
            self.assertEqual(r["record"]["status"], "on_hold", pid)
            self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "invalid_project_id")
        self.assertFalse(os.path.exists(self.store))

    def test_cli_args_and_metadata_json(self):
        meta = self.put(json.dumps({"drawing_number": "SNP-M-101", "title": "T"}), "meta.json")
        base = [SAMPLE_101, "--project", "proj-1", "--store-root", self.store, "--by", "cli"]
        self.assertEqual(register_cli.main(base + ["--metadata", meta, "--revision", "0"]), 0)
        with open(os.path.join(self.store, "proj-1", "registrations", "material-" +
                               registry.sha256_of(read_bytes(SAMPLE_101))[:12], "1.json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual((rec["drawing_number"], rec["design_revision"], rec["title"]), ("SNP-M-101", "0", "T"))
        # 같은 항목을 인자와 JSON에 다르게 주면 보류
        self.assertEqual(register_cli.main(base + ["--metadata", meta, "--drawing-number", "OTHER"]), 1)
        self.assertEqual(register_cli.main([self.put(b""), "--project", "proj-1", "--store-root", self.store]), 1)


class ExtractionLinkTest(RegisterBase):

    def test_extract_with_registration_fills_ids(self):
        r = self.reg(SAMPLE_101)
        record, original = registry.load_for_extraction(r["registration_file"])
        ex = drawio.extract(original, registration=record)
        self.assertEqual(ex["project_id"], "proj-1")
        self.assertEqual((ex["source"]["material_id"], ex["source"]["registration_version"]),
                         (record["material_id"], 1))
        self.assertEqual(ex["source_context"]["document_id"], "document-001")
        checks = [u["check"] for u in ex["validation"]["unknowns"]]
        self.assertNotIn("not_registered", checks)
        self.assertEqual(sorted(u["field"] for u in ex["validation"]["unknowns"]
                                if u["check"] == "registration_unknown"),
                         ["design_revision", "drawing_number", "title"])
        self.assertEqual(ex["validation"]["status"], "passed")
        self.assertIn(record["material_id"] + "-r1", ex["extraction_run_id"])
        # 등록 없는 기존 경로는 그대로
        plain = drawio.extract(SAMPLE_101)
        self.assertEqual(plain["nodes"], ex["nodes"])
        self.assertEqual(sorted(u["field"] for u in plain["validation"]["unknowns"] if u["check"] == "not_registered"),
                         ["material_id", "project_id", "registration_version"])

    def test_registration_page_mismatch_blocks_extraction(self):
        record = self.reg(SAMPLE_101)["record"]
        docs = [dict(record["documents"][0], page_ids=["other-page"])]
        ex = drawio.extract(SAMPLE_101, registration=dict(record, documents=docs))
        self.assertEqual(ex["validation"]["status"], "blocked")
        self.assertIn("registration_page_mismatch", [b["check"] for b in ex["validation"]["blockers"]])

    def test_registration_hash_mismatch_blocks_extraction(self):
        record = self.reg(SAMPLE_101)["record"]
        ex = drawio.extract(SAMPLE_101, registration=dict(record, sha256="0" * 64))
        self.assertEqual(ex["validation"]["status"], "blocked")

    def test_cli_extract_and_graph_mapping(self):
        r = self.reg(SAMPLE_101)
        out_ex, out_g = os.path.join(self.tmp, "ex"), os.path.join(self.tmp, "g")
        self.assertEqual(extract_drawio.main(["--registration", r["registration_file"], "--out-root", out_ex]), 0)
        with open(os.path.join(out_ex, "SNP-M-101", "extraction.json"), encoding="utf-8") as fh:
            ex = json.load(fh)
        self.assertEqual(ex["source"]["material_id"], r["record"]["material_id"])
        al = ex["coordinate_system"]["svg_alignment"]
        self.assertEqual((al["status"], al["source"]), ("verified", "input_path_sibling, unregistered"))
        graph, out_dir = build_graph.build_one(os.path.join(out_ex, "SNP-M-101", "extraction.json"), out_g)
        with open(os.path.join(out_dir, "entity_mapping.json"), encoding="utf-8") as fh:
            m = json.load(fh)
        self.assertEqual((m["project_id"], m["graph_id"], m["graph_version"], m["input_runs"]),
                         ("proj-1", graph["graph_id"], graph["graph_version"], graph["input_runs"]))
        obj = {x["local_id"]: x["source_object_id"] for x in ex["nodes"] + ex["relations"]}
        self.assertEqual(len(m["entity_mapping"]), len(graph["entity_mapping"]))
        for got, base in zip(m["entity_mapping"], graph["entity_mapping"]):
            self.assertEqual({k: got[k] for k in base}, base)  # ③ -> ④ 규격 항목 그대로
            self.assertEqual((got["source_object_id"], got["material_id"], got["registration_version"]),
                             (obj[got["local_id"]], r["record"]["material_id"], 1))
        self.assertEqual(json.dumps(build.entity_mapping_document(graph, ex), sort_keys=True),
                         json.dumps(m, sort_keys=True))  # 같은 입력 같은 결과

    def test_failed_registration_rejected_by_extract_cli(self):
        with mock.patch.object(registry, "_write_new", mock.Mock(side_effect=OSError("모의"))):
            r = self.reg(SAMPLE_101)
        with self.assertRaises(SystemExit):
            extract_drawio.main(["--registration", r["registration_file"], "--out-root", self.tmp])


if __name__ == "__main__":
    unittest.main()
