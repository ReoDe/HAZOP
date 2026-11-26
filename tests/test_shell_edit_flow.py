"""구간 '확정' 없는 화면과, 고른 구간을 Ctrl로 바로 고치기. 실행: python -m unittest tests.test_shell_edit_flow

만든 구간은 곧바로 분석에 든다. 구간 하나를 고른 채 Ctrl로 누르거나 끌면 더함·뺌이 모이고, Enter 한 번(nodes.edit_members)으로 저장한다.
고친 뒤 판정은 칸에 남고 '범위 바뀜'으로 보인다.
"""

import json
import unittest

from tests.test_shell_view_flow import BADGES, PRESS_AT, PRESS_ID, ViewBase
from tests.test_shell_web import pump, wait_for

from hazop.shell import api, api_nodes, api_results

# 화면에서 '확정·잠금' 단추와 상태 글을 찾는다(IE 그룹·쪽 확정은 구간 탭에 없다)
STATE_WORDS = """(() => { const p = document.querySelector('.pwrap'); if (!p) return ['패널 없음'];
  const btn = [...p.querySelectorAll('button')].map((b) => (b.getAttribute('aria-label') || '') + ' ' + b.textContent).filter((s) => /확정|분석 마침|잠금(?! 해제)/.test(s));
  const txt = (p.innerText.match(/확정[^\\n]*|적용됨|분석 마침[^\\n]*|잠금: [^\\n]*/g) || []);
  return btn.concat(txt); })()"""


class EditBase(ViewBase):
    def start(self):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        self.js(win, "window.__ns = null; import('hazop-app://shell/js/panels/nodes_state.js').then((m) => { window.__ns = m; })")
        self.assertTrue(wait_for(lambda: self.js(win, "!!window.__ns") is True, 10))
        self.g1, self.g2 = self.gid["SNP-M-101"], self.gid["SNP-M-102"]
        return win

    def summary(self, win):
        return {n["node_id"]: n for n in api_nodes.summary(win.engine)["nodes"]}

    def members(self, win, nid, number):
        v = api_nodes.sheet_view(win.engine, self.gid[number])
        return sorted(next((s["ids"] for s in v["segments"] if s["node_id"] == nid), []))

    def show_nodes(self, win, count):
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.nrow').length") == count, 30), self.text(win)[-400:])
        pump(0.8)

    def focus(self, win, nid):
        js = "(() => { const b = [...document.querySelectorAll('.nrow .nrow-b')].find((x) => x.getAttribute('aria-label').startsWith(%s)); if (!b) return false; if (b.getAttribute('aria-pressed') !== 'true') b.click(); return true; })()"
        self.assertTrue(wait_for(lambda: self.js(win, js % json.dumps(nid + " ")) is True, 20), nid)
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [nid], 20), "고른 구간 강조: %s" % self.jsj(win, BADGES))
        pump(0.8)

    def press_id(self, win, local, ctrl):
        js = PRESS_AT_ID % json.dumps([local, ctrl])
        self.assertTrue(wait_for(lambda: self.js(win, js) is True, 20), local)
        pump(0.5)

    def bar(self, win):
        return self.js(win, "(() => { const b = document.querySelector('.selbar'); return b ? b.innerText.replace(/\\s+/g, ' ').trim() : ''; })()")

    def picks(self, win):
        return sorted((p["sheet"], i) for p in self.jsj(win, "window.__ns.pickParts()") or [] for i in p["ids"])

    def key(self, win, key):
        self.js(win, "(document.querySelector('.hz-cv') || document.body).dispatchEvent(new KeyboardEvent('keydown', {key: %s, bubbles: true, cancelable: true}))" % json.dumps(key))
        pump(0.5)

    def outside_ids(self, win, nid, number, count):
        """구간에 없는, 눌러서 바로 그것이 잡히는 구성요소."""
        have = set(self.members(win, nid, number))
        return self.pickable(win, [i for i in self.sheet_ids(win, number) if i not in have], count)

    def pickable(self, win, ids, count):
        out = []
        for local in ids:
            self.js(win, "window.__ns.clearSelection()")
            pump(0.2)
            if self.js(win, PRESS_AT_ID % json.dumps([local, True])) is True:
                pump(0.4)
                if (self.jsj(win, "window.__ns.nodes.get().selection") or []) == [local]:
                    out.append(local)
            if len(out) == count:
                break
        self.js(win, "window.__ns.clearSelection()")
        pump(0.4)
        self.assertEqual(len(out), count, "누를 수 있는 구성요소")
        return out


