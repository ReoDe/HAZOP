"""새 웹 화면 3단계 ⑤ 분석 결과의 엔진 쪽(docs/design/app-shell-web.md §2.1·§2.3 ⑤·§5.3·§5.4). Qt를 import하지 않는다.

- **읽기** `results`(요약: 구간×편차 행렬·머리 수치·판 지문), `results/cell/<구간>/<편차>`(칸 하나의 워크시트), `results/recs`(권고 목록),
  `results/trace?entity=<ID>`(구성요소 -> 소속 구간 -> 칸 -> 권고, INTENT §3.6). 읽기는 파일을 하나도 쓰지 않는다(load_view).
- **명령** `results.*`: 판정(수용·수정·기각·보류, 사유 필수 규칙은 엔진이 지킨다), 항목 고치기, 범위 바뀜 확인, Excel·초기사건 인계 묶음 내보내기,
  분석 실행·멈춤. 쓰기 명령은 화면이 읽은 **결과 파일 지문(`ver`)**을 들고 가고 `by`·`at`은 Python 쪽이 채운다(웹 인자 아님).
  판정 규칙은 hazop.study.result_commands(e32042a)를 그대로 부른다.
- 내보내기 위치는 웹이 보내지 않는다: 창이 저장 대화상자를 연다(engine.hooks["save_path"]).
"""

import json
import logging
import os

from hazop.analysis.risk import FREQUENCIES, SEVERITIES
from hazop.study import nodes
from hazop.study import result_commands
from hazop.study import results as res

LOG = logging.getLogger("hazop.shell.api_results")
INT_MAX = 10 ** 9
STATUS_COUNTS = ("proposed", "revised", "approved", "rejected", "on_hold")


def _api():
    from hazop.shell import api
    return api


def _pg(engine, strict=True):
    from hazop.app import project_ctx
    try:
        return project_ctx.project_graph(engine.project_id())
    except (OSError, ValueError, KeyError):
        if strict:
            raise _api().CommandError("failed", "프로젝트 그래프를 만들 수 없습니다. 도면을 먼저 추출하세요.")
        return None


def _node_set(pg):
    """저장본을 읽기만 한다(파일을 바꾸지 않음). (집합, 옛 판 여부)."""
    doc = nodes.read_as_is(pg)
    if doc is None:
        return nodes.new_set(pg), False
    if (doc.get("schema_version") or nodes.LEGACY_SCHEMA_VERSION) == nodes.LEGACY_SCHEMA_VERSION:
        return nodes.new_set(pg), True
    return doc, False


def _load(ns):
    """(결과 문서, 지문). 파일이 없으면 빈 결과와 None. 읽기 전용(원본 보관·변환 저장 없음)."""
    devs = res.load_deviations()
    doc, fp = res.load_fp(ns, devs)        # 공개 읽기: 파일을 쓰지 않고 지문까지 돌려준다
    if doc is None:
        return res.empty_results(ns, devs), None
    return doc, fp


def _ver(fp):
    return fp or "none"


def _screen_status(n):
    return ((n or {}).get("screen") or {}).get("status") or "keep"


def scope_rows(ns):
    """행렬 행이 되는 구간 = 이전 화면(results.py _rows)과 같은 규칙: 확정·잠금 구간만, 스크리닝 제외는 뺀다, 낮음은 맨 아래."""
    shown = [n for n in ns["nodes"] if _screen_status(n) != "excluded" and nodes.is_active(n)]
    return [n for n in shown if _screen_status(n) != "low"] + [n for n in shown if _screen_status(n) == "low"]


def scope_set(ns):
    """AI 일괄·Excel·권고의 범위 = 행렬 행과 같은 구간(이전 화면 _scope_set)."""
    return dict(ns, nodes=scope_rows(ns))


def check_version(ns, ver):
    """화면이 읽은 결과 파일 지문(ver)과 지금 파일을 맞춘다. 'none'은 '파일이 없었다'는 뜻이라 지금 파일이 있으면 다르다(없던 것이 생겨도 다름, 규격 §5.3)."""
    _doc, fp = res.load_fp(ns)
    if (ver == "none") != (fp is None) or (fp is not None and ver != fp):
        raise _api().CommandError("stale", "분석 결과가 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요.")


