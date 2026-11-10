"""⑥ 초기사건 저장 문서(data/initiating-events/<project>.json)와 상태 전이. Qt 의존 없음. 기획서/초기사건-출력설계.md §3.3, §6.2, §8 P3.

문서는 JSON dict 하나이고 전이는 모두 순수 함수다(문서를 받아 사본을 고쳐 돌려주고 history에 한 줄 남김).
- 후보(IEC)는 ⑤ 승인 항목 하나다. 키는 "<결과 graph_id>/<entry_id>"다(entry_id는 결과 파일 하나 안에서만 고유).
  candidates 표가 키 → IEC 대응표이고 counters는 늘기만 하므로, 승인이 풀리거나 그룹이 지워져도 ID를 다시 쓰지 않는다.
- 소속은 후보 쪽(candidates[IEC].group_id)에 둔다. 한 후보가 두 그룹에 드는 상태를 만들 수 없다.
- 저장된 status의 'confirmed'는 주장일 뿐이다. 화면·묶음·지식그래프는 effective_status로 읽는다: 그룹 origin이 human이고 확정
  문제(confirm_problems)가 없고, 확정 때 찍은 digest가 지금 내용과 같을 때만 '확정'이다. ⑤에서 항목이 바뀌거나 승인이 풀리면 저절로 '초안'이 된다.
- ⑥ 안의 편집은 모두 _change를 지나고, 건드린 확정 그룹을 그 자리에서 초안으로 내린다(되돌려도 확정이 살아나지 않음).
- 확정(confirm)은 사람 이름이 있어야 하고 confirm_problems가 비어야 한다. suggest(규칙 초안)는 확정하지 않고 확정 그룹을 건드리지 않는다.
- 나누기·삭제한 그룹, 지운 표제·최종상태·기본사건은 기록으로 남는다(ID가 사라지지 않음).
"""

import copy
import hashlib
import re

from hazop import store_io
from hazop.kg.build import dump_bytes
from hazop.study import refs
from hazop.study import results as res
from hazop.study.nodes import now_utc

KIND = "hazop_ie_groups"
SCHEMA_VERSION = "0.1"
SEP = "/"
ORIGINS = ("ai_draft", "human")
GROUP_STATUSES = {"draft": "초안", "confirmed": "확정", "split": "나뉨", "deleted": "삭제"}
RETIRED = ("split", "deleted")
RECORD_STATUSES = ("live", "deleted")
ID_FORMATS = {"IEC": "IEC-%03d", "IEG": "IEG-%02d", "H": "H-%02d", "ES": "ES-%02d", "BE": "BE-%03d"}
# ref 종류 → (문서 안 표, ID 접두어). 만들기·고치기·지우기·받아들이기가 이 표 하나로 움직인다
COLLECTIONS = {"group": ("groups", "IEG"), "heading": ("headings", "H"), "end_state": ("end_states", "ES"),
               "basic_event": ("basic_events", "BE")}
EDITABLE = {"group": ("name", "definition", "categories", "representative", "representative_reason", "plant_response",
                      "affected_mitigation", "support_ie"),
            "heading": ("name", "targets", "systems", "role", "actuation", "operator_cue"),
            "end_state": ("text", "category"),
            "basic_event": ("name", "equipment_kind", "system", "failure_mode", "failure_text")}
SUPPORT_IE = {"yes": "예", "no": "아니오", "unknown": "미정"}
ES_CATEGORIES = {"core_damage_possible": "노심손상 가능", "containment_bypass_possible": "격납 우회 가능",
                 "unclassified": "미분류"}
COVERAGE = {"out_of_scope": "범위 밖", "other_method": "다른 기법으로 확인 예정", "not_applicable": "해당 없음(설계 특성)"}
# 후보 내용이 바뀌었는지 보는 ⑤ 필드. 확정 때 이 값들의 지문을 digest에 넣는다
MEMBER_FIELDS = ("cause", "consequence", "consequence_basis", "cause_kind", "cause_refs", "safeguards", "ie_hint")
SOURCE_KINDS = {"cause": "HAZOP 원인", "safeguard": "보호수단 구현 대상"}


def _sha(obj):
    return "sha256:" + hashlib.sha256(dump_bytes(obj)).hexdigest()


def key_of(graph_id, entry_id):
    return "%s%s%s" % (graph_id, SEP, entry_id)


def entry_of_key(key):
    return key.partition(SEP)[2]


