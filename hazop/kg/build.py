"""지식 빌더: knowledge.json + 참조 P&ID 그래프(graph.json) -> knowledge_graph.json (kg_version).

근거: 기획서/그래프활용.md §2(레이어 분리, 노드·관계 종류, 근거 규칙, ID·버전·target_ref), §3.2(mentions 재확인),
§4.1(V4 계산 포함 규칙), §7.2(검사 K1~K8).
- P&ID 레이어(graph.json)는 읽기만 한다. 지식 입력이 P&ID에 없는 연결·흐름 방향을 만들지 않는다.
- P&ID 참조는 target_ref(`graph_id:tag` 또는 `graph_id#source_object_id`)로 받고 빌드 시점에 entity_id로 푼다.
  같은 태그가 여러 개인데 `graph_id:tag`로 쓰면 자동으로 고르지 않고 차단한다(K2).
- 노드·관계 ID는 입력 그대로 쓴다. 빌더는 순번을 매기지 않는다.
- 차단 오류(blockers)가 하나라도 있으면 validation.status = blocked. 각 항목의 rule은 검사 번호(K1~K8)다.
- 같은 입력이면 같은 kg_version·같은 결과(입력 순서 유지, 집계는 정렬).
"""

import hashlib
import json
import os
import re
import shutil

import networkx as nx

from hazop.kg.inputs import SOURCE_COLUMNS, candidate_fields, normalize_tag, normalize_text, text_sha256

SCHEMA_VERSION = "0.1"
BUILDER = "hazop.kg.build"
BUILDER_VERSION = "0.1.0"

NODE_PREFIX = {"document": "doc-", "doc_chunk": "chunk-", "requirement": "req-", "setpoint": "setpt-",
               "condition": "cond-", "analysis_case": "case-"}
LINK_PREFIX = "krel-"
PID = "pid"  # 타입 쌍 표에서 P&ID 노드(drawing_object·pipe_segment)를 뜻함
# kind -> (허용 시작 타입, 허용 끝 타입) (§2.3)
LINK_TYPES = {
    "part_of": ({"doc_chunk"}, {"document"}),
    "mentions": ({"doc_chunk"}, {PID}),
    "specified_in": ({"requirement", "setpoint", "condition"}, {"doc_chunk"}),
    "governed_by": ({PID}, {"requirement"}),
    "has_setpoint": ({PID}, {"setpoint"}),
    "has_condition": ({PID}, {"condition"}),
    "depends_on": ({PID}, {PID}),
    "analyzed_in": ({PID}, {"analysis_case"}),
}
KNOWLEDGE_STATUS = ("confirmed", "unknown", "hypothesis")
LINK_STATUS = ("candidate", "confirmed", "rejected")
METHODS = ("manual", "regex", "exact_norm", "fuzzy", "extractor")
RESERVED_PREFIXES = ("entity-", "relation-", "graph-")  # P&ID ID·target_ref와 겹치는 접두어(K3)
REF_RE = re.compile(r"^(graph-[^:#]+)([:#])(.+)$")
# mentions 대상이 기록 당시와 다른 도면 버전에서 사라지거나 모호해진 경우 차단 대신 재확인(§3.2)
STALE_TARGET_CODES = ("pid_ref_not_found", "ambiguous_tag")
# 같은 대상·항목 충돌 비교에 쓰는 설비 적용 관계(K7)
CONFLICT_KINDS = {"has_setpoint": "setpoint", "has_condition": "condition"}


def _canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def kg_version(knowledge, graph_refs):
    """정규화한 지식 입력(knowledge.json 전체: 노드·관계·입력 파일 sha256·ID) + 참조한 graph_version
    + 빌더 버전(networkx 버전 포함)의 해시. 형식은 graph_version과 같다.
    출력에 들어가는 값은 모두 이 해시나 graph_version에 반영되므로 kg_version이 같으면 두 결과 파일의 바이트도 같다."""
    canon = _canon({"knowledge": knowledge, "graph_refs": graph_refs})
    head = "%s|nx=%s|" % (BUILDER_VERSION, nx.__version__)
    return "v-" + hashlib.sha256((head + canon).encode("utf-8")).hexdigest()[:12]


def _has_source(src):
    return bool(src) and (src.get("material_id") is not None or src.get("document_id") is not None)


