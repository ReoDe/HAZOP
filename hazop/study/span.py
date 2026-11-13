"""여러 도면에 걸친 검토구간의 표기·경계·조회·이전. 근거: 사용자 결정(2026-11-07, 총괄 전달) 표기 규칙.

- 구간 ID는 프로젝트 그래프(hazop.graph.project)에서 제안한 S1…Sn 그대로다. 어느 도면에서 보든 같다.
- 표시 이름 "S7 <이름> [101 → 102]": 괄호 안은 프로젝트 공통 접두를 뺀 짧은 도면번호를 흐름 순서대로 쓴다.
- annotate는 순수 함수다. 집합을 고친 뒤(병합·분할 등)에는 다시 부른다. 같은 입력이면 같은 결과.
- 이전(migrate_*)은 도면별 저장본을 바꾸지 않고 새 문서만 만든다. 옛 ID(graph_id:S#)를 legacy_ids로 남기고,
  범위가 정확히 같지 않은 구간에서 옮긴 항목에는 scope_changed를 붙여 사람이 다시 보게 한다(상태는 그대로).
"""

import copy
import os
import pickle
import re

from hazop.graph import project

PHYSICAL = "has_endpoint"


# ---------------------------------------------------------------- 도면번호

def short_numbers(drawing_numbers):
    """(공통 접두, {도면번호: 짧은 번호}). 접두는 구분자('-'·'_'·' ')까지만 자른다. 한 장뿐이면 마지막 구분자까지."""
    dns = sorted({d for d in drawing_numbers if d})
    if not dns:
        return "", {}
    common = os.path.commonprefix(dns) if len(dns) > 1 else dns[0]
    cut = max(common.rfind(c) for c in "-_ ") + 1
    prefix = common[:cut]
    return prefix, {d: d[len(prefix):] or d for d in dns}


def _sheet_of(pg):
    dn = {s["graph_id"]: s["drawing_number"] for s in pg["sheets"]}
    return {n["entity_id"]: dn.get(n.get("sheet")) for n in pg["nodes"]}


def _flow_order(drawings, pg, members):
    """구간 안 도면을 이은 연결(TO→FROM)의 위상 순서. 순환·방향 미확인은 도면번호순으로 채운다."""
    edges = set()
    for l in pg["sheet_links"]:
        if l["status"] == project.LINKED and l["flow_known"] and l["link_id"] in members:
            a, b = l["from"]["drawing_number"], l["to"]["drawing_number"]
            if a in drawings and b in drawings and a != b:
                edges.add((a, b))
    order, left = [], sorted(drawings)
    while left:
        ready = [d for d in left if not any(b == d and a in left for a, b in edges)]
        pick = ready[0] if ready else left[0]
        order.append(pick)
        left.remove(pick)
    return order


# ---------------------------------------------------------------- 표기·경계

def _segment_ends(pg):
    """{배관 구간 ID: 그 구간의 물리 간선 목록}. 키는 간선 순서대로 처음 나온 차례다."""
    seg_ends = {}
    for e in pg["edges"]:
        if e["kind"] == PHYSICAL:
            seg_ends.setdefault(e["segment"], []).append(e)
    return seg_ends


EMPTY_NODE = "구성요소 없음"


