"""자동 수락 검사: 저장된 AI 응답을 지금 코드로 다시 재생해 자동 수락 규칙(hazop.extract.ai_review.auto_block)으로 걸러, 맞은 수와 새
오검출을 낸다. 호출하지 않는다(고정 응답만). 근거: docs/units/2026-11-13-drawing-knowledge/evidence/auto-confirm-design.md 4장.

  python scripts/check_auto_accept.py --input-dir <쪽 PDF 폴더> --keys <정답지 폴더> [--keys …] --responses <고정 응답 폴더> --pages 7,19
      쪽마다 자동 수락 수·막힌 까닭·종류 미정 기호와 DEXPI로 나가는 구성요소 앞뒤(4.3 표), 확신도 구간별 값(4.2 표)
  python scripts/check_auto_accept.py … --saved <이름=후보 json> [--saved …]
      예전에 저장한 후보({쪽 이름: {"candidates", "stats"}})를 확신도 구간별로만 채점해 나란히 낸다(참고용, 규칙은 걸지 않음).
      --rest를 주면 --pages에 든 쪽은 뺀다
  python scripts/check_auto_accept.py … --held --judge
      켜도 되는지 판정(judge의 기준). 0.70이 통과면 종료 코드 0, 아니면 1. 처음 보는 쪽에서만 뜻이 있다
  --floors 0.60,0.70 (기본)  문턱마다 같은 재생을 자동 수락 규칙에 다시 걸어 따로 채점한다(호출 0). 판정 줄은 --judge가 없어도 참고로 낸다

보류 쪽(HELD)은 --held를 줘야 열고, 그때는 쪽별 값을 내지 않고 합계만 낸다. 보류 측정은 총괄만 한다.
"""

import argparse
import collections
import json
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

HELD = {"013", "047", "084", "088", "113", "143"}
BINS = ((0.8, 9), (0.7, 0.8), (0.6, 0.7), (0.5, 0.6), (0.0, 0.5))
# 켜는 판정의 기준(총괄 2026-11-25). 앞 기준(40건·90%)에 하한, 판정을 뒤집는 오답, 짝 없는 조각, 태그, 낮춘 문턱의 구간을 더했다
JUDGE_MIN, JUDGE_RATE, JUDGE_WILSON, UNPAIRED_MAX = 40, 0.90, 0.80, 2
TAG_MIN, TAG_RATE = 10, 0.95
BASE_FLOOR, BAND_MIN, BAND_RATE = 0.70, 20, 0.85       # BASE_FLOOR보다 낮은 문턱은 그 사이 구간만으로 따로 지나야 한다
FLIP_TRUTH = ("check_valve", "isolation_valve", "psv", "relief_valve", "rupture_disc")     # 이 정답을 다른 종류로 읽으면 역류·격리·과압 방호가 사라진다
ACTUATED = ("manual_valve", "isolation_valve", "control_valve", "motor_operated_valve", "air_operated_valve", "solenoid_valve")   # 서로 바뀌면 구동 방식이 바뀐다
COMPONENT = ("equipment", "valve", "instrument")       # 짝 없는 조각에 붙으면 없는 구성요소가 생기는 분류


def page_name(seq):
    return "apr1400-%03d" % seq


