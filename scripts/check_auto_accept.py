"""자동 수락 검사: 저장된 AI 응답을 지금 코드로 다시 재생해 자동 수락 규칙(hazop.extract.ai_review.auto_block)으로 걸러, 맞은 수와 새
오검출을 낸다. 호출하지 않는다(고정 응답만). 근거: docs/units/2026-11-13-drawing-knowledge/evidence/auto-confirm-design.md 4장.

  python scripts/check_auto_accept.py --input-dir <쪽 PDF 폴더> --keys <정답지 폴더> [--keys …] --responses <고정 응답 폴더> --pages 7,19
      쪽마다 자동 수락 수·막힌 까닭·종류 미정 기호와 DEXPI로 나가는 구성요소 앞뒤(4.3 표), 확신도 구간별 값(4.2 표)
  python scripts/check_auto_accept.py … --saved <이름=후보 json> [--saved …]
      예전에 저장한 후보({쪽 이름: {"candidates", "stats"}})를 확신도 구간별로만 채점해 나란히 낸다(참고용, 규칙은 걸지 않음).
      --rest를 주면 --pages에 든 쪽은 뺀다
  python scripts/check_auto_accept.py … --held --judge
      켜도 되는지 판정(4.5): 자동 수락 종류 후보 40건 이상이고 정밀도 90% 이상이면 통과(종료 코드 0), 아니면 1. 처음 보는 쪽에서만 뜻이 있다

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
JUDGE_MIN, JUDGE_RATE = 40, 0.90


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
    """후보 하나를 적용했을 때의 채점: ok·wrong·unpaired(짝 없는 조각)·no_gt·outside(정답지 영역 밖)·moved(상자가 어긋남)."""
    import check_read_quality as rq
    n = next((n for n in ex["nodes"] if n["source_object_id"] == c["target"]), None)
    if n is None or max(abs(a - b) for a, b in zip(rq._bbox(n), c["bbox"])) > 0.6:
        return "moved"
    if not rq._in_region(n, key["regions"]):
        return "outside"
    one = {"candidates": [{"node_local_id": n["local_id"], "field": c["field"], "values": c["values"]}]}
    m = rq.match_symbols(key["symbols"], rq.apply_candidates(ex, one)["nodes"])
    s = next((s for s in key["symbols"] if s["id"] in m and m[s["id"]]["local_id"] == n["local_id"]), None)
    if s is None:
        return "unpaired"
    v = c["values"][0]
    if c["field"] == "kind":
        return "ok" if rq.same_kind(v, s["kind"]) else "wrong"
    if c["field"] == "tag":
        return "no_gt" if not s.get("tag") else "ok" if rq.same_tag(v, s["tag"]) else "wrong"
    want = (s.get("attributes") or {}).get(c["field"])
    return "no_gt" if not want else "ok" if rq._same_value(c["field"], v, want) else "wrong"


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


def simulate(args, name, ex, cands):
    """앱과 같은 길(merge_and_save → auto_accept)로 임시 작업 루트에서 수락해 본다 → (수락한 cand_id, 막힌 까닭, 고친 추출)."""
    from unittest import mock
    from hazop import paths
    from hazop.extract import ai_review, corrections
    d = os.path.join(paths.output_root("extract"), name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "extraction.json"), "w", encoding="utf-8") as fh:
        json.dump(ex, fh, ensure_ascii=False)
    ai_review.merge_and_save(name, ex, {"candidates": cands, "stats": {"calls": 0}}, auto=True)
    with mock.patch.object(ai_review, "AUTO_ACCEPT_ENABLED", True):
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
    return {"page": page, "task": c["task"], "field": c["field"], "value": c["values"][0], "conf": c["confidence"], "res": score(c, ex, key)}


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
    rows, accepted, total = [], [], collections.Counter()
    if seqs:
        client = providers.make_client("fixed", response_dir=args.responses)
        for seq in seqs:
            name = page_name(seq)
            pdf, ex = extract(args, seq, work)
            key = load_key(args.keys, name)
            cands = replay(args, ex, pdf, client)["candidates"]
            scored = {c["cand_id"]: row(name, c, ex, key) for c in cands}
            rows += scored.values()
            got, blocked, after = simulate(args, name, ex, cands)
            accepted += [scored[i] for i in got]
            n0, n1 = (confirmation.check(e)["counts"]["unknown_symbol"] for e in (ex, after))
            total.update({"before": n0, "after": n1})
            if not args.held:
                kinds = collections.Counter(scored[i]["field"] for i in got)
                res = collections.Counter("%s:%s" % (scored[i]["field"], scored[i]["res"]) for i in got)
                print("%s 자동 수락 종류 %d·태그 %d %s | 막힘 %s | 종류 미정 %d → %d | DEXPI %s → %s"
                      % (name, kinds["kind"], kinds["tag"], dict(res), dict(sorted(blocked.items())), n0, n1, dexpi(ex), dexpi(after)), flush=True)
        table("재생한 응답 %d쪽" % len(seqs), rows)
        for field in ("kind", "tag"):
            rs = [r for r in accepted if r["field"] == field]
            in_key = [r for r in rs if r["res"] not in ("moved", "outside")]
            print("자동 수락 %s %d건: 정답지 영역 안 %d건 가운데 맞음 %d %s" % (
                field, len(rs), len(in_key), sum(r["res"] == "ok" for r in in_key), dict(collections.Counter(r["res"] for r in rs))))
        print("종류 미정 기호 %d → %d" % (total["before"], total["after"]))
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
        kinds = [r for r in accepted if r["field"] == "kind" and r["res"] not in ("moved", "outside")]
        ok = sum(r["res"] == "ok" for r in kinds)
        verdict = "판정 못 함(후보 %d건 미만)" % JUDGE_MIN if len(kinds) < JUDGE_MIN else "통과" if ok / len(kinds) >= JUDGE_RATE else "실패"
        print("판정: %s (%d/%d)" % (verdict, ok, len(kinds)))
        return 0 if verdict == "통과" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
