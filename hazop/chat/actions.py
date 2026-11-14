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
import logging
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
LATER = "later"              # 아직 화면이 없어 채팅으로 할 수 없는 동작(A11 2차에 잇는다). 거절하되 '아직'이라고 분명히 답한다
CLASS_NAMES = {DISPLAY: "표시", AUTO: "바로", CANDIDATE: "후보", CONFIRM: "확인", NEVER: "안 함", LATER: "아직"}
NOT_YET = "아직 채팅으로 할 수 없는 동작입니다(화면이 생기면 잇습니다)"
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
    results_fp: str = None       # ⑤ 결과 파일 지문(hazop.study.results.load_fp의 둘째 값). 결과 판정의 낡은 판 대조에 쓴다
    # 도면 쪽: graph_id -> {"state": open|ready|confirmed, "fingerprint", "rev", "reason"}(hazop.extract.confirmation.sheet_confirmation)
    sheets: dict = field(default_factory=dict)


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
           "구간 {node_ids}을 AI로 분석합니다. 쓸 연결과 비용은 아래 줄에 있습니다. 사람이 쓴 항목은 바꾸지 않습니다."),
    # 결과 판정(수용·수정·기각·보류)은 사람 판단이라 늘 확인(UC1). 인자는 result_commands와 같다(results-commands.md §4).
    # 사유(reason)는 모델 글이라 확인 문구에 넣지 않는다. 화면은 사유를 'AI가 제안한 사유' 원문으로 따로 보인다
    Action("results.set_status", CONFIRM,
           _spec(("node_id", "id"), ("deviation_id", "id"), ("entry_id", "id"), ("status", "str"), reason="str"), "⑤",
           "사람 판단. 수정·기각·보류는 사유 필수. 잠긴 구간의 칸은 거절",
           "구간 {node_id} 편차 {deviation_id}의 항목 {entry_id}을 {status_label}(으)로 판정합니다. "
           "아래 판정과 사유는 AI가 쓴 글이며, 확인한 사람 이름과 함께 그대로 저장됩니다."),
    Action("results.edit", CONFIRM,
           _spec(("node_id", "id"), ("deviation_id", "id"), ("entry_id", "id"), ("fields", "obj"), ("reason", "str")),
           "⑤", "사람 판단(판정 '수정'). 사유 필수. 잠긴 구간의 칸은 거절",
           "구간 {node_id} 편차 {deviation_id}의 항목 {entry_id} 내용을 고칩니다({field_names}). 판정은 '수정'이 되고 "
           "아래 새 값과 사유는 AI가 쓴 글이며, 확인한 사람 이름과 함께 그대로 저장됩니다."),
    Action("export.excel", AUTO, _spec(scope="str", node_ids="ids"), "⑤",
           "이름에 시각을 붙인 새 파일. 범위 scope: all(전체)·approved(승인 항목만)·nodes(고른 구간만, node_ids 필요)"),
    Action("export.ie_bundle", AUTO, _spec(), "⑤", "이름에 시각을 붙인 새 파일"),
    # ② 도면 쪽 확정과 DEXPI 내보내기(sheet-commands.md·dexpi-commands.md). 확정은 사람 판단이라 늘 확인. '원본과 견줌'은 화면에서 사람이 본다
    Action("sheet.confirm", CONFIRM, _spec(("graph_id", "id")), "②", "미확인 0·위치 없음 0·원본과 견줌을 마친 쪽만(엔진이 센다)",
           "도면 {graph_id}을(를) 확정합니다. 확정자로 검토자 이름이 남고, 이 쪽은 DEXPI로 내보낼 수 있게 됩니다."),
    Action("sheet.compare", NEVER, _spec(), "②", "원본과 견줌", where="도면 화면에서 원본과 겹쳐 보고 사람이 누른다"),
    Action("dexpi.export", AUTO, _spec(("graph_ids", "ids")), "②", "확정된 쪽만. 시각을 붙인 새 폴더에 써서 덮어쓰지 않는다"),
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
    # A11 2차: 새 화면 영역(지식그래프 A6·AI 검토 후보 A4·원본 선택)의 실행 함수를 잇는 동작. 사람 판단을 저장하므로 확인을 받고,
    # 화면이 하는 대조(잠재 후보는 항목 digest·상태·판, AI 후보는 후보 ID와 판)를 확인 상자에서 본 값 그대로 넘긴다(hazop/shell/chat_screens.py)
    Action("kg.find", DISPLAY, _spec(("text", "str")), "③", "지식그래프 패널을 열고 태그·이름·규칙 ID로 찾은 노드를 고른다"),
    Action("kg.judge", CONFIRM, _spec(("id", "str"), ("judgement", "str"), reason="text", evidence="str"), "③",
           "잠재 후보 판단: confirm(후보 확인)·reject(후보 기각)·absent(부재 확정)·not_applicable(무관)·undo(판단 되돌리기)",
           "잠재 후보 {id}을(를) 판단합니다. 아래 사유·근거는 AI가 쓴 글이며, 확인한 사람 이름이 판단한 사람으로 남습니다."),
    Action("aireview.accept", CONFIRM, _spec(("graph_id", "id"), ("cand_ids", "ids")), "②",
           "AI 후보 수락: 사람 수정 기록에 연산으로 들어가고 그래프를 다시 만든다. 되돌릴 수 있다",
           "도면 {graph_id}의 AI 후보 {cand_ids}을(를) 수락합니다. 아래 값이 도면 수정 기록에 들어가고 그래프를 다시 만듭니다."),
    Action("aireview.reject", CONFIRM, _spec(("graph_id", "id"), ("cand_ids", "ids")), "②", "AI 후보 거절",
           "도면 {graph_id}의 AI 후보 {cand_ids}을(를) 거절합니다."),
    Action("aireview.revert", CONFIRM, _spec(("graph_id", "id"), ("cand_ids", "ids")), "②",
           "수락·거절 되돌리기(수락한 연산은 수정 기록에서 빠지고 그래프를 다시 만든다)",
           "도면 {graph_id}의 AI 후보 {cand_ids}의 수락·거절을 되돌립니다."),
    Action("aireview.accept_bulk", CONFIRM, _spec(("graph_id", "id"), ("task", "str")), "②",
           "확신 높은 묶음 수락. 확인 상자에 보인 후보 ID만 수락한다",
           "도면 {graph_id}의 확신 높은 AI 후보 묶음을 한 번에 수락합니다. 아래 후보만 수락합니다."),
    Action("sources.choose", CONFIRM, _spec(("drawing_number", "str"), ("format", "str")), "②",
           "같은 도면 번호의 원본이 형식 둘 이상일 때 프로젝트 그래프에 쓸 형식을 고른다(사람 수정·추출 결과는 그대로)",
           "도면 {drawing_number}에 {format} 원본을 쓰도록 고릅니다. 프로젝트 그래프가 그 원본으로 다시 만들어집니다."),
    # ⑥ 초기사건 편집(A10, api_ie). 확인 상자에서 본 ⑥ 파일 지문·⑤ 지문·항목 지문을 그대로 넘긴다. 확정 그룹을 초안으로 내리는 변경은 ⑥ 패널에서
    Action("ie.move", CONFIRM, _spec(("iecs", "ids"), to="id"), "⑥", "후보를 다른 그룹으로 옮기기(to가 없으면 그룹에서 뺌)",
           "초기사건 후보 {iecs}을(를) 옮깁니다."),
    Action("ie.split", CONFIRM, _spec(("group_id", "id"), ("moved", "ids")), "⑥", "그룹 나누기(고른 후보를 새 그룹으로)",
           "초기사건 그룹 {group_id}에서 후보 {moved}을(를) 새 그룹으로 나눕니다."),
    Action("ie.edit_group", CONFIRM, _spec(("group_id", "id"), ("fields", "obj")), "⑥", "그룹 이름·정의·범주·대표 등 고치기",
           "초기사건 그룹 {group_id}을(를) 고칩니다. 아래 새 값은 AI가 쓴 글입니다."),
    Action("ie.accept_members", CONFIRM, _spec(("iecs", "ids")), "⑥", "규칙이 배정한 소속을 사람이 확인",
           "초기사건 후보 {iecs}의 소속을 확인합니다."),
    Action("ie.confirm_group", CONFIRM, _spec(("group_id", "id")), "⑥", "그룹 확정(확정자는 확인한 사람)",
           "초기사건 그룹 {group_id}을(를) 확정합니다. 확정자로 확인한 사람 이름이 남습니다."),
    Action("ie.reopen_group", CONFIRM, _spec(("group_id", "id")), "⑥", "그룹 확정 풀기", "초기사건 그룹 {group_id}의 확정을 풉니다."),
    Action("ie.set_coverage", CONFIRM, _spec(("code", "str"), disposition="str", reason="text"), "⑥",
           "완전성 대조 빈 범주 판정: out_of_scope·other_method·not_applicable(사유 필수), 빈 글자면 지움",
           "완전성 대조 범주 {code}을(를) 판정합니다. 아래 사유는 AI가 쓴 글입니다."),
    Action("ie.export", AUTO, _spec(), "⑥", "인계 묶음 Excel+JSON. 시각을 붙인 새 이름으로 쓰고 덮어쓰지 않는다"),
    # 설계 문서(A7, api_docs)
    Action("docs.extract", CONFIRM, _spec(("material_id", "id")), "③", "등록한 설계 문서의 지식 추출 다시 하기(뽑힌 항목을 새로 씀)",
           "설계 문서 {material_id}의 지식 추출을 다시 합니다."),
    Action("docs.add", NEVER, _spec(), "③", "설계 문서 등록(파일 고르기)", where="설계 문서 패널의 '추가'에서 사람이 파일을 고른다"),
    Action("docs.revision", CONFIRM, _spec(("material_id", "id"), ("answer", "str"), old="id"), "③",
           "같은 문서의 새 판인지 묻는 물음에 답한다: replace(old를 이 문서가 대신)·separate(다른 문서)",
           "설계 문서 {material_id}의 판 대응을 정합니다."),
    # 표제란(A3, api_titleblock). 확인 상자에서 본 등록정보 판(ver)을 넘긴다. 확정하면 추출한 쪽을 다시 추출한다(작업)
    Action("titleblock.confirm", CONFIRM, _spec(("fields", "obj"), material_id="id", graph_id="id", reason="text"), "②",
           "도면 번호(drawing_number)·개정(design_revision)·제목(title)을 사람이 확정(후보 그대로 또는 고친 값). 이미 추출한 쪽은 다시 추출",
           "표제란 값을 확정합니다. 확정한 사람으로 확인한 사람 이름이 남습니다."),
    Action("titleblock.unconfirm", CONFIRM, _spec(material_id="id", graph_id="id", fields="list", reason="text"), "②",
           "표제란 확정 취소(fields가 없으면 세 항목 모두). 이미 추출한 쪽은 다시 추출", "표제란 확정을 취소합니다."),
    # 도면 고치기(A5, api_corrections). 세 파일 판(ver)·항목 지문(base)·엔진이 물을 확인 글을 상자에서 본 그대로 넘긴다
    Action("drawing.edit", CONFIRM, _spec(("op", "str"), id="id", graph_id="id", local_id="id", value="obj"), "②",
           "도면 고침 하나(set_tag·set_kind·set_normal_position·set_fail_position·set_flow·set_endpoint·clear_endpoint·set_path·confirm·"
           "add_node·delete_node·add_relation·delete_relation). 대상은 구성요소 id 또는 graph_id+local_id. 되돌리기로 뺄 수 있다",
           "도면 고침을 저장합니다."),
    Action("drawing.undo", CONFIRM, _spec(("graph_id", "id"), op_id="id"), "②",
           "도면 고침 하나 빼기(op_id가 없으면 되돌릴 수 있는 마지막 고침). AI 검토에서 수락한 고침은 aireview.revert",
           "도면 {graph_id}의 고침을 되돌립니다."),
    Action("drawing.redo", CONFIRM, _spec(("graph_id", "id")), "②", "마지막으로 되돌린 도면 고침을 원래 자리에 되살리기",
           "도면 {graph_id}의 되돌린 고침을 다시 합니다."),
    # 초기사건 P5(api_ie): FMEA 파일 지문(fver)·MLD 파일 지문(mver)과 행·가지 지문을 넘긴다. MLD 가지 판정은 ie.set_coverage code 'MLD:<가지>'
    Action("ie.fmea_status", CONFIRM, _spec(("row_ids", "ids"), ("status", "str")), "⑥",
           "FMEA 행 승인(approved)·제외(excluded)·가져옴으로 되돌리기(imported)", "FMEA 행 {row_ids}을(를) {status}(으)로 바꿉니다."),
    Action("ie.fmea_mark", CONFIRM, _spec(("node_id", "id"), mark="str"), "⑥", "전기·제어 구간 사람 표시(include·exclude, 빈 글자면 지움)",
           "구간 {node_id}의 전기·제어 표시를 바꿉니다."),
    Action("ie.mld_link", CONFIRM, _spec(("branch_id", "id"), group_ids="ids"), "⑥", "MLD 잎 가지에 초기사건 그룹 잇기(없으면 지움)",
           "MLD 가지 {branch_id}에 초기사건 그룹을 잇습니다."),
    # 도면 연결 짝(B1, api_links). 상자가 본 판(ver)·연결점 지문(base)·엔진이 물을 확인 글(confirm)을 넘긴다
    Action("links.pair", CONFIRM, _spec(id="id", graph_id="id", local_id="id", peer_id="id", peer_graph_id="id", peer_local_id="id",
                                        reason="text"), "②",
           "도면 연결(오각형) 하나와 다른 도면의 연결점을 짝으로 지정(id 또는 graph_id+local_id, 맞은편은 peer_)",
           "도면 연결점의 짝을 지정합니다."),
    Action("links.unlink", CONFIRM, _spec(id="id", graph_id="id", local_id="id", reason="text"), "②",
           "도면 연결점을 '연결하지 않음'으로 지정(자동 짝도 끊음)", "도면 연결점의 연결을 끊습니다."),
    Action("links.clear", CONFIRM, _spec(id="id", graph_id="id", local_id="id", op_id="id"), "②",
           "사람이 한 연결 지정 하나 빼기(op_id가 없으면 이 연결점의 지정). 자동 판정으로 돌아감", "도면 연결 지정을 뺍니다."),
    Action("ie.fmea_import", NEVER, _spec(), "⑥", "FMEA 양식 가져오기·내보내기(파일 고르기)", where="⑥ 초기사건 패널의 FMEA에서 사람이 파일을 고른다"),
    Action("ie.mld_import", NEVER, _spec(), "⑥", "주논리도(MLD) 가져오기(파일 고르기)", where="⑥ 초기사건 패널의 MLD에서 사람이 파일을 고른다"),
    # 아직 화면이 없는 기능. 모델이 내면 '아직 채팅으로 할 수 없음'으로 답한다
    Action("settings.connection", LATER, _spec(), "공통", "AI 연결 방식·도면 연결 설정(A8)", where="연결·설정 화면이 생기면 잇는다"),
)}

