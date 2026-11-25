"""내보내는 DEXPI 2.0.1의 그림 쪽(HZ-PLN-22 §6.7): 기호의 자리·크기·방향, 배관과 신호선의 길, 글자.

추출 결과의 값만 쓰고 자리나 방향을 지어내지 않는다. 쓸 수 없는 값(수가 아님, 크기 0, 도면 밖, 점 하나짜리 선, 끝 모름)은 XML에 쓰지 않고
곁 파일의 `picture.not_drawn`에 원래 단위로 적는다. 구성요소와 연결은 그림이 없어도 그대로 나간다.
- 기호 모양(Shape)은 종류마다 하나이고 이름과 1 × 1 상자만 있다. 받는 쪽은 이름으로 자기 기호를 고른다.
- 신호선은 2.0.1 Reference P&ID처럼 양 끝에 InstrumentationNodePosition을 두고 그 둘을 ConnectorLine으로 잇는다.
"""

import math

from hazop.export import dexpi_xml as dx
from hazop.extract import drawio
from hazop.extract.adapters import dexpi_shape
from hazop.extract.adapters.dexpi_shape import Placement, unit_placement

A3 = (420.0, 297.0)
TEXT_MM = 2.0
TEXT_CHARS = 40
TEXT_LINES = 2
PIPE_MM, SIGNAL_MM, SHAPE_MM = 0.5, 0.25, 0.25
MATCH_MM = 0.002  # 좌표를 소수 셋째 자리로 쓰므로 되읽은 값이 이 안에서 같아야 한다
DIRECTION = {"east": 0.0, "south": 90.0, "west": 180.0, "north": 270.0}
BOX_KEYS = ("x", "y", "width", "height")


class Undrawable(Exception):
    """그릴 수 없는 까닭 코드: no_box · bad_number · zero_size · off_sheet · orientation_unknown · one_point · end_unknown."""


def _ok(values):
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def _plain(v):
    """곁 파일에 적을 값. JSON에 없는 수(nan·inf)는 글자로."""
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return repr(v) if isinstance(v, float) and not math.isfinite(v) else v


def label_lines(text):
    """원본 글자 -> 그릴 줄(빈 줄을 빼고 두 줄까지, 정리된 보기와 같다)."""
    return [ln.strip()[:TEXT_CHARS] for ln in dx.clean_text(text or "").splitlines() if ln.strip()][:TEXT_LINES]


# ---------------------------------------------------------------- 추출 결과 -> 놓을 자리(원래 단위)
def source_box(node, location, fmt):
    """기호가 놓인 상자 [x, y, 너비, 높이](원래 단위). drawio의 geometry는 부모 도형 기준이라 쪽 기준 자리(source_locations)를 쓴다."""
    if fmt == "drawio" and location:
        return list(location["bbox"])
    g = node.get("geometry") or {}
    return [g.get(k) for k in BOX_KEYS] if any(g.get(k) is not None for k in BOX_KEYS) else None


def drawio_turn(style):
    """drawio 스타일 -> (direction의 각도, 회전, 뒤집힘). drawio 읽기(drawio._symbol_direction)가 모른다고 하는 조합(동쪽이 아닌 direction과
    뒤집기가 함께, 처음 보는 값, 수가 아닌 회전)은 방향을 지어내지 않고 Undrawable."""
    direction = DIRECTION.get(style.get("direction", "east"))
    flips = [style.get(k, "0") for k in ("flipH", "flipV")]
    try:
        turn = float(style.get("rotation") or 0.0)
    except (TypeError, ValueError):
        turn = math.nan
    if direction is None or any(f not in ("0", "1") for f in flips) or (direction and "1" in flips) or not math.isfinite(turn):
        raise Undrawable("orientation_unknown")
    # 위아래 뒤집기는 좌우 뒤집고 180도 돌린 것과 같다
    return direction, direction + turn + (180.0 if flips[1] == "1" else 0.0), flips[0] != flips[1]


