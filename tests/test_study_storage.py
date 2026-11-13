"""검토구간 저장 규격 v2(docs/specs/study-node-segmentation.md rev 2, N1) 시험. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다.
번호 ①~㉗은 규격 §9 N1 표의 '시험해야 할 경우', 재현 1·4·5·8은 §12.1이다.
실행: python -m unittest tests.test_study_storage
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import store_io  # noqa: E402
from hazop.ie import bundle as ib  # noqa: E402
from hazop.ie import model  # noqa: E402
from hazop.study import ai_cells, convert, migrate, node_tools as nt, refs, remap  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_study_migrate import graph  # noqa: E402

AT = "2026-11-13T00:00:00Z"
DEVS = [{"deviation_id": "D01", "item_id": "I1", "parameter": "유량", "guideword": "없음", "label": "유량 없음"},
        {"deviation_id": "D02", "item_id": "I2", "parameter": "압력", "guideword": "낮음", "label": "압력 낮음"}]
HINT = {"candidate": "yes", "disturbs": "yes", "challenges": "yes", "safety_functions": ["2차측 열제거"],
        "category": "LOMFW", "reason": "", "origin": "human", "status": "confirmed"}


def ids(g, *soids):
    by = {n["source_object_id"]: n["entity_id"] for n in g["nodes"]}
    return [by[s] for s in soids]


def sref(g, soid):
    """앱이 cause_refs에 넣는 실제 형식의 안정 참조(graph_id#source_object_id, hazop.study.refs)."""
    return migrate.ref_of(next(n for n in g["nodes"] if n["source_object_id"] == soid), g["graph_id"])


def build(g, groups, confirm=True):
    """groups: [(이름, [source_object_id])] → 0.2 집합(사람이 만든 구간). confirm이면 모두 확정."""
    ns = sn.new_set(g)
    ops = [{"op": "add", "name": name, "members": ids(g, *members)} for name, members in groups]
    ns, _r, _b = nt.apply_nodes(ns, None, g, ops, {}, "user", ns["set_rev"], at=AT)
    return sn.confirm(ns, g, "검토자", at=AT) if confirm else ns


def entry(eid, status="approved", **kw):
    return dict({"entry_id": eid, "origin": "human", "status": status, "cause": "원인 " + eid, "consequence": "결과",
                 "safeguards": []}, **kw)


def put_entries(doc, node_id, item, entries):
    cell = next(c for c in doc["cells"] if (c["node_id"], c["item_id"]) == (node_id, item))
    cell.update(state="analyzed", entries=entries)
    return doc


class WorkRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-nodes-v2-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)
        self.g = graph("v1")


# ---------------------------------------------------------------- 0.1 파일 변환(§2.5)

def set01(g, nodes, status="confirmed", confirmed_at="t1", previous=None):
    return {"schema_version": "0.1", "kind": "hazop_study_nodes", "project_id": None, "graph_id": g["graph_id"],
            "graph_version": g["graph_version"], "status": status,
            "confirmed_at": confirmed_at if status == "confirmed" else None,
            "confirmed_by": "홍길동" if status == "confirmed" else None,
            "nodes": [{"node_id": nid, "name": "구간 " + nid, "origin": "rule", "members": ids(g, *m)}
                      for nid, m in nodes],
            "history": [], **({"previous": previous} if previous is not None else {})}


def results01(set_like, confirmed_at, approved_cells):
    """0.1 결과. approved_cells: [(node_id, deviation_id, entry_id)] 승인 항목."""
    doc = remap.empty_legacy(dict(set_like, confirmed_at=confirmed_at), DEVS)
    for nid, did, eid in approved_cells:
        cell = next(c for c in doc["cells"] if (c["node_id"], c["deviation_id"]) == (nid, did))
        cell.update(state="analyzed", entries=[entry(eid, recommendation="권고 " + eid)])
    return doc


def write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    with open(path, "rb") as fh:
        return fh.read()


