"""저장 경로별 충돌·번호·옛 자리 재현 시험(단위 D 교차검증 지적 1~8). 실행: python -m unittest tests.test_store_conflicts

화면을 거치는 재현은 tests/test_study_screens.py와 tests/test_viewer_edit.py에 있다. 임시 HAZOP_WORK_ROOT만 쓴다.
"""

import json
import os
import stat
import sys
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import store_io  # noqa: E402
from hazop.extract import corrections  # noqa: E402
from hazop.graph.project import LEGACY_PROJECT_DIR  # noqa: E402
from hazop.study import node_review, nodes as sn, results as res  # noqa: E402
from tests.test_store_io import AT, WorkRootCase, old_bytes, put, raw  # noqa: E402


def op(tag, op_id="c-0001"):
    return {"op_id": op_id, "op": "add_node", "target": None, "base": None, "refs": {},
            "value": {"category": "equipment", "kind": "pump", "tag": tag, "bbox": [0, 0, 10, 10]},
            "by": "검토자", "at": AT}


class LegacyPlaceTest(WorkRootCase):
    """프로젝트 없는 옛 자리(no-project)에만 있는 저장본을 읽어 새 자리에 처음 저장한다."""

    def test_study_nodes_read_from_the_old_place_save_to_the_new_place(self):
        old = sn.propose(self.g, at=AT)
        legacy = put(os.path.join(sn.store_dir(), LEGACY_PROJECT_DIR, "graph-T.json"), old_bytes(old, False))
        doc, fp = sn.load_fp(self.g)
        self.assertEqual(doc, old)
        path, _fp = sn.save_fp(sn.rename(doc, "S1", "새 이름", at=AT), expect=fp)
        self.assertEqual(path, sn.store_path(None, "graph-T"))
        self.assertEqual(sn.load(self.g)["nodes"][0]["name"], "새 이름")
        self.assertEqual(raw(legacy), old_bytes(old, False), "옛 자리 파일은 그대로")

    def test_results_read_from_the_old_place_save_to_the_new_place(self):
        ns = self.confirmed()
        old = self.results_doc()
        legacy = put(res.store_path(LEGACY_PROJECT_DIR, "graph-T"), old_bytes(old, True))
        doc, fp = res.load_fp(ns)
        self.assertEqual(doc, old)
        path, _fp = res.save_fp(dict(doc, ai_log=[{"at": AT}]), None, expect=fp)
        self.assertEqual(path, res.store_path(None, "graph-T"))
        self.assertEqual(raw(legacy), old_bytes(old, True))


class ConflictPerFileTest(WorkRootCase):
    """A를 읽음 → 파일이 밖에서 B로 바뀜 → A를 고쳐 저장: B를 덮어쓰지 않는다."""

    def test_results(self):
        ns = self.confirmed()
        path = res.save(self.results_doc(), None)
        doc, fp = res.load_fp(ns)
        outside = old_bytes(dict(doc, ai_log=[{"at": AT, "by": "다른 프로그램"}]), True)
        put(path, outside)
        with self.assertRaises(store_io.Conflict):
            res.save_fp(dict(doc, ai_log=[{"at": AT}]), None, expect=fp)
        self.assertEqual(raw(path), outside)

    def test_review_proposals(self):
        path = node_review.save(node_review.empty(None, "graph-T"))
        doc, fp = node_review.load_fp(None, "graph-T")
        outside = old_bytes(dict(doc, next_id=40), False)
        put(path, outside)
        with self.assertRaises(store_io.Conflict):
            node_review.save_fp(dict(doc, next_id=2), expect=fp)
        self.assertEqual(raw(path), outside)
        self.assertEqual(node_review.load_fp(None, "graph-X"), (node_review.empty(None, "graph-X"), None))

    def test_drawing_corrections(self):
        self.assertEqual(corrections.load_fp("X"), (None, None))
        path = corrections.save("X", [op("P-1")], "검토자")
        doc, fp = corrections.load_fp("X")
        outside = old_bytes(dict(doc, ops=[op("P-1"), op("P-2", "c-0002")]), True)
        put(path, outside)
        with self.assertRaises(store_io.Conflict):
            corrections.save("X", doc["ops"] + [op("P-3", "c-0002")], "검토자", expect=fp)
        self.assertEqual(raw(path), outside)
        _path, fp2 = corrections.save_fp("X", [op("P-1"), op("P-2", "c-0002")], "검토자", expect=store_io.fingerprint(path))
        self.assertEqual(fp2, store_io.fingerprint(path))


