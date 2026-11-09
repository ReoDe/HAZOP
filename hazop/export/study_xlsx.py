"""⑤ 분석 결과(구간 × 편차, hazop.study.results) Excel 내보내기. 실무 HAZOP 워크시트(IEC 61882 용어) 형식.

build_workbook(results, node_set, pg, deviations, scope, node_ids, reviewer, intents, now) → openpyxl Workbook
- 시트: 표지·요약 / 구간 목록 / 워크시트 / 권고 목록
- 워크시트 행 하나 = 시나리오(항목) 하나. 항목 없는 분석 칸('해당 없음'·'시나리오 없음')·AI 실패 칸·제외 칸도
  한 행으로 남기고 상태 열에서 구분한다. 분석 전 칸은 행으로 쓰지 않고 요약에 칸 수만 적는다.
- 범위(SCOPES): 전체 / 승인만(승인 항목만, 칸 표시 행 없음) / 선택한 구간만.
- 다른 도면 태그는 'RC-P01(101)'처럼 짧은 도면번호를 붙인다(span.label_tags). 여러 도면에 걸친 구간은 기준 도면이
  하나가 아니므로 모든 태그에 붙인다.
- 위험도는 KOSHA P-86 〈표5〉 값(항목의 risk)과 구분(수용·조건부 수용·불허)을 글자로 함께 쓰고 색은 보조로만 쓴다.
- 모든 문자열은 수식으로 실행되지 않게 문자열 셀로 쓰고, 드라이브 경로·API 키처럼 보이는 글자는 가린다.
- 그래프 참조(원인 위치·영향 대상·보호수단 역할·구현 대상·관련 잠재 후보, hazop.study.refs)는 '그래프 참조' 열에
  "보호수단: RC-PSV101 (SNP-M-102) · 완화"처럼 적는다. 잠재 후보는 근거가 아니라 확인할 단서라 줄 앞에 "단서:"를 붙인다. 참조가 없는 옛 항목은 빈칸이다.
- 초기사건 인계 열(기획서/초기사건-출력설계.md §5.3, P1): 원인 유형, 결과 기준(표시가 없으면 '비완화 여부 미확인'),
  초기사건 판정, 일반 범주, 판정 작성(AI 초안·사람 확정). 보호수단 열의 줄마다 작동 방식을 "[자동]"처럼 앞에 붙인다.
  품질 경고(완화 결과로 적힘·작동 방식 미확인)는 근거 경고 열에 함께 적는다.
- AI 초안의 출처(디자인/AI연결-화면설계.md §8.2, D3): 표지에 'AI 초안 생성'(모델·연결 방식별 칸 수)과
  'AI 사용 요금(API 키 호출분)', 워크시트 오른쪽 끝에 'AI 초안 생성' 열(AI 항목만, 사람이 더한 항목은 빈칸).
  고정 응답(시험) 결과에서 내보내면 표지 고지 아래 빨간 경고 줄을 넣고 파일 이름 끝에 '-시험'을 붙인다.
"""

import datetime
import os
import re
import tempfile

from hazop.app.conn_view import api_cost, drafted_cells, provenance
from hazop.app.tokens import COLORS, risk_band
from hazop.study import refs as srefs
from hazop.study import results as res
from hazop.study import span

SCOPES = {"all": "전체", "approved": "승인만", "nodes": "선택한 구간만"}
SHEETS = ("표지·요약", "구간 목록", "워크시트", "권고 목록")
STATUS_LABELS = {"proposed": "제안", "revised": "수정", "approved": "승인", "rejected": "기각"}
BAND_LABELS = {"ok": "수용", "cond": "조건부 수용", "deny": "불허"}
FIELD_LABELS = {"cause": "원인", "consequence": "결과", "safeguards": "보호수단", "recommendation": "권고",
                "severity": "강도", "frequency": "빈도", "cause_refs": "원인 위치", "consequence_refs": "영향 대상",
                "expectation_refs": "잠재 후보", "cause_kind": "원인 유형", "consequence_basis": "결과 기준"}
