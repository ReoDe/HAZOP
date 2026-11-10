"""데스크톱 화면 지원 검사(기획서/인터페이스.md §2.5·§3.1·§3.3·§7.1, §8의 ①·④·패키징 대비 행). QA용.

임시 폴더만 쓴다(데이터/·자료저장소/·출력/ 원본은 바꾸지 않음). AI 호출·네트워크 없음.
1) 샘플 추출 -> 그래프 (임시 폴더, scripts/extract_drawio.py --samples·build_graph.py와 같은 함수)
2) 근거 묶음 내보내기: 내보낸 bundle_sha256 = 데이터/고정응답/의 bundle_sha256, 실행 폴더·analysis.json 없음
3) 자원 루트·작업 루트를 임시 폴더로 바꿔 analyze.py·export_bundles.py·register.py·extract_drawio.py를 새 프로세스로 실행
   (graph_version = 구간 파일이 고정한 값, 후보 44·시나리오 14·위험도 제안 6·설계보완 후보 11, 등록 SVG 우선 사용)
4) 샘플 6개 등록: SVG 6개 파생 등록, 등록 SVG 추출 = 원본 옆 SVG 추출(svg_file·source 제외)
5) unittest tests.test_desktop_support
종료 코드 0 = 전부 통과.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

import analyze  # noqa: E402
import build_graph  # noqa: E402
import extract_drawio  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.analysis import bundle_export  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.register import registry  # noqa: E402

import json as _json  # noqa: E402
with open(paths.folder("표본", "regions", "region-SNP-M-102-pzr.json"), encoding="utf-8") as _fh:
    GRAPH_VERSION = _json.load(_fh)["graph_ref"]["graph_version"]  # 구간 파일이 고정한 그래프 버전(재고정 시 따라감)
COUNTS = {"candidates": 44, "scenarios": 14, "risk_proposed": 6, "design_improvement_candidates": 11}
PYTHON = sys.executable if os.path.isfile(sys.executable) else (shutil.which("python") or sys.executable)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ok(name, cond, failures):
    print("  [%s] %s" % ("통과" if cond else "실패", name))
    if not cond:
        failures.append(name)


def check_export(graph_file, tmp, failures):
    region_before = open(analyze.DEFAULT_REGION, "rb").read()
    res = bundle_export.export_bundles(analyze.DEFAULT_REGION, os.path.join(tmp, "근거묶음"), graph_path=graph_file)
    m = res["manifest"]
    by_id = {c["candidate_id"]: c["bundle_sha256"] for c in m["candidates"]}
    fixed = sorted(f for f in os.listdir(analyze.DEFAULT_FIXED) if f.endswith(".json"))
    same = [f for f in fixed if _load(os.path.join(analyze.DEFAULT_FIXED, f))["bundle_sha256"] == by_id.get(f[:-5])]
    ok("내보낸 bundle_sha256 = 데이터/고정응답 %d/%d" % (len(same), len(fixed)), fixed and same == fixed, failures)
    ok("그래프 버전 %s" % m["graph"]["graph_version"], m["graph"]["graph_version"] == GRAPH_VERSION, failures)
    files = [f for _, _, fs in os.walk(tmp) for f in fs]
    ok("실행 폴더·analysis.json 만들지 않음", "analysis.json" not in files
       and not os.path.exists(os.path.join(tmp, "분석")), failures)
    ok("구간 JSON 변경 없음", open(analyze.DEFAULT_REGION, "rb").read() == region_before, failures)


def check_split_roots(graph, tmp, failures):
    res, work = os.path.join(tmp, "res"), os.path.join(tmp, "work")
    region = _load(analyze.DEFAULT_REGION)
    for rel in list(region["inputs"].values()) + [paths.file_rel("guide")]:
        os.makedirs(os.path.dirname(os.path.join(res, rel)), exist_ok=True)
        shutil.copyfile(paths.resolve_rel(rel, REPO_ROOT), os.path.join(res, rel))
    os.makedirs(paths.folder_in(work, "구간"))
    shutil.copyfile(analyze.DEFAULT_REGION, paths.folder_in(work, "구간", os.path.basename(analyze.DEFAULT_REGION)))
    shutil.copytree(analyze.DEFAULT_FIXED, paths.folder_in(work, "고정응답", os.path.basename(analyze.DEFAULT_FIXED)))
    gpath = os.path.join(work, region["graph_ref"]["graph_file"])
    os.makedirs(os.path.dirname(gpath))
    shutil.copyfile(graph, gpath)
    env = {k: v for k, v in os.environ.items() if k not in (paths.ENV_STORE_ROOT, "PYTHONIOENCODING")}
    env.update(HAZOP_RESOURCE_ROOT=res, HAZOP_WORK_ROOT=work)

    def cli(*args):
        p = subprocess.run([PYTHON, os.path.join(REPO_ROOT, "scripts", args[0])] + list(args[1:]), cwd=tmp, env=env,
                           capture_output=True, timeout=600)
        if p.returncode:
            print(p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace"))
        return p.returncode

    ok("analyze.py (작업·자원 루트 임시 폴더)", cli("analyze.py", "--run-id", "analysis-split") == 0, failures)
    run_file = os.path.join(work, "출력", "분석", region["region_id"], "analysis-split", "analysis.json")
    if os.path.isfile(run_file):
        doc = _load(run_file)
        c = doc["validation"]["counts"]
        ok("분석 결과 수 %s" % {k: c[k] for k in COUNTS}, {k: c[k] for k in COUNTS} == COUNTS, failures)
        ok("그래프 버전", doc["graph_ref"]["graph_version"] == GRAPH_VERSION, failures)
        ok("입력 파일 경로 = 루트 기준 상대 경로", [f["path"] for f in doc["analysis_run"]["input_files"]][2:]
           == [region["inputs"][r] for r in ("candidate_catalog", "applicability", "patterns", "risk_criteria")],
           failures)
    ok("export_bundles.py (임시 루트)", cli("export_bundles.py") == 0
       and os.path.isdir(os.path.join(work, "출력", "근거묶음", region["region_id"])), failures)
    sample = [p for p in glob.glob(extract_drawio.SAMPLE_GLOB) if "SNP-M-101" in p][0]
    drawio = os.path.join(work, "in", "P-1.drawio")
    os.makedirs(os.path.dirname(drawio))
    shutil.copyfile(sample, drawio)
    shutil.copyfile(os.path.join(os.path.dirname(sample), "01_SNP-M-101.drawio.svg"), drawio + ".svg")
    ok("register.py (같은 이름 SVG 포함)", cli("register.py", "--project", "p", drawio) == 0, failures)
    reg_dir = os.path.join(work, "자료저장소", "p", "registrations")
    mid = os.listdir(reg_dir)[0] if os.path.isdir(reg_dir) else None
    rec = _load(os.path.join(reg_dir, mid, "1.json")) if mid else {}
    ok("derived_files에 SVG 해시 기록", [d["role"] for d in rec.get("derived_files", [])] == ["svg"], failures)
    ok("extract_drawio.py --registration", mid and cli("extract_drawio.py", "--registration",
                                                         os.path.join(reg_dir, mid, "1.json")) == 0, failures)
    ex_file = os.path.join(work, "출력", "추출", "p__%s-r1-p0" % mid, "extraction.json")
    al = _load(ex_file)["coordinate_system"]["svg_alignment"] if os.path.isfile(ex_file) else {}
    ok("추출이 등록된 SVG 사용 (svg_alignment.source=%s)" % al.get("source"),
       al.get("source") == "registered_derived" and al.get("status") == "verified", failures)


def check_samples(tmp, failures):
    """샘플 6개 등록: 원본 옆 SVG가 파생 자료로 등록되고, 등록 SVG로 추출한 결과가 원본 옆 SVG 추출과
    svg_alignment의 svg_file·source만 다름(미확인 항목 수 같음)."""
    n_svg, same = 0, 0
    samples = sorted(glob.glob(extract_drawio.SAMPLE_GLOB))
    for p in samples:
        r = registry.register(p, "check-project", store_root=os.path.join(tmp, "store"), actor="check")
        rec = r["record"]
        n_svg += len(rec.get("derived_files") or [])
        record, original = registry.load_for_extraction(r["registration_file"])
        d, _ = extract_drawio.run_one(original, os.path.join(tmp, "d"), registration=record,
                                      registered_svgs=registry.registered_svgs(r["registration_file"], record))
        s, _ = extract_drawio.run_one(original, os.path.join(tmp, "s"), registration=record, registered_svgs={})
        ad, as_ = d["coordinate_system"]["svg_alignment"], s["coordinate_system"]["svg_alignment"]
        ad.update(svg_file=as_["svg_file"], source=as_["source"])
        if d == s and build.build_graph(d)["graph_version"] == build.build_graph(s)["graph_version"]:
            same += 1
    ok("샘플 %d개 등록: SVG 파생 등록 %d개" % (len(samples), n_svg), n_svg == len(samples) == 6, failures)
    ok("등록 SVG 추출 = 원본 옆 SVG 추출(svg_file·source 제외) %d/%d" % (same, len(samples)),
       same == len(samples), failures)


def main():
    safe_console()
    failures = []
    tmp = tempfile.mkdtemp(prefix="check_desktop_")
    try:
        ext, gr = os.path.join(tmp, "추출"), os.path.join(tmp, "그래프")
        print("== 1. 샘플 추출·그래프 빌드 (임시 폴더)")
        if extract_drawio.main(["--samples", "--out-root", ext]) != 0 or \
                build_graph.main(["--extract-root", ext, "--out-root", gr]) != 0:
            failures.append("추출·그래프 빌드 실패")
        graph = os.path.join(gr, "SNP-M-102", "graph.json")
        print("== 2. 근거 묶음 내보내기")
        sub = os.path.join(tmp, "export")
        os.makedirs(sub)
        check_export(graph, sub, failures)
        print("== 3. 자원 루트·작업 루트 변경 (새 프로세스)")
        split = os.path.join(tmp, "split")
        os.makedirs(split)
        check_split_roots(graph, split, failures)
        print("== 4. 샘플 6개 SVG 파생 등록")
        smp = os.path.join(tmp, "samples")
        os.makedirs(smp)
        check_samples(smp, failures)
        print("== 5. unittest (tests/test_desktop_support.py)")
        suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_desktop_support")
        outcome = unittest.TextTestRunner(verbosity=1).run(suite)
        if not outcome.wasSuccessful():
            failures.append("unittest 실패 (failures %d, errors %d)" % (len(outcome.failures), len(outcome.errors)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
