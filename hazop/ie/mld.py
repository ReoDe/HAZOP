"""P5 주논리도(Master Logic Diagram, MLD) 가지 대조(설계 HZ-PLN-17 §8.2 질문 6, 방법론 카드 M02·M04).

앱은 MLD를 짓지 않는다. 사람이 준 MLD 파일(대상 노형의 것)을 가져와, 잎 가지마다 대응 일반 범주에 '후보' 판정의 승인 후보가 있는지
대조한다. 앱에 예시 MLD를 넣지 않는다(대상 발전소의 완전성으로 오해될 수 있음). 가지 이름(안전기능 분류 포함)은 파일 값 그대로 쓰고
⑤의 안전기능 칸과 잇지 않는다(E9 보류). 파일을 쓰지 않는 순수 함수다(저장은 hazop.ie.store).

- 가져오는 파일 {"kind": "hazop_mld", "schema_version": "0.1", "mld_id", "title", "revision", "reactor_type", "source",
  "branches": [{"id", "name", "parent", "categories": [일반 범주 코드]}]}.
- 저장 문서 {"kind": "hazop_mld_store", "schema_version", "project_id", "mld": 가져온 파일 또는 None, "file", "imported_at", "by",
  "links": {가지 ID: [그룹 ID]}, "history": []}.
- 사람 판정(범위 밖·다른 기법·해당 없음)은 ⑥ 문서 coverage에 'MLD:<가지 ID>'로 둔다(일반 범주 대조와 같은 model.set_coverage).
"""

import copy
import json

from hazop import store_io

FILE_KIND = "hazop_mld"
KIND = "hazop_mld_store"
SCHEMA_VERSION = "0.1"
COVER_PREFIX = "MLD:"
MAX_BYTES = 2 * 1024 * 1024
MAX_BRANCHES = 2000
STATUS_LABELS = {"covered": "있음", "gap": "공백", "unmapped": "범주 없음", "not_applicable": "해당 없음"}


def empty(project_id):
    return {"kind": KIND, "schema_version": SCHEMA_VERSION, "project_id": project_id, "mld": None, "file": None,
            "imported_at": None, "by": None, "links": {}, "history": []}


def problems(doc):
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        return ["kind가 %s가 아님" % KIND]
    if not isinstance(doc.get("links"), dict) or not isinstance(doc.get("history"), list):
        return ["links·history 형식이 맞지 않음"]
    if doc.get("mld") is not None:
        return validate(doc["mld"])
    return []


def validate(mld, codes=None):
    """가져올 MLD 파일의 문제 목록. codes(일반 범주 코드 집합)를 주면 기준표에 없는 코드도 본다."""
    if not isinstance(mld, dict) or mld.get("kind") != FILE_KIND:
        return ["MLD 파일이 아님(kind가 %s여야 함)" % FILE_KIND]
    branches = mld.get("branches")
    if not isinstance(branches, list) or not branches:
        return ["branches(가지 목록)가 비었거나 목록이 아님"]
    if len(branches) > MAX_BRANCHES:
        return ["가지가 %d개를 넘음" % MAX_BRANCHES]
    out = []
    ids = {}
    for i, b in enumerate(branches):
        if not isinstance(b, dict) or not isinstance(b.get("id"), str) or not b["id"].strip() or len(b["id"]) > 40:
            out.append("%d번째 가지: id가 없거나 형식이 맞지 않음" % (i + 1))
            continue
        if b["id"] in ids:
            out.append("가지 ID 중복: %s" % b["id"])
        ids[b["id"]] = b
        if not isinstance(b.get("name"), str) or not b["name"].strip():
            out.append("%s: 이름이 없음" % b["id"])
        cats = b.get("categories", [])
        if not isinstance(cats, list) or not all(isinstance(c, str) for c in cats):
            out.append("%s: categories는 글 목록이어야 함" % b["id"])
        elif codes is not None:
            bad = [c for c in cats if c not in codes]
            if bad:
                out.append("%s: 기준표에 없는 범주 코드 %s" % (b["id"], ", ".join(bad)))
    for bid, b in ids.items():
        p = b.get("parent")
        if p is not None and p not in ids:
            out.append("%s: 없는 부모 가지 %s" % (bid, p))
    for bid in ids:  # 순환
        seen, cur = set(), bid
        while cur is not None and cur in ids:
            if cur in seen:
                out.append("%s: 부모를 따라가면 순환함" % bid)
                break
            seen.add(cur)
            cur = ids[cur].get("parent")
    return out


def read_file(path):
    """MLD JSON 파일 → dict. 크기·형식이 맞지 않으면 ValueError."""
    with open(path, "rb") as fh:
        data = fh.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("MLD 파일이 너무 큽니다(2MB 넘음)")
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("JSON이 아님: %s" % exc) from None


