"""CI 설정이 가리키는 것이 실제로 있는지 본다. 이름 이전이 경로를 바꾸면 이 시험이 로컬에서 먼저 깨진다."""

import glob
import os
import re
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml")
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import run_ci  # noqa: E402


def _workflow_text():
    with open(WORKFLOW, encoding="utf-8") as f:
        return f.read()


class WorkflowTest(unittest.TestCase):
    def test_referenced_repo_files_exist(self):
        refs = re.findall(r"(?:scripts|packaging)/[\w./*-]+", _workflow_text())
        self.assertIn("scripts/run_ci.py", refs)
        for ref in refs:
            self.assertTrue(glob.glob(os.path.join(REPO_ROOT, ref)), "워크플로가 가리키는 파일이 없다: %s" % ref)

    def test_workflow_names_only_the_entry_point(self):
        text = _workflow_text()
        self.assertTrue(text.isascii(), "워크플로에 한글이나 ASCII 밖 글자가 있다")
        self.assertNotIn("check_", text, "검사 스크립트 목록은 run_ci.py가 정한다")

    def test_no_secrets_and_read_only(self):
        text = _workflow_text()
        self.assertNotIn("secrets.", text)
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read$")
        self.assertNotIn("continue-on-error", text, "실패는 빨간불로 보여야 한다")

    def test_actions_pinned_to_commit(self):
        uses = re.findall(r"uses:\s*(\S+)", _workflow_text())
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$", "커밋 SHA로 고정하지 않은 액션: %s" % ref)

    def test_runner_image_pinned(self):
        runs_on = re.findall(r"runs-on:\s*(\S+)", _workflow_text())
        self.assertTrue(runs_on)
        for image in runs_on:
            self.assertNotIn("latest", image)


class CheckListTest(unittest.TestCase):
    def test_listed_checks_exist(self):
        for name in tuple(run_ci.CHECKS) + tuple(run_ci.NOT_IN_CI):
            self.assertTrue(os.path.isfile(run_ci.check_path(name)), "없는 검사 스크립트: %s" % name)

    def test_every_check_is_classified(self):
        on_disk = {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(REPO_ROOT, "scripts", "check_*.py"))}
        listed = set(run_ci.CHECKS) | set(run_ci.NOT_IN_CI)
        self.assertEqual(set(), on_disk - listed, "CI에 넣을지 run_ci.py에 적지 않은 검사 스크립트")
        self.assertEqual(set(), set(run_ci.CHECKS) & set(run_ci.NOT_IN_CI))


if __name__ == "__main__":
    unittest.main()
