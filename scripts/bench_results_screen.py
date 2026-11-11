"""⑤ 결과 화면 전환 시간 측정(offscreen). 시험 자료(앱 작업 루트 사본)를 저장소 밖 임시 루트에 한 번 복사해 두고,
같은 방법으로 수정 전후를 비교한다. 실제 창을 띄우지 않으므로 화면 그리기(GPU·창 합성) 시간은 빠진다.

사용:
  python scripts/bench_results_screen.py --trial <저장소 밖 시험 폴더> [--runs 5]
      [--root <임시 작업 루트>] [--code <코드 저장소>] [--fresh] [--fill N] [--profile <out.prof>] [--json <out.json>]

- --code: 시험할 코드가 있는 저장소(기본은 이 스크립트의 저장소). 수정 전 코드는 `git archive`로 푼 사본을 준다.
- 시간: ①(index 0)에서 ⑤(index 6)로 win.go 한 번 + processEvents. 실행마다 ①로 돌아간 뒤 잰다.
- 일한 확인: ⑤ 행렬 행 수, 탐색기 구간 항목 수, 결과 칸 수를 함께 적는다. 0이면 측정이 무효다.
- --fill N: 이 시험 자료처럼 ⑤ 저장본이 없을 때, 모든 칸을 분석됨 + 제안 항목 N개로 채운 합성 결과를 임시 루트에 쓴다.
  채운 루트는 채우지 않은 루트와 섞지 않게 --root를 따로 준다.
- --profile을 주면 시간 측정과 따로 한 번 더 들어가며 cProfile을 남긴다(프로파일 실행 시간은 보고하지 않음).
"""

import argparse
import cProfile
import json
import os
import pstats
import shutil
import statistics
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_SCREEN = 6
START_SCREEN = 0

ap = argparse.ArgumentParser()
ap.add_argument("--trial", required=True, help="시험 폴더(안에 app/ 작업 루트 사본)")
ap.add_argument("--root", default=os.path.join(tempfile.gettempdir(), "hazop-bench-results"))
ap.add_argument("--code", default=REPO)
ap.add_argument("--runs", type=int, default=5)
ap.add_argument("--fresh", action="store_true", help="임시 루트를 지우고 다시 복사")
ap.add_argument("--fill", type=int, default=0, help="모든 칸을 분석됨 + 제안 항목 N개로 채운 합성 결과를 임시 루트에 씀")
ap.add_argument("--profile")
ap.add_argument("--json")
args = ap.parse_args()

MARKER = ".hazop-bench-root"  # 이 스크립트가 만든 임시 루트 표시. --fresh는 이 표시가 있는 폴더만 지운다


def outside_repo(path, what):
    """저장소 안이거나 저장소를 품은 경로면 끝낸다(지우기·덮어쓰기로 저장소를 건드리지 않게)."""
    path = os.path.abspath(path)
    a, b = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(REPO))  # Windows는 대소문자 무시
    if os.path.commonpath([a, b]) in (a, b):
        sys.exit("%s: 저장소 밖 경로만 쓸 수 있습니다(저장소를 품은 경로도 안 됨): %s" % (what, path))
    return path


src = os.path.join(os.path.abspath(args.trial), "app")
root = outside_repo(args.root, "임시 루트")
for out_path, what in ((args.json, "--json"), (args.profile, "--profile")):
    if out_path:
        outside_repo(out_path, what)
if args.fresh and os.path.isdir(root):
    if not os.path.isfile(os.path.join(root, MARKER)):
        sys.exit("이 스크립트가 만든 임시 루트가 아니라 지우지 않습니다(%s 없음): %s" % (MARKER, root))
    shutil.rmtree(root)
if not os.path.isdir(root):
    shutil.copytree(src, root)
    open(os.path.join(root, MARKER), "w").close()
os.environ.update(HAZOP_WORK_ROOT=os.path.join(root, "work"), HAZOP_STORE_ROOT=os.path.join(root, "store"),
                  QT_QPA_PLATFORM="offscreen", QT_QPA_FONTDIR=r"C:\Windows\Fonts")
