"""UI/UX 디테일 개선(디자인/시안/UIUX-디테일/개선명세.md) 화면 스크린샷과 측정. 사용: python scripts/shoot_uiux.py <출력 폴더>

임시 작업 루트에 샘플 도면 SNP-M-102(출력/추출·그래프·지식그래프 사본)를 두고 검토구간을 확정한 뒤, 가짜 클라이언트로
⑤ AI 분석을 채운다(네트워크 없음, scripts/shoot_results.py와 같은 준비). 창 크기 1366×768·1920×1080마다
① 등록(빈 상태) ② 추출 ③ 지식그래프 ④ 검토구간 ⑤ 결과 · 명령 팔레트 · ④+⑤ 분할을 찍고, 명세 측정값을 measure.json에 쓴다.
"""

import json
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
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # offscreen은 시스템 글꼴을 찾지 못해 한글이 깨짐

SIZES = ((1366, 768), (1920, 1080))


def visible_columns(table):
    """표 viewport에 보이는 열 수(잘린 열은 보이는 비율만큼)."""
    vw, shown = table.viewport().width(), 0.0
    for c in range(table.columnCount()):
        x, w = table.columnViewportPosition(c), table.columnWidth(c)
        if x >= vw or x + w <= 0:
            continue
        shown += (min(x + w, vw) - max(x, 0)) / float(w)
    return round(shown, 1)


def visible_rows(view):
    """목록·표에서 끝까지 보이는 행 수."""
    vp = view.viewport().rect()
    n = view.count() if hasattr(view, "count") else view.rowCount()
    item = view.item if hasattr(view, "count") else (lambda r: view.item(r, 0))
    return sum(1 for r in range(n) if item(r) is not None and vp.contains(view.visualItemRect(item(r))))


def js(win, code, timeout=10.0):
    from hazop.app.screenshots import wait
    out = []
    win.webview.page().runJavaScript(code, 0, out.append)
    wait(lambda: out, timeout)
    return out[0] if out else None


def main():
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(paths.DEV_WORK_ROOT, "출력", "스크린샷", "uiux"))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shoot-uiux-")
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    files, measure = [], {}
    try:
        import shoot_results
        shoot_results.prepare(os.environ["HAZOP_WORK_ROOT"])
        shutil.copytree(paths.folder("참고"), paths.logical_reference_dir(os.environ["HAZOP_WORK_ROOT"]))
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
        win.go(6)
        res = win.screens[6]
        res.make_client = lambda: shoot_results.FakeClient()
        res.run_ai("all")
        if not wait(lambda: not res.running(), 180):
            raise SystemExit("AI 분석(가짜)이 끝나지 않음")

        def shot(name, w, h, popup=None):
            wait(lambda: win.webview.isHidden() or win.webview.current_file is None or win.webview.bridge.is_ready, 20)
            settle(1.0)
            if shoot_results.KEY[:12] in shoot_results.screen_text(win):
                raise SystemExit("화면 글자에 API 키가 보임")
            p = os.path.join(out_dir, "%s-%dx%d.png" % (name, w, h))
            img = win.grab()
            if popup is not None:  # 팔레트는 따로 뜨는 창이라 창 그림 위에 제자리로 겹쳐 그린다
                from PySide6.QtGui import QPainter
                painter = QPainter(img)
                painter.drawPixmap(win.mapFromGlobal(popup.mapToGlobal(popup.rect().topLeft())), popup.grab())
                painter.end()
            img.save(p)
            files.append(p)

        for w, h in SIZES:
            win.showNormal()
            win.resize(w, h)
            settle(0.5)
            m = measure.setdefault("%dx%d" % (w, h), {})
            win.go(0)
            shot("1-register", w, h)
            win.go(1)
            shot("2-viewer", w, h)
            m["tags_at_fit"] = json.loads(js(win, "JSON.stringify(window.hzTags ? hzTags.state() : null)") or "null")
            m["tag_label_px"] = js(win, "(function(){var s=document.querySelector('#taglabels span');return s?parseFloat(getComputedStyle(s).fontSize):null})()")
            m["tag_min_px"] = js(win, "window.hzTags ? hzTags.MIN_PX : null")
            win.go(4)
            settle(2.0)
            shot("3-knowledge", w, h)
            win.go(5)
            study = win.screens[5]
            shot("4-study", w, h)
            m["study_segments_visible"] = "%d/%d" % (visible_rows(study.node_list), study.node_list.count())
            win.go(6)
            first = res.node_set["nodes"][0]["node_id"]
            res.open_cell(first, res.deviations[0]["deviation_id"])
            res.select_entry(0)
            shot("5-results", w, h)
            m["results_deviation_columns_visible"] = visible_columns(res.matrix)
            m["results_row_height"] = res.matrix.rowHeight(0)
            m["center_width"] = win.center.width()
            dlg = win.open_palette("RC")
            settle(0.4)
            shot("6-palette", w, h, popup=dlg)
            m["palette_hits_RC"] = len(dlg.results())
            dlg.close()
            win.go(5)
            m["split_study_results"] = bool(win.toggle_split(6)) or win.msg_label.text()
            shot("7-split-study-results", w, h)
            win.unsplit()
        win.close()
        app.processEvents()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with open(os.path.join(out_dir, "measure.json"), "w", encoding="utf-8") as fh:
        json.dump(measure, fh, ensure_ascii=False, indent=2)
    print(json.dumps(measure, ensure_ascii=False, indent=2))
    for p in files:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
