"""시트 정착(hazop.graph.sources.settle, hazop.app.data.settle_sheets) 시험: 이 단위 전에 쓰던 시트 이름을 자리 표에 붙박는 일.
근거: docs/units/2026-11-13-drawing-knowledge/evidence/sheet-identity-design.md §4.2.

- 읽는 길(프로젝트 그래프·도면 이름·고르기 줄·셸 도면 목록)과 다른 그래프 폴더를 준 고르기는 파일을 쓰지 않는다.
- 정착은 명시적인 차례(다시 추출·그래프 짓기·settle_sheets)에서만, 작업 루트에서만 돈다. 쓰기 전에 백업하고, 실패하면 옛 상태 그대로,
  두 번 돌려도 한 번과 같다.
실행: python -m unittest tests.test_sheet_settle
"""

import hashlib
import os
import shutil
import unittest
from unittest import mock

from tests.test_sheet_gid_paths import SheetCase, legacy_name

from hazop import paths
from hazop.app import data, project_ctx
from hazop.graph import project, sources
from hazop.kg import auto
from hazop.study import nodes
from tests.test_titleblock import P


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

    def test_failed_settle_leaves_the_old_state(self):
        """다시 짓기가 둘째 시트에서 실패하면 앞서 고친 시트도 되돌리고 자리 표를 쓰지 않는다(옛 상태 그대로). 다음 정착이 끝까지 한다."""
        self.legacy_three()
        before = tree(paths.output_root())
        real = data.script_module("build_graph").render_one
        calls = []

        def flaky(path, **kw):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("디스크가 가득 참(시험)")
            return real(path, **kw)
        with mock.patch.object(data.script_module("build_graph"), "render_one", flaky):
            with self.assertRaises(OSError):
                data.settle_sheets(P)
        self.assertEqual(tree(paths.output_root()), before, "실패한 정착이 시트 하나를 바꾼 채 남김")
        self.assertFalse(os.path.exists(sources.choices_path(P)), "실패한 정착이 자리 표를 씀")
        self.assertTrue(data.settle_sheets(P)["changed"])
        self.assertEqual(len(self.gids()), 3)


if __name__ == "__main__":
    unittest.main()
