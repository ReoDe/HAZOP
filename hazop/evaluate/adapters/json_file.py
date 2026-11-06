"""정본 JSON 기준 파일 읽기(변환 없음)."""

import json

from hazop.evaluate.criteria import CriteriaError

NAME = "json"
VERSION = None  # 변환하지 않으므로 보고서 adapter는 null


def load(path):
    try:
        with open(path, "rb") as fh:
            doc = json.loads(fh.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CriteriaError("기준 JSON을 읽을 수 없음: %s" % exc)
    return doc, []
