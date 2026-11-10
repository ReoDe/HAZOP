"""⑥ 초기사건 저장 파일 읽기·쓰기. 데이터/초기사건/<프로젝트>.json. Qt 의존 없음.

- 읽기는 utf-8-sig(BOM 허용). 모양 검사(model.problems)를 통과하지 못하면 Unreadable이고, 고치거나 옮기지 않는다.
- 저장은 읽은 뒤 파일이 바뀌었는지 지문(sha256)으로 보고, 바뀌었으면 Conflict로 거절한다. 같은 폴더 임시 파일에 쓰고
  fsync 뒤 os.replace로 바꾼다(실패하면 임시 파일을 지움).
- 읽지 못한 파일을 덮어쓰기 전에는 화면이 사람에게 묻고 backup으로 원본을 데이터/백업/<시각>-초기사건읽기실패/ 아래에 둔다.
검토구간 저장의 같은 방식(지문 비교·백업)을 따르되, 그 코드에 기대지 않고 여기서 따로 쓴다.
"""

import hashlib
import json
import os
import shutil
import tempfile

from hazop import paths
from hazop.ie import model
from hazop.kg.build import dump_bytes
from hazop.study.nodes import now_utc

BACKUP_LABEL = "초기사건읽기실패"


class Conflict(Exception):
    """읽은 뒤 파일이 바뀌었다(지문이 다름)."""


class Unreadable(Exception):
    """JSON이 아니거나 종류·모양이 맞지 않는다. path, problems."""

    def __init__(self, path, problems):
        super().__init__("초기사건 파일을 읽을 수 없음: %s (%s)" % (path, "; ".join(problems[:3])))
        self.path, self.problems = path, problems


def store_path(project_id):
    return paths.folder("initiating-events", paths.safe_name(project_id or "프로젝트") + ".json")


def fingerprint(path):
    """'sha256:<hex>'. 파일이 없으면 None."""
    try:
        with open(path, "rb") as fh:
            return "sha256:" + hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        return None


def load(project_id):
    """(문서, 지문). 파일이 없으면 (빈 문서, None). 읽을 수 없으면 Unreadable."""
    path = store_path(project_id)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        return model.empty(project_id), None
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unreadable(path, ["JSON이 아님: %s" % exc]) from None
    bad = model.problems(doc)
    if bad:
        raise Unreadable(path, bad)
    return doc, "sha256:" + hashlib.sha256(data).hexdigest()


def save(doc, expect):
    """expect(읽을 때 지문, 없던 파일이면 None)와 지금 파일 지문이 다르면 Conflict. 모양이 틀린 문서는 쓰지 않는다
    (ValueError). 새 지문을 돌려준다."""
    bad = model.problems(doc)
    if bad:
        raise ValueError("초기사건 문서 형식 오류: %s" % "; ".join(bad[:3]))
    path = store_path(doc["project_id"])
    if fingerprint(path) != expect:
        raise Conflict("초기사건 파일이 읽은 뒤 바뀌었습니다: %s" % path)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    data = dump_bytes(doc)
    fd, tmp = tempfile.mkstemp(prefix=".hazop-ie-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def backup(project_id, label=BACKUP_LABEL):
    """지금 파일을 데이터/백업/<UTC 시각>-<label>/<작업 루트 기준 경로>로 복사한다. 백업 경로를 돌려준다.
    복사하지 못하면 OSError를 그대로 올린다(그때는 덮어쓰지 말 것).
    같은 시각 폴더가 이미 있으면 -2, -3 …을 붙여 옛 백업을 덮어쓰지 않는다."""
    path = store_path(project_id)
    stamp = now_utc().replace(":", "").replace("-", "")
    rel = paths.backup_rel(path, paths.work_root())
    folder, n = "%s-%s" % (stamp, label), 1
    while os.path.exists(paths.folder("backup", folder)):
        n += 1
        folder = "%s-%s-%d" % (stamp, label, n)
    dst = paths.folder("backup", folder, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(path, dst)
    return dst


def replace_unreadable(project_id):
    """읽지 못한 파일을 백업한 뒤 빈 문서로 바꾼다. (빈 문서, 새 지문, 백업 경로). 백업이 실패하면 쓰지 않는다.
    지문은 백업 전에 잡으므로 백업 뒤에 파일이 바뀌면 Conflict다. 새 문서의 번호는 원본 글에 보이는 가장 큰 ID 다음부터라
    전에 낸 ID를 다시 내지 않는다(같은 항목의 옛 IEC 대응은 잃는다)."""
    path = store_path(project_id)
    with open(path, "rb") as fh:
        raw = fh.read()
    expect = "sha256:" + hashlib.sha256(raw).hexdigest()
    saved = backup(project_id)
    doc = model.empty(project_id, model.issued_numbers(raw.decode("utf-8", errors="replace")))
    return doc, save(doc, expect=expect), saved
