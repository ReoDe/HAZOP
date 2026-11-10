"""단계 ① 등록 검사를 한 번에 실행한다 (QA용). 하위 프로세스를 쓰지 않는다.

임시 저장 폴더·임시 출력 폴더만 쓴다(store/·output/은 건드리지 않음).
1) 샘플 6개 등록: 등록 완료, 보관 원본 해시 = 입력 해시, 원본 변경 없음, 필수 필드
2) 같은 샘플 재등록: 전부 재사용, 자료·보관 파일 수 그대로
3) 등록정보로 추출 -> 그래프: material_id·registration_version·project_id 채움, not_registered 없음,
   entity_mapping.json 항목 = 그래프 매핑 + 원본 객체·자료·등록 버전
4) tests/ 아래 unittest 전체
종료 코드 0 = 전부 통과.
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

import build_graph  # noqa: E402
import extract_drawio  # noqa: E402
from hazop.register import registry  # noqa: E402

PROJECT = "check-project"
REQUIRED = ["schema_version", "project_id", "material_id", "registration_version", "format", "storage_ref",
            "sha256", "documents", "drawing_number", "design_revision", "auto_candidates", "history",
            "status", "validation"]


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def main():
    safe_console()
    failures = []
    tmp = tempfile.mkdtemp()
    try:
        store, out_ex, out_g = (os.path.join(tmp, x) for x in ("store", "ex", "g"))
        samples = sorted(glob.glob(extract_drawio.SAMPLE_GLOB))
        if len(samples) != 6:
            failures.append("샘플 %d개 != 6" % len(samples))
        print("== 1. 샘플 등록")
        before = {p: read_bytes(p) for p in samples}
        reg_files = {}
        for p in samples:
            r = registry.register(p, PROJECT, store_root=store, actor="check_register")
            rec = r["record"]
            name = os.path.basename(p)
            missing = [k for k in REQUIRED if k not in rec]
            if r["outcome"] != "registered" or rec["status"] != "registered":
                failures.append("%s: 등록 결과 %s/%s" % (name, r["outcome"], rec["status"]))
                continue
            if missing:
                failures.append("%s: 필수 필드 누락 %s" % (name, missing))
            _, stored = registry.load_for_extraction(r["registration_file"])
            if read_bytes(stored) != before[p] or read_bytes(p) != before[p]:
                failures.append("%s: 보관본 또는 원본 내용 불일치" % name)
            if rec["drawing_number"] is not None or "drawing_number" not in rec["auto_candidates"]:
                failures.append("%s: 도면 번호가 자동 후보로만 기록되지 않음" % name)
            reg_files[p] = r["registration_file"]
            print("  %s: %s v%d 미확인 %d" % (name, rec["material_id"], rec["registration_version"],
                                            len(rec["validation"]["unknowns"])))
        print("== 2. 재등록(재사용)")
        for p in samples:
            r = registry.register(p, PROJECT, store_root=store, actor="check_register")
            if r["outcome"] != "reused" or r["registration_file"] != reg_files.get(p):
                failures.append("%s: 재등록이 재사용되지 않음(%s)" % (os.path.basename(p), r["outcome"]))
        with open(os.path.join(store, PROJECT, "registry.json"), encoding="utf-8") as fh:
            n_materials = len(json.load(fh)["materials"])
        walk = list(os.walk(os.path.join(store, PROJECT, "originals")))
        n_files = sum(len(fs) for d, _, fs in walk if os.path.basename(d) != "derived")
        n_derived = sum(len(fs) for d, _, fs in walk if os.path.basename(d) == "derived")  # 원본 옆 SVG(파생 자료)
        if (n_materials, n_files, n_derived) != (len(samples), len(samples), len(samples)):
            failures.append("자료 %d개·보관 원본 %d개·파생 SVG %d개 (기대 %d)"
                            % (n_materials, n_files, n_derived, len(samples)))
        print("  자료 %d개, 보관 원본 %d개, 파생 SVG %d개" % (n_materials, n_files, n_derived))
        print("== 3. 등록 -> 추출 -> 그래프 매핑")
        args = sum([["--registration", f] for f in reg_files.values()], [])
        if extract_drawio.main(args + ["--out-root", out_ex]) != 0:
            failures.append("등록 자료 추출에 blocked 있음")
        recs = {}
        for f in reg_files.values():
            with open(f, encoding="utf-8") as fh:
                rec = json.load(fh)
            recs[rec["material_id"]] = rec
        for d in sorted(os.listdir(out_ex)):
            path = os.path.join(out_ex, d, "extraction.json")
            with open(path, encoding="utf-8") as fh:
                ex = json.load(fh)
            rec = recs.get(ex["source"]["material_id"])
            f = []
            if rec is None or ex["source"]["registration_version"] != rec["registration_version"] \
                    or ex["project_id"] != PROJECT or ex["source"]["sha256"] != rec["sha256"]:
                f.append("추출 결과의 등록 식별정보 불일치")
            if any(u["check"] == "not_registered" for u in ex["validation"]["unknowns"]):
                f.append("not_registered 미확인이 남음")
            graph, out_dir = build_graph.build_one(path, out_g)
            with open(os.path.join(out_dir, "entity_mapping.json"), encoding="utf-8") as fh:
                m = json.load(fh)
            obj = {x["local_id"]: x["source_object_id"] for x in ex["nodes"] + ex["relations"]}
            want = [dict(e, source_object_id=obj[e["local_id"]], material_id=ex["source"]["material_id"],
                         registration_version=ex["source"]["registration_version"])
                    for e in graph["entity_mapping"]]
            if m["entity_mapping"] != want or m["graph_version"] != graph["graph_version"]:
                f.append("entity_mapping.json 불일치")
            if any(e["source_object_id"] is None for e in m["entity_mapping"]):
                f.append("원본 객체 ID 없는 매핑 항목")
            print("  %s: 매핑 %d건 문제 %d건" % (d, len(m["entity_mapping"]), len(f)))
            failures += ["%s: %s" % (d, x) for x in f]
        if len(os.listdir(out_ex)) != len(samples):
            failures.append("추출 결과 %d개 != %d" % (len(os.listdir(out_ex)), len(samples)))
    finally:
        shutil.rmtree(tmp, True)

    print("== 4. unittest")
    suite = unittest.defaultTestLoader.discover(os.path.join(REPO_ROOT, "tests"), top_level_dir=REPO_ROOT)
    outcome = unittest.TextTestRunner(verbosity=1).run(suite)
    if not outcome.wasSuccessful():
        failures.append("unittest 실패 (failures %d, errors %d)" % (len(outcome.failures), len(outcome.errors)))
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
