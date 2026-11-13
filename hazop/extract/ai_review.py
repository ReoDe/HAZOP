"""② 추출 뒤 AI 검토: 스크립트가 못 읽은 곳에 AI 후보를 받는다(INTENT.md §3.2, docs/specs/extraction.md '읽기 품질 지표').

스크립트 추출이 먼저이고 AI는 후보만 낸다. 후보는 추출 결과를 바꾸지 않고 따로 저장한다
(<작업 루트>/data/ai-review/<추출 이름>.json, origin "ai", 확신도, 근거). 사람이 수락하면 사람 수정 기록
(hazop.extract.corrections)에 연산으로 들어가고, 되돌리면 그 연산을 지운다. 그래서 AI 검토 없이 다시 추출하면
스크립트 결과는 늘 같다.

후보를 받는 곳(task):
- kind: 종류를 못 정한 기호(미분류 노드)
- tag: 이름표가 없는 밸브·계기·설비, 정상·고장 위치가 필요한데 없는 밸브
- connection: 한쪽 끝이 비어 있는 배관(열린 끝 근처 기호 가운데 하나를 고름), 목적지를 못 읽은 도면 밖 연결 표기
- recheck: 읽은 결과 표본(도면 이름으로 정한 씨앗)을 다시 확인. 같으면 '확인'으로만 세고 후보를 만들지 않는다

그림 대신 글: 구독 CLI 호출(hazop.study.claude_cli)은 표준 입력으로 글만 보내고 도구를 모두 끈다. 그림 파일을 넘길 길이
없으므로 그 자리의 벡터 자료(상자 좌표, 주변 글자와 위치, 이웃 기호의 종류·태그, 열린 끝 근처 기호)를 글로 풀어 보낸다.
Qt 의존 없음. 클라이언트는 analyze(request) 계약(구독·API·고정 응답 같은 꼴)을 쓴다.
"""

import copy
import hashlib
import json
import math
import random

from hazop import paths, store_io
from hazop.extract import corrections, rules
from hazop.study import providers
from hazop.study.nodes import now_utc

KIND = "hazop_ai_review"
SCHEMA_VERSION = "0.1"
FIELDS = ("kind", "tag", "normal_position", "fail_position", "connection", "to_system")
TASK_ORDER = ("kind", "tag", "connection", "recheck")
NEED_TAG = {"valve", "instrument", "equipment"}
POSITION_VALUES = {"normal_position": ("NO", "NC", "LO", "LC", "LT"), "fail_position": ("FO", "FC", "FL", "FAI")}
DEFAULT_CAP = 20          # 도면당 호출 수 기본 상한(규격 'AI 검토 호출 수')
DEFAULT_BATCH = 20        # 호출 하나에 넣는 항목 수(b)
DEFAULT_RECHECK = 5       # 다시 확인 표본 수
DEFAULT_THRESHOLD = 0.85  # 묶어 수락하는 확신도 하한
SECONDS_PER_CALL = 30     # 예상 시간 어림. 실측 2026-11-13 SNP 6장 구독 6회(medium)가 추출 포함 92초(호출당 약 15초).
                          # APR1400 쪽은 항목 설명이 길어 두 배로 잡는다
NEAR_TEXT = 40.0          # 주변 글자 반경(pt)
NEAR_NODE = 60.0          # 이웃 기호 반경(pt)
PARTNER_REACH = 30.0      # 열린 끝에서 이을 후보 기호까지 거리(pt)


# ---------------------------------------------------------------- 대상 고르기

def _box(obj):
    g = obj.get("geometry") or {}
    if "x" not in g:
        return None
    return [g["x"], g["y"], g["x"] + (g.get("width") or 0), g["y"] + (g.get("height") or 0)]


