"""채팅 읽기 도구. Qt를 import하지 않는 순수 함수다. 규격: docs/specs/chat-panel.md §3.

- 모든 도구는 `fn(ctx: ChatContext, **args) -> dict`(결과 봉투)이고 `ctx`를 바꾸지 않는다.
- `REGISTRY`: 도구 이름 -> {fn, description, input_schema, tier}. 뒤 단위의 MCP 서버가 이것만 보고 도구를 내놓는다.
  `fn`은 인자 검사·오류 변환·크기 상한까지 한 번에 하므로 서버는 `REGISTRY[name]["fn"](ctx, **args)`만 부르면 된다.
- 도구가 받는 인자에 파일 경로는 없다. 정의에 없는 인자는 `bad_args`다.
- 결과 JSON 하나는 8,000자를 넘지 않는다. 목록은 `cursor`로 다음 쪽을 받고, 경로는 길면 요약으로 바꾼다.
- 같은 입력이면 같은 결과다(`GraphQuery`의 결정적 BFS, ID 오름차순).

문서·워크시트 도구(get_worksheet, search_documents, get_document)는 뒤 단위 C3가, 구간 도구 셋은 N3이 이어 붙인다.
앱에 여는 목록은 `hazop.chat.registry.REGISTRY`다(여기 `REGISTRY`를 복사해 시작한다).
"""

import json
import re
import secrets
from collections import Counter, deque

from hazop.graph import project
from hazop.graph.query import VALVE_POSITION_NOTE, GraphQuery
from hazop.kg.schema import REGISTRY as KG_REGISTRY

MAX_CHARS = 8000
LIST_MAX = 200  # 목록 도구의 쪽 상한(limit 최대)
CURSOR_TABLE_MAX = 200
ID_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")
UNCERTAIN_CAP = 50
STRING_CAP = 300
REASON_ORDER = ("unknown_symbol", "unknown_tag", "unresolved_connector", "unlinked_sheet", "direction_unknown",
                "valve_position_ignored")
FLOW_WORD = {"with_flow": "with", "against_flow": "against", "unknown": "unknown"}

REGISTRY = {}


class ToolError(Exception):
    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


# ---------------------------------------------------------------- 인자 검사

def _type_ok(spec, value):
    t = spec.get("type")
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    return True


def _path_like(value):
    """절대경로·드라이브 글자·역슬래시·'..' 조각. 도구는 파일을 열지 않으므로 이런 값은 찾아보지도 않고 거절한다."""
    return bool(re.match(r"^([A-Za-z]:|[\\/])", value) or "\\" in value or ".." in re.split(r"[\\/]", value))


def _check(spec, value, where):
    """JSON 스키마의 쓰는 부분만 검사한다. 틀리면 이유 문장, 맞으면 None."""
    if not _type_ok(spec, value):
        return "%s: %s 형식이어야 함" % (where, spec.get("type"))
    if isinstance(value, str):
        if len(value) < spec.get("minLength", 0):
            return "%s: 비어 있음" % where
        if len(value) > spec.get("maxLength", STRING_CAP):
            return "%s: %d자를 넘음" % (where, spec.get("maxLength", STRING_CAP))
        if any(ord(ch) < 32 for ch in value):
            return "%s: 제어 문자가 있음" % where
        if _path_like(value):
            return "%s: 경로처럼 생긴 값은 받지 않음(ID·태그·cursor는 이 프로젝트의 색인에서만 찾는다)" % where
        if spec.get("idLike") and not ID_RE.match(value):
            return "%s: ID 글자가 아님(영문·숫자와 _ . : / - 만, 200자까지)" % where
        if "pattern" in spec and not re.match(spec["pattern"], value):
            return "%s: 형식이 맞지 않음(%s)" % (where, spec.get("patternHint", spec["pattern"]))
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"] or "maximum" in spec and value > spec["maximum"]:
            return "%s: %s~%s 범위여야 함" % (where, spec.get("minimum"), spec.get("maximum"))
    if "enum" in spec and value not in spec["enum"]:
        return "%s: %s 중 하나여야 함" % (where, " | ".join(map(str, spec["enum"])))
    if isinstance(value, list):
        if len(value) > spec.get("maxItems", 50):
            return "%s: 항목이 %d개를 넘음" % (where, spec.get("maxItems", 50))
        for i, v in enumerate(value):
            bad = _check(spec.get("items") or {}, v, "%s[%d]" % (where, i))
            if bad:
                return bad
    if isinstance(value, dict) and "properties" in spec:
        return _check_object(spec, value, where)
    return None


def _check_object(spec, args, where):
    props = spec.get("properties") or {}
    for k in args:
        if k not in props:
            return "%s: 정의에 없는 인자 %r(이 도구가 받는 인자: %s)" % (where, k, ", ".join(sorted(props)) or "없음")
    for k in spec.get("required") or []:
        if k not in args or args[k] is None:
            return "%s: 필수 인자 %r가 없음" % (where, k)
    for k, v in args.items():
        if v is None and k not in (spec.get("required") or []):
            continue
        bad = _check(props[k], v, "%s.%s" % (where, k) if where != "인자" else k)
        if bad:
            return bad
    return None