class OpIdTest(WorkRootCase):
    def test_an_id_in_use_cannot_be_given_to_another_op(self):
        path = corrections.save("X", [op("P-1")], "검토자")
        before = raw(path)
        with self.assertRaises(ValueError):
            corrections.save("X", [op("P-2")], "스크립트")
        with self.assertRaises(ValueError):
            corrections.save("X", [op("P-1"), op("P-2")], "스크립트")
        self.assertEqual(raw(path), before, "c-0001이 가리키던 수정이 사라지지 않음")
        corrections.save("X", [op("P-1")], "검토자")


class IssuedAfterUndoTest(WorkRootCase):
    def test_undo_does_not_give_the_number_back(self):
        s = sn.propose(self.g, at=AT)
        members = s["nodes"][0]["members"]
        after = sn.split(s, "S1", members[:1], at=AT)
        first = after["history"][-1]["detail"]["new_node_id"]
        undone = sn.keep_issued(s, after)
        self.assertEqual({k: v for k, v in undone.items() if k != "issued_upto"}, s, "되돌린 내용은 그대로")
        again = sn.split(undone, "S1", members[1:2], at=AT)
        self.assertNotEqual(again["history"][-1]["detail"]["new_node_id"], first)
        path = sn.save(again)
        self.assertEqual(sn.load(self.g), json.loads(raw(path)))
        self.assertIs(sn.keep_issued(s, s), s, "새로 낸 번호가 없으면 아무것도 적지 않음")

    def test_issued_upto_of_a_wrong_type_is_a_shape_error(self):
        doc = dict(sn.propose(self.g, at=AT), issued_upto="7")
        put(sn.store_path(None, "graph-T"), old_bytes(doc, False))
        with self.assertRaises(ValueError):
            sn.load(self.g)


class EmptyNodeTest(WorkRootCase):
    """구성요소를 다 빼면 구간을 없앤다. 이미 빈 구간이 든 집합도 읽고 표기할 수 있다."""

    def test_removing_the_last_member_removes_the_node(self):
        from hazop.study import span
        s = sn.propose(self.g, at=AT)
        node = s["nodes"][1]
        out = s
        for m in node["members"]:
            out = sn.remove_member(out, node["node_id"], m, at=AT)
        self.assertNotIn(node["node_id"], [n["node_id"] for n in out["nodes"]])
        self.assertEqual(out["history"][-1]["detail"], {"node_id": node["node_id"], "entity_id": node["members"][-1],
                                                        "node_removed": True,
                                                        "screen": {"status": "keep", "by": "human", "reason": None}})
        self.assertEqual(len(s["nodes"][1]["members"]), len(node["members"]), "입력은 그대로")
        top = max(int(n["node_id"][1:]) for n in s["nodes"])
        again = sn.split(out, out["nodes"][0]["node_id"], out["nodes"][0]["members"][:1], at=AT)
        self.assertEqual(again["history"][-1]["detail"]["new_node_id"], "S%d" % (top + 1))
        span.annotate(out, self.g) if self.g.get("sheets") else None

    def test_a_human_screening_decision_is_kept_in_the_history_when_its_node_goes(self):
        s = sn.propose(self.g, at=AT)
        node = s["nodes"][1]
        out = sn.screen_override(s, node["node_id"], "excluded", reason="사람이 적은 이유", at=AT)
        for m in node["members"]:
            out = sn.remove_member(out, node["node_id"], m, at=AT)
        self.assertEqual(out["history"][-1]["detail"]["screen"],
                         {"status": "excluded", "by": "human", "reason": "사람이 적은 이유"})
        hollow = sn.screen_override(s, node["node_id"], "excluded", reason="사람이 적은 이유", at=AT)
        next(n for n in hollow["nodes"] if n["node_id"] == node["node_id"])["members"] = []
        self.assertEqual(sn.remove_empty(hollow, node["node_id"], at=AT)["history"][-1]["detail"],
                         {"node_id": node["node_id"], "screen": {"status": "excluded", "by": "human", "reason": "사람이 적은 이유"}})

    def test_a_set_that_already_has_an_empty_node_loads_and_can_drop_it(self):
        s = sn.propose(self.g, at=AT)
        empty = s["nodes"][1]["node_id"]
        s["nodes"][1]["members"] = []
        sn.save(s)
        loaded = sn.load(self.g)
        self.assertEqual(loaded, s, "빈 구간 때문에 파일 전체를 못 읽지 않음")
        dropped = sn.remove_empty(loaded, empty, at=AT)
        self.assertNotIn(empty, [n["node_id"] for n in dropped["nodes"]])
        self.assertEqual((dropped["history"][-1]["op"], dropped["history"][-1]["detail"]["node_id"]), ("remove_empty", empty))
        with self.assertRaises(ValueError):
            sn.remove_empty(loaded, loaded["nodes"][0]["node_id"])
        with self.assertRaises(ValueError):
            sn.confirm(loaded, self.g, "검토자A")


