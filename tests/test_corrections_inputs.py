"""② 입력 연산(나누기 split·배관 지정 pipe)과 기준 추출 시험. 합성 1쪽 PDF(벡터 선)로 실제 추출 길을 탄다.
저장은 임시 HAZOP_WORK_ROOT 아래에만 한다. 근거: docs/units/2026-11-13-drawing-knowledge/evidence/fix-input-ops-design.md R1~R7."""

import copy
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from hazop.extract.adapters import pdf_vector  # noqa: E402
from hazop.graph import build  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from tests.test_adapter import make_pdf  # noqa: E402

HAS_PDFPLUMBER = importlib.util.find_spec("pdfplumber") is not None
NAME = "SYN-1"
AT = "2026-11-18T00:00:00Z"


def bowtie(x, y, w=20, h=10):
    t, b = y + h / 2, y - h / 2
    return ("%g %g m %g %g l %g %g l h S %g %g m %g %g l %g %g l h S"
            % (x, t, x, b, x + w / 2, y, x + w, t, x + w, b, x + w / 2, y)).encode()


def ln(x0, y0, x1, y1):
    return ("%g %g m %g %g l S" % (x0, y0, x1, y1)).encode()


def page(blob_dx=0, extra_line=False):
    """맞닿은 밸브 셋(한 덩어리로 읽힘, pdf-path-0004~0009) 양쪽에 배관, 그 뒤에 태그 없는 수동 밸브 둘.
    blob_dx: 가운데 밸브를 옮김(도면이 바뀐 판). extra_line: 먼 곳에 선 하나를 더 그려 pdf 개체 순번이 하나씩 밀린 판."""
    lines = [ln(40, 150, 100, 150), ln(160, 150, 220, 150), ln(240, 150, 300, 150), ln(320, 150, 380, 150)]
    lines = ([ln(10, 280, 30, 280)] if extra_line else []) + lines
    shapes = [bowtie(100, 150), bowtie(120 + blob_dx, 150), bowtie(140, 150), bowtie(220, 150), bowtie(300, 150)]
    return make_pdf(b"\n".join([b"1 w"] + lines + shapes), width=420, height=300)


BLOB = "pdf-p0-sym-0001"
GROUPS = [["pdf-path-0004", "pdf-path-0005"], ["pdf-path-0006", "pdf-path-0007"], ["pdf-path-0008", "pdf-path-0009"]]


