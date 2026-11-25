"""원래 값 표시가 종류·태그·글자를 바꾼 노드의 옛 글자(HZ-PLN-22 §6.9.4). 그래프 노드의 read_as 칸만 본다. 칸이 없는 노드는 옛 글자가 없다."""

PLAIN = "read_as"
FIELDS = ("kind", "tag", "label_text")
_EDITED = {"set_kind": ("kind",), "set_tag": ("tag", "label_text")}


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