def empty(project_id, counters=None):
    """빈 문서. counters를 주면 그 번호부터 이어서 매긴다(읽지 못한 파일을 바꿀 때 옛 ID를 다시 내지 않도록)."""
    return {"kind": KIND, "schema_version": SCHEMA_VERSION, "project_id": project_id,
            "counters": dict(dict.fromkeys(ID_FORMATS, 0), **(counters or {})), "candidates": {}, "groups": {},
            "headings": {}, "end_states": {}, "basic_events": {}, "coverage": {}, "history": []}


def issued_numbers(text):
    """글 안에 보이는 ID 번호의 접두어별 최댓값({IEC: n, ...}, 없는 접두어는 0). 읽지 못한 파일의 원본 글에서 쓴다."""
    out = dict.fromkeys(ID_FORMATS, 0)
    for prefix, num in re.findall(r"(IEC|IEG|H|ES|BE)-(\d+)", text):  # 더 크게 잡는 쪽은 안전하다
        out[prefix] = max(out[prefix], int(num))
    return out


def _id_number(prefix, value):
    m = re.fullmatch(ID_FORMATS[prefix].split("%")[0] + r"(\d+)", value or "")
    return int(m.group(1)) if m else None


def problems(doc):
    """형식 문제 목록(빈 목록이면 편집 가능). store.load가 경계 검사로 쓴다."""
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        return ["kind가 %s가 아님" % KIND]
    out = []
    counters = doc.get("counters")
    if not isinstance(counters, dict) or set(counters) != set(ID_FORMATS) \
            or not all(type(v) is int and v >= 0 for v in counters.values()):
        return ["counters 형식이 맞지 않음"]
    tables = {"candidates": "IEC", "groups": "IEG", "headings": "H", "end_states": "ES", "basic_events": "BE"}
    for table, prefix in tables.items():
        if not isinstance(doc.get(table), dict):
            out.append("%s가 객체가 아님" % table)
            continue
        for k, v in doc[table].items():
            n = _id_number(prefix, k)
            if n is None or n > counters[prefix] or not isinstance(v, dict):
                out.append("%s: ID 형식 또는 번호가 맞지 않음(%s)" % (table, k))
    if out:
        return out
    if not isinstance(doc.get("coverage"), dict) or not isinstance(doc.get("history"), list):
        return ["coverage·history 형식이 맞지 않음"]
    groups = doc["groups"]
    seen = set()
    for iec, c in doc["candidates"].items():
        if not isinstance(c.get("key"), str) or SEP not in c["key"] or c["key"] in seen:
            out.append("%s: key가 없거나 중복" % iec)
        seen.add(c.get("key"))
        g = c.get("group_id")
        if g is not None and (g not in groups or groups[g].get("status") in RETIRED):
            out.append("%s: 없는(또는 나뉨·삭제) 그룹 %s에 소속" % (iec, g))
        if c.get("placed_by") not in (None,) + ORIGINS or (g is None) != (c.get("placed_by") is None):
            out.append("%s: placed_by 값 %r" % (iec, c.get("placed_by")))
    for gid, g in groups.items():
        if g.get("status") not in GROUP_STATUSES or g.get("origin") not in ORIGINS:
            out.append("%s: status·origin 값이 맞지 않음" % gid)
        for h in g.get("heading_ids", []):
            if h not in doc["headings"]:
                out.append("%s: 없는 표제 %s" % (gid, h))
        for e in g.get("end_state_ids", []):
            if e not in doc["end_states"]:
                out.append("%s: 없는 최종상태 %s" % (gid, e))
        for s in g.get("split_into", []):
            if s not in groups:
                out.append("%s: 나뉜 그룹(%s)이 없음" % (gid, s))
        if g.get("status") == "confirmed" and not isinstance(g.get("confirmation"), dict):
            out.append("%s: 확정 기록 없음" % gid)
    for table in ("headings", "end_states", "basic_events"):
        for k, v in doc[table].items():
            if v.get("status") not in RECORD_STATUSES or v.get("origin") not in ORIGINS:
                out.append("%s: status·origin 값이 맞지 않음" % k)
    return out


# ---------------------------------------------------------------- ⑤ 사실(결과 문서 읽기만)

def entry_facts(results):
    """{key: {approved, ie_human, judgement, category, fp, entry, node_id, deviation_id}} 결과 칸 순서대로."""
    out = {}
    if not results:
        return out
    gid = results.get("graph_id")
    for cell in results["cells"]:
        for e in cell["entries"]:
            hint = e.get("ie_hint") if isinstance(e.get("ie_hint"), dict) else {}
            out[key_of(gid, e["entry_id"])] = {
                "approved": e.get("status") == "approved",
                "ie_human": hint.get("origin") == "human",
                "judgement": hint.get("candidate") if hint.get("candidate") in res.IE_CANDIDATES else "undecided",
                "category": hint.get("category"),
                "fp": _sha({k: e.get(k) for k in MEMBER_FIELDS}),
                "entry": e, "node_id": cell["node_id"], "deviation_id": cell["deviation_id"]}
    return out


