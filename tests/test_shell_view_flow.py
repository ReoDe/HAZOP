"""도면을 여는 보기·구간 강조·고정 패널·Ctrl 고름을 실제 새 화면(화면 밖)에서 확인한다. 실행: python -m unittest tests.test_shell_view_flow

도면은 어느 길로 열어도 한 장 전체가 도면 칸 가운데에 들어온다. 구간은 고른 것만 강조하고 확대해 들어가지 않는다.
"""

import json
import unittest

from tests import test_shell_web as W
from tests.test_shell_web import pump, wait_for

from hazop.shell import api, api_nodes

# 도면 상자(.hz-cv-world는 도면 크기의 상자를 이동·확대한 것)가 도면 칸 안에 모두 들고 가운데에 있는가: 빈 글이면 맞음
FITTED = """(() => { const w = document.querySelector('.hz-cv-world'), v = document.querySelector('.hz-cv-vp'); if (!w || !v) return '도면 없음';
  const a = w.getBoundingClientRect(), b = v.getBoundingClientRect(), bad = [];
  if (!(a.width > 0)) return '크기 0';
  const panel = document.querySelector('.pwrap'); if (panel && panel.getBoundingClientRect().right > b.left + 1) bad.push('패널이 도면 칸을 덮음');
  if (a.left < b.left - 1 || a.right > b.right + 1 || a.top < b.top - 1 || a.bottom > b.bottom + 1) bad.push('칸 밖');
  if (Math.abs((a.left + a.right) - (b.left + b.right)) > 4 || Math.abs((a.top + a.bottom) - (b.top + b.bottom)) > 4) bad.push('가운데 아님');
  if (a.width < b.width * 0.75 && a.height < b.height * 0.75) bad.push('너무 작음');
  return bad.length ? bad.join(',') + ' ' + JSON.stringify([a, b]) : ''; })()"""
# 구간 색으로 그린 것: S 배지 글자와 지금 그린 구간 구성요소
BADGES = "[...document.querySelectorAll('.hz-cv-marks text')].map((t) => t.textContent).filter((t) => /^S\\d+/.test(t))"
SEG_LEGEND = "(() => { const l = document.querySelector('.hz-cv-legend'); return !!l && getComputedStyle(l).display !== 'none' && l.textContent.includes('구간 색'); })()"
VEIL = "!!document.querySelector('.hz-cv-marks rect[fill=\"var(--bg, #f4f5f7)\"]')"
CHIPS = "[...document.querySelectorAll('.hz-cv-chip')].map((c) => c.textContent)"
# 도면 칸의 한 곳을 누른다([x 비율, y 비율, 끈 거리, ctrl]). 합성 포인터 사건
PRESS_AT = """(([fx, fy, dx, ctrl]) => { const vp = document.querySelector('.hz-cv-vp'), v = vp.getBoundingClientRect(), x = v.left + v.width * fx, y = v.top + v.height * fy;
  const at = (t, ax) => vp.dispatchEvent(new PointerEvent(t, {bubbles: true, cancelable: true, clientX: ax, clientY: y, button: 0, pointerId: 11, isPrimary: true, ctrlKey: !!ctrl}));
  at('pointerdown', x); if (dx) at('pointermove', x + dx); at('pointerup', x + dx); return true; })(%s)"""
WHEEL = """(() => { const vp = document.querySelector('.hz-cv-vp'), v = vp.getBoundingClientRect();
  for (let i = 0; i < 4; i++) vp.dispatchEvent(new WheelEvent('wheel', {bubbles: true, cancelable: true, deltaY: -200, clientX: v.left + 60, clientY: v.top + 80})); return true; })()"""