# ---------------------------------------------------------------- 봉투

def _size(obj):
    return len(json.dumps(obj, ensure_ascii=False))  # 공백이 붙는 기본 모양으로 센다(서버가 어떻게 직렬화해도 상한 안)


def _envelope(data, total=None, returned=None, cursor=None, truncated=False, uncertain=(), sources=(), error=None, **extra):
    n = len(data) if isinstance(data, list) else 1
    env = {"ok": error is None, "data": data, "total": n if total is None else total,
           "returned": n if returned is None else returned, "cursor": cursor, "truncated": truncated,
           "uncertain": list(uncertain), "sources": list(sources), "error": error}
    env.update(extra)
    return env


def _error(code, message, **extra):
    err = {"code": code, "message": message}
    err.update(extra)
    return _envelope(None, total=0, returned=0, error=err)


def _argsig(args):
    return json.dumps({k: v for k, v in args.items() if k not in ("cursor", "limit")}, sort_keys=True, ensure_ascii=False)


def _offset(ctx, cursor, total):
    """cursor -> 다음 시작 위치. cursor는 서버가 낸 값만 쓴다: 표에 없거나 다른 도구·인자·판의 것이면 bad_args."""
    if cursor is None:
        return 0
    entry = ctx.cursors.get(cursor)
    bad = None
    if entry is None:
        bad = "서버가 낸 cursor가 아님(앞 결과의 cursor를 그대로 넣을 것)"
    elif entry["call"] != ctx._call:
        bad = "다른 도구나 다른 인자로 받은 cursor"
    elif entry["graph_version"] != ctx.pg["graph_version"]:
        bad = "도면이 바뀌어 쓸 수 없는 cursor(처음부터 다시 물을 것)"
    elif entry["pos"] > total:
        bad = "자리가 맞지 않는 cursor"
    if bad:
        raise ToolError("bad_args", "cursor: " + bad)
    return entry["pos"]


def _issue(ctx, pos):
    key = "c-" + secrets.token_hex(6)
    ctx.cursors[key] = {"call": ctx._call, "pos": pos, "graph_version": ctx.pg["graph_version"]}
    while len(ctx.cursors) > CURSOR_TABLE_MAX:
        ctx.cursors.pop(next(iter(ctx.cursors)))
    return key