def iec_of(doc):
    """{key: IEC}."""
    return {c["key"]: iec for iec, c in doc["candidates"].items()}


def members_of(doc, gid):
    return sorted(iec for iec, c in doc["candidates"].items() if c["group_id"] == gid)


def live_groups(doc):
    return sorted(g for g, v in doc["groups"].items() if v["status"] not in RETIRED)


def source_keys(table, rec):
    """표제·최종상태·기본사건 기록이 나온 ⑤ 항목 키. 사람이 출처 없이 쓴 기록은 빈 목록."""
    return list(rec["source_keys"]) if table == "end_states" else [s["key"] for s in rec["sources"]]


def in_scope(table, rec, facts):
    """⑤ 출처가 있는 기록은 출처 가운데 승인 항목이 하나라도 있어야 묶음에 든다. 출처 없이 사람이 쓴 기록은 든다."""
    keys = source_keys(table, rec)
    return not keys or any((facts.get(k) or {}).get("approved") for k in keys)


def _member_problems(doc, iec, facts):
    c = doc["candidates"][iec]
    f = facts.get(c["key"])
    if f is None:
        return ["%s: ⑤ 결과에서 찾을 수 없음" % iec]
    out = []
    if not f["approved"]:
        out.append("%s: ⑤ 승인 풀림" % iec)
    if not f["ie_human"]:
        out.append("%s: 초기사건 판정이 AI 초안임(⑤에서 사람이 판정해야 함)" % iec)
    elif f["judgement"] != "yes":
        out.append("%s: 판정이 '%s'라 그룹에 넣을 수 없음" % (iec, res.IE_CANDIDATES[f["judgement"]]))
    if c["placed_by"] != "human":
        out.append("%s: 규칙이 배정한 소속을 아직 확인하지 않음" % iec)
    return out


def confirm_problems(doc, gid, results, facts=None):
    """그룹을 확정할 수 없는(또는 확정이 풀린) 이유. 화면의 [확정] 버튼과 confirm()이 같은 함수를 쓴다."""
    g = doc["groups"].get(gid)
    if g is None:
        return ["없는 그룹: %s" % gid]
    if g["status"] in RETIRED:
        return ["%s 그룹이라 확정할 수 없음" % GROUP_STATUSES[g["status"]]]
    facts = entry_facts(results) if facts is None else facts
    members = members_of(doc, gid)
    out = [] if members else ["소속 후보가 없음"]
    for iec in members:
        out += _member_problems(doc, iec, facts)
    if g["representative"] is not None and g["representative"] not in members:
        out.append("대표 후보(%s)가 소속 후보가 아님" % g["representative"])
    for table, ids, what in (("headings", g["heading_ids"], "표제"), ("end_states", g["end_state_ids"], "최종상태")):
        for rid in ids:
            r = doc[table][rid]
            if r["status"] != "live":
                out.append("%s: 지운 %s" % (rid, what))
            elif r["origin"] != "human":
                out.append("%s: AI 초안 %s(받아들이기 전)" % (rid, what))
            elif not in_scope(table, r, facts):
                out.append("%s: ⑤ 출처 항목의 승인이 모두 풀려 묶음에서 빠지는 %s" % (rid, what))
    return out


def digest(doc, gid, results, facts=None):
    """그룹 내용 지문: 그룹 필드, 소속(후보·소속을 정한 쪽·⑤ 내용 지문), 참조하는 표제·최종상태 기록."""
    facts = entry_facts(results) if facts is None else facts
    g = doc["groups"][gid]
    strip = lambda r: {k: v for k, v in r.items() if k != "status"}  # noqa: E731
    return _sha({
        "group": {k: g[k] for k in EDITABLE["group"] + ("heading_ids", "end_state_ids")},
        "members": [[iec, c["placed_by"], (facts.get(c["key"]) or {}).get("fp")]
                    for iec, c in ((i, doc["candidates"][i]) for i in members_of(doc, gid))],
        "headings": {h: strip(doc["headings"][h]) for h in g["heading_ids"]},
        "end_states": {e: strip(doc["end_states"][e]) for e in g["end_state_ids"]}})


def effective_status(doc, gid, results, facts=None):
    g = doc["groups"][gid]
    if g["status"] != "confirmed":
        return g["status"]
    facts = entry_facts(results) if facts is None else facts
    ok = g["origin"] == "human" and not confirm_problems(doc, gid, results, facts) and \
        digest(doc, gid, results, facts) == (g.get("confirmation") or {}).get("digest")
    return "confirmed" if ok else "draft"


