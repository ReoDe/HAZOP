"""도면 쪽 확정 칩·카드와 DEXPI 내보내기·가져오기의 통합 시험(실제 새 화면 창 + 실제 엔진). 실행: python -m unittest tests.test_shell_drawings_flow

SNP 가상 도면에서: 칩이 남은 조건을 보이고 -> 조건을 채운 뒤 견주기·확정 -> DEXPI 내보내기(저장 폴더는 창이 묻는 자리를 시험이 대신 꽂음) -> 그 파일을 새 프로젝트에 가져오기.
"""

import json
import os
import shutil
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop.extract import confirmation as cf  # noqa: E402
from tests.test_sheet_confirmation import make_clean  # noqa: E402

pump, wait_for = W.pump, W.wait_for


class SheetConfirmFlowTest(W.ShellBase):
    def setUp(self):
        self.gid = None

    def open_sheet(self, win):
        self.gid = [g for g in win.engine.graph_names() if "101" in g][0]
        self.name = win.engine.graph_names()[self.gid]
        path = cf.extraction_path(self.name)
        with open(path, encoding="utf-8") as fh:
            self.original = fh.read()
        self.addCleanup(lambda: open(path, "w", encoding="utf-8").write(self.original))
        self.addCleanup(lambda: os.path.exists(cf.store_path(self.name)) and os.remove(cf.store_path(self.name)))
        self.js(win, "window.__hz.store.set({sheet: %s, panel: null})" % json.dumps(self.gid))
        win.engine.dispatch("sheet.open", {"graph_id": self.gid})
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.confbar .chip') !== null") is True, 20), "쪽 확정 칩이 없음")
        pump(0.8)
        return path

    def chip(self, win):
        return self.js(win, "document.querySelector('.confbar .chip').textContent.trim()")

    def make_clean(self, path):
        with open(path, encoding="utf-8") as fh:
            ex = json.load(fh)
        ex.setdefault("drawing", {})["identification_basis"] = "registration_confirmed"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(make_clean(ex), fh, ensure_ascii=False)

    def test_chip_shows_the_remaining_conditions_and_the_buttons_explain_why_they_are_off(self):
        win = self.window()
        self.open_sheet(win)
        self.assertTrue(wait_for(lambda: "확정 조건" in self.chip(win), 10), self.chip(win))
        self.assertTrue(self.click(win, ".confbar .chip"))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.confcard').length") or 0) == 1, 10))
        text = self.text(win)
        self.assertIn("미확인", text)
        self.assertIn("원본에 남은 것", text)
        for label in ("원본과 견주기", "이 쪽 확정"):
            self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='%s']\").disabled" % label), True, label)
        self.assertIn("남은 조건을 모두 채워야 합니다", text)
        self.assertFalse(os.path.exists(cf.store_path(self.name)), "누르기만으로는 아무것도 쓰지 않는다")

    def test_confirm_flow_then_cancel(self):
        win = self.window()
        path = self.open_sheet(win)
        self.make_clean(path)
        self.assertTrue(self.click(win, ".confbar .chip"))
        self.assertTrue(wait_for(lambda: "원본과 견줌 남음" in self.chip(win), 10), self.chip(win))
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='원본과 견주기']\").disabled"), True, "체크 상자를 켜기 전에는 막힘")
        self.assertTrue(self.click(win, ".confcard input[type=checkbox]"))
        pump(0.3)
        self.assertTrue(self.click(win, "button[aria-label='원본과 견주기']"))
        self.assertTrue(wait_for(lambda: "확정만 남음" in self.chip(win), 10), self.chip(win))
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='이 쪽 확정']\").disabled"), False)
        self.assertTrue(self.click(win, "button[aria-label='이 쪽 확정']"))
        self.assertTrue(wait_for(lambda: "쪽 확정됨" in self.chip(win), 10), self.chip(win))
        self.assertEqual(cf.sheet_confirmation(self.name)["confirmed"]["by"], "검토자A", "확정자는 설정의 검토자 이름")
        self.assertTrue(self.click(win, "button[aria-label='확정 취소']"))
        self.assertTrue(wait_for(lambda: "쪽 확정됨" not in self.chip(win), 10), self.chip(win))
        self.assertIsNone(cf.sheet_confirmation(self.name)["confirmed"])

    def test_dexpi_card_guides_without_a_confirmed_page_then_exports_and_imports(self):
        win = self.window()
        path = self.open_sheet(win)
        self.js(win, "window.__hz.store.set({panel: 'drawings'})")
        self.assertTrue(wait_for(lambda: "DEXPI로 내보내기" in self.text(win), 10))
        self.assertTrue(wait_for(lambda: "확정된 쪽이 하나도 없어 내보낼 수 없습니다" in self.text(win), 10), self.text(win)[-400:])
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='확정된 쪽 DEXPI로 내보내기']\") === null"), True, "단추 대신 안내")
        # 확정
        self.make_clean(path)
        st = cf.sheet_confirmation(self.name)
        self.assertTrue(win.engine.dispatch("sheet.compare", {"graph_id": self.gid, "ver": st["fingerprint"], "rev": st["rev"]})["ok"])
        st = cf.sheet_confirmation(self.name)
        self.assertTrue(win.engine.dispatch("sheet.confirm", {"graph_id": self.gid, "ver": st["fingerprint"], "rev": st["rev"]})["ok"])
        out = os.path.join(self.tmp, "dexpi-out")
        os.makedirs(out, exist_ok=True)
        win.engine.hooks["save_dir"] = lambda kind: out
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector(\"button[aria-label='확정된 쪽 DEXPI로 내보내기']\") !== null") is True, 15), self.text(win)[-400:])
        self.assertTrue(self.click(win, "button[aria-label='확정된 쪽 DEXPI로 내보내기']"))
        self.assertTrue(wait_for(lambda: "쪽을 내보냈습니다" in self.text(win), 20), self.text(win)[-500:])
        xml = os.path.join(out, self.name + ".dexpi.xml")
        self.assertTrue(os.path.isfile(xml))
        self.assertNotIn(self.tmp, self.text(win), "웹에는 경로를 보이지 않는다")
        # 그 파일을 새 프로젝트에 가져온다
        self.switch_project(win, "DEXPI-NEW")
        win.drop_files([xml])
        self.assertTrue(win.engine.wait_jobs(60))
        self.assertTrue(wait_for(lambda: any(v.startswith("DEXPI-NEW__") for v in win.engine.graph_names().values()), 20),
                        "가져온 도면이 새 프로젝트 목록에 들어온다: %s" % (win.engine.graph_names(),))
        done = [j for j in win.engine._jobs.values() if j["label"].endswith(".dexpi.xml")]
        self.assertTrue(done and done[-1]["state"] == "done", done)


if __name__ == "__main__":
    unittest.main()
