"""작업 폴더 이전의 손실 경로 재현 시험(2026-11-11 교차검증 지적 1~10). 실행: python -m unittest tests.test_workroot_review

모두 임시 폴더의 실제 파일로 한다. 링크·정션이 가리키는 대상도 임시 폴더 안에 둔다.
"""

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

import migrate_names  # noqa: E402
from hazop import paths, workroot  # noqa: E402
from hazop.app import startup  # noqa: E402
from tests.test_workroot import Crash, files_of, make_old_root, tree  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def junction(link, target):
    """정션을 만든다(관리자 권한이 필요 없다). 만들지 못하면 False."""
    done = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
    return done.returncode == 0


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hazop-wr-review-", ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.root = os.path.join(self.tmp, "HAZOP")
        make_old_root(self.root)
        self.before = tree(self.root)

    def assert_untouched(self):
        self.assertEqual(self.before, tree(self.root))


class DestinationCollisionTest(Case):
    """지적 1: 서로 다른 원본이 같은 목적지로 간다."""

    def test_two_sources_for_one_destination_stop_the_move_and_are_listed(self):
        write(os.path.join(self.root, "데이터", "regions", "region-a.json"), "0.2.0 이름으로 손으로 둔 것")
        self.before = tree(self.root)
        plan = workroot.make_plan(self.root)
        self.assertEqual("conflict", plan.state)
        text = " ".join(plan.conflicts)
        self.assertIn("데이터/구간/region-a.json", text)
        self.assertIn("데이터/regions/region-a.json", text)
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        self.assert_untouched()

    @unittest.skipUnless(os.name == "nt", "대소문자를 가리지 않는 파일 시스템에서만 겹친다")
    def test_names_that_differ_only_by_case_collide(self):
        write(os.path.join(self.root, "출력", "GRAPH", "SNP-M-102", "graph.json"), "대문자 폴더")
        self.before = tree(self.root)
        plan = workroot.make_plan(self.root)
        self.assertEqual("conflict", plan.state)
        self.assertIn("출력/GRAPH/SNP-M-102/graph.json", " ".join(plan.conflicts))
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        self.assert_untouched()


@unittest.skipUnless(os.name == "nt", "icacls로 권한을 바꾼다")
class UnreadableFolderTest(Case):
    """지적 2·10: 읽지 못한 하위 폴더가 빠진 채 끝난다. 배치 확인이 실패하면 앱이 그냥 시작한다."""

    def setUp(self):
        super().setUp()
        self.locked = os.path.join(self.root, "출력", "분석", "region-a")
        user = os.environ.get("USERNAME")
        done = subprocess.run(["icacls", self.locked, "/deny", "%s:(RD)" % user], capture_output=True)
        if done.returncode != 0:
            self.skipTest("권한을 바꾸지 못함")
        self.addCleanup(subprocess.run, ["icacls", self.locked, "/remove:d", user], capture_output=True)
        try:
            os.listdir(self.locked)
        except PermissionError:
            return
        self.skipTest("권한을 막아도 읽힌다(관리자 실행)")

    def test_an_unreadable_folder_stops_the_move(self):
        with self.assertRaises((workroot.MigrationError, OSError)):
            workroot.apply(self.root)
        subprocess.run(["icacls", self.locked, "/remove:d", os.environ.get("USERNAME")], capture_output=True)
        self.assertEqual([], [n for n in os.listdir(self.root) if n in dict(workroot.top_names()).values()], "새 이름 폴더가 놓임")
        self.assertFalse(os.path.isdir(os.path.join(self.root, workroot.KEEP_DIR, "출력")), "옛 폴더가 보관 자리로 감")
        self.assertEqual(files_of(self.before), {k: v for k, v in files_of(tree(self.root)).items() if k in self.before})

    def test_the_app_does_not_start_when_the_layout_cannot_be_checked(self):
        told = []
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.root}):
            rc = startup.offer_work_root_move(True, ask=lambda plan: self.fail("물으면 안 됨"),
                                              notify=lambda title, text: told.append(text))
        self.assertEqual(startup.EXIT_OLD_LAYOUT, rc)
        self.assertEqual(1, len(told))


