"""패키징 W4: 묶인 실행(HAZOP-check.exe)에서 ①~⑤를 화면이 쓰는 함수로 돈다. 네트워크·AI 호출 없음(고정 응답).

사용: HAZOP-check.exe <사본>/w4_flow.py --samples <샘플 사본 폴더> --expect <datas 해시 JSON> --result <결과 JSON>
- 모든 검사는 실패하면 그 자리에서 끝낸다(ok()가 Stop을 던짐, 결과 JSON에는 그때까지의 단계만 남음).
- 사전 검사(복사·분석 전에): ① 루트: 묶인 실행이고, 자원 루트 = 프로그램 루트(묶음 _internal)이며 작업 루트와 묶음이
  서로 포함되지 않음 ② 묶음 datas 해시: --expect({저장소 상대 경로: sha256})와 묶음 안 같은 위치 파일의 바이트 해시가
  같음 ③ 자원 경로: 구간 JSON이 가리키는 기준 자료 4종과 지침서를 자원 루트에서 찾은 경로가 묶음 안이고 해시가 같음.
- 작업 루트: HAZOP_WORK_ROOT(필수, 임시 폴더). 샘플 사본에서 구간 JSON·고정 응답·지식 입력·샘플 도면을 복사한다
  (샘플 도면은 저장소와 같은 상대 위치: samples 경로 graph_version이 구간 JSON 기록과 같아야 ④가 통과).
- ④ 뒤: 실행 기록(input_files)의 기준 자료 4종 경로가 묶음 안이고 해시가 맞는지, 지침서 경로가 묶음 안인지 본다.
  음성 검사: 묶음 안 패턴 파일·지침서를 잠시 다른 이름으로 바꾸면 분석이 통과하지 못해야 한다(끝나면 되돌림).
tests/test_packaging.py SplitRootsFlowTest와 같은 순서·기대값(후보 44·시나리오 14·위험도 6·설계보완 11)을 쓴다.
마지막 줄에 RUN_DIR=<④ 실행 폴더>를 출력한다(이어서 HAZOP.exe --run으로 ④⑤ 스크린샷).
"""

import argparse
import glob
import hashlib
import json
import os
import shutil
import sys

T = "2026-11-05T00:00:00Z"
REGION = "region-SNP-M-102-pzr"


def norm(p):
    return os.path.normcase(os.path.realpath(p))


def within(path, root):
    """path가 root와 같거나 그 아래면 True. 드라이브가 다르면 False."""
    try:
        return os.path.commonpath([norm(path), norm(root)]) == norm(root)
    except ValueError:
        return False


def root_problems(frozen, program_root, resource_root, work_root):
    """루트 판정 문제 목록(빈 목록 = 통과). 자원 루트가 묶음이 아닌 곳(예: 저장소)으로 빠지는 경우를 잡는다."""
    probs = []
    if not frozen:
        probs.append("묶인 실행이 아님(sys._MEIPASS 없음)")
    if norm(resource_root) != norm(program_root):
        probs.append("자원 루트가 묶음이 아님: %s (묶음 %s)" % (resource_root, program_root))
    if within(work_root, program_root) or within(program_root, work_root):
        probs.append("작업 루트와 묶음이 서로 포함됨: %s / %s" % (work_root, program_root))
    return probs


def sha_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def sha_text_file(path):
    """hazop.analysis.run이 기록하는 방식(텍스트로 읽은 내용의 UTF-8 해시)."""
    with open(path, encoding="utf-8") as fh:
        return hashlib.sha256(fh.read().encode("utf-8")).hexdigest()


def datas_problems(program_root, expect):
    """묶음 안 datas 파일이 기대 해시와 같은지. 문제 목록."""
    probs = []
    for rel, want in sorted(expect.items()):
        p = os.path.join(program_root, *rel.split("/"))
        if not os.path.isfile(p):
            probs.append("없음: %s" % rel)
        elif sha_file(p) != want:
            probs.append("해시 다름: %s" % rel)
    return probs


