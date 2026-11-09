"""SNP 샘플 회귀 기준판. 샘플 drawio·벡터 PDF를 임시 작업 루트에서 새로 추출해 요약을 얼린 기준값과 견준다.

  python scripts/check_snp_baseline.py                 # 기준값과 비교(종료 코드 0 = 후퇴 없음)
  python scripts/check_snp_baseline.py --update        # 기준값을 지금 결과로 바꿈(커밋 메시지에 이유를 적을 것)
  python scripts/check_snp_baseline.py --samples-dir <샘플 폴더>   # 데이터 이전으로 샘플 위치가 바뀌어도 쓸 수 있게

요약(도면·형식마다): 종류별 노드 수, 태그 집합, 배관(관계) 수, 미확인 수, 제안 검토구간 수.
프로젝트(형식마다): 도면 연결 짝 수, 방향 모순 수, 프로젝트 제안 구간 수.
판정: drawio는 값이 그대로 같아야 통과. PDF는 같거나 나아야 통과한다.
- 태그(개수까지 센다): 잃으면 후퇴. 새 태그는 같은 도면 drawio(정답)에 있는 태그일 때만 나아짐, 아니면 후퇴.
- 종류: 미분류에서 다른 종류로 옮겨 간 것만 나아짐(분류된 종류 수가 줄면 후퇴). 미확인·방향 모순·미연결 합은 낮을수록,
  짝은 높을수록 나음. 나머지(배관 수·제안 구간 수·도면 수)는 같아야 한다.
좋아진 값도 기준값을 갱신해야 다음 커밋의 바닥이 된다.
"""

import argparse
import collections
import glob
import json
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402

BASELINE = os.path.join(REPO_ROOT, "tests", "baselines", "snp_baseline.json")
AT = "2026-11-07T00:00:00Z"
# PDF에서 '같거나 나아야' 하는 숫자 값과 나은 방향. tags·kinds·unlinked는 따로 본다. 나머지는 같아야 한다.
PDF_BETTER = {"unknowns": "lower", "unclassified": "lower", "linked": "higher", "direction_conflicts": "lower"}


def default_samples_dir():
    return paths.folder("참고", "P&ID 도면 샘플")


def drawing_summary(extraction, graph, proposal):
    kinds = collections.Counter(n.get("kind") or "unclassified" for n in extraction["nodes"])
    return {"kinds": dict(sorted(kinds.items())),
            "tags": sorted(n["tag"] for n in extraction["nodes"] if n.get("tag")),
            "pipes": extraction["summary"]["relations"],
            "unknowns": extraction["summary"]["unknowns"],
            "unclassified": kinds.get("unclassified", 0),
            "proposed_nodes": len(proposal["nodes"])}


def project_summary(graphs):
    from hazop.graph import project
    from hazop.study import nodes as sn
    pg = project.build(project.UNREGISTERED_PROJECT, graphs)
    s = project.summary(pg)
    return {"sheets": s["sheets"], "linked": s["linked"], "direction_conflicts": s["direction_conflicts"],
            "unlinked": s["unlinked"], "proposed_nodes": len(sn.propose(pg, at=AT)["nodes"])}


def collect(samples_dir):
    import extract_drawio
    from hazop.extract.adapters import pdf_vector
    from hazop.graph import build
    from hazop.study import nodes as sn
    out = {"drawio": {}, "pdf": {}, "project": {}}
    graphs = {"drawio": [], "pdf": []}
    folders = sorted(d for d in glob.glob(os.path.join(samples_dir, "*")) if os.path.isdir(d))
    if not folders:
        raise SystemExit("샘플 폴더가 비었음: %s" % samples_dir)
    tmp = paths.work_root()
    for folder in folders:
        name = os.path.basename(folder)
        for fmt, pattern in (("drawio", "*.drawio"), ("pdf", "*.pdf")):
            files = sorted(glob.glob(os.path.join(folder, pattern)))
            if not files:
                continue
            if fmt == "drawio":
                ex, _ = extract_drawio.run_one(files[0], os.path.join(tmp, "추출"))
            else:
                ex = pdf_vector.extract(files[0], page=0, repo_root=tmp)
            g = build.build_graph(ex)
            graphs[fmt].append(g)
            out[fmt][name] = drawing_summary(ex, g, sn.propose(g, at=AT))
    for fmt in ("drawio", "pdf"):
        if graphs[fmt]:
            out["project"][fmt] = project_summary(graphs[fmt])
    return out


