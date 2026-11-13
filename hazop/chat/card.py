"""채팅 답 카드: 모델이 낸 답(§5.1)을 앱이 검사해 그릴 값으로 바꾼다. Qt를 import하지 않는다.

규격: docs/specs/chat-panel.md §5.2. 모델이 낸 경고와 출처 구분은 믿지 않고 앱이 다시 계산한다.
1. 종류별 존재 확인  — 프로젝트에 없는 ID는 빼고 몇 개 뺐는지 센다.
2. 종류별 근거 확인  — 이번 질문의 도구 결과(tool_ids)에 같은 종류로 나오지 않은 ID는 '근거 확인 안 됨'으로 내린다.
3. 경로 다시 계산    — path_ref는 이번 질문의 trace_path가 낸 것이어야 하고, 앱이 원본 단계를 다시 얻는다.
4. 경고는 앱이 계산  — 원본 단계와 강조 ID 전체에 미확인 색인을 대어 만든다. 모델 warnings는 따로 둔다.
5. text가 비고 general만 있으면 '도면·문서에서 확인한 내용 없음'.

뒤 단위(C1)가 `CardEnv`를 ChatContext 위에 얹어 준다. 지금은 가짜 환경으로 시험한다.
"""

import json
from dataclasses import dataclass, field

REASON_ORDER = ("unknown_symbol", "unknown_tag", "unresolved_connector", "unlinked_sheet", "direction_unknown",
                "flow_against", "valve_position_ignored")
REASON_TEXT = {
    "unknown_symbol": "못 읽은 기호 %d개",
    "unknown_tag": "태그를 읽지 못한 항목 %d개",
    "unresolved_connector": "끊긴 연결 %d개",
    "unlinked_sheet": "이어지지 않은 도면 연결점 %d개",
    "direction_unknown": "흐름 방향 미확인 배관 %d개",
    "flow_against": "흐름과 반대로 지나는 배관 %d개",
    "valve_position_ignored": "밸브 정상 위치를 반영하지 않음(밸브 %d개)",
}
STYLES = ("focus", "path", "cause", "safeguard", "warn", "muted")
KINDS = ("component", "node", "cell", "chunk")
BADGE = {"component": "도면", "node": "도면", "cell": "결과", "chunk": "문서"}
PIPE_KIND = "pipe_segment"
FOLD_LIMIT, FOLD_HEAD, FOLD_TAIL = 12, 5, 5


class CardEnv:
    """카드 검사가 프로젝트 자료를 묻는 창구. 모든 메서드는 자료를 바꾸지 않는다."""

    def component(self, ref):
        """구성요소 ID(또는 하나로 정해지는 태그) -> 프로젝트 ID, 없으면 None."""
        raise NotImplementedError

    def exists(self, kind, ident):
        """node·cell·chunk ID가 있는지."""
        raise NotImplementedError

    def describe(self, ident):
        """-> {"id", "tag", "kind", "sheet"} 또는 None."""
        raise NotImplementedError

    def reasons(self, ident):
        """미확인 색인에서 이 ID에 붙은 사유 집합(REASON_ORDER의 값)."""
        raise NotImplementedError

    def path_steps(self, path_ref):
        """path_ref -> 원본 단계 [{id, kind, flow}](배관 포함). 판이 바뀌었으면 None. (C1 path_steps_raw)"""
        raise NotImplementedError


def path_key(ref):
    return json.dumps(ref, sort_keys=True, ensure_ascii=False) if isinstance(ref, dict) else None


@dataclass
class CardPath:
    label: str
    steps: list
    chips: list
    sheets: list          # [(graph_id, 객체 수)] 경로를 따라 처음 나온 차례
    ref: dict = None


