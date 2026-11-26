"""원래 값 표시가 있는 노드를 파일만 읽은 값(옛 글자, 배관은 흐름)(HZ-PLN-22 §6.9.4). 그래프 노드의 read_as 칸만 본다. 칸이 없는 노드는 옛 글자가 없다.
옛 글자가 그래프 안에서 하나여도 같은 글자의 다른 설비일 수 있다. 옛 글자로 찾은 것은 쓰는 쪽이 재확인으로 남긴다."""

PLAIN = "read_as"
FIELDS = ("kind", "tag", "label_text", "flow_direction")
_EDITED = {"set_kind": ("kind",), "set_tag": ("tag", "label_text"), "set_flow": ("flow_direction",)}


def carried(node):
    """추출 노드 -> 그래프 노드에 옮길 칸. 사람이나 자동 확정이 고친 칸은 옛 글자로 보지 않는다."""
    plain = node.get(PLAIN)
    if not plain:
        return {}
    edited = {f for op in (node.get("human_edit") or {}).get("ops") or () for f in _EDITED.get(op, ())}
    left = {k: plain[k] for k in FIELDS if k in plain and k not in edited}
    return {PLAIN: left} if left else {}


def plain_node(node):
    """옛 글자로 본 노드. 옛 글자가 없으면 받은 노드 그대로."""
    return dict(node, **node[PLAIN]) if node.get(PLAIN) else node


def old_tag(node):
    """지금 태그와 다른 옛 태그. 없으면 None."""
    tag = plain_node(node).get("tag")
    return tag if tag and tag != node.get("tag") else None
