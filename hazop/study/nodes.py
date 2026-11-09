"""④ 검토구간 집합(StudyNodeSet): 자동 제안·편집·확정·저장. 근거: 3단계 명세 §B nodes.py.

도면 그래프(graph.json) 하나당 집합 하나. 구성요소 = graph nodes 전부(배관 구간 포함).
프로젝트 그래프(hazop.graph.project)를 넣으면 도면 경계를 넘는 프로젝트 전체 집합이 된다. 도면 연결점(continuation)과
도면 연결 구간은 배관 경로 요소라 경로가 이어진 도면까지 한 구간에 든다. 도면별 저장본은 그대로 따로 읽힌다.
편집 연산은 모두 순수 함수다. 입력을 바꾸지 않고 새 dict를 돌려주며 history에 한 줄 덧붙인다.
확정된 집합은 reopen 뒤에만 고칠 수 있다.
"""

import copy
import hashlib
import json
import math
import os
from collections import deque
from datetime import datetime, timezone

from hazop import paths
from hazop.graph.project import LEGACY_PROJECT_DIR, UNREGISTERED_PROJECT

SCHEMA_VERSION = "0.1"
KIND = "hazop_study_nodes"
MAX_ACTIVE = 5
PROPOSER = {"name": "hazop.study.nodes", "version": "0.1.0", "max_active": MAX_ACTIVE}
PHYSICAL_EDGES = ("has_endpoint",)
INSTRUMENT_EDGES = ("measurement_connection", "signal_connection")
OTHER_NAME = "기타"


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_active(node):
    """능동 요소: 밸브(category valve) 또는 펌프(kind에 pump)."""
    return node.get("category") == "valve" or "pump" in (node.get("kind") or "")


def _role(node):
    category = node.get("category")
    if category in ("equipment", "instrument"):
        return category
    return "process"


def _adjacency(graph, kinds):
    adj = {}
    for e in graph.get("edges", []):
        if e.get("kind") not in kinds:
            continue
        a, b = e["nodes"]
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return {k: sorted(v) for k, v in adj.items()}


def _label(node):
    first_line = (node.get("label_text") or "").split("\n")[0].strip()
    return node.get("tag") or first_line or node.get("kind") or node["entity_id"]


def _path_name(chunk, nodes, adj):
    """대표 배관 번호 + 경계 기기 태그. 같은 배관 번호의 짧은 경로가 여럿일 때 경계 기기로 구분된다."""
    lines = sorted({nodes[e].get("line_no") for e in chunk if nodes[e].get("line_no")})
    names = lines or sorted({nodes[e]["tag"] for e in chunk if nodes[e].get("tag")}) or [chunk[0]]
    name = "배관 " + names[0] + (" 외 %d" % (len(names) - 1) if len(names) > 1 else "")
    bounds = sorted({_label(nodes[n]) for e in chunk for n in adj.get(e, ()) if _role(nodes[n]) == "equipment"})
    if bounds:
        name += " (%s)" % "·".join(bounds[:2] + (["외 %d" % (len(bounds) - 2)] if len(bounds) > 2 else []))
    return name


def _bfs(start, adj, allowed):
    order, seen, queue = [], {start}, deque([start])
    while queue:
        cur = queue.popleft()
        order.append(cur)
        for nxt in adj.get(cur, ()):
            if nxt not in seen and nxt in allowed:
                seen.add(nxt)
                queue.append(nxt)
    return order


def _chunk_by_active(order, nodes, max_active):
    chunks, count = [[]], 0
    for eid in order:
        if is_active(nodes[eid]):
            if count == max_active:
                chunks.append([])
                count = 0
            count += 1
        chunks[-1].append(eid)
    return chunks


