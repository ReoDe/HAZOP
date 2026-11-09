"""APR1400 DCD 도면 연결 표시(화살표) 검출 시험. 실행: python -m unittest tests.test_apr1400_connectors

자료: tests/fixtures/apr1400/pdf/ 5.4.12-1(가로 2·세로 1), 9.3.3-1 시트 7(세로 3·계통 약어 없는 것 2).
정답: tests/fixtures/apr1400/answer_key/(렌더한 그림을 눈으로 읽어 만듦, SOURCE.md). 쪽끼리 짝짓기는 시험하지 않는다.
pdfplumber가 있을 때만 돈다(결정 D1).
"""

import importlib.util
import os
import re
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

from test_apr1400_extract import HAS_PDFPLUMBER, load_page  # noqa: E402

CODE_RE = re.compile(r"^([A-Z]{2,3}):")


def continuation_near(ex, bbox, margin=2.0):
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    for n in ex["nodes"]:
        g = n.get("geometry")
        if n.get("kind") == "continuation" and g and g["x"] - margin <= cx <= g["x"] + g["width"] + margin \
                and g["y"] - margin <= cy <= g["y"] + g["height"] + margin:
            return n
    return None


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(결정 D1)")
class ConnectorArrows(unittest.TestCase):
    """화살표 모양 연결 표시는 continuation 노드가 되고, 'CV:RDT'처럼 계통 약어가 붙은 표시는 그 약어를 to_system에 둔다.
    세로로 쓴 표시(글자를 90° 돌림)도 같다."""

    @classmethod
    def setUpClass(cls):
        cls.pages = [load_page(12), load_page(62)]

    def test_every_key_arrow_is_a_continuation(self):
        for ex, key in self.pages:
            for item in key["connectors"]:
                self.assertIsNotNone(continuation_near(ex, item["bbox"]), "%s %s" % (key["drawing"], item["label"]))

    def test_system_code_is_read_including_rotated_labels(self):
        for ex, key in self.pages:
            for item in key["connectors"]:
                m = CODE_RE.match(item["label"])
                n = continuation_near(ex, item["bbox"])
                got = n and n["attributes"].get("to_system")
                self.assertEqual(got, m and m.group(1), "%s %s" % (key["drawing"], item["label"]))

    def test_rotated_text_is_not_reversed(self):
        ex, _ = self.pages[0]
        texts = " ".join(t["text"].replace("\n", " ") for t in ex["texts"]) + " " + \
            " ".join(n["label_text"].replace("\n", " ") for n in ex["nodes"])
        self.assertIn("CV:RDT", texts)
        self.assertNotIn("TDR:VC", texts.replace(" ", ""))

    def test_to_label_keeps_the_full_label_text(self):
        ex, key = self.pages[1]
        item = next(i for i in key["connectors"] if i["label"].startswith("WV:LRS CHEMICAL"))
        self.assertEqual(continuation_near(ex, item["bbox"])["attributes"].get("to_label"), "WV:LRS CHEMICAL WASTE TANK")


class ChevronShape(unittest.TestCase):
    """화살표 모양 판정(DCD 범례 그림 1.7-1): 꼬리가 파인 갈매기(같은 그림 다른 시트)와 양 끝이 뾰족한 육각형(다른 그림).
    파인 꼭짓점이 둘인 도형(10.4.5-1 세로 펌프 기둥)과 끝이 가운데가 아닌 볼록 육각형은 아니다."""

    @staticmethod
    def body(pts):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return {"pts": pts + [pts[0]], "closed": True, "curved": False, "bbox": (min(xs), min(ys), max(xs), max(ys))}

    def test_notched_arrow_is_a_chevron(self):
        from hazop.extract.adapters import pdf_vector
        self.assertTrue(pdf_vector._is_chevron(self.body(
            [(182.1, 122.2), (186.3, 118.8), (182.1, 115.5), (211.5, 115.5), (215.7, 118.8), (211.5, 122.2)])))

    def test_double_pointed_hexagon_is_a_connector(self):
        """5.1.2-3 'SHEET 1' RC 표시(28.4×5.7pt)."""
        from hazop.extract.adapters import pdf_vector
        self.assertTrue(pdf_vector._is_chevron(self.body(
            [(3.6, 0.0), (24.9, 0.0), (28.4, 2.8), (24.9, 5.7), (3.6, 5.7), (0.0, 2.8)])))

    def test_two_notches_or_off_centre_tips_are_not(self):
        from hazop.extract.adapters import pdf_vector
        two_notches = [(0, 0), (3, 3), (0, 6), (30, 6), (27, 3), (30, 0)]
        off_centre = [(0, 1), (3, 0), (27, 0), (30, 5), (27, 6), (3, 6)]
        self.assertFalse(pdf_vector._is_chevron(self.body(two_notches)))
        self.assertFalse(pdf_vector._is_chevron(self.body(off_centre)))


if __name__ == "__main__":
    unittest.main()
