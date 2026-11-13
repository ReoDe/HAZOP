"""PyInstaller one-folder 빌드 준비·실행 (docs/units/2026-11-05-packaging W4, T2 결정 D1·D5안).

기본 동작: 저장소 밖 출력 폴더에 spec(HAZOP.spec)과 datas 목록(datas.json)만 쓴다. --build를 주면 빌드한다.
  <전용 venv python> scripts/build_package.py --out %TEMP%\\hazop-w4 [--build] [--with-check]

- 입구: scripts/run_app.py → 실행 파일 HAZOP.exe(창 프로그램, 콘솔 없음). 결과는 <out>/dist/HAZOP/(one-folder, 배포용).
  런타임 훅 packaging/rthook_applog.py: <작업 루트>/logs/app.log에 logging·stdout·stderr·미처리 예외를 남긴다(HAZOP.exe만).
- datas: 템플릿 2개, hazop/kg/vendor, hazop/shell/web(새 웹 화면: html·css·js·묶음 라이브러리 vendor/), 기획서/HAZOP기법지침.md, 데이터/이탈후보·기준표·패턴, scripts/extract_drawio.py·
  extract_pdf.py·build_graph.py(화면이 importlib로 읽는 파일, hazop/app/data.py SCRIPT_NAMES). 참고자료/ 샘플은 넣지 않는다(D5안).
- 제3자 고지(W9, D15): licenses/는 datas(_internal/licenses/)가 아니라 빌드 뒤 결과 폴더의 실행 파일 옆 licenses/로
  복사한다(copy_licenses). 빌드 뒤 검사가 실행 파일 옆 사본이 저장소와 같고 _internal/licenses/가 없는지 본다.
- hiddenimports: hazop 하위 모듈 정적 목록(hazop_modules, spec은 sys.path를 바꾸지 않음) + 세 스크립트 모듈(스크립트가 가져오는 표준 라이브러리까지 묶이게)
  + PDF 어댑터 모듈 pdfplumber·pypdfium2(W9, D15: pdf_vector가 함수 안에서 지연 import)
  + 함수 안에서만 import하는 라이브러리 LAZY_MODULES(openpyxl·networkx: 시작을 빠르게 하려고 쓸 때만 읽음). 빌드 뒤 검사가
  앱 PYZ에 있는지 본다.
- excludes: anthropic·httpx(D1, 배포본 제외). pdfplumber와 의존성(pdfminer.six·Pillow·pypdfium2·charset-normalizer·
  cryptography·cffi·pycparser, packaging/requirements-pdf.txt)은 묶는다(W9, D15). 빌드 뒤 검사가 앱 PYZ(PYZ-00.toc)에
  PDF_REQUIRED_MODULES가 있고 결과 폴더에 _internal/pypdfium2_raw/pdfium.dll이 있는지 본다.
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
- GPL 전용 Qt 모듈 제외(D13, W8-B): Charts·DataVisualization·Graphs·Quick3D(Physics·Xr 포함)·VirtualKeyboard·
  QuickTimeline·ShaderTools와 딸린 파일(QT_EXCLUDED_MODULES)을 spec의 drop_binaries로 빼고, 빌드 뒤 검사에서 TOC나 결과
  폴더에 남아 있으면 rc=3. 의존 관계로 Qt5Compat.GraphicalEffects(ShaderTools 링크)·Qt6SpatialAudio.dll·QtSpatialAudio.pyd도 함께 뺀다.
  판정은 파일 이름 전체(위치 무관)와 PySide6 기준 상대 경로(폴더 규칙)로 한다. 결과 폴더가 없거나 탐색 오류·확인하지
  못한 항목·링크 폴더가 있으면 검사 실패(rc=3).
출력 폴더는 저장소 밖이어야 한다(저장소 안이면 거부). 네트워크를 쓰지 않는다(UPX도 쓰지 않음).
"""

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402

