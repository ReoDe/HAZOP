"""패키징 대비 테스트(docs/2026-11-05-packaging W3, 기획서/인터페이스.md §7.1·§8 '패키징 대비' 행).

1) hazop/paths.py 공개 API 하위 호환: 기존 이름·인자가 그대로 있다(추가만 허용).
2) hazop/app/data.py의 scripts/ importlib 로딩 경로: 개발 실행은 저장소, 묶인 실행은 묶음 폴더(sys._MEIPASS).
   묶인 실행은 빌드하지 않고 sys.frozen·sys._MEIPASS를 패치해 모의한다. 이 테스트의 통과는 경로 선택만 검증하며,
   실제 실행 파일의 의존성(hiddenimports)·자료(datas) 포함·기동 성공을 보장하지 않는다(실빌드 확인은 W4).
3) HAZOP_RESOURCE_ROOT·HAZOP_WORK_ROOT를 서로 다른 임시 폴더로 바꿔 ①~⑤ 흐름(등록·추출·그래프 → 뷰어 → 지식그래프 →
   분석 → 검토 저장·Excel 출력)을 화면이 쓰는 함수로 실행한다. 자원 루트와 저장소의 출력/·자료저장소/는 바뀌지 않는다.
4) W4: scripts/build_package.py의 datas 목록·spec 원문을 빌드 없이 검사한다(코드의 경로 상수와 대조).
실행: python -m unittest discover -s tests. 임시 폴더만 쓴다. 네트워크·AI 호출 없음(고정 응답).
"""

import glob
import hashlib
import inspect
import json
import os
import shutil
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

ENV_KEYS = (paths.ENV_RESOURCE_ROOT, paths.ENV_WORK_ROOT, paths.ENV_STORE_ROOT)
SAMPLE_DIR = os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플")
KG_SAMPLE = os.path.join(REPO_ROOT, "데이터", "지식", "SNP-SAMPLE")
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
                self.assertEqual(paths.work_root(), os.path.join("C:/L", "HAZOP") if bundle else REPO_ROOT)


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
        with FrozenMock(bundles[0]):
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
        self.assertEqual(data.SCRIPT_NAMES, ("extract_drawio", "build_graph"))


