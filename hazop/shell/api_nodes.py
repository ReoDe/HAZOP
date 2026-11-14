"""새 웹 화면의 구간 명령과 읽기(2단계, docs/design/app-shell-web.md §2.1·§5.2·§5.3). Qt를 import하지 않는다.

- **명령 `nodes.*`**: 웹이 보내는 것은 구간 ID·도면 안 local_id·이름·`set_rev`·대상의 `{node_id, rev, state}`뿐이다. 프로젝트 구성요소 ID로의
  변환(`hazop.chat.view.lift`)과 `by`(검토자 이름 = 설정)·`at`(시각)·`author`(`user`)는 여기서 채운다. 웹이 `by`·`at`·`author`·`origin`을
  보내면 인자 검사가 `bad_args`로 거절한다(채팅 규격 §4.7과 같은 규칙).
- 처리는 `hazop.study.node_commands.execute`가 한다(채팅의 쓰기와 같은 길). 판 검사(§5.3): `set_rev`는 엔진이, 대상 구간의 `rev`·`state`는
  여기서 대조한다. 엔진이 거절하면 아무것도 저장하지 않고 `reason`(한국어 문장)을 오류 글로 돌려준다.
- **읽기 `nodes`**(`ReadApi`가 부른다): `nodes`(목록·묶음), `nodes/sheet/<graph_id>`(도면 한 장의 구간별 local_id), `nodes/node/<node_id>`(상세).
- 영역 모듈이라 `api.py`는 `register(COMMANDS)` 한 줄로만 이 모듈을 부른다(§6 '파일 주인').
"""

import collections
import logging

from hazop.chat import view as chatview
from hazop.study import node_commands, node_tools, nodes

LOG = logging.getLogger("hazop.shell.api_nodes")
MEMBERS_SHOWN = 200        # 상세에 보이는 구성요소 수(나머지는 개수만)
BATCHES_SHOWN = 12         # 목록 머리에 보이는 최근 묶음
MAJORS_SHOWN = 8
MAX_IDS = 2000             # 한 번에 보내는 local_id 수(도면 고르기 상한과 같다)
INT_MAX = 10 ** 9


# ---------------------------------------------------------------- 엔진 접근

def _api():
    from hazop.shell import api
    return api


def _pg(engine, strict=True):
    """프로젝트 그래프. 만들 수 없으면 읽기는 None, 명령은 오류."""
    from hazop.app import project_ctx
    try:
        return project_ctx.project_graph(engine.project_id())
    except (OSError, ValueError, KeyError):
        if strict:
            raise _api().CommandError("failed", "프로젝트 그래프를 만들 수 없습니다. 도면을 먼저 추출하세요.")
        return None


def _peek(pg):
    """저장본을 읽기만 한다(파일을 바꾸지 않음, 규격 §5.2 '읽기 API는 읽기만'). (집합, 옛 판 여부).
    0.1 파일은 변환하지 않고 빈 집합과 legacy=True를 돌려준다: 변환은 사용자가 `nodes.migrate`를 눌러 한 번 한다."""
    try:
        doc = nodes.read_as_is(pg)
    except (OSError, ValueError) as exc:
        raise _api().CommandError("failed", "검토구간 파일을 읽을 수 없습니다(%s)." % str(exc)[:120])
    if doc is None:
        return nodes.new_set(pg), False
    if (doc.get("schema_version") or nodes.LEGACY_SCHEMA_VERSION) == nodes.LEGACY_SCHEMA_VERSION:
        return nodes.new_set(pg), True
    return doc, False


# ---------------------------------------------------------------- 읽기

def _by_sheet(pg, members):
    fwd, _ = chatview._locals(pg)
    out = collections.OrderedDict()
    for m in members:
        hit = fwd.get(m)
        if hit:
            out.setdefault(hit[0], []).append(hit[1])
    return out


def _owners(ns):
    """구성요소 -> 그것을 품은 구간 ID 목록."""
    owners = {}
    for n in ns["nodes"]:
        for m in n["members"]:
            owners.setdefault(m, []).append(n["node_id"])
    return owners


