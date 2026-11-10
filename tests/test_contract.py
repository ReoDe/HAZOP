"""단계 연쇄 검사(hazop/contract, scripts/check_contract.py) 독립 검증 V1–V21 (기획서/단계연쇄검사.md §6).

저장소의 출력/·자료저장소/는 읽기만 한다. 정상 연쇄를 임시 작업 루트·저장 루트에 만든 뒤(샘플 연쇄 S, 등록 연쇄 R),
사례마다 그 복사본에서 한 곳만 바꿔 검사한다. 네트워크·AI 호출 없음(고정 응답).
샘플 연쇄 S는 저장소 출력/(git 제외)의 최신 분석 실행을 복사해 쓰고, 출력/이 없으면 저장소 안 샘플 도면·구간 JSON·
고정 응답으로 같은 형태의 연쇄를 임시 폴더에 새로 만든다(이 경우 V1의 저장소 실제 실행 판정만 건너뜀).
샘플 도면(참고자료/P&ID 도면 샘플/*SNP-M-102*/*.drawio)이 없으면 준비 오류(RuntimeError)로 보고한다.
"""

import contextlib
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop import paths  # noqa: E402
from hazop import contract, review as rv  # noqa: E402
from hazop.analysis import api  # noqa: E402
from hazop.contract import chain  # noqa: E402
from hazop.export.worksheet import export_worksheet  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.register import registry  # noqa: E402

REGION_ID = "region-SNP-M-102-pzr"
CID = "deviation-p86-d09"
WHO = "검토자A"
EXPORT_AT = "2026-11-06T00:00:00Z"
FIXED_DIR = paths.folder("samples", "fixed-responses", REGION_ID)
REG_RUN_ID = "analysis-20261106T000000Z-regtst"
SYNTH_RUN_ID = "analysis-20261106T000000Z-synth0"


def sample_drawio():
    """SNP-M-102 샘플 도면 경로. 없으면 준비 오류."""
    found = [p for p in glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio"))
             if "SNP-M-102" in p]
    if not found:
        raise RuntimeError("준비 오류: 샘플 도면 없음 (참고자료/P&ID 도면 샘플/*/*SNP-M-102*.drawio)")
    return found[0]


def latest_repo_run():
    d = paths.output_in(paths.DEV_WORK_ROOT, "analysis", REGION_ID)
    if not os.path.isdir(d):
        return None
    runs = sorted((x for x in os.listdir(d) if os.path.isfile(os.path.join(d, x, "analysis.json"))),
                  key=chain._run_sort_key)
    return os.path.join(d, runs[-1]) if runs else None


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, doc):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def env(work, store):
    return mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": work, "HAZOP_STORE_ROOT": store})


def results(res, idx=-1):
    return res["chains"][idx]["results"]


def levels(res, cid, idx=-1):
    return [r["level"] for r in results(res, idx) if r["id"] == cid]


def fails(res, idx=-1):
    return [contract.format_line(r) for r in results(res, idx) if r["level"] == "FAIL"]


def make_junction(link, target):
    """디렉터리 정션(Windows) 또는 심볼릭 링크를 만든다. 둘 다 못 만들면 False."""
    if os.name == "nt":
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT)
        if proc.returncode == 0:
            return True
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


# ---------------------------------------------------------------- 정상 연쇄 만들기
def _synth_sample_outputs(work):
    """출력/이 없을 때: 샘플 도면을 등록 없이(project_id null, 샘플 경로) hazop.extract.drawio.extract로 추출하고
    그래프를 만든다. scripts/extract_drawio --samples와 달리 SVG 좌표 대응(svg_alignment)은 하지 않는다(연쇄 검사와 무관).
    구간 JSON을 그 그래프에 맞춘 뒤 고정 응답으로 분석 1회. 실행 폴더 경로를 돌려준다."""
    with env(work, paths.folder_in(work, "store")):
        ext = drawio.extract(sample_drawio(), page=0, repo_root=work)
        ex_dir = paths.output_in(work, "extract", "SNP-M-102")
        g_dir = paths.output_in(work, "graph", "SNP-M-102")
        os.makedirs(ex_dir)
        os.makedirs(g_dir)
        write_json(os.path.join(ex_dir, "extraction.json"), ext)
        graph = build.build_graph(ext, extraction_file=paths.output_rel("extract", "SNP-M-102", "extraction.json"))
        write_json(os.path.join(g_dir, "graph.json"), graph)
        write_json(os.path.join(g_dir, "entity_mapping.json"), build.entity_mapping_document(graph, ext))
        region_path = paths.folder_in(work, "regions", REGION_ID + ".json")
        region = read_json(region_path)
        region["graph_ref"].update(graph_id=graph["graph_id"], graph_version=graph["graph_version"],
                                   graph_file=paths.output_rel("graph", "SNP-M-102", "graph.json"))
        write_json(region_path, region)
        out = api.run_analysis(region_path, response_dir=FIXED_DIR, out_root=paths.output_in(work, "analysis"),
                               run_id=SYNTH_RUN_ID)
    if out["status"] != "passed":
        raise RuntimeError("준비 오류: 합성 샘플 분석 실패 %r" % out.get("blockers"))
    return out["run_dir"]


