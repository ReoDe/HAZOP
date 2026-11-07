"""Claude API 키 보관 (4단계 설계 D6). Qt 의존 없음.

키는 메모리에 둔다. '이 PC에 저장'을 고르면 Windows DPAPI(CryptProtectData, 현재 사용자 범위)로 암호화한 바이트만
설정 파일 옆 api_key.dpapi에 쓴다. 평문은 파일·로그·예외 문구·repr에 남기지 않는다. 새 패키지 없이 ctypes만 쓴다.
"""

import ctypes
import os
import sys

from hazop import paths

KEY_FILE_NAME = "api_key.dpapi"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_ENTROPY = b"hazop-claude-api-key"


def default_key_path():
    return os.path.join(os.path.dirname(paths.settings_path()), KEY_FILE_NAME)


def mask(text, key):
    """text 안의 key를 '***'로 바꾼다. key가 비었으면 그대로."""
    if text is None or not key:
        return text
    return str(text).replace(key, "***")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(data, protect):
    """DPAPI 암호화(protect=True)·복호화. 실패하면 OSError. Windows 전용."""
    if sys.platform != "win32":
        raise OSError("Windows DPAPI는 Windows에서만 쓸 수 있음")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    src, _src_buf = _blob(data)
    ent, _ent_buf = _blob(_ENTROPY)
    out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.restype = ctypes.c_int
    if protect:
        ok = fn(ctypes.byref(src), "HAZOP Claude API key", ctypes.byref(ent), None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI %s 실패(Windows 오류 %d)" % ("암호화" if protect else "복호화", ctypes.GetLastError()))
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect(data):
    return _dpapi(data, True)


def unprotect(data):
    return _dpapi(data, False)


def key_problem(key):
    """키 형식 문제(한국어, 키 값은 넣지 않음) 또는 None. 줄바꿈·공백·제어문자가 든 키는 HTTP 헤더 오류 문구에
    키가 그대로 실려 로그로 새므로 받지 않는다."""
    if not key:
        return "빈 API 키"
    if not key.isascii() or not key.isprintable() or any(c.isspace() for c in key):
        return "API 키에 공백·줄바꿈 또는 허용되지 않는 문자가 있음"
    return None


class KeyStore:
    """API 키 하나를 보관한다. 저장 파일은 첫 get()에서 한 번 읽는다.
    저장 파일을 읽지 못하면(다른 사용자·손상) 키 없음으로 두고 load_error에 한국어 사유를 남긴다."""

    def __init__(self, path=None):
        self.path = path or default_key_path()
        self._key = None
        self._loaded = False
        self.load_error = None

    def __repr__(self):
        return "KeyStore(path=%r, key=%s)" % (self.path, "설정됨" if self._key else "없음")

    def _load(self):
        self._loaded = True
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "rb") as fh:
                self._key = unprotect(fh.read()).decode("utf-8") or None
        except (OSError, UnicodeDecodeError):
            self._key = None
            self.load_error = "저장된 API 키를 읽지 못함(다른 사용자·다른 PC에서 저장했거나 파일이 손상됨)"

    def get(self):
        if not self._loaded:
            self._load()
        return self._key

    def set(self, key, persist):
        """키를 바꾼다. persist=False면 이전에 저장한 파일도 지워 다음 실행에 옛 키가 살아나지 않게 한다."""
        key = (key or "").strip()
        problem = key_problem(key)
        if problem:
            raise ValueError(problem)
        if persist:
            data = protect(key.encode("utf-8"))
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, self.path)
        else:
            self._remove_file()
        self._key = key
        self._loaded = True
        self.load_error = None

    def clear(self):
        self._key = None
        self._loaded = True
        self.load_error = None
        self._remove_file()

    def is_persisted(self):
        return os.path.isfile(self.path)

    def _remove_file(self):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
