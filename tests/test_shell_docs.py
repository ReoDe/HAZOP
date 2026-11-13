"""새 웹 화면 설계 문서 패널의 엔진 쪽(hazop/shell/api_docs.py). 실행: python -m unittest tests.test_shell_docs

가상 도면 SNP-M-101·102를 프로젝트에 등록·추출해 두고(템플릿 작업 루트를 시험마다 복사), 가상 설계 문서 PDF(tests/fixtures/docextract, 실제 설계자료 아님)를
등록 → 추출 → 지식그래프까지 실제 엔진으로 돌린다. 도면에 이어짐, 읽을 수 없는 PDF·글자 없는 PDF의 사유, 같은 문서 다시 등록, 채팅 문서 도구에서 찾힘,
웹이 경로를 보내지 못함을 본다.
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hazop import paths  # noqa: E402
from hazop.shell import api, api_docs  # noqa: E402

PID = "A7-PROJ"
DOC_PDF = glob.glob(os.path.join(REPO, "tests", "fixtures", "docextract", "*.pdf"))[0]
_TPL = {}


def template():
    """도면 2장을 프로젝트 PID로 등록·추출한 작업·저장 루트(시험마다 복사해 쓴다)."""
    if "root" not in _TPL:
        from hazop.app import data
        from hazop.register import registry
        tmp = tempfile.mkdtemp(prefix="hazop-shelldocs-tpl-")
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(tmp, "store")}):
            os.makedirs(os.environ["HAZOP_WORK_ROOT"])
            for d in ("SNP-M-101", "SNP-M-102"):
                src = glob.glob(os.path.join(paths.folder("references", "pid-samples"), d + "*", "*.drawio"))[0]
                r = registry.register(src, PID, "P&ID", paths.store_root(), None, "t")
                data.extract_and_graph(r["registration_file"])
        _TPL["root"] = tmp
    return _TPL


def tearDownModule():
    if "root" in _TPL:
        shutil.rmtree(_TPL["root"], ignore_errors=True)


def blank_pdf(path):
    """글자가 없는 PDF(스캔본과 같은 모양: 그림만)."""
    from PySide6.QtGui import QPainter, QPdfWriter
    w = QPdfWriter(path)
    p = QPainter(w)
    p.drawRect(100, 100, 2000, 1000)
    p.end()


class Events:
    def __init__(self):
        self.items = []

    def __call__(self, event):
        self.items.append(event)

    def topics(self):
        return [e.get("topic") for e in self.items if e.get("t") == "changed"]


class Base(unittest.TestCase):
    def setUp(self):
        tpl = template()
        self.tmp = tempfile.mkdtemp(prefix="hazop-shelldocs-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for sub in ("work", "store"):
            shutil.copytree(os.path.join(tpl["root"], sub), os.path.join(self.tmp, sub))
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")}),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        if "docs.add" not in api.COMMANDS:
            api_docs.register(api.COMMANDS)
        from hazop.app import project_ctx
        project_ctx._PROJECT_GRAPHS.clear()
        self.events = Events()
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events, run_jobs=lambda jid, fn: fn())
        self.engine.settings.update(project_id=PID, reviewer_name="검토자A")
        self.picked = [DOC_PDF]
        self.engine.hooks["pick_doc"] = lambda: self.picked

    def read(self, *parts):
        r = api_docs.read(self.engine, ["docs"] + list(parts), {})
        self.assertIsNotNone(r, parts)
        return json.loads(r.body.decode("utf-8"))

    def call(self, name, args=None):
        return self.engine.dispatch(name, args or {})

    def add(self):
        return self.call("docs.add", {"kind": "design_document"})

    def job_events(self, name):
        return [e["data"] for e in self.events.items if e.get("t") == "event" and e.get("name") == name]


class RegisterExtractTest(Base):
    def test_register_extract_and_link_to_the_drawings(self):
        self.assertEqual(self.read()["docs"], [])
        r = self.add()
        self.assertTrue(r["ok"], r)
        done = self.job_events("job.done")
        self.assertEqual(len(done), 1, self.job_events("job.failed"))
        self.assertEqual(done[0]["result"]["counts"], {"doc_chunk": 5, "setpoint": 3, "condition": 3, "requirement": 4})
        s = self.read()
        row = s["docs"][0]
        self.assertEqual((row["state"], row["pages"], row["version"]), ("ok", 3, 1))
        self.assertEqual(row["counts"]["setpoint"], 3)
        self.assertGreater(row["linked_links"], 0)            # 문장 속 태그가 도면 구성요소와 이어짐(지식그래프 관계)
        self.assertGreater(row["linked_nodes"], 0)
        self.assertEqual(s["totals"], {"docs": 1, "ok": 1, "problems": 0, "items": 10})
        self.assertTrue(s["has_kg"])
        self.assertIn("docs", self.events.topics())
        self.assertIn("kg", self.events.topics())

    def test_extracted_items_are_listed_with_source_and_auto_status(self):
        self.add()
        mid = self.read()["docs"][0]["material_id"]
        d = self.read(mid)
        self.assertEqual(d["items_total"], 10)
        trip = next(i for i in d["items"] if i["type"] == "setpoint" and i["value"] == "16.6")
        self.assertEqual((trip["unit"], trip["status"]), ("MPa", "unknown"))          # 자동 추출 · 사람 확인 전
        self.assertIn("쪽", trip["locator"])
        self.assertTrue(any(i["linked"] for i in d["items"]))

    def test_knowledge_shows_in_the_kg_panel_model_connected_to_drawing_components(self):
        from hazop.app import project_ctx
        from hazop.kg import expect, screen
        from hazop.shell import api_kg
        self.add()
        pg = project_ctx.project_graph(PID)
        kg, _ = api_kg._load_kg(PID)
        m = screen.panel_model(pg, kg, expect.evaluate(pg, kg))
        kn = [n for n in m["nodes"].values() if n["layer"] == "kn"]
        self.assertGreaterEqual(len(kn), 16)                                          # 문서·조각·설정치·조건·요건
        pid_ends = [l for l in m["links"] if l["id"].startswith("kn:") and (m["nodes"][l["s"]]["layer"] == "pid" or m["nodes"][l["t"]]["layer"] == "pid")]
        self.assertGreater(len(pid_ends), 0)
        tags = {m["nodes"][x]["label"] for l in pid_ends for x in (l["s"], l["t"]) if m["nodes"][x]["layer"] == "pid"}
        self.assertTrue(tags & {"RC-PIC110", "RC-PSV101", "RC-PV101", "RC-LT110"}, tags)

    def test_same_document_again_is_reused_and_not_extracted_twice(self):
        self.add()
        n = len(self.job_events("job.done"))
        r = self.add()
        self.assertTrue(r["ok"], r)
        done = self.job_events("job.done")
        self.assertEqual(len(done), n + 1)
        self.assertEqual(done[-1]["result"]["outcome"], "reused")
        self.assertIn("이미 등록", done[-1]["result"]["skipped"])
        self.assertEqual(len(self.read()["docs"]), 1)
        self.assertEqual(self.read()["docs"][0]["version"], 1)

    def test_extract_again_by_material_id(self):
        self.add()
        mid = self.read()["docs"][0]["material_id"]
        r = self.call("docs.extract", {"material_id": mid})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.job_events("job.done")[-1]["result"]["outcome"], "extracted")
        self.assertEqual(self.call("docs.extract", {"material_id": "mat-nope"})["error"]["code"], "not_found")


class FailureTest(Base):
    def test_unreadable_pdf_is_refused_with_the_reason_and_nothing_is_listed(self):
        bad = os.path.join(self.tmp, "broken.pdf")
        with open(bad, "wb") as fh:
            fh.write(b"%PDF-1.4 not really a pdf")
        self.picked = [bad]
        self.add()
        failed = self.job_events("job.failed")
        self.assertEqual(len(failed), 1)
        self.assertIn("등록하지 못함", failed[0]["message"])
        self.assertEqual(self.job_events("job.done"), [])
        self.assertEqual(self.read()["docs"], [])

    def test_pdf_without_text_is_registered_but_shown_as_blocked_with_reason(self):
        scan = os.path.join(self.tmp, "scan.pdf")
        blank_pdf(scan)
        self.picked = [scan]
        self.add()
        rows = self.read()["docs"]
        if not rows:                                      # 등록 단계에서 막히면 그 사유가 작업 실패로 남는다
            self.assertIn("글자", self.job_events("job.failed")[0]["message"])
            return
        self.assertEqual(rows[0]["state"], "blocked")
        self.assertTrue(any("글자" in r for r in rows[0]["reasons"]), rows[0]["reasons"])
        self.assertEqual(self.read()["totals"]["problems"], 1)

    def test_extraction_blocked_after_registration_shows_the_reason(self):
        from hazop.app import data
        self.add()
        e = next(x for x in data.list_registrations() if x["record"].get("material_type") == "design_document")
        p = os.path.join(data.doc_root(), e["extract_name"], "document_knowledge.json")
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        d["validation"] = {"status": "blocked", "blockers": [{"check": "no_text", "reason": "PDF에서 글자를 읽지 못함"}], "unknowns": []}
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        row = self.read()["docs"][0]
        self.assertEqual((row["state"], row["reasons"]), ("blocked", ["PDF에서 글자를 읽지 못함"]))

    def test_non_pdf_is_refused_and_missing_hook_is_an_error(self):
        txt = os.path.join(self.tmp, "a.txt")
        open(txt, "w").close()
        self.picked = [txt]
        self.assertEqual(self.add()["error"]["code"], "bad_args")
        del self.engine.hooks["pick_doc"]
        self.assertEqual(self.add()["error"]["code"], "failed")

    def test_cancelled_dialog_starts_nothing(self):
        self.picked = []
        self.assertEqual(self.add()["data"], {"jobs": []})
        self.assertEqual(self.job_events("job.progress"), [])

    def test_fallback_to_the_drawing_picker_keeps_only_pdfs(self):
        del self.engine.hooks["pick_doc"]
        self.engine.hooks["pick_files"] = lambda: [DOC_PDF, os.path.join(self.tmp, "x.drawio")]
        self.assertTrue(self.add()["ok"])
        self.assertEqual(len(self.read()["docs"]), 1)

    def test_web_cannot_send_a_path(self):
        r = self.call("docs.add", {"kind": "design_document", "path": DOC_PDF})
        self.assertEqual(r["error"]["code"], "bad_args")
        self.assertEqual(self.call("docs.add", {"kind": "P&ID"})["error"]["code"], "bad_args")
        self.assertEqual(self.read()["docs"], [])

    def test_reading_writes_no_file(self):
        self.add()
        before = sorted(os.path.join(d, f) for d, _, fs in os.walk(self.tmp) for f in fs)
        mid = self.read()["docs"][0]["material_id"]
        self.read(mid)
        self.assertEqual(sorted(os.path.join(d, f) for d, _, fs in os.walk(self.tmp) for f in fs), before)


class ChatTest(Base):
    def test_registered_document_is_found_by_the_chat_document_tools(self):
        from hazop.chat import context, tools
        self.add()
        ctx = context.load_context(PID)
        res = tools.call(ctx, "search_documents", {"query": "RC-PIC110 설정치"})
        self.assertTrue(res["ok"], res)
        chunks = res["data"]["chunks"]
        self.assertTrue(chunks)
        got = tools.call(ctx, "get_document", {"chunk_id": chunks[0]["chunk_id"]})
        self.assertTrue(got["ok"], got)
        self.assertIn("SNP-DOC-102", got["data"]["document"]["title"] or "")

    def test_chat_functions_list_and_run_extraction_without_the_web(self):
        self.add()
        rows = api_docs.list_documents(self.engine)
        self.assertEqual(len(rows), 1)
        out = api_docs.run_extraction(self.engine, rows[0]["material_id"])
        self.assertTrue(out["job"])
        api_docs.open_panel(self.engine)
        self.assertIn({"t": "event", "name": "docs.open", "data": {}}, self.events.items)


if __name__ == "__main__":
    unittest.main()
