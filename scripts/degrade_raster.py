"""T3 W5 열화 시험: 샘플 PNG에 열화를 한 가지씩 단계별로 적용해 래스터 어댑터 지표를 잰다.

사용 예(래스터 venv, 결정 D7):
  python scripts/degrade_raster.py                 # 전체 조건 × 샘플 6장, 표를 화면에 출력
  python scripts/degrade_raster.py --out 폴더       # 폴더/results.json·summary.md 저장(저장소 밖 폴더 권장)
  python scripts/degrade_raster.py --only scale    # 한 축만(scale·noise·rotate·jpeg·jpg_file)

입력은 check_adapter.raster_samples()와 같다(`.drawio.png` 제외, 결정 D1 블라인드). 정답은 같은 폴더 `.drawio`의
drawio.extract()(메모리). 열화 영상은 실행 중 임시 폴더에만 만들고 끝나면 지운다.
열화는 한 번에 한 축만 바꾸고 나머지는 원본 그대로 둔다(기준 = 원본 PNG 파일 그대로).
  - scale  : Pillow LANCZOS로 가로·세로를 같은 비율로 줄임(100% = 원본)
  - noise  : 회색조(L)로 바꾼 뒤 평균 0·표준편차 σ(회색 단계 0~255)의 가우시안 잡음, 0~255로 자름. 샘플별 고정 씨앗
  - rotate : 중심 기준 반시계 회전, 크기 유지(expand 없음), 빈 곳은 흰색, BICUBIC
  - jpeg   : Pillow JPEG 저장(quality 지정, 그 밖 기본값)
  - jpg_file: 샘플 폴더에 이미 있는 .jpg 파일 그대로(참고)
측정은 check_adapter.evaluate_raster와 같은 순서(추출 → blocker → 그래프 단계 호환 → 정렬 → 평가 → 품질 하한)이고,
두 번 실행 결정성 검사는 하지 않는다. 어댑터 예외는 죽지 않고 그 조건의 결과로 기록한다.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_adapter as ca  # noqa: E402
from hazop.console import safe_console  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.extract.adapters import align, raster  # noqa: E402
from hazop.extract.adapters import evaluation as ev  # noqa: E402

# (축, 단계 값) — 작업지시서 W5 단계. 기준(100%·σ0·0°)은 축마다 따로 돌리지 않고 "base" 한 번만 잰다.
CONDITIONS = ([("base", None)]
              + [("scale", v) for v in (75, 50, 35)]
              + [("noise", v) for v in (5, 10, 20)]
              + [("rotate", v) for v in (0.5, 1.0, 2.0)]
              + [("jpeg", v) for v in (95, 75, 50)]
              + [("jpg_file", None)])
SEED = 20261106


def label(axis, value):
    return {"base": "기준(원본 PNG)", "scale": "해상도 %s%", "noise": "잡음 σ%s", "rotate": "회전 %s°",
            "jpeg": "JPEG q%s", "jpg_file": "샘플 .jpg 파일"}[axis].replace("%s", str(value))


def make_input(axis, value, png_path, tmp, idx):
    """열화 영상 경로. base·jpg_file은 원본 파일 경로를 그대로 돌려준다."""
    if axis == "base":
        return png_path
    if axis == "jpg_file":
        return os.path.splitext(png_path)[0] + ".jpg"
    import numpy as np
    from PIL import Image
    im = Image.open(png_path)
    im.load()
    out = os.path.join(tmp, "%d_%s_%s.%s" % (idx, axis, value, "jpg" if axis == "jpeg" else "png"))
    if axis == "scale":
        w, h = im.size
        im = im.resize((max(1, round(w * value / 100.0)), max(1, round(h * value / 100.0))), Image.LANCZOS)
    elif axis == "noise":
        a = np.asarray(im.convert("L"), dtype=np.float64)
        a = a + np.random.default_rng(SEED + idx).normal(0.0, value, a.shape)
        im = Image.fromarray(np.clip(np.rint(a), 0, 255).astype(np.uint8), "L")
    elif axis == "rotate":
        fill = 255 if im.mode == "L" else (255,) * len(im.getbands())
        im = im.rotate(value, resample=Image.BICUBIC, expand=False, fillcolor=fill)
    if axis == "jpeg":
        im.convert("RGB").save(out, "JPEG", quality=value)
    else:
        im.save(out, "PNG")
    return out


def measure(name, truth, path):
    """한 조건의 결과 dict. 예외·정렬 실패·평가 실패도 결과로 남긴다."""
    r = {"input_bytes": os.path.getsize(path)}
    t0 = time.time()
    try:
        cand = raster.extract(path, repo_root=REPO_ROOT)
    except Exception as exc:  # 열화로 어댑터가 죽는 사례를 기록한다(작업지시서)
        r.update(outcome="exception", error="%s: %s" % (type(exc).__name__, exc),
                 trace=traceback.format_exc(limit=4))
        return r
    r["seconds"] = round(time.time() - t0, 1)
    s = cand["summary"]
    r.update(blockers=len(cand["validation"]["blockers"]), status=cand["validation"]["status"],
             nodes=s["nodes"], relations=s["relations"], unresolved=s["unresolved_connectors"], texts=s["texts"],
             unknowns=s["unknowns"], truth_nodes=len(truth["nodes"]), truth_relations=len(truth["relations"]),
             graph_problems=ca.graph_problems(name, cand))
    al = align.estimate_transform(truth, cand)
    r["alignment"] = {k: al.get(k) for k in ("status", "reason", "anchors_used", "anchors_total", "residual_rms",
                                             "residual_max", "transform")}
    if al["status"] != "ok":
        r["outcome"] = "align_failed"
        return r
    res = ev.evaluate(truth, cand, al["transform"])
    if res["status"] != "ok":
        r.update(outcome="eval_failed", eval_reasons=res.get("reasons"))
        return r
    keep = ("tp", "fp", "fn", "precision", "recall", "f1")
    r.update(outcome="ok", relations_m={k: res["relations"][k] for k in keep},
             objects_m={k: res["objects"][k] for k in keep}, tags_m={k: res["tags"][k] for k in keep},
             kind_accuracy=res["objects"]["kind_accuracy"])
    row = {"name": name, "relations": res["relations"], "objects": res["objects"]}
    r["floor_problems"] = ca.quality_problems(row, ca.RASTER_QUALITY_FLOORS)
    return r


def _f(v):
    return "-" if v is None else "%.3f" % v


def cell(r):
    """표 칸: 관계/객체/태그 F1 · kind · blocker, 하한 미달은 *."""
    if r["outcome"] == "exception":
        return "예외 " + r["error"].split(":")[0]
    if r["outcome"] != "ok":
        return "%s(b%d)" % (r["outcome"], r.get("blockers", 0))
    star = "*" if r["floor_problems"] else ""
    return "%s%s / %s / %s / %s / b%d" % (star, _f(r["relations_m"]["f1"]), _f(r["objects_m"]["f1"]),
                                          _f(r["tags_m"]["f1"]), _f(r["kind_accuracy"]), r["blockers"])


def summary_table(results, names, conds):
    short = [n.split("_")[0].replace("SNP-M-", "") for n in names]
    lines = ["| 조건 | " + " | ".join(short) + " | 하한 미달 | 관계 F1 평균 |",
             "|---|" + "---|" * len(names) + "---|---|"]
    for axis, value in conds:
        rs = [results[(axis, value, n)] for n in names]
        below = sum(1 for r in rs if r["outcome"] != "ok" or r["floor_problems"])
        f1s = [r["relations_m"]["f1"] or 0.0 if r["outcome"] == "ok" else 0.0 for r in rs]
        lines.append("| %s | %s | %d/%d | %.3f |" % (label(axis, value), " | ".join(cell(r) for r in rs), below,
                                                   len(rs), sum(f1s) / len(f1s)))
    return "\n".join(lines) + "\n"


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="results.json·summary.md를 저장할 폴더(저장소 밖 권장)")
    ap.add_argument("--only", choices=sorted({a for a, _ in CONDITIONS}), help="이 축과 기준만 잰다")
    args = ap.parse_args(argv)
    has_cv, has_ocr = raster.available()
    if not (has_cv and has_ocr):
        print("OpenCV 또는 rapidocr 없음(결정 D7): 래스터 venv로 실행할 것")
        return 2
    conds = [c for c in CONDITIONS if args.only is None or c[0] in ("base", args.only)]
    samples = ca.raster_samples()
    names = [n for n, _, _ in samples]
    results = {}
    tmp = tempfile.mkdtemp(prefix="hazop-w5-")
    try:
        for idx, (name, drawio_path, png_path) in enumerate(samples):
            truth = drawio.extract(drawio_path, repo_root=REPO_ROOT)
            for axis, value in conds:
                path = make_input(axis, value, png_path, tmp, idx)
                r = measure(name, truth, path)
                results[(axis, value, name)] = r
                print("%-26s %-16s %s" % (name, label(axis, value), cell(r)), flush=True)
                if path.startswith(tmp):
                    os.remove(path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    table = summary_table(results, names, conds)
    print(table)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        rows = [dict(axis=a, value=v, name=n, **r) for (a, v, n), r in sorted(results.items(), key=lambda x: str(x[0]))]
        with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(table)
        print("저장: %s" % args.out)
    crashed = sum(1 for r in results.values() if r["outcome"] == "exception")
    print("예외 %d건" % crashed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
