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

from hazop import store_io
from hazop.app import tokens
from hazop.graph.build import node_origin
from hazop.kg import algo, auto, build, expect, link
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
STUDY_LAYER = REGISTRY.screen_layer("study")
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


def graph_for_ref(graph_root, graph_id, graph_version, retry=True):
    """지식그래프 graph_ref에 맞는 (폴더 이름, graph) 또는 None. 같은 graph_id 폴더가 여럿이면(같은 도면을 drawio·PDF로
    따로 등록한 경우 등) graph_version이 같은 폴더를 먼저, 없으면 load_graphs와 같은 첫 폴더(이름순)를 쓴다."""
    same = []
    for name in sorted(os.listdir(graph_root)) if os.path.isdir(graph_root) else []:
        p = os.path.join(graph_root, name, "graph.json")
        head = auto.graph_head(p)  # 머리만 캐시해 두고 고른 도면 하나만 다시 읽는다
        if head is not None and head["graph_id"] == graph_id:
            same.append((head["graph_version"] != graph_version, name, p))
    if not same:
        return None
    other_version, name, p = min(same)
    with open(p, encoding="utf-8") as fh:
        g = json.load(fh)
    if retry and (g.get("graph_id") != graph_id or (g.get("graph_version") != graph_version) != other_version):
        auto.forget_heads()  # 머리를 읽은 뒤 파일이 바뀜: 머리를 새로 읽어 한 번만 다시 고른다
        return graph_for_ref(graph_root, graph_id, graph_version, retry=False)
    return name, g


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
    """data/knowledge-graph/<project_id>/link_candidates.csv 행(link.read_candidates). 파일이 없으면 None."""
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


def _short(text, n=24):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def study_view(study, graph, exp_ids=()):
    """검토 층 투영(설계안 KD7·§8.3, U2(가)): ⑤ 결과 파일을 읽어 이 도면에 걸친 검토구간의 시나리오·보호수단을 노드·관계로
    만든다. 원본은 결과 파일이고 여기서는 읽기만 한다. 모두 v5=false라 계산 뷰·알고리즘에 들어가지 않는다.
    구간 구성요소(covers)는 선을 그리지 않는다. 구간 하나가 구성요소 수십 개에 선을 그어 시나리오가 보이지 않게 되기 때문이다.
    study: {"node_set", "results"(없으면 None), "note"} 또는 None. 원인·결과 노드는 이 도면 대상을 가리키는 참조가 있을 때만
    만든다(cause_at·affects 경로를 보이기 위해). 기각한 항목은 넣지 않는다. 대상을 찾지 못한 참조는 지우지 않고 센다."""
    from hazop.graph.project import SEP
    from hazop.study import refs, results as res
    if study is None:
        return [], [], None
    gid = graph["graph_id"]
    ids = {n["entity_id"] for n in graph["nodes"]}
    idx = {r: n["entity_id"] for r, n in refs.index(graph).items()}
    devs = {d["deviation_id"]: d["label"] for d in (study.get("results") or {}).get("deviations") or []}
    cells = {}
    for c in (study.get("results") or {}).get("cells") or []:
        cells.setdefault(c["node_id"], []).append(c)
    nodes, links, rows = [], [], []

    def node(nid, typ, label, sn, **kw):
        nodes.append(dict({"id": nid, "layer": STUDY_LAYER, "type": typ, "label": _short(label), "sn": sn, "v5": False}, **kw))

    def link(kind, s, t, **kw):
        links.append(dict({"id": "srel-%s-%s-%s" % (kind, s, t), "kind": kind, "s": s, "t": t, "layer": STUDY_LAYER,
                           "st": "study", "v5": False, "a": 0}, **kw))
    for sn in (study.get("node_set") or {}).get("nodes") or []:
        members = []
        for m in sn["members"]:
            g, sep, e = m.partition(SEP)
            if sep and g == gid and e in ids:
                members.append(e)
        if not members:
            continue
        snid = "st-" + sn["node_id"]
        n_scen = n_missing = 0
        node(snid, "study_node", "%s %s" % (sn["node_id"], sn.get("name") or ""), sn["node_id"],
             detail={"name": sn.get("name"), "members": len(sn["members"]), "here": len(members)})
        for cell in cells.get(sn["node_id"], []):
            for e in cell["entries"]:
                if e.get("status") == "rejected":
                    continue
                n_scen += 1
                draft = res.is_ai_draft(e)
                sc = "st-" + e["entry_id"]
                miss = [r for r in refs.all_refs(e) if r not in idx and refs.drawing_of(r) == gid]
                n_missing += len(miss)
                node(sc, "scenario", "%s · %s" % (devs.get(cell["deviation_id"], cell["deviation_id"]), e.get("cause") or ""),
                     sn["node_id"], draft=draft, missing=len(miss),
                     detail={"deviation": devs.get(cell["deviation_id"]), "cause": e.get("cause"),
                             "consequence": e.get("consequence"), "status": e.get("status"), "risk": e.get("risk"),
                             "missing": miss})
                link("in_node", sc, snid)
                for key, typ, rel, suffix in (("cause_refs", "cause", "cause_at", "c"),
                                              ("consequence_refs", "consequence", "affects", "q")):
                    hits = [idx[r["ref"]] for r in e.get(key) or [] if isinstance(r, dict) and r.get("ref") in idx]
                    if not hits:
                        continue
                    cid = "%s-%s" % (sc, suffix)
                    node(cid, typ, e.get(typ) or "", sn["node_id"], draft=draft, detail={"text": e.get(typ)})
                    link("has_" + typ, sc, cid)
                    for h in dict.fromkeys(hits):
                        link(rel, cid, h)
                for i, s in enumerate(refs.safeguard_items(e)):
                    gid_ = "%s-g%d" % (sc, i + 1)
                    node(gid_, "safeguard", s["text"], sn["node_id"], draft=draft or not refs.is_confirmed(s, e),
                         role=s["role"], detail={"text": s["text"], "role": refs.ROLES[s["role"]]})
                    link("protected_by", sc, gid_, role=s["role"])
                    for r in s["refs"]:
                        if r.get("ref") in idx:
                            link("safeguard_by", gid_, idx[r["ref"]])
                for x in e.get("expectation_refs") or []:
                    if x in exp_ids:
                        link("raised_from", sc, x)
        rows.append({"sn": sn["node_id"], "name": sn.get("name"), "scenarios": n_scen, "missing": n_missing})
    info = {"nodes": rows, "note": study.get("note"), "scenarios": sum(r["scenarios"] for r in rows),
            "missing": sum(r["missing"] for r in rows)}
    info["ie"] = ie_view(study.get("ie"), {n["id"] for n in nodes if n["type"] == "scenario"}, idx, node, link)
    return nodes, links, info


