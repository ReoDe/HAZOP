"""비교 보고 JSON·Excel (기획서/평가기준비교.md §5).

- build_report(criteria, view, criteria_info, view_reasons, now): 메모리에서 보고 dict를 만든다(파일 쓰기 없음).
- write_report(report, out_root): <out_root>/<region_id>/<analysis_run_id>/compare-<기준 ID>-v<버전>-<basis>-<시각>.json
  과 같은 이름의 .xlsx를 새로 만든다. 같은 이름이 있으면 CompareError(덮어쓰지 않음).
- run_compare(...): 기준 읽기(어댑터) → 뷰 생성 → 보고 → 쓰기.
- comparison_id는 시각이 아니라 입력(기준 해시·analysis 해시·basis·검토본 목록·export_id·compare_version)에서 만든다.
"""

import hashlib
import io
import json
import os
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils.exceptions import IllegalCharacterError

from hazop import paths
from hazop.evaluate import adapters
from hazop.evaluate.criteria import CriteriaError, validate_criteria
from hazop.evaluate.match import NOT_EVALUATED, match
from hazop.evaluate.view import build_view
from hazop.export.worksheet import FORMULA_PREFIX
from hazop.review import store

SCHEMA_VERSION = "0.1"
COMPARE_VERSION = "0.1.0"
SYNTHETIC_NOTICE = "가상 기준 — MVP 성공 판단에 쓰지 않음"
SHEETS = ("요약", "행별 대응", "누락", "초과")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class CompareError(ValueError):
    """비교 실행 실패(파일 쓰기 불가·같은 이름 파일 있음 등). errors에 사유 목록."""

    def __init__(self, errors):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


def dumps(obj):
    """결정적 JSON(키 정렬·들여쓰기 2칸·끝 줄바꿈) — evaluation.dumps와 같은 방식."""
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_sha256(doc):
    """파일이 없는 기준(메모리)의 해시: 키 정렬·공백 없는 JSON의 SHA-256."""
    return hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def comparison_id(criteria_sha, view):
    reviews = ",".join("%s:%s" % (r["candidate_id"], r["review_version"])
                       for r in sorted(view["reviews"], key=lambda r: (r["candidate_id"], r["review_version"])))
    key = "|".join([criteria_sha, view["analysis_sha256"], view["basis"], reviews, view.get("export_id") or "",
                    COMPARE_VERSION])
    return "compare-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def build_report(criteria, view, criteria_info=None, view_reasons=(), now="1970-01-01T00:00:00Z"):
    """보고 dict. criteria_info: {"sha256", "source_format", "adapter", "notes"}(없으면 메모리 기준으로 채움).
    criteria가 None이면(읽기 실패) criteria_info["errors"]를 차단 사유로 쓴다."""
    info = dict(criteria_info or {})
    reasons = list(info.get("errors") or [])
    if criteria is not None:
        reasons.extend(validate_criteria(criteria))
    elif not reasons:
        reasons.append("기준을 읽지 못함(내용 없음)")
    crit = criteria if isinstance(criteria, dict) else {}
    sha = info.get("sha256") or (canonical_sha256(criteria) if criteria is not None else None)
    prov = crit.get("provenance") if isinstance(crit.get("provenance"), dict) else {}
    if not reasons:
        if crit["region_id"] != view["region_ref"]["region_id"]:
            reasons.append("기준 region_id(%s)가 분석 실행 구간(%s)과 다름"
                           % (crit["region_id"], view["region_ref"]["region_id"]))
        if crit["operating_mode"] != view.get("operating_mode"):
            reasons.append("기준 operating_mode(%s)가 분석 실행(%s)과 다름"
                           % (crit["operating_mode"], view.get("operating_mode")))
    reasons.extend(view_reasons)
    body = None
    if not reasons:
        try:
            body = match(criteria, view)
        except CriteriaError as exc:
            reasons.extend(exc.errors)
    reviewed_scen = sum(1 for s in view["scenarios"] if s.get("decision") is not None) + view["excluded_by_review"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "comparison_id": comparison_id(sha, view) if sha else None,
        "compare_version": COMPARE_VERSION, "compared_at": now,
        "status": "blocked" if reasons else "ok", "reasons": reasons,
        "notice": SYNTHETIC_NOTICE if prov.get("kind") == "synthetic" else None,
        "criteria": {"criteria_id": crit.get("criteria_id"), "criteria_version": crit.get("criteria_version"),
                     "sha256": sha, "provenance_kind": prov.get("kind"),
                     "source_format": info.get("source_format", "json"), "adapter": info.get("adapter"),
                     "notes": list(info.get("notes") or [])},
        "target": {"analysis_run_id": view["analysis_run_id"], "analysis_sha256": view["analysis_sha256"],
                   "region_ref": view["region_ref"], "graph_ref": view["graph_ref"], "basis": view["basis"],
                   "export_id": view.get("export_id"), "reviewed_scenarios": reviewed_scen,
                   "excluded_by_review": view["excluded_by_review"]},
    }
    if body is None:
        report.update({"metrics": None, "pairs": None, "missing": None, "extra": None, "criteria_warnings": None})
    else:
        report.update(body)
    return report


