"""앱의 채팅 도구 목록(MCP 서버에 여는 도구). 규격: docs/specs/chat-panel.md §3.1.

그래프 도구(`hazop.chat.tools`)로 시작한다. 문서·결과 도구(C3)와 구간 도구(N3 `hazop.study.node_tools`)는
각 단위가 자기 파일에서 이 표에 줄을 더한다. 항목은 {name, fn, description, input_schema, tier, returns}다.
`returns`는 도구가 돌려주는 ID 종류(component·node·cell·chunk·path_ref)다.
"""

from hazop.chat import tools

REGISTRY = dict(tools.REGISTRY)

# 채팅 시스템 프롬프트에 넣을 '구간 만들기 절차'. 도구 설명(find_major_equipment·make_candidates)에도 같은 글이 들어 있다.
NODE_CREATION_PROCEDURE = tools.NODE_PROCEDURE
