"""패키징 대비 테스트(docs/2026-11-05-packaging W3, 기획서/인터페이스.md §7.1·§8 '패키징 대비' 행).

1) hazop/paths.py 공개 API 하위 호환: 기존 이름·인자가 그대로 있다(추가만 허용).
2) hazop/app/data.py의 scripts/ importlib 로딩 경로: 개발 실행은 저장소, 묶인 실행은 묶음 폴더(sys._MEIPASS).
   묶인 실행은 빌드하지 않고 sys.frozen·sys._MEIPASS를 패치해 모의한다. 이 테스트의 통과는 경로 선택만 검증하며,
   실제 실행 파일의 의존성(hiddenimports)·자료(datas) 포함·기동 성공을 보장하지 않는다(실빌드 확인은 W4).
3) HAZOP_RESOURCE_ROOT·HAZOP_WORK_ROOT를 서로 다른 임시 폴더로 바꿔 ①~⑤ 흐름(등록·추출·그래프 → 뷰어 → 지식그래프 →
   분석 → 검토 저장·Excel 출력)을 화면이 쓰는 함수로 실행한다. 자원 루트와 저장소의 출력/·자료저장소/는 바뀌지 않는다.
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


if __name__ == "__main__":
    unittest.main()