def _center(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _dist_to_box(p, b):
    dx = max(b[0] - p[0], 0, p[0] - b[2])
    dy = max(b[1] - p[1], 0, p[1] - b[3])
    return math.hypot(dx, dy)


def _current(n):
    a = n.get("attributes") or {}
    return {"kind": n.get("kind"), "tag": n.get("tag"), "normal_position": a.get("normal_position"),
            "fail_position": a.get("fail_position"), "label_text": (n.get("label_text") or "")[:80]}


def _has_target(n):
    a = n.get("attributes") or {}
    return bool(a.get("to_system") or a.get("to_drawing") or ":" in (a.get("to_label") or n.get("label_text") or ""))


def _item(task, obj, ask, item_id=None, **more):
    b = _box(obj)
    return dict({"item_id": item_id or "%s-%s" % (task[0], obj["source_object_id"]), "task": task,
                 "target": obj["source_object_id"], "local_id": obj["local_id"], "bbox": b, "ask": list(ask),
                 "current": _current(obj)}, **more)


def _partners(ex, rel, open_end):
    """열린 끝 점에서 PARTNER_REACH 안의 기호(붙은 기호·티 제외), 가까운 순."""
    pt = open_end.get("point")
    if not pt:
        return []
    attached = {e.get("node_local_id") for e in rel["endpoints"] if e.get("node_local_id")}
    out = []
    for n in ex["nodes"]:
        b = _box(n)
        if b is None or n["local_id"] in attached or n.get("kind") == "tee":
            continue
        d = _dist_to_box(pt, b)
        if d <= PARTNER_REACH:
            out.append((round(d, 1), n))
    out.sort(key=lambda t: (t[0], t[1]["source_object_id"]))
    return [{"id": n["source_object_id"], "local_id": n["local_id"], "kind": n.get("kind"), "tag": n.get("tag"),
             "distance_pt": d} for d, n in out[:6]]


def collect_items(ex, recheck=DEFAULT_RECHECK):
    """AI에게 물을 항목 목록(우선순위 순서는 plan이 정한다)."""
    items = []
    for n in ex["nodes"]:
        if _box(n) is None or n.get("kind") == "tee":
            continue
        kind = n.get("kind")
        if kind is None:
            items.append(_item("kind", n, ["kind"]))
            continue
        cat = rules.KIND_CATEGORY.get(kind)
        if cat in NEED_TAG and not n.get("tag"):
            items.append(_item("tag", n, ["tag"]))
        a = n.get("attributes") or {}
        ask = [f for f, kinds in (("normal_position", rules.KINDS_NEED_NORMAL_POSITION),
                                  ("fail_position", rules.KINDS_NEED_FAIL_POSITION)) if kind in kinds and not a.get(f)]
        if ask:
            items.append(_item("tag", n, ask, item_id="p-%s" % n["source_object_id"]))
        if kind == "continuation" and not _has_target(n):
            items.append(_item("connection", n, ["to_system"]))
    for rel in ex.get("unresolved_connectors") or []:
        open_ends = [e for e in rel["endpoints"] if not e.get("node_local_id")]
        if rel.get("kind") != "physical_connection" or len(open_ends) != 1:
            continue
        partners = _partners(ex, rel, open_ends[0])
        if not partners:
            continue  # 이을 후보가 없는 끝은 물어도 고를 것이 없다
        pt = open_ends[0]["point"]
        items.append({"item_id": "c-%s" % rel["source_object_id"], "task": "connection", "target": rel["source_object_id"],
                      "local_id": rel["local_id"], "bbox": [pt[0] - 4, pt[1] - 4, pt[0] + 4, pt[1] + 4],
                      "ask": ["connection"], "open_end": open_ends[0]["end"], "open_point": pt,
                      "attached": [e.get("source_object_id") for e in rel["endpoints"] if e.get("node_local_id")],
                      "attached_local": [e.get("node_local_id") for e in rel["endpoints"] if e.get("node_local_id")],
                      "partners": partners, "current": {}})
    if recheck:
        asked = {i["target"] for i in items}
        pool = sorted((n for n in ex["nodes"] if n.get("kind") not in (None, "tee") and n.get("tag")
                       and n["source_object_id"] not in asked and _box(n) is not None),
                      key=lambda n: n["source_object_id"])
        seed = int(hashlib.sha256(json.dumps((ex.get("drawing") or {}).get("drawing_number")).encode()).hexdigest()[:8], 16)
        for n in random.Random(seed).sample(pool, min(recheck, len(pool))):
            items.append(_item("recheck", n, ["kind", "tag"]))
    return items


def plan(items, cap=DEFAULT_CAP, batch=DEFAULT_BATCH):
    """우선순위(종류 → 태그·위치 → 연결 → 다시 확인)로 줄 세워 호출 묶음으로 나눈다. 상한을 넘는 항목 수는 left."""
    ordered = sorted(items, key=lambda i: TASK_ORDER.index(i["task"]))
    calls = [ordered[i:i + batch] for i in range(0, len(ordered), batch)]
    kept = calls[:max(0, cap)]
    return {"calls": kept, "left": len(ordered) - sum(len(c) for c in kept), "needed": len(calls)}


def estimate(ex, cap=DEFAULT_CAP, batch=DEFAULT_BATCH, recheck=DEFAULT_RECHECK):
    """추출 결과에서 예상 호출 수·시간. → {items, calls, needed, left, seconds}."""
    items = collect_items(ex, recheck)
    p = plan(items, cap, batch)
    return {"items": len(items), "calls": len(p["calls"]), "needed": p["needed"], "left": p["left"],
            "seconds": len(p["calls"]) * SECONDS_PER_CALL}


# ---------------------------------------------------------------- 그 자리를 글로 풀기

def describe(ex, item):
    """항목 자리의 벡터 자료를 글(사전)로 푼다: 상자, 지금 값, 주변 글자(상대 위치), 이웃 기호, 열린 끝 후보."""
    b = item["bbox"]
    c = _center(b)
    texts = []
    for t in ex.get("texts") or []:
        tb = _box(t)
        if tb and _dist_to_box(c, tb) <= NEAR_TEXT and (t.get("text") or "").strip():
            tc = _center(tb)
            texts.append({"text": t["text"][:60], "dx": round(tc[0] - c[0]), "dy": round(tc[1] - c[1])})
    near = []
    for n in ex["nodes"]:
        nb = _box(n)
        if nb is None or n["local_id"] == item.get("local_id") or n.get("kind") == "tee":
            continue
        d = _dist_to_box(c, nb)
        if d <= NEAR_NODE:
            nc = _center(nb)
            near.append({"kind": n.get("kind"), "tag": n.get("tag"), "label": (n.get("label_text") or "")[:40],
                         "dx": round(nc[0] - c[0]), "dy": round(nc[1] - c[1]), "w": round(nb[2] - nb[0], 1),
                         "h": round(nb[3] - nb[1], 1)})
    near.sort(key=lambda x: abs(x["dx"]) + abs(x["dy"]))
    texts.sort(key=lambda x: abs(x["dx"]) + abs(x["dy"]))
    out = {"item_id": item["item_id"], "task": item["task"], "ask": item["ask"], "target": item["target"],
           "bbox_pt": [round(v, 1) for v in b], "size_pt": [round(b[2] - b[0], 1), round(b[3] - b[1], 1)],
           "current": item.get("current") or {}, "texts_near": texts[:12], "symbols_near": near[:10]}
    if item["task"] == "connection" and item.get("partners"):
        out["partners"] = item["partners"]
        out["open_point"] = item.get("open_point")
    return out


SYSTEM = """너는 원자력 발전소 P&ID(배관계장도)를 읽는 검토자다. 결정적 스크립트가 벡터 PDF를 읽고 못 정한 곳을 받아 '후보'를 낸다.
너의 답은 사람이 확인하기 전까지 후보일 뿐이다. 그림은 없고, 그 자리의 상자 좌표(pt, 왼쪽 위 원점), 주변 글자와 상대 위치(dx, dy),
이웃 기호의 종류·태그를 글로 받는다.

규칙
- item마다 ask에 적힌 필드만 답한다. values의 첫 값이 너의 답이고, 다음 값은 차선이다.
- kind는 아래 목록에서만 고른다: {kinds}. 목록에 맞는 것이 없으면 답하지 않는다.
- tag는 주변 글자에 실제로 있는 글자만 쓴다(예: 'V1430', '021', 'PT 106'). 지어내지 않는다.
- normal_position은 {npos}, fail_position은 {fpos} 가운데 주변 글자에 있는 것만.
- connection은 partners에 있는 id 가운데 하나, 또는 'none'(어느 것과도 이어지지 않음).
- to_system은 도면 밖 연결 표기의 계통 약어(글자에 'CV:'처럼 있을 때만).
- recheck 항목은 지금 값(current)이 맞는지 본다. 맞으면 지금 값을 그대로 values에 넣는다.
- 확신도(confidence)는 0~1. 근거 글자가 바로 옆에 있으면 높게, 추측이면 0.5 아래로.
- reason에는 근거를 한국어로 짧게 쓴다."""


def schema():
    item = {"type": "object", "additionalProperties": False,
            "required": ["item_id", "field", "values", "confidence", "reason"],
            "properties": {"item_id": {"type": "string"}, "field": {"type": "string", "enum": list(FIELDS)},
                           "values": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                           "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                           "reason": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["answers"],
            "properties": {"answers": {"type": "array", "items": item}}}


def build_request(ex, call_items):
    """analyze(request) 계약의 요청. context는 항목 설명 JSON(도면 번호 포함), user는 지시 한 줄."""
    drawing = (ex.get("drawing") or {}).get("drawing_number")
    ctx = {"drawing": drawing, "items": [describe(ex, i) for i in call_items]}
    return {"system": SYSTEM.format(kinds=", ".join(sorted(rules.KIND_CATEGORY)),
                                    npos="/".join(POSITION_VALUES["normal_position"]),
                                    fpos="/".join(POSITION_VALUES["fail_position"])),
            "context": json.dumps(ctx, ensure_ascii=False, sort_keys=True),
            "user": "위 items 각각에 대해 ask의 필드를 답하라. 모르면 그 항목은 빼라.",
            "schema": schema()}


# ---------------------------------------------------------------- 실행

def make_candidate(item_id, task, obj_or_item, field, values, confidence, reason, extra=None):
    target = obj_or_item.get("target") or obj_or_item.get("source_object_id")
    local = obj_or_item.get("local_id")
    cand = {"cand_id": "%s:%s" % (item_id, field), "item_id": item_id, "task": task, "target": target, "local_id": local,
            "bbox": obj_or_item.get("bbox") or _box(obj_or_item), "field": field, "values": list(values),
            "confidence": float(confidence), "reason": reason, "origin": "ai", "status": "proposed", "op_id": None,
            "decided_at": None, "decided_by": None}
    if extra:
        cand.update(extra)
    return cand


def _valid(item, ans):
    f, vals = ans.get("field"), [str(v).strip() for v in ans.get("values") or [] if str(v).strip()]
    if f not in item["ask"] or not vals:
        return None
    v = vals[0]
    if f == "kind" and v not in rules.KIND_CATEGORY:
        return None
    if f in POSITION_VALUES and v not in POSITION_VALUES[f]:
        return None
    if f == "connection" and v != "none" and v not in {p["id"] for p in item.get("partners") or []}:
        return None
    if f == "tag" and not any(ch.isdigit() for ch in v):
        return None
    return f, vals


def run(ex, client, cap=DEFAULT_CAP, batch=DEFAULT_BATCH, recheck=DEFAULT_RECHECK, on_progress=None,
        should_stop=None):
    """AI 검토 한 번. ex는 바꾸지 않는다. → 후보 문서(저장 전): {candidates, stats, runs}.
    on_progress(끝낸 호출 수, 이번 호출 수, 남은 항목 수), should_stop() → True면 다음 호출 전에 멈춘다.
    멈춤·오류 규칙은 providers.halts(같은 오류 3번, 한도·인증 등 즉시 멈춤)를 따른다."""
    ex = copy.deepcopy(ex)
    items = collect_items(ex, recheck)
    p = plan(items, cap, batch)
    by_id = {i["item_id"]: i for i in items}
    cands, kinds = [], []
    stats = {"items": len(items), "planned_calls": len(p["calls"]), "needed_calls": p["needed"], "calls": 0,
             "errors": 0, "dropped": 0, "confirmed": 0, "halted": False, "stopped": False, "left": p["left"],
             "error_kinds": []}
    done_items = 0
    for n, call in enumerate(p["calls"]):
        if should_stop and should_stop():
            stats["stopped"] = True
            break
        res = client.analyze(build_request(ex, call))
        stats["calls"] += 1
        kind = res.get("error_kind") if res.get("status") != "completed" else None
        if kind is None and res.get("status") != "completed":
            kind = providers.api_error_kind(res)[0] or "other"
        kinds.append(kind)
        if kind:
            stats["errors"] += 1
            stats["error_kinds"].append(kind)
        else:
            done_items += len(call)
            ids = {i["item_id"] for i in call}
            for ans in (res.get("output") or {}).get("answers") or []:
                item = by_id.get(ans.get("item_id")) if ans.get("item_id") in ids else None
                ok = _valid(item, ans) if item else None
                if not ok:
                    stats["dropped"] += 1
                    continue
                f, vals = ok
                if item["task"] == "recheck" and (item["current"].get(f) or "") == vals[0]:
                    stats["confirmed"] += 1
                    continue
                if f == "connection" and vals[0] == "none":
                    continue
                extra = None
                if f == "connection":
                    partner = next(x for x in item["partners"] if x["id"] == vals[0])
                    extra = {"open_end": item["open_end"], "attached_local": item["attached_local"],
                             "partner_local": partner["local_id"]}
                cands.append(make_candidate(item["item_id"], item["task"], item, f, vals, ans.get("confidence") or 0,
                                            ans.get("reason") or "", extra))
        if on_progress:
            on_progress(n + 1, len(p["calls"]), len(items) - done_items)
        if providers.halts(kinds):
            stats["halted"] = True
            break
    stats["left"] = len(items) - done_items
    return {"candidates": _dedupe(cands), "stats": stats}


def _dedupe(cands):
    seen, out = set(), []
    for c in cands:
        if c["cand_id"] not in seen:
            seen.add(c["cand_id"])
            out.append(c)
    return out


# ---------------------------------------------------------------- 묶음 수락과 검사 꼴

def bulk_groups(doc, threshold=DEFAULT_THRESHOLD):
    """확신도가 threshold 이상인 제안 후보를 필드별로 묶는다. → {field: [cand_id]}."""
    out = {}
    for c in doc["candidates"]:
        if c["status"] == "proposed" and c["confidence"] >= threshold:
            out.setdefault(c["field"], []).append(c["cand_id"])
    return out


def to_check_candidates(doc):
    """scripts/check_read_quality.py --ai-candidates 꼴. 사람이 손대기 전 값이므로 상태와 관계없이 모든 AI 후보를 넣는다."""
    out = []
    for c in doc["candidates"]:
        if c["field"] == "connection":
            if c.get("attached_local"):
                out.append({"field": "connection", "a": c["attached_local"][0], "b": c["partner_local"],
                            "values": ["connected"]})
        else:
            out.append({"node_local_id": c["local_id"], "field": c["field"], "values": c["values"]})
    return {"candidates": out}


# ---------------------------------------------------------------- 저장·수락·되돌리기

def store_path(name):
    return paths.folder("ai-review", paths.safe_name(name) + ".json")


def new_doc(name, ex):
    return {"kind": KIND, "schema_version": SCHEMA_VERSION, "extraction_name": name,
            "drawing_number": (ex.get("drawing") or {}).get("drawing_number"), "runs": [], "candidates": []}


def load_doc(name):
    data, _ = store_io.read_bytes(store_path(name))
    if data is None:
        return None
    doc = json.loads(data.decode("utf-8"))
    if doc.get("kind") != KIND:
        raise ValueError("AI 검토 후보 파일이 아님: %s" % store_path(name))
    return doc


def save_doc(doc):
    return store_io.write_json(store_path(doc["extraction_name"]), doc)


def merge_run(doc, result, via=None, model=None, at=None):
    """run 결과를 문서에 더한다. 이미 있는 후보(같은 cand_id)는 사람이 정한 상태를 지키고 새 값만 갱신하지 않는다."""
    have = {c["cand_id"] for c in doc["candidates"]}
    doc["candidates"] += [c for c in result["candidates"] if c["cand_id"] not in have]
    doc["runs"].append(dict(result["stats"], at=at or now_utc(), via=via, model=model))
    return doc


def _op_for(c):
    v = c["values"][0]
    if c["field"] == "kind":
        return "set_kind", {"kind": v, "category": rules.KIND_CATEGORY[v]}
    if c["field"] == "tag":
        return "set_tag", {"tag": v}
    if c["field"] in POSITION_VALUES:
        return "set_" + c["field"], {"value": v}
    if c["field"] == "connection":
        return "set_endpoint", {"end": c["open_end"], "node": v}
    return None, None  # to_system: 맞는 수정 연산이 없다(후보 문서에만 남긴다)


def accept(doc, cand_ids, original_ex, name, by, at=None):
    """후보를 수락한다. 사람 수정 기록에 연산을 더하고 후보에 op_id를 적는다. 연산이 없는 필드(to_system)는 상태만 바꾼다.
    → 적용하지 못한 후보 [(cand_id, 사유)]. 사람 수정 기록은 읽은 지문으로 저장해 그새 바뀌었으면 store_io.Conflict."""
    rec, fp = corrections.load_fp(name)
    ops = list((rec or {}).get("ops") or [])
    failed, touched = [], []
    for c in doc["candidates"]:
        if c["cand_id"] not in cand_ids or c["status"] == "accepted":
            continue
        op, value = _op_for(c)
        if op:
            try:
                new = corrections.make_op(original_ex, op, c["target"], value, by, at=at, existing_ops=ops, name=name)
            except ValueError as exc:
                failed.append((c["cand_id"], str(exc)))
                continue
            ops.append(new)
            c["op_id"] = new["op_id"]
        c.update(status="accepted", decided_at=at or now_utc(), decided_by=by)
        touched.append(c["cand_id"])
    if any(c["op_id"] for c in doc["candidates"] if c["cand_id"] in touched):
        corrections.save_fp(name, ops, by, drawing_number=doc.get("drawing_number"), at=at, expect=fp)
    save_doc(doc)
    return failed


def reject(doc, cand_ids, by, at=None):
    for c in doc["candidates"]:
        if c["cand_id"] in cand_ids and c["status"] == "proposed":
            c.update(status="rejected", decided_at=at or now_utc(), decided_by=by)
    save_doc(doc)


def revert(doc, cand_ids, name, by, at=None):
    """수락·거절을 되돌린다. 수락으로 넣은 연산은 사람 수정 기록에서 지운다."""
    rec, fp = corrections.load_fp(name)
    ops = list((rec or {}).get("ops") or [])
    drop = set()
    for c in doc["candidates"]:
        if c["cand_id"] in cand_ids and c["status"] in ("accepted", "rejected"):
            if c.get("op_id"):
                drop.add(c["op_id"])
            c.update(status="proposed", op_id=None, decided_at=at or now_utc(), decided_by=by)
    if drop:
        corrections.save_fp(name, [o for o in ops if o["op_id"] not in drop], by,
                            drawing_number=doc.get("drawing_number"), at=at, expect=fp)
    save_doc(doc)
