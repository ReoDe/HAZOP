// 도면 탭의 추출 확인 창(web/js/canvas/extract_check.js, 화면 단순화 B): 무엇을 어떤 색으로 칠할지와 구성요소 속성 글.
import { LEGEND, extractGroups, neighborsOf, segmentsOf } from "../js/canvas/extract_check.js";
import { resolveMark, styleColor } from "../js/canvas/marks.js";
import { viewRect } from "../js/sheet_host.js";
import { syncInputsNotice } from "../js/next/next.js";
import { store } from "../js/store.js";
import { deliver } from "../js/bridge.js";
import * as D from "../js/panels/docs_state.js";

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
  { name: "도면 위 말풍선은 보기(이동·확대)를 따라간다: 누른 때의 자리를 지금 보기로 옮긴다", run(assert) {
    const r = viewRect({ x: 100, y: 50, w: 20, h: 10 }, { x: 10, y: 10, k: 1 }, { x: 40, y: 20, k: 2 });
    assert.equal(r, { x: (100 - 10) * 2 + 40, y: (50 - 10) * 2 + 20, w: 40, h: 20 });
    assert.equal(viewRect({ x: 1, y: 1 }, null, { x: 0, y: 0, k: 1 }), null);
  } },
  { name: "추출 확인 창: 색은 셋(읽음·읽지 못함·AI 후보 있음). 끊긴 연결은 읽지 못함에, 도면 연결은 읽음에 든다", run(assert) {
    const g = extractGroups(SHEET, CLEAN_REASONS);
    assert.equal(g.counts, { ok: 3, unknown: 5, ai: 0 });
    const by = Object.fromEntries(g.mark.groups.map((x) => [x.style, x.ids]));
    assert.equal(by["chk-ok"], ["a", "b", "d"]);
    assert.equal(by["chk-unknown"], ["c", "e", "p2", "f", "g"]);
    assert(g.mark.groups.every((x) => x.thin === true), "가는 테두리")
    assert.equal(g.mark.op, "mark");
    assert(g.mark.dim_others === false, "다른 것을 흐리게 하지 않는다");
    assert(!JSON.stringify(g).includes("t1"), "글자(태그) 층은 칠하지 않는다");
    assert.equal(LEGEND.map((l) => l.text), ["읽음", "읽지 못함", "AI 후보 있음"]);
    assert(LEGEND.length <= 5, "범례 색은 다섯을 넘지 않는다");
  } },
  { name: "추출 확인 창: 추적·강조 색(focus·path·cause·warn)과 다른 색, 그리는 쪽은 가는 선(차단 1)", run(assert) {
    const hl = ["focus", "path", "cause", "warn", "safeguard", "muted"].map(styleColor);
    for (const l of LEGEND) assert(!hl.includes(styleColor(l.style)), l.style + "가 강조 색과 겹침");
    const index = { byId: new Map([["a", [{ id: "a", layer: "symbol", rect: { x0: 0, y0: 0, x1: 10, y1: 10 } }]]]) };
    const r = resolveMark({ id: "extract-check", op: "mark", groups: [{ ids: ["a"], style: "chk-ok", thin: true }] }, index);
    assert(r.items.length === 1 && r.items[0].thin === true, "가는 선 표시");
    const r2 = resolveMark({ id: "q", op: "mark", groups: [{ ids: ["a"], style: "focus" }] }, index);
    assert(!r2.items[0].thin, "채팅 강조는 굵은 선 그대로");
  } },
  { name: "추출 확인 창: 한 기호에 사유가 여럿이어도 한 색이다", run(assert) {
    const sheet = { items: [{ id: "x", layer: "symbol", unknown: false }] };
    const clean = { unconfirmed: [{ id: "x", reason: "unknown_symbol" }, { id: "x", reason: "open_end" }] };
    assert.equal(extractGroups(sheet, clean).counts, { ok: 0, unknown: 1, ai: 0 });
    const clean2 = { unconfirmed: [{ id: "x", reason: "flow_direction" }] };
    assert.equal(extractGroups(sheet, clean2).counts, { ok: 1, unknown: 0, ai: 0 });
  } },
  { name: "추출 확인 창: AI가 기호 아님이라 본 것·수락 전 후보·자동으로 채운 것은 AI 후보 있음 한 색이고 읽지 못함보다 앞선다", run(assert) {
    const sheet = { items: [{ id: "n", layer: "symbol", unknown: true }, { id: "f", layer: "symbol", unknown: false, kind: "valve" }, { id: "c", layer: "symbol", unknown: true }, { id: "o", layer: "symbol", unknown: false, kind: "pump" }] };
    const clean = { unconfirmed: [{ id: "c", reason: "ai_candidate" }], items: { n: { ai_answer: "not_symbol", review: "script" }, f: { review: "ai_auto" }, c: { review: "ai_candidate" }, o: { review: "script" } } };
    const g = extractGroups(sheet, clean);
    const by = Object.fromEntries(g.mark.groups.map((x) => [x.style, x.ids]));
    assert.equal(by["chk-ai"], ["n", "f", "c"]);
    assert.equal(by["chk-ok"], ["o"]);
    assert(!by["chk-unknown"], "AI 후보가 있으면 읽지 못함 칸에 겹쳐 세지 않는다");
    const cols = LEGEND.map((l) => styleColor(l.style));
    assert.equal(new Set(cols).size, cols.length, "범례 색이 모두 다르다");
  } },
  { name: "수락했지만 도면에 반영하지 않은 입력 연산이 남으면 알림 줄에 '다시 읽기' 한 줄, 없어지면 지운다(차단 2)", run(assert) {
    store.set({ notices: [] });
    const item = { kind: "inputs_pending", count: 2, action: { label: "다시 읽기", go: "confirm:inputs.build", target: "G1" } };
    syncInputsNotice([item]);
    const n = store.get().notices.find((x) => x.id === "inputs-pending");
    assert(n && n.text === "수락한 내용이 아직 반영되지 않은 도면 2장" && n.action.label === "다시 읽기", JSON.stringify(store.get().notices));
    syncInputsNotice([]);
    assert(!store.get().notices.some((x) => x.id === "inputs-pending"), "처리되면 지움");
  } },
  { name: "문서 작업 결과의 지식그래프 재확인 글(kg_notes)은 경고 한 줄로 남고, 끝났다는 글은 없다(차단 3)", async run(assert) {
    window.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
    window.hazopBridge = { send(text) { const m = JSON.parse(text); if (m.t !== "cmd") return;
      Promise.resolve().then(() => deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data: { job: "jd1" } }))); }, setHandler() {} };
    D.wire();
    await D.extractAgain("m1");
    deliver(JSON.stringify({ t: "event", name: "job.done", data: { id: "jd1", label: "추출", result: { counts: { items: 3 }, kg_notes: ["확인한 조각 언급 2건이 다시 후보가 됨"] } } }));
    await new Promise((r) => setTimeout(r, 50));
    assert.equal(D.docs.get().notice, "확인한 조각 언급 2건이 다시 후보가 됨");
    await D.extractAgain("m1");
    deliver(JSON.stringify({ t: "event", name: "job.done", data: { id: "jd1", label: "추출", result: { counts: { items: 3 }, kg_notes: [] } } }));
    await new Promise((r) => setTimeout(r, 50));
    assert.equal(D.docs.get().notice, null, "알릴 것이 없으면 글이 없다");
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
