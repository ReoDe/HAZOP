"""새 웹 화면의 지식그래프 패널(완료 목록 2 A6, INTENT §3.3). Qt를 import하지 않는다.

- **읽기 `kg`**(`ReadApi`가 부른다):
    `kg`(요약: 도면별 묶음·노드 수·잠재 후보 상태 수·처음 펼칠 묶음·판단 판 지문 ver) · `kg/graph?expand=<gid,…|all>`(그릴 그래프) ·
    `kg/node?id=<노드 ID>`(상세) · `kg/search?q=<글>`(찾기) · `kg/force-graph.js`(이미 묶인 hazop/kg/vendor의 그리기 라이브러리).
  노드 ID에는 '/'가 들어 있어 경로가 아니라 질의 문자열로 받는다. 읽기는 파일을 쓰지 않는다.
- **명령 `kg.*`**: `kg.judge`(잠재 후보 판단: 후보 확인·후보 기각·부재 확정·무관·판단 되돌리기), `kg.open`(패널 열기 사건).
  판단자는 설정의 검토자 이름이고(웹 인자 아님) 시각은 여기서 채운다. 판단은 상세에서 본 그 항목의 내용 지문(digest)·상태와 판 표시 ver(`<프로젝트>|<판단 파일 sha256 16자>`)를 들고 오고, 하나라도 다르면 저장하지 않는다(stale).
- **채팅이 부를 실행 함수**: `open_panel`, `find_nodes`, `judge`. 채팅 연결(hazop/chat/actions.py)은 채팅 담당이 한다.
- 잠재 후보의 상태·재확인·허용 동작은 `hazop.kg.expect`가 정한다. 규칙 판이 바뀌면 확인됨·부재 확정·무관이 재확인으로 돌아가는 것도
  엔진 동작 그대로다. 여기서는 조건을 다시 세지 않는다.
- 큰 그래프(APR1400 143쪽): 전체 노드가 `screen.PANEL_NODE_CAP` 이하면 모두 펼쳐 그리고, 넘으면 도면별 묶음 노드로 먼저 그린 뒤
  사람이 묶음을 눌러 펼친다. 펼친 노드 합이 상한을 넘으면 거절한다. 찾기는 늘 프로젝트 전체에서 한다.
"""

import hashlib
import logging
import os

from hazop import paths
from hazop.kg import expect, screen

LOG = logging.getLogger("hazop.shell.api_kg")
TOPICS = ("kg",)
PROJECT_PREFIXES = ("kg.",)    # kg.* 명령은 웹이 본 프로젝트와 엔진의 지금 프로젝트가 같아야 돈다(api.dispatch). ver에도 프로젝트 ID를 넣는다
ACTIONS = ("confirm", "reject", "absent", "not_applicable", "undo")
SEARCH_LIMIT = 20
MAX_EXPAND = 200
_CACHE = {}   # 최근 패널 모델 하나: {"key", "model"}. 열쇠는 내용 지문(그래프 판·지식그래프 판·판단 파일 지문·규칙 지문)


def _api():
    from hazop.shell import api
    return api


# ---------------------------------------------------------------- 자료 모으기

def _load_kg(project_id):
    """프로젝트 지식그래프 또는 None. 깨진 지식그래프는 (None, 사유)."""
    from hazop.kg import build
    root = os.path.join(paths.output_root("knowledge-graph"), paths.safe_name("kg-%s" % project_id))
    if not os.path.isfile(os.path.join(root, build.POINTER_FILE)):
        return None, None
    try:
        return build.load_outputs(root)[1], None
    except (OSError, ValueError, KeyError) as exc:
        LOG.warning("지식그래프를 읽지 못함: %s", exc)
        return None, "지식그래프를 읽을 수 없어 도면 노드와 잠재 후보만 보입니다."