_SPAN_CACHE = {}


def _span_key(ns, pg):
    members = sum(len(n.get("members") or ()) for n in ns.get("nodes") or ())
    return (pg.get("project_id"), pg.get("graph_version"), ns.get("set_rev"), len(ns.get("nodes") or ()), members, tuple(n.get("rev") or 1 for n in ns.get("nodes") or ()))


def _span_info(ns, pg):
    """구간 도면 범위 표기. 525구간·구성요소 4만 개에서 계산이 약 1초라, 프로젝트 그래프 판·구간 집합 판이 같으면 지은 것을 그대로 준다(목록·상세가 매번 다시 짓지 않게)."""
    key = _span_key(ns, pg)
    hit = _SPAN_CACHE.get("v")
    if hit is not None and hit[0] == key:
        return hit[1]
    out = _span_info_build(ns, pg)
    _SPAN_CACHE["v"] = (key, out)
    return out


def _span_info_build(ns, pg):
    """구간마다 도면 범위 표기: {node_id: {range, drawings, spans, display_name, by_drawing, continuations}}. hazop.study.span.annotate가 만든 값을 그대로 쓴다
    (이전 화면이 쓰던 '[101 → 102]'와 같은 표기·같은 흐름 순서)."""
    from hazop.study import span
    out = {}
    try:
        ann = span.annotate(ns, pg)
    except Exception:  # noqa: BLE001 - 표기를 못 만들어도 구간 목록은 보인다(옛 '101 외 1장'). 까닭은 기록에 남긴다
        LOG.exception("구간 도면 범위 표기를 만들지 못함")
        return out
    for n in ann["nodes"]:
        short = n.get("drawings_short") or []
        out[n["node_id"]] = {
            "range": "[%s]" % " → ".join(short) if short else None, "drawings": short, "spans": bool(n.get("spans_drawings")),
            "display_name": n.get("display_name"), "by_drawing": n.get("members_by_drawing") or {}, "count": n.get("member_count") or 0,
            "continuations": [{"entity_id": c["entity_id"], "drawing": c.get("drawing"), "to_drawing": c.get("to_drawing"), "to_node_ids": c.get("to_node_ids") or [],
                               "chip": span.continuation_chip(n["node_id"], c)} for c in n.get("continuations") or []]}
    return out


def _row(n, fwd, owners, info=None, known=None):
    sheets = collections.OrderedDict()
    shared = collections.Counter()
    for m in n["members"]:
        hit = fwd.get(m)
        if hit:
            sheets[hit[0]] = sheets.get(hit[0], 0) + 1
        for other in owners.get(m, ()):
            if other != n["node_id"]:
                shared[other] += 1
    intent = n.get("design_intent") or None
    return {"node_id": n["node_id"], "name": n.get("name"), "state": nodes.node_state(n), "origin": n.get("origin"),
            "name_by": n.get("name_by"), "rev": n.get("rev") or 1, "basis": n.get("basis"), "batch_id": n.get("batch_id"),
            "design_intent": {"text": intent.get("text"), "by": intent.get("by")} if intent else None,
            "count": len(n["members"]), "sheets": [{"graph_id": g, "n": c} for g, c in sheets.items()],
            "overlaps": [{"node_id": o, "shared": c} for o, c in sorted(shared.items(), key=lambda kv: (-kv[1], kv[0]))],
            "confirmed": n.get("confirmed"), "locked": n.get("locked"),
            "screen": (n.get("screen") or {}).get("status"), "screen_reason": (n.get("screen") or {}).get("reason"),
            "screen_by": (n.get("screen") or {}).get("decided_by"), "screen_at": (n.get("screen") or {}).get("at"),
            "span": (info or {}).get(n["node_id"]),
            "broken": sum(1 for m in n["members"] if known is not None and m not in known)}      # 도면에서 지워진 구성원(도면 고치기·다시 추출 뒤 끊긴 참조)