# ---------------------------------------------------------------- 전이의 한 길목

def _change(doc, op, ids, touched, at, fn, **detail):
    """사본에 fn을 적용하고, touched 그룹 중 저장 상태가 확정인 것을 초안으로 내린 뒤 history에 한 줄 남긴다.
    (새 문서, fn의 반환값)."""
    out = copy.deepcopy(doc)
    value = fn(out)
    demoted = []
    for g in dict.fromkeys(t for t in touched if t):
        rec = out["groups"].get(g)
        if rec is not None and rec["status"] == "confirmed":
            rec["status"], rec["confirmation"] = "draft", None
            demoted.append(g)
    row = store_io.history_row(op, dict({"ids": list(ids)}, **detail), at)
    if demoted:
        row["demoted"] = demoted
    out["history"].append(row)
    return out, value


def _next_id(out, prefix):
    out["counters"][prefix] += 1
    return ID_FORMATS[prefix] % out["counters"][prefix]


def _record(doc, ref):
    kind, rid = ref
    if kind == "member":
        if rid not in doc["candidates"]:
            raise ValueError("없는 후보: %s" % rid)
        return doc["candidates"][rid]
    if kind not in COLLECTIONS:
        raise ValueError("모르는 종류: %s" % kind)
    rec = doc[COLLECTIONS[kind][0]].get(rid)
    if rec is None:
        raise ValueError("없는 ID: %s" % rid)
    return rec


def _groups_touching(doc, ref):
    kind, rid = ref
    if kind == "group":
        return [rid]
    if kind == "member":
        return [doc["candidates"][rid]["group_id"]]
    field = {"heading": "heading_ids", "end_state": "end_state_ids"}.get(kind)
    return [g for g, v in doc["groups"].items() if field and rid in v[field]]


def _live_group(doc, gid):
    g = doc["groups"].get(gid)
    if g is None:
        raise ValueError("없는 그룹: %s" % gid)
    if g["status"] in RETIRED:
        raise ValueError("%s 그룹은 %s 상태라 고칠 수 없습니다" % (gid, GROUP_STATUSES[g["status"]]))
    return g


def _group_record(name, origin, rule_key=None):
    return {"name": name, "definition": "", "categories": [], "representative": None, "representative_reason": "",
            "plant_response": "", "affected_mitigation": "", "support_ie": "unknown", "heading_ids": [],
            "end_state_ids": [], "origin": origin, "rule_key": rule_key, "status": "draft", "confirmation": None,
            "split_from": None, "split_into": []}


def _check_fields(doc, kind, fields):
    unknown = sorted(set(fields) - set(EDITABLE[kind]))
    if unknown:
        raise ValueError("고칠 수 없는 필드: %s" % ", ".join(unknown))
    lists = {"categories", "targets"}
    for k, v in fields.items():
        if k in lists:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ValueError("%s는 문자열 목록이어야 함" % k)
        elif k == "representative":
            if v is not None and v not in doc["candidates"]:
                raise ValueError("없는 후보: %s" % v)
        elif not isinstance(v, str):
            raise ValueError("%s는 문자열이어야 함" % k)
    for k, allowed in (("support_ie", SUPPORT_IE), ("role", refs.ROLES), ("actuation", refs.ACTUATIONS),
                       ("category", ES_CATEGORIES)):
        if k in fields and fields[k] not in allowed:
            raise ValueError("%s 값 %r(%s)" % (k, fields[k], "/".join(allowed)))


# ---------------------------------------------------------------- ⑤와 맞추기

def sync(doc, results, at=None):
    """1) IEC가 없는 승인 항목에 다음 IEC를 준다(결과 칸 순서, 그룹 없음). 2) 저장 상태는 확정인데 실제로는 초안인 그룹을
    이유와 함께 내린다. 두 번 돌려도 더하는 것이 없고, 할 일이 없으면 받은 문서를 그대로 돌려준다."""
    facts = entry_facts(results)
    known = iec_of(doc)
    new = [k for k, f in facts.items() if f["approved"] and k not in known]
    stale = {}
    for gid in live_groups(doc):
        if doc["groups"][gid]["status"] == "confirmed" and effective_status(doc, gid, results, facts) == "draft":
            why = confirm_problems(doc, gid, results, facts)
            stale[gid] = "; ".join(why) if why else "⑤ 항목 내용 또는 그룹 내용이 확정 뒤 바뀜"
    if not new and not stale:
        return doc
    out = doc
    if new:
        def add(o):
            for k in new:
                o["candidates"][_next_id(o, "IEC")] = {"key": k, "group_id": None, "placed_by": None}
        out, _ = _change(out, "sync", [], [], at, add, added=len(new))
    for gid, why in stale.items():
        out, _ = _change(out, "demote", [gid], [gid], at, lambda o: None, reason=why)
    return out


