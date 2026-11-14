"""래스터(PNG·JPG) P&ID → 추출 결과(extraction.json, drawio 경로와 같은 스키마) (T3 W4, 결정 D1·D7).

영상에서 선·기호·글자를 찾아 벡터 PDF 어댑터(pdf_vector)가 받는 원시 요소 형식으로 바꾼 뒤, 같은 형상·연결·분류
규칙(pdf_vector.analyze·build_extraction)을 그대로 쓴다. 샘플 파일별 분기는 두지 않는다.

1. 잉크: 회색조 이진화(Otsu). 글자 인식(OCR, rapidocr-onnxruntime)이 있으면 글자 상자 안에 통째로 들어가는
   잉크 덩어리(글자 획)를 뺀다. OCR이 없으면 글자 없이 진행하고 미확인 `ocr_unavailable`(끈 경우 `ocr_disabled`)을 남긴다.
2. 채운 도형: 원판 열림(opening)을 견디는 잉크 = 검은 채움(화살촉·검은 원 등). 크기 판정은 pdf_vector가 한다.
3. 기호 몸체: 잉크로 둘러싸인 흰 영역(구멍) 중 크기·볼록도가 맞는 것. 선 하나로 갈라진 원(계기 원의 가운데 선)은
   합친 모양이 원이면 하나로 합친다. 윤곽은 선 두께 절반만큼 넓혀 다각형(원은 곡선 표시)으로 둔다.
4. 선: 몸체·채움·글자 잉크를 뺀 나머지에서 가로·세로 긴 획(형태학 열림)을 선분으로, 남은 가늘고 긴 덩어리를
   사선으로, 짧은 조각이 이웃과 사슬을 이루면 점선 조각으로 둔다. 꺾임·분기는 선 끝을 상대 선 중심선으로 맞춘다.
   같은 직선 위 두 선 사이 빈칸이 글자 상자로 덮여 있으면(선 라벨의 흰 바탕) 잇고 그 글자 상자를 흰 바탕 마스크로 둔다.
   페이지 폭·높이의 대부분을 덮는 가로·세로 선(도면 테두리)은 버린다.
5. 좌표: 이미지 px, 원점 왼쪽 위, x 오른쪽·y 아래쪽 증가. pdf_vector 문턱(pt)은 실제 배율(params px_per_pt: 스캔 PDF,
   dpi가 적힌 그림)로, 없으면 이미지 폭을 공칭 페이지 폭(A3 가로 1190.55pt)에 맞춘 배율로 px로 바꿔 쓴다.
   drawio 좌표로의 변환은 추정하지 않는다(평가 쪽 align.py).
6. 스캔 입력(HZ-PLN-23): 읽기 전에 기울기를 재서 0.05°~5°이면 바로잡는다(deskew). OCR은 W4 조건의 낮은 배율로 한 번,
   그림이 더 고우면 원래 해상도 타일로 한 번 더 읽어 겹치지 않는 줄만 더한다. 해상도 안내는 미확인(scan_input 등)으로 단다.

OpenCV(cv2)·numpy·rapidocr는 importlib로 함수 안에서만 읽는다. 앱·배포 빌드(PyInstaller는 import 문을 정적으로
따라간다)가 이 의존성을 끌어오지 않게 하기 위해서다(결정 D7). 설치: packaging/requirements-raster.txt.
"""

import hashlib
import importlib
import importlib.util
import math
import os
import re

from hazop import paths

from . import pdf_vector as pv

SCRIPT_NAME = "hazop.extract.adapters.raster"
SCRIPT_VERSION = "0.1.0"
RULES_VERSION = "raster-rules-0.1.0+" + pv.RULES_VERSION
COORDINATE_SPACE = "image_px"
UNIT = "px"
FORMATS = {".png": "raster_png", ".jpg": "raster_jpeg", ".jpeg": "raster_jpeg"}
MAX_FILE_BYTES = 100 * 1024 * 1024  # 해독 전 파일 크기 상한(샘플 PNG는 1 MB 안팎)
MAX_PIXELS = 50_000_000             # 해독 전후 픽셀 수 상한(50 MP, 샘플은 7.5 MP)

# 래스터 단계 문턱. 길이는 pt(공칭 페이지 기준)이며 실행 때 px로 바꾼다. 샘플 6세트 PNG로 정한 값(표본 내).
PARAMS = {
    "nominal_page_width_pt": 1190.55,  # 공칭 페이지 폭(A3 가로 420mm) → px/pt 배율 = 이미지 폭 / 이 값
    "px_per_pt": None,           # 실제 배율(스캔 PDF·dpi가 적힌 그림, HZ-PLN-23 §3.1). 있으면 공칭 페이지 폭 대신 쓴다
    "fill_kernel_pt": 2.2,       # 이 지름의 원판 열림을 견디는 잉크 = 채운 도형(굵은 배관보다 커야 함)
    "fill_min_area_pt2": 4.0,    # 채운 도형 최소 넓이
    "hv_min_len_pt": 6.0,        # 가로·세로 획 최소 길이(점선 조각보다 길어야 함)
    "hv_join_tol_pt": 1.6,       # 꺾임·분기: 선 끝과 상대 선 중심선 거리 여유(선 두께에 더함)
    "hv_collinear_tol_pt": 1.0,  # 같은 직선 판정(중심선 차)
    "hv_gap_join_pt": 1.0,       # 같은 직선 위 빈칸이 이 이하면 잇는다
    "stub_min_len_pt": 1.2,      # 배관 라벨 양옆 짧은 토막 최소 길이
    "stub_reach_pt": 8.0,        # 배관 라벨 양옆에서 짧은 토막을 찾는 띠 폭
    "stub_thick_max_pt": 2.5,    # 짧은 토막 두께 상한(굵은 배관 1.44pt보다 크게)
    "stub_touch_pt": 2.0,        # 짧은 토막 끝과 글자 상자 가장자리 거리 상한
    "frame_cover_ratio": 0.8,    # 페이지 폭(높이)의 이 비율 이상인 가로(세로) 선 = 도면 테두리
    "body_min_pt": 3.0,          # 몸체(흰 구멍) 짧은 변 하한
    "body_max_ratio": 0.25,      # 몸체 긴 변 상한 = 페이지 폭 × 비율(넘으면 배관이 둘러싼 빈 곳)
    "body_convexity_min": 0.85,  # 몸체 넓이 / 볼록 껍질 넓이 하한(배관이 둘러싼 오목한 빈 곳 제외)
    "body_pad_pt": 0.7,          # 몸체 윤곽을 넓히는 폭(선 두께 절반)
    "body_zone_pt": 1.4,         # 몸체 윤곽선 잉크로 보고 선 검출에서 빼는 폭
    "circle_min": 0.85,          # 원 판정: 4πA/P² 하한
    "poly_eps_ratio": 0.03,      # 다각형 근사 허용 오차 = 둘레 × 비율
    "rect_fill_min": 0.95,       # 넓이 / bbox 넓이가 이 이상이면 축 정렬 사각형
    "triangle_fit_min": 0.85,    # 넓이 / 감싸는 최소 삼각형 넓이가 이 이상이면 삼각형
    # 작은 채운 도형(화살촉)의 삼각형 하한. 화살촉은 배관 토막·번짐이 붙어 0.68~0.85로 재지고(SNP-M-301 300dpi 14개),
    # 원판은 0.60, 정사각형은 0.50이다. 삼각형으로 넘겨야 흐름 방향(pdf_vector_flow.arrow_axis, 꼭짓점 3개)을 읽는다
    "marker_triangle_fit_min": 0.66,
    "marker_tri_max_pt": 8.5,    # 위 하한을 쓰는 도형 긴 변 상한(PV_OVERRIDES marker_max와 같은 값)
    "marker_tri_min_pt": 4.5,    # 위 하한을 쓰는 도형 긴 변 하한. 체크밸브 안 작은 표식(3~4pt)은 삼각형으로 넘기면 흐름 화살촉으로 읽혀
                                 # 기호에서 빠진다(SNP 6장 기호 종류 84 → 80)
    "bow_axis_tol": 0.15,        # 맞댄 두 삼각형 중심이 한 축에서 이 비율(크기 대비) 안이면 나비 모양 밸브 몸통
    "fill_link_pt": 3.5,         # 선과 채운 도형(화살촉) 사이 빈칸이 이 이하면 짧은 잇는 선을 더한다
    "label_bridge_max_pt": 40.0,  # 글자를 못 읽은 선 라벨 빈칸 상한
    "label_glyph_max_pt": 12.0,  # 선 라벨 빈칸 안 글자 획 덩어리 크기 상한
    "label_glyph_min_count": 3,  # 선 라벨 빈칸 안 글자 획 덩어리 개수 하한
    "stem_max_pt": 12.0,         # 두 몸체 사이 이 길이 이하 선 = 기호 안 축(구동부 축 등), 몸체로 본다
    "stem_attach_pt": 2.5,       # 축 선 끝과 몸체 사이 거리 상한
    "end_link_min_pt": 1.5,      # 선과 채운 도형 사이가 이보다 가까우면 이미 닿은 것으로 본다
    "spring_angle_tol": 8.0,     # 평행 사선 묶음(스프링 표시) 각도 차 상한(도)
    "diag_min_len_pt": 3.0,      # 사선 최소 길이
    "diag_elong_min": 3.0,       # 사선: 긴 변 / 짧은 변 하한
    "curve_min_len_pt": 6.0,     # 굽은 획 최소 크기(최소 외접 사각형 긴 변)
    "curve_fill_max": 0.5,       # 굽은 획: 잉크 넓이 / 최소 외접 사각형 넓이 상한(넘으면 덩어리로 보고 버린다)
    "curve_eps_pt": 0.4,         # 굽은 획 윤곽을 꺾은선으로 줄일 때 허용 오차
    "dash_thick_max_pt": 1.5,    # 점선 조각 두께 상한(pdf_vector와 같은 값)
    "dash_long_max_pt": 8.0,     # 점선 조각 길이 상한
    "dash_link_pt": 3.0,         # 점선 조각 후보끼리 이 간격 안에 이웃이 있어야 점선(외톨이는 짧은 실선)
    "text_pad_pt": 0.7,          # 글자 상자 여유(글자 획 판정)
    "ocr_min_score": 0.5,        # OCR 신뢰도 하한
    "ocr_box_trim": 0.12,        # OCR 상자 위·아래를 높이의 이 비율씩 줄여 글자 크기에 맞춘다
    "max_merge_items": 400,      # 몸체 합치기(원·사각형·삼각형 쌍 비교) 후보 상한. 넘으면 합치기를 건너뛴다
    "max_spring_items": 400,     # 평행 사선 묶음(쌍 비교) 후보 상한. 넘으면 묶음 정규화를 건너뛴다
    "circle_ocr_zoom": 3.0,      # 원 안을 다시 읽을 때 확대 배율
    "circle_ocr_ok_score": 0.9,  # 원 안 두 줄이 모두 이 신뢰도 이상이면 다시 읽지 않는다
}
# pdf_vector PARAMS 중 길이(pt) 값. 래스터에서는 배율을 곱해 px로 쓴다. 나머지는 비율·각도·횟수.
PV_LENGTH_KEYS = ("twin_tol", "dash_thick_max", "dash_long_max", "dash_corner_max", "marker_max", "touch_tol",
                  "attach_tol", "end_tol", "inner_tol_min", "inner_tol_max", "deep_min", "decor_group_tol",
                  "stroke_symbol_min", "stroke_symbol_max", "dash_gap_max", "dash_attach_tol", "label_gap_max",
                  "tee_half", "axis_rect_tol", "table_edge_tol", "pipe_cap_max", "dash_stroke_step",
                  "dash_collinear_tol", "line_size_tol")
