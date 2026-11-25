"""자동 확정 엔진(C1) 시험: 확정 수준, 자동 수락, 되돌리기, 도면 번호 자동 확정, 옛 앱 호환.

설계: docs/units/2026-11-13-drawing-knowledge/evidence/auto-confirm-design.md 2~7장과 10.1(재현 시험 1~16). 시험 이름의 rNN이 그 번호다.
임시 작업 루트만 쓰고 AI를 부르지 않는다. 자동 수락은 상수로 꺼 둔 채라(ai_review.AUTO_ACCEPT_ENABLED) 켠 시험은 patch로 켠다.
실행: python -m unittest tests.test_auto_confirm
"""

import copy
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hazop import paths, store_io  # noqa: E402
from hazop.extract import ai_images, ai_review as ar, confirmation as cf, corrections as co, drawio  # noqa: E402
from hazop.graph import build, sources  # noqa: E402
from hazop.kg import claims, screen  # noqa: E402
from hazop.register import registry, titleblock as tb  # noqa: E402

AUTO = "hazop:auto"
BY = "검토자"
P = "P1"
NAME = "t__material-000000000001-r1-p0"
NEXT = "t__material-000000000001-r2-p0"
OLD = "46b973ac"          # 옛 앱 구실을 하는 고정 커밋
_CACHE = {}


def sample(drawing, ext):
    return glob.glob(os.path.join(paths.folder("references", "pid-samples"), drawing + "*", "*." + ext))[0]


def pdf_extraction():
    if "pdf" not in _CACHE:
        from hazop.extract.adapters import pdf_vector
        _CACHE["pdf"] = pdf_vector.extract(sample("SNP-M-101", "pdf"), page=0, repo_root=REPO)
    return copy.deepcopy(_CACHE["pdf"])


def drawio_extraction():
    return drawio.extract(sample("SNP-M-101", "drawio"), repo_root=REPO)


def sid(n):
    return "pdf-p0-sym-%04d" % n


def by_sid(ex):
    return {n["source_object_id"]: n for n in ex["nodes"]}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def unread(ex, *sids):
    """그 기호들을 '종류를 못 읽은 기호'로 바꾼다."""
    for s in sids:
        n = by_sid(ex)[s]
        n.update(kind=None, category="unclassified", classification="unclassified", tag=None, attributes={})
        ex["validation"]["unknowns"] = [u for u in ex["validation"]["unknowns"] if u.get("target") != n["local_id"]] + [
            {"check": "missing_kind", "target": n["local_id"], "source_object_id": s, "field": "kind", "reason": "종류 미확인"}]
    return ex


def swap(ex, a, b):
    """다시 추출로 번호가 밀린 추출: 두 기호의 순번 id(와 그 id를 적은 자리)를 맞바꾼다. 자리·모양·local_id는 그대로다."""
    tr = {a: b, b: a}

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return tr.get(x, x) if isinstance(x, str) else x
    return walk(copy.deepcopy(ex))


def cand(ex, s, value, conf=0.9, field="kind", **extra):
    n = by_sid(ex)[s]
    more = {"near_symbol": None, "match": "legend"} if field == "kind" else {}
    if field == "kind" and value in ar.WIDE_KINDS:
        more["wide"] = "done"
    more.update(dict({"input": "image", "legend_source": "symbols"}, **extra))
    task = more.pop("task", field)
    return ar.make_candidate("%s-%s" % (task[0], s), task, {"target": s, "local_id": n["local_id"], "bbox": ar._box(n)},
                             field, [value], conf, "근거", more)


