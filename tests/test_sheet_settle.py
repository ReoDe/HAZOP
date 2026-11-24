"""시트 정착(hazop.graph.sources.settle, hazop.app.data.settle_sheets) 시험: 이 단위 전에 쓰던 시트 이름을 자리 표에 붙박는 일.
근거: docs/units/2026-11-13-drawing-knowledge/evidence/sheet-identity-design.md §4.2.

- 읽는 길(프로젝트 그래프·도면 이름·고르기 줄·셸 도면 목록)과 다른 그래프 폴더를 준 고르기는 파일을 쓰지 않는다.
- 정착은 명시적인 차례(다시 추출·그래프 짓기·settle_sheets)에서만, 작업 루트에서만 돈다. 쓰기 전에 백업하고, 실패하면 옛 상태 그대로,
  두 번 돌려도 한 번과 같다.
실행: python -m unittest tests.test_sheet_settle
"""

import hashlib
import json
import os
import shutil
import unittest
from unittest import mock

from tests.test_sheet_gid_paths import NUMBER, SheetCase, legacy_name

from hazop import paths
from hazop.app import data, project_ctx
from hazop.graph import project, sources
from hazop.kg import auto
from hazop.study import nodes
from tests.test_titleblock import BY, P


def tree(root, skip=()):
    """{상대 경로: (크기, 바뀐 시각, 내용 해시)}. 같은 바이트를 다시 쓴 것도 바뀐 것으로 센다. skip: 세지 않는 하위 폴더(상대 경로)."""
    out = {}
    for d, _dirs, names in os.walk(root):
        if any(os.path.relpath(d, root).startswith(s) for s in skip):
            continue
        for n in names:
            p = os.path.join(d, n)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = (os.path.getsize(p), os.stat(p).st_mtime_ns,
                                                 hashlib.sha256(fh.read()).hexdigest())
    return out


