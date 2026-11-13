"""그리는 기호 한 벌(resources/library/drawing-symbols/)과 웹이 읽는 도형 자료(symbols.json) 시험. 실행: python -m unittest tests.test_drawing_symbols

사전(resources/library/symbols)의 kind와 목록을 대조하고, SVG에 허용 요소만 있는지, 연결점이 그림 안에 있는지, symbols.json이 최신인지 본다.
"""

import glob
import json
import os
import re
import unittest

from scripts import build_drawing_symbols as bds

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICT = os.path.join(REPO, "resources", "library", "symbols")
# 가상 도면(SNP)에서 읽힌 기호 kind(2026-11-13, 6장). 모두 그림이 있거나 점(tee)이어야 한다
SNP_KINDS = {"tee", "continuation", "transmitter", "check_valve", "pump", "motor_operated_valve", "temperature_element", "tank", "manual_valve",
             "indicator", "control_valve", "controller", "psv", "heat_exchanger", "pipe_cap", "orifice", "reactor_vessel", "steam_generator",
             "pressurizer", "filter", "demineralizer", "vent", "isolation_valve", "turbine", "condenser"}


def dictionary_kinds():
    kinds = set()
    for p in glob.glob(os.path.join(DICT, "**", "*.json"), recursive=True):
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict) and isinstance(doc.get("kind"), str):
            kinds.add(doc["kind"])
    return kinds


class SymbolSetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = bds.build()
        cls.symbols = cls.data["symbols"]

    def test_every_dictionary_kind_has_a_drawing_or_is_reported(self):
        missing = sorted(dictionary_kinds() - set(self.symbols))
        # 그림 없는 kind는 generic 자리표로 그린다. 목록은 알리되 사전에 새 kind가 생기면 같은 날 그리도록 지금은 0이어야 한다
        print("\n[그림 없는 사전 kind %d개] %s" % (len(missing), ", ".join(missing) or "없음"))
        self.assertEqual(missing, [])

    def test_snp_kinds_are_all_drawn(self):
        self.assertEqual(sorted(SNP_KINDS - set(self.symbols)), [])
        self.assertTrue(self.symbols["tee"]["junction"])      # tee는 그림 없이 점
        for kind in SNP_KINDS - {"tee"}:
            self.assertTrue(self.symbols[kind]["shapes"], kind)

    def test_generic_exists_and_every_symbol_has_known_fit_and_label(self):
        self.assertIn("generic", self.symbols)
        for kind, s in self.symbols.items():
            self.assertIn(s["fit"], bds.FITS, kind)
            self.assertIn(s["label"], bds.LABELS, kind)

    def test_svg_files_use_only_allowed_elements_and_no_text_or_scripts(self):
        bad = re.compile(r"<(text|image|script|style|use|foreignObject|a)\b|href=|\bon\w+=|style=|https?:", re.I)
        for p in glob.glob(os.path.join(bds.SRC, "*.svg")):
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(bad.search(text.replace("http://www.w3.org/2000/svg", "")), os.path.basename(p))

    def test_ports_are_inside_the_drawing_and_files_match_manifest(self):
        for kind, s in self.symbols.items():
            w, h = s["vb"]
            for x, y, name in s["ports"]:
                self.assertTrue(0 <= x <= w and 0 <= y <= h, "%s %s" % (kind, name))
        with open(os.path.join(bds.SRC, "manifest.json"), encoding="utf-8") as fh:
            files = {r["file"] for r in json.load(fh)["symbols"] if r.get("file")}
        on_disk = {os.path.basename(p) for p in glob.glob(os.path.join(bds.SRC, "*.svg"))}
        self.assertEqual(files, on_disk)

    def test_symbols_json_in_the_repo_is_current(self):
        with open(bds.OUT, encoding="utf-8", newline="") as fh:
            self.assertEqual(fh.read().replace("\r\n", "\n"), bds.dump(self.data))

    def test_a_bad_svg_is_refused(self):
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x.svg")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text x="1" y="1">a</text></svg>')
        with self.assertRaises(bds.SymbolError):
            bds._shapes(p)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0,0 L1,1" fill="red" stroke="currentColor"/></svg>')
        with self.assertRaises(bds.SymbolError):
            bds._shapes(p)


if __name__ == "__main__":
    unittest.main()
