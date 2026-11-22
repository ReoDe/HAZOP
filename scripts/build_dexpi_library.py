"""DEXPI 2.0.1 클래스 목록(classes-2-0-1.json)을 resources/library/dexpi-schema/에 만든다(HZ-PLN-22 §5.6·§8.1).

사용 예:
  python scripts/build_dexpi_library.py <사양 원문 폴더>
사양 원문 폴더에는 GitLab dexpi/Specification 태그 V2.0.1의 `src/model/Plant/<패키지>/<패키지>.py`를
`<패키지>.py.txt`로(확장자만 바꿔 텍스트로 읽음), 스키마를 그 한 단계 위(--schema로 지정)에서 `DEXPI_XML_Schema.xsd`로 둔다.
원문의 스크립트는 실행하지 않고 클래스 정의 줄만 정규식으로 읽는다. 사양은 CC BY 4.0이다(licenses/dexpi/NOTICE.md).
"""

import argparse
import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402

DEFINITION = re.compile(r"^([A-Z_]+)\.(\w+)\s*=\s*(ABSTRACT|CONCRETE)_CLASS\(\s*(?:superTypes\s*=\s*\[([^\]]*)\])?", re.M)


def read_classes(source_dir):
    classes = {}
    for path in sorted(glob.glob(os.path.join(source_dir, "*.py.txt"))):
        package = os.path.basename(path).split(".")[0]
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in DEFINITION.finditer(text):
            supers = [s.strip().split(".")[-1] for s in (m.group(4) or "").replace("\n", " ").split(",") if s.strip()]
            classes[m.group(2)] = {"package": package, "abstract": m.group(3) == "ABSTRACT", "supers": supers}
    return classes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source_dir")
    args = ap.parse_args(argv)
    classes = read_classes(args.source_dir)
    if not classes:
        ap.error("클래스 정의를 찾지 못함: %s" % args.source_dir)
    out = paths.folder("dexpi-schema")
    os.makedirs(out, exist_ok=True)
    doc = {"dexpi_version": "2.0.1",
           "source": "GitLab dexpi/Specification V2.0.1 src/model/Plant/{Piping,ProcessEquipment,Instrumentation}",
           "license": "CC BY 4.0, DEXPI e.V. (licenses/dexpi/NOTICE.md)",
           "classes": dict(sorted(classes.items()))}
    with open(os.path.join(out, "classes-2-0-1.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("클래스 %d개 -> %s" % (len(classes), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
