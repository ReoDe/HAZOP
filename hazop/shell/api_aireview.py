"""새 웹 화면의 AI 검토 후보 영역(INTENT.md §3.2, 완료 목록 2 A4). Qt를 import하지 않는다.

- **읽기** `aireview`(도면별 후보 수·마지막 실행), `aireview/<도면 ID>`(한 도면의 후보: 할 일별 묶음, 묶어 수락할 수 있는 묶음, 지금 값),
  `aireview/estimate?cap=N`(도면별 예상 호출 수, `ai_review.estimate_pages`). 읽기는 파일을 쓰지 않는다.
- **명령** `aireview.accept`·`aireview.reject`·`aireview.revert`(낱개), `aireview.accept_bulk`(확신 높은 묶음), `aireview.run`(고른 도면에
  AI 검토 실행). 쓰기는 읽은 판(`ver` = 후보 파일과 사람 수정 기록의 지문)을 대조해 어긋나면 stale로 거절한다. 결정한 사람은 설정의 검토자 이름이다.
- **수락·되돌리기 뒤 그래프를 바로 다시 만든다.** 수락은 사람 수정 기록(hazop.extract.corrections)에 연산으로 들어가므로, 이전 화면처럼 '다시 열면
  반영'이 아니라 그 도면의 그래프(scripts/build_graph.build_one이 기록을 적용)와 프로젝트 지식그래프를 이 자리에서 다시 만든다(hazop.app.data와 같은 길).
- 채팅(d-chat)이 부를 실행 함수: `candidates`, `accept`, `accept_bulk`, `reject`, `revert`. 모두 {"ok", ...} 사전을 돌려주고 예외를 올리지 않는다.
  웹 명령은 이 함수들을 감싼 것이다. 웹과 채팅 모두 경로를 주고받지 않고 도면 ID·후보 ID만 쓴다.
"""

import hashlib
import logging
import os

from hazop import paths, store_io
from hazop.extract import ai_review, corrections
from hazop.study.nodes import now_utc

LOG = logging.getLogger("hazop.shell.api_aireview")
TOPICS = ("aireview",)
PROJECT_PREFIXES = ("aireview.",)
MAX_IDS = 500
FIELD_LABELS = {"kind": "종류", "tag": "태그", "normal_position": "정상 위치", "fail_position": "고장 위치", "connection": "연결",
                "to_system": "연결 계통"}
STATUS_LABELS = {"proposed": "제안", "accepted": "수락", "rejected": "거절"}


def _api():
    from hazop.shell import api
    return api


class Refused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


# ---------------------------------------------------------------- 읽기

def _name(engine, graph_id):
    name = engine.graph_names().get(graph_id)
    if not name:
        raise Refused("not_found", "없는 도면")
    return name


def _original(name):
    from hazop.app import data
    return data.read_json(data.extraction_path(name))


def ver_of(name):
    """읽은 판: 쪽 확정과 같은 세 파일(추출 결과·사람 수정 기록·AI 후보, confirmation.file_paths)의 지문을 묶은 값.
    다시 추출해 추출 결과가 바뀌어도 달라진다(검토 2)."""
    from hazop.extract import confirmation
    files = confirmation.file_paths(name)
    text = "|".join("%s=%s" % (k, store_io.fingerprint(files[k]) or "-") for k in sorted(files))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def stale_path(name):
    """그래프가 수정 기록보다 낡았다는 표시 파일(수락·되돌리기는 저장됐는데 그래프 다시 만들기가 실패했을 때 남긴다)."""
    return paths.folder("ai-review", paths.safe_name(name) + ".graph-stale.json")


def _mark_stale(name, why):
    try:
        store_io.write_json(stale_path(name), {"name": name, "at": now_utc(), "reason": str(why)[:200]})
    except OSError:
        LOG.exception("낡은 그래프 표시를 남기지 못함")


def graph_stale(name):
    return os.path.isfile(stale_path(name))


def _ensure_graph(name):
    """낡은 그래프 표시가 있으면 다시 만들어 본다(다음에 열 때·다음 동작 때). → (아직 낡았는지, 알림 글, 재확인 안내)."""
    if not graph_stale(name):
        return False, [], []
    try:
        notes, recheck = _rebuild(name)
    except Exception as exc:  # noqa: BLE001 - 다시 만들기 실패는 표시로 남기고 화면은 뜬다
        LOG.exception("낡은 그래프 다시 만들기 실패")
        return True, ["그래프가 수정 기록보다 낡았습니다. 다시 만들지 못했습니다(%s)." % type(exc).__name__], []
    try:
        os.remove(stale_path(name))
    except OSError:
        pass
    return False, notes, recheck


