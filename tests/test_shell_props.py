"""구성요소 속성 카드의 자료(hazop/shell/api_props.py): 종류별 항목 표, 값의 출처(도면 속성·설계 문서 주장), 없는 값은 비워 둠.
실행: python -m unittest tests.test_shell_props"""

import json
import unittest

from hazop.shell import api, api_props
from tests.test_shell_web import ShellBase


class SpecTableTest(unittest.TestCase):
    def test_each_kind_group_has_the_agreed_items_in_order(self):
        names = {k: [x[0] for x in v[1]] for k, v in api_props.SPECS.items()}
        self.assertEqual(names["pipe"], ["호칭 지름", "두께(스케줄)", "재질", "설계 압력", "설계 온도", "유체", "보온"])
        self.assertEqual(names["vessel"], ["재질", "설계 압력", "설계 온도", "용량", "치수"])
        self.assertEqual(names["rotating"], ["형식", "정격 유량", "정격 양정(압력)", "동력", "재질"])
        self.assertEqual(names["valve"], ["형식", "호칭 지름", "압력 등급", "재질", "구동 방식", "고장 시 위치"])
        self.assertEqual(names["instrument"], ["측정 변수", "측정 범위", "기능", "설정값"])
        self.assertEqual(names["other"], ["재질", "비고"])
        self.assertEqual(names["relief"][4], "설정 압력")

    def test_kinds_fall_into_the_right_group(self):
        g = api_props.group_of
        self.assertEqual([g("control_valve", "symbol"), g("check_valve", "symbol"), g("psv", "symbol"), g("relief_valve", "symbol")], ["valve", "valve", "relief", "relief"])
        self.assertEqual([g("pump", "symbol"), g("compressor", "symbol"), g("vessel", "symbol"), g("tank", "symbol"), g("heat_exchanger", "symbol")],
                         ["rotating", "rotating", "vessel", "vessel", "vessel"])
        self.assertEqual([g("transmitter", "symbol"), g("tee", "symbol"), g(None, "symbol"), g("not_a_kind", "symbol"), g("process", "pipe")],
                         ["instrument", "other", "other", "other", "pipe"])

    def test_every_attribute_name_in_the_table_is_in_the_property_dictionary_or_a_known_future_name(self):
        """표의 도면 속성 이름은 속성 사전의 이름이거나, 추출이 아직 내지 않는 이름(아래 목록)이다. 오타가 조용히 빈 칸이 되지 않게 한다."""
        from hazop.kg.schema import REGISTRY
        future = {"schedule", "wall_thickness", "fluid", "capacity", "volume", "dimensions", "pump_type", "equipment_type", "rated_pressure", "rated_power",
                  "pressure_class", "rating", "remarks", "note"}
        for _group, (_label, specs) in api_props.SPECS.items():
            for _name, attr_names, _items in specs:
                for a in attr_names:
                    self.assertTrue(a in REGISTRY.properties or a in future, a)


class ValuesTest(unittest.TestCase):
    def test_drawing_attributes_fill_the_items_and_the_rest_stay_empty(self):
        out = api_props.values_for("valve", {"valve_type": "globe", "fail_position": "FC", "actuator_type": "motor", "motive_power": "electric"}, [])
        by = {i["label"]: i for i in out["items"]}
        self.assertEqual(by["형식"]["value"], "글로브")
        self.assertEqual(by["고장 시 위치"]["value"], "닫힘")
        self.assertEqual(by["구동 방식"]["value"], "전동기 · 전기")
        self.assertEqual(by["재질"], {"label": "재질", "value": None, "source": None})
        self.assertEqual(by["형식"]["source"], {"kind": "drawing"})
        self.assertEqual(len(out["items"]), 6)

    def test_a_document_value_fills_an_empty_item_by_property_or_by_item_name_and_never_beats_the_drawing(self):
        claims = [{"property": None, "item": "설계압력", "value": "17.2", "unit": "MPa", "name": "설계기준서"},
                  {"property": "material", "item": None, "value": "SA-106", "unit": None, "name": "배관 사양서"}]
        out = api_props.values_for("vessel", {}, claims)
        by = {i["label"]: i for i in out["items"]}
        self.assertEqual((by["설계 압력"]["value"], by["설계 압력"]["source"]), ("17.2 MPa", {"kind": "document", "name": "설계기준서"}))
        self.assertEqual(by["재질"]["value"], "SA-106")
        both = api_props.values_for("vessel", {"material": "SS304"}, claims)
        self.assertEqual({i["label"]: i["value"] for i in both["items"]}["재질"], "SS304")

    def test_the_instrument_range_joins_low_and_high(self):
        out = api_props.values_for("instrument", {"range_min": "0 MPa", "range_max": "20 MPa", "set_pressure": "17.2 MPa"}, [])
        by = {i["label"]: i["value"] for i in out["items"]}
        self.assertEqual((by["측정 범위"], by["설정값"]), ("0 MPa~20 MPa", "17.2 MPa"))


class ReadTest(ShellBase):
    def test_the_read_topic_gives_items_for_a_real_component_and_nothing_for_an_unknown_one(self):
        win = self.window()
        gid = self.jsj(win, "window.__hz.store.get().drawings.drawings")[0]["graph_id"]
        reader = api.ReadApi(win.engine)
        items = json.loads(reader.read(["sheet", gid], {}).body.decode("utf-8"))["items"]
        valve = next(i for i in items if i.get("layer") == "symbol" and api_props.group_of(i.get("kind"), "symbol") == "valve")
        got = json.loads(reader.read(["props", gid, valve["id"]], {}).body.decode("utf-8"))
        self.assertEqual((got["found"], got["group"]), (True, "valve"))
        self.assertEqual([i["label"] for i in got["items"]], [x[0] for x in api_props.SPECS["valve"][1]])
        pipe = next(i for i in items if i.get("layer") == "pipe")
        self.assertEqual(json.loads(reader.read(["props", gid, pipe["id"]], {}).body.decode("utf-8"))["group"], "pipe")
        self.assertIsNone(reader.read(["props", gid, "no-such-item"], {}))
        self.assertIsNone(reader.read(["props", "no-such-sheet", valve["id"]], {}))


if __name__ == "__main__":
    unittest.main()
