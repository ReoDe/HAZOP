"""⑤ 관련 지식 표시·③ 이동 테스트 C10 (기획서/그래프활용.md §6.4.3, §6.4.5, §7.2). Qt 오프스크린.
실행: python -m unittest discover -s tests

작업 루트(HAZOP_WORK_ROOT)·저장 루트(HAZOP_STORE_ROOT)·설정 파일은 임시 폴더. 분석 실행은 손으로 쓴 고정 응답
(tests/fixtures/kg_context/responses)으로 임시 폴더에 새로 만든다. 네트워크·실제 AI 호출 없음.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing --log-level=3")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_kg_context as chk  # noqa: E402
from hazop import paths  # noqa: E402
from hazop.analysis import ai, run  # noqa: E402
from hazop.kg import build, context  # noqa: E402
from tests.test_app import pump, tearDownModule  # noqa: E402,F401  (창·웹뷰 정리)

REGION = "region-SNP-M-102-pzr"
D09 = "deviation-p86-d09"


class KgReviewBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hazop-kgreview-")
        cls._env = {k: os.environ.get(k) for k in ("HAZOP_WORK_ROOT", "HAZOP_STORE_ROOT")}
        cls.work = os.path.join(cls.tmp, "work")
        os.environ["HAZOP_WORK_ROOT"] = cls.work
        os.environ["HAZOP_STORE_ROOT"] = os.path.join(cls.tmp, "store")
        cls.graph = chk.sample_graph()
        gdir = os.path.join(cls.work, "출력", "그래프", "SNP-M-102")
        os.makedirs(gdir)
        cls.graph_path = os.path.join(gdir, "graph.json")
        with open(cls.graph_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(cls.graph, fh, ensure_ascii=False)
        os.makedirs(paths.folder_in(cls.work, "구간"))
        shutil.copy(chk.REGION_FILE, paths.folder_in(cls.work, "구간"))
        cls.kg = cls.build_kg(chk.sample_knowledge())
        cls.runs = {"kg": cls.make_run("kg", chk.KG_REF),
                    "nokg": cls.make_run("nokg", None, chk.FIXED_DIR)}
        with mock.patch.dict(context.LIMITS, {"max_items": 4}):
            cls.runs["trunc"] = cls.make_run("trunc", chk.KG_REF)
        zero = chk.sample_knowledge()
        zero["links"] = [l for l in zero["links"] if l["kind"] in ("part_of", "specified_in") or l["id"] == "krel-015"]
        cls.build_kg(zero, "kg-ZERO")
        cls.runs["zero"] = cls.make_run("zero", "출력/지식그래프/kg-ZERO")
        # 잠긴 실행(결과 검증 blocked → 편집·저장 막힘): kg 실행 사본
        locked = os.path.join(os.path.dirname(cls.runs["kg"]), "analysis-kg-locked")
        shutil.copytree(cls.runs["kg"], locked)
        doc = chk.load(os.path.join(locked, "analysis.json"))
        doc["validation"]["status"] = "blocked"
        run._write(os.path.join(locked, "analysis.json"), doc)
        cls.runs["locked"] = locked
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def build_kg(cls, knowledge, kg_id=chk.KG_ID):
        knowledge["kg_id"] = kg_id
        kg = build.build_kg(knowledge, [cls.graph])
        build.write_outputs(os.path.join(cls.work, "출력", "지식그래프", kg_id), knowledge, kg)
        return kg

    @classmethod
    def make_run(cls, name, kg_ref, responses=chk.KG_RESPONSES):
        region = chk.load(chk.REGION_FILE)
        if kg_ref:
            region["inputs"]["knowledge_graph"] = kg_ref
        rp = os.path.join(cls.tmp, "region-%s.json" % name)
        with open(rp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(region, fh, ensure_ascii=False)
        ins = run.load_inputs(rp, cls.work, graph_path=cls.graph_path, resource_root=REPO_ROOT)
        _, run_dir = run.execute(ins, ai.FixedResponseClient(responses), os.path.join(cls.work, "출력", "분석"),
                                 run_id="analysis-kg-%s" % name, now=chk.now)
        return run_dir

    def setUp(self):
        os.environ["HAZOP_STORE_ROOT"] = tempfile.mkdtemp(prefix="store-", dir=self.tmp)
        self.settings = os.path.join(tempfile.mkdtemp(prefix="settings-", dir=self.tmp), "settings.json")

    def open_review(self, key="kg", cid=D09):
        from hazop.app.main_window import MainWindow
        win = MainWindow(settings_path=self.settings, ask_reviewer=False)
        self.addCleanup(win.deleteLater)
        self.addCleanup(win.close)
        win.resize(1440, 860)
        win.set_reviewer_name("검토자A")
        self.assertTrue(win.open_run(self.runs[key]))
        win.go(3)
        scr = win.screens[3]
        scr.select_candidate(cid)
        self.assertEqual(scr.cid, cid)
        return win, scr

    def html(self, form):
        return form.knowledge.view.toHtml() if form.knowledge.view else ""

    def plain(self, form):
        return form.knowledge.view.toPlainText() if form.knowledge.view else ""


class RelatedKnowledgeTest(KgReviewBase):
    def test_items_and_citation_badges_per_scenario(self):
        """(a)(b) 시나리오별 대상 규칙, 사실 인용은 모든 시나리오의 req-001, 시나리오 인용은 인용한 시나리오의 cond-001만."""
        from hazop.app import data
        win, scr = self.open_review()
        self.assertTrue(scr.sforms)
        cited = 0
        for sid, f in scr.sforms.items():
            rk = data.related_knowledge(scr.ctx.doc, f.s)
            self.assertFalse(f.knowledge.view.isVisibleTo(f))           # 기본 접힘
            f.knowledge.toggle.setChecked(True)
            self.assertTrue(f.knowledge.view.isVisibleTo(f))
            text = self.plain(f)
            self.assertEqual(f.knowledge.toggle.text().split(" ")[3], "%d건" % len(rk["items"]))
            req = next(r for r in rk["items"] if r["item"]["knowledge_id"] == "req-001")
            self.assertIn("사실 인용", [t for t, _ in req["badges"]])
            self.assertIn("사실 인용", text)
            ai_ = f.s.get("ai_interpretation") or {}
            cites = "ev-kg-cond-001" in f.s["graph_evidence"]["evidence_ids"] + (ai_.get("evidence_ids") or [])
            cond = next((r for r in rk["items"] if r["item"]["knowledge_id"] == "cond-001"), None)
            self.assertEqual(bool(cond and cond["scenario_cited"]), cites, sid)
            self.assertEqual("시나리오 인용" in text, cites, sid)
            cited += cites
        self.assertEqual(cited, 2)

    def test_conflict_and_node_classes(self):
        """(c) 충돌, (d) 적용 근거 공백·분석 범위 제외 문구, 같은 버전 칩."""
        win, scr = self.open_review()
        texts = " ".join(self.plain(f) for f in scr.sforms.values())
        self.assertIn("충돌", texts)
        self.assertIn("(값 선택 유보)", texts)
        self.assertIn("RC-PV101: 적용 근거 공백 — 문서 언급만 있음", texts)
        self.assertIn("RC-PSV101: 분석 범위 제외 1건(가설·미확인 등)", texts)
        self.assertNotIn("상한으로 생략", texts)
        self.assertTrue(scr.chip_kg.isVisibleTo(scr))
        self.assertEqual(scr.chip_kg.text(), "지식 %s" % self.kg["kg_version"])
        self.assertTrue(scr.banner_kg.isHidden())

    def test_truncated_run(self):
        """(c) C5(f) 충돌(상대 미포함: 상한), (d) 상한으로 생략, 생략 표시."""
        win, scr = self.open_review("trunc")
        texts = " ".join(self.plain(f) for f in scr.sforms.values())
        self.assertIn("충돌(상대 미포함: 상한)", texts)
        self.assertIn("상한으로 생략", texts)
        self.assertIn("지식 맥락: 항목 6개 중 4개만 분석에 사용(항목 수 상한)", texts)

    def test_no_knowledge_input_run(self):
        """(d) C2-0: 지식 입력 없음."""
        win, scr = self.open_review("zero")
        texts = " ".join(self.plain(f) for f in scr.sforms.values())
        self.assertIn("RC-PZ01: 지식 입력 없음", texts)
        self.assertIn("관련 지식 항목 없음", texts)

    def test_locked_run_still_shows_knowledge(self):
        """잠긴 실행: 검토 입력은 막히지만 관련 지식 펼치기·③에서 보기는 된다(재작업 지적 7)."""
        win, scr = self.open_review("locked")
        self.assertFalse(scr.ctx.editable(D09)["editable"])
        self.assertFalse(scr.btn_save.isEnabled())
        f = next(iter(scr.sforms.values()))
        for w in (f.radios, f.reason, f.rev_box, f.risk_box, f.prior):
            self.assertFalse(w.isEnabled(), w)
        self.assertTrue(f.knowledge.toggle.isEnabled() and f.knowledge.view.isEnabled())
        f.knowledge.toggle.click()
        self.assertTrue(f.knowledge.view.isVisibleTo(f))
        self.assertTrue(scr.open_in_knowledge("entity-node-009"))
        self.assertEqual(win.stack.currentIndex(), 4)

    def test_unused_run_line(self):
        """(e) 지식 미사용: 관련 지식 자리에 한 줄, 칩·띠 없음."""
        from hazop.app import runctx
        win, scr = self.open_review("nokg")
        for f in scr.sforms.values():
            self.assertIsNone(f.knowledge.view)
            labels = [w.text() for w in f.knowledge.findChildren(type(scr.run_label))]
            self.assertIn(runctx.KG_UNUSED, labels)
        self.assertFalse(scr.chip_kg.isVisibleTo(scr))
        self.assertTrue(scr.banner_kg.isHidden())
        self.assertFalse(scr.open_in_knowledge("entity-node-001"))


class KnowledgeNavigationTest(KgReviewBase):
    """(f) ③에서 보기, (e) 바뀜·읽기 불가 띠."""

    def record(self, win):
        sent = []
        real = win.webview.bridge.send

        def spy(msg_type, **payload):
            sent.append((msg_type, payload))
            return real(msg_type, **payload)
        win.webview.bridge.send = spy
        return sent

    def web_state(self, win, want_sel, want_version):
        """웹(③ 그래프 화면)의 hzKG.state()에서 선택 노드와 kg_version을 읽는다. 조건을 만족하면 그 상태, 아니면 마지막 상태."""
        from tests.test_app import wait_for
        got = []

        def ok():
            if not win.webview.bridge.is_ready:
                return False
            win.webview.page().runJavaScript("JSON.stringify(window.hzKG ? window.hzKG.state() : null)", 0, got.append)
            st = json.loads(got[-1]) if got and got[-1] else None
            return bool(st) and (st.get("sel") or {}).get("id") == want_sel and st.get("kg_version") == want_version
        wait_for(ok, 30)
        return json.loads(got[-1]) if got and got[-1] else None

    def test_1_same_version_selects_node_after_load(self):
        win, scr = self.open_review()
        win.show()
        sent = self.record(win)
        self.assertTrue(scr.open_in_knowledge("entity-node-009"))
        self.assertEqual(win.stack.currentIndex(), 4)
        types = [t for t, _ in sent]
        self.assertIn("loadKnowledge", types)
        self.assertEqual(sent[-1], ("selectNode", {"id": "entity-node-009"}))
        self.assertLess(max(i for i, t in enumerate(types) if t == "loadKnowledge"), types.index("selectNode"))
        self.assertEqual(win.screens[4].kg["kg_version"], self.kg["kg_version"])
        st = self.web_state(win, "entity-node-009", self.kg["kg_version"])   # 웹 쪽 실제 선택 상태
        self.assertEqual(((st or {}).get("sel") or {}).get("id"), "entity-node-009", st)
        self.assertEqual((st or {}).get("kg_version"), self.kg["kg_version"], st)
        self.assertIn("kg:entity-node-001", self.html(next(iter(scr.sforms.values()))))

    def test_3_blocked_latest_goes_to_previous_passed(self):
        """최신 버전이 blocked이고 직전 passed 버전이 기록 kg_version이면 ③ '이전 버전'으로 열고 노드를 선택한다."""
        root = os.path.join(self.work, "출력", "지식그래프", chk.KG_ID)
        blocked = chk.sample_knowledge()
        blocked["nodes"].append(dict(chk.node(blocked, "req-003")))  # 중복 ID -> blocked
        bkg = self.build_kg(blocked)
        self.assertEqual(bkg["validation"]["status"], "blocked")
        os.utime(os.path.join(root, self.kg["kg_version"]))  # 이전 passed 버전 = 기록 버전(폴더 수정 시각 기준)
        try:
            win, scr = self.open_review()
            win.show()
            self.assertEqual(scr.ctx.kg["state"], "changed")
            sent = self.record(win)
            self.assertTrue(scr.open_in_knowledge("entity-node-009"))
            ks = win.screens[4]
            self.assertTrue(ks.showing_prev)
            self.assertEqual(ks.kg["kg_version"], self.kg["kg_version"])
            self.assertEqual(sent[-1], ("selectNode", {"id": "entity-node-009"}))
            st = self.web_state(win, "entity-node-009", self.kg["kg_version"])
            self.assertEqual(((st or {}).get("sel") or {}).get("id"), "entity-node-009", st)
        finally:
            build.write_outputs(root, chk.sample_knowledge() | {"kg_id": chk.KG_ID}, self.kg)

    def test_2_changed_then_unreadable(self):
        """기록 kg_version과 ③ 버전이 다르면 이동만(selectNode 없음), 읽기 불가면 버튼(링크) 끔."""
        know = chk.sample_knowledge()
        chk.node(know, "cond-001")["value"] = "7.5"
        kg2 = self.build_kg(know)
        root = os.path.join(self.work, "출력", "지식그래프", chk.KG_ID)
        ptr_path = os.path.join(root, build.POINTER_FILE)
        try:
            win, scr = self.open_review()
            self.assertTrue(scr.chip_kg.isHidden())
            self.assertIn("분석 당시 지식그래프 %s, 현재 %s" % (self.kg["kg_version"], kg2["kg_version"]),
                          scr.banner_kg.label.text())
            sent = self.record(win)
            self.assertFalse(scr.open_in_knowledge("entity-node-009"))
            self.assertEqual(win.stack.currentIndex(), 4)
            self.assertNotIn("selectNode", [t for t, _ in sent])
            self.assertIn("분석 당시와 다른 버전", win.msg_label.text())
            # 읽기 불가
            with open(ptr_path, encoding="utf-8") as fh:
                ptr = json.load(fh)
            with open(ptr_path, "w", encoding="utf-8") as fh:
                json.dump({k: v for k, v in ptr.items() if k != "knowledge_sha256"}, fh)
            win2, scr2 = self.open_review()
            self.assertIn("현재 지식그래프를 읽을 수 없음", scr2.banner_kg.label.text())
            f = next(iter(scr2.sforms.values()))
            self.assertNotIn("kg:", self.html(f))
            self.assertIn("③에서 보기(현재 지식그래프 읽기 불가)", self.plain(f))
            sent2 = self.record(win2)
            self.assertFalse(scr2.open_in_knowledge("entity-node-009"))
            self.assertEqual(win2.stack.currentIndex(), 3)
            self.assertEqual(sent2, [])
        finally:
            build.write_outputs(root, chk.sample_knowledge() | {"kg_id": chk.KG_ID}, self.kg)  # 다음 테스트를 위해 되돌림


if __name__ == "__main__":
    unittest.main()
