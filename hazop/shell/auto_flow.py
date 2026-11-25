"""자동 확정의 흐름: 올린 도면을 추출에 이어 AI 검토로 메우고 확정(미확인 n)까지 잇는다. Qt를 import하지 않는다.

설계는 docs/units/2026-11-13-drawing-knowledge/evidence/auto-confirm-design.md(3·8·9·15장). 결과를 정하고 수락하는 규칙은 엔진(hazop.extract.ai_review의
auto_finish, confirmation.record_auto) 한 곳에 있고, 이 모듈은 언제·무엇을 보낼지만 정한다.

- 보내도 되는가는 `gate` 한 곳이다: ai_off(보내지 않는 프로젝트) · no_consent(동의 기록 없음) · images_off(그림 보내기를 끔) · no_connection(구독 연결 없음). 막히면 호출 없이
  쪽마다 그 까닭으로 waiting을 적는다. 호출 하나하나 앞에서도 다시 본다(동의를 거두면 다음 호출부터 나가지 않는다).
- 동의는 사용자 설정(CONSENT_KEY)에 있고 `set_consent`(명령 aireview.consent)만 쓴다. 기본은 동의 없음. 옛 토글(extract_ai_review)은 동의가 아니다.
- 호출 상한: 같은 자료 누적 ai_review.AUTO_CAP(사용자가 낮춘 extract_ai_cap이 있으면 그 값), 올리기 묶음 전체 ai_review.RUN_CAP(Budget). 부르기 전에 호출 수를 파일에 남겨(_Counted)
  앱이 죽어도 그 호출을 다시 세지 않고 쓰지 않는다.
- 이어 하기(start_resume): 앱 열기, AI 연결이 준비됨, 다음 올리기의 끝, 동의·보내기 허용. 자동 기록이 없는 옛 쪽은 건드리지 않는다.
"""

import contextlib
import logging
import os
import threading

from hazop import paths, store_io
from hazop.app import data
from hazop.extract import ai_review, confirmation, corrections
from hazop.graph import sheets
from hazop.shell import ai_image_flow, sheet_refresh
from hazop.study.nodes import now_utc

LOG = logging.getLogger("hazop.shell.auto_flow")
CONSENT_KEY = "auto_send_consent"
CONSENT_NOTICE = "auto-send-1"      # 사용자에게 보인 동의 문장의 판. 보내는 범위가 바뀌면 올린다(옛 동의는 동의가 아니게 된다)
SHARED_STOPS = ("limit", "no_connection", "stopped", "no_consent", "ai_off", "images_off")      # 한 쪽에서 걸리면 남은 쪽도 같은 까닭인 것
JOB_LABEL = "AI 검토 이어 하기"
TRIES = 3


# ---------------------------------------------------------------- 동의와 보내기 정책

def consent(engine):
    """{"allow", "asked", "at"}. 온전한 기록이 아니면 묻지 않은 것으로 본다(보내지 않는 쪽)."""
    rec = engine.settings.get(CONSENT_KEY)
    ok = isinstance(rec, dict) and isinstance(rec.get("allow"), bool) and rec.get("notice") == CONSENT_NOTICE \
        and isinstance(rec.get("at"), str) and bool(rec["at"])
    return {"allow": ok and rec["allow"], "asked": ok, "at": rec["at"] if ok else None}


def set_consent(engine, allow):
    """사람의 답을 사용자 설정에 적는다(명령 aireview.consent만 부른다). 동의 문장이 조각 그림을 말하므로 동의하면 그림 보내기도 켠다(뒤에 끄면 끈 것이
    이김). 저장하지 못하면 예외를 올린다. 그때 동의는 앞 값으로 되돌리고, 거절·철회는 이 실행 동안 그대로 지킨다."""
    keys = (CONSENT_KEY, ai_image_flow.KEY)
    before = {k: engine.settings[k] for k in keys if k in engine.settings}
    engine.settings[CONSENT_KEY] = {"allow": bool(allow), "notice": CONSENT_NOTICE, "at": now_utc(), "by": engine.reviewer()}
    if allow:
        engine.settings[ai_image_flow.KEY] = True
    try:
        engine.save_settings()
    except Exception:
        if allow:
            for k in keys:
                engine.settings.pop(k, None)
            engine.settings.update(before)
        raise
    engine.changed("aireview", None)
    return consent(engine)


