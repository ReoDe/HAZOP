"""T3 W2 평가 하네스·W3 PDF 어댑터 검사 (QA용). 종료 코드 0 = 전부 통과.

인자 없이 실행: 가상 소형 픽스처와 샘플 6세트(drawio 추출 결과, 메모리에서만 사용)로
  1) 정답지끼리 비교 시 객체·관계·태그 F1=1, GED=0
  2) 의도적 오류 주입(태그 오타, 객체 누락, 연결 뒤바꿈, 객체 이동, 좌표 이동)별 기대 감점
  3) 좌표 정규화(이동·배율 transform), 좌표계 불일치 시 blocked
  4) 결정성(두 번 실행·입력 순서 뒤집기 시 JSON 동일)
을 확인한다. 이어서 W3(pdfplumber가 있을 때만, 없으면 건너뜀을 출력): 샘플 6세트 PDF를 어댑터로 읽어
  5) 구조 검증 blocker 0, drawio 추출 결과와 같은 스키마 키, 두 번 실행 결과 동일
  6) 기준점 좌표 정렬(align.py) status ok와 잔차, 정답 대비 평가 status ok
를 확인하고 지표 표를 출력한다. 지표 목표치는 정하지 않았다(측정값만 기록).
이어서 W4(OpenCV·rapidocr가 있을 때만, 없으면 건너뜀을 출력): 샘플 6세트 PNG(`.drawio.png` 제외, 결정 D1)를
래스터 어댑터로 읽어 5)·6)과 같은 검사와 샘플별 품질 하한(RASTER_QUALITY_FLOORS)을 확인한다.

평가 실행: python scripts/check_adapter.py --truth 정답.json --candidate 후보.json
           [--transform 변환.json] [--out 폴더]   → 폴더에 evaluation.json·evaluation.md
W3 결과 저장: python scripts/check_adapter.py --pdf-out 폴더
           → 폴더/<도면>/{extraction,alignment,evaluation}.json·evaluation.md, 폴더/summary.md
W4 결과 저장: python scripts/check_adapter.py --raster-out 폴더 (같은 구성)
"""

import argparse
import copy
import glob
import importlib.util
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.extract.adapters import align  # noqa: E402
from hazop.extract.adapters import evaluation as ev  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
from hazop.extract.adapters import raster  # noqa: E402  (cv2는 함수 안에서만 읽는다)
from hazop.graph import build as graph_build  # noqa: E402

FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "adapter", "truth_small.json")
SAMPLE_GLOB = os.path.join(REPO_ROOT, "참고자료", "P&ID 도면 샘플", "*", "*.drawio")
FAR = (3000.0, 2000.0)  # 페이지 밖으로 옮기는 거리(어떤 정답 bbox와도 겹치지 않음)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------- 오류 주입 (입력을 바꾸지 않고 사본을 돌려준다) ----------

def _degree(ext, local_id):
    return sum(1 for r in ext["relations"] for e in r["endpoints"] if e.get("node_local_id") == local_id)


def _map_box(x, y, w, h, dx, dy, sx, sy):
    """후보 좌표 = 정답 × s + d. 음수 s(반전)면 양 끝을 다시 정렬해 양수 폭·높이로 둔다."""
    x1, x2 = sorted((x * sx + dx, (x + w) * sx + dx))
    y1, y2 = sorted((y * sy + dy, (y + h) * sy + dy))
    return x1, y1, x2 - x1, y2 - y1


def _shift_node(ext, local_id, dx, dy, sx=1.0, sy=1.0):
    for loc in ext.get("source_locations") or []:
        if loc.get("local_id") == local_id:
            loc["bbox"] = list(_map_box(*loc["bbox"], dx, dy, sx, sy))
    for n in ext["nodes"]:
        if n["local_id"] == local_id and n.get("geometry"):
            g = n["geometry"]
            x, y, w, h = _map_box(g["x"], g["y"], g["width"], g["height"], dx, dy, sx, sy)
            n["geometry"] = {"x": x, "y": y, "width": w, "height": h}


