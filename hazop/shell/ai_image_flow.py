"""AI 검토 실행에 그림 입력을 잇는 곳(도면 패널의 AI 검토 실행과 추출 뒤 자동 AI 검토가 함께 쓴다). Qt를 import하지 않는다.

규격은 docs/specs/extraction.md 'AI 검토 실행(R2)'의 '그림 입력 진입'. 이 모듈은 어느 도면에 그림을 실을지(원본 PDF가 프로젝트에 있는 벡터 PDF),
프로젝트 도면 목록(범례판 재료), 예상 호출 수만 정하고, 그림을 만들고 묻는 일은 hazop.extract.ai_images·ai_review가 한다.

- 켜고 끄기: 설정 `ai_review_images`(없으면 켬). 끄면 모든 도면을 글 입력으로 돌린다. 이 선택 하나뿐이다.
- 그림을 싣는 도면: 추출 결과의 source.format이 pdf_vector이고 source.file의 원본 PDF가 지금 있는 도면. drawio·DEXPI·스캔·원본이 없는 도면은 글 입력.
- 범례판 캐시: paths.folder('cache', 'ai-legend') 아래에만 쓴다(지워도 되는 계산 결과, 저장소·배포본에 들어가지 않음).
- 보내는 것: 종류를 못 정한 기호 둘레의 조각 그림과 범례판(구독 연결로만. 연결 방식은 api_aireview.run_review가 구독으로 고정한다).
"""

import logging
import os

from hazop import paths
from hazop.app import data
from hazop.extract import ai_images, ai_review, corrections

LOG = logging.getLogger("hazop.shell.ai_image_flow")
KEY = "ai_review_images"
LEGEND_LABELS = {"project": "이 프로젝트 도면에서 만든 견본", "symbols": "표준 기호 그림", "none": "범례판 없이"}


def enabled(engine):
    """그림 입력을 쓰는지(설정, 기본은 켬)."""
    return engine.settings.get(KEY) is not False


def pdf_source(ex):
    """추출 결과의 (원본 PDF 경로, 쪽 번호(0부터)). 벡터 PDF가 아니거나 원본이 없으면 None."""
    src = ex.get("source") or {}
    if src.get("format") != "pdf_vector" or not src.get("file"):
        return None
    path = paths.resolve_rel(src["file"], paths.work_root())
    if not os.path.isfile(path):
        return None
    try:
        page = int(((ex.get("run") or {}).get("settings") or {}).get("page_index") or 0)
    except (TypeError, ValueError):
        page = 0
    return path, max(0, page)


def estimate_input():
    """예상 호출 수를 셀 때 쓰는 그림 입력(쪽 그림을 그리지 않는다). 실행이 쓰는 기본값(wide·recheck)과 같다."""
    return ai_images.ImageInput(None, wide=True, recheck=True)


def estimate_pages(pages, cap, run_cap, with_images):
    """pages [(이름, 추출 결과)] → (ai_review.estimate_pages와 같은 꼴, {이름: 그림 입력 여부}).
    도면마다 실행과 같은 길(그림 가능한 PDF는 그림 입력, 나머지는 글 입력)로 세고, 실행 전체 상한(run_cap)은 앞에서부터 나눠 쓴다."""
    out, mode, left = [], {}, run_cap
    for name, ex in pages:
        img = bool(with_images and pdf_source(ex))
        mode[name] = img
        part = ai_review.estimate_pages([(name, ex)], cap=cap, run_cap=left, images=estimate_input() if img else None)
        left -= part["calls"]
        out += part["pages"]
    calls = sum(x["calls"] for x in out)
    needed = sum(min(x["needed"], cap) for x in out)
    return {"pages": out, "calls": calls, "needed": needed, "seconds": calls * ai_review.SECONDS_PER_CALL, "capped": needed > calls}, mode


class Factory:
    """run_many(images=)에 줄 함수. 도면마다 그림 입력을 만들고, 어느 범례판을 썼는지 used에 남긴다.
    프로젝트 도면 목록(범례판 재료)은 처음 필요할 때 한 번 읽는다. 그림 입력을 만들지 못한 도면은 글 입력으로 돌리고 failed에 센다."""

    def __init__(self, engine, extra=()):
        self.engine, self.extra = engine, list(extra)
        self.used, self.failed = {}, []
        self._drawings = None

    def drawings(self):
        if self._drawings is None:
            out = []
            names = list((self.engine.graph_names() or {}).values())
            for name in names + [n for n, _ex in self.extra if n not in names]:
                try:
                    ex = dict(self.extra).get(name) or data.read_json(data.extraction_path(name))
                    src = pdf_source(ex)
                    if src:
                        out.append((src[0], src[1], corrections.apply_saved(ex, name)))
                except (OSError, ValueError, KeyError):
                    continue
            self._drawings = out
        return self._drawings

    def __call__(self, name, ex):
        src = pdf_source(ex)
        if src is None:
            return None
        try:
            img = ai_images.image_input_for(src[0], src[1], drawings=self.drawings(), cache_dir=paths.folder("cache", "ai-legend"))
        except Exception:  # noqa: BLE001 - 그림을 만들지 못해도 그 도면은 글 입력으로 돌린다
            LOG.exception("그림 입력을 만들지 못함: %s", name)
            self.failed.append(name)
            return None
        self.used[name] = img.legend_source
        return img


def factory(engine, extra=()):
    """그림 입력을 끈 설정이면 None(글 입력), 아니면 Factory."""
    return Factory(engine, extra) if enabled(engine) else None


def stamp_run(name, info):
    """방금 저장된 그 도면의 마지막 실행 기록에 그림 입력 정보(info 사전)를 적는다. 그새 바뀌면 다시 읽어 적는다. 실패해도 실행 결과는 그대로다."""
    from hazop import store_io
    for _ in range(3):
        try:
            doc = ai_review.load_doc(name)
            if not doc or not doc.get("runs"):
                return False
            doc["runs"][-1]["images"] = dict(info)
            ai_review.save_doc(doc)
            return True
        except store_io.Conflict:
            continue
        except (OSError, ValueError):
            return False
    return False
