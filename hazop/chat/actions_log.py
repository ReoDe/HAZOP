"""채팅이 낸 동작의 실행 기록. 규격: docs/specs/chat-panel.md §4.7. Qt를 import하지 않는다.

- 위치: `<작업 루트>/data/chat-actions/<project_id>/<YYYY-MM-DD>.jsonl`(KST 날짜). 한 줄에 동작 하나, 덧붙이기만 하고 고치지 않는다
  (되돌리기도 새 줄). 대화 내용은 저장하지 않는다: 질문 원문은 그 동작을 낳은 한 개만 500자까지.
- 모든 필드는 앱이 채운다. 모델에게서 온 것은 `action`·`args`·`why`뿐이고 `model_proposal` 안에만 둔다(그 밖의 키는 버린다).
  시각(`at`)·`request_id`·`answer_id`·`action_key`는 이 모듈이 만들거나 앱 코드가 넘기며, 확인자(`confirmed_by`)는 확인 상자를
  거친 동작(`class: confirm`)에만 쓸 수 있다.
- 같은 동작을 두 번 쓰지 않는다: 열쇠는 (`action_key`, `result`, `undo_of`)이다. 같은 열쇠가 오늘이나 어제 파일에 있으면
  쓰지 않고 이미 있는 줄을 돌려준다. `action_key`는 답 하나 안의 동작 번호(`<answer_id>#<번호>`)라서, 같은 동작의 '후보' → '실행' →
  '되돌림'은 `result`가 달라 각각 한 줄씩 남는다.
- 쓰기는 `hazop.store_io.write_bytes`(같은 폴더 임시 파일 + fsync + os.replace)로 파일 전체를 바꾼다. 프로세스 간 잠금(프로젝트 폴더의
  .lock)과 지문 확인(expect)을 함께 쓰고, 잠금 시간 초과·접근 거부·Conflict는 짧게 쉬며 다시 시도한다. 그래도 안 되면 예외 대신
  status=failed를 돌려줘서, 기록 실패가 동작 실행을 막거나 화면을 깨지 않는다(부른 쪽이 알린다).
"""

import contextlib
import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from hazop import paths, store_io

try:
    import msvcrt
    fcntl = None
except ImportError:  # Windows가 아닌 환경
    msvcrt = None
    import fcntl

SCHEMA = "hazop_chat_action/1"
KST = timezone(timedelta(hours=9))
RESULTS = ("ok", "failed", "candidate", "declined", "rejected", "stale", "undone", "done")  # done: 뒤에서 돈 작업(분석·추출)이 끝남
CLASSES = ("auto", "confirm")  # 표시 동작은 기록하지 않는다. 안 함 동작은 앱이 거절한 것이므로 result=rejected로 남긴다
REQUEST_TEXT_MAX = 500
WHY_MAX = 300
ERROR_MAX = 300
ARGS_MAX_CHARS = 8000
RETRIES = 5
RETRY_PAUSE = 0.05   # 다시 시도 사이에 쉬는 시간(초, 시도 번호를 곱한다)
LOCK_SECONDS = 3     # 프로세스 간 잠금을 기다리는 시간
LOCK_NAME = ".lock"
NL = b"\n"
_LOCK = threading.Lock()
_KEY_RE = re.compile(r"^[A-Za-z0-9_.:#-]{1,100}$")


def now_kst():
    return datetime.now(KST).replace(microsecond=0)


def new_id(prefix, now=None):
    """앱이 만드는 ID: q-20261113-152031-3f9a(질문), a-…(답). 모델이 정한 값을 쓰지 않는다."""
    return "%s-%s-%s" % (prefix, (now or now_kst()).strftime("%Y%m%d-%H%M%S"), secrets.token_hex(2))


def action_key(answer_id, index):
    return "%s#%d" % (answer_id, index)


def day_path(project_id, day):
    """day: 'YYYY-MM-DD' 또는 date."""
    name = day if isinstance(day, str) else day.strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", name):
        raise ValueError("날짜 형식이 아님: %r" % (day,))
    return paths.folder("chat-actions", paths.safe_name(project_id), name + ".jsonl")


def _proposal(proposal):
    """모델이 낸 것에서 action·args·why만 남긴다. args가 너무 크면 자르지 않고 지문만 남긴다."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get("action"), str):
        raise ValueError("model_proposal에는 action(글)이 필요")
    args = proposal.get("args") if proposal.get("args") is not None else {}
    dumped = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    if len(dumped) > ARGS_MAX_CHARS:
        args = {"_truncated": True, "size": len(dumped), "sha256": hashlib.sha256(dumped.encode("utf-8")).hexdigest()}
    return {"action": proposal["action"][:100], "args": args, "why": str(proposal.get("why") or "")[:WHY_MAX]}


def _parse(data):
    """바이트 -> (줄 목록, 깨진 줄 수). 깨진 줄은 건너뛴다(파일은 고치지 않는다)."""
    rows, bad = [], 0
    for line in (data or b"").decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            bad += 1
    return rows, bad


class Recorded:
    """record의 돌려주는 값. status: written(새로 씀) | duplicate(같은 열쇠가 이미 있음) | failed(쓰지 못함, error에 이유).
    `row, written = record(...)`처럼 둘로 풀어 쓸 수도 있다. 쓰기 실패는 예외가 아니라 status로 알린다: 기록이 안 된다고 이미
    끝난 동작을 되돌리거나 화면을 깨지 않고, 부른 쪽이 '기록하지 못함'을 사용자에게 보인다."""

    def __init__(self, row, status, error=None):
        self.row, self.status, self.error = row, status, error

    @property
    def written(self):
        return self.status == "written"

    @property
    def ok(self):
        return self.status != "failed"

    def __iter__(self):
        yield self.row
        yield self.written

    def __repr__(self):
        return "Recorded(%s)" % self.status


@contextlib.contextmanager
def _file_lock(path, timeout=None):
    """프로젝트 폴더의 .lock 파일에 건 프로세스 간 잠금. 못 잡으면 TimeoutError(OSError)."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fh = open(os.path.join(folder, LOCK_NAME), "a+b")
    timeout = LOCK_SECONDS if timeout is None else timeout
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fh.seek(0)
                if msvcrt is not None:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("실행 기록 잠금을 %d초 안에 잡지 못함" % timeout)
                time.sleep(0.02)
        try:
            yield
        finally:
            fh.seek(0)
            if msvcrt is not None:
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def _same(row, key, result, undo_of):
    return row.get("action_key") == key and row.get("result") == result and row.get("undo_of") == undo_of


