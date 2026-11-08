"""③ 지식그래프 화면 데이터·HTML 생성 (기획서/그래프활용.md §5, 디자인/지식그래프화면.md).

- 계산은 Python: 계산 뷰 V5(hazop.kg.algo.view_v5), A1(a1_propagation), A2·A3·A5, 배관 구간 접기(fold_segments)를
  algo.py 함수 그대로 호출한다. JS는 넘겨받은 값으로 그리기만 하고, 로컬 깊이 BFS는 표시 전용이다(§5.2, 검사 V1).
- 데이터: P&ID 노드·관계 + 지식 노드·관계(V5 포함 여부 표시) + 표시 전용 연결 후보(link_candidates.csv의
  link_status=candidate 행, 현재 도면·버전에서 대상이 풀리는 것만, T1 D9). 후보·미확인·가설·재확인 항목은 계산에 넣지 않는다.
- 잠재 후보(hazop.kg.expect 결과)는 기대 층 노드·관계(expects·satisfied_by)로 넣되 v5=false로 두고 계산 뷰에 넣지 않는다.
  화면이 상태별로 켜고 끄며, 사람 판단은 앱(③ 상세 패널)이 저장한다.
- HTML: force-graph vendor JS를 인라인으로 넣는다(<script src> 없음, T1 D5). 데이터를 넣으면 브라우저 단독 모드,
  데이터 없이(app 셸) 만들면 앱이 브리지 loadKnowledge 메시지로 데이터를 넘긴다. 데이터 JSON의 '/'는 '\\/'로 적어
  생성 부분에 URL 문자열이 생기지 않게 한다(검사 V2).
- 지식그래프 validation이 passed가 아니거나 도면 버전이 맞지 않으면(algo.check_inputs) 알고리즘을 실행하지 않는다(§7.1).
"""

import hashlib
import json
import os

from hazop.app import tokens
from hazop.graph.build import node_origin
from hazop.kg import algo, build, expect, link
from hazop.kg.schema import REGISTRY

NODE_LIMIT = 5000  # 전역 보기 노드 수 상한(그래프활용 §7.3, 검사 S1, T1 D8)
DEFAULT_RADIUS = 2  # 로컬 깊이 기본값(§5.1)
CANDIDATES_CSV = "link_candidates.csv"
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "screen_template.html")
VENDOR_DIR = os.path.join(HERE, "vendor", "force-graph-1.52.0")
VENDOR_JS = os.path.join(VENDOR_DIR, "force-graph.min.js")
PLACEHOLDERS = ("/*@CSS_VARS@*/", "/*@DATA@*/", "/*@VENDOR@*/", "/*@SCHEMA@*/")
SCREEN_LAYER = {ly: REGISTRY.screen_layer(ly) for ly in REGISTRY.layers}
EXP_LAYER = REGISTRY.screen_layer("expectation")
# 잠재 후보 상태: (상태, 색 토큰, 처음 켬). 색은 ③의 차분한 계열에서 고름(새 토큰 없음). 무관·확인됨은 기본 숨김(입력 §2.1)
EXPECT_STATES = (("expected", "kg-edge-hi", True), ("candidate_found", "kg-instrument", True),
                 ("confirmed_absent", "kg-flag-ink", True), ("confirmed_present", "kg-pipe_segment", False),
                 ("not_applicable", "kg-unclassified", False))
TRUNCATION_LABELS = {"external_drawing": "도면 경계에서 멈춤"}  # 디자인 §3.2. 그 밖의 사유는 reason 그대로
S1_TEXT ="전역 보기 노드 수 상한 초과 — 노드 %s개 > %s. 로컬 보기를 권장합니다(전역 보기는 그대로 쓸 수 있음)"


# ---------------------------------------------------------------- 입력 읽기
def list_kg_roots(out_root):
    """<out_root>/<kg_id>/current.json이 있는 지식그래프 폴더 [(kg_id, 경로)]."""
    if not os.path.isdir(out_root):
        return []
    return [(n, os.path.join(out_root, n)) for n in sorted(os.listdir(out_root))
            if os.path.isfile(os.path.join(out_root, n, build.POINTER_FILE))]


