"""새 웹 화면의 표제란 패널(완료 목록 2 A3, INTENT §3.1, 화면 규격 HZ-DSN-05 '표제란 후보 확정'). Qt를 import하지 않는다.

- **읽기 `titleblock`**: 이 프로젝트 도면 자료마다 도면 번호·개정·제목의 확정값·후보·근거(읽은 자리)·누가 언제 확정했는가, 상태,
  판 표시(`ver`), 추출한 쪽(그래프 ID), 번호를 바꾸면 끊길 검토 자료. `titleblock/<자료 ID>`는 자료 하나. 읽기는 파일을 쓰지 않는다.
- **명령** `titleblock.confirm`(`material_id`, `fields` {항목: 값}, `reason`?, `ver`), `titleblock.unconfirm`(`material_id`,
  `fields` [항목]?, `reason`?, `ver`). 확정한 사람(`by`)은 설정의 검토자 이름이고 시각은 엔진이 채운다. 검사(사람 이름·판·값·번호
  변경으로 끊기는 구간·결과·같은 번호)는 명령에서 바로 하고 막히면 사유를 돌려준다. 통과하면 새 등록 버전과 다시 추출을 작업으로
  돌리고 `{"job": 작업 ID}`를 돌려준다(이미 추출한 쪽이 없으면 작업 없이 바로 끝내고 결과를 돌려준다).
- 엔진은 `hazop.register.titleblock`이다. 채팅도 같은 함수(`titleblock.execute`)를 부른다.
"""

from hazop.register import titleblock as tb

TOPICS = ("titleblock",)
FIELD_IDS = tuple(f for f, _ in tb.FIELDS)
CODE_MAP = {"stale": "stale", "not_found": "not_found", "bad_args": "bad_args", "bad_actor": "bad_args"}


def _api():
    from hazop.shell import api
    return api


def summary(engine):
    pid = engine.project_id()
    rows = tb.view(pid)
    order = {"unconfirmed": 0, "partial": 1, "confirmed": 2}
    rows.sort(key=lambda r: (order.get(r["state"], 3), r.get("name") or ""))
    return {"project_id": pid, "reviewer": engine.reviewer(), "rows": rows,
            "fields": [{"id": f, "label": label} for f, label in tb.FIELDS],
            "totals": {"materials": len(rows), "confirmed": sum(1 for r in rows if r["state"] == "confirmed")}}


def read(engine, parts, query):
    """ReadApi가 부르는 길: parts[0] == 'titleblock'. 없는 자료는 None(404)."""
    api = _api()
    if len(parts) == 1:
        return api._json(summary(engine))
    if len(parts) == 2:
        r = tb.row(engine.project_id(), parts[1])
        return api._json(r) if r is not None else None
    return None


def _refuse(out):
    api = _api()
    r = (out.get("refused") or [{}])[0]
    raise api.CommandError(CODE_MAP.get(r.get("code"), "failed"), str(r.get("reason") or "처리하지 못했습니다."))


def _run(engine, a, fn):
    """fn(dry, progress) -> 엔진 답. 먼저 dry로 검사하고, 다시 추출할 쪽이 있으면 작업으로 돌린다."""
    pid = engine.project_id()
    check = fn(pid, True, None)
    if not check["ok"]:
        _refuse(check)
    if not check.get("changed"):
        return {"changed": False, "row": tb.row(pid, a["material_id"])}

    def job(progress):
        out = fn(pid, False, progress)
        if not out["ok"]:
            raise RuntimeError((out["refused"][0] or {}).get("reason") or "처리하지 못했습니다.")
        engine.changed("titleblock")
        engine.changed("sheetconf")
        engine.changed("kg")
        return {"material_id": a["material_id"], "version": out["version"], "re_extracted": out["re_extracted"],
                "carried": out["carried"], "released": out["released_sheet_confirmations"],
                "number_conflicts": [c.get("drawing_number") for c in out.get("conflicts") or []], "notes": out["notes"]}
    if not check.get("re_extract"):
        result = job(lambda *_: None)
        return dict(result, changed=True, row=tb.row(pid, a["material_id"]))
    label = "표제란 확정 · %s" % (tb.row(pid, a["material_id"]) or {}).get("name", a["material_id"])
    return {"changed": True, "job": engine.start_job(label, job)}


def _h_confirm(engine, a):
    fields = {k: v for k, v in (a.get("fields") or {}).items() if v is not None}
    return _run(engine, a, lambda pid, dry, progress: tb.confirm(
        pid, a["material_id"], fields, engine.reviewer(), a["ver"], a.get("reason"), progress=progress, dry=dry))


def _h_unconfirm(engine, a):
    return _run(engine, a, lambda pid, dry, progress: tb.unconfirm(
        pid, a["material_id"], a.get("fields"), engine.reviewer(), a["ver"], a.get("reason"),
        progress=progress, dry=dry))


def register(commands):
    api = _api()
    C, v_str, v_enum, v_list, v_obj = api.Command, api.v_str, api.v_enum, api.v_list, api.v_obj
    value = v_str(1, tb.MAX_VALUE)

    def put(name, spec_, handler, doc):
        key = "titleblock." + name
        if key in commands:
            raise ValueError("명령 이름이 겹침: %s" % key)
        commands[key] = C(spec_, handler, doc)

    base = {"material_id": (v_str(1, 80), True), "ver": (v_str(1, 100), True), "reason": (v_str(0, 300), False)}
    put("confirm", dict(base, fields=(v_obj(**{f: value for f in FIELD_IDS}), True)), _h_confirm,
        "표제란 값(도면 번호·개정·제목)을 사람이 확정한다(후보 그대로 또는 고친 값). 이미 추출한 도면은 다시 추출한다")
    put("unconfirm", dict(base, fields=(v_list(v_enum(*FIELD_IDS), len(FIELD_IDS)), False)), _h_unconfirm,
        "표제란 확정을 취소해 후보만 있는 상태로 되돌린다")
