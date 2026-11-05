"""패키징 W4 묶음 검증: 빌드한 one-folder를 저장소 밖 새 폴더에 복사해 묶인 실행으로 ①~⑤·③ V1·V2·S1·로그를 확인한다.

사용(전용 venv, 스냅숏 또는 저장소 루트에서):
  python packaging/verify_bundle.py --dist <out>/dist/HAZOP-verify --target-base %TEMP%\\hz_ascii --out <결과 상위 폴더>
  python packaging/verify_bundle.py --dist <out>/dist/HAZOP --target-base ... --out ... --app-only   # 배포용
순서:
 0) 사전 검사: dist에 HAZOP.exe가 있어야 하고, --app-only가 아니면 HAZOP-check.exe도 있어야 한다(없으면 중단).
    --target-base·--out은 저장소·dist와 서로 포함되면 안 된다. 기존 폴더는 어떤 경우에도 지우지 않는다.
 1) 실행마다 새 폴더 <target-base>/verify-<시각>-<uuid8>(또는 --run-name)를 만든다. 같은 이름이 있으면 실패로 끝낸다.
    그 아래 HAZOP/(dist 사본)과 w4-run/(검사 입력 사본·작업 루트·임시)을 둔다. 결과는 --out 아래 새 폴더(run-<시각>-xxxx).
 2) HAZOP-check.exe w4_flow.py: 루트·datas 해시·자원 경로(분석 전) → ①~⑤ 함수 흐름·기준 자료 읽기 위치·음성 검사
 3) HAZOP-check.exe check_kg_screen.py --skip-tests --screenshots: ③ V2·렌더링·V1·S1·③ 탭과 ③ PNG
    (이 단계만 HAZOP_WORK_ROOT = 입력 사본: 샘플 graph_version이 개발 실행과 같게. QT_QPA_PLATFORM = windows:
    offscreen은 위젯 한글이 빈 상자로 찍힘)
 4) HAZOP.exe --screenshots [--run <④ 실행 폴더>]: ①②④⑤ PNG(앱의 --screenshots는 ③을 찍지 않음).
    <작업 루트>/logs/app.log에 시작 기록이 있는지. 미처리 예외 기록: JSON 배열인 설정 파일(--settings)을 주면 MainWindow가
    ValueError를 낸다 → 로그에 "미처리 예외"와 그 메시지가 남아야 한다(창 프로그램은 PyInstaller 오류 대화상자가 떠서
    끝나지 않으므로 60초 뒤 강제 종료). 잘못된 옵션(--w4-unknown-option)은 종료 코드 2와 사용법 오류(표준 출력 사본)만
    본다: 하위 프로세스로 띄우면 표준 출력 핸들이 있어 로그 파일 연결(핸들이 없을 때만)이 일어나지 않는다
 5) 저장소 출력/·자료저장소/ 파일 해시가 전후 같은지, 3)이 입력 사본을 바꾸지 않았는지, PNG가 이번 실행에서 생겼는지
자식 프로세스 환경: PYTHONPATH·PYTHONHOME·HAZOP_* 제거, HAZOP_WORK_ROOT·APPDATA·TEMP = 임시, 작업 폴더 = 임시(저장소 아님).
새 폴더를 만든 뒤의 모든 단계는 try 안에서 하고, 끝나면(실패해도, finally) 이번 실행에서 만든 verify-… 폴더만 지운다.
지우지 못하면 errors.cleanup에 남기고 실패 처리한다. 단계별 예외는 summary.json errors에 남긴다. 종료 코드 0 = 전부 통과.
네트워크·AI 호출 없음.
"""

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_SCRIPTS = ("check_kg_screen", "check_kg", "check_kg_algo", "check_kg_renderer", "build_kg", "analyze_kg",
                 "analyze", "extract_drawio", "build_graph")
SAMPLE = ("참고자료", "P&ID 도면 샘플", "SNP-M-102_RCS-pressurizer")
APP_PNG = ("01-register.png", "02-viewer.png", "04-analysis.png", "05-review.png")
FULL_PNG = APP_PNG + ("03-knowledge.png", "03-knowledge-1366.png", "05-review-confirmed.png")
TIMEOUT = 900


