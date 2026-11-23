"""시트 정체 퍼즈(tests.test_sheet_identity_fuzz)가 e33f2de에서 찾은 결함의 고정 재현 시험. 퍼즈 시드에 기대지 않는 정해진 순서다.

E1 붙박은 in_use 자리가 낡은 채 남아, 번호를 쓰던 파일이 있는데도 앞서 붙박였던 파일이 번호로 돌아오면 그 번호의 주인이 말없이 뒤집힌다.
   변형(시드 207): 낡은 자리의 주인이 아닌 셋째 파일이 그 번호를 받아도, 먼저 등록한 자료라는 차례로 쓰던 파일에게서 가져간다.
E2 정착이 붙박은 옛 자리(legacy)의 주인 파일을 고르기로 고르면 자리가 chosen으로 바뀌어 옛 이름 붙박기가 풀린다. 다음 추출에서 그 파일은 임시 이름으로
   옮겨 가고 그 이름을 같은 번호의 다른 파일이 이어받으며, 그 사이 표제란 가드는 옛 이름 대신 임시 이름으로 셈해 옮길 구간을 0개로 알린다.
E4 (퍼즈가 시드 111·115·183에서 찾음) 문서(초기사건·FMEA·잠재 후보 판단)의 판 이전 기록 `ref_migrations[].lost`에 잃었던 참조의 옛 값('graph-<번호>#…')이 글로
   남는데, 번호 확정 가드가 이를 지금 참조로 세어 그 번호를 다른 도면에 확정하지 못하게 막는다. 참조는 이미 새 이름으로 되찾아졌고 그 기록은 사람이 지울 수 없어
   그 번호가 영영 막힌다(막다른 길). 읽을 때만 옮겨 파일 원문에 남은 옛 이름도 같은 꼴로 막는다(시드 111·115·183).
E5 (퍼즈가 시드 232에서 찾음) 먼저 등록하고 번호를 받았지만 아직 추출하지 않은 파일 x가 나중에 추출되면, 그 사이 같은 번호로 등록·추출해 쓰이던 파일 y에게서 그 번호의 주인을
   말없이 가져간다(고르는 차례 4 '먼저 등록한 자료'가 이김, 자리를 붙박지 않음). 등록 단조(새 자료를 넣어도 있던 시트의 주인이 안 바뀜)가 어긋나고, y의 구간은 묘비가 된다.
고르기 가드(퍼즈가 시드 155·214·246에서 찾음) 다른 파일을 골라 옛 이름 붙박기가 풀린 파일은 다시 추출하기 전까지 옛 이름으로 보이는데, 표제란 가드는 규칙이
   셈한 임시 이름으로 센다. 그래서 옮길 구간을 0개로 알리고 허락한 뒤 구간을 묘비로 만들거나(214·246), 이름이 그대로인 확정을 자기 구간 때문에 거절한다(155).
실행: python -m unittest tests.test_sheet_identity_regress
"""

import unittest
import json
import os
from unittest import mock

from tests.test_sheet_gid_paths import NUMBER, SheetCase, legacy_name
from tests.test_titleblock import BY, P

from hazop import paths
from hazop.app import project_ctx
from hazop.graph import sources
from hazop.register import registry, titleblock as tb
from hazop.ie import model, store as ie_store
from hazop.study import migrate, nodes


class Crash(BaseException):
    """앱이 죽은 것을 흉내 낸다(확정 길의 except Exception이 잡지 못함)."""


