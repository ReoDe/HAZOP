"""0.1.x 작업 폴더를 0.2.0 배치로 옮기는 도구 시험(HZ-GOV-02 §6.6). 실행: python -m unittest tests.test_workroot"""

import collections
import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import devenv  # noqa: E402
import migrate_names  # noqa: E402
from hazop import paths, workroot  # noqa: E402

# 0.1.x 작업 폴더의 예: (옛 상대 경로, 0.2.0에서 놓일 상대 경로). 뒤가 None이면 건드리지 않는 파일이다.
LAYOUT = (
    ("데이터/구간/region-a.json", "data/regions/region-a.json"),
    ("데이터/고정응답/region-a/d09.json", "data/fixed-responses/region-a/d09.json"),
    ("데이터/지식/SNP-SAMPLE/knowledge_nodes.csv", "data/knowledge-graph/SNP-SAMPLE/knowledge_nodes.csv"),
    ("데이터/평가기준/criteria.json", "data/evaluation-criteria/criteria.json"),
    ("데이터/검토구간/no-project/SNP.json", "data/study-nodes/no-project/SNP.json"),
    ("데이터/분석결과/no-project/SNP.json", "data/analysis-results/no-project/SNP.json"),
    ("데이터/초기사건/no-project.json", "data/initiating-events/no-project.json"),
    # 백업 폴더 이름과 그 안의 내용은 그대로 둔다
    ("데이터/백업/20261108T124409Z-판이전/데이터/구간/region-a.json", "data/backup/20261108T124409Z-판이전/데이터/구간/region-a.json"),
    ("데이터/사용자가-둔-폴더/memo.txt", "data/사용자가-둔-폴더/memo.txt"),
    ("기호후보/묶음.json", "symbol-candidates/묶음.json"),
    ("자료저장소/p1/originals/material-1/1/a.drawio", "store/p1/originals/material-1/1/a.drawio"),
    ("자료저장소/reviews/region-a/run-1/d09/v1.json", "store/reviews/region-a/run-1/d09/v1.json"),
    ("출력/추출/SNP-M-102/extraction.json", "output/extract/SNP-M-102/extraction.json"),
    ("출력/그래프/SNP-M-102/graph.json", "output/graph/SNP-M-102/graph.json"),
    ("출력/분석/region-a/run-1/analysis.json", "output/analysis/region-a/run-1/analysis.json"),
    ("출력/지식그래프/kg-1/current.json", "output/knowledge-graph/kg-1/current.json"),
    ("출력/samples/추출/SNP-M-102/extraction.json", "output/samples/extract/SNP-M-102/extraction.json"),
    ("출력/초기사건/bundle.xlsx", "output/initiating-events/bundle.xlsx"),
    ("출력/문서지식/doc/document_knowledge.json", "output/document-knowledge/doc/document_knowledge.json"),
    ("출력/어댑터/x/extraction.json", "output/adapter/x/extraction.json"),
    ("출력/로그/run.log", "output/logs/run.log"),
    # 보관 폴더 안은 옮길 때의 상대 경로 그대로다
    ("출력/_보관/20261109T000000Z/분석/region-a/run-0/analysis.json", "output/_archive/20261109T000000Z/분석/region-a/run-0/analysis.json"),
    ("logs/app.log", None),
    ("cache/q.bin", None),
    ("venv-py312/pyvenv.cfg", None),
    ("settings-backup.json", None),
)
EMPTY_DIRS = (("데이터/도면수정", "data/drawing-edits"),)


def make_old_root(root):
    for i, (old, _new) in enumerate(LAYOUT):
        full = os.path.join(root, *old.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(("내용 %d %s" % (i, old)).encode("utf-8") * (i + 1))
    for old, _new in EMPTY_DIRS:
        os.makedirs(os.path.join(root, *old.split("/")))


def tree(root):
    """{상대 경로: SHA-256} 폴더는 값이 None이다."""
    out = {}
    for d, dirs, files in os.walk(root):
        for name in dirs:
            out[os.path.relpath(os.path.join(d, name), root).replace("\\", "/")] = None
        for name in files:
            full = os.path.join(d, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root).replace("\\", "/")] = hashlib.sha256(fh.read()).hexdigest()
    return out


def files_of(state):
    return {k: v for k, v in state.items() if v is not None}


class Crash(Exception):
    pass


class WorkRootMigrationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hazop-workroot-")
        self.addCleanup(tmp.cleanup)
        self.root = os.path.join(tmp.name, "HAZOP")
        make_old_root(self.root)
        self.before = tree(self.root)

    def test_layout_table_matches_the_path_table(self):
        for old, new in LAYOUT + EMPTY_DIRS:
            if new is not None:
                self.assertEqual(new, workroot.new_rel(old))

    def test_plan_reads_only(self):
        plan = workroot.make_plan(self.root)
        self.assertEqual("todo", plan.state)
        self.assertEqual({(o, n) for o, n in LAYOUT if n}, {(o, n) for o, n, _size in plan.files})
        self.assertEqual(self.before, tree(self.root))

    def test_apply_copies_under_new_names_and_keeps_the_old_folders(self):
        manifest = workroot.apply(self.root)
        after = tree(self.root)
        for old, new in LAYOUT:
            with self.subTest(old=old):
                if new is None:
                    self.assertEqual(self.before[old], after[old])
                else:
                    self.assertEqual(self.before[old], after[new])
                    self.assertEqual(self.before[old], after[workroot.KEEP_DIR + "/" + old])
                    self.assertNotIn(old, after)
        for old, new in EMPTY_DIRS:
            self.assertIn(new, after)
        self.assertEqual(os.path.join(self.root, workroot.KEEP_DIR, workroot.MANIFEST), manifest)
        self.assertEqual("done", workroot.make_plan(self.root).state)
        self.assertEqual([], [n for n in os.listdir(self.root) if n in dict(workroot.top_names())], "옛 이름 폴더가 최상위에 남음")
        self.assertFalse(os.path.exists(os.path.join(self.root, workroot.STAGING_DIR)))

    def test_apply_twice_changes_nothing(self):
        workroot.apply(self.root)
        once = tree(self.root)
        workroot.apply(self.root)
        self.assertEqual(once, tree(self.root))

    def test_undo_restores_the_original_tree(self):
        workroot.apply(self.root)
        report = workroot.undo(self.root)
        self.assertEqual(self.before, tree(self.root))
        self.assertEqual([], report["left"])
        self.assertEqual("todo", workroot.make_plan(self.root).state)

    def test_undo_keeps_files_made_or_changed_after_the_move(self):
        workroot.apply(self.root)
        made = os.path.join(self.root, "output", "graph", "NEW", "graph.json")
        os.makedirs(os.path.dirname(made))
        with open(made, "w", encoding="utf-8") as fh:
            fh.write("새 그래프")
        changed = os.path.join(self.root, "data", "regions", "region-a.json")
        with open(changed, "a", encoding="utf-8") as fh:
            fh.write("고침")
        report = workroot.undo(self.root)
        self.assertEqual(["data/regions/region-a.json", "output/graph/NEW/graph.json"], sorted(report["left"]))
        after = tree(self.root)
        self.assertEqual(files_of(self.before), {k: v for k, v in files_of(after).items() if k not in report["left"]})
        self.assertTrue(os.path.isfile(made) and os.path.isfile(changed))

    def test_stops_without_touching_anything_when_a_new_folder_already_has_files(self):
        taken = os.path.join(self.root, "store", "p9", "x.json")
        os.makedirs(os.path.dirname(taken))
        with open(taken, "w", encoding="utf-8") as fh:
            fh.write("0.2.0에서 만든 것")
        before = tree(self.root)
        self.assertEqual("conflict", workroot.make_plan(self.root).state)
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        self.assertEqual(before, tree(self.root))

    def test_empty_new_folders_do_not_block(self):
        """옮기기를 미루고 0.2.0을 한 번 켠 곳: 새 이름의 빈 폴더만 생겨 있다."""
        os.makedirs(os.path.join(self.root, "output", "graph"))
        os.makedirs(os.path.join(self.root, "store"))
        workroot.apply(self.root)
        self.assertEqual(self.before["출력/그래프/SNP-M-102/graph.json"], tree(self.root)["output/graph/SNP-M-102/graph.json"])

    def test_nothing_to_do_on_a_new_layout(self):
        fresh = os.path.join(os.path.dirname(self.root), "fresh")
        os.makedirs(os.path.join(fresh, "output", "graph"))
        self.assertEqual("none", workroot.make_plan(fresh).state)
        self.assertIsNone(workroot.apply(fresh))
        self.assertEqual({"output": None, "output/graph": None}, tree(fresh))
        with self.assertRaises(workroot.MigrationError):
            workroot.undo(fresh)

    def test_a_copy_that_differs_from_the_original_stops_the_move(self):
        real = shutil.copy2

        def corrupt(src, dst, **kw):
            real(src, dst, **kw)
            if src.endswith("graph.json"):
                with open(dst, "ab") as fh:
                    fh.write(b"!")

        with mock.patch.object(workroot.shutil, "copy2", corrupt), self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        after = tree(self.root)
        self.assertEqual(files_of(self.before), {k: v for k, v in files_of(after).items() if k in self.before})
        self.assertEqual([], [n for n in os.listdir(self.root) if n in dict(workroot.top_names()).values()], "새 이름 폴더가 놓임")
        workroot.apply(self.root)  # 다시 돌리면 틀린 복사본을 새로 쓰고 끝낸다
        self.assertEqual(self.before["출력/그래프/SNP-M-102/graph.json"], tree(self.root)["output/graph/SNP-M-102/graph.json"])

    def test_stops_when_the_disk_is_too_full(self):
        usage = collections.namedtuple("usage", "total used free")
        with mock.patch.object(workroot.shutil, "disk_usage", lambda _p: usage(10, 10, 1000)), \
                self.assertRaises(workroot.MigrationError):
            workroot.apply(self.root)
        self.assertEqual(self.before, tree(self.root))

    def test_progress_reports_bytes(self):
        seen = []
        workroot.apply(self.root, progress=lambda done, total: seen.append((done, total)))
        total = sum(os.path.getsize(os.path.join(self.root, workroot.KEEP_DIR, *o.split("/"))) for o, n in LAYOUT if n)
        self.assertEqual((total, total), seen[-1])
        self.assertEqual(sorted(seen), seen)

    def crash_points(self):
        """apply 한 번이 부르는 os.rename·os.replace·shutil.copy2 횟수."""
        probe = os.path.join(os.path.dirname(self.root), "probe")
        shutil.copytree(self.root, probe)
        calls = []
        with self.crashing(None, calls):
            workroot.apply(probe)
        shutil.rmtree(probe)
        return len(calls)

    def crashing(self, at, calls):
        """at번째 파일 연산 바로 앞에서 끊긴 것처럼 Crash를 낸다."""
        def wrap(real):
            def call(*a, **kw):
                if at is not None and len(calls) == at:
                    raise Crash()
                calls.append(real.__name__)
                return real(*a, **kw)
            return call
        stack = mock.patch.multiple(workroot.os, rename=wrap(os.rename), replace=wrap(os.replace))
        copy = mock.patch.object(workroot.shutil, "copy2", wrap(shutil.copy2))

        class Both:
            def __enter__(self_inner):
                stack.start()
                copy.start()

            def __exit__(self_inner, *exc):
                copy.stop()
                stack.stop()
        return Both()

    def test_an_interrupted_move_finishes_on_the_next_run_from_every_crash_point(self):
        done = os.path.join(os.path.dirname(self.root), "done")
        shutil.copytree(self.root, done)
        workroot.apply(done)
        want = files_of(tree(done))
        want.pop(workroot.KEEP_DIR + "/" + workroot.MANIFEST)
        n = self.crash_points()
        self.assertGreater(n, len(LAYOUT))
        for at in range(n):
            with self.subTest(crash_before_call=at):
                trial = os.path.join(os.path.dirname(self.root), "trial-%d" % at)
                shutil.copytree(self.root, trial)
                with self.crashing(at, []), self.assertRaises(Crash):
                    workroot.apply(trial)
                mid = files_of(tree(trial))
                self.assertEqual([], [k for k, v in files_of(self.before).items()
                                      if v not in (mid.get(k), mid.get(workroot.KEEP_DIR + "/" + k))], "끊긴 자리에서 옛 파일이 사라짐")
                workroot.apply(trial)
                got = files_of(tree(trial))
                got.pop(workroot.KEEP_DIR + "/" + workroot.MANIFEST)
                self.assertEqual(want, got)
                shutil.rmtree(trial)

    def test_an_interrupted_move_can_be_undone_from_every_crash_point(self):
        n = self.crash_points()
        for at in range(1, n):
            with self.subTest(crash_before_call=at):
                trial = os.path.join(os.path.dirname(self.root), "trial-%d" % at)
                shutil.copytree(self.root, trial)
                with self.crashing(at, []), self.assertRaises(Crash):
                    workroot.apply(trial)
                workroot.undo(trial)
                self.assertEqual(self.before, tree(trial))
                shutil.rmtree(trial)

    def test_work_root_folder_can_be_renamed_first_and_undo_puts_it_back(self):
        new_root = os.path.join(os.path.dirname(self.root), "work")
        workroot.apply(new_root, from_root=self.root)
        self.assertFalse(os.path.exists(self.root))
        self.assertEqual(self.before["출력/그래프/SNP-M-102/graph.json"], tree(new_root)["output/graph/SNP-M-102/graph.json"])
        once = tree(new_root)
        workroot.apply(new_root, from_root=self.root)
        self.assertEqual(once, tree(new_root))
        report = workroot.undo(new_root)
        self.assertEqual(os.path.abspath(self.root), report["root"])
        self.assertFalse(os.path.exists(new_root))
        self.assertEqual(self.before, tree(self.root))

    def test_refuses_to_rename_the_root_over_an_existing_folder(self):
        new_root = os.path.join(os.path.dirname(self.root), "work")
        os.makedirs(new_root)
        with self.assertRaises(workroot.MigrationError):
            workroot.apply(new_root, from_root=self.root)
        self.assertEqual(self.before, tree(self.root))


