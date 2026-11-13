"""스캔 도면 입력: 판별·해상도·쪽 그리기·래스터 읽기 부르기(규격 docs/specs/raster-extraction.md, HZ-PLN-23).

이 모듈은 OpenCV·numpy를 쓰지 않는다. 시험 venv와 배포본에 있는 pypdfium2·Pillow로 PDF 쪽과 그림 머리말만 읽고,
선·기호·글자 읽기는 raster.extract에 맡긴다. 같은 프로세스에 OpenCV가 없으면 래스터 venv의 Python을 하위
프로세스로 불러 scripts/extract_raster.py --json-out으로 결과를 받는다(§4).

- classify_pdf_page: 쪽이 벡터·스캔·섞임·빈 쪽 중 무엇인지와 그림의 해상도(§2).
- image_scale: PNG·JPG의 해상도. 파일에 믿을 만한 dpi가 없으면 그림 폭을 A3 가로로 가정한다(§2.2).
- extract_scan_pdf: 스캔 PDF 한 쪽을 원래 해상도(400dpi 상한)로 그려 래스터 읽기로 추출한다.
- to_page_points: 추출 결과의 px 좌표를 쪽 좌표(pt)로 바꾼다(채점·겹쳐 보기용).
"""

import copy
import hashlib
import importlib
import io
import json
import os
import shutil
import subprocess
import tempfile

from hazop import paths

from . import raster

# §2.1 스캔 PDF 판별 문턱
SCAN_MAX_PATHS = 10          # 스캐너가 붙이는 여백 선·쪽 번호 몇 개는 봐준다(추정)
SCAN_MIN_COVER = 0.8         # 가장 큰 그림이 쪽 넓이의 이 비율 이상을 덮으면 스캔
MIXED_MIN_COVER = 0.3        # 벡터 내용과 함께 이 비율 이상의 그림이 있으면 섞인 PDF
# §2.2 해상도
DPI_OK = 300
DPI_LOW = 200
DPI_READ_MAX = 400           # 이보다 높은 입력은 이 해상도로 줄여 읽는다
DPI_TRUST = (150, 1200)      # 그림 파일에 적힌 dpi를 믿는 범위(72·96 같은 화면 값과 비율 값은 믿지 않음)
RASTER_VENV = os.path.join(os.path.expanduser("~"), ".hazop", "venv-raster-py312")


def resolution_level(dpi):
    """ok(300dpi 이상) / low(200 이상) / too_low."""
    return "ok" if dpi >= DPI_OK else ("low" if dpi >= DPI_LOW else "too_low")


def resolution_guidance(dpi):
    """등급이 ok가 아니면 사용자 안내 문구(§2.2), ok면 None."""
    level = resolution_level(dpi)
    if level == "ok":
        return None
    if level == "low":
        return ("해상도가 낮아(%d dpi) 작은 글자를 놓칠 수 있습니다. 300dpi 이상으로 다시 스캔하면 낫습니다."
                % round(dpi))
    return ("해상도가 너무 낮아(%d dpi) 선과 기호가 끊겨 읽기 결과가 크게 떨어집니다. 300dpi 이상으로 다시 "
            "스캔해 주세요." % round(dpi))


def read_dpi(dpi):
    """읽을 때 쓸 해상도: 원래 해상도, 단 DPI_READ_MAX 상한."""
    return min(float(dpi), DPI_READ_MAX)


def trusted_dpi(dpi):
    """그림 파일에 적힌 dpi를 믿을 수 있으면 그 값, 아니면 None."""
    if dpi is None:
        return None
    try:
        v = float(dpi)
    except (TypeError, ValueError):
        return None
    v = round(v, 1)  # 그림 파일의 dpi는 단위 환산으로 199.9996처럼 저장된다
    return v if DPI_TRUST[0] <= v <= DPI_TRUST[1] else None


def _scale_info(px_per_pt, source):
    dpi = px_per_pt * 72.0
    return {"px_per_pt": round(px_per_pt, 6), "dpi": round(dpi, 1), "dpi_source": source,
            "level": resolution_level(dpi)}


# ---------------------------------------------------------------- 판별

def _pdfium():
    return importlib.import_module("pypdfium2")