def set_send_policy(engine, send, reason=None):
    """지금 프로젝트의 'AI로 보내지 않음'을 적는다(읽기는 ai_review.send_policy). 정한 사람 이름이 있어야 한다."""
    by = engine.reviewer()
    if not by:
        raise ValueError("검토자 이름을 먼저 설정에서 입력하세요. 정한 사람으로 남습니다.")
    corrections.check_person(by)
    pid = engine.project_id()
    path = ai_review.send_policy_path(pid)
    store_io.write_json(path, {"kind": ai_review.SEND_POLICY_KIND, "schema_version": "0.1", "project_id": pid, "send": send,
                               "by": by, "at": now_utc(), "reason": reason})
    engine.changed("aireview", None)
    return ai_review.send_policy(pid)


def _may_send(engine, project_id):
    """연결을 빼고, 보내도 되는가(호출마다 본다) → 막는 까닭 또는 None."""
    known = {p for p in (project_id, engine.project_id()) if p}
    if not known or any(ai_review.send_policy(p) == "deny" for p in known):      # 어느 프로젝트인지 모르면 정책도 모르므로 보내지 않는다
        return "ai_off"
    if not consent(engine)["allow"]:
        return "no_consent"
    return None if ai_image_flow.enabled(engine) else "images_off"


def cap_of(engine):
    """같은 자료 누적 상한: 사용자가 낮춘 값이 있으면 그 값, AUTO_CAP을 넘지 않음."""
    try:
        return max(1, min(ai_review.AUTO_CAP, int(engine.settings.get("extract_ai_cap") or ai_review.AUTO_CAP)))
    except (TypeError, ValueError):
        return ai_review.AUTO_CAP


def gate(engine, project_id):
    """자동으로 보내지 않을 까닭 또는 None."""
    why = _may_send(engine, project_id)
    if why:
        return why
    from hazop.shell import api_settings
    return None if api_settings.run_conn(engine, "ai_review")["can_start"] else "no_connection"


# ---------------------------------------------------------------- 호출 예산과 세기