# ---------------------------------------------------------------- 규칙 초안(§6.3)

def _norm(text):
    return " ".join((text or "").split()).lower()


def rule_key(fact):
    """같은 일반 범주 + 같은 보호수단 집합이면 같은 그룹 후보."""
    sgs = sorted({_norm(s["text"]) for s in refs.safeguard_items(fact["entry"]) if s["text"].strip()})
    return "%s|%s" % (fact["category"], ";".join(sgs))


def _be_name(node, tag, mode):
    """E6 꼴 '<계통>-<기기 종류>-<고장모드>-<태그>' 제안. 계통은 태그 앞부분으로 짐작한다(PSA 기본사건 이름은 따로 둠)."""
    system, _, rest = (tag or "").partition("-")
    kind = (node or {}).get("kind") or ""
    parts = (system, kind, mode or "미정", rest) if rest else (kind, mode or "미정", tag)
    return "-".join(p for p in parts if p)


def suggest(doc, results, pg=None, at=None):
    """§6.3 결정적 규칙 초안. 그룹이 없고 판정이 '후보'이며 범주가 있는 승인 후보만 보고, 초안 그룹만 만들거나 넓힌다.
    표제는 보호수단, 최종상태는 비완화 결과, 기본사건은 원인 위치·고장모드와 보호수단 구현 대상에서 모은다.
    모두 origin ai_draft·placed_by ai_draft이고 확정하지 않는다. 같은 것을 다시 만들지 않으므로 두 번 돌려도 더하는 것이 없다."""
    facts = entry_facts(results)
    picked = []
    for iec, c in sorted(doc["candidates"].items()):
        f = facts.get(c["key"])
        if c["group_id"] is None and f and f["approved"] and f["judgement"] == "yes" and f["category"]:
            picked.append((iec, f))
    if not picked:
        return doc
    idx = refs.index(pg) if pg else {}

    def apply(o):
        by_rule = {v["rule_key"]: g for g, v in sorted(o["groups"].items())
                   if v["status"] == "draft" and v.get("rule_key")}
        live = lambda table: {v.get("source_key") or v.get("key"): k for k, v in sorted(o[table].items())  # noqa: E731
                              if v["status"] == "live"}
        headings, ends, bes = live("headings"), live("end_states"), live("basic_events")
        touched = []
        for iec, f in picked:
            rk = rule_key(f)
            gid = by_rule.get(rk)
            if gid is None:
                gid = _next_id(o, "IEG")
                o["groups"][gid] = _group_record(res.ie_category_label(f["category"]), "ai_draft", rk)
                o["groups"][gid]["categories"] = [f["category"]]
                o["groups"][gid]["representative"] = iec
                by_rule[rk] = gid
            g = o["groups"][gid]
            o["candidates"][iec].update(group_id=gid, placed_by="ai_draft")
            touched.append(gid)
            e = f["entry"]
            for i, s in enumerate(refs.safeguard_items(e)):
                sk = _norm(s["text"])
                if not sk:
                    continue
                if sk not in headings:
                    hid = _next_id(o, "H")
                    o["headings"][hid] = {"name": s["text"].strip(), "sources": [{"key": o["candidates"][iec]["key"],
                                                                                  "index": i, "text": s["text"]}],
                                          "targets": [r["ref"] for r in s["refs"] if r.get("ref")], "systems": "",
                                          "role": s["role"], "actuation": s["actuation"], "operator_cue": "",
                                          "origin": "ai_draft", "source_key": sk, "status": "live"}
                    headings[sk] = hid
                if headings[sk] not in g["heading_ids"]:
                    g["heading_ids"].append(headings[sk])
                for r in s["refs"]:
                    _add_be(o, bes, idx, r.get("ref"), None, "safeguard", o["candidates"][iec]["key"], headings[sk])
            ck = _norm(e.get("consequence"))
            if ck:
                if ck not in ends:
                    esid = _next_id(o, "ES")
                    o["end_states"][esid] = {"text": (e.get("consequence") or "").strip(), "category": "unclassified",
                                             "source_keys": [o["candidates"][iec]["key"]], "origin": "ai_draft",
                                             "source_key": ck, "status": "live"}
                    ends[ck] = esid
                es = o["end_states"][ends[ck]]
                if es["origin"] == "ai_draft" and o["candidates"][iec]["key"] not in es["source_keys"]:
                    es["source_keys"].append(o["candidates"][iec]["key"])  # 비완화 기준은 출처마다 확인한다
                if ends[ck] not in g["end_state_ids"]:
                    g["end_state_ids"].append(ends[ck])
            for r in e.get("cause_refs") or []:
                if isinstance(r, dict):
                    _add_be(o, bes, idx, r.get("ref"), r.get("failure_mode"), "cause", o["candidates"][iec]["key"],
                            None)
        return touched

    out, _ = _change(doc, "suggest", [i for i, _ in picked], [], at, apply)
    return out


