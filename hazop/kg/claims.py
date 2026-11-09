"""속성 주장(property claim): 도면 속성과 문서 값을 같은 형식으로 모은다.

근거: 기획서/지식그래프-스키마-사전.md §1.2(주장 필드), 기획서/지식그래프-스키마.md KD4·§3(태그 추정은 tag 주장만 가설).
- 도면 주장: 참조한 P&ID 그래프 노드의 태그(배관 구간은 배관 번호)와 attributes 가운데 레지스트리 속성 사전에 있는 이름.
  graph.json은 읽기만 한다(graph_version 불변). 값은 원문 그대로 두고, 수량 속성은 '숫자 단위(g/a)' 꼴일 때만 나눠 읽는다.
- 문서 주장: 충돌 비교 관계(레지스트리 conflict_check, has_setpoint·has_condition)로 P&ID 노드에 붙은 설정치·운전조건 값.
  설정치·운전조건 노드는 그대로 두고 값만 주장으로 옮겨 적는다(사전 §1.2 마지막 문단, D5 유지).
- 같은 대상의 어느 주장끼리 비교할지는 compare_key가 정한다. 문서 항목(item)이 레지스트리 속성의 knowledge_items에 있고
  대상 클래스가 그 속성을 가질 때만 도면 속성과 같은 칸으로 본다. 아니면 지금처럼 (노드 종류, 항목)끼리만 비교한다.
- 단위 환산(unit_normalized·value_normalized)은 하지 않고 null로 둔다. 단위가 다르면 충돌로 보는 기존 K7 규칙을 그대로 쓴다.
"""

import hashlib

from hazop.kg.docextract import BASIS, VALUE_RE
from hazop.kg.schema import REGISTRY

INFERRED_MARK = "[추론]"
# 종류·태그(배관 구간은 배관 번호)는 노드 필드가 원본이다(② 수정은 attributes가 아니라 노드 필드를 바꾼다).
# attributes에 같은 이름이 있어도 주장으로 옮기지 않는다.
NODE_FIELD_PROPS = ("kind", "tag")


def claim_id(target, prop_key, holder):
    raw = "|".join(str(x) for x in (target, prop_key, holder))
    return "claim-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def stable_ref(graph_id, source_object_id):
    return "%s#%s" % (graph_id, source_object_id)


def pid_class(node):
    """P&ID 노드 -> 레지스트리 클래스 ID(kind 클래스, 없으면 분류). 모르면 None."""
    cid = REGISTRY.kind_class.get(node.get("kind"))
    if cid is None and node.get("category") in REGISTRY.classes:
        cid = node["category"]
    return cid


def parse_quantity(text):
    """'17.2 MPa'·'8 bar(g)' -> (값, 단위, 압력 기준). 그 꼴이 아니면 (원문, None, None)."""
    s = str(text).strip()
    m = VALUE_RE.match(s)
    if not m or m.end() != len(s):
        return s, None, None
    basis = (m.group("basis1") or m.group("basis2") or "").lower()
    return m.group("value").replace(",", ""), m.group("punit") or m.group("ounit"), BASIS.get(basis)


def _record(target, prop, holder, value, unit=None, basis=None, mode=None, item=None, node_type=None, **meta):
    rec = {"id": claim_id(target, prop or "%s/%s" % (node_type, item), holder), "target": target, "property": prop,
           "item": item, "node_type": node_type, "value": value, "value_min": None, "value_max": None,
           "unit": unit, "unit_normalized": None, "value_normalized": None,
           "pressure_basis": basis, "operating_mode": mode, "holder": holder}
    rec.update(meta)
    return rec


def drawing_claims(graph):
    """P&ID 그래프 -> 도면 주장 목록(노드 순서, 노드 안에서는 태그 다음 속성 이름순)."""
    gid, gver = graph["graph_id"], graph["graph_version"]
    out = []
    for n in graph["nodes"]:
        soid = n.get("source_object_id")
        if not soid:
            continue
        target = stable_ref(gid, soid)
        src = {"graph_id": gid, "graph_version": gver, "source_object_id": soid}
        ops = set(((n.get("human_edit") or {}).get("ops")) or [])

        def meta(edited, status="confirmed"):
            return {"origin": "human_edit" if edited else "pid_extract", "method": "manual" if edited else "extractor",
                    "source": dict(src), "knowledge_status": status, "display": "inline", "link": None}
        tag_prop = "line_no" if n.get("node_type") == "pipe_segment" else "tag"
        if n.get("tag"):
            basis = n.get("tag_basis") or ""
            edited = basis == "human" or "set_tag" in ops
            # PDF에서 계통 접두를 추정한 태그: 노드는 그대로 두고 이 주장만 가설(설계안 §3)
            status = "hypothesis" if INFERRED_MARK in basis else "confirmed"
            out.append(_record(target, tag_prop, None, n["tag"], **meta(edited, status)))
        for name in sorted(n.get("attributes") or {}):
            value = n["attributes"][name]
            spec = REGISTRY.properties.get(name)
            if spec is None or name in NODE_FIELD_PROPS or name == tag_prop or value in (None, ""):
                continue
            unit = basis = None
            if spec["type"] == "quantity":
                value, unit, basis = parse_quantity(value)
            out.append(_record(target, name, None, str(value), unit, basis, **meta("set_" + name in ops)))
    return out


def knowledge_claim(link, node, pid_node, graph_id):
    """충돌 비교 관계 하나 -> 문서 주장. pid_node는 관계 시작 끝의 P&ID 노드."""
    target = stable_ref(graph_id, pid_node["source_object_id"])
    prop = REGISTRY.property_of_item(node.get("node_type"), node.get("item"))
    if prop is not None and prop not in REGISTRY.class_properties(pid_class(pid_node)):
        prop = None  # 그 속성이 없는 클래스(예: 전송기의 '설정압력')는 도면 속성과 비교하지 않음
    return _record(target, prop, node["id"], node.get("value"), node.get("unit"), node.get("pressure_basis"),
                   node.get("operating_mode"), node.get("item"), node.get("node_type"),
                   origin=node.get("origin"), method=node.get("method"), source=node.get("source"),
                   knowledge_status=node.get("knowledge_status"), display="node", link=link["id"])


def compare_key(claim):
    """같은 대상 안에서 서로 비교할 칸."""
    if claim["property"] is not None:
        return ("property", claim["property"])
    return ("item", claim["node_type"], claim["item"])


def member_id(claim):
    """충돌 members에 적는 값: 지식 노드 ID, 도면 주장이면 대상 안정 참조."""
    return claim["holder"] or claim["target"]
