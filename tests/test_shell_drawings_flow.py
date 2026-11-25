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
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.confbar .chip:not(.review)') !== null") is True, 20), "쪽 확정 칩이 없음")
        pump(0.8)

    def chip(self, win):
        return self.js(win, "document.querySelector('.confbar .chip:not(.review)').textContent.trim()")

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
        self.assertTrue(self.click(win, ".confbar .chip:not(.review)"))
        self.assertTrue(wait_for(lambda: self.enabled(win, "원본과 견주고 확정") is True, 10), self.text(win)[-300:])
        self.assertTrue(self.click(win, "button[aria-label='원본과 견주고 확정']"))
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.cmpcard') !== null") is True, 10), "견주기 화면이 열리지 않음")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.cmpcard .cmp-step, .cmpcard [role=status]') !== null") is True, 15), self.text(win)[-300:])      # 남은 것 넘기기 또는 '남은 것이 없습니다' 줄

    def test_chip_shows_the_remaining_conditions_and_the_buttons_explain_why_they_are_off(self):
        win = self.window()
        self.locate(win)
        self.open_sheet(win)
        self.assertTrue(wait_for(lambda: "확정 조건" in self.chip(win), 10), self.chip(win))
        self.assertTrue(self.click(win, ".confbar .chip:not(.review)"))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.confcard').length") or 0) == 1, 10))
        text = self.text(win)
        self.assertIn("미확인", text)
        self.assertIn("원본에 남은 것", text)
        self.assertEqual(self.js(win, "%s.disabled" % self.btn("원본과 견주고 확정")), True)
        self.assertEqual(self.js(win, "%s === null" % self.btn("이 쪽 확정")), True, "견주기 전에는 확정 단추 대신 '견주고 확정' 하나")
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
        self.assertEqual(self.js(win, "%s.disabled" % self.btn("견줌만 기록")), True, "체크 전에는 막힘")
        self.assertTrue(self.click(win, ".cmpcard input[type=checkbox]"))
        pump(0.3)
        self.assertTrue(self.click(win, "button[aria-label='견줌만 기록']"))
        self.assertTrue(wait_for(lambda: "확정만 남음" in self.chip(win), 10), self.chip(win))
        self.assertEqual(cf.sheet_confirmation(self.name)["compared"]["mode"], "side_by_side", "사람이 본 방식 한 가지만 적는다")
        self.assertEqual(self.js(win, "document.querySelector('.cmpcard') === null"), True, "견줌을 마치면 견주기 화면이 닫힌다")
        self.assertTrue(self.click(win, ".confbar .chip:not(.review)"))
        self.assertTrue(wait_for(lambda: self.enabled(win, "이 쪽 확정") is True, 10))
        self.assertTrue(self.click(win, "button[aria-label='이 쪽 확정']"))
        self.assertTrue(wait_for(lambda: "쪽 확정됨" in self.chip(win), 10), self.chip(win))
        self.assertEqual(cf.sheet_confirmation(self.name)["confirmed"]["by"], "검토자A", "확정자는 설정의 검토자 이름")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.confcard').length") or 0) == 0, 10), "확정하면 카드가 저절로 닫힌다(U8)")
        self.assertTrue(self.click(win, ".confbar .chip:not(.review)"))
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector(\"button[aria-label='확정 취소']\") !== null") is True, 10))
        self.assertTrue(self.click(win, "button[aria-label='확정 취소']"))
        self.assertTrue(wait_for(lambda: "쪽 확정됨" not in self.chip(win), 10), self.chip(win))
        self.assertIsNone(cf.sheet_confirmation(self.name)["confirmed"])

    def test_compare_and_confirm_is_one_flow_and_closes_itself(self):
        """U8(쪽 확정 8 → 3클릭): '다음에 할 일'의 쪽 확정 단추(openNext)가 조건이 찬 쪽에서는 견주기 화면을 바로 열고, 체크 하나와
        '견줌 기록하고 확정' 한 번으로 견줌 기록·확정을 함께 남긴 뒤 견주기 화면과 카드가 저절로 닫힌다. 견줌을 건너뛰는 길은 없다."""
        win = self.window()
        path = self.locate(win)
        self.make_clean(path)
        self.open_sheet(win)
        self.js(win, "window.__hz.next.set({ running: null, open: false, items: [{ kind: 'sheet_confirm', count: 1, text: '원본과 견주어 확정할 쪽이 1장 있습니다', detail: null,"
                     " action: { label: '쪽 확정', go: 'panel:drawings#sheetconf', target: %s }, tone: '' }] })" % json.dumps(self.gid))
        self.js(win, "window.__hz.go({ go: 'panel:drawings#sheetconf', target: %s })" % json.dumps(self.gid))      # '다음에 할 일' 줄은 화면에서 내렸다: 그 단추가 부르던 길을 바로 부른다
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.cmpcard') !== null") is True, 15), "조건이 찬 쪽은 견주기 화면이 바로 열린다")
        self.assertTrue(wait_for(lambda: self.js(win, "!document.querySelector('.cmpcard input[type=checkbox]').disabled") is True, 15))
        self.assertEqual(self.js(win, "%s.disabled" % self.btn("견줌 기록하고 이 쪽 확정")), True, "체크 전에는 막힘(견줌을 건너뛰지 않는다)")
        self.assertTrue(self.click(win, ".cmpcard input[type=checkbox]"))                       # 클릭 2
        pump(0.3)
        self.assertTrue(self.click(win, "button[aria-label='견줌 기록하고 이 쪽 확정']"))         # 클릭 3
        self.assertTrue(wait_for(lambda: "쪽 확정됨" in self.chip(win), 15), self.chip(win))
        rec = cf.sheet_confirmation(self.name)
        self.assertEqual((rec["compared"]["mode"], rec["confirmed"]["by"]), ("side_by_side", "검토자A"), "견줌과 확정이 모두 기록됨")
        self.assertEqual(self.js(win, "document.querySelector('.cmpcard') === null && document.querySelectorAll('.confcard').length === 0"), True,
                         "끝나면 견주기 화면과 쪽 확정 카드가 저절로 닫힌다")

    def test_the_card_shows_a_button_that_fixes_each_remaining_reason(self):
        """U8 막다른 칩: '확정 조건 n개 남음' 카드가 남은 까닭마다 푸는 단추(표제란 확정 등)를 보이고, 누르면 그 자리로 간다."""
        win = self.window()
        self.locate(win)
        self.open_sheet(win)
        self.assertTrue(self.click(win, ".confbar .chip:not(.review)"))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.confcard').length") or 0) == 1, 10))
        labels = self.js(win, "JSON.stringify([...document.querySelectorAll('.confcard .conf-list button')].map((b) => b.getAttribute('aria-label')))")
        self.assertTrue(labels and json.loads(labels), "남은 조건을 푸는 단추가 없음: %s" % self.text(win)[-300:])
        self.assertNotIn("registration_unknown", self.text(win))

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
        self.assertTrue(self.click(win, "button[aria-label='견줌만 기록']"))
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
        self.assertTrue(self.click(win, ".confbar .chip:not(.review)"))
        self.assertTrue(wait_for(lambda: self.enabled(win, "원본과 견주고 확정") is True, 10), self.text(win)[-300:])
        self.assertTrue(self.click(win, "button[aria-label='원본과 견주고 확정']"))
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
        self.assertTrue(self.click(win, ".confbar .chip:not(.review)"))
        self.assertTrue(wait_for(lambda: "확정 기록을 읽을 수 없습니다" in self.text(win), 10), self.text(win)[-300:])
        self.assertEqual(self.js(win, "%s.disabled" % self.btn("원본과 견주고 확정")), True)
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
    def test_the_drawings_panel_has_no_ai_review_settings_card(self):
        """화면 단순화(사용자 결정 2026-11-25): 도면 패널의 AI 검토 설정(켜고 끄기·호출 상한)은 화면에서 내린다. 엔진의 상한과 구독 제한은 그대로다."""
        win = self.window()
        self.js(win, "window.__hz.store.set({panel: 'drawings'})")
        pump(0.5)
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.drow').length") or 0) >= 2, 10))
        text = self.text(win)
        for word in ("추출 설정", "도면당 호출 상한", "예상 호출"):
            self.assertNotIn(word, text)
        self.assertEqual(self.js(win, "document.querySelectorAll('.ai-foot').length"), 0)


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