def pick_text_node(ext):
    """보이는 글자가 있고 연결이 1개 이상인 첫 노드(local_id 순)."""
    for n in sorted(ext["nodes"], key=lambda n: n["local_id"]):
        if ev.normalize_text(n.get("label_text")) and _degree(ext, n["local_id"]) > 0:
            return n["local_id"]
    raise ValueError("글자·연결이 있는 노드 없음")


def inject_tag_typo(ext, local_id):
    out = copy.deepcopy(ext)
    for n in out["nodes"]:
        if n["local_id"] == local_id:
            text = n["label_text"]
            last = text.rstrip()[-1]
            n["label_text"] = text.rstrip()[:-1] + ("Q" if last != "Q" else "Z")
    return out


def inject_node_drop(ext, local_id):
    out = copy.deepcopy(ext)
    out["nodes"] = [n for n in out["nodes"] if n["local_id"] != local_id]
    out["source_locations"] = [s for s in out.get("source_locations") or [] if s.get("local_id") != local_id]
    out["relations"] = [r for r in out["relations"]
                        if all(e.get("node_local_id") != local_id for e in r["endpoints"])]
    return out


def _rel_keys(ext):
    return {(tuple(sorted(e.get("node_local_id") for e in r["endpoints"])), r["kind"]) for r in ext["relations"]}


def pick_swap(ext):
    """끝점 4개가 모두 다르고, 바꾼 쌍이 정답에 없는 같은 kind 관계 2개(local_id 순 첫 조합)."""
    rels = sorted(ext["relations"], key=lambda r: r["local_id"])
    keys = _rel_keys(ext)
    for i, r1 in enumerate(rels):
        for r2 in rels[i + 1:]:
            if r1["kind"] != r2["kind"]:
                continue
            a, b = (e.get("node_local_id") for e in r1["endpoints"])
            c, d = (e.get("node_local_id") for e in r2["endpoints"])
            if None in (a, b, c, d) or len({a, b, c, d}) != 4:
                continue
            if (tuple(sorted((a, d))), r1["kind"]) in keys or (tuple(sorted((c, b))), r1["kind"]) in keys:
                continue
            return r1["local_id"], r2["local_id"]
    raise ValueError("뒤바꿀 관계 쌍 없음")


def inject_relation_swap(ext, rel1, rel2):
    """두 관계의 target 끝점을 맞바꾼다: a-b, c-d → a-d, c-b."""
    out = copy.deepcopy(ext)
    r = {x["local_id"]: x for x in out["relations"]}
    e1, e2 = r[rel1]["endpoints"][1], r[rel2]["endpoints"][1]
    e1["node_local_id"], e2["node_local_id"] = e2["node_local_id"], e1["node_local_id"]
    return out


def inject_node_move(ext, local_id, dx=FAR[0], dy=FAR[1]):
    out = copy.deepcopy(ext)
    _shift_node(out, local_id, dx, dy)
    return out


def inject_page_transform(ext, dx, dy, sx=1.0, sy=1.0, coordinate_space=None, unit=None):
    """모든 좌표를 후보 좌표 = 정답 × s + d 로 바꾼다(다른 좌표계 후보 흉내)."""
    out = copy.deepcopy(ext)
    for n in out["nodes"]:
        _shift_node(out, n["local_id"], dx, dy, sx, sy)
    if coordinate_space or unit:
        out["coordinate_system"] = dict(out.get("coordinate_system") or {})
        if coordinate_space:
            out["coordinate_system"]["coordinate_space"] = coordinate_space
        if unit:
            out["coordinate_system"]["unit"] = unit
    return out


def reverse_order(ext):
    out = copy.deepcopy(ext)
    for key in ("nodes", "relations", "source_locations"):
        out[key] = list(reversed(out.get(key) or []))
    return out


# ---------- 기대 감점 ----------

def _f1(tp, fp, fn):
    """기대 P/R/F1을 검증 대상(ev.prf)과 독립으로 직접 계산한다. 이 검사의 시나리오는 분모가 0이 아니다."""
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(tp / (tp + fp), 6),
            "recall": round(tp / (tp + fn), 6), "f1": round(2 * tp / (2 * tp + fp + fn), 6)}


