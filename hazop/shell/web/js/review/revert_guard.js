// 되돌리기 전 확인(입력 연산 U2 §11.6). AI 후보 수락에 기대 사람이 한 고침이 있으면 엔진은 그 목록(confirm)을 받아야만 되돌린다.
// 대기열 Z와 AI 검토 패널의 되돌리기가 같은 함수를 쓴다: 엔진의 미리 알림(aireview/<도면>/revert?ids=)을 읽어, 사람 고침이 있으면
// "이 수락에 기대 사람이 한 고침 n건이 함께 빠집니다"를 보이고 확인받은 목록을 돌려준다. Enter = 되돌리기, Esc = 그만두기.
import { html } from "../ui/html.js";
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore } from "../store.js";
import { read } from "../bridge.js";

export const guard = createStore({ ask: null });      // {text, confirm, resolve}

export const asking = () => !!guard.get().ask;

/** → {confirm: [op_id]}(되돌려도 됨) 또는 null(사람이 그만둠). 사람 고침이 없으면 묻지 않는다. 미리 알림을 못 읽으면 빈 목록으로
 *  보낸다: 엔진이 기댄 고침을 보면 needs_confirm으로 거절하고 아무것도 지우지 않는다(조용히 지워지지 않음). */
export async function confirmRevert(gid, candIds) {
  let p = null;
  try { p = await read("aireview/" + encodeURIComponent(gid) + "/revert?ids=" + encodeURIComponent((candIds || []).join(","))); } catch (e) { p = null; }
  if (!p || !p.human) return { confirm: [], text: p ? p.text : "" };
  return new Promise((resolve) => guard.set({ ask: { text: p.text, confirm: p.confirm, resolve } }));
}

export function answer(yes) {
  const a = guard.get().ask;
  if (!a) return;
  guard.set({ ask: null });
  a.resolve(yes ? { confirm: a.confirm, text: a.text } : null);
}

function useAsk() {
  const [v, setV] = useState(() => guard.get().ask);
  useLayoutEffect(() => guard.subscribe((s) => setV(s.ask)), []);
  return v;
}

export function RevertGuard() {
  const a = useAsk();
  useLayoutEffect(() => {
    if (!a) return undefined;
    const b = document.querySelector(".rg-modal .btn.primary");
    if (b) b.focus();
    const key = (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); answer(false); }
      else if (e.key === "Enter" && !(e.target && e.target.closest && e.target.closest(".rg-modal button:not(.primary)"))) { e.preventDefault(); e.stopImmediatePropagation(); answer(true); }
      else if (e.key.length === 1) { e.stopImmediatePropagation(); }        // 대기열 키(A·R·Z…)가 확인 중에 먹지 않게
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, [a]);
  if (!a) return null;
  return html`<div class="rv-back" onClick=${() => answer(false)}><div class="rv-modal rg-modal" role="dialog" aria-modal="true" aria-label="되돌리기 확인" onClick=${(ev) => ev.stopPropagation()}>
    <h3>함께 빠지는 고침이 있습니다</h3><div>${a.text}</div><div class="muted small">되돌리면 이 고침도 도면 수정 기록에서 빠집니다.</div>
    <div class="acts"><button type="button" class="btn primary" onClick=${() => answer(true)}>함께 되돌리기 Enter</button>
      <button type="button" class="btn" onClick=${() => answer(false)}>그만두기 Esc</button></div></div></div>`;
}
