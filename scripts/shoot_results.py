"""⑤ 분석 결과 화면 스크린샷 (4단계 화면 검토용). 사용: python scripts/shoot_results.py <출력 폴더>

임시 작업 루트에 출력/추출·출력/그래프의 샘플 도면 SNP-M-102와 출력/지식그래프를 복사하고 검토구간을 확정한 뒤,
창 크기 1366×768·1920×1080마다 세 상태를 찍는다: before(분석 전), running(실행 중, 진행 막대가 중간),
after(결과와 근거 경고가 있는 칸의 워크시트). 파일 이름 05-results-<폭>-<상태>.png.
가짜 클라이언트만 쓴다(네트워크 없음). 화면에 API 키를 보이지 않는다(키 문자열이 화면 글자에 없는지 확인).
"""

import json
import os
import shutil
import sys
import tempfile
import threading

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # offscreen은 시스템 글꼴을 찾지 못해 한글이 깨짐

DRAWING = "SNP-M-102"
SIZES = ((1366, 768), (1920, 1080))
KEY = "sk-ant-api03-SCREENSHOT-ONLY-not-a-real-key"
BLOCK_AT = 13  # 이 번째 호출에서 멈춰 진행 막대가 중간에 있는 화면을 찍는다
SCENARIOS = {
    "high": ("가압기 압력 제어 실패로 살수 밸브가 열린 채 고착", "가압기 압력 급감, 원자로 냉각재 압력 저하", 3, 2),
    "deny": ("방출 밸브 오동작 개방", "냉각재 방출 탱크 과압 가능성", 4, 2),
    "ok": ("계측 신호 지연", "운전원 대응 지연(영향 제한적)", 2, 1),
}


class FakeClient:
    """구간 구성요소 태그를 써서 그럴듯한 초안을 만든다. 도면에 없는 태그 하나를 넣어 근거 경고가 보이게 한다.
    gate가 있으면 BLOCK_AT번째 호출에서 gate.set()까지 기다린다."""

    def __init__(self, gate=None):
        self.gate, self.calls, self.waiting = gate, 0, threading.Event()

    def analyze(self, request):
        self.calls += 1
        if self.gate is not None and self.calls == BLOCK_AT:
            self.waiting.set()
            self.gate.wait()
        ctx = json.loads(request["context"].split("\n", 1)[1])
        tags = [c["tag"] for c in ctx["components"] if c.get("tag")] or ["-"]
        asked = json.loads(request["user"].split("\n", 1)[1])
        out = []
        for i, d in enumerate(asked):
            if d["parameter"] == "반응":
                out.append({"deviation_id": d["deviation_id"], "applicable": False,
                            "note": "이 구간에는 화학 반응이 없음", "scenarios": []})
                continue
            cause, cons, sev, freq = SCENARIOS[("high", "deny", "ok")[i % 3]]
            out.append({"deviation_id": d["deviation_id"], "applicable": True, "note": "설정치 자료 확인 필요",
                        "scenarios": [{"cause": "%s(%s)" % (cause, tags[0]), "consequence": cons,
                                       "safeguards": ["%s 경보" % tags[-1]], "recommendation": "제어 논리 설정치 확인",
                                       "severity": sev, "frequency": freq,
                                       "equipment_tags": [tags[0], "PZR-HTR-99"],
                                       "kg_paths": [[c["entity_id"] for c in ctx["components"][:2]]],
                                       "sources": []}]})
        if asked[0]["parameter"] == "온도" and len(asked) > 1:
            return {"status": "api_error", "output": None, "usage": None, "model": "claude-opus-5-5",
                    "error_type": "overloaded", "status_code": 529, "error": "AI 서비스가 과부하 상태임(HTTP 529, 잠시 뒤 재시도)"}
        return {"status": "completed", "output": {"deviations": out}, "model": "claude-opus-5-5",
                "usage": {"input_tokens": 5200, "output_tokens": 1400, "cache_read_input_tokens": 4100,
                          "cache_creation_input_tokens": 0},
                "error_type": None, "status_code": 200, "error": None}