def _instrument_target(eid, adj, nodes, group_of):
    """계측·신호(및 물리) 연결을 계기끼리만 따라가며, 가장 가까운 홉의 비계기 요소 중 구간 번호가 가장 작은 것."""
    seen, layer = {eid}, [eid]
    while layer:
        found, nxt_layer = [], []
        for cur in layer:
            for nxt in adj.get(cur, ()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                if nxt in group_of:
                    found.append(group_of[nxt])
                elif _role(nodes[nxt]) == "instrument":
                    nxt_layer.append(nxt)
        if found:
            return min(found)
        layer = nxt_layer
    return None


def _position_target(eid, nodes, groups):
    pos = nodes[eid].get("position")
    if not pos:
        return None
    best = None
    for i, g in enumerate(groups):
        for m in g["core"]:
            p = nodes[m].get("position")
            if p and nodes[m].get("sheet") == nodes[eid].get("sheet"):  # 위치는 같은 도면 안에서만 비교
                cand = (math.hypot(p[0] - pos[0], p[1] - pos[1]), i)
                best = cand if best is None or cand < best else best
    return None if best is None else best[1]


def propose(graph, at=None, max_active=MAX_ACTIVE):
    """그래프에서 검토구간을 제안한다(status=proposed). 모든 구성요소가 한 구간 이상에 든다.

    1. 주요 기기(category equipment)는 각자 구간 하나.
    2. 기기·계기를 뺀 공정 요소의 물리 연결 성분 = 배관 경로. 기기에서 끊어 설계의도 변화 경계를 근사한다.
    3. 경로의 능동 요소가 max_active개를 넘으면 BFS 순서대로 max_active개씩 나눈다.
    4. 계기·제어기는 연결된 요소의 구간에, 없으면 위치가 가장 가까운 구간에, 그래도 없으면 '기타' 구간에 붙는다.
    구간 순서는 핵심 구성요소의 가장 작은 entity_id 순이다.
    """
    nodes = {n["entity_id"]: n for n in graph.get("nodes", [])}
    role = {eid: _role(n) for eid, n in nodes.items()}
    phys = _adjacency(graph, PHYSICAL_EDGES)
    groups = []
    for eid in sorted(nodes):
        if role[eid] == "equipment":
            n = nodes[eid]
            groups.append({"core": [eid], "name": _label(n),
                           "basis": "주요 기기 경계: %s(%s)" % (_label(n), n.get("kind") or "-")})
    process = {eid for eid in nodes if role[eid] == "process"}
    seen = set()
    for eid in sorted(process):
        if eid in seen:
            continue
        order = _bfs(eid, phys, process)
        seen.update(order)
        chunks = _chunk_by_active(order, nodes, max_active)
        for i, chunk in enumerate(chunks):
            active = sum(is_active(nodes[e]) for e in chunk)
            if len(chunks) == 1:
                name, basis = _path_name(chunk, nodes, phys), "기기 사이 배관 경로(능동 요소 %d개)" % active
            else:
                name = "%s (%d/%d)" % (_path_name(chunk, nodes, phys), i + 1, len(chunks))
                basis = "능동 요소 %d개 초과 경로를 연결 순서대로 나눔 %d/%d(능동 요소 %d개)" % (
                    max_active, i + 1, len(chunks), active)
            groups.append({"core": chunk, "name": name, "basis": basis})
    groups.sort(key=lambda g: min(g["core"]))
    group_of = {}
    for i, g in enumerate(groups):
        g["members"] = list(g["core"])
        for eid in g["core"]:
            group_of.setdefault(eid, i)
    links = _adjacency(graph, PHYSICAL_EDGES + INSTRUMENT_EDGES)
    other = []
    for eid in sorted(e for e in nodes if role[e] == "instrument"):
        target = _instrument_target(eid, links, nodes, group_of)
        if target is None:
            target = _position_target(eid, nodes, groups)
        if target is None:
            other.append(eid)
        else:
            groups[target]["members"].append(eid)
    if other:
        groups.append({"members": other, "name": OTHER_NAME, "basis": "연결·위치로 붙일 구간이 없는 계기"})
    out_nodes = [{"node_id": "S%d" % (i + 1), "name": g["name"], "origin": "rule", "basis": g["basis"],
                  "members": sorted(set(g["members"]))} for i, g in enumerate(groups)]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "project_id": graph.get("project_id"),
        "graph_id": graph.get("graph_id"),
        "graph_version": graph.get("graph_version"),
        "drawing_number": (graph.get("source") or {}).get("drawing_number"),
        "status": "proposed",
        "proposer": dict(PROPOSER, max_active=max_active),
        "nodes": out_nodes,
        "confirmed_at": None,
        "confirmed_by": None,
        "history": [{"at": at or now_utc(), "op": "propose",
                     "detail": {"nodes": len(out_nodes), "components": len(nodes)}}],
    }


# ---------------------------------------------------------------- 조회

def coverage(node_set, graph):
    ids = {n["entity_id"] for n in graph.get("nodes", [])}
    members = {m for n in node_set["nodes"] for m in n["members"]}
    uncovered = sorted(ids - members)
    total = len(ids)
    covered = total - len(uncovered)
    return {"total": total, "covered": covered, "uncovered": uncovered, "ratio": covered / total if total else 1.0}


def nodes_of(node_set, entity_id):
    return [n["node_id"] for n in node_set["nodes"] if entity_id in n["members"]]


def is_stale(node_set, graph):
    """저장본을 만든 그래프 판과 현재 그래프 판이 다르면 True(화면이 경고로 보여 준다)."""
    return node_set.get("graph_version") != graph.get("graph_version")


# ---------------------------------------------------------------- 편집(순수 함수)

def _begin(node_set):
    if node_set.get("status") == "confirmed":
        raise ValueError("확정된 검토구간은 reopen 뒤에 고칠 수 있음")
    return copy.deepcopy(node_set)


