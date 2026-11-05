"""Excel 워크시트 출력 검사를 한 번에 실행한다 (QA용, 기획서/인터페이스.md §8 Excel 행). 네트워크·AI 호출 없음.

입력: tests/run_fixture.py가 임시 폴더에 고정 응답으로 새로 만든 실행(scripts/analyze.py 하위 프로세스)을 복사해 쓴다.
검토 기록·출력은 임시 폴더에만 쓰고 끝나면 지운다(자료저장소/·출력/에 쓰지 않음).

1) 검토 저장(수정 1·수용 1·보류 1, 수식처럼 시작하는 문자열 포함) → scripts/export_worksheet.py 실행(종료 코드 0)
2) openpyxl로 다시 읽어: 시트 6개, 5–7열 사람 확정값 또는 '미확정'(0 없음), AI 제안 비포함, 수식 비실행,
   〈별표9〉 수용·수정만·'관리 안 함', 검토일(KST)·쪽 머리글, exports/ 출력 기록
3) analysis.json 재작성(해시 불일치) 뒤 출력 차단(종료 코드 1, 파일 추가 없음)
4) tests/test_export.py
종료 코드 0 = 전부 통과.
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

import openpyxl  # noqa: E402

import export_worksheet  # noqa: E402
from hazop import review as rv  # noqa: E402
from hazop.export import FIRST_DATA_ROW, WORKSHEET_COLUMNS, kst_date  # noqa: E402
from tests.run_fixture import fresh_run_dir  # noqa: E402

WHO = "검토자A"
T = "2026-11-04T16:30:00Z"


def ok(label, cond, failures):
    print("  [%s] %s" % ("OK" if cond else "FAIL", label))
    if not cond:
        failures.append(label)


def harness(tmp, src, failures):
    run_dir = os.path.join(tmp, "runs", os.path.basename(src))
    shutil.copytree(src, run_dir)
    store, out = os.path.join(tmp, "store"), os.path.join(tmp, "worksheet")
    run = rv.open_run(run_dir)
    doc = run["doc"]

    def rc(sev, f):
        return rv.make_risk_confirmation(run, sev, "강도 근거", f, f, "빈도 근거")

    print("1) 검토 저장 → CLI 출력")
    cid = "deviation-p86-d09"
    s = [x["scenario_id"] for x in doc["scenarios"] if x["candidate_id"] == cid]
    dic_of = {d["scenario_id"]: d["dic_id"] for d in doc["design_improvement_candidates"]}
    decs = [rv.scenario_decision(run, s[0], "modify", "정정", WHO, revised={"consequence": "=1+1"},
                                 risk_confirmation=rc(2, 1), now=T),
            rv.scenario_decision(run, s[1], "accept", "수용", WHO, risk_confirmation=rc(3, 2), now=T),
            rv.scenario_decision(run, s[2], "defer", "자료 대기", WHO, now=T)]
    ddecs = [rv.dic_decision(run, dic_of[s[2]], "accept", "권고 필요", WHO, recommendation="@경보 추가 검토", now=T)]
    rv.save_review(store, run, rv.build_review(run, cid, WHO, "요약", decs, ddecs), now=T)
    code = export_worksheet.main(["--run", run_dir, "--store-root", store, "--out-root", out])
    files = glob.glob(os.path.join(out, "*", "*", "worksheet-*.xlsx"))
    ok("CLI 종료 코드 0, 파일 1개", code == 0 and len(files) == 1, failures)
    if not files:
        return
    wb = openpyxl.load_workbook(files[0])

    print("2) 다시 읽어 검사")
    ok("시트 6개", wb.sheetnames == ["분석 정보", "전체 편차 후보", "HAZOP 워크시트", "설계보완 후보", "개선 권고",
                                   "자료 요청 메모"], failures)
    ws = wb["HAZOP 워크시트"]
    keys = [k for k, _h, _s in WORKSHEET_COLUMNS]
    rows = {}
    for r in range(FIRST_DATA_ROW, ws.max_row + 1):
        row = {k: ws.cell(row=r, column=i) for i, k in enumerate(keys, 1)}
        rows.setdefault(row["scenario_id"].value, row)
    risk_vals = [row[k].value for row in rows.values() for k in ("frequency", "severity", "risk")]
    ok("5–7열에 0·빈칸 없음", all(v == "미확정" or (isinstance(v, int) and v >= 1) for v in risk_vals), failures)
    ok("확정값(빈도 1·강도 2·위험도 1)", [rows[s[0]][k].value for k in ("frequency", "severity", "risk")] == [1, 2, 1],
       failures)
    ok("AI 제안 위험도 4가 있는 보류 행은 5–7열 '미확정', 제안은 추가 열에만",
       [rows[s[2]][k].value for k in ("frequency", "severity", "risk")] == ["미확정"] * 3
       and "위험도 4" in rows[s[2]]["ai_risk"].value, failures)
    ok("수식 문자열 '=1+1'이 문자열 셀", rows[s[0]]["consequence"].value == "=1+1"
       and rows[s[0]]["consequence"].data_type == "s", failures)
    rec_ws = wb["개선 권고"]
    rec_rows = [[rec_ws.cell(row=r, column=c).value for c in range(1, 10)] for r in range(2, rec_ws.max_row + 1)]
    ok("〈별표9〉 수용 후보 1건, 위험등급 '미확정'(basis.risk 미사용), 관리 열 '관리 안 함'",
       len(rec_rows) == 1 and rec_rows[0][2] == "미확정" and rec_rows[0][3] == "@경보 추가 검토"
       and rec_rows[0][4:8] == ["관리 안 함"] * 4, failures)
    ok("검토일 = 최신 reviewed_at의 KST 날짜(2026-11-05)", ws.cell(row=2, column=4).value == kst_date(T) == "2026-11-05",
       failures)
    ok("인쇄 머리글 쪽 번호/전체(&P/&N)", ws.oddHeader.right.text == "&P/&N"
       and rec_ws.oddHeader.right.text == "&P/&N", failures)
    exp = glob.glob(os.path.join(store, "reviews", "*", "*", "exports", "*.json"))
    ok("exports/ 출력 기록 1건", len(exp) == 1, failures)
    if exp:
        with open(exp[0], encoding="utf-8") as fh:
            rec = json.load(fh)
        ok("출력 기록: 범위·대상 해시·행 식별자", rec["scope"] == "all"
           and rec["target"]["analysis_sha256"] == run["analysis_sha256"]
           and len(rec["rows"]["worksheet"]) == ws.max_row - FIRST_DATA_ROW + 1, failures)

    print("3) 해시 불일치 차단")
    with open(run["analysis_path"], "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    code = export_worksheet.main(["--run", run_dir, "--store-root", store, "--out-root", out])
    ok("analysis.json 해시 변경 시 출력 차단(종료 코드 1, 파일 추가 없음)",
       code == 1 and len(glob.glob(os.path.join(out, "*", "*", "worksheet-*.xlsx"))) == 1, failures)


def main():
    safe_console()
    failures = []
    try:
        src = fresh_run_dir()
    except Exception as e:  # 분석 실행 실패도 실패로 보고
        print("[FAIL] 검사용 분석 실행을 만들지 못함: %r" % e)
        return 1
    tmp = tempfile.mkdtemp(prefix="hazop-check-export-")
    try:
        harness(tmp, src, failures)
    except Exception as e:  # 검사 도중 예외도 실패로 보고
        failures.append("예외: %r" % e)
        print("  [FAIL] 예외: %r" % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("4) tests/test_export.py")
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_export")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok("단위 테스트 %d개" % result.testsRun, result.wasSuccessful(), failures)
    print("결과: %s" % ("전부 통과" if not failures else "실패 %d건: %s" % (len(failures), failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
