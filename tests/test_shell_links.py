"""도면 연결(오각형) 짝 지정·끊기(완료 목록 3 B1, hazop/shell/api_links.py). 실행: python -m unittest tests.test_shell_links

임시 작업 루트에 SNP 표본 6장의 graph.json을 써 두고 새 화면의 실제 길(엔진 명령 links.* → project.save_manual → project_ctx.project_graph)로 돈다.
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import drawio  # noqa: E402
from hazop.graph import build, project  # noqa: E402
from hazop.shell import api, api_links  # noqa: E402

SAMPLES = sorted(glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio")))
PID = "SNP-SAMPLE"
S101, S102 = "graph-SNP-M-101", "graph-SNP-M-102"


@unittest.skipUnless(SAMPLES, "SNP 샘플 없음")
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-links-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")}),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])
        from hazop.app import project_ctx
        project_ctx._PROJECT_GRAPHS.clear()
        project_ctx._NAMES.clear()
        project.clear_sheet_cache()
        self.addCleanup(project.clear_sheet_cache)
        root = paths.output_root("graph")
        for path in SAMPLES:
            g = build.build_graph(drawio.extract(path, repo_root=REPO_ROOT))
            os.makedirs(os.path.join(root, g["graph_id"]), exist_ok=True)
            with open(os.path.join(root, g["graph_id"], "graph.json"), "w", encoding="utf-8", newline="\n") as fh:
                json.dump(g, fh, ensure_ascii=False, indent=2)
        if "links.pair" not in api.COMMANDS:
            from hazop.shell import api_corrections
            api_corrections.register(api.COMMANDS)
        self.events = []
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=self.events.append)
        self.engine.settings.update(reviewer_name="검토자A", project_id=PID)

    # ------------------------------------------------------------ 도움
    def pg(self):
        from hazop.app import project_ctx
        return project_ctx.project_graph(PID)

    def linked_pair(self):
        """자동으로 이은 101 ↔ 102 짝 하나: ((graph_id, local_id), (graph_id, local_id))."""
        pg = self.pg()
        by_id = {n["entity_id"]: n for n in pg["nodes"]}
        for l in pg["sheet_links"]:
            if l["status"] == "linked" and {l["from"]["graph_id"], l["to"]["graph_id"]} == {S101, S102}:
                a = by_id[project.nid(l["from"]["graph_id"], l["from"]["entity_id"])]
                b = by_id[project.nid(l["to"]["graph_id"], l["to"]["entity_id"])]
                if a["sheet"] != S101:
                    a, b = b, a
                return (a["sheet"], a["local_id"]), (b["sheet"], b["local_id"])
        self.fail("101 ↔ 102 자동 짝이 없음")

    def view(self, at, q=None):
        v = api_links.view(self.engine, at[0], at[1], q=q)
        self.assertTrue(v["ok"], v)
        return v

    def web(self, name, at, **args):
        """웹이 하듯: 카드가 본 판(ver)·연결점 지문(base)을 싣고 프로젝트에 묶어 보낸다."""
        v = self.view(at)
        a = dict({"graph_id": at[0], "local_id": at[1], "ver": v["ver"], "base": v["point"]["base"]}, **args)
        return self.engine.dispatch("links." + name, a, project=PID, via_web=True)

    def confirmed(self, name, at, **args):
        r = self.web(name, at, **args)
        if not r["ok"] and r["error"]["code"] == "needs_confirm":
            r = self.web(name, at, confirm=r["error"]["message"], **args)
        self.assertTrue(r["ok"], r)
        return r


class PairUnlinkClearTest(Base):
    def test_unlink_asks_then_both_ends_are_unlinked_and_the_record_says_who_and_why(self):
        a, b = self.linked_pair()
        r = self.web("unlink", a, reason="도면 개정으로 끊김")
        self.assertEqual(r["error"]["code"], "needs_confirm")
        self.assertIn("짝이 풀립니다", r["error"]["message"])
        self.confirmed("unlink", a, reason="도면 개정으로 끊김")
        pa, pb = self.view(a)["point"], self.view(b)["point"]
        self.assertEqual((pa["status"], pa["origin"], pa["reason"]), ("unlinked", "manual", "manual_unlink"))
        self.assertEqual((pa["op"]["by"], pa["op"]["reason"]), ("검토자A", "도면 개정으로 끊김"))
        self.assertEqual(pb["status"], "unlinked")
        doc = project.load_manual(PID)
        self.assertEqual(doc["log"][-1]["note"]["op"], "unlink")
        told = {e.get("topic") for e in self.events if e.get("t") == "changed"}
        self.assertTrue({"links", "nodes"} <= told, told)            # 카드와 도면 위 오각형·구간 표기를 다시 읽게

    def test_pair_from_the_candidate_list_links_both_ways_and_clear_returns_to_automatic(self):
        a, b = self.linked_pair()
        self.confirmed("unlink", a)
        v = self.view(a)
        cand = next(c for c in v["candidates"] if (c["graph_id"], c["local_id"]) == b)
        self.assertFalse(cand["linked"])
        self.assertEqual(v["candidates"][0]["graph_id"], S102, "이 도면을 가리키는 짝 없는 연결점이 먼저 온다")
        self.confirmed("pair", a, peer_graph_id=b[0], peer_local_id=b[1], reason="배관 번호 확인")
        pa, pb = self.view(a)["point"], self.view(b)["point"]
        self.assertEqual((pa["status"], pa["origin"]), ("linked", "manual"))
        self.assertEqual((pa["peer"]["graph_id"], pa["peer"]["local_id"]), b)
        self.assertEqual((pb["peer"]["graph_id"], pb["peer"]["local_id"]), a)
        ops = project.load_manual(PID)["ops"]
        self.assertEqual([o["op"] for o in ops], ["link"], "같은 연결점의 앞선 끊기 지정은 빠진다")
        again = self.web("pair", a, peer_graph_id=b[0], peer_local_id=b[1])
        self.assertEqual(again["error"]["code"], "bad_args")
        self.confirmed("clear", a, op_id=ops[0]["op_id"])
        pa = self.view(a)["point"]
        self.assertEqual((pa["status"], pa["origin"]), ("linked", "auto"))
        self.assertEqual(project.load_manual(PID)["ops"], [])

    def test_pairing_with_a_point_that_has_another_partner_names_the_pair_that_breaks(self):
        a, b = self.linked_pair()
        pg = self.pg()
        other = next(n for n in pg["nodes"] if n.get("kind") == "continuation" and n.get("sheet") not in (S101, a[0])
                     and (n.get("sheet_link") or {}).get("status") == "linked" and n.get("local_id"))
        r = self.web("pair", a, peer_graph_id=other["sheet"], peer_local_id=other["local_id"])
        self.assertEqual(r["error"]["code"], "needs_confirm")
        self.assertEqual(r["error"]["message"].count("짝이 풀립니다"), 2, r["error"]["message"])

    def test_search_filters_candidates(self):
        a, b = self.linked_pair()
        v = self.view(a, q="SNP-M-102")
        self.assertTrue(any(c["drawing_number"] == "SNP-M-102" for c in v["candidates"]))
        self.assertTrue(all("snp-m-102" in " ".join(str(c[k] or "") for k in ("drawing_number", "line_no", "label", "to_drawing")).casefold()
                            for c in v["candidates"]))
        self.assertEqual(self.view(a, q="없는-글-ZZZ")["candidates"], [])

    def test_only_continuations_can_be_paired(self):
        pg = self.pg()
        n = next(n for n in pg["nodes"] if n.get("sheet") == S101 and n.get("kind") not in ("continuation", None) and n.get("local_id"))
        v = api_links.view(self.engine, S101, n["local_id"])
        self.assertEqual(v["code"], "bad_args")


class SaveRulesTest(Base):
    def test_a_stale_screen_version_or_point_fingerprint_writes_nothing(self):
        a, b = self.linked_pair()
        v = self.view(a)
        self.confirmed("unlink", b)                          # 다른 쪽에서 바뀜
        r = self.engine.dispatch("links.unlink", {"graph_id": a[0], "local_id": a[1], "ver": v["ver"], "base": v["point"]["base"]},
                                 project=PID, via_web=True)
        self.assertEqual(r["error"]["code"], "stale")
        v2 = self.view(a)
        r = self.engine.dispatch("links.unlink", {"graph_id": a[0], "local_id": a[1], "ver": v2["ver"], "base": v["point"]["base"]},
                                 project=PID, via_web=True)
        self.assertEqual(r["error"]["code"], "stale", "카드에서 본 연결점 상태가 지금과 다르면 거절")
        self.assertEqual(len(project.load_manual(PID)["ops"]), 1)

    def test_wrong_project_and_missing_reviewer_are_refused(self):
        a, _b = self.linked_pair()
        v = self.view(a)
        r = self.engine.dispatch("links.unlink", {"graph_id": a[0], "local_id": a[1], "ver": v["ver"]}, project="OTHER", via_web=True)
        self.assertFalse(r["ok"])
        self.engine.settings["reviewer_name"] = ""
        r = self.engine.dispatch("links.unlink", {"graph_id": a[0], "local_id": a[1], "ver": v["ver"]}, project=PID, via_web=True)
        self.assertEqual(r["error"]["code"], "bad_args")
        self.assertIsNone(project.load_manual(PID))

    def test_a_file_changed_by_another_process_after_reading_is_not_overwritten(self):
        a, b = self.linked_pair()
        v = self.view(a)
        real = project.save_manual

        def sneak(pid, ops, by, at, expect=project._KEEP, note=None):
            real(pid, [], "다른 프로세스", at)                  # 읽은 뒤·쓰기 전에 다른 프로세스가 씀
            return real(pid, ops, by, at, expect=expect, note=note)
        with mock.patch.object(project, "save_manual", sneak):
            r = api_links.unlink(self.engine, a[0], a[1], v["ver"], base=v["point"]["base"], confirm=api_links._impact_text(*self._impact(a)))
        self.assertEqual(r["code"], "stale", r)
        self.assertEqual(project.load_manual(PID)["ops"], [])

    def _impact(self, a):
        pg = self.pg()
        n, by_id = api_links._entity(pg, a[0], a[1])
        mine = api_links._peer_of(pg, n, by_id)
        return pg, by_id, [n, mine], [(n, mine)]

    def test_two_threads_with_the_same_version_do_not_both_write(self):
        a, b = self.linked_pair()
        va, vb = self.view(a), self.view(b)
        text_a = api_links._impact_text(*self._impact(a))
        text_b = api_links._impact_text(*self._impact(b))
        out = {}
        ts = [threading.Thread(target=lambda: out.__setitem__("a", api_links.unlink(self.engine, a[0], a[1], va["ver"], base=va["point"]["base"], confirm=text_a))),
              threading.Thread(target=lambda: out.__setitem__("b", api_links.unlink(self.engine, b[0], b[1], vb["ver"], base=vb["point"]["base"], confirm=text_b)))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sorted(r["ok"] for r in out.values()), [False, True], out)
        self.assertEqual(len(project.load_manual(PID)["ops"]), 1)

    def test_confirmed_segment_holding_the_point_asks_and_is_named_for_recheck(self):
        from hazop.study import nodes as sn
        a, _b = self.linked_pair()
        pg = self.pg()
        eid = next(n["entity_id"] for n in pg["nodes"] if (n.get("sheet"), n.get("local_id")) == a)
        ns = sn.new_set(pg)
        ns["nodes"] = [dict(sn._v2_fields("user"), node_id="S1", name="확정 구간", basis="시험", members=[eid], state="confirmed")]
        sn.write(sn.store_path(PID, pg["graph_id"]), ns)
        r = self.web("unlink", a)
        self.assertIn("S1", r["error"]["message"])
        done = self.confirmed("unlink", a)
        self.assertTrue(any(t.startswith("④ 검토구간") for t in done["data"]["recheck"]), done)

    def test_sheet_confirmation_does_not_read_the_link_record(self):
        from hazop.extract import confirmation
        files = confirmation.file_paths("SNP-M-101")
        self.assertNotIn(project.manual_path(PID), files.values())


class StaleAndCacheTest(Base):
    def test_an_assignment_whose_point_is_gone_is_shown_as_stale_and_can_be_cleared(self):
        a, _b = self.linked_pair()
        project.save_manual(PID, [{"op_id": "sl-old", "op": "unlink", "ends": [{"drawing_number": "SNP-M-101", "source_object_id": "gone-1"}],
                                   "by": "검토자B", "at": "2026-11-01T00:00:00Z", "reason": "옛 지정"}], "검토자B", "2026-11-01T00:00:00Z")
        v = self.view(a)
        self.assertEqual([s["op_id"] for s in v["stale"]], ["sl-old"])
        self.assertIn("없음", v["stale"][0]["reason"])
        self.confirmed("clear", a, op_id="sl-old")
        self.assertEqual(self.view(a)["stale"], [])

    def test_the_sheet_cache_does_not_hide_a_new_assignment(self):
        a, b = self.linked_pair()
        warm = self.pg()                                     # 쪽별 캐시·프로젝트 그래프 캐시를 채운다
        self.assertEqual(self.view(a)["point"]["origin"], "auto")
        self.confirmed("unlink", a)
        after = self.pg()
        self.assertNotEqual(after["graph_version"], warm["graph_version"])
        from hazop.app import project_ctx
        project.clear_sheet_cache()
        project_ctx._PROJECT_GRAPHS.clear()
        fresh = project_ctx.project_graph(PID)
        canon = lambda g: json.dumps(g, ensure_ascii=False, sort_keys=True)  # noqa: E731
        self.assertEqual(canon(after), canon(fresh))
        self.assertEqual(self.view(a)["point"]["origin"], "manual")

    def test_web_read_goes_through_the_read_api(self):
        a, _b = self.linked_pair()
        ra = api.ReadApi(self.engine)
        r = ra.read(["links", a[0], a[1]], {"q": ["SNP-M-102"]})
        data = json.loads(r.body.decode("utf-8"))
        self.assertEqual(data["point"]["local_id"], a[1])


class FingerprintPathTest(Base):
    """B1 검토: 저장 길 전체에서 지문이 남고, 번호가 밀린 다시 추출을 따라가며, 옛 지정은 '확인 필요'로 보인다."""

    def rename_soid(self, gid, local_id, new_soid):
        """다시 추출로 그 연결점의 원본 번호만 바뀐 것처럼 graph.json을 고친다(라벨·자리는 그대로)."""
        p = os.path.join(paths.output_root("graph"), gid, "graph.json")
        with open(p, encoding="utf-8") as fh:
            g = json.load(fh)
        n = next(n for n in g["nodes"] if n.get("local_id") == local_id)
        n["source_object_id"] = new_soid
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(g, fh, ensure_ascii=False, indent=2)

    def test_a_saved_pair_keeps_fingerprints_and_follows_a_renumbered_point(self):
        a, b = self.linked_pair()
        self.confirmed("unlink", a)
        self.confirmed("pair", a, peer_graph_id=b[0], peer_local_id=b[1])
        op = project.load_manual(PID)["ops"][0]
        self.assertTrue(all(isinstance(e.get("fp"), dict) and e["fp"]["label"] for e in op["ends"]), op)
        self.rename_soid(a[0], a[1], "renumbered-1")
        v = self.view(a)
        self.assertEqual((v["point"]["status"], v["point"]["origin"]), ("linked", "manual"), "같은 지문의 연결점 하나로 옮겨 붙는다")
        self.assertEqual([(m["from"], m["to"]) for m in v["relocated"]], [(op["ends"][0]["source_object_id"], "renumbered-1")])
        self.confirmed("unlink", b, reason="다음 저장")              # 다음 저장이 옮긴 것을 기록에 남긴다
        doc = project.load_manual(PID)
        self.assertEqual(doc["log"][-1]["note"]["relocated"][0]["to"], "renumbered-1")

    def test_a_point_that_changed_is_not_reattached_and_shows_as_stale(self):
        a, b = self.linked_pair()
        self.confirmed("unlink", a)
        self.confirmed("pair", a, peer_graph_id=b[0], peer_local_id=b[1])
        p = os.path.join(paths.output_root("graph"), a[0], "graph.json")
        with open(p, encoding="utf-8") as fh:
            g = json.load(fh)
        n = next(n for n in g["nodes"] if n.get("local_id") == a[1])
        n["label_text"] = n["label_text"].replace("TO", "TO X")        # 같은 번호에 다른 연결점이 들어선 것처럼
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(g, fh, ensure_ascii=False, indent=2)
        v = self.view(a)
        self.assertNotEqual(v["point"]["origin"], "manual")
        self.assertTrue(v["stale"] and "바뀜" in v["stale"][0]["reason"], v["stale"])

    def test_an_old_record_without_fingerprints_is_used_but_marked_for_checking(self):
        a, b = self.linked_pair()
        nums = {S101: "SNP-M-101", S102: "SNP-M-102"}
        pg = self.pg()
        sid = {(n["sheet"], n["local_id"]): n.get("source_object_id") for n in pg["nodes"] if n.get("local_id")}
        project.save_manual(PID, [{"op_id": "sl-old", "op": "link", "by": "B", "at": "t", "reason": "",
                                   "ends": [{"drawing_number": nums[a[0]], "source_object_id": sid[a]},
                                            {"drawing_number": nums[b[0]], "source_object_id": sid[b]}]}], "B", "t")
        p = self.view(a)["point"]
        self.assertEqual((p["origin"], p["check"]), ("manual", "no_fingerprint"))

    def test_candidates_carry_mismatch_warnings(self):
        a, b = self.linked_pair()
        v = self.view(a)
        good = next(c for c in v["candidates"] if (c["graph_id"], c["local_id"]) == b)
        self.assertEqual(good["warn"], [])
        self.assertTrue(any(c["warn"] for c in v["candidates"]))

    def test_dry_run_returns_the_same_confirm_text_and_writes_nothing(self):
        """채팅 확인 상자용: dry=True는 검사와 확인 글만 돌려주고 저장하지 않는다. 그 글이 실제 needs_confirm 글과 같다."""
        a, b = self.linked_pair()
        v = self.view(a)
        d = api_links.unlink(self.engine, a[0], a[1], v["ver"], base=v["point"]["base"], dry=True)
        self.assertTrue(d["ok"] and d["dry"] and d["confirm"], d)
        self.assertIsNone(project.load_manual(PID))
        real = api_links.unlink(self.engine, a[0], a[1], v["ver"], base=v["point"]["base"])
        self.assertEqual((real["code"], real["message"]), ("needs_confirm", d["confirm"]))
        ok = api_links.unlink(self.engine, a[0], a[1], v["ver"], base=v["point"]["base"], confirm=d["confirm"])
        self.assertTrue(ok["ok"], ok)
        self.assertEqual(api_links.unlink(self.engine, a[0], a[1], v["ver"], base=v["point"]["base"], dry=True)["code"], "stale")

    def test_the_chat_functions_refuse_without_version_and_fingerprint(self):
        a, _b = self.linked_pair()
        v = self.view(a)
        for kw in ({"ver": None, "base": v["point"]["base"]}, {"ver": v["ver"], "base": None}):
            r = api_links.unlink(self.engine, a[0], a[1], kw["ver"], base=kw["base"])
            self.assertEqual(r["code"], "bad_args", r)
        self.assertIsNone(project.load_manual(PID))


def _cont(eid, soid, direction, to, line, at=None):
    n = {"entity_id": eid, "kind": "continuation", "source_object_id": soid, "local_id": eid,
         "attributes": {"direction": direction, "to_drawing": to, "line_no": line}, "label_text": "%s %s\n%s" % (direction.upper(), to, line)}
    if at:
        n["position"] = at
    return n


def _graph(gid, dn, nodes):
    return {"graph_id": gid, "graph_version": "v-" + gid, "source": {"drawing_number": dn}, "nodes": nodes, "edges": [], "validation": {"status": "passed"}}


class RenumberTest(unittest.TestCase):
    """B1 검토 차단(재현 D:\\HAZOP-trials\\2026-11-14-review-b1-b2\\scripts\\repro_b1_renumber.py를 옮김): PDF 추출 ID는 순번이라
    다시 추출해 번호가 밀리면, 번호만 보는 지정이 다른 연결점에 조용히 붙었다. 끝마다 연결점 지문을 남기고 다르면 붙이지 않는다."""

    def setUp(self):
        self.g101 = _graph("g101", "X-101", [_cont("n1", "pdf-p1-sym-0001", "to", "X-102", "L-1", [10, 10]),
                                             _cont("n2", "pdf-p1-sym-0002", "to", "X-102", "L-2", [10, 50])])
        self.g102 = _graph("g102", "X-102", [_cont("m1", "pdf-p1-sym-0001", "from", "X-101", "L-1X", [90, 10]),
                                             _cont("m2", "pdf-p1-sym-0002", "from", "X-101", "L-2", [90, 50])])
        ends = [project.end_ref(self.g101, self.g101["nodes"][0]), project.end_ref(self.g102, self.g102["nodes"][0])]
        self.op = {"op_id": "sl-test", "op": "link", "by": "검토자", "at": "2026-11-14T00:00:00Z", "reason": "배관 번호 오독", "ends": ends}

    def manual(self, graphs, ops):
        links, skipped = project.match(graphs, ops)
        return [l for l in links if l["origin"] == "manual"], skipped, links

    def pairs(self, man):
        return [(l["from"]["entity_id"], l["to"]["entity_id"]) for l in man]

    def test_first_extraction_pairs_as_assigned(self):
        man, skipped, _ = self.manual([self.g101, self.g102], [self.op])
        self.assertEqual(self.pairs(man), [("n1", "m1")])
        self.assertEqual(skipped, [])

    def test_shifted_numbers_follow_the_same_point_and_say_so(self):
        """앞에 연결점 하나가 더 잡혀 번호가 하나씩 밀림: 지문이 같은 연결점(옛 L-1, 같은 자리)이 하나뿐이면 그쪽으로 옮겨 붙인다."""
        g = _graph("g101", "X-101", [_cont("k0", "pdf-p1-sym-0001", "to", "X-102", "L-9", [10, 90]),
                                     _cont("k1", "pdf-p1-sym-0002", "to", "X-102", "L-1", [10, 10]),
                                     _cont("k2", "pdf-p1-sym-0003", "to", "X-102", "L-2", [10, 50])])
        moved = []
        links, skipped = project.match([g, self.g102], [self.op], moved=moved)
        man = [l for l in links if l["origin"] == "manual"]
        self.assertEqual(self.pairs(man), [("k1", "m1")], "L-9 연결점에 조용히 붙으면 안 된다")
        self.assertEqual(skipped, [])
        self.assertEqual([(m["op_id"], m["from"], m["to"]) for m in moved], [("sl-test", "pdf-p1-sym-0001", "pdf-p1-sym-0002")])
        pg = project.build("X", [g, self.g102], [self.op])
        self.assertEqual(pg["manual_relocated"][0]["op_id"], "sl-test")

    def test_a_changed_point_with_no_unique_match_is_stale_not_reattached(self):
        g = _graph("g101", "X-101", [_cont("k0", "pdf-p1-sym-0001", "to", "X-102", "L-9", [10, 90]),
                                     _cont("k2", "pdf-p1-sym-0003", "to", "X-102", "L-2", [10, 50])])
        man, skipped, links = self.manual([g, self.g102], [self.op])
        self.assertEqual(man, [])
        self.assertEqual([s["op_id"] for s in skipped], ["sl-test"])
        self.assertIn("바뀜", skipped[0]["reason"])
        k0 = next(l for l in links if any((l.get(s) or {}).get("entity_id") == "k0" for s in ("from", "to")))
        self.assertEqual(k0["origin"], "auto")

    def test_an_old_assignment_without_fingerprints_still_applies_but_needs_checking(self):
        old = dict(self.op, ends=[{"drawing_number": "X-101", "source_object_id": "pdf-p1-sym-0001"},
                                  {"drawing_number": "X-102", "source_object_id": "pdf-p1-sym-0001"}])
        man, skipped, _ = self.manual([self.g101, self.g102], [old])
        self.assertEqual(self.pairs(man), [("n1", "m1")])
        self.assertEqual(man[0].get("check"), "no_fingerprint")

    def test_auto_links_do_not_change_shape(self):
        _man, _s, links = self.manual([self.g101, self.g102], [])
        self.assertTrue(all("check" not in l for l in links))
        self.assertNotIn("manual_relocated", project.build("X", [self.g101, self.g102], []))


if __name__ == "__main__":
    unittest.main()