_EN_CACHE = {}


def deviation_names_en():
    """{item_id: {guideword_en, label_en}} KOSHA P-86 이탈후보표의 영문. 표를 못 읽으면 빈 사전(화면은 한국어만 보인다)."""
    if "v" not in _EN_CACHE:
        import json
        from hazop import paths
        try:
            with open(paths.folder("deviations", res.DEVIATION_CHART), encoding="utf-8") as fh:
                items = json.load(fh).get("items") or []
        except (OSError, ValueError):
            return {}
        _EN_CACHE["v"] = {i["item_id"]: {"guideword_en": (i.get("guide_word_en") or "").strip(),
                                         "label_en": (i.get("deviation_en") or "").strip()}
                          for i in items if i.get("item_id")}
    return _EN_CACHE["v"]


def _dev_with_en(d, en):
    n = en.get(d.get("item_id")) or {}
    return dict(d, guideword_en=n.get("guideword_en", ""), label_en=n.get("label_en", ""))


KIND_DEFAULT_REASON = {"not_applicable": "AI가 이 구간에는 해당하지 않는다고 판단했습니다(이유를 적지 않음).",
                       "no_scenario": "AI가 분석했으나 시나리오가 나오지 않았습니다.",
                       "failed": "AI 실행이 실패했습니다.", "excluded": "제외한 칸입니다."}


def cell_kind(cell):
    """행렬에서 '아직 분석 안 함'과 구분해 보일 칸 종류. 없으면 None (항목이 있거나 아직 분석 전).
    Excel 칸 표시 행과 같은 규칙(study_xlsx._cell_kind)으로 하되, 하나만 고른다."""
    run = cell.get("ai_run") or {}
    if run.get("status") == "failed":
        return "failed"
    if cell["state"] == "excluded":
        return "excluded"
    if cell["state"] == "analyzed" and not cell["entries"]:
        return "not_applicable" if run.get("applicable") is False else "no_scenario"
    return None


def cell_reason(cell, kind):
    run = cell.get("ai_run") or {}
    text = run.get("error") if kind == "failed" else run.get("note")
    return (text.strip() if isinstance(text, str) else "") or KIND_DEFAULT_REASON[kind]


def _mark_kinds(matrix, cells):
    """matrix_summary의 칸에 kind·reason을 더한다(키만 더함). 해당이 없는 칸(대부분)에는 키를 붙이지 않아 크기를 키우지 않는다."""
    for c in cells:
        kind = cell_kind(c)
        if kind:
            matrix[c["node_id"]][c["deviation_id"]].update(kind=kind, reason=cell_reason(c, kind))
    return matrix


def _entry_view(e):
    return dict(e, verdict=res.verdict(e))


def _rec_rows(doc, ns, only_node=None):
    by_node = {n["node_id"]: n for n in scope_rows(ns)}
    labels = {d["deviation_id"]: d.get("label") or d["deviation_id"] for d in doc.get("deviations") or []}
    rows = []
    for cell in doc["cells"]:
        if (only_node and cell["node_id"] != only_node) or cell["node_id"] not in by_node:
            continue
        for e in cell["entries"]:
            text = (e.get("recommendation") or "").strip() if isinstance(e.get("recommendation"), str) else ""
            if not text or e.get("status") == "rejected":
                continue
            rows.append({"node_id": cell["node_id"], "node_name": (by_node.get(cell["node_id"]) or {}).get("name"),
                         "deviation_id": cell["deviation_id"], "deviation": labels.get(cell["deviation_id"]), "entry_id": e.get("entry_id"),
                         "text": text, "status": e.get("status"), "risk": e.get("risk")})
    rows.sort(key=lambda r: (-(r["risk"] or 0), r["node_id"], r["deviation_id"]))
    return rows


# ---------------------------------------------------------------- 읽기