def _add_be(o, bes, idx, ref, mode, kind, key, heading):
    if not ref:
        return
    bkey = "%s|%s" % (ref, mode or "")
    if bkey not in bes:
        bid = _next_id(o, "BE")
        node = idx.get(ref)
        tag = refs.node_text(node) if node else ref.partition("#")[2]
        o["basic_events"][bid] = {"key": bkey, "ref": ref, "tag": tag, "name": _be_name(node, tag, mode),
                                  "equipment_kind": (node or {}).get("kind") or "",
                                  "system": tag.partition("-")[0] if "-" in tag else "", "failure_mode": mode or "",
                                  "failure_text": "", "sources": [], "heading_ids": [], "origin": "ai_draft",
                                  "status": "live"}
        bes[bkey] = bid
    be = o["basic_events"][bes[bkey]]
    if be["origin"] == "ai_draft":  # 사람이 받아들인 기록은 규칙이 넓히지 않는다
        src = {"kind": kind, "key": key}
        if src not in be["sources"]:
            be["sources"].append(src)
        if heading and heading not in be["heading_ids"]:
            be["heading_ids"].append(heading)


# ---------------------------------------------------------------- 사람 편집

def create_group(doc, name, iecs=(), at=None):
    """(문서, 새 그룹 ID). 사람이 만든 그룹이고 고른 후보는 사람이 넣은 소속이 된다."""
    if not (name or "").strip():
        raise ValueError("그룹 이름이 비었습니다")
    for i in iecs:
        _record(doc, ("member", i))
    old = [doc["candidates"][i]["group_id"] for i in iecs]

    def apply(o):
        gid = _next_id(o, "IEG")
        o["groups"][gid] = _group_record(name.strip(), "human")
        cleared = []
        for i in iecs:
            cleared += _leave(o, i)
            o["candidates"][i].update(group_id=gid, placed_by="human")
        if iecs:
            o["groups"][gid]["representative"] = sorted(iecs)[0]
        return gid, cleared
    out, (gid, cleared) = _change(doc, "create_group", list(iecs), old, at, apply)
    out["history"][-1]["ids"].insert(0, gid)
    if cleared:
        out["history"][-1]["representative_cleared"] = cleared
    return out, gid


def _leave(o, iec):
    """후보가 지금 그룹을 떠나기 직전에 부른다. 그 그룹의 대표 후보였으면 대표를 비우고 [그 그룹 ID]를 돌려준다
    (남겨 두면 옛 그룹 확정이 막힘). 아니면 []."""
    gid = o["candidates"][iec]["group_id"]
    old = o["groups"].get(gid)
    if old is not None and old["representative"] == iec:
        old["representative"] = None
        return [gid]
    return []


def place(doc, iec, gid, at=None):
    """후보를 그룹 gid로 옮기거나(gid None이면) 그룹에서 뺀다. 사람이 정한 소속이 된다. 옛 그룹·새 그룹을 모두 건드린다.
    옛 그룹의 대표 후보였으면 옛 그룹의 대표를 비운다. history에 옛 그룹(from)과 대표를 비운 그룹을 남긴다."""
    c = _record(doc, ("member", iec))
    if gid is not None:
        _live_group(doc, gid)

    def apply(o):
        cleared = _leave(o, iec) if gid != c["group_id"] else []
        o["candidates"][iec].update(group_id=gid, placed_by="human" if gid else None)
        return cleared
    out, cleared = _change(doc, "place", [iec], [c["group_id"], gid], at, apply, to=gid, **{"from": c["group_id"]})
    if cleared:
        out["history"][-1]["representative_cleared"] = cleared
    return out


def accept(doc, ref, at=None):
    """규칙·AI 초안을 사람이 받아들인다: 소속(member)은 placed_by, 그룹·표제·최종상태·기본사건은 origin을 human으로."""
    rec = _record(doc, ref)
    if ref[0] == "member" and rec["group_id"] is None:
        raise ValueError("%s 후보는 그룹에 들지 않아 확인할 소속이 없습니다" % ref[1])
    if ref[0] == "group":
        _live_group(doc, ref[1])

    def apply(o):
        r = _record(o, ref)
        r["placed_by" if ref[0] == "member" else "origin"] = "human"
    return _change(doc, "accept", [ref[1]], _groups_touching(doc, ref), at, apply)[0]


