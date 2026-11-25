"""정리된 보기를 DEXPI에서 그리기 위한 화면용 짓기·되읽기(HZ-PLN-22 §6.8). 화면 코드와 Qt를 import하지 않는다.

고친 추출 결과에서 DEXPI를 짓고(내보내기와 같은 쓰기 함수) 화면 곁 파일(`hazop_dexpi_screen/1`)과 함께 작업 루트 캐시에 둔다. 열 때는 DEXPI를
가져오기와 같은 코드로 되읽고 곁 파일의 다른 칸만 얹어, 정리된 보기(`sheet_items.build_items`·`clean_items.build`)가 읽는 추출 꼴로 되돌린다.
- 실선: DEXPI에서 읽은 그림. 점선: DEXPI에 실리지 못해 곁 파일에서 그리는 것. 실선은 '파일로 나가는 것'이고 '확정'이 아니다.
- 실선·점선·위치 없음의 id 집합이 지금 고친 추출의 id 집합과 같고 되돌린 값이 같을 때만 쓴다. 아니면 까닭 코드를 내고 지금 길로 그리게 한다.
- 캐시는 지워도 다시 짓는다. 추출 결과·사람 수정·확정 기록·내보내기 폴더를 건드리지 않는다.
"""

import collections
import hashlib
import json
import logging
import math
import os

from hazop import paths, store_io
from hazop.export import dexpi_diagram, dexpi_export
from hazop.extract.adapters import dexpi_import
from hazop.graph import build as graph_build

LOG = logging.getLogger("hazop.export.dexpi_screen")
SCHEMA = "hazop_dexpi_screen/1"
WRITER = "2"  # 짓는 규칙이 바뀌면 올린다(옛 캐시는 stale)
FORMATS = ("drawio", "dexpi")
KINDS = ("component", "pipe", "signal", "unresolved")
GROUPS = ("nodes", "relations", "unresolved")
CODES = {
    "format": "이 형식의 도면은 읽은 결과로 그립니다",
    "no_cache": "파일로 만든 그림이 아직 없습니다",
    "no_sidecar": "그림의 곁 파일이 없습니다",
    "unreadable": "파일로 만든 그림을 읽을 수 없습니다",
    "sidecar_mismatch": "그림과 곁 파일이 서로 맞지 않습니다",
    "stale": "도면이 바뀌어 그림을 다시 만들어야 합니다",
    "build_failed": "그림 파일을 만들지 못했습니다",
    "missing_part": "그림 파일에서 빠진 것이 있습니다",
    "extra_part": "그림 파일에 도면에 없는 것이 있습니다",
    "ledger": "그림에 있는 것과 도면에 있는 것이 다릅니다",
    "differs": "그림의 값이 도면과 다릅니다",
}
ORIENT_KEYS = ("rotation", "direction", "flipH", "flipV")
NODE_KEYS = ("source_object_id", "classification", "category", "kind", "tag", "label_text", "human_edit", "origin")
REL_KEYS = ("source_object_id", "kind", "line_type", "line_no", "label_text", "human_edit", "origin")

Screen = collections.namedtuple("Screen", "xml sidecar")


class Reject(Exception):
    """되읽은 그림을 쓰지 않는 까닭: CODES의 코드와 기록용 글."""

    def __init__(self, code, detail=None):
        Exception.__init__(self, code, detail)
        self.code, self.detail = code, detail