class ViewBase(W.ShellBase):
    def open_app(self, panel="drawings"):
        win = self.window((1366, 768))
        pump(0.8)
        self.js(win, "window.__hz.store.set({panel: %s})" % json.dumps(panel))
        rows = self.jsj(win, "window.__hz.store.get().drawings.drawings")
        self.gid = {d["drawing_number"]: d["graph_id"] for d in rows}
        return win

    def sheet(self, win):
        return self.js(win, "window.__hz.store.get().sheet")

    def fitted(self, win, where):
        self.assertTrue(wait_for(lambda: self.js(win, FITTED) == "", 15), "%s: %s" % (where, self.js(win, FITTED)))

    def ready(self, win, number):
        self.assertTrue(wait_for(lambda: self.sheet(win) == self.gid[number] and self.js(win, "window.__hz.store.get().readySheet") == self.gid[number], 30),
                        "%s 도면이 열리지 않음(%s)" % (number, self.sheet(win)))
        pump(0.8)

    def open_row(self, win, number):
        self.assertTrue(wait_for(lambda: self.js(win, "(() => { const b = [...document.querySelectorAll('.drow-open')].find((x) => x.textContent.includes(%s)); if (!b) return false; b.click(); return true; })()" % json.dumps(number)) is True, 20))
        self.ready(win, number)

    def zoom_away(self, win):
        self.js(win, WHEEL)
        pump(0.5)
        self.assertNotEqual(self.js(win, FITTED), "", "확대하면 전체 맞춤이 아니다(시험 장치 확인)")

    def sheet_ids(self, win, number):
        items = json.loads(api.ReadApi(win.engine).read(["sheet", self.gid[number]], {}).body.decode("utf-8"))["items"]
        return [i["id"] for i in items if i.get("layer") == "symbol" and i.get("category") == "equipment"] + [i["id"] for i in items if i.get("layer") == "symbol" and i.get("category") != "equipment"]

    def cmd(self, win, name, args):
        r = win.engine.dispatch(name, args)
        self.assertTrue(r["ok"], r)
        return r["data"]

    def make_node(self, win, name, parts, skip=0):
        """skip: 첫 도면에서 앞 skip개를 건너뛴다. parts: [(도면 번호, 구성요소 수)] 순서대로 한 구간을 만든다(첫 도면에서 만들고 다른 도면 것은 더한다)."""
        pid = win.engine.project_id()
        first, n = parts[0]
        data = self.cmd(win, "nodes.create", {"project_id": pid, "set_rev": api_nodes.summary(win.engine)["set_rev"], "sheet": self.gid[first],
                                              "ids": self.sheet_ids(win, first)[skip:skip + n], "name": name})
        nid = data["node_ids"][0]
        for number, count in parts[1:]:
            row = next(x for x in api_nodes.summary(win.engine)["nodes"] if x["node_id"] == nid)
            self.cmd(win, "nodes.add_members", {"project_id": pid, "set_rev": api_nodes.summary(win.engine)["set_rev"], "node_id": nid, "sheet": self.gid[number],
                                                "ids": self.sheet_ids(win, number)[:count], "targets": [{"node_id": nid, "rev": row["rev"], "state": row["state"]}]})
        win.engine.changed("nodes")
        return nid

    def click_chip(self, win, number):
        self.assertTrue(wait_for(lambda: self.js(win, "(() => { const c = [...document.querySelectorAll('.hz-cv-chip')].find((x) => x.textContent.includes(%s)); if (!c) return false; c.click(); return true; })()" % json.dumps(number)) is True, 20),
                        "칩 %s 없음: %s" % (number, self.jsj(win, CHIPS)))
        self.ready(win, number)


