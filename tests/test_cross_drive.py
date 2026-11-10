"""작업 루트 밖·다른 드라이브 파일의 백업 자리와 그래프 출처 경로(단위 A, docs/2026-11-10-plan/pstack-advice.md).

실제 드라이브 넘김: 임시 폴더(%TEMP%)와 저장소가 다른 드라이브일 때만 돈다. 드라이브가 하나인 환경은
os.path.relpath가 ValueError를 내게 바꾼 시험이 같은 경로를 본다."""

import glob
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402

TEMP_DRIVE = os.path.splitdrive(tempfile.gettempdir())[0].upper()
REPO_DRIVE = os.path.splitdrive(REPO_ROOT)[0].upper()
CROSS = bool(TEMP_DRIVE and REPO_DRIVE and TEMP_DRIVE != REPO_DRIVE)


def other_drive_dir(test):
    """저장소 드라이브 루트 아래 임시 폴더(임시 폴더와 다른 드라이브). 시험이 끝나면 지운다."""
    d = tempfile.mkdtemp(prefix="hazop-xdrive-", dir=REPO_DRIVE + os.sep)
    test.addCleanup(shutil.rmtree, d, True)
    return d


def temp_dir(test):
    d = tempfile.mkdtemp(prefix="hazop-xdrive-")
    test.addCleanup(shutil.rmtree, d, True)
    return d