class View:
    """한 도면의 판정. ok이면 extraction이 정리된 보기에 넣을 추출 꼴이고, 아니면 None(지금 길로 그린다)."""

    def __init__(self, code=None, detail=None, extraction=None, sidecar=None):
        self.ok, self.code, self.detail, self.extraction = code is None, code, detail, extraction
        self.sidecar = sidecar if self.ok else None

    def verdict(self):
        """화면에 넘길 판정값(JSON). 키는 HZ-PLN-22 §6.8."""
        s = self.sidecar or {"dashed": {}, "unplaced": {}}
        ox, oy = _offset(s)
        dashed = [{"id": lid, "what": rec["what"], "reason": rec["reason"], "points": rec["points"] and [[x - ox, y - oy] for x, y in rec["points"]]}
                  for group in GROUPS for lid, rec in s["dashed"].get(group, {}).items()]
        unplaced = [{"id": lid, "what": rec["what"]} for group in GROUPS for lid, rec in s["unplaced"].get(group, {}).items()]
        return {"source": "dexpi" if self.ok else "extraction", "code": self.code, "why": CODES.get(self.code), "detail": self.detail,
                "ledger": s.get("ledger"), "dashed": dashed, "unplaced": unplaced}


# ---------------------------------------------------------------- 고친 추출 -> 그림에 쓰는 칸만
def _offset(sidecar):
    """추출 좌표에서 SVG 좌표로 가는 값(sheet_items._offset과 같은 규칙)."""
    align = ((sidecar.get("rest") or {}).get("coordinate_system") or {}).get("svg_alignment") or {}
    off = align.get("offset")
    return tuple(off) if isinstance(off, list) and len(off) == 2 and all(_num(v) for v in off) else (0.0, 0.0)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pair(p):
    """점 [x, y]. 꼴이 틀리면 None(sheet_items._pair와 같은 규칙)."""
    if isinstance(p, dict):
        p = [p.get("x"), p.get("y")]
    return list(p) if isinstance(p, (list, tuple)) and len(p) == 2 and all(_num(v) for v in p) else None


def _bbox4(b):
    return list(b) if isinstance(b, (list, tuple)) and len(b) == 4 and all(_num(v) for v in b) else None


def _node(n):
    out = {k: n.get(k) for k in NODE_KEYS}
    g = n.get("geometry") if isinstance(n.get("geometry"), dict) else {}
    shape = g.get("shape") if isinstance(g.get("shape"), dict) else {}
    out["box"] = _bbox4([g.get(k) for k in dexpi_diagram.BOX_KEYS])
    out["turn"] = [shape["rotation"], shape.get("mirrored", False)] if _num(shape.get("rotation")) else None
    out["label_box"] = _bbox4((n.get("label_location") or {}).get("bbox"))
    out["style"] = ";".join(p for p in str(n.get("style") or "").split(";") if p.partition("=")[0] in ORIENT_KEYS)
    return out


def _relation(r):
    out = {k: r.get(k) for k in REL_KEYS}
    out["ends"] = [{"end": e.get("end"), "node": e.get("node_local_id"), "status": e.get("status"), "point": _pair(e.get("point"))}
                   for e in r.get("endpoints") or [] if isinstance(e, dict)]
    out["way"] = [p for p in (_pair(w) for w in r.get("waypoints") or []) if p is not None]
    fd = r.get("flow_direction")
    out["flow"] = fd.get("from_end") if isinstance(fd, dict) else None
    return out


def _line(rec):
    """관계 -> 점 목록(sheet_items._points와 같은 차례)."""
    src = [e["point"] for e in rec["ends"] if e["point"] and e["end"] == "source"]
    dst = [e["point"] for e in rec["ends"] if e["point"] and e["end"] != "source"]
    return src + rec["way"] + dst


def _what(group, rec):
    if group == "nodes":
        return "component"
    if group == "unresolved":
        return "unresolved"
    return "pipe" if rec["kind"] == "physical_connection" else "signal"


def _placed(group, rec):
    if group == "nodes":
        return rec["box"] is not None or rec["label_box"] is not None
    return len(_line(rec)) >= 2


