"""도면 쪽 확정 칩·카드·견주기 화면과 DEXPI 내보내기·가져오기의 통합 시험(실제 새 화면 창 + 실제 엔진). 실행: python -m unittest tests.test_shell_drawings_flow

SNP 가상 도면에서: 칩이 남은 조건을 보이고 -> 견주기 화면을 열어 원본에 남은 것을 끝까지 넘겨 본 뒤에만 '견줌 완료'가 켜지고 -> 확정 -> DEXPI 내보내기
(저장 폴더는 창이 묻는 자리를 시험이 대신 꽂고, 작업 스레드에서 도는 내보내기가 그 질문을 화면 스레드로 넘기는지 본다) -> 그 파일을 새 프로젝트에 가져오기.
"""

import json
import os
import shutil
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.extract import confirmation as cf  # noqa: E402
from tests.test_sheet_confirmation import make_clean  # noqa: E402

pump, wait_for = W.pump, W.wait_for
tearDownModule = W.shell_teardown


class SheetConfirmFlowTest(W.ShellBase):
    def setUp(self):
        self.gid = None

    def locate(self, win, key="101"):
        """도면을 찾고 시험이 끝나면 추출 결과·확정 기록을 되돌리게 해 둔다(아직 열지 않는다)."""
        self.gid = [g for g in win.engine.graph_names() if key in g][0]
        self.name = win.engine.graph_names()[self.gid]
        path = cf.extraction_path(self.name)
        with open(path, encoding="utf-8") as fh:
            original = fh.read()
        name = self.name
        self.addCleanup(self.restore, path, original)
        self.addCleanup(self.remove_record, cf.store_path(name))
        return path

    @staticmethod
    def restore(path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    @staticmethod
    def remove_record(path):
        """확정 기록을 지운다. 창이 닫히는 중이면 Windows가 잠시 파일을 붙들고 있어 몇 번 다시 해 본다."""
        for _ in range(30):
            try:
                if os.path.exists(path):
                    os.remove(path)
                return
            except PermissionError:
                pump(0.1)

    def open_sheet(self, win, gid=None):
        gid = gid or self.gid
        self.js(win, "window.__hz.store.set({sheet: %s, panel: null})" % json.dumps(gid))
        win.engine.dispatch("sheet.open", {"graph_id": gid})
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.confbar .chip') !== null") is True, 20), "쪽 확정 칩이 없음")
        pump(0.8)

    def chip(self, win):
        return self.js(win, "document.querySelector('.confbar .chip').textContent.trim()")

    def make_clean(self, path, leftovers=()):
        with open(path, encoding="utf-8") as fh:
            ex = json.load(fh)
        ex.setdefault("drawing", {})["identification_basis"] = "registration_confirmed"
        ex = make_clean(ex)
        if leftovers:
            ex["unclassified"] = [{"local_id": "u%d" % i, "label_text": t, "bbox": box} for i, (t, box) in enumerate(leftovers)]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)

    def btn(self, label):
        return "document.querySelector(\"button[aria-label='%s']\")" % label

    def enabled(self, win, label):
        return self.js(win, "(() => { const b = %s; return !!b && !b.disabled; })()" % self.btn(label))

    def open_compare(self, win):
        self.assertTrue(self.click(win, ".confbar .chip"))
        self.assertTrue(wait_for(lambda: self.enabled(win, "견주기 화면 열기") is True, 10), self.text(win)[-300:])
        self.assertTrue(self.click(win, "button[aria-label='견주기 화면 열기']"))
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.cmpcard') !== null") is True, 10), "견주기 화면이 열리지 않음")
        self.assertTrue(wait_for(lambda: "원본에 남은" in self.text(win) or "남은 것이 없습니다" in self.text(win), 15), self.text(win)[-300:])

    def test_chip_shows_the_remaining_conditions_and_the_buttons_explain_why_they_are_off(self):
        win = self.window()
        self.locate(win)
        self.open_sheet(win)
        self.assertTrue(wait_for(lambda: "확정 조건" in self.chip(win), 10), self.chip(win))
        self.assertTrue(self.click(win, ".confbar .chip"))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.confcard').length") or 0) == 1, 10))
        text = self.text(win)
        self.assertIn("미확인", text)
        self.assertIn("원본에 남은 것", text)
        for label in ("견주기 화면 열기", "이 쪽 확정"):
            self.assertEqual(self.js(win, "%s.disabled" % self.btn(label)), True, label)
        self.assertIn("남은 조건을 모두 채워야 합니다", text)
        self.assertEqual(self.js(win, "document.querySelector('.confcard input[type=checkbox]') === null"), True, "체크는 견주기 화면에만 있다")
        self.assertFalse(os.path.exists(cf.store_path(self.name)), "누르기만으로는 아무것도 쓰지 않는다")

    def test_confirm_flow_goes_through_the_compare_screen_then_cancel(self):
        win = self.window()
        path = self.locate(win)
        self.make_clean(path)
        self.open_sheet(win)
        self.open_compare(win)
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.cmp-pane svg image') !== null") is True, 15), "왼쪽 칸에 원본 그림이 있어야 한다")
        self.assertIsNone(cf.sheet_confirmation(self.name)["compared"], "화면을 열기만 해서는 견줌이 기록되지 않는다")
        self.assertTrue(wait_for(lambda: self.js(win, "!document.querySelector('.cmpcard input[type=checkbox]').disabled") is True, 15), "남은 것이 없으면 체크를 켤 수 있다")
        self.assertEqual(self.js(win, "%s.disabled" % self.btn("견줌 완료")), True, "체크 전에는 막힘")
        self.assertTrue(self.click(win, ".cmpcard input[type=checkbox]"))
        pump(0.3)
        self.assertTrue(self.click(win, "button[aria-label='견줌 완료']"))
        self.assertTrue(wait_for(lambda: "확정만 남음" in self.chip(win), 10), self.chip(win))
        self.assertEqual(cf.sheet_confirmation(self.name)["compared"]["mode"], "side_by_side", "사람이 본 방식 한 가지만 적는다")
        self.assertEqual(self.js(win, "document.querySelector('.cmpcard') === null"), True, "견줌을 마치면 견주기 화면이 닫힌다")
        self.assertTrue(self.click(win, ".confbar .chip"))
        self.assertTrue(wait_for(lambda: self.enabled(win, "이 쪽 확정") is True, 10))
        self.assertTrue(self.click(win, "button[aria-label='이 쪽 확정']"))
        self.assertTrue(wait_for(lambda: "쪽 확정됨" in self.chip(win), 10), self.chip(win))
        self.assertEqual(cf.sheet_confirmation(self.name)["confirmed"]["by"], "검토자A", "확정자는 설정의 검토자 이름")
        self.assertTrue(self.click(win, "button[aria-label='확정 취소']"))
        self.assertTrue(wait_for(lambda: "쪽 확정됨" not in self.chip(win), 10), self.chip(win))
        self.assertIsNone(cf.sheet_confirmation(self.name)["confirmed"])

    def test_the_compare_screen_needs_every_leftover_stepped_through_and_records_the_mode_in_use(self):
        win = self.window()
        path = self.locate(win)
        self.make_clean(path, leftovers=[("가", [100, 100, 30, 20]), ("나", [300, 300, 30, 20])])
        self.assertEqual(cf.sheet_confirmation(self.name)["leftovers"]["total"], 2)
        self.open_sheet(win)
        self.open_compare(win)
        self.assertTrue(wait_for(lambda: "1 / 2" in self.text(win), 15), self.text(win)[-300:])
        self.assertEqual(self.js(win, "document.querySelector('.cmpcard input[type=checkbox]').disabled"), True, "남은 것을 다 보기 전에는 체크가 막힘")
        self.assertIn("끝까지 넘겨 보아야", self.text(win))
        self.assertTrue(self.click(win, "button[aria-label='다음 남은 것']"))
        self.assertTrue(wait_for(lambda: "2 / 2" in self.text(win), 10))
        self.assertTrue(wait_for(lambda: self.js(win, "!document.querySelector('.cmpcard input[type=checkbox]').disabled") is True, 10), "끝까지 보면 체크가 켜진다")
        self.assertTrue(self.click(win, ".cmp-mode button", 1))      # 방식을 바꿔 겹쳐 본다
        pump(0.3)
        self.assertEqual(self.js(win, "document.querySelector('.cmp-pane') === null"), True, "겹쳐 보기에는 왼쪽 칸이 없다")
        self.assertTrue(self.click(win, ".cmpcard input[type=checkbox]"))
        self.assertTrue(self.click(win, "button[aria-label='견줌 완료']"))
        self.assertTrue(wait_for(lambda: cf.sheet_confirmation(self.name)["compared"] is not None, 10))
        self.assertEqual(cf.sheet_confirmation(self.name)["compared"]["mode"], "overlay")

    def test_the_agreement_is_per_page_and_switching_pages_closes_the_compare_screen(self):
        win = self.window()
        path_a = self.locate(win, "101")
        self.make_clean(path_a)
        gid_a, name_a = self.gid, self.name
        path_b = self.locate(win, "102")
        self.make_clean(path_b)
        gid_b, name_b = self.gid, self.name
        self.gid, self.name = gid_a, name_a
        self.open_sheet(win, gid_a)
        self.open_compare(win)
        self.assertTrue(wait_for(lambda: self.js(win, "!document.querySelector('.cmpcard input[type=checkbox]').disabled") is True, 15))
        self.assertTrue(self.click(win, ".cmpcard input[type=checkbox]"))
        pump(0.3)
        self.js(win, "window.__hz.store.set({sheet: %s})" % json.dumps(gid_b))      # 견주지 않고 B 쪽으로 바꿈
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.cmpcard') === null") is True, 10), "쪽을 바꾸면 견주기 화면이 닫힌다")
        pump(0.8)
        self.assertIsNone(cf.sheet_confirmation(name_b)["compared"], "A에서 켠 체크가 B에 견줌을 남기지 않는다")
        self.assertIsNone(cf.sheet_confirmation(name_a)["compared"])
        self.assertTrue(self.click(win, ".confbar .chip"))
        self.assertTrue(wait_for(lambda: self.enabled(win, "견주기 화면 열기") is True, 10), self.text(win)[-300:])
        self.assertTrue(self.click(win, "button[aria-label='견주기 화면 열기']"))
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.cmpcard input[type=checkbox]') !== null") is True, 10))
        self.assertEqual(self.js(win, "document.querySelector('.cmpcard input[type=checkbox]').checked"), False, "B의 견주기 화면은 체크가 꺼진 채 시작한다")

    def test_a_broken_confirmation_record_shows_its_reason_and_a_way_to_start_over(self):
        win = self.window()
        path = self.locate(win)
        self.make_clean(path)
        sp = cf.store_path(self.name)
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write("{깨진 json")
        self.open_sheet(win)
        self.assertTrue(wait_for(lambda: "확정 기록 깨짐" in self.chip(win), 10), self.chip(win))
        self.assertTrue(self.click(win, ".confbar .chip"))
        self.assertTrue(wait_for(lambda: "확정 기록을 읽을 수 없습니다" in self.text(win), 10), self.text(win)[-300:])
        self.assertEqual(self.js(win, "%s.disabled" % self.btn("견주기 화면 열기")), True)
        self.assertEqual(self.js(win, "%s.disabled" % self.btn("이 쪽 확정")), True)
        self.assertTrue(self.click(win, "button[aria-label='확정 해제']"))
        self.assertTrue(wait_for(lambda: "확정 기록 깨짐" not in self.chip(win), 10), self.chip(win))
        self.assertFalse(cf.sheet_confirmation(self.name).get("record_error"))

    def test_dexpi_card_guides_without_a_confirmed_page_then_exports_and_imports(self):
        win = self.window()
        path = self.locate(win)
        self.open_sheet(win)
        self.js(win, "window.__hz.store.set({panel: 'drawings'})")
        self.assertTrue(wait_for(lambda: "DEXPI로 내보내기" in self.text(win), 10))
        self.assertTrue(wait_for(lambda: "확정된 쪽이 하나도 없어 내보낼 수 없습니다" in self.text(win), 10), self.text(win)[-400:])
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='확정된 쪽 DEXPI로 내보내기']\") === null"), True, "단추 대신 안내")
        # 확정(엔진 명령으로: 견주기 화면의 방식은 위 시험이 본다)
        self.make_clean(path)
        st = cf.sheet_confirmation(self.name)
        self.assertTrue(win.engine.dispatch("sheet.compare", {"graph_id": self.gid, "ver": st["fingerprint"], "rev": st["rev"]})["ok"])
        st = cf.sheet_confirmation(self.name)
        self.assertTrue(win.engine.dispatch("sheet.confirm", {"graph_id": self.gid, "ver": st["fingerprint"], "rev": st["rev"]})["ok"])
        out = os.path.join(self.tmp, "dexpi-out")
        os.makedirs(out, exist_ok=True)
        asked = []
        win._save_dir = lambda kind: (asked.append(threading.current_thread()), out)[1]      # 창이 묻는 자리. 내보내기는 작업 스레드에서 도니 화면 스레드로 넘어와야 한다
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector(\"button[aria-label='확정된 쪽 DEXPI로 내보내기']\") !== null") is True, 15), self.text(win)[-400:])
        self.assertTrue(self.click(win, "button[aria-label='확정된 쪽 DEXPI로 내보내기']"))
        self.assertTrue(wait_for(lambda: "쪽을 내보냈습니다" in self.text(win), 30), self.text(win)[-500:])
        self.assertEqual(asked, [threading.main_thread()], "저장 폴더는 화면 스레드에서 물었다")
        xml = os.path.join(out, self.name + ".dexpi.xml")
        self.assertTrue(os.path.isfile(xml))
        self.assertNotIn(self.tmp, self.text(win), "웹에는 경로를 보이지 않는다")
        # 그 파일을 새 프로젝트에 가져온다(다른 시험의 도면 목록에 남지 않게 가져온 폴더는 끝나면 지운다)
        for root in (paths.output_root("extract"), paths.output_root("graph")):
            self.addCleanup(lambda root=root: [shutil.rmtree(os.path.join(root, d), True) for d in os.listdir(root) if d.startswith("DEXPI-NEW__")])
        self.switch_project(win, "DEXPI-NEW")
        win.drop_files([xml])
        self.assertTrue(win.engine.wait_jobs(60))
        self.assertTrue(wait_for(lambda: any(v.startswith("DEXPI-NEW__") for v in win.engine.graph_names().values()), 20),
                        "가져온 도면이 새 프로젝트 목록에 들어온다: %s" % (win.engine.graph_names(),))
        done = [j for j in win.engine._jobs.values() if j["label"].endswith(".dexpi.xml")]
        self.assertTrue(done and done[-1]["state"] == "done", done)


