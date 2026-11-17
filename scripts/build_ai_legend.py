"""AI 검토 그림 입력의 표준 기호 범례판(resources/library/ai-legend/)을 만든다.

실행: python scripts/build_ai_legend.py [--check]
- 직접 그린 표준 기호 그림(resources/library/drawing-symbols, manifest.json + SVG) 가운데 답 목록(ai_images.answer_kinds)에 든
  종류마다 한 칸을 그려 범례판 PNG(symbols-01.png …)와 표지(legend.json)를 쓴다. 칸 순서와 판 꼴은 도면 견본 판과 같다
  (ai_images.boards_of).
- 어느 도면 조각도 쓰지 않는다. 도면에서 오린 견본 판(정답지 판·프로젝트 판)은 저장소에 두지 않는다.
- 표지의 inputs_sha256은 답 목록과 그 종류들의 SVG 바이트로 만든 값이다. --check는 이 값과 PNG가 지금 입력과 맞는지만
  본다(다르면 종료 코드 1). 시험(tests/test_ai_images_legend.py)도 같은 함수를 부른다.
- SVG를 그리는 데 PySide6(QtSvg)를 쓴다. 앱은 만든 PNG만 읽는다.
"""

import argparse
import hashlib
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from hazop import paths  # noqa: E402
from hazop.extract import ai_images  # noqa: E402

SIDE = 160          # 기호 그림의 긴 변(px)
MARGIN = 8          # 그림 둘레 여백(px)
STROKE = 2.5        # 선 굵기(viewBox 단위). 기호 그림은 굵기를 그릴 때 정한다
PREFIX = "symbols"


def _symbols():
    with open(paths.folder("drawing-symbols", "manifest.json"), encoding="utf-8") as fh:
        return {r["kind"]: r["file"] for r in json.load(fh)["symbols"] if r.get("file")}


def inputs():
    """(답 목록, {kind: SVG 바이트}, inputs_sha256)."""
    files = _symbols()
    kinds = ai_images.answer_kinds()
    svgs = {}
    for k in kinds:
        if k in files:
            with open(paths.folder("drawing-symbols", files[k]), "rb") as fh:
                svgs[k] = fh.read()
    h = hashlib.sha256(json.dumps([kinds, SIDE, MARGIN, STROKE, list(ai_images.CELL), ai_images.BOARD_COLS,
                                   ai_images.BOARD_CELLS]).encode("utf-8"))
    for k in sorted(svgs):
        h.update(k.encode("utf-8") + b"\0" + svgs[k] + b"\0")
    return kinds, svgs, h.hexdigest()


def render(svg):
    """SVG 바이트 -> 흰 바탕 검은 선 PIL 그림."""
    from PIL import Image
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        render.app = QGuiApplication([])
    text = svg.decode("utf-8").replace("currentColor", "#000000")
    text = text.replace("<svg ", '<svg stroke-width="%s" ' % STROKE, 1)
    r = QSvgRenderer(QByteArray(text.encode("utf-8")))
    vb = r.viewBoxF()
    s = SIDE / max(vb.width(), vb.height())
    w, h = int(round(vb.width() * s)), int(round(vb.height() * s))
    img = QImage(w + 2 * MARGIN, h + 2 * MARGIN, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(MARGIN, MARGIN, w, h))
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGB")


def build():
    """-> (표지 dict, [PNG 바이트])."""
    kinds, svgs, sha = inputs()
    boards, order = ai_images.boards_of({k: [render(svg)] for k, svg in svgs.items()})
    index = {"note": "AI 검토 그림 입력의 표준 기호 범례판. scripts/build_ai_legend.py가 만든다. 손으로 고치지 않는다.",
             "source": "resources/library/drawing-symbols", "inputs_sha256": sha, "answer_kinds": kinds,
             "cells": order, "per_kind": 1,
             "boards": ["%s-%02d.png" % (PREFIX, i) for i in range(1, len(boards) + 1)]}
    return index, boards


def stale():
    """저장소 판이 지금 입력과 다르면 사유 목록, 같으면 []."""
    try:
        with open(paths.folder("ai-legend", ai_images.LEGEND_INDEX), encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError):
        return ["표지(legend.json)가 없거나 읽을 수 없다"]
    out = []
    kinds, _svgs, sha = inputs()
    if index.get("inputs_sha256") != sha:
        out.append("입력(답 목록·기호 SVG·판 꼴)이 바뀌었다")
    if index.get("answer_kinds") != kinds:
        out.append("답 목록이 다르다")
    missing = [f for f in index.get("boards") or [] if not os.path.isfile(paths.folder("ai-legend", f))]
    if missing or not index.get("boards"):
        out.append("범례판 PNG가 없다: %s" % ", ".join(missing))
    return out


def write():
    index, boards = build()
    out = paths.folder("ai-legend")
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.startswith(PREFIX + "-") and f.endswith(".png") and f not in index["boards"]:
            os.remove(os.path.join(out, f))
    for f, png in zip(index["boards"], boards):
        with open(os.path.join(out, f), "wb") as fh:
            fh.write(png)
    with open(os.path.join(out, ai_images.LEGEND_INDEX), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return index, boards


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="저장소 판이 지금 입력과 맞는지만 본다")
    args = ap.parse_args(argv)
    if args.check:
        why = stale()
        print("범례판이 낡았다: %s. python scripts/build_ai_legend.py로 다시 만든다" % "; ".join(why) if why else "범례판 최신")
        return 1 if why else 0
    index, boards = write()
    print("범례판 %d장(칸 %d, %d바이트): %s" % (len(boards), len(index["cells"]), sum(map(len, boards)),
                                         paths.folder_rel("ai-legend")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