def evidence(ex):
    return {n["source_object_id"]: tuple(sorted(n["evidence"]["pdf_objects"])) for n in ex["nodes"]}


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber 필요")
class InputOpsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get(paths.ENV_WORK_ROOT)
        os.environ[paths.ENV_WORK_ROOT] = self.tmp
        self.pdf = os.path.join(self.tmp, "syn.pdf")
        self.write_pdf(page())
        self.original = pdf_vector.extract(self.pdf, page=0, repo_root=self.tmp)
        out = os.path.join(paths.output_root("extract"), NAME)
        os.makedirs(out)
        with open(os.path.join(out, "extraction.json"), "w", encoding="utf-8") as fh:
            json.dump(self.original, fh, ensure_ascii=False)

    def tearDown(self):
        if self._old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = self._old
        shutil.rmtree(self.tmp)

    def write_pdf(self, data):
        with pdf_vector._cache_lock:
            pdf_vector._cache.clear()
        with open(self.pdf, "wb") as fh:
            fh.write(data)

    def split_ops(self, groups=GROUPS, kinds=("manual_valve",) * 3):
        ops = []
        for g, kind in zip(groups, kinds):
            ops.append(corrections.make_op(self.original, "split", BLOB,
                                           corrections.input_value(self.original, g, kind=kind), "김고침", at=AT,
                                           existing_ops=ops, name=NAME))
        return ops

    def save(self, ops):
        corrections.save(NAME, ops, "김고침", at=AT)

    def test_fixture_reads_one_lump_then_two_untagged_valves(self):
        ev = evidence(self.original)
        self.assertEqual(ev[BLOB], tuple(i for g in GROUPS for i in g))
        self.assertEqual([(n["source_object_id"], n["kind"], n["tag"]) for n in self.original["nodes"][1:]],
                         [("pdf-p0-sym-0002", "manual_valve", None), ("pdf-p0-sym-0003", "manual_valve", None)])

    def test_r1_split_keeps_other_symbol_ids_and_reattaches_pipe_ends(self):
        ops = self.split_ops()
        self.save(ops)
        got = corrections.resolve(NAME, allow_extract=True)
        base = got["base"]
        before, after = evidence(self.original), evidence(base)
        for sid in ("pdf-p0-sym-0002", "pdf-p0-sym-0003"):
            self.assertEqual(after[sid], before[sid], "덩어리 뒤 밸브 %s가 나누기 전과 같은 기호" % sid)
        self.assertNotIn(BLOB, after, "몸체가 모두 떨어진 덩어리는 없어짐")
        made = ["pdf-p0-split-%s" % o["op_id"] for o in ops]
        self.assertEqual([after[m] for m in made], [tuple(g) for g in GROUPS])
        self.assertEqual({n["kind"] for n in base["nodes"] if n["source_object_id"] in made}, {"manual_valve"})
        ends = {e["source_object_id"] for r in base["relations"] + base["unresolved_connectors"] for e in r["endpoints"]}
        self.assertTrue({made[0], made[2]} <= ends, "양쪽 배관 끝이 바깥쪽 나눈 기호에 붙음")
        self.assertEqual((got["inputs"]["state"], got["inputs"]["applied"], got["inputs"]["not_applicable"]),
                         ("ready", [o["op_id"] for o in ops], []))

    def test_r2_study_node_member_stays_on_its_valve(self):
        g1 = build.build_graph(self.original)
        ns = sn.confirm(sn.propose(g1, at=AT), g1, "김검토", at=AT)
        sn.save(ns)
        self.save(self.split_ops())
        g2 = build.build_graph(corrections.resolve(NAME, allow_extract=True)["corrected"])
        moved = sn.load(g2)
        by1 = {n["entity_id"]: n for n in g1["nodes"]}
        by2 = {n["entity_id"]: n for n in g2["nodes"]}
        renamed = moved["history"][-1]["detail"]["renamed"]
        for seg in ns["nodes"]:
            for m in seg["members"]:
                if by1[m]["source_object_id"] in ("pdf-p0-sym-0002", "pdf-p0-sym-0003"):
                    self.assertEqual(by2[renamed.get(m, m)]["bbox"], by1[m]["bbox"])

    def test_r3_edit_on_split_symbol_records_what_it_relies_on(self):
        ops = self.split_ops()
        self.save(ops)
        base = corrections.resolve(NAME, allow_extract=True)["base"]
        target = "pdf-p0-split-%s" % ops[1]["op_id"]
        tag = corrections.make_op(base, "set_tag", target, {"tag": "V-101"}, "김고침", at=AT, existing_ops=ops, name=NAME)
        self.assertEqual(tag["via"], [ops[1]["op_id"]])
        self.save(ops + [tag])
        node = next(n for n in corrections.resolve(NAME)["corrected"]["nodes"] if n["source_object_id"] == target)
        self.assertEqual(node["tag"], "V-101")

    def test_r4_undoing_split_restores_original_and_reports_dependent_edit(self):
        ops = self.split_ops()
        self.save(ops)
        base = corrections.resolve(NAME, allow_extract=True)["base"]
        target = "pdf-p0-split-%s" % ops[1]["op_id"]
        tag = corrections.make_op(base, "set_tag", target, {"tag": "V-101"}, "김고침", at=AT, existing_ops=ops, name=NAME)
        self.assertEqual(corrections.dependents(ops + [tag], ops[1]["op_id"]), [tag["op_id"]])
        self.save(ops + [tag])
        no_split = [tag]
        self.save(no_split)
        got = corrections.resolve(NAME, allow_extract=True)
        self.assertEqual(json.dumps(got["base"], sort_keys=True), json.dumps(self.original, sort_keys=True))
        self.assertEqual(got["corrected"]["corrections"]["not_applicable"],
                         [{"op_id": tag["op_id"], "reason": "나누기 %s이(가) 되돌려져 대상이 없음" % ops[1]["op_id"]}])
        self.save([])
        self.assertEqual(json.dumps(corrections.resolve(NAME)["corrected"], sort_keys=True),
                         json.dumps(self.original, sort_keys=True), "입력 연산을 넣었다 빼면 원래대로")

    def test_r5_objects_are_found_again_by_shape(self):
        ops = self.split_ops()
        self.save(ops)
        self.write_pdf(page(extra_line=True))
        got = corrections.resolve(NAME, allow_extract=True)
        self.assertEqual(got["inputs"]["applied"], [o["op_id"] for o in ops])
        self.assertEqual(len(got["inputs"]["retargeted"]), 6, "pdf 개체 순번이 바뀌어도 모양으로 다시 찾음")

    def test_r5_changed_drawing_is_not_applicable_with_count(self):
        ops = self.split_ops()
        self.save(ops)
        self.write_pdf(page(blob_dx=3))
        got = corrections.resolve(NAME, allow_extract=True)
        self.assertEqual(got["inputs"]["not_applicable"],
                         [{"op_id": ops[1]["op_id"], "reason": "도면이 바뀌어 나눌 개체를 찾지 못함(2개 중 2개)"}])

    def test_pending_without_extract_keeps_original_and_marks_inputs(self):
        ops = self.split_ops()
        self.save(ops)
        got = corrections.resolve(NAME)
        self.assertEqual(got["inputs"]["state"], "pending")
        self.assertIs(got["base"], got["original"])
        self.assertEqual(got["corrected"]["corrections"]["input_ops"], [o["op_id"] for o in ops])
        self.assertEqual(corrections.ensure_base(NAME), "ready")
        self.assertEqual(corrections.resolve(NAME)["inputs"]["state"], "ready")

    def test_base_is_rebuilt_when_extract_code_fingerprint_changes(self):
        ops = self.split_ops()
        self.save(ops)
        with mock.patch.object(corrections, "code_fingerprint", lambda: "code-a"):
            self.assertEqual(corrections.ensure_base(NAME), "ready")
            self.assertEqual(corrections.resolve(NAME)["inputs"]["state"], "ready")
        with mock.patch.object(corrections, "code_fingerprint", lambda: "code-b"):
            self.assertEqual(corrections.resolve(NAME)["inputs"]["state"], "pending")
            self.assertEqual(corrections.ensure_base(NAME), "ready")
            self.assertEqual(corrections.resolve(NAME)["inputs"]["state"], "ready")
        with mock.patch.object(corrections, "code_fingerprint", lambda: "code-a"):
            self.assertEqual(corrections.resolve(NAME)["inputs"]["state"], "pending")

    def test_pipe_op_is_stored_but_not_yet_extracted(self):
        op = corrections.make_op(self.original, "pipe", None,
                                 corrections.input_value(self.original, ["pdf-path-0001"], ring=False, line_type="process"),
                                 "김고침", at=AT, name=NAME)
        self.save([op])
        got = corrections.resolve(NAME, allow_extract=True)
        self.assertEqual(got["inputs"]["not_applicable"], [{"op_id": op["op_id"], "reason": corrections.PIPE_PENDING}])
        self.assertEqual(got["base"], got["original"])

    def test_r7_no_input_ops_is_byte_identical(self):
        tag = corrections.make_op(self.original, "set_tag", "pdf-p0-sym-0002", {"tag": "V-1"}, "김고침", at=AT, name=NAME)
        self.save([tag])
        got = corrections.resolve(NAME)
        self.assertIs(got["base"], got["original"])
        self.assertEqual(json.dumps(got["corrected"], sort_keys=True),
                         json.dumps(corrections.apply(self.original, [tag]), sort_keys=True))
        self.assertEqual(got["inputs"]["state"], "none")
        self.assertFalse(os.path.exists(corrections.base_path(NAME)))
        self.assertEqual(pdf_vector.extract(self.pdf, page=0, repo_root=self.tmp), self.original)