def summary(engine):
    pg = _pg(engine, strict=False)
    if pg is None:
        return {"available": False, "reason": "프로젝트 그래프가 없습니다. 도면을 먼저 추출하세요."}
    ns, legacy = _node_set(pg)
    active = scope_rows(ns)
    base = {"available": True, "legacy": legacy, "set_rev": ns.get("set_rev") or 0}
    if legacy or not active:
        return dict(base, empty=True, nodes=[], deviations=[], matrix={}, ver="none", kpi=_kpi(None),
                    reason="옛 판 구간 파일입니다. 구간 패널에서 새 판으로 바꾸세요." if legacy else "확정한 구간이 아직 없습니다.")
    try:
        doc, fp = _load(ns)
    except (OSError, ValueError) as exc:
        return dict(base, empty=True, nodes=[], deviations=[], matrix={}, ver="none", kpi=_kpi(None),
                    reason="분석 결과 파일을 읽을 수 없습니다(%s)." % str(exc)[:120])
    from hazop.shell import api_nodes
    info = api_nodes._span_info(ns, pg)
    rows = [{"node_id": n["node_id"], "name": n.get("name"), "state": nodes.node_state(n), "rev": n.get("rev") or 1,
             "range": (info.get(n["node_id"]) or {}).get("range"), "spans": bool((info.get(n["node_id"]) or {}).get("spans"))} for n in active]
    en = deviation_names_en()
    return dict(base, empty=False, nodes=rows, deviations=[{"deviation_id": d["deviation_id"], "parameter": d["parameter"],
                                                             "guideword": d["guideword"], "label": d.get("label"),
                                                             "guideword_en": _dev_with_en(d, en)["guideword_en"],
                                                             "label_en": _dev_with_en(d, en)["label_en"]} for d in doc["deviations"]],
                matrix=_mark_kinds(res.matrix_summary(doc), doc["cells"]), ver=_ver(fp), read_only=doc.get("read_only"), kpi=_kpi(doc),
                run=_run_state(engine))


def _kpi(doc):
    out = {"cells": 0, "analyzed": 0, "entries": 0, "recs": 0, "unreviewed": 0, "approved": 0, "rejected": 0, "on_hold": 0, "revised": 0,
           "proposed": 0, "failed_cells": 0, "usage": None}
    if doc is None:
        return out
    for cell in doc["cells"]:
        out["cells"] += 1
        out["analyzed"] += cell["state"] == "analyzed"
        out["failed_cells"] += (cell.get("ai_run") or {}).get("status") == "failed"
        for e in cell["entries"]:
            out["entries"] += 1
            st = e.get("status")
            if st in STATUS_COUNTS:
                out[st] += 1
            if st in res.UNDECIDED_STATUSES or (res.is_ai_draft(e) and st != "rejected"):
                out["unreviewed"] += 1
            if st != "rejected" and isinstance(e.get("recommendation"), str) and e["recommendation"].strip():
                out["recs"] += 1
    try:
        from hazop.study import ai_cells
        out["usage"] = ai_cells.usage_total(doc)
    except Exception:  # noqa: BLE001 - 사용량 집계가 틀어져도 표는 보인다
        out["usage"] = None
    return out


def cells_delta(doc, ur, fp):
    """호출 하나가 바꾼 칸의 요약만(525구간 행렬 전체 1.9MB를 호출마다 다시 읽지 않게). 머리 수치와 새 판 지문을 함께 준다."""
    wanted = set(ur["cells"])
    cells = {}
    for c in doc["cells"]:
        if c["node_id"] == ur["node_id"] and c["deviation_id"] in wanted:
            cells[c["deviation_id"]] = _mark_kinds(res.matrix_summary({"cells": [c]}), [c])[c["node_id"]][c["deviation_id"]]
    return {"node_id": ur["node_id"], "cells": cells, "kpi": _kpi(doc), "ver": _ver(fp)}


def _run_state(engine):
    run = getattr(engine, "analysis", None)
    return run.snapshot() if run is not None else {"running": False}


