"""IE 인계 묶음 Excel(사람이 읽는 판)과 내보내기. 기획서/초기사건-출력설계.md §3.2, §8 P2·P3.

build_workbook(bundle) → openpyxl Workbook. 내용은 모두 hazop.ie.bundle.build_bundle의 dict에서 옮긴다.
- 시트 0~9: 읽는 법 / IE 후보 / IE 그룹 / 사건수목 표제 후보 / 최종상태 후보 / 기본사건 후보 / 추적표 / 완전성 대조 /
  품질 경고 / 용어·출처. 머리글·순서·열 너비는 §3.4 예시 Excel과 같다.
- 작성이 'AI 초안'인 행은 회색 바탕으로 칠한다. PSA 담당이 채울 열('PSA …' 머리글)은 머리글을 노란색으로 두고 비워 둔다.
- 셀 쓰기는 ⑤ Excel(hazop.export.study_xlsx.put)과 같다: 문자열 셀, 수식 모양 글자 실행 막기, 경로·키 가리기.
export(xlsx_path, bundle)는 .xlsx와 같은 이름의 .json을 같은 폴더에 쓴다. 둘 다 임시 파일에 쓴 뒤 교체한다.
"""

import datetime
import os
import re
import shutil
import tempfile

from hazop.export import study_xlsx as sx
from hazop.ie import bundle as ib
from hazop.ie import model
from hazop.study import refs
from hazop.study import results as res

JUDGEMENTS = {"yes": "후보", "no": "제외", "undecided": "보류"}
ANSWERS = {"yes": "예", "no": "아니오", "unknown": "미확인"}
ORIGINS = {"ai_draft": "AI 초안", "human": "사람"}
COVERAGE = {"covered": "대응 있음", "gap": "공백", "not_applicable": "해당 없음", "unclassified": "미분류"}
BASIS_UNKNOWN_PREFIX = ib.BASIS_UNKNOWN_PREFIX
NOT_JUDGED = "초기사건 판정 전"
AI_FILL = "EEF0F2"
PSA_FILL = "FDF0D2"

# 읽는 법 시트에 적는 경고별 한 줄 안내(ib.WARNING_KINDS 순서)
WARNING_GUIDE = (
    ("safeguard_as_cause", "원인 위치가 안전밸브 같은 보호설비이거나 다른 승인 항목이 보호수단으로 적은 대상입니다. "
                           "보호설비 고장은 대개 초기사건이 아니라 표제의 실패입니다"),
    ("mitigated_consequence", "결과 문장이 보호수단이 작동한 뒤의 결과로 읽힙니다. 표현으로만 짐작하므로 틀릴 수 있습니다"),
    ("actuation_unknown", "보호수단이 자동·운전원·자체작동 가운데 무엇인지 정해지지 않았습니다"),
    ("boundary_cut", "결과의 영향 대상이 다른 구간에 있는데 그 구간에 승인 항목이 없어 사건 진행을 이을 수 없습니다"),
    ("fmea_pending", "계기·제어 구성요소가 든 구간입니다. 이 앱에는 아직 FMEA 입력이 없어 항목마다 띄우지 않고 구간 수만 "
                     "한 줄로 적습니다"),
)
GUIDE_COLUMNS =(("항목", 22), ("내용", 100))
CANDIDATE_COLUMNS = (("후보 ID", 9), ("판정", 7), ("정상운전 교란", 8), ("안전기능 도전", 8), ("도전받는 안전기능", 16),
                     ("원인", 30), ("원인 유형", 11), ("원인 위치", 11), ("고장모드", 10), ("구간", 7), ("편차", 10),
                     ("비완화 결과", 34), ("일반 범주 제안", 10), ("그룹 ID", 8), ("제외·보류 사유", 26), ("식별 기법", 8),
                     ("출처 항목 ID", 14), ("안정 참조", 22), ("작성", 8), ("⑤ 상태", 7))