def ie_view(bundle, scenario_ids, idx, node, link):
    """⑥ 초기사건 투영(설계 §8 P3): IE 인계 묶음 dict(hazop.ie.bundle)에서 이 도면 시나리오에서 온 후보와 그 그룹·표제·
    최종상태·일반 범주, 이 도면 기기에 걸린 기본사건 후보를 만든다. 원본은 ⑥ 저장 파일이고 여기서는 읽기만 한다.
    node·link는 study_view의 만들기 함수라 같은 목록에 같은 층·v5=false로 들어간다. 사람이 확정하지 않은 것은 draft.
    개수 정보를 돌려준다(묶음이 없으면 None)."""
    if not bundle:
        return None
    made, n_links = set(), [0]

    def add(nid, typ, label, **kw):
        node(nid, typ, label, None, **kw)
        made.add(nid)

    def rel(kind, s, t):
        link(kind, s, t)
        n_links[0] += 1
    shown = [c for c in bundle["candidates"] if "st-" + c["entry_id"] in scenario_ids]
    groups = {g["group_id"]: g for g in bundle["groups"]}
    used = {c["group_id"] for c in shown if c["group_id"] in groups}
    for c in shown:
        cid = "st-" + c["candidate_id"]
        add(cid, "ie_candidate", "%s %s" % (c["candidate_id"], c["cause"]), draft=c["ie_origin"] != "human",
            detail={"cause": c["cause"]})
        rel("derived_from", cid, "st-" + c["entry_id"])
        if c["group_id"] in used:
            rel("member_of", cid, "st-" + c["group_id"])
    heads = {h["heading_id"]: h for h in bundle["top_events"]}
    ends = {e["end_state_id"]: e for e in bundle["end_states"]}
    refs_done = set()
    for gid in sorted(used):
        g = groups[gid]
        add("st-" + gid, "ie_group", "%s %s" % (gid, g["name"]),
            draft=g["status"] != "confirmed" or g["origin"] == "ai_draft", detail={"name": g["name"]})
        for code in g["categories"]:
            rid = "st-ref-" + code
            if rid not in refs_done:
                refs_done.add(rid)
                add(rid, "reference_ie", code)
            rel("corresponds_to", "st-" + gid, rid)
        for hid in g["heading_ids"]:
            if "st-" + hid not in made:
                h = heads[hid]
                add("st-" + hid, "top_event", "%s %s" % (hid, h["name"]), draft=h["origin"] != "human",
                    detail={"name": h["name"]})
                for e in h["entry_ids"]:
                    if "st-" + e in scenario_ids:
                        rel("heading_from", "st-" + hid, "st-" + e)
            rel("pivotal", "st-" + gid, "st-" + hid)
        for eid in g["end_state_ids"]:
            if "st-" + eid not in made:
                add("st-" + eid, "end_state", "%s %s" % (eid, ends[eid]["text"]), draft=ends[eid]["origin"] != "human",
                    detail={"text": ends[eid]["text"]})
            rel("leads_to", "st-" + gid, "st-" + eid)
    for b in bundle["basic_events"]:
        if b.get("ref") in idx:
            add("st-" + b["be_id"], "basic_event", "%s %s" % (b["be_id"], b["name"]), draft=b["origin"] != "human",
                detail={"name": b["name"], "text": b["failure_text"] or b["failure_mode"]})
            rel("basic_event_at", "st-" + b["be_id"], idx[b["ref"]])
    return {"candidates": len(shown), "groups": len(used), "nodes": len(made), "links": n_links[0]}


