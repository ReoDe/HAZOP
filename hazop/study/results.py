"""⑤ 분석 결과 셸: 검토구간 × 편차 행렬. 4단계에서 AI가 칸을 채운다. 근거: 3단계 명세 §B results.py.

편차 목록은 데이터/이탈후보/kosha-p86-2017-deviation-chart.json의 items(파라미터 × 가이드워드)에서 만든다.
편집 연산(set_status·edit_entry·set_ie_hint)은 순수 함수다. 입력을 바꾸지 않고 새 dict를 돌려주며 항목 history에 한 줄 덧붙인다.

초기사건 인계용 항목 필드(기획서/초기사건-출력설계.md §5.1, E1·E2·E4). 모두 선택이며 없으면 옛 항목처럼 읽는다.
- cause_kind: CAUSE_KINDS 키. 없으면 '미확인'.
- consequence_basis: "unmitigated"(결과를 보호수단 실패 가정으로 쓴 것) 또는 없음('비완화 여부 미확인').
- ie_hint: 원인 단위 초기사건 판정 {candidate, disturbs, challenges, safety_functions, category, reason, origin, status}.
  category는 일반 범주 기준표(IE_CATEGORY_TABLE) 코드 또는 null(미분류). 항목 승인과 따로 확정하므로 edit_entry가 아니라
  set_ie_hint로 고친다(항목 상태를 바꾸지 않음).
"""

import copy
import functools
import json
import os

from hazop import paths, store_io
from hazop.analysis.risk import FREQUENCIES, MATRIX_P86, SEVERITIES
from hazop.graph.project import LEGACY_PROJECT_DIR, UNREGISTERED_PROJECT
from hazop.study import refs

SCHEMA_VERSION = "0.1"
KIND = "hazop_study_results"
DEVIATION_CHART = "kosha-p86-2017-deviation-chart.json"  # 이탈후보 폴더
CELL_STATES = ("not_analyzed", "analyzed", "excluded")
ENTRY_ORIGINS = ("ai_draft", "human")
ENTRY_STATUSES = ("proposed", "revised", "approved", "rejected")
HUMAN_STATUSES = ("revised", "approved", "rejected")  # proposed는 AI만 쓴다(재실행이 덮어쓰는 상태)
AI_RUN_STATUSES = ("ok", "failed")
EDITABLE_FIELDS = ("cause", "consequence", "safeguards", "recommendation", "severity", "frequency",
                   "cause_refs", "consequence_refs", "expectation_refs",  # 참조 필드: hazop.study.refs
                   "cause_kind", "consequence_basis")
CAUSE_KINDS = {"equipment": "기기 고장", "human": "인적 오류", "support": "지원계통 상실", "external": "외부 요인",
               "other": "기타"}
UNKNOWN_LABEL = "미확인"
CONSEQUENCE_BASES = {"unmitigated": "비완화"}
BASIS_UNKNOWN_LABEL = "비완화 여부 미확인"
IE_CANDIDATES = {"yes": "후보", "no": "제외", "undecided": "보류"}
IE_ANSWERS = {"yes": "예", "no": "아니오", "unknown": "모름"}
IE_STATUSES = {"draft": "초안", "confirmed": "확정"}
IE_KEYS = ("candidate", "disturbs", "challenges", "safety_functions", "category", "reason", "origin", "status")
IE_CATEGORY_TABLE = "lwr-generic-ie-categories.json"  # 기준표 폴더
UNCLASSIFIED_LABEL = "미분류"
# 품질 경고 종류 {키: (이름, 근거)}. 근거는 PSAM14 PHA-to-PRA 논문 쪽수(초기사건 출력설계 §3.2 시트 8)
QUALITY_KINDS = {"mitigated_consequence": ("완화 결과로 적힘", "PSAM14 382·383"),
                 "actuation_unknown": ("작동 방식 미확인", "PSAM14 383")}
# 보호수단이 작동해 결과를 막았다고 쓴 표현(초기사건 출력설계 §5.2 예시에서 넓힘). 경고만 하고 막지 않는다 [추론]
MITIGATED_PHRASES = ("영향 없음", "영향이 없", "영향은 없", "문제 없음", "문제가 없", "경보 후 회복", "회복된다", "회복됨",
                     "정상 복귀", "정상으로 복귀", "정상 상태로 돌아", "작동하여", "작동해 ", "작동하므로", "방지된다",
                     "방지됨", "막아 준다", "막는다")