def classify_pdf_page(data, page=0):
    """PDF(바이트 또는 경로)의 한 쪽 → {kind: vector|scan|mixed|empty, page_pt, image_px, px_per_pt, dpi,
    dpi_source, level, text_layer, paths, chars, image_cover}. 스캔·섞임이 아니면 해상도 값은 None."""
    pdfium = _pdfium()
    doc = pdfium.PdfDocument(data)
    try:
        pg = doc[page]
        pw, ph = (float(v) for v in pg.get_size())
        tp = pg.get_textpage()
        chars = tp.count_chars()
        tp.close()
        n_paths, best = 0, None
        for obj in pg.get_objects(max_depth=3):
            if obj.type == pdfium.raw.FPDF_PAGEOBJ_PATH:
                n_paths += 1
            elif obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                left, bottom, right, top = obj.get_bounds()
                area = max(0.0, right - left) * max(0.0, top - bottom)
                if best is None or area > best[0]:
                    best = (area, right - left, top - bottom, obj.get_px_size())
        pg.close()
    finally:
        doc.close()
    cover = best[0] / (pw * ph) if best and pw * ph else 0.0
    if best and cover >= SCAN_MIN_COVER and n_paths <= SCAN_MAX_PATHS:
        kind = "scan"
    elif n_paths or chars:
        kind = "mixed" if cover >= MIXED_MIN_COVER else "vector"
    else:
        kind = "scan" if best else "empty"
    out = {"kind": kind, "page_pt": [round(pw, 2), round(ph, 2)], "image_px": None, "px_per_pt": None, "dpi": None,
           "dpi_source": None, "level": None, "text_layer": bool(chars), "paths": n_paths, "chars": chars,
           "image_cover": round(cover, 3)}
    if kind in ("scan", "mixed") and best and best[1] > 0 and best[2] > 0:
        (iw, ih) = best[3]
        ppt = (iw / best[1] + ih / best[2]) / 2.0
        out.update(_scale_info(ppt, "pdf_image"))
        out["image_px"] = [int(iw), int(ih)]
    return out


def image_scale(data):
    """PNG·JPG 바이트 → {px_per_pt, dpi, dpi_source(file|assumed_a3), level, image_px}."""
    image = importlib.import_module("PIL.Image")
    with image.open(io.BytesIO(data)) as im:
        w, h = im.size
        dpi = (im.info.get("dpi") or (None,))[0]
    good = trusted_dpi(dpi)
    if good is not None:
        out = _scale_info(good / 72.0, "file")
    else:
        out = _scale_info(w / raster.PARAMS["nominal_page_width_pt"], "assumed_a3")
    out["image_px"] = [w, h]
    return out


# ---------------------------------------------------------------- 그리기·읽기

def render_pdf_page(path, page, out_png, dpi):
    """PDF 쪽을 dpi 해상도의 회색조 PNG로 그린다. → 실제 px/pt(= dpi/72)."""
    pdfium = _pdfium()
    doc = pdfium.PdfDocument(path)
    try:
        pg = doc[page]
        scale = float(dpi) / 72.0
        bitmap = pg.render(scale=scale, grayscale=True)
        bitmap.to_pil().save(out_png)
        bitmap.close()
        pg.close()
    finally:
        doc.close()
    return scale


def raster_python():
    """래스터 venv Python 경로(HAZOP_RASTER_PYTHON, 없으면 기본 venv). 없으면 None."""
    env = os.environ.get("HAZOP_RASTER_PYTHON")
    cands = [env] if env else [os.path.join(RASTER_VENV, "Scripts", "python.exe"),
                               os.path.join(RASTER_VENV, "bin", "python")]
    return next((c for c in cands if c and os.path.isfile(c)), None)


class ScanReaderUnavailable(RuntimeError):
    """스캔 읽기 의존성(OpenCV)이 이 프로세스에도 없고 래스터 venv도 없다(§7 blocker scan_reader_unavailable)."""


