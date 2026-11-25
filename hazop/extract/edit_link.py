"""등록된 DEXPI 도면을 같은 도면의 새 파일로 바꿀 때 사람 고침을 새 파일의 기록으로 옮긴다(HZ-PLN-22 §4.2.1).

옛 파일에 자리가 없던 대상(계기, 노즐 없는 설비)은 사람 고침의 지문에 at이 없다. 새 파일에는 자리가 생겨 corrections._same이 다른 대상으로
본다. 여기서는 옛 추출과 새 추출을 나란히 놓고, id·종류·태그가 같고 그 태그가 양쪽에서 하나뿐일 때만 지문을 새 추출의 것으로 바꿔 적는다.
애매하면 잇지 않는다. 잇지 않은 고침도 기록에 남고(held) 적용되지 않는다. 옛 기록 파일은 바꾸지 않는다.
고침을 적용하는 길(corrections.apply)은 건드리지 않으므로 drawio·PDF 도면과 기준 추출에는 닿지 않는다.
"""

import collections
import copy
import json
import os

from hazop import paths, store_io
from hazop.extract import ai_review, corrections, ids

# 잇지 않은 까닭(rows[].why)
WHY = {"not_of_old_file": "옛 파일에서도 적용되지 않던 고침", "gone": "새 파일에 그 id가 없음", "duplicate_id": "같은 id가 둘 이상",
       "relation": "자리를 모르는 배관·계장선(태그가 없어 확인할 수 없음)", "made_id": "파일에 없어 읽을 때 지은 id", "no_tag": "태그가 없음",
       "no_kind": "종류를 모름", "kind_changed": "종류가 다름", "tag_changed": "태그가 다름", "tag_not_unique": "같은 태그가 둘 이상",
       "moved": "자리나 내용이 달라짐", "not_alone": "같은 자리에 똑같이 보이는 것이 있고 그 id들이 달라짐"}
REFUSALS = {"not_dexpi": "DEXPI 도면끼리만 잇습니다.", "other_project": "프로젝트가 다릅니다.", "other_page": "쪽이 다릅니다.",
            "number_unknown": "파일에 도면 번호가 없어 같은 도면인지 알 수 없습니다.",
            "other_drawing": "도면 번호나 제목, 구성요소가 달라 같은 도면으로 볼 수 없습니다.",
            "new_has_edits": "새 도면에 이미 사람 고침이나 AI 후보 기록이 있어 합치지 않습니다."}


class Refused(ValueError):
    """옮기지 않은 까닭. code는 REFUSALS의 열쇠."""

    def __init__(self, code):
        super().__init__(REFUSALS[code])
        self.code = code


# ---------------------------------------------------------------- 같은 도면인가
def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _in_file(extraction, field):
    """파일에 적힌 번호·제목. 등록을 거친 추출은 확정값과 파일의 값을 따로 둔다."""
    d = extraction["drawing"]
    return _text(d.get("title_block_candidates", d).get({"number": "drawing_number", "title": "title"}[field]))


def _tag_key(tag):
    return "".join(tag.split()).casefold() if isinstance(tag, str) else ""


def _marks(extraction):
    """알아볼 수 있는 구성요소의 표시 {(id, 종류, 태그 또는 자리)}."""
    fp = corrections._fingerprints(extraction)
    rows = ((n["source_object_id"], n.get("kind"), _tag_key(n.get("tag")) or tuple(fp[n["source_object_id"]]["at"] or ())) for n in extraction["nodes"])
    return {r for r in rows if r[2]}


def check_same_drawing(old, new):
    """두 추출이 같은 도면이 아니거나 같은지 알 수 없으면 Refused. 번호가 같아도 알아볼 수 있는 구성요소(태그가 있거나, 태그가
    없으면 자리를 아는 것)의 절반 넘게 새 파일에 같은 id·종류와 같은 태그(또는 같은 자리)로 있어야 한다. id는 순번이라 다른 도면에도 있고,
    번호는 임시 값이 겹칠 수 있다."""
    if any((x.get("source") or {}).get("format") != "dexpi" for x in (old, new)):
        raise Refused("not_dexpi")
    if old.get("project_id") != new.get("project_id"):
        raise Refused("other_project")
    if any(((x.get("run") or {}).get("settings") or {}).get("page_index") != 0 for x in (old, new)):
        raise Refused("other_page")     # DEXPI는 첫 쪽만 읽는다
    numbers = [_in_file(x, "number") for x in (old, new)]
    if not all(numbers):
        raise Refused("number_unknown")
    confirmed = [_text(x["drawing"].get("drawing_number")) for x in (old, new)]
    titles = [_in_file(x, "title") for x in (old, new)]
    if numbers[0] != numbers[1] or (all(confirmed) and confirmed[0] != confirmed[1]) or (all(titles) and titles[0] != titles[1]):
        raise Refused("other_drawing")
    known = [_marks(x) for x in (old, new)]
    if not known[0] or 2 * len(known[0] & known[1]) <= len(known[0]):
        raise Refused("other_drawing")


