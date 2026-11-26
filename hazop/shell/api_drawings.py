"""새 웹 화면의 도면 쪽 확정과 DEXPI 내보내기의 엔진 쪽(앱 틀 규격 §10.6·§10.7, DEXPI 규격 HZ-PLN-22 §6). Qt를 import하지 않는다.

- **쪽 확정 읽기** `sheetconf/<도면 ID>`: 엔진 함수 `confirmation.sheet_confirmation`의 답(상태·미확인·위치 없음·원본에 남은 것·견줌·확정·지문·판)을 그대로 돌려준다.
  화면은 조건을 다시 세지 않는다. 읽기는 파일을 쓰지 않는다.
- **쪽 확정 명령** `sheet.compare`·`sheet.confirm`·`sheet.unconfirm`: 화면이 읽은 세 파일 지문(`ver`)과 기록 판(`rev`)을 실어 보내고 어긋나면 stale로 거절한다. `by`는 설정의 검토자
  이름이고 `at`은 엔진이 채운다(웹 인자 아님). 조건을 못 채우면 엔진이 거절하고 사유(미확인 n곳·위치 없는 것·원본과 견줌 없음)를 그대로 올린다.
- **DEXPI 내보내기** `dexpi`(읽기: 내보낼 수 있는 도면 목록과 사유), `dexpi.export`(명령): 확정된 쪽만 낸다. 저장할 폴더는 창이 Python 쪽 대화상자로 묻고(웹은 경로를 보내지 않는다),
  이미 있는 파일을 덮어쓸 때는 확인을 받는다. 결과는 낸 도면(파일 이름만)과 뺀 목록(확정 안 된 쪽)과 도면별 뺀 항목 수로 보인다.
- 채팅 동작 층(hazop/chat/actions.py의 sheet.confirm·dexpi.export)은 hazop/shell/chat_actions.py가 이 모듈의 `_sheet_command`·`_export`를 불러 잇는다(쪽 확정은 확인 상자에서 본 지문·판을 그대로 넘긴다). 웹의 `dexpi.export`는 `_export`를 작업 스레드에서 돌린다(`_export_command`).
- **원본 선택** `sources`(읽기)·`sources.choose`(명령): 같은 도면 번호의 원본이 형식 둘 이상일 때 어느 형식을 쓸지 사람이 고른다(hazop.graph.sources).
"""

import logging
import os

from hazop.extract import confirmation
from hazop.shell import errtext

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


# ---------------------------------------------------------------- 사람용 도면 이름(시트 정체 U4)
_LABELS = {}


def labels(engine):
    """{graph_id: 도면 목록 한 줄 엔진 값(hazop.graph.sources.sheet_rows) + display(사람용 이름, sheets.display_name)}.
    셸이 도면을 부르는 모든 글(도면 목록·위 막대·구간·다음에 할 일·AI 검토·대기열)이 이 이름 하나를 쓴다(임시 이름·폴더 이름이 보이지 않게,
    한 화면에 두 이름이 섞이지 않게). 프로젝트 그래프 입력이 같으면 다시 읽지 않는다. 읽기만 한다(정착하지 않음)."""
    from hazop.app import project_ctx
    from hazop.graph import sheets, sources
    pid = engine.project_id()
    try:
        key = project_ctx._graph_inputs(pid)
    except (OSError, ValueError):
        key = None
    hit = _LABELS.get(pid)
    if hit is not None and key is not None and hit[0] == key:
        return hit[1]
    try:
        rows = sources.sheet_rows(pid)
    except (OSError, ValueError, KeyError):
        LOG.warning("도면 목록 이름을 읽지 못함", exc_info=True)
        rows = []
    out = {r["graph_id"]: dict(r, display=sheets.display_name(r), notice=_notice(r.get("notice"))) for r in rows if r.get("graph_id")}
    _LABELS[pid] = (key, out)
    return out


CONFIRM_FIRST_TEXT = ("도면 번호를 아직 확정하지 않았습니다. 표제란에서 번호를 확정하면 도면 연결·DEXPI 내보내기를 쓸 수 있습니다. "
                      "만들어 둔 구간·분석 결과는 바뀐 도면 이름을 따라갑니다.")


def _notice(n):
    """도면 목록 행 알림. 번호 미확정 알림은 시트 정체 U5 뒤의 사실로 고친다('구간을 만들기 전에 확정하세요'가 아님, 설계 §6 4)."""
    from hazop.graph import sheets
    if isinstance(n, dict) and n.get("code") == sheets.CONFIRM_FIRST:
        return dict(n, text=CONFIRM_FIRST_TEXT)
    return n


