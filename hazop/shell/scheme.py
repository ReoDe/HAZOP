"""앱 전용 주소 체계 `hazop-app://`(docs/design/app-shell-web.md §5.1·§5.5).

Chromium은 `file://`에서 ES 모듈을 막으므로(출처가 null이라 CORS 검사를 통과하지 못함) 새 화면은 맞춤 주소 체계로 읽는다.
- `hazop-app://shell/<경로>`: 정해진 폴더(`hazop/shell/web/`)의 파일만. 확장자 표에 있는 것만 돌려준다.
- `hazop-app://shell/api/<…>`: 읽기 API(`hazop.shell.api.ReadApi`). GET만이다. 쓰기는 이 길로 받지 않는다(명령 길은 따로).
- `hazop-app://shell/icons/<이름>.svg`: 아이콘 목록(manifest)에 있는 이름만.

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
HOST_SHELL = "shell"   # 화면·정적 파일·읽기 API·아이콘이 모두 이 한 호스트(한 출처)다. 읽기 API는 /api/…, 아이콘은 /icons/…
ORIGIN = "%s://%s" % (SCHEME, HOST_SHELL)
MAX_PARTS = 32
MAX_PART_CHARS = 255
MIME = {".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
        ".svg": "image/svg+xml", ".json": "application/json", ".png": "image/png"}
# 스크립트·연결·그림은 자기 출처만(주소 체계 전체가 아니다). base-uri·form-action은 막는다.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'none'; "
       "base-uri 'none'; form-action 'none'")
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
    """allow_test: web/test/(웹 단위 시험)를 내줄지. 실행 중에는 시험 모드(HAZOP_DEBUG)일 때만 켜고 배포본에는 그 폴더가 없다."""

    def __init__(self, web_root, api=None, icons_dir=None, icon_names=(), allow_test=False):
        self.web_root = os.path.realpath(web_root)
        self.api = api
        self.icons_dir = os.path.realpath(icons_dir) if icons_dir else None
        self.icon_names = frozenset(icon_names)
        self.allow_test = allow_test

    # ------------------------------------------------------------ 진입
    @staticmethod
    def is_api(url):
        """읽기 API 요청인지(Qt 처리기가 작업 스레드로 돌릴지 정한다)."""
        try:
            parts = urlsplit(url)
            return parts.scheme.lower() == SCHEME and (parts.hostname or "").lower() == HOST_SHELL and parts.path.startswith("/api/")
        except ValueError:
            return False

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
        if (host or "").lower() != HOST_SHELL:
            return _error(404, "없는 자리")
        path = parts_url.path
        try:
            if path.startswith("/api/"):
                resp = self._api(path[len("/api"):], parts_url.query)
            elif path.startswith("/icons/"):
                resp = self._icon(path[len("/icons"):])
            elif path.startswith("/test/") and not self.allow_test:
                return _error(404, "시험 모드에서만 열림")
            else:
                resp = self._static(path)
        except ValueError:
            return _error(400, "잘못된 경로")
        # 머리는 Qt 처리기가 웹 엔진에 싣지 못한다(PySide가 머리 사전을 잘못 풀어 값이 깨짐, 실측). CSP는 index.html의 meta가, nosniff는 확장자 MIME 표가 맡는다.
        resp.headers.setdefault("Cache-Control", "no-cache")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
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
    # SecureScheme: 보안 맥락(모듈·fetch). CorsEnabled·FetchApiAllowed: 같은 출처 fetch()로 읽기 API를 부르려면 필요(Qt 6.6 이상).
    # LocalScheme·LocalAccessAllowed는 **켜지 않는다**(규격 §10 1). 이 둘은 이 주소 체계를 file·qrc 같은 '로컬 주소'로 다루는 표시인데, 그러면
    # 새 화면 웹뷰가 LocalContentCanAccessFileUrls=False(바깥 file 읽기 차단)일 때 이 주소 체계의 모듈 스크립트도 막혀 화면이 안 그려진다
    # (2026-11-13 PySide6 6.12 오프스크린 실측: 1) LocalAccessAllowed만 빼면 안 그려짐, 2) 그 상태에서 FileUrls를 True로 풀면 그려짐,
    # 3) LocalScheme까지 빼면 FileUrls=False인 채로 그려짐). 그래서 로컬 표시를 모두 빼고, file 읽기 차단은 설정·가로채기·CSP 세 겹으로 유지한다.
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.CorsEnabled | QWebEngineUrlScheme.Flag.FetchApiAllowed)
    QWebEngineUrlScheme.registerScheme(scheme)
    _REGISTERED.append(scheme)


def _handler_class():
    from concurrent.futures import ThreadPoolExecutor

    import shiboken6
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Signal
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlSchemeHandler

    class _Relay(QObject):
        done = Signal(object, object)    # (요청 객체, Future): 작업 스레드에서 내보내고 화면 스레드가 받는다(큐 연결)

    class AppSchemeHandler(QWebEngineUrlSchemeHandler):
        """정적 파일은 화면 스레드에서 바로 답하고, 읽기 API(/api/…)는 작업 스레드에서 돌려 화면이 멈추지 않게 한다(규격 §5.4).
        요청 객체를 붙잡아 두었다가 끝나면 reply, 웹이 버렸으면(destroyed) 아무것도 하지 않는다."""

        def __init__(self, router, parent=None):
            super().__init__(parent)
            self.router = router
            # 큰 프로젝트에서는 구간 목록 같은 읽기 하나가 수 초 걸린다. 일꾼이 둘뿐이면 그 사이 도면 목록·상태 읽기가 줄을 서서 열기가 늦어진다(측정: 143쪽에서 도면 목록이 5초 늦게 시작).
            self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hazop-api")
            self._live = set()
            self._down = False
            self._relay = _Relay(self)
            self._relay.done.connect(self._finish)

        def requestStarted(self, job):  # noqa: N802 (Qt 이름)
            url = job.requestUrl().toString()
            method = bytes(job.requestMethod()).decode("ascii", "replace")
            if not Router.is_api(url):
                self._reply(job, self.router.resolve(url, method))
                return
            if self._down:   # 창이 닫히는 중: 새 읽기는 받지 않는다
                job.fail(QWebEngineUrlRequestJob.Error.RequestAborted)
                return
            self._live.add(job)
            job.destroyed.connect(lambda *_a, j=job: self._live.discard(j))
            self._pool.submit(self.router.resolve, url, method).add_done_callback(lambda fut, j=job: self._relay.done.emit(j, fut))

        def _finish(self, job, fut):
            if job not in self._live or not shiboken6.isValid(job):
                return
            self._live.discard(job)
            try:
                resp = fut.result()
            except Exception:  # noqa: BLE001 - 안쪽 오류 글은 웹에 보내지 않는다
                LOG.exception("읽기 API 작업 오류")
                resp = Response(500, "application/json", b'{"error":"internal"}')
            self._reply(job, resp)

        @staticmethod
        def _reply(job, resp):
            if resp.status != 200:
                job.fail({404: QWebEngineUrlRequestJob.Error.UrlNotFound}.get(resp.status, QWebEngineUrlRequestJob.Error.RequestDenied))
                return
            buf = QBuffer(job)
            buf.setData(QByteArray(resp.body))
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            job.reply(QByteArray(resp.mime.encode("ascii")), buf)

        def shutdown(self):
            self._down = True
            self._live.clear()
            self._pool.shutdown(wait=False, cancel_futures=True)

    return AppSchemeHandler


def install(profile, router):
    """프로필에 처리기를 붙인다(이미 붙어 있으면 바꾼다). 처리기 객체를 돌려준다(프로필이 소유)."""
    handler = _handler_class()(router, profile)
    profile.removeUrlScheme(SCHEME.encode("ascii"))
    profile.installUrlSchemeHandler(SCHEME.encode("ascii"), handler)
    return handler
