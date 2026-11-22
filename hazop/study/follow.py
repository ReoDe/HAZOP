"""판 이전을 프로젝트 문서(⑥ 초기사건 문서, FMEA, 잠재 후보 판단)에 잇는다. 무엇이 무엇으로 가는지는 집합 이력의 판 이전 줄
(hazop.study.migrate), 어디에 id가 있는지는 등록부(hazop.study.idmap.FIELDS의 IE·FMEA·LATENT)가 맡고, 여기서는 어느 줄부터
적용할지(판 표지)만 정한다. 근거: docs/units/2026-11-13-drawing-knowledge/evidence/migration-map-design.md §M3.

- 판 표지 ref_versions {집합 graph_id: {"graph_version", "step"}}: 문서의 참조가 그 집합의 몇째 판 이전 줄(step)까지 옮겨졌는지.
  ⑤ 결과의 version_migrations[].step과 같은 셈이다. 표지가 있으면 그 뒤 줄만 적용하고(앞 판으로 돌아와도 다시 적용하지 않음),
  줄들이 지금 판까지 빠짐없이 이어지지 않으면(집합을 백업에서 되돌림, 잘린 이력) 이어졌다는 것을 증명하지 못한 것이다.
- 표지가 없는 문서(M3 전에 쓴 것)는 문서에 적힌 시각(at)이 모두 어느 두 판 이전 줄 사이에 들 때만 그 사이 판에서 쓴 것으로
  보고 그 뒤 줄을 적용한다 [추론: 앱은 집합을 연 뒤(판 이전을 마친 뒤) ⑥을 고친다]. 판 이전 줄이 문서 시각 사이에 끼었거나,
  시각이 없는 기록이 있거나, 집합 이력이 문서보다 늦게 시작하거나(구간을 새로 제안), 옮긴 기록(ref_migrations)은 있는데 표지가
  없으면 증명하지 못한 것이다. 이 집합의 도면을 가리키는 값이 하나도 없으면 지금 판으로 표지만 찍는다.
- 증명하지 못하면 이 집합 도면의 참조를 모두 묘비로 한다(M2 결과와 같은 원칙). 까닭은 ref_migrations[].unproven에 적는다.
- 프로젝트 전체 집합(graph_id "project-…")이 있으면 그 집합만 따른다(옛 도면별 집합은 화면이 쓰지 않고, 같은 도면을 두 집합이
  옮기면 두 번 적용된다). 없으면 폴더의 집합을 모두 따른다.
- 같은 입력에 두 번 적용해도 같다(표지가 지금 판이면 아무것도 하지 않음).
"""

import copy
import json
import os

from hazop import paths
from hazop.study import idmap, migrate

# 문서마다 사람이 쓴 시각이 있는 자리(표지 없는 문서의 판을 미루어 볼 때 씀)
TIMES = {idmap.IE: ("history[].at",), idmap.FMEA: ("history[].at", "imports[].at"),
         idmap.LATENT: ("judgements{}.at", "judgements{}.history[].at")}

NO_TIME = "판 표지가 없고 시각이 없는 기록이 있어 어느 판에서 쓴 참조인지 모름"
MIXED = "판 표지가 없고 문서를 쓰는 사이에 판 이전이 있어 어느 판에서 쓴 참조인지 모름"
YOUNGER = "판 표지가 없고 집합 이력이 문서보다 늦게 시작해 어느 판에서 쓴 참조인지 모름"
BROKEN = migrate.BROKEN_CHAIN


def _rows(node_set):
    """[(시각, 판 이전 줄 detail)] 차례대로."""
    return [(h.get("at"), h.get("detail") or {}) for h in node_set.get("history") or []
            if isinstance(h, dict) and h.get("op") == migrate.OP]


