"""앱 전용 주소 체계 `hazop-app://`(docs/design/app-shell-web.md §5.1·§5.5).

Chromium은 `file://`에서 ES 모듈을 막으므로(출처가 null이라 CORS 검사를 통과하지 못함) 새 화면은 맞춤 주소 체계로 읽는다.
- `hazop-app://shell/<경로>`: 정해진 폴더(`hazop/shell/web/`)의 파일만. 확장자 표에 있는 것만 돌려준다.
- `hazop-app://api/<…>`: 읽기 API(`hazop.shell.api.ReadApi`). GET만이다. 쓰기는 이 길로 받지 않는다(명령 길은 따로).
- `hazop-app://icons/<이름>.svg`: 아이콘 목록(manifest)에 있는 이름만.

경로 검사는 채팅 도구와 같은 방식이다(`realpath`·`commonpath`). 그 앞에 주소 문자열 단계의 검사가 있다: 이중 인코딩, 역슬래시, 드라이브·
대체 스트림(`:`), 제어 문자, `.`·`..` 조각, 빈 조각, 끝점·끝 공백, Windows 예약 이름, 너무 긴 경로. 링크·정션이 폴더 밖을 가리키면
`realpath`가 풀어 폴더 밖이므로 거절한다. 단축 이름(8.3) 작업 루트도 `realpath`가 긴 이름으로 풀어 같은 폴더로 본다.
오류 글에는 내부 경로를 싣지 않는다.

`Router`는 Qt 없이 시험할 수 있는 순수 부분이고, `AppSchemeHandler`가 Qt에 붙인다. `register()`는 `QApplication`을 만들기 전에 불러야 한다.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlsplit

LOG = logging.getLogger("hazop.shell.scheme")
SCHEME = "hazop-app"
HOST_SHELL, HOST_API, HOST_ICONS = "shell", "api", "icons"
ORIGIN = "%s://%s" % (SCHEME, HOST_SHELL)
MAX_PARTS = 32
MAX_PART_CHARS = 255
MIME = {".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
        ".svg": "image/svg+xml", ".json": "application/json", ".png": "image/png"}
CSP = ("default-src 'none'; script-src hazop-app:; style-src hazop-app: 'unsafe-inline'; img-src hazop-app: data:; "
       "connect-src hazop-app:; font-src 'none'")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f\\:*?\"<>|]")
_METHODS = ("GET", "HEAD")


@dataclass
class Response:
    status: int
    mime: str
    body: bytes = b""
    headers: dict = field(default_factory=dict)


def _error(status, text):
    return Response(status, "text/plain", text.encode("utf-8"))


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def split_path(raw_path, directory_ok=False):
    """주소의 경로 -> 조각 목록. 검사에 걸리면 ValueError(상태 코드 400)."""
    if "%25" in raw_path.lower() or "%" in unquote(raw_path):
        raise ValueError("이중 인코딩")
    try:
        path = unquote(raw_path, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("글자 해석 실패") from exc
    if _BAD_CHARS.search(path):
        raise ValueError("허용하지 않는 글자")
    if path in ("", "/"):
        return []
    if not path.startswith("/"):
        raise ValueError("경로가 /로 시작하지 않음")
    parts = path[1:].split("/")
    if parts and parts[-1] == "" and directory_ok:
        parts = parts[:-1]
    if len(parts) > MAX_PARTS:
        raise ValueError("경로가 너무 깊음")
    for part in parts:
        if part in ("", ".", "..") or len(part) > MAX_PART_CHARS or part[-1] in ". ":
            raise ValueError("허용하지 않는 조각")
        if _RESERVED.match(part.split(".", 1)[0]):
            raise ValueError("예약 이름")
    return parts


class Router:
    def __init__(self, web_root, api=None, icons_dir=None, icon_names=()):
        self.web_root = os.path.realpath(web_root)
        self.api = api
        self.icons_dir = os.path.realpath(icons_dir) if icons_dir else None
        self.icon_names = frozenset(icon_names)

    # ------------------------------------------------------------ 진입
    def resolve(self, url, method="GET"):
        if not isinstance(url, str):
            return _error(400, "잘못된 주소")
        try:
            parts_url = urlsplit(url)
            host, port = parts_url.hostname, parts_url.port
            has_user = parts_url.username is not None or parts_url.password is not None
        except ValueError:
            return _error(400, "잘못된 주소")
        if parts_url.scheme.lower() != SCHEME:
            return _error(400, "이 주소 체계는 지원하지 않음")
        if port is not None or has_user or "@" in parts_url.netloc or ":" in parts_url.netloc:
            return _error(400, "잘못된 주소")
        if str(method).upper() not in _METHODS:
            return _error(405, "읽기만 받음")
        host = (host or "").lower()
        if host not in (HOST_SHELL, HOST_API, HOST_ICONS):
            return _error(404, "없는 자리")
        try:
            alias = parts_url.path if host == HOST_SHELL else None
            if alias and alias.startswith("/api/"):
                host, parts_url = HOST_API, parts_url._replace(path=alias[len("/api"):])   # 같은 출처로 읽는 별칭(CORS가 필요 없다)
            elif alias and alias.startswith("/icons/"):
                host, parts_url = HOST_ICONS, parts_url._replace(path=alias[len("/icons"):])
            if host == HOST_SHELL:
                resp = self._static(parts_url.path)
            elif host == HOST_API:
                resp = self._api(parts_url.path, parts_url.query)
            else:
                resp = self._icon(parts_url.path)
        except ValueError:
            return _error(400, "잘못된 경로")
        resp.headers.setdefault("Cache-Control", "no-cache")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        if host == HOST_API:
            resp.headers.setdefault("Access-Control-Allow-Origin", ORIGIN)
        if str(method).upper() == "HEAD":
            resp = Response(resp.status, resp.mime, b"", resp.headers)
        return resp

    # ------------------------------------------------------------ 정적 파일
    @staticmethod
    def _within(root, real):
        try:
            return os.path.commonpath([_norm(root), _norm(real)]) == _norm(root)
        except ValueError:   # 다른 드라이브
            return False

    def _file(self, root, parts):
        real = os.path.realpath(os.path.join(root, *parts))
        if not self._within(root, real):
            return None, _error(403, "허용하지 않는 자리")
        if not os.path.isfile(real):
            return None, _error(404, "없는 파일")
        ext = os.path.splitext(real)[1].lower()
        mime = MIME.get(ext)
        if mime is None:
            return None, _error(415, "허용하지 않는 종류")
        return (real, mime), None

    def _static(self, raw_path):
        parts = split_path(raw_path, directory_ok=True) or ["index.html"]
        if raw_path.endswith("/") and raw_path != "/":
            return _error(404, "폴더는 열지 않음")
        found, err = self._file(self.web_root, parts)
        if err:
            return err
        real, mime = found
        try:
            with open(real, "rb") as fh:
                body = fh.read()
        except OSError:
            return _error(404, "읽을 수 없음")
        headers = {"Content-Security-Policy": CSP} if mime == "text/html" else {}
        return Response(200, mime, body, headers)

    def _icon(self, raw_path):
        parts = split_path(raw_path)
        if self.icons_dir is None or len(parts) != 1 or not parts[0].endswith(".svg") or parts[0][:-4] not in self.icon_names:
            return _error(404, "없는 아이콘")
        found, err = self._file(self.icons_dir, parts)
        if err:
            return err
        with open(found[0], "rb") as fh:
            return Response(200, found[1], fh.read())

    # ------------------------------------------------------------ 읽기 API
    def _api(self, raw_path, raw_query):
        parts = split_path(raw_path)
        if self.api is None or not parts:
            return _error(404, "없는 자료")
        query = dict(parse_qsl(raw_query, keep_blank_values=True, max_num_fields=20))
        try:
            resp = self.api.read(parts, query)
        except Exception:  # noqa: BLE001 - 안쪽 오류 글을 웹에 보이지 않는다
            LOG.exception("읽기 API 오류: %s", parts)
            return Response(500, "application/json", b'{"error":"internal"}')
        return resp if resp is not None else _error(404, "없는 자료")


# ---------------------------------------------------------------- Qt에 붙이기

_REGISTERED = []


def register():
    """맞춤 주소 체계를 등록한다. QApplication을 만들기 전에 불러야 한다(여러 번 불러도 한 번만 등록)."""
    if _REGISTERED:
        return
    from PySide6.QtWebEngineCore import QWebEngineUrlScheme
    scheme = QWebEngineUrlScheme(SCHEME.encode("ascii"))
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    # FetchApiAllowed는 fetch()로 읽기 API를 부르려면 필요(Qt 6.6 이상). LocalAccessAllowed: 규격(§10 1)은 뺄 것을 정했지만 빼면 틀 창(ShellWindow)의 웹 화면이
    # 전혀 그려지지 않는다(2026-11-13 PySide6 6.12 오프스크린 실측: main.js가 돌지 않고 콘솔 오류도 없음. 연결 스크립트 없는 맨 QWebEnginePage에서는 빼도 뜸).
    # 새 화면 웹뷰는 file 주소를 따로 허용하지 않으므로(ShellPage 이동 제한·CSP) 이 플래그로 file을 읽을 길은 없다. 원인은 더 파야 한다.
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.LocalScheme
                    | QWebEngineUrlScheme.Flag.LocalAccessAllowed | QWebEngineUrlScheme.Flag.CorsEnabled
                    | QWebEngineUrlScheme.Flag.FetchApiAllowed)
    QWebEngineUrlScheme.registerScheme(scheme)
    _REGISTERED.append(scheme)


def _handler_class():
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlSchemeHandler

    class AppSchemeHandler(QWebEngineUrlSchemeHandler):
        def __init__(self, router, parent=None):
            super().__init__(parent)
            self.router = router

        def requestStarted(self, job):  # noqa: N802 (Qt 이름)
            url = job.requestUrl().toString()
            resp = self.router.resolve(url, bytes(job.requestMethod()).decode("ascii", "replace"))
            if resp.status != 200:
                job.fail({404: QWebEngineUrlRequestJob.Error.UrlNotFound}.get(resp.status, QWebEngineUrlRequestJob.Error.RequestDenied))
                return
            buf = QBuffer(job)
            buf.setData(QByteArray(resp.body))
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            # 응답 머리(CSP·ACAO)는 Qt에 싣지 않는다: PySide가 머리 사전을 잘못 풀어 CSP가 글자 단위로 깨진다. CSP는 index.html의 meta가 맡고,
            # 읽기 API는 같은 출처(hazop-app://shell/api/…)로 불러 CORS가 필요 없다.
            job.reply(QByteArray(resp.mime.encode("ascii")), buf)

    return AppSchemeHandler


def install(profile, router):
    """프로필에 처리기를 붙인다(이미 붙어 있으면 바꾼다). 처리기 객체를 돌려준다(프로필이 소유)."""
    handler = _handler_class()(router, profile)
    profile.removeUrlScheme(SCHEME.encode("ascii"))
    profile.installUrlSchemeHandler(SCHEME.encode("ascii"), handler)
    return handler