class AiEstimateFlowTest(W.ShellBase):
    def test_turning_ai_review_on_shows_the_expected_calls_per_drawing(self):
        win = self.window()
        self.js(win, "window.__hz.store.set({panel: 'drawings'})")
        pump(0.5)
        self.assertNotIn("예상 호출", self.text(win), "꺼져 있으면 예상 호출 수를 읽지 않는다")
        self.assertTrue(win.engine.dispatch("extract.set_ai_review", {"enabled": True, "cap": 20}, project=win.engine.project_id(), via_web=True)["ok"])
        self.js(win, "window.__hz.store.set((s) => ({app: Object.assign({}, s.app, {ai_review: true, ai_review_cap: 20})}))")
        self.assertTrue(wait_for(lambda: "예상 호출" in self.text(win), 15), self.text(win)[-300:])
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.row .chip.ai').length") or 0) >= 1, 10), "도면 행마다 호출 수 칩")
        win.engine.dispatch("extract.set_ai_review", {"enabled": False}, project=win.engine.project_id(), via_web=True)


class TitleblockLinkFlowTest(W.ShellBase):
    def test_a_drawing_row_opens_the_titleblock_panel_for_that_sheet(self):
        win = self.window()
        self.js(win, "window.__hz.store.set({panel: 'drawings'})")
        pump(0.5)
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll(\"button[aria-label$=' 표제란']\").length") or 0) >= 2, 10), "도면 행마다 표제란 단추")
        self.assertTrue(self.click(win, "button[aria-label$=' 표제란']"))
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().panel") == "titleblock", 10))
        self.assertTrue(wait_for(lambda: "표제란" in self.text(win), 10))


