"""새 웹 화면 3단계 ⑥ 초기사건의 엔진 쪽(앱 틀 규격 §2.1·§2.3 ⑥). Qt를 import하지 않는다.

- **읽기** `ie`(요약: 머리 수치·그룹 목록·묶이지 않은 후보·완전성 대조·품질 경고·판 지문), `ie/group/<IEG>`(그룹 상세: 정의·소속 후보·표제·최종상태·기본사건·
  확정 조건). 읽기는 인계 묶음(hazop.ie.bundle.build_bundle)을 메모리에서 만들어 그 값을 그대로 보인다 — 화면과 내보내는 묶음이 같은 계산을 쓴다. 파일을 쓰지 않는다.
- **명령** `ie.suggest`(규칙 초안 만들기), `ie.confirm`·`ie.reopen`(그룹 확정·확정 풀기), 편집(A10, 이전 화면 ⑥과 같은 model 함수):
  `ie.create_group`·`ie.move`·`ie.accept_members`(후보 묶기·옮기기·빼기·소속 확인), `ie.edit_group`·`ie.split`·`ie.delete_group`,
  `ie.add_record`·`ie.edit_record`·`ie.accept_record`·`ie.remove_record`(표제·최종상태·기본사건), `ie.set_coverage`(범주 대조 판정),
  `ie.export`(인계 묶음 Excel+JSON), `ie.replace_unreadable`(읽지 못한 파일 백업 뒤 새로 시작).
- **쓰기 대조**(이전 화면의 대조를 모두 옮김): ① 읽은 ⑥ 파일 지문(ver, 'none'은 파일이 없었다는 뜻), ② 읽은 ⑤ 결과 지문(rver,
  이전 화면의 _reload_if_results_changed), ③ 화면이 본 항목 지문(seen {"group:IEG-01": 지문, …}: 명령이 건드리는 그룹·후보·기록마다),
  ④ 프로젝트 ID(api.dispatch). 하나라도 다르면 'stale'로 거절하고 아무것도 쓰지 않는다. 저장은 ie.store.save(원자적 쓰기, expect 대조).
- **되묻기**: 그룹 지우기·기록 지우기, 그리고 확정한 그룹의 확정이 풀리는 모든 변경(초안으로 내리기, 나누기 등 저장 상태가 '확정'에서
  바뀌는 것)은 저장하지 않고 {"ask": {message, groups}}로 답한다. groups는 확정이 풀릴 그룹 ID 전부다. 웹은 카드에 글을 보이고, '계속'을
  누르면 카드가 보인 때의 ver·rver·seen 그대로 confirmed=true와 confirm_groups(카드에 보인 목록)를 붙여 다시 보낸다. 서버는 그 목록과
  실제로 확정이 풀릴 목록이 다르면 'stale'로 거절한다. 읽지 못한 파일 바꾸기는 'confirm' 오류로 되묻는다.
- 확정자·판정자는 설정의 검토자 이름이다(웹 인자 아님). 인계 묶음 Excel 위치는 창이 묻고, 같은 이름의 JSON이 있으면 창이 덮어쓸지 묻는다.
- 채팅에서 부르는 실행 함수: view_groups, move_candidates, split_group, judge_coverage. 판 지문(ver)이 없으면 거절하고, 되물을 일이
  있으면 'confirm' 오류(글에 확정이 풀릴 그룹)를 올린다(confirmed와 confirm_groups를 붙여 다시 부른다).
- 인계 묶음 내보내기는 ie.store.load_synced로 IEC 대응을 먼저 저장한다(저장하지 못하면 내보내지 않음).
- P5(설계 HZ-PLN-17 §8.2): 읽기 `ie/fmea`(FMEA 행·전기·제어 구간·구성요소 목록), `ie/mld`(MLD 잎 가지 대조). 명령 `ie.fmea_template`(양식
  내보내기, 위치는 창이 묻는다), `ie.fmea_import`(파일은 창 훅 pick_import가 묻는다), `ie.fmea_edit`·`ie.fmea_status`·`ie.fmea_mark`,
  `ie.mld_import`·`ie.mld_link`. FMEA·MLD 쓰기는 그 파일의 지문(fver·mver)과 화면이 본 행 지문(seen "fmea:FM-001")을 대조한다.
  MLD 가지 판정은 ie.set_coverage에 code 'MLD:<가지 ID>'. 채팅 실행 함수: view_fmea, set_fmea_status, mark_ec_node, view_mld, link_mld_branch,
  confirm_mld_branch. 다시 가져오기 충돌은 `ie.fmea_resolve`, 규칙 대조 가지의 사람 확인은 `ie.mld_confirm`. FMEA·MLD 파일 하나를 읽지 못해도
  ⑥ 화면과 내보내기는 막지 않고(그 파일은 '읽을 수 없음', 묶음 '읽는 법'에 적음) `ie.fmea_replace_unreadable`·`ie.mld_replace_unreadable`로
  백업 뒤 새로 시작한다.
"""

import hashlib
import json
import logging
import os

from hazop.ie import bundle, fmea, mld, model
from hazop.ie import store as ie_store
from hazop.study import nodes
from hazop.study import results as res

LOG = logging.getLogger("hazop.shell.api_ie")


def _api():
    from hazop.shell import api
    return api


def _results():
    from hazop.shell import api_results
    return api_results


def _context(engine):
    """(pg, 구간 집합, 결과 문서, ie 문서, ie 지문) 또는 (None, 이유)."""
    R = _results()
    pg = R._pg(engine, strict=False)
    if pg is None:
        return None, "프로젝트 그래프가 없습니다. 도면을 먼저 추출하세요."
    ns, legacy = R._node_set(pg)
    if legacy:
        return None, "옛 판 구간 파일입니다. 구간 패널에서 새 판으로 바꾸세요."
    if not [n for n in ns["nodes"] if nodes.is_active(n)]:
        return None, "확정한 구간이 아직 없습니다. 구간을 확정하고 분석한 뒤 초기사건을 봅니다."
    try:
        doc, _fp = R._load(ns)
    except (OSError, ValueError) as exc:
        return None, "분석 결과 파일을 읽을 수 없습니다(%s)." % str(exc)[:120]
    try:
        ie_doc, ie_fp = ie_store.load(ns.get("project_id"))
    except ie_store.Unreadable as exc:
        return None, "초기사건 파일을 읽을 수 없습니다: %s" % "; ".join(exc.problems[:2])[:200]
    return (pg, ns, doc, ie_doc, ie_fp), None


def _view_doc(ie_doc, doc, ns):
    """읽기용: 승인 항목과 승인 FMEA 행과 맞춘 문서(사본을 돌려줄 뿐 저장하지 않는다)."""
    return ie_store.sync_all(ie_doc, doc, ns, _sides(ns)[0])


def _sides(ns):
    """(FMEA 문서 또는 None, MLD 저장 문서 또는 None, 읽지 못한 파일 이름). 하나를 못 읽어도 ⑥ 화면과 내보내기는 막지 않는다
    (그 파일만 '읽을 수 없음'으로 보이고 백업 뒤 새로 시작하는 길을 둔다)."""
    return ie_store.load_sides(ns.get("project_id"))


