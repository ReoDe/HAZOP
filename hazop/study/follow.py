"""판 이전을 프로젝트 문서(⑥ 초기사건 문서, FMEA, 잠재 후보 판단)에 잇는다. 무엇이 무엇으로 가는지는 집합 이력의 판 이전 줄
(hazop.study.migrate), 어디에 id가 있는지는 등록부(hazop.study.idmap.FIELDS의 IE·FMEA·LATENT)가 맡고, 여기서는 어느 줄부터
적용할지(판 표지)와 쓰는 순간의 판 확인을 맡는다. 근거: docs/units/2026-11-13-drawing-knowledge/evidence/migration-map-design.md
14절, docs/specs/ie-output-design.md §8.3.

- 판 표지 ref_versions {집합 graph_id: {"graph_version", "step"}}: 문서의 참조가 어느 판의 것이고 그 집합의 몇째 판 이전 줄(step)
  까지 옮겨졌는지. ⑤ 결과의 version_migrations[].step과 같은 셈이다. 표지가 있으면 그 뒤 줄만 적용하고(앞 판으로 돌아와도
  다시 적용하지 않음), 줄들이 지금 판까지 빠짐없이 이어지지 않으면(집합을 백업에서 되돌림, 잘린 이력, 새로 제안) 이어졌다는
  것을 증명하지 못한 것이다. 판 문자열이 같으면 내용이 같은 그래프라 참조가 그대로 맞다(줄 번호만 다시 찍음).
- 쓰는 순간의 판: 그래프를 보고 참조를 쓰는 함수(FMEA 가져오기·고치기, 잠재 후보 판단 저장, ⑥ 규칙 초안)는 mark_for로 문서의
  표지와 그 그래프 판을 맞대 보고, 다르면(다시 추출 뒤 검토구간을 열기 전) Stale로 거절한다. 표지가 없으면 그 판을 표지로
  찍는다(step None: 그 판에서 시작하는 판 이전 줄부터 적용). 그래서 옛 표지 아래 새 판 참조가 저장되지 않는다.
- 읽기 길: 읽는 쪽은 디스크의 집합 이력으로 메모리에서 이어 옮긴다(catch_up). 새 판 그래프로 계산하는 화면은 view로 그 판에
  맞춘 사본을 쓴다(집합을 열기 전이면 메모리에서 판 이전, 파일은 쓰지 않음).
- 표지가 없는 문서(M3 전에 쓴 것)는 문서의 기록마다 시각(at)이 있고 그 시각이 모두 어느 두 판 이전 줄 사이에 들며 집합 이력이
  문서보다 먼저 시작했을 때만 그 사이 판에서 쓴 것으로 본다. 그 밖에는(시각 없는 기록, 판 이전이 시각 사이에 낌, 문서보다
  늦게 만든 집합, 옮긴 기록은 있는데 표지가 없음) 증명하지 못한 것이다. 이 집합의 도면을 가리키는 값이 하나도 없으면 지금
  판으로 표지만 찍는다.
- 증명하지 못하면 이 집합 도면의 참조를 모두 묘비로 한다(M2 결과와 같은 원칙). 까닭은 ref_migrations[].unproven에, 묘비가 된
  자리의 원래 값은 ref_migrations[].lost에 적고, 파일에 없던 묘비를 쓰기 전에는 옛 파일을 백업한다(backup_new_tombs).
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

NO_TIME = "언제 쓴 기록인지 알 수 없어 어느 도면 기준인지 정하지 못함"
MIXED = "기록을 쓰는 사이에 도면이 다시 읽혀 어느 도면 기준인지 정하지 못함"
YOUNGER = "구간 이력이 기록보다 늦게 시작해 어느 도면 기준인지 정하지 못함"
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


def slots(doc, kind):
    """[(공간, 값)] 등록된 자리의 id 값 전부(차례 고정, 열쇠 꼴은 참조 부분만, 공간은 REF 또는 EID)."""
    out = []
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
            out.append((idmap.EID if space == idmap.EID else idmap.REF, v))
    return out


def _values(doc, kind):
    """(참조들, entity_id들). 등록된 자리의 살아 있는 값."""
    refs, eids = set(), set()
    for space, v in slots(doc, kind):
        if not idmap.is_tomb(v):
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
        if have == want:  # 판 문자열은 내용 해시라 같은 판이면 참조가 그대로 맞다(줄 번호만 다시 찍음)
            return [], None
        if type(step) is int and 0 <= step < len(rows):
            start = rows[step - 1][1].get("to") if step else rows[0][1].get("from")
            if start == have and migrate._end([d for _a, d in rows[step:]], have) == want:
                return [d for _a, d in rows[step:]], None
        elif step is None:  # 그래프를 보고 쓰며 찍은 표지(집합의 줄 번호를 모름): 그 판에서 시작하는 줄이 하나뿐일 때만
            starts = [i for i, (_a, d) in enumerate(rows) if d.get("from") == have]
            todo = [d for _a, d in rows[starts[0]:]] if len(starts) == 1 else None
            if todo and migrate._end(todo, have) == want:
                return todo, None
        return None, BROKEN
    if any(isinstance(m, dict) and m.get("graph_id") == gid for m in doc.get("ref_migrations") or []):
        return None, BROKEN  # 옮긴 적이 있는데 표지를 잃음: 시각으로 미루어 보면 두 번 적용할 수 있다
    if not _touches(doc, kind, node_set):
        return [], None
    times = _times(doc, kind)
    if times is None:
        return None, NO_TIME
    first, last = min(times), max(times)
    born = [h.get("at") for h in node_set.get("history") or [] if isinstance(h, dict) and isinstance(h.get("at"), str)]
    if not born or min(born) > first:
        # 문서보다 늦게 만든 집합(새로 제안 등)의 이력은 문서의 판을 말해 주지 않는다. 판 이전 줄이 없어도 그 사이에 다시
        # 추출했을 수 있다(구간을 새로 제안). M3 뒤 문서는 쓸 때 그래프 판을 표지로 찍어(mark_for) 이 길을 타지 않는다
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


def _times(doc, kind):
    """문서에 사람이 쓴 기록의 시각들. 기록 하나라도 시각이 없으면 None(어느 판에서 쓴 것인지 모름)."""
    out = []
    for p in TIMES[kind]:
        for h, k in idmap.walk(doc, p[:-len(".at")]):
            t = h[k].get("at") if isinstance(h[k], dict) else None
            if not (isinstance(t, str) and t):
                return None
            out.append(t)
    return out or None


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
    """FMEA: 대상이 묘비가 된 행은 대응 실패(match none)로 보이고, 승인 행은 가져옴으로 되돌린다(승인은 도면 구성요소에
    대응한 행만). 되돌린 행 ID 목록."""
    out = []
    for rid, r in sorted(doc["rows"].items()):
        if not idmap.is_tomb(r.get("ref")):
            continue
        r["match"] = "none"
        if r.get("status") == "approved":
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
    old = slots(doc, kind)
    total = {"changed": 0, "lost": 0, "found": 0}
    unregistered = set()
    for t in tables:
        out, rep = idmap.apply(out, kind, t)
        for k in total:
            total[k] += rep[k]
        unregistered.update(rep["unregistered"])
    if out is doc:
        out = copy.deepcopy(doc)
    # 묘비가 된 자리의 원래 값(묘비 id는 해시라 되돌릴 수 없으므로 문서에 남김)
    lost = {b: a for (_s, a), (_t, b) in zip(old, slots(out, kind)) if idmap.is_tomb(b) and not idmap.is_tomb(a)}
    after = AFTER.get(kind, lambda _d, _a: [])(out, at)
    row = {"at": at, "graph_id": gid, "from": (rows[0].get("from") if rows else None), "to": want, "step": mark["step"],
           "refs_changed": total["changed"] - total["lost"] - total["found"], "refs_lost": total["lost"],
           "refs_found": total["found"], "unregistered": sorted(unregistered),
           **({"unproven": why} if why else {}), **({"reopened": after} if after else {}),
           **({"lost": dict(sorted(lost.items()))} if lost else {})}
    out["ref_versions"] = dict(out.get("ref_versions") or {}, **{gid: mark})
    out["ref_migrations"] = list(out.get("ref_migrations") or []) + [row]
    return out, row


# ---------------------------------------------------------------- 쓰는 쪽: 쓰는 순간의 그래프 판

STALE = "도면이 다시 읽혀 바뀌었습니다. 검토구간 패널에서 '도면 변경 반영하기'를 눌러 반영을 마친 뒤 하세요"


class Stale(ValueError):
    """문서의 참조는 옛 판인데 새 판 그래프로 고치거나 내보내려 함(다시 추출 뒤 검토구간을 열기 전)."""


def mark_for(doc, graph_id, version):
    """그래프(graph_id·판)를 보고 참조를 쓰기 전에 부른다. 문서의 판 표지가 그 판과 다르면 Stale(옛 표지 아래 새 판 참조를
    쓰지 않음). 표지가 없으면 그 판으로 찍은 사본을 돌려준다(집합의 줄 번호를 모르므로 step None, 뒤의 판 이전은 그 판에서
    시작하는 줄부터)."""
    if not graph_id or not version:
        return doc
    m = (doc.get("ref_versions") or {}).get(graph_id)
    if isinstance(m, dict):
        if m.get("graph_version") != version:
            raise Stale(STALE)
        return doc
    out = copy.copy(doc)
    out["ref_versions"] = dict(doc.get("ref_versions") or {}, **{graph_id: {"graph_version": version, "step": None}})
    return out


def view(doc, kind, graph):
    """읽기 전용: 문서를 그래프 판에 맞춘 사본(파일을 쓰지 않음). 다시 추출 뒤 검토구간을 열기 전이면 디스크의 집합을
    메모리에서 판 이전해 같은 줄로 옮기고, 그럴 수 없으면 이 그래프의 참조를 모두 묘비로 한다. 표지가 없거나 같은 판이면 그대로."""
    gid, ver = graph.get("graph_id"), graph.get("graph_version")
    m = (doc.get("ref_versions") or {}).get(gid)
    if not isinstance(m, dict) or m.get("graph_version") == ver:
        return doc
    ns = next((s for s in followed(graph.get("project_id")) if s.get("graph_id") == gid), None)
    if ns is not None:
        ns2, p = migrate.migrate_set(migrate.with_refs(ns, graph), graph)
        if p["state"] in ("kept", "same") and ns2.get("graph_version") == ver:
            moved = follow(doc, kind, ns2)[0]
            if ((moved.get("ref_versions") or {}).get(gid) or {}).get("graph_version") == ver:
                return moved
    bare = {"graph_id": gid, "graph_version": ver, "graph_member_refs": {}, "history": []}
    return idmap.apply(doc, kind, unproven_table(doc, kind, bare))[0]


def backup_new_tombs(path, doc, kind, label="판이전묘비"):
    """문서를 쓰기 전에 부른다. 파일에 없던 묘비를 쓰게 되면(읽을 때 옮긴 묘비를 사람이 저장) 옛 파일을 먼저 백업하고 백업
    경로를 돌려준다. 원래 값은 ref_migrations[].lost에도 남는다. 백업하지 못하면 OSError(쓰지 말 것)."""
    from hazop import store_io
    data, _fp = store_io.read_bytes(path)
    if data is None:
        return None
    try:
        before = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    had = {v for _s, v in slots(before, kind) if idmap.is_tomb(v)} if isinstance(before, dict) else set()
    if {v for _s, v in slots(doc, kind) if idmap.is_tomb(v)} - had:
        return store_io.backup_file(path, label)
    return None


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



def documents(project_id):
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
    for kind, path, problems in documents(pid):
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
