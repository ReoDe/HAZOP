"""그래프 판 이전: 판이 바뀐 그래프에 검토구간과 ⑤ 결과를 source_object_id로 다시 대응시킨다.
근거: 기획서/지식그래프-스키마.md §8.2 '판 이전', §9 U10(가), docs/specs/study-node-segmentation.md §2.6.

- 집합(0.2)의 graph_member_refs는 그래프 전체 구성요소의 안정 참조("<도면 graph_id>#<source_object_id>")다. 그래프를 다시
  만들면 entity_id는 바뀔 수 있어도 이 참조는 그대로라서, 판이 바뀐 뒤에도 옛 구성요소를 새 entity_id로 찾는다.
  구간 밖 구성요소가 늘거나 줄어도 재확인 사유가 아니다(§1 #17·#18).
- 판 이전은 모든 구간에 적용하고 재확인은 구간마다 정한다. 구간마다 내용 지문(md3-: 그 구간 구성요소와 거기 닿는 관계의
  종류·태그·배관 번호·흐름·정상 위치·고장 위치)을 남기고, 지문이 바뀌었거나 구성요소를 새 판에서 찾지 못한 구간만 rev를
  올린다. 그 구간이 확정이면 적용됨으로 내리고(⑤ 칸은 보관), 잠금이면 잠금을 두고 version_changed를 단다(§5.3).
- ⑤ 결과는 판 이전 기록을 따라 판과 kg_paths의 구성요소 ID만 바꾼다. 칸의 범위 바뀜·보관은 results.reconcile이 rev로 정한다.
- 0.1 파일의 함수(member_refs·member_digest·legacy_steps·legacy_migrate_results)는 0.1 결과를 처음 이을 때만 쓴다.
- 같은 입력에 두 번 적용해도 결과가 같다(판이 같으면 아무것도 하지 않음).
"""

import copy
import hashlib
import json
import logging
import re

from hazop import store_io

OP = "migrate_version"
_PID_ID = re.compile(r"(^|/)(entity|relation)-")
POSITION_ATTRS = ("normal_position", "fail_position")


def ref_of(node, graph_id):
    """구성요소의 안정 참조. 도면 연결 구간은 ID 자체가 양 끝 연결점의 안정 참조로 만든 해시라 그대로 쓴다."""
    soid = node.get("source_object_id")
    if soid:
        return "%s#%s" % (node.get("sheet") or graph_id, soid)
    if (node.get("sheet_link") or {}).get("link_id") == node["entity_id"]:
        return node["entity_id"]
    return None


def graph_refs(graph):
    """{그래프 구성요소 entity_id: 안정 참조 또는 None} 그래프 전체."""
    gid = graph.get("graph_id")
    return dict(sorted((n["entity_id"], ref_of(n, gid)) for n in graph.get("nodes", [])))


def node_digests(graph, members_by_node):
    """{node_id: "md3-…"}. members_by_node: {node_id: [entity_id]}. 그래프에 없는 구성요소가 있거나 빈 구간은 뺀다."""
    gid = graph.get("graph_id")
    by_id = {n["entity_id"]: n for n in graph.get("nodes", [])}
    ref = {e: ref_of(n, gid) for e, n in by_id.items()}
    touching = {}
    for e in graph.get("edges", []):
        row = json.dumps([e.get("kind")] + sorted(ref.get(x) or "" for x in e.get("nodes") or []), ensure_ascii=False)
        for x in set(e.get("nodes") or []):
            touching.setdefault(x, []).append(row)

    def row(n):
        a = n.get("attributes") or {}
        flow = ([ref.get((n.get("flow_direction") or {}).get(k)) or "" for k in ("from", "to")]
                if isinstance(n.get("flow_direction"), dict) else None)
        return [ref[n["entity_id"]] or "", n.get("kind"), n.get("tag"), n.get("line_no"), flow,
                [a.get(k) for k in POSITION_ATTRS]]
    out = {}
    for nid, members in members_by_node.items():
        if not members or any(m not in by_id for m in members):
            continue
        nodes = sorted((row(by_id[m]) for m in set(members)), key=json.dumps)
        edges = sorted({r for m in set(members) for r in touching.get(m, [])})
        canon = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        out[nid] = "md3-" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
    return out


def node_digest(graph, members):
    return node_digests(graph, {"_": members}).get("_")


