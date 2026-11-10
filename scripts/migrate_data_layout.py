"""`데이터/`·`참고자료/` 배치 이전 (docs/2026-11-09-data-consolidation §4, 결정 D1~D9).

    python scripts/migrate_data_layout.py plan --phase 3a|3b         무엇이 어디로 가는지 미리보기(쓰지 않음)
    python scripts/migrate_data_layout.py apply --phase 3a|3b         미리보기만(apply도 기본은 쓰지 않음)
    python scripts/migrate_data_layout.py apply --phase 3a|3b --write 실제 이전: 잠금 확인 → 통째 백업 → 이동 → 대조
    python scripts/migrate_data_layout.py manifest --out <json>       sha256 목록(추적·미추적·ignore 모두)
    python scripts/migrate_data_layout.py compare <전 json> <후 json> 전 목록의 파일이 규칙대로 옮겨진 곳에 같은 해시로 있는지
    python scripts/migrate_data_layout.py graph-check                 샘플을 지금 코드로 다시 추출해 graph_version이 그대로인지

- 3a: 참고자료·기준 자료를 `자원/`으로. 추적 파일은 `git mv`, 그 밖은 파일 단위 os.replace.
- 3b: 추적 표본을 `자원/표본/`으로(`git mv`), 나머지 작업 데이터(데이터·출력·자료저장소·logs)를 `작업/`으로.
  HEAD와 내용이 다른 추적 표본은 사람 작업으로 보고 `작업/` 쪽에 먼저 복사한 뒤 새 위치를 HEAD 내용으로 되돌린다.
- 지우지 않는다. 대상에 같은 해시가 있으면 건너뛰고(원본은 남김) 다른 해시가 하나라도 있으면 아무것도 쓰지 않고 멈춘다.
- 다시 돌리면 남은 차이만 옮긴다. 백업은 저장소 밖 %LOCALAPPDATA%\\HAZOP-이전백업\\<UTC 시각>-<번호>\\(덮어쓰지 않음).
- `.gitignore` 변경과 커밋은 하지 않는다. 커밋 순서는 설계서 §4를 따른다.
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_NAME = ".hazop-app.lock"
MANIFEST_ROOTS = ("데이터", "참고자료", "출력", "자료저장소", "logs", "자원", "작업")

# 규칙은 위에서부터 처음 맞는 것. (원본 접두, 대상 접두, 대상 종류)
# 대상 종류: "any"는 추적이면 git mv, 아니면 os.replace. "tracked"/"untracked"는 그 상태의 파일에만 맞는다.
RULES = {
    "3a": (
        ("데이터/참고자료/APR1400_DCD/", "자원/참고자료/APR1400_DCD/", "any"),
        ("참고자료/", "자원/참고자료/", "any"),
        ("데이터/이탈후보/", "자원/기준/이탈후보/", "any"),
        ("데이터/기준표/", "자원/기준/기준표/", "any"),
        ("데이터/패턴/", "자원/기준/패턴/", "any"),
    ),
    "3b": (
        ("데이터/구간/", "자원/표본/구간/", "tracked"),
        ("데이터/고정응답/", "자원/표본/고정응답/", "tracked"),
        ("데이터/지식/", "자원/표본/지식/", "tracked"),
        ("데이터/평가기준/", "자원/표본/평가기준/", "tracked"),
        ("데이터/", "작업/데이터/", "untracked"),
        ("출력/", "작업/출력/", "untracked"),
        ("자료저장소/", "작업/자료저장소/", "untracked"),
        ("logs/", "작업/logs/", "untracked"),
    ),
}
PHASE_ROOTS = {"3a": ("참고자료", "데이터"), "3b": ("데이터", "출력", "자료저장소", "logs")}
SKIP_NAMES = (LOCK_NAME,)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(repo, *args, check=True):
    out = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=repo, capture_output=True, check=check)
    return out.stdout.decode("utf-8")


def git_state(repo):
    """(추적 집합, HEAD와 다른 추적 집합)"""
    tracked = {x for x in git(repo, "ls-files", "-z").split("\0") if x}
    modified = {x for x in git(repo, "diff", "--name-only", "-z", "HEAD").split("\0") if x}
    return tracked, modified & tracked


def walk(repo, roots):
    for root in roots:
        top = os.path.join(repo, root)
        if os.path.isfile(top):
            yield root
            continue
        for d, dirs, files in os.walk(top):
            dirs.sort()
            for f in sorted(files):
                yield os.path.relpath(os.path.join(d, f), repo).replace("\\", "/")


def map_path(rel, phase, is_tracked):
    for src, dst, kind in RULES[phase]:
        if not rel.startswith(src):
            continue
        if kind == "tracked" and not is_tracked or kind == "untracked" and is_tracked:
            continue
        return dst + rel[len(src):]
    return None


def map_any(rel, tracked):
    """이전 전 경로 → 3a·3b를 모두 거친 뒤 경로(규칙에 안 맞으면 그대로)."""
    cur = rel
    for phase in ("3a", "3b"):
        nxt = map_path(cur, phase, rel in tracked)
        cur = nxt or cur
    return cur


def build_plan(repo, phase):
    tracked, modified = git_state(repo)
    steps, problems, left_3a = [], [], 0
    for rel in walk(repo, PHASE_ROOTS[phase]):
        if os.path.basename(rel) in SKIP_NAMES:
            continue
        is_tracked = rel in tracked
        if phase == "3b" and map_path(rel, "3a", is_tracked):
            left_3a += 1  # 3a 몫이 남아 있음
            continue
        dst = map_path(rel, phase, is_tracked)
        if dst is None:
            if is_tracked and not any(map_path(rel, ph, True) for ph in RULES):
                problems.append("규칙에 없는 추적 파일: %s" % rel)
            continue
        step = {"src": rel, "dst": dst, "how": "git" if is_tracked else "fs", "sha256": sha256(os.path.join(repo, rel)),
                "state": "move"}
        if rel in modified:
            step["keep_copy"] = "작업/" + rel  # 사람이 고친 표본: 작업 루트 쪽에 남긴다
        full_dst = os.path.join(repo, dst)
        if os.path.exists(full_dst):
            step["state"] = "same" if sha256(full_dst) == step["sha256"] else "conflict"
        if step.get("keep_copy") and os.path.exists(os.path.join(repo, step["keep_copy"])):
            if sha256(os.path.join(repo, step["keep_copy"])) != step["sha256"]:
                step["state"] = "conflict"
        steps.append(step)
    if left_3a:
        problems.append("3a가 끝나지 않았음(3a 규칙에 맞는 파일 %d개가 남아 있음, 미리보기에서는 뺐음)" % left_3a)
    seen = {}
    for s in steps:  # 서로 다른 원본이 같은 대상으로 가면 뒤의 것이 앞의 것을 덮으므로 충돌로 본다
        if s["dst"] in seen and seen[s["dst"]]["sha256"] != s["sha256"]:
            s["state"] = seen[s["dst"]]["state"] = "conflict"
            problems.append("같은 대상으로 가는 원본 둘(내용 다름): %s, %s" % (seen[s["dst"]]["src"], s["src"]))
        seen.setdefault(s["dst"], s)
    return steps, problems


def print_plan(repo, phase, steps, problems):
    print("단계 %s: 파일 %d개" % (phase, len(steps)))
    rows = {}
    for s in steps:
        top = "/".join(s["src"].split("/")[:2])
        dtop = "/".join(s["dst"].split("/")[:3 if s["dst"].startswith("자원/") else 2])
        k = (top, dtop, s["how"], s["state"])
        r = rows.setdefault(k, [0, 0])
        r[0] += 1
        r[1] += os.path.getsize(os.path.join(repo, s["src"]))
    print("| 원본 | 대상 | 방법 | 상태 | 파일 | 크기 |")
    print("|---|---|---|---|---|---|")
    for (src, dst, how, state), (n, size) in sorted(rows.items()):
        print("| %s | %s | %s | %s | %d | %.1f MB |" % (src, dst, how, state, n, size / 1e6))
    kept = [s for s in steps if s.get("keep_copy")]
    for s in kept:
        print("사람이 고친 추적 표본: %s → %s 에 복사 후 새 위치는 HEAD 내용으로" % (s["src"], s["keep_copy"]))
    for s in steps:
        if s["state"] == "conflict":
            print("충돌(대상에 다른 내용): %s → %s" % (s["src"], s["dst"]))
    for p in problems:
        print("문제: %s" % p)


def hold_app_locks(repo, roots=None):
    """앱과 같은 QLockFile을 작업 루트 후보(HAZOP_WORK_ROOT, 저장소/작업, 저장소 루트) 모두에서 잡는다.
    (잠금 목록, None) 또는 (None, 이유). 잡은 잠금은 호출한 쪽이 끝날 때까지 들고 있어 그동안 앱이 시작하지 못한다.
    PySide6가 없으면 판단할 수 없으므로 실행 중으로 본다."""
    try:
        from PySide6.QtCore import QLockFile
    except ImportError:
        return None, "PySide6가 없어 앱 실행 여부를 확인할 수 없음"
    roots = roots or [os.environ.get("HAZOP_WORK_ROOT"), os.path.join(repo, "작업"), repo]
    held = []
    for root in dict.fromkeys(os.path.abspath(r) for r in roots if r):
        if not os.path.isdir(root):
            continue
        lock = QLockFile(os.path.join(root, LOCK_NAME))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            for h in held:
                h.unlock()
            return None, "앱이 실행 중이거나 잠금을 쥐고 있음: %s" % os.path.join(root, LOCK_NAME)
        held.append(lock)
    return held, None


def new_backup_dir():
    base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "HAZOP-이전백업")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(base, exist_ok=True)
    n = 1
    while True:
        path = os.path.join(base, "%s-%d" % (stamp, n))
        try:
            os.mkdir(path)  # 이미 있으면 실패: 기존 백업을 덮어쓰지 않는다
            return path
        except FileExistsError:
            n += 1


def backup(repo, steps, dest):
    for s in steps:
        dst = os.path.join(dest, "files", s["src"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(repo, s["src"]), dst)
        if sha256(dst) != s["sha256"]:
            raise SystemExit("백업 해시 불일치, 중단: %s" % s["src"])


def apply_steps(repo, steps):
    done = []
    for s in steps:
        if s["state"] != "move":
            continue
        src, dst = os.path.join(repo, s["src"]), os.path.join(repo, s["dst"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if s.get("keep_copy"):
            keep = os.path.join(repo, s["keep_copy"])
            if not os.path.exists(keep):
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.copy2(src, keep)
        if os.path.exists(dst):  # 계획 뒤에 생긴 대상은 덮지 않는다
            print("계획 뒤에 대상이 생겨 옮기지 않음: %s" % s["dst"])
            s["state"] = "conflict"
            continue
        if s["how"] == "git":
            git(repo, "mv", "--", s["src"], s["dst"])
            if s.get("keep_copy"):
                # 새 위치는 HEAD 내용으로(색인에 올린 수정도 빼고): 이동 커밋이 이름 바꾸기만 되게 한다
                head = subprocess.run(["git", "-c", "core.quotepath=off", "show", "HEAD:" + s["src"]], cwd=repo,
                                      capture_output=True, check=True).stdout
                with open(dst, "wb") as fh:
                    fh.write(head)
                git(repo, "add", "--", s["dst"])
        else:
            os.replace(src, dst)
        done.append(s)
    left = set()
    for s in steps:  # 비게 된 원본 폴더만 정리(파일은 지우지 않음). 다른 프로그램이 쥔 폴더는 남기고 알린다
        d = os.path.dirname(os.path.join(repo, s["src"]))
        while os.path.isdir(d) and not os.listdir(d) and os.path.abspath(d) != os.path.abspath(repo):
            try:
                os.rmdir(d)
            except OSError:
                left.add(os.path.relpath(d, repo))
                break
            d = os.path.dirname(d)
    for d in sorted(left):
        print("빈 폴더를 지우지 못함(다른 프로그램이 열어 둠?): %s" % d)
    return done


def verify(repo, steps):
    bad = []
    for s in steps:
        if s["state"] == "conflict":
            continue
        target = s["keep_copy"] if s.get("keep_copy") else s["dst"]
        full = os.path.join(repo, target)
        if not os.path.isfile(full) or sha256(full) != s["sha256"]:
            bad.append(target)
    return bad


def cmd_plan(repo, phase):
    steps, problems = build_plan(repo, phase)
    print_plan(repo, phase, steps, problems)
    return 1 if problems or any(s["state"] == "conflict" for s in steps) else 0


def cmd_apply(repo, phase, write):
    steps, problems = build_plan(repo, phase)
    print_plan(repo, phase, steps, problems)
    if problems or any(s["state"] == "conflict" for s in steps):
        print("멈춤: 문제나 충돌이 있어 아무것도 쓰지 않음")
        return 1
    if not write:
        print("미리보기만 했음(--write 없음)")
        return 0
    locks, why = hold_app_locks(repo)
    if locks is None:
        print("멈춤: %s" % why)
        return 1
    todo = [s for s in steps if s["state"] == "move"]
    if not todo:
        print("옮길 것이 없음(이미 끝남)")
        return 0
    dest = new_backup_dir()
    with open(os.path.join(dest, "before.json"), "w", encoding="utf-8") as fh:
        json.dump({"phase": phase, "repo": repo, "head": git(repo, "rev-parse", "HEAD").strip(), "steps": steps},
                  fh, ensure_ascii=False, indent=1)
    backup(repo, todo, dest)
    print("백업: %s (%d개, 해시 확인)" % (dest, len(todo)))
    apply_steps(repo, todo)
    bad = verify(repo, steps) + [s["dst"] for s in todo if s["state"] == "conflict"]
    with open(os.path.join(dest, "report.json"), "w", encoding="utf-8") as fh:
        json.dump({"moved": len(todo), "mismatch": bad}, fh, ensure_ascii=False, indent=1)
    if bad:
        print("대조 실패 %d개(백업에서 되살릴 수 있음: %s)" % (len(bad), dest))
        for b in bad[:20]:
            print("  " + b)
        return 1
    print("옮김 %d개, 전후 해시 일치" % len(todo))
    return 0


def manifest(repo):
    tracked, modified = git_state(repo)
    out = {}
    for rel in walk(repo, [r for r in MANIFEST_ROOTS if os.path.exists(os.path.join(repo, r))]):
        if os.path.basename(rel) in SKIP_NAMES:
            continue
        full = os.path.join(repo, rel)
        out[rel] = {"sha256": sha256(full), "size": os.path.getsize(full),
                    "git": "modified" if rel in modified else "tracked" if rel in tracked else "other"}
    return {"head": git(repo, "rev-parse", "HEAD").strip(), "files": out}


def cmd_compare(before_path, after_path):
    before = json.load(open(before_path, encoding="utf-8"))["files"]
    after = json.load(open(after_path, encoding="utf-8"))["files"]
    tracked = {k for k, v in before.items() if v["git"] != "other"}
    missing, changed = [], []
    for rel, info in sorted(before.items()):
        new = map_any(rel, tracked)
        cand = [new] + (["작업/" + rel] if info["git"] == "modified" else [])
        hits = [c for c in cand if c in after]
        if not hits:
            missing.append("%s → %s" % (rel, new))
        elif info["git"] == "modified":
            if not any(after[c]["sha256"] == info["sha256"] for c in hits):
                changed.append("%s (사람이 고친 내용이 어디에도 없음)" % rel)
        elif after[hits[0]]["sha256"] != info["sha256"]:
            changed.append("%s → %s" % (rel, new))
    print("전 %d개, 후 %d개, 빠짐 %d개, 내용 다름 %d개" % (len(before), len(after), len(missing), len(changed)))
    for x in (missing + changed)[:40]:
        print("  " + x)
    return 1 if missing or changed else 0


def cmd_graph_check(repo):
    """샘플 도면을 지금 코드로 임시 폴더에 다시 추출·그래프 빌드해 graph_version이 저장된 graph.json과 같은지 본다.
    작업 루트·자원 위치는 지금 설정(환경변수·기본값) 그대로다. 이전 전후에 돌려 판이 그대로인지 확인한다."""
    import glob
    import tempfile
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "scripts"))
    from hazop import paths
    import build_graph
    import extract_drawio
    stored_root = paths.output_root("그래프")
    rows, bad = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for drawio in sorted(glob.glob(paths.folder("참고", "pid-samples", "*", "*.drawio"))):
            _, ex_dir = extract_drawio.run_one(drawio, os.path.join(tmp, "추출"))
            graph, _ = build_graph.build_one(os.path.join(ex_dir, "extraction.json"), os.path.join(tmp, "그래프"))
            name = os.path.basename(ex_dir)
            gpath = os.path.join(stored_root, name, "graph.json")
            stored = json.load(open(gpath, encoding="utf-8")).get("graph_version") if os.path.isfile(gpath) else None
            ex = json.load(open(os.path.join(ex_dir, "extraction.json"), encoding="utf-8"))
            svg = ((ex.get("coordinate_system") or {}).get("svg_alignment") or {}).get("svg_file")
            same = stored == graph["graph_version"]
            bad += not same
            rows.append((name, stored, graph["graph_version"], ex["source"]["file"], svg, same))
    print("| 도면 | 저장된 판 | 다시 만든 판 | source.file | svg_file | 같음 |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print("| %s | %s | %s | %s | %s | %s |" % (r[0], r[1], r[2], r[3], r[4], "예" if r[5] else "아니오"))
    print("작업 루트 %s, 샘플 %s, 다름 %d" % (paths.work_root(), paths.folder("참고"), bad))
    return 1 if bad or not rows else 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=REPO_DEFAULT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--phase", choices=sorted(RULES), required=True)
        if name == "apply":
            p.add_argument("--write", action="store_true")
    p = sub.add_parser("manifest")
    p.add_argument("--out", required=True)
    p = sub.add_parser("compare")
    p.add_argument("before")
    p.add_argument("after")
    sub.add_parser("graph-check")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    if args.cmd == "plan":
        return cmd_plan(repo, args.phase)
    if args.cmd == "apply":
        return cmd_apply(repo, args.phase, args.write)
    if args.cmd == "manifest":
        doc = manifest(repo)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        print("파일 %d개 → %s" % (len(doc["files"]), args.out))
        return 0
    if args.cmd == "compare":
        return cmd_compare(args.before, args.after)
    return cmd_graph_check(repo)


if __name__ == "__main__":
    sys.exit(main())
