"""저장 공용 규칙(hazop.store_io)과 그것을 쓰는 저장 파일들의 재현 시험. 실행: python -m unittest tests.test_store_io

docs/records/backlog.md '저장·이력 경미 후속(2026-11-09 재판정)'과 백업 폴더 겹침 결함을 하나씩 재현한다.
임시 HAZOP_WORK_ROOT만 쓴다. 옛 저장 파일은 0.1.x가 쓰던 직렬화(들여쓰기 2, 줄끝 LF)로 직접 만들어 읽힌다.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths, store_io  # noqa: E402
from hazop.ie import model as ie_model, store as ie_store  # noqa: E402
from hazop.study import migrate, node_review, nodes as sn, results as res  # noqa: E402
from tests.test_study_nodes import synthetic_graph  # noqa: E402

AT = "2026-11-07T00:00:00Z"

KILLED_WRITER = """
import os, sys
from hazop import store_io
if sys.argv[2] == "replace":
    os.replace = lambda *a: os._exit(9)
else:
    os.fsync = lambda fd: os._exit(9)
store_io.write_json(sys.argv[1], {"v": "new", "pad": "x" * 200000})
"""


def old_bytes(obj, sort_keys):
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n").encode("utf-8")


def raw(path):
    with open(path, "rb") as fh:
        return fh.read()


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class WorkRootCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-store-io-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.g = synthetic_graph()

    def confirmed(self):
        return sn.confirm(sn.propose(self.g, at=AT), self.g, "검토자A", at=AT)

    def results_doc(self):
        return res.empty_results(self.confirmed(), res.load_deviations())


class AtomicWriteTest(WorkRootCase):
    def test_killed_writer_leaves_old_file_whole_and_its_temp_is_swept_later(self):
        for stage in ("fsync", "replace"):
            with self.subTest(stage):
                folder = tempfile.mkdtemp(dir=self.tmp)
                path = os.path.join(folder, "기록.json")
                store_io.write_json(path, {"v": "old"})
                done = subprocess.run([sys.executable, "-c", KILLED_WRITER, path, stage], cwd=REPO_ROOT)
                self.assertEqual(done.returncode, 9, "쓰는 도중 죽음")
                self.assertEqual(json.loads(raw(path)), {"v": "old"}, "옛 파일이 온전함")
                left = [n for n in os.listdir(folder) if n != "기록.json"]
                self.assertEqual(len(left), 1, "죽은 프로세스의 임시 파일")
                store_io.write_json(path, {"v": "next"})
                self.assertIn(left[0], os.listdir(folder), "방금 생긴 임시 파일은 쓰는 중일 수 있어 두고")
                os.utime(os.path.join(folder, left[0]), (0, 0))
                store_io.write_json(path, {"v": "last"})
                self.assertEqual(os.listdir(folder), ["기록.json"], "오래된 것은 다음 저장이 지움")
                self.assertEqual(json.loads(raw(path)), {"v": "last"})

    def test_failed_replace_keeps_old_file_and_leaves_no_temp(self):
        confirmed = self.confirmed()
        review = node_review.empty(None, "graph-T")
        writers = {
            "검토구간": (sn.store_path(None, "graph-T"), lambda: sn.save(sn.reopen(confirmed, at=AT))),
            "분석 결과": (res.store_path(None, "graph-T"), lambda: res.save(dict(self.results_doc(), ai_log=[{}]), None)),
            "AI 구간 검토": (node_review.store_path(None, "graph-T"), lambda: node_review.save(dict(review, next_id=9))),
            "초기사건": (ie_store.store_path("가상 PWR"),
                     lambda: ie_store.save(ie_model.create_group(ie_model.empty("가상 PWR"), "그룹", at=AT)[0],
                                           expect=ie_store.fingerprint(ie_store.store_path("가상 PWR")))),
        }
        sn.save(confirmed)
        res.save(self.results_doc(), None)
        node_review.save(review)
        ie_store.save(ie_model.empty("가상 PWR"), expect=None)
        for label, (path, write) in writers.items():
            with self.subTest(label):
                before, names = raw(path), sorted(os.listdir(os.path.dirname(path)))
                with mock.patch("os.replace", side_effect=OSError("디스크 가득")):
                    with self.assertRaises(OSError):
                        write()
                self.assertEqual(raw(path), before)
                self.assertEqual(sorted(os.listdir(os.path.dirname(path))), names, "임시 파일이 남지 않음")

    def test_conflict_is_checked_against_the_bytes_that_were_read(self):
        path = os.path.join(self.tmp, "a.json")
        self.assertEqual(store_io.read_bytes(path), (None, None))
        fp = store_io.write_json(path, {"n": 1}, expect=None)
        self.assertEqual(store_io.read_bytes(path), (raw(path), fp))
        put(path, b"{}")
        with self.assertRaises(store_io.Conflict):
            store_io.write_json(path, {"n": 2}, expect=fp)
        self.assertEqual(raw(path), b"{}")
        self.assertEqual(os.listdir(self.tmp), ["a.json"])
        self.assertIs(sn.Conflict, store_io.Conflict)
        self.assertIs(ie_store.Conflict, store_io.Conflict)


class LoadTest(WorkRootCase):
    def test_version_migration_on_load_does_not_overwrite_a_change_made_after_reading(self):
        """판 이전은 읽은 파일 자리에 다시 쓴다. 읽은 뒤 바뀐 파일이면 쓰지 않고 읽은 내용만 돌려준다."""
        old = self.confirmed()
        for key in ("graph_member_refs", "member_digest"):
            old.pop(key)
        path = sn.save(old)
        outside = old_bytes(dict(old, drawing_number="바깥에서 고침"), False)
        real = migrate.with_refs

        def refs_then_outside_edit(node_set, graph):
            put(path, outside)
            return real(node_set, graph)
        with mock.patch.object(migrate, "with_refs", side_effect=refs_then_outside_edit):
            loaded = sn.load(self.g)
        self.assertEqual(raw(path), outside, "바깥에서 고친 내용이 그대로")
        self.assertEqual(loaded["nodes"][0]["confirmed"]["by"], "검토자A")

    def test_load_gives_the_fingerprint_of_what_it_read_or_wrote(self):
        self.assertEqual(sn.load_fp(self.g), (None, None))
        path = sn.save(sn.propose(self.g, at=AT))
        self.assertEqual(sn.load_fp(self.g)[1], store_io.fingerprint(path))
        old = self.confirmed()
        old.pop("graph_member_refs")
        sn.save(old)
        doc, fp = sn.load_fp(self.g)
        self.assertIn("graph_member_refs", doc)
        self.assertEqual(fp, store_io.fingerprint(path), "참조를 채워 다시 쓴 파일의 지문")
        _path, saved_fp = sn.save_fp(sn.reopen(doc, at=AT), expect=fp)
        self.assertEqual(saved_fp, store_io.fingerprint(path))

    def test_members_of_a_wrong_type_are_a_shape_error(self):
        for bad in ([{}], [1], [None], [["a"]]):
            with self.subTest(members=bad):
                doc = sn.propose(self.g, at=AT)
                doc["nodes"][0]["members"] = bad
                put(sn.store_path(None, "graph-T"), old_bytes(doc, False))
                with self.assertRaises(ValueError):
                    sn.load(self.g)
        doc = sn.propose(self.g, at=AT)
        doc["nodes"][0]["absorbed"] = [{"from": "P1", "members": [{}], "rule": "R2"}]
        put(sn.store_path(None, "graph-T"), old_bytes(doc, False))
        with self.assertRaises(ValueError):
            sn.load(self.g)


class BackupTest(WorkRootCase):
    def test_backups_in_the_same_second_keep_both_copies(self):
        path = sn.store_path(None, "graph-T")
        makers = {"파일 하나": lambda: store_io.backup_file(path, "시험"),
                  "여러 파일": lambda: os.path.join(store_io.backup([path], "시험"), os.path.relpath(path, self.tmp)),
                  "초기사건": lambda: ie_store.backup("가상 PWR", "시험")}
        for label, make in makers.items():
            with self.subTest(label), mock.patch("hazop.store_io.now_utc", return_value=AT), \
                    mock.patch("hazop.ie.store.now_utc", return_value=AT), \
                    mock.patch.object(ie_store, "store_path", return_value=path):
                put(path, b"first")
                one = make()
                put(path, b"second")
                two = make()
                self.assertNotEqual(one, two)
                self.assertEqual((raw(one), raw(two)), (b"first", b"second"), "앞 백업을 덮어쓰지 않음")
                shutil.rmtree(paths.folder("backup"))

    def test_different_files_in_the_same_second_share_one_folder(self):
        a, b = put(os.path.join(self.tmp, "a.json"), b"a"), put(os.path.join(self.tmp, "b.json"), b"b")
        one, two = store_io.backup_file(a, "시험", at=AT), store_io.backup_file(b, "시험", at=AT)
        self.assertEqual(os.path.dirname(one), os.path.dirname(two))
        self.assertEqual((raw(one), raw(two)), (b"a", b"b"))


class NodeIdTest(WorkRootCase):
    def split_off(self, node_set, node_id="S1"):
        members = next(n for n in node_set["nodes"] if n["node_id"] == node_id)["members"]
        out = sn.split(node_set, node_id, members[:1], at=AT)
        return out, out["history"][-1]["detail"]["new_node_id"]

    def test_a_merged_away_number_is_not_issued_again(self):
        s = sn.propose(self.g, at=AT)
        top = len(s["nodes"])
        s, first = self.split_off(s)
        self.assertEqual(first, "S%d" % (top + 1))
        s = sn.merge(s, ["S1", first], at=AT)
        s, second = self.split_off(s)
        self.assertEqual(second, "S%d" % (top + 2), "지운 번호를 다시 쓰지 않음")
        sn.save(s)
        _again, third = self.split_off(sn.load(self.g))
        self.assertEqual(third, "S%d" % (top + 3), "저장했다 읽어도 이어짐")

    def test_numbers_continue_from_the_history_of_an_old_file(self):
        """옛 파일에는 발급 기록이 따로 없다. 이력에 남은 분할·병합에서 지운 번호를 찾는다."""
        old = sn.propose(self.g, at=AT)
        for n in old["nodes"]:
            n.pop("screen"), n.pop("absorbed", None), n.pop("parts", None)
        old["history"] += [{"at": AT, "op": "split", "detail": {"node_id": "S1", "new_node_id": "S41", "members": ["n-E1"]}},
                           {"at": AT, "op": "merge", "detail": {"node_ids": ["S1", "S41"], "into": "S1"}}]
        put(sn.store_path(None, "graph-T"), old_bytes(old, False))
        _out, new = self.split_off(sn.load(self.g))
        self.assertEqual(new, "S42")


class OldFilesTest(WorkRootCase):
    """0.1.x가 쓴 파일을 지금 코드로 읽고 다시 저장해도 내용이 그대로다."""

    def test_study_nodes_round_trip_byte_for_byte(self):
        old = sn.propose(self.g, at=AT)
        for n in old["nodes"]:  # screen 필드가 생기기 전 제안기(0.1.0) 저장본
            n.pop("screen"), n.pop("absorbed", None), n.pop("parts", None)
        old["proposer"] = {"name": "hazop.study.nodes", "version": "0.1.0"}
        path = put(sn.store_path(None, "graph-T"), old_bytes(old, False))
        loaded, fp = sn.load_fp(self.g)
        self.assertEqual(loaded, old)
        sn.save(loaded, expect=fp)
        self.assertEqual(raw(path), old_bytes(old, False))

    def test_confirmed_set_without_refs_keeps_its_confirmation_and_original_is_backed_up(self):
        old = self.confirmed()
        for key in ("graph_member_refs", "member_digest"):
            old.pop(key)
        path = put(sn.store_path(None, "graph-T"), old_bytes(old, False))
        loaded = sn.load(self.g)
        for key in ("nodes", "history", "set_rev", "batches"):
            self.assertEqual(loaded[key], old[key], key)
        self.assertEqual(json.loads(raw(path)), loaded)
        copies = [os.path.join(d, f) for d, _s, fs in os.walk(paths.folder("backup")) for f in fs]
        self.assertEqual([raw(c) for c in copies], [old_bytes(old, False)])

    def test_results_round_trip_byte_for_byte(self):
        doc = self.results_doc()
        cell = doc["cells"][0]
        cell["entries"].append({"entry_id": "e1", "status": "approved", "text": "사람이 승인한 원인",
                                "history": [{"at": AT, "op": "status", "from": "proposed", "to": "approved"}]})
        path = put(res.store_path(None, "graph-T"), old_bytes(doc, True))
        loaded = res.read(path)
        self.assertEqual(loaded, doc)
        res.save(loaded, None)
        self.assertEqual(raw(path), old_bytes(doc, True))

    def test_initiating_events_round_trip_byte_for_byte(self):
        doc, _ = ie_model.create_group(ie_model.empty("가상 PWR"), "주급수 상실", at=AT)
        path = put(ie_store.store_path("가상 PWR"), old_bytes(doc, True))
        loaded, fp = ie_store.load("가상 PWR")
        self.assertEqual(loaded, doc)
        self.assertEqual(ie_store.save(loaded, expect=fp), fp)
        self.assertEqual(raw(path), old_bytes(doc, True))

    def test_review_proposals_round_trip(self):
        doc = dict(node_review.empty(None, "graph-T"), next_id=7)
        path = put(node_review.store_path(None, "graph-T"), json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8"))
        loaded = node_review.load(None, "graph-T")
        node_review.save(loaded)
        self.assertEqual(json.loads(raw(path)), doc)
        self.assertEqual(list(json.loads(raw(path))), list(doc), "키 순서도 그대로")


class Stored01FilesTest(WorkRootCase):
    """tests/fixtures/store-0.1/: 0.1.x 코드(d86bd89)의 저장 함수가 쓴 파일 그대로(source.json).
    지금 코드로 읽고 다시 저장해도 사람이 고친 내용이 그대로다."""

    def old(self, name):
        return raw(os.path.join(REPO_ROOT, "tests", "fixtures", "store-0.1", name))

    def test_study_nodes(self):
        """0.1 집합은 처음 읽을 때 0.2로 바꾸고 원본은 <이름>.v0.1.bak.json으로 남긴다(검토구간 규격 §2.5)."""
        from hazop.study import convert
        data = self.old("study-nodes.json")
        path = put(sn.store_path(None, "graph-T"), data)
        doc, fp = sn.load_fp(self.g)
        self.assertEqual(raw(convert.backup_path(path)), data, "원본 그대로 보관")
        old = json.loads(data)
        self.assertEqual({(n["state"], n["confirmed"]["by"]) for n in doc["nodes"]}, {("confirmed", "검토자A")})
        self.assertEqual(doc["nodes"][0]["name"], "사람이 정한 이름")
        self.assertEqual(doc["history"][:len(old["history"])], old["history"])
        sn.save(doc, expect=fp)
        self.assertEqual(sn.load(self.g), doc, "닫고 다시 열어도 같음")
        gone = next(h["detail"]["new_node_id"] for h in doc["history"] if h["op"] == "split")
        self.assertNotIn(gone, [n["node_id"] for n in doc["nodes"]])
        big = max(doc["nodes"], key=lambda n: len(n["members"]))
        again = sn.split(sn.reopen(doc, at=AT), big["node_id"], big["members"][:1], at=AT)
        self.assertEqual(again["history"][-1]["detail"]["new_node_id"], "S%d" % (int(gone[1:]) + 1), "병합으로 지운 번호 다음")

    def test_analysis_results(self):
        """0.1 결과는 집합과 함께 0.2로 바뀐다(칸 열쇠 item_id, node_rev). 승인 항목·칸 상태는 그대로다."""
        data = self.old("analysis-results.json")
        old = json.loads(data)
        put(sn.store_path(None, "graph-T"), self.old("study-nodes.json"))
        path = put(res.store_path(None, "graph-T"), data)
        with mock.patch.object(res, "load_deviations", lambda path=None: old["deviations"]):
            doc, fp = res.load_fp(sn.load(self.g))
            res.save_fp(doc, None, expect=fp)
        self.assertEqual(doc["schema_version"], "0.2")
        self.assertEqual(doc["cells"][0]["entries"], old["cells"][0]["entries"])
        self.assertEqual([(c["node_id"], c["deviation_id"], c["state"]) for c in doc["cells"]],
                         [(c["node_id"], c["deviation_id"], c["state"]) for c in old["cells"]])
        self.assertEqual(json.loads(raw(path))["cells"][0]["entries"][0]["status"], "approved")

    def test_initiating_events(self):
        data = self.old("initiating-events.json")
        path = put(ie_store.store_path("가상 PWR"), data)
        doc, fp = ie_store.load("가상 PWR")
        self.assertEqual(doc, json.loads(data))
        ie_store.save(doc, expect=fp)
        self.assertEqual(raw(path), data)

    def test_drawing_edits(self):
        from hazop.extract import corrections
        data = self.old("drawing-edits.json")
        path = put(corrections.store_path("T-1"), data)
        old, fp = corrections.load_fp("T-1")
        self.assertEqual(corrections.issued_op_ids("T-1"), {"c-0001", "c-0002"})
        corrections.save("T-1", old["ops"], "검토자B", expect=fp)
        new = json.loads(raw(path))
        self.assertEqual((new["ops"], new["log"][:2], new["drawing_number"]), (old["ops"], old["log"], "T-1"))
        self.assertEqual((new["log"][2]["added"], new["log"][2]["removed"]), ([], []))

    def test_node_review(self):
        data = self.old("node-review.json")
        path = put(node_review.store_path(None, "graph-T"), data)
        doc, fp = node_review.load_fp(None, "graph-T")
        node_review.save_fp(doc, fp)
        self.assertEqual(raw(path).rstrip(b"\n"), data, "끝의 줄바꿈만 더해짐")


class HistoryRowTest(unittest.TestCase):
    def test_rows_keep_the_shape_each_file_already_uses(self):
        self.assertEqual(store_io.history_row("rename", {"detail": {"node_id": "S1"}}, AT),
                         {"at": AT, "op": "rename", "detail": {"node_id": "S1"}})
        self.assertEqual(list(store_io.history_row("status", {"from": "proposed", "to": "approved"}, AT)),
                         ["at", "op", "from", "to"])
        row = store_io.history_row("edit")
        self.assertRegex(row["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_next_id_counts_only_ids_of_its_own_shape(self):
        self.assertEqual(store_io.next_id("S%d", []), "S1")
        self.assertEqual(store_io.next_id("S%d", ["S2", "S10", "Sx", "R0004", None]), "S11")
        self.assertEqual(store_io.next_id("c-%04d", ["c-0002", "c-0011", "manual-c-0099"]), "c-0012")


if __name__ == "__main__":
    unittest.main()
