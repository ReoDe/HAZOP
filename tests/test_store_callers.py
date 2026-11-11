"""고정 이름 임시 파일('<파일>.tmp')로 쓰던 일곱 자리가 공용 원자적 쓰기(hazop.store_io)를 쓴다.
실행: python -m unittest tests.test_store_callers

자리마다 세 가지를 본다. 쓴 바이트가 전과 같다(직렬화 옵션 그대로), 교체가 실패해도 원본이 온전하고 임시 파일이 남지 않는다,
같은 폴더에 있는 '<파일>.tmp'(다른 쓰기가 쓰는 중일 수 있는 파일)를 건드리지 않는다.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths, workroot  # noqa: E402
from hazop.analysis import run as analysis_run  # noqa: E402
from hazop.kg import link as kg_link, screen as kg_screen  # noqa: E402
from hazop.register import registry  # noqa: E402
from hazop.study import apikey  # noqa: E402

DOC = {"b": "한글 값", "a": [1, {"z": None, "y": True}], "c": "줄\n바꿈"}
OTHER = {"b": "다른 값", "a": []}


def pretty(doc):
    """등록 정보·분석 결과·설정·이전 기록이 써 온 모양: 들여쓰기 2, 키 순서 그대로, 한글 그대로, 끝에 줄바꿈."""
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def raw(path):
    with open(path, "rb") as fh:
        return fh.read()


class Case:
    def __init__(self, label, path, write, expected):
        self.label, self.path, self.write, self.expected = label, path, write, expected


class FixedTempNameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-store-callers-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def cases(self):
        t = self.tmp
        csv_text = "열1,열2\r\n값,한글\r\n"
        html = "<html><body>지식그래프 화면</body></html>"
        root = os.path.join(t, "root")
        return [
            Case("등록 정보", os.path.join(t, "reg", "1.json"),
                 lambda p, d: registry._write_json(p, d), pretty),
            Case("분석 결과", os.path.join(t, "run", "analysis.json"),
                 lambda p, d: analysis_run._write(p, d), pretty),
            Case("지식 연결 CSV(BOM)", os.path.join(t, "csv", "links.csv"),
                 lambda p, d: kg_link.write_atomic(p, csv_text + json.dumps(d, ensure_ascii=False)),
                 lambda d: b"\xef\xbb\xbf" + (csv_text + json.dumps(d, ensure_ascii=False)).encode("utf-8")),
            Case("지식 연결 CSV(BOM 없음)", os.path.join(t, "plain", "plain.csv"),
                 lambda p, d: kg_link.write_atomic(p, csv_text + json.dumps(d, ensure_ascii=False), bom=False),
                 lambda d: (csv_text + json.dumps(d, ensure_ascii=False)).encode("utf-8")),
            Case("지식그래프 화면 HTML", os.path.join(t, "html", "kg.html"),
                 lambda p, d: kg_screen.write_html(p, html + json.dumps(d, ensure_ascii=False)),
                 lambda d: (html + json.dumps(d, ensure_ascii=False)).encode("utf-8")),
            Case("설정", os.path.join(t, "settings", "settings.json"),
                 lambda p, d: paths.save_settings(d, p), pretty),
            Case("작업 폴더 이전 기록", workroot.manifest_path(root),
                 lambda p, d: workroot._write_manifest(root, d), pretty),
        ]

    def test_bytes_are_the_same_as_before(self):
        for c in self.cases():
            with self.subTest(c.label):
                os.makedirs(os.path.dirname(c.path), exist_ok=True)
                c.write(c.path, DOC)
                self.assertEqual(raw(c.path), c.expected(DOC))
                self.assertEqual(os.listdir(os.path.dirname(c.path)), [os.path.basename(c.path)])

    def test_failed_replace_keeps_the_old_file_and_leaves_no_temp(self):
        for c in self.cases():
            with self.subTest(c.label):
                os.makedirs(os.path.dirname(c.path), exist_ok=True)
                c.write(c.path, DOC)
                with mock.patch("os.replace", side_effect=OSError("디스크 가득")):
                    with self.assertRaises(OSError):
                        c.write(c.path, OTHER)
                self.assertEqual(raw(c.path), c.expected(DOC))
                self.assertEqual(os.listdir(os.path.dirname(c.path)), [os.path.basename(c.path)], "임시 파일이 남지 않음")

    def test_a_file_named_like_the_old_temp_is_left_alone(self):
        """'<파일>.tmp'는 다른 쓰기가 쓰는 중인 임시 파일일 수 있다. 같은 이름에 쓰고 옮기면 그 쓰기를 망가뜨린다."""
        for c in self.cases():
            with self.subTest(c.label):
                os.makedirs(os.path.dirname(c.path), exist_ok=True)
                with open(c.path + ".tmp", "wb") as fh:
                    fh.write(b"someone else is writing")
                c.write(c.path, DOC)
                self.assertEqual(raw(c.path), c.expected(DOC))
                self.assertEqual(raw(c.path + ".tmp"), b"someone else is writing")


class KeyStoreWriteTest(unittest.TestCase):
    """API 키 저장소: 키 평문은 파일에도 임시 파일에도 남지 않는다. 시험 키는 가짜 값이고 출력에 찍지 않는다."""

    SECRET = "sk-test-" + "0" * 24

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-store-callers-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "keys", "ai_keys.json")

    def store(self):
        ks = apikey.KeyStore(self.path)
        ks.add("시험 키", self.SECRET, True)
        return ks

    def leaked(self):
        return [n for n in os.listdir(os.path.dirname(self.path))
                if self.SECRET.encode("ascii") in raw(os.path.join(os.path.dirname(self.path), n))]

    def test_format_is_unchanged_and_the_key_is_not_in_the_file(self):
        self.store()
        data = raw(self.path)
        doc = json.loads(data.decode("utf-8"))
        self.assertEqual(data.decode("utf-8"), json.dumps(doc, ensure_ascii=False, indent=1).replace("\n", os.linesep),
                         "들여쓰기 1, 끝 줄바꿈 없음, 줄끝은 전처럼 운영체제 것")
        self.assertEqual((doc["version"], [k["name"] for k in doc["keys"]]), (1, ["시험 키"]))
        self.assertEqual(self.leaked(), [])
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["ai_keys.json"])
        self.assertEqual(apikey.KeyStore(self.path).entries()[0]["name"], "시험 키")

    def test_failed_write_leaves_no_temp_file_and_keeps_the_old_store(self):
        ks = self.store()
        before = raw(self.path)
        with mock.patch("os.replace", side_effect=OSError("디스크 가득")):
            with self.assertRaises(OSError):
                ks.add("둘째 키", self.SECRET + "1", True)
        self.assertEqual(raw(self.path), before)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["ai_keys.json"])

    def test_leftover_temp_files_are_removed_at_the_next_save_whatever_their_age(self):
        """강제 종료로 남은 임시 파일에는 암호문이 들어 있다. 키 저장소는 앱 하나만 쓰므로 다음 저장 때 바로 지운다."""
        os.makedirs(os.path.dirname(self.path))
        for name in ("ai_keys.json.tmp", ".ai_keys.json.k3x9q2.tmp"):
            with open(os.path.join(os.path.dirname(self.path), name), "wb") as fh:
                fh.write(b"leftover")
        self.store()
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["ai_keys.json"])


class StoreIoEdgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-store-callers-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_bare_file_name_is_written_in_the_current_folder(self):
        here = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, here)
        analysis_run._write("analysis.json", DOC)
        kg_link.write_atomic("links.csv", "a,b\r\n")
        self.assertEqual(sorted(os.listdir(self.tmp)), ["analysis.json", "links.csv"])
        self.assertEqual(raw("analysis.json"), pretty(DOC))

    def test_remove_temps_takes_both_names_and_nothing_else(self):
        from hazop import store_io
        path = os.path.join(self.tmp, "manifest.json")
        for name in ("manifest.json", "manifest.json.tmp", ".manifest.json.ab12.tmp", "other.json.tmp", ".other.json.x.tmp"):
            with open(os.path.join(self.tmp, name), "wb") as fh:
                fh.write(b"x")
        store_io.remove_temps(path, older_than=600)
        self.assertEqual(len(os.listdir(self.tmp)), 5, "방금 만든 것은 나이 조건에 걸리지 않음")
        store_io.remove_temps(path)
        self.assertEqual(sorted(os.listdir(self.tmp)), [".other.json.x.tmp", "manifest.json", "other.json.tmp"])


class WorkrootRenameTest(unittest.TestCase):
    """작업 루트 이름을 바꾼 직후 원래 자리를 적는다. 그 기록을 쓰지 못하면 이름만 바뀐 채 남지 않는다."""

    def test_failed_first_record_puts_the_root_name_back(self):
        tmp = tempfile.mkdtemp(prefix="hazop-store-callers-")
        self.addCleanup(shutil.rmtree, tmp, True)
        old, new = os.path.join(tmp, "old-root"), os.path.join(tmp, "work")
        os.makedirs(old)
        with open(os.path.join(old, "keep.txt"), "w", encoding="utf-8") as fh:
            fh.write("사람이 만든 파일")
        with mock.patch("os.replace", side_effect=OSError("디스크 가득")):
            with self.assertRaises(OSError):
                workroot.apply(new, from_root=old)
        self.assertEqual((os.path.isdir(old), os.path.exists(new)), (True, False), "이름을 되돌려 원래 자리에 그대로")
        self.assertEqual(os.listdir(old), ["keep.txt"])
        workroot.apply(new, from_root=old)
        self.assertEqual(workroot.read_manifest(new)["root_renamed_from"], os.path.abspath(old))


class RegistryTraceTest(unittest.TestCase):
    """등록은 첫 스냅샷을 쓰다 끊긴 흔적(임시 파일만 있는 폴더)을 이어서 등록할 수 있는 상태로 본다.
    옛 이름('1.json.tmp')과 공용 쓰기의 이름('.1.json.<무작위>.tmp') 둘 다 흔적이다."""

    def test_both_temp_names_count_as_an_unfinished_trace(self):
        tmp = tempfile.mkdtemp(prefix="hazop-store-callers-")
        self.addCleanup(shutil.rmtree, tmp, True)
        sha = "a" * 64
        for name in ("1.json.tmp", ".1.json.k3x9q2.tmp"):
            with self.subTest(name):
                root = os.path.join(tmp, name.strip("."))
                folder = os.path.join(root, "registrations", "material-x")
                os.makedirs(folder)
                with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                    json.dump({"sha256": sha}, fh)
                fake = mock.Mock(root=root)
                self.assertTrue(registry._unfinished_trace_only(fake, "material-x", sha))
                self.assertFalse(registry._unfinished_trace_only(fake, "material-x", "b" * 64), "다른 원본의 흔적이면 이어 쓰지 않음")


if __name__ == "__main__":
    unittest.main()