class InputOpCheckTest(unittest.TestCase):
    PDF = {"sha256": "0" * 64, "page": 0, "reader": "pdfplumber-0.11.9"}

    def test_value_checks(self):
        good = {"pdf": self.PDF, "objects": ["pdf-path-0001"], "shapes": {"pdf-path-0001": [0, 0, 1, 1, 2, False]}}
        corrections.OPS["split"].check(dict(good, kind="manual_valve"))
        corrections.OPS["pipe"].check(dict(good, ring=True, line_type="process"))
        for bad in (dict(good, pdf=None), dict(good, objects=[]), dict(good, shapes={}), dict(good, kind="no_such_kind")):
            with self.assertRaises(ValueError):
                corrections.OPS["split"].check(bad)
        with self.assertRaises(ValueError):
            corrections.OPS["pipe"].check(dict(good, ring="yes", line_type="process"))

    def test_drawio_drawing_refuses_input_ops(self):
        ex = {"source": {"format": "drawio", "file": "x.drawio"}}
        with self.assertRaisesRegex(ValueError, "벡터 PDF 도면만"):
            corrections.input_value(ex, ["pdf-path-0001"])

    def test_fingerprint_objs_rematches_shifted_target(self):
        def ex(ids):
            nodes = [{"local_id": "n%d" % i, "source_object_id": sid, "kind": "manual_valve", "category": "valve", "tag": None,
                      "evidence": {"pdf_objects": objs}} for i, (sid, objs) in enumerate(ids)]
            locs = [{"local_id": "n%d" % i, "bbox": [10 * i, 0, 4, 4]} for i in range(len(ids))]
            return {"nodes": nodes, "relations": [], "unresolved_connectors": [], "source_locations": locs}
        old = ex([("s1", ["p1"]), ("s2", ["p2"])])
        new = ex([("s0", ["p0"]), ("s1", ["p9"]), ("s2", ["p1"])])
        fp = corrections._fingerprints(old)["s1"]
        self.assertIn("objs", fp)
        self.assertEqual(corrections._rematch(fp, corrections._fingerprints(new)), "s2")

    def test_old_ai_split_add_node_still_applies(self):
        ex = {"nodes": [], "relations": [], "unresolved_connectors": [], "source_locations": [], "texts": [],
              "unclassified": [], "coordinate_system": {"coordinate_space": "pdf", "unit": "pt"},
              "validation": {"status": "passed", "blockers": [], "unknowns": []}, "drawing": {"ignored_objects": []}}
        op = {"op_id": "c-0001", "op": "add_node", "target": None, "base": None, "refs": {}, "origin": "ai",
              "ai_candidate": "split:pdf-p0-sym-0001:1a2b3c4d5e6f",
              "value": {"kind": "manual_valve", "category": "valve", "bbox": [1, 2, 3, 4]}, "by": "x", "at": AT}
        out = corrections.apply(ex, [op])
        self.assertEqual(out["corrections"]["applied"], ["c-0001"])
        self.assertEqual(out["nodes"][0]["source_object_id"], "manual-c-0001")