def _source_blank(src):
    """관계 행의 근거 열 5개가 모두 비었는지(비었으면 지식 쪽 끝 노드 근거를 상속)."""
    return all((src or {}).get(c) is None for c in SOURCE_COLUMNS)


def _comparable_modes(a, b):
    """운전 모드가 같거나 한쪽이라도 빈 칸이면 비교한다(빈 칸 = 모드 미확인. 추정하지 않으므로 모든 모드와 비교)."""
    ma, mb = a.get("operating_mode"), b.get("operating_mode")
    return ma is None or mb is None or ma == mb


def _values_differ(a, b):
    """값(숫자면 숫자로)이 다르거나, 단위·압력 기준이 둘 다 적혀 있는데 다르면 True."""
    if _value_key(a.get("value")) != _value_key(b.get("value")):
        return True
    return any(a.get(f) is not None and b.get(f) is not None and a[f] != b[f] for f in ("unit", "pressure_basis"))


def _mention_problem(link, m, chunk, pid):
    """confirmed 근거로서 mentions 행 검증. 문제가 없으면 None, 있으면 (check, 사유).
    §3.2 순서: 조각 원문이 바뀌었으면(기록 text_sha256 != 현재) 위치를 검증하지 않고 None을 돌려준다.
    그 관계는 재확인 판정(recheck_required, 계산 제외)으로 넘어가며 차단하지 않는다.
    1) 대상 일치(mention_target_mismatch): 관계 to, 후보 키 target_ref, 키·행의 target_source_object_id,
       키 target_graph_id가 같은 대상을 가리켜야 함. graph_id:tag 참조는 후보 키의 target_graph_version이
       현재 그래프 버전과 같을 때만 현재 그래프에서 원본 객체 ID로 풀어 비교한다(버전이 다르면 재확인 대상).
    2) 위치(invalid_match_position). 위치는 normalize_text(조각 원문) 기준 문자(코드 포인트) 오프셋이며
       text_sha256과 같은 정규화다. 0 <= match_start < match_end <= len(정규화 원문)이어야 하고,
       대상 태그를 알 수 있으면(참조가 graph_id:tag이거나 #source_object_id 노드의 태그) 정규화 원문[start:end]가
       그 태그와 normalize_tag 기준으로 같아야 함. fuzzy(유사 일치)는 일치 문자열이 태그와 다를 수 있어
       태그 비교를 적용하지 않는다 [가정]."""
    key = candidate_fields(m.get("candidate_key")) or {}
    # 0) 후보 키와 행의 기록값 일치(mention_key_mismatch). 재확인 판정은 행 값만 비교하므로, 키와 행이 다르면
    #    키 쪽 값(예: target_graph_version)으로 대상 해석을 건너뛰는 우회가 생긴다(W3 Codex 4차 지적).
    pairs = [(f, f) for f in ("chunk_id", "text_sha256", "material_id", "registration_version",
                              "target_source_object_id")] + [("target_graph_version", "graph_version")]
    diffs = [kf for kf, rf in pairs if (key.get(kf) or None) != (m.get(rf) or None)]
    if diffs:
        return "mention_key_mismatch", "후보 키와 행의 기록값이 다름: %s" % ", ".join(diffs)
    text_raw = chunk.get("text")
    if m.get("text_sha256") != text_sha256(text_raw):
        return None  # 원문 변경 -> 재확인(아래 §3.2 판정)
    soid = key.get("target_source_object_id")
    to_hit, key_hit = REF_RE.match(link.get("to") or ""), REF_RE.match(key.get("target_ref") or "")
    if not to_hit or not key_hit:
        return "mention_target_mismatch", "후보 키 target_ref가 P&ID 참조 형식이 아님"
    current = pid.by_id.get(to_hit.group(1), [])
    same_version = len(current) == 1 and current[0]["graph_version"] == key.get("target_graph_version")

    def ref_soid_tag(hit):
        """참조 -> (원본 객체 ID 또는 None, 태그 또는 None)."""
        if hit.group(2) == "#":
            tag = None
            if same_version:
                tag = next((n.get("tag") for n in current[0]["nodes"] if n.get("source_object_id") == hit.group(3)), None)
            return hit.group(3), tag
        if same_version:
            hits = [n for n in current[0]["nodes"] if n.get("tag") == hit.group(3)]
            return (hits[0]["source_object_id"] if len(hits) == 1 else None), hit.group(3)
        return None, hit.group(3)
    to_soid, to_tag = ref_soid_tag(to_hit)
    key_soid, key_tag = ref_soid_tag(key_hit)
    diffs = []
    if {to_hit.group(1), key_hit.group(1), key.get("target_graph_id")} != {to_hit.group(1)}:
        diffs.append("graph_id")
    if soid != m.get("target_source_object_id"):
        diffs.append("후보 키·행의 target_source_object_id")
    for name, x in (("to", to_soid), ("후보 키 target_ref", key_soid)):
        if x is not None and x != soid:
            diffs.append("%s의 원본 객체(%s)" % (name, x))
    if to_tag is not None and key_tag is not None and normalize_tag(to_tag) != normalize_tag(key_tag):
        diffs.append("태그(%s/%s)" % (to_tag, key_tag))
    if diffs:
        return "mention_target_mismatch", "관계 to와 후보 키 대상이 다름: %s" % ", ".join(diffs)
    text = normalize_text(text_raw or "")
    start, end = m["match_start"], m["match_end"]
    if not (0 <= start < end <= len(text)):
        return "invalid_match_position", "위치 %d:%d가 조각 원문 범위(0:%d) 밖" % (start, end, len(text))
    tag = to_tag or key_tag
    if tag is not None and link.get("method") != "fuzzy" and normalize_tag(text[start:end]) != normalize_tag(tag):
        return "invalid_match_position", "원문[%d:%d]=%r가 대상 태그 %r와 다름" % (start, end, text[start:end], tag)
    return None