def edit(doc, ref, fields, at=None):
    """ref 종류의 EDITABLE 필드를 고친다. 표제·최종상태·기본사건은 사람이 쓴 것이 된다. history에 바뀐 필드의 이전 값."""
    kind = ref[0]
    if kind not in EDITABLE:
        raise ValueError("고칠 수 없는 종류: %s" % kind)
    rec = _record(doc, ref)
    if kind == "group":
        _live_group(doc, ref[1])
    elif rec["status"] != "live":
        raise ValueError("지운 기록(%s)은 고칠 수 없습니다" % ref[1])
    _check_fields(doc, kind, fields)
    before = {k: copy.deepcopy(rec.get(k)) for k in sorted(fields) if rec.get(k) != fields[k]}
    if not before:
        return doc

    def apply(o):
        r = _record(o, ref)
        r.update(copy.deepcopy(fields))
        if kind != "group":
            r["origin"] = "human"
    return _change(doc, "edit", [ref[1]], _groups_touching(doc, ref), at, apply, before=before)[0]


def _add(doc, gid, kind, record, at):
    """사람이 쓴 표제·최종상태를 새 ID로 만들어 그룹 gid에 붙인다."""
    _live_group(doc, gid)
    table, prefix = COLLECTIONS[kind]

    def apply(o):
        rid = _next_id(o, prefix)
        o[table][rid] = record
        o["groups"][gid][{"heading": "heading_ids", "end_state": "end_state_ids"}[kind]].append(rid)
        return rid
    out, rid = _change(doc, "add_" + kind, [], [gid], at, apply)
    out["history"][-1]["ids"] = [rid, gid]
    return out, rid


def add_heading(doc, gid, fields, at=None):
    """(문서, 새 표제 ID). 사람이 쓴 표제를 그룹에 붙인다."""
    _check_fields(doc, "heading", fields)
    if not (fields.get("name") or "").strip():
        raise ValueError("표제 이름이 비었습니다")
    rec = {"name": "", "sources": [], "targets": [], "systems": "", "role": "mitigative", "actuation": "unknown",
           "operator_cue": "", "origin": "human", "source_key": None, "status": "live"}
    rec.update(copy.deepcopy(fields))
    return _add(doc, gid, "heading", rec, at)


def add_end_state(doc, gid, fields, at=None):
    _check_fields(doc, "end_state", fields)
    if not (fields.get("text") or "").strip():
        raise ValueError("최종상태 문장이 비었습니다")
    rec = {"text": "", "category": "unclassified", "source_keys": [], "origin": "human", "source_key": None,
           "status": "live"}
    rec.update(copy.deepcopy(fields))
    return _add(doc, gid, "end_state", rec, at)


def attach(doc, gid, ref, on=True, at=None):
    """표제·최종상태 ref를 그룹에 붙이거나(on) 뗀다."""
    _live_group(doc, gid)
    kind, rid = ref
    field = {"heading": "heading_ids", "end_state": "end_state_ids"}.get(kind)
    if field is None:
        raise ValueError("그룹에 붙일 수 없는 종류: %s" % kind)
    if _record(doc, ref)["status"] != "live" and on:
        raise ValueError("지운 기록(%s)은 붙일 수 없습니다" % rid)
    if (rid in doc["groups"][gid][field]) == on:
        return doc

    def apply(o):
        lst = o["groups"][gid][field]
        lst.append(rid) if on else lst.remove(rid)
    return _change(doc, "attach" if on else "detach", [gid, rid], [gid], at, apply)[0]


def remove(doc, ref, at=None):
    """표제·최종상태·기본사건을 지운다(status deleted, 기록은 남김). 붙어 있던 그룹에서 떼므로 그 그룹을 건드린다."""
    kind, rid = ref
    if kind not in ("heading", "end_state", "basic_event"):
        raise ValueError("지울 수 없는 종류: %s" % kind)
    if _record(doc, ref)["status"] != "live":
        return doc
    touched = _groups_touching(doc, ref)

    def apply(o):
        _record(o, ref)["status"] = "deleted"
        field = {"heading": "heading_ids", "end_state": "end_state_ids"}.get(kind)
        for g in touched:
            o["groups"][g][field].remove(rid)
        if kind == "heading":
            for be in o["basic_events"].values():
                if rid in be["heading_ids"]:
                    be["heading_ids"].remove(rid)
    return _change(doc, "remove", [rid], touched, at, apply)[0]


