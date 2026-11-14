"""구간을 묶음 하나로 바꾸는 앱 함수(Qt 없음). 근거: docs/specs/study-node-segmentation.md §2.3, §4.4, §6.2.

- apply_nodes: 채팅의 제안 동작(node.create·update·merge·split·remove)과 도면에서 고르기가 부른다. ops 전체를 묶음(B<번호>)
  하나로 적용하거나, 하나라도 규칙에 걸리면 아무것도 바꾸지 않고 ValueError(무엇이 왜인지 목록)를 낸다.
- undo_batch: 묶음 하나를 되돌린다. op마다 '구간 삭제'(add 되돌림)·'편집 복원'(edit 되돌림)·'되살림'(remove 되돌림)을
  구분하고, 그 사이 바뀐 구간·확정 구간·사람 판정이 있는 칸·AI가 사람 묶음을 되돌리는 경우를 막는다. 되돌리기도 새 묶음이다.
- 두 함수 모두 ⑤ 결과를 받는다(병합·삭제의 칸 처리와 되돌리기의 칸 검사). 결과가 없으면 None을 넘긴다(칸이 없는 상태).
- AI가 부르는 읽기 도구(§6.2, 채팅 규격 §3.2): find_major_equipment·make_candidates·outside_components. 집합을 바꾸지
  않고, 결과에 상한과 쪽 나누기(cursor)가 있다. make_candidates는 분할 스크립트(segment.cut)를 크기 매개변수(§7)로 돌린
  후보이고, cand_id는 (그래프 판, 매개변수 지문, 구성요소 집합)의 해시라 같은 입력이면 같다. 같은 (판, 매개변수, 범위)면
  분할 결과를 캐시해 쪽을 넘길 때 다시 자르지 않는다.
- 구간 만들기의 누적 상한(채팅 규격 §4.5): 사람이 아직 확인하지 않은 AI 구간(pending_ai)과 이번 요청의 새 구간을 합쳐
  5개까지는 바로 적용(대표 단계). 넘으면 '나머지' 단계로, 대표 구간을 만든 메시지와 다른 새 사용자 메시지(user_turn)에서
  사람이 확인 상자를 눌렀을 때(confirmed_rest)만 한 요청 30개까지 적용하고, 그때 앞의 AI 묶음은 확인된 것(human_seen)이 된다.
  요청 하나는 묶음 하나다(같은 request_id로 두 번 적용하지 않음).
"""

import copy
import hashlib
import json
import os
import time

from hazop import paths, store_io
from hazop.study import nodes, segment
from hazop.study import results as res
from hazop.study.node_review import TAG_LIKE, drawing_tags

REPRESENTATIVE_LIMIT = 5
REST_LIMIT = 30
CANDIDATE_LIMIT = 30       # make_candidates 한 쪽 상한
LIST_LIMIT = 200           # find_major_equipment·outside_components 한 쪽 상한
GRANULARITIES = ("coarse", "normal", "fine")
SKIP_OVERLAP = 0.8         # skip_existing: 후보 구성요소의 80%를 넘게 품은 구간이 있으면 뺌
GRADE_ORDER = {"주요": 0, "일반": 1, "낮음": 2, None: 3}
OPS = ("add", "edit", "merge", "split", "remove")
_CACHE = {}
_CACHE_SIZE = 8
MAX_HOPS = 30              # scope around의 hops 상한
CAND_PARAMS_TTL = 24 * 3600  # 후보 매개변수 기록을 믿는 시간(초). 지나면 후보를 다시 찾게 한다