class ConvertTest(WorkRoot):
    def paths(self):
        return sn.store_path(None, self.g["graph_id"]), res.store_path(None, self.g["graph_id"])

    def cells(self, doc):
        return {(c["node_id"], c["deviation_id"]): c for c in doc["cells"]}

    def test_1_confirmed_with_matching_results_keeps_every_cell(self):
        old = set01(self.g, [("S1", ["TK", "V1"]), ("S2", ["V2", "PP"])])
        spath, rpath = self.paths()
        sdata = write(spath, old)
        rdata = write(rpath, results01(old, "t1", [("S1", "D01", "e1")]))
        ns, fp = sn.load_fp(self.g)
        self.assertEqual((ns["schema_version"], [n["state"] for n in ns["nodes"]]), ("0.2", ["confirmed", "confirmed"]))
        self.assertNotIn("status", ns)
        self.assertEqual(ns["nodes"][0]["confirmed"], {"at": "t1", "by": "홍길동", "rev": 1})
        doc = res.load(ns)
        cell = self.cells(doc)[("S1", "D01")]
        self.assertEqual((cell["node_rev"], cell["hold"], cell["item_id"]), (1, False, "I1"))
        self.assertEqual([(e["entry_id"], e["status"], e["recommendation"]) for e in cell["entries"]],
                         [("e1", "approved", "권고 e1")])
        with open(convert.backup_path(spath), "rb") as fh:
            self.assertEqual(fh.read(), sdata, "변환 전 원본 집합 보관")
        with open(convert.backup_path(rpath), "rb") as fh:
            self.assertEqual(fh.read(), rdata, "변환 전 원본 결과 보관")
        self.assertIsNotNone(fp)

    def test_2_repro1_previous_results_follow_members_not_ids(self):
        """재현 1: previous.S1={TK}, 지금 S1={V1}, S2={TK} → 옛 S1 칸은 S2로 간다."""
        prev = [remap.snapshot(set01(self.g, [("S1", ["TK"])]), "t0")]
        old = set01(self.g, [("S1", ["V1"]), ("S2", ["TK"])], confirmed_at="t1", previous=prev)
        spath, rpath = self.paths()
        write(spath, old)
        write(rpath, results01(set01(self.g, [("S1", ["TK"])]), "t0", [("S1", "D01", "e1")]))
        ns = sn.load(self.g)
        cells = self.cells(res.load(ns))
        self.assertEqual([e["entry_id"] for e in cells[("S2", "D01")]["entries"]], ["e1"])
        self.assertEqual(cells[("S1", "D01")]["entries"], [])

    def test_3_reopened_set_keeps_results_held_until_confirmed(self):
        prev = [remap.snapshot(set01(self.g, [("S1", ["TK", "V1"]), ("S2", ["V2"])]), "t0")]
        old = set01(self.g, [("S1", ["TK", "V1"]), ("S2", ["V2", "PP"])], status="proposed", previous=prev)
        spath, rpath = self.paths()
        write(spath, old)
        write(rpath, results01(prev[0] | {"graph_id": self.g["graph_id"], "graph_version": "v1"}, "t0",
                               [("S1", "D01", "e1"), ("S2", "D02", "e2")]))
        ns = sn.load(self.g)
        self.assertEqual({n["state"] for n in ns["nodes"]}, {"applied"})
        doc = res.load(ns)
        held = {c["node_id"]: c for c in doc["cells"] if c["entries"]}
        self.assertTrue(all(c["hold"] for c in held.values()), "확정 해제 상태라 칸은 보관")
        self.assertEqual(sorted(e["entry_id"] for c in held.values() for e in c["entries"]), ["e1", "e2"],
                         "사람이 승인한 항목이 백업에만 남지 않음")
        self.assertFalse(held["S1"]["entries"][0].get("scope_changed"), "구성요소가 같은 구간은 그대로")
        self.assertTrue(held["S2"]["entries"][0].get("scope_changed"), "넓어진 구간은 범위 바뀜")
        ns = sn.confirm_nodes(ns, self.g, ["S1"], "검토자", at=AT)
        doc = res.reconcile(doc, ns, DEVS)
        self.assertFalse(self.cells(doc)[("S1", "D01")]["hold"], "확정하면 바로 ⑤에 나타남")
        self.assertTrue(self.cells(doc)[("S2", "D02")]["hold"])

    def test_4_unmapped_cells_are_archived_and_the_rest_converts(self):
        prev = [remap.snapshot(set01(self.g, [("S1", ["TK"]), ("S9", ["LT"])]), "t0")]
        old = set01(self.g, [("S1", ["TK"]), ("S2", ["V1"])], previous=prev)
        spath, rpath = self.paths()
        write(spath, old)
        write(rpath, results01(set01(self.g, [("S1", ["TK"]), ("S9", ["LT"])]), "t0",
                               [("S1", "D01", "e1"), ("S9", "D01", "e9")]))
        ns = sn.load(self.g)
        doc = res.load(ns)
        self.assertEqual([e["entry_id"] for e in self.cells(doc)[("S1", "D01")]["entries"]], ["e1"])
        self.assertEqual([(a["reason"], a["cell"]["entries"][0]["entry_id"]) for a in doc["archived_cells"]],
                         [("legacy_unmapped", "e9")])

    def test_5_restart_after_results_were_written(self):
        old = set01(self.g, [("S1", ["TK", "V1"])])
        spath, rpath = self.paths()
        sdata = write(spath, old)
        write(rpath, results01(old, "t1", [("S1", "D01", "e1")]))
        fp = store_io.fingerprint_of(sdata)
        with open(rpath, encoding="utf-8") as fh:
            set02, res02, _r = convert.convert(old, json.load(fh), DEVS)
        res02["conversion"] = {"conversion_id": "cv-x", "source_set_fp": fp, "set_keep_excluded": []}
        res.write(rpath, res02)  # 결과만 쓰고 멈춘 상태
        ns, nfp = sn.load_fp(self.g)
        self.assertEqual((ns["schema_version"], ns.get("read_only")), ("0.2", None), "2단계부터 이어 감")
        self.assertEqual(res.load(ns)["cells"][0]["entries"][0]["entry_id"], "e1")
        # 지문이 다름(그 사이 옛 앱이 집합을 고침) → 멈춤
        write(spath, dict(old, nodes=old["nodes"] + [{"node_id": "S2", "name": "옛 앱", "origin": "rule",
                                                       "members": ids(self.g, "PP")}]))
        stopped, sfp = sn.load_fp(self.g)
        self.assertTrue(stopped.get("read_only"))
        self.assertIsNone(sfp)
        with self.assertRaises(store_io.Conflict):
            sn.save(stopped)

    def test_6_backup_failure_opens_read_only(self):
        old = set01(self.g, [("S1", ["TK"])])
        spath, _rpath = self.paths()
        sdata = write(spath, old)
        os.makedirs(convert.backup_path(spath))  # 백업 자리를 폴더로 막음
        ns, fp = sn.load_fp(self.g)
        self.assertTrue(ns.get("read_only"))
        self.assertIsNone(fp)
        with open(spath, "rb") as fh:
            self.assertEqual(fh.read(), sdata, "바꾸지 않음")

    def test_7_old_app_rejects_02_and_old_results_view_keeps_the_original(self):
        old = set01(self.g, [("S1", ["TK"])])
        spath, rpath = self.paths()
        write(spath, old)
        rdata = write(rpath, results01(old, "t1", [("S1", "D01", "e1")]))
        sn.load(self.g)
        with open(spath, encoding="utf-8") as fh:
            new = json.load(fh)
        with self.assertRaises(ValueError):
            sn.check_legacy_shape(new, spath)  # 옛 앱의 형식 검사(집합 status 필요)와 같은 검사
        with open(rpath, encoding="utf-8") as fh:
            new_res = json.load(fh)
        old_is_stale = new_res.get("study_nodes_ref") != {"graph_version": new.get("graph_version"),
                                                          "confirmed_at": new.get("confirmed_at")}
        self.assertTrue(old_is_stale, "옛 ⑤는 0.2 결과를 '이전 확정본 것'으로 보고 빈 결과로 시작한다")
        with open(convert.backup_path(rpath), "rb") as fh:
            self.assertEqual(fh.read(), rdata, "그래도 원본 결과는 보관본으로 남아 있음")

    def test_7b_old_app_shape_check_from_git_refuses_02(self):
        try:
            src = subprocess.run(["git", "-C", REPO_ROOT, "show", "0c61a1a:hazop/study/nodes.py"], capture_output=True,
                                 check=True).stdout.decode("utf-8")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git으로 옛 코드를 읽을 수 없음")
        scope = {}
        start = src.index("def _check_shape(")
        end = src.index("\n# ----", start)
        exec("STATUSES = ('keep', 'low', 'excluded')\n" + src[start:end], scope)
        with self.assertRaises(ValueError):
            scope["_check_shape"](build(self.g, [("A", ["TK"])]), "x.json")

    def test_excluded_screen_nodes_hide_unless_they_hold_entries(self):
        old = set01(self.g, [("S1", ["TK"]), ("S2", ["V1"]), ("S3", ["V2"])])
        old["nodes"][1]["screen"] = {"status": "excluded", "rule": "R3", "by": "rule"}
        old["nodes"][2]["screen"] = {"status": "excluded", "rule": "R3", "by": "rule"}
        spath, rpath = self.paths()
        write(spath, old)
        write(rpath, results01(old, "t1", [("S3", "D01", "e3")]))
        ns = sn.load(self.g)
        self.assertEqual([(n["node_id"], n["state"]) for n in ns["nodes"]], [("S1", "confirmed"), ("S3", "applied")])
        self.assertEqual([n["node_id"] for n in ns["legacy"]["excluded_nodes"]], ["S2"])
        self.assertTrue(self.cells(res.load(ns))[("S3", "D01")]["hold"])
        self.assertIn("S2", sn.issued_node_ids(ns), "숨긴 구간 번호도 다시 내지 않음")


