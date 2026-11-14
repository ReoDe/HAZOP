"""⑤ 결과 명령: 새 화면(웹 shell)과 채팅이 부르는 얇은 진입점. 명령 표는
docs/units/2026-11-13-drawing-knowledge/evidence/results-commands.md, 판정 규칙은 hazop.study.results(보류·사유).

execute(pg, name, args, by, fingerprint, set_rev=None)는 검토구간 집합과 ⑤ 결과를 엔진이 직접 읽어 명령 하나를 실행한다.
부르는 쪽이 든 집합은 받지 않는다(그 사이 다른 창이 잠근 구간을 낡은 집합으로 고치지 않게). 쓰는 명령은 실행 직전에
- set_rev(화면이 읽은 집합 판)가 None이 아니면 지금 집합 판과,
- args의 node_rev가 있으면 대상 구간의 지금 rev와,
- fingerprint(화면이 읽은 결과 파일 지문)가 None이 아니면 지금 결과 파일 지문과 대조하고,
대상 구간의 잠금·보관 칸은 지금 집합으로 막는다. 읽기는 파일을 쓰지 않는다.
돌려주는 값: {"ok", "command", "fingerprint", "set_rev", "refused": [{"target", "code", "reason"}], …명령별 값}.
판정·고치기의 args에 author="ai"가 있으면 기록 줄에 글쓴이 AI를 남기고 by는 그 글을 확인한 사람이다(채팅 동작, results.AUTHORS).
분석 실행·멈춤은 구독 연결의 실행기(hazop/app/ai_runner)가 맡아 여기 두지 않는다(명령 표 참고).
"""

from hazop import store_io
from hazop.study import nodes
from hazop.study import results as res

# 거절 사유 코드(구간 명령 node_commands.CODES와 같은 갈래 + 파일 입출력 io)
CODES = ("unknown_command", "bad_actor", "stale", "conflict", "unreadable", "read_only", "rule", "io")


def _refused(name, target, reason, fp=None, set_rev=None, code="rule"):
    return {"ok": False, "command": name, "fingerprint": fp, "set_rev": set_rev,
            "refused": [{"target": str(target), "code": code, "reason": str(reason)}]}


def _ok(name, fp, set_rev, **values):
    return dict({"ok": True, "command": name, "fingerprint": fp, "set_rev": set_rev, "refused": []}, **values)


def _where(a):
    return a.get("node_id"), a.get("deviation_id")


def _cell_view(doc, node_id, deviation_id):
    cell = next((c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == (node_id, deviation_id)), None)
    if cell is None:
        return None
    return dict(cell, entries=[dict(e, verdict=res.verdict(e)) for e in cell["entries"]])


def _get_matrix(ns, doc, a, by, pg):
    return {"matrix": res.matrix_summary(doc)}, None


def _get_cell(ns, doc, a, by, pg):
    cell = _cell_view(doc, *_where(a))
    if cell is None:
        raise ValueError("없는 칸: %s/%s" % _where(a))
    node = next((n for n in ns["nodes"] if n["node_id"] == a.get("node_id")), {})
    return {"cell": cell, "editable": res.editable_problem(doc, *_where(a), ns) is None,
            "node_rev": node.get("rev")}, None


def _set_status(ns, doc, a, by, pg):
    return {}, res.set_status(doc, *_where(a), a.get("entry_id"), a.get("status"), node_set=ns, by=by,
                              reason=a.get("reason"), author=a.get("author"))


def _edit_entry(ns, doc, a, by, pg):
    return {}, res.edit_entry(doc, *_where(a), a.get("entry_id"), dict(a.get("fields") or {}), node_set=ns, by=by,
                              reason=a.get("reason"), author=a.get("author"))


def _recheck_cell(ns, doc, a, by, pg):
    return {}, res.recheck_cell(doc, *_where(a), by, node_set=ns)


def _set_ie_hints(ns, doc, a, by, pg):
    """사람이 초기사건 판정(ie_hint)을 정한다(B5). targets [{node_id, deviation_id, entry_id}]에 같은 판정을 한 번에 저장한다
    (겹친 구간에서 한 후보로 묶인 같은 원인 항목들). 판정한 사람(by)을 항목 이력에 남긴다. 항목 상태는 res.set_ie_hint 규칙대로."""
    targets = a.get("targets") or []
    if not targets:
        raise ValueError("판정할 항목이 없습니다")
    out = doc
    for t in targets:
        out = res.set_ie_hint(out, t["node_id"], t["deviation_id"], t["entry_id"], dict(a.get("hint") or {}), node_set=ns)
        res._entry(out, t["node_id"], t["deviation_id"], t["entry_id"])["history"][-1]["by"] = by
    return {"targets": len(targets)}, out


def _export_excel(ns, doc, a, by, pg):
    from hazop.export import study_xlsx
    path, rows = study_xlsx.export(a["path"], doc, ns, pg, res.load_deviations(), reviewer=by,
                                   scope=a.get("scope") or "all", node_ids=a.get("node_ids"))
    return {"path": path, "rows": rows}, None


