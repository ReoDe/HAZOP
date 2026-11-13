"""새 웹 화면 ⑥ 초기사건 편집(A10, hazop/shell/api_ie.py). 실행: python -m unittest tests.test_shell_ie_edit

이전 화면 ⑥(hazop/app/screens/initiating.py)의 편집과 그 대조를 새 화면 명령으로 옮긴 것을 본다: 편집마다 저장·다시 읽기,
낡은 판(⑥ 지문·⑤ 지문·항목 지문) 거절, 지우기와 확정 그룹 변경의 되묻기, 인계 묶음 내보내기 반영(JSON 덮어쓰기 확인 포함),
겹친 구간의 같은 원인 후보가 한 후보로 묶이고 두 구간이 근거로 남는지. 임시 작업 루트만 쓴다.
"""

import copy
import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hazop.ie import model  # noqa: E402
from hazop.ie import store as ie_store  # noqa: E402
from hazop.shell import api, api_ie  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as res  # noqa: E402
from tests.test_shell_ie import Base  # noqa: E402


class EditBase(Base):
    def seen_all(self):
        """화면이 지금 보는 모든 항목 지문(요약 + 그룹 상세)."""
        s = self.read("ie")
        out = {}
        for c in s["unassigned"]:
            out["member:" + c["candidate_id"]] = c["fp"]
        for r in s["completeness"]:
            if r.get("code"):
                out["coverage:" + r["code"]] = r["fp"]
        for g in s["groups"]:
            out["group:" + g["group_id"]] = g["fp"]
            d = self.read("ie", "group", g["group_id"])
            for m in d["members"]:
                out["member:" + m["candidate_id"]] = m["fp"]
            for kind, key, rows in (("heading", "heading_id", d["headings"]), ("end_state", "end_state_id", d["end_states"]),
                                    ("basic_event", "be_id", d["basic_events"])):
                for x in rows:
                    out[kind + ":" + x[key]] = x["fp"]
        return out

    def args(self, **a):
        s = self.read("ie")
        return dict({"ver": s["ver"], "rver": s["rver"], "seen": self.seen_all()}, **a)

    def do(self, cmd_name, **a):
        return self.call(cmd_name, self.args(**a))

    def ok(self, cmd_name, **a):
        r = self.do(cmd_name, **a)
        self.assertTrue(r["ok"], r)
        self.assertNotIn("ask", r["data"], r)
        return r["data"]

    def ask(self, cmd_name, **a):
        """되묻기까지: (카드가 보인 때의 인자, 되물은 내용). 저장하지 않았는지는 부르는 쪽이 본다."""
        args = self.args(**a)
        r = self.call(cmd_name, args)
        self.assertTrue(r["ok"] and r["data"].get("ask"), r)
        return args, r["data"]["ask"]

    def go_on(self, cmd_name, args, ask):
        """카드의 '계속': 카드가 보인 때의 인자 그대로 confirmed와 카드에 보인 그룹 목록을 붙인다(ie_state.confirmAsk)."""
        return self.call(cmd_name, dict(args, confirmed=True, confirm_groups=ask["groups"]))

    def code(self, r):
        return (r["ok"], (r.get("error") or {}).get("code"))

    def iec(self, eid):
        """⑤ 항목 entry_id의 후보 ID(묶이지 않은 후보 또는 그룹 소속)."""
        s = self.read("ie")
        found = [c["candidate_id"] for c in s["unassigned"] if c["entry_id"] == eid]
        for g in s["groups"]:
            found += [m["candidate_id"] for m in self.read("ie", "group", g["group_id"])["members"] if m["entry_id"] == eid]
        self.assertEqual(len(found), 1, (eid, found))
        return found[0]

    def file_bytes(self):
        path = ie_store.store_path(self.project)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as fh:
            return fh.read()

    def reread(self):
        """새 엔진(새 창)으로 다시 읽는다 - 저장한 것만 보인다."""
        e = api.Engine(settings_path=os.path.join(self.tmp, "settings2.json"), emit=lambda ev: None)
        e.settings.update(project_id=self.project, reviewer_name="검토자B")
        import json as _j
        r = api.ReadApi(e).read(["ie"], {})
        return _j.loads(r.body.decode("utf-8"))

    def make_group(self, name, *eids):
        return self.ok("ie.create_group", name=name, iecs=[self.iec(e) for e in eids])["group_id"]