def _batch_rows(ns):
    rows = []
    for b in reversed((ns.get("batches") or [])[-BATCHES_SHOWN:]):
        rows.append({"batch_id": b["batch_id"], "origin": b.get("origin"), "kind": b.get("kind"), "at": b.get("at"),
                     "request_text": b.get("request_text"), "undone": bool(b.get("undone")),
                     "ops": sorted({o["op"] for o in b.get("ops") or []}),
                     "node_ids": sorted({o["node_id"] for o in b.get("ops") or []}, key=lambda x: (len(x), x))})
    return rows


def summary(engine):
    """구간 목록 머리: 집합 판, 구간 행, 최근 묶음, 구간 밖 개수."""
    pg = _pg(engine, strict=False)
    if pg is None:
        return {"available": False, "set_rev": 0, "nodes": [], "batches": [], "outside": {"count": 0, "total": 0}, "stale": False,
                "read_only": None, "pending_ai": 0, "legacy": False, "ver": "0", "project_id": engine.project_id()}
    ns, legacy = _peek(pg)
    fwd, _ = chatview._locals(pg)
    owners = _owners(ns)
    info = _span_info(ns, pg)
    known = {x["entity_id"] for x in pg.get("nodes") or []}
    rows = [_row(n, fwd, owners, info, known) for n in ns["nodes"]]
    total = len(fwd)
    covered = sum(1 for m in fwd if m in owners)
    return {"available": True, "set_rev": ns.get("set_rev") or 0, "graph_version": ns.get("graph_version"),
            "stale": bool(ns["nodes"]) and nodes.is_stale(ns, pg), "read_only": ns.get("read_only"), "legacy": legacy, "project_id": engine.project_id(), "nodes": rows,
            "batches": _batch_rows(ns), "pending_ai": node_tools.pending_ai(ns),
            "outside": {"count": total - covered, "total": total}, "ver": str(ns.get("set_rev") or 0)}


def sheet_view(engine, graph_id):
    """도면 한 장 위의 구간: 구간마다 그 도면의 local_id, 어느 구간에도 속하지 않은 local_id."""
    pg = _pg(engine, strict=False)
    if pg is None:
        return None
    ns, _legacy = _peek(pg)
    fwd, _ = chatview._locals(pg)
    if not any(sh == graph_id for sh, _l in fwd.values()):
        return None          # 이 프로젝트에 없는 도면(경로 모양 글자 포함)은 404
    owners = _owners(ns)
    segments = []
    for n in ns["nodes"]:
        ids = _by_sheet(pg, n["members"]).get(graph_id)
        if ids:
            segments.append({"node_id": n["node_id"], "name": n.get("name"), "state": nodes.node_state(n), "ids": ids})
    outside = [local for ent, (sheet, local) in fwd.items() if sheet == graph_id and ent not in owners]
    return {"graph_id": graph_id, "set_rev": ns.get("set_rev") or 0, "segments": segments, "outside_ids": outside, "links": sheet_links(pg, graph_id, ns)}


def sheet_links(pg, graph_id, ns):
    """이 도면 위 다른 도면 연결(오각형) 목록: {id(도면 안 local_id), status, label(맞은편 도면 번호), peer_graph_id, peer_id(맞은편 local_id), reason, nodes(이 연결이 든 구간 ID)}.
    이어지지 않은 연결은 사유와 함께 싣는다(이전 화면의 '미연결' 표시와 같다)."""
    from hazop.graph import project
    fwd, _ = chatview._locals(pg)
    nums = {s["graph_id"]: s.get("drawing_number") for s in pg.get("sheets") or []}
    owners = _owners(ns)
    reasons = {}
    for l in pg.get("sheet_links") or []:
        if l.get("status") != "linked":
            for side in ("from", "to"):
                ref = l.get(side) or {}
                if ref.get("entity_id"):
                    reasons[project.nid(ref["graph_id"], ref["entity_id"])] = l.get("detail") or l.get("reason")
    out = []
    for n in pg.get("nodes") or []:
        if n.get("sheet") != graph_id or n.get("kind") != "continuation" or not n.get("local_id"):
            continue
        link = n.get("sheet_link") or {}
        peer = link.get("peer")
        hit = fwd.get(peer) if peer else None
        row = {"id": n["local_id"], "status": link.get("status") or "unlinked", "nodes": owners.get(n["entity_id"], [])}
        if link.get("status") == "linked" and hit:
            row.update(peer_graph_id=hit[0], peer_id=hit[1], label=nums.get(hit[0]) or hit[0].replace("graph-", "", 1))
        else:
            row["reason"] = reasons.get(n["entity_id"]) or link.get("reason")
        out.append(row)
    return sorted(out, key=lambda r: r["id"])