def _judgement_fp(path):
    """판단 파일 내용 지문(sha256 앞 16자): 없으면 'none'."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except FileNotFoundError:
        return "none"


def _ver(pid, path):
    """판단 판 표시 '<프로젝트 ID>|<판단 파일 지문>'. 프로젝트를 넣어 두 프로젝트 모두 파일이 없을 때('none')도 같아지지 않게 한다."""
    return "%s|%s" % (pid, _judgement_fp(path))


def _blocks(kg, pg):
    """규격 HZ-DSN-05 §2.3 ③ '차단 띠': 지식그래프 검증이 막힘, 지식그래프를 만든 뒤 도면 판이 바뀜. [{kind, text}]."""
    out = []
    if kg is None:
        return out
    v = kg.get("validation") or {}
    if v.get("status") != "passed":
        out.append({"kind": "kg_blocked", "text": "지식그래프 검증이 막혀 있습니다(%s, 차단 %d건). 지식 노드와 관계는 확인 전 자료로만 보고, "
                    "막힌 까닭을 고친 뒤 도면이나 문서를 다시 추출하면 지식그래프도 다시 만들어집니다."
                    % (v.get("status") or "상태 없음", len(v.get("blockers") or []))})
    have = {s["graph_id"]: (s["graph_version"], s.get("drawing_number")) for s in pg.get("sheets") or []}
    bad = sorted((have.get(r.get("graph_id")) or (None, r.get("graph_id")))[1] or r.get("graph_id")
                 for r in kg.get("graph_refs") or [] if (have.get(r.get("graph_id")) or (None,))[0] != r.get("graph_version"))
    if bad:
        out.append({"kind": "graph_mismatch", "text": "지식그래프를 만든 뒤 도면 %d장이 바뀌었거나 빠졌습니다(%s). 지식 관계가 지금 도면과 맞지 않을 수 있습니다. "
                    "도면을 다시 추출하면 지식그래프도 다시 만들어집니다." % (len(bad), ", ".join(bad[:5]) + (" 외" if len(bad) > 5 else ""))})
    return out


def _context(engine):
    """(맥락 dict, None) 또는 (None, 사유). 맥락: pg, kg, model, expectations, ver, judge_problem, notes."""
    from hazop.app import project_ctx
    pid = engine.project_id()
    try:
        pg = project_ctx.project_graph(pid)
    except (OSError, ValueError, KeyError):
        return None, "프로젝트 그래프를 만들 수 없습니다. 도면을 먼저 추출하세요."
    if not pg or not pg.get("nodes"):
        return None, "추출한 도면이 없습니다. 도면을 등록하고 추출하면 지식그래프가 만들어집니다."
    kg, kg_note = _load_kg(pid)
    path = expect.store_path(pid)
    ver = _ver(pid, path)
    judge_problem = None
    try:
        judgements = expect.load_judgements(path, pid)
    except (OSError, expect.ExpectError) as exc:
        judgements, judge_problem = {}, "잠재 후보 판단 파일을 읽을 수 없어 판단을 저장하지 않습니다(%s)." % str(exc)[:160]
    try:
        expectations = expect.evaluate_cached(pg, kg, judgements)
    except expect.ExpectError as exc:
        expectations, judge_problem = None, "잠재 후보를 계산하지 못했습니다(%s)." % str(exc)[:160]
    items = (expectations or {}).get("items") or ()
    exp_fp = hashlib.sha256("\n".join("%s %s %s" % (i["id"], i["digest"], i["state"]) for i in items).encode("utf-8")).hexdigest()
    key = (pid, pg.get("graph_version"), len(pg.get("nodes") or ()), (kg or {}).get("kg_version"), ver, exp_fp, judge_problem)
    hit = _CACHE.get("key") == key
    model = _CACHE["model"] if hit else screen.panel_model(pg, kg, expectations)
    if not hit:
        _CACHE.clear()
        _CACHE.update(key=key, model=model)
    notes = [x for x in (kg_note, judge_problem) if x]
    if expectations and expectations.get("bad_judgements"):
        notes.append("형식이 어긋난 판단 기록 %d건은 적용하지 않았습니다(파일에는 그대로 있음)." % len(expectations["bad_judgements"]))
    if expectations and expectations.get("orphan_judgements"):
        notes.append("대상이 그래프에서 사라진 판단 기록 %d건이 있습니다(파일에는 그대로 있음)." % len(expectations["orphan_judgements"]))
    return {"pid": pid, "pg": pg, "kg": kg, "model": model, "expectations": expectations, "ver": ver, "path": path,
            "judge_problem": judge_problem, "notes": notes, "blocks": _blocks(kg, pg)}, None


# ---------------------------------------------------------------- 읽기

def summary(engine):
    ctx, why = _context(engine)
    if ctx is None:
        return {"available": False, "reason": why}
    m = ctx["model"]
    total = len(m["nodes"])
    states = {}
    recheck = 0
    for n in m["nodes"].values():
        if n["layer"] == "exp":
            states[n["xs"]] = states.get(n["xs"], 0) + 1
            recheck += 1 if n["recheck"] else 0
    groups = [dict(m["groups"][g]) for g in m["order"]]
    full = total <= screen.PANEL_NODE_CAP
    return {"available": True, "project_id": ctx["pid"], "ver": ctx["ver"], "cap": screen.PANEL_NODE_CAP, "total": total,
            "links": len(m["links"]), "mode": "full" if full else "overview", "expand": list(m["order"]) if full else [],
            "groups": groups, "sheets": sum(1 for g in groups if g["kind"] == "sheet"),
            "layers": {ly: sum(1 for n in m["nodes"].values() if n["layer"] == ly) for ly in ("pid", "kn", "exp")},
            "expect": {"states": [{"state": s, "label": expect.STATES[s], "count": states.get(s, 0),
                                   "shown": s in screen.EXPECT_SHOWN} for s in expect.STATES],
                       "recheck": recheck, "rules_version": (ctx["expectations"] or {}).get("rules_version")},
            "has_kg": ctx["kg"] is not None, "can_judge": ctx["judge_problem"] is None, "notes": ctx["notes"],
            "blocks": ctx["blocks"]}


def graph(engine, expand):
    """그릴 그래프. expand: 묶음 ID 목록 또는 'all'. 상한을 넘으면 {"refused": 사유}."""
    ctx, why = _context(engine)
    if ctx is None:
        return {"available": False, "reason": why}
    m = ctx["model"]
    want = list(m["order"]) if expand == "all" else [g for g in expand if g in m["groups"]]
    try:
        out = screen.panel_graph(m, want)
    except screen.PanelLimit as exc:
        return {"available": True, "refused": str(exc), "count": exc.count, "cap": exc.cap}
    out["available"] = True
    return out


def node(engine, nid):
    ctx, _why = _context(engine)
    if ctx is None:
        return None
    d = screen.panel_node(ctx["model"], nid, ctx["kg"])
    if d is not None:
        d["ver"] = ctx["ver"]
        d["can_judge"] = ctx["judge_problem"] is None
    return d


def find_nodes(engine, text, limit=SEARCH_LIMIT):
    """채팅·찾기 칸이 부른다: 태그·이름·규칙 ID로 찾은 노드 [{id, label, layer, type, group, drawing}]. 그래프가 없으면 빈 목록."""
    ctx, _why = _context(engine)
    if ctx is None:
        return []
    return screen.panel_search(ctx["model"], text, max(1, min(int(limit), 50)))


def _vendor():
    with open(screen.VENDOR_JS, "rb") as fh:
        return fh.read()


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'kg'. 없는 자료는 None(404)."""
    api = _api()
    if len(parts) == 1:
        return api._json(summary(engine))
    if len(parts) != 2:
        return None
    what = parts[1]
    if what == "graph":
        raw = (query.get("expand") or "").strip()
        expand = "all" if raw == "all" else [g for g in raw.split(",") if g][:MAX_EXPAND]
        return api._json(graph(engine, expand))
    if what == "node":
        data = node(engine, query.get("id") or "")
        return api._json(data) if data is not None else None
    if what == "search":
        return api._json({"hits": find_nodes(engine, (query.get("q") or "")[:100])})
    if what == "force-graph.js":
        from hazop.shell import scheme
        return scheme.Response(200, "text/javascript", _vendor())
    return None


