"""출력 파일 이름·경로 안전 처리."""

import os
import re

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
