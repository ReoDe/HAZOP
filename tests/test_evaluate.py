"""평가 기준 비교 독립 검증 E1–E15 (기획서/평가기준비교.md §7). 실행: python -m unittest tests.test_evaluate

- E1–E12·E15: 고정 비교 입력 뷰(§7.2)와 가상 기준(데이터/평가기준/)만 쓴다. 분석 실행·검토 저장소 없음.
- E13·E14·E3(파일): 실제 최신 분석 실행(출력/분석/region-SNP-M-102-pzr/ 최신)을 임시 폴더에 복사해 쓴다.
  출력/에 실행이 없으면 tests/run_fixture.py의 고정 응답 실행을 쓴다. 저장소의 출력/·자료저장소/에는 쓰지 않는다.
- 네트워크·AI 호출 없음. 기대값은 기획 §7.3 표 그대로.
"""

import contextlib
import copy
import io
import glob
import hashlib
import json
import os
import shutil
import tempfile
import unittest

from openpyxl import Workbook, load_workbook

from hazop import paths
from hazop import review as rv
from hazop.evaluate import (CompareError, build_report, build_view, dumps, load_criteria, run_compare,
                            write_report)
from hazop.evaluate.adapters import xlsx_sheet
from hazop.evaluate.criteria import norm, tag_in_text

REPO = paths.REPO_ROOT
CRIT_DIR = paths.folder("표본", "평가기준")
CRIT_JSON = os.path.join(CRIT_DIR, "criteria-SNP-M-102-pzr-sample.json")
CRIT_XLSX = os.path.join(CRIT_DIR, "criteria-SNP-M-102-pzr-sample.xlsx")
REAL_RUNS = os.path.join(REPO, "출력", "분석", "region-SNP-M-102-pzr")
T1, T2 = "2026-11-06T00:00:00Z", "2026-11-06T00:00:01Z"


