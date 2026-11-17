"""그래프 판 이전: 판이 바뀐 그래프에 검토구간과 ⑤ 결과를 source_object_id로 다시 대응시킨다.
근거: 기획서/지식그래프-스키마.md §8.2 '판 이전', §9 U10(가), docs/specs/study-node-segmentation.md §2.6.

- 집합(0.2)의 graph_member_refs는 그래프 전체 구성요소의 안정 참조("<도면 graph_id>#<source_object_id>")다. 그래프를 다시
  만들면 entity_id는 바뀔 수 있어도 이 참조는 그대로라서, 판이 바뀐 뒤에도 옛 구성요소를 새 entity_id로 찾는다.
  구간 밖 구성요소가 늘거나 줄어도 재확인 사유가 아니다(§1 #17·#18).
- PDF 추출의 source_object_id는 기호 순번이라, 추출 규칙이 바뀌어 다시 추출하면 같은 참조가 다른 기호를 가리킬 수 있다.
  그래서 구성요소마다 위치 표시(graph_member_marks: 구성요소 종류와 위치 상자)도 남기고, 참조가 가리키는 새 구성요소의
  표시가 다르면 잇지 않는다. 같은 표시를 가진 구성요소가 새 판에 정확히 하나면 그것으로 잇고, 아니면 '찾지 못함'으로
  남긴다(확신하지 못하면 가리키지 않는다). 표시가 없는 옛 집합과 상자가 없는 구성요소는 참조만 본다.
- 판 이전은 모든 구간에 적용하고 재확인은 구간마다 정한다. 구간마다 내용 지문(md3-: 그 구간 구성요소와 거기 닿는 관계의
  종류·태그·배관 번호·흐름·정상 위치·고장 위치)을 남기고, 지문이 바뀌었거나 구성요소를 새 판에서 찾지 못한 구간만 rev를
  올린다. 그 구간이 확정이면 적용됨으로 내리고(⑤ 칸은 보관), 잠금이면 잠금을 두고 version_changed를 단다(§5.3).
- ⑤ 결과는 판 이전 기록을 따라 판과 kg_paths의 구성요소 ID를 바꾸고, 항목의 대상 참조(원인 위치·영향 대상·보호수단 구현
  대상)도 판 이전이 이은 구성요소의 참조로 바꾼다. 새 판에서 찾지 못한 구성요소의 참조는 LOST_MARK를 붙여 어디도 가리키지
  않게 한다(그대로 두면 같은 순번의 다른 기호를 가리킨다). 칸의 범위 바뀜·보관은 results.reconcile이 rev로 정한다.
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
LOST_MARK = "~lost"  # 판 이전에서 대상을 찾지 못한 ⑤ 참조 끝에 붙인다. 그래프 어디에도 없는 참조라 '대상 없음(재확인)'으로 보인다
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


MARK_TOL = 1.0  # pt. 같은 기호를 다시 읽으면 상자가 그대로다


def mark_of(node):
    """구성요소의 위치 표시 [node_type, 도면(프로젝트 그래프의 sheet, 도면 그래프는 None), x0, y0, x1, y1](0.1pt 반올림).
    위치 상자가 없으면 None. 좌표는 도면마다 따로라 도면도 같아야 같은 자리다."""
    b = node.get("bbox")
    if not (isinstance(b, (list, tuple)) and len(b) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in b)):
        return None
    x, y, w, h = b
    return [node.get("node_type"), node.get("sheet"), round(x, 1), round(y, 1), round(x + w, 1), round(y + h, 1)]


def graph_marks(graph):
    """{그래프 구성요소 entity_id: 위치 표시} 위치 상자가 있는 구성요소만."""
    return dict(sorted((n["entity_id"], m) for n in graph.get("nodes", []) for m in [mark_of(n)] if m is not None))


def _fits(mark, node):
    m = mark_of(node)
    return (m is not None and len(mark) == len(m) and m[:2] == mark[:2]
            and all(abs(a - b) <= MARK_TOL for a, b in zip(m[2:], mark[2:])))


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
    if (set(node_set.get("graph_member_refs") or {}) == ids and not fresh
            and node_set.get("graph_member_marks") == graph_marks(graph)):
        return node_set
    out = copy.deepcopy(node_set)
    out["graph_member_refs"] = graph_refs(graph)
    out["graph_member_marks"] = graph_marks(graph)
    out["member_digest"] = dict(have, **fresh)
    return out


def plan(node_set, graph):
    """{"state": "same"|"kept"|"skip", "matched", "renamed"{옛 ID: 새 ID}, "lost"[새 판에서 찾지 못한 구간 구성요소],
    "unmapped"[새 판에서 찾지 못한 그래프 전체 구성요소], "ref_moved"{옛 안정 참조: 새 안정 참조 또는 None(찾지 못함)} 바뀐
    것만, "marked"(위치 표시로 확인했는가. 표시 없는 옛 집합은 참조만 믿어 False), "recheck"{node_id: 사유}, "reason"}.
    kept는 판 이전을 적용한다는 뜻이고 재확인은 recheck에 든 구간만이다. skip은 0.2 집합이 아니거나 그래프를 비교할 수 없는 것."""
    out = {"state": "skip", "reason": None, "matched": 0, "renamed": {}, "lost": [], "unmapped": [], "ref_moved": {},
           "marked": False, "recheck": {}}
    if not _usable(node_set, graph):
        return out
    if node_set.get("graph_version") == graph["graph_version"]:
        return dict(out, state="same")
    old = node_set.get("graph_member_refs") or {}
    marks = node_set.get("graph_member_marks") or {}
    by_id = {n["entity_id"]: n for n in graph["nodes"]}
    new, by_type = {}, {}
    for n in graph["nodes"]:
        new.setdefault(ref_of(n, graph.get("graph_id")), []).append(n["entity_id"])
        by_type.setdefault(n.get("node_type"), []).append(n)
    mapping, lost = {}, set()
    every = set(old) | {m for n in node_set["nodes"] for m in n["members"]}  # 그래프 전체(되돌리기 기록의 ID도 옮기려고)
    for m in sorted(every):
        r = old.get(m)
        hits = new.get(r) if r is not None else None
        mark = marks.get(m)
        if mark is not None and not (hits and len(hits) == 1 and _fits(mark, by_id[hits[0]])):
            # 참조가 다른 자리의 구성요소를 가리킨다(다시 추출로 순번이 밀림). 같은 자리의 구성요소가 하나뿐일 때만 잇는다
            hits = [n["entity_id"] for n in by_type.get(mark[0], []) if _fits(mark, n)]
        if not hits or len(hits) != 1:
            lost.add(m)
        else:
            mapping[m] = hits[0]
    into = {}
    for m, e in mapping.items():
        into.setdefault(e, []).append(m)
    for ms in into.values():
        if len(ms) > 1:  # 옛 구성요소 둘이 새 구성요소 하나로 모이면 어느 쪽인지 모른다
            for m in ms:
                del mapping[m]
                lost.add(m)
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
    ref_moved = {}
    for m, r in old.items():
        if r is None:
            continue
        to = ref_of(by_id[mapping[m]], graph.get("graph_id")) if m in mapping else None
        if to != r:
            ref_moved[r] = to
    return dict(out, state="kept", matched=len(member_ids & set(mapping)), recheck=recheck,
                renamed={a: b for a, b in mapping.items() if a != b}, lost=sorted(member_ids & lost),
                unmapped=sorted(lost), ref_moved=dict(sorted(ref_moved.items())), marked=bool(marks))


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
    out["graph_member_marks"] = graph_marks(graph)
    out["member_digest"] = node_digests(graph, {n["node_id"]: n["members"] for n in out["nodes"]})
    if (out.get("legacy") or {}).get("member_digest"):  # 한 번 이어 쓴 뒤로는 구간 지문만 쓴다
        out["legacy"] = dict(out["legacy"], member_digest=None)
    out["set_rev"] = (out.get("set_rev") or 0) + 1
    out["history"].append(store_io.history_row(OP, {"detail": {
        "from": old_version, "to": graph["graph_version"], "matched": p["matched"],
        "renamed": dict(sorted(ren.items())), "unmapped": p["unmapped"], "ref_moved": p["ref_moved"],
        "marked": p["marked"], "recheck": dict(sorted(p["recheck"].items())), "demoted": demoted}}, at))
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
    forward, refs_forward = {}, {}
    for d in steps:
        gone = set(d.get("unmapped") or [])

        def step(v):
            return v if v.endswith(LOST_MARK) else v + LOST_MARK if v in gone else d["renamed"].get(v, v)
        forward = {k: step(v) for k, v in forward.items()}
        for k in set(d["renamed"]) | gone:
            forward.setdefault(k, step(k))
        moved = d.get("ref_moved") or {}
        refs_forward = {k: (moved.get(v, v) if v is not None else None) for k, v in refs_forward.items()}
        for k, v in moved.items():
            refs_forward.setdefault(k, v)
    out = copy.deepcopy(results)
    changed, unmapped = _rename_paths(out, forward)
    refs_changed, refs_lost = _move_refs(out, refs_forward)
    old_version = out.get("graph_version")
    out["graph_version"] = node_set["graph_version"]
    out.setdefault("version_migrations", []).append({
        "at": at or now_utc(), "from": old_version, "to": node_set["graph_version"],
        "kg_path_ids_changed": changed, "kg_path_ids_unmapped": unmapped,
        "refs_changed": refs_changed, "refs_lost": refs_lost,
        # 위치 표시 없이(참조만 믿고) 이은 판 이전이 끼어 있으면, 옮긴 참조도 다른 기호일 수 있다. 화면이 확인을 띄울 근거
        "refs_unverified": any(not d.get("marked") for d in steps)})
    return out, changed


def _move_expectations(entry, forward):
    """항목의 잠재 후보 ID(exp-<규칙>-<대상 참조 해시>)를 대상 참조 대응대로 바꾼다. (바꾼 수, 찾지 못한 수)."""
    from hazop.kg import expect
    xs = entry.get("expectation_refs")
    if not isinstance(xs, list) or not forward:
        return 0, 0
    changed = lost = 0
    out = []
    for x in xs:
        rule = x[len(expect.ID_PREFIX):].rsplit("-", 1)[0] if isinstance(x, str) and x.startswith(expect.ID_PREFIX) else None
        old = next((r for r in forward if rule and expect.expectation_id(rule, r) == x), None)
        if old is None:
            out.append(x)
        elif forward[old] is None:
            out.append(x + LOST_MARK)
            lost += 1
        else:
            out.append(expect.expectation_id(rule, forward[old]))
            changed += 1
    entry["expectation_refs"] = out
    return changed, lost


def _move_refs(results, forward):
    """results(고침) 항목의 대상 참조(원인·영향·보호수단, 잠재 후보 ID)를 forward{옛 참조: 새 참조 또는 None}로 바꾼다.
    (바꾼 수, 찾지 못해 표시한 수)."""
    changed = lost = 0
    for cell in results.get("cells") or []:
        for e in cell.get("entries") or []:
            c, n = _move_expectations(e, forward)
            changed, lost = changed + c, lost + n
            rows = [r for f in ("cause_refs", "consequence_refs") for r in e.get(f) or []]
            rows += [r for s in e.get("safeguards") or [] if isinstance(s, dict) for r in s.get("refs") or []]
            for r in rows:
                if not isinstance(r, dict) or r.get("ref") not in forward:
                    continue
                to = forward[r["ref"]]
                if to is None:
                    r["ref"] += LOST_MARK
                    lost += 1
                else:
                    r["ref"] = to
                    changed += 1
    return changed, lost


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