# 래스터에서 바꾸는 pdf_vector 값(pt 기준): OCR 상자 높이는 줄마다 몇 px씩 달라 글자 크기 차 허용을 넓히고, 몸체 윤곽은
# 선 두께만큼 떨어져 나오므로(맞댄 삼각형 꼭짓점 등) 몸체 맞닿음·표 칸·축 정렬 허용을 넓힌다. 화살촉은 번짐(안티에일리어싱)으로
# 벡터보다 1pt 안팎 커서(샘플 6.9~8.0pt) 표식 상한을 넓힌다. 선 끝은 몸체 윤곽선을 빼며 잘리고 뾰족한 꼭짓점(도면 연결
# 오각형 끝)에서는 구멍이 윤곽보다 안쪽이라 몸체 접속 허용을 3.5pt로 넓힌다(2.5·3.5·4.5 비교, evidence/w4-raster.md).
# 장식선 묶음 거리는 3.0 → 4.0: 선 기호(체크밸브 두 판과 사선·화살촉)의 조각이 잉크 정리로 1~1.5pt씩 떨어져 나와 한 기호로
# 묶이지 않았다(SNP 6장 300dpi 연결 103/194 → 114/194, 3.0·4.0·4.5·5.5·8.0 비교, 5.5부터 기호 오검출 증가. 2026-11-14).
PV_OVERRIDES = {"line_size_tol": 4.0, "touch_tol": 1.5, "marker_max": 8.5, "attach_tol": 3.5, "axis_rect_tol": 0.6,
                "table_edge_tol": 1.2, "decor_group_tol": 4.0}


def _cv():
    return importlib.import_module("cv2"), importlib.import_module("numpy")


def available():
    """(영상 처리 가능, OCR 가능)."""
    has = lambda m: importlib.util.find_spec(m) is not None  # noqa: E731
    return has("cv2") and has("numpy"), has("rapidocr_onnxruntime")


# ---------------------------------------------------------------- 읽기·OCR

class RasterInputError(ValueError):
    """입력 형식 오류(빈 파일·손상·해독 불가·크기 상한 초과). 추출 결과(blocker)가 아니라 실행 오류로 다룬다."""


def check_header(data, max_pixels=None):
    """해독 전에 PNG·JPEG 머리말에서 폭·높이를 읽는다(Pillow, 픽셀은 풀지 않음). 상한을 넘거나 읽을 수 없으면
    RasterInputError. → (폭, 높이)."""
    max_pixels = MAX_PIXELS if max_pixels is None else max_pixels
    if not data:
        raise RasterInputError("빈 파일(0바이트)")
    image = importlib.import_module("PIL.Image")
    io = importlib.import_module("io")
    try:
        with image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception as exc:  # 손상·형식 불명
        raise RasterInputError("영상 머리말을 읽을 수 없음(손상 또는 형식 불명): %s" % type(exc).__name__)
    if w <= 0 or h <= 0:
        raise RasterInputError("크기가 0인 영상(%dx%d)" % (w, h))
    if w * h > max_pixels:
        raise RasterInputError("입력이 너무 큼: %dx%d = %d 픽셀 > 상한 %d" % (w, h, w * h, max_pixels))
    return w, h


def load_image(path, max_bytes=None, max_pixels=None):
    """회색조 영상(numpy uint8 2차원). 경로에 한글이 있어도 읽도록 바이트로 읽어 해독한다.
    파일 크기·픽셀 수 상한을 해독 전에 확인하고, 넘거나 빈 파일·손상 파일이면 RasterInputError."""
    cv2, np = _cv()
    max_bytes = MAX_FILE_BYTES if max_bytes is None else max_bytes
    size = os.path.getsize(path)
    if size > max_bytes:
        raise RasterInputError("입력이 너무 큼: 파일 %d바이트 > 상한 %d" % (size, max_bytes))
    with open(path, "rb") as fh:
        data = fh.read()
    check_header(data, max_pixels)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or img.size == 0:
        raise RasterInputError("영상을 해독할 수 없음: %s" % os.path.basename(path))
    if img.size > (MAX_PIXELS if max_pixels is None else max_pixels):
        raise RasterInputError("입력이 너무 큼: %d 픽셀" % img.size)
    return img


_OCR = None
# rapidocr-onnxruntime 1.4.4는 긴 변이 2000px을 넘는 그림을 줄여 읽는다(config.yaml max_side_len). 300dpi A3 쪽(약 5000px)은
# 40%로 줄어 작은 글자를 놓치므로 이 크기 이하 타일로 나눠 읽는다(HZ-PLN-23 §3 5). 겹침은 줄 하나가 한 타일에 온전히 들도록 둔다.
OCR_TILE_MAX = 2000
OCR_TILE_OVERLAP = 400
OCR_EDGE_PX = 3.0  # 타일 안쪽 가장자리에서 이 거리 안에 닿은 줄은 잘렸을 수 있다


def _ocr_engine():
    global _OCR
    if _OCR is None:
        _OCR = importlib.import_module("rapidocr_onnxruntime").RapidOCR()
    return _OCR