def load_key(folders, name):
    for d in folders:
        p = os.path.join(d, name + ".json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                key = json.load(fh)
            key.setdefault("lines", [])
            key.setdefault("continuations", [])
            return key
    raise SystemExit("정답지가 없음: %s" % name)


def extract(args, seq, work):
    import check_read_quality as rq
    from hazop.extract.adapters import pdf_vector
    path = rq.apr_pdf(args.input_dir, seq)
    return path, pdf_vector.extract(path, page=0, repo_root=work)


def score(c, ex, key):
    """후보 하나를 적용했을 때의 (채점, 종류 후보면 정답 종류): ok·wrong·unpaired(짝 없는 조각)·no_gt·outside(정답지 영역 밖)·moved(상자가 어긋남)."""
    import check_read_quality as rq
    n = next((n for n in ex["nodes"] if n["source_object_id"] == c["target"]), None)
    if n is None or max(abs(a - b) for a, b in zip(rq._bbox(n), c["bbox"])) > 0.6:
        return "moved", None
    if not rq._in_region(n, key["regions"]):
        return "outside", None
    one = {"candidates": [{"node_local_id": n["local_id"], "field": c["field"], "values": c["values"]}]}
    m = rq.match_symbols(key["symbols"], rq.apply_candidates(ex, one)["nodes"])
    s = next((s for s in key["symbols"] if s["id"] in m and m[s["id"]]["local_id"] == n["local_id"]), None)
    if s is None:
        return "unpaired", None
    v = c["values"][0]
    if c["field"] == "kind":
        return ("ok" if rq.same_kind(v, s["kind"]) else "wrong"), s["kind"]
    if c["field"] == "tag":
        return ("no_gt" if not s.get("tag") else "ok" if rq.same_tag(v, s["tag"]) else "wrong"), None
    want = (s.get("attributes") or {}).get(c["field"])
    return ("no_gt" if not want else "ok" if rq._same_value(c["field"], v, want) else "wrong"), None


def replay(args, ex, pdf, client):
    """앱의 자동 경로와 같은 입력(표준 기호 판 고정)으로 다시 물은 결과. 응답이 없으면 멈춘다(부분 재생을 채점하지 않음)."""
    from hazop.extract import ai_images, ai_review
    img = ai_images.image_input_for(pdf, 0, (), None, wide=True, recheck=True)
    result = ai_review.run(ex, client, cap=ai_review.AUTO_CAP, images=img)
    if result["stats"]["errors"]:
        raise SystemExit("고정 응답이 모자람: %s" % result["stats"]["error_kinds"][:3])
    return result


def dexpi(ex):
    from hazop.export import dexpi_export
    from hazop.graph import build
    ex = dict(ex, drawing=dict(ex["drawing"], drawing_number=ex["drawing"].get("drawing_number") or "T"))   # 번호 없는 쪽도 구성요소 수를 센다
    try:
        s = dexpi_export.export_drawing(build.build_graph(ex), ex, require_confirmed_number=False).stats
    except dexpi_export.ExportError as exc:
        return "실패 %s" % exc.reasons[:1]
    return "%d/%d" % (s["components"], s["components"] + s["excluded_components"])


def simulate(args, name, ex, cands, floor):
    """문턱 floor로 앱과 같은 길(merge_and_save → auto_accept)로 임시 작업 루트에서 수락해 본다 → (수락한 cand_id, 막힌 까닭, 고친 추출)."""
    import dataclasses
    from unittest import mock
    from hazop import paths
    from hazop.extract import ai_review, corrections
    name = "%s-f%d" % (name, round(100 * floor))
    ruleset = dataclasses.replace(ai_review.AUTO_RULES, version="check-%.2f" % floor, min_confidence={k: floor for k in ai_review.AUTO_RULES.min_confidence})
    d = os.path.join(paths.output_root("extract"), name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "extraction.json"), "w", encoding="utf-8") as fh:
        json.dump(ex, fh, ensure_ascii=False)
    ai_review.merge_and_save(name, ex, {"candidates": cands, "stats": {"calls": 0}}, auto=True)
    with mock.patch.object(ai_review, "AUTO_ACCEPT_ENABLED", True), mock.patch.object(ai_review, "AUTO_RULES", ruleset):
        out = ai_review.auto_accept(name, ex)
    return out["accepted"], out["blocked"], corrections.resolve(name, ex)["corrected"]


def table(title, rows):
    """확신도 구간별 종류 값(첫 묻기 과제, 어긋난 것·영역 밖 제외)."""
    kinds = [r for r in rows if r["task"] == "kind" and r["field"] == "kind" and r["res"] not in ("moved", "outside")]
    dropped = collections.Counter(r["res"] for r in rows if r["res"] in ("moved", "outside"))
    print("== %s (뺀 것 %s)" % (title, dict(dropped)))
    for lo, hi in BINS:
        t = [r for r in kinds if lo <= r["conf"] < hi]
        print("   종류 %.2f~ %d/%d" % (lo, sum(r["res"] == "ok" for r in t), len(t)))
    for what, rs in [("종류", kinds)] + [(f, [r for r in rows if r["task"] == t and r["field"] == f and r["res"] not in ("moved", "outside")])
                                         for t, f in (("tag", "tag"), ("recheck", "kind"), ("tag", "normal_position"), ("tag", "fail_position"))]:
        top = [r for r in rs if r["conf"] >= 0.7]
        print("   %-16s 0.70 이상 %d/%d, 전체 %d/%d" % (what if rs is not kinds else "kind", sum(r["res"] == "ok" for r in top), len(top),
                                                        sum(r["res"] == "ok" for r in rs), len(rs)))


