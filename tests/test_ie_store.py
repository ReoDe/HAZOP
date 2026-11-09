"""⑥ 초기사건 저장 파일(hazop.ie.store): 지문 비교 저장, 원자적 교체, utf-8-sig 읽기, 읽지 못한 파일의 백업 뒤 교체.
임시 작업 루트만 쓴다. 실행: python -m unittest tests.test_ie_store
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop import paths  # noqa: E402
from hazop.ie import model, store  # noqa: E402

AT = "2026-11-09T01:00:00Z"


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-ie-store-")
        self._env = os.environ.get("HAZOP_WORK_ROOT")
        os.environ["HAZOP_WORK_ROOT"] = self.tmp
        self.path = store.store_path("가상 PWR")

    def tearDown(self):
        if self._env is None:
            os.environ.pop("HAZOP_WORK_ROOT", None)
        else:
            os.environ["HAZOP_WORK_ROOT"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def doc(self):
        d = model.empty("가상 PWR")
        d, _ = model.create_group(d, "주급수 상실", at=AT)
        return d

    def write_raw(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "wb") as fh:
            fh.write(data)

    def test_path_is_under_data_folder(self):
        self.assertEqual(self.path, paths.work_path("데이터", "초기사건", "가상_PWR.json"))

    def test_missing_file_reads_empty_and_round_trips(self):
        doc, fp = store.load("가상 PWR")
        self.assertEqual((doc, fp), (model.empty("가상 PWR"), None))
        fp = store.save(self.doc(), expect=None)
        self.assertEqual(fp, store.fingerprint(self.path))
        self.assertEqual(store.load("가상 PWR"), (self.doc(), fp))
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.path))], ["가상_PWR.json"], "임시 파일이 남지 않음")

    def test_conflict_when_file_changed_since_read(self):
        fp = store.save(self.doc(), expect=None)
        other, _ = model.create_group(self.doc(), "다른 사람이 만든 그룹", at=AT)
        store.save(other, expect=fp)
        with self.assertRaises(store.Conflict):
            store.save(self.doc(), expect=fp)
        with self.assertRaises(store.Conflict):
            store.save(self.doc(), expect=None)  # 없던 파일로 읽었는데 그사이 생김
        self.assertEqual(store.load("가상 PWR")[0], other)

    def test_reads_utf8_with_bom(self):
        self.write_raw(b"\xef\xbb\xbf" + json.dumps(self.doc(), ensure_ascii=False).encode("utf-8"))
        doc, fp = store.load("가상 PWR")
        self.assertEqual(doc, self.doc())
        self.assertEqual(fp, store.fingerprint(self.path))

    def test_unreadable_files_are_not_repaired(self):
        for raw in (b"{not json", json.dumps({"kind": "other"}).encode(),
                    json.dumps(dict(self.doc(), counters={"IEC": 0})).encode()):
            self.write_raw(raw)
            with self.assertRaises(store.Unreadable) as cm:
                store.load("가상 PWR")
            self.assertTrue(cm.exception.problems)
            with open(self.path, "rb") as fh:
                self.assertEqual(fh.read(), raw)

    def test_save_refuses_a_malformed_doc(self):
        bad = self.doc()
        bad["candidates"]["IEC-001"] = {"key": "g/e", "group_id": "IEG-99", "placed_by": "human"}
        with self.assertRaises(ValueError):
            store.save(bad, expect=None)
        self.assertFalse(os.path.exists(self.path))

    def test_failed_write_keeps_old_file_and_cleans_temp(self):
        fp = store.save(self.doc(), expect=None)
        with mock.patch("hazop.ie.store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.save(model.empty("가상 PWR"), expect=fp)
        self.assertEqual(store.load("가상 PWR")[0], self.doc())
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["가상_PWR.json"])

    def test_replace_unreadable_backs_up_original_bytes_first(self):
        self.write_raw(b"{broken")
        doc, fp, saved = store.replace_unreadable("가상 PWR")
        with open(saved, "rb") as fh:
            self.assertEqual(fh.read(), b"{broken")
        rel = os.path.relpath(saved, paths.work_path("데이터", "백업"))
        self.assertTrue(rel.split(os.sep)[0].endswith("-초기사건읽기실패"), rel)
        self.assertTrue(rel.endswith(os.path.join("데이터", "초기사건", "가상_PWR.json")), rel)
        self.assertEqual(store.load("가상 PWR"), (doc, fp))

    def test_change_after_backup_is_not_overwritten(self):
        self.write_raw(b"{broken")
        real = store.backup

        def backup_then_someone_writes(project_id):
            saved = real(project_id)
            self.write_raw(b"{fixed by hand")
            return saved
        with mock.patch("hazop.ie.store.backup", side_effect=backup_then_someone_writes):
            with self.assertRaises(store.Conflict):
                store.replace_unreadable("가상 PWR")
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), b"{fixed by hand")

    def test_backup_never_overwrites_an_earlier_backup(self):
        with mock.patch("hazop.ie.store.now_utc", return_value=AT):
            self.write_raw(b"{first")
            one = store.backup("가상 PWR")
            self.write_raw(b"{second")
            two = store.backup("가상 PWR")
        self.assertNotEqual(one, two)
        for path, data in ((one, b"{first"), (two, b"{second")):
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), data)

    def test_replacing_an_unreadable_file_never_reissues_its_ids(self):
        self.write_raw('{"candidates": {"IEC-007": {"key": "g/E1", "group_id": "IEG-03"}}, "headings": {"H-12": {}},'
                       ' "end_states": {"ES-02"  "basic_events": {"BE-015": 그'.encode("utf-8")[:-1])
        doc, _, _ = store.replace_unreadable("가상 PWR")
        self.assertEqual(doc["counters"], {"IEC": 7, "IEG": 3, "H": 12, "ES": 2, "BE": 15})
        self.assertEqual(store.load("가상 PWR")[0], doc)
        doc = model.sync(doc, {"graph_id": "g", "cells": [{"node_id": "S1", "deviation_id": "D01", "entries": [
            {"entry_id": "E1", "status": "approved"}]}]}, at=AT)
        doc, gid = model.create_group(doc, "주급수 상실", at=AT)
        self.assertEqual((list(doc["candidates"]), gid), (["IEC-008"], "IEG-04"))

    def test_no_overwrite_when_backup_fails(self):
        self.write_raw(b"{broken")
        with mock.patch("hazop.ie.store.shutil.copy2", side_effect=OSError("backup denied")):
            with self.assertRaises(OSError):
                store.replace_unreadable("가상 PWR")
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), b"{broken")


if __name__ == "__main__":
    unittest.main()
