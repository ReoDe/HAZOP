"""표제란 후보와 사람 확정(hazop.register.titleblock, registry.clear_metadata) 시험. 근거: INTENT §3.1, 완료 목록 2 A3.

가상 도면 SNP의 원본(drawio·PDF)을 임시 작업 루트·저장 루트에 등록하고 실제로 추출해 확인한다.
실행: python -m unittest tests.test_titleblock
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hazop import paths  # noqa: E402
from hazop.app import data  # noqa: E402
from hazop.extract import ai_review, confirmation, corrections  # noqa: E402
from hazop.register import registry, titleblock as tb  # noqa: E402
from hazop.study import nodes  # noqa: E402

BY = "검토자"
P = "P1"


def sample(drawing, ext):
    return glob.glob(os.path.join(paths.folder("references", "pid-samples"), drawing + "*", "*." + ext))[0]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-tb-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"),
                                           "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        env.start()
        self.addCleanup(env.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])

    def add(self, drawing="SNP-M-101", ext="drawio", extract=True):
        src = sample(drawing, ext)
        dst = os.path.join(self.tmp, "in", drawing + "-" + ext, os.path.basename(src))
        if ext == "drawio":  # 원본 옆 SVG도 같이(등록이 파생 자료로 찾음)
            shutil.copytree(os.path.dirname(src), os.path.dirname(dst))
        else:
            os.makedirs(os.path.dirname(dst))
            shutil.copy(src, dst)
        res = registry.register(dst, P, "P&ID", paths.store_root(), None, BY)
        self.assertEqual(res["outcome"], "registered", res.get("notes"))
        if extract:
            data.extract_and_graph(res["registration_file"])
        return res["record"]["material_id"]

    def row(self, mid):
        return tb.row(P, mid)

    def sheet(self, mid):
        return self.row(mid)["sheets"][0]

    def confirm(self, mid, fields, **kw):
        kw.setdefault("ver", self.row(mid)["ver"])
        return tb.confirm(P, mid, fields, kw.pop("by", BY), **kw)

    def candidates(self, mid):
        return {f["field"]: f["candidate"] for f in self.row(mid)["fields"]}

    def make_nodes(self, mid, n=6):
        """새 화면의 실제 길(api_nodes의 nodes.create → node_commands → 프로젝트 그래프 구간 파일)로 그 도면의 구성요소 n개를
        구간 하나로 만든다. 반환 (프로젝트 그래프, 저장된 구간 집합)."""
        from hazop.app import project_ctx
        from hazop.shell import api, api_nodes
        eng = api.Engine(settings_path=os.path.join(self.tmp, "engine-settings.json"), emit=lambda e: None)
        eng.settings.update(reviewer_name=BY, project_id=P)
        cmds = {}
        api_nodes.register(cmds)
        s = self.sheet(mid)
        with open(confirmation.extraction_path(s["name"]), encoding="utf-8") as fh:
            ids = [x["local_id"] for x in json.load(fh)["nodes"][:n]]
        pg = project_ctx.project_graph(P)
        cur = nodes.load(pg)
        c = cmds["nodes.create"]
        c.handler(eng, api.check_args(c.spec, {"project_id": P, "set_rev": (cur or {}).get("set_rev") or 0,
                                              "sheet": s["graph_id"], "ids": ids, "name": "S-%d" % n}))
        pg = project_ctx.project_graph(P)
        return pg, nodes.load(pg)


class CandidateTest(Base):
    def test_candidates_with_evidence_and_nothing_confirmed_until_a_person_does(self):
        mid = self.add()
        r = self.row(mid)
        self.assertEqual(r["state"], "unconfirmed")
        dwg = next(f for f in r["fields"] if f["field"] == "drawing_number")
        self.assertEqual((dwg["value"], dwg["candidate"]), (None, "SNP-M-101"))
        self.assertIn("표제란", dwg["evidence"]["text"])
        self.assertTrue(dwg["evidence"]["value_object_id"])
        st = confirmation.sheet_confirmation(self.sheet(mid)["name"])
        self.assertIn("registration_unknown", [u["reason"] for u in st["unconfirmed"] if u["id"] is None],
                      "표제란 확정 전에는 쪽 확정 조건(미확인 전체)이 막힘")
        self.assertEqual([x["material_id"] for x in tb.view(P)], [mid])


class ConfirmTest(Base):
    def test_confirm_as_is_survives_reopening_and_clears_the_sheet_unknown(self):
        mid = self.add()
        old = self.sheet(mid)
        out = self.confirm(mid, self.candidates(mid))
        self.assertTrue(out["ok"] and out["changed"], out)
        self.assertEqual((out["version"], out["re_extracted"]), (2, True))
        r = self.row(mid)
        self.assertEqual(r["state"], "confirmed")
        self.assertEqual({f["field"]: f["confirmed_by"] for f in r["fields"]}, {f: BY for f, _ in tb.FIELDS})
        self.assertTrue(all(f["confirmed_at"] for f in r["fields"]))
        new = self.sheet(mid)
        self.assertNotEqual(new["name"], old["name"])
        self.assertEqual(new["graph_id"], "graph-SNP-M-101")
        with open(confirmation.extraction_path(new["name"]), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["drawing"]["drawing_number"], "SNP-M-101")
        st = confirmation.sheet_confirmation(new["name"])
        self.assertNotIn("registration_unknown", [u["reason"] for u in st["unconfirmed"]])
        again = self.confirm(mid, self.candidates(mid))
        self.assertTrue(again["ok"] and not again["changed"], "같은 값이면 새 버전을 만들지 않음")

    def test_edited_value_is_confirmed_with_reason(self):
        mid = self.add()
        out = self.confirm(mid, {"title": "  원자로 냉각재   계통 주배관 "}, reason="표제란 오타")
        self.assertTrue(out["ok"], out)
        r = self.row(mid)
        title = next(f for f in r["fields"] if f["field"] == "title")
        self.assertEqual((title["value"], r["state"]), ("원자로 냉각재 계통 주배관", "partial"))
        rec, _ = registry.latest(P, mid)
        self.assertEqual(rec["history"][-1]["reason"], "표제란 오타")

    def test_human_edits_and_ai_candidates_follow_the_new_version(self):
        mid = self.add()
        old = self.sheet(mid)["name"]
        with open(confirmation.extraction_path(old), encoding="utf-8") as fh:
            ex = json.load(fh)
        op = corrections.make_op(ex, "confirm", ex["nodes"][0]["source_object_id"],
                                 {"items": [{"check": "missing_tag", "reason": "태그 없는 것이 맞음"}]}, BY, name=old)
        corrections.save(old, [op], BY)
        ai_review.save_doc(ai_review.new_doc(old, ex))
        out = self.confirm(mid, self.candidates(mid))
        self.assertEqual(out["carried"][0]["edits"], True)
        self.assertEqual(out["carried"][0]["ai_review"], True)
        new = self.sheet(mid)["name"]
        self.assertEqual(corrections.load(new)["ops"][0]["op_id"], op["op_id"])
        self.assertEqual(ai_review.load_doc(new)["extraction_name"], new)
        _orig, corrected = data.load_extraction(new)
        self.assertIn(op["op_id"], corrected["corrections"]["applied"], "새 추출에도 사람 수정이 적용됨")
        self.assertTrue(os.path.isfile(corrections.store_path(old)), "앞 파일은 지우지 않음")

    def test_unconfirm_returns_to_candidates_and_keeps_who_did_it(self):
        mid = self.add()
        self.confirm(mid, self.candidates(mid))
        out = tb.unconfirm(P, mid, ["title"], BY, ver=self.row(mid)["ver"], reason="제목이 틀림")
        self.assertTrue(out["ok"] and out["changed"], out)
        r = self.row(mid)
        title = next(f for f in r["fields"] if f["field"] == "title")
        self.assertEqual((title["value"], title["confirmed_by"], r["state"]), (None, None, "partial"))
        rec, _ = registry.latest(P, mid)
        self.assertEqual((rec["registration_version"], rec["history"][-1]["action"], rec["history"][-1]["by"]),
                         (3, "unconfirm_metadata", BY))
        self.assertFalse(tb.unconfirm(P, mid, ["title"], BY)["changed"], "되돌릴 것이 없으면 그대로")

    def test_refusals(self):
        mid = self.add(extract=False)
        ver = self.row(mid)["ver"]
        self.assertEqual(tb.confirm(P, mid, {"title": "x"}, "", ver)["refused"][0]["code"], "bad_actor")
        self.assertEqual(tb.confirm(P, mid, {"title": "  "}, BY, ver)["refused"][0]["code"], "bad_args")
        self.assertEqual(tb.confirm(P, mid, {"owner": "x"}, BY, ver)["refused"][0]["code"], "bad_args")
        self.assertEqual(tb.confirm(P, "material-000000000000", {"title": "x"}, BY)["refused"][0]["code"], "not_found")
        self.assertTrue(tb.confirm(P, mid, {"title": "x"}, BY, ver)["ok"])
        stale = tb.confirm(P, mid, {"title": "y"}, BY, ver)
        self.assertEqual(stale["refused"][0]["code"], "stale", "본 판이 낡았으면 거절")
        self.assertEqual(self.row(mid)["sheets"], [], "추출하지 않은 자료는 다시 추출하지 않음")


class NumberChangeTest(Base):
    def test_number_change_is_blocked_while_nodes_exist_and_allowed_without(self):
        mid = self.add()
        self.confirm(mid, self.candidates(mid))
        pg, ns = self.make_nodes(mid)
        members = sorted({m for x in ns["nodes"] for m in x["members"]})
        self.assertTrue(members and all(m.startswith("graph-SNP-M-101/") for m in members))
        before = self.row(mid)["version"]
        out = self.confirm(mid, {"drawing_number": "SNP-M-999"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["refused"][0]["code"], "rule")
        self.assertIn("구간", out["refused"][0]["reason"])
        self.assertEqual(self.row(mid)["version"], before, "막히면 등록정보를 바꾸지 않음")
        self.assertTrue(self.row(mid)["review_data"][0].startswith("구간 "), self.row(mid)["review_data"])
        from hazop.app import project_ctx
        ids = {x["entity_id"] for x in project_ctx.project_graph(P)["nodes"]}
        self.assertEqual([m for m in members if m not in ids], [], "구간 구성원이 하나도 끊기지 않음")
        undo = tb.unconfirm(P, mid, ["drawing_number"], BY, ver=self.row(mid)["ver"])
        self.assertTrue(undo["ok"], "번호 취소로 그래프 ID가 그대로면(쪽 이름 SNP-M-101) 막지 않음")
        os.remove(nodes.store_path(P, pg["graph_id"]))   # 사람이 구간을 정리한 뒤
        moved = self.confirm(mid, {"drawing_number": "SNP-M-999"})
        self.assertTrue(moved["ok"], moved)
        self.assertEqual(self.sheet(mid)["graph_id"], "graph-SNP-M-999")

    def test_same_number_same_format_is_refused_other_format_is_reported(self):
        a = self.add("SNP-M-101")
        self.confirm(a, {"drawing_number": "SNP-M-101"})
        b = self.add("SNP-M-102", extract=False)
        clash = self.confirm(b, {"drawing_number": "snp-m-101"})
        self.assertEqual(clash["refused"][0]["code"], "conflict")
        pdf = self.add("SNP-M-101", "pdf", extract=False)
        out = self.confirm(pdf, {"drawing_number": "SNP-M-101"})
        self.assertTrue(out["ok"], out)
        self.assertEqual([c["drawing_number"] for c in out["conflicts"]], ["SNP-M-101"], "다른 형식은 막지 않고 충돌을 알림")

    def test_multi_page_material_number_is_not_confirmed(self):
        rec = {"material_id": "m", "drawing_number": None, "documents": [{"page_ids": ["page-1", "page-2"]}]}
        with self.assertRaises(tb.Refused) as cm:
            tb._guard_number(P, rec, [], "X-1", None)
        self.assertEqual(cm.exception.row["code"], "rule")


class InterrogateFindingsTest(Base):
    """적대 검토(interrogate, 2026-11-14)가 실행으로 보인 결함들."""

    def boom(self, _path):
        raise RuntimeError("추출 실패 흉내")

    def test_failed_reextract_keeps_the_guard_and_the_old_graph_and_can_be_retried(self):
        mid = self.add()
        old = self.sheet(mid)
        with open(confirmation.extraction_path(old["name"]), encoding="utf-8") as fh:
            ex = json.load(fh)
        op = corrections.make_op(ex, "confirm", ex["nodes"][0]["source_object_id"],
                                 {"items": [{"check": "missing_tag", "reason": "x"}]}, BY, name=old["name"])
        corrections.save(old["name"], [op], BY)
        self.make_nodes(mid)
        out = self.confirm(mid, {"title": "주 배관"}, extract=self.boom)
        self.assertEqual(out["refused"][0]["code"], "io")
        self.assertIn("다시 읽지 못함", out["refused"][0]["reason"])
        r = self.row(mid)
        self.assertEqual((r["version"], r["needs_reextract"], r["sheets"][0]["name"]), (2, True, old["name"]))
        self.assertTrue(os.path.isfile(os.path.join(paths.output_root("graph"), old["name"], "graph.json")), "앞 그래프를 되돌림")
        self.assertTrue(r["review_data"] and r["review_data"][0].startswith("구간"), "지금 쪽은 앞 버전의 추출")
        blocked = self.confirm(mid, {"drawing_number": "SNP-M-999"})
        self.assertEqual(blocked["refused"][0]["code"], "rule", "다시 읽기 실패 뒤에도 구간이 있는 번호 바꾸기는 막음")
        again = self.confirm(mid, {"title": "주 배관"})
        self.assertTrue(again["ok"] and again["re_extracted"], again)
        self.assertEqual(again["version"], 2, "새 버전 없이 다시 읽기만")
        r = self.row(mid)
        self.assertFalse(r["needs_reextract"])
        self.assertEqual(corrections.load(r["sheets"][0]["name"])["ops"][0]["op_id"], op["op_id"], "사람 수정이 이어짐")

    def test_new_graph_carries_the_human_edits_and_the_old_graph_leaves_the_project(self):
        from hazop.graph import project
        mid = self.add()
        old = self.sheet(mid)["name"]
        with open(confirmation.extraction_path(old), encoding="utf-8") as fh:
            ex = json.load(fh)
        node = next(n for n in ex["nodes"] if n.get("tag"))
        op = corrections.make_op(ex, "set_tag", node["source_object_id"], {"tag": "ZZ-999"}, BY, name=old)
        corrections.save(old, [op], BY)
        out = self.confirm(mid, {"drawing_number": "SNP-M-555"})
        self.assertTrue(out["ok"], out)
        new = self.sheet(mid)["name"]
        with open(os.path.join(paths.output_root("graph"), new, "graph.json"), encoding="utf-8") as fh:
            self.assertIn("ZZ-999", fh.read(), "새 그래프에 사람 수정이 들어감(옮겨 쓴 뒤 추출)")
        self.assertEqual(sorted(project.pick_graphs(P)), ["graph-SNP-M-555"], "앞 그래프는 비켜 둠")
        self.assertTrue(os.path.isfile(os.path.join(paths.output_root("graph"), old, tb.SUPERSEDED)))

    def test_number_that_collides_through_a_page_name_case_or_file_key_is_refused(self):
        a = self.add("SNP-M-101")
        b = self.add("SNP-M-102", extract=False)
        for number in ("SNP-M-101", "snp-m-101", "SNP-M-101_"):
            with self.subTest(number):
                out = self.confirm(b, {"drawing_number": number})
                self.assertEqual(out["refused"][0]["code"], "conflict", out)
        self.confirm(a, {"drawing_number": "SNP-M-101"})
        pdf = self.add("SNP-M-101", "pdf", extract=False)
        self.assertEqual(self.confirm(pdf, {"drawing_number": "snp-m-101"})["refused"][0]["code"], "conflict",
                         "형식이 달라도 글자만 다르면 같은 파일을 쓰므로 막음")
        self.assertTrue(self.confirm(pdf, {"drawing_number": "SNP-M-101"})["ok"])

    def test_control_characters_and_empty_cancel_list_are_refused(self):
        mid = self.add(extract=False)
        for value in ("AB", "A‮B", "SNP-M-101​"):
            with self.subTest(repr(value)):
                self.assertEqual(self.confirm(mid, {"title": value})["refused"][0]["code"], "bad_args")
        self.confirm(mid, {"title": "주 배관"})
        self.assertEqual(tb.unconfirm(P, mid, [], BY)["refused"][0]["code"], "bad_args")
        self.assertEqual(next(f for f in self.row(mid)["fields"] if f["field"] == "title")["value"], "주 배관")

    def test_two_registry_writers_at_once_keep_both_versions(self):
        import threading
        a = self.add("SNP-M-101", extract=False)
        b = self.add("SNP-M-102", extract=False)
        self.confirm(a, {"title": "가"})
        gate = threading.Barrier(2, timeout=1.5)
        real = registry.Store.load_index

        def slow(store, project_id):
            try:
                gate.wait()
            except threading.BrokenBarrierError:
                pass
            return real(store, project_id)
        results = {}
        with mock.patch.object(registry.Store, "load_index", slow):
            ts = [threading.Thread(target=lambda: results.update(a=tb.unconfirm(P, a, ["title"], BY))),
                  threading.Thread(target=lambda: results.update(b=tb.confirm(P, b, {"title": "나"}, BY)))]
            for t in ts:
                t.start()
            for t in ts:
                t.join(30)
        self.assertTrue(results["a"]["ok"] and results["b"]["ok"], results)
        self.assertEqual((self.row(a)["version"], self.row(b)["version"]), (3, 2))
        self.assertTrue(self.confirm(a, {"title": "다"})["ok"], "색인과 버전 파일이 어긋나지 않음")


class ReviewFindingsTest(Base):
    """총괄 검토 반려(2026-11-14)에서 재현한 결함."""

    def boom(self, _path):
        raise RuntimeError("추출 실패 흉내")

    def test_r1_project_graph_nodes_block_the_number_change_and_stay_whole(self):
        mid = self.add()
        self.confirm(mid, self.candidates(mid))
        pg, ns = self.make_nodes(mid, n=10)
        dry = tb.confirm(P, mid, {"drawing_number": "SNP-M-555"}, BY, self.row(mid)["ver"], dry=True)
        self.assertFalse(dry["ok"], "dry 검사도 막음")
        self.assertIn("구간", dry["refused"][0]["reason"])
        out = self.confirm(mid, {"drawing_number": "SNP-M-555"})
        self.assertFalse(out["ok"])
        self.assertEqual(self.row(mid)["fields"][0]["value"], "SNP-M-101")
        from hazop.app import project_ctx
        pg2 = project_ctx.project_graph(P)
        ids = {x["entity_id"] for x in pg2["nodes"]}
        saved = nodes.load(pg2)
        self.assertEqual(sum(1 for x in saved["nodes"] for m in x["members"] if m not in ids), 0)
        self.assertTrue(self.confirm(mid, {"title": "개정과 제목은 확정 가능"})["ok"], "번호를 안 바꾸는 확정은 그대로 됨")

    def test_r1_every_record_that_points_at_the_graph_is_counted(self):
        from hazop.graph import project
        from hazop.ie import store as ie_store
        from hazop.kg import expect
        mid = self.add()
        self.confirm(mid, self.candidates(mid))
        gid = self.sheet(mid)["graph_id"]
        for label, path, body in (("초기사건", ie_store.store_path(P), {"evidence": [gid + "/entity-node-001"]}),
                                  ("잠재 후보 판단", expect.store_path(P), {"decisions": [{"ref": gid + "#n1"}]}),
                                  ("도면 연결 지정", project.manual_path(P), {"links": [{"a": gid + "#n2"}]})):
            with self.subTest(label):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(body, fh)
                out = self.confirm(mid, {"drawing_number": "SNP-M-555"}, dry=True)
                self.assertIn(label, out["refused"][0]["reason"])
                os.remove(path)
        with open(ie_store.store_path(P), "w", encoding="utf-8") as fh:
            json.dump({"evidence": [gid + "0/entity-node-001", gid + "-B#n1"]}, fh)
        self.assertEqual(tb._references(P, gid), {}, "graph-SNP-M-1010·graph-SNP-M-101-B 같은 다른 번호는 세지 않음")
        self.assertTrue(self.confirm(mid, {"drawing_number": "SNP-M-555"}, dry=True)["ok"])

    def test_r1_source_format_choice_blocks_the_number_change(self):
        from hazop.graph import sources
        a = self.add("SNP-M-101")
        self.confirm(a, {"drawing_number": "SNP-M-101"})
        pdf = self.add("SNP-M-101", "pdf")
        self.confirm(pdf, {"drawing_number": "SNP-M-101"})
        sources.choose(P, "SNP-M-101", "drawio", BY)
        out = self.confirm(a, {"drawing_number": "SNP-M-555"})
        self.assertEqual(out["refused"][0]["code"], "rule")
        self.assertIn("원본 형식 선택", out["refused"][0]["reason"])
        self.assertIn("SNP-M-101", sources.load_choices(P), "선택은 그대로 남음")

    def test_r2_edits_made_after_a_failed_reextract_reach_the_new_graph(self):
        mid = self.add()
        old = self.sheet(mid)["name"]
        with open(confirmation.extraction_path(old), encoding="utf-8") as fh:
            ex = json.load(fh)
        tagged = [x for x in ex["nodes"] if x.get("tag")]
        op1 = corrections.make_op(ex, "set_tag", tagged[0]["source_object_id"], {"tag": "ZZ-111"}, BY, name=old)
        corrections.save(old, [op1], BY)
        self.assertEqual(self.confirm(mid, {"title": "주 배관"}, extract=self.boom)["refused"][0]["code"], "io")
        cur = self.sheet(mid)["name"]
        self.assertEqual(cur, old)
        new_name = tb._out_name(registry.latest(P, mid)[0], 0)
        self.assertFalse(os.path.exists(corrections.store_path(new_name)), "실패한 시도가 옮긴 사본은 지움")
        doc = corrections.load(cur)
        op2 = corrections.make_op(ex, "set_tag", tagged[1]["source_object_id"], {"tag": "ZZ-222"}, BY,
                                  existing_ops=doc["ops"], name=cur)
        corrections.save(cur, doc["ops"] + [op2], BY)
        again = self.confirm(mid, {"title": "주 배관"})
        self.assertTrue(again["ok"], again)
        new = self.sheet(mid)["name"]
        self.assertEqual([o["op_id"] for o in corrections.load(new)["ops"]], [op1["op_id"], op2["op_id"]])
        with open(os.path.join(paths.output_root("graph"), new, "graph.json"), encoding="utf-8") as fh:
            g = fh.read()
        self.assertTrue("ZZ-111" in g and "ZZ-222" in g, "실패 뒤 수정도 새 그래프에 들어감")

    def test_r2_a_leftover_copy_is_merged_by_operation_not_skipped(self):
        mid = self.add()
        old = self.sheet(mid)["name"]
        with open(confirmation.extraction_path(old), encoding="utf-8") as fh:
            ex = json.load(fh)
        tagged = [x for x in ex["nodes"] if x.get("tag")]
        op1 = corrections.make_op(ex, "set_tag", tagged[0]["source_object_id"], {"tag": "ZZ-111"}, BY, name=old)
        op2 = corrections.make_op(ex, "set_tag", tagged[1]["source_object_id"], {"tag": "ZZ-222"}, BY,
                                  existing_ops=[op1], name=old)
        corrections.save(old, [op1, op2], BY)
        corrections.save(old, [op1], BY)        # 사람이 op2를 지움
        record = registry.latest(P, mid)[0]
        stale = dict(corrections.load(old), ops=[op1, op2], log=[])   # 끊긴 시도가 남긴 옛 사본(지우기 전 내용)
        future = dict(record, registration_version=record["registration_version"] + 1)
        store_path = corrections.store_path(tb._out_name(future, 0))
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        with open(store_path, "w", encoding="utf-8") as fh:
            json.dump(stale, fh)
        out = self.confirm(mid, {"title": "주 배관"})
        self.assertTrue(out["ok"], out)
        self.assertEqual([o["op_id"] for o in corrections.load(self.sheet(mid)["name"])["ops"]], [op1["op_id"]],
                         "지금 쪽에서 지운 연산은 옛 사본에서 되살리지 않음")


class ExecuteTest(Base):
    def test_chat_entry_needs_the_version_it_saw(self):
        mid = self.add(extract=False)
        for cmd, args in (("confirm", {"material_id": mid, "fields": {"title": "x"}}), ("unconfirm", {"material_id": mid})):
            with self.subTest(cmd):
                out = tb.execute(P, cmd, args, BY, None)
                self.assertEqual(out["refused"][0]["code"], "bad_args")
                self.assertIn("ver", out["refused"][0]["reason"])
        self.assertIsNone(self.row(mid)["fields"][2]["value"], "판 없이는 아무것도 쓰지 않음")

    def test_chat_entry(self):
        mid = self.add(extract=False)
        self.assertEqual(tb.execute(P, "view")["rows"][0]["material_id"], mid)
        self.assertEqual(tb.execute(P, "view", {"material_id": "nope"})["refused"][0]["code"], "not_found")
        self.assertEqual(tb.execute(P, "erase")["refused"][0]["code"], "unknown_command")
        out = tb.execute(P, "confirm", {"material_id": mid, "fields": {"design_revision": "0"}}, BY, self.row(mid)["ver"])
        self.assertTrue(out["ok"] and out["changed"], out)
        out = tb.execute(P, "unconfirm", {"material_id": mid, "fields": ["design_revision"]}, BY, self.row(mid)["ver"])
        self.assertTrue(out["ok"] and out["changed"], out)


if __name__ == "__main__":
    unittest.main()
