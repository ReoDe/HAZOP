"""스캔 읽기 품질 측정: 벡터 PDF 쪽을 그림으로 그려 스캔 읽기로 추출하고, 벡터 읽기와 같은 정답지·채점으로 잰다
(규격 docs/specs/raster-extraction.md §5, HZ-PLN-23).

  python scripts/check_scan_quality.py                      # SNP 6장(정답 = 같은 도면 drawio), 300dpi
  python scripts/check_scan_quality.py --apr 12,62,105      # APR1400 정답지 쪽도(쪽 PDF가 저장소 밖에 있을 때)
  python scripts/check_scan_quality.py --dpi 200 --json 결과.json
  python scripts/check_scan_quality.py --degrade             # 실제 스캔처럼 기울기·번짐·잡음·JPEG을 넣은 그림으로

시험 venv(pypdfium2·pdfplumber)로 돌린다. 쪽 그리기는 이 프로세스가 하고, 그림 읽기(OpenCV·OCR)는 이 프로세스에
OpenCV가 없으면 래스터 venv(HAZOP_RASTER_PYTHON 또는 %USERPROFILE%\\.hazop\\venv-raster-py312)를 하위 프로세스로 부른다.
채점 함수는 scripts/check_read_quality.py의 것을 가져다 쓰기만 한다. 결과 좌표는 px ÷ (dpi/72)로 쪽 좌표(pt)로 바꿔 잰다.
깨끗한 렌더링 그림이라 실제 스캔보다 좋게 나온다. 기준값 비교는 하지 않는다(값을 보이기만, 종료 코드 0).
"""

import argparse
import glob
import json
import os
import shutil
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_read_quality as rq  # noqa: E402
from hazop.console import safe_console  # noqa: E402
from hazop.extract.adapters import raster_scan  # noqa: E402

ITEMS = rq.ITEMS


def jobs_for(input_dir, samples_dir, apr, snp, work):
    """[(이름, 정답지, 쪽 PDF)]."""
    import extract_drawio
    out = []
    if snp:
        for folder in rq.snp_folders(samples_dir):
            dio_path = glob.glob(os.path.join(folder, "*.drawio"))
            pdf = glob.glob(os.path.join(folder, "*.pdf"))
            if dio_path and pdf:
                dio, _ = extract_drawio.run_one(dio_path[0], os.path.join(work, "extract"))
                name = os.path.basename(folder).split("_")[0]
                out.append((name, rq.snp_key(dio, pdf[0], name), pdf[0]))
    missing = []
    for name, k in rq.load_keys(apr) if apr else []:
        pdf = rq.apr_pdf(input_dir, k["seq"]) if os.path.isdir(input_dir) else None
        if pdf is None:
            missing.append(name)
        else:
            out.append((name, k, pdf))
    return out, missing


# 실제 스캔다운 입력(--degrade): 종이를 조금 비뚤게 놓고(0.7°), 스캐너 광학으로 번지고(가우시안 반지름 1px@300dpi),
# 센서 잡음(σ 8 회색 단계)이 끼고, JPEG(품질 75)으로 저장한 꼴. 값은 W5 열화 시험(scripts/degrade_raster.py) 단계 가운데
# 중간 값을 한데 묶은 것이다. 씨앗을 고정해 같은 그림이 나온다.
DEGRADE = {"rotate_deg": 0.7, "blur_px_at_300": 1.0, "noise_sigma": 8.0, "jpeg_quality": 75, "seed": 20261114}
NOISE_TILE = 512


def degrade(png, dpi, idx=0):
    """그린 쪽 그림 → 스캔다운 JPG 경로(png 옆). DEGRADE 값을 쓴다."""
    import random
    from PIL import Image, ImageChops, ImageFilter
    with Image.open(png) as im:
        im = im.convert("L")
        im = im.rotate(DEGRADE["rotate_deg"], resample=Image.BICUBIC, expand=False, fillcolor=255)
        im = im.filter(ImageFilter.GaussianBlur(DEGRADE["blur_px_at_300"] * dpi / 300.0))
        # 잡음: 시험 venv에는 numpy가 없어 씨앗 고정 가우시안 512×512 조각을 깔아 더한다(128 = 0)
        rng, n = random.Random(DEGRADE["seed"] + idx), NOISE_TILE
        tile = Image.frombytes("L", (n, n), bytes(min(255, max(0, int(round(128 + rng.gauss(0.0, DEGRADE["noise_sigma"])))))
                                                  for _ in range(n * n)))
        noise = Image.new("L", im.size)
        for y in range(0, im.size[1], n):
            for x in range(0, im.size[0], n):
                noise.paste(tile, (x, y))
        im = ImageChops.add(im, noise, scale=1.0, offset=-128)
        out = os.path.splitext(png)[0] + "-scan.jpg"
        im.save(out, "JPEG", quality=DEGRADE["jpeg_quality"])
    return out


