"""AI(채팅)가 실행한 일의 기록 보기(완료 목록 2 A12, 채팅 규격 §4.7). Qt를 import하지 않는다. 읽기만 하고 명령은 없다.

- **읽기** `actionlog?days=8`(오늘부터 지난 날까지 최근 것부터), `actionlog/<YYYY-MM-DD>`(그날 기록, 최근 것부터).
  기록 파일은 `hazop.chat.actions_log`(`<작업 루트>/data/chat-actions/<프로젝트>/<날짜>.jsonl`)이 쓴다. 이 모듈은 그 줄을 화면 줄로 바꾼다.
- **대화 내용은 웹으로 보내지 않는다.** 기록 파일에는 그 동작을 낳은 질문 한 개(`request_text`, 500자까지)가 들어 있지만 화면 줄에는 싣지 않는다.
  승인 표지(`approval_digest`)·대화 ID도 싣지 않는다. 모델이 적은 까닭(`why`, 300자)과 오류 글은 보인다.
- 대상은 종류를 붙여 보낸다: 구간(node) · 칸(cell: 구간/편차/항목) · 도면(sheet) · 구성요소(component, 도면 안 local_id) · 그 밖(other).
  웹은 이 값으로 그 도면·구간·칸으로 이동한다(경로는 보내지 않는다).
"""

import re
from datetime import date

from hazop.chat import actions_log

TOPICS = ("actionlog",)
DEFAULT_DAYS = 8                 # 오늘과 지난 7일(채팅 규격 §4.7)
MAX_DAYS = 31
MAX_ROWS = 500
MAX_TARGETS = 20

RESULT_LABELS = {"ok": "실행함", "candidate": "후보로 올림", "declined": "사람이 하지 않음", "rejected": "앱이 거절",
                 "stale": "바뀌어 실행 안 함", "failed": "실패", "undone": "되돌림", "done": "작업 끝남"}
CLASS_LABELS = {"auto": "바로 실행", "confirm": "사람 확인 뒤"}


def _api():
    from hazop.shell import api
    return api


def _titles():
    from hazop.shell import chat_actions
    return chat_actions.TITLES


def action_label(name, args=None):
    if name == "nodes.apply":
        ops = (args or {}).get("ops") or []
        kinds = {o.get("op") for o in ops if isinstance(o, dict)}
        if kinds == {"add"}:
            return "구간 %d개 만들기" % len(ops)
        return "구간 고치기"
    return _titles().get(name) or name or "동작"


class Resolver:
    """대상 ID -> 종류와 보일 이름. 프로젝트 그래프·구간 집합·도면 이름을 한 번만 읽는다(못 읽으면 그 종류만 'other')."""

    def __init__(self, engine):
        self.names, self.nodes, self.locals, self.tags = {}, {}, {}, {}
        try:
            self.names = dict(engine.graph_names())
        except Exception:  # noqa: BLE001
            self.names = {}
        try:
            from hazop.app import project_ctx
            from hazop.chat import view as chatview
            from hazop.study import nodes as sn
            pg = project_ctx.project_graph(engine.project_id())
            self.locals = chatview._locals(pg)[0]
            self.tags = {n.get("entity_id"): n.get("tag") for n in pg.get("nodes") or [] if n.get("entity_id")}
            ns = sn.read_as_is(pg) or {}
            self.nodes = {n.get("node_id"): n.get("name") or "" for n in ns.get("nodes") or []}
        except Exception:  # noqa: BLE001 - 그래프가 없어도 기록은 보인다
            pass

    def target(self, t):
        t = str(t)
        if t in self.nodes:
            return {"id": t, "kind": "node", "label": ("%s %s" % (t, self.nodes[t])).strip(), "node_id": t}
        parts = t.split("/")
        if len(parts) == 3 and parts[0] in self.nodes:
            return {"id": t, "kind": "cell", "label": "%s 편차 %s 항목 %s" % tuple(parts), "cell": [parts[0], parts[1]]}
        if t in self.names:
            return {"id": t, "kind": "sheet", "label": "도면 %s" % self.names[t], "sheet": t}
        if t in self.locals:
            sheet, local = self.locals[t]
            return {"id": t, "kind": "component", "label": self.tags.get(t) or t, "sheet": sheet, "local_id": local}
        return {"id": t, "kind": "other", "label": t}