# ---------------------------------------------------------------- 0.1 집합의 기록(0.1 결과를 처음 이을 때만)

def member_refs(node_set, graph):
    """(0.1) {구간 구성요소 entity_id: 안정 참조 또는 None}. 그래프에 없는 구성요소도 None."""
    by_id = {n["entity_id"]: n for n in graph.get("nodes", [])}
    members = sorted({m for n in node_set["nodes"] for m in n["members"]})
    return {m: ref_of(by_id[m], graph.get("graph_id")) if m in by_id else None for m in members}


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
    """(0.1) 그래프 전체 내용 해시(md2-). 0.1 확정본이 남긴 값과 비교할 때만 쓴다."""
    return _digest(graph, "md2-", positions=True)


def legacy_member_digest(graph):
    """옛 "md-" 기록과 비교할 값: 분류를 M2 이전 분류표(rules.LEGACY_KIND_CATEGORY)로 다시 정해 옛 방식대로 계산한다."""
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


def legacy_steps(results, node_set):
    """(0.1) 결과의 판에서 집합의 판까지 이어지는 판 이전 기록(순서대로). 이어지지 않으면 None."""
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


def legacy_migrate_results(results, node_set, at=None):
    """(0.1) (결과, 바꾼 kg_paths ID 수 또는 None). 같은 확정본을 옛 판으로 가리키는 0.1 결과만 판·kg_paths ID를 바꾼 사본."""
    from hazop.study.nodes import now_utc
    steps = legacy_steps(results, node_set)
    if steps is None:
        return results, None
    current = {m for n in node_set["nodes"] for m in n["members"]}
    back = {}
    for d in reversed(steps):
        inv = {v: k for k, v in d["renamed"].items()}
        back = {m: inv.get(back.get(m, m), back.get(m, m)) for m in current}
    forward = {old: new for new, old in back.items()}
    out = copy.deepcopy(results)
    changed = _rename_paths(out, forward)[0]
    old_version = out["study_nodes_ref"]["graph_version"]
    out["study_nodes_ref"]["graph_version"] = node_set["graph_version"]
    out.setdefault("version_migrations", []).append({
        "at": at or now_utc(), "from": old_version, "to": node_set["graph_version"],
        "kg_path_ids_changed": changed, "kg_path_ids_unmapped": _rename_paths(out, {})[1]})
    return out, changed


def _rename_paths(results, forward):
    """results(고침)의 kg_paths ID를 forward로 바꾼다. (바꾼 수, 대응 없는 ID 수)."""
    changed = unmapped = 0
    for cell in results.get("cells") or []:
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
    return changed, unmapped


# ---------------------------------------------------------------- 0.2 집합

def _usable(node_set, graph):
    return (isinstance(node_set, dict) and node_set.get("schema_version") == "0.2"
            and graph.get("graph_version") and "nodes" in graph)


def with_refs(node_set, graph):
    """판이 같은 집합에 그래프 전체 참조나 확정·잠금 구간의 지문(md3-)이 모자라면 채운 사본, 아니면 입력 그대로."""
    if not _usable(node_set, graph) or node_set.get("graph_version") != graph["graph_version"]:
        return node_set
    ids = {n["entity_id"] for n in graph["nodes"]}
    have = node_set.get("member_digest") or {}
    todo = {n["node_id"]: n["members"] for n in node_set["nodes"]  # 적용됨 구간은 지문이 없어도 됨(판이 바뀌면 rev만 오름)
            if n.get("state") in ("confirmed", "locked") and not str(have.get(n["node_id"]) or "").startswith("md3-")}
    fresh = node_digests(graph, todo) if todo else {}
    if set(node_set.get("graph_member_refs") or {}) == ids and not fresh:
        return node_set
    out = copy.deepcopy(node_set)
    out["graph_member_refs"] = graph_refs(graph)
    out["member_digest"] = dict(have, **fresh)
    return out