APP_NAME = "HAZOP"
CHECK_NAME = "HAZOP-check"
VERIFY_DIST = "HAZOP-verify"  # --with-check 결과 폴더 이름
RUNTIME_HOOK = "packaging/rthook_applog.py"
VERIFY_HOOK = "packaging/rthook_verify_build.py"  # 검증용 HAZOP.exe에만: 시험 트리거 표지(D18)
ENTRY = "scripts/run_app.py"
CHECK_ENTRY = "packaging/check_entry.py"
# 묶음에 넣는 파일·폴더(저장소 기준 상대 경로, 묶음 안에서도 같은 상대 위치)
DATA_FILES = (
    "hazop/viewer/template.html",
    "hazop/kg/screen_template.html",
    "hazop/kg/schema/registry.json",
    "hazop/kg/schema/expectations.json",
    paths.file_rel("guide"),
    "scripts/extract_drawio.py",
    "scripts/extract_pdf.py",
    "scripts/build_graph.py",
)
# 자원 폴더는 hazop.paths.FOLDERS의 resource 행에서 만든다(묶음 안에서도 같은 상대 위치)
DATA_DIRS = ("hazop/kg/vendor", "hazop/shell/web") + tuple(paths.folder_rel(n) for n, f in paths.FOLDERS.items() if f.root == "resource")
# 패키징 D5안: 저장소에만 있는 자료(샘플 도면·표본)는 넣지 않는다
EXCLUDED_DIRS = tuple(paths.folder_rel(n) for n, f in paths.FOLDERS.items() if f.root == "repo")
EXCLUDES = ("anthropic", "httpx")
SCRIPT_MODULES = ("extract_drawio", "extract_pdf", "build_graph")
# W9(D15): 제3자 고지는 실행 파일 옆 licenses/에 둔다(D9의 _internal/licenses/를 대체, 사용자 결정 2026-11-06)
LICENSES_DIR = "licenses"
# W9(D15): PDF 어댑터. pdf_vector가 pdfplumber를 함수 안에서 import하므로 명시적으로 묶는다.
PDF_MODULES = ("pdfplumber", "pypdfium2")
# 시작 시간 때문에 함수 안에서만 import하는 라이브러리. 정적 분석이 놓쳐도 묶이게 명시하고, 빌드 뒤 앱 PYZ에서 확인한다.
LAZY_MODULES = ("openpyxl", "networkx")
PDF_REQUIRED_MODULES = ("pdfplumber", "pdfminer", "pypdfium2", "pypdfium2_raw", "PIL.Image", "charset_normalizer",
                        "cryptography")
