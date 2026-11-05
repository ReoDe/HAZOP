"""PyInstaller one-folder 빌드 준비·실행 (docs/2026-11-05-packaging W4, T2 결정 D1·D5안).

기본 동작: 저장소 밖 출력 폴더에 spec(HAZOP.spec)과 datas 목록(datas.json)만 쓴다. --build를 주면 빌드한다.
  <전용 venv python> scripts/build_package.py --out %TEMP%\\hazop-w4 [--build] [--with-check]

- 입구: scripts/run_app.py → 실행 파일 HAZOP.exe(창 프로그램, 콘솔 없음). 결과는 <out>/dist/HAZOP/(one-folder, 배포용).
  런타임 훅 packaging/rthook_applog.py: <작업 루트>/logs/app.log에 logging·stdout·stderr·미처리 예외를 남긴다(HAZOP.exe만).
- datas: 템플릿 2개, hazop/kg/vendor, 기획서/HAZOP기법지침.md, 데이터/이탈후보·기준표·패턴, scripts/extract_drawio.py·
  build_graph.py(화면이 importlib로 읽는 파일, hazop/app/data.py SCRIPT_NAMES), licenses/(제3자 고지, D9).
  참고자료/ 샘플은 넣지 않는다(D5안).
- hiddenimports: collect_submodules("hazop") + 두 스크립트 모듈(스크립트가 가져오는 표준 라이브러리까지 묶이게).
- excludes: anthropic·httpx(D1, 배포본 제외), pdfplumber(전용 venv에 없음, PDF 어댑터는 묶음 범위 밖).
- --with-check: 검증 전용 실행 파일 HAZOP-check.exe(입구 packaging/check_entry.py)를 함께 만들고, 결과 폴더 이름을
  <out>/dist/HAZOP-verify/로 바꾼다(배포용 HAZOP/과 섞이지 않게). 파일 경로로 받은 .py를 실행하는 도구라 배포하지 않는다.
- 빌드 뒤 검사(check_dist): 배포용 폴더에는 HAZOP.exe만, 검증용 폴더에는 HAZOP.exe·HAZOP-check.exe가 있어야 한다.
- 경고 파일: 두 Analysis가 같은 warn-HAZOP.txt를 덮어쓰므로 Analysis마다 warn-HAZOP-app.txt·warn-HAZOP-check.txt로 복사한다.
- 인터프리터 확인(D10): --build는 전용 venv(%USERPROFILE%\\.hazop\\venv-py312, 기반 CPython 3.12.10)에서만 한다.
  다른 인터프리터면 중단한다(rc=2). --allow-other-python으로 우회할 수 있다.
- PATH 통제(D10): PyInstaller는 의존 DLL과 Qt용 OpenSSL을 PATH에서도 찾는다. 그래서 PATH를 venv Scripts·기반 CPython·
  기반 CPython DLLs·Windows System32로만 두고 실행한다(JDK·Git 등 사용자 도구 경로 제외). 다른 환경변수는 그대로 둔다.
- Qt OpenSSL TLS 플러그인 제외(D10): PySide6/plugins/tls/qopensslbackend.dll을 binaries에서 뺀다. 실행 PC의 PATH에 있는
  libssl-3-x64.dll을 Qt가 읽지 않게 하기 위해서다. Qt TLS는 Windows Schannel 백엔드(qschannelbackend.dll)를 쓴다.
- 빌드 뒤 출처 검사(D10, check_sources): build/HAZOP/COLLECT-00.toc의 형식(([(이름, 출처, 종류), ...],), 3열 문자열,
  EXECUTABLE HAZOP.exe 있음)을 확인하고, 바이너리(종류 BINARY·EXTENSION이거나 이름·출처 확장자 .dll·.pyd·.exe)의
  출처가 절대 경로이며 venv·기반 CPython 안인지 본다. EXECUTABLE은 <out>/build 안, SYMLINK는 묶음 밖을 가리키면 안 된다.
  출처와 관계없이 이름 거부 목록(ucrtbase, api-ms-win-*, lib(ssl|crypto)-3-x64)과 제외 플러그인이 TOC나 결과 폴더에
  있으면 실패한다. 하나라도 걸리면 rc=3.
출력 폴더는 저장소 밖이어야 한다(저장소 안이면 거부). 네트워크를 쓰지 않는다(UPX도 쓰지 않음).
"""