def source_placement(node, location, fmt):
    """추출한 노드 -> 1 × 1 모양의 놓임(원래 단위). 쓸 수 없으면 Undrawable."""
    box = source_box(node, location, fmt)
    if box is None:
        raise Undrawable("no_box")
    if not _ok(box):
        raise Undrawable("bad_number")
    shape = (node.get("geometry") or {}).get("shape")
    if shape:  # DEXPI에서 읽은 기호: 돌리기 전 크기와 각도를 그대로 되쓴다
        size = (shape.get("width"), shape.get("height"), shape.get("rotation"))
        if not _ok(size):
            raise Undrawable("bad_number")
        return Placement(box[0] + box[2] / 2.0, box[1] + box[3] / 2.0, size[0], size[1], size[2], bool(shape.get("mirrored")))
    if fmt != "drawio":
        return unit_placement(box)
    direction, rotation, mirrored = drawio_turn(drawio.parse_style(node.get("style")))
    # direction은 상자 안에서 도형만 돌고(배율의 가로세로가 바뀜), rotation은 상자째 가운데를 두고 돈다
    return unit_placement(box, direction)._replace(rotation=rotation, mirrored=mirrored)


def is_approximate(node, location, fmt):
    """drawio 읽기가 자리를 근사로 본 도형(돌아간 부모 안, 부모 크기 비율)이거나, 부모 도형 안이라 부모의 회전·뒤집기를 알 수 없는 도형인가."""
    if fmt != "drawio" or not location:
        return False
    g = node.get("geometry") or {}
    return bool(location.get("approximate")) or [g.get("x", 0), g.get("y", 0)] != list(location["bbox"][:2])


def source_path(rel):
    """추출한 관계 -> 점 목록(원래 단위, source에서 target으로). 쓸 수 없으면 Undrawable."""
    ends = {e.get("end"): e.get("point") for e in rel.get("endpoints") or []}
    pts = [ends.get("source")] + list(rel.get("waypoints") or []) + [ends.get("target")]
    if pts[0] is None or pts[-1] is None:
        raise Undrawable("end_unknown")
    if not all(isinstance(p, (list, tuple)) and len(p) == 2 and _ok(p) for p in pts):
        raise Undrawable("bad_number")
    if len({tuple(p) for p in pts}) < 2:
        raise Undrawable("one_point")
    return [list(p) for p in pts]


def raw_points(rel):
    """곁 파일에 적을 점(모르는 끝은 None)."""
    ends = {e.get("end"): e.get("point") for e in rel.get("endpoints") or []}
    return _plain([ends.get("source")] + list(rel.get("waypoints") or []) + [ends.get("target")])


# ---------------------------------------------------------------- 도면에 놓기(mm)
class Canvas:
    """원래 좌표를 도면 mm로 옮긴다. sheet가 None이면(크기를 모르는 DEXPI 도면) 도면 밖인지 보지 않는다."""

    def __init__(self, scale, sheet):
        self.scale, self.sheet = scale, sheet

    def xy(self, p):
        return (round(p[0] * self.scale["factor"] + self.scale["dx"], 3), round(p[1] * self.scale["factor"] + self.scale["dy"], 3))

    def holds(self, *pts):
        return self.sheet is None or all(0.0 <= x <= self.sheet[0] and 0.0 <= y <= self.sheet[1] for x, y in pts)

    def place(self, p):
        x, y = self.xy((p.x, p.y))
        f = self.scale["factor"]
        out = Placement(x, y, round(p.scale_x * f, 6), round(p.scale_y * f, 6), dexpi_shape.angle(p.rotation, 6), p.mirrored)
        box = dexpi_shape.placed(dexpi_shape.UNIT, out)
        if box is None:
            raise Undrawable("zero_size")
        if not self.holds(box[:2], (box[0] + box[2], box[1] + box[3])):
            raise Undrawable("off_sheet")
        return out

    def path(self, pts):
        out = [self.xy(p) for p in pts]
        if len(set(out)) < 2:
            raise Undrawable("one_point")
        if not self.holds(*out):
            raise Undrawable("off_sheet")
        return out


