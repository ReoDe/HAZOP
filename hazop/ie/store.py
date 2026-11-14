"""⑥ 초기사건 저장 파일 읽기·쓰기. data/initiating-events/<프로젝트>.json. Qt 의존 없음.
P5(설계 §8.2): 같은 폴더의 <프로젝트>.fmea.json(FMEA 행, hazop.ie.fmea)과 <프로젝트>.mld.json(가져온 MLD, hazop.ie.mld)도 여기서 읽고 쓴다.

- 읽기는 utf-8-sig(BOM 허용). 모양 검사(model.problems)를 통과하지 못하면 Unreadable이고, 고치거나 옮기지 않는다.
- 저장은 읽은 뒤 파일이 바뀌었는지 지문으로 보고, 바뀌었으면 Conflict로 거절한다. 쓰기·지문·백업은 검토구간 등과 같은
  공용 규칙(hazop.store_io)을 쓴다.
- 읽지 못한 파일을 덮어쓰기 전에는 화면이 사람에게 묻고 backup으로 원본을 data/backup/<시각>-초기사건읽기실패/ 아래에 둔다.
"""

import json
import os

from hazop import paths, store_io
from hazop.ie import model
from hazop.store_io import Conflict, fingerprint, now_utc  # noqa: F401  이 모듈 이름으로도 쓴다

BACKUP_LABEL = "초기사건읽기실패"


class Unreadable(Exception):
    """JSON이 아니거나 종류·모양이 맞지 않는다. path, problems."""

    def __init__(self, path, problems):
        super().__init__("초기사건 파일을 읽을 수 없음: %s (%s)" % (path, "; ".join(problems[:3])))
        self.path, self.problems = path, problems


def store_path(project_id):
    return paths.folder("initiating-events", paths.safe_name(project_id or "프로젝트") + ".json")


def load(project_id):
    """(문서, 지문). 파일이 없으면 (빈 문서, None). 읽을 수 없으면 Unreadable."""
    path = store_path(project_id)
    data, fp = store_io.read_bytes(path)
    if data is None:
        return model.empty(project_id), None
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unreadable(path, ["JSON이 아님: %s" % exc]) from None
    bad = model.problems(doc)
    if bad:
        raise Unreadable(path, bad)
    return doc, fp


def save(doc, expect):
    """expect(읽을 때 지문, 없던 파일이면 None)와 지금 파일 지문이 다르면 Conflict. 모양이 틀린 문서는 쓰지 않는다
    (ValueError). 새 지문을 돌려준다."""
    bad = model.problems(doc)
    if bad:
        raise ValueError("초기사건 문서 형식 오류: %s" % "; ".join(bad[:3]))
    return store_io.write_json(store_path(doc["project_id"]), doc, expect)


def load_synced(project_id, results, node_set=None):
    """(⑤와 맞춘 문서, 지문). sync가 바꾼 것(새 후보의 IEC 번호, 확정 내리기)이 있으면 먼저 저장한다. 인계 묶음을 내보내기 전에
    부른다: 저장하지 않은 IEC 번호로 내보내면 뒤에 ⑤ 승인이 바뀌었을 때 같은 번호가 다른 원인에 붙는다(설계 §3 '다시 만들어도
    같은 IEC ID'). 한 번 준 번호는 그 원인이 승인에서 빠져도 문서에 남아 다시 쓰지 않는다. 저장하지 못하면 오류를 그대로 올린다
    (Conflict·ValueError·OSError): 그때는 내보내지 않는다."""
    doc, fp = load(project_id)
    try:   # FMEA 파일을 읽지 못하면 FMEA 출처 없이 맞춘다(그 사실은 묶음 '읽는 법'에 적힘, load_sides)
        fdoc = load_fmea(project_id)[0]
    except Unreadable:
        fdoc = None
    synced = sync_all(doc, results, node_set, fdoc)
    if synced is not doc:
        fp = save(synced, expect=fp)
    return synced, fp


def sync_all(doc, results, node_set, fmea_doc):
    """⑤와 맞추기(model.sync) + 승인 FMEA 행을 기본사건 후보의 출처로 붙이기(fmea.sync_basic_events). 할 일이 없으면 받은 문서."""
    from hazop.ie import fmea
    return fmea.sync_basic_events(model.sync(doc, results, node_set=node_set), fmea_doc)


# ---------------------------------------------------------------- P5: FMEA·MLD 파일

def _side_path(project_id, suffix):
    return paths.folder("initiating-events", paths.safe_name(project_id or "프로젝트") + suffix)


