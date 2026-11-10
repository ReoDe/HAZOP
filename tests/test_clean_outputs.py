"""scripts/clean_outputs.py(출력 정리)와 scripts/run_samples.py 출력 경로(output/samples/) 검사.
임시 폴더에서만 실행한다(실제 output/·store/·설정 파일은 쓰지 않음)."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import clean_outputs  # noqa: E402
from hazop import paths  # noqa: E402

D_RUN, D_KG, D_EX, D_CMP, D_GRAPH, D_VIEW, D_SAMPLES, D_ARCH = (paths.output_name(n) for n in (
    "analysis", "knowledge-graph", "extract", "evaluation-compare", "graph", "viewer", "samples", "archive"))
REGION = "region-X"
V_CUR, V_OLD, V_REF = "v-" + "a" * 12, "v-" + "b" * 12, "v-" + "c" * 12


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def _names(root):
    return sorted(os.path.relpath(os.path.join(d, f), root).replace("\\", "/")
                  for d, _, fs in os.walk(root) for f in fs) if os.path.isdir(root) else []


def _junction(link, target):
    """Windows 정션을 만든다. 만들 수 없으면 테스트 건너뜀."""
    try:
        import _winapi
        _winapi.CreateJunction(target, link)
    except (ImportError, AttributeError, OSError) as exc:
        raise unittest.SkipTest("정션을 만들 수 없음: %s" % exc)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = paths.output_in(self.tmp)
        self.store = paths.folder_in(self.tmp, "store")
        appdata = os.path.join(self.tmp, "appdata")  # 실제 설정 파일을 읽지 않게
        patcher = mock.patch.dict(os.environ, {"APPDATA": appdata})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def plan(self, keep=5):
        return clean_outputs.make_plan(self.out, self.store, keep)

    def moved(self, keep=5):
        return {i["rel"] for i in self.plan(keep)["move"]}

    def run_main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = clean_outputs.main(["--out-root", self.out, "--store-root", self.store] + list(args))
        return rc, buf.getvalue()


class CleanOutputsTest(Base):
    def setUp(self):
        super().setUp()
        # 분석 실행 7개(시각 순 r0..r6). r1은 검토 기록이 있고 V_REF 지식그래프를 참조한다.
        self.runs = ["analysis-2026110%dT000000Z-aaaaaa" % i for i in range(7)]
        for i, run_id in enumerate(self.runs):
            versions = {"knowledge_graph": {"id": "kg-S", "version": V_REF}} if i == 1 else {}
            _write(os.path.join(self.out, D_RUN, REGION, run_id, "analysis.json"),
                   {"analysis_run_id": run_id, "region_ref": {"region_id": REGION},
                    "analysis_run": {"created_at": "2026-11-0%dT00:00:00Z" % i, "versions": versions}})
        os.makedirs(os.path.join(self.out, D_RUN, REGION, "no-analysis"))  # analysis.json 없는 폴더
        self.review = os.path.join(self.store, "reviews", REGION, self.runs[1], "D-1", "v1.json")
        _write(self.review, {"x": 1})
        # 지식그래프(폴더 이름 kgdir, kg_id kg-S): current = V_CUR, V_OLD·V_REF(blocked), 옛 경로 파일, screen/algo 캐시
        self.kg = os.path.join(self.out, D_KG, "kgdir")
        _write(os.path.join(self.kg, "current.json"), {"kg_id": "kg-S", "kg_version": V_CUR})
        for v in (V_CUR, V_OLD, V_REF):
            status = "passed" if v == V_CUR else "blocked"
            _write(os.path.join(self.kg, v, "knowledge_graph.json"), {"kg_version": v, "validation": {"status": status}})
            _write(os.path.join(self.kg, "screen", v, "g.html"), {})
            _write(os.path.join(self.kg, "algo", v, "r.json"), {})
        _write(os.path.join(self.kg, "knowledge.json"), {})
        _write(os.path.join(self.kg, "knowledge_graph.json"), {})
        _write(os.path.join(self.out, D_KG, "p1_performance.json"), {})
        _write(os.path.join(self.out, D_KG, "kg-nopointer", V_OLD, "knowledge_graph.json"), {})
        _write(os.path.join(self.out, D_EX, "A", "extraction.json"), {})

    def test_plan(self):
        plan = self.plan()
        move = {i["rel"] for i in plan["move"]}
        keep = {r for r, _ in plan["keep"]}
        a = D_RUN + "/%s/" % REGION
        # 최근 5개(r2..r6) 보존, r1은 검토 기록으로 보존, r0만 후보
        self.assertEqual({r for r in move if r.startswith(a)}, {a + self.runs[0]})
        self.assertIn(a + self.runs[1], keep)
        self.assertTrue(all(a + r in keep for r in self.runs[2:]))
        self.assertEqual(plan["skipped"], [])
        k = D_KG + "/kgdir/"
        # V_REF는 보존하는 r1이 kg_id(kg-S)로 참조(폴더 이름 kgdir와 달라도 보존), V_CUR는 포인터. V_OLD만 후보
        self.assertEqual({r for r in move if r.startswith(k)},
                         {k + "knowledge.json", k + "knowledge_graph.json", k + V_OLD,
                          k + "screen/" + V_OLD, k + "algo/" + V_OLD})
        self.assertTrue({k + V_CUR, k + V_REF} <= keep)
        self.assertFalse(any("kg-nopointer" in r or "p1_performance" in r or r.startswith(D_EX) for r in move))

    def test_unreadable_run_holds_kg_versions(self):
        # 읽을 수 없는 실행이 있으면 버전 폴더는 보존(사유 표시), 옛 경로 파일은 그대로 후보
        bad = os.path.join(self.out, D_RUN, REGION, "analysis-broken")
        os.makedirs(bad)
        with open(os.path.join(bad, "analysis.json"), "w", encoding="utf-8") as fh:
            fh.write("{깨짐")
        plan = self.plan()
        k = D_KG + "/kgdir/"
        self.assertEqual([r for r, _ in plan["skipped"]], [D_RUN + "/%s/analysis-broken" % REGION])
        self.assertEqual({i["rel"] for i in plan["move"] if i["rel"].startswith(k)},
                         {k + "knowledge.json", k + "knowledge_graph.json"})
        keep = dict(plan["keep"])
        for rel in (k + V_OLD, k + "screen/" + V_OLD, k + "algo/" + V_OLD):
            self.assertEqual(keep[rel], "참조를 확인할 수 없는 분석 실행 있음")
        self.assertIn(D_RUN + "/%s/%s" % (REGION, self.runs[0]), {i["rel"] for i in plan["move"]})

    def test_sort_key_falls_back_to_folder_name(self):
        # created_at이 없으면 폴더 이름으로 정렬(docstring과 같음)
        for run_id in self.runs:
            p = os.path.join(self.out, D_RUN, REGION, run_id, "analysis.json")
            doc = clean_outputs._read_json(p)
            del doc["analysis_run"]["created_at"]
            _write(p, doc)
        self.assertEqual({r for r in self.moved() if r.startswith(D_RUN + "/")}, {D_RUN + "/%s/%s" % (REGION, self.runs[0])})

    def test_compare_json_target_only(self):
        # 폴더 이름은 다르고 보고서 JSON의 target만 실행을 가리켜도 보존
        shutil.rmtree(os.path.join(self.store, "reviews"))
        _write(os.path.join(self.out, D_CMP, "other", "dir", "compare-c-v1-draft-t.json"),
               {"target": {"analysis_run_id": self.runs[0], "region_ref": {"region_id": REGION}}})
        keep = dict(self.plan()["keep"])
        self.assertEqual(keep[D_RUN + "/%s/%s" % (REGION, self.runs[0])], "평가 비교 보고서가 참조함")

    def test_kg_id_mismatch_not_protected(self):
        # 실행이 다른 kg_id를 참조하면 이 kg의 V_REF는 보호되지 않는다
        p = os.path.join(self.out, D_RUN, REGION, self.runs[1], "analysis.json")
        doc = clean_outputs._read_json(p)
        doc["analysis_run"]["versions"]["knowledge_graph"]["id"] = "kg-OTHER"
        _write(p, doc)
        self.assertIn(D_KG + "/kgdir/" + V_REF, self.moved())

    def test_keep_and_reference_drop(self):
        shutil.rmtree(os.path.join(self.store, "reviews"))
        move = self.moved()
        self.assertIn(D_RUN + "/%s/%s" % (REGION, self.runs[1]), move)
        self.assertIn(D_KG + "/kgdir/" + V_REF, move)
        self.assertFalse(any(r.startswith(D_RUN + "/") for r in self.moved(7)))

    def test_region_folder_name_differs_from_region_id(self):
        # 구간 폴더 이름(regdir)과 region_id(region-Y)가 달라도 region_id 기준 검토 기록으로 보존
        runs = ["analysis-2026120%dT000000Z-bbbbbb" % i for i in range(3)]
        for i, run_id in enumerate(runs):
            _write(os.path.join(self.out, D_RUN, "regdir", run_id, "analysis.json"),
                   {"analysis_run_id": run_id, "region_ref": {"region_id": "region-Y"},
                    "analysis_run": {"created_at": "2026-12-0%dT00:00:00Z" % i}})
        _write(os.path.join(self.store, "reviews", "region-Y", runs[0], "D-1", "v1.json"), {})
        move = self.moved(1)
        self.assertNotIn(D_RUN + "/regdir/" + runs[0], move)
        self.assertIn(D_RUN + "/regdir/" + runs[1], move)

    def test_compare_and_settings_references(self):
        shutil.rmtree(os.path.join(self.store, "reviews"))
        _write(os.path.join(self.out, D_CMP, REGION, self.runs[0], "compare-c-v1-draft-t.json"),
               {"target": {"analysis_run_id": self.runs[0]}})
        _write(paths.settings_path(), {"recent_runs": [os.path.join(self.out, D_RUN, REGION, self.runs[1])]})
        keep = dict(self.plan()["keep"])
        self.assertEqual(keep[D_RUN + "/%s/%s" % (REGION, self.runs[0])], "평가 비교 보고서가 참조함")
        self.assertEqual(keep[D_RUN + "/%s/%s" % (REGION, self.runs[1])], "설정 recent_runs가 참조함")

    def test_broken_settings_warns(self):
        os.makedirs(os.path.dirname(paths.settings_path()))
        with open(paths.settings_path(), "w", encoding="utf-8") as fh:
            fh.write("[1]")
        plan = self.plan()
        self.assertEqual(len(plan["warnings"]), 1)
        self.assertIn(D_RUN + "/%s/%s" % (REGION, self.runs[0]), {i["rel"] for i in plan["move"]})

    def test_previous_passed_protected(self):
        _write(os.path.join(self.kg, V_OLD, "knowledge_graph.json"),
               {"kg_version": V_OLD, "validation": {"status": "passed"}})
        self.assertIn(D_KG + "/kgdir/" + V_OLD, dict(self.plan()["keep"]))

    def test_dry_run_changes_nothing(self):
        before = _names(self.tmp)
        rc, text = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("dry-run", text)
        self.assertEqual(_names(self.tmp), before)

    def test_apply_moves_and_manifest(self):
        before = _names(self.tmp)
        plan = self.plan()
        manifest = clean_outputs.apply_plan(plan, self.out, self.store, "20261106T000000Z")
        dest = os.path.dirname(manifest)
        self.assertEqual(dest, os.path.join(self.out, D_ARCH, "20261106T000000Z"))
        doc = clean_outputs._read_json(manifest)
        self.assertEqual([m["original"] for m in doc["entries"]], [i["rel"] for i in plan["move"]])
        self.assertTrue(all(m["status"] == "moved" and m["reason"] and
                            m["archived"].startswith(D_ARCH + "/20261106T000000Z/") for m in doc["entries"]))
        self.assertEqual(len(_names(self.tmp)), len(before) + 1)  # 삭제 없음 + manifest
        for i in plan["move"]:
            self.assertFalse(os.path.exists(os.path.join(self.out, *i["rel"].split("/"))))
            self.assertTrue(os.path.exists(os.path.join(dest, *i["rel"].split("/"))))
        self.assertTrue(os.path.isfile(self.review))
        with self.assertRaises(ValueError):  # 같은 보관 폴더 재사용 거부
            clean_outputs.apply_plan(plan, self.out, self.store, "20261106T000000Z")

    def test_rename_failure_stops(self):
        plan = self.plan()
        real_rename, calls = os.rename, []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError("잠김")
            return real_rename(src, dst)

        with mock.patch.object(clean_outputs.os, "rename", flaky), self.assertRaises(OSError):
            clean_outputs.apply_plan(plan, self.out, self.store, "t1")
        self.assertEqual(len(calls), 2)  # 실패 뒤 더 진행하지 않음
        doc = clean_outputs._read_json(os.path.join(self.out, D_ARCH, "t1", "manifest.json"))
        self.assertEqual([e["status"] for e in doc["entries"]], ["moved", "failed"])
        self.assertEqual(doc["entries"][1]["original"], plan["move"][1]["rel"])
        for i in plan["move"][1:]:  # 실패한 항목과 나머지 원본은 그대로
            self.assertTrue(os.path.exists(os.path.join(self.out, *i["rel"].split("/"))))

    def test_pending_recorded_before_rename(self):
        plan = self.plan()
        manifest = os.path.join(self.out, D_ARCH, "t3", "manifest.json")
        real_rename, seen = os.rename, []

        def check(src, dst):
            seen.append(clean_outputs._read_json(manifest)["entries"][-1]["status"])
            return real_rename(src, dst)

        with mock.patch.object(clean_outputs.os, "rename", check):
            clean_outputs.apply_plan(plan, self.out, self.store, "t3")
        self.assertEqual(seen, ["pending"] * len(plan["move"]))

    def test_pre_record_failure_moves_nothing(self):
        plan = self.plan()
        real_write, calls = clean_outputs._write_manifest, []

        def fail_second(path, doc):
            calls.append(1)
            if len(calls) == 2:  # 첫 항목의 pending 기록
                raise OSError("디스크 가득")
            return real_write(path, doc)

        with mock.patch.object(clean_outputs, "_write_manifest", fail_second), \
                mock.patch.object(clean_outputs.os, "rename") as ren, self.assertRaises(OSError):
            clean_outputs.apply_plan(plan, self.out, self.store, "t4")
        ren.assert_not_called()
        self.assertTrue(all(os.path.exists(os.path.join(self.out, *i["rel"].split("/"))) for i in plan["move"]))

    def test_update_failure_leaves_pending(self):
        plan = self.plan()
        real_write, calls = clean_outputs._write_manifest, []

        def fail_third(path, doc):
            calls.append(1)
            if len(calls) == 3:  # 첫 항목 rename 뒤 moved 갱신
                raise OSError("디스크 가득")
            return real_write(path, doc)

        with mock.patch.object(clean_outputs, "_write_manifest", fail_third), self.assertRaises(OSError):
            clean_outputs.apply_plan(plan, self.out, self.store, "t5")
        dest = os.path.join(self.out, D_ARCH, "t5")
        doc = clean_outputs._read_json(os.path.join(dest, "manifest.json"))
        self.assertEqual([(e["original"], e["status"]) for e in doc["entries"]], [(plan["move"][0]["rel"], "pending")])
        self.assertTrue(os.path.exists(os.path.join(dest, *plan["move"][0]["rel"].split("/"))))  # 복구 가능
        self.assertTrue(os.path.exists(os.path.join(self.out, *plan["move"][1]["rel"].split("/"))))

    def test_main_reports_errors(self):
        with mock.patch.object(clean_outputs, "apply_plan", side_effect=ValueError("x")):
            self.assertEqual(self.run_main("--apply")[0], 2)
        with mock.patch.object(clean_outputs.os, "makedirs", side_effect=OSError("권한")):
            rc, text = self.run_main("--apply")
        self.assertEqual(rc, 1)
        self.assertIn("기록 파일 없음", text)
        self.assertNotIn("그때까지 기록", text)

    def test_recheck_before_move(self):
        plan = self.plan()
        # 계획 뒤 r0에 검토 기록이 생기고 current.json이 바뀜 -> 해당 항목은 건너뜀
        _write(os.path.join(self.store, "reviews", REGION, self.runs[0], "D-1", "v1.json"), {})
        _write(os.path.join(self.kg, "current.json"), {"kg_id": "kg-S", "kg_version": V_OLD})
        manifest = clean_outputs.apply_plan(plan, self.out, self.store, "t2")
        doc = clean_outputs._read_json(manifest)
        self.assertEqual(doc["entries"], [])
        self.assertEqual(len(doc["skipped"]), len(plan["move"]))
        self.assertTrue(os.path.isdir(os.path.join(self.out, D_RUN, REGION, self.runs[0])))
        self.assertTrue(os.path.isdir(os.path.join(self.kg, V_OLD)))

    def test_apply_refuses_outside_paths(self):
        for n, rel in enumerate((D_EX + "/A", D_RUN + "/../../" + os.path.basename(self.store))):
            with self.assertRaises(ValueError):
                clean_outputs.apply_plan({"move": [{"rel": rel, "reason": "x", "kind": "analysis_run",
                                                    "names": [], "regions": []}]}, self.out, self.store, "o%d" % n)
        self.assertTrue(os.path.isfile(self.review))
        self.assertTrue(os.path.isdir(os.path.join(self.out, D_EX, "A")))
        self.assertFalse(os.path.exists(os.path.join(self.out, D_ARCH)))

    def test_main_apply_and_args(self):
        rc, text = self.run_main("--keep", "6", "--apply")
        self.assertEqual(rc, 0, text)
        runs_left = sorted(os.listdir(os.path.join(self.out, D_RUN, REGION)))
        self.assertEqual(runs_left, sorted(self.runs[1:] + ["no-analysis"]))
        archived = os.listdir(os.path.join(self.out, D_ARCH))
        self.assertEqual(len(archived), 1)
        self.assertTrue(os.path.isdir(os.path.join(self.out, D_ARCH, archived[0], D_RUN, REGION, self.runs[0])))
        for bad in (["--keep", "0", "--out-root", self.out, "--store-root", self.store], ["--out-root", self.out]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                clean_outputs.main(bad)

    def test_apply_without_reviews_needs_flag(self):
        shutil.rmtree(os.path.join(self.store, "reviews"))
        before = _names(self.tmp)
        rc, text = self.run_main("--apply")
        self.assertEqual(rc, 2)
        self.assertEqual(_names(self.tmp), before)
        rc, text = self.run_main("--apply", "--no-review-records")
        self.assertEqual(rc, 0, text)
        self.assertFalse(os.path.exists(os.path.join(self.out, D_RUN, REGION, self.runs[0])))


class JunctionTest(Base):
    def test_junctions_refused(self):
        real = os.path.join(self.tmp, "real")
        _write(os.path.join(real, D_RUN, REGION, "analysis-1", "analysis.json"), {"analysis_run": {}})
        _write(os.path.join(real, D_RUN, REGION, "analysis-2", "analysis.json"), {"analysis_run": {}})
        os.makedirs(self.out)
        _junction(os.path.join(self.out, D_RUN), os.path.join(real, D_RUN))  # 기준 폴더가 정션
        kg = os.path.join(self.out, D_KG, "kg")
        _write(os.path.join(kg, "current.json"), {"kg_id": "kg", "kg_version": V_CUR})
        _write(os.path.join(kg, V_CUR, "knowledge_graph.json"), {"kg_version": V_CUR})
        _write(os.path.join(real, "screen", V_OLD, "g.html"), {})
        _junction(os.path.join(kg, "screen"), os.path.join(real, "screen"))  # screen/이 정션
        _write(os.path.join(real, "algo-old", "r.json"), {})
        os.makedirs(os.path.join(kg, "algo"))
        _junction(os.path.join(kg, "algo", V_OLD), os.path.join(real, "algo-old"))  # 버전 폴더가 정션
        plan = self.plan(1)
        self.assertEqual(plan["move"], [])
        skipped = {r for r, _ in plan["skipped"]}
        self.assertEqual(skipped, {D_RUN, D_KG + "/kg/screen", D_KG + "/kg/algo/" + V_OLD})

    def test_region_and_kg_root_junctions_refused(self):
        real = os.path.join(self.tmp, "real")
        for i in range(3):
            _write(os.path.join(real, "reg", "analysis-%d" % i, "analysis.json"), {"analysis_run": {}})
        _write(os.path.join(real, "kg", "current.json"), {"kg_id": "kg", "kg_version": V_CUR})
        _write(os.path.join(real, "kg", V_CUR, "knowledge_graph.json"), {"kg_version": V_CUR})
        _write(os.path.join(real, "kg", V_OLD, "knowledge_graph.json"), {"kg_version": V_OLD})
        _write(os.path.join(real, "kg", "knowledge.json"), {})
        os.makedirs(os.path.join(self.out, D_RUN))
        os.makedirs(os.path.join(self.out, D_KG))
        _junction(os.path.join(self.out, D_RUN, "reg"), os.path.join(real, "reg"))  # 구간 폴더가 정션
        _junction(os.path.join(self.out, D_KG, "kg"), os.path.join(real, "kg"))  # kg 루트가 정션
        plan = self.plan(1)
        self.assertEqual(plan["move"], [])
        self.assertEqual({r for r, _ in plan["skipped"]}, {D_RUN + "/reg", D_KG + "/kg"})


class RunSamplesOutRootTest(unittest.TestCase):
    """run_samples 결과는 <작업 루트>/출력/samples/ 아래에 쓰고 output/extract·그래프·뷰어는 건드리지 않는다."""

    def test_default_out_root(self):
        import run_samples
        tmp = tempfile.mkdtemp()
        try:
            work, store = os.path.join(tmp, "work"), os.path.join(tmp, "store")
            env = {paths.ENV_WORK_ROOT: work, paths.ENV_STORE_ROOT: store}
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
                rc = run_samples.main(["--store-root", store, "--by", "test"])
            self.assertEqual(rc, 0)
            out = paths.output_in(work)
            self.assertEqual(sorted(os.listdir(out)), [D_SAMPLES])
            ex = os.listdir(os.path.join(out, D_SAMPLES, D_EX))
            self.assertEqual(len(ex), 6)
            self.assertTrue(all(n.startswith("sample-project__") for n in ex))
            for n in ex:
                self.assertTrue(os.path.isfile(os.path.join(out, D_SAMPLES, D_GRAPH, n, "graph.json")))
                self.assertTrue(os.path.isfile(os.path.join(out, D_SAMPLES, D_VIEW, n + ".html")))
            self.assertTrue(os.path.isfile(os.path.join(out, D_SAMPLES, D_VIEW, "index.html")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
