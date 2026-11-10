"""출력 파일 이름·경로 안전 처리, 자원 루트·작업 루트·설정 파일 위치 결정."""

import json
import os
import re
import sys
from typing import NamedTuple

_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def safe_name(name, default="drawing"):
    """파일·폴더 이름으로 쓸 수 있게 정규화한다. 글자·숫자·'.'·'-'·'_' 외에는 '_'로 바꾼다."""
    s = re.sub(r"[^\w.-]+", "_", str(name or "")).strip("._ ")
    if not s:
        s = default
    if s.split(".")[0].upper() in _RESERVED:
        s = "_" + s
    return s[:120]


def safe_join(root, name):
    """root 아래 경로를 root가 들어온 형태 그대로(8.3 단축 이름이면 단축 이름으로) 돌려준다. 결과가 root 밖이면 ValueError.
    안팎 판정은 realpath로 하지만, realpath를 그대로 돌려주면 단축 이름 root와 긴 이름 결과가 섞여
    rel_or_abs가 '../..'로 시작하는 저장 경로를 만든다(CI run 42771733162)."""
    root_abs = os.path.realpath(root)
    path = os.path.realpath(os.path.join(root_abs, name))
    if path == root_abs or os.path.commonpath([root_abs, path]) != root_abs:
        raise ValueError("출력 경로가 출력 루트 밖임: %r" % name)
    return os.path.join(os.path.abspath(root), path[len(root_abs):].lstrip("\\/"))


def long_path(path):
    """절대 경로에서 이미 있는 앞부분의 8.3 단축 이름을 긴 이름으로 펼친다. 링크·정션은 풀지 않는다."""
    head, tail = os.path.abspath(path), []
    try:
        import ctypes
        get_long = ctypes.windll.kernel32.GetLongPathNameW
    except AttributeError:
        return head
    while True:
        buf = ctypes.create_unicode_buffer(32768)
        n = get_long(head, buf, 32768)
        if 0 < n < 32768:
            return os.path.join(buf.value, *reversed(tail))
        parent, name = os.path.split(head)
        if parent == head:
            return os.path.abspath(path)
        head, tail = parent, tail + [name]


def rel_or_abs(path, root):
    """root 기준 상대 경로('/' 구분). 다른 드라이브 등으로 상대 경로를 만들 수 없으면 절대 경로.
    저장소 전용 폴더(샘플 도면·APR1400) 아래 파일은 root와 관계없이 옮기기 전 위치의 논리 경로(LEGACY_PREFIXES,
    예: '참고자료/<나머지>')로 쓴다: 추출 JSON의 source.file·svg_file이 그래프 판(graph_version) 해시에 들어가므로
    폴더 위치가 바뀌어도 판이 같아야 한다(D9). resolve_rel이 같은 표로 되돌려 읽는다."""
    try:
        for prefix, name in LEGACY_PREFIXES:
            if FOLDERS[name].root == "repo" and _inside(path, folder(name)):
                return prefix + os.path.relpath(os.path.abspath(path), folder(name)).replace("\\", "/")
        rel = os.path.relpath(path, root)
    except ValueError:
        rel = os.path.abspath(path)
    return rel.replace("\\", "/")


EXTERNAL_BACKUP_DIR = "_외부"


def backup_rel(path, root):
    """백업 폴더 아래 path를 둘 자리(상대 경로). root 안이면 root 기준 경로, 밖이면(다른 드라이브, '작업2' 같은 형제 폴더)
    _외부/<드라이브>/<나머지 경로>. 결과에 '..'나 드라이브 표시가 없으므로 os.path.join(백업 폴더, 결과)가 백업 폴더 밖으로
    나가거나 원본 자리로 바뀌지 않는다. rel_or_abs는 기록용이라 절대 경로를 돌려줄 수 있어 이 자리에 쓰면 안 된다."""
    path, root = os.path.abspath(path), os.path.abspath(root)
    if _inside(path, root):
        return path[len(root):].lstrip("\\/")
    drive, rest = os.path.splitdrive(path)
    return os.path.join(EXTERNAL_BACKUP_DIR, safe_name(drive, "_"), rest.lstrip("\\/"))


