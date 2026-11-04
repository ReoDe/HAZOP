"""④ AI 호출부 (기획서/HAZOP분석.md 'AI 추론과 위험도 제안', '모델 연결').

호출부를 분리한다: 모든 클라이언트는 describe()와 infer(request)를 가진다.
- FixedResponseClient: 고정 응답 파일(<candidate_id>.json). 테스트·QA는 이것만 쓴다.
- AnthropicClient: 공식 SDK(anthropic.Anthropic). 사용자가 명시 옵션(--live)으로 실행할 때만 만든다.

infer() 결과 status: completed / no_response / input_mismatch / refused / truncated / api_error / parse_error
"""

import hashlib
import json
import os

from hazop import paths

DEFAULT_MODEL = "claude-opus-5-5"
ALLOWED_MODELS = ("claude-opus-5-5",)  # MVP 단일 모델(사용자 결정 2026-11-04). 다른 값은 거부
DEFAULT_MAX_TOKENS = 16000
DEFAULT_EFFORT = "high"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

TEMPLATE_ID = "hazop-deviation-analysis"
TEMPLATE_VERSION = "3"

SYSTEM_PROMPT = """너는 원자력발전소 계통 HAZOP 검토를 돕는 분석 보조자다. 결과는 전문가 검토용 초안이다.
입력 JSON(편차 후보 1건)의 설계 의도·정상 운전 조건, 그래프 탐색 근거(evidence), 적용된 원인·결과 패턴(pattern_matches),
누락 정보와 탐색 한계만 근거로 쓴다.

규칙:
1. facts에는 evidence로 확인되는 사실만 쓰고 evidence_ids를 하나 이상 인용한다.
2. scenarios의 basis는 적용된 cause 패턴을 해석했으면 "pattern"(pattern_match_id 필수),
   패턴 밖의 추가 가설이면 "additional_hypothesis"(pattern_match_id는 null)로 둔다.
3. node_ids, relation_ids, evidence_ids, pattern_match_id, safeguards.node_id, credited_safeguard_node_ids에는
   입력 allowed_ids에 있는 값만 쓴다. 없는 ID를 만들지 않는다. 보호수단 node_id는 도면 객체(배관 구간 제외)만 쓴다.
4. 연결 경로(도달 가능)만으로 인과관계를 단정하지 않는다. 정상 유동 방향만으로 역류·과압 전파를 배제하지 않는다.
5. 보호수단은 그래프에 존재만 확인되었으며 독립성·용량·작동 적정성은 미확인이다.
6. 위험도: risk_criteria가 null이면 severity와 frequency 값을 모두 null로 둔다. 있으면 severity(강도 1-4)는 보호수단을
   고려하지 않고, frequency_without_safeguards(발생빈도 1-3)는 보호수단 효과 없이, frequency_with_safeguards는
   credited_safeguard_node_ids의 보호수단을 반영해 제안한다. 위험도 등급은 계산하지 않는다(Python이 기준표로 계산).
   판단 근거가 부족하면 null로 두고 missing_information에 적는다.
7. 확인되지 않은 정보는 추정하지 말고 missing_information에 자료 요청으로 적는다.
8. 원인·결과·보호수단에는 그래프(도면)에 있는 실제 기기만 쓴다. 도면에 없는 설비(도면에 표시되지 않은 전열기·경보·차단밸브,
   다른 도면 연결점 너머의 설비 등)를 가정하지 않는다. 연결 요소(tee·continuation·pipe_cap)와 배관 구간은 기기가 아니다.
   cause_entity_ids에는 원인이 되는 기기의 entity_id를, assumed_equipment에는 시나리오가 전제한 기기의 entity_id를 모두 적는다.
   cause·consequence·interpretation 문장에 그래프에 없는 설비 이름이 들어가면 그 이름을 outside_graph_equipment에
   모두 적는다(자기 신고, 그 시나리오는 결과에서 제외됨). 없으면 빈 목록.
   보호수단 node_id는 입력 allowed_ids.safeguard_node_ids 안에서만 고른다. 도면에 없는 보호수단·설비는 missing_information에
   자료 요청으로만 적는다.
9. 도면 설비만으로 분석했는데 중대한 문제가 보이면 그대로 기술한다(설계보완 후보 판정은 Python이 한다).
10. 한국어로 쓴다."""

USER_PREFIX = "다음은 편차 후보 1건의 분석 입력이다(JSON).\n"

_IDS = {"type": "array", "items": {"type": "string"}}
_STR = {"type": "string"}


