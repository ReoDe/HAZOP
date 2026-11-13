"""정리된 보기(docs/design/app-shell-web.md §10)가 그리는 데 더 필요한 자료. Qt를 import하지 않는다.

`sheet_items.build_items`(도면 읽기 API의 `items`)는 그대로 두고, 같은 추출 결과에서 그리기용 값만 따로 모은다. 웹은 `/api/clean/<graph_id>`로
읽어 `items`와 같은 `id`로 잇는다. 좌표는 `items`와 같은 SVG 사용자 단위다(추출 좌표에서 svg_alignment.offset을 뺌). 엔진은 자료를 바꾸지 않고 읽기만 한다.

기호(symbol)마다: `orient`{rot, flip_h, flip_v, basis}, `review`, 다른 도면 연결이면 `label`(원본 글자 두 줄 안).
배관(pipe)마다: `line_type`, `flow`(source_to_target·target_to_source·None), `ends`[{point, status, node}], `review`.
도면마다: `source_format`(drawio·dexpi·pdf_vector·raster·unknown), `text_items`, `unconfirmed`, `counts`, `unplaced`, `leftovers`.

미확인은 추출이 남긴 미확인 목록 전체다(규격 §10.4): `validation.unknowns` 전체(check 코드가 사유), `unresolved_connectors`, 분류 안 된 기호, 열린 끝,
태그 없음, 수락 전 AI 후보, 위치 없음. 같은 대상의 여러 사유는 따로 센다. 좌표가 없는 구성요소·관계는 버리지 않고 `unplaced`로 세어 돌려준다
(도면에 그릴 자리가 없으므로 목록에서만 보인다).
"""

import re

from hazop.shell import sheet_items

TAGGED = ("equipment", "valve", "instrument")        # 태그를 갖는 종류(없으면 '태그 없음')
TWO_PORT = ("manual_valve", "isolation_valve", "check_valve", "control_valve", "motor_operated_valve", "damper", "reducer", "orifice",
            "pump", "psv")
DIRECTION = {"east": 0, "south": 90, "west": 180, "north": 270}
# 정리된 보기가 직접 정한 사유. 그 밖의 사유는 추출의 미확인 기록(validation.unknowns)의 check 코드 그대로다
REASONS = ("unknown_symbol", "open_end", "missing_tag", "ai_candidate", "unplaced", "unresolved_connector")
KNOWN_FORMATS = ("drawio", "dexpi", "pdf_vector", "raster")


def _style(style, key):
    m = re.search(r"(?:^|;)%s=([^;]*)" % re.escape(key), style or "")
    return m.group(1) if m else None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def source_format(extraction):
    """읽은 방법. 모르는 값·빈 값은 'unknown'(가장 조심스러운 쪽: 원본이 기본, 읽은 방법 모름 꼬리표)."""
    fmt = str((extraction.get("source") or {}).get("format") or "").strip().lower()
    if fmt.startswith("pdf"):
        return "pdf_vector"
    return fmt if fmt in KNOWN_FORMATS else "unknown"


def _drawio_orient(style):
    """도형 스타일의 rotation·direction·flipH·flipV. 하나도 없으면 None."""
    rot = _num(_style(style, "rotation"))
    direction = _style(style, "direction")
    fh, fv = _style(style, "flipH") == "1", _style(style, "flipV") == "1"
    if rot is None and direction is None and not fh and not fv:
        return None
    angle = (rot or 0.0) + DIRECTION.get(direction, 0)
    return {"rot": angle % 360, "flip_h": fh, "flip_v": fv, "basis": "drawio"}


def _pipes_orient(node_id, relations, ox, oy):
    """PDF처럼 회전 정보가 없을 때: 그 기호에 붙은 배관 끝점들이 놓인 축으로 0°·90°를 정한다. 못 정하면 None."""
    pts = []
    for r in relations:
        for ep in r.get("endpoints") or []:
            if isinstance(ep, dict) and ep.get("node_local_id") == node_id:
                p = sheet_items._pair(ep.get("point"), ox, oy)
                if p is not None:
                    pts.append(p)
    if len(pts) < 2:
        return None
    dx = max(p[0] for p in pts) - min(p[0] for p in pts)
    dy = max(p[1] for p in pts) - min(p[1] for p in pts)
    if dx == dy:
        return None
    return {"rot": 90 if dy > dx else 0, "flip_h": False, "flip_v": False, "basis": "pipes"}