# ---------------------------------------------------------------- 자원 루트·작업 루트 (기획서/인터페이스.md §7.1)
# 자원 루트(읽기 전용): 기준 자료(자원/기준/이탈후보·기준표·패턴), 기법 지침서. 폴더 위치는 아래 FOLDERS 표가 정한다.
#   뷰어 템플릿은 패키지 안(hazop/viewer/template.html)에 두므로 패키지 위치를 그대로 쓴다.
# 작업 루트(쓰기): 저장 루트(자료저장소/), 출력/, logs/, 데이터/(구간·고정응답·검토구간·분석결과 등).
# 기본값: 자원 루트 = 저장소 루트, 작업 루트 = 저장소/작업(DEV_WORK_ROOT, git 제외). 환경변수로 바꿀 수 있고
# HAZOP_STORE_ROOT는 계속 우선한다. 표본(자원/표본)은 scripts/seed_samples.py로 작업 루트에 채운다.
# PyInstaller 실행(sys._MEIPASS)은 감지만 한다: 자원 루트 = 묶음 폴더, 작업 루트 = %LOCALAPPDATA%\HAZOP [제안, §7.1].
# 프로그램 루트(program_root): 화면이 importlib로 읽는 scripts/*.py 위치. 묶음 폴더 또는 저장소 루트(자원 루트 환경변수와 무관).
# 값은 호출할 때마다 환경변수를 다시 읽는다. 다만 스크립트의 기본 인자(DEFAULT_*)는 가져올 때 한 번 정해진다.

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV_WORK_ROOT = os.path.join(REPO_ROOT, "작업")  # 개발 환경 작업 루트 기본값(배포본은 %LOCALAPPDATA%\HAZOP)
ENV_RESOURCE_ROOT = "HAZOP_RESOURCE_ROOT"
ENV_WORK_ROOT = "HAZOP_WORK_ROOT"
ENV_STORE_ROOT = "HAZOP_STORE_ROOT"
# 구간 JSON inputs 중 자원 루트 기준으로 읽는 항목(나머지 region·graph는 작업 루트 기준)
RESOURCE_INPUT_ROLES = ("candidate_catalog", "applicability", "patterns", "risk_criteria")


def frozen_bundle_dir():
    """PyInstaller로 묶어 실행 중이면 묶음 폴더(sys._MEIPASS), 아니면 None. 감지만 한다(빌드하지 않음).
    frozen 판단은 sys._MEIPASS만 본다: sys.frozen만 있고 _MEIPASS가 없는 다른 묶음 도구는 개발 실행으로 취급한다."""
    return getattr(sys, "_MEIPASS", None)


def program_root():
    """프로그램 코드(scripts/*.py)가 있는 폴더: 묶인 실행이면 묶음 폴더(sys._MEIPASS), 아니면 저장소 루트.
    코드는 기준 자료가 아니므로 HAZOP_RESOURCE_ROOT를 따르지 않는다. 추가 API(패키징 W3)."""
    return frozen_bundle_dir() or REPO_ROOT


def program_path(*parts):
    return os.path.join(program_root(), *parts)


def licenses_dir():
    """제3자 라이선스 고지 폴더: 묶인 실행이면 실행 파일 옆 licenses/(빌드가 복사, 패키징 D15), 아니면 저장소 licenses/.
    추가 API(패키징 W10). 폴더가 있는지는 보지 않는다."""
    if frozen_bundle_dir():
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "licenses")
    return os.path.join(REPO_ROOT, "licenses")


def resource_root():
    env = os.environ.get(ENV_RESOURCE_ROOT)
    if env:
        return os.path.abspath(env)
    return frozen_bundle_dir() or REPO_ROOT


def work_root():
    env = os.environ.get(ENV_WORK_ROOT)
    if env:
        return os.path.abspath(env)
    if frozen_bundle_dir():
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "HAZOP")
    return DEV_WORK_ROOT


def resource_path(*parts):
    return os.path.join(resource_root(), *parts)


def work_path(*parts):
    return os.path.join(work_root(), *parts)


def store_root():
    """등록 저장 루트: HAZOP_STORE_ROOT 우선, 없으면 <작업 루트>/자료저장소."""
    return os.environ.get(ENV_STORE_ROOT) or work_path("자료저장소")


