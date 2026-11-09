"""IE 인계 묶음 Excel(사람이 읽는 판)과 내보내기. 기획서/초기사건-출력설계.md §3.2, §8 P2.

build_workbook(bundle) → openpyxl Workbook. 내용은 모두 hazop.ie.bundle.build_bundle의 dict에서 옮긴다.
- 시트: 읽는 법 / IE 후보 / 추적표 / 완전성 대조 / 품질 경고 / 용어·출처. 머리글·순서·열 너비는 §3.4 예시 Excel과 같다.
  IE 그룹·사건수목 표제 후보·최종상태 후보·기본사건 후보 시트(2~5)는 ⑥ 화면(P3)에서 더한다.
- 'IE 후보'에서 작성이 'AI 초안'인 행은 회색 바탕으로 칠한다.
- 셀 쓰기는 ⑤ Excel(hazop.export.study_xlsx.put)과 같다: 문자열 셀, 수식 모양 글자 실행 막기, 경로·키 가리기.
export(xlsx_path, bundle)는 .xlsx와 같은 이름의 .json을 같은 폴더에 쓴다. 둘 다 임시 파일에 쓴 뒤 교체한다.
"""

import datetime
import os
import re
import tempfile

from openpyxl import Workbook
from openpyxl.styles import PatternFill

from hazop.export import study_xlsx as sx
from hazop.ie import bundle as ib
from hazop.study import results as res

JUDGEMENTS = {"yes": "후보", "no": "제외", "undecided": "보류"}
ANSWERS = {"yes": "예", "no": "아니오", "unknown": "미확인"}
ORIGINS = {"ai_draft": "AI 초안", "human": "사람"}
COVERAGE = {"covered": "대응 있음", "gap": "공백", "unclassified": "미분류"}
BASIS_UNKNOWN_PREFIX = "[비완화 여부 미확인] "
NOT_JUDGED = "초기사건 판정 전"
AI_FILL = PatternFill("solid", fgColor="EEF0F2")

GUIDE_COLUMNS = (("항목", 22), ("내용", 100))
CANDIDATE_COLUMNS = (("후보 ID", 9), ("판정", 7), ("정상운전 교란", 8), ("안전기능 도전", 8), ("도전받는 안전기능", 16),
                     ("원인", 30), ("원인 유형", 11), ("원인 위치", 11), ("고장모드", 10), ("구간", 7), ("편차", 10),
                     ("비완화 결과", 34), ("일반 범주 제안", 10), ("그룹 ID", 8), ("제외·보류 사유", 26), ("식별 기법", 8),
                     ("출처 항목 ID", 14), ("안정 참조", 22), ("작성", 8), ("⑤ 상태", 7))
TRACE_COLUMNS = (("구간·편차", 14), ("출처 항목 ID", 14), ("원인", 30), ("후보 ID", 9), ("판정", 7), ("그룹 ID", 8),
                 ("표제 ID", 18), ("ES ID", 12), ("근거 KG 경로", 34), ("출처 문서", 24))
COMPLETENESS_COLUMNS = (("범주 코드", 9), ("범주 이름", 28), ("기준표 출처", 16), ("대응 그룹", 10), ("후보 수", 6),
                        ("상태", 9), ("사유·처리", 40))
WARNING_COLUMNS = (("경고", 18), ("대상", 14), ("내용", 50), ("근거", 26))
GLOSSARY_COLUMNS = (("용어", 18), ("뜻", 60), ("출처", 40))
SHEETS = ("읽는 법", "IE 후보", "추적표", "완전성 대조", "품질 경고", "용어·출처")


def _joined(xs):
    return ", ".join(xs or [])


def candidate_row(c):
    return (c["candidate_id"], JUDGEMENTS[c["judgement"]], ANSWERS[c["disturbs"]], ANSWERS[c["challenges"]],
            _joined(c["safety_functions"]), c["cause"], res.CAUSE_KINDS.get(c["cause_kind"], res.UNKNOWN_LABEL),
            _joined(c["cause_location"]), _joined(c["failure_modes"]), c["node_id"], c["deviation_label"],
            (BASIS_UNKNOWN_PREFIX if c["consequence_basis"] is None else "") + c["consequence"],
            c["category"] or res.UNCLASSIFIED_LABEL, c["group_id"] or "",
            c["reason"] if c["ie_origin"] else NOT_JUDGED, c["method"], c["entry_id"], _joined(c["stable_refs"]),
            ORIGINS.get(c["ie_origin"], ""), "승인")


def trace_row(t):
    sources = ["%s%s" % (s["doc"] or "-", " (%s)" % s["where"] if s["where"] else "") for s in t["sources"]]
    return ("%s · %s" % (t["node_id"], t["deviation_label"]), t["entry_id"], t["cause"], t["candidate_id"],
            JUDGEMENTS[t["judgement"]], t["group_id"] or "", _joined(t["top_event_ids"]), _joined(t["end_state_ids"]),
            "\n".join(t["kg_paths"]), "\n".join(sources))


def completeness_row(r):
    return (r["code"] or res.UNCLASSIFIED_LABEL, r["name_ko"], r["source_label"], r["group_id"] or "",
            r["candidate_count"], COVERAGE[r["status"]], r["note"])


def warning_row(w):
    return (res.QUALITY_KINDS[w["kind"]][0], w["target"], w["text"], w["basis"])


