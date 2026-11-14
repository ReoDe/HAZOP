"""AI 연결 설정 묶음(기획서/AI연결-구독제.md §5·§11, 디자인/AI연결-화면설계.md §4). Qt 의존 없음.

설정 파일(paths.settings_path(), settings.json)에 함께 둔다. 이 필드를 읽고 쓰는 곳은 이 모듈 하나다.
API 키와 API 모델은 지금처럼 api_keys.json(apikey.KeyStore)에 둔다. 옛 설정 파일(이 필드가 없음)은 기본값으로 읽는다.

- ai_method: 사용자가 '이 방식으로 사용'으로 고른 방식. 없으면 앱이 정한다(ai_method_auto).
- ai_method_auto: 앱이 마지막으로 정한 방식. 다음 시작 때 결과가 달라질 때만 알리려고 남긴다.
"""

import datetime

from hazop import paths
from hazop.study import claude_cli, claude_http, providers

DEFAULTS = {"ai_method": None, "ai_method_auto": None, "subscription_terms_ack_at": None, "claude_cli_path": None,
            "ai_models": {}, "allow_overage": False, "ai_concurrency": 1, "fixed_response_dir": None}
CONCURRENCY_MAX = 2

# 새 화면(auto_api=False): 구독을 쓸 수 없고 키가 있어도 API로 넘어가지 않을 때 한 번 알리는 글
NOTICE_NO_SUBSCRIPTION = ("Claude 구독을 쓸 수 없어 AI 분석을 시작하지 않습니다. API 키(호출마다 요금)로 쓰려면 설정의 'API 키' 카드에서 "
                          "'이 방식으로 사용'을 누르세요.")
NOTICE_TO_API = "Claude Code를 쓸 수 없어 API 키로 연결했습니다. 구독을 쓰려면 AI 연결 설정을 여세요."
NOTICE_TO_SUBSCRIPTION = ("AI 연결을 Claude 구독으로 바꿨습니다. 건별 요금이 나가지 않습니다. API 키로 되돌리려면 "
                          "AI 연결 설정을 여세요.")


def auto_method(cli_state, has_key, methods):
    """사용자가 고른 방식이 없을 때 앱이 정하는 방식(화면 설계 §4 표). 구독 확인이 통과하면 구독,
    실패하면 API 키가 있을 때만 API. 키도 없으면 구독(실행할 수 없는 상태)으로 두어 무엇을 고칠지 보이게 한다."""
    if "subscription" not in methods:
        return "api"
    m = providers.default_method(cli_state)
    return m if m == "subscription" or has_key else "subscription"


def auto_notice(previous, new, has_key):
    """앱이 정한 방식이 바뀌었을 때만 토스트 문구, 아니면 None. 처음 켠 사용자(이전 값 없음)는 키가 있으면
    이전을 API로 본다(구독 연결 전에는 API뿐이었음). 키도 없는 첫 실행은 알릴 것이 없다."""
    if previous is None:
        if not has_key:
            return None
        previous = "api"
    if previous == new:
        return None
    return NOTICE_TO_SUBSCRIPTION if new == "subscription" else NOTICE_TO_API


class AiPrefs:
    """settings dict(주 창 self.settings와 같은 객체)의 AI 연결 필드를 읽고 쓴다. save는 settings를 파일에 쓰는 함수
    (예: lambda s: paths.save_settings(s, path)). save가 None이면 메모리에만 둔다(시험·단독 창)."""

    def __init__(self, settings=None, save=None):
        self.settings = settings if settings is not None else {}
        self._save = save

    def _get(self, name):
        v = self.settings.get(name)
        return DEFAULTS[name] if v is None else v

    def _set(self, **values):
        self.settings.update(values)
        if self._save is not None:
            self._save(self.settings)

    # ---- 방식
    @property
    def chosen_method(self):
        """사용자가 고른 방식. 이 실행본에서 쓸 수 없는 값(배포본의 구독 등)은 없는 것으로 본다."""
        m = self._get("ai_method")
        return m if m in providers.available_methods() else None

    def choose(self, method):
        if method not in providers.available_methods():
            raise ValueError("이 실행본에서는 쓸 수 없는 연결 방식: %r" % method)
        self._set(ai_method=method)

    @property
    def auto_method(self):
        m = self._get("ai_method_auto")
        return m if m in providers.available_methods() else None

    def remember_auto(self, method):
        if self._get("ai_method_auto") != method:
            self._set(ai_method_auto=method)

    # ---- 구독
    @property
    def terms_ack_at(self):
        return self._get("subscription_terms_ack_at")

    def ack_terms(self, now=None):
        at = (now or datetime.datetime.now(claude_cli.KST)).isoformat(timespec="seconds")
        self._set(subscription_terms_ack_at=at)
        return at

    @property
    def cli_path(self):
        return self._get("claude_cli_path")

    def set_cli_path(self, path):
        self._set(claude_cli_path=path or None)

    @property
    def allow_overage(self):
        return self._get("allow_overage") is True

    @property
    def concurrency(self):
        try:
            n = int(self._get("ai_concurrency"))
        except (TypeError, ValueError):
            return 1
        return max(1, min(CONCURRENCY_MAX, n))

    # ---- 모델(구독·고정 응답. API 모델은 KeyStore.model)
    def _models(self):
        v = self._get("ai_models")
        return v if isinstance(v, dict) else {}         # 손으로 고친 설정 파일의 다른 모양은 기본값으로 읽는다(고르면 고쳐 쓴다)

    @property
    def bad_models(self):
        """설정 파일의 ai_models가 사전이 아니거나 모르는 모델을 적었는지(화면이 '기본값으로 읽었음'을 알린다)."""
        v = self.settings.get("ai_models")
        if v is None:
            return False
        return not isinstance(v, dict) or any(m not in claude_http.MODELS for m in v.values())

    def model(self, method):
        if method == "fixed":
            return None
        m = self._models().get(method)
        return m if m in claude_http.MODELS else claude_http.DEFAULT_MODEL

    def set_model(self, method, model):
        if model not in claude_http.MODELS:
            raise ValueError("지원하지 않는 모델")
        models = {k: v for k, v in self._models().items() if v in claude_http.MODELS}
        models[method] = model
        self._set(ai_models=models)

    # ---- 고정 응답
    @property
    def fixed_dir(self):
        """고정 응답 폴더. 0.1.x가 적어 둔 옛 자리(<작업 루트>/데이터/고정응답/…)는 지금 자리로 풀어 준다. 고른 폴더를 다시
        저장하면(set_fixed_dir) 지금 자리가 적힌다."""
        return paths.resolve_moved(self._get("fixed_response_dir"))

    def set_fixed_dir(self, path):
        self._set(fixed_response_dir=path or None)