class CommandTest(unittest.TestCase):
    """scripts/migrate_names.py --work-root"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hazop-workroot-")
        self.addCleanup(tmp.cleanup)
        self.root = os.path.join(tmp.name, "HAZOP")
        make_old_root(self.root)
        self.before = tree(self.root)
        self.said = []

    def run_command(self, **kw):
        return migrate_names.migrate_work_root(self.root, out=self.said.append, **kw)

    def test_default_only_shows_what_would_move(self):
        self.assertEqual(0, self.run_command())
        self.assertEqual(self.before, tree(self.root))
        text = "\n".join(self.said)
        for old, now in workroot.top_names():
            self.assertIn("%s -> %s" % (old, now), text)

    def test_apply_then_undo_round_trip(self):
        self.assertEqual(0, self.run_command(apply=True))
        self.assertEqual("done", workroot.make_plan(self.root).state)
        self.assertEqual(0, self.run_command(apply=True))
        self.assertEqual(0, self.run_command(undo=True))
        self.assertEqual(self.before, tree(self.root))

    def test_conflict_and_missing_record_exit_with_2(self):
        os.makedirs(os.path.join(self.root, "output", "graph"))
        with open(os.path.join(self.root, "output", "graph", "x.json"), "w"):
            pass
        before = tree(self.root)
        self.assertEqual(2, self.run_command())
        with mock.patch.object(sys, "stderr"):
            self.assertEqual(2, self.run_command(apply=True))
            self.assertEqual(2, self.run_command(undo=True))
        self.assertEqual(before, tree(self.root))

    def test_refuses_while_the_app_holds_the_work_root(self):
        from PySide6.QtCore import QLockFile
        from hazop.app.startup import LOCK_NAME
        held = QLockFile(os.path.join(self.root, LOCK_NAME))
        self.assertTrue(held.tryLock(0))
        try:
            before = tree(self.root)
            with mock.patch.object(sys, "stderr"):
                self.assertEqual(2, self.run_command(apply=True))
            self.assertEqual(before, tree(self.root))
        finally:
            held.unlock()
        self.assertEqual(0, self.run_command(apply=True))
        self.assertFalse(os.path.exists(os.path.join(self.root, LOCK_NAME)), "잠금 파일이 남음")

    def test_renames_the_root_and_back(self):
        new_root = os.path.join(os.path.dirname(self.root), "work")
        self.assertEqual(0, migrate_names.migrate_work_root(new_root, from_root=self.root, apply=True, out=self.said.append))
        self.assertFalse(os.path.exists(self.root))
        self.assertEqual("done", workroot.make_plan(new_root).state)
        self.assertEqual(0, migrate_names.migrate_work_root(new_root, undo=True, out=self.said.append))
        self.assertEqual(self.before, tree(self.root))
        self.assertFalse(os.path.exists(new_root))

    def test_preflight_warns_about_a_root_that_still_has_old_folders(self):
        warnings = devenv.old_work_root_warnings([self.root])
        self.assertEqual(1, len(warnings))
        self.assertIn(self.root, warnings[0])
        workroot.apply(self.root)
        self.assertEqual([], devenv.old_work_root_warnings([self.root]))


class MigratedRootReadsTest(unittest.TestCase):
    """옮긴 뒤에는 0.1.x가 적어 둔 경로가 새 폴더에서 풀린다."""

    def test_old_records_resolve_after_the_move(self):
        with tempfile.TemporaryDirectory(prefix="hazop-workroot-") as tmp:
            root = os.path.join(tmp, "HAZOP")
            make_old_root(root)
            workroot.apply(root)
            for old, new in LAYOUT:
                if new is not None and "/백업/" not in old and "/_보관/" not in old:
                    with self.subTest(old=old):
                        self.assertTrue(os.path.samefile(os.path.join(root, *new.split("/")), paths.resolve_rel(old, root)))


if __name__ == "__main__":
    unittest.main()
