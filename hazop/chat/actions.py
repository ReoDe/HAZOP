"""채팅 답 카드의 '제안 동작'을 앱이 검사·분류·실행하는 층(규격 docs/specs/chat-panel.md §4, §2.6). Qt를 import하지 않는다.

모델이 쓸 수 있는 것은 `action`·`args`·`why`뿐이다(§4.1). 이 모듈은
1. 동작 표(ACTIONS)로 이름·인자 서명·분류(표시·바로·후보·확인·안 함)를 정하고,
2. 지금 프로젝트 상태(Snapshot, 부르는 쪽이 읽어 넘김)로 대상·잠금·확정·개정을 검사해 `plan()`이 [바로 실행할 것, 확인 받을 것,
   거절한 것과 사유, 표시]로 나누고,
3. 확인 동작에는 승인 표지(§4.6)를 만들어 실행 직전에 다시 대조하며,
4. 같은 `action_key`를 두 번 실행하지 않고, 표시를 뺀 모든 결과를 `hazop.chat.actions_log.record`로 남긴다.

실제 실행은 하지 않는다. 실행 함수는 `executors={동작 이름: fn(args, call) -> dict}`로 주입받는다(새 화면 `hazop/shell/api.py`가
엔진 함수를 잇는다. 구간 동작은 `node_executors(pg, node_commands.execute)`가 참고 연결부다). 구간 규칙(대표 5개·나머지 30개, AI가 사람 구간을 못 고침, 잠금·확정)은 `hazop.study.node_tools.apply_nodes`·
`undo_batch`가 최종으로 지키고, 이 층은 그 앞에서 '바로 / 확인 / 거절'을 가르고 질문을 건너 쌓이는 상한(§4.5)을 센다.
"""

import copy
import hashlib
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

from hazop.chat import actions_log

# ---------------------------------------------------------------- 분류

DISPLAY, AUTO, CANDIDATE, CONFIRM, NEVER = "display", "auto", "candidate", "confirm", "never"
CLASS_NAMES = {DISPLAY: "표시", AUTO: "바로", CANDIDATE: "후보", CONFIRM: "확인", NEVER: "안 함"}
MAX_ACTIONS = 20             # 한 답의 동작 수(§4.1)
PENDING_LIMIT = 5            # 사람 확인 전 AI 구간 상한(§4.5 대표 단계)
REST_LIMIT = 30              # '나머지' 단계 한 요청 상한(§4.5)
APPROVAL_TTL = 600           # 승인 표지 유효 시간(초, §4.6)
# 엔진이 사람만 받는 구간 상태 동작(node_commands.STATE_COMMANDS 가운데 채팅이 제안할 수 있는 것). 확인 상자로만 실행된다
STATE_ACTIONS = frozenset(("nodes.confirm", "nodes.unconfirm", "nodes.lock"))
# 모델이 넣으면 그 동작을 거절하는 키(§4.1, 차단 11). 기록의 신뢰 필드는 앱이 만든다
FORGED_KEYS = frozenset(("request_id", "answer_id", "action_key", "batch_id", "result", "confirmed_by", "confirmed_at",
                         "approval_digest", "conversation_id", "by", "origin", "reviewer", "accepted_by", "proposed_by",
                         "at", "class", "undo_of"))
# 제어 문자(줄바꿈·탭 제외). 글 인자(이름·설계 의도·이유)에는 경로 검사를 하지 않는다: '50%~100%' 같은 정상 글이 걸린다
# (검토 5). 경로처럼 생긴 값은 ID 형(_ID)이 막는다(드라이브 글자·역슬래시·'..'·'%'·'~'는 ID 글자가 아니다).
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ID = re.compile(r"^[A-Za-z0-9_.#-]+(/[A-Za-z0-9_.#-]+)*$")


# ---------------------------------------------------------------- 상태(부르는 쪽이 읽어 넘김)

@dataclass
class Snapshot:
    """지금 프로젝트 상태. plan()과 approve() 직전에 부르는 쪽이 새로 읽어 넘긴다(read_state).

    files: 대상 열쇠 -> {"path", "size", "mtime"}. 열쇠는 등록 ID(추출 결과), "kg"(지식그래프), "ie"(초기사건 문서).
    """
    project_id: str
    node_set: dict = None
    results: dict = None
    graph_ids: frozenset = frozenset()
    registrations: dict = field(default_factory=dict)   # reg_id -> {"has_result": bool, "excluded": bool}
    files: dict = field(default_factory=dict)
    ie_draft_by_human: bool = False


def _nodes(snap):
    return {n.get("node_id"): n for n in ((snap.node_set or {}).get("nodes") or [])}


def node_state(n):
    if n.get("state") in ("applied", "confirmed", "locked"):
        return n["state"]
    return "locked" if n.get("locked") else ("confirmed" if n.get("confirmed") else "applied")


def _cells(snap, nid):
    return [c for c in ((snap.results or {}).get("cells") or []) if c.get("node_id") == nid]


def has_cells(snap, nid):
    """⑤ 칸에 항목이나 판정이 남은 구간(§4.3 마지막 줄)."""
    return any(c.get("entries") or c.get("state") not in (None, "not_analyzed") for c in _cells(snap, nid))


def _batch(snap, bid):
    return next((b for b in ((snap.node_set or {}).get("batches") or []) if b.get("batch_id") == bid), None)


def human_touched(n):
    return n.get("name_by") == "user" or (n.get("design_intent") or {}).get("by") == "user"


def pending_ai(snap):
    """사람 확인 전 AI 구간 수(§4.5-1): origin ai·applied이고, 그 구간의 마지막 묶음이 AI 묶음이며 human_seen이 아니고,
    사람이 이름·설계 의도를 고친 적 없는 구간. 묶음의 human_seen은 구간 규격 묶음 필드(N1)이고, 없으면 아직 안 본 것으로 센다."""
    count = 0
    for n in _nodes(snap).values():
        if n.get("origin") != "ai" or node_state(n) != "applied" or human_touched(n):
            continue
        b = _batch(snap, n.get("batch_id"))
        if b is not None and (b.get("origin") != "ai" or b.get("human_seen")):
            continue
        count += 1
    return count


# ---------------------------------------------------------------- 인자 서명

def _is_id(v):
    return isinstance(v, str) and 0 < len(v) <= 200 and bool(_ID.match(v)) and ".." not in v.split("/")


def _ids(v, limit=200):
    return isinstance(v, list) and 0 < len(v) <= limit and all(_is_id(x) for x in v)