# 사람이 정하는 판정(results-commands.md §1). proposed(AI 초안)는 사람이 정할 수 없는 값이라 받지 않는다
RESULT_STATUSES = ("approved", "revised", "rejected", "on_hold")
STATUS_LABELS = {"approved": "수용", "revised": "수정", "rejected": "기각", "on_hold": "보류"}
REASON_REQUIRED = ("revised", "rejected", "on_hold")
EXCEL_SCOPES = ("all", "approved", "nodes")     # api_results results.export_excel의 범위(0f6a554)
# results.edit로 고칠 수 있는 필드(hazop.study.results.EDITABLE_FIELDS와 같음. 시험이 대조)
EDIT_FIELDS = ("cause", "consequence", "safeguards", "recommendation", "severity", "frequency",
               "cause_refs", "consequence_refs", "expectation_refs", "cause_kind", "consequence_basis")
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
    basis: dict = None           # 결과 판정: 계획 때 읽은 {set_rev, node_rev, fingerprint}. 엔진이 실행 직전에 대조한다
    # 확인 상자에 보일 '저장될 값'(앱이 지금 상태에서 만든 줄 [{label, before?, after}]). 승인 표지에 들어가 실행 직전에 다시 대조한다
    details: list = field(default_factory=list)

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
    basis: dict = None           # 결과 판정: 사람이 확인 상자에서 본 판 {set_rev, node_rev, fingerprint}(Item.basis)

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
                 via="subscription", app_version=None, clock=time.time, not_yet=None, extra_checks=None, detail_fns=None):
        self.project_id = project_id
        self.read_state = read_state
        self.executors = dict(executors or {})
        # 동작 표에는 있으나 이 화면에 아직 잇지 않은 동작 -> 사람이 할 곳. 판정 때 '아직'으로 거절한다(실행 함수 없음으로 실패시키지 않는다)
        self.not_yet = dict(not_yet or {})
        # 화면 연결부가 더하는 검사 {동작: fn(item, snap) -> 거절 사유 또는 None}와 확인 상자 줄 {동작: fn(item, snap) -> [줄]}
        self.extra_checks = dict(extra_checks or {})
        self.detail_fns = dict(DETAIL_FNS, **(detail_fns or {}))
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
        if action.klass == LATER:
            raise _Reject(NOT_YET, action.where)
        if action.name in self.not_yet:
            raise _Reject(NOT_YET, self.not_yet[action.name] or action.where or None)
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
        extra = self.extra_checks.get(item.action)
        if extra is not None:
            why = extra(item, snap)
            if why:
                raise _Reject(why)
        item.details = self._details(item, snap)
        broken = [r for r in item.details if isinstance(r, dict) and r.get("label") == "오류"]
        if item.klass == CONFIRM and broken:      # 저장될 값을 다 보이지 못하면 확인 상자를 띄우지 않는다(승인할 수 없게)
            raise _Reject("확인 상자에 저장될 값을 보일 수 없어 실행하지 않습니다(%s)" % str(broken[0].get("after") or "")[:200])

    def _details(self, item, snap):
        """확인 상자에 보일 저장될 값. 계획 때와 승인 직전에 같은 함수로 지금 상태에서 다시 만든다(글자 하나라도 다르면 표지가 어긋남)."""
        fn = self.detail_fns.get(item.action)
        if fn is None:
            return []
        try:
            return list(fn(item, snap) or [])
        except Exception:  # noqa: BLE001 - 줄을 못 만들면 '오류' 줄: 계획 때는 거절, 승인 때는 표지가 어긋나 실행하지 않는다
            logging.getLogger("hazop.chat.actions").exception("확인 상자 줄을 만들지 못함: %s", item.action)
            return [{"label": "오류", "after": "저장될 값을 읽지 못함"}]

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

    def _check_export_excel(self, item, snap):
        scope = item.args.get("scope") or "all"
        ids = item.args.get("node_ids") or []
        if scope not in EXCEL_SCOPES:
            raise _Reject("내보내기 범위는 %s 가운데 하나" % ", ".join(EXCEL_SCOPES))
        if scope == "nodes" and not ids:
            raise _Reject("'고른 구간만'에는 구간 ID(node_ids)가 있어야 함")
        if scope != "nodes" and ids:
            raise _Reject("구간 ID는 범위 nodes(고른 구간만)에서만 씀")
        missing = [i for i in ids if i not in _nodes(snap)]
        if missing:
            raise _Reject("없는 구간: %s" % ", ".join(missing[:5]))
        item.targets = list(ids)

    def _check_kg_rebuild(self, item, snap):
        item.targets = ["kg"]

    def _check_ie_draft_rules(self, item, snap):
        if snap.ie_draft_by_human:
            item.klass = CONFIRM
            item.targets = ["ie"]

    def _check_ie_reset(self, item, snap):
        item.targets = ["ie"]

    def _check_sheet_confirm(self, item, snap):
        gid = item.args["graph_id"]
        sheet = snap.sheets.get(gid)
        if sheet is None:
            raise _Reject("지금 프로젝트에 없는 도면")
        if sheet.get("state") == "confirmed":
            raise _Reject("이미 확정한 쪽")
        if sheet.get("state") != "ready":
            raise _Reject("아직 확정할 수 없는 쪽(%s)" % (sheet.get("reason") or "미확인이 남았거나 원본과 견주지 않음"),
                          "도면 화면에서 미확인을 끝내고 원본과 견준 뒤 다시 요청")
        item.targets = [gid]
        item.basis = {"fingerprint": sheet.get("fingerprint"), "rev": sheet.get("rev") or 0}

    def _check_dexpi_export(self, item, snap):
        ids = item.args["graph_ids"]
        missing = [g for g in ids if g not in snap.sheets]
        if missing:
            raise _Reject("지금 프로젝트에 없는 도면: %s" % ", ".join(missing[:5]))
        if not any(snap.sheets[g].get("state") == "confirmed" for g in ids):
            raise _Reject("확정된 쪽이 하나도 없어 내보낼 것이 없음", "도면에서 '쪽 확정'을 마친 쪽만 내보낸다")
        item.targets = list(ids)

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

    def _entry(self, item, snap):
        a = item.args
        n = _nodes(snap).get(a["node_id"])
        if n is None:
            raise _Reject("없는 구간의 칸")
        if node_state(n) == "locked":
            raise _Reject("잠긴 구간의 칸은 바꾸지 않음(④에서 사람이 이유를 적고 풀어야 함)")
        cell = next((c for c in _cells(snap, a["node_id"]) if c.get("deviation_id") == a["deviation_id"]), None)
        if cell is None:
            raise _Reject("없는 칸")
        if not any(e.get("entry_id") == a["entry_id"] for e in cell.get("entries") or []):
            raise _Reject("없는 항목")
        item.targets = ["%s/%s/%s" % (a["node_id"], a["deviation_id"], a["entry_id"])]
        item.basis = {"set_rev": (snap.node_set or {}).get("set_rev"), "node_rev": n.get("rev"),
                      "fingerprint": snap.results_fp}

    @staticmethod
    def _reason(item, required):
        reason = (item.args.get("reason") or "").strip()
        if required and not reason:
            raise _Reject("수정·기각·보류에는 사유가 있어야 함")
        if "reason" in item.args:
            item.args["reason"] = reason

    def _check_results_set_status(self, item, snap):
        status = item.args["status"]
        if status not in RESULT_STATUSES:
            raise _Reject("판정은 %s 중 하나" % ", ".join(RESULT_STATUSES))
        self._reason(item, status in REASON_REQUIRED)
        self._entry(item, snap)
        item.confirm_text = _fill(ACTIONS["results.set_status"].confirm_text,
                                  dict(item.args, status_label=STATUS_LABELS[status]))

    def _check_results_edit(self, item, snap):
        fields = item.args["fields"]
        bad = sorted(k for k in fields if k not in EDIT_FIELDS)
        if not fields or bad:
            raise _Reject("고칠 수 없는 필드: %s" % ", ".join(bad) if bad else "고칠 필드가 없음")
        self._reason(item, True)
        self._entry(item, snap)
        item.confirm_text = _fill(ACTIONS["results.edit"].confirm_text,
                                  dict(item.args, field_names=[FIELD_LABELS.get(k, k) for k in sorted(fields)]))

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
            if t in snap.sheets:
                entry["sheet"] = {k: snap.sheets[t].get(k) for k in ("state", "fingerprint", "rev")}
            targets.append(entry)
        return {"project_id": snap.project_id, "action": item.action, "args_digest": _digest(item.args),
                "targets": targets, "set_rev": (snap.node_set or {}).get("set_rev"),
                "pending_ai": pending_ai(snap) if item.action == "nodes.apply" else None,
                "results_fp": snap.results_fp if item.action.startswith("results.") else None,
                "details": _digest(self._details(item, snap))}

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
                    action=item.action, basis=copy.deepcopy(item.basis))
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
        return dict(_outcome(result), batch_id=batch, set_rev=out.get("set_rev"), targets=list(targets), record=rec,
                    message=str(out.get("message") or "")[:300] or None, topics=_topics(out))

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
                                   request_text=request_text, proposal=prop, klass=klass, result=result, error=actions_log.strip_paths(error),
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