# ---------------------------------------------------------------- 그림 한 장
class Picture:
    """그릴 것을 모은 뒤(symbol·line·text) write로 XML에 쓴다. 모은 값은 되읽기 검사(problems)의 기준이기도 하다."""

    def __init__(self, extraction, canvas):
        self.canvas, self.known = canvas, extraction is not None
        ex = extraction or {}
        self.format = (ex.get("source") or {}).get("format")
        self.nodes = {n["local_id"]: n for n in ex.get("nodes") or []}
        self.relations = {r["local_id"]: r for r in ex.get("relations") or []}
        self.locations = {loc["local_id"]: loc for loc in ex.get("source_locations") or []}
        self.free_texts = [{"text": dx.clean_text(t["text"]), "bbox": _plain(t.get("bbox") or [(t.get("geometry") or {}).get(k) for k in BOX_KEYS])}
                           for t in ex.get("texts") or [] if isinstance(t, dict) and t.get("text") and not t.get("owner")]
        self.symbols = {}  # DEXPI id -> (모양 이름, Placement)
        self.local = {}  # DEXPI id -> 추출 결과의 local_id(그린 기호와 선만)
        self.lines = {}  # DEXPI id -> ([(x, y) mm], 신호선인가)
        self.joins = {}  # DEXPI id -> ((구성요소 id, 배관 노드 id 또는 None), …) 선의 시작과 끝이 닿는 곳
        self.texts = {}  # DEXPI id -> [(글자, x, y)]
        self.not_drawn = []
        self.approximate = []  # 그렸으나 자리가 근사인 것

    def _skip(self, what, reason, ent, dexpi_id, **more):
        self.not_drawn.append(dict({"what": what, "reason": reason, "entity_id": ent.get("entity_id"), "local_id": ent.get("local_id"),
                                    "dexpi_id": dexpi_id}, **more))

    @staticmethod
    def _of(table, ent):
        """그래프의 대상에 맞는 추출 결과의 대상. 순번 local_id가 같아도 원본 객체가 다르면(그래프를 지은 추출 결과가 아님) None."""
        hit = table.get(ent["local_id"])
        return hit if hit is not None and hit.get("source_object_id") == ent.get("source_object_id") else None

    def _mark(self, what, ent, dexpi_id):
        self.approximate.append({"what": what, "entity_id": ent["entity_id"], "local_id": ent["local_id"], "dexpi_id": dexpi_id})

    def leave_symbol(self, ent, reason, dexpi_id=None):
        """그리지 않는 구성요소를 곁 파일에 적는다(자리를 알면 함께)."""
        node = self._of(self.nodes, ent)
        box = source_box(node, self.locations.get(ent["local_id"]), self.format) if node else None
        more = {"lines": label_lines(ent.get("label_text") or ent.get("tag"))} if ent.get("kind") == "continuation" else {}
        self._skip("symbol", reason, ent, dexpi_id, box=_plain(box), **more)

    def leave_line(self, what, ent, reason, dexpi_id=None):
        rel = self._of(self.relations, ent)
        self._skip(what, reason, ent, dexpi_id, points=raw_points(rel) if rel else None)

    def symbol(self, ent, dexpi_id, shape_name):
        """구성요소의 기호와 글자."""
        if not self.known:
            return
        node = self._of(self.nodes, ent)
        try:
            if node is None:
                raise Undrawable("no_box")
            p = self.canvas.place(source_placement(node, self.locations.get(ent["local_id"]), self.format))
        except Undrawable as why:
            self.leave_symbol(ent, str(why), dexpi_id)
            return
        self.symbols[dexpi_id], self.local[dexpi_id] = (shape_name, p), ent["local_id"]
        if is_approximate(node, self.locations.get(ent["local_id"]), self.format):
            self._mark("symbol", ent, dexpi_id)
        box = dexpi_shape.placed(dexpi_shape.UNIT, p)
        if ent["kind"] == "continuation":
            a = ent.get("attributes") or {}
            lines = label_lines(ent.get("label_text") or ent.get("tag")) or [x for x in (a.get("to_drawing"), a.get("to_object")) if x]
            at = (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0 - (len(lines) - 1) * 0.6 * TEXT_MM)
        else:
            lines = label_lines(ent.get("tag"))
            at = self._label_place(node) or (box[0] + box[2] / 2.0, box[1] + box[3] + TEXT_MM)
        for n, text in enumerate(lines):
            self.text(dexpi_id, text, (at[0], at[1] + n * 1.2 * TEXT_MM))

    def _label_place(self, node):
        b = (node.get("label_location") or {}).get("bbox")
        if not (isinstance(b, (list, tuple)) and len(b) == 4 and _ok(b)):
            return None
        at = self.canvas.xy((b[0] + b[2] / 2.0, b[1] + b[3] / 2.0))
        return at if self.canvas.holds(at) else None

    def text(self, dexpi_id, text, at):
        at, text = (round(at[0], 3), round(at[1], 3)), dx.clean_text(text)
        if text and self.canvas.holds(at):
            self.texts.setdefault(dexpi_id, []).append((text,) + at)

    def line(self, ent, dexpi_id, joins, first=None, backward=False, signal=False):
        """배관(backward면 거꾸로 쓴다)이나 신호선(first 구성요소의 끝에서 시작하게 쓴다)의 길."""
        if not self.known:
            return
        rel = self._of(self.relations, ent)
        try:
            if rel is None:
                raise Undrawable("end_unknown")
            pts = self.canvas.path(source_path(rel))
        except Undrawable as why:
            self.leave_line("signal" if signal else "line", ent, str(why), dexpi_id)
            return
        if "parent_offset_approx" in str((self.locations.get(ent["local_id"]) or {}).get("method")):
            self._mark("line", ent, dexpi_id)
        if signal:
            start = next((e.get("node_local_id") for e in rel["endpoints"] if e.get("end") == "source"), None)
            backward = start != first
        self.lines[dexpi_id], self.joins[dexpi_id] = (pts[::-1] if backward else pts, signal), joins
        self.local[dexpi_id] = ent["local_id"]

    def middle(self, dexpi_ids):
        """선들 가운데 가장 긴 것의 중점(글자 자리). 그린 선이 없으면 None."""
        best = None
        for oid in dexpi_ids:
            pts = self.lines.get(oid, ((), False))[0]
            size = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
            if pts and (best is None or size > best[0]):
                best = (size, pts)
        if best is None:
            return None
        left, pts = best[0] / 2.0, best[1]
        for a, b in zip(pts, pts[1:]):
            d = math.dist(a, b)
            if d and left <= d:
                return (a[0] + (b[0] - a[0]) * left / d, a[1] + (b[1] - a[1]) * left / d)
            left -= d
        return pts[-1]

    def node_positions(self, kept, centers):
        """배관 노드 id -> 자리(mm). 파일에 있던 자리(kept), 그린 배관의 끝, 구성요소의 가운데(centers) 차례로 정한다."""
        out = dict(kept)
        for oid, (pts, signal) in self.lines.items():
            for (_owner, nid), at in zip(self.joins[oid], (pts[0], pts[-1])) if not signal else ():
                out.setdefault(nid, at)
        for nid, at in centers:
            if _ok(at) and self.canvas.holds(at):
                out.setdefault(nid, at)
        return out

    def counts(self):
        return {"symbols": len(self.symbols), "lines": sum(1 for _p, s in self.lines.values() if not s),
                "signals": sum(1 for _p, s in self.lines.values() if s), "texts": sum(len(t) for t in self.texts.values()),
                "not_drawn": len(self.not_drawn), "approximate": len(self.approximate)}

    def sidecar(self):
        sheet = self.canvas.sheet
        return {"sheet": list(sheet) if sheet else None, "not_drawn": self.not_drawn, "approximate": self.approximate, "texts": self.free_texts}

    # ----- 되읽기 검사
    def problems(self, again):
        """곁 파일 없이 되읽은 추출 결과와 견준 문장 목록. 쓴 기호·선이 모두 같은 자리·방향으로 나와야 한다."""
        out = []
        nodes = {n["source_object_id"]: n for n in again["nodes"]}
        rels = {r["source_object_id"]: r for r in again["relations"]}
        for oid, (_name, p) in self.symbols.items():
            g = (nodes.get(oid) or {}).get("geometry") or {}
            want, shape = dexpi_shape.placed(dexpi_shape.UNIT, p), g.get("shape") or {}
            if not shape or any(abs(a - g[k]) > MATCH_MM for a, k in zip(want, BOX_KEYS)) or shape.get("mirrored") != p.mirrored \
                    or dexpi_shape.angle_gap(shape["rotation"], p.rotation) > MATCH_MM:
                out.append("기호 %s의 자리나 방향이 다름" % oid)
        for oid, (pts, _signal) in self.lines.items():
            r = rels.get(oid)
            got = [r["endpoints"][0]["point"]] + r["waypoints"] + [r["endpoints"][1]["point"]] if r else []
            # 신호선의 자리는 노드를 가리키지 않아 되읽을 때 시작과 끝이 바뀔 수 있다. 그려지는 선은 같다
            if not any(len(way) == len(pts) and all(math.dist(a, b) <= MATCH_MM for a, b in zip(way, pts)) for way in (got, got[::-1])):
                out.append("선 %s의 점이 다름" % oid)
        return out

    # ----- 쓰기
    def write(self, model, plant_id, name, ids, owners, positions):
        """owners: [(DEXPI id, 그 구성요소가 지닌 배관 노드 id들)], positions: 노드 id -> (x, y) mm(node_positions). 그릴 것이 없으면 쓰지 않는다."""
        if not positions and not self.symbols and not self.lines:
            return
        sheet = self.canvas.sheet or A3
        diagram = dx.obj(dx.components(model, "Diagram"), "Core/Diagram.Diagram")
        dx.color(diagram, "BackgroundColor", (255, 255, 255))
        for prop, v in (("MaxX", sheet[0]), ("MaxY", sheet[1]), ("MinX", 0.0), ("MinY", 0.0)):
            dx.number(diagram, prop, v)
        dx.value(diagram, "Name", "String", name)
        groups = dx.components(diagram, "Groups")
        border = dx.obj(dx.components(dx.obj(groups, "Core/Diagram.Border"), "Elements"), "Core/Diagram.PolyLine")
        dx.points(border, "Points", ((1.0, 1.0), (sheet[0] - 1.0, sheet[1] - 1.0)))
        dx.stroke(border, SHAPE_MM)
        shapes = {}
        for _oid, (shape, _p) in self.symbols.items():
            shapes.setdefault(shape, None)
        for shape in sorted(shapes):
            shapes[shape] = ids.take("Shape_" + shape, "Shape")
        marks = {}  # 구성요소 DEXPI id -> [(자리 id, 요소 종류, 노드 id 또는 None, (x, y))]
        node_mark = {}
        for oid, node_ids in owners:
            for nid in node_ids:
                if nid in positions:
                    pid = ids.take("Pos_" + (nid[3:] if nid.startswith("HZ_") else nid), "NodePosition")
                    node_mark[nid] = pid
                    marks.setdefault(oid, []).append((pid, "PipingNodePosition", nid, positions[nid]))
        ends = {}
        for oid, (pts, signal) in self.lines.items():
            ends[oid] = []
            for role, at, (owner, nid) in zip(("S", "T"), (pts[0], pts[-1]), self.joins[oid]):
                if nid in node_mark and math.dist(positions[nid], at) <= MATCH_MM:
                    ends[oid].append(node_mark[nid])
                    continue
                pid = ids.take("Pos_%s_%s" % (oid[3:] if oid.startswith("HZ_") else oid, role), "NodePosition")
                # 한 노드에 선이 둘 이상 닿아 자리가 다르면 노드를 가리키지 않는 자리를 선이 따로 갖는다
                marks.setdefault(owner if signal else oid, []).append((pid, "%sNodePosition" % ("Instrumentation" if signal else "Piping"), None, at))
                ends[oid].append(pid)
        for oid, _nodes in owners:
            if oid in marks or oid in self.symbols or oid in self.texts:
                self._group(groups, oid, marks.get(oid, ()), shapes)
        for oid in self.lines:
            self._group(groups, oid, marks.get(oid, ()), shapes, ends[oid])
        done = {oid for oid, _n in owners} | set(self.lines)
        for oid in self.texts:
            if oid not in done:
                self._group(groups, oid, (), shapes)
        dx.refs(diagram, "Represents", plant_id)
        if shapes:
            self._catalogue(model, shapes)

    def _group(self, groups, oid, marks, shapes, ends=None):
        group = dx.obj(groups, "Core/Diagram.RepresentationGroup")
        parts = None
        if oid in self.symbols or ends or oid in self.texts:
            parts = dx.components(group, "Groups")
        if oid in self.symbols:
            shape, p = self.symbols[oid]
            use = dx.obj(dx.components(dx.obj(parts, "Core/Diagram.Static"), "Elements"), "Core/Diagram.ShapeUsage")
            dx.value(use, "IsMirrored", "Boolean", "true" if p.mirrored else "false")
            dx.points(use, "Position", ((p.x, p.y),))
            for prop, v in (("Rotation", p.rotation), ("ScaleX", p.scale_x), ("ScaleY", p.scale_y)):
                dx.number(use, prop, v)
            dx.refs(use, "Shape", shapes[shape])
        if ends:
            pts, signal = self.lines[oid]
            line = dx.obj(dx.components(dx.obj(parts, "Core/Diagram.Static"), "Elements"), "Core/Diagram.ConnectorLine")
            if len(pts) > 2:
                dx.points(line, "InnerPoints", pts[1:-1])
            dx.refs(line, "Source", ends[0])
            dx.stroke(line, SIGNAL_MM if signal else PIPE_MM, "Dash" if signal else "Solid")
            dx.refs(line, "Target", ends[1])
        if oid in self.texts:
            elements = dx.components(dx.obj(parts, "Core/Diagram.Label"), "Elements")
            for text, x, y in self.texts[oid]:
                t = dx.obj(elements, "Core/Diagram.Text")
                dx.reference(t, "Alignment", "Core/Diagram.TextAlignment.CenterCenter")
                dx.color(t, "Color", (0, 0, 0))
                dx.value(t, "Font", "String", "Calibri")
                dx.points(t, "Position", ((x, y),))
                dx.number(t, "Rotation", 0.0)
                dx.number(t, "Size", TEXT_MM)
                dx.value(t, "Text", "String", text)
        if marks:
            comp = dx.components(group, "NodePositions")
            for pid, kind, nid, at in marks:
                mark = dx.obj(comp, "Plant/Diagram." + kind, pid)
                if nid:
                    dx.refs(mark, "Node", nid)
                dx.points(mark, "Position", (at,))
        dx.refs(group, "Represents", oid)

    @staticmethod
    def _catalogue(model, shapes):
        cat = dx.obj(dx.components(model, "ShapeCatalogues"), "Core/Diagram.ShapeCatalogue")
        dx.value(cat, "Name", "String", "Shapes")
        comp = dx.components(cat, "Shapes")
        u = dexpi_shape.UNIT
        for shape, sid in sorted(shapes.items()):
            o = dx.obj(comp, "Core/Diagram.Shape", sid)
            dx.value(o, "Name", "String", shape)
            box = dx.obj(dx.components(o, "Primitives"), "Core/Diagram.PolyLine")
            dx.points(box, "Points", ((u.x0, u.y0), (u.x1, u.y0), (u.x1, u.y1), (u.x0, u.y1), (u.x0, u.y0)))
            dx.stroke(box, SHAPE_MM)
            dx.value(o, "SymbolRegistrationNumber", "String", shape)
