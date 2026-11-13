"""채팅 창과 도면 사이의 순수 변환, 질문 한 번의 기록. Qt를 import하지 않는다(docs/specs/chat-panel.md §6.4).

- split_by_sheet / path_steps / lift: 프로젝트 그래프 ID ↔ 도면 안 local_id. 도면 연결 구간처럼 도면이 없는 것은 어느 도면에도 그리지 않는다.
- marks_for_card: 카드 하나를 `ViewerHost.show_marks`가 받는 도면별 항목으로 바꾼다.
- QuestionLog: 세션의 on_tool_event를 받아 질문마다 부른 도구와 path_ref를 모은다(답 카드 검사 입력).

채팅 세션(`hazop.chat.session.ChatSession`, 단위 S-conn)에 기대는 인터페이스는 `SessionPort`에 적어 둔다. 창은 이 모양만 안다.
"""

import threading


class SessionPort:
    """창이 채팅 세션에 기대는 것(ChatSession이 이미 가진 이름). 시험은 이 모양의 가짜를 쓴다.

    생성자 인자(이름 그대로): on_tool_event, on_answer, on_error, on_state — 모두 읽기 스레드에서 불릴 수 있다.
        on_tool_event(question_id, name, args, result)   on_answer(question_id, card, tool_ids)
        on_error(question_id, error{error_kind, conn_state, message, limit})   on_state(state, message)
    메서드: start()  ask(text, view{stage, sheet, selected}) -> question_id  stop()  close()  set_model("fast"|"normal"|"deep")
    """


_LOCALS = {}  # 한 칸짜리 캐시: {"key": (id(pg), graph_version), "fwd", "back"}


def _locals(pg):
    """프로젝트 노드 ID -> (도면 graph_id, 도면 안 local_id)와 그 거꾸로. 같은 판이면 한 번만 만든다(pg는 건드리지 않는다)."""
    key = (id(pg), pg.get("graph_version"), len(pg.get("nodes") or ()))
    if _LOCALS.get("key") != key:
        fwd, back = {}, {}
        for n in pg.get("nodes") or []:
            if n.get("sheet") and n.get("local_id"):
                fwd[n["entity_id"]] = (n["sheet"], n["local_id"])
                back[(n["sheet"], n["local_id"])] = n["entity_id"]
        _LOCALS.clear()
        _LOCALS.update(key=key, fwd=fwd, back=back)
    return _LOCALS["fwd"], _LOCALS["back"]


def split_by_sheet(pg, ids):
    """프로젝트 ID -> {graph_id: [local_id]}, 들어온 순서를 지킨다. 도면에 그릴 수 없는 ID는 뺀다."""
    fwd, _ = _locals(pg)
    out = {}
    for i in ids or []:
        hit = fwd.get(i)
        if hit:
            out.setdefault(hit[0], []).append(hit[1])
    return out


def path_steps(pg, steps):
    """원본 경로 단계 [{id, flow}] -> {graph_id: [draw_path 단계 {id: local_id, flow}]}, 경로를 따라 처음 나온 도면 차례."""
    fwd, _ = _locals(pg)
    out = {}
    for s in steps or []:
        hit = fwd.get(s.get("id"))
        if hit:
            out.setdefault(hit[0], []).append({"id": hit[1], "flow": s.get("flow")})
    return out


def lift(pg, graph_id, local_ids):
    """뷰어에서 고른 local_id -> 프로젝트 ID. 모르는 것은 뺀다."""
    _, back = _locals(pg)
    return [back[(graph_id, l)] for l in local_ids or [] if (graph_id, l) in back]


def marks_for_card(pg, card, path_index=None):
    """카드의 경로(path_index 하나, None이면 전부)와 강조를 도면별 항목으로. `ViewerHost.show_marks`의 marks_by_sheet 형식."""
    out = {}
    chosen = card.paths if path_index is None else card.paths[path_index:path_index + 1]
    for p in chosen:
        for sheet, steps in path_steps(pg, p.steps).items():
            out.setdefault(sheet, []).append({"op": "path", "steps": steps, "style": "path", "numbered": True})
    for h in card.highlight:
        for sheet, ids in split_by_sheet(pg, h["ids"]).items():
            out.setdefault(sheet, []).append({"op": "mark", "groups": [{"ids": ids, "style": h["style"], "label": None}],
                                              "dim_others": True, "center": False})
    return out


def _find_path_refs(data, depth=0):
    """도구 결과 data 안의 path_ref를 모두 찾는다(trace_path는 path·flow_path 안에 하나씩 둔다)."""
    out = []
    if depth > 4 or not isinstance(data, (dict, list)):
        return out
    items = data.items() if isinstance(data, dict) else enumerate(data)
    for key, value in items:
        if key == "path_ref" and isinstance(value, dict):
            out.append(value)
        elif isinstance(value, (dict, list)):
            out.extend(_find_path_refs(value, depth + 1))
    return out


