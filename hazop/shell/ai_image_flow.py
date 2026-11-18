"""AI 검토 실행에 그림 입력을 잇는 곳(도면 패널의 AI 검토 실행과 추출 뒤 자동 AI 검토가 함께 쓴다). Qt를 import하지 않는다.

규격은 docs/specs/extraction.md 'AI 검토 실행(R2)'의 '그림 입력 진입'. 이 모듈은 어느 도면에 그림을 실을지(원본 PDF가 프로젝트에 있는 벡터 PDF),
프로젝트 도면 목록(범례판 재료), 예상 호출 수, 구독 클라이언트 고르기, 도면별 실행 순서를 정하고, 그림을 만들고 묻는 일은
hazop.extract.ai_images·ai_review가 한다.

- 켜고 끄기: 설정 `ai_review_images`. 수동 실행은 값이 없으면 켬이다(스위치와 안내가 실행 전에 보인다). 추출 뒤 자동 검토는 안내를 거치지 않으므로
  값이 명시적으로 True일 때만 그림을 싣는다(수동 실행을 누르면 그때의 스위치 값이 설정에 적힌다). 이 선택 하나뿐이다.
- 그림을 싣는 도면: 추출 결과의 source.format이 pdf_vector이고 source.file의 원본 PDF가 지금 있는 도면. drawio·DEXPI·스캔·원본이 없는 도면은 글 입력.
- 범례판 캐시: paths.folder('cache', 'ai-legend') 아래에만 쓴다(지워도 되는 계산 결과, 저장소·배포본에 들어가지 않음).
- 보내는 것: 종류를 못 정한 기호 둘레의 조각 그림과 범례판. 구독 연결로만 보낸다(subscription_client가 API 클라이언트를 거절한다).
- 범례판 출처는 도면 실행 기록(runs[].images)에 그 실행을 저장할 때 함께 적는다(run_pages가 ai_review.run과 merge_and_save를 직접 부른다.
  run_many와 같은 순서이고, 실행 기록에 덧붙일 값을 받는 인자가 run_many에 생기면 그쪽으로 옮긴다).
"""

import logging
import os

from hazop import paths
from hazop.app import data
from hazop.extract import ai_images, ai_review, corrections

LOG = logging.getLogger("hazop.shell.ai_image_flow")
KEY = "ai_review_images"
LEGEND_LABELS = {"project": "이 프로젝트 도면에서 만든 견본", "project+symbols": "이 프로젝트 도면 견본과 표준 기호 그림",
                 "symbols": "표준 기호 그림", "none": "범례판 없이"}
UNKNOWN_LEGEND = "출처를 알 수 없는 범례판"      # 새 출처 값이 와도 화면은 이 기본 표시로 보인다
FAILED_TEXT = "그림을 만들지 못해 글만 보냄"
NOT_PDF_TEXT = "이 도면은 PDF 도면이 아니라 글만 보냅니다."
NO_ORIGINAL_TEXT = "원본 PDF가 없어 글만 보냅니다."
API_REFUSED = "AI 검토는 Claude 구독 연결로만 돕니다. 연결 방식을 구독으로 바꾸면 켤 수 있습니다(건별 요금 방지)."
NO_SUBSCRIPTION = "구독 연결을 쓸 수 없어 AI 검토를 하지 않습니다(AI 검토는 구독 연결로만 돕니다)."


def enabled(engine, auto=False):
    """그림 입력을 쓰는지. 수동 실행은 설정이 없으면 켬, 자동 검토(auto)는 설정이 명시적으로 True일 때만."""
    value = engine.settings.get(KEY)
    return value is True if auto else value is not False


def pdf_source(ex):
    """추출 결과의 (원본 PDF 경로, 쪽 번호(0부터)). 그림을 실을 수 없으면 None."""
    return _source(ex)[0]


def text_reason(ex):
    """그림을 실을 수 없는 까닭(화면에 보일 글). 실을 수 있으면 None."""
    return _source(ex)[1]


def _source(ex):
    src = ex.get("source") or {}
    if src.get("format") != "pdf_vector" or not src.get("file"):
        return None, NOT_PDF_TEXT
    path = paths.resolve_rel(src["file"], paths.work_root())
    if not os.path.isfile(path):
        return None, NO_ORIGINAL_TEXT
    try:
        page = int(((ex.get("run") or {}).get("settings") or {}).get("page_index") or 0)
    except (TypeError, ValueError):
        page = 0
    return (path, max(0, page)), None


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


# ---------------------------------------------------------------- 구독 클라이언트

def is_api_client(client):
    """API 키(건별 요금) 클라이언트인가. 실제 API 클라이언트의 describe에는 via가 없고 type만 있어, 둘 다 본다."""
    try:
        d = client.describe() if hasattr(client, "describe") else {}
    except Exception:  # noqa: BLE001
        d = {}
    if not isinstance(d, dict):
        d = {}
    if d.get("via") == "api" or d.get("type") == "anthropic_http":
        return True
    from hazop.study import claude_http
    return isinstance(client, claude_http.ClaudeHttpClient)