class ViewTest(WorkRoot):
    """보기 전용 읽기(load_view)는 파일을 쓰지 않고, 편집용 열기(load_fp)가 변환·판 이전을 쓴다."""

    def files(self):
        return sorted(os.path.relpath(os.path.join(d, f), self.tmp) for d, _s, fs in os.walk(self.tmp) for f in fs)

    def test_01_file_is_converted_only_in_memory(self):
        old = set01(self.g, [("S1", ["TK", "V1"])])
        spath, rpath = sn.store_path(None, self.g["graph_id"]), res.store_path(None, self.g["graph_id"])
        sdata = write(spath, old)
        write(rpath, results01(old, "t1", [("S1", "D01", "e1")]))
        before = self.files()
        ns, info = sn.load_view(self.g)
        self.assertEqual((ns["schema_version"], info["needs_open"], bool(ns.get("read_only"))), ("0.2", True, True))
        doc = res.load_view(ns)
        self.assertEqual(doc["cells"][0]["entries"][0]["entry_id"], "e1")
        self.assertTrue(doc.get("read_only"))
        self.assertEqual(self.files(), before, "읽기만 해서는 아무 파일도 생기거나 바뀌지 않음")
        with open(spath, "rb") as fh:
            self.assertEqual(fh.read(), sdata)
        opened, fp = sn.load_fp(self.g)
        self.assertIsNotNone(fp)
        self.assertFalse(opened.get("read_only"))
        self.assertTrue(os.path.isfile(convert.backup_path(spath)), "열 때 변환하고 원본 보관")

    def test_version_change_is_shown_then_written_on_open(self):
        ns = build(self.g, [("A", ["TK"])])
        sn.save(ns)
        g2 = graph("v2", shift=10)
        before = self.files()
        view, info = sn.load_view(g2)
        self.assertTrue(info["needs_open"])
        self.assertIn("v1 → v2", info["notice"])
        self.assertEqual(view["graph_version"], "v2")
        self.assertEqual(self.files(), before)
        self.assertEqual(sn.load(g2)["graph_version"], "v2")
        again, info2 = sn.load_view(g2)
        self.assertEqual((info2["needs_open"], again.get("read_only")), (False, None))

    def test_02_results_view_writes_no_backup(self):
        ns = build(self.g, [("A", ["TK"])])
        sn.save(ns)
        doc = dict(put_entries(res.empty_results(ns, DEVS), "S1", "I1", [entry("e1")]), schema_version="0.2")
        rpath = res.store_path(None, self.g["graph_id"])
        write(rpath, doc)
        before = self.files()
        view = res.load_view(ns)
        self.assertTrue(view.get("read_only"))
        self.assertEqual(self.files(), before)
        res.load_fp(ns)
        self.assertTrue(os.path.isfile(convert.backup_path(rpath, ".v0.2.bak.json")))


class RoundTripTest(WorkRoot):
    """저장소 표본 tests/fixtures/store-0.1(0.1.x 코드가 쓴 파일)을 새 판으로 열고 닫아도 확정본·분석 결과·권고가 그대로."""

    def test_store_01_sample_survives_open_save_reopen(self):
        from tests.test_store_io import synthetic_graph
        g = synthetic_graph()
        folder = os.path.join(REPO_ROOT, "tests", "fixtures", "store-0.1")
        with open(os.path.join(folder, "study-nodes.json"), "rb") as fh:
            sdata = fh.read()
        with open(os.path.join(folder, "analysis-results.json"), "rb") as fh:
            rdata = fh.read()
        old_set, old_res = json.loads(sdata), json.loads(rdata)
        spath, rpath = sn.store_path(None, "graph-T"), res.store_path(None, "graph-T")
        for path, data in ((spath, sdata), (rpath, rdata)):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        with mock.patch.object(res, "load_deviations", lambda path=None: old_res["deviations"]):
            ns, fp = sn.load_fp(g)
            doc, rfp = res.load_fp(ns)
            sn.save(ns, expect=fp)
            res.save_fp(doc, None, expect=rfp)
            again = sn.load(g)
            doc2 = res.load(again)
        kept = [n for n in old_set["nodes"] if (n.get("screen") or {}).get("status") != "excluded"]
        self.assertEqual([(n["node_id"], n["name"], n["members"]) for n in again["nodes"]],
                         [(n["node_id"], n["name"], n["members"]) for n in kept])
        self.assertEqual({n["state"] for n in again["nodes"]}, {"confirmed"})
        self.assertEqual({(n["confirmed"]["at"], n["confirmed"]["by"]) for n in again["nodes"]},
                         {(old_set["confirmed_at"], old_set["confirmed_by"])})
        strip = lambda e: {k: v for k, v in e.items() if k != "scope_changed"}  # noqa: E731
        before = {(c["node_id"], c["deviation_id"]): (c["state"], c["entries"]) for c in old_res["cells"]
                  if c["entries"] or c["state"] != "not_analyzed"}
        after = {(c["node_id"], c["deviation_id"]): (c["state"], [strip(e) for e in c["entries"]])
                 for c in doc2["cells"] if c["entries"] or c["state"] != "not_analyzed"}
        self.assertEqual(after, before, "칸 상태·항목(승인·권고·이력)이 그대로")
        self.assertEqual(doc2["ai_log"], old_res["ai_log"])
        with open(convert.backup_path(spath), "rb") as fh:
            self.assertEqual(fh.read(), sdata)


# ---------------------------------------------------------------- ⑤ 칸(§2.4·§2.7)

class CellTest(WorkRoot):
    def setUp(self):
        super().setUp()
        self.ns = build(self.g, [("A", ["TK", "V1"]), ("B", ["V1", "V2"])])
        self.doc = put_entries(res.empty_results(self.ns, DEVS), "S1", "I1", [entry("e1")])
        put_entries(self.doc, "S2", "I2", [entry("e2")])

    def test_8_repro4_reopen_one_node_holds_only_its_cells(self):
        ns = sn.reopen_node(self.ns, "S1", at=AT)
        doc = res.reconcile(self.doc, ns, DEVS)
        hold = {(c["node_id"], c["item_id"]): c["hold"] for c in doc["cells"]}
        self.assertEqual(hold, {("S1", "I1"): True, ("S1", "I2"): True, ("S2", "I1"): False, ("S2", "I2"): False})
        self.assertEqual(res.validate(doc, ns), [], "보관 칸은 문제가 아님(재현 4b)")
        self.assertEqual(sum(len(c["entries"]) for c in doc["cells"]), 2, "결과 전체가 비지 않음")
        with self.assertRaises(ValueError):
            res.set_status(doc, "S1", "D01", "e1", "rejected", reason="시험 사유", node_set=ns)

    def test_9_one_bad_cell_is_quarantined_and_written_back(self):
        bad = copy.deepcopy(self.doc)
        bad["cells"][0]["state"] = "not_analyzed"  # 항목 있는 not_analyzed(재현 4a)
        used, doc_problems, cell_problems = res.partition(bad, self.ns)
        self.assertEqual(doc_problems, [])
        self.assertEqual(len(cell_problems), 1)
        self.assertEqual(len(used["cells"]), len(bad["cells"]) - 1)
        self.assertEqual([e["entry_id"] for c in used["cells"] for e in c["entries"]], ["e2"])
        self.assertEqual(res.disk_form(used)["cells"][-1], bad["cells"][0], "저장할 때 떼어 둔 칸을 그대로 다시 씀")

    def test_10_design_intent_change_bumps_rev_and_marks_entries(self):
        ns = sn.reopen_node(self.ns, "S1", at=AT)
        ns = sn.set_design_intent(ns, "S1", "탱크에서 펌프로 보냄", at=AT)
        self.assertEqual(sn._find(ns, "S1")["rev"], 2)
        ns = sn.confirm_nodes(ns, self.g, ["S1"], "검토자", at=AT)
        doc = res.reconcile(self.doc, ns, DEVS)
        e = next(c for c in doc["cells"] if (c["node_id"], c["item_id"]) == ("S1", "I1"))["entries"][0]
        self.assertEqual((e["scope_changed"]["from_rev"], e["scope_changed"]["to_rev"], e["status"]), (1, 2, "approved"))
        self.assertIs(res.reconcile(doc, ns, DEVS), doc, "같은 입력이면 그대로")
        doc = res.set_status(doc, "S1", "D01", "e1", "approved", at=AT, node_set=ns)
        cell = next(c for c in doc["cells"] if (c["node_id"], c["item_id"]) == ("S1", "I1"))
        self.assertNotIn("scope_changed", cell["entries"][0])
        self.assertEqual(cell["node_rev"], 2, "다시 확인하면 칸 판을 맞춤")
        self.assertIs(res.reconcile(doc, ns, DEVS), doc)

    def test_17_inserted_deviation_keeps_item_id_and_removed_one_is_archived(self):
        devs = [DEVS[0], {"deviation_id": "D02", "item_id": "I9", "parameter": "온도", "guideword": "높음",
                          "label": "온도 높음"}, dict(DEVS[1], deviation_id="D03")]
        doc = res.reconcile(self.doc, self.ns, devs)
        cell = next(c for c in doc["cells"] if (c["node_id"], c["item_id"]) == ("S2", "I2"))
        self.assertEqual((cell["deviation_id"], cell["entries"][0]["entry_id"]), ("D03", "e2"))
        self.assertEqual(len([c for c in doc["cells"] if c["item_id"] == "I9"]), 2, "새 편차 칸")
        doc = res.reconcile(doc, self.ns, [DEVS[0]])
        self.assertEqual([(a["reason"], a["cell"]["entries"][0]["entry_id"]) for a in doc["archived_cells"]],
                         [("deviation_removed", "e2")])


