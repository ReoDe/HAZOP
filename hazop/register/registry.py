"""자료 등록: 해시·내부 ID·등록 버전 발급, 원본 보관, 저장 후 해시 확인, 등록정보 JSON 기록.

근거: 기획서/자료등록.md(MVP 등록 절차, 입력과 등록정보, 처리 원칙), 기획서/전체기획.md #data-contract(① -> ②),
flow chart/01-registration.md. 사용자 결정(2026-11-04): 저장 위치는 저장소 안 '자료저장소/'(인자·환경변수로 변경),
표제란 값은 자동 후보로만 기록하고 사람이 확정하기 전까지 확정값은 미확인.

저장 구조 (<저장 루트>/<project_id>/):
  registry.json                               자료 목록(자료 ID·해시·버전·상태)
  originals/<material_id>/<버전>/<원래 파일명>   보관 원본 (storage_ref는 이 프로젝트 폴더 기준 상대 경로)
  registrations/<material_id>/<버전>.json       등록 버전별 등록정보(① -> ② 전달 문서)

발급 규칙(결정적):
  material_id = "material-" + 최초 등록 원본 SHA-256 앞 12자리 (같은 내용이면 같은 ID)
  registration_version = 1부터 시작, 같은 자료의 식별정보가 확정·변경될 때마다 1 증가
상태(status): draft(저장 진행 중) / on_hold(등록정보 입력 오류·자료 ID 충돌로 보류) / registered(등록 완료) / failed(실패)
등록 완료된 버전 스냅샷은 불변이다. 이후 보관 원본 변조·누락 같은 실패는 registry.json의 자료 상태에 기록한다.
"""

import datetime
import getpass
import hashlib
import json
import os

from hazop import paths
from . import fileinfo

SCHEMA_VERSION = "0.1"
REGISTRAR = "hazop.register"
REGISTRAR_VERSION = "0.1.0"
MATERIAL_TYPES = ("P&ID",)
META_FIELDS = ("drawing_number", "design_revision", "title")
META_INPUT_KEYS = set(META_FIELDS) | {"by", "reason"}
DOCUMENT_ID = "document-001"  # drawio 파일 1개 = 문서 1개
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_STORE = os.environ.get("HAZOP_STORE_ROOT") or os.path.join(REPO_ROOT, "자료저장소")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _problem(check, reason, field=None):
    return {"check": check, "field": field, "reason": reason}


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha(path):
    with open(path, "rb") as fh:
        return sha256_of(fh.read())