PDFIUM_DLL = ("pypdfium2_raw", "pdfium.dll")  # _internal 아래
# D10: Qt TLS 플러그인은 허용 목록만 묶는다(Schannel·cert-only). OpenSSL 백엔드(qopensslbackend.dll)는 실행 PC PATH의
# libssl-3-x64.dll을 읽으므로 뺀다. 묶음 안 이름과 출처 실경로의 긴 파일명을 모두 본다(이름 바꾸기·8.3 단축명·링크 별칭).
TLS_PLUGIN_DIR = "pyside6/plugins/tls/"
TLS_ALLOWED = ("qschannelbackend.dll", "qcertonlybackend.dll")
TLS_EXCLUDED = ("qopensslbackend.dll",)
# W8-B(D13): 앱이 쓰지 않는 GPL 전용 Qt 모듈과 딸린 파일(DLL·바인딩·qml 폴더·플러그인)은 묶지 않는다. 앱·WebEngine이
# 링크하는 Qt6Quick·Qt6Qml·Qt6QuickWidgets는 남긴다. 근거(SPDX·PE import): docs/units/2026-11-05-packaging/evidence/w8b-module-exclusion.md
# (모듈, 이름 규칙, 폴더 규칙)
# - 이름 규칙: 파일 이름 전체(대소문자 무시)로 위치와 관계없이 판정한다. 설치본 PySide6 6.12.0에서 뽑은 모듈 DLL·바인딩·
#   제외 폴더 안 플러그인 DLL 이름이다. 설치본의 다른 파일과 이름이 겹치지 않는다(겹치는 흔한 이름은 넣지 않는다).
# - 폴더 규칙: PySide6 폴더 기준 상대 경로의 앞부분으로만 판정한다(묶음 안 'PySide6/…', 허용 루트의 site-packages/PySide6
#   아래 출처, 결과 폴더 '_internal/PySide6/…'). 절대 경로의 상위 폴더 이름으로는 판정하지 않는다.
QT_EXCLUDED_MODULES = (
    ("Charts", ("Qt6Charts.dll", "Qt6ChartsQml.dll", "QtCharts.pyd", "qtchartsqml2plugin.dll"), ("qml/QtCharts/",)),
    ("DataVisualization", ("Qt6DataVisualization.dll", "Qt6DataVisualizationQml.dll", "QtDataVisualization.pyd",
                           "datavisualizationqmlplugin.dll"), ("qml/QtDataVisualization/",)),
    ("Graphs", ("Qt6Graphs.dll", "Qt6Graphs2DImpl.dll", "Qt6GraphsWidgets.dll", "QtGraphs.pyd", "QtGraphsWidgets.pyd",
                "graphsplugin.dll"), ("qml/QtGraphs/",)),
    # Physics·Xr·SpatialAudio·Helpers 등, Quick3D에 링크하는 qml 디버그 플러그인·자산 가져오기 플러그인,
    # Qt6Quick3DSpatialAudio만 import하던 Qt6SpatialAudio.dll·바인딩(제외 뒤 묶음 안 importer 0, 총괄 판정)
    ("Quick3D", ("Qt6Quick3D.dll", "Qt6Quick3DAssetImport.dll", "Qt6Quick3DAssetUtils.dll", "Qt6Quick3DEffects.dll",
                 "Qt6Quick3DGlslParser.dll", "Qt6Quick3DHelpers.dll", "Qt6Quick3DHelpersImpl.dll",
                 "Qt6Quick3DIblBaker.dll", "Qt6Quick3DParticleEffects.dll", "Qt6Quick3DParticles.dll",
                 "Qt6Quick3DPhysics.dll", "Qt6Quick3DPhysicsHelpers.dll", "Qt6Quick3DRuntimeRender.dll",
                 "Qt6Quick3DSpatialAudio.dll", "Qt6Quick3DUtils.dll", "Qt6Quick3DXr.dll", "QtQuick3D.pyd",
                 "Qt6SpatialAudio.dll", "QtSpatialAudio.pyd", "qmldbg_quick3dprofiler.dll", "assimp.dll",
                 "qtquick3dassetutilsplugin.dll", "qtquick3deffectplugin.dll", "qtquick3dhelpersimplplugin.dll",
                 "qtquick3dhelpersplugin.dll", "qtquick3dparticleeffectsplugin.dll", "qtquick3dparticles3dplugin.dll",
                 "qtquick3dphysicshelpersplugin.dll", "qquick3dphysicsplugin.dll", "quick3dspatialaudioplugin.dll",
                 "quick3dxrplugin.dll", "qquick3dplugin.dll"),
     ("qml/QtQuick3D/", "plugins/assetimporters/")),
    ("VirtualKeyboard", ("Qt6VirtualKeyboard.dll", "Qt6VirtualKeyboardQml.dll", "Qt6VirtualKeyboardSettings.dll",
                         "qtvirtualkeyboardplugin.dll", "qtvkbcomponentsplugin.dll", "virtualkeyboardplugin.dll",
                         "qtvkblayoutsplugin.dll", "qtvkbhangulplugin.dll", "qtvkbopenwnnplugin.dll",
                         "qtvkbpinyinplugin.dll", "qtvkbtcimeplugin.dll", "qtvkbthaiplugin.dll", "qtvkbpluginsplugin.dll",
                         "qtvkbsettingsplugin.dll", "qtvkbbuiltinstylesplugin.dll", "qtvkbstylesplugin.dll",
                         "qtvkbplugin.dll"), ("qml/QtQuick/VirtualKeyboard/",)),
    ("QuickTimeline", ("Qt6QuickTimeline.dll", "Qt6QuickTimelineBlendTrees.dll", "qtquicktimelineplugin.dll",
                       "qtquicktimelineblendtreesplugin.dll"), ("qml/QtQuick/Timeline/",)),
    ("ShaderTools", ("Qt6ShaderTools.dll",), ()),
    # Qt6ShaderTools.dll에 링크하는 private 플러그인을 쓰는 QML 모듈(남기면 읽을 수 없는 플러그인만 남는다, 총괄 판정)
    ("Qt5Compat.GraphicalEffects(ShaderTools 의존)", ("qtgraphicaleffectsplugin.dll", "qtgraphicaleffectsprivateplugin.dll"),
     ("qml/Qt5Compat/GraphicalEffects/",)),
)
# D10: 출처와 관계없이 묶음에 있으면 안 되는 이름(UCRT는 Windows 10 이상 시스템 구성요소, OpenSSL -x64는 PATH 경유)
FORBIDDEN_NAME = re.compile(r"^(ucrtbase\.dll|api-ms-win-.*\.dll|lib(ssl|crypto)-3-x64\.dll)$", re.I)
VENV_DIR = os.environ.get("HAZOP_VENV") or os.path.join(os.path.expanduser("~"), ".hazop", "venv-py312")  # 전용 venv(T2 D4)
# 기반 CPython 판(T2 D4). 패치 판을 올리면 이 상수와 packaging/README.md·requirements를 함께 바꾼다.
PYTHON_VERSION = (3, 12, 10)
# HAZOP-check.exe가 실행할 검사·준비 스크립트(저장소 밖 사본에서 실행)가 가져오는 모듈을 묶기 위한 이름
CHECK_MODULES = ("check_kg_screen", "check_kg", "check_kg_algo", "check_kg_renderer", "build_kg", "analyze_kg",
                 "analyze", "extract_drawio", "build_graph")


