// '모두 확정' 확인 카드(HZ-DSN-06 U9). 구간 패널 안에서는 패널 속 카드로, 패널이 닫혀 있으면('다음에 할 일' 한 줄에서 바로) 도면 위 창으로 같은 카드를 보인다.
// 확정은 카드를 열 때 붙잡은 판으로만 보낸다(nodes_state.confirmMany). Enter = 확정, Esc = 취소.
import { html } from "../ui/html.js";
import { useLayoutEffect } from "../../vendor/hooks.module.js";
import { useStore } from "../store.js";
import { Btn } from "../ui/parts.js";
import * as N from "./nodes_state.js";

export function ConfirmAllCard() {
  const confirmAsk = N.useNodes((s) => s.confirmAsk);
  const list = N.useNodes((s) => s.list);
  const busy = N.useNodes((s) => s.busy);
  if (!confirmAsk) return null;
  return html`<div class="card confirm-all" role="dialog" aria-label="여러 구간 확정"><b>${confirmAsk.length}개 구간을 확정할까요?</b>
    <ul class="tight">${confirmAsk.slice(0, 12).map((id) => { const n = list.nodes.find((x) => x.node_id === id); return html`<li key=${id}>${id} ${n ? n.name : ""}${n && n.lost ? html` <span class="chip warn">찾지 못한 구성요소 ${n.lost}개</span>` : null}</li>`; })}
      ${confirmAsk.length > 12 ? html`<li class="muted">그 밖에 ${confirmAsk.length - 12}개</li>` : null}</ul>
    <div class="acts-row"><${Btn} sm=${true} kind="primary" label="이 구간들 확정" disabled=${busy} onClick=${() => N.confirmMany(confirmAsk)}>확정<//>
      <${Btn} sm=${true} label="확정하지 않기" onClick=${N.cancelConfirmAll}>취소<//></div></div>`;
}

/** 구간 패널이 닫혀 있을 때 도면 위 창. */
export function ConfirmAllModal() {
  const panel = useStore((s) => s.panel);
  const confirmAsk = N.useNodes((s) => s.confirmAsk);
  const on = !!confirmAsk && panel !== "nodes";
  useLayoutEffect(() => {
    if (!on) return undefined;
    const b = document.querySelector(".na-modal .btn.primary");
    if (b) b.focus();
    const key = (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); N.cancelConfirmAll(); }
      else if (e.key === "Enter" && !e.ctrlKey && !(e.target && e.target.closest && e.target.closest(".na-modal button:not(.primary)"))) {
        e.preventDefault(); e.stopImmediatePropagation(); if (!N.nodes.get().busy) N.confirmMany(N.nodes.get().confirmAsk);
      }
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, [on]);
  if (!on) return null;
  return html`<div class="rv-back" onClick=${N.cancelConfirmAll}><div class="rv-modal na-modal" onClick=${(ev) => ev.stopPropagation()}><${ConfirmAllCard} /></div></div>`;
}