# ---------------------------------------------------------------- 확인 상자 줄(저장될 값)

FIELD_LABELS = {"cause": "원인", "consequence": "결과", "safeguards": "보호수단", "recommendation": "권고", "severity": "심각도",
                "frequency": "빈도", "cause_refs": "원인 근거", "consequence_refs": "결과 근거", "expectation_refs": "기대 근거",
                "cause_kind": "원인 종류", "consequence_basis": "결과 근거 종류"}


def show_value(v):
    """저장될 값을 글자 그대로(자르지 않는다). 없으면 '(비어 있음)'."""
    if v is None or v == "" or v == []:
        return "(비어 있음)"
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _status_label(status):
    """판정 이름(사람 판정은 STATUS_LABELS, AI 초안은 'AI 초안')."""
    return STATUS_LABELS.get(status) or {"proposed": "AI 초안", None: "(없음)"}.get(status, status)


def _entry_now(snap, a):
    cell = next((c for c in _cells(snap, a.get("node_id")) if c.get("deviation_id") == a.get("deviation_id")), None)
    return next((e for e in (cell or {}).get("entries") or [] if e.get("entry_id") == a.get("entry_id")), None)


def _status_details(item, snap):
    a = item.args
    e = _entry_now(snap, a) or {}
    old = e.get("status")
    return [{"label": "판정", "before": _status_label(old), "after": STATUS_LABELS.get(a["status"], a["status"])},
            {"label": "사유(AI가 씀)", "after": show_value(a.get("reason"))},
            {"label": "항목 원인", "after": show_value(e.get("cause"))}]


