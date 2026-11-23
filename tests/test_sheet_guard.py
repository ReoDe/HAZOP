"""시트 정체 U2 재현 시험: 도면 번호를 바꾸는 길(표제란 확정·확정 취소, 옛 등록 화면·명령줄의 등록)이 사람 기록을 끊거나 사용자를 가두는 길.
근거: docs/units/2026-11-13-drawing-knowledge/evidence/sheet-identity-design.md §8·§11.

가드 건전(불변식 6): 번호 바꾸기를 허락하면 그 도면을 가리키던 사람 기록(구간·분석 결과·초기사건·FMEA·잠재 후보 판단·도면 연결 지정·
구간 제외 표시·지식그래프 판단)이 하나도 끊기지 않는다. 막을 때는 사유 코드와 사람용 글을 돌려주고, 그 이름의 지금 주인이 아닌 자료는
남의 기록 때문에 막지 않는다(갇히지 않음).
실행: python -m unittest tests.test_sheet_guard
"""

import json
import os
import unittest
from unittest import mock

import pypdfium2 as pdfium

from tests.test_sheet_gid_paths import NUMBER, SheetCase, legacy_name
from tests.test_titleblock import BY, P, sample

from hazop import paths
from hazop.app import project_ctx
from hazop.graph import sheets, sources
from hazop.register import registry, titleblock as tb
from hazop.study import nodes

RESERVED = "material-0123456789ab-p0"


class GuardCase(SheetCase):
    def numbered(self, drawing="SNP-M-101", ext="drawio"):
        mid = self.add(drawing, ext)
        self.assertTrue(self.confirm(mid, {"drawing_number": drawing})["ok"])
        self.assertEqual(self.sheet(mid)["graph_id"], "graph-" + drawing)
        return mid

    def refused(self, out):
        self.assertFalse(out["ok"], out)
        return out["refused"][0]

    def multi_page_pdf(self):
        doc = pdfium.PdfDocument.new()
        for d in ("SNP-M-101", "SNP-M-102"):
            doc.import_pages(pdfium.PdfDocument(sample(d, "pdf")))
        dst = os.path.join(self.tmp, "in2", "two.pdf")
        os.makedirs(os.path.dirname(dst))
        doc.save(dst)
        return dst