def _value_key(v):
    """설정치·운전조건 값 비교용. 숫자로 읽히면 숫자로 비교한다(8 과 8.0은 같음)."""
    if v is None:
        return None
    try:
        return ("n", float(v.replace(",", "")))
    except ValueError:
        return ("s", v)


class _PidIndex:
    """graph_id -> 태그·원본 객체 ID 색인. 그래프는 읽기만 한다."""

    def __init__(self, graphs):
        self.by_id = {}
        for g in graphs:
            self.by_id.setdefault(g["graph_id"], []).append(g)

    def resolve(self, ref):
        """target_ref -> (end dict, 오류 (code, reason) 또는 None)."""
        m = REF_RE.match(ref)
        gid, sep, key = m.group(1), m.group(2), m.group(3)
        end = {"ref": ref, "layer": "pid", "graph_id": gid, "graph_version": None, "entity_id": None,
               "node_type": None, "tag": None, "source_object_id": None}
        found = self.by_id.get(gid, [])
        if not found:
            return end, ("graph_not_found", "참조한 P&ID 그래프가 없음: %s" % gid)
        if len({g["graph_version"] for g in found}) > 1:
            return end, ("graph_ambiguous", "같은 graph_id의 그래프가 여러 버전으로 있음: %s" % gid)
        g = found[0]
        end["graph_version"] = g["graph_version"]
        if g["validation"]["status"] != "passed":
            return end, ("graph_blocked", "참조한 P&ID 그래프가 구조 검증을 통과하지 못함: %s" % gid)
        if sep == ":":
            hits = [n for n in g["nodes"] if n.get("tag") == key]
            if len(hits) > 1:
                return end, ("ambiguous_tag", "태그 %s가 %s에 %d개 - graph_id#source_object_id로 지정해야 함(%s)"
                             % (key, gid, len(hits), ", ".join(sorted(n["source_object_id"] for n in hits))))
        else:
            hits = [n for n in g["nodes"] if n.get("source_object_id") == key]
        if not hits:
            return end, ("pid_ref_not_found", "P&ID 대상이 없음: %s" % ref)
        n = hits[0]
        end.update(entity_id=n["entity_id"], node_type=n["node_type"], tag=n.get("tag"),
                   source_object_id=n["source_object_id"])
        return end, None


