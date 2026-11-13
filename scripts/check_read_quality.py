"""도면 읽기 품질 검사: 기호 종류·태그/번호·연결·속성 네 항목의 정확도(규격 docs/specs/extraction.md '읽기 품질 지표').

  python scripts/check_read_quality.py                       # 정답지 쪽을 모두 추출해 재고 기준값과 견줌(종료 코드 0 = 후퇴 없음)
  python scripts/check_read_quality.py --update [--force]    # 기준값을 지금 값으로 바꿈(규칙 12)
  python scripts/check_read_quality.py --pages 12,62         # 몇 쪽만(기준값 비교 없이 보기만)
  python scripts/check_read_quality.py --ai-candidates <폴더> # '스크립트 + AI 후보' 값도 냄(쪽마다 <정답지 이름>.json)
  python scripts/check_read_quality.py tiles <쪽.pdf> <출력 폴더>   # 정답지 쓰기용 격자 타일(추출 결과를 쓰지 않음)
  python scripts/check_read_quality.py sample <출력 폴더> [--per-page 20] [--seed 20261113]
      사용자 확인용 무작위 표본: 쪽마다 정답 단위 N건과 그림 조각, 확인 목록(md)
  python scripts/check_read_quality.py compare <B 폴더> <출력 폴더> [--crops]
      같은 쪽을 따로 쓴 정답지 B와 저장소 정답지를 견줘 항목별 일치율과 어긋난 항목(그림 조각)을 씀

정답지: tests/fixtures/read-quality/apr1400/*.json(쪽 그림만 보고 씀), SNP 가상 도면은 같은 도면의 drawio가 정답이다
(사람이 그린 원본이라 순환 채점이 아니다). APR1400 쪽 PDF는 저장소 밖(resources/references/APR1400_DCD/by-drawing)에
있으므로, 그 폴더가 없으면 APR1400 쪽은 건너뛰고 SNP만 잰다(건너뛴 사실을 찍고 기준값 비교에서 그 쪽은 빼지 않고 실패한다.
--allow-missing을 주면 SNP만으로 판정한다. CI가 이렇게 부른다).

정확도 = 맞은 수 / (정답 단위 수 + 오검출 수). 맞은 수와 분모를 함께 낸다. 기준값보다 맞은 수가 줄거나 오검출이 늘면 실패.
"""

import argparse
import glob
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

KEY_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "read-quality", "apr1400")
BASELINE = os.path.join(REPO_ROOT, "tests", "baselines", "read_quality.json")
ITEMS = ("kind", "tag", "connection", "attribute")
ITEM_LABEL = {"kind": "기호 종류", "tag": "태그·번호", "connection": "연결", "attribute": "속성"}

# 위치 맞춤(규격 §읽기 품질 지표 '맞춤'): 정답 기호 가운데가 추출 노드 상자를 MARGIN만큼 넓힌 안에 있거나,
# 두 가운데 거리가 NEAR 이하이면 짝 후보. 가까운 순서로 하나씩 짝짓는다.
MARGIN = 4.0
NEAR = 10.0
LINE_NEAR = 8.0   # 배관 속성(구경·배관 번호) 자리가 추출 배관 경로에서 떨어져도 되는 거리(pt)
TILE_W, TILE_H, TILE_OVERLAP, TILE_SCALE = 240.0, 160.0, 20.0, 5.0


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def norm_size(s):
    """배관 구경 글자: '3/4"'·'3/4 IN'·'0.75' 따위를 '3/4'꼴로. 숫자와 /·.만 남긴다."""
    return re.sub(r"[^0-9/.]", "", s or "")


# ---------------------------------------------------------------- 정답지 쓰기용 타일(추출 결과를 쓰지 않는다)

def render_page(pdf_path, scale):
    import pypdfium2
    doc = pypdfium2.PdfDocument(pdf_path)
    page = doc[0]
    w, h = page.get_size()
    return page.render(scale=scale).to_pil().convert("RGB"), (w, h)


