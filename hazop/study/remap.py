"""확정 해제 → 다시 제안·편집 → 다시 확정할 때 옛 구간과 ⑤ 결과를 새 구간에 잇는다. 근거: 기획서/검토구간-분할설계.md §4.6.

nodes.reopen이 확정본의 구간 구성요소를 node_set["previous"](최근 것이 뒤, 최대 KEEP개)에 남기고, 편집·다시 제안이
그것을 물려준다. 결과를 이을 때는 결과의 확정 열쇠(study_nodes_ref.confirmed_at)와 같은 기록을 쓴다(여러 번 확정
해제해도 결과를 만든 확정본을 찾는다). 옛 구간마다 가장 많이 겹치는 새 구간이 대표다(결정적).
- 같음: 새 구간 구성요소가 옛 구간 하나와 똑같고, 그 사이 그래프 내용이 바뀌지 않았음. 칸 상태·항목을 그대로 옮긴다.
- 그 밖에 겹침: 항목은 옮기되 scope_changed를 붙이고 칸 상태는 물려받지 않는다.
- 제외로 감: 대표 새 구간이 '스크리닝 제외'. 사람 판정 항목이 있으면 옮기지 않고 멈춘다(행 없는 구간에 숨지 않게).
- 대응 없음: 옛 구간이 새 집합과 겹치지 않음. 항목이나 손댄 칸이 있으면 멈춘다(말없이 버리지 않게).
"""

import copy

KINDS = ("same", "merged", "split", "changed", "new", "excluded")
KEEP = 5


def snapshot(node_set, confirmed_at):
    """확정본의 구간 기록. study_nodes_ref는 그 확정본으로 만든 결과의 열쇠다."""
    return {"study_nodes_ref": {"graph_version": node_set.get("graph_version"), "confirmed_at": confirmed_at},
            "nodes": [{"node_id": n["node_id"], "members": list(n["members"])} for n in node_set["nodes"]]}


def remember(node_set, confirmed_at):
    """node_set의 previous 목록에 이번 확정본을 덧붙인 목록(같은 확정은 한 번만)."""
    olds = [p for p in node_set.get("previous") or []
            if (p.get("study_nodes_ref") or {}).get("confirmed_at") != confirmed_at]
    return (olds + [snapshot(node_set, confirmed_at)])[-KEEP:]


def latest(node_set):
    prev = node_set.get("previous") or []
    return prev[-1] if prev else None


def _excluded(node):
    return (node.get("screen") or {}).get("status") == "excluded"


def _num(node_id):
    return int(node_id[1:]) if node_id[1:].isdigit() else 10 ** 9


def node_map(previous, node_set, content_same=True):
    """(옛 → 새 {old_id: {node_id, exact, to_excluded}}, 새 구간 줄 {new_id: {kind, old_ids}}).
    content_same이 False면(그 사이 그래프 내용이 바뀜) 구성요소가 같아도 같음으로 보지 않는다."""
    new_nodes = {n["node_id"]: n for n in node_set["nodes"]}
    owner = {m: n["node_id"] for n in node_set["nodes"] for m in n["members"]}
    old_to_new = {}
    for o in previous["nodes"]:
        hits = {}
        for m in o["members"]:
            if m in owner:
                hits[owner[m]] = hits.get(owner[m], 0) + 1
        best = sorted(hits, key=lambda nid: (-hits[nid], _num(nid), nid))[0] if hits else None
        exact = (content_same and best is not None and len(hits) == 1
                 and set(new_nodes[best]["members"]) == set(o["members"]))
        old_to_new[o["node_id"]] = {"node_id": best, "exact": exact,
                                    "to_excluded": best is not None and _excluded(new_nodes[best])}
    old_members = {o["node_id"]: set(o["members"]) for o in previous["nodes"]}
    rows = {}
    for nid, n in new_nodes.items():
        olds = sorted((k for k, v in old_to_new.items() if v["node_id"] == nid), key=_num)
        if _excluded(n) and olds:
            kind = "excluded"
        elif not olds:
            kind = "new"
        elif len(olds) == 1 and old_to_new[olds[0]]["exact"]:
            kind = "same"
        elif len(olds) > 1:
            kind = "merged"
        elif not old_members[olds[0]] <= set(n["members"]):
            kind = "split"
        else:
            kind = "changed"
        rows[nid] = {"kind": kind, "old_ids": olds}
    return old_to_new, rows


