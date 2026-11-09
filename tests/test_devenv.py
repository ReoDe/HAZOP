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
        for out in (" M 자원/기준/기호/APR1400/check_valve_box.json\n", "?? 자원/기준/기호/APR1400/new.json\n",
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