class GroupEditTest(EditBase):
    def test_create_move_unassign_and_accept_are_saved_and_reread(self):
        c1, c4 = self.iec("c1"), self.iec("c4")
        gid = self.make_group("주급수 상실", "c1")
        again = self.reread()
        self.assertEqual([(g["group_id"], g["name"], g["member_count"]) for g in again["groups"]], [(gid, "주급수 상실", 1)])
        self.ok("ie.move", iecs=[c4], to=gid)
        self.assertEqual(self.reread()["groups"][0]["member_count"], 2)
        self.ok("ie.move", iecs=[c4], to="")
        self.assertIn(c4, [c["candidate_id"] for c in self.reread()["unassigned"]])
        self.assertEqual(ie_store.load(self.project)[0]["candidates"][c1]["placed_by"], "human")
        self.ok("ie.accept_members", iecs=[c1])
        self.assertTrue([e for e in self.events if e.get("topic") == "ie"])

    def test_edit_group_fields_are_saved_and_bad_fields_write_nothing(self):
        gid = self.make_group("주급수 상실", "c1")
        self.ok("ie.edit_group", group_id=gid, fields={"name": "급수 상실", "definition": "주급수가 끊김", "support_ie": "no",
                                                         "categories": ["LOMFW"]})
        d = self.read("ie", "group", gid)
        self.assertEqual((d["editable"]["name"], d["editable"]["definition"], d["editable"]["support_ie"], d["editable"]["categories"]),
                         ("급수 상실", "주급수가 끊김", "no", ["LOMFW"]))
        before = self.file_bytes()
        self.assertEqual(self.code(self.do("ie.edit_group", group_id=gid, fields={"support_ie": "maybe"})), (False, "failed"))
        self.assertEqual(self.code(self.do("ie.edit_group", group_id=gid, fields={"status": "confirmed"})), (False, "bad_args"))
        self.assertEqual(self.file_bytes(), before, "거절한 편집은 아무것도 쓰지 않는다")

    def test_split_makes_two_new_draft_groups_and_keeps_the_old_id_as_split(self):
        c4 = self.iec("c4")
        gid = self.make_group("묶음", "c1", "c4")
        new = self.ok("ie.split", group_id=gid, moved=[c4])["groups"]
        self.assertEqual(len(new), 2)
        s = self.reread()
        self.assertEqual(sorted(g["group_id"] for g in s["groups"]), sorted(new))
        self.assertEqual(ie_store.load(self.project)[0]["groups"][gid]["status"], "split")
        self.assertEqual(self.code(self.do("ie.split", group_id=new[0], moved=[])), (False, "failed"), "전부·없음으로는 나누지 않는다")

    def test_delete_asks_first_and_then_unassigns_members(self):
        c1 = self.iec("c1")
        gid = self.make_group("지울 그룹", "c1")
        before = self.file_bytes()
        args, ask = self.ask("ie.delete_group", group_id=gid)
        self.assertIn(gid, ask["message"])
        self.assertEqual(ask["groups"], [], "초안 그룹이라 확정이 풀리는 그룹은 없다")
        self.assertEqual(self.file_bytes(), before, "확인 전에는 지우지 않는다")
        self.assertTrue(self.go_on("ie.delete_group", args, ask)["ok"])
        s = self.reread()
        self.assertEqual(s["groups"], [])
        self.assertIn(c1, [c["candidate_id"] for c in s["unassigned"]])
        self.assertEqual(ie_store.load(self.project)[0]["groups"][gid]["status"], "deleted")

    def test_changes_to_a_confirmed_group_ask_first_then_demote_it(self):
        gid = self.human_group()
        self.ok("ie.confirm", group_id=gid)
        before = self.file_bytes()
        args, ask = self.ask("ie.edit_group", group_id=gid, fields={"name": "새 이름"})
        self.assertEqual(ask["groups"], [gid])
        self.assertIn("주급수 상실", ask["message"], "초안이 될 그룹 이름을 보인다")
        self.assertEqual(self.file_bytes(), before)
        self.assertEqual(self.read("ie")["groups"][0]["status"], "confirmed")
        _a, ask2 = self.ask("ie.move", iecs=[self.iec("c4")], to=gid)
        self.assertEqual(ask2["groups"], [gid], "확정 그룹에 후보를 넣는 것도 되묻는다")
        r = self.call("ie.edit_group", dict(args, confirmed=True))
        self.assertEqual(self.code(r), (False, "stale"), "확인한 그룹 목록 없이 confirmed만 보내면 받지 않는다")
        r = self.go_on("ie.edit_group", args, ask)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["demoted"], [gid])
        g = self.reread()["groups"][0]
        self.assertEqual((g["name"], g["status"]), ("새 이름", "draft"))
        self.assertTrue(self.ok("ie.reopen", group_id=gid) is not None)

    def test_confirm_delete_of_a_confirmed_group_is_refused_by_the_engine(self):
        gid = self.human_group()
        self.ok("ie.confirm", group_id=gid)
        r = self.do("ie.delete_group", group_id=gid, confirmed=True)
        self.assertEqual(self.code(r), (False, "failed"), "확정한 그룹은 먼저 확정을 풀어야 지운다(이전 화면과 같음)")


