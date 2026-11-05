"""PyInstaller one-folder 빌드 준비·실행 (docs/2026-11-05-packaging W4, T2 결정 D1·D5안).

기본 동작: 저장소 밖 출력 폴더에 spec(HAZOP.spec)과 datas 목록(datas.json)만 쓴다. --build를 주면 빌드한다.
  <전용 venv python> scripts/build_package.py --out %TEMP%\\hazop-w4 [--build] [--with-check]

- 입구: scripts/run_app.py → 실행 파일 HAZOP.exe(창 프로그램, 콘솔 없음). 결과는 <out>/dist/HAZOP/(one-folder, 배포용).
  런타임 훅 packaging/rthook_applog.py: <작업 루트>/logs/app.log에 logging·stdout·stderr·미처리 예외를 남긴다(HAZOP.exe만).
- datas: 템플릿 2개, hazop/kg/vendor, 기획서/HAZOP기법지침.md, 데이터/이탈후보·기준표·패턴, scripts/extract_drawio.py·
  build_graph.py(화면이 importlib로 읽는 파일, hazop/app/data.py SCRIPT_NAMES). 참고자료/ 샘플은 넣지 않는다(D5안).
- hiddenimports: collect_submodules("hazop") + 두 스크립트 모듈(스크립트가 가져오는 표준 라이브러리까지 묶이게).
- excludes: anthropic·httpx(D1, 배포본 제외), pdfplumber(전용 venv에 없음, PDF 어댑터는 묶음 범위 밖).
- --with-check: 검증 전용 실행 파일 HAZOP-check.exe(입구 packaging/check_entry.py)를 함께 만들고, 결과 폴더 이름을
  <out>/dist/HAZOP-verify/로 바꾼다(배포용 HAZOP/과 섞이지 않게). 파일 경로로 받은 .py를 실행하는 도구라 배포하지 않는다.
- 빌드 뒤 검사(check_dist): 배포용 폴더에는 HAZOP.exe만, 검증용 폴더에는 HAZOP.exe·HAZOP-check.exe가 있어야 한다.
- 경고 파일: 두 Analysis가 같은 warn-HAZOP.txt를 덮어쓰므로 Analysis마다 warn-HAZOP-app.txt·warn-HAZOP-check.txt로 복사한다.
출력 폴더는 저장소 밖이어야 한다(저장소 안이면 거부). 네트워크를 쓰지 않는다(UPX도 쓰지 않음).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

APP_NAME = "HAZOP"
CHECK_NAME = "HAZOP-check"
VERIFY_DIST = "HAZOP-verify"  # --with-check 결과 폴더 이름
RUNTIME_HOOK = "packaging/rthook_applog.py"
ENTRY = "scripts/run_app.py"
CHECK_ENTRY = "packaging/check_entry.py"
# 묶음에 넣는 파일·폴더(저장소 기준 상대 경로, 묶음 안에서도 같은 상대 위치)
DATA_FILES = (
    "hazop/viewer/template.html",
    "hazop/kg/screen_template.html",
    "기획서/HAZOP기법지침.md",
    "scripts/extract_drawio.py",
    "scripts/build_graph.py",
)
DATA_DIRS = (
    "hazop/kg/vendor",
    "데이터/이탈후보",
    "데이터/기준표",
    "데이터/패턴",
)
EXCLUDED_DIRS = ("참고자료",)  # D5안: 샘플 도면(28 MB)은 넣지 않는다
EXCLUDES = ("anthropic", "httpx", "pdfplumber")
SCRIPT_MODULES = ("extract_drawio", "build_graph")
# HAZOP-check.exe가 실행할 검사·준비 스크립트(저장소 밖 사본에서 실행)가 가져오는 모듈을 묶기 위한 이름
CHECK_MODULES = ("check_kg_screen", "check_kg", "check_kg_algo", "check_kg_renderer", "build_kg", "analyze_kg",
                 "analyze", "extract_drawio", "build_graph")


def datas_list(repo_root=REPO_ROOT):
    """[(저장소 상대 원본 파일, 묶음 안 대상 폴더)] — '/' 구분, 정렬. 빠진 파일·폴더는 FileNotFoundError."""
    out = []
    for rel in DATA_FILES:
        if not os.path.isfile(os.path.join(repo_root, rel)):
            raise FileNotFoundError("datas 파일 없음: %s" % rel)
        out.append((rel, os.path.dirname(rel)))
    for rel in DATA_DIRS:
        top = os.path.join(repo_root, rel)
        if not os.path.isdir(top):
            raise FileNotFoundError("datas 폴더 없음: %s" % rel)
        for d, dirs, files in os.walk(top):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            for f in sorted(files):
                src = os.path.relpath(os.path.join(d, f), repo_root).replace("\\", "/")
                out.append((src, os.path.dirname(src)))
    return sorted(out)


def spec_text(repo_root=REPO_ROOT, with_check=False):
    """PyInstaller spec 원문. 경로는 JSON(ASCII 이스케이프) 문자열로 넣어 한글 경로의 인코딩 문제를 피한다."""
    root = os.path.abspath(repo_root)
    datas = [[os.path.join(root, *src.split("/")), dest.replace("/", os.sep)] for src, dest in datas_list(root)]
    lines = [
        "# 자동 생성: scripts/build_package.py (직접 고치지 않음). PyInstaller 6.22, one-folder.",
        "import json, os, sys",
        "from PyInstaller.utils.hooks import collect_submodules",
        "REPO = json.loads(%s)" % json.dumps(json.dumps(root)),
        "sys.path.insert(0, REPO)  # collect_submodules('hazop')가 저장소의 hazop을 찾게",
        "PATHEX = [REPO, os.path.join(REPO, 'scripts')]",
        "DATAS = [tuple(x) for x in json.loads(%s)]" % json.dumps(json.dumps(datas)),
        "EXCLUDES = %r" % list(EXCLUDES),
        "HIDDEN = collect_submodules('hazop') + %r" % list(SCRIPT_MODULES),
        "import shutil",
        "def keep_warn(tag):  # 두 Analysis가 같은 경고 파일을 덮어쓰므로 Analysis마다 복사해 둔다",
        "    w = globals().get('WARNFILE')",
        "    if w and os.path.isfile(w):",
        "        shutil.copyfile(w, w[:-4] + '-' + tag + '.txt')",
        "a = Analysis([os.path.join(REPO, %r)], pathex=PATHEX, datas=DATAS, hiddenimports=HIDDEN," % ENTRY,
        "             runtime_hooks=[os.path.join(REPO, %r)], excludes=EXCLUDES, noarchive=False)" % RUNTIME_HOOK,
        "keep_warn('app')",
        "pyz = PYZ(a.pure)",
        "exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=%r, console=False, upx=False)" % APP_NAME,
        "parts = [exe, a.binaries, a.datas]",
    ]
    if with_check:
        lines += [
            "# 검증 전용(배포본 제외): 저장소 밖 사본의 검사 스크립트를 묶인 인터프리터·hazop으로 실행",
            "c = Analysis([os.path.join(REPO, %r)], pathex=PATHEX, datas=DATAS," % CHECK_ENTRY,
            "             hiddenimports=collect_submodules('hazop') + %r, excludes=EXCLUDES, noarchive=False)"
            % list(CHECK_MODULES),
            "keep_warn('check')",
            "cpyz = PYZ(c.pure)",
            "cexe = EXE(cpyz, c.scripts, [], exclude_binaries=True, name=%r, console=True, upx=False)" % CHECK_NAME,
            "parts += [cexe, c.binaries, c.datas]",
        ]
    lines.append("coll = COLLECT(*parts, upx=False, name=%r)" % (VERIFY_DIST if with_check else APP_NAME))
    return "\n".join(lines) + "\n"


def inside(path, root):
    path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # 다른 드라이브
        return False


def write_spec(out_dir, with_check=False, repo_root=REPO_ROOT):
    """<out>/HAZOP.spec, <out>/datas.json을 쓰고 spec 경로를 돌려준다. out이 저장소 안이면 ValueError."""
    if inside(out_dir, repo_root):
        raise ValueError("출력 폴더가 저장소 안임(산출물을 저장소에 남기지 않음): %s" % out_dir)
    os.makedirs(out_dir, exist_ok=True)
    spec = os.path.join(out_dir, APP_NAME + ".spec")
    with open(spec, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(spec_text(repo_root, with_check))
    with open(os.path.join(out_dir, "datas.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"datas": datas_list(repo_root), "excluded_dirs": list(EXCLUDED_DIRS), "excludes": list(EXCLUDES),
                   "with_check": with_check}, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return spec


def dist_dir(out_dir, with_check=False):
    return os.path.join(out_dir, "dist", VERIFY_DIST if with_check else APP_NAME)


def check_dist(out_dir, with_check=False):
    """빌드 결과 폴더 검사. 문제 목록(빈 목록 = 통과): 배포용에는 HAZOP-check.exe가 없어야 한다."""
    d = dist_dir(out_dir, with_check)
    probs = []
    if not os.path.isfile(os.path.join(d, APP_NAME + ".exe")):
        probs.append("%s.exe 없음: %s" % (APP_NAME, d))
    has_check = os.path.isfile(os.path.join(d, CHECK_NAME + ".exe"))
    if with_check and not has_check:
        probs.append("검증용 빌드에 %s.exe 없음" % CHECK_NAME)
    if not with_check and has_check:
        probs.append("배포용 빌드에 검증 전용 %s.exe가 있음" % CHECK_NAME)
    if not with_check and os.path.isdir(os.path.join(out_dir, "dist", VERIFY_DIST)):
        probs.append("배포용 출력 폴더에 검증용 결과(%s)가 함께 있음 — 출력 폴더를 나눌 것" % VERIFY_DIST)
    return probs


def build(spec, out_dir):
    """PyInstaller 실행. 로그는 <out>/build.log. 반환: 종료 코드."""
    cmd = [sys.executable, "-m", "PyInstaller", spec, "--noconfirm", "--clean",
           "--distpath", os.path.join(out_dir, "dist"), "--workpath", os.path.join(out_dir, "build")]
    log = os.path.join(out_dir, "build.log")
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        fh.write("명령: %s\n" % " ".join(cmd))
        fh.flush()
        proc = subprocess.run(cmd, cwd=out_dir, stdout=fh, stderr=subprocess.STDOUT)
    print("빌드 로그: %s (종료 코드 %d)" % (log, proc.returncode))
    return proc.returncode


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "hazop-build"),
                    help="spec·build·dist를 둘 저장소 밖 폴더(기본 %%TEMP%%\\hazop-build)")
    ap.add_argument("--build", action="store_true", help="spec을 쓴 뒤 PyInstaller로 빌드")
    ap.add_argument("--with-check", action="store_true", help="검증 전용 HAZOP-check.exe를 함께 빌드(배포본 제외)")
    args = ap.parse_args(argv)
    out = os.path.abspath(args.out)
    try:
        spec = write_spec(out, args.with_check)
    except (ValueError, FileNotFoundError) as e:
        print("중단: %s" % e)
        return 2
    print("spec: %s" % spec)
    print("datas %d개: %s" % (len(datas_list()), os.path.join(out, "datas.json")))
    if not args.build:
        return 0
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("중단: PyInstaller가 없음. 전용 venv(%USERPROFILE%\\.hazop\\venv-py312) python으로 실행")
        return 2
    rc = build(spec, out)
    if rc != 0:
        return rc
    probs = check_dist(out, args.with_check)
    print("결과 폴더 검사(%s): %s" % (dist_dir(out, args.with_check), "통과" if not probs else "; ".join(probs)))
    return 0 if not probs else 3


if __name__ == "__main__":
    sys.exit(main())