def _write_json(path, obj):
    """임시 파일에 쓴 뒤 교체한다(쓰는 도중 실패해도 기존 파일이 깨지지 않게).
    등록정보 스냅샷은 직접 부르지 말고 _write_snapshot을 쓴다(완료된 버전 불변 확인)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_new(path, data):
    """새 파일로만 쓴다('xb': 같은 이름 파일이 있으면 실패, 덮어쓰지 않음). 테스트에서 저장 실패를 흉내 낼 때 교체한다."""
    fh = open(path, "xb")  # 여기서 실패하면 아무 파일도 만들지 않은 것(기존 파일은 남의 것이므로 건드리지 않음)
    try:
        with fh:
            fh.write(data)
    except BaseException:
        os.remove(path)  # 이 함수가 생성에 성공한 파일만 정리한다
        raise


def _write_snapshot(store, record):
    """등록 버전 스냅샷을 쓴다. 같은 버전 파일을 다시 쓰는 것은 등록 완료 전(draft·failed)에만 허용한다.
    이미 등록 완료(registered)된 버전 파일은 불변이며, 바꾸려 하면 RuntimeError."""
    path = store.snapshot_path(record["material_id"], record["registration_version"])
    if os.path.isfile(path) and _read_json(path).get("status") == "registered":
        raise RuntimeError("등록 완료된 버전은 다시 쓸 수 없음: %s 버전 %d"
                           % (record["material_id"], record["registration_version"]))
    _write_json(path, record)
    return path


def _display_path(path):
    absp = os.path.abspath(path)
    try:
        if os.path.commonpath([REPO_ROOT, absp]) == REPO_ROOT:
            return os.path.relpath(absp, REPO_ROOT).replace("\\", "/")
    except ValueError:  # 다른 드라이브
        pass
    return absp.replace("\\", "/")


class Store:
    """프로젝트 하나의 저장 공간."""

    def __init__(self, store_root, project_id):
        self.root = paths.safe_join(store_root, project_id)
        self.index_path = os.path.join(self.root, "registry.json")

    def load_index(self, project_id):
        if os.path.isfile(self.index_path):
            return _read_json(self.index_path)
        return {"schema_version": SCHEMA_VERSION, "project_id": project_id, "materials": []}

    def save_index(self, index):
        # registry.json은 자료 목록·현재 상태를 담는 가변 색인이다(버전 스냅샷과 달리 갱신 허용).
        _write_json(self.index_path, index)

    def snapshot_path(self, material_id, version):
        return os.path.join(self.root, "registrations", material_id, "%d.json" % version)

    def abs_ref(self, storage_ref):
        return paths.safe_join(self.root, storage_ref)


def _meta_problems(meta):
    problems = []
    for key, value in (meta or {}).items():
        if key not in META_INPUT_KEYS:
            problems.append(_problem("invalid_metadata", "알 수 없는 식별정보 항목 %r" % key, key))
        elif value is not None and (not isinstance(value, str) or not value.strip()):
            problems.append(_problem("invalid_metadata", "%s 값은 비어 있지 않은 문자열이어야 함" % key, key))
    return problems


def _unknowns(record):
    out = []
    for field in META_FIELDS:
        if record[field] is None:
            cand = record["auto_candidates"].get(field)
            reason = ("사람 확정 전. 표제란 자동 후보 %r" % cand["value"] if cand
                      else "미확인(표제란 자동 후보 없음, 사람 입력 없음)")
            out.append({"field": field, "reason": reason})
    return out


def _apply_meta(record, meta, actor, at):
    """사람 확정 입력을 반영하고 이력을 남긴다. 바뀐 필드 목록을 돌려준다."""
    changed = []
    by = (meta or {}).get("by") or actor
    reason = (meta or {}).get("reason") or "사람 확정 입력"
    for field in META_FIELDS:
        value = (meta or {}).get(field)
        if value is None or value == record[field]:
            continue
        record["history"].append({"at": at, "by": by, "action": "confirm_metadata", "field": field,
                                  "before": record[field], "after": value, "reason": reason})
        record[field] = value
        changed.append(field)
    return changed


def _result(record, outcome, path=None, notes=None):
    return {"outcome": outcome, "registration_file": path, "notes": notes or [], "record": record}


def _on_hold(project_id, material_type, source_path, problems):
    record = {"schema_version": SCHEMA_VERSION, "project_id": project_id, "material_id": None,
              "registration_version": None, "material_type": material_type, "status": "on_hold",
              "original_name": os.path.basename(source_path),
              "validation": {"status": "blocked", "blockers": problems, "unknowns": []}}
    return _result(record, "on_hold")


def _store_original(store, record, data):
    """원본 바이트를 storage_ref 위치에 새 파일로 저장하고 해시를 다시 확인한다. 문제 목록을 돌려준다."""
    dest = store.abs_ref(record["storage_ref"])
    if os.path.exists(dest):
        # 재시도: 이미 같은 내용이 있으면 그대로 쓰고, 다르면 덮어쓰지 않는다.
        if _file_sha(dest) == record["sha256"]:
            return []
        return [_problem("storage_conflict", "저장 위치에 다른 내용의 파일이 있어 덮어쓰지 않음: %s"
                         % record["storage_ref"], "storage_ref")]
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        _write_new(dest, data)  # 실패 시 정리는 _write_new가 자기가 만든 파일에 한해 한다
    except OSError as exc:
        return [_problem("storage_failed", "원본 저장 실패: %s" % exc, "storage_ref")]
    stored = _file_sha(dest)
    if stored != record["sha256"]:
        os.remove(dest)  # 방금 이 호출이 새로 만든(_write_new 성공) 잘못된 사본만 지워 재시도가 가능하게 한다
        return [_problem("stored_hash_mismatch", "저장 후 해시 불일치(입력 %s, 저장본 %s)"
                         % (record["sha256"][:12], stored[:12]), "sha256")]
    return []


def _finalize(store, index, record, problems, at, actor):
    record["validation"]["blockers"] = problems
    record["validation"]["status"] = "blocked" if problems else "passed"
    record["validation"]["unknowns"] = _unknowns(record)
    record["status"] = "failed" if problems else "registered"
    record["history"].append({"at": at, "by": actor,
                              "action": "storage_verified" if not problems else "storage_failed",
                              "reason": "; ".join(p["reason"] for p in problems) or None})
    path = _write_snapshot(store, record)
    entry = next(m for m in index["materials"] if m["material_id"] == record["material_id"])
    entry["status"] = record["status"]
    store.save_index(index)
    return path


def _without_times(record):
    rec = json.loads(json.dumps(record))
    for h in rec.get("history", []):
        h.pop("at", None)
    return rec


def _orphan_entry(store, material_id, sha):
    """색인에 없지만 registrations/<material_id>/에 같은 해시의 버전 파일이 있으면 색인 항목을 재구성한다."""
    folder = os.path.join(store.root, "registrations", material_id)
    if not os.path.isdir(folder):
        return None
    versions = {}
    for fname in os.listdir(folder):
        stem = fname[:-5] if fname.endswith(".json") else ""
        if stem.isdigit():
            versions[int(stem)] = _read_json(os.path.join(folder, fname))
    if not versions or any(r.get("sha256") != sha for r in versions.values()) or 1 not in versions:
        return None
    nums = sorted(versions)
    if nums != list(range(1, len(nums) + 1)):
        return None
    last = versions[nums[-1]]
    return {"material_id": material_id, "sha256": sha, "original_name": versions[1]["original_name"],
            "status": last["status"], "versions": nums}


def _unfinished_trace_only(store, material_id, sha):
    """registrations/<material_id>/가 없거나, 첫 스냅샷 교체(os.replace) 전에 중단된 이 원본의 흔적
    (빈 폴더 또는 *.json.tmp만 있고, 읽히는 .tmp는 같은 해시)만 있으면 True. 이어서 등록해도 된다
    (.tmp는 다음 _write_json이 같은 이름으로 다시 쓴다). 다른 해시의 흔적이나 버전 파일이 있으면 False."""
    folder = os.path.join(store.root, "registrations", material_id)
    if not os.path.exists(folder):
        return True
    if not os.path.isdir(folder):
        return False
    for fname in os.listdir(folder):
        if not fname.endswith(".json.tmp"):
            return False
        try:
            if _read_json(os.path.join(folder, fname)).get("sha256") != sha:
                return False
        except (OSError, ValueError):
            pass  # 쓰다 만(읽을 수 없는) 임시 파일: _write_json만 만드는 이름이므로 이 등록의 미완료 흔적으로 본다
    return True


def register(source_path, project_id, material_type="P&ID", store_root=None, metadata=None, actor=None,
             now=None):
    """draw.io 원본 1개를 등록한다. 원본 파일은 읽기만 한다.

    metadata: {"drawing_number", "design_revision", "title", "by", "reason"} 중 사람이 확정하는 값(없으면 None).
    반환: {"outcome": registered|reused|new_version|failed|on_hold, "registration_file", "notes", "record"}
    """
    store_root = store_root or DEFAULT_STORE
    actor = actor or getpass.getuser()
    at = (now or _now)()

    problems = _meta_problems(metadata)
    if not project_id or paths.safe_name(project_id) != project_id:
        problems.append(_problem("invalid_project_id",
                                 "프로젝트 ID 규칙(paths.safe_name과 같음): 비어 있지 않음, 글자(한글 포함)·숫자·'_'·'.'·'-'만, "
                                 "'.'·'_'로 시작·끝나지 않음, Windows 예약 이름(CON·NUL 등) 아님, 120자 이하: %r"
                                 % project_id, "project_id"))
    if material_type not in MATERIAL_TYPES:
        problems.append(_problem("unsupported_material_type", "MVP 자료 종류는 P&ID만: %r" % material_type,
                                 "material_type"))
    if problems:
        return _on_hold(project_id, material_type, source_path, problems)

    try:
        with open(source_path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        data, read_error = None, exc
    if data is None:
        rec = _on_hold(project_id, material_type, source_path,
                       [_problem("unreadable", "원본을 읽을 수 없음: %s" % read_error)])["record"]
        rec["status"] = "failed"
        return _result(rec, "failed")

    info = fileinfo.inspect(source_path, data)
    sha = sha256_of(data)
    if info["blockers"]:
        rec = _on_hold(project_id, material_type, source_path, info["blockers"])["record"]
        rec.update({"status": "failed", "format": info["format"], "size_bytes": info["size_bytes"],
                    "sha256": sha})
        return _result(rec, "failed")

    # 대소문자를 구분하지 않는 파일시스템(Windows 등)에서 'Alpha'와 'alpha'가 같은 폴더로 섞이지 않게 막는다.
    others = sorted(d for d in (os.listdir(store_root) if os.path.isdir(store_root) else [])
                    if d.lower() == project_id.lower() and d != project_id)
    store = Store(store_root, project_id)
    index = store.load_index(project_id)
    if others or index["project_id"] != project_id:
        return _on_hold(project_id, material_type, source_path, [_problem(
            "project_id_case_conflict", "대소문자만 다른 기존 프로젝트가 있음(%s). 같은 폴더로 섞이지 않게 보류"
            % ", ".join(others or [index["project_id"]]), "project_id")])
    entry = next((m for m in index["materials"] if m["sha256"] == sha), None)

    if entry is not None:
        latest = entry["versions"][-1]
        path = store.snapshot_path(entry["material_id"], latest)
        record = _read_json(path)
        if record["status"] != "registered":
            # 저장 실패·중단 후 재시도: 같은 자료 ID·버전으로 다시 저장한다(중복 등록 없음).
            _apply_meta(record, metadata, actor, at)
            record["history"].append({"at": at, "by": actor, "action": "retry", "reason": None})
            path = _finalize(store, index, record, _store_original(store, record, data), at, actor)
            return _result(record, record["status"], path, ["재시도: 기존 %s 버전 %d 사용"
                                                             % (record["material_id"], latest)])
        # 기존 등록 재사용: 보관 원본의 존재와 해시를 먼저 확인한다.
        stored = store.abs_ref(record["storage_ref"])
        notes = ["같은 프로젝트에 동일 원본 등록됨: %s 버전 %d" % (record["material_id"], latest)]
        if not os.path.isfile(stored):
            restore = _store_original(store, record, data)
            if not restore:
                notes.append("보관 원본이 없어 같은 내용으로 복구함")
        elif _file_sha(stored) != sha:
            restore = [_problem("stored_hash_mismatch", "보관 원본 해시가 등록정보와 다름(변조 의심). 덮어쓰지 않음",
                                "sha256")]
        else:
            restore = []
        if restore:
            # 완료된 버전 스냅샷은 불변이므로 실패는 색인(registry.json)에 기록하고, 반환 record도 실패로 맞춘다.
            entry["status"] = "failed"
            entry["problems"] = restore
            store.save_index(index)
            failed = json.loads(json.dumps(record))
            failed["status"] = "failed"
            failed["validation"]["status"] = "blocked"
            failed["validation"]["blockers"] = restore
            return _result(failed, "failed", path, notes + [p["reason"] for p in restore])
        if entry.get("status") != "registered":  # 이전 무결성 실패가 해소됨
            entry["status"] = "registered"
            entry.pop("problems", None)
            store.save_index(index)
            notes.append("보관 원본 무결성 재확인: 색인 상태를 registered로 복원")
        new = json.loads(json.dumps(record))
        if not _apply_meta(new, metadata, actor, at):
            return _result(record, "reused", path, notes)
        # 식별정보가 바뀌면 새 등록 버전(같은 원본·해시 사용). 이전 버전 파일은 그대로 둔다.
        new["registration_version"] = latest + 1
        new["validation"]["unknowns"] = _unknowns(new)
        path = store.snapshot_path(new["material_id"], new["registration_version"])
        if os.path.isfile(path):
            # 이전 실행이 버전 파일을 쓴 뒤 색인 갱신 전에 중단된 경우: 같은 내용이면 그 파일로 이어서 완료,
            # 다르면 덮어쓰지 않고 차단한다(시각만 다른 것은 같은 내용으로 본다).
            existing = _read_json(path)
            if _without_times(existing) != _without_times(new):
                failed = json.loads(json.dumps(new))
                failed["status"] = "failed"
                failed["validation"]["status"] = "blocked"
                failed["validation"]["blockers"] = [_problem(
                    "version_conflict", "색인에 없는 버전 파일 %d.json 이 다른 내용으로 이미 있음. 덮어쓰지 않음"
                    % new["registration_version"], "registration_version")]
                return _result(failed, "failed", path, notes)
            new = existing
            notes.append("중단된 버전 %d 저장을 이어서 완료" % new["registration_version"])
        else:
            path = _write_snapshot(store, new)
        entry["versions"].append(new["registration_version"])
        store.save_index(index)
        return _result(new, "new_version", path, notes)

    material_id = "material-" + sha[:12]
    orphan = _orphan_entry(store, material_id, sha)
    if orphan is not None and not any(m["material_id"] == material_id for m in index["materials"]):
        # 초안(등록정보 파일)은 썼지만 색인 저장 전에 중단된 같은 원본: 색인을 되살리고 이어서 처리한다.
        index["materials"].append(orphan)
        store.save_index(index)
        return register(source_path, project_id, material_type, store_root, metadata, actor, lambda: at)
    if (any(m["material_id"] == material_id for m in index["materials"])
            or not _unfinished_trace_only(store, material_id, sha)):
        # 다른 원본이 같은 자료 ID(해시 앞 12자리)를 이미 쓰고 있음: 덮어쓰지 않고 보류
        return _on_hold(project_id, material_type, source_path, [_problem(
            "id_collision", "자료 ID %s 가 다른 원본(해시 다름)에 이미 발급됨. 덮어쓰지 않고 보류" % material_id,
            "material_id")])
    record = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "material_id": material_id,
        "registration_version": 1,
        "material_type": material_type,
        "status": "draft",
        "format": info["format"],
        "original_name": os.path.basename(source_path),
        "input_path": _display_path(source_path),
        "storage_ref": "originals/%s/1/%s" % (material_id, os.path.basename(source_path)),
        "sha256": sha,
        "size_bytes": info["size_bytes"],
        "compressed": info["compressed"],
        "documents": [{"document_id": DOCUMENT_ID, "page_ids": [p["page_id"] for p in info["pages"]],
                       "pages": info["pages"]}],
        "drawing_number": None,
        "design_revision": None,
        "title": None,
        "auto_candidates": info["auto_candidates"],
        "registrar": {"name": REGISTRAR, "version": REGISTRAR_VERSION},
        "history": [{"at": at, "by": actor, "action": "register", "reason": None}],
        "validation": {"status": "passed", "blockers": [], "unknowns": []},
    }
    _apply_meta(record, metadata, actor, at)
    record["validation"]["unknowns"] = _unknowns(record)
    # 저장 전에 초안을 먼저 기록해 두면, 저장 중 중단되어도 재시도 시 같은 ID·버전을 찾는다.
    index["materials"].append({"material_id": material_id, "sha256": sha, "original_name": record["original_name"],
                               "status": "draft", "versions": [1]})
    _write_snapshot(store, record)
    store.save_index(index)
    path = _finalize(store, index, record, _store_original(store, record, data), at, actor)
    return _result(record, record["status"], path)


def load_for_extraction(registration_path):
    """등록정보 파일 -> (등록정보, 보관 원본 절대 경로). 등록 완료·해시 일치가 아니면 ValueError."""
    record = _read_json(registration_path)
    if record.get("status") != "registered" or record.get("validation", {}).get("status") != "passed":
        raise ValueError("등록 완료 상태가 아니어서 추출에 쓸 수 없음: status=%r" % record.get("status"))
    # registrations/<material_id>/<버전>.json -> 프로젝트 폴더
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(registration_path))))
    original = paths.safe_join(project_root, record["storage_ref"])
    if not os.path.isfile(original):
        raise ValueError("보관 원본 없음: %s" % record["storage_ref"])
    if _file_sha(original) != record["sha256"]:
        raise ValueError("보관 원본 해시가 등록정보와 다름: %s" % record["storage_ref"])
    return record, original