def _paged(ctx, items, limit, cursor, build, sources=(), uncertain=(), **extra):
    """items[offset:offset+limit]를 build(조각) -> data로 싸서 봉투를 만든다. 8,000자를 넘으면 조각을 줄인다."""
    total = len(items)
    off = _offset(ctx, cursor, total)
    n = min(limit, total - off)
    while True:
        part = items[off:off + n]
        more = off + n < total
        env = _envelope(build(part), total=total, returned=len(part), cursor=None, truncated=more,
                        sources=sources, uncertain=uncertain, **extra)
        if _size(env) <= MAX_CHARS:
            if more:
                env["cursor"] = _issue(ctx, off + n)
            return env
        if n <= 1:  # 한 줄로도 넘으면 불확실한 곳 목록을 줄인다(전체 개수는 uncertain_total에 남는다)
            unc = env["uncertain"]
            env["uncertain_total"] = max(len(unc), env.get("uncertain_total", 0))
            while unc and _size(env) > MAX_CHARS:
                unc = unc[:len(unc) * 3 // 4]
                env["uncertain"] = unc
            if more:
                env["cursor"] = _issue(ctx, off + n)
            return env
        n = max(1, n * 4 // 5)


def _sources(idx, ids):
    sheets = sorted({idx.nodes[i]["sheet"] for i in ids if i in idx.nodes and idx.nodes[i].get("sheet")})
    return [{"kind": "drawing", "sheet": s} for s in sheets]


def _uncertain(ctx, ids, valves=False):
    """노드 ID들에 걸린 불확실한 곳. (앞 50개, 전체 개수)."""
    idx = ctx.index
    out = []
    for i in sorted(set(ids)):
        reasons = set(idx.uncertain.get(i, ()))
        if valves and (idx.nodes.get(i) or {}).get("category") == "valve":
            reasons.add("valve_position_ignored")
        out += [{"id": i, "reason": r} for r in reasons]
    out.sort(key=lambda u: (REASON_ORDER.index(u["reason"]), u["id"]))
    return out[:UNCERTAIN_CAP], len(out)


def _cap_note(total):
    return {"uncertain_total": total} if total > UNCERTAIN_CAP else {}


# ---------------------------------------------------------------- 공통 조회

def _describe(idx, nid_):
    n = idx.nodes[nid_]
    return {"id": nid_, "tag": n.get("tag"), "kind": n.get("kind"), "sheet": n.get("sheet")}


def _is_seg(n):
    return n["node_type"] == "pipe_segment"


def _candidates(idx, ids):
    return [_describe(idx, i) for i in sorted(ids)[:10]]


def _resolve(ctx, ref):
    """ID 또는 태그 -> 노드 ID. 하나로 정해지지 않으면 ToolError(not_found / ambiguous)."""
    idx = ctx.index
    if ref in idx.nodes:
        return ref
    hits = idx.by_tag.get(ref.lower(), [])
    objs = [h for h in hits if not _is_seg(idx.nodes[h])]
    hits = objs or hits
    if not hits:
        hits = idx.by_entity.get(ref, [])
    if not hits:
        raise ToolError("not_found", "대상을 찾을 수 없음: %r" % ref)
    if len(hits) > 1:
        raise ToolError("ambiguous", "%r가 %d곳에 있어 하나로 정할 수 없음. 후보의 id로 다시 물을 것" % (ref, len(hits)),
                        candidates=_candidates(idx, hits))
    return hits[0]


def _kind_match(node, kinds):
    k = node.get("kind")
    return any(k == w or KG_REGISTRY.is_a(k, w) for w in kinds)


def _wildcard(pattern):
    return re.compile("".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern) + r"\Z",
                      re.IGNORECASE | re.DOTALL)


def _hops(idx, start, radius, kind="all"):
    """start에서 객체 기준 radius걸음 안의 노드 ID 집합(배관 구간은 걸음에 세지 않는다)."""
    adj = idx.q.adjacency(kind)
    depth = {start: 0}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for nb, _e in adj[cur]:
            d = depth[cur] + (0 if _is_seg(idx.nodes[nb]) else 1)
            if nb not in depth and d <= radius:
                depth[nb] = d
                queue.append(nb)
    return depth


def _matcher(ctx, flt):
    """filter(§3.2) -> 노드 -> 맞는지. 인자가 가리키는 대상이 없으면 ToolError."""
    idx = ctx.index
    flt = flt or {}
    kinds, cats, sheets = flt.get("kinds"), flt.get("categories"), flt.get("sheets")
    tag = _wildcard(flt["tag"]) if flt.get("tag") else None
    line = flt["line_no"].upper() if flt.get("line_no") else None
    attrs = {k: str(v).lower() for k, v in (flt.get("attrs") or {}).items()}
    near = None
    if flt.get("near"):
        near = set(_hops(idx, _resolve(ctx, flt["near"]["id"]), flt["near"].get("radius", 3)))
    members = None
    if flt.get("in_node"):
        members = {m for ns in ctx.node_sets or [] for nd in (ns or {}).get("nodes") or []
                   if nd.get("node_id") == flt["in_node"] for m in nd.get("members") or []}
        if not members and not any(nd.get("node_id") == flt["in_node"] for ns in ctx.node_sets or []
                                   for nd in (ns or {}).get("nodes") or []):
            raise ToolError("not_found", "검토구간을 찾을 수 없음: %r" % flt["in_node"])
    want_unc = flt.get("uncertain")

    def match(n):
        eid = n["entity_id"]
        if kinds and not _kind_match(n, kinds):
            return False
        if cats and n.get("category") not in cats:
            return False
        if sheets and n.get("sheet") not in sheets:
            return False
        if tag and not (n.get("tag") and tag.match(str(n["tag"]))):
            return False
        if line and str(n.get("line_no") or "").upper() != line:
            return False
        if attrs and any(str((n.get("attributes") or {}).get(k, "")).lower() != v for k, v in attrs.items()):
            return False
        if near is not None and eid not in near:
            return False
        if members is not None and eid not in members:
            return False
        if want_unc is not None and bool(idx.uncertain.get(eid)) != want_unc:
            return False
        return True
    return match


# ---------------------------------------------------------------- 스키마 조각

_STR = {"type": "string", "minLength": 1, "idLike": True}  # ID 또는 태그(경로 아님)
FILTER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "kinds": {"type": "array", "items": _STR, "description": "종류(지식그래프 레지스트리 클래스). 상위 클래스(valve)를 주면 아래 종류를 모두 포함"},
        "categories": {"type": "array", "items": _STR},
        "tag": {"type": "string", "minLength": 1, "description": "* ? 만 쓰는 와일드카드(정규식 아님)"},
        "sheets": {"type": "array", "items": _STR, "description": "도면 graph_id"},
        "line_no": {"type": "string", "minLength": 1},
        "attrs": {"type": "object", "description": "속성 이름 -> 값(대소문자 무시)"},
        "uncertain": {"type": "boolean"},
        "in_node": {"type": "string", "minLength": 1, "idLike": True, "description": "검토구간 node_id"},
        "near": {"type": "object", "additionalProperties": False, "required": ["id"],
                 "properties": {"id": _STR, "radius": {"type": "integer", "minimum": 1, "maximum": 10}}},
    }}
CURSOR = {"type": "string", "pattern": r"^c-[0-9a-f]{12}$", "patternHint": "앞 결과의 cursor 값 그대로"}
LIMIT = {"type": "integer", "minimum": 1, "maximum": LIST_MAX}