class QuestionLog:
    """질문마다 부른 도구와 그 결과에서 나온 path_ref를 모은다. on_tool_event는 읽기 스레드에서 오므로 잠근다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tools = {}
        self._calls = {}
        self._refs = {}

    def tool_event(self, qid, name, args, result):
        refs = _find_path_refs(result.get("data") if isinstance(result, dict) else None)
        with self._lock:
            self._calls.setdefault(qid, []).append((str(name), args if isinstance(args, dict) else {}))
            self._tools.setdefault(qid, []).append(str(name))
            for ref in refs:
                if ref not in self._refs.setdefault(qid, []):
                    self._refs[qid].append(ref)

    def tool_count(self, qid):
        return len(self._tools.get(qid, ()))

    def tool_names(self, qid):
        return list(self._tools.get(qid, ()))

    def tool_calls(self, qid):
        """[(도구 이름, 인자)] — 카드 바닥 '근거 보기'에 보인다."""
        return list(self._calls.get(qid, ()))

    def path_refs(self, qid):
        return list(self._refs.get(qid, ()))

    def forget(self, qid):
        with self._lock:
            self._tools.pop(qid, None)
            self._calls.pop(qid, None)
            self._refs.pop(qid, None)


# ---------------------------------------------------------------- 구독이 없는 PC의 안내(§8)

INSTALL_URL = "https://docs.claude.com/en/docs/claude-code/setup"
NO_CLI = ("이 PC에 Claude Code가 없습니다. 채팅은 Claude 구독(Pro·Max 등)과 Claude Code 설치가 있어야 씁니다. "
          "도면 보기·추출·분석 기록은 그대로 쓸 수 있습니다.")
# conn_state -> (입력칸을 막는가, 안내 글, 단추 이름). 표에 없는 상태는 상태 표시줄 칩과 같은 문구(message)를 쓴다.
_AVAILABILITY = {
    "not_installed": (True, NO_CLI, "install"), "cli_unsupported": (True, NO_CLI, "install"),
    "cli_too_old": (True, NO_CLI, "install"),
    "login_required": (True, "Claude Code에 로그인하지 않았습니다.", "login"),
    "login_expired": (True, "Claude Code에 로그인하지 않았습니다.", "login"),
    "disabled": (True, "구독으로 채팅을 쓰려면 먼저 켜야 합니다. 소비자 약관과 학습 설정 안내를 확인한 뒤 켜세요.", "enable"),
}
_OPEN = ("ok", "unchecked", "checking", "limit_warning", "overage_risk", None)


def availability(conn_state, message="", reset_text=None):
    """채팅 창이 conn_state에 따라 보일 모양. -> {"blocked": bool, "text": str, "button": None|"install"|"login"|"enable"}"""
    if conn_state in _OPEN:
        return {"blocked": False, "text": "", "button": None}
    if conn_state in ("limit_reached", "overage"):
        tail = " %s에 다시 쓸 수 있습니다." % reset_text if reset_text else ""
        return {"blocked": True, "text": "한도에 닿았습니다.%s" % tail, "button": None}
    if conn_state in _AVAILABILITY:
        blocked, text, button = _AVAILABILITY[conn_state]
        return {"blocked": blocked, "text": text, "button": button}
    return {"blocked": True, "text": message or "AI 연결을 쓸 수 없습니다.", "button": None}


# ---------------------------------------------------------------- 예시 질문(§7: 종류별, 태그는 지금 프로젝트에서)

def examples(pg, limit=2):
    """프로젝트 그래프에서 태그를 골라 종류별 예시 질문을 만든다. -> [(묶음 이름, [질문])]. 그래프가 없으면 태그 없는 질문."""
    tags = []
    for n in (pg or {}).get("nodes") or []:
        if n.get("tag") and n.get("kind") not in ("pipe_segment", "continuation") and n["tag"] not in tags:
            tags.append(str(n["tag"]))
    a = tags[0] if tags else None
    b = tags[-1] if len(tags) > 1 else None
    out = [("찾기", ["%s는 어디에 이어져 있어?" % a] if a else ["도면에 어떤 기기가 있어?"]),
           ("경로", ["%s에서 %s까지 배관 경로와 밸브를 알려줘." % (a, b)] if b else ["두 기기 사이 배관 경로를 알려줘."]),
           ("개수", ["도면 전체에 제어밸브는 몇 개이고 태그는 뭐야?"]),
           ("확인할 곳", ["못 읽은 기호나 끊긴 연결이 있는 곳을 알려줘."])]
    return [(name, qs[:limit]) for name, qs in out]
