// 도면 탭의 추출 확인 창(web/js/canvas/extract_check.js, 화면 단순화 B): 무엇을 어떤 색으로 칠할지와 구성요소 속성 글.
import { LEGEND, extractGroups, neighborsOf, segmentsOf } from "../js/canvas/extract_check.js";

const SHEET = {
  items: [
    { id: "a", layer: "symbol", kind: "pump", tag: "RC-P01", unknown: false, kind_label: "펌프" },
    { id: "b", layer: "symbol", kind: "control_valve", tag: "RC-V01", unknown: false, kind_label: "제어 밸브" },
    { id: "c", layer: "symbol", kind: null, tag: null, unknown: true },
    { id: "d", layer: "symbol", kind: "off_page_connector", tag: null, unknown: false },
    { id: "e", layer: "symbol", kind: "off_page_connector", tag: null, unknown: false },
    { id: "p1", layer: "pipe", tag: "RC-L030", unknown: false },
    { id: "p2", layer: "pipe", tag: "RC-L031", unknown: true },
    { id: "t1", layer: "tag", tag: "RC-P01" },
    { id: "f", layer: "symbol", kind: "sensor", tag: null, unknown: false },
    { id: "g", layer: "symbol", kind: "valve", tag: "RC-V09", unknown: false },
  ],
  links: [{ id: "d", status: "linked", peer_graph_id: "G2", peer_id: "x" }, { id: "e", status: "missing_peer", peer_graph_id: "G9", peer_id: null }],
};
const CLEAN_REASONS = { unconfirmed: [{ id: "f", reason: "unknown_symbol" }, { id: "g", reason: "open_end" }, { id: "a", reason: "flow_direction" }] };
const CLEAN = { items: { p1: { ends: [{ node: "a", status: "connected" }, { node: "b", status: "connected" }] }, p2: { ends: [{ node: "b", status: "connected" }, { node: null, status: "open" }] } } };

export const tests = [
  { name: "추출 확인 창: 읽은 기호·도면 연결·읽지 못한 기호·끊긴 연결(열린 끝 배관, 이어지지 않은 도면 연결)을 서로 다른 색으로 나눈다", run(assert) {
    const g = extractGroups(SHEET, CLEAN_REASONS);
    assert.equal(g.counts, { ok: 2, link: 1, unknown: 2, broken: 3 });
    const by = Object.fromEntries(g.mark.groups.map((x) => [x.style, x.ids]));
    assert.equal(by.focus, ["a", "b"]);
    assert.equal(by.path, ["d"]);
    assert.equal(by.warn, ["c", "f"]);
    assert.equal(by.cause, ["e", "p2", "g"]);
    assert.equal(g.mark.op, "mark");
    assert(g.mark.dim_others === false, "다른 것을 흐리게 하지 않는다");
    assert(!JSON.stringify(g).includes("t1"), "글자(태그) 층은 칠하지 않는다");
    assert.equal(LEGEND.map((l) => l.text), ["읽음", "도면 연결", "읽지 못함", "끊긴 연결"]);
  } },
  { name: "추출 확인 창: 자료가 비었으면 표시가 없다", run(assert) {
    assert.equal(extractGroups(null).mark, null);
    assert.equal(extractGroups({ items: [] }).mark, null);
  } },
  { name: "구성요소 속성: 기호는 이어진 배관과 그 반대쪽 기기를 태그로, 배관은 양 끝의 기기를 보인다", run(assert) {
    assert.equal(neighborsOf("a", SHEET, CLEAN), ["RC-L030 → RC-V01"]);
    assert.equal(neighborsOf("b", SHEET, CLEAN), ["RC-L030 → RC-P01", "RC-L031"]);
    assert.equal(neighborsOf("p1", SHEET, CLEAN), ["RC-P01", "RC-V01"]);
    assert.equal(neighborsOf("zz", SHEET, CLEAN), []);
    assert.equal(neighborsOf("a", SHEET, null), []);
  } },
  { name: "구성요소 속성: 든 구간은 구간 번호와 이름", run(assert) {
    const view = { segments: [{ node_id: "S1", name: "냉각수 루프", ids: ["a", "b"] }, { node_id: "S2", name: null, ids: ["b"] }] };
    assert.equal(segmentsOf("b", view), ["S1 냉각수 루프", "S2"]);
    assert.equal(segmentsOf("c", view), []);
    assert.equal(segmentsOf("a", null), []);
  } },
];
