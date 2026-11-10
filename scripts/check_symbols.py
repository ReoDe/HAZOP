"""기호 사전 검사(기획서/PID-기호사전.md §4.6). 오류가 있으면 종료 코드 1.

  python scripts/check_symbols.py [--library <사전 폴더>]

오류: 사전을 읽지 못함(형식·id·파일 이름·중복), 켜진 항목의 kind가 타입 레지스트리에 없음, 노드가 되지 않는 역할
(actuator·annotation·drop)에 kind, 레지스트리 속성의 허용값 밖 값, 예시 그림 경로가 없음.
레지스트리 범주 이름과 다른 category도 오류다.
경고: 꺼진 항목(레지스트리 반영 대기), 레지스트리에 없는 속성 이름, 글자 조건 없이는 구분되지 않는 두 항목
(구성 키가 같고 크기 허용이 겹치며 견본 거리가 margin 미만).
"""

import argparse
import itertools
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import symbols  # noqa: E402
from hazop.kg.schema import REGISTRY  # noqa: E402

NON_NODE_ROLES = ("actuator", "drop")


def category_label(kind):
    cid = REGISTRY.kind_class.get(kind)
    while cid and REGISTRY.classes[cid].get("parent") not in (None, "plant_item"):
        cid = REGISTRY.classes[cid]["parent"]
    return REGISTRY.label(cid) if cid else None


def check(root):
    errors, warnings = [], []
    try:
        lib = symbols.Library.load(root)
    except symbols.SymbolLibraryError as e:
        return ["사전을 읽지 못함: %s" % e], warnings, None
    kinds = REGISTRY.kind_category()
    for e in sorted(lib.entries.values(), key=lambda e: e.id):
        if e.kind is not None and e.kind not in kinds:
            (errors if e.enabled else warnings).append(
                "%s: kind %r가 레지스트리에 없음%s" % (e.id, e.kind, "" if e.enabled else "(꺼진 항목, 레지스트리 반영 대기)"))
        if e.role in NON_NODE_ROLES and e.kind is not None:
            errors.append("%s: role %s는 노드가 되지 않으므로 kind를 두지 않는다" % (e.id, e.role))
        if e.role in ("symbol", "continuation") and e.kind is None and e.kind_from is None:
            errors.append("%s: role %s에는 kind나 kind_from이 있어야 한다" % (e.id, e.role))
        for prop, value in sorted(e.attributes.items()):
            spec = REGISTRY.properties.get(prop)
            if spec is None:
                warnings.append("%s: 속성 %r는 레지스트리에 없음(사전 안에서만 쓰임)" % (e.id, prop))
            elif spec.get("type") == "enum" and value not in spec.get("values", ()):
                errors.append("%s: 속성 %s=%r는 허용값 %s 밖" % (e.id, prop, value, spec["values"]))
        for t in e.templates:
            for prop, value in sorted(t.set_attributes.items()):
                spec = REGISTRY.properties.get(prop)
                if spec and spec.get("type") == "enum" and value not in spec.get("values", ()):
                    errors.append("%s: 견본 속성 %s=%r는 허용값 %s 밖" % (e.id, prop, value, spec["values"]))
        img = e.raw.get("image")
        if img and not os.path.isfile(symbols.image_path(symbols.bundle_dir(root, e.bundle, e.id.split(".", 1)[0]), img)):
            errors.append("%s: 예시 그림이 없음(%s)" % (e.id, img))
        if e.kind and e.kind in kinds and e.category != category_label(e.kind):
            errors.append("%s: category %r ≠ 레지스트리 범주 %r" % (e.id, e.category, category_label(e.kind)))
        if not e.enabled:
            warnings.append("%s: 꺼져 있음(enabled=false)" % e.id)

    grid = [(e, t) for e in lib.entries.values() if e.enabled for t in e.templates if t.shape == "grid"]
    seen = set()
    for (ea, ta), (eb, tb) in itertools.combinations(sorted(grid, key=lambda x: x[0].id), 2):
        if ea.id == eb.id or ta.comp_key != tb.comp_key or (ea.id, eb.id) in seen:
            continue
        span = ta.size_ratio * tb.size_ratio  # 두 허용 구간 [s/r, s*r]이 겹치는 조건
        if not (1 / span <= ta.size / tb.size <= span):
            continue
        _, ca, da = ta.variants[0]
        d = min(symbols.chamfer(ca, da, cb, db) for _, cb, db in tb.variants)
        if d < lib.margin and not (ea.text_inside or eb.text_inside or ea.text_forbid or eb.text_forbid):
            warnings.append("%s ↔ %s: 견본 거리 %.2f칸 < %.2f, 글자 조건 없이는 구분되지 않음(애매함으로 남음)"
                            % (ea.id, eb.id, d, lib.margin))
            seen.add((ea.id, eb.id))
    return errors, warnings, lib


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--library")
    a = ap.parse_args()
    root = a.library or paths.folder("기호")
    errors, warnings, lib = check(root)
    if lib is not None:
        print("묶음 %s, 항목 %d(켜짐 %d)" % (lib.versions, len(lib.entries), sum(e.enabled for e in lib.entries.values())))
    for w in warnings:
        print("경고:", w)
    for e in errors:
        print("오류:", e)
    print("오류 %d, 경고 %d" % (len(errors), len(warnings)))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