def _build(doc, ns, pg, ie_doc, now):
    """인계 묶음(화면·대조·내보내기가 같은 계산). FMEA·MLD 문서를 함께 넘기고, 읽지 못한 파일은 묶음 '읽는 법'에 적는다."""
    fdoc, mdoc, bad = _sides(ns)
    return bundle.build_bundle(doc, ns, pg, ie_doc, now, fmea=fdoc, mld=mdoc, unreadable=bad)


def _ver(fp):
    return fp or "none"


def _rver(ctx):
    """⑤ 결과 파일 지문(화면이 본 ⑤ 판). 파일이 없으면 'none'."""
    _pg, ns, _doc, _ie, _fp = ctx
    try:
        return _results()._ver(res.load_fp(ns)[1])
    except (OSError, ValueError):
        return "none"


def _sha(obj):
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def item_fps(b):
    """{"group:IEG-01"|"member:IEC-001"|"heading:H-01"|"end_state:ES-01"|"basic_event:BE-001"|"coverage:<범주>": 지문}.
    화면이 본 항목 지문. 그룹 지문은 그룹 행·소속 후보·붙은 표제·최종상태를 함께 담아, ⑤ 결과가 바뀌어 소속 후보 글이 달라져도 다르다."""
    cands = {c["candidate_id"]: c for c in b["candidates"]}
    out = {}
    for c in b["candidates"]:
        out["member:" + c["candidate_id"]] = _sha(c)
    for h in b["top_events"]:
        out["heading:" + h["heading_id"]] = _sha(h)
    for e in b["end_states"]:
        out["end_state:" + e["end_state_id"]] = _sha(e)
    for be in b["basic_events"]:
        out["basic_event:" + be["be_id"]] = _sha(be)
    for r in b["completeness"]:
        if r.get("code"):
            out["coverage:" + r["code"]] = _sha(r)
    for x in (b.get("mld") or {}).get("branches") or []:
        out["coverage:" + mld.COVER_PREFIX + x["id"]] = _sha(x)
    for g in b["groups"]:
        gid = g["group_id"]
        out["group:" + gid] = _sha({"g": g, "m": [cands.get(m) for m in g["members"]],
                                    "h": [h for h in b["top_events"] if gid in h["group_ids"]],
                                    "e": [e for e in b["end_states"] if gid in e["group_ids"]]})
    return out


def summary(engine):
    ctx, why = _context(engine)
    if ctx is None:
        return {"available": False, "reason": why}
    pg, ns, doc, ie_doc, ie_fp = ctx
    ie_doc = _view_doc(ie_doc, doc, ns)
    b = _build(doc, ns, pg, ie_doc, nodes.now_utc())
    grouped = {m for g in b["groups"] for m in g["members"]}
    unassigned = [c for c in b["candidates"] if c["candidate_id"] not in grouped]
    status_count = {}
    for g in b["groups"]:
        status_count[g["status"]] = status_count.get(g["status"], 0) + 1
    gaps = [c for c in b["completeness"] if c["status"] == "gap"]
    fps = item_fps(b)
    unassigned = [dict(c, fp=fps.get("member:" + c["candidate_id"])) for c in unassigned]
    return {"available": True, "ver": _ver(ie_fp), "rver": _rver(ctx), "project_id": b["project_id"],
            "side_unreadable": list(b.get("unreadable_inputs") or []),
            "kpi": {"candidates": len(b["candidates"]), "unassigned": len(unassigned), "groups": len(b["groups"]),
                    "confirmed": status_count.get("confirmed", 0), "draft": status_count.get("draft", 0),
                    "warnings": len(b["warnings"]), "gaps": len(gaps), "categories": len(b["completeness"])},
            "groups": [dict(_group_row(g), fp=fps.get("group:" + g["group_id"])) for g in b["groups"]], "unassigned": unassigned,
            "completeness": [dict(r, fp=fps.get("coverage:" + r["code"]), disposition=(ie_doc.get("coverage") or {}).get(r["code"]))
                             if r.get("code") else r for r in b["completeness"]],
            "warnings": b["warnings"], "warning_summary": b["warning_summary"], "created_at": b["created_at"]}


def _group_row(g):
    return {"group_id": g["group_id"], "name": g["name"], "status": g["status"], "origin": g["origin"], "member_count": g["member_count"],
            "held_member_count": g["held_member_count"], "categories": g["categories"], "problems": g["problems"], "confirmed_by": g["confirmed_by"]}


def group_view(engine, gid):
    ctx, _why = _context(engine)
    if ctx is None:
        return None
    pg, ns, doc, ie_doc, ie_fp = ctx
    ie_doc = _view_doc(ie_doc, doc, ns)
    b = _build(doc, ns, pg, ie_doc, nodes.now_utc())
    g = next((x for x in b["groups"] if x["group_id"] == gid), None)
    if g is None:
        return None
    cands = {c["candidate_id"]: c for c in b["candidates"]}
    fps = item_fps(b)
    fp = lambda kind, rid: fps.get(kind + ":" + rid)  # noqa: E731
    rec = ie_doc["groups"].get(gid) or {}
    return {"group": dict(g, fp=fp("group", gid)), "members": [dict(cands[m], fp=fp("member", m)) for m in g["members"] if m in cands],
            "headings": [dict(h, fp=fp("heading", h["heading_id"])) for h in b["top_events"] if gid in h["group_ids"]],
            "end_states": [dict(e, fp=fp("end_state", e["end_state_id"])) for e in b["end_states"] if gid in e["group_ids"]],
            "basic_events": [dict(be, fp=fp("basic_event", be["be_id"])) for be in b["basic_events"]
                             if set(be["candidate_ids"]) & set(g["members"])],
            "editable": {k: rec.get(k) for k in model.EDITABLE["group"]},   # 고치기 칸의 지금 값(묶음 글은 표시용으로 바뀐 것이 있다)
            "records": _record_fields(ie_doc),
            "stored_status": rec.get("status"),
            "choices": {"support_ie": model.SUPPORT_IE, "role": _refs().ROLES, "actuation": _refs().ACTUATIONS,
                        "category": model.ES_CATEGORIES},
            "ver": _ver(ie_fp), "rver": _rver(ctx)}


def _refs():
    from hazop.study import refs
    return refs