class OpenFittedTest(ViewBase):
    def test_every_way_of_opening_a_drawing_shows_the_whole_sheet_centred(self):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        self.fitted(win, "도면 줄로 연 직후")
        self.zoom_away(win)
        self.open_row(win, "SNP-M-101")
        self.fitted(win, "같은 도면 줄을 다시 누름")
        self.zoom_away(win)
        self.open_row(win, "SNP-M-102")
        self.fitted(win, "확대해 둔 채 다른 도면 줄")
        self.open_row(win, "SNP-M-101")
        self.zoom_away(win)
        self.click_chip(win, "SNP-M-102")
        self.fitted(win, "도면 연결 칩")
        # 분석 결과의 '도면에서 보기'가 도면을 바꾸는 길
        nid = self.make_node(win, "가압기 쪽", [("SNP-M-102", 4)])
        self.open_row(win, "SNP-M-101")
        self.zoom_away(win)
        self.js(win, "import('hazop-app://shell/js/panels/results_state.js').then((m) => m.viewOnSheet(%s))" % json.dumps(nid))
        self.ready(win, "SNP-M-102")
        self.fitted(win, "분석 결과의 도면에서 보기")
        self.assertEqual(self.js(win, "window.__hz.store.get().panel"), "nodes", "구간 강조가 보이는 구간 탭")
        self.assertTrue(wait_for(lambda: nid in (self.jsj(win, BADGES) or []), 15), "고른 구간 강조")


class NodeFocusViewTest(ViewBase):
    def row(self, win, nid):
        js = "(() => { const b = [...document.querySelectorAll('.nrow .nrow-b')].find((x) => x.getAttribute('aria-label').startsWith(%s)); if (!b) return false; b.click(); return true; })()"
        self.assertTrue(wait_for(lambda: self.js(win, js % json.dumps(nid + " ")) is True, 20), "구간 줄 %s" % nid)

    def test_no_pick_means_a_plain_drawing_and_a_pick_highlights_only_that_node_on_the_fitted_sheet(self):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        a = self.make_node(win, "두 도면 구간", [("SNP-M-101", 3), ("SNP-M-102", 7)])
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        self.assertTrue(wait_for(lambda: "두 도면 구간" in self.text(win), 30))
        pump(1.5)
        self.assertEqual(self.jsj(win, BADGES), [], "고르지 않으면 S 배지가 없다")
        self.assertFalse(self.js(win, SEG_LEGEND), "구간 색 범례가 없다")
        self.assertFalse(self.js(win, VEIL), "흐리게 덮지 않는다")
        self.zoom_away(win)
        self.row(win, a)
        self.ready(win, "SNP-M-102")      # 구성요소가 가장 많은 도면
        self.fitted(win, "구간을 누른 뒤(확대해 들어가지 않음)")
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [a], 15), "고른 구간만: %s" % self.jsj(win, BADGES))
        self.assertTrue(self.js(win, VEIL), "나머지는 흐리게")
        self.click_chip(win, "SNP-M-101")
        self.fitted(win, "칩으로 넘어간 도면")
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [a], 15), "넘어간 도면에도 같은 구간 강조: %s" % self.jsj(win, BADGES))
        self.js(win, PRESS_AT % json.dumps([0.01, 0.98, 40, False]))
        pump(0.5)
        self.assertEqual(self.jsj(win, BADGES), [a], "끌어 옮긴 것은 고름을 풀지 않는다")
        self.js(win, PRESS_AT % json.dumps([0.01, 0.98, 0, False]))
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [], 15), "빈 곳을 누르면 기본 모습")
        self.assertFalse(self.js(win, VEIL))
        self.row(win, a)
        self.ready(win, "SNP-M-102")
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [a], 15))
        self.row(win, a)
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [], 15), "고른 구간을 다시 누르면 기본 모습")


