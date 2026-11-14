"""B2 검토 재현: 확정 그룹의 후보가 있는 구간을 '분석에서 제외'하면 그룹 구성원과 인계 묶음 후보가 같은 기준을 써야 한다.
실행: python -m unittest tests.test_ie_excluded_node

제외한 구간의 승인 항목은 묶음 후보(bundle.approved_entries)에서 빠진다. 그룹도 그 후보를 구성원으로 두지 않고(묶음에 없는 IEC를
가리키지 않음), 확정 근거가 사라졌으니 '확정'으로 넘기지 않는다. 구간 집합은 저장본을 읽어 메모리에서만 바꾼다(구간 명령은
바뀌는 중이라 기대지 않음). 임시 작업 루트만 쓴다.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.ie import bundle, model  # noqa: E402
from hazop.study import nodes  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_shell_node_screen import Base  # noqa: E402
from tests.test_study_results import entry  # noqa: E402

NOW = "2026-11-14T00:00:00Z"


class ExcludedNodeGroupTest(Base):
    def _confirmed_group(self):
        nid = self.confirmed_node()
        ns = nodes.load(self.pg)
        doc, fp = res.load_fp(ns)
        doc = doc or res.empty_results(ns, res.load_deviations())
        cell = next(c for c in doc["cells"] if c["node_id"] == nid)
        e = entry("e1", status="approved")
        e["ie_hint"] = {"origin": "human", "candidate": "yes", "disturbs": "yes", "challenges": "yes", "category": None,
                        "safety_functions": [], "reason": "", "status": "confirmed"}
        cell["entries"], cell["state"] = [e], "analyzed"
        res.save_fp(doc, ns["project_id"], expect=fp)
        ns = nodes.load(self.pg)
        doc = res.load_fp(ns)[0]
        ie = model.sync(model.empty(ns["project_id"]), doc, node_set=ns)
        iec = next(iter(ie["candidates"]))
        ie, gid = model.create_group(ie, "그룹 가", [iec])
        ie = model.confirm(ie, gid, doc, "검토자", node_set=ns)
        b0 = bundle.build_bundle(doc, ns, self.pg, ie, NOW)
        self.assertEqual([g["members"] for g in b0["groups"]], [[iec]])
        self.assertEqual(b0["groups"][0]["status"], "confirmed")
        return nid, ie, iec, gid

    def _check_left_out(self, ie, iec, gid, ns, doc):
        ie2 = model.sync(ie, doc, node_set=ns)
        b1 = bundle.build_bundle(doc, ns, self.pg, ie2, NOW)
        cand = {c["candidate_id"] for c in b1["candidates"]}
        members = [m for g in b1["groups"] for m in g["members"]]
        self.assertNotIn(iec, cand, "분석에서 빠진 구간의 항목은 후보가 아니다")
        self.assertEqual([m for m in members if m not in cand], [], "그룹이 묶음에 없는 후보 ID를 가리킴")
        self.assertNotEqual(b1["groups"][0]["status"], "confirmed", "확정 근거가 빠진 그룹을 확정으로 넘김")
        self.assertTrue(any(iec in p for p in model.confirm_problems(ie2, gid, doc, node_set=ns)), "그룹 확정 조건에 이유를 보인다")

    def test_old_screen_excluded_node_drops_the_member_and_the_confirmation(self):
        """0.2 집합에 남은 옛 '분석 제외' 판정(검토 재현 repro_b2_bundle: 묶음 후보에서 빠진 IEC를 그룹이 확정으로 가리킴)."""
        nid, ie, iec, gid = self._confirmed_group()
        ns = nodes.load(self.pg)
        doc = res.load_fp(ns)[0]
        next(n for n in ns["nodes"] if n["node_id"] == nid)["screen"] = {"status": "excluded", "by": "human", "reason": "범위 밖"}
        self.assertTrue(nodes.screen_excluded(next(n for n in ns["nodes"] if n["node_id"] == nid)))
        self._check_left_out(ie, iec, gid, ns, doc)

    def test_node_missing_from_the_set_drops_the_member_too(self):
        nid, ie, iec, gid = self._confirmed_group()
        ns = nodes.load(self.pg)
        doc = res.load_fp(ns)[0]
        ns = dict(ns, nodes=[n for n in ns["nodes"] if n["node_id"] != nid])
        self._check_left_out(ie, iec, gid, ns, doc)

    def test_without_a_node_set_nothing_is_dropped(self):
        nid, ie, iec, gid = self._confirmed_group()
        doc = res.load_fp(nodes.load(self.pg))[0]
        f = next(iter(model.entry_facts(doc, None).values()))
        self.assertFalse(f["excluded"], "구간 집합을 모르면(옛 호출) 빼지 않는다")

if __name__ == "__main__":
    unittest.main()
