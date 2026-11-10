"""고정 AI 응답 파일의 bundle_sha256(근거 묶음 해시)을 현재 입력으로 다시 계산한다.

고정 응답(FixedResponseClient)은 region_id와 bundle_sha256이 요청과 같을 때만 쓰인다. 패턴·그래프·구간 JSON·기준표가
바뀌면 근거 묶음이 달라져 고정 응답이 input_mismatch가 되므로, 바뀐 입력에 맞게 응답 내용(인용 ID 등)을 확인한 뒤
이 스크립트로 해시를 갱신한다. 응답 내용은 바꾸지 않고 region_id·bundle_sha256만 쓴다.

사용법(저장소 루트):
  python scripts/extract_drawio.py --samples && python scripts/build_graph.py   # 구간 JSON의 그래프 준비
  python scripts/refresh_fixture_hashes.py --check      # 불일치만 보고(파일 변경 없음, 불일치 있으면 종료 코드 1)
  python scripts/refresh_fixture_hashes.py              # 해시 갱신
옵션: --region <구간 JSON>, --graph <그래프 JSON>, --fixed-dir <폴더>(여러 번 지정 가능.
기본: 데이터/고정응답/<구간 ID>/ 와 tests/fixtures/analysis/bad/)
"""

import argparse
import glob
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402
from hazop.analysis import ai, run  # noqa: E402

DEFAULT_REGION = paths.folder("표본", "구간", "region-SNP-M-102-pzr.json")
BAD_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "analysis", "bad")


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default=DEFAULT_REGION)
    ap.add_argument("--graph", help="그래프 JSON (기본: 구간 JSON의 graph_ref.graph_file)")
    ap.add_argument("--fixed-dir", action="append", default=[])
    ap.add_argument("--check", action="store_true", help="보고만 하고 파일을 바꾸지 않음")
    args = ap.parse_args(argv)
    inputs = run.load_inputs(args.region, paths.work_root(), graph_path=args.graph, resource_root=paths.resource_root())
    if inputs["blockers"]:
        print("입력 차단 오류 — 계산하지 않음:")
        for b in inputs["blockers"]:
            print("  -", b)
        return 1
    region_id = inputs["region"]["region_id"]
    doc = run.prepare_doc(inputs, None, "refresh", lambda: "refresh")
    dirs = args.fixed_dir or [paths.folder("표본", "고정응답", region_id), BAD_DIR]
    stale = 0
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "*.json"))):
            with open(path, encoding="utf-8") as fh:
                resp = json.load(fh)
            cid = resp["output"]["candidate_id"]
            bundle = doc["evidence_bundles"].get(cid)
            rel = os.path.relpath(path, REPO_ROOT)
            if bundle is None:
                print("%s: 선택 후보의 근거 묶음 없음(%s) — 건너뜀" % (rel, cid))
                stale += 1
                continue
            want = ai.bundle_sha256(bundle)
            if resp.get("region_id") == region_id and resp.get("bundle_sha256") == want:
                print("%s: 최신" % rel)
                continue
            stale += 1
            if args.check:
                print("%s: 불일치(갱신 필요)" % rel)
                continue
            new = {}
            for k, v in resp.items():
                if k in ("region_id", "bundle_sha256"):
                    continue
                new[k] = v
                if k == "sample_note":
                    new["region_id"], new["bundle_sha256"] = region_id, want
            new.setdefault("region_id", region_id)
            new.setdefault("bundle_sha256", want)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(new, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            print("%s: 갱신 %s" % (rel, want[:12]))
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