class Budget:
    """올리기 묶음 하나의 호출 예산(RUN_CAP). 자동 작업이 하나도 없을 때 새로 만들고, 도는 동안 들어온 작업은 나눠 쓴다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._users = 0
        self._reset()

    def _reset(self):
        self.left, self._files = ai_review.RUN_CAP, 0
        self.touched = set()        # 이 묶음에서 다룬 도면(같은 묶음의 이어 하기가 다시 잡지 않는다)
        self.kinds = []             # 오류 종류 목록(파일마다 작업이 달라도 같은 오류가 이어지면 멈춘다)
        self.stop = None            # 묶음 전체를 멈춘 까닭(사용 한도 등). 남은 쪽은 부르지 않고 이 까닭으로 남는다

    def enter(self, file=False):
        """file: 올린 파일 하나의 몫(file_done과 짝)."""
        with self._lock:
            if self._users == 0:
                self._reset()
            self._users += 1
            self._files += file

    def leave(self):
        with self._lock:
            self._users -= 1

    def file_done(self):
        """이 파일의 일이 끝났다 → 올린 파일 가운데 마지막이었는가(leave 앞에서 부른다)."""
        with self._lock:
            self._files -= 1
            return self._files == 0

    def spend(self):
        with self._lock:
            self.left -= 1


def _call_path(ex):
    src, run = ex.get("source") or {}, ex.get("run") or {}
    page = (run.get("settings") or {}).get("page_index") or 0
    return paths.folder("ai-review", "auto", paths.safe_name("calls-%s-%s-p%s" % (
        str(src.get("sha256") or "none")[:64], ex.get("project_id") or "none", page)) + ".json")      # 같은 PDF라도 프로젝트마다 따로 센다


class _Counted:
    """부르기 전에 호출 하나를 파일과 예산에 적는 클라이언트. 앱이 호출 중에 죽어도 쓴 호출을 안다(_recover)."""

    def __init__(self, client, budget, path, note):
        self._client, self._budget, self._path, self._note = client, budget, path, dict(note, calls=0)

    def analyze(self, request):
        self._note["calls"] += 1
        store_io.write_json(self._path, self._note)
        self._budget.spend()
        return self._client.analyze(request)

    def __getattr__(self, name):
        return getattr(self._client, name)


def _recover(name, ex):
    """앞 실행이 호출 중에 죽어 실행 기록에 남지 못한 호출을 실행 기록으로 옮긴다(누적 상한이 그 호출을 세게). 두 번 불러도 한 번만 센다."""
    path = _call_path(ex)
    try:
        left = data.read_json(path)
    except (OSError, ValueError):
        return
    doc = ai_review.load_doc(name)
    known = any(r.get("auto_id") == left.get("auto_id") for r in (doc or {}).get("runs") or [])
    if not known and left.get("calls"):
        stats = {"items": left.get("items"), "calls": left["calls"], "left": left.get("items") or 1, "errors": 0, "error_kinds": [],
                 "halted": False, "stopped": True, "refused": None, "legend_source": ai_review.AUTO_LEGEND, "auto_id": left.get("auto_id")}
        ai_review.merge_and_save(name, ex, {"candidates": [], "stats": stats}, auto=True)
    _remove(path)


def _remove(path):
    with contextlib.suppress(OSError):
        os.remove(path)


# ---------------------------------------------------------------- 추출하는 동안의 표지(쪽 기록을 적기 전에 죽어도 이어 하게)

def _intent_path(project_id, material_id):
    return paths.folder("ai-review", "auto", paths.safe_name("intent-%s-%s" % (project_id, material_id)) + ".json")


def sheets_of(material_id):
    root = paths.output_root("extract")
    out = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        key = sheets.from_out_name(name)
        if key and key[0] == material_id and os.path.isfile(data.extraction_path(name)):
            out.append(name)
    return out


class Intake:
    """등록한 자료 하나의 추출 → 자동 확정 시작. 처음 추출한 쪽에만 'waiting(started)'를 적는다. 처음인지는 이름이 아니라 (자료, 쪽)으로 본다(등록판이
    올라가면 이름이 바뀐다). 앞서 추출한 쪽은 자동 기록이 있는 것만 이어 하며, 등록판이 올라갔으면 앞 판의 기록을 먼저 옮긴다."""

    def __init__(self, project_id, material_id, registration_file, number_why=None):
        self.number_why, self.created = number_why, _carry_previous(registration_file)
        self.path = _intent_path(project_id, material_id)
        # 앞 추출이 표지를 남긴 채 죽었으면 그때의 '추출 전 쪽'을 이어 쓴다(그때 새로 추출한 쪽이 옛 쪽으로 보이지 않게)
        self.had = _had(self.path)
        if self.had is None:
            self.had = sheets_of(material_id)
            try:
                store_io.write_json(self.path, {"project_id": project_id, "material_id": material_id, "had": self.had, "number_why": number_why})
            except OSError:         # 표지가 없으면 추출 한가운데서 죽었을 때만 이어 하지 못한다. 추출을 막지 않는다
                LOG.exception("추출 표지를 적지 못함")

    def start(self, names):
        for name in names:
            if not _has_record(name) and _is_new(name, self.had):
                mark_waiting(name, "taken" if self.number_why == "taken" else "started")
        _remove(self.path)

    def undo(self):
        """추출하지 못함: 이번에 옮겨 만든 사본을 지운다(앞 판의 기록 하나만 진실로 남게)."""
        for path in self.created:
            _remove(path)


def _is_new(name, had):
    """추출 전에 이 자료의 이 쪽이 어느 등록판으로도 없었는가."""
    key = sheets.from_out_name(name)
    return name not in had and not (key and any((sheets.from_out_name(h) or (None, None, None))[2] == key[2] for h in had))


def _carry_previous(registration_file):
    from hazop.register import titleblock
    try:
        record = data.read_json(registration_file)
        return titleblock.carry_previous(record) if isinstance(record, dict) and record.get("registration_version", 1) > 1 else []
    except (OSError, ValueError, KeyError, TypeError):
        LOG.warning("앞 등록판의 기록을 옮기지 못함", exc_info=True)
        return []


def _had(path):
    try:
        return list(data.read_json(path).get("had") or [])
    except (OSError, ValueError, AttributeError):
        return None


def _adopt_intents(project_id, busy):
    """추출은 끝났지만 쪽 기록을 적기 전에 죽은 자료의 쪽에 'waiting(started)'를 적는다. 지금 추출 중인 자료(busy)는 건드리지 않는다."""
    folder = paths.folder("ai-review", "auto")
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not f.startswith("intent-"):
            continue
        path = os.path.join(folder, f)
        try:
            doc = data.read_json(path)
        except (OSError, ValueError):
            continue
        mid = doc.get("material_id")
        if doc.get("project_id") != project_id or mid in busy:
            continue
        for name in sheets_of(mid):
            if _is_new(name, doc.get("had") or []) and not _has_record(name):
                mark_waiting(name, "taken" if doc.get("number_why") == "taken" else "started")
        _remove(path)


@contextlib.contextmanager
def extracting(engine, project_id, material_id, registration_file, number_why=None):
    """추출 한 번을 감싼다 → Intake. 추출이 오류로 끝나거나 앱이 죽으면 표지가 남아 다음 추출이나 이어 하기가 거둔다."""
    with engine._lock:
        engine._auto_extracting.add(material_id)
    try:
        intake = Intake(project_id, material_id, registration_file, number_why)
        try:
            yield intake
        except Exception:
            intake.undo()
            raise
    finally:
        with engine._lock:
            engine._auto_extracting.discard(material_id)


# ---------------------------------------------------------------- 쪽 기록

def _has_record(name):
    return confirmation.auto_record(name) is not None


def _retry(fn):
    for n in range(TRIES):
        try:
            return fn()
        except store_io.Conflict:
            if n == TRIES - 1:
                raise


def mark_waiting(name, why):
    """waiting(why)를 적는다. 되돌린 쪽·읽을 수 없는 기록은 그대로 둔다."""
    def write():
        with sheet_refresh.lock(name):
            st = confirmation.sheet_confirmation(name)
            a = st["auto"] or {}
            if st["state"] == "confirmed" or a.get("result") == "reverted":
                return
            confirmation.record_auto(name, "waiting", why, ai=a.get("ai"), accepted=st["auto_accepted"], unconfirmed=st["unconfirmed_targets"],
                                     attempts=a.get("attempts") or 0)
    try:
        _retry(write)
    except (OSError, ValueError):
        LOG.exception("자동 확정 기록을 적지 못함: %s", name)


def _finish(engine, name):
    """엔진의 마무리(결과 정하기 → 수락 → 기록). 수락한 것이 있으면 그래프 다시 짓기를 짓기 차례에 맡긴다."""
    def go():
        with sheet_refresh.lock(name):
            return ai_review.auto_finish(name, _read(name), cap_of(engine))
    out = _retry(go)
    if out["accepted"]:
        from hazop.shell import api_inputs
        api_inputs.note(engine, name)
    return out


def _read(name):
    return data.read_json(data.extraction_path(name))


ASK, FINISH = "ask", "finish"


def _next(engine, name, ex):
    """이 쪽에 할 일: FINISH(부르지 않고 마무리) · ASK(물음) · no_image(그림을 실을 수 없음) · None(할 것 없음)."""
    st = confirmation.sheet_confirmation(name)
    if not confirmation.auto_resumable(st):
        return None
    if confirmation.source_format(ex) != "pdf_vector":
        return FINISH
    _recover(name, ex)
    doc = ai_review.load_doc(name)
    if ai_review.auto_asked(doc, st["read_key"]):
        return FINISH
    if not ai_review.auto_calls_left(doc, name, cap_of(engine)):
        return FINISH
    return ASK if ai_image_flow.pdf_source(ex) else "no_image"


# ---------------------------------------------------------------- 실행

def run(engine, names, progress):
    """도면들의 자동 확정을 이어서 한다. 어디서 끊겨도 다시 부르면 같은 끝이다. 사람이 시킨 AI 검토가 잡은 도면은 건너뛴다.
    → {"calls", "done": [이름], "skipped": 까닭 또는 None}."""
    from hazop.shell import api, api_aireview as AR
    held = engine.reserve_review(names, partial=True)
    out = {"calls": 0, "done": [], "skipped": None if held else "busy"}
    ask = []
    token = AR._mark_waiting(engine, held) if held else None
    try:
        for name in held:
            engine.auto_budget.touched.add(name)
            step = _guarded(engine, name, lambda: _next(engine, name, _read(name)))
            if step == ASK:
                ask.append(name)
            elif step == FINISH:
                _guarded(engine, name, lambda: _finish(engine, name))
                out["done"].append(name)
            elif step:
                mark_waiting(name, step)
        if ask:
            why = gate(engine, (_read(ask[0]) or {}).get("project_id"))
            if why is None:
                client, refused = ai_image_flow.subscription_client(engine)
                why = "no_connection" if refused else None
            if why:
                out["skipped"] = why
                for name in ask:
                    mark_waiting(name, why)
            else:
                try:
                    with engine.ai_turn("자동 AI 검토", progress, should_stop=lambda: AR._stopper(engine, token)() or engine.stop_requested()):
                        _ask_all(engine, ask, client, progress, token, out)
                except api.JobStopped:
                    out["skipped"] = "stopped"
                    for name in ask:
                        mark_waiting(name, "stopped")
    finally:
        if token is not None:
            AR._mark_ended(engine, token, held)
        engine.release_review(held)
        for topic in ("aireview", "sheetconf", "drawings"):
            engine.changed(topic, None)
    return out


def run_budgeted(engine, names, progress):
    """올리기 묶음 밖(채팅의 추출)에서 부르는 run: 예산을 잡고 돌리며, 실패해도 부른 일을 막지 않는다."""
    engine.auto_budget.enter()
    try:
        return run(engine, names, progress)
    except Exception:  # noqa: BLE001
        LOG.exception("자동 확정 오류")
        return None
    finally:
        engine.auto_budget.leave()


def _guarded(engine, name, fn):
    """도면 하나의 일: 실패해도 남은 도면은 이어 한다."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        LOG.exception("자동 확정 실패: %s", name)
        return None


