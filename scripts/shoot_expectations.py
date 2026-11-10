"""③ 잠재 후보 화면 스크린샷을 1366×768·1920×1080에서 찍는다. 사용: python scripts/shoot_expectations.py <출력 폴더>

임시 작업 루트에 샘플 6장(SNP-SAMPLE)과 지식그래프를 둔다(scripts/shoot_results.prepare, 네트워크 없음). SNP-M-102에서
- 3-expect-legend: 왼쪽 '잠재 후보' 묶음·관계 '기대'·'AI 초안'·'기대 공백' 표시, 기대 공백 강조를 켬
- 3-expect-detail: 후보 발견 잠재 후보를 골라 상세 패널(규칙·근거 수준·후보·판단 버튼)
- 3-expect-absent: 기대됨 항목을 임시 폴더에 부재 확정으로 저장한 뒤의 상세 패널
판단 파일은 임시 작업 루트의 데이터/잠재후보/에만 쓴다.
"""

import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
from hazop import paths  # noqa: E402
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

SIZES = ((1366, 768), (1920, 1080))


def main():
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else paths.output_in(paths.DEV_WORK_ROOT, "스크린샷", "expectations"))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shoot-expect-")
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    files = []
    try:
        import shoot_results
        shoot_results.prepare(os.environ["HAZOP_WORK_ROOT"])
        from hazop.app import make_application
        from hazop.app.main_window import MainWindow
        from hazop.app.screenshots import settle, wait
        app = make_application(["shoot"])
        win = MainWindow(settings_path=os.path.join(tmp, "settings.json"), ask_reviewer=False)
        win.set_reviewer_name("검토자(예시)")
        win.show()
        kgs = win.screens[4]

        def shot(name, w, h):
            wait(lambda: win.webview.isHidden() or win.webview.current_file is None or win.webview.bridge.is_ready, 20)
            settle(2.5)
            p = os.path.join(out_dir, "%s-%dx%d.png" % (name, w, h))
            win.grab().save(p)
            files.append(p)

        def pick(state):
            return next(i for i in kgs.expect["items"] if i["graph_id"] == "graph-SNP-M-102" and i["state"] == state)

        for w, h in SIZES:
            win.showNormal()
            win.resize(w, h)
            settle(0.5)
            win.set_drawing("SNP-M-102")
            win.go(4)
            settle(1.0)
            if kgs.expect is None:
                raise SystemExit("잠재 후보를 계산하지 못함(프로젝트 그래프 없음)")
            win.webview.page().runJavaScript("window.hzKG.setToggles({xgap: true}); "
                                              "document.getElementById('sec-exp').scrollIntoView()")
            shot("3-expect-legend", w, h)
            it = pick("candidate_found")
            win.webview.bridge.send("selectNode", id=it["id"])
            kgs.render_node(it["id"])
            shot("3-expect-detail", w, h)
            if w == SIZES[0][0]:
                target = pick("expected")
                kgs.render_node(target["id"])
                kgs.judge_expectation("absent", reason="샘플 도면·문서에 구동원 정보 없음(스크린샷용)",
                                      evidence="스크린샷용 가상 근거")
            absent = pick("confirmed_absent")
            win.webview.bridge.send("selectNode", id=absent["id"])
            kgs.render_node(absent["id"])
            shot("3-expect-absent", w, h)
        win.close()
        app.processEvents()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for p in files:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
