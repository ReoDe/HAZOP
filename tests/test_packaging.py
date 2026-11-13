"""패키징 대비 테스트(docs/units/2026-11-05-packaging W3, 기획서/인터페이스.md §7.1·§8 '패키징 대비' 행).

1) hazop/paths.py 공개 API 하위 호환: 기존 이름·인자가 그대로 있다(추가만 허용).
2) hazop/app/data.py의 scripts/ importlib 로딩 경로: 개발 실행은 저장소, 묶인 실행은 묶음 폴더(sys._MEIPASS).
   묶인 실행은 빌드하지 않고 sys.frozen·sys._MEIPASS를 패치해 모의한다. 이 테스트의 통과는 경로 선택만 검증하며,
   실제 실행 파일의 의존성(hiddenimports)·자료(datas) 포함·기동 성공을 보장하지 않는다(실빌드 확인은 W4).
3) HAZOP_RESOURCE_ROOT·HAZOP_WORK_ROOT를 서로 다른 임시 폴더로 바꿔 ①~⑤ 흐름(등록·추출·그래프 → 뷰어 → 지식그래프 →
   분석 → 검토 저장·Excel 출력)을 화면이 쓰는 함수로 실행한다. 자원 루트와 저장소의 output/·store/는 바뀌지 않는다.
4) W4: scripts/build_package.py의 datas 목록·spec 원문을 빌드 없이 검사한다(코드의 경로 상수와 대조).
5) W6·W9: licenses/README.md 고지 목록이 기준 목록(원문 경로·라이선스 식별자)과 맞고, 원문 파일의 SHA-256·버전이 목록과
   같다. W9(D15)부터 licenses/는 datas가 아니라 빌드 뒤 실행 파일 옆 licenses/로 복사되며, 그 복사·대조 함수
   (build_package.copy_licenses·licenses_problems, verify_bundle.licenses_problems)를 빌드 없이 검사한다.
6) W9(D15): PDF 어댑터(pdfplumber와 의존성)를 묶는다. spec의 hiddenimports·excludes, 빌드 뒤 PDF 검사(pdf_problems),
   verify의 pdf_probe 판정(pdf_probe_problems), packaging/requirements-pdf.txt의 고정·해시를 빌드 없이 검사한다.
실행: python -m unittest discover -s tests. 임시 폴더만 쓴다. 네트워크·AI 호출 없음(고정 응답).
"""

import glob
import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.run_fixture import FIXED_DIR, REGION_FILE, REPO_ROOT

from hazop import paths  # noqa: E402
from hazop import review as rv  # noqa: E402
from hazop.analysis import api, run as run_mod  # noqa: E402
from hazop.app import data  # noqa: E402
from hazop.export import export_worksheet  # noqa: E402
from hazop.kg import build as kg_build, inputs as kg_inputs, screen as kg_screen  # noqa: E402
from hazop.register import registry  # noqa: E402
from tests.test_analysis import GRAPH  # noqa: E402

TLS_OK = ("qschannelbackend.dll", "qcertonlybackend.dll")
ENV_KEYS = (paths.ENV_RESOURCE_ROOT, paths.ENV_WORK_ROOT, paths.ENV_STORE_ROOT)
SAMPLE_DIR = paths.folder("references", "pid-samples")
KG_SAMPLE = paths.folder("samples", "knowledge-graph", "SNP-SAMPLE")
T = "2026-11-05T00:00:00Z"

# W3 착수 시점(ddb9a50) paths.py 공개 API. 이름·인자를 바꾸면 실패한다(새 함수 추가는 허용).
# 규칙: 기존 함수에 선택 인자를 추가할 때(하위 호환 변경)는 이 표도 함께 고친다. 필수 인자 추가·이름 변경은 금지.
PATHS_SIGNATURES = {
    "safe_name": "(name, default='drawing')",
    "safe_join": "(root, name)",
    "rel_or_abs": "(path, root)",
    "frozen_bundle_dir": "()",
    "resource_root": "()",
    "work_root": "()",
    "resource_path": "(*parts)",
    "work_path": "(*parts)",
    "store_root": "()",
    "output_root": "(*parts)",
    "settings_path": "()",
    "load_settings": "(path=None)",
    "save_settings": "(settings, path=None)",
}
PATHS_CONSTANTS = {
    "ENV_RESOURCE_ROOT": "HAZOP_RESOURCE_ROOT",
    "ENV_WORK_ROOT": "HAZOP_WORK_ROOT",
    "ENV_STORE_ROOT": "HAZOP_STORE_ROOT",
    "RESOURCE_INPUT_ROLES": ("candidate_catalog", "applicability", "patterns", "risk_criteria"),
}
# DEFAULT_SETTINGS는 기존 키·값이 들어 있는지만 본다(키 추가는 허용)
DEFAULT_SETTINGS_BASE = {"reviewer_name": None, "work_root": None, "recent_regions": [], "recent_runs": []}


def _clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    env.update(extra)
    return env


def _tree(root):
    """{상대 경로: sha256} — 폴더가 없으면 빈 dict."""
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def _names(root):
    return sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs) \
        if os.path.isdir(root) else []


class FrozenMock:
    """sys.frozen·sys._MEIPASS를 패치하고 script_module 캐시·sys.path를 격리한다. bundle=None이면 _MEIPASS 없음."""

    def __init__(self, bundle, frozen=True):
        self.bundle, self.frozen = bundle, frozen

    def __enter__(self):
        self._path = list(sys.path)
        self._patches = [mock.patch.dict(data._script_cache, {}, clear=True)]
        self._patches.append(mock.patch.object(sys, "frozen", bool(self.frozen), create=True))
        if self.bundle:
            self._patches.append(mock.patch.object(sys, "_MEIPASS", self.bundle, create=True))
        for p in self._patches:
            p.start()
        self._meipass = sys.__dict__.pop("_MEIPASS", None) if not self.bundle else None  # 외부 상태와 격리
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        if self._meipass is not None:
            sys._MEIPASS = self._meipass
        sys.path[:] = self._path


# ---------------------------------------------------------------- 1) paths.py 하위 호환
class PathsCompatTest(unittest.TestCase):

    def test_existing_api_unchanged(self):
        for name, sig in PATHS_SIGNATURES.items():
            self.assertTrue(callable(getattr(paths, name, None)), name)
            self.assertEqual(str(inspect.signature(getattr(paths, name))), sig, name)
        for name, value in PATHS_CONSTANTS.items():
            self.assertEqual(getattr(paths, name), value, name)
        for k, v in DEFAULT_SETTINGS_BASE.items():
            self.assertIn(k, paths.DEFAULT_SETTINGS)
            self.assertEqual(paths.DEFAULT_SETTINGS[k], v, k)
        self.assertEqual(paths.REPO_ROOT, REPO_ROOT)

    def test_program_root_dev_ignores_resource_env(self):
        with mock.patch.dict(os.environ, _clean_env(HAZOP_RESOURCE_ROOT="C:/r"), clear=True):
            self.assertIsNone(paths.frozen_bundle_dir())
            self.assertEqual(paths.program_root(), REPO_ROOT)
            self.assertEqual(paths.program_path("scripts"), os.path.join(REPO_ROOT, "scripts"))
            self.assertEqual(paths.resource_root(), os.path.abspath("C:/r"))

    def test_frozen_detection_combinations(self):
        """frozen 판단은 sys._MEIPASS만 본다(기존 resource_root·work_root와 같은 방식)."""
        env = _clean_env(LOCALAPPDATA="C:/L")
        cases = [(False, None, REPO_ROOT), (True, None, REPO_ROOT),       # sys.frozen만: 개발 실행으로 취급
                 (False, "C:/b", "C:/b"), (True, "C:/b", "C:/b")]          # _MEIPASS 있으면 묶음
        for frozen, bundle, want in cases:
            with self.subTest(frozen=frozen, meipass=bundle), mock.patch.dict(os.environ, env, clear=True), \
                    FrozenMock(bundle, frozen=frozen):
                self.assertEqual(paths.frozen_bundle_dir(), bundle)
                self.assertEqual((paths.program_root(), paths.resource_root()), (want, want))
                self.assertEqual(paths.work_root(), os.path.join("C:/L", "HAZOP") if bundle else paths.DEV_WORK_ROOT)


# ---------------------------------------------------------------- 2) importlib 로딩 경로
class ScriptLoadingTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-pkg-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_dev_loads_repo_scripts(self):
        with mock.patch.dict(data._script_cache, {}, clear=True), \
                mock.patch.dict(os.environ, _clean_env(HAZOP_RESOURCE_ROOT=self.tmp), clear=True):
            for name in ("extract_drawio", "build_graph"):
                mod = data.script_module(name)
                self.assertEqual(os.path.normcase(mod.__file__),
                                 os.path.normcase(os.path.join(REPO_ROOT, "scripts", name + ".py")))
        self.assertEqual(data.SCRIPTS_DIR, os.path.join(REPO_ROOT, "scripts"))

    def test_frozen_loads_bundle_scripts(self):
        bundle = os.path.join(self.tmp, "dist", "HAZOP", "_internal")
        os.makedirs(os.path.join(bundle, "scripts"))
        for name in ("extract_drawio", "build_graph"):
            shutil.copy(os.path.join(REPO_ROOT, "scripts", name + ".py"), os.path.join(bundle, "scripts"))
        local = os.path.join(self.tmp, "local")
        with mock.patch.dict(os.environ, _clean_env(LOCALAPPDATA=local), clear=True), FrozenMock(bundle):
            self.assertEqual(paths.program_root(), bundle)
            self.assertEqual(paths.resource_root(), bundle)
            self.assertEqual(paths.work_root(), os.path.join(local, "HAZOP"))
            ex = data.script_module("extract_drawio")
            bg = data.script_module("build_graph")
            self.assertEqual(os.path.normcase(ex.__file__),
                             os.path.normcase(os.path.join(bundle, "scripts", "extract_drawio.py")))
            self.assertEqual(os.path.normcase(bg.__file__),
                             os.path.normcase(os.path.join(bundle, "scripts", "build_graph.py")))
            self.assertTrue(callable(ex.run_one) and callable(ex.registered_out_name) and callable(bg.build_one))
        self.assertFalse(hasattr(sys, "_MEIPASS"))

    def test_frozen_missing_script_reports_path(self):
        bundle = os.path.join(self.tmp, "empty_bundle")
        os.makedirs(bundle)
        with FrozenMock(bundle):
            with self.assertRaises(FileNotFoundError) as cm:
                data.script_module("extract_drawio")
            self.assertIn(os.path.join(bundle, "scripts", "extract_drawio.py"), str(cm.exception))
            self.assertEqual(data._script_cache, {})

    def test_cache_keyed_by_path(self):
        """같은 이름이라도 프로그램 루트가 바뀌면 이전 모듈을 돌려주지 않는다."""
        bundles = []
        for i in range(2):
            b = os.path.join(self.tmp, "b%d" % i)
            os.makedirs(os.path.join(b, "scripts"))
            shutil.copy(os.path.join(REPO_ROOT, "scripts", "build_graph.py"), os.path.join(b, "scripts"))
            bundles.append(b)
        # 작업 루트를 임시 폴더로 돌린다: 묶인 실행의 기본 작업 루트는 이 PC의 실제 배포본 작업 폴더이고 그 배치에 따라 결과가 갈린다
        with FrozenMock(bundles[0]), mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: os.path.join(self.tmp, "w")}):
            m0 = data.script_module("build_graph")
            self.assertIs(data.script_module("build_graph"), m0)  # 같은 경로는 캐시
            with mock.patch.object(sys, "_MEIPASS", bundles[1]):
                m1 = data.script_module("build_graph")
            self.assertIsNot(m1, m0)
            self.assertTrue(os.path.normcase(m1.__file__).startswith(os.path.normcase(bundles[1])))
            self.assertEqual(len(data._script_cache), 2)

    def test_name_restricted(self):
        with mock.patch.dict(data._script_cache, {}, clear=True):
            for bad in ("analyze", "../scripts/build_graph", r"scripts\build_graph", "scripts/build_graph", r"..\build_graph",
                        os.path.join(REPO_ROOT, "scripts", "build_graph"), "C:build_graph", "", None):
                with self.subTest(name=bad), self.assertRaises(ValueError):
                    data.script_module(bad)
            self.assertEqual(data._script_cache, {})
        self.assertEqual(data.SCRIPT_NAMES, ("extract_drawio", "extract_pdf", "build_graph"))


