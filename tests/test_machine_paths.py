r"""이 컴퓨터에만 있는 절대 경로 금지 검사(2026-11-10 교훈: D 드라이브 이전 대비).

git이 추적하는 코드·시험·패키징·.claude 파일에 사용자 폴더(C:\Users\<이름>), 저장소 밖 시험 폴더(HAZOP-trials),
Claude 세션 임시 폴더 경로가 박혀 있으면 실패한다. 경로는 저장소 기준 상대 경로, %USERPROFILE%·~, 환경변수로 쓴다.
시험 자료처럼 가짜 사용자 이름(C:\Users\u 등)은 걸리지 않는다.

    python -m unittest tests.test_machine_paths
"""

import getpass
import os
import re
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ("hazop", "scripts", "tests", "packaging", ".claude", "CLAUDE.md")
SELF = "tests/test_machine_paths.py"


def pattern(user=None):
    user = user or getpass.getuser()
    sep = r"[\\/]+"
    parts = [r"HAZOP-trials", "AppData" + sep + "Local" + sep + "Temp" + sep + "claude" + sep,
             r"/c/Users/" + re.escape(user) + r"\b"]
    if user and len(user) > 2:
        parts.append("[A-Za-z]:" + sep + "Users" + sep + re.escape(user) + r"\b")
    return re.compile("|".join(parts), re.I)


def violations(repo=REPO, rx=None):
    rx = rx or pattern()
    r = subprocess.run(["git", "-C", repo, "ls-files", "-z", "--"] + list(SCAN), capture_output=True)
    if r.returncode != 0:
        return []
    out = []
    for rel in r.stdout.decode("utf-8").split("\0"):
        full = os.path.join(repo, rel)
        if not rel or rel == SELF or not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8") as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                out.append("%s:%d %s" % (rel, n, line.strip()[:100]))
    return out


class MachinePathTest(unittest.TestCase):
    def test_no_machine_specific_paths(self):
        found = violations()
        self.assertEqual(found, [], "이 컴퓨터에만 있는 경로:\n" + "\n".join(found[:30]))

    def test_pattern(self):
        rx = pattern("kim92")
        self.assertTrue(rx.search(r"C:\Users\kim92\HAZOP"))
        self.assertTrue(rx.search("D:/HAZOP-trials/x"))
        self.assertFalse(rx.search(r"C:\Users\u\.hazop\venv-py312"))
        self.assertFalse(rx.search(r"%USERPROFILE%\.hazop\venv-py312"))


if __name__ == "__main__":
    unittest.main()
