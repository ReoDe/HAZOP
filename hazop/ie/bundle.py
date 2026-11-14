"""IE 인계 묶음 원본(JSON). 기획서/초기사건-출력설계.md §3.1~3.3, §8 P2·P3.

build_bundle(results, node_set, pg, ie_doc, now, table) → dict. 파일을 쓰지 않는 순수 함수다(table이 없을 때 기준표 파일만 읽음).
- 입력은 ⑤ 결과 중 확정·잠금 구간의 승인(approved) 항목만이다. 확정 해제로 보관된 칸과 '범위 바뀜' 항목은 넣지 않는다
  (다시 확인하기 전에는 확정 근거가 아님, 검토구간 규격 §2.4·§4.3). 항목 하나에 원인이 하나라 후보(IEC-nnn)도 항목마다 하나다.
- 겹친 두 구간에서 같은 원인(model.twins)이 승인되고 판정·범주·안전 기능·결과가 같으면 후보 하나로 묶는다. 대표는 집합 순서로
  첫 후보이고 merged_from·node_ids·entry_ids·deviation_labels를 단다. 추적표는 항목마다 한 줄씩 그대로 둔다. 판단이 다르면
  묶지 않고 두 후보에 twin_conflict를 달고 추적표에 결과 문장을 남긴다. 고장모드가 없는 원인은 묶지 않는다.
- 후보 ID는 ⑥ 저장 문서(ie_doc, hazop.ie.model)의 대응표에서 읽는다. 그래서 묶음을 다시 만들어도 같은 원인은 같은 ID다.
  ie_doc은 model.sync를 거친 것이어야 한다(IEC가 없는 승인 항목이 있으면 ValueError). 행 순서는 검토구간 × 편차 × 항목.
- 그룹·사건수목 표제·최종상태·기본사건(시트 2~5)도 ie_doc에서 온다. 그룹 상태는 model.effective_status다.
  그룹의 members·member_count는 승인 항목만이다. 승인이 풀린 소속 후보는 ID를 내보내지 않고 수(held_member_count)만
  적는다. ⑤ 출처가 있는데 그중 승인
  항목이 하나도 없는 표제·최종상태·기본사건은 넣지 않는다(그룹 행·추적표에도 그 ID가 나가지 않음).
- HAZOP 위험도(강도·빈도·위험도)와 권고는 넣지 않는다(E8: KOSHA 빈도 등급이 PSA 빈도로 오해될 수 있음).
- 품질 경고(시트 8)는 5종이다(WARNING_KINDS). 항목 하나만 보면 되는 2종은 ⑤와 같은 res.quality_warnings를 쓰고, 다른
  항목·구간·그래프를 함께 봐야 하는 3종은 여기서 계산한다. 종류별 건수는 warning_summary에 둔다.
- 값은 영어 키로 두고 한국어 표기는 Excel(hazop.ie.bundle_xlsx)에서 붙인다. 드라이브 경로·API 키처럼 보이는 글자는 가린다.
- Excel은 이 dict에서 만든다. 원본은 JSON 하나다(§2-6).
- P5(설계 §8.2, 형식 판 0.3): fmea(hazop.ie.fmea 문서)를 주면 승인 FMEA 행을 출처로 가진 기본사건이 들고(fmea_rows), 'FMEA 대조 전'
  경고는 승인 FMEA 행이 없는 전기·제어 구간(규칙 + 사람 표시)만 센다. mld(hazop.ie.mld 저장 문서)를 주면 완전성 대조 행에
  mld_branches·mld_status를 채우고 'mld' 키에 잎 가지 대조를 둔다. 키를 더하기만 하므로 0.2 묶음은 upgrade()로 읽는다.
"""

import json

from hazop.export import study_xlsx as sx
from hazop.ie import fmea as _fm
from hazop.ie import model
from hazop.study import refs
from hazop.study import results as res

