"""초기사건 패널의 통합 시험(실제 새 화면 창 + 실제 인계 묶음 계산·초기사건 저장). 실행: python -m unittest tests.test_shell_ie_flow

패널이 열리면 후보·완전성 대조·품질 경고가 보이고, 규칙 초안 만들기가 그룹을 만들며, 그룹 상세와 확정 조건이 보이고, 인계 묶음 내보내기가 저장 대화상자 훅을 통해 돈다.
"""

import copy
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop.ie import model  # noqa: E402
from hazop.ie import store as ie_store  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_ie_bundle import ie_sample  # noqa: E402
from tests.test_study_export import DEVS as XDEVS  # noqa: E402

pump, wait_for = W.pump, W.wait_for
tearDownModule = W.shell_teardown


class IePanelTest(W.ShellBase):
    def setUp(self):
        from hazop.app import project_ctx
        self.r, self.ns, self.pg = ie_sample()
        for p in (mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(XDEVS)),
                  mock.patch.object(W, "small_pg", lambda: self.pg)):
            p.start()
            self.addCleanup(p.stop)
        sn.save(self.ns)
        res.save(self.r, self.ns.get("project_id"))
        self.project = self.ns.get("project_id")
        path = ie_store.store_path(self.project)
        if os.path.exists(path):
            os.remove(path)

    def open_panel(self):
        win = self.window()
        self.switch_project(win, self.project)
        self.assertTrue(self.click(win, ".rail button", 3))
        self.assertTrue(wait_for(lambda: "묶이지 않은 후보" in self.text(win), 15), self.text(win)[-300:])
        return win

    def test_panel_shows_candidates_completeness_and_warnings(self):
        win = self.open_panel()
        text = self.text(win)
        self.assertIn("초기사건", text)
        self.assertIn("IEC-001", text)
        self.assertIn("그룹이 없습니다", text)
        self.assertTrue(self.click(win, "button[aria-label^='완전성 대조']"))
        self.assertTrue(wait_for(lambda: "주급수 완전 상실" in self.text(win), 10), self.text(win)[-300:])
        self.assertTrue(self.click(win, "button[aria-label^='품질 경고']"))
        self.assertTrue(wait_for(lambda: "작동 방식 미확인" in self.text(win), 10), self.text(win)[-300:])

    def test_suggest_makes_a_draft_group_and_its_detail_explains_why_it_cannot_be_confirmed(self):
        win = self.open_panel()
        self.assertTrue(self.click(win, "button[aria-label='규칙 초안 만들기']"))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "document.querySelector(\"[aria-label='그룹 목록'] .nrow-b\") !== null")), 15), self.text(win)[-300:])
        self.assertTrue(os.path.isfile(ie_store.store_path(self.project)))
        self.assertTrue(self.click(win, "[aria-label='그룹 목록'] .nrow-b"))
        self.assertTrue(wait_for(lambda: "확정할 수 없는 이유" in self.text(win), 10), self.text(win)[-400:])
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='그룹 확정']\").disabled"), True, "AI 초안 표제가 남아 확정 단추가 막힌다")
        self.assertIn("AI 초안", self.text(win))

    def test_export_bundle_uses_the_save_dialog_hook(self):
        win = self.open_panel()
        out = os.path.join(os.path.dirname(win.engine.settings_path), "ie-bundle.xlsx")
        win.engine.hooks["save_path"] = lambda kind, name: out
        self.assertTrue(self.click(win, "button[aria-label='초기사건 인계 묶음 내보내기']"))
        self.assertTrue(wait_for(lambda: os.path.isfile(out), 20))
        self.assertTrue(wait_for(lambda: "ie-bundle.xlsx" in self.text(win), 10))
        self.assertNotIn(os.path.dirname(out), self.text(win))

    def test_human_group_can_be_confirmed_from_the_panel(self):
        doc, fp = ie_store.load(self.project)
        doc = model.sync(doc, self.r, at="2026-11-13T01:00:00Z", node_set=self.ns)
        iec = model.iec_of(doc)[model.key_of(self.r["graph_id"], "c1")]
        doc, gid = model.create_group(doc, "주급수 상실", [iec], at="2026-11-13T01:00:00Z")
        ie_store.save(doc, expect=fp)
        win = self.open_panel()
        self.assertTrue(wait_for(lambda: gid in self.text(win), 10))
        self.assertTrue(self.click(win, "[aria-label='그룹 목록'] .nrow-b"))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "document.querySelector(\"button[aria-label='그룹 확정']\") !== null")), 10))
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='그룹 확정']\").disabled"), False)
        self.assertTrue(self.click(win, "button[aria-label='그룹 확정']"))
        self.assertTrue(wait_for(lambda: bool(ie_store.load(self.project)[0]["groups"][gid].get("confirmation")), 10))
        self.assertEqual(ie_store.load(self.project)[0]["groups"][gid]["confirmation"]["by"], "검토자A")
        self.assertTrue(wait_for(lambda: "확정 풀기" in self.text(win), 10))


    # ------------------------------------------------------------ A10 편집
    def type_into(self, win, selector, value):
        """입력칸에 글을 넣고 input 이벤트를 낸다(사람이 친 것과 같은 상태)."""
        import json as _j
        return self.js(win, "(() => { const e = document.querySelector(%s); if (!e) return false; e.value = %s; e.dispatchEvent(new Event('input', {bubbles: true}));"
                            " e.dispatchEvent(new Event('change', {bubbles: true})); return true; })()" % (_j.dumps(selector), _j.dumps(value)))

    def stored(self):
        return ie_store.load(self.project)[0]

    def idle(self, win, selector):
        """다시 읽기가 끝나 단추가 풀릴 때까지 기다린다(사람도 막힌 단추는 누르지 못한다)."""
        import json as _j
        return wait_for(lambda: self.js(win, "(() => { const b = document.querySelector(%s); return !!b && !b.disabled; })()" % _j.dumps(selector)) is True, 10)

    def test_pick_candidates_make_a_group_rename_it_and_delete_it_after_asking(self):
        win = self.open_panel()
        iec = next(c["candidate_id"] for c in self.read_unassigned(win))
        self.assertTrue(self.click(win, "input[aria-label='%s 고르기']" % iec))
        self.assertTrue(wait_for(lambda: "1개" in self.text(win), 10))
        self.assertTrue(self.type_into(win, "input[aria-label='새 그룹 이름']", "주급수 상실"))
        pump(0.2)
        self.assertTrue(self.click(win, "button[aria-label='새 그룹으로 묶기']"))
        self.assertTrue(wait_for(lambda: any(g["name"] == "주급수 상실" for g in self.stored()["groups"].values()), 10), self.text(win)[-300:])
        gid = next(g for g, v in self.stored()["groups"].items() if v["name"] == "주급수 상실")
        self.assertEqual(self.stored()["candidates"][iec]["group_id"], gid)
        self.assertTrue(wait_for(lambda: gid + " 상세" in (self.js(win, "[...document.querySelectorAll('.ndetail')].map(e => e.getAttribute('aria-label')).join()") or ""), 10))
        # 고치기
        self.assertTrue(self.click(win, "button[aria-label='그룹 고치기']"))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "!!document.querySelector(\"input[aria-label='그룹 이름']\")")), 10))
        self.type_into(win, "input[aria-label='그룹 이름']", "급수 완전 상실")
        self.type_into(win, "input[aria-label='정의']", "주급수가 모두 끊김")
        pump(0.2)
        self.assertTrue(self.click(win, ".ie-form button[aria-label='저장']"))
        self.assertTrue(wait_for(lambda: self.stored()["groups"][gid]["name"] == "급수 완전 상실", 10), self.text(win)[-300:])
        self.assertEqual(self.stored()["groups"][gid]["definition"], "주급수가 모두 끊김")
        # 지우기: 먼저 되묻고, 그만두면 그대로
        self.assertTrue(self.idle(win, "button[aria-label='그룹 동작 더 보기']"))
        self.assertTrue(self.click(win, "button[aria-label='그룹 동작 더 보기']"))
        self.assertTrue(self.idle(win, "button[aria-label='그룹 지우기']"))
        self.assertTrue(self.click(win, "button[aria-label='그룹 지우기']"))
        self.assertTrue(wait_for(lambda: "지울까요" in self.text(win), 10), self.text(win)[:2500])
        self.assertEqual(self.stored()["groups"][gid]["status"], "draft", "되묻는 동안에는 지우지 않는다")
        self.assertTrue(self.click(win, "button[aria-label='그만두기']"))
        pump(0.3)
        self.assertEqual(self.stored()["groups"][gid]["status"], "draft")
        self.assertTrue(self.idle(win, "button[aria-label='그룹 동작 더 보기']"))
        self.assertTrue(self.click(win, "button[aria-label='그룹 동작 더 보기']"))
        self.assertTrue(self.idle(win, "button[aria-label='그룹 지우기']"))
        self.assertTrue(self.click(win, "button[aria-label='그룹 지우기']"))
        self.assertTrue(wait_for(lambda: "지울까요" in self.text(win), 10))
        self.assertTrue(self.click(win, "button[aria-label='계속']"))
        self.assertTrue(wait_for(lambda: self.stored()["groups"][gid]["status"] == "deleted", 10), self.text(win)[-300:])
        self.assertIsNone(self.stored()["candidates"][iec]["group_id"])

    def read_unassigned(self, win):
        from hazop.shell import api_ie
        return api_ie.summary(win.engine)["unassigned"]

    def test_confirmed_group_edit_asks_and_coverage_is_judged_with_a_reason(self):
        doc, fp = ie_store.load(self.project)
        doc = model.sync(doc, self.r, at="2026-11-13T01:00:00Z", node_set=self.ns)
        iec = model.iec_of(doc)[model.key_of(self.r["graph_id"], "c1")]
        doc, gid = model.create_group(doc, "주급수 상실", [iec], at="2026-11-13T01:00:00Z")
        doc = model.confirm(doc, gid, self.r, "검토자A", at="2026-11-13T01:00:00Z", node_set=self.ns)
        ie_store.save(doc, expect=fp)
        win = self.open_panel()
        self.assertTrue(wait_for(lambda: gid in self.text(win), 10))
        self.assertTrue(self.click(win, "[aria-label='그룹 목록'] .nrow-b"))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "!!document.querySelector(\"button[aria-label='그룹 고치기']\")")), 10))
        self.assertTrue(self.click(win, "button[aria-label='그룹 고치기']"))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "!!document.querySelector(\"input[aria-label='그룹 이름']\")")), 10))
        self.type_into(win, "input[aria-label='그룹 이름']", "새 이름")
        pump(0.2)
        self.assertTrue(self.click(win, ".ie-form button[aria-label='저장']"))
        self.assertTrue(wait_for(lambda: "확정이 풀리는 그룹" in self.text(win), 10), self.text(win)[-300:])
        self.assertEqual(self.stored()["groups"][gid]["status"], "confirmed")
        self.assertTrue(self.click(win, "button[aria-label='계속']"))
        self.assertTrue(wait_for(lambda: self.stored()["groups"][gid]["name"] == "새 이름", 10), self.text(win)[-300:])
        self.assertEqual(self.stored()["groups"][gid]["status"], "draft")
        # 완전성 대조: 빈 범주 판정(사유 없이는 저장 단추가 막힘)
        self.assertTrue(self.idle(win, "button[aria-label='규칙 초안 만들기']"))
        self.assertTrue(self.click(win, "button[aria-label^='완전성 대조']"))
        code = self.js(win, "(() => { const b = [...document.querySelectorAll('.ie-cov button')].find(x => / 판정$/.test(x.getAttribute('aria-label'))); return b ? b.getAttribute('aria-label').replace(/ 판정$/, '') : null; })()")
        self.assertTrue(code, self.text(win)[-300:])
        self.assertTrue(self.click(win, "button[aria-label='%s 판정']" % code))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "!!document.querySelector(\"input[aria-label='%s 사유']\")" % code)), 10))
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='%s 판정 저장']\").disabled" % code), True)
        self.type_into(win, "input[aria-label='%s 사유']" % code, "이 계통 범위 밖")
        pump(0.2)
        self.assertTrue(self.click(win, "button[aria-label='%s 판정 저장']" % code))
        self.assertTrue(wait_for(lambda: (self.stored()["coverage"].get(code) or {}).get("reason") == "이 계통 범위 밖", 10), self.text(win)[-300:])
        self.assertEqual(self.stored()["coverage"][code]["by"], "검토자A")


    # ------------------------------------------------------------ P5: FMEA·MLD(설계 §8.2)
    def test_fmea_import_pick_and_approve_then_mld_branches(self):
        import json as _j
        import openpyxl
        from tests.test_ie_p5 import MLD
        for n in self.pg["nodes"]:
            if n["entity_id"] == "graph-SNP-M-102/E":
                n.update(kind="motor_operated_valve", category="valve")
        win = self.open_panel()
        tmp = os.path.dirname(win.engine.settings_path)
        wb = openpyxl.Workbook()
        wb.active.title = "FMEA"
        wb.active.append(["행 ID", "기기 태그", "고장모드", "고장모드 코드", "원인"])
        wb.active.append(["", "SNP-M-102-E", "열림 실패", "FTO", "구동기 고장"])
        wb.active.append(["", "NO-SUCH", "닫힘 실패", "FTC", "x"])
        xlsx = os.path.join(tmp, "fmea.xlsx")
        wb.save(xlsx)
        mld_path = os.path.join(tmp, "mld.json")
        with open(mld_path, "w", encoding="utf-8") as fh:
            _j.dump(MLD, fh, ensure_ascii=False)
        win.engine.hooks["pick_import"] = lambda kind, filters=None: [{"fmea": xlsx, "mld": mld_path}[kind]]
        self.assertTrue(self.click(win, "button[aria-label='FMEA']"))
        self.assertTrue(self.idle(win, "button[aria-label='FMEA 가져오기']"))
        self.assertTrue(self.click(win, "button[aria-label='FMEA 가져오기']"))
        self.assertTrue(wait_for(lambda: "FMEA를 가져왔습니다" in self.text(win), 15), self.text(win)[-400:])
        self.assertIn("대응 실패 1", self.text(win))
        self.assertIn("FMEA 대조 전 S2", self.text(win), "전기·제어 구간 줄이 대조 전 구간을 보인다")
        self.assertTrue(self.click(win, "button[aria-label='FM-001 SNP-M-102-E']"))
        self.assertTrue(self.idle(win, "button[aria-label='FM-001 승인']"))
        self.assertTrue(self.click(win, "button[aria-label='FM-001 승인']"))
        self.assertTrue(wait_for(lambda: ie_store.load_fmea(self.project)[0]["rows"]["FM-001"]["status"] == "approved", 10), self.text(win)[-300:])
        self.assertEqual(ie_store.load_fmea(self.project)[0]["history"][-1]["by"], "검토자A")
        self.assertTrue(self.click(win, "button[aria-label='FM-002 NO-SUCH']"))
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector(\"button[aria-label='FM-002 승인']\")"), 10))
        self.assertEqual(self.js(win, "document.querySelector(\"button[aria-label='FM-002 승인']\").disabled"), True, "대응 실패 행은 승인 단추가 막힌다")
        self.assertTrue(self.click(win, "button[aria-label^='완전성 대조']"))
        self.assertTrue(self.idle(win, "button[aria-label='MLD 가져오기']"))
        self.assertTrue(self.click(win, "button[aria-label='MLD 가져오기']"))
        self.assertTrue(wait_for(lambda: "시험용 가상 MLD" in self.text(win) and "B12" in self.text(win), 15), self.text(win)[-400:])
        self.assertIn("범주 없음", self.text(win))


    # ------------------------------------------------------------ B5: 후보 카드(추적·IE 판정)
    def test_candidate_card_shows_the_trace_and_saves_a_judgement(self):
        from hazop.shell import api_ie
        win = self.open_panel()
        c2 = next(c["candidate_id"] for c in api_ie.summary(win.engine)["unassigned"] if c["entry_id"] == "c2")
        self.assertTrue(self.click(win, "button[aria-label='%s 추적·판정']" % c2))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "!!document.querySelector(\"[aria-label='추적']\")")), 10), self.text(win)[-300:])
        trace = self.js(win, "document.querySelector(\"[aria-label='추적']\").innerText") or ""
        for word in ("구간·편차", "원인", "위치·고장모드", "IE 판정", "그룹", "최종상태"):
            self.assertIn(word, trace)
        self.assertTrue(self.click(win, "button[aria-label='%s IE 판정']" % c2))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "!!document.querySelector(\"select[aria-label='초기사건 후보']\")")), 10))
        for sel, val in (("초기사건 후보", "yes"), ("정상운전 교란", "yes"), ("안전기능 도전", "yes"), ("일반 범주", "LOIA")):
            self.js(win, "(() => { const s = document.querySelector(\"select[aria-label='%s']\"); s.value = '%s'; s.dispatchEvent(new Event('change', {bubbles: true})); })()" % (sel, val))
        self.type_into(win, "input[aria-label='판정 이유']", "공기 헤더 압력 저하")
        pump(0.3)
        self.assertTrue(self.click(win, "button[aria-label='판정 확정']"))

        def hint():
            doc, _fp = res.load_fp(self.ns)
            return next(e for c in doc["cells"] for e in c["entries"] if e["entry_id"] == "c2").get("ie_hint") or {}
        self.assertTrue(wait_for(lambda: hint().get("origin") == "human", 10), self.text(win)[-300:])
        h = hint()
        self.assertEqual((h["candidate"], h["category"], h["reason"]), ("yes", "LOIA", "공기 헤더 압력 저하"))
        self.assertTrue(wait_for(lambda: "판정을 저장했습니다" in self.text(win), 10))
        self.assertTrue(self.click(win, "button[aria-label^='구간·편차:']"))
        self.assertTrue(wait_for(lambda: self.js(win, "window.__hz.store.get().panel") == "results", 10), "구간·편차 마디는 그 칸을 연다")


if __name__ == "__main__":
    unittest.main()