def _ai_pending(name):
    """수락 전 AI 후보가 걸린 대상 ID {id: [후보 ID]}. 후보 기록이 없거나 못 읽으면 빈 사전."""
    if not name:
        return {}
    try:
        from hazop.extract import ai_review
        doc = ai_review.load_doc(name)
    except Exception:  # noqa: BLE001 - 후보 기록이 없거나 깨졌다고 정리된 보기를 막지 않는다
        return {}
    out = {}
    for c in (doc or {}).get("candidates") or []:
        if isinstance(c, dict) and c.get("status") not in ("accepted", "rejected") and isinstance(c.get("target"), str):
            out.setdefault(c["target"], []).append(c.get("cand_id"))
    return out


def _leftovers(extraction, fmt, ox, oy):
    """원본에 남은 것(§10.5). 엔진이 세는 읽은 방법만 counted: drawio는 분류 못 한 셀과 일부러 뺀 셀을 준다. PDF는 남은 선을 추출 결과로
    넘기지 않아 세지 못한다(counted False): 필요한 값의 꼴은 규격 §10.5 '엔진에 필요한 것'."""
    if fmt != "drawio":
        return {"counted": False, "n": 0, "items": []}
    out = []
    for c in (extraction.get("drawing") or {}).get("ignored_objects") or []:
        bb = sheet_items._box((c or {}).get("bbox"), ox, oy) if isinstance(c, dict) else None
        out.append({"kind": "ignored", "id": (c or {}).get("source_object_id"), "bbox": bb, "text": (c or {}).get("label_text")})
    for c in extraction.get("unclassified") or []:
        if isinstance(c, dict):
            bb = sheet_items._box((c.get("label_location") or {}).get("bbox"), ox, oy) or sheet_items._box(c.get("bbox"), ox, oy)
            out.append({"kind": "unclassified", "id": c.get("local_id") or c.get("source_object_id"), "bbox": bb, "text": c.get("label_text")})
    return {"counted": True, "n": len(out), "items": out[:200]}


