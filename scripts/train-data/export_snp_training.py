"""가상 도면(SNP) drawio 원본에서 학습 자료를 뽑는다: 쪽 그림 + 기호 COCO + 글자 COCO + 연결 그래프.

  python scripts/train-data/export_snp_training.py <출력 폴더> [--dpi 200]

정답은 사람이 그린 drawio 원본이다(check_read_quality.snp_key와 같은 좌표 맞춤). 글자 영역은 같은 PDF의 텍스트 층에서
낱말 상자를 그대로 쓴다(가상 도면은 PDF가 drawio에서 나왔으므로 텍스트 층이 곧 정답이다).
"""

import argparse
import glob
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import coco_format as cf  # noqa: E402

sys.path.insert(0, os.path.join(cf.REPO_ROOT, "scripts"))


def transform_of(key):
    m = re.search(r"배율 ([\d.]+), 이동 \(([-\d.]+), ([-\d.]+)\)", key["method"])
    return float(m.group(1)), float(m.group(2)), float(m.group(3))


def export(samples_dir, out_dir, dpi):
    import pdfplumber
    import extract_drawio
    import check_read_quality as crq
    os.environ.setdefault("HAZOP_WORK_ROOT", tempfile.mkdtemp(prefix="hazop-train-snp-"))
    scale = dpi / 72.0
    sym = cf.dataset("SNP 가상 도면 기호(drawio 원본 정답)")
    txt = cf.text_dataset("SNP 가상 도면 글자 영역(PDF 텍스트 층)")
    graphs = []
    for folder in crq.snp_folders(samples_dir):
        name = os.path.basename(folder).split("_")[0]
        dio_path = glob.glob(os.path.join(folder, "*.drawio"))[0]
        pdf = glob.glob(os.path.join(folder, "*.pdf"))[0]
        dio, _ = extract_drawio.run_one(dio_path, os.path.join(os.environ["HAZOP_WORK_ROOT"], "extract"))
        key = crq.snp_key(dio, pdf, name)
        png = "images/%s.png" % name
        (w, h), _ = cf.render_pdf_page(pdf, dpi, os.path.join(out_dir, png))
        meta = {"source": "snp-drawio", "drawing": name, "group": name.split("-")[1] + "-" + name.split("-")[2][0],
                "dpi": dpi}
        iid = cf.add_image(sym, png, w, h, **meta)
        tid = cf.add_image(txt, png, w, h, **meta)
        ann_of = {}
        for s in key["symbols"]:
            kind = cf.canonical(s["kind"])
            ann_of[s["id"]] = cf.add_box(sym, iid, cf.CATEGORY_ID[kind], s["bbox"], scale,
                                         attributes={"tag": s.get("tag"), "label_source": "drawio"})
        with pdfplumber.open(pdf) as doc:
            for wd in doc.pages[0].extract_words():
                cf.add_box(txt, tid, 1, [wd["x0"], wd["top"], wd["x1"], wd["bottom"]], scale,
                           attributes={"text": wd["text"]})
        s_, tx, ty = transform_of(key)
        polylines = []
        for r in dio["relations"]:
            if r.get("kind") != "physical_connection":
                continue
            pts = [[round((s_ * p[0] + tx) * scale, 1), round((s_ * p[1] + ty) * scale, 1)] for p in crq._rel_points(r)]
            if len(pts) >= 2:
                polylines.append(pts)
        graphs.append({"image": png, "nodes": [ann_of[s["id"]] for s in key["symbols"]],
                       "edges": [{"a": ann_of[c["a"]], "b": ann_of[c["b"]], "flow": c["flow"]}
                                 for c in key["connections"]],
                       "pipes_px": polylines})
    cf.save(sym, os.path.join(out_dir, "symbols.coco.json"))
    cf.save(txt, os.path.join(out_dir, "text.coco.json"))
    cf.save({"schema": "hazop_train_graph", "version": 1, "pages": graphs}, os.path.join(out_dir, "graph.json"))
    return sym, txt, graphs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--samples", default=os.path.join(cf.REPO_ROOT, "resources", "references", "pid-samples"))
    a = ap.parse_args()
    t0 = time.time()
    sym, txt, graphs = export(a.samples, a.out, a.dpi)
    from collections import Counter
    cats = {c["id"]: c["name"] for c in sym["categories"]}
    print("쪽 %d, 기호 %d, 글자 %d, 연결 %d, 배관 선 %d, %.1f초" % (
        len(sym["images"]), len(sym["annotations"]), len(txt["annotations"]),
        sum(len(g["edges"]) for g in graphs), sum(len(g["pipes_px"]) for g in graphs), time.time() - t0))
    print("종류별:", dict(Counter(cats[a["category_id"]] for a in sym["annotations"]).most_common()))


if __name__ == "__main__":
    main()