class SeatRegressTest(SheetCase):
    def owner(self, gid):
        return next((s["material_id"] for s in project_ctx.project_graph(P)["sheets"] if s["graph_id"] == gid), None)

    def test_e1_a_file_that_returns_to_a_number_does_not_take_it_from_the_file_using_it(self):
        a, b = self.add("SNP-M-101", "drawio"), self.add("SNP-M-102", "drawio")
        for mid, number in ((a, "SNP-M-555"), (b, "SNP-M-555"), (a, "SNP-M-101")):
            self.assertTrue(self.confirm(mid, {"drawing_number": number})["ok"], number)
        self.assertEqual(self.owner("graph-SNP-M-555"), b, "시험 전제: a가 떠나 b가 쓰는 번호")
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-555"})["ok"])
        self.assertEqual(self.owner("graph-SNP-M-555"), b, "a가 번호로 돌아왔다고 쓰던 b에게서 말없이 넘어옴")
        self.assertEqual([(c["in_use_material"]) for c in sources.conflicts(P)], [b])

    def test_e1_variant_a_third_file_does_not_take_the_number_through_a_stale_seat(self):
        c = self.add("SNP-M-301", "drawio")
        a, b = self.add("SNP-M-101", "drawio"), self.add("SNP-M-102", "drawio")
        for mid, number in ((a, "SNP-M-555"), (b, "SNP-M-555"), (a, "SNP-M-101")):
            self.assertTrue(self.confirm(mid, {"drawing_number": number})["ok"], number)
        self.assertEqual(self.owner("graph-SNP-M-555"), b, "시험 전제: a가 떠나 b가 쓰는 번호, a의 낡은 자리가 남음")
        self.assertTrue(self.confirm(c, {"drawing_number": "SNP-M-555"})["ok"])
        self.assertEqual(self.owner("graph-SNP-M-555"), b, "먼저 등록한 c가 낡은 자리를 틈타 쓰던 b에게서 번호를 가져감")
        self.assertEqual([x["in_use_material"] for x in sources.conflicts(P)], [b])

    def legacy_pair(self):
        """이 단위 전 앱: 번호 없는 drawio a(쪽 이름 graph-SNP-M-101)와 같은 번호 101을 확정한 PDF b가 한 이름을 나눠 쓴다. 정착하면 a가 옛 자리 주인이다."""
        with mock.patch("hazop.graph.sources.sheet_name", legacy_name, create=True), \
                mock.patch("hazop.app.data.settle_sheets", lambda *a, **k: None, create=True):
            a = self.add("SNP-M-101", "drawio")
            b = self.register(self.copy_in("SNP-M-101", "pdf", "in-b"), dict(NUMBER))
        self.reextract(a)    # 명시적인 차례가 정착을 부른다
        seat = sources.load_seats(P)[0]["graph-SNP-M-101"]
        self.assertEqual((seat["why"], seat["material_id"]), ("legacy", a), "시험 전제: a가 옛 자리 주인")
        return a, b

    def test_e2_choosing_the_legacy_seat_owner_keeps_its_name_when_it_is_extracted_again(self):
        a, b = self.legacy_pair()
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=a)
        self.reextract(a)
        self.assertEqual(self.owner("graph-SNP-M-101"), a, "사람이 고른 a가 다음 추출에서 임시 이름으로 옮겨 가고 b가 그 이름을 이어받음")
        self.assertEqual(self.sheet(a)["graph_id"], "graph-SNP-M-101")

    def test_e2_guard_counts_the_segment_on_the_chosen_legacy_name(self):
        a, _b = self.legacy_pair()
        self.make_nodes(a)
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=a)
        dry = self.confirm(a, {"drawing_number": "SNP-M-102"}, dry=True)
        self.assertTrue(dry["ok"], dry)
        self.assertEqual(dry["carries"], {"구간": 1}, "가드가 a의 옛 이름 대신 임시 이름으로 셈해 옮길 구간을 놓침")

    def unpinned_owner(self):
        """옛 자리 주인 a를 두고 b를 고르면 a의 옛 이름 붙박기가 풀린다. a는 다시 추출하기 전까지 디스크의 graph.json으로 옛 이름을 지닌다."""
        a, b = self.legacy_pair()
        self.make_nodes(a)
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=b)
        self.assertNotIn("pin", sources.load_seats(P)[0]["graph-SNP-M-101"], "시험 전제: b를 고르자 a의 붙박기가 풀림")
        return a, b

    def test_choose_guard_counts_the_segment_on_the_name_the_sheet_uses_now(self):
        """시드 214·246: 붙박기가 풀린 a를 다시 고르면 a는 옛 이름 그대로 보이는데, 가드는 규칙이 셈한 임시 이름으로 세어 옮길 구간을 0개로 알리고
        허락한 뒤 그 구간을 묘비로 만든다."""
        a, _b = self.unpinned_owner()
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=a)
        self.assertEqual(self.owner("graph-SNP-M-101"), a, "시험 전제: 다시 고른 a가 옛 이름으로 보임")
        _pg, before = self.node()
        dry = self.confirm(a, {"drawing_number": "SNP-M-102"}, dry=True)
        self.assertTrue(dry["ok"], dry)
        self.assertEqual(dry["carries"], {"구간": 1}, "가드가 a가 지금 쓰는 이름 대신 임시 이름으로 셈해 옮길 구간을 놓침")
        self.assertEqual([r["from"] for r in dry["renames"]], ["graph-SNP-M-101"])
        out = self.confirm(a, {"drawing_number": "SNP-M-102"})
        self.assertEqual((out["ok"], out["carries"]), (True, {"구간": 1}), out)
        _pg, n = self.node()
        self.assertEqual((len(n["members"]), n.get("lost") or []), (len(before["members"]), []), "허락한 번호 바꿈이 구간 구성요소를 묘비로 만듦")

    def test_choose_guard_confirming_the_name_the_sheet_uses_now_is_not_refused(self):
        """시드 155: 붙박기가 풀린 a가 옛 이름(번호 101과 같은 이름)으로 보이는 채 번호 101을 확정하면 이름은 그대로인데, 가드는 a를 임시 이름에서
        101로 옮기는 것으로 셈해 a 자신의 구간을 '새 번호의 도면을 가리키는 기록'으로 세어 거절한다."""
        a, b = self.legacy_pair()
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=b)
        left = tb.unconfirm(P, b, ["drawing_number"], BY, ver=self.row(b)["ver"])
        self.assertTrue(left["ok"], "시험 전제: b가 번호를 떠남: %s" % left.get("refused"))
        self.assertEqual(self.owner("graph-SNP-M-101"), a, "시험 전제: 붙박기가 풀린 a가 옛 이름으로 보임")
        self.assertEqual(self.sheet(a)["graph_id"], "graph-SNP-M-101", "표제란 줄이 a가 지금 쓰는 이름 대신 임시 이름을 보임")
        self.make_nodes(a)
        out = self.confirm(a, {"drawing_number": "SNP-M-101"}, dry=True)
        self.assertTrue(out["ok"], "막을 것이 없는데 거절: %s" % (out.get("refused") or [{}])[0].get("reason"))
        self.assertEqual((out["carries"], out["renames"]), ({}, []))

    def choose_back(self, step):
        """옛 자리 주인 a의 구간을 두고 b를 골랐다가, a에 step(다시 추출·제목 확정)을 한 뒤 a를 다시 고른다. 카드가 '다시 고르면 바로 되돌아옵니다'라고
        약속하므로 a의 구간은 되돌아와야 한다."""
        a, b = self.legacy_pair()
        _pg, before = self.make_nodes(a)
        members = before["nodes"][0]["members"]
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=b)
        _pg, n = self.node()
        self.assertEqual((n["members"], len(n.get("lost") or [])), ([], 6), "시험 전제: b를 고르자 a의 구성요소가 묘비가 됨")
        step(a)
        self.assertIn(a, [x["material_id"] for c in sources.conflicts(P) if c["graph_id"] == "graph-SNP-M-101" for x in c["candidates"]],
                      "a가 그 이름의 고르기 후보에서 사라져 되돌릴 길이 없음")
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=a)
        self.assertEqual(self.owner("graph-SNP-M-101"), a)
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []), "다시 고른 a의 구성요소가 묘비로 남음")

    def test_choosing_back_after_reextracting_the_unpinned_file_restores_its_segment(self):
        self.choose_back(self.reextract)

    def test_choosing_back_after_confirming_only_the_title_restores_its_segment(self):
        def title(a):
            out = self.confirm(a, {"title": "다른 제목"})
            self.assertTrue(out["ok"], out.get("refused"))
        self.choose_back(title)

    def test_e2_choosing_a_format_after_the_legacy_owner_keeps_its_name(self):
        a, b = self.legacy_pair()
        sources.choose(P, "graph-SNP-M-101", None, BY, material_id=a)
        sources.choose(P, "graph-SNP-M-101", "pdf_vector", BY)
        self.reextract(a)
        self.assertEqual(self.sheet(a)["graph_id"], "graph-SNP-M-101", "형식을 고르며 고른 파일을 내려놓자 옛 이름 붙박기도 풀림")
        self.assertEqual(self.owner("graph-SNP-M-101"), b)

    def test_e5_guard_the_owner_confirming_its_own_name_keeps_it_while_its_graph_is_set_aside(self):
        """시드 14·16·29: 확정 길은 그 쪽 앞 그래프를 비켜 둔 뒤 다시 추출한다. 그 사이 디스크로는 같은 번호를 원하는 b가 주인으로 보이지만
        추출이 그것을 붙박으면 이름을 쓰던 a가 자리를 잃는다."""
        a, b = self.legacy_pair()
        self.assertEqual(self.owner("graph-SNP-M-101"), a, "시험 전제: 옛 자리 주인 a가 이름을 씀")
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-101"})["ok"])
        self.assertEqual(self.owner("graph-SNP-M-101"), a, "같은 이름의 번호를 확정한 a가 비켜 둔 사이 b에게 붙박혀 이름을 잃음")

    def test_e5_guard_a_plain_reextract_after_a_crashed_confirm_keeps_the_owner(self):
        """확정 중 다시 추출하다 앱이 죽어(비켜 둔 앞 그래프가 되돌려지지 않음) 사람이 그냥 다시 추출한다. 디스크로는 b가 주인으로 보이지만
        a는 비켜 두기 직전까지 그 이름을 쓰던 주인이다."""
        a, b = self.legacy_pair()
        _pg, before = self.make_nodes(a)

        def crash(_path):
            raise Crash()
        with self.assertRaises(Crash):
            self.confirm(a, {"drawing_number": "SNP-M-101"}, extract=crash)
        self.reextract(a)
        self.assertEqual(self.owner("graph-SNP-M-101"), a, "죽은 확정 뒤 그냥 다시 추출하자 a의 이름이 b에게 붙박힘")
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (before["nodes"][0]["members"], []))

    def test_e3_refusal_text_does_not_send_the_user_to_a_no_op(self):
        """옛 자리 주인 a가 번호를 확정했다가 취소하면 옛 자리 이름으로 돌아가는데, 그 이름을 b의 번호가 쓰고 있다. 판이 이미 맞는데 '도면 변경 반영하기'를 시키면 막다른 글이다."""
        from hazop.register import titleblock as tb
        a, b = self.legacy_pair()
        self.make_nodes(a)
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-102"})["ok"])
        self.assertEqual(self.owner("graph-SNP-M-101"), b, "시험 전제: 옛 자리 이름을 지금은 b가 씀")
        pg = project_ctx.project_graph(P)
        self.assertEqual(nodes.load(pg)["graph_version"], pg["graph_version"], "시험 전제: 구간 저장본이 지금 판과 같음")
        out = tb.unconfirm(P, a, ["drawing_number"], BY, ver=self.row(a)["ver"], dry=True)
        self.assertFalse(out["ok"], "시험 전제: 옛 이름을 b의 번호가 쓰므로 막음")
        self.assertNotIn("도면 변경 반영하기", out["refused"][0]["reason"], "이미 맞는 판을 반영하라는 막다른 글")


