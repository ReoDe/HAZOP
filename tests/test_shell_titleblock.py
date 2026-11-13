"""새 웹 화면의 표제란 패널 엔진 길(hazop/shell/api_titleblock.py). 실행: python -m unittest tests.test_shell_titleblock
가상 도면 SNP-M-101을 임시 작업 루트·저장 루트에 등록·추출하고 실제 엔진(hazop.register.titleblock)을 부른다.
읽기의 후보·근거, 확정 → 작업 → 다시 읽어도 유지, 고쳐서 확정, 취소, 바로 거절(사람 이름·판·끊길 구간), 인자 검사를 본다.
"""

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

from hazop.shell import api, api_titleblock  # noqa: E402
from hazop.study import nodes  # noqa: E402
from tests.test_titleblock import Base as EngineBase  # noqa: E402


class Events:
    def __init__(self):
        self.items = []

    def __call__(self, event):
        self.items.append(event)

    def of(self, name):
        return [e.get("data") for e in self.items if e.get("t") == "event" and e.get("name") == name]

    def changes(self, topic):
        return [e for e in self.items if e.get("t") == "changed" and e.get("topic") == topic]


class Base(EngineBase):
    def setUp(self):
        super().setUp()
        self.mid = self.add()
        self.events = Events()
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events)
        self.engine.settings["reviewer_name"] = "검토자A"
        self.engine.settings["project_id"] = "P1"
        self.commands = {}
        api_titleblock.register(self.commands)

    def read(self, *parts):
        r = api_titleblock.read(self.engine, ["titleblock"] + list(parts), {})
        return None if r is None else json.loads(r.body.decode("utf-8"))

    def cmd(self, name, **args):
        cmd = self.commands["titleblock." + name]
        return cmd.handler(self.engine, api.check_args(cmd.spec, args))

    def ver(self):
        return self.read(self.mid)["ver"]


class ReadTest(Base):
    def test_rows_show_candidates_evidence_and_state(self):
        s = self.read()
        self.assertEqual((s["project_id"], s["reviewer"], s["totals"]), ("P1", "검토자A", {"materials": 1, "confirmed": 0}))
        r = s["rows"][0]
        self.assertEqual((r["material_id"], r["state"]), (self.mid, "unconfirmed"))
        dwg = r["fields"][0]
        self.assertEqual((dwg["field"], dwg["value"], dwg["candidate"]), ("drawing_number", None, "SNP-M-101"))
        self.assertIn("표제란", dwg["evidence"]["text"])
        self.assertEqual(r["sheets"][0]["graph_id"], "graph-SNP-M-101")
        self.assertIsNone(self.read("material-000000000000"))


class CommandTest(Base):
    def test_confirm_runs_a_job_and_survives_reopening(self):
        out = self.cmd("confirm", material_id=self.mid, ver=self.ver(),
                       fields={"drawing_number": "SNP-M-101", "design_revision": "0", "title": "주 배관"})
        self.assertIn("job", out)
        self.assertTrue(self.engine.wait_jobs(60))
        done = [d for d in self.events.of("job.done") if d["id"] == out["job"]]
        self.assertTrue(done, self.events.items)
        self.assertEqual(done[0]["result"]["version"], 2)
        self.assertTrue(self.events.changes("titleblock"))
        r = self.read(self.mid)
        self.assertEqual((r["state"], r["fields"][2]["value"], r["fields"][2]["confirmed_by"]), ("confirmed", "주 배관", "검토자A"))
        engine2 = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=lambda e: None)
        again = json.loads(api_titleblock.read(engine2, ["titleblock", self.mid], {}).body.decode("utf-8"))
        self.assertEqual(again["state"], "confirmed", "다시 열어도 유지")

    def test_unconfirm(self):
        self.cmd("confirm", material_id=self.mid, ver=self.ver(), fields={"title": "주 배관"})
        self.assertTrue(self.engine.wait_jobs(60))
        out = self.cmd("unconfirm", material_id=self.mid, ver=self.ver(), fields=["title"], reason="잘못 고름")
        self.assertTrue(self.engine.wait_jobs(60))
        self.assertTrue(out["changed"])
        self.assertEqual(self.read(self.mid)["state"], "unconfirmed")

    def test_refusals_come_back_at_once(self):
        with self.assertRaises(api.CommandError) as cm:
            self.cmd("confirm", material_id=self.mid, ver="sha256:낡음", fields={"title": "x"})
        self.assertEqual(cm.exception.code, "stale")
        self.engine.settings["reviewer_name"] = ""
        with self.assertRaises(api.CommandError) as cm:
            self.cmd("confirm", material_id=self.mid, ver=self.ver(), fields={"title": "x"})
        self.assertIn("사람 이름", cm.exception.message)
        self.engine.settings["reviewer_name"] = "검토자A"
        self.cmd("confirm", material_id=self.mid, ver=self.ver(), fields={"drawing_number": "SNP-M-101"})
        self.assertTrue(self.engine.wait_jobs(60))
        self.make_nodes(self.mid)   # 새 화면의 실제 길로 만든 구간(프로젝트 그래프 구간 파일)
        with self.assertRaises(api.CommandError) as cm:
            self.cmd("confirm", material_id=self.mid, ver=self.ver(), fields={"drawing_number": "SNP-M-777"})
        self.assertIn("구간", cm.exception.message)
        self.assertEqual(self.read(self.mid)["version"], 2, "막히면 작업을 시작하지 않음")
        with self.assertRaises(api.CommandError):
            self.cmd("confirm", material_id=self.mid, ver=self.ver(), fields={"owner": "x"})
        same = self.cmd("confirm", material_id=self.mid, ver=self.ver(), fields={"drawing_number": "SNP-M-101"})
        self.assertEqual(same["changed"], False)

    def test_material_without_extraction_is_confirmed_without_a_job(self):
        other = self.add("SNP-M-102", extract=False)
        out = self.cmd("confirm", material_id=other, ver=self.read(other)["ver"], fields={"title": "가압기"})
        self.assertNotIn("job", out)
        self.assertEqual(out["row"]["fields"][2]["value"], "가압기")


