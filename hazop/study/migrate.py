"""그래프 판 이전: 판이 바뀐 그래프에 확정 검토구간과 ⑤ 결과를 source_object_id로 다시 대응시킨다.
근거: 기획서/지식그래프-스키마.md §8.2 '판 이전', §9 U10(가)(사용자 채택 2026-11-08).

- 확정할 때 구성요소마다 안정 참조("<도면 graph_id>#<source_object_id>")를 member_refs에 남긴다. 그래프를 다시 만들면
  entity_id는 바뀔 수 있어도 이 참조는 그대로라서, 판이 바뀐 뒤에도 옛 구성요소를 새 entity_id로 찾을 수 있다.
- 확정을 유지하는 조건은 보수적이다. 옛 참조 집합과 새 그래프의 참조 집합이 정확히 같고 양쪽 모두 참조가 하나씩만
  있을 때만 유지한다. 구성요소가 빠지거나 늘거나 겹치거나 참조가 없으면 손대지 않는다(지금처럼 '재확인 필요').
- 참조가 같아도 구성요소의 종류·태그·배관 번호·흐름 방향·정상 위치·고장 위치·연결(member_digest)이 바뀌었으면 유지하지 않는다.
  분류(category)는 kind에서 레지스트리로 정해지므로 넣지 않는다(레지스트리 분류 이동만으로 재확인되지 않게, M2 U9).
  분류를 넣어 계산한 옛 기록("md-")은 그 기록을 만들 때의 분류표(레지스트리 0.2.0)로 새 그래프를 다시 계산해 비교한다.
  ② 도면 사람 수정(태그·종류·흐름·끝점)은 '재확인 필요'로 알린다는 결정(결정로그 2026-11-07)을 지키고,
  밸브가 펌프로 바뀐 것처럼 구간 판단이 달라질 변경에서 확정을 그대로 두지 않기 위해서다.
- 유지하면 구성요소·판만 바꾸고 history에 판 이전(옛 판 → 새 판, 대응 수, 바뀐 ID)을 남긴다. 확정자·확정 시각은 그대로다.
- ⑤ 결과는 같은 확정본(confirmed_at)을 가리키면 판과 kg_paths의 구성요소 ID만 바꾼다. 문장·사람 편집·상태는 건드리지 않는다.
- 같은 입력에 두 번 적용해도 결과가 같다(판이 같으면 아무것도 하지 않음).
"""

import copy
import hashlib
import json
import os
import re
import shutil

from hazop import paths

OP = "migrate_version"
_PID_ID = re.compile(r"(^|/)(entity|relation)-")


def ref_of(node, graph_id):
    """구성요소의 안정 참조. 도면 연결 구간은 ID 자체가 양 끝 연결점의 안정 참조로 만든 해시라 그대로 쓴다."""
    soid = node.get("source_object_id")
    if soid:
        return "%s#%s" % (node.get("sheet") or graph_id, soid)
    if (node.get("sheet_link") or {}).get("link_id") == node["entity_id"]:
        return node["entity_id"]
    return None


def member_refs(node_set, graph):
    """{구성요소 entity_id: 안정 참조 또는 None}. 그래프에 없는 구성요소도 None."""
    by_id = {n["entity_id"]: n for n in graph.get("nodes", [])}
    members = sorted({m for n in node_set["nodes"] for m in n["members"]})
    return {m: ref_of(by_id[m], graph.get("graph_id")) if m in by_id else None for m in members}


POSITION_ATTRS = ("normal_position", "fail_position")


def _digest(graph, prefix, category=None, positions=False):
    gid = graph.get("graph_id")
    ref = {n["entity_id"]: ref_of(n, gid) for n in graph.get("nodes", [])}

    def pos(n):
        a = n.get("attributes") or {}
        return [[a.get(k) for k in POSITION_ATTRS]] if positions else []
    nodes = sorted(([ref[n["entity_id"]] or "", n.get("kind")] + ([category(n)] if category else [])
                    + [n.get("tag"), n.get("line_no"),
                       [ref.get((n.get("flow_direction") or {}).get(k)) or "" for k in ("from", "to")]
                       if isinstance(n.get("flow_direction"), dict) else None] + pos(n)
                    for n in graph.get("nodes", [])),
                   key=json.dumps)
    edges = sorted(([e.get("kind")] + sorted(ref.get(x) or "" for x in e.get("nodes") or [])
                    for e in graph.get("edges", [])), key=json.dumps)
    canon = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def member_digest(graph):
    """구간 판단에 쓰는 내용(구성요소 종류·태그·배관 번호·흐름 방향·정상 위치·고장 위치, 관계 종류와 양 끝)을 참조로 적은 해시.
    정상·고장 위치는 ⑤ 원인·결과 판단이 기대므로 바뀌면 재확인한다(결정로그 2026-11-07 "② 수정 시 ④·⑤ 재확인").
    entity_id·판·도면 위치·그 밖의 속성·분류는 넣지 않는다(재추출·필드 추가·레지스트리 분류 이동으로는 바뀌지 않게)."""
    return _digest(graph, "md2-", positions=True)


