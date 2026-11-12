"""0.1.x 작업 폴더(한글 이름 배치)를 0.2.0 배치로 옮긴다(HZ-GOV-02 §5.6, §6.6).

옮기는 것은 hazop.paths의 옛 이름 표에 있는 최상위 폴더(데이터, 기호후보, 자료저장소, 출력)뿐이다. 작업 루트의 다른 폴더
(logs, cache, cli-run, 사용자가 둔 것)는 건드리지 않는다. 그 아래에서는 표에 있는 폴더만 새 이름이 되고, 표에 없는 것은
이름 그대로 따라간다(백업 폴더 안, 보관 폴더 안의 내용도 그대로다).

차례:
1. 옛 폴더의 파일을 <작업 루트>/_migrating-0.2.0/<새 이름> 아래로 복사한다.
2. 복사본을 다시 읽어 원본의 SHA-256과 견준다.
3. 복사본 폴더를 <작업 루트>/<새 이름>으로, 옛 폴더를 <작업 루트>/_before-0.2.0/<옛 이름>으로 이름만 바꾼다.
옛 내용은 지우지 않는다. 단계마다 <작업 루트>/_before-0.2.0/manifest.json에 적으므로 중간에 끊겨도 다시 돌리면 남은 일만 한다.

옮기지 않고 멈추는 경우(무엇 때문인지 목록을 댄다):
- 새 이름 폴더에 이미 파일이 있다.
- 서로 다른 옛 파일이나 폴더가 같은 새 자리로 간다(데이터/regions와 데이터/구간, 대소문자만 다른 이름).
- 옛 폴더나 임시 폴더에 심볼릭 링크·정션이 있다. 따라가지 않는다. 링크 너머를 복사하거나 덮어쓰지 않으려는 것이다.
- 읽지 못하는 폴더가 있다. 빠뜨린 채 끝내지 않는다.
- 디스크 여유가 모자란다.

되돌리기(undo)는 옛 폴더를 제자리로 돌리고, 이 도구가 만든 복사본 가운데 기록한 해시와 같은 파일만 지운다. 옮긴 뒤에 생겼거나
바뀐 파일, 임시 폴더에 남이 둔 파일은 그대로 남기고 목록으로 돌려준다. 되돌리기도 단계마다 기록해서 끊기면 다시 돌려 끝낸다.
개발 작업 루트처럼 작업 루트 폴더 자체의 이름이 바뀌는 곳은 from_root로 옛 자리를 알려 주면 폴더 이름부터 바꾸고 시작한다.
폴더 이름 바꾸기는 같은 드라이브 안에서만 된다.
"""

import collections
import datetime
import hashlib
import json
import os
import shutil
from typing import NamedTuple

from hazop import paths, store_io

TO_VERSION = "0.2.0"
KEEP_DIR = "_before-" + TO_VERSION
STAGING_DIR = "_migrating-" + TO_VERSION
MANIFEST = "manifest.json"
SPACE_MARGIN = 64 * 1024 * 1024
CONFLICT_LIST = 10  # 멈춘 까닭에 적는 파일 수


class MigrationError(Exception):
    """옮길 수 없어 멈췄다. 이미 한 단계는 manifest에 남아 있다."""


class Plan(NamedTuple):
    root: str
    state: str  # "none"(옛 폴더 없음) | "todo" | "resume"(하다 끊김) | "done" | "conflict" | "undoing"(되돌리다 끊김)
    tops: tuple  # ((옛 최상위 이름, 새 최상위 이름), …) 아직 옮길 것
    files: tuple  # ((옛 상대 경로, 새 상대 경로, 크기), …)
    dirs: tuple  # 새 상대 경로. 빈 폴더도 따라가게 한다
    conflicts: tuple  # 멈춘 까닭

    @property
    def size(self):
        return sum(f[2] for f in self.files)


def top_names():
    """[(옛 최상위 폴더, 새 최상위 폴더)]"""
    return sorted({(old.split("/")[0], now.split("/")[0]) for now, old in paths.work_names()})


def new_rel(old_rel):
    """0.1.x 상대 경로가 0.2.0에서 놓일 상대 경로('/' 구분)."""
    return paths._swap_prefix(old_rel, [(old, now) for now, old in paths.work_names()])


def manifest_path(root):
    return os.path.join(root, KEEP_DIR, MANIFEST)


