"""M5 화면 스크린샷: ⑤ 결과 참조(원인 위치·영향 대상·보호수단 역할·구현 대상)와 ③ 검토 층. 1366×768·1920×1080.
사용: python scripts/shoot_study_refs.py <출력 폴더>

임시 작업 루트에 샘플 6장과 지식그래프를 두고(scripts/shoot_results.prepare) SNP-M-102를 지나는 첫 구간만 가짜 AI로
채운다(참조 필드가 든 고정 응답, 네트워크 없음). 한 항목은 사람이 역할·구현 대상을 고쳐 '수정'으로 둔다.
- 05-refs-<폭>-sheet: 워크시트(원인 위치·영향 대상·보호수단 역할·구현 대상, AI 초안 표시)
- 05-refs-<폭>-dialog: 수정 창(역할·구현 대상 표, 원인 위치·영향 대상·관련 잠재 후보 고르기)
- 3-study-<폭>: ③ 검토 층을 켜고 시나리오를 고른 화면(읽기 전용 상세)
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
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

SIZES = ((1366, 768), (1920, 1080))
KEY = "sk-ant-api03-SCREENSHOT-ONLY-not-a-real-key"


class RefClient:
    """구간 구성요소의 entity_id로 원인 위치·영향 대상·보호수단 구현 대상을 채운 초안. 그래프에 없는 ID 하나를 넣어
    '뺌' 경고가 보이게 한다."""

    def analyze(self, request):
        ctx = json.loads(request["context"].split("\n", 1)[1])
        comps = [c for c in ctx["components"] if c.get("tag") and c.get("drawing")
                 and c.get("category") not in ("pipe_segment", "piping_element")] or ctx["components"]
        a, b = comps[0], comps[-1]
        out = []
        for d in json.loads(request["user"].split("\n", 1)[1]):
            out.append({"deviation_id": d["deviation_id"], "applicable": True, "note": "",
                        "scenarios": [{"cause": "%s 오동작" % a.get("tag"), "consequence": "%s 압력 상승" % b.get("tag"),
                                       "recommendation": "설정치 자료 확인", "severity": 3, "frequency": 2,
                                       "cause_refs": [{"entity_id": a["entity_id"], "failure_mode": "닫힘 고착"},
                                                      {"entity_id": "entity-node-999", "failure_mode": ""}],
                                       "consequence_refs": [{"entity_id": b["entity_id"]}],
                                       "safeguards": [{"text": "%s 경보" % b.get("tag"), "role": "mitigative",
                                                       "entity_ids": [b["entity_id"]]},
                                                      {"text": "운전원 순시", "role": "unknown", "entity_ids": []}],
                                       "equipment_tags": [a.get("tag")], "kg_paths": [], "sources": []}]})
        return {"status": "completed", "output": {"deviations": out}, "model": "claude-opus-5-5",
                "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0,
                          "cache_creation_input_tokens": 0}, "error_type": None, "status_code": 200, "error": None}


def main():
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else paths.output_in(paths.DEV_WORK_ROOT, "screenshots", "m5"))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shoot-m5-")
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    files = []
    try:
        import shoot_results
        shoot_results.prepare(os.environ["HAZOP_WORK_ROOT"])
        from hazop.app import make_application
        from hazop.app.main_window import MainWindow
        from hazop.app.screens.results import EntryDialog
        from hazop.app.screenshots import settle, wait
        from hazop.kg import screen as kg_screen
        app = make_application(["shoot"])
        win = MainWindow(settings_path=os.path.join(tmp, "settings.json"), ask_reviewer=False)
        win.set_reviewer_name("검토자(예시)")
        win.api_keys.set(KEY, persist=False)
        win.ai_prefs.choose("api")  # 가짜 API 클라이언트로 돌린다
        win.show()
        node_id = shoot_results.drawing_node_ids()[0]

        def save(widget, name):
            settle(0.8)
            p = os.path.join(out_dir, name)
            widget.grab().save(p)
            files.append(p)

        for i, (w, h) in enumerate(SIZES):
            win.showNormal()
            win.resize(w, h)
            win.set_drawing("SNP-M-102")
            win.go(6)
            scr = win.screens[6]
            if i == 0:
                scr.make_client = lambda: RefClient()
                scr.matrix.setCurrentCell(scr._row_of(node_id), 0)
                if not scr.run_ai("node"):
                    raise SystemExit("가짜 AI 실행을 시작하지 못함")
                if not wait(lambda: not scr.running(), 120):
                    raise SystemExit("가짜 AI 실행이 끝나지 않음")
                scr.open_cell(node_id, scr.deviations[1]["deviation_id"])
                scr.select_entry(0)
                e = scr.selected_entry()
                if e is None:
                    raise SystemExit("항목 없음: %s" % (scr._cell_doc(),))
                sg = e["safeguards"][1]
                scr.edit_selected({"safeguards": [e["safeguards"][0], dict(sg, role="preventive", origin="human")]})
            scr.open_cell(node_id, scr.deviations[1]["deviation_id"])
            scr.select_entry(0)
            save(win, "05-refs-%d-sheet.png" % w)
            dlg = EntryDialog(scr.selected_entry(), scr, scr.ref_context(node_id))
            dlg.show()
            save(dlg, "05-refs-%d-dialog.png" % w)
            dlg.close()
            dlg.deleteLater()

            win.go(4)
            kgs = win.screens[4]
            settle(1.0)
            wait(lambda: win.webview.bridge.is_ready, 20)
            win.webview.page().runJavaScript(
                "var el = document.getElementById('ly-st'); el.checked = true; el.onchange(); "
                "document.getElementById('sec-st').scrollIntoView()")
            scen = next((n for n in kgs.data["nodes"] if n["layer"] == kg_screen.STUDY_LAYER and n["type"] == "scenario"),
                        None)
            if scen is None:
                raise SystemExit("③에 검토 층 시나리오가 없음: %s" % (kgs.data["meta"].get("study"),))
            win.webview.bridge.send("selectNode", id=scen["id"])
            kgs.render_node(scen["id"])
            settle(2.5)
            save(win, "3-study-%d.png" % w)
        win.close()
        app.processEvents()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for p in files:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
