"""평가 기준 비교 검사를 한 번에 실행한다 (QA용, 기획서/평가기준비교.md §7). 네트워크·AI 호출 없음.

입력: 실제 최신 분석 실행(출력/분석/region-SNP-M-102-pzr/ 최신)을 임시 폴더에 복사해 쓴다. 실행이 없으면
tests/run_fixture.py의 고정 응답 실행을 쓴다. 비교 보고는 임시 작업 루트(HAZOP_WORK_ROOT)에만 쓰고 끝나면 지운다
(출력/·자료저장소/에 쓰지 않음, 원본 실행 폴더는 읽기만 함).

1) 가상 기준(JSON)으로 scripts/compare_criteria.py 실행(draft, 종료 코드 0): JSON·Excel 생성, 가상 기준 표시, status ok
2) 같은 기준의 Excel판(xlsx_sheet)으로 실행: 지표가 JSON판과 같음
3) 같은 시각(--now)으로 다시 실행하면 실패(종료 코드 1, 덮어쓰지 않음)
4) 원본 실행 폴더·저장소 출력/평가비교가 바뀌지 않음
5) tests/test_evaluate.py
종료 코드 0 = 전부 통과.
"""

import contextlib
import glob
import hashlib
import io
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

import compare_criteria  # noqa: E402
from hazop import paths  # noqa: E402

CRIT_DIR = paths.folder("samples", "evaluation-criteria")
CRIT_JSON = os.path.join(CRIT_DIR, "criteria-SNP-M-102-pzr-sample.json")
CRIT_XLSX = os.path.join(CRIT_DIR, "criteria-SNP-M-102-pzr-sample.xlsx")
REAL_RUNS = paths.output_in(paths.DEV_WORK_ROOT, "analysis", "region-SNP-M-102-pzr")
NOTICE = "가상 기준 — MVP 성공 판단에 쓰지 않음"  # 기획 §2.1 고정 문구
T1, T2 = "2026-11-06T00:00:00Z", "2026-11-06T00:00:01Z"


def ok(label, cond, failures):
    print("  [%s] %s" % ("OK" if cond else "FAIL", label))
    if not cond:
        failures.append(label)


def latest_run():
    runs = sorted(d for d in glob.glob(os.path.join(REAL_RUNS, "analysis-*"))
                  if os.path.isfile(os.path.join(d, "analysis.json")))
    if runs:
        return runs[-1]
    from tests.run_fixture import fresh_run_dir
    return fresh_run_dir()


def snapshot(root):
    out = {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as fh:
                out[p] = hashlib.sha256(fh.read()).hexdigest()
    return out


def cli(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = compare_criteria.main(args)
    return code, buf.getvalue()


def harness(tmp, src, failures):
    run_dir = os.path.join(tmp, "runs", os.path.basename(src))
    shutil.copytree(src, run_dir)
    store = os.path.join(tmp, "store")
    os.makedirs(store)
    out_glob = paths.output_in(os.path.join(tmp, "work"), "evaluation-compare", "*", "*")
    base = ["--run", run_dir, "--store-root", store]
    print("입력 실행: %s" % src)

    print("1) 가상 기준 JSON → CLI 비교(draft)")
    code, text = cli(["--criteria", CRIT_JSON, "--now", T1] + base)
    files = sorted(glob.glob(os.path.join(out_glob, "*.json")))
    ok("CLI 종료 코드 0, JSON 1개", code == 0 and len(files) == 1, failures)
    if not files:
        print(text)
        return
    with open(files[0], encoding="utf-8") as fh:
        rep = json.load(fh)
    ok("status ok, 지표 있음", rep["status"] == "ok" and rep["metrics"] is not None, failures)
    ok("보고 JSON에 가상 기준 표시", rep.get("notice") == NOTICE, failures)
    xlsx = files[0][:-5] + ".xlsx"
    ok("Excel 보고 4시트", os.path.isfile(xlsx) and
       openpyxl.load_workbook(xlsx).sheetnames == ["요약", "행별 대응", "누락", "초과"], failures)
    if os.path.isfile(xlsx):
        ws = openpyxl.load_workbook(xlsx)["요약"]
        ok("Excel 요약에 가상 기준 표시", ws["B2"].value == NOTICE, failures)
    m = rep["metrics"] or {}
    for k in ("deviation_recall", "cause_recall", "cause_precision", "consequence_match", "safeguard_match",
              "recommendation_match"):
        print("    %s = %s" % (k, m.get(k)))
    print("    counts = %s" % m.get("counts"))

    print("2) 같은 기준의 Excel판(xlsx_sheet)")
    code, text = cli(["--criteria", CRIT_XLSX, "--format", "xlsx_sheet", "--now", T2] + base)
    files2 = [f for f in glob.glob(os.path.join(out_glob, "*.json")) if f not in files]
    rep2 = None
    if len(files2) == 1:
        with open(files2[0], encoding="utf-8") as fh:
            rep2 = json.load(fh)
    ok("CLI 종료 코드 0, 지표가 JSON판과 같음", code == 0 and rep2 is not None and rep2["metrics"] == rep["metrics"],
       failures)

    print("3) 같은 시각으로 다시 쓰기")
    before = snapshot(os.path.dirname(files[0]))
    code, _text = cli(["--criteria", CRIT_JSON, "--now", T1] + base)
    ok("종료 코드 1, 기존 파일 그대로(덮어쓰지 않음)", code == 1 and snapshot(os.path.dirname(files[0])) == before,
       failures)


def main():
    safe_console()
    failures = []
    try:
        src = latest_run()
    except Exception as e:  # 분석 실행 준비 실패도 실패로 보고
        print("[FAIL] 검사용 분석 실행을 찾거나 만들지 못함: %r" % e)
        return 1
    src_before = snapshot(src)
    repo_cmp = paths.output_in(paths.DEV_WORK_ROOT, "evaluation-compare")
    out_existed = os.path.exists(repo_cmp)
    out_before = snapshot(repo_cmp) if out_existed else None
    tmp = tempfile.mkdtemp(prefix="hazop-check-compare-")
    old = os.environ.get(paths.ENV_WORK_ROOT)
    os.environ[paths.ENV_WORK_ROOT] = os.path.join(tmp, "work")
    try:
        harness(tmp, src, failures)
    except Exception as e:  # 검사 도중 예외도 실패로 보고
        failures.append("예외: %r" % e)
        print("  [FAIL] 예외: %r" % e)
    finally:
        if old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = old
        shutil.rmtree(tmp, ignore_errors=True)
    print("4) 원본 보존")
    ok("원본 실행 폴더 바뀌지 않음", snapshot(src) == src_before, failures)
    ok("저장소 출력/평가비교 생성·변경 없음",
       os.path.exists(repo_cmp) == out_existed and (not out_existed or snapshot(repo_cmp) == out_before), failures)
    print("5) tests/test_evaluate.py")
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_evaluate")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok("단위 테스트 %d개" % result.testsRun, result.wasSuccessful(), failures)
    print("결과: %s" % ("전부 통과" if not failures else "실패 %d건: %s" % (len(failures), failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