def pump(sec):
    from PySide6.QtCore import QCoreApplication
    import time
    end = time.monotonic() + sec
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


class PanelTest(Base):
    """실제 새 화면(화면 밖)의 표제란 패널: 번호 칸이 잠긴 도면에서 개정·제목만 고쳐 확정하면 번호 후보를 보내지 않는다."""

    def js(self, win, code, timeout=10.0):
        import time
        out = []
        win.view.page().runJavaScript(code, 0, out.append)
        end = time.monotonic() + timeout
        while time.monotonic() < end and not out:
            pump(0.02)
        return out[0] if out else None

    def wait(self, win, code, timeout=60.0):
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.js(win, code):
                return True
            pump(0.1)
        return False

    def test_locked_number_is_not_sent_and_only_edited_fields_go(self):
        from hazop.app import make_application
        from hazop.shell.window import ShellWindow
        self.qapp = make_application(["titleblock-test"])
        self.make_nodes(self.mid)          # 번호 칸이 잠기는 도면(구간이 가리킴)
        settings = os.path.join(self.tmp, "shell-settings.json")
        with open(settings, "w", encoding="utf-8") as fh:
            json.dump({"reviewer_name": "검토자A", "project_id": "P1"}, fh)
        dbg = mock.patch.dict(os.environ, {"HAZOP_DEBUG": "1"})   # window.__hz 시험 갈고리(화면이 읽는 동안 내내 켜 둠)
        dbg.start()
        self.addCleanup(dbg.stop)
        win = ShellWindow(settings_path=settings, size=(1366, 768))
        win.show()
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        self.assertTrue(self.wait(win, "!!window.__hz && document.querySelector('.rail') !== null"), "웹 화면이 뜨지 않음")
        self.js(win, "window.__hz.store.set({panel: 'titleblock'})")
        self.assertTrue(self.wait(win, "document.querySelectorAll('.titleblock .tb-row').length === 1"))
        self.assertTrue(self.js(win, "document.querySelector('.titleblock input.tb-input').disabled"), "번호 칸이 잠김")
        typed = self.js(win, """(() => { const inp = document.querySelectorAll('.titleblock input.tb-input')[2];
            inp.value = '주 배관(고침)'; inp.dispatchEvent(new Event('input', { bubbles: true })); return inp.value; })()""")
        self.assertEqual(typed, "주 배관(고침)")
        self.js(win, "document.querySelector('.titleblock button[aria-label=\"입력한 값으로 확정\"]').click()")
        self.assertTrue(self.wait(win, "(document.querySelector('.titleblock').innerText || '').includes('확정했습니다')", 120),
                        self.js(win, "document.querySelector('.titleblock').innerText"))
        r = self.read(self.mid)
        self.assertEqual([f["value"] for f in r["fields"]], [None, None, "주 배관(고침)"],
                         "고친 제목만 확정되고 잠긴 번호 후보는 보내지 않음")
        self.js(win, """(() => { const b = document.querySelector('.titleblock button[aria-label="확정 전 항목을 후보 그대로 확정"]');
            b.click(); return true; })()""")
        self.assertTrue(self.wait(win, "document.querySelectorAll('.titleblock .tb-row.partial').length === 1 && "
                                       "(document.querySelector('.titleblock').innerText || '').includes('등록 버전 3')", 120))
        r = self.read(self.mid)
        self.assertEqual((r["fields"][0]["value"], r["fields"][1]["value"]), (None, "0"),
                         "'후보 그대로 확정'도 잠긴 번호는 빼고 개정만 확정")


if __name__ == "__main__":
    unittest.main()
