"""검토구간 분할(C6)과 AI 없는 스크리닝(R0~R4). 근거: 기획서/검토구간-분할설계.md §3·§4.

그래프 하나를 받아 구간 목록을 돌려주는 순수 함수 `cut`과 그 결과 타입, 구성요소 몫 표, 점수만 연다.
저장 형식(JSON)은 모른다. 문서로 바꾸는 일은 hazop.study.nodes.propose가 맡는다.

cut 결과의 불변식(어기면 RuntimeError):
- 모든 구성요소가 정확히 한 구간(Kept 또는 Excluded)에 든다.
- R3 제외 묶음에는 편차원이 없다.
같은 그래프면 노드·간선 순서와 상관없이 같은 결과다. 집합은 늘 정렬해 돌고, 동점은 ID로 가른다.
"""

from __future__ import annotations

import enum
import math
from collections import Counter, deque
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, Union

ALGORITHM = "C6"
MAX_ACTIVE = 5
BUDGET = 40
MERGE_CAP = 60

PHYSICAL_EDGES = ("has_endpoint",)
INSTRUMENT_EDGES = ("measurement_connection", "signal_connection")
OTHER_NAME = "기타"


# ---------------------------------------------------------------- 구성요소의 몫(표 하나)

class Part(enum.Enum):
    VESSEL = "vessel"            # 용기류. 구간 경계
    MACHINE = "machine"          # 경계가 아닌 큰 기기(터빈·압축기, 표에 없는 기기)
    PUMP = "pump"
    FILTER = "filter"
    VALVE = "valve"
    INLINE = "inline"            # 오리피스·벤트 등
    INSTRUMENT = "instrument"    # 뼈대가 정해진 뒤 붙인다
    LINK = "link"                # 도면 연결점·도면 연결 구간
    PLAIN = "plain"              # 배관 구간·T·캡·미분류


@dataclass(frozen=True)
class Traits:
    boundary: bool      # 구간 경계(기기 하나가 구간 하나)
    weighted: bool      # 분할 가중 요소(구간당 MAX_ACTIVE개)
    source: bool        # 편차원(R1)
    points: int         # 점수 기여(§4.2)


TRAITS: Mapping[Part, Traits] = {
    Part.VESSEL: Traits(True, False, True, 3),
    Part.MACHINE: Traits(False, False, True, 3),
    Part.PUMP: Traits(False, True, True, 2),
    Part.FILTER: Traits(False, False, True, 1),
    Part.VALVE: Traits(False, True, True, 2),
    Part.INLINE: Traits(False, False, True, 1),
    Part.INSTRUMENT: Traits(False, False, True, 1),
    Part.LINK: Traits(False, False, False, 1),
    Part.PLAIN: Traits(False, False, False, 0),
}

# 기기 kind마다 몫. 지식그래프 레지스트리에 기기 kind가 늘면 tests/test_study_segment.py가 이 표에 없다고 실패한다.
EQUIPMENT_PART: Mapping[str, Part] = {
    "reactor_vessel": Part.VESSEL, "steam_generator": Part.VESSEL, "pressurizer": Part.VESSEL,
    "vessel": Part.VESSEL, "tank": Part.VESSEL, "heat_exchanger": Part.VESSEL, "condenser": Part.VESSEL,
    "demineralizer": Part.VESSEL, "accumulator": Part.VESSEL, "drum": Part.VESSEL, "column": Part.VESSEL,
    "pump": Part.PUMP, "filter": Part.FILTER,
    "turbine": Part.MACHINE, "compressor": Part.MACHINE, "fan": Part.MACHINE,
}