def scenarios(truth):
    """(이름, 후보, transform, 기대값 dict). 기대값 키: objects·relations·tags(prf dict), status, ged_zero."""
    n_nodes, n_rel = len(truth["nodes"]), len(truth["relations"])
    visible = sum(1 for n in truth["nodes"] if ev.normalize_text(n.get("label_text")))
    node = pick_text_node(truth)
    k = _degree(truth, node)
    r1, r2 = pick_swap(truth)
    perfect_o, perfect_r, perfect_t = _f1(n_nodes, 0, 0), _f1(n_rel, 0, 0), _f1(visible, 0, 0)
    sx, dx = 2.0, 20.0  # PNG 내보내기 흉내(배율 2, 테두리)
    return [
        ("self", copy.deepcopy(truth), None,
         {"objects": perfect_o, "relations": perfect_r, "tags": perfect_t, "ged_zero": True}),
        ("tag_typo", inject_tag_typo(truth, node), None,
         {"objects": perfect_o, "relations": perfect_r, "tags": _f1(visible - 1, 1, 1), "ged_zero": True}),
        ("node_drop", inject_node_drop(truth, node), None,
         {"objects": _f1(n_nodes - 1, 0, 1), "relations": _f1(n_rel - k, 0, k), "tags": _f1(visible - 1, 0, 1),
          "ged_zero": False}),
        ("relation_swap", inject_relation_swap(truth, r1, r2), None,
         {"objects": perfect_o, "relations": _f1(n_rel - 2, 2, 2), "tags": perfect_t}),
        ("node_move", inject_node_move(truth, node), None,
         {"objects": _f1(n_nodes - 1, 1, 1), "relations": _f1(n_rel - k, k, k), "tags": _f1(visible - 1, 1, 1),
          "ged_zero": True}),
        ("page_shift_no_transform", inject_page_transform(truth, *FAR), None,
         {"objects": _f1(0, n_nodes, n_nodes), "relations": _f1(0, n_rel, n_rel), "tags": _f1(0, visible, visible),
          "ged_zero": True}),
        ("page_shift_with_transform", inject_page_transform(truth, *FAR),
         {"scale": 1.0, "offset": [-FAR[0], -FAR[1]]},
         {"objects": perfect_o, "relations": perfect_r, "tags": perfect_t, "ged_zero": True}),
        ("scale_with_transform", inject_page_transform(truth, dx, dx, sx, sx, "image_px", "px"),
         {"scale": [1 / sx, 1 / sx], "offset": [-dx / sx, -dx / sx]},
         {"objects": perfect_o, "relations": perfect_r, "tags": perfect_t, "ged_zero": True}),
        ("flip_y_with_transform", inject_page_transform(truth, 0.0, 1200.0, 1.0, -1.0, "pdf_page_pt", "pt"),
         {"scale": [1.0, -1.0], "offset": [0.0, 1200.0]},
         {"objects": perfect_o, "relations": perfect_r, "tags": perfect_t, "ged_zero": True}),
        ("coordinate_mismatch_no_transform", inject_page_transform(truth, dx, dx, sx, sx, "image_px", "px"), None,
         {"status": "blocked"}),
        ("reversed_order", reverse_order(truth), None,
         {"objects": perfect_o, "relations": perfect_r, "tags": perfect_t, "ged_zero": True}),
    ]


def check_result(name, result, exp):
    """기대값과 다른 항목 목록(빈 목록이면 통과)."""
    errs = []
    if result["status"] != exp.get("status", "ok"):
        return ["%s: status %s != %s" % (name, result["status"], exp.get("status", "ok"))]
    if result["status"] != "ok":
        return errs
    for part in ("objects", "relations", "tags"):
        got = {key: result[part][key] for key in ("tp", "fp", "fn", "precision", "recall", "f1")}
        if got != exp[part]:
            errs.append("%s: %s %s != 기대 %s" % (name, part, got, exp[part]))
    g = result["ged"]
    is_zero = g["status"] == "exact" and g["value"] == 0
    if exp.get("ged_zero") is True and not is_zero:
        errs.append("%s: GED 0 기대, 실제 %s" % (name, g))
    if exp.get("ged_zero") is False and is_zero:
        errs.append("%s: GED>0 또는 미계산 기대, 실제 0" % name)
    return errs


