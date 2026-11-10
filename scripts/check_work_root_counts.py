"""작업 루트 사본을 화면 없이 읽어, 화면과 탐색기가 보는 목록의 수를 센다(HZ-GOV-02 단계 6 재현 스크립트).

폴더 이름을 바꾸는 이전 전후에 같은 사본으로 돌려 수가 같은지, '경로를 못 찾음'이 새로 생기지 않는지 본다.

    python scripts/check_work_root_counts.py --work-root <작업 루트 사본> --out <결과.json>
    python scripts/check_work_root_counts.py --work-root <작업 루트 사본> --compare <이전 결과.json> [--compare-key <열쇠>]

- 작업 루트는 사본을 준다. 읽기만 하며, 실행 전후로 사본의 파일 목록·크기·수정 시각이 같은지 확인해 결과에 적는다(changed_files).
- 설정 파일(%APPDATA%)은 임시 폴더로 돌려 실제 설정을 읽지 않는다. 등록 저장 루트는 <작업 루트>의 기본 자리다.
- seen: hazop.app.data와 탐색기 모듈이 쓰는 함수로 센 수(등록 자료, 추출, 그래프, 지식그래프, 구간, 분석 실행, 검토 기록,
  ④ 검토구간 저장본·확정본, ⑤ 분석 결과, ⑥ 초기사건 그룹).
- files: paths.FOLDERS의 작업 루트 행과 paths.OUTPUT_FOLDERS 행마다 그 아래 파일 수. 열쇠로 세므로 폴더 이름이 바뀌어도 견줄 수 있다.
- records: 사용자 파일에 적힌 상대 경로(구간 inputs·graph_ref.graph_file, 추출 source.file·svg_file, 그래프 source.extraction_file,
  분석 input_files·ai_client.response_dir)를 paths.resolve_rel로 풀어 본 결과. 안 풀린 것은 (종류, 적힌 경로)로 모두 적는다.
- --compare: seen·files·records의 수가 같고, 안 풀린 경로가 이전 결과에 없던 것이 0이면 종료 코드 0, 아니면 1.
"""

import argparse
import collections
import glob
import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402

MAX_JSON_BYTES = 30_000_000


def tree_state(root):
    """{상대 경로: (크기, 수정 시각 ns)}"""
    out = {}
    for d, _dirs, files in os.walk(root):
        for f in files:
            full = os.path.join(d, f)
            st = os.stat(full)
            out[os.path.relpath(full, root).replace("\\", "/")] = (st.st_size, st.st_mtime_ns)
    return out


def file_count(root):
    return sum(len(files) for _d, _dirs, files in os.walk(root)) if os.path.isdir(root) else None


def count_files():
    """표의 열쇠마다 그 폴더 아래 파일 수(폴더가 없으면 None)."""
    work = {name: file_count(paths.folder(name)) for name, f in paths.FOLDERS.items() if f.root == "work"}
    out = {name: file_count(paths.output_root(name)) for name in paths.OUTPUT_FOLDERS}
    return {"work": work, "output": out}


