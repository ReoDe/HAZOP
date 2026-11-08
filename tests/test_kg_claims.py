"""속성 주장(claim)과 도면값·문서값 충돌 테스트 (기획서/지식그래프-스키마.md KD4·§3·§8.2 M3, 사전 §1.2).
실행: python -m unittest discover -s tests -t .

샘플 도면 SNP-M-102(RC-PSV101 도면 속성 set_pressure="17.2 MPa")와 정상 샘플 지식 CSV 사본을 쓴다. 파일을 쓰지 않는다.
"""

import copy
import unittest

from hazop.kg import build, claims, screen
from hazop.kg.schema import REGISTRY, Registry, RegistryError
from tests.test_kg import link, pid_graph, sample

GID = "graph-SNP-M-102"


def psv(graph):
    return next(n for n in graph["nodes"] if n.get("tag") == "RC-PSV101")


def with_setpt3(**values):
    """setpt-003(RC-PSV101 has_setpoint, 항목 '설정압력')의 값만 바꾼 샘플."""
    k = sample()
    next(n for n in k["nodes"] if n["id"] == "setpt-003").update(values)
    return k


def set_pressure_conflicts(kg):
    return [c for c in kg["conflicts"] if c["property"] == "set_pressure"]


class ClaimFormatTest(unittest.TestCase):

    def test_drawing_and_document_claims_share_one_format(self):
        g = pid_graph()
        kg = build.build_kg(sample(), [g])
        ref = claims.stable_ref(GID, psv(g)["source_object_id"])
        mine = {(c["property"], c["holder"]): c for c in kg["claims"] if c["target"] == ref}
        drawing, doc = mine[("set_pressure", None)], mine[("set_pressure", "setpt-003")]
        self.assertEqual(set(drawing), set(doc))
        for f in ("target", "property", "value", "value_min", "value_max", "unit", "unit_normalized",
                  "value_normalized", "pressure_basis", "operating_mode", "origin", "method", "source",
                  "knowledge_status", "display"):
            self.assertIn(f, drawing)
        self.assertEqual((drawing["value"], drawing["unit"], drawing["pressure_basis"]), ("17.2", "MPa", None))
        self.assertEqual((drawing["origin"], drawing["knowledge_status"], drawing["display"]),
                         ("pid_extract", "confirmed", "inline"))
        self.assertEqual(drawing["source"], {"graph_id": GID, "graph_version": g["graph_version"],
                                             "source_object_id": psv(g)["source_object_id"]})
        self.assertEqual((doc["value"], doc["item"], doc["link"], doc["display"]), ("9", "설정압력", "krel-012", "node"))
        self.assertEqual((doc["origin"], doc["knowledge_status"], doc["source"]["material_id"]),
                         ("human", "unknown", "MAT-KG-001"))
        self.assertIsNone(doc["unit_normalized"])  # 단위 환산은 하지 않음
        self.assertEqual(mine[("tag", None)]["value"], "RC-PSV101")
        self.assertEqual(len({c["id"] for c in kg["claims"]}), len(kg["claims"]))

    def test_quantity_parsing_keeps_text_when_not_number_unit(self):
        self.assertEqual(claims.parse_quantity("17.2 MPa"), ("17.2", "MPa", None))
        self.assertEqual(claims.parse_quantity("8 bar(g)"), ("8", "bar", "gauge"))
        self.assertEqual(claims.parse_quantity("1,200 kPa(a)"), ("1200", "kPa", "absolute"))
        self.assertEqual(claims.parse_quantity("약 17 MPa"), ("약 17 MPa", None, None))

    def test_human_edited_position_claim_origin(self):
        g = pid_graph()
        n = next(x for x in g["nodes"] if (x.get("attributes") or {}).get("normal_position"))
        n["human_edit"] = {"op_ids": ["op-1"], "ops": ["set_normal_position"], "by": "t", "at": None}
        cs = {c["property"]: c for c in claims.drawing_claims(g)
              if c["target"] == claims.stable_ref(GID, n["source_object_id"])}
        self.assertEqual((cs["normal_position"]["origin"], cs["normal_position"]["method"]), ("human_edit", "manual"))
        self.assertEqual(cs["tag"]["origin"], "pid_extract")  # 태그는 고치지 않음

    def test_graph_not_changed_and_graph_version_same(self):
        g = pid_graph()
        before = copy.deepcopy(g)
        build.build_kg(sample(), [g])
        self.assertEqual(g, before)