DATA_EXCLUDE = ("hazop/shell/web/test",)   # 웹 단위 시험(시험 모드에서만 쓴다)은 배포본에 넣지 않는다


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
                if any(src == x or src.startswith(x + "/") for x in DATA_EXCLUDE):
                    continue
                out.append((src, os.path.dirname(src)))
    return sorted(out)


def hazop_modules(repo_root=REPO_ROOT):
    """hazop 패키지와 하위 모듈 이름 전부(__init__.py가 있는 폴더만 따라감). spec이 collect_submodules('hazop')를 부르려고
    저장소를 sys.path에 넣지 않아도 되게 spec을 쓸 때 정적으로 뽑는다(D11 후속)."""
    out = []
    base = os.path.join(os.path.abspath(repo_root), "hazop")
    for d, dirs, files in os.walk(base):
        if "__init__.py" not in files:
            dirs[:] = []
            continue
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        rel = os.path.relpath(d, base)
        pkg = ".".join(["hazop"] + ([] if rel == "." else rel.split(os.sep)))
        out.append(pkg)
        out += [pkg + "." + f[:-3] for f in sorted(files) if f.endswith(".py") and f != "__init__.py"]
    return sorted(out)


def spec_text(repo_root=REPO_ROOT, with_check=False):
    """PyInstaller spec 원문. 경로는 JSON(ASCII 이스케이프) 문자열로 넣어 한글 경로의 인코딩 문제를 피한다."""
    root = os.path.abspath(repo_root)
    datas = [[os.path.join(root, *src.split("/")), dest.replace("/", os.sep)] for src, dest in datas_list(root)]
    lines = [
        "# 자동 생성: scripts/build_package.py (직접 고치지 않음). PyInstaller 6.22, one-folder.",
        "import json, os",
        "REPO = json.loads(%s)" % json.dumps(json.dumps(root)),
        "# hazop 하위 모듈은 spec을 쓸 때 정적으로 뽑는다(hazop_modules). spec은 sys.path를 바꾸지 않는다(D11 후속)",
        "HAZOP_MODULES = %r" % hazop_modules(root),
        "PATHEX = [REPO, os.path.join(REPO, 'scripts')]",
        "DATAS = [tuple(x) for x in json.loads(%s)]" % json.dumps(json.dumps(datas)),
        "EXCLUDES = %r" % list(EXCLUDES),
        "HIDDEN = HAZOP_MODULES + %r" % list(SCRIPT_MODULES + PDF_MODULES + LAZY_MODULES),
        "import importlib.util, shutil",
        "# D10 TLS 허용 목록·D13 Qt 모듈 제외(사후 검사와 같은 규칙). scripts/를 sys.path에 넣지 않고 경로로 읽는다(D11 후속)",
        "_BP = importlib.util.spec_from_file_location('build_package', os.path.join(REPO, 'scripts', 'build_package.py'))",
        "build_package = importlib.util.module_from_spec(_BP)",
        "_BP.loader.exec_module(build_package)",
        "drop_binaries = build_package.drop_binaries",
        "def keep_warn(tag):  # 두 Analysis가 같은 경고 파일을 덮어쓰므로 Analysis마다 복사해 둔다",
        "    w = globals().get('WARNFILE')",
        "    if w and os.path.isfile(w):",
        "        shutil.copyfile(w, w[:-4] + '-' + tag + '.txt')",
        "a = Analysis([os.path.join(REPO, %r)], pathex=PATHEX, datas=DATAS, hiddenimports=HIDDEN," % ENTRY,
        "             runtime_hooks=[os.path.join(REPO, h) for h in %r], excludes=EXCLUDES, noarchive=False)"
        % ([RUNTIME_HOOK] + ([VERIFY_HOOK] if with_check else [])),
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
            "             hiddenimports=HAZOP_MODULES + %r, excludes=EXCLUDES, noarchive=False)"
            % list(CHECK_MODULES + PDF_MODULES + LAZY_MODULES),
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


def _norm(path):
    return str(path).replace("\\", "/").lower()


def _pyside_rel_src(src, roots):
    """출처 실경로가 허용 루트의 Lib/site-packages/PySide6 안이면 그 안의 상대 경로(소문자, '/'), 아니면 None."""
    if not os.path.isabs(src):
        return None
    real = long_real(src)
    for root in roots:
        pkg = os.path.join(root, "Lib", "site-packages", "PySide6")
        if inside(real, pkg):
            return _norm(os.path.relpath(os.path.realpath(real), os.path.realpath(pkg)))
    return None


def qt_module_rejected(dest, src=None, roots=None):
    """제외 대상 Qt 모듈(D13) 이름, 없으면 None. 이름 규칙은 묶음 안 이름·출처·출처 실경로(긴 파일명)의 파일 이름으로,
    폴더 규칙은 PySide6 기준 상대 경로(묶음 안 이름 'PySide6/…', 허용 루트 안 출처)로만 본다."""
    d = _norm(dest)
    names = {_base(d)}
    rels = {d[len("pyside6/"):]} if d.startswith("pyside6/") else set()
    if src:
        names.add(_base(_norm(src)))
        if os.path.isabs(src):
            names.add(_base(_norm(long_real(src))))
        r = _pyside_rel_src(src, roots or allowed_roots())
        if r:
            rels.add(r)
    for mod, files, dirs in QT_EXCLUDED_MODULES:
        if names & {f.lower() for f in files} or any(r.startswith(x.lower()) for r in rels for x in dirs):
            return mod
    return None


def drop_binaries(toc, roots=None):
    """spec에서 Analysis binaries·datas에 적용: TLS 플러그인 규칙(D10)과 제외 대상 Qt 모듈(D13)에 걸리는 항목을 뺀다."""
    return [x for x in toc if not tls_rejected(x[0], x[1]) and not qt_module_rejected(x[0], x[1], roots)]


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


def copy_licenses(out_dir, with_check=False, repo_root=REPO_ROOT):
    """저장소 licenses/를 결과 폴더의 실행 파일 옆 licenses/로 복사(W9, D15). 반환: 복사한 폴더."""
    dest = os.path.join(dist_dir(out_dir, with_check), LICENSES_DIR)
    shutil.copytree(os.path.join(repo_root, LICENSES_DIR), dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def _tree_hashes(root):
    """{'/' 구분 상대 경로: sha256}. 폴더가 없으면 빈 dict. 탐색 중 오류(권한 등)는 OSError로 올린다(일부를 못 본 채
    같다고 판정하지 않게)."""
    out = {}
    if not os.path.isdir(root):
        return out
    for d, dirs, files in os.walk(root, onerror=_raise):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root).replace("\\", "/")] = hashlib.sha256(fh.read()).hexdigest()
    return out