def _grid(img, origin, scale, step=10.0, label_every=50.0):
    """그림 위에 pt 격자(10pt 연한 선, 50pt 진한 선과 숫자)를 그린다. origin은 그림 왼쪽 위의 pt 좌표."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    ox, oy = origin
    w, h = img.size
    x = math.ceil(ox / step) * step
    while (x - ox) * scale < w:
        px = (x - ox) * scale
        major = abs(x / label_every - round(x / label_every)) < 1e-6
        d.line([(px, 0), (px, h)], fill=(255, 120, 120) if major else (200, 220, 255), width=1)
        if major:
            d.text((px + 2, 2), "%d" % x, fill=(200, 0, 0))
            d.text((px + 2, h - 12), "%d" % x, fill=(200, 0, 0))
        x += step
    y = math.ceil(oy / step) * step
    while (y - oy) * scale < h:
        py = (y - oy) * scale
        major = abs(y / label_every - round(y / label_every)) < 1e-6
        d.line([(0, py), (w, py)], fill=(255, 120, 120) if major else (200, 220, 255), width=1)
        if major:
            d.text((2, py + 2), "%d" % y, fill=(200, 0, 0))
            d.text((w - 30, py + 2), "%d" % y, fill=(200, 0, 0))
        y += step


def tiles(pdf_path, out_dir, region=None):
    """쪽 전체 개요(격자 100pt)와 TILE_W×TILE_H pt 타일(겹침 TILE_OVERLAP, 격자 10pt)을 쓴다. → 타일 목록."""
    os.makedirs(out_dir, exist_ok=True)
    img, (pw, ph) = render_page(pdf_path, TILE_SCALE)
    over = img.resize((int(pw * 1.5), int(ph * 1.5)))
    _grid(over, (0, 0), 1.5, step=50.0, label_every=100.0)
    over.save(os.path.join(out_dir, "overview.png"))
    x0, y0, x1, y1 = region or (0, 0, pw, ph)
    out = []
    y = y0
    while y < y1:
        x = x0
        while x < x1:
            box = (x, y, min(x + TILE_W, x1), min(y + TILE_H, y1))
            crop = img.crop(tuple(int(v * TILE_SCALE) for v in box))
            _grid(crop, box[:2], TILE_SCALE)
            name = "tile-x%04d-y%04d.png" % (box[0], box[1])
            crop.save(os.path.join(out_dir, name))
            out.append({"file": name, "bbox": [round(v, 1) for v in box]})
            x += TILE_W - TILE_OVERLAP
        y += TILE_H - TILE_OVERLAP
    with open(os.path.join(out_dir, "tiles.json"), "w", encoding="utf-8") as fh:
        json.dump({"pdf": os.path.abspath(pdf_path), "page_size": [pw, ph], "scale": TILE_SCALE, "tiles": out},
                  fh, ensure_ascii=False, indent=1)
    return out


# ---------------------------------------------------------------- 채점(규격 '읽기 품질 지표')

# 같은 종류로 보는 이름(사전과 정답지가 같은 기호를 다른 이름으로 부르는 경우만)
KIND_SAME = {"psv": "relief_valve"}
NOT_SYMBOL = {"tee", None}
OFFPAGE_RE = re.compile(r"^(?:[\d/.]+\")?([A-Z]{2,3}):[A-Z0-9]")  # check_apr1400과 같은 꼴
SHEET_RE = re.compile(r"SHEET\s*(\d+)")
SYMBOL_FIELDS = ("normal_position", "fail_position")
LINE_FIELDS = ("size", "line_no", "material", "design_pressure")


def same_kind(a, b):
    return a is not None and KIND_SAME.get(a, a) == KIND_SAME.get(b, b)


PREFIX_RE = re.compile(r"^\s*([A-Z]{1,4})-(.+)$")


def same_tag(got, want):
    """태그가 같은가. 글자·숫자만 견준다. 추출기가 도면에 찍히지 않은 계통 앞머리('RC-')를 붙인 것도 같은 태그로 본다
    (도면 안에서는 앞머리 없이 쓰는 관례). 반대로 찍힌 앞머리를 빠뜨리면 틀림."""
    if not got or not want:
        return False
    if norm(got) == norm(want):
        return True
    m = PREFIX_RE.match(got.upper())
    return bool(m) and norm(m.group(2)) == norm(want)


def is_tag(t):
    """태그·번호로 세는 이름표: 숫자가 하나라도 든 것. 루프 번호 없는 'PI'처럼 기능 문자만 있는 글자는 식별자가 아니다."""
    return bool(t) and any(ch.isdigit() for ch in t)


def _bbox(n):
    g = n.get("geometry") or {}
    if "x" not in g:
        return None
    return (g["x"], g["y"], g["x"] + (g.get("width") or 0), g["y"] + (g.get("height") or 0))


def _center(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def in_regions(pt, regions):
    return any(r[0] <= pt[0] <= r[2] and r[1] <= pt[1] <= r[3] for r in regions)


def _near(sym_box, node_box):
    c = _center(sym_box)
    if node_box[0] - MARGIN <= c[0] <= node_box[2] + MARGIN and node_box[1] - MARGIN <= c[1] <= node_box[3] + MARGIN:
        return True
    return math.dist(c, _center(node_box)) <= NEAR


def match_symbols(symbols, nodes):
    """정답 기호 ↔ 추출 노드 하나씩 짝. 종류가 있는 노드와 먼저 짝짓고, 남은 기호를 미분류 노드와 짝짓는다.
    → {정답 id: 노드}."""
    out, used = {}, set()
    boxes = {n["local_id"]: _bbox(n) for n in nodes}
    for classified in (True, False):
        pool = [n for n in nodes if boxes[n["local_id"]] and n.get("kind") != "tee"
                and (n.get("kind") is not None) == classified]
        cand = sorted((math.dist(_center(s["bbox"]), _center(boxes[n["local_id"]])), s["id"], n["local_id"])
                      for s in symbols if s["id"] not in out
                      for n in pool if _near(s["bbox"], boxes[n["local_id"]]))
        by_id = {n["local_id"]: n for n in pool}
        for _, sid, nid in cand:
            if sid not in out and nid not in used:
                out[sid] = by_id[nid]
                used.add(nid)
    return out


def _count(correct=0, units=0, false_pos=0):
    return {"correct": correct, "units": units, "false_pos": false_pos}


def accuracy(c):
    den = c["units"] + c["false_pos"]
    return c["correct"] / den if den else None


def _in_region(n, regions):
    b = _bbox(n)
    return b is not None and in_regions(_center(b), regions)


def score_kind(key, ex, m):
    matched = {n["local_id"] for n in m.values()}
    correct = sum(1 for s in key["symbols"] if s["id"] in m and same_kind(m[s["id"]].get("kind"), s["kind"]))
    fp = sum(1 for n in ex["nodes"] if n.get("kind") not in NOT_SYMBOL and n["local_id"] not in matched
             and _in_region(n, key["regions"]))
    return _count(correct, len(key["symbols"]), fp)


def score_tag(key, ex, m):
    matched = {n["local_id"] for n in m.values()}
    units = [s for s in key["symbols"] if is_tag(s.get("tag"))]
    correct = sum(1 for s in units if s["id"] in m and same_tag(m[s["id"]].get("tag"), s["tag"]))
    fp = sum(1 for s in key["symbols"] if not s.get("tag") and s["id"] in m and m[s["id"]].get("tag"))
    fp += sum(1 for n in ex["nodes"] if n.get("tag") and n["local_id"] not in matched and n.get("kind") != "tee"
              and _in_region(n, key["regions"]))
    return _count(correct, len(units), fp)


def _adjacency(ex):
    adj = {}
    for r in ex.get("relations", []):
        if r.get("kind") != "physical_connection":
            continue
        ids = [e.get("node_local_id") for e in r["endpoints"]]
        if len(ids) != 2 or None in ids or ids[0] == ids[1]:
            continue
        fd = r.get("flow_direction") or {}
        for a, b in ((ids[0], ids[1]), (ids[1], ids[0])):
            adj.setdefault(a, []).append((b, fd.get("from") == a and fd.get("to") == b))
    return adj


def extracted_pairs(ex, m):
    """짝지은 노드끼리, 짝 없는 노드(티·미분류 등)만 지나서 닿는 쌍. → (쌍 집합 {frozenset(정답 id)},
    방향 쌍 집합 {(앞 id, 뒤 id)}: 지난 관계가 모두 흐름 방향과 같은 쪽인 경로가 있을 때)."""
    adj = _adjacency(ex)
    key_of = {n["local_id"]: sid for sid, n in m.items()}
    pairs, directed = set(), set()
    for sid, n in m.items():
        seen = {(n["local_id"], True)}
        stack = [(n["local_id"], True)]
        while stack:
            cur, fwd = stack.pop()
            for nxt, f in adj.get(cur, ()):
                state = (nxt, fwd and f)
                if state in seen:
                    continue
                seen.add(state)
                if nxt in key_of:
                    if key_of[nxt] != sid:
                        pairs.add(frozenset((sid, key_of[nxt])))
                        if fwd and f:
                            directed.add((sid, key_of[nxt]))
                    continue
                stack.append(state)
    return pairs, directed


def continuation_target(n):
    attrs = n.get("attributes") or {}
    text = (attrs.get("to_label") or n.get("label_text") or "").strip().upper()
    m = OFFPAGE_RE.match(text)
    sheet = SHEET_RE.search(text)
    return {"system": attrs.get("to_system") or (m.group(1) if m else None),
            "drawing": attrs.get("to_drawing"), "sheet": attrs.get("to_sheet") or (sheet.group(1) if sheet else None)}


def continuation_ok(c, n):
    got = continuation_target(n)
    if c.get("target_drawing"):  # 속성으로 따로 읽었거나, 이름표 글자에 도면번호가 그대로 들어 있으면 맞음
        want = norm(c["target_drawing"])
        return norm(got["drawing"]) == want or bool(re.search(r"(?<![A-Z0-9])%s(?![0-9])" % re.escape(
            c["target_drawing"].upper()), attrs_label(n).upper())) and bool(want)
    if c.get("target_system"):
        if norm(got["system"]) != norm(c["target_system"]):
            return False
        return not c.get("target_sheet") or not got["sheet"] or str(got["sheet"]) == str(c["target_sheet"])
    if c.get("label"):  # 계통·그림번호 없이 이름만 적힌 표기('SERVICE AIR'): 글자가 같으면 맞음
        return bool(norm(c["label"])) and norm(attrs_label(n)) == norm(c["label"])
    return False


def attrs_label(n):
    return (n.get("attributes") or {}).get("to_label") or n.get("label_text") or ""


# 계측 연결(규격 '연결'): 계기 원·비석이 낀 쌍은 공정 연결 단위가 아니다. 계기는 충격선·신호선으로 붙고, 추출기도 계기에
# 닿은 선을 measurement_connection으로 따로 둔다. 배관 안에 들어가는 flow_element는 공정 기호로 센다.
INSTRUMENT_KINDS = {"transmitter", "controller", "indicator", "temperature_element", "switch", "recorder"}


def process_connections(key):
    kind = {s["id"]: s["kind"] for s in key["symbols"]}
    return [c for c in key["connections"] if kind[c["a"]] not in INSTRUMENT_KINDS and kind[c["b"]] not in INSTRUMENT_KINDS]


def score_connection(key, ex, m):
    kind = {s["id"]: s["kind"] for s in key["symbols"]}
    pm = {sid: n for sid, n in m.items() if kind[sid] not in INSTRUMENT_KINDS}
    pairs, directed = extracted_pairs(ex, pm)
    conns = process_connections(key)
    want = {frozenset((c["a"], c["b"])) for c in conns}
    p = _count(len(want & pairs), len(want), len(pairs - want))
    flows = [c for c in conns if c.get("flow")]
    fl = _count(sum(1 for c in flows if ((c["a"], c["b"]) if c["flow"] == "a_to_b" else (c["b"], c["a"])) in directed),
                len(flows), 0)
    co = _count(sum(1 for c in key["continuations"] if c["symbol"] in m and continuation_ok(c, m[c["symbol"]])),
                len(key["continuations"]), 0)
    total = _count(*(sum(x[k] for x in (p, fl, co)) for k in ("correct", "units", "false_pos")))
    total["detail"] = {"pairs": p, "flows": fl, "continuations": co}
    return total


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _rel_points(r):
    eps = [e.get("point") for e in r.get("endpoints", [])]
    if len(eps) != 2 or None in eps:
        return []
    return [tuple(eps[0])] + [tuple(p) for p in r.get("waypoints") or []] + [tuple(eps[1])]


def _rel_value(r, field):
    v = (r.get("attributes") or {}).get(field)
    if v is None and field == "line_no":
        v = r.get("line_no")
    return v


def _same_value(field, a, b):
    if a is None or b is None:
        return False
    return norm_size(a) == norm_size(b) if field == "size" else norm(a) == norm(b)


def score_attribute(key, ex, m):
    correct = units = fp = 0
    for s in key["symbols"]:
        want = s.get("attributes") or {}
        got = (m[s["id"]].get("attributes") or {}) if s["id"] in m else {}
        for f in SYMBOL_FIELDS:
            if want.get(f):
                units += 1
                correct += _same_value(f, got.get(f), want[f])
            elif got.get(f):
                fp += 1
    rels = [(r, _rel_points(r)) for r in ex.get("relations", [])]
    claimed = set()
    for ln in key["lines"]:
        near = [r for r, pts in rels if len(pts) > 1
                and min(_seg_dist(ln["at"], a, b) for a, b in zip(pts, pts[1:])) <= LINE_NEAR]
        claimed.update(r["local_id"] for r in near)
        for f in LINE_FIELDS:
            if ln.get(f):
                units += 1
                correct += any(_same_value(f, _rel_value(r, f), ln[f]) for r in near)
    for r, pts in rels:
        if r["local_id"] in claimed or not pts or not in_regions(pts[len(pts) // 2], key["regions"]):
            continue
        fp += sum(1 for f in LINE_FIELDS if _rel_value(r, f))
    return _count(correct, units, fp)


def score_page(key, ex):
    m = match_symbols(key["symbols"], ex["nodes"])
    return {"kind": score_kind(key, ex, m), "tag": score_tag(key, ex, m),
            "connection": score_connection(key, ex, m), "attribute": score_attribute(key, ex, m),
            "matched": len(m)}


# ---------------------------------------------------------------- 두 정답지 견주기(독립 두 판의 일치율)

def _as_nodes(symbols):
    return [{"local_id": s["id"], "kind": s["kind"] or "?", "tag": s.get("tag"), "attributes": s.get("attributes") or {},
             "geometry": {"x": s["bbox"][0], "y": s["bbox"][1], "width": s["bbox"][2] - s["bbox"][0],
                          "height": s["bbox"][3] - s["bbox"][1]}} for s in symbols]


def compare_keys(a, b):
    """같은 쪽을 따로 쓴 정답지 A·B를 견준다. 기호는 위치로 짝짓는다(채점과 같은 허용 오차).
    → {agree: {항목: 수}, disagree: {항목: 수}, disputes: [{item, a, b, bbox}], map: {A id: B id}}.
    항목: symbol(한쪽에만 있는 기호), kind, tag, attribute(기호 위치 속성과 배관 글자), connection(쌍·흐름·도면 밖 연결)."""
    items = ("symbol", "kind", "tag", "attribute", "connection")
    agree, disagree, disputes = dict.fromkeys(items, 0), dict.fromkeys(items, 0), []
    sa, sb = {s["id"]: s for s in a["symbols"]}, {s["id"]: s for s in b["symbols"]}

    def dispute(item, va, vb, box, **extra):
        disagree[item] += 1
        disputes.append(dict({"item": item, "a": va, "b": vb, "bbox": [round(v, 1) for v in box]}, **extra))

    m = {aid: n["local_id"] for aid, n in match_symbols(a["symbols"], _as_nodes(b["symbols"])).items()}
    back = {v: k for k, v in m.items()}
    agree["symbol"] = len(m)
    for s in a["symbols"]:
        if s["id"] not in m:
            dispute("symbol", _describe(s), None, s["bbox"], a_id=s["id"])
    for s in b["symbols"]:
        if s["id"] not in back:
            dispute("symbol", None, _describe(s), s["bbox"], b_id=s["id"])
    for aid, bid in m.items():
        x, y = sa[aid], sb[bid]
        box = _union(x["bbox"], y["bbox"])
        if same_kind(x["kind"], y["kind"]):  # unlisted끼리는 kind_text 글이 달라도 같은 판단으로 본다
            agree["kind"] += 1
        else:
            dispute("kind", _describe(x), _describe(y), box, a_id=aid, b_id=bid)
        if is_tag(x.get("tag")) or is_tag(y.get("tag")):
            if same_tag(x.get("tag"), y.get("tag")) or same_tag(y.get("tag"), x.get("tag")):
                agree["tag"] += 1
            else:
                dispute("tag", x.get("tag"), y.get("tag"), box, a_id=aid, b_id=bid)
        for f in SYMBOL_FIELDS:
            va, vb = (x.get("attributes") or {}).get(f), (y.get("attributes") or {}).get(f)
            if va or vb:
                if _same_value(f, va, vb):
                    agree["attribute"] += 1
                else:
                    dispute("attribute", "%s=%s" % (f, va), "%s=%s" % (f, vb), box, a_id=aid, b_id=bid)
    used = set()
    for la in a["lines"]:
        lb = min((l for l in b["lines"] if l["id"] not in used and math.dist(l["at"], la["at"]) <= 2 * LINE_NEAR),
                 key=lambda l: math.dist(l["at"], la["at"]), default=None)
        if lb:
            used.add(lb["id"])
        for f in LINE_FIELDS:
            va, vb = la.get(f), (lb or {}).get(f)
            if va or vb:
                if _same_value(f, va, vb):
                    agree["attribute"] += 1
                else:
                    x, y = la["at"]
                    dispute("attribute", "배관 %s=%s" % (f, va), "배관 %s=%s" % (f, vb), [x - 6, y - 6, x + 6, y + 6],
                            a_line=la["id"], b_line=(lb or {}).get("id"))
    for lb in b["lines"]:
        if lb["id"] not in used:
            for f in LINE_FIELDS:
                if lb.get(f):
                    x, y = lb["at"]
                    dispute("attribute", None, "배관 %s=%s" % (f, lb[f]), [x - 6, y - 6, x + 6, y + 6], b_line=lb["id"])
    ca = {frozenset((c["a"], c["b"])): c for c in process_connections(a)}
    cb = {}
    for c in process_connections(b):
        ends = (back.get(c["a"], "B:" + c["a"]), back.get(c["b"], "B:" + c["b"]))
        flow = c.get("flow")
        cb[frozenset(ends)] = {"a": ends[0], "b": ends[1], "flow": flow}

    def ends_box(ends):
        boxes = [sa[e]["bbox"] if e in sa else sb[e[2:]]["bbox"] for e in ends]
        return _union(*boxes)

    def desc(e):
        return _describe(sa[e]) if e in sa else "B만: " + _describe(sb[e[2:]])

    for p in set(ca) | set(cb):
        ends = sorted(p)
        if p in ca and p in cb:
            agree["connection"] += 1
            fa = ca[p].get("flow") and ((ca[p]["a"], ca[p]["b"]) if ca[p]["flow"] == "a_to_b" else (ca[p]["b"], ca[p]["a"]))
            fb = cb[p].get("flow") and ((cb[p]["a"], cb[p]["b"]) if cb[p]["flow"] == "a_to_b" else (cb[p]["b"], cb[p]["a"]))
            if fa or fb:
                if fa == fb:
                    agree["connection"] += 1
                else:
                    dispute("connection", "흐름 %s" % (fa and " → ".join(desc(e) for e in fa)),
                            "흐름 %s" % (fb and " → ".join(desc(e) for e in fb)), ends_box(ends), pair=ends)
        else:
            text = " ↔ ".join(desc(e) for e in ends)
            dispute("connection", text if p in ca else None, text if p in cb else None, ends_box(ends), pair=ends)
    cona = {c["symbol"]: c for c in a["continuations"]}
    conb = {back.get(c["symbol"]): c for c in b["continuations"] if c["symbol"] in back}
    for sid in set(cona) | set(k for k in conb if k):
        x, y = cona.get(sid), conb.get(sid)
        key_of = lambda c: c and (norm(c.get("target_system")), norm(c.get("target_sheet")), norm(c.get("target_drawing")))
        if x and y and key_of(x) == key_of(y):
            agree["connection"] += 1
        elif sid in sa:
            dispute("connection", "도면 밖 %s" % (key_of(x),), "도면 밖 %s" % (key_of(y),), sa[sid]["bbox"], a_id=sid)
    return {"agree": agree, "disagree": disagree, "disputes": disputes, "map": m}


# ---------------------------------------------------------------- AI 후보(규격 '스크립트 + AI 후보')

def apply_candidates(ex, cands):
    """후보마다 첫 값만 받아들인 추출 결과 사본. 원본은 바꾸지 않는다. 후보 꼴(규격 'AI 후보 파일'):
    {node_local_id | new_id+bbox, field: kind|tag|normal_position|fail_position, values: [...]},
    {field: connection, a, b, values: [...]}, {relation_local_id, field: size|line_no|material|design_pressure, values}."""
    import copy
    out = copy.deepcopy(ex)
    out.setdefault("relations", [])
    nodes = {n["local_id"]: n for n in out["nodes"]}
    rels = {r["local_id"]: r for r in out["relations"]}
    for i, c in enumerate((cands or {}).get("candidates", [])):
        if not c.get("values"):
            continue
        v, f = c["values"][0], c.get("field")
        if f == "connection":
            if c.get("a") in nodes and c.get("b") in nodes:
                out["relations"].append({"local_id": "ai-rel-%d" % i, "kind": "physical_connection",
                                         "endpoints": [{"node_local_id": c["a"], "point": None},
                                                       {"node_local_id": c["b"], "point": None}],
                                         "flow_direction": None, "waypoints": [], "attributes": {}})
            continue
        if c.get("relation_local_id") in rels:
            rels[c["relation_local_id"]].setdefault("attributes", {})[f] = v
            continue
        n = nodes.get(c.get("node_local_id") or c.get("new_id"))
        if n is None and c.get("new_id") and c.get("bbox"):
            b = c["bbox"]
            n = {"local_id": c["new_id"], "kind": None, "tag": None, "attributes": {}, "label_text": "",
                 "geometry": {"x": b[0], "y": b[1], "width": b[2] - b[0], "height": b[3] - b[1]}}
            out["nodes"].append(n)
            nodes[n["local_id"]] = n
        if n is None:
            continue
        if f in ("kind", "tag"):
            n[f] = v
        elif f in SYMBOL_FIELDS:
            n.setdefault("attributes", {})[f] = v
    return out


# ---------------------------------------------------------------- 기준값

def ratchet(base, now):
    """→ 후퇴 목록. 쪽·항목마다 맞은 수가 줄거나 오검출이 늘면 후퇴. 정답 단위 수가 다르면 정답지가 바뀐 것이라 실패."""
    bad = []
    for page, items in sorted(base["pages"].items()):
        got = now["pages"].get(page)
        if got is None:
            bad.append("%s: 지금 결과에 없음" % page)
            continue
        for it in ITEMS:
            b, n = items[it], got[it]
            if b["units"] != n["units"]:
                bad.append("%s %s: 정답 단위 %d → %d(정답지가 바뀌었으면 기준값도 갱신)" % (page, it, b["units"], n["units"]))
            if n["correct"] < b["correct"]:
                bad.append("%s %s: 맞음 %d → %d" % (page, it, b["correct"], n["correct"]))
            if n["false_pos"] > b["false_pos"]:
                bad.append("%s %s: 오검출 %d → %d" % (page, it, b["false_pos"], n["false_pos"]))
    return bad


# ---------------------------------------------------------------- SNP 가상 도면: drawio 원본을 정답지로

def fit_scale(pairs, tol=1.0):
    """drawio 좌표 → PDF 좌표의 균일 배율과 이동(x' = s·x + tx, y' = s·y + ty). 가장 어긋난 짝부터 빼며
    남은 짝이 모두 tol pt 안에 들 때까지 다시 맞춘다. → (s, tx, ty, 쓴 짝 수)."""
    def fit(ps):
        k = len(ps)
        mx, my = sum(a[0] for a, _ in ps) / k, sum(a[1] for a, _ in ps) / k
        nx, ny = sum(b[0] for _, b in ps) / k, sum(b[1] for _, b in ps) / k
        num = sum((a[0] - mx) * (b[0] - nx) + (a[1] - my) * (b[1] - ny) for a, b in ps)
        den = sum((a[0] - mx) ** 2 + (a[1] - my) ** 2 for a, _ in ps)
        s = num / den
        return s, nx - s * mx, ny - s * my

    def err(t, p):
        return max(abs(t[0] * p[0][0] + t[1] - p[1][0]), abs(t[0] * p[0][1] + t[2] - p[1][1]))

    keep = list(pairs)
    if len(keep) < 3:
        raise ValueError("좌표 맞춤 짝이 3개 미만")
    t = fit(keep)
    while len(keep) > 3 and max(err(t, p) for p in keep) > tol:
        keep.remove(max(keep, key=lambda p: err(t, p)))
        t = fit(keep)
    return t[0], t[1], t[2], len(keep)


def snp_key(dio, pdf_path, name):
    """drawio 추출 결과(사람이 그린 원본)를 PDF 좌표로 옮긴 정답지. 글자 값(태그·배관 번호)은 PDF에 실제로 찍힌 것만 둔다
    (PDF 텍스트 층은 보이는지 거르는 데만 쓴다). 좌표 맞춤: 가운데 두 줄 이름표(TT 위 110)를 PDF 낱말 쌍과 맞춘다."""
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        pg = pdf.pages[0]
        words = pg.extract_words()
        size = [float(pg.width), float(pg.height)]
    tokens = {norm(w["text"]) for w in words}
    pairs_of = {}
    for w1 in words:
        for w2 in words:
            c1, c2 = (w1["x0"] + w1["x1"]) / 2, (w2["x0"] + w2["x1"]) / 2
            if abs(c1 - c2) < 4 and 3 < w2["top"] - w1["top"] < 12:
                pairs_of.setdefault((w1["text"], w2["text"]), []).append(((c1 + c2) / 2, (w1["top"] + w2["bottom"]) / 2))
    src = {}
    for n in dio["nodes"]:
        st = (n.get("label_location") or {}).get("style") or {}
        parts = tuple((n.get("label_text") or "").split("\n"))
        g = n.get("geometry")
        if g and len(parts) == 2 and st.get("labelPosition") == "center" and st.get("verticalLabelPosition") == "middle":
            src.setdefault(parts, []).append((g["x"] + g["width"] / 2, g["y"] + g["height"] / 2))
    pairs = [(src[k][0], pairs_of[k][0]) for k in src if len(src[k]) == 1 and len(pairs_of.get(k, [])) == 1]
    s, tx, ty, used = fit_scale(pairs)

    def pt(p):
        return [round(s * p[0] + tx, 1), round(s * p[1] + ty, 1)]

    symbols, by_local = [], {}
    for n in dio["nodes"]:
        b = _bbox(n)
        if n.get("kind") in NOT_SYMBOL or b is None:
            continue
        lab = norm((n.get("label_text") or "").split("\n")[0] + "".join((n.get("label_text") or "").split("\n")[1:2]))
        if n.get("tag") and norm(n["tag"]) in tokens:
            tag = n["tag"]
        elif n.get("tag") and is_tag(lab):
            tag = lab  # 계기 원 안의 두 줄(TT / 110)처럼 계통 앞머리 없이 찍힌 이름표
        else:
            tag = None
        sid = "s%03d" % (len(symbols) + 1)
        box = pt(b[:2]) + pt(b[2:])
        # 밸브 위치는 PDF에 그 글자(NO·LC…)가 기호 40pt 안에 찍힌 것만 정답으로 둔다(drawio 속성에만 있는 값은 뺀다)
        attrs = {f: v for f, v in ((f, (n.get("attributes") or {}).get(f)) for f in SYMBOL_FIELDS)
                 if v and any(norm(w["text"]) == norm(v) and box[0] - 40 <= (w["x0"] + w["x1"]) / 2 <= box[2] + 40
                              and box[1] - 40 <= (w["top"] + w["bottom"]) / 2 <= box[3] + 40 for w in words)}
        symbols.append({"id": sid, "kind": n["kind"], "bbox": box, "tag": tag, "attributes": attrs})
        by_local[n["local_id"]] = sid
    m = {by_local[n["local_id"]]: n for n in dio["nodes"] if n["local_id"] in by_local}
    found, directed = extracted_pairs(dio, m)
    connections = []
    for a, b in sorted(tuple(sorted(p)) for p in found):
        flow = "a_to_b" if (a, b) in directed and (b, a) not in directed else (
            "b_to_a" if (b, a) in directed and (a, b) not in directed else None)
        connections.append({"a": a, "b": b, "flow": flow})
    continuations = [{"symbol": by_local[n["local_id"]], "label": n.get("label_text") or "", "target_system": None,
                      "target_sheet": None, "target_drawing": (n.get("attributes") or {}).get("to_drawing")}
                     for n in dio["nodes"] if n.get("kind") == "continuation" and n["local_id"] in by_local]
    lines, seen = [], set()
    for r in dio["relations"]:
        no = r.get("line_no") or (r.get("attributes") or {}).get("line_no")
        pts = _rel_points(r)
        if r.get("kind") != "physical_connection" or not no or norm(no) not in tokens or len(pts) < 2 or no in seen:
            continue
        seen.add(no)  # 배관 번호는 한 번만 센다
        a, b = pts[len(pts) // 2 - 1], pts[len(pts) // 2]
        lines.append({"id": "l%03d" % (len(lines) + 1), "at": pt(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)), "line_no": no})
    return {"schema": "hazop_read_quality_key", "version": 1, "drawing": name, "page_size": size,
            "regions": [[0, 0, size[0], size[1]]],
            "method": "drawio 원본(사람이 그린 정답)을 PDF 좌표로 옮김. 배율 %.4f, 이동 (%.1f, %.1f), 맞춘 짝 %d"
                      % (s, tx, ty, used),
            "symbols": symbols, "lines": lines, "connections": connections, "continuations": continuations}


# ---------------------------------------------------------------- 사용자 확인 표본

def _describe(s):
    k = s["kind"] if s["kind"] != "unlisted" else "unlisted(%s)" % s.get("kind_text", "")
    return "%s %s" % (k, s["tag"]) if s.get("tag") else k


def _union(*boxes):
    boxes = [b for b in boxes if b]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def key_units(key):
    """정답 단위 목록(분모와 같다). 항목마다 {item, id, what, value, bbox}. bbox는 그림 조각을 자를 범위(pt)."""
    sym = {s["id"]: s for s in key["symbols"]}
    out = [{"item": "kind", "id": s["id"], "what": "기호 종류", "value": _describe(s), "bbox": s["bbox"]}
           for s in key["symbols"]]
    out += [{"item": "tag", "id": s["id"], "what": "태그·번호 (%s)" % s["kind"], "value": s["tag"],
             "bbox": _union(s["bbox"], s.get("tag_bbox"))} for s in key["symbols"] if is_tag(s.get("tag"))]
    for c in process_connections(key):
        a, b = sym[c["a"]], sym[c["b"]]
        out.append({"item": "connection", "id": "%s-%s" % (c["a"], c["b"]), "what": "연결",
                    "value": "%s ↔ %s" % (_describe(a), _describe(b)), "bbox": _union(a["bbox"], b["bbox"])})
        if c.get("flow"):
            f, t = (a, b) if c["flow"] == "a_to_b" else (b, a)
            out.append({"item": "connection", "id": "%s-%s-flow" % (c["a"], c["b"]), "what": "흐름 방향",
                        "value": "%s → %s" % (_describe(f), _describe(t)), "bbox": _union(a["bbox"], b["bbox"])})
    for c in key["continuations"]:
        out.append({"item": "connection", "id": c["symbol"] + "-to", "what": "도면 밖 연결",
                    "value": "%s (계통 %s, 시트 %s, 그림 %s)" % ((c.get("label") or "").replace("\n", " "),
                                                         c.get("target_system"), c.get("target_sheet"),
                                                         c.get("target_drawing")),
                    "bbox": sym[c["symbol"]]["bbox"]})
    for s in key["symbols"]:
        for f in SYMBOL_FIELDS:
            if (s.get("attributes") or {}).get(f):
                out.append({"item": "attribute", "id": "%s-%s" % (s["id"], f), "what": "%s (%s)" % (f, _describe(s)),
                            "value": s["attributes"][f], "bbox": s["bbox"]})
    for ln in key["lines"]:
        for f in LINE_FIELDS:
            if ln.get(f):
                x, y = ln["at"]
                out.append({"item": "attribute", "id": "%s-%s" % (ln["id"], f), "what": "배관 %s" % f, "value": ln[f],
                            "bbox": _union([x - 4, y - 4, x + 4, y + 4], ln.get("text_bbox"))})
    return out


def sample_units(units, n, seed):
    return random.Random(seed).sample(units, min(n, len(units)))


def write_crop(img, scale, unit, path, pad=40.0):
    from PIL import ImageDraw
    b = unit["bbox"]
    box = [max(0, b[0] - pad), max(0, b[1] - pad), b[2] + pad, b[3] + pad]
    crop = img.crop(tuple(int(v * scale) for v in box)).copy()
    d = ImageDraw.Draw(crop)
    d.rectangle([(b[0] - box[0]) * scale - 3, (b[1] - box[1]) * scale - 3,
                 (b[2] - box[0]) * scale + 3, (b[3] - box[1]) * scale + 3], outline=(230, 0, 0), width=3)
    crop.save(path)


# ---------------------------------------------------------------- 실행

def load_keys(only=None):
    keys = []
    for path in sorted(glob.glob(os.path.join(KEY_DIR, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            k = json.load(fh)
        k.setdefault("lines", [])
        k.setdefault("continuations", [])
        if only and k["seq"] not in only:
            continue
        keys.append((os.path.splitext(os.path.basename(path))[0], k))
    return keys


def apr_pdf(input_dir, seq):
    hits = glob.glob(os.path.join(input_dir, "%03d_*.pdf" % seq))
    return hits[0] if len(hits) == 1 else None


def snp_folders(samples_dir):
    return sorted(d for d in glob.glob(os.path.join(samples_dir, "SNP-*")) if os.path.isdir(d))


def run(input_dir, samples_dir, pages=None, ai_dir=None):
    import extract_drawio
    from hazop.extract.adapters import pdf_vector
    work = tempfile.mkdtemp(prefix="hazop-read-quality-")
    os.environ["HAZOP_WORK_ROOT"] = work
    res = {"pages": {}, "ai_pages": {}, "missing": []}
    try:
        jobs = []
        for name, k in load_keys(pages):
            pdf = apr_pdf(input_dir, k["seq"]) if os.path.isdir(input_dir) else None
            if pdf is None:
                res["missing"].append(name)
            else:
                jobs.append((name, k, pdf))
        if not pages:
            for folder in snp_folders(samples_dir):
                dio_path = glob.glob(os.path.join(folder, "*.drawio"))
                pdf = glob.glob(os.path.join(folder, "*.pdf"))
                if dio_path and pdf:
                    dio, _ = extract_drawio.run_one(dio_path[0], os.path.join(work, "extract"))
                    name = os.path.basename(folder).split("_")[0]
                    jobs.append((name, snp_key(dio, pdf[0], name), pdf[0]))
        for name, k, pdf in jobs:
            ex = pdf_vector.extract(pdf, page=0, repo_root=work)
            res["pages"][name] = score_page(k, ex)
            cand_path = os.path.join(ai_dir, name + ".json") if ai_dir else None
            if cand_path and os.path.isfile(cand_path):
                with open(cand_path, encoding="utf-8") as fh:
                    res["ai_pages"][name] = score_page(k, apply_candidates(ex, json.load(fh)))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return res


def totals(pages, prefix=None):
    out = {}
    for it in ITEMS:
        rows = [p[it] for n, p in pages.items() if prefix is None or n.startswith(prefix)]
        out[it] = _count(*(sum(r[k] for r in rows) for k in ("correct", "units", "false_pos")))
    return out


def fmt(c):
    a = accuracy(c)
    return "%d/%d(%s, 오검출 %d)" % (c["correct"], c["units"] + c["false_pos"],
                                  "—" if a is None else "%.1f%%" % (100 * a), c["false_pos"])


def report(res, at):
    lines = []
    for label, pages in (("스크립트만", res["pages"]), ("스크립트 + AI 후보", res["ai_pages"])):
        if not pages:
            lines.append("%s: 후보 파일 없음(값은 스크립트만과 같다)" % label)
            continue
        lines.append("%s @%s" % (label, at))
        for name in sorted(pages):
            lines.append("  %-14s " % name + " · ".join("%s %s" % (ITEM_LABEL[it], fmt(pages[name][it])) for it in ITEMS))
        for lab, prefix in (("APR1400 합계", "apr1400-"), ("SNP 합계", "SNP-"), ("전체 합계", None)):
            t = totals(pages, prefix)
            lines.append("  %-14s " % lab + " · ".join("%s %s" % (ITEM_LABEL[it], fmt(t[it])) for it in ITEMS))
    if res["missing"]:
        lines.append("PDF가 없어 건너뜀: %s" % ", ".join(res["missing"]))
    return "\n".join(lines)


def head_commit():
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # git이 없는 곳에서도 돈다
        return "unknown"


def default_input_dir():
    from hazop import paths
    return paths.folder("APR1400", "by-drawing")


def default_samples_dir():
    from hazop import paths
    return paths.folder("references", "pid-samples")


def cmd_sample(args):
    input_dir = os.path.abspath(args.input_dir or default_input_dir())
    os.makedirs(os.path.join(args.out, "crops"), exist_ok=True)
    rows = []
    for name, k in load_keys():
        pdf = apr_pdf(input_dir, k["seq"])
        picked = sample_units(key_units(k), args.per_page, args.seed + k["seq"])
        img, _ = render_page(pdf, 4.0)
        for i, u in enumerate(picked, 1):
            crop = os.path.join(args.out, "crops", "%s-%02d.png" % (name, i))
            write_crop(img, 4.0, u, crop)
            rows.append({"page": name, "drawing": k["drawing"], "no": i, "item": u["item"], "id": u["id"],
                         "what": u["what"], "value": u["value"], "bbox": [round(v, 1) for v in u["bbox"]], "crop": crop})
    with open(os.path.join(args.out, "sample.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print("표본 %d건: %s" % (len(rows), args.out))
    return 0


def cmd_compare(args):
    """저장소 정답지(A)와 독립으로 쓴 정답지(B, 같은 파일 이름)를 견줘 쪽·항목별 일치율과 어긋난 항목 목록·그림 조각을 쓴다."""
    input_dir = os.path.abspath(args.input_dir or default_input_dir())
    out = os.path.abspath(args.out)
    os.makedirs(os.path.join(out, "crops"), exist_ok=True)
    summary = {}
    for name, a in load_keys():
        path_b = os.path.join(args.key_b, name + ".json")
        if not os.path.isfile(path_b):
            print("B 없음: %s" % name)
            continue
        with open(path_b, encoding="utf-8") as fh:
            b = json.load(fh)
        b.setdefault("lines", [])
        b.setdefault("continuations", [])
        r = compare_keys(a, b)
        img = render_page(apr_pdf(input_dir, a["seq"]), 4.0)[0] if args.crops else None
        for i, d in enumerate(r["disputes"], 1):
            d["no"] = i
            if img is not None:
                d["crop"] = os.path.join(out, "crops", "%s-%03d.png" % (name, i))
                write_crop(img, 4.0, d, d["crop"])
        with open(os.path.join(out, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=1)
        summary[name] = {"agree": r["agree"], "disagree": r["disagree"]}
        print("%-12s " % name + " · ".join("%s %d/%d" % (it, r["agree"][it], r["agree"][it] + r["disagree"][it])
                                           for it in r["agree"]))
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    return 0


def main(argv=None):
    from hazop.console import safe_console
    safe_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["compare"]:
        ap = argparse.ArgumentParser(prog="check_read_quality.py compare")
        ap.add_argument("key_b", help="독립으로 쓴 정답지 폴더(파일 이름이 저장소 정답지와 같음)")
        ap.add_argument("out")
        ap.add_argument("--input-dir")
        ap.add_argument("--crops", action="store_true", help="어긋난 항목마다 그림 조각을 쓴다")
        return cmd_compare(ap.parse_args(argv[1:]))
    if argv[:1] == ["tiles"]:
        ap = argparse.ArgumentParser(prog="check_read_quality.py tiles")
        ap.add_argument("pdf")
        ap.add_argument("out")
        a = ap.parse_args(argv[1:])
        print("타일 %d장: %s" % (len(tiles(a.pdf, a.out)), a.out))
        return 0
    if argv[:1] == ["sample"]:
        ap = argparse.ArgumentParser(prog="check_read_quality.py sample")
        ap.add_argument("out")
        ap.add_argument("--per-page", type=int, default=20)
        ap.add_argument("--seed", type=int, default=20261113)
        ap.add_argument("--input-dir")
        return cmd_sample(ap.parse_args(argv[1:]))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input-dir", help="APR1400 쪽별 PDF 폴더(기본: 저장소의 APR1400 by-drawing)")
    ap.add_argument("--samples-dir", help="SNP 표본 폴더(기본: resources/references/pid-samples)")
    ap.add_argument("--pages", help="APR1400 순번 몇 개만(쉼표). SNP는 빼고, 기준값 비교·갱신을 하지 않음")
    ap.add_argument("--ai-candidates", help="AI 후보 폴더(<정답지 이름>.json)")
    ap.add_argument("--allow-missing", action="store_true", help="APR1400 PDF가 없으면 그 쪽을 빼고 판정(CI)")
    ap.add_argument("--baseline", default=BASELINE)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--force", action="store_true", help="HEAD와 다른(커밋 안 한) 기준값도 --update로 덮음")
    ap.add_argument("--json", help="쪽별 결과를 JSON으로 쓸 경로")
    args = ap.parse_args(argv)
    import devenv
    devenv.require("apr1400", check_disk=False)
    if args.update:
        devenv.require_baseline_update(args.baseline, args.force)
    pages = {int(x) for x in args.pages.split(",")} if args.pages else None
    input_dir = os.path.abspath(args.input_dir or default_input_dir())
    if not os.path.isdir(input_dir):  # CI처럼 DCD 원본 폴더가 아예 없으면 SNP만으로 판정한다(폴더가 있는데 쪽이 빠지면 실패)
        print("APR1400 쪽 폴더가 없어 SNP만 잰다: %s" % input_dir)
        args.allow_missing = True
    res = run(input_dir, os.path.abspath(args.samples_dir or default_samples_dir()), pages, args.ai_candidates)
    print(report(res, head_commit()))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
    if pages:
        return 0
    saved = {"pages": {n: {it: {k: p[it][k] for k in ("correct", "units", "false_pos")} for it in ITEMS}
                       for n, p in res["pages"].items()}}
    if args.update:
        if res["missing"]:
            print("PDF가 없는 쪽이 있어 기준값을 쓰지 않음: %s" % ", ".join(res["missing"]), file=sys.stderr)
            return 2
        devenv.require_baseline_update(args.baseline, args.force)
        with open(args.baseline, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(saved, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print("기준값을 썼음: %s" % args.baseline)
        return 0
    with open(args.baseline, encoding="utf-8") as fh:
        base = json.load(fh)
    if res["missing"]:
        if not args.allow_missing:
            print("PDF가 없어 잴 수 없는 쪽: %s (--allow-missing이면 그 쪽을 빼고 판정)" % ", ".join(res["missing"]),
                  file=sys.stderr)
            return 1
        base = {"pages": {n: v for n, v in base["pages"].items() if n not in res["missing"]}}
    bad = ratchet(base, saved)
    for line in bad:
        print("후퇴: %s" % line)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
