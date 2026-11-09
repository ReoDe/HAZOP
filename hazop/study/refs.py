"""⑤ 결과 항목의 그래프 대상 참조(원인 위치·영향 대상·보호수단 구현 대상·관련 잠재 후보).
근거: 기획서/지식그래프-스키마.md KD7·§7.1·§7.2, 사전 §1.3·§3.5, U6(가)(보호수단은 예방·완화 역할만, LOPA 후속).

- 참조는 entity_id가 아니라 안정 참조 "<도면 graph_id>#<source_object_id>"로 저장한다. entity_id는 재추출 때 바뀌지만
  안정 참조는 그대로라 판이 바뀌어도 결과 파일을 고칠 필요가 없다(hazop.study.migrate.ref_of와 같은 규칙).
- 항목 필드(모두 선택, 없으면 옛 항목처럼 자유 문장만):
  cause_refs        [{ref, failure_mode?, origin?}]
  consequence_refs  [{ref, origin?}]  다른 구간 대상 허용
  safeguards[]      문자열 또는 {text, role, refs: [{ref, origin?}], ipl: null, origin?}. 문자열은 role unknown으로 읽는다
  expectation_refs  [잠재 후보 ID(exp-<규칙>-<대상 해시>)]. 대상 안정 참조에서 정해지는 ID라 판이 바뀌어도 같다
- origin이 ai_draft인 참조·역할은 항목이 승인되기 전까지 확정이 아니다(is_confirmed). 읽기만 하고 파일 내용을 바꾸지 않는다.
- 대상이 그래프에서 사라진 참조는 지우지 않고 '대상 없음(재확인)'으로 보인다.
"""

from hazop.study import migrate

ROLES = {"preventive": "예방", "mitigative": "완화", "unknown": "미정"}
REF_FIELDS = (("cause_refs", "원인 위치"), ("consequence_refs", "영향 대상"))
ORIGINS = ("ai_draft", "human")
MISSING = "대상 없음(재확인)"
# 근거 경로 끝(설비 적용 관계 → 지식 노드 → 원문 위치). 사전 §3.2
APPLY_KINDS = ("has_setpoint", "has_condition", "governed_by")
CITATION_KIND = "specified_in"


# ---------------------------------------------------------------- 읽기
def safeguard_items(entry):
    """보호수단을 {text, role, refs, ipl, origin} 목록으로 읽는다. 문자열은 role unknown·refs 없음."""
    out = []
    for s in entry.get("safeguards") or []:
        if isinstance(s, str):
            out.append({"text": s, "role": "unknown", "refs": [], "ipl": None, "origin": None})
        elif isinstance(s, dict):
            out.append({"text": s.get("text") or "", "role": s.get("role") if s.get("role") in ROLES else "unknown",
                        "refs": [r for r in s.get("refs") or [] if isinstance(r, dict)], "ipl": s.get("ipl"),
                        "origin": s.get("origin")})
    return out


def safeguard_texts(entry):
    return [s["text"] for s in safeguard_items(entry)]


def all_refs(entry):
    """항목이 가리키는 안정 참조(원인·결과·보호수단 순서, 중복 없음)."""
    out = [r.get("ref") for f, _ in REF_FIELDS for r in entry.get(f) or [] if isinstance(r, dict)]
    out += [r.get("ref") for s in safeguard_items(entry) for r in s["refs"]]
    return list(dict.fromkeys(x for x in out if isinstance(x, str) and x))


def is_confirmed(item, entry):
    """참조·역할 하나가 확정인지: 사람이 고른 것이거나, AI가 만들었어도 항목이 승인된 것."""
    return item.get("origin") != "ai_draft" or entry.get("status") == "approved"