def _ask_all(engine, names, client, progress, token, out):
    from hazop.shell import api, api_aireview as AR
    stop_engine = AR._stopper(engine, token)
    skip = AR._skipper(engine, token)
    budget = engine.auto_budget
    shared, rest = None, ()
    for n, name in enumerate(names):
        rest = names[n:]
        shared = "stopped" if engine.stop_requested() else budget.stop
        if shared:
            break
        ex = _guarded(engine, name, lambda: _read(name))
        step = _guarded(engine, name, lambda: _next(engine, name, ex)) if ex else None      # 차례를 기다리는 동안 바뀐 것을 다시 본다
        if step != ASK:
            if step == FINISH:
                _guarded(engine, name, lambda: _finish(engine, name))
                out["done"].append(name)
            elif step:
                mark_waiting(name, step)
            continue
        if skip(name):
            mark_waiting(name, "stopped")
            continue
        why = _may_send(engine, ex.get("project_id"))
        if why:
            mark_waiting(name, why)
            continue
        if budget.left <= 0:
            mark_waiting(name, "run_cap")
            continue
        AR._page_started(engine, token, name)
        got = _guarded(engine, name, lambda: _ask_one(engine, name, ex, client, budget.kinds, progress, token, stop_engine, out))
        if got is None:
            mark_waiting(name, "error")
            continue
        why, rest = got.get("why"), names[n + 1:]
        if why in SHARED_STOPS or got.get("halted"):
            # 이 쪽이 확정(상한)되거나 실패로 남아도 멈춘 까닭은 실행 기록에 있다. 모르면 남은 쪽은 묻지 않은 것일 뿐이라 stopped
            shared = why if why in SHARED_STOPS else got.get("stop") or "stopped"
            if shared == "stopped" and not got.get("halted") and not engine.stop_requested():      # 사람이 이 도면만 멈췄다
                shared = None
                continue
            if shared != "stopped" or got.get("halted"):
                budget.stop = shared
            break
        try:
            progress("AI 검토 %d/%d쪽" % (n + 1, len(names)), n + 1, len(names))
        except api.JobStopped:
            shared = "stopped"
            break
    for name in rest if shared else ():
        mark_waiting(name, shared)