TYPES = {
    "str": lambda v: isinstance(v, str) and 0 < len(v) <= 500 and not _CONTROL.search(v),
    "text": lambda v: isinstance(v, str) and len(v) <= 2000 and not _CONTROL.search(v),
    "id": _is_id,
    "ids": _ids,
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "obj": lambda v: isinstance(v, dict) and len(v) <= 50 and _clean(v),
    "list": lambda v: isinstance(v, list) and len(v) <= 200,
}


def _spec(*required, **optional):
    """_spec(("node_ids", "ids"), stage=("str",)) 형태: 필수는 (이름, 형) 튜플, 선택은 이름=형."""
    out = {name: (kind, True) for name, kind in required}
    out.update({name: (kind, False) for name, kind in optional.items()})
    return out


@dataclass(frozen=True)
class Action:
    name: str
    klass: str                   # 기본 분류. nodes.apply·nodes.undo 등은 check가 상태에 따라 바꾼다
    args: dict                   # 인자 이름 -> (형, 필수)
    stage: str                   # 단계(공통·①~⑥)
    note: str = ""               # 보존되는 것·비고(§4.2 표의 넷째 칸)
    confirm_text: str = ""       # 확인 상자 문구 틀(앱이 검사한 값만 넣음)
    where: str = ""              # 안 함 동작: 사람이 할 곳


ACTIONS = {a.name: a for a in (
    # 공통 · 표시(데이터를 바꾸지 않음, 기록하지 않음)
    Action("show", DISPLAY, _spec(sheet="id", ids="ids", path_ref="obj", style="str"), "공통", "도면 이동·강조·경로 표시"),
    Action("goto", DISPLAY, _spec(("target", "str"), id="id"), "공통", "단계·탭 이동, 항목 열기"),
    Action("select", DISPLAY, _spec(("ids", "ids")), "공통", "구성요소·구간·칸 고르기"),
    Action("layer", DISPLAY, _spec(("name", "str"), on="bool"), "공통", "도면 층 켜기·끄기"),
    Action("fit", DISPLAY, _spec(sheet="id"), "공통", "도면 맞춤"),
    # ①
    Action("register.extract", AUTO, _spec(("registration_id", "id")), "①",
           "결과가 없을 때만. 파일 고르기 창을 열지 않고 경로를 채팅으로 받지 않는다"),
    Action("register.reextract", CONFIRM, _spec(("registration_id", "id")), "①",
           "추출 결과를 새로 쓴다. 사람 수정 기록은 쓰지 않고 새 결과 위에 다시 얹는다",
           "등록 자료 {registration_id}를 다시 추출합니다. 추출 결과는 새로 쓰고, 사람 수정 기록은 새 결과 위에 다시 얹습니다."),
    Action("register.exclude", CONFIRM, _spec(("registration_id", "id")), "①", "등록 기록은 지우지 않음",
           "등록 자료 {registration_id}를 구간 분석에서 뺍니다. 등록 기록은 지우지 않습니다."),
    # ②
    Action("extract.suggest", CANDIDATE, _spec(("sheet", "id"), ("target", "id"), ("field", "str"), value="text",
                                               reason="text"), "②",
           "태그·종류·흐름 방향·미확인 확정·끊긴 연결·짝 지정의 후보만. 사람이 받아들일 때만 반영(origin: ai)"),
    Action("extract.edit", NEVER, _spec(), "②", "편집 저장·객체 지우기·연결 끊기", where="② 도면 추출 화면에서 사람이 한다"),
    # ③
    Action("kg.algorithm", AUTO, _spec(("name", "str"), params="obj"), "③", "결과는 내용 ID 폴더에 새로 씀(덮지 않음)"),
    Action("kg.rebuild", CONFIRM, _spec(), "③", "사람 지식 CSV와 언급 판단 파일은 쓰지 않음",
           "지식그래프를 다시 만듭니다. 사람 지식과 언급 판단 파일은 그대로 두고, 판이 바뀐 사람 확인은 후보로 돌아갑니다."),
    # ④
    Action("nodes.apply", AUTO, _spec(("set_rev", "int"), ("ops", "list"), graph_id="id"), "④",
           "§4.3 표·§4.5 상한. 구간 규격 apply_nodes",
           "AI가 만든 구간 {pending}개를 아직 확인하지 않았습니다. 이 요청으로 {adds}개를 더 만들고 {edits}개를 바꿉니다."),
    Action("nodes.undo", AUTO, _spec(("batch_id_to_undo", "id"), ("set_rev", "int")), "④", "§4.3 표. 구간 규격 undo_batch",
           "묶음 {batch}를 되돌립니다."),
    Action("nodes.confirm", CONFIRM, _spec(("node_ids", "ids")), "④", "사람 판단. 실행하면 by에 검토자",
           "구간 {node_ids}을 확정합니다."),
    # unconfirm·lock은 node_commands와 같이 node_ids 목록(node-commands.md §2, a9c0193)
    Action("nodes.unconfirm", CONFIRM, _spec(("node_ids", "ids")), "④", "사람 판단",
           "구간 {node_ids}의 확정을 해제합니다."),
    Action("nodes.lock", CONFIRM, _spec(("node_ids", "ids")), "④", "분석 마침·잠금. 구간 규격 §5.1 조건을 채운 구간만",
           "구간 {node_ids}을 분석 마침으로 잠급니다. 잠금은 ④에서 이유를 적어야만 풀립니다."),
    Action("nodes.unlock", NEVER, _spec(), "④", "차단 9", where="④ 검토구간에서 사람이 이유를 적고 푼다"),
    # ⑤
    Action("analysis.run", CONFIRM, _spec(("node_ids", "ids"), cell_ids="ids"), "⑤",
           "구독 한도를 쓴다. 사람이 쓴 항목은 바꾸지 않음",
           "구간 {node_ids}을 AI로 분석합니다(구독 한도를 씁니다). 사람이 쓴 항목은 바꾸지 않습니다."),
    Action("results.set_status", CONFIRM, _spec(("cell_id", "id"), ("status", "str")), "⑤", "사람 판단. 잠긴 구간의 칸은 거절",
           "칸 {cell_id}의 상태를 {status}(으)로 바꿉니다."),
    Action("results.edit", CONFIRM, _spec(("cell_id", "id"), ("fields", "obj")), "⑤", "사람 판단. 잠긴 구간의 칸은 거절",
           "칸 {cell_id}의 내용을 고칩니다."),
    Action("export.excel", AUTO, _spec(), "⑤", "이름에 시각을 붙인 새 파일"),
    Action("export.ie_bundle", AUTO, _spec(), "⑤", "이름에 시각을 붙인 새 파일"),
    # ⑥
    Action("ie.draft_rules", AUTO, _spec(), "⑥", "초안. 기존 초안을 사람이 고쳤으면 확인",
           "사람이 고친 초기사건 규칙 초안을 새 초안으로 바꿉니다."),
    Action("ie.reset", CONFIRM, _spec(), "⑥", "원본은 백업 파일로 남음",
           "초기사건 문서를 백업한 뒤 빈 문서로 새로 시작합니다. 원본은 백업 파일로 남습니다."),
    # 공통 · 안 함
    Action("settings.change", NEVER, _spec(), "공통", "AI 연결 방식·초과 사용 허용·모델", where="설정 창에서 한다"),
    Action("settings.api_key", NEVER, _spec(), "공통", "API 키", where="설정 창에서 한다"),
    Action("settings.work_root", NEVER, _spec(), "공통", "작업 루트", where="설정 창에서 한다"),
    Action("settings.reviewer", NEVER, _spec(), "공통", "검토자 이름", where="설정 창에서 한다"),
    Action("files.delete", NEVER, _spec(), "공통", "파일·폴더 지우기", where="탐색기에서 사람이 한다"),
)}