def count_seen(errors):
    from hazop.app import data, related
    from hazop.ie import store as ie_store
    from hazop.kg import screen as kg_screen
    from hazop.review import store as review_store

    seen = collections.OrderedDict()
    regs = data.list_registrations()
    seen["registrations"] = len(regs)
    seen["registrations_extracted"] = sum(bool(e["extracted"]) for e in regs)
    seen["registrations_graphed"] = sum(bool(e["graphed"]) for e in regs)
    extractions = data.list_extractions()
    seen["extractions"] = len(extractions)
    seen["unregistered_extractions"] = sum(bool(data.extraction_origin(e["path"])) for e in extractions)
    graphs = kg_screen.load_graphs(paths.output_root("그래프"))
    seen["graphs"] = len(graphs)
    seen["kg_roots"] = len(kg_screen.list_kg_roots(paths.output_root("지식그래프")))

    regions = data.list_regions()
    seen["regions"] = len(regions)
    runs = reviews = with_graph = 0
    for path in regions:
        try:
            region = data.read_json(path)
        except (OSError, ValueError) as exc:
            errors.append("구간 읽기 실패 %s: %s" % (os.path.basename(path), exc))
            continue
        with_graph += data.current_graph(region) is not None
        region_id = region.get("region_id") or os.path.splitext(os.path.basename(path))[0]
        for run_dir in data.list_runs(region_id):
            runs += 1
            try:
                reviews += len(review_store.load_run_reviews(paths.store_root(), region_id, os.path.basename(run_dir)))
            except (OSError, ValueError) as exc:
                errors.append("검토 기록 읽기 실패 %s: %s" % (os.path.basename(run_dir), exc))
    seen["regions_with_current_graph"] = with_graph
    seen["analysis_runs"] = runs
    seen["reviews"] = reviews

    sets, projects = {}, set(e["record"].get("project_id") for e in regs)
    for e in extractions:  # ②④⑤의 도면 고르기와 같은 이름으로 색인을 연다
        try:
            idx = related.DrawingIndex(e["name"])
        except Exception as exc:  # noqa: BLE001 - 화면도 이 자리에서 멈추므로 수가 아니라 오류로 남긴다
            errors.append("색인 실패 %s: %s: %s" % (e["name"], type(exc).__name__, exc))
            continue
        if not idx.graph:
            continue
        projects.add(idx.graph.get("project_id"))
        key = (idx.graph.get("project_id"), idx.graph["graph_id"])
        sets[key] = (idx.node_set is not None, bool(idx.node_set) and idx.node_set.get("status") == "confirmed",
                     idx.results is not None, idx.kg is not None)
    seen["project_graphs"] = len(sets)
    seen["study_node_sets"] = sum(v[0] for v in sets.values())
    seen["study_node_sets_confirmed"] = sum(v[1] for v in sets.values())
    seen["study_results"] = sum(v[2] for v in sets.values())
    seen["project_kg"] = sum(v[3] for v in sets.values())

    groups = candidates = 0
    for project_id in sorted(projects, key=str):
        try:
            doc, _ = ie_store.load(project_id)
        except ie_store.Unreadable as exc:
            errors.append("초기사건 읽기 실패 %s: %s" % (project_id, exc))
            continue
        groups += len(doc["groups"])
        candidates += len(doc["candidates"])
    seen["ie_groups"] = groups
    seen["ie_candidates"] = candidates
    return seen


def recorded_paths(work):
    """[(종류, 적힌 경로, 푸는 기준 루트)] 작업 루트 아래 JSON에 적힌 상대 경로."""
    found = []

    def add(kind, rel, role=None):
        if isinstance(rel, str) and ("/" in rel or "\\" in rel):  # inputs에는 경로가 아닌 값(kg_id, 해시)도 있다
            found.append((kind, rel, paths.resource_root() if role in paths.RESOURCE_INPUT_ROLES else work))

    for f in sorted(glob.glob(os.path.join(work, "**", "*.json"), recursive=True)):
        if os.path.getsize(f) > MAX_JSON_BYTES:
            continue
        try:
            with open(f, encoding="utf-8-sig") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        if isinstance(doc.get("inputs"), dict):
            for role, rel in doc["inputs"].items():
                add("inputs." + role, rel, role)
        if isinstance(doc.get("graph_ref"), dict):
            add("graph_ref.graph_file", doc["graph_ref"].get("graph_file"))
        if isinstance(doc.get("source"), dict):
            add("source.file", doc["source"].get("file"))
            add("source.extraction_file", doc["source"].get("extraction_file"))
        cs = doc.get("coordinate_system")
        if isinstance(cs, dict) and isinstance(cs.get("svg_alignment"), dict):
            add("svg_file", cs["svg_alignment"].get("svg_file"))
        run = doc.get("analysis_run")
        if isinstance(run, dict):
            for x in run.get("input_files") or ():
                if isinstance(x, dict):
                    add("input_files." + str(x.get("role")), x.get("path"), x.get("role"))
            if isinstance(run.get("ai_client"), dict):
                add("ai_client.response_dir", run["ai_client"].get("response_dir"))
    return found