@unittest.skipUnless(os.name == "nt", "정션은 Windows 것")
class LinkTest(Case):
    """지적 3: 링크·정션."""

    def test_a_junction_inside_an_old_folder_stops_the_move_and_is_listed(self):
        target = os.path.join(self.tmp, "elsewhere")
        write(os.path.join(target, "inside.txt"), "정션 너머의 파일")
        if not junction(os.path.join(self.root, "자료저장소", "linked"), target):
            self.skipTest("정션을 만들지 못함")
        plan = workroot.make_plan(self.root)
        self.assertEqual("conflict", plan.state)
        self.assertIn("자료저장소/linked", " ".join(plan.conflicts))
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        self.assertTrue(os.path.isfile(os.path.join(target, "inside.txt")))
        self.assertEqual([], [n for n in os.listdir(self.root) if n in dict(workroot.top_names()).values()])

    def test_a_staging_folder_that_is_a_junction_is_not_written_through(self):
        outside = os.path.join(self.tmp, "outside")
        victim = write(os.path.join(outside, "graph", "SNP-M-102", "graph.json"), "밖에 있는 파일")
        os.makedirs(os.path.join(self.root, workroot.STAGING_DIR))
        if not junction(os.path.join(self.root, workroot.STAGING_DIR, "output"), outside):
            self.skipTest("정션을 만들지 못함")
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        with open(victim, encoding="utf-8") as fh:
            self.assertEqual("밖에 있는 파일", fh.read())
        self.assertEqual(["graph"], os.listdir(outside))

    def test_a_staged_file_that_is_a_symlink_is_not_written_through(self):
        victim = write(os.path.join(self.tmp, "outside", "victim.json"), "밖에 있는 파일")
        link = os.path.join(self.root, workroot.STAGING_DIR, "output", "graph", "SNP-M-102", "graph.json")
        os.makedirs(os.path.dirname(link))
        try:
            os.symlink(victim, link)
        except OSError:
            self.skipTest("심볼릭 링크를 만들 권한이 없음")
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        with open(victim, encoding="utf-8") as fh:
            self.assertEqual("밖에 있는 파일", fh.read())


class UndoKeepsForeignFilesTest(Case):
    """지적 4: 되돌리기가 임시 폴더나 새 배치의 파일을 해시·소유 검사 없이 지운다."""

    def test_undo_keeps_a_file_someone_put_in_the_staging_folder(self):
        calls = []
        real = shutil.copy2

        def stop_midway(src, dst, **kw):
            if len(calls) == 5:
                raise Crash()
            calls.append(src)
            return real(src, dst, **kw)

        with mock.patch.object(workroot.shutil, "copy2", stop_midway), self.assertRaises(Crash):
            workroot.apply(self.root)
        foreign = write(os.path.join(self.root, workroot.STAGING_DIR, "output", "graph", "mine.json"), "도구가 만든 것이 아님")
        report = workroot.undo(self.root)
        self.assertTrue(os.path.isfile(foreign), "남의 파일을 지움")
        self.assertIn(workroot.STAGING_DIR + "/output/graph/mine.json", report["left"])
        self.assertEqual(files_of(self.before), {k: v for k, v in files_of(tree(self.root)).items() if k in self.before})
        self.assertEqual([workroot.STAGING_DIR + "/output/graph/mine.json"],
                         sorted(k for k in files_of(tree(self.root)) if k not in self.before))


class UndoInterruptedTest(Case):
    """지적 5: 되돌리다 끊기면 다시 돌려도 막힌다."""

    def crashing(self, at, calls):
        def wrap(real):
            def call(*a, **kw):
                if at is not None and len(calls) == at:
                    raise Crash()
                calls.append(real.__name__)
                return real(*a, **kw)
            return call
        return mock.patch.multiple(workroot.os, rename=wrap(os.rename), replace=wrap(os.replace), remove=wrap(os.remove),
                                   rmdir=wrap(os.rmdir))

    def test_an_interrupted_undo_finishes_on_the_next_undo_from_every_crash_point(self):
        workroot.apply(self.root)
        moved = os.path.join(self.tmp, "moved")
        shutil.copytree(self.root, moved)
        calls = []
        with self.crashing(None, calls):
            workroot.undo(moved)
        shutil.rmtree(moved)
        self.assertGreater(len(calls), 8)
        for at in range(len(calls)):
            with self.subTest(crash_before_call=at, call=calls[at]):
                trial = os.path.join(self.tmp, "trial-%d" % at)
                shutil.copytree(self.root, trial)
                with self.crashing(at, []), self.assertRaises(Crash):
                    workroot.undo(trial)
                mid = files_of(tree(trial))
                self.assertEqual([], [k for k, v in files_of(self.before).items()
                                      if v not in (mid.get(k), mid.get(workroot.KEEP_DIR + "/" + k))], "끊긴 자리에서 옛 파일이 사라짐")
                workroot.undo(trial)
                self.assertEqual(self.before, tree(trial))
                shutil.rmtree(trial)

    def test_apply_refuses_while_an_undo_is_half_done(self):
        workroot.apply(self.root)
        with self.crashing(6, []), self.assertRaises(Crash):
            workroot.undo(self.root)
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        workroot.undo(self.root)
        self.assertEqual(self.before, tree(self.root))


