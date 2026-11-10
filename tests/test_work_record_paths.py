"""작업 루트 쪽 기록 경로 시험(HZ-GOV-02 §5.6, §6.6). 실행: python -m unittest tests.test_work_record_paths

작업 루트 폴더 이름이 바뀌어도 (1) 파일에 적는 경로는 0.1.x 이름 그대로이고(등록한 자료를 다시 추출해도 그래프 판이 같다),
(2) 0.1.x가 적어 둔 경로는 지금 폴더에서 읽힌다.
"""

import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402

# 0.1.x가 사용자 파일에 적은 경로의 예(이 PC의 작업 루트 사본과 표본 구간에서 가져왔다)
OLD_EXAMPLES = (
    "자료저장소/sample-project/originals/material-8bf200cdef9a/1/SNP-M-101_RCS-main-loop.drawio",
    "출력/추출/SNP-M-102/page.svg",
    "출력/추출/SNP-M-102/extraction.json",
    "출력/그래프/SNP-M-102/graph.json",
    "출력/samples/그래프/SNP-M-102/graph.json",
    "출력/지식그래프/kg-SNP-SAMPLE/v-1/knowledge_graph.json",
    "데이터/구간/region-SNP-M-102-pzr.json",
    "데이터/고정응답/region-SNP-M-102-pzr",
    "데이터/지식/SNP-SAMPLE",
)
# 0.1.x 코드(d86bd89)로 SNP-M-201 샘플을 프로젝트 'rich-demo'에 등록·추출해 얻은 그래프 판
REGISTERED_GRAPH_VERSION = "v-0c3f7251efc9"


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("x")
    return path


class WorkRecordPathTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hazop-workrec-")
        self.addCleanup(tmp.cleanup)
        self.root = os.path.join(paths.long_path(tmp.name), "work")

    def now_path(self, old):
        """0.1.x 경로 old가 지금 있을 자리."""
        for now, before in sorted(paths.work_names(), key=lambda r: -len(r[1])):
            if old == before or old.startswith(before + "/"):
                return os.path.join(self.root, *(now + old[len(before):]).split("/"))
        self.fail("표에 없는 옛 경로: %s" % old)

    def test_every_work_folder_is_recorded_under_its_old_name(self):
        for now, old in paths.work_names():
            with self.subTest(now=now):
                path = os.path.join(self.root, *now.split("/"), "a", "b.json")
                self.assertEqual(old + "/a/b.json", paths.rel_or_abs(path, self.root))
                self.assertEqual(old, paths.rel_or_abs(os.path.join(self.root, *now.split("/")), self.root))

    def test_old_examples_round_trip(self):
        for old in OLD_EXAMPLES:
            with self.subTest(old=old):
                path = touch(self.now_path(old))
                self.assertEqual(old, paths.rel_or_abs(path, self.root))
                self.assertTrue(os.path.samefile(path, paths.resolve_rel(old, self.root)))

    def test_old_record_resolves_to_the_current_folder_even_when_the_file_is_missing(self):
        """없는 파일도 지금 폴더로 푼다. 이 경로에 새로 쓰는 코드가 옛 이름 폴더를 다시 만들지 않는다."""
        for old in OLD_EXAMPLES:
            with self.subTest(old=old):
                self.assertEqual(os.path.normpath(self.now_path(old)), os.path.normpath(paths.resolve_rel(old, self.root)))

    def test_hand_written_variants_resolve(self):
        """'..'가 끼었거나, 역슬래시로 적었거나, 대소문자가 다른 옛 경로(Windows에서는 옮기기 전에 읽히던 경로)."""
        old = OLD_EXAMPLES[3]
        path = touch(self.now_path(old))
        head, _, tail = old.partition("/")
        for variant in (old.replace("/", "\\"), "./" + old, head + "/x/../" + tail, old.replace("SNP-M-102/graph", "snp-m-102/GRAPH"),
                        head + "/" + tail.upper()):
            with self.subTest(variant=variant):
                self.assertTrue(os.path.samefile(path, paths.resolve_rel(variant, self.root)))

    def test_a_file_at_the_recorded_path_wins(self):
        """옮기지 않은 작업 폴더(옛 이름 폴더가 그대로 있는 곳)에서는 적힌 자리의 파일을 읽는다."""
        old = OLD_EXAMPLES[3]
        direct = touch(os.path.join(self.root, *old.split("/")))
        self.assertTrue(os.path.samefile(direct, paths.resolve_rel(old, self.root)))

    def test_absolute_and_outside_paths_are_left_alone(self):
        outside = touch(os.path.join(os.path.dirname(self.root), "elsewhere", "store", "p", "originals", "a.drawio"))
        rel = paths.rel_or_abs(outside, self.root)
        self.assertEqual("../elsewhere/store/p/originals/a.drawio", rel)
        self.assertTrue(os.path.samefile(outside, paths.resolve_rel(rel, self.root)))
        self.assertEqual(outside, paths.resolve_rel(outside, self.root))

    def test_plain_rel_shows_the_name_on_disk(self):
        for now, _old in paths.work_names():
            self.assertEqual(now + "/x", paths.plain_rel(os.path.join(self.root, *now.split("/"), "x"), self.root))

    def test_old_resource_record_is_not_resolved_into_the_work_root(self):
        """'데이터/이탈후보/…'는 자원 폴더의 옛 이름이다. 파일이 없다고 작업 루트의 데이터 폴더로 풀지 않는다."""
        rel = "데이터/이탈후보/없는파일.json"
        self.assertEqual(os.path.join(self.root, rel), paths.resolve_rel(rel, self.root))

    def test_sample_region_graph_file_resolves(self):
        """표본 구간(resources/samples, 고치지 않는 파일)에 적힌 graph_file을 지금 그래프 폴더에서 찾는다."""
        with open(paths.folder(*SAMPLE_REGION), encoding="utf-8") as fh:
            rel = json.load(fh)["graph_ref"]["graph_file"]
        self.assertTrue(rel.startswith(paths.OLD_WORK_RELS[OUTPUT_KEY] + "/"), rel)
        path = touch(os.path.join(paths.output_in(self.root, GRAPH_KEY), "SNP-M-102", "graph.json"))
        self.assertTrue(os.path.samefile(path, paths.resolve_rel(rel, self.root)))