class ItemBubbleFlowTest(W.ShellBase):
    def test_the_component_card_shows_the_korean_kind_name_first_and_the_english_one_small(self):
        win = self.window()
        gid = self.jsj(win, "window.__hz.store.get().drawings.drawings")[0]["graph_id"]
        from hazop.shell import api
        item = json.loads(api.ReadApi(win.engine).read(["sheet", gid], {}).body.decode("utf-8"))["items"][0]["id"]      # 고치기가 읽을 수 있는 실제 구성요소
        bubble = {"sheet": gid, "id": item, "tag": "RC-V001", "kind": "control_valve", "kind_label": "제어 밸브", "rect": {"x": 200, "y": 200, "w": 20, "h": 20}}
        self.js(win, "window.__hz.store.set({sheet: %s, panel: null, bubble: %s})" % (json.dumps(gid), json.dumps(bubble)))
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.bubble') !== null") is True, 15))
        text = self.js(win, "document.querySelector('.bubble div').textContent")
        self.assertIn("RC-V001", text)
        self.assertIn("제어 밸브", text)
        self.assertIn("control_valve", text)
        self.assertLess(text.index("제어 밸브"), text.index("control_valve"), "한글이 먼저")
        self.js(win, "window.__hz.store.set({bubble: %s})" % json.dumps(dict(bubble, kind_label=None)))      # 사전에 없는 종류는 영문만
        self.assertTrue(wait_for(lambda: "제어 밸브" not in (self.js(win, "document.querySelector('.bubble div').textContent") or ""), 10))
        self.assertIn("control_valve", self.js(win, "document.querySelector('.bubble div').textContent"))
        self.assertTrue(self.click(win, ".bubble button[aria-label='고치기']"), "말풍선에서 바로 고치기로 간다")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.bubble') === null") is True, 10), "말풍선은 닫히고 고치기 카드로 넘어간다(카드 모양은 s-viewer의 시험이 본다)")
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [], "웹 콘솔 오류 없음")


if __name__ == "__main__":
    unittest.main()
