"""단계 ⑤ 검토 확정 기록 (기획서/인터페이스.md §5, §3.4, §6.2). UI 없이 쓰는 공개 API.

흐름: open_run → (check_editable) → scenario_decision / dic_decision / no_scenario_confirmation / memo_record
→ build_review → validate_review → save_review. 표시값은 merge_display, 집계는 review_summary.
"""

from hazop.review.merge import SOURCE_LABELS, merge_display, value_source_text
from hazop.review.prior import (find_prior_reviews, import_dic_decision, import_no_scenario_confirmation,
                                import_scenario_decision, match_dic, match_scenario, match_status)
from hazop.review.record import (DIC_DECISIONS, SCENARIO_DECISIONS, adopt_ai_proposal, build_review,
                                 check_risk_confirmation, compute_review_status, compute_risk, dic_decision,
                                 make_risk_confirmation, memo_record, no_scenario_confirmation, review_summary,
                                 save_review, scenario_ai_original, scenario_decision, scenario_match_key,
                                 validate_review)
from hazop.review.store import (ReviewError, check_editable, file_sha256, list_versions, load_review,
                                load_run_reviews, open_run, review_dir, utc_now)

__all__ = [
    "ReviewError", "open_run", "check_editable", "file_sha256", "utc_now",
    "review_dir", "list_versions", "load_review", "load_run_reviews", "save_review",
    "SCENARIO_DECISIONS", "DIC_DECISIONS", "scenario_decision", "dic_decision", "no_scenario_confirmation",
    "memo_record", "build_review", "validate_review", "compute_review_status", "review_summary",
    "compute_risk", "make_risk_confirmation", "adopt_ai_proposal", "check_risk_confirmation",
    "scenario_ai_original", "scenario_match_key",
    "find_prior_reviews", "match_scenario", "match_dic", "match_status",
    "import_scenario_decision", "import_dic_decision", "import_no_scenario_confirmation",
    "merge_display", "value_source_text", "SOURCE_LABELS",
]