def tool(name, description, properties, required=(), tier="min", returns=()):
    """returns: 이 도구가 돌려주는 ID 종류(component·node·cell·chunk·path_ref). 앱이 근거 ID를 종류별로 모을 때 쓴다."""
    """함수를 도구로 등록한다. 등록된 fn은 인자를 검사하고 오류를 봉투로 바꾼다."""
    schema = {"type": "object", "additionalProperties": False, "properties": properties, "required": list(required)}

    def deco(impl):
        def run(ctx, **args):
            try:
                bad = _check_object(schema, args, "인자")
                if bad:
                    raise ToolError("bad_args", bad)
                args = {k: v for k, v in args.items() if v is not None}
                ctx._call = (name, _argsig(args))
                env = impl(ctx, **args)
                if _size(env) > MAX_CHARS:
                    raise ToolError("too_large", "결과가 %d자를 넘어 줄일 수 없음. 조건을 좁혀 다시 물을 것" % MAX_CHARS)
                return env
            except ToolError as exc:
                return _error(exc.code, exc.message, **exc.extra)
            except Exception as exc:  # 도구 하나의 오류가 대화를 끊지 않게 한다
                return _error("internal", "%s: %s" % (type(exc).__name__, str(exc)[:200]))
        run.__name__ = name
        run.__doc__ = description
        REGISTRY[name] = {"name": name, "fn": run, "description": description, "input_schema": schema, "tier": tier,
                          "returns": tuple(returns)}
        return run
    return deco


def call(ctx, name, args=None):
    """이름으로 도구를 부른다. 없는 이름은 bad_args."""
    entry = REGISTRY.get(name)
    if entry is None:
        return _error("bad_args", "없는 도구: %r(쓸 수 있는 도구: %s)" % (name, ", ".join(sorted(REGISTRY))))
    if not isinstance(args, dict):
        args = {} if args is None else args
        if not isinstance(args, dict):
            return _error("bad_args", "인자는 객체여야 함")
    return entry["fn"](ctx, **args)


# ---------------------------------------------------------------- find / get_component

@tool("find", "태그·ID·글자 일부로 구성요소 후보를 찾는다. 없으면 빈 목록(오류 아님). 이 결과의 id를 다른 도구에 넣는다.",
      {"query": {"type": "string", "minLength": 1, "maxLength": 120}, "limit": LIMIT, "cursor": CURSOR},
      ["query"], returns=("component",))
def find(ctx, query, limit=10, cursor=None):
    idx = ctx.index
    low = query.lower()
    ranked = []
    wild = _wildcard(query) if ("*" in query or "?" in query) else None
    for n in ctx.pg["nodes"]:
        eid, tag = n["entity_id"], str(n.get("tag") or "")
        tl = tag.lower()
        if eid == query:
            how = ("id", 0)
        elif tag and tl == low:
            how = ("tag", 1)
        elif wild and tag and wild.match(tag):
            how = ("tag", 2)
        elif tag and tl.startswith(low):
            how = ("tag_prefix", 3)
        elif tag and low in tl:
            how = ("tag_part", 4)
        elif low in eid.lower() or (n.get("sheet_entity_id") or "").lower() == low:
            how = ("id", 5)
        elif low in str(n.get("label_text") or "").lower():
            how = ("label", 6)
        else:
            continue
        ranked.append((how[1], _is_seg(n), eid, how[0]))
    ranked.sort()
    items = [dict(_describe(idx, r[2]), match=r[3]) for r in ranked]
    return _paged(ctx, items, limit, cursor, lambda part: {"query": query, "matches": part},
                  sources=_sources(idx, [i["id"] for i in items[:limit]]))


def _knowledge(ctx, eid):
    """연결된 지식(설정값·조건). 지식그래프가 없으면 None. 20개까지."""
    if ctx.kg is None:
        return None
    try:
        from hazop.kg import context as kc
        view = ctx.index.kg_view(ctx)
        built, _too_large = kc.build_context(view, ctx.pg, [eid])
    except Exception:
        return None
    out = []
    for it in built.get("items") or []:
        row = {"knowledge_id": it["knowledge_id"], "node_type": it["node_type"], "source": it.get("source")}
        row.update({f: it[f] for f in kc.VALUE_FIELDS if it.get(f) is not None})
        out.append(row)
    return out


@tool("get_component", "구성요소 하나의 종류·태그·속성·도면·위치·연결 수·속한 검토구간·연결된 지식을 본다. id는 find 결과의 id나 태그.",
      {"id": _STR}, ["id"], returns=("component",))
def get_component(ctx, id):
    idx = ctx.index
    eid = _resolve(ctx, id)
    n = idx.nodes[eid]
    adj = idx.q.adjacency("all")[eid]
    d = {"id": eid, "tag": n.get("tag"), "kind": n.get("kind"), "category": n.get("category"),
         "classification": n.get("classification"), "label_text": n.get("label_text"),
         "sheet": n.get("sheet"), "drawing_number": idx.drawing_number.get(n.get("sheet")),
         "attributes": n.get("attributes") or {}, "bbox": n.get("bbox"), "position": n.get("position"),
         "connections": len(adj),
         "connections_by_kind": dict(sorted(Counter(idx.q.edges[e]["kind"] for _nb, e in adj).items())),
         "nodes": sorted(idx.node_of.get(eid, []))[:20], "node_count": len(idx.node_of.get(eid, []))}
    if _is_seg(n):
        d["line_no"] = n.get("line_no")
        d["flow_direction"] = n.get("flow_direction")
    know = _knowledge(ctx, eid)
    if know is not None:
        d["knowledge"] = know[:20]
        d["knowledge_count"] = len(know)
    unc = [{"id": eid, "reason": r} for r in sorted(idx.uncertain.get(eid, ()), key=REASON_ORDER.index)]
    src = _sources(idx, [eid]) + ([{"kind": "knowledge"}] if know else [])
    return _envelope(d, uncertain=unc, sources=src)


