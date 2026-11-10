"""IE 인계 묶음 원본(JSON). 기획서/초기사건-출력설계.md §3.1~3.3, §8 P2·P3.

build_bundle(results, node_set, pg, ie_doc, now, table) → dict. 파일을 쓰지 않는 순수 함수다(table이 없을 때 기준표 파일만 읽음).
- 입력은 ⑤ 결과 중 승인(approved) 항목만이다. 항목 하나에 원인이 하나라 후보(IEC-nnn)도 항목마다 하나다.
- 후보 ID는 ⑥ 저장 문서(ie_doc, hazop.ie.model)의 대응표에서 읽는다. 그래서 묶음을 다시 만들어도 같은 원인은 같은 ID다.
  ie_doc은 model.sync를 거친 것이어야 한다(IEC가 없는 승인 항목이 있으면 ValueError). 행 순서는 검토구간 × 편차 × 항목.
- 그룹·사건수목 표제·최종상태·기본사건(시트 2~5)도 ie_doc에서 온다. 그룹 상태는 model.effective_status다.
  그룹의 members·member_count는 승인 항목만이고 승인이 풀린 소속 후보는 held_members에 둔다. ⑤ 출처가 있는데 그중 승인
  항목이 하나도 없는 표제·최종상태·기본사건은 넣지 않는다(그룹 행·추적표에도 그 ID가 나가지 않음).
- HAZOP 위험도(강도·빈도·위험도)와 권고는 넣지 않는다(E8: KOSHA 빈도 등급이 PSA 빈도로 오해될 수 있음).
- 값은 영어 키로 두고 한국어 표기는 Excel(hazop.ie.bundle_xlsx)에서 붙인다. 드라이브 경로·API 키처럼 보이는 글자는 가린다.
- Excel은 이 dict에서 만든다. 원본은 JSON 하나다(§2-6).
"""

import json

from hazop.export import study_xlsx as sx
from hazop.ie import model
from hazop.study import refs
from hazop.study import results as res

KIND = "hazop_ie_bundle"
SCHEMA_VERSION = "0.2"
SCOPE = "approved"
METHOD = "HAZOP"
# 기준표 파일에 짧은 출처 이름이 없어 table_id로 붙인다. 모르는 기준표는 제목을 쓴다
SOURCE_LABELS = {"lwr-generic-ie-categories-inl2015": "INL 2015 IE 범주"}
CATEGORY_TERM = "일반 범주 코드"
BASIS_UNKNOWN_PREFIX = "[비완화 여부 미확인] "
GLOSSARY = (
    ("초기사건(IE)", "정상운전을 교란해 제어·안전계통에 도전하는 사건", "NUREG-2122 용어집(ASME/ANS 표준 정의 인용)"),
    (CATEGORY_TERM, "경수로 산업 평균 초기사건 범주", None),
    ("비완화 결과", "보호수단이 모두 작동하지 않는다고 본 결과. 기준 표시(consequence_basis)가 없으면 '비완화 여부 미확인'",
     "PSAM14 paper 382·383"),
    ("사건수목 표제", "사건수목 위쪽의 완화 기능·계통", "NRC 용어집, NUREG-2122 Top Event"),
    ("최종상태", "사건 진행 끝의 발전소 상태", "NUREG-2122"),
    ("기본사건", "더 나누지 않는 PSA 모델 요소", "NUREG-2122"),
    ("작동 방식", "자동 / 운전원 / 자체작동 / 미확인", "이 앱 정의(PSAM14 383 권고 반영)"),
)


def approved_entries(results, node_set):
    """([(node_id, 편차, 항목)] 승인 항목을 묶음 순서대로, 승인 안 된 항목 수)."""
    cells = {(c["node_id"], c["deviation_id"]): c for c in results["cells"]}
    picked, left_out = [], 0
    for n in node_set["nodes"]:
        for d in results["deviations"]:
            for e in (cells.get((n["node_id"], d["deviation_id"])) or {}).get("entries", []):
                if e.get("status") == "approved":
                    picked.append((n["node_id"], d, e))
                else:
                    left_out += 1
    return picked, left_out