def cell_view(engine, node_id, deviation_id):
    pg = _pg(engine, strict=False)
    if pg is None:
        return None
    ns, _legacy = _node_set(pg)
    doc, fp = _load(ns)
    cell = next((c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == (node_id, deviation_id)), None)
    if cell is None:
        return None
    node = next((n for n in ns["nodes"] if n["node_id"] == node_id), {})
    dev = _dev_with_en(next((d for d in doc["deviations"] if d["deviation_id"] == deviation_id), {}), deviation_names_en())
    cell = dict(cell, entries=[_entry_view(e) for e in cell["entries"]])
    problem = res.editable_problem(doc, node_id, deviation_id, ns)
    return {"cell": cell, "node": {"node_id": node_id, "name": node.get("name"), "state": nodes.node_state(node) if node else None},
            "deviation": dev, "editable": problem is None, "not_editable_reason": problem, "ver": _ver(fp),
            "cause_kinds": res.CAUSE_KINDS, "read_only": doc.get("read_only"),
            "severities": list(SEVERITIES), "frequencies": list(FREQUENCIES)}


def _entities(pg, query):
    """추적을 시작할 프로젝트 구성요소 ID와 보일 이름. query: entity(프로젝트 ID 또는 태그) 또는 sheet+local(도면에서 누른 구성요소)."""
    from hazop.chat import view as chatview
    by_id = {n.get("entity_id"): n for n in pg.get("nodes") or [] if n.get("entity_id")}
    if query.get("sheet") and query.get("local"):
        ids = chatview.lift(pg, query["sheet"], [query["local"]])
    else:
        ent = (query.get("entity") or "").strip()
        if ent in by_id:
            ids = [ent]
        else:                                                        # 태그로도 찾는다(같은 태그가 여럿이면 모두)
            low = ent.lower()
            ids = [i for i, n in by_id.items() if low and str(n.get("tag") or "").lower() == low]
    label = ", ".join(sorted({str((by_id.get(i) or {}).get("tag") or i) for i in ids}))
    return ids, label or (query.get("entity") or "")


