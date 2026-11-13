"""시험용 가짜 채팅 도구 목록과 MCP 서버 실행기. C1의 실제 도구(`hazop.chat.registry`)와 순서에 매이지 않게 쓴다.

실행: python -E -s fake_tools.py --project <id> --question-file <파일> [--version-file <파일>]
--version-file이 있으면 도구를 부를 때마다 그 파일 내용을 그래프 판(graph_version)으로 다시 읽는다(자료가 바뀐 경우 시험).
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

COMPONENTS = {"g1/e-pz01": {"tag": "RC-PZ01", "kind": "pressurizer"},
              "g1/e-pv101": {"tag": "RC-PV101", "kind": "control_valve"},
              "g1/e-psv101": {"tag": "RC-PSV101", "kind": "safety_valve"}}
GROUPS = [{"key": k, "count": n} for k, n in (("control_valve", 4), ("gate_valve", 3), ("pump", 2), ("tank", 1),
                                               ("pressurizer", 1))]


class FakeCtx:
    def __init__(self, project_id, version="v1"):
        self.project_id = project_id
        self.pg = {"graph_version": version}


def _env(data, total=None, returned=None, cursor=None, sources=("drawing",)):
    return {"ok": True, "data": data, "total": total, "returned": returned, "cursor": cursor,
            "truncated": cursor is not None, "uncertain": [], "sources": [{"kind": k} for k in sources], "error": None}


def _err(code, message):
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


def count(ctx, filter=None, group_by="kind", limit=50, cursor=None):
    start = int(cursor or 0)
    page = GROUPS[start:start + int(limit)]
    nxt = start + len(page)
    return _env({"groups": page, "group_by": group_by}, total=len(GROUPS), returned=len(page),
                cursor=nxt if nxt < len(GROUPS) else None)


def trace_path(ctx, start, end, mode="physical", limit=200, cursor=None):
    ids = {c["tag"]: k for k, c in COMPONENTS.items()}
    a, b = ids.get(start, start), ids.get(end, end)
    if a not in COMPONENTS or b not in COMPONENTS:
        return _err("not_found", "없는 객체")
    steps = [{"id": a, "tag": COMPONENTS[a]["tag"]}, {"id": "g1/e-pv101", "tag": "RC-PV101"},
             {"id": b, "tag": COMPONENTS[b]["tag"]}]
    return _env({"path_ref": {"start": a, "end": b, "mode": mode, "graph_version": ctx.pg["graph_version"]},
                 "steps": steps}, total=3, returned=3)


def get_component(ctx, id):
    if id not in COMPONENTS:
        return _err("not_found", "없는 객체")
    return _env(dict(COMPONENTS[id], id=id))


def big(ctx):
    return _env({"blob": "가" * 9000})


def boom(ctx):
    raise RuntimeError("도구 안에서 난 오류")


def _schema(**props):
    return {"type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "additionalProperties": False}


REGISTRY = {
    "count": {"fn": count, "description": "묶음별 개수", "returns": (),
              "input_schema": _schema(filter="object", group_by="string", limit="integer", cursor="string")},
    "trace_path": {"fn": trace_path, "description": "두 객체 사이 배관 경로", "returns": ("component", "path_ref"),
                   "input_schema": _schema(start="string", end="string", mode="string", limit="integer",
                                           cursor="string")},
    "get_component": {"fn": get_component, "description": "객체 하나", "returns": ("component",),
                      "input_schema": _schema(id="string")},
    "big": {"fn": big, "description": "너무 큰 결과", "input_schema": _schema()},
    "boom": {"fn": boom, "description": "예외를 내는 도구", "input_schema": _schema()},
}


def main(argv=None):
    from hazop.chat import mcp_server
    argv = list(sys.argv[1:] if argv is None else argv)
    version_file = None
    if "--version-file" in argv:
        i = argv.index("--version-file")
        version_file = argv[i + 1]
        del argv[i:i + 2]

    def version():
        if not version_file:
            return "v1"
        try:
            with open(version_file, encoding="utf-8") as fh:
                return fh.read().strip() or "v1"
        except OSError:
            return "v1"

    def loader(project_id):
        return FakeCtx(project_id, version())

    def refresher(ctx):
        v = version()
        return ctx if v == ctx.pg["graph_version"] else FakeCtx(ctx.project_id, v)

    return mcp_server.main(argv, registry=REGISTRY, loader=loader, refresher=refresher)


if __name__ == "__main__":
    sys.exit(main())