def licenses_problems(bundle_dir, repo_root=REPO_ROOT):
    """묶음(one-folder)의 실행 파일 옆 licenses/가 저장소 licenses/와 파일 목록·SHA-256까지 같고, 이전 위치
    _internal/licenses/가 없는지(W9, D15). 문제 목록(빈 목록 = 통과)."""
    try:
        want = _tree_hashes(os.path.join(repo_root, LICENSES_DIR))
        if not want:
            return ["저장소 licenses/ 없음"]
        got = _tree_hashes(os.path.join(bundle_dir, LICENSES_DIR))
    except OSError as e:  # 탐색·읽기 오류는 대조 실패
        return ["고지 대조 중 탐색 오류: %s" % e]
    probs = ["묶음에 없음: %s" % k for k in sorted(set(want) - set(got))]
    probs += ["저장소에 없는 파일: %s" % k for k in sorted(set(got) - set(want))]
    probs += ["해시 다름: %s" % k for k in sorted(set(want) & set(got)) if want[k] != got[k]]
    if os.path.exists(os.path.join(bundle_dir, "_internal", LICENSES_DIR)):
        probs.append("이전 위치 _internal/%s/가 있음(실행 파일 옆으로 옮김, D15)" % LICENSES_DIR)
    return probs


def pyz_modules(path):
    """PyInstaller PYZ TOC 파일 → 모듈 이름 집합. 형식: ('<pyz>', [(이름, 출처, 'PYMODULE'), ...])."""
    with open(path, encoding="utf-8") as fh:
        data = ast.literal_eval(fh.read())
    return {x[0] for x in data[1]}


