"""IE 인계 묶음 내보내기 (기획서/초기사건-출력설계.md §3, §8 P2·P3) -> <출력 폴더>/IE-<프로젝트>-<KST 시각>.xlsx·.json

사용 예:
  python scripts/export_ie_bundle.py --results data/analysis-results/<프로젝트>/<graph_id>.json \\
      --nodes data/study-nodes/<프로젝트>/<graph_id>.json --graph <프로젝트 그래프 또는 도면 graph.json>
  python scripts/export_ie_bundle.py ... --ie <다른 ⑥ 초기사건 파일>   # 작업 루트 밖의 ⑥ 파일을 쓸 때
  python scripts/export_ie_bundle.py ... --out <폴더> --now 2026-11-08T03:00:00Z   # 같은 입력이면 같은 JSON

⑤ 결과 중 승인 항목만 넣는다. 승인 항목이 없으면 파일을 쓰지 않는다. 그룹·표제·최종상태·기본사건과 IEC 대응표는 ⑥ 저장
파일(작업 루트의 data/initiating-events/<프로젝트>.json)에서 읽으므로 ⑥ 화면에서 내보낸 묶음과 IEC 번호가 같다. 그 파일이
없을 때만 빈 문서를 쓰고 그 사실을 출력한다. ⑥ 파일은 읽기만 하고 고치지 않는다(⑤와 맞추는 것은 메모리 안에서만).
종료 코드 0 = 출력함, 1 = 승인 항목 없음·오류.
"""

import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.ie import bundle as ib  # noqa: E402
from hazop.ie import bundle_xlsx as ix  # noqa: E402
from hazop.ie import model, store  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402


def _read_json(path, kind=None, what="파일"):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or (kind is not None and doc.get("kind") != kind):
        raise ValueError("%s이 아님: %s" % (what, path))
    return doc


def _utc(text):
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", text):
        raise argparse.ArgumentTypeError("UTC 시각은 2026-11-08T03:00:00Z 꼴이어야 함")
    return text


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True, help="⑤ 분석 결과 JSON")
    ap.add_argument("--nodes", required=True, help="확정한 검토구간 집합 JSON")
    ap.add_argument("--graph", required=True, help="프로젝트 그래프 또는 도면 graph.json(원인 위치 태그를 찾는 데 씀)")
    ap.add_argument("--ie", default=None, help="⑥ 초기사건 저장 파일. 주지 않으면 작업 루트의 %s/<프로젝트>.json을 읽고, "
                    "그 파일이 없으면 빈 문서" % paths.folder_rel("initiating-events"))
    ap.add_argument("--out", default=paths.output_root("initiating-events"), help="출력 폴더 (기본 %(default)s)")
    ap.add_argument("--now", type=_utc, default=None, help="만든 시각(UTC). 주지 않으면 지금")
    args = ap.parse_args(argv)
    try:
        results = res.read(args.results)
        if results is None:
            raise ValueError("분석 결과 파일이 없음: %s" % args.results)
        node_set = _read_json(args.nodes, sn.KIND, "검토구간 파일")
        graph = _read_json(args.graph, None, "그래프 파일")
        if results.get("graph_id") != node_set.get("graph_id"):
            raise ValueError("분석 결과(%s)와 검토구간(%s)의 도면이 다름" % (results.get("graph_id"), node_set.get("graph_id")))
        bad = res.validate(results, node_set)
        if bad:
            raise ValueError("분석 결과 검증 실패: " + "; ".join(bad[:5]) + (" 외 %d건" % (len(bad) - 5) if len(bad) > 5 else ""))
        now = args.now or sn.now_utc()
        if args.ie:
            ie_from = args.ie
            ie_doc = _read_json(args.ie, model.KIND, "⑥ 초기사건 파일")
            bad = model.problems(ie_doc)
            if bad:
                raise ValueError("⑥ 초기사건 파일 검증 실패: " + "; ".join(bad[:5]))
        else:
            ie_from = store.store_path(node_set.get("project_id"))
            try:
                ie_doc, saved = store.load(node_set.get("project_id"))
            except store.Unreadable as exc:
                raise ValueError("%s. 고친 뒤 다시 하거나 --ie로 다른 파일을 주세요" % exc) from None
            if saved is None:
                ie_from = "없음(%s). 빈 문서로 IEC 번호를 매겼으므로 나중에 ⑥ 화면이 매기는 번호와 다를 수 있음" % ie_from
        b = ib.build_bundle(results, node_set, graph, model.sync(ie_doc, results, at=now), now)
        if not b["candidates"]:
            print("출력하지 않음: 승인한 항목이 없습니다(승인 안 된 항목 %d건)" % b["source"]["left_out_unapproved"])
            return 1
        os.makedirs(args.out, exist_ok=True)
        xlsx, js = ix.export(os.path.join(args.out, ix.default_stem(b["project_id"], now) + ".xlsx"), b)
    except (OSError, ValueError, KeyError) as exc:
        print("출력하지 않음: %s" % exc)
        return 1
    print("IE 후보 %d건 (승인 항목 %d건, 넣지 않은 항목 %d건), 그룹 %d건"
          % (len(b["candidates"]), b["source"]["approved_entries"], b["source"]["left_out_unapproved"],
             len(b["groups"])))
    print("품질 경고:", ib.warning_summary_text(b))
    print("⑥ 초기사건 파일:", ie_from)
    print("Excel:", xlsx)
    print("JSON:", js)
    return 0


if __name__ == "__main__":
    sys.exit(main())