def display(engine, graph_id, rows=None):
    """한 도면의 사람용 이름. 목록에 없으면 graph-를 뗀 이름(임시 이름이면 '번호 미확정 도면')."""
    from hazop.graph import sheets
    row = (rows if rows is not None else labels(engine)).get(graph_id)
    return row["display"] if row else sheets.display_name({"graph_id": graph_id})


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
        return {"available": False, "reason": "쪽 자료를 읽을 수 없습니다(%s)." % errtext.why(exc, 120)}
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
        rows.append({"graph_id": gid, "name": r["name"], "display": display(engine, gid), "drawing_number": r.get("drawing_number"), "state": r.get("state"), "level": r.get("level"),
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


FORMAT_WORD = {"drawio": "drawio 파일", "pdf_vector": "PDF 파일", "dexpi": "DEXPI 파일"}


def _format_word(fmt):
    return FORMAT_WORD.get(fmt or "", "형식을 모르는 파일")


def conflict_text(c, shown):
    """원본 고르기 줄의 사람용 글(실제 창 3차 D). 엔진 글(hazop.graph.sources.REASONS)은 형식 코드·폴더 이름을 실어 화면에 그대로 쓰지 않는다.
    c는 sources.conflicts 한 줄, shown은 사람용 도면 이름(display)."""
    using = c.get("in_use_file") or _format_word(c.get("in_use_format"))
    if c.get("in_use_file") and c.get("in_use_format"):
        using = "%s(%s)" % (c["in_use_file"], _format_word(c["in_use_format"]))
    reason = c.get("reason")
    if reason == "same_number_other_format":
        kinds = "과 ".join(_format_word(f) for f in c.get("formats") or [])      # 말이 모두 '파일'로 끝나 '과'(실제 창 4차 조사 오류)
        return "같은 도면 번호 %s의 원본이 %s로 함께 있습니다. 사람이 고르기 전에는 %s을(를) 씁니다." % (shown, kinds, using)
    if reason == "same_number_other_file":
        return "같은 도면 번호 %s의 다른 파일이 들어왔습니다. 쓸 파일을 고르세요. 사람이 고르기 전에는 %s을(를) 씁니다." % (shown, using)
    if reason == "same_name_before_settle":
        return "번호가 없는 도면 %d장이 한 자리를 나눠 써서 %s만 보입니다. 다음 추출 때 도면마다 따로 들어옵니다." % (len(c.get("candidates") or []), using)
    if reason == "settle_rebuild_failed":
        stuck = [x.get("file") for x in c.get("candidates") or [] if not x.get("in_use") and x.get("file")]
        return "가려졌던 도면 %s을(를) 다시 읽지 못해 %s만 보입니다. 그 도면을 다시 추출하면 따로 들어옵니다." % ("·".join(stuck) or "한 장", using)
    return c.get("text")


def source_conflicts(engine):
    """같은 시트 자리에 고를 원본이 둘 이상인 것(hazop.graph.sources.conflicts). 읽기만 하고 파일을 쓰지 않는다.
    -> {"conflicts": [{"kind": format|file, "reason", "text", "display", "drawing_number", "graph_id", "formats", "in_use_format",
         "in_use_material", "in_use_file", "chosen", "chosen_material", "nodes_on_sheet"(지금 이 도면 구성요소를 품은 구간 수: 갈아타기 미리 알림),
         "candidates": [{"material_id", "file"(원본 파일 이름), "format", "modified", "in_use"}]}]}.
    폴더 이름·경로는 싣지 않는다(원본 파일 이름·형식·바뀐 시각만)."""
    import datetime
    from hazop.graph import sources
    rows = []
    found = sources.conflicts(engine.project_id())[:MAX_ROWS]
    held = _nodes_on(engine, [c["graph_id"] for c in found]) if found else {}
    firm = _confirmed_on(engine, [c["graph_id"] for c in found]) if found else {}
    unknown = held is None or firm is None          # 구간 파일을 읽지 못함: 0으로 안심시키지 않고 '알 수 없음'으로 보인다(검토 ⑥ 나)
    held, firm = held or {}, firm or {}
    lb = labels(engine) if found else {}
    for c in found:
        shown = display(engine, c["graph_id"], lb)
        rows.append({"kind": c.get("kind") or "format", "reason": c.get("reason"), "text": conflict_text(c, shown), "display": shown,
                     "drawing_number": c["drawing_number"], "graph_id": c["graph_id"], "formats": list(c["formats"]),
                     "in_use_format": c.get("in_use_format"), "in_use_material": c.get("in_use_material"), "in_use_file": c.get("in_use_file"),
                     "chosen": c.get("chosen"), "chosen_material": c.get("chosen_material"), "nodes_on_sheet": held.get(c["graph_id"], 0),
                     "confirmed_on_sheet": firm.get(c["graph_id"], 0), "nodes_unknown": unknown,
                     "candidates": [{"material_id": x.get("material_id"), "file": x.get("file"), "format": x.get("format"),
                                     "in_use": bool(x.get("in_use")),
                                     # 이 후보로 바꾸면 다시 확인할 구간 수(지금 쓰는 파일이면 바뀌는 것이 없어 0, 검토 지적 3)
                                     "recheck": 0 if x.get("in_use") else None if unknown else held.get(c["graph_id"], 0),
                                     "released": 0 if x.get("in_use") else None if unknown else firm.get(c["graph_id"], 0),       # 바꾸면 확정이 풀리는 구간 수
                                     "modified": datetime.datetime.fromtimestamp(x["modified"]).strftime("%Y-%m-%d %H:%M") if x.get("modified") else None}
                                    for x in c["candidates"]]})
    return {"conflicts": rows}


def _nodes_on(engine, graph_ids):
    """{graph_id: 그 도면 구성요소를 품은 구간 수}(갈아타기 전 미리 알림). 프로젝트 그래프가 아직 없으면 {}(구간도 없음),
    구간 파일을 읽지 못하면 None(영향을 알 수 없음: 0으로 안심시키지 않는다)."""
    from hazop.shell import api_nodes
    from hazop.study import node_commands
    pg = api_nodes._pg(engine, strict=False)
    if pg is None:
        return {}
    try:
        ns, _legacy = api_nodes._peek(pg)
    except Exception:  # noqa: BLE001 - 미리 알림의 수다: 못 읽으면 '알 수 없음'(None)
        return None
    return {g: len(node_commands.drawing_nodes(pg, ns, g)) for g in graph_ids}


def _confirmed_on(engine, graph_ids):
    """{graph_id: 그 도면 구성요소를 품은 구간 가운데 확정·잠금한 수}: 원본을 바꾸면 그 확정이 풀린다(실제 창 4차, 미리 알림)."""
    from hazop.shell import api_nodes
    from hazop.study import node_commands, nodes
    pg = api_nodes._pg(engine, strict=False)
    if pg is None:
        return {}
    try:
        ns, _legacy = api_nodes._peek(pg)
    except Exception:  # noqa: BLE001 - 미리 알림의 수다: 못 읽으면 '알 수 없음'(None)
        return None
    state = {n["node_id"]: nodes.node_state(n) for n in (ns or {}).get("nodes") or []}
    return {g: sum(1 for x in node_commands.drawing_nodes(pg, ns, g) if state.get(x["node_id"]) != "applied") for g in graph_ids}


def choose_impact(engine, conflict, fmt=None, material_id=None):
    """채팅 확인 상자의 미리 알림 수(웹 카드와 같은 셈): {"recheck": n 또는 None, "released": n 또는 None}. None은 구간 파일을
    읽지 못해 알 수 없음. 지금 쓰는 원본을 고르면 바뀌는 것이 없어 0."""
    same = (material_id and material_id == conflict.get("in_use_material")) or (not material_id and fmt and fmt == conflict.get("in_use_format"))
    if same:
        return {"recheck": 0, "released": 0}
    g = conflict.get("graph_id")
    held, firm = _nodes_on(engine, [g]), _confirmed_on(engine, [g])
    return {"recheck": None if held is None else held.get(g, 0), "released": None if firm is None else firm.get(g, 0)}


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
        if not a.get("format") and not a.get("material_id"):
            raise api.CommandError("bad_args", "쓸 형식이나 파일을 골라 주세요.")
        record = sources.choose(engine.project_id(), a["drawing_number"], a.get("format"), _by(engine), material_id=a.get("material_id"))
    except store_io.Conflict:
        raise api.CommandError("stale", "다른 곳에서 선택이 바뀌었습니다. 목록을 다시 읽었으니 한 번 더 골라 주세요.")
    except ValueError as exc:
        engine.changed("sources", None)
        raise api.CommandError("failed", errtext.why(exc, 300))
    from hazop.app import data
    data.notify_graph_changed(engine.project_id())      # 쓸 원본이 바뀌면 프로젝트 그래프 판도 바뀐다: 검토구간을 이어서 맞춘다
    engine.changed("sources", None)
    engine.changed("drawings", None)
    applied = _applied(engine)
    out = {"chosen": {"drawing_number": a["drawing_number"], "format": record.get("format"), "material_id": record.get("material_id")},
           "applied": applied}
    if not applied:      # 고르기는 저장했지만 검토구간에 반영하지 못함(검토 지적 2): 화면이 '도면 변경 반영하기' 안전망을 보인다
        out["apply_text"] = APPLY_FAILED_TEXT
    return out


APPLY_FAILED_TEXT = ("쓸 파일은 바꿨지만 검토구간에 도면 변경을 반영하지 못했습니다. '도면 변경 반영하기'를 눌러 다시 맞추세요. "
                     "그 전까지 구간 고치기와 분석은 막혀 있습니다.")


def _applied(engine):
    """고른 뒤 검토구간이 지금 그래프에 맞춰졌는가. AI 작업이 끝나기를 기다리는 자동 반영(catching)은 실패가 아니다.
    읽지 못하면 True(알 수 없음을 실패로 알리지 않음)."""
    from hazop.shell import api_nodes
    try:
        s = api_nodes.summary(engine)
    except Exception:  # noqa: BLE001
        return True
    return not (s.get("available") and s.get("stale")) or engine.catching(engine.project_id())


def _export(engine, a):
    from hazop.export import dexpi_export
    api = _api()
    by_gid = engine.graph_names()
    names = []
    for gid in a["graph_ids"]:
        if gid not in by_gid:
            raise api.CommandError("not_found", "없는 도면")
        names.append(by_gid[gid])
    if not names:
        raise api.CommandError("failed", "내보낼 도면이 없습니다.")
    # 못 내는 쪽(확정이 안 됐거나 번호가 확정되지 않은 쪽)을 미리 빼지 않는다: 엔진이 쪽마다 수준·까닭을 not_exported에 적고 나머지는 낸다.
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
        # 엔진의 사유는 내부 이름으로 적혀 있다: 화면에는 사람용 도면 이름과 쪽별 사유로 다시 쓴다
        lines = ["%s: %s" % (r["display"], (r.get("why") or ["내보낼 수 없음"])[0]) for r in exportable(engine)["drawings"] if r["name"] in names and not r["exportable"]]
        raise api.CommandError("failed", ("내보낼 수 있는 쪽이 없습니다.\n" + "\n".join(lines[:12]))[:700] if lines else "\n".join(exc.reasons)[:900])
    except OSError as exc:
        raise api.CommandError("failed", "저장하지 못했습니다(%s)." % errtext.why(exc, 160))
    to_gid = {v: k for k, v in by_gid.items()}
    lb = labels(engine)
    not_exported = [{"graph_id": to_gid.get(x["name"]), "display": display(engine, to_gid.get(x["name"]), lb), "drawing_number": x.get("drawing_number"), "state": x.get("state"),
                     "level": x.get("level"), "code": x.get("code"), "unconfirmed": x.get("unconfirmed") or 0, "reason": x.get("reason")} for x in res["not_exported"]]
    return {"cancelled": False, "folder": os.path.basename(out_dir.rstrip("\\/")),
            "drawings": [{"graph_id": to_gid.get(d["name"]), "display": display(engine, to_gid.get(d["name"]), lb), "drawing_number": d.get("drawing_number"), "files": d["files"], "stats": d.get("stats") or {},
                          "state": d.get("state"), "level": d.get("level"), "unconfirmed": d.get("unconfirmed") or 0, "auto_accepted": d.get("auto_accepted") or 0,
                          "graph_rebuilt": bool(d.get("graph_rebuilt"))} for d in res["drawings"]],
            "not_exported": not_exported, "stale_files": list(res.get("stale_files") or []), "stale_reason": res.get("stale_reason")}


def _export_command(engine, a):
    """웹의 dexpi.export: 없는 도면만 먼저 가려내고 내보내기(그래프를 확정한 세 파일로 짓고 XML을 쓰는 일)는 작업 스레드에서 한다.
    저장 폴더 고르기와 덮어쓰기 확인은 창이 화면 스레드로 넘겨 묻는다. 결과는 job.done의 result(_export의 답)로, 실패는 job.failed로 온다."""
    api = _api()
    by_gid = engine.graph_names()
    for gid in a["graph_ids"]:
        if gid not in by_gid:
            raise api.CommandError("not_found", "없는 도면")
    return {"job": engine.start_job("DEXPI 내보내기", lambda progress: _export(engine, a), kind="export")}


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
    put("sources.choose", {"drawing_number": (v_str(1, 200), True), "format": (v_enum("drawio", "pdf_vector", "dexpi"), False),
                           "material_id": (v_str(1, 120), False)},
        _choose_source, "같은 시트 자리에 원본이 둘 이상일 때 프로젝트 그래프에 쓸 형식(format) 또는 파일(material_id)을 고른다. drawing_number는 번호나 graph_id. "
                        "갈아타면 검토구간을 이어서 맞추고(자동 반영), 잃은 것이 있으면 알림이 간다")
    put("dexpi.export", {"graph_ids": (v_list(v_str(1, 200), 200), True)}, _export_command,
        "확정된 쪽을 DEXPI XML로 내보낸다(저장 폴더는 창이 대화상자로 묻고, 덮어쓰면 확인한다)")