# ---------------------------------------------------------------- 3) 자원 루트·작업 루트 분리 ①~⑤
class SplitRootsFlowTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-pkg-flow-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.res, self.work = os.path.join(self.tmp, "res"), os.path.join(self.tmp, "work")
        region = data.read_json(REGION_FILE)
        # 자원 루트: 기준 자료 4종·기법 지침서·샘플 도면(읽기 전용)
        for rel in list(region["inputs"].values()) + ["기획서/HAZOP기법지침.md"]:
            os.makedirs(os.path.dirname(os.path.join(self.res, rel)), exist_ok=True)
            shutil.copyfile(os.path.join(REPO_ROOT, rel), os.path.join(self.res, rel))
        drawio = [p for p in glob.glob(os.path.join(SAMPLE_DIR, "*", "*.drawio")) if "SNP-M-102" in p][0]
        self.sample = os.path.join(self.res, "참고자료", "샘플", "P-102.drawio")
        os.makedirs(os.path.dirname(self.sample))
        shutil.copyfile(drawio, self.sample)
        shutil.copyfile(glob.glob(os.path.join(os.path.dirname(drawio), "*.drawio.svg"))[0], self.sample + ".svg")
        # 작업 루트: 구간 JSON·고정 응답·분석용 그래프·지식 입력(사용자 데이터)
        self.region_path = os.path.join(self.work, "데이터", "구간", os.path.basename(REGION_FILE))
        os.makedirs(os.path.dirname(self.region_path))
        shutil.copyfile(REGION_FILE, self.region_path)
        self.fixed = os.path.join(self.work, "데이터", "고정응답", os.path.basename(FIXED_DIR))
        shutil.copytree(FIXED_DIR, self.fixed)
        gpath = os.path.join(self.work, region["graph_ref"]["graph_file"])
        os.makedirs(os.path.dirname(gpath))
        with open(gpath, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(GRAPH, fh, ensure_ascii=False, indent=2)
        shutil.copytree(KG_SAMPLE, os.path.join(self.work, "데이터", "지식", "SNP-SAMPLE"))
        self.region = region

    def test_flow_1_to_5_with_split_roots(self):
        res_before = _tree(self.res)
        repo_before = {d: _names(os.path.join(REPO_ROOT, d)) for d in ("출력", "자료저장소")}
        env = _clean_env(HAZOP_RESOURCE_ROOT=self.res, HAZOP_WORK_ROOT=self.work)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.dict(data._script_cache, {}, clear=True):
            self.assertEqual((paths.resource_root(), paths.work_root()), (self.res, self.work))
            store = paths.store_root()
            self.assertEqual(store, os.path.join(self.work, "자료저장소"))

            # ① 등록 → 추출 → 그래프
            reg = registry.register(self.sample, "p", store_root=store, actor="tester", now=lambda: T,
                                    metadata={"drawing_number": "SNP-M-102", "reason": "패키징 검사"})
            self.assertEqual(reg["outcome"], "registered", reg.get("notes"))
            rows = data.list_registrations()
            self.assertEqual(len(rows), 1)
            out = data.extract_and_graph(rows[0]["path"])
            self.assertTrue(out["extract_dir"].startswith(os.path.join(self.work, "출력", "추출")))
            self.assertTrue(out["graph_dir"].startswith(os.path.join(self.work, "출력", "그래프")))
            al = out["extraction"]["coordinate_system"]["svg_alignment"]
            self.assertEqual(al["source"], "registered_derived")
            row = data.list_registrations()[0]
            self.assertTrue(row["extracted"] and row["graphed"])

            # ② 추출 목록·뷰어 HTML(SVG는 작업 루트 안 저장 루트에서)
            names = [e["name"] for e in data.list_extractions()]
            self.assertEqual(names, [row["extract_name"]])
            info = data.viewer_html_for(names[0])
            self.assertIsNone(info["error"])
            self.assertTrue(info["html"].startswith(os.path.join(self.work, "출력", "뷰어")))

            # ③ 지식그래프: 작업 루트의 지식 입력으로 빌드 → 화면 데이터·HTML(템플릿·vendor는 패키지 안)
            kdir = os.path.join(paths.work_path("데이터", "지식"), "SNP-SAMPLE")
            knowledge = kg_inputs.load_knowledge(os.path.join(kdir, "knowledge_nodes.csv"),
                                                 os.path.join(kdir, "knowledge_links.csv"), "SNP-SAMPLE")
            graphs = kg_screen.load_graphs(paths.output_root("그래프"))
            kg = kg_build.build_kg(knowledge, [g for _, g in graphs.values()])
            kg_out = paths.output_root("지식그래프")
            kg_build.write_outputs(paths.safe_join(kg_out, paths.safe_name(kg["kg_id"])), knowledge, kg)
            roots = kg_screen.list_kg_roots(kg_out)
            self.assertEqual([r[0] for r in roots], [kg["kg_id"]])
            _, loaded = kg_build.load_outputs(roots[0][1])
            self.assertEqual(loaded["kg_version"], kg["kg_version"])
            _, graph = next(iter(graphs.values()))
            sdata = kg_screen.screen_data(loaded, graph, kg_screen.load_regions(paths.work_path("데이터", "구간")),
                                          kg_screen.read_candidates(kdir))
            self.assertTrue(sdata["nodes"])
            html = kg_screen.write_html(paths.output_root("뷰어", "kg-test.html"), kg_screen.build_html(sdata))
            self.assertTrue(html.startswith(self.work))

            # ④ 분석(고정 응답): 기준 자료는 자원 루트, 구간·그래프·출력은 작업 루트
            self.assertEqual(data.list_regions(), [self.region_path])
            res = api.run_analysis(self.region_path, response_dir=self.fixed, run_id="analysis-pkg")
            self.assertEqual(res["status"], "passed", res["blockers"])
            self.assertEqual(res["run_dir"], os.path.join(self.work, "출력", "분석", self.region["region_id"],
                                                          "analysis-pkg"))
            c = res["doc"]["validation"]["counts"]
            self.assertEqual((c["candidates"], c["scenarios"], c["risk_proposed"],
                              c["design_improvement_candidates"]), (44, 14, 6, 11))
            self.assertEqual(data.list_runs(self.region["region_id"]), [res["run_dir"]])
            self.assertEqual(data.current_graph(self.region)["graph_version"], res["doc"]["graph_ref"]["graph_version"])
            self.assertEqual(len(data.candidate_rows(res["doc"])), 44)

            # ④ 음성: 자원 루트에 지침서만 있고 기준 자료 4종이 없으면 저장소 자료로 대체하지 않고 입력 오류로 멈춘다
            #   (run.load_inputs가 resource_root 대신 저장소 루트를 쓰는 회귀를 잡는다)
            partial = os.path.join(self.tmp, "res_guide_only")
            os.makedirs(os.path.join(partial, "기획서"))
            shutil.copyfile(os.path.join(self.res, "기획서", "HAZOP기법지침.md"),
                            os.path.join(partial, "기획서", "HAZOP기법지침.md"))
            with mock.patch.dict(os.environ, {paths.ENV_RESOURCE_ROOT: partial}):
                with self.assertRaises(run_mod.InputError) as cm:
                    api.run_analysis(self.region_path, response_dir=self.fixed, run_id="analysis-noresource")
            self.assertIn("candidate_catalog 파일 없음", str(cm.exception))
            self.assertFalse(os.path.exists(os.path.join(self.work, "출력", "분석", self.region["region_id"],
                                                         "analysis-noresource")))

            # ⑤ 검토 저장(작업 루트 안 저장 루트) → Excel 출력(작업 루트 출력/워크시트)
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
            ex = export_worksheet(res["run_dir"], store, paths.output_root("워크시트"), now=T)
            files = glob.glob(os.path.join(self.work, "출력", "워크시트", "**", "*.xlsx"), recursive=True)
            self.assertEqual(len(files), 1, ex)

        self.assertEqual(_tree(self.res), res_before)  # 자원 루트는 읽기만
        self.assertEqual({d: _names(os.path.join(REPO_ROOT, d)) for d in ("출력", "자료저장소")}, repo_before)


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
        want |= set(data.read_json(REGION_FILE)["inputs"].values())  # 기준 자료 4종(자원 루트)
        self.assertEqual(want - self.srcs, set())
        for src, dest in self.datas:  # 묶음 안에서도 저장소와 같은 상대 위치
            self.assertEqual(dest, os.path.dirname(src), src)
            self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, src)), src)

    def test_datas_scope(self):
        """참고자료/ 샘플은 넣지 않고(D5안), .py는 화면이 읽는 두 스크립트뿐, 데이터는 3종 폴더만."""
        self.assertFalse([s for s in self.srcs if s.startswith("참고자료/")])
        self.assertEqual(sorted(s for s in self.srcs if s.endswith(".py")),
                         ["scripts/build_graph.py", "scripts/extract_drawio.py"])
        self.assertEqual({s.split("/")[1] for s in self.srcs if s.startswith("데이터/")}, {"이탈후보", "기준표", "패턴"})
        self.assertFalse([s for s in self.srcs if "__pycache__" in s])

    def test_spec_text(self):
        import ast
        for with_check in (False, True):
            text = self.bp.spec_text(with_check=with_check)
            ast.parse(text)
            self.assertIn("collect_submodules('hazop')", text)
            self.assertIn("EXCLUDES = ['anthropic', 'httpx', 'pdfplumber']", text)
            self.assertIn("name='HAZOP', console=False, upx=False", text)
            self.assertIn("scripts/run_app.py", text)
            self.assertEqual("HAZOP-check" in text, with_check)
            self.assertIn("COLLECT(*parts, upx=False, name=%r)" % ("HAZOP-verify" if with_check else "HAZOP"), text)
            self.assertIn("runtime_hooks=[os.path.join(REPO, 'packaging/rthook_applog.py')]", text)
            self.assertEqual(text.count("keep_warn("), 3 if with_check else 2)  # 정의 1 + Analysis별 복사
            ns = {}
            exec(text.split("from PyInstaller")[0] + "\n".join(
                ln for ln in text.splitlines() if ln.startswith(("REPO =", "DATAS ="))), ns)
            self.assertEqual(ns["REPO"], REPO_ROOT)
            self.assertEqual(len(ns["DATAS"]), len(self.datas))
            for src, dest in ns["DATAS"]:
                self.assertTrue(os.path.isfile(src), src)

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
        self.assertEqual(listed["excluded_dirs"], ["참고자료"])

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
        exec(text.split("from PyInstaller")[0] + "\n".join(
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
        rel = "데이터/패턴/p.json"
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
        os.makedirs(os.path.join(outside, "데이터", "패턴"))
        shutil.copyfile(p, os.path.join(outside, *rel.split("/")))
        self.assertTrue(self.wf.input_file_problems(rec, ("patterns",), outside, b, expect))  # 묶음 밖에서 읽음
        self.assertEqual(self.wf.datas_problems(b, expect), [])
        self.assertTrue(self.wf.datas_problems(b, dict(expect, **{"없는/파일.json": "0" * 64})))

    def test_resource_path_problems(self):
        b = os.path.join(self.tmp, "_internal")
        for rel in ("데이터/패턴/p.json", "기획서/g.md"):
            p = os.path.join(b, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(rel)
        expect = {r: self.wf.sha_file(os.path.join(b, *r.split("/"))) for r in ("데이터/패턴/p.json", "기획서/g.md")}
        self.assertEqual(self.wf.resource_path_problems({"patterns": "데이터/패턴/p.json"}, "기획서/g.md", b, b,
                                                        expect), [])
        self.assertTrue(self.wf.resource_path_problems({"patterns": "데이터/패턴/p.json"}, "기획서/g.md", REPO_ROOT,
                                                       b, expect))  # 자원 루트가 저장소로 폴백
        self.assertTrue(self.wf.resource_path_problems({"patterns": "../x.json"}, "기획서/g.md", b, b, expect))

    def test_main_stops_at_first_failed_check(self):
        """묶음 datas 해시가 틀리면 그 자리에서 끝난다: 작업 루트에 아무것도 복사하지 않고 이후 단계도 없다."""
        bundle, work = os.path.join(self.tmp, "HAZOP", "_internal"), os.path.join(self.tmp, "work")
        os.makedirs(bundle)
        os.makedirs(work)
        expect, result = os.path.join(self.tmp, "expect.json"), os.path.join(self.tmp, "r.json")
        with open(expect, "w", encoding="utf-8") as fh:
            json.dump({"데이터/패턴/없음.json": "0" * 64}, fh)
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
