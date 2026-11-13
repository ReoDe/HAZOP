"""검토구간·⑤ 결과 저장 규격 0.1 → 0.2 변환. 근거: docs/specs/study-node-segmentation.md §2.5, §2.7.

화면이 처음 읽을 때(nodes.load_fp) 한 번 바꾼다. 순서가 데이터를 지키는 장치다.
1. 결과 잇기(0.1 모양에서): remap.carry_results가 집합 status·confirmed_at·previous를 읽으므로 그 값을 옮기기 전에 돈다.
   A 확정본 결과 → 그대로. B 앞 확정본 결과 → 구성요소 집합으로 이음. C 확정 해제(proposed) 뒤 결과 → previous의 확정본으로
   이음(칸은 보관 hold). D 옮길 곳이 없는 칸 → archived_cells. 사람이 승인한 항목이 백업 파일에만 남는 길은 없다.
2. 집합 바꾸기: 0.1 머리 값은 legacy에 그대로 둔다. 스크리닝 제외 구간은 칸에 항목이 없으면 legacy.excluded_nodes로 뺀다.
3. 결과 바꾸기: 칸 열쇠에 item_id, 칸마다 node_rev 1, 구간 상태대로 hold(results.reconcile).
4. 쓰기: 백업 둘(<이름>.v0.1.bak.json)을 먼저 쓰고, 결과 0.2 → 집합 0.2 순으로 쓴다. 두 파일에 같은 conversion_id와
   원본 0.1 집합 파일의 지문(source_set_fp)을 적는다.
다시 시작: 집합 0.1·결과 0.2이고 결과의 source_set_fp가 지금 집합 지문과 같으면 2단계부터. 다르면 멈추고(읽기 전용) 알린다.
백업을 쓰지 못하면 바꾸지 않고 읽기 전용(메모리에서 바꾼 집합에 read_only)으로 연다.
"""

import copy
import hashlib
import logging
import os

from hazop import store_io
from hazop.study import nodes, remap
from hazop.study import results as res

BACKUP_SUFFIX = ".v0.1.bak.json"
LEGACY_ORIGINS = {"rule": "script"}  # 그 밖(merged·split·AI 검토 받아들임)은 user
_log = logging.getLogger(__name__)


def backup_path(path):
    return path[:-5] + BACKUP_SUFFIX if path.endswith(".json") else path + BACKUP_SUFFIX


def _touched(cell):
    return bool(cell.get("entries")) or cell.get("state") not in (None, "not_analyzed")


# ---------------------------------------------------------------- 1단계: 결과 잇기(0.1 모양)

def carry_legacy(set01, results01, deviations):
    """(이은 0.1 모양 결과 또는 None, 보고 {case, reason, archived}). 결과가 없으면 (None, {case: None})."""
    if results01 is None:
        return None, {"case": None, "reason": None, "archived": 0}
    ref = results01.get("study_nodes_ref") or {}
    confirmed = set01.get("status") == "confirmed"
    if confirmed and ref == {"graph_version": set01.get("graph_version"), "confirmed_at": set01.get("confirmed_at")}:
        return results01, {"case": "A", "reason": None, "archived": 0}
    if confirmed:
        from hazop.study import migrate
        moved, n = migrate.legacy_migrate_results(results01, set01)
        if n is not None:  # 같은 확정본을 옛 판으로 가리키던 결과(판 이전 기록이 이어짐)
            return moved, {"case": "A", "reason": None, "archived": 0}
        key = set01
        case = "B"
    else:
        key = dict(set01, status="confirmed", confirmed_at=set01.get("confirmed_at") or "(확정 해제 뒤 변환)")
        case = "C"
    carried, report = remap.carry_results(results01, key, deviations, partial=True)
    archived = len(carried.get("archived_cells") or [])
    if archived:
        case += "+D"
    return carried, {"case": case, "reason": report.get("reason"), "archived": archived,
                     "scope_changed_entries": report.get("scope_changed_entries", 0)}


# ---------------------------------------------------------------- 2단계: 집합

def _node_v2(n, state, set01):
    out = {k: copy.deepcopy(v) for k, v in n.items() if k not in ("origin",)}
    origin = LEGACY_ORIGINS.get(n.get("origin"), "user" if n.get("origin") else "script")
    out.update(rev=1, origin=origin, state=state, name_by=origin, design_intent=None, locked=None,
               confirmed=({"at": set01.get("confirmed_at"), "by": set01.get("confirmed_by"), "rev": 1}
                          if state == "confirmed" else None))
    if n.get("origin"):
        out["legacy_origin"] = n["origin"]
    return out