def build_sample_chain(base, src_run):
    """샘플 연쇄 S: 저장소 샘플 결과 복사(없으면 합성) + deviation-p86-d09 검토본 v1·v2(reviewing) + 출력 기록 1개.
    반환 (work, store, 실행 폴더 이름)."""
    work, store = os.path.join(base, "work"), os.path.join(base, "store")
    os.makedirs(paths.folder_in(work, "regions"))
    shutil.copy2(paths.folder("samples", "regions", REGION_ID + ".json"), paths.folder_in(work, "regions"))
    if src_run is not None:
        for rel in (("extract", "SNP-M-102"), ("graph", "SNP-M-102")):
            shutil.copytree(paths.output_in(paths.DEV_WORK_ROOT, *rel), paths.output_in(work, *rel))
        run_dir = paths.output_in(work, "analysis", REGION_ID, os.path.basename(src_run))
        shutil.copytree(src_run, run_dir)
        # 현재 구간 JSON = 실행 당시 사본(저장소 구간 JSON이 실행 뒤 바뀌었어도 버전을 섞지 않음)
        shutil.copyfile(os.path.join(run_dir, "inputs", "region.json"),
                        paths.folder_in(work, "regions", REGION_ID + ".json"))
        # 저장소 출력/의 현재 그래프가 이전 빌더 버전으로 만들어졌으면(BUILDER_VERSION 변경 뒤 재생성 전) 복사본의
        # 현재 그래프만 현재 빌더로 다시 만든다(실행 사본은 그대로 — 현재 그래프와 다르면 A7 WARN은 허용).
        ext = read_json(paths.output_in(work, "extract", "SNP-M-102", "extraction.json"))
        g_dir = paths.output_in(work, "graph", "SNP-M-102")
        if build._graph_version(ext) != read_json(os.path.join(g_dir, "graph.json"))["graph_version"]:
            graph = build.build_graph(ext, extraction_file=paths.output_rel("extract", "SNP-M-102", "extraction.json"))
            write_json(os.path.join(g_dir, "graph.json"), graph)
            write_json(os.path.join(g_dir, "entity_mapping.json"), build.entity_mapping_document(graph, ext))
    else:
        run_dir = _synth_sample_outputs(work)
    with env(work, store):
        run = rv.open_run(run_dir)
        sids = [s["scenario_id"] for s in run["doc"]["scenarios"] if s["candidate_id"] == CID]
        d1 = [rv.scenario_decision(run, sids[0], "defer", "자료 대기", WHO, now="2026-11-06T00:00:01Z")]
        rv.save_review(store, run, rv.build_review(run, CID, WHO, "1차 검토", d1), now="2026-11-06T00:00:02Z")
        d2 = d1 + [rv.scenario_decision(run, sids[1], "reject", "도면 범위 밖", WHO, now="2026-11-06T00:00:03Z")]
        _, rec = rv.save_review(store, run, rv.build_review(run, CID, WHO, "2차 검토", d2), now="2026-11-06T00:00:04Z")
        assert rec["review_status"] == "reviewing", rec["review_status"]
        out = export_worksheet(run_dir, store, paths.output_in(work, "worksheets"), now=EXPORT_AT)
    assert out["record"]["target"]["reviews"] == [{"candidate_id": CID, "review_version": 2,
                                                   "review_status": "reviewing"}]
    return work, store, os.path.basename(run_dir)


def build_registration_chain(base, out_sub=()):
    """등록 연쇄 R: 임시 저장 루트에 SNP-M-102 등록(p-test) → 등록정보로 추출·그래프 → 구간 맞춤 → 고정 응답 분석 1회.
    out_sub: 추출·그래프를 둘 작업 루트 아래 폴더(기본 출력/, run_samples 배치는 출력/samples/)."""
    import build_graph
    import extract_drawio
    work, store = os.path.join(base, "work"), os.path.join(base, "store")
    os.makedirs(paths.folder_in(work, "regions"))
    with env(work, store), contextlib.redirect_stdout(io.StringIO()):
        res = registry.register(sample_drawio(), "p-test", store_root=store, actor="tester",
                                now=lambda: "2026-11-06T00:00:00+00:00")
        assert res["outcome"] == "registered", res
        record, original = registry.load_for_extraction(res["registration_file"])
        svgs = registry.registered_svgs(res["registration_file"], record)
        result, ex_dir = extract_drawio.run_one(original, os.path.join(paths.output_in(work, *out_sub), paths.output_name("extract")), registration=record,
                                                registered_svgs=svgs)
        graph, g_dir = build_graph.build_one(os.path.join(ex_dir, "extraction.json"), os.path.join(paths.output_in(work, *out_sub), paths.output_name("graph")))
        region = read_json(paths.folder("samples", "regions", REGION_ID + ".json"))
        region["project_id"] = "p-test"
        region["graph_ref"].update(graph_id=graph["graph_id"], graph_version=graph["graph_version"],
                                   graph_source="registration",
                                   graph_file=os.path.relpath(os.path.join(g_dir, "graph.json"), work).replace("\\", "/"))
        region_path = paths.folder_in(work, "regions", REGION_ID + ".json")
        write_json(region_path, region)
        out = api.run_analysis(region_path, response_dir=FIXED_DIR, out_root=paths.output_in(work, "analysis"),
                               run_id=REG_RUN_ID)
    assert out["status"] == "passed", out
    return work, store


# ---------------------------------------------------------------- 테스트
class _Base(unittest.TestCase):
    base = None

    @classmethod
    def tearDownClass(cls):
        if cls.base:
            shutil.rmtree(cls.base, ignore_errors=True)

    def variant(self):
        """정상 연쇄의 복사본(work, store). 테스트가 끝나면 지운다."""
        d = tempfile.mkdtemp(prefix="hazop-contract-case-")
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copytree(os.path.join(self.base, "work"), os.path.join(d, "work"), symlinks=True)
        shutil.copytree(os.path.join(self.base, "store"), os.path.join(d, "store"))
        return os.path.join(d, "work"), os.path.join(d, "store")

    def check(self, work, store, **kw):
        res = contract.check(work, store, **kw)
        self.assertEqual(res["errors"], [])
        return res