class GuardCountsTest(GuardCase):
    """가드가 세지 못하던 기록(P4·P5·구간 제외 표시·지식그래프 판단 CSV)."""

    def test_guard_counts_fmea_rows(self):
        """P4. FMEA(초기사건 옆 파일)의 행 참조 '<graph_id>#…'도 번호를 바꾸면 끊긴다."""
        from hazop.ie import store as ie_store
        mid = self.numbered()
        path = ie_store.fmea_path(P)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"rows": {"r1": {"ref": "graph-SNP-M-101#n1", "entity_id": "entity-node-001"}}}, fh)
        row = self.refused(self.confirm(mid, {"drawing_number": "SNP-M-555"}, dry=True))
        self.assertIn("FMEA", row["reason"])
        self.assertEqual(row["reason_code"], tb.HAS_RECORDS)

    def test_guard_counts_sheet_links_in_their_stored_form(self):
        """P5. 도면 연결 지정의 끝은 graph_id가 아니라 도면 번호로 적힌다({"drawing_number", "source_object_id", "fp"})."""
        from hazop.graph import project
        mid = self.numbered()
        ends = [{"drawing_number": "SNP-M-101", "source_object_id": "n1"}, {"drawing_number": "SNP-M-102", "source_object_id": "n2"}]
        project.save_manual(P, [{"op_id": "op-1", "op": "link", "ends": ends, "by": BY, "at": "2026-11-23T00:00:00Z",
                                 "reason": "시험"}], BY, "2026-11-23T00:00:00Z")
        row = self.refused(self.confirm(mid, {"drawing_number": "SNP-M-555"}, dry=True))
        self.assertIn("도면 연결 지정 1곳", row["reason"])

    def test_guard_counts_the_excluded_drawing_mark(self):
        """구간 제외 표시(구간제외도면.json)는 맨 도면 번호로 적힌다. 번호를 바꾸면 그 도면이 말없이 구간 분석에 다시 들어간다."""
        mid = self.numbered()
        nodes.set_excluded(P, "SNP-M-101", True, BY, "범례 도면")
        row = self.refused(self.confirm(mid, {"drawing_number": "SNP-M-555"}, dry=True))
        self.assertIn("구간 제외 표시 1곳", row["reason"])
        nodes.set_excluded(P, "SNP-M-101", False, BY)
        self.assertTrue(self.confirm(mid, {"drawing_number": "SNP-M-555"}, dry=True)["ok"])

    def test_guard_counts_knowledge_graph_judgements_in_csv(self):
        """지식그래프 판단(link_candidates.csv)의 target_ref는 따옴표 없는 'graph-<번호>:<태그>'다. 사람이 판단한 행만 센다
        (판단 전 후보 행은 다시 만들면 새 이름으로 다시 셈되므로 번호 바꾸기를 막지 않는다)."""
        from hazop.kg import link
        mid = self.numbered()
        folder = paths.folder("knowledge-graph", paths.safe_name(P, "project"))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, link.CANDIDATES_CSV)

        def write(status):
            row = {c: "" for c in link.CANDIDATE_COLUMNS}
            row.update(candidate_key="k1", target_graph_id="graph-SNP-M-101", target_tag="RC-V101",
                       target_ref="graph-SNP-M-101:RC-V101", link_status=status, reviewed_by=BY if status != "candidate" else "")
            link.write_candidates(path, [row])
            with open(path, encoding="utf-8-sig") as fh:
                text = fh.read()
            self.assertIn(",graph-SNP-M-101:RC-V101,", text, "시험 전제: 따옴표 없이 적힘")
        write("candidate")
        self.assertTrue(self.confirm(mid, {"drawing_number": "SNP-M-555"}, dry=True)["ok"], "판단 전 후보는 막지 않음")
        write("confirmed")
        row = self.refused(self.confirm(mid, {"drawing_number": "SNP-M-555"}, dry=True))
        self.assertIn("지식그래프 판단", row["reason"])