# ---------------------------------------------------------------- 초기사건 인계(§4.3)

class IeTest(WorkRoot):
    def setUp(self):
        super().setUp()
        self.ns = build(self.g, [("A", ["TK", "V1"]), ("B", ["V1", "V2"]), ("C", ["PP"])])
        self.doc = res.empty_results(self.ns, DEVS)

    def cause(self, eid, ref_soid="V1", mode="FTC", **kw):
        ref = sref(self.g, ref_soid)
        e = entry(eid, cause="밸브 고착", cause_refs=[{"ref": ref, "failure_mode": mode} if mode else {"ref": ref}],
                  consequence=kw.pop("consequence", "급수 상실"), ie_hint=dict(HINT), **kw)
        self.assertEqual(refs.problems(e), [], "앱이 쓰는 형식의 참조")
        return e

    def bundle(self, doc=None, ie_doc=None):
        doc = doc or self.doc
        d = ie_doc or model.sync(model.empty("P"), doc, at=AT, node_set=self.ns)
        return ib.build_bundle(doc, self.ns, self.g, d, AT), d

    def test_11_repro5_scope_changed_approval_demotes_the_group(self):
        put_entries(self.doc, "S1", "I1", [self.cause("e1")])
        d = model.sync(model.empty("P"), self.doc, at=AT, node_set=self.ns)
        iec = sorted(d["candidates"])[0]
        d, gid = model.create_group(d, "G", [iec], at=AT)
        d = model.place(d, iec, gid, at=AT)
        d = model.confirm(d, gid, self.doc, "검토자", at=AT, node_set=self.ns)
        before = model.entry_facts(self.doc, self.ns)[d["candidates"][iec]["key"]]["fp"]
        changed = copy.deepcopy(self.doc)
        changed["cells"][0]["entries"][0]["scope_changed"] = {"from_rev": 1, "to_rev": 2, "at": AT}
        after = model.entry_facts(changed, self.ns)[d["candidates"][iec]["key"]]["fp"]
        self.assertNotEqual(before, after)
        synced = model.sync(d, changed, at=AT, node_set=self.ns)
        self.assertEqual(synced["groups"][gid]["status"], "draft", "확정 근거에서 빠짐")
        self.assertIn("%s: ⑤ 범위 바뀜(다시 확인 전)" % iec, model.confirm_problems(synced, gid, changed, node_set=self.ns))

    def test_12_overlapping_same_cause_merges_into_one_candidate(self):
        put_entries(self.doc, "S1", "I1", [self.cause("e1")])
        put_entries(self.doc, "S2", "I2", [self.cause("e2")])
        b, _d = self.bundle()
        self.assertEqual(len(b["candidates"]), 1)
        c = b["candidates"][0]
        self.assertEqual((c["node_ids"], c["entry_ids"], len(c["merged_from"])), (["S1", "S2"], ["e1", "e2"], 1))
        self.assertEqual(len(b["trace"]), 2, "추적표는 항목마다 한 줄")

    def test_13_same_cause_with_different_consequence_stays_two_with_conflict(self):
        put_entries(self.doc, "S1", "I1", [self.cause("e1")])
        put_entries(self.doc, "S2", "I2", [self.cause("e2", consequence="증기발생기 고수위")])
        b, _d = self.bundle()
        self.assertEqual(len(b["candidates"]), 2)
        self.assertTrue(all(c.get("twin_conflict") for c in b["candidates"]))
        self.assertTrue(any("증기발생기 고수위" in (t.get("note") or "") for t in b["trace"]))

    def test_14_missing_failure_mode_is_not_merged(self):
        put_entries(self.doc, "S1", "I1", [self.cause("e1", mode=None)])
        put_entries(self.doc, "S2", "I2", [self.cause("e2", mode=None)])
        b, _d = self.bundle()
        self.assertEqual(len(b["candidates"]), 2)
        self.assertFalse(any(c.get("twin_conflict") or c.get("merged_from") for c in b["candidates"]))

    def test_15_repro8_same_cause_in_two_groups_blocks_until_duplicate(self):
        put_entries(self.doc, "S1", "I1", [self.cause("e1")])
        put_entries(self.doc, "S2", "I2", [self.cause("e2")])
        d = model.sync(model.empty("P"), self.doc, at=AT, node_set=self.ns)
        a, b = sorted(d["candidates"])
        d, g1 = model.create_group(d, "그룹1", [a], at=AT)
        d, g2 = model.create_group(d, "그룹2", [b], at=AT)
        d = model.place(model.place(d, a, g1, at=AT), b, g2, at=AT)
        self.assertTrue(model.confirm_problems(d, g1, self.doc, node_set=self.ns))
        self.assertTrue(model.confirm_problems(d, g2, self.doc, node_set=self.ns))
        with self.assertRaises(ValueError):
            model.confirm(d, g1, self.doc, "검토자", at=AT, node_set=self.ns)
        d = model.mark_duplicate(d, b, a, at=AT)
        self.assertEqual(model.confirm_problems(d, g1, self.doc, node_set=self.ns), [])
        self.assertEqual(model.confirm(d, g1, self.doc, "검토자", at=AT, node_set=self.ns)["groups"][g1]["status"],
                         "confirmed")

    def test_16_same_cause_in_non_overlapping_nodes_is_not_merged(self):
        put_entries(self.doc, "S1", "I1", [self.cause("e1", ref_soid="TK")])
        put_entries(self.doc, "S3", "I1", [self.cause("e3", ref_soid="TK")])
        b, _d = self.bundle()
        self.assertEqual(len(b["candidates"]), 2)
        self.assertFalse(any(c.get("merged_from") for c in b["candidates"]))

    def test_held_and_scope_changed_entries_are_left_out_of_the_bundle(self):
        put_entries(self.doc, "S1", "I1", [self.cause("e1")])
        put_entries(self.doc, "S3", "I1", [self.cause("e3", ref_soid="PP")])
        self.doc["cells"][-2]["entries"][0]["scope_changed"] = True  # S3/I1
        self.ns = sn.reopen_node(self.ns, "S1", at=AT)
        doc = res.reconcile(self.doc, self.ns, DEVS)
        b, _d = self.bundle(doc)
        self.assertEqual(b["candidates"], [])
        self.assertEqual(b["source"]["left_out_unapproved"], 2)

    def test_26_bundle_excel_opens_with_the_new_source(self):
        import openpyxl
        from hazop.ie import bundle_xlsx
        put_entries(self.doc, "S1", "I1", [self.cause("e1")])
        b, _d = self.bundle()
        self.assertEqual(b["source"]["nodes"], [{"node_id": "S1", "node_rev": 1}])
        path = os.path.join(self.tmp, "ie.xlsx")
        bundle_xlsx.export(path, b)
        wb = openpyxl.load_workbook(path)
        self.assertTrue(any("S1 r1" in str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row))