# ---------------------------------------------------------------- trace_path

BASES = ("ignoring_direction", "confirmed_flow")


def _raw_nodes(idx, raw, basis):
    """GraphQuery.path 결과 -> 원본 단계 [(id, flow)]. 배관 구간을 접지 않는다."""
    side = raw["ignoring_direction"] if basis == "ignoring_direction" else raw["confirmed_flow_direction"]
    if not side.get("found"):
        return None
    out = []
    steps = side["nodes"]
    for i, st in enumerate(steps):
        flow = FLOW_WORD.get(st.get("flow"))
        if basis == "confirmed_flow" and idx.nodes[st["entity_id"]]["node_type"] == "pipe_segment" and 0 < i < len(steps) - 1:
            flow = "with"
        out.append((st["entity_id"], flow if idx.nodes[st["entity_id"]]["node_type"] == "pipe_segment" else None))
    return out


def path_steps_raw(ctx, path_ref):
    """path_ref -> 원본 단계 [{id, kind, flow}](배관 구간 포함). 앱이 자기 프로세스에서 경고를 세려고 다시 돌린다(규격 §3.3).
    판이 바뀌었으면 ToolError(not_found), 경로가 없으면 빈 목록."""
    if not isinstance(path_ref, dict) or path_ref.get("basis") not in BASES or path_ref.get("mode") not in ("physical", "all"):
        raise ToolError("bad_args", "path_ref 형식이 올바르지 않음")
    if path_ref.get("graph_version") != ctx.pg["graph_version"]:
        raise ToolError("not_found", "도면이 바뀌어 경로를 다시 찾아야 함")
    for k in ("start", "end"):
        if not isinstance(path_ref.get(k), str) or path_ref[k] not in ctx.index.nodes:
            raise ToolError("not_found", "path_ref의 %s가 이 프로젝트에 없음" % k)
    idx = ctx.index
    nodes = _raw_nodes(idx, idx.q.path(path_ref["start"], path_ref["end"], path_ref["mode"]), path_ref["basis"]) or []
    return [{"id": i, "kind": idx.nodes[i]["kind"], "flow": f} for i, f in nodes]


def _step(idx, nid_, flow):
    n = idx.nodes[nid_]
    row = {"id": nid_, "tag": n.get("tag"), "kind": n.get("kind"), "sheet": n.get("sheet"), "flow": flow}
    if n["node_type"] == "pipe_segment" and n.get("sheet_link") and not n.get("sheet"):
        row["sheet_link"] = True
    return row


def _by_sheet(rows):
    order = []
    for r in rows:
        if r["sheet"] and r["kind"] != "pipe_segment":
            if not order or order[-1]["sheet"] != r["sheet"]:
                order.append({"sheet": r["sheet"], "count": 0})
            order[-1]["count"] += 1
    return order


@tool("trace_path", "두 구성요소 사이 배관 경로. 방향 무시 경로(path)와 확인된 흐름 방향만 따르는 경로(flow_path)를 따로 낸다. "
      "각 경로는 path_ref와 원본 단계 steps(도면 객체와 배관 구간 모두, 쪽으로 나눔), 배관 번호 요약 lines를 가진다. "
      "도면 간 연결 표기를 따라 여러 도면에 걸칠 수 있다(sheets, by_sheet). 답 카드에는 path_ref를 적는다. 밸브 정상 위치(NC 등)는 반영하지 않는다.",
      {"start": _STR, "end": _STR, "mode": {"type": "string", "enum": ["physical", "all"]}, "limit": LIMIT, "cursor": CURSOR},
      ["start", "end"], returns=("component", "path_ref"))
def trace_path(ctx, start, end, mode="physical", limit=200, cursor=None):
    idx = ctx.index
    a, b = _resolve(ctx, start), _resolve(ctx, end)
    raw = idx.q.path(a, b, mode)
    sides, all_ids = {}, []
    for key, basis in (("path", "ignoring_direction"), ("flow_path", "confirmed_flow")):
        nodes = _raw_nodes(idx, raw, basis)
        ref = {"start": a, "end": b, "mode": mode, "basis": basis, "graph_version": ctx.pg["graph_version"]}
        if nodes is None:
            sides[key] = {"found": False, "path_ref": ref, "steps": []}
            if basis == "confirmed_flow":
                sides[key]["reason"] = raw["confirmed_flow_direction"].get("reason")
            continue
        rows = [_step(idx, i, f) for i, f in nodes]
        all_ids += [i for i, _f in nodes]
        sides[key] = {"found": True, "length": len(nodes) - 1, "path_ref": ref, "steps": rows,
                      "lines": list(dict.fromkeys(r["tag"] or "" for r in rows if r["kind"] == "pipe_segment" and r["tag"])),
                      "segments_direction_unknown": [r["id"] for r in rows if r["flow"] == "unknown"][:50],
                      "segments_against_flow": [r["id"] for r in rows if r["flow"] == "against"][:50]}
    first = sides["path"] if sides["path"]["found"] else sides["flow_path"]
    unc, unc_total = _uncertain(ctx, all_ids, valves=True)
    count_ = max(len(sides["path"]["steps"]), len(sides["flow_path"]["steps"]))

    def build(part):
        lo, hi = (part[0], part[-1] + 1) if part else (0, 0)
        out = {}
        for key, side in sides.items():
            out[key] = dict(side, steps=side["steps"][lo:hi], step_count=len(side["steps"]))
        return {"from": _describe(idx, a), "to": _describe(idx, b), "mode": mode, "note": VALVE_POSITION_NOTE,
                "sheets": [x["sheet"] for x in _by_sheet(first["steps"])], "by_sheet": _by_sheet(first["steps"]),
                **out, **({"mode_note": raw.get("mode_note")} if mode == "all" else {})}
    return _paged(ctx, list(range(count_)), limit, cursor, build, sources=_sources(idx, all_ids), uncertain=unc,
                  **_cap_note(unc_total))