def slice_of(extraction):
    """정리된 보기가 읽는 칸만 모은 자료. {"nodes"|"relations"|"unresolved": {local_id: 값}, "rest": 쪽 전체 값}. JSON으로 한 번 돌려 파일에서
    읽은 값과 바로 견준다. 같은 local_id가 둘이면 셈을 할 수 없으므로 Reject."""
    out = {}
    for group, key, fn in (("nodes", "nodes", _node), ("relations", "relations", _relation), ("unresolved", "unresolved_connectors", _relation)):
        out[group] = {}
        for x in extraction.get(key) or []:
            if isinstance(x, dict) and isinstance(x.get("local_id"), str):
                if x["local_id"] in out[group]:
                    raise Reject("ledger", "같은 id가 둘: %s" % x["local_id"])
                out[group][x["local_id"]] = fn(x)
    d = extraction.get("drawing") or {}
    out["rest"] = {"source": {"format": (extraction.get("source") or {}).get("format")},
                   "drawing": {"page_width": d.get("page_width"), "page_height": d.get("page_height"),
                               "ignored_objects": len(d.get("ignored_objects") or [])},
                   "coordinate_system": extraction.get("coordinate_system"),
                   "texts": [{k: t.get(k) for k in ("text", "owner", "bbox")} for t in extraction.get("texts") or [] if isinstance(t, dict)],
                   "unclassified": [{k: c.get(k) for k in ("local_id", "source_object_id", "label_location", "bbox", "label_text")}
                                    for c in extraction.get("unclassified") or [] if isinstance(c, dict)],
                   "unknowns": (extraction.get("validation") or {}).get("unknowns") or []}
    return json.loads(json.dumps(out, ensure_ascii=False))


def key_of(piece, ver=None, symbols=None):
    """캐시 열쇠. ver: 화면의 판(sheet_refresh.ver_of), symbols: 기호 그림의 판(주는 쪽이 정하는 값). 둘이 없어도 내용 지문으로 바뀐 것을 안다."""
    data = json.dumps(piece, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"ver": ver, "symbols": symbols, "writer": [WRITER, dexpi_export.EXPORTER_VERSION, dexpi_import.SCRIPT_VERSION, dexpi_import.RULES_VERSION],
            "input_sha256": hashlib.sha256(data).hexdigest()}


# ---------------------------------------------------------------- 되읽기(DEXPI + 곁 파일 -> 고친 추출의 칸)
def _digits(factor):
    """되돌린 좌표를 어디까지 믿는가(원래 단위의 소수 자리). 파일의 좌표는 소수 셋째 자리라 줄인 배율만큼 흐려진다."""
    return 3 if factor >= 0.9 else max(0, int(math.floor(-math.log10(0.002 / factor) + 1e-9)))


def _reader(scale):
    d, f = _digits(scale["factor"]), scale["factor"]
    return lambda p: [round((p[0] - scale["dx"]) / f, d), round((p[1] - scale["dy"]) / f, d)]


def _read_nodes(again, ids, scale, fmt):
    """되읽은 기호 -> {local_id: _node 꼴}. 파일에 없는 칸은 비어 있다."""
    back, d, out = _reader(scale), _digits(scale["factor"]), {}
    for n in again["nodes"]:
        g, lid = n.get("geometry"), ids.get(n["source_object_id"])
        if lid is None or not g:
            continue
        rec = dict(_node(n), label_box=None, style="")
        a, b = back((g["x"], g["y"])), back((g["x"] + g["width"], g["y"] + g["height"]))
        rec["box"] = [a[0], a[1], round(b[0] - a[0], d), round(b[1] - a[1], d)]
        if fmt == "drawio":  # drawio는 방향을 스타일로 적는다(적지 않은 것과 0도를 가린다)
            rec["turn"] = None
        out[lid] = rec
    return out


