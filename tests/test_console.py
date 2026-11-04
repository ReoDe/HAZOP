"""콘솔 인코딩 회귀 테스트: cp949 콘솔에서 표현 불가 문자('—' U+2014)를 출력해도 CLI가 죽지 않아야 한다."""

import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402


def cp949_stream():
    raw = io.BytesIO()
    return raw, io.TextIOWrapper(raw, encoding="cp949", errors="strict", newline="\n")


class Cp949ConsoleTest(unittest.TestCase):

    def test_strict_cp949_fails_without_helper(self):
        _, s = cp949_stream()
        with self.assertRaises(UnicodeEncodeError):
            s.write("사유 — 대체")
            s.flush()

    def test_helper_replaces_only_unencodable(self):
        raw, s = cp949_stream()
        with mock.patch.object(sys, "stdout", s):
            safe_console()
            print("한글 정상 — 대시")
            sys.stdout.flush()
        self.assertEqual(raw.getvalue().decode("cp949"), "한글 정상 ? 대시\n")

    def test_analyze_cli_message_with_em_dash(self):
        """회귀: analyze.py --resume 거부 메시지('—' 포함)가 cp949 콘솔에서 예외 없이 끝남."""
        import analyze as script
        from hazop.analysis import ai, run
        from tests.test_analysis import FIXED_DIR, raw_inputs
        tmp = tempfile.mkdtemp()
        try:
            _, run_dir = run.execute(raw_inputs(), ai.FixedResponseClient(FIXED_DIR), tmp, run_id="analysis-cp949",
                                     only={"p86-d10"})
            raw, s = cp949_stream()
            with mock.patch.object(sys, "stdout", s):
                rc = script.main(["--resume", run_dir, "--live"])
                sys.stdout.flush()
            self.assertEqual(rc, 1)
            out = raw.getvalue().decode("cp949")
            self.assertIn("재시도 오류: 원래 실행은 고정 응답 ? --live", out)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