# ---------------------------------------------------------------- 고침 하나하나
def _look(fp):
    return fp.get("kind"), _tag_key(fp.get("tag")), tuple(fp["at"] or ()), "ends" in fp


class _Sheet:
    def __init__(self, extraction):
        self.fp = corrections._fingerprints(extraction)
        self.made = ids.made_ids(extraction)
        everything = [x for key in ("nodes", "relations", "unresolved_connectors") for x in extraction[key]]
        self.twice = {k for k, n in collections.Counter(x["source_object_id"] for x in everything).items() if n > 1}
        self.tags = collections.Counter(_tag_key(n.get("tag")) for n in extraction["nodes"])
        self.alike = {}     # 겉모습(종류·태그·자리, 관계인지) -> 그 id들
        for sid, fp in self.fp.items():
            self.alike.setdefault(_look(fp), set()).add(sid)


def _judge(sid, base, old, new):
    """고침이 가리키는 대상 하나 → ("same", None) | ("link", None) | ("left", 까닭)."""
    was, now = old.fp.get(sid), new.fp.get(sid)
    if was is None or not corrections._same(base, was):
        return "left", "not_of_old_file"
    if now is None:
        return "left", "gone"
    if sid in old.twice or sid in new.twice:
        return "left", "duplicate_id"
    if base.get("at") is not None:
        if not corrections._same(base, now):
            return "left", "moved"
        a, b = old.alike[_look(was)], new.alike[_look(now)]
        return ("left", "not_alone") if a != b and max(len(a), len(b)) > 1 else ("same", None)
    if "ends" in was or "ends" in now:
        return "left", "relation"
    if sid in old.made or sid in new.made:
        return "left", "made_id"
    if not _tag_key(was["tag"]):
        return "left", "no_tag"
    if not was["kind"]:
        return "left", "no_kind"
    if now["kind"] != was["kind"]:
        return "left", "kind_changed"
    if now["tag"] != was["tag"]:
        return "left", "tag_changed"
    if old.tags[_tag_key(was["tag"])] != 1 or new.tags[_tag_key(was["tag"])] != 1:
        return "left", "tag_not_unique"
    return "link" if now["at"] is not None else "same", None


def _bound(sid):
    return str(sid).startswith(corrections.MANUAL_PREFIX)


def _move(op, old, new):
    """연산 하나 → (새 기록에 적을 연산, 갈래, 까닭). 대상과 참조 가운데 하나라도 이을 수 없으면 통째로 남긴다."""
    op = copy.deepcopy(op)
    target, refs = op.get("target"), op.get("refs") or {}
    if op.get("held"):
        return op, "left", op["held"]["why"]
    pieces = [(target, op.get("base") or {})] if target and not _bound(target) else []
    value = op.get("value")
    pieces += [(sid, refs.get(sid) or {}) for sid in (corrections._refs(value) if isinstance(value, dict) else [])]
    judged = [(sid,) + _judge(sid, base, old, new) for sid, base in pieces]
    why = next((w for _sid, outcome, w in judged if outcome == "left"), None)
    if why:     # 지문을 그대로 두면 같은 자리의 다른 대상에 옮겨 붙을 수 있다(corrections._rematch). 원래 지문은 held에 남긴다
        op["held"] = {"why": why, "base": op.get("base"), "refs": op.get("refs")}
        op["base"], op["refs"] = None, {}
        return op, "left", why
    linked = {sid for sid, outcome, _w in judged if outcome == "link"}
    if not linked:
        return op, "same", None
    op["base_before"] = {sid: base for sid, base in pieces if sid in linked}
    if target in linked:
        op["base"] = new.fp[target]
    if refs:
        op["refs"] = {sid: new.fp[sid] if sid in linked else fp for sid, fp in refs.items()}
    return op, "linked", None