def confirm(doc, gid, results, reviewer, at=None):
    """사람이 그룹을 확정한다. 검토자 이름이 없거나 confirm_problems가 있으면 ValueError. 확정하는 검토자가 그룹 필드도
    받아들이는 것이므로 그룹 origin을 human으로 바꾼다(effective_status는 origin이 human인 그룹만 확정으로 본다)."""
    if not (reviewer or "").strip():
        raise ValueError("검토자 이름이 있어야 확정할 수 있습니다")
    facts = entry_facts(results)
    bad = confirm_problems(doc, gid, results, facts)
    if bad:
        raise ValueError("; ".join(bad))
    d = digest(doc, gid, results, facts)
    if effective_status(doc, gid, results, facts) == "confirmed":
        return doc
    at = at or now_utc()

    def apply(o):
        o["groups"][gid].update(status="confirmed", origin="human",
                                confirmation={"at": at, "by": reviewer.strip(), "digest": d})
    return _change(doc, "confirm", [gid], [], at, apply, by=reviewer.strip())[0]


def reopen(doc, gid, at=None):
    """확정을 풀어 초안으로 되돌린다(고치거나 지우기 전). 초안이면 그대로."""
    if _live_group(doc, gid)["status"] != "confirmed":
        return doc
    return _change(doc, "reopen", [gid], [gid], at, lambda o: None)[0]


def split(doc, gid, moved, at=None):
    """(문서, (남는 쪽 새 ID, 옮긴 쪽 새 ID)). moved는 소속 후보의 비어 있지 않은 진부분집합. 옛 그룹은 '나뉨'과 새 ID를
    기록으로 남기고, 두 새 그룹은 초안으로 시작한다. 소속을 정한 쪽(placed_by)은 그대로 둔다(나누기는 AI 소속을 받아들이는
    것이 아님)."""
    _live_group(doc, gid)
    members = members_of(doc, gid)
    moved = sorted(set(moved))
    if not moved or not set(moved) < set(members):
        raise ValueError("나눌 후보는 소속 후보 일부여야 합니다(전부·없음은 안 됨)")

    def apply(o):
        old = o["groups"][gid]
        a, b = _next_id(o, "IEG"), _next_id(o, "IEG")
        for new, part in ((a, [m for m in members if m not in moved]), (b, moved)):
            rec = copy.deepcopy(old)
            rec.update(status="draft", confirmation=None, split_from=gid, split_into=[], rule_key=None)
            rec["representative"] = old["representative"] if old["representative"] in part else part[0]
            o["groups"][new] = rec
            for m in part:
                o["candidates"][m]["group_id"] = new
        old.update(status="split", confirmation=None, split_into=[a, b])
        return a, b
    out, pair = _change(doc, "split", [gid], [], at, apply, moved=moved)
    out["history"][-1]["ids"] += list(pair)
    return out, pair


def delete_group(doc, gid, at=None):
    """초안 그룹만 지운다(확정 그룹은 먼저 reopen). 소속 후보는 그룹 없음이 되고 ID는 '삭제' 기록으로 남는다."""
    g = _live_group(doc, gid)
    if g["status"] != "draft":
        raise ValueError("확정한 그룹은 먼저 확정을 풀어야 지울 수 있습니다")

    def apply(o):
        for m in members_of(o, gid):
            o["candidates"][m].update(group_id=None, placed_by=None)
        o["groups"][gid].update(status="deleted", confirmation=None)
    return _change(doc, "delete_group", [gid], [gid], at, apply)[0]


def set_coverage(doc, code, disposition, reason, reviewer, at=None):
    """완전성 대조 공백 행의 사람 판정. disposition은 COVERAGE 키 또는 None(지움). 정할 때는 사유가 있어야 한다."""
    if disposition is not None:
        if disposition not in COVERAGE:
            raise ValueError("처리 값 %r(%s)" % (disposition, "/".join(COVERAGE)))
        if not (reason or "").strip():
            raise ValueError("사유를 적어야 합니다")
        if not (reviewer or "").strip():
            raise ValueError("검토자 이름이 있어야 합니다")
    at = at or now_utc()
    new = None if disposition is None else {"disposition": disposition, "reason": reason.strip(),
                                            "by": reviewer.strip(), "at": at}
    if doc["coverage"].get(code) == new or (new is None and code not in doc["coverage"]):
        return doc

    def apply(o):
        if new is None:
            o["coverage"].pop(code, None)
        else:
            o["coverage"][code] = new
    return _change(doc, "coverage", [code], [], at, apply, disposition=disposition)[0]