def legacy_member_digest(graph):
    """옛 "md-" 기록과 비교할 값: 분류를 M2 이전 분류표(rules.LEGACY_KIND_CATEGORY)로 다시 정해 옛 방식대로 계산한다.
    배관 구간과 표에 없는 kind는 그래프의 분류를 쓰되, 그 뒤 레지스트리에 생긴 kind는 그때처럼 None으로 본다."""
    from hazop.extract.rules import KIND_CATEGORY, LEGACY_KIND_CATEGORY

    def category(n):
        k = n.get("kind")
        if k in LEGACY_KIND_CATEGORY:
            return LEGACY_KIND_CATEGORY[k]
        return None if k in KIND_CATEGORY else n.get("category")
    return _digest(graph, "md-", category)


def digest_matches(recorded, graph):
    if not recorded:
        return False
    return recorded == (member_digest(graph) if recorded.startswith("md2-") else legacy_member_digest(graph))


def _usable(node_set, graph):
    return (isinstance(node_set, dict) and node_set.get("status") == "confirmed"
            and graph.get("graph_version") and "nodes" in graph)


def with_refs(node_set, graph):
    """판이 같은 확정본에 member_refs가 없거나 모자라거나 내용 기록이 옛 방식(md-)이면 채운 사본, 아니면 입력 그대로.
    판이 같으면 그래프 내용도 같으므로 옛 기록을 지금 방식으로 다시 계산해도 된다."""
    if not _usable(node_set, graph) or node_set.get("graph_version") != graph["graph_version"]:
        return node_set
    members = {m for n in node_set["nodes"] for m in n["members"]}
    if set(node_set.get("member_refs") or {}) == members and (node_set.get("member_digest") or "").startswith("md2-"):
        return node_set
    out = copy.deepcopy(node_set)
    out.update(member_refs=member_refs(out, graph), member_digest=member_digest(graph))
    return out


def plan(node_set, graph):
    """{"state": "same"|"kept"|"recheck"|"skip", "reason", "matched", "renamed"{옛 ID: 새 ID}}.
    skip은 확정본이 아니거나 그래프가 비교할 수 없는 것(이전 대상 아님)."""
    out = {"state": "skip", "reason": None, "matched": 0, "renamed": {}}
    if not _usable(node_set, graph):
        return out
    if node_set.get("graph_version") == graph["graph_version"]:
        return dict(out, state="same")
    members = sorted({m for n in node_set["nodes"] for m in n["members"]})
    old = node_set.get("member_refs") or {}
    new = {}
    for n in graph["nodes"]:
        new.setdefault(ref_of(n, graph.get("graph_id")), []).append(n["entity_id"])
    olds = [old.get(m) for m in members]
    reason = None
    if not members:
        reason = "구성요소 없음"
    elif any(r is None for r in olds):
        reason = "옛 판의 안정 참조가 없는 구성요소 %d개" % sum(r is None for r in olds)
    elif len(set(olds)) != len(olds):
        reason = "옛 판에서 참조가 겹치는 구성요소가 있음"
    elif None in new:
        reason = "새 판에 안정 참조가 없는 구성요소 %d개" % len(new[None])
    elif any(len(v) > 1 for v in new.values()):
        reason = "새 판에서 한 참조가 여러 구성요소에 대응됨(모호)"
    else:
        missing = sorted(set(olds) - set(new))
        extra = sorted(set(new) - set(olds))
        if missing:
            reason = "새 판에 없는 구성요소 %d개(%s)" % (len(missing), ", ".join(missing[:3]))
        elif extra:
            reason = "새 판에 늘어난 구성요소 %d개(%s)" % (len(extra), ", ".join(extra[:3]))
        elif not node_set.get("member_digest"):
            reason = "옛 판의 구성요소 내용 기록(member_digest)이 없음"
        elif not digest_matches(node_set["member_digest"], graph):
            reason = "구성요소의 종류·태그·흐름·연결·정상 위치·고장 위치가 바뀜"
    if reason:
        return dict(out, state="recheck", reason=reason)
    mapping = {m: new[old[m]][0] for m in members}
    return dict(out, state="kept", matched=len(mapping), renamed={a: b for a, b in mapping.items() if a != b})


def migrate_set(node_set, graph, at=None):
    """(집합, plan). 유지할 수 있으면 구성요소·판을 새 판으로 바꾼 사본, 아니면 입력 그대로."""
    from hazop.study.nodes import now_utc
    p = plan(node_set, graph)
    if p["state"] != "kept":
        return node_set, p
    from hazop.study.nodes import map_members
    ren = p["renamed"]
    out = map_members(node_set, ren)
    old_version = out.get("graph_version")
    out["graph_version"] = graph["graph_version"]
    out.update(member_refs=member_refs(out, graph), member_digest=member_digest(graph))
    out["history"].append({"at": at or now_utc(), "op": OP,
                           "detail": {"from": old_version, "to": graph["graph_version"],
                                      "matched": p["matched"], "renamed": dict(sorted(ren.items()))}})
    return out, p


