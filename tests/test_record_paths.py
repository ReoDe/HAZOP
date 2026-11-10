"""기록 경로 시험(HZ-GOV-02 §6.1, §6.2). 실행: python -m unittest tests.test_record_paths

폴더를 영어 이름으로 옮긴 뒤에도 (1) 샘플 도면·APR1400 파일은 옮기기 전 이름으로 적히고(그래프 판이 그대로다),
(2) 사용자 파일에 남은 옛 경로는 새 폴더에서 읽힌다.
"""

import csv
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402

SAMPLE = ("SNP-M-102_RCS-pressurizer", "SNP-M-102_RCS-pressurizer.drawio")
# (지금 위치, 기록 경로). 지금 위치는 (FOLDERS 이름, 그 아래 경로…)
RECORDED = (
    (("references", "pid-samples") + SAMPLE, "참고자료/P&ID 도면 샘플/" + "/".join(SAMPLE)),
    (("references", "pid-samples", SAMPLE[0], "01_SNP-M-102.drawio.svg"), "참고자료/P&ID 도면 샘플/%s/01_SNP-M-102.drawio.svg" % SAMPLE[0]),
    (("references", "pid-symbol-catalog", "00_symbol_catalog.pdf"), "참고자료/P&ID 기호 카탈로그/00_symbol_catalog.pdf"),
    (("references", "photos", "a.jpg"), "참고자료/참고 사진/a.jpg"),
    (("references", "hazop-method", "b.pdf"), "참고자료/HAZOP 기법/b.pdf"),
    (("references", "새폴더", "c.txt"), "참고자료/새폴더/c.txt"),
    (("APR1400", "by-drawing", "005_Ch05.pdf"), "데이터/참고자료/APR1400_DCD/도면별/005_Ch05.pdf"),
    (("APR1400", "source", "ML18228A648.pdf"), "데이터/참고자료/APR1400_DCD/원본/ML18228A648.pdf"),
    (("APR1400", "system-codes.csv"), "데이터/참고자료/APR1400_DCD/계통약어.csv"),
    (("APR1400", "drawing-list.csv"), "데이터/참고자료/APR1400_DCD/도면목록.csv"),
)
# 사용자 파일에 남아 있을 수 있는 옛 경로 → 지금 위치. 모두 추적 파일이라 어느 PC에서나 있다.
OLD_RECORDS = (
    ("데이터/이탈후보/kosha-p86-2017-deviation-chart.json", ("deviations", "kosha-p86-2017-deviation-chart.json")),
    ("자원/기준/이탈후보/kosha-p86-2017-deviation-chart.json", ("deviations", "kosha-p86-2017-deviation-chart.json")),
    ("데이터/기준표/kosha-p86-2017-risk-criteria.json", ("risk-criteria", "kosha-p86-2017-risk-criteria.json")),
    ("자원/기준/기준표/kosha-p86-2017-risk-criteria.json", ("risk-criteria", "kosha-p86-2017-risk-criteria.json")),
    ("데이터/패턴/pressurizer-patterns.json", ("patterns", "pressurizer-patterns.json")),
    ("자원/기준/패턴/pressurizer-patterns.json", ("patterns", "pressurizer-patterns.json")),
    ("자원/기준/기호/묶음.json", ("symbols", "bundles.json")),
    ("자원/기준/기호/공통/그림/pattern_dot.png", ("symbols", "common", "images", "pattern_dot.png")),
    ("자원/기준/기호/APR1400/그림/gate_valve.png", ("symbols", "APR1400", "images", "gate_valve.png")),
    ("자원/표본/구간/region-SNP-M-102-pzr.json", ("samples", "regions", "region-SNP-M-102-pzr.json")),
    ("자원/표본/고정응답/region-SNP-M-102-pzr/deviation-p86-d09.json",
     ("samples", "fixed-responses", "region-SNP-M-102-pzr", "deviation-p86-d09.json")),
    ("자원/표본/지식/SNP-SAMPLE/knowledge_nodes.csv", ("samples", "knowledge-graph", "SNP-SAMPLE", "knowledge_nodes.csv")),
    ("자원/참고자료/P&ID 도면 샘플/" + "/".join(SAMPLE), ("references", "pid-samples") + SAMPLE),
    ("./참고자료/P&ID 도면 샘플/" + "/".join(SAMPLE), ("references", "pid-samples") + SAMPLE),
    ("참고자료\\P&ID 도면 샘플\\" + "\\".join(SAMPLE), ("references", "pid-samples") + SAMPLE),
    ("참고자료/APR1400_DCD/도면목록.csv", ("APR1400", "drawing-list.csv")),
    ("자원/참고자료/APR1400_DCD/계통약어.csv", ("APR1400", "system-codes.csv")),
    ("데이터/참고자료/APR1400_DCD/스크립트/make_index.py", ("APR1400", "scripts", "make_index.py")),
    # 손으로 적은 옛 경로: '..'가 끼었거나 대소문자가 다르다(Windows에서는 옮기기 전에 읽히던 경로)
    ("자원/기준/기호/공통/../묶음.json", ("symbols", "bundles.json")),
    ("참고자료/apr1400_dcd/계통약어.csv", ("APR1400", "system-codes.csv")),
    ("자원/기준/기호/apr1400/그림/GATE_VALVE.png", ("symbols", "APR1400", "images", "gate_valve.png")),
)