def _describe(pg):
    return {n["entity_id"]: n for n in pg.get("nodes") or []}


def detail(engine, node_id):
    """고른 구간의 상세: 행, 경계(주요 기기), 구성요소 앞 200개, 이 구간을 건드린 묶음."""
    pg = _pg(engine, strict=False)
    if pg is None:
        return None
    ns, _legacy = _peek(pg)
    node = node_tools._node(ns, node_id)
    if node is None:
        return None
    fwd, _ = chatview._locals(pg)
    owners = _owners(ns)
    info = _describe(pg)
    row = _row(node, fwd, owners, _span_info(ns, pg), {x["entity_id"] for x in pg.get("nodes") or []})
    majors, kinds = [], collections.Counter()
    for m in node["members"]:
        d = info.get(m) or {}
        kinds[d.get("kind") or "?"] += 1
        if d.get("category") == "equipment" and d.get("tag") and d["tag"] not in majors:
            majors.append(d["tag"])
    members = []
    for m in node["members"][:MEMBERS_SHOWN]:
        d, hit = info.get(m) or {}, fwd.get(m)
        if hit:
            members.append({"sheet": hit[0], "id": hit[1], "tag": d.get("tag"), "kind": d.get("kind"), "category": d.get("category"),
                            "shared": [o for o in owners.get(m, ()) if o != node_id]})
    history = [{"batch_id": b["batch_id"], "origin": b.get("origin"), "kind": b.get("kind"), "at": b.get("at"),
                "undone": bool(b.get("undone")), "ops": sorted({o["op"] for o in b["ops"] if o["node_id"] == node_id})}
               for b in ns.get("batches") or [] if any(o["node_id"] == node_id for o in b.get("ops") or [])]
    return dict(row, set_rev=ns.get("set_rev") or 0, majors=majors[:MAJORS_SHOWN], majors_total=len(majors),
                boundary=[majors[0], majors[-1]] if len(majors) >= 2 else majors[:1], kinds=dict(kinds.most_common(8)),
                members=members, members_total=len(node["members"]), history=history)


