"""새 웹 화면의 창(docs/design/app-shell-web.md §5.2·§5.7). QMainWindow 하나에 웹 화면 하나를 올린다.

- `ShellBridge`: QWebChannel로 웹에 노출하는 객체. 웹 → 엔진 메시지는 JSON 문자열 하나이고 길이 상한·JSON 파싱·형식 검사를 거친다.
  `{"t":"cmd","id","name","args"}`는 `Engine.dispatch`가 표에 있는 이름만 받아 돌리고 `{"t":"reply"}`로 답한다.
  엔진 → 웹은 `changed`·`event`다. 세션 콜백은 다른 스레드에서 오므로 큐 연결 신호로 화면 스레드에 넘긴다.
- `ShellView`: 원격 요청 차단(`LocalOnlyInterceptor`)과 주 프레임 이동 제한을 그대로 쓰고, 이동 허용 대상만 `hazop-app://shell/index.html`이다.
- 파일 끌어 놓기는 웹 엔진이 경로를 숨기므로 Qt 쪽에서 받는다(이벤트 필터). 웹에는 끌어 놓는 중인지(`drop.hover`)만 알린다.
- 연결(`AiConnection`)·채팅 세션·카드 검사 자료는 이전 화면과 같은 엔진 부품을 쓴다(`main_window.py`와 서로 부르지 않는다).
"""

import json
import logging
import os

from PySide6.QtCore import QEvent, QObject, QUrl, Qt, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMainWindow

from hazop import paths
from hazop.app import icons, webview
from hazop.shell import api, chat, scheme

LOG = logging.getLogger("hazop.shell.window")
SHELL_URL = "hazop-app://shell/index.html"
WEB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
MAX_MESSAGE_CHARS = webview.MAX_MESSAGE_CHARS

# 웹 쪽 연결 스크립트(QWebEngineScript로 주입: 페이지의 CSP를 받지 않는다). window.hazopBridge = {send(text), setHandler(fn)}
BRIDGE_JS = r"""
(function () {
  if (window.hazopBridge) return;
  var out = [], inbox = [], handler = null, bridge = null;
  window.hazopBridge = {
    send: function (text) { if (bridge) bridge.fromWeb(text); else out.push(text); },
    setHandler: function (fn) { handler = fn; while (inbox.length) fn(inbox.shift()); }
  };
  new QWebChannel(qt.webChannelTransport, function (ch) {
    bridge = ch.objects.bridge;
    bridge.toWeb.connect(function (text) { if (handler) handler(text); else inbox.push(text); });
    while (out.length) bridge.fromWeb(out.shift());
  });
})();
"""


class ShellBridge(QObject):
    """웹과 주고받는 길. 메시지는 JSON 문자열 하나."""

    toWeb = Signal(str)        # Python → 웹(화면 스레드에서만 내보냄)
    _queued = Signal(str)      # 다른 스레드에서 온 것을 화면 스레드로 넘기는 큐 연결 신호
    uiMessage = Signal(dict)   # 웹의 ui 메시지({"name","data"}): 시험과 도면 부품 신호용

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.log = []          # 디버그 실행의 메시지 기록(HAZOP_DEBUG=1일 때만 쌓는다)
        self._debug = bool(os.environ.get("HAZOP_DEBUG"))
        self._queued.connect(self._deliver, Qt.QueuedConnection)

    def send(self, obj):
        """엔진 → 웹. 어느 스레드에서든 부를 수 있다."""
        text = json.dumps(obj, ensure_ascii=False)
        self._queued.emit(text)

    @Slot(str)
    def _deliver(self, text):
        if self._debug:
            self.log.append(("out", text[:2000]))
        self.toWeb.emit(text)

    @Slot(str)
    def fromWeb(self, text):  # noqa: N802 (웹에서 부르는 이름)
        """웹 → 엔진. 믿지 않는다: 길이 상한, JSON 파싱, 형식 검사, 명령 표."""
        if not isinstance(text, str) or len(text) > MAX_MESSAGE_CHARS:
            LOG.warning("웹 메시지 무시: 문자열이 아니거나 길이 상한 %d자 초과", MAX_MESSAGE_CHARS)
            return
        try:
            msg = json.loads(text)
        except (TypeError, ValueError, RecursionError):
            LOG.warning("웹 메시지 무시: JSON 파싱 실패")
            return
        if not isinstance(msg, dict):
            return
        if self._debug:
            self.log.append(("in", text[:2000]))
        kind = msg.get("t")
        if kind == "cmd":
            cid = msg.get("id")
            if not isinstance(cid, str) or not 1 <= len(cid) <= 40:
                return
            reply = self.engine.dispatch(msg.get("name"), msg.get("args"))
            self.send(dict(reply, t="reply", id=cid))
        elif kind == "ui":
            name = msg.get("name")
            if isinstance(name, str) and len(name) <= 60 and isinstance(msg.get("data", {}), (dict, list, str, int, float, bool, type(None))):
                self.uiMessage.emit({"name": name, "data": msg.get("data")})


