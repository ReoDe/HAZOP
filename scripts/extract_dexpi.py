"""DEXPI 파일(DEXPI XML 2.0 이후, Proteus XML 1.x) -> output/extract/<이름>/extraction.json + validation_report.md

그림을 인식하지 않고 파일의 구조를 옮긴다(HZ-PLN-22). 읽은 방법(read_method)은 'dexpi'다. 이 뒤의 그래프 만들기는 scripts/build_graph.py를 그대로 쓴다.

사용 예:
  python scripts/extract_dexpi.py "D:/…/reference_pid.xml"
  python scripts/extract_dexpi.py --registration store/<프로젝트>/registrations/<자료 ID>/<버전>.json
읽을 수 없는 파일(DOCTYPE·개체 선언, 너무 큰 파일, XML이 아님)은 쓰지 않고 사유를 보이며 1을 돌려준다.
"""

import argparse
import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.extract import report, runinfo  # noqa: E402
from hazop.extract.adapters import dexpi_import, dexpi_read  # noqa: E402
from hazop.register import registry  # noqa: E402

DEFAULT_OUT = paths.output_root("extract")


def registered_out_name(registration, page_index, limit=120):
    """등록 경로 출력 폴더 이름. scripts/extract_drawio.registered_out_name과 같은 규칙(두 형식이 같은 이름을 쓴다)."""
    tail = paths.safe_name("%s-r%s-p%d" % (registration["material_id"], registration["registration_version"], page_index))
    project = paths.safe_name(registration["project_id"])
    room = limit - len(tail) - 2
    if len(project) > room:
        digest = hashlib.sha256(str(registration["project_id"]).encode("utf-8")).hexdigest()[:12]
        project = project[:room - 13].rstrip("._") + "-" + digest
    return project + "__" + tail


def sidecar_for(path):
    """`<이름>.dexpi.xml` 옆의 `<이름>.hazop.json`(같은 앱이 내보낼 때 함께 낸 곁 파일). 없거나 읽을 수 없으면 None."""
    base = os.path.basename(path)
    if not base.endswith(".dexpi.xml"):
        return None
    side = os.path.join(os.path.dirname(path), base[:-len(".dexpi.xml")] + ".hazop.json")
    try:
        with open(side, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def run_one(path, out_root, registration=None, warnings=None, page=0, out_name=None, sidecar="auto"):
    """파일 하나를 추출해 out_root/<이름>/에 쓴다. 반환 (추출 결과, 출력 폴더). 읽을 수 없으면 dexpi_read.DexpiError.
    sidecar: auto면 파일 옆의 곁 파일을 찾고, dict면 그것을, None이면 쓰지 않는다."""
    with open(path, "rb") as fh:
        data = fh.read()
    root = paths.work_root()
    side = sidecar_for(path) if sidecar == "auto" else sidecar
    result, _model = dexpi_import.extract_bytes(data, paths.rel_or_abs(path, root), registration=registration, page=page,
                                                sidecar=side)
    if registration is not None:
        name = out_name or registered_out_name(registration, page)
    else:
        name = paths.safe_name(result["drawing"]["drawing_number"] or os.path.splitext(os.path.basename(path))[0])
    out_dir = paths.safe_join(out_root, name)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "extraction.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    with open(os.path.join(out_dir, "validation_report.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(report.render(result))
    runinfo.record(out_dir, "dexpi", result, warnings=warnings)
    return result, out_dir


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="DEXPI 파일 경로(.xml)")
    ap.add_argument("--registration", action="append", default=[], help="① 등록정보 JSON(등록 완료 자료만)")
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    jobs = [(p, None) for p in args.files]
    for reg_path in args.registration:
        try:
            record, original = registry.load_for_extraction(reg_path)
        except (OSError, ValueError) as exc:
            ap.error("%s: %s" % (reg_path, exc))
        jobs.append((original, record))
    if not jobs:
        ap.error("파일 또는 --registration 필요")
    failed = 0
    for path, record in jobs:
        warnings = []
        try:
            result, out_dir = run_one(path, args.out_root, registration=record, warnings=warnings)
        except dexpi_read.DexpiError as exc:
            print("%s: 읽지 않음(%s) %s" % (path, exc.code, exc.reason))
            failed += 1
            continue
        s = result["summary"]
        print("%s: %s nodes=%d relations=%d unresolved=%d unknowns=%d blockers=%d -> %s"
              % (result["drawing"]["drawing_number"] or os.path.basename(out_dir), result["validation"]["status"],
                 s["nodes"], s["relations"], s["unresolved_connectors"], s["unknowns"], s["blockers"],
                 paths.plain_rel(out_dir, paths.work_root())))
        for text in warnings:
            print(text)
        failed += result["validation"]["status"] == "blocked"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