# 패널 안에서 글이 옆으로 잘린 곳: 가로로 넘치는데 감추거나 말줄임 없이 잘라 버리는 요소(말줄임표를 단 줄은 뺀다)
CLIPPED = """(() => { const out = [], panel = document.querySelector('.pwrap'); if (!panel) return ['패널 없음'];
  for (const el of panel.querySelectorAll('*')) { if (!el.clientWidth || el.scrollWidth <= el.clientWidth + 1) continue; const cs = getComputedStyle(el);
    if (cs.textOverflow === 'ellipsis' || cs.overflowX === 'auto' || cs.overflowX === 'scroll' || el.tagName === 'INPUT') continue;
    if (cs.overflowX === 'visible' && el.getBoundingClientRect().left + el.scrollWidth <= panel.getBoundingClientRect().right + 1) continue;
    out.push((el.className && el.className.baseVal === undefined ? el.className : el.tagName) + ' ' + el.scrollWidth + '>' + el.clientWidth + ' ' + (el.textContent || '').trim().slice(0, 40)); }
  const r = panel.getBoundingClientRect().right;
  for (const el of panel.querySelectorAll('button, .chip, b, span, label, h2')) { const b = el.getBoundingClientRect(); if (b.width && b.right > r + 1) out.push('패널 밖 ' + (el.textContent || '').trim().slice(0, 40)); }
  return out.slice(0, 10); })()"""


class FixedPanelTest(ViewBase):
    def panel(self, win):
        return self.js(win, "window.__hz.store.get().panel")

    def key(self, win, key, ctrl=False):
        self.js(win, "document.body.dispatchEvent(new KeyboardEvent('keydown', {key: %s, ctrlKey: %s, bubbles: true}))" % (json.dumps(key), "true" if ctrl else "false"))
        pump(0.3)

    def rail(self, win, label):
        self.assertTrue(self.js(win, "(() => { const b = [...document.querySelectorAll('.rail button')].find((x) => x.getAttribute('aria-label').startsWith(%s)); if (!b) return false; b.click(); return true; })()" % json.dumps(label)))
        pump(0.5)

    def test_the_drawing_and_node_panels_are_always_there_and_cannot_be_closed(self):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        for label, name, number in (("도면", "drawings", "1"), ("구간", "nodes", "2")):
            self.rail(win, label)
            self.assertEqual(self.panel(win), name)
            self.assertFalse(self.js(win, "!!document.querySelector(\".pwrap button[aria-label='패널 닫기']\")"), name + " 패널에 닫기 단추가 없다")
            self.rail(win, label)
            self.assertEqual(self.panel(win), name, "왼쪽 메뉴를 다시 눌러도 닫히지 않는다")
            self.key(win, number, True)
            self.key(win, "Escape")
            self.key(win, "0", True)
            self.assertEqual(self.panel(win), name, "Ctrl+숫자·Esc·Ctrl+0에도 그대로")
            self.fitted(win, name + " 패널 옆 도면 칸")
        # 다른 패널을 닫으면 마지막에 보던 고정 패널이 돌아온다
        self.rail(win, "설정")
        self.assertEqual(self.panel(win), "settings")
        self.assertTrue(self.click(win, "section.panel button[aria-label='패널 닫기']"))
        pump(0.5)
        self.assertEqual(self.panel(win), "nodes")

    def test_the_two_panels_are_four_fifths_as_wide_and_clip_no_text(self):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        nid = self.make_node(win, "가압기 살수 배관과 완충 배관을 함께 보는 긴 이름의 구간", [("SNP-M-101", 3), ("SNP-M-102", 5)])
        full = float(self.js(win, "parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--panel-w'))"))
        for name in ("drawings", "nodes"):
            self.js(win, "window.__hz.store.set({panel: %s})" % json.dumps(name))
            pump(1.0)
            if name == "nodes":
                self.assertTrue(wait_for(lambda: self.js(win, "(() => { const b = document.querySelector('.nrow .nrow-b'); if (!b) return false; if (b.getAttribute('aria-pressed') !== 'true') b.click(); return true; })()") is True, 20), nid)
                pump(2.0)
            else:
                self.js(win, "(() => { const b = document.querySelector('.drow input[type=checkbox]'); if (b && !b.checked) b.click(); })()")
                pump(0.5)
            width = self.js(win, "document.querySelector('.pwrap').getBoundingClientRect().width")
            self.assertAlmostEqual(width, full * 0.8, delta=1.5, msg=name)
            self.assertEqual(self.jsj(win, CLIPPED), [], name + " 패널에서 잘린 글")
            apart = self.jsj(win, "[...document.querySelectorAll('.pwrap .row')].filter((r) => { const c = r.querySelector('input[type=checkbox]'), m = r.querySelector('.nrow-b, .drow-open'); if (!c || !m) return false; const x = c.getBoundingClientRect(), y = m.getBoundingClientRect(), mid = (x.top + x.bottom) / 2; return mid < y.top || mid > y.bottom || x.right > y.left + 1; }).map((r) => r.textContent.slice(0, 30))")
            self.assertEqual(apart, [], name + " 줄의 체크 상자가 내용과 같은 줄 왼쪽에 있다")


