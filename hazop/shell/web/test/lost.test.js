// 확인 필요 알림 글(찾지 못한 구성요소·다시 확인할 곳): 엔진이 센 값으로만 만들고 묘비 id를 글에 쓰지 않는다.
import { catchUpText, checkText, discardLabel, lostNoticeText, lostText } from "../js/panels/nodes_logic.js";
import { store } from "../js/store.js";
import { addNotice, clearNotice, dismissNotice, lostNotice } from "../js/notices.js";

export const tests = [
  { name: "확인 필요: 구간 행 글은 '찾지 못한 구성요소 n개 · 다시 확인할 곳 m건'이고 없는 것은 뺀다", run(assert) {
    assert.equal(lostText(2, 3), "찾지 못한 구성요소 2개 · 다시 확인할 곳 3건");
    assert.equal(lostText(1, 0), "찾지 못한 구성요소 1개");
    assert.equal(lostText(0, 4), "다시 확인할 곳 4건");
    assert.equal(lostText(0, 0), "");
  } },
  { name: "확인 필요: 프로젝트 한 줄은 합계와 구간 수를 쓰고 확인할 것이 없으면 빈 글이다", run(assert) {
    const c = { needs_check: true, lost_members: { S1: 2, S2: 1 }, lost_refs: { S1: 3 }, tombstones: 3, unverified: false, unregistered: [] };
    const t = checkText(c);
    assert(t.includes("찾지 못한 구성요소 3개") && t.includes("다시 확인할 곳 3건") && t.includes("구간 2개"), t);
    assert(!t.includes("lost:"), "묘비 id가 글에 없다");
    assert.equal(checkText({ needs_check: false }), "");
    assert.equal(checkText(null), "");
    assert(checkText({ needs_check: true, lost_members: {}, lost_refs: {}, unverified: true, unregistered: [] }).length > 0, "표시 없이 이은 이력만 있어도 안내한다");
  } },
  { name: "판 이전 지금 하기: 끝난 알림은 이어진 수와 찾지 못한 구성요소 수를 쓰고, 같은 판이면 할 것이 없다고 한다", run(assert) {
    const t = catchUpText({ changed: true, matched: 7, tombstones: 2 });
    assert(t.startsWith("도면 변경을 반영했습니다") && t.includes("이어진 구성요소 7개") && t.includes("찾지 못한 구성요소 2개"), t);
    assert(!catchUpText({ changed: true, matched: 3, tombstones: 0 }).includes("찾지 못한"), "묘비가 없으면 말하지 않는다");
    assert(catchUpText({ changed: false }).includes("이미 도면의 최신 모습으로 반영"), "같은 판");
  } },
  { name: "알림: 다시 추출 뒤 글은 '찾지 못한 구성요소 n개'(한 줄과 같은 단위)이고 확인할 곳이 없으면 비어 있다", run(assert) {
    const t = lostNoticeText({ sections: 3, members: 5 });
    assert.equal(t, "도면이 바뀌어 찾지 못한 구성요소 5개를 다시 확인해야 합니다(검토구간 3곳).", "한 줄과 같은 단위(실제 창 3차 결함 6)");
    assert.equal(lostNoticeText({ sections: 2, members: 0 }), "도면이 바뀌어 검토구간 2곳을 다시 확인해야 합니다.");
    assert.equal(lostNoticeText({ sections: 0, members: 0 }), "");
    assert(!/lost:|묘비|판 이전|stale/.test(t), "내부 말이 없다");
  } },
  { name: "알림: 그 자리로 단추가 있고, 닫으면 사라지며 같은 글은 다시 띄우지 않는다(글이 바뀌면 새 알림)", run(assert) {
    store.set({ notices: [] });
    const n = lostNotice({ sections: 2, members: 2, first_node: "S1" });
    assert.equal(n.action.label, "그 자리로");
    addNotice(n);
    assert.equal(store.get().notices.length, 1);
    dismissNotice("lost");
    assert.equal(store.get().notices.length, 0);
    addNotice(n);
    assert.equal(store.get().notices.length, 0, "닫은 글은 다시 띄우지 않는다");
    addNotice(lostNotice({ sections: 3, members: 4, first_node: "S1" }));
    assert.equal(store.get().notices.length, 1, "글이 바뀌면 새 알림");
    clearNotice("lost");
    assert.equal(store.get().notices.length, 0, "처리돼 없어지면 사라진다");
  } },
  { name: "알림: 닫은 기억은 판까지 묶는다(다시 추출해 같은 수를 새로 잃으면 다시 알린다)", run(assert) {
    store.set({ notices: [] });
    const v1 = lostNotice({ sections: 1, members: 1, first_node: "S1", graph_version: "v-1" });
    addNotice(v1);
    dismissNotice("lost");
    addNotice(lostNotice({ sections: 1, members: 1, first_node: "S1", graph_version: "v-1" }));
    assert.equal(store.get().notices.length, 0, "같은 판의 같은 글은 다시 띄우지 않는다");
    addNotice(lostNotice({ sections: 1, members: 1, first_node: "S1", graph_version: "v-2" }));
    assert.equal(store.get().notices.length, 1, "새 판이면 같은 글도 다시 알린다");
    clearNotice("lost");
  } },
  { name: "알림: 찾지 못한 것 없이 확인만 필요하면 일반 안내를 띄운다", run(assert) {
    const t = lostNoticeText({ sections: 0, members: 0, generic: true });
    assert(t.includes("확인이 필요한 것이 있습니다"), t);
    assert(!/lost:|묘비|판 이전|그래프 판/.test(t), "내부 말이 없다");
  } },

];
