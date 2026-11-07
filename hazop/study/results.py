"""⑤ 분석 결과 셸: 검토구간 × 편차 행렬. 4단계에서 AI가 칸을 채운다. 근거: 3단계 명세 §B results.py.

편차 목록은 데이터/이탈후보/kosha-p86-2017-deviation-chart.json의 items(파라미터 × 가이드워드)에서 만든다.
"""

import json

from hazop import paths

SCHEMA_VERSION = "0.1"
KIND = "hazop_study_results"
DEVIATION_CHART = ("데이터", "이탈후보", "kosha-p86-2017-deviation-chart.json")
CELL_STATES = ("not_analyzed", "analyzed", "excluded")
ENTRY_ORIGINS = ("ai_draft", "human")
ENTRY_STATUSES = ("proposed", "revised", "approved", "rejected")


def load_deviations(path=None):
    """[{deviation_id, item_id, parameter, guideword, label}] 파일 순서대로. deviation_id는 D01부터."""
    with open(path or paths.resource_path(*DEVIATION_CHART), encoding="utf-8") as fh:
        chart = json.load(fh)
    return [{"deviation_id": "D%02d" % (i + 1), "item_id": item["item_id"], "parameter": item["parameter_ko"],
             "guideword": item["guide_word_ko"], "label": item["deviation_ko"]}
            for i, item in enumerate(chart["items"])]


def empty_results(node_set, deviations):
    """모든 칸이 not_analyzed이고 entries가 빈 결과."""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "graph_id": node_set.get("graph_id"),
        "study_nodes_ref": {"graph_version": node_set.get("graph_version"),
                            "confirmed_at": node_set.get("confirmed_at")},
        "deviations": [dict(d) for d in deviations],
        "cells": [{"node_id": n["node_id"], "deviation_id": d["deviation_id"], "state": "not_analyzed", "entries": []}
                  for n in node_set["nodes"] for d in deviations],
    }


def is_ai_draft(entry):
    """AI가 쓴 항목은 승인 전까지 초안이다(화면에 'AI 초안'으로 표시)."""
    return entry.get("origin") == "ai_draft" and entry.get("status") != "approved"


def matrix_summary(results):
    """{node_id: {deviation_id: {state, scenarios, max_risk, unreviewed}}}. scenarios는 기각되지 않은 항목 수.
    unreviewed는 제안 상태 항목과, 사람이 고쳤어도 승인 전인 AI 초안(revised)을 함께 센다."""
    out = {}
    for cell in results["cells"]:
        live = [e for e in cell["entries"] if e.get("status") != "rejected"]
        risks = [e["risk"] for e in live if e.get("risk") is not None]
        out.setdefault(cell["node_id"], {})[cell["deviation_id"]] = {
            "state": cell["state"],
            "scenarios": len(live),
            "max_risk": max(risks) if risks else None,
            "unreviewed": sum(e.get("status") == "proposed" or (is_ai_draft(e) and e.get("status") != "rejected")
                              for e in cell["entries"]),
        }
    return out


def validate(results, node_set=None):
    """문제 목록(빈 목록이면 통과). node_set을 주면 그 집합에 없는 node_id 참조도 본다."""
    problems = []
    if results.get("kind") != KIND:
        problems.append("kind가 %s가 아님" % KIND)
    deviation_ids = [d.get("deviation_id") for d in results.get("deviations", [])]
    if len(set(deviation_ids)) != len(deviation_ids):
        problems.append("deviation_id 중복")
    node_ids = None if node_set is None else {n["node_id"] for n in node_set["nodes"]}
    seen_cells, seen_entries = set(), set()
    for cell in results.get("cells", []):
        where = "%s/%s" % (cell.get("node_id"), cell.get("deviation_id"))
        if (cell.get("node_id"), cell.get("deviation_id")) in seen_cells:
            problems.append("%s: 칸 중복" % where)
        seen_cells.add((cell.get("node_id"), cell.get("deviation_id")))
        if node_ids is not None and cell.get("node_id") not in node_ids:
            problems.append("%s: 없는 검토구간 참조" % where)
        if cell.get("deviation_id") not in deviation_ids:
            problems.append("%s: 없는 편차 참조" % where)
        if cell.get("state") not in CELL_STATES:
            problems.append("%s: state 값 %r" % (where, cell.get("state")))
        for e in cell.get("entries", []):
            eid = e.get("entry_id")
            if not eid or eid in seen_entries:
                problems.append("%s: entry_id 없음 또는 중복 %r" % (where, eid))
            seen_entries.add(eid)
            if e.get("origin") not in ENTRY_ORIGINS:
                problems.append("%s/%s: origin 값 %r" % (where, eid, e.get("origin")))
            if e.get("status") not in ENTRY_STATUSES:
                problems.append("%s/%s: status 값 %r" % (where, eid, e.get("status")))
            risk = e.get("risk")
            if risk is not None and (not isinstance(risk, int) or isinstance(risk, bool) or not 1 <= risk <= 5):
                problems.append("%s/%s: risk 값 %r(1~5 또는 null)" % (where, eid, risk))
        if cell.get("state") == "not_analyzed" and cell.get("entries"):
            problems.append("%s: not_analyzed 칸에 항목이 있음" % where)
    return problems
