"""스크립트 콘솔 출력 안전 처리.

Windows 기본 콘솔(cp949 등)에서 표현할 수 없는 문자(예: '—' U+2014)를 print하면 UnicodeEncodeError로
스크립트가 죽는다. 모든 scripts/*.py의 main() 첫 줄에서 safe_console()을 호출해, 인코딩은 그대로 두고
표현 불가 문자만 대체 문자로 바꿔 출력한다(한글은 cp949로 정상 출력).
"""

import sys


def safe_console():
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):  # 닫혔거나 재설정할 수 없는 스트림은 그대로 둔다
                pass