# 구성요소 가운데를 누른다([id, ctrl]). 도면 탭의 추출 네모(data-check)가 구성요소 자리다
PRESS_ID = """(([id, ctrl]) => { const vp = document.querySelector('.hz-cv-vp'), el = document.querySelector('.hz-cv-marks [data-check="' + id + '"]'); if (!el) return false;
  const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
  for (const t of ['pointerdown', 'pointerup']) vp.dispatchEvent(new PointerEvent(t, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, pointerId: 12, isPrimary: true, ctrlKey: ctrl}));
  return true; })(%s)"""


class CtrlPickTest(ViewBase):
    def start(self):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        self.js(win, "window.__ns = null; import('hazop-app://shell/js/panels/nodes_state.js').then((m) => { window.__ns = m; })")
        self.assertTrue(wait_for(lambda: self.js(win, "!!window.__ns") is True, 10))
        return win

    def sel(self, win):
        return sorted(self.jsj(win, "window.__ns.nodes.get().selection") or [])

    def parts(self, win):
        """{graph_id: 고른 id들} (모든 도면)."""
        return {p["sheet"]: sorted(p["ids"]) for p in self.jsj(win, "window.__ns.pickParts()") or []}

    def press_id(self, win, local, ctrl):
        self.assertTrue(wait_for(lambda: self.js(win, PRESS_ID % json.dumps([local, ctrl])) is True, 20), local)
        pump(0.5)

    def pickable(self, win, number, count):
        """눌러서 바로 그 구성요소가 잡히는 id들(겹친 것은 건너뛴다)."""
        out = []
        for local in self.sheet_ids(win, number):
            self.js(win, "window.__ns.clearSelection()")
            pump(0.2)
            if self.js(win, PRESS_ID % json.dumps([local, True])) is True:
                pump(0.4)
                if self.sel(win) == [local]:
                    out.append(local)
            if len(out) == count:
                break
        self.js(win, "window.__ns.clearSelection()")
        pump(0.4)
        self.assertEqual(len(out), count, "누를 수 있는 구성요소")
        return out

    def links_back(self, win, number, came_from):
        data = json.loads(api.ReadApi(win.engine).read(["nodes", "sheet", self.gid[number]], {}).body.decode("utf-8"))
        return sorted(r["id"] for r in data["links"] if r.get("status") == "linked" and r.get("peer_graph_id") == self.gid[came_from])

    def test_a_plain_press_releases_every_pick_but_a_drag_does_not(self):
        win = self.start()
        a, b = self.pickable(win, "SNP-M-101", 2)
        self.press_id(win, a, True)
        self.press_id(win, b, True)
        self.assertEqual(self.sel(win), sorted([a, b]))
        self.js(win, PRESS_AT % json.dumps([0.01, 0.98, 40, False]))
        pump(0.5)
        self.assertEqual(self.sel(win), sorted([a, b]), "끌어 옮긴 것은 풀지 않는다")
        self.js(win, PRESS_AT % json.dumps([0.01, 0.98, 0, False]))
        self.assertTrue(wait_for(lambda: self.parts(win) == {}, 10), "빈 곳을 한 번 누르면 모두 풀린다: %s" % self.parts(win))
        self.press_id(win, a, True)
        self.press_id(win, b, False)
        self.assertEqual(self.parts(win), {}, "Ctrl 없이 다른 구성요소를 눌러도 풀린다")
        self.press_id(win, a, True)
        self.assertEqual(self.sel(win), [a], "풀린 뒤에는 새로 묶는다(앞의 것이 남지 않는다)")
        self.js(win, "document.querySelector('.hz-cv').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        self.assertTrue(wait_for(lambda: self.parts(win) == {}, 10), "Esc")

    def test_picks_stay_with_their_drawing_show_where_you_came_from_and_make_one_node(self):
        win = self.start()
        g1, g2 = self.gid["SNP-M-101"], self.gid["SNP-M-102"]
        self.click_chip(win, "SNP-M-102")
        self.assertEqual(self.parts(win), {}, "묶던 것이 없으면 넘어가도 아무것도 고르지 않는다")
        self.assertEqual(self.jsj(win, "[...document.querySelectorAll('.hz-cv-chip.picked')].length"), 0)
        b = self.pickable(win, "SNP-M-102", 1)[0]
        self.open_row(win, "SNP-M-101")
        a = self.pickable(win, "SNP-M-101", 1)[0]
        self.press_id(win, a, True)
        back = self.links_back(win, "SNP-M-102", "SNP-M-101")
        self.assertTrue(back, "시험 자료: 102에서 101을 가리키는 연결")
        self.click_chip(win, "SNP-M-102")
        self.assertTrue(wait_for(lambda: self.sel(win) == back, 15), "떠나온 도면을 가리키는 연결 기호가 묶음에 든다: %s / %s" % (self.sel(win), back))
        self.assertEqual(self.parts(win).get(g1), [a], "앞 도면에서 묶은 것은 그 도면에 남는다")
        chips = "[...document.querySelectorAll('.hz-cv-chip')].map((c) => [c.textContent, c.classList.contains('picked')])"
        self.assertTrue(wait_for(lambda: any(on for _t, on in self.jsj(win, chips)) and all(("SNP-M-101" in t) == on for t, on in self.jsj(win, chips)), 10),
                        "온 곳을 가리키는 칩만 묶음 색: %s" % self.jsj(win, chips))
        self.press_id(win, b, True)
        self.assertEqual(self.sel(win), sorted(back + [b]), "넘어온 도면에서 계속 더한다")
        self.open_row(win, "SNP-M-101")
        self.assertEqual(self.sel(win), [a], "돌아오면 그 도면의 묶음이 그대로")
        self.press_id(win, a, True)
        self.assertEqual(self.sel(win), [], "도면에 그려진 고름이라 Ctrl+누르기로 뺄 수 있다")
        self.press_id(win, a, True)
        self.assertEqual(self.parts(win), {g1: [a], g2: sorted(back + [b])})
        total = 1 + len(back) + 1
        self.assertTrue(wait_for(lambda: "%d개 고름" % total in self.text(win), 10), "막대의 수는 모든 도면의 합: %s" % total)
        self.js(win, "document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")
        self.assertTrue(wait_for(lambda: len(api_nodes.summary(win.engine)["nodes"]) == 1, 20), "여러 도면에 걸친 고름으로 구간 하나")
        row = api_nodes.summary(win.engine)["nodes"][0]
        self.assertEqual({x["graph_id"] for x in row["sheets"]}, {g1, g2}, row["sheets"])
        self.assertTrue(wait_for(lambda: self.parts(win) == {}, 10), "만들면 고름은 비운다")


class NodeListBase(ViewBase):
    ROW = "(() => { const r = [...document.querySelectorAll('.nrow')].find((x) => x.querySelector('.nrow-b').getAttribute('aria-label').startsWith(%s)); return r || null; })()"

    def nodes(self, win):
        return {n["node_id"]: n for n in api_nodes.summary(win.engine)["nodes"]}

    def start(self):
        win = self.open_app()
        self.open_row(win, "SNP-M-101")
        return win

    def show_nodes(self, win, count):
        self.js(win, "window.__hz.store.set({panel: 'nodes'})")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.nrow').length") == count, 30), self.text(win)[-400:])

    BOX = "[...document.querySelectorAll('.pwrap input[type=checkbox]')].find((x) => x.getAttribute('aria-label') === %s)"

    def check(self, win, label):
        js = "(() => { const b = " + self.BOX % json.dumps(label) + "; if (!b) return false; b.click(); return true; })()"
        self.assertTrue(wait_for(lambda: self.js(win, js) is True, 20), label)
        pump(0.4)

    def boxes(self, win, kind):
        """맨 위 전체 선택의 [체크됨, 중간]."""
        return self.jsj(win, "(() => { const b = " + self.BOX % json.dumps(kind + " 전체 선택") + "; return b ? [b.checked, b.indeterminate] : null; })()")

    def lock(self, win, nid):
        """저장 파일을 직접 잠금 상태로 바꾼다(잠금은 분석을 모두 마쳐야 해서 화면 시험에서는 이렇게 만든다)."""
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


class NodeRowTest(NodeListBase):
    def test_rows_show_only_the_dot_number_name_range_and_count_and_there_is_no_merge(self):
        win = self.start()
        a = self.make_node(win, "첫 구간", [("SNP-M-101", 3), ("SNP-M-102", 3)])
        b = self.make_node(win, "둘째 구간", [("SNP-M-101", 3)], skip=3)
        self.cmd(win, "nodes.confirm", {"project_id": win.engine.project_id(), "set_rev": api_nodes.summary(win.engine)["set_rev"], "node_ids": [b],
                                        "targets": [{"node_id": b, "rev": self.nodes(win)[b]["rev"], "state": "applied"}]})
        win.engine.changed("nodes")
        self.show_nodes(win, 2)
        pump(1.0)
        self.assertEqual(self.js(win, "document.querySelectorAll('.nrow .chip, .nrow .span-mark').length"), 0, "줄에 상태 꼬리표·기호가 없다")
        row = self.js(win, "document.querySelector('.nrow').innerText")
        self.assertNotIn("⇄", row)
        for word in ("확정", "적용됨", "겹침"):
            self.assertNotIn(word, self.js(win, "[...document.querySelectorAll('.nrow')].map((r) => r.innerText).join(' ')"))
        self.assertIn("구성요소", row)
        self.lock(win, b)
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.nrow svg.lock-mark, .nrow .lock-mark').length") == 1, 20), "잠긴 구간은 자물쇠 하나")
        self.check(win, "%s 고르기" % a)
        self.check(win, "%s 고르기" % b)
        self.assertFalse(self.js(win, "[...document.querySelectorAll('.pwrap button')].some((x) => /합치|병합/.test((x.textContent || '') + (x.getAttribute('aria-label') || '') + (x.title || '')))"), "합치는 길이 없다")


class NodeTrashTest(NodeListBase):
    def test_select_all_and_the_trash_delete_everything_but_locked_nodes_and_undo_brings_them_back(self):
        win = self.start()
        a = self.make_node(win, "지울 구간", [("SNP-M-101", 3)])
        b = self.make_node(win, "확정해 둔 구간", [("SNP-M-101", 3), ("SNP-M-102", 2)], skip=3)
        c = self.make_node(win, "잠긴 구간", [("SNP-M-101", 3)], skip=6)
        for nid in (b,):
            self.cmd(win, "nodes.confirm", {"project_id": win.engine.project_id(), "set_rev": api_nodes.summary(win.engine)["set_rev"], "node_ids": [nid],
                                            "targets": [{"node_id": nid, "rev": self.nodes(win)[nid]["rev"], "state": "applied"}]})
        self.lock(win, c)
        self.show_nodes(win, 3)
        pump(1.0)
        self.assertEqual(self.boxes(win, "구간"), [False, False])
        self.check(win, "%s 고르기" % a)
        self.assertEqual(self.boxes(win, "구간"), [False, True], "일부만 고르면 중간 상태")
        self.check(win, "구간 전체 선택")
        self.assertEqual(self.boxes(win, "구간"), [True, False])
        ticked = "[...document.querySelectorAll('.nrow input[type=checkbox]')].map((x) => x.checked)"
        self.assertEqual(self.jsj(win, ticked), [True, True, False], "잠긴 구간은 전체 선택에서 빠진다")
        self.assertIn("2개 고름", self.text(win))
        self.check(win, "구간 전체 선택")
        self.assertEqual(self.jsj(win, ticked), [False, False, False], "다시 누르면 모두 해제")
        self.check(win, "구간 전체 선택")
        self.js(win, "(() => { const x = document.querySelector('.nrow .nrow-b'); x.click(); })()")
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [a], 15), "지울 구간을 강조해 둔다")
        trash = """document.querySelector('.pwrap .picks button[aria-label="삭제"]')"""
        self.assertTrue(self.js(win, "!!%s && !%s.textContent.trim() && %s.title === '삭제'" % (trash, trash, trash)), "휴지통은 아이콘만")
        self.js(win, trash + ".click()")
        self.assertTrue(wait_for(lambda: sorted(self.nodes(win)) == [c], 30), "고른 구간만 지워진다: %s" % sorted(self.nodes(win)))
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.nrow').length") == 1, 20))
        self.assertTrue(wait_for(lambda: self.jsj(win, BADGES) == [], 15), "도면 강조도 사라진다")
        self.assertNotIn("보관하고 지우기", self.text(win), "확인 창이 없다")
        undo = """document.querySelector('.pwrap button[aria-label="지운 구간 되돌리기"]')"""
        self.assertTrue(wait_for(lambda: self.js(win, "!!" + undo) is True, 10), "지운 직후 되돌리기")
        self.js(win, undo + ".click()")
        self.assertTrue(wait_for(lambda: sorted(self.nodes(win)) == sorted([a, b, c]), 30), "되돌리면 돌아온다: %s" % sorted(self.nodes(win)))
        self.assertTrue(wait_for(lambda: self.nodes(win)[b]["state"] == "confirmed", 20), "확정했던 구간은 다시 확정 상태: %s" % self.nodes(win)[b]["state"])
        self.assertEqual((self.nodes(win)[a]["state"], self.nodes(win)[c]["state"]), ("applied", "locked"))
        self.assertTrue(wait_for(lambda: self.js(win, "!!" + undo) is False, 10), "한 번만")