def build_kg(knowledge, graphs):
    """knowledge dict + P&ID graph dict 목록 -> knowledge_graph dict."""
    blockers, unknowns, review_items = [], [], []

    def block(rule, code, target, reason):
        blockers.append({"rule": rule, "check": code, "target": target, "reason": reason})

    nodes = [dict(n) for n in knowledge["nodes"]]
    links = [dict(l) for l in knowledge["links"]]
    pid = _PidIndex(graphs)

    # ---- K3: ID 필수·중복·접두어 충돌
    seen = {}
    for kind, items in (("node", nodes), ("link", links)):
        for it in items:
            if it.get("id") is None:
                block("K3", "missing_id", None, "%s 행에 id 없음" % ("노드" if kind == "node" else "관계"))
                continue
            seen[it["id"]] = seen.get(it["id"], 0) + 1
    for i, c in sorted(seen.items()):
        if c > 1:
            block("K3", "duplicate_id", i, "id가 %d번 쓰임(노드·관계 통틀어)" % c)
        if i.startswith(RESERVED_PREFIXES):
            block("K3", "id_prefix_conflict", i, "P&ID ID·참조 접두어(%s)와 겹침" % "/".join(RESERVED_PREFIXES))
    for n in nodes:
        want = NODE_PREFIX.get(n.get("node_type"))
        if n.get("id") and want and not n["id"].startswith(want):
            review_items.append({"check": "id_prefix_not_recommended", "target": n["id"],
                                 "reason": "권고 접두어 %s가 아님(차단하지 않음)" % want})
    for l in links:
        if l.get("id") and not l["id"].startswith(LINK_PREFIX):
            review_items.append({"check": "id_prefix_not_recommended", "target": l["id"],
                                 "reason": "권고 접두어 %s가 아님(차단하지 않음)" % LINK_PREFIX})

    # ---- K1: 노드 종류·필수 값·열거값
    node_by_id = {}
    for n in nodes:
        if n.get("id") is not None and n["id"] not in node_by_id:
            node_by_id[n["id"]] = n
        if n.get("node_type") not in NODE_PREFIX:
            block("K1", "unknown_node_type", n.get("id"), "목록 밖 노드 종류: %r" % n.get("node_type"))
        if n.get("knowledge_status") not in KNOWLEDGE_STATUS:
            block("K1", "invalid_knowledge_status", n.get("id"), "knowledge_status 값 오류: %r" % n.get("knowledge_status"))
        n["has_source"] = _has_source(n.get("source"))
        if not n["has_source"]:
            unknowns.append({"check": "no_source", "target": n.get("id"), "field": "source",
                             "reason": "출처 없음(근거 없음 배지). confirmed로 둘 수 없음"})
        if n.get("node_type") in ("setpoint", "condition"):
            for f in ("item", "value", "unit", "pressure_basis"):
                if n.get(f) is None:
                    unknowns.append({"check": "unknown_value", "target": n.get("id"), "field": f,
                                     "reason": "%s 미확인(빈 칸, 추정하지 않음)" % f})
        # ---- K6: 출처 없는 confirmed 노드
        if n.get("knowledge_status") == "confirmed" and not n["has_source"]:
            block("K6", "confirmed_without_source", n.get("id"), "출처(material_id·document_id) 없이 confirmed")

    # ---- 관계: 종류·끝 해석·타입 쌍·근거
    resolved_graphs = {}
    for l in links:
        lid = l.get("id")
        kind = l.get("kind")
        ok = True
        for f in ("kind", "from", "to"):
            if l.get(f) is None:
                block("K1", "missing_value", lid, "%s 없음" % f)
                ok = False
        if l.get("knowledge_status") not in KNOWLEDGE_STATUS:
            block("K1", "invalid_knowledge_status", lid, "knowledge_status 값 오류: %r" % l.get("knowledge_status"))
        if l.get("link_status") not in LINK_STATUS:
            block("K1", "invalid_link_status", lid, "link_status 값 오류: %r" % l.get("link_status"))
        if l.get("method") not in METHODS:
            block("K1", "invalid_method", lid, "method 값 오류: %r" % l.get("method"))
        if l.get("link_status") == "confirmed" and l.get("reviewed_by") is None:
            block("K1", "confirmed_without_reviewer", lid, "link_status confirmed인데 reviewed_by 없음")
        if l.get("unused_mention_columns"):
            review_items.append({"check": "unused_mention_columns", "target": lid,
                                 "reason": "mentions가 아닌 관계에 재확인 열이 채워짐(무시): %s"
                                 % ", ".join(l["unused_mention_columns"])})
        if kind is not None and kind not in LINK_TYPES:
            block("K1", "unknown_relation_kind", lid, "목록 밖 관계 종류: %r" % kind)
            ok = False
        m = (l.get("mention") or {}) if kind == "mentions" else {}
        ends = {}
        for side in ("from", "to"):
            ref = l.get(side)
            if ref is None:
                continue
            if REF_RE.match(ref):
                end, err = pid.resolve(ref)
                if err and kind == "mentions" and side == "to" and err[0] in STALE_TARGET_CODES \
                        and end["graph_version"] is not None and m.get("graph_version") != end["graph_version"]:
                    # §3.2: 확인 당시와 도면 버전이 다르면(재추출 등) 대상이 사라졌어도 차단하지 않고 재확인 대상으로 둔다.
                    # 같은 버전인데 대상이 없으면 작성 오류이므로 K2로 차단한다.
                    err = None
                if err:
                    block("K2", err[0], lid, "%s: %s" % (side, err[1]))
                    ok = False
                resolved_graphs[end["graph_id"]] = end["graph_version"]  # 없거나 모호하면 None(이미 차단)
                ends[side] = end
            elif ref in node_by_id:
                ends[side] = {"ref": ref, "layer": "knowledge", "node_type": node_by_id[ref].get("node_type")}
            else:
                block("K2", "unknown_node_reference", lid, "%s: 지식 노드가 없음: %s" % (side, ref))
                ok = False
        l["ends"] = {s: ends.get(s) for s in ("from", "to")}
        if ok and len(ends) == 2:
            allowed_from, allowed_to = LINK_TYPES[kind]
            tf = PID if ends["from"]["layer"] == "pid" else ends["from"]["node_type"]
            tt = PID if ends["to"]["layer"] == "pid" else ends["to"]["node_type"]
            if tf not in allowed_from or tt not in allowed_to:
                block("K1", "type_pair_not_allowed", lid, "%s의 허용 타입 쌍이 아님: %s -> %s" % (kind, tf, tt))
                ok = False
        l["source_inherited_from"] = None
        if kind == "mentions":
            # 근거 = 조각 ID + 원문 해시 + 일치 위치(candidate_key의 match_start·match_end). 하나라도 없으면 출처 없음(§2.4)
            l["has_source"] = all(m.get(f) is not None for f in ("chunk_id", "text_sha256", "match_start", "match_end"))
            prob = _mention_problem(l, m, node_by_id.get(l.get("from"), {}), pid) if l["has_source"] and ok else None
            if prob:
                l["has_source"] = False
                if l.get("knowledge_status") == "confirmed":
                    block("K6", prob[0], lid, "mentions 근거로 인정하지 않음: %s" % prob[1])
                    ok = False  # 아래 confirmed_without_source로 중복 보고하지 않음
                # confirmed가 아니면 아래 공통 분기에서 no_source(근거 없음)로 기록됨
            if m.get("chunk_id") is not None and m["chunk_id"] != l.get("from"):
                block("K2", "mention_chunk_mismatch", lid, "chunk_id(%s)가 from(%s)과 다름" % (m["chunk_id"], l.get("from")))
        elif kind == "depends_on":
            l["has_source"] = _has_source(l.get("source"))
            if not l["has_source"]:
                block("K6", "depends_on_without_source", lid,
                      "depends_on은 근거 열 필수(상태 %s와 관계없이 차단)" % l.get("knowledge_status"))
        else:
            if _source_blank(l.get("source")) and ok:
                know = [ends[s]["ref"] for s in ("from", "to") if ends[s]["layer"] == "knowledge"]
                donor = node_by_id[know[0]]  # 양 끝이 지식 노드면 from 쪽 [가정]
                if donor["has_source"]:  # 끝 노드에도 근거가 없으면 상속 기록을 남기지 않음
                    l["source"] = dict(donor["source"])
                    l["source_inherited_from"] = donor["id"]
            l["has_source"] = _has_source(l.get("source"))
        if not l["has_source"] and kind != "depends_on" and ok:  # 이미 차단된 관계(상속 불가)는 K6로 중복 보고하지 않음
            if l.get("knowledge_status") == "confirmed":
                block("K6", "confirmed_without_source", lid, "출처 없이 confirmed(상속할 근거도 없음)")
            else:
                unknowns.append({"check": "no_source", "target": lid, "field": "source",
                                 "reason": "출처 없음(근거 없음 배지)"})
        l["valid"] = ok

    graph_refs = [{"graph_id": g, "graph_version": v} for g, v in sorted(resolved_graphs.items())]

    # ---- §3.2 mentions 재확인
    for l in links:
        l["recheck"] = None
        if l.get("kind") != "mentions" or not l["valid"]:
            continue
        m = l.get("mention") or {}
        chunk = node_by_id.get(l["from"], {})
        tgt = l["ends"]["to"]
        now = {"text_sha256": text_sha256(chunk.get("text")),
               "material_id": (chunk.get("source") or {}).get("material_id"),
               "registration_version": (chunk.get("source") or {}).get("registration_version"),
               "graph_version": resolved_graphs.get(tgt["graph_id"]),
               "target_source_object_id": tgt["source_object_id"]}
        changed = sorted(k for k, v in now.items() if m.get(k) != v)
        if changed:
            l["recheck"] = {"changed": changed, "recorded": {k: m.get(k) for k in changed},
                            "current": {k: now[k] for k in changed}}
            unknowns.append({"check": "recheck_required", "target": l["id"], "field": ",".join(changed),
                             "reason": "재확인 필요: 기록값과 현재 값이 다름(%s). 계산 뷰에서 제외, 행은 유지"
                             % ", ".join(changed)})

    # ---- V4 계산 포함 규칙(§4.1). 차단 대상 항목도 제외(blocked 지식그래프는 계산에 쓰지 않지만 표시를 일관되게)
    blocked_ids = {b["target"] for b in blockers}
    for n in nodes:
        reasons = ["blocked"] if n.get("id") in blocked_ids else []
        if n.get("knowledge_status") != "confirmed":
            reasons.append("knowledge_status=%s" % n.get("knowledge_status"))
        n["compute_view"] = {"v4": not reasons, "excluded_reasons": reasons}
    v4_nodes = {n["id"] for n in nodes if n["compute_view"]["v4"]}
    for l in links:
        reasons = ["blocked"] if l.get("id") in blocked_ids else []
        if not l["valid"]:
            reasons.append("invalid")
        if l.get("link_status") != "confirmed":
            reasons.append("link_status=%s" % l.get("link_status"))
        if l.get("knowledge_status") != "confirmed":
            reasons.append("knowledge_status=%s" % l.get("knowledge_status"))
        for s in ("from", "to"):
            e = l["ends"][s]
            if e and e["layer"] == "knowledge" and e["ref"] not in v4_nodes:
                reasons.append("%s 끝 지식 노드가 V4 밖" % s)
        if l["recheck"]:
            reasons.append("recheck_required")
        l["compute_view"] = {"v4": not reasons, "excluded_reasons": reasons}

    # ---- K7: 같은 대상·항목의 서로 다른 값 -> 둘 다 보존하고 충돌 표시
    groups = {}
    for l in links:
        ntype = CONFLICT_KINDS.get(l.get("kind"))
        if not ntype or not l["valid"] or l.get("link_status") == "rejected":
            continue
        n = node_by_id[l["to"]]
        if n.get("item") is None:
            continue
        key = (l["ends"]["from"]["graph_id"], l["ends"]["from"]["entity_id"], ntype, n["item"])
        groups.setdefault(key, {})[n["id"]] = n
    conflicts = []
    for key, uniq in sorted(groups.items(), key=lambda kv: _canon(list(kv[0]))):
        ids = sorted(uniq)
        for x, ia in enumerate(ids):
            for ib in ids[x + 1:]:
                a, b = uniq[ia], uniq[ib]
                if not _comparable_modes(a, b) or not _values_differ(a, b):
                    continue
                conflicts.append({"graph_id": key[0], "entity_id": key[1], "node_type": key[2], "item": key[3],
                                  "members": [ia, ib],
                                  "values": [{"id": i, "value": uniq[i].get("value"), "unit": uniq[i].get("unit"),
                                              "pressure_basis": uniq[i].get("pressure_basis"),
                                              "operating_mode": uniq[i].get("operating_mode")} for i in (ia, ib)]})
                unknowns.append({"check": "conflict", "target": "%s,%s" % (ia, ib), "field": "value",
                                 "reason": "같은 대상(%s)·항목(%s)에 서로 다른 값 - 둘 다 보존" % (key[1], key[3])})
    conflict_of = {}
    for c in conflicts:
        a, b = c["members"]
        conflict_of.setdefault(a, set()).add(b)
        conflict_of.setdefault(b, set()).add(a)
    for n in nodes:
        n["conflict_with"] = sorted(conflict_of.get(n.get("id"), ()))

    for l in links:
        l.pop("valid")
        l.pop("unused_mention_columns", None)

    version = kg_version(knowledge, graph_refs)
    kg = {
        "schema_version": SCHEMA_VERSION,
        "kg_id": knowledge.get("kg_id"),
        "kg_version": version,
        "project_id": knowledge.get("project_id"),
        "builder": {"name": BUILDER, "version": BUILDER_VERSION, "networkx": nx.__version__},
        "inputs": knowledge.get("inputs"),
        "knowledge_sha256": hashlib.sha256(dump_bytes(knowledge)).hexdigest(),  # 함께 쓰는 knowledge.json의 바이트 해시
        "graph_refs": graph_refs,
        "nodes": nodes,
        "links": links,
        "conflicts": conflicts,
        "validation": {"status": "blocked" if blockers else "passed", "blockers": blockers, "unknowns": unknowns},
        "review_items": review_items,
    }
    kg["summary"] = summary(kg)
    return kg