# ---------------------------------------------------------------- 쓰기·실행 함수(채팅도 부른다)

def open_panel(engine, node_id=None):
    """패널을 열라고 웹에 알린다(node_id가 있으면 그 노드를 찾아 고른다)."""
    engine.emit("kg.open", {"focus": node_id} if node_id else {})
    return {"opened": True, "focus": node_id}


STALE_TEXT = "잠재 후보가 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 바뀐 내용을 보고 한 번 더 눌러 주세요."


def judge(engine, expectation_id, action, digest, state, reason="", evidence="", ver=None, by=None):
    """잠재 후보 하나를 판단한다 -> {"ver", "state", "state_label"}.
    digest·state: 사람이 본 그 항목의 내용 지문과 상태(상세 읽기의 expectation.digest·state). 저장 직전에 다시 계산한 값과 다르면
    (도면을 다시 추출해 후보가 바뀌었거나 다른 곳에서 판단함) 저장하지 않고 stale. 사람이 보지 못한 내용을 판단으로 남기지 않으려는 것이다.
    ver가 주어지면 지금 판단 판 표시('<프로젝트>|<판단 파일 지문>')와 같아야 한다(다른 프로젝트·다른 판단 파일이면 stale).
    판단자는 by(없으면 설정의 검토자 이름). 허용되지 않는 동작·빠진 필수 입력은 저장하지 않고 CommandError."""
    api = _api()
    who = (by or engine.reviewer() or "").strip()
    if not who:
        raise api.CommandError("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 판단한 사람으로 남습니다.")
    if action not in ACTIONS:
        raise api.CommandError("bad_args", "모르는 판단입니다.")
    ctx, why = _context(engine)
    if ctx is None:
        raise api.CommandError("failed", why)
    if ctx["judge_problem"]:
        raise api.CommandError("failed", ctx["judge_problem"])
    if ver is not None and ver != ctx["ver"]:
        raise api.CommandError("stale", STALE_TEXT)
    item = next((i for i in (ctx["expectations"] or {}).get("items") or [] if i["id"] == expectation_id), None)
    if item is None:
        raise api.CommandError("not_found", "없는 잠재 후보입니다.")
    if item["digest"] != digest or item["state"] != state:
        raise api.CommandError("stale", STALE_TEXT)
    from hazop.study import nodes as study_nodes
    try:
        rec = expect.apply_action(item, action, who, reason or "", evidence or "", at=study_nodes.now_utc())
        if _ver(ctx["pid"], ctx["path"]) != ctx["ver"]:
            raise api.CommandError("stale", STALE_TEXT)
        expect.save_judgement(ctx["path"], ctx["pid"], rec)
    except expect.ExpectError as exc:
        raise api.CommandError("failed", str(exc)[:300])
    except OSError as exc:
        raise api.CommandError("failed", "저장하지 못했습니다(%s)." % str(exc)[:200])
    engine.changed("kg")
    return {"ver": _ver(ctx["pid"], ctx["path"]), "state": rec["state"], "state_label": expect.STATES[rec["state"]]}


def _h_judge(engine, a):
    return judge(engine, a["id"], a["action"], a["digest"], a["state"], a.get("reason") or "", a.get("evidence") or "", ver=a["ver"])


def _h_open(engine, a):
    return open_panel(engine, a.get("id"))


def register(commands):
    api = _api()
    C, v_str, v_enum = api.Command, api.v_str, api.v_enum

    def put(name, spec_, handler, doc):
        key = "kg." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("judge", {"id": (v_str(1, 80), True), "action": (v_enum(*ACTIONS), True), "reason": (v_str(0, 500), False),
                  "evidence": (v_str(0, 300), False), "ver": (v_str(1, 200), True), "digest": (v_str(1, 60), True),
                  "state": (v_enum(*expect.STATES), True)},
        _h_judge, "잠재 후보 판단(후보 확인·후보 기각·부재 확정·무관·판단 되돌리기). 판단자는 설정의 검토자 이름")
    put("open", {"id": (v_str(1, 300), False)}, _h_open, "지식그래프 패널을 연다(노드를 주면 그 노드를 고른다)")