def _boundaries(node, by_id, drawing_of, node_of, seg_ends, seg_rank, segs_of):
    """(start, end, continuations). 경계 = 구간 밖 주요 기기·미연결 연결점으로 이어지는 배관 구간의 끝.
    seg_ends·seg_rank는 annotate가 한 번 만든 색인이다(구간마다 전체 간선을 다시 훑지 않게). 구간 순서는 간선 순서 그대로."""
    if not node["members"]:  # 빈 구간(옛 저장본에 있을 수 있다): 경계도 도면 연결도 없다
        return None, None, []
    members = set(node["members"])
    starts, ends, unknown = [], [], []

    def item(eid):
        n = by_id[eid]
        first = (n.get("label_text") or "").split("\n")[0].strip()
        return {"entity_id": eid, "label": n.get("tag") or first or n.get("kind"), "drawing": drawing_of.get(eid)}

    for seg in sorted((m for m in members if m in seg_ends), key=seg_rank.get):
        outs = [e for e in seg_ends[seg] if e["node"] not in members]
        if not outs:
            continue
        for e in outs:
            o = by_id[e["node"]]
            if o.get("category") != "equipment" and o.get("kind") != "continuation":
                continue
            fd = by_id[seg].get("flow_direction") or {}
            bucket = starts if fd.get("from") == e["node"] else ends if fd.get("to") == e["node"] else unknown
            bucket.append(item(e["node"]))
    for eid in node["members"]:
        n = by_id.get(eid) or {}
        if n.get("kind") == "continuation" and (n.get("sheet_link") or {}).get("status") != project.LINKED:
            unknown.append(dict(item(eid), note="미연결 도면 연결점"))
    key = (lambda x: (x["drawing"] or "", x["label"] or ""))
    starts, ends, unknown = sorted(starts, key=key), sorted(ends, key=key), sorted(unknown, key=key)
    equipment = [m for m in node["members"] if (by_id.get(m) or {}).get("category") == "equipment"]
    if not starts and not ends and not unknown and equipment:  # 기기 구간: 경계는 그 기기
        only = item(equipment[0])
        return only, only, []
    start = starts[0] if starts else (unknown.pop(0) if unknown else None)
    end = ends[-1] if ends else (unknown.pop() if unknown else None)
    if equipment and (start is None) != (end is None):
        # 기기와 그 출구 배관을 한 구간에 묶으면(스크리닝 R2) 안쪽 기기가 한쪽 경계다. 배관은 상류 기기에 붙으므로
        # 흐름상 시작이 밖에서 보이지 않았으면 안쪽 기기가 시작이고, 밖의 경계는 끝으로 옮긴다
        inside = item(equipment[0])
        if start is not None and not starts:
            start, end = inside, start
        elif start is None:
            start = inside
        else:
            end = inside
    if (start is None) != (end is None):
        # 긴 경로를 크기 예산으로 나눈 조각: 경계 기기가 한쪽에만 있으면 나눈 자리(이웃 구간과 맞닿은 요소)를 다른 쪽 경계로 쓴다
        cut = sorted({x for seg in members if seg in seg_ends for x in (e["node"] for e in seg_ends[seg]) if x not in members}
                     | {seg for m in members for seg in segs_of.get(m, ()) if seg not in members})
        if cut:
            nxt = cut[0]
            mark = dict(item(nxt), note="구간 나눔" + ("(%s)" % ", ".join(node_of[nxt]) if node_of.get(nxt) else ""))
            start, end = (mark, end) if start is None else (start, mark)
    if start is None and end is None:  # 경계 기기 없이 배관 요소만 남은 구간: 태그 있는 첫 구성요소로 설명
        first = next((m for m in node["members"] if (by_id.get(m) or {}).get("tag")), node["members"][0])
        start = end = dict(item(first), note="경계 기기 없음")
    conts = []
    for eid in node["members"]:
        link = (by_id.get(eid) or {}).get("sheet_link") or {}
        if link.get("status") == project.LINKED and link.get("peer"):
            conts.append({"entity_id": eid, "drawing": drawing_of.get(eid), "to_drawing": drawing_of.get(link["peer"]),
                          "to_node_ids": node_of.get(link["peer"], [])})
    return start, end, sorted(conts, key=lambda c: (c["drawing"] or "", c["entity_id"]))


def annotate(node_set, pg):
    """표기·경계 정보를 붙인 집합 사본. 구간마다:
    display_name, drawings(흐름 순서 전체 번호), drawings_short, spans_drawings, members_by_drawing{번호: 수},
    member_count, boundary{start, end}(각 {entity_id, label, drawing}), continuations[{entity_id, drawing,
    to_drawing, to_node_ids}](화면 칩 "S7 → SNP-M-101에서 계속"). 집합 위에 drawing_numbers·drawing_prefix·drawing_short."""
    out = pickle.loads(pickle.dumps(node_set, pickle.HIGHEST_PROTOCOL))  # JSON 값이라 deepcopy와 같은 사본, 몇 배 빠름
    by_id = {n["entity_id"]: n for n in pg["nodes"]}
    drawing_of = _sheet_of(pg)
    prefix, short = short_numbers([s["drawing_number"] for s in pg["sheets"]])
    seg_ends = _segment_ends(pg)
    seg_rank = {seg: i for i, seg in enumerate(seg_ends)}
    segs_of = {}
    for seg, es in seg_ends.items():
        for e in es:
            segs_of.setdefault(e["node"], []).append(seg)
    node_of = {}
    for n in out["nodes"]:
        for m in n["members"]:
            node_of.setdefault(m, []).append(n["node_id"])
    for n in out["nodes"]:
        counts = {}
        for m in n["members"]:
            if drawing_of.get(m):
                counts[drawing_of[m]] = counts.get(drawing_of[m], 0) + 1
        drawings = _flow_order(set(counts), pg, set(n["members"]))
        start, end, conts = _boundaries(n, by_id, drawing_of, node_of, seg_ends, seg_rank, segs_of)
        n.update({
            "drawings": drawings, "drawings_short": [short.get(d, d) for d in drawings],
            "spans_drawings": len(drawings) > 1, "members_by_drawing": dict(sorted(counts.items())),
            "member_count": len(n["members"]),
            "display_name": "%s %s [%s]" % (n["node_id"], n["name"], " → ".join(short.get(d, d) for d in drawings)
                                            if n["members"] else EMPTY_NODE),
            "boundary": {"start": start, "end": end}, "continuations": conts,
        })
    out.update({"drawing_numbers": [s["drawing_number"] for s in pg["sheets"]], "drawing_prefix": prefix,
                "drawing_short": short})
    return out


