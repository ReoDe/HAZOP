"""평가 기준 변환 어댑터 (기획서/평가기준비교.md §6). 인터페이스: load(path) -> (criteria_dict, notes).

어댑터는 정본 JSON(§2.1)으로 바꾸기만 하고 형식 검사(§2)는 대신하지 않는다. 새 형식은 키 하나를 추가한다.
"""

from hazop.evaluate.adapters import json_file, xlsx_sheet

ADAPTERS = {"json": json_file, "xlsx_sheet": xlsx_sheet}
