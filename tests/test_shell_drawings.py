"""새 웹 화면의 도면 쪽 확정과 DEXPI 내보내기·가져오기(hazop/shell/api_drawings.py, register_flow). 실행: python -m unittest tests.test_shell_drawings

가상 도면 SNP-M-101의 실제 추출·그래프를 임시 작업 루트에 두고 실제 엔진(confirmation·dexpi_export·registry)을 부른다.
조건 미충족 때 확정 거부, 확정 뒤 내보내기에 그 쪽만 들어감, 확정 0쪽 안내, 읽을 수 없는 DEXPI 사유, 덮어쓰기 확인, 경로를 웹이 보내지 않음을 본다.
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
sys.path.insert(0, os.path.join(REPO, "scripts"))

from hazop import paths  # noqa: E402
from hazop.extract import confirmation as cf  # noqa: E402
from hazop.shell import api, api_drawings  # noqa: E402
from tests.test_sheet_confirmation import make_clean  # noqa: E402

_TPL = {}


def template():
    """SNP-M-101을 한 번 추출·그래프로 만든 작업 루트(시험마다 복사해 쓴다)."""
    if "root" not in _TPL:
        from scripts.check_edit_screen import install_sample
        tmp = tempfile.mkdtemp(prefix="hazop-shelldraw-tpl-")
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(tmp, "store")}):
            os.makedirs(os.environ["HAZOP_WORK_ROOT"])
            name = install_sample(os.environ["HAZOP_WORK_ROOT"], "SNP-M-101")
        _TPL.update(root=tmp, name=name)
    return _TPL


def tearDownModule():
    if "root" in _TPL:
        shutil.rmtree(_TPL["root"], ignore_errors=True)


class Events:
    def __init__(self):
        self.items = []

    def __call__(self, event):
        self.items.append(event)

    def changes(self, topic):
        return [e for e in self.items if e.get("t") == "changed" and e.get("topic") == topic]


class Base(unittest.TestCase):
    def setUp(self):
        tpl = template()
        self.tmp = tempfile.mkdtemp(prefix="hazop-shelldraw-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(os.path.join(tpl["root"], "work"), os.path.join(self.tmp, "work"))
        env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        env.start()
        self.addCleanup(env.stop)
        self.name = tpl["name"]
        self.events = Events()
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events)
        self.engine.settings["reviewer_name"] = "검토자A"
        self.gid = {v: k for k, v in self.engine.graph_names().items()}[self.name]
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.engine.hooks["save_dir"] = lambda kind: self.out
        self.asked = []
        self.engine.hooks["confirm_overwrite_files"] = lambda names: self.asked.append(list(names)) or self.answer
        self.answer = True

    def read(self, *parts):
        r = api.ReadApi(self.engine).read(list(parts), {})
        self.assertIsNotNone(r, parts)
        return json.loads(r.body.decode("utf-8"))

    def call(self, name, args=None):
        return self.engine.dispatch(name, args or {})

    def status(self):
        return self.read("sheetconf", self.gid)

    def sheet(self, command, **kw):
        st = self.status()
        return self.call("sheet." + command, dict({"graph_id": self.gid, "ver": st["ver"], "rev": st["rev"]}, **kw))

    def make_clean(self):
        """확정을 막는 것을 걷어 낸 추출 결과로 바꾼다(모양은 그대로)."""
        path = cf.extraction_path(self.name)
        with open(path, encoding="utf-8") as fh:
            ex = json.load(fh)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(make_clean(ex), fh, ensure_ascii=False)

    def confirm_page(self):
        self.make_clean()
        self.assertTrue(self.sheet("compare")["ok"])
        r = self.sheet("confirm")
        self.assertTrue(r["ok"], r)
        return r


class SheetConfirmationTest(Base):
    def test_status_is_the_engines_answer_and_reading_writes_nothing(self):
        before = os.listdir(paths.output_root("extract"))
        st = self.status()
        self.assertTrue(st["available"], st)
        self.assertIn(st["state"], ("open", "ready", "confirmed"))
        self.assertEqual(st["ver"], st["fingerprint"])
        engine_answer = cf.sheet_confirmation(self.name)
        self.assertEqual((st["state"], st["counts"], st["rev"], st["read_method"]), (engine_answer["state"], engine_answer["counts"], engine_answer["rev"], engine_answer["read_method"]),
                         "화면은 조건을 다시 세지 않고 엔진의 값을 그대로 낸다")
        self.assertEqual(st["unconfirmed_total"], len(engine_answer["unconfirmed"]))
        self.assertEqual(os.listdir(paths.output_root("extract")), before)
        self.assertFalse(os.path.exists(cf.store_path(self.name)), "읽기는 확정 기록을 만들지 않는다")
        self.assertIsNone(api.ReadApi(self.engine).read(["sheetconf", "graph-없음"], {}))

    def test_confirm_is_refused_with_the_engines_reasons_while_conditions_are_open(self):
        st = self.status()
        self.assertEqual(st["state"], "open", "표본 추출에는 미확인이 있다")
        r = self.sheet("compare")
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"), r)
        self.assertIn("미확인", r["error"]["message"])
        r = self.sheet("confirm")
        self.assertFalse(r["ok"])
        self.assertFalse(os.path.exists(cf.store_path(self.name)), "거절하면 아무것도 쓰지 않는다")
        self.assertEqual(self.status()["state"], "open")

    def test_compare_then_confirm_then_unconfirm_with_the_reviewer_name(self):
        self.make_clean()
        self.assertEqual(self.status()["state"], "ready")
        self.assertFalse(self.sheet("confirm")["ok"], "견줌 없이는 확정하지 않는다")
        r = self.sheet("compare", mode="side_by_side")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["status"]["compared"]["by"], "검토자A")
        r = self.sheet("confirm")
        self.assertTrue(r["ok"], r)
        st = r["data"]["status"]
        self.assertEqual((st["state"], st["confirmed"]["by"], st["default_view"]), ("confirmed", "검토자A", "clean"))
        self.assertTrue(self.events.changes("sheetconf") and self.events.changes("drawings"))
        r = self.sheet("unconfirm", reason="다시 본다")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["status"]["state"], "ready")
        self.assertIsNone(r["data"]["status"]["confirmed"])

    def test_stale_ver_or_rev_and_missing_reviewer_write_nothing(self):
        self.make_clean()
        old = self.status()
        self.assertTrue(self.sheet("compare")["ok"])
        r = self.call("sheet.confirm", {"graph_id": self.gid, "ver": old["ver"], "rev": old["rev"]})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), r)
        self.engine.settings["reviewer_name"] = ""
        r = self.sheet("confirm")
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "bad_args"))
        r = self.call("sheet.confirm", dict({"graph_id": self.gid, "ver": self.status()["ver"], "rev": self.status()["rev"]}, by="가짜"))
        self.assertEqual(r["error"]["code"], "bad_args", "by는 웹 인자가 아니다")

    def test_a_change_to_the_sheet_releases_the_confirmation(self):
        self.confirm_page()
        path = cf.extraction_path(self.name)
        with open(path, encoding="utf-8") as fh:
            ex = json.load(fh)
        ex["nodes"][0]["tag"] = "바뀐-태그"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)
        st = self.status()
        self.assertEqual(st["state"], "ready", "세 파일 중 하나가 바뀌면 확정이 풀린다")
        self.assertTrue(st["released"])

    def test_commands_take_ids_only_and_are_project_bound(self):
        for name in ("sheet.compare", "sheet.confirm", "sheet.unconfirm", "dexpi.export"):
            cmd = api.COMMANDS[name]
            for key in cmd.spec:
                self.assertNotRegex(key, r"path|file|dir|folder|url", "%s의 인자 %s" % (name, key))
            r = self.engine.dispatch(name, {}, project="NOT-THIS", via_web=True)
            self.assertEqual((r["ok"], r["error"]["code"]), (False, "wrong_project"), name)


class DexpiExportTest(Base):
    def test_no_confirmed_page_gives_guidance_and_writes_nothing(self):
        rows = self.read("dexpi")
        self.assertFalse(rows["any"])
        self.assertEqual([r["state"] for r in rows["drawings"]], ["open"])
        self.assertTrue(rows["drawings"][0]["why"])
        r = self.call("dexpi.export", {"graph_ids": [self.gid]})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"), r)
        self.assertIn("확정된 쪽이 하나도 없어", r["error"]["message"])
        self.assertEqual(os.listdir(self.out), [])

    def test_only_the_confirmed_page_is_exported_and_the_summary_lists_the_rest(self):
        self.confirm_page()
        self.mark_number_confirmed()
        r = self.call("dexpi.export", {"graph_ids": [self.gid]})
        self.assertTrue(r["ok"], r)
        d = r["data"]
        self.assertFalse(d["cancelled"])
        self.assertEqual([x["graph_id"] for x in d["drawings"]], [self.gid])
        self.assertIn(self.name + ".dexpi.xml", d["drawings"][0]["files"])
        self.assertTrue(all(os.sep not in f and "/" not in f for f in d["drawings"][0]["files"]), "웹에는 파일 이름만")
        self.assertEqual(d["not_exported"], [])
        self.assertTrue(os.path.isfile(os.path.join(self.out, self.name + ".dexpi.xml")))
        self.assertTrue(os.path.isfile(os.path.join(self.out, "manifest.json")))
        self.assertNotIn(self.tmp, json.dumps(d, ensure_ascii=False), "저장 경로를 웹에 돌려주지 않는다")

    def mark_number_confirmed(self):
        path = cf.extraction_path(self.name)
        with open(path, encoding="utf-8") as fh:
            ex = json.load(fh)
        ex.setdefault("drawing", {})["identification_basis"] = "registration_confirmed"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)
        # 추출 결과가 바뀌면 확정이 풀리므로 다시 견주고 확정한다
        self.assertTrue(self.sheet("compare")["ok"])
        self.assertTrue(self.sheet("confirm")["ok"])

    def test_overwriting_existing_files_asks_and_a_refusal_writes_nothing(self):
        self.confirm_page()
        self.mark_number_confirmed()
        self.assertTrue(self.call("dexpi.export", {"graph_ids": [self.gid]})["ok"])
        self.asked.clear()
        marker = os.path.join(self.out, self.name + ".dexpi.xml")
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("<keep/>")
        self.answer = False
        r = self.call("dexpi.export", {"graph_ids": [self.gid]})
        self.assertTrue(r["ok"] and r["data"]["cancelled"] and r["data"]["overwrite_refused"], r)
        self.assertEqual(len(self.asked), 1)
        self.assertIn(self.name + ".dexpi.xml", self.asked[0])
        with open(marker, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "<keep/>", "거절하면 덮어쓰지 않는다")
        self.answer = True
        r = self.call("dexpi.export", {"graph_ids": [self.gid]})
        self.assertTrue(r["ok"] and not r["data"]["cancelled"], r)
        with open(marker, encoding="utf-8") as fh:
            self.assertNotEqual(fh.read(), "<keep/>")

    def test_cancelling_the_folder_dialog_writes_nothing(self):
        self.confirm_page()
        self.mark_number_confirmed()
        self.engine.hooks["save_dir"] = lambda kind: None
        r = self.call("dexpi.export", {"graph_ids": [self.gid]})
        self.assertEqual(r["data"], {"cancelled": True})
        self.assertEqual(os.listdir(self.out), [])

    def test_unknown_graph_id_and_no_dialog_are_refused(self):
        self.assertEqual(self.call("dexpi.export", {"graph_ids": ["graph-없음"]})["error"]["code"], "not_found")
        self.confirm_page()
        self.mark_number_confirmed()
        del self.engine.hooks["save_dir"]
        self.assertFalse(self.call("dexpi.export", {"graph_ids": [self.gid]})["ok"])


class DexpiImportTest(Base):
    FIXTURE = os.path.join(REPO, "tests", "fixtures", "dexpi", "small-pid-dexpi2.xml")

    def test_a_dexpi_xml_registers_through_the_engines_format_check_and_is_extracted(self):
        from hazop.shell import register_flow
        self.assertIn(".xml", api.REGISTRABLE_EXT)
        lines = []
        out = register_flow.register_and_extract(self.engine, self.FIXTURE, lambda text, done=None, total=None: lines.append(text))
        self.assertEqual(out["outcome"] in ("registered", "created", "new", "unchanged", "same") or bool(out["material_id"]), True, out)
        self.assertGreaterEqual(out["pages"], 1)

    def test_an_unreadable_xml_shows_the_engines_reasons_not_a_generic_failure(self):
        from hazop.shell import register_flow
        bad = os.path.join(self.tmp, "bad.xml")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "x">]><x>&e;</x>')
        with self.assertRaises(RuntimeError) as cm:
            register_flow.register_and_extract(self.engine, bad, lambda *a, **k: None)
        text = str(cm.exception)
        self.assertIn("등록하지 못함", text)
        self.assertNotIn("failed", text)
        self.assertTrue(len(text) > len("등록하지 못함: ") + 4, text)

    def test_the_drop_and_pick_paths_accept_xml_and_reject_other_files(self):
        e = self.engine
        junk = os.path.join(self.tmp, "x.exe")
        open(junk, "w").close()
        with self.assertRaises(api.CommandError):
            e.add_files([junk])
        e._run_jobs = lambda job_id, fn: None
        r = e.add_files([self.FIXTURE])
        self.assertEqual(len(r["jobs"]), 1)


if __name__ == "__main__":
    unittest.main()