os.environ.pop("HAZOP_RESOURCE_ROOT", None)
sys.path.insert(0, os.path.abspath(args.code))

from hazop import paths  # noqa: E402
from hazop.app import make_application  # noqa: E402
from hazop.app.main_window import MainWindow  # noqa: E402
from hazop.study import results as res  # noqa: E402

assert paths.work_root().startswith(root) and paths.store_root().startswith(root), "작업 루트가 임시 루트가 아님"


def fill(n_entries):
    """확정 구간 집합마다 모든 칸을 분석됨 + 제안 항목 n개로 채운 결과 파일을 임시 루트에 쓴다(이미 있으면 그대로)."""
    devs = res.load_deviations()
    folder = paths.folder("study-nodes")
    written = 0
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            if not f.endswith(".json"):
                continue
            with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                ns = json.load(fh)
            if not isinstance(ns, dict) or ns.get("status") != "confirmed" or not ns.get("nodes"):
                continue
            path = res.store_path(ns.get("project_id"), ns["graph_id"])
            if os.path.isfile(path):
                continue
            doc = res.empty_results(ns, devs)
            for c in doc["cells"]:
                c["state"] = "analyzed"
                c["ai_run"] = {"status": "ok", "error": None, "at": "2026-11-09T00:00:00Z", "model": "bench",
                               "note": None, "applicable": True}
                c["entries"] = [{"entry_id": "%s-%s-%d" % (c["node_id"], c["deviation_id"], i), "origin": "ai_draft",
                                 "status": "proposed", "cause": "원인", "consequence": "결과", "safeguards": ["보호"],
                                 "recommendation": "", "severity": 2, "frequency": 2, "risk": res.risk_of(2, 2),
                                 "history": []} for i in range(n_entries)]
            assert res.validate(doc, ns) == [], "합성 결과가 검사를 통과하지 못함"
            res.write(path, doc)
            written += 1
    return written


filled = fill(args.fill) if args.fill else 0

app = make_application(["bench"])
win = MainWindow(settings_path=os.path.join(root, "settings.json"), ask_reviewer=False)
win.resize(1366, 768)
win.show()
app.processEvents()


def enter():
    win.go(START_SCREEN)
    app.processEvents()
    t = time.perf_counter()
    win.go(RESULTS_SCREEN)
    app.processEvents()
    return time.perf_counter() - t


first = enter()
times = [enter() for _ in range(args.runs)]
scr = win.screens[RESULTS_SCREEN]
explorer_items = sum(len(g.items) for g in win._explorer_groups()) if hasattr(win, "_explorer_groups") else None
out = {
    "code": os.path.abspath(args.code), "root": root, "runs": args.runs, "fill_entries": args.fill,
    "filled_files": filled,
    "first_s": round(first, 3), "values_s": [round(x, 3) for x in times],
    "median_s": round(statistics.median(times), 3), "min_s": round(min(times), 3), "max_s": round(max(times), 3),
    "work": {"matrix_rows": scr.matrix.rowCount(), "deviations": len(scr.deviations),
             "cells": len((scr.results or {}).get("cells") or []), "explorer_items": explorer_items},
}
if not out["work"]["matrix_rows"] or not out["work"]["cells"] or not out["work"]["explorer_items"]:
    out["invalid"] = "⑤ 행렬·결과 칸·탐색기 구간 중 빈 것이 있어 측정이 무효"

if args.profile:
    win.go(START_SCREEN)
    app.processEvents()
    pr = cProfile.Profile()
    pr.enable()
    win.go(RESULTS_SCREEN)
    app.processEvents()
    pr.disable()
    pr.dump_stats(args.profile)
    st = pstats.Stats(pr)
    st.sort_stats("cumulative").print_stats(30)
    st.sort_stats("tottime").print_stats(15)

win.close()
text = json.dumps(out, ensure_ascii=False, indent=1)
if args.json:
    with open(args.json, "w", encoding="utf-8") as fh:
        fh.write(text)
print(text)