class ShellPage(webview.LocalPage):
    """이동 제한: 주 프레임은 hazop-app://shell/index.html만, 하위 프레임·자원은 로컬 스킴만."""

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self.console = []     # 웹 콘솔 기록(시험이 오류 0을 확인한다): (수준, 글, 줄, 출처)

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        self.console.append((int(level.value) if hasattr(level, "value") else int(level), message, line, source))

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
        ok = webview.url_allowed(url)
        if is_main_frame:
            ok = url.toString().split("#", 1)[0] == SHELL_URL
        if not ok:
            self.blocked_navigation.append(url.toString())
        return ok


class ShellView(QWebEngineView):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.profile = webview.QWebEngineProfile.defaultProfile()
        self.profile.setHttpCacheType(webview.QWebEngineProfile.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(webview.QWebEngineProfile.NoPersistentCookies)
        self.interceptor = webview._shared_interceptor(self.profile)
        page = ShellPage(self.profile, self)
        self.setPage(page)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)
        s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.DnsPrefetchEnabled, False)
        s.setAttribute(QWebEngineSettings.AutoLoadIconsForPage, False)
        s.setAttribute(QWebEngineSettings.ErrorPageEnabled, False)
        self.bridge = bridge
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", bridge)
        page.setWebChannel(self.channel)
        for name, source, point in (("hazop-qwebchannel", webview._qwebchannel_js(), QWebEngineScript.DocumentCreation),
                                    ("hazop-shell-bridge", BRIDGE_JS, QWebEngineScript.DocumentCreation)):
            sc = QWebEngineScript()
            sc.setName(name)
            sc.setSourceCode(source)
            sc.setInjectionPoint(point)
            sc.setWorldId(QWebEngineScript.MainWorld)
            sc.setRunsOnSubFrames(False)
            page.scripts().insert(sc)

    def dispose(self):
        """종료 전에 페이지를 먼저 지운다(웹 렌더 프로세스가 남은 채 인터프리터가 끝나면 비정상 종료될 수 있음)."""
        import shiboken6
        page = self.page()
        self.setPage(None)
        if page is not None and shiboken6.isValid(page):
            page.deleteLater()


class AiAdapter:
    """엔진 창구가 쓰는 AI 연결 모양(status·check). 이전 화면과 같은 `AiConnection` 위에 얹는다."""

    def __init__(self, ai_conn, on_checked):
        self.conn = ai_conn
        self.on_checked = on_checked

    def status(self):
        from hazop.app import conn_view
        st = self.conn.status("subscription")
        look = conn_view.look("subscription", st.get("state"))
        return {"state": st.get("state"), "detail": st.get("detail") or "", "plan": st.get("plan"), "limit": st.get("limit"),
                "label": look.label, "short": look.short, "tone": look.tone, "title": look.title,
                "guide": look.guide.replace("{pct}", "").replace("{reset}", "").replace("{detail}", st.get("detail") or "").replace("{count}", ""),
                "can_start": bool(look.can_start)}

    def check(self):
        self.conn.check("subscription", done=lambda _st: self.on_checked())

    def make_client(self):
        return self.conn.make_client()