def build(extraction, name=None):
    """추출 결과(고친 것) -> 그리기용 자료. name은 AI 후보 기록을 찾는 도면 이름(없으면 후보를 보지 않는다)."""
    ox, oy = sheet_items._offset(extraction)
    fmt = source_format(extraction)
    relations = [r for r in extraction.get("relations") or [] if isinstance(r, dict)]
    pending = _ai_pending(name)
    items, unconfirmed, boxes, unplaced = {}, [], {}, []
    for n in extraction.get("nodes") or []:
        if not isinstance(n, dict) or not isinstance(n.get("local_id"), str):
            continue
        lid = n["local_id"]
        bbox = sheet_items._node_bbox(n, ox, oy)
        if bbox is None:                                 # 좌표가 없는 구성요소: 버리지 않고 '위치 없음'으로 센다
            unplaced.append({"id": lid, "kind": "node", "tag": n.get("tag") or None})
            unconfirmed.append({"id": lid, "reason": "unplaced"})
            continue
        boxes[lid] = bbox
        orient = _drawio_orient(n.get("style"))
        if orient is None and n.get("kind") in TWO_PORT:
            orient = _pipes_orient(lid, relations, ox, oy)
        orient = orient or {"rot": 0, "flip_h": False, "flip_v": False, "basis": "none"}
        review = "ai_candidate" if lid in pending else ("human" if n.get("human_edit") else ("ai_accepted" if n.get("origin") == "ai" else "script"))
        items[lid] = {"orient": orient, "review": review}
        if n.get("kind") == "continuation":              # 다른 도면 연결: 오각형 안에 원본 글자 그대로(최대 두 줄)
            raw = str(n.get("label_text") or n.get("tag") or "")
            items[lid]["label"] = [ln.strip()[:40] for ln in raw.splitlines() if ln.strip()][:2]
        cls = n.get("classification")
        if cls not in (None, "classified") or not n.get("kind"):
            unconfirmed.append({"id": lid, "reason": "unknown_symbol"})
        elif n.get("category") in TAGGED and not (n.get("tag") or "").strip():
            unconfirmed.append({"id": lid, "reason": "missing_tag"})
        if lid in pending:
            unconfirmed.append({"id": lid, "reason": "ai_candidate"})
    for r in relations:
        lid = r.get("local_id")
        if not isinstance(lid, str):
            continue
        line = sheet_items._points(r, ox, oy)
        if len(line) < 2:
            unplaced.append({"id": lid, "kind": "relation", "tag": r.get("line_no") or None})
            unconfirmed.append({"id": lid, "reason": "unplaced"})
            continue
        ends = []
        for ep in r.get("endpoints") or []:
            if isinstance(ep, dict):
                ends.append({"end": ep.get("end"), "point": sheet_items._pair(ep.get("point"), ox, oy), "status": "connected" if ep.get("status") == "connected" else "open",
                             "node": ep.get("node_local_id")})
        fd = r.get("flow_direction")
        basis = fd.get("basis") if isinstance(fd, dict) else None
        flow = basis if basis in ("source_to_target", "target_to_source") else None
        xs, ys = [p[0] for p in line], [p[1] for p in line]
        boxes[lid] = [min(xs), min(ys), max(xs), max(ys)]
        items[lid] = {"line_type": r.get("line_type"), "flow": flow, "ends": ends, "review": "human" if r.get("human_edit") else "script"}
        if any(e["status"] == "open" for e in ends):
            unconfirmed.append({"id": lid, "reason": "open_end"})
    for c in extraction.get("unresolved_connectors") or []:      # 끝이 미확정인 연결 전체
        if isinstance(c, dict) and isinstance(c.get("local_id"), str):
            pts = [sheet_items._pair(e.get("point"), ox, oy) for e in c.get("endpoints") or [] if isinstance(e, dict)]
            pts = [p for p in pts if p]
            if pts:
                boxes.setdefault(c["local_id"], [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)])
            unconfirmed.append({"id": c["local_id"], "reason": "unresolved_connector"})
    for u in ((extraction.get("validation") or {}).get("unknowns")) or []:   # 추출의 미확인 기록 전체(check 코드마다 하나)
        if isinstance(u, dict) and u.get("check"):
            unconfirmed.append({"id": u.get("target") if isinstance(u.get("target"), str) else None, "reason": str(u["check"]), "detail": u.get("reason")})
    seen, unique = set(), []
    for u in unconfirmed:                                # 같은 대상·같은 사유는 한 번만(다른 사유는 따로 센다)
        key = (u["id"], u["reason"])
        if key not in seen:
            seen.add(key)
            unique.append(u)
    unconfirmed = unique

    def order(u):
        b = boxes.get(u["id"]) if u["id"] else None
        if b is None:                                    # 위치 없는 것과 쪽 전체 미확인은 순서 끝
            return (1, 0, 0, str(u["id"]), u["reason"])
        return (0, round(b[1]), round(b[0]), u["id"], u["reason"])
    unconfirmed.sort(key=order)
    texts = []
    for t in extraction.get("texts") or []:
        if isinstance(t, dict) and t.get("text") and not t.get("owner"):
            bb = sheet_items._box(t.get("bbox"), ox, oy)
            if bb:
                texts.append({"text": str(t["text"]), "bbox": bb})
    counts = {}
    for u in unconfirmed:
        counts[u["reason"]] = counts.get(u["reason"], 0) + 1
    for r in REASONS:
        counts.setdefault(r, 0)
    counts["total"] = len(unconfirmed)
    counts["unplaced"] = len(unplaced)
    return {"source_format": fmt, "items": items, "text_items": texts, "unconfirmed": unconfirmed, "counts": counts, "unplaced": unplaced,
            "leftovers": _leftovers(extraction, fmt, ox, oy)}


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts == ['clean', graph_id]. 없는 도면은 None(404)."""
    from hazop.shell import api
    if len(parts) != 2:
        return None
    name = engine.graph_names().get(parts[1])
    if not name:
        return None
    from hazop.app import data
    _original, corrected = data.load_extraction(name)
    return api._json(build(corrected, name))