class Refused(ValueError):
    """규칙에 걸린 요청. reasons는 [(대상, 이유)]."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join("%s: %s" % r for r in self.reasons))


# ---------------------------------------------------------------- 읽기 도구

def clear_cache():
    _CACHE.clear()


def _page(items, limit, cursor, cap):
    limit = max(1, min(int(limit or cap), cap))
    start = int(cursor or 0)
    chunk = items[start:start + limit]
    return chunk, (str(start + limit) if start + limit < len(items) else None)


def _params(granularity, extra_boundaries=(), cut_at=()):
    if granularity not in GRANULARITIES:
        raise ValueError("granularity는 %s 가운데 하나" % "·".join(GRANULARITIES))
    return segment.Params(granularity=granularity, extra_boundaries=frozenset(extra_boundaries or ()),
                          cut_at=frozenset(cut_at or ()))


def _digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=sorted).encode("utf-8")).hexdigest()


def _drawing_of(pg):
    by_sheet = {s["graph_id"]: s.get("drawing_number") or s["graph_id"] for s in pg.get("sheets") or []}
    fallback = (pg.get("source") or {}).get("drawing_number") or pg.get("graph_id")
    return lambda n: by_sheet.get(n.get("sheet")) or (fallback if not by_sheet else None)


def scope_ids(pg, node_set, scope):
    """scope(§6.2)가 고르는 구성요소 ID 집합. None이면 None(전체). 모르는 키면 ValueError.
    {"drawings": [도면번호]}, {"system": 태그·배관 번호 접두}, {"around": entity_id, "hops": n}, {"node_ids": [..]}."""
    if not scope:
        return None
    if not isinstance(scope, dict) or len(scope) - ("hops" in scope) != 1:
        raise ValueError("scope는 drawings·system·around(+hops)·node_ids 가운데 하나")
    by_id = {n["entity_id"]: n for n in pg["nodes"]}
    if "drawings" in scope:
        want = {project_key(d) for d in scope["drawings"]}
        draw = _drawing_of(pg)
        return {e for e, n in by_id.items() if project_key(draw(n)) in want}
    if "system" in scope:
        head = str(scope["system"]).strip().upper()
        return {e for e, n in by_id.items()
                if any(str(n.get(k) or "").upper().startswith(head) for k in ("tag", "line_no"))}
    if "around" in scope:
        start, hops = scope["around"], int(scope.get("hops") or 2)
        if not 0 <= hops <= MAX_HOPS:
            raise ValueError("hops는 0~%d" % MAX_HOPS)
        if start not in by_id:
            raise ValueError("그래프에 없는 구성요소: %s" % start)
        adj = {}
        for e in pg.get("edges", []):
            ends = e.get("nodes") or []
            if len(ends) == 2:
                adj.setdefault(ends[0], set()).add(ends[1])
                adj.setdefault(ends[1], set()).add(ends[0])
        seen, frontier = {start}, {start}
        for _ in range(max(0, hops)):
            frontier = {y for x in frontier for y in adj.get(x, ())} - seen
            seen |= frontier
        return seen
    if "node_ids" in scope:
        want = set(scope["node_ids"])
        return {m for n in (node_set or {}).get("nodes") or [] if n["node_id"] in want for m in n["members"]}
    raise ValueError("모르는 scope: %s" % ", ".join(sorted(scope)))


def project_key(text):
    from hazop.study.nodes import drawing_key
    return drawing_key(text)


def _subgraph(pg, ids):
    if ids is None:
        return pg
    return dict(pg, nodes=[n for n in pg["nodes"] if n["entity_id"] in ids],
                edges=[e for e in pg.get("edges", []) if all(x in ids for x in e.get("nodes") or [])])


def _item(n, draw):
    return {"entity_id": n["entity_id"], "tag": n.get("tag") or None, "kind": n.get("kind"), "drawing": draw(n)}


def find_major_equipment(pg, scope=None, granularity="normal", extra_boundaries=(), limit=100, cursor=None):
    """주요 장비(§7.1). {"items": [{entity_id, tag, kind, part, drawing}], "unrecognized_equipment": int,
    "total", "truncated", "next_cursor"}. unrecognized_equipment는 기기 분류인데 kind를 몰라 경계가 안 되는 수."""
    params = _params(granularity, extra_boundaries)
    ids = scope_ids(pg, None, scope)
    draw = _drawing_of(pg)
    found, unknown = [], 0
    for n in sorted(pg["nodes"], key=lambda n: n["entity_id"]):
        if ids is not None and n["entity_id"] not in ids:
            continue
        part = segment.part_of(n)
        if part is segment.Part.INSTRUMENT:
            continue
        if params.is_boundary(n, part):
            found.append(dict(_item(n, draw), part=part.value))
        elif n.get("category") == "equipment" and (n.get("kind") or "") not in segment.EQUIPMENT_PART:
            unknown += 1
    items, nxt = _page(found, limit, cursor, LIST_LIMIT)
    return {"items": items, "unrecognized_equipment": unknown, "total": len(found), "truncated": nxt is not None,
            "next_cursor": nxt}


def _params_path(pg, digest):
    """후보 매개변수 기록 자리: <작업 루트>/data/study-nodes/<프로젝트>/candidates/<digest>.json."""
    from hazop.graph.project import UNREGISTERED_PROJECT
    return os.path.join(nodes.store_dir(), paths.safe_name(pg.get("project_id") or UNREGISTERED_PROJECT),
                        "candidates", digest + ".json")


def _remember_params(pg, digest, scope, params):
    """후보를 만든 매개변수를 작업 루트에 남긴다(후보를 만든 프로세스와 적용하는 프로세스가 달라도 cand_id로 다시 만들게).
    원자적으로 쓰고, 같은 내용이면 다시 쓰지 않는다. 쓰지 못해도 후보는 돌려준다(같은 프로세스 캐시로는 풀림)."""
    record = {"kind": "hazop_node_candidate_params", "graph_id": pg.get("graph_id"),
              "graph_version": pg.get("graph_version"), "digest": digest, "at": time.time(), "scope": scope,
              "params": {"granularity": params.granularity, "extra_boundaries": sorted(params.extra_boundaries),
                         "cut_at": sorted(params.cut_at)}}
    path = _params_path(pg, digest)
    try:
        old = _read_params(path)
        if old and {k: v for k, v in old.items() if k != "at"} == {k: v for k, v in record.items() if k != "at"} \
                and time.time() - old.get("at", 0) < CAND_PARAMS_TTL / 2:
            return
        store_io.write_json(path, record)
    except OSError:
        pass


def _read_params(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("kind") == "hazop_node_candidate_params" else None


def _all_candidates(pg, scope, params):
    """[후보(겹침·건너뛰기 전)]와 params_digest. 같은 (판, 매개변수, 범위)면 캐시."""
    sheets, _problem = nodes.exclusion_for(pg)
    digest = _digest({"granularity": params.granularity, "extra": sorted(params.extra_boundaries),
                      "cut_at": sorted(params.cut_at), "scope": scope, "excluded": sorted(sheets)})[:16]
    _remember_params(pg, digest, scope, params)
    key = (pg.get("graph_id"), pg.get("graph_version"), digest)
    if key in _CACHE:
        return _CACHE[key], digest
    ids = scope_ids(pg, None, scope) if not (scope or {}).get("node_ids") else None
    sub = _subgraph(pg, ids)
    by_id = {n["entity_id"]: n for n in pg["nodes"]}
    draw = _drawing_of(pg)
    bound = {e for e, n in by_id.items() if segment.part_of(n) is not segment.Part.INSTRUMENT
             and params.is_boundary(n, segment.part_of(n))}
    adj = {}
    for e in pg.get("edges", []):
        if e.get("kind") in segment.PHYSICAL_EDGES and len(e.get("nodes") or []) == 2:
            a, b = e["nodes"]
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    out = []
    for s in segment.cut(sub, sheets, params):
        if not isinstance(s, segment.Kept):
            continue
        members = list(s.members)
        majors = sorted({x for m in members for x in ({m} | adj.get(m, set())) if x in bound},
                        key=lambda x: (by_id[x].get("tag") or "", x))
        ends = [{"tag": by_id[x].get("tag"), "entity_id": x} for x in majors]
        parts = [segment.part_of(by_id[m]) for m in members]
        out.append({
            "cand_id": "c-%s-%s" % (digest, _digest([pg.get("graph_version"), digest, sorted(members)])[:12]),
            "member_count": len(members), "members": members,
            "start": ends[0] if ends else None, "end": ends[-1] if ends else None,
            "majors": [by_id[x].get("tag") or by_id[x].get("kind") for x in majors],
            "valves": sum(p is segment.Part.VALVE for p in parts),
            "instruments": sum(p is segment.Part.INSTRUMENT for p in parts),
            "drawings": sorted({draw(by_id[m]) for m in members if draw(by_id[m])}),
            "grade": s.grade, "score": s.score, "basis": s.head.basis, "name": s.head.name})
    out.sort(key=lambda c: (GRADE_ORDER.get(c["grade"], 3), -(c["score"] or 0), c["members"][0]))
    if len(_CACHE) >= _CACHE_SIZE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = out
    return out, digest


def _candidate_list(pg, node_set, scope, params, skip_existing):
    every, digest = _all_candidates(pg, scope, params)
    want = scope_ids(pg, node_set, scope) if (scope or {}).get("node_ids") else None
    owners = {}
    order = {}
    for i, n in enumerate((node_set or {}).get("nodes") or []):
        order[n["node_id"]] = i
        for m in n["members"]:
            owners.setdefault(m, []).append(n["node_id"])
    out = []
    for c in every:
        if want is not None and not set(c["members"]) <= want:
            continue
        mine = set(c["members"])
        shared = {}
        for m in mine:  # 구성요소 → 구간 색인으로 센다(구간이 많아도 후보 크기만큼만 돎)
            for nid in owners.get(m, ()):
                shared[nid] = shared.get(nid, 0) + 1
        overlaps = [{"node_id": nid, "shared": k} for nid, k in sorted(shared.items(), key=lambda x: order[x[0]])]
        if skip_existing and any(o["shared"] / len(mine) > SKIP_OVERLAP for o in overlaps):
            continue
        out.append(dict(c, overlaps=overlaps))
    return out, digest


def make_candidates(pg, node_set, scope=None, granularity="normal", extra_boundaries=(), cut_at=(),
                    skip_existing=True, limit=CANDIDATE_LIMIT, cursor=None):
    """주요 장비에서 주요 장비까지 후보 구간(§6.2). 등급 순(주요 → 일반 → 낮음), 같은 등급은 점수 순.
    {"candidates": [{cand_id, member_count, start, end, majors, valves, instruments, drawings, grade, score, overlaps,
    basis}], "outside": {"count", "sources"}, "total", "next_cursor", "params_digest", "set_rev"}."""
    params = _params(granularity, extra_boundaries, cut_at)
    cands, digest = _candidate_list(pg, node_set, scope, params, skip_existing)
    page, nxt = _page(cands, limit, cursor, CANDIDATE_LIMIT)
    keys = ("cand_id", "member_count", "start", "end", "majors", "valves", "instruments", "drawings", "grade",
            "score", "overlaps", "basis")
    outside = outside_components(pg, node_set, scope, only_sources=False, limit=1)
    return {"candidates": [{k: c[k] for k in keys} for c in page],
            "outside": {"count": outside["count"], "sources": outside["sources"]}, "total": len(cands),
            "next_cursor": nxt, "params_digest": digest, "set_rev": (node_set or {}).get("set_rev")}


def resolve_candidate(pg, node_set, cand_id, params=None):
    """cand_id의 구성요소와 후보(이름·basis). 순서: 이 프로세스의 캐시 → cand_id에 든 매개변수 지문으로 작업 루트의
    기록(다른 프로세스가 만든 후보, 같은 그래프 판·24시간 안)을 읽어 다시 만듦 → params로 다시 만듦.
    찾지 못하면 None(그래프 판이 바뀌었거나 매개변수가 다르거나 기록이 지남)."""
    for (gid, ver, _d), cands in list(_CACHE.items()):
        if gid == pg.get("graph_id") and ver == pg.get("graph_version"):
            hit = next((c for c in cands if c["cand_id"] == cand_id), None)
            if hit is not None:
                return hit
    parts = str(cand_id).split("-")
    if len(parts) == 3 and parts[0] == "c":
        rec = _read_params(_params_path(pg, parts[1]))
        if rec and rec.get("graph_id") == pg.get("graph_id") and rec.get("graph_version") == pg.get("graph_version") \
                and time.time() - float(rec.get("at") or 0) < CAND_PARAMS_TTL:
            p = rec["params"]
            cands, _d = _all_candidates(pg, rec.get("scope"), _params(p["granularity"], p.get("extra_boundaries"),
                                                                       p.get("cut_at")))
            hit = next((c for c in cands if c["cand_id"] == cand_id), None)
            if hit is not None:
                return hit
    if params:
        p = _params(params.get("granularity", "normal"), params.get("extra_boundaries"), params.get("cut_at"))
        cands, _d = _all_candidates(pg, params.get("scope"), p)
        return next((c for c in cands if c["cand_id"] == cand_id), None)
    return None


def outside_components(pg, node_set, scope=None, only_sources=True, limit=100, cursor=None):
    """구간 밖 구성요소(어느 구간에도 들지 않음). {"items": [{entity_id, tag, kind, drawing}], "count", "sources",
    "next_cursor"}. sources는 그 가운데 편차원(기기·밸브·인라인·계기) 수."""
    ids = scope_ids(pg, node_set, scope)
    inside = {m for n in (node_set or {}).get("nodes") or [] for m in n["members"]}
    draw = _drawing_of(pg)
    left = [n for n in sorted(pg["nodes"], key=lambda n: n["entity_id"])
            if n["entity_id"] not in inside and (ids is None or n["entity_id"] in ids)]
    sources = [n for n in left if segment.is_source(n)]
    shown = sources if only_sources else left
    items, nxt = _page([_item(n, draw) for n in shown], limit, cursor, LIST_LIMIT)
    return {"items": items, "count": len(shown), "sources": len(sources), "next_cursor": nxt}


# ---------------------------------------------------------------- 누적 상한(채팅 규격 §4.5)

def pending_ai(node_set):
    """사람이 아직 확인하지 않은 AI 구간 수: origin ai·적용됨이고, 지금 구간을 만든 묶음이 AI 묶음이며 human_seen이 아님.
    사람이 고치면 구간의 batch_id가 사람 묶음으로 바뀌어 빠지고, 확정하면 적용됨이 아니라 빠진다."""
    batches = {b["batch_id"]: b for b in node_set.get("batches") or []}
    out = 0
    for n in node_set["nodes"]:
        b = batches.get(n.get("batch_id"))
        if n.get("origin") == "ai" and nodes.node_state(n) == "applied" and b and b.get("origin") == "ai" \
                and not b.get("human_seen"):
            out += 1
    return out


def _pending_turns(node_set):
    batches = {b["batch_id"]: b for b in node_set.get("batches") or []}
    return {batches[n["batch_id"]].get("user_turn") for n in node_set["nodes"]
            if n.get("origin") == "ai" and nodes.node_state(n) == "applied" and n.get("batch_id") in batches
            and batches[n["batch_id"]].get("origin") == "ai" and not batches[n["batch_id"]].get("human_seen")}


def _node(ns, nid):
    return next((n for n in ns["nodes"] if n["node_id"] == nid), None)


def _cells_of(results, nid):
    return [c for c in (results or {}).get("cells") or [] if c.get("node_id") == nid]


def _has_entries(results, nid):
    return any(c.get("entries") for c in _cells_of(results, nid))


def _has_human(results, nid):
    return any(e.get("status") in res.HUMAN_STATUSES for c in _cells_of(results, nid) for e in c.get("entries") or [])


def _move_cells(results, src, dst, at):
    """src 구간 칸의 항목을 dst 구간의 같은 item_id 칸으로 옮기고 '범위 바뀜'을 붙인다(§4.4 병합). src 칸은 지운다.
    dst 칸이 없으면 src 칸 모양으로 만든다. 옮긴 칸의 원래 상태는 dst 칸의 legacy_cells에 남긴다."""
    out = copy.deepcopy(results)
    dst_cells = {c.get("item_id"): c for c in out["cells"] if c.get("node_id") == dst["node_id"]}
    keep = []
    for c in out["cells"]:
        if c.get("node_id") != src["node_id"]:
            keep.append(c)
            continue
        target = dst_cells.get(c.get("item_id"))
        if target is None:
            target = dict(c, node_id=dst["node_id"], entries=[], state="not_analyzed", node_rev=dst.get("rev") or 1)
            target.pop("ai_run", None)
            keep.append(target)
            dst_cells[c.get("item_id")] = target
        if not c.get("entries") and c.get("state") == "not_analyzed":
            continue
        target.setdefault("legacy_cells", []).append({"from": src["node_id"], "deviation_id": c.get("deviation_id"),
                                                      "state": c.get("state"), "ai_run": c.get("ai_run")})
        for e in c.get("entries") or []:
            target["entries"].append(dict(copy.deepcopy(e), scope_changed={
                "from_rev": c.get("node_rev") or 1, "to_rev": dst.get("rev") or 1, "at": at, "merged_from": src["node_id"]}))
        if target["entries"]:
            target["state"] = "analyzed"
    out["cells"] = keep
    return out


def _archive_cells(results, nid, reason, by, at):
    out = copy.deepcopy(results)
    moved = [c for c in out["cells"] if c.get("node_id") == nid]
    out["cells"] = [c for c in out["cells"] if c.get("node_id") != nid]
    out.setdefault("archived_cells", [])
    out["archived_cells"] += [{"cell": c, "reason": reason, "at": at, "by": by}
                              for c in moved if c.get("entries") or c.get("state") != "not_analyzed"]
    return out


def _tag_problems(texts, tags):
    missing = sorted({t for text in texts if text for t in TAG_LIKE.findall(text) if t not in tags})
    return "도면에 없는 태그: %s" % ", ".join(missing[:5]) if missing else None


def apply_nodes(node_set, results, pg, ops, request, origin, set_rev, at=None, by=None):
    """(새 집합, 새 결과, batch_id). 바뀐 것이 없으면(빼려는 구성요소가 없음, 같은 이름 등) (받은 집합, 받은 결과, None).
    ops 형식은 §6.2. request: {request_id, request_text, stage}. origin: "ai"|"user".
    거절하면 Refused(ValueError). 결과(results)는 바꾸지 않으면 받은 것 그대로 돌려준다."""
    if origin not in ("ai", "user"):
        raise Refused([("origin", "ai 또는 user")])
    if set_rev != node_set.get("set_rev"):
        raise Refused([("set_rev", "구간이 그 사이 바뀜(읽은 판 %s, 지금 %s)" % (set_rev, node_set.get("set_rev")))])
    if not ops:
        raise Refused([("ops", "할 일이 없음")])
    at = at or nodes.now_utc()
    request = dict(request or {})
    ai = origin == "ai"
    confirmed_by = (request.get("confirmed_by") or "").strip() if ai else None  # AI가 쓴 동작을 사람이 확인 상자로 눌렀는가
    graph_ids = {n["entity_id"] for n in pg.get("nodes", [])}
    tags = drawing_tags(pg) if ai else None
    out = copy.deepcopy(node_set)
    out_res = results
    why = []
    adds = 0

    def changeable(nid, kind, target_label=None):
        n = _node(out, nid)
        label = target_label or nid
        if n is None:
            why.append((label, "없는 구간"))
            return None
        if nodes.node_state(n) == "locked":
            why.append((label, "잠긴 구간은 %s할 수 없음" % kind))
            return None
        if nodes.is_active(n):
            why.append((label, "확정 구간은 %s할 수 없음(사람이 확정을 해제한 뒤)" % kind))
            return None
        if ai and n.get("origin") != "ai" and not confirmed_by:
            why.append((label, "AI가 사람·옛 규칙 구간을 %s하려면 사람이 확인해야 함(채팅 규격 §4.3)" % kind))
            return None
        return n

    def members_ok(label, members):
        if not members:
            why.append((label, "빈 구간"))
            return False
        unknown = sorted(set(members) - graph_ids)
        if unknown:
            why.append((label, "그래프에 없는 구성요소 %d개(%s)" % (len(unknown), ", ".join(unknown[:3]))))
            return False
        return True

    for i, op in enumerate(ops):
        kind = op.get("op")
        label = "%d번째 %s" % (i + 1, kind)
        if kind not in OPS:
            why.append((label, "모르는 동작"))
            continue
        if kind in ("merge", "split", "remove") and out_res is None:
            why.append((label, "⑤ 결과 없이 병합·분할·삭제할 수 없음(칸 검사가 필요함. 결과가 없으면 빈 결과를 넘길 것)"))
            continue
        if ai:
            bad = _tag_problems([op.get("name"), op.get("design_intent"), op.get("basis")], tags)
            if bad:
                why.append((label, bad))
                continue
        if kind == "add":
            cand = None
            if op.get("cand_id"):
                cand = resolve_candidate(pg, node_set, op["cand_id"], op.get("params") or request.get("params"))
                if cand is None:
                    why.append((label, "후보 %s를 다시 만들 수 없음(그래프 판이나 매개변수가 바뀜. 후보를 다시 찾을 것)"
                                % op["cand_id"]))
                    continue
            members = sorted(set(cand["members"] if cand else op.get("members") or []))
            if not members_ok(label, members):
                continue
            name = (op.get("name") or "").strip()
            if not name:
                why.append((label, "이름 없음"))
                continue
            node = dict({"node_id": nodes._next_id(out), "name": name,
                         "basis": op.get("basis") or (cand or {}).get("basis"), "members": members},
                        **nodes._v2_fields(origin))
            if cand:
                node["cand_id"] = op["cand_id"]
            if (op.get("design_intent") or "").strip():
                node["design_intent"] = {"text": op["design_intent"].strip(), "by": origin}
            out["nodes"].append(node)
            adds += 1
        elif kind == "edit":
            n = changeable(op.get("node_id"), "편집", label)
            if n is None:
                continue
            if op.get("name") is not None:
                if not op["name"].strip():
                    why.append((label, "빈 이름"))
                    continue
                if ai and n.get("name_by") == "user" and not confirmed_by:
                    why.append((label, "사람이 쓴 이름은 AI가 바꾸지 못함"))
                    continue
                if op["name"].strip() != n["name"]:  # 같은 이름이면 고친 것이 아님(쓴 쪽도 그대로)
                    n["name"], n["name_by"] = op["name"].strip(), origin
            if op.get("design_intent") is not None:
                if ai and (n.get("design_intent") or {}).get("by") == "user" and not confirmed_by:
                    why.append((label, "사람이 쓴 설계 의도는 AI가 바꾸지 못함"))
                    continue
                text = op["design_intent"].strip()
                if text != (nodes.intent_text(n) or ""):
                    n["design_intent"] = {"text": text, "by": origin} if text else None
            members = sorted((set(n["members"]) | set(op.get("add") or [])) - set(op.get("remove") or []))
            if not members_ok(label, members):
                continue
            n["members"] = members
        elif kind == "merge":
            ids = list(dict.fromkeys(op.get("node_ids") or []))
            if len(ids) < 2:
                why.append((label, "병합에는 서로 다른 구간 2개 이상 필요"))
                continue
            picked = [changeable(nid, "병합", "%s(%s)" % (label, nid)) for nid in ids]
            if None in picked:
                continue
            if ai and any(_has_entries(out_res, nid) for nid in ids):
                why.append((label, "칸에 항목이 있는 구간의 병합은 사람만 함(§4.4)"))
                continue
            if len({nodes.screen_excluded(n) for n in picked}) > 1:   # 합치면 사람의 제외 판정이 말없이 사라지거나 다른 구성요소에 붙는다
                why.append((label, "분석에서 제외한 구간과 넣은 구간은 합칠 수 없음(먼저 다시 넣거나 함께 제외)"))
                continue
            keep = picked[0]
            keep["members"] = sorted({m for n in picked for m in n["members"]})
            keep["name_by"] = keep.get("name_by") or origin
            for n in picked[1:]:
                if out_res is not None:
                    out_res = _move_cells(out_res, n, keep, at)
            out["nodes"] = [n for n in out["nodes"] if n is keep or n["node_id"] not in ids]
        elif kind == "split":
            n = changeable(op.get("node_id"), "분할", label)
            if n is None:
                continue
            moved = sorted(set(op.get("members") or []))
            if not moved or not set(moved) < set(n["members"]):
                why.append((label, "떼어 낼 구성요소는 그 구간 구성요소의 일부(전부 아님)여야 함"))
                continue
            if ai and _has_entries(out_res, n["node_id"]):
                why.append((label, "칸에 항목이 있는 구간의 분할은 사람만 함(§4.4)"))
                continue
            new = dict({"node_id": nodes._next_id(out), "name": (op.get("name") or n["name"] + " 분할").strip(),
                        "basis": "%s에서 나눔" % n["node_id"], "members": moved}, **nodes._v2_fields(origin))
            if nodes.screen_excluded(n):   # 떼어 낸 조각도 사람이 제외한 범위 안이다(말없이 분석에 다시 들어가지 않게)
                new["screen"] = copy.deepcopy(n["screen"])
            n["members"] = sorted(set(n["members"]) - set(moved))
            out["nodes"].insert(out["nodes"].index(n) + 1, new)
        elif kind == "remove":
            n = changeable(op.get("node_id"), "삭제", label)
            if n is None:
                continue
            if judged(out_res, n["node_id"]):
                if ai or not op.get("archive"):
                    why.append((label, "칸에 판정이 있는 구간은 지울 수 없음(옮길 구간을 고르거나 '보관'을 고를 것, 사람만)"))
                    continue
                out_res = _archive_cells(out_res, n["node_id"], "node_removed", by, at)
            elif out_res is not None and _cells_of(out_res, n["node_id"]):
                out_res = dict(out_res, cells=[c for c in out_res["cells"] if c.get("node_id") != n["node_id"]])
            out["nodes"] = [x for x in out["nodes"] if x is not n]
    adds = len({n["node_id"] for n in out["nodes"]} - {n["node_id"] for n in node_set["nodes"]})  # 분할로 생긴 구간도 셈
    seen_rest = False
    if ai:
        rid = request.get("request_id")
        if rid and any(b.get("request_id") == rid for b in node_set.get("batches") or []):
            why.append(("요청", "요청 하나는 묶음 하나(같은 요청 %s로 이미 적용함)" % rid))
        pending = pending_ai(node_set)
        if adds and pending + adds > REPRESENTATIVE_LIMIT:
            turn = request.get("user_turn")
            if not (request.get("confirmed_rest") and confirmed_by):
                why.append(("요청", "확인하지 않은 AI 구간 %d개 + 이번 %d개가 %d개를 넘음: 사람이 확인 상자를 눌러야 함"
                            % (pending, adds, REPRESENTATIVE_LIMIT)))
            elif not turn or turn in _pending_turns(node_set):
                why.append(("요청", "'나머지'는 대표 구간을 본 뒤의 새 사용자 메시지에서만 함(같은 메시지 안에서 이어 만들지 않음)"))
            elif adds > REST_LIMIT:
                why.append(("요청", "한 요청에서 만들 수 있는 구간은 %d개, 요청은 %d개" % (REST_LIMIT, adds)))
            else:
                seen_rest = True
    seen = {}
    for n in out["nodes"]:
        key = frozenset(n["members"])
        if key in seen:
            why.append((n["node_id"], "구성요소가 같은 구간 %s가 이미 있음" % seen[key]))
        seen.setdefault(key, n["node_id"])
    if why:
        raise Refused(why)
    if not nodes.batch_ops(node_set, out):  # 바뀐 것이 없음: 묶음·판(set_rev)·이력을 건드리지 않고 묶음 ID 없이 돌려줌
        return node_set, results, None
    if seen_rest:  # 확인 상자를 눌렀으므로 앞의 AI 묶음은 사람이 본 것
        for b in out.get("batches") or []:
            if b.get("origin") == "ai" and not b.get("human_seen"):
                b["human_seen"] = {"at": at, "by": confirmed_by}
    out = nodes._record_batch(node_set, out, "apply", origin, at, request=request,
                              tool=request.get("tool"), model=request.get("model"))
    out["history"].append(nodes.store_io.history_row("apply", {"detail": {
        "batch_id": out["batches"][-1]["batch_id"], "origin": origin, "ops": len(ops)}}, at))
    return out, out_res, out["batches"][-1]["batch_id"]


def judged(results, nid):
    """그 구간 칸 가운데 사람·AI 판정이 남은 것이 있는지(항목이 있거나 칸 상태가 분석 전이 아님)."""
    return any(c.get("entries") or c.get("state") not in (None, "not_analyzed") for c in _cells_of(results, nid))


def judged_nodes(results):
    """⑤ 결과에서 판정이 남은 칸이 있는 구간 ID(정렬). 다시 제안(S1부터 새로 매김)을 막을지 정할 때 쓴다: 판정은 구간 ID로
    붙어 있어, ID를 새로 매기면 '해당 없음' 같은 판정이 구성요소가 다른 새 구간에 붙는다(총괄 검토 R7)."""
    return sorted({c.get("node_id") for c in (results or {}).get("cells") or []
                   if isinstance(c, dict) and (c.get("entries") or c.get("state") not in (None, "not_analyzed"))},
                  key=lambda x: (len(str(x)), str(x)))


def dropped_problems(before, after, results):
    """편집(before → after)으로 사라진 구간 가운데 ⑤ 칸에 판정이 있는 것 [(구간, 이유)]. 결과를 옮기지 않는 편집 경로
    (④의 nodes.merge·remove_member·remove_empty, AI 제안 받아들이기, 다시 제안)가 저장 전에 부른다(규격 §4.4).
    results가 None이면 확인할 수 없으므로 사라진 구간마다 문제로 본다."""
    gone = [n["node_id"] for n in before["nodes"] if n["node_id"] not in {x["node_id"] for x in after["nodes"]}]
    if results is None:
        return [(nid, "⑤ 결과를 읽지 못해 칸을 확인할 수 없음") for nid in gone]
    return [(nid, "⑤ 칸에 판정이 있음(병합은 결과를 옮기는 길로, 삭제는 보관을 골라야 함)") for nid in gone if judged(results, nid)]


def undo_problems(node_set, results, batch_id, requested_by):
    """묶음을 되돌릴 수 없는 이유 [(구간, 이유)] (§2.3). 빈 목록이면 되돌릴 수 있다."""
    b = next((x for x in node_set.get("batches") or [] if x["batch_id"] == batch_id), None)
    if b is None:
        return [(batch_id, "없는 묶음(되돌릴 수 있는 최근 %d개 밖)" % nodes.BATCH_KEEP)]
    if b.get("undone"):
        return [(batch_id, "이미 되돌린 묶음")]
    out = []
    if requested_by == "ai" and b.get("origin") != "ai":
        out.append((batch_id, "AI는 AI가 만든 묶음만 되돌림"))
    for o in b["ops"]:
        nid = o["node_id"]
        cur = _node(node_set, nid)
        expect = o["after"]
        if requested_by == "ai" and nodes.ever_confirmed(node_set, nid):
            out.append((nid, "사람이 확정한 적 있는 구간이라 AI 되돌리기로 지우거나 바꾸지 않음(사람이 ④에서 되돌림)"))
            continue
        if cur is not None and nodes.is_active(cur):
            out.append((nid, "확정·잠금 구간(사람이 확정을 먼저 해제해야 함)"))
            continue
        if (cur is None) != (expect is None) or (cur is not None and cur != expect):
            out.append((nid, "그 사이 바뀜(뒤 묶음이나 사람이 고침. 뒤 묶음부터 되돌릴 것)"))
            continue
        if o["op"] == "add" and judged(results, nid):
            out.append((nid, "구간 삭제인데 칸에 판정이 있음(옮길 곳 또는 보관을 사람이 고를 것)"))
        elif o["op"] == "edit" and nodes.analysis_input(o["before"]) != nodes.analysis_input(cur) \
                and _has_human(results, nid):
            out.append((nid, "편집 복원으로 분석 판이 바뀌는데 칸에 사람 판정 항목이 있음"))
        elif o["op"] == "remove" and _node(node_set, nid) is not None:
            out.append((nid, "같은 ID의 구간이 이미 있음"))
    return out


def undo_batch(node_set, results, batch_id, set_rev, by, requested_by, at=None):
    """(새 집합, 새 결과). results가 None이면 칸 검사를 할 수 없어 거절한다(§2.3). 막으면 Refused."""
    if results is None:
        raise Refused([(batch_id, "⑤ 결과 없이 되돌릴 수 없음(칸 검사가 필요함. 결과가 없으면 빈 결과를 넘길 것)")])
    if requested_by not in ("ai", "user"):
        raise Refused([("requested_by", "ai 또는 user")])
    if set_rev != node_set.get("set_rev"):
        raise Refused([("set_rev", "구간이 그 사이 바뀜(읽은 판 %s, 지금 %s)" % (set_rev, node_set.get("set_rev")))])
    why = undo_problems(node_set, results, batch_id, requested_by)
    if why:
        raise Refused(why)
    at = at or nodes.now_utc()
    b = next(x for x in node_set["batches"] if x["batch_id"] == batch_id)
    out = copy.deepcopy(node_set)
    out_res = results
    for o in reversed(b["ops"]):
        nid = o["node_id"]
        if o["op"] == "add":
            out["nodes"] = [n for n in out["nodes"] if n["node_id"] != nid]
            if _cells_of(out_res, nid):
                out_res = dict(out_res, cells=[c for c in out_res["cells"] if c.get("node_id") != nid])
        elif o["op"] == "edit":
            restored = copy.deepcopy(o["before"])
            restored["state"], restored["confirmed"] = "applied", None
            out["nodes"] = [restored if n["node_id"] == nid else n for n in out["nodes"]]
        else:
            restored = copy.deepcopy(o["before"])
            restored["state"], restored["confirmed"], restored["locked"] = "applied", None, None
            out["nodes"].insert(min(o.get("index", len(out["nodes"])), len(out["nodes"])), restored)
    bid_before = node_set
    out = nodes._record_batch(bid_before, out, "undo", requested_by, at, request={"request_text": None})
    new_bid = out["batches"][-1]["batch_id"] if out["batches"] and out["batches"][-1]["kind"] == "undo" else None
    for x in out["batches"]:
        if x["batch_id"] == batch_id:
            x["undone"] = {"at": at, "by": by, "batch_id": new_bid}
    out["history"].append(nodes.store_io.history_row("undo_batch", {"detail": {
        "batch_id": batch_id, "undo_batch_id": new_bid, "by": by, "requested_by": requested_by}}, at))
    return out, out_res