import argparse
import ast
import json
import os
import platform
import re
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
    "licenses",  # 제3자 라이선스 고지(W6, D9)
)
EXCLUDED_DIRS = ("참고자료",)  # D5안: 샘플 도면(28 MB)은 넣지 않는다
EXCLUDES = ("anthropic", "httpx", "pdfplumber")
SCRIPT_MODULES = ("extract_drawio", "build_graph")
# D10: Qt TLS 플러그인은 허용 목록만 묶는다(Schannel·cert-only). OpenSSL 백엔드(qopensslbackend.dll)는 실행 PC PATH의
# libssl-3-x64.dll을 읽으므로 뺀다. 묶음 안 이름과 출처 실경로의 긴 파일명을 모두 본다(이름 바꾸기·8.3 단축명·링크 별칭).
TLS_PLUGIN_DIR = "pyside6/plugins/tls/"
TLS_ALLOWED = ("qschannelbackend.dll", "qcertonlybackend.dll")
TLS_EXCLUDED = ("qopensslbackend.dll",)
# D10: 출처와 관계없이 묶음에 있으면 안 되는 이름(UCRT는 Windows 10 이상 시스템 구성요소, OpenSSL -x64는 PATH 경유)
FORBIDDEN_NAME = re.compile(r"^(ucrtbase\.dll|api-ms-win-.*\.dll|lib(ssl|crypto)-3-x64\.dll)$", re.I)
VENV_DIR = os.path.join(os.path.expanduser("~"), ".hazop", "venv-py312")  # 전용 venv(T2 D4)
# 기반 CPython 판(T2 D4). 패치 판을 올리면 이 상수와 packaging/README.md·requirements를 함께 바꾼다.
PYTHON_VERSION = (3, 12, 10)
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
        "sys.path.insert(0, os.path.join(REPO, 'scripts'))",
        "from build_package import drop_binaries  # D10: TLS 플러그인 허용 목록(사후 검사와 같은 규칙)",
        "def keep_warn(tag):  # 두 Analysis가 같은 경고 파일을 덮어쓰므로 Analysis마다 복사해 둔다",
        "    w = globals().get('WARNFILE')",
        "    if w and os.path.isfile(w):",
        "        shutil.copyfile(w, w[:-4] + '-' + tag + '.txt')",
        "a = Analysis([os.path.join(REPO, %r)], pathex=PATHEX, datas=DATAS, hiddenimports=HIDDEN," % ENTRY,
        "             runtime_hooks=[os.path.join(REPO, %r)], excludes=EXCLUDES, noarchive=False)" % RUNTIME_HOOK,
        "keep_warn('app')",
        "a.binaries = drop_binaries(a.binaries)",
        "a.datas = drop_binaries(a.datas)",
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
            "c.binaries = drop_binaries(c.binaries)",
            "c.datas = drop_binaries(c.datas)",
            "cpyz = PYZ(c.pure)",
            "cexe = EXE(cpyz, c.scripts, [], exclude_binaries=True, name=%r, console=True, upx=False)" % CHECK_NAME,
            "parts += [cexe, c.binaries, c.datas]",
        ]
    lines.append("coll = COLLECT(*parts, upx=False, name=%r)" % (VERIFY_DIST if with_check else APP_NAME))
    return "\n".join(lines) + "\n"


def long_real(path):
    """실경로(링크·junction 해석)의 긴 파일명. 파일이 있으면 GetLongPathNameW로 8.3 단축명을 펼친다."""
    p = os.path.realpath(path)
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetLongPathNameW(p, buf, 32768)
        if 0 < n < 32768:
            p = buf.value
    except (AttributeError, OSError):
        pass
    return p


def _base(path):
    return os.path.basename(str(path).replace("\\", "/"))


def tls_rejected(dest, src):
    """Qt TLS 플러그인 규칙(D10) 위반 사유, 없으면 None. 묶음 안 이름이 plugins/tls/ 아래인데 허용 목록 밖이거나,
    출처(실경로의 긴 파일명)가 plugins/tls/ 아래 허용 목록 밖이거나, 어느 이름이든 qopensslbackend.dll이면 위반."""
    d = str(dest).replace("\\", "/").lower()
    real = long_real(src) if os.path.isabs(src) else str(src)
    r = real.replace("\\", "/").lower()
    names = {_base(d), _base(str(src)).lower(), _base(r)}
    if names & set(TLS_EXCLUDED):
        return "Qt OpenSSL TLS 플러그인"
    if d.startswith(TLS_PLUGIN_DIR) and _base(d) not in TLS_ALLOWED:
        return "plugins/tls/ 허용 목록 밖(묶음 안 이름)"
    if "/plugins/tls/" in r and _base(r) not in TLS_ALLOWED:
        return "plugins/tls/ 허용 목록 밖(출처)"
    return None


def drop_binaries(toc):
    """spec에서 Analysis binaries·datas에 적용: TLS 플러그인 규칙에 걸리는 항목을 뺀다(D10)."""
    return [x for x in toc if not tls_rejected(x[0], x[1])]


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


