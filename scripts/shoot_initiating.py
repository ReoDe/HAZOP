"""⑥ 초기사건 화면 스크린샷(P3 화면 검토용). 사용: python scripts/shoot_initiating.py <출력 폴더> [폭 높이]

임시 작업 루트에 샘플 도면 6장(출력/추출·출력/그래프)을 복사하고 프로젝트 검토구간을 확정한 뒤, 고정된 가상 ⑤ 결과
(승인 항목 7건)와 ⑥ 문서(규칙 초안 → 일부 사람 확인·확정, 공백 범주 판정 하나)를 저장하고 세 장면을 찍는다:
06-initiating-<폭>.png(확정한 그룹), 06-initiating-draft-<폭>.png(규칙 초안 그룹, 빗금),
06-initiating-coverage-<폭>.png(완전성 대조 탭, LOCHS 공백 행 선택).
모든 값은 가상이다. 네트워크·AI 호출 없음. 작업 루트는 끝나면 지운다.
"""

import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from hazop import paths  # noqa: E402
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # offscreen은 시스템 글꼴을 찾지 못해 한글이 깨짐

from scripts.shoot_results import SHEETS, prepare  # noqa: E402

AT = "2026-11-09T06:10:00Z"
REVIEWER = "검토자(예시)"
AUTO = "automatic"
# (원인, 원인 유형, 결과, [(보호수단, 작동 방식)], 판정, 범주, 판정 작성, 사유) — 가상 예시
SCENARIOS = (
    ("주급수펌프 FW-P01A 정지", "equipment", "SG 수위 저하, 2차측 열제거 상실",
     [("원자로 정지", AUTO), ("보조급수 자동 기동", AUTO)], "yes", "LOMFW", "human", ""),
    ("주급수 조절밸브 FCV-478 닫힘 방향 오동작", "equipment", "SG 수위 저하, 2차측 열제거 상실",
     [("원자로 정지", AUTO), ("보조급수 자동 기동", AUTO)], "yes", "LOMFW", "human", ""),
    ("급수 가열기 출구 차단밸브 오조작 닫힘", "human", "SG 수위 저하, 2차측 열제거 상실",
     [("원자로 정지", AUTO), ("보조급수 자동 기동", AUTO)], "yes", "LOMFW", "ai_draft", ""),
    ("가압기 PORV 열림 고착", "equipment", "가압기 증기공간으로 냉각재 유출 지속",
     [("고압안전주입", AUTO), ("운전원 PORV 차단밸브 닫힘", "operator")], "yes", "SORV", "human", ""),
    ("기기냉각수 펌프 전동기 정지", "support", "기기냉각수 계통 전체 냉각 상실",
     [("대기 펌프 자동 기동", AUTO)], "yes", "LOCCW", "human", ""),
    ("계기용 공기 헤더 압력 낮음", "support", "공기구동 밸브가 고장 위치로 이동",
     [("예비 공기압축기 기동", AUTO)], "undecided", "LOIA", "ai_draft", "응답 자료 없음"),
    ("가압기 살수밸브 조금 열림", "equipment", "가압기 압력 소폭 저하", [("압력 제어기 보상", AUTO)], "no", None,
     "human", "정상운전 범위 안에서 보상됨"),
)


def build_results():
    """확정 구간 앞쪽 칸에 승인 항목을 넣은 ⑤ 결과를 저장한다. 원인 위치는 프로젝트 그래프의 태그 있는 기기."""
    from hazop.graph import project
    from hazop.study import nodes, refs
    from hazop.study import results as res
    pg = project.load(project.UNREGISTERED_PROJECT)
    ns = nodes.load(pg)
    r = res.empty_results(ns, res.load_deviations())
    tagged = [ref for ref, n in sorted(refs.index(pg).items()) if n.get("tag")]
    for i, (cause, kind, cons, sgs, judge, cat, origin, reason) in enumerate(SCENARIOS):
        cell = r["cells"][i * 7]
        cell["state"] = "analyzed"
        cell["entries"].append({
            "entry_id": "E%02d" % (i + 1), "cause": cause, "cause_kind": kind, "consequence": cons,
            "consequence_basis": "unmitigated",
            "cause_refs": [{"ref": tagged[i * 3 % len(tagged)], "failure_mode": ("FTR", "FTC", "FTO", "FTC", "FTR",
                                                                                 "PLG", "SO")[i]}],
            "safeguards": [{"text": t, "role": "mitigative", "actuation": a, "refs": [], "ipl": None} for t, a in sgs],
            "recommendation": "", "severity": None, "frequency": None, "risk": None, "origin": "ai_draft",
            "status": "approved",
            "ie_hint": {"candidate": judge, "disturbs": "yes", "challenges": "yes" if judge == "yes" else "unknown",
                        "safety_functions": ["2차측 열제거"] if cat == "LOMFW" else [], "category": cat,
                        "reason": reason, "origin": origin, "status": "confirmed" if origin == "human" else "draft"}})
    assert not res.validate(r, ns)
    res.save(r, ns.get("project_id"))
    return pg, ns, r


