"""0.1.x 작업 폴더를 만난 앱 시험(HZ-GOV-02 §6.6). 실행: python -m unittest tests.test_workroot_app

(1) 시작할 때 옛 배치를 찾으면 묻고, 승낙하면 복사해 옮긴 뒤에만 화면을 연다. 거절하거나 옮기지 못하면 옛 폴더를 그대로 두고
    알린 뒤 시작하지 않는다. 그동안 새 이름 폴더에는 아무것도 생기지 않는다.
(2) 옮긴 뒤 ④ 확정한 검토구간, ⑤ 결과, ⑥ 초기사건 그룹, 검토 기록, 도면 수정 기록, 추출 목록, 구간이 화면이 쓰는 함수로 그대로 읽힌다.
(3) 설정 파일에 적힌 옛 고정 응답 폴더(절대 경로)를 새 자리에서 찾는다.
"""

import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths, workroot  # noqa: E402
from hazop.app import startup  # noqa: E402
from scripts import check_work_root_counts as counts  # noqa: E402
from tests.test_workroot import make_old_root, tree  # noqa: E402

NEW_TOPS = sorted(now for _old, now in workroot.top_names())


def to_old_layout(root):
    """지금 배치의 작업 루트를 0.1.x 배치로 되돌려 놓는다(폴더 이름만 바꾼다). 옛 배치 자료를 지금 코드로 만들 때 쓴다."""
    for now, old in sorted(paths.work_names(), key=lambda r: len(r[0])):  # 윗폴더부터. 아랫폴더는 이미 옛 이름이 된 윗폴더 아래에 있다
        dst = os.path.join(root, *old.split("/"))
        src = os.path.join(os.path.dirname(dst), now.split("/")[-1])
        if os.path.isdir(src) and src != dst:
            os.rename(src, dst)


def new_layout_files(root):
    return [k for k, v in tree(root).items() if v is not None and k.split("/")[0] in NEW_TOPS]


class OfferTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hazop-offer-")
        self.addCleanup(tmp.cleanup)
        self.root = os.path.join(tmp.name, "HAZOP")
        make_old_root(self.root)
        self.before = tree(self.root)
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.root})
        env.start()
        self.addCleanup(env.stop)
        self.told = []

    def offer(self, answer=None, interactive=True, **kw):
        asked = []

        def ask(plan):
            asked.append(plan)
            return answer

        result = startup.offer_work_root_move(interactive, ask=ask, notify=lambda title, text: self.told.append((title, text)),
                                              run=kw.pop("run", workroot.apply), **kw)
        return result, asked

    def test_nothing_is_asked_on_a_fresh_or_already_moved_root(self):
        workroot.apply(self.root)
        self.assertEqual((None, []), self.offer(True))
        fresh = os.path.join(os.path.dirname(self.root), "fresh")
        os.makedirs(fresh)
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: fresh}):
            self.assertEqual((None, []), self.offer(True))
        self.assertEqual([], self.told)

    def test_yes_copies_then_lets_the_program_start(self):
        result, asked = self.offer(True)
        self.assertIsNone(result)
        self.assertEqual(1, len(asked))
        self.assertEqual(self.before["출력/그래프/SNP-M-102/graph.json"], tree(self.root)["output/graph/SNP-M-102/graph.json"])
        self.assertIn(workroot.KEEP_DIR, self.told[-1][1])
        self.assertEqual(self.root, paths.work_root())

    def test_no_leaves_everything_tells_the_user_and_does_not_start(self):
        result, asked = self.offer(False)
        self.assertEqual(startup.EXIT_OLD_LAYOUT, result)
        self.assertEqual(self.before, tree(self.root))
        self.assertEqual(1, len(self.told))
        for old, _now in workroot.top_names():
            self.assertIn(old, self.told[0][1])
        with self.assertRaises(paths.OldLayoutError):
            paths.work_root()

    def test_the_question_names_the_folders_and_the_size(self):
        _result, asked = self.offer(False)
        text = startup.move_question(asked[0])
        for old, _now in workroot.top_names():
            self.assertIn(old, text)
        self.assertIn(workroot.KEEP_DIR, text)

    def test_old_and_new_files_together_stop_without_asking_and_list_the_files(self):
        clash = os.path.join(self.root, "store", "p9", "x.json")
        os.makedirs(os.path.dirname(clash))
        with open(clash, "w", encoding="utf-8") as fh:
            fh.write("0.2.0에서 만든 것")
        before = tree(self.root)
        result, asked = self.offer(True)
        self.assertEqual((startup.EXIT_OLD_LAYOUT, []), (result, asked))
        self.assertEqual(before, tree(self.root))
        self.assertEqual(1, len(self.told))
        self.assertIn("store/p9/x.json", self.told[0][1])

    def test_non_interactive_start_never_moves_and_does_not_start(self):
        err = io.StringIO()
        result, asked = self.offer(True, interactive=False, err=err)
        self.assertEqual((startup.EXIT_OLD_LAYOUT, []), (result, asked))
        self.assertEqual(self.before, tree(self.root))
        self.assertIn("자료저장소", err.getvalue())

    def test_a_failed_move_is_reported_and_the_old_folders_stay(self):
        def fail(root, progress=None):
            raise workroot.MigrationError("디스크 여유가 모자랍니다.")

        result, _asked = self.offer(True, run=fail)
        self.assertEqual(startup.EXIT_OLD_LAYOUT, result)
        self.assertEqual(self.before, tree(self.root))
        self.assertIn("디스크 여유", self.told[-1][1])


