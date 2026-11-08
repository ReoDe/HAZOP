"""M4: 잠재 후보(기대 패턴) 규칙 E01~E08, 상태 전이, 판단 저장·재실행 유지, 판 변경 재확인, 계산 제외, M0 확장성 공백,
M4 검토 지적(근거 경로 차단, 후보 내용 재확인, 손상 판단 기록, ID 충돌, 압력 기준, 기각·무관 재확인, 판단 되돌리기, 오류 격리).

근거: 기획서/지식그래프-스키마.md KD6·§4·§8.2 M4·§8.3, 지식그래프-스키마-입력.md §2, 지식그래프-스키마-사전.md §2.4·§3.4.
판단 파일은 임시 폴더에만 쓴다. 그래프는 시험용 가상 도면(실제 설계자료 아님)과 샘플 SNP-M-102다.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import test_kg  # noqa: E402
import test_kg_origin  # noqa: E402
from hazop.app import tokens  # noqa: E402
from hazop.kg import algo, build, expect, schema, screen  # noqa: E402
from hazop.kg.schema import REGISTRY  # noqa: E402
from hazop.study import ai_cells  # noqa: E402

GID = "graph-T-001"


def _obj(eid, kind, cat, tag, soid, **kw):
    n = {"entity_id": eid, "node_type": "drawing_object", "kind": kind, "category": cat, "tag": tag,
         "source_object_id": soid, "attributes": {}, "origin": "pid_extract"}
    n.update(kw)
    return n


def _seg(eid, soid, fd=None):
    return {"entity_id": eid, "node_type": "pipe_segment", "kind": "pipe_segment", "category": "pipe_segment",
            "tag": None, "source_object_id": soid, "attributes": {}, "flow_direction": fd}


def _ends(seg, a, b):
    return [{"entity_id": "r-%s-%s" % (seg, a), "kind": "has_endpoint", "nodes": [seg, a], "segment": seg, "node": a},
            {"entity_id": "r-%s-%s" % (seg, b), "kind": "has_endpoint", "nodes": [seg, b], "segment": seg, "node": b}]


def graph():
    """가상 도면: 펌프 P-1 → 체크밸브 CV-1(흐름 확인) → 탱크 TK-1(수위 LT-1, 안전밸브 PSV-1), 제어 루프 PT-1→PIC-1→FCV-1,
    전동 밸브 MOV-1(고장 위치 없음), 압력 스위치 PSH-1(기능 S), 펌프 P-2(체크밸브 없음)."""
    nodes = [
        _obj("e-p1", "pump", "equipment", "P-1", "o-p1"),
        _obj("e-cv1", "check_valve", "valve", "CV-1", "o-cv1"),
        _obj("e-tk1", "tank", "equipment", "TK-1", "o-tk1", attributes={"design_pressure_max": "1.0 MPa(g)"}),
        _obj("e-psv1", "psv", "valve", "PSV-1", "o-psv1", attributes={"set_pressure": "0.9 MPa(g)", "normal_position": "NC"}),
        _obj("e-lt1", "transmitter", "instrument", "LT-1", "o-lt1", isa={"measured_variable": "L", "functions": "T"}),
        _obj("e-pt1", "transmitter", "instrument", "PT-1", "o-pt1", isa={"measured_variable": "P", "functions": "T"}),
        _obj("e-pic1", "controller", "instrument", "PIC-1", "o-pic1", isa={"measured_variable": "P", "functions": "IC"}),
        _obj("e-fcv1", "control_valve", "valve", "FCV-1", "o-fcv1", attributes={"fail_position": "FC"}),
        _obj("e-mov1", "motor_operated_valve", "valve", "MOV-1", "o-mov1"),
        _obj("e-psh1", "switch", "instrument", "PSH-1", "o-psh1", isa={"measured_variable": "P", "functions": "SH"}),
        _obj("e-p2", "pump", "equipment", "P-2", "o-p2"),
        _seg("s1", "o-s1", {"from": "e-p1", "to": "e-cv1"}), _seg("s2", "o-s2"), _seg("s3", "o-s3"),
        _seg("s4", "o-s4"), _seg("s5", "o-s5"),
    ]
    edges = (_ends("s1", "e-p1", "e-cv1") + _ends("s2", "e-cv1", "e-tk1") + _ends("s3", "e-tk1", "e-psv1")
             + _ends("s4", "e-tk1", "e-mov1") + _ends("s5", "e-mov1", "e-p2"))
    edges += [{"entity_id": "m1", "kind": "measurement_connection", "nodes": ["e-tk1", "e-lt1"]},
              {"entity_id": "g1", "kind": "signal_connection", "nodes": ["e-pt1", "e-pic1"]},
              {"entity_id": "g2", "kind": "signal_connection", "nodes": ["e-pic1", "e-fcv1"]}]
    return {"graph_id": GID, "graph_version": "v-000000000001", "nodes": nodes, "edges": edges,
            "validation": {"status": "passed"}}


def kg():
    """지식그래프 일부: MOV-1 depends_on(후보), PSH-1 has_setpoint, FCV-1 depends_on(기각 → 세지 않음)."""
    def pid(soid):
        return {"layer": "pid", "graph_id": GID, "source_object_id": soid, "entity_id": None}
    return {"kg_version": "v-00000000000k", "claims": [],
            "nodes": [{"id": "setpt-1", "node_type": "setpoint", "item": "고압 트립", "value": "8", "unit": "bar",
                       "pressure_basis": "gauge", "knowledge_status": "confirmed"}],
            "links": [
        {"id": "krel-1", "kind": "depends_on", "link_status": "candidate",
         "ends": {"from": pid("o-mov1"), "to": {"layer": "knowledge", "ref": "req-air"}}},
        {"id": "krel-2", "kind": "has_setpoint", "link_status": "confirmed",
         "ends": {"from": pid("o-psh1"), "to": {"layer": "knowledge", "ref": "setpt-1"}}},
        {"id": "krel-3", "kind": "depends_on", "link_status": "rejected",
         "ends": {"from": pid("o-fcv1"), "to": {"layer": "knowledge", "ref": "req-air"}}}]}


def item(res, rule, tag):
    return next(i for i in res["items"] if i["rule_id"] == rule and i["target_tag"] == tag)


class RulesTableTest(unittest.TestCase):
    def test_shipped_rules_e01_e08(self):
        self.assertEqual(expect.validate_rules(copy.deepcopy(expect.RULES.data)), [])
        self.assertEqual([r["id"] for r in expect.RULES.rules], ["E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08"])
        for r in expect.RULES.rules:
            self.assertGreaterEqual(r["version"], 1)
            self.assertIn(r["basis_level"], expect.RULES.levels)
            self.assertTrue(r["basis_ko"] and r["label_ko"] and r["hazop_ko"])
        self.assertEqual(expect.RULES.levels["general"], "[일반지식]")
        self.assertEqual(expect.RULES.by_id["E01"]["label_ko"], "펌프 출구 역류 방지 체크밸브")

    def test_bad_rules_are_rejected(self):
        cases = [
            (lambda d: d["rules"][0]["target"].update(classes=["no_class"]), "없는 클래스"),
            (lambda d: d["rules"][0]["check"].update(relations=["governed_by"]), "pid 층 관계가 아님"),
            (lambda d: d["rules"][4]["check"].update(relations=["has_endpoint"]), "knowledge 층 관계가 아님"),
            (lambda d: d["rules"][0].update(basis_level="guess"), "근거 수준"),
            (lambda d: d["rules"][0].update(version=0), "version"),
            (lambda d: d["rules"][0]["check"].update(type="magic"), "check.type"),
            (lambda d: d["rules"].append(copy.deepcopy(d["rules"][0])), "id 중복"),
            (lambda d: d["rules"][3]["check"].update(properties=["colour"]), "properties"),
        ]
        for mutate, needle in cases:
            with self.subTest(needle=needle):
                d = copy.deepcopy(expect.RULES.data)
                mutate(d)
                probs = expect.validate_rules(d)
                self.assertTrue(any(needle in p for p in probs), probs)
                with self.assertRaises(expect.ExpectError):
                    expect.Rules(d)


class RuleTest(unittest.TestCase):
    def setUp(self):
        self.res = expect.evaluate(graph(), kg())

    def test_e01_check_valve_downstream_marked(self):
        i = item(self.res, "E01", "P-1")
        self.assertEqual(i["state"], "candidate_found")
        self.assertEqual([(f["tag"], f["direction"], f["hops"]) for f in i["found"]], [("CV-1", "하류", 1)])
        self.assertEqual(item(self.res, "E01", "P-2")["state"], "expected")  # P-2 → MOV-1 → TK-1(설비에서 멈춤)

    def test_e02_overpressure(self):
        self.assertEqual([f["tag"] for f in item(self.res, "E02", "TK-1")["found"]], ["PSV-1"])

    def test_e03_level(self):
        self.assertEqual([f["tag"] for f in item(self.res, "E03", "TK-1")["found"]], ["LT-1"])

    def test_e04_fail_position(self):
        self.assertEqual(item(self.res, "E04", "FCV-1")["found"][0]["value"], "FC")
        self.assertEqual(item(self.res, "E04", "MOV-1")["state"], "expected")

    def test_e05_dependency_ignores_rejected_link(self):
        self.assertEqual(item(self.res, "E05", "MOV-1")["found"][0]["link"], "krel-1")
        self.assertEqual(item(self.res, "E05", "FCV-1")["state"], "expected")

    def test_e06_compare_only_when_units_match(self):
        i = item(self.res, "E06", "PSV-1")
        self.assertEqual(i["state"], "candidate_found")
        self.assertIn("설정압력 0.9 MPa ≤ 설계압력 1.0 MPa(TK-1)", i["note"])
        g = graph()
        next(n for n in g["nodes"] if n["tag"] == "TK-1")["attributes"]["design_pressure_max"] = "10 bar(g)"
        self.assertIn("비교 안 함", item(expect.evaluate(g), "E06", "PSV-1")["note"])

    def test_e06_no_compare_when_one_basis_unknown(self):
        for tag, prop, text in (("TK-1", "design_pressure_max", "1.0 MPa"), ("PSV-1", "set_pressure", "0.9 MPa")):
            with self.subTest(tag=tag):
                g = graph()
                next(n for n in g["nodes"] if n["tag"] == tag)["attributes"][prop] = text  # 압력 기준 미확인
                i = item(expect.evaluate(g), "E06", "PSV-1")
                self.assertIn("비교 안 함", i["note"])
                self.assertNotIn("≤", i["note"])
                self.assertEqual(i["state"], "candidate_found")  # 두 값이 있으면 후보 발견은 그대로

    def test_e07_targets_only_alarm_or_switch(self):
        self.assertEqual(sorted({i["target_tag"] for i in self.res["items"] if i["rule_id"] == "E07"}), ["PSH-1"])
        self.assertEqual(item(self.res, "E07", "PSH-1")["found"][0]["relation"], "has_setpoint")

    def test_e08_loop_needs_both_sides(self):
        self.assertEqual(sorted(f["tag"] for f in item(self.res, "E08", "PIC-1")["found"]), ["FCV-1", "PT-1"])
        g = graph()
        g["edges"] = [e for e in g["edges"] if e["entity_id"] != "g2"]
        i = item(expect.evaluate(g), "E08", "PIC-1")
        self.assertEqual(i["state"], "expected")
        self.assertIn("밸브", i["note"])

    def test_ids_keys_and_determinism(self):
        i = item(self.res, "E01", "P-1")
        self.assertEqual(i["key"], "E01|%s#o-p1" % GID)
        self.assertRegex(i["id"], r"^exp-E01-[0-9a-f]{16}$")
        self.assertEqual(expect.evaluate(graph(), kg()), self.res)

    def test_ids_do_not_collide_and_duplicates_stop(self):
        a, b = expect.expectation_id("E01", "graph-T#o-64159"), expect.expectation_id("E01", "graph-T#o-68217")
        self.assertEqual(a[:16], b[:16])  # 해시 앞 8자가 같은 두 키(옛 ID는 같았음)
        self.assertNotEqual(a, b)
        with mock.patch.object(expect, "expectation_id", lambda rule_id, ref: "exp-%s-same" % rule_id):
            with self.assertRaises(expect.ExpectError) as cm:
                expect.evaluate(graph(), kg())
        self.assertIn("ID 중복", str(cm.exception))

    def test_summary_counts(self):
        s = self.res["summary"]["E01"]
        self.assertEqual((s["targets"], s["candidate_found"], s["not_found"]), (2, 1, 1))


class TransitionTest(unittest.TestCase):
    def test_table_allows_only_listed(self):
        self.assertEqual(expect.human_actions("candidate_found"), ["confirm", "reject"])
        self.assertEqual(expect.human_actions("expected"), ["absent", "not_applicable"])
        for st in ("confirmed_present", "confirmed_absent", "not_applicable"):
            self.assertEqual(expect.human_actions(st), ["undo"])
            self.assertTrue(expect.allowed(st, "expected", "revision"))
        for frm, action in (("expected", "confirm"), ("expected", "reject"), ("candidate_found", "absent"),
                            ("confirmed_absent", "not_applicable"), ("not_applicable", "confirm"),
                            ("expected", "undo"), ("candidate_found", "undo")):
            with self.subTest(frm=frm, action=action):
                with self.assertRaises(expect.ExpectError):
                    expect.transition(frm, action=action)

    def test_required_inputs(self):
        res = expect.evaluate(graph(), kg())
        mov = item(res, "E04", "MOV-1")
        with self.assertRaises(expect.ExpectError):
            expect.apply_action(mov, "absent", "검토자", reason="데이터시트 확인")  # 근거 없음
        with self.assertRaises(expect.ExpectError):
            expect.apply_action(mov, "not_applicable", "검토자")  # 사유 없음
        with self.assertRaises(expect.ExpectError):
            expect.apply_action(mov, "absent", "", reason="r", evidence="e")  # 이름 없음
        with self.assertRaises(expect.ExpectError):
            expect.apply_action(mov, "confirm", "검토자")  # 기대됨에서 확인 불가
        rec = expect.apply_action(mov, "absent", "검토자", reason="데이터시트에 없음", evidence="DS-1 3쪽")
        self.assertEqual((rec["state"], rec["evidence"]), ("confirmed_absent", "DS-1 3쪽"))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "데이터", "잠재후보", "P.json")

    def judge(self, res, rule, tag, action, **kw):
        rec = expect.apply_action(item(res, rule, tag), action, "검토자", at="2026-11-09T00:00:00Z", **kw)
        expect.save_judgement(self.path, "P", rec)
        return expect.load_judgements(self.path, "P")

    def test_judgements_survive_rerun(self):
        res = expect.evaluate(graph(), kg())
        self.judge(res, "E01", "P-1", "confirm")
        self.judge(res, "E04", "MOV-1", "absent", reason="데이터시트에 고장 위치 없음", evidence="DS-MOV-1 2쪽")
        self.judge(res, "E01", "P-2", "not_applicable", reason="정지 상태 예비 펌프")
        self.judge(res, "E02", "TK-1", "reject")
        again = expect.evaluate(graph(), kg(), expect.load_judgements(self.path, "P"))
        self.assertEqual(item(again, "E01", "P-1")["state"], "confirmed_present")
        self.assertEqual(item(again, "E04", "MOV-1")["state"], "confirmed_absent")
        self.assertEqual(item(again, "E01", "P-2")["state"], "not_applicable")
        x = item(again, "E02", "TK-1")
        self.assertEqual((x["state"], x["found"], x["rejected"]), ("expected", [], ["%s#o-psv1" % GID]))
        third = expect.evaluate(graph(), kg(), expect.load_judgements(self.path, "P"))
        self.assertEqual(third, again)  # 멱등
        with open(self.path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["kind"], expect.STORE_KIND)
        self.assertIn("E01|%s#o-p1" % GID, doc["judgements"])

    def test_history_kept_on_rejudge(self):
        res = expect.evaluate(graph(), kg())
        self.judge(res, "E02", "TK-1", "reject")
        res = expect.evaluate(graph(), kg(), expect.load_judgements(self.path, "P"))
        j = self.judge(res, "E02", "TK-1", "absent", reason="도면 범위 밖 확인", evidence="SDD 4.1")
        rec = j["E02|%s#o-tk1" % GID]
        self.assertEqual(rec["state"], "confirmed_absent")
        self.assertEqual([h["state"] for h in rec["history"]], ["expected"])

    def test_revision_rechecks_confirmed_and_absent(self):
        res = expect.evaluate(graph(), kg())
        self.judge(res, "E01", "P-1", "confirm")
        self.judge(res, "E04", "MOV-1", "absent", reason="r", evidence="e")
        self.judge(res, "E01", "P-2", "not_applicable", reason="r")
        self.judge(res, "E02", "TK-1", "reject")
        g = graph()
        for n in g["nodes"]:
            if n["tag"] in ("CV-1", "MOV-1", "P-2", "PSV-1"):
                n["tag"] += "A"  # ② 수정으로 태그가 바뀐 판
        out = expect.evaluate(g, kg(), expect.load_judgements(self.path, "P"))
        p1 = item(out, "E01", "P-1")
        self.assertEqual((p1["state"], p1["recheck"], p1["previous_state"]), ("candidate_found", True, "confirmed_present"))
        mov = item(out, "E04", "MOV-1A")
        self.assertEqual((mov["state"], mov["recheck"], mov["previous_state"]), ("expected", True, "confirmed_absent"))
        p2 = item(out, "E01", "P-2A")
        self.assertEqual((p2["state"], p2["recheck"], p2["previous_state"]), ("expected", True, "not_applicable"))
        tk = item(out, "E02", "TK-1")  # 기각한 후보 PSV-1A가 다시 보이되 재확인 필요로 알림
        self.assertEqual((tk["state"], tk["recheck"], tk["previous_state"]), ("candidate_found", True, "expected"))
        self.assertEqual(expect.previous_label(tk), "후보 기각")
        self.assertEqual(tk["judgement"]["rejected"], ["%s#o-psv1" % GID])
        self.assertEqual(out["summary"]["E02"]["recheck"], 1)
        self.assertEqual(out["orphan_judgements"], [])
        g["nodes"] = [n for n in g["nodes"] if n["tag"] != "MOV-1A"]  # 대상이 도면에서 사라짐
        gone = expect.evaluate(g, kg(), expect.load_judgements(self.path, "P"))
        self.assertEqual(gone["orphan_judgements"], ["E04|%s#o-mov1" % GID])  # 파일에 남고 따로 알림

    def test_rule_version_change_rechecks(self):
        res = expect.evaluate(graph(), kg())
        self.judge(res, "E01", "P-1", "confirm")
        self.judge(res, "E01", "P-2", "not_applicable", reason="r")
        d = copy.deepcopy(expect.RULES.data)
        d["rules"][0]["version"] = 2
        out = expect.evaluate(graph(), kg(), expect.load_judgements(self.path, "P"), expect.Rules(d))
        self.assertTrue(item(out, "E01", "P-1")["recheck"])
        p2 = item(out, "E01", "P-2")
        self.assertEqual((p2["state"], p2["recheck"], p2["previous_state"]), ("expected", True, "not_applicable"))

    def test_satisfier_and_relation_target_change_rechecks(self):
        res = expect.evaluate(graph(), kg())
        self.judge(res, "E01", "P-1", "confirm")
        self.judge(res, "E07", "PSH-1", "confirm")
        g = graph()
        next(n for n in g["nodes"] if n["tag"] == "CV-1")["attributes"]["size"] = "2 in"  # 후보 내용(태그 그대로)
        k = kg()
        k["nodes"][0]["value"] = "9"  # E07 관계 대상(설정치) 값
        out = expect.evaluate(g, k, expect.load_judgements(self.path, "P"))
        for rule, tag in (("E01", "P-1"), ("E07", "PSH-1")):
            with self.subTest(rule=rule):
                x = item(out, rule, tag)
                self.assertEqual((x["state"], x["recheck"], x["previous_state"]),
                                 ("candidate_found", True, "confirmed_present"))
        same = expect.evaluate(graph(), kg(), expect.load_judgements(self.path, "P"))
        self.assertEqual(item(same, "E07", "PSH-1")["state"], "confirmed_present")

    def test_undo_returns_to_auto_state_and_keeps_history(self):
        res = expect.evaluate(graph(), kg())
        self.judge(res, "E01", "P-1", "confirm")
        self.judge(res, "E04", "MOV-1", "absent", reason="r", evidence="e")
        self.judge(res, "E01", "P-2", "not_applicable", reason="r")
        res = expect.evaluate(graph(), kg(), expect.load_judgements(self.path, "P"))
        with self.assertRaises(expect.ExpectError):
            expect.apply_action(item(res, "E01", "P-1"), "undo", " ")  # 판단자 필수
        for rule, tag in (("E01", "P-1"), ("E04", "MOV-1"), ("E01", "P-2")):
            j = self.judge(res, rule, tag, "undo")
        out = expect.evaluate(graph(), kg(), j)
        self.assertEqual(out["bad_judgements"], [])
        self.assertEqual([(item(out, r, t)["state"], item(out, r, t)["recheck"]) for r, t in
                          (("E01", "P-1"), ("E04", "MOV-1"), ("E01", "P-2"))],
                         [("candidate_found", False), ("expected", False), ("expected", False)])
        rec = j["E01|%s#o-p1" % GID]
        self.assertEqual((rec["action"], rec["state"], rec["previous_state"]), ("undo", "expected", "confirmed_present"))
        self.assertEqual([h["action"] for h in rec["history"]], ["confirm"])

    def test_bad_records_skipped_reported_and_kept(self):
        res = expect.evaluate(graph(), kg())
        self.judge(res, "E01", "P-1", "confirm")
        with open(self.path, encoding="utf-8") as fh:
            doc = json.load(fh)
        good = doc["judgements"]["E01|%s#o-p1" % GID]

        def rec(key, **kw):
            return dict(good, key=key, **kw)
        bad = {"E04|%s#o-mov1" % GID: rec("E04|%s#o-mov1" % GID, state="confirmed_absent", action="absent",
                                           reason="r", evidence=None),               # 근거 없음
               "E01|%s#o-p2" % GID: rec("E01|%s#o-p2" % GID, state="not_applicable", action="not_applicable",
                                         reason=" "),                                 # 사유 없음
               "E02|%s#o-tk1" % GID: rec("E02|%s#o-tk1" % GID, by=""),               # 판단자 없음
               "E03|%s#o-tk1" % GID: rec("E03|%s#o-tk1" % GID, action="reject"),     # 확인됨인데 마지막 동작이 기각
               "E07|%s#o-psh1" % GID: rec("E07|%s#o-psh1" % GID, state="candidate_found"),  # 사람이 만들 수 없는 상태
               "E08|%s#o-pic1" % GID: ["깨진 기록"]}
        doc["judgements"].update(bad)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        out = expect.evaluate(graph(), kg(), expect.load_judgements(self.path, "P"))
        self.assertEqual([b["key"] for b in out["bad_judgements"]], sorted(bad))
        self.assertTrue(all(b["problems"] for b in out["bad_judgements"]))
        self.assertEqual(item(out, "E01", "P-1")["state"], "confirmed_present")  # 성한 기록은 적용
        self.assertEqual(item(out, "E04", "MOV-1")["state"], "expected")
        self.assertEqual(item(out, "E03", "TK-1")["state"], "candidate_found")
        self.assertIsNone(item(out, "E03", "TK-1")["judgement"])
        self.assertEqual(out["orphan_judgements"], [])
        j = self.judge(out, "E04", "FCV-1", "confirm")  # 다른 판단을 저장해도 어긋난 기록은 파일에 남음
        for k, v in bad.items():
            self.assertEqual(j[k], v)
        j = self.judge(out, "E04", "MOV-1", "absent", reason="r", evidence="e")  # 같은 키를 다시 판단하면 history로
        self.assertEqual(j["E04|%s#o-mov1" % GID]["history"][-1]["evidence"], None)

    def test_bad_store_is_not_overwritten(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        res = expect.evaluate(graph(), kg())
        with self.assertRaises(expect.ExpectError):
            expect.save_judgement(self.path, "P", expect.apply_action(item(res, "E01", "P-1"), "confirm", "검토자"))
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{broken")
        with self.assertRaises(expect.ExpectError):
            expect.load_judgements(self.path, "P")
        self.assertEqual(expect.load_judgements(os.path.join(self.tmp, "none.json"), "P"), {})

    def test_store_path_under_work_root(self):
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp}):
            self.assertEqual(expect.store_path("SNP-SAMPLE"),
                             os.path.join(self.tmp, "데이터", "잠재후보", "SNP-SAMPLE.json"))


class ExclusionTest(unittest.TestCase):
    """잠재 후보는 사실이 아니다: 그래프·지식그래프 원본, V4·V5, kg_paths에 들어가지 않는다."""

    def test_inputs_not_mutated(self):
        g, k = graph(), kg()
        before = copy.deepcopy((g, k))
        expect.evaluate(g, k)
        self.assertEqual((g, k), before)

    def test_registry_marks_expect_relations_out_of_v4(self):
        for rid in ("expects", "satisfied_by"):
            self.assertFalse(REGISTRY.relations[rid]["v4"])
            self.assertEqual(REGISTRY.relations[rid]["layer"], "expectation")
            self.assertNotIn(rid, build.LINK_TYPES)
        self.assertNotIn("expectation", build.NODE_PREFIX)

    def test_knowledge_input_cannot_carry_expectations(self):
        nodes = [test_kg_origin.kn_node("exp-E01-0000", "expectation"), test_kg_origin.kn_node("req-1")]
        links = [test_kg.link("krel-x", "expects", "graph-SNP-M-102:RC-PZ01", "req-1")]
        out = build.build_kg(test_kg_origin.knowledge(nodes, links), [test_kg.pid_graph()])
        checks = {(b["check"], b["target"]) for b in out["validation"]["blockers"]}
        self.assertIn(("unknown_node_type", "exp-E01-0000"), checks)
        self.assertIn(("unknown_relation_kind", "krel-x"), checks)

    def test_screen_expectations_never_in_v5(self):
        g = test_kg.pid_graph()
        k = build.build_kg(test_kg.sample(), [g])
        res = expect.evaluate(g, k)
        data = screen.screen_data(k, g, expectations=res)
        x_nodes = [n for n in data["nodes"] if n["layer"] == screen.EXP_LAYER]
        x_links = [l for l in data["links"] if l["layer"] == screen.EXP_LAYER]
        self.assertTrue(x_nodes and x_links)
        self.assertFalse(any(n["v5"] for n in x_nodes) or any(l["v5"] for l in x_links))
        v5 = algo.view_v5(k, g)
        self.assertFalse({n["id"] for n in x_nodes} & set(v5.nodes))
        self.assertFalse({l["id"] for l in x_links} & {key for _, _, key in v5.edges(keys=True)})
        self.assertEqual(data["algo"], screen.screen_data(k, g)["algo"])  # A1~A5 결과가 같음
        self.assertEqual(data["meta"]["expectations"]["shown"], len(x_nodes))
        self.assertIsNone(screen.screen_data(k, g)["meta"]["expectations"])

    def test_ai_context_lists_gaps_without_ids(self):
        g = test_kg.pid_graph()
        k = build.build_kg(test_kg.sample(), [g])
        res = expect.evaluate(g, k)
        node = {"node_id": "S1", "name": "가압기", "members": [n["entity_id"] for n in g["nodes"]
                                                               if n.get("tag") in ("RC-PV101", "RC-PZ01")]}
        plain = ai_cells.node_context(node, g, k)
        ctx = ai_cells.node_context(node, g, k, expectations=res)
        self.assertNotIn("unverified_expectations", plain["prompt"])
        self.assertEqual({k2: v for k2, v in ctx["prompt"].items() if k2 != "unverified_expectations"}, plain["prompt"])
        items = ctx["prompt"]["unverified_expectations"]["items"]
        self.assertTrue(items)
        self.assertEqual({i["target_tag"] for i in items}, {"RC-PV101"})  # E05 구동원 의존 기대됨
        self.assertNotIn("exp-", json.dumps(ctx["prompt"]["unverified_expectations"], ensure_ascii=False))
        xid = res["items"][0]["id"]
        self.assertNotIn(xid, ctx["allowed"]["kg_ids"])
        warn = ai_cells.check_evidence({"equipment_tags": [], "kg_paths": [[xid]], "sources": []}, ctx)
        self.assertIn("그래프에 없는 ID: %s" % xid, warn)

    def test_ai_entry_drops_paths_with_expectation_ids(self):
        g = test_kg.pid_graph()
        k = build.build_kg(test_kg.sample(), [g])
        res = expect.evaluate(g, k)
        ids = [n["entity_id"] for n in g["nodes"] if n.get("tag") in ("RC-PV101", "RC-PZ01")]
        node = {"node_id": "S1", "name": "가압기", "members": ids}
        ctx = ai_cells.node_context(node, g, k, expectations=res)
        xid = res["items"][0]["id"]
        scenario = {"cause": "c", "consequence": "q", "recommendation": "r", "safeguards": [], "equipment_tags": [],
                    "severity": None, "frequency": None, "sources": [],
                    "kg_paths": [[ids[0], xid], [ids[0]]]}
        e = ai_cells._entry(scenario, ctx, "S1-D1-t-1")
        self.assertEqual(e["ai_basis"]["kg_paths"], [[ids[0]]])
        self.assertNotIn(xid, json.dumps(e["ai_basis"]["kg_paths"]))
        self.assertTrue(any("잠재 후보가 든 근거 경로를 뺌" in w and xid in w for w in e["ai_basis"]["warnings"]))
        self.assertFalse(any("그래프에 없는 ID" in w for w in e["ai_basis"]["warnings"]))
        self.assertEqual(e["origin"], "ai_draft")


class ScreenTablesTest(unittest.TestCase):
    def test_layers_and_states_tables(self):
        self.assertEqual(set(screen.SCREEN_LAYER), set(REGISTRY.layers))
        self.assertEqual(screen.SCREEN_LAYER["expectation"], "exp")
        self.assertEqual(screen.SCREEN_LAYER["study"], "st")
        self.assertEqual([x["state"] for x in screen.expect_table() if x["on"]],
                         ["expected", "candidate_found", "confirmed_absent"])
        for x in screen.expect_table():
            self.assertIn(x["col"], tokens.COLORS)
        for c in REGISTRY.legend_classes():
            self.assertIn(c["legend"]["token"], tokens.COLORS, c["id"])
        html = screen.build_html(None)
        for needle in ('id="sec-exp"', 'id="o-ai"', 'id="o-xgap"', "var LAYERS = ", "var XSTATES = ",
                       "updateExpectations"):
            self.assertIn(needle, html)


class KnowledgeScreenExpectTest(unittest.TestCase):
    """③ 잠재 후보 부분만: 계산 오류 격리, 손상 기록 안내, 판단 되돌리기 버튼(웹뷰·창 없이 화면 객체만)."""

    @classmethod
    def setUpClass(cls):
        from hazop.app import make_application
        cls.qapp = make_application(["test"])

    def setUp(self):
        from hazop.app.screens import knowledge
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.errors = []
        app = mock.Mock()
        app.log_error.side_effect = lambda what, exc: self.errors.append(what)
        self.scr = knowledge.KnowledgeScreen(app)
        self.addCleanup(self.scr.deleteLater)
        self.scr.pg = dict(graph(), project_id="P")
        self.scr.kg = kg()

    def test_calc_error_only_turns_off_expectations(self):
        with mock.patch.object(expect, "evaluate", side_effect=expect.ExpectError("잠재 후보 ID 중복: exp-E01-x")):
            self.assertIsNone(self.scr._expectations())
        self.assertEqual(self.errors, ["잠재 후보 계산"])
        self.scr.expect = None
        msgs, _ = self.scr._expect_band()
        self.assertEqual(msgs, ["잠재 후보를 계산하지 못함: 잠재 후보 ID 중복: exp-E01-x"])
        self.assertIsNotNone(self.scr._expectations())  # 다음 계산이 성공하면 안내가 사라짐
        self.assertIsNone(self.scr.expect_calc_error)

    def test_bad_record_band_and_undo_button(self):
        path = expect.store_path("P")
        res = expect.evaluate(self.scr.pg, self.scr.kg)
        rec = expect.apply_action(item(res, "E01", "P-1"), "confirm", "검토자")
        expect.save_judgement(path, "P", rec)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["judgements"]["E01|%s#o-p2" % GID] = dict(rec, key="E01|%s#o-p2" % GID, state="confirmed_absent", action="absent")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        self.scr.expect = self.scr._expectations()
        msgs, details = self.scr._expect_band()
        self.assertIn("잠재 후보 판단 기록 1건을 읽지 못해 적용하지 않음(파일은 그대로 둠)", msgs)
        self.assertTrue(any(d.startswith("읽지 못한 판단 E01|") for d in details))
        b = self.scr.expect_btns["undo"]
        self.assertEqual(b.text(), "판단 되돌리기")
        self.scr._show_expect_buttons(item(self.scr.expect, "E01", "P-1"))
        self.assertTrue(b.isEnabled())
        self.assertFalse(self.scr.expect_btns["confirm"].isEnabled())
        self.scr._show_expect_buttons(item(self.scr.expect, "E01", "P-2"))
        self.assertFalse(b.isEnabled())


class M0GapTest(unittest.TestCase):
    """M0 검토에서 넘긴 확장성 공백(결정 기록 'M4로')."""

    def _reg(self, mutate):
        d = copy.deepcopy(REGISTRY.data)
        mutate(d)
        return schema.Registry(d)

    def test_format_problems_not_exceptions(self):
        for mutate, needle in (
                (lambda d: next(r for r in d["relations"] if r["id"] == "governed_by").update(to=[]), "to는 클래스 ID 목록"),
                (lambda d: next(c for c in d["classes"] if c["id"] == "valve").update(parent=[]), "parent는"),
                (lambda d: next(c for c in d["classes"] if c["id"] == "valve").update(legend=None), "legend"),
                (lambda d: d.pop("layers"), "layers"),
                (lambda d: d["layers"][0].update(filter="x"), "filter"),
                (lambda d: d["relations"][0].update(pid_view="V3"), "V1")):
            with self.subTest(needle=needle):
                d = copy.deepcopy(REGISTRY.data)
                mutate(d)
                probs = schema.validate(d)
                self.assertTrue(any(needle in p for p in probs), probs)

    def test_apply_relation_inherits_and_allows_several_ends(self):
        bad = copy.deepcopy(REGISTRY.data)
        next(r for r in bad["relations"] if r["id"] == "governed_by")["to"] = ["requirement", "analysis_case"]
        self.assertTrue(any("같은 클래스 analysis_case" in p for p in schema.validate(bad)), schema.validate(bad))

        def ok(d):
            d["classes"].append({"id": "x_lco", "parent": "requirement", "label_ko": "운전제한조건", "label_en": "LCO"})
            d["classes"].append({"id": "x_logic", "parent": "knowledge_item", "label_ko": "논리", "label_en": "Logic"})
            next(r for r in d["relations"] if r["id"] == "governed_by")["to"] = ["requirement", "x_logic"]
        r = self._reg(ok)
        self.assertEqual(r.apply_relation_of("x_lco"), "governed_by")   # 상위 클래스(요건)로 적은 관계를 상속
        self.assertEqual(r.apply_relation_of("x_logic"), "governed_by")  # 끝 클래스 둘
        self.assertEqual(r.apply_kind_of()["x_lco"], "governed_by")
        self.assertIsNone(r.apply_relation_of("document"))

    def test_a2_skips_types_without_apply_relation(self):
        g = test_kg.pid_graph()
        k = build.build_kg(test_kg.sample(), [g])
        with mock.patch.dict(algo.APPLY_KIND_OF, {}, clear=True):
            out = algo.a2_orphans_gaps(k, g)  # 옛 코드는 APPLY_KIND_OF[t] KeyError
        self.assertEqual({o["node_type"] for o in out["orphans"]} - {"doc_chunk"}, set())

    def test_v1_accepts_several_relations(self):
        g = test_kg.pid_graph()
        e = dict(next(x for x in g["edges"] if x["kind"] == "has_endpoint"), entity_id="x-extra", kind="x_pipe_link")
        g["edges"].append(e)
        with mock.patch.object(algo, "PHYSICAL_KINDS", ("has_endpoint", "x_pipe_link")):
            self.assertTrue(algo.view_v1(g).has_edge(*e["nodes"]))

    @staticmethod
    def _valve_only(d, v4=True):
        rel = next(x for x in d["relations"] if x["id"] == "governed_by")
        rel["from"] = ["valve"]
        rel["v4"] = v4

    def test_pid_end_matches_parent_classes(self):
        r = self._reg(self._valve_only)
        self.assertTrue(r.pair_allowed("governed_by", "control_valve", "requirement"))
        self.assertFalse(r.pair_allowed("governed_by", "pump", "requirement"))

    def test_build_uses_pid_class_and_registry_v4(self):
        reg = self._reg(lambda d: self._valve_only(d, v4=False))
        nodes = [test_kg_origin.kn_node("req-1")]
        links = [test_kg.link("krel-a", "governed_by", "graph-SNP-M-102:RC-PZ01", "req-1"),
                 test_kg.link("krel-b", "governed_by", "graph-SNP-M-102:RC-PV101", "req-1")]
        with mock.patch.object(build, "REGISTRY", reg):
            out = build.build_kg(test_kg_origin.knowledge(nodes, links), [test_kg.pid_graph()])
        blocked = {(b["check"], b["target"]) for b in out["validation"]["blockers"]}
        self.assertIn(("type_pair_not_allowed", "krel-a"), blocked)  # 가압기는 밸브가 아님
        self.assertNotIn(("type_pair_not_allowed", "krel-b"), blocked)  # 제어 밸브는 밸브의 하위 클래스
        b = next(l for l in out["links"] if l["id"] == "krel-b")
        self.assertIn("relation_not_in_v4", b["compute_view"]["excluded_reasons"])


if __name__ == "__main__":
    unittest.main()