def read_manifest(root):
    try:
        with open(manifest_path(root), encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def _write_manifest(root, doc):
    # 지문 충돌 확인은 하지 않는다. 이전 기록은 옮기는 한 프로세스가 작업 루트 잠금을 쥐고 단계마다 고쳐 쓴다
    store_io.write_json(manifest_path(root), doc, sort_keys=False)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_link(path):
    return os.path.islink(path) or getattr(os.path, "isjunction", lambda p: False)(path)


def _unreadable(err):
    raise MigrationError("읽지 못하는 폴더가 있습니다. 빠뜨리고 옮기지 않습니다: %s (%s)" % (err.filename, err.strerror or err))


def _walk(root, top):
    """(파일 상대 경로들, 폴더 상대 경로들, 링크·정션 상대 경로들) root 기준 '/' 구분, 이름순. 링크는 따라가지 않는다.
    읽지 못하는 폴더가 있으면 MigrationError."""
    files, dirs, links = [], [], []
    start = os.path.join(root, top)
    if _is_link(start):
        return files, dirs, [top.replace("\\", "/")]
    for d, sub, names in os.walk(start, onerror=_unreadable):
        rel = os.path.relpath(d, root).replace("\\", "/")
        dirs.append(rel)
        for name in sorted(sub):
            if _is_link(os.path.join(d, name)):
                links.append(rel + "/" + name)
                sub.remove(name)
        sub.sort()
        for name in sorted(names):
            (links if _is_link(os.path.join(d, name)) else files).append(rel + "/" + name)
    return files, dirs, links


def _some(names):
    return ", ".join(names[:CONFLICT_LIST]) + (" 외 %d개" % (len(names) - CONFLICT_LIST) if len(names) > CONFLICT_LIST else "")


def _placed(root, top):
    """새 폴더가 제자리에 놓였는가. 놓은 직후 기록하기 전에 끊겼으면 기록은 없고 복사본 폴더만 사라져 있다."""
    return top["placed"] or (top["copied"] and os.path.isdir(os.path.join(root, top["new"]))
                             and not os.path.exists(os.path.join(root, STAGING_DIR, top["new"])))


def _kept(root, top):
    """옛 폴더가 보관 자리에 있는가. 옮긴 직후나 되돌린 직후 기록하기 전에 끊겼어도 디스크를 보고 안다."""
    return os.path.isdir(os.path.join(root, KEEP_DIR, top["old"])) and not os.path.exists(os.path.join(root, top["old"]))


def _same_place(sources):
    """{새 자리(소문자): [옛 경로…]} 가운데 옛 경로가 둘 이상인 것. 대소문자를 가리지 않는 파일 시스템에서 하나만 남는 짝이다."""
    return {new: olds for new, olds in sources.items() if len(olds) > 1}


def make_plan(root):
    """디스크를 읽기만 한다. 읽지 못하는 폴더가 있으면 MigrationError."""
    root = os.path.abspath(root)
    doc = read_manifest(root)
    if doc and doc.get("state") == "undoing":
        return Plan(root, "undoing", (), (), (), ("되돌리다 끊긴 작업 루트입니다. 되돌리기를 다시 돌려 끝낸 뒤에 옮깁니다.",))
    step = {t["old"]: t for t in (doc or {}).get("tops", ())}
    tops, files, dirs, conflicts = [], [], [], []
    staging = os.path.join(root, STAGING_DIR)
    if os.path.lexists(staging):
        links = _walk(root, STAGING_DIR)[2]
        if links:
            conflicts.append("임시 폴더에 링크·정션이 있습니다. 링크 너머에 쓰지 않습니다: %s" % _some(links))
    file_at, dir_at = collections.defaultdict(list), collections.defaultdict(list)
    for old, now in top_names():
        if not os.path.isdir(os.path.join(root, old)):
            continue
        tops.append((old, now))
        if os.path.exists(os.path.join(root, KEEP_DIR, old)):
            conflicts.append("옛 폴더가 다시 생겼습니다: %s. %s 안에 먼저 옮겨 둔 같은 이름의 폴더가 있습니다. "
                             "둘을 견주어 하나를 다른 곳으로 옮기세요." % (old, KEEP_DIR))
        elif old in step and step[old]["kept"]:
            # 옛 폴더가 디스크에 있으면 기록이 뭐라 하든 아직 옮기지 않은 것이다. 기록은 '옮겼다'인데 폴더가 제자리에 있으면
            # (손으로 돌려놓았거나 되돌리기가 기록을 못 고치고 끊겼다) 새 폴더와 어느 쪽이 맞는지 도구가 정할 수 없다
            conflicts.append("옛 폴더가 제자리에 다시 있습니다: %s. 옮겼다는 기록과 맞지 않습니다. 새 폴더 '%s'와 견주어 "
                             "쓰지 않을 쪽을 다른 곳으로 옮기세요." % (old, now))
        placed = old in step and _placed(root, step[old])
        if not placed and os.path.lexists(os.path.join(root, now)):
            there, _dirs, links = _walk(root, now)
            if there or links:
                conflicts.append("새 폴더 '%s'에 이미 파일이 %d개 있습니다. 덮어쓰지 않습니다: %s"
                                 % (now, len(there) + len(links), _some(there + links)))
        if placed:
            continue
        found, folders, links = _walk(root, old)
        if links:
            conflicts.append("옛 폴더 '%s'에 링크·정션이 있습니다. 따라가지 않고 멈춥니다: %s" % (old, _some(links)))
        for rel in found:
            files.append((rel, new_rel(rel), os.path.getsize(os.path.join(root, rel))))
            file_at[files[-1][1].lower()].append(rel)
        for rel in folders:
            dirs.append(new_rel(rel))
            dir_at[dirs[-1].lower()].append(rel)
    clash = sorted(old for olds in list(_same_place(file_at).values()) + list(_same_place(dir_at).values()) for old in olds)
    clash += sorted(old for new, olds in file_at.items() if new in dir_at for old in olds + dir_at[new])
    if clash:
        conflicts.append("서로 다른 옛 파일·폴더가 같은 새 자리로 갑니다. 하나를 잃지 않게 멈춥니다: %s" % _some(clash))
    if os.path.isdir(staging):
        # 임시 폴더에는 이번에 복사할 파일만 있어야 한다. 끊긴 뒤 옛 폴더에서 지운 파일의 복사본이나 남이 둔 파일이
        # 새 폴더로 딸려 들어가지 않게 멈춘다
        waiting = {t[1] for t in tops if not (t[0] in step and _placed(root, step[t[0]]))}
        planned = {f[1].lower() for f in files}
        stray = [rel[len(STAGING_DIR) + 1:] for rel in _walk(root, STAGING_DIR)[0]]
        stray = [rel for rel in stray if rel.lower() not in planned and (rel.split("/")[0] in waiting or not tops)]
        if stray:
            conflicts.append("임시 폴더 %s에 이번에 옮길 목록에 없는 파일이 있습니다. 확인해 지우거나 다른 곳으로 옮기세요: %s"
                             % (STAGING_DIR, _some([STAGING_DIR + "/" + rel for rel in stray])))
    if conflicts:
        state = "conflict"
    elif tops:
        state = "resume" if doc else "todo"
    else:
        state = "done" if doc and doc.get("state") == "done" else "resume" if doc else "none"
    return Plan(root, state, tuple(tops), tuple(files), tuple(dirs), tuple(conflicts))


def _copy_verified(src, dst):
    """src를 dst로 복사하고 dst를 다시 읽어 견준다. 같은 내용이 이미 있으면 다시 쓰지 않는다. 원본의 SHA-256을 돌려준다.
    dst가 링크면 쓰지 않는다(링크가 가리키는 파일을 덮어쓰게 된다)."""
    if os.path.lexists(dst) and _is_link(dst):
        raise MigrationError("임시 폴더의 파일이 링크입니다. 쓰지 않습니다: %s" % dst)
    want = _sha256(src)
    if not (os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src) and _sha256(dst) == want):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if _sha256(dst) != want:
            raise MigrationError("복사본이 원본과 다릅니다: %s" % dst)
    return want