def _steps(results, node_set):
    """결과의 판에서 집합의 판까지 이어지는 판 이전 기록(순서대로). 이어지지 않으면 None."""
    ref = results.get("study_nodes_ref") or {}
    if ref.get("confirmed_at") != node_set.get("confirmed_at") or node_set.get("status") != "confirmed":
        return None
    cur, steps = ref.get("graph_version"), []
    for h in node_set.get("history") or []:
        d = h.get("detail") or {}
        if h.get("op") == OP and d.get("from") == cur:
            steps.append(d)
            cur = d.get("to")
    return steps if steps and cur == node_set.get("graph_version") else None


def migrate_results(results, node_set, at=None):
    """(결과, 바꾼 kg_paths ID 수 또는 None). 같은 확정본을 옛 판으로 가리키는 결과만 판·kg_paths ID를 바꾼 사본.
    이어지는 판 이전 기록이 없으면 입력 그대로(결과의 is_stale이 지금처럼 재확인으로 보여 줌)."""
    from hazop.study.nodes import now_utc
    steps = _steps(results, node_set)
    if steps is None:
        return results, None
    current = {m for n in node_set["nodes"] for m in n["members"]}
    back = {}
    for d in reversed(steps):
        inv = {v: k for k, v in d["renamed"].items()}
        back = {m: inv.get(back.get(m, m), back.get(m, m)) for m in current}
    forward = {old: new for new, old in back.items()}
    out = copy.deepcopy(results)
    changed = unmapped = 0
    for cell in out.get("cells") or []:
        for e in cell.get("entries") or []:
            basis = e.get("ai_basis")
            if not isinstance(basis, dict) or not isinstance(basis.get("kg_paths"), list):
                continue
            for path in basis["kg_paths"]:
                for i, x in enumerate(path):
                    if x in forward:
                        changed += forward[x] != x
                        path[i] = forward[x]
                    elif isinstance(x, str) and _PID_ID.search(x):
                        unmapped += 1
    old_version = out["study_nodes_ref"]["graph_version"]
    out["study_nodes_ref"]["graph_version"] = node_set["graph_version"]
    out.setdefault("version_migrations", []).append({
        "at": at or now_utc(), "from": old_version, "to": node_set["graph_version"],
        "kg_path_ids_changed": changed, "kg_path_ids_unmapped": unmapped})
    return out, changed


def notice(node_set):
    """마지막 기록이 판 이전이면 화면 문구, 아니면 None."""
    h = (node_set or {}).get("history") or []
    if not h or h[-1].get("op") != OP:
        return None
    d = h[-1]["detail"]
    return "그래프 판이 바뀌어(%s → %s) 구성요소 %d개를 새 판에 다시 맞췄습니다. 확정은 그대로입니다." % (
        d["from"], d["to"], d["matched"])


def _backup(path, label="판이전"):
    """<작업 루트>/데이터/백업/<시각>-<label>/<작업 루트 기준 경로>에 복사하고 그 경로를 돌려준다."""
    from hazop.study.nodes import now_utc
    stamp = now_utc().replace(":", "").replace("-", "")
    dst = os.path.join(paths.folder("백업", "%s-%s" % (stamp, label)), paths.backup_rel(path, paths.work_root()))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(path, dst)
    return dst


def on_load(node_set, graph, path):
    """nodes.load가 부른다. 참조를 채우거나 판을 이전했으면 옛 파일을 백업한 뒤 읽은 파일 자리에 쓰고,
    같은 확정본의 ⑤ 결과 파일도 함께 이전한다. 쓸 일이 없으면 아무것도 쓰지 않는다."""
    from hazop.study import nodes, results as res
    out = with_refs(node_set, graph)
    out, p = migrate_set(out, graph)
    if out is node_set:
        return node_set
    try:
        _backup(path)
        nodes.write(path, out)
    except OSError:  # 백업·쓰기를 못 하면 이전하지 않는다. 화면은 지금처럼 재확인 안내와 함께 저장본을 연다
        return node_set
    if p["state"] == "kept":
        rpath = res._readable_path(out.get("project_id"), out["graph_id"])
        try:
            doc = res.read(rpath)
        except (OSError, ValueError):  # 읽지 못하는 결과는 그대로 두고 화면이 지금처럼 문제로 보여 준다
            doc = None
        if doc is not None and doc.get("graph_id") == out["graph_id"]:
            moved, n = migrate_results(doc, out)
            if n is not None:
                try:
                    _backup(rpath)
                    res.write(rpath, moved)
                except OSError:  # 결과 파일은 다음에 읽을 때 results.load가 메모리에서 다시 이전한다
                    pass
    return out