IE_ORIGIN_LABELS = {"ai_draft": "AI 초안", "human": "사람 확정"}
FLAG_LABELS = (("scope_changed", "범위 바뀜 · 다시 확인"), ("source_stale", "옛 결과 · 다시 확인"))
NOTICE = "AI 결과는 초안이며 사람이 승인한 항목만 확정입니다. 상태가 '승인'이 아닌 행은 검토 전 초안입니다."
TEST_NOTICE = "시험용 고정 응답으로 채운 결과입니다. 실제 검토 결과로 쓰지 마세요."

# 칸 표시 행(항목이 아닌 행)의 상태 문구
CELL_ROW_LABELS = {"not_applicable": "해당 없음(AI 판단)", "no_scenario": "시나리오 없음(AI)",
                   "failed": "실패(AI 실행)", "excluded": "제외"}

# (키, 머리글, 열 너비)
WORKSHEET_COLUMNS = (
    ("node", "구간", 22), ("drawings", "도면 번호", 18), ("parameter", "변수", 8), ("guideword", "가이드워드", 9),
    ("deviation", "편차", 14), ("cause", "원인", 34), ("cause_kind", "원인 유형", 11),
    ("consequence", "결과(보호수단 실패 가정)", 34), ("consequence_basis", "결과 기준", 12), ("safeguards", "보호수단", 30),
    ("severity", "강도", 6), ("frequency", "빈도", 6), ("risk", "위험도", 13), ("recommendation", "권고", 32),
    ("basis", "AI 근거(KG 경로·출처 문서)", 34), ("refs", "그래프 참조", 34),
    ("warnings", "근거 경고", 22), ("status", "상태", 14),
    ("ie_judgement", "초기사건 판정", 28), ("ie_category", "일반 범주", 18), ("ie_origin", "판정 작성", 11),
    ("history", "수정 이력 요약", 28), ("ai_origin", "AI 초안 생성", 22),
)
NODE_COLUMNS = (("구간 ID", 9), ("표시 이름", 30), ("도면 범위", 14), ("경계 시작", 20), ("경계 끝", 20),
                ("설계의도", 40), ("구성요소", 50))
RECOMMENDATION_COLUMNS = (("번호", 6), ("구간", 22), ("편차", 16), ("권고", 50), ("위험도", 13), ("상태", 12),
                          ("담당", 12), ("기한", 12))

_SECRET = re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{8,}"
                     r"|(?<![A-Za-z])[A-Za-z]:[\\/](?:[^\\/\n]*[\\/])*[^\s\\/,;)]*"
                     r"|\\\\(?:[^\\/\n]*[\\/])*[^\s\\/,;)]*")
_FORMULA_PREFIX = ("=", "+", "-", "@")
_KST = datetime.timezone(datetime.timedelta(hours=9), "KST")
_HEAD_FILL = "E2EDFB"


def scrub(text):
    """내보낸 파일에 남기면 안 되는 글자(API 키 모양, 드라이브·네트워크 경로)를 가린다."""
    return _SECRET.sub("[가림]", text)


def kst(utc_iso, fmt="%Y-%m-%d %H:%M"):
    t = datetime.datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(_KST).strftime(fmt)


def risk_text(risk):
    band = risk_band(risk)
    return "%d %s" % (risk, BAND_LABELS[band]) if band else ""


def default_filename(project_id, now, test=False):
    """저장 대화상자 기본 이름: HAZOP-<프로젝트>-<KST 날짜시각>[-시험].xlsx."""
    return "HAZOP-%s-%s%s.xlsx" % (re.sub(r'[\\/:*?"<>|\s]+', "_", project_id or "프로젝트"), kst(now, "%Y%m%d-%H%M"),
                                   "-시험" if test else "")


# ---------------------------------------------------------------- 행 모델

def entity_labels(pg):
    """{entity_id: 태그(짧은 도면번호)}. 태그 없는 요소는 넣지 않는다(근거 경로는 ID로 남김)."""
    sheets = pg.get("sheets") or []  # 도면 그래프 하나에는 sheets가 없다
    short = span.short_numbers(s["drawing_number"] for s in sheets)[1]
    dn = {s["graph_id"]: s["drawing_number"] for s in sheets}
    out = {}
    for n in pg["nodes"]:
        if n.get("tag"):
            d = dn.get(n.get("sheet"))
            out[n["entity_id"]] = "%s(%s)" % (n["tag"], short.get(d, d)) if d else n["tag"]
    return out