def continuation_chip(node_id, cont):
    """화면 칩 문구. 상대 쪽 구간 ID를 모두 적는다(겹친 구간이면 "S7·S9 → 102에서 계속"). 상대가 없으면 이 구간 ID."""
    targets = cont["to_node_ids"] or [node_id]
    return "%s → %s에서 계속" % ("·".join(targets), cont["to_drawing"])


# ---------------------------------------------------------------- 조회

def nodes_on_drawing(annotated, drawing_number):
    """그 도면을 지나는 구간(걸친 구간 포함), 집합 순서."""
    return [n for n in annotated["nodes"] if drawing_number in n.get("drawings", ())]


def coverage_by_drawing(node_set, pg):
    """{"project": {covered, total, ratio, outside}, "drawings": {번호: {…}}}. outside는 구간 밖 구성요소 수(표시용,
    확정·⑤를 막지 않음). 도면 연결 구간은 프로젝트에만."""
    drawing_of = _sheet_of(pg)
    covered = {m for n in node_set["nodes"] for m in n["members"]}

    def cov(ids):
        c = sum(1 for i in ids if i in covered)
        return {"covered": c, "total": len(ids), "ratio": c / len(ids) if ids else 1.0, "outside": len(ids) - c}
    every = [n["entity_id"] for n in pg["nodes"]]
    per = {}
    for i in every:
        if drawing_of.get(i):
            per.setdefault(drawing_of[i], []).append(i)
    return {"project": cov(every), "drawings": {d: cov(ids) for d, ids in sorted(per.items())}}


def worksheet_header(node):
    """⑤ 워크시트 머리말 값: 전체 도면번호(흐름 순서)와 시작·끝 경계."""
    b = node.get("boundary") or {}

    def text(x):
        return None if not x else "%s(%s)" % (x["label"], x["drawing"]) if x.get("drawing") else x["label"]
    return {"node_id": node["node_id"], "display_name": node.get("display_name"), "drawings": node.get("drawings", []),
            "start": text(b.get("start")), "end": text(b.get("end"))}


def drawing_column(node):
    """내보내기 '도면 번호' 열 값."""
    return ", ".join(node.get("drawings", []))


def tag_drawings(pg):
    """{태그: 도면번호} (도면 객체만, 여러 도면에 같은 태그면 넣지 않음)."""
    seen = {}
    for n in pg["nodes"]:
        if n.get("tag") and n.get("node_type") == "drawing_object" and n.get("sheet"):
            seen.setdefault(n["tag"], set()).add(_sheet_of_one(pg, n))
    return {t: next(iter(d)) for t, d in seen.items() if len(d) == 1}


def _sheet_of_one(pg, n):
    return next(s["drawing_number"] for s in pg["sheets"] if s["graph_id"] == n["sheet"])


def label_tags(text, tag_drawing, home_drawing, short):
    """문장 속 태그가 home_drawing이 아닌 도면의 것이면 'RC-P01(101)'처럼 짧은 도면번호를 붙인다(표시용 후처리,
    저장값은 바꾸지 않음). 이미 괄호가 붙은 태그는 그대로 둔다."""
    tags = sorted((t for t, d in tag_drawing.items() if d != home_drawing), key=len, reverse=True)
    if not text or not tags:
        return text
    pat = re.compile(r"(?<![A-Za-z0-9-])(%s)(?![A-Za-z0-9-]|\()" % "|".join(re.escape(t) for t in tags))
    return pat.sub(lambda m: "%s(%s)" % (m.group(1), short.get(tag_drawing[m.group(1)], tag_drawing[m.group(1)])), text)


# ---------------------------------------------------------------- 이전