def _ocr_raw(cv2, gray, offset, zoom):
    res, _ = _ocr_engine()(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
    out = []
    for box, text, score in res or []:
        xs = [float(q[0]) / zoom + offset[0] for q in box]
        ys = [float(q[1]) / zoom + offset[1] for q in box]
        out.append({"text": str(text).strip(), "x0": round(min(xs), 1), "x1": round(max(xs), 1),
                    "top": round(min(ys), 1), "bottom": round(max(ys), 1), "score": round(float(score), 4)})
    return [o for o in out if o["text"]]


def _starts(n, size, overlap):
    if n <= size:
        return [0]
    step = size - overlap
    out = list(range(0, n - size, step))
    return out + [n - size]


def ocr_tiles(W, H, size=OCR_TILE_MAX, overlap=OCR_TILE_OVERLAP):
    """OCR 타일 [(x0, y0, x1, y1)]. 그림이 size 이하이면 통째로 한 장."""
    return [(x, y, min(W, x + size), min(H, y + size)) for y in _starts(H, size, overlap) for x in _starts(W, size, overlap)]


def merge_tile_lines(tile_lines, edge=OCR_EDGE_PX):
    """타일별 OCR 줄 [(타일, 줄 목록)] → 겹친 줄을 하나로. 타일 안쪽 가장자리에 닿은 줄(잘렸을 수 있음)보다
    온전한 줄을, 같은 조건이면 신뢰도 높은 줄을 남긴다. 겹침 = 교집합 넓이 / 작은 상자 넓이 ≥ 0.5."""
    W = max(t[2] for t, _ in tile_lines)
    H = max(t[3] for t, _ in tile_lines)
    cand = []
    for (x0, y0, x1, y1), lines in tile_lines:
        for o in lines:
            cut = ((x0 > 0 and o["x0"] - x0 <= edge) or (x1 < W and x1 - o["x1"] <= edge)
                   or (y0 > 0 and o["top"] - y0 <= edge) or (y1 < H and y1 - o["bottom"] <= edge))
            cand.append((cut, o))
    cand.sort(key=lambda c: (c[0], -c[1]["score"], -(c[1]["x1"] - c[1]["x0"]), c[1]["top"], c[1]["x0"]))
    kept = []
    for _, o in cand:
        if not any(_overlaps(o, k) for k in kept):
            kept.append(o)
    return kept


# 글자를 크게(배율 높게) 읽으면 rapidocr가 낱말 사이 띄어쓰기를 잃는다(SNP-M-101 PNG: 1.7 px/pt에서 'TO SNP-M-102',
# 원래 2.75 px/pt에서 'TOSNP-M-102'. 2026-11-14 측정). 띄어쓰기는 도면 연결 표기·기기 이름의 종류 판정에 쓰이므로
# 이 배율로 한 번 읽어 기본으로 두고, 그림이 더 고우면 원래 해상도로 한 번 더 읽어 겹치지 않는 줄만 더한다.
# 이 배율은 W4가 재던 조건(A3 가로 그림을 통째로 넣으면 OCR이 긴 변 2000px로 줄임)과 같다. 1.65로 하면 SNP-M-501의
# kind 정확도가 0.85 → 0.75로 내려가 W4 하한(0.8) 아래였다(2026-11-14, check_adapter.py W4, 래스터 venv).
OCR_COARSE_PX_PER_PT = OCR_TILE_MAX / 1190.55


def _ocr_tiled(cv2, np, gray):
    H, W = gray.shape[:2]
    tiles = ocr_tiles(W, H)
    if len(tiles) == 1:
        return _ocr_raw(cv2, gray, (0, 0), 1.0)
    parts = []
    for x0, y0, x1, y1 in tiles:
        parts.append(((x0, y0, x1, y1), _ocr_raw(cv2, np.ascontiguousarray(gray[y0:y1, x0:x1]), (x0, y0), 1.0)))
    return merge_tile_lines(parts)


def _overlaps(o, k, ratio=0.5):
    iw = min(o["x1"], k["x1"]) - max(o["x0"], k["x0"])
    ih = min(o["bottom"], k["bottom"]) - max(o["top"], k["top"])
    if iw <= 0 or ih <= 0:
        return False
    small = min(max(1e-6, (o["x1"] - o["x0"]) * (o["bottom"] - o["top"])),
                max(1e-6, (k["x1"] - k["x0"]) * (k["bottom"] - k["top"])))
    return iw * ih / small >= ratio


def add_fine_lines(coarse, fine):
    """낮은 배율 줄(띄어쓰기가 살아 있음)에 원래 해상도에서만 읽힌 줄(겹치지 않는 것)을 더한다."""
    return list(coarse) + [o for o in fine if not any(_overlaps(o, k) for k in coarse)]


# 띄어쓰기 되살리기: rapidocr는 배율과 상관없이 낱말 사이 띄어쓰기를 자주 잃는다('SAFETY INJECTION PUMP' →
# 'SAFETYINJECTIONPUMP', SNP-M-301 300dpi, 배율 1.0~4.17 px/pt 가운데 1.4에서만 띄어 읽음. 2026-11-14 측정). 줄 상자 안
# 잉크의 세로 빈 열이 줄 높이의 SPACE_GAP_RATIO 이상이면 낱말 사이로 보고, 조각마다 글자 인식만 다시 해서 띄어 붙인다.
# 같은 측정에서 글자 사이 빈칸은 줄 높이의 0.19 이하, 낱말 사이는 0.21 이상이었다. 다시 읽은 조각을 이은 글자가 원래 줄
# 글자(띄어쓰기 뺀 것)와 같을 때만 바꾼다.
SPACE_GAP_RATIO = 0.21
SPACE_MIN_CHARS = 6
SPACE_MAX_PIECES = 16


def _word_cuts(ink_cols, h, ratio=SPACE_GAP_RATIO):
    """줄 상자 안 열별 잉크 여부 → 낱말 조각 [(시작 열, 끝 열)]. 양 끝 빈 열은 뺀다."""
    cols = [i for i, v in enumerate(ink_cols) if v]
    if not cols:
        return []
    pieces, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev - 1 >= ratio * h:
            pieces.append((start, prev + 1))
            start = c
        prev = c
    pieces.append((start, prev + 1))
    return pieces


def _squash(t):
    return "".join(t.split()).upper()


def restore_spaces(gray, lines):
    """OCR 줄 가운데 띄어쓰기가 빠진 듯한 줄을 낱말 조각으로 나눠 다시 읽는다. → 바꾼 줄 수."""
    cv2, np = _cv()
    eng = _ocr_engine()
    H, W = gray.shape[:2]
    changed = 0
    for o in lines:
        text = o["text"]
        if len(_squash(text)) < SPACE_MIN_CHARS:
            continue
        x0, x1 = max(0, int(o["x0"])), min(W, int(math.ceil(o["x1"])))
        y0, y1 = max(0, int(o["top"])), min(H, int(math.ceil(o["bottom"])))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        sub = gray[y0:y1, x0:x1]
        pieces = _word_cuts((sub < 128).any(axis=0).tolist(), y1 - y0)
        if len(pieces) <= len(text.split()) or len(pieces) > SPACE_MAX_PIECES:
            continue
        pad = max(2, (y1 - y0) // 6)
        words = []
        for a, b in pieces:
            crop = np.full((y1 - y0, b - a + 2 * pad), 255, dtype=np.uint8)
            crop[:, pad:pad + b - a] = sub[:, a:b]
            res, _ = eng(cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR), use_det=False, use_cls=False, use_rec=True)
            words.append(str(res[0][0]).strip() if res else "")
        if all(words) and _squash("".join(words)) == _squash(text):
            # 한 글자 조각은 앞 조각에 붙인다. 좁은 글자('1')나 끝 글자 앞 빈칸이 넓어 태그가 갈리는 일을 막는다
            # ('RC-L011' → 'RC-L01 1', 'CC-V101B' → 'CC-V101 B', 2026-11-14 SNP 300dpi)
            joined = []
            for w in words:
                if joined and len(w) == 1:
                    joined[-1] += w
                else:
                    joined.append(w)
            new = " ".join(joined)
            if new != text:
                o["text"] = new
                changed += 1
    return changed


def ocr_lines(gray, offset=(0, 0), zoom=1.0, px_per_pt=None):
    """OCR 줄 목록 [{text, x0, x1, top, bottom, score}] (위→아래, 왼→오 순). OCR이 없으면 None.
    offset·zoom: 잘라 키운 영상일 때 원래 좌표로 되돌리는 값. 큰 그림은 타일로 나눠 읽는다(OCR_TILE_MAX).
    px_per_pt를 주면 OCR_COARSE_PX_PER_PT로 줄여 한 번, 그보다 고우면 원래 해상도로 한 번 더 읽어 합친다."""
    if importlib.util.find_spec("rapidocr_onnxruntime") is None:
        return None
    cv2, np = _cv()
    f = min(1.0, OCR_COARSE_PX_PER_PT / px_per_pt) if px_per_pt else 1.0
    if f < 1.0:
        small = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        coarse = _ocr_tiled(cv2, np, small)
        for o in coarse:
            o.update(x0=round(o["x0"] / f, 1), x1=round(o["x1"] / f, 1), top=round(o["top"] / f, 1),
                     bottom=round(o["bottom"] / f, 1))
        out = add_fine_lines(coarse, _ocr_tiled(cv2, np, gray))
    else:
        out = _ocr_tiled(cv2, np, gray)
    restore_spaces(gray, out)
    for o in out:
        o.update(x0=round(o["x0"] / zoom + offset[0], 1), x1=round(o["x1"] / zoom + offset[0], 1),
                 top=round(o["top"] / zoom + offset[1], 1), bottom=round(o["bottom"] / zoom + offset[1], 1))
    out.sort(key=lambda o: (o["top"], o["x0"], o["text"]))
    return out


# ---------------------------------------------------------------- 기울기 보정(HZ-PLN-23 §3 2)

DESKEW_MIN_DEG = 0.05   # 이보다 작은 기울기는 그대로 둔다
DESKEW_MAX_DEG = 5.0    # 이보다 큰 기울기는 돌리지 않고 미확인 skew_too_large
DESKEW_WINDOW_DEG = 10.0  # 가로·세로에서 이 각 안의 선만 기울기 재기에 쓴다
DESKEW_WORK_PX = 2000   # 재기는 긴 변을 이 크기로 줄인 그림에서 한다(각은 배율에 따라 변하지 않음)


def skew_angle(gray):
    """긴 가로·세로 선의 길이 가중 중앙값 각(도, 그림 좌표에서 시계 방향 +). 선이 없으면 None."""
    cv2, np = _cv()
    H, W = gray.shape[:2]
    f = min(1.0, DESKEW_WORK_PX / float(max(H, W)))
    small = cv2.resize(gray, (max(1, int(W * f)), max(1, int(H * f))), interpolation=cv2.INTER_AREA) if f < 1 else gray
    _, ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    min_len = max(60, int(0.06 * min(small.shape[:2])))
    segs = cv2.HoughLinesP(ink, 1, np.pi / 3600, threshold=min_len, minLineLength=min_len, maxLineGap=3)
    if segs is None:
        return None
    angs = []
    for x1, y1, x2, y2 in segs.reshape(-1, 4):  # OpenCV 판에 따라 (N,1,4) 또는 (N,4)
        a = math.degrees(math.atan2(float(y2 - y1), float(x2 - x1)))
        a = (a + 90.0) % 180.0 - 90.0  # -90..90
        if abs(a) > 45:  # 세로선: 90°를 빼서 가로 기준 각으로
            a = a - 90.0 if a > 0 else a + 90.0
        if abs(a) <= DESKEW_WINDOW_DEG:
            angs.append((a, math.hypot(float(x2 - x1), float(y2 - y1))))
    if not angs:
        return None
    angs.sort()
    half, acc = sum(w for _, w in angs) / 2.0, 0.0
    for a, w in angs:
        acc += w
        if acc >= half:
            return a
    return angs[-1][0]


def deskew(gray):
    """(그림, 잰 각, 상태). 상태: corrected(돌림) / straight(DESKEW_MIN_DEG 미만) / too_large(DESKEW_MAX_DEG 초과,
    그대로) / unknown(선이 없어 못 잼, 그대로). 돌리면 크기는 같고 빈 곳은 흰색."""
    cv2, np = _cv()
    a = skew_angle(gray)
    if a is None:
        return gray, 0.0, "unknown"
    if abs(a) < DESKEW_MIN_DEG:
        return gray, a, "straight"
    if abs(a) > DESKEW_MAX_DEG:
        return gray, a, "too_large"
    H, W = gray.shape[:2]
    m = cv2.getRotationMatrix2D((W / 2.0, H / 2.0), a, 1.0)
    out = cv2.warpAffine(gray, m, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    return out, a, "corrected"


# ---------------------------------------------------------------- 보조

def _px(prm, scale):
    out = {k[:-3]: v * scale for k, v in prm.items() if k.endswith("_pt") and k != "px_per_pt"}  # 배율 자체는 길이가 아님
    out.update({k[:-4]: v * scale * scale for k, v in prm.items() if k.endswith("_pt2")})
    return out


def _odd(v):
    n = max(1, int(round(v)))
    return n if n % 2 else n + 1


def _components(cv2, np, mask, conn=8):
    """[(라벨 마스크 접근용 라벨 번호, x, y, w, h, 넓이)] — 위치 순(결정적)."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=conn)
    comps = [(i, int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3]), int(stats[i, 4]))
             for i in range(1, n)]
    comps.sort(key=lambda c: (c[2], c[1], c[5]))
    return labels, comps


def _contour(cv2, np, sub):
    cs, _ = cv2.findContours(sub.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(cs, key=cv2.contourArea) if cs else None


def _box_inside(b, t):
    return t[0] <= b[0] and t[1] <= b[1] and b[2] <= t[2] and b[3] <= t[3]


# ---------------------------------------------------------------- 원시 요소 검출

def _ink(cv2, np, gray):
    _, binv = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binv.astype(np.uint8)


def _glyph_mask(cv2, np, ink, lines, pad):
    """글자 상자 안에 통째로 들어가는 잉크 덩어리(글자 획)."""
    out = np.zeros_like(ink)
    if not lines:
        return out
    labels, comps = _components(cv2, np, ink)
    boxes = [(o["x0"] - pad, o["top"] - pad, o["x1"] + pad, o["bottom"] + pad) for o in lines]
    for i, x, y, w, h, _ in comps:
        b = (x, y, x + w - 1, y + h - 1)
        if any(_box_inside(b, t) for t in boxes):
            out[labels == i] = 1
    return out


def _fills(cv2, np, ink, px):
    """채운 도형 [(마스크 영역 조각, bbox)]과 채움 마스크."""
    k = _odd(px["fill_kernel"])
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    core = cv2.morphologyEx(ink, cv2.MORPH_OPEN, ker)
    full = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))) & ink  # 경계 1px만 되살린다
    labels, comps = _components(cv2, np, full)
    out, mask = [], np.zeros_like(ink)
    for i, x, y, w, h, area in comps:
        if area < px["fill_min_area"]:
            continue
        sub = (labels[y:y + h, x:x + w] == i)
        mask[y:y + h, x:x + w][sub] = 1
        out.append((sub, x, y))
    return out, mask


def _is_round(cv2, c, prm):
    """원 판정: 볼록 껍질의 4πA/P²가 하한 이상, 폭·높이가 비슷하고, 껍질을 다각형으로 줄여도 꼭짓점이 7개 이상
    (육각형·팔각형 같은 다각형과 구별). 껍질을 쓰는 것은 선이 닿은 자리의 작은 홈을 무시하기 위해서다."""
    if c is None or len(c) < 5:
        return False
    hull = cv2.convexHull(c)
    a, p = cv2.contourArea(hull), cv2.arcLength(hull, True)
    x, y, w, h = cv2.boundingRect(hull)
    if p <= 0 or 4 * math.pi * a / (p * p) < prm["circle_min"] or abs(w - h) > 0.1 * max(w, h):
        return False
    return len(cv2.approxPolyDP(hull, 0.02 * p, True)) >= 7


def _poly_of(cv2, np, sub, ox, oy, prm, px, allow_curve=True, arrow_ok=False):
    """영역 마스크 → (점 목록(닫힘, 첫 점 반복), 곡선 여부). 원·사각형·다각형.
    arrow_ok: 화살촉 크기의 채운 도형에 낮은 삼각형 하한(marker_triangle_fit_min)을 쓴다."""
    c = _contour(cv2, np, sub)
    if c is None or len(c) < 3:
        return None, False
    area = cv2.contourArea(c)
    per = cv2.arcLength(c, True)
    bx, by, w, h = cv2.boundingRect(c)
    if area >= prm["rect_fill_min"] * w * h:
        x0, y0 = ox + bx, oy + by
        pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
        return pts + [pts[0]], False
    tri_area, tri = cv2.minEnclosingTriangle(c.astype(np.float32))
    small = arrow_ok and px["marker_tri_min"] <= max(w, h) <= px["marker_tri_max"]
    fit_min = prm["marker_triangle_fit_min"] if small else prm["triangle_fit_min"]
    if tri_area > 0 and area / tri_area >= fit_min:
        # 삼각형(꼭짓점이 다른 도형에 조금 가려진 것 포함) → 감싸는 삼각형
        q3 = [(float(q[0]), float(q[1])) for q in tri.reshape(-1, 2)]
        if area / tri_area < prm["triangle_fit_min"]:
            # 낮은 하한으로 받은 화살촉: 감싸는 삼각형이 잉크보다 커 꼭짓점이 닿은 기호 안으로 들어간다. 무게중심 쪽으로
            # 넓이가 잉크 넓이와 같게 줄인다(방향은 그대로)
            gx, gy = sum(q[0] for q in q3) / 3, sum(q[1] for q in q3) / 3
            f = math.sqrt(area / tri_area)
            q3 = [(gx + (q[0] - gx) * f, gy + (q[1] - gy) * f) for q in q3]
        pts = [(round(q[0] + ox, 1), round(q[1] + oy, 1)) for q in q3]
        return pts + [pts[0]], False
    if allow_curve and _is_round(cv2, c, prm):
        ap = cv2.approxPolyDP(c, max(0.5, 0.005 * per), True)
        curved = True
    else:
        ap = cv2.approxPolyDP(c, max(1.0, prm["poly_eps_ratio"] * per), True)
        curved = False
    pts = [(float(p[0][0] + ox), float(p[0][1] + oy)) for p in ap]
    if len(pts) < 3:
        return None, False
    return pts + [pts[0]], curved


def _bodies(cv2, np, ink, glyph_boxes, prm, px, W, limits=None):
    """흰 구멍 → 몸체 [(점 목록, 곡선 여부, bbox)]과 몸체 구역 마스크(윤곽선 잉크 포함)."""
    white = (ink == 0).astype(np.uint8)
    labels, comps = _components(cv2, np, white, conn=4)
    H = ink.shape[0]
    cand = []
    for i, x, y, w, h, area in comps:
        if x == 0 or y == 0 or x + w >= W or y + h >= H:
            continue
        if min(w, h) < px["body_min"] or max(w, h) > prm["body_max_ratio"] * W:
            continue
        b = (x, y, x + w - 1, y + h - 1)
        if any(_box_inside(b, t) for t in glyph_boxes):
            continue
        cand.append({"lab": i, "box": [x, y, x + w, y + h]})
    pad = max(1, int(round(px["body_pad"])))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pad + 1, 2 * pad + 1))

    def region(items):
        x0 = min(c["box"][0] for c in items) - pad - 1
        y0 = min(c["box"][1] for c in items) - pad - 1
        x1 = max(c["box"][2] for c in items) + pad + 1
        y1 = max(c["box"][3] for c in items) + pad + 1
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(x1, labels.shape[1]), min(y1, labels.shape[0])  # 영상 경계 근처 몸체(잘라내기 범위 제한)
        sub = np.zeros((y1 - y0, x1 - x0), np.uint8)
        lab = labels[y0:y1, x0:x1]
        for c in items:
            sub[lab == c["lab"]] = 1
        sub = cv2.dilate(sub, ker)
        cfill = _contour(cv2, np, sub)
        filled = np.zeros_like(sub)
        cv2.drawContours(filled, [cfill], -1, 1, thickness=-1)
        return filled, x0, y0

    def circular(sub):
        return _is_round(cv2, _contour(cv2, np, sub), prm)

    # 가로·세로 선 하나로 갈라진 원(계기 원의 가운데 선): 이웃 구멍 둘을 합친 모양이 원이면 합친다
    groups = [[c] for c in cand]
    over = len(cand) > prm["max_merge_items"]
    if over and limits is not None:
        limits.append("body_merge_skipped:%d>%d" % (len(cand), prm["max_merge_items"]))
    merged = not over
    while merged:
        merged = False
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                A = [min(c["box"][0] for c in groups[a]), min(c["box"][1] for c in groups[a]),
                     max(c["box"][2] for c in groups[a]), max(c["box"][3] for c in groups[a])]
                B = [min(c["box"][0] for c in groups[b]), min(c["box"][1] for c in groups[b]),
                     max(c["box"][2] for c in groups[b]), max(c["box"][3] for c in groups[b])]
                gap = max(B[0] - A[2], A[0] - B[2], B[1] - A[3], A[1] - B[3])
                if gap > 2 * pad + 2:
                    continue
                size = max(A[2] - A[0], A[3] - A[1], B[2] - B[0], B[3] - B[1])
                tol = 0.1 * size + 2 * pad + 2
                stacked = abs(A[0] - B[0]) <= tol and abs(A[2] - B[2]) <= tol   # 가로선으로 위아래로 갈림
                beside = abs(A[1] - B[1]) <= tol and abs(A[3] - B[3]) <= tol    # 세로선으로 좌우로 갈림
                if not (stacked or beside):
                    continue  # 사선으로 갈린 원(응축기 등 기호 안 사선)은 합치지 않는다
                if circular(region(groups[a])[0]) or circular(region(groups[b])[0]):
                    continue
                if circular(region(groups[a] + groups[b])[0]):
                    groups[a] = groups[a] + groups[b]
                    del groups[b]
                    merged = True
                    break
            if merged:
                break

    kept = []
    for g in groups:
        sub, ox, oy = region(g)
        c = _contour(cv2, np, sub)
        hull = cv2.convexHull(c)
        ha = cv2.contourArea(hull)
        if ha <= 0 or cv2.contourArea(c) / ha < prm["body_convexity_min"]:
            continue
        pts, curved = _poly_of(cv2, np, sub, ox, oy, prm, px)
        if pts is not None:
            kept.append([g, pts, curved])

    # 글자 없는 축 정렬 사각형이 변 하나를 통째로 맞대고 있으면 한 몸체로 합친다(열교환기 관 다발 칸 등).
    # 표 칸(표제란)은 글자가 있어 합치지 않는다(pdf_vector가 표로 읽는다).
    def is_rect(k):
        q = k[1]
        return len(q) == 5 and not k[2] and q[0][1] == q[1][1] and q[1][0] == q[2][0] and q[2][1] == q[3][1]

    def has_text(b):
        return any(b[0] <= (t[0] + t[2]) / 2 <= b[2] and b[1] <= (t[1] + t[3]) / 2 <= b[3] for t in glyph_boxes)

    def kbox(k):
        xs, ys = [q[0] for q in k[1]], [q[1] for q in k[1]]
        return (min(xs), min(ys), max(xs), max(ys))
    done = len(kept) > prm["max_merge_items"]
    while not done:
        done = True
        for a in range(len(kept)):
            if not is_rect(kept[a]) or has_text(kbox(kept[a])):
                continue
            for b in range(a + 1, len(kept)):
                if not is_rect(kept[b]) or has_text(kbox(kept[b])):
                    continue
                A, B = kbox(kept[a]), kbox(kept[b])
                tol = 2 * pad + 3
                side = (abs(A[1] - B[1]) <= tol and abs(A[3] - B[3]) <= tol and
                        (abs(A[2] - B[0]) <= tol or abs(B[2] - A[0]) <= tol))
                stack = (abs(A[0] - B[0]) <= tol and abs(A[2] - B[2]) <= tol and
                         (abs(A[3] - B[1]) <= tol or abs(B[3] - A[1]) <= tol))
                if not (side or stack):
                    continue
                g = kept[a][0] + kept[b][0]
                sub, ox, oy = region(g)
                pts, curved = _poly_of(cv2, np, sub, ox, oy, prm, px, allow_curve=False)
                kept[a] = [g, pts, curved]
                del kept[b]
                done = False
                break
            if not done:
                break

    # 꼭짓점을 맞댄 삼각형 둘이 같은 축에 마주 보지 않으면(안전밸브 몸통의 직각 배치 등) 나비 모양 밸브가 아니므로
    # 한 몸체로 합친다(벡터 PDF에서는 한 경로로 그려지는 모양).
    def tri(k):
        return len(k[1]) == 4 and not k[2]

    def box(k):
        xs, ys = [q[0] for q in k[1]], [q[1] for q in k[1]]
        return (min(xs), min(ys), max(xs), max(ys))
    done = len(kept) > prm["max_merge_items"]
    while not done:
        done = True
        for a in range(len(kept)):
            for b in range(a + 1, len(kept)):
                if not (tri(kept[a]) and tri(kept[b])):
                    continue
                A, B = box(kept[a]), box(kept[b])
                gap = max(B[0] - A[2], A[0] - B[2], B[1] - A[3], A[1] - B[3])
                if gap > 2 * pad + 2:
                    continue
                ca, cb = ((A[0] + A[2]) / 2, (A[1] + A[3]) / 2), ((B[0] + B[2]) / 2, (B[1] + B[3]) / 2)
                size = max(A[2] - A[0], A[3] - A[1], B[2] - B[0], B[3] - B[1])
                if min(abs(ca[0] - cb[0]), abs(ca[1] - cb[1])) <= prm["bow_axis_tol"] * size:
                    continue  # 같은 축에서 마주 봄 = 나비 모양 밸브 몸통
                g = kept[a][0] + kept[b][0]
                sub, ox, oy = region(g)
                c = _contour(cv2, np, sub)
                ap = cv2.approxPolyDP(c, max(1.0, prm["poly_eps_ratio"] * cv2.arcLength(c, True)), True)
                pts = [(float(q[0][0] + ox), float(q[0][1] + oy)) for q in ap]
                kept[a] = [g, pts + [pts[0]], False]
                del kept[b]
                done = False
                break
            if not done:
                break

    out, zone = [], np.zeros_like(ink)
    zpad = max(1, int(round(px["body_zone"])))
    zker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * zpad + 1, 2 * zpad + 1))
    for g, pts, curved in kept:
        sub, ox, oy = region(g)
        out.append((pts, curved, box([g, pts, curved])))
        z = cv2.dilate(sub, zker)
        zh, zw = min(z.shape[0], zone.shape[0] - oy), min(z.shape[1], zone.shape[1] - ox)
        zone[oy:oy + zh, ox:ox + zw] |= z[:zh, :zw]
    out.sort(key=lambda t: (round(t[2][1], 1), round(t[2][0], 1)))
    return out, zone


def _hv_segments(cv2, np, ink, px, horizontal):
    """가로(세로) 획 → [{a, b, c(중심선), t(두께)}] 선분. a<b는 진행 축 좌표."""
    L = _odd(px["hv_min_len"])
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1) if horizontal else (1, L))
    m = cv2.morphologyEx(ink, cv2.MORPH_OPEN, ker)
    labels, comps = _components(cv2, np, m)
    segs = []
    for i, x, y, w, h, _ in comps:
        if horizontal:
            segs.append({"a": float(x), "b": float(x + w - 1), "c": y + (h - 1) / 2.0, "t": float(h)})
        else:
            segs.append({"a": float(y), "b": float(y + h - 1), "c": x + (w - 1) / 2.0, "t": float(w)})
    return segs, m


def _label_stubs(cv2, np, rest, taken, text_boxes, px, horizontal):
    """배관 라벨 양옆의 짧은 선 토막(선 최소 길이보다 짧음)을 찾는다. 라벨 흰 바탕이 짧은 배관 가운데를 가리면 양쪽 토막이
    모두 짧아 배관이 통째로 빠진다(SNP-M-301 SI-L001: 탱크 벽 → 라벨 → 화살촉, 2026-11-14). 찾는 곳은 글자 상자 진행 방향
    양옆 띠뿐이고(상자 안 글자 획은 보지 않는다), 토막 한 끝이 상자 가장자리에 닿아야 한다. → 선분 목록."""
    H, W = rest.shape[:2]
    L = _odd(max(3, px["stub_min_len"]))
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1) if horizontal else (1, L))
    region = np.zeros_like(rest)
    reach = px["stub_reach"]
    for t in text_boxes:
        x0, y0, x1, y1 = t
        if horizontal:
            for a, b in ((x0 - reach, x0), (x1, x1 + reach)):
                region[max(0, int(y0)):min(H, int(y1) + 1), max(0, int(a)):min(W, int(b) + 1)] = 1
        else:
            for a, b in ((y0 - reach, y0), (y1, y1 + reach)):
                region[max(0, int(a)):min(H, int(b) + 1), max(0, int(x0)):min(W, int(x1) + 1)] = 1
    m = cv2.morphologyEx(rest & (1 - taken) & region, cv2.MORPH_OPEN, ker)
    out = []
    _, comps = _components(cv2, np, m)
    for i, x, y, w, h, _ in comps:
        a, b, c, t = (x, x + w - 1, y + (h - 1) / 2.0, h) if horizontal else (y, y + h - 1, x + (w - 1) / 2.0, w)
        if t > px["stub_thick_max"] or b - a + 1 < max(px["stub_min_len"], 2 * t):
            continue
        touch = False
        for tb in text_boxes:
            lo, hi = (tb[0], tb[2]) if horizontal else (tb[1], tb[3])
            c0, c1 = (tb[1], tb[3]) if horizontal else (tb[0], tb[2])
            if c0 <= c <= c1 and (abs(b - lo) <= px["stub_touch"] or abs(a - hi) <= px["stub_touch"]):
                touch = True
                break
        if touch:
            out.append({"a": float(a), "b": float(b), "c": c, "t": float(t)})
    return out


def _join_collinear(segs, text_boxes, px, horizontal, text_like=None):
    """같은 직선 위 선분: 빈칸이 짧거나 글자 상자(선 라벨)로 덮이거나 글자 획처럼 보이는 잉크만 있으면 잇는다.
    → (선분, 쓰인 글자 상자 번호)."""
    segs = sorted(segs, key=lambda s: (round(s["c"]), s["a"]))
    used = set()
    out = []
    for s in segs:
        prev = out[-1] if out else None
        if prev and abs(prev["c"] - s["c"]) <= px["hv_collinear_tol"] + max(prev["t"], s["t"]) / 2 \
                and s["a"] >= prev["b"]:
            g0, g1 = prev["b"], s["a"]
            hit = None
            if g1 - g0 <= px["hv_gap_join"]:
                hit = -1
            else:
                for k, t in enumerate(text_boxes):
                    lo, hi = (t[0], t[2]) if horizontal else (t[1], t[3])
                    c0, c1 = (t[1], t[3]) if horizontal else (t[0], t[2])
                    m = (t[3] - t[1]) * 0.5 + 3  # 선 라벨 흰 바탕은 글자 상자보다 조금 크다
                    if lo - m <= g0 and g1 <= hi + m and c0 <= s["c"] <= c1:
                        hit = k
                        break
                if hit is None and text_like is not None and g1 - g0 <= px["label_bridge_max"] and \
                        text_like(g0, g1, s["c"], horizontal):
                    hit = -1
            if hit is not None:
                prev["b"] = max(prev["b"], s["b"])
                prev["t"] = max(prev["t"], s["t"])
                if hit >= 0:
                    used.add(hit)
                continue
        out.append(dict(s))
    return out, used


def _bridge_label_ends(hs, vs, text_boxes, px):
    """선 끝이 글자 상자(배관 라벨) 가장자리에서 끊기고 라벨 건너편에 꺾이는 상대 선이 있으면 그 중심선까지 늘인다.
    라벨 흰 바탕이 꺾임 바로 앞을 가리면 꺾임과 라벨 사이 토막이 선 최소 길이보다 짧아 빠지고, 남은 선은 꺾임에 닿지
    못한다(SNP-M-301 SI-L002, 300dpi 2026-11-14). 벡터 PDF에서는 선이 라벨 밑으로 이어져 있어 생기지 않는 일이다.
    → 쓰인 글자 상자 번호 집합."""
    tol = px["hv_join_tol"]
    used = set()
    for A, B, horizontal in ((hs, vs, True), (vs, hs, False)):
        for s in A:
            for end in ("a", "b"):
                p = s[end]
                for k, t in enumerate(text_boxes):
                    lo, hi = (t[0], t[2]) if horizontal else (t[1], t[3])
                    c0, c1 = (t[1], t[3]) if horizontal else (t[0], t[2])
                    m = (t[3] - t[1]) * 0.5 + 3
                    if not c0 <= s["c"] <= c1:
                        continue
                    if end == "a" and lo < p <= hi + m and p >= hi - m:
                        far, lim = lo, lo - m
                    elif end == "b" and lo - m <= p < hi and p <= lo + m:
                        far, lim = hi, hi + m
                    else:
                        continue
                    span = (min(lim, p), max(lim, p))
                    cand = [o for o in B if span[0] <= o["c"] <= span[1]
                            and o["a"] - tol - s["t"] <= s["c"] <= o["b"] + tol + s["t"]]
                    if not cand:
                        continue
                    o = min(cand, key=lambda o: abs(o["c"] - far))
                    s[end] = o["c"]
                    for oe in ("a", "b"):
                        if abs(o[oe] - s["c"]) <= tol + s["t"] + o["t"]:
                            o[oe] = s["c"]
                    used.add(k)
                    break
    return used


def _snap(hs, vs, px):
    """선 끝을 상대 선 중심선에 맞춘다(꺾임·분기). 가로 끝 x를 세로 중심선으로, 세로 끝 y를 가로 중심선으로."""
    tol = px["hv_join_tol"]
    for A, B in ((hs, vs), (vs, hs)):
        for s in A:
            for end in ("a", "b"):
                p = s[end]
                best = None
                for o in B:
                    if abs(o["c"] - p) <= tol + o["t"] / 2 + s["t"] / 2 and \
                            o["a"] - tol - s["t"] <= s["c"] <= o["b"] + tol + s["t"]:
                        d = abs(o["c"] - p)
                        if best is None or d < best[0]:
                            best = (d, o)
                if best is not None:
                    o = best[1]
                    s[end] = o["c"]
                    # 꺾임: 상대 선 끝이 이 선 중심선 근처면 그 끝도 맞춘다
                    for oe in ("a", "b"):
                        if abs(o[oe] - s["c"]) <= tol + s["t"]:
                            o[oe] = s["c"]


def _circle_ocr(cv2, np, gray, bodies, lines, ocr, prm):
    """원(계기 원) 안 글자가 두 줄 미만이거나 신뢰도가 낮으면 원 안을 잘라 키워 다시 읽는다(영문 대문자·숫자 줄만).
    다시 읽은 줄이 더 많거나 평균 신뢰도가 높으면 원 안 줄을 바꾼다.
    → (새 OCR 줄 목록, 바꾼 원 개수)."""
    lines = list(lines)
    changed = 0
    for pts, curved, b in bodies:
        if not curved:
            continue
        inside = [o for o in lines if b[0] <= (o["x0"] + o["x1"]) / 2 <= b[2] and
                  b[1] <= (o["top"] + o["bottom"]) / 2 <= b[3]]
        if len(inside) >= 2 and min(o["score"] for o in inside) >= prm["circle_ocr_ok_score"]:
            continue  # 기능 문자·번호 두 줄을 이미 확실히 읽음
        inset = 0.18 * (b[2] - b[0])  # 내접 정사각형 안쪽(원 윤곽선이 글자로 읽히지 않게)
        x0, y0 = max(0, int(b[0] + inset)), max(0, int(b[1] + inset))
        x1, y1 = min(gray.shape[1], int(b[2] - inset)), min(gray.shape[0], int(b[3] - inset))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        z = prm["circle_ocr_zoom"]
        pad = int(0.25 * (x1 - x0) * z)
        big = cv2.resize(gray[y0:y1, x0:x1], None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC)
        big = cv2.copyMakeBorder(big, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
        got = [o for o in ocr(big, (x0 - pad / z, y0 - pad / z), z) or [] if o["score"] >= prm["ocr_min_score"]
               and re.fullmatch(r"[A-Z0-9][A-Z0-9\-]*", o["text"])]
        mean = lambda ls: sum(o["score"] for o in ls) / len(ls) if ls else 0.0  # noqa: E731
        if got and (len(got) > len(inside) or (len(got) == len(inside) and mean(got) > mean(inside))):
            lines = [o for o in lines if o not in inside] + got
            changed += 1
    return lines, changed


def detect(gray, lines=None, params=None, ocr=None):
    """회색조 영상 + OCR 줄 → (폭, 높이, words, prims, 진단 dict). words·prims는 pdf_vector.analyze 형식(px).
    ocr: 원 안 다시 읽기용 함수 ocr_lines(영상, offset, zoom). 없으면 다시 읽지 않는다."""
    cv2, np = _cv()
    prm = dict(PARAMS)
    prm.update(params or {})
    H, W = gray.shape
    scale = prm.get("px_per_pt") or W / prm["nominal_page_width_pt"]
    px = _px(prm, scale)
    ink = _ink(cv2, np, gray)
    lines = [o for o in (lines or []) if o["score"] >= prm["ocr_min_score"]]
    tpad = px["text_pad"]
    text_boxes = [(o["x0"] - tpad, o["top"] - tpad, o["x1"] + tpad, o["bottom"] + tpad) for o in lines]
    glyph = _glyph_mask(cv2, np, ink, lines, tpad)
    ink_ng = ink & (1 - glyph)
    fills, fill_mask = _fills(cv2, np, ink_ng, px)
    limits = []
    bodies, zone = _bodies(cv2, np, ink_ng, text_boxes, prm, px, W, limits)
    rereads = 0
    if ocr is not None:
        lines, rereads = _circle_ocr(cv2, np, gray, bodies, lines, ocr, prm)
        lines.sort(key=lambda o: (o["top"], o["x0"], o["text"]))
    rest = ink_ng & (1 - zone)
    rest &= 1 - cv2.dilate(fill_mask, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    hs, hmask = _hv_segments(cv2, np, rest, px, True)
    vs, vmask = _hv_segments(cv2, np, rest, px, False)
    taken = hmask | vmask
    hs += _label_stubs(cv2, np, rest, taken, text_boxes, px, True)
    vs += _label_stubs(cv2, np, rest, taken, text_boxes, px, False)
    frame = []
    hs_keep = [s for s in hs if s["b"] - s["a"] < prm["frame_cover_ratio"] * W]
    vs_keep = [s for s in vs if s["b"] - s["a"] < prm["frame_cover_ratio"] * H]
    frame = len(hs) - len(hs_keep) + len(vs) - len(vs_keep)
    hvm = cv2.dilate(hmask | vmask, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    resid = rest & (1 - hvm)
    labels, comps = _components(cv2, np, resid)
    glyph_px = px["label_glyph_max"]
    bridged = []  # 읽지 못한 선 라벨 자리(그 안 잉크 덩어리는 글자로 보고 선 검출에서 뺀다)

    def text_like(g0, g1, c, horizontal):
        """선 빈칸에 글자 획 크기 잉크 덩어리가 여러 개 있고 몸체·채움·다른 선이 없으면 읽지 못한 선 라벨."""
        half = glyph_px
        x0, x1, y0, y1 = (g0 + 1, g1 - 1, c - half, c + half) if horizontal else (c - half, c + half, g0 + 1, g1 - 1)
        x0, y0, x1, y1 = (max(0, int(x0)), max(0, int(y0)), min(W, int(x1) + 1), min(H, int(y1) + 1))
        if x1 <= x0 or y1 <= y0:
            return False
        if zone[y0:y1, x0:x1].any() or fill_mask[y0:y1, x0:x1].any() or hmask[y0:y1, x0:x1].any() or \
                vmask[y0:y1, x0:x1].any():
            return False
        ids = set(int(v) for v in np.unique(labels[y0:y1, x0:x1]) if v)
        n = 0
        for i, x, y, w, h, _ in comps:
            if i in ids:
                if max(w, h) > glyph_px:
                    return False
                n += 1
        if n >= prm["label_glyph_min_count"]:
            bridged.append((x0, y0, x1, y1))
            return True
        return False

    hs, used_h = _join_collinear(hs_keep, text_boxes, px, True, text_like)
    vs, used_v = _join_collinear(vs_keep, text_boxes, px, False, text_like)
    used_h |= _bridge_label_ends(hs, vs, text_boxes, px)
    _snap(hs, vs, px)

    # 남은 잉크: 사선·점선 조각
    diag, dash_cand, curves, ignored = [], [], [], 0
    for i, x, y, w, h, area in comps:
        if max(w, h) < 2 or any(_box_inside((x, y, x + w - 1, y + h - 1), b) for b in bridged):
            continue
        sub = (labels[y:y + h, x:x + w] == i).astype(np.uint8)
        c = _contour(cv2, np, sub)
        if c is None or len(c) < 2:
            continue
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
        long_, short = max(rw, rh), min(rw, rh)
        box = [(float(p[0] + x), float(p[1] + y)) for p in cv2.boxPoints(((cx, cy), (rw, rh), ang))]
        if short <= px["dash_thick_max"] and long_ <= px["dash_long_max"] and long_ >= 2 * max(short, 1.0):
            dash_cand.append({"box": box, "bb": (x, y, x + w, y + h), "long": long_, "short": short,
                              "c": (cx + x, cy + y), "ang": ang if rw >= rh else ang + 90})
        elif long_ >= px["diag_min_len"] and long_ >= prm["diag_elong_min"] * max(short, 1.0):
            t = math.radians(ang if rw >= rh else ang + 90)
            dx, dy = math.cos(t) * long_ / 2, math.sin(t) * long_ / 2
            diag.append([(cx + x - dx, cy + y - dy), (cx + x + dx, cy + y + dy)])
        elif long_ >= px["curve_min_len"] and area <= prm["curve_fill_max"] * rw * rh:
            # 굽은 획(펌프 외곽 곡선 등): 윤곽을 줄인 꺾은선으로 넘긴다. 벡터 PDF의 곡선 경로에 해당하고, 기호 묶기가
            # 이 획으로 몸체·화살촉·배관 끝을 한 기호로 잇는다(SNP-M-301 SI-PP01, 2026-11-14)
            approx = cv2.approxPolyDP(c, max(1.5, px["curve_eps"]), True).reshape(-1, 2)
            curves.append([(float(p[0] + x), float(p[1] + y)) for p in approx] + [(float(approx[0][0] + x),
                                                                                  float(approx[0][1] + y))])
        else:
            ignored += 1
    dashes = []
    for d in dash_cand:
        if any(e is not d and max(e["bb"][0] - d["bb"][2], d["bb"][0] - e["bb"][2], e["bb"][1] - d["bb"][3],
                                  d["bb"][1] - e["bb"][3]) <= px["dash_link"] for e in dash_cand):
            dashes.append(d)
        else:  # 외톨이 짧은 조각 = 짧은 실선
            t = math.radians(d["ang"])
            dx, dy = math.cos(t) * d["long"] / 2, math.sin(t) * d["long"] / 2
            diag.append([(d["c"][0] - dx, d["c"][1] - dy), (d["c"][0] + dx, d["c"][1] + dy)])

    # 화살촉 등 채운 도형과 선 사이 짧은 빈칸(잉크 정리로 잘려 나간 짧은 연결부): 잇는 선을 더한다
    fill_boxes = [(ox, oy, ox + sub.shape[1] - 1, oy + sub.shape[0] - 1) for sub, ox, oy in fills]
    links = []
    for fb in fill_boxes:
        for s, horizontal in [(s, True) for s in hs] + [(s, False) for s in vs]:
            a, b = (s["a"], s["b"])
            # 선 중심선 위 가장 가까운 점과 채운 도형 bbox 사이 거리
            if horizontal:
                qx = min(max((fb[0] + fb[2]) / 2, a), b)
                q = (qx, s["c"])
            else:
                qy = min(max((fb[1] + fb[3]) / 2, a), b)
                q = (s["c"], qy)
            nx, ny = min(max(q[0], fb[0]), fb[2]), min(max(q[1], fb[1]), fb[3])
            d = math.hypot(nx - q[0], ny - q[1])
            if d <= px["fill_link"] + s["t"] / 2:
                touching = d <= px["end_link_min"]
                # 선 축 위에 놓인 화살촉 크기 채움이면 화살촉 건너편 끝까지 잇는다. 벡터 PDF는 배관이 화살촉 밑으로 꼭짓점까지
                # 이어져 꼭짓점이 닿은 기호(도면 연결 상자·밸브)에 붙는다. 화살촉 가운데에서 끝나면 기호에 닿지 않는다
                # (SNP-M-401 CC-L101, 2026-11-14)
                lo, hi = (fb[0], fb[2]) if horizontal else (fb[1], fb[3])
                mid = ((fb[1] + fb[3]) / 2) if horizontal else ((fb[0] + fb[2]) / 2)
                if max(fb[2] - fb[0], fb[3] - fb[1]) <= px["marker_tri_max"] and                         abs(mid - s["c"]) <= s["t"] / 2 + px["end_link_min"]:
                    far = hi if (lo + hi) / 2 > (q[0] if horizontal else q[1]) else lo
                    if touching:  # 이미 닿은 화살촉: 따로 잇는 선을 두지 않고 선 끝을 꼭짓점까지 늘인다
                        end = "b" if far > s["b"] else ("a" if far < s["a"] else None)
                        if end is not None:
                            s[end] = far
                        continue
                    nx, ny = (far, s["c"]) if horizontal else (s["c"], far)
                if not touching:
                    links.append([q, (nx, ny)])
    diag += links

    # 두 몸체를 잇는 아주 짧은 선 = 기호 안 축(구동부 축 등): 얇은 몸체로 바꿔 두 몸체를 한 기호로 묶는다
    body_boxes = [b[2] for b in bodies] + fill_boxes

    def near_bodies(p):
        return {k for k, bb in enumerate(body_boxes)
                if max(bb[0] - p[0], 0, p[0] - bb[2]) ** 2 + max(bb[1] - p[1], 0, p[1] - bb[3]) ** 2
                <= px["stem_attach"] ** 2}
    stems = []

    def is_stem(p0, p1):
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > px["stem_max"]:
            return False
        n0, n1 = near_bodies(p0), near_bodies(p1)
        return bool(n0) and bool(n1) and bool(n0 ^ n1) and not (n0 & n1)
    for lst, horizontal in ((hs, True), (vs, False)):
        keep = []
        for s in lst:
            p0, p1 = ((s["a"], s["c"]), (s["b"], s["c"])) if horizontal else ((s["c"], s["a"]), (s["c"], s["b"]))
            (stems if is_stem(p0, p1) else keep).append((p0, p1, s["t"]) if is_stem(p0, p1) else s)
        lst[:] = keep
    diag_keep = []
    for seg in diag:
        if is_stem(seg[0], seg[1]):
            stems.append((seg[0], seg[1], 2.0))
        else:
            diag_keep.append(seg)
    diag = diag_keep

    # 평행 사선 묶음(스프링 표시): 가까운 같은 방향 사선은 같은 방향·길이 벡터로 맞춘다(벡터 도면의 같은 도형 반복에 해당)
    def ang_of(seg):
        a = math.degrees(math.atan2(seg[1][1] - seg[0][1], seg[1][0] - seg[0][0])) % 180.0
        return a
    def is_diag(seg):
        a = ang_of(seg)
        return min(a % 90.0, 90.0 - a % 90.0) > prm["spring_angle_tol"]
    dg = [k for k, seg in enumerate(diag) if is_diag(seg)]
    if len(dg) > prm["max_spring_items"]:
        limits.append("spring_regularize_skipped:%d>%d" % (len(dg), prm["max_spring_items"]))
        dg = []
    groups = {}
    parent = {k: k for k in dg}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    for i_ in dg:
        for j_ in dg:
            if j_ <= i_:
                continue
            si, sj = diag[i_], diag[j_]
            da = abs(ang_of(si) - ang_of(sj))
            da = min(da, 180.0 - da)
            ci = ((si[0][0] + si[1][0]) / 2, (si[0][1] + si[1][1]) / 2)
            cj = ((sj[0][0] + sj[1][0]) / 2, (sj[0][1] + sj[1][1]) / 2)
            Li = math.hypot(si[1][0] - si[0][0], si[1][1] - si[0][1])
            if da <= prm["spring_angle_tol"] and math.hypot(ci[0] - cj[0], ci[1] - cj[1]) <= 2.0 * Li:
                parent[find(i_)] = find(j_)
    for k in dg:
        groups.setdefault(find(k), []).append(k)
    for g in groups.values():
        if len(g) < 2:
            continue
        vx = vy = 0.0
        for k in g:
            (x0, y0), (x1, y1) = diag[k]
            if x1 < x0:
                x0, y0, x1, y1 = x1, y1, x0, y0
            vx += x1 - x0
            vy += y1 - y0
        vx, vy = round(vx / len(g), 1), round(vy / len(g), 1)
        for k in g:
            c = ((diag[k][0][0] + diag[k][1][0]) / 2, (diag[k][0][1] + diag[k][1][1]) / 2)
            p0 = (round(c[0] - vx / 2, 2), round(c[1] - vy / 2, 2))
            diag[k] = [p0, (round(p0[0] + vx, 2), round(p0[1] + vy, 2))]

    prims = []

    def prim(pts, closed, curved=False, fill=False, white=False, stroke=True):
        prims.append({"fill": fill, "stroke": stroke, "fill_white": white, "stroke_white": False, "dash": None,
                      "subpaths": [([tuple(map(float, p)) for p in pts], closed, [tuple(map(float, p)) for p in pts],
                                    curved)]})

    for pts, curved, _ in bodies:
        prim(pts, True, curved)
    for sub, ox, oy in fills:
        pts, curved = _poly_of(cv2, np, sub.astype(np.uint8), ox, oy, prm, px, allow_curve=True, arrow_ok=True)
        if pts is not None:
            prim(pts, True, curved, fill=True, stroke=False)
    for s in sorted(hs, key=lambda s: (s["c"], s["a"])):
        prim([(s["a"], s["c"]), (s["b"], s["c"])], False)
    for s in sorted(vs, key=lambda s: (s["c"], s["a"])):
        prim([(s["c"], s["a"]), (s["c"], s["b"])], False)
    for seg in sorted(diag):
        prim(seg, False)
    for pts in sorted(curves):
        prim(pts, True, curved=True)
    for p0, p1, t in sorted(stems):  # 기호 안 축: 얇은 닫힌 몸체
        h = max(t, 2.0) / 2
        x0, y0, x1, y1 = min(p0[0], p1[0]) - h, min(p0[1], p1[1]) - h, max(p0[0], p1[0]) + h, max(p0[1], p1[1]) + h
        prim([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], True)
    for d in sorted(dashes, key=lambda d: (d["bb"][1], d["bb"][0])):
        prim(d["box"] + [d["box"][0]], True, fill=True, stroke=False)
    for k in sorted(used_h | used_v):  # 선 라벨 흰 바탕(PDF의 흰 채움 마스크에 해당)
        t = text_boxes[k]
        prim([(t[0], t[1]), (t[2], t[1]), (t[2], t[3]), (t[0], t[3]), (t[0], t[1])], True, fill=True, white=True,
             stroke=False)
    # OCR 상자는 글자 위아래에 여백이 있어 줄 사이 간격이 실제보다 좁거나 겹쳐 보인다. 높이의 일정 비율씩 줄여
    # 글자 크기에 가깝게 맞춘 뒤 pdf_vector의 줄·문단 규칙에 넘긴다.
    words = []
    for o in lines:
        trim = prm["ocr_box_trim"] * (o["bottom"] - o["top"])
        top, bottom = round(o["top"] + trim, 1), round(o["bottom"] - trim, 1)
        words.append({"text": o["text"], "x0": o["x0"], "x1": o["x1"], "top": top, "bottom": bottom,
                      "size": round(bottom - top, 1)})
    diag_info = {"scale_px_per_pt": round(scale, 6), "bodies": len(bodies), "fills": len(fills),
                 "h_lines": len(hs), "v_lines": len(vs), "diagonal_or_short": len(diag), "curves": len(curves), "stems": len(stems),
                 "fill_links": len(links), "dash_pieces": len(dashes), "frame_lines_dropped": frame,
                 "unread_line_labels": len(bridged), "ignored_ink_clusters": ignored, "ocr_lines": len(lines),
                 "ocr_circle_rereads": rereads, "limits_hit": limits}
    return W, H, words, prims, diag_info


# ---------------------------------------------------------------- 조립

def _pv_params(scale, extra=None):
    p = dict(pv.PARAMS)
    p.update(PV_OVERRIDES)
    p.update(extra or {})
    return {k: (round(v * scale, 6) if k in PV_LENGTH_KEYS else v) for k, v in p.items()}


_RENAME_KEYS = {"pdf_objects": "raster_objects"}


def _retag_id(v):
    """PDF 결과의 ID 접두어를 래스터 접두어로(기호·관계 'pdf-p0-' → 'img-', 원시 요소 'pdf-path-' → 'img-prim-')."""
    return v.replace("pdf-p0-", "img-").replace("pdf-path-", "img-prim-")


def _retag(obj):
    """pdf_vector 결과의 PDF 전용 표기를 래스터 표기로 바꾼다(좌표 값은 그대로 px). ID 접두어는 모든 문자열 값
    (ignored_objects·evidence 목록 포함)에 같은 규칙을 적용한다."""
    if isinstance(obj, list):
        return [_retag(v) for v in obj]
    if isinstance(obj, str):
        return _retag_id(obj)
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        k2 = _RENAME_KEYS.get(k, k)
        if k in ("point_basis", "line_type", "method", "classification_basis") and isinstance(v, str):
            v = v.replace("pdf_", "raster_")
        elif k == "coordinate_space" and v == pv.COORDINATE_SPACE:
            v = COORDINATE_SPACE
        elif k == "unit" and v == pv.UNIT:
            v = UNIT
        elif k == "reason" and isinstance(v, str):
            v = v.replace("PDF", "이미지")
        elif k in ("label", "label_text", "text", "value"):
            pass  # 보이는 글자는 바꾸지 않는다
        else:
            v = _retag(v)
        out[k2] = v
    return out


def build_extraction(W, H, words, prims, diag_info, ocr_state, file_label, sha, fmt, params=None):
    scale = diag_info["scale_px_per_pt"]
    pvp = _pv_params(scale, (params or {}).get("pv_overrides"))
    analysis = pv.analyze(W, H, words, prims, pvp)
    res = pv.build_extraction(analysis, W, H, 1, 0, file_label, sha)
    res = _retag(res)
    if ocr_state == "disabled":
        pv._issue(res["validation"]["unknowns"], "ocr_disabled",
                  "글자 인식을 끄고 실행함(--no-ocr): 글자·태그·표제란을 읽지 않음", field="label_text")
    elif ocr_state != "ok":
        pv._issue(res["validation"]["unknowns"], "ocr_unavailable",
                  "글자 인식(rapidocr-onnxruntime)이 없어 글자·태그·표제란을 읽지 않음(결정 D7)", field="label_text")
    for hit in diag_info.get("limits_hit") or []:
        pv._issue(res["validation"]["unknowns"], "processing_limit",
                  "처리량 상한으로 단계를 줄여 처리함(%s)" % hit)
    if diag_info["ignored_ink_clusters"]:
        pv._issue(res["validation"]["unknowns"], "unread_ink_clusters",
                  "선·기호·글자로 해석하지 못한 잉크 덩어리 %d개" % diag_info["ignored_ink_clusters"])
    blockers = res["validation"]["blockers"]
    for b in blockers:
        if b.get("check") == "no_vector_content":
            b["check"], b["reason"] = "no_image_content", "영상에서 선·기호·글자를 찾지 못함"
    res["validation"]["status"] = "blocked" if blockers else "passed"
    prm = dict(PARAMS)
    prm.update(params or {})
    stem = os.path.splitext(os.path.basename(file_label))[0]
    dn = res["drawing"]["drawing_number"]
    res["extraction_run_id"] = "extract-raster-%s-%s-%s" % (dn or stem, RULES_VERSION, sha[:12])
    res["run"] = {"script": SCRIPT_NAME, "script_version": SCRIPT_VERSION, "rules_version": RULES_VERSION,
                  "scope": "full", "settings": {"raster_params": prm, "params": pvp, "ocr": ocr_state,
                                                "detection": diag_info}}
    res["source"]["format"] = fmt
    res["coordinate_system"] = {"coordinate_space": COORDINATE_SPACE, "unit": UNIT,
                                "origin": "영상 왼쪽 위 픽셀, x 오른쪽·y 아래쪽 증가", "svg_alignment": None}
    from .. import drawio
    res["summary"] = drawio.summarize(res)
    return res


SCAN_NOTES = ("scan_input", "low_resolution", "scale_assumed")


def note_scale(res, scale):
    """스캔 결과의 해상도 미확인(HZ-PLN-23 §3 8)을 단다. 앞서 단 것은 바꾼다. scale: {dpi, dpi_source, level}."""
    from . import raster_scan
    unknowns = [u for u in res["validation"]["unknowns"] if u.get("check") not in SCAN_NOTES]
    source = {"file": "그림 파일에 적힌 값", "pdf_image": "PDF 안 그림의 크기", "given": "호출이 준 값",
              "assumed_a3": "그림 폭을 A3 가로로 가정"}.get(scale["dpi_source"], scale["dpi_source"])
    pv._issue(unknowns, "scan_input", "스캔 입력이라 벡터 PDF보다 읽기 결과가 떨어집니다(%d dpi, %s)"
              % (round(scale["dpi"]), source))
    if scale["dpi_source"] == "assumed_a3":
        pv._issue(unknowns, "scale_assumed", "그림에 해상도(dpi)가 없어 그림 폭을 A3 가로로 보고 문턱을 맞춤")
    guide = raster_scan.resolution_guidance(scale["dpi"])
    if guide:
        pv._issue(unknowns, "low_resolution", guide)
    res["validation"]["unknowns"] = unknowns
    res["run"]["settings"]["scale"] = dict(scale)
    from .. import drawio
    res["summary"] = drawio.summarize(res)
    return res


def extract(path, repo_root=None, params=None, use_ocr=True):
    """PNG·JPG 한 장 → extraction dict. OpenCV가 없으면 ImportError. OCR이 없으면 글자 없이 진행(미확인 기록).
    배율: params의 px_per_pt, 없으면 파일에 적힌 믿을 만한 dpi, 그것도 없으면 A3 가로 가정(HZ-PLN-23 §2.2).
    기울기는 재서 0.05°~5°이면 바로잡는다(§3 2)."""
    from . import raster_scan
    ext = os.path.splitext(path)[1].lower()
    if ext not in FORMATS:
        raise ValueError("래스터 형식이 아님(.png·.jpg·.jpeg): %s" % path)
    with open(path, "rb") as fh:
        data = fh.read()
    sha = hashlib.sha256(data).hexdigest()
    gray = load_image(path)
    prm = dict(params or {})
    if prm.get("px_per_pt"):
        dpi = float(prm["px_per_pt"]) * 72.0
        scale = {"dpi": round(dpi, 1), "dpi_source": "given", "level": raster_scan.resolution_level(dpi)}
    else:
        scale = raster_scan.image_scale(data)
        if scale["dpi_source"] == "file":
            prm["px_per_pt"] = scale["px_per_pt"]
    gray, angle, skew = deskew(gray)
    ppt = prm.get("px_per_pt") or gray.shape[1] / PARAMS["nominal_page_width_pt"]
    lines = ocr_lines(gray, px_per_pt=ppt) if use_ocr else None
    ocr_state = "ok" if lines is not None else ("disabled" if not use_ocr else "unavailable")
    W, H, words, prims, info = detect(gray, lines, prm, ocr=ocr_lines if lines is not None else None)
    label = paths.rel_or_abs(path, repo_root) if repo_root else path
    res = build_extraction(W, H, words, prims, info, ocr_state, label, sha, FORMATS[ext], prm)
    res["coordinate_system"]["deskew_deg"] = round(angle, 3) if skew == "corrected" else 0.0
    res["run"]["settings"]["deskew"] = {"measured_deg": round(angle, 3), "state": skew}
    if skew == "too_large":
        pv._issue(res["validation"]["unknowns"], "skew_too_large",
                  "기울기가 %.1f°라 바로잡지 않음(%.0f° 초과). 바로 놓고 다시 스캔해 주세요" % (angle, DESKEW_MAX_DEG))
    return note_scale(res, scale)