def _candidate(iec, node_id, dev, e, idx):
    hint = e.get("ie_hint") if isinstance(e.get("ie_hint"), dict) else None
    h = hint or {}
    causes = [r for r in e.get("cause_refs") or [] if isinstance(r, dict) and r.get("ref")]
    return {
        "candidate_id": iec,
        "entry_id": e["entry_id"],
        "node_id": node_id,
        "deviation_id": dev["deviation_id"],
        "deviation_label": dev["label"],
        "judgement": h.get("candidate") if h.get("candidate") in res.IE_CANDIDATES else "undecided",
        "disturbs": h.get("disturbs") if h.get("disturbs") in res.IE_ANSWERS else "unknown",
        "challenges": h.get("challenges") if h.get("challenges") in res.IE_ANSWERS else "unknown",
        "safety_functions": list(h.get("safety_functions") or []),
        "cause": e.get("cause") or "",
        "cause_kind": e.get("cause_kind") if e.get("cause_kind") in res.CAUSE_KINDS else None,
        "cause_location": [refs.label(r["ref"], idx) for r in causes],
        "failure_modes": [r["failure_mode"] for r in causes if r.get("failure_mode")],
        "consequence": e.get("consequence") or "",
        "consequence_basis": e.get("consequence_basis") if e.get("consequence_basis") in res.CONSEQUENCE_BASES else None,
        "category": h.get("category"),
        "group_id": None,
        "reason": h.get("reason") or "",
        "method": METHOD,
        "stable_refs": [r["ref"] for r in causes],
        "ie_origin": h.get("origin") if hint else None,
        "entry_status": "approved",
    }


def _trace(c, e, labels, group):
    basis = e.get("ai_basis") or {}
    return {
        "node_id": c["node_id"],
        "deviation_label": c["deviation_label"],
        "entry_id": c["entry_id"],
        "cause": c["cause"],
        "candidate_id": c["candidate_id"],
        "judgement": c["judgement"],
        "group_id": c["group_id"],
        "top_event_ids": list(group["heading_ids"]) if group else [],
        "end_state_ids": list(group["end_state_ids"]) if group else [],
        "kg_paths": [" → ".join(labels.get(i, i) for i in p) for p in basis.get("kg_paths") or [] if p],
        "sources": [{"doc": s.get("doc") or "", "where": s.get("where") or ""} for s in basis.get("sources") or []],
    }


def _completeness(candidates, categories, source_label, groups, coverage):
    """기준표 범주마다 한 행(파일 순서). 후보 수는 판정이 후보·보류인 것만 센다. '대응 있음'은 판정이 후보인 것이
    하나라도 있을 때이고, 그 판정이 모두 AI 초안이면 사유·처리에 적는다(AI가 범주를 잘못 고르면 공백이 가려지므로).
    대응 그룹은 범주에 그 코드를 넣은 ⑥ 그룹이다. 공백 행에 사람이 적은 처리(coverage)가 있으면 사유·처리 앞에 붙이고,
    '해당 없음(설계 특성)'이면 상태도 '해당 없음'이 된다. 범주가 없거나 기준표에 없는 코드인 후보·보류는 끝의 '미분류' 행에 모은다."""
    live = [c for c in candidates if c["judgement"] in ("yes", "undecided")]
    codes = {cat["code"] for cat in categories}
    rows = []
    for cat in categories:
        mine = [c for c in live if c["category"] == cat["code"]]
        yes = [c for c in mine if c["judgement"] == "yes"]
        held = [c for c in mine if c["judgement"] == "undecided"]
        notes = []
        status = "covered" if yes else "gap"
        done = coverage.get(cat["code"]) if not yes else None
        if done:
            notes.append("%s: %s" % (model.COVERAGE[done["disposition"]], done["reason"]))
            if done["disposition"] == "not_applicable":
                status = "not_applicable"
        if yes:
            draft = all(c["ie_origin"] != "human" for c in yes)
            notes.append(("AI 초안 판정만 있음: " if draft else "") + ", ".join(c["candidate_id"] for c in yes))
        if held:
            notes.append("%s 보류(판정 대기)" % ", ".join(c["candidate_id"] for c in held))
        mapped = [g["group_id"] for g in groups if cat["code"] in g["categories"]]
        rows.append({"code": cat["code"], "name_ko": cat["name_ko"], "source_label": source_label,
                     "group_id": ", ".join(mapped) or None, "candidate_count": len(mine), "status": status,
                     "note": " · ".join(notes)})
    loose = [c for c in live if c["category"] not in codes]
    if loose:
        rows.append({"code": None, "name_ko": "기준표 범주에 넣지 않은 후보", "source_label": "", "group_id": None,
                     "candidate_count": len(loose), "status": "unclassified",
                     "note": ", ".join(c["candidate_id"] + ("(기준표에 없는 코드 %s)" % c["category"] if c["category"]
                                                            else "") for c in loose)})
    return rows