def legacy_map(old_sets, project_set, pg=None):
    """도면별 저장본 -> {옛 ID "graph_id:S#": {"node_id": 대표 새 구간 또는 None, "overlap": [새 구간], "exact": bool}}.
    대표 = 옛 구성요소와 가장 많이 겹치는 새 구간(같으면 ID순). exact = 대표 구간 구성요소 전체가 옛 구성요소와 같고,
    pg를 주면 옛 집합의 도면 판이 프로젝트 그래프의 그 도면 판과 같음(넓어짐·나뉨·판 바뀜이면 False)."""
    versions = {s["graph_id"]: s["graph_version"] for s in pg["sheets"]} if pg else None
    out = {}
    for old in old_sets:
        gid = old["graph_id"]
        same_version = versions is None or versions.get(gid) == old.get("graph_version")
        for n in old["nodes"]:
            lifted = set(project.lift_ids(gid, n["members"]))
            hits = []
            for p in project_set["nodes"]:
                k = len(lifted & set(p["members"]))
                if k:
                    hits.append((-k, _num(p["node_id"]), p["node_id"]))
            hits.sort()
            best = hits[0][2] if hits else None
            mine = {m for p in project_set["nodes"] if p["node_id"] == best for m in p["members"]}
            out["%s:%s" % (gid, n["node_id"])] = {
                "node_id": best, "overlap": [h[2] for h in hits],
                "exact": bool(best) and same_version and mine == lifted and len(hits) == 1}
    return out


def _num(node_id):
    return int(node_id[1:]) if node_id[1:].isdigit() else 10 ** 9


def unmapped_ids(mapping):
    """대응하는 새 구간이 없는 옛 구간 ID(이전을 멈출 사유)."""
    return sorted(k for k, v in mapping.items() if v["node_id"] is None)


def migrate_set(old_sets, project_set, pg=None):
    """프로젝트 집합 사본에 legacy_ids를 더한다(이미 있던 legacy_ids는 남기고 합친다). 상태·구성요소는 바꾸지 않는다.
    옛 저장본의 확정 상태·확정자는 legacy_sources에, 대응 없는 옛 구간 ID는 legacy_unmapped에 남긴다."""
    out = copy.deepcopy(project_set)
    m = legacy_map(old_sets, project_set, pg)
    for n in out["nodes"]:
        n["legacy_ids"] = sorted(set(n.get("legacy_ids") or ()) |
                                 {k for k, v in m.items() if v["node_id"] == n["node_id"]})
    prev = {x["graph_id"]: x for x in out.get("legacy_sources") or []}
    for s in old_sets:
        prev[s["graph_id"]] = {"graph_id": s["graph_id"], "graph_version": s.get("graph_version"),
                               "status": s.get("status"), "confirmed_at": s.get("confirmed_at"),
                               "confirmed_by": s.get("confirmed_by"), "nodes": len(s["nodes"])}
    out["legacy_sources"] = [prev[k] for k in sorted(prev)]
    out["legacy_unmapped"] = sorted(set(out.get("legacy_unmapped") or ()) | set(unmapped_ids(m)))
    return out


def _lift_entry(entry, gid, legacy_id, flags):
    e = copy.deepcopy(entry)
    basis = e.get("ai_basis")
    if isinstance(basis, dict) and basis.get("kg_paths"):
        basis["kg_paths"] = [[project.nid(gid, x) if x.startswith(("entity-", "relation-")) else x for x in p]
                             for p in basis["kg_paths"]]
    e["legacy"] = {"from": legacy_id, "entry_id": entry.get("entry_id")}
    e["entry_id"] = "%s:%s" % (gid, entry.get("entry_id"))  # 도면마다 같은 구간 번호라 겹칠 수 있음
    e.update(flags)
    return e