def _edit_details(item, snap):
    a = item.args
    e = _entry_now(snap, a) or {}
    rows = [{"label": "%s(AI가 씀)" % FIELD_LABELS.get(k, k), "before": show_value(e.get(k)), "after": show_value(v)}
            for k, v in sorted(a["fields"].items())]
    old = e.get("status")
    rows.append({"label": "판정", "before": _status_label(old),
                 "after": STATUS_LABELS["on_hold"] if old == "on_hold" else STATUS_LABELS["revised"]})
    rows.append({"label": "사유(AI가 씀)", "after": show_value(a.get("reason"))})
    return rows


DETAIL_FNS = {"results.set_status": _status_details, "results.edit": _edit_details}


# 실행 함수가 돌려줄 값의 꼴(검토 1). node_commands.execute의 돌려주는 값과 같다(node-commands.md §1).
#   {"ok": bool, "refused": [{"target": str, "code": str, "reason": str}], "batch_id": str|None, "node_ids": [str],
#    "set_rev": int|None, "error": str(선택, ok가 false이고 refused가 비었을 때의 실패 사유)}
# ok가 true일 때만 성공이다. ok가 없거나 dict가 아니면 실패(꼴 틀림)로 본다. refused의 code(엔진 거절 코드: stale·conflict·
# rule·bad_actor 등)는 그대로 화면에 넘긴다.
EXECUTOR_RESULT = {"ok": "bool", "refused": "[{target, code, reason}]", "batch_id": "str|None", "node_ids": "[str]",
                   "set_rev": "int|None", "error": "str?", "message": "str?(성공 글, 앱이 만든 것)",
                   "topics": "[str]?(바뀐 자료 이름: nodes·results·drawings 등)"}


