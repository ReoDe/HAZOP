"""패키징 W4: 저장소 밖 빌드용 스냅숏을 만든다(다른 트랙이 진행 중인 파일을 HEAD 내용으로 되돌림).

사용(저장소 루트에서): python packaging/make_snapshot.py --dest <저장소 밖 새 폴더> \
    [--restore-head <경로> ...] [--overlay <미추적 경로> ...]
- git ls-files의 추적 파일을 작업 트리 디스크 바이트 그대로 복사한다(줄 끝 변환 없음: 고정 해시·graph_version 보존).
  작업 트리에서 지워진 추적 파일은 건너뛴다.
- --restore-head: 그 파일은 작업 트리 대신 `git show HEAD:<경로>` 바이트로 쓴다(진행 중인 다른 트랙 변경 제외).
- --overlay: 추적되지 않은 파일(이번 작업의 새 파일)을 디스크에서 추가로 복사한다. 추적 파일을 넣으면 거부한다.
- 두 옵션의 경로는 정규화한다(normalize_rel): 절대 경로·'./'·'../' 우회·저장소 밖 realpath는 거부하고, 추적 여부는
  정규화한 상대 경로로 비교한다. 쓰는 위치도 목적지 안인지 commonpath로 확인한다(dest_path).
- 그 밖의 미추적 파일(예: 참고자료/ 아래 미추적 폴더)은 복사하지 않는다.
- <dest>/SNAPSHOT.json: HEAD 커밋, 파일별 {path, sha256, source: disk|head|overlay}. 표준 출력에 개수와 목록 해시를 쓴다.
dest는 없거나 빈 폴더여야 하고 저장소 밖이어야 한다.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args):
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=REPO_ROOT, capture_output=True,
                          check=True).stdout


def inside(path, root):
    a, b = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def normalize_rel(path, repo=REPO_ROOT):
    """저장소 상대 경로를 정규화해 '/' 구분으로 돌려준다. 절대 경로·드라이브·'./'·'../'·'..' 조각, 그리고
    realpath가 저장소 밖(링크 포함)이면 ValueError."""
    raw = str(path or "")
    p = raw.replace("\\", "/")
    parts = p.split("/")
    if not p or os.path.isabs(raw) or os.path.splitdrive(raw)[0] or p.startswith("/") \
            or any(x in ("", ".", "..") for x in parts):
        raise ValueError("저장소 상대 경로가 아님: %r" % raw)
    real = os.path.realpath(os.path.join(repo, *parts))
    if not inside(real, repo) or os.path.normcase(real) == os.path.normcase(os.path.realpath(repo)):
        raise ValueError("저장소 밖 경로: %r" % raw)
    rel = os.path.relpath(real, os.path.realpath(repo)).replace("\\", "/")
    if os.path.normcase(rel) != os.path.normcase(p):
        raise ValueError("정규화 결과가 다름(링크 등): %r -> %r" % (raw, rel))
    return rel


def dest_path(dest, rel):
    """목적지 안 경로. realpath가 목적지 밖이면 ValueError."""
    out = os.path.realpath(os.path.join(dest, *rel.split("/")))
    if not inside(out, dest):
        raise ValueError("목적지 밖 경로: %r" % rel)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--restore-head", nargs="*", default=[])
    ap.add_argument("--overlay", nargs="*", default=[])
    args = ap.parse_args(argv)
    dest = os.path.abspath(args.dest)
    if inside(dest, REPO_ROOT) or inside(REPO_ROOT, dest):
        print("중단: 저장소와 겹치는 경로: %s" % dest)
        return 2
    if os.path.isdir(dest) and os.listdir(dest):
        print("중단: 비어 있지 않은 폴더: %s" % dest)
        return 2
    try:  # 경로 검사는 git을 부르기 전에 한다
        restore = [normalize_rel(p) for p in args.restore_head]
        overlay = [normalize_rel(p) for p in args.overlay]
    except ValueError as e:
        print("중단: %s" % e)
        return 2
    tracked = [f for f in git("ls-files", "-z").decode("utf-8").split("\0") if f]
    tset = set(tracked)
    tnorm = {os.path.normcase(t) for t in tset}
    bad = [p for p in restore if os.path.normcase(p) not in tnorm]
    bad += [p for p in overlay if os.path.normcase(p) in tnorm or not os.path.isfile(os.path.join(REPO_ROOT, p))]
    if bad:
        print("중단: --restore-head는 추적 파일, --overlay는 존재하는 미추적 파일이어야 함: %s" % bad)
        return 2
    # 대소문자만 다른 경로도 Git의 정확한 경로로 맞춘다(Windows normcase 비교와 같은 키를 씀)
    exact = {os.path.normcase(t): t for t in tset}
    restore = [exact[os.path.normcase(p)] for p in restore]
    rkeys = {os.path.normcase(p) for p in restore}
    head = git("rev-parse", "HEAD").decode().strip()
    entries = []
    for rel in tracked + overlay:
        src = os.path.join(REPO_ROOT, *rel.split("/"))
        if not inside(src, REPO_ROOT):  # 추적 파일이라도 링크로 저장소 밖을 가리키면 거부
            print("중단: 저장소 밖을 가리키는 파일: %s" % rel)
            return 2
        if os.path.normcase(rel) in rkeys:
            data, source = git("show", "HEAD:" + rel), "head"
        elif os.path.isfile(src):
            with open(src, "rb") as fh:
                data = fh.read()
            source = "overlay" if rel in overlay else "disk"
        else:
            continue  # 작업 트리에서 지워진 추적 파일
        out = dest_path(dest, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(data)
        entries.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "source": source})
    listing = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest = {"head": head, "restore_head": restore, "overlay": overlay, "files": entries,
                "files_sha256": hashlib.sha256(listing).hexdigest()}
    with open(os.path.join(dest, "SNAPSHOT.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    counts = {s: sum(1 for e in entries if e["source"] == s) for s in ("disk", "head", "overlay")}
    print("HEAD %s, 파일 %d개 %s, 목록 해시 %s" % (head, len(entries), counts, manifest["files_sha256"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