class TagHypothesisTest(unittest.TestCase):

    def test_inferred_tag_claim_is_hypothesis_node_stays(self):
        g = pid_graph()
        n = psv(g)
        n["tag_basis"] = "도면 글자 'PSV101' + 계통 접두 RC- 추정 [추론]"
        kg = build.build_kg(sample(), [g])
        ref = claims.stable_ref(GID, n["source_object_id"])
        tag = next(c for c in kg["claims"] if c["target"] == ref and c["property"] == "tag")
        self.assertEqual(tag["knowledge_status"], "hypothesis")
        others = [c for c in kg["claims"] if c["target"] == ref and c["property"] != "tag" and c["holder"] is None]
        self.assertTrue(others and all(c["knowledge_status"] == "confirmed" for c in others))
        self.assertEqual(kg["validation"]["status"], "passed")  # 노드·관계는 그대로(차단·제외 없음)
        lk = {l["id"]: l for l in kg["links"]}
        self.assertTrue(lk["krel-009"]["compute_view"]["v4"])

    def test_human_tag_confirmed(self):
        g = pid_graph()
        psv(g)["tag_basis"] = "human"
        tag = next(c for c in claims.drawing_claims(g) if c["property"] == "tag" and c["value"] == "RC-PSV101")
        self.assertEqual((tag["knowledge_status"], tag["origin"]), ("confirmed", "human_edit"))


class DrawingDocumentConflictTest(unittest.TestCase):

    def test_drawing_value_vs_document_value_conflict(self):
        g = pid_graph()
        kg = build.build_kg(with_setpt3(value="16.5", unit="MPa", pressure_basis="gauge"), [g])
        ref = claims.stable_ref(GID, psv(g)["source_object_id"])
        [c] = set_pressure_conflicts(kg)
        self.assertEqual(c["members"], [ref, "setpt-003"])
        self.assertEqual((c["graph_id"], c["entity_id"], c["node_type"]), (GID, psv(g)["entity_id"], None))
        self.assertEqual([(v["value"], v["unit"], v["origin"]) for v in c["values"]],
                         [("17.2", "MPa", "pid_extract"), ("16.5", "MPa", "human")])
        node = {n["id"]: n for n in kg["nodes"]}
        self.assertEqual((node["setpt-003"]["conflict_with"], node["setpt-003"]["conflict_with_pid"]), ([], [ref]))
        self.assertIn({"check": "conflict", "target": "%s,setpt-003" % ref, "field": "value",
                       "reason": "같은 대상(%s)·항목(설정압력)에 서로 다른 값 - 둘 다 보존" % psv(g)["entity_id"]},
                      kg["validation"]["unknowns"])

    def test_comparison_rules_reused(self):
        same = build.build_kg(with_setpt3(value="17.20", unit="MPa"), [pid_graph()])
        self.assertEqual(set_pressure_conflicts(same), [])  # 숫자로 같으면 충돌 아님
        no_unit = build.build_kg(with_setpt3(value="17.2", unit=None), [pid_graph()])
        self.assertEqual(set_pressure_conflicts(no_unit), [])  # 한쪽 단위 빈 칸이면 단위는 비교하지 않음
        other_unit = build.build_kg(with_setpt3(value="17.2", unit="kgf/cm2"), [pid_graph()])
        self.assertEqual(len(set_pressure_conflicts(other_unit)), 1)  # 환산하지 않음: 단위가 다르면 충돌

    def test_both_sides_preserved(self):
        g = pid_graph()
        kg = build.build_kg(with_setpt3(value="16.5", unit="MPa"), [g])
        self.assertEqual(psv(g)["attributes"]["set_pressure"], "17.2 MPa")
        node = {n["id"]: n for n in kg["nodes"]}
        self.assertEqual((node["setpt-003"]["value"], node["setpt-003"]["unit"]), ("16.5", "MPa"))
        c = set_pressure_conflicts(kg)[0]
        held = {x["id"]: x for x in kg["claims"]}
        self.assertEqual([held[i]["value"] for i in c["claims"]], ["17.2", "16.5"])
        self.assertEqual(kg["validation"]["status"], "passed")

    def test_document_values_also_compared_under_property(self):
        k = with_setpt3(value="17.2", unit="MPa")
        n4 = dict(next(n for n in k["nodes"] if n["id"] == "setpt-003"), id="setpt-004", item="설정 압력", value="16")
        k["nodes"].append(n4)
        k["links"].append(link("krel-104", "has_setpoint", "graph-SNP-M-102:RC-PSV101", "setpt-004"))
        kg = build.build_kg(k, [pid_graph()])
        pairs = [c["members"] for c in set_pressure_conflicts(kg)]
        self.assertIn(["setpt-003", "setpt-004"], pairs)  # 문서값끼리('설정압력'='설정 압력')
        self.assertEqual(len(pairs), 2)  # 도면 17.2 ≠ setpt-004 16 도 충돌, 도면 = setpt-003

    def test_property_only_for_classes_that_have_it(self):
        k = sample()
        k["links"].append(link("krel-105", "has_setpoint", "graph-SNP-M-102:RC-PT110", "setpt-003"))
        kg = build.build_kg(k, [pid_graph()])
        c = next(c for c in kg["claims"] if c["link"] == "krel-105")
        self.assertIsNone(c["property"])  # 전송기에는 설정압력 속성이 없음 -> (설정치, 항목)끼리만 비교

    def test_rejected_link_not_claimed(self):
        k = with_setpt3(value="16.5", unit="MPa")
        next(l for l in k["links"] if l["id"] == "krel-012")["link_status"] = "rejected"
        kg = build.build_kg(k, [pid_graph()])
        self.assertEqual(set_pressure_conflicts(kg), [])
        self.assertFalse(any(c["link"] == "krel-012" for c in kg["claims"]))

    def test_same_input_same_bytes(self):
        k = with_setpt3(value="16.5", unit="MPa")
        a, b = build.build_kg(copy.deepcopy(k), [pid_graph()]), build.build_kg(copy.deepcopy(k), [pid_graph()])
        self.assertEqual(build.dump_bytes(a), build.dump_bytes(b))