# ---------------------------------------------------------------- Excel
def _put(ws, row, col, value, bold=False):
    """셀 쓰기. None은 '없음'(호출자가 의미를 정한 문자열을 넘기는 것이 원칙), 수식처럼 시작하는 문자열은 문자열 셀."""
    if value is None:
        value = "없음"
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    cell = ws.cell(row=row, column=col)
    cell.value = value
    if isinstance(value, str) and value.startswith(FORMULA_PREFIX):
        cell.data_type = "s"
        cell.quotePrefix = True
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    if bold:
        cell.font = Font(bold=True)


def _table(ws, start, headers, rows, widths=None):
    for c, h in enumerate(headers, 1):
        _put(ws, start, c, h, bold=True)
    for r, values in enumerate(rows, start + 1):
        for c, v in enumerate(values, 1):
            _put(ws, r, c, v)
    for c, w in enumerate(widths or (), 1):
        ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = w
    return start + len(rows)


def _metric_text(v, num_den=None):
    if v == NOT_EVALUATED:
        return "평가 안 함(draft 기준)"
    if v is None:
        return "계산 안 함(분모 0)"
    return "%s%s" % (v, " (%d/%d)" % num_den if num_den else "")


def _bools(values, n_label="#"):
    if values is None:
        return "평가 안 함(기준 safeguards가 null)"
    if not values:
        return "기준 항목 없음"
    return ", ".join("%s%d %s" % (n_label, i, {True: "일치", False: "불일치", None: "평가 안 함"}[v])
                     for i, v in enumerate(values, 1))


def _dev_text(ref):
    if isinstance(ref, dict):
        return "%s/%s%s" % (ref.get("parameter"), ref.get("guide_word"),
                            " (%s)" % ref["item_id"] if ref.get("item_id") else "")
    return str(ref)