def drawings(node_set):
    """집합이 옮기는 도면(graph_id): 판 사진의 참조 도면, 집합 graph_id, 판 이전 줄의 도면."""
    out = {idmap.drawing_of(r) for r in (node_set.get("graph_member_refs") or {}).values()}
    out |= {x for _at, d in _rows(node_set) for x in d.get("drawings") or ()}
    return out - {None} | {node_set.get("graph_id")}


def _values(doc, kind):
    """(참조들, entity_id들). 등록된 자리의 살아 있는 값(열쇠 꼴은 참조 부분만)."""
    refs, eids = set(), set()
    for path, space in idmap.FIELDS[kind]:
        if path.endswith("{}"):
            vals = [k for h, key in idmap.walk(doc, path[:-2]) if isinstance(h[key], dict) for k in h[key]]
        else:
            vals = [h[k] for h, k in idmap.walk(doc, path)]
        for v in vals:
            if not isinstance(v, str):
                continue
            if space == idmap.HEAD:
                v = v.partition("|")[0]
            elif space == idmap.TAIL:
                v = v.partition("|")[2]
            if idmap.is_tomb(v):
                continue
            (eids if space == idmap.EID else refs).add(v)
    return refs, eids


def _mine(doc, kind, node_set):
    """(이 집합의 참조들, 이 집합의 entity_id들) 가운데 문서에 든 것. 도면 연결 구간(xlink-…)은 도면 접두가 없고 id가 양 끝
    참조의 해시라 다른 판에서 같은 id가 다른 기호 쌍을 가리킬 수 있으므로, 프로젝트 그래프 집합이면 모두 이 집합의 것으로 본다."""
    refs, eids = _values(doc, kind)
    mine = drawings(node_set)
    known = node_set.get("graph_member_refs") or {}
    linked = str(node_set.get("graph_id")).startswith("project-") or any(str(e).startswith(_XLINK) for e in known)

    def ours(x):
        return x in known or migrate._PID_ID.search(x) or linked and x.startswith(_XLINK)
    return ({r for r in refs if idmap.drawing_of(r) in mine or ours(r)}, {e for e in eids if ours(e)})


_XLINK = "xlink-"


def _touches(doc, kind, node_set):
    return any(_mine(doc, kind, node_set))


def plan(doc, kind, node_set):
    """(적용할 판 이전 줄 detail 목록, 증명하지 못한 까닭 또는 None). 빈 목록이면 할 일이 없다."""
    gid, want = node_set.get("graph_id"), node_set.get("graph_version")
    rows = _rows(node_set)
    mark = (doc.get("ref_versions") or {}).get(gid)
    if isinstance(mark, dict):
        have, step = mark.get("graph_version"), mark.get("step")
        if have == want:
            return [], None
        if type(step) is int and 0 <= step < len(rows):
            start = rows[step - 1][1].get("to") if step else rows[0][1].get("from")
            if start == have and migrate._end([d for _a, d in rows[step:]], have) == want:
                return [d for _a, d in rows[step:]], None
        return None, BROKEN
    if any(isinstance(m, dict) and m.get("graph_id") == gid for m in doc.get("ref_migrations") or []):
        return None, BROKEN  # 옮긴 적이 있는데 표지를 잃음: 시각으로 미루어 보면 두 번 적용할 수 있다
    if not _touches(doc, kind, node_set):
        return [], None
    times = [h[k] for p in TIMES[kind] for h, k in idmap.walk(doc, p)]
    if not times or not all(isinstance(t, str) and t for t in times):
        return None, NO_TIME
    first, last = min(times), max(times)
    born = [h.get("at") for h in node_set.get("history") or [] if isinstance(h, dict) and isinstance(h.get("at"), str)]
    if not born or min(born) > first:  # 문서보다 늦게 만든 집합(새로 제안 등)의 이력은 문서의 판을 말해 주지 않는다
        return None, YOUNGER
    before = [i for i, (a, _d) in enumerate(rows) if isinstance(a, str) and a < first]
    after = [i for i, (a, _d) in enumerate(rows) if isinstance(a, str) and a > last]
    if before != list(range(len(before))) or after != list(range(len(before), len(rows))):
        return None, MIXED
    have = rows[len(before) - 1][1].get("to") if before else rows[0][1].get("from") if rows else want  # 문서를 쓰던 때의 판
    todo = [d for _a, d in rows[len(before):]]
    if migrate._end(todo, have) != want:
        return None, BROKEN
    return todo, None