def _build_package():
    spec = importlib.util.spec_from_file_location("hazop_build_package_v",
                                                  os.path.join(REPO_ROOT, "scripts", "build_package.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bp = _build_package()
inside = bp.inside  # 드라이브가 다르면 False(ValueError 처리)


def overlaps(a, b):
    return inside(a, b) or inside(b, a)


def tree_hashes(root):
    """{상대 경로: sha256} — 폴더가 없으면 빈 dict(이름이 같아도 내용이 바뀌면 다름)."""
    out = {}
    if not os.path.isdir(root):
        return out
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def tree_size(root):
    total = count = 0
    for d, _, fs in os.walk(root):
        for f in fs:
            total += os.path.getsize(os.path.join(d, f))
            count += 1
    return total, count


def base_problems(base, dist, repo=REPO_ROOT):
    """검증 사본을 만들 상위 폴더 검사. 문제 목록(빈 목록 = 써도 됨)."""
    probs = []
    if overlaps(base, repo):
        probs.append("대상 상위 폴더가 저장소와 겹침: %s" % base)
    if overlaps(base, dist):
        probs.append("대상 상위 폴더가 dist와 겹침: %s" % base)
    return probs


def new_run_root(base, name=None):
    """이번 실행 전용 새 폴더 <base>/<name>(기본 verify-<시각>-<uuid8>). 이미 있으면 FileExistsError(건드리지 않음)."""
    name = name or time.strftime("verify-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    if os.path.basename(name) != name or name in ("", ".", ".."):
        raise ValueError("폴더 이름이 아님: %r" % name)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, name)
    os.mkdir(path)  # 있으면 FileExistsError
    return path


def fresh_problems(png_dir, since, want):
    """want 이름의 PNG가 png_dir에 있고 since 이후에 만들어졌는지. 문제 목록."""
    probs = []
    for name in want:
        p = os.path.join(png_dir, name)
        if not os.path.isfile(p):
            probs.append("없음: %s" % name)
        elif os.path.getmtime(p) < since:
            probs.append("이번 실행 전 파일: %s" % name)
    return probs


def make_inputs(dest):
    """검사 입력 사본(저장소 구조 일부). hazop/ 은 넣지 않는다(묶음의 hazop만 읽히게)."""
    os.makedirs(os.path.join(dest, "scripts"))
    for n in CHECK_SCRIPTS:
        shutil.copy2(os.path.join(REPO_ROOT, "scripts", n + ".py"), os.path.join(dest, "scripts"))
    shutil.copy2(os.path.join(REPO_ROOT, "packaging", "w4_flow.py"), os.path.join(dest, "scripts"))
    sdir = os.path.join(dest, *SAMPLE)
    os.makedirs(sdir)
    for p in glob.glob(os.path.join(REPO_ROOT, *SAMPLE, "*.drawio")) + \
            glob.glob(os.path.join(REPO_ROOT, *SAMPLE, "*.drawio.svg")):
        shutil.copy2(p, sdir)
    for rel in (("데이터", "구간"), ("데이터", "고정응답"), ("데이터", "지식", "SNP-SAMPLE")):
        shutil.copytree(os.path.join(REPO_ROOT, *rel), os.path.join(dest, *rel))


def expected_datas(repo=REPO_ROOT):
    """{저장소 상대 경로: sha256} — 빌드가 묶은 datas 원본의 바이트 해시."""
    out = {}
    for src, _ in bp.datas_list(repo):
        with open(os.path.join(repo, *src.split("/")), "rb") as fh:
            out[src] = hashlib.sha256(fh.read()).hexdigest()
    return out


def child_env(tmp):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP") and not k.startswith("HAZOP_")}
    env["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    env["APPDATA"] = os.path.join(tmp, "appdata")
    env["TEMP"] = env["TMP"] = os.path.join(tmp, "t")
    for k in ("HAZOP_WORK_ROOT", "APPDATA", "TEMP"):
        os.makedirs(env[k], exist_ok=True)
    return env


def decode(raw):
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def run(cmd, env, cwd, log, timeout=TIMEOUT):
    """(종료 코드 또는 'timeout'·'error: …', 초, 출력). 실행 자체의 예외도 결과로 돌려준다."""
    t0 = time.monotonic()
    try:
        with open(log, "wb") as fh:
            proc = subprocess.run(cmd, env=env, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    except OSError as e:
        rc = "error: %s" % e
    text = ""
    if os.path.isfile(log):
        with open(log, "rb") as fh:
            text = decode(fh.read())
    return rc, round(time.monotonic() - t0, 1), text


def read_text(path):
    if not os.path.isfile(path):
        return ""
    with open(path, "rb") as fh:
        return decode(fh.read())


def steps(args, summary, run_root, out, repo_dirs):
    """새 폴더를 만든 뒤의 단계 전부(main의 try 안에서 부른다)."""
    png = os.path.join(out, "png")
    target, tmp = os.path.join(run_root, "HAZOP"), os.path.join(run_root, "w4-run")
    summary["target"] = target
    summary["repo_before"] = {d: tree_hashes(os.path.join(REPO_ROOT, d)) for d in repo_dirs}
    shutil.copytree(summary["dist"], target)
    os.mkdir(tmp)
    size, count = tree_size(target)
    summary.update(bundle_bytes=size, bundle_files=count,
                   has_reference_samples=os.path.isdir(os.path.join(target, "_internal", "참고자료")),
                   has_check_exe=os.path.isfile(os.path.join(target, "HAZOP-check.exe")))
    env = child_env(tmp)
    start = time.time()
    run_dir = None
    if not args.app_only:
        inputs = os.path.join(tmp, "inputs")
        make_inputs(inputs)
        expect = os.path.join(tmp, "expect.json")
        with open(expect, "w", encoding="utf-8") as fh:
            json.dump(expected_datas(), fh, ensure_ascii=False)
        check_exe, scripts = os.path.join(target, "HAZOP-check.exe"), os.path.join(inputs, "scripts")
        rc, sec, text = run([check_exe, os.path.join(scripts, "w4_flow.py"), "--samples", inputs, "--expect",
                             expect, "--result", os.path.join(out, "flow.json")], env, tmp,
                            os.path.join(out, "flow.log"))
        run_dir = next((ln.split("=", 1)[1].strip() for ln in text.splitlines() if ln.startswith("RUN_DIR=")), None)
        run_dir = run_dir if run_dir and run_dir != "None" else None
        summary["steps"]["flow"] = {"rc": rc, "sec": sec, "run_dir": run_dir,
                                    "lines": [ln.strip() for ln in text.splitlines() if ln.startswith("  [")]}
        print("flow rc=%s %ss" % (rc, sec))

        kenv = dict(env, HAZOP_WORK_ROOT=inputs, QT_QPA_PLATFORM="windows")
        inputs_before = tree_hashes(inputs)
        rc, sec, text = run([check_exe, os.path.join(scripts, "check_kg_screen.py"), "--skip-tests",
                             "--screenshots", png], kenv, tmp, os.path.join(out, "check_kg_screen.log"))
        summary["checks"]["inputs_unchanged_by_kg_check"] = tree_hashes(inputs) == inputs_before
        summary["steps"]["check_kg_screen"] = {
            "rc": rc, "sec": sec,
            "lines": [ln.strip() for ln in text.splitlines() if ln.strip().startswith(("[OK]", "[FAIL]", "결과"))]}
        print("check_kg_screen rc=%s %ss" % (rc, sec))
    else:
        summary["steps"]["flow"] = summary["steps"]["check_kg_screen"] = {"rc": "skipped(--app-only)"}

    app_exe = os.path.join(target, "HAZOP.exe")
    cmd = [app_exe, "--screenshots", png, "--settings", os.path.join(tmp, "settings.json")]
    if run_dir:
        cmd += ["--run", run_dir]
    rc, sec, _ = run(cmd, env, tmp, os.path.join(out, "app.log"))
    summary["steps"]["app_screenshots"] = {"rc": rc, "sec": sec}
    log_path = os.path.join(env["HAZOP_WORK_ROOT"], "logs", "app.log")
    log1 = read_text(log_path)
    rc2, sec2, text2 = run([app_exe, "--w4-unknown-option"], env, tmp, os.path.join(out, "app-badarg.log"))
    bad_settings = os.path.join(tmp, "bad-settings.json")
    with open(bad_settings, "w", encoding="utf-8") as fh:
        fh.write("[]")
    rc3, sec3, _ = run([app_exe, "--settings", bad_settings], env, tmp, os.path.join(out, "app-unhandled.log"),
                       timeout=60)
    log3 = read_text(log_path)
    if os.path.isfile(log_path):
        shutil.copyfile(log_path, os.path.join(out, "work-logs-app.log"))
    summary["steps"]["app_bad_option"] = {"rc": rc2, "sec": sec2}
    summary["steps"]["app_unhandled"] = {"rc": rc3, "sec": sec3}
    summary["checks"]["app_log_started"] = "시작 pid=" in log1
    summary["checks"]["app_bad_option_rc2"] = rc2 == 2 and "unrecognized arguments" in text2
    tail = log3[len(log1):]
    summary["checks"]["app_log_unhandled"] = "미처리 예외" in tail and "설정 파일이 JSON 객체가 아님" in tail
    want = APP_PNG if args.app_only else FULL_PNG
    summary["png"] = sorted(os.path.basename(p) for p in glob.glob(os.path.join(png, "*.png")))
    summary["checks"]["png_fresh_problems"] = fresh_problems(png, start, want)
    print("app rc=%s %ss png=%s, 잘못된 옵션 rc=%s" % (rc, sec, summary["png"], rc2))
    summary["checks"]["repo_unchanged"] = {d: tree_hashes(os.path.join(REPO_ROOT, d)) for d in repo_dirs} \
        == summary.pop("repo_before")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dist", required=True, help="빌드 결과 one-folder(<out>/dist/HAZOP-verify 또는 HAZOP)")
    ap.add_argument("--target-base", required=True,
                    help="검증 사본을 만들 상위 폴더(저장소 밖, 예: %%TEMP%%\\한글테스트). 실행마다 새 하위 폴더")
    ap.add_argument("--out", required=True, help="결과 상위 폴더(실행마다 새 하위 폴더를 만든다)")
    ap.add_argument("--run-name", help="새 하위 폴더 이름(기본 verify-<시각>-<uuid8>). 이미 있으면 실패")
    ap.add_argument("--app-only", action="store_true", help="배포용 빌드: HAZOP.exe 단계만(검증 exe 단계는 건너뜀)")
    args = ap.parse_args(argv)
    dist, base, out_parent = (os.path.abspath(p) for p in (args.dist, args.target_base, args.out))

    pre = []
    if not os.path.isfile(os.path.join(dist, "HAZOP.exe")):
        pre.append("dist에 HAZOP.exe 없음: %s" % dist)
    if not args.app_only and not os.path.isfile(os.path.join(dist, "HAZOP-check.exe")):
        pre.append("dist에 HAZOP-check.exe 없음 — 검증용 빌드(--with-check)가 아님. 배포용이면 --app-only")
    if overlaps(out_parent, REPO_ROOT) or overlaps(out_parent, dist) or overlaps(out_parent, base):
        pre.append("--out이 저장소·dist·대상 상위 폴더와 겹침: %s" % out_parent)
    pre += base_problems(base, dist)
    if pre:
        for p in pre:
            print("중단: %s" % p)
        return 2
    try:
        run_root = new_run_root(base, args.run_name)
    except (FileExistsError, ValueError) as e:
        print("중단: 새 실행 폴더를 만들 수 없음(기존 폴더는 지우지 않음): %s" % e)
        return 2

    summary = {"dist": dist, "run_root": run_root, "app_only": args.app_only, "steps": {}, "errors": {},
               "checks": {}}
    repo_dirs = ("출력", "자료저장소")
    out = None
    try:
        os.makedirs(out_parent, exist_ok=True)
        out = tempfile.mkdtemp(prefix=time.strftime("run-%Y%m%d-%H%M%S-"), dir=out_parent)
        summary["out"] = out
        steps(args, summary, run_root, out, repo_dirs)
    except Exception as e:  # 단계 밖 예외도 남긴다
        summary["errors"]["main"] = "%s: %s" % (type(e).__name__, e)
    finally:
        summary.pop("repo_before", None)
        try:
            shutil.rmtree(run_root)  # 이번 실행에서 만든 폴더만
        except OSError as e:
            summary["errors"]["cleanup"] = "%s: %s" % (type(e).__name__, e)
        summary["run_root_removed"] = not os.path.exists(run_root)
    checks, st = summary["checks"], summary["steps"]
    rc_ok = all(st.get(k, {}).get("rc") in (0, "skipped(--app-only)")
                for k in ("flow", "check_kg_screen", "app_screenshots"))
    summary["passed"] = bool(
        rc_ok and not summary["errors"] and summary["run_root_removed"]
        and not checks.get("png_fresh_problems", ["미실행"])
        and checks.get("repo_unchanged") and checks.get("app_log_started") and checks.get("app_bad_option_rc2")
        and checks.get("app_log_unhandled")
        and (args.app_only or checks.get("inputs_unchanged_by_kg_check"))
        and summary.get("has_reference_samples") is False
        and summary.get("has_check_exe") is (not args.app_only))
    if out:
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        print("결과 폴더 %s" % out)
    print("묶음 %.1f MB, 파일 %s개, 검사 %s, 오류 %s, 결과 %s"
          % ((summary.get("bundle_bytes") or 0) / 1048576, summary.get("bundle_files"), checks,
             summary["errors"] or "없음", "통과" if summary["passed"] else "실패"))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