def part_of(node: Mapping) -> Part:
    category, kind = node.get("category"), node.get("kind") or ""
    if category == "instrument":
        return Part.INSTRUMENT
    if category == "valve":
        return Part.VALVE
    if "pump" in kind:  # 0.1.0 제안기의 is_active와 같은 부분 문자열 규칙
        return Part.PUMP
    if category == "equipment":
        return EQUIPMENT_PART.get(kind, Part.MACHINE)
    if category == "inline_component":
        return Part.INLINE
    if kind == "continuation" or node.get("sheet_link"):
        return Part.LINK
    return Part.PLAIN


def traits(node: Mapping) -> Traits:
    return TRAITS[part_of(node)]


# ---------------------------------------------------------------- 결과 타입

@dataclass(frozen=True)
class Piece:
    """분할이 낸 원래 조각. 스크리닝은 조각을 쪼개지 않고 통째로 붙이거나 묶는다."""
    pid: str                     # P1…: 한 제안 안에서만 뜻이 있고 구간 ID(S…)와 겹치지 않는다
    core: tuple[str, ...]        # 계기를 뺀 기본 구성요소. '기타' 조각만 빈 튜플
    members: tuple[str, ...]     # core + 붙은 계기
    name: str
    basis: str
    sheet: str


@dataclass(frozen=True)
class Absorbed:
    piece: Piece
    rule: Literal["R2", "R4"]


@dataclass(frozen=True)
class Kept:
    """남긴 구간. low는 R4(편차원 구간에 닿지만 크기 상한에 막힌 부속 배관 묶음)."""
    head: Piece
    absorbed: tuple[Absorbed, ...]
    low: bool
    score: int

    @property
    def members(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.head.members).union(*(a.piece.members for a in self.absorbed))))

    @property
    def status(self) -> str:
        return "low" if self.low else "keep"

    @property
    def grade(self) -> str | None:
        return grade(self.status, self.score)


@dataclass(frozen=True)
class Excluded:
    """도면·규칙마다 하나인 '스크리닝 제외' 묶음. 묶음도 구간이라 덮음률 100%가 유지된다."""
    sheet: str
    drawing: str
    rule: Literal["R0", "R3"]
    parts: tuple[Piece, ...]

    @property
    def members(self) -> tuple[str, ...]:
        return tuple(sorted(m for p in self.parts for m in p.members))


Segment = Union[Kept, Excluded]


# ---------------------------------------------------------------- 공개 함수

# 크기 조절(검토구간 규격 §7.1). 경계가 되는 몫·kind와 구성요소 예산·합치기 상한.
COARSE_VESSELS = frozenset({"reactor_vessel", "steam_generator", "pressurizer", "tank", "condenser"})
FINE_VALVE_WORDS = ("control", "relief", "safety")
GRANULARITY = {"coarse": (80, 120), "normal": (BUDGET, MERGE_CAP), "fine": (20, 30)}


@dataclass(frozen=True)
class Params:
    """cut의 매개변수. 기본값(granularity=None)은 0.1 제안기와 같은 규칙(용기류만 경계, 예산 40·상한 60)이다.
    granularity는 coarse·normal·fine(§7.1). extra_boundaries는 경계로 볼 구성요소, cut_at은 경로를 끊을 구성요소
    (그 구성요소를 경계로 둠 [추론: 끊는 자리를 혼자 남기는 것이 가장 단순한 끊기])."""
    granularity: str | None = None
    extra_boundaries: frozenset = frozenset()
    cut_at: frozenset = frozenset()

    def sizes(self):
        return GRANULARITY[self.granularity] if self.granularity else (BUDGET, MERGE_CAP)

    def is_boundary(self, node: Mapping, part: Part) -> bool:
        eid = node["entity_id"]
        if eid in self.extra_boundaries or eid in self.cut_at:
            return True
        g = self.granularity
        if g is None:
            return TRAITS[part].boundary
        kind = node.get("kind") or ""
        if g == "coarse":
            return part is Part.VESSEL and kind in COARSE_VESSELS
        if part is Part.VESSEL or kind in ("turbine", "compressor"):
            return True
        return g == "fine" and (part in (Part.PUMP, Part.FILTER) or (
            part is Part.VALVE and any(w in kind for w in FINE_VALVE_WORDS)))


