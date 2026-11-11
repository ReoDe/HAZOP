"""단계 ④ 근거 묶음 내보내기 -> output/evidence-bundles/<구간 ID>/<내보낸 시각>/ (기획서/인터페이스.md §2.5)

사용 예:
  python scripts/export_bundles.py                                   # 기본 구간(SNP-M-102 가압기)
  python scripts/export_bundles.py --region data/regions/region-SNP-M-102-pzr.json --out-root <폴더>

판단이 '선택'인 후보마다 근거 묶음(bundle.json)·요청 프롬프트(user_prompt.txt)와 응답 틀(responses/<candidate_id>.json)을
만든다. AI를 호출하지 않고 분석 실행 폴더를 만들지 않는다. 응답을 채운 뒤:
  python scripts/analyze.py --region <구간 JSON> --fixed-dir <내보낸 폴더>/responses
반출 주의: 근거 묶음은 도면 내용을 담는다. 보안 등급이 있는 실제 설계자료는 사용자 확인 뒤에만 외부로 보낸다.
종료 코드 0 = 내보냄, 1 = 입력 오류·차단.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.analysis import bundle_export, run  # noqa: E402

DEFAULT_REGION = paths.folder("regions", "region-SNP-M-102-pzr.json")
DEFAULT_OUT = paths.output_root("evidence-bundles")


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default=DEFAULT_REGION, help="구간 지정 JSON")
    ap.add_argument("--graph", help="그래프 JSON (기본: 구간 JSON의 graph_ref.graph_file)")
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    try:
        res = bundle_export.export_bundles(args.region, args.out_root, graph_path=args.graph)
    except (run.InputError, ValueError, OSError) as exc:
        print("입력 오류 — 내보내지 않음:", exc)
        return 1
    m = res["manifest"]
    print("%s v%s 그래프 %s: 근거 묶음 %d개 -> %s" % (
        m["region"]["region_id"], m["region"]["region_version"], m["graph"]["graph_version"], len(m["candidates"]),
        paths.plain_rel(res["export_dir"], paths.work_root())))
    for c in m["candidates"]:
        print("  %s bundle_sha256=%s" % (c["candidate_id"], c["bundle_sha256"]))
    print("응답 폴더:", paths.plain_rel(res["response_dir"], paths.work_root()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