class StaleTest(EditBase):
    def test_old_file_version_is_refused(self):
        gid = self.make_group("그룹", "c1")
        old = self.args(group_id=gid, fields={"name": "A"})
        self.ok("ie.edit_group", group_id=gid, fields={"name": "B"})
        before = self.file_bytes()
        r = self.call("ie.edit_group", old)
        self.assertEqual(self.code(r), (False, "stale"))
        self.assertEqual(self.file_bytes(), before)

    def test_changed_analysis_results_are_refused(self):
        """화면을 연 뒤 ⑤ 결과가 바뀌면(이전 화면의 _reload_if_results_changed) 확정·편집을 저장하지 않는다."""
        gid = self.make_group("그룹", "c1")
        old = self.args(group_id=gid)
        doc, fp = res.load_fp(self.ns)
        cell = next(c for c in doc["cells"] for e in c["entries"] if e["entry_id"] == "c1")
        next(e for e in cell["entries"] if e["entry_id"] == "c1")["consequence"] = "급수가 끊겨 열제거 상실(고침)"
        res.save_fp(doc, self.project, expect=fp)
        before = self.file_bytes()
        r = self.call("ie.confirm", old)
        self.assertEqual(self.code(r), (False, "stale"))
        self.assertIn("분석 결과", r["error"]["message"])
        self.assertEqual(self.file_bytes(), before)
        stale_seen = dict(self.args(group_id=gid), seen=old["seen"])       # ⑤ 지문은 새것, 본 항목은 옛것
        r = self.call("ie.confirm", stale_seen)
        self.assertEqual(self.code(r), (False, "stale"), "그룹 소속 후보의 글이 바뀌었으니 그룹 지문도 다르다")
        self.assertEqual(self.file_bytes(), before)
        self.ok("ie.confirm", group_id=gid)

    def test_a_missing_or_wrong_item_fingerprint_is_refused(self):
        gid = self.make_group("그룹", "c1")
        a = self.args(group_id=gid, fields={"name": "X"})
        bad = dict(a, seen=dict(a["seen"], **{"group:" + gid: "sha256:000"}))
        self.assertEqual(self.code(self.call("ie.edit_group", bad)), (False, "stale"))
        missing = dict(a, seen={k: v for k, v in a["seen"].items() if k != "group:" + gid})
        self.assertEqual(self.code(self.call("ie.edit_group", missing)), (False, "stale"), "화면이 보지 않은 항목은 고치지 않는다")
        self.assertTrue(self.call("ie.edit_group", a)["ok"])

    def test_item_fingerprints_are_stable_across_reads(self):
        self.make_group("그룹", "c1")
        self.assertEqual(self.seen_all(), self.seen_all())

    def test_wrong_project_is_refused_before_anything(self):
        gid = self.make_group("그룹", "c1")
        r = self.engine.dispatch("ie.edit_group", self.args(group_id=gid, fields={"name": "X"}), project="다른-프로젝트", via_web=True)
        self.assertEqual(self.code(r), (False, "wrong_project"))