class WriteFailureTest(WorkRootCase):
    def target(self):
        path = os.path.join(self.tmp, "기록.json")
        store_io.write_json(path, {"v": "old"})
        return path

    def test_unserializable_document_writes_nothing(self):
        path = self.target()
        with self.assertRaises(TypeError):
            store_io.write_json(path, {"v": object()})
        self.assertEqual((json.loads(raw(path)), os.listdir(self.tmp)), ({"v": "old"}, ["기록.json"]))

    def test_fsync_failure_removes_the_temp_file(self):
        path = self.target()
        with mock.patch("os.fsync", side_effect=OSError("장치 오류")):
            with self.assertRaises(OSError):
                store_io.write_json(path, {"v": "new"})
        self.assertEqual((json.loads(raw(path)), os.listdir(self.tmp)), ({"v": "old"}, ["기록.json"]))

    def test_read_only_target_is_left_alone(self):
        path = self.target()
        os.chmod(path, stat.S_IREAD)
        self.addCleanup(os.chmod, path, stat.S_IWRITE | stat.S_IREAD)
        with self.assertRaises(OSError):
            store_io.write_json(path, {"v": "new"})
        self.assertEqual((json.loads(raw(path)), os.listdir(self.tmp)), ({"v": "old"}, ["기록.json"]))

    def test_a_temp_file_that_cannot_be_removed_is_logged(self):
        path = self.target()
        with mock.patch("os.replace", side_effect=OSError("디스크 가득")), \
                mock.patch("os.remove", side_effect=PermissionError(13, "잠김")):
            with self.assertLogs("hazop.store_io", level="WARNING") as logs:
                with self.assertRaises(OSError):
                    store_io.write_json(path, {"v": "new"})
        self.assertIn("임시 파일", logs.output[0])

    def test_migration_reports_sharing_a_backup_folder_do_not_overwrite_each_other(self):
        from hazop.app import project_ctx
        folder = os.path.join(self.tmp, "reports")
        project_ctx._write_report(folder, {"project": "A"})
        project_ctx._write_report(folder, {"project": "B"})
        docs = [json.loads(raw(os.path.join(folder, n))) for n in sorted(os.listdir(folder))]
        self.assertEqual(docs, [{"project": "B"}, {"project": "A"}])

    def test_archive_names_in_the_same_second_do_not_collide(self):
        pattern = os.path.join(self.tmp, "결과.20261107T000000Z%s.bak.json")
        first = put(store_io.unused_name(pattern), b"1")
        second = store_io.unused_name(pattern)
        self.assertEqual((os.path.basename(first), os.path.basename(second)),
                         ("결과.20261107T000000Z.bak.json", "결과.20261107T000000Z-2.bak.json"))

    def test_backup_retries_when_another_writer_takes_the_name_first(self):
        src = put(os.path.join(self.tmp, "a.json"), b"mine")
        real = store_io._copy_new
        calls = []

        def someone_first(a, b):
            calls.append(b)
            if len(calls) == 1:
                put(b, b"theirs")
            return real(a, b)
        with mock.patch.object(store_io, "_copy_new", side_effect=someone_first):
            mine = store_io.backup_file(src, "시험", at=AT)
        self.assertEqual((raw(calls[0]), raw(mine)), (b"theirs", b"mine"))
        self.assertNotEqual(calls[0], mine)


if __name__ == "__main__":
    import unittest
    unittest.main()
