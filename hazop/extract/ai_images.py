"""AI 검토에 싣는 그림: 노드 조각과 범례판(docs/specs/extraction.md 'AI 검토', 계획 aiplan 2026-11-17).

조각: 노드 상자 둘레에 PAD pt를 더해 SCALE배로 그린 PNG. 상자 테두리를 빨갛게 그어 어느 기호를 묻는지 보인다.
범례판: 종류(kind)마다 견본 조각(기본 하나, 많으면 모양이 다른 것 몇 개)에 kind 이름을 적은 칸을 모아 범주별로 한 장씩
만든다. 견본 자리(종류, 상자)는 부르는 쪽이 준다(APR1400은 저장소 정답지 12쪽의 기호, SNP는 SNP 도면들의 추출 결과).
답으로 받는 종류는 모양이 일정한 종류(answer_kinds)이고, 범례판에 견본이 없는 종류도 답할 수 있다.
이 모듈은 그림을 만들기만 하고 보내지 않는다.
앱과 측정이 함께 부르는 진입은 image_input_for다. 범례판은 프로젝트 도면에서 고른 견본(project_legend)이 있으면 그것,
없으면 직접 그린 표준 기호 그림으로 만든 저장소 판(symbol_legend, scripts/build_ai_legend.py)을 쓴다.
"""

import base64
import hashlib
import io
import json
import os

from hazop import paths, store_io
from hazop.extract import rules

SCALE = 2.0
PAD = 25.0
WIDE_PAD = 60.0        # 넓힌 조각: 밸브 구동부(조작기)와 옆 글자가 들어가는 둘레(pt)
MIN_CROP = 4.0         # 자를 영역의 가로·세로 하한(pt)
SAMPLE_PAD = 6.0
CELL = (200, 150)      # 범례판 칸 크기(px). 아래 18px는 이름 글자
BOARD_COLS = 5
BOARD_CELLS = 20       # 범례판 한 장의 칸 수 상한
SHAPE_RATIO = 1.4      # 견본 모양 무리: 가로가 세로의 이 배 이상이면 눕힌 모양, 세로가 가로의 이 배 이상이면 세운 모양
SIZE_GAP = 2.0         # 같은 모양 무리에서 넓이가 이 배 넘게 차이 나야 다른 크기의 견본으로 더 싣는다
OUTLINE = (230, 0, 0)


# 그림 입력 답에서 뺄 종류. solenoid_valve는 두 표본에서 0/16(개발용 0/8, 보류 0/8)으로 모두 틀렸다. 범례의 'S' 네모는
# 밸브 구동부 표시일 뿐이고 정답지는 'S 파일럿 + 공기 구동'을 air_operated_valve로 적는다. 기호 그림·manifest·레지스트리는 그대로
# 두어 화면의 정리된 보기(viewer_kinds)에는 계속 쓴다.
NOT_IMAGE_ANSWER = frozenset({"solenoid_valve"})


def viewer_kinds():
    """보기가 그림을 가진 종류(resources/library/drawing-symbols/manifest.json) 가운데 레지스트리에 있는 것.
    그림 없이 점으로 그리는 이음점(junction, tee)은 기호가 아니라 뺀다."""
    with open(paths.folder("drawing-symbols", "manifest.json"), encoding="utf-8") as fh:
        rows = json.load(fh)["symbols"]
    return sorted({r["kind"] for r in rows if not r.get("junction")} & set(rules.KIND_CATEGORY))


def answer_kinds():
    """그림 입력에서 답으로 받을 수 있는 종류: 보기 그림이 있고 모양이 일정한 것(manifest fit "keep"). 크기에 맞춰 늘려
    그리는 설비 외곽(fit "stretch": 탱크·용기·열교환기·냉동기·도면 밖 연결 표기 등)은 견본 하나로 모양을 대 볼 수 없어 뺀다."""
    with open(paths.folder("drawing-symbols", "manifest.json"), encoding="utf-8") as fh:
        keep = {r["kind"] for r in json.load(fh)["symbols"] if r.get("fit") == "keep"}
    return sorted((set(viewer_kinds()) & keep) - NOT_IMAGE_ANSWER)


def _png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def block(label, png):
    """analyze 요청의 images 칸 하나."""
    return {"label": label, "media_type": "image/png", "data": base64.b64encode(png).decode("ascii")}


