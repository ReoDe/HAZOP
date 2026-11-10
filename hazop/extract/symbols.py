"""P&ID 기호 사전과 모양 서명 매칭(기획서/PID-기호사전.md §3·§4).

사전은 `resources/library/symbols/<묶음 폴더>/<id>.json`(기호 하나에 파일 하나)이고, 묶음 목록은 그 폴더의 `bundles.json`이다.
추출기가 묶은 기호의 구성 요소(몸체·선·표식·점선 조각)에서 서명(구성 키, 크기, 24×24 격자)을 만들고,
같은 구성 키의 견본과 양방향 평균 챔퍼 거리(칸)로 견준다. 결과는 맞음·애매함·후보 없음 셋 중 하나다.
배포본에 numpy가 없으므로 순수 파이썬으로 계산한다. 같은 입력과 같은 사전이면 같은 결과를 낸다.

격자로 가를 수 없는 규칙은 견본의 shape으로 구분해 같은 사전에 둔다(§7 S7). 'structure'는 추출기가 판정한 구조 특징을,
'label_words'는 라벨의 장비 이름 낱말을 요구하고, 여럿이 맞으면 order가 가장 작은 견본이 이긴다(shape_rule, word_rule).
이 견본들은 격자 매칭(match)에 끼지 않는다.
"""

import collections
import hashlib
import json
import math
import os
import re

GRID = 24
LAST = GRID - 1
# 회전·뒤집기 8가지. 같은 거리면 이 순서의 앞을 고른다(§4.1). (r, c) → 바뀐 칸.
TRANSFORMS = (
    ("r0", lambda r, c: (r, c)),
    ("r90", lambda r, c: (LAST - c, r)),
    ("r180", lambda r, c: (LAST - r, LAST - c)),
    ("r270", lambda r, c: (c, LAST - r)),
    ("fx", lambda r, c: (r, LAST - c)),
    ("fy", lambda r, c: (LAST - r, c)),
    ("t", lambda r, c: (c, r)),
    ("at", lambda r, c: (LAST - c, LAST - r)),
)
ROTATION_SETS = {"dihedral8": tuple(n for n, _ in TRANSFORMS), "none": ("r0",)}
ROLES = ("symbol", "actuator", "annotation", "continuation", "drop")
RULE_SHAPES = ("structure", "label_words")  # 격자 대신 구조 특징·라벨 낱말로 맞히는 견본. order가 작은 것이 먼저다
DEFAULT_MARGIN = 0.1
CURVE_SAMPLES = 8
BUNDLES_FILE = "bundles.json"
IMAGE_DIR = "images"  # 묶음 폴더 아래 예시 그림 폴더
OLD_IMAGE_DIR = "그림"  # 2026-11-10 이름 이전 전에 만든 항목의 image 값은 '그림/<이름>.png'다. 항목 파일은 고치지 않고 읽을 때 푼다


class SymbolLibraryError(ValueError):
    """사전 파일이 없거나 형식이 틀림. 조용히 넘어가지 않고 멈춘다."""


Signature = collections.namedtuple("Signature", "comp_key size cells zero")
Match = collections.namedtuple("Match", "outcome entry distance rotation candidates attributes")
ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
WORD_RE = re.compile(r"^[A-Z]+$")
# 구조 규칙 견본(shape 'structure')이 요구할 수 있는 특징. 격자로는 못 가르는 구조(몸체 수와 배치, 선의 방향)를
# 추출기(pdf_vector._shape_features)가 기호마다 판정해 이 이름으로 넘긴다.
STRUCTURE_FEATURES = {
    "plate_valve:butterfly": "배관을 가로지르는 두 판 사이에 원판 점(버터플라이 밸브 몸통)",
    "plate_valve:ball": "배관을 가로지르는 두 판 사이에 공(볼 밸브 몸통)",
    "bowtie": "삼각형 몸체가 정확히 둘(꼭짓점을 맞댄 나비 모양 밸브 몸통)",
    "outside_circle": "나비 몸통 상자 밖에 가운데가 있는 원(전동 구동부)",
    "outside_body": "나비 몸통 상자 밖에 가운데가 있는 몸체(구동부)",
    "body_with_springs": "몸체가 있고 기울기와 길이가 같은 사선이 둘 이상(스프링)",
    "stroke_only": "몸체 없이 선만으로 된 기호",
    "markers": "표식(작은 검은 채움)이 있음",
    "parallel_plates": "곧은 선만으로 된 기호이고 가로선이나 세로선이 둘 이상(오리피스 판)",
    "single_circle": "몸체가 원 하나뿐",
    "single_tombstone": "몸체가 비석 모양 하나뿐",
    "chevrons": "몸체가 모두 오각 화살표 모양",
}