def measure(jobs, dpi, work, use_ocr=True, log=print, degraded=False):
    from hazop.extract.adapters import pdf_vector
    res = {"vector": {}, "scan": {}, "seconds": {}, "unknowns": {}}
    for name, key, pdf in jobs:
        res["vector"][name] = rq.score_page(key, pdf_vector.extract(pdf, page=0, repo_root=work))
        png = os.path.join(work, "%s-%ddpi.png" % (name, dpi))
        scale = raster_scan.render_pdf_page(pdf, 0, png, dpi)
        img = degrade(png, dpi, len(res["seconds"])) if degraded else png
        t = time.time()
        ex = raster_scan.run_raster(img, px_per_pt=scale, use_ocr=use_ocr)
        res["seconds"][name] = round(time.time() - t, 1)
        for f in {png, img}:
            os.remove(f)
        res["scan"][name] = rq.score_page(key, raster_scan.to_page_points(ex, scale))
        res["unknowns"][name] = len(ex["validation"]["unknowns"])
        log("  %s: 벡터 %s | 스캔 %s (%.1f초)" % (name, line(res["vector"][name]), line(res["scan"][name]),
                                              res["seconds"][name]))
    return res


def line(page):
    return " · ".join("%s %d/%d" % (it[:4], page[it]["correct"], page[it]["units"] + page[it]["false_pos"])
                      for it in ITEMS)


def pct(c):
    a = rq.accuracy(c)
    return None if a is None else round(100 * a, 1)


def report(res, dpi, at, degraded=False):
    cond = ("스캔다운 열화(기울기 %(rotate_deg)s°, 번짐 %(blur_px_at_300)spx@300dpi, 잡음 σ%(noise_sigma)s, JPEG q%(jpeg_quality)s)"
            % DEGRADE) if degraded else "깨끗한 렌더링"
    out = ["스캔 읽기 품질 @%s, %ddpi 회색조(pypdfium2) %s, 정답지·채점 = check_read_quality" % (at, dpi, cond)]
    for lab, prefix in (("SNP 합계", "SNP-"), ("APR1400 합계", "apr1400-"), ("전체 합계", None)):
        names = [n for n in res["scan"] if prefix is None or n.startswith(prefix)]
        if not names:
            continue
        v = rq.totals({n: res["vector"][n] for n in names})
        s = rq.totals({n: res["scan"][n] for n in names})
        out.append("%s(%d쪽)" % (lab, len(names)))
        for it in ITEMS:
            dv, ds = pct(v[it]), pct(s[it])
            diff = "—" if dv is None or ds is None else "%+.1f%%p" % (ds - dv)
            out.append("  %-6s 벡터 %s · 스캔 %s · 차이 %s" % (rq.ITEM_LABEL[it], rq.fmt(v[it]), rq.fmt(s[it]), diff))
    return "\n".join(out)


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--apr", help="APR1400 정답지 쪽 번호(쉼표), 예: 12,62,105. 'all'이면 정답지 전부")
    ap.add_argument("--no-snp", action="store_true", help="SNP 6장을 빼고 APR1400 쪽만")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--degrade", action="store_true", help="실제 스캔처럼 기울기·번짐·잡음·JPEG을 넣어 읽는다(DEGRADE)")
    ap.add_argument("--input-dir", help="APR1400 쪽 PDF 폴더(기본: 참고자료 by-drawing)")
    ap.add_argument("--samples-dir", help="SNP 표본 폴더(기본: 참고자료 pid-samples)")
    ap.add_argument("--json", help="쪽별 값을 이 파일에 쓴다")
    args = ap.parse_args(argv)
    if not raster_scan.raster_python() and not raster_scan.raster.available()[0]:
        print("스캔 읽기 의존성(OpenCV) 없음: 래스터 venv가 필요하다(packaging/requirements-raster.txt)")
        return 2
    apr = None
    if args.apr:
        apr = None if args.apr == "all" else {int(x) for x in args.apr.split(",") if x.strip()}
        if args.apr == "all":
            apr = {k["seq"] for _, k in rq.load_keys()}
    input_dir = os.path.abspath(args.input_dir or rq.default_input_dir())
    samples_dir = os.path.abspath(args.samples_dir or rq.default_samples_dir())
    work = tempfile.mkdtemp(prefix="hazop-scan-quality-")
    os.environ["HAZOP_WORK_ROOT"] = work
    try:
        jobs, missing = jobs_for(input_dir, samples_dir, apr, not args.no_snp, work)
        res = measure(jobs, args.dpi, work, use_ocr=not args.no_ocr, degraded=args.degrade)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    at = rq.head_commit()
    print(report(res, args.dpi, at, args.degrade))
    if missing:
        print("쪽 PDF가 없어 건너뜀: %s" % ", ".join(missing))
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(dict(res, dpi=args.dpi, at=at, missing=missing, degrade=DEGRADE if args.degrade else None), fh,
                      ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