def screen_data(kg, graph, regions=(), candidates=None, start=None, standalone_note=None, expectations=None,
                study=None):
    """화면 JSON(dict). candidates: link_candidates.csv 행 목록 또는 None(파일 없음).
    start: A1 시작점(None이면 default_start). 알고리즘을 실행할 수 없으면 algo.enabled=false와 사유.
    expectations: 잠재 후보(expect.evaluate 결과) 또는 None(계산하지 않음).
    study: 검토 층 원본 {"node_set", "results", "note"} 또는 None(투영하지 않음, study_view)."""
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
    s_nodes, s_links, s_info = study_view(study, graph, {n["id"] for n in x_nodes})
    nodes += s_nodes
    links += s_links

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
    off = {ly["screen"] for ly in REGISTRY.data["layers"] if not ly["default_on"]}
    # 렌더러가 처음 그리는 노드(계산 제외 노드도 물리 배치에는 들어감). 기본으로 꺼진 층은 켜기 전엔 그리지 않으므로 세지 않는다
    global_count = sum(1 for n in nodes if n["layer"] not in off)
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
        "study": s_info,
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
    return "var TYPE = %s;\n  var GRP_OF = %s;\n  var GRP = %s;\n  var LAYERS = %s;\n  var XSTATES = %s;\n  var STL = %s;" % (
        js(types), js(grp_of), js(grps), js(layer_table()), js(expect_table()), js(STUDY_LAYER))


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
    store_io.write_bytes(path, data)  # 다시 만들 수 있는 화면 파일이라 지문 충돌 확인은 하지 않는다
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


# ---------------------------------------------------------------- 새 화면 지식그래프 패널(프로젝트 전체, 완료 목록 2 A6)
# 이전 ③ 화면은 도면 한 장씩 그렸다. 새 화면 패널은 프로젝트 그래프(도면 전체를 이은 망) 하나를 그린다. 계산(V5·A1~A5)은 하지 않고
# 무엇이 있고 무엇과 이어졌는지만 보인다. 잠재 후보 상태는 hazop.kg.expect가 계산한 값을 그대로 싣는다(화면에서 조건을 다시 세지 않음).
PANEL_NODE_CAP = 1500        # 한 번에 그리는 노드 수 상한. 넘으면 도면별 묶음 노드로 먼저 그리고 눌러 펼친다
KN_GROUP = "kn"              # 어느 도면에도 걸리지 않은 지식 노드 묶음
GROUP_PREFIX = "grp:"
KN_PREFIX = "kn:"
EXPECT_SHOWN = tuple(s for s, _, on in EXPECT_STATES if on)
NEIGHBORS_SHOWN = 30
ORIGIN_LABELS = {"pid_extract": "도면 추출", "human_edit": "사람 수정", "ai_draft": "AI 초안"}
EXPECT_NOTE_TEXT = "잠재 후보는 사실이 아닙니다. 규칙상 있어야 할 것을 찾아 보라는 단서이며, 부재 확정은 근거를 본 사람만 합니다."


