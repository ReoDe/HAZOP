"""새 웹 화면의 도면 쪽 확정과 DEXPI 내보내기의 엔진 쪽(앱 틀 규격 §10.6·§10.7, DEXPI 규격 HZ-PLN-22 §6). Qt를 import하지 않는다.

- **쪽 확정 읽기** `sheetconf/<도면 ID>`: 엔진 함수 `confirmation.sheet_confirmation`의 답(상태·미확인·위치 없음·원본에 남은 것·견줌·확정·지문·판)을 그대로 돌려준다.
  화면은 조건을 다시 세지 않는다. 읽기는 파일을 쓰지 않는다.
- **쪽 확정 명령** `sheet.compare`·`sheet.confirm`·`sheet.unconfirm`: 화면이 읽은 세 파일 지문(`ver`)과 기록 판(`rev`)을 실어 보내고 어긋나면 stale로 거절한다. `by`는 설정의 검토자
  이름이고 `at`은 엔진이 채운다(웹 인자 아님). 조건을 못 채우면 엔진이 거절하고 사유(미확인 n곳·위치 없는 것·원본과 견줌 없음)를 그대로 올린다.
- **DEXPI 내보내기** `dexpi`(읽기: 내보낼 수 있는 도면 목록과 사유), `dexpi.export`(명령): 확정된 쪽만 낸다. 저장할 폴더는 창이 Python 쪽 대화상자로 묻고(웹은 경로를 보내지 않는다),
  이미 있는 파일을 덮어쓸 때는 확인을 받는다. 결과는 낸 도면(파일 이름만)과 뺀 목록(확정 안 된 쪽)과 도면별 뺀 항목 수로 보인다.
- 채팅의 실행 동작(쪽 확정·DEXPI 내보내기)은 hazop/shell/chat_actions.py가 이 모듈의 `_sheet_command`·`_export`를 그대로 불러 잇는다(8c74f5f).
- **원본 선택** `sources`(읽기)·`sources.choose`(명령): 같은 도면 번호의 원본이 형식 둘 이상일 때 어느 형식을 쓸지 사람이 고른다(hazop.graph.sources).
"""

import logging
import os

from hazop.extract import confirmation

LOG = logging.getLogger("hazop.shell.api_drawings")
MAX_ROWS = 200
TOPICS = ("sheetconf", "dexpi", "sources")                 # api.py가 읽기 길을 이 모듈로 잇는다(register와 함께 hazop/shell/README.md의 등록 규약)
PROJECT_PREFIXES = ("sheet.", "dexpi.", "sources.")           # 쪽 확정·내보내기 명령은 프로젝트 ID를 실어야 한다


def _api():
    from hazop.shell import api
    return api


def _name(engine, graph_id):
    name = engine.graph_names().get(graph_id)
    if not name:
        raise _api().CommandError("not_found", "없는 도면")
    return name


def _trim(rows, n=MAX_ROWS):
    return list(rows[:n])


def status(engine, graph_id):
    """도면 한 쪽의 확정 상태(엔진이 센 값 그대로, 긴 목록만 자른다). 못 읽으면 {"available": False, "reason"}."""
    name = engine.graph_names().get(graph_id)
    if not name:
        return None
    try:
        st = confirmation.sheet_confirmation(name)
    except FileNotFoundError:
        return {"available": False, "reason": "이 도면의 추출 결과가 없습니다."}
    except (OSError, ValueError) as exc:
        return {"available": False, "reason": "쪽 자료를 읽을 수 없습니다(%s)." % str(exc)[:120]}
    out = {k: v for k, v in st.items() if k not in ("unconfirmed", "unplaced", "files", "released")}
    out.update(available=True, graph_id=graph_id, ver=st["fingerprint"], unconfirmed=_trim(st["unconfirmed"]), unconfirmed_total=len(st["unconfirmed"]),
              unplaced=_trim(st["unplaced"]), unplaced_total=len(st["unplaced"]),
              released=[{"what": r.get("what"), "changed": r.get("changed")} for r in st.get("released") or []])
    return out