# ---------------------------------------------------------------- 곡선 펴기

def _bezier(p0, p1, p2, p3, n=CURVE_SAMPLES):
    out = []
    for i in range(1, n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def sample_subpaths(obj):
    """pdfplumber 경로 객체 → 하위 경로마다 곡선을 표본점으로 편 점 목록. pdf_vector._subpaths와 순서·개수가 같다."""
    path = obj.get("path")
    if not path:
        pts = [tuple(map(float, p)) for p in obj.get("pts") or []]
        return [pts] if pts else []
    out, cur = [], None
    for cmd in path:
        op = cmd[0]
        if op == "m":
            if cur:
                out.append(cur)
            cur = [tuple(map(float, cmd[1]))]
        elif op == "l" and cur is not None:
            cur.append(tuple(map(float, cmd[1])))
        elif op == "c" and cur is not None:
            c = [tuple(map(float, x)) for x in cmd[1:]]
            cur += _bezier(cur[-1], c[0], c[1], c[2])
        elif op == "h" and cur is not None:
            cur.append(cur[0])
    if cur:
        out.append(cur)
    return out


def page_fine_points(page):
    """pdfplumber 쪽 → {pdf_vector 경로 id: 편 점 목록}. id 규칙은 pdf_vector._classify_primitives와 같다."""
    fine = {}
    for i, obj in enumerate(list(page.lines) + list(page.rects) + list(page.curves)):
        for k, pts in enumerate(sample_subpaths(obj)):
            fine["pdf-path-%04d" % i + ("" if k == 0 else "-%d" % k)] = pts
    return fine


# ---------------------------------------------------------------- 서명

def sym_members(sym):
    """pdf_vector._Sym(또는 같은 속성을 가진 객체) → (몸체, 열린 선, 표식, 점선 조각) 목록."""
    return list(sym.bodies), list(sym.strokes), list(sym.markers), list(sym.dashes)


def composition(bodies, strokes, markers, dashes):
    curved = sum(1 for b in bodies if b.get("closed") and b.get("curved") and not b.get("solid"))
    solid = sum(1 for b in bodies if b.get("solid"))
    return {"closed_curved": curved, "closed_straight": len(bodies) - curved - solid, "solid": min(solid, 3),
            "strokes": min(len(strokes), 6), "markers": min(len(markers), 3), "dashes": min(len(dashes), 3)}


COMP_CAPS = {"closed_curved": 99, "closed_straight": 99, "solid": 3, "strokes": 6, "markers": 3, "dashes": 3}


def comp_key(comp):
    return "C%(closed_curved)d.P%(closed_straight)d.F%(solid)d.S%(strokes)d.M%(markers)d.D%(dashes)d" % comp


def _points(item, fine):
    pid = item["id"]
    pts = item.get("fine") or (fine.get(pid[:-1] if pid.endswith("s") else pid) if fine else None)
    pts = list(pts or item.get("pts") or [])
    if item.get("closed") and pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def _inside_poly(x, y, pts):
    inside = False
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def signature(bodies, strokes, markers, dashes, bbox, fine=None):
    """구성 요소와 기호 상자 → Signature. 채운 도형(검은 몸체·표식·점선 조각)은 실제 윤곽 안쪽 칸까지 켠다."""
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    comp = composition(bodies, strokes, markers, dashes)
    size = (round(min(w, h), 2), round(max(w, h), 2))
    if w <= 0 and h <= 0:
        return Signature(comp_key(comp), size, frozenset(), True)
    s = LAST / max(w, h)
    ox, oy = (LAST - w * s) / 2, (LAST - h * s) / 2
    cells = set()

    def cell(px, py):
        r, c = int(round((py - y0) * s + oy)), int(round((px - x0) * s + ox))
        return min(max(r, 0), LAST), min(max(c, 0), LAST)

    filled = [(m, True) for m in markers + dashes] + [(b, bool(b.get("solid"))) for b in bodies]
    for item, fill in filled + [(m, False) for m in strokes]:
        pts = _points(item, fine)
        if fill and len(pts) >= 3 and pts[0] != pts[-1]:
            pts.append(pts[0])  # 채우기 연산은 닫는 연산(h)이 없어도 하위 경로를 닫는다
        for a, b in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) * s * 2))
            for t in range(n + 1):
                cells.add(cell(a[0] + (b[0] - a[0]) * t / n, a[1] + (b[1] - a[1]) * t / n))
        if len(pts) == 1:
            cells.add(cell(*pts[0]))
        if fill and len(pts) >= 3:
            r0, c0 = cell(min(p[0] for p in pts), min(p[1] for p in pts))
            r1, c1 = cell(max(p[0] for p in pts), max(p[1] for p in pts))
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    px, py = x0 + (c - ox) / s, y0 + (r - oy) / s
                    if _inside_poly(px, py, pts):
                        cells.add((r, c))
    return Signature(comp_key(comp), size, frozenset(cells), False)


