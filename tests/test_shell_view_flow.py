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

    def make_node(self, win, name, parts):
        """parts: [(도면 번호, 구성요소 수)] 순서대로 한 구간을 만든다(첫 도면에서 만들고 다른 도면 것은 더한다)."""
        pid = win.engine.project_id()
        first, n = parts[0]
        data = self.cmd(win, "nodes.create", {"project_id": pid, "set_rev": api_nodes.summary(win.engine)["set_rev"], "sheet": self.gid[first],
                                              "ids": self.sheet_ids(win, first)[:n], "name": name})
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


if __name__ == "__main__":
    unittest.main()