def _remove_empty_dirs(path):
    """path 아래(자신 포함)의 빈 폴더만 지운다. 파일이 든 폴더는 남는다."""
    for d, _dirs, _files in os.walk(path, topdown=False):
        if not os.listdir(d):
            os.rmdir(d)


def move_root(old_root, new_root):
    """작업 루트 폴더의 이름을 바꾼다. 이미 바뀌어 있으면 아무것도 하지 않는다. 둘 다 있으면 멈춘다."""
    old_root, new_root = os.path.abspath(old_root), os.path.abspath(new_root)
    if os.path.isdir(old_root) and os.path.exists(new_root):
        raise MigrationError("옛 작업 루트와 새 작업 루트가 둘 다 있습니다. 덮어쓰지 않습니다: %s, %s" % (old_root, new_root))
    if os.path.isdir(old_root):
        try:
            os.rename(old_root, new_root)
        except OSError as e:
            raise MigrationError("작업 루트 폴더의 이름을 바꾸지 못했습니다(같은 드라이브 안에서만 됩니다): %s → %s (%s)"
                                 % (old_root, new_root, e))
    elif not os.path.isdir(new_root):
        raise MigrationError("작업 루트가 없습니다: %s" % old_root)


def apply(root, progress=None, from_root=None):
    """옮긴다. 다시 불러도 같은 끝 상태가 된다. manifest 경로를 돌려준다(옮길 것이 없었으면 None). 옮길 수 없으면 MigrationError.
    progress(끝낸 바이트, 전체 바이트)는 파일 하나를 복사할 때마다 불린다."""
    root = os.path.abspath(root)
    if from_root:
        renamed_now = os.path.isdir(os.path.abspath(from_root))
        move_root(from_root, root)
        doc = read_manifest(root) or {"to_version": TO_VERSION, "started_at": _now(), "state": "renamed", "tops": [], "files": {}}
        if doc.get("root_renamed_from") != os.path.abspath(from_root) and doc.get("state") != "undoing":
            doc["root_renamed_from"] = os.path.abspath(from_root)
            try:
                _write_manifest(root, doc)  # 뒤에서 멈춰도 되돌리기가 원래 자리를 안다
            except OSError:
                # 원래 자리를 적지 못했다. 이름만 바뀐 채 남으면 되돌리기가 원래 자리를 모르므로 방금 바꾼 이름을 되돌린다
                if renamed_now and not os.path.exists(os.path.abspath(from_root)):
                    store_io.remove_temps(manifest_path(root))
                    try:
                        os.rmdir(os.path.dirname(manifest_path(root)))
                    except OSError:
                        pass
                    os.rename(root, os.path.abspath(from_root))
                raise
    plan = make_plan(root)
    if plan.state in ("conflict", "undoing"):
        raise MigrationError(" ".join(plan.conflicts))
    if plan.state in ("none", "done"):
        return manifest_path(root) if plan.state == "done" else None
    free = shutil.disk_usage(root).free
    if free < plan.size + SPACE_MARGIN:
        raise MigrationError("디스크 여유가 모자랍니다. 복사에 %.1f MB가 필요한데 %.1f MB 남았습니다."
                             % ((plan.size + SPACE_MARGIN) / 1e6, free / 1e6))
    doc = read_manifest(root) or {"to_version": TO_VERSION, "started_at": _now(), "tops": [], "files": {}}
    doc["state"] = "copying"
    known = {t["old"] for t in doc["tops"]}
    doc["tops"] += [{"old": old, "new": now, "copied": False, "placed": False, "kept": False}
                    for old, now in plan.tops if old not in known]
    for top in doc["tops"]:
        top["placed"] = _placed(root, top)
    _write_manifest(root, doc)

    staging = os.path.join(root, STAGING_DIR)
    for rel in plan.dirs:
        os.makedirs(os.path.join(staging, rel), exist_ok=True)
    done = 0
    for old, now, size in plan.files:
        sha = _copy_verified(os.path.join(root, old), os.path.join(staging, now))
        doc["files"][old] = {"new": now, "size": size, "sha256": sha}
        done += size
        if progress:
            progress(done, plan.size)
    for top in doc["tops"]:
        top["copied"] = True
    _write_manifest(root, doc)

    for top in doc["tops"]:
        old_dir, new_dir = os.path.join(root, top["old"]), os.path.join(root, top["new"])
        staged = os.path.join(staging, top["new"])
        if not top["placed"]:
            if os.path.isdir(staged):
                if os.path.isdir(new_dir):  # 파일 없는 폴더뿐이다(계획에서 확인). 그 빈 폴더들도 따라가게 한 뒤 자리를 비운다
                    for d, _dirs, _files in os.walk(new_dir):
                        os.makedirs(os.path.join(staged, os.path.relpath(d, new_dir)), exist_ok=True)
                    _remove_empty_dirs(new_dir)
                os.rename(staged, new_dir)
            elif not os.path.isdir(new_dir):
                raise MigrationError("복사본 폴더가 없습니다: %s" % staged)
            top["placed"] = True
            _write_manifest(root, doc)
        if not top["kept"]:
            if os.path.isdir(old_dir):
                os.rename(old_dir, os.path.join(root, KEEP_DIR, top["old"]))
            top["kept"] = True
            _write_manifest(root, doc)
    if os.path.isdir(staging):
        _remove_empty_dirs(staging)
    doc["state"], doc["finished_at"] = "done", _now()
    _write_manifest(root, doc)
    return manifest_path(root)