KIND = "hazop_ie_bundle"
SCHEMA_VERSION = "0.3"   # 0.3(2026-11-14 P5): fmea·mld 키, 기본사건 fmea_rows, 완전성 대조 mld_branches·mld_status
SCOPE = "approved"
METHOD = "HAZOP"
# 기준표 파일에 짧은 출처 이름이 없어 table_id로 붙인다. 모르는 기준표는 제목을 쓴다
SOURCE_LABELS = {"lwr-generic-ie-categories-inl2015": "INL 2015 IE 범주"}
CATEGORY_TERM = "일반 범주 코드"
BASIS_UNKNOWN_PREFIX = "[비완화 여부 미확인] "
# 품질 경고 종류 {키: (이름, 근거)}, 설계 §3.2 시트 8에 적힌 순서. 근거는 조사 문서 §9.2의 출처
WARNING_KINDS = {
    "safeguard_as_cause": ("보호설비 고장이 원인 칸에 있음", "IChemE Hazards 26"),
    "mitigated_consequence": res.QUALITY_KINDS["mitigated_consequence"],
    "actuation_unknown": res.QUALITY_KINDS["actuation_unknown"],
    "boundary_cut": ("구간 경계 결과 끊김", "IChemE Hazards 26, PSAM14 383"),
    "fmea_pending": ("전기·제어 구간 FMEA 대조 전", "PSAM14 383"),
}
# 스스로 작동해 압력을 푸는 보호 기기(레지스트리 kind). 원인 위치가 이것이면 보호설비 고장을 원인으로 적은 것으로 본다
PROTECTIVE_KINDS = frozenset({"psv", "relief_valve", "rupture_disc"})
# 전기·제어 구간 규칙의 값은 hazop.ie.fmea에 둔다(규칙 + 사람 표시가 한곳에서 정해지게)
CONTROL_CATEGORY = _fm.CONTROL_CATEGORY
ELECTRIC_KINDS = _fm.ELECTRIC_KINDS
GLOSSARY = (
    ("초기사건(IE)", "정상운전을 교란해 제어·안전계통에 도전하는 사건", "NUREG-2122 용어집(ASME/ANS 표준 정의 인용)"),
    (CATEGORY_TERM, "경수로 산업 평균 초기사건 범주", None),
    ("비완화 결과", "보호수단이 모두 작동하지 않는다고 본 결과. 기준 표시(consequence_basis)가 없으면 '비완화 여부 미확인'",
     "PSAM14 paper 382·383"),
    ("사건수목 표제", "사건수목 위쪽의 완화 기능·계통", "NRC 용어집, NUREG-2122 Top Event"),
    ("최종상태", "사건 진행 끝의 발전소 상태", "NUREG-2122"),
    ("기본사건", "더 나누지 않는 PSA 모델 요소", "NUREG-2122"),
    ("초기사건 그룹", "플랜트 응답과 필요한 완화 기능이 같아 PSA에서 한 초기사건으로 다루는 후보의 묶음. 이 묶음의 그룹은 "
                 "PSA 담당이 고쳐 쓸 제안", "이 앱 정의 [추론]"),
    ("지원계통 초기사건(SSIE)", "정상운전을 교란하면서 완화계통도 약화하는 지원계통 고장. 'IE 그룹' 시트의 '지원계통 IE' 열",
     "NUREG-2122, EPRI 1016741"),
    ("PSA", "확률론적 안전성 평가. 미국 문헌의 PRA와 같은 뜻으로 쓴다. 이 묶음은 평가를 PSA로, 정량화 도구를 PRA 도구로 "
            "적는다", "[일반지식]"),
    ("작동 방식", "자동 / 운전원 / 자체작동 / 미확인", "이 앱 정의(PSAM14 383 권고 반영)"),
)


def approved_entries(results, node_set):
    """([(node_id, 편차, 항목)] 확정 근거가 되는 승인 항목을 묶음 순서대로, 넣지 않은 항목 수).
    확정·잠금 구간의 보관되지 않은 칸만 보고, '범위 바뀜' 승인은 넣지 않은 수에 센다. 분석에서 제외한 구간(screen excluded)은
    행렬·Excel처럼 빼고 그 항목을 넣지 않은 수에 센다."""
    from hazop.study import nodes
    cells = {(c["node_id"], c["deviation_id"]): c for c in results["cells"]}
    picked, left_out = [], 0
    for n in node_set["nodes"]:
        if not nodes.is_active(n) or nodes.screen_excluded(n):
            left_out += sum(len(cells.get((n["node_id"], d["deviation_id"]), {}).get("entries", []))
                            for d in results["deviations"])
            continue
        for d in results["deviations"]:
            cell = cells.get((n["node_id"], d["deviation_id"])) or {}
            for e in cell.get("entries", []):
                if e.get("status") == "approved" and not e.get("scope_changed") and not cell.get("hold"):
                    picked.append((n["node_id"], d, e))
                else:
                    left_out += 1
    return picked, left_out