class ShellWindow(QMainWindow):
    """새 화면의 창. 설정 파일 경로를 받아 엔진·연결·채팅을 만들고 웹 화면을 연다."""

    def __init__(self, settings_path=None, ask_reviewer=True, debug=False, size=(1440, 860), session_factory=None, env_provider=None):
        super().__init__()
        from hazop.app import tokens
        from hazop.app.ai_conn import AiConnection
        from hazop.study.ai_settings import AiPrefs
        from hazop.study.apikey import STORE_FILE_NAME, KeyStore
        self.setWindowTitle("HAZOP 분석 도구")
        self.resize(*size)
        self.setStyleSheet("QMainWindow { background: %s; }" % tokens.SHELL["bg"])
        self._debug = debug or bool(os.environ.get("HAZOP_DEBUG"))
        self.engine = api.Engine(settings_path=settings_path)
        self.bridge = ShellBridge(self.engine, self)
        self.engine._emit = self.bridge.send
        self.api = api.ReadApi(self.engine)
        scheme.install(webview.QWebEngineProfile.defaultProfile(), scheme.Router(
            WEB_ROOT, api=self.api, icons_dir=paths.folder("icons", "tabler"), icon_names=icons.names()))
        keys = KeyStore(os.path.join(os.path.dirname(settings_path or paths.settings_path()), STORE_FILE_NAME))
        prefs = AiPrefs(self.engine.settings, lambda s: paths.save_settings(s, settings_path))
        self.ai_conn = AiConnection(prefs, keys, debug=self._debug, parent=self)
        self.engine.ai = AiAdapter(self.ai_conn, lambda: self._on_conn(user_check=True))
        self.ai_conn.changed.connect(self._on_conn)
        self.chat = chat.ChatController(self.bridge.send, session_factory or self._make_session, env_provider or self._card_env,
                                        project_fn=self.engine.project_id, model=self.engine.settings.get("chat_model") or "fast")
        self.engine.chat = self.chat
        self._ctx = None
        self.engine.hooks["pick_files"] = self._pick_files
        self.engine.hooks["open_classic"] = self._open_classic
        self.engine.hooks["conn_guide"] = self._conn_guide
        self.classic_requested = False
        self.view = ShellView(self.bridge, self)
        self.setCentralWidget(self.view)
        self.setAcceptDrops(True)
        self._drop_targets = []
        self.view.installEventFilter(self)
        self.view.loadFinished.connect(self._loaded)
        self.view.load(QUrl(SHELL_URL))
        self._on_conn()

    # ------------------------------------------------------------ 연결·채팅 부품
    def _on_conn(self, user_check=False):
        st = self.ai_conn.status("subscription")
        self.chat.set_availability(st.get("state"), st.get("detail") or "", user_check=user_check)
        self.bridge.send({"t": "event", "name": "conn.changed", "data": self.engine.ai.status()})

    def _make_session(self, model, callbacks):
        pid = self.engine.project_id()
        from hazop.chat import card as chatcard
        try:
            from hazop.chat.session import ChatSession
        except ImportError as exc:
            raise ValueError("이 설치에는 채팅 부품이 없습니다(%s)." % exc) from exc
        return ChatSession(pid, model=model, schema=chatcard.CARD_SCHEMA, system_prompt=chatcard.SYSTEM_PROMPT, **callbacks)

    def _card_env(self):
        """-> (CardEnv, 프로젝트 그래프) 또는 None. 같은 프로젝트면 파일 지문이 같을 때 읽은 묶음을 다시 쓴다."""
        from hazop.chat import card as chatcard
        from hazop.chat import context as chatcontext
        pid = self.engine.project_id()
        ctx = self._ctx
        ctx = chatcontext.refresh(ctx) if ctx is not None and ctx.project_id == pid else chatcontext.load_context(pid)
        self._ctx = ctx
        return chatcard.ContextEnv(ctx), ctx.pg

    # ------------------------------------------------------------ 창
    def _loaded(self, ok):
        if not ok:
            LOG.error("웹 화면을 읽지 못함: %s", SHELL_URL)

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "도면 파일 고르기", "", "도면 (*.drawio *.pdf)")
        return files

    def _conn_guide(self, name):
        from hazop.app.settings_dialog import ACTION_HELP, show_help
        show_help(self, ACTION_HELP["install_help" if name == "install" else "terminal_login"])

    def _open_classic(self):
        self.classic_requested = True
        self.close()

    def _local_files(self, mime):
        out = []
        for url in mime.urls():
            if url.isLocalFile():
                out.append(url.toLocalFile())
        return out

    def eventFilter(self, obj, event):  # noqa: N802
        """웹 엔진 안쪽 위젯의 끌어 놓기를 가로채 파일 경로를 받는다(웹은 경로를 숨긴다)."""
        t = event.type()
        if t in (QEvent.ChildAdded,) and isinstance(event.child(), QObject) and hasattr(event.child(), "setAcceptDrops"):
            child = event.child()
            child.installEventFilter(self)
            self._drop_targets.append(child)
        if t in (QEvent.DragEnter, QEvent.DragMove) and event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.bridge.send({"t": "event", "name": "drop.hover", "data": {"over": True}})
            return True
        if t == QEvent.DragLeave:
            self.bridge.send({"t": "event", "name": "drop.hover", "data": {"over": False}})
        if t == QEvent.Drop and event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.bridge.send({"t": "event", "name": "drop.hover", "data": {"over": False}})
            self.drop_files(self._local_files(event.mimeData()))
            return True
        return super().eventFilter(obj, event)

    def drop_files(self, files):
        files = [f for f in files if os.path.splitext(f)[1].lower() in api.REGISTRABLE_EXT]
        if not files:
            self.bridge.send({"t": "event", "name": "drop.refused", "data": {"text": "도면 파일(.drawio, .pdf)만 받습니다."}})
            return {"ok": False}
        return self.engine.dispatch("register.add_files", {"paths": files[:api.MAX_FILES]})

    def closeEvent(self, event):  # noqa: N802
        self.chat.shutdown()
        self.view.dispose()
        super().closeEvent(event)