def _read_lines(again, ids, node_ids, scale, reverse):
    """되읽은 선 -> {local_id: _relation 꼴}. reverse: 파일에 거꾸로 적힌 선의 local_id."""
    back, out = _reader(scale), {}
    local = {n["local_id"]: node_ids.get(n["source_object_id"]) for n in again["nodes"]}
    for r in again["relations"] + again["unresolved_connectors"]:
        lid = ids.get(r["source_object_id"])
        rec = _relation(r)
        if lid is None or len(_line(rec)) < 2:
            continue
        rec["human_edit"] = rec["origin"] = None
        path = [back(p) for p in _line(rec)]
        ends = [dict(e, node=local.get(e["node"])) for e in rec["ends"]]
        if lid in reverse:
            path = path[::-1]
            ends = [dict(ends[1], end="source"), dict(ends[0], end="target")]
            rec["flow"] = {"source": "target", "target": "source"}.get(rec["flow"])
        ends[0]["point"], ends[1]["point"] = path[0], path[-1]
        rec["ends"], rec["way"] = ends, path[1:-1]
        out[lid] = rec
    return out


def _apart(a, b):
    """좌표 목록 둘의 가장 큰 차이(한쪽이 없거나 개수가 다르면 무한)."""
    if a is None or b is None or len(a) != len(b):
        return 0.0 if a == b else math.inf
    return max([abs(x - y) for x, y in zip(a, b)] or [0.0])


def _flat(rec):
    return [v for p in _line(rec) for v in p]


def _bare(rec):
    """관계에서 점을 뺀 것(점은 따로 견준다)."""
    return dict({k: v for k, v in rec.items() if k != "way"}, ends=[{k: v for k, v in e.items() if k != "point"} for e in rec["ends"]])


def _differing(group, got, want):
    """다른 칸만 {칸: want의 값}. 지을 때는 곁 파일에 둘 것이고, 열 때는 비어 있어야 한다. 자리도 똑같아야 한다: 소수 둘째 자리의 차이가 정돈
    (clean_layout)의 묶음을 바꿔 그림이 수십 단위 달라질 수 있다."""
    if group == "nodes":
        return {k: v for k, v in want.items() if got[k] != v}
    g, w = _bare(got), _bare(want)
    out = {k: v for k, v in w.items() if g[k] != v}
    if _line(got) != _line(want):
        out["points"] = _line(want)
    return out


def _with_extra(group, got, extra):
    out = dict(got, **{k: v for k, v in extra.items() if k not in ("points", "reverse")})
    if group == "relations":
        path = extra.get("points") or _line(got)
        out["ends"] = [dict(e, point=path[0] if e["end"] == "source" else path[-1]) for e in out["ends"]]
        out["way"] = path[1:-1]
    return out


# ---------------------------------------------------------------- 짓기
def _regular(rec):
    """DEXPI의 선 하나로 되돌릴 수 있는 관계인가(시작과 끝이 하나씩, 둘 다 자리를 앎)."""
    return [e["end"] for e in rec["ends"]] in (["source", "target"], ["target", "source"]) and all(e["point"] for e in rec["ends"])