def compare(base, now):
    """→ (후퇴 목록, 나아진 목록)."""
    bad, better = [], []
    for name in sorted(set(base["drawio"]) | set(now["drawio"])):
        if base["drawio"].get(name) != now["drawio"].get(name):
            bad.append("drawio %s: %s" % (name, diff(base["drawio"].get(name), now["drawio"].get(name))))
    if base["project"].get("drawio") != now["project"].get("drawio"):
        bad.append("drawio 프로젝트: %s" % diff(base["project"].get("drawio"), now["project"].get("drawio")))
    pdf_pairs = [("pdf " + n, base["pdf"].get(n), now["pdf"].get(n), set((now["drawio"].get(n) or {}).get("tags") or ()))
                 for n in sorted(set(base["pdf"]) | set(now["pdf"]))]
    pdf_pairs.append(("pdf 프로젝트", base["project"].get("pdf"), now["project"].get("pdf"), set()))
    for label, b, n, truth in pdf_pairs:
        if b is None or n is None:
            bad.append("%s: 기준값 또는 지금 결과가 없음" % label)
            continue
        for key in sorted(set(b) | set(n)):
            bv, nv = b.get(key), n.get(key)
            if bv == nv:
                continue
            if key == "tags":
                lost = sorted((collections.Counter(bv) - collections.Counter(nv)).elements())
                added = sorted((collections.Counter(nv) - collections.Counter(bv)).elements())
                wrong = [t for t in added if t not in truth]
                if lost or wrong:
                    bad.append("%s 태그 잃음 %s · drawio에 없는 새 태그 %s" % (label, lost, wrong))
                else:
                    better.append("%s 태그 늘어남 %s" % (label, added))
            elif key == "kinds":
                shrunk = {k: (bv.get(k, 0), nv.get(k, 0)) for k in bv if k != "unclassified" and nv.get(k, 0) < bv[k]}
                moved = sum(nv.values()) == sum(bv.values()) and nv.get("unclassified", 0) <= bv.get("unclassified", 0)
                if shrunk or not moved:
                    bad.append("%s kinds %s → %s" % (label, json.dumps(bv, ensure_ascii=False),
                                                     json.dumps(nv, ensure_ascii=False)))
                else:
                    better.append("%s 미분류에서 분류됨 %s" % (label, {k: nv[k] - bv.get(k, 0) for k in nv
                                                                if k != "unclassified" and nv[k] != bv.get(k, 0)}))
            elif key == "unlinked":
                (bad if sum(nv.values()) > sum(bv.values()) else better).append(
                    "%s 미연결 %s → %s" % (label, bv, nv))
            elif key in PDF_BETTER:
                worse = nv > bv if PDF_BETTER[key] == "lower" else nv < bv
                (bad if worse else better).append("%s %s %s → %s" % (label, key, bv, nv))
            else:
                bad.append("%s %s %s → %s" % (label, key, json.dumps(bv, ensure_ascii=False),
                                              json.dumps(nv, ensure_ascii=False)))
    return bad, better


def diff(b, n):
    if not isinstance(b, dict) or not isinstance(n, dict):
        return "%r → %r" % (b, n)
    return "; ".join("%s %s → %s" % (k, json.dumps(b.get(k), ensure_ascii=False), json.dumps(n.get(k), ensure_ascii=False))
                     for k in sorted(set(b) | set(n)) if b.get(k) != n.get(k))


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples-dir", default=None, help="SNP 샘플 폴더(기본: 자원 루트의 참고자료/P&ID 도면 샘플)")
    ap.add_argument("--baseline", default=BASELINE)
    ap.add_argument("--update", action="store_true", help="기준값을 지금 결과로 바꿈")
    args = ap.parse_args(argv)
    samples = os.path.abspath(args.samples_dir or default_samples_dir())
    tmp = tempfile.mkdtemp(prefix="hazop_snp_baseline_")
    old = os.environ.get(paths.ENV_WORK_ROOT)
    os.environ[paths.ENV_WORK_ROOT] = tmp
    try:
        now = collect(samples)
    finally:
        if old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = old
        shutil.rmtree(tmp, ignore_errors=True)
    if args.update:
        os.makedirs(os.path.dirname(args.baseline), exist_ok=True)
        with open(args.baseline, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(now, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print("기준값을 썼음: %s" % paths.rel_or_abs(args.baseline, REPO_ROOT))
        return 0
    with open(args.baseline, encoding="utf-8") as fh:
        base = json.load(fh)
    bad, better = compare(base, now)
    for line in better:
        print("나아짐: %s" % line)
    for line in bad:
        print("후퇴: %s" % line)
    p = now["project"].get("drawio", {})
    print("SNP: 후퇴 %d · 나아짐 %d · drawio 짝 %s · 방향 모순 %s · 도면 drawio %d · pdf %d"
          % (len(bad), len(better), p.get("linked"), p.get("direction_conflicts"), len(now["drawio"]), len(now["pdf"])))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