def _ask_one(engine, name, ex, client, kinds, progress, token, stop_engine, out):
    """도면 하나를 묻고 마무리한다 → auto_finish의 답 + {"halted"}. 그림을 실을 수 없으면 부르지 않고 no_image."""
    from hazop.shell import api_aireview as AR
    doc = ai_review.load_doc(name)
    cap = ai_review.auto_calls_left(doc, name, cap_of(engine))
    items = ai_review.estimate_pages([(name, ex)], cap=cap, images=ai_image_flow.estimate_input())["pages"][0]["items"]
    path = _call_path(ex)
    note = {"auto_id": "%s/%s" % (now_utc(), os.urandom(4).hex()), "name": name, "items": items}
    counted = _Counted(client, engine.auto_budget, path, note)
    done, images = ai_image_flow.run_pages(
        engine, [(name, ex)], counted, cap, engine.auto_budget.left, lambda nm, d, t, left: AR._progress(engine, token, progress, nm, d, t),
        lambda: stop_engine() or bool(_may_send(engine, ex.get("project_id"))), auto=True, kinds=kinds, note={"auto_id": note["auto_id"]})
    _remove(path)
    if not done:
        why = "no_image" if images.failed or not ai_image_flow.pdf_source(ex) else _may_send(engine, ex.get("project_id")) or "stopped"
        mark_waiting(name, why)
        return {"why": why}
    stats = done[0][2]
    out["calls"] += stats["calls"]
    got = _finish(engine, name)
    why = _may_send(engine, ex.get("project_id"))
    if got["result"] == "waiting" and got["why"] == "stopped" and why:      # 동의를 거두거나 보내지 않음으로 바꿔 멈춘 것
        mark_waiting(name, why)
        got = dict(got, why=why)
    if got["result"] != "waiting":
        out["done"].append(name)
    return dict(got, halted=bool(stats["halted"]), stop=ai_review._stop_why(stats))