def problems(entry):
    """새 필드 형식 문제 목록(빈 목록 = 통과). 필드가 없으면 검사하지 않는다(옛 항목)."""
    out = []

    def ref_list(xs, name, extra):
        if not isinstance(xs, list):
            out.append("%s는 목록이어야 함" % name)
            return
        for r in xs:
            if not isinstance(r, dict) or not isinstance(r.get("ref"), str) or "#" not in r["ref"]:
                out.append("%s 항목은 {ref: \"graph_id#source_object_id\"} 꼴이어야 함" % name)
            elif set(r) - {"ref", "origin"} - set(extra):
                out.append("%s: 모르는 키 %s" % (name, ", ".join(sorted(set(r) - {"ref", "origin"} - set(extra)))))
            elif r.get("origin") not in (None,) + ORIGINS:
                out.append("%s: origin 값 %r" % (name, r.get("origin")))
    for f, extra in (("cause_refs", ("failure_mode",)), ("consequence_refs", ())):
        if f in entry:
            ref_list(entry[f], f, extra)
    sgs = entry.get("safeguards")
    if sgs is not None:
        if not isinstance(sgs, list):
            out.append("safeguards는 목록이어야 함")
        else:
            for s in sgs:
                if isinstance(s, str):
                    continue
                if not isinstance(s, dict) or not isinstance(s.get("text"), str):
                    out.append("safeguards 항목은 문자열 또는 {text, role, refs, ipl} 객체여야 함")
                    continue
                if s.get("role", "unknown") not in ROLES:
                    out.append("safeguards: role 값 %r(%s)" % (s.get("role"), "/".join(ROLES)))
                if s.get("ipl") is not None:
                    out.append("safeguards: ipl은 null(LOPA는 후속, U6)")
                if s.get("origin") not in (None,) + ORIGINS:
                    out.append("safeguards: origin 값 %r" % s.get("origin"))
                ref_list(s.get("refs", []), "safeguards.refs", ())
    if "expectation_refs" in entry:
        x = entry["expectation_refs"]
        if not isinstance(x, list) or not all(isinstance(i, str) and i for i in x):
            out.append("expectation_refs는 잠재 후보 ID 목록이어야 함")
    return out


# ---------------------------------------------------------------- 대상 찾기
def index(graph):
    """{안정 참조: 노드} — 도면 그래프·프로젝트 그래프 모두(프로젝트 노드는 sheet가 도면 graph_id)."""
    gid = graph.get("graph_id")
    out = {}
    for n in graph.get("nodes") or []:
        r = migrate.ref_of(n, gid)
        if r:
            out.setdefault(r, n)
    return out


def ref_of_entity(graph_by_id, entity_id, graph_id):
    n = graph_by_id.get(entity_id)
    return migrate.ref_of(n, graph_id) if n else None


def drawing_of(ref):
    """안정 참조의 도면 graph_id. 형식이 아니면 None."""
    gid, sep, _ = (ref or "").partition("#")
    return gid if sep else None


def node_text(n):
    first = (n.get("label_text") or "").split("\n")[0].strip()
    return n.get("tag") or first or n.get("kind") or n.get("entity_id")


def label(ref, idx, drawing_numbers=None, short=None):
    """사람이 읽는 대상 이름. drawing_numbers {graph_id: 도면 번호}가 있으면 "RC-PSV101 (SNP-M-102)", short {도면 번호:
    짧은 번호}도 있으면 "RC-PSV101(102)". 대상이 없으면 "대상 없음(재확인): <ref>"."""
    n = idx.get(ref)
    if n is None:
        return "%s: %s" % (MISSING, ref)
    text = node_text(n)
    dn = (drawing_numbers or {}).get(n.get("sheet") or drawing_of(ref))
    if not dn:
        return text
    return "%s(%s)" % (text, short.get(dn, dn)) if short is not None else "%s (%s)" % (text, dn)


def missing(entry, idx):
    """그래프에서 찾지 못한 참조(지우지 않고 재확인 표시할 것)."""
    return [r for r in all_refs(entry) if r not in idx]