# ---------------------------------------------------------------- trace_flow

def _walk(idx, start, direction, stop_kinds, max_depth, include_unknown):
    """흐름 방향을 따라 도달 범위를 BFS로 찾는다. (도달 객체, 경계 객체, 깊이에 막힌 적 있는지)."""
    phys = idx.q.adjacency("physical")
    directed = idx.q.adjacency("directed")
    flow_adj = directed if direction == "down" else idx.reverse_directed()
    allowed = {u: {v for v, _e in lst} for u, lst in flow_adj.items()}
    seen = {start: (0, False)}
    queue = deque([start])
    reached, boundary, cut = [], [], False
    while queue:
        cur = queue.popleft()
        depth, unk = seen[cur]
        for nb, _e in phys[cur]:
            if nb in seen:
                continue
            seg = cur if _is_seg(idx.nodes[cur]) else nb
            via = False
            if nb in allowed.get(cur, ()):
                pass
            elif include_unknown and not idx.nodes[seg].get("flow_direction"):
                via = True
            else:
                continue
            nd = depth + (0 if _is_seg(idx.nodes[nb]) else 1)
            if nd > max_depth:
                cut = True
                continue
            seen[nb] = (nd, unk or via)
            if not _is_seg(idx.nodes[nb]):
                if stop_kinds and _kind_match(idx.nodes[nb], stop_kinds):
                    boundary.append(nb)
                    continue
                reached.append(nb)
            queue.append(nb)
    return reached, boundary, cut, seen


@tool("trace_flow", "시작 객체에서 확인된 흐름 방향으로 내려가(down)거나 거슬러 올라가(up) 닿는 객체. stop_kinds 종류에서 멈추고 그 객체는 boundary에 낸다. "
      "include_unknown이면 흐름 방향 미확인 배관도 건너가고 via_unknown=true를 단다. 깊이는 객체 걸음 수다.",
      {"start": _STR, "direction": {"type": "string", "enum": ["down", "up"]},
       "stop_kinds": {"type": "array", "items": _STR}, "max_depth": {"type": "integer", "minimum": 1, "maximum": 100},
       "include_unknown": {"type": "boolean"}, "limit": LIMIT, "cursor": CURSOR},
      ["start", "direction"], returns=("component",))
def trace_flow(ctx, start, direction, stop_kinds=(), max_depth=30, include_unknown=True, limit=50, cursor=None):
    idx = ctx.index
    s = _resolve(ctx, start)
    reached, boundary, cut, seen = _walk(idx, s, direction, list(stop_kinds), max_depth, include_unknown)
    items = [dict(_describe(idx, r), depth=seen[r][0], via_unknown=seen[r][1]) for r in reached]
    ids = [s] + reached + boundary
    seg_unknown = [i for i, (_d, v) in seen.items() if v and _is_seg(idx.nodes[i])]
    unc, unc_total = _uncertain(ctx, [s] + reached + boundary + seg_unknown, valves=True)
    return _paged(ctx, items, limit, cursor, lambda part: {
        "start": _describe(idx, s), "direction": direction, "reached": part,
        "boundary": [_describe(idx, b) for b in boundary[:30]], "boundary_count": len(boundary),
        "capped": cut, "max_depth": max_depth, "segments_direction_unknown": len(seg_unknown)},
        sources=_sources(idx, ids), uncertain=unc, **_cap_note(unc_total))


# ---------------------------------------------------------------- neighbors / count / summary

@tool("neighbors", "바로 이웃(direct)과 배관 구간 너머의 객체(via_segment, 흐름 관계 포함). 계측·신호 연결도 이웃이다.",
      {"id": _STR, "limit": LIMIT, "cursor": CURSOR}, ["id"], returns=("component",))
def neighbors(ctx, id, limit=50, cursor=None):
    idx = ctx.index
    eid = _resolve(ctx, id)
    raw = idx.q.neighbors(eid)
    rows = [("direct", {"edge": r["edge"], "edge_kind": r["edge_kind"], "neighbor": _describe(idx, r["neighbor"]["entity_id"])})
            for r in raw["direct"]]
    rows += [("via", {"via_segment": r["via_segment"], "node": _describe(idx, r["node"]["entity_id"]), "flow": r["flow"]})
             for r in raw["via_segment"]]
    ids = [eid] + [r[1]["neighbor"]["id"] if r[0] == "direct" else r[1]["node"]["id"] for r in rows]
    unc, unc_total = _uncertain(ctx, ids)
    return _paged(ctx, rows, limit, cursor, lambda part: {
        "target": _describe(idx, eid), "direct": [p for k, p in part if k == "direct"],
        "via_segment": [p for k, p in part if k == "via"]},
        sources=_sources(idx, ids), uncertain=unc, **_cap_note(unc_total))


