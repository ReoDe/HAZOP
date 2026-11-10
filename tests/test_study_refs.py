"""⑤ 결과 항목의 그래프 참조(M5, 설계안 KD7·§7.1·§7.2·§8.3, U2(가)·U6(가)) 시험.
실행: python -m unittest tests.test_study_refs

저장은 임시 HAZOP_WORK_ROOT 아래에만 한다. 실제 데이터/분석결과는 읽기만 하고(있을 때만) 사본으로 왕복한다.
AI는 가짜 응답만 쓴다(네트워크 호출 없음).
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import openpyxl  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.export import study_xlsx as sx  # noqa: E402
from hazop.kg import algo, build, context, screen  # noqa: E402
from hazop.kg.schema import REGISTRY  # noqa: E402
from hazop.study import ai_cells, migrate, refs  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_kg import link, pid_graph, sample  # noqa: E402
from tests.test_study_migrate import AT, OBJECTS, graph, results_for, text_of  # noqa: E402

REAL = paths.folder("analysis-results", "no-project", "graph-SNP-M-102.json")
GID = "graph-SNP-M-102"


def new_entry(**kw):
    e = {"entry_id": "n1", "origin": "ai_draft", "status": "proposed", "cause": "V1 닫힘 고착", "consequence": "유량 없음",
         "safeguards": ["LT 저액위 경보", {"text": "V2 수동 개방", "role": "mitigative",
                                       "refs": [{"ref": "graph-T#V2", "origin": "ai_draft"}], "ipl": None,
                                       "origin": "ai_draft"}],
         "cause_refs": [{"ref": "graph-T#V1", "failure_mode": "닫힘 고착", "origin": "ai_draft"}],
         "consequence_refs": [{"ref": "graph-T#PP", "origin": "human"}],
         "expectation_refs": ["exp-E01-0123456789abcdef"],
         "recommendation": "", "severity": 2, "frequency": 2, "risk": 2, "history": []}
    e.update(kw)
    return e


class TmpRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-refs-")
        self._old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)


class FormatTest(unittest.TestCase):

    def test_string_safeguard_reads_as_unknown_role(self):
        items = refs.safeguard_items(new_entry())
        self.assertEqual(items[0], {"text": "LT 저액위 경보", "role": "unknown", "actuation": "unknown", "refs": [],
                                    "ipl": None, "origin": None})
        self.assertEqual((items[1]["role"], items[1]["refs"][0]["ref"]), ("mitigative", "graph-T#V2"))
        self.assertEqual(refs.safeguard_texts({"safeguards": ["a", "b"]}), ["a", "b"])
        self.assertEqual(refs.all_refs(new_entry()), ["graph-T#V1", "graph-T#PP", "graph-T#V2"])

    def test_problems(self):
        self.assertEqual(refs.problems(new_entry()), [])
        self.assertEqual(refs.problems({"safeguards": ["옛 문자열"]}), [])  # 옛 항목
        for bad in ({"cause_refs": [{"ref": "entity-node-001"}]},  # entity_id는 안정 참조가 아님
                    {"cause_refs": "graph-T#V1"},
                    {"consequence_refs": [{"ref": "g#a", "failure_mode": "x"}]},
                    {"safeguards": [{"text": "x", "role": "barrier"}]},
                    {"safeguards": [{"text": "x", "ipl": True}]},
                    {"safeguards": [{"text": "x", "refs": [{"ref": "g#a", "origin": "robot"}]}]},
                    {"expectation_refs": [1]}):
            self.assertTrue(refs.problems(bad), bad)

    def test_ai_refs_are_drafts_until_approved(self):
        e = new_entry()
        idx = refs.index(graph("v-1"))
        texts = dict(refs.lines(e, idx))
        self.assertIn("· AI 초안", texts["cause"])
        self.assertNotIn("AI 초안", texts["consequence"])  # 사람이 고른 참조
        self.assertEqual(texts["cause"], "원인 위치: V1 · 닫힘 고착 · AI 초안")
        approved = res.set_status({"cells": [{"node_id": "S1", "deviation_id": "D01", "entries": [e]}]},
                                  "S1", "D01", "n1", "approved", at=AT)["cells"][0]["entries"][0]
        self.assertFalse(any("AI 초안" in t for _k, t in refs.lines(approved, idx)))

    def test_missing_target_is_marked_not_dropped(self):
        e = new_entry()
        g = graph("v-1", objects=[o for o in OBJECTS if o[0] != "V1"])
        idx = refs.index(g)
        self.assertEqual(refs.missing(e, idx), ["graph-T#V1"])
        cause = [t for k, t in refs.lines(e, idx) if k == "cause"]
        self.assertEqual(cause, ["원인 위치: 대상 없음(재확인): graph-T#V1 · 닫힘 고착 · AI 초안"])
        self.assertEqual(e["cause_refs"][0]["ref"], "graph-T#V1")  # 읽기만, 항목은 그대로


class FileTest(TmpRoot):

    @unittest.skipUnless(os.path.isfile(REAL), "실제 분석 결과 파일 없음")
    def test_real_old_results_round_trip_unchanged(self):
        """실제 저장본 사본: 읽기 → 다시 쓰기 → 읽기 내용이 같고, 새 필드 검사에서 문제가 없음. 실제 폴더에는 쓰지 않는다."""
        src = os.path.join(self.tmp, "copy.json")
        shutil.copy2(REAL, src)
        with open(REAL, "rb") as fh:
            original = fh.read()
        doc = res.read(src)
        self.assertEqual([p for p in res.validate(doc) if "refs" in p or "safeguards" in p], [])
        out = res.write(os.path.join(self.tmp, "again.json"), doc)
        self.assertEqual(res.read(out), json.loads(original.decode("utf-8")))
        entries = [e for c in doc["cells"] for e in c["entries"]]
        self.assertTrue(entries)
        idx = refs.index(pid_graph())
        self.assertEqual({k for e in entries for k, _t in refs.lines(e, idx)}, set())  # 옛 항목은 참조 줄 없음
        with open(REAL, "rb") as fh:
            self.assertEqual(fh.read(), original)

    def test_old_entry_edit_keeps_text_status_history(self):
        g = graph("v-1")
        ns = sn.confirm(sn.propose(g, at=AT), g, "김검토", at=AT)
        doc = results_for(ns, g)
        before = text_of(doc)
        out = res.edit_entry(doc, doc["cells"][0]["node_id"], "D01", "e1",
                             {"cause_refs": [{"ref": "graph-T#V1", "origin": "human"}],
                              "safeguards": [{"text": "LT 저액위 경보", "role": "preventive",
                                              "refs": [{"ref": "graph-T#LT", "origin": "human"}], "ipl": None,
                                              "origin": "human"}]}, at=AT)
        e = out["cells"][0]["entries"][0]
        self.assertEqual(e["status"], "revised")
        self.assertEqual(e["history"][:1], before[0]["history"])
        self.assertEqual(e["history"][-1]["before"], {"cause_refs": None, "safeguards": ["LT 저액위 경보"]})
        self.assertEqual((e["cause"], e["consequence"]), (before[0]["cause"], before[0]["consequence"]))
        self.assertEqual(text_of(out)[1], before[1])
        path = res.write(os.path.join(self.tmp, "r.json"), out)
        self.assertEqual(res.read(path), out)
        self.assertEqual(res.validate(res.read(path), ns), [])
        with self.assertRaises(ValueError):
            res.edit_entry(doc, doc["cells"][0]["node_id"], "D01", "e1", {"cause_refs": [{"ref": "entity-node-001"}]})

    def test_stable_refs_survive_version_migration(self):
        """판이 바뀌어 entity_id가 밀려도 안정 참조는 그대로이고 새 판에서 같은 대상을 찾는다(이전이 필요 없음)."""
        g1 = graph("v-1")
        ns = sn.confirm(sn.propose(g1, at=AT), g1, "김검토", at=AT)
        sn.save(ns)
        doc = results_for(ns, g1)
        doc["cells"][0]["entries"][0].update(new_entry(entry_id="e1"))
        rpath = res.save(doc, None)
        g2 = graph("v-2", shift=10)
        ns2 = sn.load(g2)
        moved = res.read(rpath)
        self.assertEqual(moved["study_nodes_ref"]["graph_version"], "v-2")
        e = moved["cells"][0]["entries"][0]
        self.assertEqual({k: e[k] for k in ("cause_refs", "consequence_refs", "safeguards", "expectation_refs")},
                         {k: new_entry()[k] for k in ("cause_refs", "consequence_refs", "safeguards", "expectation_refs")})
        idx2 = refs.index(g2)
        self.assertEqual(idx2["graph-T#V1"]["entity_id"], "entity-node-012")
        self.assertNotEqual(refs.index(g1)["graph-T#V1"]["entity_id"], idx2["graph-T#V1"]["entity_id"])
        self.assertEqual(res.validate(moved, ns2), [])


class AiRefsTest(unittest.TestCase):

    def setUp(self):
        self.g = graph("v-1")
        self.node = {"node_id": "S1", "members": [n["entity_id"] for n in self.g["nodes"]]}
        self.ctx = ai_cells.node_context(self.node, self.g, None)

    def e(self, soid):
        return next(n["entity_id"] for n in self.g["nodes"] if n["source_object_id"] == soid)

    def test_refs_converted_unknown_dropped_and_marked_draft(self):
        s = {"cause": "V1 닫힘", "consequence": "PP 공동현상", "recommendation": "", "severity": 2, "frequency": 2,
             "equipment_tags": ["V1"], "kg_paths": [], "sources": [],
             "cause_refs": [{"entity_id": self.e("V1"), "failure_mode": "닫힘 고착"}, {"entity_id": "entity-node-999",
                                                                                   "failure_mode": ""}],
             "consequence_refs": [{"entity_id": self.e("PP")}],
             "safeguards": [{"text": "LT 저액위 경보", "role": "preventive", "entity_ids": [self.e("LT"), "nope"]},
                            {"text": "운전원 확인", "role": "barrier", "entity_ids": []}]}
        self.assertTrue(ai_cells._scenario_ok(s))
        e = ai_cells._entry(s, self.ctx, "x1")
        self.assertEqual(e["cause_refs"], [{"ref": "graph-T#V1", "origin": "ai_draft", "failure_mode": "닫힘 고착"}])
        self.assertEqual(e["consequence_refs"], [{"ref": "graph-T#PP", "origin": "ai_draft"}])
        self.assertEqual(e["safeguards"][0], {"text": "LT 저액위 경보", "role": "preventive", "actuation": "unknown",
                                              "ipl": None, "origin": "ai_draft", "refs": [{"ref": "graph-T#LT", "origin": "ai_draft"}]})
        self.assertEqual(e["safeguards"][1]["role"], "unknown")
        w = e["ai_basis"]["warnings"]
        self.assertIn("그래프에 없는 원인 위치 대상을 뺌: entity-node-999", w)
        self.assertIn("그래프에 없는 보호수단 구현 대상을 뺌: nope", w)
        self.assertIn("모르는 보호수단 역할을 미정으로 둠: barrier", w)
        self.assertEqual(refs.problems(e), [])
        self.assertEqual((e["origin"], e["status"]), ("ai_draft", "proposed"))
        self.assertFalse(any(refs.is_confirmed(r, e) for r in e["cause_refs"] + e["safeguards"]))

    def test_old_response_shape_gives_old_entry_shape(self):
        s = {"cause": "c", "consequence": "q", "safeguards": ["보호"], "recommendation": "", "severity": None,
             "frequency": None, "equipment_tags": [], "kg_paths": [], "sources": []}
        e = ai_cells._entry(s, self.ctx, "x2")
        self.assertEqual(e["safeguards"], ["보호"])
        self.assertFalse({"cause_refs", "consequence_refs", "expectation_refs"} & set(e))

    def test_bad_ref_shapes_rejected(self):
        base = {"cause": "c", "consequence": "q", "safeguards": [], "recommendation": "", "severity": None,
                "frequency": None, "equipment_tags": [], "kg_paths": [], "sources": []}
        for bad in ({"cause_refs": "V1"}, {"cause_refs": [{"ref": "x"}]}, {"consequence_refs": [{"entity_id": 3}]},
                    {"safeguards": [{"role": "preventive"}]}, {"safeguards": [{"text": "t", "entity_ids": "x"}]}):
            self.assertFalse(ai_cells._scenario_ok(dict(base, **bad)), bad)

    def test_prompt_treats_expectations_as_clues(self):
        p = ai_cells.SYSTEM_PROMPT
        self.assertIn("잠재 후보(unverified_expectations)는 근거가 아니라 확인할 단서", p)
        self.assertIn("잠재 후보 문구", p)
        self.assertIn("conflict_with_drawing", p)
        self.assertIn("cause_refs", p)
        from hazop.kg import expect
        self.assertIn("확인할 단서", expect.CONTEXT_NOTE)
        props = ai_cells.SCENARIO_SCHEMA["properties"]
        self.assertEqual(props["safeguards"]["items"]["properties"]["role"]["enum"], list(refs.ROLES))
        self.assertEqual(set(ai_cells.SCENARIO_SCHEMA["required"]), set(props))


class KgTest(unittest.TestCase):
    """샘플 도면 SNP-M-102 + 정상 샘플 지식 CSV 사본(파일을 쓰지 않음)."""

    @classmethod
    def setUpClass(cls):
        cls.g = pid_graph()
        k = sample()
        k["links"].append(link("krel-901", "specified_in", "setpt-001", "chunk-003"))
        cls.kg = build.build_kg(k, [cls.g])

    def soid(self, tag):
        return next(n["source_object_id"] for n in self.g["nodes"] if n.get("tag") == tag)

    def eid(self, tag):
        return next(n["entity_id"] for n in self.g["nodes"] if n.get("tag") == tag)

    def test_evidence_trail_from_cause_ref_to_document_chunk(self):
        """근거 경로 시연: 원인 참조 → P&ID 노드 → has_setpoint → 설정치 → specified_in → 문서 조각."""
        entry = {"cause_refs": [{"ref": "%s#%s" % (GID, self.soid("RC-PT110"))}]}
        trails = refs.evidence_trails(entry["cause_refs"][0]["ref"], self.g, self.kg)
        full = [[s["kind"] for s in t] for t in trails]
        self.assertIn(["pid_node", "has_setpoint", "setpoint", "specified_in", "doc_chunk"], full)
        t = next(t for t in trails if len(t) == 5)
        self.assertEqual([s["id"] for s in t], [entry["cause_refs"][0]["ref"], "krel-010", "setpt-001", "krel-901",
                                               "chunk-003"])
        self.assertTrue(all(s["v4"] for s in t))
        self.assertEqual(refs.evidence_trails("%s#nope" % GID, self.g, self.kg), [])

    def test_drawing_conflict_reaches_ai_context(self):
        k = sample()
        next(n for n in k["nodes"] if n["id"] == "setpt-003")["knowledge_status"] = "confirmed"
        kg = build.build_kg(k, [self.g])
        ctx, _ = context.build_context(kg, self.g, [self.eid("RC-PSV101"), self.eid("RC-PT110")])
        items = {it["knowledge_id"]: it for it in ctx["items"]}
        self.assertEqual(items["setpt-003"]["conflict_with_drawing"],
                         [{"target": "%s#%s" % (GID, self.soid("RC-PSV101")), "property": "set_pressure",
                           "value": "17.2", "unit": "MPa", "pressure_basis": None}])
        self.assertNotIn("conflict_with_drawing", items["setpt-001"])  # 충돌 없는 항목은 옛 바이트 그대로
        from hazop.app import data
        doc = {"evidence_bundles": {"c1": {"knowledge_context": ctx}}, "candidates": []}
        rk = data.related_knowledge(doc, {"candidate_id": "c1", "cause_equipment": [self.eid("RC-PSV101")]})
        it = next(x for x in rk["items"] if x["item"]["knowledge_id"] == "setpt-003")
        self.assertTrue(it["conflict"])
        self.assertIn(("도면값과 충돌", "err"), it["badges"])

    def study(self):
        members = ["%s/%s" % (GID, self.eid(t)) for t in ("RC-PSV101", "RC-PZ01", "RC-PT110")]
        ns = {"nodes": [{"node_id": "S1", "name": "가압기", "members": members},
                        {"node_id": "S9", "name": "다른 도면", "members": ["graph-OTHER/entity-node-001"]}]}
        r = {"deviations": [{"deviation_id": "D01", "label": "압력 높음"}],
             "cells": [{"node_id": "S1", "deviation_id": "D01", "state": "analyzed", "entries": [
                 dict(new_entry(entry_id="e1", cause="PT 오지시",
                                cause_refs=[{"ref": "%s#%s" % (GID, self.soid("RC-PT110")), "origin": "ai_draft"}],
                                consequence_refs=[{"ref": "%s#%s" % (GID, self.soid("RC-PZ01"))},
                                                  {"ref": "%s#gone" % GID}],
                                safeguards=[{"text": "PSV 방출", "role": "mitigative", "ipl": None,
                                             "refs": [{"ref": "%s#%s" % (GID, self.soid("RC-PSV101"))}]}],
                                expectation_refs=[])),
                 dict(new_entry(entry_id="e2", status="rejected"))]}]}
        return {"node_set": ns, "results": r, "note": None}

    def test_study_layer_projection_default_off_and_outside_v4(self):
        self.assertEqual(next(x for x in screen.layer_table() if x["key"] == screen.STUDY_LAYER)["on"], False)
        for cid in ("study_node", "scenario", "cause", "consequence", "safeguard", "recommendation"):
            self.assertEqual(REGISTRY.layer(cid), "study")
        for rid in ("covers", "cause_at", "affects", "safeguard_by", "addresses", "raised_from", "cites"):
            self.assertFalse(REGISTRY.relations[rid]["v4"])
        data = screen.screen_data(self.kg, self.g, study=self.study())
        st = [n for n in data["nodes"] if n["layer"] == screen.STUDY_LAYER]
        sl = [l for l in data["links"] if l["layer"] == screen.STUDY_LAYER]
        self.assertEqual({n["type"] for n in st}, {"study_node", "scenario", "cause", "consequence", "safeguard"})
        self.assertFalse(any(n["id"].startswith("st-e2") for n in st))  # 기각 항목 제외
        self.assertFalse(any(n["v5"] for n in st) or any(l["v5"] for l in sl))
        self.assertEqual(data["meta"]["global_count"], len(data["nodes"]) - len(st), "기본 꺼진 검토 층은 세지 않음")
        kinds = {l["kind"] for l in sl}
        self.assertEqual(kinds, {"in_node", "has_cause", "has_consequence", "cause_at", "affects",
                                 "protected_by", "safeguard_by"})
        sb = next(l for l in sl if l["kind"] == "safeguard_by")
        self.assertEqual(sb["t"], self.eid("RC-PSV101"))
        meta = data["meta"]["study"]
        self.assertEqual(meta["nodes"], [{"sn": "S1", "name": "가압기", "scenarios": 1, "missing": 1}])
        scen = next(n for n in st if n["type"] == "scenario")
        self.assertEqual((scen["draft"], scen["missing"]), (True, 1))
        v5 = algo.view_v5(self.kg, self.g)
        self.assertFalse(any(n["id"] in v5 for n in st))
        self.assertEqual(data["meta"]["excluded_nodes"], screen.screen_data(self.kg, self.g)["meta"]["excluded_nodes"])
        self.assertEqual(data["algo"]["A3"], screen.screen_data(self.kg, self.g)["algo"]["A3"])
        html = screen.build_html(data)
        self.assertIn('id="sec-st"', html)
        self.assertIn("var STL = \"st\"", html)

    def test_no_study_means_no_projection(self):
        data = screen.screen_data(self.kg, self.g)
        self.assertIsNone(data["meta"]["study"])
        self.assertFalse(any(n["layer"] == screen.STUDY_LAYER for n in data["nodes"]))


class ExcelTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-xlsx-refs-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_fields_in_reference_column_old_blank(self):
        from tests.test_study_export import DEVS, NOW, sample as xsample
        r, ns, pg, span_node, _single = xsample()
        node = next(n for n in pg["nodes"] if n.get("tag") and n.get("source_object_id"))
        ref = migrate.ref_of(node, pg["graph_id"])
        dn = {s["graph_id"]: s["drawing_number"] for s in pg["sheets"]}[node["sheet"]]
        cell = next(c for c in r["cells"] if (c["node_id"], c["deviation_id"]) == (span_node, "D01"))
        e = cell["entries"][0]
        e.update(cause_refs=[{"ref": ref, "failure_mode": "닫힘 고착", "origin": "human"}],
                 safeguards=[{"text": "안전밸브", "role": "mitigative", "refs": [{"ref": ref, "origin": "human"}],
                              "ipl": None, "origin": "human"}, "옛 문자열 보호수단"],
                 consequence_refs=[{"ref": "%s#gone" % node["sheet"], "origin": "human"}],
                 expectation_refs=["exp-E02-x"])
        self.assertEqual(res.validate(r, ns), [])
        xs = {"items": [{"id": "exp-E02-x", "rule_id": "E02", "target": ref, "target_tag": node["tag"],
                         "label": "과압 보호수단", "state_label": "부재 확정", "recheck": False}]}
        path, _n = sx.export(os.path.join(self.tmp, "o.xlsx"), r, ns, pg, DEVS, now=NOW, expectations=xs)
        ws = openpyxl.load_workbook(path)[sx.SHEETS[2]]
        head = [c.value for c in ws[1]]
        col = "그래프 참조"
        rows = [dict(zip(head, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]
        mine = next(x for x in rows if x["원인"] == e["cause"])
        label = "%s (%s)" % (node["tag"], dn)
        self.assertEqual(mine[col].split("\n"), [
            "원인 위치: %s · 닫힘 고착" % label, "영향 대상: 대상 없음(재확인): %s#gone" % node["sheet"],
            "보호수단: %s · 완화" % label, "단서: 잠재 후보: E02 %s 과압 보호수단 · 부재 확정" % node["tag"]])
        self.assertEqual(mine["보호수단"], "[미확인] 안전밸브\n[미확인] 옛 문자열 보호수단")
        others = [x for x in rows if x is not mine and x["상태"] and not x["상태"].startswith(("해당", "실패", "시나리오"))]
        self.assertTrue(others)
        self.assertTrue(all(x[col] is None for x in others))  # 옛 항목은 빈칸


class DialogTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, entry):
        from hazop.app.screens.results import EntryDialog
        labels = {"g#V1": "V1(1)", "g#V2": "V2(1)", "g#PP": "PP(1)"}
        ctx = {"choices": [(r, t) for r, t in labels.items()], "label": lambda r: labels.get(r, "%s: %s" % (refs.MISSING, r)),
               "expectations": [("exp-1", "E01 PP 체크밸브 · 기대됨")]}
        dlg = EntryDialog(entry, None, ctx)
        self.addCleanup(dlg.deleteLater)
        return dlg

    def test_pick_targets_and_roles(self):
        entry = {"cause": "c", "consequence": "q", "safeguards": ["경보", {"text": "AI 보호", "role": "preventive",
                                                                       "refs": [{"ref": "g#V2", "origin": "ai_draft"}],
                                                                       "ipl": None, "origin": "ai_draft"}],
                 "recommendation": "", "severity": None, "frequency": None,
                 "cause_refs": [{"ref": "g#gone", "failure_mode": "FTC", "origin": "ai_draft"}]}
        dlg = self.dialog(entry)
        self.assertEqual(dlg.changed(), {})
        self.assertEqual(dlg.pickers["cause_refs"].checked(), ["g#gone"])  # 대상 없는 참조도 체크된 채로 남음
        self.assertTrue(dlg.pickers["cause_refs"].set_checked("g#V1"))
        self.assertTrue(dlg.pickers["consequence_refs"].set_checked("g#PP"))
        self.assertTrue(dlg.pickers["expectation_refs"].set_checked("exp-1"))
        role = dlg.sg_table.cellWidget(0, 1)
        role.setCurrentIndex(role.findData("mitigative"))
        target = dlg.sg_table.cellWidget(0, 3)
        target.setCurrentIndex(target.findText("V1(1)"))
        got = dlg.changed()
        self.assertEqual(got["cause_refs"], [{"ref": "g#gone", "origin": "ai_draft", "failure_mode": "FTC"},
                                             {"ref": "g#V1", "origin": "human"}])
        self.assertEqual(got["consequence_refs"], [{"ref": "g#PP", "origin": "human"}])
        self.assertEqual(got["expectation_refs"], ["exp-1"])
        self.assertEqual(got["safeguards"], [
            {"text": "경보", "role": "mitigative", "refs": [{"ref": "g#V1", "origin": "human"}], "ipl": None,
             "origin": "human"},
            entry["safeguards"][1]])  # 손대지 않은 AI 보호수단은 그대로(AI 초안 표시 유지)
        self.assertEqual(refs.problems(got), [])

    def test_text_edit_keeps_row_choices(self):
        dlg = self.dialog({"cause": "", "consequence": "", "safeguards": ["A"], "recommendation": "",
                           "severity": None, "frequency": None})
        role = dlg.sg_table.cellWidget(0, 1)
        role.setCurrentIndex(role.findData("preventive"))
        dlg.safeguards.setPlainText("A\nB")
        self.assertEqual(dlg.sg_table.rowCount(), 2)
        self.assertEqual(dlg.sg_table.cellWidget(0, 1).currentData(), "preventive")
        self.assertEqual(dlg.changed()["safeguards"],
                         [{"text": "A", "role": "preventive", "refs": [], "ipl": None, "origin": "human"}, "B"])

    def test_text_only_edit_keeps_role_and_refs(self):
        sg = {"text": "PSV 방출", "role": "mitigative", "ipl": None, "origin": "ai_draft",
              "refs": [{"ref": "g#V2", "origin": "ai_draft"}, {"ref": "g#gone", "origin": "ai_draft"}]}
        dlg = self.dialog({"cause": "", "consequence": "", "safeguards": [sg], "recommendation": "",
                           "severity": None, "frequency": None})
        dlg.safeguards.setPlainText("PSV 방출(설정치 17.2 MPa)")
        self.assertEqual(dlg.changed()["safeguards"], [dict(sg, text="PSV 방출(설정치 17.2 MPa)", origin="human")])

    def test_same_text_safeguards_matched_by_position(self):
        a = {"text": "운전원 조치", "role": "preventive", "ipl": None, "origin": "ai_draft",
             "refs": [{"ref": "g#V1", "origin": "ai_draft"}]}
        b = {"text": "운전원 조치", "role": "mitigative", "ipl": None, "origin": "ai_draft",
             "refs": [{"ref": "g#V2", "origin": "ai_draft"}]}
        entry = {"cause": "", "consequence": "", "safeguards": [a, b], "recommendation": "",
                 "severity": None, "frequency": None}
        dlg = self.dialog(entry)
        self.assertEqual(dlg.changed(), {}, "고치지 않으면 아무것도 바뀌지 않음")
        self.assertEqual(dlg.fields()["safeguards"], [a, b])
        target = dlg.sg_table.cellWidget(1, 3)
        target.setCurrentIndex(target.findText("PP(1)"))
        self.assertEqual(dlg.changed()["safeguards"],
                         [a, dict(b, refs=[{"ref": "g#PP", "origin": "human"}], origin="human")])


class EditGuardTest(unittest.TestCase):
    """도면 연결 구간처럼 저장할 수 없는 참조를 골라도 고친 내용이 사라지지 않는지(⑤ 수정 창)."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tests.test_results_project_ui import ResultsProjectUiTest
        self.fx = ResultsProjectUiTest("test_no_cell_open_hint")
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)
        self.fx.confirm_project_set()
        self.st, scr = self.fx.screen()
        self.st.log_error = lambda *_a: None
        self.scr = scr
        self.node = self.fx.spanning(scr)
        did = scr.deviations[0]["deviation_id"]
        doc = copy.deepcopy(scr.results)
        cell = next(c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == (self.node["node_id"], did))
        cell.update(state="analyzed", entries=[new_entry(entry_id="E1", cause_refs=[], consequence_refs=[],
                                                         expectation_refs=[], safeguards=[])])
        scr.set_results(doc)
        self.assertTrue(scr.open_cell(self.node["node_id"], did))
        scr.select_entry(0)

    def test_link_span_not_offered_and_bad_save_keeps_dialog(self):
        from unittest import mock
        from PySide6.QtWidgets import QDialog
        from hazop.app.screens import results as rs
        xlinks = [r for r in self.scr.ref_idx if "#" not in r]
        self.assertTrue(xlinks, "합성 도면에 도면 연결 구간이 있어야 함")
        ctx = self.scr.ref_context(self.node["node_id"])
        self.assertTrue(all("#" in r for r, _t in ctx["choices"]))
        bad = {"cause": "고친 원인", "cause_refs": [{"ref": xlinks[0], "origin": "human"}]}
        good = {"cause": "고친 원인"}

        class FakeDialog:
            answers = [bad, good]
            runs = 0

            def __init__(self, *_a):
                pass

            def exec(self):
                FakeDialog.runs += 1
                return QDialog.Accepted

            def changed(self):
                return FakeDialog.answers[FakeDialog.runs - 1]

        before = copy.deepcopy(self.scr.results)
        with mock.patch.object(rs, "EntryDialog", FakeDialog), \
                mock.patch.object(rs.QMessageBox, "warning") as warn:
            self.assertTrue(self.scr.edit_selected())
        self.assertEqual(FakeDialog.runs, 2, "오류 뒤 같은 창을 다시 연다")
        self.assertEqual(warn.call_count, 1)
        self.assertIn("창에 그대로 남아", warn.call_args[0][2])
        self.assertEqual(self.scr.selected_entry()["cause"], "고친 원인")
        with mock.patch.object(rs.QMessageBox, "warning") as warn:
            self.scr.set_results(before)
            self.scr.open_cell(self.node["node_id"], self.scr.deviations[0]["deviation_id"])
            self.scr.select_entry(0)
            self.assertFalse(self.scr.edit_selected(bad))
        self.assertEqual(warn.call_count, 1)
        self.assertEqual(self.scr.results, before, "저장할 수 없는 값이면 아무것도 바꾸지 않는다")


if __name__ == "__main__":
    unittest.main()