class OldDevRootTest(unittest.TestCase):
    """지적 6: 옛 개발 작업 루트만 있을 때 잠금 폴더를 만들면서 새 작업 루트가 생겨 감지가 풀린다."""

    def test_old_dev_root_still_blocks_after_the_lock_created_the_new_folder(self):
        with tempfile.TemporaryDirectory(prefix="hazop-wr-review-") as tmp:
            old_root, new_root = os.path.join(tmp, "old"), os.path.join(tmp, "new")
            make_old_root(old_root)
            before = tree(old_root)
            told = []
            with mock.patch.dict(os.environ), mock.patch.object(paths, "DEV_WORK_ROOT", new_root), \
                    mock.patch.object(paths, "OLD_DEV_WORK_ROOT", old_root):
                os.environ.pop(paths.ENV_WORK_ROOT, None)
                os.environ["QT_QPA_PLATFORM"] = "offscreen"
                from hazop.app import make_application
                make_application(["t"])
                lock, rc = startup.single_instance(notify=lambda *a: None)
                try:
                    self.assertIsNone(rc)
                    rc = startup.offer_work_root_move(True, ask=lambda plan: True, notify=lambda title, text: told.append(text))
                    self.assertEqual(startup.EXIT_OLD_LAYOUT, rc)
                    with self.assertRaises(paths.OldLayoutError):
                        paths.work_root()
                finally:
                    if lock is not None:
                        lock.unlock()
            self.assertEqual(before, tree(old_root))
            self.assertIn(old_root, told[0])


class StoreRootInsideOldLayoutTest(Case):
    """지적 7: HAZOP_STORE_ROOT가 옛 배치 작업 루트 안을 가리키면 배치 검사 없이 통과한다."""

    def test_store_root_inside_an_old_layout_work_root_is_blocked(self):
        inside = os.path.join(self.root, "store")
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.root, paths.ENV_STORE_ROOT: inside}):
            with self.assertRaises(paths.OldLayoutError):
                paths.store_root()
        self.assert_untouched()

    def test_store_root_outside_the_work_root_is_not_affected(self):
        outside = os.path.join(self.tmp, "kept-store")
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.root, paths.ENV_STORE_ROOT: outside}):
            self.assertEqual(outside, paths.store_root())


class LayoutCacheTest(Case):
    """지적 8: 옮긴 뒤 열었던 작업 루트를 되돌리면 옛 배치인데도 통과한다. 시험이 캐시를 직접 비우지 않는다."""

    def test_apply_open_undo_open(self):
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.root}):
            with self.assertRaises(paths.OldLayoutError):
                paths.work_root()
            workroot.apply(self.root)
            self.assertEqual(self.root, paths.work_root())
            workroot.undo(self.root)
            with self.assertRaises(paths.OldLayoutError):
                paths.work_root()
            workroot.apply(self.root)
            self.assertEqual(self.root, paths.work_root())

    def test_old_folders_that_appear_later_are_noticed(self):
        fresh = os.path.join(self.tmp, "fresh")
        os.makedirs(fresh)
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: fresh}):
            self.assertEqual(fresh, paths.work_root())
            os.makedirs(os.path.join(fresh, "출력"))
            with self.assertRaises(paths.OldLayoutError):
                paths.work_root()


class LockTest(Case):
    """지적 9: 잠금 없이 옮기거나 시작한다."""

    def test_the_app_does_not_move_without_the_lock(self):
        told = []
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.root}):
            rc = startup.offer_work_root_move(True, ask=lambda plan: True, notify=lambda title, text: told.append(text), locked=False)
        self.assertEqual(startup.EXIT_OLD_LAYOUT, rc)
        self.assert_untouched()
        self.assertEqual(1, len(told))

    def test_undo_with_a_renamed_root_refuses_while_the_app_holds_the_lock(self):
        from PySide6.QtCore import QLockFile
        new_root = os.path.join(self.tmp, "work")
        self.assertEqual(0, migrate_names.migrate_work_root(new_root, from_root=self.root, apply=True, out=lambda s: None))
        held = QLockFile(os.path.join(new_root, startup.LOCK_NAME))
        self.assertTrue(held.tryLock(0))
        try:
            with mock.patch.object(sys, "stderr"):
                self.assertEqual(2, migrate_names.migrate_work_root(new_root, undo=True, out=lambda s: None))
            self.assertEqual("done", workroot.make_plan(new_root).state)
        finally:
            held.unlock()
        self.assertEqual(0, migrate_names.migrate_work_root(new_root, undo=True, out=lambda s: None))
        self.assertEqual(self.before, tree(self.root))