def _basis_text(entry, labels):
    basis = entry.get("ai_basis") or {}
    lines = ["KG: " + " → ".join(labels.get(i, i) for i in path) for path in basis.get("kg_paths") or [] if path]
    for s in basis.get("sources") or []:
        lines.append("문서: %s%s" % (s.get("doc") or "-", " (%s)" % s["where"] if s.get("where") else ""))
    return "\n".join(lines)


def _refs_text(entry, idx, drawing_numbers, expectations):
    return "\n".join("단서: " + t if k == "expectation" else t
                     for k, t in srefs.lines(entry, idx, drawing_numbers, None, expectations))


def _warnings_text(entry):
    items = list((entry.get("ai_basis") or {}).get("warnings") or [])
    items += [res.quality_line(k, t) for k, t in res.quality_warnings(entry)]
    items += [label for key, label in FLAG_LABELS if entry.get(key)]
    return "\n".join("⚠ %s" % w for w in items)


def _safeguards_text(entry, tagged):
    return "\n".join("[%s] %s" % (srefs.ACTUATIONS[s["actuation"]], tagged(s["text"])) for s in srefs.safeguard_items(entry))


def ie_columns(entry):
    """{ie_judgement, ie_category, ie_origin}. 판정이 없으면 '미판정'과 빈칸."""
    h = entry.get("ie_hint")
    if not isinstance(h, dict):
        return {"ie_judgement": "미판정", "ie_category": "", "ie_origin": ""}
    lines = ["%s · 교란 %s · 도전 %s" % (res.IE_CANDIDATES.get(h.get("candidate"), "보류"),
                                       res.IE_ANSWERS.get(h.get("disturbs"), "모름"),
                                       res.IE_ANSWERS.get(h.get("challenges"), "모름"))]
    if h.get("safety_functions"):
        lines.append("안전기능: " + ", ".join(h["safety_functions"]))
    if h.get("reason"):
        lines.append("이유: " + h["reason"])
    return {"ie_judgement": "\n".join(lines), "ie_category": res.ie_category_label(h.get("category")),
            "ie_origin": IE_ORIGIN_LABELS.get(h.get("origin"), "")}


def _history_text(entry):
    out = []
    for h in entry.get("history") or []:
        at = kst(h["at"], "%m-%d %H:%M") if h.get("at") else ""
        if h.get("op") == "status":
            out.append("%s %s→%s" % (at, STATUS_LABELS.get(h.get("from"), h.get("from")),
                                     STATUS_LABELS.get(h.get("to"), h.get("to"))))
        elif h.get("op") == "edit":
            fields = "·".join(FIELD_LABELS.get(k, k) for k in h.get("before") or {})
            out.append("%s 수정(%s)" % (at, fields or "변경 없음"))
        elif h.get("op") == "ie_hint":
            out.append("%s 초기사건 판정" % at)
    return "\n".join(out)


def _status_text(entry):
    """기각은 사람이 내린 판정이라 'AI 초안'을 붙이지 않는다(제안·수정인 AI 항목만 초안)."""
    text = STATUS_LABELS.get(entry.get("status"), entry.get("status") or "")
    return text + " · AI 초안" if res.is_ai_draft(entry) and entry.get("status") != "rejected" else text


def _cell_kind(cell):
    """칸 표시 행 종류 목록. 항목 행과 별도로 쓴다."""
    run = cell.get("ai_run") or {}
    kinds = []
    if run.get("status") == "failed":
        kinds.append("failed")
    if cell["state"] == "excluded":
        kinds.append("excluded")
    elif cell["state"] == "analyzed" and not cell["entries"] and run.get("status") != "failed":
        kinds.append("not_applicable" if run.get("applicable") is False else "no_scenario")
    return kinds


