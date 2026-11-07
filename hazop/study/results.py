"""⑤ 분석 결과 셸: 검토구간 × 편차 행렬. 4단계에서 AI가 칸을 채운다. 근거: 3단계 명세 §B results.py.

편차 목록은 데이터/이탈후보/kosha-p86-2017-deviation-chart.json의 items(파라미터 × 가이드워드)에서 만든다.
편집 연산(set_status·edit_entry)은 순수 함수다. 입력을 바꾸지 않고 새 dict를 돌려주며 항목 history에 한 줄 덧붙인다.
"""

import copy
import json
import os

from hazop import paths
from hazop.analysis.risk import FREQUENCIES, MATRIX_P86, SEVERITIES
from hazop.graph.project import LEGACY_PROJECT_DIR, UNREGISTERED_PROJECT
from hazop.kg.build import write_json_atomic
from hazop.study.nodes import now_utc

SCHEMA_VERSION = "0.1"
KIND = "hazop_study_results"
DEVIATION_CHART = ("데이터", "이탈후보", "kosha-p86-2017-deviation-chart.json")
CELL_STATES = ("not_analyzed", "analyzed", "excluded")
ENTRY_ORIGINS = ("ai_draft", "human")
ENTRY_STATUSES = ("proposed", "revised", "approved", "rejected")
HUMAN_STATUSES = ("revised", "approved", "rejected")  # proposed는 AI만 쓴다(재실행이 덮어쓰는 상태)
AI_RUN_STATUSES = ("ok", "failed")
EDITABLE_FIELDS = ("cause", "consequence", "safeguards", "recommendation", "severity", "frequency")


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
        "ai_log": [],
    }


def risk_of(severity, frequency):
    """〈표5〉 조회(MATRIX_P86). 둘 중 하나라도 null이거나 허용값 밖이면 None."""
    if type(severity) is not int or type(frequency) is not int:
        return None
    return MATRIX_P86.get(severity, {}).get(frequency)


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
            for name, allowed in (("severity", SEVERITIES), ("frequency", FREQUENCIES)):
                v = e.get(name)
                if v is not None and (type(v) is not int or v not in allowed):
                    problems.append("%s/%s: %s 값 %r(%d~%d 또는 null)" % (where, eid, name, v, allowed[0], allowed[-1]))
        if cell.get("state") == "not_analyzed" and cell.get("entries"):
            problems.append("%s: not_analyzed 칸에 항목이 있음" % where)
        run = cell.get("ai_run")
        if run is not None and (not isinstance(run, dict) or run.get("status") not in AI_RUN_STATUSES):
            problems.append("%s: ai_run.status 값 %r" % (where, (run or {}).get("status") if isinstance(run, dict)
                                                         else run))
    return problems


# ---------------------------------------------------------------- 사람 검토(순수 함수)

def _entry(results, node_id, deviation_id, entry_id):
    for cell in results["cells"]:
        if cell["node_id"] == node_id and cell["deviation_id"] == deviation_id:
            for e in cell["entries"]:
                if e["entry_id"] == entry_id:
                    return e
            raise ValueError("없는 항목: %s/%s/%s" % (node_id, deviation_id, entry_id))
    raise ValueError("없는 칸: %s/%s" % (node_id, deviation_id))


def set_status(results, node_id, deviation_id, entry_id, status, at=None):
    """승인(approved)·기각(rejected)·되돌림(revised). proposed로는 바꿀 수 없다(재실행이 덮어쓰게 되므로)."""
    if status not in HUMAN_STATUSES:
        raise ValueError("사람이 정할 수 있는 상태가 아님: %r" % status)
    out = copy.deepcopy(results)
    e = _entry(out, node_id, deviation_id, entry_id)
    old, e["status"] = e.get("status"), status
    e.setdefault("history", []).append({"at": at or now_utc(), "op": "status", "from": old, "to": status})
    return out


def edit_entry(results, node_id, deviation_id, entry_id, fields, at=None):
    """항목 내용을 고친다. 상태는 revised가 된다(승인한 항목을 고치면 다시 승인해야 함).
    severity·frequency를 고치면 risk를 다시 계산한다. history에는 바뀐 필드의 이전 값을 남긴다."""
    unknown = sorted(set(fields) - set(EDITABLE_FIELDS))
    if unknown:
        raise ValueError("고칠 수 없는 필드: %s" % ", ".join(unknown))
    for name, allowed in (("severity", SEVERITIES), ("frequency", FREQUENCIES)):
        v = fields.get(name)
        if v is not None and (type(v) is not int or v not in allowed):
            raise ValueError("%s 값 %r(%d~%d 또는 null)" % (name, v, allowed[0], allowed[-1]))
    if "safeguards" in fields and not (isinstance(fields["safeguards"], list)
                                       and all(isinstance(x, str) for x in fields["safeguards"])):
        raise ValueError("safeguards는 문자열 목록이어야 함")
    out = copy.deepcopy(results)
    e = _entry(out, node_id, deviation_id, entry_id)
    before = {k: copy.deepcopy(e.get(k)) for k in sorted(fields) if e.get(k) != fields[k]}
    e.update(copy.deepcopy(fields))
    e["risk"] = risk_of(e.get("severity"), e.get("frequency"))
    old, e["status"] = e.get("status"), "revised"
    e.setdefault("history", []).append({"at": at or now_utc(), "op": "edit", "from": old, "before": before})
    return out


# ---------------------------------------------------------------- 저장

def store_path(project_id, graph_id):
    return paths.work_path("데이터", "분석결과", paths.safe_name(project_id or UNREGISTERED_PROJECT),
                           paths.safe_name(graph_id) + ".json")


def _readable_path(project_id, graph_id):
    """저장 경로. 없고 project_id가 없으면 이 규칙 이전 폴더(no-project)의 저장본을 그대로 읽는다(옮기지 않음)."""
    path = store_path(project_id, graph_id)
    legacy = paths.work_path("데이터", "분석결과", LEGACY_PROJECT_DIR, paths.safe_name(graph_id) + ".json")
    return legacy if not project_id and not os.path.isfile(path) and os.path.isfile(legacy) else path


def save(results, project_id):
    """임시 파일에 쓴 뒤 os.replace로 교체한다. 쓴 경로를 돌려준다."""
    path = store_path(project_id, results["graph_id"])
    write_json_atomic(path, results)
    return path


def load(node_set):
    """node_set 도면의 저장본. 없으면 None. 다른 종류·다른 도면의 파일이면 ValueError. 판 비교는 is_stale로 한다."""
    path = _readable_path(node_set.get("project_id"), node_set["graph_id"])
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError("분석 결과 파일이 아님: %s" % path)
    if doc.get("graph_id") != node_set["graph_id"]:
        raise ValueError("다른 도면의 분석 결과: %s (%s)" % (path, doc.get("graph_id")))
    return doc


def is_stale(results, node_set):
    """결과를 만든 검토구간 확정본(graph_version, confirmed_at)과 현재 확정본이 다르면 True."""
    return results.get("study_nodes_ref") != {"graph_version": node_set.get("graph_version"),
                                              "confirmed_at": node_set.get("confirmed_at")}