@dataclass
class Card:
    text: str = ""
    general: str = ""
    no_evidence: bool = False
    badges: list = field(default_factory=list)
    refs: list = field(default_factory=list)
    highlight: list = field(default_factory=list)
    paths: list = field(default_factory=list)
    path_notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)       # 앱이 계산: [{reason, text, ids}]
    model_warnings: list = field(default_factory=list)  # 모델이 적은 주의
    actions: list = field(default_factory=list)
    dropped: int = 0
    ungrounded: int = 0

    def footer_notes(self):
        notes = []
        if self.dropped:
            notes.append("프로젝트에 없는 항목 %d개를 뺐습니다" % self.dropped)
        if self.ungrounded:
            notes.append("근거 확인 안 됨 %d개" % self.ungrounded)
        return notes


def _text(v):
    return v if isinstance(v, str) else ""


def _list(v):
    return v if isinstance(v, list) else []


def build_card(answer, tool_ids, env, path_refs=()):
    """모델 답 -> Card. answer가 이상한 모양이어도 깨지지 않는다."""
    answer = answer if isinstance(answer, dict) else {}
    tool_ids = tool_ids or {}
    card = Card(text=_text(answer.get("text")), general=_text(answer.get("general")),
                model_warnings=[w for w in _list(answer.get("warnings")) if isinstance(w, str)],
                actions=[a for a in _list(answer.get("actions")) if isinstance(a, dict)])
    card.no_evidence = not card.text.strip() and bool(card.general.strip())
    seen = {path_key(r) for r in path_refs}
    kinds_used = []
    warn_ids = {}

    def check(kind, ref):
        """-> 확인한 프로젝트 ID 또는 None. 없으면 dropped, 근거 없으면 ungrounded를 센다."""
        if not isinstance(ref, str):
            card.dropped += 1
            return None
        ident = env.component(ref) if kind == "component" else (ref if env.exists(kind, ref) else None)
        if ident is None:
            card.dropped += 1
            return None
        if ident not in (tool_ids.get(kind) or ()):
            card.ungrounded += 1
            return None
        return ident

    for r in _list(answer.get("refs")):
        if not isinstance(r, dict) or r.get("kind") not in KINDS:
            card.dropped += 1
            continue
        ident = check(r["kind"], r.get("id"))
        if ident is not None:
            card.refs.append({"kind": r["kind"], "id": ident})
            if BADGE[r["kind"]] not in kinds_used:
                kinds_used.append(BADGE[r["kind"]])

    for h in _list(answer.get("highlight")):
        if not isinstance(h, dict):
            continue
        ids = [i for i in (check("component", i) for i in _list(h.get("ids"))) if i]
        if ids:
            style = h.get("style") if h.get("style") in STYLES else "focus"
            card.highlight.append({"ids": ids, "style": style})
            for i in ids:
                for reason in env.reasons(i):
                    warn_ids.setdefault(reason, []).append(i)

    for p in _list(answer.get("paths")):
        path = _path(p, env, seen, card)
        if path is None:
            continue
        card.paths.append(path)
        if "도면" not in kinds_used:
            kinds_used.append("도면")
        for step in path.steps:
            reasons = set(env.reasons(step["id"]))
            if step.get("flow") == "unknown":
                reasons.add("direction_unknown")
            elif step.get("flow") == "against":
                reasons.add("flow_against")
            for reason in reasons:
                warn_ids.setdefault(reason, []).append(step["id"])
        _mark_chips(path, env)

    card.badges = [b for b in ("도면", "결과", "문서") if b in kinds_used] if card.text.strip() else []
    for reason in REASON_ORDER:
        ids = list(dict.fromkeys(warn_ids.get(reason, ())))
        if ids:
            card.warnings.append({"reason": reason, "text": REASON_TEXT[reason] % len(ids), "ids": ids})
    return card