def subscription_client(engine):
    """AI 검토에 쓸 클라이언트 → (client, None) 또는 (None, 못 쓰는 까닭). 분석 연결이 API 키여도 구독으로만 돈다.
    연결 객체가 있으면 구독 클라이언트를 직접 만들고(구독 방식이 없으면 못 씀, 고정 응답을 설정에서 고른 시험 실행만 예외),
    연결 객체가 없는 창구(시험 대역)는 make_client()를 쓰되 API 클라이언트면 거절한다."""
    ai = engine.ai
    if ai is None:
        return None, NO_SUBSCRIPTION
    conn = getattr(ai, "conn", None)
    if conn is not None:
        methods = conn.methods()
        if "subscription" in methods:
            client = conn.make_client("subscription")
        elif conn.method == "fixed" and "fixed" in methods:
            client = conn.make_client("fixed")
        else:
            return None, NO_SUBSCRIPTION
    else:
        client = ai.make_client()
    if is_api_client(client):
        return None, API_REFUSED
    return client, ai_review.refuse_reason(client)


# ---------------------------------------------------------------- 그림 입력 만들기

class Factory:
    """도면마다 그림 입력을 만들고, 어느 범례판을 썼는지 used에, 만들지 못한 도면을 failed에 남긴다.
    프로젝트 도면 목록(범례판 재료)은 처음 필요할 때 한 번 읽고, 읽다 실패하면 빈 목록으로 굳힌다(도면마다 다시 읽지 않는다)."""

    def __init__(self, engine, extra=()):
        self.engine, self.extra = engine, dict(extra)
        self.used, self.failed = {}, []
        self._drawings = None

    def drawings(self):
        if self._drawings is None:
            try:
                names = list((self.engine.graph_names() or {}).values())
                out = []
                for name in names + [n for n in self.extra if n not in names]:
                    try:
                        ex = self.extra.get(name) or data.read_json(data.extraction_path(name))
                        src = pdf_source(ex)
                        if src:
                            out.append((src[0], src[1], corrections.apply_saved(ex, name)))
                    except (OSError, ValueError, KeyError):
                        continue
                self._drawings = out
            except Exception:  # noqa: BLE001 - 범례판 재료를 못 읽어도 실행은 계속한다(범례판이 표준 기호 그림으로 바뀐다)
                LOG.exception("프로젝트 도면 목록을 읽지 못함")
                self._drawings = []
        return self._drawings

    def __call__(self, name, ex):
        src = pdf_source(ex)
        if src is None:
            return None
        try:
            img = ai_images.image_input_for(src[0], src[1], drawings=self.drawings(), cache_dir=paths.folder("cache", "ai-legend"))
        except Exception:  # noqa: BLE001 - 그림을 만들지 못해도 그 도면은 글 입력으로 돌린다(호출 수는 그림 입력 예상으로 자른다)
            LOG.exception("그림 입력을 만들지 못함: %s", name)
            self.failed.append(name)
            return None
        self.used[name] = img.legend_source
        return img


def _tolerant(progress, name):
    """호출 사이의 진행 알림. 작업 멈춤 요청이 서 있으면 알림이 JobStopped를 올리는데, 그것이 ai_review.run 안으로 번지면 그 도면에서 이미 받은 답을
    저장하지 못하고 버린다(구독 한도만 쓰고 결과가 없다). 여기서 삼키면 run이 곧바로 should_stop을 보고 새 호출 없이 멈추며, 받은 답은 저장된다."""
    from hazop.shell import api

    def on(d, t, left):
        try:
            progress(name, d, t, left)
        except api.JobStopped:
            pass
    return on


def run_pages(engine, pages, client, cap, run_cap, progress, should_stop, auto=False):
    """도면마다 AI 검토를 돌려 후보 문서에 합쳐 저장한다(ai_review.run_many와 같은 순서). 그림 입력은 설정(enabled)이 켜졌을 때만이고,
    범례판 출처·그림 실패는 그 실행 기록(runs[].images)에 저장과 함께 적힌다. 실행 상한이 바닥난 도면은 그림을 만들지 않는다.
    그림 입력을 만들지 못한 도면은 글 입력으로 돌리되 그 도면의 그림 입력 예상 호출 수에서 자른다.
    → ([(이름, 새 후보 수, stats)], Factory 또는 None)."""
    images = Factory(engine, pages) if enabled(engine, auto) else None
    done, used = [], 0
    for name, ex in pages:
        if should_stop and should_stop():
            break
        budget, limit, img, info = run_cap - used, cap, None, None
        if images is not None and budget > 0 and pdf_source(ex):
            img = images(name, ex)
            if img is None:
                limit = min(cap, ai_review.estimate_pages([(name, ex)], cap=cap, run_cap=budget, images=estimate_input())["calls"])
                info = {"failed": True}
            else:
                info = {"legend_source": img.legend_source}
        result = ai_review.run(ex, client, cap=limit, budget=budget, exclude=ai_review.decided_targets(name),
                               on_progress=_tolerant(progress, name) if progress else None, should_stop=should_stop, images=img)
        stats = result["stats"]
        used += stats["calls"]
        if info is not None:
            stats["images"] = info
        if not stats["refused"]:
            desc = client.describe() if hasattr(client, "describe") else {}
            ai_review.merge_and_save(name, ex, result, via=desc.get("via"), model=desc.get("model"))
        done.append((name, len(result["candidates"]), stats))
        if stats["halted"] or stats["refused"]:
            break
    return done, images
