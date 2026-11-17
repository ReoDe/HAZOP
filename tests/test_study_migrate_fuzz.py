"""판 이전 불변식 퍼즈(hazop.study.migrate·idmap). 합성 도면을 v1 → v2 → v3로 다시 추출한 것처럼 바꾸고(기호 지움·옮김·
종류·태그 바꿈·되살림·순서 섞임), 무작위 검토구간 집합(편집 묶음 포함)과 ⑤ 결과를 판 이전한 뒤 진실(노드의 _uid, 판 이전
코드는 보지 않음)과 견준다. 도면 꼴은 벡터 PDF·스캔(img-)·drawio·DEXPI(파일 id와 가져오기가 지은 id가 섞임)이고,
집합 꼴은 새 꼴·A꼴(표시 없음)·B꼴(순번 정규식 표시, lost_members)이다.

불변식
① 옛 구성요소는 이어지거나 묘비가 된다. 조용히 사라지지 않는다(실행 취소 기록 포함).
② 표지(종류·태그·상자)가 다른 기호끼리 잇지 않는다. 표지가 같은 다른 기호는 알려진 한계로 따로 센다.
③ 묘비는 되찾기 말고는 어떤 기호도 가리키지 않는다(실행 취소 뒤, ⑤ 참조·잠재 후보 ID·근거 경로 포함).
④ 같은 판 이전을 두 번 해도 같다.
⑤ 예외가 없다.
⑥ 등록되지 않은 자리에서 옛 id를 만나지 않는다.
⑦ 순번 구성요소를 이었으면 앞뒤 기호의 종류·태그·위치가 같다.
"""

import collections
import copy
import json
import os
import random
import shutil
import sys
import tempfile
import traceback
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import ids  # noqa: E402
from hazop.kg import expect  # noqa: E402
from hazop.study import idmap, migrate, node_tools  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402

SEEDS = 300
GID = "graph-T"
KINDS = ["manual_valve", "manual_valve", "manual_valve", "pump", "tank", "check_valve"]
TAGS = [None, None, None, "V-1", "V-2", "P-1", "V-1"]
FORMATS = ["pdf_vector", "pdf_vector", "raster_png", "drawio", "dexpi"]
LIMIT = "표지가 같은 다른 기호(알려진 한계)"


# ---------------------------------------------------------------- 판 이전 결과를 읽는 자리(옛 판 코드와 견줄 때 이 함수들만 바꾼다)

def lost_of(node):
    return list(node.get("lost") or [])


def tomb_entity(ns, t):
    return ((ns.get("tombstones") or {}).get(t) or {}).get("entity_id")


def is_tomb(x):
    return idmap.is_tomb(x)


def step_lost(detail):
    return set(detail.get("lost") or {})


def unregistered(ns2, res2):
    rows = [h["detail"] for h in ns2["history"] if h["op"] == migrate.OP]
    rows += res2.get("version_migrations") or []
    return [p for r in rows for p in r.get("unregistered") or []]


def to_b_form(ns, g):
    """49033f1 판이 썼을 꼴: 표시는 순번 정규식에 걸린 것만, id 근거 없음, 묘비 대신 lost_members."""
    out = copy.deepcopy(ns)
    out.pop("graph_member_basis", None)
    out.pop("tombstones", None)
    out["schema_version"] = "0.2"
    out["graph_member_marks"] = idmap.legacy_marks(g)
    return out


def to_a_form(ns, g):
    out = to_b_form(ns, g)
    out.pop("graph_member_marks")
    return out


# ---------------------------------------------------------------- 합성 도면

def place(r):
    return [r.randrange(0, 12) * 20.0, r.randrange(0, 3) * 20.0, 5.0, 5.0]


