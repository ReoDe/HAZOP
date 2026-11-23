"""셸 화면의 도면 이름(시트 정체 U4). 실행: python -m unittest tests.test_shell_sheet_names

번호를 확정하지 않은 여러 쪽 PDF를 실제로 등록·추출하고(합성 3쪽 PDF, 임시 작업·저장 루트), 셸이 내주는 읽기
(도면 목록·AI 검토 목록·다음에 할 일·구간 카드 초안·DEXPI 목록)가 임시 이름(graph-material-…-p0)이나 폴더 이름(SCN__material-…)을
글로 내지 않고 사람용 이름('three.pdf · 2쪽')을 쓰는지, 도면 목록이 쪽마다 한 줄이고 번호 상태를 싣는지 본다. AI·구독 호출 없음.
"""

import json
import os
import re
import unittest

import pypdfium2 as pdfium

from tests.test_sheet_gid_paths import SheetCase
from tests.test_titleblock import BY, P, sample

TEMP = re.compile(r"graph-material-|SCN__|material-[0-9a-f]{12}-p\d")


class SheetNamesTest(SheetCase):
    def setUp(self):
        super().setUp()
        doc = pdfium.PdfDocument.new()
        for d in ("SNP-M-101", "SNP-M-102", "SNP-M-201"):
            doc.import_pages(pdfium.PdfDocument(sample(d, "pdf")))
        dst = os.path.join(self.tmp, "in3", "three.pdf")
        os.makedirs(os.path.dirname(dst))
        doc.save(dst)
        self.mid = self.register(dst)
        from hazop.shell import api
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=lambda *a, **k: None,
                                 run_jobs=lambda job_id, fn: fn())
        self.engine.settings.update(reviewer_name=BY, project_id=P)
        self.engine.set_project(P) if hasattr(self.engine, "set_project") else None

    def read(self, *parts):
        from hazop.shell import api
        r = api.ReadApi(self.engine).read(list(parts), {})
        self.assertIsNotNone(r, parts)
        return json.loads(r.body.decode("utf-8"))

    def shown_text(self, data, keys=("display", "drawing_number", "label", "text", "sheet", "name_hint")):
        """화면 글로 쓰이는 칸만 모은다(폴더 이름 name·graph_id는 열쇠라 화면에 내지 않음)."""
        out = []

        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in keys and isinstance(v, str):
                        out.append(v)
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(data)
        return out

    def test_the_drawing_list_has_a_row_per_page_with_human_names(self):
        d = self.read("drawings")
        self.assertEqual(self.engine.project_id(), P)
        rows = d["drawings"]
        self.assertEqual(len(rows), 3, "3쪽 PDF는 쪽마다 한 줄")
        self.assertEqual([r["display"] for r in rows], ["three.pdf · 1쪽", "three.pdf · 2쪽", "three.pdf · 3쪽"])
        for r in rows:
            self.assertEqual(r["number_state"], "unconfirmed")
            self.assertTrue(r["notice"] and r["notice"]["text"], "번호가 없는 까닭(먼저 표제란을 확정하세요)")
        for t in self.shown_text(d):
            self.assertNotRegex(t, TEMP)

    def test_other_reads_use_the_same_names(self):
        names = {r["graph_id"]: r["display"] for r in self.read("drawings")["drawings"]}
        ov = self.read("aireview")
        self.assertEqual({r["graph_id"]: r["drawing_number"] for r in ov["drawings"]}, names, "AI 검토 목록도 같은 이름")
        nx = self.read("next")
        for t in self.shown_text(nx) + [i.get("detail") or "" for i in nx["items"]]:
            self.assertNotRegex(t, TEMP)
        from hazop.shell import api_nodes
        gid = sorted(names)[1]
        from hazop.app import project_ctx
        pg = project_ctx.project_graph(P)
        ids = [n["local_id"] for n in pg["nodes"] if n.get("sheet") == gid and n.get("local_id")][:3]
        if ids:
            sg = api_nodes.suggest(self.engine, gid, ids)
            self.assertNotRegex(sg["name"], TEMP)
        dx = self.read("dexpi")
        for t in self.shown_text(dx):
            self.assertNotRegex(t, TEMP)


if __name__ == "__main__":
    unittest.main()