GROUPS = ("kind", "category", "sheet", "line_no", "uncertain")


@tool("count", "조건(filter)에 맞는 객체 수를 묶음별로 센다. group_by: kind | category | sheet | line_no | uncertain. 도면 객체와 배관 구간을 모두 센다.",
      {"filter": FILTER_SCHEMA, "group_by": {"type": "string", "enum": list(GROUPS)}, "limit": LIMIT, "cursor": CURSOR},
      tier="min")
def count(ctx, filter=None, group_by="kind", limit=50, cursor=None):
    idx = ctx.index
    match = _matcher(ctx, filter)
    counts, matched = Counter(), 0

    def key(n):
        if group_by == "uncertain":
            return "uncertain" if idx.uncertain.get(n["entity_id"]) else "certain"
        v = n.get("line_no") if group_by == "line_no" else n.get(group_by)
        return v if v is not None else "(none)"
    for n in ctx.pg["nodes"]:
        if match(n):
            matched += 1
            counts[key(n)] += 1
    groups = [{"key": k, "count": c} for k, c in sorted(counts.items(), key=lambda kc: (-kc[1], str(kc[0])))]
    return _paged(ctx, groups, limit, cursor, lambda part: {"group_by": group_by, "matched": matched, "groups": part},
                  sources=[{"kind": "drawing", "sheet": s["graph_id"]} for s in ctx.pg["sheets"]][:20])


@tool("summary", "프로젝트 전체 현황: 도면 수, 도면 간 연결, 미확인·끊긴 곳의 수, 검토구간 수(고정 항목)와 종류별 개수(kinds, limit개씩 cursor로).",
      {"limit": LIMIT, "cursor": CURSOR})
def summary(ctx, limit=50, cursor=None):
    idx = ctx.index
    s = dict(idx.summary(ctx))
    unc = Counter(r for rs in idx.uncertain.values() for r in rs)
    kinds = sorted(Counter(n.get("kind") for n in ctx.pg["nodes"]).items(), key=lambda kv: str(kv[0]))
    s.update(nodes=len(ctx.pg["nodes"]), edges=len(ctx.pg["edges"]),
             uncertain={r: unc.get(r, 0) for r in REASON_ORDER if r != "valve_position_ignored"},
             sheet_list=[{"graph_id": x["graph_id"], "drawing_number": x.get("drawing_number")} for x in ctx.pg["sheets"]][:20],
             sheet_list_truncated=len(ctx.pg["sheets"]) > 20,
             node_sets=sum(len((ns or {}).get("nodes") or []) for ns in ctx.node_sets or []),
             knowledge_graph=ctx.kg is not None)
    return _paged(ctx, kinds, limit, cursor, lambda part: dict(s, kinds=dict(part)),
                  sources=[{"kind": "drawing", "sheet": x["graph_id"]} for x in ctx.pg["sheets"]][:20])


# ---------------------------------------------------------------- 두 번째 묶음: enclose / search / 검토구간

@tool("enclose", "start에서 물리 배관으로 이어진 범위를 stop_kinds 종류(예: 밸브)에서 멈추며 찾는다(격리 범위 질문용). "
      "범위 객체(objects)와 멈춘 경계 객체(boundary)를 같은 쪽 안에 함께 낸다. 범위가 max_size를 넘으면 거기서 멈추고 data.capped=true. "
      "밸브 정상 위치는 반영하지 않는다.",
      {"start": _STR, "stop_kinds": {"type": "array", "items": _STR}, "max_size": {"type": "integer", "minimum": 1, "maximum": 5000},
       "limit": LIMIT, "cursor": CURSOR}, ["start"], tier="more", returns=("component",))
def enclose(ctx, start, stop_kinds=(), max_size=5000, limit=50, cursor=None):
    idx = ctx.index
    s = _resolve(ctx, start)
    adj = idx.q.adjacency("physical")
    seen, queue, objects, boundary, capped = {s}, deque([s]), [], [], False
    if not _is_seg(idx.nodes[s]):
        objects.append(s)
    while queue and not capped:
        cur = queue.popleft()
        for nb, _e in adj[cur]:
            if nb in seen:
                continue
            seen.add(nb)
            n = idx.nodes[nb]
            if not _is_seg(n):
                if stop_kinds and _kind_match(n, stop_kinds):
                    boundary.append(nb)
                    continue
                if len(objects) >= max_size:
                    capped = True
                    break
                objects.append(nb)
            queue.append(nb)
    lines = sorted({idx.nodes[i].get("line_no") for i in seen if _is_seg(idx.nodes[i]) and idx.nodes[i].get("line_no")})
    rows = [("object", o) for o in objects] + [("boundary", b) for b in boundary]
    unc, unc_total = _uncertain(ctx, objects + boundary, valves=True)
    by_sheet = Counter(idx.nodes[o].get("sheet") for o in objects)
    return _paged(ctx, rows, limit, cursor, lambda part: {
        "start": _describe(idx, s), "stop_kinds": list(stop_kinds), "capped": capped, "complete": not capped,
        "size": len(objects), "boundary_count": len(boundary),
        "objects": [_describe(idx, i) for k, i in part if k == "object"],
        "boundary": [_describe(idx, i) for k, i in part if k == "boundary"],
        "line_numbers": lines[:60], "by_sheet": [{"sheet": k, "count": v} for k, v in sorted(by_sheet.items(), key=lambda kv: str(kv[0]))]},
        sources=_sources(idx, objects + boundary), uncertain=unc, **_cap_note(unc_total))


