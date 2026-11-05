"""데스크톱 인터페이스 검사를 한 번에 실행한다 (QA용). 네트워크·AI 호출 없음.

1) 정적 검사: hazop/app·scripts/run_app.py·이 파일이 네트워크 모듈을 가져오지 않음(ast), 뷰어 템플릿 <script> 3개 유지·
   qwebchannel.js 미포함, 색 토큰이 웹뷰 CSS와 Qt 스타일에 같은 값으로 들어감
2) 웹뷰 설정: 원격 URL 접근 끔, 파일 URL 교차 접근 끔, off-the-record 프로필, 요청 가로채기·탐색 제한, 주입 스크립트 2개
3) tests/test_app.py (QT_QPA_PLATFORM=offscreen: 창·단계 전환, ①등록·추출·그래프, ④⑤ 실행 열기, ⑤ 저장 차단·새 버전,
   Excel 출력, 웹뷰 브리지·강조·외부 요청 차단)
종료 코드 0 = 전부 통과.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from hazop.console import safe_console  # noqa: E402


def ok(label, cond, failures):
    print("  [%s] %s" % ("OK" if cond else "FAIL", label))
    if not cond:
        failures.append(label)


def static_checks(failures):
    from hazop.app import tokens
    from hazop.viewer import build, check
    from tests import test_app
    print("1) 정적 검사")
    files = test_app.app_sources()
    bad = {os.path.relpath(f, REPO_ROOT): test_app.network_imports(f) for f in files}
    bad = {k: v for k, v in bad.items() if v}
    ok("앱 코드 %d개 파일에 네트워크 모듈 import 없음%s" % (len(files), (" — " + repr(bad)) if bad else ""), not bad, failures)
    with open(build.TEMPLATE, encoding="utf-8") as fh:
        tpl = fh.read().lower()
    ok("템플릿 <script> %d개(기대 %d), qwebchannel 미포함" % (tpl.count("<script"), check.TEMPLATE_SCRIPT_COUNT),
       tpl.count("<script") == check.TEMPLATE_SCRIPT_COUNT == 3 and "qwebchannel" not in tpl, failures)
    css, qss = tokens.web_css(), tokens.qss()
    ok("토큰 한 곳 정의: 웹뷰 CSS에 모든 색 토큰, Qt 스타일에 UI 강조색",
       all("--%s: %s" % (k, v) in css for k, v in tokens.COLORS.items()) and tokens.COLORS["ui"] in qss, failures)


def webview_checks(failures):
    print("2) 웹뷰 설정")
    from PySide6.QtCore import QUrl
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from hazop.app import make_application
    from hazop.app.webview import HazopWebView, url_allowed
    make_application(["check_app"])
    v = HazopWebView()
    s = v.page().settings()
    ok("LocalContentCanAccessRemoteUrls 끔", not s.testAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls),
       failures)
    ok("LocalContentCanAccessFileUrls 끔", not s.testAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls), failures)
    ok("off-the-record 프로필(디스크 캐시·쿠키 저장 없음)", v.profile.isOffTheRecord(), failures)
    ok("요청 가로채기: http·https·ws 차단, file·qrc 허용",
       not any(url_allowed(u) for u in ("http://a", "https://a", "ws://a")) and url_allowed("file:///C:/a.html")
       and url_allowed("qrc:///qtwebchannel/qwebchannel.js"), failures)
    ok("원격 주소 탐색 차단", not v.page().acceptNavigationRequest(QUrl("https://example.com"), 0, True), failures)
    names = [sc.name() for sc in v.page().scripts().toList()]
    ok("qwebchannel.js·브리지 스크립트 실행 시점 주입: %s" % names, names == ["hazop-qwebchannel", "hazop-bridge"], failures)
    v.dispose()
    v.deleteLater()


def main():
    safe_console()
    failures = []
    for step in (static_checks, webview_checks):
        try:
            step(failures)
        except Exception as e:  # 검사 도중 예외도 실패로 보고
            failures.append("예외: %r" % e)
            print("  [FAIL] 예외: %r" % e)
    print("3) tests/test_app.py")
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_app")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok("단위 테스트 %d개" % result.testsRun, result.wasSuccessful(), failures)
    print("결과: %s" % ("전부 통과" if not failures else "실패 %d건: %s" % (len(failures), failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