class PageImages:
    """PDF 한 쪽의 그림. 처음 자를 때 한 번만 그린다."""

    def __init__(self, pdf_path, page=0, scale=SCALE):
        self.pdf_path, self.page, self.scale = pdf_path, page, scale
        self._img = None

    def image(self):
        if self._img is None:
            import pypdfium2
            doc = pypdfium2.PdfDocument(self.pdf_path)
            try:
                self._img = doc[self.page].render(scale=self.scale).to_pil().convert("RGB")
            finally:
                doc.close()
        return self._img

    def crop_box(self, bbox, pad=PAD):
        """bbox(pt) 둘레 자를 영역(pt, 쪽 안으로 맞춤). 상자가 쪽과 겹치지 않거나(쪽 밖으로 삐져나간 상자)
        맞춘 영역이 MIN_CROP pt보다 좁으면 None: 그 항목은 그림 없이 건너뛴다."""
        img, s = self.image(), self.scale
        w, h = img.width / s, img.height / s
        if bbox[2] < 0 or bbox[3] < 0 or bbox[0] > w or bbox[1] > h:
            return None
        box = [max(0.0, bbox[0] - pad), max(0.0, bbox[1] - pad), min(w, bbox[2] + pad), min(h, bbox[3] + pad)]
        if box[2] - box[0] < MIN_CROP or box[3] - box[1] < MIN_CROP:
            return None
        return box

    def crop(self, bbox, pad=PAD, outline=True):
        """bbox(pt) 둘레 조각(PIL), 자를 수 없으면 None. outline이면 상자 테두리를 긋는다."""
        from PIL import ImageDraw
        box = self.crop_box(bbox, pad)
        if box is None:
            return None
        img, s = self.image(), self.scale
        out = img.crop(tuple(int(round(v * s)) for v in box)).copy()
        if outline:
            ImageDraw.Draw(out).rectangle([(bbox[0] - box[0]) * s - 2, (bbox[1] - box[1]) * s - 2,
                                           (bbox[2] - box[0]) * s + 2, (bbox[3] - box[1]) * s + 2],
                                          outline=OUTLINE, width=2)
        return out

    def crop_png(self, bbox, pad=PAD):
        out = self.crop(bbox, pad=pad)
        return None if out is None else _png(out)


def _box(n):
    g = n.get("geometry") or {}
    if "x" not in g:
        return None
    return [g["x"], g["y"], g["x"] + (g.get("width") or 0), g["y"] + (g.get("height") or 0)]


def node_samples(ex):
    """추출 결과의 노드를 견본 자리 [(kind, bbox)]로(SNP처럼 스크립트 종류가 믿을 만한 묶음에 쓴다)."""
    return [(n.get("kind"), _box(n)) for n in sorted(ex.get("nodes") or [], key=lambda n: str(n.get("source_object_id")))
            if n.get("kind") and _box(n)]


def _shape(b):
    w, h = b[2] - b[0], b[3] - b[1]
    return "wide" if w >= h * SHAPE_RATIO else "tall" if h >= w * SHAPE_RATIO else "square"