def load_sample():
    with open(CRIT_JSON, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- §7.2 고정 비교 입력 뷰
def _sg(*tags):
    return [{"tag": t, "description": ""} for t in tags]


def _scen(sid, cid, tags, cause, cons, sgs):
    return {"scenario_id": sid, "candidate_id": cid, "worksheet_row": None, "cause": cause, "consequence": cons,
            "cause_equipment_tags": tags, "safeguards": sgs, "recommendations": [], "decision": None}


def view_draft():
    devs = [("deviation-p86-d03", "p86-d03", "유량", "없음", "No, Not, or None"),
            ("deviation-p86-d09", "p86-d09", "압력", "증가", "More"),
            ("deviation-p86-d10", "p86-d10", "압력", "감소", "Less"),
            ("deviation-p86-d12", "p86-d12", "온도", "증가", "More")]
    return {
        "analysis_run_id": "analysis-fixture", "analysis_sha256": "0" * 64,
        "region_ref": {"region_id": "region-SNP-M-102-pzr", "region_version": 1},
        "graph_ref": {"graph_id": "graph-SNP-M-102", "graph_version": "v-7ed95b0c74f1"},
        "operating_mode": "normal", "basis": "draft", "export_id": None, "reviews": [], "excluded_by_review": 0,
        "graph_tags": ["RC-L010", "RC-L031", "RC-PIC110", "RC-PSV101", "RC-PSV102", "RC-PT110", "RC-PV101",
                       "RC-PZ01"],
        "deviations": [{"candidate_id": c, "item_id": i, "parameter_ko": p, "guide_word_ko": k, "guide_word_en": e,
                        "selection_status": "selected"} for c, i, p, k, e in devs],
        "scenarios": [
            _scen("scenario-p86-d09-01", "deviation-p86-d09", ["RC-PZ01"],
                  "RC-L010 써지 배관을 통한 냉각재 유입(인서지) 증가", "증기 공간 압축으로 RC-PZ01 압력 상승",
                  _sg("RC-PSV101", "RC-PSV102")),
            _scen("scenario-p86-d09-03", "deviation-p86-d09", ["RC-PIC110"],
                  "RC-PIC110 제어기 출력 오류로 RC-PV101 오동작",
                  "RC-PV101가 조절하는 유입량 이상으로 연결 용기 압력 이탈", _sg("RC-PSV101")),
            _scen("scenario-p86-d09-04", "deviation-p86-d09", ["RC-PV101"],
                  "RC-PV101 개방 실패(정상 닫힘)로 압력 상승 시 유량 공급 불가",
                  "RC-PV101를 통한 압력 상승 억제 기능 상실", _sg("RC-PSV101")),
            _scen("scenario-p86-d10-04", "deviation-p86-d10", ["RC-PV101"],
                  "RC-PV101 오개방 또는 열림 고착(정상 닫힘 밸브)",
                  "RC-PV101를 통한 과도 유입으로 연결 용기 압력 감소·혼합 증가", _sg("RC-PSV101")),
            _scen("scenario-p86-d10-05", "deviation-p86-d10", ["RC-PSV101"],
                  "RC-PSV101 오개방·개방 고착 또는 시트 누설", "보호 대상 압력 감소, 방출 배관 하류로 유체 방출", []),
            _scen("scenario-p86-d12-01", "deviation-p86-d12", ["RC-PZ01"],
                  "RC-PZ01 압력 상승에 따른 포화온도 상승", "RC-PZ01 및 연결 배관 온도 증가", []),
        ],
    }


def view_reviewed():
    v = view_draft()
    v["basis"], v["excluded_by_review"] = "reviewed", 1
    v["scenarios"] = [s for s in v["scenarios"] if s["scenario_id"] != "scenario-p86-d09-03"]
    s3 = [s for s in v["scenarios"] if s["scenario_id"] == "scenario-p86-d09-04"][0]
    s3.update(decision="modify", safeguards=_sg("RC-PSV101", "RC-PSV102"),
              recommendations=["RC-PV101 살수 개방 실패 대비 경보 검토"])
    return v


def _row(crit, rid):
    return [r for d in crit["deviations"] for r in d["rows"] if r["row_id"] == rid][0]


# ---------------------------------------------------------------- §2.2 Excel 양식 (가상 샘플을 손으로 옮긴 행)
META = ["criteria-SNP-M-102-pzr-sample", 1, "region-SNP-M-102-pzr", "normal", "synthetic", "hazop-planner",
        "2026-11-06T00:00:00Z", "[추론]·가상 샘플. 비교 기능 검증용이며 정답이 아님", "PZR=RC-PZ01"]
N = None
SAMPLE_ROWS = [
    ("R06", "p86-d03", "유량", "없음", "써지 배관 막힘", "RC-L010", "막힘|폐색", "가압기 압력 제어 곤란", N, "압력",
     N, N, N, N, N, N, "유량 없음", N),
    ("R01", "p86-d09", "압력", "증가", "인서지로 증기 공간 압축", "PZR", "인서지|유입", "가압기 압력 상승", "RC-PZ01",
     "압력;상승|증가", "RC-PSV101;RC-PSV102", N, N, N, N, N, "압력 증가", N),
    ("R02", "p86-d09", "압력", "증가", "살수 밸브 개방 실패", "RC-PV101", "개방실패|열림실패",
     "압력 상승 억제 실패\n과압으로 POSRV 개방 요구", N, "압력;상승\n과압", "RC-PSV101;RC-PSV102", N,
     "살수 개방 실패 경보 검토", "살수;경보", N, N, "압력 증가", N),
    ("R03", "p86-d09", "압력", "증가", "가압기 히터 제어 오류로 과열", N, "히터", "가압기 압력 상승", N, "압력;상승",
     N, N, N, N, N, N, "압력 증가", N),
    ("R04", N, "압력", "Less", "살수 밸브 오개방", "RC-PV101", "오개방|열림고착", "가압기 압력 감소", N,
     "압력;감소|저하", "없음", N, N, N, N, N, "압력 감소", N),
    ("R05", N, "압력", "Less", "POSRV 시트 누설", "RC-PSV101", "시트누설|오개방", "RC-L031로 냉각재 방출", "RC-L031",
     "방출", N, "경보", N, N, N, N, "압력 감소", N),
]


def write_sheet(path, meta=META, rows=SAMPLE_ROWS):
    """§2.2 양식 Excel을 쓴다. 데이터/평가기준/의 샘플 Excel도 이 함수로 만들었다."""
    wb = Workbook()
    ws = wb.active
    ws.title = xlsx_sheet.SHEET
    for i, (label, value) in enumerate(zip(xlsx_sheet.META_LABELS, meta), 1):
        ws.cell(row=i, column=1, value=label)
        ws.cell(row=i, column=2, value=value)
    ws.cell(row=1, column=3, value="가상·[추론] 샘플 — 비교 기능 검증용이며 정답이 아님(MVP 성공 판단에 쓰지 않음)")
    for c, h in enumerate(xlsx_sheet.HEADERS, 1):
        ws.cell(row=xlsx_sheet.HEADER_ROW, column=c, value=h)
    for r, values in enumerate(rows, xlsx_sheet.FIRST_ROW):
        for c, v in enumerate(values, 1):
            if v is not None:
                ws.cell(row=r, column=c, value=v)
    wb.save(path)


def fill_defaults(doc):
    doc = copy.deepcopy(doc)
    for d in doc["deviations"]:
        d.setdefault("expected", "scenarios")
        for r in d["rows"]:
            r.setdefault("required", True)
            r.setdefault("recommendations", [])
            r.setdefault("safeguards", None)
    return doc


# ---------------------------------------------------------------- E1–E12, E15 (뷰 고정 사례)
class FixtureCases(unittest.TestCase):
    def report(self, crit=None, view=None, **kw):
        return build_report(crit if crit is not None else load_sample(), view or view_draft(), now=T1, **kw)

    def test_E1_metrics(self):
        rep = self.report()
        self.assertEqual(rep["status"], "ok", rep["reasons"])
        pairs = sorted((p["row_id"], p["scenario_id"]) for p in rep["pairs"])
        self.assertEqual(pairs, [("R01", "scenario-p86-d09-01"), ("R02", "scenario-p86-d09-04"),
                                 ("R04", "scenario-p86-d10-04"), ("R05", "scenario-p86-d10-05")])
        m = rep["metrics"]
        self.assertEqual((m["counts"]["M"], m["counts"]["Mc"]), (4, 4))
        self.assertEqual(m["deviation_recall"], 0.666667)
        self.assertEqual(m["cause_recall"], 0.666667)
        self.assertEqual(m["cause_precision"], 0.8)
        self.assertEqual(m["consequence_match"], 0.6)
        self.assertEqual(m["safeguard_match"], 0.6)
        self.assertEqual(m["recommendation_match"], "not_evaluated")
        self.assertEqual(rep["criteria_warnings"], [])

    def test_E1a_missing(self):
        miss = self.report()["missing"]
        self.assertEqual([(d["candidate_id"], d["reason"]) for d in miss["deviations"]],
                         [("deviation-p86-d03", "no_scenario")])
        self.assertEqual(sorted((r["row_id"], r["reason"]) for r in miss["rows"]),
                         [("R03", "no_keyword_match"), ("R06", "deviation_not_reproduced")])
        self.assertEqual(sorted((c["row_id"], c["index"], c["text"]) for c in miss["consequences"]),
                         [("R02", 2, "과압으로 POSRV 개방 요구"), ("R05", 1, "RC-L031로 냉각재 방출")])
        self.assertEqual(sorted((g["row_id"], g["tag"], json.dumps(g["keywords"], ensure_ascii=False))
                                for g in miss["safeguards"]),
                         [("R02", "RC-PSV102", "null"), ("R05", None, '[["경보"]]')])
        self.assertEqual(miss["recommendations"], [])

    def test_E1b_extra(self):
        extra = self.report()["extra"]
        self.assertEqual(extra["deviations"], [{"candidate_id": "deviation-p86-d12",
                                                "scenario_ids": ["scenario-p86-d12-01"]}])
        self.assertEqual([s["scenario_id"] for s in extra["scenarios"]], ["scenario-p86-d09-03"])
        self.assertEqual([(g["row_id"], g["scenario_id"], g["tag"]) for g in extra["safeguards"]],
                         [("R04", "scenario-p86-d10-04", "RC-PSV101")])

    def test_E1c_basis(self):
        rep = self.report()
        r01 = [p for p in rep["pairs"] if p["row_id"] == "R01"][0]
        self.assertEqual(r01["score"], 11)  # 별칭 PZR → RC-PZ01 설비 1개 + 키워드 그룹 1개
        crit = load_sample()
        crit["tag_aliases"] = {}
        crit["deviations"][1]["rows"][0]["cause"]["equipment"] = ["PZR"]
        self.assertNotIn("R01", [p["row_id"] for p in self.report(crit)["pairs"]])  # 별칭 없으면 대응 없음
        self.assertNotIn("scenario-p86-d09-03", [p["scenario_id"] for p in rep["pairs"]])  # S2는 원인 설비가 RC-PIC110
        self.assertIn("R04", [p["row_id"] for p in rep["pairs"]])  # d10: 기준 'Less' = 후보 guide_word_en

    def test_E2_reviewed(self):
        rep = self.report(view=view_reviewed())
        m = rep["metrics"]
        self.assertEqual(rep["target"]["excluded_by_review"], 1)
        self.assertEqual(m["cause_precision"], 1.0)
        self.assertEqual(m["safeguard_match"], 0.8)
        self.assertEqual(m["recommendation_match"], 1.0)
        e1 = self.report()["metrics"]
        for k in ("deviation_recall", "cause_recall", "consequence_match"):
            self.assertEqual(m[k], e1[k])

    def test_E3_determinism_memory(self):
        a, b = self.report(), build_report(load_sample(), view_draft(), now=T2)
        strip = lambda r: dumps({k: v for k, v in r.items() if k != "compared_at"})  # noqa: E731
        self.assertEqual(strip(a), strip(b))
        self.assertEqual(a["comparison_id"], b["comparison_id"])
        self.assertTrue(a["comparison_id"].startswith("compare-") and len(a["comparison_id"]) == 20)

    def test_E4_region_mismatch(self):
        crit = load_sample()
        crit["region_id"] = "region-OTHER"
        rep = self.report(crit)
        self.assertEqual(rep["status"], "blocked")
        self.assertIsNone(rep["metrics"])

    def test_E5_format_errors(self):
        crit = load_sample()
        _row(crit, "R02")["row_id"] = "R01"
        rep = self.report(crit)
        self.assertEqual(rep["status"], "blocked")
        self.assertTrue(any("R01" in r and "중복" in r for r in rep["reasons"]), rep["reasons"])
        crit = load_sample()
        del _row(crit, "R03")["cause"]["keywords"]
        rep = self.report(crit)
        self.assertEqual(rep["status"], "blocked")
        self.assertTrue(any("R03" in r for r in rep["reasons"]), rep["reasons"])
        crit = load_sample()
        _row(crit, "R04")["cause"]["keywords"] = [[]]
        rep = self.report(crit)
        self.assertEqual(rep["status"], "blocked")
        self.assertTrue(any("R04" in r for r in rep["reasons"]), rep["reasons"])

    def test_E6_alias_chain(self):
        crit = load_sample()
        crit["tag_aliases"] = {"A": "B", "B": "RC-PZ01"}
        rep = self.report(crit)
        self.assertEqual(rep["status"], "blocked")
        self.assertTrue(any("연쇄" in r for r in rep["reasons"]), rep["reasons"])

    def test_E7_not_in_catalog(self):
        crit = load_sample()
        crit["deviations"].append({"deviation_ref": {"parameter": "누출", "guide_word": "있음"}, "rows": [
            {"row_id": "R07", "cause": {"text": "배관 누출", "keywords": [["누출"]]},
             "consequences": [{"text": "냉각재 상실", "keywords": [["냉각재"]]}]}]})
        rep = self.report(crit)
        self.assertEqual(rep["status"], "ok")
        self.assertIn("not_in_catalog", [d["reason"] for d in rep["missing"]["deviations"]])
        m = rep["metrics"]
        self.assertEqual((m["deviation_recall"], m["cause_recall"], m["cause_precision"]), (0.5, 0.571429, 0.8))

    def test_E8_tag_not_in_graph(self):
        crit = load_sample()
        _row(crit, "R01")["cause"]["equipment"] = ["RC-PZ99"]
        rep = self.report(crit)
        w = [(x["kind"], x.get("tag") or x.get("alias")) for x in rep["criteria_warnings"]]
        self.assertEqual(sorted(w), [("alias_unused", "PZR"), ("tag_not_in_graph", "RC-PZ99")])
        self.assertIn(("R01", "no_equipment_match"), [(r["row_id"], r["reason"]) for r in rep["missing"]["rows"]])
        self.assertIn("scenario-p86-d09-01", [s["scenario_id"] for s in rep["extra"]["scenarios"]])
        m = rep["metrics"]
        self.assertEqual((m["cause_recall"], m["cause_precision"], m["consequence_match"], m["safeguard_match"],
                          m["deviation_recall"]), (0.5, 0.6, 0.5, 0.333333, 0.666667))

    def test_E9_tag_boundary(self):
        self.assertFalse(tag_in_text(norm("RC-L010"), norm("RC-L010-T3 부근 누설")))
        self.assertTrue(tag_in_text(norm("RC-PV101"), norm("RC-PV101를 통한 압력 상승")))  # 한글 조사는 경계
        crit, view = load_sample(), view_draft()
        _row(crit, "R01")["consequences"] = [{"text": "써지 배관 누설", "equipment": ["RC-L010"],
                                              "keywords": [["누설"]]}]
        view["scenarios"][0]["consequence"] = "RC-L010-T3 부근 누설"
        r01 = [p for p in self.report(crit, view)["pairs"] if p["row_id"] == "R01"][0]
        self.assertEqual(r01["consequences"], [False])

    def test_E10_xlsx_adapter(self):
        conv, info = load_criteria(CRIT_XLSX, "xlsx_sheet")
        self.assertIsNotNone(conv, info.get("errors"))
        want = fill_defaults(load_sample())
        r05 = _row(want, "R05")
        self.assertEqual(r05["safeguards"][0].pop("text"), "저압 경보 후 운전원 조치")  # Excel이 받지 않는 유일한 차이
        self.assertEqual(dumps(fill_defaults(conv)), dumps(want))
        rep = build_report(conv, view_draft(), info, now=T1)
        self.assertEqual(rep["metrics"], self.report()["metrics"])
        self.assertEqual(rep["criteria"]["adapter"], {"name": "xlsx_sheet", "version": xlsx_sheet.VERSION})

    def _xlsx_blocked(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "c.xlsx")
            write_sheet(p, rows=rows)
            conv, info = load_criteria(p, "xlsx_sheet")
        rep = build_report(conv, view_draft(), info, now=T1)
        self.assertEqual(rep["status"], "blocked")
        return rep["reasons"]

    def test_E11_line_count(self):
        rows = list(SAMPLE_ROWS)
        r = list(rows[2])
        r[9] = "압력;상승"  # H열 2줄, J열 1줄
        rows[2] = tuple(r)
        self.assertTrue(any("줄 수" in x for x in self._xlsx_blocked(rows)))

    def test_E12_formula(self):
        rows = list(SAMPLE_ROWS)
        r = list(rows[1])
        r[15] = "=1+1"
        rows[1] = tuple(r)
        self.assertTrue(any("수식" in x for x in self._xlsx_blocked(rows)))

    def test_E15_synthetic_notice(self):
        notice = "가상 기준 — MVP 성공 판단에 쓰지 않음"  # 기획 §2.1·§7.3 E15 고정 문구(구현 상수를 쓰지 않음)
        rep = self.report()
        self.assertEqual(rep["notice"], notice)
        with tempfile.TemporaryDirectory() as tmp:
            _jp, xp = write_report(rep, load_sample(), tmp)
            ws = load_workbook(xp)["요약"]
            self.assertEqual((ws["A2"].value, ws["B2"].value), ("주의", notice))
        crit = load_sample()
        crit["provenance"]["kind"] = "user"
        self.assertIsNone(self.report(crit)["notice"])


# ---------------------------------------------------------------- 재작업 1회차 보강
def _paths(o, p=()):
    yield p
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _paths(v, p + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _paths(v, p + (i,))


def _set(doc, path, value):
    if not path:
        return value
    t = doc
    for k in path[:-1]:
        t = t[k]
    t[path[-1]] = value
    return doc


class Hardening(unittest.TestCase):
    def test_report_name_no_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a", "b", "c", "out")
            crit = load_sample()
            crit["criteria_id"] = "/../../../ESCAPED"
            rep = build_report(crit, view_draft(), now=T1)
            with self.assertRaises(CompareError):
                write_report(rep, crit, out)
            crit = load_sample()
            crit["criteria_version"] = "/../../../ESCAPED"
            rep = build_report(crit, view_draft(), now=T1)
            self.assertEqual(rep["status"], "blocked")
            jp, xp = write_report(rep, crit, out)
            run_dir = os.path.join(out, "region-SNP-M-102-pzr", "analysis-fixture")
            self.assertEqual({os.path.dirname(jp), os.path.dirname(xp)}, {run_dir})
            self.assertIn("-vX-", os.path.basename(jp))
            found = [f for _dp, dn, fn in os.walk(tmp) for f in dn + fn if "ESCAPED" in f]
            self.assertEqual(found, [])

    def test_type_fuzz_blocks_without_exception(self):
        bad = [None, [], {}, 1, 1.5, True, "", [[]], [1], {"a": 1}, [None], [[1]], [[""]], [{}]]
        base = load_sample()
        for p in list(_paths(base)):
            for b in bad:
                with self.subTest(path=p, value=b):
                    rep = build_report(_set(copy.deepcopy(base), p, b), view_draft(), now=T1)  # 예외 없음
                    self.assertIn(rep["status"], ("ok", "blocked"))
        for p, b in ((("deviations", 0, "deviation_ref"), 1), (("deviations", 0, "rows", 0, "row_id"), []),
                     (("deviations", 1, "rows"), {}), (("criteria_version",), "1"), (("deviations",), None),
                     ((), [])):
            rep = build_report(_set(copy.deepcopy(base), p, b), view_draft(), now=T1)
            self.assertEqual(rep["status"], "blocked", p)

    def test_xlsx_datetime_version_blocks_and_writes_json(self):
        """B2 기준 버전이 날짜·시간형이면 예외 없이 차단되고 JSON·Excel 보고가 모두 쓰인다(총괄 직접 수정)."""
        import datetime
        for v in (datetime.datetime(2026, 1, 1), datetime.time(1, 1), datetime.timedelta(days=1)):
            with self.subTest(v=v), tempfile.TemporaryDirectory() as tmp:
                p = os.path.join(tmp, "c.xlsx")
                meta = list(META)
                meta[1] = v
                write_sheet(p, meta=meta)
                conv, info = load_criteria(p, "xlsx_sheet")
                crit = conv if conv is not None else load_sample()
                if conv is None:
                    crit["criteria_version"] = str(v)
                rep = build_report(crit, view_draft(), now=T1)
                self.assertEqual(rep["status"], "blocked")
                jp, xp = write_report(rep, crit, os.path.join(tmp, "out"))
                self.assertTrue(os.path.isfile(jp) and os.path.isfile(xp))

    def _sheet(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "c.xlsx")
            write_sheet(p, rows=rows)
            return load_criteria(p, "xlsx_sheet")

    def test_xlsx_multiline_keeps_leading_newline(self):
        rows = list(SAMPLE_ROWS)
        r = list(rows[1])  # R01: 결과 2줄, 두 번째 줄에만 설비
        r[7], r[8], r[9] = "가압기 압력 상승\n가압기 수위 상승", "\nRC-PZ01", "압력\n수위"
        rows[1] = tuple(r)
        conv, info = self._sheet(rows)
        self.assertIsNotNone(conv, info.get("errors"))
        cons = _row(conv, "R01")["consequences"]
        self.assertEqual(len(cons), 2)
        self.assertNotIn("equipment", cons[0])
        self.assertEqual(cons[1]["equipment"], ["RC-PZ01"])

    def test_xlsx_O_and_R_columns(self):
        rows = list(SAMPLE_ROWS)
        r = list(rows[3])
        r[14] = "N"  # R03 O열 필수 N
        rows[3] = tuple(r)
        rows.append(("R99", "p86-d12", "온도", "증가") + (N,) * 12 + ("온도 증가", "시나리오 없음"))
        conv, info = self._sheet(rows)
        self.assertIsNotNone(conv, info.get("errors"))
        self.assertIs(_row(conv, "R03")["required"], False)
        d12 = [d for d in conv["deviations"] if d["deviation_ref"].get("item_id") == "p86-d12"][0]
        self.assertEqual((d12["expected"], d12["rows"]), ("no_scenario", []))
        bad = list(rows)
        bad[-1] = ("R99", "p86-d12", "온도", "증가", "원인 있음") + (N,) * 11 + ("온도 증가", "시나리오 없음")
        conv, info = self._sheet(bad)
        rep = build_report(conv, view_draft(), info, now=T1)
        self.assertEqual(rep["status"], "blocked")
        self.assertTrue(any("E–P" in x for x in rep["reasons"]), rep["reasons"])
        bad = list(SAMPLE_ROWS)
        r = list(bad[3])
        r[14] = "X"  # O열 허용값 밖
        bad[3] = tuple(r)
        conv, info = self._sheet(bad)
        self.assertEqual(build_report(conv, view_draft(), info, now=T1)["status"], "blocked")

    def test_expected_no_scenario(self):
        crit = load_sample()
        crit["deviations"][0] = {"deviation_ref": {"item_id": "p86-d03", "parameter": "유량", "guide_word": "없음"},
                                 "expected": "no_scenario", "rows": []}
        crit["deviations"].append({"deviation_ref": {"item_id": "p86-d12", "parameter": "온도", "guide_word": "증가"},
                                   "expected": "no_scenario", "rows": []})
        rep = build_report(crit, view_draft(), now=T1)
        self.assertEqual(rep["status"], "ok", rep["reasons"])
        self.assertEqual([(d["candidate_id"], d["reason"]) for d in rep["missing"]["deviations"]],
                         [("deviation-p86-d12", "unexpected_scenarios")])
        c = rep["metrics"]["counts"]
        self.assertEqual((c["Dc"], c["Dr"], c["Rc"], c["So"]), (4, 3, 5, 6))  # d03 재현(시나리오 0), d12 미재현
        self.assertEqual(rep["metrics"]["deviation_recall"], 0.75)
        self.assertIn("scenario-p86-d12-01", [s["scenario_id"] for s in rep["extra"]["scenarios"]])
        self.assertEqual(rep["extra"]["deviations"], [])

    def test_required_false_optional_matched(self):
        crit = load_sample()
        r03 = _row(crit, "R03")
        r03["required"] = False
        r03["cause"] = {"text": "제어기 출력 오류", "equipment": ["RC-PIC110"], "keywords": [["오동작"]]}
        rep = build_report(crit, view_draft(), now=T1)
        m = rep["metrics"]
        self.assertEqual((m["counts"]["optional_matched"], m["counts"]["Mc"], m["counts"]["Rc"]), (1, 5, 5))
        self.assertEqual((m["cause_precision"], m["cause_recall"]), (1.0, 0.8))
        self.assertEqual(rep["extra"]["scenarios"], [])
        self.assertNotIn("R03", [r["row_id"] for r in rep["missing"]["rows"]])
        self.assertEqual(m["consequence_match"], 0.6)  # 선택 행은 결과 일치율 분모에 넣지 않음


# ---------------------------------------------------------------- E13, E14, E3(파일): 실제 실행 사본
def _latest_real_run():
    runs = sorted(d for d in glob.glob(os.path.join(REAL_RUNS, "analysis-*"))
                  if os.path.isfile(os.path.join(d, "analysis.json")))
    return runs[-1] if runs else None


def _snapshot(root):
    out = {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as fh:
                out[p] = (os.path.getmtime(p), hashlib.sha256(fh.read()).hexdigest())
    return out


class RunCopyCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _latest_real_run()
        if cls.src is None:
            from tests.run_fixture import fresh_run_dir
            cls.src = fresh_run_dir()
        cls.before = _snapshot(cls.src)
        cls.out_existed = os.path.exists(os.path.join(REPO, "출력", "평가비교"))
        cls.tmp = tempfile.mkdtemp(prefix="hazop-evaluate-")
        cls.run_dir = os.path.join(cls.tmp, "runs", os.path.basename(cls.src))
        shutil.copytree(cls.src, cls.run_dir)
        cls.store = os.path.join(cls.tmp, "store")
        os.makedirs(cls.store)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_E13_view_builder(self):
        view, reasons = build_view(self.run_dir, self.store, "draft")
        self.assertEqual(reasons, [])
        with open(os.path.join(self.run_dir, "analysis.json"), "rb") as fh:
            raw = fh.read()
        doc = json.loads(raw.decode("utf-8"))
        selected = {c["candidate_id"] for c in doc["candidates"] if c["selection_status"] == "selected"}
        scens = [s for s in doc["scenarios"] if s["candidate_id"] in selected]
        self.assertEqual(len(view["scenarios"]), len(scens))
        for s, v in zip(scens, view["scenarios"]):
            merged = rv.merge_display(s, None)
            self.assertEqual((v["scenario_id"], v["cause"], v["consequence"]),
                             (s["scenario_id"], merged["cause"]["value"], merged["consequence"]["value"]))
        self.assertEqual(view["analysis_sha256"], hashlib.sha256(raw).hexdigest())
        with open(os.path.join(self.run_dir, "inputs", "graph.json"), encoding="utf-8") as fh:
            graph = json.load(fh)
        self.assertEqual(view["graph_tags"], sorted({norm(n["tag"]) for n in graph["nodes"] if n.get("tag")}))
        self.assertEqual((view["reviews"], view["excluded_by_review"]), ([], 0))
        self.assertEqual(_snapshot(self.src), self.before)  # 원본 실행 폴더는 바뀌지 않음
        self.assertEqual(os.path.exists(os.path.join(REPO, "출력", "평가비교")), self.out_existed)

    def test_E14_export_hash_mismatch(self):
        from hazop.export import export_worksheet
        run = os.path.join(self.tmp, "e14", os.path.basename(self.src))
        shutil.copytree(self.src, run)
        store_root = os.path.join(self.tmp, "e14-store")
        res = export_worksheet(run, store_root, os.path.join(self.tmp, "e14-ws"), now=T1)
        out = os.path.join(self.tmp, "e14-out")
        ok = run_compare(CRIT_JSON, run, store_root, out, export_path=res["export_record_path"], now=T1)
        self.assertEqual(ok["report"]["target"]["export_id"], res["record"]["export_id"])  # 대조군: 해시 같으면 비교함
        self.assertEqual(ok["report"]["reasons"], [])
        p = os.path.join(run, "analysis.json")
        with open(p, "rb") as fh:
            data = fh.read()
        with open(p, "wb") as fh:
            fh.write(data[:-1] + (b" " if data[-1:] != b" " else b"\n"))  # 마지막 1바이트 변경(JSON은 유효)
        bad = run_compare(CRIT_JSON, run, store_root, out, export_path=res["export_record_path"], now=T2)
        self.assertEqual(bad["report"]["status"], "blocked")
        self.assertTrue(any("해시" in r for r in bad["report"]["reasons"]), bad["report"]["reasons"])
        self.assertIsNone(bad["report"]["metrics"])

    def test_E3_files_no_overwrite(self):
        import scripts.compare_criteria as cli
        work = os.path.join(self.tmp, "e3-work")
        old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = work
        try:
            args = ["--criteria", CRIT_JSON, "--run", self.run_dir, "--store-root", self.store]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(args + ["--now", T1]), 0)
                self.assertEqual(cli.main(args + ["--now", T2]), 0)
            files = sorted(glob.glob(os.path.join(work, "출력", "평가비교", "*", "*", "*.json")))
            self.assertEqual(len(files), 2)
            reps = []
            for f in files:
                with open(f, encoding="utf-8") as fh:
                    rep = json.load(fh)
                self.assertTrue(os.path.isfile(f[:-5] + ".xlsx"))
                reps.append(dumps({k: v for k, v in rep.items() if k != "compared_at"}))
            self.assertEqual(reps[0], reps[1])
            mtime = os.path.getmtime(files[0])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(args + ["--now", T1]), 1)  # 같은 시각으로 다시 쓰면 실패
            self.assertEqual(os.path.getmtime(files[0]), mtime)
            self.assertEqual(len(glob.glob(os.path.join(work, "출력", "평가비교", "*", "*", "*"))), 4)
        finally:
            if old is None:
                os.environ.pop(paths.ENV_WORK_ROOT, None)
            else:
                os.environ[paths.ENV_WORK_ROOT] = old


if __name__ == "__main__":
    unittest.main()