def cut(graph: Mapping, exclude_sheets: Iterable[str] = (), params: Params | None = None) -> tuple[Segment, ...]:
    """그래프를 구간으로 나눈다. 순서: Kept(머리 조각 순, '기타'는 Kept 맨 뒤) → Excluded((도면, 규칙) 순).
    exclude_sheets는 사람이 '구간 분석에서 뺌'으로 표시한 도면 graph_id(R0). 그래프에 없는 ID는 무시한다.
    params(Params)를 주면 경계·예산을 바꾼다(AI 구간 도구 make_candidates의 크기 조절)."""
    ix = _index(graph, params or Params())
    pieces = _pieces(ix, _cores(ix))
    segs = _screen(ix, pieces, frozenset(exclude_sheets))
    _check(ix, segs)
    return segs


def score(nodes_by_id: Mapping[str, Mapping], members: Iterable[str]) -> int:
    """§4.2 점수. 판정에는 쓰지 않고 정렬·표시에만 쓴다. 그래프에 없는 구성요소는 0점."""
    return sum(traits(nodes_by_id[m]).points for m in members if m in nodes_by_id)


def grade(status: str, score_value: int | None) -> str | None:
    if status == "excluded" or score_value is None:
        return None
    if status == "low" or score_value == 0:
        return "낮음"
    return "주요" if score_value >= 3 else "일반"


def is_source(node: Mapping) -> bool:
    return traits(node).source


# ---------------------------------------------------------------- 안쪽

@dataclass(frozen=True)
class _Index:
    nodes: Mapping[str, Mapping]
    part: Mapping[str, Part]
    phys: Mapping[str, tuple[str, ...]]
    links: Mapping[str, tuple[str, ...]]
    sheet: Mapping[str, str]
    drawing: Mapping[str, str]
    bound: frozenset = frozenset()       # 경계 구성요소(Params.is_boundary)
    budget: int = BUDGET
    merge_cap: int = MERGE_CAP


def _adjacency(graph, kinds):
    ids = {n["entity_id"] for n in graph.get("nodes", [])}
    adj = {}
    for e in graph.get("edges", []):
        if e.get("kind") in kinds:
            a, b = e["nodes"]
            if a not in ids or b not in ids:  # 그래프에 없는 노드를 가리키는 간선은 연결로 보지 않는다
                continue
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    return {k: tuple(sorted(v)) for k, v in adj.items()}


def _index(graph, params=None):
    params = params or Params()
    nodes = {n["entity_id"]: n for n in graph.get("nodes", [])}
    gid = graph.get("graph_id") or ""
    drawing = {s["graph_id"]: s.get("drawing_number") or s["graph_id"] for s in graph.get("sheets") or []}
    drawing.setdefault(gid, (graph.get("source") or {}).get("drawing_number") or gid)
    part = {e: part_of(n) for e, n in nodes.items()}
    budget, cap = params.sizes()
    return _Index(nodes=nodes, part=part,
                  phys=_adjacency(graph, PHYSICAL_EDGES), links=_adjacency(graph, PHYSICAL_EDGES + INSTRUMENT_EDGES),
                  sheet={e: n.get("sheet") or gid for e, n in nodes.items()}, drawing=drawing,
                  bound=frozenset(e for e, n in nodes.items() if part[e] is not Part.INSTRUMENT
                                  and params.is_boundary(n, part[e])),
                  budget=budget, merge_cap=cap)


def _comps(ids, adj):
    seen, out = set(), []
    for s in sorted(ids):
        if s in seen:
            continue
        order, stack = [], [s]
        seen.add(s)
        while stack:
            cur = stack.pop()
            order.append(cur)
            for x in adj.get(cur, ()):
                if x in ids and x not in seen:
                    seen.add(x)
                    stack.append(x)
        out.append(sorted(order))
    return out


