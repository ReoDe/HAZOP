"""Claude API 키 보관 (4단계 설계 D6). Qt 의존 없음.

이름 붙인 키를 여러 개 두고 그중 하나를 쓴다. '이 PC에 저장'을 고른 키만 Windows DPAPI(CryptProtectData, 현재 사용자
범위)로 암호화한 바이트를 설정 파일 옆 api_keys.json에 base64로 쓴다. 메모리에만 둔 키는 파일에 남지 않는다.
평문은 파일·로그·예외 문구·repr에 남기지 않는다. 화면에는 끝 4자리만 보인다(hint). 새 패키지 없이 ctypes만 쓴다.
옛 단일 키 파일(api_key.dpapi)은 첫 읽기에서 새 파일로 옮긴다. 새 파일을 쓰고 다시 읽어 같은 키임을 확인한 뒤에만
옛 파일을 지우므로, 옮기다 실패해도 옛 키는 남는다.
"""

import base64
import ctypes
import json
import os
import sys
import uuid

from hazop import paths, store_io

STORE_FILE_NAME = "api_keys.json"
LEGACY_FILE_NAME = "api_key.dpapi"
LEGACY_NAME = "기존 키"
DEFAULT_NAME = "기본 키"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_ENTROPY = b"hazop-claude-api-key"


def default_store_path():
    return os.path.join(os.path.dirname(paths.settings_path()), STORE_FILE_NAME)


def mask(text, key):
    """text 안의 key를 '***'로 바꾼다. key가 비었으면 그대로."""
    if text is None or not key:
        return text
    return str(text).replace(key, "***")


def hint(key):
    """키 식별용 꼬리 'sk-ant-…abcd'. 키가 짧으면 꼬리도 보이지 않는다."""
    if not key or len(key) < 12:
        return "…"
    return "%s…%s" % (key[:7], key[-4:])