def summary(kg):
    def count(items, key):
        out = {}
        for it in items:
            out[str(it.get(key))] = out.get(str(it.get(key)), 0) + 1
        return dict(sorted(out.items()))
    return {
        "node_count": len(kg["nodes"]),
        "link_count": len(kg["links"]),
        "node_types": count(kg["nodes"], "node_type"),
        "link_kinds": count(kg["links"], "kind"),
        "v4_nodes": sum(1 for n in kg["nodes"] if n["compute_view"]["v4"]),
        "v4_links": sum(1 for l in kg["links"] if l["compute_view"]["v4"]),
        "conflicts": len(kg["conflicts"]),
        "blockers": len(kg["validation"]["blockers"]),
        "unknowns": len(kg["validation"]["unknowns"]),
    }


def dump_bytes(obj):
    """결정적 직렬화(UTF-8, 키 정렬, 들여쓰기 2, 줄끝 LF). 입력 dict의 키 순서와 무관하게 같은 바이트."""
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_json_atomic(path, obj):
    """임시 파일에 쓴 뒤 os.replace로 교체한다. 쓴 바이트를 돌려준다."""
    data = dump_bytes(obj)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return data


KNOWLEDGE_FILE = "knowledge.json"
KG_FILE = "knowledge_graph.json"


