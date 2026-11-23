"""새 화면 사용자 시나리오 가운데 가벼운 앞쪽(N1 등록 → N2 AI 검토 켜고 등록 → N3 표제란 확정 → N4 도면 고치기 → N5 쪽 확정)을
scripts/check_shell_scenarios.py로 돌린다. 실행: python -m unittest tests.test_shell_scenarios_light

이 스크립트는 CI 묶음 밖이라 시트 정체 U1(번호 확정 전 도면이 graph-<자료>-p<쪽> 이름을 받음) 뒤로 깨진 것을 놓쳤다(2026-11-23).
스크립트가 자기 Qt 앱과 임시 작업·저장 루트를 만들므로 따로 프로세스로 띄운다. AI는 가짜, 화면 밖(offscreen), 1분 안쪽.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LightScenariosTest(unittest.TestCase):
    def test_n1_to_n5_pass(self):
        out = tempfile.mkdtemp(prefix="hazop-scn-light-")
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "check_shell_scenarios.py"), "--out", out, "--only", "N1,N2,N3,N4,N5"],
                           cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
        with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
            rep = json.load(fh)
        got = {s["id"]: s["verdict"] for s in rep["scenarios"] if s["id"] in ("N1", "N2", "N3", "N4", "N5")}
        bad = {s["id"]: [c for c in s["checks"] if not c["ok"]] or s["error"] for s in rep["scenarios"] if s["id"] in got and s["verdict"] != "통과"}
        self.assertEqual(got, {k: "통과" for k in ("N1", "N2", "N3", "N4", "N5")}, json.dumps(bad, ensure_ascii=False)[:1500] + p.stdout[-500:])
        self.assertEqual(p.returncode, 0, p.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
