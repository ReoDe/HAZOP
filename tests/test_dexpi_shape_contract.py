"""노드의 geometry.shape 계약(HZ-PLN-22 §5.3.1) 시험: 규격의 견본이 읽기·쓰기 코드가 만드는 값과 같은지 본다.

실행: python -m unittest tests.test_dexpi_shape_contract
"""

import json
import math
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.export import dexpi_diagram  # noqa: E402
from hazop.extract.adapters import dexpi_shape  # noqa: E402
from tests.test_dexpi_picture import pump, usage, with_pump  # noqa: E402

SPEC = os.path.join(REPO_ROOT, "docs", "specs", "dexpi-exchange.md")
SAMPLES = os.path.join(REPO_ROOT, "tests", "fixtures", "dexpi", "geometry-shape-samples.json")
CORNERS = {"left_top": (-0.5, -0.5), "right_top": (0.5, -0.5), "right_bottom": (0.5, 0.5), "left_bottom": (-0.5, 0.5)}


def by_the_formula(geometry, corner):
    """규격 §5.3.1의 셈만으로 구한 모서리 자리. 읽는 쪽(정리된 보기)이 따를 셈이다."""
    s = geometry["shape"]
    u, v = corner[0] * s["width"] * (-1.0 if s["mirrored"] else 1.0), corner[1] * s["height"]
    t = math.radians(s["rotation"])
    return (geometry["x"] + geometry["width"] / 2.0 + u * math.cos(t) - v * math.sin(t),
            geometry["y"] + geometry["height"] / 2.0 + u * math.sin(t) + v * math.cos(t))


class ShapeContractTest(unittest.TestCase):

    def setUp(self):
        with open(SAMPLES, encoding="utf-8") as fh:
            self.doc = json.load(fh)
        self.samples = self.doc["samples"]

    def node(self, sample):
        u = sample["usage"]
        return pump(with_pump(usage(u["x"], u["y"], u["scale_x"], u["scale_y"], u["rotation"], "true" if u["mirrored"] else "false")))

    def test_reading_the_file_gives_the_sample_geometry(self):
        for s in self.samples:
            self.assertEqual(self.node(s)["geometry"], s["geometry"], s["name"])

    def test_corners_are_where_the_reader_puts_them(self):
        """모양의 모서리에 아주 작은 상자를 두고 dexpi_shape.placed가 놓는 자리와 견준다."""
        x0, y0, x1, y1 = self.doc["local_bounds"]
        e = 1e-6
        for s in self.samples:
            p = dexpi_shape.Placement(**s["usage"])
            for name, (cx, cy) in CORNERS.items():
                x, y = (x0 + x1) / 2.0 + cx * (x1 - x0), (y0 + y1) / 2.0 + cy * (y1 - y0)
                bx, by, w, h = dexpi_shape.placed(dexpi_shape.Bounds(x - e, y - e, x + e, y + e, 0.0), p)
                self.assertLess(math.dist((bx + w / 2.0, by + h / 2.0), s["corners"][name]), 1e-6, (s["name"], name))

    def test_the_formula_of_the_spec_gives_the_same_corners(self):
        for s in self.samples:
            for name, at in CORNERS.items():
                self.assertLess(math.dist(by_the_formula(s["geometry"], at), s["corners"][name]), 1e-9, (s["name"], name))

    def test_turning_before_the_mirror_would_miss_the_corner(self):
        s = next(x for x in self.samples if x["usage"]["mirrored"])
        wrong = json.loads(json.dumps(s["geometry"]))
        wrong["shape"]["rotation"] = 360.0 - wrong["shape"]["rotation"]  # 돌린 뒤 뒤집은 것과 같다
        self.assertGreater(math.dist(by_the_formula(wrong, CORNERS["left_top"]), s["corners"]["left_top"]), 1.0)

    def test_writing_again_uses_the_center_of_the_box_and_the_size_before_the_turn(self):
        for s in self.samples:
            g = s["geometry"]
            p = dexpi_diagram.source_placement({"geometry": g}, None, "dexpi")
            self.assertEqual(p, dexpi_shape.Placement(g["x"] + g["width"] / 2.0, g["y"] + g["height"] / 2.0, g["shape"]["width"],
                                                      g["shape"]["height"], g["shape"]["rotation"], g["shape"]["mirrored"]), s["name"])
            self.assertEqual(dexpi_shape.placed(dexpi_shape.UNIT, p), (g["x"], g["y"], g["width"], g["height"]), s["name"])

    def test_the_spec_shows_the_same_samples(self):
        with open(SPEC, encoding="utf-8") as fh:
            section = fh.read().split("#### 5.3.1", 1)[1].split("### 5.4", 1)[0]
        shown = [json.loads(part.split("```", 1)[0]) for part in section.split("```json")[1:]]
        self.assertEqual(shown, [s["geometry"] for s in self.samples])


if __name__ == "__main__":
    unittest.main()
