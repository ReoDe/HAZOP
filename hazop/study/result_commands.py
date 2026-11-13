"""⑤ 결과 명령: 새 화면(웹 shell)과 채팅이 부르는 얇은 진입점. 명령 표는
docs/units/2026-11-13-drawing-knowledge/evidence/results-commands.md, 판정 규칙은 hazop.study.results(보류·사유).

execute(node_set, name, args, by, fingerprint)는 저장된 ⑤ 결과(results.load_fp: 0.1·0.2 파일은 이때 맞춰 읽음)를 읽어 명령
하나를 실행한다. 쓰는 명령은 fingerprint(화면이 읽을 때 받은 결과 파일 지문)를 지금 파일과 대조해 다르면 쓰지 않는다.
돌려주는 값: {"ok", "command", "fingerprint", "refused": [{"target", "reason"}], …명령별 값}.
분석 실행·멈춤은 구독 연결의 실행기(hazop/app/ai_runner)가 맡아 여기 두지 않는다(명령 표 참고).
"""

from hazop import store_io
from hazop.study import results as res


def _refused(name, target, reason, fp=None):
    return {"ok": False, "command": name, "fingerprint": fp, "refused": [{"target": str(target), "reason": str(reason)}]}


def _ok(name, fp, **values):
    return dict({"ok": True, "command": name, "fingerprint": fp, "refused": []}, **values)


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
    return {"cell": cell, "editable": res.editable_problem(doc, *_where(a), ns) is None}, None


def _set_status(ns, doc, a, by, pg):
    return {}, res.set_status(doc, *_where(a), a.get("entry_id"), a.get("status"), node_set=ns, by=by,
                              reason=a.get("reason"))


def _edit_entry(ns, doc, a, by, pg):
    return {}, res.edit_entry(doc, *_where(a), a.get("entry_id"), dict(a.get("fields") or {}), node_set=ns, by=by,
                              reason=a.get("reason"))


def _recheck_cell(ns, doc, a, by, pg):
    return {}, res.recheck_cell(doc, *_where(a), by, node_set=ns)


def _export_excel(ns, doc, a, by, pg):
    from hazop.export import study_xlsx
    if pg is None:
        raise ValueError("Excel 내보내기에는 프로젝트 그래프가 필요함")
    path, rows = study_xlsx.export(a["path"], doc, ns, pg, res.load_deviations(), reviewer=by,
                                   scope=a.get("scope") or "all", node_ids=a.get("node_ids"))
    return {"path": path, "rows": rows}, None


def _export_ie_bundle(ns, doc, a, by, pg):
    from hazop.ie import bundle, bundle_xlsx, model
    from hazop.ie import store as ie_store
    from hazop.study.nodes import now_utc
    if pg is None:
        raise ValueError("IE 인계 묶음에는 프로젝트 그래프가 필요함")
    ie_doc = model.sync(ie_store.load(ns.get("project_id"))[0], doc, node_set=ns)
    b = bundle.build_bundle(doc, ns, pg, ie_doc, now_utc())
    xlsx_path, json_path = bundle_xlsx.export(a["path"], b)
    return {"path": xlsx_path, "json_path": json_path, "candidates": len(b["candidates"])}, None


COMMANDS = {"get_matrix": (_get_matrix, False), "get_cell": (_get_cell, False), "set_status": (_set_status, True),
            "edit_entry": (_edit_entry, True), "recheck_cell": (_recheck_cell, True),
            "export_excel": (_export_excel, False), "export_ie_bundle": (_export_ie_bundle, False)}


def execute(node_set, name, args, by, fingerprint, pg=None):
    """명령 name을 실행한다. 쓰는 명령(set_status·edit_entry·recheck_cell)은 by(검토자)가 있어야 하고, fingerprint가
    None이 아니면 지금 결과 파일 지문과 같아야 한다. 결과 파일이 없으면 빈 결과에서 시작한다."""
    entry = COMMANDS.get(name)
    if entry is None:
        return _refused(name, "command", "모르는 명령(%s 가운데 하나)" % ", ".join(sorted(COMMANDS)))
    fn, writes = entry
    if writes and not (by or "").strip():
        return _refused(name, "by", "사람 이름(검토자) 필요")
    try:
        doc, fp = res.load_fp(node_set)
    except (OSError, ValueError) as exc:
        return _refused(name, "results", "⑤ 결과 파일을 읽을 수 없음(%s)" % exc)
    doc = doc if doc is not None else res.empty_results(node_set, res.load_deviations())
    if writes and fingerprint is not None and fingerprint != fp:
        return _refused(name, "fingerprint", "읽은 뒤 결과 파일이 바뀜(다시 읽고 고칠 것)", fp)
    doc, problems, _bad = res.partition(doc, node_set)
    if writes and (problems or doc.get("read_only")):
        return _refused(name, "results", "읽기 전용: %s" % (doc.get("read_only") or problems[0]), fp)
    try:
        values, new = fn(node_set, doc, dict(args or {}), (by or "").strip(), pg)
    except (KeyError, ValueError) as exc:
        return _refused(name, name, exc, fp)
    if new is not None and new is not doc:
        try:
            _path, fp = res.save_fp(new, node_set.get("project_id"), expect=fp)
        except store_io.Conflict as exc:
            return _refused(name, "file", "읽은 뒤 파일이 바뀌어 저장하지 않음(%s)" % exc, fp)
        except OSError as exc:
            return _refused(name, "file", "저장 실패(%s)" % exc, fp)
    return _ok(name, fp, **values)