def sym_signature(sym, fine=None):
    return signature(*sym_members(sym), sym.bbox, fine)


def grid_text(cells):
    return ["".join("#" if (r, c) in cells else "." for c in range(GRID)) for r in range(GRID)]


def cells_of(grid):
    if len(grid) != GRID or any(len(row) != GRID or set(row) - {"#", "."} for row in grid):
        raise SymbolLibraryError("격자는 %d줄 × %d칸의 '#'/'.'여야 한다" % (GRID, GRID))
    return frozenset((r, c) for r, row in enumerate(grid) for c, ch in enumerate(row) if ch == "#")


def distance_table(cells):
    """칸마다 가장 가까운 켜진 칸까지 유클리드 거리(칸). 켜진 칸이 없으면 GRID."""
    on = list(cells)
    if not on:
        return [float(GRID)] * (GRID * GRID)
    return [min(math.hypot(r - a, c - b) for a, b in on) for r in range(GRID) for c in range(GRID)]


def chamfer(cells_a, dt_a, cells_b, dt_b):
    if not cells_a or not cells_b:
        return float(GRID)
    da = sum(dt_b[r * GRID + c] for r, c in cells_a) / len(cells_a)
    db = sum(dt_a[r * GRID + c] for r, c in cells_b) / len(cells_b)
    return (da + db) / 2


# ---------------------------------------------------------------- 사전