def migrate_results(old_results, old_sets, project_set, deviations, pg=None):
    """도면별 결과들 -> (프로젝트 결과 문서, 이전 보고). 새 문서만 만들고 옛 파일은 그대로 둔다.
    - 옛 칸(옛 구간, 편차)의 항목을 대표 새 구간의 칸으로 옮긴다. 편차는 deviation_id가 아니라 item_id로 맞춘다.
    - 항목 상태(승인·기각·수정·제안)와 내용은 바꾸지 않는다. legacy{from, entry_id}를 남기고, 범위가 다르면
      scope_changed, 옛 결과가 옛 확정본과 이미 맞지 않았으면(results.is_stale) source_stale을 붙인다.
      entry_id는 "<graph_id>:<옛 entry_id>".
    - 칸 상태: 항목이 있으면 analyzed. 항목이 없으면 범위가 같고 최신인 옛 칸에서만 analyzed·excluded를 물려받는다
      (넓어진 범위는 사람이 보지 않았으므로 not_analyzed). 옛 칸 원문(상태·ai_run)은 legacy_cells에 남긴다.
    - 보고의 unmapped(옮길 곳 없는 옛 칸)·unmapped_nodes(대응 없는 옛 구간)·unmapped_deviations가 하나라도 있으면
      blocked(report)가 사유를 돌려준다(이전하지 않음)."""
    from hazop.study import results as res
    out = res.empty_results(project_set, deviations)
    cells = {(c["node_id"], c["deviation_id"]): c for c in out["cells"]}
    new_dev = {d["item_id"]: d["deviation_id"] for d in deviations}
    m = legacy_map(old_sets, project_set, pg)
    sets = {s["graph_id"]: s for s in old_sets}
    report = {"moved_entries": 0, "unmapped": [], "unmapped_nodes": unmapped_ids(m), "unmapped_deviations": [],
              "to_excluded": [], "scope_changed_entries": 0, "stale_entries": 0, "human_entries": 0}
    excluded = {n["node_id"] for n in project_set["nodes"] if (n.get("screen") or {}).get("status") == "excluded"}
    for old in old_results:
        gid = old["graph_id"]
        src = sets.get(gid) or {}
        if old.get("schema_version") in res.CELL_SCHEMA_VERSIONS:
            stale = gid not in sets or old.get("graph_version") != src.get("graph_version")
        else:
            stale = gid not in sets or old.get("study_nodes_ref") != {"graph_version": src.get("graph_version"),
                                                                      "confirmed_at": src.get("confirmed_at")}
        old_dev = {d["deviation_id"]: d.get("item_id") for d in old.get("deviations") or []}
        kept = [a["cell"] for a in old.get("archived_cells") or [] if isinstance(a, dict) and isinstance(a.get("cell"), dict)]
        for c in old["cells"] + kept:  # 0.2로 바뀐 도면별 결과의 보관 칸도 옮긴다(승인 항목이 옛 파일에만 남지 않게)
            lid = "%s:%s" % (gid, c["node_id"])
            did = new_dev.get(old_dev.get(c["deviation_id"]))
            if did is None:
                report["unmapped_deviations"].append({"legacy_id": lid, "deviation_id": c["deviation_id"]})
                continue
            cell = cells.get(((m.get(lid) or {}).get("node_id"), did))
            if cell is None:
                report["unmapped"].append({"legacy_id": lid, "deviation_id": c["deviation_id"],
                                           "entries": len(c["entries"]), "state": c["state"]})
                continue
            if m[lid]["node_id"] in excluded and any(e.get("status") in res.HUMAN_STATUSES for e in c["entries"]):
                report["to_excluded"].append({"legacy_id": lid, "deviation_id": c["deviation_id"], "node_id": m[lid]["node_id"]})
                continue  # 사람이 판정한 항목을 행 없는 '스크리닝 제외' 구간에 숨기지 않는다(§4.6 '제외로 감')
            exact = m[lid]["exact"]
            flags = dict({} if exact else {"scope_changed": True}, **({"source_stale": True} if stale else {}))
            cell.setdefault("legacy_cells", []).append({"from": lid, "deviation_id": c["deviation_id"],
                                                        "state": c["state"], "ai_run": c.get("ai_run"),
                                                        "exact": exact, "stale": stale})
            for e in c["entries"]:
                cell["entries"].append(_lift_entry(e, gid, lid, flags))
                report["moved_entries"] += 1
                report["scope_changed_entries"] += not exact
                report["stale_entries"] += stale
                report["human_entries"] += e.get("status") in res.HUMAN_STATUSES
            trusted = {x["state"] for x in cell["legacy_cells"] if x["exact"] and not x["stale"]}
            every = {x["state"] for x in cell["legacy_cells"]}
            if cell["entries"]:
                cell["state"] = "analyzed"
            elif every == trusted and trusted in ({"excluded"}, {"analyzed"}, {"analyzed", "excluded"}):
                cell["state"] = "excluded" if trusted == {"excluded"} else "analyzed"
            else:
                cell["state"] = "not_analyzed"
    out["ai_log"] = [dict(x, legacy_from=o["graph_id"]) for o in old_results for x in o.get("ai_log") or []]
    out["legacy_sources"] = [{"graph_id": o["graph_id"], "study_nodes_ref": o.get("study_nodes_ref")}
                             for o in old_results]
    return out, report


def blocked(report):
    """이전을 멈출 사유(보고 키) 목록. 빈 목록이면 진행."""
    return [k for k in ("unmapped", "unmapped_nodes", "unmapped_deviations", "to_excluded") if report.get(k)]