def worksheet_rows(results, view, pg, deviations, scope="all", node_ids=None, expectations=None):
    """워크시트 행 [{키: 값, "kind": "entry"|칸 표시 종류, "risk_value", "status_key"}] (구간 순서 × 편차 순서).
    expectations {잠재 후보 ID: 항목}이 있으면 관련 잠재 후보를 규칙·대상·상태로 적는다(없으면 ID)."""
    if scope not in SCOPES:
        raise ValueError("모르는 범위: %r" % scope)
    nodes = {n["node_id"]: n for n in view["nodes"]}
    order = [n["node_id"] for n in view["nodes"] if scope != "nodes" or n["node_id"] in (node_ids or ())]
    devs = {d["deviation_id"]: d for d in deviations}
    dev_rank = {d["deviation_id"]: i for i, d in enumerate(deviations)}
    tag_drawing = span.tag_drawings(pg)
    labels = entity_labels(pg)
    short = view.get("drawing_short") or {}
    idx = srefs.index(pg)
    dn = {s["graph_id"]: s["drawing_number"] for s in pg["sheets"]}
    cells = {}
    for c in results["cells"]:
        cells.setdefault(c["node_id"], []).append(c)
    rows = []
    for nid in order:
        node = nodes[nid]
        home = node["drawings"][0] if len(node.get("drawings") or []) == 1 else None

        def tagged(text):
            return span.label_tags(text, tag_drawing, home, short) if text else text
        for cell in sorted(cells.get(nid, []), key=lambda c: dev_rank.get(c["deviation_id"], 10 ** 6)):
            run = cell.get("ai_run") or {}
            d = devs.get(cell["deviation_id"]) or {"label": cell["deviation_id"], "parameter": "", "guideword": ""}
            base = {"node": node.get("display_name") or nid, "node_id": nid, "drawings": span.drawing_column(node),
                    "parameter": d["parameter"], "guideword": d["guideword"], "deviation": d["label"],
                    "deviation_id": cell["deviation_id"]}
            for e in cell["entries"]:
                if scope == "approved" and e.get("status") != "approved":
                    continue
                rows.append(dict(base, kind="entry", status_key=e.get("status"), risk_value=e.get("risk"),
                                 cause=tagged(e.get("cause")), cause_kind=res.cause_kind_label(e),
                                 consequence=tagged(e.get("consequence")), consequence_basis=res.basis_label(e),
                                 safeguards=_safeguards_text(e, tagged), **ie_columns(e),
                                 severity=e.get("severity"), frequency=e.get("frequency"),
                                 risk=risk_text(e.get("risk")), recommendation=tagged(e.get("recommendation")),
                                 basis=_basis_text(e, labels), refs=_refs_text(e, idx, dn, expectations),
                                 warnings=_warnings_text(e),
                                 status=_status_text(e), history=_history_text(e),
                                 ai_origin=provenance(run, excel=True) if e.get("origin") == "ai_draft" else ""))
            if scope == "approved":
                continue
            for kind in _cell_kind(cell):
                extra = ({"warnings": "⚠ %s" % run["error"]} if kind == "failed" and run.get("error") else
                         {"basis": "AI 메모: %s" % run["note"]} if kind != "failed" and run.get("note") else {})
                rows.append(dict(base, kind=kind, status_key=kind, risk_value=None, status=CELL_ROW_LABELS[kind],
                                 **extra))
    return rows


def counts(results, node_ids=None):
    """요약 수치. node_ids를 주면 그 구간 칸만 센다. scenarios는 모든 상태의 항목 수."""
    keep = (lambda c: True) if node_ids is None else (lambda c: c["node_id"] in node_ids)
    cells = [c for c in results["cells"] if keep(c)]
    entries = [e for c in cells for e in c["entries"]]
    by_status = {s: sum(e.get("status") == s for e in entries) for s in res.ENTRY_STATUSES}
    unreviewed = sum(e.get("status") == "proposed" or (res.is_ai_draft(e) and e.get("status") != "rejected")
                     for e in entries)
    return {"nodes": len({c["node_id"] for c in cells}), "deviations": len({c["deviation_id"] for c in cells}),
            "scenarios": len(entries), "by_status": by_status, "unreviewed": unreviewed,
            "failed_cells": sum((c.get("ai_run") or {}).get("status") == "failed" for c in cells),
            "not_analyzed_cells": sum(c["state"] == "not_analyzed" for c in cells)}


# ---------------------------------------------------------------- 쓰기

def put(ws, row, col, value, bold=False):
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Alignment, Font
    cell = ws.cell(row=row, column=col)
    if isinstance(value, str):
        value = scrub(ILLEGAL_CHARACTERS_RE.sub("", value))
    cell.value = value if value != "" else None
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIX):
        cell.data_type = "s"
        cell.quotePrefix = True
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    if bold:
        cell.font = Font(bold=True)
    return cell