class PanelLimit(ValueError):
    """펼친 도면의 노드가 상한을 넘음."""

    def __init__(self, count, cap):
        super().__init__("펼친 도면의 노드 %s개가 상한 %s개를 넘습니다. 다른 도면을 접거나 검색으로 좁히세요."
                         % (format(count, ","), format(cap, ",")))
        self.count, self.cap = count, cap


def _pid_label(n):
    if n.get("tag"):
        return str(n["tag"])
    if n.get("kind") == "continuation":
        first = (n.get("label_text") or "").split("\n")[0].strip()
        if first:
            return _short(first)
    return n.get("kind") or n["entity_id"].split("/")[-1]


def _kg_end(end, kn_ids, pg_nodes, by_soid):
    from hazop.graph import project
    if end.get("layer") == "knowledge":
        return kn_ids.get(end.get("ref"))
    if end.get("entity_id") and project.nid(end.get("graph_id"), end["entity_id"]) in pg_nodes:
        return project.nid(end["graph_id"], end["entity_id"])
    return by_soid.get((end.get("graph_id"), end.get("source_object_id")))


def panel_model(pg, kg=None, expectations=None):
    """프로젝트 그래프(+ 지식그래프, 잠재 후보) -> 패널 모델. 입력은 바꾸지 않는다.

    - 배관 구간은 끝이 정확히 둘이면 접어 두 끝을 바로 잇는다(관계 kind "pipe"). 끝이 하나거나 셋 이상(분기)이면 작은 노드로 남긴다.
      도면 연결 구간도 같은 방식이라 도면을 넘는 배관이 두 도면의 연결점을 바로 잇는다(cross=True).
    - 노드마다 group(도면 graph_id, 또는 도면에 걸리지 않은 지식 노드는 KN_GROUP). 지식 노드와 잠재 후보는 이어진 도면 노드의 도면에 둔다.
    - 지식그래프 관계 중 기각(rejected)은 넣지 않는다. 끝이 프로젝트 그래프에 없으면 세기만 한다(skipped).
    - 잠재 후보는 expect.evaluate 결과의 상태·재확인을 그대로 싣는다."""
    from hazop.graph import project
    drawing = {s["graph_id"]: s.get("drawing_number") or s["graph_id"] for s in pg.get("sheets") or []}
    pg_nodes = {n["entity_id"]: n for n in pg["nodes"]}
    seg_ends = {}
    for e in pg["edges"]:
        if e.get("kind") == project.PHYSICAL and len(e.get("nodes") or ()) == 2:
            seg_ends.setdefault(e["nodes"][0], []).append(e["nodes"][1])
    nodes, links = {}, []

    def add_link(lid, kind, s, t, **kw):
        links.append(dict({"id": lid, "kind": kind, "s": s, "t": t}, **kw))

    folded = set()
    for sid, ends in seg_ends.items():
        ends = list(dict.fromkeys(ends))
        seg = pg_nodes.get(sid) or {}
        if len(ends) == 2 and seg.get("node_type") == "pipe_segment":
            folded.add(sid)
            fd = seg.get("flow_direction") if isinstance(seg.get("flow_direction"), dict) else {}
            flow = [fd.get("from"), fd.get("to")] if set(ends) == {fd.get("from"), fd.get("to")} else None
            a, b = flow or ends
            add_link(sid, "pipe", a, b, line=seg.get("line_no") or seg.get("tag"), flow=bool(flow),
                     cross=seg.get("sheet") is None and bool(seg.get("sheet_link")))
    for n in pg["nodes"]:
        nid = n["entity_id"]
        if nid in folded:
            continue
        seg = n.get("node_type") == "pipe_segment"
        group = n.get("sheet") or next((pg_nodes[x]["sheet"] for x in seg_ends.get(nid, ()) if (pg_nodes.get(x) or {}).get("sheet")), None)
        nodes[nid] = {"id": nid, "layer": "pid", "type": "pipe_segment" if seg else (n.get("category") or "unclassified"),
                      "label": "" if seg else _pid_label(n), "group": group or KN_GROUP, "tag": n.get("tag")}
    for sid, ends in seg_ends.items():
        if sid not in folded:
            for x in dict.fromkeys(ends):
                add_link("%s>%s" % (sid, x), "pipe", sid, x)
    for e in pg["edges"]:
        if e.get("kind") != project.PHYSICAL and len(e.get("nodes") or ()) == 2:
            add_link(e["entity_id"], e["kind"], e["nodes"][0], e["nodes"][1])

    by_soid = {(n.get("sheet"), n.get("source_object_id")): n["entity_id"] for n in pg["nodes"] if n.get("source_object_id")}
    skipped = {"knowledge_links": 0, "rejected": 0, "expectations": 0}
    if kg:
        kn_ids = {}
        for k in kg.get("nodes") or []:
            kid = KN_PREFIX + k["id"]
            kn_ids[k["id"]] = kid
            nodes[kid] = {"id": kid, "layer": "kn", "type": k.get("node_type") or "unclassified", "label": _label(k), "group": None,
                          "ks": k.get("knowledge_status") or "confirmed", "ai": build.origin_of(k) == "ai_draft"}
        for l in kg.get("links") or []:
            if l.get("link_status") == "rejected":
                skipped["rejected"] += 1
                continue
            ends = [_kg_end((l.get("ends") or {}).get(side) or {}, kn_ids, pg_nodes, by_soid) for side in ("from", "to")]
            if None in ends or ends[0] not in nodes or ends[1] not in nodes:
                skipped["knowledge_links"] += 1
                continue
            add_link(KN_PREFIX + l["id"], l["kind"], ends[0], ends[1], st=l.get("link_status") or "confirmed")
        # 지식 노드는 이어진 도면 노드의 도면에 둔다. 지식끼리만 이어진 노드는 이웃 지식 노드의 도면을 한 번 더 따른다
        for _ in range(2):
            for l in links:
                for a, b in ((l["s"], l["t"]), (l["t"], l["s"])):
                    na, nb = nodes.get(a), nodes.get(b)
                    if na and nb and na["layer"] == "kn" and na["group"] is None and nb["group"] not in (None, KN_GROUP):
                        na["group"] = nb["group"]
        for n in nodes.values():
            if n["group"] is None:
                n["group"] = KN_GROUP

    exp_items = {}
    for it in (expectations or {}).get("items") or []:
        target = it.get("target_entity")
        if target not in nodes:
            skipped["expectations"] += 1
            continue
        xid = it["id"]
        exp_items[xid] = it
        nodes[xid] = {"id": xid, "layer": "exp", "type": "expectation", "label": _short(it["label"]), "group": nodes[target]["group"],
                      "xs": it["state"], "recheck": bool(it["recheck"]), "rule": it["rule_id"], "target": target}
        add_link("xrel-%s-t" % xid, "expects", target, xid)
        if it["state"] in ("candidate_found", "confirmed_present"):
            refs = (it.get("judgement") or {}).get("found") if it["state"] == "confirmed_present" else None
            for ref in sorted(set(refs or [f["ref"] for f in it["found"]])):
                g, _, soid = ref.partition("#")
                e = by_soid.get((g, soid))
                if e is not None and e != target and e in nodes:
                    add_link("xrel-%s-%s" % (xid, e), "satisfied_by", xid, e)

    groups = {}
    for gid in [s["graph_id"] for s in pg.get("sheets") or []] + [KN_GROUP]:
        groups[gid] = {"id": gid, "label": drawing.get(gid) or "도면 밖 지식", "kind": "kn" if gid == KN_GROUP else "sheet",
                       "count": 0, "gaps": 0}
    for n in nodes.values():
        g = groups.setdefault(n["group"], {"id": n["group"], "label": n["group"], "kind": "sheet", "count": 0, "gaps": 0})
        g["count"] += 1
        if n["layer"] == "exp" and n["xs"] in expect.GAP_STATES:
            g["gaps"] += 1
    order = [g for g in groups if groups[g]["count"]]
    links = [l for l in links if l["s"] in nodes and l["t"] in nodes]
    adj = {}
    for l in links:
        adj.setdefault(l["s"], []).append(l)
        adj.setdefault(l["t"], []).append(l)
    return {"nodes": nodes, "links": links, "groups": groups, "order": order, "adj": adj, "skipped": skipped,
            "pg_nodes": pg_nodes, "drawing": drawing, "exp_items": exp_items}