def run_suite(label, truth):
    errs, base_json = [], None
    for name, cand, tf, exp in scenarios(truth):
        first = ev.dumps(ev.evaluate(truth, cand, tf))
        second = ev.dumps(ev.evaluate(copy.deepcopy(truth), copy.deepcopy(cand), tf))
        result = json.loads(first)
        if first != second:
            errs.append("%s: 두 번 실행 결과 다름" % name)
        errs += check_result(name, result, exp)
        if name == "self":
            base_json = first
        if name == "reversed_order" and first != base_json:
            errs.append("%s: 입력 순서를 뒤집으면 JSON이 달라짐" % name)
        if result["status"] == "ok":
            o, r, g = result["objects"], result["relations"], result["ged"]
            print("  %-34s obj F1 %-8s rel F1 %-8s tag %d/%d GED %s%s"
                  % (name, o["f1"], r["f1"], result["tags"]["exact"], result["tags"]["visible_total"],
                     g["status"], "" if g["value"] is None else "=%s" % g["value"]))
        else:
            print("  %-34s %s" % (name, result["status"]))
    status = "통과" if not errs else "실패 %d건" % len(errs)
    print("[%s] %s" % (status, label))
    for e in errs:
        print("    - " + e)
    return errs


# ---------- W3: 벡터 PDF 어댑터 ----------

# 샘플별 품질 하한(회귀 방지 바닥값). 2026-11-05 W3 재작업 1회차 측정값 그대로이며 목표치가 아니다
# (evidence/w3-pdf.md §4). kind는 평가 하네스에 F1이 없어 대응 쌍 kind 정확도를 쓴다.
QUALITY_FLOORS = {
    "SNP-M-101_RCS-main-loop": {"relations_f1": 1.0, "objects_f1": 1.0, "kind_accuracy": 1.0},
    "SNP-M-102_RCS-pressurizer": {"relations_f1": 0.923077, "objects_f1": 1.0, "kind_accuracy": 1.0},
    "SNP-M-201_CVCS": {"relations_f1": 1.0, "objects_f1": 1.0, "kind_accuracy": 1.0},
    "SNP-M-301_SIS": {"relations_f1": 1.0, "objects_f1": 1.0, "kind_accuracy": 1.0},
    "SNP-M-401_CCW": {"relations_f1": 0.869565, "objects_f1": 0.956522, "kind_accuracy": 0.909091},
    "SNP-M-501_MS-FW": {"relations_f1": 1.0, "objects_f1": 1.0, "kind_accuracy": 0.95},
}


def quality_problems(row, floors=None):
    """표 행이 샘플별 하한 아래로 내려간 항목 목록. 하한이 없는 샘플은 그 사실을 문제로 낸다."""
    floor = (QUALITY_FLOORS if floors is None else floors).get(row["name"])
    if floor is None:
        return ["%s: 품질 하한 미등록" % row["name"]]
    got = {"relations_f1": row["relations"]["f1"], "objects_f1": row["objects"]["f1"],
           "kind_accuracy": row["objects"]["kind_accuracy"]}
    return ["%s: %s %s < 하한 %s" % (row["name"], k, got[k], v) for k, v in sorted(floor.items())
            if got[k] is None or got[k] < v - 1e-9]


def graph_problems(name, extraction):
    """그래프 단계(③) 호환: build_graph·render_report·entity_mapping_document가 돌고 검증 passed인지."""
    try:
        graph = graph_build.build_graph(extraction)
        graph_build.render_report(graph)
        graph_build.entity_mapping_document(graph, extraction)
    except Exception as exc:  # 호환 실패를 검사 결과로 남긴다
        return ["%s: 그래프 단계 오류 %s: %s" % (name, type(exc).__name__, exc)]
    status = graph["validation"]["status"]
    return [] if status == "passed" else ["%s: 그래프 검증 %s" % (name, status)]

