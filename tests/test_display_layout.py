"""② 도면·④ 검토구간 표시 결함(단위 H-b, 실제 창 결함 후보 4·6·11·14). 실행: python -m unittest tests.test_display_layout

오프스크린 Qt에서 두 창 크기로 본다. 1366×768(100%)과 1920×1080(125%)이다. 125%는 논리 화소로 1536×864다
(시험 프로세스는 배율을 하나만 쓰므로 같은 논리 크기로 맞춘다). 임시 작업 루트에 샘플 도면 SNP-M-101·102를 추출해 쓴다.
"""

import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

from scripts.check_edit_screen import install_sample  # noqa: E402
from tests.test_app import pump, tearDownModule, wait_for  # noqa: E402,F401

SIZES = {"1366x768 100%": (1366, 768), "1920x1080 125%": (1536, 864)}
DRAWINGS = ("SNP-M-101", "SNP-M-102")
EXTRACT, STUDY = 1, 5

# 웹뷰 점검(scripts/check_user_scenarios.py DOM_AUDIT_JS와 같은 기준): 글자를 가진 보이는 요소끼리 4px 넘게 겹치는 쌍,
# 떠 있는 조작 칸끼리 겹치는 쌍, 떠 있는 칸 밑에 깔린 태그 글자, 떠 있는 칸 가운데를 덮은 요소
AUDIT_JS = r"""(() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('svg'); };
  const desc = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : '') + ' "' + e.textContent.trim().slice(0, 20) + '"';
  const hit = (ra, rb, m) => Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left) > m && Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top) > m;
  const leaves = [];
  for (const e of document.querySelectorAll('body *')) {
    if (!vis(e)) continue;
    const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (own) leaves.push([e, e.getBoundingClientRect()]);
  }
  const out = {overlaps: [], floats: [], under: [], covered: [], tags: document.querySelectorAll('#taglabels span').length};
  for (let i = 0; i < leaves.length; i++) for (let j = i + 1; j < leaves.length; j++) {
    const [a, ra] = leaves[i], [b, rb] = leaves[j];
    if (!a.contains(b) && !b.contains(a) && hit(ra, rb, 4)) out.overlaps.push(desc(a) + ' × ' + desc(b));
  }
  const floats = [...document.querySelectorAll('.float')].filter(vis).filter(e => !e.closest('#layers #legend-drop'));
  for (let i = 0; i < floats.length; i++) for (let j = i + 1; j < floats.length; j++)
    if (hit(floats[i].getBoundingClientRect(), floats[j].getBoundingClientRect(), 0)) out.floats.push(floats[i].id + ' × ' + floats[j].id);
  for (const s of document.querySelectorAll('#taglabels span')) if (vis(s))
    for (const f of floats) if (hit(s.getBoundingClientRect(), f.getBoundingClientRect(), 0)) out.under.push(s.textContent + ' × ' + f.id);
  for (const f of floats) { const r = f.getBoundingClientRect(), top = document.elementFromPoint(r.left + 6, r.top + r.height / 2);
    if (top && !f.contains(top)) out.covered.push(f.id + ' ← ' + desc(top)); }
  return JSON.stringify(out);
})()"""


class DisplayBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-display-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        os.environ["HAZOP_WORK_ROOT"] = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop.app import make_application
        cls.qapp = make_application(["test"])
        cls.names = [install_sample(os.environ["HAZOP_WORK_ROOT"], d) for d in DRAWINGS]

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def window(self, size):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=os.path.join(tempfile.mkdtemp(dir=self.tmp), "settings.json"), ask_reviewer=False)
        win.set_reviewer_name("검토자A")
        win.resize(*size)
        win.show()
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.webview.dispose)
        self.addCleanup(win.close)
        pump(seconds=0.1)
        return win

    def settle(self, win):
        self.assertTrue(wait_for(lambda: win.webview.bridge.is_ready), "웹뷰 준비 안 됨")
        pump(seconds=0.4)

    def js(self, win, code):
        out = []
        win.webview.page().runJavaScript(code, 0, out.append)
        self.assertTrue(wait_for(lambda: out), "JS 응답 없음")
        return out[0]