def _topics(out):
    """실행 함수가 알린 '바뀐 자료 이름' 목록(글만). 없거나 꼴이 다르면 빈 목록."""
    t = out.get("topics")
    return [x for x in t if isinstance(x, str)][:10] if isinstance(t, list) else []


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
# 구조화 출력(모든 객체 additionalProperties false·required 전부)에 맞춘 꼴: 인자는 JSON 글(args_json)로 받아 앱이 푼다(hazop.chat.card).
CARD_ACTIONS_MODEL_SCHEMA = {
    "type": "array",
    "items": {"type": "object", "additionalProperties": False, "required": ["action", "args_json", "why"],
              "properties": {"action": {"type": "string", "enum": sorted(n for n, a in ACTIONS.items() if a.klass != NEVER)},
                             "args_json": {"type": "string"},
                             "why": {"type": "string"}}},
}


def signature_text(names=None):
    """모델 안내에 넣는 동작 서명: 'nodes.confirm(node_ids: ids)'를 '; '로 이음. names가 없으면 안 함·아직을 뺀 모든 동작."""
    out = []
    for a in ACTIONS.values():
        if (names is None and a.klass in (NEVER, LATER)) or (names is not None and a.name not in names):
            continue
        args = ", ".join("%s%s: %s" % (k, "" if req else "?", kind) for k, (kind, req) in a.args.items())
        out.append("%s(%s)" % (a.name, args))
    return "; ".join(out)


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


def result_executors(pg, execute):
    """결과 판정 동작의 실행 함수 표. `execute`는 `hazop.study.result_commands.execute`(서명 results-commands.md §3).

    검토자는 확인 상자를 누른 사람(call.confirmed_by)이다. 계획 때 읽은 판(call.basis: set_rev·node_rev·결과 파일 지문)을
    그대로 넘겨, 확인 상자를 띄운 뒤 다른 창이 칸·구간을 바꿨으면 엔진이 stale로 거절한다.
    """
    def run(cmd):
        def fn(args, call):
            basis = call.basis or {}
            cargs = dict(args, author="ai")     # 글은 AI가 썼고 by(누른 사람)는 확인한 사람이다(results 기록의 author·by)
            if basis.get("node_rev") is not None:
                cargs["node_rev"] = basis["node_rev"]
            return execute(pg, cmd, cargs, call.confirmed_by, basis.get("fingerprint"), set_rev=basis.get("set_rev"))
        return fn

    return {"results.set_status": run("set_status"), "results.edit": run("edit_entry")}
