"""⑤ 검토 기록 저장·읽기와 분석 실행 열기 (기획서/인터페이스.md §5.1, §5.2 analysis_sha256, §3.4 분석 결과 변경).

저장 위치: <저장 루트>/reviews/<region_id>/<analysis_run_id>/<candidate_id>/v<review_version>.json
- 저장할 때마다 새 버전 파일을 만들고 이전 파일은 고치지 않는다(있으면 저장 거부).
- 같은 폴더 임시 파일에 다 쓴 뒤 os.link로 최종 이름을 배타적으로 만든다(원자적·덮어쓰기 없음, write_exclusive).
"""

import hashlib
import json
import os
import re
import tempfile

from hazop import paths
from hazop.analysis.run import utc_now  # noqa: F401  (UTC ISO 8601 초 단위 'Z' — 실행 기록과 같은 함수)

REVIEWS_DIR = "reviews"
_VERSION_FILE = re.compile(r"^v(\d+)\.json$")


class ReviewError(ValueError):
    """검토 저장·검사 실패. errors에 사유 목록."""

    def __init__(self, errors):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


def file_sha256(path):
    """파일 바이트의 SHA-256. 파일이 없으면 None."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        return None


def obj_sha256(obj):
    """정렬한 JSON(UTF-8, 공백 없음)의 SHA-256. ai_original 해시에 쓴다."""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def open_run(run_dir):
    """분석 실행 폴더를 읽기 전용으로 연다. analysis.json이 없으면 ReviewError.

    반환 dict: run_dir, analysis_path, analysis_sha256(연 시점 파일 바이트 해시), doc,
    criteria(<실행>/inputs/risk_criteria.json, 없으면 None), graph(inputs/graph.json, 없으면 None),
    blocked(bool), blocked_reasons(list)."""
    analysis_path = os.path.join(run_dir, "analysis.json")
    if not os.path.isfile(analysis_path):
        raise ReviewError("analysis.json 없음: %s" % analysis_path)
    with open(analysis_path, "rb") as fh:
        raw = fh.read()
    doc = json.loads(raw.decode("utf-8"))
    crit_path = os.path.join(run_dir, "inputs", "risk_criteria.json")
    graph_path = os.path.join(run_dir, "inputs", "graph.json")
    criteria = _read_json(crit_path) if os.path.isfile(crit_path) else None
    graph = _read_json(graph_path) if os.path.isfile(graph_path) else None
    reasons = []
    validation = doc.get("validation") or {}
    if validation.get("status") != "passed":
        reasons.append("분석 결과 검증 상태가 passed가 아님(%s): %s"
                       % (validation.get("status"), "; ".join(validation.get("errors") or [])))
    return {"run_dir": run_dir, "analysis_path": analysis_path,
            "analysis_sha256": hashlib.sha256(raw).hexdigest(), "doc": doc,
            "criteria": criteria, "graph": graph, "blocked": bool(reasons), "blocked_reasons": reasons}


def path_component(value, label):
    """경로 한 단계로 쓸 식별자 검사(safe_name으로 바뀌는 값·빈 값은 거부). 검토 기록·Excel 출력 경로가 함께 쓴다."""
    s = str(value or "")
    if not s or paths.safe_name(s) != s:
        raise ReviewError("%s를 경로 이름으로 쓸 수 없음: %r" % (label, value))
    return s


def review_dir(store_root, region_id, analysis_run_id, candidate_id):
    """편차 검토본 폴더 경로(만들지 않음)."""
    d = paths.safe_join(store_root, REVIEWS_DIR)
    for value, label in ((region_id, "region_id"), (analysis_run_id, "analysis_run_id"),
                         (candidate_id, "candidate_id")):
        d = paths.safe_join(d, path_component(value, label))
    return d


def list_versions(store_root, region_id, analysis_run_id, candidate_id):
    """저장된 review_version 목록(오름차순). 없으면 []."""
    d = review_dir(store_root, region_id, analysis_run_id, candidate_id)
    if not os.path.isdir(d):
        return []
    return sorted(int(m.group(1)) for m in (_VERSION_FILE.match(n) for n in os.listdir(d)) if m)


def load_review(store_root, region_id, analysis_run_id, candidate_id, version=None):
    """검토본 읽기. version이 None이면 최신. 없으면 None."""
    versions = list_versions(store_root, region_id, analysis_run_id, candidate_id)
    if version is None:
        if not versions:
            return None
        version = versions[-1]
    elif version not in versions:
        return None
    return _read_json(os.path.join(review_dir(store_root, region_id, analysis_run_id, candidate_id),
                                   "v%d.json" % version))


def load_run_reviews(store_root, region_id, analysis_run_id):
    """한 실행의 편차별 최신 검토본 {candidate_id: record}."""
    d = paths.safe_join(paths.safe_join(store_root, REVIEWS_DIR), path_component(region_id, "region_id"))
    d = paths.safe_join(d, path_component(analysis_run_id, "analysis_run_id"))
    out = {}
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name != "exports" and os.path.isdir(os.path.join(d, name)):
                rec = load_review(store_root, region_id, analysis_run_id, name)
                if rec is not None:
                    out[name] = rec
    return out


def check_editable(run, record=None):
    """편집·저장 가능 여부(§3.4 분석 결과 변경, §5.3). 반환 {"editable": bool, "reasons": [...], "current_sha256"}.

    analysis.json이 지워졌거나, 파일 바이트 해시가 연 시점 값 또는 검토본의 analysis_ref.analysis_sha256과
    다르면 편집 불가(열람만). blocked 결과도 편집 불가."""
    current = file_sha256(run["analysis_path"])
    reasons = []
    if current is None:
        reasons.append("analysis.json이 없음 — 열람만 가능")
    else:
        if current != run["analysis_sha256"]:
            reasons.append("analysis.json이 연 뒤에 바뀜 — 다시 열어야 함")
        saved = ((record or {}).get("analysis_ref") or {}).get("analysis_sha256")
        if record is not None and saved != current:
            reasons.append("검토 기록의 analysis_sha256과 현재 analysis.json 해시가 다름 — 열람만 가능")
    reasons.extend(run["blocked_reasons"])
    return {"editable": not reasons, "reasons": reasons, "current_sha256": current}


def write_exclusive(path, data):
    """bytes를 path에 새 파일로 쓴다. 같은 폴더 임시 파일에 쓰고 fsync한 뒤 os.link로 최종 이름을 만든다.
    최종 이름이 이미 있으면 ReviewError(덮어쓰지 않음). 실패하면 임시 파일을 지우고 최종 파일은 생기지 않는다."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise ReviewError("같은 이름 파일이 이미 있음(덮어쓰지 않음): %s" % path)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return path


def write_new_version(store_root, record):
    """record를 새 버전 파일로 원자적·배타적으로 쓴다(검사는 호출자 몫). 같은 버전 파일이 있으면 ReviewError."""
    d = review_dir(store_root, record["analysis_ref"]["region_ref"]["region_id"],
                   record["analysis_run_id"], record["candidate_id"])
    os.makedirs(d, exist_ok=True)
    data = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return write_exclusive(os.path.join(d, "v%d.json" % record["review_version"]), data)