# ---------------------------------------------------------------- 이어 하기

def resumable(engine):
    """이어 할 도면 이름(등록 차례). 자동 기록이 없는 옛 쪽, 되돌린 쪽, 사람이 확정한 쪽은 없다. 읽기만 한다.
    확정된 쪽은 그 뒤 다시 추출한 것만 연다(열 때마다 모든 쪽을 다시 세지 않게)."""
    closed = {}
    names = []
    for name in engine.graph_names().values():
        rec = confirmation.auto_record(name)
        if not rec or rec["result"] == "reverted":
            continue
        if rec["result"] == "confirmed" and not _newer(name, rec["at"]):
            continue
        if rec["result"] == "waiting" and rec.get("why") != "started":
            try:
                pid = _read(name).get("project_id")
            except (OSError, ValueError):
                continue
            if pid not in closed:
                closed[pid] = gate(engine, pid)
            if closed[pid] and closed[pid] == rec.get("why"):
                continue                # 막힌 까닭이 그대로다: 다시 열어 보지 않는다
        try:
            if confirmation.auto_resumable(confirmation.sheet_confirmation(name)):
                names.append(name)
        except (OSError, ValueError):
            LOG.warning("자동 확정 기록을 읽지 못함: %s", name, exc_info=True)
    order = _registered_order()
    return sorted(names, key=lambda n: (order.get((sheets.from_out_name(n) or (None,))[0], ""), (sheets.from_out_name(n) or (0, 0, 0))[2], n))


def _newer(name, at):
    import datetime
    try:
        return os.path.getmtime(data.extraction_path(name)) > datetime.datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()
    except (OSError, ValueError):
        return True


def _registered_order():
    out = {}
    for e in data.list_registrations():
        rec = e["record"]
        hist = rec.get("history") or [{}]
        out[rec.get("material_id")] = str((hist[0] or {}).get("at") or "")
    return out


def start_resume(engine, exclude=()):
    """이어 할 도면이 있으면 작업 하나를 띄운다(한 번에 하나) → 작업 ID 또는 None. exclude: 이 묶음에서 이미 다룬 도면."""
    with engine._lock:
        if engine._auto_resuming or engine.stop_requested():
            return None
        engine._auto_resuming = True
        busy = set(engine._auto_extracting)
    started = False
    try:
        _adopt_intents(engine.project_id(), busy)
        names = [n for n in resumable(engine) if n not in exclude]
        if not names:
            return None
        engine.auto_budget.enter()

        def work(progress):
            try:
                return run(engine, names, progress)
            finally:
                engine.auto_budget.leave()
                _resume_ended(engine)
        started = True
        try:
            return engine.start_job(JOB_LABEL, work, kind="ai_review")
        except Exception:
            engine.auto_budget.leave()
            started = False
            raise
    finally:
        if not started:
            _resume_ended(engine)


def _resume_ended(engine):
    with engine._lock:
        engine._auto_resuming = False


def resume_quietly(engine, exclude=()):
    """이어 하기를 시작해 본다. 실패해도 부른 일을 막지 않는다."""
    try:
        return start_resume(engine, exclude)
    except Exception:  # noqa: BLE001
        LOG.exception("이어 하기를 시작하지 못함")
        return None


# ---------------------------------------------------------------- 사람이 시키는 것(채팅)