def _record_fields(ie_doc):
    """표제·최종상태·기본사건의 고칠 수 있는 필드 값과 작성(origin)·상태. {"heading:H-01": {...}} (고치기 칸의 지금 값)."""
    out = {}
    for kind in ("heading", "end_state", "basic_event"):
        table = model.COLLECTIONS[kind][0]
        for rid, rec in (ie_doc.get(table) or {}).items():
            out[kind + ":" + rid] = dict({k: rec.get(k) for k in model.EDITABLE[kind]}, origin=rec.get("origin"),
                                         status=rec.get("status"))
    return out


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'ie'. 없는 자료는 None(404)."""
    api = _api()
    if len(parts) == 1:
        return api._json(summary(engine))
    if len(parts) == 2 and parts[1] == "fmea":
        data = fmea_view(engine)
        return api._json(data) if data is not None else None
    if len(parts) == 2 and parts[1] == "mld":
        data = mld_view(engine)
        return api._json(data) if data is not None else None
    if len(parts) == 3 and parts[1] == "group":
        data = group_view(engine, parts[2])
        return api._json(data) if data is not None else None
    return None


# ---------------------------------------------------------------- 쓰기

STALE = "초기사건이 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요."
STALE_RESULTS = "분석 결과가 바뀌어 저장하지 않았습니다. 바뀐 내용을 다시 읽었으니 확인한 뒤 한 번 더 눌러 주세요."
STALE_ITEM = "화면에 보이던 내용이 지금과 달라 저장하지 않았습니다(%s). 다시 읽었으니 확인한 뒤 한 번 더 눌러 주세요."


def lost_confirmations(base, new):
    """저장 상태가 '확정'이던 그룹 가운데 new에서 확정이 아닌 것(초안으로 내려감·나뉨·지움). 확정 기록이 지워지는 그룹 전부."""
    return sorted(g for g, v in base["groups"].items()
                  if v.get("status") == "confirmed" and (new["groups"].get(g) or {}).get("status") != "confirmed")


def _write(engine, a, fn, keys=None, ask=None, demote_ok=False):
    """fn(ie_doc, results, ns, pg, by) -> 새 ie 문서 또는 (새 문서, 값). 읽은 지문(ver)·⑤ 지문(rver, 있으면)·항목 지문(seen,
    있으면. keys(base, b)가 돌려주는 열쇠는 모두 있어야 한다)을 대조하고 저장한다. ask: 되물을 글. 되물을 글이 있거나 확정이 풀리는
    그룹이 있으면(demote_ok가 아니면) confirmed가 없을 때 저장하지 않고 {"ask": {message, groups}}로 답하고, confirmed가 있으면
    confirm_groups와 지금 확정이 풀릴 목록이 같아야 저장한다."""
    api = _api()
    by = engine.reviewer()
    if not by:
        raise api.CommandError("bad_args", "검토자 이름을 먼저 설정에서 입력하세요. 확정한 사람으로 남습니다.")
    ctx, why = _context(engine)
    if ctx is None:
        raise api.CommandError("failed", why)
    pg, ns, doc, ie_doc, ie_fp = ctx
    ver = a.get("ver", _ver(ie_fp))
    if (ver == "none") != (ie_fp is None) or (ie_fp is not None and ver != ie_fp):      # 'none'은 파일이 없었다는 뜻: 지금 있으면 다르다
        raise api.CommandError("stale", STALE)
    if a.get("rver") is not None and a["rver"] != _rver(ctx):
        raise api.CommandError("stale", STALE_RESULTS)
    base = _view_doc(ie_doc, doc, ns)
    if keys is not None and a.get("seen") is not None:
        b = _build(doc, ns, pg, base, nodes.now_utc())
        now = item_fps(b)
        seen = a["seen"]
        for k in keys(base, b):
            if k not in seen or seen[k] != now.get(k):
                raise api.CommandError("stale", STALE_ITEM % k.split(":", 1)[1])
    try:
        out = fn(base, doc, ns, pg, by)
    except ValueError as exc:
        raise api.CommandError("failed", str(exc)[:300])
    new, value = out if isinstance(out, tuple) else (out, None)
    if new is base or new == base:
        return {"ver": _ver(ie_fp), "changed": False, "value": value}
    lost = [] if demote_ok else lost_confirmations(base, new)
    if ask or lost:
        if not a.get("confirmed"):
            text = (ask(base) if callable(ask) else ask) if ask else ""
            if lost:
                names = ", ".join("%s(%s)" % (g, base["groups"][g].get("name", "")) for g in lost)
                text = (text + " " if text else "") + "확정이 풀리는 그룹: %s. 바꾼 뒤 다시 확정해야 합니다." % names
            return {"ver": _ver(ie_fp), "changed": False, "value": None,
                    "ask": {"message": text + " 계속할까요?", "groups": lost}}
        if sorted(a.get("confirm_groups") or []) != lost:
            raise api.CommandError("stale", "확인한 뒤 내용이 바뀌어 저장하지 않았습니다(확인한 그룹: %s, 지금 확정이 풀릴 그룹: %s). 다시 확인해 주세요."
                                   % (", ".join(sorted(a.get("confirm_groups") or [])) or "없음", ", ".join(lost) or "없음"))
    demoted = lost
    try:
        fp = ie_store.save(new, expect=ie_fp)
    except ie_store.Conflict:
        raise api.CommandError("stale", STALE)
    except (ValueError, OSError) as exc:
        raise api.CommandError("failed", "저장하지 못했습니다(%s)." % str(exc)[:200])
    engine.changed("ie", None)
    out = {"ver": fp, "changed": True, "value": value}
    if demoted:
        out["demoted"] = demoted
    return out


def _suggest(engine, a):
    return _write(engine, a, lambda base, doc, ns, pg, by: model.suggest(base, doc, pg=pg))


def _confirm(engine, a):
    return _write(engine, a, lambda base, doc, ns, pg, by: model.confirm(base, a["group_id"], doc, by, node_set=ns),
                  keys=lambda base, b: ["group:" + a["group_id"]])


def _reopen(engine, a):
    return _write(engine, a, lambda base, doc, ns, pg, by: model.reopen(base, a["group_id"]),
                  keys=lambda base, b: ["group:" + a["group_id"]], demote_ok=True)   # 확정 풀기 자체가 내리는 일


# ---------------------------------------------------------------- 편집(A10)

def _twins_in(b, iecs):
    """묶음 b에서 iecs가 합친 쌍둥이까지 넓힌 IEC 목록."""
    by = {c["candidate_id"]: c for c in b["candidates"]}
    out = []
    for i in iecs:
        out += [i] + list((by.get(i) or {}).get("merged_from") or [])
    return list(dict.fromkeys(out))


def _twins_of(base, doc, ns, pg, iecs):
    """묶음이 한 후보로 합친 쌍둥이(겹친 구간의 같은 원인, merged_from)까지 넓힌 IEC 목록. 쌍둥이는 같은 그룹에 있어야 확정된다."""
    b = _build(doc, ns, pg, base, nodes.now_utc())
    by = {c["candidate_id"]: c for c in b["candidates"]}
    out = []
    for i in iecs:
        out += [i] + list((by.get(i) or {}).get("merged_from") or [])
    return list(dict.fromkeys(out))


def _member_keys(base, iecs, extra_groups=(), b=None):
    """화면이 본 것이어야 하는 열쇠: 고른 후보, 그 후보와 쌍둥이(함께 옮겨짐)가 지금 든 그룹, 옮길 그룹."""
    every = _twins_in(b, iecs) if b is not None else list(iecs)
    groups = [base["candidates"][i]["group_id"] for i in every if i in base["candidates"]]
    return ["member:" + i for i in iecs] + ["group:" + g for g in dict.fromkeys(list(groups) + list(extra_groups)) if g]


def _create_group(engine, a):
    def fn(base, doc, ns, pg, by):
        return model.create_group(base, a["name"], _twins_of(base, doc, ns, pg, a.get("iecs") or []))
    out = _write(engine, a, fn, keys=lambda base, b: _member_keys(base, a.get("iecs") or [], (), b))
    out["group_id"] = out.pop("value")
    return out


def _move(engine, a):
    """후보를 그룹 to로 옮긴다(to가 빈 글자면 그룹에서 뺀다). 쌍둥이도 함께 옮긴다."""
    to = a.get("to") or None

    def fn(base, doc, ns, pg, by):
        d = base
        for i in _twins_of(base, doc, ns, pg, a["iecs"]):
            d = model.place(d, i, to)
        return d
    return _write(engine, a, fn, keys=lambda base, b: _member_keys(base, a["iecs"], [to] if to else [], b))


def _chat(fn, engine, a):
    """채팅 실행 함수의 공통 길: 판 지문(ver)이 없으면 거절하고, 되물을 일이 있으면 'confirm' 오류로 올린다."""
    api = _api()
    if not a.get("ver"):
        raise api.CommandError("bad_args", "초기사건 판 지문(ver)을 함께 보내야 합니다(먼저 view_groups로 읽음).")
    out = fn(engine, a)
    if out.get("ask"):
        raise api.CommandError("confirm", "%s (다시 부를 때 confirmed=true, confirm_groups=[%s])"
                               % (out["ask"]["message"], ", ".join(out["ask"]["groups"])))
    return out


def move_candidates(engine, a):
    """채팅 실행 함수: {iecs, to(그룹 ID, 빈 글자면 뺌), ver, confirmed?, confirm_groups?}."""
    return _chat(_move, engine, a)


def _accept_members(engine, a):
    def fn(base, doc, ns, pg, by):
        d = base
        for i in _twins_of(base, doc, ns, pg, a["iecs"]):
            if base["candidates"].get(i, {}).get("group_id"):
                d = model.accept(d, ("member", i))
        return d
    return _write(engine, a, fn, keys=lambda base, b: _member_keys(base, a["iecs"], (), b))


def _edit_group(engine, a):
    return _write(engine, a, lambda base, doc, ns, pg, by: model.edit(base, ("group", a["group_id"]), a["fields"]),
                  keys=lambda base, b: ["group:" + a["group_id"]])


def _split(engine, a):
    def fn(base, doc, ns, pg, by):
        return model.split(base, a["group_id"], _twins_of(base, doc, ns, pg, a["moved"]))
    out = _write(engine, a, fn, keys=lambda base, b: ["group:" + a["group_id"]])
    out["groups"] = list(out.pop("value") or [])
    return out


def split_group(engine, a):
    """채팅 실행 함수: {group_id, moved[IEC], ver, confirmed?, confirm_groups?}. (남는 쪽, 옮긴 쪽) 새 그룹 ID를 groups로."""
    return _chat(_split, engine, a)


def _delete_group(engine, a):
    gid = a["group_id"]

    def ask(base):
        g = base["groups"].get(gid) or {}
        return ("%s 그룹(%s)을 지울까요? 소속 후보 %d개는 묶이지 않은 후보가 되고, ID는 '삭제' 기록으로 남아 다시 쓰지 않습니다."
                % (gid, g.get("name", ""), len(model.members_of(base, gid))))
    return _write(engine, a, lambda base, doc, ns, pg, by: model.delete_group(base, gid),
                  keys=lambda base, b: ["group:" + gid], ask=ask)


def _record_keys(base, kind, rid):
    try:
        touching = model._groups_touching(base, (kind, rid))
    except (KeyError, ValueError):
        touching = []
    return [kind + ":" + rid] + ["group:" + g for g in touching if g]


def _add_record(engine, a):
    add = {"heading": model.add_heading, "end_state": model.add_end_state}[a["kind"]]
    out = _write(engine, a, lambda base, doc, ns, pg, by: add(base, a["group_id"], a["fields"]),
                 keys=lambda base, b: ["group:" + a["group_id"]])
    out["id"] = out.pop("value")
    return out


def _edit_record(engine, a):
    return _write(engine, a, lambda base, doc, ns, pg, by: model.edit(base, (a["kind"], a["id"]), a["fields"]),
                  keys=lambda base, b: _record_keys(base, a["kind"], a["id"]))


def _accept_record(engine, a):
    return _write(engine, a, lambda base, doc, ns, pg, by: model.accept(base, (a["kind"], a["id"])),
                  keys=lambda base, b: _record_keys(base, a["kind"], a["id"]))


def _remove_record(engine, a):
    what = {"heading": "표제", "end_state": "최종상태", "basic_event": "기본사건"}[a["kind"]]
    return _write(engine, a, lambda base, doc, ns, pg, by: model.remove(base, (a["kind"], a["id"])),
                  keys=lambda base, b: _record_keys(base, a["kind"], a["id"]),
                  ask="%s %s을(를) 지울까요? 붙어 있던 그룹에서 떨어지고, ID는 '삭제' 기록으로 남습니다." % (what, a["id"]))


def _set_coverage(engine, a):
    """빈 범주 판정. 범주 코드는 완전성 대조에 있는 것이어야 하고, 대응 그룹이 있는 범주(covered)에는 판정을 두지 않는다(지우기는 된다)."""
    disposition = a.get("disposition") or None

    def fn(base, doc, ns, pg, by):
        b = _build(doc, ns, pg, base, nodes.now_utc())
        rows = {r["code"]: r for r in b["completeness"] if r.get("code")}
        rows.update({mld.COVER_PREFIX + x["id"]: x for x in (b.get("mld") or {}).get("branches") or []})
        if a["code"] not in rows and a["code"] not in base["coverage"]:
            raise ValueError("완전성 대조에 없는 범주 코드입니다: %s" % a["code"])
        if disposition and (rows.get(a["code"]) or {}).get("status") == "covered":
            raise ValueError("%s 범주에는 대응 그룹이 있어 빈 범주 판정을 둘 수 없습니다" % a["code"])
        return model.set_coverage(base, a["code"], disposition, a.get("reason") or "", by)
    # 없는 범주 코드는 화면에 지문이 없으니 지문 대조를 건너뛰고 fn이 이유를 알린다
    return _write(engine, a, fn, keys=lambda base, b: ["coverage:" + a["code"]] if a["code"] in _coverage_codes(b) else [])


def _coverage_codes(b):
    return {r["code"] for r in b["completeness"] if r.get("code")} | {
        mld.COVER_PREFIX + x["id"] for x in (b.get("mld") or {}).get("branches") or []}


def judge_coverage(engine, a):
    """채팅 실행 함수: {code, disposition(out_of_scope·other_method·not_applicable, 빈 글자면 지움), reason, ver}."""
    return _chat(_set_coverage, engine, a)


def view_groups(engine):
    """채팅 실행 함수: 그룹 목록·묶이지 않은 후보·완전성 대조(화면 요약과 같은 값)."""
    return summary(engine)


def _replace_unreadable(engine, a):
    api = _api()
    pid = engine.project_id()
    try:
        ie_store.load(pid)
    except ie_store.Unreadable as exc:
        path = exc.path
    else:
        raise api.CommandError("failed", "초기사건 파일을 읽을 수 있어 바꾸지 않았습니다.")
    if not a.get("confirmed"):
        raise api.CommandError("confirm", "읽지 못한 파일을 data/backup 아래에 복사한 뒤 빈 문서로 바꿉니다. 그룹·표제는 다시 묶어야 하고, "
                                          "원인마다 받았던 IEC 번호는 이어지지 않습니다(옛 번호는 다시 쓰지 않음). 계속할까요? (%s)"
                               % os.path.basename(path))
    try:
        _doc, fp, saved = ie_store.replace_unreadable(pid)
    except (OSError, ValueError, ie_store.Conflict) as exc:
        raise api.CommandError("failed", "백업하지 못해 바꾸지 않았습니다(%s)." % str(exc)[:200])
    engine.changed("ie", None)
    return {"ver": fp, "backup": os.path.basename(saved)}


def _export(engine, a):
    """인계 묶음(승인 항목만, Excel + 같은 이름의 JSON). Excel 위치·덮어쓰기는 창이 묻고, 같은 이름의 JSON이 있으면 덮어쓸지 한 번 더
    묻는다(이전 화면 export_bundle). 화면이 본 ⑤ 판(rver)·⑥ 판(ver)이 지금과 다르면 내보내지 않는다."""
    api = _api()
    ctx, why = _context(engine)
    if ctx is None:
        raise api.CommandError("failed", why)
    pg, ns, doc, ie_doc, ie_fp = ctx
    if a.get("rver") is not None and a["rver"] != _rver(ctx):
        raise api.CommandError("stale", STALE_RESULTS)
    if a.get("ver") is not None and a["ver"] != _ver(ie_fp):
        raise api.CommandError("stale", STALE)
    from hazop.ie import bundle_xlsx
    now = nodes.now_utc()
    if not _build(doc, ns, pg, _view_doc(ie_doc, doc, ns), now)["candidates"]:
        raise api.CommandError("failed", "승인한 항목이 없어 인계 묶음을 만들지 않았습니다. 분석 결과에서 항목을 승인한 뒤 내보내세요.")
    path = _results()._save_path(engine, "ie", bundle_xlsx.default_stem(ns.get("project_id"), now) + ".xlsx")
    if not path:
        return {"cancelled": True}
    if not path.lower().endswith(".xlsx"):
        path += ".xlsx"
    json_path = os.path.splitext(path)[0] + ".json"
    if os.path.exists(json_path):
        ask = engine.hooks.get("confirm_overwrite_files")
        if ask is None or not ask([os.path.basename(json_path)]):
            return {"cancelled": True, "reason": "같은 이름의 JSON 파일을 덮어쓰지 않았습니다."}
    try:      # IEC 대응을 먼저 저장한다. 저장하지 못하면 내보내지 않는다(저장하지 않은 번호가 나중에 다른 원인에 붙지 않게)
        synced, _fp = ie_store.load_synced(ns.get("project_id"), doc, ns)
    except ie_store.Conflict:
        raise api.CommandError("stale", STALE)
    except (ValueError, OSError) as exc:
        raise api.CommandError("failed", "초기사건 번호를 저장하지 못해 내보내지 않았습니다(%s)." % str(exc)[:200])
    if synced is not ie_doc:
        engine.changed("ie", None)
    b = _build(doc, ns, pg, synced, now)
    try:
        path, json_path = bundle_xlsx.export(path, b)
    except (OSError, ValueError) as exc:
        raise api.CommandError("failed", "저장하지 못했습니다(파일이 열려 있으면 닫고 다시 하세요). %s" % str(exc)[:200])
    return {"path": os.path.basename(path), "json_path": os.path.basename(json_path), "candidates": len(b["candidates"]),
            "groups": len(b["groups"]), "cancelled": False}



# ---------------------------------------------------------------- P5: FMEA 입력·MLD 가지 대조(설계 §8.2)

def _row_fp(row):
    return _sha(row)


def _p5_context(engine, need=("fmea", "mld")):
    """(pg, ns, ⑤ 결과, FMEA 문서, FMEA 지문, MLD 문서, MLD 지문) 또는 CommandError. need에 든 파일만 읽어야 하고, 그 파일을
    읽지 못하면 백업 뒤 새로 시작하라고 알린다(다른 쪽 파일이 깨져도 이 쪽 쓰기는 막지 않음)."""
    api = _api()
    ctx, why = _context(engine)
    if ctx is None:
        raise api.CommandError("failed", why)
    pg, ns, doc, _ie, _fp = ctx
    pid = ns.get("project_id")
    got = {}
    for which, load_fn in (("fmea", ie_store.load_fmea), ("mld", ie_store.load_mld)):
        try:
            got[which] = load_fn(pid)
        except ie_store.Unreadable as exc:
            if which in need:
                raise api.CommandError("unreadable", "%s 파일을 읽을 수 없습니다(%s): %s. 원본을 백업하고 새로 시작할 수 있습니다."
                                       % (which.upper(), os.path.basename(exc.path), "; ".join(exc.problems[:2])[:160]))
            got[which] = (None, None)
    return (pg, ns, doc) + got["fmea"] + got["mld"]


def _analysed(doc, ns):
    picked, _left = bundle.approved_entries(doc, ns)
    return {node_id for node_id, _d, _e in picked}


def _ec_view(ns, pg, fdoc, analysed):
    rule = set(fmea.rule_nodes(ns, pg))
    ec = set(fmea.ec_nodes(ns, pg, fdoc))
    done = fmea.done_nodes(ns, fdoc)
    marks = fdoc["node_marks"]
    return [{"node_id": n["node_id"], "name": n.get("name"), "rule": n["node_id"] in rule, "mark": marks.get(n["node_id"]),
             "ec": n["node_id"] in ec, "analysed": n["node_id"] in analysed, "fmea_done": n["node_id"] in done}
            for n in ns["nodes"] if n["node_id"] in rule or n["node_id"] in marks]


def fmea_view(engine):
    """{fver, rows: [행 + row_id·fp], counts, ec_nodes, components, imports, codes}. 읽기만 한다."""
    ctx, _why = _context(engine)
    if ctx is None:
        return None
    pg, ns, doc, _ie, _fp = ctx
    try:
        fdoc, ffp = ie_store.load_fmea(ns.get("project_id"))
    except ie_store.Unreadable as exc:
        return {"unreadable": os.path.basename(exc.path), "problems": exc.problems[:3], "rows": [], "counts": {}, "ec_nodes": [],
                "components": [], "imports": [], "fver": "none"}
    from hazop.study import migrate, refs
    idx = {n["entity_id"]: n for n in pg.get("nodes") or []}
    drawing = {s["graph_id"]: s.get("drawing_number") for s in pg.get("sheets") or []}

    def matched(r):   # 대응된 구성요소(태그·도면)를 보이게(다시 이을 수 있음)
        n = idx.get(r.get("entity_id")) if r.get("entity_id") else None
        return {"tag": refs.node_text(n), "drawing": drawing.get(refs.drawing_of(r.get("ref"))) or refs.drawing_of(r.get("ref"))} if n else None
    rows = [dict(r, row_id=rid, fp=_row_fp(r), matched=matched(r)) for rid, r in sorted(fdoc["rows"].items())]
    counts = {k: sum(r["status"] == k for r in rows) for k in fmea.STATUSES}
    counts["unmatched"] = sum(1 for r in rows if not r.get("ref"))
    homes = {}
    for n in ns["nodes"]:
        for m in n.get("members") or []:
            homes.setdefault(m, []).append(n["node_id"])
    comps = [{"entity_id": n["entity_id"], "tag": refs.node_text(n), "kind": n.get("kind") or "", "nodes": homes.get(n["entity_id"], [])}
             for n in pg.get("nodes") or [] if n.get("tag") and migrate.ref_of(n, pg.get("graph_id"))]
    return {"fver": _ver(ffp), "rows": rows, "counts": counts, "ec_nodes": _ec_view(ns, pg, fdoc, _analysed(doc, ns)),
            "components": comps[:3000], "imports": fdoc["imports"][-5:], "codes": fmea.FAILURE_MODE_CODES,
            "statuses": fmea.STATUSES, "matches": fmea.MATCHES}


def view_fmea(engine):
    """채팅 실행 함수: FMEA 행·전기·제어 구간(화면 읽기와 같은 값)."""
    return fmea_view(engine)


def _fmea_write(engine, a, fn, keys=()):
    """FMEA 문서 쓰기: 검토자, FMEA 지문(fver), 화면이 본 행 지문(seen)을 대조하고 저장한다."""
    api = _api()
    by = engine.reviewer()
    if not by:
        raise api.CommandError("bad_args", "검토자 이름을 먼저 설정에서 입력하세요.")
    pg, ns, doc, fdoc, ffp, _m, _mfp = _p5_context(engine, ("fmea",))
    if a.get("fver") != _ver(ffp):
        raise api.CommandError("stale", "FMEA가 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요.")
    if a.get("seen") is not None:
        for k in keys:
            rid = k.split(":", 1)[1]
            now = _row_fp(fdoc["rows"][rid]) if rid in fdoc["rows"] else None
            if a["seen"].get(k) != now:
                raise api.CommandError("stale", STALE_ITEM % rid)
    try:
        new = fn(fdoc, pg, ns, doc, by)
    except ValueError as exc:
        raise api.CommandError("failed", str(exc)[:300])
    new, value = new if isinstance(new, tuple) else (new, None)
    if new is fdoc:
        return {"fver": _ver(ffp), "changed": False, "value": value}
    try:
        fp = ie_store.save_fmea(new, expect=ffp)
    except ie_store.Conflict:
        raise api.CommandError("stale", "FMEA가 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요.")
    except (ValueError, OSError) as exc:
        raise api.CommandError("failed", "저장하지 못했습니다(%s)." % str(exc)[:200])
    engine.changed("ie", None)
    return {"fver": fp, "changed": True, "value": value}


PICK_FILTERS = {"fmea": ["FMEA 양식 (*.xlsx)"], "mld": ["MLD 파일 (*.json)"]}


def _pick(engine, kind):
    """창의 파일 고르기(window.py 훅 pick_import(kind, filters) → 경로 목록, 취소면 []). 웹은 경로를 보내지 않는다.
    고르는 동안 프로젝트가 바뀌면 거절한다(고르기 전에 잡은 프로젝트 ID와 대조)."""
    api = _api()
    hook = engine.hooks.get("pick_import")
    if hook is None:
        raise api.CommandError("failed", "이 창에서는 파일을 고를 수 없습니다(창의 파일 고르기 기능 없음).")
    pid = engine.project_id()
    got = hook(kind, PICK_FILTERS[kind])
    if isinstance(got, (list, tuple)):
        got = got[0] if got else None
    if got and engine.project_id() != pid:
        raise api.CommandError("wrong_project", "파일을 고르는 동안 프로젝트가 바뀌어 가져오지 않았습니다.")
    return got


def _fmea_template(engine, a):
    api = _api()
    pg, ns, doc, fdoc, _ffp, _m, _mfp = _p5_context(engine, ("fmea",))
    ec = set(fmea.ec_nodes(ns, pg, fdoc))
    idx = {n["entity_id"]: n for n in pg.get("nodes") or []}
    from hazop.study import refs
    ec_rows = [(n["node_id"], refs.node_text(idx[m]), idx[m].get("kind") or "") for n in ns["nodes"] if n["node_id"] in ec
               for m in n.get("members") or [] if m in idx and idx[m].get("tag")]
    path = _results()._save_path(engine, "fmea", "FMEA-%s.xlsx" % (ns.get("project_id") or "프로젝트"))
    if not path:
        return {"cancelled": True}
    if not path.lower().endswith(".xlsx"):
        path += ".xlsx"
    try:
        from hazop.export.study_xlsx import save_workbook
        save_workbook(fmea.template_workbook(fdoc, ec_rows), path)
    except (OSError, ValueError) as exc:
        raise api.CommandError("failed", "저장하지 못했습니다(파일이 열려 있으면 닫고 다시 하세요). %s" % str(exc)[:200])
    return {"cancelled": False, "path": os.path.basename(path), "rows": len(fdoc["rows"])}


def _fmea_import(engine, a):
    path = _pick(engine, "fmea")
    if not path:
        return {"cancelled": True}
    try:
        got, problems = fmea.read_rows(path)
    except Exception as exc:  # noqa: BLE001 - 깨진 Excel은 이유만 알린다
        raise _api().CommandError("failed", "Excel을 읽지 못했습니다(%s)." % str(exc)[:160])
    if not got:
        raise _api().CommandError("failed", "가져올 행이 없습니다. %s" % " ".join(problems)[:200])
    name = os.path.basename(path)
    out = _fmea_write(engine, a, lambda fdoc, pg, ns, doc, by: fmea.import_rows(fdoc, got, pg, ns, name, by))
    rep = out.pop("value")
    rep["problems"] = problems + rep["problems"]
    return dict(out, cancelled=False, file=name, report={k: v if k == "problems" else len(v) for k, v in rep.items()},
                reopened=rep["reopened"], unmatched=rep["unmatched"])


def _fmea_edit(engine, a):
    return _fmea_write(engine, a, lambda fdoc, pg, ns, doc, by: fmea.edit_row(fdoc, a["row_id"], a["fields"], pg, ns),
                       keys=["fmea:" + a["row_id"]])


def _fmea_status(engine, a):
    return _fmea_write(engine, a, lambda fdoc, pg, ns, doc, by: fmea.set_status(fdoc, a["row_ids"], a["status"], by),
                       keys=["fmea:" + r for r in a["row_ids"]])


def set_fmea_status(engine, a):
    """채팅 실행 함수: {row_ids, status(approved·excluded·imported), fver}. fver 없이는 거절."""
    if not a.get("fver"):
        raise _api().CommandError("bad_args", "FMEA 판 지문(fver)을 함께 보내야 합니다(먼저 view_fmea로 읽음).")
    return _fmea_status(engine, a)


def _fmea_mark(engine, a):
    def fn(fdoc, pg, ns, doc, by):
        if a["node_id"] not in {n["node_id"] for n in ns["nodes"]}:
            raise ValueError("없는 구간: %s" % a["node_id"])
        return fmea.set_node_mark(fdoc, a["node_id"], a["mark"] or None)
    return _fmea_write(engine, a, fn)


def mark_ec_node(engine, a):
    """채팅 실행 함수: {node_id, mark(include·exclude·빈 글자), fver}."""
    if not a.get("fver"):
        raise _api().CommandError("bad_args", "FMEA 판 지문(fver)을 함께 보내야 합니다(먼저 view_fmea로 읽음).")
    return _fmea_mark(engine, a)


def mld_view(engine):
    """{mver, loaded, source, branches(대조 결과 + fp), groups(이을 수 있는 그룹)}. 읽기만 한다."""
    ctx, _why = _context(engine)
    if ctx is None:
        return None
    pg, ns, doc, ie_doc, _fp = ctx
    try:
        mdoc, mfp = ie_store.load_mld(ns.get("project_id"))
    except ie_store.Unreadable as exc:
        return {"unreadable": os.path.basename(exc.path), "problems": exc.problems[:3], "mver": "none", "loaded": False,
                "branches": [], "gone_links": [], "groups": [], "statuses": mld.STATUS_LABELS}
    b = _build(doc, ns, pg, _view_doc(ie_doc, doc, ns), nodes.now_utc())
    m = b.get("mld")
    fps = item_fps(b)
    return {"mver": _ver(mfp), "loaded": m is not None, "source": (m or {}).get("source"),
            "branches": [dict(x, fp=fps.get("coverage:" + mld.COVER_PREFIX + x["id"])) for x in (m or {}).get("branches") or []],
            "gone_links": (m or {}).get("gone_links") or [],
            "groups": [{"group_id": g["group_id"], "name": g["name"]} for g in b["groups"]],
            "statuses": mld.STATUS_LABELS}


def view_mld(engine):
    """채팅 실행 함수: MLD 잎 가지 대조(화면 읽기와 같은 값)."""
    return mld_view(engine)


def _mld_write(engine, a, fn, keys=()):
    api = _api()
    by = engine.reviewer()
    if not by:
        raise api.CommandError("bad_args", "검토자 이름을 먼저 설정에서 입력하세요.")
    pg, ns, doc, _f, _ffp, mdoc, mfp = _p5_context(engine, ("mld",))
    if a.get("mver") != _ver(mfp):
        raise api.CommandError("stale", "MLD가 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요.")
    if keys and a.get("seen") is not None:
        view = mld_view(engine)
        now = {"coverage:" + mld.COVER_PREFIX + x["id"]: x["fp"] for x in view["branches"]}
        for k in keys:
            if a["seen"].get(k) != now.get(k):
                raise api.CommandError("stale", STALE_ITEM % k.rsplit(":", 1)[1])
    try:
        new = fn(mdoc, by)
    except ValueError as exc:
        raise api.CommandError("failed", str(exc)[:300])
    if new is mdoc:
        return {"mver": _ver(mfp), "changed": False}
    try:
        fp = ie_store.save_mld(new, expect=mfp)
    except ie_store.Conflict:
        raise api.CommandError("stale", "MLD가 다른 곳에서 바뀌어 저장하지 않았습니다. 다시 읽었으니 한 번 더 눌러 주세요.")
    except (ValueError, OSError) as exc:
        raise api.CommandError("failed", "저장하지 못했습니다(%s)." % str(exc)[:200])
    engine.changed("ie", None)
    return {"mver": fp, "changed": True}


def _mld_import(engine, a):
    path = _pick(engine, "mld")
    if not path:
        return {"cancelled": True}
    try:
        data = mld.read_file(path)
    except (OSError, ValueError) as exc:
        raise _api().CommandError("failed", "MLD 파일을 읽지 못했습니다(%s)." % str(exc)[:200])
    codes = {c["code"] for c in res.ie_category_table()["categories"]}
    name = os.path.basename(path)
    out = _mld_write(engine, a, lambda mdoc, by: mld.import_mld(mdoc, data, name, by, codes))
    return dict(out, cancelled=False, file=name, branches=len(data.get("branches") or []))


def _mld_link(engine, a):
    return _mld_write(engine, a, lambda mdoc, by: mld.set_links(mdoc, a["branch_id"], a["group_ids"]),
                      keys=["coverage:" + mld.COVER_PREFIX + a["branch_id"]])


def _fmea_resolve(engine, a):
    return _fmea_write(engine, a, lambda fdoc, pg, ns, doc, by: fmea.resolve_conflict(fdoc, a["row_id"], a["field"], a["take"]),
                       keys=["fmea:" + a["row_id"]])


def _mld_confirm(engine, a):
    return _mld_write(engine, a, lambda mdoc, by: mld.set_confirm(mdoc, a["branch_id"], a["on"], by),
                      keys=["coverage:" + mld.COVER_PREFIX + a["branch_id"]])


def confirm_mld_branch(engine, a):
    """채팅 실행 함수: {branch_id, on(참·거짓), mver}. 규칙 대조로 맞은 가지를 사람이 확인한다."""
    if not a.get("mver"):
        raise _api().CommandError("bad_args", "MLD 판 지문(mver)을 함께 보내야 합니다(먼저 view_mld로 읽음).")
    return _mld_confirm(engine, a)


def _side_replace(engine, a, which):
    api = _api()
    pid = engine.project_id()
    loader = ie_store.load_fmea if which == "fmea" else ie_store.load_mld
    try:
        loader(pid)
    except ie_store.Unreadable as exc:
        name = os.path.basename(exc.path)
    else:
        raise api.CommandError("failed", "%s 파일을 읽을 수 있어 바꾸지 않았습니다." % which.upper())
    if not a.get("confirmed"):
        msg = ("읽지 못한 %s 파일(%s)을 data/backup 아래에 복사한 뒤 빈 문서로 바꿉니다. %s 계속할까요?"
               % (which.upper(), name, "FMEA 행은 다시 가져와야 하고, 행 번호는 원본의 가장 큰 번호 다음부터 매깁니다." if which == "fmea"
                  else "MLD를 다시 가져와야 하고 사람 연결·확인은 없어집니다."))
        return {"ask": {"message": msg, "groups": []}, "changed": False}
    try:
        fp, saved = ie_store.replace_side_unreadable(pid, which)
    except (OSError, ValueError, ie_store.Conflict) as exc:
        raise api.CommandError("failed", "백업하지 못해 바꾸지 않았습니다(%s)." % str(exc)[:200])
    engine.changed("ie", None)
    return {"changed": True, "backup": os.path.basename(saved), "ver": fp}


def link_mld_branch(engine, a):
    """채팅 실행 함수: {branch_id, group_ids, mver}."""
    if not a.get("mver"):
        raise _api().CommandError("bad_args", "MLD 판 지문(mver)을 함께 보내야 합니다(먼저 view_mld로 읽음).")
    return _mld_link(engine, a)

def register(commands):
    api = _api()
    C, v_str, v_list = api.Command, api.v_str, api.v_list
    ver = (v_str(1, 100), True)
    rver = (v_str(1, 100), False)
    seen = (v_seen, False)

    def put(name, spec_, handler, doc):
        key = "ie." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    put("suggest", {"ver": ver, "rver": rver, "seen": seen}, _suggest, "규칙 초안 만들기(확정하지 않음, 두 번 돌려도 더하는 것이 없다)")
    put("confirm", {"group_id": (v_str(1, 20), True), "ver": ver, "rver": rver, "seen": seen}, _confirm, "그룹 확정(검토자 이름이 확정자로 남는다)")
    put("reopen", {"group_id": (v_str(1, 20), True), "ver": ver, "rver": rver, "seen": seen}, _reopen, "그룹 확정 풀기")
    gid = (v_str(1, 20), True)
    iecs = (v_list(v_str(1, 20), 2000), True)
    common = {"ver": ver, "rver": rver, "seen": seen, "confirmed": (api.v_bool(), False),
              "confirm_groups": (v_list(v_str(1, 20), 500), False)}
    put("create_group", dict(common, name=(v_str(1, 200), True), iecs=(v_list(v_str(1, 20), 2000), False)), _create_group,
        "고른 후보로 새 그룹 만들기(사람이 만든 초안 그룹). 쌍둥이 후보도 함께 넣는다")
    put("move", dict(common, iecs=iecs, to=(v_str(0, 20), True)), _move, "후보를 다른 그룹으로 옮기기(to가 빈 글자면 그룹에서 빼기)")
    put("accept_members", dict(common, iecs=iecs), _accept_members, "규칙이 배정한 소속을 사람이 확인")
    put("edit_group", dict(common, group_id=gid, fields=(v_fields("group"), True)), _edit_group, "그룹 이름·정의·범주·대표 등 고치기")
    put("split", dict(common, group_id=gid, moved=iecs), _split, "그룹 나누기(고른 소속 후보를 새 그룹으로)")
    put("delete_group", dict(common, group_id=gid), _delete_group, "초안 그룹 지우기(확인 필요)")
    kind = (api.v_enum("heading", "end_state", "basic_event"), True)
    put("add_record", dict(common, kind=(api.v_enum("heading", "end_state"), True), group_id=gid, fields=(v_fields("record"), True)),
        _add_record, "그룹에 표제·최종상태 더하기")
    put("edit_record", dict(common, kind=kind, id=(v_str(1, 20), True), fields=(v_fields("record"), True)), _edit_record,
        "표제·최종상태·기본사건 고치기")
    put("accept_record", dict(common, kind=kind, id=(v_str(1, 20), True)), _accept_record, "AI 초안 표제·최종상태·기본사건 받아들이기")
    put("remove_record", dict(common, kind=kind, id=(v_str(1, 20), True)), _remove_record, "표제·최종상태·기본사건 지우기(확인 필요)")
    put("set_coverage", dict(common, code=(v_str(1, 40), True), disposition=(api.v_enum("", *model.COVERAGE), True),
                             reason=(v_str(0, 1000), False)), _set_coverage, "완전성 대조 빈 범주 판정(사유 필수, 빈 처리는 지움)")
    put("export", {"ver": (v_str(1, 100), False), "rver": rver}, _export, "인계 묶음 Excel+JSON 내보내기(위치는 창이 묻는다)")
    fver = (v_str(1, 100), True)
    fseen = {"fver": fver, "seen": seen}
    put("fmea_template", {}, _fmea_template, "FMEA 양식(.xlsx) 내보내기(지금 있는 행을 채움, 위치는 창이 묻는다)")
    put("fmea_import", {"fver": fver}, _fmea_import, "채운 FMEA 양식 가져오기(파일은 창이 묻는다). 같은 행은 같은 ID")
    put("fmea_edit", dict(fseen, row_id=(v_str(1, 20), True), fields=(v_fmea_fields, True)), _fmea_edit,
        "FMEA 행 고치기(구성요소 고르기 포함). 내용이 바뀌면 승인이 풀린다")
    put("fmea_status", dict(fseen, row_ids=(v_list(v_str(1, 20), 2000), True), status=(api.v_enum(*fmea.STATUSES), True)),
        _fmea_status, "FMEA 행 승인·제외·가져옴으로 되돌리기(검토자 이름이 남는다)")
    put("fmea_mark", dict(fseen, node_id=(v_str(1, 40), True), mark=(api.v_enum("", *fmea.MARKS), True)), _fmea_mark,
        "전기·제어 구간 사람 표시(include·exclude, 빈 글자면 지움)")
    put("mld_import", {"mver": (v_str(1, 100), True)}, _mld_import, "주논리도(MLD) 파일 가져오기(파일은 창이 묻는다)")
    put("mld_link", {"mver": (v_str(1, 100), True), "seen": seen, "branch_id": (v_str(1, 40), True),
                     "group_ids": (v_list(v_str(1, 20), 50), True)}, _mld_link, "MLD 잎 가지에 초기사건 그룹 잇기(빈 목록이면 지움)")
    put("fmea_resolve", dict(fseen, row_id=(v_str(1, 20), True), field=(api.v_enum(*fmea.TEXT_FIELDS), True),
                             take=(api.v_enum("file", "mine"), True)), _fmea_resolve,
        "다시 가져오기 충돌 고르기(file: 파일 값, mine: 사람이 고친 값). 파일 값을 쓰면 앞값을 이력에 남긴다")
    put("mld_confirm", {"mver": (v_str(1, 100), True), "seen": seen, "branch_id": (v_str(1, 40), True), "on": (api.v_bool(), True)},
        _mld_confirm, "규칙 대조(범주 단위)로 맞은 MLD 가지를 사람이 확인하거나 확인 풀기")
    put("fmea_replace_unreadable", {"confirmed": (api.v_bool(), False), "confirm_groups": (v_list(v_str(1, 20), 1), False)},
        lambda engine, a: _side_replace(engine, a, "fmea"), "읽지 못한 FMEA 파일을 백업하고 새로 시작(확인 필요)")
    put("mld_replace_unreadable", {"confirmed": (api.v_bool(), False), "confirm_groups": (v_list(v_str(1, 20), 1), False)},
        lambda engine, a: _side_replace(engine, a, "mld"), "읽지 못한 MLD 파일을 백업하고 새로 시작(확인 필요)")
    put("replace_unreadable", {"confirmed": (api.v_bool(), False)}, _replace_unreadable,
        "읽지 못한 초기사건 파일을 백업하고 새로 시작(확인 필요)")


def v_fmea_fields(v):
    if not isinstance(v, dict) or not v or len(v) > 20:
        raise ValueError("고칠 필드 객체여야 함")
    for k, x in v.items():
        if k not in fmea.EDITABLE:
            raise ValueError("고칠 수 없는 필드: %s" % str(k)[:40])
        if x is not None and (not isinstance(x, str) or len(x) > fmea.MAX_TEXT):
            raise ValueError("%s 값 형식 오류" % k)
    return dict(v)


def v_seen(v):
    """화면이 본 항목 지문 {"group:IEG-01": "sha256:…"}."""
    if not isinstance(v, dict) or len(v) > 5000:
        raise ValueError("항목 지문 객체(최대 5000개)여야 함")
    for k, x in v.items():
        if not isinstance(k, str) or len(k) > 80 or not (x is None or (isinstance(x, str) and len(x) <= 100)):
            raise ValueError("항목 지문 형식 오류")
    return dict(v)


def v_fields(kind):
    """고칠 필드 {이름: 글자|글자 목록|None}. 값의 뜻은 model._check_fields가 본다(종류에 없는 필드는 거기서 거절)."""
    names = set(model.EDITABLE["group"]) if kind == "group" else {
        k for x in ("heading", "end_state", "basic_event") for k in model.EDITABLE[x]}

    def check(v):
        if not isinstance(v, dict) or not v or len(v) > 20:
            raise ValueError("고칠 필드 객체여야 함")
        for k, x in v.items():
            if k not in names:
                raise ValueError("고칠 수 없는 필드: %s" % str(k)[:40])
            ok = x is None or (isinstance(x, str) and len(x) <= 2000) or (
                isinstance(x, list) and len(x) <= 50 and all(isinstance(y, str) and len(y) <= 200 for y in x))
            if not ok:
                raise ValueError("%s 값 형식 오류" % k)
        return dict(v)
    return check