def _log(node_set, op, detail, at):
    node_set["history"].append({"at": at or now_utc(), "op": op, "detail": detail})
    return node_set


def _find(node_set, node_id):
    for n in node_set["nodes"]:
        if n["node_id"] == node_id:
            return n
    raise ValueError("없는 검토구간: %s" % node_id)


def _next_id(node_set):
    used = [int(n["node_id"][1:]) for n in node_set["nodes"] if n["node_id"][1:].isdigit()]
    return "S%d" % (max(used, default=0) + 1)


def merge(node_set, node_ids, at=None):
    """여러 구간을 하나로 합친다. 집합 안 순서로 첫 구간의 node_id를 남긴다."""
    out = _begin(node_set)
    wanted = set(node_ids)
    if len(wanted) < 2:
        raise ValueError("병합에는 서로 다른 구간 2개 이상 필요")
    for nid in wanted:
        _find(out, nid)
    picked = [n for n in out["nodes"] if n["node_id"] in wanted]
    keep = picked[0]
    keep.update({
        "name": "%s 외 %d" % (keep["name"], len(picked) - 1),
        "origin": "merged",
        "basis": "%s 병합" % "·".join(n["node_id"] for n in picked),
        "members": sorted({m for n in picked for m in n["members"]}),
    })
    out["nodes"] = [n for n in out["nodes"] if n is keep or n["node_id"] not in wanted]
    return _log(out, "merge", {"node_ids": [n["node_id"] for n in picked], "into": keep["node_id"]}, at)


def split(node_set, node_id, members_for_new, name=None, at=None):
    """구간 node_id에서 members_for_new를 떼어 새 구간(바로 뒤)으로 만든다."""
    out = _begin(node_set)
    src = _find(out, node_id)
    moved = sorted(set(members_for_new))
    if not moved:
        raise ValueError("새 구간에 넣을 구성요소가 없음")
    if not set(moved) < set(src["members"]):
        raise ValueError("떼어 낼 구성요소는 %s 구성요소의 일부(전부 아님)여야 함" % node_id)
    new = {"node_id": _next_id(out), "name": name or src["name"] + " 분할", "origin": "split",
           "basis": "%s에서 나눔" % node_id, "members": moved}
    src["members"] = sorted(set(src["members"]) - set(moved))
    out["nodes"].insert(out["nodes"].index(src) + 1, new)
    return _log(out, "split", {"node_id": node_id, "new_node_id": new["node_id"], "members": moved}, at)