def panel_graph(model, expand=(), cap=None):
    """그릴 그래프: 펼친 묶음(expand)의 노드는 그대로, 나머지 묶음은 묶음 노드 하나("grp:<gid>", count)로. 접힌 묶음으로 가는 관계는
    묶음 노드로 이어 붙이고, 같은 두 끝으로 모이는 관계는 하나로 합쳐 개수(n)를 단다. 펼친 노드 수가 cap을 넘으면 PanelLimit."""
    cap = PANEL_NODE_CAP if cap is None else cap
    groups = model["groups"]
    want = set(expand)
    opened = [g for g in model["order"] if g in want]
    total = sum(groups[g]["count"] for g in opened)
    if total > cap:
        raise PanelLimit(total, cap)
    is_open = set(opened)
    out_nodes = [dict(n) for n in model["nodes"].values() if n["group"] in is_open]
    for g in model["order"]:
        if g not in is_open:
            gr = groups[g]
            out_nodes.append({"id": GROUP_PREFIX + g, "layer": "group", "type": gr["kind"], "label": gr["label"], "group": g,
                              "count": gr["count"], "gaps": gr["gaps"]})

    def end(i):
        n = model["nodes"][i]
        return i if n["group"] in is_open else GROUP_PREFIX + n["group"]
    seen, out_links = {}, []
    for l in model["links"]:
        s, t = end(l["s"]), end(l["t"])
        if s == t:
            continue
        if s == l["s"] and t == l["t"]:
            out_links.append(dict(l))
            continue
        key = tuple(sorted((s, t)))
        if key in seen:
            seen[key]["n"] += 1
            continue
        seen[key] = {"id": "agg:%s|%s" % key, "kind": "group", "s": key[0], "t": key[1], "n": 1}
        out_links.append(seen[key])
    return {"nodes": out_nodes, "links": out_links, "expanded": opened, "count": len(out_nodes), "cap": cap}


