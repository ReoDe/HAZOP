"""정답 extraction(drawio 추출) 대비 후보 extraction(같은 계약)의 정확도 평가 (T3 W2, 결정 D1).

평가 기준(D1):
- 태그는 속성 `tag`가 아니라 화면에 보이는 글자(`label_text` 정규화)로 비교한다.
- 화면 근거가 없는 속성(보이는 글자에 값이 없는 속성)은 주 지표 분모에서 빼고 별도 집계한다.
- 객체 대응: 글자 일치(중심 거리 이내) → bbox IoU ≥ 0.5 → kind 순으로 비용을 매겨 1:1 할당(헝가리안).
  작은 기호(정답 bbox 짧은 변 ≤ small_size_max, 예: tee 2×2)는 IoU가 민감하므로 중심 거리를 보조 기준으로 쓴다.
- 주 지표는 관계(연결) F1: 양 끝이 대응된 무방향 쌍과 관계 kind가 같아야 일치.
- GED(networkx)는 보조 지표. 동형이면 0(정확), 아니면 시간 제한으로 계산하고 실패하면 미계산으로 표시한다.

좌표계: 추정하지 않는다. 후보 좌표계가 정답과 다르면 호출자가 transform(후보 → 정답 좌표)을 넘겨야 하며,
없으면 평가를 blocked로 둔다. 같은 좌표계(coordinate_space·unit 일치)면 항등 변환을 쓴다.

사용하는 입력 키: extraction_run_id, source.file, coordinate_system.coordinate_space·unit,
nodes(local_id·source_object_id·kind·category·label_text·tag·attributes·geometry), source_locations(local_id·bbox),
relations(local_id·kind·endpoints[].node_local_id).
"""

import json
import math
import time
import unicodedata
from collections import Counter

EVAL_VERSION = "0.2.0"

DEFAULT_PARAMS = {
    "iou_min": 0.5,            # D1: 좌표 대응 문턱
    "text_center_max": 50.0,   # 글자 일치 대응의 bbox 중심 거리 상한(정답 좌표 단위)
    "small_size_max": 10.0,    # 작은 기호 판정: 정답 bbox 짧은 변 이하
    "small_center_max": 10.0,  # 작은 기호의 중심 거리 상한
    "ged_timeout_s": 5.0,
    "ged_max_nodes": 60,
}

_FORBIDDEN = 1.0e6