def suggest(engine, sheet, ids):
    """도면에서 고른 구성요소로 만들 구간의 카드 초안(저장하지 않음): 이름 제안, 경계, 겹치는 구간."""
    pg = _pg(engine)
    ns, _legacy = _peek(pg)
    members = list(dict.fromkeys(chatview.lift(pg, sheet, ids)))
    info = _describe(pg)
    majors = []
    for m in members:
        d = info.get(m) or {}
        if d.get("category") == "equipment" and d.get("tag") and d["tag"] not in majors:
            majors.append(d["tag"])
    if len(majors) >= 2:
        name = "%s → %s" % (majors[0], majors[-1])
    elif majors:
        name = "%s 주변" % majors[0]
    else:
        name = "%s 구간" % sheet.replace("graph-", "", 1)
    owners = _owners(ns)
    shared = collections.Counter(o for m in members for o in owners.get(m, ()))
    return {"count": len(members), "asked": len(ids), "name": name, "majors": majors[:MAJORS_SHOWN],
            "boundary": [majors[0], majors[-1]] if len(majors) >= 2 else majors[:1],
            "overlaps": [{"node_id": o, "shared": c} for o, c in sorted(shared.items(), key=lambda kv: (-kv[1], kv[0]))],
            "set_rev": ns.get("set_rev") or 0}


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'nodes'. 없는 자료는 None(404)."""
    api = _api()
    if len(parts) == 1:
        return api._json(summary(engine))
    if len(parts) == 3 and parts[1] == "sheet":
        data = sheet_view(engine, parts[2])
        return api._json(data) if data is not None else None
    if len(parts) == 3 and parts[1] == "node":
        data = detail(engine, parts[2])
        return api._json(data) if data is not None else None
    if len(parts) == 2 and parts[1] == "drawings":
        return api._json(drawings_view(engine))
    return None


def drawings_view(engine):
    """도면마다 구간 분석에서 뺐는지와 그 도면의 구성요소를 품은 구간. ver는 도면 빼기 표시 파일의 판(명령에 함께 보낸다)."""
    pg = _pg(engine, strict=False)
    if pg is None:
        return {"available": False, "drawings": [], "ver": "none", "problem": None}
    ns, _legacy = _peek(pg)
    pid = pg.get("project_id")
    ver = node_commands.excluded_ver(pid)
    try:
        marked = nodes.load_excluded(pid)
        problem = None
    except (OSError, ValueError) as exc:
        marked, problem = {}, "도면 빼기 표시를 읽지 못했습니다(%s)." % str(exc)[:120]
    keys = {nodes.drawing_key(k): v for k, v in marked.items()}
    sheets = pg.get("sheets") or [{"graph_id": pg.get("graph_id"), "drawing_number": (pg.get("source") or {}).get("drawing_number")}]
    rows = []
    for sh in sheets:
        mark = keys.get(nodes.drawing_key(sh.get("drawing_number"))) if sh.get("drawing_number") else None
        rows.append({"graph_id": sh["graph_id"], "drawing_number": sh.get("drawing_number"), "excluded": mark is not None,
                     "reason": (mark or {}).get("reason"), "by": (mark or {}).get("by"), "at": (mark or {}).get("at"),
                     "nodes": node_commands.drawing_nodes(pg, ns, sh["graph_id"]), "ver": ver})
    return {"available": True, "drawings": rows, "ver": ver, "problem": problem}


# ---------------------------------------------------------------- 쓰기

PROJECT_TEXT = "프로젝트가 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요."
STALE_TEXT = "구간이 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요."
SKIP_TEXT = "고른 것 가운데 %d개는 구성요소가 아닌 선(신호선·계측선)이라 뺐습니다."
EDIT_COMMANDS = ("add_members", "remove_members", "rename", "set_design_intent", "merge", "split", "remove")


def _error(out, ns, targets, name):
    """엔진의 거절을 오류 답으로(규격 §5.2 코드: bad_args·stale·locked·not_found·busy·failed). 갈래는 엔진의 거절 코드와 구간 상태로 정하고,
    글은 엔진이 쓴 한국어 사유를 그대로 잇는다(문구를 대조하지 않는다)."""
    reasons = out.get("refused") or [{"code": "rule", "reason": "처리하지 못했습니다."}]
    codes = {r.get("code") for r in reasons}
    text = " ".join(r["reason"] for r in reasons[:3])
    if codes & {"stale", "conflict"}:
        return _api().CommandError("stale", STALE_TEXT)
    if codes & {"unreadable", "read_only"}:
        return _api().CommandError("failed", text)
    if codes & {"bad_actor", "unknown_command"}:
        return _api().CommandError("bad_args", text)
    held = [t["node_id"] for t in targets if nodes.node_state(node_tools._node(ns, t["node_id"]) or {}) != "applied"]
    if name in EDIT_COMMANDS and held:
        return _api().CommandError("locked", text)
    return _api().CommandError("failed", text)


def _check_project(eng, a):
    """화면이 본 프로젝트가 지금 프로젝트와 같아야 쓴다(프로젝트를 바꾼 뒤 낡은 목록으로 다른 프로젝트의 구간을 쓰지 않게)."""
    if a["project_id"] != eng.project_id():
        raise _api().CommandError("stale", PROJECT_TEXT)


def _wanted(a):
    """명령이 건드리는 구간 ID."""
    return list(dict.fromkeys(([a["node_id"]] if a.get("node_id") else []) + list(a.get("node_ids") or [])))


def _check_targets(ns, a):
    """판 검사(§5.3): set_rev가 같고, 건드리는 구간마다 targets에 그 구간의 rev·state가 있고 저장본과 같아야 한다."""
    if a["set_rev"] != (ns.get("set_rev") or 0):
        raise _api().CommandError("stale", STALE_TEXT)
    given = {t["node_id"]: t for t in a.get("targets") or []}
    for nid in _wanted(a):
        t = given.get(nid)
        if t is None:
            raise _api().CommandError("bad_args", "%s 구간의 판(targets)을 함께 보내야 합니다." % nid)
        node = node_tools._node(ns, nid)
        if node is None:
            raise _api().CommandError("not_found", "%s 구간이 이미 없습니다." % nid)
        if (node.get("rev") or 1) != t["rev"] or nodes.node_state(node) != t["state"]:
            raise _api().CommandError("stale", "%s 구간이 다른 곳에서 바뀌어 저장하지 않았습니다." % nid)
    for t in given.values():
        if node_tools._node(ns, t["node_id"]) is None:
            raise _api().CommandError("not_found", "%s 구간이 이미 없습니다." % t["node_id"])


def _members(pg, a):
    """고른 local_id -> (프로젝트 구성요소 ID, 뺀 개수). 그래프의 구성요소가 아닌 선(신호선·계측선)은 빼고 그 개수를 돌려준다.
    하나도 남지 않으면 거절한다."""
    members = list(dict.fromkeys(chatview.lift(pg, a["sheet"], a["ids"])))
    if not members:
        raise _api().CommandError("bad_args", "고른 것 가운데 구간에 넣을 수 있는 구성요소가 없습니다(신호선·계측선은 넣지 않습니다).")
    return members, len(set(a["ids"])) - len(members)


def _judged(pg, ns, nid):
    from hazop.study import results as res
    try:
        doc, _fp = res.load_fp(ns)
    except (OSError, ValueError):
        return False
    return bool(doc) and node_tools.judged(doc, nid)


def _run(name, build):
    """build(pg, a) -> (node_commands 인자, 뺀 개수). 같은 길: 검토자 이름 확인 → 판 검사 → execute → 바뀜 알림."""
    def handler(eng, a):
        by = eng.reviewer()
        if not by:
            raise _api().CommandError("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 구간 기록에 남습니다.")
        _check_project(eng, a)
        pg = _pg(eng)
        ns, legacy = _peek(pg)
        if legacy:
            raise _api().CommandError("failed", "옛 판(0.1) 구간 파일입니다. 구간 패널의 '새 판으로 바꾸기'를 먼저 눌러 주세요.")
        _check_targets(ns, a)
        args, skipped = build(pg, a)
        if name == "remove" and not args.get("archive") and _judged(pg, ns, args["node_id"]):
            # 분석 칸에 판정이 있는 구간: 아무것도 저장하지 않고 '보관하고 지울지' 되묻는다(보관은 사람만 고르는 선택)
            return {"set_rev": ns.get("set_rev") or 0, "batch_id": None, "node_ids": [args["node_id"]], "needs_archive": True, "skipped": 0}
        out = node_commands.execute(pg, name, args, author="user", confirmed_by=by, set_rev=a["set_rev"])
        if out.get("needs_confirm"):   # 아무것도 저장하지 않았다. 화면이 이 글을 보이고 사람이 누르면 confirm으로 다시 보낸다
            return {"set_rev": ns.get("set_rev") or 0, "batch_id": None, "node_ids": out["node_ids"], "needs_confirm": out["needs_confirm"],
                    "skipped": 0}
        if not out["ok"]:
            raise _error(out, ns, a.get("targets") or [], name)
        after, _ = _peek(pg)
        changed = (after.get("batch_seq") or 0) != (ns.get("batch_seq") or 0)
        eng.changed("nodes", out["set_rev"])
        data = {"set_rev": out["set_rev"], "batch_id": out["batch_id"] if changed else None, "node_ids": out["node_ids"], "skipped": skipped}
        if skipped:
            data["skipped_text"] = SKIP_TEXT % skipped
        return data
    return handler


def _exclude_drawing(eng, a):
    by = eng.reviewer()
    if not by:
        raise _api().CommandError("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 도면 빼기 기록에 남습니다.")
    _check_project(eng, a)
    pg = _pg(eng)
    out = node_commands.exclude_drawing(pg, a["graph_id"], a["excluded"], by=by, reason=a.get("reason"), ver=a["ver"],
                                        confirm=a.get("confirm"))
    if out.get("needs_confirm"):
        return {"needs_confirm": out["needs_confirm"], "ver": a["ver"]}
    if not out["ok"]:
        codes = {r.get("code") for r in out["refused"]}
        text = " ".join(r["reason"] for r in out["refused"][:3])
        if "stale" in codes:
            raise _api().CommandError("stale", "도면 빼기 표시가 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요.")
        raise _api().CommandError("bad_args" if "bad_actor" in codes else "failed", text)
    if out["changed"]:
        eng.changed("nodes")
    return {"ver": out["ver"], "changed": out["changed"]}


def _migrate(eng, a):
    """0.1 구간 파일을 새 판으로 바꾼다(사용자가 누를 때 한 번. 읽기 API는 바꾸지 않는다)."""
    _check_project(eng, a)
    pg = _pg(eng)
    try:
        ns = nodes.load(pg)
    except (OSError, ValueError) as exc:
        raise _api().CommandError("failed", "구간 파일을 바꾸지 못했습니다(%s)." % str(exc)[:120])
    eng.changed("nodes", (ns or {}).get("set_rev"))
    return {"set_rev": (ns or {}).get("set_rev") or 0, "read_only": (ns or {}).get("read_only")}


def register(commands):
    """api.COMMANDS에 nodes.* 명령을 올린다. 이미 있는 이름이면 덮어쓰지 않고 오류를 낸다."""
    api = _api()
    C, v_str, v_int, v_list, v_obj, v_enum, v_bool = (api.Command, api.v_str, api.v_int, api.v_list, api.v_obj, api.v_enum, api.v_bool)
    rev = (v_int(0, INT_MAX), True)
    proj = (v_str(1, 120), True)
    target = v_list(v_obj(node_id=v_str(1, 40), rev=v_int(0, INT_MAX), state=v_enum("applied", "confirmed", "locked")), 100)
    sheet, ids = (v_str(1, 200), True), (v_list(v_str(1, 200), MAX_IDS), True)
    nid, nids = (v_str(1, 40), True), (v_list(v_str(1, 40), 100), True)

    def put(name, spec_, handler, doc):
        key = "nodes." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    cmd_name = {"set_intent": "set_design_intent"}

    def add(name, spec_, build, doc, needs_target=True):
        base = {"project_id": proj, "set_rev": rev, "targets": (target, needs_target)}
        put(name, dict(base, **spec_), _run(cmd_name.get(name, name), build), doc)

    def with_members(extra):
        def build(pg, a):
            members, skipped = _members(pg, a)
            return dict(extra(a), members=members), skipped
        return build

    add("create", dict(sheet=sheet, ids=ids, name=(v_str(1, 120), True), design_intent=(v_str(0, 2000), False)),
        lambda pg, a: _create_args(pg, a), "고른 구성요소로 구간을 만든다", needs_target=False)
    add("add_members", dict(node_id=nid, sheet=sheet, ids=ids), with_members(lambda a: {"node_id": a["node_id"]}), "구간에 구성요소를 더한다")
    add("remove_members", dict(node_id=nid, sheet=sheet, ids=ids), with_members(lambda a: {"node_id": a["node_id"]}), "구간에서 구성요소를 뺀다")
    add("rename", dict(node_id=nid, name=(v_str(1, 120), True)), lambda pg, a: ({"node_id": a["node_id"], "name": a["name"]}, 0), "구간 이름을 고친다")
    add("set_intent", dict(node_id=nid, text=(v_str(0, 2000), True)), lambda pg, a: ({"node_id": a["node_id"], "text": a["text"]}, 0),
        "설계 의도를 고친다(빈 글이면 지움)")
    add("merge", dict(node_ids=(v_list(v_str(1, 40), 20), True)), lambda pg, a: ({"node_ids": a["node_ids"]}, 0), "구간을 합친다(첫 구간이 남음)")
    add("split", dict(node_id=nid, sheet=sheet, ids=ids, name=(v_str(1, 120), False)),
        with_members(lambda a: {"node_id": a["node_id"], "name": a.get("name")}), "고른 구성요소를 떼어 새 구간으로 나눈다")
    add("remove", dict(node_id=nid, archive=(v_bool(), False)), lambda pg, a: ({"node_id": a["node_id"], "archive": bool(a.get("archive"))}, 0),
        "구간을 지운다(분석 칸에 판정이 있으면 지우지 않고 needs_archive를 답한다)")
    add("confirm", dict(node_ids=nids), lambda pg, a: ({"node_ids": a["node_ids"]}, 0), "구간을 확정한다")
    add("unconfirm", dict(node_ids=nids), lambda pg, a: ({"node_ids": a["node_ids"]}, 0), "구간 확정을 푼다")
    add("lock", dict(node_ids=nids), lambda pg, a: ({"node_ids": a["node_ids"]}, 0), "분석을 마치고 구간을 잠근다")
    add("unlock", dict(node_ids=nids, reason=(v_str(1, 500), True)), lambda pg, a: ({"node_ids": a["node_ids"], "reason": a["reason"]}, 0),
        "잠금을 푼다(이유를 적어야 함)")
    add("undo", dict(batch_id=(v_str(2, 20), True)), lambda pg, a: ({"batch_id": a["batch_id"]}, 0), "묶음을 되돌린다", needs_target=False)
    add("screen", dict(node_id=nid, status=(v_enum(*nodes.SCREEN_CHOICES), True), reason=(v_str(0, 500), False),
                       confirm=(v_str(0, 2000), False)),
        lambda pg, a: ({k: a.get(k) for k in ("node_id", "status", "reason", "confirm")}, 0),
        "구간을 분석에서 제외(이유 필수)하거나 다시 넣는다. 확정·잠긴 구간이나 결과가 있는 구간은 엔진이 돌려준 확인 글(needs_confirm)을 confirm으로 다시 보낸다")
    put("exclude_drawing", {"project_id": proj, "graph_id": (v_str(1, 200), True), "excluded": (v_bool(), True),
                            "reason": (v_str(0, 500), False), "ver": (v_str(1, 100), True), "confirm": (v_str(0, 2000), False)},
        _exclude_drawing, "도면을 구간 분석에서 빼거나(범례·기호표) 다시 넣는다. 그 도면의 구성요소를 품은 구간이 있으면 확인 글을 confirm으로 다시 보낸다")
    def h_suggest(eng, a):
        _check_project(eng, a)
        return suggest(eng, a["sheet"], a["ids"])
    put("suggest", {"project_id": proj, "sheet": sheet, "ids": ids}, h_suggest, "고른 구성요소로 만들 구간의 카드 초안(저장하지 않음)")
    put("migrate", {"project_id": proj}, _migrate, "0.1 구간 파일을 새 판으로 바꾼다(사용자가 누를 때 한 번)")
    return commands


def _create_args(pg, a):
    members, skipped = _members(pg, a)
    return {"items": [{"members": members, "name": a["name"].strip(), "design_intent": a.get("design_intent") or None,
                       "basis": "사람이 도면에서 고른 구성요소"}]}, skipped