def build(extraction, name, ver=None, symbols=None):
    """고친 추출 -> Screen(DEXPI 바이트, 화면 곁 파일). 지을 수 없으면 예외. 추출 결과를 바꾸지 않는다."""
    piece = slice_of(extraction)
    graph = graph_build.build_graph(extraction)
    if not graph["source"].get("drawing_number"):  # 번호가 없어도 짓는다. 파일 안에만 쓰는 표시 이름
        graph["source"] = dict(graph["source"], drawing_number=paths.safe_name(name))
    export = dexpi_export.export_drawing(graph, extraction, require_confirmed_number=False, name=paths.safe_name(name))
    drawn, scale, fmt = export.drawn, export.sidecar["scale"], piece["rest"]["source"]["format"]
    again = dexpi_import.extract_bytes(export.xml, "screen.dexpi.xml")[0]
    symbols_of = {o: lid for o, lid in drawn["symbols"].items() if lid in piece["nodes"] and piece["nodes"][lid]["box"]}
    lines_of = {o: lid for o, lid in drawn["lines"].items() if lid in piece["relations"] and _regular(piece["relations"][lid])}
    ahead = _read_lines(again, lines_of, drawn["nodes"], scale, ())
    back = _read_lines(again, lines_of, drawn["nodes"], scale, set(lines_of.values()))
    solid = {"nodes": {lid: _differing("nodes", rec, piece["nodes"][lid]) for lid, rec in _read_nodes(again, symbols_of, scale, fmt).items()},
             "relations": {}}
    for lid, rec in ahead.items():
        want = piece["relations"][lid]
        if _apart(_flat(back[lid]), _flat(want)) < _apart(_flat(rec), _flat(want)):
            solid["relations"][lid] = dict(_differing("relations", back[lid], want), reverse=True)
        else:
            solid["relations"][lid] = _differing("relations", rec, want)
    why = _reasons(export, graph)
    dashed, unplaced = ({g: {} for g in GROUPS} for _ in range(2))
    for group in GROUPS:
        for lid, rec in piece[group].items():
            if lid in solid.get(group, ()):
                continue
            what = _what(group, rec)
            if _placed(group, rec):
                reason = "unresolved_connector" if group == "unresolved" else why.get(lid, "not_drawn")
                dashed[group][lid] = {"what": what, "reason": reason, "points": _line(rec) if group != "nodes" else None, "value": rec}
            else:
                unplaced[group][lid] = {"what": what, "value": rec}
    sidecar = {"schema": SCHEMA, "name": name, "key": key_of(piece, ver, symbols), "dexpi_sha256": hashlib.sha256(export.xml).hexdigest(), "scale": scale,
               "ids": {"nodes": drawn["nodes"], "symbols": symbols_of, "lines": lines_of}, "in_file": drawn["in_file"], "solid_extra": solid,
               "dashed": dashed, "unplaced": unplaced, "order": {g: list(piece[g]) for g in GROUPS}, "rest": piece["rest"]}
    sidecar["ledger"] = _ledger(sidecar, piece)
    return Screen(export.xml, json.loads(json.dumps(sidecar, ensure_ascii=False)))


def _reasons(export, graph):
    """DEXPI 그림에 없는 것의 까닭 {local_id: 코드}(내보내기의 뺀 목록과 그리지 않은 목록 그대로)."""
    local = {x["entity_id"]: x.get("local_id") for part in ("nodes", "edges") for x in graph[part] if x.get("entity_id")}
    out = {local.get(x["entity_id"]): x["reason"] for x in export.excluded["excluded_components"] + export.excluded["excluded_connections"]}
    for x in export.sidecar["picture"]["not_drawn"]:
        out.setdefault(x["local_id"], x["reason"])
    return out


# ---------------------------------------------------------------- 셈과 되읽기 검사
def _ledger(sidecar, piece):
    """종류마다 {total, solid, dashed, unplaced}. total은 고친 추출에서, 나머지는 곁 파일에서 센다. 세 무리의 id가 겹치거나 고친 추출의 id 집합과
    다르면 Reject."""
    out = {k: {"total": 0, "solid": 0, "dashed": 0, "unplaced": 0} for k in KINDS}
    for group in GROUPS:
        for rec in piece[group].values():
            out[_what(group, rec)]["total"] += 1
        bins = {"solid": set(sidecar["solid_extra"].get(group, {})), "dashed": set(sidecar["dashed"][group]), "unplaced": set(sidecar["unplaced"][group])}
        seen = [lid for b in bins.values() for lid in b]
        twice = sorted(lid for lid, n in collections.Counter(seen).items() if n > 1)
        lost, more = sorted(set(piece[group]) - set(seen)), sorted(set(seen) - set(piece[group]))
        if twice or lost or more or sidecar["order"][group] != list(piece[group]):
            raise Reject("ledger", "%s: 빠진 id %s, 남는 id %s, 겹친 id %s" % (group, lost[:5], more[:5], twice[:5]))
        for where, ids in bins.items():
            for lid in ids:
                out[_what(group, piece[group][lid])][where] += 1
    return out


