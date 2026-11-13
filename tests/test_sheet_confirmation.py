"""도면 쪽 확정(hazop.extract.confirmation) 시험. 근거: docs/design/app-shell-web.md §10.4·§10.7, docs/specs/dexpi-exchange.md §6.1.

가상 도면 SNP의 실제 추출 결과(scripts/check_edit_screen.install_sample)와 사람 수정 기록(corrections), AI 후보 기록(ai_review)을
임시 작업 루트에 두고 확인한다. 실행: python -m unittest tests.test_sheet_confirmation
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from hazop import paths  # noqa: E402
from hazop.extract import ai_review, corrections  # noqa: E402
from hazop.extract import confirmation as cf  # noqa: E402

BY = "검토자"
_TEMPLATE = {}


def template():
    """SNP-M-101을 한 번만 추출해 둔 작업 루트(시험마다 그 추출 폴더를 새 작업 루트로 복사해 쓴다)."""
    if "root" not in _TEMPLATE:
        from scripts.check_edit_screen import install_sample
        tmp = tempfile.mkdtemp(prefix="hazop-sheetconf-tpl-")
        with mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(tmp, "work"),
                                          "HAZOP_STORE_ROOT": os.path.join(tmp, "store")}):
            os.makedirs(os.environ["HAZOP_WORK_ROOT"])
            name = install_sample(os.environ["HAZOP_WORK_ROOT"], "SNP-M-101")
            _TEMPLATE.update(root=tmp, name=name, folder=os.path.join(paths.output_root("extract"), name))
    return _TEMPLATE


def tearDownModule():
    if "root" in _TEMPLATE:
        shutil.rmtree(_TEMPLATE["root"], ignore_errors=True)


def make_clean(ex):
    """실제 추출 결과에서 확정을 막는 것을 걷어 낸 사본(모양은 그대로)."""
    out = copy.deepcopy(ex)
    out.pop("corrections", None)
    out["validation"]["unknowns"] = []
    out["unresolved_connectors"] = []
    out["unclassified"] = []
    for n in out["nodes"]:
        n["classification"] = "classified"
        n["kind"] = n.get("kind") or "pump"
        if n.get("category") in cf.TAGGED and not (n.get("tag") or "").strip():
            n["tag"] = "T-" + n["local_id"]
    for r in out["relations"]:
        for ep in r["endpoints"]:
            ep["status"] = "connected"
    return out


class Base(unittest.TestCase):
    def setUp(self):
        tpl = template()
        self.tmp = tempfile.mkdtemp(prefix="hazop-sheetconf-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(self.tmp, "work"),
                                           "HAZOP_STORE_ROOT": os.path.join(self.tmp, "store")})
        env.start()
        self.addCleanup(env.stop)
        self.name = tpl["name"]
        shutil.copytree(tpl["folder"], os.path.join(paths.output_root("extract"), self.name))
        with open(cf.extraction_path(self.name), encoding="utf-8") as fh:
            self.real = json.load(fh)

    def write_extraction(self, ex):
        with open(cf.extraction_path(self.name), "w", encoding="utf-8") as fh:
            json.dump(ex, fh, ensure_ascii=False)

    def clean(self, **extra):
        ex = dict(make_clean(self.real), **extra)
        self.write_extraction(ex)
        return ex

    def ack(self, base, target, check, reason="사람이 원본과 견주어 그대로 둠"):
        doc = corrections.load(self.name)
        ops = list((doc or {}).get("ops") or [])
        ops.append(corrections.make_op(base, "confirm", target, {"items": [{"check": check, "reason": reason}]}, BY,
                                       existing_ops=ops, name=self.name))
        corrections.save(self.name, ops, BY)

    def ai(self, *cands):
        doc = ai_review.load_doc(self.name) or ai_review.new_doc(self.name, self.real)
        doc["candidates"] = [dict(c) for c in cands]
        ai_review.save_doc(doc)

    def run_cmd(self, command, args=None, **kw):
        kw.setdefault("by", BY)
        return cf.execute(self.name, command, args, **kw)

    def confirm_all(self):
        self.assertTrue(self.run_cmd("compare", {"mode": "side_by_side"})["ok"])
        out = self.run_cmd("confirm")
        self.assertTrue(out["ok"], out)
        return out


class CountTest(unittest.TestCase):
    def test_counts_match_the_clean_view_on_all_snp_sheets(self):
        from hazop.shell import clean_items
        from tests.test_clean_items import snp_extractions
        for sheet, ex in snp_extractions().items():
            with self.subTest(sheet):
                mine = cf.check(ex)
                view = clean_items.build(ex)
                self.assertEqual(sorted((str(u["id"]), u["reason"]) for u in mine["unconfirmed"]),
                                 sorted((str(u["id"]), u["reason"]) for u in view["unconfirmed"]))
                self.assertEqual([(u["id"], u["reason"]) for u in mine["unconfirmed"]],
                                 [(u["id"], u["reason"]) for u in view["unconfirmed"]], "도면 안 순서도 같음")
                self.assertEqual(mine["leftovers"]["total"], view["leftovers"]["n"])
                self.assertGreater(mine["counts"]["total"], 0)

    def test_unplaced_objects_are_counted_with_their_other_reasons(self):
        ex = {"source": {"format": "drawio"}, "validation": {"unknowns": [
                  {"check": "missing_drawing_number", "target": None, "reason": "도면 번호 없음"}]},
              "nodes": [{"local_id": "n1", "classification": "unclassified", "kind": None, "category": "valve"},
                        {"local_id": "n2", "classification": "classified", "kind": "pump", "category": "equipment",
                         "tag": "", "geometry": {"x": 0, "y": 0, "width": 10, "height": 10}}],
              "relations": [{"local_id": "r1", "endpoints": [{"end": "source", "point": [0, 0], "status": "connected"},
                                                            {"end": "target", "status": "open"}]}],
              "unresolved_connectors": [{"local_id": "u1", "endpoints": [{"point": [5, 50]}]}]}
        out = cf.check(ex)
        got = [(u["id"], u["reason"]) for u in out["unconfirmed"]]
        self.assertEqual(got, [("n2", "missing_tag"), ("u1", "unresolved_connector"), (None, "missing_drawing_number"),
                               ("n1", "unknown_symbol"), ("n1", "unplaced"), ("r1", "open_end"), ("r1", "unplaced")])
        self.assertEqual([u["id"] for u in out["unplaced"]], ["n1", "r1"])
        self.assertEqual((out["counts"]["unknowns"], out["counts"]["open_ends"], out["counts"]["unplaced"]), (1, 2, 2))

    def test_leftovers_by_read_method(self):
        base = {"nodes": [], "relations": []}
        self.assertIsNone(cf.leftovers(dict(base, source={"format": "pdf_vector"})), "PDF는 남은 선을 넘기지 않음")
        self.assertIsNone(cf.leftovers(dict(base, source={"format": "raster"})))
        self.assertIsNone(cf.leftovers(dict(base, source={})))
        self.assertEqual(cf.leftovers(dict(base, source={"format": "pdf_vector"},
                                           leftovers={"paths": [{}, {}], "texts": ["t1"]}))["total"], 3)
        self.assertEqual(cf.leftovers(dict(base, source={"format": "dexpi"}))["total"], 0)
        self.assertEqual(cf.leftovers(dict(base, source={"format": "drawio"}, unclassified=[{"local_id": "x"}]))["paths"], 1)

    def test_default_view(self):
        for fmt, state, want in (("drawio", "open", "clean"), ("dexpi", None, "clean"), ("pdf_vector", "ready", "original"),
                                 ("pdf_vector", "confirmed", "clean"), ("raster", "confirmed", "clean"),
                                 ("unknown", "confirmed", "original"), ("", None, "original"), (None, "confirmed", "original"),
                                 ("svg", "confirmed", "original")):
            with self.subTest(fmt=fmt, state=state):
                self.assertEqual(cf.default_view(fmt, state), want)


class StateTest(Base):
    def test_real_sheet_is_open_and_confirm_says_what_is_left(self):
        st = cf.sheet_confirmation(self.name)
        self.assertEqual(st["state"], "open")
        self.assertEqual(st["read_method"], "drawio")
        self.assertGreater(st["counts"]["total"], 0)
        out = self.run_cmd("compare")
        self.assertFalse(out["ok"])
        self.assertEqual(out["refused"][0]["target"], "unconfirmed")
        self.assertEqual(out["refused"][0]["code"], "rule")
        self.assertIn("미확인 %d곳" % st["counts"]["total"], out["refused"][0]["reason"])
        self.assertFalse(os.path.exists(cf.store_path(self.name)), "거절하면 아무것도 쓰지 않음")

    def test_compare_then_confirm_by_a_person_and_it_survives_reopening(self):
        self.clean()
        st = cf.sheet_confirmation(self.name)
        self.assertEqual((st["state"], st["default_view"]), ("ready", "clean"))
        early = self.run_cmd("confirm")
        self.assertFalse(early["ok"])
        self.assertEqual([r["target"] for r in early["refused"]], ["compared"])
        self.assertEqual(self.run_cmd("confirm", by="  ")["refused"][0]["code"], "bad_actor")
        cmp_ = self.run_cmd("compare", {"mode": "overlay"}, fingerprint=st["fingerprint"], rev=st["rev"])
        self.assertTrue(cmp_["ok"], cmp_)
        self.assertEqual(cmp_["status"]["state"], "ready")
        self.assertEqual(cmp_["status"]["fingerprint"], st["fingerprint"], "기록을 써도 세 파일 지문은 그대로")
        out = self.run_cmd("confirm", fingerprint=st["fingerprint"], rev=cmp_["rev"])
        self.assertTrue(out["ok"], out)
        conf = cf.sheet_confirmation(self.name)
        self.assertEqual(conf["state"], "confirmed")
        self.assertEqual(conf["confirmed"]["by"], BY)
        self.assertTrue(conf["confirmed"]["at"].endswith("Z"))
        self.assertEqual(conf["confirmed"]["leftovers_seen"], 0)
        self.assertEqual(conf["compared"]["mode"], "overlay")
        again = self.run_cmd("confirm")
        self.assertTrue(again["ok"] and not again["changed"], "이미 확정된 쪽은 쓰지 않음")
        with open(cf.store_path(self.name), encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual([e["action"] for e in rec["log"]], ["compare", "confirm"])
        self.assertEqual(rec["rev"], 2)

    def test_each_of_the_three_files_releases_the_confirmation(self):
        base = self.clean()
        node = base["nodes"][0]["source_object_id"]

        def touch_extraction():
            self.write_extraction(dict(base, rerun="다시 추출"))

        def touch_edits():
            self.ack(base, node, "missing_tag")

        def touch_ai():
            self.ai({"cand_id": "a1", "target": base["nodes"][0]["local_id"], "status": "rejected"})

        for key, touch in (("extraction", touch_extraction), ("edits", touch_edits), ("ai_review", touch_ai)):
            with self.subTest(key):
                self.confirm_all()
                self.assertEqual(cf.sheet_confirmation(self.name)["state"], "confirmed")
                touch()
                st = cf.sheet_confirmation(self.name)
                self.assertEqual(st["state"], "ready", "확정이 풀림")
                self.assertIsNone(st["confirmed"])
                self.assertEqual(sorted({r["what"] for r in st["released"]}), ["compared", "confirmed"])
                self.assertEqual({tuple(r["changed"]) for r in st["released"]}, {(key,)})
                self.confirm_all()
                with open(cf.store_path(self.name), encoding="utf-8") as fh:
                    log = json.load(fh)["log"]
                released = [e for e in log if e["action"] == "released"]
                self.assertTrue(released and all(e["changed"] == [key] for e in released[-2:]), "풀린 사실이 기록에 남음")

    def test_pending_ai_candidate_blocks_until_accepted_or_rejected(self):
        base = self.clean()
        lid = base["nodes"][0]["local_id"]
        self.ai({"cand_id": "a1", "target": lid, "status": "proposed"})
        st = cf.sheet_confirmation(self.name)
        self.assertEqual((st["state"], st["counts"]["ai_pending"]), ("open", 1))
        self.assertIn((lid, "ai_candidate"), [(u["id"], u["reason"]) for u in st["unconfirmed"]])
        self.ai({"cand_id": "a1", "target": lid, "status": "rejected"})
        self.assertEqual(cf.sheet_confirmation(self.name)["state"], "ready")

    def test_acknowledge_ends_a_missing_tag(self):
        base = make_clean(self.real)
        valve = next(n for n in base["nodes"] if n.get("category") in cf.TAGGED)
        valve["tag"] = None
        self.write_extraction(base)
        st = cf.sheet_confirmation(self.name)
        self.assertEqual([(u["id"], u["reason"]) for u in st["unconfirmed"]], [(valve["local_id"], "missing_tag")])
        self.ack(base, valve["source_object_id"], "missing_tag", "태그 없는 밸브")
        self.assertEqual(cf.sheet_confirmation(self.name)["state"], "ready")

    def test_pdf_sheet_needs_leftovers_from_the_extraction(self):
        self.clean(source=dict(self.real["source"], format="pdf_vector"))
        st = cf.sheet_confirmation(self.name)
        self.assertEqual((st["state"], st["leftovers"], st["default_view"]), ("open", None, "original"))
        out = self.run_cmd("compare")
        self.assertEqual([r["target"] for r in out["refused"]], ["leftovers"])
        self.clean(source=dict(self.real["source"], format="pdf_vector"),
                   leftovers={"paths": [{"bbox": [0, 0, 1, 1], "kind": "line"}], "texts": []})
        self.confirm_all()
        st = cf.sheet_confirmation(self.name)
        self.assertEqual((st["state"], st["default_view"], st["confirmed"]["leftovers_seen"]), ("confirmed", "clean", 1))

    def test_stale_fingerprint_or_rev_writes_nothing(self):
        self.clean()
        out = self.run_cmd("compare", fingerprint="sha256:낡은")
        self.assertEqual(out["refused"][0]["code"], "stale")
        out = self.run_cmd("compare", rev=7)
        self.assertEqual(out["refused"][0]["code"], "stale")
        self.assertFalse(os.path.exists(cf.store_path(self.name)))

    def test_unconfirm_needs_a_name_and_releases_both(self):
        self.clean()
        self.confirm_all()
        self.assertEqual(self.run_cmd("unconfirm", by=None)["refused"][0]["code"], "bad_actor")
        out = self.run_cmd("unconfirm", {"reason": "배관 하나가 빠짐"})
        self.assertTrue(out["ok"] and out["changed"], out)
        self.assertEqual(out["status"]["state"], "ready")
        self.assertIsNone(out["status"]["compared"])
        with open(cf.store_path(self.name), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["log"][-1]["reason"], "배관 하나가 빠짐")
        self.assertFalse(self.run_cmd("unconfirm")["changed"])

    def test_status_unknown_command_and_missing_sheet(self):
        self.assertTrue(cf.execute(self.name, "status")["ok"])
        self.assertEqual(self.run_cmd("lock")["refused"][0]["code"], "unknown_command")
        self.assertEqual(cf.execute("없는-쪽", "status")["refused"][0]["code"], "unreadable")
        with self.assertRaises(FileNotFoundError):
            cf.sheet_confirmation("없는-쪽")


if __name__ == "__main__":
    unittest.main()
