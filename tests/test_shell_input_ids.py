"""기준 추출을 지으면 local-node 번호가 밀린다: 화면이 보낸 판과 후보의 자리 번호가 그 뒤에도 맞는지(입력 연산 U2 셸 검토 차단 1).
실행: python -m unittest tests.test_shell_input_ids

합성 1쪽 PDF(tests.test_corrections_inputs의 page)에 나누기를 저장한 뒤 짓기 앞뒤로 (1) 판(ver)이 바뀌어 짓기 전에 본 화면의 고침이 낡은 판으로
거절되는지, (2) AI 후보·대기열이 보이는 자리 번호(local_id)가 저장된 값이 아니라 지금 고친 결과에서 그 기호(source_object_id)로 다시 찾은
값인지 본다. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다. AI 호출 없음.
"""

import unittest

from hazop.extract import ai_review as ar
from hazop.extract import corrections
from hazop.shell import api_aireview, api_corrections, sheet_refresh
from tests.test_corrections_inputs import GROUPS, HAS_PDFPLUMBER, NAME
from tests import test_corrections_inputs as _tci


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 필요")
class InputIdsTest(unittest.TestCase):
    # 합성 PDF 틀만 빌려 쓴다(엔진 시험은 물려받지 않음)
    setUp, tearDown, write_pdf, split_ops, save = (_tci.InputOpsTest.setUp, _tci.InputOpsTest.tearDown, _tci.InputOpsTest.write_pdf,
                                                    _tci.InputOpsTest.split_ops, _tci.InputOpsTest.save)

    def built(self, n=3):
        self.save(self.split_ops(GROUPS[:n]))
        before = api_corrections._sources(NAME)
        self.assertEqual(before["ver"], sheet_refresh.ver_of(NAME), "웹 고치기와 AI 검토가 같은 판을 쓴다")
        self.assertEqual(corrections.ensure_base(NAME), "ready")
        after = api_corrections._sources(NAME)
        self.assertEqual(after["ver"], sheet_refresh.ver_of(NAME))
        return before, after

    def test_building_the_base_changes_the_version(self):
        before, after = self.built(3)
        old = api_corrections._request("set_tag", "local-node-002", {"tag": "V1"}, before["corrected"], before["original"])[0]
        new = api_corrections._request("set_tag", "local-node-002", {"tag": "V1"}, after["corrected"], after["original"])[0]
        self.assertNotEqual(old, new, "시험 전제: 짓기 뒤 같은 자리 번호가 다른 기호를 가리킨다")
        self.assertNotEqual(before["ver"], after["ver"], "짓기 전에 본 화면의 판으로는 저장하지 않아야 한다")

    def test_one_split_also_moves_the_numbers_and_changes_the_version(self):
        before, after = self.built(1)
        self.assertNotEqual(before["ver"], after["ver"])

    def test_candidate_rows_find_the_place_by_symbol_not_the_stored_number(self):
        self.save(self.split_ops(GROUPS))
        doc = ar.new_doc(NAME, self.original)
        node = next(n for n in self.original["nodes"] if n["source_object_id"] == "pdf-p0-sym-0002")
        c = ar.make_candidate("t-1", "tag", node, "tag", ["V901"], 0.95, "주변 글자")
        self.assertEqual(c["local_id"], node["local_id"], "후보에는 그때의 자리 번호가 저장된다")
        doc["candidates"] = [c]
        corrections.ensure_base(NAME)
        shown = {n["source_object_id"]: n for n in corrections.resolve(NAME)["corrected"]["nodes"]}
        self.assertNotEqual(shown["pdf-p0-sym-0002"]["local_id"], c["local_id"], "시험 전제: 짓기 뒤 번호가 밀림")
        row = api_aireview._row(c, shown)
        self.assertEqual(row["local_id"], shown["pdf-p0-sym-0002"]["local_id"], "지금 고친 결과에서 그 기호로 다시 찾은 번호")
        gone = dict(c, target="pdf-p0-sym-9999")
        self.assertIsNone(api_aireview._row(gone, shown)["local_id"], "지금 없는 기호는 번호를 싣지 않는다(엉뚱한 기호에 붙지 않게)")


if __name__ == "__main__":
    unittest.main()
