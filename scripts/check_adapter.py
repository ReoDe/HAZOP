"""T3 W2 평가 하네스 검사 (QA용). 종료 코드 0 = 전부 통과.

인자 없이 실행: 가상 소형 픽스처와 샘플 6세트(drawio 추출 결과, 메모리에서만 사용)로
  1) 정답지끼리 비교 시 객체·관계·태그 F1=1, GED=0
  2) 의도적 오류 주입(태그 오타, 객체 누락, 연결 뒤바꿈, 객체 이동, 좌표 이동)별 기대 감점
  3) 좌표 정규화(이동·배율 transform), 좌표계 불일치 시 blocked
  4) 결정성(두 번 실행·입력 순서 뒤집기 시 JSON 동일)
을 확인한다.

평가 실행: python scripts/check_adapter.py --truth 정답.json --candidate 후보.json
           [--transform 변환.json] [--out 폴더]   → 폴더에 evaluation.json·evaluation.md
"""

import argparse
import copy
import glob
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.extract.adapters import evaluation as ev  # noqa: E402

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


def run_checks():
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
    print("== 결과: %s" % ("전부 통과" if not failures else "실패 %d건" % len(failures)))
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
    args = ap.parse_args(argv)
    if args.truth or args.candidate:
        if not (args.truth and args.candidate):
            ap.error("--truth와 --candidate를 함께 지정해야 함")
        return run_eval(args)
    return run_checks()


if __name__ == "__main__":
    sys.exit(main())
