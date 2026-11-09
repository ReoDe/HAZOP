"""단계별 탐색기(①~⑤) 스크린샷을 1366×768·1920×1080에서 찍는다. 사용: python scripts/shoot_stage_explorer.py <출력 폴더>

임시 작업 루트에 샘플 6장(SNP-SAMPLE 프로젝트)·확정 구간·가짜 AI 결과를 둔다(scripts/shoot_results.prepare, 네트워크 없음).
단계마다 창 전체(<단계>-window)와 탐색기만(<단계>-explorer) 저장한다.
"""

import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

SIZES = ((1366, 768), (1920, 1080))
STAGES = ((0, "1-register"), (1, "2-extract"), (4, "3-graph"), (5, "4-study"), (6, "5-results"))


def main():
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO_ROOT, "출력", "스크린샷", "stage-explorer"))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shoot-explorer-")
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    files = []
    try:
        import shoot_results
        shoot_results.prepare(os.environ["HAZOP_WORK_ROOT"])
        shutil.copytree(os.path.join(REPO_ROOT, "참고자료"), os.path.join(os.environ["HAZOP_WORK_ROOT"], "참고자료"))
        from hazop.app import make_application
        from hazop.app.main_window import MainWindow
        from hazop.app.screenshots import settle, wait
        app = make_application(["shoot"])
        win = MainWindow(settings_path=os.path.join(tmp, "settings.json"), ask_reviewer=False)
        win.set_reviewer_name("검토자(예시)")
        win.api_keys.set(shoot_results.KEY, persist=False)
        win.ai_prefs.choose("api")  # 가짜 API 클라이언트로 돌린다
        win.show()
        win.resize(*SIZES[0])
        win.set_drawing("SNP-M-102")
        win.go(6)
        res = win.screens[6]
        res.make_client = lambda: shoot_results.FakeClient()
        for nid in shoot_results.drawing_node_ids():
            res.matrix.setCurrentCell(res._row_of(nid), 0)
            res.run_ai("node")
            if not wait(lambda: not res.running(), 180):
                raise SystemExit("AI 분석(가짜)이 끝나지 않음")
        for w, h in SIZES:
            win.showNormal()
            win.resize(w, h)
            settle(0.5)
            for index, name in STAGES:
                win.set_drawing("SNP-M-102")
                win.go(index)
                wait(lambda: win.webview.isHidden() or win.webview.current_file is None or win.webview.bridge.is_ready, 20)
                settle(2.0)
                for part, widget in (("window", win), ("explorer", win.explorer_panel)):
                    p = os.path.join(out_dir, "%s-%s-%dx%d.png" % (name, part, w, h))
                    widget.grab().save(p)
                    files.append(p)
        win.close()
        app.processEvents()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for p in files:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
