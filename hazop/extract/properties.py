"""P&ID 노드 속성 사전 검사(경고만). 근거: 기획서/지식그래프-스키마-사전.md §2.1 클래스별 속성, 부속 2 §3.2.

속성 이름·허용값·클래스별 필수 속성은 타입 레지스트리(hazop/kg/schema/registry.json)의 properties·required에서 읽는다.
결과는 추출 결과의 미확인(validation.unknowns)으로 남기며 차단하지 않는다. 값은 고치지 않고 원문 그대로 둔다.

- missing_<속성>: kind 클래스의 required 속성이 없음(정상 위치·고장 위치)
- invalid_<속성>: enum 허용값에 없는 값, 또는 수량 속성에 숫자가 없음. 사유 문구는 옛 검사와 같게 둔다(사람이 확정한
  미확인은 check·reason이 같아야 다시 추출해도 지워진다)
- unknown_attribute: 속성 사전에 없는 이름(오타 후보)
"""

import re

from hazop.kg.schema import REGISTRY

_DIGIT = re.compile(r"\d")


def node_issues(kind, attributes):
    """[(check, field, reason)] 순서: 필수 누락 → 허용값 → 모르는 이름. kind가 레지스트리에 없으면 필수 검사는 하지 않는다."""
    attrs = attributes or {}
    out = []
    cid = REGISTRY.kind_class.get(kind)
    if cid is not None:
        cat = REGISTRY.label(REGISTRY.classes[cid]["parent"])
        for prop in REGISTRY.class_required(cid):
            if not attrs.get(prop):
                out.append(("missing_" + prop, prop, "%s %s 미확인" % (cat, REGISTRY.properties[prop]["label_ko"])))
    for name, value in attrs.items():
        spec = REGISTRY.properties.get(name)
        if spec is None or value in (None, ""):
            continue
        if spec["type"] == "enum" and value not in spec["values"]:
            out.append(("invalid_" + name, name, "규칙에 없는 값 %r" % value))
        elif spec["type"] == "quantity" and not _DIGIT.search(str(value)):
            out.append(("invalid_" + name, name, "숫자가 없는 값 %r" % value))
    for name in attrs:
        if name not in REGISTRY.properties:
            out.append(("unknown_attribute", name, "속성 사전에 없는 이름 %r (값은 보존)" % name))
    return out
