"""그래프 판 이전: 판이 바뀐 그래프에 검토구간과 ⑤ 결과를 다시 대응시킨다. 무엇이 무엇으로 가는지(대응표)와 어디에 id가
있는지(등록부)는 hazop.study.idmap이 맡고, 여기서는 차례(옛 꼴 바꾸기 → 표 계산 → 적용 → 재확인 → 쓰기)만 맡는다.
근거: 기획서/지식그래프-스키마.md §8.2 '판 이전', §9 U10(가), docs/specs/study-node-segmentation.md §2.6.

- 집합의 판 사진(graph_member_refs·graph_member_marks·graph_member_basis)은 그래프 전체 구성요소의 안정 참조·표시·id 근거다.
  판이 같으면 사진을 채우기만 하고(읽기만으로 구성요소를 잃지 않음), 판이 다르면 사진으로 대응표를 만든다(idmap.compute).
  구간 밖 구성요소가 늘거나 줄어도 재확인 사유가 아니다(§1 #17·#18).
- 판 이전은 모든 구간에 적용하고 재확인은 구간마다 정한다. 구간마다 내용 지문(md3-: 그 구간 구성요소와 거기 닿는 관계의
  종류·태그·배관 번호·흐름·정상 위치·고장 위치)을 남기고, 지문이 바뀌었거나 구성요소를 잃었거나 되찾은 구간만 rev를
  올린다. 그 구간이 확정이면 적용됨으로 내리고(⑤ 칸은 보관), 잠금이면 잠금을 두고 version_changed를 단다(§5.3).
- ⑤ 결과는 판 이전 줄 번호(step)로 따라간다. 결과에 마지막으로 적용한 줄 번호를 적고 그 뒤 줄만 적용한다(앞 판으로 돌아온
  뒤 그 판에서 단 참조를 되돌아감에 다시 넣지 않음). 줄에는 그대로 이어진 것도 적어, 늦게 따라와도 즉시 옮긴 것과 같은 표다.
- 0.1 파일의 함수(member_refs·member_digest·legacy_steps·legacy_migrate_results)는 0.1 결과를 처음 이을 때만 쓴다.
- 같은 입력에 두 번 적용해도 결과가 같다(판이 같으면 아무것도 하지 않음, 묘비 id는 입력의 묘비 일련번호에서 결정됨).
"""

import copy
import hashlib
import json
import logging

from hazop import store_io
from hazop.study import idmap
from hazop.study.idmap import ref_of  # noqa: F401  여러 곳(ie·shell·refs)이 이 이름으로 부른다

OP = "migrate_version"
_PID_ID = idmap._PID_ID
POSITION_ATTRS = ("normal_position", "fail_position")
SCHEMA = "0.3"            # 묘비 꼴 집합(hazop.study.nodes.SCHEMA_VERSION과 같음)
SCHEMAS = ("0.2", "0.3")  # 0.2는 읽을 때 0.3으로 바꾼다


def node_digests(graph, members_by_node, names=None):
    """{node_id: "md3-…"}. members_by_node: {node_id: [entity_id]}. 그래프에 없는 구성요소가 있거나 빈 구간은 뺀다.
    names {entity_id: 옛 판 참조}를 주면 그 구성요소는 참조 대신 그 이름으로 센다(판 이전에서 이은 구성요소를 옛 판 이름으로
    불러, 순번만 다시 매겨진 것은 내용이 바뀐 것으로 보지 않는다)."""
    gid = graph.get("graph_id")
    by_id = {n["entity_id"]: n for n in graph.get("nodes", [])}
    ref = {e: ref_of(n, gid) for e, n in by_id.items()}
    ref.update((e, r) for e, r in (names or {}).items() if e in ref)
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


# ---------------------------------------------------------------- 0.2·0.3 집합

def _usable(node_set, graph):
    return (isinstance(node_set, dict) and node_set.get("schema_version") in SCHEMAS
            and graph.get("graph_version") and "nodes" in graph)


