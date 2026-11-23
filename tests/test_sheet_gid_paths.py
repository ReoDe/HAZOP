"""시트 정체 U1 재현 시험: 번호를 확정하기 전의 시트가 자료·쪽을 가르지 못해(확정 전 PDF는 모두 graph-drawing, drawio는 graph-<쪽 이름>,
DEXPI는 graph-<도면 이름>) 다른 도면이 한 시트 이름을 나눠 쓰던 길. 근거: docs/units/2026-11-13-drawing-knowledge/evidence/sheet-identity-design.md.

가상 도면 SNP의 원본을 임시 작업 루트·저장 루트에 등록하고 실제로 추출한다. 기대는 '넣은 시트가 모두 프로젝트 그래프에 들어오고,
사람이 만든 구간이 다른 도면 때문에 묘비가 되거나 다른 기호를 가리키지 않는다'이다.
표제란 가드 쪽 길(P4·P5, 빠졌던 둘째 도면의 번호 확정, 구간 제외 표시)은 U2가 tests/test_sheet_guard.py로 옮겼다.
실행: python -m unittest tests.test_sheet_gid_paths
"""

import json
import os
import shutil
import unittest
from unittest import mock

import pypdfium2 as pdfium

from tests.test_titleblock import BY, P, Base, sample

from hazop import paths
from hazop.app import data, project_ctx
from hazop.extract import confirmation
from hazop.graph import sources
from hazop.register import registry
from hazop.study import nodes

NUMBER = {"drawing_number": "SNP-M-101", "by": BY, "reason": "명령줄 등록"}


def legacy_name(_project_id, extraction, **_kw):
    """이 단위 전의 이름 규칙(정착 전 앱이 쓰던 것)."""
    return "graph-%s" % ((extraction.get("drawing") or {}).get("drawing_number")
                         or (extraction.get("source_context") or {}).get("page_name") or "drawing")


class SheetCase(Base):
    """시트 시험의 도움 함수(시험 없음)."""

    def register(self, src, meta=None):
        res = registry.register(src, P, "P&ID", paths.store_root(), meta, BY)
        self.assertIn(res["outcome"], ("registered", "new_version"), res.get("notes"))
        data.extract_and_graph(res["registration_file"])
        return res["record"]["material_id"]

    def reextract(self, mid):
        rec, _p = registry.latest(P, mid)
        data.extract_and_graph(registry.Store(paths.store_root(), P).snapshot_path(mid, rec["registration_version"]))

    def node(self):
        pg = project_ctx.project_graph(P)
        return pg, nodes.load(pg)["nodes"][0]

    def gids(self):
        return sorted(s["graph_id"] for s in project_ctx.project_graph(P)["sheets"])

    def copy_in(self, drawing, ext, folder, edit=None):
        src = sample(drawing, ext)
        dst = os.path.join(self.tmp, folder, os.path.basename(src))
        if ext == "drawio":
            shutil.copytree(os.path.dirname(src), os.path.dirname(dst))
        else:
            os.makedirs(os.path.dirname(dst))
            shutil.copy(src, dst)
        if edit:
            with open(dst, encoding="utf-8") as fh:
                text = fh.read()
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(edit(text))
        return dst

    def same_page_name_drawio(self):
        """SNP-M-102 도면인데 쪽 이름을 SNP-M-101로 바꾼 drawio(기본 쪽 이름 'Page-1'이 겹치는 것과 같은 꼴)."""
        return self.copy_in("SNP-M-102", "drawio", "in-same-page", lambda t: t.replace('name="SNP-M-102"', 'name="SNP-M-101"', 1))

    def judge_in_kg(self, graph_id):
        """그 도면을 가리키는 사람이 판단한 지식그래프 연결 후보 한 줄(번호를 바꿀 때 옮기지 못하는 기록)."""
        from hazop.kg import link
        folder = paths.folder("knowledge-graph", paths.safe_name(P, "project"))
        os.makedirs(folder, exist_ok=True)
        r = {c: "" for c in link.CANDIDATE_COLUMNS}
        r.update(candidate_key="k1", target_graph_id=graph_id, target_tag="T", target_ref=graph_id + ":T", link_status="confirmed", reviewed_by=BY)
        link.write_candidates(os.path.join(folder, link.CANDIDATES_CSV), [r])

    def collided(self, kind):
        """이 단위 전 앱으로 두 도면이 한 시트 이름을 나눠 쓴 채 저장된 프로젝트를 만든다. 첫 도면 구간은 둘째 도면 때문에 이미 잃었다."""
        with mock.patch("hazop.graph.sources.sheet_name", legacy_name, create=True),                 mock.patch("hazop.app.data.settle_sheets", lambda *a, **k: None, create=True):
            a = self.add("SNP-M-101", kind)
            self.make_nodes(a)
            b = self.add("SNP-M-102", "pdf") if kind == "pdf" else self.register(self.same_page_name_drawio())
            pg, n = self.node()
        self.assertEqual(len(pg["sheets"]), 1, "시험 전제: 옛 규칙에서는 한 시트")
        return a, b, n


