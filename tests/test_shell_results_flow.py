"""분석 결과 패널의 통합 시험(실제 새 화면 창 + 실제 결과 명령·저장, AI 호출만 가짜). 실행: python -m unittest tests.test_shell_results_flow

행렬이 그려지고 칸을 고르면 워크시트가 열리며, 수용·보류(사유 필수)가 저장되고 머리 수치가 바뀌고, 내보내기와 분석 실행이 패널에서 돈다.
구간 자료는 tests/test_study_export.sample()(도면 둘에 걸친 구간 포함)을 임시 작업 루트에 저장해 쓴다.
"""

import copy
import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

import tests.test_shell_web as W  # noqa: E402
from hazop.shell import analysis_run  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_shell_results import FakeAi, fake_run_unit  # noqa: E402
from tests.test_study_export import DEVS as XDEVS, sample  # noqa: E402

pump, wait_for = W.pump, W.wait_for
tearDownModule = W.shell_teardown


class ResultsPanelTest(W.ShellBase):
    def setUp(self):
        from hazop.app import project_ctx
        self.res_doc, self.ns, self.pg, self.span_node, self.single = sample()
        for p in (mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(XDEVS)),
                  mock.patch.object(W, "small_pg", lambda: self.pg)):
            p.start()
            self.addCleanup(p.stop)
        sn.save(self.ns)
        res.save(self.res_doc, self.ns.get("project_id"))
        self.project = self.ns.get("project_id")

    def stored(self):
        doc, _fp = res.load_fp(self.ns)
        return doc

    def entry(self, node, dev, eid):
        cell = next(c for c in self.stored()["cells"] if (c["node_id"], c["deviation_id"]) == (node, dev))
        return next(e for e in cell["entries"] if e["entry_id"] == eid)

    def open_panel(self):
        win = self.window()
        self.switch_project(win, self.project)
        self.assertTrue(self.click(win, ".rail button", 2))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.res-matrix .vg-cell').length") or 0) > 0, 15), self.text(win)[-300:])
        return win

    def click_cell(self, win, node, dev):
        rows = [n["node_id"] for n in self.ns["nodes"] if n.get("state") != "applied"]
        r, c = rows.index(node), int(dev[1:]) - 1
        ok = self.js(win, "(() => { const e = document.querySelector('.vg-cell[style*=\"top: %dpx; left: %dpx\"]'); if (!e) return false; e.click(); return true; })()" % (r * 34, c * 64))
        self.assertTrue(ok, "칸이 그려지지 않음")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.worksheet .ent').length") or 0) > 0, 10), self.text(win)[-300:])

    def test_matrix_worksheet_accept_hold_and_header_numbers(self):
        win = self.open_panel()
        text = self.text(win)
        self.assertIn("분석 결과", text)
        self.assertIn("구간×편차 행렬", self.js(win, "document.querySelector('[role=grid]').getAttribute('aria-label')"))
        self.click_cell(win, self.span_node, "D01")
        self.assertEqual(self.js(win, "document.querySelectorAll('.worksheet .ent').length"), 2)
        # 두 번째 항목(AI 초안 a2) 수용: 사유 없이 저장
        self.assertTrue(self.js(win, "(() => { const b = [...document.querySelectorAll('.worksheet .ent')][1].querySelector(\"button[aria-label='승인']\"); b.click(); return true; })()"))
        self.assertTrue(wait_for(lambda: self.entry(self.span_node, "D01", "a2")["status"] == "approved", 10))
        self.assertEqual(self.entry(self.span_node, "D01", "a2")["history"][-1]["by"], "검토자A")
        # 보류: 사유가 비면 저장 단추가 막힌다
        self.js(win, "(() => { const e = [...document.querySelectorAll('.worksheet .ent')][0]; e.querySelector(\"button[aria-label='보류']\").click(); })()")
        pump(0.3)
        self.assertEqual(self.js(win, "document.querySelector('.worksheet .ent .field .btn.primary').disabled"), True)
        self.js(win, "(() => { const i = document.querySelector('.worksheet .ent .field input'); i.value = '운전 절차서 확인 뒤'; i.dispatchEvent(new Event('input', {bubbles: true})); })()")
        pump(0.3)
        self.assertEqual(self.js(win, "document.querySelector('.worksheet .ent .field .btn.primary').disabled"), False)
        self.js(win, "document.querySelector('.worksheet .ent .field .btn.primary').click()")
        self.assertTrue(wait_for(lambda: self.entry(self.span_node, "D01", "a1")["status"] == "on_hold", 10))
        e = self.entry(self.span_node, "D01", "a1")
        self.assertEqual(e["history"][-1]["reason"], "운전 절차서 확인 뒤")
        self.assertTrue(wait_for(lambda: "보류 1" in self.text(win), 10), "머리 수치가 바뀐다")
        self.assertIn("운전 절차서 확인 뒤", self.text(win), "판정 사유가 워크시트에 보인다")

    def test_model_text_is_never_html(self):
        win = self.open_panel()
        doc, fp = res.load_fp(self.ns)
        cell = next(c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == (self.span_node, "D01"))
        cell["entries"][1]["cause"] = "<img src=x onerror=window.__pwned=1>원인"
        res.save_fp(doc, self.project, expect=fp)
        self.click_cell(win, self.span_node, "D01")
        self.assertEqual(self.js(win, "document.querySelectorAll('.worksheet img').length"), 0)
        self.assertEqual(self.js(win, "typeof window.__pwned"), "undefined")
        self.assertIn("<img src=x", self.text(win))

    def test_export_buttons_use_the_save_dialog_hook_and_show_the_file_name_only(self):
        win = self.open_panel()
        out = os.path.join(os.path.dirname(win.engine.settings_path), "exported.xlsx")
        win.engine.hooks["save_path"] = lambda kind, name: out
        self.open_export_card(win)
        self.assertTrue(self.js(win, "(() => { const b = document.querySelector(\".exportcard button[aria-label='Excel로 내보내기']\"); b.click(); return true; })()"))
        self.assertTrue(wait_for(lambda: os.path.isfile(out), 20))
        self.assertTrue(wait_for(lambda: "exported.xlsx" in self.text(win), 10))
        self.assertNotIn(os.path.dirname(out), self.text(win), "웹에는 경로를 보이지 않는다")

    def open_export_card(self, win):
        self.assertTrue(self.js(win, "(() => { const b = document.querySelector(\"button[aria-label='Excel 내보내기 범위 고르기']\"); b.click(); return true; })()"))
        self.assertTrue(wait_for(lambda: self.js(win, "!!document.querySelector('.exportcard')"), 10))

    def cell_el(self, win, node, dev):
        rows = [n["node_id"] for n in self.ns["nodes"] if n.get("state") != "applied"]
        r, c = rows.index(node), int(dev[1:]) - 1
        out = self.js(win, "(() => { const e = document.querySelector('.vg-cell[style*=\"top: %dpx; left: %dpx\"]'); if (!e) return null;"
                            " const k = e.querySelector('[title]'); return JSON.stringify({text: e.textContent.trim(), title: k ? k.getAttribute('title') : null, cls: k ? k.className : ''}); })()" % (r * 34, c * 64))
        return json.loads(out) if isinstance(out, str) else out

    def test_matrix_tells_not_applicable_from_not_yet_analyzed_and_shows_the_reason(self):
        win = self.open_panel()
        na = self.cell_el(win, self.span_node, "D02")            # AI가 '해당 없음'(이유: 흐름 없음)
        self.assertEqual(na["text"], "해당 없음")
        self.assertIn("흐름 없음", na["title"])
        failed = self.cell_el(win, self.single, "D01")           # AI 실행 실패
        self.assertEqual(failed["text"], "실패")
        self.assertIn("Timeout", failed["title"])
        not_yet = self.cell_el(win, self.span_node, "D03")       # 아직 분석 전
        self.assertEqual(not_yet["text"], "·")
        self.assertEqual(not_yet["title"], "아직 분석 안 함")
        self.assertIn("해당 없음(AI 판단)", self.text(win), "범례가 Excel과 같은 이름으로 설명한다")
        self.assertIn("아직 분석 안 함", self.text(win))
        self.click_na = self.js(win, "(() => { const e = document.querySelector('.rk-na'); e.click(); return true; })()")
        self.assertTrue(wait_for(lambda: "흐름 없음" in (self.js(win, "(document.querySelector('.worksheet') || {}).textContent || ''") or ""), 10),
                        "눌러 열면 워크시트에 이유가 적힌다")

    def test_export_scope_approved_only_and_chosen_nodes(self):
        import openpyxl
        from hazop.export import study_xlsx
        win = self.open_panel()
        out = os.path.join(os.path.dirname(win.engine.settings_path), "scope.xlsx")
        win.engine.hooks["save_path"] = lambda kind, name: out

        def rows():
            ws = openpyxl.load_workbook(out)[study_xlsx.SHEETS[2]]
            head = [c.value for c in ws[1]]
            return [dict(zip(head, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]

        self.open_export_card(win)
        self.js(win, "document.querySelectorAll('.exportcard input[type=radio]')[1].click()")
        pump(0.3)
        self.assertIn("승인", self.js(win, "document.querySelector('.exportcard').textContent"))
        self.js(win, "document.querySelector(\".exportcard button[aria-label='Excel로 내보내기']\").click()")
        self.assertTrue(wait_for(lambda: os.path.isfile(out), 20))
        self.assertTrue(wait_for(lambda: "승인 항목만" in self.text(win), 10))
        got = rows()
        self.assertTrue(got and {r["상태"] for r in got} == {"승인"}, got)
        os.remove(out)
        self.open_export_card(win)
        self.js(win, "document.querySelectorAll('.exportcard input[type=radio]')[2].click()")
        pump(0.3)
        self.assertEqual(self.js(win, "document.querySelector(\".exportcard button[aria-label='Excel로 내보내기']\").disabled"), True,
                         "구간을 고르지 않으면 내보낼 수 없다")
        self.js(win, "document.querySelectorAll('.exportcard input[type=checkbox]')[0].click()")
        pump(0.3)
        self.js(win, "document.querySelector(\".exportcard button[aria-label='Excel로 내보내기']\").click()")
        self.assertTrue(wait_for(lambda: os.path.isfile(out), 20))
        names = {r["구간"] for r in rows()}
        self.assertEqual(len(names), 1, names)

    def test_run_analysis_from_the_panel(self):
        win = self.open_panel()
        win.engine.ai = FakeAi()
        from hazop.shell import api_results
        reads = []
        real_summary = api_results.summary
        with mock.patch.object(api_results, "summary", lambda eng: reads.append(1) or real_summary(eng)), \
                mock.patch.object(analysis_run, "contexts", lambda units, ns, pg, intent_of: {u["node_id"]: {} for u in units}), \
                mock.patch("hazop.study.ai_cells.run_unit", fake_run_unit()):
            self.assertTrue(self.js(win, "(() => { document.querySelector(\"button[aria-label='분석 실행']\").click(); return true; })()"))
            pump(0.3)
            self.assertTrue(self.js(win, "(() => { document.querySelector(\"button[aria-label='모든 구간 분석']\").click(); return true; })()"))
            self.assertTrue(wait_for(lambda: "AI 분석 실행" in self.text(win), 10), self.text(win)[-300:])
            self.assertIn("호출", self.text(win))
            self.assertTrue(self.js(win, "(() => { const b = document.querySelector(\"button[aria-label='분석 시작']\"); if (b.disabled) return false; b.click(); return true; })()"))
            self.assertTrue(wait_for(lambda: "AI 분석이 끝났습니다" in self.text(win), 30), self.text(win)[-500:])
            self.assertLessEqual(len(reads), 4, "호출 6번 동안 행렬 전체 요약을 호출마다 다시 읽지 않는다: %d번" % len(reads))
        doc = self.stored()
        self.assertTrue(any(e["entry_id"].startswith("ai-") for c in doc["cells"] for e in c["entries"]))

    def test_project_switch_clears_the_panel_and_rereads_for_the_new_project(self):
        win = self.open_panel()
        self.click_cell(win, self.span_node, "D01")
        self.assertEqual(self.js(win, "document.querySelectorAll('.worksheet .ent').length"), 2)
        win.engine.dispatch("project.set", {"project_id": "OTHER"})
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.worksheet').length") or 0) == 0, 10), "앞 프로젝트의 워크시트가 남지 않는다")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.res-matrix .vg-cell').length") or 0) > 0, 15), "새 프로젝트의 행렬을 다시 읽는다")
        self.assertEqual(self.js(win, "document.querySelectorAll('.vg-cell.on').length"), 0, "고른 칸도 비워진다")
        # 낡은 화면이 보낸 쓰기는 바뀐 프로젝트에 닿지 않는다(웹이 싣는 프로젝트 ID가 새 프로젝트로 바뀌었다)
        self.js(win, "window.__hz.cmd('results.stop', {})")
        self.assertEqual(self.js(win, "window.__hz.store.get().app.project_id"), "OTHER")

    def test_without_nodes_the_panel_points_to_the_node_panel(self):
        for n in list(self.ns["nodes"]):
            pass
        os.remove(sn.store_path(self.project, self.ns["graph_id"]))
        win = self.window()
        self.switch_project(win, self.project)
        self.assertTrue(self.click(win, ".rail button", 2))
        self.assertTrue(wait_for(lambda: "확정한 구간이 아직 없습니다" in self.text(win) or "구간 패널 열기" in self.text(win), 15), self.text(win)[-300:])


if __name__ == "__main__":
    unittest.main()


class ResultsToSheetTest(W.ShellBase):
    """'도면에서 보기'와 도면 말풍선의 '분석 결과 추적'(INTENT §3.6): SNP 표본 그래프에서 구간을 만들어 확정하고 분석 칸 하나를 채운 뒤 실제 창에서 따라간다."""

    S101 = "graph-SNP-M-101"

    def setUp(self):
        from hazop.app import project_ctx
        from hazop.shell import api_nodes
        from tests.test_study_node_tools import DEVS, snp_graph
        self.pg = snp_graph()
        for p in (mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                  mock.patch.object(W, "small_pg", lambda: self.pg)):
            p.start()
            self.addCleanup(p.stop)
        self.api_nodes = api_nodes
        self.DEVS = DEVS
        shutil_rm = os.path.join(sn.store_dir(), "SNP")
        import shutil
        shutil.rmtree(shutil_rm, ignore_errors=True)

    def make_confirmed_node_with_a_recommendation(self, win):
        eng = win.engine
        local = [n["local_id"] for n in self.pg["nodes"] if n.get("sheet") == self.S101][:6]
        rev = self.api_nodes.summary(eng)["set_rev"]
        r = eng.dispatch("nodes.create", {"project_id": "SNP", "set_rev": rev, "sheet": self.S101, "ids": local, "name": "구간 가"})
        self.assertTrue(r["ok"], r)
        row = self.api_nodes.summary(eng)["nodes"][0]
        c = eng.dispatch("nodes.confirm", {"project_id": "SNP", "node_ids": [row["node_id"]], "set_rev": self.api_nodes.summary(eng)["set_rev"],
                                           "targets": [{"node_id": row["node_id"], "rev": row["rev"], "state": row["state"]}]})
        self.assertTrue(c["ok"], c)
        ns = sn.load(self.pg)
        doc, fp = res.load_fp(ns)
        doc = doc or res.empty_results(ns, self.DEVS)
        cell = next(x for x in doc["cells"] if x["node_id"] == row["node_id"] and x["deviation_id"] == "D01")
        cell.update(state="analyzed", entries=[{"entry_id": "e1", "origin": "ai_draft", "status": "proposed", "cause": "원인", "consequence": "결과", "safeguards": [],
                                                "recommendation": "밸브 점검", "severity": 2, "frequency": 2, "risk": 2}])
        res.save_fp(doc, ns.get("project_id"), expect=fp if fp else __import__("hazop.store_io", fromlist=["ANY"]).ANY)
        return row["node_id"], local

    def test_view_on_sheet_closes_the_panel_shows_a_back_chip_and_returns(self):
        win = self.window()
        self.switch_project(win, "SNP")
        node, _local = self.make_confirmed_node_with_a_recommendation(win)
        self.assertTrue(self.click(win, ".rail button", 2))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.res-matrix .vg-cell').length") or 0) > 0, 15), self.text(win)[-300:])
        self.js(win, "(() => { const e = document.querySelector('.vg-cell[style*=\"top: 0px; left: 0px\"]'); if (e) e.click(); })()")
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.worksheet').length") or 0) == 1, 10), self.text(win)[-300:])
        self.assertTrue(self.click(win, "button[aria-label='도면에서 보기']"))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.panel').length") or 0) == 0, 10), "패널이 닫힌다")
        self.assertTrue(wait_for(lambda: "분석 결과로 돌아가기" in self.text(win), 10), self.text(win)[:300])
        self.assertEqual(self.js(win, "window.__hz.store.get().sheet"), self.S101, "구간의 구성요소가 놓인 도면이 열린다")
        self.assertTrue(self.click(win, "button[aria-label='분석 결과로 돌아가기']"))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.panel.results').length") or 0) == 1, 10))
        self.assertEqual(self.js(win, "window.__hz.store.get().backTo === null"), True)

    def test_bubble_button_traces_from_a_sheet_component_to_its_recommendation(self):
        win = self.window()
        self.switch_project(win, "SNP")
        node, local = self.make_confirmed_node_with_a_recommendation(win)
        self.js(win, "window.__hz.store.set({sheet: %s})" % json.dumps(self.S101))
        pump(0.5)
        self.js(win, "window.__hz.store.set({bubble: {sheet: %s, id: %s, tag: 'RC-X', kind: 'valve', rect: {x: 100, y: 100, w: 20, h: 20}}})" % (json.dumps(self.S101), json.dumps(local[0])))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.bubble').length") or 0) == 1, 10))
        self.assertTrue(self.click(win, "button[aria-label='분석 결과 추적']"))
        self.assertTrue(wait_for(lambda: "밸브 점검" in self.text(win), 15), self.text(win)[-400:])
        self.assertIn(node, self.text(win))
        self.assertEqual(self.js(win, "document.querySelectorAll('.bubble').length"), 0)

    def test_trace_box_finds_a_component_by_its_tag(self):
        win = self.window()
        self.switch_project(win, "SNP")
        node, local = self.make_confirmed_node_with_a_recommendation(win)
        member = next(n for n in self.pg["nodes"] if n.get("local_id") == local[0])
        tag = member.get("tag") or member["entity_id"]
        self.assertTrue(self.click(win, ".rail button", 2))
        self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.res-matrix .vg-cell').length") or 0) > 0, 15))
        self.assertTrue(self.click(win, "button[aria-label^='권고']"))
        self.assertTrue(wait_for(lambda: bool(self.js(win, "document.getElementById('trace-q') !== null")), 10))
        self.js(win, "(() => { const i = document.getElementById('trace-q'); i.value = %s; i.dispatchEvent(new Event('input', {bubbles: true})); })()" % json.dumps(tag))
        pump(0.3)
        self.assertTrue(self.click(win, "button[aria-label='추적']"))
        self.assertTrue(wait_for(lambda: node in self.text(win) and "구성요소" in self.text(win), 15), self.text(win)[-400:])