SAMPLE_REGION = ("표본", "regions", "region-SNP-M-102-pzr.json")
OUTPUT_KEY, GRAPH_KEY, EXTRACT_KEY = "출력", "그래프", "추출"


class RegisteredMaterialVersionTest(unittest.TestCase):
    """등록한 자료를 지금 코드로 추출하면 0.1.x 때와 같은 그래프 판이 나온다. 판은 추출 JSON 전체의 해시이고 그 안에
    source.file과 svg_file(저장 루트 아래 경로)이 들어 있다."""

    def run_script(self, env, *args):
        done = subprocess.run([sys.executable, *args], cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(0, done.returncode, done.stdout.decode("utf-8", "replace"))

    def graph_of(self, env, work):
        sample = [p for p in glob.glob(paths.folder("참고", "pid-samples", "*", "*.drawio")) if "SNP-M-201" in p][0]
        self.run_script(env, "scripts/register.py", "--project", "rich-demo", sample, "--drawing-number", "SNP-M-201",
                        "--revision", "0", "--by", "검토자(예시)", "--reason", "재현 자료")
        store = env.get(paths.ENV_STORE_ROOT) or paths.folder_in(work, "자료저장소")
        reg = glob.glob(os.path.join(store, "rich-demo", "registrations", "*", "*.json"))
        self.assertEqual(1, len(reg))
        self.run_script(env, "scripts/extract_drawio.py", "--registration", reg[0])
        self.run_script(env, "scripts/build_graph.py")
        name = "rich-demo__*"
        with open(glob.glob(os.path.join(paths.output_in(work, EXTRACT_KEY), name, "extraction.json"))[0], encoding="utf-8") as fh:
            extraction = json.load(fh)
        with open(glob.glob(os.path.join(paths.output_in(work, GRAPH_KEY), name, "graph.json"))[0], encoding="utf-8") as fh:
            return extraction, json.load(fh)

    def env(self, work, **more):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", **{paths.ENV_WORK_ROOT: work}, **more)
        if paths.ENV_STORE_ROOT not in more:
            env.pop(paths.ENV_STORE_ROOT, None)
        return env

    def test_registered_material_keeps_its_graph_version(self):
        with tempfile.TemporaryDirectory(prefix="hazop-workrec-") as tmp:
            work = os.path.join(paths.long_path(tmp), "work")
            extraction, graph = self.graph_of(self.env(work), work)
        old_store = paths.OLD_WORK_RELS["자료저장소"]
        self.assertEqual(old_store + "/rich-demo/originals/material-8cb400a20d1d/1/SNP-M-201_CVCS.drawio", extraction["source"]["file"])
        self.assertEqual(old_store + "/rich-demo/originals/material-8cb400a20d1d/1/derived/01_SNP-M-201.drawio.svg",
                         extraction["coordinate_system"]["svg_alignment"]["svg_file"])
        self.assertEqual(REGISTERED_GRAPH_VERSION, graph["graph_version"])

    def test_store_root_outside_the_work_root_still_extracts(self):
        """HAZOP_STORE_ROOT를 준 환경: 저장 루트가 작업 루트 밖이라 기록 경로가 '..'로 시작한다. 폴더 이름과 무관하다."""
        with tempfile.TemporaryDirectory(prefix="hazop-workrec-") as tmp:
            work, store = os.path.join(paths.long_path(tmp), "work"), os.path.join(paths.long_path(tmp), "kept")
            extraction, graph = self.graph_of(self.env(work, **{paths.ENV_STORE_ROOT: store}), work)
            self.assertEqual("../kept/rich-demo/originals/material-8cb400a20d1d/1/SNP-M-201_CVCS.drawio", extraction["source"]["file"])
            self.assertTrue(os.path.isfile(paths.resolve_rel(extraction["source"]["file"], work)))
            self.assertTrue(graph["graph_version"].startswith("v-"))


class OldNameTableTest(unittest.TestCase):
    def test_old_names_belong_to_folders_in_the_tables(self):
        work = {name for name, f in paths.FOLDERS.items() if f.root == "work"}
        self.assertLessEqual(set(paths.OLD_WORK_RELS), work)
        self.assertLessEqual(set(paths.OLD_OUTPUT_NAMES), set(paths.OUTPUT_FOLDERS))

    def test_no_two_folders_share_a_name(self):
        rows = paths.work_names()
        self.assertEqual(len(rows), len({now.lower() for now, _ in rows}))
        self.assertEqual(len(rows), len({old.lower() for _, old in rows}))


if __name__ == "__main__":
    unittest.main()