def load_deviations(path=None):
    """[{deviation_id, item_id, parameter, guideword, label}] 파일 순서대로. deviation_id는 D01부터."""
    with open(path or paths.folder("deviations", DEVIATION_CHART), encoding="utf-8") as fh:
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


@functools.lru_cache(maxsize=None)
def _ie_category_table(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ie_category_table(path=None):
    """일반 범주 기준표 문서 {table_id, title, basis, categories} 사본."""
    return copy.deepcopy(_ie_category_table(path or paths.folder("risk-criteria", IE_CATEGORY_TABLE)))


def ie_categories(path=None):
    """일반 범주 기준표 [{code, nureg_6928, name_en, name_ko}] 파일 순서대로."""
    return ie_category_table(path)["categories"]


def ie_category_label(code, categories=None):
    """'LOCCW 기기냉각수 완전 상실'. null은 '미분류', 기준표에 없는 코드는 코드 그대로."""
    if code is None:
        return UNCLASSIFIED_LABEL
    c = next((c for c in categories or ie_categories() if c["code"] == code), None)
    return "%s %s" % (code, c["name_ko"]) if c else code


def ie_hint_problems(hint, codes=None):
    """ie_hint 형식 문제 목록. codes(기준표 코드 집합)를 주면 category가 그 안에 있는지도 본다."""
    if not isinstance(hint, dict):
        return ["ie_hint는 객체여야 함"]
    out = []
    unknown = sorted(set(hint) - set(IE_KEYS))
    if unknown:
        out.append("ie_hint: 모르는 키 %s" % ", ".join(unknown))
    for k, allowed in (("candidate", IE_CANDIDATES), ("disturbs", IE_ANSWERS), ("challenges", IE_ANSWERS),
                       ("origin", dict.fromkeys(ENTRY_ORIGINS)), ("status", IE_STATUSES)):
        if hint.get(k) not in allowed:
            out.append("ie_hint.%s 값 %r(%s)" % (k, hint.get(k), "/".join(allowed)))
    sf = hint.get("safety_functions", [])
    if not isinstance(sf, list) or not all(isinstance(x, str) for x in sf):
        out.append("ie_hint.safety_functions는 문자열 목록이어야 함")
    if not isinstance(hint.get("reason", ""), str):
        out.append("ie_hint.reason은 문자열이어야 함")
    cat = hint.get("category")
    if cat is not None and (not isinstance(cat, str) or (codes is not None and cat not in codes)):
        out.append("ie_hint.category 값 %r(기준표 코드 또는 null)" % (cat,))
    return out


def entry_problems(entry, codes=None):
    """초기사건 인계용 필드(cause_kind·consequence_basis·ie_hint) 형식 문제. 필드가 없으면 검사하지 않는다."""
    out = []
    if entry.get("cause_kind") is not None and entry["cause_kind"] not in CAUSE_KINDS:
        out.append("cause_kind 값 %r(%s 또는 null)" % (entry["cause_kind"], "/".join(CAUSE_KINDS)))
    if entry.get("consequence_basis") is not None and entry["consequence_basis"] not in CONSEQUENCE_BASES:
        out.append("consequence_basis 값 %r(unmitigated 또는 null)" % (entry["consequence_basis"],))
    if entry.get("ie_hint") is not None:
        out += ie_hint_problems(entry["ie_hint"], codes)
    return out


def cause_kind_label(entry):
    return CAUSE_KINDS.get(entry.get("cause_kind"), UNKNOWN_LABEL)


def basis_label(entry):
    return CONSEQUENCE_BASES.get(entry.get("consequence_basis"), BASIS_UNKNOWN_LABEL)


def mitigated_phrase(text):
    """결과 문장에서 보호수단이 작동한 뒤의 결과로 보이는 표현(없으면 None). '오작동하여'는 고장 표현이라 보지 않는다."""
    text = (text or "").replace("오작동", "")
    return next((p for p in MITIGATED_PHRASES if p in text), None)


def quality_warnings(entry):
    """초기사건 인계 품질 경고 [(종류 키, 내용)] (초기사건 출력설계 §3.2 시트 8 중 P1 범위, 종류는 QUALITY_KINDS).
    결과가 완화 결과로 적혔는지는 표현으로만 짐작하고, 보호수단 작동 방식이 미확인인지 본다. 항목을 막지 않는다."""
    out = []
    hit = mitigated_phrase(entry.get("consequence"))
    if hit:
        out.append(("mitigated_consequence", "결과에 '%s' 같은 표현이 있어 보호수단이 작동한 뒤의 결과일 수 있습니다. "
                    "보호수단이 모두 실패했다고 보고 썼는지 확인하세요" % hit.strip()))
    unknown = [s["text"] for s in refs.safeguard_items(entry) if s["actuation"] == "unknown"]
    if unknown:
        out.append(("actuation_unknown", "보호수단 %d개(%s)가 자동·운전원·자체작동 가운데 무엇인지 정해지지 않았습니다"
                    % (len(unknown), ", ".join(t or "-" for t in unknown[:3]) + (" 외" if len(unknown) > 3 else ""))))
    return out


def quality_line(kind, text):
    """화면·⑤ Excel에 한 줄로 쓰는 품질 경고: '작동 방식 미확인: 보호수단 1개(...)...'."""
    return "%s: %s" % (QUALITY_KINDS[kind][0], text)


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
        if not cell["entries"]:  # 대부분의 칸(분석 전)은 셀 것이 없다
            out.setdefault(cell["node_id"], {})[cell["deviation_id"]] = {
                "state": cell["state"], "scenarios": 0, "max_risk": None, "unreviewed": 0}
            continue
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
            problems += ["%s/%s: %s" % (where, eid, p) for p in refs.problems(e) + entry_problems(e)]
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
    e.setdefault("history", []).append(store_io.history_row("status", {"from": old, "to": status}, at))
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
    if "safeguards" in fields and not isinstance(fields["safeguards"], list):
        raise ValueError("safeguards는 목록이어야 함")
    bad = refs.problems(fields) + entry_problems(fields)
    if bad:
        raise ValueError("; ".join(bad))
    out = copy.deepcopy(results)
    e = _entry(out, node_id, deviation_id, entry_id)
    before = {k: copy.deepcopy(e.get(k)) for k in sorted(fields) if e.get(k) != fields[k]}
    e.update(copy.deepcopy(fields))
    e["risk"] = risk_of(e.get("severity"), e.get("frequency"))
    old, e["status"] = e.get("status"), "revised"
    e.setdefault("history", []).append(store_io.history_row("edit", {"from": old, "before": before}, at))
    return out


def set_ie_hint(results, node_id, deviation_id, entry_id, hint, at=None):
    """사람이 초기사건 판정을 정한다. origin human·status confirmed로 저장하고 승인·수정·기각 상태는 그대로 둔다.
    제안(proposed) 항목만 수정(revised)이 된다. 제안 항목은 AI 재실행이 통째로 바꾸므로 사람이 정한 판정이 사라지기 때문이다.
    category는 기준표 코드 또는 None. history에는 op ie_hint, 판정 뒤 항목 상태, 이전 판정을 남긴다."""
    new = {"candidate": hint.get("candidate"), "disturbs": hint.get("disturbs", "unknown"),
           "challenges": hint.get("challenges", "unknown"),
           "safety_functions": [x.strip() for x in hint.get("safety_functions") or [] if isinstance(x, str) and x.strip()],
           "category": hint.get("category"), "reason": (hint.get("reason") or "").strip(),
           "origin": "human", "status": "confirmed"}
    bad = ie_hint_problems(new, {c["code"] for c in ie_categories()})
    if bad:
        raise ValueError("; ".join(bad))
    out = copy.deepcopy(results)
    e = _entry(out, node_id, deviation_id, entry_id)
    before = copy.deepcopy(e.get("ie_hint"))
    e["ie_hint"] = new
    if e.get("status") == "proposed":
        e["status"] = "revised"
    e.setdefault("history", []).append(store_io.history_row("ie_hint", {"status": e.get("status"), "before": before}, at))
    return out


# ---------------------------------------------------------------- 저장

def store_path(project_id, graph_id):
    return paths.folder("analysis-results", paths.safe_name(project_id or UNREGISTERED_PROJECT),
                           paths.safe_name(graph_id) + ".json")


def test_store_path(project_id, graph_id):
    """고정 응답(시험) 결과 파일. 시험 값이 실제 검토 기록의 AI 초안을 덮지 않게 따로 둔다(D5)."""
    return paths.fixed_test_results_path(project_id or UNREGISTERED_PROJECT, graph_id)


def _readable_path(project_id, graph_id):
    """저장 경로. 없고 project_id가 없으면 이 규칙 이전 폴더(no-project)의 저장본을 그대로 읽는다(옮기지 않음)."""
    path = store_path(project_id, graph_id)
    legacy = paths.folder("analysis-results", LEGACY_PROJECT_DIR, paths.safe_name(graph_id) + ".json")
    return legacy if not project_id and not os.path.isfile(path) and os.path.isfile(legacy) else path


def save(results, project_id, expect=store_io.ANY):
    """쓴 경로를 돌려준다. expect는 save_fp와 같다. 읽어서 고친 결과를 쓸 때는 expect를 꼭 넘긴다
    (넘기지 않는 것은 방금 만든 결과를 처음 쓰는 검사·시험뿐이다)."""
    return write(store_path(project_id, results["graph_id"]), results, expect)


def save_fp(results, project_id, expect):
    """(쓴 경로, 새 지문). expect(load_fp의 지문, 없던 파일이면 None)와 지금 파일이 다르면 store_io.Conflict."""
    path = store_path(project_id, results["graph_id"])
    return path, store_io.write_json(path, results, expect)


def written_fp(results):
    """results를 쓴 파일의 지문(직렬화가 결정적이라 다시 읽지 않고 안다)."""
    return store_io.fingerprint_of(store_io.dump_bytes(results))


def write(path, results, expect=store_io.ANY):
    """expect(read_fp의 지문)를 주면 읽은 뒤 바뀐 파일은 쓰지 않고 store_io.Conflict를 낸다."""
    store_io.write_json(path, results, expect)
    return path


def read(path):
    """path의 결과 문서. 없으면 None, 다른 종류면 ValueError."""
    return read_fp(path)[0]


def read_fp(path):
    """(결과 문서, 읽은 바이트의 지문). 없으면 (None, None)."""
    data, fp = store_io.read_bytes(path)
    if data is None:
        return None, None
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError("분석 결과 파일이 아님: %s" % path)
    return doc, fp


def load(node_set):
    """node_set 도면의 저장본. 없으면 None. 다른 종류·다른 도면의 파일이면 ValueError. 판 비교는 is_stale로 한다.
    집합이 판 이전된 뒤 옛 판으로 저장된 결과는 읽을 때 같은 규칙으로 이전한다(파일은 nodes.load가 이전할 때만 씀)."""
    return load_fp(node_set)[0]


def load_fp(node_set):
    """(load와 같은 문서, save_fp의 expect로 쓸 지문). 없으면 (None, None).
    옛 자리(no-project)에서 읽었으면 저장할 자리에는 아직 파일이 없으므로 지문은 None이다."""
    from hazop.study import migrate
    path = _readable_path(node_set.get("project_id"), node_set["graph_id"])
    doc, fp = read_fp(path)
    if doc is None:
        return None, None
    if doc.get("graph_id") != node_set["graph_id"]:
        raise ValueError("다른 도면의 분석 결과: %s (%s)" % (path, doc.get("graph_id")))
    same_place = path == store_path(node_set.get("project_id"), node_set["graph_id"])
    return migrate.migrate_results(doc, node_set)[0], fp if same_place else None


def is_stale(results, node_set):
    """결과를 만든 검토구간 확정본(graph_version, confirmed_at)과 현재 확정본이 다르면 True."""
    return results.get("study_nodes_ref") != {"graph_version": node_set.get("graph_version"),
                                              "confirmed_at": node_set.get("confirmed_at")}