def pdf_problems(out_dir, with_check=False):
    """PDF 어댑터 묶음 검사(W9, D15). 앱 PYZ(PYZ-00.toc, HAZOP.exe의 Analysis)에 PDF_REQUIRED_MODULES·LAZY_MODULES가 있고 결과 폴더에
    _internal/pypdfium2_raw/pdfium.dll이 있는지. 문제 목록(빈 목록 = 통과)."""
    probs = []
    toc = os.path.join(out_dir, "build", APP_NAME, "PYZ-00.toc")
    try:
        mods = pyz_modules(toc)
    except (OSError, SyntaxError, ValueError, IndexError, TypeError) as e:
        return ["앱 PYZ TOC를 읽을 수 없음: %s (%s)" % (toc, e)]
    probs += ["앱 PYZ에 PDF 모듈 없음: %s" % m for m in PDF_REQUIRED_MODULES if m not in mods]
    probs += ["앱 PYZ에 지연 import 모듈 없음: %s" % m for m in LAZY_MODULES if m not in mods]
    dll = os.path.join(dist_dir(out_dir, with_check), "_internal", *PDFIUM_DLL)
    if not os.path.isfile(dll):
        probs.append("pdfium.dll 없음: %s" % dll)
    return probs


def finish_bundle(out_dir, with_check=False):
    """빌드 뒤 마무리(W9, D15): 실행 파일 옆 licenses/ 복사, 고지 사본 대조, PDF 어댑터 묶음 검사. 문제 목록."""
    dist = dist_dir(out_dir, with_check)
    if not os.path.isdir(dist):
        return ["결과 폴더 없음(고지 복사 못 함): %s" % dist]
    try:
        print("제3자 고지 복사: %s" % copy_licenses(out_dir, with_check))
    except OSError as e:
        return ["제3자 고지 복사 실패: %s" % e]
    return licenses_problems(dist) + pdf_problems(out_dir, with_check)


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


def _raise(err):
    raise err


