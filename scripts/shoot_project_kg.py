"""도면 통합 화면 스크린샷: ②·④·⑤·탐색기를 1366×768·1920×1080에서 찍는다. 사용: python scripts/shoot_project_kg.py <출력 폴더>

임시 작업 루트에 샘플 6장(도면 연결로 이어진 SNP-SAMPLE 프로젝트)과 확정한 프로젝트 검토구간, 가짜 AI 결과(SNP-M-102 구간)를
둔다(scripts/shoot_results.prepare, 네트워크 없음). 여러 도면에 걸친 구간(⇄)을 골라 찍는다.
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


def main():
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO_ROOT, "출력", "스크린샷", "project-kg"))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shoot-pkg-")
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
        win.show()
        win.resize(*SIZES[0])
        win.go(6)
        res = win.screens[6]
        res.make_client = lambda: shoot_results.FakeClient()
        for nid in shoot_results.drawing_node_ids():
            res.matrix.setCurrentCell(res._row_of(nid), 0)
            res.run_ai("node")
            if not wait(lambda: not res.running(), 180):
                raise SystemExit("AI 분석(가짜)이 끝나지 않음")
        study = win.screens[5]

        def shot(name, w, h):
            wait(lambda: win.webview.isHidden() or win.webview.current_file is None or win.webview.bridge.is_ready, 20)
            settle(2.5)
            p = os.path.join(out_dir, "%s-%dx%d.png" % (name, w, h))
            win.grab().save(p)
            files.append(p)

        for w, h in SIZES:
            win.showNormal()
            win.resize(w, h)
            settle(0.5)
            win.set_drawing("SNP-M-102")
            win.go(5)
            settle(1.0)
            span_id = next(n["node_id"] for n in study.view["nodes"]
                           if n.get("spans_drawings") and "SNP-M-102" in n["drawings"])
            study.select_node(span_id)
            shot("4-study-span-%s-102" % span_id, w, h)
            study.jump("SNP-M-101", span_id)
            settle(1.5)
            shot("4-study-span-%s-101-after-chip" % span_id, w, h)
            study.show_overview()
            shot("4-study-overview-101-chips", w, h)
            win.go(1)
            win.screens[1].select_drawing("SNP-M-102")
            settle(1.5)
            shot("2-viewer-102-chips", w, h)
            win.screens[1].select_drawing("SNP-M-401")
            settle(1.5)
            shot("2-viewer-401-unlinked", w, h)
            win.set_drawing("SNP-M-102")
            win.go(6)
            res.show_node("SNP-M-102", span_id)
            shot("5-results-span-%s" % span_id, w, h)
            win.explorer_drawing.setCurrentIndex(win.explorer_drawing.findText("SNP-M-301"))
            settle(0.5)
            shot("explorer-filter-301", w, h)
            win.explorer_drawing.setCurrentIndex(0)
        win.close()
        app.processEvents()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for p in files:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