def guide_rows(b):
    ref = b["source"]["study_nodes_ref"] or {}
    confirmed = sx.kst(ref["confirmed_at"]) + " KST" if ref.get("confirmed_at") else "-"
    table = b["category_table"]
    return (
        ("묶음", "IE 인계 묶음(초기사건 분석 인계 자료). 원본은 같은 이름의 .json 파일이고, 이 Excel은 그 내용을 사람이 "
                "읽기 좋게 옮긴 판입니다"),
        ("프로젝트", b["project_id"] or "-"),
        ("만든 시각", sx.kst(b["created_at"]) + " KST"),
        ("입력", "⑤ HAZOP 결과 중 '승인' 항목 %d건. 결과 판: 검토구간 확정 %s, 그래프 판 %s"
               % (b["source"]["approved_entries"], confirmed, ref.get("graph_version") or "-")),
        ("넣지 않은 항목", "승인되지 않은 항목 %d건(제안·수정·기각)은 넣지 않았습니다" % b["source"]["left_out_unapproved"]),
        ("빈도", "이 묶음에는 초기사건 빈도·기기 고장확률이 없습니다. 빈도 산정과 정량화는 PSA 도구에서 합니다"),
        ("HAZOP 위험도", "KOSHA 위험도(강도·빈도 등급)는 정성 등급이라 넣지 않았습니다. 필요하면 ⑤ 워크시트를 보십시오"),
        ("AI 초안", "'IE 후보' 시트에서 '작성' 열이 'AI 초안'인 행(회색 바탕)은 사람이 아직 확정하지 않은 초기사건 판정입니다"),
        ("ID 규칙", "IEC-nnn은 초기사건 후보 ID입니다. 번호는 이 묶음에 든 승인 항목 순서(구간 → 편차 → 항목)대로 붙이므로 "
                  "승인 항목이 늘거나 줄면 바뀔 수 있습니다. 같은 원인이 늘 같은 ID를 갖게 하는 대응표는 다음 단계에서 ⑥ 저장 "
                  "파일과 함께 더합니다. 그때까지는 '출처 항목 ID'(⑤ 항목 ID)로 찾아 주십시오"),
        ("기준표", "일반 범주 코드: %s · %s. 출처는 '용어·출처' 시트에 있습니다" % (table["title"] or "-", table["source_label"])),
        ("시트", " / ".join(SHEETS)),
        ("다음 단계", "IE 그룹·사건수목 표제 후보·최종상태 후보·기본사건 후보 시트는 다음 단계(⑥ 화면)에서 더합니다"),
    )


def _sheet(wb, title, columns, rows, first=False, ai_col=None):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    sx.header(ws, columns)
    for r, row in enumerate(rows, 2):
        draft = ai_col is not None and row[ai_col] == ORIGINS["ai_draft"]
        for c, v in enumerate(row, 1):
            cell = sx.put(ws, r, c, v)
            if draft:
                cell.fill = AI_FILL
    sx.autofilter(ws, len(columns), len(rows))
    return ws


def build_workbook(b):
    wb = Workbook()
    made = datetime.datetime.strptime(b["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    wb.properties.created = wb.properties.modified = made  # 같은 묶음이면 같은 파일이 나오게 실행 시각 대신 만든 시각
    _sheet(wb, SHEETS[0], GUIDE_COLUMNS, guide_rows(b), first=True)
    _sheet(wb, SHEETS[1], CANDIDATE_COLUMNS, [candidate_row(c) for c in b["candidates"]],
           ai_col=[t for t, _ in CANDIDATE_COLUMNS].index("작성"))
    _sheet(wb, SHEETS[2], TRACE_COLUMNS, [trace_row(t) for t in b["trace"]])
    _sheet(wb, SHEETS[3], COMPLETENESS_COLUMNS, [completeness_row(r) for r in b["completeness"]])
    _sheet(wb, SHEETS[4], WARNING_COLUMNS, [warning_row(w) for w in b["warnings"]])
    _sheet(wb, SHEETS[5], GLOSSARY_COLUMNS, [(g["term"], g["meaning"], g["source"]) for g in b["glossary"]])
    return wb


def default_stem(project_id, now):
    """IE-<프로젝트>-<KST 날짜시각>. 확장자는 붙이지 않는다(.xlsx와 .json이 같은 이름)."""
    return "IE-%s-%s" % (re.sub(r'[\\/:*?"<>|\s]+', "_", project_id or "프로젝트"), sx.kst(now, "%Y%m%d-%H%M"))


def export(xlsx_path, b):
    """xlsx_path와 같은 이름의 .json을 함께 쓴다. 둘 다 같은 폴더 임시 파일에 먼저 쓰고 둘 다 써진 뒤에 교체하므로, 쓰는
    도중 실패하면 어느 쪽도 바뀌지 않는다. 다만 .xlsx를 교체한 뒤 .json 교체가 실패하면(.json이 열려 있는 등) 새 .xlsx와
    옛 .json이 남는다. 오류는 그대로 올린다. (xlsx 경로, json 경로)."""
    json_path = os.path.splitext(xlsx_path)[0] + ".json"
    folder = os.path.dirname(os.path.abspath(xlsx_path))
    tmps = []
    try:
        for suffix in (".xlsx", ".json"):
            fd, tmp = tempfile.mkstemp(prefix=".hazop-ie-", suffix=suffix, dir=folder)
            os.close(fd)
            tmps.append(tmp)
        build_workbook(b).save(tmps[0])
        with open(tmps[1], "w", encoding="utf-8", newline="\n") as fh:
            fh.write(ib.dumps(b))
        os.replace(tmps[0], xlsx_path)
        os.replace(tmps[1], json_path)
    finally:
        for tmp in tmps:
            if os.path.exists(tmp):
                os.remove(tmp)
    return xlsx_path, json_path