def check(screen, extraction, ver=None, symbols=None):
    """캐시의 Screen과 지금 고친 추출 -> 되돌린 추출 꼴. 하나라도 어긋나면 Reject."""
    s = screen.sidecar
    if s.get("schema") != SCHEMA:
        raise Reject("stale", "곁 파일 판 %r" % s.get("schema"))
    piece = slice_of(extraction)
    if s.get("key") != key_of(piece, ver, symbols):
        raise Reject("stale", "열쇠가 다름")
    if s.get("failed"):
        raise Reject("build_failed", s["failed"])
    if screen.xml is None:
        raise Reject("no_cache", "그림 파일이 없음")
    if hashlib.sha256(screen.xml).hexdigest() != s.get("dexpi_sha256"):
        raise Reject("sidecar_mismatch", "dexpi_sha256")
    again = dexpi_import.extract_bytes(screen.xml, "screen.dexpi.xml")[0]
    have = {"nodes": [n["source_object_id"] for n in again["nodes"]],
            "relations": [r["source_object_id"] for r in again["relations"] + again["unresolved_connectors"]]}
    for group, ids in have.items():
        lost, more = set(s["in_file"][group]) - set(ids), set(ids) - set(s["in_file"][group])
        if lost or more or len(ids) != len(set(ids)):
            raise Reject("missing_part" if lost else "extra_part", "%s %s" % (group, sorted(lost or more)[:5]))
    ledger = _ledger(s, piece)
    if ledger != s.get("ledger"):
        raise Reject("ledger", "셈이 적힌 값과 다름")
    ids, extra = s["ids"], s["solid_extra"]
    got = {"nodes": _read_nodes(again, ids["symbols"], s["scale"], s["rest"]["source"]["format"]),
           "relations": _read_lines(again, ids["lines"], ids["nodes"], s["scale"], {lid for lid, e in extra["relations"].items() if e.get("reverse")})}
    values = {}
    for group in GROUPS:
        if group in got and set(got[group]) != set(extra[group]):
            raise Reject("missing_part", "%s %s" % (group, sorted(set(got[group]) ^ set(extra[group]))[:5]))
        values[group] = {}
        for lid, want in piece[group].items():
            if lid in extra.get(group, {}):
                v = _with_extra(group, got[group][lid], extra[group][lid])
            else:
                v = (s["dashed"][group].get(lid) or s["unplaced"][group][lid])["value"]
            bad = sorted(_differing(group, v, want))
            if bad:
                raise Reject("differs", "%s %s: %s" % (group, lid, ", ".join(bad)))
            values[group][lid] = v
    if s["rest"] != piece["rest"]:
        raise Reject("differs", "rest")
    return _extraction(values, s["rest"])


def _extraction(values, rest):
    """되돌린 값 -> sheet_items·clean_items가 읽는 추출 꼴."""
    nodes = []
    for lid, v in values["nodes"].items():
        n = dict({k: v[k] for k in NODE_KEYS}, local_id=lid, style=v["style"], geometry=None,
                 label_location={"bbox": v["label_box"]} if v["label_box"] else None)
        if v["box"]:
            n["geometry"] = dict(zip(dexpi_diagram.BOX_KEYS, v["box"]))
            if v["turn"]:
                n["geometry"]["shape"] = {"rotation": v["turn"][0], "mirrored": v["turn"][1]}
        nodes.append(n)

    def relation(lid, v):
        return dict({k: v[k] for k in REL_KEYS}, local_id=lid, waypoints=v["way"], flow_direction={"from_end": v["flow"]} if v["flow"] else None,
                    endpoints=[{"end": e["end"], "node_local_id": e["node"], "status": e["status"], "point": e["point"]} for e in v["ends"]])
    d = rest["drawing"]
    return {"source": rest["source"], "drawing": dict(d, ignored_objects=[None] * d["ignored_objects"]), "coordinate_system": rest["coordinate_system"],
            "nodes": nodes, "relations": [relation(*x) for x in values["relations"].items()],
            "unresolved_connectors": [relation(*x) for x in values["unresolved"].items()], "texts": rest["texts"], "unclassified": rest["unclassified"],
            "validation": {"unknowns": rest["unknowns"]}}