class DrawingSelectAllTest(NodeListBase):
    def test_select_all_in_the_drawing_list_leaves_out_drawings_without_a_number(self):
        win = self.open_app()
        self.js(win, """(() => { const d = window.__hz.store.get().drawings; window.__hz.store.set({ drawings: Object.assign({}, d, { drawings: d.drawings.concat([{ graph_id: 'g-blank', display: 'SIS.pdf · 1쪽', drawing_number: null, number_state: 'unconfirmed', title: null, material_id: 'm9', unknowns: 0 }]) }) }); })()""")
        self.assertTrue(wait_for(lambda: self.js(win, "document.querySelectorAll('.drow input[type=checkbox]').length") == 3, 20))
        ticked = "[...document.querySelectorAll('.drow input[type=checkbox]')].map((x) => x.checked)"
        self.assertEqual(self.boxes(win, "도면"), [False, False])
        self.check(win, "도면 전체 선택")
        self.assertEqual(self.jsj(win, ticked), [True, True, False], "번호가 빈 도면은 빠진다")
        self.assertEqual(self.boxes(win, "도면"), [True, False])
        self.js(win, "document.querySelector('.drow input[type=checkbox]').click()")
        pump(0.4)
        self.assertEqual(self.boxes(win, "도면"), [False, True])
        self.check(win, "도면 전체 선택")
        self.check(win, "도면 전체 선택")
        self.assertEqual(self.jsj(win, ticked), [False, False, False])


if __name__ == "__main__":
    unittest.main()