def header(ws, columns):
    from openpyxl.styles import PatternFill
    from openpyxl.utils import get_column_letter
    for i, (title, width) in enumerate(columns, 1):
        c = put(ws, 1, i, title, bold=True)
        c.fill = PatternFill("solid", fgColor=_HEAD_FILL)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    ws.print_title_rows = "1:1"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def autofilter(ws, ncols, nrows):
    from openpyxl.utils import get_column_letter
    ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(ncols), max(1, nrows + 1))


def _paint_risk(cell, risk):
    from openpyxl.styles import Font, PatternFill
    band = risk_band(risk)
    if band:
        cell.fill = PatternFill("solid", fgColor=COLORS["risk-%s-bg" % band].lstrip("#").upper())
        cell.font = Font(bold=True, color=COLORS["risk-%s-ink" % band].lstrip("#").upper())


def _summary_sheet(ws, results, node_set, view, scope, node_ids, reviewer, now, n_rows, test=False):
    from openpyxl.styles import Font
    # 표지 수치는 내보낸 구간만 센다(⑤가 스크리닝 제외 구간을 뺀 집합을 넘기면 그 칸도 빠지게)
    keep = set(node_ids) if scope == "nodes" else {n["node_id"] for n in node_set["nodes"]}
    c = counts(results, keep)
    cells = [x for x in results["cells"] if keep is None or x["node_id"] in keep]
    ref = results.get("study_nodes_ref") or {}
    s = c["by_status"]
    lines = [
        ("HAZOP 분석 결과 (⑤ 구간 × 편차)", None),
        ("고지", NOTICE),
    ] + ([("시험 결과", TEST_NOTICE)] if test else []) + [
        ("프로젝트", node_set.get("project_id") or "-"),
        ("도면 목록", ", ".join(view.get("drawing_numbers") or [])),
        ("그래프 판", ref.get("graph_version") or "-"),
        ("검토구간 확정 시각", kst(ref["confirmed_at"]) + " KST" if ref.get("confirmed_at") else "-"),
        ("내보낸 시각", kst(now) + " KST"),
        ("검토자", reviewer or ""),
        ("내보낸 범위", SCOPES[scope] + (" (%s)" % ", ".join(node_ids) if scope == "nodes" else "")),
        ("구간 수", c["nodes"]), ("편차 수", c["deviations"]), ("시나리오 수", c["scenarios"]),
        ("상태별: 제안", s["proposed"]), ("상태별: 수정", s["revised"]), ("상태별: 승인", s["approved"]),
        ("상태별: 기각", s["rejected"]), ("미검토 시나리오", c["unreviewed"]), ("실패 칸", c["failed_cells"]),
        ("분석 전 칸(워크시트에 행 없음)", c["not_analyzed_cells"]), ("워크시트 행 수", n_rows),
        ("AI 초안 생성", drafted_cells(cells)),
        ("AI 사용 요금(API 키 호출분)", "$%.2f" % api_cost(results.get("ai_log"))),
        ("위험도", "KOSHA P-86 〈표5〉 강도 × 빈도 → 1–5. 구분 1·2 수용 · 3·4 조건부 수용 · 5 불허는 〈표9〉 비고를 "
              "허용 구분으로 해석한 것 [추론](HAZOP기법지침 §6). 글자와 색 함께 표기"),
        ("용어", "구간 = node, 편차 = deviation, 가이드워드 = guide word, 원인 = cause, 결과 = consequence, "
               "보호수단 = safeguard, 권고 = recommendation (IEC 61882)"),
    ]
    for r, (k, v) in enumerate(lines, 1):
        put(ws, r, 1, k, bold=True)
        if v is not None:
            put(ws, r, 2, v)
    ws["A1"].font = Font(bold=True, size=14)
    ws["B2"].font = Font(bold=True, color="991B1B")
    if test:
        ws["A3"].font = Font(bold=True, color="991B1B")
        ws["B3"].font = Font(bold=True, color="991B1B")
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 90
    ws.page_setup.orientation = "landscape"