# ---------------------------------------------------------------- 구간 바꾸기·잠금·되돌리기(§2.3·§4.4·§5)

class EditTest(WorkRoot):
    def setUp(self):
        super().setUp()
        self.ns = build(self.g, [("A", ["TK", "V1"]), ("B", ["V2"])], confirm=False)
        self.doc = res.empty_results(self.ns, DEVS)

    def apply(self, ops, origin="user", ns=None, doc=None, stage=None):
        ns = ns or self.ns
        return nt.apply_nodes(ns, doc if doc is not None else self.doc, self.g, ops, {"stage": stage}, origin,
                              ns["set_rev"], at=AT)

    def held_entries(self, ns, nid):
        """확정했다가 해제해 칸에 항목이 남은 구간을 만든다."""
        ns = sn.confirm_nodes(ns, self.g, [nid], "검토자", at=AT)
        doc = put_entries(res.reconcile(self.doc, ns, DEVS), nid, "I1", [entry("h1")])
        ns = sn.reopen_node(ns, nid, at=AT)
        return ns, res.reconcile(doc, ns, DEVS)

    def test_overlap_is_allowed_but_same_member_set_is_refused(self):
        ns, _r, bid = self.apply([{"op": "add", "name": "겹침", "members": ids(self.g, "V1", "V2")}])
        self.assertEqual((bid, sn.nodes_of(ns, ids(self.g, "V1")[0])), ("B2", ["S1", "S3"]))
        with self.assertRaises(nt.Refused):
            self.apply([{"op": "add", "name": "같음", "members": ids(self.g, "V2")}], ns=ns)
        conf = sn.confirm(ns, self.g, "검토자", at=AT)
        self.assertTrue(sn.outside(conf, self.g), "구간 밖이 있어도 확정됨(㉗)")

    def test_18_removing_a_node_with_entries_needs_archive(self):
        ns, doc = self.held_entries(self.ns, "S1")
        with self.assertRaises(nt.Refused):
            self.apply([{"op": "remove", "node_id": "S1"}], ns=ns, doc=doc)
        ns2, doc2, _b = self.apply([{"op": "remove", "node_id": "S1", "archive": True}], ns=ns, doc=doc)
        self.assertNotIn("S1", [n["node_id"] for n in ns2["nodes"]])
        self.assertEqual([a["cell"]["entries"][0]["entry_id"] for a in doc2["archived_cells"]], ["h1"])

    def test_19_merge_moves_entries_as_scope_changed(self):
        ns, doc = self.held_entries(self.ns, "S2")
        ns2, doc2, _b = self.apply([{"op": "merge", "node_ids": ["S1", "S2"]}], ns=ns, doc=doc)
        cell = next(c for c in doc2["cells"] if c["node_id"] == "S1" and c["item_id"] == "I1")
        self.assertEqual(cell["entries"][0]["entry_id"], "h1")
        self.assertEqual(cell["entries"][0]["scope_changed"]["merged_from"], "S2")
        self.assertFalse(any(c["node_id"] == "S2" for c in doc2["cells"]))

    def test_22_undo_batch_cases(self):
        ns, _r, bid = self.apply([{"op": "add", "name": "새", "members": ids(self.g, "PP")}])
        undone, _doc = nt.undo_batch(ns, self.doc, bid, ns["set_rev"], "검토자", "user", at=AT)
        self.assertEqual([n["node_id"] for n in undone["nodes"]], ["S1", "S2"])
        self.assertTrue(next(b for b in undone["batches"] if b["batch_id"] == bid)["undone"])
        self.assertNotIn("S3", [n["node_id"] for n in nt.apply_nodes(
            undone, self.doc, self.g, [{"op": "add", "name": "다음", "members": ids(self.g, "LT")}], {}, "user",
            undone["set_rev"], at=AT)[0]["nodes"]], "되돌린 묶음의 번호를 다시 내지 않음")
        later = sn.rename(ns, "S3", "고친 이름", at=AT)
        with self.assertRaises(nt.Refused) as why:
            nt.undo_batch(later, self.doc, bid, later["set_rev"], "검토자", "user", at=AT)
        self.assertIn("그 사이 바뀜", str(why.exception))
        conf = sn.confirm_nodes(ns, self.g, ["S3"], "검토자", at=AT)
        with self.assertRaises(nt.Refused) as why:
            nt.undo_batch(conf, self.doc, bid, conf["set_rev"], "검토자", "user", at=AT)
        self.assertIn("확정", str(why.exception))
        held, doc = self.held_entries(ns, "S3")
        with self.assertRaises(nt.Refused):
            nt.undo_batch(held, doc, bid, held["set_rev"], "검토자", "user", at=AT)
        with self.assertRaises(nt.Refused) as why:
            nt.undo_batch(ns, self.doc, bid, ns["set_rev"], "AI", "ai", at=AT)
        self.assertIn("AI는 AI가 만든 묶음만", str(why.exception))

    def test_23_undo_without_results_is_refused(self):
        ns, _r, bid = self.apply([{"op": "add", "name": "새", "members": ids(self.g, "PP")}])
        with self.assertRaises(nt.Refused):
            nt.undo_batch(ns, None, bid, ns["set_rev"], "검토자", "user", at=AT)

    def test_24_ai_rules(self):
        refused = lambda ops, **kw: self.assertRaises(nt.Refused, self.apply, ops, "ai", **kw)  # noqa: E731
        refused([{"op": "edit", "node_id": "S1", "name": "AI가 바꿈"}])
        ai_ns, _r, _b = self.apply([{"op": "add", "name": "AI 구간", "members": ids(self.g, "PP"),
                                     "design_intent": "펌프 토출"}], origin="ai")
        human = sn.set_design_intent(ai_ns, "S3", "사람이 쓴 설계 의도", at=AT)
        refused([{"op": "edit", "node_id": "S3", "design_intent": "AI가 덮음"}], ns=human)
        ai2, _r, _b = self.apply([{"op": "add", "name": "AI 둘", "members": ids(self.g, "LT")}], origin="ai", ns=ai_ns)
        held, doc = self.held_entries(ai2, "S3")
        refused([{"op": "merge", "node_ids": ["S3", "S4"]}], ns=held, doc=doc)
        six = [{"op": "add", "name": "후보 %d" % i, "members": ids(self.g, x)}
               for i, x in enumerate(["TK", "V1", "V2", "PP", "LT", "L1"])]
        refused(six, stage="representative")
        refused([{"op": "add", "name": "ZZ-999 펌프", "members": ids(self.g, "L2")}])
        with self.assertRaises(nt.Refused):
            nt.apply_nodes(self.ns, self.doc, self.g, [{"op": "add", "name": "x", "members": ids(self.g, "PP")}], {},
                           "user", self.ns["set_rev"] - 1, at=AT)

    def test_toast_undo_of_an_edit_does_not_unconfirm_another_node(self):
        renamed = sn.rename(self.ns, "S1", "새 이름", at=AT)
        bid = renamed["batches"][-1]["batch_id"]
        conf = sn.confirm_nodes(renamed, self.g, ["S2"], "검토자", at=AT)
        undone, _doc = nt.undo_batch(conf, self.doc, bid, conf["set_rev"], "검토자", "user", at=AT)
        self.assertEqual((sn._find(undone, "S1")["name"], sn._find(undone, "S2")["state"]), ("A", "confirmed"))
        self.assertEqual(sn._find(undone, "S1")["rev"], 3, "편집 복원도 분석 판을 올림")

    def test_25_locked_node_is_skipped_and_its_entries_cannot_change(self):
        ns = sn.confirm(self.ns, self.g, "검토자", at=AT)
        doc = res.empty_results(ns, DEVS)
        for c in doc["cells"]:
            if c["node_id"] == "S1":
                c.update(state="analyzed", entries=[entry("L%s" % c["item_id"])])
        with self.assertRaises(ValueError):
            sn.lock_node(ns, "S2", "검토자", doc)  # 분석하지 않은 칸이 있음
        ns = sn.lock_node(ns, "S1", "검토자", doc, at=AT)
        self.assertEqual([u["node_id"] for u in ai_cells.plan_units(ns, DEVS)], ["S2", "S2"])
        self.assertEqual(ai_cells.plan_units(ns, DEVS, [("S1", "D01"), ("S2", "D01")]),
                         [{"unit_id": "S2/D01", "node_id": "S2", "deviation_ids": ["D01"]}])
        with self.assertRaises(ValueError):
            res.set_status(doc, "S1", "D01", "LI1", "rejected", reason="시험 사유", node_set=ns)
        with self.assertRaises(ValueError):
            nt.apply_nodes(ns, doc, self.g, [{"op": "edit", "node_id": "S1", "name": "x"}], {}, "user", ns["set_rev"])
        with self.assertRaises(ValueError):
            sn.reopen_node(ns, "S1")
        with self.assertRaises(ValueError):
            sn.unlock_node(ns, "S1", "검토자", "")
        self.assertEqual(sn.node_state(sn._find(sn.unlock_node(ns, "S1", "검토자", "다시 봄", at=AT), "S1")), "confirmed")