def _upgrade(node_set):
    """옛 꼴(0.2: A꼴 표시 없음, B꼴 lost_members)을 묘비 꼴(0.3)로. 할 일이 없으면 입력 그대로."""
    out, _rep = idmap.upgrade(node_set)
    if out.get("schema_version") != SCHEMA:
        out = dict(out if out is not node_set else copy.deepcopy(node_set), schema_version=SCHEMA)
    return out


def with_refs(node_set, graph):
    """판이 같은 집합을 묘비 꼴로 바꾸고, 판 사진이나 확정·잠금 구간의 지문(md3-)이 모자라면 채운 사본. 할 일이 없으면
    입력 그대로. 묘비를 만들지 않는다(읽기만으로 구성요소를 잃지 않음)."""
    if not _usable(node_set, graph) or node_set.get("graph_version") != graph["graph_version"]:
        return node_set
    out = _upgrade(node_set)
    have = out.get("member_digest") or {}
    todo = {n["node_id"]: n["members"] for n in out["nodes"]  # 적용됨 구간은 지문이 없어도 됨(판이 바뀌면 rev만 오름)
            if n.get("state") in ("confirmed", "locked") and not str(have.get(n["node_id"]) or "").startswith("md3-")}
    fresh = node_digests(graph, todo) if todo else {}
    if out is node_set and not fresh and idmap.has_snapshot(node_set, graph):
        return node_set
    out = copy.deepcopy(out)
    out.update(idmap.snapshot(graph))
    out["member_digest"] = dict(have, **fresh)
    return out


def plan(node_set, graph):
    """{"state": "same"|"kept"|"skip", "reason", "matched", "table"(idmap.compute), "recheck"{node_id: 사유}}.
    kept는 판 이전을 적용한다는 뜻이고 재확인은 recheck에 든 구간만이다. skip은 0.2·0.3 집합이 아니거나 그래프를 비교할 수
    없는 것."""
    out = {"state": "skip", "reason": None, "matched": 0, "table": None, "recheck": {}}
    if not _usable(node_set, graph):
        return out
    if node_set.get("graph_version") == graph["graph_version"]:
        return dict(out, state="same")
    ns = _upgrade(node_set)
    table = idmap.compute(ns, graph)
    eid = table["eid"]
    recorded = ns.get("member_digest") or {}
    legacy = (ns.get("legacy") or {}).get("member_digest")
    legacy_same = bool(legacy) and digest_matches(legacy, graph)
    moved = {n["node_id"]: [eid.get(m, m) for m in n["members"]] for n in ns["nodes"]}
    old_refs = ns.get("graph_member_refs") or {}
    names = {e: old_refs[m] for m, e in eid.items() if not idmap.is_tomb(e) and old_refs.get(m)}
    fresh = node_digests(graph, {k: v for k, v in moved.items() if not any(idmap.is_tomb(x) for x in v)}, names)
    recheck = {}
    for n in ns["nodes"]:
        nid = n["node_id"]
        gone = sorted(m for m, x in zip(n["members"], moved[nid]) if idmap.is_tomb(x))
        back = [t for t in n.get("lost") or [] if t in table["found"]]
        rec = str(recorded.get(nid) or "")
        if gone:
            recheck[nid] = "새 판에서 찾지 못한 구성요소 %d개(%s)" % (
                len(gone), ", ".join(idmap.describe(ns, m) for m in gone[:3]))
        elif back:
            recheck[nid] = "잃었던 구성요소 %d개를 같은 자리에서 되찾음" % len(back)
        elif rec.startswith("md3-"):
            if rec != fresh.get(nid):
                recheck[nid] = "구성요소의 종류·태그·흐름·연결·정상 위치·고장 위치가 바뀜"
        elif not legacy_same and n.get("state") in ("confirmed", "locked"):
            recheck[nid] = "옛 판의 구간 내용 기록이 없음"  # 확정한 적 없는 적용됨 구간은 분석 전이라 판만 옮김
    members = {m for n in ns["nodes"] for m in n["members"]}
    matched = sum(1 for m in members if not idmap.is_tomb(eid.get(m, m)))
    return dict(out, state="kept", matched=matched, table=table, recheck=recheck)