def output_root(*parts):
    """<작업 루트>/출력[/parts...]"""
    return work_path("출력", *parts)


def fixed_test_results_path(project_name, graph_name):
    """고정 응답(시험)으로 채운 ⑤ 결과 파일. 실제 결과(데이터/분석결과)와 따로 둔다(화면 설계 D5·§8.3)."""
    return folder("분석결과-시험", safe_name(project_name), safe_name(graph_name) + ".json")


# ---------------------------------------------------------------- 폴더 표 (docs/2026-11-09-data-consolidation §3)
# 데이터 폴더는 이 표로만 연다(paths.folder). 다른 모듈에 '데이터'·'참고자료' 경로 문자열을 쓰지 않는다
# (tests/test_path_literals.py가 막음). 새 기능이 폴더를 더하면 여기 한 줄을 더한다.
class Folder(NamedTuple):
    # "resource": 자원 루트(읽기 전용 기준 자료, 배포본에 묶음 = scripts/build_package.py DATA_DIRS)
    # "repo": 저장소에만 있는 개발·검사 입력(샘플 도면, 표본). 배포본에 묶지 않고 자원 루트 환경변수와 무관
    # "work": 작업 루트(쓰기). 이 아래 배치는 배포본 작업 루트(%LOCALAPPDATA%\HAZOP)와 같아야 한다(바꾸지 않는 계약)
    root: str
    rel: tuple  # 루트 기준 상대 경로


FOLDERS = {
    "이탈후보": Folder("resource", ("자원", "기준", "이탈후보")),
    "기준표": Folder("resource", ("자원", "기준", "기준표")),
    "패턴": Folder("resource", ("자원", "기준", "패턴")),
    "기호": Folder("resource", ("자원", "기준", "기호")),
    "참고": Folder("repo", ("자원", "참고자료")),
    "APR1400": Folder("repo", ("자원", "참고자료", "APR1400_DCD")),
    "표본": Folder("repo", ("자원", "표본")),
    "작업데이터": Folder("work", ("데이터",)),
    "구간": Folder("work", ("데이터", "구간")),
    "고정응답": Folder("work", ("데이터", "고정응답")),
    "지식": Folder("work", ("데이터", "지식")),
    "검토구간": Folder("work", ("데이터", "검토구간")),
    "분석결과": Folder("work", ("데이터", "분석결과")),
    "분석결과-시험": Folder("work", ("데이터", "분석결과-시험")),
    "백업": Folder("work", ("데이터", "백업")),
    "초기사건": Folder("work", ("데이터", "초기사건")),
    "도면수정": Folder("work", ("데이터", "도면수정")),
    "도면연결": Folder("work", ("데이터", "도면연결")),
    "잠재후보": Folder("work", ("데이터", "잠재후보")),
    "캐시": Folder("work", ("데이터", "캐시")),  # 지워도 되는 계산 결과(hazop.app.data 추출 요약)
    "기호후보": Folder("work", ("기호후보",)),
}
# 자원 루트 아래에 낱개로 두는 파일. FOLDERS의 resource 행은 배포본에 통째로 묶는 폴더라서 파일은 따로 적는다.
# 배포본도 같은 상대 위치에 묶는다(scripts/build_package.py DATA_FILES). 위치를 아는 곳은 이 표 하나다.
FILES = {
    "guide": Folder("resource", ("기획서", "HAZOP기법지침.md")),  # HAZOP 기법 지침서. 내용 해시는 hazop/analysis/integrity.py가 고정한다
}
REFERENCE_LOGICAL = "참고자료/"  # 참고 폴더 아래 파일의 기록용 접두(rel_or_abs)
# 사용자 파일(구간 JSON inputs, 추출 JSON source.file·svg_file)에 저장된 옛 상대 경로 접두 → 폴더 이름.
# 읽을 때만 풀고(resolve_rel) 파일은 고치지 않는다. 긴 접두가 먼저.
LEGACY_PREFIXES = (
    ("데이터/참고자료/APR1400_DCD/", "APR1400"),
    ("데이터/이탈후보/", "이탈후보"),
    ("데이터/기준표/", "기준표"),
    ("데이터/패턴/", "패턴"),
    (REFERENCE_LOGICAL, "참고"),
)


