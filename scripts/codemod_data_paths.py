"""기계적으로 바꿀 수 있는 경로 호출만 `paths.folder()`로 바꾼다(docs/units/2026-11-09-data-consolidation §3, §4 ③a 1번).

    python scripts/codemod_data_paths.py            바뀔 내용을 diff로 보여 준다(쓰지 않음)
    python scripts/codemod_data_paths.py --write    파일에 쓴다

바꾸는 형태(하위 이름이 FOLDER_NAMES에 있을 때만):
    paths.work_path("데이터", "구간", x)       → paths.folder("구간", x)
    paths.resource_path("데이터", "이탈후보")  → paths.folder("이탈후보")
    paths.resource_path("데이터", "참고자료", "APR1400_DCD", x) → paths.folder("APR1400", x)
    paths.resource_path("참고자료", x)          → paths.folder("참고", x)
그 밖의 참조(os.path.join(REPO, "데이터", ...), 모듈 상수 튜플, 화면 문구)는 판단이 필요하다. 남은 것은
tests/test_path_literals.py --report가 작업 목록으로 보여 준다. 같은 파일에 두 번 돌려도 결과가 같다.
"""

import argparse
import difflib
import os
import re
import sys

REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ("hazop", "scripts", "packaging", "tests")
SELF = {"scripts/codemod_data_paths.py", "scripts/migrate_data_layout.py", "scripts/inventory_data_paths.py",
        "hazop/paths.py"}
# paths.FOLDERS의 이름(설계서 §3). 이름이 곧 옛 `데이터/` 하위 폴더 이름이다.
FOLDER_NAMES = ("이탈후보", "기준표", "패턴", "구간", "고정응답", "지식", "평가기준", "검토구간", "분석결과", "백업",
                "초기사건", "도면수정", "도면연결", "잠재후보", "분석결과-시험")
CALL = re.compile(r"""paths\.(?:work_path|resource_path)\(\s*["']데이터["']\s*,\s*["'](%s)["']\s*(,\s*|\))"""
                  % "|".join(FOLDER_NAMES))


APR_CALL = re.compile(r"""paths\.resource_path\(\s*["']데이터["']\s*,\s*["']참고자료["']\s*,\s*["']APR1400_DCD["']\s*(,\s*|\))""")
REF_CALL = re.compile(r"""paths\.resource_path\(\s*["']참고자료["']\s*(,\s*|\))""")


def rewrite(text):
    text = CALL.sub(lambda m: 'paths.folder("%s"%s' % (m.group(1), m.group(2)), text)
    text = APR_CALL.sub(lambda m: 'paths.folder("APR1400"%s' % m.group(1), text)
    return REF_CALL.sub(lambda m: 'paths.folder("참고"%s' % m.group(1), text)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    changed = sites = 0
    for top in SCAN:
        for d, dirs, files in os.walk(os.path.join(args.repo, top)):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                full = os.path.join(d, f)
                rel = os.path.relpath(full, args.repo).replace("\\", "/")
                if rel in SELF:
                    continue
                with open(full, encoding="utf-8", newline="") as fh:
                    old = fh.read()
                new = rewrite(old)
                if new == old:
                    continue
                changed += 1
                sites += len(CALL.findall(old)) + len(APR_CALL.findall(old)) + len(REF_CALL.findall(old))
                if args.write:
                    with open(full, "w", encoding="utf-8", newline="") as fh:
                        fh.write(new)
                else:
                    sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                               "a/" + rel, "b/" + rel, n=0))
    print("%s: 파일 %d개, 호출 %d곳" % ("바꿈" if args.write else "미리보기", changed, sites))
    return 0


if __name__ == "__main__":
    sys.exit(main())