class RecordAndCoverageTest(EditBase):
    def test_end_state_and_heading_add_edit_remove(self):
        gid = self.make_group("그룹", "c1")
        es = self.ok("ie.add_record", kind="end_state", group_id=gid, fields={"text": "노심 손상 가능", "category": "core_damage_possible"})["id"]
        h = self.ok("ie.add_record", kind="heading", group_id=gid, fields={"name": "보조급수 기동", "role": "mitigative"})["id"]
        d = self.read("ie", "group", gid)
        self.assertIn(es, [e["end_state_id"] for e in d["end_states"]])
        self.assertIn(h, [x["heading_id"] for x in d["headings"]])
        self.ok("ie.edit_record", kind="end_state", id=es, fields={"text": "노심 손상 가능(고침)"})
        self.assertEqual(self.read("ie", "group", gid)["records"]["end_state:" + es]["text"], "노심 손상 가능(고침)")
        self.assertEqual(self.code(self.do("ie.add_record", kind="end_state", group_id=gid, fields={"text": " "})), (False, "failed"))
        args, ask = self.ask("ie.remove_record", kind="heading", id=h)
        self.assertIn(h, ask["message"])
        self.assertTrue(self.go_on("ie.remove_record", args, ask)["ok"])
        self.assertNotIn(h, [x["heading_id"] for x in self.read("ie", "group", gid)["headings"]])

    def test_ai_draft_records_can_be_accepted(self):
        self.ok("ie.suggest")
        s = self.read("ie")
        drafts = []
        for g in s["groups"]:
            recs = self.read("ie", "group", g["group_id"])["records"]
            drafts += [k for k, v in recs.items() if v["origin"] != "human" and v["status"] == "live" and not k.startswith("basic_event")]
        if not drafts:
            self.skipTest("규칙 초안이 표제·최종상태를 만들지 않음")
        kind, rid = drafts[0].split(":")
        doc = ie_store.load(self.project)[0]
        attached = [g for g, v in doc["groups"].items() if rid in v[{"heading": "heading_ids", "end_state": "end_state_ids"}[kind]]]
        if not attached or attached[0] not in [g["group_id"] for g in s["groups"]]:
            self.skipTest("초안 기록이 보이는 그룹에 붙어 있지 않음")
        self.ok("ie.accept_record", kind=kind, id=rid)
        self.assertEqual(ie_store.load(self.project)[0][model.COLLECTIONS[kind][0]][rid]["origin"], "human")

    def test_coverage_needs_a_reason_saves_with_the_reviewer_and_clears(self):
        gap = next(r for r in self.read("ie")["completeness"] if r["status"] == "gap")
        self.assertEqual(self.code(self.do("ie.set_coverage", code=gap["code"], disposition="out_of_scope", reason=" ")), (False, "failed"))
        self.ok("ie.set_coverage", code=gap["code"], disposition="out_of_scope", reason="이 계통 범위 밖")
        row = next(r for r in self.reread()["completeness"] if r["code"] == gap["code"])
        self.assertEqual((row["disposition"]["disposition"], row["disposition"]["reason"]), ("out_of_scope", "이 계통 범위 밖"))
        self.assertIn("이 계통 범위 밖", row["note"], "묶음의 완전성 대조에 사유가 나간다")
        self.assertEqual(ie_store.load(self.project)[0]["coverage"][gap["code"]]["by"], "검토자A")
        self.ok("ie.set_coverage", code=gap["code"], disposition="")
        self.assertIsNone(next(r for r in self.reread()["completeness"] if r["code"] == gap["code"])["disposition"])


class ExportTest(EditBase):
    def export(self, out, overwrite=None):
        self.engine.hooks["save_path"] = lambda kind, name: out
        if overwrite is not None:
            self.engine.hooks["confirm_overwrite_files"] = lambda names: overwrite
        s = self.read("ie")
        r = self.call("ie.export", {"ver": s["ver"], "rver": s["rver"]})
        self.assertTrue(r["ok"], r)
        return r["data"]

    def test_export_reflects_edits_only_approved_and_no_hazop_risk(self):
        gid = self.make_group("주급수 상실", "c1")
        self.ok("ie.edit_group", group_id=gid, fields={"name": "급수 완전 상실", "definition": "정의 글"})
        es = self.ok("ie.add_record", kind="end_state", group_id=gid, fields={"text": "노심 손상 가능", "category": "core_damage_possible"})["id"]
        out = os.path.join(self.tmp, "bundle.xlsx")
        data = self.export(out)
        self.assertEqual((data["path"], data["json_path"], data["cancelled"]), ("bundle.xlsx", "bundle.json", False))
        with open(os.path.join(self.tmp, "bundle.json"), encoding="utf-8") as fh:
            b = json.load(fh)
        g = next(x for x in b["groups"] if x["group_id"] == gid)
        self.assertEqual((g["name"], g["definition"]), ("급수 완전 상실", "정의 글"))
        self.assertIn(es, [e["end_state_id"] for e in b["end_states"]])
        approved = {e["entry_id"] for c in self.r["cells"] for e in c["entries"] if e.get("status") == "approved"}
        self.assertTrue({c["entry_id"] for c in b["candidates"]} <= approved, "승인 항목만 나간다")
        text = json.dumps(b, ensure_ascii=False)
        for key in ('"risk"', '"severity"', '"frequency"'):
            self.assertNotIn(key, text, "HAZOP 위험도는 넣지 않는다")

    def test_existing_json_is_overwritten_only_after_asking(self):
        self.make_group("그룹", "c1")
        out = os.path.join(self.tmp, "b.xlsx")
        self.export(out)
        jpath = os.path.join(self.tmp, "b.json")
        with open(jpath, "w", encoding="utf-8") as fh:
            fh.write("옛 내용")
        data = self.export(out, overwrite=False)
        self.assertTrue(data["cancelled"])
        with open(jpath, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "옛 내용")
        self.engine.hooks.pop("confirm_overwrite_files", None)
        self.assertTrue(self.export(out)["cancelled"], "물을 길이 없으면 덮어쓰지 않는다")
        self.assertFalse(self.export(out, overwrite=True)["cancelled"])
        with open(jpath, encoding="utf-8") as fh:
            self.assertNotEqual(fh.read(), "옛 내용")

    def test_cancelled_dialog_and_stale_results_write_nothing(self):
        self.engine.hooks["save_path"] = lambda kind, name: None
        s = self.read("ie")
        self.assertTrue(self.call("ie.export", {"ver": s["ver"], "rver": s["rver"]})["data"]["cancelled"])
        r = self.call("ie.export", {"ver": s["ver"], "rver": "sha256:old"})
        self.assertEqual(self.code(r), (False, "stale"))