def _in_scope(keys, approved):
    """⑤ 출처가 있는 기록은 출처 중 승인 항목이 하나라도 있어야 묶음에 든다. 출처 없이 사람이 쓴 기록은 든다."""
    return not keys or any(k in approved for k in keys)


def _scope(doc, approved):
    """{표: 묶음에 드는 live 기록 ID 집합}."""
    keys = {"headings": lambda r: [s["key"] for s in r["sources"]], "end_states": lambda r: r["source_keys"],
            "basic_events": lambda r: [s["key"] for s in r["sources"]]}
    return {t: {rid for rid, r in doc[t].items() if r["status"] == "live" and _in_scope(f(r), approved)}
            for t, f in keys.items()}


def _groups(doc, results, facts, source_label, scope):
    out = []
    for gid in model.live_groups(doc):
        g = doc["groups"][gid]
        everyone = model.members_of(doc, gid)
        members = [m for m in everyone if (facts.get(doc["candidates"][m]["key"]) or {}).get("approved")]
        held = [m for m in everyone if m not in members]
        heads = [doc["headings"][h] for h in g["heading_ids"]]
        ends = [doc["end_states"][e] for e in g["end_state_ids"]]
        human = (g["origin"] == "human" and all(doc["candidates"][m]["placed_by"] == "human" for m in everyone)
                 and all(r["origin"] == "human" for r in heads + ends))
        out.append({"group_id": gid, "name": g["name"], "definition": g["definition"],
                    "categories": list(g["categories"]),
                    "category_source": source_label if g["categories"] else "",
                    "representative": g["representative"] if g["representative"] in members else None,
                    "representative_reason": g["representative_reason"], "members": members, "held_members": held,
                    "member_count": len(members), "plant_response": g["plant_response"],
                    "affected_mitigation": g["affected_mitigation"], "support_ie": g["support_ie"],
                    "heading_ids": [h for h in g["heading_ids"] if h in scope["headings"]],
                    "end_state_ids": [e for e in g["end_state_ids"] if e in scope["end_states"]],
                    "origin": "human" if human else "ai_draft",
                    "status": model.effective_status(doc, gid, results, facts),
                    "confirmed_by": (g.get("confirmation") or {}).get("by"),
                    "problems": model.confirm_problems(doc, gid, results, facts)})
    return out


def _referrers(groups, field):
    out = {}
    for g in groups:
        for rid in g[field]:
            out.setdefault(rid, []).append(g["group_id"])
    return out


def _top_events(doc, groups, approved, idx, scope):
    used = _referrers(groups, "heading_ids")
    return [{"heading_id": hid, "name": h["name"], "sources": [s["text"] for s in h["sources"] if s["key"] in approved],
             "targets": [refs.label(r, idx) for r in h["targets"]], "systems": h["systems"], "role": h["role"],
             "actuation": h["actuation"], "operator_cue": h["operator_cue"], "group_ids": used.get(hid, []),
             "entry_ids": list(dict.fromkeys(model.entry_of_key(s["key"]) for s in h["sources"]
                                             if s["key"] in approved)),
             "origin": h["origin"]}
            for hid, h in sorted(doc["headings"].items()) if hid in scope["headings"]]


def _end_states(doc, groups, approved, facts, scope):
    """승인 출처 가운데 비완화 기준 표시가 없는 것이 하나라도 있으면 대표 문장 앞에 '비완화 여부 미확인'을 붙인다
    (규칙 초안은 ⑤ 결과 문장을 그대로 옮기므로 완화된 결과가 최종상태로 들어갈 수 있다)."""
    used = _referrers(groups, "end_state_ids")
    out = []
    for eid, e in sorted(doc["end_states"].items()):
        if eid not in scope["end_states"]:
            continue
        src = [k for k in e["source_keys"] if k in approved]
        unknown = any(facts[k]["entry"].get("consequence_basis") != "unmitigated" for k in src)
        out.append({"end_state_id": eid, "text": (BASIS_UNKNOWN_PREFIX if unknown else "") + e["text"],
                    "category": e["category"], "group_ids": used.get(eid, []), "source_count": len(src),
                    "origin": e["origin"]})
    return out