class SampleChainTest(_Base):
    @classmethod
    def setUpClass(cls):
        cls.src_run = latest_repo_run()  # 없으면 합성(출력/ 부재)
        cls.base = tempfile.mkdtemp(prefix="hazop-contract-S-")
        try:
            cls.work, cls.store, cls.run_name = build_sample_chain(cls.base, cls.src_run)
        except Exception:
            shutil.rmtree(cls.base, ignore_errors=True)
            raise

    def run_dir_of(self, work):
        return paths.output_in(work, "analysis", REGION_ID, self.run_name)

    def review_dir_of(self, store):
        return os.path.join(store, "reviews", REGION_ID, self.run_name)

    def edit_json(self, path, fn):
        doc = read_json(path)
        fn(doc)
        write_json(path, doc)

    def edit_analysis(self, work, fn):
        self.edit_json(os.path.join(self.run_dir_of(work), "analysis.json"), fn)

    def export_record_path(self, store):
        d = os.path.join(self.review_dir_of(store), "exports")
        return os.path.join(d, os.listdir(d)[0])

    def test_v1_sample_chain(self):
        res = self.check(self.work, self.store)
        self.assertEqual(len(res["chains"]), 1)
        self.assertEqual(fails(res), [])
        self.assertEqual(res["chains"][0]["path"], "samples")
        for cid in ("R1", "R2", "R3", "R4"):
            rs = [r for r in results(res) if r["id"] == cid]
            self.assertEqual([(r["level"], r["message"]) for r in rs], [("SKIP", chain.SAMPLE_SKIP)])
        k1 = [r for r in results(res) if r["id"] == "K1" and r["level"] == "PASS"]
        self.assertTrue(any("not_registered 3건" in r["message"] for r in k1))
        for cid in ("C1", "C2", "C3", "C4", "C5", "E1", "E2", "E3", "E4", "E5"):
            self.assertEqual(levels(res, cid), ["PASS"], cid)
        self.assertEqual(contract.exit_code(res), 0)

    def test_v1_repository_latest_run_read_only(self):
        """저장소 실제 출력/의 최신 실행(읽기 전용). 검토본·출력 기록은 저장소 자료저장소/에 있으면 함께 본다."""
        if self.src_run is None:
            self.skipTest("저장소 출력/분석 없음(git 제외 폴더) — 실제 실행 판정만 생략, 나머지는 합성 연쇄로 검사")
        res = self.check(paths.DEV_WORK_ROOT, paths.folder_in(paths.DEV_WORK_ROOT, "store"), region=REGION_ID)
        self.assertEqual(res["chains"][0]["analysis_run_id"], os.path.basename(self.src_run))
        bad = fails(res)
        stale = [x for x in bad if " X2 " in x and "빌더 버전이 그래프 생성 뒤 바뀜" in x]
        self.assertEqual(bad, [], "저장소 출력/의 그래프가 현재 빌더 버전보다 낡음 — 그래프 재생성 필요(검사 오류 아님): %s"
                         % stale if stale else "저장소 실제 실행의 연쇄 FAIL")
        self.assertEqual(levels(res, "R1"), ["SKIP"])

    def test_v6_extraction_node_deleted(self):
        work, store = self.variant()
        self.edit_json(paths.output_in(work, "extract", "SNP-M-102", "extraction.json"), lambda d: d["nodes"].pop())
        res = self.check(work, store)
        self.assertIn("FAIL", levels(res, "X2"))
        self.assertIn("FAIL", levels(res, "X3"))

    def test_v7_entity_mapping_entry_deleted(self):
        work, store = self.variant()
        self.edit_json(paths.output_in(work, "graph", "SNP-M-102", "entity_mapping.json"),
                       lambda d: d["entity_mapping"].pop(0))
        res = self.check(work, store)
        self.assertIn("FAIL", levels(res, "X4"))
        self.assertEqual(levels(res, "X3"), ["PASS"])

    def test_v8_input_copy_whitespace(self):
        work, store = self.variant()
        with open(os.path.join(self.run_dir_of(work), "inputs", "graph.json"), "ab") as fh:
            fh.write(b" ")
        res = self.check(work, store)
        self.assertIn("FAIL", levels(res, "A2"))

    def test_v9_scenario_node_not_in_graph(self):
        work, store = self.variant()
        self.edit_analysis(work, lambda d: d["scenarios"][0]["graph_evidence"]["node_ids"].append("entity-node-999"))
        res = self.check(work, store)
        for cid in ("A5", "C2", "E1"):
            self.assertIn("FAIL", levels(res, cid), cid)
        self.assertTrue(any("entity-node-999" in x for x in fails(res)))

    def test_v10_extraction_and_graph_replaced_together(self):
        work, store = self.variant()
        with open(sample_drawio(), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('pageWidth="1654"', text)
        src = os.path.join(os.path.dirname(work), "SNP-M-102-changed.drawio")
        with open(src, "w", encoding="utf-8", newline="") as fh:
            fh.write(text.replace('pageWidth="1654"', 'pageWidth="1655"', 1))
        with env(work, store):
            ext = drawio.extract(src, page=0, repo_root=work)
        write_json(paths.output_in(work, "extract", "SNP-M-102", "extraction.json"), ext)
        graph = build.build_graph(ext, extraction_file=paths.output_rel("extract", "SNP-M-102", "extraction.json"))
        write_json(paths.output_in(work, "graph", "SNP-M-102", "graph.json"), graph)
        write_json(paths.output_in(work, "graph", "SNP-M-102", "entity_mapping.json"),
                   build.entity_mapping_document(graph, ext))
        res = self.check(work, store)
        for cid in ("X1", "X2", "X3", "X4", "A2", "A3", "A4", "A5", "A6"):
            self.assertEqual(levels(res, cid), ["PASS"], cid)
        self.assertEqual(levels(res, "A7"), ["WARN"])

    def test_v11_review_version_gap(self):
        work, store = self.variant()
        d = os.path.join(self.review_dir_of(store), CID)
        v2 = read_json(os.path.join(d, "v2.json"))
        v2.update(review_version=3, previous_review_version=2)
        write_json(os.path.join(d, "v3.json"), v2)
        os.remove(os.path.join(d, "v2.json"))
        res = self.check(work, store)
        self.assertIn("FAIL", levels(res, "C3"))
        self.assertIn("FAIL", levels(res, "E2"))
        self.assertTrue(any("v2 없음 (v1, v3만 있음)" in x for x in fails(res)))

    def test_v12_review_status_tampered(self):
        work, store = self.variant()
        self.edit_json(os.path.join(self.review_dir_of(store), CID, "v2.json"),
                       lambda d: d.update(review_status="confirmed"))
        res = self.check(work, store)
        self.assertIn("FAIL", levels(res, "C5"))
        self.assertIn("FAIL", levels(res, "E2"))

    def test_v13_worksheet_changed_or_deleted(self):
        work, store = self.variant()
        xlsx = paths.resolve_rel(read_json(self.export_record_path(store))["file"], work)
        with open(xlsx, "r+b") as fh:
            fh.seek(-1, os.SEEK_END)
            last = fh.read(1)
            fh.seek(-1, os.SEEK_END)
            fh.write(bytes([last[0] ^ 1]))
        self.assertEqual(levels(self.check(work, store), "E3"), ["FAIL"])
        os.remove(xlsx)
        res = self.check(work, store)
        self.assertEqual(levels(res, "E3"), ["WARN"])
        self.assertEqual(contract.exit_code(res), 0)

    def test_v14_graph_not_registered_unknown_deleted(self):
        work, store = self.variant()

        def drop(doc):
            doc["validation"]["unknowns"] = [u for u in doc["validation"]["unknowns"]
                                             if not (u["check"] == "not_registered" and u["field"] == "material_id")]
        self.edit_json(paths.output_in(work, "graph", "SNP-M-102", "graph.json"), drop)
        res = self.check(work, store)
        self.assertIn("FAIL", levels(res, "K1"))
        self.assertEqual(levels(res, "X2"), ["PASS"])

    def test_v15_extraction_flow_direction_removed(self):
        work, store = self.variant()

        def edit(doc):
            rel = next(r for r in doc["relations"] if r["kind"] == "physical_connection" and r["flow_direction"])
            rel["flow_direction"] = None
            doc["validation"]["unknowns"].append({"check": "unknown_flow_direction", "target": rel["local_id"],
                                                  "source_object_id": rel["source_object_id"],
                                                  "field": "flow_direction", "reason": "원본에 흐름 방향 지정 없음"})
        self.edit_json(paths.output_in(work, "extract", "SNP-M-102", "extraction.json"), edit)
        res = self.check(work, store)
        for cid in ("K2", "K1", "X2"):
            self.assertIn("FAIL", levels(res, cid), cid)

    def test_k2_check_valve_direction(self):
        """체크밸브 허용 방향(K2 확장): 추출 판정과 같으면 PASS, 그래프에서 입출구를 바꾸면 FAIL."""
        work, store = self.variant()
        gpath = paths.output_in(work, "graph", "SNP-M-102", "graph.json")
        epath = paths.output_in(work, "extract", "SNP-M-102", "extraction.json")
        graph = read_json(gpath)
        segs = [n for n in graph["nodes"] if n.get("node_type") == "pipe_segment"][:2]
        valve = next(n for n in graph["nodes"] if n.get("category") == "valve")
        cd = {"inlet": segs[0]["local_id"], "outlet": segs[1]["local_id"], "basis": ["attribute"], "status": "declared"}
        self.edit_json(epath, lambda d: next(x for x in d["nodes"] if x["local_id"] == valve["local_id"])
                       .update(check_direction=cd))

        def set_graph(inlet, outlet):
            def fn(d):
                node = next(x for x in d["nodes"] if x["entity_id"] == valve["entity_id"])
                node["check_direction"] = dict(cd, inlet=inlet, outlet=outlet)
            self.edit_json(gpath, fn)

        set_graph(segs[0]["entity_id"], segs[1]["entity_id"])
        self.assertEqual(levels(self.check(work, store), "K2"), ["PASS"])
        set_graph(segs[1]["entity_id"], segs[0]["entity_id"])
        res = self.check(work, store)
        self.assertEqual(levels(res, "K2"), ["FAIL"])
        self.assertTrue(any("K2 %s: 체크밸브 입구·출구가 추출 판정과 다름" % valve["entity_id"] in x for x in fails(res)))

    def test_v16_graph_hold_deleted(self):
        work, store = self.variant()

        def drop(doc):
            h = next(h for h in doc["holds"] if h["source"] == "graph" and h["candidate_id"] is None)
            doc["holds"].remove(h)
        self.edit_analysis(work, drop)
        res = self.check(work, store)
        for cid in ("K3", "C2", "E1"):
            self.assertIn("FAIL", levels(res, cid), cid)

    def test_v17_scenario_confirmed(self):
        work, store = self.variant()
        self.edit_analysis(work, lambda d: d["scenarios"][0].update(knowledge_status="confirmed"))
        res = self.check(work, store)
        for cid in ("K5", "C2", "E1"):
            self.assertIn("FAIL", levels(res, cid), cid)

    def test_v18_no_reviews_no_exports(self):
        work, store = self.variant()
        shutil.rmtree(os.path.join(store, "reviews"))
        res = self.check(work, store)
        for cid in ("C1", "C2", "C3", "C4", "C5", "E1", "E2", "E3", "E4", "E5"):
            rs = [r for r in results(res) if r["id"] == cid]
            self.assertEqual([r["level"] for r in rs], ["SKIP"], cid)
            self.assertTrue(rs[0]["message"], cid)
        self.assertEqual(contract.exit_code(res), 0)
        import check_contract
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = check_contract.main(["--work-root", work, "--store-root", store])
        self.assertEqual(code, 0)
        self.assertIn("요약: PASS", out.getvalue())

    def test_v19_run_all_with_old_run_missing_fields(self):
        work, store = self.variant()
        old = "analysis-20261101T000000Z-old000"
        old_dir = paths.output_in(work, "analysis", REGION_ID, old)
        shutil.copytree(self.run_dir_of(work), old_dir)

        def make_old(doc):
            doc["analysis_run_id"] = old
            doc.pop("design_improvement_candidates")
            for s in doc["scenarios"]:
                s.pop("cause_equipment")
            rp = next(s["risk_proposal"] for s in doc["scenarios"] if s["risk_proposal"]["status"] != "proposed")
            rp["risk"] = 3  # 보류된 위험도에 등급 값(K6 위반)
        self.edit_json(os.path.join(old_dir, "analysis.json"), make_old)
        res = self.check(work, store, run="all")
        self.assertEqual([c["analysis_run_id"] for c in res["chains"]], [old, self.run_name])
        a5 = [r for r in results(res, 0) if r["id"] == "A5"]
        self.assertEqual([r["level"] for r in a5], ["FAIL"])
        self.assertIn("cause_equipment", a5[0]["message"])
        self.assertIn("(오래된 형식 또는 검사 오류)", a5[0]["message"])
        k6 = [r for r in results(res, 0) if r["id"] == "K6"]  # 뒤 항목도 계속 검사되고 내용까지 맞음
        self.assertEqual([r["level"] for r in k6], ["FAIL"])
        self.assertIn("위험도에 등급 3", k6[0]["message"])
        self.assertEqual(fails(res, 1), [])
        self.assertEqual(contract.exit_code(res), 1)
        latest = self.check(work, store)
        self.assertEqual([c["analysis_run_id"] for c in latest["chains"]], [self.run_name])

    def test_v20_same_input_same_report(self):
        out = tempfile.mkdtemp(prefix="hazop-contract-report-")
        self.addCleanup(shutil.rmtree, out, True)
        p1, p2 = os.path.join(out, "a.json"), os.path.join(out, "b.json")
        contract.write_report(self.check(self.work, self.store), p1, checked_at="2026-11-06T00:00:00Z")
        contract.write_report(self.check(self.work, self.store), p2)
        a, b = read_json(p1), read_json(p2)
        a.pop("checked_at")
        b.pop("checked_at")
        self.assertEqual(a, b)
        self.assertEqual(a["summary"]["FAIL"], 0)
        with open(p1, encoding="utf-8") as fh:
            self.assertTrue(fh.read().endswith("}\n"))

    def test_v21_worksheet_row_scenario_of_other_candidate(self):
        work, store = self.variant()

        def edit(doc):
            row = next(r for r in doc["rows"]["worksheet"] if r["candidate_id"] == CID and r["scenario_id"])
            row["scenario_id"] = "scenario-p86-d10-01"
        self.edit_json(self.export_record_path(store), edit)
        res = self.check(work, store)
        self.assertIn("FAIL", levels(res, "E4"))
        self.assertTrue(any("scenario-p86-d10-01은 %s 소속이 아님" % CID in x for x in fails(res)))

    # ---- 재작업 1회차 추가 사례
    def test_x3_unknown_relation_kind_exempt_only_with_one_record(self):
        work, store = self.variant()
        ex_path = paths.output_in(work, "extract", "SNP-M-102", "extraction.json")
        g_dir = paths.output_in(work, "graph", "SNP-M-102")
        ext = read_json(ex_path)
        rel = next(r for r in ext["relations"] if r["kind"] != "physical_connection")
        rel["kind"] = "unknown_kind_x"  # 빌더는 매핑하지 않고 unknown_relation_kind 1건을 남김
        write_json(ex_path, ext)
        graph = build.build_graph(ext, extraction_file=paths.output_rel("extract", "SNP-M-102", "extraction.json"))
        write_json(os.path.join(g_dir, "graph.json"), graph)
        write_json(os.path.join(g_dir, "entity_mapping.json"), build.entity_mapping_document(graph, ext))
        res = self.check(work, store)
        x3 = [r for r in results(res) if r["id"] == "X3"]
        self.assertEqual([r["level"] for r in x3], ["PASS"])
        self.assertIn("매핑 제외 1개", x3[0]["message"])
        graph["validation"]["unknowns"] = [u for u in graph["validation"]["unknowns"]
                                           if u["check"] != "unknown_relation_kind"]
        write_json(os.path.join(g_dir, "graph.json"), graph)
        res = self.check(work, store)
        self.assertEqual(levels(res, "X3"), ["FAIL"])
        self.assertTrue(any("매핑 없는 local_id %s" % rel["local_id"] in x for x in fails(res)))

    def test_x2_builder_version_change_named_in_message(self):
        work, store = self.variant()
        ext = read_json(paths.output_in(work, "extract", "SNP-M-102", "extraction.json"))
        canon = json.dumps(ext, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        old = "v-" + __import__("hashlib").sha256(("0.0.9|" + canon).encode("utf-8")).hexdigest()[:12]
        self.edit_json(paths.output_in(work, "graph", "SNP-M-102", "graph.json"),
                       lambda d: (d["builder"].update(version="0.0.9"), d.update(graph_version=old)))
        res = self.check(work, store)
        x2 = [r for r in results(res) if r["id"] == "X2"]
        self.assertEqual([r["level"] for r in x2], ["FAIL"])  # 기획대로 FAIL, 원인만 구분 표시
        self.assertIn("빌더 버전이 그래프 생성 뒤 바뀜(기록 0.0.9", x2[0]["message"])
        self.assertIn("추출 변경 없음", x2[0]["message"])

    def test_x3_known_relation_kind_not_exempt(self):
        work, store = self.variant()
        g_path = paths.output_in(work, "graph", "SNP-M-102", "graph.json")
        ext = read_json(paths.output_in(work, "extract", "SNP-M-102", "extraction.json"))
        rel = next(r for r in ext["relations"] if r["kind"] == "signal_connection")

        def edit(g):
            g["entity_mapping"] = [m for m in g["entity_mapping"] if m["local_id"] != rel["local_id"]]
            g["validation"]["unknowns"].append({"check": "unknown_relation_kind", "target": rel["local_id"],
                                                "field": "kind", "reason": "시험"})
        self.edit_json(g_path, edit)
        res = self.check(work, store)
        self.assertEqual(levels(res, "X3"), ["FAIL"])
        self.assertTrue(any("면제 대상 아님" in x and rel["local_id"] in x for x in fails(res)))

    def test_report_contains_notes(self):
        work, store = self.variant()
        unfinished = "analysis-20991231T000000Z-unfin2"
        os.makedirs(paths.output_in(work, "analysis", REGION_ID, unfinished))
        out = tempfile.mkdtemp(prefix="hazop-contract-report-")
        self.addCleanup(shutil.rmtree, out, True)
        p = contract.write_report(self.check(work, store), os.path.join(out, "r.json"))
        self.assertTrue(any(unfinished in n for n in read_json(p)["notes"]))

    def test_listdir_error_is_execution_error(self):
        work, store = self.variant()
        real = os.listdir
        target = paths.output_in(work, "analysis", REGION_ID)

        def denied(path="."):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(target):
                raise PermissionError(13, "접근 거부(시험)", path)
            return real(path)
        with mock.patch.object(chain.os, "listdir", denied):
            res = contract.check(work, store)
        self.assertTrue(any("파일 접근 실패" in e for e in res["errors"]))
        self.assertEqual(contract.exit_code(res), 2)
        import check_contract
        with mock.patch.object(contract, "check", side_effect=PermissionError(13, "접근 거부(시험)")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(check_contract.main(["--work-root", work, "--store-root", store]), 2)
        self.assertIn("[ERROR]", out.getvalue())

    @unittest.skipUnless(os.name == "nt", "Windows 경로 표기 시험")
    def test_report_windows_path_forms_refused(self):
        work, store = self.variant()
        res = self.check(work, store)
        target = paths.output_in(os.path.abspath(work))
        before = sorted(os.listdir(target))
        drive, rest = os.path.splitdrive(target)
        forms = ["\\\\?\\" + os.path.join(target, "r1.json"),
                 "\\\\localhost\\%s$" % drive.rstrip(":") + os.path.join(rest, "r2.json"),
                 target + ":e.json"]
        for p in forms:
            with self.assertRaises(contract.ContractError, msg=p):
                contract.write_report(res, p)
        self.assertEqual(sorted(os.listdir(target)), before)
        self.assertFalse(os.path.exists(target + ":e.json"))

    def test_latest_ignores_unfinished_run_folder(self):
        work, store = self.variant()
        unfinished = "analysis-20991231T000000Z-unfin0"
        os.makedirs(paths.output_in(work, "analysis", REGION_ID, unfinished, "inputs"))
        res = self.check(work, store)
        self.assertEqual([c["analysis_run_id"] for c in res["chains"]], [self.run_name])
        self.assertTrue(any(unfinished in n for n in res["notes"]))
        self.assertEqual(contract.exit_code(res), 0)

    def test_run_all_skips_unfinished_but_named_run_is_error(self):
        work, store = self.variant()
        unfinished = "analysis-20261101T000000Z-unfin1"
        os.makedirs(paths.output_in(work, "analysis", REGION_ID, unfinished, "inputs"))
        res = self.check(work, store, run="all")
        self.assertEqual([c["analysis_run_id"] for c in res["chains"]], [self.run_name])
        self.assertTrue(any(unfinished in n for n in res["notes"]))
        self.assertEqual(contract.exit_code(res), 0)
        res = contract.check(work, store, run=unfinished)
        self.assertTrue(any("analysis.json 없음" in e for e in res["errors"]))
        self.assertEqual(contract.exit_code(res), 2)

    def test_non_object_json_is_execution_error(self):
        work, store = self.variant()
        with open(os.path.join(self.run_dir_of(work), "analysis.json"), "w", encoding="utf-8") as fh:
            fh.write("[]")
        res = contract.check(work, store)
        self.assertTrue(any("JSON 객체가 아님" in e and "analysis.json" in e for e in res["errors"]))
        self.assertEqual(contract.exit_code(res), 2)
        work, store = self.variant()
        with open(paths.output_in(work, "graph", "SNP-M-102", "graph.json"), "w", encoding="utf-8") as fh:
            fh.write("[1]")
        res = contract.check(work, store)
        self.assertTrue(any("JSON 객체가 아님" in e and "graph.json" in e for e in res["errors"]))
        self.assertEqual(contract.exit_code(res), 2)

    def test_file_access_error_is_execution_error(self):
        work, store = self.variant()
        real = chain.file_sha256

        def denied(path):
            if path and path.endswith("graph.json") and "inputs" in path:
                raise PermissionError(13, "접근 거부(시험)", path)
            return real(path)
        with mock.patch.object(chain, "file_sha256", denied):
            res = contract.check(work, store)
        self.assertTrue(any("파일 접근 실패" in e for e in res["errors"]))
        self.assertEqual(contract.exit_code(res), 2)

    def test_c3_start_version_and_previous(self):
        work, store = self.variant()
        d = os.path.join(self.review_dir_of(store), CID)
        v1 = read_json(os.path.join(d, "v1.json"))
        write_json(os.path.join(d, "v0.json"), dict(v1, review_version=0, previous_review_version=-1))
        res = self.check(work, store)
        self.assertTrue(any("C3" in x and "시작 버전이 v1이 아님" in x for x in fails(res)))
        work, store = self.variant()
        d = os.path.join(self.review_dir_of(store), CID)
        self.edit_json(os.path.join(d, "v1.json"), lambda r: r.update(previous_review_version=-1))
        self.assertIn("FAIL", levels(self.check(work, store), "C3"))
        work, store = self.variant()  # v1의 previous 필드가 아예 없음 → 허용
        d = os.path.join(self.review_dir_of(store), CID)
        self.edit_json(os.path.join(d, "v1.json"), lambda r: r.pop("previous_review_version"))
        self.assertEqual(levels(self.check(work, store), "C3"), ["PASS"])

    def test_g2_sample_path_requires_null_project_id(self):
        work, store = self.variant()
        self.edit_json(paths.output_in(work, "extract", "SNP-M-102", "extraction.json"),
                       lambda d: d.update(project_id="p-x"))
        res = self.check(work, store)
        g2 = [r for r in results(res) if r["id"] == "G2"]
        self.assertEqual([r["level"] for r in g2], ["FAIL"])
        self.assertIn("샘플 경로 null", g2[0]["message"])

    def test_version_values_normalized_to_int(self):
        work, store = self.variant()
        region_path = paths.folder_in(work, "regions", REGION_ID + ".json")
        # 실행 당시 구간 버전(사본)과 같은 값을 문자열로 둔다(현재 구간이 재고정으로 올라가 있어도 A8 PASS 조건 유지)
        cur = read_json(os.path.join(self.run_dir_of(work), "inputs", "region.json"))["region_version"]
        self.edit_json(region_path, lambda d: d.update(region_version=str(cur)))
        self.edit_json(os.path.join(self.review_dir_of(store), CID, "v2.json"),
                       lambda d: d.update(review_version="2", previous_review_version="1"))
        res = self.check(work, store)
        self.assertEqual(levels(res, "A8"), ["PASS"])
        self.assertEqual(levels(res, "C3"), ["PASS"])
        for bad in ("v-abc", "\uff11"):  # 문자, 전각 숫자('１'.isdigit()는 True지만 ASCII 아님)
            self.edit_json(region_path, lambda d: d.update(region_version=bad))
            res = self.check(work, store)
            a8 = [r for r in results(res) if r["id"] == "A8"]
            self.assertEqual([r["level"] for r in a8], ["FAIL"], bad)
            self.assertIn("정수로 바꿀 수 없음", a8[0]["message"])

    def test_report_path_rules(self):
        res = self.check(self.work, self.store)
        for p in (os.path.join(paths.output_in(self.work), "r.json"), os.path.join(self.store, "r.json"),
                  paths.folder_in(self.work, "data", "x", "..", "r.json")):
            with self.assertRaises(contract.ContractError):
                contract.write_report(res, p)
            self.assertFalse(os.path.exists(os.path.normpath(p)))
        cwd = os.getcwd()  # 상대 경로도 실제 경로 기준으로 거부
        os.chdir(self.work)
        try:
            with self.assertRaises(contract.ContractError):
                contract.write_report(res, os.path.join(paths.folder_rel("output"), "rel.json"))
        finally:
            os.chdir(cwd)
        self.assertFalse(os.path.exists(os.path.join(paths.output_in(self.work), "rel.json")))
        out = tempfile.mkdtemp(prefix="hazop-contract-report-")
        self.addCleanup(shutil.rmtree, out, True)
        p = os.path.join(out, "r.json")
        contract.write_report(res, p)
        with open(p, "rb") as fh:
            before = fh.read()
        with self.assertRaises(contract.ContractError):  # 기존 파일 덮어쓰기 금지
            contract.write_report(res, p)
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), before)
        import check_contract
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_contract.main(["--work-root", self.work, "--store-root", self.store,
                                                  "--report", p]), 2)

    def test_report_path_through_junction_refused(self):
        out = tempfile.mkdtemp(prefix="hazop-contract-link-")
        self.addCleanup(shutil.rmtree, out, True)
        work, store = self.variant()
        res = self.check(work, store)
        into_input = os.path.join(out, "to-output")
        outside_target = os.path.join(out, "real")
        os.makedirs(outside_target)
        to_outside = os.path.join(out, "to-real")
        if not (make_junction(into_input, paths.output_in(work)) and make_junction(to_outside, outside_target)):
            self.skipTest("정션·심볼릭 링크를 만들 수 없음")
        for link in (into_input, to_outside):
            self.addCleanup(lambda x=link: os.path.isjunction(x) and os.rmdir(x) or os.path.islink(x) and os.unlink(x))
            with self.assertRaises(contract.ContractError):
                contract.write_report(res, os.path.join(link, "r.json"))
        self.assertFalse(os.path.exists(os.path.join(paths.output_in(work), "r.json")))
        self.assertFalse(os.path.exists(os.path.join(outside_target, "r.json")))

    def test_missing_input_folder_exit_2(self):
        d = tempfile.mkdtemp(prefix="hazop-contract-empty-")
        self.addCleanup(shutil.rmtree, d, True)
        with contextlib.redirect_stdout(io.StringIO()):
            import check_contract
            self.assertEqual(check_contract.main(["--work-root", d, "--store-root", d]), 2)