def dist_files(dist):
    """결과 폴더의 파일 [(전체 경로, 파일 이름, dist 상대 경로, _internal 아래 묶음 안 이름)]. 폴더가 없거나 탐색 중
    오류(권한 등)가 나면 OSError — 검사가 일부 파일을 못 보고 통과하지 않게 한다."""
    if not os.path.isdir(dist):
        raise FileNotFoundError("결과 폴더 없음: %s" % dist)
    out = []
    for d, dirs, files in os.walk(dist, onerror=_raise):
        for x in dirs:  # os.walk는 링크·junction 폴더 안으로 들어가지 않으므로 검사 실패로 둔다
            p = os.path.join(d, x)
            if os.path.islink(p) or os.path.isjunction(p):
                raise OSError("링크 폴더(탐색하지 않음): %s" % p)
        for f in files:
            full = os.path.join(d, f)
            if stat.S_ISDIR(os.lstat(full).st_mode):  # is_dir() 오류로 파일 목록에 들어온 폴더(안을 보지 못함)
                raise OSError("폴더를 탐색하지 못함: %s" % full)
            rel = os.path.relpath(full, dist).replace("\\", "/")
            out.append((full, f, rel, rel[len("_internal/"):] if rel.lower().startswith("_internal/") else rel))
    return out


def forbidden_files(dist):
    """결과 폴더에서 이름 거부 목록·TLS 규칙(_internal 아래 묶음 안 이름 기준)에 걸리는 파일(dist 상대 경로)."""
    out = []
    for full, f, rel, inner in dist_files(dist):
        if FORBIDDEN_NAME.match(f) or FORBIDDEN_NAME.match(_base(long_real(full))) or tls_rejected(inner, full):
            out.append(rel)
    return sorted(out)


def excluded_module_entries(toc, roots=None):
    """제외 대상 Qt 모듈(D13)에 걸리는 TOC 항목 [(묶음 안 이름, 출처, 모듈)]."""
    return [(n, s, m) for n, s, _ in toc for m in [qt_module_rejected(n, s, roots)] if m]


def excluded_module_files(dist):
    """결과 폴더 전체에서 제외 대상 Qt 모듈(D13)에 걸리는 파일 [(dist 상대 경로, 모듈)]. 이름 규칙은 파일 이름(과 실경로의
    긴 파일명)으로 위치와 관계없이, 폴더 규칙은 '_internal/PySide6/' 아래 상대 경로로만 본다(dist 바깥 경로는 보지 않음)."""
    out = []
    for full, f, rel, inner in dist_files(dist):
        m = qt_module_rejected(inner, None) or qt_module_rejected(_base(_norm(long_real(full))), None)
        if m:
            out.append((rel, m))
    return sorted(out)


def check_sources(out_dir, with_check=False, roots=None):
    """빌드 결과 바이너리 검사(D10·D13). 문제 목록(빈 목록 = 통과): TOC 형식, 허용 루트 밖 출처, 이름 거부 목록·제외
    플러그인, 제외 대상 Qt 모듈(TOC와 결과 폴더 모두)."""
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
    probs += ["제외 대상 Qt 모듈(%s)이 TOC에 있음: %s (%s)" % (m, n, s)
              for n, s, m in excluded_module_entries(toc, roots or allowed_roots())]
    dist = dist_dir(out_dir, with_check)
    try:
        probs += ["거부 목록·제외 대상이 결과 폴더에 있음: %s" % r for r in forbidden_files(dist)]
        probs += ["제외 대상 Qt 모듈(%s)이 결과 폴더에 있음: %s" % (m, r) for r, m in excluded_module_files(dist)]
    except OSError as e:  # 탐색 오류는 검사 실패(일부 파일을 못 본 채 통과하지 않게)
        probs.append("결과 폴더 탐색 오류: %s" % e)
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
    probs = check_dist(out, args.with_check) + finish_bundle(out, args.with_check)
    print("결과 폴더 검사(%s): %s" % (dist_dir(out, args.with_check), "통과" if not probs else "; ".join(probs)))
    src_probs = check_sources(out, args.with_check)
    print("바이너리 검사(%s): %s" % (collect_toc_path(out), "통과" if not src_probs else "실패 %d건" % len(src_probs)))
    for p in src_probs:
        print("  " + p)
    return 0 if not probs and not src_probs else 3


if __name__ == "__main__":
    sys.exit(main())