class ChatFunctionTest(EditBase):
    def test_chat_functions_need_the_version_and_raise_confirm(self):
        gid = self.make_group("그룹", "c1")
        v = api_ie.view_groups(self.engine)
        self.assertEqual([g["group_id"] for g in v["groups"]], [gid])
        c4 = self.iec("c4")
        with self.assertRaises(api.CommandError) as no_ver:
            api_ie.move_candidates(self.engine, {"iecs": [c4], "to": gid})
        self.assertEqual(no_ver.exception.code, "bad_args", "판 지문 없이는 고치지 않는다")
        api_ie.move_candidates(self.engine, {"iecs": [c4], "to": gid, "ver": self.read("ie")["ver"]})
        pair = api_ie.split_group(self.engine, {"group_id": gid, "moved": [c4], "ver": self.read("ie")["ver"]})["groups"]
        self.assertEqual(len(pair), 2)
        gap = next(r for r in self.read("ie")["completeness"] if r["status"] == "gap")
        with self.assertRaises(api.CommandError):
            api_ie.judge_coverage(self.engine, {"code": gap["code"], "disposition": "other_method", "reason": "FMEA로 확인"})
        api_ie.judge_coverage(self.engine, {"code": gap["code"], "disposition": "other_method", "reason": "FMEA로 확인",
                                            "ver": self.read("ie")["ver"]})
        self.assertEqual(next(r for r in self.read("ie")["completeness"] if r["code"] == gap["code"])["disposition"]["disposition"], "other_method")
        with self.assertRaises(api.CommandError):
            api_ie.move_candidates(self.engine, {"iecs": [c4], "to": gid, "ver": "sha256:old"})

    def test_chat_confirm_needs_the_shown_groups(self):
        gid = self.human_group()
        self.ok("ie.confirm", group_id=gid)
        c4 = self.iec("c4")
        ver = self.read("ie")["ver"]
        with self.assertRaises(api.CommandError) as asked:
            api_ie.move_candidates(self.engine, {"iecs": [c4], "to": gid, "ver": ver})
        self.assertEqual(asked.exception.code, "confirm")
        self.assertIn(gid, asked.exception.message)
        api_ie.move_candidates(self.engine, {"iecs": [c4], "to": gid, "ver": ver, "confirmed": True, "confirm_groups": [gid]})
        self.assertEqual(ie_store.load(self.project)[0]["groups"][gid]["status"], "draft")