def clean_key(text):
    """붙여 넣은 키의 앞뒤·중간 공백과 줄바꿈을 지운다(복사할 때 섞여 들어오는 경우)."""
    return "".join((text or "").split())


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
    """이름 붙인 API 키 목록과 사용 중인 키·모델·키별 마지막 연결 시험 결과를 보관한다.

    항목(entry): {"id", "name", "persisted", "last_test": {"at", "ok", "message"} 또는 None}. 키 평문은 _keys[id]에만.
    저장 파일은 첫 접근에서 한 번 읽는다. 읽지 못한 키는 목록에 이름만 남기고 load_error에 사유를 둔다."""

    def __init__(self, path=None):
        self.path = path or default_store_path()
        self.legacy_path = os.path.join(os.path.dirname(os.path.abspath(self.path)), LEGACY_FILE_NAME)
        self._entries = []
        self._keys = {}
        self._active = None
        self._model = None
        self._unreadable = []  # 복호화하지 못한 항목 원본. 다음 저장 때 그대로 다시 써서 잃지 않는다
        self._loaded = False
        self.load_error = None

    def __repr__(self):
        return "KeyStore(path=%r, keys=%d, active=%s)" % (self.path, len(self._entries), self._active)

    # ------------------------------------------------------------ 읽기
    def _ensure(self):
        if not self._loaded:
            self._loaded = True
            if os.path.isfile(self.path):
                self._load()
            elif os.path.isfile(self.legacy_path):
                self._migrate()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            self.load_error = "API 키 목록 파일을 읽지 못함(파일 손상). 키를 다시 추가하세요."
            return
        self._model = doc.get("model")
        bad = 0
        for e in doc.get("keys") or []:
            try:
                self._keys[e["id"]] = unprotect(base64.b64decode(e["blob"])).decode("utf-8")
            except (OSError, KeyError, ValueError, UnicodeDecodeError):
                bad += 1
                self._unreadable.append(e)
                continue
            self._entries.append({"id": e["id"], "name": e.get("name") or DEFAULT_NAME, "persisted": True,
                                  "last_test": e.get("last_test")})
        if bad:
            self.load_error = "저장된 키 %d개를 읽지 못함(다른 사용자·다른 PC에서 저장했거나 손상됨)" % bad
        ids = [e["id"] for e in self._entries]
        self._active = doc.get("active") if doc.get("active") in ids else (ids[0] if ids else None)

    def _migrate(self):
        try:
            with open(self.legacy_path, "rb") as fh:
                key = unprotect(fh.read()).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            self.load_error = "저장된 API 키를 읽지 못함(다른 사용자·다른 PC에서 저장했거나 파일이 손상됨)"
            return
        if not key:
            return
        kid = self._new_entry(LEGACY_NAME, key, persisted=True)
        self._active = kid
        try:
            self._write()
            check = KeyStore(self.path)
            if check.get() != key:
                raise OSError("옮긴 키를 다시 읽지 못함")
        except OSError:
            self.load_error = "기존 키를 새 목록으로 옮기지 못함(기존 파일은 그대로 둠)"
            return
        try:
            os.remove(self.legacy_path)
        except OSError:
            pass

    # ------------------------------------------------------------ 쓰기
    def _write(self):
        """저장 대상 키만 암호화해 원자적으로 쓴다(사용 키·모델·시험 결과 포함)."""
        keys = []
        for e in self._entries:
            if e["persisted"]:
                blob = base64.b64encode(protect(self._keys[e["id"]].encode("utf-8"))).decode("ascii")
                keys.append({"id": e["id"], "name": e["name"], "blob": blob, "last_test": e["last_test"]})
        keys += self._unreadable
        if not keys and self._model is None and not os.path.isfile(self.path):
            return  # 메모리 키만 쓰는 동안은 파일을 만들지 않는다
        doc = {"version": 1, "active": self._active, "model": self._model, "keys": keys}
        # 공용 원자적 쓰기: 임시 파일은 같은 폴더에 만들고(폴더 권한을 물려받음) 실패하면 지운다. 줄끝은 전처럼 운영체제 것.
        # 지문 충돌 확인은 하지 않는다. 키 저장소는 이 객체가 읽은 항목을 통째로 다시 쓰고(읽지 못한 항목도 보존) 앱 하나만 쓴다
        text = json.dumps(doc, ensure_ascii=False, indent=1).replace("\n", os.linesep)
        store_io.write_bytes(os.path.abspath(self.path), text.encode("utf-8"))

    def _new_entry(self, name, key, persisted):
        kid = uuid.uuid4().hex[:12]
        self._keys[kid] = key
        self._entries.append({"id": kid, "name": name, "persisted": persisted, "last_test": None})
        return kid

    def _entry(self, kid):
        for e in self._entries:
            if e["id"] == kid:
                return e
        raise KeyError("없는 키 항목")

    # ------------------------------------------------------------ 공개 API
    def entries(self):
        """화면용 항목 목록(키 평문 없음, hint는 끝 4자리만)."""
        self._ensure()
        return [dict(e, hint=hint(self._keys.get(e["id"])), active=e["id"] == self._active) for e in self._entries]

    def active(self):
        """사용 중인 항목(entries() 형식) 또는 None."""
        return next((e for e in self.entries() if e["active"]), None)

    def get(self):
        self._ensure()
        return self._keys.get(self._active)

    def add(self, name, key, persist):
        """새 키를 추가하고 사용 키로 고른다. 형식이 틀리면 ValueError, 암호화·저장 실패는 OSError(목록은 그대로)."""
        self._ensure()
        key = clean_key(key)
        problem = key_problem(key)
        if problem:
            raise ValueError(problem)
        name = (name or "").strip() or ("%s %d" % (DEFAULT_NAME, len(self._entries) + 1) if self._entries else DEFAULT_NAME)
        before = (list(self._entries), dict(self._keys), self._active)
        kid = self._new_entry(name, key, persist)
        self._active = kid
        if not persist:
            return kid
        try:
            self._write()
        except OSError:
            self._entries, self._keys, self._active = before
            raise
        return kid

    def set(self, key, persist):
        """키 하나를 넣고 쓴다(스크립트용). add()와 같다."""
        return self.add(DEFAULT_NAME, key, persist)

    def select(self, kid):
        self._ensure()
        self._entry(kid)
        self._active = kid
        self._write()

    def rename(self, kid, name):
        self._ensure()
        name = (name or "").strip()
        if not name:
            raise ValueError("빈 이름")
        self._entry(kid)["name"] = name
        self._write()

    def remove(self, kid):
        """키를 지운다. 사용 중이던 키면 남은 첫 키를 사용 키로 고른다."""
        self._ensure()
        self._entries.remove(self._entry(kid))
        self._keys.pop(kid, None)
        if self._active == kid:
            self._active = self._entries[0]["id"] if self._entries else None
        self._write()

    def clear(self):
        """사용 중인 키를 지운다."""
        if self.get() is not None:
            self.remove(self._active)
        self.load_error = None

    def record_test(self, kid, ok, message, at, model):
        """키별 마지막 연결 시험 결과(시각은 UTC ISO 문자열, 시험한 모델 포함). 문구 속 키는 가린다."""
        self._ensure()
        self._entry(kid)["last_test"] = {"at": at, "ok": bool(ok), "model": model,
                                         "message": mask(message, self._keys.get(kid))}
        self._write()

    @property
    def model(self):
        from hazop.study.claude_http import DEFAULT_MODEL, MODELS
        self._ensure()
        return self._model if self._model in MODELS else DEFAULT_MODEL

    def set_model(self, model):
        from hazop.study.claude_http import MODELS
        if model not in MODELS:
            raise ValueError("지원하지 않는 모델")
        self._ensure()
        self._model = model
        self._write()

    def is_persisted(self):
        e = self.active()
        return bool(e and e["persisted"])