def _number(entry_id, name, value, above):
    """유한한 수이고 above보다 커야 한다. NaN·무한·문자열·참거짓은 형식 오류."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= above:
        raise SymbolLibraryError("%s: %s=%r는 %s보다 큰 유한한 수여야 한다" % (entry_id, name, value, above))
    return float(value)


class Template:
    __slots__ = ("entry_id", "shape", "comp_key", "size", "size_ratio", "max_distance", "variants",
                 "set_attributes", "order", "requires", "basis", "words")

    def __init__(self, entry_id, spec):
        self.entry_id = entry_id
        self.shape = spec.get("shape", "grid")
        self.set_attributes = spec.get("set_attributes") or {}
        if not isinstance(self.set_attributes, dict):
            raise SymbolLibraryError("%s: set_attributes는 객체여야 한다" % entry_id)
        if self.shape == "zero_size":
            self.comp_key = None
            self.variants = ()
            return
        if self.shape in RULE_SHAPES:
            self.order = spec["order"]
            if isinstance(self.order, bool) or not isinstance(self.order, int):
                raise SymbolLibraryError("%s: order=%r는 정수여야 한다" % (entry_id, self.order))
            if self.shape == "structure":
                self.requires, self.basis = spec["requires"], spec["basis"]
                if not isinstance(self.requires, list) or not self.requires \
                        or any(f not in STRUCTURE_FEATURES for f in self.requires):
                    raise SymbolLibraryError("%s: requires=%r는 %s 중에서 하나 이상"
                                             % (entry_id, self.requires, ", ".join(STRUCTURE_FEATURES)))
                if not isinstance(self.basis, str) or not self.basis:
                    raise SymbolLibraryError("%s: basis는 빈 문자열이 아닌 글자여야 한다" % entry_id)
            else:
                self.words = spec["words"]
                if not isinstance(self.words, list) or not self.words \
                        or any(not isinstance(w, str) or not WORD_RE.match(w) for w in self.words):
                    raise SymbolLibraryError("%s: words=%r는 영문 대문자 낱말 하나 이상" % (entry_id, self.words))
                self.words = tuple(self.words)
            return
        if self.shape != "grid":
            raise SymbolLibraryError("%s: 모르는 견본 모양 %r" % (entry_id, self.shape))
        given = spec["composition"]
        if not isinstance(given, dict) or set(given) - set(COMP_CAPS):
            raise SymbolLibraryError("%s: composition 키는 %s만" % (entry_id, ", ".join(COMP_CAPS)))
        for k, v in given.items():
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= COMP_CAPS[k]:
                raise SymbolLibraryError("%s: composition %s=%r는 0~%d 정수" % (entry_id, k, v, COMP_CAPS[k]))
        comp = dict({k: 0 for k in COMP_CAPS}, **given)
        self.comp_key = comp_key(comp)
        short, long_ = spec["size_pt"]
        if not 0 < long_ or short > long_:
            raise SymbolLibraryError("%s: size_pt는 [짧은 변, 긴 변]이고 긴 변 > 0" % entry_id)
        self.size = _number(entry_id, "size_pt", long_, 0.0)
        _number(entry_id, "size_pt", short, -1e-9)
        self.size_ratio = _number(entry_id, "size_ratio", spec.get("size_ratio", 1.25), 1.0)
        self.max_distance = _number(entry_id, "max_distance", spec.get("max_distance", 0.8), 0.0)
        rot = spec.get("rotations", "dihedral8")
        if rot not in ROTATION_SETS:
            raise SymbolLibraryError("%s: rotations는 %s 중 하나" % (entry_id, "/".join(ROTATION_SETS)))
        base = cells_of(spec["grid"])
        names = ROTATION_SETS[rot]
        self.variants = tuple((name, frozenset(f(r, c) for r, c in base), None)
                              for name, f in TRANSFORMS if name in names)
        self.variants = tuple((n, cs, distance_table(cs)) for n, cs, _ in self.variants)


class Entry:
    __slots__ = ("id", "bundle", "revision", "name_en", "name_ko", "category", "role", "kind", "kind_from",
                 "attributes", "enabled", "text_inside", "text_forbid", "templates", "raw")

    def __init__(self, bundle, data, prefix=None):
        prefix = prefix or bundle.lower()
        if not isinstance(data, dict) or not isinstance(data.get("match"), list):
            raise SymbolLibraryError("%s: 항목은 객체이고 match는 목록이어야 한다" % bundle)
        try:
            self.id = data["id"]
            self.bundle = bundle
            self.revision = int(data["revision"])
            self.name_en, self.name_ko = data["name"]["en"], data["name"]["ko"]
            self.category = data["category"]
            self.role = data["role"]
            self.kind = data.get("kind")
            self.kind_from = data.get("kind_from")
            self.attributes = dict(data.get("attributes") or {})
            self.enabled = data.get("enabled", True)
            if not isinstance(self.enabled, bool) or not isinstance(data["revision"], int) \
                    or isinstance(data["revision"], bool):
                raise TypeError("enabled는 true/false, revision은 정수")
            if not isinstance(data.get("attributes") or {}, dict):
                raise TypeError("attributes는 객체")
            text = data.get("text") or {}
            if not isinstance(text, dict) or set(text) - {"inside", "forbid_inside"}:
                raise TypeError("text 키는 inside, forbid_inside만")
            self.text_inside = re.compile(text["inside"]) if text.get("inside") else None
            self.text_forbid = re.compile(text["forbid_inside"]) if text.get("forbid_inside") else None
            if not all(isinstance(t, dict) for t in data["match"]):
                raise TypeError("match의 견본은 객체")
            self.templates = tuple(Template(self.id, t) for t in data["match"])
        except SymbolLibraryError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError, re.error) as e:
            raise SymbolLibraryError("%s/%s: 항목 형식 오류(%s: %s)" % (bundle, data.get("id"), type(e).__name__, e))
        if not isinstance(self.id, str) or not ID_RE.match(self.id):
            raise SymbolLibraryError("%r: id는 '<묶음 접두>.<영문 소문자·숫자·_>' 꼴이어야 한다" % (self.id,))
        if not self.id.startswith(prefix + "."):
            raise SymbolLibraryError("%s: id는 '%s.'로 시작해야 한다" % (self.id, prefix))
        if self.role not in ROLES:
            raise SymbolLibraryError("%s: role은 %s 중 하나" % (self.id, "/".join(ROLES)))
        if self.kind_from not in (None, "isa_letters"):
            raise SymbolLibraryError("%s: kind_from은 isa_letters만" % self.id)
        if not self.templates:
            raise SymbolLibraryError("%s: match 견본이 없음" % self.id)
        self.raw = data

    def text_ok(self, inside_text):
        joined = "\n".join(t for t in inside_text if t)
        if self.text_forbid and self.text_forbid.search(joined):
            return False
        return self.text_inside is None or any(self.text_inside.search(t) for t in inside_text if t)


def bundle_dir(root, name, prefix):
    """묶음 폴더. 폴더 이름은 접두(common)이거나 묶음 이름(APR1400)이다. 묶음 이름이 한글('공통')이어도 폴더는 영어 접두로 두므로
    접두 폴더를 먼저 본다. 둘 다 없으면 묶음 이름 자리를 돌려준다(새 묶음을 만들 자리)."""
    for d in (prefix, name):
        if os.path.isdir(os.path.join(root, d)):
            return os.path.join(root, d)
    return os.path.join(root, name)


def image_path(folder, image):
    """항목의 image 값(묶음 폴더 기준 상대 경로)이 가리키는 파일."""
    parts = [p for p in image.replace("\\", "/").split("/") if p not in ("", ".")]
    if parts and parts[0] == OLD_IMAGE_DIR:
        parts[0] = IMAGE_DIR
    return os.path.join(folder, *parts)


class Library:
    """묶음들의 항목. match()가 기호 하나를 판정한다."""

    def __init__(self, entries, versions, margin=DEFAULT_MARGIN):
        self.entries = {e.id: e for e in entries}
        self.versions = dict(versions)
        self.margin = margin
        self._by_key = collections.defaultdict(list)
        self._zero = []
        rules = {shape: [] for shape in RULE_SHAPES}
        for e in sorted(entries, key=lambda e: e.id):
            if not e.enabled:
                continue
            for t in e.templates:
                if t.shape in rules:
                    rules[t.shape].append((t.order, e, t))
                else:
                    (self._zero if t.shape == "zero_size" else self._by_key[t.comp_key]).append((e, t))
        for shape, found in rules.items():
            found.sort(key=lambda x: x[0])
            for (o1, e1, _), (o2, e2, _) in zip(found, found[1:]):
                if o1 == o2:
                    raise SymbolLibraryError("%s 견본의 order %d가 겹침: %s, %s" % (shape, o1, e1.id, e2.id))
        self._structure, self._label_words = rules["structure"], rules["label_words"]
        # 구조 규칙으로 정한 노드에는 symbol_id가 없고 근거 글자(basis)만 남는다. 그 글자로 항목을 되짚으려면 겹치면 안 된다
        seen = {}
        for _, e, t in self._structure:
            if t.basis in seen:
                raise SymbolLibraryError("structure 견본의 basis %r가 겹침: %s, %s" % (t.basis, seen[t.basis], e.id))
            seen[t.basis] = e.id

    def missing_rule_shapes(self):
        """RULE_SHAPES 가운데 켜진 견본이 하나도 없는 종류. 추출기는 이 견본들로 밸브·계기·설비를 정하므로,
        하나라도 비면 그 분류가 오류 없이 통째로 빠진다(형상 규칙을 사전으로 옮기기 전 판의 사전이 그렇다)."""
        return [shape for shape, found in (("structure", self._structure), ("label_words", self._label_words))
                if not found]

    def shape_rule(self, features):
        """추출기가 본 구조 특징(STRUCTURE_FEATURES의 이름들) → (항목, 근거). 요구 특징이 모두 있는 견본 가운데
        order가 가장 작은 것. 없으면 (None, None)."""
        for _, e, t in self._structure:
            if all(f in features for f in t.requires):
                return e, t.basis
        return None, None

    def word_rule(self, tokens):
        """라벨의 영문 낱말들 → (항목, 맞은 낱말들). 낱말이 모두 있는 견본 가운데 order가 가장 작은 것."""
        for _, e, t in self._label_words:
            if all(w in tokens for w in t.words):
                return e, t.words
        return None, None

    @classmethod
    def load(cls, root=None):
        if root is None:
            from hazop import paths
            root = paths.folder("symbols")
        manifest = os.path.join(root, BUNDLES_FILE)
        if not os.path.isfile(manifest):
            raise SymbolLibraryError("기호 사전 묶음 목록이 없음: %s" % manifest)
        try:
            with open(manifest, encoding="utf-8") as f:
                meta = json.load(f)
            if any(not isinstance(b.get("active", True), bool) for b in meta["bundles"]):
                raise TypeError("active는 true/false")
            bundles = [(b["name"], b.get("prefix") or b["name"].lower()) for b in meta["bundles"] if b.get("active", True)]
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise SymbolLibraryError("묶음 목록 형식 오류: %s (%s)" % (manifest, e))
        with open(manifest, "rb") as f:
            manifest_raw = f.read()
        entries, versions = [], {}
        for name, prefix in bundles:
            folder = bundle_dir(root, name, prefix)
            if not os.path.isdir(folder):
                raise SymbolLibraryError("묶음 폴더가 없음: %s" % folder)
            h = hashlib.sha256(manifest_raw + b"\0")
            for fn in sorted(f for f in os.listdir(folder) if f.endswith(".json")):
                with open(os.path.join(folder, fn), "rb") as f:
                    raw = f.read()
                h.update(fn.encode("utf-8") + b"\0" + raw + b"\0")
                try:
                    data = json.loads(raw.decode("utf-8"))
                except ValueError as e:
                    raise SymbolLibraryError("%s/%s: JSON 오류(%s)" % (name, fn, e))
                e = Entry(name, data, prefix)
                if fn != e.id.split(".", 1)[1] + ".json":
                    raise SymbolLibraryError("%s/%s: 파일 이름은 id 뒤쪽과 같아야 한다(%s)" % (name, fn, e.id))
                entries.append(e)
            versions[name] = h.hexdigest()[:12]
        ids = collections.Counter(e.id for e in entries)
        dup = sorted(i for i, n in ids.items() if n > 1)
        if dup:
            raise SymbolLibraryError("id 중복: %s" % ", ".join(dup))
        return cls(entries, versions, _number(BUNDLES_FILE, "margin", meta.get("margin", DEFAULT_MARGIN), -1e-9))

    def match(self, sig, inside_text=()):
        """Signature와 기호 상자 안 글자 → Match(outcome, entry, distance, rotation, candidates).
        outcome: 'matched'(항목 하나), 'ambiguous'(1·2등 차가 margin 미만, 정하지 않음), 'none'(후보 없음)."""
        if sig.zero:
            hits = {}
            for e, t in self._zero:
                if e.text_ok(inside_text):
                    hits.setdefault(e.id, t)
            cands = tuple((eid, 0.0) for eid in sorted(hits))
            if not hits:
                return Match("none", None, None, None, (), None)
            if len(hits) > 1:
                return Match("ambiguous", None, 0.0, None, cands, None)
            eid, t = next(iter(hits.items()))
            return Match("matched", self.entries[eid], 0.0, "symmetric", cands, self._attrs(eid, t))
        dt = None
        best = {}
        for e, t in self._by_key.get(sig.comp_key, ()):
            if not (1 / t.size_ratio <= sig.size[1] / t.size <= t.size_ratio):
                continue
            if dt is None:
                dt = distance_table(sig.cells)
            for name, cells, tdt in t.variants:
                d = chamfer(sig.cells, dt, cells, tdt)
                if d > t.max_distance:
                    continue
                cur = best.get(e.id)
                if cur is None or d < cur[0] - 1e-9:
                    best[e.id] = (d, [name], t)
                elif abs(d - cur[0]) <= 1e-9 and cur[2] is t and name not in cur[1]:
                    cur[1].append(name)  # 같은 견본 안에서 같은 거리 = 그 기호가 그 변환에 대칭
        ranked = sorted(((round(d, 6), eid, rots, t) for eid, (d, rots, t) in best.items()
                         if self.entries[eid].text_ok(inside_text)), key=lambda x: (x[0], x[1]))
        cands = tuple((eid, d) for d, eid, _, _ in ranked)
        if not ranked:
            return Match("none", None, None, None, cands, None)
        d1, e1, rots, t1 = ranked[0]
        if len(ranked) > 1 and round(ranked[1][0] - d1, 6) < round(self.margin, 6):
            return Match("ambiguous", None, d1, None, cands, None)
        rotation = rots[0] if len(rots) == 1 else "symmetric"
        return Match("matched", self.entries[e1], d1, rotation, cands, self._attrs(e1, t1))

    def _attrs(self, eid, template):
        """항목 속성 위에 맞은 견본의 set_attributes를 덮은 것(검정 밸브의 normal_position=NC 등)."""
        return dict(self.entries[eid].attributes, **template.set_attributes)
