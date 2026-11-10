"""데스크톱 화면 지원(기획서/인터페이스.md §2.5·§3.1·§3.3·§7.1) 테스트.
경로 분리·설정 파일, SVG 파생 등록, 후보 판단 변경, 근거 묶음 내보내기, 분석 실행 API.
실행: python -m unittest discover -s tests -t .  임시 폴더만 쓰고 데이터/·자료저장소/·출력/ 원본은 바꾸지 않는다. AI 호출·네트워크 없음.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import build_viewer  # noqa: E402
import export_bundles as export_cli  # noqa: E402
import extract_drawio  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.extract import svg_align  # noqa: E402
from hazop.analysis import ai, api, bundle_export, candidate_edit, candidates as cand_mod, run  # noqa: E402
from hazop.register import registry  # noqa: E402
from tests.test_analysis import FIXED_DIR, GRAPH, REGION_FILE  # noqa: E402
from tests.test_register import SAMPLE_101, read_bytes  # noqa: E402

NOW = "2026-11-04T00:00:00Z"
SVG_101 = os.path.join(os.path.dirname(SAMPLE_101), "01_SNP-M-101.drawio.svg")
# 일부 배포판(예: LibreOffice 내장 Python)은 sys.executable이 실행 파일이 아니므로 PATH의 python으로 대체한다
PYTHON = sys.executable if os.path.isfile(sys.executable) else (shutil.which("python") or sys.executable)
ENV_KEYS = (paths.ENV_RESOURCE_ROOT, paths.ENV_WORK_ROOT, paths.ENV_STORE_ROOT)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _clean_env():
    return {k: v for k, v in os.environ.items() if k not in ENV_KEYS}


class TmpCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.graph_file = os.path.join(self.tmp, "graph.json")
        _dump(self.graph_file, GRAPH)  # 샘플에서 만든 그래프(출력/에 의존하지 않음)

    def region_copy(self):
        path = os.path.join(self.tmp, "region.json")
        shutil.copyfile(REGION_FILE, path)
        return path


# ---------------------------------------------------------------- 경로 분리·설정
class PathsTest(unittest.TestCase):

    def test_defaults_are_repo_paths(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=True):
            self.assertEqual(paths.resource_root(), REPO_ROOT)
            self.assertEqual(paths.work_root(), os.path.join(REPO_ROOT, "작업"))  # 경로문자열-허용: 개발 작업 루트 기본값(계약)
            self.assertEqual(paths.store_root(), os.path.join(paths.DEV_WORK_ROOT, "자료저장소"))
            self.assertEqual(paths.output_root("분석"), os.path.join(paths.DEV_WORK_ROOT, "출력", "분석"))
        self.assertEqual(paths.REPO_ROOT, registry.REPO_ROOT)

    def test_env_overrides_and_store_priority(self):
        env = dict(_clean_env(), HAZOP_RESOURCE_ROOT="C:/r", HAZOP_WORK_ROOT="C:/w")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(paths.resource_root(), os.path.abspath("C:/r"))
            self.assertEqual(paths.store_root(), os.path.join(os.path.abspath("C:/w"), "자료저장소"))
            self.assertEqual(paths.folder("구간"), os.path.join(os.path.abspath("C:/w"), "데이터", "구간"))  # 경로문자열-허용: 작업 루트 배치 계약(배포본과 같음)
        with mock.patch.dict(os.environ, dict(env, HAZOP_STORE_ROOT="C:/s"), clear=True):
            self.assertEqual(paths.store_root(), "C:/s")  # HAZOP_STORE_ROOT 우선

    def test_frozen_detection_only(self):
        env = dict(_clean_env(), LOCALAPPDATA="C:/L")
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "_MEIPASS", "C:/bundle", create=True):
            self.assertEqual(paths.frozen_bundle_dir(), "C:/bundle")
            self.assertEqual(paths.resource_root(), "C:/bundle")
            self.assertEqual(paths.work_root(), os.path.join("C:/L", "HAZOP"))
        self.assertIsNone(paths.frozen_bundle_dir())

    def test_settings_roundtrip(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.dict(os.environ, {"APPDATA": tmp}):
            self.assertEqual(paths.settings_path(), os.path.join(tmp, "HAZOP", "settings.json"))
            self.assertEqual(paths.load_settings(), paths.DEFAULT_SETTINGS)  # 파일 없음 -> 기본값
            s = paths.load_settings()
            s["reviewer_name"] = "홍길동"
            s["recent_regions"] = ["데이터/구간/a.json"]  # 경로문자열-허용: 설정 파일에 저장된 사용자 값
            written = paths.save_settings(s)
            self.assertEqual(paths.load_settings(), s)
            self.assertFalse(os.path.exists(written + ".tmp"))
            with open(written, "w", encoding="utf-8") as fh:
                fh.write("[1, 2]")
            with self.assertRaises(ValueError):
                paths.load_settings()
        with self.assertRaises(ValueError):
            paths.save_settings(["x"], os.path.join(tmp, "s.json"))


# ---------------------------------------------------------------- SVG 파생 등록
class SvgDerivedTest(TmpCase):

    def put_pair(self, svg=True, name="P-1", sub="in"):
        d = os.path.join(self.tmp, sub)
        os.makedirs(d, exist_ok=True)
        drawio = os.path.join(d, name + ".drawio")
        shutil.copyfile(SAMPLE_101, drawio)
        if svg:
            shutil.copyfile(SVG_101, drawio + ".svg")
        return drawio

    def reg(self, path, **kw):
        return registry.register(path, "proj-1", store_root=os.path.join(self.tmp, "store"), actor="tester",
                                 now=lambda: NOW, **kw)

    def extract(self, reg_file):
        out = os.path.join(self.tmp, "ex")
        rc = extract_drawio.main(["--registration", reg_file, "--out-root", out])
        name = os.listdir(out)
        self.assertEqual((rc, len(name)), (0, 1))
        ex = _load(os.path.join(out, name[0], "extraction.json"))
        shutil.rmtree(out)
        return ex

    def entry(self, rec, name, page_ids, data, ver=1):
        return {"role": "svg", "page_ids": page_ids,
                "storage_ref": "originals/%s/%d/derived/%s" % (rec["material_id"], ver, name),
                "original_name": name, "sha256": registry.sha256_of(data), "size_bytes": len(data)}

    def test_same_name_svg_registered_and_used_first(self):
        drawio = self.put_pair()
        r = self.reg(drawio)
        rec = r["record"]
        self.assertEqual((r["outcome"], rec["status"]), ("registered", "registered"))
        self.assertEqual(rec["derived_files"], [self.entry(rec, "P-1.drawio.svg", ["p1"], read_bytes(SVG_101))])
        stored = registry.registered_svgs(r["registration_file"])
        self.assertEqual(list(stored), ["p1"])
        self.assertEqual(read_bytes(stored["p1"]), read_bytes(SVG_101))
        self.assertNotIn(registry.NO_SVG_FIELD, [u["field"] for u in rec["validation"]["unknowns"]])
        # 추출은 등록된 SVG를 먼저 쓴다(원본 옆 SVG를 지워도 동작)
        os.remove(drawio + ".svg")
        al = self.extract(r["registration_file"])["coordinate_system"]["svg_alignment"]
        self.assertEqual((al["source"], al["status"]), ("registered_derived", "verified"))
        self.assertTrue(al["svg_file"].endswith("derived/P-1.drawio.svg"))

    def test_stem_and_page_name_rules(self):
        # <stem>.svg
        drawio = self.put_pair(svg=False, sub="stem")
        shutil.copyfile(SVG_101, os.path.join(os.path.dirname(drawio), "P-1.svg"))
        rec = self.reg(drawio)["record"]
        self.assertEqual([d["original_name"] for d in rec["derived_files"]], ["P-1.svg"])
        # <NN>_<페이지 이름>.drawio.svg (샘플 이름 규칙). 다른 *.drawio.svg가 함께 있어도 페이지 이름으로 고른다
        drawio = self.put_pair(svg=False, name="P-2", sub="page")
        folder = os.path.dirname(drawio)
        want = os.path.join(folder, "01_SNP-M-101.drawio.svg")
        shutil.copyfile(SVG_101, want)
        with open(os.path.join(folder, "other.drawio.svg"), "w", encoding="utf-8") as fh:
            fh.write("<svg/>")
        self.assertEqual(svg_align.find_svg(drawio, 0, "SNP-M-101", 1), want)
        self.assertEqual(extract_drawio.find_svg(drawio, 0, "SNP-M-101", 1), want)  # 추출과 같은 함수
        r = registry.register(drawio, "proj-2", store_root=os.path.join(self.tmp, "store2"), actor="tester",
                              now=lambda: NOW)  # 같은 원본이므로 다른 저장 루트에 새로 등록
        self.assertEqual(r["record"]["derived_files"],
                         [self.entry(r["record"], "01_SNP-M-101.drawio.svg", ["p1"], read_bytes(SVG_101))])

    def test_sample_registration_matches_sibling_extraction(self):
        r = self.reg(SAMPLE_101)  # 샘플 폴더의 01_SNP-M-101.drawio.svg가 파생 자료로 등록됨
        rec = r["record"]
        self.assertEqual([(d["original_name"], d["page_ids"]) for d in rec["derived_files"]],
                         [("01_SNP-M-101.drawio.svg", ["p1"])])
        self.assertNotIn(registry.NO_SVG_FIELD, [u["field"] for u in rec["validation"]["unknowns"]])
        derived = self.extract(r["registration_file"])
        record, original = registry.load_for_extraction(r["registration_file"])
        sibling, _ = extract_drawio.run_one(original, os.path.join(self.tmp, "sib"), svg=SVG_101,
                                            registration=record)  # 원본 옆 SVG 직접 지정(기존 경로와 같은 파일)
        al_d, al_s = (x["coordinate_system"].pop("svg_alignment") for x in (derived, sibling))
        self.assertEqual(derived, sibling)  # SVG 출처 외에는 같은 추출 결과(미확인 항목 포함)
        self.assertEqual({k: v for k, v in al_d.items() if k not in ("svg_file", "source")},
                         {k: v for k, v in al_s.items() if k != "svg_file"})

    def test_multi_page_svgs_recorded_per_page(self):
        text = read_bytes(SAMPLE_101).decode("utf-8")
        diagram = re.search(r"<diagram\b.*</diagram>", text, re.S).group(0)
        second = diagram.replace('id="p1"', 'id="p2"', 1).replace('name="SNP-M-101"', 'name="PAGE-2"', 1)
        folder = os.path.join(self.tmp, "multi")
        os.makedirs(folder)
        drawio = os.path.join(folder, "two.drawio")
        with open(drawio, "w", encoding="utf-8") as fh:
            fh.write(text.replace(diagram, diagram + second))
        shutil.copyfile(SVG_101, os.path.join(folder, "01_SNP-M-101.drawio.svg"))
        shutil.copyfile(SVG_101, os.path.join(folder, "02_PAGE-2.drawio.svg"))
        shutil.copyfile(SVG_101, drawio + ".svg")  # 여러 페이지 문서에서는 같은 이름 SVG를 쓰지 않음
        r = self.reg(drawio)
        self.assertEqual(sorted((d["original_name"], tuple(d["page_ids"])) for d in r["record"]["derived_files"]),
                         [("01_SNP-M-101.drawio.svg", ("p1",)), ("02_PAGE-2.drawio.svg", ("p2",))])
        svgs = registry.registered_svgs(r["registration_file"])
        self.assertTrue(svgs["p2"].endswith("02_PAGE-2.drawio.svg"))
        out = os.path.join(self.tmp, "ex")
        self.assertEqual(extract_drawio.main(["--registration", r["registration_file"], "--page", "1",
                                              "--out-root", out]), 0)
        ex = _load(os.path.join(out, os.listdir(out)[0], "extraction.json"))
        al = ex["coordinate_system"]["svg_alignment"]
        self.assertEqual(al["source"], "registered_derived")
        self.assertTrue(al["svg_file"].endswith("02_PAGE-2.drawio.svg"))

    def two_page(self, folder, first="FIRST", second="SECOND"):
        text = read_bytes(SAMPLE_101).decode("utf-8")
        diagram = re.search(r"<diagram\b.*</diagram>", text, re.S).group(0)
        one = diagram.replace('name="SNP-M-101"', 'name="%s"' % first, 1)
        two = diagram.replace('id="p1"', 'id="p2"', 1).replace('name="SNP-M-101"', 'name="%s"' % second, 1)
        os.makedirs(folder, exist_ok=True)
        drawio = os.path.join(folder, "two.drawio")
        with open(drawio, "w", encoding="utf-8") as fh:
            fh.write(text.replace(diagram, one + two))
        return drawio

    def test_multi_page_single_svg_not_shared(self):
        folder = os.path.join(self.tmp, "multi1")
        drawio = self.two_page(folder)
        shutil.copyfile(SVG_101, os.path.join(folder, "01_FIRST.drawio.svg"))  # 하나뿐인 *.drawio.svg
        r = self.reg(drawio)
        rec = r["record"]
        self.assertEqual([(d["original_name"], d["page_ids"]) for d in rec["derived_files"]],
                         [("01_FIRST.drawio.svg", ["p1"])])
        miss = [u for u in rec["validation"]["unknowns"] if u["field"] == registry.NO_SVG_FIELD]
        self.assertEqual(len(miss), 1)
        self.assertIn("(페이지 p2)", miss[0]["reason"])
        self.assertEqual(list(registry.registered_svgs(r["registration_file"])), ["p1"])
        # 추출도 같은 규칙: 2페이지에는 SVG를 붙이지 않음
        self.assertIsNone(svg_align.find_svg(drawio, 1, "SECOND", 2))
        out = os.path.join(self.tmp, "ex2")
        self.assertEqual(extract_drawio.main([drawio, "--page", "1", "--out-root", out]), 0)
        ex = _load(os.path.join(out, os.listdir(out)[0], "extraction.json"))
        self.assertIsNone(ex["coordinate_system"]["svg_alignment"])

    def test_unsafe_page_name_is_skipped(self):
        for bad in ("../x", "a/b", "a\\b", "C:x", "a\x00b", "..", ""):
            self.assertFalse(svg_align._safe_page_name(bad), bad)
        self.assertTrue(svg_align._safe_page_name("SNP-M-101"))
        folder = os.path.join(self.tmp, "deep", "in")
        drawio = self.two_page(folder, first="../../../outside", second="SECOND")
        outside = os.path.join(self.tmp, "deep", "outside.drawio.svg")  # folder/01_../../../outside.drawio.svg 가 가리킬 곳
        shutil.copyfile(SVG_101, outside)
        self.assertIsNone(svg_align.find_svg(drawio, 0, "../../../outside", 2))
        rec = self.reg(drawio)["record"]
        self.assertEqual(rec["derived_files"], [])  # 폴더 밖 파일을 쓰지 않음
        # 한 페이지 문서도 같은 규칙: 위험한 페이지 이름 규칙은 건너뛰고 폴더 안 규칙만
        single = os.path.join(self.tmp, "deep", "single")
        os.makedirs(single)
        one = os.path.join(single, "one.drawio")
        shutil.copyfile(SAMPLE_101, one)
        self.assertIsNone(svg_align.find_svg(one, 0, "../outside", 1))

    def test_no_svg_records_unknown(self):
        drawio = self.put_pair(svg=False)
        for name in ("a.drawio.svg", "b.drawio.svg"):  # 이름이 맞지 않고 하나뿐도 아님
            shutil.copyfile(SVG_101, os.path.join(os.path.dirname(drawio), name))
        r = self.reg(drawio)
        rec = r["record"]
        self.assertEqual((rec["status"], rec["derived_files"]), ("registered", []))
        self.assertIn("SVG 없음", next(u["reason"] for u in rec["validation"]["unknowns"]
                                      if u["field"] == registry.NO_SVG_FIELD))
        self.assertEqual(registry.registered_svgs(r["registration_file"]), {})
        self.assertIsNone(self.extract(r["registration_file"])["coordinate_system"]["svg_alignment"])

    def test_svg_change_creates_new_version(self):
        drawio = self.put_pair()
        v1 = self.reg(drawio)
        v1_bytes = read_bytes(v1["registration_file"])
        self.assertEqual(self.reg(drawio)["outcome"], "reused")  # 같은 원본·같은 SVG
        with open(drawio + ".svg", "ab") as fh:
            fh.write(b"<!-- changed -->")
        v2 = self.reg(drawio)
        rec = v2["record"]
        self.assertEqual((v2["outcome"], rec["registration_version"]), ("new_version", 2))
        self.assertEqual(rec["storage_ref"], v1["record"]["storage_ref"])  # 원본은 같은 보관본
        self.assertEqual(rec["derived_files"],
                         [self.entry(rec, "P-1.drawio.svg", ["p1"], read_bytes(drawio + ".svg"), ver=2)])
        self.assertEqual(rec["history"][-1]["action"], "register_derived")
        self.assertEqual(read_bytes(v1["registration_file"]), v1_bytes)  # 이전 버전 불변
        self.assertEqual(read_bytes(registry.registered_svgs(v2["registration_file"])["p1"]),
                         read_bytes(drawio + ".svg"))
        # SVG를 치우고 다시 등록하면 기존 버전 재사용(새 버전 없음)
        os.remove(drawio + ".svg")
        again = self.reg(drawio)
        self.assertEqual((again["outcome"], again["record"]["registration_version"]), ("reused", 2))
        self.assertTrue(any("SVG" in n for n in again["notes"]))

    def test_tampered_derived_svg_blocks_extraction(self):
        r = self.reg(self.put_pair())
        with open(registry.registered_svgs(r["registration_file"])["p1"], "ab") as fh:
            fh.write(b" ")
        with self.assertRaises(ValueError):
            registry.registered_svgs(r["registration_file"])
        with self.assertRaises(SystemExit):
            extract_drawio.main(["--registration", r["registration_file"], "--out-root", os.path.join(self.tmp, "x")])

    def test_derived_store_failure_then_retry(self):
        drawio = self.put_pair()
        real = registry._write_new

        def fail_svg(path, data):
            if path.endswith(".svg"):
                raise OSError("SVG 저장 실패(모의)")
            return real(path, data)
        with mock.patch.object(registry, "_write_new", fail_svg):
            r = self.reg(drawio)
        self.assertEqual((r["outcome"], r["record"]["status"]), ("failed", "failed"))
        self.assertEqual(r["record"]["validation"]["blockers"][0]["field"], "derived_files")
        retry = self.reg(drawio)
        self.assertEqual((retry["outcome"], retry["record"]["status"]), ("registered", "registered"))
        self.assertEqual(list(registry.registered_svgs(retry["registration_file"])), ["p1"])


# ---------------------------------------------------------------- 후보 판단 변경
class CandidateDecisionTest(TmpCase):

    def test_append_history_and_bump_version(self):
        region_path = self.region_copy()
        before = _load(region_path)
        # 열려 있는 실행 결과(analysis.json)는 바뀌지 않아야 한다
        inputs = run.load_inputs(region_path, REPO_ROOT, graph_path=self.graph_file)
        _, run_dir = run.execute(inputs, ai.FixedResponseClient(FIXED_DIR), os.path.join(self.tmp, "분석"),
                                 run_id="analysis-open")
        analysis = os.path.join(run_dir, "analysis.json")
        analysis_bytes = read_bytes(analysis)
        res = candidate_edit.change_candidate_decision(region_path, "deviation-p86-d09", "excluded", "검토자",
                                                       "검토 회의 결과 적용 불가", now=lambda: NOW)
        self.assertEqual((res["previous_status"], res["region_version"]), ("selected", before["region_version"] + 1))
        self.assertEqual(res["notice"], candidate_edit.REANALYZE_NOTICE)
        res2 = candidate_edit.change_candidate_decision(region_path, "deviation-p86-d09", "deferred", "검토자",
                                                        "추가 자료 확인", now=lambda: NOW)
        after = _load(region_path)
        self.assertEqual(after["region_version"], before["region_version"] + 2)
        self.assertEqual(after["candidate_decisions"], before["candidate_decisions"] + [res["decision"], res2["decision"]])
        self.assertEqual(res["decision"], {"candidate_id": "deviation-p86-d09", "selection_status": "excluded",
                                           "decided_by": "검토자", "reason": "검토 회의 결과 적용 불가",
                                           "decided_at": NOW})
        self.assertEqual({k: v for k, v in after.items() if k not in ("candidate_decisions", "region_version")},
                         {k: v for k, v in before.items() if k not in ("candidate_decisions", "region_version")})
        self.assertEqual(read_bytes(analysis), analysis_bytes)
        # 재분석 때 판단 이력(previous 포함)으로 이어진다
        again = run.load_inputs(region_path, REPO_ROOT, graph_path=self.graph_file)
        c = next(x for x in cand_mod.build_candidates(again["catalog"], again["applicability"], after, {}, NOW)
                 if x["candidate_id"] == "deviation-p86-d09")
        self.assertEqual([(j["selection_status"], j.get("previous")) for j in c["judgments"]],
                         [("selected", None), ("excluded", "selected"), ("deferred", "excluded")])
        self.assertEqual(c["selection_status"], "deferred")

    def test_rejected_inputs_do_not_touch_file(self):
        region_path = self.region_copy()
        original = read_bytes(region_path)
        bad = [("deviation-p86-d09", "excluded", "검토자", ""),
               ("deviation-p86-d09", "excluded", "검토자", "   "),
               ("deviation-p86-d09", "excluded", "", "사유"),
               ("deviation-p86-d09", "accepted", "검토자", "사유"),
               ("deviation-p86-d99", "excluded", "검토자", "사유")]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(candidate_edit.DecisionError):
                candidate_edit.change_candidate_decision(region_path, *args)
        self.assertEqual(read_bytes(region_path), original)

    def test_write_failure_keeps_original(self):
        region_path = self.region_copy()
        original = read_bytes(region_path)
        with mock.patch("os.replace", side_effect=OSError("교체 실패(모의)")):
            with self.assertRaises(OSError):
                candidate_edit.change_candidate_decision(region_path, "deviation-p86-d09", "excluded", "검토자", "사유")
        self.assertEqual(read_bytes(region_path), original)


# ---------------------------------------------------------------- 근거 묶음 내보내기·분석 API
class BundleExportTest(TmpCase):

    def export(self, now=NOW, out=None):
        return bundle_export.export_bundles(REGION_FILE, out or os.path.join(self.tmp, "근거묶음"),
                                            graph_path=self.graph_file, now=lambda: now)

    def test_export_matches_fixed_responses(self):
        region_before = read_bytes(REGION_FILE)
        res = self.export()
        m = res["manifest"]
        d = res["export_dir"]
        self.assertEqual(d, os.path.join(self.tmp, "근거묶음", "region-SNP-M-102-pzr", "20261104T000000Z"))
        by_id = {c["candidate_id"]: c for c in m["candidates"]}
        fixed = sorted(f for f in os.listdir(FIXED_DIR) if f.endswith(".json"))
        self.assertTrue(fixed)
        for f in fixed:  # 기존 고정 응답의 bundle_sha256 = 내보낸 값
            self.assertEqual(_load(os.path.join(FIXED_DIR, f))["bundle_sha256"], by_id[f[:-5]]["bundle_sha256"])
        for c in m["candidates"]:
            bundle = _load(os.path.join(d, c["bundle_file"]))
            self.assertEqual(ai.bundle_sha256(bundle), c["bundle_sha256"])
            with open(os.path.join(d, c["user_prompt_file"]), encoding="utf-8", newline="") as fh:
                self.assertEqual(fh.read(), ai.build_request(bundle)["user"])
            tmpl = _load(os.path.join(d, c["response_file"]))
            self.assertEqual(tmpl, {"region_id": "region-SNP-M-102-pzr", "bundle_sha256": c["bundle_sha256"],
                                    "stop_reason": "end_turn", "output": None})
        self.assertEqual(_load(os.path.join(d, "response_schema.json")), ai.RESPONSE_SCHEMA)
        with open(os.path.join(d, "system_prompt.txt"), encoding="utf-8", newline="") as fh:
            self.assertEqual(fh.read(), ai.SYSTEM_PROMPT)
        self.assertEqual(m["template"], ai.template_info())
        self.assertEqual((m["graph"]["graph_version"], m["region"]["region_version"]), (GRAPH["graph_version"], _load(REGION_FILE)["region_version"]))
        with open(os.path.join(d, "response_guide.txt"), encoding="utf-8") as fh:
            guide = fh.read()
        for field in ("region_id", "bundle_sha256", "stop_reason", "output"):
            self.assertIn(field, guide)
        # 선택 후보만, 실행 폴더·analysis.json 없음
        inputs = api.load_region_inputs(REGION_FILE, self.graph_file)
        doc = run.analyze(inputs, None, run_id="x", now=lambda: NOW)
        self.assertEqual(sorted(by_id), sorted(c["candidate_id"] for c in doc["candidates"]
                                               if c["selection_status"] == "selected"))
        all_files = [f for _, _, fs in os.walk(self.tmp) for f in fs]
        self.assertNotIn("analysis.json", all_files)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["graph.json", "근거묶음"])
        self.assertEqual(read_bytes(REGION_FILE), region_before)

    def test_deterministic_and_no_overwrite(self):
        a = self.export(NOW)["manifest"]
        b = self.export("2026-11-05T09:30:00Z")["manifest"]
        self.assertEqual([(c["candidate_id"], c["bundle_sha256"], c["user_sha256"]) for c in a["candidates"]],
                         [(c["candidate_id"], c["bundle_sha256"], c["user_sha256"]) for c in b["candidates"]])
        with self.assertRaises(run.InputError):
            self.export(NOW)
        region_dir = os.path.join(self.tmp, "근거묶음", "region-SNP-M-102-pzr")
        self.assertEqual(sorted(os.listdir(region_dir)), ["20261104T000000Z", "20261105T093000Z"])  # 임시 폴더 없음

    def test_failure_leaves_no_partial_folder(self):
        out = os.path.join(self.tmp, "근거묶음")
        real = bundle_export._write_text
        calls = []

        def fail_late(path, text):
            calls.append(path)
            if len(calls) == 3:
                raise OSError("쓰기 실패(모의)")
            return real(path, text)
        with mock.patch.object(bundle_export, "_write_text", fail_late):
            with self.assertRaises(OSError):
                self.export(out=out)
        self.assertEqual(os.listdir(out), [])  # 일부만 만든 폴더·임시 폴더·구간 폴더가 남지 않음
        # 이미 있는 구간 폴더의 다른 내보내기는 그대로 둔다
        first = self.export("2026-11-05T09:30:00Z", out=out)["export_dir"]
        calls.clear()
        with mock.patch.object(bundle_export, "_write_text", fail_late):
            with self.assertRaises(OSError):
                self.export(out=out)
        self.assertEqual(os.listdir(os.path.dirname(first)), [os.path.basename(first)])

    def test_response_file_names_use_safe_name(self):
        res = self.export()
        for c in res["manifest"]["candidates"]:
            name = paths.safe_name(c["candidate_id"])
            self.assertEqual((c["response_file"], c["bundle_file"]),
                             ("responses/%s.json" % name, "%s/bundle.json" % name))
        real = bundle_export.build_export

        def bad_id(inputs, now):
            t, selected, bundles = real(inputs, now)
            cid = selected[0]["candidate_id"]
            selected[0] = dict(selected[0], candidate_id="../" + cid)
            bundles["../" + cid] = bundles[cid]
            return t, selected, bundles
        out = os.path.join(self.tmp, "bad")
        with mock.patch.object(bundle_export, "build_export", bad_id):
            with self.assertRaises(run.InputError):
                self.export(out=out)
        self.assertFalse(os.path.exists(out))

    def test_blocked_inputs_export_nothing(self):
        g = json.loads(json.dumps(GRAPH))
        g["graph_version"] = "v-other"
        _dump(self.graph_file, g)
        out = os.path.join(self.tmp, "근거묶음")
        with self.assertRaises(run.InputError):
            self.export(out=out)
        self.assertFalse(os.path.exists(out))
        self.assertEqual(export_cli.main(["--region", REGION_FILE, "--graph", self.graph_file, "--out-root", out]), 1)
        self.assertFalse(os.path.exists(out))

    def test_roundtrip_with_response_folder(self):
        res = self.export()
        resp = res["response_dir"]
        out = os.path.join(self.tmp, "분석")
        # 응답 틀을 채우지 않고 불러오면 검증 실패로 남고 결과에 쓰이지 않는다(예외 없음)
        empty = api.run_analysis(REGION_FILE, response_dir=resp, out_root=out, graph_path=self.graph_file,
                                 run_id="analysis-empty")
        self.assertTrue(all(c["analysis"]["ai_status"] == "validation_failed"
                            for c in empty["doc"]["candidates"] if c["selection_status"] == "selected"))
        # 기존 고정 응답으로 채우면 analyze.py 결과와 같은 수
        for f in os.listdir(FIXED_DIR):
            shutil.copyfile(os.path.join(FIXED_DIR, f), os.path.join(resp, f))
        got = api.run_analysis(REGION_FILE, response_dir=resp, out_root=out, graph_path=self.graph_file,
                               run_id="analysis-filled")
        want = api.run_analysis(REGION_FILE, response_dir=FIXED_DIR, out_root=out, graph_path=self.graph_file,
                                run_id="analysis-fixed")
        keys = ("candidates", "scenarios", "risk_proposed", "design_improvement_candidates", "ai_validated")
        gc, wc = got["doc"]["validation"]["counts"], want["doc"]["validation"]["counts"]
        self.assertEqual([gc[k] for k in keys], [wc[k] for k in keys])
        self.assertEqual([wc[k] for k in keys[:4]], [44, 14, 6, 11])
        self.assertEqual((got["status"], want["status"]), ("passed", "passed"))
        self.assertTrue(os.path.isfile(os.path.join(got["run_dir"], "analysis.json")))
        # bundle_sha256이 다른 응답은 input_mismatch, 결과에 쓰이지 않음
        target = os.path.join(resp, "deviation-p86-d09.json")
        doc = _load(target)
        doc["bundle_sha256"] = "0" * 64
        _dump(target, doc)
        bad = api.run_analysis(REGION_FILE, response_dir=resp, out_root=out, graph_path=self.graph_file,
                               run_id="analysis-mismatch")
        c = next(x for x in bad["doc"]["candidates"] if x["candidate_id"] == "deviation-p86-d09")
        self.assertEqual(c["analysis"]["ai_status"], "input_mismatch")
        self.assertFalse(any(s["ai_interpretation"] for s in bad["doc"]["scenarios"]
                             if s["candidate_id"] == "deviation-p86-d09"))

    def test_api_input_blocked_and_client_sources(self):
        g = json.loads(json.dumps(GRAPH))
        g["graph_version"] = "v-other"
        _dump(self.graph_file, g)
        out = os.path.join(self.tmp, "분석")
        res = api.run_analysis(REGION_FILE, response_dir=FIXED_DIR, out_root=out, graph_path=self.graph_file)
        self.assertEqual((res["status"], res["doc"], res["run_dir"]), ("input_blocked", None, None))
        self.assertTrue(res["blockers"])
        self.assertFalse(os.path.exists(out))
        with self.assertRaises(ValueError):
            api.make_client("anthropic_api", FIXED_DIR)  # 화면에서는 비활성(확장 지점)
        with self.assertRaises(ValueError):
            api.make_client("fixed_response", None)


# ---------------------------------------------------------------- 패키징 대비: 자원 루트·작업 루트 변경 (§8)
class SplitRootsTest(TmpCase):
    """자원 루트·작업 루트를 임시 폴더로 바꿔 CLI를 새 프로세스로 실행한다(기본 콘솔 인코딩, 네트워크 없음)."""

    def run_cli(self, env, *args):
        p = subprocess.run([PYTHON] + list(args), cwd=self.tmp, env=env, capture_output=True, timeout=300)
        return p.returncode, p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")

    def test_analyze_extract_export_with_split_roots(self):
        res, work = os.path.join(self.tmp, "res"), os.path.join(self.tmp, "work")
        region = _load(REGION_FILE)
        for rel in list(region["inputs"].values()) + ["기획서/HAZOP기법지침.md"]:
            os.makedirs(os.path.dirname(os.path.join(res, rel)), exist_ok=True)
            shutil.copyfile(paths.resolve_rel(rel, REPO_ROOT), os.path.join(res, rel))
        os.makedirs(paths.folder_in(work, "구간"))
        shutil.copyfile(REGION_FILE, paths.folder_in(work, "구간", os.path.basename(REGION_FILE)))
        shutil.copytree(FIXED_DIR, paths.folder_in(work, "고정응답", os.path.basename(FIXED_DIR)))
        _dump(os.path.join(work, region["graph_ref"]["graph_file"]), GRAPH)
        env = dict(_clean_env(), HAZOP_RESOURCE_ROOT=res, HAZOP_WORK_ROOT=work)
        env.pop("PYTHONIOENCODING", None)
        repo_runs = sorted(os.listdir(os.path.join(paths.DEV_WORK_ROOT, "출력", "분석"))) \
            if os.path.isdir(os.path.join(paths.DEV_WORK_ROOT, "출력", "분석")) else []

        rc, out = self.run_cli(env, os.path.join(REPO_ROOT, "scripts", "analyze.py"), "--run-id", "analysis-split")
        self.assertEqual(rc, 0, out)
        doc = _load(os.path.join(work, "출력", "분석", region["region_id"], "analysis-split", "analysis.json"))
        c = doc["validation"]["counts"]
        self.assertEqual((c["candidates"], c["scenarios"], c["risk_proposed"], c["design_improvement_candidates"]),
                         (44, 14, 6, 11))
        self.assertEqual(doc["graph_ref"]["graph_version"], region["graph_ref"]["graph_version"])
        self.assertEqual({f["role"]: f["path"] for f in doc["analysis_run"]["input_files"]},
                         dict(region["inputs"], region=paths.folder_rel("구간") + "/" + os.path.basename(REGION_FILE),
                              graph=region["graph_ref"]["graph_file"]))
        self.assertEqual(doc["analysis_run"]["ai_client"]["response_dir"],
                         paths.folder_rel("고정응답") + "/" + os.path.basename(FIXED_DIR))

        rc, out = self.run_cli(env, os.path.join(REPO_ROOT, "scripts", "export_bundles.py"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(os.listdir(os.path.join(work, "출력", "근거묶음", region["region_id"]))), 1)

        drawio = os.path.join(work, "in", "P-1.drawio")
        os.makedirs(os.path.dirname(drawio))
        shutil.copyfile(SAMPLE_101, drawio)
        shutil.copyfile(SVG_101, drawio + ".svg")
        rc, out = self.run_cli(env, os.path.join(REPO_ROOT, "scripts", "register.py"), "--project", "p", drawio)
        self.assertEqual(rc, 0, out)
        reg_dir = os.path.join(work, "자료저장소", "p", "registrations")
        mid = os.listdir(reg_dir)[0]
        rc, out = self.run_cli(env, os.path.join(REPO_ROOT, "scripts", "extract_drawio.py"),
                               "--registration", os.path.join(reg_dir, mid, "1.json"))
        self.assertEqual(rc, 0, out)
        ex = _load(os.path.join(work, "출력", "추출", "p__%s-r1-p0" % mid, "extraction.json"))
        al = ex["coordinate_system"]["svg_alignment"]
        self.assertEqual((al["source"], al["svg_file"]),
                         ("registered_derived", "자료저장소/p/originals/%s/1/derived/P-1.drawio.svg" % mid))
        self.assertEqual(_load(os.path.join(reg_dir, mid, "1.json"))["input_path"], "in/P-1.drawio")

        now_runs = sorted(os.listdir(os.path.join(paths.DEV_WORK_ROOT, "출력", "분석"))) \
            if os.path.isdir(os.path.join(paths.DEV_WORK_ROOT, "출력", "분석")) else []
        self.assertEqual(now_runs, repo_runs)  # 저장소 출력/은 건드리지 않음

        # 자원 루트에 기준 자료가 없으면 분석하지 않는다(저장소 자료로 몰래 대체하지 않음)
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        rc, out = self.run_cli(dict(env, HAZOP_RESOURCE_ROOT=empty),
                               os.path.join(REPO_ROOT, "scripts", "analyze.py"), "--run-id", "analysis-noresource")
        self.assertEqual(rc, 1, out)
        self.assertFalse(os.path.exists(os.path.join(work, "출력", "분석", region["region_id"], "analysis-noresource")))


class SplitRootsViewerTest(TmpCase):
    """작업 루트를 저장소 밖으로 두고 샘플 추출 -> 뷰어(--graph-root none). SVG는 자원 루트·저장 루트·작업 루트 안만 허용."""

    def test_samples_viewer_with_work_root_outside_repo(self):
        work = os.path.join(self.tmp, "work")
        env = dict(_clean_env(), HAZOP_RESOURCE_ROOT=REPO_ROOT, HAZOP_WORK_ROOT=work)
        ex_root, v_root = os.path.join(work, "출력", "추출"), os.path.join(work, "출력", "뷰어")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(extract_drawio.main(["--samples", "--out-root", ex_root]), 0)
            self.assertEqual(build_viewer.main(["--extract-root", ex_root, "--out-root", v_root,
                                                "--graph-root", "none"]), 0)
            self.assertEqual(len([f for f in os.listdir(v_root) if f != "index.html"]), 6)
            # 허용 루트(작업·자원·저장) 밖 SVG를 가리키는 추출 결과는 거부
            outside = os.path.join(self.tmp, "outside", "evil.drawio.svg")
            os.makedirs(os.path.dirname(outside))
            shutil.copyfile(SVG_101, outside)
            name = sorted(os.listdir(ex_root))[0]
            path = os.path.join(ex_root, name, "extraction.json")
            ex = _load(path)
            ex["coordinate_system"]["svg_alignment"]["svg_file"] = outside
            _dump(path, ex)
            with self.assertRaises(ValueError):
                build_viewer.main(["--extract-root", ex_root, "--out-root", os.path.join(self.tmp, "v2"),
                                   "--graph-root", "none"])
            ex["coordinate_system"]["svg_alignment"]["svg_file"] = "../outside/evil.drawio.svg"  # 상대 경로로 밖
            _dump(path, ex)
            with self.assertRaises(ValueError):
                build_viewer.main(["--extract-root", ex_root, "--out-root", os.path.join(self.tmp, "v3"),
                                   "--graph-root", "none"])


if __name__ == "__main__":
    unittest.main()