def _merge_twins(candidates, trace, ie_doc, facts, idx):
    """겹친 구간의 같은 원인 후보를 묶은 후보 목록(§4.3). candidates·trace는 같은 순서다. trace는 고치기만 한다."""
    pairs = model.twins(ie_doc, facts)
    order = {c["candidate_id"]: i for i, c in enumerate(candidates)}
    by_id = {c["candidate_id"]: c for c in candidates}
    into = {}
    for c in candidates:
        iec = c["candidate_id"]
        if iec in into:
            continue
        for other, same in pairs.get(iec, []):
            if same and other in order and other not in into and order[other] > order[iec]:
                into[other] = iec
    for c, t in zip(candidates, trace):
        iec = c["candidate_id"]
        conflicts = [o for o, same in pairs.get(iec, []) if not same and o in by_id]
        if conflicts:
            c["twin_conflict"] = conflicts
            o = by_id[conflicts[0]]
            where = ", ".join("(%s, %s)" % (refs.label(r, idx), m) for r, m in sorted(model.cause_key(
                _entry_of(ie_doc, facts, iec)) or ()))
            t["note"] = "같은 원인 %s이 %s·%s에서 결과가 다름: %s '%s', %s '%s'" % (
                where, c["node_id"], o["node_id"], c["node_id"], c["consequence"], o["node_id"], o["consequence"])
        if iec in into:
            t["merged_into"] = into[iec]
    out = []
    for c in candidates:
        iec = c["candidate_id"]
        if iec in into:
            continue
        group = [iec] + [x for x, rep in into.items() if rep == iec]
        if len(group) > 1:
            group.sort(key=order.get)
            c.update(merged_from=group[1:], node_ids=list(dict.fromkeys(by_id[x]["node_id"] for x in group)),
                     entry_ids=[by_id[x]["entry_id"] for x in group],
                     deviation_labels=[by_id[x]["deviation_label"] for x in group])
        out.append(c)
    return out


def _entry_of(ie_doc, facts, iec):
    return facts[ie_doc["candidates"][iec]["key"]]["entry"]


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


def _scope(doc, facts, fmea_live=frozenset()):
    """{표: 묶음에 드는 live 기록 ID 집합}. 드는 기준은 model.in_scope(그룹 확정 여부와 같은 기준). 기본사건은 승인 FMEA 행도 출처로 센다."""
    return {t: {rid for rid, r in doc[t].items() if r["status"] == "live" and model.in_scope(t, r, facts, fmea_live)}
            for t in ("headings", "end_states", "basic_events")}