class DocLogRegressTest(SheetCase):
    def test_e4_a_past_loss_in_a_documents_move_log_does_not_block_the_number(self):
        a = self.add("SNP-M-101", "pdf")
        self.make_nodes(a)
        pg = project_ctx.project_graph(P)
        ns = nodes.load(pg)
        ref = ns["graph_member_refs"][ns["nodes"][0]["members"][0]]
        doc = model.empty(P)
        doc["counters"]["H"] = 1
        doc["headings"]["H-01"] = {"name": "h", "targets": [ref], "status": "live", "origin": "human"}
        doc["ref_versions"] = {ns["graph_id"]: {"graph_version": ns["graph_version"], "step": len(migrate.lines(ns))}}
        doc["ref_migrations"] = [{"at": "2026-11-23T00:00:00Z", "from": "pv-a", "to": "pv-b", "graph_id": ns["graph_id"], "step": 1, "refs_lost": 1,
                                  "lost": {"lost:project-P1:pv-b:t-0": "graph-SNP-M-555#pdf-p0-conn-0018"}}]
        os.makedirs(os.path.dirname(ie_store.store_path(P)), exist_ok=True)
        with open(ie_store.store_path(P), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        b = self.add("SNP-M-102", "pdf")
        out = self.confirm(b, {"drawing_number": "SNP-M-555"}, dry=True)
        self.assertTrue(out["ok"], "이미 되찾은 참조의 옛 값이 판 이전 기록에 글로 남았을 뿐인데 그 번호를 막음: %s" % (out.get("refused") or [{}])[0].get("reason"))

    def test_e4_an_old_name_left_in_a_documents_file_does_not_block_the_number(self):
        """판 이전을 문서 파일에 쓰지 못해(write_after 실패) 원문에 a의 옛 이름 101이 남았지만 읽는 길은 이미 555로 옮겨 본다. 그 뒤 101을 받은 b가
        번호를 바꿀 때 가드는 그 옛 이름을 b의 기록으로 세지 않는다."""
        a = self.add("SNP-M-101", "pdf")
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-101"})["ok"])
        self.make_nodes(a)
        pg = project_ctx.project_graph(P)
        ns = nodes.load(pg)
        ref = ns["graph_member_refs"][ns["nodes"][0]["members"][0]]
        self.assertTrue(ref.startswith("graph-SNP-M-101#"), ref)
        doc = model.empty(P)
        doc["counters"]["H"] = 1
        doc["headings"]["H-01"] = {"name": "h", "targets": [ref], "status": "live", "origin": "human"}
        doc["ref_versions"] = {ns["graph_id"]: {"graph_version": ns["graph_version"], "step": len(migrate.lines(ns))}}
        raw = json.dumps(doc, ensure_ascii=False)
        os.makedirs(os.path.dirname(ie_store.store_path(P)), exist_ok=True)
        with open(ie_store.store_path(P), "w", encoding="utf-8") as fh:
            fh.write(raw)
        self.assertTrue(self.confirm(a, {"drawing_number": "SNP-M-555"})["ok"])
        nodes.load(project_ctx.project_graph(P))
        with open(ie_store.store_path(P), "w", encoding="utf-8") as fh:
            fh.write(raw)
        seen = json.dumps(ie_store.load(P), ensure_ascii=False)
        self.assertNotIn("graph-SNP-M-101#", seen, "시험 전제: 읽는 길은 옛 이름을 새 이름으로 옮겨 봄")
        self.assertIn("graph-SNP-M-555#", seen)
        b = self.add("SNP-M-102", "pdf")
        self.assertTrue(self.confirm(b, {"drawing_number": "SNP-M-101"})["ok"], "시험 전제: 비어 있던 번호 101을 b가 받음")
        with open(ie_store.store_path(P), "w", encoding="utf-8") as fh:
            fh.write(raw)
        out = self.confirm(b, {"drawing_number": "SNP-M-103"}, dry=True)
        self.assertTrue(out["ok"], (out.get("refused") or [{}])[0].get("reason"))
        self.assertEqual(out["carries"], {}, "읽는 길이 이미 a의 555로 옮긴 원문의 옛 이름을 b의 기록으로 셈(증명이 없으면 막음)")


class RegistrationOrderRegressTest(SheetCase):
    def test_e5_extracting_a_file_registered_earlier_does_not_take_the_number_from_the_file_in_use(self):
        x = self.register_only("SNP-M-102", "drawio", "in-x")
        y = self.register(self.copy_in("SNP-M-101", "drawio", "in-y"), dict(NUMBER))
        _pg, before = self.make_nodes(y)
        members = before["nodes"][0]["members"]
        self.assertEqual(self.owner_of("graph-SNP-M-101"), y, "시험 전제: 추출한 y가 쓰는 번호")
        self.reextract(x)
        self.assertEqual(self.owner_of("graph-SNP-M-101"), y, "먼저 등록했을 뿐인 x가 추출되자 쓰던 y에게서 번호를 가져감")
        _pg, n = self.node()
        self.assertEqual((n["members"], n.get("lost") or []), (members, []))

    def register_only(self, drawing, ext, folder):
        """번호 SNP-M-101과 함께 등록만 하고 추출은 하지 않는다."""
        res = registry.register(self.copy_in(drawing, ext, folder), P, "P&ID", paths.store_root(), dict(NUMBER), BY)
        self.assertEqual(res["outcome"], "registered", res.get("notes"))
        return res["record"]["material_id"]

    def owner_of(self, gid):
        return next((s["material_id"] for s in project_ctx.project_graph(P)["sheets"] if s["graph_id"] == gid), None)


if __name__ == "__main__":
    unittest.main()