def load_graphs(graph_root):
    """{graph_id: (폴더 이름, graph)}. 같은 graph_id가 둘 이상이면 처음 것(이름순)만 쓰고 나머지는 무시한다."""
    out = {}
    for name in sorted(os.listdir(graph_root)) if os.path.isdir(graph_root) else []:
        p = os.path.join(graph_root, name, "graph.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                g = json.load(fh)
            out.setdefault(g.get("graph_id"), (name, g))
    return out


def graph_for_ref(graph_root, graph_id, graph_version):
    """지식그래프 graph_ref에 맞는 (폴더 이름, graph) 또는 None. 같은 graph_id 폴더가 여럿이면(같은 도면을 drawio·PDF로
    따로 등록한 경우 등) graph_version이 같은 폴더를 먼저, 없으면 load_graphs와 같은 첫 폴더(이름순)를 쓴다."""
    first = None
    for name in sorted(os.listdir(graph_root)) if os.path.isdir(graph_root) else []:
        p = os.path.join(graph_root, name, "graph.json")
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8") as fh:
            g = json.load(fh)
        if g.get("graph_id") != graph_id:
            continue
        if g.get("graph_version") == graph_version:
            return name, g
        first = first or (name, g)
    return first


def load_regions(region_dir):
    """[(라벨, 구간 dict, 파일 sha256)] — A1 인자(algo.a1_propagation)."""
    out = []
    for f in sorted(os.listdir(region_dir)) if os.path.isdir(region_dir) else []:
        if f.endswith(".json"):
            with open(os.path.join(region_dir, f), "rb") as fh:
                raw = fh.read()
            out.append((f, json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()))
    return out


def read_candidates(input_dir):
    """데이터/지식/<project_id>/link_candidates.csv 행(link.read_candidates). 파일이 없으면 None."""
    path = os.path.join(input_dir, CANDIDATES_CSV)
    return link.read_candidates(path) if os.path.isfile(path) else None


def previous_passed(kg_root, current_version):
    """blocked일 때 보여 줄 직전 passed 버전 (kg_version, kg) 또는 None.
    버전 폴더에는 만든 시각 기록이 없으므로 폴더 수정 시각이 가장 늦은 passed 버전을 고른다(한계: 폴더를 복사·이동하면
    순서가 바뀔 수 있음). 폴더 이름과 파일 안 kg_version이 다르면 쓰지 않는다."""
    best = None
    for name in os.listdir(kg_root) if os.path.isdir(kg_root) else []:
        p = os.path.join(kg_root, name, build.KG_FILE)
        if name == current_version or not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                kg = json.load(fh)
        except (OSError, ValueError):
            continue
        if kg.get("kg_version") != name or (kg.get("validation") or {}).get("status") != "passed":
            continue
        t = os.path.getmtime(os.path.join(kg_root, name))
        if best is None or (t, name) > best[0]:
            best = ((t, name), kg)
    return (best[1]["kg_version"], best[1]) if best else None


def default_start(graph, regions):
    """A1 기본 시작점: 이 도면을 가리키는 첫 구간(파일 이름순)의 focus_entities[0]. 없으면 None."""
    ids = {n["entity_id"] for n in graph["nodes"]}
    for _, region, _ in regions:
        if (region.get("graph_ref") or {}).get("graph_id") == graph["graph_id"]:
            f = (region.get("focus_entities") or [None])[0]
            if f in ids:
                return f
    return None


# ---------------------------------------------------------------- 화면 데이터
def algo_problem(kg, graph):
    """알고리즘을 실행할 수 없는 사유(algo.check_inputs) 또는 None."""
    try:
        algo.check_inputs(kg, graph)
    except algo.AlgoError as e:
        return str(e)
    return None


def a1_compact(a1):
    """A1 결과(algo.a1_propagation)에서 그리기에 필요한 값만: 도달 노드별 방향·깊이·마지막 경로 관계·정상 유로 여부."""
    if not a1.get("active"):
        return {"active": False, "reason": a1.get("reason"), "start": None}
    ex = a1["exploration"]
    reached = {}
    for r in ex["reached"]:
        pe = r.get("path_edges") or []
        reached[r["entity_id"]] = {"dir": r.get("direction_from_start"), "depth": r.get("depth"),
                                   "edge": pe[-1] if pe else None, "nnf": r.get("normal_operation_flow") is False,
                                   "valve": r.get("valve_state")}
    return {"active": True, "start": ex.get("start"), "region_id": a1["region_ref"]["region_id"],
            "reached": reached, "members": a1["region_members"],
            "unreached": ex.get("unreached_region_members") or [],
            "truncated": {t["at"]: TRUNCATION_LABELS.get(t.get("reason"), t.get("reason") or "탐색 멈춤")
                          for t in ex.get("truncations") or [] if t.get("at")},
            "limits_hit": ex.get("limits_hit") or []}


def run_a1(kg, graph, regions, start):
    """runAlgorithm(A1) 처리: (전체 결과, 그리기용 요약). 알고리즘 실행 불가면 AlgoError."""
    prob = algo_problem(kg, graph)
    if prob:
        raise algo.AlgoError(prob)
    a1 = algo.a1_propagation(graph, regions, start)
    c = a1_compact(a1)
    if not c["active"]:
        c["start"] = start
    return a1, c


def _flow_sign(edge, segs):
    """has_endpoint 관계(nodes = [구간, 끝 노드])의 흐름 화살표: 1 = 구간→노드, -1 = 노드→구간, 0 = 방향 미확인."""
    fd = (segs.get(edge.get("segment")) or {}).get("flow_direction")
    if not fd or not edge.get("end"):
        return 0
    if fd.get("to_end") == edge["end"]:
        return 1
    if fd.get("from_end") == edge["end"]:
        return -1
    return 0


def _label(n):
    for k in ("name", "item", "text"):
        v = n.get(k)
        if v:
            v = str(v)
            return v if len(v) <= 24 else v[:23] + "…"
    return n["id"]


def expectation_view(expectations, graph):
    """잠재 후보(expect.evaluate 결과) -> 이 도면의 기대 층 노드·관계와 집계. 대상이 다른 도면이면 넣지 않고 센다.
    후보(satisfied_by) 끝이 다른 도면이면 관계만 빼고 노드 상세에는 남긴다."""
    if expectations is None:
        return [], [], None
    gid = graph["graph_id"]
    by_soid = {n.get("source_object_id"): n["entity_id"] for n in graph["nodes"] if n.get("source_object_id")}

    def entity(ref):
        g, _, soid = (ref or "").partition("#")
        return by_soid.get(soid) if g == gid else None
    nodes, links, other, gap = [], [], 0, {}
    for it in expectations["items"]:
        target = entity(it["target"])
        if target is None:
            other += 1
            continue
        label = it["label"] if len(it["label"]) <= 24 else it["label"][:23] + "…"
        nodes.append({"id": it["id"], "layer": EXP_LAYER, "type": "expectation", "label": label, "xs": it["state"],
                      "recheck": it["recheck"], "rule": it["rule_id"], "target": target, "v5": False})
        links.append({"id": "xrel-%s-t" % it["id"], "kind": "expects", "s": target, "t": it["id"], "layer": EXP_LAYER,
                      "st": "expect", "v5": False, "a": 0})
        if it["state"] in ("candidate_found", "confirmed_present"):
            refs = (it.get("judgement") or {}).get("found") if it["state"] == "confirmed_present" else None
            for ref in sorted(set(refs or [f["ref"] for f in it["found"]])):
                e = entity(ref)
                if e is not None and e != target:
                    links.append({"id": "xrel-%s-%s" % (it["id"], e), "kind": "satisfied_by", "s": it["id"], "t": e,
                                  "layer": EXP_LAYER, "st": "expect", "v5": False, "a": 0})
        if it["state"] in expect.GAP_STATES:
            gap.setdefault(target, []).append(it["id"])
    states = {}
    for n in nodes:
        states[n["xs"]] = states.get(n["xs"], 0) + 1
    info = {"shown": len(nodes), "other_graphs": other, "states": dict(sorted(states.items())),
            "recheck": sum(1 for n in nodes if n["recheck"]), "gap": gap,
            "gap_absent": sum(1 for n in nodes if n["xs"] == "confirmed_absent"),
            "gap_expected": sum(1 for n in nodes if n["xs"] == "expected"),
            "rules_version": expectations.get("rules_version")}
    return nodes, links, info


def screen_data(kg, graph, regions=(), candidates=None, start=None, standalone_note=None, expectations=None):
    """화면 JSON(dict). candidates: link_candidates.csv 행 목록 또는 None(파일 없음).
    start: A1 시작점(None이면 default_start). 알고리즘을 실행할 수 없으면 algo.enabled=false와 사유.
    expectations: 잠재 후보(expect.evaluate 결과) 또는 None(계산하지 않음)."""
    gid, gver = graph["graph_id"], graph["graph_version"]
    v5 = algo.view_v5(kg, graph)
    v5_keys = {k for _, _, k in v5.edges(keys=True)}
    folded, _ = algo.fold_segments(v5, graph)
    foldable = {k for _, _, k, d in folded.edges(keys=True, data=True) if d.get("kind") == "folded_segment"}
    segs = {n["entity_id"]: n for n in graph["nodes"] if n.get("node_type") == "pipe_segment"}
    pid_conflict = {r for n in kg["nodes"] for r in n.get("conflict_with_pid") or []}  # 문서 값과 다른 도면 속성 주장

    nodes = []
    for n in graph["nodes"]:
        seg = n.get("node_type") == "pipe_segment"
        attrs = n.get("attributes") or {}
        pos = n.get("position")
        nodes.append({"id": n["entity_id"], "layer": "pid",
                      "type": "pipe_segment" if seg else (n.get("category") or "unclassified"),
                      "kind": n.get("kind"), "tag": n.get("tag"), "label": n.get("tag") or n.get("kind") or n["entity_id"],
                      "local_id": n.get("local_id"), "pos": pos if isinstance(pos, list) and len(pos) == 2 else None,
                      "np": attrs.get("normal_position"), "cont": n.get("kind") == "continuation",
                      "fold": n["entity_id"] in foldable, "v5": n["entity_id"] in v5,
                      "hedit": node_origin(n) == "human_edit",
                      "conflict": "%s#%s" % (gid, n.get("source_object_id")) in pid_conflict})
    kn_ids = set()
    for n in kg["nodes"]:
        kn_ids.add(n["id"])
        nodes.append({"id": n["id"], "layer": "kn", "type": n.get("node_type"), "label": _label(n),
                      "ks": n.get("knowledge_status") or "confirmed", "v5": n["id"] in v5,
                      "nosrc": n.get("has_source") is False,
                      "conflict": bool(n.get("conflict_with") or n.get("conflict_with_pid")),
                      "unit_unknown": n.get("node_type") == "setpoint" and not n.get("unit"),
                      "ai": build.origin_of(n) == "ai_draft"})
    pid_ids = {n["entity_id"] for n in graph["nodes"]}

    links, skipped = [], {"other_graph_or_unresolved": 0, "rejected": 0}
    for e in graph["edges"]:
        if e["entity_id"] not in v5_keys:
            skipped["other_graph_or_unresolved"] += 1
            continue
        a, b = e["nodes"][0], e["nodes"][1]
        links.append({"id": e["entity_id"], "kind": e["kind"], "s": a, "t": b, "layer": "pid", "st": "confirmed",
                      "v5": True, "a": _flow_sign(e, segs) if e["kind"] in algo.PHYSICAL_KINDS else 0})
    for l in kg["links"]:
        if l.get("link_status") == "rejected":
            skipped["rejected"] += 1
            continue
        ends = []
        for side in ("from", "to"):
            end = (l.get("ends") or {}).get(side) or {}
            if end.get("layer") == "knowledge":
                ends.append(end.get("ref") if end.get("ref") in kn_ids else None)
            else:
                ok = end.get("graph_id") == gid and end.get("entity_id") in pid_ids
                ends.append(end.get("entity_id") if ok else None)
        if None in ends:
            skipped["other_graph_or_unresolved"] += 1
            continue
        if l["id"] in v5_keys:
            st = "confirmed"
        elif l.get("recheck"):
            st = "recheck"
        elif l.get("link_status") == "candidate":
            st = "candidate"
        else:
            st = "excluded"
        links.append({"id": l["id"], "kind": l["kind"], "s": ends[0], "t": ends[1], "layer": "kn", "st": st,
                      "v5": st == "confirmed", "a": 0, "ks": l.get("knowledge_status"),
                      "ai": build.origin_of(l) == "ai_draft"})

    cand_info = {"file": candidates is not None, "rows": 0, "shown": 0, "not_shown": 0}
    sid_map = {n.get("source_object_id"): n["entity_id"] for n in graph["nodes"] if n.get("source_object_id")}
    kg_link_ids = {l["id"] for l in kg["links"]}
    for r in candidates or []:
        if (r.get("link_status") or "").strip() != "candidate":
            continue
        if link.relation_id(r.get("candidate_key") or "") in kg_link_ids:
            continue  # 자동 지식그래프가 이미 같은 후보 키로 만든 언급(hazop.kg.auto.mention_links)
        cand_info["rows"] += 1
        target = sid_map.get(r.get("target_source_object_id"))
        if (r.get("target_graph_id") != gid or r.get("target_graph_version") != gver or target is None
                or r.get("chunk_id") not in kn_ids):
            cand_info["not_shown"] += 1  # 다른 도면·버전, 도면에 없는 대상(예: RC-V999 언급은 후보 자체가 없음)
            continue
        cand_info["shown"] += 1
        links.append({"id": "cand:" + link.relation_id(r.get("candidate_key") or ""), "kind": "mentions",
                      "s": r["chunk_id"], "t": target, "layer": "kn", "st": "candidate", "v5": False, "a": 0,
                      "method": r.get("method"), "conf": r.get("confidence"),
                      "amb": (r.get("ambiguous") or "").strip().lower() == "true", "match": r.get("match_text"),
                      "key": r.get("candidate_key")})

    x_nodes, x_links, x_info = expectation_view(expectations, graph)
    nodes += x_nodes
    links += x_links

    problem = algo_problem(kg, graph)
    alg = {"enabled": problem is None, "reason": problem}
    if problem is None:
        v1 = algo.view_v1(graph)
        a3 = algo.a3_degree(v5, graph)
        a5 = algo.a5_components(v1, v5)
        a2 = algo.a2_orphans_gaps(kg, graph)
        start = start if start is not None else default_start(graph, regions)
        if start is not None:
            a1 = a1_compact(algo.a1_propagation(graph, list(regions), start))
            if not a1["active"]:
                a1["start"] = start
        else:
            a1 = {"active": False, "reason": "시작 노드 미선택", "start": None}
        alg.update({
            "A1": a1,
            "A2": {"orphans": {o["id"]: o["reason"] for o in a2["orphans"]},
                   "gaps": {g["entity_id"]: g["mentioned_by"] for g in a2["evidence_gaps"]},
                   "no_input": sorted(x["entity_id"] for x in a2["no_knowledge_input"]),
                   "no_input_cont": sorted(x["entity_id"] for x in a2["no_knowledge_input_continuations"])},
            "A3": {k: v["degree"] for k, v in a3["degree"].items()},
            "A5": {"V5_count": a5["V5"]["count"], "V1_count": a5["V1"]["count"],
                   "comp": {nid: i for i, c in enumerate(a5["V5"]["components"]) for nid in c},
                   "sizes": a5["V5"]["sizes"]},
        })
    v = kg.get("validation") or {}
    global_count = len(nodes)  # 렌더러가 받는 전체 노드(계산 제외 노드도 물리 배치에는 들어감)
    meta = {
        "kg_id": kg.get("kg_id"), "kg_version": kg.get("kg_version"), "graph_id": gid, "graph_version": gver,
        "graph_ref_version": {r["graph_id"]: r["graph_version"] for r in kg.get("graph_refs") or []}.get(gid),
        "status": v.get("status"), "blockers": len(v.get("blockers") or []), "unknowns": len(v.get("unknowns") or []),
        "conflicts": len(kg.get("conflicts") or []),
        "recheck": sum(1 for l in links if l["st"] == "recheck"),
        "excluded_nodes": sum(1 for n in nodes if n["layer"] == "kn" and not n["v5"]),
        "excluded_links": sum(1 for l in links if l["layer"] == "kn" and l["st"] in ("excluded", "recheck")),
        "candidates": cand_info, "skipped_links": skipped,
        "node_limit": NODE_LIMIT, "global_count": global_count, "s1": global_count > NODE_LIMIT,
        "default_radius": DEFAULT_RADIUS, "note": standalone_note,
        # 자동 추출·사람 확인 전 지식 노드 수. 0보다 크면 화면이 미확인·후보 표시를 켠 채로 연다(§9.3)
        "auto_items": sum(1 for n in kg["nodes"] if n.get("method") == "extractor"
                          and n.get("knowledge_status") != "confirmed"),
        "ai_items": sum(1 for x in nodes + links if x.get("ai") and not x["v5"]),
        "expectations": x_info,
    }
    return {"meta": meta, "nodes": nodes, "links": links, "algo": alg}


def ego_nodes(kg, graph, center, radius):
    """V5 ego_graph 노드 집합(algo.a4_ego) — 검사 V1의 Python 쪽 기준."""
    r = algo.a4_ego(algo.view_v5(kg, graph), center, radius)
    return r["nodes"] if r["active"] else []


def s1_message(data):
    m = data["meta"]
    return S1_TEXT % (format(m["global_count"], ","), format(m["node_limit"], ",")) if m["s1"] else None


# ---------------------------------------------------------------- HTML
def vendor_text():
    with open(VENDOR_JS, encoding="utf-8") as fh:
        return fh.read()


def data_js(data):
    """<script> 안에 넣을 JSON. '<'는 \\u003c로 적어 '</script>'·'<!--'·'<script'가 HTML 파서에 닿지 않게 하고,
    '/'는 '\\/'로 적어 URL 문자열(http://)이 생성 부분에 생기지 않게 한다(검사 V2). 둘 다 JSON·JS에서 같은 값."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.replace("<", "\\u003c").replace("/", "\\/")


def legend_tables():
    """화면 범례 표 (TYPE, GRP_OF, GRP). 순서는 레지스트리 파일 순서(범례 표시 순서)."""
    types = {}
    for c in REGISTRY.legend_classes():
        t = {"layer": SCREEN_LAYER[REGISTRY.layer(c["id"])], "name": c["label_ko"], "col": c["legend"]["token"],
             "shape": c["legend"]["shape"]}
        if c["legend"].get("line", "solid") != "solid":
            t["line"] = c["legend"]["line"]
        types[c["id"]] = t
    grp_of = {r["id"]: r["group"] for r in REGISTRY.data["relations"]}
    grps = {g["id"]: {"name": g["label_ko"], "w": g["width"]} for g in REGISTRY.data["groups"]}
    return types, grp_of, grps


def layer_table():
    """화면 층 표 [{key, name, filter, on}] (레지스트리 layers 순서). 종류 필터 층은 '노드 종류'에, 상태 필터 층은
    자기 묶음(기대 층은 '잠재 후보')에 나온다."""
    return [{"key": ly["screen"], "name": ly["label_ko"], "filter": ly["filter"], "on": ly["default_on"]}
            for ly in REGISTRY.data["layers"]]


def expect_table():
    """잠재 후보 상태 표 [{state, name, col, on}]."""
    return [{"state": st, "name": expect.STATES[st], "col": col, "on": on} for st, col, on in EXPECT_STATES]


def schema_js():
    """템플릿 /*@SCHEMA@*/ 자리에 넣을 JS. data_js와 같은 방식으로 '<'·'/'를 적는다(검사 V2)."""
    def js(obj):
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("/", "\\/")
    types, grp_of, grps = legend_tables()
    return "var TYPE = %s;\n  var GRP_OF = %s;\n  var GRP = %s;\n  var LAYERS = %s;\n  var XSTATES = %s;" % (
        js(types), js(grp_of), js(grps), js(layer_table()), js(expect_table()))


def build_html(data=None):
    """data가 있으면 단독 모드 HTML(데이터 포함), None이면 앱 셸(데이터는 loadKnowledge로 받음)."""
    with open(TEMPLATE, encoding="utf-8") as fh:
        tpl = fh.read()
    for p in PLACEHOLDERS:
        if tpl.count(p) != 1:
            raise ValueError("템플릿 자리표시 %s가 정확히 1개가 아님" % p)
    html = tpl.replace("/*@DATA@*/", data_js(data) if data is not None else "null")
    html = html.replace("/*@CSS_VARS@*/", tokens.kg_css_vars())
    html = html.replace("/*@SCHEMA@*/", schema_js())
    return html.replace("/*@VENDOR@*/", vendor_text())


def write_html(path, html):
    """임시 파일에 쓴 뒤 교체. 내용이 같으면 쓰지 않는다(웹뷰가 같은 파일을 다시 읽지 않게)."""
    data = html.encode("utf-8")
    if os.path.isfile(path):
        with open(path, "rb") as fh:
            if fh.read() == data:
                return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- 프로젝트 그래프: 도면 경계
def _drawing_of(pg):
    return {s["graph_id"]: s["drawing_number"] for s in pg["sheets"]}


def _end_text(by_id, end):
    """도면 연결 끝 → 연결점 이름(태그·라벨 첫 줄)."""
    from hazop.graph import project
    n = by_id.get(project.nid(end["graph_id"], end["entity_id"])) or {}
    first = (n.get("label_text") or end.get("label_text") or "").split("\n")[0].strip()
    return n.get("tag") or first or end["entity_id"]


def sheet_link_rows(pg):
    """③ '도면 연결' 표: 도면 연결마다 {from_drawing, from_label, to_drawing, to_label, line_no, status, reason, drawings}.
    linked면 from이 흐름이 나가는 쪽. unlinked면 to가 없고 to_drawing은 연결점이 가리키는 도면 번호(없으면 None)."""
    from hazop.graph import project
    by_id = {n["entity_id"]: n for n in pg["nodes"]}
    rows = []
    for l in pg["sheet_links"]:
        a, b = l["from"], l.get("to")
        rows.append({"from_drawing": a["drawing_number"], "from_label": _end_text(by_id, a),
                     "to_drawing": b["drawing_number"] if b else a.get("to_drawing"),
                     "to_label": _end_text(by_id, b) if b else None, "line_no": a.get("line_no") or (b or {}).get("line_no"),
                     "status": l["status"], "origin": l.get("origin"),
                     "reason": project.REASONS.get(l["reason"], l["reason"]) if l["reason"] else None,
                     "drawings": sorted({a["drawing_number"]} | ({b["drawing_number"]} if b else set()))})
    return rows


def cross_path(pg, a, b):
    """도면 경계를 넘는 물리 경로(GraphQuery(pg).path, 흐름 방향 무시). 찾지 못하면 None, 대상이 없거나 여럿이면
    QueryError. 단계 [{"kind": "step"|"boundary", "text", "drawings"}]: 도면 연결 구간은 지나는 순서대로
    "── SNP-M-101 → SNP-M-102 (RC-L011) ──" 경계 표시가 된다."""
    from hazop.graph.query import GraphQuery
    from hazop.study import span
    q = GraphQuery(pg)
    p = q.path(a, b)["ignoring_direction"]
    if not p["found"]:
        return None
    sheet_dn = _drawing_of(pg)
    short = span.short_numbers(sheet_dn.values())[1]
    ids = [s["entity_id"] for s in p["nodes"]]
    dn = [sheet_dn.get(q.nodes[i].get("sheet")) for i in ids]
    steps = []
    for k, i in enumerate(ids):
        n = q.nodes[i]
        if n.get("sheet") is None and n.get("sheet_link"):
            before = next((d for d in reversed(dn[:k]) if d), None)
            after = next((d for d in dn[k + 1:] if d), None)
            steps.append({"kind": "boundary", "drawings": [d for d in (before, after) if d],
                          "text": "── %s → %s (%s) ──" % (before, after, n.get("line_no") or n.get("tag") or "-")})
            continue
        first = (n.get("label_text") or "").split("\n")[0].strip()
        label = n.get("tag") or (first if n.get("kind") == "continuation" else None) or             ("배관 구간" if n.get("kind") == "pipe_segment" else n.get("kind"))
        steps.append({"kind": "step", "drawings": [dn[k]] if dn[k] else [],
                      "text": "[%s] %s" % (short.get(dn[k], dn[k] or "-"), label)})
    return steps


def filter_by_drawing(rows, drawing):
    """도면 필터: drawing이 None이면 그대로, 아니면 그 도면을 지나는 행(경로 단계·연결 표)만."""
    return list(rows) if not drawing else [r for r in rows if drawing in r["drawings"]]
