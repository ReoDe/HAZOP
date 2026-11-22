"""M3 재현 시험: 다시 추출 뒤 ⑥ 초기사건 문서·FMEA·잠재 후보 판단의 참조가 조용히 다른 기호를 가리키지 않는다.

벡터 PDF 꼴(순번 id) 합성 도면. 저장은 임시 HAZOP_WORK_ROOT 아래에만 한다. 다시 추출한 그래프는 앱이 여는 차례대로
nodes.load → results.load → ie.store.load_synced → ie.store.load_fmea → expect.load_judgements·evaluate → bundle.build_bundle로 읽는다.
판정은 '같은 기호이거나 묘비'다(묘비 = idmap.is_tomb).
612de7f(M3 전)에서는 swap·drop 네 시험이 실패하고 대조군만 통과했다(fixflow/migrate2/m3/impl/out_head_612de7f.log).
뒤의 시험은 M3가 더한 것이다: 묘비가 된 기본사건은 묶음에 '확인 필요', 묘비가 남은 그룹은 다시 확정하지 못함, 묘비가 된
승인 FMEA 행은 가져옴으로 돌아감, 다시 열어도 파일이 그대로, 표지 없는 옛 문서를 판 이전 사이에 고쳤으면 묘비.
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
sys.path.insert(0, REPO_ROOT)

from hazop import paths, store_io  # noqa: E402
from hazop.ie import bundle, model  # noqa: E402
from hazop.ie import fmea as fm  # noqa: E402
from hazop.ie import store  # noqa: E402
from hazop.kg import expect  # noqa: E402
from hazop.study import follow, idmap, refs  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402

AT = "2026-11-18T00:00:00Z"
PID, GID = "P-M3", "graph-T"
DEVS = [{"deviation_id": "D01", "item_id": "I1", "parameter": "유량", "guideword": "없음", "label": "유량 없음"}]
SYMS = [("TK", "tank", "equipment", "TK-01", [0, 0, 10, 10]),
        ("V1", "manual_valve", "valve", None, [20, 0, 5, 5]),
        ("CV1", "control_valve", "valve", None, [40, 0, 5, 5]),
        ("V2", "manual_valve", "valve", None, [60, 0, 5, 5]),
        ("CV2", "control_valve", "valve", None, [80, 0, 5, 5]),
        ("FV1", "control_valve", "valve", "FV-101", [100, 0, 5, 5]),
        ("FV2", "control_valve", "valve", "FV-102", [120, 0, 5, 5]),
        ("CK1", "check_valve", "valve", None, [140, 0, 5, 5]),
        ("PP", "pump", "equipment", "PP-01", [160, 0, 10, 10]),
        ("CK2", "check_valve", "valve", None, [180, 0, 5, 5])]
CHAIN = [s[0] for s in SYMS]
SWAP = ["TK", "V2", "CV2", "V1", "CV1", "FV2", "FV1", "CK2", "PP", "CK1"]   # 같은 종류끼리 추출 순서만 바뀜
DROP = [x for x in CHAIN if x != "V1"]                                     # V1을 놓쳐 뒤 순번이 당겨짐
# (항목, 원인 기호, 고장모드, 보호수단 글, 보호수단 대상, 영향 대상)
PLAN = [("e1", "V1", "FTO", "제어밸브 CV2 자동 차단", "CV2", "PP"),
        ("e2", "CV1", "SO", "FV-102 자동 차단", "FV2", "PP"),
        ("e3", "FV1", "SO", "체크밸브 CK1 역류 방지", "CK1", "PP"),
        ("e4", "V2", "FTC", "수동밸브 V1 수동 차단", "V1", "TK")]


def drawn(version, order):
    spec = {s[0]: s for s in SYMS}
    nodes, edges, eid = [], [], {}
    for i, name in enumerate(order, 1):
        _n, kind, cat, tag, box = spec[name]
        eid[name] = "entity-node-%03d" % i
        nodes.append({"entity_id": eid[name], "node_type": "drawing_object", "kind": kind, "category": cat,
                      "tag": tag, "label_text": tag, "source_object_id": "pdf-p0-sym-%04d" % i, "id_basis": "sequence",
                      "bbox": list(box), "position": [box[0] + box[2] / 2, box[1] + box[3] / 2]})
    present = [x for x in CHAIN if x in eid]
    for i, (a, b) in enumerate(zip(present, present[1:]), 1):
        x0 = spec[a][4][0] + spec[a][4][2]
        sid = "entity-seg-%03d" % i
        nodes.append({"entity_id": sid, "node_type": "pipe_segment", "kind": "pipe_segment", "category": "pipe_segment",
                      "tag": None, "line_no": None, "source_object_id": "pdf-p0-conn-%04d" % i, "id_basis": "sequence",
                      "bbox": [x0, 2, spec[b][4][0] - x0, 1], "position": [x0, 2.5]})
        edges += [{"entity_id": "relation-%s-%s" % (sid, eid[x]), "kind": "has_endpoint", "nodes": [sid, eid[x]]}
                  for x in (a, b)]
    return {"project_id": PID, "graph_id": GID, "graph_version": version, "source": {"drawing_number": "T-1"},
            "nodes": nodes, "edges": edges}


def names(g):
    """{안정 참조·entity_id: 기호 이름}. 합성 도면이라 상자가 정체다."""
    by_box = {tuple(s[4]): s[0] for s in SYMS}
    out = {}
    for n in g["nodes"]:
        name = by_box.get(tuple(n["bbox"]), "pipe@%s" % n["bbox"][0])
        out[n["entity_id"]] = out[idmap.ref_of(n, GID)] = name
    return out


def ref(g, name):
    return next(r for r, x in names(g).items() if x == name and "#" in r)


def ent(g, name):
    return next(n["entity_id"] for n in g["nodes"] if names(g)[n["entity_id"]] == name)


def reopen(g2):
    """앱이 다시 추출한 그래프로 프로젝트를 여는 차례. M3가 읽기 함수 인자를 바꾸면 여기만 고친다."""
    ns = sn.load(g2)
    r = res.load(ns)
    ie, _fp = store.load_synced(PID, r, ns)
    fdoc = store.load_fmea(PID)[0]
    judg = expect.load_judgements(expect.store_path(PID), PID)
    return ns, r, ie, fdoc, judg


class IeRefsAfterReextractTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp
        devs = mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS))
        devs.start()
        self.addCleanup(devs.stop)
        g = self.g1 = drawn("v-1", CHAIN)
        self.ns = sn.confirm(sn.propose(g, at=AT), g, "김검토", at=AT)
        sn.save(self.ns)
        r = res.empty_results(self.ns, DEVS)
        hint = {"candidate": "yes", "origin": "human", "category": res.ie_category_table()["categories"][0]["code"],
                "disturbs": "yes", "challenges": "yes", "safety_functions": [], "reason": "사람 판정"}
        for eid, cause, mode, sgt, sg, cons in PLAN:
            cell = next(c for c in r["cells"] if c["node_id"] == sn.nodes_of(self.ns, ent(g, cause))[0])
            cell["state"] = "analyzed"
            cell["entries"].append({
                "entry_id": eid, "origin": "human", "status": "approved", "cause": "%s %s" % (cause, mode),
                "cause_kind": "equipment", "cause_refs": [{"ref": ref(g, cause), "failure_mode": mode}],
                "consequence": "하류 유량 상실", "consequence_basis": "unmitigated", "consequence_refs": [{"ref": ref(g, cons)}],
                "safeguards": [{"text": sgt, "role": "mitigative", "actuation": "auto", "refs": [{"ref": ref(g, sg)}]}],
                "recommendation": None, "severity": 2, "frequency": 2, "risk": 2, "ie_hint": dict(hint),
                "ai_basis": {"kg_paths": [], "sources": [], "equipment_tags": [], "warnings": []}})
        res.save(r, PID)
        ie = model.suggest(model.sync(model.empty(PID), r, node_set=self.ns, at=AT), r, pg=g, at=AT)
        for iec in list(ie["candidates"]):
            ie = model.accept(ie, ("member", iec), at=AT)
        for kind, (table, _p) in model.COLLECTIONS.items():
            for rid, rec in list(ie[table].items()):
                if rec.get("origin") == "ai_draft":
                    ie = model.accept(ie, (kind, rid), at=AT)
        for gid in model.live_groups(ie):
            ie = model.confirm(ie, gid, r, "김검토", at=AT, node_set=self.ns)
        store.save(ie, expect=None)
        f = fm.empty(PID)
        f, _rep = fm.import_rows(f, [
            {"tag": "FV-102", "failure_mode": "열림 실패", "failure_code": "FTO", "cause": "구동기 고장", "line": 2},
            {"tag": "(태그 없음) 수동밸브", "failure_mode": "닫힘 실패", "failure_code": "FTC", "cause": "고착", "line": 3},
            {"tag": "(태그 없음) 체크밸브", "failure_mode": "역류", "failure_code": "FTC", "cause": "디스크 고착", "line": 4}],
            g, self.ns, "fmea.xlsx", "김검토", at=AT)
        f = fm.edit_row(f, "FM-002", {"entity_id": ent(g, "V2")}, g, self.ns, at=AT)
        f = fm.edit_row(f, "FM-003", {"entity_id": ent(g, "CK2")}, g, self.ns, at=AT)
        store.save_fmea(fm.set_status(f, ["FM-001", "FM-002", "FM-003"], "approved", "김검토", at=AT), expect=None)
        self.ie1, _fp = store.load_synced(PID, r, self.ns)
        self.fmea1 = store.load_fmea(PID)[0]
        self.judged = []
        for it in expect.evaluate(g)["items"]:
            who = names(g)[it["target_entity"]]
            if it["rule_id"] == "E04" and who == "CV1":
                rec = expect.apply_action(it, "absent", "김검토", reason="고장 위치 표시 없음", evidence="T-1 1쪽", at=AT)
            elif it["rule_id"] == "E04" and who == "CV2":
                rec = expect.apply_action(it, "not_applicable", "김검토", reason="수동 조작 전용", at=AT)
            elif it["rule_id"] == "E01" and it["found"]:
                pick = next(x["ref"] for x in it["found"] if names(g).get(x["ref"]) == "CK1")
                rec = expect.apply_action(it, "confirm", "김검토", at=AT, found_ref=pick)
            else:
                continue
            expect.save_judgement(expect.store_path(PID), PID, rec)
            self.judged.append((rec["key"], who, [names(g)[x] for x in rec["found"]]))
        self.bundle1 = bundle.build_bundle(r, self.ns, g, self.ie1, AT, fmea=self.fmea1)

    def tearDown(self):
        if self._old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self._old
        shutil.rmtree(self.tmp)

    def assertSameOrTomb(self, before, after, g2, what):
        """before(옛 판 값)가 가리키던 기호와 after(새 판 값)가 가리키는 기호가 같거나, after가 묘비여야 한다."""
        if idmap.is_tomb(after):
            return
        self.assertEqual(names(g2).get(after), names(self.g1)[before],
                         "%s: %s(%s)가 다시 추출 뒤 %s를 가리킴" % (what, before, names(self.g1)[before], names(g2).get(after)))

    def check_refs(self, order):
        g2 = drawn("v-2", order)
        _ns, _r, ie2, f2, judg = reopen(g2)
        for hid, h in self.ie1["headings"].items():
            for a, b in zip(h["targets"], ie2["headings"][hid]["targets"]):
                self.assertSameOrTomb(a, b, g2, "표제 %s 대상" % hid)
        for bid, b in self.ie1["basic_events"].items():
            self.assertSameOrTomb(b["ref"], ie2["basic_events"][bid]["ref"], g2, "기본사건 %s" % bid)
            self.assertTrue(ie2["basic_events"][bid]["key"].startswith(ie2["basic_events"][bid]["ref"] + "|"),
                            "기본사건 %s 열쇠가 참조와 같이 옮겨져야 함" % bid)
        for rid, row in self.fmea1["rows"].items():
            for fld in ("ref", "entity_id"):
                self.assertSameOrTomb(row[fld], f2["rows"][rid][fld], g2, "FMEA %s.%s" % (rid, fld))
        was = {(key.partition("|")[0], who): found for key, who, found in self.judged}
        for k, rec in judg.items():
            rule, _s, target = k.partition("|")
            if idmap.is_tomb(target):
                continue
            now = (rule, names(g2).get(target))
            self.assertIn(now, was, "잠재 후보 판단 %s(원래 %s)가 다시 추출 뒤 %s에 붙음" % (k, rec.get("target_tag"), now[1]))
            self.assertEqual([names(g2).get(x) for x in rec.get("found") or [] if not idmap.is_tomb(x)],
                             [x for x, y in zip(was[now], rec.get("found") or []) if not idmap.is_tomb(y)],
                             "잠재 후보 판단 %s의 찾은 대상" % k)

    def check_bundle(self, order):
        """인계 묶음의 표제 대상 글은 원래 기호의 이름이거나 '대상 없음'이어야 한다(다른 기호의 태그가 실리면 안 됨)."""
        g2 = drawn("v-2", order)
        ns2, r2, ie2, f2, _j = reopen(g2)
        b2 = bundle.build_bundle(r2, ns2, g2, ie2, AT, fmea=f2)
        before = {t["heading_id"]: t["targets"] for t in self.bundle1["top_events"]}
        for t in b2["top_events"]:
            for a, b in zip(before[t["heading_id"]], t["targets"]):
                self.assertIn(b, (a, idmap.LOST_LABEL), "묶음 표제 %s 대상 %r가 %r로 바뀜" % (t["heading_id"], a, b))
        idx2 = refs.index(g2)
        for b in b2["basic_events"]:
            raw = ie2["basic_events"][b["be_id"]]["ref"]
            if idmap.is_tomb(raw):
                continue
            n = idx2.get(raw)
            self.assertIsNotNone(n, "묶음 기본사건 %s의 참조가 새 판에 없는데 묘비가 아님" % b["be_id"])
            self.assertEqual(n.get("kind"), b["equipment_kind"] or n.get("kind"),
                             "묶음 기본사건 %s: 기기 종류 %s인데 참조는 %s" % (b["be_id"], b["equipment_kind"], n.get("kind")))
            if n.get("tag"):
                self.assertIn(n["tag"], (b["tag"], refs.node_text(n)), "묶음 기본사건 %s 태그" % b["be_id"])

    def test_swap_refs_follow_the_drawn_symbol(self):
        self.check_refs(SWAP)

    def test_drop_refs_follow_or_become_tombs(self):
        self.check_refs(DROP)

    def test_bundle_swap_does_not_carry_another_tag(self):
        self.check_bundle(SWAP)

    def test_bundle_drop_does_not_carry_another_tag(self):
        self.check_bundle(DROP)

    def test_untouched_extraction_changes_nothing(self):
        """대조군: 같은 순서로 다시 추출하면(판만 바뀜) 모든 참조가 그대로다. 고치기 전에도 통과해야 한다."""
        self.check_refs(CHAIN)
        self.check_bundle(CHAIN)


    # ---------------------------------------------------------------- M3가 더한 것

    def test_bundle_marks_a_lost_basic_event_for_checking(self):
        g2 = drawn("v-2", DROP)
        ns2, r2, ie2, f2, _j = reopen(g2)
        lost = sorted(b for b, x in ie2["basic_events"].items() if idmap.is_tomb(x["ref"]))
        self.assertTrue(lost, "V1을 놓친 다시 추출에서 V1 기본사건은 묘비")
        out = {b["be_id"]: b for b in bundle.build_bundle(r2, ns2, g2, ie2, AT, fmea=f2)["basic_events"]}
        self.assertTrue(set(lost) & set(out), "묘비 기본사건이 묶음에 듦")
        for bid in set(lost) & set(out):
            self.assertTrue(out[bid]["tag"].startswith(bundle.CHECK_TAG), out[bid])
            self.assertEqual(out[bid]["ref"], idmap.LOST_LABEL)

    def test_groups_with_lost_targets_cannot_be_confirmed_again(self):
        """사람이 ⑤를 다시 승인하고 그룹을 다시 확정해도 묘비가 남은 그룹은 확정되지 않고, 확정된 그룹의 표제는 지금 도면의
        기호를 가리킨다."""
        g2 = drawn("v-2", DROP)
        ns2, r2, ie2, f2, _j = reopen(g2)
        ns3 = sn.confirm(ns2, g2, "김검토", at=AT) if any(n["state"] == "applied" for n in ns2["nodes"]) else ns2
        r3 = res.reconcile(r2, ns3, DEVS, at=AT)
        for c in r3["cells"]:
            for e in list(c["entries"]):
                if e.get("scope_changed"):
                    r3 = res.set_status(r3, c["node_id"], c["deviation_id"], e["entry_id"], "approved", at=AT,
                                        node_set=ns3, by="김검토")
            if c.get("scope_changed"):
                r3 = res.recheck_cell(r3, c["node_id"], c["deviation_id"], "김검토", at=AT, node_set=ns3)
        facts = model.entry_facts(r3, ns3)
        refused, confirmed = {}, []
        for gid in model.live_groups(ie2):
            lost = model.lost_problems(ie2, gid, facts)
            try:
                ie2 = model.confirm(ie2, gid, r3, "김검토", at=AT, node_set=ns3)
                self.assertFalse(lost, "묘비가 남은 %s가 확정됨" % gid)
                confirmed.append(gid)
            except ValueError as exc:
                refused[gid] = str(exc)
        self.assertTrue(any("다시 추출 뒤 찾지 못함" in x for x in refused.values()), refused)
        self.assertTrue(confirmed, "묘비가 없는 그룹은 다시 확정됨")
        idx = refs.index(g2)
        for grp in bundle.build_bundle(r3, ns3, g2, ie2, AT, fmea=f2)["groups"]:
            if grp["status"] == "confirmed":
                for hid in grp["heading_ids"]:
                    for t in ie2["headings"][hid]["targets"]:
                        self.assertIn(t, idx, "확정 그룹 %s의 표제 %s 대상 %s" % (grp["group_id"], hid, t))

    def test_approved_fmea_row_on_a_lost_symbol_goes_back_to_imported(self):
        f, fp = store.load_fmea(PID)
        f = fm.edit_row(f, "FM-003", {"entity_id": ent(self.g1, "V1")}, self.g1, self.ns, at=AT)
        store.save_fmea(fm.set_status(f, ["FM-003"], "approved", "김검토", at=AT), expect=fp)
        g2 = drawn("v-2", DROP)
        _ns, _r, _ie, f2, _j = reopen(g2)
        row = f2["rows"]["FM-003"]
        self.assertTrue(idmap.is_tomb(row["ref"]) and idmap.is_tomb(row["entity_id"]), row)
        self.assertEqual(row["status"], "imported")
        with self.assertRaises(ValueError):
            fm.set_status(f2, ["FM-003"], "approved", "김검토", at=AT)

    def test_reopening_again_writes_nothing(self):
        g2 = drawn("v-2", SWAP)
        reopen(g2)
        files = [store.store_path(PID), store.fmea_path(PID), expect.store_path(PID)]
        before = [store_io.fingerprint(p) for p in files]
        _ns, _r, ie2, _f2, _judg = reopen(g2)
        self.assertEqual([store_io.fingerprint(p) for p in files], before)
        self.assertIs(follow.follow(ie2, idmap.IE, sn.load(g2))[0], ie2)
        self.assertEqual(ie2["ref_versions"][GID], {"graph_version": "v-2", "step": 1})

    def test_unmarked_doc_edited_across_a_migration_is_lost_not_moved(self):
        """판 표지가 없는 옛 문서를 판 이전 사이에 고쳤으면 어느 판의 참조인지 모르므로 이 도면 참조는 모두 묘비다."""
        with open(store.store_path(PID), encoding="utf-8") as fh:
            doc = json.load(fh)
        doc.pop("ref_versions", None)
        doc.pop("ref_migrations", None)
        g2 = drawn("v-2", SWAP)
        ns2 = sn.load(g2)
        doc["history"].append({"at": "9999-01-01T00:00:00Z", "op": "edit", "ids": []})
        moved, rep = follow.follow(doc, idmap.IE, ns2)
        self.assertIn(rep["unproven"], (follow.MIXED, follow.YOUNGER))
        self.assertTrue(all(idmap.is_tomb(t) for h in moved["headings"].values() for t in h["targets"]))
        self.assertTrue(all(idmap.is_tomb(b["ref"]) for b in moved["basic_events"].values()))

    def test_every_registered_field_is_met_and_no_old_id_is_left_elsewhere(self):
        """등록부(IE·FMEA·LATENT)의 자리가 실제 문서에 나오고, 판 이전이 등록되지 않은 자리에서 옛 id를 만나지 않는다."""
        ie, fp = store.load(PID)
        hid = sorted(ie["headings"])[0]
        ie = model.accept(ie, ("heading", hid), at=AT)
        store.save(model.edit(ie, ("heading", hid), {"targets": [ref(self.g1, "TK")]}, at=AT), expect=fp)
        key, _who, _found = self.judged[0]
        rec = expect.load_judgements(expect.store_path(PID), PID)[key]
        for why in ("다시 봄", "또 봄"):
            expect.save_judgement(expect.store_path(PID), PID, dict(rec, reason=why, rejected=[ref(self.g1, "CK2")]))
        docs = {idmap.IE: store.load(PID)[0], idmap.FMEA: store.load_fmea(PID)[0],
                idmap.LATENT: expect.load_store(expect.store_path(PID), PID)}
        for kind, d in docs.items():
            for path, _space in idmap.FIELDS[kind]:
                base = path[:-2] if path.endswith("{}") else path
                self.assertTrue([h[k] for h, k in idmap.walk(d, base)], "죽은 등록 항목이거나 고정 자료가 그 길을 타지 않음: %s %s"
                                % (kind, path))
        g2 = drawn("v-2", DROP)
        reopen(g2)
        docs = {idmap.IE: store.load(PID)[0], idmap.FMEA: store.load_fmea(PID)[0],
                idmap.LATENT: expect.load_store(expect.store_path(PID), PID)}
        for kind, d in docs.items():
            self.assertEqual(d["ref_migrations"][-1]["unregistered"], [], kind)
            self.assertTrue(d["ref_migrations"][-1]["refs_changed"], "순번이 당겨져 실제로 옮김: %s" % kind)


if __name__ == "__main__":
    unittest.main()