def same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class RecordPaths(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hazop-recpath-")
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def test_repo_only_files_are_written_with_the_names_from_before_the_move(self):
        for where, recorded in RECORDED:
            for root in (self.root, REPO_ROOT, paths.folder("references")):
                self.assertEqual(recorded, paths.rel_or_abs(paths.folder(*where), root), where)

    def test_recorded_name_reads_back_to_the_same_file(self):
        for where, recorded in RECORDED:
            real = paths.folder(*where)
            if os.path.exists(real):
                self.assertTrue(same(real, paths.resolve_rel(recorded, self.root)), recorded)
                self.assertEqual(recorded, paths.rel_or_abs(paths.resolve_rel(recorded, self.root), self.root))
        self.assertTrue(os.path.isfile(paths.folder(*RECORDED[0][0])), "샘플 도면이 없으면 위 왕복이 비어 버린다")

    def test_sample_records_are_reference_records(self):
        for where, recorded in RECORDED:
            self.assertEqual(where[0] == "references", paths.is_reference_rel(recorded), recorded)
        self.assertFalse(paths.is_reference_rel(paths.folder_rel("references") + "/pid-samples/x.drawio"))

    def test_old_records_in_user_files_still_resolve(self):
        for old, where in OLD_RECORDS:
            real = paths.folder(*where)
            self.assertTrue(os.path.isfile(real), real)
            self.assertTrue(same(real, paths.resolve_rel(old, self.root)), old)

    def test_every_tracked_file_moved_in_stage_5_resolves_from_its_old_name(self):
        """대응표(name-map.csv, stage 5)의 옛 이름 전부. 표에 줄이 빠지면 여기서 드러난다."""
        with open(os.path.join(REPO_ROOT, "docs", "2026-11-10-naming-rules", "name-map.csv"), encoding="utf-8-sig", newline="") as f:
            rows = [(r["old"], r["new"]) for r in csv.DictReader(f) if r["stage"] == "5"]
        self.assertGreater(len(rows), 100)
        for old, new in rows:
            self.assertTrue(same(os.path.join(REPO_ROOT, *new.split("/")), paths.resolve_rel(old, self.root)), old)

    def test_a_file_under_the_root_wins_over_the_old_name_table(self):
        own = os.path.join(self.root, "데이터", "이탈후보", "kosha-p86-2017-deviation-chart.json")
        os.makedirs(os.path.dirname(own))
        open(own, "w").close()
        self.assertTrue(same(own, paths.resolve_rel("데이터/이탈후보/kosha-p86-2017-deviation-chart.json", self.root)))

    def test_unknown_record_falls_back_to_the_root(self):
        self.assertTrue(same(os.path.join(self.root, "자원", "기준", "이탈후보", "없음.json"),
                             paths.resolve_rel("자원/기준/이탈후보/없음.json", self.root)))

    def test_copy_at_the_logical_place_gets_the_same_record(self):
        """샘플 도면 사본을 logical_dir에 두면 묶인 실행(저장소 폴더가 없는 곳)에서도 기록 경로가 같다."""
        dst = paths.logical_dir(self.root, "references", "pid-samples", *SAMPLE)
        self.assertEqual(os.path.join(self.root, "참고자료", "P&ID 도면 샘플", *SAMPLE), dst)
        self.assertEqual(RECORDED[0][1], os.path.relpath(dst, self.root).replace("\\", "/"))
        os.makedirs(os.path.dirname(dst))
        open(dst, "w").close()
        self.assertTrue(same(dst, paths.resolve_rel(RECORDED[0][1], self.root)))

    def test_resource_files_are_written_relative_to_the_resource_root(self):
        """기준 자료는 기록용 옛 이름을 쓰지 않는다. 새 기록은 새 폴더 이름으로 적히고 옛 기록은 표로 읽는다."""
        res = paths.resource_root()
        self.assertEqual("resources/library/deviations/x.json", paths.rel_or_abs(paths.folder("deviations", "x.json"), res))


class OutputFolderTest(unittest.TestCase):
    """출력 폴더는 열쇠로만 연다. 폴더 이름은 paths.OUTPUT_FOLDERS에만 있어서 이름을 바꿔도 아래가 그대로 성립한다."""

    def test_output_rel_is_the_name_on_disk_of_a_file_under_the_output_folder(self):
        root = os.path.abspath("w")
        for key in paths.OUTPUT_FOLDERS:
            full = paths.output_in(root, key, "x", "graph.json")
            self.assertEqual(paths.output_rel(key, "x", "graph.json"), paths.plain_rel(full, root), key)
            self.assertEqual(full, os.path.join(paths.folder_in(root, "output"), paths.output_name(key), "x", "graph.json"))
        self.assertEqual(paths.folder_rel("output"), paths.output_rel())
        self.assertEqual(paths.folder_in(root, "output"), paths.output_in(root))

    def test_a_name_outside_the_table_is_refused(self):
        with self.assertRaises(KeyError):
            paths.output_root("없는-폴더")
        with self.assertRaises(KeyError):
            paths.output_in("w", "없는-폴더", "x")

    def test_output_root_follows_the_work_root(self):
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: os.path.abspath("w")}):
            self.assertEqual(paths.output_in(os.path.abspath("w"), "analysis", "r"), paths.output_root("analysis", "r"))
            os.environ.pop(paths.ENV_STORE_ROOT, None)
            self.assertEqual(paths.folder_in(os.path.abspath("w"), "store"), paths.store_root())


if __name__ == "__main__":
    unittest.main()