# ---------------------------------------------------------------- 그래프 판(§2.6)

class VersionTest(WorkRoot):
    def test_20_only_the_changed_node_needs_recheck_with_outside_components(self):
        ns = build(self.g, [("A", ["TK", "V1"]), ("B", ["V2", "PP"])])
        self.assertTrue(sn.outside(ns, self.g))
        g2 = graph("v2", shift=10)
        for n in g2["nodes"]:
            if n["source_object_id"] == "PP":
                n["kind"] = "compressor"
        out, plan = migrate.migrate_set(ns, g2, at=AT)
        self.assertEqual(sorted(plan["recheck"]), ["S2"])
        self.assertEqual([(n["state"], n["rev"]) for n in out["nodes"]], [("confirmed", 1), ("applied", 2)])
        self.assertEqual(set(out["nodes"][0]["members"]), set(ids(g2, "TK", "V1")), "ID는 새 판으로")
        same, plan2 = migrate.migrate_set(build(self.g, [("A", ["TK", "V1"])]), graph("v2", shift=10), at=AT)
        self.assertEqual((plan2["recheck"], same["nodes"][0]["state"]), ({}, "confirmed"), "구간 밖이 있어도 늘 재확인 아님")

    def test_21_locked_node_stays_locked_when_its_content_changes(self):
        ns = build(self.g, [("A", ["TK"])])
        doc = res.empty_results(ns, DEVS)
        for c in doc["cells"]:
            c["state"] = "excluded"
        ns = sn.lock_node(ns, "S1", "검토자", doc, at=AT)
        g2 = graph("v2")
        g2["nodes"][0]["tag"] = "TK-NEW"
        out, _p = migrate.migrate_set(ns, g2, at=AT)
        n = out["nodes"][0]
        self.assertEqual((n["state"], n["version_changed"]["to"], n["rev"]), ("locked", "v2", 1))


# ---------------------------------------------------------------- 적대 검토(interrogate)가 재현한 결함