GROUP_COLUMNS = (("그룹 ID", 8), ("그룹 이름", 18), ("정의", 34), ("일반 범주", 9), ("범주 출처", 14), ("대표 후보", 9),
                 ("대표 선정 이유", 20), ("소속 후보", 22), ("후보 수", 6), ("플랜트 응답", 26), ("영향받는 완화계통", 24),
                 ("지원계통 IE", 7), ("표제 후보", 18), ("최종상태 후보", 12), ("작성", 8), ("상태", 7),
                 ("PSA IE 이름", 12), ("성공기준", 16), ("빈도 근거", 16))
HEADING_COLUMNS = (("표제 ID", 7), ("표제 이름(제안)", 16), ("출처 보호수단", 30), ("구현 대상", 16), ("관련 계통", 12),
                   ("역할", 7), ("작동 방식", 8), ("운전원 조치 단서", 22), ("적용 그룹", 12), ("출처 항목 ID", 18),
                   ("작성", 8), ("PSA 표제 이름", 12))
END_STATE_COLUMNS = (("ES ID", 7), ("비완화 결과(대표 문장)", 40), ("결과 범주 제안", 14), ("관련 그룹", 12),
                     ("출처 항목 수", 8), ("작성", 8), ("PSA 최종상태", 12))
BASIC_EVENT_COLUMNS = (("BE ID", 8), ("앱 제안 이름", 22), ("기기 태그", 12), ("기기 종류", 14), ("계통", 9),
                       ("고장모드 코드", 8), ("고장모드 설명", 16), ("정상 위치", 8), ("고장 위치", 8),
                       ("관련 표제·후보", 16), ("출처", 16), ("작성", 8), ("PSA 기본사건 이름", 16))
# PSA 담당 기입 칸(머리글 노란색, 값은 비움). 시트별 마지막 열들
PSA_COLUMNS = {"IE 그룹": 3, "사건수목 표제 후보": 1, "최종상태 후보": 1, "기본사건 후보": 1}
TRACE_COLUMNS = (("구간·편차", 14), ("출처 항목 ID", 14), ("원인", 30), ("후보 ID", 9), ("판정", 7), ("그룹 ID", 8),
                 ("표제 ID", 18), ("ES ID", 12), ("근거 KG 경로", 34), ("출처 문서", 24))
COMPLETENESS_COLUMNS = (("범주 코드", 9), ("범주 이름", 28), ("기준표 출처", 16), ("대응 그룹", 10), ("후보 수", 6),
                        ("상태", 9), ("사유·처리", 40))
WARNING_COLUMNS = (("경고", 18), ("대상", 14), ("내용", 50), ("근거", 26))
GLOSSARY_COLUMNS = (("용어", 18), ("뜻", 60), ("출처", 40))
SHEETS = ("읽는 법", "IE 후보", "IE 그룹", "사건수목 표제 후보", "최종상태 후보", "기본사건 후보", "추적표", "완전성 대조",
          "품질 경고", "용어·출처")


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


def group_row(g):
    held = "승인 해제로 빠진 후보: " + _joined(g["held_members"]) if g["held_members"] else ""
    definition = " · ".join(x for x in (g["definition"], held) if x)
    return (g["group_id"], g["name"], definition, "·".join(g["categories"]), g["category_source"],
            g["representative"] or "", g["representative_reason"], _joined(g["members"]), g["member_count"],
            g["plant_response"], g["affected_mitigation"], model.SUPPORT_IE[g["support_ie"]], _joined(g["heading_ids"]),
            _joined(g["end_state_ids"]), ORIGINS[g["origin"]], model.GROUP_STATUSES[g["status"]], None, None, None)


def heading_row(h):
    return (h["heading_id"], h["name"], " / ".join(h["sources"]), _joined(h["targets"]), h["systems"],
            refs.ROLES[h["role"]], refs.ACTUATIONS[h["actuation"]], h["operator_cue"], _joined(h["group_ids"]),
            _joined(h["entry_ids"]), ORIGINS[h["origin"]], None)