def summary(rows):
    """{kind: 새 구간 수}. 화면의 대응표 머리글용."""
    out = {k: 0 for k in KINDS}
    for r in rows.values():
        out[r["kind"]] += 1
    return out


def _matching(node_set, old_results):
    ref = old_results.get("study_nodes_ref") or {}
    return next((p for p in reversed(node_set.get("previous") or [])
                 if (p.get("study_nodes_ref") or {}).get("confirmed_at") == ref.get("confirmed_at")), None)


def _in_snapshot_version(old_results, snap, node_set):
    """결과를 그 확정본의 그래프 판으로 맞춘 사본. 확정 해제 전에 판 이전이 있었으면 그 기록대로 kg_paths를 바꾼다.
    이어지지 않으면 None."""
    from hazop.study import migrate
    want = snap["study_nodes_ref"]
    if old_results["study_nodes_ref"] == want:
        return old_results
    pseudo = {"status": "confirmed", "confirmed_at": want["confirmed_at"], "graph_version": want["graph_version"],
              "history": node_set.get("history") or [], "nodes": snap["nodes"]}
    moved, n = migrate.migrate_results(old_results, pseudo)
    return moved if n is not None else None


def carry_results(old_results, node_set, deviations):
    """(새 확정본의 결과, 보고) 또는 (None, 보고). 보고: {same_cells, moved_entries, scope_changed_entries,
    to_excluded: [옛 구간], unmapped: [옛 구간], unmapped_deviations: [...], reason}.
    멈출 사유가 있으면 결과를 만들지 않는다(사람이 먼저 정리해야 함)."""
    from hazop.study import migrate
    from hazop.study import results as res
    report = {"same_cells": 0, "moved_entries": 0, "scope_changed_entries": 0, "to_excluded": [], "unmapped": [],
              "unmapped_deviations": [], "reason": None}
    snap = _matching(node_set, old_results)
    if snap is None:
        return None, dict(report, reason="옛 결과를 만든 확정본 기록이 없음")
    base = _in_snapshot_version(old_results, snap, node_set)
    if base is None:
        return None, dict(report, reason="옛 결과의 그래프 판에서 지금 판으로 이어지는 판 이전 기록이 없음")
    # 그래프 판이 바뀌었으면 판 이전이 내용 같음을 확인한 경우에만 같음으로 본다(migrate.plan kept)
    same_version = snap["study_nodes_ref"]["graph_version"] == node_set.get("graph_version")
    content_same = same_version or bool(migrate._steps(dict(base, study_nodes_ref=dict(
        base["study_nodes_ref"], confirmed_at=node_set.get("confirmed_at"))), node_set))
    old_to_new, _rows = node_map(snap, node_set, content_same)
    out = res.empty_results(dict(node_set, graph_version=snap["study_nodes_ref"]["graph_version"]), deviations)
    cells = {(c["node_id"], c["deviation_id"]): c for c in out["cells"]}
    new_dev = {d["item_id"]: d["deviation_id"] for d in deviations}
    old_dev = {d["deviation_id"]: d.get("item_id") for d in base.get("deviations") or []}
    for c in base.get("cells") or []:
        target = old_to_new.get(c["node_id"]) or {}
        did = new_dev.get(old_dev.get(c["deviation_id"]))
        touched = bool(c["entries"]) or c.get("state") != "not_analyzed"
        if did is None or target.get("node_id") is None:
            if touched:
                report["unmapped_deviations" if did is None else "unmapped"].append(
                    {"node_id": c["node_id"], "deviation_id": c["deviation_id"]})
            continue
        if target["to_excluded"] and not target["exact"] and any(
                e.get("status") in res.HUMAN_STATUSES for e in c["entries"]):
            report["to_excluded"].append(c["node_id"])
            continue
        cell = cells[(target["node_id"], did)]
        if target["exact"]:
            cell.update({k: copy.deepcopy(v) for k, v in c.items() if k not in ("node_id", "deviation_id")})
            report["same_cells"] += 1
            continue
        cell.setdefault("legacy_cells", []).append({"from": c["node_id"], "deviation_id": c["deviation_id"],
                                                    "state": c.get("state"), "ai_run": c.get("ai_run")})
        for e in c["entries"]:
            cell["entries"].append(dict(copy.deepcopy(e), scope_changed=True))
            report["moved_entries"] += 1
            report["scope_changed_entries"] += 1
        cell["state"] = "analyzed" if cell["entries"] else "not_analyzed"
    report["to_excluded"] = sorted(set(report["to_excluded"]), key=_num)
    if report["to_excluded"] or report["unmapped"] or report["unmapped_deviations"]:
        return None, dict(report, reason="옮길 곳이 정해지지 않은 옛 칸이 있음")
    out["ai_log"] = list(base.get("ai_log") or [])
    out["carried_from"] = snap["study_nodes_ref"]
    if not same_version:
        moved, n = migrate.migrate_results(out, node_set)
        if n is not None:  # 판 이전 기록이 이어지면 그대로 kg_paths·판을 지금으로 맞춘다
            out = moved
        else:  # 내용이 바뀐 새 판: 모든 항목이 이미 '범위 바뀜'이라 사람이 다시 본다
            out["study_nodes_ref"] = {"graph_version": node_set.get("graph_version"),
                                      "confirmed_at": node_set.get("confirmed_at")}
    problems = res.validate(out, node_set)
    if problems:
        return None, dict(report, reason="옮긴 결과에 문제 %d건(%s)" % (len(problems), problems[0]))
    return out, report