class ScanNoteFlowTest(W.ShellBase):
    def test_a_scanned_drawing_shows_one_note_line_with_dpi_and_the_resolution_advice_and_it_can_be_closed(self):
        from unittest import mock
        from hazop.shell import api
        win = self.window()
        gid = self.jsj(win, "window.__hz.store.get().drawings.drawings")[0]["graph_id"]
        self.js(win, "window.__hz.store.set({sheet: %s, panel: null})" % json.dumps(gid))
        pump(1.0)
        self.assertFalse(self.js(win, "document.querySelector('.scan-note') !== null"), "스캔이 아니면 알림줄이 없다")
        advice = "해상도가 낮아 300 dpi 이상으로 다시 스캔하세요"

        def scan_read(self_, graph_id):
            return api._json({"graph_id": graph_id, "scan": {"dpi": 200, "low_resolution": advice}})
        with mock.patch.object(api.ReadApi, "scan", scan_read):
            other = [g["graph_id"] for g in self.jsj(win, "window.__hz.store.get().drawings.drawings") if g["graph_id"] != gid][0]
            self.js(win, "window.__hz.store.set({sheet: %s, panel: null})" % json.dumps(other))
            self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.scan-note') !== null") is True, 15), self.text(win)[-300:])
            text = self.js(win, "document.querySelector('.scan-note').textContent")
            self.assertIn("스캔 도면 · 200 dpi · 자동으로 읽은 결과가 적고 미확인이 많습니다. AI 검토를 켜면 후보를 더 받을 수 있습니다.", text)
            self.assertIn(advice, text)
            self.assertTrue(self.click(win, ".scan-note button[aria-label='스캔 알림 닫기']"))
            self.assertTrue(wait_for(lambda: self.js(win, "document.querySelector('.scan-note') === null") is True, 10))
        self.assertEqual([c for c in win.view.page().console if c[0] >= 2], [], "웹 콘솔 오류 없음")


if __name__ == "__main__":
    unittest.main()