def upgrade_set(set01, keep_excluded=(), at=None):
    """0.1 집합 → 0.2 집합(§2.5 값 대응). keep_excluded: 칸에 항목이 있어 적용됨 구간으로 남길 제외 구간 ID."""
    state = "confirmed" if set01.get("status") == "confirmed" else "applied"
    out = {k: copy.deepcopy(v) for k, v in set01.items()
           if k not in ("status", "confirmed_at", "confirmed_by", "proposer", "previous", "member_refs",
                        "member_digest", "schema_version", "nodes")}
    excluded, kept = [], []
    for n in set01["nodes"]:
        if (n.get("screen") or {}).get("status") == "excluded":
            if n["node_id"] in keep_excluded:
                kept.append(_node_v2(n, "applied", set01))
            else:
                excluded.append(copy.deepcopy(n))
            continue
        kept.append(_node_v2(n, state, set01))
    out.update(schema_version=nodes.SCHEMA_VERSION, set_rev=1, nodes=kept, batches=[], batch_seq=0,
               graph_member_refs=dict(set01.get("member_refs") or {}), member_digest={},
               legacy={"from_schema": nodes.LEGACY_SCHEMA_VERSION, "status": set01.get("status"),
                       "confirmed_at": set01.get("confirmed_at"), "confirmed_by": set01.get("confirmed_by"),
                       "graph_version": set01.get("graph_version"), "proposer": set01.get("proposer"),
                       "previous": copy.deepcopy(set01.get("previous") or []),
                       "member_digest": set01.get("member_digest"), "excluded_nodes": excluded})
    out["history"] = list(out.get("history") or []) + [store_io.history_row("convert", {"detail": {
        "from": nodes.LEGACY_SCHEMA_VERSION, "to": nodes.SCHEMA_VERSION, "state": state,
        "excluded_hidden": [n["node_id"] for n in excluded], "excluded_kept": sorted(keep_excluded)}}, at)]
    return out


def legacy_view(set02):
    """0.2 집합의 legacy로 다시 만든 0.1 모양 집합(결과만 0.1로 남은 경우 1단계를 다시 돌리려고)."""
    lg = set02.get("legacy") or {}
    return {"graph_id": set02.get("graph_id"), "project_id": set02.get("project_id"),
            "graph_version": lg.get("graph_version", set02.get("graph_version")),
            "status": lg.get("status") or "proposed", "confirmed_at": lg.get("confirmed_at"),
            "confirmed_by": lg.get("confirmed_by"), "previous": lg.get("previous") or [],
            "history": set02.get("history") or [],
            "nodes": [{k: v for k, v in n.items() if k in ("node_id", "name", "members", "screen")}
                      for n in set02["nodes"]] + list(lg.get("excluded_nodes") or [])}


# ---------------------------------------------------------------- 3단계: 결과

def upgrade_results(carried01, set02, deviations, at=None):
    """이은 0.1 모양 결과 → 0.2 결과. 칸 열쇠는 결과가 적어 둔 편차 목록의 deviation_id → item_id로 바꾼다.
    집합에 없는 구간(숨긴 제외 구간)의 손댄 칸은 archived_cells(legacy_excluded)로, 손대지 않은 빈 칸은 버린다."""
    item_of = {d.get("deviation_id"): d.get("item_id") for d in carried01.get("deviations") or []}
    ids = {n["node_id"] for n in set02["nodes"]}
    archived = [dict(a, at=a.get("at", at), by=a.get("by")) for a in carried01.get("archived_cells") or []]
    cells = []
    for c in carried01.get("cells") or []:
        cell = dict(copy.deepcopy(c), item_id=c.get("item_id") or item_of.get(c.get("deviation_id")), node_rev=1)
        if c.get("node_id") not in ids:
            if _touched(c):
                archived.append({"cell": cell, "reason": "legacy_excluded", "at": at, "by": None})
            continue
        cells.append(cell)
    out = {k: copy.deepcopy(v) for k, v in carried01.items()
           if k not in ("study_nodes_ref", "cells", "archived_cells", "schema_version")}
    out.update(schema_version=res.SCHEMA_VERSION, graph_version=set02.get("graph_version"),
               deviation_chart={"file": res.DEVIATION_CHART}, cells=cells, archived_cells=archived,
               legacy={"from_schema": res.LEGACY_SCHEMA_VERSION, "study_nodes_ref": carried01.get("study_nodes_ref"),
                       "carried_from": carried01.get("carried_from")})
    out.pop("carried_from", None)
    return res.reconcile(out, set02, deviations, at)


def results_from_legacy(results01, set02, deviations, at=None):
    """집합은 0.2인데 결과만 0.1인 경우(§2.5 다시 시작 표 넷째 줄): legacy로 1·3단계를 다시 돈다."""
    set01 = legacy_view(set02)
    carried, _report = carry_legacy(set01, results01, deviations)
    return upgrade_results(carried, set02, deviations, at)


# ---------------------------------------------------------------- 한 번에(순수)