def folder(name, *parts):
    """FOLDERS의 폴더(또는 그 아래 경로)의 절대 경로. 이름이 표에 없으면 KeyError."""
    base = {"resource": resource_root, "work": work_root, "repo": lambda: REPO_ROOT}[FOLDERS[name].root]()
    return folder_in(base, name, *parts)


def folder_in(root, name, *parts):
    """FOLDERS 폴더가 주어진 root 아래 있을 자리. 임시 작업 루트나 검사 입력 사본(작은 저장소)을 다룰 때 쓴다."""
    return os.path.join(root, *FOLDERS[name].rel, *parts)


def logical_reference_dir(root):
    """root 아래 논리 경로(REFERENCE_LOGICAL) 자리. 참고 폴더 사본을 여기 두면 그 안 파일의 기록 경로가 저장소와 같다."""
    return os.path.join(root, *REFERENCE_LOGICAL.strip("/").split("/"))


def file_rel(name):
    """FILES 파일의 루트 기준 상대 경로('/' 구분)."""
    return "/".join(FILES[name].rel)


def file_in(root, name):
    """FILES 파일이 주어진 root 아래 있을 자리. 자원 루트 사본을 꾸미는 시험과 검사가 쓴다."""
    return os.path.join(root, *FILES[name].rel)


def resource_file(name):
    """FILES 파일의 절대 경로(지금 자원 루트 기준)."""
    return file_in(resource_root(), name)


def folder_rel(name):
    """FOLDERS 폴더의 루트 기준 상대 경로('/' 구분). 화면 문구·묶음 목록용."""
    return "/".join(FOLDERS[name].rel)


def _inside(path, root):
    path, root = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def resolve_rel(rel, root):
    """저장된 상대 경로를 실제 경로로. 절대 경로면 그대로, root 아래에 있으면 그것, 없으면 LEGACY_PREFIXES로 푼 위치에
    파일이 있을 때 그것. 어디에도 없으면 root 기준 경로(호출한 쪽이 '없음'을 알린다)."""
    if os.path.isabs(rel):
        return rel
    direct = os.path.join(root, rel)
    if os.path.exists(direct):
        return direct
    norm = rel.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    for prefix, name in LEGACY_PREFIXES:
        if norm.startswith(prefix):
            alt = folder(name, *norm[len(prefix):].split("/"))
            if os.path.exists(alt):
                return alt
    return direct


def is_reference_rel(rel):
    """기록된 경로(source.file 등)가 참고 폴더(샘플 도면) 아래 파일인지."""
    return str(rel or "").replace("\\", "/").startswith(REFERENCE_LOGICAL)


# ---------------------------------------------------------------- 설정 파일 (%APPDATA%\HAZOP\settings.json)
DEFAULT_SETTINGS = {"reviewer_name": None, "work_root": None, "recent_regions": [], "recent_runs": []}


def settings_path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(base, "HAZOP", "settings.json")


def load_settings(path=None):
    """설정을 읽는다. 파일이 없으면 기본값. JSON 객체가 아니면 ValueError(기본값으로 조용히 바꾸지 않음).
    work_root 값은 기록만 한다: 작업 루트 결정(work_root())은 환경변수만 본다.
    읽기는 utf-8-sig(메모장 등이 붙인 UTF-8 BOM 허용, 패키징 W10). 쓰기(save_settings)는 BOM 없는 UTF-8 그대로."""
    path = path or settings_path()
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        os.stat(path)  # 권한 오류는 '없음'으로 삼키지 않고 OSError로 올린다(isfile은 False로 삼킴)
    except FileNotFoundError:
        return out
    if not os.path.isfile(path):
        raise OSError("설정 경로가 파일이 아님: %s" % path)
    with open(path, encoding="utf-8-sig") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict):
        raise ValueError("설정 파일이 JSON 객체가 아님: %s" % path)
    out.update(doc)
    return out


def save_settings(settings, path=None):
    """설정을 임시 파일에 쓴 뒤 교체한다. 쓴 경로를 돌려준다."""
    if not isinstance(settings, dict):
        raise ValueError("설정은 dict여야 함")
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return path