# 구성요소가 그려진 자리(구간 탭에는 추출 네모가 없어 도면 자료의 상자를 화면 좌표로 바꿔 누른다)
PRESS_AT_ID = """(([id, ctrl]) => { const vp = document.querySelector('.hz-cv-vp'), items = window.__items || {}, box = items[id], w = document.querySelector('.hz-cv-world'); if (!vp || !box || !w) return false;
  const r = w.getBoundingClientRect(), k = r.width / parseFloat(w.style.width), x = r.left + (box[0] + box[2]) / 2 * k, y = r.top + (box[1] + box[3]) / 2 * k;
  for (const t of ['pointerdown', 'pointerup']) vp.dispatchEvent(new PointerEvent(t, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, pointerId: 21, isPrimary: true, ctrlKey: ctrl}));
  return true; })(%s)"""
# 화면 좌표 네모로 Ctrl 끌기: 주어진 구성요소들을 모두 감싼다
DRAG_AROUND = """((ids) => { const vp = document.querySelector('.hz-cv-vp'), items = window.__items, w = document.querySelector('.hz-cv-world');
  const r = w.getBoundingClientRect(), k = r.width / parseFloat(w.style.width); const bs = ids.map((i) => items[i]);
  const x0 = r.left + Math.min(...bs.map((b) => b[0])) * k - 1, y0 = r.top + Math.min(...bs.map((b) => b[1])) * k - 1, x1 = r.left + Math.max(...bs.map((b) => b[2])) * k + 1, y1 = r.top + Math.max(...bs.map((b) => b[3])) * k + 1;
  const at = (t, x, y) => vp.dispatchEvent(new PointerEvent(t, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, pointerId: 22, isPrimary: true, ctrlKey: true}));
  at('pointerdown', x0, y0); at('pointermove', (x0 + x1) / 2, (y0 + y1) / 2); at('pointermove', x1, y1); at('pointerup', x1, y1); return true; })(%s)"""


def load_boxes(case, win, number):
    """그 도면 기호의 상자(정리 보기면 정돈 좌표)를 화면에 둔다."""
    gid = case.gid[number]
    items = json.loads(api.ReadApi(win.engine).read(["sheet", gid], {}).body.decode("utf-8"))["items"]
    clean = api.ReadApi(win.engine).read(["clean", gid], {})
    extra = json.loads(clean.body.decode("utf-8")).get("items", {}) if clean is not None else {}
    boxes = {i["id"]: (extra.get(i["id"]) or {}).get("tbox") or i["bbox"] for i in items if i.get("layer") == "symbol"}
    view = case.js(win, "(document.querySelector('.hz-cv') || {getAttribute: () => ''}).getAttribute('data-view')")
    if view != "clean":
        boxes = {i["id"]: i["bbox"] for i in items if i.get("layer") == "symbol"}
    case.js(win, "window.__items = %s" % json.dumps(boxes))


class NoConfirmTest(EditBase):
    def test_there_is_no_confirm_or_lock_and_a_new_node_is_in_the_analysis_at_once(self):
        win = self.start()
        nid = self.make_node(win, "바로 분석", [("SNP-M-101", 3)])
        self.show_nodes(win, 1)
        self.focus(win, nid)
        self.assertEqual(self.jsj(win, STATE_WORDS), [], "확정·잠금 단추와 상태 글이 없다")
        self.js(win, "window.__hz.store.set({panel: 'results'})")
        self.assertTrue(wait_for(lambda: nid in self.text(win) and (self.js(win, "document.querySelectorAll('.res-matrix .vg-cell').length") or 0) > 0, 20), self.text(win)[-400:])
        for gone in ("확정한 구간", "확정하지 않은", "구간을 확정"):
            self.assertNotIn(gone, self.text(win))
        self.js(win, "window.__hz.store.set({panel: 'ie'})")
        pump(1.5)
        self.assertNotIn("확정한 구간", self.text(win))
        self.assertFalse(self.js(win, "!!document.querySelector('.confirm-all')"))