def carry_saved(node_set, deviations):
    """확정본 node_set의 저장된 결과가 옛 확정본 것이면 옮겨 바로 저장한다(옛 파일은 보관본). (옮긴 결과 또는 None, 보고).
    ④ 확정 직후와 ⑤ 열기에서 같은 길로 부른다(어느 화면이 먼저든 모든 화면이 같은 결과를 읽게)."""
    import os
    from hazop.study import nodes
    from hazop.study import results as res
    if node_set.get("status") != "confirmed" or not node_set.get("previous"):
        return None, {"reason": None}
    path = res.store_path(node_set.get("project_id"), node_set["graph_id"])
    old = res.read(res._readable_path(node_set.get("project_id"), node_set["graph_id"]))
    if old is not None and not res.is_stale(old, node_set):
        return None, {"reason": None}
    if old is None or _matching(node_set, old) is None:
        old = _archived_match(path, node_set) or old  # 앞서 ⑤가 보관본으로 옮긴 옛 결과도 찾는다
    if old is None:
        return None, {"reason": None}
    carried, report = carry_results(old, node_set, deviations)
    if carried is None:
        return None, report
    if os.path.isfile(path):
        os.replace(path, "%s.%s.bak.json" % (path[:-5], nodes.now_utc().replace(":", "")))
    res.save(carried, node_set.get("project_id"))
    return carried, report


def _archived_match(path, node_set):
    """path 옆 보관본(<이름>.<시각>.bak.json) 중 기억한 확정본으로 만든 가장 최근 결과."""
    import os
    from hazop.study import results as res
    folder, base = os.path.split(path)
    if not os.path.isdir(folder):
        return None
    for name in sorted((n for n in os.listdir(folder) if n.startswith(base[:-5] + ".") and n.endswith(".bak.json")),
                       reverse=True):
        try:
            doc = res.read(os.path.join(folder, name))
        except (OSError, ValueError):
            continue
        if doc is not None and _matching(node_set, doc) is not None:
            return doc
    return None


def preview(node_set, new_set, deviations):
    """다시 제안 대응표에 보일 글감: {counts, to_excluded_old, unmatched_old, blocked_by}. 저장된 결과로 미리 옮겨 본다."""
    from hazop.study import results as res
    snap = latest(new_set)
    old_to_new, rows = node_map(snap, new_set) if snap else ({}, {})
    out = {"counts": summary(rows), "to_excluded_old": sum(1 for v in old_to_new.values() if v["to_excluded"]),
           "unmatched_old": sum(1 for v in old_to_new.values() if v["node_id"] is None), "blocked_by": None}
    try:
        old = res.read(res._readable_path(node_set.get("project_id"), node_set["graph_id"]))
    except (OSError, ValueError):
        old = None
    if old is not None and snap is not None:
        _carried, report = carry_results(old, dict(new_set, status="confirmed", confirmed_at="(미리 보기)"), deviations)
        if report.get("to_excluded") or report.get("unmapped") or report.get("unmapped_deviations"):
            out["blocked_by"] = report
    return out
