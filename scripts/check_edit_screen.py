"""② 도면 편집 화면 검사·스크린샷 (drawing-edit-spec.md '화면'). 네트워크·AI 호출 없음.

임시 작업 루트(HAZOP_WORK_ROOT·HAZOP_STORE_ROOT·설정 모두 임시)에 샘플 도면 SNP-M-101을 추출·그래프로 만들고 주 창을
화면에 띄우지 않고(WA_DontShowOnScreen) ②에서 편집 모드를 켠다. 미확인이 있는 배관을 골라 흐름 방향을 뒤집고
경로를 다시 그린 뒤 확인한다.
1) 웹 도면에 사람 수정 표시(.edited)가 있고, 다시 그린 경로는 폴리라인(사람이 그린 경로)으로 그려진다.
2) 다시 읽은 뒤에도 확대·위치가 유지된다.
3) 1366×768에서 편집 패널이 창 안에 다 들어오고 패널 내용이 가로로 잘리지 않으며 도면 캔버스 폭이 남는다.
스크린샷: 출력/스크린샷/02-edit-1366.png, 02-edit-1920.png (--out으로 폴더 변경). Windows에서는 실제 글꼴로 재도록
기본 플랫폼이 windows(창은 화면에 띄우지 않음)다. 종료 코드 0 = 전부 통과, 1 = 실패.
"""

import argparse
import glob
import json
import os
import shutil
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

DRAWING = "SNP-M-101"
SIZES = ((1366, 768), (1920, 1080))
MIN_CANVAS_W = 600  # 1366 폭에서 편집 패널을 연 뒤에도 남아야 할 도면 캔버스 폭