def plan(node_set, graph):
    """{"state": "same"|"kept"|"skip", "matched", "renamed"{옛 ID: 새 ID}, "recheck"{node_id: 사유}, "reason"}.
    kept는 판 이전을 적용한다는 뜻이고 재확인은 recheck에 든 구간만이다. skip은 0.2 집합이 아니거나 그래프를 비교할 수 없는 것."""
    out = {"state": "skip", "reason": None, "matched": 0, "renamed": {}, "recheck": {}}
    if not _usable(node_set, graph):
        return out
    if node_set.get("graph_version") == graph["graph_version"]:
        return dict(out, state="same")
    old = node_set.get("graph_member_refs") or {}
    new = {}
    for n in graph["nodes"]:
        new.setdefault(ref_of(n, graph.get("graph_id")), []).append(n["entity_id"])
    mapping, lost = {}, set()
    every = set(old) | {m for n in node_set["nodes"] for m in n["members"]}  # 그래프 전체(되돌리기 기록의 ID도 옮기려고)
    for m in sorted(every):
        r = old.get(m)
        hits = new.get(r) if r is not None else None
        if not hits or len(hits) != 1:
            lost.add(m)
        else:
            mapping[m] = hits[0]
    recorded = node_set.get("member_digest") or {}
    legacy = (node_set.get("legacy") or {}).get("member_digest")
    legacy_same = bool(legacy) and digest_matches(legacy, graph)
    fresh = node_digests(graph, {n["node_id"]: [mapping[m] for m in n["members"]]
                                 for n in node_set["nodes"] if not set(n["members"]) & lost})
    recheck = {}
    for n in node_set["nodes"]:
        nid, gone = n["node_id"], set(n["members"]) & lost
        rec = str(recorded.get(nid) or "")
        if gone:
            recheck[nid] = "새 판에서 찾지 못한 구성요소 %d개(%s)" % (len(gone), ", ".join(sorted(gone)[:3]))
        elif rec.startswith("md3-"):
            if rec != fresh.get(nid):
                recheck[nid] = "구성요소의 종류·태그·흐름·연결·정상 위치·고장 위치가 바뀜"
        elif not legacy_same and n.get("state") in ("confirmed", "locked"):
            recheck[nid] = "옛 판의 구간 내용 기록이 없음"  # 확정한 적 없는 적용됨 구간은 분석 전이라 판만 옮김
    member_ids = {m for n in node_set["nodes"] for m in n["members"]}
    return dict(out, state="kept", matched=len(member_ids & set(mapping)), recheck=recheck,
                renamed={a: b for a, b in mapping.items() if a != b})


def migrate_set(node_set, graph, at=None):
    """(집합, plan). 판 이전을 적용한 사본 또는 입력 그대로. 재확인 구간은 rev가 오르고, 확정이면 적용됨으로 내리며,
    잠금이면 잠금을 두고 version_changed를 단다. 이미 적용됨인 구간도 구성요소 ID는 새 판으로 바뀐다."""
    p = plan(node_set, graph)
    if p["state"] != "kept":
        return node_set, p
    from hazop.study.nodes import map_members, now_utc
    at = at or now_utc()
    ren = p["renamed"]
    out = map_members(node_set, ren)
    old_version = out.get("graph_version")
    demoted = []
    for n in out["nodes"]:
        why = p["recheck"].get(n["node_id"])
        if why is None:
            continue
        if n.get("state") == "locked":  # 잠금은 두고 결과도 그대로(§5.3). rev는 사람이 잠금을 풀 때 오른다
            n["version_changed"] = {"from": old_version, "to": graph["graph_version"], "reason": why, "at": at}
            continue
        n["rev"] = (n.get("rev") or 1) + 1
        if n.get("state") == "confirmed":
            n["state"], n["confirmed"] = "applied", None
            demoted.append(n["node_id"])
    out["graph_version"] = graph["graph_version"]
    out["graph_member_refs"] = graph_refs(graph)
    out["member_digest"] = node_digests(graph, {n["node_id"]: n["members"] for n in out["nodes"]})
    if (out.get("legacy") or {}).get("member_digest"):  # 한 번 이어 쓴 뒤로는 구간 지문만 쓴다
        out["legacy"] = dict(out["legacy"], member_digest=None)
    out["set_rev"] = (out.get("set_rev") or 0) + 1
    out["history"].append(store_io.history_row(OP, {"detail": {
        "from": old_version, "to": graph["graph_version"], "matched": p["matched"],
        "renamed": dict(sorted(ren.items())), "recheck": dict(sorted(p["recheck"].items())), "demoted": demoted}}, at))
    return out, p