def _current(shown, c):
    if c["field"] == "connection":
        return "열린 끝"
    node = shown.get(c["target"])
    if node is None:
        return ""
    if c["field"] in ("kind", "tag"):
        return node.get(c["field"]) or ""
    return (node.get("attributes") or {}).get(c["field"]) or ""


def _row(c, shown):
    block = ai_review.bulk_block(c)
    return {"cand_id": c["cand_id"], "task": c["task"], "field": c["field"], "field_label": FIELD_LABELS.get(c["field"], c["field"]),
            "current": _current(shown, c), "values": list(c["values"])[:3], "confidence": round(float(c["confidence"]), 2),
            "reason": (c.get("reason") or "")[:300], "status": c["status"], "status_label": STATUS_LABELS.get(c["status"], c["status"]),
            "local_id": c.get("local_id"), "bulk_ok": block is None, "bulk_block": block if c["status"] == "proposed" else None,
            "decided_by": c.get("decided_by")}


def _load(name):
    """(후보 문서 또는 None, 원본 추출). 옛 종류 후보에는 near_symbol을 채운다(메모리에서만)."""
    original = _original(name)
    doc = ai_review.load_doc(name)
    if doc is not None:
        ai_review.annotate(doc, original)
    return doc, original


def candidates(engine, graph_id):
    """한 도면의 후보(채팅·웹 공용). → {ok, available, graph_id, drawing_number, ver, counts, groups, bulk, last_run} 또는 {ok: False, code, message}."""
    try:
        name = _name(engine, graph_id)
        stale, stale_notes, _recheck = _ensure_graph(name)
        doc, original = _load(name)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    except (OSError, ValueError) as exc:
        return {"ok": False, "code": "failed", "message": "AI 후보를 읽을 수 없습니다(%s)." % str(exc)[:120]}
    base = {"ok": True, "graph_id": graph_id, "drawing_number": (original.get("drawing") or {}).get("drawing_number") or name,
            "ver": ver_of(name), "graph_stale": stale, "graph_notes": stale_notes}
    if doc is None:
        return dict(base, available=False, reason="이 도면에는 AI 후보가 없습니다. AI 검토를 실행하면 생깁니다.", counts={}, groups=[], bulk=[],
                    last_run=None)
    shown = {n["source_object_id"]: n for n in corrections.apply_saved(original, name)["nodes"]}
    order = {f: i for i, f in enumerate(FIELD_LABELS)}
    rows = sorted(doc["candidates"], key=lambda c: (c["status"] != "proposed", order.get(c["field"], 99), -c["confidence"], c["cand_id"]))
    groups = []
    for task in ai_review.TASK_ORDER:
        items = [_row(c, shown) for c in rows if c["task"] == task]
        if items:
            groups.append({"task": task, "label": ai_review.TASK_LABELS[task], "items": items,
                           "proposed": sum(1 for x in items if x["status"] == "proposed")})
    bulk = [{"task": t, "label": ai_review.TASK_LABELS[t], "count": len(ids)} for t, ids in ai_review.bulk_groups(doc, by="task").items()]
    counts = {s: sum(1 for c in doc["candidates"] if c["status"] == s) for s in STATUS_LABELS}
    runs = doc.get("runs") or []
    last = runs[-1] if runs else {}
    return dict(base, available=True, counts=counts, groups=groups, bulk=bulk, threshold=ai_review.DEFAULT_THRESHOLD,
                last_run={k: last.get(k) for k in ("at", "calls", "left", "needed_calls", "halted", "stopped", "not_symbol")} if last else None)


def overview(engine):
    """도면별 후보 수(목록). 후보 파일이 없는 도면도 0으로 넣는다."""
    rows = []
    for gid, name in sorted(engine.graph_names().items(), key=lambda kv: kv[1]):
        try:
            doc = ai_review.load_doc(name)
        except (OSError, ValueError):
            doc = None
        cands = (doc or {}).get("candidates") or []
        rows.append({"graph_id": gid, "drawing_number": (doc or {}).get("drawing_number") or name,
                     "proposed": sum(1 for c in cands if c["status"] == "proposed"), "total": len(cands),
                     "accepted": sum(1 for c in cands if c["status"] == "accepted"), "ran": bool((doc or {}).get("runs"))})
    return {"drawings": rows, "cap": int(engine.settings.get("extract_ai_cap") or ai_review.DEFAULT_CAP), "run_cap": ai_review.RUN_CAP,
            "seconds_per_call": ai_review.SECONDS_PER_CALL}