class RunAppOldLayoutTest(unittest.TestCase):
    """scripts/run_app.main: 옛 배치 작업 루트에서는 옮기기 전에 창을 만들지 않고, 새 이름 폴더에 파일을 하나도 만들지 않는다."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("hazop_run_app_old", os.path.join(REPO_ROOT, "scripts", "run_app.py"))
        cls.ra = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ra)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-runapp-old-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "HAZOP")
        make_old_root(self.root)
        self.before = tree(self.root)
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.root, "QT_QPA_PLATFORM": "offscreen"})
        env.start()
        self.addCleanup(env.stop)
        self.settings = os.path.join(self.tmp, "settings.json")

    def test_declined_exits_before_the_window_and_writes_nothing(self):
        told = []
        with mock.patch.object(startup, "ask_move_dialog", return_value=False) as ask, \
                mock.patch.object(startup, "notify_running", lambda title, text: told.append(text)), \
                mock.patch("hazop.app.main_window.MainWindow") as win:
            self.assertEqual(startup.EXIT_OLD_LAYOUT, self.ra.main(["--settings", self.settings]))
        ask.assert_called_once()
        win.assert_not_called()
        self.assertEqual(1, len(told))
        self.assertEqual([], new_layout_files(self.root))
        self.assertEqual(self.before, {k: v for k, v in tree(self.root).items() if k in self.before})
        self.assertFalse(os.path.exists(os.path.join(self.root, startup.LOCK_NAME)), "잠금을 놓지 않음")

    def test_screenshots_exits_with_a_message_and_writes_nothing(self):
        err = io.StringIO()
        png = os.path.join(self.tmp, "png")
        with mock.patch("hazop.app.make_application") as make_app, mock.patch.object(sys, "stderr", err):
            self.assertEqual(startup.EXIT_OLD_LAYOUT, self.ra.main(["--screenshots", png, "--settings", self.settings]))
        make_app.assert_not_called()
        self.assertIn("migrate_names.py", err.getvalue())
        self.assertEqual(self.before, tree(self.root))
        self.assertFalse(os.path.exists(png))

    def test_accepted_moves_first_then_opens_the_window(self):
        order = []

        def moved(root):
            order.append("move")
            return workroot.apply(root)

        with mock.patch.object(startup, "ask_move_dialog", return_value=True), \
                mock.patch.object(startup, "run_move_dialog", moved), \
                mock.patch.object(startup, "notify_running", lambda title, text: order.append("told")), \
                mock.patch("hazop.app.main_window.MainWindow", side_effect=lambda *a, **kw: order.append("window") or self.fail_window()):
            with self.assertRaises(StopIteration):
                self.ra.main(["--settings", self.settings])
        self.assertEqual(["move", "told", "window"], order)
        self.assertEqual("done", workroot.make_plan(self.root).state)

    def fail_window(self):
        raise StopIteration  # 창을 만드는 자리까지 왔는지만 본다


class MovedRootIsReadByTheAppTest(unittest.TestCase):
    """지금 코드로 만든 자료를 0.1.x 배치로 되돌려 놓고, 옮긴 뒤 화면이 쓰는 함수로 읽은 것이 옮기기 전과 같은지 본다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-moved-")
        cls.root = os.path.join(paths.long_path(cls.tmp), "HAZOP")
        os.makedirs(cls.root)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", **{paths.ENV_WORK_ROOT: cls.root})
        env.pop(paths.ENV_STORE_ROOT, None)
        for args in (["scripts/extract_drawio.py", "--samples"], ["scripts/build_graph.py"],
                     ["scripts/seed_samples.py", "--work-root", cls.root],
                     ["scripts/analyze.py", "--run-id", "analysis-20261104T000000Z-moved"]):
            done = subprocess.run([sys.executable] + args, cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        cls.patch = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: cls.root})
        cls.patch.start()
        os.environ.pop(paths.ENV_STORE_ROOT, None)
        cls.fill()
        cls.read_before = cls.read()
        cls.counts_before = counts.collect(cls.root)
        to_old_layout(cls.root)
        cls.old_tree = tree(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def fill(cls):
        from hazop import review as rv
        from hazop.extract import corrections
        from hazop.graph import project
        from hazop.study import nodes
        from scripts import shoot_initiating
        run = rv.open_run(paths.output_root("analysis", "region-SNP-M-102-pzr", "analysis-20261104T000000Z-moved"))
        cid = "deviation-p86-d09"
        sid = [s["scenario_id"] for s in run["doc"]["scenarios"] if s["candidate_id"] == cid][0]
        risk = rv.make_risk_confirmation(run, 3, "강도 근거", 2, 2, "빈도 근거", ())
        record = rv.build_review(run, cid, "검토자A", "요약", [rv.scenario_decision(run, sid, "accept", "수용", "검토자A",
                                                                             risk_confirmation=risk)], [])
        rv.save_review(paths.store_root(), run, record)
        pg = project.load(project.UNREGISTERED_PROJECT)
        nodes.save(nodes.confirm(nodes.propose(pg), pg, "검토자(예시)"))
        pg, _ns, results = shoot_initiating.build_results()
        shoot_initiating.build_ie(pg, results)
        cls.corrections_path = corrections.store_path("SNP-M-999")
        os.makedirs(os.path.dirname(cls.corrections_path), exist_ok=True)
        with open(cls.corrections_path, "w", encoding="utf-8") as fh:
            fh.write('{"marker": "사람이 한 도면 수정(가상)"}')

    @classmethod
    def read(cls):
        """화면이 쓰는 함수로 읽은 내용."""
        from hazop.app import data, related
        from hazop.extract import corrections
        from hazop.ie import store as ie_store
        idx = related.DrawingIndex("SNP-M-102")
        doc, _ = ie_store.load(idx.graph.get("project_id"))
        with open(corrections.store_path("SNP-M-999"), encoding="utf-8") as fh:
            corr = fh.read()
        return {
            "extractions": sorted(e["name"] for e in data.list_extractions()),
            "regions": sorted(os.path.basename(p) for p in data.list_regions()),
            "node_set": (idx.node_set["status"], len(idx.node_set["nodes"])),
            "entries": sorted(e["cause"] for cell in idx.results["cells"] for e in cell["entries"]),
            "ie_confirmed": sorted(g["name"] for g in doc["groups"].values() if g.get("status") == "confirmed"),
            "ie_groups": len(doc["groups"]),
            "corrections": corr,
        }

    def test_1_before_the_move_nothing_is_read_or_written(self):
        from hazop.app import data
        for call in (data.list_extractions, data.list_regions, paths.store_root):
            with self.assertRaises(paths.OldLayoutError):
                call()
        self.assertEqual([], new_layout_files(self.root))
        self.assertEqual(self.old_tree, tree(self.root))

    def test_2_after_the_move_the_app_reads_the_same_content_and_undo_restores(self):
        self.assertEqual(7, len(self.read_before["entries"]))
        self.assertEqual(["주급수 상실"], self.read_before["ie_confirmed"])
        self.assertEqual("confirmed", self.read_before["node_set"][0])
        seen = self.counts_before["seen"]
        self.assertEqual((1, 1, 1, 1, 1), (seen["reviews"], seen["study_node_sets_confirmed"], seen["study_results"],
                                           seen["analysis_runs"], seen["regions_with_current_graph"]), seen)
        workroot.apply(self.root)
        self.assertEqual(self.read_before, self.read())
        after = counts.collect(self.root)
        self.assertEqual([], counts.compare(self.counts_before, after))
        self.assertEqual([], after["errors"])
        workroot.undo(self.root)
        self.assertEqual(self.old_tree, tree(self.root))


class MovedSettingsPathTest(unittest.TestCase):
    def test_fixed_response_folder_written_by_0_1_is_found_at_its_new_place(self):
        from hazop.study.ai_settings import AiPrefs
        with tempfile.TemporaryDirectory(prefix="hazop-moved-") as tmp, mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: tmp}):
            old = os.path.join(tmp, *paths.OLD_WORK_RELS["fixed-responses"].split("/"), "region-SNP-M-102-pzr")
            now = paths.folder("fixed-responses", "region-SNP-M-102-pzr")
            os.makedirs(now)
            saved = []
            prefs = AiPrefs({"fixed_response_dir": old}, saved.append)
            self.assertTrue(os.path.samefile(now, prefs.fixed_dir))
            prefs.set_fixed_dir(prefs.fixed_dir)
            self.assertTrue(os.path.samefile(now, saved[-1]["fixed_response_dir"]))
            self.assertNotIn(paths.OLD_WORK_RELS["fixed-responses"].split("/")[0], saved[-1]["fixed_response_dir"])

    def test_a_missing_folder_is_left_as_written(self):
        with tempfile.TemporaryDirectory(prefix="hazop-moved-") as tmp, mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: tmp}):
            gone = os.path.join(tmp, "elsewhere", "responses")
            self.assertEqual(gone, paths.resolve_moved(gone))
            self.assertIsNone(paths.resolve_moved(None))

    def test_old_dev_work_root_path_is_found_in_the_new_dev_work_root(self):
        with tempfile.TemporaryDirectory(prefix="hazop-moved-") as tmp:
            old_root, new_root = os.path.join(tmp, "old"), os.path.join(tmp, "new")
            now = os.path.join(paths.folder_in(new_root, "fixed-responses"), "r1")
            os.makedirs(now)
            with mock.patch.object(paths, "OLD_DEV_WORK_ROOT", old_root), mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: new_root}):
                old = os.path.join(old_root, *paths.OLD_WORK_RELS["fixed-responses"].split("/"), "r1")
                self.assertTrue(os.path.samefile(now, paths.resolve_moved(old)))


