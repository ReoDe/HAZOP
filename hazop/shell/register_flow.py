"""끌어 놓은 파일을 등록하고 추출·그래프까지 잇는다(새 웹 화면 도면 패널). Qt를 import하지 않는다.

이전 화면 ①(`hazop/app/screens/register.py`)이 부르는 엔진 함수를 그대로 부른다: `registry.register` → `data.extract_and_graph`.
등록이 실패·보류면 추출하지 않고 이유를 적어 오류로 올린다(완료로 표시하지 않는다).
"""

import logging
import os

from hazop import paths
from hazop.app import data
from hazop.extract import ai_review
from hazop.register import registry

LOG = logging.getLogger("hazop.shell.register_flow")

MATERIAL_TYPE = "P&ID"   # 끌어 놓기는 도면으로 받는다. 설계 문서(PDF)로 바꾸는 일은 행에서 하는 것으로 2단계 이후에 둔다


def register_and_extract(engine, path, progress):
    progress("등록 중", 1, 2)
    result = registry.register(path, engine.project_id(), MATERIAL_TYPE, paths.store_root(), None, engine.reviewer())
    rec = result["record"]
    if rec.get("status") != "registered" or result["outcome"] in ("failed", "on_hold"):
        blockers = (rec.get("validation") or {}).get("blockers") or []
        cause = (blockers[0].get("reason") if blockers else None) or next(iter(result.get("notes") or []), None) or result["outcome"]
        raise RuntimeError("등록하지 못함: %s" % cause)
    progress("추출·그래프", 2, 2)
    out = data.extract_and_graph(result["registration_file"])
    pages = [(os.path.basename(p["extract_dir"]), p["extraction"]) for p in (out.get("pages") or [out])]
    return {"outcome": result["outcome"], "material_id": rec.get("material_id"), "pages": len(pages),
            "ai_review": review_if_wanted(engine, pages, progress)}


def review_if_wanted(engine, pages, progress):
    """추출 뒤 AI 검토 토글이 켜져 있고 연결이 준비돼 있으면 도면마다 호출 상한까지 후보를 제안받는다(이전 화면 ①의 AiReviewBar와 같은
    `ai_review.run_many`). 꺼져 있거나 연결이 없거나 API 연결이면 건너뛴다. AI 검토가 실패해도 등록·추출은 완료로 둔다.
    -> {"ran": bool, "candidates": 수, "skipped": 까닭 또는 None}"""
    if not engine.settings.get("extract_ai_review"):
        return {"ran": False, "candidates": 0, "skipped": "off"}
    ai = engine.ai
    status = ai.status() if ai is not None else {}
    if ai is None or not status.get("can_start"):
        return {"ran": False, "candidates": 0, "skipped": "no_connection"}
    cap = int(engine.settings.get("extract_ai_cap") or ai_review.DEFAULT_CAP)
    try:
        client = ai.make_client()
        reason = ai_review.refuse_reason(client)
        if reason:
            return {"ran": False, "candidates": 0, "skipped": reason}
        progress("AI 검토 준비 중", 0, None)
        done = ai_review.run_many(pages, client, cap=cap, on_progress=lambda name, d, t, left: progress("AI 검토 %s" % name, d, t))
    except Exception as exc:  # noqa: BLE001 - AI 검토 실패는 등록·추출을 되돌리지 않는다
        LOG.exception("AI 검토 오류")
        return {"ran": False, "candidates": 0, "skipped": "error: %s" % type(exc).__name__}
    return {"ran": True, "candidates": sum(count for _name, count, _stats in done), "skipped": None}
