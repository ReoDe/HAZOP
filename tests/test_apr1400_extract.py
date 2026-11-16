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
from hazop.extract import rules  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402

FIX = os.path.join(REPO_ROOT, "tests", "fixtures", "apr1400")
HAS_PDFPLUMBER = importlib.util.find_spec("pdfplumber") is not None


def check_apr1400():
    spec = importlib.util.spec_from_file_location("check_apr1400", os.path.join(REPO_ROOT, "scripts", "check_apr1400.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
        """PT는 전송기. TEW(보호관 온도 측정점, DCD 범례 1.7-1 TEW THERMOWELL)는 레지스트리에 보호관 종류가 없어
        온도 측정점인 temperature_element로 본다(R3 개선 4, 2026-11-13. 3e에서는 종류를 비웠다)."""
        kinds = {item["tag"]: node_at(self.ex, item["bbox"])["kind"] for item in self.key["instruments"]}
        self.assertEqual(kinds, {"TEW 106": "temperature_element", "PT 106": "transmitter",
                                 "TEW 107": "temperature_element", "TEW 108": "temperature_element"})

    def test_no_tag_outside_the_text_layer(self):
        """태그는 PDF 텍스트 층에 찍힌 글자다. 추출 결과의 label_text와 견주면 라벨에서 만든 태그는 늘 통과하므로,
        검사 도구(scripts/check_apr1400.py)가 PDF에서 따로 읽은 낱말·붙은 글자 묶음과 견준다."""
        ca = check_apr1400()
        tl = ca.text_layer(os.path.join(FIX, "pdf", self.key["source_file"]))
        bubbles = {it["tag"].replace(" ", "") for it in self.key["instruments"]}
        for n in self.ex["nodes"]:
            if n.get("tag"):
                tag = n["tag"].replace("-", "")
                self.assertTrue(tag in bubbles or ca.tag_in_text(n, tl), n["tag"])


def center(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def node_box(n):
    g = n["geometry"]
    return g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"]


def within(point, box, slack=0.0):
    return box[0] - slack <= point[0] <= box[2] + slack and box[1] - slack <= point[1] <= box[3] + slack


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(결정 D1)")
class ClosedValves(unittest.TestCase):
    """몸통을 검게 칠한 밸브는 정상 운전 중 닫힘이다(DCD 범례 1.7-1 1/4). 그 자리에는 normal_position이 닫힘(NC, 옆 글자가
    'LC'면 LC)인 밸브 노드가 있어야 하고, 몸통 모양으로 닫힘을 읽은 다른 노드는 없어야 한다. 정답은 answer_key의
    closed_valves(렌더한 그림을 눈으로 읽음)다. 옆 글자만으로 닫힘을 읽은 밸브(F1-5)는 ValveLabels가 본다."""

    PAGES = (12, 62)
    SLACK = 3.0  # 정답 상자는 검게 칠한 부분만이다. 노드 상자에는 가운데 점이나 맞닿은 판이 더해질 수 있다

    @classmethod
    def setUpClass(cls):
        cls.pages = {seq: load_page(seq) for seq in cls.PAGES}

    def closed_nodes(self, ex):
        """몸통 모양으로 닫힘을 읽은 노드: 옆 글자 없이 NC이거나, 옆 글자가 있을 때 몸통 값이 NC인 것."""
        return [n for n in ex["nodes"] if n["evidence"].get("position_from_body") == "NC" or
                ((n.get("attributes") or {}).get("normal_position") == "NC" and not n["evidence"].get("position_text"))]

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
        062쪽 22개였다. 밸브를 맞닿은 기호와 떼어 놓고 잇지 않으면 012쪽이 5개로 갈라진다(F1-3 검토).
        062쪽은 배관 끝 화살촉을 끝 기호로 읽은 뒤(9df3e7f) 26개다. 끊김 기호에서 집수정 안으로 들어가 화살촉으로 끝나는
        배수 유입관 4개가 전에는 노드 하나뿐이라 세지 않다가, 화살촉 끝 노드가 생겨 두 노드 묶음이 됐다. 그 전 22개
        묶음은 그대로다(어느 것도 갈라지지 않음).
        012쪽은 IRWST를 담는 외곽으로 읽은 뒤 3개다. 탱크 안 RCGVS 살포기가 탱크에 먹히지 않고 제 조각(분사구 두 개를 잇는
        머리관)으로 남아 두 노드 묶음 하나가 생겼다. 그 전 두 묶음(큰 것 52노드)은 그대로다."""
        before = {12: (3, 51), 62: (26, 12)}
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


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 없음(결정 D1)")
class ValveLabels(unittest.TestCase):
    """밸브 라벨 고르기(F1-5). 수동 밸브 번호('V2131')가 그 밸브의 태그이고, 위치 약어('LC,FC')는 속성이다.
    정답은 answer_key의 valve_numbers·valve_positions(렌더한 그림을 눈으로 읽음, 사람 확인 전)다."""

    PAGES = (12, 62)

    @classmethod
    def setUpClass(cls):
        cls.pages = {seq: load_page(seq) for seq in cls.PAGES}

    def test_valves_whose_bodies_are_read_carry_their_number(self):
        for seq, (ex, key) in self.pages.items():
            valves = {"nodes": [n for n in ex["nodes"] if n["category"] == "valve"]}  # 같은 자리 축소관 등은 정답이 아니다
            got = {item["tag"]: (node_at(valves, item["bbox"]) or {}).get("tag") for item in key["valve_numbers"]
                   if not item.get("extractor_misses")}
            self.assertEqual(got, {t: t for t in got}, "%03d쪽" % seq)

    def test_no_valve_carries_a_number_that_is_not_its_own(self):
        """밸브 번호 꼴 태그는 정답의 그 번호 자리에만 있어야 한다(옆 밸브의 번호를 가져가지 않는다)."""
        for seq, (ex, key) in self.pages.items():
            where = {item["tag"]: item["bbox"] for item in key["valve_numbers"]}
            wrong = [(n["tag"], [round(v, 1) for v in node_box(n)]) for n in ex["nodes"]
                     if n["tag"] and n["evidence"].get("tag_basis") == "valve_number"
                     and not (where.get(n["tag"]) and within(center(node_box(n)), where[n["tag"]], 1.0))]
            self.assertEqual(wrong, [], "%03d쪽" % seq)

    def test_position_words_become_valve_attributes(self):
        """속성은 그 종류가 가지는 것만 된다. 수동 밸브로 읽은 012쪽 'LC,FC' 밸브 11곳은 고장 위치를 두지 않고, 종류를
        확인하라는 미확인(position_kind_mismatch)을 남긴다(F1-5 검토)."""
        for seq, (ex, key) in self.pages.items():
            unknowns = {(u["target"], u["check"]) for u in ex["validation"]["unknowns"]}
            for item in key["valve_positions"]:
                node = node_at(ex, item["bbox"])
                allowed = rules.REGISTRY.class_properties(rules.REGISTRY.kind_class.get(node["kind"]) or node["category"])
                want = {f: item[f] for f in ("normal_position", "fail_position") if f in item and f in allowed}
                self.assertEqual({f: node["attributes"].get(f) for f in want}, want, "%03d쪽 %s" % (seq, item["label"]))
                if any(f in item and f not in allowed for f in ("normal_position", "fail_position")):
                    self.assertNotIn("fail_position", node["attributes"], "%03d쪽 %s" % (seq, item["label"]))
                    self.assertIn((node["local_id"], "position_kind_mismatch"), unknowns, "%03d쪽 %s" % (seq, item["label"]))

    def test_position_words_are_not_tags_or_labels(self):
        for seq, (ex, _) in self.pages.items():
            # 위치 약어가 태그가 되지 않는다. 번호 원으로 태그를 단 밸브(R3 개선 6)는 이름표 글자에 위치 약어가 남을 수 있어
            # 이름표가 아니라 태그를 본다
            self.assertEqual([n["tag"] for n in ex["nodes"]
                              if n["category"] == "valve" and (n["tag"] or "").strip() in ("LC", "LC,FC", "FC")],
                             [], seq)


PAGE_063 = paths.folder("APR1400", "by-drawing", "063_Ch09_Fig9.3.4-1_s1of7_Chemical_and_Volume_Control_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_063), "pdfplumber 또는 APR1400 063쪽 PDF 없음(저장소 밖 자료)")
class ValveNumbersNotTakenByNeighbours(unittest.TestCase):
    """063쪽(9.3.4-1 S1)에서 F1-5 중간 초안이 틀렸던 네 곳: V751·V713·V366은 품질 등급 마름모('BI|CI')가, V714는 옆의 구동
    밸브가 번호를 가져갔다. 이 번호가 태그로 붙으면 그 노드는 번호 글자 바로 옆(12pt 안)의 글자 없는 몸통이어야 한다."""

    NUMBERS = {"V751": (387.0, 209.8), "V713": (544.5, 625.4), "V714": (497.5, 626.3), "V366": (899.7, 538.7)}

    @classmethod
    def setUpClass(cls):
        cls.ex = pdf_vector.extract(PAGE_063, page=0)

    def test_numbers_stay_with_their_own_valves(self):
        wrong = []
        for n in self.ex["nodes"]:
            if n.get("tag") in self.NUMBERS:
                cx, cy = center(node_box(n))
                x, y = self.NUMBERS[n["tag"]]
                if n["evidence"].get("symbol_marks") or abs(cx - x) > 12 or abs(cy - y) > 12:
                    wrong.append((n["tag"], round(cx, 1), round(cy, 1), n["evidence"].get("symbol_marks")))
        self.assertEqual(wrong, [])


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_063), "pdfplumber 또는 APR1400 063쪽 PDF 없음(저장소 밖 자료)")
class DiaphragmUnderSolenoidPilot(unittest.TestCase):
    """063쪽 공기구동 밸브 515·516·240·522·523: 다이어프램 바로 위에 솔레노이드 파일럿 밸브를 얹어 그렸다. 둘을 한 기호로
    묶으면 사전 구동부에 맞지 않아 밸브가 구동부 없는 글로브로 남는다. 파일럿 몸통(꼬인 나비)은 S 상자 선 하나만 닿아도
    끝막음이 아니다."""

    BODIES = {"515": (282.8, 118.8), "516": (400.2, 118.8), "240": (735.8, 202.6), "522": (408.6, 470.8),
              "523": (500.9, 470.8)}

    @classmethod
    def setUpClass(cls):
        cls.ex = pdf_vector.extract(PAGE_063, page=0)

    def test_valve_under_a_piloted_diaphragm_is_air_operated(self):
        kinds = {num: (node_at(self.ex, (x, y, x, y)) or {}).get("kind") for num, (x, y) in self.BODIES.items()}
        self.assertEqual(kinds, {num: "air_operated_valve" for num in self.BODIES})

    def test_pilot_valve_is_not_a_pipe_cap(self):
        self.assertIsNone((node_at(self.ex, (735.7, 192.2, 735.7, 192.2)) or {}).get("kind"))


PAGE_111 = paths.folder("APR1400", "by-drawing", "111_Ch10_Fig10.4.5-1_s1of2_Circulating_Water_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_111), "pdfplumber 또는 APR1400 111쪽 PDF 없음(저장소 밖 자료)")
class ScallopedOutlineIsNotAVent(unittest.TestCase):
    """111쪽: 반원을 잇달아 그린 둥근 외곽의 끝 반원(371~375, 370~379)은 곧은 배관 다리 없이 곡선에 이어져 구스넥 벤트가 아니다."""

    def test_last_lobe_is_not_a_vent(self):
        ex = pdf_vector.extract(PAGE_111, page=0)
        self.assertIsNone((node_at(ex, (373.1, 374.8, 373.1, 374.8)) or {}).get("kind"))


PAGE_016 = paths.folder("APR1400", "by-drawing", "016_Ch06_Fig6.3.2-1_s2of4_Safety_Injection_Shutdown_Cooling_System_Flow_Diagram.pdf")
PAGE_025 = paths.folder("APR1400", "by-drawing", "025_Ch09_Fig9.2.2-1_s1of4_Component_Cooling_Water_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_016) and os.path.isfile(PAGE_025),
                     "pdfplumber 또는 APR1400 016·025쪽 PDF 없음(저장소 밖 자료)")
class CircledValvesKeepTheirCircleNumber(unittest.TestCase):
    """번호 원이 합쳐진 밸브는 그 원이 번호다. 옆 밸브의 번호 글자를 태그로 가져가면 안 된다(F1-6 뒤 F1-5 적용 때 찾음:
    016쪽 구동 밸브 348이 V158을, 025쪽 방출 밸브 1108이 V1110을 가져감). R3 개선 6부터 그 원의 번호가 태그다."""

    CASES = ((PAGE_016, "V158", "348"), (PAGE_025, "V1110", "1108"))

    def test_circled_valve_does_not_take_a_neighbours_number(self):
        for path, number, circle in self.CASES:
            ex = pdf_vector.extract(path, page=0)
            got = [(n["tag"], n["evidence"].get("ident_number")) for n in ex["nodes"]
                   if n["evidence"].get("ident_number") == circle]
            self.assertEqual(got, [(circle, circle)], number)


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_025), "pdfplumber 또는 APR1400 025쪽 PDF 없음(저장소 밖 자료)")
class NumbersWithACloserOtherNumberAreLeftEmpty(unittest.TestCase):
    """025쪽(9.2.2-1 S1): 옆 체크 밸브가 기호로 잡히지 않아, 자기 번호(V1007~V1010)보다 먼 옆 밸브 번호(V1001~V1004)를,
    1pt 옆 V1311·V1312 대신 8.7pt 떨어진 V1309·V1310을 받던 밸브 여섯(F1-5 검토, 그림으로 확인). 더 가까운 다른 번호
    글자가 있으면 번호를 주지 않는다(틀린 태그보다 빈 태그)."""

    WRONG = {(644.0, 177.8): "V1001", (636.7, 269.3): "V1003", (644.0, 471.0): "V1002", (636.6, 562.7): "V1004",
             (405.7, 197.9): "V1309", (405.6, 491.2): "V1310"}

    def test_neighbours_numbers_are_not_taken(self):
        ex = pdf_vector.extract(PAGE_025, page=0)
        got = {at: (node_at(ex, [at[0], at[1], at[0], at[1]]) or {}).get("tag") for at in self.WRONG}
        self.assertEqual([(at, tag) for at, tag in got.items() if tag == self.WRONG[at]], [])


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
        """큰 묶음이 제어 밸브로 읽히면 안 된다. 담는 외곽(faf498c) 뒤로는 탱크·응축기·배관이 한 덩어리(85,184,644,528)로
        묶이지 않고 가장 큰 노드가 이름을 받은 탱크 외곽이다(그림으로 확인: 그만한 기호는 쪽에 없다)."""
        big = max(self.ex["nodes"], key=lambda n: (n.get("geometry") or {}).get("width", 0) *
                  (n.get("geometry") or {}).get("height", 0))
        self.assertEqual((big["kind"], " ".join(big["label_text"].split())), ("tank", "CONDENSATE RECEIVER TANK"))
        wide_valves = [n for n in self.ex["nodes"] if (n["kind"] or "").endswith("valve") and
                       (n.get("geometry") or {}).get("width", 0) > 40]
        self.assertEqual(wide_valves, [])


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

    def test_extra_function_letters_between_letters_and_number_are_skipped(self):
        """9.2.4-1 시트 4(097쪽) 'LIS / AHL / 3025A'·'LTI / AHL / 001A': 가운데 줄은 덧붙인 경보 글자다."""
        got = self.tags([("switch", "instrument", "LIS\nAHL\n3025A"), ("indicator", "instrument", "LTI\nAHL\n001A")])
        self.assertEqual(got, ["LIS-3025A", "LTI-001A"])

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
        """10.4.8-1 시트 2 'V1337 V1338'(간격 0.232pt), 9.4.3-1 'MOTOR DRIVEN'(0.254pt)이 붙지 않는다(검토 지적).
        나란한 두 밸브 번호는 이웃한 두 밸브의 번호라 한 줄로도 잇지 않는다."""
        words = [self.word("V1337", 100.0, 109.6, 50.0, 3.7), self.word("V1338", 109.832, 119.4, 50.0, 3.7)]
        self.assertEqual(sorted(self.texts(words)), ["V1337", "V1338"])
        words = [self.word("MOTOR", 100.0, 109.6, 50.0, 3.7), self.word("DRIVEN", 109.854, 121.0, 50.0, 3.7)]
        self.assertEqual(self.texts(words), ["MOTOR DRIVEN"])

    def test_words_far_apart_on_one_row_stay_apart(self):
        words = [self.word("LEFT", 100.0, 108.0, 50.0), self.word("RIGHT", 120.0, 130.0, 50.0)]
        self.assertEqual(sorted(self.texts(words)), ["LEFT", "RIGHT"])


PAGE_002 = paths.folder("APR1400", "by-drawing", "002_Ch01_Fig1.7-1_s2of4_Flow_Diagram_Symbols_and_Legend.pdf")
PAGE_072 = paths.folder("APR1400", "by-drawing", "072_Ch09_Fig9.4.2-1_s1of2_Fuel_Handling_Area_HVAC_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_002) and os.path.isfile(PAGE_072),
                     "pdfplumber 또는 APR1400 002·072쪽 PDF 없음(저장소 밖 자료)")
class CentrifugalFans(unittest.TestCase):
    """범례 1.7-1 2/4 CENTRIFUGAL FAN OR BLOWER(달팽이 몸통 + 안쪽 짧은 호)는 사전 apr1400.centrifugal_fan으로 fan이 된다.
    범례 기호(002쪽)와 072쪽 공조기 칸 안 송풍기 넷."""

    def test_legend_and_hvac_fans(self):
        legend = pdf_vector.extract(PAGE_002, page=0)
        self.assertEqual(node_at(legend, [352, 128, 352, 128])["kind"], "fan")
        ex = pdf_vector.extract(PAGE_072, page=0)
        for at in ((540.5, 189.5), (515.0, 301.5), (603.5, 446.5), (603.5, 619.8)):
            self.assertEqual((node_at(ex, [at[0], at[1], at[0], at[1]]) or {}).get("kind"), "fan", at)



@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_025), "pdfplumber 또는 APR1400 025쪽 PDF 없음(저장소 밖 자료)")
class TombstonesSideBySide(unittest.TestCase):
    """025쪽 FT 073C·FT 071A·TEW 069: 계기 비석 셋을 1.5~2pt 사이로 나란히 그렸다. 비석 가운데 점선의 끝 토막이 옆 비석
    벽까지 닿음 거리 안이라, 그 토막을 구동부 축으로 읽어 셋을 한 노드로 묶고 첫 비석 글자만 태그로 남기던 자리다."""

    def test_each_tombstone_keeps_its_own_tag(self):
        ex = pdf_vector.extract(PAGE_025, page=0)
        tags = [(node_at(ex, (x, 152.0, x, 152.0)) or {}).get("tag") for x in (884.3, 901.2, 917.4)]
        self.assertEqual(tags, ["FT-073C", "FT-071A", "TEW-069"])



PAGE_046 = paths.folder("APR1400", "by-drawing", "046_Ch09_Fig9.3.1-1_Instrument_Air_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_046), "pdfplumber 또는 APR1400 046쪽 PDF 없음(저장소 밖 자료)")
class PiecesSetOnAnEquipmentOutline(unittest.TestCase):
    """046쪽 공기 압축기 01·02: 모서리를 따낸 L자 외곽 윗변 바깥에 필터 상자 F와 VET 계기 비석을 붙여 그렸다. 셋이 한 노드로
    묶이면 라벨이 VET가 되어 압축기 이름이 닿지 않는다. 외곽은 제 이름 'AIR COMPRESSOR 0n'을 갖고, F와 비석은 제 노드다."""

    @classmethod
    def setUpClass(cls):
        cls.ex = pdf_vector.extract(PAGE_046, page=0)

    def test_outline_box_and_tombstone_are_three_nodes(self):
        for dy, name in ((0.0, "AIR COMPRESSOR 01"), (195.4, "AIR COMPRESSOR 02")):
            comp = node_at(self.ex, (150.0, 395.0 + dy, 150.0, 395.0 + dy))
            box = node_at(self.ex, (143.5, 353.7 + dy, 143.5, 353.7 + dy))
            stone = node_at(self.ex, (174.5, 350.0 + dy, 174.5, 350.0 + dy))
            self.assertEqual(" ".join(comp["label_text"].split()), name)
            self.assertEqual(len({comp["local_id"], box["local_id"], stone["local_id"]}), 3, name)
            self.assertEqual((stone["category"], stone["label_text"]), ("instrument", "VET"), name)



PAGE_097 = paths.folder("APR1400", "by-drawing", "097_Ch09_Fig9.5.4-1_Diesel_Fuel_Oil_Transfer_System_Flow_Diagram.pdf")
PAGE_105 = paths.folder("APR1400", "by-drawing", "105_Ch10_Fig10.3.2-1_s1of2_Main_Steam_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_097) and os.path.isfile(PAGE_105),
                     "pdfplumber 또는 APR1400 097·105쪽 PDF 없음(저장소 밖 자료)")
class StackedInstrumentsAreTwoNodes(unittest.TestCase):
    """위아래로 변만 맞대 그린 계기 원·비석 둘(097쪽 TEW 003 위 TI 003, 105쪽 FT 1022Y 아래 PT 1023D)은 저마다 제 노드다.
    둥근 몸체가 맞닿았다고 한 기호로 묶으면 아래 계기가 위 계기의 글자를 태그로 가져가고 위 계기는 노드가 없다."""

    CASES = ((PAGE_097, (338.5, 595.0), (338.5, 608.4), ("TEW-003", "TI-003")),
             (PAGE_105, (291.6, 598.5), (291.9, 611.8), ("FT-1022Y", "PT-1023D")))

    def test_upper_and_lower_keep_their_tags(self):
        for path, top, bottom, want in self.CASES:
            ex = pdf_vector.extract(path, page=0)
            got = tuple((node_at(ex, (x, y, x, y)) or {}).get("tag") for x, y in (top, bottom))
            self.assertEqual(got, want, path)



@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_097), "pdfplumber 또는 APR1400 097쪽 PDF 없음(저장소 밖 자료)")
class GooseneckBesideASafetyClassMark(unittest.TestCase):
    """097쪽 위 구스넥 벤트: 끝 막대가 안전등급 경계 마름모 상자 귀퉁이(마름모 변에서 4.6pt)에 들어 마름모에 먹히던 자리.
    마름모는 변까지 잰다. 막대가 제 기호로 남아 구스넥 규칙이 벤트로 읽는다."""

    def test_upper_vent_is_read(self):
        ex = pdf_vector.extract(PAGE_097, page=0)
        self.assertEqual((node_at(ex, (656.3, 178.684, 656.3, 178.684)) or {}).get("kind"), "vent")



@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_025) and os.path.isfile(PAGE_097),
                     "pdfplumber 또는 APR1400 025·097쪽 PDF 없음(저장소 밖 자료)")
class FlowElementsUnderFEBubbles(unittest.TestCase):
    """배관 위 요소가 측정선으로 FE 계기 원에 이어지면 유량 요소다. 원은 계기로 둔다. 태그는 식별자라 요소에는 붙이지
    않고 원 번호는 근거(fe_bubble_tag)에만 남긴다(025쪽 차압 탭 상자 FE 003·047·049·071, 097쪽 FE 031 아래 오리피스 판)."""

    def test_pipe_elements_are_flow_elements_without_the_bubble_tag(self):
        ex = pdf_vector.extract(PAGE_025, page=0)
        nodes = [node_at(ex, (x, y, x, y)) or {} for x, y in ((420.0, 243.5), (655.0, 177.5), (650.5, 269.5), (901.0, 188.5))]
        self.assertEqual([(n.get("kind"), n.get("tag"), (n.get("evidence") or {}).get("fe_bubble_tag")) for n in nodes],
                         [("flow_element", None, t) for t in ("FE-003", "FE-047", "FE-049", "FE-071")])
        bubble = node_at(ex, (413.0, 261.7, 413.0, 261.7))
        self.assertNotEqual((bubble or {}).get("kind"), "flow_element")
        ex = pdf_vector.extract(PAGE_097, page=0)
        self.assertEqual((node_at(ex, (642.9, 562.0, 642.9, 562.0)) or {}).get("kind"), "flow_element")



PAGE_128 = paths.folder("APR1400", "by-drawing", "128_Ch10_Fig10.4.9-1_s1of3_Auxiliary_Feedwater_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_128), "pdfplumber 또는 APR1400 128쪽 PDF 없음(저장소 밖 자료)")
class BoundaryBoxWithWordsIsNotACheckValve(unittest.TestCase):
    """128쪽 건물 경계 표시 'AB ▶|◀ YARD' 상자는 화살촉 둘과 칸막이 선이라 '선과 표식' 체크밸브 구조로 읽혔다.
    상자 안에 낱말이 있으면 체크밸브가 아니다."""

    def test_ab_yard_boxes_have_no_kind(self):
        ex = pdf_vector.extract(PAGE_128, page=0)
        kinds = [(node_at(ex, (937.6, 249.7, 937.6, 249.7)) or {}).get("kind"),
                 (node_at(ex, (937.6, 569.5, 937.6, 569.5)) or {}).get("kind")]
        self.assertEqual(kinds, [None, None])


PAGE_134 = paths.folder("APR1400", "by-drawing", "134_Ch11_Fig11.2-1_s1of7_Liquid_Radwaste_System_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_134), "pdfplumber 또는 APR1400 134쪽 PDF 없음(저장소 밖 자료)")
class DoubleActingCylinderStack(unittest.TestCase):
    """134쪽(개발용) 펌프 출구 플러그 밸브 위에 반쪽 칠한 상자·X 상자·S 상자 둘·IA 글자로 그린 복동 실린더 구동부(범례 4/4
    VALVE OPERATOR CONTROLS)는 한 공기구동 밸브다. 옆 FL은 고장 위치 속성이고, 구동부 조각은 노드로 남지 않는다."""

    VALVE = (387.1, 146.0)
    PIECES = ((379.6, 128.3), (387.0, 135.6), (379.6, 142.8), (387.0, 139.1))

    @classmethod
    def setUpClass(cls):
        cls.ex = pdf_vector.extract(PAGE_134, page=0)

    def test_valve_is_air_operated_with_fail_position(self):
        n = node_at(self.ex, self.VALVE + self.VALVE) or {}
        self.assertEqual((n.get("kind"), (n.get("attributes") or {}).get("fail_position"),
                          (n.get("attributes") or {}).get("actuator_type")),
                         ("air_operated_valve", "FL", "pneumatic+solenoid_pilot"))

    def test_operator_pieces_are_merged(self):
        valve = node_at(self.ex, self.VALVE + self.VALVE)
        self.assertEqual([node_at(self.ex, p + p) is valve or node_at(self.ex, p + p) is None for p in self.PIECES],
                         [True] * len(self.PIECES))


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_134), "pdfplumber 또는 APR1400 134쪽 PDF 없음(저장소 밖 자료)")
class BlackPlugValves(unittest.TestCase):
    """134쪽(개발용) 검게 칠한 플러그 밸브(범례 1/4 PLUG (2-WAY) 닫힘 |◆|)는 분기점이 아니라 닫힌 밸브 노드다. 번호 글자가
    태그가 되고, 그 위 실린더 구동부 묶음은 공기구동 밸브로 합친다."""

    @classmethod
    def setUpClass(cls):
        cls.ex = pdf_vector.extract(PAGE_134, page=0)

    def test_closed_plug_valves_are_valve_nodes(self):
        got = [((node_at(self.ex, (x, y, x, y)) or {}).get("kind"), (node_at(self.ex, (x, y, x, y)) or {}).get("tag"),
                ((node_at(self.ex, (x, y, x, y)) or {}).get("attributes") or {}).get("normal_position"))
               for x, y in ((368.5, 153.3), (616.2, 221.9), (298.0, 341.5))]
        self.assertEqual(got, [("manual_valve", t, "NC") for t in ("V1015", "V2013", "V1007")])

    def test_cylinder_stack_on_a_black_plug_is_air_operated(self):
        n = node_at(self.ex, (409.3, 290.6, 409.3, 290.6)) or {}
        self.assertEqual((n.get("kind"), (n.get("attributes") or {}).get("normal_position")), ("air_operated_valve", "NC"))


PAGE_007 = paths.folder("APR1400", "by-drawing", "007_Ch05_Fig5.1.2-2_Reactor_Coolant_Pump_Flow_Diagram.pdf")


@unittest.skipUnless(HAS_PDFPLUMBER and os.path.isfile(PAGE_007) and os.path.isfile(PAGE_134),
                     "pdfplumber 또는 APR1400 007·134쪽 PDF 없음(저장소 밖 자료)")
class HatchedFramesAreNotSafetyValves(unittest.TestCase):
    """빗금을 친 큰 틀(134쪽 FLOOR DRAIN PUMP PP01 등 펌프 패키지 틀, 007쪽 UPPER OIL RESERVOIR·PUMP SEALS 상자)과
    공압선 빗금이 걸린 번호 원(134쪽 001)은 몸체+스프링 사선 규칙으로 안전밸브가 되지 않는다(개발용 쪽)."""

    def test_no_large_spring_bodies(self):
        found = []
        for path in (PAGE_007, PAGE_134):
            ex = pdf_vector.extract(path, page=0)
            found += [" ".join(n["label_text"].split()) for n in ex["nodes"] if n["kind"] == "psv"
                      and max(n["geometry"]["width"], n["geometry"]["height"]) > 10]
        self.assertEqual(found, [])


class OperatorStackKinds(unittest.TestCase):
    """밸브 축 위 구동부 묶음의 종류(합성 입력). S 상자 하나뿐이면 전자 밸브, 사전에 없는 조각이 섞이면 IA 글자가 있을 때만
    공기구동 밸브, 근거가 없으면 정하지 않는다."""

    class Piece:
        def __init__(self, x, y):
            self.bbox = (x, y, x + 3.7, y + 3.6)

    class Hit:
        def __init__(self, actuator_type):
            self.outcome = "matched"
            self.entry = type("E", (), {"attributes": {"actuator_type": actuator_type, "motive_power": "electric"}})()

    def test_single_solenoid_box_is_a_solenoid_valve(self):
        e = pdf_vector._stack_entry([self.Piece(0, 0)], [self.Hit("solenoid")], [], [])
        self.assertEqual((e.kind, e.attributes["actuator_type"]), ("solenoid_valve", "solenoid"))

    def test_unknown_pieces_need_instrument_air(self):
        pieces = [self.Piece(0, 0), self.Piece(0, 3.6), self.Piece(-6, -6)]
        hits = [None, None, self.Hit("solenoid")]
        self.assertIsNone(pdf_vector._stack_entry(pieces, hits, [], []))
        ia = [{"text": "IA", "bbox": (-4.0, 1.0, -1.0, 3.0)}]
        e = pdf_vector._stack_entry(pieces, hits, ia, [])
        self.assertEqual((e.kind, e.attributes), ("air_operated_valve", {"actuator_type": "pneumatic+solenoid_pilot",
                                                                         "motive_power": "air"}))


if __name__ == "__main__":
    unittest.main()