def lines(entry, idx, drawing_numbers=None, short=None, expectations=None):
    """[(분류, 글)] 사람이 읽는 참조 줄. 분류: cause·consequence·safeguard·expectation.
    예: ("safeguard", "보호수단: RC-PSV101 (SNP-M-102) · 완화"). AI가 만든 참조는 승인 전이면 "· AI 초안"을 붙인다.
    expectations {잠재 후보 ID: 항목}이 있으면 잠재 후보를 규칙·대상·상태로, 없으면 ID로 적는다."""
    out = []

    def mark(r):
        return "" if is_confirmed(r, entry) else " · AI 초안"
    for (f, title), kind in zip(REF_FIELDS, ("cause", "consequence")):
        for r in entry.get(f) or []:
            if isinstance(r, dict) and r.get("ref"):
                fm = " · %s" % r["failure_mode"] if r.get("failure_mode") else ""
                out.append((kind, "%s: %s%s%s" % (title, label(r["ref"], idx, drawing_numbers, short), fm, mark(r))))
    for s in safeguard_items(entry):
        if not s["refs"] and s["role"] == "unknown":
            continue
        targets = ", ".join(label(r["ref"], idx, drawing_numbers, short) for r in s["refs"] if r.get("ref")) \
            or "구현 대상 미지정"
        draft = not is_confirmed(s, entry) or any(not is_confirmed(r, entry) for r in s["refs"])
        out.append(("safeguard", "보호수단: %s · %s%s" % (targets, ROLES[s["role"]], " · AI 초안" if draft else "")))
    for xid in entry.get("expectation_refs") or []:
        it = (expectations or {}).get(xid)
        if it is None:
            out.append(("expectation", "잠재 후보: %s %s" % (xid, MISSING if expectations is not None else "")))
        else:
            out.append(("expectation", "잠재 후보: %s %s %s · %s%s" % (
                it["rule_id"], it.get("target_tag") or it["target"], it["label"], it["state_label"],
                " · 재확인 필요" if it.get("recheck") else "")))
    return [(k, t.rstrip()) for k, t in out]


# ---------------------------------------------------------------- 근거 경로
def evidence_trails(ref, graph, kg):
    """안정 참조 -> P&ID 노드 -> 설비 적용 관계(has_setpoint·has_condition·governed_by) -> 지식 노드 -> specified_in ->
    문서 조각 경로 목록. 경로 단계 {"id", "kind"(관계 이름 또는 노드 종류), "v4"}. 기각 관계는 넣지 않는다.
    graph는 kg가 참조한 도면 그래프(kg 관계의 P&ID 끝이 그 도면 entity_id를 가리킴)."""
    idx = index(graph)
    n = idx.get(ref)
    if n is None or kg is None:
        return []
    eid, gid = n["entity_id"], graph.get("graph_id")
    knodes = {k.get("id"): k for k in kg.get("nodes") or []}
    links = [l for l in kg.get("links") or [] if l.get("link_status") != "rejected"]
    cites = {}
    for l in links:
        if l.get("kind") == CITATION_KIND:
            a, b = ((l.get("ends") or {}).get(s) or {} for s in ("from", "to"))
            cites.setdefault(a.get("ref"), []).append((l, b.get("ref")))
    out = []
    for l in links:
        a, b = ((l.get("ends") or {}).get(s) or {} for s in ("from", "to"))
        if l.get("kind") not in APPLY_KINDS or a.get("layer") != "pid" or a.get("graph_id") != gid \
                or a.get("entity_id") != eid:
            continue
        kid = b.get("ref")
        head = [{"id": ref, "kind": "pid_node", "v4": True, "tag": n.get("tag")},
                {"id": l["id"], "kind": l["kind"], "v4": bool((l.get("compute_view") or {}).get("v4"))},
                {"id": kid, "kind": (knodes.get(kid) or {}).get("node_type"),
                 "v4": bool(((knodes.get(kid) or {}).get("compute_view") or {}).get("v4"))}]
        tails = cites.get(kid) or [(None, None)]
        for c, chunk in tails:
            if c is None:
                out.append(head)
                continue
            out.append(head + [{"id": c["id"], "kind": CITATION_KIND, "v4": bool((c.get("compute_view") or {}).get("v4"))},
                               {"id": chunk, "kind": (knodes.get(chunk) or {}).get("node_type"),
                                "v4": bool(((knodes.get(chunk) or {}).get("compute_view") or {}).get("v4"))}])
    return sorted(out, key=lambda p: [s["id"] or "" for s in p])