def _groups(doc, results, facts, source_label, scope):
    out = []
    for gid in model.live_groups(doc):
        g = doc["groups"][gid]
        everyone = model.members_of(doc, gid)
        members = [m for m in everyone if model.is_evidence(facts.get(doc["candidates"][m]["key"]))]
        held = [m for m in everyone if m not in members]
        heads = [doc["headings"][h] for h in g["heading_ids"]]
        ends = [doc["end_states"][e] for e in g["end_state_ids"]]
        human = (g["origin"] == "human" and all(doc["candidates"][m]["placed_by"] == "human" for m in everyone)
                 and all(r["origin"] == "human" for r in heads + ends))
        out.append({"group_id": gid, "name": g["name"], "definition": g["definition"],
                    "categories": list(g["categories"]),
                    "category_source": source_label if g["categories"] else "",
                    "representative": g["representative"] if g["representative"] in members else None,
                    "representative_reason": g["representative_reason"], "members": members, "held_member_count": len(held),
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


def _basic_events(doc, approved, iecs, scope, fmea_live=frozenset()):
    from hazop.ie import fmea as fm
    out = []
    for bid, b in sorted(doc["basic_events"].items()):
        if bid not in scope["basic_events"]:
            continue
        live_src = [s for s in b["sources"] if s["key"] in approved or s["key"] in fmea_live]
        out.append({"be_id": bid, "name": b["name"], "tag": b["tag"], "ref": b["ref"],
                    "equipment_kind": b["equipment_kind"], "system": b["system"],
                    "failure_mode": b["failure_mode"], "failure_text": b["failure_text"],
                    "normal_position": "", "failed_position": "",
                    "heading_ids": [h for h in b["heading_ids"] if h in scope["headings"]],
                    "candidate_ids": list(dict.fromkeys(iecs[s["key"]] for s in live_src if s["kind"] == "cause")),
                    "source_kinds": list(dict.fromkeys(s["kind"] for s in live_src)), "origin": b["origin"],
                    "fmea_rows": [s["key"][len(fm.SOURCE_PREFIX):] for s in live_src if s["kind"] == "fmea"]})
    return out


def _guarded(picked):
    """{완화 역할 보호수단의 구현 대상 안정 참조: [그 보호수단을 적은 승인 항목 ID]}. 예방 역할(제어 루프 등)의 대상은
    넣지 않는다. 제어 밸브 고장처럼 그 고장이 곧 전형적인 초기사건 원인이기 때문이다 [추론]."""
    out = {}
    for _node_id, _dev, e in picked:
        for s in refs.safeguard_items(e):
            if s["role"] != "mitigative":
                continue
            for r in s["refs"]:
                if r.get("ref") and e["entry_id"] not in out.setdefault(r["ref"], []):
                    out[r["ref"]].append(e["entry_id"])
    return out


def _safeguard_as_cause(e, idx, guarded):
    """원인 위치가 보호설비인 경우의 경고 글(없으면 None). 보호설비로 보는 것은 자력식 보호 기기(안전밸브·방출밸브·
    파열판)이거나 묶음 안 다른 승인 항목이 완화 역할 보호수단의 구현 대상으로 적은 대상이다 [추론]."""
    hits = []
    for r in e.get("cause_refs") or []:
        ref = r.get("ref") if isinstance(r, dict) else None
        if not ref:
            continue
        others = [x for x in guarded.get(ref, ()) if x != e["entry_id"]]
        if (idx.get(ref) or {}).get("kind") in PROTECTIVE_KINDS:
            hits.append("%s(자력식 보호 기기)" % refs.label(ref, idx))
        elif others:
            hits.append("%s(항목 %s의 완화 보호수단 구현 대상)" % (refs.label(ref, idx), ", ".join(others)))
    if not hits:
        return None
    return ("원인 위치가 보호설비입니다: %s. 보호설비 고장은 대개 초기사건이 아니라 사건수목 표제(완화 기능)의 실패로 "
            "다룹니다 [추론]. 오동작처럼 그 자체가 정상운전을 교란하는 고장이면 그대로 두고, 아니면 원인을 다시 적으세요"
            % ", ".join(hits))


def _boundary_cut(node_id, e, idx, homes, analysed, covered):
    """결과의 영향 대상이 이 구간 밖인데 받는 쪽에서 이어지지 않는 경우의 경고 글(없으면 None) [추론]. 끊긴 것으로 보는 경우:
    대상이 그래프에 없음, 어느 검토구간에도 들지 않음, 받는 구간에 승인 항목이 없음, 받는 구간의 승인 항목 가운데
    그 대상을 가리키는 것이 없음. 묶음에는 영향 대상 열이 없어 사라진 대상도 여기서 알린다.
    '검토구간 없음'은 그 대상이 구간 밖 구성요소라는 뜻이다(v2에서는 흔한 경우)."""
    cuts = []
    for r in e.get("consequence_refs") or []:
        ref = r.get("ref") if isinstance(r, dict) else None
        if not ref:
            continue
        node = idx.get(ref)
        if node is None:
            cuts.append(refs.label(ref, idx))
            continue
        home = homes.get(node["entity_id"], [])
        if node_id in home or any(h in covered.get(ref, ()) for h in home):
            continue
        if not home:
            where = "구간 밖 구성요소"
        elif any(h in analysed for h in home):
            where = "구간 %s(그 대상을 다룬 승인 항목이 없음)" % ", ".join(home)
        else:
            where = "구간 %s(승인 항목 없음)" % ", ".join(home)
        cuts.append("%s → %s" % (refs.label(ref, idx), where))
    if not cuts:
        return None
    return ("결과가 이 구간 밖으로 넘어가는데 받는 쪽에서 이어지지 않습니다(영향 대상 %s). 구간을 넘는 사건 진행이 여기서 "
            "끊기니, 받는 구간에서 그 대상을 다룬 항목을 승인하거나 이 항목의 결과를 끝까지 적었는지 확인하세요"
            % "; ".join(cuts))


def _fmea_pending(node_set, pg, analysed, fmea_doc=None):
    """승인 항목이 있는 전기·제어 구간 가운데 승인 FMEA 행이 하나도 없는 구간 ID(검토구간 순서). 전기·제어 구간은 규칙(계기·제어
    구성요소나 전기로 움직이는 밸브가 든 구간 [추론]) + 사람 표시(hazop.ie.fmea.ec_nodes, 설계 §8.2 질문 7)."""
    from hazop.ie import fmea as fm
    return fm.pending_nodes(node_set, pg, analysed, fmea_doc)


def _warnings(picked, node_set, pg, idx, fmea_doc=None):
    """(품질 경고 행 목록, 종류별 건수 [{kind, count}]). 행은 항목 순서, 한 항목 안에서는 WARNING_KINDS 순서다.
    'FMEA 대조 전'은 항목마다 띄우지 않고 묶음 끝에 한 줄로 두며, 건수는 구간 수다."""
    guarded = _guarded(picked)
    homes = {}
    for n in node_set["nodes"]:
        for m in n["members"]:
            homes.setdefault(m, []).append(n["node_id"])
    analysed = {node_id for node_id, _dev, _e in picked}
    covered = {}
    for node_id, _dev, e in picked:
        for ref in refs.all_refs(e):
            covered.setdefault(ref, set()).add(node_id)
    rows = []
    for node_id, _dev, e in picked:
        found = dict(res.quality_warnings(e))
        found["safeguard_as_cause"] = _safeguard_as_cause(e, idx, guarded)
        found["boundary_cut"] = _boundary_cut(node_id, e, idx, homes, analysed, covered)
        rows += [{"kind": k, "target": e["entry_id"], "text": found[k], "basis": WARNING_KINDS[k][1]}
                 for k in WARNING_KINDS if found.get(k)]
    pending = _fmea_pending(node_set, pg, analysed, fmea_doc)
    if pending:
        rows.append({"kind": "fmea_pending", "target": ", ".join(pending), "basis": WARNING_KINDS["fmea_pending"][1],
                     "text": "전기·제어 구간 %d개: FMEA 대조 전(승인한 FMEA 행 없음). 계기·제어 구성요소나 전동 밸브가 든 구간은 HAZOP만으로 "
                             "고장모드를 다 잡기 어렵습니다. 이 구간들은 FMEA와 대조하지 않았습니다" % len(pending)})
    counts = [{"kind": k, "count": len(pending) if k == "fmea_pending" else sum(w["kind"] == k for w in rows)}
              for k in WARNING_KINDS]
    return rows, counts


def warning_summary_text(bundle):
    """'보호설비 고장이 원인 칸에 있음 1건 · … · 전기·제어 구간 2개: FMEA 대조 전'. 읽는 법 시트·화면·명령줄이 같이 쓴다."""
    by = {s["kind"]: s["count"] for s in bundle["warning_summary"]}
    parts = ["%s %d건" % (WARNING_KINDS[k][0], by[k]) for k in WARNING_KINDS if k != "fmea_pending"]
    n = by["fmea_pending"]
    return " · ".join(parts + ["전기·제어 구간 %d개: FMEA 대조 전" % n if n else "승인된 구간 가운데 전기·제어 구간 없음"])


def _scrubbed(x):
    if isinstance(x, str):
        return sx.scrub(x)
    if isinstance(x, list):
        return [_scrubbed(v) for v in x]
    if isinstance(x, dict):
        return {k: _scrubbed(v) for k, v in x.items()}
    return x


def build_bundle(results, node_set, pg, ie_doc, now, table=None, fmea=None, mld=None, unreadable=()):
    """IE 인계 묶음 dict. ie_doc은 model.sync를 거친 ⑥ 문서, now는 UTC ISO 시각('...Z'), table은 일반 범주 기준표 문서
    (없으면 res.ie_category_table()). fmea·mld는 P5 문서(없으면 FMEA 대조 전·MLD 열 빈 값). unreadable: 읽지 못해 넣지 못한
    P5 파일 이름(읽는 법에 적음). 승인 FMEA 행을 기본사건에 붙이려면
    ie_doc이 hazop.ie.store.sync_all(또는 fmea.sync_basic_events)을 거쳐야 한다."""
    from hazop.ie import fmea as fm
    from hazop.ie import mld as ml
    if fmea is not None and not fmea.get("rows") and not fmea.get("node_marks"):
        fmea = None          # 빈 FMEA 문서(파일 없음)는 '가져오지 않음'과 같다
    fmea_live = fm.live_sources(fmea) if fmea else frozenset()
    table = table if table is not None else res.ie_category_table()
    source_label = SOURCE_LABELS.get(table.get("table_id"), table.get("title") or "")
    idx = refs.index(pg)
    labels = sx.entity_labels(pg)
    picked, left_out = approved_entries(results, node_set)
    facts = model.entry_facts(results, node_set)
    iecs = model.iec_of(ie_doc)
    approved = {k for k, f in facts.items() if f["approved"]}
    unsynced = sorted(approved - set(iecs))
    if unsynced:
        raise ValueError("⑥ 초기사건 문서를 먼저 ⑤ 결과와 맞추세요(IEC 없는 승인 항목 %d건)" % len(unsynced))
    scope = _scope(ie_doc, facts, fmea_live)
    groups = _groups(ie_doc, results, facts, source_label, scope)
    by_gid = {g["group_id"]: g for g in groups}
    candidates, trace = [], []
    for node_id, dev, e in picked:
        iec = iecs[model.key_of(results["graph_id"], e["entry_id"])]
        c = _candidate(iec, node_id, dev, e, idx)
        gid = ie_doc["candidates"][iec]["group_id"]
        c["group_id"] = gid if gid in by_gid else None
        candidates.append(c)
        trace.append(_trace(c, e, labels, by_gid.get(c["group_id"])))
    candidates = _merge_twins(candidates, trace, ie_doc, facts, idx)
    rep = {x: c["candidate_id"] for c in candidates for x in c.get("merged_from") or []}
    for g in groups:  # 묶인 후보는 그룹 행에서도 대표 후보 ID로(묶음에 없는 ID를 가리키지 않게)
        g["members"] = list(dict.fromkeys(rep.get(m, m) for m in g["members"]))
        g["member_count"] = len(g["members"])
        if g["representative"] in rep:
            g["representative"] = rep[g["representative"]]
    changed = {n["node_id"] for n in node_set["nodes"] if n.get("version_changed")}
    for c in candidates:
        hit = sorted(changed & set(c.get("node_ids") or [c["node_id"]]))
        if hit:  # 잠근 뒤 그래프 내용이 바뀐 구간(§5.3): 결과는 그대로 넣고 경고를 단다
            c["node_version_changed"] = hit
    for t in trace:
        if t["node_id"] in changed:
            t["note"] = ((t.get("note") or "") + " 잠근 뒤 그래프 판이 바뀐 구간(잠금 유지, 다시 확인 전)").strip()
    warnings, warning_summary = _warnings(picked, node_set, pg, idx, fmea)
    completeness = _completeness(candidates, table["categories"], source_label, groups, ie_doc["coverage"])
    mld_view = ml.compare(mld, candidates, groups, ie_doc["coverage"]) if mld else None
    for r in completeness:
        branches = (mld_view or {}).get("by_category", {}).get(r["code"], []) if r["code"] else []
        r["mld_branches"] = [{"id": b["id"], "name": b["name"], "status": b["status"]} for b in branches]
        # 범주 행의 MLD 대응: 가지가 모두 사람 확인(또는 해당 없음)이면 confirmed, 규칙 대조까지 넣어 모두 맞으면 rule, 아니면 gap
        r["mld_status"] = (None if not branches else "confirmed" if all(b["status"] in ml.DONE for b in branches)
                           else "rule" if all(b["status"] in ml.DONE + ("rule",) for b in branches) else "gap")
    unmapped = [b for b in (mld_view or {}).get("branches", []) if not b["categories"]]
    if unmapped:
        completeness.append({"code": None, "name_ko": "범주 없는 MLD 가지", "source_label": "", "group_id": None,
                             "candidate_count": 0,
                             "status": "covered" if all(b["status"] in ml.DONE for b in unmapped) else "unmapped",
                             "note": ", ".join("%s %s(%s)" % (b["id"], b["name"], ml.STATUS_LABELS[b["status"]]) for b in unmapped),
                             "mld_branches": [{"id": b["id"], "name": b["name"], "status": b["status"]} for b in unmapped],
                             "mld_status": None})
    revs = {n["node_id"]: n.get("rev") or 1 for n in node_set["nodes"]}
    used = list(dict.fromkeys(node_id for node_id, _d, _e in picked))
    return _scrubbed({
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "project_id": node_set.get("project_id"),
        "graph_id": results.get("graph_id"),
        "created_at": now,
        "source": {"graph_version": results.get("graph_version"),
                   "nodes": [{"node_id": nid, "node_rev": revs.get(nid)} for nid in used],
                   "approved_entries": len(picked), "left_out_unapproved": left_out},
        "unreadable_inputs": list(unreadable),
        "scope": SCOPE,
        "category_table": {"table_id": table.get("table_id"), "title": table.get("title"),
                           "source_label": source_label, "basis": table.get("basis")},
        "candidates": candidates,
        "groups": groups,
        "top_events": _top_events(ie_doc, groups, approved, idx, scope),
        "end_states": _end_states(ie_doc, groups, approved, facts, scope),
        "basic_events": _basic_events(ie_doc, approved, iecs, scope, fmea_live),
        "retired": [{"id": gid, "status": g["status"], "split_into": list(g["split_into"])}
                    for gid, g in sorted(ie_doc["groups"].items()) if g["status"] in model.RETIRED],
        "trace": trace,
        "completeness": completeness,
        "mld": None if mld_view is None else {"source": mld_view["source"], "branches": mld_view["branches"],
                                              "gone_links": mld_view["gone_links"]},
        "fmea": None if not fmea else {"rows_total": len(fmea.get("rows") or {}), "rows_approved": len(fm.approved(fmea)),
                                      "file": ((fmea.get("imports") or [{}])[-1]).get("file")},   # 설계 §8.2 묶음 형식
        "warnings": warnings,
        "warning_summary": warning_summary,
        "glossary": [{"term": t, "meaning": m, "source": s if s is not None else table.get("basis") or ""}
                     for t, m, s in GLOSSARY],
    })


def upgrade(bundle):
    """옛 형식 묶음(0.2)을 지금 형식(0.3)으로 읽는다: 더해진 키를 빈 값으로 채운다(내용은 바꾸지 않음). 지금 형식이면 그대로."""
    if bundle.get("kind") != KIND:
        raise ValueError("IE 인계 묶음이 아님")
    v = bundle.get("schema_version")
    if v == SCHEMA_VERSION:
        return bundle
    if v != "0.2":
        raise ValueError("모르는 묶음 형식 판: %s" % v)
    out = json.loads(json.dumps(bundle))
    for b in out.get("basic_events") or []:
        b.setdefault("fmea_rows", [])
    for r in out.get("completeness") or []:
        r.setdefault("mld_branches", [])
        r.setdefault("mld_status", None)
    out.setdefault("mld", None)
    out.setdefault("fmea", None)
    out.setdefault("unreadable_inputs", [])
    out["schema_version"] = SCHEMA_VERSION
    out["upgraded_from"] = v
    return out


def dumps(bundle):
    """JSON 원본 글(UTF-8로 쓸 것). 만드는 순서가 정해져 있어 같은 묶음이면 같은 글이다."""
    return json.dumps(bundle, ensure_ascii=False, indent=1) + "\n"
