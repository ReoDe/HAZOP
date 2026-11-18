"""구독 Claude Code CLI에 그림과 글을 함께 보내는 클라이언트(hazop/study/claude_cli.ClaudeCliClient 확장).

앱의 클라이언트는 글만 표준 입력으로 보낸다. 여기서는 --input-format stream-json으로 사용자 메시지 한 줄에
PNG(base64)와 글을 함께 넣는다. 인증 확인(구독인지), 한도 기록, 결과 해석은 앱 클라이언트 것을 그대로 쓴다.
"""

import base64
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from hazop.study.claude_cli import ClaudeCliClient  # noqa: E402


class VisionClient(ClaudeCliClient):
    def command(self, request, system_file):
        argv = super().command(request, system_file)
        return argv[:1] + ["--input-format", "stream-json"] + argv[1:]

    def ask(self, system, text, pngs, schema):
        """pngs: PNG 파일 경로 목록. → (결과 dict, 걸린 초)."""
        content = []
        for p in pngs:
            with open(p, "rb") as fh:
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                            "data": base64.b64encode(fh.read()).decode("ascii")}})
        content.append({"type": "text", "text": text})
        line = json.dumps({"type": "user", "message": {"role": "user", "content": content}}, ensure_ascii=False)
        t0 = time.time()
        res = self.analyze({"system": system, "context": line, "user": "", "schema": schema})
        return res, time.time() - t0
