"""8.3 단축 이름(예: C:\\Users\\RUNNER~1)으로 들어온 루트에서 경로 함수가 형태를 섞지 않는지 본다.

GitHub Windows 러너의 TEMP가 단축 이름이라 첫 CI 실행(run 42771733162)에서 14개 시험이 실패했다.
계정 이름이 길거나 한글인 사용자 PC에서도 TEMP가 단축 이름일 수 있다.
"""

import ctypes
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.contract import chain  # noqa: E402


def _short(path):
    try:
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 32768)
    except AttributeError:
        return path
    return buf.value if 0 < n < 32768 else path


class ShortNameRootTest(unittest.TestCase):
    def setUp(self):
        self.long = tempfile.mkdtemp(prefix="hazop-short-name-root-")
        self.addCleanup(shutil.rmtree, self.long, True)
        self.root = _short(self.long)
        if os.path.normcase(self.root) == os.path.normcase(self.long):
            self.skipTest("이 볼륨은 8.3 단축 이름을 만들지 않음")

    def test_safe_join_keeps_root_form(self):
        p = paths.safe_join(self.root, "a")
        self.assertEqual(p, os.path.join(self.root, "a"))

    def test_rel_or_abs_of_safe_join_stays_relative(self):
        os.makedirs(os.path.join(self.long, "a"))
        p = paths.safe_join(os.path.join(self.root, "a"), "b.json")
        self.assertEqual(paths.rel_or_abs(p, self.root), "a/b.json")

    def test_short_name_is_not_a_link(self):
        self.assertIsNone(chain._link_in_path(os.path.join(self.root, "r.json")))
        self.assertIsNone(chain._link_in_path(self.root))

    def test_long_path_expands_existing_prefix(self):
        self.assertEqual(os.path.normcase(paths.long_path(os.path.join(self.root, "없는", "f.json"))),
                         os.path.normcase(os.path.join(os.path.realpath(self.long), "없는", "f.json")))


if __name__ == "__main__":
    unittest.main()
