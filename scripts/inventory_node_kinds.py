"""PDF 도면 폴더의 쪽마다 벡터 추출을 돌려 노드를 한 줄씩 JSON Lines로 쓴다(정답지 밖 정밀도 점검의 입력).

실행: python scripts/inventory_node_kinds.py <출력.jsonl> [--input-dir 폴더] [--jobs 3]
  --input-dir 기본값은 check_read_quality의 APR1400 쪽별 PDF 폴더다.
한 줄: {"page": 파일 이름 앞 세 자리, "id", "kind", "tag", "basis": 분류 근거, "label": 라벨 앞 30자, "bbox": [x0, y0, x1, y1]}.
같은 코드면 같은 출력이다. 두 커밋의 출력을 compare_precision_samples.py로 견주고, build_precision_samples.py로 표본을 뽑는다.
쓰는 순서: inventory_node_kinds → build_precision_samples → (그림을 보고 판정 파일 작성) → analyze_precision_verdicts
→ (규칙을 고친 뒤 inventory_node_kinds 다시) → compare_precision_samples.
"""

import argparse
import glob
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [REPO_ROOT, os.path.join(REPO_ROOT, "scripts")]


def one(pdf):
    from hazop.extract.adapters import pdf_vector
    work = tempfile.mkdtemp(prefix="inventory-")
    try:
        ex = pdf_vector.extract(pdf, page=0, repo_root=work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    page = os.path.basename(pdf)[:3]
    rows = []
    for n in ex["nodes"]:
        g = n["geometry"]
        rows.append({"page": page, "id": n["local_id"], "kind": n["kind"], "tag": n.get("tag"),
                     "basis": (n["evidence"] or {}).get("classification_basis") or "", "label": n["label_text"][:30],
                     "bbox": [round(g["x"], 1), round(g["y"], 1), round(g["x"] + g["width"], 1),
                              round(g["y"] + g["height"], 1)]})
    return rows


def main():
    import check_read_quality as rq
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--input-dir", default=None)
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()
    folder = a.input_dir or rq.default_input_dir()
    pdfs = sorted(glob.glob(os.path.join(folder, "*.pdf")))
    if not pdfs:
        sys.exit("PDF가 없다: %s" % folder)
    with ProcessPoolExecutor(a.jobs) as pool, open(a.out, "w", encoding="utf-8") as fh:
        for rows in pool.map(one, pdfs):
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("쪽 %d, 출력 %s" % (len(pdfs), a.out))


if __name__ == "__main__":
    main()
