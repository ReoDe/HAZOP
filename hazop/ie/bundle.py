"""IE 인계 묶음 원본(JSON). 기획서/초기사건-출력설계.md §3.1~3.3, §8 P2.

build_bundle(results, node_set, pg, now, table) → dict. 파일을 쓰지 않는 순수 함수다(table이 없을 때 기준표 파일만 읽음).
- 입력은 ⑤ 결과 중 승인(approved) 항목만이다. 항목 하나에 원인이 하나라 후보(IEC-nnn)도 항목마다 하나다.
- 후보 순서와 번호는 검토구간 순서 × 편차 순서 × 칸 안 항목 순서다. 같은 입력이면 같은 번호가 나오지만, 승인 항목이
  늘거나 줄면 번호가 밀린다. 묶음을 다시 만들어도 같은 원인이 같은 ID를 갖게 하는 대응표는 ⑥ 저장 파일(P3)에서 더한다.
- HAZOP 위험도(강도·빈도·위험도)와 권고는 넣지 않는다(E8: KOSHA 빈도 등급이 PSA 빈도로 오해될 수 있음).
- 그룹·사건수목 표제·최종상태·기본사건은 P3라 ID 칸을 비워 둔다(group_id null, top_event_ids [] 등).
- 값은 영어 키로 두고 한국어 표기는 Excel(hazop.ie.bundle_xlsx)에서 붙인다. 드라이브 경로·API 키처럼 보이는 글자는 가린다.
- Excel은 이 dict에서 만든다. 원본은 JSON 하나다(§2-6).
"""

import json

from hazop.export import study_xlsx as sx
from hazop.study import refs
from hazop.study import results as res

KIND = "hazop_ie_bundle"
SCHEMA_VERSION = "0.1"
SCOPE = "approved"
METHOD = "HAZOP"
# 기준표 파일에 짧은 출처 이름이 없어 table_id로 붙인다. 모르는 기준표는 제목을 쓴다
SOURCE_LABELS = {"lwr-generic-ie-categories-inl2015": "INL 2015 IE 범주"}
CATEGORY_TERM = "일반 범주 코드"
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


def _candidate(i, node_id, dev, e, idx):
    hint = e.get("ie_hint") if isinstance(e.get("ie_hint"), dict) else None
    h = hint or {}
    causes = [r for r in e.get("cause_refs") or [] if isinstance(r, dict) and r.get("ref")]
    return {
        "candidate_id": "IEC-%03d" % i,
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


def _trace(c, e, labels):
    basis = e.get("ai_basis") or {}
    return {
        "node_id": c["node_id"],
        "deviation_label": c["deviation_label"],
        "entry_id": c["entry_id"],
        "cause": c["cause"],
        "candidate_id": c["candidate_id"],
        "judgement": c["judgement"],
        "group_id": None,
        "top_event_ids": [],
        "end_state_ids": [],
        "kg_paths": [" → ".join(labels.get(i, i) for i in p) for p in basis.get("kg_paths") or [] if p],
        "sources": [{"doc": s.get("doc") or "", "where": s.get("where") or ""} for s in basis.get("sources") or []],
    }


def _completeness(candidates, categories, source_label):
    """기준표 범주마다 한 행(파일 순서). 후보 수는 판정이 후보·보류인 것만 센다. '대응 있음'은 판정이 후보인 것이
    하나라도 있을 때이고, 그 판정이 모두 AI 초안이면 사유·처리에 적는다(AI가 범주를 잘못 고르면 공백이 가려지므로).
    그룹 열이 생기기 전까지는 사유·처리에 후보 ID를 적어 거슬러 갈 수 있게 한다. 범주가 없거나 기준표에 없는 코드인
    후보·보류는 끝의 '미분류' 행에 모은다."""
    live = [c for c in candidates if c["judgement"] in ("yes", "undecided")]
    codes = {cat["code"] for cat in categories}
    rows = []
    for cat in categories:
        mine = [c for c in live if c["category"] == cat["code"]]
        yes = [c for c in mine if c["judgement"] == "yes"]
        held = [c for c in mine if c["judgement"] == "undecided"]
        notes = []
        if yes:
            draft = all(c["ie_origin"] != "human" for c in yes)
            notes.append(("AI 초안 판정만 있음: " if draft else "") + ", ".join(c["candidate_id"] for c in yes))
        if held:
            notes.append("%s 보류(판정 대기)" % ", ".join(c["candidate_id"] for c in held))
        rows.append({"code": cat["code"], "name_ko": cat["name_ko"], "source_label": source_label, "group_id": None,
                     "candidate_count": len(mine), "status": "covered" if yes else "gap", "note": " · ".join(notes)})
    loose = [c for c in live if c["category"] not in codes]
    if loose:
        rows.append({"code": None, "name_ko": "기준표 범주에 넣지 않은 후보", "source_label": "", "group_id": None,
                     "candidate_count": len(loose), "status": "unclassified",
                     "note": ", ".join(c["candidate_id"] + ("(기준표에 없는 코드 %s)" % c["category"] if c["category"]
                                                            else "") for c in loose)})
    return rows


def _scrubbed(x):
    if isinstance(x, str):
        return sx.scrub(x)
    if isinstance(x, list):
        return [_scrubbed(v) for v in x]
    if isinstance(x, dict):
        return {k: _scrubbed(v) for k, v in x.items()}
    return x


def build_bundle(results, node_set, pg, now, table=None):
    """IE 인계 묶음 dict. now는 UTC ISO 시각('...Z'), table은 일반 범주 기준표 문서(없으면 res.ie_category_table())."""
    table = table if table is not None else res.ie_category_table()
    source_label = SOURCE_LABELS.get(table.get("table_id"), table.get("title") or "")
    idx = refs.index(pg)
    labels = sx.entity_labels(pg)
    picked, left_out = approved_entries(results, node_set)
    candidates, trace, warnings = [], [], []
    for i, (node_id, dev, e) in enumerate(picked, 1):
        c = _candidate(i, node_id, dev, e, idx)
        candidates.append(c)
        trace.append(_trace(c, e, labels))
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
        "trace": trace,
        "completeness": _completeness(candidates, table["categories"], source_label),
        "warnings": warnings,
        "glossary": [{"term": t, "meaning": m, "source": s if s is not None else table.get("basis") or ""}
                     for t, m, s in GLOSSARY],
    })


def dumps(bundle):
    """JSON 원본 글(UTF-8로 쓸 것). 만드는 순서가 정해져 있어 같은 묶음이면 같은 글이다."""
    return json.dumps(bundle, ensure_ascii=False, indent=1) + "\n"