def windows_dir():
    """Windows 폴더(GetSystemWindowsDirectoryW, 실패하면 SystemRoot 환경변수)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.kernel32.GetSystemWindowsDirectoryW(buf, 260):
            return buf.value
    except (AttributeError, OSError):
        pass
    return os.environ.get("SystemRoot", r"C:\Windows")


def build_path_dirs(exe=None, base=None, windir=None):
    """PyInstaller 실행 PATH(D10): venv Scripts, 기반 CPython, 기반 CPython DLLs, Windows System32 — 이 4개뿐."""
    base = base or sys.base_prefix
    return [os.path.dirname(os.path.abspath(exe or sys.executable)), base, os.path.join(base, "DLLs"),
            os.path.join(windir or windows_dir(), "System32")]


def allowed_roots(prefix=None, base=None):
    """묶음 바이너리의 허용 출처(D10): venv, 기반 CPython. Windows 폴더는 허용하지 않는다."""
    return [prefix or sys.prefix, base or sys.base_prefix]


def _key(path):
    return os.path.normcase(long_real(path))


def python_problems(prefix=None, base=None, version=None, impl=None, venv_dir=VENV_DIR):
    """--build 전 인터프리터 확인(D10). 문제 목록(빈 목록 = 전용 venv, 기반 CPython PYTHON_VERSION).
    세 경로 모두 실경로(링크·단축명 해석)+normcase로 비교한다."""
    prefix, base = prefix or sys.prefix, base or sys.base_prefix
    version, impl = version or tuple(sys.version_info[:3]), impl or platform.python_implementation()
    probs = []
    if _key(prefix) != _key(venv_dir):
        probs.append("전용 venv가 아님: sys.prefix=%s (기대 %s)" % (prefix, venv_dir))
    if _key(prefix) == _key(base):
        probs.append("venv가 아님(sys.prefix = sys.base_prefix): %s" % prefix)
    if impl != "CPython" or tuple(version) != PYTHON_VERSION:
        probs.append("기반 인터프리터가 CPython %s가 아님: %s %s"
                     % (".".join(map(str, PYTHON_VERSION)), impl, ".".join(map(str, version))))
    return probs


def collect_toc_path(out_dir):
    """COLLECT 단계 TOC. 검증용·배포용 모두 spec 이름(HAZOP) 아래에 생긴다."""
    return os.path.join(out_dir, "build", APP_NAME, "COLLECT-00.toc")


def read_toc(path):
    """PyInstaller COLLECT TOC 파일 → [(묶음 안 이름, 출처, 종류)]. 형식이 다르면 ValueError.
    형식: 최상위가 원소 1개짜리 튜플이고 그 안이 목록, 각 항목은 문자열 3개, EXECUTABLE HAZOP.exe가 있어야 한다."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        data = ast.literal_eval(text)
    except (SyntaxError, ValueError, MemoryError, RecursionError) as e:
        raise ValueError("TOC 파싱 실패: %s" % e)
    if not (isinstance(data, tuple) and len(data) == 1 and isinstance(data[0], list)):
        raise ValueError("TOC 최상위 구조가 ([...],)가 아님")
    rows = []
    for i, x in enumerate(data[0]):
        if not (isinstance(x, (tuple, list)) and len(x) == 3 and all(isinstance(v, str) for v in x)):
            raise ValueError("TOC %d번 항목이 문자열 3열이 아님: %r" % (i, x))
        rows.append(tuple(x))
    if not any(n.replace("\\", "/") == APP_NAME + ".exe" and t == "EXECUTABLE" for n, _, t in rows):
        raise ValueError("TOC에 EXECUTABLE %s.exe가 없음" % APP_NAME)
    return rows


BINARY_TYPES = ("BINARY", "EXTENSION", "EXECUTABLE")
BINARY_EXTS = (".dll", ".pyd", ".exe")


def foreign_binaries(toc, roots, work_dir):
    """허용 루트 밖 출처 바이너리 [(이름, 출처, 종류)]. 빈 목록 = 통과.
    바이너리 = 종류가 BINARY·EXTENSION·EXECUTABLE이거나 이름·출처의 확장자가 .dll·.pyd·.exe. 출처는 절대 경로여야 한다
    (상대 경로 거부). EXECUTABLE은 work_dir 안. SYMLINK는 출처 대신 링크 대상이 묶음 안(이름 기준 상대)이어야 한다."""
    out = []
    for name, src, typ in toc:
        if typ == "SYMLINK":
            target = os.path.normpath(os.path.join(os.path.dirname(name), src))
            if os.path.isabs(src) or os.path.splitdrive(src)[0] or target == ".." or target.startswith(".." + os.sep):
                out.append((name, src, typ))
            continue
        if typ not in BINARY_TYPES and not name.lower().endswith(BINARY_EXTS) \
                and not src.lower().endswith(BINARY_EXTS):
            continue
        ok = [work_dir] if typ == "EXECUTABLE" else roots
        if not os.path.isabs(src) or not any(inside(src, r) for r in ok):
            out.append((name, src, typ))
    return out