def trace(engine, query):
    pg = _pg(engine, strict=False)
    if pg is None or not (query.get("entity") or (query.get("sheet") and query.get("local"))):
        return {"entity": (query or {}).get("entity", ""), "entities": [], "nodes": []}
    ids, label = _entities(pg, query)
    ns, _legacy = _node_set(pg)
    doc, _fp = _load(ns)
    out = []
    for n in scope_rows(ns):
        if not set(ids) & set(n.get("members") or []):
            continue
        cells = {}
        for r in _rec_rows(doc, ns, only_node=n["node_id"]):
            cells.setdefault(r["deviation_id"], {"deviation_id": r["deviation_id"], "deviation": r["deviation"], "recs": []})["recs"].append(r)
        out.append({"node_id": n["node_id"], "name": n.get("name"), "state": nodes.node_state(n), "cells": list(cells.values())})
    return {"entity": label, "entities": ids, "nodes": out}


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'results'. 없는 자료는 None(404)."""
    api = _api()
    if len(parts) == 1:
        return api._json(summary(engine))
    if len(parts) == 4 and parts[1] == "cell":
        data = cell_view(engine, parts[2], parts[3])
        return api._json(data) if data is not None else None
    if len(parts) == 2 and parts[1] == "run":
        return api._json(_run_state(engine))
    if len(parts) == 2 and parts[1] == "recs":
        pg = _pg(engine, strict=False)
        if pg is None:
            return api._json({"recs": []})
        ns, _l = _node_set(pg)
        doc, _fp = _load(ns)
        return api._json({"recs": _rec_rows(doc, ns)})
    if len(parts) == 2 and parts[1] == "trace":
        return api._json(trace(engine, dict(query or {})))
    return None


# ---------------------------------------------------------------- 쓰기

def _need_reviewer(engine):
    by = engine.reviewer()
    if not by:
        raise _api().CommandError("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 판정 기록에 남습니다.")
    return by


def _after(engine, out, name):
    """엔진 답(result_commands) -> 웹 답. 거절이면 사유를 그대로 올린다. 지문이 어긋난 것은 stale."""
    api = _api()
    if not out["ok"]:
        refused = out.get("refused") or [{"target": "", "reason": "처리하지 못했습니다."}]
        text = "; ".join(str(r.get("reason") or "") for r in refused)[:300]
        codes = {r.get("code") for r in refused}
        code = ("stale" if codes & {"stale", "conflict"} else "locked" if "read_only" in codes or "잠긴" in text or "보관" in text else "failed")
        raise api.CommandError(code, text)
    engine.changed("results", None)
    return out


def _execute(engine, name, a, writes=True):
    pg = _pg(engine)
    ns, legacy = _node_set(pg)
    if legacy:
        raise _api().CommandError("failed", "옛 판(0.1) 구간 파일입니다. 구간 패널에서 새 판으로 바꾸세요.")
    by = _need_reviewer(engine) if writes else engine.reviewer()
    ver = a.get("ver")
    if writes:
        check_version(ns, ver)
    args = {k: v for k, v in a.items() if k not in ("ver", "set_rev")}
    out = result_commands.execute(pg, name, args, by, None if ver in (None, "none") else ver, set_rev=a.get("set_rev"))
    return _after(engine, out, name), ns, pg


def _set_status(engine, a):
    out, _ns, _pg_ = _execute(engine, "set_status", a)
    return {"ver": out["fingerprint"] or "none"}


def _edit_entry(engine, a):
    out, _ns, _pg_ = _execute(engine, "edit_entry", a)
    return {"ver": out["fingerprint"] or "none"}


def _recheck(engine, a):
    out, _ns, _pg_ = _execute(engine, "recheck_cell", a)
    return {"ver": out["fingerprint"] or "none"}


def _save_path(engine, kind, default_name):
    hook = engine.hooks.get("save_path")
    if hook is None:
        raise _api().CommandError("failed", "저장 위치를 고를 수 없습니다.")
    path = hook(kind, default_name)
    return path or None


def _export_excel(engine, a):
    from hazop.export import study_xlsx
    pg = _pg(engine)
    ns, legacy = _node_set(pg)
    if legacy:
        raise _api().CommandError("failed", "옛 판(0.1) 구간 파일입니다. 구간 패널에서 새 판으로 바꾸세요.")
    doc, _fp = _load(ns)
    now = nodes.now_utc()
    path = _save_path(engine, "excel", study_xlsx.default_filename(ns.get("project_id"), now))
    if not path:
        return {"cancelled": True}
    if not path.lower().endswith(".xlsx"):
        path += ".xlsx"
    scope = a.get("scope") or "all"
    node_ids = a.get("node_ids") or None
    inputs = excel_inputs(ns, pg)
    try:
        path, rows = study_xlsx.export(path, doc, scope_set(ns), pg, doc["deviations"], scope=scope, node_ids=node_ids,
                                       reviewer=engine.reviewer() or "", intents=inputs["intents"], now=now, expectations=inputs["expectations"])
    except (OSError, ValueError) as exc:
        raise _api().CommandError("failed", "저장하지 못했습니다(파일이 열려 있으면 닫고 다시 하세요). %s" % str(exc)[:200])
    return {"path": os.path.basename(path), "rows": rows, "cancelled": False}


def excel_inputs(ns, pg):
    """이전 화면의 export_excel과 같은 보조 입력(구간 설계 의도, 잠재 후보)을 만든다 -> 같은 입력이면 같은 Excel이 나온다."""
    from hazop.study import ai_cells, node_review
    from hazop.shell import analysis_run
    review = None
    try:
        review = node_review.load(ns.get("project_id"), ns["graph_id"])
    except (OSError, ValueError):
        review = None
    intents = {}
    for n in ns["nodes"]:
        found = analysis_run.intent_text(n, review)
        if found:
            intents[n["node_id"]] = found[0]
    kg, _reason = ai_cells.load_kg_for(ns)
    expectations, _note = ai_cells.expectations_for(pg, kg)
    return {"intents": intents, "expectations": expectations}


def _export_ie(engine, a):
    pg = _pg(engine)
    ns, legacy = _node_set(pg)
    if legacy:
        raise _api().CommandError("failed", "옛 판(0.1) 구간 파일입니다. 구간 패널에서 새 판으로 바꾸세요.")
    from hazop.ie import bundle_xlsx
    path = _save_path(engine, "ie", bundle_xlsx.default_stem(ns.get("project_id"), nodes.now_utc()) + ".xlsx")
    if not path:
        return {"cancelled": True}
    if not path.lower().endswith(".xlsx"):
        path += ".xlsx"
    out = result_commands.execute(pg, "export_ie_bundle", {"path": path}, engine.reviewer(), None)
    if not out["ok"]:
        raise _api().CommandError("failed", "; ".join(str(r.get("reason")) for r in out["refused"])[:300])
    return {"path": os.path.basename(out["path"]), "candidates": out["candidates"], "cancelled": False}


# ---------------------------------------------------------------- 분석 실행·멈춤

class AnalysisRun:
    """분석 실행 하나의 상태(웹이 머리에 보인다)와 멈춤 표시."""

    def __init__(self):
        self.running = False
        self.stop = False
        self.done = 0
        self.total = 0
        self.text = ""
        self.last = None       # 끝난 실행의 요약(한도·실패 안내)

    def snapshot(self):
        return {"running": self.running, "stopping": self.running and self.stop, "done": self.done, "total": self.total, "text": self.text,
                "last": self.last}


def _plan(engine, a):
    from hazop.shell import analysis_run
    pg = _pg(engine)
    ns, legacy = _node_set(pg)
    if legacy:
        raise _api().CommandError("failed", "옛 판(0.1) 구간 파일입니다. 구간 패널에서 새 판으로 바꾸세요.")
    doc, _fp = _load(ns)
    ns = scope_set(ns)                       # 스크리닝 제외 구간은 호출·요금에 들어가지 않는다
    units = analysis_run.plan(ns, doc, a["scope"], a.get("node_id"), a.get("deviation_id"))
    return pg, ns, doc, units


def _run_plan(engine, a):
    from hazop.shell import analysis_run
    _pg_, _ns, _doc, units = _plan(engine, a)
    ai = engine.ai
    status = ai.status() if ai is not None else {}
    terms = bool(getattr(ai, "terms_acked", lambda: True)()) if ai is not None else True
    s = analysis_run.summarize(units)
    return dict(s, can_start=bool(status.get("can_start")) and bool(units), state=status.get("label") or "", guide=status.get("guide") or "",
                needs_terms=not terms, running=_run_state(engine)["running"],
                empty_text=None if units else {"node": "분석할 구간의 행을 고르세요(확정한 구간만 분석합니다).",
                                              "failed": "다시 실행할 실패 칸이 없습니다.", "cell": "분석할 칸이 없습니다."}.get(a["scope"], "분석할 칸이 없습니다."))


def _ack_terms(engine, a):
    ai = engine.ai
    if ai is None or not hasattr(ai, "ack_terms"):
        raise _api().CommandError("failed", "이용 조건을 기록할 수 없습니다.")
    ai.ack_terms()
    return {}


def _run(engine, a):
    from hazop.shell import analysis_run
    api = _api()
    if engine.analysis.running:
        raise api.CommandError("busy", "분석이 이미 돌고 있습니다.")
    _need_reviewer(engine)
    pg, ns, _doc, units = _plan(engine, a)
    if not units:
        raise api.CommandError("bad_args", "분석할 칸이 없습니다.")
    ai = engine.ai
    status = ai.status() if ai is not None else {}
    if not status.get("can_start"):
        raise api.CommandError("failed", status.get("guide") or "AI 연결을 쓸 수 없어 분석을 시작하지 않았습니다.")
    if ai is not None and hasattr(ai, "terms_acked") and not ai.terms_acked():
        raise api.CommandError("terms", "구독 사용 안내를 먼저 확인해 주세요.")
    try:
        client = ai.make_client()
    except ValueError as exc:
        raise api.CommandError("failed", str(exc)[:200])
    run = engine.analysis
    run.running, run.stop, run.done, run.total, run.text, run.last = True, False, 0, len(units), "AI 연결을 확인하는 중", None
    engine.changed("results.run", None)
    review_holder = {}

    def intent_of(node):
        from hazop.app.screens.results import design_intent
        if "r" not in review_holder:
            from hazop.study import node_review
            try:
                review_holder["r"] = node_review.load(ns.get("project_id"), ns["graph_id"])
            except (OSError, ValueError):
                review_holder["r"] = None
        return design_intent(node, review_holder["r"])

    def work(progress):
        def tick(text, done, total):
            run.done, run.total, run.text = done, total, text
            engine.changed("results.run", None)
            progress(text, done, total)

        try:
            summary_ = analysis_run.run(client, ns, pg, units, intent_of, tick, lambda: run.stop or engine.stop_requested(),
                                        on_saved=lambda ur, doc, fp: engine.emit("results.cells", cells_delta(doc, ur, fp)))
        finally:
            run.running = False
        run.last = summary_
        engine.changed("results", None)
        engine.changed("results.run", None)
        return summary_
    job = engine.start_job("AI 분석 실행", work, kind="analysis")
    return {"job": job, "calls": len(units)}


def _stop(engine, a):
    """남은 호출을 부르지 않는다(진행 중인 호출은 끝까지 받는다)."""
    run = engine.analysis
    if run.running:
        run.stop = True
        engine.changed("results.run", None)
    return {"stopping": run.running}


def _v_fields(v):
    if not isinstance(v, dict) or len(v) > 12:
        raise ValueError("고칠 필드가 객체(12개 이하)여야 함")
    allowed = set(res.EDITABLE_FIELDS)
    for k, val in v.items():
        if k not in allowed:
            raise ValueError("고칠 수 없는 필드: %s" % k)
        if len(json.dumps(val, ensure_ascii=False)) > 6000:
            raise ValueError("%s 값이 너무 김" % k)
    return v


def register(commands):
    api = _api()
    C, v_str, v_int, v_list, v_enum = api.Command, api.v_str, api.v_int, api.v_list, api.v_enum
    where = {"node_id": (v_str(1, 40), True), "deviation_id": (v_str(1, 20), True)}
    ver = (v_str(1, 100), True)
    rev = (v_int(0, INT_MAX), False)          # 화면이 읽은 구간 집합 판(그 사이 구간이 바뀌면 엔진이 거절)
    entry = {"entry_id": (v_str(1, 80), True)}

    def put(name, spec_, handler, doc):
        key = "results." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("set_status", dict(where, **entry, status=(v_enum(*res.HUMAN_STATUSES), True), reason=(v_str(0, 1000), False), ver=ver, set_rev=rev), _set_status,
        "항목 판정: 수용·수정(되돌림)·기각·보류. 수정·기각·보류에는 사유가 있어야 한다. 읽은 결과 파일 지문(ver)을 함께 보낸다")
    put("edit_entry", dict(where, **entry, fields=(_v_fields, True), reason=(v_str(1, 1000), True), ver=ver, set_rev=rev), _edit_entry,
        "항목 내용 고치기(판정 '수정'). 사유 필수")
    put("recheck", dict(where, ver=ver, set_rev=rev), _recheck, "범위가 바뀐 칸의 판정을 다시 확인했다고 적는다")
    put("export_excel", {"scope": (v_enum("all", "approved", "nodes"), False), "node_ids": (v_list(v_str(1, 40), 500), False)}, _export_excel,
        "Excel로 내보낸다(저장 위치는 창이 대화상자로 묻는다)")
    put("export_ie", {}, _export_ie, "초기사건 인계 묶음을 내보낸다(수용 항목만, 저장 위치는 창이 묻는다)")
    put("run_plan", {"scope": (v_enum(*("all", "node", "cell", "failed")), True), "node_id": (v_str(1, 40), False),
                     "deviation_id": (v_str(1, 20), False)}, _run_plan, "분석 실행 전 확인: 호출 수·칸 수·연결 상태")
    put("run", {"scope": (v_enum(*("all", "node", "cell", "failed")), True), "node_id": (v_str(1, 40), False),
                "deviation_id": (v_str(1, 20), False)}, _run, "AI 분석을 시작한다(구독 연결)")
    put("stop", {}, _stop, "분석을 멈춘다(남은 호출을 부르지 않음)")
    put("ack_terms", {}, _ack_terms, "구독 사용 안내를 확인했다고 기록한다")
