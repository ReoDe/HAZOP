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


class BareSystemCode(unittest.TestCase):
    """쌍점 없이 화살표 바로 옆에 두 글자만 쓴 계통 약어(범례 1.7-1 'MS / SHEET 2"A"', 10.4.2-1 'WI / SHEET 2"B"')."""

    class Arrow:
        bbox = (457.0, 150.0, 488.0, 156.0)

    def attrs(self, text, top, own='SHEET 2 "B"'):
        from hazop.extract.adapters import pdf_vector
        block = {"text": text, "bbox": (458.0, top, 466.0, top + 3.3)}
        own_block = {"text": own, "bbox": (462.0, 151.0, 480.0, 155.0)}
        return pdf_vector._continuation_attributes(self.Arrow(), [block, own_block], dict(pdf_vector.PARAMS), own_block)

    def test_two_letters_right_above_the_arrow_are_the_system(self):
        self.assertEqual(self.attrs("WI", 145.0).get("to_system"), "WI")

    def test_valve_position_or_far_letters_are_not(self):
        self.assertEqual(self.attrs("FC", 145.0), {})
        self.assertEqual(self.attrs("WI", 135.0), {})
        self.assertEqual(self.attrs("RDT", 145.0), {})

    def test_only_next_to_a_sheet_reference(self):
        """9.3.3-1 시트 7 'MAKE-UP DEMIN. WATER' 화살표 옆 밸브 표기 'DE'는 계통 약어가 아니다."""
        self.assertEqual(self.attrs("DE", 145.0, own="MAKE-UP\nDEMIN. WATER"), {})

    def test_code_line_inside_the_arrow_text_is_the_system(self):
        """037쪽 'CC\\nSHEET 4', 080쪽 'VO\\nSHEET 1 "A"': 약어와 시트 표기가 한 문단이다."""
        self.assertEqual(self.attrs("", 135.0, own="CC\nSHEET 4"), {"to_system": "CC", "to_label": "CC SHEET 4"})
        self.assertEqual(self.attrs("", 135.0, own="AA\nB"), {})


def arrow_node(local_id, box, label):
    return {"local_id": local_id, "kind": "continuation", "label_text": label, "attributes": {},
            "geometry": {"x": box[0], "y": box[1], "width": box[2] - box[0], "height": box[3] - box[1]}}


class NameAboveArrow(unittest.TestCase):
    """134쪽 'ACID ADDITION' 위 'SHEET 4"Q"' 화살표, 051쪽 'CD CONDENSER A\\nHOTWELL' 위 'SHEET 1' 화살표: 화살표 글자 자리에
    맞닿은 이름 문단이 행선이다. 정답지 규약처럼 '이름 / 자기 글자'로 적는다."""

    def run_names(self, nodes, blocks):
        from hazop.extract.adapters.pdf_vector_connectors import attach_continuation_names
        attach_continuation_names(nodes, blocks, list(range(len(blocks))), 1.5)
        return [n["attributes"] for n in nodes]

    def test_touching_name_above_is_the_destination(self):
        got = self.run_names([arrow_node("a", (476, 122, 506, 128), 'SHEET 4"Q"')],
                             [{"text": "ACID ADDITION", "bbox": (480, 119, 503, 122)}])
        self.assertEqual(got, [{"to_label": 'ACID ADDITION / SHEET 4"Q"'}])

    def test_leading_two_letter_code_is_the_system(self):
        got = self.run_names([arrow_node("a", (218, 143, 250, 150), "SHEET 1")],
                             [{"text": "CD CONDENSER A\nHOTWELL", "bbox": (218, 137, 248, 143)}])
        self.assertEqual(got, [{"to_system": "CD", "to_label": "CD CONDENSER A HOTWELL / SHEET 1"}])

    def test_rotated_name_left_of_an_upright_arrow(self):
        got = self.run_names([arrow_node("a", (395, 179, 401, 207), 'SHEET 3"M"')],
                             [{"text": "DEMIN. WATER", "bbox": (392, 184, 395, 207)}])
        self.assertEqual(got, [{"to_label": 'DEMIN. WATER / SHEET 3"M"'}])

    def test_not_attached_when_far_below_or_shared(self):
        self.assertEqual(self.run_names([arrow_node("a", (476, 133, 506, 139), 'SHEET 4"R"')],
                                        [{"text": "ACID ADDITION", "bbox": (480, 119, 503, 122)}]), [{}])
        self.assertEqual(self.run_names([arrow_node("a", (476, 122, 506, 128), "SHEET 4")],
                                        [{"text": "TO RMS", "bbox": (476, 126, 506, 132)}]), [{}])
        # 이름 문단 하나에 두 화살표가 같은 거리로 맞닿음: 어느 쪽 행선인지 모른다
        self.assertEqual(self.run_names([arrow_node("a", (476, 122, 490, 128), "SHEET 4"),
                                         arrow_node("b", (492, 122, 506, 128), "SHEET 5")],
                                        [{"text": "ACID ADDITION", "bbox": (485, 119, 497, 122)}]), [{}, {}])

    def test_arrow_that_already_has_a_system_keeps_it(self):
        node = arrow_node("a", (476, 122, 506, 128), "SHEET 4")
        node["attributes"] = {"to_system": "DE", "to_label": "DE:SUMP"}
        self.assertEqual(self.run_names([node], [{"text": "ACID ADDITION", "bbox": (480, 119, 503, 122)}]),
                         [{"to_system": "DE", "to_label": "DE:SUMP"}])


class WaveBreak(unittest.TestCase):
    """077·080쪽 배관 끝 물결 끊김 둘(공급·환수) 옆 'FROM & TO\\nWI': 두 물결 모두 WI로 가는 연결 표시다."""

    def test_bent_strokes_only(self):
        from hazop.extract.adapters.pdf_vector_connectors import is_wave_mark
        s = [{"pts": [(311.61, 261.01), (311.88, 259.77), (311.19, 259.35)]},
             {"pts": [(312.03, 262.67), (311.21, 261.68), (311.61, 261.01)]}]
        self.assertTrue(is_wave_mark(s))
        self.assertFalse(is_wave_mark(s + [{"pts": [(0, 0), (5, 0)]}]))
        self.assertFalse(is_wave_mark([{"pts": [(0, 0), (1, 0), (2, 0)]}]))

    def test_both_waves_take_the_shared_text_and_other_codes_block(self):
        from hazop.extract.adapters.pdf_vector_connectors import wave_break_targets
        text = {"text": "FROM & TO\nWI", "bbox": (314, 262, 335, 270)}
        got = wave_break_targets([("a", (311, 259, 312, 263)), ("b", (311, 267, 312, 270))], [text], 15.0)
        self.assertEqual(got, {k: {"to_system": "WI", "to_label": "FROM & TO WI"} for k in "ab"})
        other = {"text": "FROM & TO\nWO", "bbox": (314, 272, 335, 280)}
        self.assertEqual(wave_break_targets([("b", (311, 267, 312, 270))], [text, other], 15.0), {})
        self.assertEqual(wave_break_targets([("a", (311, 259, 312, 263))], [{"text": "FROM & TO\nFC", "bbox": text["bbox"]}],
                                            15.0), {})


if __name__ == "__main__":
    unittest.main()