def forbidden_entries(toc):
    """이름 거부 목록(묶음 안 이름, 출처 이름, 출처 실경로의 긴 파일명)이나 TLS 플러그인 규칙(tls_rejected)에 걸리는 항목."""
    out = []
    for n, s, t in toc:
        names = [_base(n), _base(s)] + ([_base(long_real(s))] if os.path.isabs(s) else [])
        if any(FORBIDDEN_NAME.match(x) for x in names) or tls_rejected(n, s):
            out.append((n, s, t))
    return out


def forbidden_files(dist):
    """결과 폴더에서 이름 거부 목록·TLS 규칙(_internal 아래 묶음 안 이름 기준)에 걸리는 파일(dist 상대 경로)."""
    out = []
    for d, _, files in os.walk(dist):
        for f in files:
            full = os.path.join(d, f)
            rel = os.path.relpath(full, dist).replace("\\", "/")
            inner = rel[len("_internal/"):] if rel.lower().startswith("_internal/") else rel
            if FORBIDDEN_NAME.match(f) or FORBIDDEN_NAME.match(_base(long_real(full))) or tls_rejected(inner, full):
                out.append(rel)
    return sorted(out)


def check_sources(out_dir, with_check=False, roots=None):
    """빌드 결과 바이너리 검사(D10). 문제 목록(빈 목록 = 통과): TOC 형식, 허용 루트 밖 출처, 이름 거부 목록·제외
    플러그인(TOC와 결과 폴더 모두)."""
    toc_path = collect_toc_path(out_dir)
    if not os.path.isfile(toc_path):
        return ["COLLECT TOC 없음: %s" % toc_path]
    try:
        toc = read_toc(toc_path)
    except (ValueError, OSError) as e:
        return ["COLLECT TOC 형식 오류: %s" % e]
    probs = ["허용 루트 밖 출처 %s: %s (%s)" % (t, n, s)
             for n, s, t in foreign_binaries(toc, roots or allowed_roots(), os.path.join(out_dir, "build"))]
    probs += ["거부 목록·제외 대상이 TOC에 있음: %s (%s)" % (n, s) for n, s, _ in forbidden_entries(toc)]
    probs += ["거부 목록·제외 대상이 결과 폴더에 있음: %s" % r for r in forbidden_files(dist_dir(out_dir, with_check))]
    return probs


def build(spec, out_dir, path_dirs=None):
    """PyInstaller 실행(PATH 통제, D10). 로그는 <out>/build.log. 반환: 종료 코드."""
    cmd = [sys.executable, "-m", "PyInstaller", spec, "--noconfirm", "--clean",
           "--distpath", os.path.join(out_dir, "dist"), "--workpath", os.path.join(out_dir, "build")]
    env = dict(os.environ)
    for k in [k for k in env if k.upper() == "PATH"]:  # Windows 환경은 대소문자 무시 — 다른 표기의 PATH도 지운다
        del env[k]
    env["PATH"] = os.pathsep.join(path_dirs or build_path_dirs())
    log = os.path.join(out_dir, "build.log")
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        fh.write("명령: %s\nPATH: %s\n" % (" ".join(cmd), env["PATH"]))
        fh.flush()
        proc = subprocess.run(cmd, cwd=out_dir, stdout=fh, stderr=subprocess.STDOUT, env=env)
    print("빌드 로그: %s (종료 코드 %d)" % (log, proc.returncode))
    return proc.returncode


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "hazop-build"),
                    help="spec·build·dist를 둘 저장소 밖 폴더(기본 %%TEMP%%\\hazop-build)")
    ap.add_argument("--build", action="store_true", help="spec을 쓴 뒤 PyInstaller로 빌드")
    ap.add_argument("--with-check", action="store_true", help="검증 전용 HAZOP-check.exe를 함께 빌드(배포본 제외)")
    ap.add_argument("--allow-other-python", action="store_true",
                    help="전용 venv·CPython 3.12.10이 아니어도 빌드(D10 확인 우회, 결과 재현성 보장 없음)")
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
    py_probs = python_problems()
    for p in py_probs:
        print("%s: %s" % ("경고(--allow-other-python)" if args.allow_other_python else "중단", p))
    if py_probs and not args.allow_other_python:
        return 2
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
    src_probs = check_sources(out, args.with_check)
    print("바이너리 검사(%s): %s" % (collect_toc_path(out), "통과" if not src_probs else "실패 %d건" % len(src_probs)))
    for p in src_probs:
        print("  " + p)
    return 0 if not probs and not src_probs else 3


if __name__ == "__main__":
    sys.exit(main())