def unproven_table(doc, kind, node_set):
    """증명하지 못한 문서에 쓸 표: 이 집합 도면의 참조와 이 집합의 entity_id를 모두 묘비로."""
    gid, to = node_set.get("graph_id"), node_set.get("graph_version")
    t = idmap._empty_table(gid, None, to, False)
    refs, eids = _mine(doc, kind, node_set)
    t["eid"] = {e: idmap.tomb_id(gid, to, "e-" + idmap._sha8(e)) for e in sorted(eids)}
    t["ref"] = {r: idmap.tomb_id(gid, to, "r-" + idmap._sha8(r)) for r in sorted(refs)}
    t["drawings"] = sorted(drawings(node_set))
    t["unproven"] = True
    return t


def _demote_lost_rows(doc, at):
    """FMEA: 대상이 묘비가 된 승인 행은 가져옴으로 되돌린다(승인은 도면 구성요소에 대응한 행만). 되돌린 행 ID 목록."""
    out = []
    for rid, r in sorted(doc["rows"].items()):
        if r.get("status") == "approved" and idmap.is_tomb(r.get("ref")):
            r["status"] = "imported"
            out.append(rid)
    if out:
        doc["history"].append({"at": at, "op": "migrate_version", "ids": out, "to": "imported",
                               "reason": "다시 추출 뒤 대상을 찾지 못함(확인 필요)"})
    return out


AFTER = {idmap.FMEA: _demote_lost_rows}


def follow(doc, kind, node_set, at=None):
    """(문서, 보고 또는 None). 집합 하나의 판 이전 줄 가운데 아직 적용하지 않은 것을 문서에 적용한 사본. 할 일이 없으면 입력
    그대로(표지만 찍을 때도 사본). 보고는 ref_migrations에 남긴 줄과 같다."""
    from hazop.study.nodes import now_utc
    if not isinstance(node_set, dict) or node_set.get("schema_version") not in migrate.SCHEMAS:
        return doc, None
    gid, want = node_set.get("graph_id"), node_set.get("graph_version")
    rows, why = plan(doc, kind, node_set)
    mark = {"graph_version": want, "step": len(_rows(node_set))}
    if why is None and not rows:
        if (doc.get("ref_versions") or {}).get(gid) == mark:
            return doc, None
        out = copy.deepcopy(doc)
        out["ref_versions"] = dict(out.get("ref_versions") or {}, **{gid: mark})
        return out, None
    tables = [] if why else [idmap.from_record(d, gid) for d in rows]
    if any(t["partial"] for t in tables):
        why = migrate.PARTIAL_ROWS
    if why:
        tables = [unproven_table(doc, kind, node_set)]
    at = at or now_utc()
    out = doc
    total = {"changed": 0, "lost": 0, "found": 0}
    unregistered = set()
    for t in tables:
        out, rep = idmap.apply(out, kind, t)
        for k in total:
            total[k] += rep[k]
        unregistered.update(rep["unregistered"])
    if out is doc:
        out = copy.deepcopy(doc)
    after = AFTER.get(kind, lambda _d, _a: [])(out, at)
    row = {"at": at, "graph_id": gid, "from": (rows[0].get("from") if rows else None), "to": want, "step": mark["step"],
           "refs_changed": total["changed"] - total["lost"] - total["found"], "refs_lost": total["lost"],
           "refs_found": total["found"], "unregistered": sorted(unregistered),
           **({"unproven": why} if why else {}), **({"reopened": after} if after else {})}
    out["ref_versions"] = dict(out.get("ref_versions") or {}, **{gid: mark})
    out["ref_migrations"] = list(out.get("ref_migrations") or []) + [row]
    return out, row