class AdversaryTest(WorkRoot):
    def test_split_counts_toward_the_ai_node_limit_and_blank_names_are_refused(self):
        ns = sn.new_set(self.g)
        empty = res.empty_results(ns, DEVS)
        ops = [{"op": "add", "name": "후보 %d" % i, "members": ids(self.g, x)}
               for i, x in enumerate(["TK", "V1", "V2", "PP"])]
        ops.append({"op": "add", "name": "큰 후보", "members": ids(self.g, "LT", "L1", "L2")})
        ok, _r, _b = nt.apply_nodes(ns, empty, self.g, ops, {"stage": "representative"}, "ai", ns["set_rev"], at=AT)
        with self.assertRaises(nt.Refused):  # 한 요청에서 추가 5 + 분할 1 = 새 구간 6
            nt.apply_nodes(ns, empty, self.g, ops + [{"op": "split", "node_id": "S5", "members": ids(self.g, "LT")}],
                           {"stage": "representative"}, "ai", ns["set_rev"], at=AT)
        with self.assertRaises(nt.Refused):
            nt.apply_nodes(ok, empty, self.g, [{"op": "edit", "node_id": "S1", "name": "   "}], {}, "user",
                           ok["set_rev"], at=AT)
        with self.assertRaises(nt.Refused):
            nt.apply_nodes(ok, None, self.g, [{"op": "remove", "node_id": "S1"}], {}, "user", ok["set_rev"], at=AT)

    def test_undo_after_version_migration_restores_new_ids(self):
        ns = build(self.g, [("A", ["TK"]), ("B", ["V1"])], confirm=False)
        doc = res.empty_results(ns, DEVS)
        ns, doc, bid = nt.apply_nodes(ns, doc, self.g, [{"op": "remove", "node_id": "S2"}], {}, "user",
                                      ns["set_rev"], at=AT)
        g2 = graph("v2", shift=10)
        moved, plan = migrate.migrate_set(ns, g2, at=AT)
        self.assertEqual(plan["recheck"], {}, "확정한 적 없는 적용됨 구간은 판만 옮김")
        undone, _d = nt.undo_batch(moved, doc, bid, moved["set_rev"], "검토자", "user", at=AT)
        self.assertEqual(sn._find(undone, "S2")["members"], ids(g2, "V1"))

    def test_duplicate_resolves_twins_transitively_and_groups_point_at_bundle_candidates(self):
        ns = build(self.g, [("A", ["TK", "V1"]), ("B", ["V1", "V2"]), ("C", ["V1", "PP"])])
        doc = res.empty_results(ns, DEVS)
        cause = lambda eid: entry(eid, cause_refs=[{"ref": sref(self.g, "V1"), "failure_mode": "FTC"}],  # noqa: E731
                                  ie_hint=dict(HINT))
        for nid in ("S1", "S2", "S3"):
            put_entries(doc, nid, "I1", [cause("e" + nid)])
        d = model.sync(model.empty("P"), doc, at=AT, node_set=ns)
        a, b, c = sorted(d["candidates"])
        d = model.mark_duplicate(d, a, b, at=AT)
        with self.assertRaises(ValueError):
            model.mark_duplicate(d, b, c, at=AT)  # 사슬을 만들지 않음
        d, g = model.create_group(d, "G", [b, c], at=AT)
        d = model.place(model.place(d, b, g, at=AT), c, g, at=AT)
        self.assertEqual(model.confirm_problems(d, g, doc, node_set=ns), [])
        d2 = model.sync(model.empty("P"), doc, at=AT, node_set=ns)
        x, y, _z = sorted(d2["candidates"])
        d2, g1 = model.create_group(d2, "G1", [x], at=AT)
        d2, g2 = model.create_group(d2, "G2", [y], at=AT)
        bundle = ib.build_bundle(doc, ns, self.g, d2, AT)
        listed = {cand["candidate_id"] for cand in bundle["candidates"]}
        self.assertTrue(all(m in listed for grp in bundle["groups"] for m in grp["members"]))

    def test_locked_node_keeps_its_results_in_the_bundle_when_the_graph_changes(self):
        ns = build(self.g, [("A", ["TK"])])
        doc = res.empty_results(ns, DEVS)
        for cell in doc["cells"]:
            cell.update(state="analyzed", entries=[entry("L" + cell["item_id"], cause_refs=[
                {"ref": sref(self.g, "TK"), "failure_mode": "FTR"}], ie_hint=dict(HINT))])
        ns = sn.lock_node(ns, "S1", "검토자", doc, at=AT)
        g2 = graph("v2")
        g2["nodes"][0]["tag"] = "TK-NEW"
        moved, _p = migrate.migrate_set(ns, g2, at=AT)
        kept = res.reconcile(doc, moved, DEVS)
        self.assertFalse(any(e.get("scope_changed") for cell in kept["cells"] for e in cell["entries"]))
        b = ib.build_bundle(kept, moved, g2, model.sync(model.empty("P"), kept, at=AT, node_set=moved), AT)
        self.assertEqual([c["node_version_changed"] for c in b["candidates"]], [["S1"], ["S1"]])
        opened = sn.unlock_node(moved, "S1", "검토자", "판 바뀜 확인", at=AT)
        self.assertEqual(sn._find(opened, "S1")["rev"], 2, "풀면 분석 판이 올라 항목을 다시 봄")


class AdversaryStoreTest(WorkRoot):
    def test_reapproved_and_new_ai_entries_are_not_flagged_again(self):
        ns = build(self.g, [("A", ["TK", "V1"])])
        doc = put_entries(res.empty_results(ns, DEVS), "S1", "I1", [entry("h1"), entry("a1", "proposed", origin="ai_draft")])
        ns = sn.confirm_nodes(sn.set_design_intent(sn.reopen_node(ns, "S1"), "S1", "새 의도"), self.g, ["S1"], "검토자")
        doc = res.reconcile(doc, ns, DEVS)
        doc = res.set_status(doc, "S1", "D01", "h1", "approved", node_set=ns)
        cell = next(c for c in doc["cells"] if c["item_id"] == "I1")
        cell["entries"] = [cell["entries"][0], entry("a2", "proposed", origin="ai_draft")]  # AI 재실행이 제안 항목을 바꿈
        again = res.reconcile(doc, ns, DEVS)
        self.assertEqual([e.get("scope_changed") for c in again["cells"] if c["item_id"] == "I1" for e in c["entries"]],
                         [None, None])

    def test_malformed_cells_are_quarantined_on_load_and_read_only_set_blocks_results_save(self):
        ns = build(self.g, [("A", ["TK"])])
        sn.save(ns)
        doc = put_entries(res.empty_results(ns, DEVS), "S1", "I1", [entry("e1")])
        doc["cells"] += [None, {"item_id": "I1"}]
        res.save(doc, None)
        loaded = res.load(ns)
        used, problems, bad = res.partition(loaded, ns)
        self.assertTrue(bad)
        self.assertEqual((problems, len(used["quarantined_cells"]), [e["entry_id"] for c in used["cells"] for e in c["entries"]]),
                         ([], 2, ["e1"]))
        with self.assertRaises(store_io.Conflict):
            res.save(res.load(dict(ns, read_only="시험")), None)

    def test_legacy_results_under_a_02_set_are_backed_up_before_overwrite(self):
        old = set01(self.g, [("S1", ["TK"])])
        spath, rpath = sn.store_path(None, "graph-T"), res.store_path(None, "graph-T")
        write(spath, old)
        ns = sn.load(self.g)  # 결과가 없을 때 바뀐 0.2 집합
        rdata = write(rpath, results01(old, "t1", [("S1", "D01", "e1")]))
        doc, fp = res.load_fp(ns)
        res.save_fp(doc, None, expect=fp)
        with open(convert.backup_path(rpath), "rb") as fh:
            self.assertEqual(fh.read(), rdata)