class CodeFingerprintTest(unittest.TestCase):
    """기준 추출 열쇠의 추출 코드 지문(설계 문서 '기준 추출 열쇠'). 임시 트리의 파일 내용으로 지문이 바뀌는지 본다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pkg = "fpkg%d" % id(self)
        os.makedirs(os.path.join(self.tmp, self.pkg))
        self.write("__init__.py", b"")
        sys.path.insert(0, self.tmp)
        importlib.invalidate_caches()

    def tearDown(self):
        sys.path.remove(self.tmp)
        for k in [k for k in sys.modules if k == self.pkg or k.startswith(self.pkg + ".")]:
            del sys.modules[k]
        shutil.rmtree(self.tmp)

    def write(self, name, data):
        with open(os.path.join(self.tmp, self.pkg, name), "wb") as fh:
            fh.write(data)

    def fp(self, data=("data.json",)):
        return corrections._compute_code_fingerprint((self.pkg + ".mod",), tuple((self.pkg, d) for d in data))

    def test_source_change_changes_fingerprint_but_line_endings_do_not(self):
        self.write("mod.py", b"X = 1\nY = 2\n")
        self.write("data.json", b"{}\n")
        base = self.fp()
        self.assertEqual(self.fp(), base)
        self.write("mod.py", b"X = 1\r\nY = 2\r\n")
        self.assertEqual(self.fp(), base)
        self.write("mod.py", b"X = 1\nY = 3\n")
        changed = self.fp()
        self.assertNotEqual(changed, base)
        self.write("data.json", b'{"a": 1}\n')
        self.assertNotEqual(self.fp(), changed)

    def test_module_without_source_on_disk_is_fingerprinted_by_loader_code(self):
        """PyInstaller 묶음은 .py 없이 PYZ 안 코드 개체만 갖는다. 같은 길(소스 파일이 없고 로더가 코드를 줌)을 zip으로 만든다."""
        import zipfile
        zname = os.path.join(self.tmp, "bundle.zip")

        def build(src):
            with zipfile.ZipFile(zname, "w") as z:
                z.writestr("zmod.py", src)
            importlib.invalidate_caches()
            sys.modules.pop("zmod", None)
            return corrections._module_digest("zmod")

        sys.path.insert(0, zname)
        try:
            a = build("K = frozenset({'a', 'b'})\ndef f():\n    return 1\n")
            self.assertEqual(build("K = frozenset({'a', 'b'})\ndef f():\n    return 1\n"), a)
            self.assertNotEqual(build("K = frozenset({'a', 'b'})\ndef f():\n    return 2\n"), a)
            self.assertNotEqual(build("K = frozenset({'a', 'c'})\ndef f():\n    return 1\n"), a)
        finally:
            sys.path.remove(zname)
            sys.modules.pop("zmod", None)

    def test_real_fingerprint_is_stable_in_process(self):
        corrections.code_fingerprint.cache_clear()
        a = corrections.code_fingerprint()
        self.assertRegex(a, r"^[0-9a-f]{16}$")
        self.assertEqual(corrections._compute_code_fingerprint(), a)
        self.assertIs(corrections.code_fingerprint(), corrections.code_fingerprint())

    def test_key_changes_with_fingerprint_only(self):
        original = {"source": {"sha256": "s"}, "run": {"settings": {"page_index": 0}}, "extraction_run_id": "r"}
        ops = [{"op_id": "c-0001", "op": "split", "target": "t", "value": {"k": 1}}]
        with mock.patch.object(corrections, "code_fingerprint", lambda: "aaaa"):
            k1 = corrections.inputs_key(original, ops)
            self.assertEqual(corrections.inputs_key(original, ops), k1)
        with mock.patch.object(corrections, "code_fingerprint", lambda: "bbbb"):
            self.assertNotEqual(corrections.inputs_key(original, ops), k1)

    def test_listed_modules_cover_the_extract_import_closure(self):
        """build_base가 부르는 추출 길(pdf_vector)이 함수 안 import까지 닿는 hazop 모듈은, 패키지 껍데기를 빼고 전부 지문 목록에 있어야 한다."""
        import ast
        shells = {"hazop", "hazop.extract", "hazop.extract.adapters", "hazop.kg", "hazop.paths", "hazop.store_io"}

        def mod_file(name):
            p = os.path.join(REPO_ROOT, *name.split("."))
            for f in (p + ".py", os.path.join(p, "__init__.py")):
                if os.path.isfile(f):
                    return f
            return None

        closure, todo = set(), ["hazop.extract.adapters.pdf_vector"]
        while todo:
            name = todo.pop()
            if name in closure:
                continue
            closure.add(name)
            f = mod_file(name)
            with open(f, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            pkg = name if f.endswith("__init__.py") else name.rpartition(".")[0]
            for n in ast.walk(tree):
                names = []
                if isinstance(n, ast.Import):
                    names = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom):
                    base = n.module or ""
                    if n.level:
                        parts = pkg.split(".")
                        base = ".".join(parts[:len(parts) - (n.level - 1)] + ([n.module] if n.module else []))
                    names = [base] + [base + "." + a.name for a in n.names]
                todo += [x for x in names if x.startswith("hazop") and mod_file(x)]
        self.assertEqual(sorted(closure - shells - set(corrections.FINGERPRINT_MODULES)), [])
        for name in corrections.FINGERPRINT_MODULES:
            self.assertIsNotNone(mod_file(name), name)


if __name__ == "__main__":
    unittest.main()