class CountsCommandTest(unittest.TestCase):
    def test_out_inside_the_checked_root_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="hazop-counts-") as tmp, mock.patch.object(sys, "stderr"):
            with self.assertRaises(SystemExit) as caught:
                counts.main(["--work-root", tmp, "--out", os.path.join(tmp, "output", "counts.json")])
            self.assertEqual(2, caught.exception.code)
            self.assertEqual([], os.listdir(tmp))

    def test_a_result_keyed_by_0_1_names_compares_without_false_differences(self):
        """한글 열쇠로 적힌 이전 결과(0.1.x 코드로 센 것)와 견준다. 같은 수면 같다고 하고, 다른 수면 그 열쇠로 알린다."""
        new = {"seen": {}, "errors": [], "changed_files": [], "records": {"total": 0, "resolved": 0, "unresolved": 0, "unresolved_paths": []},
               "files": {"work": {"data": 9, "regions": 1, "store": None, "output": 5, "evaluation-criteria": 2},
                         "output": {"graph": 3, "archive": None, "samples": 1}}}
        old = dict(new, files={"work": {"작업데이터": 9, "구간": 1, "자료저장소": None, "출력": 5},
                               "output": {"그래프": 3, "보관": None, "samples": 1}})
        self.assertEqual([], counts.compare(old, new))
        old["files"]["work"]["구간"] = 2
        old["files"]["output"]["그래프"] = 4
        self.assertEqual(["files.work.구간: 2 → 1", "files.output.그래프: 4 → 3"], counts.compare(old, new))


if __name__ == "__main__":
    unittest.main()