class ReviewFixTest(WorkRoot):
    """총괄 검토(2026-11-13) 재현 R2·R3·R5·R6을 실제 형식의 데이터로."""

    def test_r2_edits_that_drop_a_judged_node_are_refused_and_merge_moves_entries(self):
        ns = build(self.g, [("A", ["TK", "V1"]), ("B", ["V2", "PP"])])
        doc = put_entries(res.empty_results(ns, DEVS), "S2", "I1", [entry("e1", cause="펌프 정지", ie_hint=dict(HINT))])
        opened = sn.reopen(ns, at=AT)
        doc = res.reconcile(doc, opened, DEVS)
        with self.assertRaises(ValueError):  # 결과를 옮기지 않는 옛 길은 확정한 적 있는 구간을 없애지 않음
            sn.merge(opened, ["S1", "S2"], at=AT)
        members = list(sn._find(opened, "S2")["members"])
        one_left = sn.remove_member(opened, "S2", members[0], at=AT)
        with self.assertRaises(ValueError):  # 마지막 구성요소를 빼면 구간이 없어지므로 거절
            sn.remove_member(one_left, "S2", members[1], at=AT)
        fresh = build(self.g, [("A", ["TK"]), ("B", ["V1"])], confirm=False)  # 확정한 적 없는 구간은 그대로 됨
        self.assertEqual(len(sn.merge(fresh, ["S1", "S2"], at=AT)["nodes"]), 1)
        gone = dict(opened, nodes=[n for n in opened["nodes"] if n["node_id"] != "S2"])
        self.assertEqual([nid for nid, _w in nt.dropped_problems(opened, gone, doc)], ["S2"], "화면이 저장 전에 쓰는 검사")
        moved, mdoc, _b = nt.apply_nodes(opened, doc, self.g, [{"op": "merge", "node_ids": ["S1", "S2"]}], {}, "user",
                                         opened["set_rev"], at=AT)
        self.assertEqual(nt.dropped_problems(opened, moved, mdoc), [])
        again = sn.confirm(moved, self.g, "검토자", at=AT)
        picked, _left = ib.approved_entries(res.reconcile(mdoc, again, DEVS), again)
        self.assertEqual([e["entry_id"] for _n, _d, e in picked], [], "옮긴 항목은 범위 바뀜이라 다시 확인 전에는 인계 안 됨")
        used, problems, bad = res.partition(res.reconcile(mdoc, again, DEVS), again)
        self.assertEqual((problems, bad), ([], []))
        self.assertEqual([e["entry_id"] for c in used["cells"] if c["node_id"] == "S1" for e in c["entries"]], ["e1"])

    def test_r3_judged_cells_without_entries_are_flagged_and_block_lock(self):
        ns = build(self.g, [("A", ["TK"])])
        doc = put_entries(res.empty_results(ns, DEVS), "S1", "I1", [entry("e9")])
        for c in doc["cells"]:
            if c["item_id"] == "I2":
                c["state"] = "excluded"  # 해당 없음
        ns2 = sn.confirm(sn.add_member(sn.reopen(ns, at=AT), "S1", ids(self.g, "V1")[0], at=AT), self.g, "검토자", at=AT)
        doc2 = res.reconcile(doc, ns2, DEVS)
        cell = next(c for c in doc2["cells"] if c["item_id"] == "I2")
        self.assertEqual((cell["scope_changed"]["from_rev"], cell["scope_changed"]["to_rev"]), (1, 2))
        doc3 = res.set_status(doc2, "S1", "D01", "e9", "approved", at=AT, node_set=ns2)
        self.assertTrue(sn.lock_problems(ns2, "S1", doc3), "칸 판정을 다시 보기 전에는 잠글 수 없음")
        doc4 = res.recheck_cell(doc3, "S1", cell["deviation_id"], "검토자", at=AT, node_set=ns2)
        self.assertEqual(sn.lock_problems(ns2, "S1", doc4), [])
        self.assertIs(res.reconcile(doc4, ns2, DEVS), doc4, "다시 확인한 뒤에는 표시가 되살아나지 않음")

    def test_r7_judged_cells_without_entries_mark_the_node_and_removal_needs_archive(self):
        ns = build(self.g, [("A", ["TK", "V1"]), ("B", ["V2"])])
        doc = res.empty_results(ns, DEVS)
        for c in doc["cells"]:
            if c["node_id"] == "S1":
                c["state"] = "excluded"  # 해당 없음(항목 없음)
        self.assertEqual(nt.judged_nodes(doc), ["S1"], "다시 제안(ID 새로 매김)을 막을 근거")
        opened = sn.reopen(ns, at=AT)
        doc = res.reconcile(doc, opened, DEVS)
        with self.assertRaises(nt.Refused):
            nt.apply_nodes(opened, doc, self.g, [{"op": "remove", "node_id": "S1"}], {}, "user", opened["set_rev"], at=AT)
        kept, kdoc, _b = nt.apply_nodes(opened, doc, self.g, [{"op": "remove", "node_id": "S1", "archive": True}], {},
                                        "user", opened["set_rev"], at=AT)
        self.assertEqual({a["cell"]["state"] for a in kdoc["archived_cells"]}, {"excluded"})

    def test_r5_any_confirmed_follows_the_01_set_status(self):
        path = os.path.join(sn.store_dir(), "P", "project-x.json")
        write(path, {"schema_version": "0.1", "kind": sn.KIND, "graph_id": "project-x", "status": "proposed",
                     "history": [], "nodes": [{"node_id": "S1", "name": "a", "members": ["m"]}]})
        self.assertFalse(sn.any_confirmed(project_only=True))
        write(path, {"schema_version": "0.1", "kind": sn.KIND, "graph_id": "project-x", "status": "confirmed",
                     "history": [], "nodes": [{"node_id": "S1", "name": "a", "members": ["m"]}]})
        self.assertTrue(sn.any_confirmed(project_only=True))

    def test_r6_archived_cells_keep_their_item_id(self):
        old = [DEVS[0], DEVS[1]]
        new = [{"deviation_id": "D01", "item_id": "I0", "parameter": "온도", "guideword": "높음", "label": "온도 높음"}] + [
            dict(d, deviation_id="D%02d" % (i + 2)) for i, d in enumerate(old)]
        set_01 = {"schema_version": "0.1", "kind": "hazop_study_nodes", "graph_id": "g", "graph_version": "v1",
                  "status": "confirmed", "confirmed_at": "T2", "confirmed_by": "a", "history": [],
                  "previous": [{"study_nodes_ref": {"graph_version": "v1", "confirmed_at": "T1"},
                                "nodes": [{"node_id": "S1", "members": ["x"]}, {"node_id": "S2", "members": ["gone"]}]}],
                  "nodes": [{"node_id": "S1", "name": "a", "members": ["x"]}]}
        res_01 = {"schema_version": "0.1", "kind": "hazop_study_results", "graph_id": "g",
                  "study_nodes_ref": {"graph_version": "v1", "confirmed_at": "T1"}, "deviations": old, "ai_log": [],
                  "cells": [{"node_id": "S2", "deviation_id": "D01", "state": "analyzed", "entries": [entry("e1")]},
                            {"node_id": "S1", "deviation_id": "D02", "state": "analyzed", "entries": [entry("e2")]}]}
        _set, res_02, _rep = convert.convert(set_01, res_01, new, at="T3")
        self.assertEqual([(a["cell"]["node_id"], a["cell"]["item_id"]) for a in res_02["archived_cells"]], [("S2", "I1")])
        self.assertEqual([(c["deviation_id"], c["item_id"]) for c in res_02["cells"] if c["entries"]], [("D03", "I2")])


# ---------------------------------------------------------------- 재현 스크립트(§12.1)를 고친 동작으로

class ReproTest(unittest.TestCase):
    def test_repro_script_shows_fixed_behaviour(self):
        g = graph("v1")
        old = {"study_nodes_ref": {"graph_version": "v1", "confirmed_at": "t0"},
               "nodes": [{"node_id": "S1", "members": ["a"]}]}
        new = {"graph_version": "v1", "nodes": [{"node_id": "S1", "members": ["b"]}, {"node_id": "S2", "members": ["a"]}]}
        self.assertEqual(remap.node_map(old, new)[0]["S1"]["node_id"], "S2", "재현 1: 구성요소로 이음")
        ns = build(g, [("A", ["TK"]), ("B", ["V1"])])
        doc = put_entries(res.empty_results(ns, DEVS[:1]), "S1", "I1", [entry("E1")])
        reopened = sn.reopen_node(ns, "S1")
        self.assertEqual(res.validate(res.reconcile(doc, reopened, DEVS[:1]), reopened), [], "재현 4b")


if __name__ == "__main__":
    unittest.main()
