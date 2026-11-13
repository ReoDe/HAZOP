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
from PySide6.QtWebEngineCore import QWebEngineScript, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from hazop import paths
from hazop.app import icons, webview
from hazop.shell import api, chat, chat_actions, scheme

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
            reply = self.engine.dispatch(msg.get("name"), msg.get("args"), project=msg.get("project"), via_web=True)
            self.send(dict(reply, t="reply", id=cid))
        elif kind == "ui":
            name = msg.get("name")
            if isinstance(name, str) and len(name) <= 60 and isinstance(msg.get("data", {}), (dict, list, str, int, float, bool, type(None))):
                self.uiMessage.emit({"name": name, "data": msg.get("data")})


class ShellPage(webview.LocalPage):
    """이동 제한: 주 프레임은 hazop-app://shell/index.html만, 하위 프레임은 없다(자원 요청의 원격 차단은 프로필의 LocalOnlyInterceptor가 한다)."""

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self.console = []     # 웹 콘솔 기록(시험이 오류 0을 확인한다): (수준, 글, 줄, 출처)

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        self.console.append((int(level.value) if hasattr(level, "value") else int(level), message, line, source))

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
        # 새 화면은 file 주소를 허용하지 않고 하위 프레임도 쓰지 않는다: 주 프레임은 SHELL_URL 하나뿐이다
        ok = is_main_frame and url.toString().split("#", 1)[0] == SHELL_URL
        if not ok:
            self.blocked_navigation.append(url.toString())
        return ok


# 새 화면 웹뷰가 요청할 수 있는 주소 체계. file·qrc·원격은 없다(이전 화면의 webview.ALLOWED_SCHEMES와 따로, 규격 §5.1 '새 화면 웹뷰의 허용 체계')
SHELL_SCHEMES = frozenset({"hazop-app", "data", "about", "blob"})


