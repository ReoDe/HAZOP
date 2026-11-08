"""그래프 판 이전(U10) 측정 (QA용, 쓰지 않음). 근거: 기획서/지식그래프-스키마.md §8.2 '판 이전' 완료 기준 3.

작업 루트의 데이터/검토구간 저장본마다 지금 그래프(출력/그래프, 프로젝트 집합이면 프로젝트 그래프)와 비교해
판 이전 결과를 센다: 유지(확정 유지) · 재확인 · 같은 판 · 대상 아님(확정 전). ⑤ 결과가 함께 옮겨질 파일·항목 수도 센다.
--bump를 주면 모든 도면 그래프의 판을 바꾸고 entity_id를 모두 바꾼 사본(메모리)으로 비교한다(재추출 흉내).
'참조 채운 뒤'는 앱이 판이 바뀌기 전에 저장본을 한 번 읽어 member_refs를 채운 경우다(hazop.study.migrate.with_refs).
파일은 읽기만 한다. 끝에 데이터/ 아래 파일 바이트가 그대로인지 확인한다.
종료 코드 0 = 쓰기 없음 · 이전한 ⑤ 결과의 문장·상태 보존.

    python scripts/check_version_migration.py [--work-root DIR] [--bump]
"""

import argparse
import copy
import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.graph import project  # noqa: E402
from hazop.study import migrate  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402

CONTENT = ("entry_id", "origin", "status", "cause", "consequence", "safeguards", "recommendation",
           "severity", "frequency", "risk", "history")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sheet_graphs(root):
    """{graph_id: graph} 같은 graph_id면 가장 최근 것(project.load와 같은 규칙)."""
    best = {}
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        p = os.path.join(root, name, "graph.json")
        try:
            g = read(p)
        except (OSError, ValueError):
            continue
        key = (os.path.getmtime(p), p)
        if g.get("graph_id") and (g["graph_id"] not in best or key > best[g["graph_id"]][0]):
            best[g["graph_id"]] = (key, g)
    return {k: v[1] for k, v in best.items()}


def bumped(g):
    ren = (lambda x: "m-" + x)
    out = copy.deepcopy(g)
    out["graph_version"] += "-bump"
    for n in out["nodes"]:
        n["entity_id"] = ren(n["entity_id"])
        fd = n.get("flow_direction")
        if isinstance(fd, dict):
            fd.update({k: ren(fd[k]) for k in ("from", "to") if fd.get(k)})
    for e in out["edges"]:
        e.update(entity_id=ren(e["entity_id"]), nodes=[ren(x) for x in e["nodes"]])
        for k in ("segment", "node"):
            if e.get(k):
                e[k] = ren(e[k])
    return out


def graph_for(node_set, sheets):
    gid = node_set.get("graph_id") or ""
    if gid.startswith("project-"):
        pid = node_set.get("project_id") or project.UNREGISTERED_PROJECT
        mine = [g for g in sheets.values() if project.project_id_of(g) == pid]
        if not mine:
            return None
        return project.build(pid, mine, (project.load_manual(pid) or {}).get("ops") or ())
    return sheets.get(gid)


def digest(root):
    out = {}
    for d, _subs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def content(doc):
    return [{k: e.get(k) for k in CONTENT} for c in doc.get("cells") or [] for e in c.get("entries") or []]


def main():
    safe_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root")
    ap.add_argument("--bump", action="store_true")
    args = ap.parse_args()
    if args.work_root:
        os.environ[paths.ENV_WORK_ROOT] = args.work_root
    data_root = paths.work_path("데이터")
    before = digest(data_root)
    current = sheet_graphs(paths.output_root("그래프"))
    target = {k: bumped(g) for k, g in current.items()} if args.bump else current
    store = sn.store_dir()
    totals = {"stored": {}, "prepared": {}}
    results_moved = entries_moved = 0
    failures = []
    print("%-40s %-10s %-9s %-9s %s" % ("검토구간 저장본", "상태", "그대로", "참조 채운 뒤", "사유"))
    for folder in sorted(os.listdir(store)) if os.path.isdir(store) else []:
        for name in sorted(os.listdir(os.path.join(store, folder))):
            if not name.endswith(".json"):
                continue
            path = os.path.join(store, folder, name)
            try:
                ns = read(path)
            except (OSError, ValueError) as exc:
                print("%-40s 읽기 실패: %s" % (folder + "/" + name, exc))
                continue
            if not isinstance(ns, dict) or ns.get("kind") != sn.KIND:
                continue
            now_g, new_g = graph_for(ns, current), graph_for(ns, target)
            if new_g is None:
                print("%-40s %-10s 그래프 없음" % (folder + "/" + name, ns.get("status")))
                continue
            prepared = migrate.with_refs(ns, now_g)
            p0, p1 = migrate.plan(ns, new_g), migrate.plan(prepared, new_g)
            for key, p in (("stored", p0), ("prepared", p1)):
                totals[key][p["state"]] = totals[key].get(p["state"], 0) + 1
            print("%-40s %-10s %-9s %-9s %s" % (folder + "/" + name, ns.get("status"), p0["state"], p1["state"],
                                                p1["reason"] or ""))
            if p1["state"] != "kept":
                continue
            moved_set, _ = migrate.migrate_set(prepared, new_g)
            rpath = res._readable_path(ns.get("project_id"), ns["graph_id"])
            if not os.path.isfile(rpath):
                continue
            doc = read(rpath)
            moved, n = migrate.migrate_results(doc, moved_set)
            if n is None:
                print("    ⑤ 결과: 다른 확정본 기준이라 옮기지 않음(재확인)")
                continue
            results_moved += 1
            entries_moved += len(content(moved))
            if content(moved) != content(doc) or res.is_stale(moved, moved_set):
                failures.append("%s: 이전한 ⑤ 결과의 내용·판이 맞지 않음" % name)
            print("    ⑤ 결과: 항목 %d건 이전, kg_paths ID %d개 바꿈, 대응 못 한 P&ID ID %d개"
                  % (len(content(moved)), n, moved["version_migrations"][-1]["kg_path_ids_unmapped"]))
    label = {"kept": "유지", "recheck": "재확인", "same": "같은 판", "skip": "대상 아님"}
    for key, title in (("stored", "그대로"), ("prepared", "참조 채운 뒤")):
        print("%s: %s" % (title, " · ".join("%s %d" % (label[k], totals[key].get(k, 0)) for k in label)))
    print("⑤ 결과 이전: 파일 %d개 · 항목 %d건" % (results_moved, entries_moved))
    if digest(data_root) != before:
        failures.append("데이터/ 아래 파일이 바뀜(쓰지 않아야 함)")
    for f in failures:
        print("실패:", f)
    print("판정:", "통과" if not failures else "실패 %d건" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