def migrate_set(node_set, graph, at=None):
    """(집합, plan). 판 이전을 적용한 사본 또는 입력 그대로. 재확인 구간은 rev가 오르고, 확정이면 적용됨으로 내리며,
    잠금이면 잠금을 두고 version_changed를 단다. 이미 적용됨인 구간도 구성요소 ID는 새 판으로 바뀐다."""
    p = plan(node_set, graph)
    if p["state"] != "kept":
        return node_set, p
    from hazop.study.nodes import now_utc
    at = at or now_utc()
    table = p["table"]
    out, rep = idmap.apply(_upgrade(node_set), idmap.SET, table)
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
    tombs = dict(out.get("tombstones") or {})
    for t, rec in table["new_tombs"].items():  # 새 묘비 id는 있는 것을 건너뛰고 지었으므로 앞 기록을 덮지 않는다
        tombs[t] = dict(rec, at=at)
    out["tomb_seq"] = table["tomb_seq"]
    for t, (e, r) in table["found"].items():
        tombs[t] = dict(tombs.get(t) or {}, found={"entity_id": e, "ref": r, "version": graph["graph_version"], "at": at})
    out["tombstones"] = dict(sorted(tombs.items()))
    out["graph_version"] = graph["graph_version"]
    out.update(idmap.snapshot(graph))
    out["member_digest"] = node_digests(graph, {n["node_id"]: n["members"] for n in out["nodes"]})
    if (out.get("legacy") or {}).get("member_digest"):  # 한 번 이어 쓴 뒤로는 구간 지문만 쓴다
        out["legacy"] = dict(out["legacy"], member_digest=None)
    out["set_rev"] = (out.get("set_rev") or 0) + 1
    detail = {"from": old_version, "to": graph["graph_version"], "matched": p["matched"], "step": len(lines(out)) + 1}
    detail.update(idmap.record(table))
    detail.update(unregistered=rep["unregistered"], recheck=dict(sorted(p["recheck"].items())), demoted=demoted)
    out["history"].append(store_io.history_row(OP, {"detail": detail}, at))
    return out, p


def lines(node_set):
    """집합 이력의 판 이전 줄 detail(차례대로). 줄 번호(step)는 이 목록의 1부터 센 자리다(이력은 지우지 않음)."""
    return [h.get("detail") or {} for h in node_set.get("history") or [] if isinstance(h, dict) and h.get("op") == OP]


def _chained(rows, start):
    cur = start
    for d in rows:
        if d.get("from") != cur:
            return False
        cur = d.get("to")
    return True


def _steps(results, node_set):
    """(결과에 아직 적용하지 않은 판 이전 줄들, 마지막 줄 번호). 결과가 지금 판이면 ([], None), 이어지지 않으면 None.
    결과가 마지막으로 옮겨진 줄 번호(version_migrations[-1].step, 그 줄의 to가 결과의 판일 때)가 있으면 그 뒤 줄들이다.
    번호가 없는 결과(새로 만든 것, 옛 판이 옮긴 것)는 결과의 판에서 시작하는 마지막 줄부터다. 판 문자열은 내용 해시라
    같은 판이면 같은 그래프이고, 그 사이의 되돌아감(A→B→A)을 거치지 않아도 참조가 같은 기호를 가리킨다."""
    rows = lines(node_set)
    have, want = results.get("graph_version"), node_set.get("graph_version")
    marks = [m for m in results.get("version_migrations") or [] if isinstance(m, dict)]
    step = marks[-1].get("step") if marks else None
    done = type(step) is int and 1 <= step <= len(rows) and rows[step - 1].get("to") == have
    if done and _chained(rows[step:], have) and (rows[step:] or have == want):
        return rows[step:], len(rows)
    if have == want:
        return [], None
    starts = [i for i, d in enumerate(rows) if d.get("from") == have and _chained(rows[i:], have)]
    if not starts or rows[-1].get("to") != want:
        return None
    return rows[starts[-1]:], len(rows)