class MinorTest(Case):
    def test_an_empty_user_folder_in_the_new_layout_survives_the_move(self):
        os.makedirs(os.path.join(self.root, "data", "custom-empty"))
        workroot.apply(self.root)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "data", "custom-empty")))

    def test_an_empty_user_folder_in_the_old_layout_is_carried_over(self):
        os.makedirs(os.path.join(self.root, "데이터", "custom-empty"))
        workroot.apply(self.root)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "data", "custom-empty")))

    def test_root_rename_is_recorded_even_when_the_move_then_stops(self):
        """작업 루트 이름을 바꾼 뒤 옮기기가 멈춰도 되돌리기가 원래 자리를 안다."""
        write(os.path.join(self.root, "store", "p9", "x.json"), "새 이름 폴더에 이미 있는 파일")
        before = tree(self.root)
        new_root = os.path.join(self.tmp, "work")
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(new_root, from_root=self.root)
        self.assertTrue(os.path.isdir(new_root))
        report = workroot.undo(new_root)
        self.assertEqual(os.path.abspath(self.root), report["root"])
        self.assertEqual(before, tree(self.root))

    @unittest.skipUnless(os.name == "nt", "Windows 경로 길이")
    def test_a_long_path_is_moved(self):
        deep = os.path.join(self.root, "출력", "분석", *["가나다라마바사아자차카타파하-%02d" % i for i in range(12)])
        try:
            write(os.path.join(deep, "analysis.json"), "긴 경로")
        except OSError:
            self.skipTest("이 PC는 긴 경로를 만들지 못함")
        before = files_of(tree(self.root))
        workroot.apply(self.root)
        workroot.undo(self.root)
        self.assertEqual(before, files_of(tree(self.root)))

    def test_read_only_files_are_moved_and_undone(self):
        target = os.path.join(self.root, "자료저장소", "p1", "originals", "material-1", "1", "a.drawio")
        os.chmod(target, 0o444)
        self.addCleanup(lambda: [os.chmod(os.path.join(d, f), 0o666) for d, _s, fs in os.walk(self.root) for f in fs])
        workroot.apply(self.root)
        self.assertEqual(self.before["자료저장소/p1/originals/material-1/1/a.drawio"],
                         tree(self.root)["store/p1/originals/material-1/1/a.drawio"])
        workroot.undo(self.root)
        self.assertEqual(self.before, tree(self.root))


class RecordAndDiskDisagreeTest(Case):
    """Claude 측 검토 1: 기록은 '옮겼다'인데 옛 폴더가 제자리에 있다(손으로 돌려놓았거나 되돌리기가 끊겼다)."""

    def setUp(self):
        super().setUp()
        workroot.apply(self.root)
        os.rename(os.path.join(self.root, workroot.KEEP_DIR, "출력"), os.path.join(self.root, "출력"))
        self.state = tree(self.root)

    def test_an_old_folder_on_disk_is_never_reported_as_moved(self):
        plan = workroot.make_plan(self.root)
        self.assertEqual("conflict", plan.state)
        self.assertIn("출력", " ".join(plan.conflicts))
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        self.assertEqual(self.state, tree(self.root))

    def test_the_app_does_not_say_moved_and_does_not_start(self):
        told = []
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.root}):
            rc = startup.offer_work_root_move(True, ask=lambda plan: True, notify=lambda title, text: told.append(text))
            self.assertEqual(startup.EXIT_OLD_LAYOUT, rc)
            with self.assertRaises(paths.OldLayoutError):
                paths.work_root()
        self.assertEqual(1, len(told))
        self.assertNotIn("옮겼습니다", told[0])
        self.assertEqual(self.state, tree(self.root))

    def test_a_move_that_reports_success_but_leaves_old_folders_is_not_announced(self):
        told = []
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.root}), \
                mock.patch.object(workroot, "make_plan", lambda root: workroot.Plan(root, "todo", (("출력", "output"),), (), (), ())):
            rc = startup.offer_work_root_move(True, ask=lambda plan: True, notify=lambda title, text: told.append(text),
                                              run=lambda root: None)
        self.assertEqual(startup.EXIT_OLD_LAYOUT, rc)
        self.assertNotIn("옮겼습니다", " ".join(told))

    def test_undo_still_puts_everything_back(self):
        os.rename(os.path.join(self.root, "출력"), os.path.join(self.root, workroot.KEEP_DIR, "출력"))
        workroot.undo(self.root)
        self.assertEqual(self.before, tree(self.root))