def _change(doc, op, at, fn, **detail):
    out = copy.deepcopy(doc)
    fn(out)
    out["history"].append(store_io.history_row(op, detail, at))
    return out


def import_mld(doc, mld, filename, by, codes, at=None):
    """MLD를 가져와 바꾼다(문제가 있으면 ValueError). 옛 판에 있던 사람 연결은 지우지 않는다(없어진 가지는 '가지 없음'으로 보임)."""
    bad = validate(mld, codes)
    if bad:
        raise ValueError("MLD를 가져오지 않았습니다: " + "; ".join(bad[:5]))
    at = at or store_io.now_utc()
    keep = {k: mld.get(k) for k in ("kind", "schema_version", "mld_id", "title", "revision", "reactor_type", "source")}
    keep["branches"] = [{"id": b["id"].strip(), "name": b["name"].strip(), "parent": b.get("parent"),
                         "categories": list(dict.fromkeys(b.get("categories") or []))} for b in mld["branches"]]

    def apply(o):
        o.update(mld=keep, file=filename, imported_at=at, by=by)
    old = (doc.get("mld") or {})
    return _change(doc, "import", at, apply, file=filename, mld_id=keep.get("mld_id"), revision=keep.get("revision"),
                   replaced=old.get("revision") if old else None)


def set_links(doc, branch_id, group_ids, at=None):
    """범주 없는 잎(또는 어느 잎이든)에 사람이 그룹을 잇는다. 빈 목록이면 지운다."""
    leaves = {b["id"] for b in leaves_of(doc)}
    if branch_id not in leaves:
        raise ValueError("MLD에 없는 잎 가지: %s" % branch_id)
    group_ids = list(dict.fromkeys(group_ids))
    if doc["links"].get(branch_id, []) == group_ids:
        return doc

    def apply(o):
        if group_ids:
            o["links"][branch_id] = group_ids
        else:
            o["links"].pop(branch_id, None)
    return _change(doc, "link", at, apply, branch=branch_id, groups=group_ids)


def leaves_of(doc):
    m = (doc or {}).get("mld")
    if not m:
        return []
    parents = {b.get("parent") for b in m["branches"]}
    return [b for b in m["branches"] if b["id"] not in parents]


def _path(by_id, bid):
    names, cur, guard = [], bid, 0
    while cur is not None and cur in by_id and guard < 100:
        names.append(by_id[cur]["name"])
        cur = by_id[cur].get("parent")
        guard += 1
    return " › ".join(reversed(names))


def compare(doc, candidates, groups, coverage):
    """{"source", "branches": [{id, name, path, categories, status, disposition, group_ids}], "by_category": {코드: [가지]}}.
    MLD를 받지 않았으면 None. candidates·groups는 인계 묶음의 것(승인 항목만), coverage는 ⑥ 문서의 사람 판정.
    잎 가지: 대응 범주에 판정이 '후보'인 승인 후보가 있거나, 이은 그룹에 승인 후보가 있으면 '있음'. 대응 범주가 없고 이은 그룹도 없으면
    '범주 없음', 아니면 '공백'. 사람 판정이 '해당 없음'이면 '해당 없음'(일반 범주 대조와 같은 규칙)."""
    m = (doc or {}).get("mld")
    if not m:
        return None
    by_id = {b["id"]: b for b in m["branches"]}
    yes = {c["category"] for c in candidates if c.get("judgement") == "yes" and c.get("category")}
    live_groups = {g["group_id"] for g in groups if g.get("members")}
    out, by_cat = [], {}
    for b in leaves_of(doc):
        linked = [g for g in doc["links"].get(b["id"], [])]
        if set(b["categories"]) & yes or set(linked) & live_groups:
            status = "covered"
        elif not b["categories"] and not linked:
            status = "unmapped"
        else:
            status = "gap"
        done = (coverage or {}).get(COVER_PREFIX + b["id"]) if status != "covered" else None
        if done and done.get("disposition") == "not_applicable":
            status = "not_applicable"
        row = {"id": b["id"], "name": b["name"], "path": _path(by_id, b["id"]), "categories": list(b["categories"]),
               "status": status, "disposition": done, "group_ids": linked,
               "missing_groups": [g for g in linked if g not in {x["group_id"] for x in groups}]}
        out.append(row)
        for c in b["categories"]:
            by_cat.setdefault(c, []).append(row)
    gone = sorted(set(doc["links"]) - {b["id"] for b in leaves_of(doc)})
    return {"source": {"mld_id": m.get("mld_id"), "title": m.get("title"), "revision": m.get("revision"),
                       "reactor_type": m.get("reactor_type"), "file": doc.get("file"), "imported_at": doc.get("imported_at")},
            "branches": out, "by_category": by_cat, "gone_links": gone}