def record(project_id, *, answer_id, index, request_id, request_text, proposal, klass, result, error=None, targets=(),
           batch_id=None, undo_of=None, confirmed_by=None, confirmed_at=None, approval_digest=None, conversation_id=None,
           model=None, via=None, app_version=None, now=None):
    """한 줄을 덧붙인다 -> Recorded. 같은 (action_key, result, undo_of)가 이미 있으면 status=duplicate와 이미 있는 줄.
    잘못된 값(result·class 밖, 확인 아닌 동작에 확인자)은 ValueError, 파일을 쓰지 못한 것은 status=failed(예외 아님)."""
    if result not in RESULTS:
        raise ValueError("result는 %s 중 하나: %r" % (", ".join(RESULTS), result))
    if klass not in CLASSES:
        raise ValueError("class는 %s 중 하나: %r" % (", ".join(CLASSES), klass))
    if (confirmed_by or confirmed_at or approval_digest) and klass != "confirm":
        raise ValueError("확인자·확인 시각·승인 표지는 확인 상자를 거친 동작에만 쓴다")
    key = action_key(answer_id, index)
    if not _KEY_RE.match(key) or not _KEY_RE.match(str(request_id)):
        raise ValueError("request_id·answer_id 형식이 올바르지 않음")
    when = (now or now_kst()).astimezone(KST).replace(microsecond=0)
    row = {"schema": SCHEMA, "at": when.isoformat(), "project_id": project_id, "conversation_id": conversation_id,
           "request_id": request_id, "answer_id": answer_id, "action_key": key,
           "request_text": str(request_text or "")[:REQUEST_TEXT_MAX], "model_proposal": _proposal(proposal),
           "class": klass, "result": result, "error": None if error is None else str(error)[:ERROR_MAX],
           "targets": [str(t) for t in targets], "batch_id": batch_id, "undo_of": undo_of,
           "confirmed_by": confirmed_by, "confirmed_at": confirmed_at, "approval_digest": approval_digest,
           "model": model, "via": via, "app_version": app_version}
    path = day_path(project_id, when)
    before = day_path(project_id, when - timedelta(days=1))
    last = None
    with _LOCK:
        for attempt in range(RETRIES):
            try:
                with _file_lock(path):   # 앱 창을 둘 띄워도(프로세스가 둘이어도) 한 번에 하나만 읽고 쓴다
                    seen = _parse(store_io.read_bytes(before)[0])[0]
                    existing, fp = store_io.read_bytes(path)  # 읽기와 지문은 한 번에(그 사이에 바뀐 파일을 읽은 것으로 착각하지 않게)
                    dup = next((r for r in _parse(existing)[0] + seen if _same(r, key, result, undo_of)), None)
                    if dup is not None:
                        return Recorded(dup, "duplicate")
                    body = existing or b""
                    if body and not body.endswith(NL):
                        body += NL  # 앞 쓰기가 끊겼어도 새 줄은 줄 첫머리에서 시작한다
                    body += json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + NL
                    store_io.write_bytes(path, body, expect=fp)
                    return Recorded(row, "written")
            except (store_io.Conflict, OSError) as exc:   # 잠금 시간 초과·교체 중 접근 거부·그 사이 바뀐 파일: 짧게 쉬고 다시
                last = exc
                time.sleep(RETRY_PAUSE * (attempt + 1))
    return Recorded(row, "failed", "%s: %s" % (type(last).__name__, str(last)[:200]))   # 동작 실행을 막지 않는다. 부른 쪽이 알린다


def read_day(project_id, day):
    """그날 기록(파일 순서) -> (줄 목록, 깨진 줄 수). 폴더 이름은 safe_name(project_id)라 다른 프로젝트('P A'와 'P_A')가 같은 폴더를
    쓸 수 있으므로, 줄의 project_id가 이 프로젝트인 것만 돌려준다(다른 프로젝트 줄은 깨진 줄로 세지 않는다)."""
    rows, bad = _parse(store_io.read_bytes(day_path(project_id, day))[0])
    return [r for r in rows if r.get("project_id") == project_id], bad


def read_recent(project_id, days=7, today=None):
    """오늘부터 지난 days-1일까지의 기록을 최근 것부터 -> (줄 목록, 깨진 줄 수). 규격: 오늘과 지난 7일 → days=8."""
    today = today or now_kst()
    if isinstance(today, datetime):
        today = today.astimezone(KST).date()
    out, bad = [], 0
    for back in range(max(1, int(days))):
        rows, b = read_day(project_id, today - timedelta(days=back))
        out += list(reversed(rows))
        bad += b
    return out, bad
