"""개발 환경 점검(scripts/devenv.py) 시험. 실행: python -m unittest tests.test_devenv"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import devenv  # noqa: E402


class Interpreter(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop(devenv.ENV_ALLOW_ANY_PYTHON, None)

    def test_libreoffice_python_is_refused(self):
        bad = devenv.interpreter_problems(r"C:\Program Files\LibreOffice\program\python.exe", r"C:\Program Files\LibreOffice")
        self.assertEqual(len(bad), 1)
        self.assertIn("LibreOffice", bad[0])

    def test_venv_python_passes(self):
        self.assertEqual(devenv.interpreter_problems(r"C:\Users\u\.hazop\venv-py312\Scripts\python.exe", r"C:\Python312"), [])

    def test_stale_venv_is_refused(self):
        for exe in (r"C:\Users\u\AppData\Local\HAZOP\venv-py312\Scripts\python.exe",
                    r"C:\Users\u\AppData\Local\Packages\Claude_x\LocalCache\Local\HAZOP\venv-py312\Scripts\python.exe"):
            self.assertEqual(len(devenv.interpreter_problems(exe, r"C:\Python312")), 1, exe)

    def test_override(self):
        os.environ[devenv.ENV_ALLOW_ANY_PYTHON] = "1"
        self.assertEqual(devenv.interpreter_problems(r"C:\Program Files\LibreOffice\program\python.exe", ""), [])


class Disk(unittest.TestCase):
    def test_threshold(self):
        tmp = tempfile.gettempdir()
        self.assertEqual(devenv.disk_problems([tmp], need_gb=0), [])
        self.assertEqual(len(devenv.disk_problems([tmp], need_gb=10 ** 9)), 1)

    def test_missing_path_uses_existing_parent(self):
        self.assertGreater(devenv.free_gb(os.path.join(tempfile.gettempdir(), "없는", "폴더")), 0)


class TempSweep(unittest.TestCase):
    def test_only_old_hazop_dirs_go(self):
        base = tempfile.mkdtemp(prefix="sweep-base-")
        self.addCleanup(__import__("shutil").rmtree, base, True)
        old, new, other = (os.path.join(base, n) for n in ("hazop-app-old", "hazop_new", "keep-me"))
        for d in (old, new, other):
            os.makedirs(d)
        os.utime(old, (0, 0))
        os.utime(other, (0, 0))
        with mock.patch.dict(os.environ, {devenv.ENV_KEEP_TEMP: "0"}):
            self.assertEqual(devenv.sweep_stale_temp(24, base), [old])
            os.makedirs(old)
            os.utime(old, (0, 0))
            os.environ[devenv.ENV_KEEP_TEMP] = "1"
            self.assertEqual(devenv.sweep_stale_temp(24, base), [])
        self.assertTrue(os.path.isdir(new) and os.path.isdir(other))


class TrialsFolder(unittest.TestCase):
    """HZ-GOV-02 §8.2. 2026-11-10의 저장소 밖 시험 폴더에 실제로 있던 모양을 넣는다."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="trials-")
        self.addCleanup(__import__("shutil").rmtree, self.root, True)

    def folder(self, name, readme=None):
        os.makedirs(os.path.join(self.root, name))
        if readme is not None:
            with open(os.path.join(self.root, name, "README.md"), "w", encoding="utf-8") as f:
                f.write(readme)

    def test_each_kind_is_reported(self):
        for name in ("README.md", "u2.diff", "계통약어_v2.csv"):
            open(os.path.join(self.root, name), "w").close()
        self.folder("ie-20261109")
        self.folder("2026-11-10-unit-b-packaging", "주인: 단위 B\n")
        self.folder("2026-11-09-u5", "- keep_until: 2026-11-23\n")
        self.folder("2026-11-09-ie-subscription-run", "- `keep_until`: forever\n")
        self.folder("2026-11-10-unsorted", "keep_until: 2026-11-24\n")
        found = devenv.trials_warnings(self.root, today="2026-11-24")
        self.assertEqual(5, len(found), found)
        self.assertIn("낱개 파일 2개: u2.diff, 계통약어_v2.csv", found[0])
        self.assertIn("아닌 폴더 1개: ie-20261109", found[1])
        self.assertIn("README.md가 없는 폴더 1개: ie-20261109", found[2])
        self.assertIn("keep_until이 없는 폴더 1개: 2026-11-10-unit-b-packaging", found[3])
        self.assertIn("지난 폴더 1개(지우기는 사람 확인 뒤): 2026-11-09-u5", found[4])

    def test_clean_or_missing_root_is_quiet(self):
        self.folder("2026-11-10-unsorted", "keep_until: 2026-11-24\n")
        self.assertEqual([], devenv.trials_warnings(self.root, today="2026-11-10"))
        self.assertEqual([], devenv.trials_warnings(os.path.join(self.root, "none")))

    def test_root_comes_from_env(self):
        with mock.patch.dict(os.environ, {devenv.ENV_TRIALS_ROOT: self.root}):
            self.assertEqual(self.root, devenv.trials_root())
        with mock.patch.dict(os.environ):
            os.environ.pop(devenv.ENV_TRIALS_ROOT, None)
            self.assertEqual(devenv.REPO_ROOT + "-trials", devenv.trials_root())


class BaselineGuard(unittest.TestCase):
    PATH = os.path.join(REPO_ROOT, "tests", "baselines", "apr1400_score.json")

    def fake_git(self, out):
        return mock.patch.object(devenv, "_git", return_value=subprocess.CompletedProcess([], 0, out, ""))

    def test_dirty_baseline_blocks_update(self):
        with self.fake_git(" M tests/baselines/apr1400_score.json\n"):
            bad = devenv.baseline_update_problems(self.PATH)
        self.assertEqual(len(bad), 1)
        self.assertIn("--force", bad[0])

    def test_dirty_symbol_dictionary_or_answer_key_blocks_update(self):
        symbols = devenv.hp.folder_rel("symbols")
        self.assertIn(symbols, devenv.SCORING_PATHS)
        for out in (" M %s/APR1400/check_valve_box.json\n" % symbols, "?? %s/APR1400/new.json\n" % symbols,
                    " M tests/fixtures/apr1400/pairs_key.json\n"):
            with self.fake_git(out):
                self.assertEqual(len(devenv.baseline_update_problems(self.PATH)), 1, out)

    def test_clean_baseline_allows_update(self):
        with self.fake_git(""):
            self.assertEqual(devenv.baseline_update_problems(self.PATH), [])

    def test_force_and_outside_repo_skip_check(self):
        with self.fake_git(" M x\n"):
            self.assertEqual(devenv.baseline_update_problems(self.PATH, force=True), [])
            self.assertEqual(devenv.baseline_update_problems(os.path.join(tempfile.gettempdir(), "b.json")), [])


if __name__ == "__main__":
    unittest.main()
