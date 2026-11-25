"""등록된 DEXPI 도면을 같은 도면의 새 파일로 바꿀 때 사람 고침을 새 파일의 기록으로 옮긴다(HZ-PLN-22 §4.2.1).

옛 파일에 자리가 없던 대상(계기, 노즐 없는 설비)은 사람 고침의 지문에 at이 없다. 새 파일에는 자리가 생겨 corrections._same이 다른 대상으로
본다. 여기서는 옛 추출과 새 추출을 나란히 놓고, id·종류·태그가 같고 그 태그가 양쪽에서 하나뿐일 때만 지문을 새 추출의 것으로 바꿔 적는다.
원래 값 표시(§6.9)가 있는 파일은 표시를 빼고 읽은 값끼리 견준다. 옛 파일이 표시 없는 파일이어도, 새 파일이 표시 없는 파일이어도 같다.
애매하면 잇지 않는다. 잇지 않은 고침도 기록에 남고(held) 적용되지 않는다. 옛 기록 파일은 바꾸지 않는다.
고침을 적용하는 길(corrections.apply)은 건드리지 않으므로 drawio·PDF 도면과 기준 추출에는 닿지 않는다.
"""

import collections
import copy
import hashlib
import json
import os

from hazop import paths, store_io
from hazop.extract import ai_review, confirmation, corrections, ids
from hazop.extract.adapters import dexpi_origin

MIN_MARKS = 3               # 알아볼 수 있는 구성요소가 이보다 적게 맞으면 같은 도면으로 보지 않는다
HELD_TARGET = "carry-held"  # 남긴 add_* 연산의 target. add_*는 대상이 없어야 적용되므로 옛 앱도 적용하지 않는다

# 잇지 않은 까닭(rows[].why)
WHY = {"not_of_old_file": "옛 파일에서도 적용되지 않던 고침", "gone": "새 파일에 그 id가 없음", "duplicate_id": "같은 id가 둘 이상",
       "relation": "자리를 모르는 배관·계장선(태그가 없어 확인할 수 없음)", "made_id": "파일에 없어 읽을 때 지은 id", "no_tag": "태그가 없음",
       "no_kind": "종류를 모름", "kind_changed": "종류가 다름", "tag_changed": "태그가 다름", "text_changed": "글자가 다름", "tag_not_unique": "같은 태그가 둘 이상",
       "moved": "자리나 내용이 달라짐", "not_for_kind": "표시된 종류에는 할 수 없는 고침",
       "not_alone": "같은 자리에 다른 것이 있고 그 id들이 달라짐",
       "in_file": "사람이 더한 것이 이미 파일에 있음", "needs_left": "남긴 고침이 더한 것에 기댐", "unknown": "까닭을 읽을 수 없음"}
REFUSALS = {"not_dexpi": "DEXPI 도면끼리만 잇습니다.", "other_project": "프로젝트가 다릅니다.", "other_page": "쪽이 다릅니다.",
            "number_unknown": "파일에 도면 번호가 없어 같은 도면인지 알 수 없습니다.",
            "other_drawing": "도면 번호나 제목, 구성요소가 달라 같은 도면으로 볼 수 없습니다.",
            "corrupt": "기록이나 추출 결과를 읽을 수 없습니다.",
            "new_has_edits": "새 도면에 이미 사람 고침이나 사람이 정한 AI 후보가 있어 합치지 않습니다."}


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
    known = [_marks(dexpi_origin.plain_view(x)) for x in (old, new)]
    same = len(known[0] & known[1])
    if same < MIN_MARKS or 2 * same <= len(known[0]):
        raise Refused("other_drawing")