def _nodes_sheet(ws, view, node_ids, intents, labels):
    header(ws, NODE_COLUMNS)
    r = 1
    for n in view["nodes"]:
        if node_ids is not None and n["node_id"] not in node_ids:
            continue
        r += 1
        b = n.get("boundary") or {}
        short = view.get("drawing_short") or {}

        def one(x):
            if not x:
                return ""
            return "%s(%s)" % (x["label"], short.get(x["drawing"], x["drawing"])) if x.get("drawing") else x["label"]
        members = [labels.get(m) for m in n["members"]]
        tagged = sorted({m for m in members if m})
        untagged = len(members) - len([m for m in members if m])
        comp = ", ".join(tagged) + ((" 외 태그 없는 요소 %d" % untagged) if untagged else "")
        intent = (intents or {}).get(n["node_id"]) or ""
        for c, v in enumerate((n["node_id"], n.get("name") or "", "[%s]" % " → ".join(n.get("drawings_short") or []),
                               one(b.get("start")), one(b.get("end")), intent, comp), 1):
            put(ws, r, c, v)
    autofilter(ws, len(NODE_COLUMNS), r - 1)


def _worksheet_sheet(ws, rows):
    from openpyxl.styles import Font
    cols = [(title, width) for _k, title, width in WORKSHEET_COLUMNS]
    header(ws, cols)
    keys = [k for k, _t, _w in WORKSHEET_COLUMNS]
    risk_col = keys.index("risk") + 1
    for r, row in enumerate(rows, 2):
        for c, k in enumerate(keys, 1):
            put(ws, r, c, row.get(k, ""))
        _paint_risk(ws.cell(row=r, column=risk_col), row["risk_value"])
        if row["kind"] != "entry":
            ws.cell(row=r, column=keys.index("status") + 1).font = Font(italic=True, bold=True)
    autofilter(ws, len(cols), len(rows))


def _recommendation_sheet(ws, rows):
    header(ws, RECOMMENDATION_COLUMNS)
    picked = [x for x in rows if x["kind"] == "entry" and x.get("recommendation") and x["status_key"] != "rejected"]
    for i, x in enumerate(picked, 1):
        for c, v in enumerate((i, x["node"], x["deviation"], x["recommendation"], x["risk"], x["status"], "", ""), 1):
            put(ws, i + 1, c, v)
        _paint_risk(ws.cell(row=i + 1, column=5), x["risk_value"])
    autofilter(ws, len(RECOMMENDATION_COLUMNS), len(picked))


def build_workbook(results, node_set, pg, deviations, scope="all", node_ids=None, reviewer="", intents=None, now=None,
                   expectations=None, test=False):
    """Workbook과 워크시트 행 수. scope가 'nodes'면 node_ids(구간 ID 목록)가 있어야 한다.
    expectations: 잠재 후보 계산 결과(hazop.kg.expect.evaluate) 또는 None. test: 고정 응답(시험) 결과에서 내보냄."""
    from openpyxl import Workbook
    if scope == "nodes" and not node_ids:
        raise ValueError("선택한 구간이 없습니다")
    now = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    view = span.annotate(node_set, pg)
    xs = {i["id"]: i for i in expectations["items"]} if expectations else None
    rows = worksheet_rows(results, view, pg, deviations, scope, node_ids, xs)
    wb = Workbook()
    _summary_sheet(wb.active, results, node_set, view, scope, list(node_ids or ()), reviewer, now, len(rows), test)
    wb.active.title = SHEETS[0]
    _nodes_sheet(wb.create_sheet(SHEETS[1]), view, set(node_ids) if scope == "nodes" else None, intents,
                 entity_labels(pg))
    _worksheet_sheet(wb.create_sheet(SHEETS[2]), rows)
    _recommendation_sheet(wb.create_sheet(SHEETS[3]), rows)
    return wb, len(rows)


def save_workbook(wb, path):
    """같은 폴더 임시 파일에 쓴 뒤 교체한다(열려 있는 파일이면 PermissionError 그대로)."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".hazop-export-", suffix=".xlsx", dir=folder)
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def export(path, results, node_set, pg, deviations, **kw):
    """build_workbook + save_workbook. (경로, 워크시트 행 수)."""
    wb, n = build_workbook(results, node_set, pg, deviations, **kw)
    return save_workbook(wb, path), n
