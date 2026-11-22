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

    from hazop.shell import scheme
    scheme.register()  # 앱 전용 주소 체계 hazop-app://는 QApplication보다 먼저 등록한다(hazop/shell/scheme.py)

    app = QApplication.instance()
    if app is None:
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        app = QApplication(list(argv if argv is not None else sys.argv))
        app.setApplicationName("HAZOP")
    app.setFont(QFont(tokens.FONT_FAMILY, 10))
    install_qt_translation(app)
    return app


QT_TRANSLATION = "qtbase_ko"  # Qt 기본 대화상자(입력 창 OK/Cancel 등)를 한국어로. 배포본에도 묶인다(packaging/verify_bundle)
TRANSLATION_FAILED = "Qt 기본 번역(%s)을 읽지 못함: 대화상자 단추가 영어로 보일 수 있음" % QT_TRANSLATION


def qt_translation_dirs():
    """번역 파일을 찾을 폴더: Qt가 아는 번역 폴더, 그다음 PySide6 패키지 안 translations(묶인 실행)."""
    import os

    import PySide6
    from PySide6.QtCore import QLibraryInfo
    return [QLibraryInfo.path(QLibraryInfo.TranslationsPath), os.path.join(os.path.dirname(PySide6.__file__), "translations")]


def install_qt_translation(app):
    """Qt 기본 번역을 한 번만 건다. 걸었으면 True. 못 읽으면 경고만 남기고 영어 단추로 계속 띄운다."""
    import logging

    from PySide6.QtCore import QTranslator
    if getattr(app, "_hazop_qt_translator", None) is not None:
        return True
    tr = QTranslator(app)
    if not any(tr.load(QT_TRANSLATION, d) for d in qt_translation_dirs() if d):
        logging.getLogger("hazop.startup").warning(TRANSLATION_FAILED)
        return False
    app.installTranslator(tr)
    app._hazop_qt_translator = tr
    return True