# 오류 글 속 로컬 전체 경로(드라이브·UNC·POSIX)를 파일 이름만 남긴다(화면에 사용자 폴더 이름을 싣지 않는다)
_PATH = re.compile(r"""(?:[A-Za-z]:[\\/]|\\\\)[^'"\s<>|]*|(?<![\w.])/(?:[^/'"\s]+/)+[^/'"\s]*""")


def strip_paths(text):
    """'C:\\Users\\x\\a.xlsx' -> 'a.xlsx'(UNC·POSIX 절대 경로도)."""
    if not isinstance(text, str):
        return text
    return _PATH.sub(lambda m: re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1] or "(경로)", text)


def well_formed(row):
    """화면 줄로 바꿀 수 있는 꼴인지(JSON으로는 읽혀도 값의 형태가 틀린 줄은 건너뛰고 센다)."""
    prop = row.get("model_proposal")
    if not isinstance(prop, dict) or not isinstance(prop.get("action"), str):
        return False
    if prop.get("args") is not None and not isinstance(prop.get("args"), dict):
        return False
    if not isinstance(row.get("targets", []), list):
        return False
    return all(row.get(k) is None or isinstance(row.get(k), str)
               for k in ("at", "action_key", "result", "class", "error", "confirmed_by", "confirmed_at", "batch_id", "undo_of"))


def screen_row(row, resolver):
    """기록 한 줄 -> 화면 줄. 질문 원문·승인 표지·대화 ID는 싣지 않는다."""
    prop = row.get("model_proposal") or {}
    name = prop.get("action") or ""
    at = str(row.get("at") or "")
    targets = [resolver.target(t) for t in (row.get("targets") or [])[:MAX_TARGETS]]
    return {"key": "%s|%s|%s" % (row.get("action_key"), row.get("result"), row.get("undo_of") or ""),
            "at": at, "day": at[:10], "time": at[11:16], "action": name, "title": action_label(name, prop.get("args")),
            "class": row.get("class"), "class_label": CLASS_LABELS.get(row.get("class"), row.get("class") or ""),
            "result": row.get("result"), "result_label": RESULT_LABELS.get(row.get("result"), row.get("result") or ""),
            "by": "채팅 AI", "confirmed_by": row.get("confirmed_by"), "confirmed_at": row.get("confirmed_at"),
            "why": str(prop.get("why") or "")[:300], "error": strip_paths(row.get("error")), "targets": targets,
            "targets_total": len(row.get("targets") or []), "batch_id": row.get("batch_id"), "undo_of": row.get("undo_of"),
            "model": row.get("model"), "via": row.get("via")}


def recent(engine, days=DEFAULT_DAYS, today=None):
    """오늘부터 days일 기록을 최근 것부터 -> {project_id, days, rows, total, bad, cut}."""
    days = max(1, min(int(days), MAX_DAYS))
    pid = engine.project_id()
    rows, bad = actions_log.read_recent(pid, days, today=today)
    return _answer(engine, pid, rows, bad, days=days)


def one_day(engine, day):
    pid = engine.project_id()
    rows, bad = actions_log.read_day(pid, day)
    return _answer(engine, pid, list(reversed(rows)), bad, day=day)


def _answer(engine, pid, rows, bad, **extra):
    resolver = Resolver(engine)
    good = [r for r in rows if well_formed(r)]
    bad += len(rows) - len(good)
    rows = good
    shown = [screen_row(r, resolver) for r in rows[:MAX_ROWS]]
    counts = {}
    for r in rows:
        counts[r.get("result")] = counts.get(r.get("result"), 0) + 1
    return dict({"project_id": pid, "rows": shown, "total": len(rows), "cut": len(rows) > MAX_ROWS, "bad": bad, "counts": counts}, **extra)


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'actionlog'. 날짜 형식이 틀리면 None(404)."""
    api = _api()
    if len(parts) == 1:
        raw = (query or {}).get("days")
        raw = raw[0] if isinstance(raw, list) else raw
        try:
            days = int(raw) if raw not in (None, "") else DEFAULT_DAYS
        except (TypeError, ValueError):
            days = DEFAULT_DAYS
        return api._json(recent(engine, days))
    if len(parts) == 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]):
        try:
            date.fromisoformat(parts[1])
        except ValueError:
            return None
        return api._json(one_day(engine, parts[1]))
    return None
