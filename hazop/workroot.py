"""0.1.x 작업 폴더(한글 이름 배치)를 0.2.0 배치로 옮긴다(HZ-GOV-02 §5.6, §6.6).

옮기는 것은 hazop.paths의 옛 이름 표에 있는 최상위 폴더(데이터, 기호후보, 자료저장소, 출력)뿐이다. 작업 루트의 다른 폴더
(logs, cache, cli-run, 사용자가 둔 것)는 건드리지 않는다. 그 아래에서는 표에 있는 폴더만 새 이름이 되고, 표에 없는 것은
이름 그대로 따라간다(백업 폴더 안, 보관 폴더 안의 내용도 그대로다).

차례:
1. 옛 폴더의 파일을 <작업 루트>/_migrating-0.2.0/<새 이름> 아래로 복사한다.
2. 복사본을 다시 읽어 원본의 SHA-256과 견준다.
3. 복사본 폴더를 <작업 루트>/<새 이름>으로, 옛 폴더를 <작업 루트>/_before-0.2.0/<옛 이름>으로 이름만 바꾼다.
옛 내용은 지우지 않는다. 단계마다 <작업 루트>/_before-0.2.0/manifest.json에 적으므로 중간에 끊겨도 다시 돌리면 남은 일만 한다.
새 이름 폴더에 이미 파일이 있으면 덮어쓰지 않고 멈춘다. 되돌리기(undo)는 옛 폴더를 제자리로 돌리고, 복사본 가운데
옮긴 뒤로 바뀌지 않은 파일만 지운다. 옮긴 뒤에 생겼거나 바뀐 파일은 새 폴더에 그대로 남긴다.
링크·정션 폴더는 따라가지 않는다(그 안의 파일은 옛 폴더에만 남는다).
개발 작업 루트처럼 작업 루트 폴더 자체의 이름이 바뀌는 곳은 from_root로 옛 자리를 알려 주면 폴더 이름부터 바꾸고 시작한다.
"""

import datetime
import hashlib
import json
import os
import shutil
from typing import NamedTuple

from hazop import paths

TO_VERSION = "0.2.0"
KEEP_DIR = "_before-" + TO_VERSION
STAGING_DIR = "_migrating-" + TO_VERSION
MANIFEST = "manifest.json"
SPACE_MARGIN = 64 * 1024 * 1024


class MigrationError(Exception):
    """옮길 수 없어 멈췄다. 이미 한 단계는 manifest에 남아 있다."""


class Plan(NamedTuple):
    root: str
    state: str  # "none"(옛 폴더 없음) | "todo" | "resume"(하다 끊김) | "done" | "conflict"
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
    path = manifest_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _has_files(path):
    return any(files for _d, _dirs, files in os.walk(path))


def _walk(root, top):
    """(파일 상대 경로들, 폴더 상대 경로들) root 기준 '/' 구분, 이름순."""
    files, dirs = [], []
    for d, sub, names in os.walk(os.path.join(root, top)):
        sub.sort()
        rel = os.path.relpath(d, root).replace("\\", "/")
        dirs.append(rel)
        files += [rel + "/" + n for n in sorted(names)]
    return files, dirs


def _placed(root, top):
    """새 폴더가 제자리에 놓였는가. 놓은 직후 기록하기 전에 끊겼으면 기록은 없고 복사본 폴더만 사라져 있다."""
    return top["placed"] or (top["copied"] and os.path.isdir(os.path.join(root, top["new"]))
                             and not os.path.exists(os.path.join(root, STAGING_DIR, top["new"])))


def _kept(root, top):
    """옛 폴더가 보관 자리로 옮겨졌는가. 옮긴 직후 기록하기 전에 끊겼어도 디스크를 보고 안다."""
    return top["kept"] or (not os.path.exists(os.path.join(root, top["old"]))
                           and os.path.isdir(os.path.join(root, KEEP_DIR, top["old"])))


def make_plan(root):
    """디스크를 읽기만 한다."""
    root = os.path.abspath(root)
    doc = read_manifest(root)
    step = {t["old"]: t for t in (doc or {}).get("tops", ())}
    tops, files, dirs, conflicts = [], [], [], []
    for old, now in top_names():
        if not os.path.isdir(os.path.join(root, old)):
            continue
        tops.append((old, now))
        if os.path.exists(os.path.join(root, KEEP_DIR, old)):
            conflicts.append("옛 폴더 '%s'가 다시 생겼습니다. %s 안에 먼저 옮겨 둔 것이 있습니다." % (old, KEEP_DIR))
        placed = old in step and _placed(root, step[old])
        if not placed and os.path.exists(os.path.join(root, now)) and _has_files(os.path.join(root, now)):
            conflicts.append("새 폴더 '%s'에 이미 파일이 있습니다. 덮어쓰지 않습니다." % now)
        if placed:
            continue
        found, folders = _walk(root, old)
        files += [(rel, new_rel(rel), os.path.getsize(os.path.join(root, rel))) for rel in found]
        dirs += [new_rel(rel) for rel in folders]
    if conflicts:
        state = "conflict"
    elif tops:
        state = "resume" if doc else "todo"
    else:
        state = "done" if doc and doc.get("state") == "done" else "resume" if doc else "none"
    return Plan(root, state, tuple(tops), tuple(files), tuple(dirs), tuple(conflicts))