POINTER_FILE = "current.json"


def write_outputs(kg_root, knowledge, kg):
    """<kg_root>/<kg_version>/에 knowledge.json·knowledge_graph.json을 두고, 그 뒤에만
    <kg_root>/current.json(kg_version과 두 파일 sha256)을 os.replace 한 번으로 교체한다.
    - 버전 폴더가 없으면 임시 폴더(<kg_version>.partial)에 두 파일을 다 쓴 뒤 이름을 바꿔 만든다.
    - 버전 폴더가 이미 있으면 덮어쓰지 않는다. 두 파일 바이트가 새 내용과 같으면 그대로 두고 포인터만 갱신하고,
      다르면 ValueError(같은 kg_version이면 같은 바이트여야 하므로 손상 또는 빌더 오류).
    중간에 실패하면 포인터는 이전 버전을 그대로 가리킨다. 이전 버전 폴더는 지우지 않는다(정리 정책은 후속).
    버전 폴더 경로를 돌려준다."""
    ver_dir = os.path.join(kg_root, kg["kg_version"])
    kbytes, gbytes = dump_bytes(knowledge), dump_bytes(kg)
    if os.path.exists(ver_dir):
        for name, data in ((KNOWLEDGE_FILE, kbytes), (KG_FILE, gbytes)):
            path = os.path.join(ver_dir, name)
            old = None
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    old = hashlib.sha256(fh.read()).hexdigest()
            if old != hashlib.sha256(data).hexdigest():
                raise ValueError("%s: 같은 kg_version 폴더에 다른 내용이 있음 - 덮어쓰지 않음" % path)
    else:
        tmp_dir = ver_dir + ".partial"
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)  # 이전 실패로 남은 임시 폴더(포인터가 가리킨 적 없음)
        write_json_atomic(os.path.join(tmp_dir, KNOWLEDGE_FILE), knowledge)
        write_json_atomic(os.path.join(tmp_dir, KG_FILE), kg)
        os.rename(tmp_dir, ver_dir)
    write_json_atomic(os.path.join(kg_root, POINTER_FILE),
                      {"kg_id": kg["kg_id"], "kg_version": kg["kg_version"],
                       "knowledge_sha256": hashlib.sha256(kbytes).hexdigest(),
                       "knowledge_graph_sha256": hashlib.sha256(gbytes).hexdigest()})
    return ver_dir