def make_world(r):
    syms = [{"uid": "s%d" % u, "kind": r.choice(KINDS), "tag": r.choice(TAGS), "bbox": place(r),
             "nobox": r.random() < 0.05, "fixed": r.random() < 0.15} for u in range(r.randint(2, 9))]
    if r.random() < 0.3 and len(syms) > 1:  # 태그 없는 같은 종류가 같은 자리(알려진 한계)
        syms[1].update(kind=syms[0]["kind"], tag=None, bbox=list(syms[0]["bbox"]))
    juncs = [{"uid": "j%d" % u, "kind": "tee", "tag": None, "bbox": place(r)[:2] + [2.0, 2.0], "nobox": False,
              "fixed": False} for u in range(r.randint(0, 2))]
    allu = [s["uid"] for s in syms + juncs]
    pipes = [{"uid": "c%d" % u, "ends": r.sample(allu, 2), "bbox": place(r)[:2] + [15.0, 1.0],
              "nobox": r.random() < 0.05, "tag": r.choice([None, "L-1"])} for u in range(r.randint(1, 6))]
    return {"syms": syms, "juncs": juncs, "pipes": pipes, "next": 100, "fmt": r.choice(FORMATS),
            "basis": r.random() > 0.1}


def mutate(r, w):
    w = copy.deepcopy(w)
    out = []
    for s in w["syms"]:
        x = r.random()
        if x < 0.15:
            w.setdefault("deleted", []).append(s)
            continue
        if x < 0.25:
            s["bbox"] = place(r)
        elif x < 0.30:
            s["kind"] = r.choice(KINDS)
        elif x < 0.40:
            s["tag"] = r.choice(TAGS)
        out.append(s)
    for d in list(w.get("deleted") or []):
        if r.random() < 0.15:  # 지운 자리에 다른 기호(새 uid)
            w["next"] += 1
            out.append(dict(d, uid="s%d" % w["next"], tag=None))
    for d in list(w.get("deleted") or []):
        if r.random() < 0.4 and d["uid"] not in {s["uid"] for s in out}:  # 같은 기호가 돌아옴
            out.append(copy.deepcopy(d))
            w["deleted"].remove(d)
    for _ in range(r.randint(0, 2)):
        w["next"] += 1
        out.append({"uid": "s%d" % w["next"], "kind": r.choice(KINDS), "tag": r.choice(TAGS), "bbox": place(r),
                    "nobox": False, "fixed": r.random() < 0.15})
    w["syms"] = out
    alive = {s["uid"] for s in out + w["juncs"]}
    for p in w["pipes"]:
        p["ends"] = [e for e in p["ends"] if e in alive]
        if r.random() < 0.1:
            p["bbox"] = place(r)[:2] + [15.0, 1.0]
    w["order_seed"] = r.random()
    return w


def soid_of(fmt, s, k, what):
    """(source_object_id, 어댑터가 지은 id인가). k는 그 판의 열거 순번."""
    if fmt == "drawio":
        return ("edge-" if what == "conn" else "cell-") + s["uid"], False
    if fmt == "dexpi":
        if what == "conn":
            return "Seg_1__Connection_%d" % k, True
        if what == "junction" or s["fixed"]:
            return "Item-" + s["uid"], False
        return "Seg_1__item_%d" % k, True
    if s.get("fixed"):
        return "manual-c-" + s["uid"], False
    head = "img" if fmt == "raster_png" else "pdf-p0"
    return "%s-%s-%04d" % (head, what, k), False