def count_records(work):
    found = recorded_paths(work)
    missing = collections.Counter((kind, rel) for kind, rel, root in found if not os.path.exists(paths.resolve_rel(rel, root)))
    return {"total": len(found), "resolved": len(found) - sum(missing.values()), "unresolved": sum(missing.values()),
            "unresolved_paths": [[kind, rel, n] for (kind, rel), n in sorted(missing.items())]}


def collect(work_root):
    work_root = os.path.abspath(work_root)
    if not os.path.isdir(work_root):
        raise SystemExit("작업 루트가 없음: %s" % work_root)
    before = tree_state(work_root)
    saved = {k: os.environ.get(k) for k in (paths.ENV_WORK_ROOT, paths.ENV_STORE_ROOT, "APPDATA")}
    errors = []
    with tempfile.TemporaryDirectory(prefix="hazop-counts-") as appdata:
        os.environ[paths.ENV_WORK_ROOT] = work_root
        os.environ.pop(paths.ENV_STORE_ROOT, None)
        os.environ["APPDATA"] = appdata
        try:
            result = {"seen": count_seen(errors), "files": count_files(), "records": count_records(work_root), "errors": errors}
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    after = tree_state(work_root)
    result["changed_files"] = sorted(set(before) ^ set(after) | {k for k in before if k in after and before[k] != after[k]})
    result["total_files"] = len(after)
    return result


def compare(old, new):
    """다른 점 목록. 비어 있으면 같다."""
    diffs = []
    for part in ("seen", "errors", "changed_files"):
        if old.get(part) != new.get(part):
            diffs.append("%s: %r → %r" % (part, old.get(part), new.get(part)))
    for group in ("work", "output"):
        a, b = old["files"][group], new["files"][group]
        for key in sorted(set(a) | set(b)):
            if a.get(key) != b.get(key):
                diffs.append("files.%s.%s: %r → %r" % (group, key, a.get(key), b.get(key)))
    for key in ("total", "resolved", "unresolved"):
        if old["records"][key] != new["records"][key]:
            diffs.append("records.%s: %r → %r" % (key, old["records"][key], new["records"][key]))
    known = {(k, r) for k, r, _n in old["records"]["unresolved_paths"]}
    for kind, rel, n in new["records"]["unresolved_paths"]:
        if (kind, rel) not in known:
            diffs.append("새로 못 찾는 경로: %s %s (%d곳)" % (kind, rel, n))
    return diffs


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-root", required=True, help="작업 루트 사본(읽기만 한다)")
    ap.add_argument("--out", help="결과 JSON을 쓸 경로")
    ap.add_argument("--compare", help="이전 결과 JSON. 다르면 종료 코드 1")
    ap.add_argument("--compare-key", help="이전 결과 JSON이 여러 사본의 결과를 묶은 파일일 때 견줄 항목의 열쇠(예: dev_work_root)")
    args = ap.parse_args(argv)
    result = collect(args.work_root)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    seen = result["seen"]
    print("화면이 보는 수: " + " · ".join("%s %s" % kv for kv in seen.items()))
    print("기록 경로 %(total)d건 · 풀림 %(resolved)d · 안 풀림 %(unresolved)d" % result["records"])
    print("오류 %d · 사본에서 바뀐 파일 %d · 전체 파일 %d" % (len(result["errors"]), len(result["changed_files"]), result["total_files"]))
    if args.compare:
        with open(args.compare, encoding="utf-8") as fh:
            old = json.load(fh)
        diffs = compare(old[args.compare_key] if args.compare_key else old, result)
        for d in diffs:
            print("다름: " + d)
        print("이전 결과와 %s" % ("같음" if not diffs else "다름 %d건" % len(diffs)))
        return 1 if diffs else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