class SheetGidPathTest(SheetCase):

    # ------------------------------------------------------------ 번호 없는 시트끼리
    def test_two_unconfirmed_pdfs_are_two_sheets_and_the_first_keeps_its_node(self):
        """P1. 번호를 확정하지 않은 PDF 둘은 시트 둘이다. 둘째를 넣어도, 첫째를 다시 추출해도 첫 PDF 구간은 그대로다."""
        a = self.add("SNP-M-101", "pdf")
        _pg, before = self.make_nodes(a)
        members = before["nodes"][0]["members"]
        b = self.add("SNP-M-102", "pdf")
        self.assertEqual(len(self.gids()), 2, "둘째 PDF가 첫 PDF와 한 시트 이름을 나눠 써서 하나만 들어옴")
        self.assertNotEqual(self.sheet(a)["graph_id"], self.sheet(b)["graph_id"])
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []), "다른 도면을 넣었을 뿐인데 구간 구성요소를 잃음")
        self.reextract(a)
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []), "첫 PDF를 다시 추출해도 그대로")
        self.assertEqual(len(self.gids()), 2)

    def test_three_unconfirmed_pdfs_are_three_sheets(self):
        """번호 없는 PDF 세 장은 시트 셋이고 고를 것이 없다(충돌 줄 없음)."""
        mids = [self.add(d, "pdf") for d in ("SNP-M-101", "SNP-M-102", "SNP-M-201")]
        self.assertEqual(len(self.gids()), 3, "PDF 세 장 가운데 마지막 것만 들어옴")
        self.assertEqual(len({self.sheet(m)["graph_id"] for m in mids}), 3)
        self.assertEqual(sources.conflicts(P), [])

    def test_every_page_of_a_multi_page_pdf_is_a_sheet(self):
        """여러 쪽 PDF 한 파일은 쪽마다 시트다. 쪽들이 한 이름(graph-drawing)으로 겹치면 마지막 쪽만 들어온다."""
        doc = pdfium.PdfDocument.new()
        for d in ("SNP-M-101", "SNP-M-102", "SNP-M-201"):
            doc.import_pages(pdfium.PdfDocument(sample(d, "pdf")))
        dst = os.path.join(self.tmp, "in3", "three.pdf")
        os.makedirs(os.path.dirname(dst))
        doc.save(dst)
        mid = self.register(dst)
        self.assertEqual(len(self.gids()), 3, "3쪽 PDF에서 한 쪽만 들어옴")
        self.assertEqual(len(project_ctx.graph_names(P)), 3)
        self.assertTrue(all(mid in g for g in self.gids()), self.gids())

    def test_unconfirmed_drawio_with_the_same_page_name_is_another_sheet(self):
        """P2. 쪽 이름이 같은 다른 drawio는 다른 시트다. 첫 도면 구간이 묘비가 되거나 파일 id가 우연히 같은 다른 도면의 기호로 이어지지 않는다."""
        a = self.add("SNP-M-101", "drawio")
        _pg, before = self.make_nodes(a)
        members = before["nodes"][0]["members"]
        b = self.register(self.same_page_name_drawio())
        self.assertEqual(len(self.gids()), 2, "쪽 이름이 같은 다른 drawio가 첫 도면 시트를 밀어냄")
        self.assertNotEqual(self.sheet(a)["graph_id"], self.sheet(b)["graph_id"])
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []), "첫 도면 구간이 묘비가 되거나 다른 기호로 이어짐")

    def test_dexpi_files_with_the_same_drawing_name_are_two_sheets(self):
        """P8. DEXPI 가져오기도 번호 확정 전에는 graph-<DEXPI 도면 이름>이었다. 도면 이름이 같은 다른 DEXPI 파일은 다른 시트다."""
        fixtures = os.path.join(paths.REPO_ROOT, "tests", "fixtures", "dexpi")
        srcs = []
        for name in ("small-pid-dexpi2.xml", "small-pid-proteus.xml"):
            dst = os.path.join(self.tmp, "in-" + name, name)
            os.makedirs(os.path.dirname(dst))
            shutil.copy(os.path.join(fixtures, name), dst)
            srcs.append(dst)
        a = self.register(srcs[0])
        _pg, before = self.make_nodes(a, n=4)
        members = before["nodes"][0]["members"]
        b = self.register(srcs[1])
        self.assertEqual(len(self.gids()), 2, "도면 이름이 같은 다른 DEXPI가 첫 시트를 밀어냄")
        self.assertNotEqual(self.sheet(a)["graph_id"], self.sheet(b)["graph_id"])
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []))

    def test_numbering_a_new_drawing_is_not_blocked_by_another_drawings_segments(self):
        """구간이 없는 새 도면의 번호 확정은 다른 도면의 구간 때문에 막히지 않는다(판 사진에 적힌 그래프 전체 참조는 구간이 가리키는 것이 아님)."""
        a = self.add("SNP-M-101", "drawio")
        self.make_nodes(a)
        b = self.add("SNP-M-102", "drawio")
        out = self.confirm(b, {"drawing_number": "SNP-M-102"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.sheet(b)["graph_id"], "graph-SNP-M-102")

    def test_refusal_names_the_drawing_by_file_not_by_its_temporary_name(self):
        """옮기지 못하는 기록(지식그래프 판단)이 있는 번호 미확정 도면의 번호 확정은 막되, 안내에 임시 이름(graph-material-…)이 아니라 파일 이름·쪽이 나온다."""
        a = self.add("SNP-M-101", "drawio")
        self.make_nodes(a)
        self.judge_in_kg(self.sheet(a)["graph_id"])
        out = self.confirm(a, {"drawing_number": "SNP-M-101"})
        self.assertFalse(out["ok"])
        reason = out["refused"][0]["reason"]
        self.assertNotIn("material-", reason)
        self.assertIn("SNP-M-101_RCS-main-loop.drawio · 1쪽", reason)

    # ------------------------------------------------------------ 번호가 같은 시트
    def test_reextracting_the_first_format_does_not_hand_the_sheet_to_the_other_format(self):
        """P9. 같은 번호의 drawio와 PDF가 함께 있으면 먼저 있던 형식을 쓴다. 먼저 있던 drawio를 다시 추출해 그래프가 더 새로워져도
        PDF로 갈아타지 않는다(고르기 차례에 그래프 수정 시각을 쓰지 않는다)."""
        a = self.add("SNP-M-101", "drawio")
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-101"})["ok"])
        b = self.add("SNP-M-101", "pdf")
        self.assertTrue(self.confirm(b, {"drawing_number": "SNP-M-101"})["ok"])
        _pg, before = self.make_nodes(a)
        members = before["nodes"][0]["members"]
        self.reextract(a)
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []), "먼저 있던 drawio를 다시 추출했을 뿐인데 PDF로 갈아탐")
        self.assertEqual([(c.get("kind"), c["in_use_format"]) for c in sources.conflicts(P)], [("format", "drawio")])

    def test_registering_the_same_file_again_with_a_number_is_one_sheet(self):
        """P3의 고르기 쪽. 이 단위 전 옛 등록 화면·명령줄은 같은 원본을 도면 번호와 함께 다시 등록할 수 있었다(새 등록 판). 같은 (자료, 쪽)이면
        판이 달라도 한 시트다. 지금은 그 등록을 보류한다(tests.test_sheet_guard). 여기서는 그렇게 이미 저장된 판을 만든다."""
        a = self.add("SNP-M-101", "pdf")
        rec, _p = registry.latest(P, a)
        src = registry.Store(paths.store_root(), P).abs_ref(rec["storage_ref"])
        res = registry.register(src, P, "P&ID", paths.store_root(), NUMBER, BY, number_checked=True)
        self.assertEqual(res["outcome"], "new_version")
        data.extract_and_graph(res["registration_file"])
        self.assertEqual(self.gids(), ["graph-SNP-M-101"], "같은 원본의 두 등록 판이 두 시트로 들어감")

    def test_mixed_formats_and_files_with_the_same_number_wait_for_a_choice(self):
        """같은 번호의 다른 형식·다른 파일(개정판을 다른 파일로, 옛 등록 화면·명령줄은 번호를 그대로 넘긴다)은 말없이 갈아타지 않는다.
        고르기 줄에 오르고 고르기 전에는 먼저 쓰던 파일을 지킨다. 사람이 파일을 고르면 그 파일로 갈아탄다."""
        a = self.register(self.copy_in("SNP-M-101", "drawio", "in-a"), NUMBER)
        _pg, before = self.make_nodes(a)
        members = before["nodes"][0]["members"]
        b = self.register(self.copy_in("SNP-M-101", "pdf", "in-b"), dict(NUMBER))
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []), "같은 번호의 다른 파일이 말없이 작업을 덮음")
        c = self.register(self.copy_in("SNP-M-102", "pdf", "in-c"), dict(NUMBER))
        rows = sources.conflicts(P)
        self.assertEqual([(r.get("kind"), r.get("in_use_material")) for r in rows], [("format", a)], rows)
        self.assertEqual(sorted(x.get("material_id") for x in rows[0]["candidates"]), sorted([a, b, c]))
        self.assertEqual(self.gids(), ["graph-SNP-M-101"])
        sources.choose(P, "SNP-M-101", None, BY, material_id=c)
        self.assertEqual(project_ctx.graph_names(P)["graph-SNP-M-101"], self.sheet(c)["name"], "사람이 고른 파일로 갈아탐")

    def test_same_format_other_file_with_the_same_number_is_a_file_choice(self):
        """같은 형식 같은 번호의 다른 파일은 형식으로 고를 수 없어 kind file 줄이 된다. 사유 코드가 엔진 값에 나온다."""
        a = self.register(self.copy_in("SNP-M-101", "pdf", "in-a"), NUMBER)
        _pg, before = self.make_nodes(a)
        members = before["nodes"][0]["members"]
        b = self.register(self.copy_in("SNP-M-102", "pdf", "in-b"), dict(NUMBER))
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []), "같은 번호의 다른 PDF가 말없이 작업을 덮음")
        rows = sources.conflicts(P)
        self.assertEqual([(r.get("kind"), r.get("reason"), r.get("in_use_material")) for r in rows],
                         [("file", "same_number_other_file", a)], rows)
        self.assertEqual(sorted(x.get("material_id") for x in rows[0]["candidates"]), sorted([a, b]))
        with self.assertRaises(ValueError):
            sources.choose(P, "SNP-M-101", "pdf_vector", BY)    # 형식이 같아 형식으로는 고를 수 없음

    def test_choosing_another_drawio_file_does_not_reuse_matching_file_ids(self):
        """조건 4. 같은 번호의 다른 drawio로 갈아탈 때 파일 id(source_object_id)가 우연히 같아도 이어짐의 증거로 쓰지 않는다.
        표시로 증명하지 못하는 구성요소는 묘비다(다른 도면의 기호로 조용히 이어지지 않음)."""
        a = self.register(self.copy_in("SNP-M-101", "drawio", "in-a"), NUMBER)
        _pg, before = self.make_nodes(a)
        members = before["nodes"][0]["members"]
        b = self.register(self.copy_in("SNP-M-102", "drawio", "in-b"), dict(NUMBER))
        with open(confirmation.extraction_path(self.sheet(a)["name"]), encoding="utf-8") as fh:
            ours = {x["source_object_id"] for x in json.load(fh)["nodes"][:6]}
        with open(confirmation.extraction_path(self.sheet(b)["name"]), encoding="utf-8") as fh:
            theirs = {x["source_object_id"] for x in json.load(fh)["nodes"]}
        self.assertTrue(ours & theirs, "시험 전제: 두 파일이 같은 파일 id를 우연히 씀")
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []), "고르기 전에 다른 파일의 같은 id 기호로 이어짐")
        sources.choose(P, "SNP-M-101", None, BY, material_id=b)
        _pg, n = self.node()
        self.assertEqual(n["members"], [], "다른 파일의 같은 id 기호로 이어지면 안 됨")
        self.assertEqual(len(n.get("lost") or []), len(members))

    # ------------------------------------------------------------ 이미 겹친 저장본
    def _open_saved_collision_twice(self, kind):
        a, b, seen = self.collided(kind)
        gid = project_ctx.project_graph(P)["sheets"][0]["graph_id"]
        self.reextract(b)                                   # 명시적인 차례(다시 추출)가 정착을 부른다
        for _ in range(2):
            project_ctx._PROJECT_GRAPHS.clear()            # 앱을 새로 켠 것처럼
            project_ctx._NAMES.clear()
            pg, n = self.node()
            self.assertEqual((n["members"], n.get("lost") or []), (seen["members"], seen.get("lost") or []),
                             "열 때 지금 보이던 구간이 뒤집힘")
            self.assertEqual(len(pg["sheets"]), 2, "가려졌던 도면이 새 시트로 들어와야 함")
            self.assertIn(gid, [s["graph_id"] for s in pg["sheets"]], "지금 쓰던 시트 이름을 지킴")
            self.assertEqual(project_ctx.graph_names(P)[gid], self.sheet(b)["name"])

    def test_saved_collision_of_two_pdfs_opens_the_same_twice(self):
        self._open_saved_collision_twice("pdf")

    def test_saved_collision_of_two_drawios_opens_the_same_twice(self):
        self._open_saved_collision_twice("drawio")


if __name__ == "__main__":
    unittest.main()