def panel_search(model, text, limit=20):
    """태그·이름·규칙 ID로 찾기(대소문자 무시, 부분 일치). 정확히 같은 것이 먼저, 다음은 도면 노드·지식·잠재 후보 순, 이름순."""
    q = " ".join(str(text or "").split()).casefold()
    if not q:
        return []
    hits = []
    for n in model["nodes"].values():
        keys = [str(x).casefold() for x in (n.get("tag"), n.get("label"), n.get("rule")) if x]
        if not any(q in k for k in keys):
            continue
        rank = (0 if q in keys else 1, {"pid": 0, "kn": 1, "exp": 2}.get(n["layer"], 3), str(n.get("label") or ""), n["id"])
        hits.append((rank, n))
    hits.sort(key=lambda x: x[0])
    return [{"id": n["id"], "label": n.get("label") or n["id"], "layer": n["layer"], "type": n["type"], "group": n["group"],
             "drawing": model["groups"][n["group"]]["label"]} for _, n in hits[:limit]]


def _plain_attrs(d, limit=12):
    out = []
    for k, v in sorted((d or {}).items()):
        if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip():
            out.append([k, _short(v, 80)])
        if len(out) >= limit:
            break
    return out


def _expectation_detail(model, it):
    nodes = model["nodes"]
    needs = {r[3]: list(r[4]) for r in expect.TRANSITIONS if r[0] == it["state"] and r[2] == "human"}
    j = it.get("judgement")
    return {"label": it["label"], "rule_id": it["rule_id"], "rule_version": it["rule_version"], "basis_level": it["basis_label"],
            "basis": it["basis"], "hazop": it["hazop"], "state": it["state"], "state_label": it["state_label"],
            "auto_state_label": expect.STATES[it["auto_state"]], "recheck": bool(it["recheck"]),
            "previous_label": expect.previous_label(it) if it["recheck"] else None, "note": it.get("note"),
            "target": {"id": it["target_entity"], "label": (nodes.get(it["target_entity"]) or {}).get("label") or it["target_tag"]},
            "found": [{"ref": f["ref"], "label": f.get("tag") or f["ref"].split("#")[-1]} for f in it["found"]],
            "judgement": {k: j.get(k) for k in ("state", "action", "by", "at", "reason", "evidence")} if j else None,
            "actions": [{"action": a, "label": expect.ACTION_LABELS[a], "needs": [[k, expect.NEED_LABELS[k]] for k in needs[a]]}
                        for a in it["actions"]],
            "caution": EXPECT_NOTE_TEXT}