SHEETS = ("SNP-M-101", "SNP-M-102", "SNP-M-201", "SNP-M-301", "SNP-M-401", "SNP-M-501")  # 도면 연결로 이어진 샘플 프로젝트


def prepare(tmp):
    """샘플 6장(추출·그래프)과 지식그래프를 복사하고 프로젝트 전체 검토구간(S1…Sn)을 확정해 둔다."""
    for sub in [("추출", d) for d in SHEETS] + [("그래프", d) for d in SHEETS] + [("지식그래프",)]:
        shutil.copytree(os.path.join(REPO_ROOT, "출력", *sub), os.path.join(tmp, "출력", *sub))
    from hazop.graph import project
    from hazop.study import nodes
    pg = project.load(project.UNREGISTERED_PROJECT)
    nodes.save(nodes.confirm(nodes.propose(pg), pg, "검토자(예시)"))


def drawing_node_ids(drawing=DRAWING):
    """DRAWING을 지나는 프로젝트 구간 ID(가짜 AI를 이 구간에만 돌려 준비 시간을 줄인다)."""
    from hazop.graph import project
    from hazop.study import nodes, span
    pg = project.load(project.UNREGISTERED_PROJECT)
    return [n["node_id"] for n in span.nodes_on_drawing(span.annotate(nodes.load(pg), pg), drawing)]


def screen_text(widget):
    from PySide6.QtWidgets import QAbstractButton, QLabel, QTableWidget
    out = [w.text() for w in widget.findChildren(QLabel) + widget.findChildren(QAbstractButton)]
    for t in widget.findChildren(QTableWidget):
        out += [t.item(r, c).text() for r in range(t.rowCount()) for c in range(t.columnCount()) if t.item(r, c)]
    return "\n".join(out)


def shoot(win, scr, out_dir, w, state, files):
    from hazop.app.screenshots import settle
    settle(0.6)
    if KEY in screen_text(win) or KEY[:12] in screen_text(win):
        raise SystemExit("화면 글자에 API 키가 보임")
    p = os.path.join(out_dir, "05-results-%d-%s.png" % (w, state))
    win.grab().save(p)
    files.append(p)


def main():
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO_ROOT, "출력", "스크린샷", "stage4"))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shoot-results-")
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    files = []
    try:
        prepare(os.environ["HAZOP_WORK_ROOT"])
        from hazop import paths
        from hazop.app import make_application
        from hazop.app.main_window import MainWindow
        from hazop.app.screenshots import wait
        from PySide6.QtWidgets import QAbstractItemView
        app = make_application(["shoot"])
        win = MainWindow(settings_path=os.path.join(tmp, "settings.json"), ask_reviewer=False)
        win.set_reviewer_name("검토자(예시)")
        win.api_keys.set(KEY, persist=False)
        win.show()
        for w, h in SIZES:
            shutil.rmtree(paths.work_path("데이터", "분석결과"), ignore_errors=True)
            win.showNormal()
            win.resize(w, h)
            win.go(6)
            scr = win.screens[6]
            first = scr.node_set["nodes"][0]["node_id"]
            scr.open_cell(first, scr.deviations[0]["deviation_id"])
            shoot(win, scr, out_dir, w, "before", files)

            gate = threading.Event()
            client = FakeClient(gate)
            scr.make_client = lambda c=client: c
            scr.run_ai("all")
            if not wait(client.waiting.is_set, 60):
                raise SystemExit("실행이 중간 지점에 닿지 않음")
            wait(lambda: scr.progress.value() == BLOCK_AT - 1, 10)
            shoot(win, scr, out_dir, w, "running", files)
            gate.set()
            if not wait(lambda: not scr.running(), 120):
                raise SystemExit("실행이 끝나지 않음")
            scr.open_cell(first, scr.deviations[0]["deviation_id"])
            failed_col = next(i for i, d in enumerate(scr.deviations) if d["parameter"] == "온도")
            scr.matrix.scrollToItem(scr.matrix.item(0, failed_col), QAbstractItemView.PositionAtCenter)
            shoot(win, scr, out_dir, w, "after", files)
        win.close()
        app.processEvents()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for p in files:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