def _steps(results, node_set):
    """0.2 결과의 판에서 집합의 판까지 이어지는 판 이전 기록(순서대로). 이어지지 않으면 None."""
    cur, steps = results.get("graph_version"), []
    for h in node_set.get("history") or []:
        d = h.get("detail") or {}
        if h.get("op") == OP and d.get("from") == cur:
            steps.append(d)
            cur = d.get("to")
    return steps if steps and cur == node_set.get("graph_version") else None


def migrate_results(results, node_set, at=None):
    """(결과, 바꾼 kg_paths ID 수 또는 None). 0.2 결과의 판과 kg_paths ID를 판 이전 기록대로 지금 판으로 바꾼 사본.
    판이 같거나 이어지는 기록이 없으면 입력 그대로와 None. 0.1 결과는 legacy_migrate_results로."""
    if results.get("schema_version") not in ("0.2", "0.3"):  # results.CELL_SCHEMA_VERSIONS(순환 import를 피해 값으로)
        return legacy_migrate_results(results, node_set, at)
    steps = _steps(results, node_set)
    if steps is None:
        return results, None
    from hazop.study.nodes import now_utc
    forward = {}
    for d in steps:
        forward = {k: d["renamed"].get(v, v) for k, v in forward.items()}
        for k, v in d["renamed"].items():
            forward.setdefault(k, v)
    out = copy.deepcopy(results)
    changed, unmapped = _rename_paths(out, forward)
    old_version = out.get("graph_version")
    out["graph_version"] = node_set["graph_version"]
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
    again = len(d.get("recheck") or {})
    return "그래프 판이 바뀌어(%s → %s) 구성요소 %d개를 새 판에 다시 맞췄습니다. %s" % (
        d["from"], d["to"], d["matched"],
        "내용이 바뀐 구간 %d개만 다시 확인이 필요합니다." % again if again else "확정은 그대로입니다.")


BACKUP_LABEL = "판이전"
_log = logging.getLogger(__name__)


def unwritten(node_set, graph):
    """읽은 집합이 아직 판 이전·참조 채우기를 기다리면 True. on_load가 파일에 쓰지 못하고 저장본을 그대로 돌려준 경우다."""
    out = with_refs(node_set, graph)
    return migrate_set(out, graph)[0] is not node_set


def on_load(node_set, graph, path, fp):
    """nodes.load_fp가 부른다. fp는 node_set을 읽은 바이트의 지문이다. (집합, 지금 파일의 지문)을 돌려준다.
    참조를 채우거나 판을 이전했으면 옛 파일을 백업한 뒤 읽은 파일 자리에 쓰고, ⑤ 결과 파일의 판·kg_paths도 함께 이전한다.
    쓸 일이 없으면 아무것도 쓰지 않는다. 읽은 뒤 파일이 바뀌었으면 쓰지 않는다."""
    from hazop.study import results as res
    out = with_refs(node_set, graph)
    out, p = migrate_set(out, graph)
    if out is node_set:
        return node_set, fp
    try:
        store_io.backup_file(path, BACKUP_LABEL)
        fp = store_io.write_json(path, out, expect=fp, sort_keys=False)
    except (OSError, store_io.Conflict) as exc:  # 백업·쓰기를 못 하면 이전하지 않는다. 부른 쪽은 unwritten으로 알아보고 알린다
        _log.warning("검토구간 판 이전을 저장하지 못함: %s (%s)", path, exc)
        return node_set, fp
    if p["state"] == "kept":
        rpath = res._readable_path(out.get("project_id"), out["graph_id"])
        try:
            doc, rfp = res.read_fp(rpath)
        except (OSError, ValueError):  # 읽지 못하는 결과는 그대로 두고 화면이 지금처럼 문제로 보여 준다
            doc = None
        if doc is not None and doc.get("graph_id") == out["graph_id"] and doc.get("schema_version") in ("0.2", "0.3"):
            moved, n = migrate_results(doc, out)
            if n is not None:
                try:
                    store_io.backup_file(rpath, BACKUP_LABEL)
                    res.write(rpath, moved, expect=rfp)
                except (OSError, store_io.Conflict) as exc:  # 결과 파일은 다음에 읽을 때 results.load가 메모리에서 다시 이전한다
                    _log.warning("분석 결과 판 이전을 저장하지 못함: %s (%s)", rpath, exc)
    return out, fp
