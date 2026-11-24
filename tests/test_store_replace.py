"""저장 파일 교체가 읽기와 겹칠 때(Windows 공유 위반). 실행: python -m unittest tests.test_store_replace

Windows에서 다른 스레드가 같은 파일을 읽으려고 잠깐 열고 있으면 os.replace가 접근 거부(WinError 5)로 실패한다.
본다: 읽는 스레드가 계속 읽어도 쓰기가 모두 성공한다, AI 분석 실행이 칸마다 저장하는 동안 결과를 읽어도 실행이 끝까지 저장한다,
오래 쥐고 있으면 상한 시간 뒤 지금처럼 실패하되 원본은 그대로이고 임시 파일이 남지 않는다.
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

from hazop import store_io
from hazop.shell import analysis_run
from hazop.study import results as res
from tests.test_shell_results import Base, FakeAi, fake_run_unit

WINDOWS = sys.platform == "win32"


class Reader:
    """멈출 때까지 path를 열고 읽고 닫는다(화면 갱신이 결과 파일을 읽는 것과 같은 꼴)."""

    def __init__(self, read):
        self.read, self.stop, self.count = read, threading.Event(), 0
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        while not self.stop.is_set():
            try:
                self.read()
                self.count += 1
            except Exception:  # noqa: BLE001 - 읽기 실패는 이 시험이 보는 것이 아니다(읽는 스레드가 죽지 않게)
                pass

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(5)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hazop-replace-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "x.json")
        store_io.write_json(self.path, {"n": -1})

    def temps(self):
        return [n for n in os.listdir(self.dir) if n.endswith(".tmp")]

    def test_writes_succeed_while_another_thread_keeps_reading(self):
        errors = []
        with Reader(lambda: store_io.read_bytes(self.path)) as r:
            for i in range(300):
                try:
                    store_io.write_json(self.path, {"n": i, "pad": "x" * 20000})
                except OSError as exc:
                    errors.append(exc)
        self.assertGreater(r.count, 0)
        self.assertEqual(errors, [])
        self.assertEqual(store_io.read_bytes(self.path)[0], store_io.dump_bytes({"n": 299, "pad": "x" * 20000}))
        self.assertEqual(self.temps(), [])

    @unittest.skipUnless(WINDOWS, "공유 위반은 Windows에서만 난다")
    def test_held_open_too_long_fails_and_keeps_the_original(self):
        before = store_io.read_bytes(self.path)[0]
        with mock.patch.object(store_io, "REPLACE_RETRY_SECONDS", 0.3, create=True), open(self.path, "rb"):
            with self.assertRaises(PermissionError):
                store_io.write_json(self.path, {"n": 1})
        self.assertEqual(store_io.read_bytes(self.path)[0], before)
        self.assertEqual(self.temps(), [])

    def test_other_permission_errors_are_not_retried(self):
        calls = []

        def replace(src, dst):
            calls.append(1)
            raise PermissionError(13, "읽기 전용")
        with mock.patch.object(store_io.os, "replace", replace):
            with self.assertRaises(PermissionError):
                store_io.write_json(self.path, {"n": 1})
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.temps(), [])


class AnalysisWhileReadingTest(Base):
    """실제 길: AI 분석 실행이 칸마다 결과 파일을 저장하는 동안 화면이 그 파일을 읽는다."""

    def setUp(self):
        super().setUp()
        self.engine.ai = FakeAi()
        p = mock.patch.object(analysis_run, "contexts", lambda units, ns, pg, intent_of: {u["node_id"]: {} for u in units})
        p.start()
        self.addCleanup(p.stop)

    def test_run_saves_every_call_while_results_are_read(self):
        for _ in range(5):
            with Reader(lambda: res.load_fp(self.ns)) as reader, mock.patch("hazop.study.ai_cells.run_unit", fake_run_unit()):
                r = self.call("results.run", {"scope": "all"})
            self.assertTrue(r["ok"], r)
            self.assertGreater(reader.count, 0)
            ended = [e for e in self.events.items if e.get("name") in ("job.done", "job.failed")][-1]
            self.assertEqual(ended["name"], "job.done", ended["data"])
            doc, _fp = res.load_fp(self.ns)
            self.assertTrue(all(c["state"] == "analyzed" for c in doc["cells"]))


if __name__ == "__main__":
    unittest.main()