RESULT_STATUSES = ("approved", "rejected", "pending")
SUGGEST_FIELDS = ("tag", "kind", "flow_direction", "unknown_confirm", "connect", "pair")


def table_rows():
    """동작 표(§4.2)를 행 목록으로: [{name, class, class_name, stage, note, args, where}]. 문서·시험·화면이 같은 표를 읽는다."""
    return [{"name": a.name, "class": a.klass, "class_name": CLASS_NAMES[a.klass], "stage": a.stage, "note": a.note,
             "args": {k: v[0] + ("" if v[1] else "?") for k, v in a.args.items()}, "where": a.where}
            for a in ACTIONS.values()]


# ---------------------------------------------------------------- 계획

@dataclass
class Item:
    """한 동작의 판정. keys: 이 판정에 묶인 action_key 목록(같은 답의 nodes.apply는 하나로 합친다)."""
    keys: list
    indexes: list
    action: str
    args: dict
    why: str
    klass: str
    reason: str = None           # 거절 사유(klass == "rejected"일 때)
    where: str = None            # 사람이 할 곳(안 함)
    confirm_text: str = None
    approval: dict = None        # 확인 동작의 승인 표지
    stage: str = None            # nodes.apply: "representative" | "rest"
    targets: list = field(default_factory=list)
    proposals: list = field(default_factory=list)
    token: str = None            # planner가 낸 무작위 표(run·approve·decline에 넘김). 화면은 이 값만 들고 있으면 된다

    @property
    def key(self):
        return self.keys[0]


@dataclass
class Plan:
    answer_id: str
    run: list = field(default_factory=list)        # 바로·후보: run()으로 실행
    confirm: list = field(default_factory=list)    # 확인: 사람이 누르면 approve(), 거절하면 decline()
    rejected: list = field(default_factory=list)   # 앱 검사에서 거절(이미 기록함)
    display: list = field(default_factory=list)    # 표시: 화면이 바로 그림(기록 없음)


AUTHOR = "ai"   # 채팅에서 온 동작의 글은 늘 AI가 썼다(사람이 확인 상자를 눌렀어도)


@dataclass
class Call:
    """실행 함수에 넘기는 앱 값. 모델 값은 args뿐이다.

    누가 그 글을 썼나(author)와 누가 실행을 허락했나(confirmed_by)를 따로 둔다(검토 R6). 채팅에서 온 동작은 사람이 확인했어도
    author가 "ai"이고, 연결부는 엔진에 출처를 AI로 넘겨야 한다(`engine_request()`). 그래야 AI가 쓴 구간이 사람 것으로 저장되어
    누적 상한(§4.5)이 풀리는 일이 없다.
    """
    project_id: str
    request_id: str
    request_text: str
    action_keys: list
    klass: str                   # "auto" | "candidate" | "confirm"(사람이 확인 상자에서 누름)
    confirmed_by: str = None     # 확인 상자에서 누른 사람. 바로·후보 동작은 None
    stage: str = None            # nodes.apply: representative | rest
    confirmed_rest: bool = False  # '나머지' 단계를 사람이 확인함(그때까지의 AI 묶음을 human_seen으로)
    user_turn: str = None        # 이 동작을 낳은 사용자 메시지(질문 ID). 같은 메시지 안의 '나머지'를 엔진도 막는다
    conversation_id: str = None
    model: str = None
    author: str = AUTHOR

    action: str = None           # 동작 이름(ACTIONS의 열쇠)

    @property
    def origin(self):
        """글을 쓴 쪽. 늘 "ai"다(사람이 확인했어도 글은 AI가 썼다)."""
        return self.author

    def engine_author(self):
        """`node_commands.execute`의 author. 확정·확정 해제·잠금은 글이 없는 사람 판단이라 엔진이 사람만 받는다(node-commands.md
        §1): 확인 상자를 누른 사람이 있으면 "user". 그 밖의 구간 동작은 사람이 확인했어도 "ai"다(R6)."""
        if self.action in STATE_ACTIONS and self.confirmed_by:
            return "user"
        return self.author

    def engine_request(self):
        """`node_commands.execute(..., request=…)`에 넘길 값(AI 동작만 쓰임). 누른 사람은 엔진이 confirmed_by 인자로 받는다."""
        return {"request_id": self.request_id, "request_text": self.request_text, "user_turn": self.user_turn,
                "confirmed_rest": self.confirmed_rest, "tool": "chat", "model": self.model}

    def engine_kwargs(self):
        """`node_commands.execute(pg, 명령, 인자, **call.engine_kwargs(), set_rev=…)`의 서명 인자(a9c0193)."""
        return {"author": self.engine_author(), "confirmed_by": self.confirmed_by, "request": self.engine_request()}


def _digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _forged(args, depth=0):
    if depth > 4:
        return None
    if isinstance(args, dict):
        for k, v in args.items():
            if k in FORGED_KEYS:
                return k
            bad = _forged(v, depth + 1)
            if bad:
                return bad
    elif isinstance(args, list):
        for v in args:
            bad = _forged(v, depth + 1)
            if bad:
                return bad
    return None


def _clean(value, depth=0):
    """글·목록·객체 안의 글이 길이 상한 안이고 제어 문자가 없는지. 경로 검사는 하지 않는다(ID 형이 막는다)."""
    if depth > 5:
        return False
    if isinstance(value, str):
        return len(value) <= 2000 and not _CONTROL.search(value)
    if isinstance(value, dict):
        return len(value) <= 50 and all(isinstance(k, str) and _clean(k, depth + 1) and _clean(v, depth + 1)
                                        for k, v in value.items())
    if isinstance(value, list):
        return len(value) <= 2000 and all(_clean(v, depth + 1) for v in value)
    return value is None or isinstance(value, (bool, int, float))


