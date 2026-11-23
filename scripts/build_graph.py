"""output/extract/<도면번호>/extraction.json -> output/graph/<도면번호>/graph.json + structure_report.md + entity_mapping.json

추출 결과가 없으면 먼저: python scripts/extract_drawio.py --samples
"""

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths, store_io  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.graph.query import GraphQuery  # noqa: E402

DEFAULT_EXTRACT = paths.output_root("extract")  # <작업 루트>/출력 (hazop/paths.py)
DEFAULT_OUT = paths.output_root("graph")


def _prepare_study_marks(extraction, out_root):
    """그래프 파일을 덮어쓰기 전에, 표지가 없는 옛 검토구간 집합을 지금(옛) 그래프로 한 번 읽어 표지를 채운다. 사람 수정(노드 더하기·지우기)이나 다시
    추출로 entity 순번이 밀리기 전이어야 한다. 그래프를 앱 작업 루트가 아닌 곳에 만드는 호출(시험·샘플 만들기)은 건드리지 않고, 앱이 없어도 건너뛴다."""
    try:
        from hazop.app import data
        if getattr(data._PREPARED, "on", False) or os.path.normcase(os.path.abspath(out_root)) != os.path.normcase(os.path.abspath(paths.output_root("graph"))):
            return
        from hazop.graph import project
        data.prepare_reextract(project.project_id_of(extraction))      # project_id가 없는 추출은 샘플 프로젝트(project_id_of가 정한다)
    except Exception:  # noqa: BLE001 - 표지 채우기는 덤이다: 그래프 만들기를 막지 않는다
        pass


def _sheet_name(extraction, out_root, seats):
    """그래프 이름(graph_id). seats를 주면 그 자리 표로(정착이 부름). 앱 작업 루트의 그래프면 그 프로젝트의 자리 표로
    (hazop.graph.sources.sheet_name, 정착 전 프로젝트는 이 규칙 전 이름 그대로). 다른 곳(시험·샘플 만들기)은 자리 표를 보지 않은 자연 이름.
    정착은 여기서 하지 않는다(낡은 그래프 다시 짓기처럼 읽는 길이 부르는 다시 짓기가 정착을 일으키지 않게). 정착은 추출 맨 앞
    (hazop.app.data.extract_and_graph)에서 한다."""
    from hazop.graph import project, sheets, sources
    if seats is not None:
        return sheets.sheet_id(sheets.facts(extraction), seats)
    if not _is_app_root(out_root):
        return None
    return sources.sheet_name(project.project_id_of(extraction), extraction)


def _is_app_root(out_root):
    return os.path.normcase(os.path.abspath(out_root)) == os.path.normcase(os.path.abspath(paths.output_root("graph")))


def render_one(extraction_path, seats=None, out_root=None, extraction=None, allow_extract=False):
    """추출 결과 -> (graph, {파일 이름: 바이트}) 쓰지 않고 만든다. 파일은 graph.json·structure_report.md·entity_mapping.json·path_expectations.json.
    extraction: 이미 읽은 추출 결과(없으면 extraction_path에서 읽음). allow_extract: 나누기의 기준 추출이 없으면 그 자리에서
    짓는다(배치 실행만. 앱은 기준 추출을 작업에서 지으므로 넘기지 않는다, corrections.resolve)."""
    if extraction is None:
        with open(extraction_path, encoding="utf-8") as fh:
            extraction = json.load(fh)
    folder = os.path.basename(os.path.dirname(extraction_path))
    # ② 사람 수정 기록을 매번 다시 적용한다(다시 추출해도 수정 유지, extraction.json은 원본 그대로)
    resolved = corrections.resolve(folder, extraction, allow_extract=allow_extract)
    extraction = resolved["corrected"]
    gid = _sheet_name(extraction, out_root or "", seats) if (seats is not None or out_root) else None
    graph = build.build_graph(extraction, extraction_file=paths.rel_or_abs(extraction_path, paths.work_root()), graph_id=gid)
    # 판 이전이 순번 구성요소를 참조로 이을 근거(hazop.study.idmap). graph_version 입력이 아니다
    graph["base_version"] = build.base_version(resolved["base"])
    files = {
        "graph.json": (json.dumps(graph, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "structure_report.md": build.render_report(graph).encode("utf-8"),
        # 그래프 버전별 대상 매핑 (③ -> ④ entity_mapping + 원본 객체·자료·등록 버전)
        "entity_mapping.json": (json.dumps(build.entity_mapping_document(graph, extraction), ensure_ascii=False, indent=2)
                                + "\n").encode("utf-8"),
        # 뷰어 JS 경로 함수 대조용 기대값 (scripts/check_viewer_paths.js)
        "path_expectations.json": json.dumps(GraphQuery(graph).path_expectations(), ensure_ascii=False,
                                             separators=(",", ":")).encode("utf-8"),
    }
    return graph, files


def build_one(extraction_path, out_root, seats=None, allow_extract=False):
    with open(extraction_path, encoding="utf-8") as fh:
        extraction = json.load(fh)
    _prepare_study_marks(extraction, out_root)
    graph, files = render_one(extraction_path, seats=seats, out_root=out_root, extraction=extraction,
                              allow_extract=allow_extract)
    # 추출 결과 폴더 이름을 그대로 쓴다(--samples: 도면번호, 등록 경로: <자료 ID>-r<버전>). 뷰어도 같은 이름으로 그래프를 찾는다.
    out_dir = paths.safe_join(out_root, paths.safe_name(os.path.basename(os.path.dirname(extraction_path))))
    os.makedirs(out_dir, exist_ok=True)
    for name, data in files.items():   # 파일마다 원자적으로(쓰다 끊겨도 반쯤 쓴 graph.json이 남지 않게)
        store_io.write_bytes(os.path.join(out_dir, name), data)
    return graph, out_dir


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extract-root", default=DEFAULT_EXTRACT)
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    blocked = built = 0
    for name in sorted(os.listdir(args.extract_root)):
        path = os.path.join(args.extract_root, name, "extraction.json")
        if not os.path.isfile(path):
            continue
        graph, out_dir = build_one(path, args.out_root, allow_extract=True)
        s = graph["structure"]
        print("%s: %s nodes=%d edges=%d components_physical=%d unknowns=%d -> %s" % (
            graph["source"]["drawing_number"] or os.path.basename(out_dir), graph["validation"]["status"], s["node_count"],
            s["edge_count"], s["components_physical"], len(graph["validation"]["unknowns"]),
            paths.plain_rel(out_dir, paths.work_root())))
        built += 1
        blocked += graph["validation"]["status"] != "passed"
    return 1 if blocked or not built else 0


if __name__ == "__main__":
    sys.exit(main())