def end_state_row(e):
    return (e["end_state_id"], e["text"], model.ES_CATEGORIES[e["category"]], _joined(e["group_ids"]),
            e["source_count"], ORIGINS[e["origin"]], None)


def basic_event_row(b):
    return (b["be_id"], b["name"], b["tag"], b["equipment_kind"], b["system"], b["failure_mode"] or "코드 미정",
            b["failure_text"], b["normal_position"] or "—", b["failed_position"] or "—",
            _joined(b["candidate_ids"] + b["heading_ids"]), "·".join(model.SOURCE_KINDS[k] for k in b["source_kinds"]),
            ORIGINS[b["origin"]], None)


def trace_row(t):
    sources = ["%s%s" % (s["doc"] or "-", " (%s)" % s["where"] if s["where"] else "") for s in t["sources"]]
    return ("%s · %s" % (t["node_id"], t["deviation_label"]), t["entry_id"], t["cause"], t["candidate_id"],
            JUDGEMENTS[t["judgement"]], t["group_id"] or "", _joined(t["top_event_ids"]), _joined(t["end_state_ids"]),
            "\n".join(t["kg_paths"]), "\n".join(sources))


def completeness_row(r):
    return (r["code"] or res.UNCLASSIFIED_LABEL, r["name_ko"], r["source_label"], r["group_id"] or "",
            r["candidate_count"], COVERAGE[r["status"]], r["note"])


def warning_row(w):
    return (ib.WARNING_KINDS[w["kind"]][0], w["target"], w["text"], w["basis"])


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
        ("AI 초안", "'작성' 열이 'AI 초안'인 행(회색 바탕)은 사람이 아직 확정하지 않은 값입니다. 규칙으로 만든 초안도 "
                   "여기에 듭니다"),
        ("그룹 상태", "'확정'은 검토자가 ⑥ 화면에서 확정한 뒤 소속 후보·표제·최종상태가 바뀌지 않은 그룹입니다. ⑤에서 소속 "
                    "항목을 고치거나 승인을 풀면 다시 '초안'이 됩니다"),
        ("PSA 기입 칸", "머리글이 노란 열('PSA …' 열)은 PSA 담당이 채우는 칸이며 비워 두었습니다"),
        ("ID 규칙", "IEC-nnn 후보 · IEG-nn 그룹 · H-nn 사건수목 표제 후보 · ES-nn 최종상태 후보 · BE-nnn 기본사건 후보. "
                  "대응표를 ⑥ 저장 파일에 두므로 묶음을 다시 만들어도 같은 원인은 같은 ID를 유지합니다. 나눈 그룹은 새 ID를 받고 "
                  "옛 ID는 '나뉨' 기록으로 남습니다(지운 ID도 다시 쓰지 않음)"),
        ("품질 경고 요약", ib.warning_summary_text(b)),
        ("품질 경고 읽는 법", "'품질 경고' 시트는 인계 전에 다시 볼 곳을 알려 줄 뿐 항목을 막지 않습니다. "
                         + " ".join("%s: %s." % (ib.WARNING_KINDS[k][0], t) for k, t in WARNING_GUIDE)),
        ("기준표", "일반 범주 코드: %s · %s. 출처는 '용어·출처' 시트에 있습니다" % (table["title"] or "-", table["source_label"])),
        ("시트", " / ".join(SHEETS[1:])),
    ) + ((("나뉨·삭제 그룹", ", ".join("%s(%s%s)" % (r["id"], model.GROUP_STATUSES[r["status"]],
                                                   " → " + ", ".join(r["split_into"]) if r["split_into"] else "")
                                       for r in b["retired"])),) if b["retired"] else ())


def _sheet(wb, title, columns, rows, first=False, ai_col=None):
    from openpyxl.styles import PatternFill
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    sx.header(ws, columns)
    for c in range(len(columns) - PSA_COLUMNS.get(title, 0) + 1, len(columns) + 1):
        ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor=PSA_FILL)
    for r, row in enumerate(rows, 2):
        draft = ai_col is not None and row[ai_col] == ORIGINS["ai_draft"]
        for c, v in enumerate(row, 1):
            cell = sx.put(ws, r, c, v)
            if draft:
                cell.fill = PatternFill("solid", fgColor=AI_FILL)
    sx.autofilter(ws, len(columns), len(rows))
    return ws


