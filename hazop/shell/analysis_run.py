"""⑤ AI 분석 실행의 새 화면 길(Qt를 import하지 않는다). 이전 화면(hazop/app/screens/results.py + ai_runner.AiRunner)의 규칙을 그대로 지킨다:
호출 단위(ai_cells.plan_units)·맥락(node_context)·호출(run_unit)·반영(apply_unit)은 엔진 함수를 그대로 부르고, 한 호출이 끝날 때마다 결과 파일을 저장한다.
저장은 읽은 지문(expect)을 대조해(results.save_fp) 실행 중 사람이 고친 칸을 덮지 않는다. 멈추라고 하면 남은 호출을 부르지 않고 진행 중인 호출은 끝까지
받는다. 구독 한도·초과 사용 같은 멈춤(providers.halts)이 오면 남은 호출을 멈춘다.

방식(B4, 2026-11-14): 구독·API 키·고정 응답(시험). 어느 방식으로 돌지는 api_results가 api_settings.run_conn으로 정해 클라이언트를 넘긴다.
API 키(과금)는 사용자가 고른 경우에만, 실행 카드에서 예상 비용을 확인한 뒤에만 돈다(api_results._run이 막는다). 고정 응답 결과는 시험 파일
(results.test_store_path)에 저장해 실제 검토 기록의 AI 초안에 섞지 않는다(D5).
'이어서 실행'(scope resume): 앞 실행이 멈춘 뒤 남은 칸(부르지 않은 단위와 실패한 단위의 칸, run()의 rest)만 다시 계획한다.
다른 방식(API 키)으로 잇는 것은 사용자가 그때 고르고 비용을 확인한 경우뿐이다(자동으로 넘어가지 않는다).
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

from hazop.study import ai_cells, nodes, providers
from hazop.study import results as res

LOG = logging.getLogger("hazop.shell.analysis_run")
SCOPES = ("all", "node", "cell", "failed", "resume")
SECONDS_PER_CALL = 25      # 호출 하나의 어림(화면에 '약 몇 분'으로만 쓴다)

_stamp_lock = threading.Lock()
_last = [datetime.min.replace(tzinfo=timezone.utc)]


def stamp():
    """호출이 끝난 시각(UTC, 앞 시각보다 늘 뒤): 이력의 순서를 지키려는 것(ai_runner.stamp와 같은 규칙)."""
    with _stamp_lock:
        now = datetime.now(timezone.utc)
        if now <= _last[0]:
            now = _last[0] + timedelta(microseconds=1)
        _last[0] = now
        return now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def plan(ns, doc, scope, node_id=None, deviation_id=None, rest=None):
    """-> 호출 단위 목록. 분석 대상은 확정 구간뿐이다(잠금·적용됨 구간은 계획에서 빠진다).
    rest: scope resume에서 이을 칸 [(node_id, deviation_id)](앞 실행 run()의 rest). 지금 구간 집합에 없는 칸은 빠진다."""
    devs = res.load_deviations()
    if scope == "resume":
        cells = [tuple(c) for c in rest or [] if isinstance(c, (list, tuple)) and len(c) == 2]
        return ai_cells.plan_units(ns, devs, cells, group=True) if cells else []
    if scope == "all":
        return ai_cells.plan_units(ns, devs)
    if scope == "node":
        return [] if not node_id else ai_cells.plan_units(
            ns, devs, [(node_id, d["deviation_id"]) for d in devs], group=True)
    if scope == "cell":
        return [] if not (node_id and deviation_id) else ai_cells.plan_units(ns, devs, [(node_id, deviation_id)])
    if scope == "failed":
        return ai_cells.plan_units(ns, devs, ai_cells.failed_cells(doc))
    raise ValueError("모르는 범위: %r" % (scope,))


def summarize(units):
    return {"calls": len(units), "cells": sum(len(u["deviation_ids"]) for u in units),
            "seconds": len(units) * SECONDS_PER_CALL}


def contexts(units, ns, pg, intent_of):
    """구간마다 한 번 만드는 AI 맥락. intent_of(node) -> (글, 출처) 또는 None."""
    kg, _reason = ai_cells.load_kg_for(ns)
    expectations, _note = ai_cells.expectations_for(pg, kg)
    by_id = {n["node_id"]: n for n in ns["nodes"]}
    out = {}
    for u in units:
        if u["node_id"] not in out:
            node = by_id[u["node_id"]]
            out[u["node_id"]] = ai_cells.node_context(node, pg, kg, intent_of(node), expectations=expectations)
    return out


def run(client, ns, pg, units, intent_of, progress, should_stop, on_saved=None, test=False):
    """units를 차례로 부르고 호출마다 저장한다 -> {"calls", "ok_calls", "failed_calls", "cells", "reason", "limit", "usage", "rest", ...}.
    reason: done · stopped(멈추라고 함) · halted(구독 한도·초과 사용 등으로 남은 호출을 멈춤). progress(text, done, total)는 호출 사이에 부른다.
    rest: 이어서 실행할 칸 [[node_id, deviation_id]](실패한 단위의 칸 + 부르지 않은 단위의 칸, 순서 유지·중복 없음).
    test: 고정 응답(시험) 실행. 결과를 시험 파일에 저장한다."""
    devs = res.load_deviations()
    ctxs = contexts(units, ns, pg, intent_of)
    project = ns.get("project_id")
    kinds, ok_calls, ok_cells, limit, halted, last_error = [], 0, 0, None, None, None
    done = 0
    stopped = False
    rest = []
    for unit in units:
        if should_stop():
            stopped = True
            break
        progress("%s 분석 중" % unit["node_id"], done, len(units))
        ur = ai_cells.run_unit(client, unit, ctxs[unit["node_id"]], devs, stamp())
        done += 1
        kinds.append(ur.get("error_kind"))
        if ur.get("limit"):
            limit = ur["limit"]
        if ur["status"] == "ok":
            ok_calls += 1
            ok_cells += len(ur["cells"])
        else:
            last_error = ur.get("error")
            rest += [[unit["node_id"], d] for d in unit["deviation_ids"]]
        saved = _merge_and_save(ns, project, ur, test=test)
        if on_saved is not None and saved is not None and not test:
            on_saved(ur, saved[0], saved[1])         # 반영한 문서와 새 지문: 화면에 바뀐 칸만 알리려고(시험 파일은 화면 결과가 아니다)
        if providers.halts(kinds):
            halted = ur
            break
    for unit in units[done:]:
        rest += [[unit["node_id"], d] for d in unit["deviation_ids"]]
    seen = set()
    rest = [c for c in rest if not (tuple(c) in seen or seen.add(tuple(c)))]
    doc, _fp = (res.load_test_fp(ns) if test else res.load_fp(ns))
    reason = "halted" if halted is not None else ("stopped" if stopped else "done")
    return {"calls": done, "planned": len(units), "ok_calls": ok_calls, "failed_calls": done - ok_calls, "cells": ok_cells, "reason": reason,
            "limit": limit, "error_kind": (halted or {}).get("error_kind"), "error": (halted or {}).get("error") or last_error,
            "conn_state": (halted or {}).get("conn_state"), "usage": ai_cells.usage_total(doc) if doc else None, "rest": rest, "test": bool(test)}


def _merge_and_save(ns, project, ur, attempts=3, test=False):
    """호출 결과 하나를 지금 결과 파일에 합쳐 저장한다. 그새 파일이 바뀌었으면(사람이 고침) 다시 읽어 합친다.
    test: 고정 응답(시험) 결과 파일에 쓴다(실제 결과 파일은 건드리지 않는다)."""
    from hazop import store_io
    for _ in range(attempts):
        doc, fp = res.load_test_fp(ns) if test else res.load_fp(ns)
        if doc is None:
            doc, fp = res.empty_results(ns, res.load_deviations()), store_io.ANY
        merged = ai_cells.apply_unit(doc, ur)
        try:
            if test:
                res.write(res.test_store_path(project, merged["graph_id"]), merged, expect=fp)
                new_fp = res.written_fp(merged)
            else:
                _path, new_fp = res.save_fp(merged, project, expect=fp)
            return merged, new_fp
        except store_io.Conflict:
            continue
    LOG.error("결과 저장이 계속 겹쳐 이 호출의 결과를 반영하지 못함: %s", ur.get("unit_id"))
    return None


def intent_text(node, review=None):
    """AI 맥락에 넣는 구간 설계 의도(글만). 이전 화면의 design_intent와 같은 규칙을 지키려고 그 함수를 그대로 부른다."""
    from hazop.app.screens.results import design_intent
    found = design_intent(node, review)
    return found
