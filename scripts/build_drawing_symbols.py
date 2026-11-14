"""그리는 기호 한 벌(resources/library/drawing-symbols/)을 웹이 읽는 도형 자료 하나(symbols.json)로 만든다.

실행: python scripts/build_drawing_symbols.py [--check]
- --check: 만들 자료가 저장소의 symbols.json과 같은지만 본다(다르면 종료 코드 1). 시험(tests/test_drawing_symbols.py)도 같은 함수를 부른다.
- SVG는 path·line·polyline·polygon·circle·rect만 쓴다(글자·그림·스크립트·외부 참조 없음). 색은 currentColor이고 선 굵기는 그릴 때 정한다.
- 웹은 이 도형 자료를 읽어 SVG 요소(createElementNS)로 그린다. HTML 문자열을 넣지 않는다.
"""

import json
import os
import sys
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from hazop.paths import folder  # noqa: E402
SRC = folder("drawing-symbols")
OUT = os.path.join(REPO, "hazop", "shell", "web", "js", "canvas", "symbols.json")
ALLOWED = ("path", "line", "polyline", "polygon", "circle", "rect")
FITS = ("keep", "stretch")
LABELS = ("below", "right", "inside", "none")
NS = "{http://www.w3.org/2000/svg}"


class SymbolError(ValueError):
    pass


def _shapes(path):
    root = ET.parse(path).getroot()
    if root.tag != NS + "svg":
        raise SymbolError("%s: 루트가 svg가 아님" % os.path.basename(path))
    vb = [float(x) for x in (root.get("viewBox") or "").split()]
    if len(vb) != 4 or vb[0] != 0 or vb[1] != 0 or vb[2] <= 0 or vb[3] <= 0:
        raise SymbolError("%s: viewBox는 '0 0 가로 세로'여야 함" % os.path.basename(path))
    shapes = []
    for el in root:
        tag = el.tag.replace(NS, "")
        if tag not in ALLOWED:
            raise SymbolError("%s: 허용하지 않는 요소 <%s>" % (os.path.basename(path), tag))
        attrs = {k: v for k, v in el.attrib.items()}
        for k in attrs:
            if k.startswith("on") or "href" in k or k == "style":
                raise SymbolError("%s: 허용하지 않는 속성 %s" % (os.path.basename(path), k))
        if attrs.pop("stroke", None) != "currentColor" or attrs.pop("fill", None) != "none":
            raise SymbolError("%s: 색은 fill=none, stroke=currentColor만 씀" % os.path.basename(path))
        shapes.append([tag, attrs])
    if not shapes:
        raise SymbolError("%s: 도형이 없음" % os.path.basename(path))
    return vb[2:], shapes


def build():
    """manifest.json과 SVG들에서 도형 자료를 만든다. 틀리면 SymbolError."""
    with open(os.path.join(SRC, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    out, seen = {}, set()
    for row in manifest["symbols"]:
        kind = row["kind"]
        if kind in seen:
            raise SymbolError("kind가 겹침: %s" % kind)
        seen.add(kind)
        if row.get("fit") not in FITS or row.get("label") not in LABELS:
            raise SymbolError("%s: fit·label 값이 틀림" % kind)
        item = {"fit": row["fit"], "label": row["label"], "ports": [[p["x"], p["y"], p["name"]] for p in row.get("ports") or []]}
        if row.get("flow_axis"):
            item["flow_axis"] = row["flow_axis"]
        if row.get("junction"):
            item.update(junction=True, vb=[100, 100], shapes=[])
        else:
            vb, shapes = _shapes(os.path.join(SRC, row["file"]))
            item.update(vb=vb, shapes=shapes)
            for x, y, name in item["ports"]:
                if not (0 <= x <= vb[0] and 0 <= y <= vb[1]):
                    raise SymbolError("%s: 연결점 %s가 그림 밖" % (kind, name))
        out[kind] = item
    if "generic" not in out:
        raise SymbolError("generic 그림이 없음")
    return {"version": manifest.get("version", 1), "symbols": out}


def dump(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def main(argv):
    text = dump(build())
    if "--check" in argv:
        with open(OUT, encoding="utf-8", newline="") as fh:
            same = fh.read().replace("\r\n", "\n") == text
        print("같음" if same else "다름: python scripts/build_drawing_symbols.py 로 다시 만드세요")
        return 0 if same else 1
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("%s (%d종)" % (os.path.relpath(OUT, REPO), len(json.loads(text)["symbols"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