class CountChipTest(DisplayBase):
    """결함 4: 저장 전 개수 칩이 저장본과 같은 기준(그래프)으로 센다."""

    def counts(self, text):
        m = re.match(r"노드 (\d+) · 관계 (\d+) · 미확인 (\d+)", text)
        self.assertIsNotNone(m, text)
        return tuple(int(x) for x in m.groups())

    def test_deleting_one_item_changes_the_count_by_about_one(self):
        from hazop.app.screens import viewer
        win = self.window(SIZES["1366x768 100%"])
        win.go(EXTRACT)
        scr = win.screens[EXTRACT]
        scr.select_drawing(self.names[1])
        self.assertTrue(scr.editable())
        scr.edit_btn.setChecked(True)
        self.addCleanup(lambda: scr.session and scr.session.mark_saved())  # 실패해도 닫을 때 저장 질문 창이 뜨지 않게
        self.settle(win)
        before = self.counts(scr.chip_stats.text())
        g = scr.info["graph"]["structure"]
        self.assertEqual(before[:2], (g["node_count"], g["edge_count"]), "저장본 칩은 그래프 기준")
        node = next(n for n in scr.info["corrected"]["nodes"] if n.get("tag") == "RC-TE110")
        scr.on_node({"local_id": node["local_id"], "entity_id": None})
        with mock.patch.object(viewer, "notify"):
            scr._delete()
        self.settle(win)
        text = scr.chip_stats.text()
        self.assertIn("저장 전", text)
        after = self.counts(text)
        g2 = scr.info["graph"]["structure"]
        self.assertEqual(after[:2], (g2["node_count"], g2["edge_count"]), "저장 전에도 같은 기준(고친 내용으로 만든 그래프)")
        self.assertTrue(1 <= before[0] - after[0] <= 3, (before, after))


class StudyButtonRowTest(DisplayBase):
    """결함 6: ④ 오른쪽 패널의 단추 글자가 잘리지 않는다."""

    def test_panel_buttons_fit_at_both_sizes(self):
        from PySide6.QtWidgets import QAbstractButton
        for label, size in SIZES.items():
            with self.subTest(label):
                win = self.window(size)
                win.go(STUDY)
                scr = win.screens[STUDY]
                scr.select_drawing(self.names[1])
                self.assertEqual(scr.stack.currentIndex(), 1)
                scr.select_node(scr.node_set["nodes"][0]["node_id"])
                scr.merge_btn.setText("병합 99 M")  # 체크한 구간 수가 두 자리일 때 가장 긴 글자
                pump(seconds=0.2)
                for b in (scr.merge_btn, scr.split_btn, scr.rename_btn, scr.screen_btn, scr.to_results_btn):
                    self.assertIsInstance(b, QAbstractButton)
                    self.assertGreaterEqual(b.width(), b.sizeHint().width(), "%s 글자가 잘림(%d < %d)"
                                            % (b.text(), b.width(), b.sizeHint().width()))
                    right = b.mapTo(scr.panel, b.rect().topRight()).x()
                    self.assertLessEqual(right, scr.panel.width(), "%s가 패널 밖" % b.text())
                win.close()


class WebviewLayoutTest(DisplayBase):
    """결함 11·14: 찾기 상자·칩·구간 색 줄이 서로 겹치지 않고, 태그 글자가 그 위로 올라오거나 서로 겹치지 않는다."""

    def audit(self, win):
        return json.loads(self.js(win, AUDIT_JS))

    def check(self, win, where):
        got = self.audit(win)
        self.assertGreater(got["tags"], 0, "%s: 태그 글자 층이 그려지지 않음" % where)
        self.assertEqual(got["floats"], [], "%s: 떠 있는 칸끼리 겹침" % where)
        self.assertEqual(got["under"], [], "%s: 태그 글자가 떠 있는 칸 밑에 깔림" % where)
        self.assertEqual(got["covered"], [], "%s: 떠 있는 칸을 다른 요소가 덮음" % where)
        self.assertEqual(got["overlaps"], [], "%s: 글자 겹침" % where)

    def test_extract_view(self):
        for label, size in SIZES.items():
            win = self.window(size)
            win.go(EXTRACT)
            scr = win.screens[EXTRACT]
            for name in self.names:
                with self.subTest(label=label, drawing=name):
                    scr.select_drawing(name)
                    self.settle(win)
                    self.check(win, "② %s %s" % (name, label))
            win.close()

    def test_study_view(self):
        for label, size in SIZES.items():
            win = self.window(size)
            win.go(STUDY)
            scr = win.screens[STUDY]
            for name in self.names:
                with self.subTest(label=label, drawing=name):
                    scr.select_drawing(name)
                    self.settle(win)
                    scr.select_node(scr.node_set["nodes"][0]["node_id"])
                    pump(seconds=0.4)
                    self.check(win, "④ %s %s" % (name, label))
            win.close()

    def test_narrow_viewport_moves_the_search_box_below_the_chips(self):
        win = self.window(SIZES["1366x768 100%"])
        win.go(EXTRACT)
        scr = win.screens[EXTRACT]
        scr.select_drawing(self.names[1])
        self.settle(win)
        scr.edit_btn.setChecked(True)  # 편집 패널이 열려 도면 칸이 좁아진다
        self.settle(win)
        win.resize(1100, 700)
        pump(seconds=0.6)
        self.assertEqual(self.audit(win)["floats"], [])


if __name__ == "__main__":
    unittest.main()