def pdf_samples():
    """[(도면 폴더 이름, drawio 경로, pdf 경로)] — 같은 폴더·같은 이름의 drawio와 pdf 쌍."""
    out = []
    for path in sorted(glob.glob(SAMPLE_GLOB)):
        pdf = os.path.splitext(path)[0] + ".pdf"
        if os.path.isfile(pdf):
            out.append((os.path.basename(os.path.dirname(path)), path, pdf))
    return out


def schema_problems(candidate, reference):
    """reference(drawio 추출 결과)의 필수 키가 candidate에 없으면 그 목록. 최상위 키는 같아야 한다.
    목록 항목은 reference의 모든 항목에 있는 키만 필수로 본다(근사 좌표일 때만 있는 method 등은 선택)."""
    probs = []
    if set(candidate) != set(reference):
        probs.append("최상위 키 다름: 없음 %s, 추가 %s" % (sorted(set(reference) - set(candidate)),
                                                    sorted(set(candidate) - set(reference))))

    def need(label, ref_items, cand_items):
        ref_keys = set.intersection(*[set(x) for x in ref_items]) if ref_items else set()
        for i, item in enumerate(cand_items):
            missing = ref_keys - set(item)
            if missing:
                probs.append("%s[%d] 키 없음: %s" % (label, i, sorted(missing)))
                break
    for key in ("nodes", "relations", "texts", "source_locations"):
        need(key, reference.get(key) or [], candidate.get(key) or [])
    need("unresolved_connectors", reference.get("relations") or [], candidate.get("unresolved_connectors") or [])
    cand_rel = (candidate.get("relations") or []) + (candidate.get("unresolved_connectors") or [])
    need("endpoints", [e for r in reference.get("relations") or [] for e in r["endpoints"]],
         [e for r in cand_rel for e in r["endpoints"]])
    for key in ("run", "source", "source_context", "drawing", "coordinate_system", "validation", "summary"):
        missing = set(reference.get(key) or {}) - set(candidate.get(key) or {})
        if missing:
            probs.append("%s 키 없음: %s" % (key, sorted(missing)))
    return probs


def evaluate_pdf(name, drawio_path, pdf_path, mutate=None):
    """(문제 목록, 표 행 dict 또는 None, 산출물 dict) — 한 샘플의 W3 검사.
    mutate: 후보 extraction을 바꾸는 함수(검사가 감점을 잡는지 확인하는 시험용)."""
    errs = []
    truth = drawio.extract(drawio_path, repo_root=REPO_ROOT)
    cand = pdf_vector.extract(pdf_path, repo_root=REPO_ROOT)
    again = pdf_vector.extract(pdf_path, repo_root=REPO_ROOT)
    if ev.dumps(cand) != ev.dumps(again):
        errs.append("%s: 두 번 실행 결과 다름" % name)
    if cand["validation"]["blockers"]:
        errs.append("%s: 구조 검증 blocker %d건" % (name, len(cand["validation"]["blockers"])))
    errs += ["%s: 스키마 %s" % (name, p) for p in schema_problems(cand, truth)]
    if mutate is not None:
        cand = mutate(copy.deepcopy(cand))
    errs += graph_problems(name, cand)
    al = align.estimate_transform(truth, cand)
    if al["status"] != "ok":
        errs.append("%s: 좌표 정렬 %s (%s)" % (name, al["status"], al["reason"]))
        return errs, None, {"extraction": cand, "alignment": al}
    result = ev.evaluate(truth, cand, al["transform"])
    if result["status"] != "ok":
        errs.append("%s: 평가 %s %s" % (name, result["status"], result["reasons"]))
        return errs, None, {"extraction": cand, "alignment": al, "evaluation": result}
    row = {"name": name, "truth_nodes": len(truth["nodes"]), "cand_nodes": len(cand["nodes"]),
           "truth_relations": len(truth["relations"]), "cand_relations": len(cand["relations"]),
           "unresolved": len(cand["unresolved_connectors"]), "blockers": len(cand["validation"]["blockers"]),
           "objects": result["objects"], "relations": result["relations"], "tags": result["tags"],
           "anchors": "%d/%d" % (al["anchors_used"], al["anchors_total"]), "outliers": al["outliers"],
           "rms": al["residual_rms"], "max": al["residual_max"], "rms_all": al["residual_rms_all"]}
    errs += quality_problems(row)
    return errs, row, {"extraction": cand, "alignment": al, "evaluation": result}