def run_raster(png_path, px_per_pt=None, repo_root=None, use_ocr=True):
    """그림 한 장 → 추출 결과. 이 프로세스에 OpenCV가 있으면 바로, 없으면 래스터 venv 하위 프로세스로."""
    params = {"px_per_pt": px_per_pt} if px_per_pt else None
    if raster.available()[0]:
        return raster.extract(png_path, repo_root=repo_root, params=params, use_ocr=use_ocr)
    py = raster_python()
    if py is None:
        raise ScanReaderUnavailable("스캔 도면을 읽으려면 스캔 읽기 묶음(래스터 venv)이 필요합니다")
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    out_dir = tempfile.mkdtemp(prefix="hazop-raster-run-")
    try:
        out = os.path.join(out_dir, "extraction.json")
        cmd = [py, os.path.join(repo, "scripts", "extract_raster.py"), png_path, "--json-out", out]
        if px_per_pt:
            cmd += ["--px-per-pt", repr(float(px_per_pt))]
        if repo_root:
            cmd += ["--repo-root", repo_root]
        if not use_ocr:
            cmd.append("--no-ocr")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        if proc.returncode not in (0, 1) or not os.path.isfile(out):
            raise RuntimeError("래스터 읽기 실패(종료 코드 %d): %s" % (proc.returncode,
                                                                (proc.stdout + proc.stderr).strip()[-500:]))
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def extract_scan_pdf(path, page=0, repo_root=None, use_ocr=True):
    """스캔 PDF 한 쪽 → 추출 결과(좌표 image_px, coordinate_system에 px_per_pt·쪽 번호). 스캔 쪽이 아니면 ValueError."""
    info = classify_pdf_page(path, page)
    if info["kind"] != "scan":
        raise ValueError("스캔 쪽이 아님(%s): %s 쪽 %d" % (info["kind"], path, page + 1))
    with open(path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    with _pdfium().PdfDocument(path) as doc:
        page_count = len(doc)
    work = tempfile.mkdtemp(prefix="hazop-scan-page-")
    try:
        png = os.path.join(work, "page-%d.png" % (page + 1))
        scale = render_pdf_page(path, page, png, read_dpi(info["dpi"]))
        ex = run_raster(png, px_per_pt=scale, use_ocr=use_ocr)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    label = paths.rel_or_abs(path, repo_root) if repo_root else path
    ex["source"].update({"format": "raster_scan_pdf", "file": label, "sha256": sha, "page_count": page_count})
    ex["source_context"]["page_id"] = "page-%d" % (page + 1)
    ex["run"]["settings"]["page_index"] = page
    ex["run"]["settings"]["scan"] = info
    ex["coordinate_system"].update({"px_per_pt": round(scale, 6), "page_index": page,
                                    "origin": "쪽을 %.0f dpi로 그린 그림의 왼쪽 위 픽셀, x 오른쪽·y 아래쪽 증가. "
                                              "쪽 좌표(pt) = px ÷ px_per_pt" % (scale * 72)})
    stem = os.path.splitext(os.path.basename(path))[0]
    ex["extraction_run_id"] = "extract-scan-%s-p%d-%s-%s" % (ex["drawing"].get("drawing_number") or stem, page,
                                                            raster.RULES_VERSION, sha[:12])
    raster.note_scale(ex, {"dpi": info["dpi"], "dpi_source": "pdf_image", "level": info["level"]})
    return ex


# ---------------------------------------------------------------- 좌표

def to_page_points(ex, px_per_pt):
    """추출 결과의 px 좌표(노드 geometry, 관계 끝점·꺾임점)를 쪽 좌표(pt)로 바꾼 사본."""
    out = copy.deepcopy(ex)
    k = float(px_per_pt)

    def pt(p):
        return [round(v / k, 3) for v in p]

    for n in out.get("nodes", []):
        g = n.get("geometry")
        if g:
            n["geometry"] = {key: (round(v / k, 3) if key in ("x", "y", "width", "height") and v is not None else v)
                             for key, v in g.items()}
    for r in out.get("relations", []):
        for e in r.get("endpoints", []):
            if e.get("point") is not None:
                e["point"] = pt(e["point"])
        if r.get("waypoints"):
            r["waypoints"] = [pt(p) for p in r["waypoints"]]
    cs = out.setdefault("coordinate_system", {})
    cs.update({"coordinate_space": "page_pt_from_image", "unit": "pt"})
    return out