def run_stats(**kw):
    return dict({"items": 1, "calls": 1, "errors": 0, "left": 0, "halted": False, "stopped": False, "refused": None,
                 "error_kinds": [], "legend_source": "symbols"}, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-autoconf-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"),
                                           "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        env.start()
        self.addCleanup(env.stop)
        os.makedirs(os.environ["HAZOP_WORK_ROOT"])

    def on(self):
        p = mock.patch.object(ar, "AUTO_ACCEPT_ENABLED", True, create=True)
        p.start()
        self.addCleanup(p.stop)

    def put(self, ex, name=NAME):
        d = os.path.join(paths.output_root("extract"), name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "extraction.json"), "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)
        return ex

    def asked(self, ex, *cands, name=NAME, auto=True, **stats):
        """AI에 물은 실행 하나를 저장한다(앱이 쓰는 merge_and_save)."""
        return ar.merge_and_save(name, ex, {"candidates": list(cands), "stats": run_stats(**stats)}, via="fixed", auto=auto)

    def status(self, name=NAME):
        return cf.sheet_confirmation(name)

    def ops(self, name=NAME):
        return (co.load(name) or {}).get("ops") or []

    def node(self, ex, s, name=NAME):
        return by_sid(co.resolve(name, ex)["corrected"])[s]

    def edit(self, ex, op, target, value, name=NAME, by=BY):
        ops = self.ops(name)
        co.save(name, ops + [co.make_op(ex, op, target, value, by, existing_ops=ops, name=name)], by)

    def follow(self, name=NAME, to=NEXT):
        """옛 앱의 번호 확정: 수정 기록과 AI 후보만 새 이름으로 옮긴다."""
        for path_of in (co.store_path, ar.store_path):
            if os.path.isfile(path_of(name)):
                store_io.write_json(path_of(to), dict(read(path_of(name)), extraction_name=to))

    def simple(self, **kw):
        """못 읽은 기호 하나(8번)에 쓸 수 있는 종류 후보 하나를 받아 둔 쪽."""
        ex = self.put(unread(pdf_extraction(), sid(8)))
        cf.record_auto(NAME, "waiting", "started")
        self.asked(ex, cand(ex, sid(8), "check_valve"), **kw)
        return ex


# ---------------------------------------------------------------- 상수를 끈 상태

class OffTest(Base):
    def test_switches_ship_off(self):
        self.assertIs(ar.AUTO_ACCEPT_ENABLED, False)
        self.assertIs(tb.AUTO_NUMBER_ENABLED, False)

    def test_nothing_is_accepted_while_off(self):
        ex = self.simple()
        before = self.node(ex, sid(8))
        self.assertEqual(ar.auto_accept(NAME, ex), {"accepted": [], "blocked": {"off": 1}})
        self.assertEqual((self.ops(), self.node(ex, sid(8))), ([], before))
        self.assertEqual(ar.load_doc(NAME)["candidates"][0]["status"], "proposed")

    def test_a_sheet_without_auto_record_keeps_its_old_answer(self):
        self.put(pdf_extraction())
        st = self.status()
        self.assertEqual((st["state"], st["level"], st["auto"], st["auto_accepted"]), ("open", "extracted", None, 0))
        self.assertFalse(os.path.exists(cf.store_path(NAME)), "읽기는 파일을 쓰지 않음")

    def test_human_accept_is_unchanged(self):
        ex = self.put(unread(pdf_extraction(), sid(8)))
        doc = ar.merge_and_save(NAME, ex, {"candidates": [cand(ex, sid(8), "check_valve")], "stats": run_stats()})
        self.assertEqual(ar.accept(doc, [doc["candidates"][0]["cand_id"]], ex, NAME, BY), [])
        cor = co.resolve(NAME, ex)["corrected"]
        mark = by_sid(cor)[sid(8)]["human_edit"]
        self.assertNotIn("auto", mark)
        n = next(n for n in build.build_graph(cor)["nodes"] if n["source_object_id"] == sid(8))
        self.assertEqual((n["origin"], "auto" in n), ("human_edit", False))
        self.assertEqual(n["human_edit"], {"op_ids": mark["op_ids"], "ops": ["set_kind"], "by": BY, "at": mark["at"]})
        self.assertIn(("check_valve", ar._box(by_sid(ex)[sid(8)])), ai_images.confirmed_samples(cor))

    def test_number_stays_unconfirmed_while_off(self):
        src = os.path.join(self.tmp, "a.drawio")
        shutil.copy(sample("SNP-M-101", "drawio"), src)
        res = registry.register(src, P, store_root=paths.store_root(), actor=BY)
        out = tb.auto_confirm_number(P, res["record"]["material_id"])
        self.assertEqual((out["confirmed"], out["why"]), (False, "off"))
        self.assertTrue(os.path.samefile(out["registration_file"], res["registration_file"]))
        self.assertIsNone(registry.latest(P, res["record"]["material_id"])[0]["drawing_number"])


# ---------------------------------------------------------------- 확정 수준과 전이(설계 2장)

class LevelTest(Base):
    def test_r01_auto_stays_auto_after_a_chat_edit(self):
        self.on()
        ex = self.simple()
        self.assertEqual(self.status()["level"], "extracted", "waiting은 추출만 됨")
        out = ar.auto_finish(NAME, ex)
        self.assertEqual((out["result"], len(out["accepted"])), ("confirmed", 1))
        st = self.status()
        self.assertEqual((st["level"], st["state"], st["auto_accepted"]), ("auto", "open", 1))
        self.edit(ex, "set_tag", sid(9), {"tag": "V-777"})
        st = self.status()
        self.assertEqual((st["level"], st["auto_accepted"]), ("auto", 1))
        self.edit(ex, "set_kind", sid(8), {"kind": "check_valve", "category": "valve"})
        self.assertEqual(self.status()["auto_accepted"], 0, "사람이 같은 값으로 덮으면 자동 값이 아님")

    def test_r02_read_key_ignores_registration_and_carried_record_stays_auto(self):
        self.on()
        ex = self.simple()
        ar.auto_finish(NAME, ex)
        new = copy.deepcopy(ex)
        new["extraction_run_id"] = "다른 실행"
        new["source"].update(registration_version=2)
        new["drawing"]["drawing_number"] = "SNP-M-999"
        self.assertEqual(cf.read_key(ex), cf.read_key(new))
        self.put(new, NEXT)
        self.follow()
        cf.carry_auto(NAME, NEXT)
        st = self.status(NEXT)
        self.assertEqual((st["level"], st["auto_accepted"]), ("auto", 1))
        self.assertFalse(cf.auto_resumable(st), "같은 읽기라 다시 부르지 않음")
        self.assertTrue(ar.auto_asked(ar.load_doc(NEXT), cf.read_key(new)), "끝난 실행이 있음")

    def test_r02_r03_real_number_confirm_keeps_read_key_and_the_revert(self):
        from hazop.app import data
        src = os.path.join(self.tmp, "in.pdf")
        shutil.copy(sample("SNP-M-101", "pdf"), src)
        res = registry.register(src, P, store_root=paths.store_root(), actor=BY)
        data.extract_and_graph(res["registration_file"])
        mid = res["record"]["material_id"]
        old = tb.row(P, mid)["sheets"][0]["name"]
        ex = read(cf.extraction_path(old))
        cf.record_auto(old, "waiting", "started")
        self.asked(ex, name=old, calls=3)
        self.assertEqual(ar.auto_finish(old, ex)["result"], "confirmed")
        self.assertEqual(self.status(old)["level"], "auto")
        out = tb.confirm(P, mid, {"drawing_number": "SNP-M-101"}, BY)
        self.assertTrue(out["ok"], out)
        new = tb.row(P, mid)["sheets"][0]["name"]
        again = read(cf.extraction_path(new))
        self.assertNotEqual((old, ex["extraction_run_id"]), (new, again["extraction_run_id"]), "시험 전제")
        self.assertEqual((cf.read_key(ex), self.status(new)["level"]), (cf.read_key(again), "auto"))
        self.assertTrue(ar.auto_asked(ar.load_doc(new), cf.read_key(again)), "새 호출 0")
        self.assertEqual(ar.calls_used(ar.load_doc(new)), 3, "누적 호출도 함께 옮겨짐")
        ar.auto_revert(new, BY)
        self.assertTrue(tb.confirm(P, mid, {"title": "제목"}, BY)["ok"])
        last = tb.row(P, mid)["sheets"][0]["name"]
        self.assertNotEqual(last, new)
        self.assertEqual((self.status(last)["auto"]["result"], self.status(last)["level"]), ("reverted", "extracted"))

    def test_r03_reverted_stays_reverted_after_rename(self):
        self.on()
        ex = self.simple()
        ar.auto_finish(NAME, ex)
        ar.auto_revert(NAME, BY)
        st = self.status()
        self.assertEqual((st["level"], st["auto"]["result"], st["auto"]["by"]), ("extracted", "reverted", BY))
        self.put(ex, NEXT)
        self.follow()
        cf.carry_auto(NAME, NEXT)
        self.assertEqual(ar.auto_finish(NEXT, ex)["result"], "reverted")
        self.assertEqual(ar.auto_accept(NEXT, ex)["accepted"], [])
        self.assertEqual(self.ops(NEXT), [])
        with self.assertRaises(cf.AutoReverted):
            cf.record_auto(NEXT, "waiting", "started")
        self.assertFalse(cf.auto_resumable(self.status(NEXT)))
        cf.record_auto(NEXT, "waiting", "started", by=BY, restart=True)
        self.assertEqual(ar.auto_finish(NEXT, ex)["result"], "confirmed")
        self.assertEqual(self.ops(NEXT), [], "사람이 되돌린 후보는 다시 시켜도 저절로 넣지 않음")

    def test_r03_revert_wins_over_a_later_record_when_carrying(self):
        ex = self.put(pdf_extraction())
        self.put(ex, NEXT)
        cf.record_auto(NAME, "reverted", by=BY)
        cf.record_auto(NEXT, "confirmed")
        cf.carry_auto(NAME, NEXT)
        self.assertEqual(self.status(NEXT)["auto"]["result"], "reverted")
        with mock.patch.object(cf, "now_utc", lambda: "2999-01-01T00:00:00+00:00"):
            cf.record_auto(NAME, "confirmed", by=BY, restart=True)
        cf.carry_auto(NAME, NEXT)
        self.assertEqual(self.status(NEXT)["auto"]["result"], "reverted", "옮길 곳의 되돌림도 지지 않음")

    def test_carry_leaves_human_cells_behind(self):
        ex = self.put(pdf_extraction())
        self.put(ex, NEXT)
        rec = cf._empty_record(NAME)
        rec["compared"] = {"by": BY, "at": "t", "fingerprint": "f", "files": {}}
        store_io.write_json(cf.store_path(NAME), rec)
        cf.record_auto(NAME, "confirmed")
        self.assertEqual(read(cf.store_path(NAME))["compared"], rec["compared"], "자동 기록은 사람 칸을 건드리지 않음")
        cf.carry_auto(NAME, NEXT)
        got = read(cf.store_path(NEXT))
        self.assertEqual((got["auto"]["result"], got["compared"], got["extraction_name"]), ("confirmed", None, NEXT))

    def test_r04_changed_rules_drop_to_extracted_and_keep_accepts(self):
        self.on()
        ex = self.simple()
        ar.auto_finish(NAME, ex)
        ex["run"]["rules_version"] = "pdf-vector-rules-9"
        self.put(ex)
        st = self.status()
        self.assertEqual((st["level"], len(self.ops()), st["auto_accepted"]), ("extracted", 1, 1))
        self.assertTrue(cf.auto_resumable(st))
        self.assertFalse(ar.auto_asked(ar.load_doc(NAME), st["read_key"]))

    def test_read_key_follows_content(self):
        ex = pdf_extraction()
        for change in (lambda d: d["source"].update(sha256="0" * 64), lambda d: d["run"]["settings"].update(page_index=1),
                       lambda d: d["run"].update(script_version="9"), lambda d: d["nodes"][0].update(kind="pump"),
                       lambda d: d["nodes"][0].update(tag="X-1"), lambda d: d["nodes"][0]["geometry"].update(x=1.0),
                       lambda d: d["nodes"].pop()):
            other = copy.deepcopy(ex)
            change(other)
            self.assertNotEqual(cf.read_key(ex), cf.read_key(other))

    def test_r07_empty_or_blocked_sheet_is_never_auto(self):
        ex = pdf_extraction()
        empty = dict(copy.deepcopy(ex), nodes=[], relations=[], unresolved_connectors=[], source_locations=[])
        empty["validation"] = {"status": "passed", "blockers": [], "unknowns": []}
        self.put(empty)
        cf.record_auto(NAME, "confirmed")
        self.assertEqual(self.status()["level"], "extracted")
        blocked = copy.deepcopy(ex)
        blocked["validation"]["status"] = "blocked"
        self.put(blocked, NEXT)
        cf.record_auto(NEXT, "confirmed")
        self.assertEqual(self.status(NEXT)["level"], "extracted")

    def test_r07_rows_without_target_count_one_by_one(self):
        ex = pdf_extraction()
        ex["validation"]["unknowns"] = []
        base = cf.check(ex)["unconfirmed_targets"]
        ex["validation"]["unknowns"] = [{"check": "not_registered", "target": None, "reason": "r%d" % i} for i in range(3)]
        got = cf.check(ex)
        self.assertEqual(got["unconfirmed_targets"], base + 3)
        self.assertEqual(got["counts"]["not_registered"], 1, "있던 세기(§10.4)는 그대로")

    def test_r08_candidate_and_unread_symbol_count_once(self):
        ex = unread(pdf_extraction(), sid(8))
        without = cf.check(ex, None)["unconfirmed_targets"]
        doc = {"candidates": [cand(ex, sid(8), "check_valve"), cand(ex, sid(8), "V-1", field="tag")]}
        self.assertEqual(cf.check(ex, doc)["unconfirmed_targets"], without)

    def test_human_confirm_beats_auto_and_falls_back_to_it(self):
        self.put(pdf_extraction())
        cf.record_auto(NAME, "confirmed")
        real = cf.check

        def ready(*a, **k):
            return dict(real(*a, **k), unconfirmed=[], unplaced=[], leftovers={"total": 0})
        with mock.patch.object(cf, "check", ready):
            for c in ("compare", "confirm"):
                self.assertTrue(cf.execute(NAME, c, {}, by=BY)["ok"])
            self.assertEqual(self.status()["level"], "human")
            self.assertTrue(cf.execute(NAME, "unconfirm", {}, by=BY)["ok"])
            self.assertEqual(self.status()["level"], "auto")

    def test_auto_never_touches_a_human_confirmed_sheet(self):
        self.on()
        ex = self.simple()
        real = cf._status
        with mock.patch.object(cf, "_status", lambda *a, **k: dict(real(*a, **k), state="confirmed", level="human")):
            self.assertEqual(ar.auto_finish(NAME, ex)["result"], "human")
            self.assertEqual(ar.auto_accept(NAME, ex), {"accepted": [], "blocked": {"human": 1}})
        self.assertEqual(self.ops(), [])

    def test_same_record_is_not_written_twice(self):
        self.put(pdf_extraction())
        cf.record_auto(NAME, "waiting", "limit")
        before = store_io.fingerprint(cf.store_path(NAME))
        cf.record_auto(NAME, "waiting", "limit")
        self.assertEqual(store_io.fingerprint(cf.store_path(NAME)), before)

    def test_record_refuses_unknown_values_and_broken_files(self):
        self.put(pdf_extraction())
        for bad in (("done", None), ("waiting", None), ("waiting", "because")):
            with self.assertRaises(ValueError):
                cf.record_auto(NAME, *bad)
        with self.assertRaises(ValueError):
            cf.record_auto(NAME, "reverted", by=AUTO)
        cf.record_auto(NAME, "confirmed")
        with open(cf.store_path(NAME), "w", encoding="utf-8") as fh:
            fh.write("{깨짐")
        with self.assertRaises(ValueError):
            cf.record_auto(NAME, "confirmed")
        with open(cf.store_path(NAME), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{깨짐")

    def test_malformed_auto_cell_is_ignored_without_touching_human_cells(self):
        self.put(pdf_extraction())
        for bad in ("x", {"result": 1}, {"result": "confirmed", "read_key": 3}, []):
            store_io.write_json(cf.store_path(NAME), dict(cf._empty_record(NAME), auto=bad))
            st = self.status()
            self.assertEqual((st["level"], st["auto"], st["record_error"]), ("extracted", None, None))

    def test_unconfirm_of_a_broken_record_keeps_the_auto_cell(self):
        self.put(pdf_extraction())
        cf.record_auto(NAME, "reverted", by=BY)
        store_io.write_json(cf.store_path(NAME), dict(read(cf.store_path(NAME)), compared={"x": 1}))
        self.assertTrue(cf.execute(NAME, "unconfirm", {}, by=BY)["ok"])
        self.assertEqual(self.status()["auto"]["result"], "reverted")


class OutcomeTest(Base):
    """2.3 전이 표: 실행 기록만 보고 정한 결과(auto_finish)와 남는 기록."""

    def finish(self, ex=None, **stats):
        ex = self.put(ex or unread(pdf_extraction(), sid(8)))
        if stats:
            self.asked(ex, **stats)
        out = ar.auto_finish(NAME, ex)
        return out["result"], out["why"], self.status()["level"]

    def test_all_answered(self):
        self.assertEqual(self.finish(left=0), ("confirmed", None, "auto"))
        self.assertEqual(self.status()["auto"]["ai"], {"calls": 1, "left": 0, "status": "done"})

    def test_material_cap_reached(self):
        self.assertEqual(self.finish(calls=20, left=4), ("confirmed", None, "auto"))
        self.assertEqual(self.status()["auto"]["ai"], {"calls": 20, "left": 4, "status": "capped"})

    def test_cap_counts_over_runs(self):
        ex = self.put(unread(pdf_extraction(), sid(8)))
        for n in (12, 8):
            self.asked(ex, calls=n, left=4, stopped=True)
        self.assertEqual(ar.auto_calls_left(ar.load_doc(NAME)), 0)
        self.assertEqual(ar.auto_finish(NAME, ex)["result"], "confirmed")

    def test_partial_failure_waits_and_third_failure_is_final(self):
        ex = self.put(unread(pdf_extraction(), sid(8)))
        seen = []
        for _ in range(3):
            self.asked(ex, cand(ex, sid(8), "check_valve"), calls=2, left=1, errors=1, error_kinds=["timeout"])
            for _again in range(2):          # 같은 일을 두 번 마무리해도 시도는 한 번으로 셈
                out = ar.auto_finish(NAME, ex)
            st = self.status()
            seen.append((out["result"], out["why"], st["auto"]["attempts"], cf.auto_resumable(st)))
        self.assertEqual(seen, [("waiting", "error", 1, True), ("waiting", "error", 2, True), ("waiting", "error_final", 3, False)])
        self.assertEqual((self.ops(), self.status()["level"]), ([], "extracted"), "후보는 남기고 수락은 하지 않음")
        self.assertEqual(len(ar.load_doc(NAME)["candidates"]), 1)

    def test_waits_that_are_not_attempts(self):
        cases = (({"halted": True, "error_kinds": ["limit_reached"], "errors": 1}, "limit"),
                 ({"halted": True, "error_kinds": ["overage"], "errors": 1}, "limit"),
                 ({"halted": True, "error_kinds": ["not_ready"], "errors": 1}, "no_connection"),
                 ({"refused": "구독 아님", "calls": 0}, "no_connection"),
                 ({"stopped": True}, "stopped"),
                 ({"halted": True, "error_kinds": ["cancelled"], "errors": 1}, "stopped"),
                 ({}, "run_cap"))
        for extra, why in cases:
            with self.subTest(why):
                if os.path.isfile(ar.store_path(NAME)):
                    os.remove(ar.store_path(NAME))
                self.assertEqual(self.finish(left=2, **extra), ("waiting", why, "extracted"))
                self.assertEqual(self.status()["auto"]["attempts"], 0)
                self.assertTrue(cf.auto_resumable(self.status()))

    def test_not_asked_yet(self):
        self.assertEqual(self.finish(), ("waiting", "started", "extracted"))

    def test_manual_runs_and_project_legend_do_not_count_as_asked(self):
        ex = self.put(unread(pdf_extraction(), sid(8)))
        self.asked(ex, auto=False)
        self.assertEqual(ar.auto_finish(NAME, ex)["why"], "started")
        self.asked(ex, legend_source="project+symbols")
        self.assertEqual(ar.auto_finish(NAME, ex)["why"], "no_image")

    def test_formats_without_images(self):
        box = drawio_extraction()
        for ex, want in ((box, ("confirmed", None, "auto")), (dict(box, source=dict(box["source"], format="dexpi")), ("confirmed", None, "auto")),
                         (dict(box, source=dict(box["source"], format="raster")), ("waiting", "scan", "extracted"))):
            with self.subTest(ex["source"]["format"]):
                if os.path.isfile(cf.store_path(NAME)):
                    os.remove(cf.store_path(NAME))
                self.assertEqual(self.finish(ex), want)
                self.assertFalse(cf.auto_resumable(self.status()))

    def test_taken_waits_and_is_not_resumed(self):
        self.put(pdf_extraction())
        cf.record_auto(NAME, "waiting", "taken")
        self.assertEqual(self.status()["level"], "extracted")
        self.assertFalse(cf.auto_resumable(self.status()))

    def test_no_record_means_no_retroactive_run(self):
        self.put(pdf_extraction())
        self.assertFalse(cf.auto_resumable(self.status()))

    def test_confirmed_sheet_does_not_accept_later(self):
        ex = self.simple()
        self.assertEqual(ar.auto_finish(NAME, ex)["result"], "confirmed")   # 꺼진 채 자동 확정
        self.on()
        self.assertEqual(ar.auto_finish(NAME, ex)["accepted"], [])
        self.assertEqual(self.ops(), [])


# ---------------------------------------------------------------- 자동 수락 규칙(설계 4.3·4.4)

class RuleTest(Base):
    def setUp(self):
        Base.setUp(self)
        self.ex = unread(pdf_extraction(), sid(8), sid(9), sid(16))

    def block(self, c, protected=(), pending=None, ex=None):
        return ar.auto_block(c, ex or self.ex, set(protected), [c] if pending is None else pending)

    def test_r08_passes(self):
        self.assertIsNone(self.block(cand(self.ex, sid(8), "check_valve", 0.70)))
        self.assertIsNone(self.block(cand(self.ex, sid(8), "manual_valve", 0.70)))
        ex = pdf_extraction()
        by_sid(ex)[sid(14)]["tag"] = None
        self.assertIsNone(self.block(cand(ex, sid(14), "V999", field="tag"), ex=ex), "태그 후보도 규칙 5를 지남")

    def test_r08_each_rule_blocks(self):
        def c(value="check_valve", conf=0.9, **k):
            made = cand(self.ex, sid(8), value, conf, **{x: v for x, v in k.items() if x in ("field", "task")})
            return dict(made, **{x: v for x, v in k.items() if x not in ("field", "task")})
        rows = (("status", c(status="rejected")), ("status", c(status="accepted")),
                ("human", c(decided_at="t", decided_by=BY)), ("human", c(decided_at="t", decided_by=ar.RECONCILED_BY)),
                ("task", c(task="recheck")), ("task", c(field="fail_position", value="FO")), ("task", c(value="없는종류")),
                ("input", c(input="text")), ("input", c(input=None)), ("input", c(legend_source="project+symbols")),
                ("input", c(legend_source=None)), ("confidence", c(conf=0.699)),
                ("moved", c(bbox=[0, 0, 5, 5])), ("moved", c(bbox=None)), ("moved", c(target="pdf-p0-sym-9999")),
                ("letter_circle", c(value="transmitter")), ("wide", c(value="manual_valve", wide=None)))
        for want, x in rows:
            with self.subTest(want=want, value=x["values"][0]):
                self.assertEqual(self.block(x), want)
        self.assertEqual(self.block(c(), protected=[sid(8)]), "protected")
        self.assertEqual(self.block(cand(self.ex, sid(14), "pump")), "conflict")
        for text in ("RC-V030", "rc v 030"):
            self.assertEqual(self.block(c(field="tag", value=text)), "tag_taken", "같은 태그가 이미 있음")
        a, b = cand(self.ex, sid(8), "V-5", field="tag"), cand(self.ex, sid(9), "V5", field="tag")
        self.assertEqual((self.block(a, pending=[a, b]), self.block(b, pending=[a, b])), ("tag_taken", "tag_taken"))

    def test_first_matching_rule_wins(self):
        x = dict(cand(self.ex, sid(8), "transmitter", 0.1, input="text"), decided_at="t", decided_by=BY)
        self.assertEqual(self.block(x, protected=[sid(8)]), "human")

    def test_accept_counts_reasons(self):
        self.on()
        ex = self.put(self.ex)
        self.asked(ex, cand(ex, sid(8), "check_valve"), cand(ex, sid(9), "pump", 0.4), cand(ex, sid(16), "check_valve", legend_source="none"))
        out = ar.auto_accept(NAME, ex)
        self.assertEqual((len(out["accepted"]), out["blocked"]), (1, {"confidence": 1, "input": 1}))
        op = self.ops()[0]
        self.assertEqual((op["by"], op["accepted_by"], op["origin"], op["target"]), (AUTO, AUTO, "ai", sid(8)))
        c = next(c for c in ar.load_doc(NAME)["candidates"] if c["target"] == sid(8))
        self.assertEqual((c["status"], c["decided_by"], c["op_id"]), ("accepted", AUTO, op["op_id"]))

    def test_r05_human_edit_protects_its_symbol_when_numbers_shift(self):
        self.on()
        ex = self.put(unread(pdf_extraction(), sid(8), sid(17)))
        self.edit(ex, "set_tag", sid(8), {"tag": "X-8"})
        moved = self.put(swap(ex, sid(8), sid(17)))       # 같은 자리의 기호가 17번이 됨
        self.assertEqual(self.node(moved, sid(17))["tag"], "X-8", "시험 전제: 사람 고침은 자리를 따라감")
        self.asked(moved, cand(moved, sid(17), "check_valve"))
        self.assertEqual(ar.auto_accept(NAME, moved), {"accepted": [], "blocked": {"protected": 1}})
        self.assertEqual(len(self.ops()), 1)

    def test_r05_unapplied_human_edit_protects_its_place(self):
        self.on()
        ex = self.put(unread(pdf_extraction(), sid(8)))
        self.edit(ex, "set_tag", sid(14), {"tag": "X-14"})
        changed = copy.deepcopy(ex)
        by_sid(changed)[sid(14)]["kind"] = "pump"          # 종류가 달라져 사람 고침을 적용하지 못함
        moved = self.put(swap(changed, sid(14), sid(8)))
        self.assertEqual([x["op_id"] for x in co.resolve(NAME, moved)["corrected"]["corrections"]["not_applicable"]],
                         [self.ops()[0]["op_id"]], "시험 전제")
        self.asked(moved, cand(moved, sid(8), "check_valve"))
        self.assertEqual(ar.auto_accept(NAME, moved)["blocked"], {"protected": 1})

    def test_r05_rejected_place_is_not_accepted_under_a_new_number(self):
        self.on()
        ex = self.put(unread(pdf_extraction(), sid(8), sid(17)))
        doc = self.asked(ex, cand(ex, sid(8), "check_valve"))
        ar.reject(doc, [doc["candidates"][0]["cand_id"]], BY)
        moved = self.put(swap(ex, sid(8), sid(17)))
        self.asked(moved, cand(moved, sid(17), "check_valve"))
        self.assertEqual(ar.auto_accept(NAME, moved), {"accepted": [], "blocked": {"status": 1, "protected": 1}})

    def test_r05_place_whose_auto_op_a_person_removed_is_protected(self):
        self.on()
        ex = self.put(unread(pdf_extraction(), sid(8), sid(17)))
        self.asked(ex, cand(ex, sid(8), "check_valve"))
        ar.auto_accept(NAME, ex)
        self.assertEqual(len(self.ops()), 1, "시험 전제")
        co.save(NAME, [], BY)                              # 옛 앱이 수정 기록에서 바로 뺌
        os.remove(ar.store_path(NAME))                     # 후보 파일도 새로 시작
        moved = self.put(swap(ex, sid(8), sid(17)))
        self.asked(moved, cand(moved, sid(17), "check_valve"))
        self.assertEqual(ar.auto_accept(NAME, moved)["accepted"], [])

    def test_undo_in_the_edit_record_is_a_human_decision(self):
        self.on()
        ex = self.simple()
        ar.auto_finish(NAME, ex)
        self.assertEqual(len(self.ops()), 1, "시험 전제")
        co.save(NAME, [], BY)
        self.assertEqual(ar.auto_accept(NAME, ex)["accepted"], [])
        self.assertEqual(self.ops(), [])

    def test_r06_shifted_candidate_does_not_hit_another_symbol(self):
        self.on()
        ex = self.put(unread(pdf_extraction(), sid(8), sid(17)))
        self.asked(ex, cand(ex, sid(8), "check_valve"))
        moved = self.put(swap(ex, sid(8), sid(17)))
        self.assertEqual(ar.auto_accept(NAME, moved), {"accepted": [], "blocked": {"moved": 1}})

    def test_auto_op_follows_its_symbol(self):
        self.on()
        ex = self.put(unread(pdf_extraction(), sid(8)))
        self.asked(ex, cand(ex, sid(8), "check_valve"))
        ar.auto_accept(NAME, ex)
        moved = self.put(swap(ex, sid(8), sid(17)))
        self.assertEqual(self.node(moved, sid(17))["kind"], "check_valve")

    def test_edit_between_choosing_and_writing_is_not_overwritten(self):
        self.on()
        ex = pdf_extraction()
        by_sid(ex)[sid(14)]["tag"] = None
        self.put(ex)
        self.asked(ex, cand(ex, sid(14), "V-777", field="tag"))
        real, hit = ar.accept, []

        def racing(*a, **k):
            if not hit:
                hit.append(1)
                self.edit(ex, "set_tag", sid(9), {"tag": "V777"})       # 고른 뒤 쓰기 전에 사람이 같은 태그를 다른 자리에 씀
            return real(*a, **k)
        with mock.patch.object(ar, "accept", racing):
            out = ar.auto_accept(NAME, ex)
        self.assertEqual((out, [o["target"] for o in self.ops()]), ({"accepted": [], "blocked": {"tag_taken": 1}}, [sid(9)]))

    def test_rules_live_in_one_place_and_ship_as_designed(self):
        r = ar.AUTO_RULES
        self.assertEqual((r.min_confidence, r.inputs, r.legends), ({("kind", "kind"): 0.70, ("tag", "tag"): 0.70}, ("image",), ("symbols",)))

    def test_rules_can_open_values_but_never_the_safety_checks(self):
        wide = ar.AutoRules(version="test", min_confidence={(t, f): 0.0 for t in ("kind", "tag", "recheck", "connection", "split")
                                                            for f in ("kind", "tag", "normal_position", "fail_position", "connection", "split")},
                            inputs=("image", "text", None), legends=("symbols", "project+symbols", "none", None))
        ex = self.ex
        ex2 = pdf_extraction()
        by_sid(ex2)[sid(20)]["attributes"]["fail_position"] = "FO"
        block = lambda c, protected=(), e=ex: ar.auto_block(c, e, set(protected), [c], wide)  # noqa: E731
        low = cand(ex, sid(8), "check_valve", 0.1, input="text", legend_source=None)
        self.assertIsNone(block(low), "여는 값은 열린다")
        self.assertIsNone(block(cand(ex2, sid(23), "FC", 0.1, field="fail_position", task="tag"), e=ex2))
        rows = (("status", dict(low, status="rejected"), (), ex), ("human", dict(low, decided_at="t", decided_by=BY), (), ex),
                ("protected", low, [sid(8)], ex), ("moved", dict(low, bbox=[0, 0, 1, 1]), (), ex),
                ("moved", dict(low, target="pdf-p0-sym-9999"), (), ex), ("conflict", cand(ex, sid(14), "pump", 1.0, task="recheck"), (), ex),
                ("conflict", cand(ex2, sid(20), "FC", 1.0, field="fail_position", task="tag"), (), ex2),
                ("tag_taken", cand(ex, sid(8), "RC-V030", 1.0, field="tag"), (), ex),
                ("letter_circle", cand(ex, sid(8), "transmitter", 1.0), (), ex),
                ("wide", cand(ex, sid(8), "manual_valve", 1.0, wide=None), (), ex),
                ("moved", dict(low, target="pdf-p0-conn-0004", field="connection", task="connection", values=[sid(9)]), (), ex),
                ("task", dict(low, field="to_system", task="connection"), (), ex))
        for want, c, protected, e in rows:
            with self.subTest(want):
                self.assertEqual(block(c, protected, e), want)

    def test_auto_run_replaces_only_undecided_candidates(self):
        ex = self.put(self.ex)
        self.asked(ex, cand(ex, sid(8), "pump", legend_source="project+symbols"), cand(ex, sid(9), "pump"), auto=False)
        doc = ar.load_doc(NAME)
        ar.reject(doc, [doc["candidates"][1]["cand_id"]], BY)
        self.asked(ex, cand(ex, sid(8), "check_valve"), cand(ex, sid(9), "check_valve"))
        self.assertEqual(sorted((c["target"], c["values"], c["status"]) for c in ar.load_doc(NAME)["candidates"]),
                         [(sid(8), ["check_valve"], "proposed"), (sid(9), ["pump"], "rejected")])
        self.asked(ex, cand(ex, sid(8), "pump"), auto=False)
        self.assertEqual([c["values"] for c in ar.load_doc(NAME)["candidates"] if c["target"] == sid(8)], [["check_valve"]], "사람이 시킨 실행은 지금처럼 덮지 않음")

    def test_run_marks_input_and_legend(self):
        from tests.test_ai_review import StubClient, ex_fixture, good_answers
        plain = ar.run(ex_fixture(), StubClient(good_answers))["candidates"]
        self.assertEqual({(c["input"], c["legend_source"]) for c in plain}, {("text", None)})


# ---------------------------------------------------------------- 되돌리기(설계 4.4)

class RevertTest(Base):
    def test_r09_reverts_the_whole_sheet_and_only_auto(self):
        self.on()
        ex = self.put(unread(pdf_extraction(), sid(8), sid(17), sid(16)))
        human = cand(ex, sid(16), "check_valve", 0.2)
        self.asked(ex, cand(ex, sid(8), "check_valve"), cand(ex, sid(17), "pump"), human)
        ar.auto_finish(NAME, ex)
        ar.accept(ar.load_doc(NAME), [human["cand_id"]], ex, NAME, BY)
        self.edit(ex, "set_tag", sid(14), {"tag": "X-14"})
        self.assertEqual(len(self.ops()), 4)
        self.assertEqual(len(ar.auto_revert(NAME, BY)), 2)
        self.assertEqual([(o["op"], o.get("accepted_by")) for o in self.ops()], [("set_kind", BY), ("set_tag", None)])
        self.assertEqual(ar.auto_revert(NAME, BY), [], "다시 해도 같은 끝")

    def test_r09_dependent_human_edit_needs_confirm(self):
        self.on()
        ex = self.simple()
        ar.auto_finish(NAME, ex)
        ops = self.ops()
        dep = co.make_op(ex, "set_tag", sid(9), {"tag": "X-9"}, BY, existing_ops=ops, name=NAME)
        dep["via"] = [ops[0]["op_id"]]
        co.save(NAME, ops + [dep], BY)
        with self.assertRaises(ar.RevertNeedsConfirm) as caught:
            ar.auto_revert(NAME, BY)
        self.assertEqual(caught.exception.dependents, [dep["op_id"]])
        self.assertEqual((len(self.ops()), self.status()["auto"]["result"]), (2, "confirmed"), "확인 전에는 아무것도 바뀌지 않음")
        self.assertEqual(ar.auto_revert(NAME, BY, confirm=[dep["op_id"]]), [o["op_id"] for o in ops] + [dep["op_id"]])
        self.assertEqual(self.ops(), [])

    def test_person_accepting_again_makes_it_human(self):
        self.on()
        ex = self.simple()
        ar.auto_finish(NAME, ex)
        first = self.ops()[0]["op_id"]
        ar.auto_revert(NAME, BY)
        doc = ar.load_doc(NAME)
        self.assertEqual(ar.accept(doc, [doc["candidates"][0]["cand_id"]], ex, NAME, BY), [])
        op = self.ops()[0]
        self.assertEqual((op["op_id"], op["by"], op["accepted_by"]), (first, BY, BY))
        self.assertNotIn("auto", self.node(ex, sid(8))["human_edit"])

    def test_auto_op_whose_candidate_is_gone_is_reverted_too(self):
        self.on()
        ex = self.simple()
        ar.auto_finish(NAME, ex)
        os.remove(ar.store_path(NAME))
        self.assertEqual(len(ar.auto_revert(NAME, BY)), 1)
        self.assertEqual(self.ops(), [])


# ---------------------------------------------------------------- 하류 표시(설계 5장)

class MarkTest(Base):
    def build(self):
        self.on()
        ex = unread(pdf_extraction(), sid(8))
        by_sid(ex)[sid(14)].update(tag=None)
        by_sid(ex)[sid(14)]["attributes"].pop("tag", None)
        self.put(ex)
        self.asked(ex, cand(ex, sid(8), "check_valve"), cand(ex, sid(14), "V777", field="tag"))
        ar.auto_finish(NAME, ex)
        self.assertEqual(len(self.ops()), 2)
        return ex, co.resolve(NAME, ex)["corrected"]

    def graph_node(self, ex, s):
        g = build.build_graph(co.resolve(NAME, ex)["corrected"])
        return g, next(n for n in g["nodes"] if n["source_object_id"] == s)

    def tag_claim(self, g, s):
        return next(c for c in claims.drawing_claims(g) if c["source"]["source_object_id"] == s and c["property"] == "tag")

    def test_r10_auto_kind_is_not_a_legend_sample_and_tag_basis_is_ai_auto(self):
        ex, cor = self.build()
        box = ar._box(by_sid(ex)[sid(8)])
        self.assertNotIn(box, [b for _k, b in ai_images.confirmed_samples(cor)])
        self.assertEqual(by_sid(cor)[sid(14)]["evidence"]["tag_basis"], "ai_auto")
        self.assertEqual(by_sid(cor)[sid(8)]["human_edit"]["auto"], ["set_kind"])
        self.edit(ex, "set_kind", sid(8), {"kind": "check_valve", "category": "valve"})
        cor = co.resolve(NAME, ex)["corrected"]
        self.assertNotIn("auto", by_sid(cor)[sid(8)]["human_edit"])
        self.assertIn(box, [b for _k, b in ai_images.confirmed_samples(cor)])

    def test_r11_graph_and_claims(self):
        ex, _cor = self.build()
        g, kind_node = self.graph_node(ex, sid(8))
        _g, tag_node = self.graph_node(ex, sid(14))
        _g, plain = self.graph_node(ex, sid(9))
        self.assertEqual((kind_node["origin"], kind_node["auto"]), ("ai_auto", ["kind"]))
        self.assertEqual((tag_node["origin"], tag_node["auto"]), ("ai_auto", ["tag"]))
        self.assertIn("[추론]", tag_node["tag_basis"], "자동 연결이 추정 태그로 다룸(hazop.kg.auto)")
        self.assertNotIn("auto", plain)
        row = lambda s: [self.tag_claim(g, s)[k] for k in ("origin", "method", "knowledge_status")]  # noqa: E731
        self.assertEqual(row(sid(14)), ["ai_auto", "ai", "hypothesis"])
        self.assertEqual(row(sid(9)), ["pid_extract", "extractor", "confirmed"])
        self.assertEqual((screen.made_by(kind_node), screen.made_by(plain)), ("자동 확정(AI)", "도면 추출"))
        self.edit(ex, "set_tag", sid(8), {"tag": "X-8"})
        g, n = self.graph_node(ex, sid(8))
        self.assertEqual((n["origin"], n["auto"]), ("human_edit", ["kind"]))
        self.assertEqual(screen.made_by(n), "사람 수정, 자동 확정(AI)")
        self.assertEqual([self.tag_claim(g, sid(8))[k] for k in ("origin", "method", "knowledge_status")],
                         ["human_edit", "manual", "confirmed"])

    def test_human_tag_over_auto_tag(self):
        ex, _cor = self.build()
        self.edit(ex, "set_tag", sid(14), {"tag": "X-14"})
        g, n = self.graph_node(ex, sid(14))
        self.assertEqual([self.tag_claim(g, sid(14))[k] for k in ("value", "origin", "knowledge_status")],
                         ["X-14", "human_edit", "confirmed"])
        self.assertNotIn("auto", n)


# ---------------------------------------------------------------- 도면 번호 자동 확정(설계 6장)

class NumberTest(Base):
    def setUp(self):
        Base.setUp(self)
        p = mock.patch.object(tb, "AUTO_NUMBER_ENABLED", True, create=True)
        p.start()
        self.addCleanup(p.stop)

    def add(self, ext="drawio", drawing="SNP-M-101", tail=b"", name=None):
        src = os.path.join(self.tmp, (name or drawing) + "." + ext)
        with open(sample(drawing, ext), "rb") as fh:
            body = fh.read()
        with open(src, "wb") as fh:
            fh.write(body + tail)
        res = registry.register(src, P, store_root=paths.store_root(), actor=BY)
        self.assertEqual(res["outcome"], "registered", res.get("notes"))
        return res["record"]["material_id"]

    def twin(self):
        return self.add(tail=b"\n<!-- twin -->\n", name="b")

    def number(self, mid):
        return registry.latest(P, mid)[0]["drawing_number"]

    def test_r12_the_extraction_has_the_confirmed_number(self):
        from hazop.app import data
        mid = self.add()
        out = tb.auto_confirm_number(P, mid)
        self.assertEqual((out["confirmed"], out["why"]), (True, None))
        got = data.extract_and_graph(out["registration_file"])
        self.assertEqual((got["extraction"]["drawing"]["drawing_number"], got["graph"]["graph_id"]),
                         ("SNP-M-101", "graph-SNP-M-101"))
        rec = registry.latest(P, mid)[0]
        self.assertEqual((rec["registration_version"], rec["history"][-1]["by"], rec["design_revision"]), (2, AUTO, None))
        again = tb.auto_confirm_number(P, mid)
        self.assertEqual((again["confirmed"], again["why"], registry.latest(P, mid)[0]["registration_version"]), (True, None, 2))

    def test_r13_two_threads_confirm_one(self):
        a, b = self.add(), self.twin()
        out, gate = {}, threading.Barrier(2)

        def work(mid):
            gate.wait()
            out[mid] = tb.auto_confirm_number(P, mid)
        ts = [threading.Thread(target=work, args=(m,)) for m in (a, b)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sorted(o["confirmed"] for o in out.values()), [False, True])
        self.assertEqual([o["why"] for o in out.values() if not o["confirmed"]], ["taken"])
        self.assertEqual(sorted(str(self.number(m)) for m in (a, b)), ["None", "SNP-M-101"])

    def test_r13_check_and_write_are_one_step(self):
        a, b = self.add(), self.twin()
        real, other = tb._others, []

        def slow(*args):
            got = real(*args)
            if not other:              # 겹침을 본 뒤 쓰기 전에 다른 스레드가 같은 번호를 확정하려 한다
                other.append(threading.Thread(target=lambda: other.append(tb.auto_confirm_number(P, b))))
                other[0].start()
                other[0].join(1.0)
            return got
        with mock.patch.object(tb, "_others", slow):
            first = tb.auto_confirm_number(P, a)
        other[0].join(30)
        self.assertEqual((first["confirmed"], other[1]["confirmed"], other[1]["why"]), (True, False, "taken"))

    def test_r13_records_under_the_new_name(self):
        from hazop.study import nodes
        mid = self.add()
        store_io.write_json(os.path.join(nodes.store_dir(), P, "project-%s.json" % P),
                            {"nodes": [{"node_id": "S1", "members": ["graph-SNP-M-101/entity-node-001"]}]})
        self.assertEqual(tb.auto_confirm_number(P, mid)["why"], "has_records")
        self.assertIsNone(self.number(mid))

    def test_chosen_source_blocks(self):
        mid = self.add()
        with mock.patch.object(sources, "load_choices", lambda *a, **k: {"snp-m-101": {"format": "pdf"}}):
            self.assertEqual(tb.auto_confirm_number(P, mid)["why"], "has_records")

    def test_other_format_and_other_letters_are_taken(self):
        first = self.add()
        registry.register(os.path.join(self.tmp, "SNP-M-101.drawio"), P, store_root=paths.store_root(),
                          metadata={"drawing_number": "snp-m-101", "by": BY}, number_checked=True)
        self.assertEqual(self.number(first), "snp-m-101", "시험 전제")
        second = self.add("pdf")
        self.assertEqual((tb.auto_confirm_number(P, second)["why"], self.number(second)), ("taken", None))

    def test_taken_by_an_extracted_sheet(self):
        from hazop.app import data
        data.extract_and_graph(tb.auto_confirm_number(P, self.add())["registration_file"])
        self.assertEqual(tb.auto_confirm_number(P, self.twin())["why"], "taken")

    def test_empty_multi_page_reserved(self):
        mid = self.add()
        real = registry.latest
        docs = [{"document_id": "d", "page_ids": ["1", "2"], "pages": []}]
        for kw, why in (({"auto_candidates": {}}, "empty"), ({"auto_candidates": {"drawing_number": {"value": "  "}}}, "empty"),
                        ({"documents": docs}, "multi_page"),
                        ({"auto_candidates": {"drawing_number": {"value": "material-000000000000-p0"}}}, "reserved")):
            def latest(*a, **k):
                r, path = real(*a, **k)
                return dict(copy.deepcopy(r), **kw), path
            with self.subTest(why), mock.patch.object(registry, "latest", latest):
                self.assertEqual(tb.auto_confirm_number(P, mid)["why"], why)
        self.assertIsNone(self.number(mid))

    def test_already_extracted_material_is_left_to_people(self):
        from hazop.app import data
        mid = self.add()
        data.extract_and_graph(registry.latest(P, mid)[1])
        self.assertEqual(tb.auto_confirm_number(P, mid)["why"], "extracted")
        self.assertIsNone(self.number(mid))

    def test_r16_registration_cut_before_the_index_is_finished_by_a_rerun(self):
        mid = self.add()
        with mock.patch.object(registry.Store, "save_index", side_effect=OSError("끊김")):
            with self.assertRaises(OSError):
                tb.auto_confirm_number(P, mid)
        out = tb.auto_confirm_number(P, mid)
        self.assertEqual((out["confirmed"], self.number(mid), registry.latest(P, mid)[0]["registration_version"]), (True, "SNP-M-101", 2))


# ---------------------------------------------------------------- 예약 이름(설계 2.4)

class ReservedNameTest(Base):
    def test_r14_refused_everywhere_a_person_enters(self):
        ex = self.put(unread(pdf_extraction(), sid(8)))
        doc = self.asked(ex, cand(ex, sid(8), "check_valve"))
        cid = [doc["candidates"][0]["cand_id"]]
        src = sample("SNP-M-101", "drawio")
        for who in (AUTO, " HAZOP:auto ", "hazop:robot"):
            for what, call in (
                    ("save_fp", lambda: co.save_fp(NAME, [], who)), ("save", lambda: co.save(NAME, [], who)),
                    ("make_op", lambda: co.make_op(ex, "set_tag", sid(9), {"tag": "Z-1"}, who)),
                    ("accept", lambda: ar.accept(doc, cid, ex, NAME, who)), ("reject", lambda: ar.reject(doc, cid, who)),
                    ("revert", lambda: ar.revert(doc, cid, NAME, who)), ("auto_revert", lambda: ar.auto_revert(NAME, who)),
                    ("clear_metadata", lambda: registry.clear_metadata(P, "material-x", ["title"], who))):
                with self.subTest(what=what, who=who), self.assertRaisesRegex(ValueError, "예약"):
                    call()
            for command in ("compare", "confirm", "unconfirm"):
                self.assertEqual(cf.execute(NAME, command, {}, by=who)["refused"][0]["code"], "bad_actor")
            self.assertEqual(tb.confirm(P, "material-x", {"title": "T"}, who)["refused"][0]["code"], "bad_actor")
            self.assertEqual(tb.unconfirm(P, "material-x", ["title"], who)["refused"][0]["code"], "bad_actor")
            for kw in ({"actor": who}, {"metadata": {"title": "T", "by": who}, "actor": BY}):
                self.assertEqual(registry.register(src, P, store_root=paths.store_root(), **kw)["outcome"], "on_hold")
        self.assertEqual((self.ops(), ar.load_doc(NAME)["candidates"][0]["status"]), ([], "proposed"))
        self.assertTrue(cf.execute(NAME, "status", by=AUTO)["ok"], "읽기는 이름을 보지 않음")

    def test_r14_smuggled_op_is_refused_but_undo_redo_of_an_auto_op_works(self):
        self.on()
        ex = self.put(unread(pdf_extraction(), sid(8)))
        op = co.make_op(ex, "set_tag", sid(9), {"tag": "Z-1"}, BY, name=NAME)
        for key in ("by", "accepted_by"):
            with self.assertRaisesRegex(ValueError, "예약"):
                co.save_fp(NAME, [dict(op, **{key: AUTO})], BY)
        self.asked(ex, cand(ex, sid(8), "check_valve"))
        ar.auto_accept(NAME, ex)
        ops = self.ops()
        self.assertEqual(len(ops), 1, "시험 전제")
        self.edit(ex, "set_tag", sid(9), {"tag": "Z-1"})          # 자동 연산이 있는 채로 사람이 저장
        co.save(NAME, [], BY)
        co.save(NAME, ops, BY)
        self.assertEqual(self.ops(), ops)

    def test_ordinary_names_still_work(self):
        ex = self.put(pdf_extraction())
        for who in (BY, "hazop", "hazopauto", "hazop.register"):
            co.make_op(ex, "set_tag", sid(9), {"tag": "Z-1"}, who)


# ---------------------------------------------------------------- 끊김(설계 10.1의 16)

class Cut(Exception):
    pass


class CrashTest(Base):
    def end(self, name=NAME):
        doc = ar.load_doc(name) or {}
        ops = [{k: v for k, v in o.items() if k not in ("at", "accepted_at")} for o in self.ops(name)]
        auto = self.status(name)["auto"]
        return (ops, [(c["cand_id"], c["status"], c["op_id"], c["decided_by"]) for c in doc.get("candidates") or []],
                auto and {k: auto[k] for k in ("result", "why", "accepted", "attempts", "ai", "unconfirmed")}, self.status(name)["level"])

    def two(self):
        self.on()
        ex = self.put(unread(pdf_extraction(), sid(8), sid(17)))
        cf.record_auto(NAME, "waiting", "started")
        self.asked(ex, cand(ex, sid(8), "check_valve"), cand(ex, sid(17), "pump"), calls=2)
        return ex

    def snapshot(self):
        saved = os.environ["HAZOP_WORK_ROOT"] + "-start"
        shutil.copytree(os.environ["HAZOP_WORK_ROOT"], saved)

        def restore():
            shutil.rmtree(os.environ["HAZOP_WORK_ROOT"])
            shutil.copytree(saved, os.environ["HAZOP_WORK_ROOT"])
        return restore

    def die_at(self, cut, after, call):
        """cut번째 쓰기 앞(after면 뒤)에서 죽는다. 죽은 뒤에는 되돌리는 쓰기도 일어나지 않는다. → 쓰려 한 횟수."""
        real, n = store_io.write_json, [0]

        def dying(path, *a, **k):
            n[0] += 1
            if n[0] > cut or (n[0] == cut and not after):
                raise Cut()
            return real(path, *a, **k)
        with mock.patch.object(store_io, "write_json", dying):
            try:
                call()
            except Cut:
                pass
        return n[0]

    def test_r16_every_write_can_be_the_last_one(self):
        ex = self.two()
        restore = self.snapshot()
        total = self.die_at(99, True, lambda: ar.auto_finish(NAME, ex))
        want = self.end()
        self.assertEqual((len(want[0]), want[3]), (2, "auto"))
        self.assertGreaterEqual(total, 3)
        for after in (False, True):
            for cut in range(1, total + 1):
                with self.subTest(cut=cut, after=after):
                    restore()
                    self.die_at(cut, after, lambda: ar.auto_finish(NAME, ex))
                    for _ in range(2):
                        ar.auto_finish(NAME, ex)
                        self.assertEqual(self.end(), want)

    def test_r16_revert_cut_anywhere_converges(self):
        ex = self.two()
        ar.auto_finish(NAME, ex)
        restore = self.snapshot()
        total = self.die_at(99, True, lambda: ar.auto_revert(NAME, BY))
        self.assertGreaterEqual(total, 3)
        for cut in range(1, total + 1):
            for after in (False, True):
                with self.subTest(cut=cut, after=after):
                    restore()
                    self.die_at(cut, after, lambda: ar.auto_revert(NAME, BY))
                    ar.auto_finish(NAME, ex)                         # 그사이 이어 하기가 돌아도 다시 넣지 않음
                    ar.auto_revert(NAME, BY)
                    self.assertEqual((self.ops(), self.status()["level"], self.status()["auto"]["result"]), ([], "extracted", "reverted"))
                    self.assertEqual({c["status"] for c in ar.load_doc(NAME)["candidates"]}, {"proposed"})
                    self.assertEqual(ar.auto_accept(NAME, ex)["accepted"], [])

    def test_r16_cut_before_the_answers_asks_again(self):
        ex = self.put(unread(pdf_extraction(), sid(8)))
        cf.record_auto(NAME, "waiting", "started")
        st = self.status()
        self.assertTrue(cf.auto_resumable(st))
        self.assertFalse(ar.auto_asked(ar.load_doc(NAME), st["read_key"]))
        self.asked(ex, cand(ex, sid(8), "check_valve"))
        self.assertTrue(ar.auto_asked(ar.load_doc(NAME), st["read_key"]))

    def test_carry_twice_is_the_same(self):
        ex = self.put(pdf_extraction())
        self.put(ex, NEXT)
        cf.record_auto(NAME, "confirmed")
        cf.carry_auto(NAME, NEXT)
        before = store_io.fingerprint(cf.store_path(NEXT))
        cf.carry_auto(NAME, NEXT)
        self.assertEqual(store_io.fingerprint(cf.store_path(NEXT)), before)


# ---------------------------------------------------------------- 프로젝트의 'AI로 보내지 않음'

class SendPolicyTest(Base):
    DOC = {"kind": "hazop_ai_send_policy", "schema_version": "0.1", "project_id": P, "send": "deny", "by": BY, "at": "t", "reason": "보안"}

    def put_policy(self, body):
        p = ar.send_policy_path(P)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body if isinstance(body, str) else json.dumps(body, ensure_ascii=False))

    def test_unset_means_existing_behaviour(self):
        self.assertIsNone(ar.send_policy(P))
        self.assertIsNone(ar.send_policy(None))

    def test_values(self):
        for value in ("deny", "allow"):
            self.put_policy(dict(self.DOC, send=value))
            self.assertEqual(ar.send_policy(P), value)
        for bad in ("{깨짐", [], dict(self.DOC, send="maybe"), dict(self.DOC, kind="x"), dict(self.DOC, project_id="다른 프로젝트")):
            self.put_policy(bad)
            self.assertEqual(ar.send_policy(P), "deny", "읽을 수 없으면 보내지 않는 쪽")

    def test_run_sends_nothing_when_denied(self):
        from tests.test_ai_review import StubClient, ex_fixture, good_answers
        client = StubClient(good_answers)
        ex = dict(ex_fixture(), project_id=P)
        self.assertGreater(ar.run(ex, client)["stats"]["calls"], 0)
        self.put_policy(self.DOC)
        n = len(client.requests)
        stats = ar.run(ex, client)["stats"]
        self.assertTrue(stats["refused"])
        self.assertEqual((stats["calls"], len(client.requests)), (0, n))


# ---------------------------------------------------------------- 46b973ac 고정 코드(옛 앱)

OLD_SCRIPT = r'''
import json, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from hazop.extract import ai_review, confirmation as cf, corrections as co
from hazop.graph import build
name, step, by = sys.argv[2], sys.argv[3], "옛사람"
out = {}
with open(cf.extraction_path(name), encoding="utf-8") as fh:
    ex = json.load(fh)
if step == "read":
    st = cf.sheet_confirmation(name)
    out = {"state": st["state"], "default_view": st["default_view"], "record_error": st["record_error"]}
elif step == "confirm":
    real = cf.check
    cf.check = lambda *a, **k: dict(real(*a, **k), unconfirmed=[], unplaced=[], leftovers={"total": 0})
    out = [cf.execute(name, c, {}, by=by)["ok"] for c in ("compare", "confirm", "unconfirm")]
elif step == "unconfirm":
    out = cf.execute(name, "unconfirm", {}, by=by)["ok"]
elif step == "version":
    try:
        cf.sheet_confirmation(name)
        out = "read"
    except ValueError:
        out = "ValueError"
elif step == "reaccept":
    doc = ai_review.load_doc(name)
    cid = [c["cand_id"] for c in doc["candidates"]]
    ai_review.revert(doc, cid, name, by)
    out = {"failed": ai_review.accept(ai_review.load_doc(name), cid, ex, name, by)}
elif step == "graph":
    g = build.build_graph(co.resolve(name, ex)["corrected"])
    out = {"version": g["graph_version"], "ids": [[n["entity_id"], n["source_object_id"], n["kind"]] for n in g["nodes"]]}
elif step == "edit":
    ops = (co.load(name) or {}).get("ops") or []
    co.save(name, ops + [co.make_op(ex, "set_tag", "pdf-p0-sym-0009", {"tag": "OLD-9"}, by, existing_ops=ops, name=name)], by)
elif step == "protect":
    doc = ai_review.load_doc(name)
    out = ai_review.accept(doc, [c["cand_id"] for c in doc["candidates"]], ex, name, "hazop:auto")
sys.stdout.write("RESULT" + json.dumps(out, ensure_ascii=True))
'''


class OldAppTest(Base):
    @classmethod
    def setUpClass(cls):
        import tarfile
        cls.root = tempfile.mkdtemp(prefix="hazop-oldapp-")
        tar = os.path.join(cls.root, "old.tar")
        try:
            subprocess.run(["git", "-C", REPO, "archive", "--format=tar", "-o", tar, OLD, "hazop", "resources/library"],
                           check=True, capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            shutil.rmtree(cls.root, True)
            raise unittest.SkipTest("고정 커밋 %s를 꺼낼 수 없음" % OLD)
        with tarfile.open(tar) as t:
            t.extractall(cls.root, filter="data")
        cls.script = os.path.join(cls.root, "old_app.py")
        with open(cls.script, "w", encoding="utf-8") as fh:
            fh.write(OLD_SCRIPT)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, True)

    def old(self, step, name=NAME):
        p = subprocess.run([sys.executable, self.script, self.root, name, step], capture_output=True, timeout=120, encoding="utf-8",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=""), cwd=self.root)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout.split("RESULT")[-1])

    def record(self):
        return read(cf.store_path(NAME))

    def auto_sheet(self):
        self.on()
        ex = self.simple()
        ar.auto_finish(NAME, ex)
        self.assertEqual(self.status()["level"], "auto", "시험 전제")
        return ex

    def test_r15_old_app_reads_auto_as_not_confirmed(self):
        self.auto_sheet()
        self.assertEqual(self.old("read"), {"state": "open", "default_view": "original", "record_error": None})

    def test_r15_old_app_writes_keep_the_auto_cell(self):
        self.auto_sheet()
        before = self.record()["auto"]
        self.assertEqual(self.old("confirm"), [True, True, True])
        self.assertEqual(self.record()["auto"], before)
        self.assertEqual(self.status()["level"], "auto")

    def test_r15_old_app_resetting_a_broken_record_only_lowers_the_level(self):
        self.auto_sheet()
        store_io.write_json(cf.store_path(NAME), dict(self.record(), compared={"x": 1}))
        self.assertTrue(self.old("unconfirm"))
        self.assertEqual((self.status()["level"], self.status()["auto"]), ("extracted", None))
        self.assertFalse(cf.auto_resumable(self.status()))

    def test_r15_record_version_is_not_raised(self):
        self.auto_sheet()
        self.assertEqual((self.record()["schema_version"], self.old("version")), ("0.1", "read"))
        store_io.write_json(cf.store_path(NAME), dict(self.record(), schema_version="0.2"))
        self.assertEqual(self.old("version"), "ValueError", "판을 올리지 않는 까닭")

    def test_r15_rename_by_the_old_app_never_runs_again_by_itself(self):
        ex = self.auto_sheet()
        ar.auto_revert(NAME, BY)
        self.put(ex, NEXT)
        self.follow()
        self.assertFalse(cf.auto_resumable(self.status(NEXT)))
        self.assertEqual(ar.auto_accept(NEXT, ex)["accepted"], [])

    def test_r15_old_app_revert_and_accept_turns_the_op_human(self):
        ex = self.auto_sheet()
        op_id = self.ops()[0]["op_id"]
        self.assertEqual(self.old("reaccept"), {"failed": []})
        op = self.ops()[0]
        self.assertEqual((op["op_id"], op["by"], op["accepted_by"]), (op_id, "옛사람", "옛사람"))
        self.assertEqual(self.status()["auto_accepted"], 0)
        self.assertNotIn("auto", self.node(ex, sid(8))["human_edit"])

    def test_r15_old_app_edit_next_to_auto_ops(self):
        ex = self.auto_sheet()
        self.old("edit")
        self.assertEqual([o["op"] for o in self.ops()], ["set_kind", "set_tag"])
        self.assertEqual((self.status()["level"], self.status()["auto_accepted"]), ("auto", 1))
        self.assertEqual(self.node(ex, sid(9))["tag"], "OLD-9")

    def test_r15_old_app_accept_respects_human_edit(self):
        ex = self.put(unread(pdf_extraction(), sid(8)))
        self.asked(ex, cand(ex, sid(8), "check_valve"))
        self.edit(ex, "set_tag", sid(8), {"tag": "X-8"})
        self.assertEqual(len(self.old("protect")), 1)
        self.assertEqual([o["op"] for o in self.ops()], ["set_tag"])

    def test_r15_entity_ids_match_between_old_and_new_graphs(self):
        ex = self.auto_sheet()
        g = build.build_graph(co.resolve(NAME, ex)["corrected"])
        old = self.old("graph")
        self.assertEqual(old["ids"], [[n["entity_id"], n["source_object_id"], n["kind"]] for n in g["nodes"]])
        self.assertNotEqual(old["version"], g["graph_version"], "자동 표시가 든 쪽만 판이 다름")

    def test_r15_sheet_without_auto_ops_has_the_same_graph_version(self):
        ex = self.put(unread(pdf_extraction(), sid(8)))
        self.edit(ex, "set_kind", sid(8), {"kind": "check_valve", "category": "valve"})
        self.assertEqual(self.old("graph")["version"], build.build_graph(co.resolve(NAME, ex)["corrected"])["graph_version"])


if __name__ == "__main__":
    unittest.main()
