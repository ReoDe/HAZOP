"""새 웹 화면 3단계 ⑥ 초기사건의 엔진 쪽(hazop/shell/api_ie.py). 실행: python -m unittest tests.test_shell_ie

실제 인계 묶음 계산(hazop.ie.bundle)과 초기사건 저장(hazop.ie.store)을 임시 작업 루트에서 부른다. 읽기는 파일을 쓰지 않고, 쓰기는 읽은 지문(ver)을 대조하며
확정자는 설정의 검토자 이름이다. 표본: tests.test_ie_bundle.ie_sample().
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hazop.ie import model  # noqa: E402
from hazop.ie import store as ie_store  # noqa: E402
from hazop.shell import api  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_ie_bundle import ie_sample  # noqa: E402
from tests.test_study_export import DEVS as XDEVS  # noqa: E402

AT = "2026-11-13T01:00:00Z"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-shellie-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from hazop.app import project_ctx
        self.r, self.ns, self.pg = ie_sample()
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp}),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(XDEVS)),
                  mock.patch.object(project_ctx, "project_graph", lambda pid: self.pg),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        sn.save(self.ns)
        res.save(self.r, self.ns.get("project_id"))
        self.project = self.ns.get("project_id")
        self.events = []
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events.append)
        self.engine.settings.update(project_id=self.project, reviewer_name="검토자A")

    def read(self, *parts):
        r = api.ReadApi(self.engine).read(list(parts), {})
        self.assertIsNotNone(r, parts)
        return json.loads(r.body.decode("utf-8"))

    def call(self, name, args=None):
        return self.engine.dispatch(name, args or {})

    def ver(self):
        return self.read("ie")["ver"]

    def human_group(self):
        """사람이 만든 그룹 하나(c1)를 저장해 두고 그 ID를 돌려준다."""
        doc, fp = ie_store.load(self.project)
        doc = model.sync(doc, self.r, at=AT, node_set=self.ns)
        iec = model.iec_of(doc)[model.key_of(self.r["graph_id"], "c1")]
        doc, gid = model.create_group(doc, "주급수 상실", [iec], at=AT)
        ie_store.save(doc, expect=fp)
        return gid


class ReadTest(Base):
    def test_summary_has_numbers_unassigned_completeness_and_warnings(self):
        s = self.read("ie")
        self.assertTrue(s["available"], s)
        k = s["kpi"]
        self.assertGreater(k["candidates"], 0)
        self.assertEqual((k["groups"], k["unassigned"]), (0, k["candidates"]))
        self.assertEqual(len(s["completeness"]), k["categories"])
        self.assertGreaterEqual(k["gaps"], 1)
        self.assertEqual(len(s["warnings"]), k["warnings"])
        self.assertEqual(s["ver"], "none")

    def test_reads_write_nothing(self):
        self.read("ie")
        self.assertFalse(os.path.exists(ie_store.store_path(self.project)), "읽기는 초기사건 파일을 만들지 않는다")

    def test_unavailable_reasons(self):
        from hazop.app import project_ctx
        with mock.patch.object(project_ctx, "project_graph", side_effect=OSError("x")):
            s = self.read("ie")
        self.assertFalse(s["available"])
        self.assertTrue(s["reason"])
        os.remove(sn.store_path(self.project, self.ns["graph_id"]))
        s = self.read("ie")
        self.assertFalse(s["available"], s)

    def test_group_detail_and_404(self):
        gid = self.human_group()
        s = self.read("ie")
        self.assertEqual([g["group_id"] for g in s["groups"]], [gid])
        d = self.read("ie", "group", gid)
        self.assertEqual(d["group"]["name"], "주급수 상실")
        self.assertEqual(len(d["members"]), 1)
        self.assertIsNone(api.ReadApi(self.engine).read(["ie", "group", "IEG-99"], {}))
        self.assertEqual(s["kpi"]["unassigned"], s["kpi"]["candidates"] - 1)


class WriteTest(Base):
    def test_suggest_makes_draft_groups_and_twice_adds_nothing(self):
        r = self.call("ie.suggest", {"ver": "none"})
        self.assertTrue(r["ok"], r)
        s = self.read("ie")
        self.assertGreater(s["kpi"]["groups"], 0)
        self.assertEqual({g["status"] for g in s["groups"]}, {"draft"}, "초안만 만들고 확정하지 않는다")
        ver, count = s["ver"], s["kpi"]["groups"]
        r2 = self.call("ie.suggest", {"ver": ver})
        self.assertTrue(r2["ok"], r2)
        self.assertEqual(self.read("ie")["kpi"]["groups"], count)
        self.assertTrue([e for e in self.events if e.get("topic") == "ie"])

    def test_confirm_uses_the_reviewer_name_and_reopen_unconfirms(self):
        gid = self.human_group()
        r = self.call("ie.confirm", {"group_id": gid, "ver": self.ver()})
        self.assertTrue(r["ok"], r)
        g = self.read("ie")["groups"][0]
        self.assertEqual((g["status"], g["confirmed_by"]), ("confirmed", "검토자A"))
        r = self.call("ie.reopen", {"group_id": gid, "ver": self.ver()})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.read("ie")["groups"][0]["status"], "draft")

    def test_confirm_refuses_with_the_engines_reason(self):
        self.call("ie.suggest", {"ver": "none"})
        gid = self.read("ie")["groups"][0]["group_id"]
        r = self.call("ie.confirm", {"group_id": gid, "ver": self.ver()})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "failed"), r)
        self.assertTrue(r["error"]["message"])
        self.assertEqual(self.read("ie")["groups"][0]["status"], "draft")

    def test_ver_none_is_refused_when_the_file_exists_and_accepted_when_it_does_not(self):
        r = self.call("ie.suggest", {"ver": "none"})          # 파일이 없을 때: 통과
        self.assertTrue(r["ok"], r)
        self.assertNotEqual(self.ver(), "none")
        r = self.call("ie.suggest", {"ver": "none"})          # 이제 파일이 있다: 낡은 화면의 'none'은 거절
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), r)

    def test_stale_version_and_missing_reviewer_write_nothing(self):
        gid = self.human_group()
        old = self.ver()
        self.assertTrue(self.call("ie.confirm", {"group_id": gid, "ver": old})["ok"])
        r = self.call("ie.reopen", {"group_id": gid, "ver": old})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), r)
        self.assertEqual(self.read("ie")["groups"][0]["status"], "confirmed", "낡은 화면의 명령은 아무것도 바꾸지 않는다")
        self.engine.settings["reviewer_name"] = ""
        r = self.call("ie.reopen", {"group_id": gid, "ver": self.ver()})
        self.assertEqual(r["error"]["code"], "bad_args")
        r = self.call("ie.reopen", {"group_id": gid, "ver": self.ver(), "by": "가짜"})
        self.assertEqual(r["error"]["code"], "bad_args", "by는 웹 인자가 아니다")


if __name__ == "__main__":
    unittest.main()