def _path(p, env, seen, card):
    if not isinstance(p, dict) or not isinstance(p.get("path_ref"), dict):
        card.path_notes.append("경로는 path_ref로만 받습니다. ID 목록으로 낸 경로는 그리지 않았습니다.")
        return None
    ref, label = p["path_ref"], _text(p.get("label")) or "경로"
    if path_key(ref) not in seen:
        card.path_notes.append("%s: 이번 질문에서 찾은 경로가 아니라서 그리지 않았습니다." % label)
        return None
    steps = env.path_steps(ref)
    if steps is None:
        card.path_notes.append("%s: 도면이 바뀌어 경로를 다시 찾아야 합니다." % label)
        return None
    steps = [s for s in steps if isinstance(s, dict) and isinstance(s.get("id"), str)]
    chips, via, sheets = [], [], []
    for s in steps:
        d = env.describe(s["id"]) or {}
        if s.get("kind") == PIPE_KIND:
            if d.get("tag"):
                via.append(d["tag"])
            continue
        chips.append({"id": s["id"], "tag": d.get("tag") or d.get("kind") or "?", "kind": d.get("kind"),
                      "sheet": d.get("sheet"), "warn": False, "via": " · ".join(dict.fromkeys(via)) or None})
        via = []
        sheet = d.get("sheet")
        if sheet:
            if not sheets or sheets[-1][0] != sheet:
                sheets.append([sheet, 0])
            sheets[-1][1] += 1
    return CardPath(label=label, steps=steps, chips=chips, sheets=[tuple(x) for x in sheets], ref=ref)


def _mark_chips(path, env):
    for c in path.chips:
        c["warn"] = bool(env.reasons(c["id"]))


def fold_chips(chips, expanded=False, limit=FOLD_LIMIT, head=FOLD_HEAD, tail=FOLD_TAIL):
    """칩이 limit개를 넘으면 앞 head개 · {"fold": n} · 뒤 tail개로 접는다."""
    if expanded or len(chips) <= limit:
        return list(chips)
    return list(chips[:head]) + [{"fold": len(chips) - head - tail}] + list(chips[-tail:])


class ContextEnv(CardEnv):
    """`hazop.chat.context.ChatContext` 위에 얹은 환경(C1의 색인을 읽기만 한다). 경로 단계는 C1의 `tools.path_steps_raw`를 쓰고,
    그 함수가 아직 없거나 그래프 판이 바뀌었으면 None(그리지 않음)이다."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.idx = ctx.index

    def component(self, ref):
        if not isinstance(ref, str):
            return None
        if ref in self.idx.nodes:
            return ref
        ids = self.idx.by_tag.get(ref.lower()) or []
        return ids[0] if len(ids) == 1 else None

    def exists(self, kind, ident):
        if kind == "node":
            return any(nd.get("node_id") == ident for ns in self.ctx.node_sets or [] for nd in (ns or {}).get("nodes") or [])
        if kind == "cell":
            check = getattr(self.ctx, "has_cell", None)
            return bool(check and check(ident))
        if kind == "chunk":
            return ident in (getattr(self.ctx, "docs", None) or {})
        return False

    def describe(self, ident):
        n = self.idx.nodes.get(ident)
        if n is None:
            return None
        tag = n.get("line_no") if n.get("node_type") == "pipe_segment" else n.get("tag")
        return {"id": ident, "tag": tag or n.get("tag"), "kind": n.get("kind"), "sheet": n.get("sheet")}

    def reasons(self, ident):
        out = set(self.idx.uncertain.get(ident, ()))
        n = self.idx.nodes.get(ident) or {}
        if "valve" in str(n.get("kind") or ""):
            out.add("valve_position_ignored")
        return out

    def path_steps(self, path_ref):
        if path_ref.get("graph_version") != self.ctx.pg.get("graph_version"):
            return None
        try:
            from hazop.chat import tools
            fn = getattr(tools, "path_steps_raw", None)
            return fn(self.ctx, path_ref) if fn else None
        except Exception:  # noqa: BLE001 - 경로를 못 다시 구하면 그리지 않는다
            return None