def restart_names(engine, graph_ids):
    """사람이 'AI로 확정해 줘'라고 시킨 도면 가운데 할 것이 있는 이름. 사람이 확정한 쪽과 이미 이 읽기로 자동 확정된 쪽은 뺀다."""
    names = engine.graph_names()
    out = []
    for gid in graph_ids:
        if gid in names:
            st = confirmation.sheet_confirmation(names[gid])
            if st["level"] == "extracted":
                out.append(names[gid])
    return out


def restart(engine, graph_ids, by):
    """되돌린 쪽·멈춘 쪽·옛 쪽도 다시 시작한다(누적 상한은 그대로) → (작업 ID, 도면 수). 이미 AI 검토가 도는 도면은 뺀다."""
    names = [n for n in restart_names(engine, graph_ids) if n not in engine._reviewing]
    _carry_for_restart(engine, names)
    for name in names:
        def write(name=name):
            with sheet_refresh.lock(name):
                confirmation.record_auto(name, "waiting", "started", by=by, restart=True)
        _retry(write)
    if not names:
        return None, 0
    engine.auto_budget.enter()

    def work(progress):
        try:
            return run(engine, names, progress)
        finally:
            engine.auto_budget.leave()
    try:
        return engine.start_job("AI로 확정", work, kind="ai_review"), len(names)
    except Exception:
        engine.auto_budget.leave()
        raise


def _carry_for_restart(engine, names):
    """이전 화면이 새 등록판으로 추출해 둔 쪽: 앞 판의 되돌림·후보·호출 수를 먼저 옮긴다(사람이 물린 자리를 다시 받지 않게)."""
    from hazop.register import registry
    from hazop.shell import api_inputs
    for mid in {(sheets.from_out_name(n) or (None,))[0] for n in names} - {None}:
        try:
            _rec, path = registry.latest(engine.project_id(), mid, paths.store_root())
        except (OSError, ValueError, KeyError):
            continue
        if path and _carry_previous(path):
            for n in sheets_of(mid):
                if n in names:
                    api_inputs.note(engine, n)


def revert_preview(name):
    """이 도면의 자동 수락 되돌리기 전에 알릴 값 {"count": 자동으로 받은 값 수, "confirm": [함께 빠질 사람 고침 op_id], "record": 자동 기록이 있는가}."""
    ops = (corrections.load(name) or {}).get("ops") or []
    own = [o["op_id"] for o in ops if corrections.is_auto(o)]
    deps = set()
    for oid in own:
        deps.update(corrections.dependents(ops, oid))
    human = [o["op_id"] for o in ops if o["op_id"] in deps and o["op_id"] not in own and o.get("origin") != "ai"]
    rec = confirmation.auto_record(name)
    return {"count": len(own), "confirm": human, "record": bool(rec) and rec["result"] != "reverted"}


# ---------------------------------------------------------------- 읽기

def summary(engine):
    """웹 읽기 `aireview/auto`: 동의·보내기 정책·막힌 까닭과 쪽마다의 자동 기록. 파일을 쓰지 않는다.
    ask: 연결돼 있고 아직 묻지 않았으며 동의를 기다리는 쪽이 있다(화면이 한 번 묻는다). 쪽의 확정 수준(level)은 `sheetconf/<도면>`이 준다."""
    from hazop.shell import api_drawings
    pid = engine.project_id()
    lb = api_drawings.labels(engine)
    rows = []
    for gid, name in engine.graph_names().items():
        rec = confirmation.auto_record(name)
        if rec:
            rows.append({"graph_id": gid, "display": api_drawings.display(engine, gid, lb), "result": rec["result"], "why": rec.get("why"),
                         "at": rec["at"], "ai": rec.get("ai"), "accepted": rec.get("accepted"), "unconfirmed": rec.get("unconfirmed")})
    rows.sort(key=lambda r: (r["display"], r["graph_id"]))
    agreed = consent(engine)
    from hazop.shell import api_settings
    ready = bool(api_settings.run_conn(engine, "ai_review")["can_start"])
    waiting = any(r["why"] == "no_consent" for r in rows)
    return {"project_id": pid, "consent": agreed, "connected": ready, "ask": ready and not agreed["asked"] and waiting,
            "send": ai_review.send_policy(pid), "gate": gate(engine, pid), "accept_on": ai_review.AUTO_ACCEPT_ENABLED, "sheets": rows}