def _sheets(wb, report, criteria):
    ws = [wb.active] + [wb.create_sheet() for _ in SHEETS[1:]]
    for w, t in zip(ws, SHEETS):
        w.title = t
    crit, tgt = report["criteria"], report["target"]
    rows = []
    if report["notice"]:
        rows.append(("주의", report["notice"]))
    rows += [("상태", report["status"]), ("차단 사유", "\n".join(report["reasons"]) or "없음"),
             ("비교 ID", report["comparison_id"] or "계산 안 함(기준 해시 없음)"),
             ("비교 시각(UTC)", report["compared_at"]), ("비교 버전", report["compare_version"]),
             ("기준 ID·버전", "%s v%s" % (crit["criteria_id"], crit["criteria_version"])),
             ("기준 출처 구분", crit["provenance_kind"] or "확인 안 됨"), ("기준 파일 SHA-256", crit["sha256"]),
             ("기준 입력 형식", crit["source_format"]),
             ("변환 어댑터", "%s %s" % (crit["adapter"]["name"], crit["adapter"]["version"]) if crit["adapter"]
              else "변환 없음(정본 JSON)"),
             ("변환 메모", "\n".join(crit["notes"]) or "없음"),
             ("분석 실행 ID", tgt["analysis_run_id"]), ("analysis.json SHA-256", tgt["analysis_sha256"]),
             ("구간", "%s v%s" % (tgt["region_ref"]["region_id"], tgt["region_ref"].get("region_version"))),
             ("그래프", "%s %s" % (tgt["graph_ref"]["graph_id"], tgt["graph_ref"].get("graph_version"))),
             ("비교 기준(basis)", tgt["basis"]), ("출력 기록 ID", tgt["export_id"] or "지정 안 함"),
             ("검토 기록이 있는 시나리오 수", tgt["reviewed_scenarios"]),
             ("검토 기각으로 빠진 시나리오 수", tgt["excluded_by_review"])]
    m = report["metrics"]
    if m is not None:
        c = m["counts"]
        rows += [("편차 재현율", _metric_text(m["deviation_recall"], (c["Dr"], c["Dc"]))),
                 ("원인 재현율", _metric_text(m["cause_recall"])),
                 ("원인 정밀도", _metric_text(m["cause_precision"], (c["Mc"], c["So"]))),
                 ("결과 일치율", _metric_text(m["consequence_match"])),
                 ("보호수단 일치율", _metric_text(m["safeguard_match"])),
                 ("권고 일치율", _metric_text(m["recommendation_match"])),
                 ("집계", ", ".join("%s=%d" % (k, c[k]) for k in ("Dc", "Dr", "Do", "Rc", "M", "Mc", "So",
                                                                   "optional_matched")))]
        warns = report["criteria_warnings"]
        rows.append(("기준 경고", "\n".join(
            "%s: %s" % (w["kind"], w.get("tag") or "%s → %s" % (w.get("alias"), w.get("target")))
            + (" (행 %s)" % ", ".join(w["row_ids"]) if w.get("row_ids") else "") for w in warns) or "없음"))
    else:
        rows.append(("지표", "만들지 않음(차단)"))
    rows.append(("주의(공통)", "비교 통과는 계산이 규칙대로라는 뜻이며 분석 결과가 공학적으로 옳다는 뜻이 아님"))
    _table(ws[0], 1, ("항목", "값"), rows, (30, 100))
    if m is None:
        for w, h in zip(ws[1:], (("행 ID",), ("구분",), ("구분",))):
            _table(w, 1, h, [("차단되어 비교하지 않음",)])
        return

    pairs = {p["row_id"]: p for p in report["pairs"]}
    miss_rows = {r["row_id"]: r["reason"] for r in report["missing"]["rows"]}
    rrows = []
    for dev in criteria["deviations"]:
        for r in dev["rows"]:
            p = pairs.get(r["row_id"])
            rrows.append((r["row_id"], dev.get("label") or _dev_text(dev["deviation_ref"]),
                          "필수" if r.get("required", True) else "선택", r["cause"]["text"],
                          p["scenario_id"] if p else "대응 없음",
                          (p["worksheet_row"] if p and p["worksheet_row"] is not None else "없음(출력 기록 미지정)")
                          if p else "해당 없음",
                          p["score"] if p else "해당 없음",
                          _bools(p["consequences"]) if p else "해당 없음",
                          _bools(p["safeguards"]) if p else "해당 없음",
                          _bools(p["recommendations"]) if p else "해당 없음",
                          miss_rows.get(r["row_id"], "대응됨" if p else "선택 행 미대응(누락 아님)")))
    _table(ws[1], 1, ("행 ID", "편차", "필수", "기준 원인", "대응 시나리오", "워크시트 행", "점수", "결과 일치",
                      "보호수단 일치", "권고 일치", "누락 사유"), rrows, (8, 16, 6, 30, 22, 10, 6, 24, 24, 20, 24))

    mrows = []
    for d in report["missing"]["deviations"]:
        mrows.append(("편차", d.get("label") or _dev_text(d["deviation_ref"]), d["candidate_id"] or "후보 없음",
                      "해당 없음", d["reason"] + (" (%s)" % d["selection_status"] if d.get("selection_status") else "")))
    for r in report["missing"]["rows"]:
        mrows.append(("원인 행", r["row_id"], "해당 없음", r["cause"], r["reason"]))
    for kind, label in (("consequences", "결과"), ("safeguards", "보호수단"), ("recommendations", "권고")):
        for x in report["missing"][kind]:
            what = x.get("text") or x.get("tag") or json.dumps(x.get("keywords"), ensure_ascii=False)
            if kind == "safeguards":
                what = x.get("tag") or "키워드 %s" % json.dumps(x.get("keywords"), ensure_ascii=False)
            mrows.append((label, "%s #%d" % (x["row_id"], x["index"]), x["scenario_id"], what,
                          "대응 쌍에서 불일치" + ("" if x["required"] else "(선택 행)")))
    _table(ws[2], 1, ("구분", "편차·행", "후보·시나리오", "기준 내용", "사유"), mrows, (10, 24, 24, 50, 30))

    xrows = []
    for d in report["extra"]["deviations"]:
        xrows.append(("편차", d["candidate_id"], "해당 없음", ", ".join(d["scenario_ids"])))
    for s in report["extra"]["scenarios"]:
        xrows.append(("시나리오", s["scenario_id"], s["worksheet_row"] if s["worksheet_row"] is not None
                      else "없음(출력 기록 미지정)", s["candidate_id"]))
    for g in report["extra"]["safeguards"]:
        xrows.append(("보호수단", "%s–%s" % (g["row_id"], g["scenario_id"]), "해당 없음",
                      "%s %s" % (g["tag"] or "태그 없음", g["description"] or "")))
    _table(ws[3], 1, ("구분", "대상", "워크시트 행", "내용"), xrows, (10, 30, 12, 60))