def check_signature(action, args):
    """-> None 또는 거절 사유."""
    if not isinstance(args, dict):
        return "인자는 객체여야 함"
    extra = sorted(k for k in args if k not in action.args)
    if extra:
        return "서명에 없는 인자: %s" % ", ".join(extra[:5])
    for name, (kind, required) in action.args.items():
        if name not in args or args[name] is None:
            if required:
                return "필수 인자 없음: %s" % name
            continue
        if not TYPES[kind](args[name]):
            return "인자 형이 맞지 않음: %s" % name
    if not _clean(args):
        return "글이 너무 길거나 제어 문자가 있음"
    return None


class _Reject(Exception):
    def __init__(self, reason, where=None):
        super().__init__(reason)
        self.reason, self.where = reason, where


class ActionPlanner:
    """대화 하나(채팅 프로세스 하나) 동안의 동작 판정·실행·기록.

    read_state() -> Snapshot: plan()·approve() 때마다 새로 읽는다.
    executors: {동작 이름: fn(args, call: Call) -> dict}. 돌려주는 dict의 "targets"·"batch_id"를 기록에 쓴다. 예외는 failed.
    record: actions_log.record와 같은 서명(시험은 가짜를 넘긴다).
    """

    def __init__(self, project_id, read_state, executors, record=actions_log.record, conversation_id=None, model=None,
                 via="subscription", app_version=None, clock=time.time):
        self.project_id = project_id
        self.read_state = read_state
        self.executors = dict(executors or {})
        self._record = record
        self.conversation_id = conversation_id or actions_log.new_id("conv")
        self.model, self.via, self.app_version = model, via, app_version
        self.clock = clock
        self._lock = threading.RLock()
        self.done_keys = set()           # 실행(또는 결론)한 action_key: 두 번 실행하지 않는다
        self.conv_batches = set()        # 이번 대화에서 AI가 만든 묶음
        self.last_add_turn = None        # 마지막으로 AI 구간을 바로 적용한 사용자 질문 번호
        self.exec_seq = 0                # 실행한 동작 수(표지 사이에 다른 동작이 실행됐는지)
        self.requests = {}               # answer_id -> (request_id, request_text, turn)
        self.closed = False
        self.log = []                    # 기록 결과(시험·화면 알림)
        self._items = {}                 # token -> 판정한 Item(이 메모리에만 있다)
        self._secret = secrets.token_hex(16)   # 승인 표지 재료. 웹·모델이 모르는 값

    # ---- 계획

    def plan(self, answer_id, actions, turn, request_id, request_text=""):
        """답 하나의 동작 목록 -> Plan. 거절은 여기서 기록한다. turn: 이 대화에서 사용자가 보낸 질문 번호(1부터)."""
        snap = self.read_state()
        out = Plan(answer_id)
        with self._lock:
            self.requests[answer_id] = (request_id, request_text, turn)
            actions = actions if isinstance(actions, list) else []
            node_items = []
            for i, raw in enumerate(actions):
                key = actions_log.action_key(answer_id, i)
                prop = raw if isinstance(raw, dict) else {}
                name = prop.get("action") if isinstance(prop.get("action"), str) else ""
                item = Item([key], [i], name[:100], copy.deepcopy(prop.get("args")) if isinstance(prop.get("args"), dict)
                            else prop.get("args"), str(prop.get("why") or "")[:300], NEVER,
                            proposals=[{"action": name[:100] or "?", "args": prop.get("args"), "why": prop.get("why")}])
                try:
                    if i >= MAX_ACTIONS:
                        raise _Reject("한 답의 동작은 %d개까지" % MAX_ACTIONS)
                    self._check(item, snap)
                except _Reject as rej:
                    item.klass, item.reason, item.where = "rejected", rej.reason, rej.where
                if item.klass == "rejected":
                    out.rejected.append(item)
                elif item.action == "nodes.apply":
                    node_items.append(item)
                else:
                    self._route(out, item, snap)
            if node_items:
                merged = self._merge_nodes(node_items, snap, turn)
                if merged.klass == "rejected":
                    out.rejected.append(merged)
                else:
                    self._route(out, merged, snap)
            for item in out.rejected:
                self._write(item, "rejected", error=item.reason)
        return out

    def _route(self, out, item, snap):
        if item.klass == DISPLAY:
            out.display.append(item)
        elif item.klass in (AUTO, CANDIDATE):
            out.run.append(self._keep(item))
        elif item.klass == CONFIRM:
            item.approval = self._approval(item, snap)
            out.confirm.append(self._keep(item))

    def _check(self, item, snap):
        action = ACTIONS.get(item.action)
        if action is None:
            raise _Reject("동작 표에 없는 동작(채팅으로 할 수 없음)")
        if action.klass == NEVER:
            raise _Reject("채팅으로 하지 않는 동작", action.where)
        bad = _forged(item.args)
        if bad:
            raise _Reject("앱이 정하는 값(%s)을 모델이 넣음" % bad)
        bad = check_signature(action, item.args)
        if bad:
            raise _Reject(bad)
        item.klass = action.klass
        check = getattr(self, "_check_" + item.action.replace(".", "_"), None)
        if check is not None:
            check(item, snap)
        if item.klass == CONFIRM and action.confirm_text and not item.confirm_text:
            item.confirm_text = _fill(action.confirm_text, item.args)

    # ---- 동작별 검사

    def _reg(self, item, snap):
        rid = item.args["registration_id"]
        reg = snap.registrations.get(rid)
        if reg is None:
            raise _Reject("지금 프로젝트에 없는 등록 자료")
        item.targets = [rid]
        return reg

    def _check_register_extract(self, item, snap):
        if self._reg(item, snap).get("has_result"):
            raise _Reject("이미 추출 결과가 있음(다시 추출은 register.reextract, 확인 필요)")

    def _check_register_reextract(self, item, snap):
        self._reg(item, snap)

    def _check_register_exclude(self, item, snap):
        if self._reg(item, snap).get("excluded"):
            raise _Reject("이미 구간 분석에서 뺀 자료")

    def _check_extract_suggest(self, item, snap):
        a = item.args
        if a["field"] not in SUGGEST_FIELDS:
            raise _Reject("고칠 수 있는 항목이 아님(%s)" % ", ".join(SUGGEST_FIELDS))
        if snap.graph_ids and a["target"] not in snap.graph_ids:
            raise _Reject("지금 프로젝트 그래프에 없는 대상")
        item.targets = [a["target"]]

    def _check_kg_rebuild(self, item, snap):
        item.targets = ["kg"]

    def _check_ie_draft_rules(self, item, snap):
        if snap.ie_draft_by_human:
            item.klass = CONFIRM
            item.targets = ["ie"]

    def _check_ie_reset(self, item, snap):
        item.targets = ["ie"]

    def _need_nodes(self, item, snap, allow=("applied", "confirmed")):
        nodes = _nodes(snap)
        ids = item.args["node_ids"] if "node_ids" in item.args else [item.args["node_id"]]
        for nid in ids:
            n = nodes.get(nid)
            if n is None:
                raise _Reject("없는 구간: %s" % nid)
            if node_state(n) not in allow:
                raise _Reject("%s 구간은 이 동작을 할 수 없음: %s" % (node_state(n), nid))
        item.targets = list(ids)

    def _check_nodes_confirm(self, item, snap):
        self._need_nodes(item, snap, ("applied",))

    def _check_nodes_unconfirm(self, item, snap):
        self._need_nodes(item, snap, ("confirmed",))

    def _check_nodes_lock(self, item, snap):
        self._need_nodes(item, snap, ("confirmed",))

    def _check_analysis_run(self, item, snap):
        self._need_nodes(item, snap)

    def _cell(self, item, snap):
        cid = item.args["cell_id"]
        parts = cid.split("/")
        if len(parts) < 2:
            raise _Reject("칸 ID 형식이 아님(<node_id>/<deviation_id>[/<entry_id>])")
        n = _nodes(snap).get(parts[0])
        if n is None:
            raise _Reject("없는 구간의 칸")
        if node_state(n) == "locked":
            raise _Reject("잠긴 구간의 칸은 바꾸지 않음(④에서 사람이 이유를 적고 풀어야 함)")
        cell = next((c for c in _cells(snap, parts[0]) if c.get("deviation_id") == parts[1]), None)
        if cell is None:
            raise _Reject("없는 칸")
        if len(parts) > 2 and not any(e.get("entry_id") == parts[2] for e in cell.get("entries") or []):
            raise _Reject("없는 항목")
        item.targets = [cid]

    def _check_results_set_status(self, item, snap):
        if item.args["status"] not in RESULT_STATUSES:
            raise _Reject("상태는 %s 중 하나" % ", ".join(RESULT_STATUSES))
        self._cell(item, snap)

    def _check_results_edit(self, item, snap):
        self._cell(item, snap)

    def _check_nodes_undo(self, item, snap):
        bid = item.args["batch_id_to_undo"]
        b = _batch(snap, bid)
        if b is None:
            raise _Reject("없는 묶음(되돌릴 수 있는 최근 묶음 밖)")
        if b.get("undone"):
            raise _Reject("이미 되돌린 묶음")
        if item.args["set_rev"] != (snap.node_set or {}).get("set_rev"):
            raise _Reject("구간이 그 사이 바뀜(set_rev)")
        if b.get("origin") != "ai":
            raise _Reject("사람 묶음은 채팅으로 되돌리지 않음", "④ 검토구간에서 사람이 되돌린다")
        nodes = _nodes(snap)
        for o in b.get("ops") or []:
            n = nodes.get(o.get("node_id"))
            if n is not None and node_state(n) in ("confirmed", "locked"):
                raise _Reject("확정·잠금 구간이 든 묶음(%s)" % n["node_id"], "④에서 확정 해제 뒤 다시 요청")
            if n is not None and has_cells(snap, n["node_id"]):
                raise _Reject("⑤ 칸이 있는 구간이 든 묶음(%s)" % n["node_id"])
        item.targets = sorted({o.get("node_id") for o in b.get("ops") or []})
        item.klass = AUTO if bid in self.conv_batches else CONFIRM
        item.confirm_text = _fill(ACTIONS["nodes.undo"].confirm_text, {"batch": bid})

    def _merge_nodes(self, items, snap, turn):
        """같은 답의 nodes.apply를 묶음 하나로 합치고 §4.3·§4.5로 분류한다."""
        keys = [k for it in items for k in it.keys]
        merged = Item(keys, [i for it in items for i in it.indexes], "nodes.apply",
                      {"set_rev": items[0].args["set_rev"], "ops": [o for it in items for o in it.args["ops"]]},
                      " / ".join(it.why for it in items if it.why)[:300], AUTO,
                      proposals=[p for it in items for p in it.proposals])
        if items[0].args.get("graph_id"):
            merged.args["graph_id"] = items[0].args["graph_id"]
        try:
            if any(it.args["set_rev"] != merged.args["set_rev"] for it in items):
                raise _Reject("같은 답의 구간 동작이 서로 다른 set_rev를 씀")
            self._check_set(merged, snap, [it.args.get("graph_id") for it in items])
            self._classify_ops(merged, snap, turn)
        except _Reject as rej:
            merged.klass, merged.reason, merged.where = "rejected", rej.reason, rej.where
        return merged

    @staticmethod
    def _check_set(item, snap, graph_ids=None):
        """set_rev와 graph_id를 지금 집합과 대조한다(검토 4)."""
        ns = snap.node_set or {}
        if item.args["set_rev"] != ns.get("set_rev"):
            raise _Reject("구간이 그 사이 바뀜(set_rev %s, 지금 %s)" % (item.args["set_rev"], ns.get("set_rev")))
        for gid in graph_ids if graph_ids is not None else [item.args.get("graph_id")]:
            if gid is not None and gid != ns.get("graph_id"):
                raise _Reject("지금 검토구간 집합의 graph_id가 아님(%s)" % gid)

    def _classify_ops(self, item, snap, turn):
        nodes = _nodes(snap)
        adds, edits, klass, targets = 0, 0, AUTO, []
        for i, op in enumerate(item.args["ops"]):
            if not isinstance(op, dict) or op.get("op") not in ("add", "edit", "merge", "split", "remove"):
                raise _Reject("%d번째 op가 구간 동작이 아님" % (i + 1))
            if op["op"] == "add":
                if not (op.get("cand_id") or op.get("members")):
                    raise _Reject("%d번째 add에 cand_id나 members가 없음" % (i + 1))
                if op.get("members") is not None and not (_ids(op["members"], 2000) and
                                                           (not snap.graph_ids or set(op["members"]) <= snap.graph_ids)):
                    raise _Reject("%d번째 add의 구성요소가 지금 그래프에 없음" % (i + 1))
                adds += 1
                continue
            ids = op.get("node_ids") if op["op"] == "merge" else [op.get("node_id")]
            if not ids or not all(_is_id(x) for x in ids):
                raise _Reject("%d번째 %s에 구간 ID가 없음" % (i + 1, op["op"]))
            for nid in ids:
                n = nodes.get(nid)
                if n is None:
                    raise _Reject("없는 구간: %s" % nid)
                k = self._node_class(n, op, snap)
                targets.append(nid)
                if k == "rejected":
                    raise _Reject(self._node_reason(n, op, snap), "④ 검토구간에서 사람이 한다")
                if k == CONFIRM:
                    klass = CONFIRM
            if op["op"] == "split":  # 나누기로 생기는 구간도 새 AI 구간으로 센다(엔진과 같은 셈, 검토 3)
                adds += 1
            edits += 1
        pending = pending_ai(snap)
        stage = "representative"
        if adds:
            if pending + adds > PENDING_LIMIT:
                if self.last_add_turn is not None and turn <= self.last_add_turn:
                    raise _Reject("대표 구간 확인 전에는 같은 질문에서 구간을 더 만들지 않음(새 질문 뒤 확인을 받아 진행)")
                if pending == 0 and adds > PENDING_LIMIT and self.last_add_turn is None:
                    raise _Reject("대표 구간은 한 번에 %d개까지(먼저 대표 구간을 만들고 사람이 확인)" % PENDING_LIMIT)
                if adds > REST_LIMIT:
                    raise _Reject("한 요청에서 만들 수 있는 구간은 %d개" % REST_LIMIT)
                stage, klass = "rest", CONFIRM
        item.stage, item.klass, item.targets = stage, klass, sorted(set(targets))
        if klass == CONFIRM:
            item.confirm_text = _fill(ACTIONS["nodes.apply"].confirm_text,
                                      {"pending": pending, "adds": adds, "edits": edits})

    def _node_class(self, n, op, snap):
        """§4.3 표 한 칸: AUTO | CONFIRM | "rejected"."""
        state = node_state(n)
        if state in ("confirmed", "locked"):
            return "rejected"
        members_change = op["op"] in ("merge", "split", "remove") or bool(op.get("add") or op.get("remove"))
        if has_cells(snap, n["node_id"]):
            return "rejected" if members_change else CONFIRM
        if n.get("origin") == "ai" and n.get("batch_id") in self.conv_batches and not human_touched(n):
            return AUTO
        return CONFIRM

    @staticmethod
    def _node_reason(n, op, snap):
        state = node_state(n)
        if state == "locked":
            return "잠긴 구간(%s)은 채팅으로 바꾸지 않음. ④에서 사람이 이유를 적고 풀어야 함" % n["node_id"]
        if state == "confirmed":
            return "확정 구간(%s)은 사람이 확정을 해제한 뒤에 바꿀 수 있음" % n["node_id"]
        return "⑤ 칸이 있는 구간(%s)의 구성요소는 채팅으로 바꾸지 않음" % n["node_id"]

    # ---- 승인 표지(§4.6)

    def _fingerprint(self, item, snap):
        nodes = _nodes(snap)
        targets = []
        for t in item.targets:
            n = nodes.get(t.split("/")[0]) if t not in snap.files else None
            entry = {"id": t}
            if n is not None:
                entry.update(rev=n.get("rev"), state=node_state(n), locked=node_state(n) == "locked",
                             batch_id=n.get("batch_id"))
                if "/" in t:
                    entry["cell"] = _digest([c for c in _cells(snap, n["node_id"])
                                             if c.get("deviation_id") == t.split("/")[1]])
            if t in snap.files:
                entry["file"] = dict(snap.files[t])
            if t in snap.registrations:
                entry["registration"] = dict(snap.registrations[t])
            targets.append(entry)
        return {"project_id": snap.project_id, "action": item.action, "args_digest": _digest(item.args),
                "targets": targets, "set_rev": (snap.node_set or {}).get("set_rev"),
                "pending_ai": pending_ai(snap) if item.action == "nodes.apply" else None}

    def _approval(self, item, snap):
        """승인 표지. 재료에 이 planner만 아는 비밀(_secret)을 섞어, 웹 화면이나 모델이 같은 표지를 만들어 낼 수 없다(검토 8)."""
        body = self._fingerprint(item, snap)
        return dict(body, issued_at=self.clock(), action_key=item.key, exec_seq=self.exec_seq,
                    digest=_digest([self._secret, body]))

    def _keep(self, item):
        """판정한 Item을 planner 메모리에 두고 무작위 token을 단다. 실행·확인은 이 메모리의 Item으로만 한다."""
        item.token = "t-" + secrets.token_hex(16)
        self._items[item.token] = copy.deepcopy(item)
        return item

    def _resolve(self, ref):
        """화면이 넘긴 Item이나 token -> planner 메모리의 Item(없으면 None). 넘긴 객체의 args·approval은 믿지 않는다."""
        token = ref if isinstance(ref, str) else getattr(ref, "token", None)
        return self._items.get(token) if isinstance(token, str) else None

    # ---- 실행

    def run(self, ref):
        """바로·후보 동작을 실행한다. 실행 직전에 지금 상태로 다시 검사한다(검토 6).
        -> {"result", "code", "error", "refused", "batch_id", "record"}. result: ok|candidate|rejected|failed|duplicate|
        needs_confirm(그 사이 상태가 바뀌어 확인이 필요해짐: "item"에 새 확인 Item)."""
        item = self._resolve(ref)
        if item is None:
            return _outcome("rejected", "unknown_token", "이 앱이 낸 동작이 아님")
        if item.klass not in (AUTO, CANDIDATE):
            return _outcome("rejected", "not_auto", "바로·후보 동작이 아님")
        with self._lock:
            if self._seen(item):
                return _outcome("duplicate")
            fresh = self._recheck(item, self.read_state())
            if fresh.klass == "rejected":
                return _outcome("rejected", "state_changed", fresh.reason,
                                refused=[{"target": "", "code": "state_changed", "reason": fresh.reason}])
            if fresh.klass == CONFIRM:
                self._items.pop(item.token, None)
                return dict(_outcome("needs_confirm", "state_changed", "그 사이 상태가 바뀌어 확인이 필요함"),
                            item=self._keep(fresh))
            return self._execute(fresh)

    def approve(self, ref, confirmed_by):
        """확인 상자에서 사람이 누름. planner 메모리의 표지를 지금 상태로 다시 만들어 대조하고 같을 때만 실행한다."""
        item = self._resolve(ref)
        if item is None:
            return _outcome("rejected", "unknown_token", "이 앱이 낸 확인이 아님")
        if item.klass != CONFIRM or not item.approval:
            return _outcome("rejected", "not_confirm", "확인 동작이 아님")
        if not isinstance(confirmed_by, str) or not confirmed_by.strip():
            return _outcome("rejected", "no_reviewer", "확인한 사람 이름이 없음")
        with self._lock:
            if self._seen(item):
                return _outcome("duplicate")
            ap = item.approval
            why = None
            if self.closed:
                why = "대화가 끝나 표지를 버림"
            elif self.clock() - ap["issued_at"] > APPROVAL_TTL:
                why = "확인 시간(%d분)이 지남" % (APPROVAL_TTL // 60)
            elif ap["exec_seq"] != self.exec_seq:
                why = "확인 상자를 띄운 뒤 다른 동작이 실행됨"
            elif _digest([self._secret, self._fingerprint(item, self.read_state())]) != ap["digest"]:
                why = "확인한 뒤 대상이 바뀌어 실행하지 않았습니다"
            if why:
                self.done_keys.update(item.keys)
                rec = self._write(item, "stale", error=why, confirmed=True)
                return dict(_outcome("stale", "stale", why), record=rec)
            return self._execute(item, confirmed_by=confirmed_by.strip(), approval_digest=ap["digest"])

    def _recheck(self, item, snap):
        """지금 상태로 다시 판정한 새 Item(token 없음). 거절이면 klass="rejected"."""
        fresh = Item(list(item.keys), list(item.indexes), item.action, copy.deepcopy(item.args), item.why, NEVER,
                     proposals=item.proposals)
        turn = self.requests.get(item.key.split("#")[0], (None, None, None))[2]
        try:
            if fresh.action == "nodes.apply":
                self._check_set(fresh, snap)
                self._classify_ops(fresh, snap, turn)
            else:
                self._check(fresh, snap)
        except _Reject as rej:
            fresh.klass, fresh.reason, fresh.where = "rejected", rej.reason, rej.where
        return fresh

    def reissue(self, ref):
        """같은 답의 다음 확인 동작을 띄울 때(§4.6: 한 번에 하나, 앞 동작이 실행되면 표지를 버림) 지금 상태로 다시 검사하고
        새 token·표지를 단 Item을 돌려준다. 이제 거절할 동작이면 거절을 기록하고 klass="rejected"인 Item을 돌려준다."""
        item = self._resolve(ref)
        if item is None:
            return None
        snap = self.read_state()
        with self._lock:
            if self._seen(item) or self.closed:
                return item
            fresh = self._recheck(item, snap)
            self._items.pop(item.token, None)
            if fresh.klass == "rejected":
                self.done_keys.update(fresh.keys)
                self._write(fresh, "rejected", error=fresh.reason)
                return fresh
            if fresh.klass == CONFIRM:
                fresh.approval = self._approval(fresh, snap)
            return self._keep(fresh)

    def decline(self, ref):
        item = self._resolve(ref)
        if item is None:
            return _outcome("rejected", "unknown_token", "이 앱이 낸 확인이 아님")
        with self._lock:
            if self._seen(item):
                return _outcome("duplicate")
            self.done_keys.update(item.keys)
            return dict(_outcome("declined"), record=self._write(item, "declined", confirmed=True))

    def end_conversation(self):
        """대화가 끝남: 남은 승인 표지를 버린다(§4.6). 실행한 키는 이 객체와 함께 사라진다."""
        with self._lock:
            self.closed = True
            self._items.clear()

    def _seen(self, item):
        return any(k in self.done_keys for k in item.keys)

    def _execute(self, item, confirmed_by=None, approval_digest=None):
        """잠금 안에서 부른다. 실행 함수의 돌려주는 값(EXECUTOR_RESULT)을 검사해 성공일 때만 성공으로 기록한다(검토 1)."""
        if self.closed:
            return _outcome("rejected", "closed", "대화가 끝났음")
        if self._seen(item):
            return _outcome("duplicate")
        self.done_keys.update(item.keys)
        fn = self.executors.get(item.action)
        request_id, request_text, turn = self.requests.get(item.key.split("#")[0], ("", "", None))
        klass = "confirm" if confirmed_by else ("candidate" if item.klass == CANDIDATE else "auto")
        call = Call(self.project_id, request_id, request_text, list(item.keys), klass, confirmed_by, item.stage,
                    item.stage == "rest" and bool(confirmed_by), request_id, self.conversation_id, self.model,
                    action=item.action)
        confirmed = bool(confirmed_by)
        if fn is None:
            msg = "이 앱에 실행 함수가 연결되지 않음"
            return dict(_outcome("failed", "no_executor", msg),
                        record=self._write(item, "failed", error="no_executor: " + msg, confirmed=confirmed,
                                           confirmed_by=confirmed_by, approval_digest=approval_digest))
        try:
            out = fn(copy.deepcopy(item.args), call)
        except Exception as exc:  # 실행 함수가 예외로 끝나도 기록은 남긴다
            msg = "%s: %s" % (type(exc).__name__, str(exc)[:250])
            return dict(_outcome("failed", "exception", msg),
                        record=self._write(item, "failed", error="exception: " + msg, confirmed=confirmed,
                                           confirmed_by=confirmed_by, approval_digest=approval_digest))
        code, msg, refused = check_result(out)
        if code is not None:  # 엔진이 거절했거나 꼴이 틀림: 실행 횟수에 세지 않고, 거절은 rejected·꼴 틀림은 failed
            result = "rejected" if code == "engine_refused" else "failed"
            return dict(_outcome(result, code, msg, refused=refused),
                        record=self._write(item, result, error="%s: %s" % (code, msg), confirmed=confirmed,
                                           confirmed_by=confirmed_by, approval_digest=approval_digest))
        self.exec_seq += 1
        batch = out.get("batch_id")
        if item.action == "nodes.apply" and batch:
            self.conv_batches.add(batch)
            if any(isinstance(o, dict) and o.get("op") in ("add", "split") for o in item.args["ops"]):
                self.last_add_turn = turn
        targets = out.get("node_ids") or out.get("targets") or item.targets
        result = "candidate" if item.klass == CANDIDATE else "ok"
        rec = self._write(item, result, batch_id=batch, targets=targets, confirmed=confirmed, confirmed_by=confirmed_by,
                          approval_digest=approval_digest,
                          undo_of=item.args.get("batch_id_to_undo") if item.action == "nodes.undo" else None)
        return dict(_outcome(result), batch_id=batch, set_rev=out.get("set_rev"), targets=list(targets), record=rec)

    def _write(self, item, result, error=None, batch_id=None, targets=None, confirmed=False, confirmed_by=None,
               approval_digest=None, undo_of=None):
        """action_key마다 한 줄. 기록 실패는 실행을 막지 않는다(결과에 담아 돌려줌).
        confirmed: 확인 상자를 거친 결론(실행·거절·stale). 확인자·표지는 그때만 적는다(actions_log 규칙)."""
        request_id, request_text, _turn = self.requests.get(item.key.split("#")[0], ("", "", None))
        klass = "confirm" if confirmed or confirmed_by else "auto"
        if klass != "confirm":
            confirmed_by = approval_digest = None
        out = []
        for key, prop in zip(item.keys, item.proposals or [{"action": item.action, "args": item.args, "why": item.why}]):
            answer_id, index = key.rsplit("#", 1)
            try:
                rec = self._record(self.project_id, answer_id=answer_id, index=int(index), request_id=request_id or "q-none",
                                   request_text=request_text, proposal=prop, klass=klass, result=result, error=error,
                                   targets=targets if targets is not None else item.targets, batch_id=batch_id,
                                   undo_of=undo_of, confirmed_by=confirmed_by,
                                   confirmed_at=actions_log.now_kst().isoformat() if confirmed_by else None,
                                   approval_digest=approval_digest, conversation_id=self.conversation_id,
                                   model=self.model, via=self.via, app_version=self.app_version)
            except ValueError as exc:
                rec = {"status": "failed", "error": str(exc)}
            out.append(rec)
            self.log.append((key, result, rec))
        return out


# 실행 함수가 돌려줄 값의 꼴(검토 1). node_commands.execute의 돌려주는 값과 같다(node-commands.md §1).
#   {"ok": bool, "refused": [{"target": str, "code": str, "reason": str}], "batch_id": str|None, "node_ids": [str],
#    "set_rev": int|None, "error": str(선택, ok가 false이고 refused가 비었을 때의 실패 사유)}
# ok가 true일 때만 성공이다. ok가 없거나 dict가 아니면 실패(꼴 틀림)로 본다. refused의 code(엔진 거절 코드: stale·conflict·
# rule·bad_actor 등)는 그대로 화면에 넘긴다.
EXECUTOR_RESULT = {"ok": "bool", "refused": "[{target, code, reason}]", "batch_id": "str|None", "node_ids": "[str]",
                   "set_rev": "int|None", "error": "str?"}


def check_result(out):
    """실행 함수의 돌려주는 값 -> (사유 코드 | None, 문구, refused 목록). 코드: engine_refused | engine_failed | bad_result."""
    if not isinstance(out, dict) or not isinstance(out.get("ok"), bool):
        return "bad_result", "실행 함수가 정해진 꼴({ok, refused, …})을 돌려주지 않음", []
    refused = [{"target": str(r.get("target", "")), "code": str(r.get("code") or "rule")[:40],
                "reason": str(r.get("reason", ""))[:300]}
               for r in out.get("refused") or [] if isinstance(r, dict)]
    if out["ok"] is True:
        return None, None, []
    if refused:
        return "engine_refused", "; ".join("%s: %s" % (r["target"], r["reason"]) for r in refused)[:300], refused
    return "engine_failed", str(out.get("error") or "실행 함수가 실패를 알림")[:300], []


def _outcome(result, code=None, error=None, refused=None):
    """run·approve·decline이 화면에 돌려주는 값의 공통 꼴."""
    return {"result": result, "code": code, "error": error, "refused": refused or []}


def _fill(template, values):
    """확인 문구 틀에 앱이 검사한 값만 넣는다. 목록은 쉼표로 잇고, 모델 글(why 등)은 넣지 않는다."""
    safe = {k: (", ".join(map(str, v)) if isinstance(v, list) else v) for k, v in values.items()
            if isinstance(v, (str, int, list)) and k not in ("why",)}
    try:
        return template.format(**safe)
    except (KeyError, IndexError, ValueError):
        return template


CARD_ACTIONS_SCHEMA = {
    "type": "array", "maxItems": MAX_ACTIONS,
    "items": {"type": "object", "additionalProperties": False, "required": ["action", "args"],
              "properties": {"action": {"type": "string", "enum": sorted(n for n, a in ACTIONS.items() if a.klass != NEVER)},
                             "args": {"type": "object"},
                             "why": {"type": "string"}}},
}


# ---------------------------------------------------------------- 구간 엔진 연결(참고 연결부)

_EDIT_COMMANDS = (("name", "rename", "name"), ("design_intent", "set_design_intent", "text"),
                  ("add", "add_members", "members"), ("remove", "remove_members", "members"))


def _unsupported(why):
    return {"ok": False, "refused": [{"target": "ops", "code": "unsupported", "reason": why}], "batch_id": None,
            "node_ids": [], "set_rev": None}


def _ops_to_command(ops):
    """nodes.apply의 ops -> (명령, 인자) 또는 None. 요청 하나가 묶음 하나여야 하므로(node-commands.md §4) 명령 하나로 옮길 수
    있을 때만 옮긴다: 모두 add면 create, 아니면 op 하나에 바꿀 것 하나."""
    if ops and all(o.get("op") == "add" for o in ops):
        keep = ("cand_id", "members", "name", "design_intent", "basis", "params")
        return "create", {"items": [{k: o[k] for k in keep if k in o} for o in ops]}
    if len(ops) != 1:
        return None
    op = ops[0]
    kind = op.get("op")
    if kind == "edit":
        fields = [f for f in _EDIT_COMMANDS if f[0] in op]
        if len(fields) != 1:
            return None
        key, cmd, arg = fields[0]
        return cmd, {"node_id": op.get("node_id"), arg: op[key]}
    if kind == "merge":
        return "merge", {"node_ids": list(op.get("node_ids") or [])}
    if kind == "split":
        return "split", {"node_id": op.get("node_id"), "members": list(op.get("members") or []), "name": op.get("name")}
    if kind == "remove":
        return "remove", {"node_id": op.get("node_id")}   # 보관(archive)은 사람만(엔진이 AI 보관을 막음)
    return None


def node_executors(pg, execute):
    """구간 동작의 실행 함수 표. `execute`는 `hazop.study.node_commands.execute`(시험은 같은 서명의 가짜).

    새 화면 연결부는 이 표를 `ActionPlanner(executors=…)`에 넣거나 같은 방식으로 잇는다. 서명은 `call.engine_kwargs()`가
    정한다(누가 썼나 author, 누가 눌렀나 confirmed_by, request). 섞인 ops(add와 edit, edit 여러 개)는 엔진에 묶음 하나로 받는
    공개 명령이 없어 'unsupported'로 거절한다.
    """
    def apply(args, call):
        found = _ops_to_command(list(args.get("ops") or []))
        if found is None:
            return _unsupported("한 요청에 여러 종류의 구간 변경을 섞을 수 없음. 나눠서 다시 요청")
        cmd, cargs = found
        return execute(pg, cmd, cargs, set_rev=args.get("set_rev"), **call.engine_kwargs())

    def undo(args, call):
        return execute(pg, "undo", {"batch_id": args.get("batch_id_to_undo")}, set_rev=args.get("set_rev"),
                       **call.engine_kwargs())

    def state(cmd):
        return lambda args, call: execute(pg, cmd, {"node_ids": list(args.get("node_ids") or [])}, set_rev=None,
                                          **call.engine_kwargs())

    return {"nodes.apply": apply, "nodes.undo": undo, "nodes.confirm": state("confirm"),
            "nodes.unconfirm": state("unconfirm"), "nodes.lock": state("lock")}