# ---------------------------------------------------------------- 고침 하나하나
class _Sheet:
    """추출 하나. fp: 지금 값의 지문(고침이 적는 것). plain: 표시를 빼고 읽은 값의 지문(견주는 것). 표시가 없으면 둘이 같다."""

    def __init__(self, extraction):
        self.fp = corrections._fingerprints(extraction)
        self.extraction, self.ops, self._final = extraction, [], None
        self.marks = {n["source_object_id"]: n for n in extraction["nodes"] if dexpi_origin.PLAIN in n}
        self.marked_nodes = extraction["nodes"]
        extraction = dexpi_origin.plain_view(extraction)
        self.plain = corrections._fingerprints(extraction)
        self.made = ids.made_ids(extraction)
        everything = [x for key in ("nodes", "relations", "unresolved_connectors") for x in extraction[key]]
        self.twice = {k for k, n in collections.Counter(x["source_object_id"] for x in everything).items() if n > 1}
        self.tags = collections.Counter(_tag_key(n.get("tag")) for n in extraction["nodes"])
        self.soid = {n["local_id"]: n["source_object_id"] for n in extraction["nodes"]}
        self.nodes = [(n, fp["at"], _tag_key(n.get("tag"))) for n, fp in ((n, self.plain[n["source_object_id"]]) for n in extraction["nodes"])]
        self.lines = collections.Counter((r.get("kind"), frozenset(self.soid.get(e.get("node_local_id")) for e in r["endpoints"]))
                                         for r in extraction["relations"])

    def final(self, sid):
        """사람 고침을 모두 거친 노드. 없으면 빈 것."""
        if self._final is None:
            done = corrections.apply(self.extraction, [o for o in self.ops if not o.get("held")])
            self._final = {n["source_object_id"]: n for n in done["nodes"]}
        return self._final.get(sid) or {}

    def standing(self, base):
        """같은 자리(반올림)에서 base와 같은 대상으로 보일 수 있는 id들. corrections._same과 같은 관용을 쓴다(모르는 종류·태그가 채워진 것,
        배관이 측정선이 된 것). 관계의 끝 id는 순번이라 보지 않는다."""
        mine = {k: v for k, v in base.items() if k != "ends"}
        return {sid for sid, fp in self.plain.items() if ("ends" in fp) == ("ends" in base)
                and corrections._same(mine, {k: v for k, v in fp.items() if k != "ends"})}

    def holding(self, add):
        """사람이 더한 것(add: _final의 값)과 같아 보이는 것의 수 (태그로, 자리로)."""
        if add["op"] == "add_relation":
            return (self.lines[(add["kind"], frozenset((add["from"], add["to"])))], 0)
        return self._alike(add, self.nodes)

    def holding_marked(self, add, old):
        """old에 없던 id 가운데 표시된 값이 사람이 더한 것과 같아 보이는 것이 있는가(사람이 더한 것을 내보내면 새 id로 나간다)."""
        rows = [(n, self.fp[n["source_object_id"]]["at"], _tag_key(n.get("tag"))) for n in self.marked_nodes
                if dexpi_origin.PLAIN in n and n["source_object_id"] not in old.fp]
        return add["op"] == "add_node" and any(self._alike(add, rows))

    @staticmethod
    def _alike(add, rows):
        x, y, w, h = add["bbox"]
        tag = _tag_key(add.get("tag"))
        return (sum(1 for _n, _at, t in rows if tag and t == tag),
                sum(1 for n, at, _t in rows if at and n.get("kind") == add["kind"] and x - 1 <= at[0] <= x + w + 1 and y - 1 <= at[1] <= y + h + 1))


MARKED_WHY = {"kind": "kind_changed", "tag": "tag_changed", "label_text": "text_changed"}


def _marks_differ(sid, old, new):
    """두 파일의 표시가 서로 다른 설비를 말하면 그 까닭, 아니면 None. 새 표시가 사람이 고쳐 놓은 값이면 다른 것이 아니다."""
    a, b = old.marks.get(sid), new.marks.get(sid)
    if a is None or b is None:
        return None
    return next((why for field, why in MARKED_WHY.items() if (a.get(field) or None) != (b.get(field) or None)
                 and (old.final(sid).get(field) or None) != (b.get(field) or None)), None)