class ReadOnlyUndoTest(Case):
    """Claude 측 검토 1의 재현: 출력/ 아래 읽기 전용 파일이 있어도 되돌리기가 끝난다."""

    def test_undo_finishes_with_read_only_files_under_output(self):
        for rel in ("출력/그래프/SNP-M-102/graph.json", "출력/분석/region-a/run-1/analysis.json", "데이터/구간/region-a.json"):
            os.chmod(os.path.join(self.root, *rel.split("/")), 0o444)
        self.addCleanup(lambda: [os.chmod(os.path.join(d, f), 0o666) for d, _s, fs in os.walk(self.tmp) for f in fs])
        workroot.apply(self.root)
        report = workroot.undo(self.root)
        self.assertEqual([], report["left"])
        self.assertEqual(self.before, tree(self.root))
        workroot.apply(self.root)
        self.assertEqual("done", workroot.make_plan(self.root).state)


class StagingStrayTest(Case):
    """Claude 측 검토 경미: 끊긴 뒤 옛 폴더에서 지운 파일이 임시 폴더 복사본에서 되살아나거나, 남이 둔 파일이 딸려 들어간다."""

    def interrupt(self):
        calls = []
        real = shutil.copy2

        def stop_late(src, dst, **kw):
            if len(calls) == 18:
                raise Crash()
            calls.append(src)
            return real(src, dst, **kw)

        with mock.patch.object(workroot.shutil, "copy2", stop_late), self.assertRaises(Crash):
            workroot.apply(self.root)

    def test_a_file_deleted_from_the_old_folder_after_an_interruption_does_not_come_back(self):
        self.interrupt()
        gone = "데이터/구간/region-a.json"
        self.assertTrue(os.path.isfile(os.path.join(self.root, workroot.STAGING_DIR, "data", "regions", "region-a.json")))
        os.remove(os.path.join(self.root, *gone.split("/")))
        plan = workroot.make_plan(self.root)
        self.assertEqual("conflict", plan.state)
        self.assertIn(workroot.STAGING_DIR + "/data/regions/region-a.json", " ".join(plan.conflicts))
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        self.assertFalse(os.path.exists(os.path.join(self.root, "data")))

    def test_a_stray_file_in_the_staging_folder_is_not_carried_into_the_new_folder(self):
        self.interrupt()
        write(os.path.join(self.root, workroot.STAGING_DIR, "output", "stray.txt"), "남이 둔 파일")
        with self.assertRaises(workroot.MigrationError) as caught:
            workroot.apply(self.root)
        self.assertIn(workroot.STAGING_DIR + "/output/stray.txt", str(caught.exception))
        self.assertFalse(os.path.exists(os.path.join(self.root, "output")))


class WorkRootArgumentTest(Case):
    """Claude 측 검토 3: 작업 루트를 인자로 받는 스크립트도 옛 배치에는 쓰지 않는다."""

    def test_seed_samples_writes_nothing_into_an_old_layout_root(self):
        done = subprocess.run([sys.executable, os.path.join(REPO_ROOT, "scripts", "seed_samples.py"), "--work-root", self.root],
                              cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        said = done.stdout.decode("utf-8", "replace")
        self.assertNotEqual(0, done.returncode, said)
        self.assertIn("이전 버전(0.1)의 폴더가 남아 있습니다", said)
        self.assertNotIn("Traceback", said)
        self.assert_untouched()

    def test_seed_samples_still_fills_a_moved_root(self):
        workroot.apply(self.root)
        done = subprocess.run([sys.executable, os.path.join(REPO_ROOT, "scripts", "seed_samples.py"), "--work-root", self.root],
                              cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(0, done.returncode, done.stdout.decode("utf-8", "replace"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "data", "regions", "region-SNP-M-102-pzr.json")))


if __name__ == "__main__":
    unittest.main()