def _basic_events(doc, approved, iecs, scope):
    out = []
    for bid, b in sorted(doc["basic_events"].items()):
        if bid not in scope["basic_events"]:
            continue
        live_src = [s for s in b["sources"] if s["key"] in approved]
        out.append({"be_id": bid, "name": b["name"], "tag": b["tag"], "ref": b["ref"],
                    "equipment_kind": b["equipment_kind"], "system": b["system"],
                    "failure_mode": b["failure_mode"], "failure_text": b["failure_text"],
                    "normal_position": "", "failed_position": "",
                    "heading_ids": [h for h in b["heading_ids"] if h in scope["headings"]],
                    "candidate_ids": list(dict.fromkeys(iecs[s["key"]] for s in live_src if s["kind"] == "cause")),
                    "source_kinds": list(dict.fromkeys(s["kind"] for s in live_src)), "origin": b["origin"]})
    return out


def _scrubbed(x):
    if isinstance(x, str):
        return sx.scrub(x)
    if isinstance(x, list):
        return [_scrubbed(v) for v in x]
    if isinstance(x, dict):
        return {k: _scrubbed(v) for k, v in x.items()}
    return x


def build_bundle(results, node_set, pg, ie_doc, now, table=None):
    """IE 인계 묶음 dict. ie_doc은 model.sync를 거친 ⑥ 문서, now는 UTC ISO 시각('...Z'), table은 일반 범주 기준표 문서
    (없으면 res.ie_category_table())."""
    table = table if table is not None else res.ie_category_table()
    source_label = SOURCE_LABELS.get(table.get("table_id"), table.get("title") or "")
    idx = refs.index(pg)
    labels = sx.entity_labels(pg)
    picked, left_out = approved_entries(results, node_set)
    facts = model.entry_facts(results)
    iecs = model.iec_of(ie_doc)
    approved = {k for k, f in facts.items() if f["approved"]}
    unsynced = sorted(approved - set(iecs))
    if unsynced:
        raise ValueError("⑥ 초기사건 문서를 먼저 ⑤ 결과와 맞추세요(IEC 없는 승인 항목 %d건)" % len(unsynced))
    scope = _scope(ie_doc, approved)
    groups = _groups(ie_doc, results, facts, source_label, scope)
    by_gid = {g["group_id"]: g for g in groups}
    candidates, trace, warnings = [], [], []
    for node_id, dev, e in picked:
        iec = iecs[model.key_of(results["graph_id"], e["entry_id"])]
        c = _candidate(iec, node_id, dev, e, idx)
        gid = ie_doc["candidates"][iec]["group_id"]
        c["group_id"] = gid if gid in by_gid else None
        candidates.append(c)
        trace.append(_trace(c, e, labels, by_gid.get(c["group_id"])))
        warnings += [{"kind": k, "target": e["entry_id"], "text": t, "basis": res.QUALITY_KINDS[k][1]}
                     for k, t in res.quality_warnings(e)]
    return _scrubbed({
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "project_id": node_set.get("project_id"),
        "graph_id": results.get("graph_id"),
        "created_at": now,
        "source": {"study_nodes_ref": {k: (results.get("study_nodes_ref") or {}).get(k)
                                    for k in ("graph_version", "confirmed_at")}, "approved_entries": len(picked),
                   "left_out_unapproved": left_out},
        "scope": SCOPE,
        "category_table": {"table_id": table.get("table_id"), "title": table.get("title"),
                           "source_label": source_label, "basis": table.get("basis")},
        "candidates": candidates,
        "groups": groups,
        "top_events": _top_events(ie_doc, groups, approved, idx, scope),
        "end_states": _end_states(ie_doc, groups, approved, facts, scope),
        "basic_events": _basic_events(ie_doc, approved, iecs, scope),
        "retired": [{"id": gid, "status": g["status"], "split_into": list(g["split_into"])}
                    for gid, g in sorted(ie_doc["groups"].items()) if g["status"] in model.RETIRED],
        "trace": trace,
        "completeness": _completeness(candidates, table["categories"], source_label, groups, ie_doc["coverage"]),
        "warnings": warnings,
        "glossary": [{"term": t, "meaning": m, "source": s if s is not None else table.get("basis") or ""}
                     for t, m, s in GLOSSARY],
    })


def dumps(bundle):
    """JSON 원본 글(UTF-8로 쓸 것). 만드는 순서가 정해져 있어 같은 묶음이면 같은 글이다."""
    return json.dumps(bundle, ensure_ascii=False, indent=1) + "\n"