# ---------------------------------------------------------------- 캐시와 화면이 부르는 함수
def cache_paths(name):
    """(DEXPI, 곁 파일)의 자리. 작업 루트의 지워도 되는 캐시 아래. 이름의 지문을 붙여, 파일 이름으로 바꾸면 같아지는 두 도면이 서로 덮지 않게 한다."""
    mark = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    base = paths.folder("cache", "dexpi-screen", "%s-%s" % (paths.safe_name(name), mark))
    return base + ".dexpi.xml", base + ".screen.json"


def _store(name, xml, sidecar):
    """DEXPI를 먼저, 곁 파일을 나중에 쓴다(각각 임시 파일에 쓰고 바꿔 넣음). 사이에 끊기면 지문이 어긋나 쓰이지 않는다."""
    xml_path, side_path = cache_paths(name)
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)
    if xml is not None:
        store_io.write_bytes(xml_path, xml)
    store_io.write_json(side_path, sidecar)


def _load(name):
    xml_path, side_path = cache_paths(name)
    xml, side = store_io.read_bytes(xml_path)[0], store_io.read_bytes(side_path)[0]
    if side is None:
        raise Reject("no_cache" if xml is None else "no_sidecar")
    sidecar = json.loads(side.decode("utf-8"))
    if sidecar.get("name") != name:  # 파일 이름으로 바꾸며 같아진 다른 도면의 캐시
        raise Reject("stale", "다른 도면의 캐시")
    return Screen(xml, sidecar)


def _gate(extraction):
    fmt = (extraction.get("source") or {}).get("format")
    if fmt not in FORMATS:
        raise Reject("format", fmt)


def open_view(name, extraction, ver=None, symbols=None):
    """지어 둔 그림을 검사해 View로. 짓지 않고 쓰지 않으며 예외를 올리지 않는다(무엇이 틀려도 지금 길)."""
    try:
        _gate(extraction)
        screen = _load(name)
        return View(extraction=check(screen, extraction, ver, symbols), sidecar=screen.sidecar)
    except Reject as why:
        return View(why.code, why.detail)
    except Exception as exc:  # noqa: BLE001 - 깨진 캐시가 정리 보기를 막지 않게 한다
        LOG.warning("DEXPI 그림을 읽지 못함(%s)", name, exc_info=True)
        return View("unreadable", "%s: %s" % (type(exc).__name__, exc))


def prepare(name, extraction, ver=None, symbols=None):
    """그림을 지어 캐시에 두고 바로 검사한 View. 같은 열쇠로 지은 것이 있으면 다시 짓지 않는다. 예외를 올리지 않는다.
    짓지 못하면 까닭을 캐시에 남겨, 자료가 그대로인 동안 다시 짓지 않는다."""
    now = open_view(name, extraction, ver, symbols)
    if now.ok or now.code in ("format", "build_failed"):
        return now
    try:
        try:
            xml, sidecar = build(extraction, name, ver, symbols)
        except Exception as exc:  # noqa: BLE001 - 짓기가 실패해도 지금 길은 그대로다
            detail = "%s: %s" % (type(exc).__name__, exc)
            if not isinstance(exc, (dexpi_export.ExportError, Reject)):
                LOG.warning("DEXPI 그림을 짓지 못함(%s)", name, exc_info=True)
            xml, sidecar = None, {"schema": SCHEMA, "name": name, "failed": detail[:500], "key": key_of(slice_of(extraction), ver, symbols)}
        _store(name, xml, sidecar)
    except Reject as why:
        return View(why.code, why.detail)
    except Exception as exc:  # noqa: BLE001 - 디스크에 쓰지 못함
        LOG.warning("DEXPI 그림을 캐시에 두지 못함(%s)", name, exc_info=True)
        return View("build_failed", "%s: %s" % (type(exc).__name__, exc))
    return open_view(name, extraction, ver, symbols)