class GuardOwnerTest(GuardCase):
    """그 이름의 지금 주인일 때만 참조를 센다. 주인이 아닌 자료는 남의 기록 때문에 갇히지 않고, 주인은 지금처럼 막힌다."""

    def test_guard_blocks_title_block_number_change_and_unconfirm_with_a_node(self):
        """P0 가드 고정: 구간이 있는 도면은 표제란 확정(번호 바꾸기)과 확정 취소 모두 막히고 구간은 그대로다."""
        mid = self.numbered("SNP-M-101", "pdf")
        _pg, ns = self.make_nodes(mid)
        members = ns["nodes"][0]["members"]
        row = self.refused(self.confirm(mid, {"drawing_number": "SNP-M-555"}))
        self.assertEqual((row["code"], row["reason_code"]), ("rule", tb.HAS_RECORDS))
        self.assertIn("구간", row["reason"])
        undo = tb.unconfirm(P, mid, ["drawing_number"], BY, ver=self.row(mid)["ver"])
        self.assertFalse(undo["ok"], "확정 취소로 이름이 바뀌는 것도 막음")
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []))

    def test_other_file_with_the_same_number_can_change_its_number(self):
        """같은 번호의 다른 형식 파일(고르기 전에는 쓰이지 않음)은 주인 도면의 구간 때문에 번호를 고치거나 취소하지 못하던 길."""
        a = self.numbered("SNP-M-101", "drawio")
        b = self.numbered("SNP-M-101", "pdf")
        _pg, before = self.make_nodes(a)
        members = before["nodes"][0]["members"]
        self.assertEqual(project_ctx.graph_names(P)["graph-SNP-M-101"], self.sheet(a)["name"], "시험 전제: drawio가 주인")
        self.assertTrue(tb.unconfirm(P, b, ["drawing_number"], BY, ver=self.row(b)["ver"], dry=True)["ok"])
        out = self.confirm(b, {"drawing_number": "SNP-M-102"})
        self.assertTrue(out["ok"], out)
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []), "주인 도면 구간은 그대로")
        self.assertEqual(self.gids(), ["graph-SNP-M-101", "graph-SNP-M-102"])
        self.assertEqual(self.refused(self.confirm(a, {"drawing_number": "SNP-M-555"}))["reason_code"], tb.HAS_RECORDS,
                         "주인은 지금처럼 막힘")

    def test_taking_a_number_whose_drawing_has_records_is_refused(self):
        """새 이름의 참조는 늘 센다. 그 번호의 도면에 구간이 있으면 다른 파일이 그 번호를 받지 못한다(받으면 고르기 차례에 따라 주인이
        바뀔 수 있는데, 가드는 그것을 미리 알지 못한다)."""
        a = self.numbered("SNP-M-101", "drawio")
        self.make_nodes(a)
        b = self.add("SNP-M-101", "pdf")
        row = self.refused(self.confirm(b, {"drawing_number": "SNP-M-101"}))
        self.assertEqual(row["reason_code"], tb.HAS_RECORDS)
        self.assertIn("새 번호의 도면(SNP-M-101)", row["reason"])

    def test_left_out_second_drawing_can_be_numbered(self):
        """이 단위 전에 두 PDF가 한 이름(graph-drawing)을 나눠 쓴 저장본에서(옛 규칙은 가장 새 것을 써서 둘째 B가 주인, 첫 도면 A가 가려짐),
        가려진 도면은 번호를 확정해 따로 들어온다. 주인 B는 그 이름에 구간 기록이 있어 지금처럼 막힌다."""
        a, b, seen = self.collided("pdf")
        self.assertEqual(project_ctx.graph_names(P)["graph-drawing"], self.sheet(b)["name"], "시험 전제: 둘째가 주인")
        out = self.confirm(a, {"drawing_number": "SNP-M-101"})
        self.assertTrue(out["ok"], out)
        self.assertIn("graph-SNP-M-101", self.gids())
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (seen["members"], seen.get("lost") or []))
        row = self.refused(self.confirm(b, {"drawing_number": "SNP-M-102"}))
        self.assertEqual(row["reason_code"], tb.HAS_RECORDS, row)

    def test_unconfirm_before_settle_uses_the_settled_name(self):
        """정착 전 프로젝트에서 확정 취소의 새 이름을 옛 규칙(graph-drawing)으로 예측하면, 그 이름을 쓰는 다른 도면의 구간 때문에
        막힌다. 실제로는 추출 맨 앞에서 정착해 graph-<자료>-p0이 되므로 막을 까닭이 없다(표제란 확정 맨 앞에서 정착)."""
        with mock.patch("hazop.graph.sources.sheet_name", legacy_name, create=True), \
                mock.patch("hazop.app.data.settle_sheets", lambda *a, **k: None, create=True):
            x = self.add("SNP-M-101", "pdf")
            _pg, before = self.make_nodes(x)
            y = self.register(self.copy_in("SNP-M-102", "pdf", "in-y"), dict(NUMBER, drawing_number="SNP-M-102"))
        self.assertFalse(sources.load_seats(P)[1], "시험 전제: 정착 전")
        self.assertEqual(self.sheet(x)["graph_id"], "graph-drawing")
        self.assertTrue(tb.unconfirm(P, y, ["drawing_number"], BY, ver=self.row(y)["ver"], dry=True)["ok"])
        out = tb.unconfirm(P, y, ["drawing_number"], BY, ver=self.row(y)["ver"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.sheet(y)["graph_id"], "graph-%s-p0" % y)
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (before["nodes"][0]["members"], []))


