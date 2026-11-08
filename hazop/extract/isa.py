"""계기 태그에서 ISA-5.1 식 문자·루프 번호 읽기. 근거: 기획서/지식그래프-스키마-사전.md §2.1 '계기 기능'(measured_variable,
functions, loop_no), 본문 §9 U4(식별 체계는 아직 모름 → 선택 속성만).

문자 규칙은 ISA-5.1 관례를 따른 [일반지식]이다(원문 미확인): 첫 글자 = 측정변수, 둘째 글자가 변수 수식 문자(D 차압·
F 비율·J 스캔·K 변화율·Q 적산)면 첫 글자에 붙고, 나머지 = 기능 문자. 원전 고유 문자를 막지 않도록 글자 값은 검사하지
않는다. 태그 앞 계통 접두(예: RC-)는 따로 둔다. 모양이 맞지 않으면 None(미확인)이고 원래 태그는 바꾸지 않는다.
"""

import re

VARIABLE_MODIFIERS = frozenset("DFJKQ")
BASIS = "ISA-5.1 관례 [일반지식]"
# [계통 접두-]기능 문자 2~5개[- ]루프 번호[접미]. 예: RC-PT101, CV-PIC201, PT-101, FW-FIC503A
_TAG = re.compile(r"(?:(?P<prefix>[A-Z][A-Z0-9]{0,3})-)?(?P<letters>[A-Z]{2,5})[- ]?(?P<loop>\d{1,5})(?P<suffix>[A-Z]?\d?)")


def parse_tag(tag):
    """{"system_prefix", "measured_variable", "variable_modifier", "functions", "loop_no", "suffix", "basis"} 또는 None."""
    if not isinstance(tag, str):
        return None
    m = _TAG.fullmatch(tag.strip().upper())
    if not m:
        return None
    letters = m.group("letters")
    modifier = letters[1] if letters[1] in VARIABLE_MODIFIERS and len(letters) > 2 else None
    functions = letters[2:] if modifier else letters[1:]
    return {"system_prefix": m.group("prefix"), "measured_variable": letters[0], "variable_modifier": modifier,
            "functions": functions, "loop_no": m.group("loop"), "suffix": m.group("suffix") or None, "basis": BASIS}