def exportable(engine):
    """DEXPI로 내보낼 수 있는 도면 목록(파일을 쓰지 않음). graph_id를 붙이고 이름은 웹에 보이는 도면 번호·이름만 둔다."""
    from hazop.export import dexpi_export
    names = {v: k for k, v in engine.graph_names().items()}
    rows = []
    for r in dexpi_export.list_exportable():
        gid = names.get(r["name"])
        if gid is None:
            continue
        rows.append({"graph_id": gid, "name": r["name"], "drawing_number": r.get("drawing_number"), "state": r.get("state"),
                     "unconfirmed": r.get("unconfirmed") or 0, "exportable": bool(r.get("exportable")), "why": list(r.get("why") or [])[:6]})
    return {"drawings": rows, "any": any(x["exportable"] for x in rows)}


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'sheetconf'(parts[1]=도면 ID) 또는 'dexpi'. 없는 자료는 None(404)."""
    api = _api()
    if parts[0] == "sheetconf" and len(parts) == 2:
        data = status(engine, parts[1])
        return api._json(data) if data is not None else None
    if parts[0] == "dexpi" and len(parts) == 1:
        return api._json(exportable(engine))
    if parts[0] == "sources" and len(parts) == 1:
        return api._json(source_conflicts(engine))
    return None


def source_conflicts(engine):
    """같은 도면 번호의 원본이 형식 둘 이상으로 들어온 것(hazop.graph.sources.conflicts). 읽기만 하고 파일을 쓰지 않는다.
    -> {"conflicts": [{"drawing_number", "graph_id", "formats", "in_use_format", "chosen", "candidates": [{"format", "modified"}]}]}.
    폴더 이름·경로는 싣지 않는다(형식 이름과 바뀐 시각만)."""
    import datetime
    from hazop.graph import sources
    rows = []
    for c in sources.conflicts(engine.project_id())[:MAX_ROWS]:
        rows.append({"drawing_number": c["drawing_number"], "graph_id": c["graph_id"], "formats": list(c["formats"]),
                     "in_use_format": c.get("in_use_format"), "chosen": c.get("chosen"),
                     "candidates": [{"format": x.get("format"),
                                     "modified": datetime.datetime.fromtimestamp(x["modified"]).strftime("%Y-%m-%d %H:%M")}
                                    for x in c["candidates"]]})
    return {"conflicts": rows}


# ---------------------------------------------------------------- 쓰기

def _by(engine):
    by = engine.reviewer()
    if not by:
        raise _api().CommandError("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 확정 기록에 남습니다.")
    return by


def _sheet_command(command):
    def handler(engine, a):
        api = _api()
        name = _name(engine, a["graph_id"])
        out = confirmation.execute(name, command, {k: a[k] for k in ("mode", "reason") if k in a}, _by(engine), a["ver"], a["rev"])
        if not out["ok"]:
            rows = out.get("refused") or [{"code": "failed", "reason": "처리하지 못했습니다."}]
            codes = {r.get("code") for r in rows}
            code = "stale" if codes & {"stale", "conflict"} else "bad_args" if "bad_actor" in codes else "failed"
            raise api.CommandError(code, "; ".join(str(r.get("reason")) for r in rows)[:600])
        if out["changed"]:
            engine.changed("sheetconf", None)
            engine.changed("drawings", None)
        data = status(engine, a["graph_id"])
        return {"changed": out["changed"], "status": data}
    return handler


def _choose_source(engine, a):
    """같은 도면 번호의 어느 형식 원본을 프로젝트 그래프에 쓸지 사람이 고른 것을 받는다(고른 사람은 설정의 검토자 이름)."""
    from hazop import store_io
    from hazop.graph import sources
    api = _api()
    try:
        record = sources.choose(engine.project_id(), a["drawing_number"], a["format"], _by(engine))
    except store_io.Conflict:
        raise api.CommandError("stale", "다른 곳에서 선택이 바뀌었습니다. 목록을 다시 읽었으니 한 번 더 골라 주세요.")
    except ValueError as exc:
        engine.changed("sources", None)
        raise api.CommandError("failed", str(exc)[:300])
    engine.changed("sources", None)
    engine.changed("drawings", None)
    return {"chosen": {"drawing_number": a["drawing_number"], "format": record["format"]}}


def _export(engine, a):
    from hazop.export import dexpi_export
    api = _api()
    by_gid = engine.graph_names()
    names = []
    for gid in a["graph_ids"]:
        if gid not in by_gid:
            raise api.CommandError("not_found", "없는 도면")
        names.append(by_gid[gid])
    rows = exportable(engine)
    if not any(r["exportable"] and r["name"] in names for r in rows["drawings"]):
        raise api.CommandError("failed", "확정된 쪽이 하나도 없어 내보낼 것이 없습니다. 도면에서 '쪽 확정'을 마친 쪽만 내보냅니다.")
    pick = engine.hooks.get("save_dir")
    if pick is None:
        raise api.CommandError("failed", "저장 위치를 고를 수 없습니다.")
    out_dir = pick("dexpi")
    if not out_dir:
        return {"cancelled": True}
    try:
        res = dexpi_export.export_names(names, out_dir)
        if res.get("status") == "exists":
            # 엔진이 쓸 파일이 이미 있다고 알려 준 경우에만 묻고, 확인을 받은 뒤에만 덮어쓴다(거절하면 아무것도 쓰지 않았다)
            confirm = engine.hooks.get("confirm_overwrite_files")
            if confirm is None or not confirm(list(res.get("existing") or [])):
                return {"cancelled": True, "overwrite_refused": True}
            res = dexpi_export.export_names(names, out_dir, overwrite=True)
    except dexpi_export.ExportError as exc:
        raise api.CommandError("failed", "\n".join(exc.reasons)[:900])
    except OSError as exc:
        raise api.CommandError("failed", "저장하지 못했습니다(%s)." % str(exc)[:160])
    to_gid = {v: k for k, v in by_gid.items()}
    return {"cancelled": False, "folder": os.path.basename(out_dir.rstrip("\\/")),
            "drawings": [{"graph_id": to_gid.get(d["name"]), "drawing_number": d.get("drawing_number"), "files": d["files"], "stats": d.get("stats") or {}}
                         for d in res["drawings"]],
            "not_exported": [{"graph_id": to_gid.get(x["name"]), "drawing_number": x.get("drawing_number"), "state": x.get("state"),
                              "unconfirmed": x.get("unconfirmed") or 0} for x in res["not_exported"]]}


def register(commands):
    api = _api()
    C, v_str, v_int, v_enum, v_list = api.Command, api.v_str, api.v_int, api.v_enum, api.v_list
    base = {"graph_id": (v_str(1, 200), True), "ver": (v_str(1, 100), True), "rev": (v_int(0, 10 ** 9), True)}

    def put(name, spec_, handler, doc):
        key = name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("sheet.compare", dict(base, mode=(v_enum("side_by_side", "overlay", "dexpi_list"), False)), _sheet_command("compare"),
        "'원본과 견줌' 기록(미확인 0·위치 없음 0일 때). 화면이 읽은 세 파일 지문과 기록 판을 함께 보낸다")
    put("sheet.confirm", dict(base), _sheet_command("confirm"), "이 쪽 확정(조건을 엔진이 센다, 확정자는 검토자 이름)")
    put("sheet.unconfirm", dict(base, reason=(v_str(0, 500), False)), _sheet_command("unconfirm"), "견줌·확정 취소")
    put("sources.choose", {"drawing_number": (v_str(1, 200), True), "format": (v_enum("drawio", "pdf_vector", "dexpi"), True)},
        _choose_source, "같은 도면 번호의 원본이 여러 형식일 때 프로젝트 그래프에 쓸 형식을 고른다(고르기 전에는 먼저 있던 형식)")
    put("dexpi.export", {"graph_ids": (v_list(v_str(1, 200), 200), True)}, _export,
        "확정된 쪽을 DEXPI XML로 내보낸다(저장 폴더는 창이 대화상자로 묻고, 덮어쓰면 확인한다)")
