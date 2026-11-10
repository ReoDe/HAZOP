"""단계 ① draw.io P&ID 원본 1개 등록 -> <저장 루트>/<프로젝트>/registrations/<자료 ID>/<버전>.json

사용 예:
  python scripts/register.py --project sample-project "resources/references/pid-samples/SNP-M-101_RCS-main-loop/SNP-M-101_RCS-main-loop.drawio"
  python scripts/register.py --project sample-project 파일.drawio --drawing-number SNP-M-101 --revision 0 --by 홍길동 --reason "표제란 대조"
  python scripts/register.py --project sample-project 파일.drawio --metadata 식별정보.json
저장 루트 기본값: 환경변수 HAZOP_STORE_ROOT 또는 <작업 루트>/자료저장소/(작업 루트 기본은 저장소 루트, HAZOP_WORK_ROOT로
변경). --store-root로 바꿀 수 있다.
원본 옆 도면 SVG는 페이지마다 찾아 파생 자료로 originals/<자료 ID>/<버전>/derived/에 함께 보관하고 등록정보
derived_files(page_ids·해시)에 기록한다. 찾는 규칙은 추출과 같은 함수(hazop.extract.svg_align.find_svg):
  한 페이지 문서: 원본과 같은 이름 <파일명>.svg·<stem>.svg -> <NN>_<페이지 이름>.drawio.svg
                  -> 폴더에 *.drawio.svg가 하나뿐이면 그것
  여러 페이지 문서: <NN>_<페이지 이름>.drawio.svg만(하나뿐인 SVG를 여러 페이지에 붙이지 않음)
  페이지 이름에 경로 구분자·'..'·드라이브 문자·제어문자가 있으면 그 규칙을 건너뛰고, 원본 폴더 밖 파일은 쓰지 않는다.
SVG를 찾지 못한 페이지는 validation.unknowns에 'SVG 없음'을 남긴다.
표제란 값은 자동 후보(auto_candidates)로만 기록한다. 도면 번호·개정번호·제목의 확정값은 사람이 인자나
메타데이터 JSON({"drawing_number", "design_revision", "title", "by", "reason"})으로 입력해야 생긴다.
종료 코드 0 = 등록 완료(재사용 포함), 1 = 실패·보류.
"""

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop.register import registry  # noqa: E402


def build_metadata(args):
    """인자와 메타데이터 JSON을 합친다. 같은 항목에 다른 값이 있으면 ValueError."""
    meta = {}
    if args.metadata:
        with open(args.metadata, encoding="utf-8") as fh:
            meta = json.load(fh)
        if not isinstance(meta, dict):
            raise ValueError("메타데이터 JSON은 객체여야 함")
    for key, value in (("drawing_number", args.drawing_number), ("design_revision", args.revision),
                       ("title", args.title), ("reason", args.reason)):
        if value is None:
            continue
        if meta.get(key) not in (None, value):
            raise ValueError("%s 값이 인자(%r)와 메타데이터 JSON(%r)에서 다름" % (key, value, meta[key]))
        meta[key] = value
    return meta or None


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("drawio", help="등록할 draw.io 원본 파일 1개")
    ap.add_argument("--project", required=True, help="프로젝트 ID")
    ap.add_argument("--material-type", default="P&ID", help="자료 종류 (MVP: P&ID)")
    ap.add_argument("--store-root", default=registry.DEFAULT_STORE)
    ap.add_argument("--drawing-number")
    ap.add_argument("--revision", help="설계 개정번호(design_revision)")
    ap.add_argument("--title")
    ap.add_argument("--metadata", help="사람 확정 식별정보 JSON 파일")
    ap.add_argument("--by", help="등록·확정 주체 (기본: 로그인 사용자명)")
    ap.add_argument("--reason", help="확정 사유")
    args = ap.parse_args(argv)
    try:
        meta = build_metadata(args)
    except (OSError, ValueError) as exc:
        print("%s: on_hold status=on_hold\n  문제: invalid_metadata %s" % (os.path.basename(args.drawio), exc))
        return 1
    result = registry.register(args.drawio, args.project, args.material_type, args.store_root, meta, args.by)
    rec = result["record"]
    print("%s: %s material_id=%s version=%s status=%s -> %s" % (
        rec["original_name"], result["outcome"], rec["material_id"], rec["registration_version"], rec["status"],
        result["registration_file"] and registry._display_path(result["registration_file"])))
    for note in result["notes"]:
        print("  안내:", note)
    for p in rec["validation"]["blockers"]:
        print("  문제: %s %s" % (p["check"], p["reason"]))
    for u in rec["validation"]["unknowns"]:
        print("  미확인: %s %s" % (u["field"], u["reason"]))
    return 0 if rec["status"] == "registered" and result["outcome"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