def build(w, version):
    fmt, key = w["fmt"], random.Random(w.get("order_seed", 0))
    nodes, by_uid, edges = [], {}, []

    def add(eid, s, k, what, extra):
        soid, made = soid_of(fmt, s, k, what)
        n = dict({"entity_id": eid, "source_object_id": soid, "bbox": None if s["nobox"] else list(s["bbox"]),
                  "_uid": s["uid"]}, **extra)
        if w["basis"]:
            n["id_basis"] = ids.basis(fmt, soid, made)
        nodes.append(n)
        by_uid[s["uid"]] = n
    for i, s in enumerate(sorted(w["syms"], key=lambda s: key.random()), 1):
        add("entity-node-%03d" % i, s, i, "sym", {"node_type": "drawing_object", "kind": s["kind"], "tag": s["tag"]})
    base = len(nodes)
    for j, s in enumerate(w["juncs"], 1):
        add("entity-node-%03d" % (base + j), s, j, "junction", {"node_type": "drawing_object", "kind": "tee", "tag": None})
    rel = 0
    for i, p in enumerate(sorted(w["pipes"], key=lambda s: key.random()), 1):
        sid = "entity-seg-%03d" % i
        add(sid, p, i, "conn", {"node_type": "pipe_segment", "kind": "pipe_segment", "tag": p["tag"], "line_no": p["tag"]})
        for e in p["ends"]:
            rel += 1
            edges.append({"entity_id": "relation-%03d" % rel, "kind": "has_endpoint", "nodes": [sid, by_uid[e]["entity_id"]]})
    return {"project_id": None, "graph_id": GID, "graph_version": version, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------- 집합과 결과

def make_set(r, g):
    ns = sn.new_set(g)
    ids_ = [n["entity_id"] for n in g["nodes"]]
    for i in range(r.randint(1, 4)):
        mem = sorted(r.sample(ids_, r.randint(1, len(ids_))))
        ns["nodes"].append(dict({"node_id": "S%d" % (i + 1), "name": "n%d" % i, "basis": "b", "members": mem},
                                **sn._v2_fields("script")))
    for _ in range(r.randint(0, 3)):  # 실행 취소 기록을 만드는 편집
        live = [n for n in ns["nodes"] if n["state"] == "applied"]
        try:
            x = r.random()
            if x < 0.4 and live:
                n = r.choice(live)
                if len(n["members"]) > 1:
                    ns = sn.split(ns, n["node_id"], r.sample(n["members"], len(n["members"]) // 2), at="t")
            elif x < 0.7 and live:
                n = r.choice(live)
                ns = sn.remove_member(ns, n["node_id"], r.choice(n["members"]), at="t")
            elif len(live) > 1:
                ns = sn.merge(ns, [n["node_id"] for n in r.sample(live, 2)], at="t")
        except ValueError:
            pass
    pick = [n["node_id"] for n in ns["nodes"] if r.random() < 0.6]
    if pick:
        ns = sn.confirm_nodes(ns, g, pick, "x", at="t")
    for n in ns["nodes"]:
        if n["state"] == "confirmed" and r.random() < 0.2:
            n["state"], n["locked"] = "locked", {"at": "t", "by": "x"}
    form = r.choice(["new", "new", "a", "b", "b"])
    if form == "a":
        ns = to_a_form(ns, g)
    elif form == "b":
        ns = to_b_form(ns, g)
        for n in ns["nodes"]:
            if r.random() < 0.15:  # 앞 판 이전이 남긴 잃은 기록(되찾을 수 없는 자리, 손상 기록)
                n["lost_members"] = r.choice([
                    [{"entity_id": "entity-node-900", "ref": GID + "#pdf-p0-sym-0900",
                      "mark": ["drawing_object", None, "pump", None, 999.0, 999.0, 1004.0, 1004.0], "from": "v-0"}],
                    [None], ["x"], [{}]])
    return ns, form


def make_results(ns, g, r):
    by_id = {n["entity_id"]: n for n in g["nodes"]}
    cells = []
    for n in ns["nodes"]:
        refs = [idmap.ref_of(by_id[m], GID) for m in n["members"]]
        path = list(n["members"]) + ["cond-001"]
        touching = [e["entity_id"] for e in g["edges"] if set(e["nodes"]) & set(n["members"])]
        if touching and r.random() < 0.5:
            path.append(r.choice(touching))
        cells.append({"node_id": n["node_id"], "entries": [{
            "cause_refs": [{"ref": x} for x in refs], "consequence_refs": [],
            "safeguards": [{"refs": [{"ref": x} for x in refs]}],
            "expectation_refs": [expect.expectation_id("R-1", x) for x in refs],
            "ai_basis": {"kg_paths": [path]}}]})
    return {"schema_version": "0.3", "graph_id": GID, "graph_version": g["graph_version"], "cells": cells}


# ---------------------------------------------------------------- 판정

def look(n):
    return (n.get("kind"), n.get("tag"), n.get("bbox"))


def same_look(a, b):
    la, lb = look(a), look(b)
    if la[:2] != lb[:2] or (la[2] is None) != (lb[2] is None):
        return False
    return la[2] is None or all(abs(x - y) <= idmap.MARK_TOL for x, y in zip(la[2], lb[2]))


class Judge:
    def __init__(self):
        self.stats = collections.Counter()
        self.examples = collections.defaultdict(list)

    def note(self, kind, info):
        self.stats[kind] += 1
        if len(self.examples[kind]) < 3:
            self.examples[kind].append(info)

    def holders(self, ns):
        """(자리 이름, members를 가진 사전) 집합의 구간과 실행 취소 기록의 before·after."""
        out = [("node:" + n["node_id"], n) for n in ns["nodes"]]
        for b in ns.get("batches") or []:
            for i, o in enumerate(b["ops"]):
                for side in ("before", "after"):
                    if isinstance(o.get(side), dict):
                        out.append(("%s/%d/%s" % (b["batch_id"], i, side), o[side]))
        return out

    def step(self, seed, ns_a, ns_b, g_a, g_b, graphs):
        d = ns_b["history"][-1]["detail"]
        lost, renamed = step_lost(d), d.get("renamed") or {}
        self.stats["되찾은 묘비"] += len(d.get("found") or {})
        ua = {n["entity_id"]: n for n in g_a["nodes"]}
        ub = {n["entity_id"]: n for n in g_b["nodes"]}
        basis_a = idmap.bases(g_a)
        after = dict(self.holders(ns_b))
        for where, b in self.holders(ns_a):
            a = after.get(where)
            if a is None:
                self.note("① 자리가 사라짐", (seed, where))
                continue
            tomb_eids = {tomb_entity(ns_b, t) for t in lost_of(a)}
            for t in lost_of(a):
                if not is_tomb(t) or t in ub:
                    self.note("③ lost에 살아 있는 id", (seed, where, t))
            for m in b["members"]:
                self.stats["구성요소 점검"] += 1
                if m in lost:
                    if m not in tomb_eids:
                        self.note("① 사라짐(잃었는데 묘비 없음)", (seed, where, m))
                    continue
                t = renamed.get(m, m)
                if t not in a["members"]:
                    self.note("① 사라짐(이은 구성요소가 members에도 lost에도 없음)", (seed, where, m, t))
                    continue
                o, nn = ua.get(m), ub.get(t)
                if o is None or nn is None:
                    self.note("① 그래프에 없는 id가 members에 남음", (seed, where, m, t))
                    continue
                if o["_uid"] != nn["_uid"]:
                    self.note(LIMIT if same_look(o, nn) else "② 표지가 다른 기호로 이음", (seed, where, m, t, look(o), look(nn)))
                elif basis_a[m] == ids.SEQUENCE and not same_look(o, nn):
                    self.note("⑦ 순번 구성요소인데 표지가 다른 기호로 이음", (seed, where, m, t, look(o), look(nn)))
            back = self.found_nodes(ns_b, b, graphs)
            allowed = {ua[m]["_uid"] for m in b["members"] if m in ua} | {n["_uid"] for n in back}
            for e in a["members"]:
                if e not in ub:
                    self.note("③ 새 판에 없는 id가 members에 있음", (seed, where, e))
                elif ub[e]["_uid"] not in allowed:
                    old = [ua[m] for m in b["members"] if renamed.get(m, m) == e and m in ua] + back
                    same = any(same_look(o, ub[e]) for o in old)
                    self.note(LIMIT if same else "② 구간에 없던 기호가 members에 들어옴", (seed, where, e, ub[e]["_uid"]))

    def found_nodes(self, ns_b, b, graphs):
        """b(판 이전 전)의 묘비 가운데 이번에 되찾은 것이 잃기 전 가리키던 기호(진실 그래프의 노드)."""
        out = []
        for t in b.get("lost") or []:
            rec = (ns_b.get("tombstones") or {}).get(t) or {}
            g = graphs.get(rec.get("lost_from"))
            if rec.get("found") and g is not None:
                out += [n for n in g["nodes"] if n["entity_id"] == rec.get("entity_id")]
        return out

    def undo(self, seed, ns_a, ns_b, graphs):
        """판 이전 뒤 마지막 묶음을 되돌리고 되살린 구간이 옛 기록의 기호만 갖는지 본다."""
        live = [b for b in ns_b.get("batches") or [] if not b.get("undone")]
        if not live:
            return
        bid = live[-1]["batch_id"]
        try:
            out, _ = node_tools.undo_batch(ns_b, {"cells": []}, bid, ns_b["set_rev"], "x", "user", at="t")
        except node_tools.Refused:
            return
        self.stats["되돌림"] += 1
        g_a, g_b = graphs[ns_a["graph_version"]], graphs[ns_b["graph_version"]]
        ua = {n["entity_id"]: n for n in g_a["nodes"]}
        ub = {n["entity_id"]: n for n in g_b["nodes"]}
        before = next(b for b in ns_a["batches"] if b["batch_id"] == bid)
        for o in before["ops"]:
            if o["before"] is None:
                continue
            node = next((n for n in out["nodes"] if n["node_id"] == o["node_id"]), None)
            if node is None:
                continue
            back = self.found_nodes(ns_b, o["before"], graphs)
            allowed = {ua[m]["_uid"] for m in o["before"]["members"] if m in ua} | {n["_uid"] for n in back}
            for e in node["members"]:
                if e not in ub or ub[e]["_uid"] not in allowed:
                    old = [ua[m] for m in o["before"]["members"] if m in ua] + back
                    same = e in ub and any(same_look(n, ub[e]) for n in old)
                    self.note(LIMIT if same else "③ 되돌린 구간이 다른 기호를 가리킴", (seed, o["node_id"], e))
            for t in lost_of(node):
                if not is_tomb(t) or t in ub:
                    self.note("③ 되돌린 구간의 lost에 살아 있는 id", (seed, t))

    def results(self, seed, r_start, r_end, g_start, g_end, label, passed=None):
        idx = {idmap.ref_of(n, GID): n for n in g_end["nodes"]}
        sidx = {idmap.ref_of(n, GID): n for n in g_start["nodes"]}
        s_id = {n["entity_id"]: n for n in g_start["nodes"]}
        e_id = {n["entity_id"]: n for n in g_end["nodes"]}
        s_rel = {e["entity_id"]: e for e in g_start["edges"]}
        e_rel = {e["entity_id"]: e for e in g_end["edges"]}
        mid = passed or r_start

        def uids(edge, by):
            return sorted(by[x]["_uid"] for x in edge["nodes"])
        for c0, c1, cm in zip(r_start["cells"], r_end["cells"], mid["cells"]):
            e0, e1, em = c0["entries"][0], c1["entries"][0], cm["entries"][0]
            for r0, r1, rm in zip(e0["cause_refs"], e1["cause_refs"], em["cause_refs"]):
                o = sidx[r0["ref"]]
                if is_tomb(r1["ref"]):
                    self.stats["묘비가 된 ⑤ 참조(%s)" % label] += 1
                    continue
                n = idx.get(r1["ref"])
                if n is None:
                    self.note("③ ⑤ 참조가 묘비도 살아 있는 참조도 아님(%s)" % label, (seed, r0["ref"], r1["ref"]))
                elif n["_uid"] != o["_uid"]:
                    head = "③ 묘비였던 ⑤ 참조가 다른 기호로 풀림" if is_tomb(rm["ref"]) else "② ⑤ 참조가 다른 기호"
                    self.note(LIMIT if same_look(o, n) else "%s(%s)" % (head, label), (seed, r0["ref"], r1["ref"]))
            for x0, x1 in zip(e0["expectation_refs"], e1["expectation_refs"]):
                if is_tomb(x1):
                    continue
                hit = [n for r, n in idx.items() if expect.expectation_id("R-1", r) == x1]
                want = [n for r, n in sidx.items() if expect.expectation_id("R-1", r) == x0][0]
                if not hit:
                    self.note("③ 잠재 후보 ID가 묘비도 살아 있는 ID도 아님(%s)" % label, (seed, x0, x1))
                elif hit[0]["_uid"] != want["_uid"] and not same_look(hit[0], want):
                    self.note("② 잠재 후보 ID가 다른 기호(%s)" % label, (seed, x0, x1))
            for x0, x1 in zip(e0["ai_basis"]["kg_paths"][0], e1["ai_basis"]["kg_paths"][0]):
                if is_tomb(x1) or x0 == "cond-001":
                    continue
                if x0 in s_id:
                    n = e_id.get(x1)
                    if n is None:
                        self.note("③ 근거 경로 id가 묘비도 살아 있는 id도 아님(%s)" % label, (seed, x0, x1))
                    elif n["_uid"] != s_id[x0]["_uid"] and not same_look(n, s_id[x0]):
                        self.note("② 근거 경로가 다른 기호(%s)" % label, (seed, x0, x1))
                elif x0 in s_rel:
                    rel = e_rel.get(x1)
                    if rel is not None and uids(rel, e_id) != uids(s_rel[x0], s_id):
                        self.note("② 근거 경로 관계 id가 다른 관계(%s)" % label, (seed, x0, x1))


def run(seeds, judge):
    for seed in seeds:
        r = random.Random(seed)
        w1 = make_world(r)
        w2 = mutate(r, w1)
        w3 = mutate(r, w2)
        graphs = {v: build(w, v) for v, w in (("v-1", w1), ("v-2", w2), ("v-3", w3))}
        g1, g2, g3 = graphs["v-1"], graphs["v-2"], graphs["v-3"]
        stage = "만들기"
        try:
            ns1, form = make_set(r, g1)
            res1 = make_results(ns1, g1, r)
            judge.stats["집합 꼴 " + form] += 1
            judge.stats["도면 꼴 %s%s" % (w1["fmt"], "" if w1["basis"] else "(id_basis 없음)")] += 1
            stage = "판 이전 v1→v2"
            ns2, p2 = migrate.migrate_set(ns1, g2, at="t")
            judge.stats["판 이전"] += 1
            judge.step(seed, ns1, ns2, g1, g2, graphs)
            res2, _ = migrate.migrate_results(res1, ns2, at="t", **({"table": p2["table"]} if "table" in p2 else {}))
            judge.results(seed, res1, res2, g1, g2, "1단계")
            stage = "되돌리기 v2"
            judge.undo(seed, ns1, ns2, graphs)
            stage = "두 번 적용"
            again, _ = migrate.migrate_set(copy.deepcopy(ns1), g2, at="t")
            if json.dumps(again, sort_keys=True) != json.dumps(ns2, sort_keys=True):
                judge.note("④ 같은 판 이전을 두 번 하면 다름", seed)
            if migrate.migrate_set(ns2, g2, at="t")[0] is not ns2:
                judge.note("④ 같은 판에서 다시 바꿈", seed)
            twice, _ = migrate.migrate_results(res2, ns2, at="t")
            if json.dumps(twice, sort_keys=True) != json.dumps(res2, sort_keys=True):
                judge.note("④ ⑤ 결과를 두 번 옮기면 다름", seed)
            stage = "판 이전 v2→v3"
            ns3, p3 = migrate.migrate_set(ns2, g3, at="t")
            judge.stats["판 이전"] += 1
            judge.step(seed, ns2, ns3, g2, g3, graphs)
            res3, _ = migrate.migrate_results(res2, ns3, at="t", **({"table": p3["table"]} if "table" in p3 else {}))
            judge.results(seed, res1, res3, g1, g3, "2단계 이어서", passed=res2)
            res13, _ = migrate.migrate_results(res1, ns3, at="t")
            judge.results(seed, res1, res13, g1, g3, "2단계 늦게 따라옴", passed=res2)
            stage = "되돌리기 v3"
            judge.undo(seed, ns2, ns3, graphs)
            stage = "형식 검사"
            sn._check_shape(json.loads(json.dumps(ns3)), "x")
            for p in unregistered(ns3, res3):
                judge.note("⑥ 등록되지 않은 자리의 옛 id", (seed, p))
        except Exception as exc:  # noqa: BLE001  예외 자체가 불변식 ⑤ 위반이다
            tb = traceback.extract_tb(exc.__traceback__)[-1]
            judge.note("⑤ 예외 %s: %s (%s:%d)" % (stage, type(exc).__name__, os.path.basename(tb.filename), tb.lineno),
                       (seed, str(exc)[:120]))
    return judge


def failures(judge):
    return {k: v for k, v in judge.stats.items() if k[0] in "①②③④⑤⑥⑦"}


def report(judge):
    lines = []
    for k, v in sorted(judge.stats.items()):
        lines.append("%6d  %s" % (v, k))
        lines += ["          %s" % (ex,) for ex in judge.examples.get(k, [])]
    return "\n".join(lines)


class MigrateFuzzTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_invariants_hold_over_many_reextractions(self):
        judge = run(range(SEEDS), Judge())
        self.assertGreater(judge.stats["판 이전"], SEEDS, "판 이전을 실제로 돌림")
        self.assertGreater(judge.stats["되돌림"], 20, "판 이전 뒤 되돌리기를 실제로 돌림")
        for form in ("new", "a", "b"):
            self.assertGreater(judge.stats["집합 꼴 " + form], 20)
        self.assertEqual(failures(judge), {}, report(judge))


if __name__ == "__main__":
    print(report(run(range(int(sys.argv[1]) if len(sys.argv) > 1 else SEEDS), Judge())))