class LockedNodeTest(EditBase):
    def test_an_old_locked_node_shows_only_the_lock_and_cannot_be_edited_or_deleted(self):
        win = self.start()
        nid = self.make_node(win, "옛 잠금", [("SNP-M-101", 3)])
        self.lock(win, nid)
        self.show_nodes(win, 1)
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.nrow .lock-mark').length") == 1, 20))
        self.focus(win, nid)
        labels = self.jsj(win, "[...document.querySelectorAll('.ndetail button')].map((b) => b.getAttribute('aria-label') || b.textContent)")
        self.assertEqual([x for x in labels if "잠금" in x], ["%s 잠금 해제" % nid], labels)
        self.assertFalse([x for x in labels if "지우기" in x or "확정" in x], labels)
        self.assertNotIn("잠금: ", self.text(win), "잠금 기록 글은 없다")
        load_boxes(self, win, "SNP-M-101")
        extra = self.outside_ids(win, nid, "SNP-M-101", 1)[0]
        self.press_id(win, extra, True)
        self.assertNotIn("수정", self.bar(win), "잠긴 구간은 고치기 막대가 아니다: " + self.bar(win))

    def lock(self, win, nid):
        from hazop import store_io
        from hazop.app import project_ctx
        from hazop.study import nodes as sn
        pg = project_ctx.project_graph(win.engine.project_id())
        path = sn.store_path(pg["project_id"], pg["graph_id"])
        raw = json.loads(store_io.read_bytes(path)[0].decode("utf-8"))
        row = next(x for x in raw["nodes"] if x["node_id"] == nid)
        row["state"], row["locked"] = "locked", {"at": "2026-11-26T00:00:00Z", "by": "검토자A", "reason": None}
        store_io.write_json(path, raw, sort_keys=False)
        win.engine.changed("nodes")


class CtrlEditBase(EditBase):
    def prepare(self):
        win = self.start()
        self.nid = self.make_node(win, "고칠 구간", [("SNP-M-101", 4)])
        self.show_nodes(win, 1)
        self.focus(win, self.nid)
        load_boxes(self, win, "SNP-M-101")
        return win


class CtrlEditApplyTest(CtrlEditBase):
    def test_ctrl_press_and_drag_collect_adds_and_removes_and_enter_saves_them_at_once(self):
        win = self.prepare()
        before = self.members(win, self.nid, "SNP-M-101")
        inside = self.pickable(win, before, 1)[0]
        new1, new2 = self.outside_ids(win, self.nid, "SNP-M-101", 2)
        self.press_id(win, new1, True)
        self.assertIn("%s 수정 · 더함 1 · 뺌 0" % self.nid, self.bar(win))
        self.assertIn("구간 수정", self.bar(win))
        self.assertNotIn("구간 만들기", self.bar(win))
        self.press_id(win, inside, True)
        self.assertIn("더함 1 · 뺌 1", self.bar(win))
        self.press_id(win, inside, True)
        self.assertIn("더함 1 · 뺌 0", self.bar(win), "다시 누르면 그 변경을 거둔다")
        self.press_id(win, inside, True)
        self.js(win, DRAG_AROUND % json.dumps([new2]))
        pump(0.6)
        picked = {i for _s, i in self.picks(win)}
        self.assertTrue({new1, inside, new2} <= picked, picked)
        adds, removes = sorted(picked - set(before)), sorted(picked & set(before))
        self.assertTrue(wait_for(lambda: "더함 %d · 뺌 %d" % (len(adds), len(removes)) in self.bar(win), 10), "끌기: 없던 것은 더함, 든 것은 뺌: %s / %s %s" % (self.bar(win), adds, removes))
        self.assertEqual(self.members(win, self.nid, "SNP-M-101"), before, "적용 전에는 저장하지 않는다")
        batches = len(api_nodes.summary(win.engine)["batches"])
        rev = self.summary(win)[self.nid]["rev"]
        self.key(win, "Enter")
        want = (set(before) | set(adds)) - set(removes)
        symbols = lambda ids: sorted(i for i in ids if i.startswith("local-node-"))
        self.assertTrue(wait_for(lambda: symbols(self.members(win, self.nid, "SNP-M-101")) == symbols(want), 20),
                        "적용 뒤 구성원(기호): %s / %s" % (self.members(win, self.nid, "SNP-M-101"), sorted(want)))
        after = set(self.members(win, self.nid, "SNP-M-101"))
        self.assertTrue(after <= want and not (after & set(removes)), "구간에 넣지 않는 선(신호선·계측선)은 엔진이 뺀다: %s / %s" % (sorted(after), sorted(want)))
        self.assertEqual(len(api_nodes.summary(win.engine)["batches"]), batches + 1, "한 번 저장")
        self.assertEqual(self.summary(win)[self.nid]["rev"], rev + 1)
        self.assertEqual(len(self.summary(win)), 1, "새 구간을 만들지 않는다")
        self.assertTrue(wait_for(lambda: self.picks(win) == [] and self.bar(win) == "", 10))
        self.assertEqual(self.js(win, "window.__ns.nodes.get().focus"), self.nid, "고친 구간은 고른 채로")