def _copy_verified(src, dst):
    """src를 dst로 복사하고 dst를 다시 읽어 견준다. 같은 내용이 이미 있으면 다시 쓰지 않는다. 원본의 SHA-256을 돌려준다."""
    want = _sha256(src)
    if not (os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src) and _sha256(dst) == want):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if _sha256(dst) != want:
            raise MigrationError("복사본이 원본과 다릅니다: %s" % dst)
    return want


def _remove_empty_tree(path):
    for d, _dirs, _files in os.walk(path, topdown=False):
        os.rmdir(d)


def move_root(old_root, new_root):
    """작업 루트 폴더의 이름을 바꾼다. 이미 바뀌어 있으면 아무것도 하지 않는다. 둘 다 있으면 멈춘다."""
    old_root, new_root = os.path.abspath(old_root), os.path.abspath(new_root)
    if os.path.isdir(old_root) and os.path.exists(new_root):
        raise MigrationError("옛 작업 루트와 새 작업 루트가 둘 다 있습니다. 덮어쓰지 않습니다: %s, %s" % (old_root, new_root))
    if os.path.isdir(old_root):
        os.rename(old_root, new_root)
    elif not os.path.isdir(new_root):
        raise MigrationError("작업 루트가 없습니다: %s" % old_root)


def apply(root, progress=None, from_root=None):
    """옮긴다. 다시 불러도 같은 끝 상태가 된다. manifest 경로를 돌려준다(옮길 것이 없었으면 None). 옮길 수 없으면 MigrationError.
    progress(끝낸 바이트, 전체 바이트)는 파일 하나를 복사할 때마다 불린다."""
    if from_root:
        move_root(from_root, root)
    plan = make_plan(root)
    root = plan.root
    if plan.state == "conflict":
        raise MigrationError(" ".join(plan.conflicts))
    if plan.state in ("none", "done"):
        return manifest_path(root) if plan.state == "done" else None
    free = shutil.disk_usage(root).free
    if free < plan.size + SPACE_MARGIN:
        raise MigrationError("디스크 여유가 모자랍니다. 복사에 %.1f MB가 필요한데 %.1f MB 남았습니다."
                             % ((plan.size + SPACE_MARGIN) / 1e6, free / 1e6))
    doc = read_manifest(root) or {"to_version": TO_VERSION, "started_at": _now(), "tops": [], "files": {}}
    doc["state"] = "copying"
    if from_root:
        doc["root_renamed_from"] = os.path.abspath(from_root)
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
                if os.path.isdir(new_dir):
                    _remove_empty_tree(new_dir)
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
        _remove_empty_tree(staging)
    doc["state"], doc["finished_at"] = "done", _now()
    _write_manifest(root, doc)
    return manifest_path(root)


def undo(root):
    """apply를 되돌린다(하다 끊긴 것도). 옛 폴더를 제자리로 돌리고, 복사본 가운데 그대로인 파일만 지운다.
    작업 루트 이름을 바꿨으면 그것도 되돌린다. {"restored": [옛 폴더], "left": [새 폴더에 남긴 파일의 상대 경로],
    "root": 되돌린 뒤의 작업 루트}를 돌려준다. 되돌릴 것이 없으면 MigrationError."""
    root = os.path.abspath(root)
    doc = read_manifest(root)
    if doc is None:
        raise MigrationError("옮긴 기록이 없습니다: %s" % manifest_path(root))
    kept = {top["old"] for top in doc["tops"] if _kept(root, top)}
    for old in sorted(kept):
        if os.path.exists(os.path.join(root, old)):
            raise MigrationError("옛 폴더 '%s' 자리에 이미 다른 것이 있습니다. 덮어쓰지 않습니다." % old)
    back = doc.get("root_renamed_from")
    if back and os.path.exists(back):
        raise MigrationError("옛 작업 루트 자리에 이미 다른 것이 있습니다. 덮어쓰지 않습니다: %s" % back)
    placed = {top["new"] for top in doc["tops"] if _placed(root, top)}
    copies = {f["new"]: f for f in doc["files"].values()}
    restored, left = [], []
    shutil.rmtree(os.path.join(root, STAGING_DIR), ignore_errors=True)
    for top in doc["tops"]:
        new_dir = os.path.join(root, top["new"])
        if top["new"] in placed and os.path.isdir(new_dir):
            found, _dirs = _walk(root, top["new"])
            for rel in found:
                full, copy = os.path.join(root, rel), copies.get(rel)
                if copy and os.path.getsize(full) == copy["size"] and _sha256(full) == copy["sha256"]:
                    os.remove(full)
                else:
                    left.append(rel)
            for d, _dirs, _files in os.walk(new_dir, topdown=False):
                if not os.listdir(d):
                    os.rmdir(d)
        if top["old"] in kept:
            os.rename(os.path.join(root, KEEP_DIR, top["old"]), os.path.join(root, top["old"]))
            restored.append(top["old"])
    os.remove(manifest_path(root))
    if os.path.exists(manifest_path(root) + ".tmp"):  # 기록을 쓰다 끊긴 자국
        os.remove(manifest_path(root) + ".tmp")
    if not os.listdir(os.path.join(root, KEEP_DIR)):
        os.rmdir(os.path.join(root, KEEP_DIR))
    if back:
        os.rename(root, back)
    return {"restored": restored, "left": left, "root": back or root}