VERSION_RE = re.compile(r"^v-[0-9a-f]{12}$")  # kg_version 형식(kg_version()과 같은 꼴)


def _pointer_dir(kg_root, version):
    """포인터의 kg_version을 열기 전에 검사한다(T1 D10): 형식이 v-+16진 12자리가 아니거나, 버전 폴더의 realpath가
    kg 폴더(realpath) 바로 아래가 아니면 ValueError. 반환은 os.path.join(kg_root, version)."""
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise ValueError("%s: current.json의 kg_version 형식이 아님: %r" % (kg_root, version))
    path = os.path.join(kg_root, version)
    root_real, real = os.path.realpath(kg_root), os.path.realpath(path)
    if os.path.dirname(real) != root_real:
        raise ValueError("%s: 버전 폴더가 kg 폴더 밖으로 풀림: %s -> %s" % (kg_root, version, real))
    return path


def current_dir(kg_root):
    """포인터가 가리키는 버전 폴더(_pointer_dir로 형식·위치 검사)."""
    with open(os.path.join(kg_root, POINTER_FILE), encoding="utf-8") as fh:
        return _pointer_dir(kg_root, json.load(fh).get("kg_version"))


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _check_pointer(kg_root, ptr):
    """current.json 필수 키·자료형 검사(그래프활용 §6.4.1). 틀리면 KeyError가 아니라 ValueError."""
    if not isinstance(ptr, dict):
        raise ValueError("%s: current.json이 JSON 객체가 아님" % kg_root)
    if not isinstance(ptr.get("kg_id"), str) or not ptr["kg_id"]:
        raise ValueError("%s: current.json의 kg_id가 없거나 문자열이 아님" % kg_root)
    for k in ("knowledge_sha256", "knowledge_graph_sha256"):
        if not isinstance(ptr.get(k), str) or not SHA256_RE.match(ptr[k]):
            raise ValueError("%s: current.json의 %s가 없거나 16진 64자리 문자열이 아님" % (kg_root, k))