def _judge(sid, base, old, new):
    """고침이 가리키는 대상 하나 → ("same", None) | ("link", None) | ("left", 까닭)."""
    was, now, given = old.fp.get(sid), new.fp.get(sid), base
    if was is None or not corrections._same(base, was):
        return "left", "not_of_old_file"
    if was != old.plain[sid]:    # 표시가 바꾼 값에 남긴 고침: 파일만 읽은 값으로 견준다
        base = old.plain[sid]
    was, now, found = old.plain[sid], new.plain.get(sid), now
    if now is None:
        return "left", "gone"
    if sid in old.twice or sid in new.twice:
        return "left", "duplicate_id"
    differ = _marks_differ(sid, old, new)
    if differ:
        return "left", differ
    if base.get("at") is not None:
        if not corrections._same(base, now):
            return "left", "moved"
        settled = {y for y in set(old.fp) & set(new.fp) if "ends" in old.fp[y] and old.fp[y]["kind"] != base["kind"]
                   and all(old.fp[y][k] == new.fp[y].get(k) for k in ("kind", "ends"))}     # 두 파일에서 같은 다른 종류의 선
        a, b = old.standing(base) - settled, new.standing(base) - settled
        if a != b and max(len(a), len(b)) > 1:
            return "left", "not_alone"
        return ("same" if corrections._same(given, found) else "link"), None
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
    return "link" if now["at"] is not None or not corrections._same(given, found) else "same", None


def _bound(sid):
    return str(sid).startswith(corrections.MANUAL_PREFIX)


def _value(op):
    return op["value"] if isinstance(op.get("value"), dict) else {}


def _final(add, ops):
    """더한 것이 뒤 고침까지 거친 모습. 새 파일에는 이 모습으로 들어 있다."""
    out, mine = dict(_value(add), op=add["op"]), corrections.MANUAL_PREFIX + str(add.get("op_id"))
    for o in ops:
        v = _value(o)
        if o.get("target") == mine:
            out.update({"set_tag": {"tag": v.get("tag")}, "set_kind": {"kind": v.get("kind")}}.get(o.get("op"), {}))
            if o.get("op") == "set_endpoint":
                out["from" if v.get("end") == "source" else "to"] = v.get("node")
    return out


def _refs(op):
    v = _value(op)
    return [(sid, (op.get("refs") or {}).get(sid) or {}) for sid in corrections._refs(v)]


def _judge_op(op, ops, old, new):
    """연산 하나(더한 것에 기댄 몫은 빼고) → (갈래, 까닭, 이을 id들)."""
    if op.get("held"):
        why = op["held"].get("why") if isinstance(op["held"], dict) else None
        return "left", why if why in WHY else "unknown", ()
    if op.get("op") in ("add_node", "add_relation"):
        add = _final(op, ops)
        if any(n > o for n, o in zip(new.holding(add), old.holding(add))) or new.holding_marked(add, old):
            return "left", "in_file", ()
    target = op.get("target")
    pieces = ([(target, op.get("base") or {})] if target and not _bound(target) else []) + _refs(op)
    judged = [(sid,) + _judge(sid, base, old, new) for sid, base in pieces]
    why = next((w for _sid, outcome, w in judged if outcome == "left"), None)
    if why:
        return "left", why, ()
    linked = {sid for sid, outcome, _w in judged if outcome == "link"}
    return ("linked" if linked else "same"), None, linked


def _needs(op):
    """이 연산이 가리키는, 사람이 더한 것의 id."""
    return [x for x in [op.get("target")] + [_value(op).get(k) for k in corrections.REF_KEYS] if isinstance(x, str) and _bound(x)]


