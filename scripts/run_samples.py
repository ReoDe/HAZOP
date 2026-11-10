"""샘플 6개를 등록 -> 추출 -> 그래프 -> 뷰어까지 한 번에 실행한다. 하위 프로세스를 쓰지 않는다.

  python scripts/run_samples.py [--project sample-project] [--store-root 자료저장소] [--by 이름] [--out-root 출력/samples]

1) 참고자료 샘플 drawio를 하나씩 등록(이미 등록된 같은 원본은 재사용)
2) 등록정보로 추출(출력/samples/추출/), 3) 그래프(출력/samples/그래프/), 4) 뷰어(출력/samples/뷰어/)
결과는 출력/samples/ 아래에 따로 둔다: extract_drawio --samples 결과(출력/추출·그래프·뷰어)와 화면 등록 결과를 덮어쓰지 않는다.
종료 코드 0 = 전부 성공.
"""

import argparse
import glob
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402

import build_graph  # noqa: E402
import build_viewer  # noqa: E402
import extract_drawio  # noqa: E402
from hazop.register import registry  # noqa: E402


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default="sample-project")
    ap.add_argument("--store-root", default=registry.DEFAULT_STORE)
    ap.add_argument("--by", help="등록 주체 (기본: 로그인 사용자명)")
    ap.add_argument("--out-root", default=paths.output_root("samples"),
                    help="결과 루트. 그 아래 추출/·그래프/·뷰어/에 쓴다 (기본 %(default)s)")
    args = ap.parse_args(argv)
    ex_root, g_root, v_root = (os.path.join(args.out_root, paths.output_name(d)) for d in ("추출", "그래프", "뷰어"))
    print("== 1. 등록")
    reg_files = []
    for path in sorted(glob.glob(extract_drawio.SAMPLE_GLOB)):
        result = registry.register(path, args.project, store_root=args.store_root, actor=args.by)
        rec = result["record"]
        print("  %s: %s %s v%s" % (rec["original_name"], result["outcome"], rec["material_id"],
                                   rec["registration_version"]))
        if rec["status"] != "registered" or result["outcome"] == "failed":
            print("  등록 실패:", [p["reason"] for p in rec["validation"]["blockers"]] + result["notes"])
            return 1
        reg_files.append(result["registration_file"])
    print("== 2. 추출")
    rc = extract_drawio.main(sum([["--registration", f] for f in reg_files], []) + ["--out-root", ex_root])
    print("== 3. 그래프")
    rc = build_graph.main(["--extract-root", ex_root, "--out-root", g_root]) or rc
    print("== 4. 뷰어")
    rc = build_viewer.main(["--extract-root", ex_root, "--out-root", v_root, "--graph-root", g_root]) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
