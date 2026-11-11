"""문서 머리와 결정로그 고정 번호 넣기(scripts/migrate_doc_headers.py, HZ-GOV-02 §4.7·§4.8) 시험.

    python -m unittest tests.test_migrate_doc_headers
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import migrate_doc_headers as mh  # noqa: E402
from tests import test_naming_rules as rules  # noqa: E402

LOG = ("# 결정 로그\n\n[운영](README.md)\n\n| 날짜 | 결정 | 주체 | 근거 |\n| --- | --- | --- | --- |\n"
       "| 2026-11-02 | 첫 결정 | 사용자 | [원칙](../specs/overview.md) |\n"
       "| 2026-11-03 | `a | b`처럼 칸 안에 세로줄이 있는 결정 | 사용자 | — |\n"
       "\n"
       "| 2026-11-08 | 빈 줄 다음에 이어진 결정 | 권고 승인 | — |\n")


class Header(unittest.TestCase):
    def test_header_passes_n6_and_keeps_body(self):
        new = mh.add_header("# 전체 기획\n\n본문\n", "HZ-PLN-01")
        self.assertEqual([], rules.n6_doc_headers({"specs/overview.md": new}))
        self.assertEqual({"doc_id": "HZ-PLN-01", "rev": "0", "status": "draft", "author": "unknown", "reviewed": "—",
                          "approved": "—"}, rules.front_matter(new))
        self.assertTrue(new.endswith("---\n\n# 전체 기획\n\n본문\n"))

    def test_second_run_changes_nothing(self):
        once = mh.add_header("# 제목\n", "HZ-PLN-02")
        self.assertEqual(once, mh.add_header(once, "HZ-PLN-02"))

    def test_line_endings_and_bom_are_kept(self):
        new = mh.add_header("﻿# 제목\r\n본문\r\n", "HZ-DSN-01")
        self.assertTrue(new.startswith("﻿---\r\ndoc_id: HZ-DSN-01\r\n"))
        self.assertNotIn("\n", new.replace("\r\n", ""))
        self.assertTrue(new.endswith("# 제목\r\n본문\r\n"))


class DecisionIds(unittest.TestCase):
    def test_number_is_the_line_number_of_the_row(self):
        new = mh.add_decision_ids(LOG).splitlines()
        self.assertEqual("| 번호 | 날짜 | 결정 | 주체 | 근거 |", new[4])
        self.assertEqual("| --- | --- | --- | --- | --- |", new[5])
        self.assertTrue(new[6].startswith("| DEC-0007 | 2026-11-02 | 첫 결정 "))
        self.assertTrue(new[7].startswith("| DEC-0008 | 2026-11-03 | `a | b`처럼"))
        self.assertEqual("", new[8])
        self.assertTrue(new[9].startswith("| DEC-0010 | 2026-11-08 "))

    def test_rows_and_sentences_are_unchanged_apart_from_the_new_column(self):
        new = mh.add_decision_ids(LOG)
        self.assertEqual(LOG, mh.strip_decision_ids(new))
        self.assertEqual(len(LOG.splitlines()), len(new.splitlines()))

    def test_second_run_changes_nothing_even_after_the_header(self):
        once = mh.add_header(mh.add_decision_ids(LOG), "HZ-REC-02")
        self.assertEqual(once, mh.add_decision_ids(once))

    def test_refuses_to_number_after_the_header_shifted_the_lines(self):
        with self.assertRaises(mh.HeaderError):
            mh.add_decision_ids(mh.add_header(LOG, "HZ-REC-02"))

    def test_refuses_a_file_without_a_table(self):
        with self.assertRaises(mh.HeaderError):
            mh.add_decision_ids("# 결정 로그\n\n표가 없다\n")


class DocIds(unittest.TestCase):
    def test_ids_are_unique_and_well_formed(self):
        ids = list(mh.DOC_IDS.values())
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([], [i for i in ids if not rules.DOC_ID.match(i)])

    def test_every_header_target_has_an_id(self):
        """INTENT.md(HZ-GOV-01)와 HZ-GOV-02는 이 도구가 다루지 않는다. 앞은 총괄이 달고 뒤는 이미 머리가 있다."""
        targets = {p for p in rules.tracked_files() if rules.is_header_target(p)} - {"INTENT.md", rules.NAMING_DOC}
        self.assertEqual(set(), targets - set(mh.DOC_IDS))


if __name__ == "__main__":
    unittest.main()