def migrate_results(results, node_set, at=None, table=None):
    """(결과, 바꾼 근거 경로 ID 수 또는 None). 0.2·0.3 결과의 판과 등록된 id 필드(원인·영향·보호수단 참조, 잠재 후보 ID,
    근거 경로)를 판 이전 대응대로 지금 판으로 바꾼 사본. 적용할 줄은 _steps가 고르고(결과가 마지막으로 옮겨진 줄 번호 뒤),
    그 줄이 table(방금 계산한 대응표) 하나면 그 표를, 아니면 이력 줄에서 만든 표를 차례로 적용한다. 옮긴 마지막 줄 번호를
    version_migrations[].step에 적는다. 판이 같거나 이어지는 기록이 없으면 None이고,
    49033f1 판의 `~lost`만 묘비로 바꾼 사본(바꿀 것이 없으면 입력 그대로)을 돌려준다. 0.1 결과는 legacy_migrate_results로."""
    if results.get("schema_version") not in ("0.2", "0.3"):  # results.CELL_SCHEMA_VERSIONS(순환 import를 피해 값으로)
        return legacy_migrate_results(results, node_set, at)
    doc, _n = idmap.upgrade_results(results, node_set)
    found = _steps(doc, node_set)
    if not found or not found[0]:
        return doc, None
    steps, step = found
    if table is not None and len(steps) == 1 and (table["from"], table["to"]) == (steps[0].get("from"), steps[0].get("to")):
        tables = [table]  # 방금 계산한 표(이력 줄과 같은 표)
    else:
        tables = [idmap.from_record(d, node_set.get("graph_id")) for d in steps]
    from hazop.study.nodes import now_utc
    total = {"changed": 0, "lost": 0, "found": 0}
    kg = {"changed": 0, "lost": 0}
    unregistered = set()
    for t in tables:
        doc, rep = idmap.apply(doc, idmap.RESULTS, t)
        for k in total:
            total[k] += rep[k]
        for k in kg:
            kg[k] += rep["spaces"].get(idmap.EID, {}).get(k, 0)
        unregistered.update(rep["unregistered"])
    old_version = doc.get("graph_version")
    doc["graph_version"] = node_set["graph_version"]
    doc.setdefault("version_migrations", []).append({
        "at": at or now_utc(), "from": old_version, "to": node_set["graph_version"],
        "kg_path_ids_changed": kg["changed"] - kg["lost"], "kg_path_ids_unmapped": kg["lost"],
        "refs_changed": total["changed"] - total["lost"] - total["found"], "refs_lost": total["lost"],
        "refs_found": total["found"],
        # 표시 없이 참조만 믿고 이은 옛 판 이전이 끼어 있으면 화면이 확인을 띄울 근거(idmap.needs_check)
        "check": "ref" if any(t["check"] == "ref" for t in tables) else "mark",
        "unregistered": sorted(unregistered), "step": step})
    return doc, kg["changed"] - kg["lost"]


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
    옛 꼴을 바꾸거나 참조를 채우거나 판을 이전했으면 옛 파일을 백업한 뒤 읽은 파일 자리에 원자적으로 쓰고(실패하면 원본
    그대로 두고 읽은 집합을 돌려줌), ⑤ 결과 파일도 같은 대응표로 옮겨 쓴다. 쓸 일이 없으면 아무것도 쓰지 않는다.
    읽은 뒤 파일이 바뀌었으면 쓰지 않는다."""
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
    rpath = res._readable_path(out.get("project_id"), out["graph_id"])
    try:
        doc, rfp = res.read_fp(rpath)
    except (OSError, ValueError):  # 읽지 못하는 결과는 그대로 두고 화면이 지금처럼 문제로 보여 준다
        doc = None
    if doc is not None and doc.get("graph_id") == out["graph_id"] and doc.get("schema_version") in ("0.2", "0.3"):
        moved, _n = migrate_results(doc, out, table=p["table"])
        if moved is not doc:
            try:
                store_io.backup_file(rpath, BACKUP_LABEL)
                res.write(rpath, moved, expect=rfp)
            except (OSError, store_io.Conflict) as exc:  # 결과 파일은 다음에 읽을 때 results.load가 메모리에서 다시 이전한다
                _log.warning("분석 결과 판 이전을 저장하지 못함: %s (%s)", rpath, exc)
    return out, fp
