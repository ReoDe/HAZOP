// 무엇을 눌러 도면의 구성요소를 '찾아가는' 모든 길이 쓰는 한 곳. 확대하지 않는다:
// 도면 한 장 전체가 가운데에 맞은 보기를 두고(다른 도면이면 그 도면을 그렇게 열고), 걸려 있던 강조(구간 고름·Ctrl 고름·앞선 일시 강조·말풍선)를
// 풀어 기본 모습으로 돌린 뒤 누른 대상만 일시 강조한다. 일시 강조는 바깥 누름·Esc로 풀린다(sheet_host.js가 useLightDismiss로). 시간으로는 사라지지 않는다.
import { store } from "./store.js";
import { cmd } from "./bridge.js";
import * as N from "./panels/nodes_state.js";
import { openSheet } from "./panels/results_state.js";
import { closeBubble, setLocator } from "./canvas/clean_ui.js";

const NONE = () => ({ rid: null, bySheet: {} });
let seq = 0;

/** 걸려 있는 강조·고름·말풍선을 모두 푼다. */
export function resetHighlights() {
  N.unfocus();
  N.clearSelection();
  closeBubble();
  store.set({ marks: NONE(), bubble: null });
}

export const clearTempHighlight = () => store.set({ marks: NONE() });

const fitSheet = () => store.set((s) => ({ command: { seq: s.command.seq + 1, type: "fit" } }));

/** 도면을 전체 맞춤으로 보인다: 다른 도면이면 연다(새 도면은 도면 부품이 전체 맞춤으로 연다), 같은 도면이면 fit일 때 다시 맞춘다. */
function showSheet(target, fit) {
  if (!target) return;
  if (store.get().sheet === target) { if (fit) fitSheet(); return; }
  if (!openSheet(target)) { store.set({ sheet: target }); cmd("sheet.open", { graph_id: target }).catch(() => {}); }
}

/**
 * 대상으로 간다. sheet: 대상 도면(없으면 지금 도면). ids: 강조할 구성요소. marks: 도면별 표시(경로의 차례 번호 등)가 있으면 그것을 그린다.
 * rid: 표시 묶음 이름. patch: 함께 바꿀 화면 상태(패널·돌아가기 칩). fit: 같은 도면에서 전체 맞춤 명령을 보낼지(뒤에 다른 명령을 보낼 때 끈다).
 */
export function locate({ sheet = null, ids = [], marks = null, rid = null, patch = null, fit = true } = {}) {
  resetHighlights();
  const target = sheet || store.get().sheet;
  showSheet(target, fit);
  if (patch) store.set(patch);
  const bySheet = marks && Object.keys(marks).length ? marks
    : (ids.length && target ? { [target]: [{ op: "mark", groups: [{ ids: ids.slice(0, 400), style: "focus" }], dim_others: true, center: false }] } : {});
  store.set({ marks: Object.keys(bySheet).length ? { rid: rid || "locate-" + (++seq), bySheet } : NONE() });
  return true;
}

setLocator(locate);