def _export_ie_bundle(ns, doc, a, by, pg):
    from hazop.ie import bundle, bundle_xlsx
    from hazop.ie import store as ie_store
    from hazop.study.nodes import now_utc
    try:   # IEC 대응을 먼저 저장한다(저장하지 못하면 내보내지 않는다, ie_store.load_synced)
        ie_doc = ie_store.load_synced(ns.get("project_id"), doc, ns)[0]
    except ie_store.Conflict as exc:
        raise ValueError("초기사건 파일이 그 사이 바뀌어 내보내지 않았습니다(%s). 다시 하세요." % exc) from None
    fdoc, mdoc, bad = ie_store.load_sides(ns.get("project_id"))   # P5: 읽지 못한 FMEA·MLD는 빼고 '읽는 법'에 적는다(설계 §8.2)
    b = bundle.build_bundle(doc, ns, pg, ie_doc, now_utc(), fmea=fdoc, mld=mdoc, unreadable=bad)
    xlsx_path, json_path = bundle_xlsx.export(a["path"], b)
    return {"path": xlsx_path, "json_path": json_path, "candidates": len(b["candidates"])}, None


COMMANDS = {"get_matrix": (_get_matrix, False), "get_cell": (_get_cell, False), "set_status": (_set_status, True),
            "edit_entry": (_edit_entry, True), "recheck_cell": (_recheck_cell, True), "set_ie_hints": (_set_ie_hints, True),
            "export_excel": (_export_excel, False), "export_ie_bundle": (_export_ie_bundle, False)}


def execute(graph, name, args, by, fingerprint, set_rev=None, pg=None):
    """명령 name을 실행한다. graph는 프로젝트 그래프(구간 명령 node_commands.execute의 pg와 같은 것). 쓰는 명령(set_status·
    edit_entry·recheck_cell)은 by(검토자)가 있어야 하고 set_rev·node_rev·fingerprint를 지금 파일과 대조한다(모듈 설명).
    결과 파일이 없으면 빈 결과에서 시작한다. pg=는 옛 호출 꼴 execute(집합, …, pg=그래프)를 잇는 자리다. 그때 첫 인자
    (집합)는 쓰지 않고 pg를 그래프로 쓴다(웹 화면이 새 꼴로 옮기면 지움)."""
    entry = COMMANDS.get(name)
    if entry is None:
        return _refused(name, "command", "모르는 명령(%s 가운데 하나)" % ", ".join(sorted(COMMANDS)),
                        code="unknown_command")
    fn, writes = entry
    pg = pg if pg is not None else graph
    if not isinstance(pg, dict) or pg.get("kind") == nodes.KIND or not pg.get("graph_id"):
        return _refused(name, "pg", "프로젝트 그래프를 넘겨야 함(검토구간 집합은 엔진이 직접 읽음)", code="bad_actor")
    if writes and not (by or "").strip():
        return _refused(name, "by", "사람 이름(검토자) 필요", code="bad_actor")
    try:
        ns = nodes.load_fp(pg)[0] if writes else nodes.load_view(pg)[0]
    except (OSError, ValueError) as exc:
        return _refused(name, "node_set", "검토구간 파일을 읽을 수 없음(%s)" % exc, code="unreadable")
    if ns is None:
        return _refused(name, "node_set", "이 도면의 검토구간 파일이 없음", code="unreadable")
    rev = ns.get("set_rev")
    try:
        doc, fp = res.load_fp(ns)
    except (OSError, ValueError) as exc:
        return _refused(name, "results", "⑤ 결과 파일을 읽을 수 없음(%s)" % exc, set_rev=rev, code="unreadable")
    doc = doc if doc is not None else res.empty_results(ns, res.load_deviations())
    a = dict(args or {})
    if writes:
        node = next((n for n in ns["nodes"] if n["node_id"] == a.get("node_id")), None)
        if set_rev is not None and set_rev != rev:
            return _refused(name, "set_rev", "구간이 그 사이 바뀜(읽은 판 %s, 지금 %s)" % (set_rev, rev), fp, rev, "stale")
        if a.get("node_rev") is not None and (node or {}).get("rev") != a["node_rev"]:
            return _refused(name, "node_rev", "%s 구간이 그 사이 바뀜(읽은 rev %s, 지금 %s)"
                            % (a.get("node_id"), a["node_rev"], (node or {}).get("rev")), fp, rev, "stale")
        if fingerprint is not None and fingerprint != fp:
            return _refused(name, "fingerprint", "읽은 뒤 결과 파일이 바뀜(다시 읽고 고칠 것)", fp, rev, "stale")
    doc, problems, _bad = res.partition(doc, ns)
    if writes and (problems or doc.get("read_only") or ns.get("read_only")):
        why = ns.get("read_only") or doc.get("read_only") or problems[0]
        return _refused(name, "results", "읽기 전용: %s" % why, fp, rev, "read_only")
    a.pop("node_rev", None)
    try:
        values, new = fn(ns, doc, a, (by or "").strip(), pg)
    except (KeyError, ValueError) as exc:
        return _refused(name, name, exc, fp, rev)
    except OSError as exc:
        return _refused(name, "file", "파일을 쓰지 못함(%s)" % exc, fp, rev, "io")
    if new is not None and new is not doc:
        try:
            _path, fp = res.save_fp(new, ns.get("project_id"), expect=fp)
        except store_io.Conflict as exc:
            return _refused(name, "file", "읽은 뒤 파일이 바뀌어 저장하지 않음(%s)" % exc, fp, rev, "conflict")
        except OSError as exc:
            return _refused(name, "file", "저장 실패(%s)" % exc, fp, rev, "io")
    return _ok(name, fp, rev, **values)