def move_ops(ops, old_extraction, new_extraction):
    """연산 목록 → (옮긴 연산 목록, [{op_id, target, outcome: same|linked|left, why}]). 입력은 바꾸지 않는다."""
    old, new = _Sheet(old_extraction), _Sheet(new_extraction)
    out, rows = [], []
    for op in ops:
        moved, outcome, why = _move(op, old, new)
        out.append(moved)
        rows.append({"op_id": op.get("op_id"), "target": op.get("target"), "outcome": outcome, "why": why})
    return out, rows


# ---------------------------------------------------------------- 기록 파일
def _extraction(name):
    with open(os.path.join(paths.safe_join(paths.output_root("extract"), name), "extraction.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _moved_candidates(old_name, new_name, new_extraction):
    """새 이름의 AI 후보 문서. 사람이 정한 후보(수락·거절·되돌림)만 옮긴다. 옮길 것이 없으면 None."""
    doc = ai_review.load_doc(old_name)
    kept = [copy.deepcopy(c) for c in (doc or {}).get("candidates") or [] if c.get("status") in ("accepted", "rejected") or c.get("decided_at")]
    return dict(ai_review.new_doc(new_name, new_extraction), candidates=kept, carried_from=[old_name]) if kept else None


def carry(old_name, new_name, by, at=None, dry_run=False):
    """옛 추출(old_name)의 사람 고침·사람이 정한 AI 후보를 새 추출(new_name)의 기록으로 옮겨 쓴다. 같은 도면이 아니면 Refused(아무것도 쓰지 않음).
    이미 옮겼으면 아무것도 하지 않는다. 앞뒤 두 파일 가운데 AI 후보를 먼저 쓰고 고침 기록을 끝에 써서, 중간에 끊겨도 다시 하면 같은 끝이 된다.
    쪽 확정과 자동 확정 기록은 옮기지 않는다. 그래프는 부르는 쪽이 다시 짓는다. → {"state": none|already|preview|carried, "rows"}."""
    corrections.check_person(by)
    record = corrections.load(old_name)
    if record is None:
        return {"state": "none", "rows": []}
    have, fp = corrections.load_fp(new_name)
    if have is not None and any((e.get("carry") or {}).get("from") == old_name for e in have.get("log") or []):
        # 기록의 carried_from은 다음 저장(corrections.save_fp)에서 빠지므로 log로 안다
        return {"state": "already", "rows": []}
    ai_have = ai_review.load_doc(new_name)
    if have is not None or (ai_have is not None and old_name not in (ai_have.get("carried_from") or [])):
        raise Refused("new_has_edits")
    old, new = _extraction(old_name), _extraction(new_name)
    check_same_drawing(old, new)
    ops, rows = move_ops(record.get("ops") or [], old, new)
    if dry_run:
        return {"state": "preview", "rows": rows}
    at = at or store_io.now_utc()
    log = [dict(e, removed_ops=move_ops(e["removed_ops"], old, new)[0]) if e.get("removed_ops") else copy.deepcopy(e)
           for e in record.get("log") or []]     # 지운 고침도 함께 옮긴다: 다시 하기가 되고, 되돌린 AI 값의 자리가 지켜진다
    log.append({"at": at, "by": by, "action": "save", "added": [], "removed": [], "removed_ops": [],
                "carry": {"from": old_name, "left": [{"op_id": r["op_id"], "why": r["why"]} for r in rows if r["outcome"] == "left"],
                          "linked": [r["op_id"] for r in rows if r["outcome"] == "linked"]}})
    candidates = _moved_candidates(old_name, new_name, new)
    if candidates is not None and ai_have is None:
        ai_review.save_doc(candidates)
    corrections._stamp_old_graph(new_name)
    doc = dict(record, extraction_name=new_name, drawing_number=new["drawing"].get("drawing_number"), ops=ops, log=log,
               carried_from=list(dict.fromkeys(list(record.get("carried_from") or []) + [old_name])))
    store_io.write_json(corrections.store_path(new_name), doc, expect=fp)
    return {"state": "carried", "rows": rows}