def _nullable_enum(values):
    return {"anyOf": [{"type": "integer", "enum": list(values)}, {"type": "null"}]}


def _obj(props, required=None):
    return {"type": "object", "additionalProperties": False, "required": required or list(props),
            "properties": props}


RESPONSE_SCHEMA = _obj({
    "candidate_id": _STR,
    "facts": {"type": "array", "items": _obj({
        "statement": _STR, "evidence_ids": _IDS, "node_ids": _IDS, "relation_ids": _IDS})},
    "scenarios": {"type": "array", "items": _obj({
        "basis": {"type": "string", "enum": ["pattern", "additional_hypothesis"]},
        "pattern_match_id": {"anyOf": [_STR, {"type": "null"}]},
        "cause": _STR, "consequence": _STR, "interpretation": _STR,
        "node_ids": _IDS, "relation_ids": _IDS, "evidence_ids": _IDS,
        "cause_entity_ids": _IDS,
        "assumed_equipment": _IDS,
        "outside_graph_equipment": {"type": "array", "items": _STR},
        "safeguards": {"type": "array", "items": _obj({"node_id": _STR, "description": _STR})},
        "risk": _obj({
            "severity": _nullable_enum((1, 2, 3, 4)), "severity_basis": _STR,
            "frequency_without_safeguards": _nullable_enum((1, 2, 3)),
            "frequency_with_safeguards": _nullable_enum((1, 2, 3)),
            "credited_safeguard_node_ids": _IDS, "frequency_basis": _STR,
            "assumptions": {"type": "array", "items": _STR}, "uncertainty": _STR}),
    })},
    "missing_information": {"type": "array", "items": _obj({"item": _STR, "reason": _STR, "request": _STR})},
})


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def template_info():
    canon = SYSTEM_PROMPT + "\n" + USER_PREFIX + json.dumps(RESPONSE_SCHEMA, sort_keys=True)
    return {"template_id": TEMPLATE_ID, "template_version": TEMPLATE_VERSION, "sha256": _sha(canon)}


def build_request(bundle):
    """근거 묶음 -> 요청(시스템·사용자 문장·응답 스키마). 같은 묶음이면 같은 요청."""
    user = USER_PREFIX + json.dumps(bundle, ensure_ascii=False, sort_keys=True)
    return {"candidate_id": bundle["candidate"]["candidate_id"], "system": SYSTEM_PROMPT, "user": user,
            "schema": RESPONSE_SCHEMA, "user_sha256": _sha(user),
            # 아래 두 값은 API로 보내지 않는다(고정 응답 대조용)
            "region_id": bundle["region"]["region_id"], "bundle_sha256": bundle_sha256(bundle)}