# ---------------------------------------------------------------- 프로젝트의 집합

_CACHE = {}  # 경로 → ((mtime_ns, 크기), 집합)


def _read_set(path):
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        with open(path, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except (OSError, ValueError, RecursionError):
        doc = None
    from hazop.study.nodes import KIND
    if not (isinstance(doc, dict) and doc.get("kind") == KIND and doc.get("schema_version") in migrate.SCHEMAS
            and isinstance(doc.get("graph_id"), str)):
        doc = None
    _CACHE[path] = (sig, doc)
    return doc


def followed(project_id, node_set=None):
    """문서가 따를 집합들(디스크의 저장본). node_set을 주면 그 집합을 디스크본 대신 쓴다(방금 판 이전한 것). 프로젝트 전체
    집합이 있으면 그것만, 없으면 폴더의 집합 모두."""
    if not project_id:
        return []
    from hazop.study.nodes import store_dir
    folder = os.path.join(store_dir(), paths.safe_name(project_id))
    sets = {}
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.endswith(".json"):
                s = _read_set(os.path.join(folder, name))
                if s is not None and s.get("project_id") in (None, project_id):
                    sets[s["graph_id"]] = s
    if node_set is not None:
        sets[node_set["graph_id"]] = node_set
    whole = {g: s for g, s in sets.items() if g.startswith("project-")}
    return list((whole or sets).values())


def catch_up(doc, kind, project_id, at=None):
    """(문서, 보고 목록). 따르는 집합마다 follow. 읽는 쪽(ie.store.load·load_fmea, expect.load_judgements)이 부른다."""
    reports = []
    for s in followed(project_id):
        doc, rep = follow(doc, kind, s, at)
        if rep:
            reports.append(rep)
    return doc, reports



def _docs(project_id):
    """[(종류, 파일 경로, 모양 검사)] 판 이전을 따르는 프로젝트 문서."""
    from hazop.ie import fmea, model, store
    from hazop.kg import expect

    def latent_problems(doc):
        try:
            expect._check_store(doc, project_id, "")
        except expect.ExpectError as exc:
            return [str(exc)]
        return []
    return [(idmap.IE, store.store_path(project_id), model.problems),
            (idmap.FMEA, store.fmea_path(project_id), fmea.problems),
            (idmap.LATENT, expect.store_path(project_id), latent_problems)]


def write_after(node_set, label, at=None):
    """집합을 판 이전한 뒤(migrate.on_load) 프로젝트 문서를 같은 줄로 옮겨 쓴다. 문서마다 옛 파일을 백업한 뒤 읽은 지문으로
    원자적으로 쓰고, 읽지 못하거나 쓰지 못하면 그 문서는 두고(읽을 때 catch_up이 메모리에서 옮김) 나머지를 계속한다.
    [(종류, 보고 또는 오류 글)]을 돌려준다."""
    from hazop import store_io
    pid = node_set.get("project_id")
    if not any(s is node_set for s in followed(pid, node_set)):
        return []
    out = []
    for kind, path, problems in _docs(pid):
        try:
            data, fp = store_io.read_bytes(path)
            if data is None:
                continue
            doc = json.loads(data.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            out.append((kind, "읽지 못함: %s" % exc))
            continue
        if problems(doc):
            out.append((kind, "모양이 맞지 않아 두었음"))
            continue
        moved, rep = follow(doc, kind, node_set, at)
        if moved is doc:
            continue
        try:
            store_io.backup_file(path, label)
            store_io.write_json(path, moved, expect=fp)
        except (OSError, store_io.Conflict) as exc:
            out.append((kind, "쓰지 못함: %s" % exc))
            continue
        out.append((kind, rep))
    return out