def row(page, c, ex, key):
    res, truth = score(c, ex, key)
    return {"page": page, "task": c["task"], "field": c["field"], "value": c["values"][0], "conf": c["confidence"], "res": res, "truth": truth}


# ---------------------------------------------------------------- 켜는 판정

def wilson(ok, n, z=1.96):
    """Wilson 95% 하한."""
    if not n:
        return 0.0
    p = ok / n
    return (p + z * z / (2 * n) - z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5) / (1 + z * z / n)


def flips(r):
    """판정을 뒤집는 오답인가."""
    if r["res"] != "wrong":
        return False
    return r["truth"] in FLIP_TRUTH or (r["truth"] in ACTUATED and r["value"] in ACTUATED)


def _rate(rows):
    return sum(r["res"] == "ok" for r in rows) / len(rows) if rows else 0.0


def judge(accepted, floor):
    """자동 수락한 줄들과 그 문턱 → {"kind": 통과, "tag": 통과|None(판정 못 함), "why": [걸린 기준], "n", "ok", "wilson", "flips", "unpaired", "tag_n", "tag_ok"}.
    floor가 BASE_FLOOR보다 낮으면 BASE_FLOOR 이상인 줄이 기준을 모두 지나고, 그 사이 구간의 줄만으로도 BAND 기준을 지나야 한다."""
    from hazop.extract import rules
    inside = [r for r in accepted if r["res"] not in ("moved", "outside")]
    kinds = [r for r in inside if r["field"] == "kind"]
    main = [r for r in kinds if r["conf"] >= BASE_FLOOR]
    band = [r for r in kinds if r["conf"] < BASE_FLOOR]
    lost = [r for r in kinds if r["res"] == "unpaired" and rules.KIND_CATEGORY.get(r["value"]) in COMPONENT]
    ok = sum(r["res"] == "ok" for r in main)
    low = wilson(ok, len(main))
    checks = [("count", len(main) >= JUDGE_MIN), ("precision", _rate(main) >= JUDGE_RATE), ("wilson", low >= JUDGE_WILSON),
              ("flip", not any(flips(r) for r in main)), ("unpaired", len(lost) <= UNPAIRED_MAX)]
    if floor < BASE_FLOOR:
        checks += [("band_count", len(band) >= BAND_MIN), ("band_precision", _rate(band) >= BAND_RATE), ("band_flip", not any(flips(r) for r in band))]
    why = [name for name, passed in checks if not passed]
    tags = [r for r in inside if r["field"] == "tag" and r["res"] != "no_gt"]
    return {"kind": not why, "tag": None if len(tags) < TAG_MIN else _rate(tags) >= TAG_RATE, "why": why, "n": len(main), "ok": ok, "wilson": low,
            "flips": sum(flips(r) for r in kinds), "unpaired": len(lost), "tag_n": len(tags), "tag_ok": sum(r["res"] == "ok" for r in tags),
            "band_n": len(band), "band_ok": sum(r["res"] == "ok" for r in band)}