@tool("search", "조건(filter)에 맞는 객체 목록. 조건: kinds(상위 클래스 포함)·categories·tag(와일드카드)·sheets·line_no·attrs·uncertain·in_node·near. "
      "조건을 비우면 전부이므로 쪽 나누기(cursor)로 받는다.",
      {"filter": FILTER_SCHEMA, "limit": LIMIT, "cursor": CURSOR}, tier="more", returns=("component",))
def search(ctx, filter=None, limit=50, cursor=None):
    idx = ctx.index
    match = _matcher(ctx, filter)
    items = sorted((n["entity_id"] for n in ctx.pg["nodes"] if match(n)))
    rows = [dict(_describe(idx, i), category=idx.nodes[i].get("category")) for i in items]
    return _paged(ctx, rows, limit, cursor, lambda part: {"items": part},
                  sources=_sources(idx, items[:limit]))


def _all_nodes(ctx):
    return [nd for ns in ctx.node_sets or [] for nd in (ns or {}).get("nodes") or []]


def _node_row(idx, nd):
    members = nd.get("members") or []
    return {"node_id": nd.get("node_id"), "name": nd.get("name"), "state": nd.get("state") or nd.get("status"),
            "origin": nd.get("origin"), "rev": nd.get("rev"),
            "member_count": len(members),
            "sheets": sorted({idx.nodes[m]["sheet"] for m in members if m in idx.nodes and idx.nodes[m].get("sheet")})}


@tool("get_node", "검토구간 하나: 이름·설계 의도·구성요소(50개까지와 총수)·걸친 도면·상태(확정·잠금·origin).",
      {"node_id": _STR, "limit": LIMIT, "cursor": CURSOR}, ["node_id"], tier="more", returns=("node", "component"))
def get_node(ctx, node_id, limit=50, cursor=None):
    idx = ctx.index
    if not _all_nodes(ctx):
        raise ToolError("no_data", "검토구간이 아직 없음(④ 단계에서 만들거나 제안을 받을 것)")
    nd = next((x for x in _all_nodes(ctx) if x.get("node_id") == node_id), None)
    if nd is None:
        raise ToolError("not_found", "검토구간을 찾을 수 없음: %r" % node_id)
    members = [m for m in nd.get("members") or []]
    known = [m for m in members if m in idx.nodes]
    rows = [_describe(idx, m) for m in known]
    set_rev = next((ns.get("set_rev") for ns in ctx.node_sets or [] if nd in ((ns or {}).get("nodes") or [])), None)
    head = dict(_node_row(idx, nd), intent=nd.get("intent") or nd.get("design_intent"), locked=nd.get("locked"), set_rev=set_rev,
                unknown_members=len(members) - len(known))
    unc, unc_total = _uncertain(ctx, known)
    return _paged(ctx, rows, limit, cursor, lambda part: dict(head, members=part), sources=_sources(idx, known),
                  uncertain=unc, **_cap_note(unc_total))


@tool("list_nodes", "검토구간 목록. filter: sheet(도면 graph_id)·contains(이름 일부)·state·origin·batch_id.",
      {"filter": {"type": "object", "additionalProperties": False, "properties": {
          "sheet": _STR, "contains": {"type": "string", "minLength": 1}, "state": _STR, "origin": _STR, "batch_id": _STR}},
       "limit": LIMIT, "cursor": CURSOR}, tier="more", returns=("node",))
def list_nodes(ctx, filter=None, limit=50, cursor=None):
    idx = ctx.index
    flt = filter or {}
    rows = []
    for nd in _all_nodes(ctx):
        row = _node_row(idx, nd)
        if flt.get("sheet") and flt["sheet"] not in row["sheets"]:
            continue
        if flt.get("contains") and flt["contains"].lower() not in str(nd.get("name") or "").lower():
            continue
        if flt.get("state") and row["state"] != flt["state"]:
            continue
        if flt.get("batch_id") and nd.get("batch_id") != flt["batch_id"]:
            continue
        if flt.get("origin") and nd.get("origin") != flt["origin"]:
            continue
        rows.append(row)
    rows.sort(key=lambda r: str(r["node_id"]))
    return _paged(ctx, rows, limit, cursor, lambda part: {"items": part, "set_rev": next(
        (ns.get("set_rev") for ns in ctx.node_sets or [] if (ns or {}).get("set_rev") is not None), None)})