class SettleTest(SheetCase):
    def legacy_three(self):
        """이 단위 전 앱으로 번호 없는 PDF 세 장을 넣은 프로젝트(셋 다 graph-drawing, 마지막 것만 보임)."""
        with mock.patch("hazop.graph.sources.sheet_name", legacy_name, create=True), \
                mock.patch("hazop.app.data.settle_sheets", lambda *a, **k: None, create=True):
            mids = [self.add(d, "pdf") for d in ("SNP-M-101", "SNP-M-102", "SNP-M-201")]
            self.make_nodes(mids[-1])
        project_ctx._PROJECT_GRAPHS.clear()
        project_ctx._NAMES.clear()
        self.assertEqual(self.gids(), ["graph-drawing"], "시험 전제: 옛 규칙에서는 한 시트")
        return mids

    def test_reading_writes_nothing(self):
        """프로젝트를 열고 읽기만 하면(프로젝트 그래프, 도면 이름, 고르기 줄, 셸 도면 목록) 작업 루트의 어느 파일도 바뀌지 않는다."""
        from hazop.shell import api
        self.legacy_three()
        cache = os.path.relpath(paths.folder("cache"), paths.work_root())   # 도면 이름·추출 요약 캐시는 HEAD에서도 읽을 때 쓴다(캐시일 뿐)
        before = tree(paths.work_root(), (cache,))

        class E:
            def project_id(self):
                return P

            def graph_names(self):
                return dict(project_ctx.graph_names(P))
        for _ in range(2):
            project_ctx._PROJECT_GRAPHS.clear()
            project_ctx._NAMES.clear()
            project_ctx.project_graph(P)
            project_ctx.graph_names(P)
            sources.conflicts(P)
            project.load(P)
            api.ReadApi(E()).drawings()
        self.assertEqual(tree(paths.work_root(), (cache,)), before, "읽기만 했는데 파일이 바뀜")
        self.assertFalse(os.path.exists(sources.choices_path(P)), "읽는 길에서 자리 표를 씀")

    def test_another_graph_root_is_read_only(self):
        """그래프 폴더만 바꾼 고르기(시험·검사 스크립트·지식그래프 빌드의 graph_root)는 그 폴더도 작업 루트도 쓰지 않는다."""
        self.legacy_three()
        other = os.path.join(self.tmp, "other", "graph")
        shutil.copytree(paths.output_root("graph"), other)
        shutil.copytree(paths.output_root("extract"), os.path.join(self.tmp, "other", "extract"))
        before, before_other = tree(paths.work_root()), tree(os.path.join(self.tmp, "other"))
        project.load(P, graph_root=other)
        auto.project_graphs(P, other)
        sources.conflicts(P, graph_root=other)
        self.assertEqual(tree(paths.work_root()), before)
        self.assertEqual(tree(os.path.join(self.tmp, "other")), before_other)

    def test_settle_keeps_the_visible_sheet_backs_up_and_is_idempotent(self):
        """정착은 지금 보이던 시트(마지막 PDF)의 이름 graph-drawing을 지키고 가려졌던 두 장을 임시 이름으로 들인다. 쓰기 전에 백업하고,
        다시 돌리면 아무것도 쓰지 않는다. 구간은 그대로다."""
        mids = self.legacy_three()
        pg = project_ctx.project_graph(P)
        before = nodes.load(pg)["nodes"][0]
        out = data.settle_sheets(P)
        self.assertTrue(out["changed"], out)
        self.assertEqual(sorted(r["from"] for r in out["renamed"]), ["graph-drawing", "graph-drawing"])
        self.assertEqual(out["seats"]["graph-drawing"]["material_id"], mids[-1])
        self.assertEqual(out["seats"]["graph-drawing"]["why"], "legacy")
        self.assertTrue(out["backup"] and os.path.isdir(out["backup"]), "정착 전 백업")
        backed = [os.path.basename(os.path.dirname(f)) for f in out["backup_files"]]
        self.assertEqual(sorted(set(backed)), sorted(r["name"] for r in out["renamed"]), "다시 지은 폴더의 파일만 백업")
        after = tree(paths.work_root())
        again = data.settle_sheets(P)
        self.assertFalse(again["changed"], again)
        self.assertEqual(tree(paths.work_root()), after, "두 번째 정착이 무엇이든 씀")
        pg = project_ctx.project_graph(P)
        self.assertEqual(len(pg["sheets"]), 3)
        n = nodes.load(pg)["nodes"][0]
        self.assertEqual((n["members"], n.get("lost") or []), (before["members"], before.get("lost") or []))

    def test_a_sheet_that_cannot_be_rebuilt_is_skipped_with_a_reason(self):
        """가려진 시트 하나를 다시 짓지 못해도(만들다 실패) 정착은 나머지를 마치고, 그 시트만 옛 이름 그대로 두며 사유를 돌려준다.
        그 사유는 자리 표에 남아 고르기 줄(reason settle_rebuild_failed)로 보인다."""
        self.legacy_three()
        real = data.script_module("build_graph").render_one
        calls = []

        def flaky(path, **kw):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("디스크가 가득 참(시험)")
            return real(path, **kw)
        with mock.patch.object(data.script_module("build_graph"), "render_one", flaky):
            out = data.settle_sheets(P)
        self.assertTrue(out["changed"])
        self.assertEqual((len(out["renamed"]), len(out["skipped"])), (1, 1), out)
        self.assertIn("디스크가 가득 참", out["skipped"][0]["reason"])
        self.assertEqual(len(self.gids()), 2)
        rows = sources.conflicts(P)
        self.assertEqual([r["reason"] for r in rows], ["settle_rebuild_failed"], rows)
        self.assertIn("디스크가 가득 참", rows[0]["text"])

    def test_a_broken_hidden_sheet_does_not_block_reextracting_the_visible_one(self):
        """이 단위 전 저장본에서 가려진 도면의 추출 결과가 깨져 있어도(source_locations 없음) 보이던 도면의 다시 추출·다시 짓기는 된다."""
        from hazop.extract import confirmation
        from hazop.shell import sheet_refresh
        a, b, _seen = self.collided("pdf")
        path = confirmation.extraction_path(self.sheet(a)["name"])
        with open(path, encoding="utf-8") as fh:
            ex = json.load(fh)
        del ex["source_locations"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(ex, fh)
        self.reextract(b)
        sheet_refresh.rebuild(self.sheet(b)["name"])
        self.assertEqual([r["reason"] for r in sources.conflicts(P)], ["settle_rebuild_failed"])

    def test_old_set_does_not_follow_matching_file_ids_to_the_other_file(self):
        """조건 4, 이 단위 전 집합: 같은 번호의 drawio 둘(뒤에 넣은 B가 보임) 위에 만든 구간을 정착 뒤 A로 갈아타도, 시트 자료 칸이 없는
        옛 판 사진이라 A의 같은 파일 id 기호로 잇지 않는다(묘비)."""
        from hazop.app import project_ctx
        with mock.patch("hazop.graph.sources.sheet_name", legacy_name, create=True), \
                mock.patch("hazop.app.data.settle_sheets", lambda *a, **k: None, create=True):
            a = self.register(self.copy_in("SNP-M-101", "drawio", "in-a"), NUMBER)
            b = self.register(self.copy_in("SNP-M-102", "drawio", "in-b"), dict(NUMBER))
            _pg, ns = self.make_nodes(b)
        members = ns["nodes"][0]["members"]
        path = nodes.store_path(P, "project-" + P)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc.pop("graph_member_sheets", None)          # f945ff2 전 집합에는 이 칸이 없다
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        project_ctx._PROJECT_GRAPHS.clear()
        project_ctx._NAMES.clear()
        self.assertEqual(data.settle_sheets(P)["seats"]["graph-SNP-M-101"]["material_id"], b)
        sources.choose(P, "SNP-M-101", None, BY, material_id=a)
        n = nodes.load(project_ctx.project_graph(P))["nodes"][0]
        self.assertEqual((n["members"], len(n.get("lost") or [])), ([], len(members)), "다른 파일의 같은 id 기호로 이어짐")

    def test_settle_leaves_results_and_initiating_event_references_alone(self):
        """⑤·⑥ 참조까지 있는 저장본: 정착은 그 파일을 쓰지 않고, 참조하는 시트(보이던 도면)의 이름과 자료가 그대로다."""
        from hazop.app import project_ctx
        from hazop.ie import store as ie_store
        a, b, seen = self.collided("pdf")
        pg = project_ctx.project_graph(P)
        gid = pg["sheets"][0]["graph_id"]
        ref = next(n for n in pg["nodes"] if n.get("sheet") == gid and n.get("source_object_id"))
        refs = {"ie": ie_store.store_path(P), "fmea": ie_store.fmea_path(P)}
        for k, f in refs.items():
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "w", encoding="utf-8") as fh:
                json.dump({"ref": "%s#%s" % (gid, ref["source_object_id"]), "entity_id": ref["entity_id"]}, fh)
        before = {k: open(f, "rb").read() for k, f in refs.items()}
        data.settle_sheets(P)
        self.assertEqual({k: open(f, "rb").read() for k, f in refs.items()}, before)
        pg = project_ctx.project_graph(P)
        sheet = next(s for s in pg["sheets"] if s["graph_id"] == gid)
        self.assertEqual(sheet["material_id"], b, "참조하던 시트의 자료가 바뀜")
        self.assertIn(ref["entity_id"], {n["entity_id"] for n in pg["nodes"]})

    def test_temporary_name_sheet_is_not_exported_to_dexpi_and_says_why(self):
        """임시 이름 시트(번호 미확정)는 DEXPI 내보내기 목록에서 '도면 번호가 없음'으로 빠진다."""
        from hazop.export import dexpi_export
        mid = self.add("SNP-M-101", "pdf")
        rows = [r for r in dexpi_export.list_exportable() if r["name"] == self.sheet(mid)["name"]]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["exportable"])
        self.assertIn("도면 번호가 없음", rows[0]["why"])


if __name__ == "__main__":
    unittest.main()
