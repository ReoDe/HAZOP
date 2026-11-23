// 닫을 수 있는 알림 줄(INTENT §3.8). 사람이 처리하면(그 자리로 가거나 닫으면) 사라지고, 같은 글은 닫은 뒤 다시 띄우지 않는다. 사라지는 알림(토스트)과 달리 처리할 때까지 남는다.
// 지금은 '다시 추출 뒤 찾지 못한 구성요소'가 쓴다: 엔진의 study.lost 사건이나 프로젝트를 열 때 읽은 확인 필요(idmap.needs_check)가 만든다.
import { html } from "./ui/html.js";
import { store, useStore } from "./store.js";
import { read } from "./bridge.js";
import { Icon } from "./ui/icon.js";
import { focusNode } from "./panels/nodes_state.js";
import { demotedNoticeText, lostNoticeText } from "./panels/nodes_logic.js";

// 닫은 알림(id|판|글). 글이 바뀌거나, 같은 글이라도 도면이 다시 읽혀 판(key)이 바뀌면 새 알림이다(같은 수를 새로 잃어도 다시 알린다)
const closed = new Set();
const keyOf = (n) => n.id + "|" + (n.key || "") + "|" + n.text;

export function addNotice(n) {
  if (closed.has(keyOf(n))) return;
  store.set((s) => ({ notices: s.notices.filter((x) => x.id !== n.id).concat(n) }));
}

export function dismissNotice(id) {
  const n = store.get().notices.find((x) => x.id === id);
  if (n) closed.add(keyOf(n));
  store.set((s) => ({ notices: s.notices.filter((x) => x.id !== id) }));
}

/** 알림을 없앤다(처리돼서 더는 필요 없을 때). 닫은 기록은 남기지 않는다. */
export function clearNotice(id) { store.set((s) => ({ notices: s.notices.filter((x) => x.id !== id) })); }

/** 찾지 못한 구성요소 알림: 그 글과 '그 자리로'(구간 패널을 열고 첫 구간을 고른다). */
export function lostNotice(info) {
  const text = lostNoticeText(info);
  if (!text) return null;
  return { id: "lost", key: info.graph_version || "", kind: "warn", text, action: { label: "그 자리로", run: () => { store.set({ panel: "nodes" }); if (info.first_node) focusNode(info.first_node); } } };
}

/** 확정을 푼 구간 알림(study.lost 사건의 demoted). 첫 구간으로 가는 단추. */
export function demotedNotice(info) {
  const ids = (info && info.demoted) || [];
  const text = demotedNoticeText(ids);
  if (!text) return null;
  return { id: "demoted", key: info.graph_version || "", kind: "warn", text, action: { label: "그 자리로", run: () => { store.set({ panel: "nodes" }); focusNode(ids[0]); } } };
}

/** 읽어 온 확인 필요(구간 목록의 check)로 알림을 맞춘다: 있으면 띄우고(닫은 글은 빼고) 없어졌으면 지운다. 읽기 실패는 조용히 넘어간다. */
export async function refreshLostNotice() {
  try {
    const l = await read("nodes");
    const c = l && l.check;
    const lm = (c && c.lost_members) || {};
    const info = c && c.needs_check ? { sections: Object.keys(lm).length, members: Object.values(lm).reduce((a, b) => a + b, 0), first_node: Object.keys(lm)[0] || null,
      generic: !Object.keys(lm).length, graph_version: l.graph_version || "" } : null;      // 찾지 못한 것 없이 확인만 필요하면(옛 판 이전 기록 등) 일반 안내
    const n = info ? lostNotice(info) : null;
    if (n) addNotice(n); else clearNotice("lost");
  } catch (e) { /* 알림은 덤이다 */ }
}

export function Notices() {
  const list = useStore((s) => s.notices);
  if (!list.length) return null;
  return html`<div class="notice-bar" role="region" aria-label="알림">${list.map((n) => html`<div class=${"notice-row " + (n.kind || "info")} key=${n.id} role="status">
    <${Icon} name="alert-triangle" size=${15} /><span class="nt">${n.text}</span>
    ${n.action ? html`<button type="button" class="btn sm primary" onClick=${() => { n.action.run(); dismissNotice(n.id); }}>${n.action.label}</button>` : null}
    <button type="button" class="btn ghost sm" aria-label="알림 닫기" title="닫기" onClick=${() => dismissNotice(n.id)}>닫기</button></div>`)}</div>`;
}
