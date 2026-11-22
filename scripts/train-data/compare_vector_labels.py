"""build_vector_labels.py가 만든 학습용 정답을 저장소 정답지(시험 집합)와 견준다. 만든 뒤에만 돌린다.

  python scripts/train-data/compare_vector_labels.py <build 출력 폴더> [--pages 12,63] [--json <출력.json>]

정책별로 셈한다.
  script    : 추출기가 종류를 정한 후보만(지금 추출기와 같음)
  vec_ai    : script + 종류 없는 후보는 AI 종류((나) 기본안)
  ai_all    : 모든 후보에 AI 종류(스크립트 종류는 버림, AI가 not_symbol이면 뺌)
  ai_merge  : ai_all에서 AI가 조각이라 한 후보를 닿은 같은 종류 후보와 한 상자로 합침(build_vector_labels.merge_parts)
  +missed   : 위 정책에 AI가 찾은 놓친 기호(벡터 원소로 맞춘 상자)를 더함
값: 기호 종류·태그는 읽기 품질 지표와 같은 셈(check_read_quality.score_kind/score_tag, 맞은 수/(정답 단위 + 오검출)).
기호 유무 재현율, 상자 IoU(짝지은 것끼리, 정답지 상자도 그림으로 ±3pt 읽은 값임), 놓친 종류, 오검출 종류를 함께 낸다.
"""

import argparse
import json
import os
import statistics
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import coco_format as cf  # noqa: E402

sys.path.insert(0, os.path.join(cf.REPO_ROOT, "scripts"))
import check_read_quality as crq  # noqa: E402


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def policy_symbols(doc, policy):
    out = []
    for s in doc["symbols"]:
        if policy == "script" and s["source"] != "script":
            continue
        if policy.startswith(("ai_all", "ai_merge")):
            continue
        out.append(dict(s))
    if policy.startswith(("ai_all", "ai_merge")):
        for s in doc["symbols"]:
            k = s.get("ai_kind")
            if k and k != "not_symbol":
                out.append(dict(s, kind=cf.canonical(k)))
            elif not k:
                out.append(dict(s))  # AI 답이 없으면 스크립트 종류
    if policy.startswith("ai_merge"):
        import build_vector_labels
        out = build_vector_labels.merge_parts(out)
    if policy.endswith("+missed"):
        out += [dict(m, id=m["id"]) for m in doc["missed"]]
    return out


def measure(key, symbols):
    ex = {"nodes": crq._as_nodes(symbols)}
    m = crq.match_symbols(key["symbols"], ex["nodes"])
    by_id = {s["id"]: s for s in symbols}
    ious = [iou(s["bbox"], by_id[m[s["id"]]["local_id"]]["bbox"]) for s in key["symbols"] if s["id"] in m]
    matched_labels = {n["local_id"] for n in m.values()}
    fp = [s for s in symbols if s["id"] not in matched_labels
          and crq.in_regions(crq._center(s["bbox"]), key["regions"])]
    missed = [s for s in key["symbols"] if s["id"] not in m]
    wrong = [(s["kind"], m[s["id"]]["kind"]) for s in key["symbols"] if s["id"] in m
             and not crq.same_kind(m[s["id"]]["kind"], s["kind"])]
    return {"kind": crq.score_kind(key, ex, m), "tag": crq.score_tag(key, ex, m),
            "present": [len(m), len(key["symbols"])], "labels_in_region": len(symbols) - sum(
                1 for s in symbols if not crq.in_regions(crq._center(s["bbox"]), key["regions"])),
            "iou_median": round(statistics.median(ious), 2) if ious else None,
            "iou_ge_05": [sum(v >= 0.5 for v in ious), len(ious)],
            "missed_kinds": dict(Counter(s["kind"] for s in missed).most_common()),
            "fp_kinds": dict(Counter(s["kind"] for s in fp).most_common()),
            "wrong_kinds": dict(Counter("%s→%s" % w for w in wrong).most_common())}


def candidate_ceiling(key, doc):
    cands = [{"id": s["candidate"], "kind": "x", "bbox": s["bbox"]} for s in doc["symbols"]]
    cands += [{"id": r["candidate"], "kind": "x", "bbox": r["bbox"]} for r in doc["rejected"]]
    m = crq.match_symbols(key["symbols"], crq._as_nodes(cands))
    return [len(m), len(key["symbols"])]