# ---------------------------------------------------------------- 3) 자원 루트·작업 루트 분리 ①~⑤
class SplitRootsFlowTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-pkg-flow-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.res, self.work = os.path.join(self.tmp, "res"), os.path.join(self.tmp, "work")
        region = data.read_json(REGION_FILE)
        # 자원 루트: 기준 자료 4종·기법 지침서·샘플 도면(읽기 전용)
        for rel in list(region["inputs"].values()) + [paths.file_rel("guide")]:
            os.makedirs(os.path.dirname(os.path.join(self.res, rel)), exist_ok=True)
            shutil.copyfile(paths.resolve_rel(rel, REPO_ROOT), os.path.join(self.res, rel))
        drawio = [p for p in glob.glob(os.path.join(SAMPLE_DIR, "*", "*.drawio")) if "SNP-M-102" in p][0]
        self.sample = os.path.join(self.res, "샘플", "P-102.drawio")
        os.makedirs(os.path.dirname(self.sample))
        shutil.copyfile(drawio, self.sample)
        shutil.copyfile(glob.glob(os.path.join(os.path.dirname(drawio), "*.drawio.svg"))[0], self.sample + ".svg")
        # 작업 루트: 구간 JSON·고정 응답·분석용 그래프·지식 입력(사용자 데이터)
        self.region_path = paths.folder_in(self.work, "regions", os.path.basename(REGION_FILE))
        os.makedirs(os.path.dirname(self.region_path))
        shutil.copyfile(REGION_FILE, self.region_path)
        self.fixed = paths.folder_in(self.work, "fixed-responses", os.path.basename(FIXED_DIR))
        shutil.copytree(FIXED_DIR, self.fixed)
        gpath = paths.resolve_rel(region["graph_ref"]["graph_file"], self.work)
        os.makedirs(os.path.dirname(gpath))
        with open(gpath, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(GRAPH, fh, ensure_ascii=False, indent=2)
        shutil.copytree(KG_SAMPLE, paths.folder_in(self.work, "knowledge-graph", "SNP-SAMPLE"))
        self.region = region

    def test_flow_1_to_5_with_split_roots(self):
        res_before = _tree(self.res)
        repo_before = {d: _names(paths.folder_in(paths.DEV_WORK_ROOT, d)) for d in ("output", "store")}
        env = _clean_env(HAZOP_RESOURCE_ROOT=self.res, HAZOP_WORK_ROOT=self.work)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.dict(data._script_cache, {}, clear=True):
            self.assertEqual((paths.resource_root(), paths.work_root()), (self.res, self.work))
            store = paths.store_root()
            self.assertEqual(store, paths.folder_in(self.work, "store"))

            # ① 등록 → 추출 → 그래프
            reg = registry.register(self.sample, "p", store_root=store, actor="tester", now=lambda: T,
                                    metadata={"drawing_number": "SNP-M-102", "reason": "패키징 검사"})
            self.assertEqual(reg["outcome"], "registered", reg.get("notes"))
            rows = data.list_registrations()
            self.assertEqual(len(rows), 1)
            out = data.extract_and_graph(rows[0]["path"])
            self.assertTrue(out["extract_dir"].startswith(paths.output_in(self.work, "extract")))
            self.assertTrue(out["graph_dir"].startswith(paths.output_in(self.work, "graph")))
            al = out["extraction"]["coordinate_system"]["svg_alignment"]
            self.assertEqual(al["source"], "registered_derived")
            row = data.list_registrations()[0]
            self.assertTrue(row["extracted"] and row["graphed"])

            # ② 추출 목록·뷰어 HTML(SVG는 작업 루트 안 저장 루트에서)
            names = [e["name"] for e in data.list_extractions()]
            self.assertEqual(names, [row["extract_name"]])
            info = data.viewer_html_for(names[0])
            self.assertIsNone(info["error"])
            self.assertTrue(info["html"].startswith(paths.output_in(self.work, "viewer")))

            # ③ 지식그래프: 작업 루트의 지식 입력으로 빌드 → 화면 데이터·HTML(템플릿·vendor는 패키지 안)
            kdir = os.path.join(paths.folder("knowledge-graph"), "SNP-SAMPLE")
            knowledge = kg_inputs.load_knowledge(os.path.join(kdir, "knowledge_nodes.csv"),
                                                 os.path.join(kdir, "knowledge_links.csv"), "SNP-SAMPLE")
            graphs = kg_screen.load_graphs(paths.output_root("graph"))
            kg = kg_build.build_kg(knowledge, [g for _, g in graphs.values()])
            kg_out = paths.output_root("knowledge-graph")
            kg_build.write_outputs(paths.safe_join(kg_out, paths.safe_name(kg["kg_id"])), knowledge, kg)
            roots = dict(kg_screen.list_kg_roots(kg_out))
            self.assertEqual(sorted(roots), sorted([kg["kg_id"], "kg-p"]))  # kg-p: ① 추출 때 자동 생성(도면 기반)
            _, loaded = kg_build.load_outputs(roots[kg["kg_id"]])
            self.assertEqual(loaded["kg_version"], kg["kg_version"])
            _, graph = next(iter(graphs.values()))
            sdata = kg_screen.screen_data(loaded, graph, kg_screen.load_regions(paths.folder("regions")),
                                          kg_screen.read_candidates(kdir))
            self.assertTrue(sdata["nodes"])
            html = kg_screen.write_html(paths.output_root("viewer", "kg-test.html"), kg_screen.build_html(sdata))
            self.assertTrue(html.startswith(self.work))

            # ④ 분석(고정 응답): 기준 자료는 자원 루트, 구간·그래프·출력은 작업 루트
            self.assertEqual(data.list_regions(), [self.region_path])
            res = api.run_analysis(self.region_path, response_dir=self.fixed, run_id="analysis-pkg")
            self.assertEqual(res["status"], "passed", res["blockers"])
            self.assertEqual(res["run_dir"], paths.output_in(self.work, "analysis", self.region["region_id"], "analysis-pkg"))
            c = res["doc"]["validation"]["counts"]
            self.assertEqual((c["candidates"], c["scenarios"], c["risk_proposed"],
                              c["design_improvement_candidates"]), (44, 14, 6, 11))
            self.assertEqual(data.list_runs(self.region["region_id"]), [res["run_dir"]])
            self.assertEqual(data.current_graph(self.region)["graph_version"], res["doc"]["graph_ref"]["graph_version"])
            self.assertEqual(len(data.candidate_rows(res["doc"])), 44)

            # ④ 음성: 자원 루트에 지침서만 있고 기준 자료 4종이 없으면 저장소 자료로 대체하지 않고 입력 오류로 멈춘다
            #   (run.load_inputs가 resource_root 대신 저장소 루트를 쓰는 회귀를 잡는다)
            partial = os.path.join(self.tmp, "res_guide_only")
            os.makedirs(os.path.dirname(paths.file_in(partial, "guide")))
            shutil.copyfile(paths.file_in(self.res, "guide"), paths.file_in(partial, "guide"))
            with mock.patch.dict(os.environ, {paths.ENV_RESOURCE_ROOT: partial}):
                with self.assertRaises(run_mod.InputError) as cm:
                    api.run_analysis(self.region_path, response_dir=self.fixed, run_id="analysis-noresource")
            self.assertIn("candidate_catalog 파일 없음", str(cm.exception))
            self.assertFalse(os.path.exists(paths.output_in(self.work, "analysis", self.region["region_id"], "analysis-noresource")))

            # ⑤ 검토 저장(작업 루트 안 저장 루트) → Excel 출력(작업 루트 output/worksheets)
            run = rv.open_run(res["run_dir"])
            doc = run["doc"]
            cid = "deviation-p86-d12"
            sid, = [s["scenario_id"] for s in doc["scenarios"] if s["candidate_id"] == cid]
            did, = [d["dic_id"] for d in doc["design_improvement_candidates"] if d["candidate_id"] == cid]
            rc = rv.make_risk_confirmation(run, 3, "강도 근거", 2, 2, "빈도 근거", (), "human")
            sdec = rv.scenario_decision(run, sid, "accept", "원안 수용", "검토자A", risk_confirmation=rc, now=T)
            ddec = rv.dic_decision(run, did, "accept", "권고 필요", "검토자A", recommendation="경보 추가 검토", now=T)
            path, saved = rv.save_review(store, run, rv.build_review(run, cid, "검토자A", "요약", [sdec], [ddec]),
                                         now=T)
            self.assertTrue(path.startswith(store))
            self.assertEqual(saved["review_version"], 1)
            ex = export_worksheet(res["run_dir"], store, paths.output_root("worksheets"), now=T)
            files = glob.glob(paths.output_in(self.work, "worksheets", "**", "*.xlsx"), recursive=True)
            self.assertEqual(len(files), 1, ex)

        self.assertEqual(_tree(self.res), res_before)  # 자원 루트는 읽기만
        self.assertEqual({d: _names(paths.folder_in(paths.DEV_WORK_ROOT, d)) for d in ("output", "store")}, repo_before)


# ---------------------------------------------------------------- 4) W4 spec·datas 목록(빌드하지 않음)
def _build_package():
    import importlib.util
    spec = importlib.util.spec_from_file_location("hazop_build_package",
                                                  os.path.join(REPO_ROOT, "scripts", "build_package.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BuildSpecTest(unittest.TestCase):
    """scripts/build_package.py가 만드는 datas 목록·spec 원문. 실제 빌드·기동은 W4 evidence(묶인 실행)에서 확인한다."""

    @classmethod
    def setUpClass(cls):
        cls.bp = _build_package()
        cls.datas = cls.bp.datas_list()
        cls.srcs = {s for s, _ in cls.datas}

    def test_datas_cover_runtime_reads(self):
        """코드가 실행 중 읽는 비 Python 파일이 모두 datas에 있다(코드의 경로 상수와 대조)."""
        from hazop.analysis import integrity
        from hazop.viewer import build as viewer_build

        def rel(p):
            return os.path.relpath(p, REPO_ROOT).replace("\\", "/")
        want = {rel(viewer_build.TEMPLATE), rel(kg_screen.TEMPLATE), "/".join(integrity.GUIDE_PARTS)}
        want |= {rel(os.path.join(kg_screen.VENDOR_DIR, f)) for f in ("force-graph.min.js", "LICENSE", "SOURCE.md")}
        want |= {"scripts/%s.py" % n for n in data.SCRIPT_NAMES}
        res = paths.resource_root()
        want |= {paths.rel_or_abs(paths.resolve_rel(v, res), res) for v in data.read_json(REGION_FILE)["inputs"].values()}  # 기준 자료 4종(옛 경로도 별칭으로 묶음 파일)
        self.assertEqual(want - self.srcs, set())
        for src, dest in self.datas:  # 묶음 안에서도 저장소와 같은 상대 위치
            self.assertEqual(dest, os.path.dirname(src), src)
            self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, src)), src)

    def test_datas_scope(self):
        """저장소에만 있는 자료(샘플 도면·표본)는 넣지 않고(D5안), .py는 화면이 읽는 세 스크립트뿐, 데이터는 기준 4종 폴더만."""
        self.assertFalse([s for s in self.srcs if any(s.startswith(d + "/") for d in self.bp.EXCLUDED_DIRS)])
        self.assertEqual(sorted(s for s in self.srcs if s.endswith(".py")),
                         ["scripts/build_graph.py", "scripts/extract_drawio.py", "scripts/extract_pdf.py"])
        data = [s for s in self.srcs if not s.startswith(("hazop/", "scripts/")) and s != paths.file_rel("guide")]
        self.assertTrue(data)
        self.assertEqual({n for n, f in paths.FOLDERS.items()
                          if f.root == "resource" and any(s.startswith(paths.folder_rel(n) + "/") for s in data)},
                         {"deviations", "risk-criteria", "patterns", "symbols", "icons"})
        self.assertFalse([s for s in self.srcs if "__pycache__" in s])

    def test_spec_text(self):
        import ast
        for with_check in (False, True):
            text = self.bp.spec_text(with_check=with_check)
            ast.parse(text)
            self.assertFalse([t for t in ("sys.path.insert", "sys.path.append", "collect_submodules") if t in text])  # D11 후속
            self.assertIn("HAZOP_MODULES = %r" % self.bp.hazop_modules(), text)
            self.assertIn("EXCLUDES = ['anthropic', 'httpx']", text)  # W9(D15): pdfplumber는 묶는다
            self.assertEqual(text.count("'pdfplumber', 'pypdfium2', 'openpyxl', 'networkx']"), 2 if with_check else 1)  # 두 Analysis 모두
            self.assertIn("name='HAZOP', console=False, upx=False", text)
            self.assertIn("scripts/run_app.py", text)
            self.assertEqual("HAZOP-check" in text, with_check)
            self.assertIn("COLLECT(*parts, upx=False, name=%r)" % ("HAZOP-verify" if with_check else "HAZOP"), text)
            # D18: 시험 트리거 표지 훅은 검증용 빌드의 앱 Analysis에만(배포용에는 없음)
            hooks = ["packaging/rthook_applog.py"] + (["packaging/rthook_verify_build.py"] if with_check else [])
            self.assertIn("runtime_hooks=[os.path.join(REPO, h) for h in %r]" % hooks, text)
            self.assertEqual(text.count("rthook_verify_build"), 1 if with_check else 0)
            self.assertEqual(text.count("keep_warn("), 3 if with_check else 2)  # 정의 1 + Analysis별 복사
            ns = {}
            exec(text.split("HAZOP_MODULES =")[0] + "\n".join(
                ln for ln in text.splitlines() if ln.startswith(("REPO =", "DATAS ="))), ns)
            self.assertEqual(ns["REPO"], REPO_ROOT)
            self.assertEqual(len(ns["DATAS"]), len(self.datas))
            for src, dest in ns["DATAS"]:
                self.assertTrue(os.path.isfile(src), src)

    def test_hazop_modules_lists_every_package_module(self):
        """정적 목록은 __init__.py가 있는 폴더의 .py를 모두 담고, 패키지가 아닌 폴더(vendor)는 따라가지 않는다."""
        mods = self.bp.hazop_modules()
        self.assertIn("hazop", mods)
        self.assertIn("hazop.app.startup", mods)
        self.assertIn("hazop.extract.adapters.pdf_vector", mods)
        self.assertFalse([m for m in mods if "vendor" in m or "__init__" in m])
        on_disk = {os.path.relpath(os.path.join(d, f), REPO_ROOT)[:-3].replace(os.sep, ".")
                   for d, _, fs in os.walk(os.path.join(REPO_ROOT, "hazop")) if "__pycache__" not in d
                   and os.path.isfile(os.path.join(d, "__init__.py")) for f in fs if f.endswith(".py")}
        self.assertEqual(set(mods), {m[:-len(".__init__")] if m.endswith(".__init__") else m for m in on_disk})

    def test_write_spec_outside_repo_only(self):
        inside = os.path.join(REPO_ROOT, "build-should-not-exist")
        with self.assertRaises(ValueError):
            self.bp.write_spec(inside)
        self.assertFalse(os.path.exists(inside))
        tmp = tempfile.mkdtemp(prefix="hazop-spec-")
        self.addCleanup(shutil.rmtree, tmp, True)
        spec = self.bp.write_spec(tmp)
        self.assertEqual(os.path.basename(spec), "HAZOP.spec")
        listed = data.read_json(os.path.join(tmp, "datas.json"))
        self.assertEqual([tuple(x) for x in listed["datas"]], self.datas)
        self.assertEqual(listed["excluded_dirs"], [paths.folder_rel(n) for n in ("references", "APR1400", "samples")])

    def test_spec_roundtrip_odd_path(self):
        """한글·공백·작은따옴표·백틱이 든 저장소 경로가 spec(JSON 이스케이프)을 거쳐도 그대로다(Windows는 " 금지)."""
        tmp = tempfile.mkdtemp(prefix="hazop-spec-")
        self.addCleanup(shutil.rmtree, tmp, True)
        root = os.path.join(tmp, "한글 경로 it's `x`")
        for src, _ in self.datas:
            os.makedirs(os.path.join(root, os.path.dirname(src)), exist_ok=True)
            shutil.copyfile(os.path.join(REPO_ROOT, src), os.path.join(root, src))
        text = self.bp.spec_text(root, with_check=True)
        ns = {}
        exec(text.split("HAZOP_MODULES =")[0] + "\n".join(
            ln for ln in text.splitlines() if ln.startswith(("REPO =", "DATAS ="))), ns)
        self.assertEqual(ns["REPO"], root)
        self.assertEqual([os.path.relpath(s, root).replace("\\", "/") for s, _ in ns["DATAS"]],
                         [s for s, _ in self.bp.datas_list(root)])
        self.assertTrue(all(os.path.isfile(s) for s, _ in ns["DATAS"]))

    def test_check_dist(self):
        """배포용 결과에 검증 exe가 있으면 실패, 검증용에는 둘 다 있어야 한다."""
        tmp = tempfile.mkdtemp(prefix="hazop-dist-")
        self.addCleanup(shutil.rmtree, tmp, True)

        def touch(*parts):
            p = os.path.join(tmp, *parts)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").close()
        self.assertTrue(self.bp.check_dist(tmp, False))  # HAZOP.exe 없음
        touch("dist", "HAZOP", "HAZOP.exe")
        self.assertEqual(self.bp.check_dist(tmp, False), [])
        touch("dist", "HAZOP", "HAZOP-check.exe")
        self.assertTrue(any("검증 전용" in p for p in self.bp.check_dist(tmp, False)))
        touch("dist", "HAZOP-verify", "HAZOP.exe")
        self.assertTrue(any("HAZOP-check" in p for p in self.bp.check_dist(tmp, True)))
        touch("dist", "HAZOP-verify", "HAZOP-check.exe")
        self.assertEqual(self.bp.check_dist(tmp, True), [])

    # ---- D10: PATH 통제, Qt OpenSSL 플러그인 제외, 바이너리 검사, 인터프리터 확인(빌드 없이)
    VENV, BASE, WIN = r"C:\v\venv", r"C:\py\Python312", r"C:\Windows"
    JDK, GIT = r"C:\Users\u\Java\jdk\bin", r"C:\Program Files\Git\mingw64\bin"

    def _tmp(self):
        tmp = tempfile.mkdtemp(prefix="hazop-d10-")
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp

    def test_build_path_dirs_and_roots(self):
        dirs = self.bp.build_path_dirs(exe=self.VENV + r"\Scripts\python.exe", base=self.BASE, windir=self.WIN)
        self.assertEqual([os.path.normcase(d) for d in dirs],
                         [os.path.normcase(d) for d in (self.VENV + r"\Scripts", self.BASE, self.BASE + r"\DLLs",
                                                        self.WIN + r"\System32")])
        # 기본값은 실행 중인 인터프리터(sys.executable·sys.base_prefix·sys.prefix)에서 고른다
        dflt = self.bp.build_path_dirs()
        self.assertEqual(dflt[:3], [os.path.dirname(os.path.abspath(sys.executable)), sys.base_prefix,
                                    os.path.join(sys.base_prefix, "DLLs")])
        self.assertEqual(os.path.normcase(dflt[3]), os.path.normcase(os.path.join(self.bp.windows_dir(), "System32")))
        # 허용 루트는 venv·기반 CPython 둘뿐(Windows 폴더 제외)
        self.assertEqual(self.bp.allowed_roots(self.VENV, self.BASE), [self.VENV, self.BASE])
        self.assertEqual(self.bp.allowed_roots(), [sys.prefix, sys.base_prefix])

    def test_build_replaces_path(self):
        """PyInstaller 자식 프로세스의 PATH는 통제 목록뿐이다. Windows의 os.environ은 키를 대문자로 바꾸므로, 일반
        dict로 바꿔 끼워 'Path'·'PATH'·'path' 표기가 모두 지워지는지 본다. 다른 환경변수는 그대로다."""
        tmp = self._tmp()
        seen = {}

        def fake_run(cmd, **kw):
            seen.update(kw["env"])
            return mock.Mock(returncode=0)
        dirs = self.bp.build_path_dirs(base=self.BASE, windir=self.WIN)
        fake_env = {"Path": self.JDK, "PATH": self.GIT, "path": self.JDK, "HAZOP_TEST_MARKER": "1"}
        with mock.patch.object(self.bp.os, "environ", fake_env), \
                mock.patch.object(self.bp.subprocess, "run", side_effect=fake_run):
            self.assertEqual(self.bp.build(os.path.join(tmp, "HAZOP.spec"), tmp, dirs), 0)
        self.assertEqual([k for k in seen if k.upper() == "PATH"], ["PATH"])
        self.assertEqual(seen["PATH"].split(os.pathsep), dirs)
        self.assertNotIn("jdk", seen["PATH"].lower())
        self.assertNotIn("git", seen["PATH"].lower())
        self.assertEqual(seen.get("HAZOP_TEST_MARKER"), "1")
        with open(os.path.join(tmp, "build.log"), encoding="utf-8") as fh:
            self.assertIn("PATH: " + seen["PATH"], fh.read())

    def test_spec_drops_openssl_tls_plugin(self):
        """spec이 Analysis마다 build_package.drop_binaries(사후 검사와 같은 TLS 규칙)를 binaries·datas에 적용하고,
        이 함수는 Qt OpenSSL TLS 플러그인을 빼고 Schannel·cert-only 플러그인은 남긴다."""
        import ast
        for with_check in (False, True):
            text = self.bp.spec_text(with_check=with_check)
            ast.parse(text)
            self.assertIn("drop_binaries = build_package.drop_binaries", text)
            self.assertNotIn("sys.path.insert(0, os.path.join(REPO, 'scripts'))", text)  # D11 후속: 경로 지정 로딩
            self.assertIn("a.binaries = drop_binaries(a.binaries)", text)
            self.assertIn("a.datas = drop_binaries(a.datas)", text)
            self.assertEqual("c.binaries = drop_binaries(c.binaries)" in text, with_check)
            self.assertEqual("c.datas = drop_binaries(c.datas)" in text, with_check)
        kept = self.bp.drop_binaries([(r"PySide6\plugins\tls\qopensslbackend.dll", "x", "BINARY"),
                                      ("PySide6/plugins/tls/QOpenSSLBackend.DLL", "x", "BINARY"),
                                      (r"PySide6\plugins\tls\qschannelbackend.dll", "x", "BINARY"),
                                      (r"PySide6\plugins\tls\qcertonlybackend.dll", "x", "BINARY")])
        self.assertEqual([k[0] for k in kept], [r"PySide6\plugins\tls\qschannelbackend.dll",
                                                r"PySide6\plugins\tls\qcertonlybackend.dll"])

    def test_tls_plugin_renamed_rejected(self):
        """TLS 플러그인을 다른 이름으로 수집해도 걸린다: plugins/tls/ 아래 허용 목록 밖 이름, 출처가 plugins/tls/의 허용 목록
        밖 파일, 출처 이름이 qopensslbackend.dll인 경우. spec 필터(drop_binaries)와 사후 검사(forbidden_entries·files) 모두."""
        tls = self.VENV + r"\Lib\site-packages\PySide6\plugins\tls"
        bad = [("PySide6/plugins/tls/renamed.dll", tls + r"\qopensslbackend.dll", "BINARY"),
               ("PySide6/plugins/tls/renamed.dll", self.VENV + r"\other\foo.dll", "BINARY"),
               ("PySide6/x.dll", tls + r"\qopensslbackend.dll", "BINARY"),
               ("PySide6/y.dll", tls + r"\renamed.dll", "BINARY"),
               ("PySide6/z.bin", self.VENV + r"\elsewhere\qopensslbackend.dll", "DATA")]
        good = [("PySide6/x.dll", tls + r"\qschannelbackend.dll", "BINARY"),
                (r"PySide6\plugins\tls\qcertonlybackend.dll", tls + r"\qcertonlybackend.dll", "BINARY")]
        self.assertEqual(self.bp.drop_binaries(bad + good), good)
        self.assertEqual(self.bp.forbidden_entries(bad + good), bad)
        dist = os.path.join(self._tmp(), "HAZOP")
        d = os.path.join(dist, "_internal", "PySide6", "plugins", "tls")
        os.makedirs(d)
        for f in TLS_OK + ("renamed.dll",):
            open(os.path.join(d, f), "wb").close()
        self.assertEqual(self.bp.forbidden_files(dist), ["_internal/PySide6/plugins/tls/renamed.dll"])

    def test_alias_short_name(self):
        """출처가 8.3 단축명이어도 긴 파일명으로 이름 거부 목록·TLS 규칙을 적용한다(볼륨에 8.3 이름이 없으면 건너뜀)."""
        import ctypes
        d = os.path.join(self._tmp(), "longfolder-name-for-alias")
        os.makedirs(d)
        out = {}
        for f in ("libssl-3-x64.dll", "qopensslbackend.dll"):
            full = os.path.join(d, f)
            open(full, "wb").close()
            buf = ctypes.create_unicode_buffer(32768)
            n = ctypes.windll.kernel32.GetShortPathNameW(full, buf, 32768)
            if not n or os.path.basename(buf.value).lower() == f:
                self.skipTest("8.3 단축명을 만들 수 없는 볼륨")
            out[f] = buf.value
        self.assertTrue(self.bp.FORBIDDEN_NAME.match(os.path.basename(self.bp.long_real(out["libssl-3-x64.dll"]))))
        toc = [("x.dll", out["libssl-3-x64.dll"], "BINARY"), ("y.dll", out["qopensslbackend.dll"], "BINARY")]
        self.assertEqual(self.bp.forbidden_entries(toc), toc)
        self.assertEqual(self.bp.drop_binaries(toc), toc[:1])  # spec 필터는 TLS 규칙만

    def _junction(self, link, target):
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
        if r.returncode != 0 or not os.path.isdir(link):
            self.skipTest("junction을 만들 수 없음")

    def test_alias_junction(self):
        """junction 별칭: venv 별칭 경로의 출처·sys.prefix는 허용하고, 별칭 너머 plugins/tls/의 다른 이름 파일은 걸린다."""
        tmp = self._tmp()
        real_venv = os.path.join(tmp, "real-venv")
        tls = os.path.join(real_venv, "Lib", "site-packages", "PySide6", "plugins", "tls")
        os.makedirs(tls)
        open(os.path.join(tls, "renamed.dll"), "wb").close()
        open(os.path.join(real_venv, "a.dll"), "wb").close()
        alias = os.path.join(tmp, "alias-venv")
        self._junction(alias, real_venv)
        work = os.path.join(tmp, "build")
        self.assertEqual(self.bp.foreign_binaries([("a.dll", os.path.join(alias, "a.dll"), "BINARY")],
                                                  [real_venv], work), [])
        self.assertEqual(self.bp.foreign_binaries([("a.dll", os.path.join(real_venv, "a.dll"), "BINARY")],
                                                  [alias], work), [])
        ok = dict(base=self.BASE, version=(3, 12, 10), impl="CPython")
        self.assertEqual(self.bp.python_problems(prefix=alias, venv_dir=real_venv, **ok), [])
        self.assertEqual(self.bp.python_problems(prefix=real_venv, venv_dir=alias, **ok), [])
        tls_alias = os.path.join(tmp, "plain-folder")
        self._junction(tls_alias, tls)
        entry = ("PySide6/foo.dll", os.path.join(tls_alias, "renamed.dll"), "BINARY")
        self.assertTrue(self.bp.tls_rejected(entry[0], entry[1]))
        self.assertEqual(self.bp.drop_binaries([entry]), [])

    def _toc(self, tmp):
        """(작업 폴더, 통과 항목, 실패 항목)."""
        work = os.path.join(tmp, "build")
        good = [
            ("HAZOP.exe", os.path.join(work, "HAZOP", "HAZOP.exe"), "EXECUTABLE"),
            ("PySide6\\Qt6Core.dll", self.VENV + r"\Lib\site-packages\PySide6\Qt6Core.dll", "BINARY"),
            ("PySide6\\Qt6Gui.dll", self.VENV.upper() + r"\LIB\site-packages\PySide6\Qt6Gui.dll", "BINARY"),  # 대소문자
            ("libssl-3.dll", self.BASE + r"\DLLs\libssl-3.dll", "BINARY"),
            ("_ssl.pyd", self.BASE + r"\DLLs\_ssl.pyd", "EXTENSION"),
            ("PySide6\\plugins\\tls\\qschannelbackend.dll",
             self.VENV + r"\Lib\site-packages\PySide6\plugins\tls\qschannelbackend.dll", "BINARY"),
            ("licenses\\README.md", r"D:\snap\licenses\README.md", "DATA"),
            ("PySide6\\lib\\a.so", "a.so.1", "SYMLINK"),  # 묶음 안 링크
        ]
        bad = [
            ("x.dll", self.WIN + r"\System32\x.dll", "BINARY"),  # Windows 폴더는 허용 루트가 아니다
            ("ucrtbase.dll", self.JDK + r"\ucrtbase.dll", "BINARY"),
            ("libssl-3-x64.dll", self.GIT + r"\libssl-3-x64.dll", "BINARY"),
            ("y.pyd", r"D:\elsewhere\y.pyd", "EXTENSION"),
            ("z.dll", r"D:\elsewhere\z.dll", "DATA"),  # 종류가 DATA여도 이름이 바이너리
            ("payload.bin", r"D:\outside\evil.dll", "DATA"),  # 이름을 바꾼 DATA: 출처 확장자로 검사
            ("rel.dll", r"Lib\site-packages\rel.dll", "BINARY"),  # 상대 경로 출처는 거부
            ("other.exe", r"D:\elsewhere\other.exe", "EXECUTABLE"),  # 만든 exe는 build 안이어야 한다
            ("a.dll", self.VENV + r"-other\a.dll", "BINARY"),  # 접두어만 같은 형제 폴더
            ("PySide6\\b.so", r"..\..\outside.so", "SYMLINK"),  # 묶음 밖을 가리키는 링크
        ]
        return work, good, bad

    def test_foreign_binaries(self):
        work, good, bad = self._toc(self._tmp())
        roots = [self.VENV, self.BASE]
        self.assertEqual(self.bp.foreign_binaries(good, roots, work), [])
        self.assertEqual([b[0] for b in self.bp.foreign_binaries(good + bad, roots, work)], [b[0] for b in bad])

    def test_forbidden_names(self):
        """출처가 허용 루트 안이어도 이름 거부 목록·제외 플러그인이면 걸린다(묶음 안 이름 또는 출처 파일 이름)."""
        toc = [("ucrtbase.dll", self.VENV + r"\ucrtbase.dll", "BINARY"),
               ("API-MS-WIN-CRT-runtime-l1-1-0.dll", self.BASE + r"\api-ms-win-crt-runtime-l1-1-0.dll", "BINARY"),
               ("libcrypto-3-x64.dll", self.BASE + r"\libcrypto-3-x64.dll", "BINARY"),
               ("renamed.dll", self.BASE + r"\libssl-3-x64.dll", "BINARY"),
               ("PySide6\\plugins\\tls\\qopensslbackend.dll",
                self.VENV + r"\Lib\site-packages\PySide6\plugins\tls\qopensslbackend.dll", "BINARY"),
               ("libssl-3.dll", self.BASE + r"\DLLs\libssl-3.dll", "BINARY"),
               ("PySide6\\plugins\\tls\\qschannelbackend.dll", self.VENV + r"\q.dll", "BINARY")]
        self.assertEqual([t[0] for t in self.bp.forbidden_entries(toc)], [t[0] for t in toc[:5]])
        dist = os.path.join(self._tmp(), "HAZOP")
        for rel in ("HAZOP.exe", "_internal/libssl-3.dll", "_internal/PySide6/plugins/tls/qschannelbackend.dll"):
            os.makedirs(os.path.dirname(os.path.join(dist, rel)), exist_ok=True)
            open(os.path.join(dist, rel), "wb").close()
        self.assertEqual(self.bp.forbidden_files(dist), [])
        for rel in ("_internal/ucrtbase.dll", "_internal/PySide6/plugins/tls/qopensslbackend.dll"):
            os.makedirs(os.path.dirname(os.path.join(dist, rel)), exist_ok=True)
            open(os.path.join(dist, rel), "wb").close()
        self.assertEqual(self.bp.forbidden_files(dist),
                         ["_internal/PySide6/plugins/tls/qopensslbackend.dll", "_internal/ucrtbase.dll"])

    def _write_toc(self, out, text):
        path = self.bp.collect_toc_path(out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.makedirs(self.bp.dist_dir(out), exist_ok=True)
        return path

    def test_read_toc_rejects_malformed(self):
        """빈 TOC·형식이 틀린 TOC는 ValueError, check_sources는 형식 오류를 문제로 돌려준다."""
        out = self._tmp()
        exe = ("HAZOP.exe", r"C:\b\HAZOP.exe", "EXECUTABLE")
        for text in ("", "(((", "[]", "([],)", repr([exe]), repr(([exe], [])), repr(([exe, ("a", "b")],)),
                     repr(([exe, ("a", 1, "BINARY")],)), repr(([("x.dll", r"C:\v\x.dll", "BINARY")],)),
                     repr(([("HAZOP.exe", r"C:\b\HAZOP.exe", "BINARY")],))):
            path = self._write_toc(out, text)
            with self.assertRaises(ValueError, msg=text):
                self.bp.read_toc(path)
            self.assertTrue(any("형식 오류" in p for p in self.bp.check_sources(out, roots=[self.VENV])), text)
        path = self._write_toc(out, repr(([exe],)))
        self.assertEqual(self.bp.read_toc(path), [exe])

    def test_check_sources(self):
        out = self._tmp()
        roots = [self.VENV, self.BASE]
        self.assertTrue(any("TOC 없음" in p for p in self.bp.check_sources(out, roots=roots)))
        _, good, bad = self._toc(out)
        self._write_toc(out, repr((good,)))
        self.assertEqual(self.bp.check_sources(out, roots=roots), [])
        self._write_toc(out, repr((good + bad,)))
        probs = self.bp.check_sources(out, roots=roots)
        self.assertEqual(sum("허용 루트 밖" in p for p in probs), len(bad))
        self.assertTrue(any("거부 목록" in p and "ucrtbase.dll" in p for p in probs))
        # TOC가 깨끗해도 결과 폴더에 제외 플러그인이 있으면 실패
        self._write_toc(out, repr((good,)))
        p = os.path.join(self.bp.dist_dir(out), "_internal", "PySide6", "plugins", "tls", "qopensslbackend.dll")
        os.makedirs(os.path.dirname(p))
        open(p, "wb").close()
        self.assertTrue(any("결과 폴더" in x for x in self.bp.check_sources(out, roots=roots)))
        os.makedirs(self.bp.dist_dir(out, True))
        self.assertEqual(self.bp.check_sources(out, with_check=True, roots=roots), [])  # 검증용 폴더는 따로

    # ---- D13(W8-B): GPL 전용 Qt 모듈 제외(빌드 없이)
    SP = VENV + r"\Lib\site-packages\PySide6"
    QT_EXCLUDED = [  # (묶음 안 이름, 기대 모듈) — 대소문자·구분자 섞음
        (r"PySide6\Qt6Charts.dll", "Charts"), ("PySide6/qt6chartsqml.DLL", "Charts"),
        (r"PySide6\qml\QtCharts\qmldir", "Charts"), (r"PySide6\QtCharts.pyd", "Charts"),
        (r"PySide6\Qt6DataVisualizationQml.dll", "DataVisualization"),
        (r"PySide6\qml\QtDataVisualization\designer\x.qml", "DataVisualization"),
        (r"PySide6\Qt6Graphs2DImpl.dll", "Graphs"), (r"PySide6\Qt6GraphsWidgets.dll", "Graphs"),
        (r"PySide6\qml\QtGraphs\qmldir", "Graphs"),
        (r"PySide6\Qt6Quick3DPhysics.dll", "Quick3D"), (r"PySide6\Qt6Quick3DXr.dll", "Quick3D"),
        (r"PySide6\Qt6Quick3DSpatialAudio.dll", "Quick3D"), (r"PySide6\qml\QtQuick3D\Physics\qmldir", "Quick3D"),
        (r"PySide6\Qt6SpatialAudio.dll", "Quick3D"),  # Qt6Quick3DSpatialAudio만 import하던 DLL(총괄 판정)
        (r"PySide6\plugins\qmltooling\qmldbg_quick3dprofiler.dll", "Quick3D"),
        (r"PySide6\plugins\assetimporters\assimp.dll", "Quick3D"),
        (r"PySide6\Qt6VirtualKeyboardSettings.dll", "VirtualKeyboard"),
        (r"PySide6\qml\QtQuick\VirtualKeyboard\Plugins\Hangul\x.dll", "VirtualKeyboard"),
        (r"PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll", "VirtualKeyboard"),
        (r"PySide6\Qt6QuickTimelineBlendTrees.dll", "QuickTimeline"), (r"PySide6\qml\QtQuick\Timeline\qmldir", "QuickTimeline"),
        (r"PySide6\Qt6ShaderTools.dll", "ShaderTools"),
        (r"PySide6\qml\Qt5Compat\GraphicalEffects\private\qtgraphicaleffectsprivateplugin.dll",
         "Qt5Compat.GraphicalEffects(ShaderTools 의존)"),
    ]
    QT_KEPT = [r"PySide6\Qt6Quick.dll", r"PySide6\Qt6Qml.dll", r"PySide6\Qt6QuickWidgets.dll",
               r"PySide6\Qt6WebEngineCore.dll", r"PySide6\Qt6WebEngineWidgets.dll", r"PySide6\Qt63DCore.dll",
               r"PySide6\Qt6QuickControls2.dll", r"PySide6\qml\QtQuick\Controls\qmldir",
               r"PySide6\qml\QtQuick\Templates\qmldir", r"PySide6\qml\Qt3D\Core\qmldir", r"PySide6\qml\QtWebEngine\qmldir",
               r"PySide6\plugins\qmltooling\qmldbg_quickprofiler.dll", r"PySide6\plugins\platforms\qwindows.dll",
               r"PySide6\translations\qtbase_ko.qm", r"licenses\qt\GPL-3.0.txt", "Qt6Charts-notes.txt",
               r"PySide6\Qt6OpenGLWidgets.dll", r"PySide6\opengl32sw.dll", r"PySide6\Qt6Multimedia.dll",
               r"PySide6\qml\Qt5Compat\Core5Compat\qmldir"]

    def test_qt_module_exclusion_rules(self):
        """제외 대상 모듈(D13)은 spec 필터가 빼고 사후 검사(TOC·결과 폴더)가 잡는다. 앱·WebEngine이 링크하는
        Qt6Quick·Qt6Qml·Qt6QuickWidgets와 Qt3D·Quick Controls 등은 남는다. 이름을 바꿔도 출처로 잡는다."""
        bad = [(n, self.SP + "\\" + n.replace("/", "\\").split("\\", 1)[1], "BINARY") for n, _ in self.QT_EXCLUDED]
        good = [(n, self.SP + "\\" + n.split("\\", 1)[1] if n.startswith("PySide6") else r"D:\snap" + "\\" + n, "BINARY")
                for n in self.QT_KEPT]
        renamed = [("PySide6/x.dll", self.SP + r"\Qt6Charts.dll", "BINARY"),
                   ("payload.bin", self.SP + r"\qml\QtQuick3D\Helpers\y.dll", "DATA")]
        roots = [self.VENV]
        self.assertEqual([self.bp.qt_module_rejected(n, s, roots) for n, s, _ in bad], [m for _, m in self.QT_EXCLUDED])
        self.assertEqual(self.bp.drop_binaries(bad + good + renamed, roots), good)
        self.assertEqual(self.bp.excluded_module_entries(good, roots), [])
        self.assertEqual([x[0] for x in self.bp.excluded_module_entries(bad + renamed, roots)],
                         [b[0] for b in bad + renamed])
        dist = os.path.join(self._tmp(), "HAZOP")
        for rel in ("HAZOP.exe", "_internal/PySide6/Qt6Quick.dll", "_internal/PySide6/qml/QtQuick/Controls/qmldir"):
            os.makedirs(os.path.dirname(os.path.join(dist, rel)), exist_ok=True)
            open(os.path.join(dist, rel), "wb").close()
        self.assertEqual(self.bp.excluded_module_files(dist), [])
        for rel in ("_internal/PySide6/qml/QtCharts/qmldir", "_internal/PySide6/Qt6ShaderTools.dll"):
            os.makedirs(os.path.dirname(os.path.join(dist, rel)), exist_ok=True)
            open(os.path.join(dist, rel), "wb").close()
        self.assertEqual(self.bp.excluded_module_files(dist),
                         [("_internal/PySide6/Qt6ShaderTools.dll", "ShaderTools"),
                          ("_internal/PySide6/qml/QtCharts/qmldir", "Charts")])
        # PySide6 폴더 밖·다른 하위 폴더로 옮겨진 DLL은 파일 이름(이름 규칙)으로 잡는다. 이동한 플러그인 DLL 포함
        moved = ("HAZOP-extra/qt6quicktimeline.DLL", "_internal/Qt6Charts.dll", "_internal/x/Qt6SpatialAudio.dll",
                 "_internal/y/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
                 "_internal/moved/qtvirtualkeyboardplugin.dll", "_internal/moved/qmldbg_quick3dprofiler.dll",
                 "_internal/moved/assimp.dll", "_internal/moved/QTVKBHANGULPLUGIN.dll")
        # 폴더 규칙은 PySide6 기준 경로에서만, 이름 규칙은 전체 이름만: 아래는 걸리지 않는다
        unrelated = ("_internal/docs/plugins/assetimporters/readme.txt", "_internal/other/qml/QtCharts/qmldir",
                     "_internal/Qt6Charts-custom.dll", "_internal/PySide6/Qt6ChartsExtra.dll",
                     "_internal/PySide6/qml/QtChartsFake/qmldir")
        for rel in moved + unrelated:
            os.makedirs(os.path.dirname(os.path.join(dist, rel)), exist_ok=True)
            open(os.path.join(dist, rel), "wb").close()
        self.assertEqual(sorted(r for r, _ in self.bp.excluded_module_files(dist)),
                         sorted(list(moved) + ["_internal/PySide6/Qt6ShaderTools.dll",
                                               "_internal/PySide6/qml/QtCharts/qmldir"]))

    def test_qt_rules_ignore_absolute_ancestors(self):
        """절대 경로의 상위 폴더 이름으로 판정하지 않는다: 출처가 '…\\qml\\QtCharts\\project\\venv\\PySide6\\Qt6Core.dll'이거나
        출력 폴더가 '…\\qml\\QtCharts' 아래여도 정상 파일은 걸리지 않는다. 접두사만 같은 이름·무관한 경로도 걸리지 않는다."""
        odd_venv = os.path.join(self._tmp(), "qml", "QtCharts", "project", "venv")
        core = (r"PySide6\Qt6Core.dll", os.path.join(odd_venv, "Lib", "site-packages", "PySide6", "Qt6Core.dll"), "BINARY")
        qmldir = (r"PySide6\qml\QtQuick\Controls\qmldir",
                  os.path.join(odd_venv, "Lib", "site-packages", "PySide6", "qml", "QtQuick", "Controls", "qmldir"), "DATA")
        other = [(r"docs\plugins\assetimporters\readme.txt", r"D:\snap\docs\plugins\assetimporters\readme.txt", "DATA"),
                 ("Qt6Charts-custom.dll", self.SP + r"\Qt6Charts-custom.dll", "BINARY"),
                 (r"PySide6\Qt6QuickTimelineX.dll", self.SP + r"\Qt6QuickTimelineX.dll", "BINARY")]
        for roots in ([odd_venv], [self.VENV]):
            self.assertEqual(self.bp.drop_binaries([core, qmldir] + other, roots), [core, qmldir] + other)
            self.assertEqual(self.bp.excluded_module_entries([core, qmldir] + other, roots), [])
        # 허용 루트 안 출처는 PySide6 기준 경로로 폴더 규칙을 적용한다(묶음 안 이름을 바꿔도)
        moved = ("payload.bin", os.path.join(odd_venv, "Lib", "site-packages", "PySide6", "qml", "QtCharts", "x.qml"), "DATA")
        self.assertEqual(self.bp.qt_module_rejected(moved[0], moved[1], [odd_venv]), "Charts")
        self.assertIsNone(self.bp.qt_module_rejected(moved[0], moved[1], [self.VENV]))  # 허용 루트 밖: 상위 이름 무시
        # 출력 폴더가 qml/QtCharts 아래: 정상 묶음은 통과
        out = os.path.join(self._tmp(), "qml", "QtCharts")
        _, good, _ = self._toc(out)
        self._write_toc(out, repr((good,)))
        for rel in ("_internal/PySide6/Qt6Core.dll", "_internal/PySide6/qml/QtQuick/Controls/qmldir"):
            os.makedirs(os.path.dirname(os.path.join(self.bp.dist_dir(out), rel)), exist_ok=True)
            open(os.path.join(self.bp.dist_dir(out), rel), "wb").close()
        self.assertEqual(self.bp.excluded_module_files(self.bp.dist_dir(out)), [])
        self.assertEqual(self.bp.check_sources(out, roots=[self.VENV, self.BASE]), [])

    def test_spec_applies_filter_to_both_analyses(self):
        """생성한 spec을 PyInstaller 없이 모의 실행해, 두 Analysis(앱·검증)의 binaries·datas가 drop_binaries를 거친 뒤
        COLLECT로 간다는 것을 확인한다(spec에서 필터 연결을 지우면 실패)."""
        bad = [(r"PySide6\Qt6Charts.dll", r"C:\x\Qt6Charts.dll", "BINARY"),
               (r"PySide6\qml\QtQuick3D\qmldir", r"C:\x\qmldir", "DATA"),
               (r"PySide6\plugins\tls\qopensslbackend.dll", r"C:\x\qopensslbackend.dll", "BINARY")]
        keep = [(r"PySide6\Qt6Quick.dll", r"C:\x\Qt6Quick.dll", "BINARY"), ("licenses\\README.md", r"C:\x\README.md", "DATA")]
        seen = {}

        class FakeAnalysis:
            def __init__(self, scripts, **kw):
                self.binaries = list(bad + keep)
                self.datas = list(bad + keep)
                self.pure, self.scripts = [], []

        def fake_collect(*parts, **kw):
            seen["parts"] = parts
        hooks = mock.Mock()
        hooks.collect_submodules.return_value = []
        saved_path = list(sys.path)
        self.addCleanup(lambda: sys.modules.pop("build_package", None))
        try:
            for with_check in (False, True):
                ns = {"Analysis": FakeAnalysis, "PYZ": mock.Mock(), "EXE": mock.Mock(side_effect=lambda *a, **k: "exe"),
                      "COLLECT": fake_collect}
                with mock.patch.dict(sys.modules, {"PyInstaller": mock.Mock(), "PyInstaller.utils": mock.Mock(),
                                                   "PyInstaller.utils.hooks": hooks}):
                    exec(compile(self.bp.spec_text(with_check=with_check), "HAZOP.spec", "exec"), ns)
                lists = [x for x in seen["parts"] if isinstance(x, list)]
                self.assertEqual(len(lists), 4 if with_check else 2)
                for lst in lists:
                    self.assertEqual(lst, keep)
        finally:
            sys.path[:] = saved_path

    def test_check_sources_qt_modules(self):
        """제외 대상 모듈이 TOC나 결과 폴더에 있으면 check_sources가 실패하고 main은 rc=3."""
        out = self._tmp()
        roots = [self.VENV, self.BASE]
        _, good, _ = self._toc(out)
        bad = (r"PySide6\Qt6VirtualKeyboard.dll", self.SP + r"\Qt6VirtualKeyboard.dll", "BINARY")
        self._write_toc(out, repr((good + [bad],)))
        probs = self.bp.check_sources(out, roots=roots)
        self.assertEqual([p for p in probs if "제외 대상 Qt 모듈" in p],
                         ["제외 대상 Qt 모듈(VirtualKeyboard)이 TOC에 있음: %s (%s)" % bad[:2]])
        self._write_toc(out, repr((good,)))
        p = os.path.join(self.bp.dist_dir(out), "_internal", "PySide6", "qml", "QtQuick3D", "qmldir")
        os.makedirs(os.path.dirname(p))
        open(p, "wb").close()
        self.assertEqual(self.bp.check_sources(out, roots=roots),
                         ["제외 대상 Qt 모듈(Quick3D)이 결과 폴더에 있음: _internal/PySide6/qml/QtQuick3D/qmldir"])

        # main: 결과 폴더에는 위반 파일이 없고 TOC 위반만 있을 때 rc=3, TOC도 깨끗하면 rc=0(새 출력 폴더)
        out2 = self._tmp()
        _, good, _ = self._toc(out2)
        toc_text = {}

        def fake_build(spec, o):
            self._write_toc(o, toc_text["v"])
            return 0
        with mock.patch.dict(sys.modules, {"PyInstaller": mock.Mock()}), \
                mock.patch.object(self.bp, "build", side_effect=fake_build), \
                mock.patch.object(self.bp, "check_dist", return_value=[]), \
                mock.patch.object(self.bp, "finish_bundle", return_value=[]), \
                mock.patch.object(self.bp, "allowed_roots", return_value=roots), \
                mock.patch.object(self.bp, "python_problems", return_value=[]):
            toc_text["v"] = repr((good + [bad],))
            self.assertEqual(self.bp.main(["--out", out2, "--build"]), 3)
            self.assertEqual(self.bp.dist_files(self.bp.dist_dir(out2)), [])
            self.assertEqual(self.bp.check_sources(out2, roots=roots),
                             ["제외 대상 Qt 모듈(VirtualKeyboard)이 TOC에 있음: %s (%s)" % bad[:2]])
            toc_text["v"] = repr((good,))
            self.assertEqual(self.bp.main(["--out", out2, "--build"]), 0)

    def test_result_folder_unwalked_dirs(self):
        """os.walk가 들어가지 않는 폴더는 검사 실패: is_dir() 오류로 파일 목록에 들어온 폴더(모의), junction 폴더(실제)."""
        dist = os.path.join(self._tmp(), "HAZOP")
        os.makedirs(os.path.join(dist, "_internal", "sub"))
        open(os.path.join(dist, "HAZOP.exe"), "wb").close()
        self.assertEqual([x[2] for x in self.bp.dist_files(dist)], ["HAZOP.exe"])
        real_walk = os.walk

        def isdir_failed_walk(top, onerror=None, **kw):  # Python 3.12 os.walk: is_dir() OSError면 파일로 분류
            if os.path.normcase(top) != os.path.normcase(dist):
                return real_walk(top, onerror=onerror, **kw)
            return iter([(dist, [], ["HAZOP.exe"]), (os.path.join(dist, "_internal"), [], ["sub"])])
        with mock.patch.object(self.bp.os, "walk", side_effect=isdir_failed_walk):
            with self.assertRaises(OSError) as cm:
                self.bp.dist_files(dist)
            self.assertIn("폴더를 탐색하지 못함", str(cm.exception))
        target = os.path.join(self._tmp(), "outside")
        os.makedirs(target)
        open(os.path.join(target, "Qt6Charts.dll"), "wb").close()
        self._junction(os.path.join(dist, "_internal", "linked"), target)
        with self.assertRaises(OSError) as cm:
            self.bp.dist_files(dist)
        self.assertIn("링크 폴더", str(cm.exception))

    def test_result_folder_walk_errors(self):
        """결과 폴더가 없거나 탐색 중 오류(PermissionError 모의)가 나면 검사 실패, main은 rc=3."""
        out = self._tmp()
        roots = [self.VENV, self.BASE]
        _, good, _ = self._toc(out)
        self._write_toc(out, repr((good,)))
        self.assertEqual(self.bp.check_sources(out, roots=roots), [])
        os.rmdir(self.bp.dist_dir(out))
        probs = self.bp.check_sources(out, roots=roots)
        self.assertEqual(len(probs), 1)
        self.assertIn("결과 폴더 탐색 오류", probs[0])
        self.assertIn("결과 폴더 없음", probs[0])
        os.makedirs(self.bp.dist_dir(out))

        real_walk, dist = os.walk, self.bp.dist_dir(out)

        def bad_walk(top, onerror=None, **kw):  # 결과 폴더 탐색만 오류(datas 목록 등 다른 탐색은 그대로)
            if os.path.normcase(os.path.abspath(top)) != os.path.normcase(os.path.abspath(dist)):
                return real_walk(top, onerror=onerror, **kw)
            onerror(PermissionError(13, "액세스 거부(모의)", os.path.join(top, "_internal")))
            return iter([(top, [], ["HAZOP.exe"])])
        with mock.patch.object(self.bp.os, "walk", side_effect=bad_walk):
            with self.assertRaises(PermissionError):
                self.bp.dist_files(self.bp.dist_dir(out))
            probs = self.bp.check_sources(out, roots=roots)
            self.assertEqual(len(probs), 1)
            self.assertIn("결과 폴더 탐색 오류", probs[0])
            self.assertIn("액세스 거부(모의)", probs[0])
            with mock.patch.dict(sys.modules, {"PyInstaller": mock.Mock()}), \
                    mock.patch.object(self.bp, "build", return_value=0), \
                    mock.patch.object(self.bp, "check_dist", return_value=[]), \
                    mock.patch.object(self.bp, "finish_bundle", return_value=[]), \
                    mock.patch.object(self.bp, "allowed_roots", return_value=roots), \
                    mock.patch.object(self.bp, "python_problems", return_value=[]):
                self.assertEqual(self.bp.main(["--out", out, "--build"]), 3)

    def test_qt_exclusion_against_installed_pyside6(self):
        """설치된 PySide6 기준: 제외 규칙마다 실제 파일이 하나 이상 걸리고(이름이 바뀌면 규칙이 헛돈다), 앱이 import하는
        모듈의 DLL(QtWebEngineWidgets·QtWebChannel·QtWidgets 등)에서 PE import를 따라간 의존 DLL은 하나도 걸리지 않는다."""
        try:
            import PySide6
            import pefile
        except ImportError:
            self.skipTest("PySide6·pefile 없음(전용 venv에서 실행)")
        root = os.path.dirname(PySide6.__file__)
        rels = [os.path.relpath(os.path.join(d, f), root).replace("\\", "/")
                for d, _, files in os.walk(root) for f in files]
        lower = {r.lower() for r in rels}
        bases = {}
        for r in lower:
            bases.setdefault(os.path.basename(r), []).append(r)
        excluded_dirs = [x.lower() for _, _, dirs in self.bp.QT_EXCLUDED_MODULES for x in dirs]
        for mod, files, dirs in self.bp.QT_EXCLUDED_MODULES:
            for f in files:  # 이름 규칙의 모든 이름이 설치본에 있고, 다른 모듈 파일과 이름이 겹치지 않는다
                self.assertIn(f.lower(), bases, (mod, f))
                clash = [r for r in bases[f.lower()] if "/" in r and not any(r.startswith(x) for x in excluded_dirs)
                         and not r.startswith(("plugins/platforminputcontexts/", "plugins/qmltooling/"))]
                self.assertEqual(clash, [], (mod, f))
            for x in dirs:  # 폴더 규칙의 모든 폴더가 설치본에 있다
                self.assertTrue(any(r.startswith(x.lower()) for r in lower), (mod, x))

        def imports(name):
            pe = pefile.PE(os.path.join(root, name), fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                                   pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
            out = {e.dll.decode("ascii") for a in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                   for e in getattr(pe, a, [])}
            pe.close()
            return {x for x in out if os.path.isfile(os.path.join(root, x))}  # PySide6 폴더 안 DLL만 따라간다
        todo = ["Qt6WebEngineWidgets.dll", "Qt6WebEngineCore.dll", "Qt6WebChannel.dll", "Qt6Widgets.dll",
                "Qt6Gui.dll", "Qt6Core.dll", "Qt6Network.dll", "QtWebEngineProcess.exe"]
        seen = set()
        while todo:
            n = todo.pop()
            if n.lower() in seen:
                continue
            seen.add(n.lower())
            todo += sorted(imports(n))
        self.assertTrue({"qt6quick.dll", "qt6qml.dll", "qt6quickwidgets.dll"} <= seen)  # WebEngine이 링크(남겨야 함)
        self.assertEqual(sorted(n for n in seen if self.bp.qt_module_rejected("PySide6/" + n, "x")), [])

    def test_python_problems(self):
        venv = r"C:\Users\u\.hazop\venv-py312"
        ok = dict(prefix=venv, base=self.BASE, version=(3, 12, 10), impl="CPython", venv_dir=venv)
        self.assertEqual(self.bp.python_problems(**ok), [])
        self.assertEqual(self.bp.python_problems(**dict(ok, prefix=venv.upper())), [])  # 대소문자 무시
        self.assertTrue(self.bp.python_problems(**dict(ok, prefix=r"C:\other\venv")))
        self.assertTrue(self.bp.python_problems(**dict(ok, base=venv)))  # venv가 아님
        self.assertTrue(self.bp.python_problems(**dict(ok, version=(3, 12, 14))))
        self.assertTrue(self.bp.python_problems(**dict(ok, impl="PyPy")))

    def test_main_exit_codes(self):
        """출처 위반·거부 목록·TOC 형식 오류는 rc=3, 전용 venv가 아니면 빌드 전에 rc=2(--allow-other-python으로 우회)."""
        out = self._tmp()
        _, good, bad = self._toc(out)
        toc_text = {}

        def fake_build(spec, o):
            self._write_toc(o, toc_text["v"])
            return 0
        built = mock.Mock(side_effect=fake_build)
        common = [mock.patch.dict(sys.modules, {"PyInstaller": mock.Mock()}),
                  mock.patch.object(self.bp, "build", built),
                  mock.patch.object(self.bp, "check_dist", return_value=[]),
                  mock.patch.object(self.bp, "allowed_roots", return_value=[self.VENV, self.BASE]),
                  mock.patch.object(self.bp, "finish_bundle", return_value=[])]
        with common[0], common[1], common[2], common[3], common[4], \
                mock.patch.object(self.bp, "python_problems", return_value=[]):
            for text, rc in ((repr((good + bad,)), 3), (repr((good,)), 0), ("([],)", 3), ("", 3)):
                toc_text["v"] = text
                self.assertEqual(self.bp.main(["--out", out, "--build"]), rc, text)
        built.reset_mock()
        toc_text["v"] = repr((good,))
        with common[0], common[1], common[2], common[3], common[4], \
                mock.patch.object(self.bp, "python_problems", return_value=["전용 venv가 아님"]):
            self.assertEqual(self.bp.main(["--out", out, "--build"]), 2)
            built.assert_not_called()
            self.assertEqual(self.bp.main(["--out", out, "--build", "--allow-other-python"]), 0)
            built.assert_called_once()


# ---------------------------------------------------------------- W6 제3자 고지(licenses/, D9)
LICENSES_DIR = os.path.join(REPO_ROOT, "licenses")
# 기준 목록: 반드시 있어야 하는 원문 파일(licenses/ 상대 경로) → 라이선스 식별자. README 표의 행과 파일을 함께 지워도
# 이 기준과 대조해 실패한다. force-graph 의존성은 W1 §2 목록(하위 의존성 포함) 전부.
_FG_MIT = ("accessor-fn", "bezier-js", "canvas-color-tracker", "d3-binarytree", "d3-force-3d", "d3-octree",
           "float-tooltip", "force-graph", "index-array-by", "kapsule", "lodash-es", "preact", "tinycolor2",
           "tweenjs-tween.js")
_FG_ISC = ("d3-array", "d3-color", "d3-dispatch", "d3-drag", "d3-format", "d3-interpolate", "d3-quadtree", "d3-scale",
           "d3-selection", "d3-time", "d3-time-format", "d3-timer", "d3-transition", "d3-zoom", "internmap")
# W9-B(D17): LICENSE-APACHE·LICENSE-MIT 두 원문을 함께 둔 crates.io 크레이트(cryptography `_rust.pyd`, SBOM 기준)
_CRATES_MIT_APACHE = (
    "base64-0.22.1", "bitflags-2.11.1", "cc-1.2.61", "cfg-if-1.0.4", "find-msvc-tools-0.1.9",
    "foreign-types-shared-0.1.1", "foreign-types-0.3.2", "heck-0.5.0", "itoa-1.0.18", "libc-0.2.186",
    "once_cell-1.21.4", "openssl-macros-0.1.1", "pkg-config-0.3.33", "portable-atomic-1.13.1", "proc-macro2-1.0.106",
    "pyo3-build-config-0.28.3", "pyo3-ffi-0.28.3", "pyo3-macros-backend-0.28.3", "pyo3-macros-0.28.3", "pyo3-0.28.3",
    "quote-1.0.45", "shlex-1.3.0", "syn-2.0.117", "unicode-ident-1.0.24", "vcpkg-0.2.15")
REQUIRED_NOTICES = dict(
    [("force-graph/%s-%s" % (n, "LICENSE.md" if n == "bezier-js" else "LICENSE"), "MIT") for n in _FG_MIT]
    + [("force-graph/%s-LICENSE" % n, "ISC") for n in _FG_ISC]
    + [("force-graph/d3-ease-LICENSE", "BSD-3-Clause"),
       ("force-graph/d3-scale-chromatic-LICENSE", "ISC AND Apache-2.0"),
       ("force-graph/Apache-2.0.txt", "Apache-2.0"),
       ("tabler-icons/LICENSE", "MIT"),
       ("qt/LGPL-3.0.txt", "LGPL-3.0-only"),
       ("qt/GPL-3.0.txt", "GPL-3.0-only"),
       ("qt/LicenseRef-Qt-Commercial.txt", "LicenseRef-Qt-Commercial"),
       ("python/CPython-LICENSE.txt", "PSF-2.0"),
       ("python/CPython-license-acknowledgements.rst.txt", "구성요소별(파일 안)"),
       ("pyinstaller/COPYING.txt", "GPL-2.0-or-later WITH Bootloader-exception"),
       ("python/networkx-LICENSE.txt", "BSD-3-Clause"),
       ("python/openpyxl-LICENCE.rst", "MIT"),
       ("python/et_xmlfile-LICENCE.rst", "MIT"),
       ("python/et_xmlfile-LICENCE.python", "PSF-2.0")]
    # W9(D15): 내려받은 고지 원문(Qt·PDFium·WebEngine·opengl32sw·VC++ 재배포·liblzma)과 PDF 어댑터 휠의 고지
    + [("qt/GPL-2.0.txt", "GPL-2.0-only"),
       ("qt/pdfium-LICENSE", "BSD-3-Clause·Apache-2.0(파일 안)"),
       ("qt/qtwebengine-licensing.html", "구성요소별(파일 안)"),
       ("qt/opengl32sw/mesa-11.2.2-license.html", "MIT(파일 안, 구성요소별)"),
       ("qt/opengl32sw/llvm-3.6.0-LICENSE.TXT", "NCSA"),
       ("msvc/vs2022-redistribution.html", "Microsoft 재배포 조건 안내(라이선스 본문 아님)"),
       ("python/liblzma-xz-5.2.5-COPYING", "퍼블릭 도메인(liblzma, 파일 안)"),
       ("qt/third-party/qtimageformats-libtiff-COPYRIGHT", "libtiff"),
       ("qt/third-party/qtimageformats-libwebp-COPYING", "BSD-3-Clause")]
    + [("qt/third-party/LICENSES/%s.txt" % n, n) for n in (
        "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0", "FTL", "IJG", "Libpng", "libpng-2.0", "MIT",
        "MIT-open-group", "MPL-2.0", "Zlib", "LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception",
        "LicenseRef-ICC-License", "LicenseRef-Lcs-Telegraphics", "LicenseRef-SHA1-Public-Domain")]
    + [("qt/third-party/attribution/%s.qt_attribution.json" % n, lic) for n, lic in (
        ("qtbase-D3D12MemoryAllocator", "MIT"), ("qtbase-VulkanMemoryAllocator", "MIT"),
        ("qtbase-blake2", "CC0-1.0 OR Apache-2.0"), ("qtbase-double-conversion", "BSD-3-Clause"),
        ("qtbase-easing", "BSD-3-Clause"), ("qtbase-emoji-segmenter", "Apache-2.0"),
        ("qtbase-freetype", "FTL OR GPL-2.0-only; Zlib; MIT; MIT AND MIT-open-group"), ("qtbase-harfbuzz-ng", "MIT"),
        ("qtbase-icc", "LicenseRef-ICC-License"), ("qtbase-libjpeg", "IJG AND BSD-3-Clause"),
        ("qtbase-libpng", "Libpng AND libpng-2.0"), ("qtbase-libpsl", "MPL-2.0; BSD-3-Clause"),
        ("qtbase-md4", "CC0-1.0"), ("qtbase-md4c", "MIT"), ("qtbase-md5", "CC0-1.0"),
        ("qtbase-pcre2", "LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception; BSD-2-Clause"),
        ("qtbase-rfc6234", "BSD-3-Clause"), ("qtbase-sha1", "LicenseRef-SHA1-Public-Domain"),
        ("qtbase-sha3", "BSD-2-Clause; CC0-1.0"), ("qtbase-siphash", "CC0-1.0"), ("qtbase-tinycbor", "MIT"),
        ("qtbase-wintab", "LicenseRef-Lcs-Telegraphics"), ("qtbase-zlib", "Zlib"),
        ("qtimageformats-libtiff", "libtiff"), ("qtimageformats-libwebp", "BSD-3-Clause"))]
    + [("python/%s" % f, lic) for f, lic in (
        ("pdfplumber-LICENSE.txt", "MIT"), ("pdfminer.six-LICENSE", "MIT"), ("pillow-LICENSE", "MIT-CMU"),
        ("charset_normalizer-LICENSE", "MIT"), ("cryptography-LICENSE", "Apache-2.0 OR BSD-3-Clause"),
        ("cryptography-LICENSE.APACHE", "Apache-2.0"), ("cryptography-LICENSE.BSD", "BSD-3-Clause"),
        ("cffi-LICENSE", "MIT"), ("cffi-AUTHORS", "MIT(저작자 목록)"), ("pycparser-LICENSE", "BSD-3-Clause"),
        ("pypdfium2/LICENSES/Apache-2.0.txt", "Apache-2.0"), ("pypdfium2/LICENSES/BSD-3-Clause.txt", "BSD-3-Clause"),
        ("pypdfium2/LICENSES/CC-BY-4.0.txt", "CC-BY-4.0"))]
    + [("python/pypdfium2/BUILD_LICENSES/%s" % f, lic) for f, lic in (
        ("abseil.txt", "Apache-2.0"), ("agg23.txt", "AGG 허가 문구(파일 안)"), ("fast_float.txt", "MIT"),
        ("freetype.txt", "FTL(파일 안)"), ("icu.txt", "Unicode-3.0(파일 안)"), ("lcms.txt", "MIT"),
        ("libjpeg_turbo.ijg", "IJG"), ("libjpeg_turbo.md", "IJG·BSD-3-Clause·Zlib(파일 안)"),
        ("libopenjpeg.txt", "BSD-2-Clause"), ("libpng.txt", "libpng-2.0"), ("libtiff.txt", "libtiff"),
        ("llvm-libc.txt", "Apache-2.0 WITH LLVM-exception(파일 안)"), ("pdfium-binaries.txt", "MIT"),
        ("pdfium.txt", "BSD-3-Clause·Apache-2.0(파일 안)"), ("simdutf.txt", "MIT"), ("zlib.txt", "Zlib"))]
    # W9 재작업 1회차: qt_attribution.json의 LicenseFile·CopyrightFile 원문(qtbase v6.12.0), cryptography 휠 동봉 SBOM
    + [("qt/third-party/files/%s" % f, lic) for f, lic in (
        ("D3D12MemoryAllocator/LICENSE.txt", "MIT"), ("VulkanMemoryAllocator/LICENSE.txt", "MIT"),
        ("blake2/COPYING", "CC0-1.0 OR Apache-2.0"), ("double-conversion/LICENSE", "BSD-3-Clause"),
        ("easing/LICENSE", "BSD-3-Clause"), ("freetype/BDF-LICENSE.txt", "MIT"),
        ("freetype/PCF-LICENSE.txt", "MIT AND MIT-open-group"), ("freetype/ZLIB-LICENSE.txt", "Zlib"),
        ("freetype/LICENSE.txt", "FTL OR GPL-2.0-only"), ("harfbuzz-ng/COPYING", "MIT"),
        ("icc/LICENSE.txt", "LicenseRef-ICC-License"), ("libjpeg/LICENSE", "IJG AND BSD-3-Clause"),
        ("libjpeg/ijg-license.txt", "IJG AND BSD-3-Clause"), ("libjpeg/COPYRIGHT.txt", "저작권자 목록"),
        ("libpng/LICENSE", "Libpng AND libpng-2.0"), ("libpsl/PSL-LICENSE.txt", "MPL-2.0"),
        ("libpsl/src/LICENSE.chromium", "BSD-3-Clause"), ("md4c/LICENSE.md", "MIT"),
        ("pcre2/LICENSE-SLJIT", "BSD-2-Clause"),
        ("pcre2/LICENCE.md", "LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception"),
        ("rfc6234/LICENSE", "BSD-3-Clause"), ("sha3/CC0_LICENSE", "CC0-1.0"), ("sha3/BRG_ENDIAN_LICENSE", "BSD-2-Clause"),
        ("tinycbor/LICENSE", "MIT"), ("zlib/LICENSE", "Zlib"))]
    + [("python/cryptography-sboms/%s" % f, "구성요소별(파일 안)")
       for f in ("sbom.json", "cryptography-rust.cyclonedx.json")]
    # W9-B(D17): VS 2022 사용 조건(.docx와 텍스트 사본), cryptography 안 OpenSSL·Rust 크레이트(crates.io .crate) 원문
    + [("msvc/vs2022-license-terms.docx", "Microsoft 소프트웨어 사용 조건"),
       ("msvc/vs2022-license-terms.txt", "Microsoft 소프트웨어 사용 조건"),
       ("python/openssl-4.0.0-LICENSE.txt", "Apache-2.0")]
    + [("python/cryptography-rust-crates/%s/%s" % (c, f), lic) for c in _CRATES_MIT_APACHE
       for f, lic in (("LICENSE-APACHE", "Apache-2.0"), ("LICENSE-MIT", "MIT"))]
    + [("python/cryptography-rust-crates/%s" % f, lic) for f, lic in (
        ("asn1-0.24.1/LICENSE", "BSD-3-Clause"), ("asn1_derive-0.24.1/LICENSE", "BSD-3-Clause"),
        ("openssl-sys-0.9.115/LICENSE-MIT", "MIT"), ("openssl-0.10.79/LICENSE", "Apache-2.0"),
        ("openssl-0.10.79/LICENSE-APACHE", "Apache-2.0"), ("pem-3.0.6/LICENSE.md", "MIT"),
        ("self_cell-1.2.2/LICENSE-APACHE", "Apache-2.0"), ("self_cell-1.2.2/LICENSE-GPLv2", "GPL-2.0-only"),
        ("target-lexicon-0.13.5/LICENSE", "Apache-2.0 WITH LLVM-exception"),
        ("unicode-ident-1.0.24/LICENSE-UNICODE", "Unicode-3.0"))])
# W9(D15): PDF 어댑터 휠 고정(packaging/requirements-pdf.txt) — 이 8개만, 휠 하나의 sha256씩
PDF_PINS = {"pdfplumber": "0.11.9", "pdfminer.six": "20251230", "pillow": "12.2.0", "pypdfium2": "5.8.0",
            "charset-normalizer": "3.4.7", "cryptography": "48.0.0", "cffi": "2.0.0", "pycparser": "3.0"}
REQUIRED_DOCS = ("qt/QT-SOURCE.md", "qt/QTWEBENGINE-THIRD-PARTY.md")  # Qt 소스 위치·WebEngine 제3자 목록 위치


def _notice_rows(path=None):
    """licenses/README.md 고지 목록 표 → [(구성요소, 버전, 라이선스, 원문 파일, sha256)]."""
    rows = []
    with open(path or os.path.join(LICENSES_DIR, "README.md"), encoding="utf-8") as fh:
        for ln in fh:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) == 7 and cells[4].startswith("`") and cells[6].startswith("`"):
                rows.append((cells[0], cells[1], cells[2], cells[4].strip("`"), cells[6].strip("`")))
    return rows


def _table_problems(text):
    """Markdown 표 연속성: '|'로 시작하는 줄 묶음마다 첫 줄이 머리행, 둘째 줄이 구분행(|---|)이고, 모든 행의 칸 수가
    머리행과 같아야 한다. 빈 줄로 끊긴 표(머리행 없이 시작하는 행 묶음)를 잡는다. 문제 목록(빈 목록 = 통과)."""
    import re
    probs, block = [], []

    def ncell(ln):
        return len(ln.strip().strip("|").split("|"))

    def check(block):
        if not block:
            return
        (n0, h), rest = block[0], block[1:]
        if not rest or not re.match(r"^\|(\s*:?-{3,}:?\s*\|)+$", rest[0][1].strip()):
            probs.append("%d행: 머리행·구분행 없이 시작하는 표" % n0)
            return
        probs.extend("%d행: 칸 수 %d != 머리행 %d" % (n, ncell(ln), ncell(h)) for n, ln in rest if ncell(ln) != ncell(h))
    for n, ln in enumerate(text.splitlines(), 1):
        if ln.startswith("|"):
            block.append((n, ln))
        else:
            check(block)
            block = []
    check(block)
    return probs


def _notice_problems(rows, licenses_dir=LICENSES_DIR):
    """고지 목록을 기준 목록·폴더와 대조. 문제 목록(빈 목록 = 통과)."""
    probs = []
    listed = {r[3]: r for r in rows}
    for rel, lic in sorted(REQUIRED_NOTICES.items()):
        if rel not in listed:
            probs.append("기준 원문이 목록에 없음: %s" % rel)
        elif listed[rel][2] != lic:
            probs.append("라이선스 식별자 다름: %s %r != %r" % (rel, listed[rel][2], lic))
    probs += ["기준 안내문이 목록에 없음: %s" % rel for rel in REQUIRED_DOCS if rel not in listed]
    for _, _, _, rel, sha in rows:
        p = os.path.join(licenses_dir, *rel.split("/"))
        if not os.path.isfile(p):
            probs.append("원문 파일 없음: %s" % rel)
            continue
        with open(p, "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != sha:
                probs.append("SHA-256 불일치: %s" % rel)
    on_disk = {os.path.relpath(os.path.join(d, f), licenses_dir).replace("\\", "/")
               for d, _, files in os.walk(licenses_dir) for f in files}
    probs += ["목록 밖 파일: %s" % x for x in sorted(on_disk - set(listed) - {"README.md", ".gitattributes"})]
    return probs


class LicenseNoticeTest(unittest.TestCase):
    """고지 목록이 기준 목록(원문 경로·라이선스 식별자)과 맞고, 원문 파일이 있고 SHA-256이 목록과 같으며(W6 완료 기준),
    README 표가 끊기지 않았다. W9(D15)부터 licenses/는 datas가 아니라 빌드 뒤 실행 파일 옆으로 복사된다."""

    @classmethod
    def setUpClass(cls):
        cls.bp = _build_package()
        cls.rows = _notice_rows()

    def test_licenses_copied_next_to_exe(self):
        """W9(D15): licenses/는 datas(_internal/licenses/)에 넣지 않고, 빌드 뒤 결과 폴더의 실행 파일 옆으로 복사한다."""
        self.assertNotIn("licenses", self.bp.DATA_DIRS)
        self.assertFalse([s for s, _ in self.bp.datas_list() if s.startswith("licenses/")])
        for with_check in (False, True):
            text, ns = self.bp.spec_text(with_check=with_check), {}
            exec(text.split("HAZOP_MODULES =")[0] + "\n".join(
                ln for ln in text.splitlines() if ln.startswith(("REPO =", "DATAS ="))), ns)
            self.assertFalse([s for s, _ in ns["DATAS"] if self.bp.inside(s, LICENSES_DIR)])
            out = tempfile.mkdtemp(prefix="hazop-lic-copy-")
            self.addCleanup(shutil.rmtree, out, True)
            dist = self.bp.dist_dir(out, with_check)
            os.makedirs(os.path.join(dist, "_internal"))
            dest = self.bp.copy_licenses(out, with_check)
            self.assertEqual(dest, os.path.join(dist, "licenses"))
            listed = {r[3] for r in self.rows} | {"README.md", ".gitattributes"}
            on_disk = {os.path.relpath(os.path.join(d, f), dest).replace("\\", "/")
                       for d, _, fs in os.walk(dest) for f in fs}
            self.assertEqual(on_disk, listed)
            self.assertEqual(self.bp.licenses_problems(dist), [])
            os.makedirs(os.path.join(dist, "_internal", "licenses"))  # 이전 위치가 남아 있으면 실패
            self.assertEqual(self.bp.licenses_problems(dist),
                             ["이전 위치 _internal/licenses/가 있음(실행 파일 옆으로 옮김, D15)"])

    def test_notices_match_baseline_and_sha256(self):
        self.assertEqual(_notice_problems(self.rows), [])

    def test_readme_tables_continuous(self):
        """licenses/README.md의 표가 빈 줄로 끊기지 않았다(끊기면 뒤 행이 머리행 없는 별도 표가 된다)."""
        with open(os.path.join(LICENSES_DIR, "README.md"), encoding="utf-8") as fh:
            self.assertEqual(_table_problems(fh.read()), [])
        good = "글\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        self.assertEqual(_table_problems(good), [])
        self.assertEqual(_table_problems(good + "\n| 3 | 4 |\n"), ["7행: 머리행·구분행 없이 시작하는 표"])
        self.assertEqual(_table_problems(good + "| 3 | 4 | 5 |\n"), ["6행: 칸 수 3 != 머리행 2"])

    def test_rust_crates_cover_sbom(self):
        """W9-B(D17): SBOM의 crates.io 크레이트마다 원문 폴더(`<이름>-<버전>/`)가 있고, 그 밖의 폴더는 없다.
        cryptography 내부 경로 크레이트(download_url=file)는 cryptography 고지로 갈음한다."""
        import json
        with open(os.path.join(LICENSES_DIR, "python", "cryptography-sboms", "cryptography-rust.cyclonedx.json"),
                  encoding="utf-8") as fh:
            comps = json.load(fh)["components"]
        want = {"%s-%s" % (c["name"], c["version"]) for c in comps if "download_url=file" not in c["purl"]}
        self.assertEqual(len(want), 32)
        have = set(os.listdir(os.path.join(LICENSES_DIR, "python", "cryptography-rust-crates")))
        self.assertEqual(have, want)

    def test_removed_row_and_file_detected(self):
        """목록 행과 원문 파일을 함께 지워도(사본에서) 기준 목록 대조로 실패한다. 식별자·해시 변경도 잡는다."""
        tmp = tempfile.mkdtemp(prefix="hazop-lic-")
        self.addCleanup(shutil.rmtree, tmp, True)
        lic = os.path.join(tmp, "licenses")
        shutil.copytree(LICENSES_DIR, lic)
        self.assertEqual(_notice_problems(_notice_rows(os.path.join(lic, "README.md")), lic), [])
        rows = [r for r in self.rows if r[3] != "force-graph/d3-ease-LICENSE"]
        os.remove(os.path.join(lic, "force-graph", "d3-ease-LICENSE"))
        self.assertEqual(_notice_problems(rows, lic), ["기준 원문이 목록에 없음: force-graph/d3-ease-LICENSE"])
        rows = [r if r[3] != "qt/LGPL-3.0.txt" else r[:2] + ("MIT",) + r[3:] for r in self.rows]
        self.assertTrue(any("식별자 다름: qt/LGPL-3.0.txt" in p for p in _notice_problems(rows)))
        with open(os.path.join(lic, "force-graph", "preact-LICENSE"), "ab") as fh:
            fh.write(b" ")
        self.assertIn("SHA-256 불일치: force-graph/preact-LICENSE", _notice_problems(self.rows, lic))

    def test_notice_versions_match_pins(self):
        """목록의 버전이 전용 venv 고정(packaging/requirements*.txt)·vendor 폴더 이름과 같고, 간접 의존성은 추정 표시."""
        pins = {}
        for name in ("requirements.txt", "requirements-build.txt"):
            with open(os.path.join(REPO_ROOT, "packaging", name), encoding="utf-8") as fh:
                for ln in fh:
                    if "==" in ln:
                        k, v = ln.strip().split("==")
                        pins[k.lower()] = v
        by_file = {r[3]: r[1] for r in self.rows}
        self.assertTrue(by_file["qt/LGPL-3.0.txt"].startswith(pins["pyside6"] + " "))
        self.assertEqual(by_file["python/networkx-LICENSE.txt"], pins["networkx"])
        self.assertEqual(by_file["python/openpyxl-LICENCE.rst"], pins["openpyxl"])
        self.assertEqual(by_file["pyinstaller/COPYING.txt"], pins["pyinstaller"])
        pdf_rows = {"pdfplumber": "python/pdfplumber-LICENSE.txt", "pdfminer.six": "python/pdfminer.six-LICENSE",
                    "pillow": "python/pillow-LICENSE", "charset-normalizer": "python/charset_normalizer-LICENSE",
                    "cryptography": "python/cryptography-LICENSE", "cffi": "python/cffi-LICENSE",
                    "pycparser": "python/pycparser-LICENSE", "pypdfium2": "python/pypdfium2/LICENSES/Apache-2.0.txt"}
        pdf_pins = _pdf_pins()
        self.assertEqual(set(pdf_rows), set(pdf_pins))
        for name, rel in pdf_rows.items():  # W9(D15): 고지 목록의 버전 = requirements-pdf.txt 고정 버전
            self.assertEqual(by_file[rel], pdf_pins[name][0], name)
        vendor = [d for d in os.listdir(os.path.dirname(kg_screen.VENDOR_DIR)) if d.startswith("force-graph-")]
        self.assertEqual(by_file["force-graph/force-graph-LICENSE"], vendor[0].split("-")[-1] + "(vendor)")
        for rel in REQUIRED_NOTICES:
            if rel.startswith("force-graph/") and rel not in ("force-graph/force-graph-LICENSE",
                                                              "force-graph/Apache-2.0.txt"):
                self.assertIn("(추정)", by_file[rel], rel)


def _pdf_pins(path=None):
    """packaging/requirements-pdf.txt → {이름: (버전, [sha256, ...])}. 줄 이음(\\)과 --hash 줄을 읽는다."""
    import re
    with open(path or os.path.join(REPO_ROOT, "packaging", "requirements-pdf.txt"), encoding="utf-8") as fh:
        text = re.sub(r"\\\r?\n", " ", fh.read())
    pins = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)==(\S+)((?:\s+--hash=sha256:[0-9a-f]{64})*)\s*$", ln)
        if not m:
            raise ValueError("해석할 수 없는 줄: %r" % ln)
        pins[m.group(1).lower()] = (m.group(2), re.findall(r"[0-9a-f]{64}", m.group(3)))
    return pins


class BundleLicensesTest(unittest.TestCase):
    """packaging/verify_bundle.licenses_problems: 묶음의 실행 파일 옆 licenses/가 저장소 licenses/와 같고 이전 위치
    _internal/licenses/가 없는지(빌드 없이, W9 D15)."""

    def test_licenses_problems(self):
        vb = _load("packaging/verify_bundle.py", "hazop_verify_bundle_lic")
        tmp = tempfile.mkdtemp(prefix="hazop-bundle-lic-")
        self.addCleanup(shutil.rmtree, tmp, True)
        dest = os.path.join(tmp, "licenses")
        self.assertTrue(vb.licenses_problems(tmp))  # 묶음에 licenses 없음
        shutil.copytree(LICENSES_DIR, dest)
        self.assertEqual(vb.licenses_problems(tmp), [])
        with open(os.path.join(dest, "qt", "GPL-3.0.txt"), "ab") as fh:
            fh.write(b"x")
        os.remove(os.path.join(dest, "force-graph", "d3-ease-LICENSE"))
        open(os.path.join(dest, "extra.txt"), "w").close()
        probs = vb.licenses_problems(tmp)
        self.assertIn("해시 다름: qt/GPL-3.0.txt", probs)
        self.assertIn("묶음에 없음: force-graph/d3-ease-LICENSE", probs)
        self.assertIn("저장소에 없는 파일: extra.txt", probs)
        self.assertNotIn("이전 위치 _internal/licenses/가 있음(실행 파일 옆으로 옮김, D15)", probs)
        shutil.rmtree(dest)  # 이전 위치(_internal/licenses/)에만 있으면 전부 없음 + 이전 위치 문제
        shutil.copytree(LICENSES_DIR, os.path.join(tmp, "_internal", "licenses"))
        probs = vb.licenses_problems(tmp)
        self.assertIn("묶음에 없음: README.md", probs)
        self.assertEqual(probs[-1], "이전 위치 _internal/licenses/가 있음(실행 파일 옆으로 옮김, D15)")


class BundleSymbolsTest(unittest.TestCase):
    """packaging/verify_bundle.symbols_problems: 묶음 안 기호 사전이 읽히고 구조·이름 낱말 견본이 들어 있는지(빌드 없이)."""

    def test_symbols_problems(self):
        vb = _load("packaging/verify_bundle.py", "hazop_verify_bundle_sym")
        tmp = tempfile.mkdtemp(prefix="hazop-bundle-sym-")
        self.addCleanup(shutil.rmtree, tmp, True)
        dest = paths.folder_in(os.path.join(tmp, "_internal"), "symbols")
        self.assertEqual(len(vb.symbols_problems(tmp)), 1)  # 묶음에 사전 없음
        shutil.copytree(paths.folder("symbols"), dest)
        self.assertEqual(vb.symbols_problems(tmp), [])
        for fn in os.listdir(os.path.join(dest, "common")):
            if fn.startswith("name_"):
                os.remove(os.path.join(dest, "common", fn))
        self.assertEqual(vb.symbols_problems(tmp), ["기호 사전에 label_words 견본이 없음(코드보다 옛 판 사전)"])


class PdfBundleTest(unittest.TestCase):
    """W9(D15): PDF 어댑터 묶음 — requirements-pdf.txt 고정, 빌드 뒤 PDF 검사, verify의 pdf_probe 판정(빌드 없이)."""

    @classmethod
    def setUpClass(cls):
        cls.bp = _build_package()
        cls.vb = _load("packaging/verify_bundle.py", "hazop_verify_bundle_pdf")
        cls.probe = _load("packaging/pdf_probe.py", "hazop_pdf_probe_t")

    def _tmp(self):
        d = tempfile.mkdtemp(prefix="hazop-pdf-")
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_requirements_pdf_pins_and_hashes(self):
        pins = _pdf_pins()
        self.assertEqual({k: v[0] for k, v in pins.items()}, PDF_PINS)
        for name, (_, hashes) in pins.items():
            self.assertEqual(len(hashes), 1, name)  # 휠 하나만(다른 휠·sdist로 바뀌지 않게)
        bad = os.path.join(self._tmp(), "r.txt")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("pdfplumber>=0.11\n")
        with self.assertRaises(ValueError):
            _pdf_pins(bad)

    def _fake_build(self, mods, dll=True, with_check=False):
        out = self._tmp()
        b = os.path.join(out, "build", "HAZOP")
        os.makedirs(b)
        with open(os.path.join(b, "PYZ-00.toc"), "w", encoding="utf-8") as fh:
            fh.write(repr((os.path.join(b, "PYZ-00.pyz"), [(m, "C:\\x\\%s.py" % m, "PYMODULE") for m in mods])))
        d = os.path.join(self.bp.dist_dir(out, with_check), "_internal", *self.bp.PDFIUM_DLL)
        os.makedirs(os.path.dirname(d))
        if dll:
            open(d, "wb").close()
        return out

    def test_pdf_problems(self):
        mods = list(self.bp.PDF_REQUIRED_MODULES + self.bp.LAZY_MODULES) + ["hazop", "PIL"]
        for with_check in (False, True):
            self.assertEqual(self.bp.pdf_problems(self._fake_build(mods, with_check=with_check), with_check), [])
        self.assertEqual(self.bp.pdf_problems(self._fake_build([m for m in mods if m != "openpyxl"])),
                         ["앱 PYZ에 지연 import 모듈 없음: openpyxl"])
        out = self._fake_build([m for m in mods if m != "pypdfium2_raw"], dll=False)
        probs = self.bp.pdf_problems(out)
        self.assertEqual(probs[0], "앱 PYZ에 PDF 모듈 없음: pypdfium2_raw")
        self.assertTrue(probs[1].startswith("pdfium.dll 없음: "))
        self.assertTrue(self.bp.pdf_problems(self._tmp())[0].startswith("앱 PYZ TOC를 읽을 수 없음"))

    def test_finish_bundle(self):
        """빌드 뒤 마무리: 실행 파일 옆 licenses/ 복사 + 고지 대조 + PDF 검사. 결과 폴더가 없으면 실패."""
        self.assertTrue(self.bp.finish_bundle(self._tmp())[0].startswith("결과 폴더 없음"))
        out = self._fake_build(list(self.bp.PDF_REQUIRED_MODULES + self.bp.LAZY_MODULES))
        self.assertEqual(self.bp.finish_bundle(out), [])
        self.assertTrue(os.path.isfile(os.path.join(self.bp.dist_dir(out), "licenses", "README.md")))
        self.assertTrue(self.bp.finish_bundle(out)[0].startswith("제3자 고지 복사 실패"))  # 두 번째 복사(이미 있음)

    def test_license_tree_walk_error_fails(self):
        """고지 대조의 폴더 탐색 오류(onerror)·파일 읽기 오류는 '같음'이 아니라 실패다."""
        out = self._fake_build(list(self.bp.PDF_REQUIRED_MODULES + self.bp.LAZY_MODULES))
        dist = self.bp.dist_dir(out)
        self.bp.copy_licenses(out)
        self.assertEqual(self.bp.licenses_problems(dist), [])
        real_walk = os.walk

        def bad_walk(top, onerror=None, **kw):
            if onerror is not None and os.path.normcase(top).startswith(os.path.normcase(dist)):
                onerror(PermissionError(13, "액세스 거부(모의)", os.path.join(top, "qt")))
            return real_walk(top, onerror=onerror, **kw)
        with mock.patch.object(self.bp.os, "walk", side_effect=bad_walk):
            probs = self.bp.licenses_problems(dist)
        self.assertEqual(len(probs), 1)
        self.assertTrue(probs[0].startswith("고지 대조 중 탐색 오류:"), probs)
        with mock.patch("builtins.open", side_effect=PermissionError(13, "읽기 거부(모의)")):
            self.assertTrue(self.bp.licenses_problems(dist)[0].startswith("고지 대조 중 탐색 오류:"))

    def test_main_rc3_when_finish_bundle_fails(self):
        """빌드 뒤 마무리(finish_bundle)가 문제를 돌려주면 main은 rc=3이고, 마무리는 결과 폴더 경로로 한 번 불린다."""
        out = self._tmp()
        fin = mock.Mock(return_value=["x"])
        with mock.patch.dict(sys.modules, {"PyInstaller": mock.Mock()}), \
                mock.patch.object(self.bp, "build", return_value=0), \
                mock.patch.object(self.bp, "check_dist", return_value=[]), \
                mock.patch.object(self.bp, "check_sources", return_value=[]), \
                mock.patch.object(self.bp, "python_problems", return_value=[]), \
                mock.patch.object(self.bp, "finish_bundle", fin):
            self.assertEqual(self.bp.main(["--out", out, "--build"]), 3)
            fin.assert_called_once_with(os.path.abspath(out), False)
            fin.return_value = []
            self.assertEqual(self.bp.main(["--out", out, "--build", "--with-check"]), 0)
            fin.assert_called_with(os.path.abspath(out), True)

    def test_pdf_probe_problems(self):
        bundle = self._tmp()
        inner = os.path.join(bundle, "_internal")
        exp = {"extraction_run_id": "x", "summary": {"nodes": 1}, "counts": {"nodes": 1}}
        files = {m: os.path.join(inner, m, "__init__.pyc") for m in self.probe.PROBE_MODULES}
        good = {"frozen": True, "extraction": dict(exp), "render_size": [100, 80], "module_files": files,
                "pdfium_dll": os.path.join(inner, "pypdfium2_raw", "pdfium.dll"), "pdfium_dll_exists": True}
        self.assertEqual(self.vb.pdf_probe_problems(good, exp, bundle), [])
        self.assertEqual(self.vb.PDF_PROBE_MODULES, self.probe.PROBE_MODULES)
        # 필수 키 누락: 모듈 키가 빠지거나 pdfium_dll 키가 없으면 실패(빈 결과가 통과하지 않게)
        missing = dict(good, module_files={k: v for k, v in files.items() if k not in ("PIL", "cryptography")})
        del missing["pdfium_dll"]
        self.assertEqual(self.vb.pdf_probe_problems(missing, exp, bundle),
                         ["결과에 없음: PIL", "결과에 없음: cryptography", "결과에 없음: pdfium.dll"])
        self.assertEqual(self.vb.pdf_probe_problems(dict(good, module_files=None), exp, bundle),
                         ["결과에 없음: %s" % m for m in self.probe.PROBE_MODULES])
        self.assertEqual(self.vb.pdf_probe_problems(None, exp, bundle), ["결과 없음"])
        self.assertEqual(self.vb.pdf_probe_problems({"error": "ImportError: x"}, exp, bundle), ["오류: ImportError: x"])
        bad = dict(good, frozen=False, extraction=dict(exp, summary={"nodes": 2}), render_size=[0, 5],
                   pdfium_dll_exists=False,
                   module_files=dict(files, pdfplumber=r"C:\venv\Lib\site-packages\pdfplumber\__init__.py", PIL=None))
        self.assertEqual(self.vb.pdf_probe_problems(bad, exp, bundle),
                         ["묶인 실행이 아님", "추출 요약이 개발 실행과 다름", "pypdfium2 그림 크기 이상: [0, 5]",
                          "읽히지 않음: PIL", "읽히지 않음: pdfium.dll",
                          "묶음 밖에서 읽힘: pdfplumber (C:\\venv\\Lib\\site-packages\\pdfplumber\\__init__.py)"])

    @unittest.skipUnless(importlib.util.find_spec("pdfplumber"), "pdfplumber 없음(전용 venv에서 실행)")
    def test_probe_runs_in_dev_venv(self):
        """개발 실행(묶지 않음)에서 pdf_probe가 샘플 PDF를 추출·그리고, 요약이 verify의 기대값(pdf_expected)과 같다."""
        pdf = paths.folder("references", *self.vb.SAMPLE_DIR, self.vb.SAMPLE_DIR[-1] + ".pdf")
        res = os.path.join(self._tmp(), "r.json")
        self.assertEqual(self.probe.main(["--pdf", pdf, "--result", res]), 0)
        got = data.read_json(res)
        self.assertFalse(got["frozen"])
        self.assertEqual(got["extraction"], self.vb.pdf_expected(pdf))
        self.assertTrue(got["pdfium_dll_exists"])
        self.assertTrue(all(got["module_files"].values()))
        # 묶음 판정으로 보면 개발 실행은 '묶인 실행이 아님'·'묶음 밖에서 읽힘'으로 실패한다
        probs = self.vb.pdf_probe_problems(got, got["extraction"], self._tmp())
        self.assertIn("묶인 실행이 아님", probs)
        self.assertTrue(any(p.startswith("묶음 밖에서 읽힘: pdfplumber") for p in probs))


def _load(rel, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO_ROOT, *rel.split("/")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _other_drive(path):
    return "Z:\\x" if os.path.splitdrive(path)[0].upper() != "Z:" else "Y:\\x"


class VerifierTest(unittest.TestCase):
    """packaging/verify_bundle.py의 안전 장치(빌드 없이): 기존 폴더를 지우지 않음, 해시 비교, 오래된 PNG, 실패·정리."""

    @classmethod
    def setUpClass(cls):
        cls.vb = _load("packaging/verify_bundle.py", "hazop_verify_bundle")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-verify-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dist = os.path.join(self.tmp, "dist", "HAZOP")
        os.makedirs(self.dist)
        with open(os.path.join(self.dist, "HAZOP.exe"), "w") as fh:
            fh.write("not an executable")

    def test_base_problems_and_new_run_root(self):
        self.assertTrue(self.vb.base_problems(os.path.join(REPO_ROOT, "x"), self.dist))      # 저장소 안
        self.assertTrue(self.vb.base_problems(os.path.dirname(REPO_ROOT), self.dist))        # 저장소를 포함
        self.assertTrue(self.vb.base_problems(os.path.join(self.dist, "sub"), self.dist))    # dist 안
        self.assertTrue(self.vb.base_problems(os.path.join(self.tmp, "dist"), self.dist))    # dist를 포함
        self.assertEqual(self.vb.base_problems(os.path.join(self.tmp, "base"), self.dist), [])
        self.assertFalse(self.vb.inside(_other_drive(self.tmp), self.tmp))  # 다른 드라이브: ValueError 없이 False
        base = os.path.join(self.tmp, "base")
        a, b = self.vb.new_run_root(base), self.vb.new_run_root(base)
        self.assertNotEqual(a, b)
        self.assertTrue(os.path.basename(a).startswith("verify-"))
        with self.assertRaises(FileExistsError):
            self.vb.new_run_root(base, os.path.basename(a))
        for bad in ("..", "a/b", r"a\b", ""):
            with self.assertRaises(ValueError):
                self.vb.new_run_root(base, bad) if bad else self.vb.new_run_root(base, ".")

    def test_app_checks_without_window(self):
        """W10(D18) 판정 함수: 손상 설정(--screenshots) rc 2·안내·로그·파일 그대로, 시험 트리거는 검증용 rc 70·배포용 rc 2."""
        ok = ("설정 파일을 읽을 수 없어 종료합니다: x\n원인: JSONDecodeError: ...", "WARNING hazop.settings: 설정 파일을 읽을 수 없음")
        self.assertTrue(self.vb.bad_settings_ok(2, ok[0], ok[1], True))
        self.assertFalse(self.vb.bad_settings_ok(1, ok[0], ok[1], True))
        self.assertFalse(self.vb.bad_settings_ok(2, "", ok[1], True))
        self.assertFalse(self.vb.bad_settings_ok(2, ok[0], "", True))
        self.assertFalse(self.vb.bad_settings_ok(2, ok[0], ok[1], False))  # 백업·덮어쓰기·PNG가 생김
        hooked = "CRITICAL hazop.unhandled: 미처리 예외\nRuntimeError: 시험용 미처리 예외(HAZOP_TEST_EXCEPTHOOK)"
        self.assertTrue(self.vb.trigger_ok(False, 70, hooked))
        self.assertFalse(self.vb.trigger_ok(False, 2, ok[1]))       # 검증용인데 트리거가 꺼짐
        self.assertFalse(self.vb.trigger_ok(False, 70, hooked.split("\n")[0]))
        self.assertTrue(self.vb.trigger_ok(True, 2, ok[1]))         # 배포용: 트리거 꺼짐
        self.assertFalse(self.vb.trigger_ok(True, 70, hooked))      # 배포용인데 트리거가 켜짐
        with open(os.path.join(REPO_ROOT, "packaging", "verify_bundle.py"), encoding="utf-8") as fh:
            self.assertNotIn("bad-settings.json", fh.read())

    def _fake_app(self, verify_build, calls):
        """HAZOP.exe 대역: 실제 scripts/run_app.main을 같은 프로세스에서 부른다(스크린샷 정상 실행만 rc 0으로 건너뜀).
        앱 로그는 런타임 훅처럼 root logging과 sys.excepthook을 <작업 루트>/logs/app.log에 연결한다.
        모든 실행이 비대화형(--screenshots 또는 잘못된 옵션)인지 확인하고, 대화상자·QApplication이 불리면 실패한다."""
        import contextlib
        import io
        import logging
        ra = _load("scripts/run_app.py", "hazop_run_app_fake")

        def fake_run(cmd, env, cwd, log, timeout=None):
            calls.append((cmd, env.get("HAZOP_TEST_EXCEPTHOOK")))
            self.assertTrue("--screenshots" in cmd or "--w4-unknown-option" in cmd, cmd)  # 대화형 실행 없음
            args = cmd[1:]
            log_path = os.path.join(env["HAZOP_WORK_ROOT"], "logs", "app.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
            root = logging.getLogger()
            root.addHandler(handler)
            level, root.level = root.level, logging.INFO
            out = io.StringIO()

            def hook(*exc):
                logging.getLogger("hazop.unhandled").critical("미처리 예외", exc_info=exc)
            try:
                if args[:1] == ["--screenshots"] and os.path.dirname(args[3]) == cwd:  # 정상 설정의 스크린샷
                    logging.getLogger("hazop.startup").info("시작 pid=1")
                    rc = 0
                else:
                    with mock.patch.dict(os.environ, {k: v for k, v in env.items() if k == "HAZOP_TEST_EXCEPTHOOK"}), \
                            mock.patch.object(sys, "_hazop_verify_build", verify_build, create=True), \
                            mock.patch.object(sys, "excepthook", hook), \
                            mock.patch("hazop.app.make_application", side_effect=AssertionError("창 생성")), \
                            mock.patch("hazop.app.startup.ask_dialog", side_effect=AssertionError("대화상자")), \
                            contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                        try:
                            rc = ra.main(args)
                        except SystemExit as e:
                            rc = e.code
            finally:
                root.removeHandler(handler)
                handler.close()
                root.level = level
            with open(log, "w", encoding="utf-8") as fh:
                fh.write(out.getvalue())
            return rc, 0.0, out.getvalue()
        return fake_run

    def test_app_steps_mock_run(self):
        """W10(D18) verify 단계 4를 대역 HAZOP.exe(실제 run_app.main)로 실행: 검증용은 트리거 rc 70·미처리 예외 기록,
        배포용은 트리거 꺼짐 rc 2. 두 경우 모두 손상 설정 rc 2·파일 그대로이고, 대화형 실행·창 생성이 없다."""
        for verify_build in (True, False):
            for app_only in (False, True):
                tmp = tempfile.mkdtemp(prefix="hazop-appsteps-", dir=self.tmp)
                work = os.path.join(tmp, "work")
                out, png = os.path.join(tmp, "out"), os.path.join(tmp, "png")
                os.makedirs(out)
                calls, summary = [], {"steps": {}, "checks": {}}
                with mock.patch.object(self.vb, "run", self._fake_app(verify_build, calls)):
                    rc, _, rc2 = self.vb.app_steps("HAZOP.exe", {"HAZOP_WORK_ROOT": work}, tmp, out, png, None,
                                                   app_only, summary)
                c, st = summary["checks"], summary["steps"]
                self.assertEqual((rc, rc2, st["app_bad_settings"]["rc"]), (0, 2, 2))
                self.assertEqual(st["app_excepthook"]["rc"], 70 if verify_build else 2)
                self.assertTrue(c["app_bad_settings"] and c["app_log_started"] and c["app_bad_option_rc2"])
                key = "app_trigger_off" if app_only else "app_log_unhandled"
                # 빌드 종류와 판정 기준이 맞을 때만(검증용 빌드 + 검증 판정, 배포용 빌드 + --app-only) 통과
                self.assertEqual(c[key], verify_build is not app_only, (verify_build, app_only))
                self.assertEqual(len(calls), 4)
                self.assertEqual([e for _, e in calls], [None, None, None, "1"])

    def test_child_env_path_is_system_only(self):
        """묶인 실행 PATH는 Windows System32·Windows 폴더뿐이고 Qt·OpenSSL 설정 변수는 지운다(D10, 사용자 PATH 의존 제거)."""
        extra = {"PATH": r"C:\jdk\bin;C:\Program Files\Git\mingw64\bin", "QT_PLUGIN_PATH": r"C:\x",
                 "QT_OPENSSL": "1", "OPENSSL_CONF": r"C:\x\o.cnf", "OPENSSL_MODULES": r"C:\x",
                 "SSL_CERT_FILE": r"C:\x\c.pem", "SSL_CERT_DIR": r"C:\x", "HAZOP_STORE_ROOT": r"C:\x",
                 "W8_KEEP_MARKER": "1"}
        with mock.patch.dict(os.environ, extra):
            env = self.vb.child_env(self.tmp)
        self.assertEqual([k for k in env if k.upper() == "PATH"], ["PATH"])
        self.assertFalse([k for k in env if k.upper().startswith(("QT_", "OPENSSL_", "SSL_CERT_", "HAZOP_STORE"))])
        self.assertEqual(env.get("W8_KEEP_MARKER"), "1")
        win = self.vb.bp.windows_dir()
        self.assertEqual(env["PATH"].split(os.pathsep), [os.path.join(win, "System32"), win])
        self.assertEqual(self.vb.runtime_path(r"C:\W"), os.pathsep.join([r"C:\W\System32", r"C:\W"]))

    def test_tree_hashes_detect_content_change(self):
        p = os.path.join(self.tmp, "a", "f.txt")
        os.makedirs(os.path.dirname(p))
        with open(p, "w") as fh:
            fh.write("1")
        before = self.vb.tree_hashes(os.path.join(self.tmp, "a"))
        with open(p, "w") as fh:
            fh.write("2")
        self.assertNotEqual(self.vb.tree_hashes(os.path.join(self.tmp, "a")), before)
        self.assertEqual(self.vb.tree_hashes(os.path.join(self.tmp, "none")), {})

    def test_fresh_problems_rejects_old_png(self):
        p = os.path.join(self.tmp, "01.png")
        open(p, "wb").close()
        os.utime(p, (1000, 1000))
        self.assertEqual(self.vb.fresh_problems(self.tmp, 2000, ["01.png", "02.png"]),
                         ["이번 실행 전 파일: 01.png", "없음: 02.png"])
        self.assertEqual(self.vb.fresh_problems(self.tmp, 500, ["01.png"]), [])

    def test_kg_work_root_puts_reference_copy_at_logical_path(self):
        """③ 검사 작업 루트 기준으로 샘플 도면 사본의 기록 경로가 저장소 샘플 도면의 기록 경로와 같다."""
        with self.assertRaises(ValueError):
            self.vb.kg_work_root(self.tmp)
        sample = self.vb.SAMPLE_DIR + (self.vb.SAMPLE_DIR[-1] + ".drawio",)
        drawio = paths.logical_dir(self.tmp, "references", *sample)
        os.makedirs(os.path.dirname(drawio))
        work = self.vb.kg_work_root(self.tmp)
        self.assertEqual(paths.rel_or_abs(drawio, work), paths.rel_or_abs(paths.folder("references", *sample), work))
        self.assertTrue(paths.is_reference_rel(paths.rel_or_abs(drawio, work)))

    def test_lock_probe_matches_app_titles_and_exit_code(self):
        """lock_probe가 기다리는 주 창 제목·종료 코드·잠금 파일 이름이 앱 정의와 같다."""
        from hazop.app import main_window, startup
        lp = _load("packaging/lock_probe.py", "hazop_lock_probe")
        self.assertEqual(lp.MAIN_TITLE, main_window.APP_NAME)
        self.assertEqual(lp.EXIT_RUNNING, startup.EXIT_RUNNING)
        self.assertEqual(lp.LOCK_NAME, startup.LOCK_NAME)

    def test_app_png_covers_every_rail_stage_and_edit_mode(self):
        """배포본 스크린샷 목록이 레일 단계 ①~⑥ × 두 크기와 ② 편집 모드를 모두 요구한다(앱의 단계 정의와 같은 이름)."""
        from hazop.app import screenshots
        from hazop.app.main_window import STAGES
        self.assertEqual(self.vb.STAGE_NAMES, tuple((n, short) for n, short, _ in STAGES))
        self.assertEqual(self.vb.STAGE_SIZES, screenshots.STAGE_SIZES)
        self.assertIn("02-viewer-edit.png", self.vb.APP_PNG)
        self.assertEqual([n for n in self.vb.APP_PNG if n.startswith("stages/stage6-")],
                         ["stages/stage6-초기사건-1366x768.png", "stages/stage6-초기사건-1920x1080.png"])
        self.assertFalse(set(self.vb.APP_PNG) - set(self.vb.FULL_PNG))

    def _summary(self, out):
        runs = sorted(os.listdir(out))
        return data.read_json(os.path.join(out, runs[-1], "summary.json")), runs

    def test_main_precheck_existing_folder_and_cleanup(self):
        base, out = os.path.join(self.tmp, "base"), os.path.join(self.tmp, "o")
        # 검증 exe 없는 dist를 --app-only 없이 넘기면 사전 검사에서 중단(아무것도 만들지 않음)
        self.assertEqual(self.vb.main(["--dist", self.dist, "--target-base", base, "--out", out]), 2)
        self.assertFalse(os.path.exists(out) or os.path.exists(base))
        # 이전 검증 사본처럼 보이는 폴더(표지·HAZOP.exe)가 같은 이름으로 있으면 지우지 않고 실패
        old = os.path.join(base, "verify-old", "HAZOP")
        os.makedirs(old)
        for f in (".hazop-verify-copy", "HAZOP.exe"):
            open(os.path.join(old, f), "wb").close()
        self.assertEqual(self.vb.main(["--dist", self.dist, "--target-base", base, "--out", out,
                                       "--run-name", "verify-old", "--app-only"]), 2)
        self.assertEqual(sorted(os.listdir(old)), [".hazop-verify-copy", "HAZOP.exe"])
        # 실행할 수 없는 exe: 단계 오류를 기록하고 실패, 이번 실행 폴더만 지운다(기존 폴더는 그대로)
        self.assertEqual(self.vb.main(["--dist", self.dist, "--target-base", base, "--out", out, "--app-only"]), 1)
        summary, runs = self._summary(out)
        self.assertFalse(summary["passed"])
        self.assertTrue(str(summary["steps"]["app_screenshots"]["rc"]).startswith("error"))
        self.assertTrue(summary["run_root_removed"])
        self.assertEqual(os.listdir(base), ["verify-old"])
        self.assertEqual(self.vb.main(["--dist", self.dist, "--target-base", base, "--out", out, "--app-only"]), 1)
        self.assertEqual(len(os.listdir(out)), len(runs) + 1)  # 실행마다 새 결과 폴더

    def test_main_records_step_error_and_cleanup_failure(self):
        base, out = os.path.join(self.tmp, "base"), os.path.join(self.tmp, "o")
        real_rmtree = shutil.rmtree
        with mock.patch.object(self.vb, "tree_hashes", side_effect=OSError("읽기 실패")), \
                mock.patch.object(self.vb.shutil, "rmtree", side_effect=OSError("잠김")):
            self.assertEqual(self.vb.main(["--dist", self.dist, "--target-base", base, "--out", out,
                                           "--app-only"]), 1)
        summary, _ = self._summary(out)
        self.assertIn("읽기 실패", summary["errors"]["main"])   # 새 폴더 뒤 첫 단계(tree_hashes) 예외도 try 안
        self.assertIn("잠김", summary["errors"]["cleanup"])
        self.assertFalse(summary["run_root_removed"])
        self.assertFalse(summary["passed"])
        real_rmtree(base, True)


class SnapshotPathTest(unittest.TestCase):
    """packaging/make_snapshot.py: --overlay·--restore-head 경로 정규화와 저장소·목적지 탈출 거부."""

    @classmethod
    def setUpClass(cls):
        cls.ms = _load("packaging/make_snapshot.py", "hazop_make_snapshot")

    def test_normalize_rel(self):
        self.assertEqual(self.ms.normalize_rel(r"packaging\verify_bundle.py"), "packaging/verify_bundle.py")
        for bad in ("../x.py", "./packaging/verify_bundle.py", "packaging/../scripts/run_app.py", "packaging//a.py",
                    os.path.join(REPO_ROOT, "scripts", "run_app.py"), "C:x.py", "/etc/x", "", ".", "..",
                    "a/./b.py"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.ms.normalize_rel(bad)

    def test_dest_path_inside_only(self):
        tmp = tempfile.mkdtemp(prefix="hazop-snap-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertTrue(self.ms.dest_path(tmp, "a/b.py").startswith(os.path.realpath(tmp)))
        with self.assertRaises(ValueError):
            self.ms.dest_path(tmp, "../escape.py")

    def test_main_rejects_escape_before_copy(self):
        tmp = tempfile.mkdtemp(prefix="hazop-snap-")
        self.addCleanup(shutil.rmtree, tmp, True)
        dest = os.path.join(tmp, "s")
        self.assertEqual(self.ms.main(["--dest", dest, "--overlay", "../outside.py"]), 2)
        self.assertEqual(self.ms.main(["--dest", dest, "--overlay", "./scripts/run_app.py"]), 2)
        if os.path.isdir(os.path.join(REPO_ROOT, ".git")):  # 추적 파일 판정은 git 저장소에서만(스냅숏에는 .git 없음)
            self.assertEqual(self.ms.main(["--dest", dest, "--overlay", "scripts/run_app.py"]), 2)
        self.assertFalse(os.path.exists(dest))

    @unittest.skipUnless(os.path.isdir(os.path.join(REPO_ROOT, ".git")) and os.name == "nt",
                         "git 저장소·Windows(대소문자 무시 파일시스템)에서만")
    def test_restore_head_case_insensitive(self):
        # 대소문자만 다른 --restore-head도 Git의 정확한 경로로 맞춰 HEAD 내용을 복사한다(Codex 최종 재검토)
        tmp = tempfile.mkdtemp(prefix="hazop-snap-")
        self.addCleanup(shutil.rmtree, tmp, True)
        dest = os.path.join(tmp, "s")
        self.assertEqual(self.ms.main(["--dest", dest, "--restore-head", "PACKAGING/README.md"]), 0)
        with open(os.path.join(dest, "SNAPSHOT.json"), encoding="utf-8") as fh:
            m = json.load(fh)
        self.assertEqual(m["restore_head"], ["packaging/README.md"])
        self.assertEqual([e["source"] for e in m["files"] if e["path"] == "packaging/README.md"], ["head"])


class FlowHelperTest(unittest.TestCase):
    """packaging/w4_flow.py 판정 함수(빌드 없이): 자원 루트가 묶음 밖으로 빠지는 경우(예: 저장소 폴백)를 잡는다."""

    @classmethod
    def setUpClass(cls):
        cls.wf = _load("packaging/w4_flow.py", "hazop_w4_flow")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-flow-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_root_problems(self):
        b, w = os.path.join(self.tmp, "HAZOP", "_internal"), os.path.join(self.tmp, "work")
        self.assertEqual(self.wf.root_problems(True, b, b + os.sep, w), [])
        self.assertTrue(self.wf.root_problems(False, b, b, w))                    # 개발 실행
        self.assertTrue(self.wf.root_problems(True, b, REPO_ROOT, w))             # 자원 루트가 저장소로 폴백
        self.assertTrue(self.wf.root_problems(True, b, b, os.path.join(b, "w")))  # 작업 루트가 묶음 안
        self.assertTrue(self.wf.root_problems(True, b, b, self.tmp))              # 작업 루트가 묶음을 포함
        self.assertFalse(self.wf.within(_other_drive(b), b))

    def test_input_file_problems(self):
        b = os.path.join(self.tmp, "_internal")
        rel = paths.folder_rel("patterns") + "/p.json"
        p = os.path.join(b, *rel.split("/"))
        os.makedirs(os.path.dirname(p))
        with open(p, "w", encoding="utf-8") as fh:
            fh.write('{"a": 1}')
        rec = [{"role": "patterns", "path": rel, "sha256": self.wf.sha_text_file(p)}]
        expect = {rel: self.wf.sha_file(p)}
        self.assertEqual(self.wf.input_file_problems(rec, ("patterns",), b, b, expect), [])
        self.assertTrue(self.wf.input_file_problems(rec, ("patterns",), b, b, {rel: "0" * 64}))  # 빌드 원본과 다름
        self.assertTrue(self.wf.input_file_problems(rec, ("patterns", "risk_criteria"), b, b, expect))  # 기록 누락
        outside = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.dirname(os.path.join(outside, *rel.split("/"))))
        shutil.copyfile(p, os.path.join(outside, *rel.split("/")))
        self.assertTrue(self.wf.input_file_problems(rec, ("patterns",), outside, b, expect))  # 묶음 밖에서 읽음
        self.assertEqual(self.wf.datas_problems(b, expect), [])
        self.assertTrue(self.wf.datas_problems(b, dict(expect, **{"없는/파일.json": "0" * 64})))

    def test_resource_path_problems(self):
        b = os.path.join(self.tmp, "_internal")
        pat = paths.folder_rel("patterns") + "/p.json"
        for rel in (pat, "기획서/g.md"):
            p = os.path.join(b, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(rel)
        expect = {r: self.wf.sha_file(os.path.join(b, *r.split("/"))) for r in (pat, "기획서/g.md")}
        res = paths.resolve_rel
        self.assertEqual(self.wf.resource_path_problems({"patterns": pat}, "기획서/g.md", b, b, expect, res), [])
        self.assertTrue(self.wf.resource_path_problems({"patterns": pat}, "기획서/g.md", REPO_ROOT,
                                                       b, expect, res))  # 자원 루트가 저장소로 폴백
        self.assertTrue(self.wf.resource_path_problems({"patterns": "../x.json"}, "기획서/g.md", b, b, expect, res))

    def test_main_stops_at_first_failed_check(self):
        """묶음 datas 해시가 틀리면 그 자리에서 끝난다: 작업 루트에 아무것도 복사하지 않고 이후 단계도 없다."""
        bundle, work = os.path.join(self.tmp, "HAZOP", "_internal"), os.path.join(self.tmp, "work")
        os.makedirs(bundle)
        os.makedirs(work)
        expect, result = os.path.join(self.tmp, "expect.json"), os.path.join(self.tmp, "r.json")
        with open(expect, "w", encoding="utf-8") as fh:
            json.dump({paths.folder_rel("patterns") + "/없음.json": "0" * 64}, fh)
        env = _clean_env(HAZOP_WORK_ROOT=work)
        with mock.patch.dict(os.environ, env, clear=True), FrozenMock(bundle):
            rc = self.wf.main(["--samples", os.path.join(self.tmp, "없는-샘플"), "--expect", expect,
                               "--result", result])
        self.assertEqual(rc, 1)
        res = data.read_json(result)
        self.assertEqual(list(res["steps"]), ["work_root_env", "roots", "bundle-datas"])
        self.assertEqual(res["failures"], ["bundle-datas"])
        self.assertEqual(os.listdir(work), [])
        # 개발 실행(묶음 아님)이면 루트 검사에서 바로 끝난다
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.wf.main(["--samples", self.tmp, "--expect", expect, "--result", result]), 1)
        self.assertEqual(data.read_json(result)["failures"], ["roots"])
        self.assertEqual(os.listdir(work), [])


class RuntimeLogTest(unittest.TestCase):
    """packaging/rthook_applog.py: 개발 실행에서는 아무것도 설치하지 않고, install()은 로그·미처리 예외를 남긴다."""

    def test_install_logs_unhandled_exception(self):
        import logging
        root = logging.getLogger()
        saved = (sys.excepthook, sys.stdout, sys.stderr, list(root.handlers), root.level)
        mod = _load("packaging/rthook_applog.py", "hazop_rthook_applog")
        self.assertIs(sys.excepthook, saved[0])  # frozen이 아니면 설치하지 않음
        tmp = tempfile.mkdtemp(prefix="hazop-log-")
        self.addCleanup(shutil.rmtree, tmp, True)
        calls = []
        try:
            sys.excepthook = lambda *a: calls.append(a)
            path = mod.install(os.path.join(tmp, "logs"))
            try:
                raise RuntimeError("w4-test-error")
            except RuntimeError:
                sys.excepthook(*sys.exc_info())
            logging.getLogger("hazop.test").warning("경고 기록")
        finally:
            for h in root.handlers[:]:
                if h not in saved[3]:
                    root.removeHandler(h)
                    h.stream.close()
            root.setLevel(saved[4])
            sys.excepthook, sys.stdout, sys.stderr = saved[:3]
        self.assertEqual(len(calls), 1)  # 이전 훅도 부름
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("시작 pid=", text)
        self.assertIn("RuntimeError: w4-test-error", text)
        self.assertIn("경고 기록", text)

    def test_previous_hook_called_when_logging_fails(self):
        import logging
        root = logging.getLogger()
        saved = (sys.excepthook, sys.stdout, sys.stderr, list(root.handlers), root.level)
        mod = _load("packaging/rthook_applog.py", "hazop_rthook_applog2")
        tmp = tempfile.mkdtemp(prefix="hazop-log-")
        self.addCleanup(shutil.rmtree, tmp, True)
        calls = []
        try:
            sys.excepthook = lambda *a: calls.append(a)
            mod.install(os.path.join(tmp, "logs"))
            with mock.patch("logging.getLogger", side_effect=RuntimeError("로그 실패")):
                try:
                    raise ValueError("원래 예외")
                except ValueError:
                    sys.excepthook(*sys.exc_info())
        finally:
            for h in root.handlers[:]:
                if h not in saved[3]:
                    root.removeHandler(h)
                    h.stream.close()
            root.setLevel(saved[4])
            sys.excepthook, sys.stdout, sys.stderr = saved[:3]
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], ValueError)


if __name__ == "__main__":
    unittest.main()