def write(path, text="{}"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def all_files(root):
    return {os.path.join(d, f) for d, _s, fs in os.walk(root) for f in fs}


def in_stamp_folder(path, backup_root):
    """path가 <백업>/<시각>-<label>/ 아래인지. 덮어쓴 파일은 새 파일로 안 보이므로 돌려받은 복사본 경로도 이것으로 본다."""
    path = os.path.normpath(path)
    if not paths._inside(path, backup_root):
        return False
    parts = path[len(os.path.normpath(backup_root)):].strip(os.sep).split(os.sep)  # relpath는 흉내 시험에서 막혀 있다
    return len(parts) >= 2 and re.match(r"\d{8}T\d{6}Z-", parts[0]) is not None


def backup_folder(path):
    from hazop import store_io
    folder = store_io.backup([path], "시험")
    return folder, [f for f in all_files(folder)]


def backup_ie_store(path):
    from hazop.ie import store
    with mock.patch.object(store, "store_path", return_value=path):
        dst = store.backup("가상 PWR")
    return os.path.dirname(dst), [dst]


def backup_one(path):
    from hazop import store_io
    dst = store_io.backup_file(path, "시험")
    return dst, [dst]


BACKUPS = {"store_io.backup": backup_folder, "ie.store.backup": backup_ie_store, "store_io.backup_file": backup_one}


class BackupRelTest(unittest.TestCase):
    def test_inside_root_keeps_relative_path(self):
        root = os.path.join("D:" + os.sep, "w")
        self.assertEqual(paths.backup_rel(os.path.join(root, "데이터", "x.json"), root), os.path.join("데이터", "x.json"))  # 경로문자열-허용: 시험용 가짜 작업 루트 이름

    def test_outside_root_never_climbs_or_names_a_drive(self):
        root = os.path.join("D:" + os.sep, "a", "작업")  # 경로문자열-허용: 시험용 가짜 작업 루트 이름
        for p in (os.path.join("C:" + os.sep, "Users", "u", "x.json"), os.path.join("D:" + os.sep, "a", "작업2", "x.json"),
                  os.path.join("D:" + os.sep, "x.json"), r"\\srv\share\d\x.json"):
            rel = paths.backup_rel(p, root)
            self.assertFalse(os.path.isabs(rel), rel)
            self.assertNotIn(":", rel)
            self.assertNotIn("..", rel.replace("\\", "/").split("/"), rel)
            self.assertTrue(rel.endswith("x.json"), rel)

    def test_different_outside_files_get_different_places(self):
        root = os.path.join("D:" + os.sep, "w")
        a = paths.backup_rel(os.path.join("C:" + os.sep, "w", "x.json"), root)
        b = paths.backup_rel(os.path.join("E:" + os.sep, "w", "x.json"), root)
        self.assertNotEqual(a, b)


class BackupStaysInBackupFolderTest(unittest.TestCase):
    """세 백업 함수 모두: 복사본은 이번 백업 폴더 안에만 생기고, 원본과 같은 내용이다."""

    def run_case(self, work, src):
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: work}):
            backup_root = paths.folder("backup")
            for name, fn in BACKUPS.items():
                with self.subTest(name):
                    before = all_files(os.path.dirname(work)) | all_files(os.path.dirname(src))
                    folder, copies = fn(src)
                    after = all_files(os.path.dirname(work)) | all_files(os.path.dirname(src))
                    new = after - before
                    self.assertTrue(new, "백업이 아무것도 쓰지 않음")
                    for f in new | set(copies):
                        self.assertTrue(in_stamp_folder(f, backup_root), "이번 백업 폴더 밖에 씀: %s" % f)
                    for c in copies:
                        with open(c, encoding="utf-8") as fh:
                            self.assertEqual(fh.read(), '{"원본": 1}')
                    shutil.rmtree(backup_root)

    @unittest.skipUnless(CROSS, "임시 폴더와 저장소가 같은 드라이브")
    def test_a_other_drive_real(self):
        work = os.path.join(other_drive_dir(self), "작업")  # 경로문자열-허용: 시험용 가짜 작업 루트 이름
        src = write(os.path.join(temp_dir(self), "다른드라이브", "x.json"), '{"원본": 1}')
        self.run_case(work, src)

    def test_a_other_drive_simulated(self):
        base = temp_dir(self)
        src = write(os.path.join(base, "밖", "x.json"), '{"원본": 1}')
        with mock.patch.object(os.path, "relpath", side_effect=ValueError("path is on mount 'D:'")):
            self.run_case(os.path.join(base, "w", "작업"), src)  # 경로문자열-허용: 시험용 가짜 작업 루트 이름

    def test_b_same_drive_outside_root(self):
        base = temp_dir(self)
        src = write(os.path.join(base, "x.json"), '{"원본": 1}')
        self.run_case(os.path.join(base, "a", "b", "c", "d", "작업"), src)  # 경로문자열-허용: 시험용 가짜 작업 루트 이름

    def test_c_sibling_folder_with_similar_name(self):
        base = temp_dir(self)
        src = write(os.path.join(base, "작업2", "x.json"), '{"원본": 1}')
        self.run_case(os.path.join(base, "작업"), src)  # 경로문자열-허용: 시험용 가짜 작업 루트 이름


@unittest.skipUnless(CROSS, "임시 폴더와 저장소가 같은 드라이브")
class GraphFromOtherDriveTest(unittest.TestCase):
    def test_extraction_on_other_drive_builds_and_resolves(self):
        from hazop.app import data
        from hazop.contract import chain
        src = [p for p in glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio")) if "SNP-M-102" in p]
        if not src:
            self.skipTest("샘플 도면 없음")
        work = os.path.join(other_drive_dir(self), "작업")  # 경로문자열-허용: 시험용 가짜 작업 루트 이름
        outside = temp_dir(self)
        with mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: work}):
            ex = data.script_module("extract_drawio")
            bg = data.script_module("build_graph")
            _, out_dir = ex.run_one(src[0], os.path.join(outside, "extract"))
            graph, g_dir = bg.build_one(os.path.join(out_dir, "extraction.json"), paths.output_in(work, "graph"))
            rec = graph["source"]["extraction_file"]
            self.assertTrue(os.path.isabs(rec), rec)
            self.assertTrue(os.path.samefile(chain._resolve(rec, work), os.path.join(out_dir, "extraction.json")))
            with open(os.path.join(g_dir, "graph.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["source"]["extraction_file"], rec)


if __name__ == "__main__":
    unittest.main()