def _moved(op, outcome, why, linked, new):
    """새 기록에 적을 연산."""
    op = copy.deepcopy(op)
    if outcome == "left" and not op.get("held"):
        # 지문을 그대로 두면 같은 자리의 다른 대상에 옮겨 붙을 수 있다(corrections._rematch). 원래 값은 held에 남긴다
        op["held"] = {"why": why, "base": op.get("base"), "refs": op.get("refs")}
        if "ai_candidate" in op:    # 같은 번호의 새 후보가 이 고침으로 수락된 것처럼 되지 않게(ai_review.reconcile)
            op["held"]["ai_candidate"] = op.pop("ai_candidate")
        op["base"], op["refs"] = None, {}
        if not op.get("target"):
            op["target"] = HELD_TARGET
    elif outcome == "linked":
        before = {sid: fp for sid, fp in [(op.get("target"), op.get("base"))] + _refs(op) if sid in linked}
        op["base_before"] = dict(before, **(op.get("base_before") or {}))
        if op.get("target") in linked:
            op["base"] = new.fp[op["target"]]
        op["refs"] = {sid: new.fp[sid] if sid in linked else fp for sid, fp in (op.get("refs") or {}).items()}
    return op


class _Moves:
    """기록의 연산 전부(지금 것과 지운 것)를 함께 가른다. 더한 것을 남기면 거기에 기댄 고침도 남는다."""

    def __init__(self, ops, removed, old, new):
        self.new, self.verdicts, everything = new, {}, list(ops) + list(removed)
        old.ops = list(ops)
        self.old = old
        for op in everything:
            self.verdicts[id(op)] = _judge_op(op, ops, old, new)
        gone = None
        while gone != (now := {corrections.MANUAL_PREFIX + str(o.get("op_id")) for o in everything if self.verdicts[id(o)][0] == "left"}):
            gone = now
            for op in everything:
                if self.verdicts[id(op)][0] != "left" and any(x in gone for x in _needs(op)):
                    self.verdicts[id(op)] = ("left", "needs_left", ())
        if new.marks:
            self._leave_what_the_kind_refuses(list(ops), removed)

    def _leave_what_the_kind_refuses(self, ops, removed):
        """이은 고침을 실제 순서로 적용해, 옛 파일에서는 되던 것이 표시된 종류 때문에 새 파일에서 안 되면 남긴다."""
        def done(extraction, seq):
            return set((corrections.apply(extraction, seq).get("corrections") or {}).get("applied") or ())
        for seq, asked in [(ops, ops)] + [(ops + [op], [op]) for op in removed]:
            mine = [op for op in asked if self.verdicts[id(op)][0] != "left" and self.old.fp.get(op.get("target"), {}).get("kind")
                    != self.new.fp.get(op.get("target"), {}).get("kind")]
            if mine:
                was, now = done(self.old.extraction, seq), done(self.new.extraction, self.move(seq))
                for op in mine:
                    if op["op_id"] in was and op["op_id"] not in now:
                        self.verdicts[id(op)] = ("left", "not_for_kind", ())

    def move(self, ops):
        return [_moved(o, *self.verdicts[id(o)], self.new) for o in ops]

    def rows(self, ops):
        return [{"op_id": o.get("op_id"), "target": o.get("target"), "outcome": self.verdicts[id(o)][0], "why": self.verdicts[id(o)][1]} for o in ops]


def move_ops(ops, old_extraction, new_extraction):
    """연산 목록 → (옮긴 연산 목록, [{op_id, target, outcome: same|linked|left, why}]). 입력은 바꾸지 않는다."""
    moves = _Moves(ops, [], _Sheet(old_extraction), _Sheet(new_extraction))
    return moves.move(ops), moves.rows(ops)