def ai_vs_script(key, doc):
    """후보 하나하나에서 스크립트 종류와 AI 종류가 정답과 맞는지(정답 기호와 짝지어진 후보만)."""
    cands = [dict(s, id=s["candidate"]) for s in doc["symbols"]]
    cands += [{"id": r["candidate"], "kind": None, "bbox": r["bbox"], "script_kind": None,
               "ai_kind": (r.get("ai") or {}).get("kind")} for r in doc["rejected"]]
    m = crq.match_symbols(key["symbols"], crq._as_nodes([dict(c, kind=c.get("kind") or "x") for c in cands]))
    by = {c["id"]: c for c in cands}
    rows = Counter()
    for s in key["symbols"]:
        if s["id"] not in m:
            continue
        c = by[m[s["id"]]["local_id"]]
        sk, ak = c.get("script_kind"), c.get("ai_kind")
        rows["script_has_kind" if sk else "script_no_kind"] += 1
        if sk:
            rows["script_right"] += crq.same_kind(sk, s["kind"])
            rows["ai_right_where_script_has"] += crq.same_kind(ak, s["kind"])
        else:
            rows["ai_right_where_script_none"] += crq.same_kind(ak, s["kind"])
            rows["ai_said_not_symbol_where_script_none"] += ak == "not_symbol"
    return dict(rows)


def calls_summary(out_dir):
    path = os.path.join(out_dir, "calls.jsonl")
    if not os.path.isfile(path):
        return {}
    recs = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    by = {}
    for r in recs:
        page, kind = r["label"].split("-cells-")[0] if "-cells-" in r["label"] else r["label"].split("-missed-")[0], (
            "cells" if "-cells-" in r["label"] else "missed")
        d = by.setdefault(page, {}).setdefault(kind, {"calls": 0, "ok": 0, "seconds": []})
        d["calls"] += 1
        d["ok"] += r["status"] == "completed"
        d["seconds"].append(r["seconds"])
    for page in by.values():
        for d in page.values():
            s = d.pop("seconds")
            d["seconds_sum"], d["seconds_max"] = round(sum(s), 1), max(s)
    return by


def fmt(c):
    den = c["units"] + c["false_pos"]
    return "%d/%d (%.1f%%, 오검출 %d)" % (c["correct"], den, 100.0 * c["correct"] / den if den else 0, c["false_pos"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build_dir")
    ap.add_argument("--pages", default="12,63")
    ap.add_argument("--json")
    a = ap.parse_args()
    keys = dict(crq.load_keys({int(s) for s in a.pages.split(",")}))
    policies = ("script", "vec_ai", "ai_all", "ai_merge", "ai_all+missed", "ai_merge+missed")
    res = {"calls": calls_summary(a.build_dir), "pages": {}}
    total = {p: {"kind": crq._count(), "tag": crq._count()} for p in policies}
    for name, key in keys.items():
        with open(os.path.join(a.build_dir, name, "labels.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        page = {"candidate_ceiling": candidate_ceiling(key, doc), "ai_vs_script": ai_vs_script(key, doc),
                "missed_found": len(doc["missed"]), "missed_snapped": sum(m["snapped"] for m in doc["missed"]),
                "box_flags": dict(Counter(s.get("ai_box") for s in doc["symbols"]))}
        for p in policies:
            page[p] = measure(key, policy_symbols(doc, p))
            for item in ("kind", "tag"):
                for f in ("correct", "units", "false_pos"):
                    total[p][item][f] += page[p][item][f]
        res["pages"][name] = page
        print("== %s: 정답 기호 %d, 후보로 덮인 정답 %d/%d, AI가 찾은 놓친 기호 %d(벡터로 맞춤 %d)" % (
            name, len(key["symbols"]), *page["candidate_ceiling"], page["missed_found"], page["missed_snapped"]))
        print("   후보별 종류:", page["ai_vs_script"])
        for p in policies:
            r = page[p]
            print("   %-14s 종류 %s | 태그 %s | 있음 %d/%d | IoU 중앙 %s, ≥0.5 %d/%d" % (
                p, fmt(r["kind"]), fmt(r["tag"]), *r["present"], r["iou_median"], *r["iou_ge_05"]))
    res["total"] = total
    print("== 합계")
    for p in policies:
        print("   %-14s 종류 %s | 태그 %s" % (p, fmt(total[p]["kind"]), fmt(total[p]["tag"])))
    print("호출:", json.dumps(res["calls"], ensure_ascii=False))
    if a.json:
        cf.save(res, a.json)


if __name__ == "__main__":
    main()
