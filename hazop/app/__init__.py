"""PySide6 데스크톱 인터페이스 (기획서/인터페이스.md). 업무 로직은 기존 API(hazop.register·analysis·review·export·viewer)를
호출만 한다. 네트워크 모듈을 쓰지 않으며(tests/test_app.py 정적 검사), 웹뷰의 외부 요청은 hazop/app/webview.py에서 막는다."""


def make_application(argv=None):
    """QApplication 생성. QtWebEngine은 QApplication보다 먼저 가져오고 OpenGL 문맥 공유를 켜야 한다."""
    import sys

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6 import QtWebEngineWidgets  # noqa: F401  (QApplication 전에 가져와야 함)
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from hazop.app import tokens

    app = QApplication.instance()
    if app is None:
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        app = QApplication(list(argv if argv is not None else sys.argv))
        app.setApplicationName("HAZOP")
    app.setFont(QFont(tokens.FONT_FAMILY, 10))
    return app