def install_sample(work, drawing=DRAWING):
    """샘플 도면을 작업 루트 안으로 복사해 추출·그래프를 만든다(뷰어 SVG는 작업·저장 루트 안만 허용). 추출 폴더 이름."""
    from hazop.app import data
    src = [p for p in glob.glob(os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*")) if drawing in p][0]
    dst = os.path.join(work, "샘플", os.path.basename(src))
    if not os.path.isdir(dst):
        shutil.copytree(src, dst)
    _, out_dir = data.script_module("extract_drawio").run_one(glob.glob(os.path.join(dst, "*.drawio"))[0],
                                                              os.path.join(work, "출력", "추출"))
    data.script_module("build_graph").build_one(os.path.join(out_dir, "extraction.json"), os.path.join(work, "출력", "그래프"))
    return os.path.basename(out_dir)


def wait(cond, timeout=20.0):
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return bool(cond())


def js(win, expr):
    out = []
    win.webview.page().runJavaScript(expr, 0, out.append)
    wait(lambda: out, 10)
    return out[0] if out else None


def ready(win):
    ok = wait(lambda: win.webview.bridge.is_ready)
    wait(lambda: False, 0.6)
    return ok


def run(out_dir):
    from PySide6.QtCore import Qt
    from hazop.app import make_application
    from hazop.app.main_window import MainWindow
    make_application(["check_edit_screen"])
    bad = []
    tmp = tempfile.mkdtemp(prefix="hazop-edit-screen-")
    old = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    win = None
    try:
        name = install_sample(os.environ["HAZOP_WORK_ROOT"])
        win = MainWindow(settings_path=os.path.join(tmp, "settings.json"), ask_reviewer=False)
        win.set_reviewer_name("검토자(검사)")
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        win.resize(*SIZES[0])
        win.go(1)
        scr = win.screens[1]
        scr.select_drawing(name)
        scr.edit_btn.setChecked(True)
        if not ready(win):
            return ["웹뷰 준비 안 됨"]
        flows = [u["target"] for u in scr.info["corrected"]["validation"]["unknowns"]
                 if u.get("check") == "unknown_flow_direction" and u.get("target") in scr.items]
        rel = next((t for t in flows if all(ep.get("node_local_id") for ep in scr.items[t][1]["endpoints"])), None)
        if rel is None:
            return ["양 끝이 기기인 흐름 방향 미확인 배관이 샘플에 없음"]
        scr.on_node({"local_id": rel, "entity_id": None})
        scr.flow_flip.click()
        ready(win)
        js(win, "window.hzView.set({s: 0.9, x: -40, y: -30})")
        scr.set_tool("path")
        pts = [ep["point"] for ep in scr.items[rel][1]["endpoints"]]
        mid = [(pts[0][0] + pts[1][0]) / 2 + 30, (pts[0][1] + pts[1][1]) / 2 + 30]
        for p in (pts[0], mid, pts[1]):
            win.webview.bridge.fromWeb(json.dumps({"type": "editPick", "point": p, "local_id": None,
                                                   "view": {"s": 0.9, "x": -40, "y": -30}}))
        scr.path_done.click()
        ready(win)
        ops = [o["op"] for o in scr.session.ops]
        if ops != ["set_flow", "set_path"]:
            bad.append("수정 기록이 예상과 다름: %s" % ops)
        status = [scr.op_list.item(i).text() for i in range(scr.op_list.count())]
        if not all("적용" in t and "적용 불가" not in t for t in status):
            bad.append("적용되지 않은 수정: %s" % status)
        state = json.loads(js(win, "JSON.stringify({edited: document.querySelectorAll('#overlay .edited').length,"
                                   " line: (function(){var e=document.querySelector('#overlay .pipe-hit[data-local-id=\"%s\"]');"
                                   " return e ? e.tagName : null;})(), view: window.hzView.get()})" % rel) or "{}")
        print("웹 상태: %s" % state)
        if not state.get("edited"):
            bad.append("사람 수정 표시(.edited) 없음")
        if state.get("line") != "polyline":
            bad.append("다시 그린 경로가 폴리라인이 아님: %s" % state.get("line"))
        if (state.get("view") or {}).get("s") != 0.9:
            bad.append("다시 읽은 뒤 확대 유지 안 됨: %s" % state.get("view"))
        scr.on_node({"local_id": rel, "entity_id": None})
        os.makedirs(out_dir, exist_ok=True)
        for w, h in SIZES:
            win.resize(w, h)
            wait(lambda: False, 0.8)
            js(win, "window.hzView.set({s: 0.9, x: -40, y: -30})")
            wait(lambda: False, 0.4)
            path = os.path.join(out_dir, "02-edit-%d.png" % w)
            win.grab().save(path)
            print("스크린샷: %s" % os.path.abspath(path))
            panel, box = scr.edit_panel, scr.edit_panel.widget()
            right = panel.mapTo(win, panel.rect().topRight()).x()
            canvas = scr.stack.width()
            print("%d×%d: 편집 패널 오른쪽 끝 %d / 창 %d, 패널 내용 최소 폭 %d / 보이는 폭 %d, 캔버스 폭 %d"
                  % (w, h, right, win.width(), box.minimumSizeHint().width(), panel.viewport().width(), canvas))
            if w == SIZES[0][0]:
                if not panel.isVisible() or right > win.width():
                    bad.append("1366: 편집 패널이 창 밖으로 잘림")
                if box.minimumSizeHint().width() > panel.viewport().width():
                    bad.append("1366: 편집 패널 내용이 가로로 잘림")
                if canvas < MIN_CANVAS_W:
                    bad.append("1366: 도면 캔버스 폭 %d < %d" % (canvas, MIN_CANVAS_W))
        scr.session.mark_saved()
    finally:
        if win is not None:
            win.webview.dispose()
            win.close()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def main():
    from hazop.console import safe_console
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "출력", "스크린샷"), help="스크린샷 폴더")
    ap.add_argument("--platform", default="windows" if sys.platform == "win32" else "offscreen",
                    help="Qt 플랫폼. offscreen은 한글 글꼴이 없어 폭 측정·스크린샷이 실제와 다르다")
    args = ap.parse_args()
    os.environ["QT_QPA_PLATFORM"] = args.platform
    bad = run(args.out)
    for b in bad:
        print("실패: %s" % b)
    print("② 편집 화면 검사: %s" % ("통과" if not bad else "실패 %d건" % len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