def build_ie(pg, r):
    from hazop.ie import model, store
    doc = model.suggest(model.sync(model.empty(pg["project_id"]), r, at=AT), r, pg, at=AT)
    iec = model.iec_of(doc)
    key = lambda n: iec[model.key_of(r["graph_id"], "E%02d" % n)]  # noqa: E731
    lomfw = doc["candidates"][key(1)]["group_id"]
    doc = model.place(doc, key(3), None, at=AT)  # AI 초안 판정은 확정 그룹에 둘 수 없어 사람이 뺐다
    for m in model.members_of(doc, lomfw):
        doc = model.accept(doc, ("member", m), at=AT)
    for kind, field in (("heading", "heading_ids"), ("end_state", "end_state_ids")):
        for rid in doc["groups"][lomfw][field]:
            doc = model.accept(doc, (kind, rid), at=AT)
    doc = model.edit(doc, ("group", lomfw), {
        "name": "주급수 상실", "definition": "주급수 유량이 끊겨 SG 2차측 열제거가 줄고 원자로가 정지하는 사건(가상 예시)",
        "representative_reason": "응답이 가장 빠름", "plant_response": "원자로 자동 정지, 터빈 정지, 보조급수 자동 기동 요구",
        "affected_mitigation": "보조급수, 가압기 압력 방출", "support_ie": "no"}, at=AT)
    doc = model.accept(doc, ("group", lomfw), at=AT)
    doc = model.edit(doc, ("end_state", doc["groups"][lomfw]["end_state_ids"][0]),
                     {"category": "core_damage_possible"}, at=AT)
    doc = model.confirm(doc, lomfw, r, REVIEWER, at=AT)
    doc = model.set_coverage(doc, "LOCHS", "out_of_scope", "복수기 도면 미등록 — 이번 HAZOP 범위 밖(가상)", REVIEWER, at=AT)
    store.save(doc, expect=store.fingerprint(store.store_path(pg["project_id"])))
    return lomfw, doc["candidates"][key(4)]["group_id"]


def main():
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else paths.output_in(paths.DEV_WORK_ROOT, "스크린샷", "초기사건"))
    w, h = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1366, 768)
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hazop-shoot-ie-")
    os.environ["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    os.environ["HAZOP_STORE_ROOT"] = os.path.join(tmp, "store")
    files = []
    try:
        prepare(os.environ["HAZOP_WORK_ROOT"])
        pg, _ns, r = build_results()
        lomfw, draft = build_ie(pg, r)
        from hazop.app import make_application
        from hazop.app.main_window import MainWindow
        from hazop.app.screenshots import settle
        app = make_application(["shoot"])
        win = MainWindow(settings_path=os.path.join(tmp, "settings.json"), ask_reviewer=False)
        win.set_reviewer_name(REVIEWER)
        win.set_drawing(SHEETS[1])
        win.show()
        win.showNormal()
        win.resize(w, h)
        win.go(7)
        scr = win.screens[7]
        scr.open_item(("group", lomfw))
        scr.member_table.selectRow(0)
        settle(0.8)
        lochs = [x["code"] for x in scr.view["completeness"]].index("LOCHS")
        for name, prep in (("06-initiating-%d.png" % w, lambda: None),
                           ("06-initiating-draft-%d.png" % w, lambda: scr.open_item(("group", draft))),
                           ("06-initiating-coverage-%d.png" % w, lambda: (
                               scr.open_item(("tab", 5)),
                               scr.coverage_table.selectRow(lochs)))):
            prep()
            settle(0.6)
            p = os.path.join(out_dir, name)
            win.grab().save(p)
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
