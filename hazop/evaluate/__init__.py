"""평가 기준 비교 (기획서/평가기준비교.md). UI 없이 쓰는 공개 API. AI를 쓰지 않으며 결정적이다.

흐름: load_criteria(어댑터) → build_view(분석 실행+검토 저장소 → 비교 입력 뷰) → build_report(검사·대응·지표)
→ write_report(JSON·Excel, 덮어쓰지 않음). 한 번에: run_compare.
"""

from hazop.evaluate.criteria import CriteriaError, validate_criteria
from hazop.evaluate.match import match
from hazop.evaluate.report import (COMPARE_VERSION, SYNTHETIC_NOTICE, CompareError, build_report, comparison_id,
                                   dumps, load_criteria, run_compare, write_report)
from hazop.evaluate.view import BASES, build_view

__all__ = ["CriteriaError", "CompareError", "validate_criteria", "match", "build_view", "build_report",
           "comparison_id", "dumps", "load_criteria", "run_compare", "write_report", "BASES",
           "COMPARE_VERSION", "SYNTHETIC_NOTICE"]