class ScreenConflictTest(unittest.TestCase):

    def test_screen_marks_drawing_node_and_document_node(self):
        g = pid_graph()
        kg = build.build_kg(with_setpt3(value="16.5", unit="MPa"), [g])
        d = screen.screen_data(kg, g)
        nodes = {n["id"]: n for n in d["nodes"]}
        self.assertTrue(nodes[psv(g)["entity_id"]]["conflict"])
        self.assertTrue(nodes["setpt-003"]["conflict"])
        self.assertFalse(any(n["conflict"] for n in d["nodes"] if n["layer"] == "pid" and n["id"] != psv(g)["entity_id"]))
        self.assertEqual(d["meta"]["conflicts"], len(kg["conflicts"]))


class RegistryItemsTest(unittest.TestCase):

    def test_lookup_ignores_spaces(self):
        self.assertEqual(REGISTRY.property_of_item("setpoint", "설정 압력"), "set_pressure")
        self.assertEqual(REGISTRY.property_of_item("condition", "설계압력"), "design_pressure")
        self.assertIsNone(REGISTRY.property_of_item("setpoint", "고압 트립"))
        self.assertIsNone(REGISTRY.property_of_item("setpoint", None))

    def test_bad_knowledge_items_rejected(self):
        for bad in ([{"node_type": "setpoint"}], [{"node_type": "valve", "item": "x"}], "설정압력"):
            data = copy.deepcopy(REGISTRY.data)
            next(p for p in data["properties"] if p["id"] == "size")["knowledge_items"] = bad
            with self.assertRaises(RegistryError):
                Registry(data)
        data = copy.deepcopy(REGISTRY.data)  # 같은 항목이 두 속성에 대응
        next(p for p in data["properties"] if p["id"] == "size")["knowledge_items"] = \
            [{"node_type": "setpoint", "item": "설정 압력"}]
        with self.assertRaises(RegistryError):
            Registry(data)


if __name__ == "__main__":
    unittest.main()