def _keep_excluded(set01, carried01):
    """칸에 항목이 있는 스크리닝 제외 구간 ID(적용됨 구간으로 남김, V-5)."""
    if carried01 is None:
        return set()
    with_entries = {c["node_id"] for c in carried01.get("cells") or [] if c.get("entries")}
    return {n["node_id"] for n in set01["nodes"]
            if (n.get("screen") or {}).get("status") == "excluded" and n["node_id"] in with_entries}


def convert(set01, results01, deviations, at=None):
    """(집합 0.2, 결과 0.2 또는 None, 보고). 파일을 쓰지 않는다."""
    carried, report = carry_legacy(set01, results01, deviations)
    set02 = upgrade_set(set01, _keep_excluded(set01, carried), at)
    res02 = None if carried is None else upgrade_results(carried, set02, deviations, at)
    return set02, res02, report


# ---------------------------------------------------------------- 쓰기(nodes.load_fp가 부름)

def _conversion_id(fp):
    return "cv-" + hashlib.sha256(str(fp).encode("utf-8")).hexdigest()[:12]


def _write_backup(path, data):
    """원본 바이트를 <이름>.v0.1.bak.json에 쓴다. 같은 내용이 이미 있으면 그대로 두고, 다른 내용이면 새 이름을 쓴다."""
    target = backup_path(path)
    if os.path.isfile(target):
        with open(target, "rb") as fh:
            if fh.read() == data:
                return target
        target = store_io.unused_name(target[:-5] + "%s.json")
    store_io.write_bytes(target, data, expect=None)
    return target


def keep_original(path):
    """path 파일의 지금 바이트를 <이름>.v0.1.bak.json에 보관한다(같은 내용이 있으면 그대로)."""
    data, _fp = store_io.read_bytes(path)
    if data is not None:
        _write_backup(path, data)


def _read_only(set02, why):
    out = dict(set02, read_only=why)
    _log.warning("검토구간 0.1 → 0.2 변환을 저장하지 못함: %s", why)
    return out, None


def on_load(set01, data, graph, path, fp, deviations=None, at=None):
    """0.1 집합 파일(path, 읽은 바이트 data, 지문 fp)을 0.2로 바꾸고 (집합, 새 지문)을 돌려준다.
    쓰지 못하면 (read_only를 붙인 집합, None)."""
    devs = deviations if deviations is not None else res.load_deviations()
    rpath = res._readable_path(set01.get("project_id"), set01["graph_id"])
    rdata, rfp = store_io.read_bytes(rpath)
    try:
        r_doc = res.read_fp(rpath)[0] if rdata is not None else None
    except ValueError as exc:
        set02 = upgrade_set(set01, (), at)
        return _read_only(set02, "분석 결과 파일을 읽지 못해 변환하지 않음(%s)" % exc)
    if r_doc is not None and r_doc.get("schema_version") == res.SCHEMA_VERSION:
        if (r_doc.get("conversion") or {}).get("source_set_fp") != fp:
            set02 = upgrade_set(set01, (), at)
            return _read_only(set02, "분석 결과는 이미 0.2로 바뀌었는데 그 뒤 검토구간 파일이 바뀜(옛 앱이 고친 것으로 보임). "
                                     "백업 %s와 비교해 정리해야 함" % backup_path(path))
        legacy = (r_doc.get("conversion") or {}).get("set_keep_excluded") or []
        set02 = upgrade_set(set01, set(legacy), at)
        set02["conversion"] = dict(r_doc["conversion"])
        try:
            _write_backup(path, data)
            return set02, store_io.write_json(path, set02, expect=fp, sort_keys=False)
        except (OSError, store_io.Conflict) as exc:
            return _read_only(set02, "검토구간 0.2를 쓰지 못함(%s)" % exc)
    set02, res02, report = convert(set01, r_doc, devs, at)
    conv = {"conversion_id": _conversion_id(fp), "source_set_fp": fp, "at": at or store_io.now_utc(),
            "case": report.get("case"), "archived_cells": report.get("archived", 0),
            "set_keep_excluded": sorted(n["node_id"] for n in set02["nodes"] if (n.get("screen") or {}).get("status")
                                        == "excluded")}
    set02["conversion"] = conv
    try:
        _write_backup(path, data)
        if res02 is not None:
            _write_backup(rpath, rdata)
    except OSError as exc:
        return _read_only(set02, "변환 전 백업을 쓰지 못해 바꾸지 않음(%s)" % exc)
    try:
        if res02 is not None:
            res02["conversion"] = conv
            res.write(res.store_path(set01.get("project_id"), set01["graph_id"]), res02,
                      expect=rfp if rpath == res.store_path(set01.get("project_id"), set01["graph_id"]) else None)
        return set02, store_io.write_json(path, set02, expect=fp, sort_keys=False)
    except (OSError, store_io.Conflict) as exc:
        return _read_only(set02, "변환한 파일을 쓰지 못함(%s). 다음에 열 때 이어서 바꿈" % exc)