def _bfs(start, adj, allowed):
    order, seen, queue = [], {start}, deque([start])
    while queue:
        cur = queue.popleft()
        order.append(cur)
        for x in adj.get(cur, ()):
            if x not in seen and x in allowed:
                seen.add(x)
                queue.append(x)
    return order


def _walk(start, adj, allowed):
    """사슬(분기 없는 경로나 고리)을 한쪽으로 따라 걷는 순서. 고리에서 BFS 순서로 자르면 양쪽 끝이 섞여 끊긴다."""
    order, seen, cur = [start], {start}, start
    while True:
        nxt = [x for x in adj.get(cur, ()) if x in allowed and x not in seen]
        if not nxt:
            break
        cur = nxt[0]
        seen.add(cur)
        order.append(cur)
    order += [x for x in _bfs(start, adj, allowed) if x not in seen]  # 사슬이 아닌 입력에서도 빠뜨리지 않게
    return order


def _label(node):
    first_line = (node.get("label_text") or "").split("\n")[0].strip()
    return node.get("tag") or first_line or node.get("kind") or node["entity_id"]


def _path_name(core, ix):
    nodes = ix.nodes
    lines = sorted({nodes[e].get("line_no") for e in core if nodes[e].get("line_no")})
    names = lines or sorted({nodes[e]["tag"] for e in core if nodes[e].get("tag")}) or [core[0]]
    name = "배관 " + names[0] + (" 외 %d" % (len(names) - 1) if len(names) > 1 else "")
    bounds = sorted({_label(nodes[n]) for e in core for n in ix.phys.get(e, ()) if n in ix.bound})
    if bounds:
        name += " (%s)" % "·".join(bounds[:2] + (["외 %d" % (len(bounds) - 2)] if len(bounds) > 2 else []))
    return name


def _grow_by_active(comp, ix):
    """연결을 지키는 영역 키우기. 남은 것 중 최소 ID에서 출발해, 지금 영역에 닿고 분할 가중 요소 수가 넘지 않는
    후보 중 최소 ID를 하나씩 붙인다. BFS 순서로 자르면 배관이 끊긴 구간이 생겨서 이렇게 한다."""
    weighted = lambda e: int(TRAITS[ix.part[e]].weighted)  # noqa: E731
    left, out = set(comp), []
    while left:
        start = min(left)
        cur, cnt = {start}, weighted(start)
        left.discard(start)
        frontier = {x for x in ix.phys.get(start, ()) if x in left}
        while frontier:
            ok = sorted(x for x in frontier if cnt + weighted(x) <= MAX_ACTIVE)
            if not ok:
                break
            x = ok[0]
            cur.add(x)
            cnt += weighted(x)
            left.discard(x)
            frontier = (frontier | {y for y in ix.phys.get(x, ()) if y in left}) - cur
        out.append(sorted(cur))
    return out


def _split_big(core, ix):
    """계층 묶음: 분기점(경로 안 물리 차수 3 이상)을 뺀 사슬과 분기점 하나씩을 단위로 삼고(BUDGET을 넘는 사슬은
    끝점에서 BFS 순서로 BUDGET개씩), 단위 인접 그래프에서 지금 묶음에 닿는 단위만 BUDGET까지 붙인다."""
    phys = ix.phys
    cs = set(core)
    junction = {e for e in cs if sum(1 for x in phys.get(e, ()) if x in cs) >= 3}
    chains = []
    for c in _comps(cs - junction, phys) + [[j] for j in sorted(junction)]:
        if len(c) <= ix.budget:
            chains.append(c)
            continue
        cset = set(c)
        ends = [e for e in c if sum(1 for x in phys.get(e, ()) if x in cset) <= 1]
        order = _walk((ends or c)[0], phys, cset)
        chains += [order[k:k + ix.budget] for k in range(0, len(order), ix.budget)]
    owner = {e: i for i, c in enumerate(chains) for e in c}
    cadj = {i: set() for i in range(len(chains))}
    for e in cs:
        for x in phys.get(e, ()):
            if x in cs and owner[x] != owner[e]:
                cadj[owner[e]].add(owner[x])
    key = lambda i: chains[i][0]  # noqa: E731
    out, done = [], set()
    while len(done) < len(chains):
        start = min((i for i in range(len(chains)) if i not in done), key=key)
        cur, size = list(chains[start]), len(chains[start])
        done.add(start)
        frontier = cadj[start] - done
        while frontier:
            fit = sorted((j for j in frontier if size + len(chains[j]) <= ix.budget), key=key)
            if not fit:
                break
            j = fit[0]
            cur += chains[j]
            size += len(chains[j])
            done.add(j)
            frontier = (frontier | cadj[j]) - done
        out.append(sorted(cur))
    return out


