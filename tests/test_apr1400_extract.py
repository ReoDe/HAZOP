"""APR1400 DCD 실제 도면 한 쪽으로 PDF 추출을 시험한다. 실행: python -m unittest tests.test_apr1400_extract

자료: tests/fixtures/apr1400/pdf/(NRC 공개 DCD Rev.3, 출처 tests/fixtures/apr1400/SOURCE.md),
정답: tests/fixtures/apr1400/answer_key/(렌더한 그림을 눈으로 읽어 만듦, SOURCE.md). pdfplumber가 있을 때만 돈다(결정 D1).
"""

import importlib.util
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.extract.adapters import pdf_vector  # noqa: E402

FIX = os.path.join(REPO_ROOT, "tests", "fixtures", "apr1400")
HAS_PDFPLUMBER = importlib.util.find_spec("pdfplumber") is not None


def load_page(seq):
    key_path = next(os.path.join(FIX, "answer_key", f) for f in os.listdir(os.path.join(FIX, "answer_key"))
                    if f.startswith("%03d_" % seq))
    with open(key_path, encoding="utf-8") as fh:
        key = json.load(fh)
    return pdf_vector.extract(os.path.join(FIX, "pdf", key["source_file"]), page=0), key


def node_at(ex, bbox):
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    hits = [n for n in ex["nodes"] if n.get("geometry") and
            n["geometry"]["x"] <= cx <= n["geometry"]["x"] + n["geometry"]["width"] and
            n["geometry"]["y"] <= cy <= n["geometry"]["y"] + n["geometry"]["height"]]
    return min(hits, key=lambda n: n["geometry"]["width"] * n["geometry"]["height"]) if hits else None


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(결정 D1)")
class InstrumentTags(unittest.TestCase):
    """계기 기호(원·비석 모양) 안 글자 '기능 문자 / 루프 번호'가 그 노드의 태그가 된다. 계통 접두가 없는 도면이다."""

    @classmethod
    def setUpClass(cls):
        cls.ex, cls.key = load_page(12)

    def test_every_key_instrument_gets_its_bubble_text_as_tag(self):
        got = {}
        for item in self.key["instruments"]:
            n = node_at(self.ex, item["bbox"])
            got[item["tag"]] = n and n["tag"]
        want = {t: t.replace(" ", "-") for t in got}
        self.assertEqual(got, want)

    def test_instrument_symbol_kinds(self):
        """PT는 전송기. TEW(보호관, DCD 범례 1.7-1에서 TE와 다름)는 맞는 종류가 레지스트리에 없어 종류를 비우고
        계기 모양으로만 태그를 붙인다."""
        kinds = {item["tag"]: node_at(self.ex, item["bbox"])["kind"] for item in self.key["instruments"]}
        self.assertEqual(kinds, {"TEW 106": None, "PT 106": "transmitter", "TEW 107": None, "TEW 108": None})

    def test_no_tag_outside_the_text_layer(self):
        words = {w.replace("-", "") for n in self.ex["texts"] for w in (n.get("text") or "").split()}
        bubbles = {it["tag"].replace(" ", "") for it in self.key["instruments"]}
        for n in self.ex["nodes"]:
            if n.get("tag"):
                self.assertIn(n["tag"].replace("-", ""), words | bubbles, n["tag"])


class PrefixInference(unittest.TestCase):
    """같은 쪽 태그에서 계통 접두를 빌리는 규칙(_assign_tags (b)): 태그 하나뿐인 접두는 빌리지 않는다(9.2.2-1 시트 4의
    'QIAS-PV1686' 한 개가 계기 18개에 'QIAS-'를 붙인 결함)."""

    @staticmethod
    def nodes(labels, size=12.0):
        return [{"kind": kind, "category": cat, "label_text": text, "source_object_id": "s%d" % i,
                 "local_id": "n%d" % i, "evidence": {}, "geometry": {"x": 0, "y": 0, "width": size, "height": size}}
                for i, (kind, cat, text) in enumerate(labels)]

    def tags(self, labels, instruments=None):
        nodes = self.nodes(labels)
        ids = {n["local_id"] for n in nodes if n["category"] == "instrument"} if instruments is None else instruments
        pdf_vector._assign_tags(nodes, [], ids)
        return [n["tag"] for n in nodes]

    def test_single_tag_does_not_lend_its_prefix(self):
        got = self.tags([("manual_valve", "valve", "QIAS-PV1686\nBID"), ("indicator", "instrument", "FI\n237"),
                         ("indicator", "instrument", "FI\n238")])
        self.assertEqual(got, ["QIAS-PV1686", "FI-237", "FI-238"])

    def test_shared_prefix_is_still_borrowed(self):
        got = self.tags([("pump", "equipment", "RC-PP01"), ("tank", "equipment", "RC-TK01"),
                         ("transmitter", "instrument", "PT\n110")])
        self.assertEqual(got, ["RC-PP01", "RC-TK01", "RC-PT110"])

    def test_unclassified_instrument_shape_still_gets_its_bubble_tag(self):
        got = self.tags([(None, None, "AX\n134")], instruments={"n0"})
        self.assertEqual(got, ["AX-134"])

    def test_valve_number_next_to_a_small_dot_is_not_an_instrument_tag(self):
        """9.3.3-1 시트 1 체크밸브 힌지 점(0.9pt) 옆 'V1006', 9.4.1-1 댐퍼 축 점(6pt) 옆 'Y0013A'(검토 지적)."""
        for label, size in (("V1006", 0.9), ("Y0013A", 6.0), ("V5402", 12.0)):
            nodes = self.nodes([(None, None, label)], size=size)
            pdf_vector._assign_tags(nodes, [], {"n0"})
            self.assertIsNone(nodes[0]["tag"], label)


if __name__ == "__main__":
    unittest.main()
