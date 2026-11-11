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

from hazop import paths  # noqa: E402
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


def center(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def node_box(n):
    g = n["geometry"]
    return g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"]


def within(point, box, slack=0.0):
    return box[0] - slack <= point[0] <= box[2] + slack and box[1] - slack <= point[1] <= box[3] + slack


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(결정 D1)")
class ClosedValves(unittest.TestCase):
    """몸통을 검게 칠한 밸브는 정상 운전 중 닫힘이다(DCD 범례 1.7-1 1/4). 그 자리에는 normal_position이 NC인 밸브 노드가
    있어야 하고, 다른 노드는 NC가 아니어야 한다. 정답은 answer_key의 closed_valves(렌더한 그림을 눈으로 읽음)다."""

    PAGES = (12, 62)
    SLACK = 3.0  # 정답 상자는 검게 칠한 부분만이다. 노드 상자에는 가운데 점이나 맞닿은 판이 더해질 수 있다

    @classmethod
    def setUpClass(cls):
        cls.pages = {seq: load_page(seq) for seq in cls.PAGES}

    def closed_nodes(self, ex):
        return [n for n in ex["nodes"] if (n.get("attributes") or {}).get("normal_position") == "NC"]

    def test_every_filled_valve_body_is_a_normally_closed_valve(self):
        for seq, (ex, key) in self.pages.items():
            closed = self.closed_nodes(ex)
            missing = [item.get("number") or item["tag"] for item in key["closed_valves"]
                       if not any(within(center(node_box(n)), item["bbox"], self.SLACK) for n in closed)]
            self.assertEqual(missing, [], "%03d쪽: 닫힌 밸브로 읽지 못한 것" % seq)

    def test_nothing_else_is_read_as_normally_closed(self):
        for seq, (ex, key) in self.pages.items():
            extra = [(n["local_id"], n["kind"], [round(v, 1) for v in node_box(n)]) for n in self.closed_nodes(ex)
                     if not any(within(center(node_box(n)), item["bbox"], self.SLACK) for item in key["closed_valves"])]
            self.assertEqual(extra, [], "%03d쪽: 닫힌 밸브가 아닌데 NC로 읽은 것" % seq)

    def test_half_filled_valves_are_not_closed(self):
        ex, key = self.pages[62]
        self.assertEqual(len(key["half_filled_valves"]), 8)
        for item in key["half_filled_valves"]:
            near = [n for n in self.closed_nodes(ex) if within(center(node_box(n)), item["bbox"], 6.0)]
            self.assertEqual(near, [], item["tag"])

    def test_closed_valve_kind_is_a_valve_or_left_open(self):
        """구동부가 붙은 몸통은 구동 방식을 정하기 전까지 종류를 비울 수 있다. 밸브가 아닌 종류가 붙으면 안 된다."""
        from hazop.extract import rules
        for seq, (ex, _) in self.pages.items():
            kinds = {n["kind"] for n in self.closed_nodes(ex)}
            self.assertEqual({k for k in kinds if k is not None and rules.KIND_CATEGORY.get(k) != "valve"}, set(), seq)

    def test_small_closed_valve_stands_between_its_pipes(self):
        """012쪽 418번 밸브는 삼각형 둘과 점을 따로 칠한 작은 몸통이다. 화살촉으로 읽으면 위아래 배관이 밸브 없이 이어진다."""
        ex, key = self.pages[12]
        item = next(i for i in key["closed_valves"] if i["number"] == "418")
        (valve,) = [n for n in self.closed_nodes(ex) if within(center(node_box(n)), item["bbox"], self.SLACK)]
        ends = [e for r in ex["relations"] if r["kind"] == "physical_connection" for e in r["endpoints"]
                if e["node_local_id"] == valve["local_id"]]
        self.assertGreaterEqual(len(ends), 2)
        self.assertEqual(valve["attributes"]["valve_type"], "globe")

    def test_each_closed_valve_is_one_node_with_valve_category(self):
        """정답의 닫힌 밸브 하나에 NC 노드가 정확히 하나이고, 종류를 못 정했어도 분류는 밸브다."""
        for seq, (ex, key) in self.pages.items():
            for item in key["closed_valves"]:
                hits = [n for n in self.closed_nodes(ex) if within(center(node_box(n)), item["bbox"], self.SLACK)]
                self.assertEqual(len(hits), 1, (seq, item))
                self.assertEqual(hits[0]["category"], "valve", (seq, item))

    def test_every_closed_valve_stands_on_a_pipe(self):
        """정답의 닫힌 밸브 15개는 모두 배관 위에 있다. 물리 배관 끝이 둘 이상 닿아야 한다."""
        for seq, (ex, key) in self.pages.items():
            loose = []
            for item in key["closed_valves"]:
                (valve,) = [n for n in self.closed_nodes(ex) if within(center(node_box(n)), item["bbox"], self.SLACK)]
                ends = [e for r in ex["relations"] + ex["unresolved_connectors"] if r["kind"] == "physical_connection"
                        for e in r["endpoints"] if e["node_local_id"] == valve["local_id"]]
                if len(ends) < 2:
                    loose.append((item.get("number") or item["tag"], len(ends)))
            self.assertEqual(loose, [], seq)

    def test_pipe_runs_on_through_the_reducer_drawn_against_a_closed_valve(self):
        """012쪽 418번 밸브 아래에는 3"×2" 축소관이 붙어 있다. 2ce16b9에서는 밸브와 축소관이 한 기호라 위아래 배관이
        이어져 있었다. 두 기호로 읽은 뒤에도 위쪽 배관과 아래쪽 배관은 한 연결요소여야 한다."""
        ex, key = self.pages[12]
        item = next(i for i in key["closed_valves"] if i["number"] == "418")
        (valve,) = [n for n in self.closed_nodes(ex) if within(center(node_box(n)), item["bbox"], self.SLACK)]
        reducer = node_at(ex, [179.3, 275.0, 183.9, 279.6])
        group = {n["local_id"]: n["local_id"] for n in ex["nodes"]}

        def find(x):
            while group[x] != x:
                x = group[x]
            return x
        neighbours = {valve["local_id"]: set(), reducer["local_id"]: set()}
        for r in ex["relations"]:
            if r["kind"] != "physical_connection":
                continue
            a, b = (e["node_local_id"] for e in r["endpoints"])
            group[find(a)] = find(b)
            for x, y in ((a, b), (b, a)):
                if x in neighbours:
                    neighbours[x].add(y)
        above = neighbours[valve["local_id"]] - {reducer["local_id"]}
        below = neighbours[reducer["local_id"]] - {valve["local_id"]}
        self.assertTrue(above and below, (above, below))
        self.assertEqual({find(x) for x in above | below}, {find(valve["local_id"])})

    def test_pipe_network_is_not_cut_into_more_pieces_than_before_closed_valves_were_read(self):
        """닫힌 밸브를 따로 읽기 전(2ce16b9)에 물리 배관으로 이어진 노드 묶음(둘 이상)은 012쪽 2개(큰 것 51노드),
        062쪽 22개였다. 밸브를 맞닿은 기호와 떼어 놓고 잇지 않으면 012쪽이 5개로 갈라진다(F1-3 검토)."""
        before = {12: (2, 51), 62: (22, 12)}
        for seq, (ex, _) in self.pages.items():
            group = {n["local_id"]: n["local_id"] for n in ex["nodes"]}

            def find(x):
                while group[x] != x:
                    x = group[x]
                return x
            for r in ex["relations"]:
                a, b = (e["node_local_id"] for e in r["endpoints"])
                if r["kind"] == "physical_connection" and a != b:
                    group[find(a)] = find(b)
            sizes = {}
            for x in group:
                sizes[find(x)] = sizes.get(find(x), 0) + 1
            joined = [n for n in sizes.values() if n >= 2]
            self.assertLessEqual(len(joined), before[seq][0], seq)
            self.assertGreaterEqual(max(joined), before[seq][1], seq)

    def test_reducer_drawn_against_a_closed_valve_is_not_a_pipe_cap(self):
        ex, _ = self.pages[12]
        reducer = node_at(ex, [179.3, 275.0, 183.9, 279.6])  # 418번 밸브 아래에 붙여 그린 3"×2" 축소관
        self.assertIsNotNone(reducer)
        self.assertNotEqual(reducer["kind"], "pipe_cap")


PAGE_132 = paths.folder("APR1400", "by-drawing", "132_Ch10_Fig10.4.10-1_s2of3_Auxiliary_Steam_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_132), "pdfplumber 또는 APR1400 132쪽 PDF 없음(저장소 밖 자료)")
class LargeSymbolRegression(unittest.TestCase):
    """132쪽(10.4.10-1 S2)은 쪽 절반을 덮는 큰 묶음 기호가 있다. 검은 밸브를 따로 읽게 한 뒤 그 기호에 삼각형이 둘만 남아
    제어 밸브로 읽혔고, 안쪽 TI·PI 원 3개가 글자를 빼앗겨 종류를 잃었다(F1-3 검토). 2ce16b9의 판정을 고정한다."""

    INDICATORS = {"TI": [206, 418, 221, 433], "PI-1": [593, 470, 608, 485], "PI-2": [425, 474, 440, 489]}

    @classmethod
    def setUpClass(cls):
        cls.ex = pdf_vector.extract(PAGE_132, page=0)

    def test_indicators_inside_the_large_symbol_keep_their_kind(self):
        kinds = {name: node_at(self.ex, box)["kind"] for name, box in self.INDICATORS.items()}
        self.assertEqual(kinds, {name: "indicator" for name in self.INDICATORS})

    def test_large_symbol_is_not_read_as_a_valve(self):
        """미확인이던 묶음이 제어 밸브로 확정되면 종류 없음 미확인까지 사라진다. 종류 없음과 그 미확인이 함께 남아야 한다."""
        big = max(self.ex["nodes"], key=lambda n: (n.get("geometry") or {}).get("width", 0) *
                  (n.get("geometry") or {}).get("height", 0))
        self.assertEqual([round(v) for v in node_box(big)], [85, 184, 644, 528])
        self.assertEqual((big["kind"], big["category"]), (None, None))
        self.assertIn("missing_kind", [u["check"] for u in self.ex["validation"]["unknowns"]
                                       if u["target"] == big["local_id"]])


def ticks_near(ex, point, reach=5.0):
    """빗금(line_tick)으로 빼 버린 선 가운데 point 둘레 reach 안에 있는 것."""
    return [o["source_object_id"] for o in ex["drawing"]["ignored_objects"] if o.get("reason") == "line_tick"
            and abs(o["bbox"][0] + o["bbox"][2] / 2 - point[0]) <= reach
            and abs(o["bbox"][1] + o["bbox"][3] / 2 - point[1]) <= reach]


def pneumatic_through(ex, point, reach=1.0):
    """공압 신호선으로 읽은 선 가운데 point를 지나가는 것."""
    out = []
    for r in ex["relations"] + ex["unresolved_connectors"]:
        pts = r["evidence"].get("pdf_path") or []
        if r["line_type"] == "pdf_pneumatic" and any(
                min(a[0], b[0]) - reach <= point[0] <= max(a[0], b[0]) + reach
                and min(a[1], b[1]) - reach <= point[1] <= max(a[1], b[1]) + reach for a, b in zip(pts, pts[1:])):
            out.append(r["source_object_id"])
    return out


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(결정 D1)")
class ReliefValveSpring(unittest.TestCase):
    """5.4.12-1의 방출 밸브(번호 원 1421): 삼각형 몸통 위 짧은 줄기에 스프링선 셋이 걸려 있다. 선에 하나뿐인 빗금 묶음을
    신호 표시로 읽는 규칙(F1-4)이 이 선을 빗금으로 지우면 안 된다."""

    SPRING = (810.4, 373.0)
    BODY = [807.5, 372.1, 813.4, 378.0]

    @classmethod
    def setUpClass(cls):
        cls.ex, _ = load_page(12)

    def test_spring_strokes_are_not_removed_as_line_ticks(self):
        self.assertEqual(ticks_near(self.ex, self.SPRING), [])

    def test_spring_strokes_stay_in_the_valve_symbol(self):
        valve = node_at(self.ex, self.BODY)
        self.assertGreaterEqual(len(valve["evidence"]["pdf_objects"]), 5)  # 몸통, 줄기, 스프링선 셋


PAGE_104 = paths.folder("APR1400", "by-drawing", "104_Ch10_Fig10.1-2_Overall_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_104), "pdfplumber 또는 APR1400 104쪽 PDF 없음(저장소 밖 자료)")
class MainSteamSafetyValves(unittest.TestCase):
    """104쪽(그림 10.1-2)에서 줄기에 스프링선 셋을 그린 밸브 다섯: 'MSSV x 5' 표기 둘(주증기 안전밸브), 'MSADV x 1' 표기
    둘(주증기 대기방출밸브), 표기 없는 하나(601.4,140.5). 몸통을 지나 모관까지 내려가는 긴 줄기에 스프링선이 걸려 있다.
    3f에서 선에 하나뿐인 빗금 묶음을 모두 지웠을 때 이 스프링선이 지워졌다(81bc203에 같은 규칙을 주면 다섯 밸브 모두
    스프링선 둘이 지워지고 연결이 4개에서 1개로 줄며 줄기가 공압 신호선이 된다)."""

    SPRINGS = [(601.4, 140.5), (268.7, 168.1), (233.7, 215.9), (268.7, 219.2), (233.7, 164.3)]
    BODIES = [[599.8, 143.2, 604.7, 148.1], [267.1, 170.8, 272.0, 175.7], [232.0, 218.6, 236.9, 223.5],
              [267.0, 221.9, 271.9, 226.8], [232.0, 167.0, 236.9, 171.9]]

    @classmethod
    def setUpClass(cls):
        cls.ex = pdf_vector.extract(PAGE_104, page=0)

    def test_spring_strokes_are_not_removed_as_line_ticks(self):
        self.assertEqual({p: ticks_near(self.ex, p) for p in self.SPRINGS}, {p: [] for p in self.SPRINGS})

    def test_valve_stems_are_not_pneumatic_signal_lines(self):
        self.assertEqual({p: pneumatic_through(self.ex, p) for p in self.SPRINGS}, {p: [] for p in self.SPRINGS})

    def test_valves_keep_their_pipe_connections(self):
        """스프링선이 지워지면 줄기 토막이 합쳐져 밸브에 닿는 선이 4개에서 1개로 준다."""
        ends = {}
        for r in self.ex["relations"] + self.ex["unresolved_connectors"]:
            for e in r["endpoints"]:
                ends[e["node_local_id"]] = ends.get(e["node_local_id"], 0) + 1
        valves = [node_at(self.ex, box) for box in self.BODIES]
        self.assertNotIn("pipe_cap", [v["kind"] for v in valves])
        self.assertEqual([ends.get(v["local_id"], 0) for v in valves], [4] * 5)


PAGE_028 = paths.folder("APR1400", "by-drawing",
                        "028_Ch09_Fig9.2.2-1_s4of4_Component_Cooling_Water_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_028), "pdfplumber 또는 APR1400 028쪽 PDF 없음(저장소 밖 자료)")
class LonePneumaticMarks(unittest.TestCase):
    """028쪽(9.2.2-1 S4)의 I/P 변환기: 계기 공기 공급선과 구동부로 가는 짧은 공압선에 // 가 한 묶음씩 있다."""

    @classmethod
    def setUpClass(cls):
        cls.ex = pdf_vector.extract(PAGE_028, page=0)

    def test_pair_does_not_cut_its_line_into_loops(self):
        """TY 960에서 구동부로 가는 13.6pt 선: // 가 선을 잘라 한 분기점에 0 길이 고리 다섯 개가 걸리던 자리.
        이제 계기와 밸브를 잇는 신호 관계 하나다(구동부가 밸브에 합쳐져 선 종류는 pdf_solid로 남는다)."""
        loops = {u["target"] for u in self.ex["validation"]["unknowns"] if u["check"] == "self_loop"}
        here = [r["source_object_id"] for r in self.ex["unresolved_connectors"] if r["local_id"] in loops
                and all(abs(e["point"][0] - 537.6) <= 3 and abs(e["point"][1] - 272.6) <= 3 for e in r["endpoints"])]
        self.assertEqual(here, [])
        self.assertEqual(len(ticks_near(self.ex, (537.6, 272.6), reach=2.0)), 2)
        line = [r for r in self.ex["relations"] if [e["point"] for e in r["endpoints"]] ==
                [[544.372, 272.615], [530.813, 272.615]]]
        self.assertEqual([(r["kind"], [e["status"] for e in r["endpoints"]]) for r in line],
                         [("signal_connection", ["connected", "connected"])])

    def test_air_supply_stub_is_a_pneumatic_line(self):
        """TY 960 아래 계기 공기(IA) 공급선: 원에서 IA 물결 표시까지 7.5pt, // 한 묶음."""
        self.assertEqual(len(ticks_near(self.ex, (518.4, 272.6), reach=2.0)), 2)
        self.assertEqual(len(pneumatic_through(self.ex, (518.4, 272.6))), 1)


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


class SplitLetters(unittest.TestCase):
    """글자 크기가 조금씩 달라 pdfplumber가 한 자씩 끊은 연결 표시 글('SHEET 3"A"')을 한 줄로 다시 묶는다."""

    @staticmethod
    def word(text, x0, x1, top, size=3.159):
        return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 3.2, "size": size, "upright": True}

    def texts(self, words):
        return [b["text"] for b in pdf_vector._text_blocks(words, pdf_vector.PARAMS)]

    def test_letters_that_overlap_by_kerning_join_without_spaces(self):
        """9.5.1-1 시트 1: 'S' 끝(869.380)보다 'H' 시작(869.374)이 조금 앞선다. 예전에는 라벨이 'S'만 남았다."""
        words = [self.word("S", 867.266, 869.380, 243.089), self.word("H", 869.374, 871.662, 243.093),
                 self.word("EE", 871.656, 875.878, 243.097), self.word("T", 875.872, 877.809, 243.104),
                 self.word("3", 878.682, 880.445, 243.109), self.word('"', 881.318, 882.446, 243.114),
                 self.word("A", 882.440, 884.554, 243.116), self.word('"', 884.549, 885.676, 243.120)]
        self.assertEqual(self.texts(words), ['SHEET 3 "A"'])

    def test_a_piece_whose_top_is_a_hair_higher_still_joins_the_line_on_its_left(self):
        """10.4.9-1 시트 1: '"E"'의 윗변이 0.1pt 높아 먼저 줄을 열면 왼쪽 'SHEET 2'가 붙지 못했다."""
        words = [self.word("SHEET", 755.9, 765.9, 222.8), self.word("2", 766.6, 768.4, 222.8),
                 self.word('"E"', 769.2, 773.6, 222.7)]
        self.assertEqual(self.texts(words), ['SHEET 2 "E"'])

    def test_a_bracketed_number_beside_a_bubble_stays_its_own_line(self):
        """9.4.5-1 시트 2: 원 옆 '(3057)'이 'PDIS'에 붙으면 문단 가운데가 원 밖으로 밀려 'PDIS 3055' 태그를 잃는다."""
        words = [self.word("PDIS", 230.6, 239.3, 193.3, 3.7), self.word("(3057)", 241.6, 252.4, 193.2, 3.7)]
        self.assertEqual(sorted(self.texts(words)), ["(3057)", "PDIS"])

    def test_an_equipment_number_in_brackets_stays_with_its_name(self):
        """'LUBE OIL FILTER (FT32A)'의 설비 번호는 이름에서 떼지 않는다(검토 지적)."""
        words = [self.word("FILTER", 100.0, 111.0, 50.0, 3.7), self.word("(FT32A)", 112.0, 124.0, 50.0, 3.7)]
        self.assertEqual(self.texts(words), ["FILTER (FT32A)"])

    def test_narrowly_spaced_words_keep_their_space(self):
        """10.4.8-1 시트 2 'V1337 V1338'(간격 0.232pt), 9.4.3-1 'MOTOR DRIVEN'(0.254pt)이 붙지 않는다(검토 지적)."""
        words = [self.word("V1337", 100.0, 109.6, 50.0, 3.7), self.word("V1338", 109.832, 119.4, 50.0, 3.7)]
        self.assertEqual(self.texts(words), ["V1337 V1338"])

    def test_words_far_apart_on_one_row_stay_apart(self):
        words = [self.word("LEFT", 100.0, 108.0, 50.0), self.word("RIGHT", 120.0, 130.0, 50.0)]
        self.assertEqual(sorted(self.texts(words)), ["LEFT", "RIGHT"])


if __name__ == "__main__":
    unittest.main()