def _cores(ix):
    """C6 기본 구성요소 묶음 → [(core, name, basis)]."""
    nodes, part = ix.nodes, ix.part
    out = []
    for eid in sorted(nodes):
        if eid in ix.bound:
            n = nodes[eid]
            what = "용기류 경계" if part[eid] is Part.VESSEL else "주요 장비 경계"
            out.append(((eid,), _label(n), "%s: %s(%s)" % (what, _label(n), n.get("kind") or "-")))
    path = {e for e in nodes if part[e] is not Part.INSTRUMENT and e not in ix.bound}
    for comp in _comps(path, ix.phys):
        chunks = []
        for c in _grow_by_active(comp, ix):
            chunks += [(c, "big")] if len(c) <= ix.budget else [(s, "budget") for s in _split_big(c, ix)]
        for i, (c, _how) in enumerate(chunks):
            weighted = sum(TRAITS[part[e]].weighted for e in c)
            name = _path_name(c, ix)
            if len(chunks) == 1:
                basis = "용기류 사이 배관 경로(분할 가중 요소 %d개)" % weighted
            else:
                name = "%s (%d/%d)" % (name, i + 1, len(chunks))
                basis = ("배관 경로를 분할 가중 요소 %d개·기본 구성요소 %d개 안에서 연결을 지키며 나눔 %d/%d(분할 가중 요소 %d개)"
                         % (MAX_ACTIVE, ix.budget, i + 1, len(chunks), weighted))
            out.append((tuple(c), name, basis))
    return out