class CtrlEditDiscardTest(CtrlEditBase):
    def test_x_escape_and_a_plain_blank_press_throw_the_edit_away(self):
        win = self.prepare()
        before = self.members(win, self.nid, "SNP-M-101")
        new = self.outside_ids(win, self.nid, "SNP-M-101", 1)[0]
        self.press_id(win, new, True)
        self.assertTrue(self.click(win, ".selbar button[aria-label='고치던 것 버리기']"))
        self.assertTrue(wait_for(lambda: self.picks(win) == [], 10), "X")
        self.assertEqual(self.js(win, "window.__ns.nodes.get().focus"), self.nid)
        self.press_id(win, new, True)
        self.key(win, "Escape")
        self.assertTrue(wait_for(lambda: self.picks(win) == [], 10), "Esc")
        self.assertEqual(self.js(win, "window.__ns.nodes.get().focus"), self.nid, "Esc는 고치던 것만 버리고 구간 고름은 둔다")
        self.press_id(win, new, True)
        self.js(win, PRESS_AT % json.dumps([0.01, 0.98, 40, False]))
        pump(0.4)
        self.assertEqual(len(self.picks(win)), 1, "끌어 옮기는 것은 버리지 않는다")
        self.js(win, PRESS_AT % json.dumps([0.01, 0.98, 0, False]))
        self.assertTrue(wait_for(lambda: self.picks(win) == [], 10), "Ctrl 없는 빈 곳 누름")
        self.assertEqual(self.members(win, self.nid, "SNP-M-101"), before, "버린 것은 저장되지 않는다")


class CtrlEditSheetsTest(CtrlEditBase):
    def test_the_edit_stays_across_drawings_and_without_a_node_ctrl_still_makes_one(self):
        win = self.prepare()
        before = self.members(win, self.nid, "SNP-M-101")
        new = self.outside_ids(win, self.nid, "SNP-M-101", 1)[0]
        self.press_id(win, new, True)
        self.click_chip(win, "SNP-M-102")
        load_boxes(self, win, "SNP-M-102")
        self.assertEqual(self.picks(win), [(self.g1, new)], "넘어가며 저절로 더하지 않는다")
        other = self.pickable_keep(win, "SNP-M-102")
        self.assertIn("%s 수정 · 더함 2 · 뺌 0" % self.nid, self.bar(win))
        self.key(win, "Enter")
        self.assertTrue(wait_for(lambda: self.members(win, self.nid, "SNP-M-102") == [other] and self.members(win, self.nid, "SNP-M-101") == sorted(before + [new]), 20),
                        "%s %s" % (self.members(win, self.nid, "SNP-M-101"), self.members(win, self.nid, "SNP-M-102")))
        # 구간을 고르지 않으면 지금대로 '구간 만들기'
        self.js(win, "window.__ns.unfocus()")
        pump(0.6)
        fresh = self.outside_ids(win, self.nid, "SNP-M-102", 1)[0]
        self.press_id(win, fresh, True)
        self.assertIn("1개 고름", self.bar(win))
        self.assertIn("구간 만들기", self.bar(win))

    def pickable_keep(self, win, number):
        """앞의 고름은 둔 채, 구간에 없는 구성요소 하나를 Ctrl로 더 고른다."""
        have = set(self.members(win, self.nid, number))
        for local in [i for i in self.sheet_ids(win, number) if i not in have]:
            before = self.picks(win)
            if self.js(win, PRESS_AT_ID % json.dumps([local, True])) is True:
                pump(0.4)
                if self.picks(win) == sorted(before + [(self.gid[number], local)]):
                    return local
                self.js(win, "window.__ns.nodes.set({selection: []})")
                pump(0.3)
        self.fail("누를 수 있는 구성요소")