class SyntheticSampleChainTest(_Base):
    """출력/ 부재 대비 경로(합성 샘플 연쇄)가 그 자체로 정상 연쇄인지: FAIL 0, R SKIP, C·E PASS."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="hazop-contract-SY-")
        try:
            cls.work, cls.store, cls.run_name = build_sample_chain(cls.base, None)
        except Exception:
            shutil.rmtree(cls.base, ignore_errors=True)
            raise

    def test_synthetic_chain_is_normal(self):
        res = self.check(self.work, self.store)
        self.assertEqual(res["chains"][0]["analysis_run_id"], SYNTH_RUN_ID)
        self.assertEqual(fails(res), [])
        self.assertEqual(levels(res, "R1"), ["SKIP"])
        for cid in ("C1", "C3", "C5", "E1", "E2", "E3", "E4"):
            self.assertEqual(levels(res, cid), ["PASS"], cid)


class RegistrationChainTest(_Base):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="hazop-contract-R-")
        build_registration_chain(cls.base)

    def snapshot_dir(self, store):
        return glob.glob(os.path.join(store, "p-test", "registrations", "material-*"))[0]

    def test_v2_registration_chain(self):
        work, store = self.variant()
        res = self.check(work, store)
        self.assertEqual(res["chains"][0]["path"], "registration")
        self.assertEqual(res["chains"][0]["material_ref"]["registration_version"], 1)
        self.assertEqual(fails(res), [])
        for cid in ("R1", "R2", "R3"):
            self.assertEqual(levels(res, cid), ["PASS"], cid)

    def test_v3_stored_original_changed(self):
        work, store = self.variant()
        snap = read_json(os.path.join(self.snapshot_dir(store), "1.json"))
        p = os.path.join(store, "p-test", *snap["storage_ref"].split("/"))
        with open(p, "ab") as fh:
            fh.write(b" ")
        res = self.check(work, store)
        self.assertIn("FAIL", levels(res, "R3"))

    def test_v4_extraction_project_id_changed(self):
        work, store = self.variant()
        p = glob.glob(paths.output_in(work, "extract", "*", "extraction.json"))[0]
        doc = read_json(p)
        doc["project_id"] = "p-other"
        write_json(p, doc)
        res = self.check(work, store)
        for cid in ("G2", "R1", "X2"):
            self.assertIn("FAIL", levels(res, cid), cid)
        for cid in ("R2", "R3", "R4"):
            self.assertEqual(levels(res, cid), ["SKIP"], cid)

    def test_v5_new_registration_version_metadata_only(self):
        work, store = self.variant()
        with env(work, store):
            out = registry.register(sample_drawio(), "p-test", store_root=store, actor="tester",
                                    metadata={"design_revision": "B", "reason": "개정 확인"})
        self.assertEqual((out["outcome"], out["record"]["registration_version"]), ("new_version", 2))
        res = self.check(work, store)
        self.assertEqual(levels(res, "R4"), ["WARN"])
        self.assertEqual(levels(res, "R3"), ["PASS"])
        self.assertEqual(fails(res), [])

    def test_registration_version_string_normalized(self):
        work, store = self.variant()
        p = glob.glob(paths.output_in(work, "extract", "*", "extraction.json"))[0]
        doc = read_json(p)
        doc["source"]["registration_version"] = "1"
        write_json(p, doc)
        res = self.check(work, store)
        for cid in ("R1", "R2", "R3", "R4"):
            self.assertEqual(levels(res, cid), ["PASS"], cid)


class RunSamplesLayoutTest(_Base):
    """run_samples 배치(출력/samples/추출·그래프)의 등록 경로 실행: 현재 그래프를 extraction_file의 형제 그래프 폴더에서 찾는다."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="hazop-contract-RS-")
        build_registration_chain(cls.base, out_sub=("samples",))

    def test_graph_found_next_to_extraction(self):
        work, store = self.variant()
        self.assertFalse(os.path.exists(paths.output_in(work, "graph")))
        res = self.check(work, store)
        self.assertEqual(fails(res), [])
        for cid in ("X1", "X2", "X3", "X4", "X5", "A7", "K1", "K2"):
            self.assertEqual(levels(res, cid), ["PASS"], cid)


if __name__ == "__main__":
    unittest.main()
