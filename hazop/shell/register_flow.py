"""끌어 놓은 파일을 등록하고 추출·그래프·자동 확정까지 잇는다(새 웹 화면 도면 패널). Qt를 import하지 않는다.

이전 화면 ①(`hazop/app/screens/register.py`)이 부르는 엔진 함수를 그대로 부른다: `registry.register` → `data.extract_and_graph`.
등록이 실패·보류면 추출하지 않고 이유를 적어 오류로 올린다(완료로 표시하지 않는다). 추출에 이어 AI 검토와 자동 확정(hazop/shell/auto_flow.py)을
돌린다. 그 일이 막히거나 실패해도 등록·추출은 완료다.
"""

import inspect
import logging
import os

from hazop import paths
from hazop.app import data
from hazop.register import registry, titleblock
from hazop.shell import auto_flow

LOG = logging.getLogger("hazop.shell.register_flow")

MATERIAL_TYPE = "P&ID"   # 끌어 놓기는 도면으로 받는다. 설계 문서(PDF)로 바꾸는 일은 행에서 하는 것으로 2단계 이후에 둔다


def upload(engine, path, progress):
    """올린 파일 하나의 작업(api.Engine.add_files가 예산에 올려 둔 것). 묶음의 마지막 파일이 끝나면 앞서 기다리던 도면을 남은 예산으로 이어 한다."""
    try:
        return register_and_extract(engine, path, progress)
    finally:
        if engine.auto_budget.file_done():
            auto_flow.resume_quietly(engine, set(engine.auto_budget.touched))
        engine.auto_budget.leave()


def register_and_extract(engine, path, progress):
    progress("등록 중", 1, 2)
    result = registry.register(path, engine.project_id(), MATERIAL_TYPE, paths.store_root(), None, engine.reviewer())
    rec = result["record"]
    if rec.get("status") != "registered" or result["outcome"] in ("failed", "on_hold"):
        blockers = (rec.get("validation") or {}).get("blockers") or []
        reasons = [str(b.get("reason")) for b in blockers[:3] if b.get("reason")]      # 엔진이 주는 사유를 그대로(DEXPI는 형식 판별·안전 검사 사유가 여기 온다)
        cause = "; ".join(reasons) or next(iter(result.get("notes") or []), None) or result["outcome"]
        raise RuntimeError("등록하지 못함: %s" % cause)
    pid = rec.get("project_id") or engine.project_id()
    number = _number(pid, rec, result["registration_file"])
    progress("도면 읽는 중", 2, 2)
    # 스캔 도면은 쪽마다 20~30초라 extract_and_graph가 progress(끝난 쪽 수, 전체 쪽 수, 문구)를 부른다(벡터·drawio는 부르지 않는다)
    wants = {"progress": lambda done, total, text=None: progress(text or "도면 읽는 중", done, total)} if "progress" in inspect.signature(data.extract_and_graph).parameters else {}
    with auto_flow.extracting(engine, pid, rec.get("material_id"), number["why"]) as intake:
        out = data.extract_and_graph(number["registration_file"], **wants)
        names = [os.path.basename(p["extract_dir"]) for p in (out.get("pages") or [out])]
        intake.start(names)
    if number["why"] == "taken":
        engine.emit("app.notice", {"text": "%s의 도면 번호를 다른 파일이 이미 쓰고 있어 자동 확정을 멈췄습니다. 어느 파일을 쓸지, 번호를 무엇으로 할지 채팅으로 알려 주세요."
                                   % os.path.basename(path)})
    return {"outcome": result["outcome"], "material_id": rec.get("material_id"), "pages": len(names),
            "conflicts": [c["drawing_number"] for c in (result.get("conflicts") or [])],      # 같은 번호를 다른 형식 원본이 이미 쓰고 있음(고르기는 도면 패널)
            "number": number["why"], "auto": run_auto(engine, names, progress)}


def _number(project_id, rec, registration_file):
    """추출 앞에서 표제란 번호를 자동으로 확정한다. 추출은 돌려준 등록 파일로 한다(확정하면 새 등록 버전이다). 실패해도 등록한 판으로 이어 간다."""
    try:
        return titleblock.auto_confirm_number(project_id, rec.get("material_id"))
    except (OSError, ValueError):
        LOG.exception("도면 번호 자동 확정 실패")
        return {"registration_file": registration_file, "confirmed": False, "why": "not_ready"}


def run_auto(engine, names, progress):
    """추출한 쪽들의 자동 확정. 실패해도 등록·추출은 완료로 둔다(쪽 기록에 waiting이 남아 이어 한다)."""
    try:
        return auto_flow.run(engine, names, progress)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("자동 확정 오류")
        return {"calls": 0, "done": [], "skipped": "error: %s" % type(exc).__name__}
