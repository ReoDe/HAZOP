"""사람이 고친 기록을 담는 저장 파일의 공용 규칙: 지문, 원자적 쓰기, 백업, 번호 발급, 이력 한 줄. Qt 의존 없음.

검토구간·분석 결과·도면 수정·초기사건·AI 구간 검토 파일이 같은 함수로 쓰고 백업한다. 파일마다 다른 것은 문서 모양과
직렬화(키 정렬 여부)뿐이고 그것은 각 모듈이 정한다.

- 지문은 읽은 바이트에서 바로 구한다(read_bytes). 읽기와 지문을 따로 하면 그 사이에 바뀐 파일을 읽은 것으로 착각한다.
- 쓰기는 같은 폴더의 임시 파일에 쓰고 fsync한 뒤 os.replace로 바꾼다. 실패하면 임시 파일을 지우고, 프로세스가 죽어
  남은 임시 파일은 같은 파일을 다음에 쓸 때 지운다. expect를 주면 바꾸기 직전에 지문을 다시 보고 다르면 Conflict다.
  지문 확인과 교체 사이의 틈은 남는다. 그 틈에 다른 프로세스가 끼어드는 것은 단일 실행 잠금(app.startup)이 막는다.
- 백업은 이미 있는 백업 파일을 덮어쓰지 않는다.
"""

import hashlib
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone

from hazop import paths

ANY = object()
STALE_TEMP_SECONDS = 600


class Conflict(ValueError):
    """읽은 뒤 저장 파일이 바뀌어서 쓰지 않음."""


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- 지문·읽기

def fingerprint_of(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_bytes(path):
    """(바이트, 지문). 파일이 없으면 (None, None). 그 밖의 OSError는 그대로 올린다."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        return None, None
    return data, fingerprint_of(data)


def fingerprint(path):
    """파일 내용의 지문('sha256:<hex>'). 파일이 없으면 None."""
    return read_bytes(path)[1]


# ---------------------------------------------------------------- 쓰기

def dump_bytes(obj, sort_keys=True):
    """UTF-8, 들여쓰기 2, 줄끝 LF. sort_keys면 입력 dict의 키 순서와 무관하게 같은 바이트."""
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n").encode("utf-8")


def _temp_prefix(path):
    return ".%s." % os.path.basename(path)


def _sweep(path):
    """이 파일을 쓰다 죽은 프로세스가 남긴 임시 파일을 지운다. 지금 쓰는 중인 것을 건드리지 않게 오래된 것만 지운다."""
    folder, prefix = os.path.dirname(path), _temp_prefix(path)
    legacy = os.path.basename(path) + ".tmp"  # 0.2.0까지 쓰던 고정 이름
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name == legacy or (name.startswith(prefix) and name.endswith(".tmp")):
            full = os.path.join(folder, name)
            try:
                if time.time() - os.path.getmtime(full) > STALE_TEMP_SECONDS:
                    os.remove(full)
            except OSError:
                pass


def write_bytes(path, data, expect=ANY):
    """data를 path에 원자적으로 쓰고 새 지문을 돌려준다. expect(읽을 때 지문, 없던 파일이면 None)를 주면
    지금 파일의 지문이 다를 때 쓰지 않고 Conflict를 낸다."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    _sweep(path)
    fd, tmp = tempfile.mkstemp(prefix=_temp_prefix(path), suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if expect is not ANY and fingerprint(path) != expect:
            raise Conflict("읽은 뒤 저장 파일이 바뀜: %s" % path)
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return fingerprint_of(data)


def write_json(path, obj, expect=ANY, sort_keys=True):
    return write_bytes(path, dump_bytes(obj, sort_keys), expect)


# ---------------------------------------------------------------- 백업

def _copy_new(src, dst):
    with open(src, "rb") as a, open(dst, "xb") as b:
        shutil.copyfileobj(a, b)
    shutil.copystat(src, dst)


def backup(files, label, at=None):
    """files를 <작업 루트>/data/backup/<UTC 시각>-<label>/ 아래 paths.backup_rel 자리(작업 루트 안이면 원래 상대 경로,
    밖이면 _external/…)에 복사하고 백업 폴더를 돌려준다. 그 폴더에 같은 파일의 백업이 이미 있으면 -2, -3 …을 붙인
    폴더를 쓴다. 복사하지 못하면 OSError를 그대로 올린다(그때는 원본을 덮어쓰지 말 것)."""
    stamp = (at or now_utc()).replace(":", "").replace("-", "")
    root = paths.work_root()
    rels = [(p, paths.backup_rel(p, root)) for p in files]
    name, n = "%s-%s" % (stamp, label), 1
    while any(os.path.exists(paths.folder("backup", name, rel)) for _p, rel in rels):
        n += 1
        name = "%s-%s-%d" % (stamp, label, n)
    folder = paths.folder("backup", name)
    for p, rel in rels:
        dst = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        _copy_new(p, dst)
    return folder


def backup_file(path, label, at=None):
    """파일 하나를 backup으로 복사하고 복사본 경로를 돌려준다."""
    return os.path.join(backup([path], label, at), paths.backup_rel(path, paths.work_root()))


# ---------------------------------------------------------------- 번호·이력

def next_id(fmt, used):
    """fmt('S%d', 'c-%04d')의 다음 ID. used에는 지금 있는 ID와 지운 ID를 모두 넣는다(지운 번호를 다시 내지 않게).
    모양이 다른 ID는 세지 않는다."""
    head = fmt.split("%")[0]
    nums = [int(i[len(head):]) for i in map(str, used) if i.startswith(head) and i[len(head):].isdigit()]
    return fmt % (max(nums, default=0) + 1)


def history_row(op, fields=None, at=None):
    """이력 한 줄 {"at", "op", …fields}. 시각을 주지 않으면 지금(UTC, 초 단위)."""
    return dict({"at": at or now_utc(), "op": op}, **(fields or {}))