def panel_node(model, nid, kg=None):
    """노드 상세 또는 None: 무엇인지(what), 근거(evidence), 속성(attrs), 도면 위치(at: {sheet, local_id} 또는 None), 이웃(최대
    NEIGHBORS_SHOWN), 이 노드에 걸린 잠재 후보. 잠재 후보 노드면 expectation(규칙·근거·상태·판단 기록·할 수 있는 동작과 필수 입력)."""
    n = model["nodes"].get(nid)
    if n is None:
        return None
    nodes = model["nodes"]
    out = {"id": nid, "layer": n["layer"], "type": n["type"], "label": n.get("label"), "group": n["group"],
           "drawing": model["groups"][n["group"]]["label"], "at": None, "what": [], "evidence": [], "attrs": []}
    if n["layer"] == "pid":
        p = model["pg_nodes"][nid]
        out["what"] = ([["태그", p["tag"]]] if p.get("tag") else []) + [["종류", p.get("kind") or "-"],
                                                                      ["분류", p.get("category") or p.get("node_type") or "-"]]
        out["evidence"] = [["도면", model["drawing"].get(p.get("sheet")) or "도면 연결 구간"],
                           ["만든 곳", ORIGIN_LABELS.get(node_origin(p), node_origin(p))]]
        if p.get("source_object_id"):
            out["evidence"].append(["원본 객체", p["source_object_id"]])
        out["attrs"] = _plain_attrs(p.get("attributes"))
        if p.get("sheet") and p.get("local_id"):
            out["at"] = {"sheet": p["sheet"], "local_id": p["local_id"]}
    elif n["layer"] == "kn":
        k = next((x for x in (kg or {}).get("nodes") or [] if KN_PREFIX + x["id"] == nid), {})
        out["what"] = [["종류", k.get("node_type") or "-"], ["상태", k.get("knowledge_status") or "confirmed"]]
        out["what"] += [[f, _short(k[f], 80)] for f in ("name", "item", "text", "value", "unit") if k.get(f)]
        src = k.get("source") if isinstance(k.get("source"), dict) else {}
        out["evidence"] = _plain_attrs(src) or [["출처", "없음(근거 확인 필요)"]]
        out["evidence"].append(["만든 곳", ORIGIN_LABELS.get(build.origin_of(k), build.origin_of(k) or "-")])
    else:
        it = model["exp_items"][nid]
        t = model["pg_nodes"].get(it["target_entity"]) or {}
        out["expectation"] = _expectation_detail(model, it)
        out["what"] = [["잠재 후보", it["label"]], ["규칙", "%s(판 %s)" % (it["rule_id"], it["rule_version"])]]
        out["evidence"] = [["근거 수준", it["basis_label"]], ["근거", it["basis"]]]
        if t.get("sheet") and t.get("local_id"):
            out["at"] = {"sheet": t["sheet"], "local_id": t["local_id"]}
    around = model["adj"].get(nid, ())
    out["neighbors"] = []
    for l in around[:NEIGHBORS_SHOWN]:
        other = nodes[l["t"] if l["s"] == nid else l["s"]]
        out["neighbors"].append({"id": other["id"], "label": other.get("label") or other["type"], "layer": other["layer"],
                                 "type": other["type"], "kind": l["kind"], "drawing": model["groups"][other["group"]]["label"]})
    out["neighbors_total"] = len(around)
    out["expectations"] = [{"id": l["t"], "label": nodes[l["t"]]["label"], "xs": nodes[l["t"]]["xs"],
                            "state_label": expect.STATES[nodes[l["t"]]["xs"]], "recheck": nodes[l["t"]]["recheck"]}
                           for l in around if l["kind"] == "expects" and l["s"] == nid]
    return out
