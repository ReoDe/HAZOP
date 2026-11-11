"""단계 ① 자료 등록 테스트(기획서/자료등록.md 독립 검증 MVP 8사례 + 추출 연결 + 대상 매핑).
실행: python -m unittest discover -s tests -t .  샘플 파일과 임시 저장 폴더만 쓴다.
"""

import contextlib
import glob
import io
import importlib.util
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
import build_viewer  # noqa: E402
import extract_drawio  # noqa: E402
import register as register_cli  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.register import registry  # noqa: E402
from tests.test_extract_drawio import compress  # noqa: E402

SAMPLES = sorted(glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio")))
SAMPLE_101 = [p for p in SAMPLES if "SNP-M-101" in p][0]
PDF_101 = glob.glob(os.path.join(os.path.dirname(SAMPLE_101), "*.pdf"))[0]
HAS_PDFPLUMBER = importlib.util.find_spec("pdfplumber") is not None
DESIGN_DOC = glob.glob(os.path.join(REPO_ROOT, "tests", "fixtures", "docextract", "*.pdf"))[0]  # 가상 설계 문서


def minimal_pdf(content, mediabox="0 0 300 300"):
    """한 쪽짜리 PDF 바이트(Helvetica 글꼴 F1, 내용 스트림 content)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [%s] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
            % mediabox.encode(),
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
NOW = lambda:"2026-11-04T00:00:00+00:00"  # noqa: E731


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
        """보관 원본 목록(파생 SVG derived/는 제외)."""
        root = os.path.join(self.store, "proj-1", "originals")
        return sorted(os.path.relpath(os.path.join(d, f), root).replace("\\", "/")
                      for d, _, fs in os.walk(root) for f in fs if os.path.basename(d) != "derived")

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
        # 임시 폴더에 SVG 없이 둔 도면이므로 'SVG 없음'(derived_files)도 함께 남는다
        meta_unknowns = [u for u in rec["validation"]["unknowns"] if u["field"] != registry.NO_SVG_FIELD]
        self.assertEqual(sorted(u["field"] for u in meta_unknowns), ["design_revision", "drawing_number", "title"])
        self.assertTrue(all("후보 없음" in u["reason"] for u in meta_unknowns))
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
        self.assertIn("-proj-1-%s-r1" % record["material_id"], ex["extraction_run_id"])
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
        name = "proj-1__%s-r1-p0" % r["record"]["material_id"]
        with open(os.path.join(out_ex, name, "extraction.json"), encoding="utf-8") as fh:
            ex = json.load(fh)
        self.assertEqual(ex["source"]["material_id"], r["record"]["material_id"])
        al = ex["coordinate_system"]["svg_alignment"]
        self.assertEqual((al["status"], al["source"]), ("verified", "registered_derived"))  # 등록된 파생 SVG 우선
        graph, out_dir = build_graph.build_one(os.path.join(out_ex, name, "extraction.json"), out_g)
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


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(결정 D1: 전용 venv에서 실행)")
class PdfRegisterTest(RegisterBase):
    """벡터 PDF 등록 → 등록정보 반영 추출 → ① 자동 추출 흐름(사용자 결정 2026-11-06)."""

    def test_pdf_registers_without_sibling_svg(self):
        self.assertTrue(glob.glob(os.path.join(os.path.dirname(PDF_101), "*.drawio.svg")))  # 옆에 drawio SVG가 있음
        before = read_bytes(PDF_101)
        r = self.reg(PDF_101)
        rec = r["record"]
        self.assertEqual((r["outcome"], rec["status"], rec["validation"]["status"]),
                         ("registered", "registered", "passed"))
        self.assertEqual(rec["format"], "pdf")
        self.assertEqual(rec["documents"][0]["page_ids"], ["page-1"])
        self.assertFalse(rec.get("derived_files"))
        self.assertNotIn(registry.NO_SVG_FIELD, [u["field"] for u in rec["validation"]["unknowns"]])
        self.assertEqual(rec["auto_candidates"]["drawing_number"]["value"], "SNP-M-101")
        _, original = registry.load_for_extraction(r["registration_file"])
        self.assertEqual(read_bytes(original), before)

    def test_pdf_extension_with_non_pdf_bytes_fails(self):
        for data, name in ((read_bytes(SAMPLE_101), "drawio_as.pdf"), (b"\x89PNG\r\n\x1a\n0000", "png_as.pdf"),
                           (b"\x00\x01garbage", "bin.pdf")):
            with self.subTest(name=name):
                self.assert_failed_not_stored(self.reg(self.put(data, name)), "format_mismatch")

    def test_pdf_without_vector_content_fails(self):
        """스캔 PDF처럼 글자·벡터가 없는 PDF는 등록하지 않는다(이미지 등록 제외)."""
        self.assert_failed_not_stored(self.reg(self.put(minimal_pdf(b""), "empty.pdf")), "no_vector_content")

    def test_rendered_svg_matches_extraction_coordinates_with_offset_mediabox(self):
        """MediaBox 원점이 0이 아니어도 배경 SVG의 글자·선이 추출 좌표(pdfplumber)와 같은 자리에 놓인다."""
        import io
        import pdfplumber
        from hazop.extract.adapters import pdf_svg
        data = minimal_pdf(b"BT /F1 20 Tf 30 100 Td (AB) Tj ET 0 0 m 100 100 l S", "-20 -10 400 300")
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            ch, page = pdf.pages[0].chars[0], pdf.pages[0]
            line = (page.lines or page.curves)[0]["pts"]
        svg = pdf_svg.render_page_svg(io.BytesIO(data))
        x, y = map(float, re.search(r'<text transform="matrix\([^ ]+ [^ ]+ [^ ]+ [^ ]+ ([^ ]+) ([^ )]+)\)', svg).groups())
        self.assertAlmostEqual(x, ch["x0"], places=2)
        self.assertTrue(ch["top"] < y <= ch["bottom"], (y, ch["top"], ch["bottom"]))
        self.assertIn('d="M%g %g L%g %g"' % (line[0] + line[1]), svg)
        vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
        self.assertTrue(vb[0] <= ch["x0"] <= vb[0] + vb[2] and vb[1] <= ch["top"] <= vb[1] + vb[3], vb)

    def registered_pdf(self):
        meta = {"drawing_number": "REG-DN-1", "design_revision": "B", "title": "등록 제목", "by": "검토자",
                "reason": "표제란 대조"}
        record, original = registry.load_for_extraction(self.reg(PDF_101, metadata=meta)["registration_file"])
        return record, original

    def test_apply_registration_uses_registered_ids_only(self):
        record, original = self.registered_pdf()
        ex = pdf_vector.extract(original, registration=record)
        d = ex["drawing"]
        self.assertEqual((d["drawing_number"], d["revision"], d["title"]), ("REG-DN-1", "B", "등록 제목"))
        self.assertEqual(d["title_block_candidates"]["drawing_number"], "SNP-M-101")  # 표제란 값은 후보로만
        self.assertEqual(ex["project_id"], "proj-1")
        self.assertEqual((ex["source"]["material_id"], ex["source"]["registration_version"]),
                         (record["material_id"], record["registration_version"]))
        self.assertEqual(ex["source_context"]["document_id"], "document-001")
        self.assertNotIn("not_registered", [u["check"] for u in ex["validation"]["unknowns"]])
        self.assertEqual(ex["validation"]["status"], "passed")
        plain = pdf_vector.extract(original)
        self.assertIn("not_registered", [u["check"] for u in plain["validation"]["unknowns"]])
        self.assertEqual(plain["drawing"]["drawing_number"], "SNP-M-101")

    def test_apply_registration_blockers(self):
        record, original = self.registered_pdf()
        docs = [dict(record["documents"][0], page_ids=["page-2"])]
        cases = {"registration_hash_mismatch": dict(record, sha256="0" * 64),
                 "registration_page_mismatch": dict(record, documents=docs),
                 "registration_not_completed": dict(record, status="on_hold")}
        for check, reg in cases.items():
            with self.subTest(check=check):
                ex = pdf_vector.extract(original, registration=reg)
                self.assertEqual(ex["validation"]["status"], "blocked")
                self.assertEqual([b["check"] for b in ex["validation"]["blockers"]], [check])

    def test_extract_and_graph_pdf_flow(self):
        from hazop.app import data
        work = os.path.join(self.tmp, "work")
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": work, "HAZOP_STORE_ROOT": self.store}):
            r = self.reg(PDF_101)
            out = data.extract_and_graph(r["registration_file"])
            name = extract_drawio.registered_out_name(r["record"], 0)
            self.assertEqual(out["extract_dir"], paths.output_in(work, "extract", name))
            self.assertTrue(os.path.isfile(os.path.join(out["extract_dir"], "page.svg")))
            with open(os.path.join(out["extract_dir"], "extraction.json"), encoding="utf-8") as fh:
                al = json.load(fh)["coordinate_system"]["svg_alignment"]
            self.assertEqual((al["source"], al["offset"], al["status"]), ("rendered_from_pdf", [0, 0], "verified"))
            self.assertEqual(out["graph"]["validation"]["status"], "passed")
            info = data.viewer_html_for(name)
            self.assertIsNone(info["error"])
            self.assertTrue(info["html"] and os.path.isfile(info["html"]))
            rows = data.list_registrations()
            self.assertEqual([(e["extract_name"], e["extracted"], e["graphed"]) for e in rows], [(name, True, True)])
        self.assertFalse(os.path.exists(paths.output_in(paths.DEV_WORK_ROOT, "extract", name)))

    def test_app_extraction_returns_the_warning_when_the_run_record_cannot_be_written(self):
        """추출 실행 정보(extraction_run.json)를 쓰지 못해도 추출·그래프는 그대로 만들고, 경고는 화면이 보여 줄 수 있게
        결과에 담아 돌려준다."""
        from hazop.app import data
        from hazop.extract import runinfo
        real = runinfo.store_io.write_json

        def write_json(path, *args, **kwargs):
            if os.path.basename(path) == runinfo.FILE_NAME:
                raise PermissionError(13, "denied", path)
            return real(path, *args, **kwargs)
        work = os.path.join(self.tmp, "work")
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": work, "HAZOP_STORE_ROOT": self.store}), \
                mock.patch.object(runinfo.store_io, "write_json", side_effect=write_json), \
                self.assertLogs(runinfo.__name__, "WARNING"):
            out = data.extract_and_graph(self.reg(PDF_101)["registration_file"])
            self.assertEqual(out["graph"]["validation"]["status"], "passed")
            self.assertEqual(len(out["warnings"]), 1)
            self.assertIn(runinfo.FILE_NAME, out["warnings"][0])
            self.assertFalse(os.path.exists(os.path.join(out["extract_dir"], runinfo.FILE_NAME)))

    def test_multi_page_registration_extracts_every_page(self):
        import extract_pdf
        from hazop.app import data
        from tests.test_adapter import merged_pdf
        pdf_102 = glob.glob(paths.folder("references", "pid-samples", "SNP-M-102*", "*.pdf"))[0]
        src = merged_pdf(os.path.join(self.tmp, "merged.pdf"), [PDF_101, pdf_102])
        work = os.path.join(self.tmp, "work")
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": work, "HAZOP_STORE_ROOT": self.store}):
            r = self.reg(src)
            self.assertEqual(r["record"]["documents"][0]["page_ids"], ["page-1", "page-2", "page-3"])
            out = data.extract_and_graph(r["registration_file"])
            names = [extract_drawio.registered_out_name(r["record"], i) for i in range(3)]
            self.assertEqual([p["extract_dir"] for p in out["pages"]],
                             [paths.output_in(work, "extract", n) for n in names[:2]])
            self.assertEqual([p["extraction"]["drawing"]["title_block_candidates"]["drawing_number"]
                              for p in out["pages"]], ["SNP-M-101", "SNP-M-102"])
            self.assertTrue(all(os.path.isfile(os.path.join(p["graph_dir"], "graph.json")) for p in out["pages"]))
            self.assertEqual([(s["page_id"], "글자" in s["reason"]) for s in out["skipped_pages"]], [("page-3", True)])
            self.assertTrue(os.path.isfile(paths.output_in(work, "extract", names[2], extract_pdf.NOT_EXTRACTED)))
            row = data.list_registrations()[0]
            self.assertEqual((row["extracted"], row["pages"]), (True, {"total": 3, "extracted": 2, "skipped": 1}))
            cli_out = os.path.join(self.tmp, "cli")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = extract_pdf.main(["--registration", r["registration_file"], "--out-root", cli_out])
            self.assertEqual(rc, 0)
            self.assertEqual(sorted(os.listdir(cli_out)), sorted(names))
            self.assertTrue(os.path.isfile(os.path.join(cli_out, names[1], "page.svg")))


class ReviewFixTest(RegisterBase):
    """Codex 적대적 검토 A 지적 사항 재현 테스트."""

    def test_p1_index_save_failure_after_draft_then_retry(self):
        real = registry.Store.save_index
        calls = []

        def fail_first(store, index):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("색인 저장 실패(모의)")
            real(store, index)
        with mock.patch.object(registry.Store, "save_index", fail_first):
            with self.assertRaises(OSError):
                self.reg(SAMPLE_101)
        self.assertFalse(os.path.isfile(os.path.join(self.store, "proj-1", "registry.json")))
        retry = self.reg(SAMPLE_101)
        self.assertEqual((retry["outcome"], retry["record"]["status"]), ("registered", "registered"))
        self.assertEqual(retry["record"]["material_id"], "material-" + registry.sha256_of(read_bytes(SAMPLE_101))[:12])
        self.assertEqual([(m["status"], m["versions"]) for m in self.index()["materials"]], [("registered", [1])])
        registry.load_for_extraction(retry["registration_file"])

    def test_p1_index_save_failure_after_metadata_version_then_retry(self):
        self.reg(SAMPLE_101)
        meta = {"drawing_number": "SNP-M-101", "by": "검토자"}
        with mock.patch.object(registry.Store, "save_index", mock.Mock(side_effect=OSError("모의"))):
            with self.assertRaises(OSError):
                self.reg(SAMPLE_101, metadata=meta)
        self.assertEqual(self.index()["materials"][0]["versions"], [1])  # 2.json만 남은 상태
        other = self.reg(SAMPLE_101, metadata={"drawing_number": "DIFFERENT", "by": "검토자"})
        self.assertEqual((other["outcome"], other["record"]["status"]), ("failed", "failed"))
        self.assertEqual(other["record"]["validation"]["blockers"][0]["check"], "version_conflict")
        retry = self.reg(SAMPLE_101, metadata=meta, now=lambda: "2026-11-05T00:00:00+00:00")
        self.assertEqual((retry["outcome"], retry["record"]["registration_version"]), ("new_version", 2))
        self.assertEqual(retry["record"]["drawing_number"], "SNP-M-101")
        self.assertEqual(self.index()["materials"][0]["versions"], [1, 2])

    def test_p1_registered_outputs_kept_per_version(self):
        v1 = self.reg(SAMPLE_101)
        v2 = self.reg(SAMPLE_101, metadata={"drawing_number": "SNP-M-101", "by": "검토자"})
        out_ex, out_g, out_v = (os.path.join(self.tmp, x) for x in ("ex", "g", "v"))
        args = ["--registration", v1["registration_file"], "--registration", v2["registration_file"]]
        self.assertEqual(extract_drawio.main(args + ["--out-root", out_ex]), 0)
        mid = "proj-1__" + v1["record"]["material_id"]
        self.assertEqual(sorted(os.listdir(out_ex)), [mid + "-r1-p0", mid + "-r2-p0"])
        self.assertEqual(build_graph.main(["--extract-root", out_ex, "--out-root", out_g]), 0)
        self.assertEqual(sorted(os.listdir(out_g)), [mid + "-r1-p0", mid + "-r2-p0"])
        entries = build_viewer.build.build_all(out_ex, out_v, paths.work_root(), out_g, svg_roots=[self.store])
        self.assertEqual([e["file"] for e in entries], [mid + "-r1-p0.html", mid + "-r2-p0.html"])
        self.assertTrue(all(e["graph"] for e in entries))  # 뷰어가 같은 이름으로 그래프를 찾음
        for ver in (1, 2):
            with open(os.path.join(out_g, "%s-r%d-p0" % (mid, ver), "entity_mapping.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["entity_mapping"][0]["registration_version"], ver)

    def test_p1_drawing_identification_from_registration_only(self):
        v1 = self.reg(SAMPLE_101)
        record, original = registry.load_for_extraction(v1["registration_file"])
        d = drawio.extract(original, registration=record)["drawing"]
        self.assertEqual((d["drawing_number"], d["revision"], d["title"]), (None, None, None))  # 미확정
        self.assertEqual(d["identification_basis"], "registration_confirmed")
        self.assertEqual(d["title_block_candidates"]["drawing_number"], "SNP-M-101")  # 후보로만
        v2 = self.reg(SAMPLE_101, metadata={"drawing_number": "DWG-CONFIRMED", "design_revision": "A",
                                            "by": "검토자"})
        record, original = registry.load_for_extraction(v2["registration_file"])
        ex = drawio.extract(original, registration=record)
        self.assertEqual((ex["drawing"]["drawing_number"], ex["drawing"]["revision"], ex["drawing"]["title"]),
                         ("DWG-CONFIRMED", "A", None))
        self.assertEqual(ex["drawing"]["title_block_candidates"]["drawing_number"], "SNP-M-101")
        self.assertNotIn("missing_drawing_number", [u["check"] for u in ex["validation"]["unknowns"]])
        self.assertEqual(drawio.extract(SAMPLE_101)["drawing"]["drawing_number"], "SNP-M-101")  # 등록 없는 경로 유지

    def test_p1_cleanup_only_own_files(self):
        data = read_bytes(SAMPLE_101)
        dest = os.path.join(self.store, "proj-1", "originals", "material-" + registry.sha256_of(data)[:12], "1",
                            os.path.basename(SAMPLE_101))

        def race(path, payload):  # 존재 확인 직후 다른 주체가 같은 이름 파일을 만든 상황
            with open(path, "wb") as fh:
                fh.write(b"someone else")
            raise FileExistsError(path)
        with mock.patch.object(registry, "_write_new", race):
            r = self.reg(SAMPLE_101)
        self.assertEqual(r["record"]["status"], "failed")
        self.assertEqual(read_bytes(dest), b"someone else")  # 남의 파일을 지우지 않음
        with self.assertRaises(FileExistsError):  # 실제 _write_new도 기존 파일을 건드리지 않음
            registry._write_new(dest, b"x")
        self.assertEqual(read_bytes(dest), b"someone else")

    def test_p2_extract_checks_registration_status(self):
        with mock.patch.object(registry, "_write_new", mock.Mock(side_effect=OSError("모의"))):
            r = self.reg(SAMPLE_101)
        ex = drawio.extract(SAMPLE_101, registration=r["record"])
        self.assertEqual(ex["validation"]["status"], "blocked")
        self.assertIn("registration_not_completed", [b["check"] for b in ex["validation"]["blockers"]])

    def test_p2_fallback_page_id_in_source_context(self):
        text = read_bytes(SAMPLE_101).decode("utf-8")
        model = re.search(r"<mxGraphModel\b.*</mxGraphModel>", text, re.S).group(0)
        r = self.reg(self.put(model, "model_root.drawio"))
        self.assertEqual(r["record"]["documents"][0]["page_ids"], ["page-1"])
        record, original = registry.load_for_extraction(r["registration_file"])
        ex = drawio.extract(original, registration=record)
        self.assertEqual(ex["source_context"]["page_id"], "page-1")
        self.assertNotIn("registration_page_mismatch", [b["check"] for b in ex["validation"]["blockers"]])

    def test_p2_other_drive_source_path(self):
        with mock.patch("os.path.relpath", side_effect=ValueError("path is on mount 'D:'")):
            ex = drawio.extract(SAMPLE_101, repo_root=REPO_ROOT)
        self.assertEqual(ex["source"]["file"], os.path.abspath(SAMPLE_101).replace("\\", "/"))

    def test_p2_nan_infinity_title_block_coordinate_fails(self):
        text = read_bytes(SAMPLE_101).decode("utf-8")
        for bad in ("NaN", "Infinity", "-inf"):
            broken = re.sub(r'(<mxCell id="tb10"[^>]*><mxGeometry x=")[^"]*', lambda m: m.group(1) + bad, text,
                            count=1)
            self.assertNotEqual(broken, text)
            r = self.reg(self.put(broken, "nan_%s.drawio" % bad.strip("-")))
            self.assertEqual((r["outcome"], r["record"]["status"]), ("failed", "failed"), bad)
            self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "invalid_number")

    def test_p2_utf16_bom_drawio_is_readable(self):
        text = read_bytes(SAMPLE_101).decode("utf-8")
        for name, data in (("le", text.encode("utf-16")), ("be", b"\xfe\xff" + text.encode("utf-16-be"))):
            r = self.reg(self.put(data, "u16_%s.drawio" % name))
            self.assertEqual((r["record"]["status"], r["record"]["format"]), ("registered", "drawio"), name)
            self.assertEqual(r["record"]["auto_candidates"]["drawing_number"]["value"], "SNP-M-101")
        r = self.reg(self.put(text[: len(text) // 2].encode("utf-16"), "u16_broken.drawio"))
        self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "unreadable")


class ReviewFix2Test(RegisterBase):
    """Codex 재검토(A) 2회차 지적 재현 테스트."""

    def two_page_file(self):
        text = read_bytes(SAMPLE_101).decode("utf-8")
        diagram = re.search(r"<diagram\b.*</diagram>", text, re.S).group(0)
        second = diagram.replace('id="p1"', 'id="p2"', 1).replace('name="SNP-M-101"', 'name="PAGE-2"', 1)
        return self.put(text.replace(diagram, diagram + second), "two_pages.drawio")

    def test_p1_outputs_separate_by_project_and_page(self):
        path = self.two_page_file()
        a = self.reg(path)
        b = registry.register(path, "proj-2", store_root=self.store, actor="t", now=NOW)
        self.assertEqual(a["record"]["material_id"], b["record"]["material_id"])  # 같은 원본, 다른 프로젝트
        out_ex, out_g = os.path.join(self.tmp, "ex"), os.path.join(self.tmp, "g")
        for page in ("0", "1"):
            extract_drawio.main(["--registration", a["registration_file"], "--registration", b["registration_file"],
                                 "--page", page, "--svg", "none", "--out-root", out_ex])
        mid = a["record"]["material_id"]
        want = sorted("%s__%s-r1-p%d" % (proj, mid, p) for proj in ("proj-1", "proj-2") for p in (0, 1))
        self.assertEqual(sorted(os.listdir(out_ex)), want)
        runs = set()
        for name in want:
            with open(os.path.join(out_ex, name, "extraction.json"), encoding="utf-8") as fh:
                ex = json.load(fh)
            runs.add(ex["extraction_run_id"])
            self.assertTrue(name.startswith(ex["project_id"] + "__"))
            self.assertEqual(ex["run"]["settings"]["page_index"], int(name[-1]))
        self.assertEqual(len(runs), 4)  # 실행 ID도 프로젝트·페이지별로 다름
        build_graph.main(["--extract-root", out_ex, "--out-root", out_g])
        self.assertEqual(sorted(os.listdir(out_g)), want)

    def test_p1_unfinished_first_snapshot_trace_then_retry(self):
        mid = "material-" + registry.sha256_of(read_bytes(SAMPLE_101))[:12]
        real = os.replace

        def fail_replace(src, dst):
            if dst.endswith(os.path.join("registrations", mid, "1.json")):
                raise OSError("교체 전 중단(모의)")
            return real(src, dst)
        with mock.patch("os.replace", fail_replace):
            with self.assertRaises(OSError):
                self.reg(SAMPLE_101)
        rel = os.path.join("proj-1", "registrations", mid)
        folder = os.path.join(self.store, rel)
        self.assertEqual(os.listdir(folder), [])  # 교체에 실패하면 임시 파일을 지운다. 빈 폴더만 남는다
        retry = self.reg(SAMPLE_101)
        self.assertEqual((retry["outcome"], retry["record"]["status"]), ("registered", "registered"))
        self.assertEqual(sorted(os.listdir(folder)), ["1.json"])
        # 쓰다 만 .tmp, 빈 폴더도 이어서 완료
        for i, content in enumerate((b'{"sha256": "trunc', None)):
            store = os.path.join(self.tmp, "s%d" % i)
            os.makedirs(os.path.join(store, rel))
            if content is not None:
                with open(os.path.join(store, rel, "1.json.tmp"), "wb") as fh:
                    fh.write(content)
            self.assertEqual(self.reg(SAMPLE_101, store_root=store)["outcome"], "registered")
        # 다른 해시의 .tmp가 남은 경우는 충돌로 보류
        store = os.path.join(self.tmp, "s-other")
        os.makedirs(os.path.join(store, rel))
        with open(os.path.join(store, rel, "1.json.tmp"), "w", encoding="utf-8") as fh:
            json.dump({"sha256": "f" * 64}, fh)
        r = self.reg(SAMPLE_101, store_root=store)
        self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "id_collision")

    def test_p2_registration_blockers_block_extraction(self):
        record = self.reg(SAMPLE_101)["record"]
        bad = json.loads(json.dumps(record))
        bad["validation"]["blockers"] = [{"check": "x", "field": None, "reason": "남은 차단"}]
        ex = drawio.extract(SAMPLE_101, registration=bad)
        self.assertIn("registration_not_completed", [b["check"] for b in ex["validation"]["blockers"]])

    def test_p2_out_root_and_svg_on_other_drive(self):
        r = self.reg(SAMPLE_101)

        def other_drive(path, start=os.curdir):
            raise ValueError("path is on mount D:, start on mount C:")
        out_ex = os.path.join(self.tmp, "ex")
        with mock.patch("os.path.relpath", other_drive):
            self.assertEqual(extract_drawio.main(["--registration", r["registration_file"], "--out-root", out_ex]), 0)
        name = "proj-1__%s-r1-p0" % r["record"]["material_id"]
        with open(os.path.join(out_ex, name, "extraction.json"), encoding="utf-8") as fh:
            ex = json.load(fh)
        self.assertTrue(os.path.isabs(ex["coordinate_system"]["svg_alignment"]["svg_file"]))

    def test_p2_unknown_xml_encoding_is_failure(self):
        r = self.reg(self.put(b'<?xml version="1.0" encoding="x-bogus"?><mxfile/>', "enc.drawio"))
        self.assertEqual((r["outcome"], r["record"]["status"]), ("failed", "failed"))
        self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "unreadable")

    def test_p2_fallback_page_id_collision_blocks(self):
        model = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'
        text = '<mxfile><diagram name="a" id="page-2">%s</diagram><diagram name="b">%s</diagram></mxfile>' % (
            model, model)
        r = self.reg(self.put(text, "dup_page.drawio"))
        self.assertEqual(r["record"]["status"], "failed")
        self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "duplicate_page_id")


class ReviewFix3Test(RegisterBase):
    """3회차 지적 재현 테스트."""

    def test_long_project_id_keeps_identifiers_and_uniqueness(self):
        names = set()
        for pid in ("a" * 120, "a" * 119 + "b"):
            r = registry.register(SAMPLE_101, pid, store_root=self.store, actor="t", now=NOW)
            self.assertEqual(r["outcome"], "registered")
            for page in (0, 1):
                for ver in (1, 2):
                    rec = dict(r["record"], registration_version=ver)
                    name = extract_drawio.registered_out_name(rec, page)
                    self.assertLessEqual(len(name), 120)
                    self.assertEqual(name, paths.safe_name(name))  # safe_name이 더 자르지 않음
                    self.assertTrue(name.endswith("__%s-r%d-p%d" % (rec["material_id"], ver, page)))
                    names.add(name)
        self.assertEqual(len(names), 8)  # 프로젝트 2 x 버전 2 x 페이지 2 모두 다름
        short = extract_drawio.registered_out_name(dict(r["record"], project_id="proj-1"), 0)
        self.assertEqual(short, "proj-1__%s-r1-p0" % r["record"]["material_id"])  # 짧으면 그대로
        out_ex = os.path.join(self.tmp, "ex")
        self.assertEqual(extract_drawio.main(["--registration", r["registration_file"], "--svg", "none",
                                              "--out-root", out_ex]), 0)
        self.assertEqual(os.listdir(out_ex), [extract_drawio.registered_out_name(r["record"], 0)])

    def test_project_id_case_conflict(self):
        self.assertEqual(registry.register(SAMPLE_101, "alpha", store_root=self.store, actor="t")["outcome"],
                         "registered")
        r = registry.register(SAMPLE_101, "Alpha", store_root=self.store, actor="t")
        self.assertEqual((r["outcome"], r["record"]["status"]), ("on_hold", "on_hold"))
        self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "project_id_case_conflict")
        self.assertEqual(os.listdir(self.store), ["alpha"])  # 새 폴더를 만들거나 섞지 않음
        with open(os.path.join(self.store, "alpha", "registry.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["project_id"], "alpha")



@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(전용 venv에서 실행)")
class DesignDocumentRegisterTest(RegisterBase):
    """설계 문서(PDF) 등록: 글자를 읽을 수 있는 PDF만, 벡터 도면 분석·표제란 후보 없음."""

    def test_design_document_registers(self):
        r = self.reg(DESIGN_DOC, material_type="design_document")
        rec = r["record"]
        self.assertEqual((r["outcome"], rec["status"], rec["material_type"], rec["format"]),
                         ("registered", "registered", "design_document", "pdf"))
        self.assertEqual(rec["documents"][0]["page_ids"][:2], ["page-1", "page-2"])
        self.assertEqual(rec["auto_candidates"], {})
        self.assertFalse(rec.get("derived_files"))
        _, original = registry.load_for_extraction(r["registration_file"])
        self.assertEqual(read_bytes(original), read_bytes(DESIGN_DOC))

    def test_text_less_pdf_fails(self):
        r = self.reg(self.put(minimal_pdf(b"0 0 m 100 100 l S"), "scan.pdf"), material_type="design_document")
        self.assert_failed_not_stored(r, "no_text_content")

    def test_drawio_is_not_a_design_document(self):
        self.assert_failed_not_stored(self.reg(SAMPLE_101, material_type="design_document"), "unsupported_extension")

    def test_same_file_as_other_type_is_held(self):
        self.assertEqual(self.reg(DESIGN_DOC, material_type="design_document")["outcome"], "registered")
        r = self.reg(DESIGN_DOC)
        self.assertEqual(r["outcome"], "on_hold")
        self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "material_type_conflict")

    def test_unknown_material_type_on_hold(self):
        r = self.reg(DESIGN_DOC, material_type="photo")
        self.assertEqual(r["outcome"], "on_hold")
        self.assertEqual(r["record"]["validation"]["blockers"][0]["check"], "unsupported_material_type")

    def test_extract_document_writes_knowledge_and_kg(self):
        from hazop.app import data
        work = os.path.join(self.tmp, "work")
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": work, "HAZOP_STORE_ROOT": self.store}):
            r = self.reg(DESIGN_DOC, material_type="design_document")
            out = data.extract_document(r["registration_file"])
            name = extract_drawio.registered_out_name(r["record"], 0)
            self.assertEqual(out["path"], paths.output_in(work, "document-knowledge", name, "document_knowledge.json"))
            with open(out["path"], encoding="utf-8") as fh:
                doc = json.load(fh)
            self.assertEqual((doc["project_id"], doc["material_id"]), ("proj-1", r["record"]["material_id"]))
            self.assertGreater(doc["summary"]["setpoint"], 0)
            self.assertEqual(out["kg"]["kg"]["kg_id"], "kg-proj-1")             # 도면 없이 문서만으로도 빌드
            self.assertNotIn("kg_error", out)
            rows = data.list_registrations()
            self.assertEqual([(e["extracted"], e["graphed"]) for e in rows], [(True, None)])
        self.assertFalse(os.path.exists(paths.output_in(paths.DEV_WORK_ROOT, "document-knowledge", name)))


if __name__ == "__main__":
    unittest.main()
