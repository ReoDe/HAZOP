"""비교 핵심: 대응·지표·누락·초과·경고 (기획서/평가기준비교.md §3.2–§3.4, §3.6 경고, §4).

match(criteria, view) -> dict(metrics, pairs, missing, extra, criteria_warnings)
- 입력은 검사를 통과한 기준(정본 JSON)과 비교 입력 뷰뿐이다. 파일·네트워크·AI를 쓰지 않으며 결정적이다.
- 같은 후보에 기준 편차 둘이 대응하면(가이드워드 표기만 다른 같은 편차) CriteriaError(차단).
"""

from hazop.extract.adapters.evaluation import _FORBIDDEN, _r, hungarian
from hazop.evaluate.criteria import (CriteriaError, alias_map, all_groups, criteria_tags, groups_satisfied,
                                     guide_word_forms, norm, norm_tag, tag_in_text)

NOT_EVALUATED = "not_evaluated"


def _ratio(num, den):
    return _r(num / den) if den else None


def _match_deviation(dev, view_devs):
    """기준 편차 → (후보 또는 None, 사유 또는 None). 사유: not_in_catalog·ambiguous_deviation."""
    ref = dev["deviation_ref"]
    if ref.get("item_id"):
        hits = [c for c in view_devs if c.get("item_id") and norm(c["item_id"]) == norm(ref["item_id"])]
    else:
        gw = norm(ref["guide_word"])
        hits = [c for c in view_devs if norm(c.get("parameter_ko")) == norm(ref["parameter"])
                and gw in guide_word_forms(c.get("guide_word_ko"), c.get("guide_word_en"))]
    if not hits:
        return None, "not_in_catalog"
    if len(hits) > 1:
        return None, "ambiguous_deviation"
    return hits[0], None


def _cause_pair(row, scen, aliases, graph_tags):
    """(통과 여부, 점수, 설비 조건 통과 여부)."""
    cause = row["cause"]
    equip = cause.get("equipment") or []
    inter = 0
    equip_ok = True
    if equip:
        crit = {norm_tag(t, aliases) for t in equip} & graph_tags
        inter = len(crit & {norm(t) for t in scen["cause_equipment_tags"]})
        equip_ok = inter >= 1
    groups = cause.get("keywords") or []
    text = norm(scen.get("cause"))
    kw_ok = all_groups(groups, text)
    score = 10 * inter + groups_satisfied(groups, text)
    return equip_ok and kw_ok, score, equip_ok


def _assign_safeguards(items, outputs, aliases, graph_tags):
    """보호수단 배정(§3.4). 반환 (항목별 배정 출력 순번 또는 None, 미배정 출력 순번 목록)."""
    order = sorted(range(len(outputs)), key=lambda i: (norm(outputs[i].get("tag")) if outputs[i].get("tag") else "",
                                                        norm(outputs[i].get("description")), i))
    used, result = set(), [None] * len(items)
    for k, g in enumerate(items):
        if g.get("tag") is None:
            continue
        t = norm_tag(g["tag"], aliases)
        if t not in graph_tags:
            continue
        for i in order:
            o = outputs[i]
            if i in used or not o.get("tag") or norm(o["tag"]) != t:
                continue
            if g.get("keywords") is not None and not all_groups(g["keywords"], norm(o.get("description"))):
                continue
            used.add(i)
            result[k] = i
            break
    for k, g in enumerate(items):
        if g.get("tag") is not None:
            continue
        for i in order:
            if i not in used and all_groups(g["keywords"], norm(outputs[i].get("description"))):
                used.add(i)
                result[k] = i
                break
    return result, [i for i in order if i not in used]


def _warnings(criteria, aliases, graph_tags):
    out = []
    missing = {}
    for tag, rid, _where in criteria_tags(criteria):
        t = norm_tag(tag, aliases)
        if t not in graph_tags:
            missing.setdefault(t, set()).add(rid)
    for t in sorted(missing):
        out.append({"kind": "tag_not_in_graph", "tag": t, "row_ids": sorted(missing[t])})
    used = {norm(tag) for tag, _rid, _w in criteria_tags(criteria)}
    for alias in sorted(aliases):
        if alias not in used:
            out.append({"kind": "alias_unused", "alias": alias, "target": aliases[alias]})
    return out