def _remove_copies(root, top, is_copy, left):
    """root/top 아래에서 is_copy(상대 경로, 전체 경로)가 참인 파일만 지우고 빈 폴더를 지운다. 나머지는 left에 적는다."""
    base = os.path.join(root, top)
    if _is_link(base):
        left.append(top.replace("\\", "/"))
        return
    if not os.path.isdir(base):
        return
    found, _dirs, links = _walk(root, top)
    left += links
    for rel in found:
        full = os.path.join(root, rel)
        if is_copy(rel, full):
            os.chmod(full, 0o666)  # 읽기 전용 속성까지 복사된 파일도 지운다
            os.remove(full)
        else:
            left.append(rel)
    _remove_empty_dirs(base)


def undo(root, before_rename=None):
    """apply를 되돌린다(하다 끊긴 것도, 되돌리다 끊긴 것도). 옛 폴더를 제자리로 돌리고, 이 도구가 만든 복사본 가운데 기록한
    해시(기록 전이면 원본)와 같은 파일만 지운다. 작업 루트 이름을 바꿨으면 그것도 되돌린다. before_rename()은 작업 루트 이름을
    되돌리기 바로 앞에 불린다(쥐고 있던 잠금 파일을 놓을 자리).
    {"restored": [옛 폴더], "left": [남긴 파일의 상대 경로], "root": 되돌린 뒤의 작업 루트}를 돌려준다.
    되돌릴 것이 없으면 MigrationError."""
    root = os.path.abspath(root)
    doc = read_manifest(root)
    keep = os.path.join(root, KEEP_DIR)
    if doc is None and os.path.isdir(keep) and not os.listdir(keep):  # 기록을 지운 직후 끊겼다. 빈 보관 폴더만 남았다
        os.rmdir(keep)
        return {"restored": [], "left": [], "root": root}
    if doc is None:
        raise MigrationError("옮긴 기록이 없습니다: %s" % manifest_path(root))
    for top in doc["tops"]:
        if os.path.exists(os.path.join(root, top["old"])) and os.path.exists(os.path.join(root, KEEP_DIR, top["old"])):
            raise MigrationError("옛 폴더 '%s' 자리에 이미 다른 것이 있습니다. 덮어쓰지 않습니다." % top["old"])
    back = doc.get("root_renamed_from")
    if back and os.path.normcase(back) == os.path.normcase(root):
        back = None  # 이름을 되돌린 뒤 끊겼다. 남은 것은 기록 정리뿐이다
    if back and os.path.exists(back):
        raise MigrationError("옛 작업 루트 자리에 이미 다른 것이 있습니다. 덮어쓰지 않습니다: %s" % back)
    doc["state"] = "undoing"
    _write_manifest(root, doc)

    copies = {f["new"]: f for f in doc["files"].values()}
    restored, left = [], []

    def recorded(rel, full):
        copy = copies.get(rel)
        return bool(copy) and os.path.getsize(full) == copy["size"] and _sha256(full) == copy["sha256"]

    # 임시 폴더: 기록에 있으면 기록한 해시와, 기록 전에 끊겼으면 아직 제자리에 있는 원본과 견준다
    sources = {}
    for top in doc["tops"]:
        if os.path.isdir(os.path.join(root, top["old"])):
            sources.update((new_rel(rel), rel) for rel in _walk(root, top["old"])[0])

    def staged_copy(rel, full):
        inner = rel[len(STAGING_DIR) + 1:]
        if inner in copies:
            return recorded(inner, full)
        src = sources.get(inner)
        return bool(src) and _sha256(full) == _sha256(os.path.join(root, src))

    _remove_copies(root, STAGING_DIR, staged_copy, left)
    for top in doc["tops"]:
        if _placed(root, top):
            _remove_copies(root, top["new"], recorded, left)
        if _kept(root, top):
            os.rename(os.path.join(root, KEEP_DIR, top["old"]), os.path.join(root, top["old"]))
        if os.path.isdir(os.path.join(root, top["old"])):
            restored.append(top["old"])
    if back:
        if before_rename:
            before_rename()
        try:
            os.rename(root, back)
        except OSError as e:
            raise MigrationError("작업 루트 폴더의 이름을 되돌리지 못했습니다. 되돌리기를 다시 돌리면 이어서 합니다: %s → %s (%s)"
                                 % (root, back, e))
        root = back
    # 기록은 맨 끝에 지운다. 그 앞에서 끊기면 다시 돌려 끝낸다. 기록을 쓰다 끊겨 남은 임시 파일도 함께 지운다
    # (남아 있으면 보관 폴더가 비지 않아 지워지지 않는다). 작업 루트 잠금을 쥔 프로세스 하나만 쓰므로 나이를 보지 않는다
    store_io.remove_temps(manifest_path(root))
    if os.path.exists(manifest_path(root)):
        os.remove(manifest_path(root))
    if not os.listdir(os.path.join(root, KEEP_DIR)):
        os.rmdir(os.path.join(root, KEEP_DIR))
    return {"restored": restored, "left": left, "root": root}