class EditedJudgementTest(EditBase):
    def test_after_an_edit_the_judgement_stays_in_its_cell_marked_as_scope_changed_until_approved_again(self):
        from hazop.app import project_ctx
        from hazop.ie import bundle
        from hazop.study import nodes as sn
        from hazop.study import results as res
        from tests.test_study_results import entry
        win = self.start()
        nid = self.make_node(win, "판정 있는 구간", [("SNP-M-101", 4)])
        pg = project_ctx.project_graph(win.engine.project_id())
        ns = sn.load(pg)
        doc, fp = res.load_fp(ns)
        doc = res.reconcile(doc, ns, res.load_deviations()) if doc else res.empty_results(ns, res.load_deviations())
        cell = next(c for c in doc["cells"] if c["node_id"] == nid)
        e = entry("e-1", status="approved")
        cell["entries"], cell["state"] = [e], "analyzed"
        res.save_fp(doc, ns["project_id"], expect=fp)
        did = cell["deviation_id"]

        def handed():
            ns2 = sn.load(project_ctx.project_graph(win.engine.project_id()))
            d = res.reconcile(res.load_fp(ns2)[0], ns2, res.load_deviations())
            return len(bundle.approved_entries(d, ns2)[0]), [x["entry_id"] for c in d["cells"] if c["node_id"] == nid for x in c["entries"]], len(d.get("archived_cells") or [])

        self.assertEqual(handed(), (1, ["e-1"], 0))
        self.show_nodes(win, 1)
        self.focus(win, nid)
        load_boxes(self, win, "SNP-M-101")
        new = self.outside_ids(win, nid, "SNP-M-101", 1)[0]
        self.press_id(win, new, True)
        self.key(win, "Enter")
        self.assertTrue(wait_for(lambda: new in self.members(win, nid, "SNP-M-101"), 20))
        self.assertEqual(handed(), (0, ["e-1"], 0), "판정은 칸에 남고 보관 목록으로 가지 않으며, 다시 볼 때까지 인계에서 빠진다")

        def open_cell():
            self.js(win, "window.__hz.store.set({panel: 'results'})")
            self.js(win, "import('hazop-app://shell/js/panels/results_state.js').then((m) => m.openCell(%s, %s))" % (json.dumps(nid), json.dumps(did)))
            self.assertTrue(wait_for(lambda: (self.js(win, "document.querySelectorAll('.worksheet .ent').length") or 0) >= 1, 20), self.text(win)[-300:])

        open_cell()
        marked = "[...document.querySelectorAll('.worksheet .ent .chip')].filter((c) => c.textContent.trim() === '범위 바뀜').length"
        self.assertTrue(wait_for(lambda: self.js(win, marked) == 1, 10), "항목에 '범위 바뀜' 표시: " + self.text(win)[-400:])
        self.assertTrue(self.js(win, "(() => { const b = document.querySelector(\".worksheet .ent button[aria-label='승인']\"); if (!b || b.disabled) return false; b.click(); return true; })()"))
        self.assertTrue(wait_for(lambda: handed()[0] == 1, 20), "다시 승인하면 인계에 돌아온다: %s" % (handed(),))
        self.assertTrue(wait_for(lambda: self.js(win, marked) == 0, 10), "표시가 풀린다")


if __name__ == "__main__":
    unittest.main()
