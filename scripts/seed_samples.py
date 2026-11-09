"""표본(`자원/표본/`)을 작업 루트의 `데이터/` 아래로 채운다(docs/2026-11-09-data-consolidation §4 ③b 6번).

    python scripts/seed_samples.py [--work-root <폴더>]             없는 파일만 복사, 내용이 다른 파일은 목록만
    python scripts/seed_samples.py [--work-root <폴더>] --refresh   다른 파일을 백업한 뒤 표본으로 덮음

작업 루트 기본값은 hazop.paths.work_root()(HAZOP_WORK_ROOT 우선). 백업은 <작업 루트>/데이터/백업/<UTC 시각>-표본갱신-<번호>/.
다시 돌려도 결과가 같다.
"""

import argparse
import datetime
import importlib.util
import hashlib
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SAMPLE_ROOT = os.path.join(REPO, "자원", "표본")


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def plan(work_root):
    """[(표본 상대 경로, 상태)] 상태: copy(없음) / same / differs"""
    out = []
    for d, dirs, files in os.walk(SAMPLE_ROOT):
        dirs.sort()
        for f in sorted(files):
            src = os.path.join(d, f)
            rel = os.path.relpath(src, SAMPLE_ROOT)
            dst = os.path.join(work_root, "데이터", rel)
            state = "copy" if not os.path.exists(dst) else "same" if sha256(dst) == sha256(src) else "differs"
            out.append((rel.replace("\\", "/"), state))
    return out


def backup_dir(work_root):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = os.path.join(work_root, "데이터", "백업")
    os.makedirs(base, exist_ok=True)
    n = 1
    while True:
        path = os.path.join(base, "%s-표본갱신-%d" % (stamp, n))
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            n += 1


def _migrate():
    spec = importlib.util.spec_from_file_location("migrate_data_layout", os.path.join(REPO, "scripts", "migrate_data_layout.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work-root")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    if not os.path.isdir(SAMPLE_ROOT):
        print("표본 폴더가 없음: %s" % SAMPLE_ROOT)
        return 1
    if args.work_root:
        work_root = os.path.abspath(args.work_root)
    else:
        from hazop import paths
        work_root = paths.work_root()
    locks, why = _migrate().hold_app_locks(REPO, [work_root])
    if locks is None:
        print("멈춤: %s" % why)
        return 1
    items = plan(work_root)
    bdir = None
    for rel, state in items:
        src = os.path.join(SAMPLE_ROOT, rel)
        dst = os.path.join(work_root, "데이터", rel)
        if state == "copy":
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                with open(src, "rb") as fin, open(dst, "xb") as fout:  # 그사이 생긴 파일은 덮지 않는다
                    shutil.copyfileobj(fin, fout)
                shutil.copystat(src, dst)
            except FileExistsError:
                print("그사이 생긴 파일이라 그대로 둠: %s" % rel)
        elif state == "differs" and args.refresh:
            bdir = bdir or backup_dir(work_root)
            keep = os.path.join(bdir, "데이터", rel)
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            shutil.copy2(dst, keep)
            shutil.copy2(src, dst)
        if state == "differs":
            print("%s: %s" % ("백업 후 덮음" if args.refresh else "내용 다름(그대로 둠)", rel))
    counts = {s: sum(1 for _, x in items if x == s) for s in ("copy", "same", "differs")}
    print("작업 루트 %s: 복사 %d, 같음 %d, 다름 %d%s" % (work_root, counts["copy"], counts["same"], counts["differs"],
                                                  ", 백업 %s" % bdir if bdir else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