def normalize_text(text):
    """보이는 글자 정규화: NFKC, 공백·줄바꿈 제거, 대문자."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    return "".join(text.split()).upper()


def text_tokens(text):
    """보임 판정용 토큰: NFKC·대문자 후 공백·줄바꿈으로 나눈 단어."""
    if text is None:
        return []
    return unicodedata.normalize("NFKC", str(text)).upper().split()


def value_visible(value, tokens):
    """속성 값의 토큰열이 보이는 글자 토큰열 안에 연속으로 그대로 있으면 True(부분 문자열은 인정하지 않음)."""
    v = text_tokens(value)
    if not v:
        return False
    return any(tokens[i:i + len(v)] == v for i in range(len(tokens) - len(v) + 1))


def parse_transform(transform):
    """{"scale": s 또는 [sx, sy], "offset": [ox, oy]} → (sx, sy, ox, oy). 정답 = 후보 × scale + offset.

    축별 scale은 0이 아닌 유한한 수. 음수는 축 반전(예: y 위쪽 증가 좌표 → drawio y 아래쪽 증가)이다.
    """
    if not isinstance(transform, dict):
        raise ValueError("transform은 dict여야 함")
    scale = transform.get("scale", 1.0)
    if isinstance(scale, (int, float)):
        scale = [scale, scale]
    offset = transform.get("offset", [0.0, 0.0])
    try:
        sx, sy = (float(v) for v in scale)
        ox, oy = (float(v) for v in offset)
    except (TypeError, ValueError):
        raise ValueError("transform scale·offset은 숫자 2개여야 함: %r" % (transform,))
    if not all(math.isfinite(v) for v in (sx, sy, ox, oy)) or sx == 0 or sy == 0:
        raise ValueError("transform scale은 0이 아니고 모든 값은 유한해야 함: %r" % (transform,))
    return sx, sy, ox, oy


def _apply(bbox, tf):
    if bbox is None or tf is None:
        return bbox
    sx, sy, ox, oy = tf
    x, y, w, h = bbox
    x1, x2 = sorted((x * sx + ox, (x + w) * sx + ox))  # 음수 scale(반전)이면 양 끝이 뒤바뀐다
    y1, y2 = sorted((y * sy + oy, (y + h) * sy + oy))
    return [x1, y1, x2 - x1, y2 - y1]


def _bbox_of(node, locations):
    bbox = locations.get(node.get("local_id"))
    if bbox is None:
        g = node.get("geometry") or {}
        if all(isinstance(g.get(k), (int, float)) for k in ("x", "y", "width", "height")):
            bbox = [g["x"], g["y"], g["width"], g["height"]]
    if bbox is None or len(bbox) != 4:
        return None
    return [float(v) for v in bbox]


def _duplicate_ids(extraction):
    """같은 local_id가 두 번 이상 나오는 nodes·source_locations 항목(덮어쓰지 않고 blocked 사유로 쓴다)."""
    out = []
    for key in ("nodes", "source_locations"):
        seen = Counter(item.get("local_id") for item in extraction.get(key) or [] if item.get("local_id") is not None)
        out += ["%s:%s" % (key, lid) for lid, n in sorted(seen.items(), key=lambda x: str(x[0])) if n > 1]
    return out


def node_view(extraction, tf=None):
    """평가에 쓰는 노드 목록(local_id 순). bbox는 tf로 정답 좌표로 옮긴다."""
    locations = {loc.get("local_id"): loc.get("bbox") for loc in extraction.get("source_locations") or []
                 if loc.get("local_id") is not None}
    out = []
    for n in extraction.get("nodes") or []:
        out.append({
            "local_id": n.get("local_id"),
            "source_object_id": n.get("source_object_id"),
            "kind": n.get("kind"),
            "category": n.get("category"),
            "tag": n.get("tag"),
            "text": normalize_text(n.get("label_text")),
            "tokens": text_tokens(n.get("label_text")),
            "attributes": n.get("attributes") or {},
            "bbox": _apply(_bbox_of(n, locations), tf),
        })
    # 동점 대응은 W1 §4.3대로 source_object_id(어댑터가 정하는 결정적 원본 ID)를 먼저 본다(Codex W2 2차 지적)
    out.sort(key=lambda v: (str(v["source_object_id"]), str(v["local_id"])))
    return out


def iou(a, b):
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = min(ax2, bx2) - max(a[0], b[0])
    ih = min(ay2, by2) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def center_distance(a, b):
    return math.hypot((a[0] + a[2] / 2) - (b[0] + b[2] / 2), (a[1] + a[3] / 2) - (b[1] + b[3] / 2))


def hungarian(cost):
    """최소 비용 1:1 할당. cost: n×m 리스트(n ≤ m 아니어도 됨). 반환: [(i, j)] (행 순)."""
    n = len(cost)
    m = len(cost[0]) if n else 0
    if n == 0 or m == 0:
        return []
    transposed = n > m
    if transposed:
        cost = [[cost[i][j] for i in range(n)] for j in range(m)]
        n, m = m, n
    INF = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    pairs = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j] != 0]
    if transposed:
        pairs = [(j, i) for i, j in pairs]
    return sorted(pairs)


def _pair_info(t, c, params):
    """대응 가능 여부와 근거. 불가면 None."""
    if t["bbox"] is None or c["bbox"] is None:
        return None
    ov = iou(t["bbox"], c["bbox"])
    dist = center_distance(t["bbox"], c["bbox"])
    text_match = bool(t["text"]) and t["text"] == c["text"]
    small = min(t["bbox"][2], t["bbox"][3]) <= params["small_size_max"]
    if text_match and dist <= params["text_center_max"]:
        basis = "text"
    elif ov >= params["iou_min"]:
        basis = "iou"
    elif small and dist <= params["small_center_max"]:
        basis = "small_center"
    else:
        return None
    kind_match = t["kind"] == c["kind"]
    # 우선순위(D1): 글자 일치 > IoU 큼 > kind 일치. 겹침이 없는 쌍(IoU 0: 작은 기호·글자 대응)은
    # IoU 단계 안에서 중심 거리가 가까운 쪽을 고른다(0~1로 정규화, IoU 항 10과 kind 항 0.001 사이).
    ov6 = round(ov, 6)
    near = 0.0
    if ov6 == 0.0:
        limit = params["small_center_max"] if basis == "small_center" else params["text_center_max"]
        near = min(1.0, dist / limit) if limit > 0 else 1.0
    cost = (0.0 if text_match else 1000.0) + 10.0 * (1.0 - ov6) + near + (0.0 if kind_match else 0.001)
    return {"basis": basis, "iou": ov, "center_distance": dist, "text_match": text_match,
            "kind_match": kind_match, "cost": cost}


def match_nodes(truth_nodes, cand_nodes, params):
    infos = [[_pair_info(t, c, params) for c in cand_nodes] for t in truth_nodes]
    cost = [[info["cost"] if info else _FORBIDDEN for info in row] for row in infos]
    pairs = []
    for i, j in hungarian(cost):
        info = infos[i][j]
        if info is not None:
            pairs.append((i, j, info))
    return pairs


def _r(x):
    return None if x is None else round(x, 6)


def prf(tp, fp, fn):
    """정답·후보가 모두 비었을 때만 null. 한쪽만 비면 해당 비율과 F1은 0."""
    if tp + fp + fn == 0:
        p = r = f = None
    else:
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": _r(p), "recall": _r(r), "f1": _r(f)}


def levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _relation_list(extraction, id_map, prefix):
    """[(local_id, key)] — key = (정렬된 양 끝 표식 쌍, kind).

    끝 표식은 튜플이라 실제 id 문자열과 충돌하지 않는다: 대응된 끝 ("node", 정답 id),
    대응 안 된 후보 끝 (prefix, "unmatched", id), 노드 없는 끝 (prefix, "none", 관계 id, 순번).
    """
    out = []
    for r in extraction.get("relations") or []:
        ends = []
        for k, e in enumerate(r.get("endpoints") or []):
            nid = e.get("node_local_id")
            if nid is None:
                ends.append((prefix, "none", str(r.get("local_id")), str(k)))
            elif id_map is None:  # 정답: 자기 id 그대로
                ends.append(("node", str(nid)))
            elif nid in id_map:
                ends.append(("node", str(id_map[nid])))
            else:
                ends.append((prefix, "unmatched", str(nid)))
        out.append((str(r.get("local_id")), (tuple(sorted(ends)), r.get("kind"))))
    out.sort()
    return out


def _relation_metrics(truth, candidate, cand_to_truth):
    truth_rel = _relation_list(truth, None, "truth")
    cand_rel = _relation_list(candidate, cand_to_truth, "cand")
    pool = Counter(key for _, key in truth_rel)
    fp = []
    for rid, key in cand_rel:
        if pool[key] > 0:
            pool[key] -= 1
        else:
            fp.append(rid)
    pool = Counter(key for _, key in cand_rel)
    fn = []
    for rid, key in truth_rel:
        if pool[key] > 0:
            pool[key] -= 1
        else:
            fn.append(rid)
    tp = len(truth_rel) - len(fn)
    out = prf(tp, len(fp), len(fn))
    out["false_positives"] = fp
    out["false_negatives"] = fn
    return out


def _graph(extraction, nodes, id_map):
    import networkx as nx
    g = nx.Graph()
    for n in nodes:
        g.add_node(id_map.get(n["local_id"], n["local_id"]), kind=n["kind"])
    kinds = {}
    for r in extraction.get("relations") or []:
        ends = [e.get("node_local_id") for e in r.get("endpoints") or []]
        if len(ends) != 2 or None in ends:
            continue
        a, b = (id_map.get(x, x) for x in ends)
        if a not in g or b not in g:
            continue
        kinds.setdefault(tuple(sorted((a, b))), []).append(str(r.get("kind")))
    for (a, b), ks in sorted(kinds.items()):
        g.add_edge(a, b, kind="|".join(sorted(ks)))
    return g


def compute_ged(truth, candidate, truth_nodes, cand_nodes, params):
    """GED 보조 지표. 노드·관계 label은 kind. 상태: exact / upper_bound_timeout / not_computed."""
    try:
        import networkx as nx
    except ImportError:
        return {"status": "not_computed", "value": None, "method": None, "reason": "networkx_unavailable"}
    g1 = _graph(truth, truth_nodes, {})
    g2 = _graph(candidate, cand_nodes, {n["local_id"]: "cand:%s" % n["local_id"] for n in cand_nodes})

    def nm(a, b):
        return a.get("kind") == b.get("kind")

    if nx.is_isomorphic(g1, g2, node_match=nm, edge_match=nm):
        return {"status": "exact", "value": 0, "method": "isomorphism", "reason": None}
    if max(g1.number_of_nodes(), g2.number_of_nodes()) > params["ged_max_nodes"]:
        return {"status": "not_computed", "value": None, "method": None, "reason": "too_many_nodes"}
    start = time.monotonic()
    try:
        value = nx.graph_edit_distance(g1, g2, node_match=nm, edge_match=nm, timeout=params["ged_timeout_s"])
    except ImportError as exc:  # networkx GED는 scipy가 필요하다
        return {"status": "not_computed", "value": None, "method": None,
                "reason": "dependency_missing: %s" % getattr(exc, "name", exc)}
    elapsed = time.monotonic() - start
    if value is None:
        return {"status": "not_computed", "value": None, "method": None, "reason": "timeout_without_path"}
    status = "upper_bound_timeout" if elapsed >= params["ged_timeout_s"] else "exact"
    return {"status": status, "value": value, "method": "networkx.graph_edit_distance", "reason": None}


def _non_visual(truth_nodes, pairs_by_truth, cand_nodes):
    """정답 노드 속성 중 보이는 글자에 값이 없는 것(화면 근거 없음)을 키별로 집계. kind는 제외.

    보임 판정은 토큰 단위다(value_visible): 'XX-V01'은 'XX-V011' 안에 있어도 보이지 않는 것으로 센다.
    """
    per_key = {}
    tag_not_visible = []
    for i, t in enumerate(truth_nodes):
        cand = cand_nodes[pairs_by_truth[i]] if i in pairs_by_truth else None
        for key in sorted(t["attributes"]):
            if key == "kind":
                continue
            value = normalize_text(t["attributes"][key])
            row = per_key.setdefault(key, {"total": 0, "visible": 0, "non_visual": 0, "non_visual_recovered": 0})
            row["total"] += 1
            if value_visible(t["attributes"][key], t["tokens"]):
                row["visible"] += 1
                continue
            row["non_visual"] += 1
            if cand is not None and normalize_text((cand["attributes"] or {}).get(key)) == value:
                row["non_visual_recovered"] += 1
        if t["tag"] and not t["text"]:
            tag_not_visible.append(t["local_id"])
    return {"by_attribute": per_key, "nodes_with_tag_but_no_visible_text": tag_not_visible}


def _info(extraction):
    cs = extraction.get("coordinate_system") or {}
    return {"extraction_run_id": extraction.get("extraction_run_id"),
            "source_file": (extraction.get("source") or {}).get("file"),
            "coordinate_space": cs.get("coordinate_space"), "unit": cs.get("unit"),
            "nodes": len(extraction.get("nodes") or []),
            "relations": len(extraction.get("relations") or [])}


def evaluate(truth, candidate, transform=None, params=None):
    """정답·후보 extraction(dict)을 비교해 결정적 결과 dict를 돌려준다.

    transform: 후보 좌표 → 정답 좌표 변환({"scale", "offset"}). 좌표계가 다를 때 필수.
    """
    prm = dict(DEFAULT_PARAMS)
    prm.update(params or {})
    t_info, c_info = _info(truth), _info(candidate)
    result = {"evaluation_version": EVAL_VERSION, "status": "ok", "reasons": [], "params": prm,
              "truth": t_info, "candidate": c_info}
    blocked = []
    for side, ext in (("truth", truth), ("candidate", candidate)):
        blocked += ["duplicate_local_id: %s %s" % (side, d) for d in _duplicate_ids(ext)]
    t_cs = (t_info["coordinate_space"], t_info["unit"])
    c_cs = (c_info["coordinate_space"], c_info["unit"])
    if None in t_cs:
        blocked.append("coordinate_system_missing: truth")
    if None in c_cs and transform is None:
        blocked.append("coordinate_system_missing: candidate (transform 없음)")
    if blocked:
        result["status"] = "blocked"
        result["reasons"] = blocked
        result["coordinate_normalization"] = {"basis": None, "transform": None, "rule": None}
        return result
    same_space = t_cs == c_cs
    if transform is not None:
        tf = parse_transform(transform)
        norm = {"basis": "input_transform",
                "transform": {"scale": [tf[0], tf[1]], "offset": [tf[2], tf[3]]},
                "rule": "truth = candidate * scale + offset"}
    elif same_space:
        tf = None
        norm = {"basis": "identity_same_coordinate_system", "transform": None, "rule": None}
    else:
        result["status"] = "blocked"
        result["reasons"].append("coordinate_system_mismatch_without_transform: truth=%s/%s candidate=%s/%s"
                                 % (t_info["coordinate_space"], t_info["unit"],
                                    c_info["coordinate_space"], c_info["unit"]))
        result["coordinate_normalization"] = {"basis": None, "transform": None, "rule": None}
        return result
    result["coordinate_normalization"] = norm

    tn = node_view(truth)
    cn = node_view(candidate, tf)
    pairs = match_nodes(tn, cn, prm)
    pairs_by_truth = {i: j for i, j, _ in pairs}
    matched_c = {j for _, j, _ in pairs}

    rows = []
    for i, j, info in pairs:
        t, c = tn[i], cn[j]
        rows.append({"truth_local_id": t["local_id"], "truth_source_object_id": t["source_object_id"],
                     "candidate_local_id": c["local_id"], "candidate_source_object_id": c["source_object_id"],
                     "basis": info["basis"], "iou": _r(info["iou"]), "center_distance": _r(info["center_distance"]),
                     "truth_kind": t["kind"], "candidate_kind": c["kind"], "kind_match": info["kind_match"],
                     "category_match": t["category"] == c["category"],
                     "truth_text": t["text"], "candidate_text": c["text"], "text_match": info["text_match"]})
    unmatched_t = [t["local_id"] for i, t in enumerate(tn) if i not in pairs_by_truth]
    unmatched_c = [c["local_id"] for j, c in enumerate(cn) if j not in matched_c]
    no_bbox = {"truth": [n["local_id"] for n in tn if n["bbox"] is None],
               "candidate": [n["local_id"] for n in cn if n["bbox"] is None]}

    objects = prf(len(pairs), len(unmatched_c), len(unmatched_t))
    objects["kind_accuracy"] = _r(sum(r["kind_match"] for r in rows) / len(rows)) if rows else None
    objects["category_accuracy"] = _r(sum(r["category_match"] for r in rows) / len(rows)) if rows else None
    confusion = Counter((r["truth_kind"], r["candidate_kind"]) for r in rows if not r["kind_match"])
    objects["kind_confusion"] = [{"truth": str(a), "candidate": str(b), "count": n}
                                 for (a, b), n in sorted(confusion.items(), key=lambda x: (str(x[0][0]), str(x[0][1])))]
    objects["without_bbox"] = no_bbox

    # 태그: 보이는 글자가 있는 정답 노드만 분모. 대응 안 된 노드는 불일치로 센다.
    visible = [i for i, t in enumerate(tn) if t["text"]]
    exact, cers, wrong = 0, [], []
    for i in visible:
        t = tn[i]
        if i in pairs_by_truth:
            c = cn[pairs_by_truth[i]]
            cers.append(levenshtein(t["text"], c["text"]) / len(t["text"]))
            if c["text"] == t["text"]:
                exact += 1
                continue
            wrong.append({"truth_local_id": t["local_id"], "truth_text": t["text"], "candidate_text": c["text"]})
        else:
            wrong.append({"truth_local_id": t["local_id"], "truth_text": t["text"], "candidate_text": None})
    # 후보 쪽 오탐: 글자가 있는 후보 노드 중 정답 글자와 일치(TP)로 쓰이지 않은 것(허위 글자 노드 포함)
    tp_cand = {pairs_by_truth[i] for i in visible
               if i in pairs_by_truth and cn[pairs_by_truth[i]]["text"] == tn[i]["text"]}
    fp_cand = [c["local_id"] for j, c in enumerate(cn) if c["text"] and j not in tp_cand]
    tags = prf(exact, len(fp_cand), len(visible) - exact)
    tags.update({"visible_total": len(visible), "exact": exact, "false_positive_candidates": fp_cand,
                 "accuracy": _r(exact / len(visible)) if visible else None,
                 "matched_with_text": len(cers), "cer_mean_matched": _r(sum(cers) / len(cers)) if cers else None,
                 "excluded_no_visible_text": len(tn) - len(visible), "mismatches": wrong})

    cand_to_truth = {cn[j]["local_id"]: tn[i]["local_id"] for i, j, _ in pairs}
    result.update({
        "objects": objects,
        "matches": rows,
        "unmatched_truth": unmatched_t,
        "unmatched_candidate": unmatched_c,
        "tags": tags,
        "relations": _relation_metrics(truth, candidate, cand_to_truth),
        "non_visual": _non_visual(tn, pairs_by_truth, cn),
        "ged": compute_ged(truth, candidate, tn, cn, prm),
    })
    return result


def dumps(result):
    """결정적 JSON 문자열(키 정렬, 끝 줄바꿈)."""
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _fmt(v):
    return "-" if v is None else ("%.4f" % v if isinstance(v, float) else str(v))


def render_report(result):
    """짧은 Markdown 보고서."""
    lines = ["# 어댑터 평가 보고서", "",
             "- 정답: `%s` (%s)" % (result["truth"]["extraction_run_id"], result["truth"]["source_file"]),
             "- 후보: `%s` (%s)" % (result["candidate"]["extraction_run_id"], result["candidate"]["source_file"]),
             "- 상태: %s" % result["status"]]
    for reason in result["reasons"]:
        lines.append("  - %s" % reason)
    norm = result.get("coordinate_normalization") or {}
    lines.append("- 좌표 정규화: %s %s" % (norm.get("basis"), json.dumps(norm.get("transform"))))
    if result["status"] != "ok":
        return "\n".join(lines) + "\n"
    o, r, t, g = result["objects"], result["relations"], result["tags"], result["ged"]
    lines += ["", "| 지표 | TP | FP | FN | 정밀도 | 재현율 | F1 |", "|---|---|---|---|---|---|---|"]
    for name, m in (("관계(주 지표)", r), ("객체", o), ("태그(보이는 글자)", t)):
        lines.append("| %s | %d | %d | %d | %s | %s | %s |" % (name, m["tp"], m["fp"], m["fn"], _fmt(m["precision"]),
                                                             _fmt(m["recall"]), _fmt(m["f1"])))
    lines += ["",
              "- 태그(보이는 글자): %d/%d 일치, 정확도 %s, 대응 쌍 평균 CER %s, 글자 없는 정답 노드 %d개 분모 제외"
              % (t["exact"], t["visible_total"], _fmt(t["accuracy"]), _fmt(t["cer_mean_matched"]),
                 t["excluded_no_visible_text"]),
              "- kind 정확도(대응 쌍): %s, category 정확도: %s" % (_fmt(o["kind_accuracy"]), _fmt(o["category_accuracy"])),
              "- GED(보조): %s, 값 %s%s" % (g["status"], _fmt(g["value"]), (", 사유 %s" % g["reason"]) if g["reason"] else ""),
              "- 대응 안 된 정답 %d개, 대응 안 된 후보 %d개" % (len(result["unmatched_truth"]),
                                                     len(result["unmatched_candidate"])),
              "", "화면 근거 없는 속성(분모 제외, 별도 집계):", ""]
    for key, row in sorted(result["non_visual"]["by_attribute"].items()):
        if row["non_visual"]:
            lines.append("- %s: %d건 중 화면 근거 없음 %d, 후보가 같은 값 %d"
                         % (key, row["total"], row["non_visual"], row["non_visual_recovered"]))
    return "\n".join(lines) + "\n"
