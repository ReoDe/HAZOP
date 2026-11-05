"""출력 파일 이름·경로 안전 처리, 자원 루트·작업 루트·설정 파일 위치 결정."""

import json
import os
import re
import sys

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
    """root 바로 아래 경로를 돌려준다. 결과가 root 밖이면 ValueError."""
    root_abs = os.path.realpath(root)
    path = os.path.realpath(os.path.join(root_abs, name))
    if path == root_abs or os.path.commonpath([root_abs, path]) != root_abs:
        raise ValueError("출력 경로가 출력 루트 밖임: %r" % name)
    return path


def rel_or_abs(path, root):
    """root 기준 상대 경로('/' 구분). 다른 드라이브 등으로 상대 경로를 만들 수 없으면 절대 경로."""
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        rel = os.path.abspath(path)
    return rel.replace("\\", "/")


# ---------------------------------------------------------------- 자원 루트·작업 루트 (기획서/인터페이스.md §7.1)
# 자원 루트(읽기 전용): 이탈 카탈로그·적용 판단·패턴·기준표(데이터/이탈후보·패턴·기준표), 기법 지침서, 샘플 도면.
#   뷰어 템플릿은 패키지 안(hazop/viewer/template.html)에 두므로 패키지 위치를 그대로 쓴다.
# 작업 루트(쓰기): 저장 루트(자료저장소/), 출력/, 구간 JSON(데이터/구간), 고정 응답(데이터/고정응답).
# 기본값은 둘 다 저장소 루트(지금까지와 같은 경로). 환경변수로 바꿀 수 있고 HAZOP_STORE_ROOT는 계속 우선한다.
# PyInstaller 실행(sys._MEIPASS)은 감지만 한다: 자원 루트 = 묶음 폴더, 작업 루트 = %LOCALAPPDATA%\HAZOP [제안, §7.1].
# 값은 호출할 때마다 환경변수를 다시 읽는다. 다만 스크립트의 기본 인자(DEFAULT_*)는 가져올 때 한 번 정해진다.

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_RESOURCE_ROOT = "HAZOP_RESOURCE_ROOT"
ENV_WORK_ROOT = "HAZOP_WORK_ROOT"
ENV_STORE_ROOT = "HAZOP_STORE_ROOT"
# 구간 JSON inputs 중 자원 루트 기준으로 읽는 항목(나머지 region·graph는 작업 루트 기준)
RESOURCE_INPUT_ROLES = ("candidate_catalog", "applicability", "patterns", "risk_criteria")


def frozen_bundle_dir():
    """PyInstaller로 묶어 실행 중이면 묶음 폴더(sys._MEIPASS), 아니면 None. 감지만 한다(빌드하지 않음)."""
    return getattr(sys, "_MEIPASS", None)


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
    return REPO_ROOT


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


# ---------------------------------------------------------------- 설정 파일 (%APPDATA%\HAZOP\settings.json)
DEFAULT_SETTINGS = {"reviewer_name": None, "work_root": None, "recent_regions": [], "recent_runs": []}


def settings_path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(base, "HAZOP", "settings.json")


def load_settings(path=None):
    """설정을 읽는다. 파일이 없으면 기본값. JSON 객체가 아니면 ValueError(기본값으로 조용히 바꾸지 않음).
    work_root 값은 기록만 한다: 작업 루트 결정(work_root())은 환경변수만 본다."""
    path = path or settings_path()
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as fh:
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