def build_workbook(b):
    from openpyxl import Workbook
    wb = Workbook()
    made = datetime.datetime.strptime(b["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    wb.properties.created = wb.properties.modified = made  # 같은 묶음이면 같은 파일이 나오게 실행 시각 대신 만든 시각
    _sheet(wb, SHEETS[0], GUIDE_COLUMNS, guide_rows(b), first=True)
    for title, columns, rows in ((SHEETS[1], CANDIDATE_COLUMNS, [candidate_row(c) for c in b["candidates"]]),
                                 (SHEETS[2], GROUP_COLUMNS, [group_row(g) for g in b["groups"]]),
                                 (SHEETS[3], HEADING_COLUMNS, [heading_row(h) for h in b["top_events"]]),
                                 (SHEETS[4], END_STATE_COLUMNS, [end_state_row(e) for e in b["end_states"]]),
                                 (SHEETS[5], BASIC_EVENT_COLUMNS, [basic_event_row(x) for x in b["basic_events"]])):
        _sheet(wb, title, columns, rows, ai_col=[t for t, _ in columns].index("작성"))
    _sheet(wb, SHEETS[6], TRACE_COLUMNS, [trace_row(t) for t in b["trace"]])
    _sheet(wb, SHEETS[7], COMPLETENESS_COLUMNS, [completeness_row(r) for r in b["completeness"]])
    _sheet(wb, SHEETS[8], WARNING_COLUMNS, [warning_row(w) for w in b["warnings"]])
    _sheet(wb, SHEETS[9], GLOSSARY_COLUMNS, [(g["term"], g["meaning"], g["source"]) for g in b["glossary"]])
    return wb


def default_stem(project_id, now):
    """IE-<프로젝트>-<KST 날짜시각>. 확장자는 붙이지 않는다(.xlsx와 .json이 같은 이름)."""
    return "IE-%s-%s" % (re.sub(r'[\\/:*?"<>|\s]+', "_", project_id or "프로젝트"), sx.kst(now, "%Y%m%d-%H%M"))


def export(xlsx_path, b):
    """xlsx_path와 같은 이름의 .json을 함께 쓴다. 둘 다 같은 폴더 임시 파일에 먼저 쓰고 둘 다 써진 뒤에 교체하므로, 쓰는
    도중 실패하면 어느 쪽도 바뀌지 않는다. .xlsx를 교체한 뒤 .json 교체가 실패하면(.json이 열려 있는 등) 옛 .xlsx를
    되돌려 놓는다(옛 파일이 없었으면 새 .xlsx를 지운다). 그래서 새 .xlsx와 옛 .json이 짝으로 남지 않는다.
    오류는 그대로 올린다. (xlsx 경로, json 경로)."""
    json_path = os.path.splitext(xlsx_path)[0] + ".json"
    folder = os.path.dirname(os.path.abspath(xlsx_path))
    tmps = []
    try:
        for suffix in (".xlsx", ".json", ".old"):
            fd, tmp = tempfile.mkstemp(prefix=".hazop-ie-", suffix=suffix, dir=folder)
            os.close(fd)
            tmps.append(tmp)
        build_workbook(b).save(tmps[0])
        with open(tmps[1], "w", encoding="utf-8", newline="\n") as fh:
            fh.write(ib.dumps(b))
        had_old = os.path.exists(xlsx_path)
        if had_old:
            shutil.copy2(xlsx_path, tmps[2])
        os.replace(tmps[0], xlsx_path)
        try:
            os.replace(tmps[1], json_path)
        except OSError:
            if had_old:
                os.replace(tmps[2], xlsx_path)
            else:
                os.remove(xlsx_path)
            raise
    finally:
        for tmp in tmps:
            if os.path.exists(tmp):
                os.remove(tmp)
    return xlsx_path, json_path