class ShellInterceptor(QWebEngineUrlRequestInterceptor):
    """새 화면 전용 요청 가로채기: SHELL_SCHEMES 밖의 요청(file://·원격 주소 등)은 막고 blocked에 남긴다. meta CSP와 별개인 둘째 겹이다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.blocked = []

    def interceptRequest(self, info):  # noqa: N802 (Qt 이름)
        url = info.requestUrl()
        if url.scheme().lower() not in SHELL_SCHEMES:
            self.blocked.append(url.toString())
            info.block(True)


class ShellView(QWebEngineView):
    def __init__(self, bridge, router=None, parent=None):
        super().__init__(parent)
        # 새 화면은 전용 프로필(디스크에 저장하지 않는 off-the-record)을 쓴다: 이전 화면의 가로채기·처리기와 섞이지 않는다.
        # 종료 때 페이지를 먼저 지우도록 dispose()가 순서를 지킨다.
        self.profile = webview.QWebEngineProfile(self)
        self.profile.setHttpCacheType(webview.QWebEngineProfile.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(webview.QWebEngineProfile.NoPersistentCookies)
        self.interceptor = ShellInterceptor(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.handler = scheme.install(self.profile, router) if router is not None else None
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
        """종료 전에 페이지를 먼저 지우고 그다음 프로필을 지운다(페이지보다 프로필이 먼저 지워지면 비정상 종료될 수 있음)."""
        import shiboken6
        if self.handler is not None and shiboken6.isValid(self.handler):
            self.handler.shutdown()
        page = self.page()
        self.setPage(None)
        if page is not None and shiboken6.isValid(page):
            page.deleteLater()
        if shiboken6.isValid(self.profile):
            self.profile.deleteLater()


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

    def terms_acked(self):
        return self.conn.terms_acked()

    def ack_terms(self):
        self.conn.prefs.ack_terms()


class ShellWindow(QMainWindow):
    """새 화면의 창. 설정 파일 경로를 받아 엔진·연결·채팅을 만들고 웹 화면을 연다."""

    jobs_idle = Signal()   # 작업 스레드에서 마지막 작업이 끝났을 때(큐 연결로 화면 스레드가 받는다)

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
        self.router = scheme.Router(WEB_ROOT, api=self.api, icons_dir=paths.folder("icons", "tabler"), icon_names=icons.names(),
                                    allow_test=self._debug)   # web/test/는 시험 모드(HAZOP_DEBUG)일 때만 내준다
        keys = KeyStore(os.path.join(os.path.dirname(settings_path or paths.settings_path()), STORE_FILE_NAME))
        prefs = AiPrefs(self.engine.settings, lambda s: paths.save_settings(s, settings_path))
        self.ai_conn = AiConnection(prefs, keys, debug=self._debug, parent=self)
        self.engine.ai = AiAdapter(self.ai_conn, lambda: self._on_conn(user_check=True))
        self.ai_conn.changed.connect(self._on_conn)
        env_fn = env_provider or self._card_env
        self.chat_actions = chat_actions.ChatActions(
            lambda name, data: self.bridge.send({"t": "event", "name": name, "data": data}), self.engine.project_id,
            lambda: (env_fn() or (None, None))[1], self.engine.reviewer,
            self.engine.changed, model_fn=lambda: self.engine.settings.get("chat_model"))
        self.chat = chat.ChatController(self.bridge.send, session_factory or self._make_session, env_fn,
                                        project_fn=self.engine.project_id, model=self.engine.settings.get("chat_model") or "fast",
                                        actions=self.chat_actions)
        self.engine.chat = self.chat
        self._ctx = None
        self.engine.hooks["pick_files"] = self._pick_files
        self.engine.hooks["pick_doc"] = self._pick_doc
        self.engine.hooks["open_classic"] = self._open_classic
        self.engine.hooks["conn_guide"] = self._conn_guide
        self.engine.hooks["save_path"] = self._save_path
        self.engine.hooks["save_dir"] = self._save_dir
        self.engine.hooks["confirm_overwrite_files"] = self._ask_overwrite_files
        self.engine.hooks["jobs_idle"] = self.jobs_idle.emit
        self.jobs_idle.connect(self._on_jobs_idle)
        self.confirm_overwrite_files = self._ask_overwrite_files_box     # 시험이 모달 창 없이 답을 꽂는 자리: True(덮어씀) | False
        self.confirm_overwrite = self._ask_overwrite    # 시험이 모달 창 없이 답을 꽂는 자리: True(덮어씀) | False
        self.confirm_busy = self._ask_busy     # 시험이 모달 창 없이 답을 꽂는 자리: ("stop"|"wait"|"cancel") <- (작업 수)
        self._close_when_idle = False
        self._closing = False
        self.classic_requested = False
        self.view = ShellView(self.bridge, self.router, self)
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
        files, _ = QFileDialog.getOpenFileNames(self, "도면 파일 고르기", "", "도면 (*.drawio *.pdf *.xml)")
        return files

    def _pick_doc(self):
        """설계 문서 PDF 고르기(문서 패널). 도면 파일은 보이지 않는다."""
        files, _ = QFileDialog.getOpenFileNames(self, "설계 문서 PDF 고르기", "", "설계 문서 PDF (*.pdf)")
        return files

    def _save_path(self, kind, default_name):
        """내보내기 저장 위치를 묻는다(웹은 경로를 보내지 않는다). 취소하면 None."""
        from PySide6.QtCore import QStandardPaths
        folder = getattr(self, "_export_dir", None) or QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        title = "Excel로 내보내기" if kind == "excel" else "초기사건 인계 묶음 내보내기"
        # 덮어쓰기는 확장자를 붙인 뒤의 경로로 우리가 묻는다(대화상자가 묻는 것은 붙이기 전 경로라 .xlsx를 덧붙이면 건너뛴다)
        path, _ = QFileDialog.getSaveFileName(self, title, os.path.join(folder, default_name), "Excel 통합 문서 (*.xlsx)",
                                              options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return None
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        if os.path.exists(path) and not self.confirm_overwrite(path):
            return None
        self._export_dir = os.path.dirname(path)
        return path

    def _save_dir(self, kind):
        """DEXPI 내보내기 저장 폴더를 묻는다(웹은 경로를 보내지 않는다). 취소하면 None."""
        from PySide6.QtCore import QStandardPaths
        start = getattr(self, "_export_dir", None) or QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        folder = QFileDialog.getExistingDirectory(self, "DEXPI로 내보낼 폴더 고르기", start)
        if folder:
            self._export_dir = folder
        return folder or None

    def _ask_overwrite_files(self, names):
        """같은 이름의 파일이 있으면 덮어쓸지 묻는다(시험은 seam을 바꿔 끼운다). True면 덮어씀."""
        return self.confirm_overwrite_files(names)

    def _ask_overwrite_files_box(self, names):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("덮어쓸까요?")
        box.setText("같은 이름의 파일이 이미 있습니다(%d개)." % len(names))
        more = "\n…" if len(names) > 8 else ""
        box.setInformativeText("\n".join(names[:8]) + more + "\n덮어쓰면 이전 내용은 사라집니다.")
        yes = box.addButton("덮어쓰기", QMessageBox.DestructiveRole)
        no = box.addButton("취소", QMessageBox.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        return box.clickedButton() is yes

    def _ask_overwrite(self, path):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("덮어쓸까요?")
        box.setText("같은 이름의 파일이 이미 있습니다.\n%s" % os.path.basename(path))
        box.setInformativeText("덮어쓰면 이전 내용은 사라집니다.")
        yes = box.addButton("덮어쓰기", QMessageBox.DestructiveRole)
        no = box.addButton("취소", QMessageBox.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        return box.clickedButton() is yes

    def _conn_guide(self, name):
        from hazop.app.settings_dialog import ACTION_HELP, show_help
        show_help(self, ACTION_HELP["install_help" if name == "install" else "terminal_login"])

    def _open_classic(self):
        """이전 화면으로 바꾼다 -> 창이 닫히면 True. 등록·추출이 도는 중이면 closeEvent가 묻고, 닫히지 않으면 이전 화면 요청을 거둔다."""
        self.classic_requested = True
        ok = self.close()
        if not ok and not self._close_when_idle:
            self.classic_requested = False
        return ok

    BUSY_TEXT = {"register": ("도면 등록·추출 작업", "멈추면 지금 단계가 끝나는 자리에서 멈춥니다(등록까지 끝난 도면은 목록에 남습니다)."),
                 "analysis": ("AI 분석 작업", "멈추면 진행 중인 호출이 끝나는 자리에서 멈춥니다(이미 받은 칸은 저장되어 있습니다).")}

    @classmethod
    def busy_text(cls, kinds):
        """도는 작업의 종류에 맞는 확인 글 -> (제목 줄, 설명)."""
        kinds = list(kinds or ["register"])
        names = [cls.BUSY_TEXT.get(k, cls.BUSY_TEXT["register"]) for k in dict.fromkeys(kinds)]
        head = "·".join(n[0] for n in names) + " %d개가 진행 중입니다." % len(kinds)
        return head, " ".join(n[1] for n in names)

    def _ask_busy(self, n, kinds=None):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("작업이 진행 중입니다")
        head, info = self.busy_text(kinds)
        box.setText(head)
        box.setInformativeText(info)
        stop = box.addButton("멈추고 닫기", QMessageBox.DestructiveRole)
        wait = box.addButton("끝나면 닫기", QMessageBox.AcceptRole)
        keep = box.addButton("계속 사용", QMessageBox.RejectRole)
        box.setDefaultButton(keep)
        box.exec()
        clicked = box.clickedButton()
        return "stop" if clicked is stop else "wait" if clicked is wait else "cancel"

    def _on_jobs_idle(self):
        if self._close_when_idle and not self.engine.running_jobs():
            self._close_when_idle = False
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
            self.bridge.send({"t": "event", "name": "drop.refused", "data": {"text": "도면 파일(.drawio, .pdf, DEXPI .xml)만 받습니다."}})
            return {"ok": False}
        try:
            return dict(self.engine.add_files(files[:api.MAX_FILES]), ok=True)
        except api.CommandError as exc:
            self.bridge.send({"t": "event", "name": "drop.refused", "data": {"text": exc.message}})
            return {"ok": False}

    def closeEvent(self, event):  # noqa: N802
        running = self.engine.running_jobs()
        if running and not self._closing:
            choice = self.confirm_busy(len(running), self.engine.running_kinds())
            if choice == "cancel":
                event.ignore()
                return
            if choice == "stop":
                self.engine.stop_jobs()
                self.engine.wait_jobs(30)               # 추출 호출 하나가 길면 끝나기를 기다렸다 닫는다
            if self.engine.running_jobs():
                self._close_when_idle = True
                self.bridge.send({"t": "event", "name": "app.notice", "data": {"text": "진행 중인 작업이 끝나면 창을 닫습니다."}})
                event.ignore()
                return
        self._closing = True
        self.chat.shutdown()
        self.view.dispose()
        super().closeEvent(event)