class ReviewFixTest(EditBase):
    """A10 검토(2026-11-14) 재현 R1·R2·R3과 함께 고칠 것 4·5·6."""

    def set_status(self, eid, status):
        doc, fp = res.load_fp(self.ns)
        for c in doc["cells"]:
            for e in c["entries"]:
                if e["entry_id"] == eid:
                    e["status"] = status
        res.save_fp(doc, self.project, expect=fp)

    def test_R1_splitting_a_confirmed_group_asks_and_names_it(self):
        gid = self.make_group("확정 그룹", "c1", "c4")
        r = self.do("ie.confirm", group_id=gid)
        if not r["ok"]:
            self.skipTest("표본에서 두 후보 그룹을 확정할 수 없음: %s" % r["error"]["message"])
        before = self.file_bytes()
        args, ask = self.ask("ie.split", group_id=gid, moved=[self.iec("c4")])
        self.assertEqual(ask["groups"], [gid])
        self.assertIn("확정 그룹", ask["message"])
        self.assertEqual(self.file_bytes(), before, "되묻는 동안 확정 기록이 남는다")
        self.assertEqual(ie_store.load(self.project)[0]["groups"][gid]["confirmation"]["by"], "검토자A")
        r = self.go_on("ie.split", args, ask)
        self.assertTrue(r["ok"], r)
        self.assertEqual(ie_store.load(self.project)[0]["groups"][gid]["status"], "split")

    def test_R1b_every_change_that_drops_a_confirmation_asks(self):
        """확정이 풀리는 변경은 모델이 '건드린 그룹'으로 알리지 않아도 저장 전후 상태를 견줘 되묻는다."""
        gid = self.human_group()
        self.ok("ie.confirm", group_id=gid)
        _a, ask = self.ask("ie.move", iecs=[self.iec("c1")], to="")
        self.assertEqual(ask["groups"], [gid])

    def test_R2_exported_iec_ids_are_saved_and_never_move_to_another_cause(self):
        self.assertIsNone(self.file_bytes(), "표본은 ⑥ 파일이 없는 상태에서 시작한다")
        out = os.path.join(self.tmp, "b.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        s = self.read("ie")
        self.assertTrue(self.call("ie.export", {"ver": s["ver"], "rver": s["rver"]})["ok"])
        with open(os.path.join(self.tmp, "b.json"), encoding="utf-8") as fh:
            exported = {c["entry_id"]: c["candidate_id"] for c in json.load(fh)["candidates"]}
        self.assertIsNotNone(self.file_bytes(), "내보내기 전에 IEC 대응을 저장한다")
        self.set_status("c1", "on_hold")               # ⑤에서 한 건을 보류로 돌림
        self.make_group("g", "c4")                     # 그 뒤 편집
        stored = ie_store.load(self.project)[0]
        now = {model.entry_of_key(v["key"]): k for k, v in stored["candidates"].items()}
        for eid, iec in exported.items():
            self.assertEqual(now.get(eid), iec, "같은 원인은 같은 IEC ID(%s)" % eid)
        self.assertEqual(len(set(now.values())), len(now), "한 번 준 번호를 다른 원인에 다시 쓰지 않는다")

    def test_R2b_results_export_ie_saves_the_iec_map_too(self):
        out = os.path.join(self.tmp, "r.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        r = self.call("results.export_ie", {})
        self.assertTrue(r["ok"], r)
        self.assertIsNotNone(self.file_bytes(), "분석 결과 패널의 인계 묶음도 IEC 대응을 먼저 저장한다")

    def test_R2c_export_does_not_run_when_the_iec_map_cannot_be_saved(self):
        out = os.path.join(self.tmp, "c.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        s = self.read("ie")
        with mock.patch.object(ie_store, "save", side_effect=OSError("디스크 가득")):
            r = self.call("ie.export", {"ver": s["ver"], "rver": s["rver"]})
        self.assertEqual(self.code(r), (False, "failed"))
        self.assertFalse(os.path.exists(out), "IEC 대응을 저장하지 못하면 내보내지 않는다")

    def test_R3_the_card_resends_what_it_showed_and_a_changed_list_is_refused(self):
        doc, fp = res.load_fp(self.ns)
        ents = {e["entry_id"]: e for c in doc["cells"] for e in c["entries"]}
        ents["c2"]["ie_hint"] = copy.deepcopy(ents["c1"]["ie_hint"])     # c2도 c1처럼 확정할 수 있게
        res.save_fp(doc, self.project, expect=fp)
        g1 = self.make_group("g1", "c1")
        self.ok("ie.confirm", group_id=g1)
        g2 = self.make_group("g2", "c2")
        args, ask = self.ask("ie.move", iecs=[self.iec("c1")], to=g2)
        self.assertEqual(ask["groups"], [g1])
        self.ok("ie.confirm", group_id=g2)                                 # 카드가 떠 있는 동안 다른 곳에서 g2를 확정
        before = self.file_bytes()
        r = self.go_on("ie.move", args, ask)                                # 카드가 본 판 그대로 다시 보냄
        self.assertEqual(self.code(r), (False, "stale"))
        fresh = self.args(iecs=[self.iec("c1")], to=g2)
        r = self.call("ie.move", dict(fresh, confirmed=True, confirm_groups=ask["groups"]))   # 새 지문 + 옛 목록
        self.assertEqual(self.code(r), (False, "stale"), "카드에 안 보인 그룹(g2)까지 풀리면 거절한다")
        self.assertIn(g2, r["error"]["message"])
        self.assertEqual(self.file_bytes(), before)
        self.assertEqual(ie_store.load(self.project)[0]["groups"][g2]["status"], "confirmed")

    def test_5_coverage_checks_the_code_and_the_status(self):
        r = self.do("ie.set_coverage", code="NO-SUCH", disposition="out_of_scope", reason="이유")
        self.assertEqual(self.code(r), (False, "failed"))
        covered = next(r for r in self.read("ie")["completeness"] if r["status"] == "covered")
        r = self.do("ie.set_coverage", code=covered["code"], disposition="out_of_scope", reason="이유")
        self.assertEqual(self.code(r), (False, "failed"), "대응 그룹이 있는 범주에는 빈 범주 판정을 두지 않는다")

    def test_6_human_edits_survive_a_new_analysis_run(self):
        from hazop.shell import analysis_run
        from tests.test_shell_results import FakeAi, fake_run_unit
        gid = self.make_group("주급수 상실", "c1")
        self.ok("ie.edit_group", group_id=gid, fields={"name": "급수 완전 상실", "definition": "사람이 쓴 정의"})
        es = self.ok("ie.add_record", kind="end_state", group_id=gid, fields={"text": "노심 손상 가능", "category": "core_damage_possible"})["id"]
        gap = next(r for r in self.read("ie")["completeness"] if r["status"] == "gap")
        self.ok("ie.set_coverage", code=gap["code"], disposition="out_of_scope", reason="범위 밖")
        engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=lambda e: None, run_jobs=lambda jid, fn: fn())
        engine.settings.update(project_id=self.project, reviewer_name="검토자A")
        engine.ai = FakeAi()
        with mock.patch.object(analysis_run, "contexts", lambda units, ns, pg, intent_of: {u["node_id"]: {} for u in units}), \
                mock.patch("hazop.study.ai_cells.run_unit", fake_run_unit()):
            r = engine.dispatch("results.run", {"scope": "all"})
        self.assertTrue(r["ok"], r)
        doc = ie_store.load(self.project)[0]
        self.assertEqual((doc["groups"][gid]["name"], doc["groups"][gid]["definition"]), ("급수 완전 상실", "사람이 쓴 정의"))
        self.assertIn(es, doc["groups"][gid]["end_state_ids"])
        self.assertEqual(doc["coverage"][gap["code"]]["reason"], "범위 밖")
        s = self.read("ie")
        self.assertEqual([g["name"] for g in s["groups"]], ["급수 완전 상실"], "사람이 승인한 원인은 재분석 뒤에도 그룹에 남는다")

    def test_6_excel_sheets_match_the_edits(self):
        import openpyxl
        gid = self.make_group("주급수 상실", "c1")
        self.ok("ie.edit_group", group_id=gid, fields={"name": "급수 완전 상실", "plant_response": "증기발생기 수위 저하"})
        es = self.ok("ie.add_record", kind="end_state", group_id=gid, fields={"text": "노심 손상 가능", "category": "core_damage_possible"})["id"]
        out = os.path.join(self.tmp, "x.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        s = self.read("ie")
        self.assertTrue(self.call("ie.export", {"ver": s["ver"], "rver": s["rver"]})["ok"])
        wb = openpyxl.load_workbook(out)

        def rows(sheet):
            ws = wb[sheet]
            head = [c.value for c in ws[1]]
            return [dict(zip(head, [c.value for c in r])) for r in ws.iter_rows(min_row=2)]
        g = next(r for r in rows("IE 그룹") if r["그룹 ID"] == gid)
        self.assertEqual((g["그룹 이름"], g["플랜트 응답"]), ("급수 완전 상실", "증기발생기 수위 저하"))
        e = next(r for r in rows("최종상태 후보") if r["ES ID"] == es)
        self.assertIn("노심 손상 가능", e["비완화 결과(대표 문장)"])


class OverlapTwinTest(unittest.TestCase):
    """겹친 두 구간(S1·S2가 V1을 함께 가짐)에서 같은 (구성요소, 원인)이 나온 후보 둘이 묶음에서 한 후보로 합쳐지고, 두 구간이 근거로 남는다.
    화면에서 그 후보를 그룹에 넣으면 쌍둥이도 함께 들어가 확정 조건(쌍둥이는 같은 그룹)을 채운다."""

    def setUp(self):
        import shutil
        import tempfile
        from hazop.app import project_ctx
        from tests.test_study_migrate import graph
        from tests.test_study_storage import DEVS, HINT, build, entry, put_entries, sref
        self.tmp = tempfile.mkdtemp(prefix="hazop-ietwin-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.g = graph("v1")
        self.g["sheets"] = [{"graph_id": self.g["graph_id"], "drawing_number": "T-1"}]
        for p in (mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": self.tmp}),
                  mock.patch.object(res, "load_deviations", lambda path=None: copy.deepcopy(DEVS)),
                  mock.patch.object(project_ctx, "project_graph", lambda pid: self.g),
                  mock.patch.dict(api.COMMANDS)):
            p.start()
            self.addCleanup(p.stop)
        ns = build(self.g, [("A", ["TK", "V1"]), ("B", ["V1", "V2"])])
        sn.save(ns)
        doc = res.empty_results(ns, DEVS)
        for nid in ("S1", "S2"):
            put_entries(doc, nid, "I1", [entry("e" + nid, cause="V1 닫힘 고착", consequence="급수 끊김",
                                               cause_refs=[{"ref": sref(self.g, "V1"), "failure_mode": "FTC"}], ie_hint=dict(HINT))])
        self.project = ns.get("project_id")
        res.save_fp(doc, self.project, expect=None)
        self.engine = api.Engine(settings_path=os.path.join(self.tmp, "settings.json"), emit=lambda e: None)
        self.engine.settings.update(project_id=self.project, reviewer_name="검토자A")

    def read(self, *parts):
        return json.loads(api.ReadApi(self.engine).read(list(parts), {}).body.decode("utf-8"))

    def test_twins_merge_into_one_candidate_with_both_nodes_and_move_together(self):
        s = self.read("ie")
        self.assertEqual(len(s["unassigned"]), 1, s["unassigned"])
        c = s["unassigned"][0]
        self.assertEqual(c["node_ids"], ["S1", "S2"])
        self.assertEqual(len(c["merged_from"]), 1)
        r = self.engine.dispatch("ie.create_group", {"ver": s["ver"], "rver": s["rver"], "name": "급수 상실",
                                                     "iecs": [c["candidate_id"]], "seen": {"member:" + c["candidate_id"]: c["fp"]}})
        self.assertTrue(r["ok"], r)
        gid = r["data"]["group_id"]
        stored = ie_store.load(self.project)[0]
        self.assertEqual({x["group_id"] for x in stored["candidates"].values()}, {gid}, "쌍둥이도 같은 그룹에 들어간다")
        s = self.read("ie")
        g = s["groups"][0]
        self.assertEqual(g["problems"], [], "쌍둥이가 같은 그룹이라 확정할 수 있다")
        r = self.engine.dispatch("ie.confirm", {"ver": s["ver"], "rver": s["rver"], "group_id": gid, "seen": {"group:" + gid: g["fp"]}})
        self.assertTrue(r["ok"], r)
        out = os.path.join(self.tmp, "twin.xlsx")
        self.engine.hooks["save_path"] = lambda kind, name: out
        self.assertTrue(self.engine.dispatch("ie.export", {})["ok"])
        self.check_twin_export(out, gid)

    def test_moving_a_merged_candidate_checks_the_group_its_twin_is_in(self):
        """같이 옮겨지는 쌍둥이가 든 그룹도 화면이 본 그룹이어야 한다(그 그룹이 바뀌었으면 거절)."""
        s = self.read("ie")
        c = s["unassigned"][0]
        twin = c["merged_from"][0]
        doc, fp = ie_store.load(self.project)
        doc = model.sync(doc, res.load_fp(sn.load(self.g))[0], node_set=sn.load(self.g))
        doc, other = model.create_group(doc, "쌍둥이만", [twin])
        ie_store.save(doc, expect=fp)
        s = self.read("ie")
        seen = {"member:" + x["candidate_id"]: x["fp"] for x in s["unassigned"]}
        r = self.engine.dispatch("ie.create_group", {"ver": s["ver"], "rver": s["rver"], "name": "새", "iecs": [c["candidate_id"]], "seen": seen})
        self.assertEqual((r["ok"], r["error"]["code"]), (False, "stale"), "쌍둥이가 든 그룹(%s)을 보지 않았으면 거절" % other)
        seen.update({"group:" + g["group_id"]: g["fp"] for g in s["groups"]})
        for g in s["groups"]:
            seen.update({"member:" + m["candidate_id"]: m["fp"] for m in self.read("ie", "group", g["group_id"])["members"]})
        r = self.engine.dispatch("ie.create_group", {"ver": s["ver"], "rver": s["rver"], "name": "새", "iecs": [c["candidate_id"]], "seen": seen})
        self.assertTrue(r["ok"], r)

    def check_twin_export(self, out, gid):
        with open(os.path.join(self.tmp, "twin.json"), encoding="utf-8") as fh:
            b = json.load(fh)
        self.assertEqual(len(b["candidates"]), 1)
        self.assertEqual(b["candidates"][0]["node_ids"], ["S1", "S2"], "두 구간이 근거로 남는다")
        self.assertEqual(b["groups"][0]["members"], [b["candidates"][0]["candidate_id"]])
        self.assertEqual(b["groups"][0]["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
