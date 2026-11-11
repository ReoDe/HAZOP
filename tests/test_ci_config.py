"""CI 설정이 가리키는 것이 실제로 있는지, 공개 저장소에서 위험한 설정이 들어오지 않았는지 본다.

이름 이전이 경로를 바꾸면 이 시험이 로컬에서 먼저 깨진다. CI venv에는 PyYAML이 없어서 YAML을 구조로 읽지 않고
워크플로 전체 글자에 정규식을 건다. 그래서 규칙은 '어디에 있든 안 됨'으로 넓게 잡았다.
"""

import glob
import os
import re
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml")
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import run_ci  # noqa: E402

FORBIDDEN = (
    (r"\bsecrets\b", "secrets 컨텍스트를 쓴다"),
    (r"pull_request_target", "pull_request_target은 남의 PR에 쓰기 토큰을 준다"),
    (r"write-all|:\s*write\b", "쓰기 권한을 준다"),
    (r"continue-on-error", "실패는 빨간불로 보여야 한다"),
    (r"\$\{\{\s*runner\.", "runner 컨텍스트는 job env에서 못 쓴다. 단계에서 $env:RUNNER_TEMP를 쓴다"),
    (r"persist-credentials:\s*(?!false\s*$)\S", "checkout 토큰을 남긴다"),
    (r"check_", "검사 스크립트 목록은 run_ci.py가 정한다"),
    (r"^[ \t]*(?:- )?[\w-]+:[ \t]+[^|>\"'\s#][^#\n]*:[ \t]", "따옴표 없는 한 줄 값에 ': '가 있어 YAML이 깨진다(run 42771584149)"),
)


def workflow_problems(text):
    problems = []
    if not text.isascii():
        problems.append("ASCII 밖 글자(한글 경로 등)가 있다")
    for pattern, why in FORBIDDEN:
        if re.search(pattern, text, re.MULTILINE):
            problems.append(why)
    if not re.search(r"(?m)^permissions:\n  contents: read\n(?!  )", text):
        problems.append("최상단 permissions가 contents: read 하나가 아니다")
    uses = re.findall(r"uses:\s*(\S+)", text)
    if not uses:
        problems.append("액션이 없다")
    problems += ["커밋 SHA로 고정하지 않은 액션: %s" % u for u in uses if not re.search(r"@[0-9a-f]{40}$", u)]
    checkouts = len(re.findall(r"uses:\s*actions/checkout@", text))
    if len(re.findall(r"(?m)persist-credentials:\s*false\s*$", text)) != checkouts:
        problems.append("checkout마다 persist-credentials: false가 있어야 한다")
    runs_on = re.findall(r"runs-on:\s*(\S+)", text)
    if not runs_on or any("latest" in r for r in runs_on):
        problems.append("러너 이미지 판 번호를 고정하지 않았다")
    return problems


def _workflow_text():
    with open(WORKFLOW, encoding="utf-8") as f:
        return f.read()


class WorkflowTest(unittest.TestCase):
    def test_workflow_has_no_problems(self):
        self.assertEqual([], workflow_problems(_workflow_text()))

    def test_referenced_repo_files_exist(self):
        refs = re.findall(r"(?:scripts|packaging)/[\w./*-]+", _workflow_text())
        self.assertIn("scripts/run_ci.py", refs)
        for ref in refs:
            self.assertTrue(glob.glob(os.path.join(REPO_ROOT, ref)), "워크플로가 가리키는 파일이 없다: %s" % ref)

    def test_dangerous_variants_are_caught(self):
        text = _workflow_text()
        run = "run: python scripts/run_ci.py\n"
        variants = {
            "toJSON(secrets)": text.replace(run, "run: python scripts/run_ci.py ${{ toJSON(secrets) }}\n"),
            "secrets[...]": text.replace(run, "run: python scripts/run_ci.py ${{ secrets['TOKEN'] }}\n"),
            "job write-all": text.replace("    timeout-minutes", "    permissions: write-all\n    timeout-minutes"),
            "job contents: write": text.replace("    timeout-minutes", "    permissions:\n      contents: write\n    timeout-minutes"),
            "top-level extra scope": text.replace("  contents: read\n", "  contents: read\n  actions: read\n"),
            "pull_request_target": text.replace("  workflow_dispatch:", "  pull_request_target:"),
            "persist-credentials true": text.replace("persist-credentials: false", "persist-credentials: true"),
            "persist-credentials missing": text.replace("          persist-credentials: false\n", ""),
            "runner context in job env": text.replace("      QT_QPA_PLATFORM: offscreen\n",
                                                      "      QT_QPA_PLATFORM: offscreen\n      W: ${{ runner.temp }}\n"),
            "action by tag": re.sub(r"(actions/checkout@)[0-9a-f]{40}", r"\1v7", text),
            "latest image": text.replace("windows-2025", "windows-latest"),
            "continue-on-error": text.replace(run, run + "        continue-on-error: true\n"),
            "check script named": text.replace(run, run.replace("run_ci", "check_kg")),
            "colon-space in plain scalar": text.replace(
                "run: |\n          python -m pip install --require-hashes",
                "run: python -m pip install --require-hashes"),
            "hangul path": text.replace(run, run.replace("scripts", "도구")),
        }
        for name, variant in variants.items():
            with self.subTest(name):
                self.assertNotEqual(text, variant, "변형이 적용되지 않음")
                self.assertTrue(workflow_problems(variant), "잡지 못한 변형")


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