def _instrument_target(eid, ix, group_of):
    """계측·신호(및 물리) 연결을 계기끼리만 따라가며, 가장 가까운 홉의 비계기 요소 중 조각 번호가 가장 작은 것."""
    seen, layer = {eid}, [eid]
    while layer:
        found, nxt_layer = [], []
        for cur in layer:
            for nxt in ix.links.get(cur, ()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                if nxt in group_of:
                    found.append(group_of[nxt])
                elif ix.part[nxt] is Part.INSTRUMENT:
                    nxt_layer.append(nxt)
        if found:
            return min(found)
        layer = nxt_layer
    return None


def _position_target(eid, ix, groups):
    pos = ix.nodes[eid].get("position")
    if not pos:
        return None
    sheet = ix.nodes[eid].get("sheet")
    best = None
    for i, (core, _members) in enumerate(groups):
        for m in core:
            p = ix.nodes[m].get("position")
            if p and ix.nodes[m].get("sheet") == sheet:  # 위치는 같은 도면 안에서만 비교
                cand = (math.hypot(p[0] - pos[0], p[1] - pos[1]), i)
                best = cand if best is None or cand < best else best
    return None if best is None else best[1]


def _pieces(ix, cores):
    """계기 붙이기(0.1.0 제안기 4번 그대로): 계기끼리 이은 연결로 가장 가까운 조각 → 같은 도면에서 위치가 가장
    가까운 조각 → '기타' 조각(맨 뒤, core 없음). 조각은 core[0] 순으로 P1…을 붙인다."""
    cores = sorted(cores, key=lambda c: c[0][0])
    groups = [(c[0], list(c[0])) for c in cores]
    group_of = {}
    for i, (core, _m) in enumerate(groups):
        for e in core:
            group_of.setdefault(e, i)
    other = []
    for eid in sorted(e for e in ix.nodes if ix.part[e] is Part.INSTRUMENT):
        t = _instrument_target(eid, ix, group_of)
        if t is None:
            t = _position_target(eid, ix, groups)
        if t is None:
            other.append(eid)
        else:
            groups[t][1].append(eid)
    out = [Piece("P%d" % (i + 1), core, tuple(sorted(set(members))), name, basis, ix.sheet[core[0]])
           for i, ((core, members), (_c, name, basis)) in enumerate(zip(groups, cores))]
    by_sheet = {}
    for eid in other:  # 도면마다 따로 둔다(R0이 도면 단위로 판정하므로 여러 도면을 한 조각에 섞지 않음)
        by_sheet.setdefault(ix.sheet[eid], []).append(eid)
    for sheet, ids in sorted(by_sheet.items()):
        out.append(Piece("P%d" % (len(out) + 1), (), tuple(ids), OTHER_NAME, "연결·위치로 붙일 구간이 없는 계기", sheet))
    return out


def _upstream(ix, members, region):
    """조각 구성요소와 region 사이 물리 연결 중, 어느 쪽 배관에 적혀 있든 region 쪽에서 조각 쪽으로 흐르는 것의 수."""
    n = 0
    for m in members:
        for x in ix.phys.get(m, ()):
            if x not in region:
                continue
            for pipe in (m, x):
                fd = ix.nodes[pipe].get("flow_direction")
                if isinstance(fd, dict) and ((pipe == x and fd.get("to") == m) or (pipe == m and fd.get("from") == x)):
                    n += 1
    return n


def _screen(ix, pieces, exclude_sheets):
    """R0~R4. 판정은 조각 단위이고 조각을 쪼개지 않는다.

    R0  조각 구성요소의 도면이 모두 exclude_sheets에 들면 제외(편차원이 있어도).
    R1  편차원이 하나도 없는 조각 = 부속 조각. R0이 아닌 나머지 = 주인.
    R2  겹마다 주인 영역에 닿는 부속 조각을 번호순으로, (상류 연결 수, 닿는 조각 수, 영역 크기는 큰 쪽, 주인 번호는
        작은 쪽) 첫째 주인에 붙인다. 붙인 뒤 크기가 MERGE_CAP을 넘는 주인은 건너뛴다. 붙은 조각도 다음 겹에서는
        주인 영역의 일부로 닿는다. 한 겹에서 아무도 못 붙으면 끝.
    R3  남은 부속 조각끼리 이은 덩어리가 주인 영역에 하나도 닿지 않으면 제외.
    R4  닿는 덩어리는 번호가 가장 작은 조각을 머리로, 닿는 조각을 번호순으로 MERGE_CAP까지 연결을 지키며 묶어 낮음.
    """
    n = len(pieces)
    piece_of = {}
    for i, p in enumerate(pieces):
        for m in p.members:
            piece_of.setdefault(m, i)
    nb = [set() for _ in range(n)]
    for i, p in enumerate(pieces):
        for m in p.members:
            for x in ix.phys.get(m, ()):
                j = piece_of.get(x)
                if j is not None and j != i:
                    nb[i].add(j)
    size = [len(p.members) for p in pieces]
    rule = [None] * n
    frag = set()
    for i, p in enumerate(pieces):
        # 도면을 잇는 배관 구간(sheet 없음)은 어느 도면에도 속하지 않으므로 판정에서 뺀다
        real = {ix.nodes[m]["sheet"] for m in p.members if ix.nodes[m].get("sheet")} or {ix.sheet[m] for m in p.members}
        if exclude_sheets and real <= exclude_sheets:
            rule[i] = "R0"
        elif not any(TRAITS[ix.part[m]].source for m in p.members):
            frag.add(i)
    owner = {i: i for i in range(n) if rule[i] is None and i not in frag}
    region = {o: set(pieces[o].members) for o in owner}
    absorbed = {o: [] for o in owner}
    while True:
        layer = sorted(i for i in frag if i not in owner and any(j in owner for j in nb[i]))
        progressed = False
        for i in layer:
            if i in owner:
                continue
            cands = Counter(owner[j] for j in nb[i] if j in owner)
            fits = [o for o in cands if size[o] + size[i] <= ix.merge_cap]
            if not fits:
                continue
            o = sorted(fits, key=lambda o: (-_upstream(ix, pieces[i].members, region[o]), -cands[o], -size[o], o))[0]
            owner[i] = o
            size[o] += size[i]
            region[o].update(pieces[i].members)
            absorbed[o].append((i, "R2"))
            progressed = True
        if not progressed:
            break
    low = set()
    seen = set()
    for i0 in sorted(i for i in frag if i not in owner):
        if i0 in seen:
            continue
        group, stack = [], [i0]
        seen.add(i0)
        while stack:
            i = stack.pop()
            group.append(i)
            for j in nb[i]:
                if j in frag and j not in owner and j not in seen:
                    seen.add(j)
                    stack.append(j)
        if not any(j in owner for i in group for j in nb[i]):
            for i in group:
                rule[i] = "R3"
            continue
        left = set(group)
        while left:
            head = min(left)
            left.discard(head)
            owner[head] = head
            low.add(head)
            absorbed[head] = []
            frontier = {j for j in nb[head] if j in left}
            while frontier:
                ok = sorted(j for j in frontier if size[head] + size[j] <= ix.merge_cap)
                if not ok:
                    break
                j = ok[0]
                left.discard(j)
                owner[j] = head
                size[head] += size[j]
                absorbed[head].append((j, "R4"))
                frontier = (frontier | {k for k in nb[j] if k in left}) - {j}
    kept = []
    for o in sorted(k for k, v in owner.items() if k == v):
        extra = tuple(Absorbed(pieces[j], r) for j, r in sorted(absorbed[o]))
        members = set(pieces[o].members).union(*(a.piece.members for a in extra))
        kept.append(Kept(pieces[o], extra, o in low, score(ix.nodes, members)))
    buckets = {}
    for i in range(n):
        if rule[i] in ("R0", "R3"):
            buckets.setdefault((pieces[i].sheet, rule[i]), []).append(pieces[i])
    excluded = [Excluded(sheet, ix.drawing.get(sheet, sheet), r, tuple(ps)) for (sheet, r), ps in sorted(buckets.items())]
    return tuple(kept) + tuple(excluded)


def _check(ix, segs):
    seen = Counter(m for s in segs for m in s.members)
    dup = sorted(m for m, c in seen.items() if c > 1)
    missing = sorted(set(ix.nodes) - set(seen))
    leaked = [m for s in segs if isinstance(s, Excluded) and s.rule == "R3" for m in s.members
              if TRAITS[ix.part[m]].source]
    broken = [s.head.pid for s in segs if isinstance(s, Kept) and not _connected(ix, s.members)]
    if dup or missing or leaked or broken:
        raise RuntimeError("검토구간 제안 불변식 위반: 중복 %d · 빠짐 %d · R3 제외에 든 편차원 %d · 끊긴 구간 %d"
                           % (len(dup), len(missing), len(leaked), len(broken)))


def _connected(ix, members):
    core = {m for m in members if ix.part[m] is not Part.INSTRUMENT}
    return len(core) <= 1 or len(_comps(core, ix.phys)) == 1