def input_file_problems(input_files, resource_roles, resource_root, program_root, expect):
    """실행 기록의 기준 자료가 묶음 안 파일이고 기록 해시·기대 해시와 같은지. 문제 목록."""
    probs, seen = [], set()
    for f in input_files:
        if f.get("role") not in resource_roles:
            continue
        seen.add(f["role"])
        full = os.path.join(resource_root, *str(f.get("path") or "").split("/"))
        rel = os.path.relpath(full, program_root).replace("\\", "/") if within(full, program_root) else None
        if rel is None:
            probs.append("%s: 묶음 밖 파일 %s" % (f["role"], full))
        elif not os.path.isfile(full) or sha_text_file(full) != f.get("sha256"):
            probs.append("%s: 기록 해시와 다름 %s" % (f["role"], rel))
        elif expect.get(rel) != sha_file(full):
            probs.append("%s: 빌드 원본 해시와 다름 %s" % (f["role"], rel))
    missing = set(resource_roles) - seen
    if missing:
        probs.append("기록에 없는 기준 자료: %s" % sorted(missing))
    return probs


class Stop(Exception):
    """검사 실패: 이후 단계를 하지 않고 끝낸다."""


def resource_path_problems(inputs, guide_rel, resource_root, program_root, expect, resolve):
    """분석 전: 구간 JSON의 기준 자료 경로(자원 루트 기준)와 지침서가 묶음 안이고 빌드 원본 해시와 같은지."""
    probs = []
    for role, rel in sorted(inputs.items()) + [("guide", guide_rel)]:
        full = resolve(str(rel), resource_root)
        if not within(full, program_root):
            probs.append("%s: 묶음 밖 %s" % (role, full))
        elif not os.path.isfile(full):
            probs.append("%s: 없음 %s" % (role, rel))
        elif expect.get(os.path.relpath(full, program_root).replace("\\", "/")) != sha_file(full):
            probs.append("%s: 빌드 원본 해시와 다름 %s" % (role, rel))
    return probs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--expect", required=True, help="{저장소 상대 경로: sha256} JSON(묶음 datas)")
    ap.add_argument("--result", required=True)
    args = ap.parse_args(argv)

    from hazop import paths
    from hazop.console import safe_console

    safe_console()  # cp949 콘솔에서 표현할 수 없는 문자로 죽지 않게(scripts/*.py와 같음)
    res = {"frozen": bool(getattr(sys, "_MEIPASS", None)), "program_root": paths.program_root(),
           "resource_root": paths.resource_root(), "work_root": paths.work_root(), "steps": {}, "failures": []}

    def ok(step, cond, detail=""):
        res["steps"][step] = {"ok": bool(cond), "detail": detail}
        print("  [%s] %s %s" % ("OK" if cond else "FAIL", step, detail))
        if not cond:
            res["failures"].append(step)
            raise Stop(step)

    def finish():
        with open(args.result, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2, default=str)
        print("결과: %s" % ("통과" if not res["failures"] else "실패 %s" % res["failures"]))
        print("RUN_DIR=%s" % res.get("run_dir"))
        return 0 if not res["failures"] else 1

    try:
        flow(args, paths, res, ok)
    except Stop:
        pass
    return finish()