def bundle_sha256(bundle):
    return _sha(json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _parse_text(text):
    try:
        return json.loads(text), None
    except (TypeError, ValueError) as exc:
        return None, "JSON 파싱 실패: %s" % exc


class FixedResponseClient:
    """고정 응답 파일 <response_dir>/<candidate_id>.json
    형식: {"sample_note": "...", "region_id": "...", "bundle_sha256": "...",
           "stop_reason": "end_turn"|"refusal"|"max_tokens", "output": {...}}
    region_id가 다르거나, verify_bundle이면 bundle_sha256이 요청 근거 묶음과 다를 때 input_mismatch(응답 쓰지 않음)."""

    def __init__(self, response_dir, repo_root=None, verify_bundle=True):
        self.response_dir = response_dir
        self.repo_root = repo_root
        self.verify_bundle = verify_bundle

    def describe(self):
        d = self.response_dir
        if self.repo_root:
            d = paths.rel_or_abs(d, self.repo_root)
        return {"type": "fixed_response", "model": None, "response_dir": d, "verify_bundle": self.verify_bundle,
                "note": "고정 응답(테스트·QA용). 실제 AI 호출 아님"}

    def infer(self, request):
        path = os.path.join(self.response_dir, request["candidate_id"] + ".json")
        if not os.path.isfile(path):
            return {"status": "no_response", "error": "고정 응답 파일 없음: %s.json" % request["candidate_id"]}
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            return {"status": "parse_error", "error": "고정 응답 파일 JSON 오류: %s" % exc, "response_sha256": _sha(raw)}
        res = {"response_file": os.path.basename(path), "response_sha256": _sha(raw),
               "sample_note": doc.get("sample_note"), "stop_reason": doc.get("stop_reason", "end_turn"),
               "stop_details": doc.get("stop_details")}
        if doc.get("region_id") != request.get("region_id"):
            return dict(res, status="input_mismatch",
                        error="고정 응답의 구간 %r != 요청 구간 %r" % (doc.get("region_id"), request.get("region_id")))
        if self.verify_bundle and doc.get("bundle_sha256") != request.get("bundle_sha256"):
            return dict(res, status="input_mismatch", error="고정 응답의 근거 묶음 해시가 요청과 다름(입력이 바뀜)")
        if res["stop_reason"] == "refusal":
            return dict(res, status="refused", error="거절(refusal)")
        if res["stop_reason"] == "max_tokens":
            return dict(res, status="truncated", error="max_tokens로 응답 잘림")
        text = json.dumps(doc.get("output"), ensure_ascii=False)
        out, err = _parse_text(text)
        return dict(res, status="completed" if err is None else "parse_error", raw_text=text, output=out, error=err)


class AnthropicClient:
    """Claude API. client를 주입하면 그것을 쓴다(테스트의 모의 객체). 없으면 anthropic.Anthropic()."""

    def __init__(self, model=DEFAULT_MODEL, max_tokens=DEFAULT_MAX_TOKENS, effort=DEFAULT_EFFORT,
                 server_fallback=True, client=None):
        if model not in ALLOWED_MODELS:
            raise ValueError("허용되지 않은 모델 %r — 허용: %s" % (model, ", ".join(ALLOWED_MODELS)))
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.server_fallback = server_fallback
        self._client = client

    @staticmethod
    def credentials_available():
        """SDK가 찾을 수 있는 자격 증명이 있는지(실제 호출 전 확인). 네트워크 호출 없음."""
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return True
        try:
            import anthropic
            c = anthropic.Anthropic()
        except Exception:  # SDK가 자격 증명 해석 단계에서 실패
            return False
        return bool(getattr(c, "api_key", None) or getattr(c, "auth_token", None))

    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def describe(self):
        try:
            import anthropic
            sdk = anthropic.__version__
        except ImportError:
            sdk = None
        return {"type": "anthropic_api", "model": self.model, "max_tokens": self.max_tokens, "effort": self.effort,
                "server_fallback": "default" if self.server_fallback else None,
                "beta": FALLBACK_BETA if self.server_fallback else None, "sdk_version": sdk,
                "note": "output_config는 SDK 인자로 전달. fallbacks는 SDK 0.102 인자에 없어 extra_body로 전달"}

    def build_params(self, request):
        """messages.create 인자. thinking·temperature 등 샘플링 인자·tool_choice·assistant prefill 없음."""
        params = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": request["system"],
            "messages": [{"role": "user", "content": request["user"]}],
            "output_config": {"effort": self.effort,
                              "format": {"type": "json_schema", "schema": request["schema"]}},
        }
        if self.server_fallback:
            params["extra_body"] = {"fallbacks": "default"}
            params["extra_headers"] = {"anthropic-beta": FALLBACK_BETA}
        return params

    def infer(self, request):
        import anthropic
        params = self.build_params(request)
        try:
            msg = self.client().messages.create(**params)
        except anthropic.RateLimitError as exc:
            return {"status": "api_error", "error_type": "rate_limit", "status_code": exc.status_code,
                    "error": str(exc)}
        except anthropic.APIStatusError as exc:
            return {"status": "api_error", "error_type": "api_status", "status_code": exc.status_code,
                    "error": str(exc)}
        except anthropic.APIConnectionError as exc:
            return {"status": "api_error", "error_type": "connection", "status_code": None, "error": str(exc)}
        except anthropic.APIError as exc:  # 응답 형식 오류(APIResponseValidationError) 등
            return {"status": "api_error", "error_type": type(exc).__name__, "status_code": None, "error": str(exc)}
        res = {"response_id": getattr(msg, "id", None), "response_model": getattr(msg, "model", None),
               "stop_reason": getattr(msg, "stop_reason", None), "stop_details": _dump(getattr(msg, "stop_details", None)),
               "usage": _dump(getattr(msg, "usage", None))}
        if res["stop_reason"] == "refusal":
            return dict(res, status="refused", error="거절(refusal)")
        if res["stop_reason"] == "max_tokens":
            return dict(res, status="truncated", error="max_tokens로 응답 잘림")
        text = next((b.text for b in (getattr(msg, "content", None) or []) if getattr(b, "type", None) == "text"), None)
        if text is None:
            return dict(res, status="parse_error", error="text 블록 없음")
        out, err = _parse_text(text)
        return dict(res, status="completed" if err is None else "parse_error", raw_text=text, output=out, error=err)


def _dump(obj):
    if obj is None or isinstance(obj, (dict, str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)