def estimate(engine, cap, graph_ids=None):
    """도면별 예상 호출 수(사람이 고친 자리를 뺀 미확인 항목으로 센다). graph_ids가 없으면 프로젝트의 모든 도면."""
    names = engine.graph_names()
    pick = [g for g in (graph_ids or sorted(names, key=lambda g: names[g])) if g in names]
    pages = []
    for gid in pick:
        try:
            pages.append((names[gid], _original(names[gid])))
        except (OSError, ValueError):
            continue
    est = ai_review.estimate_pages(pages, cap=cap, run_cap=ai_review.RUN_CAP)
    to_gid = {names[g]: g for g in pick}
    return {"cap": cap, "run_cap": ai_review.RUN_CAP, "calls": est["calls"], "seconds": est["seconds"], "capped": est["capped"],
            "pages": [{"graph_id": to_gid.get(p["name"]), "items": p["items"], "calls": p["calls"], "needed": p["needed"]} for p in est["pages"]]}


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'aireview'. 없는 자료는 None(404)."""
    api = _api()
    if len(parts) == 1:
        return api._json(overview(engine))
    if len(parts) == 2 and parts[1] == "estimate":
        try:
            cap = max(1, min(200, int(query.get("cap") or engine.settings.get("extract_ai_cap") or ai_review.DEFAULT_CAP)))
        except ValueError:
            cap = ai_review.DEFAULT_CAP
        return api._json(estimate(engine, cap))
    if len(parts) == 2:
        data = candidates(engine, parts[1])
        if not data["ok"] and data["code"] == "not_found":
            return None
        return api._json(data)
    return None


# ---------------------------------------------------------------- 쓰기

def _rebuild(name):
    """그 도면의 그래프와 프로젝트 지식그래프를 다시 만든다(hazop.app.data.save_corrections와 같은 길).
    → (알림 글 목록, ④ 검토구간·⑤ 분석 결과 재확인 안내 목록 — data.save_corrections와 같은 규칙)."""
    from hazop.app import data
    from hazop.study import nodes as study_nodes
    from hazop.study import results as study_results
    notes = []
    graph, _ = data.script_module("build_graph").build_one(data.extraction_path(name), paths.output_root("graph"))
    if graph.get("project_id"):
        try:
            data.build_project_kg(graph["project_id"])
        except (OSError, ValueError, KeyError) as exc:
            notes.append("지식그래프를 다시 만들지 못했습니다(%s)." % str(exc)[:120])
    recheck = []
    try:
        node_set = study_nodes.read_as_is(graph)
    except ValueError:
        node_set = None
    if node_set is not None and study_nodes.is_stale(node_set, graph):
        confirmed = node_set.get("status") == "confirmed" or study_nodes.active_nodes(
            node_set if node_set.get("schema_version") == study_nodes.SCHEMA_VERSION else None)
        recheck.append("④ 검토구간 %s이 고치기 전 도면 기준입니다. 재확인이 필요합니다." % ("확정본" if confirmed else "저장본"))
    res_path = study_results.store_path(graph.get("project_id"), graph["graph_id"])
    if os.path.isfile(res_path):
        saved = data.read_json(res_path)
        ref = saved.get("graph_version") if "graph_version" in saved else (saved.get("study_nodes_ref") or {}).get("graph_version")
        if ref != graph["graph_version"]:
            recheck.append("⑤ 분석 결과가 고치기 전 도면 기준입니다. 재확인이 필요합니다.")
    return notes, recheck


STALE_TEXT = "AI 후보나 도면 수정이 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요."


def _decide(engine, graph_id, cand_ids, action, ver, by=None):
    """낱개 결정의 공통 길. ver(읽은 판)는 꼭 있어야 한다(채팅도 같다, 검토 5).
    → {ok, changed, failed, ver, notes, recheck, graph_stale} 또는 {ok: False, code, message}.
    저장한 뒤의 실패(그래프 다시 만들기)는 오류가 아니라 '저장됨, 그래프 갱신 실패'로 돌려주고 낡은 그래프 표시를 남긴다(검토 3·4)."""
    stale_before, notes, recheck = False, [], []
    try:
        name = _name(engine, graph_id)
        stale_before, notes, recheck = _ensure_graph(name)          # 앞에서 실패한 다시 만들기를 이번 동작에서 다시 해 본다
        by = by or engine.reviewer()
        if not by:
            raise Refused("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 수락·거절한 사람으로 남습니다.")
        if not ver or ver != ver_of(name):
            raise Refused("stale", STALE_TEXT if ver else "읽은 판(ver)이 없어 저장하지 않았습니다. 후보 목록을 먼저 읽으세요.")
        doc, original = _load(name)
        if doc is None:
            raise Refused("not_found", "이 도면에는 AI 후보가 없습니다.")
        have = {c["cand_id"]: c for c in doc["candidates"]}
        ids = [i for i in dict.fromkeys(cand_ids) if i in have]
        missing = [i for i in cand_ids if i not in have]
        if not ids:
            raise Refused("not_found", "없는 후보입니다.")
        before = {i: have[i]["status"] for i in ids}
        failed = [{"cand_id": i, "reason": "없는 후보"} for i in missing]
        if action == "accept":
            failed += [{"cand_id": c, "reason": r} for c, r in ai_review.accept(doc, ids, original, name, by=by)]
        elif action == "reject":
            ai_review.reject(doc, ids, by=by)
        else:
            ai_review.revert(doc, ids, name, by=by)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    except store_io.Conflict:
        return {"ok": False, "code": "stale", "message": STALE_TEXT}
    except (OSError, ValueError) as exc:
        LOG.exception("AI 후보 %s 실패", action)
        return {"ok": False, "code": "failed", "message": "저장하지 못했습니다(%s)." % str(exc)[:160]}
    # 여기부터는 저장이 끝났다. 어떤 예외도 '저장 안 됨'으로 알리지 않는다
    after = {c["cand_id"]: c["status"] for c in doc["candidates"]}
    changed = [i for i in ids if after.get(i) != before[i]]
    stale = stale_before
    if changed and action in ("accept", "revert"):
        try:
            more, recheck = _rebuild(name)
            notes = notes + more
            stale = False
            if stale_before:
                try:
                    os.remove(stale_path(name))
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001 - 저장 뒤의 실패
            LOG.exception("그래프 다시 만들기 실패")
            _mark_stale(name, type(exc).__name__)
            stale = True
            notes = notes + ["저장했습니다. 그래프를 다시 만들지 못해 도면·그래프가 아직 고치기 전 상태입니다(%s). 다음에 열 때 다시 만듭니다."
                             % type(exc).__name__]
    if changed or stale_before != stale:
        engine.changed("aireview", None)
        engine.changed("drawings", None)
        engine.changed("sheetconf", None)                         # 쪽 확정 카드의 AI 후보 수(검토 6)
        if action in ("accept", "revert") or stale_before != stale:
            engine.changed("sheet", graph_id)
            engine.changed("kg", None)
    return {"ok": True, "graph_id": graph_id, "changed": changed, "failed": failed, "ver": ver_of(name), "notes": notes,
            "recheck": recheck, "graph_stale": stale}


def accept(engine, graph_id, cand_ids, ver, by=None):
    return _decide(engine, graph_id, cand_ids, "accept", ver, by)


def reject(engine, graph_id, cand_ids, ver, by=None):
    return _decide(engine, graph_id, cand_ids, "reject", ver, by)


def revert(engine, graph_id, cand_ids, ver, by=None):
    return _decide(engine, graph_id, cand_ids, "revert", ver, by)


def accept_bulk(engine, graph_id, task, ver, by=None):
    """확신 높은 묶음(ai_review.bulk_groups, 할 일별)을 한 번에 수락한다. 묶음은 엔진이 다시 세므로 웹이 고른 ID를 믿지 않는다."""
    try:
        name = _name(engine, graph_id)
        doc, _original_ex = _load(name)
    except Refused as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    except (OSError, ValueError) as exc:
        return {"ok": False, "code": "failed", "message": "AI 후보를 읽을 수 없습니다(%s)." % str(exc)[:120]}
    if not ver or ver != ver_of(name):
        return {"ok": False, "code": "stale", "message": STALE_TEXT if ver else "읽은 판(ver)이 없어 저장하지 않았습니다. 후보 목록을 먼저 읽으세요."}
    ids = ai_review.bulk_groups(doc, by="task").get(task) if doc else None
    if not ids:
        return {"ok": False, "code": "not_found", "message": "묶어 수락할 후보가 없습니다."}
    return accept(engine, graph_id, ids, ver, by)


def run_review(engine, graph_ids, cap, progress):
    """고른 도면에 AI 검토를 돌린다(작업 스레드). 도면당 cap, 한 번 실행은 RUN_CAP까지. 사람이 고친 자리는 묻지 않는다.
    → {"drawings": [{graph_id, candidates, calls, left, halted}], "calls", "capped"}."""
    ai = engine.ai
    status = ai.status() if ai is not None else {}
    if ai is None or not status.get("can_start"):
        raise RuntimeError("AI 연결이 준비되지 않았습니다")
    client = ai.make_client()
    reason = ai_review.refuse_reason(client)
    if reason:
        raise RuntimeError(reason)
    names = engine.graph_names()
    pages = [(names[g], _original(names[g])) for g in graph_ids if g in names]
    est = ai_review.estimate_pages(pages, cap=cap, run_cap=ai_review.RUN_CAP)
    progress("AI 검토 준비 중(호출 %d회 안팎)" % est["calls"], 0, est["calls"] or None)
    to_gid = {v: k for k, v in names.items()}
    done = ai_review.run_many(pages, client, cap=cap, run_cap=ai_review.RUN_CAP, should_stop=engine.stop_requested,
                              on_progress=lambda name, d, t, left: progress("AI 검토 %s" % name, d, t))
    engine.changed("aireview", None)
    return {"drawings": [{"graph_id": to_gid.get(n), "candidates": count, "calls": st.get("calls", 0), "left": st.get("left", 0),
                          "halted": bool(st.get("halted"))} for n, count, st in done],
            "calls": sum(st.get("calls", 0) for _n, _c, st in done), "capped": est["capped"]}


def _unwrap(out):
    if not out.get("ok"):
        raise _api().CommandError(out.get("code") or "failed", out.get("message") or "처리하지 못했습니다.")
    return out


def _h_decide(fn):
    return lambda engine, a: _unwrap(fn(engine, a["graph_id"], a["cand_ids"], a["ver"]))


def _h_bulk(engine, a):
    return _unwrap(accept_bulk(engine, a["graph_id"], a["task"], a["ver"]))


def _h_run(engine, a):
    api = _api()
    names = engine.graph_names()
    gids = [g for g in a["graph_ids"] if g in names]
    if not gids:
        raise api.CommandError("not_found", "없는 도면")
    status = engine.ai.status() if engine.ai is not None else {}
    if not status.get("can_start"):
        raise api.CommandError("failed", "AI 연결이 준비되지 않았습니다. 설정에서 연결을 확인하세요.")
    cap = a.get("cap") or int(engine.settings.get("extract_ai_cap") or ai_review.DEFAULT_CAP)
    job = engine.start_job("AI 검토", lambda progress: run_review(engine, gids, cap, progress), kind="ai_review")
    return {"job": job}


def register(commands):
    api = _api()
    C, v_str, v_int, v_list, v_enum = api.Command, api.v_str, api.v_int, api.v_list, api.v_enum
    base = {"graph_id": (v_str(1, 200), True), "ver": (v_str(1, 40), True)}
    ids = (v_list(v_str(1, 120), MAX_IDS), True)

    def put(name, spec_, handler, doc):
        key = "aireview." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("accept", dict(base, cand_ids=ids), _h_decide(accept), "후보 수락(사람 수정 기록에 연산으로 들어가고 그래프를 다시 만든다)")
    put("reject", dict(base, cand_ids=ids), _h_decide(reject), "후보 거절")
    put("revert", dict(base, cand_ids=ids), _h_decide(revert), "수락·거절 되돌리기(수락한 연산은 수정 기록에서 빠지고 그래프를 다시 만든다)")
    put("accept_bulk", dict(base, task=(v_enum(*ai_review.TASK_ORDER), True)), _h_bulk,
        "확신 높은 묶음 수락(묶음은 엔진이 센다. 기호 종류는 확신 0.95 이상이고 이웃 기호에 붙지 않은 것만)")
    put("run", {"graph_ids": (v_list(v_str(1, 200), 200), True), "cap": (v_int(1, 200), False)}, _h_run,
        "고른 도면에 AI 검토 실행(도면당 상한 cap, 한 번 실행 300회까지)")