def report_name(report, stamp):
    """보고 파일 이름(확장자 제외). 기준 버전이 1 이상 정수가 아니면 'vX'. 이름 전체를 경로 한 단계 규칙으로 검사한다
    (safe_name으로 바뀌는 이름은 거부 — 경로 이탈 방지)."""
    crit, tgt = report["criteria"], report["target"]
    cid = store.path_component(crit["criteria_id"], "criteria_id")
    cv = crit["criteria_version"]
    ver = "v%d" % cv if type(cv) is int and cv >= 1 else "vX"
    return store.path_component("compare-%s-%s-%s-%s" % (cid, ver, tgt["basis"], stamp), "보고 파일 이름")


def write_report(report, criteria, out_root):
    """JSON·Excel을 새 파일로 쓴다. 반환 (json 경로, xlsx 경로)."""
    now = report["compared_at"]
    if not isinstance(now, str) or not _UTC.match(now):
        raise CompareError("비교 시각이 UTC ISO 형식 아님: %r" % (now,))
    stamp = now.replace("-", "").replace(":", "")
    tgt = report["target"]
    try:
        name = report_name(report, stamp)
        out_dir = paths.safe_join(paths.safe_join(out_root, store.path_component(tgt["region_ref"]["region_id"],
                                                                                 "region_id")),
                                  store.path_component(tgt["analysis_run_id"], "analysis_run_id"))
    except (store.ReviewError, ValueError) as exc:
        raise CompareError("출력 경로를 만들 수 없음: %s" % exc)
    json_path = os.path.join(out_dir, name + ".json")
    xlsx_path = os.path.join(out_dir, name + ".xlsx")
    for p in (json_path, xlsx_path):
        if os.path.exists(p):
            raise CompareError("같은 이름의 파일이 이미 있음(덮어쓰지 않음): %s" % p)
    try:
        data = dumps(report).encode("utf-8")  # 직렬화 실패를 파일 쓰기 전에 잡는다
    except (TypeError, ValueError) as exc:
        raise CompareError("보고를 JSON으로 만들 수 없음: %s" % exc)
    wb = Workbook()
    try:
        _sheets(wb, report, criteria)
    except IllegalCharacterError as exc:
        raise CompareError("Excel에 쓸 수 없는 제어문자가 있는 값(%s) — 기준 파일을 확인해야 함" % exc)
    buf = io.BytesIO()
    wb.save(buf)
    try:
        os.makedirs(out_dir, exist_ok=True)
        store.write_exclusive(xlsx_path, buf.getvalue())
    except (store.ReviewError, OSError) as exc:
        raise CompareError("Excel 보고 쓰기 실패: %s" % exc)
    try:
        store.write_exclusive(json_path, data)
    except (store.ReviewError, OSError) as exc:
        os.remove(xlsx_path)
        raise CompareError("JSON 보고 쓰기 실패 — Excel 보고를 지움: %s" % exc)
    return json_path, xlsx_path


def load_criteria(path, fmt="json"):
    """어댑터로 기준을 읽는다. 반환 (criteria 또는 None, criteria_info)."""
    if fmt not in adapters.ADAPTERS:
        raise CompareError("기준 형식은 %s 중 하나: %r" % (", ".join(sorted(adapters.ADAPTERS)), fmt))
    mod = adapters.ADAPTERS[fmt]
    info = {"sha256": store.file_sha256(path), "source_format": fmt,
            "adapter": {"name": mod.NAME, "version": mod.VERSION} if mod.VERSION else None, "notes": []}
    if info["sha256"] is None:
        raise CompareError("기준 파일 없음: %s" % path)
    try:
        doc, notes = mod.load(path)
    except CriteriaError as exc:
        info["errors"] = exc.errors
        return None, info
    info["notes"] = notes
    return doc, info


def run_compare(criteria_path, run_dir, store_root, out_root, basis="draft", export_path=None, fmt="json",
                now=None):
    """기준 읽기 → 뷰 → 보고 → 파일 쓰기. 반환 {"report", "json_path", "xlsx_path"}.
    analysis.json이 없으면 hazop.review.ReviewError, 쓰기 실패·같은 이름 파일이면 CompareError.
    차단(blocked)도 보고 파일을 쓴다(기준 ID를 알 수 없으면 CompareError)."""
    now = now or store.utc_now()
    if not isinstance(now, str) or not _UTC.match(now):
        raise CompareError("비교 시각이 UTC ISO 형식 아님: %r" % (now,))
    criteria, info = load_criteria(criteria_path, fmt)
    view, reasons = build_view(run_dir, store_root, basis, export_path)
    report = build_report(criteria, view, info, reasons, now)
    if not report["criteria"]["criteria_id"] or not isinstance(report["criteria"]["criteria_id"], str):
        raise CompareError(["기준 ID를 알 수 없어 보고 파일을 만들 수 없음"] + report["reasons"])
    json_path, xlsx_path = write_report(report, criteria, out_root)
    return {"report": report, "json_path": json_path, "xlsx_path": xlsx_path}