def match(criteria, view):
    aliases = alias_map(criteria)
    graph_tags = set(view["graph_tags"])
    reviewed = view["basis"] == "reviewed"
    by_cand = {}
    for s in view["scenarios"]:
        by_cand.setdefault(s["candidate_id"], []).append(s)
    for lst in by_cand.values():
        lst.sort(key=lambda s: s["scenario_id"])

    devs = []  # 기준 편차별 계산 상태
    owner = {}
    for dev in criteria["deviations"]:
        cand, reason = _match_deviation(dev, view["deviations"])
        rows = dev["rows"]
        expected = dev.get("expected", "scenarios")
        d = {"dev": dev, "cand": cand, "rows": rows, "expected": expected,
             "required": expected == "no_scenario" or any(r.get("required", True) for r in rows)}
        if cand is not None:
            cid = cand["candidate_id"]
            if cid in owner:
                raise CriteriaError("기준 편차 %r와 %r가 같은 후보 %s에 대응(같은 편차 중복)"
                                    % (owner[cid], dev.get("label") or dev["deviation_ref"], cid))
            owner[cid] = dev.get("label") or dev["deviation_ref"]
            scens = by_cand.get(cid, []) if cand["selection_status"] == "selected" else []
            if cand["selection_status"] != "selected":
                reason = "not_selected"
            elif expected == "no_scenario":
                reason = "unexpected_scenarios" if scens else None
            else:
                reason = None if scens else "no_scenario"
            d["scens"] = scens
        else:
            d["scens"] = []
        d["reason"] = reason
        d["reproduced"] = reason is None
        devs.append(d)

    selected = {c["candidate_id"] for c in view["deviations"] if c["selection_status"] == "selected"}
    do = sorted(cid for cid in by_cand if cid in selected)
    dc = [d for d in devs if d["required"]]
    dc_cands = {d["cand"]["candidate_id"] for d in dc if d["cand"] is not None}
    so = sorted(s["scenario_id"] for cid in do if cid in dc_cands for s in by_cand[cid])

    pairs, missing_rows = [], []
    miss = {"consequences": [], "safeguards": [], "recommendations": []}
    extra_sg = []
    matched_scens = set()
    sums = {"cons": [0, 0], "sg": [0, 0], "rec": [0, 0]}
    rc = cause_hit = mc = optional = 0
    for d in devs:
        rows = sorted(d["rows"], key=lambda r: r["row_id"])
        scens = d["scens"] if d["reproduced"] and d["expected"] == "scenarios" else []
        info = {}
        if rows and scens:
            cost = []
            for r in rows:
                line = []
                for s in scens:
                    ok, score, equip_ok = _cause_pair(r, s, aliases, graph_tags)
                    info[(r["row_id"], s["scenario_id"])] = (ok, score, equip_ok)
                    line.append(-score if ok else _FORBIDDEN)
                cost.append(line)
            assigned = {rows[i]["row_id"]: (scens[j], info[(rows[i]["row_id"], scens[j]["scenario_id"])][1])
                        for i, j in hungarian(cost) if info[(rows[i]["row_id"], scens[j]["scenario_id"])][0]}
        else:
            assigned = {}
        for r in rows:
            req = r.get("required", True)
            rid = r["row_id"]
            if req:
                rc += 1
            if rid not in assigned:
                if req:
                    if not d["reproduced"] or d["expected"] != "scenarios":
                        why = "deviation_not_reproduced"
                    elif any(info[(rid, s["scenario_id"])][0] for s in scens):
                        why = "assigned_elsewhere"
                    elif (r["cause"].get("equipment")
                          and not any(info[(rid, s["scenario_id"])][2] for s in scens)):
                        why = "no_equipment_match"
                    else:
                        why = "no_keyword_match"
                    missing_rows.append({"row_id": rid, "reason": why, "cause": r["cause"]["text"],
                                         "deviation": d["dev"].get("label") or d["dev"]["deviation_ref"]})
                continue
            s, score = assigned[rid]
            matched_scens.add(s["scenario_id"])
            if req:
                cause_hit += 1
            else:
                optional += 1
            if d["required"]:
                mc += 1
            cons_text = norm(s.get("consequence"))
            cons = [all_groups(c["keywords"], cons_text)
                    and all(norm_tag(t, aliases) in graph_tags and tag_in_text(norm_tag(t, aliases), cons_text)
                            for t in c.get("equipment") or [])
                    for c in r["consequences"]]
            for n, (c, ok) in enumerate(zip(r["consequences"], cons), 1):
                if not ok:
                    miss["consequences"].append({"row_id": rid, "scenario_id": s["scenario_id"], "index": n,
                                                 "text": c["text"], "required": req})
            sg_items = r.get("safeguards")
            if sg_items is None:
                sg = None
            else:
                got, unused = _assign_safeguards(sg_items, s["safeguards"], aliases, graph_tags)
                sg = [g is not None for g in got]
                for n, (g, ok) in enumerate(zip(sg_items, sg), 1):
                    if not ok:
                        miss["safeguards"].append({"row_id": rid, "scenario_id": s["scenario_id"], "index": n,
                                                   "tag": g.get("tag"), "keywords": g.get("keywords"),
                                                   "text": g.get("text"), "required": req})
                for i in unused:
                    o = s["safeguards"][i]
                    extra_sg.append({"row_id": rid, "scenario_id": s["scenario_id"], "tag": o.get("tag"),
                                     "description": o.get("description")})
            recs_c = r.get("recommendations") or []
            if reviewed:
                texts = [norm(t) for t in s.get("recommendations") or []]
                rec = [any(all_groups(k["keywords"], t) for t in texts) for k in recs_c]
                for n, (k, ok) in enumerate(zip(recs_c, rec), 1):
                    if not ok:
                        miss["recommendations"].append({"row_id": rid, "scenario_id": s["scenario_id"],
                                                        "index": n, "text": k["text"], "required": req})
            else:
                rec = [None] * len(recs_c)
            if req:
                sums["cons"][0] += sum(cons)
                sums["cons"][1] += len(cons)
                if sg is not None:
                    sums["sg"][0] += sum(sg)
                    sums["sg"][1] += len(sg)
                if reviewed:
                    sums["rec"][0] += sum(rec)
                    sums["rec"][1] += len(rec)
            pairs.append({"row_id": rid, "scenario_id": s["scenario_id"], "worksheet_row": s.get("worksheet_row"),
                          "score": score, "consequences": cons, "safeguards": sg, "recommendations": rec})

    missing_devs = []
    for d in dc:
        if d["reproduced"]:
            continue
        item = {"deviation_ref": d["dev"]["deviation_ref"], "label": d["dev"].get("label"), "reason": d["reason"],
                "candidate_id": d["cand"]["candidate_id"] if d["cand"] else None}
        if d["reason"] == "not_selected":
            item["selection_status"] = d["cand"]["selection_status"]
        missing_devs.append(item)
    scen_by_id = {s["scenario_id"]: s for s in view["scenarios"]}
    dr = sum(1 for d in dc if d["reproduced"])
    metrics = {
        "deviation_recall": _ratio(dr, len(dc)),
        "cause_recall": _ratio(cause_hit, rc),
        "cause_precision": _ratio(mc, len(so)),
        "consequence_match": _ratio(*sums["cons"]),
        "safeguard_match": _ratio(*sums["sg"]),
        "recommendation_match": _ratio(*sums["rec"]) if reviewed else NOT_EVALUATED,
        "counts": {"Dc": len(dc), "Dr": dr, "Do": len(do), "Rc": rc, "M": len(pairs), "Mc": mc, "So": len(so),
                   "optional_matched": optional},
    }
    return {
        "metrics": metrics,
        "pairs": pairs,
        "missing": {"deviations": missing_devs, "rows": missing_rows, **miss},
        "extra": {
            "deviations": [{"candidate_id": cid, "scenario_ids": [s["scenario_id"] for s in by_cand[cid]]}
                           for cid in do if cid not in dc_cands],
            "scenarios": [{"scenario_id": sid, "candidate_id": scen_by_id[sid]["candidate_id"],
                           "worksheet_row": scen_by_id[sid].get("worksheet_row")}
                          for sid in so if sid not in matched_scens],
            "safeguards": extra_sg,
        },
        "criteria_warnings": _warnings(criteria, aliases, graph_tags),
    }