def _middle(rows):
    return rows[(len(rows) - 1) // 2]


def _spread(rows, n):
    """넓이순 자리 rows에서 견본 n개까지. 첫째는 넓이가 가운데인 것(가장 큰 상자는 이웃 조각까지 묶인 자리이기 쉽고 가장
    작은 상자는 기호 일부이기 쉬워서 그 종류의 흔한 크기를 쓴다). 다음은 가로세로비 무리(두 자리 넘게 나온 것, 큰 무리부터)마다
    넓이가 가운데인 것. 그래도 모자라면 가장 큰 무리의 작은 쪽·큰 쪽 사분위 자리 가운데 고른 견본들과 넓이가 SIZE_GAP배 넘게
    다른 것."""
    out = [_middle(rows)]
    groups = {}
    for r in rows:
        groups.setdefault(_shape(r[4]), []).append(r)
    ranked = sorted(groups.items(), key=lambda g: (-len(g[1]), g[0]))
    for shape, g in ranked:
        if len(out) < n and len(g) >= 2 and shape not in {_shape(o[4]) for o in out}:
            out.append(_middle(g))
    big = ranked[0][1]
    for r in (big[len(big) // 4], big[(3 * len(big)) // 4]):
        if len(out) < n and all(max(r[0], o[0]) > SIZE_GAP * max(min(r[0], o[0]), 1e-6) for o in out):
            out.append(r)
    return out


def pick_samples(sources, kinds, per_kind=1):
    """sources [(PageImages, [(kind, bbox)])] -> {kind: [(PageImages, bbox)]}. 종류마다 모든 자리를 상자 넓이로 줄 세워
    모양이 다른 견본을 per_kind개까지 고른다(_spread). per_kind 1이면 넓이가 가운데인 것 하나."""
    seen = {}
    for pi, (page, spots) in enumerate(sources):
        for si, (k, b) in enumerate(spots):
            if k in kinds and b is not None:
                seen.setdefault(k, []).append(((b[2] - b[0]) * (b[3] - b[1]), pi, si, page, b))
    out = {}
    for k, rows in seen.items():
        rows.sort(key=lambda r: r[:3])
        out[k] = [(r[3], r[4]) for r in _spread(rows, max(1, per_kind))]
    return out


def board(cells):
    """cells [(이름, PIL 조각)] -> 범례판 PNG 바이트."""
    from PIL import Image, ImageDraw
    w, h = CELL
    rows = (len(cells) + BOARD_COLS - 1) // BOARD_COLS
    out = Image.new("RGB", (w * BOARD_COLS, h * rows), "white")
    d = ImageDraw.Draw(out)
    for i, (name, img) in enumerate(cells):
        x, y = (i % BOARD_COLS) * w, (i // BOARD_COLS) * h
        r = min((w - 10) / img.width, (h - 26) / img.height, 4.0)  # 작은 기호는 4배까지 키워 모양이 보이게
        fit = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.LANCZOS)
        out.paste(fit, (x + (w - fit.width) // 2, y + 4 + (h - 26 - fit.height) // 2))
        d.rectangle([x, y, x + w - 1, y + h - 1], outline=(170, 170, 170))
        d.text((x + 5, y + h - 18), name, fill=(0, 0, 160))
    return _png(out)


def legend_boards(sources, kinds=None, per_kind=1):
    """범례판 PNG 바이트 목록(범주 순, 한 장 BOARD_CELLS칸까지)과 견본이 실린 종류 목록. 종류마다 견본 per_kind개까지."""
    kinds = set(kinds or answer_kinds())
    return boards_of({k: [c for c in (page.crop(b, pad=SAMPLE_PAD, outline=False) for page, b in spots) if c is not None]
                      for k, spots in pick_samples(sources, kinds, per_kind).items()})


def boards_of(crops):
    """{kind: [PIL 조각]} -> (범례판 PNG 바이트 목록, 실린 종류 목록). 칸은 범주·종류 순이고 한 장 BOARD_CELLS칸까지."""
    order = sorted((k for k, c in crops.items() if c), key=lambda k: (rules.KIND_CATEGORY.get(k) or "", k))
    cells = [(k, c) for k in order for c in crops[k]]
    boards = [board(cells[i:i + BOARD_CELLS]) for i in range(0, len(cells), BOARD_CELLS)]
    return boards, order


class ImageInput:
    """AI 검토 한 쪽에 실을 그림: 그 쪽 조각(page)과 범례판(legend, PNG 바이트 목록), 답으로 받을 종류(kinds, 기본은
    모양이 일정한 종류 전부). wide면 구동부로 갈리는 밸브 종류(ai_review.WIDE_KINDS) 답을 넓힌 조각으로 한 번 더 묻는다.
    split이면 남은 호출로 기호를 여럿 품은 큰 미분류 노드를 나눈다(ai_split). recheck면 남은 호출로 틀리기 쉬운 규칙
    (ai_review.RECHECK_RULES)이 정한 종류를 다시 확인한다."""

    def __init__(self, page, legend=(), kinds=None, wide=False, split=False, recheck=False, legend_source=None):
        self.page = page
        self.legend = list(legend)
        self.legend_source = legend_source  # image_input_for가 고른 범례판 출처(project·symbols·none, 측정의 정답지 판은 keys). 직접 만들면 None
        self.kinds = sorted(kinds or answer_kinds())
        self.wide = wide
        self.split = split
        self.recheck = recheck


# ---------------------------------------------------------------- 범례판 출처와 진입 (docs/specs/extraction.md 'AI 검토')

PROJECT_PER_KIND = 3       # 프로젝트 판에 종류마다 실을 견본 수 상한
LEGEND_INDEX = "legend.json"
PROJECT_CACHE_VERSION = 1  # 프로젝트 판 캐시 열쇠에 넣는다. 판 만드는 법이 바뀌면 올린다


def symbol_legend():
    """저장소의 표준 기호 판(scripts/build_ai_legend.py가 만든 PNG). 표지나 PNG가 없으면 []."""
    try:
        with open(paths.folder("ai-legend", LEGEND_INDEX), encoding="utf-8") as fh:
            index = json.load(fh)
        boards = [store_io.read_bytes(paths.folder("ai-legend", f))[0] for f in index["boards"]]
        return boards if all(boards) else []
    except (OSError, ValueError, KeyError, TypeError):
        return []


def confirmed_samples(ex):
    """추출 결과(사람 수정 기록을 적용한 것)에서 종류를 믿을 수 있는 노드의 견본 자리 [(kind, bbox)].
    사람이 종류를 정한 노드(human_edit.ops에 set_kind, AI 후보 수락도 이 연산으로 들어간다)와 스크립트가 기호 사전 견본에 맞춘
    노드(classification_basis가 'symbol:'로 시작)만. 순서는 source_object_id 순."""
    out = []
    for n in sorted(ex.get("nodes") or [], key=lambda n: str(n.get("source_object_id"))):
        human = "set_kind" in ((n.get("human_edit") or {}).get("ops") or [])
        basis = str((n.get("evidence") or {}).get("classification_basis") or "")
        b = _box(n)
        if n.get("kind") and b and (human or basis.startswith("symbol:")):
            out.append((n["kind"], b))
    return out


def _stamp(pdf_path):
    st = os.stat(pdf_path)
    return [os.path.normcase(os.path.abspath(pdf_path)), st.st_size, st.st_mtime_ns]


def project_legend(drawings, cache_dir=None, per_kind=PROJECT_PER_KIND):
    """프로젝트 판: drawings [(pdf_path, page, 추출 결과)]의 confirmed_samples에서 종류마다 모양이 다른 견본을 per_kind개까지
    골라 만든 PNG 바이트 목록. 견본이 하나도 없으면 [].
    cache_dir를 주면 견본 자리·PDF 크기와 바뀐 시각·답 목록이 같을 때 그 폴더의 PNG를 다시 쓴다(쪽 그림을 다시 그리지 않는다).
    읽을 수 없는 PDF는 건너뛴다."""
    kinds = answer_kinds()
    sources, sig = [], []
    for pdf_path, page, ex in drawings:
        spots = [(k, b) for k, b in confirmed_samples(ex) if k in kinds]
        if not spots:
            continue
        try:
            stamp = _stamp(pdf_path)
        except OSError:
            continue
        sources.append((PageImages(pdf_path, page), spots))
        sig.append([stamp, page, spots])
    if not sources:
        return []
    key = hashlib.sha256(json.dumps([PROJECT_CACHE_VERSION, per_kind, kinds, sig], sort_keys=True).encode("utf-8")).hexdigest()[:16]
    index = os.path.join(cache_dir, key + ".json") if cache_dir else None
    if index and os.path.isfile(index):
        try:
            with open(index, encoding="utf-8") as fh:
                names = json.load(fh)["boards"]
            boards = [store_io.read_bytes(os.path.join(cache_dir, f))[0] for f in names]
            if all(boards):
                return boards
        except (OSError, ValueError, KeyError, TypeError):
            pass  # 깨진 캐시는 다시 만든다
    boards, order = legend_boards(sources, kinds, per_kind=per_kind)
    if index and boards:
        names = ["%s-%02d.png" % (key, i) for i in range(1, len(boards) + 1)]
        for f, png in zip(names, boards):
            store_io.write_bytes(os.path.join(cache_dir, f), png)
        store_io.write_json(index, {"boards": names, "kinds": order, "per_kind": per_kind})
    return boards


def image_input_for(pdf_path, page=0, drawings=(), cache_dir=None, wide=True, recheck=True, split=False):
    """AI 검토 한 쪽의 그림 입력. 앱(도면별 AI 검토)과 측정(scripts/check_read_quality.py)이 같은 길로 부른다.
    pdf_path, page: 검토할 도면의 원본 PDF와 쪽 번호(0부터).
    drawings: 프로젝트에 등록된 도면들 [(pdf_path, page, 사람 수정 기록을 적용한 추출 결과)]. 검토할 도면도 넣어도 된다.
    cache_dir: 프로젝트 판 캐시 폴더(프로젝트 작업 폴더 안). None이면 캐시 없이 만든다.
    범례판은 프로젝트 판(project_legend)이 있으면 그것, 없으면 표준 기호 판(symbol_legend), 그것도 없으면 범례판 없이.
    고른 출처는 돌려준 ImageInput의 legend_source('project'·'symbols'·'none')에 있다. 답 목록은 늘 answer_kinds()."""
    legend, source = project_legend(drawings, cache_dir), "project"
    if not legend:
        legend, source = symbol_legend(), "symbols"
    if not legend:
        source = "none"
    return ImageInput(PageImages(pdf_path, page), legend, wide=wide, split=split, recheck=recheck, legend_source=source)