def load_outputs_raw(kg_root):
    """포인터(current.json)를 한 번만 읽고 그 버전 폴더의 두 파일을 읽어
    (knowledge, kg, knowledge_graph.json 바이트, 버전 폴더, 포인터)를 돌려준다(그래프활용 §6.4.1).
    포인터 필수 키·자료형이 틀리거나, 파일 sha256이 포인터 기록과 다르거나, kg의 knowledge_sha256·kg_version이
    맞지 않으면 ValueError."""
    with open(os.path.join(kg_root, POINTER_FILE), encoding="utf-8") as fh:
        ptr = json.load(fh)
    _check_pointer(kg_root, ptr)
    ver_dir = _pointer_dir(kg_root, ptr.get("kg_version"))
    with open(os.path.join(ver_dir, KNOWLEDGE_FILE), "rb") as fh:
        kbytes = fh.read()
    with open(os.path.join(ver_dir, KG_FILE), "rb") as fh:
        gbytes = fh.read()
    if hashlib.sha256(kbytes).hexdigest() != ptr["knowledge_sha256"] or \
            hashlib.sha256(gbytes).hexdigest() != ptr["knowledge_graph_sha256"]:
        raise ValueError("%s: 결과 파일 sha256이 current.json 기록과 다름 - 다시 빌드 필요" % ver_dir)
    kg = json.loads(gbytes.decode("utf-8"))
    if not isinstance(kg, dict):
        raise ValueError("%s: knowledge_graph.json이 JSON 객체가 아님" % ver_dir)
    if kg.get("knowledge_sha256") != ptr["knowledge_sha256"] or kg.get("kg_version") != ptr["kg_version"]:
        raise ValueError("%s: knowledge_graph.json과 knowledge.json·포인터가 서로 맞지 않음" % ver_dir)
    return json.loads(kbytes.decode("utf-8")), kg, gbytes, ver_dir, ptr


def load_outputs(kg_root):
    """포인터(current.json)를 따라 두 파일을 읽어 (knowledge, kg)를 돌려준다(load_outputs_raw와 같은 검사)."""
    knowledge, kg = load_outputs_raw(kg_root)[:2]
    return knowledge, kg
