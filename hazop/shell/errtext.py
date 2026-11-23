"""오류 때만 뜨는 화면 글에 예외를 싣는 곳(실제 창 6차 ④: 영문 OSError 글·파일 경로가 화면에 그대로 올랐다).

엔진이 사람에게 보이려고 한글로 쓴 사유는 그대로 싣고, 그 밖의 예외(파이썬·운영체제가 만든 영문 글)는 사람 말 한 마디로 바꾼다.
원래 예외 글은 앱 기록(로그)에만 남긴다. Qt를 import하지 않는다.
"""

import errno
import json
import logging

LOG = logging.getLogger("hazop.shell.errtext")

UNKNOWN = "예상하지 못한 오류(자세한 내용은 앱 기록에 남겼습니다)"


def _korean(text):
    return any("가" <= ch <= "힣" for ch in text)


def why(exc, limit=160):
    """예외 → 화면 괄호 안에 넣을 사람 말(limit자 이하)."""
    text = " ".join(str(exc or "").split())
    if text and _korean(text):
        return text[:limit]
    LOG.warning("화면 오류 글로 바꾼 예외: %r", exc)
    return _plain(exc)[:limit]


def _plain(exc):
    from hazop import store_io
    if isinstance(exc, store_io.Conflict):
        return "다른 곳에서 먼저 바뀌었음"
    if isinstance(exc, PermissionError):
        return "파일이 다른 프로그램에 열려 있거나 쓸 권한이 없음"
    if isinstance(exc, FileNotFoundError):
        return "파일이나 폴더가 없음"
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return "파일 내용을 읽을 수 없음(깨졌거나 형식이 다름)"
    if isinstance(exc, TimeoutError):
        return "시간 안에 끝나지 않음"
    if isinstance(exc, OSError):
        if getattr(exc, "errno", None) == errno.ENOSPC:
            return "디스크 공간이 모자람"
        return "파일을 읽거나 쓰지 못함"
    if isinstance(exc, MemoryError):
        return "메모리가 모자람"
    return UNKNOWN
