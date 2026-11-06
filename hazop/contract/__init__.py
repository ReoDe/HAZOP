"""단계 연쇄 검사 (기획서/단계연쇄검사.md). 저장된 ①~⑤ 결과 파일 사이의 ID·버전·해시·상태 연속성만 읽기 전용으로 본다."""

from .chain import (CHECK_IDS, CHECK_VERSION, LEVELS, ContractError, check, counts, exit_code,  # noqa: F401
                    format_line, render_console, report_doc, summary_line, write_report)
