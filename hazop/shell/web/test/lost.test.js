// 확인 필요 알림 글(찾지 못한 구성요소·참조 확인 필요): 엔진이 센 값으로만 만들고 묘비 id를 글에 쓰지 않는다.
import { checkText, lostText } from "../js/panels/nodes_logic.js";

export const tests = [
  { name: "확인 필요: 구간 행 글은 '찾지 못한 구성요소 n개 · 참조 확인 필요 m건'이고 없는 것은 뺀다", run(assert) {
    assert.equal(lostText(2, 3), "찾지 못한 구성요소 2개 · 참조 확인 필요 3건");
    assert.equal(lostText(1, 0), "찾지 못한 구성요소 1개");
    assert.equal(lostText(0, 4), "참조 확인 필요 4건");
    assert.equal(lostText(0, 0), "");
  } },
  { name: "확인 필요: 프로젝트 한 줄은 합계와 구간 수를 쓰고 확인할 것이 없으면 빈 글이다", run(assert) {
    const c = { needs_check: true, lost_members: { S1: 2, S2: 1 }, lost_refs: { S1: 3 }, tombstones: 3, unverified: false, unregistered: [] };
    const t = checkText(c);
    assert(t.includes("찾지 못한 구성요소 3개") && t.includes("참조 확인 필요 3건") && t.includes("구간 2개"), t);
    assert(!t.includes("lost:"), "묘비 id가 글에 없다");
    assert.equal(checkText({ needs_check: false }), "");
    assert.equal(checkText(null), "");
    assert(checkText({ needs_check: true, lost_members: {}, lost_refs: {}, unverified: true, unregistered: [] }).length > 0, "표시 없이 이은 판 이전만 있어도 안내한다");
  } },
];