def _m(m):
    return "%s (%d/%d/%d)" % (ev._fmt(m["f1"]), m["tp"], m["fp"], m["fn"])


def summary_table(rows):
    """W3 지표 표(Markdown). 잔차 단위는 정답 좌표(canvas_unit)."""
    lines = ["| 도면 | 노드 정답/후보 | 관계 정답/후보 | 미해결 | blocker | 관계 F1 (TP/FP/FN) | 객체 F1 (TP/FP/FN) "
             "| 태그 F1 (TP/FP/FN) | kind 정확도 | category 정확도 | 기준점 사용/전체 | 잔차 RMS / 최대 | 제외 전 RMS |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for w in rows:
        lines.append("| %s | %d/%d | %d/%d | %d | %d | %s | %s | %s | %s | %s | %s | %s / %s | %s |" % (
            w["name"], w["truth_nodes"], w["cand_nodes"], w["truth_relations"], w["cand_relations"], w["unresolved"],
            w["blockers"], _m(w["relations"]), _m(w["objects"]), _m(w["tags"]),
            ev._fmt(w["objects"]["kind_accuracy"]), ev._fmt(w["objects"]["category_accuracy"]), w["anchors"],
            ev._fmt(w["rms"]), ev._fmt(w["max"]), ev._fmt(w["rms_all"])))
    return "\n".join(lines) + "\n"


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def run_pdf_checks(out=None):
    """(실패 목록, 건너뜀 여부)."""
    print("== 3. W3 벡터 PDF 어댑터(샘플 PDF)")
    if importlib.util.find_spec("pdfplumber") is None:
        print("[건너뜀] pdfplumber 없음(결정 D1). pdfplumber가 있는 Python으로 다시 실행할 것")
        return [], True
    failures, rows = [], []
    samples = pdf_samples()
    if not samples:
        failures.append("PDF 샘플 없음")
    for name, drawio_path, pdf_path in samples:
        errs, row, outputs = evaluate_pdf(name, drawio_path, pdf_path)
        failures += errs
        if row:
            rows.append(row)
            print("  %-28s rel F1 %-8s obj F1 %-8s tag F1 %-8s 정렬 RMS %s (기준점 %s)"
                  % (name, row["relations"]["f1"], row["objects"]["f1"], row["tags"]["f1"], row["rms"],
                     row["anchors"]))
        for e in errs:
            print("    - " + e)
        if out:
            d = os.path.join(out, name)
            os.makedirs(d, exist_ok=True)
            for key, value in sorted(outputs.items()):
                _write(os.path.join(d, key + ".json"), ev.dumps(value))
            if "evaluation" in outputs:
                _write(os.path.join(d, "evaluation.md"), ev.render_report(outputs["evaluation"]))
    table = summary_table(rows)
    print(table)
    if out:
        _write(os.path.join(out, "summary.md"), table)
        print("저장: %s" % out)
    print("[%s] W3 PDF" % ("통과" if not failures else "실패 %d건" % len(failures)))
    return failures, False


# ---------- W4: 래스터(PNG) 어댑터 ----------

# 샘플별 품질 하한(회귀 방지 바닥값, 목표치 아님). 2026-11-06 W4 측정값을 0.05 단위로 내린 뒤 0.05를 더 뺀 값이다
# (OCR·영상 처리 결과가 실행 환경에 따라 조금 달라질 여지를 둔 보수적 하한, evidence/w4-래스터.md §5).
RASTER_QUALITY_FLOORS = {
    "SNP-M-101_RCS-main-loop": {"relations_f1": 0.85, "objects_f1": 0.9, "kind_accuracy": 0.8},
    "SNP-M-102_RCS-pressurizer": {"relations_f1": 0.8, "objects_f1": 0.9, "kind_accuracy": 0.85},
    "SNP-M-201_CVCS": {"relations_f1": 0.65, "objects_f1": 0.8, "kind_accuracy": 0.7},
    "SNP-M-301_SIS": {"relations_f1": 0.6, "objects_f1": 0.8, "kind_accuracy": 0.6},
    "SNP-M-401_CCW": {"relations_f1": 0.55, "objects_f1": 0.75, "kind_accuracy": 0.75},
    "SNP-M-501_MS-FW": {"relations_f1": 0.65, "objects_f1": 0.8, "kind_accuracy": 0.8},
}


def raster_samples():
    """[(도면 폴더 이름, drawio 경로, png 경로)] — 같은 폴더의 PNG 중 첫 번째. `.drawio.png`는 다이어그램 XML을
    품고 있어 블라인드 시험에서 뺀다(결정 D1)."""
    out = []
    for path in sorted(glob.glob(SAMPLE_GLOB)):
        folder = os.path.dirname(path)
        pngs = [p for p in sorted(glob.glob(os.path.join(folder, "*.png"))) if not p.lower().endswith(".drawio.png")]
        if pngs:
            out.append((os.path.basename(folder), path, pngs[0]))
    return out


def evaluate_raster(name, drawio_path, png_path, mutate=None):
    """(문제 목록, 표 행 dict 또는 None, 산출물 dict) — 한 샘플의 W4 검사(evaluate_pdf와 같은 구성)."""
    if png_path.lower().endswith(".drawio.png"):
        return ["%s: 블라인드 규칙 위반(.drawio.png 입력)" % name], None, {}
    errs = []
    truth = drawio.extract(drawio_path, repo_root=REPO_ROOT)
    cand = raster.extract(png_path, repo_root=REPO_ROOT)
    again = raster.extract(png_path, repo_root=REPO_ROOT)
    if ev.dumps(cand) != ev.dumps(again):
        errs.append("%s: 두 번 실행 결과 다름" % name)
    if cand["validation"]["blockers"]:
        errs.append("%s: 구조 검증 blocker %d건" % (name, len(cand["validation"]["blockers"])))
    errs += ["%s: 스키마 %s" % (name, p) for p in schema_problems(cand, truth)]
    if mutate is not None:
        cand = mutate(copy.deepcopy(cand))
    errs += graph_problems(name, cand)
    al = align.estimate_transform(truth, cand)
    if al["status"] != "ok":
        errs.append("%s: 좌표 정렬 %s (%s)" % (name, al["status"], al["reason"]))
        return errs, None, {"extraction": cand, "alignment": al}
    result = ev.evaluate(truth, cand, al["transform"])
    if result["status"] != "ok":
        errs.append("%s: 평가 %s %s" % (name, result["status"], result["reasons"]))
        return errs, None, {"extraction": cand, "alignment": al, "evaluation": result}
    row = {"name": name, "truth_nodes": len(truth["nodes"]), "cand_nodes": len(cand["nodes"]),
           "truth_relations": len(truth["relations"]), "cand_relations": len(cand["relations"]),
           "unresolved": len(cand["unresolved_connectors"]), "blockers": len(cand["validation"]["blockers"]),
           "objects": result["objects"], "relations": result["relations"], "tags": result["tags"],
           "anchors": "%d/%d" % (al["anchors_used"], al["anchors_total"]), "outliers": al["outliers"],
           "rms": al["residual_rms"], "max": al["residual_max"], "rms_all": al["residual_rms_all"]}
    errs += quality_problems(row, RASTER_QUALITY_FLOORS)
    return errs, row, {"extraction": cand, "alignment": al, "evaluation": result}


def run_raster_checks(out=None):
    """(실패 목록, 건너뜀 여부)."""
    print("== 4. W4 래스터 어댑터(샘플 PNG)")
    has_cv, has_ocr = raster.available()
    if not (has_cv and has_ocr):
        print("[건너뜀] OpenCV 또는 rapidocr 없음(결정 D7). packaging/requirements-raster.txt를 설치한 Python으로 "
              "다시 실행할 것")
        return [], True
    failures, rows = [], []
    samples = raster_samples()
    if not samples:
        failures.append("PNG 샘플 없음")
    for name, drawio_path, png_path in samples:
        errs, row, outputs = evaluate_raster(name, drawio_path, png_path)
        failures += errs
        if row:
            rows.append(row)
            print("  %-28s rel F1 %-8s obj F1 %-8s tag F1 %-8s 정렬 RMS %s (기준점 %s)"
                  % (name, row["relations"]["f1"], row["objects"]["f1"], row["tags"]["f1"], row["rms"],
                     row["anchors"]))
        for e in errs:
            print("    - " + e)
        if out:
            d = os.path.join(out, name)
            os.makedirs(d, exist_ok=True)
            for key, value in sorted(outputs.items()):
                _write(os.path.join(d, key + ".json"), ev.dumps(value))
            if "evaluation" in outputs:
                _write(os.path.join(d, "evaluation.md"), ev.render_report(outputs["evaluation"]))
    table = summary_table(rows)
    print(table)
    if out:
        _write(os.path.join(out, "summary.md"), table)
        print("저장: %s" % out)
    print("[%s] W4 래스터" % ("통과" if not failures else "실패 %d건" % len(failures)))
    return failures, False


def run_checks(pdf_out=None, raster_out=None):
    failures = []
    print("== 1. 가상 소형 픽스처")
    failures += run_suite("fixture truth_small", load_json(FIXTURE))
    print("== 2. 샘플 drawio 추출 결과(메모리)")
    samples = sorted(glob.glob(SAMPLE_GLOB))
    if not samples:
        failures.append("샘플 없음")
    for path in samples:
        name = os.path.basename(os.path.dirname(path))
        print("-- " + name)
        failures += run_suite(name, drawio.extract(path))
    pdf_failures, skipped = run_pdf_checks(pdf_out)
    failures += pdf_failures
    raster_failures, skipped_raster = run_raster_checks(raster_out)
    failures += raster_failures
    print("== 결과: %s%s%s" % ("전부 통과" if not failures else "실패 %d건" % len(failures),
                            " (W3 건너뜀)" if skipped else "", " (W4 건너뜀)" if skipped_raster else ""))
    return 0 if not failures else 1


def _out_conflicts(args):
    """--out 폴더 또는 그 안에 쓸 파일이 입력 파일과 같은 경로면 그 경로 목록."""
    inputs = {os.path.normcase(os.path.realpath(p)) for p in (args.truth, args.candidate, args.transform) if p}
    targets = [args.out] + [os.path.join(args.out, n) for n in ("evaluation.json", "evaluation.md")]
    return [t for t in targets if os.path.normcase(os.path.realpath(t)) in inputs]


def run_eval(args):
    if args.out and _out_conflicts(args):
        print("거부: --out이 입력 파일을 덮어씀: %s" % ", ".join(_out_conflicts(args)))
        return 2
    truth, cand = load_json(args.truth), load_json(args.candidate)
    tf = load_json(args.transform) if args.transform else None
    result = ev.evaluate(truth, cand, tf)
    report = ev.render_report(result)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "evaluation.json"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(ev.dumps(result))
        with open(os.path.join(args.out, "evaluation.md"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(report)
        print("저장: %s" % args.out)
    print(report)
    return 0 if result["status"] == "ok" else 2


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--truth")
    ap.add_argument("--candidate")
    ap.add_argument("--transform", help="후보 → 정답 좌표 변환 JSON 파일 {scale, offset}")
    ap.add_argument("--out")
    ap.add_argument("--pdf-out", help="W3 샘플 결과(추출·정렬·평가·요약 표)를 저장할 폴더")
    ap.add_argument("--raster-out", help="W4 샘플 결과(추출·정렬·평가·요약 표)를 저장할 폴더")
    args = ap.parse_args(argv)
    if args.truth or args.candidate:
        if not (args.truth and args.candidate):
            ap.error("--truth와 --candidate를 함께 지정해야 함")
        return run_eval(args)
    return run_checks(args.pdf_out, args.raster_out)


if __name__ == "__main__":
    sys.exit(main())