def rename(node_set, node_id, name, at=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("빈 이름")
    out = _begin(node_set)
    node = _find(out, node_id)
    old, node["name"] = node["name"], name
    return _log(out, "rename", {"node_id": node_id, "from": old, "to": name}, at)


def add_member(node_set, node_id, entity_id, at=None):
    out = _begin(node_set)
    node = _find(out, node_id)
    if entity_id in node["members"]:
        raise ValueError("%s는 이미 %s에 있음" % (entity_id, node_id))
    node["members"] = sorted(node["members"] + [entity_id])
    return _log(out, "add", {"node_id": node_id, "entity_id": entity_id}, at)


def remove_member(node_set, node_id, entity_id, at=None):
    out = _begin(node_set)
    node = _find(out, node_id)
    if entity_id not in node["members"]:
        raise ValueError("%s는 %s에 없음" % (entity_id, node_id))
    node["members"] = [m for m in node["members"] if m != entity_id]
    return _log(out, "remove", {"node_id": node_id, "entity_id": entity_id}, at)


def confirm(node_set, graph, reviewer, at=None):
    """확정. 그래프 판이 다르거나, 구간이 없거나, 빈 구간·그래프에 없는 구성요소·미포함 구성요소가 있으면 ValueError."""
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("검토자 이름 필요")
    out = _begin(node_set)
    if is_stale(out, graph):
        raise ValueError("그래프 판이 바뀜(%s -> %s): 검토구간을 다시 확인해야 함"
                         % (out.get("graph_version"), graph.get("graph_version")))
    if not out["nodes"]:
        raise ValueError("검토구간이 없음")
    empty = [n["node_id"] for n in out["nodes"] if not n["members"]]
    if empty:
        raise ValueError("빈 구간: %s" % ", ".join(empty))
    ids = {n["entity_id"] for n in graph.get("nodes", [])}
    unknown = sorted({m for n in out["nodes"] for m in n["members"]} - ids)
    if unknown:
        raise ValueError("그래프에 없는 구성요소 %d개: %s" % (len(unknown), ", ".join(unknown[:5])))
    cov = coverage(out, graph)
    if cov["uncovered"]:
        raise ValueError("어느 구간에도 없는 구성요소 %d개: %s"
                         % (len(cov["uncovered"]), ", ".join(cov["uncovered"][:5])))
    out.update({"status": "confirmed", "confirmed_at": at or now_utc(), "confirmed_by": reviewer})
    from hazop.study import migrate
    out.update(member_refs=migrate.member_refs(out, graph), member_digest=migrate.member_digest(graph))
    return _log(out, "confirm", {"reviewer": reviewer, "nodes": len(out["nodes"])}, out["confirmed_at"])


def reopen(node_set, at=None):
    if node_set.get("status") != "confirmed":
        raise ValueError("확정되지 않은 검토구간")
    out = copy.deepcopy(node_set)
    detail = {"confirmed_at": out["confirmed_at"], "confirmed_by": out["confirmed_by"]}
    out.update({"status": "proposed", "confirmed_at": None, "confirmed_by": None})
    return _log(out, "reopen", detail, at)


# ---------------------------------------------------------------- 저장

def store_dir():
    return paths.folder("검토구간")


def store_path(project_id, graph_id):
    return os.path.join(store_dir(), paths.safe_name(project_id or UNREGISTERED_PROJECT),
                        paths.safe_name(graph_id) + ".json")


def _readable_path(project_id, graph_id):
    """저장 경로. 없고 project_id가 없으면 이 규칙 이전 폴더(no-project)의 저장본을 그대로 읽는다(옮기지 않음)."""
    path = store_path(project_id, graph_id)
    legacy = os.path.join(store_dir(), LEGACY_PROJECT_DIR, paths.safe_name(graph_id) + ".json")
    return legacy if not project_id and not os.path.isfile(path) and os.path.isfile(legacy) else path


class Conflict(ValueError):
    """읽은 뒤 다른 창·프로그램이 저장 파일을 바꿔서 저장하지 않음."""


ANY = object()


def fingerprint(path):
    """파일 내용의 SHA-256. 파일이 없으면 None."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        return None


def save(node_set, expect=ANY):
    """임시 파일에 쓴 뒤 os.replace로 교체한다. 쓴 경로를 돌려준다.
    expect(fingerprint 값)를 주면 지금 파일이 그 값과 다를 때 쓰지 않고 Conflict를 낸다."""
    path = store_path(node_set.get("project_id"), node_set["graph_id"])
    if expect is not ANY and fingerprint(path) != expect:
        raise Conflict("읽은 뒤 저장 파일이 바뀜: %s" % path)
    return write(path, node_set)


def write(path, node_set):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(node_set, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def load(graph):
    """graph의 저장본. 없으면 None. 판 비교는 is_stale로 한다.
    확정본은 읽을 때 판 이전(hazop.study.migrate)을 적용한다. 그래프는 등록·수정·화면 열기 등 여러 길에서 다시 만들어지고
    모두 이 함수로 저장본을 읽으므로, 여기서 한 번 적용하면 어느 길로 판이 바뀌어도 확정 작업이 같은 규칙으로 이어진다."""
    path = _readable_path(graph.get("project_id"), graph.get("graph_id"))
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8-sig") as fh:  # 메모장 등이 붙인 BOM도 읽는다
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError("검토구간 파일이 아님: %s" % path)
    _check_shape(doc, path)
    from hazop.study import migrate
    return migrate.on_load(doc, graph, path)


def _check_shape(doc, path):
    """판 이전·화면이 가리지 않고 꺼내 쓰는 값이 제 모양인지 본다. 아니면 ValueError(화면은 경고와 함께 새로 제안한다)."""
    ok = (isinstance(doc.get("graph_id"), str) and isinstance(doc.get("status"), str)
          and isinstance(doc.get("history"), list) and isinstance(doc.get("nodes"), list)
          and all(isinstance(n, dict) and isinstance(n.get("node_id"), str) and isinstance(n.get("name"), str)
                  and isinstance(n.get("members"), list) for n in doc["nodes"]))
    if not ok:
        raise ValueError("검토구간 파일 형식이 맞지 않음: %s" % path)


def any_confirmed(project_only=False):
    """작업 루트 아래 확정된 집합이 하나라도 있으면 True(레일 ✓ 표시용). 읽을 수 없는 파일은 확정이 아닌 것으로 본다.
    project_only면 프로젝트 전체 집합(graph_id "project-…")만 센다(옛 도면별 확정본은 화면이 쓰지 않음)."""
    root = store_dir()
    if not os.path.isdir(root):
        return False
    for project in sorted(os.listdir(root)):
        folder = os.path.join(root, project)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), encoding="utf-8-sig") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                continue
            if project_only and not str((doc or {}).get("graph_id") or "").startswith("project-"):
                continue
            if isinstance(doc, dict) and doc.get("kind") == KIND and doc.get("status") == "confirmed":
                return True
    return False
