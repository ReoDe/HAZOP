"""채팅 읽기 도구 MCP 서버의 개발 환경 입구(규격 docs/specs/chat-panel.md §2.4). 채팅 세션이 CLI 설정에 적어 띄운다.

  <시험용 venv>\\python.exe -E -s scripts/chat_tools_server.py --project <project_id> --question-file <질문 파일>

배포본은 같은 서버를 HAZOP.exe --chat-tools로 띄운다(scripts/run_app.py). Qt를 import하지 않는다.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.chat import mcp_server  # noqa: E402

if __name__ == "__main__":
    sys.exit(mcp_server.main())