class NumberRuleTest(GuardCase):
    """번호 꼴 규칙(여러 쪽·예약 꼴)과 옛 등록 화면·명령줄의 등록(registry._register_one 재사용 가지)."""

    def test_reserved_number_is_refused_by_the_title_block_and_held_by_registration(self):
        mid = self.add("SNP-M-101", "pdf")
        row = self.refused(self.confirm(mid, {"drawing_number": RESERVED}))
        self.assertEqual(row["reason_code"], sheets.NUMBER_RESERVED)
        self.assertNotIn("graph-", row["reason"])
        res = registry.register(self.copy_in("SNP-M-102", "pdf", "in-r"), P, "P&ID", paths.store_root(),
                                dict(NUMBER, drawing_number=RESERVED), BY)
        self.assertEqual(res["outcome"], "on_hold")
        self.assertEqual([b["check"] for b in res["record"]["validation"]["blockers"]], [sheets.NUMBER_RESERVED])

    def test_multi_page_pdf_with_a_number_is_held_at_registration(self):
        res = registry.register(self.multi_page_pdf(), P, "P&ID", paths.store_root(), dict(NUMBER), BY)
        self.assertEqual(res["outcome"], "on_hold", res["notes"])
        self.assertEqual([(b["check"], b["field"]) for b in res["record"]["validation"]["blockers"]],
                         [(sheets.NUMBER_HELD, "drawing_number")])
        self.assertIn("2쪽", res["record"]["validation"]["blockers"][0]["reason"])

    def test_multi_page_number_is_refused_but_a_held_number_can_be_cleared(self):
        """여러 쪽 자료에 번호를 확정하지 않는다(사유 multi_page_number). 이 단위 전에 받아 둔 자료 번호는 이름에 쓰이지 않으니 취소는 막지 않는다."""
        src = self.multi_page_pdf()
        mid = self.register(src)
        row = self.refused(self.confirm(mid, {"drawing_number": "SNP-M-101"}))
        self.assertEqual(row["reason_code"], sheets.NUMBER_HELD)
        with mock.patch("hazop.register.registry._number_hold", lambda *a: []):   # 이 단위 전 앱의 등록
            old = registry.register(src, P, "P&ID", paths.store_root(), dict(NUMBER), BY)
        self.assertEqual(old["outcome"], "new_version")
        rec, _p = registry.latest(P, mid)
        self.assertEqual(rec["drawing_number"], "SNP-M-101")
        out = tb.unconfirm(P, mid, ["drawing_number"], BY, ver=self.row(mid)["ver"], extract=lambda _p: None)
        self.assertTrue(out["ok"], out)

    def test_registering_the_same_file_again_with_another_number_is_held(self):
        """P3 등록 쪽. 옛 등록 화면·명령줄이 같은 원본을 번호와 함께 다시 등록하면 가드 없이 시트 이름이 바뀌었다. 보류하고 표제란 확정으로 안내한다."""
        a = self.add("SNP-M-101", "pdf")
        _pg, before = self.make_nodes(a)
        rec, _p = registry.latest(P, a)
        src = registry.Store(paths.store_root(), P).abs_ref(rec["storage_ref"])
        res = registry.register(src, P, "P&ID", paths.store_root(), dict(NUMBER), BY)
        self.assertEqual(res["outcome"], "on_hold", res["notes"])
        self.assertEqual(res["record"]["material_id"], a)
        blockers = res["record"]["validation"]["blockers"]
        self.assertEqual([(b["check"], b["field"]) for b in blockers], [(sheets.CONFIRM_FIRST, "drawing_number")])
        self.assertIn("표제란", blockers[0]["reason"])
        self.assertEqual(registry.latest(P, a)[0]["registration_version"], rec["registration_version"], "새 등록 판을 만들지 않음")
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (before["nodes"][0]["members"], []))
        same = registry.register(src, P, "P&ID", paths.store_root(), {"title": "제목만", "by": BY}, BY)
        self.assertEqual(same["outcome"], "new_version", "번호를 안 바꾸는 다시 등록은 그대로 됨")


class RefusalWordsTest(GuardCase):
    def test_refusals_carry_a_code_and_plain_words(self):
        """거절 글에 내부 말(graph-, material-, 판 사진 등)이 없고 모든 가드 거절에 사유 코드가 있다."""
        a = self.add("SNP-M-101", "pdf")
        self.make_nodes(a)
        rows = [self.refused(self.confirm(a, {"drawing_number": "SNP-M-101"})),
                self.refused(self.confirm(a, {"drawing_number": RESERVED}))]
        for row, words in zip(rows, (("graph-", "material-", "그래프 ID", "묘비", "판 사진"), ("graph-", "그래프 ID"))):
            self.assertIn(row["reason_code"], tb.REASON_CODES)
            for word in words:
                self.assertNotIn(word, row["reason"])
        self.assertEqual(rows[0]["reason_code"], sheets.CONFIRM_FIRST, "번호 미확정 도면에 구간이 먼저 생긴 경우")




if __name__ == "__main__":
    unittest.main()