def fmea_path(project_id):
    return _side_path(project_id, ".fmea.json")


def mld_path(project_id):
    return _side_path(project_id, ".mld.json")


def _load_side(path, mod, project_id):
    data, fp = store_io.read_bytes(path)
    if data is None:
        return mod.empty(project_id), None
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unreadable(path, ["JSON이 아님: %s" % exc]) from None
    bad = mod.problems(doc)
    if bad:
        raise Unreadable(path, bad)
    return doc, fp


def load_fmea(project_id):
    """(FMEA 문서, 지문). 파일이 없으면 (빈 문서, None). 읽을 수 없으면 Unreadable."""
    from hazop.ie import fmea
    return _load_side(fmea_path(project_id), fmea, project_id)


def save_fmea(doc, expect):
    from hazop.ie import fmea
    bad = fmea.problems(doc)
    if bad:
        raise ValueError("FMEA 문서 형식 오류: %s" % "; ".join(bad[:3]))
    return store_io.write_json(fmea_path(doc["project_id"]), doc, expect)


def load_mld(project_id):
    """(MLD 저장 문서, 지문). 파일이 없으면 (빈 문서, None)."""
    from hazop.ie import mld
    return _load_side(mld_path(project_id), mld, project_id)


def load_sides(project_id):
    """(FMEA 문서 또는 None, MLD 저장 문서 또는 None, 읽지 못한 파일 이름 목록). 하나를 못 읽어도 나머지와 ⑥은 쓸 수 있게 한다."""
    out, bad = [], []
    for load_fn in (load_fmea, load_mld):
        try:
            out.append(load_fn(project_id)[0])
        except Unreadable as exc:
            out.append(None)
            bad.append(os.path.basename(exc.path))
    return out[0], out[1], bad


def replace_side_unreadable(project_id, which):
    """읽지 못한 FMEA(which='fmea')·MLD('mld') 파일을 백업한 뒤 빈 문서로 바꾼다. (새 지문, 백업 경로). 백업이 실패하면 쓰지 않는다.
    FMEA 행 번호는 원본 글에 보이는 가장 큰 FM 번호 다음부터 매겨 전에 낸 번호를 다시 쓰지 않는다."""
    import re
    from hazop.ie import fmea, mld
    path, mod, save_fn = {"fmea": (fmea_path(project_id), fmea, save_fmea), "mld": (mld_path(project_id), mld, save_mld)}[which]
    raw, expect = store_io.read_bytes(path)
    if raw is None:
        raise FileNotFoundError(path)
    saved = store_io.backup_file(path, BACKUP_LABEL + "-" + which, at=now_utc())
    doc = mod.empty(project_id)
    if which == "fmea":
        nums = [int(x) for x in re.findall(r"FM-(\d{3,})", raw.decode("utf-8", errors="replace"))]
        doc["counters"]["FM"] = max(nums, default=0)
    return save_fn(doc, expect=expect), saved


def save_mld(doc, expect):
    from hazop.ie import mld
    bad = mld.problems(doc)
    if bad:
        raise ValueError("MLD 문서 형식 오류: %s" % "; ".join(bad[:3]))
    return store_io.write_json(mld_path(doc["project_id"]), doc, expect)


def backup(project_id, label=BACKUP_LABEL):
    """지금 파일을 store_io.backup으로 복사하고 복사본 경로를 돌려준다(옛 백업을 덮어쓰지 않음).
    복사하지 못하면 OSError를 그대로 올린다(그때는 덮어쓰지 말 것)."""
    return store_io.backup_file(store_path(project_id), label, at=now_utc())


def replace_unreadable(project_id):
    """읽지 못한 파일을 백업한 뒤 빈 문서로 바꾼다. (빈 문서, 새 지문, 백업 경로). 백업이 실패하면 쓰지 않는다.
    지문은 백업 전에 잡으므로 백업 뒤에 파일이 바뀌면 Conflict다. 새 문서의 번호는 원본 글에 보이는 가장 큰 ID 다음부터라
    전에 낸 ID를 다시 내지 않는다(같은 항목의 옛 IEC 대응은 잃는다)."""
    raw, expect = store_io.read_bytes(store_path(project_id))
    if raw is None:
        raise FileNotFoundError(store_path(project_id))
    saved = backup(project_id)
    doc = model.empty(project_id, model.issued_numbers(raw.decode("utf-8", errors="replace")))
    return doc, save(doc, expect=expect), saved