def flow(args, paths, res, ok):
    ok("work_root_env", bool(os.environ.get(paths.ENV_WORK_ROOT)), "HAZOP_WORK_ROOT(임시 폴더) 지정 여부")
    probs = root_problems(res["frozen"], paths.program_root(), paths.resource_root(), paths.work_root())
    ok("roots", not probs, "; ".join(probs) or "program=resource=%s work=%s" % (paths.program_root(),
                                                                           paths.work_root()))
    bundle = paths.program_root()
    guide_rel = paths.file_rel("guide")
    with open(args.expect, encoding="utf-8") as fh:
        expect = json.load(fh)
    probs = datas_problems(bundle, expect)
    ok("bundle-datas", not probs, "; ".join(probs) or "%d개 해시 일치" % len(expect))
    samples = os.path.abspath(args.samples)
    # samples = 검사 입력 사본(작은 저장소, verify_bundle.make_inputs): 표본은 저장소와 같은 자리, 샘플 도면은 기록 경로 자리에 있다
    with open(paths.folder_in(samples, "표본", "regions", REGION + ".json"), encoding="utf-8") as fh:
        region_inputs = json.load(fh)["inputs"]
    probs = resource_path_problems(region_inputs, guide_rel, paths.resource_root(), bundle, expect, paths.resolve_rel)
    ok("resource_paths", not probs, "; ".join(probs) or "기준 자료 4종·지침서 = 묶음 파일(분석 전 확인)")

    from hazop import review as rv
    from hazop.analysis import api, integrity
    from hazop.app import data
    from hazop.export import export_worksheet
    from hazop.kg import build as kg_build, inputs as kg_inputs, screen as kg_screen
    from hazop.register import registry

    work = paths.work_root()
    for name in ("구간", "고정응답", "지식"):
        shutil.copytree(paths.folder_in(samples, "표본", paths.SAMPLE_FOLDERS[name]), paths.folder(name), dirs_exist_ok=True)
    # 샘플 도면은 기록 경로 자리에 둔다: 추출 JSON이 저장소와 같아야 구간의 그래프 판이 맞는다
    shutil.copytree(paths.logical_dir(samples, "참고", "pid-samples"), paths.logical_dir(work, "참고", "pid-samples"),
                    dirs_exist_ok=True)
    region_path = paths.folder("구간", REGION + ".json")
    region = data.read_json(region_path)

    # ④용 samples 경로 추출·그래프(구간 how_to_build와 같은 방법): 묶음 scripts/의 run_one·build_one
    drawio_path = [p for p in glob.glob(paths.logical_dir(work, "참고", "pid-samples", "*", "*.drawio"))
                   if "SNP-M-102" in p][0]
    svg = glob.glob(os.path.join(os.path.dirname(drawio_path), "*.drawio.svg"))
    _, ex_dir = data.script_module("extract_drawio").run_one(drawio_path, paths.output_root("추출"))
    graph, gdir = data.script_module("build_graph").build_one(os.path.join(ex_dir, "extraction.json"),
                                                              paths.output_root("그래프"))
    gpath = os.path.join(work, region["graph_ref"]["graph_file"])
    ok("graph_version", graph["graph_version"] == region["graph_ref"]["graph_version"]
       and norm(os.path.join(gdir, "graph.json")) == norm(gpath), "%s %s" % (graph["graph_version"], gdir))

    # ① 등록 → 추출 → 그래프(묶음 scripts/의 extract_drawio·build_graph를 importlib로 읽음)
    store = paths.store_root()
    sample = os.path.join(work, "원본", "P-102.drawio")
    os.makedirs(os.path.dirname(sample))
    shutil.copyfile(drawio_path, sample)
    shutil.copyfile(svg[0], sample + ".svg")
    reg = registry.register(sample, "p", store_root=store, actor="w4", now=lambda: T,
                            metadata={"drawing_number": "SNP-M-102", "reason": "패키징 W4 검사"})
    ok("1-register", reg["outcome"] == "registered", reg["outcome"])
    rows = data.list_registrations()
    out = data.extract_and_graph(rows[0]["path"])
    mods = {n: data.script_module(n).__file__ for n in data.SCRIPT_NAMES}
    ok("1-script_module", all(within(f, os.path.join(bundle, "scripts")) for f in mods.values()),
       json.dumps(mods, ensure_ascii=False))
    ok("1-extract_graph", os.path.isfile(os.path.join(out["graph_dir"], "graph.json")),
       out["extraction"]["coordinate_system"]["svg_alignment"]["source"])

    # ② 추출 목록·뷰어 HTML(묶음 hazop/viewer/template.html)
    names = [e["name"] for e in data.list_extractions()]
    info = data.viewer_html_for(rows[0]["extract_name"])
    ok("2-viewer", info["error"] is None and os.path.isfile(info["html"]), "%s %s" % (names, info.get("html")))

    # ③ 지식그래프(묶음 screen_template.html·vendor)
    kdir = os.path.join(paths.folder("지식"), "SNP-SAMPLE")
    knowledge = kg_inputs.load_knowledge(os.path.join(kdir, "knowledge_nodes.csv"),
                                         os.path.join(kdir, "knowledge_links.csv"), "SNP-SAMPLE")
    graphs = kg_screen.load_graphs(paths.output_root("그래프"))
    kg = kg_build.build_kg(knowledge, [g for _, g in graphs.values()])
    kg_build.write_outputs(paths.safe_join(paths.output_root("지식그래프"), paths.safe_name(kg["kg_id"])), knowledge, kg)
    sdata = kg_screen.screen_data(kg, graph, kg_screen.load_regions(paths.folder("구간")),
                                  kg_screen.read_candidates(kdir))
    html = kg_screen.build_html(sdata)
    ok("3-kg_html", bool(sdata["nodes"]) and "/*@VENDOR@*/" not in html and within(kg_screen.VENDOR_DIR, bundle),
       "노드 %d, HTML %d자, vendor %s" % (len(sdata["nodes"]), len(html), kg_screen.VENDOR_DIR))

    # ④ 분석(고정 응답): 기준 자료 4종·지침서는 묶음(자원 루트)
    fixed = paths.folder("고정응답", REGION)
    r = api.run_analysis(region_path, response_dir=fixed, run_id="analysis-w4")
    c = r["doc"]["validation"]["counts"] if r.get("doc") else {}
    counts = (c.get("candidates"), c.get("scenarios"), c.get("risk_proposed"), c.get("design_improvement_candidates"))
    ok("4-analysis", r["status"] == "passed" and counts == (44, 14, 6, 11), "%s %s %s" % (r["status"], counts,
                                                                                        r.get("blockers")))
    res["run_dir"] = r.get("run_dir")
    files = (r.get("doc") or {}).get("analysis_run", {}).get("input_files", [])
    res["input_files"] = files
    probs = input_file_problems(files, paths.RESOURCE_INPUT_ROLES, paths.resource_root(), bundle, expect)
    guide = paths.resource_file("guide")
    if not within(guide, bundle) or expect.get(guide_rel) != sha_file(guide):
        probs.append("지침서가 묶음 파일이 아니거나 해시 다름: %s" % guide)
    ok("4-resource_reads", not probs, "; ".join(probs) or "기준 자료 4종·지침서 = 묶음 파일, 해시 일치")

    # ④ 음성: 묶음 자원을 잠시 치우면 분석이 통과하지 못해야 한다(다른 위치로 대체하지 않음)
    for label, rel in (("patterns", paths.folder_rel("패턴") + "/pressurizer-patterns.json"), ("guide", guide_rel)):
        target = os.path.join(bundle, *rel.split("/"))
        moved = target + ".w4-moved"
        run_id = "analysis-w4-no-" + label
        os.replace(target, moved)
        try:
            try:
                rr = api.run_analysis(region_path, response_dir=fixed, run_id=run_id)
                outcome = "status=%s blockers=%s" % (rr.get("status"), rr.get("blockers"))
                failed = rr.get("status") != "passed"
            except Exception as e:  # InputError 등
                outcome, failed = "%s: %s" % (type(e).__name__, e), True
        finally:
            os.replace(moved, target)
        ok("4-negative-" + label, failed and os.path.isfile(target), outcome[:300])

    # ⑤ 검토 저장 → Excel(openpyxl)
    run = rv.open_run(r["run_dir"])
    doc = run["doc"]
    cid = "deviation-p86-d12"
    sid, = [s["scenario_id"] for s in doc["scenarios"] if s["candidate_id"] == cid]
    did, = [d["dic_id"] for d in doc["design_improvement_candidates"] if d["candidate_id"] == cid]
    rc = rv.make_risk_confirmation(run, 3, "강도 근거", 2, 2, "빈도 근거", (), "human")
    sdec = rv.scenario_decision(run, sid, "accept", "원안 수용", "검토자A", risk_confirmation=rc, now=T)
    ddec = rv.dic_decision(run, did, "accept", "권고 필요", "검토자A", recommendation="경보 추가 검토", now=T)
    path, saved = rv.save_review(store, run, rv.build_review(run, cid, "검토자A", "요약", [sdec], [ddec]), now=T)
    ok("5-review", saved["review_version"] == 1, path)
    export_worksheet(r["run_dir"], store, paths.output_root("워크시트"), now=T)
    xlsx = glob.glob(paths.output_in(work, "워크시트", "**", "*.xlsx"), recursive=True)
    ok("5-excel", len(xlsx) == 1, "; ".join(xlsx))


if __name__ == "__main__":
    sys.exit(main())
