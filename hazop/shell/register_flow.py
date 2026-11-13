"""끌어 놓은 파일을 등록하고 추출·그래프까지 잇는다(새 웹 화면 도면 패널). Qt를 import하지 않는다.

이전 화면 ①(`hazop/app/screens/register.py`)이 부르는 엔진 함수를 그대로 부른다: `registry.register` → `data.extract_and_graph`.
등록이 실패·보류면 추출하지 않고 이유를 적어 오류로 올린다(완료로 표시하지 않는다).
"""

from hazop import paths
from hazop.app import data
from hazop.register import registry

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
    return {"outcome": result["outcome"], "material_id": rec.get("material_id"), "pages": len(out.get("pages") or [out])}