# ---------------------------------------------------------------- 기록 파일
def _extraction(name):
    with open(os.path.join(paths.safe_join(paths.output_root("extract"), name), "extraction.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _decided(c):
    return c.get("status") in ("accepted", "rejected") or bool(c.get("decided_at"))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _split_candidates(doc, rows, old, new):
    """사람이 정한 후보 → (옮길 것, 얼릴 것). 대상과 상대가 새 파일에서도 같은 대상일 때만 옮긴다. 후보에는 지문이 없어 옛 추출의 것으로 본다."""
    left = {r["op_id"] for r in rows if r["outcome"] == "left"}
    kept, frozen = [], []
    for c in (doc or {}).get("candidates") or []:
        if not _decided(c):
            continue
        about = [c.get("target")] + [v for v in c.get("values") or [] if c.get("field") == "connection" and v in old.fp]
        good = all(_judge(sid, old.fp.get(sid) or {}, old, new)[0] != "left" for sid in about) and c.get("op_id") not in left
        (kept if good else frozen).append(copy.deepcopy(c))
    return kept, frozen + copy.deepcopy((doc or {}).get("frozen") or [])


def _put_candidates(old_name, new_name, new_extraction, rows, old, new, taken):
    """사람이 정한 후보를 새 이름의 후보 문서에 적는다. 얼린 후보(frozen)는 candidates 밖의 칸이라 제안·수락·다시 묻기에 쓰이지 않는다.
    이미 적었으면 아무것도 안 한다. 새 이름에 기계가 만든 제안만 있으면 합치되, 사람이 고쳤거나 정한 대상의 제안은 뺀다. → 상태."""
    kept, frozen = _split_candidates(ai_review.load_doc(old_name), rows, old, new)
    have = ai_review.load_doc(new_name)
    if have is not None and old_name in (have.get("carried_from") or []):
        return "already"
    if not kept and not frozen and (have is None or not taken):
        return "none"
    if have is not None and any(_decided(c) for c in have["candidates"]):
        return "refused"
    doc = have or ai_review.new_doc(new_name, new_extraction)
    closed = taken | {c.get("target") for c in kept}
    doc["candidates"] = kept + [c for c in doc["candidates"] if c.get("target") not in closed]
    if frozen:
        doc["frozen"] = frozen
    doc["carried_from"] = list(doc.get("carried_from") or []) + [old_name]
    ai_review.save_doc(doc)
    return "carried"


def _put_reverted(old_name, new_name):
    """옛 도면의 자동 확정을 사람이 통째로 되돌렸으면 그 되돌림만 한 번 옮긴다(확정은 옮기지 않음). 뒤에 사람이 다시 시킨 것은 덮지 않는다."""
    cell = confirmation._auto_cell(confirmation._read_record(old_name)[0])
    if cell is None or cell["result"] != "reverted":
        return
    log = confirmation._read_record(new_name)[0].get("log") or []
    if not any(e.get("action") == "auto_carried" and e.get("from") == old_name for e in log):
        confirmation.carry_auto(old_name, new_name)


def _changed(then, ops):
    now = {str(o.get("op_id")): _digest(o) for o in ops}
    return sum(1 for k in set(then) | set(now) if then.get(k) != now.get(k))


def carry(old_name, new_name, by, at=None, dry_run=False):
    """옛 추출(old_name)의 사람 고침·사람이 정한 AI 후보·자동 확정 되돌림을 새 추출(new_name)의 기록으로 옮겨 쓴다. 같은 도면이 아니거나 읽을
    수 없는 기록이면 Refused(아무것도 쓰지 않음). 고침 기록을 먼저 쓰고 후보와 되돌림을 뒤에 쓴다. 중간에 끊기면 다시 부를 때 빠진 것만 마저
    쓴다(그사이 사람이 새로 고친 것은 그대로). 이미 옮긴 뒤 옛 기록이 바뀌었으면 쓰지 않고 already_stale로 알린다. 쪽 확정은 옮기지 않는다.
    그래프는 부르는 쪽이 다시 짓는다.
    → {"state": none|preview|carried|already|already_stale, "rows", "candidates": none|carried|already|refused, "changed": 바뀐 고침 수}."""
    if not str(by or "").strip():
        raise ValueError("옮긴 사람 이름이 있어야 함")
    corrections.check_person(by)
    try:
        return _carry(old_name, new_name, by, at, dry_run)
    except (Refused, store_io.Conflict, FileNotFoundError):
        raise
    except (AttributeError, KeyError, TypeError, IndexError, ValueError) as exc:
        raise Refused("corrupt") from exc


def _carry(old_name, new_name, by, at, dry_run):
    record = corrections.load(old_name)
    ops = (record or {}).get("ops") or []
    have, fp = corrections.load_fp(new_name)
    done = next((e["carry"] for e in (have or {}).get("log") or [] if (e.get("carry") or {}).get("from") == old_name), None)
    if done is not None:    # 기록의 carried_from은 다음 저장(corrections.save_fp)에서 빠지므로 log로 안다
        if done["record"] != _digest(record):
            return {"state": "already_stale", "rows": [], "candidates": "none", "changed": _changed(done["ops"], ops)}
    ai_old, ai_have = ai_review.load_doc(old_name), ai_review.load_doc(new_name)
    marked = ai_have is not None and old_name in (ai_have.get("carried_from") or [])
    if done is None and (have is not None or (ai_have is not None and not marked and any(_decided(c) for c in ai_have["candidates"]))):
        raise Refused("new_has_edits")
    cell = confirmation._auto_cell(confirmation._read_record(old_name)[0])
    if record is None and not any(_decided(c) for c in (ai_old or {}).get("candidates") or []) and (cell is None or cell["result"] != "reverted"):
        return {"state": "none", "rows": [], "candidates": "none", "changed": 0}
    old_ex, new_ex = _extraction(old_name), _extraction(new_name)
    check_same_drawing(old_ex, new_ex)
    old, new = _Sheet(old_ex), _Sheet(new_ex)
    log = (record or {}).get("log") or []
    moves = _Moves(ops, [o for e in log for o in e.get("removed_ops") or []], old, new)
    rows = moves.rows(ops)
    if dry_run:
        return {"state": "preview", "rows": rows, "candidates": "none", "changed": 0}
    if done is None and record is not None:
        # 지운 고침도 같은 규칙으로 옮긴다: 이어졌거나 그대로인 것은 다시 하기가 되고, 되돌린 AI 값의 자리가 지켜진다
        out = [dict(e, removed_ops=moves.move(e["removed_ops"])) if e.get("removed_ops") else copy.deepcopy(e) for e in log]
        out.append({"at": at or store_io.now_utc(), "by": by, "action": "save", "added": [], "removed": [], "removed_ops": [], "carry": {
            "from": old_name, "record": _digest(record), "ops": {str(o.get("op_id")): _digest(o) for o in ops},
            "left": [{"op_id": r["op_id"], "why": r["why"]} for r in rows if r["outcome"] == "left"],
            "linked": [r["op_id"] for r in rows if r["outcome"] == "linked"]}})
        corrections._stamp_old_graph(new_name)
        doc = dict(record, extraction_name=new_name, drawing_number=new_ex["drawing"].get("drawing_number"), ops=moves.move(ops), log=out,
                   carried_from=list(dict.fromkeys(list(record.get("carried_from") or []) + [old_name])))
        store_io.write_json(corrections.store_path(new_name), doc, expect=fp)
    # 이번에 이어졌거나 그대로인 대상만: 남긴 고침의 id는 새 파일에서 다른 것일 수 있다
    taken = {r["target"] for r in rows if r["target"] and r["outcome"] != "left"} if done is None else set()
    candidates = _put_candidates(old_name, new_name, new_ex, rows, old, new, taken)
    _put_reverted(old_name, new_name)
    return {"state": "already" if done is not None or (record is None and marked) else "carried", "rows": [] if done else rows,
            "candidates": candidates, "changed": 0}