def report(accepted, floors):
    """문턱마다 판정 한 줄(합계만). accepted: 문턱별 목록 {문턱: 줄} 또는 줄 목록(확신도로 거른다). → {문턱: judge의 답}."""
    out = {}
    for floor in sorted(floors):
        rows = accepted[floor] if isinstance(accepted, dict) else [r for r in accepted if r["conf"] >= floor]
        j = out[floor] = judge(rows, floor)
        print("판정 %.2f: 종류 %s(0.70 이상 %d/%d, Wilson 하한 %.0f%%, 뒤집는 오답 %d, 짝 없는 구성요소 %d%s)%s · 태그 %s(%d/%d)" % (
            floor, "통과" if j["kind"] else "실패", j["ok"], j["n"], 100 * j["wilson"], j["flips"], j["unpaired"],
            ", 구간 %d/%d" % (j["band_ok"], j["band_n"]) if floor < BASE_FLOOR else "", " 걸린 기준 " + ",".join(j["why"]) if j["why"] else "",
            "판정 못 함(끔)" if j["tag"] is None else "통과" if j["tag"] else "실패(끔)", j["tag_ok"], j["tag_n"]), flush=True)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--keys", action="append", required=True)
    ap.add_argument("--responses")
    ap.add_argument("--pages", default="", help="쪽 번호(쉼표)")
    ap.add_argument("--saved", action="append", default=[], help="이름=후보 json")
    ap.add_argument("--held", action="store_true", help="보류 쪽을 연다(합계만 냄, 총괄만)")
    ap.add_argument("--rest", action="store_true", help="--saved에서 --pages의 쪽을 뺀다")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--floors", default="0.60,0.70", help="채점할 문턱(쉼표)")
    args = ap.parse_args(argv)
    if args.judge and not args.held:
        raise SystemExit("판정은 처음 보는 쪽(--held)에서만 한다")
    seqs = [int(x) for x in args.pages.split(",") if x.strip()]
    if not args.held and any("%03d" % s in HELD for s in seqs):
        raise SystemExit("보류 쪽은 --held 없이 열지 않음")
    if seqs and not args.responses:
        raise SystemExit("--responses가 필요함")
    work = tempfile.mkdtemp(prefix="hazop-auto-accept-")
    os.environ["HAZOP_WORK_ROOT"] = work
    try:
        return run(args, seqs, work)
    finally:
        shutil.rmtree(work, True)


def run(args, seqs, work):
    from hazop.extract import confirmation
    from hazop.study import providers
    floors = tuple(sorted({float(x) for x in args.floors.split(",") if x.strip()} | {BASE_FLOOR}))
    rows, by_floor, total = [], {f: [] for f in floors}, collections.Counter()
    if seqs:
        client = providers.make_client("fixed", response_dir=args.responses)
        for seq in seqs:
            name = page_name(seq)
            pdf, ex = extract(args, seq, work)
            key = load_key(args.keys, name)
            cands = replay(args, ex, pdf, client)["candidates"]
            scored = {c["cand_id"]: row(name, c, ex, key) for c in cands}
            rows += scored.values()
            for f in floors:
                taken = simulate(args, name, ex, cands, f)
                by_floor[f] += [scored[i] for i in taken[0]]
                if f == BASE_FLOOR:
                    got, blocked, after = taken
            n0, n1 = (confirmation.check(e)["counts"]["unknown_symbol"] for e in (ex, after))
            total.update({"before": n0, "after": n1})
            if not args.held:
                kinds = collections.Counter(scored[i]["field"] for i in got)
                res = collections.Counter("%s:%s" % (scored[i]["field"], scored[i]["res"]) for i in got)
                print("%s 자동 수락 종류 %d·태그 %d %s | 막힘 %s | 종류 미정 %d → %d | DEXPI %s → %s"
                      % (name, kinds["kind"], kinds["tag"], dict(res), dict(sorted(blocked.items())), n0, n1, dexpi(ex), dexpi(after)), flush=True)
        table("재생한 응답 %d쪽" % len(seqs), rows)
        for f, field in [(f, field) for f in floors for field in ("kind", "tag")]:
            rs = [r for r in by_floor[f] if r["field"] == field]
            in_key = [r for r in rs if r["res"] not in ("moved", "outside")]
            print("문턱 %.2f 자동 수락 %s %d건: 정답지 영역 안 %d건 가운데 맞음 %d %s" % (
                f, field, len(rs), len(in_key), sum(r["res"] == "ok" for r in in_key), dict(collections.Counter(r["res"] for r in rs))))
        print("종류 미정 기호 %d → %d(문턱 %.2f)" % (total["before"], total["after"], BASE_FLOOR))
        verdict = report(by_floor, floors)
    if not args.held:
        for spec in args.saved:
            title, path = spec.split("=", 1)
            with open(path, encoding="utf-8") as fh:
                docs = json.load(fh)
            if any(n[-3:] in HELD for n in docs):
                raise SystemExit("보류 쪽이 든 자료는 채점하지 않음: %s" % title)
            out = []
            for name, d in sorted(docs.items()):
                if (args.rest and int(name[-3:]) in seqs) or d["stats"].get("errors"):
                    continue
                _pdf, ex = extract(args, int(name[-3:]), work)
                key = load_key(args.keys, name)
                out += [row(name, c, ex, key) for c in d["candidates"]]
            table("저장 후보 %s" % title, out)
    if args.judge:
        return 0 if seqs and verdict[BASE_FLOOR]["kind"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
