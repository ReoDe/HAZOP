// 답 카드 그리기(규격 §3.2, 채팅 규격 §5). 검사와 경고 계산은 엔진(hazop/chat/card.py)이 끝냈고 여기서는 받은 값을 그리기만 한다.
// 모델·도면에서 온 글은 모두 ${} 자리표시자로만 넣는다(텍스트로만 들어가며 HTML로 해석되지 않는다).
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { Icon } from "../ui/icon.js";
import { Chip } from "../ui/parts.js";

const FOLD = { limit: 12, head: 5, tail: 5 };

function foldChips(chips, expanded) {
  if (expanded || chips.length <= FOLD.limit) return chips.map((c, i) => ({ chip: c, n: i + 1 }));
  const head = chips.slice(0, FOLD.head).map((c, i) => ({ chip: c, n: i + 1 }));
  const tail = chips.slice(-FOLD.tail).map((c, i) => ({ chip: c, n: chips.length - FOLD.tail + i + 1 }));
  return [...head, { fold: chips.length - FOLD.head - FOLD.tail }, ...tail];
}

function Steps({ path, onChip }) {
  const [open, setOpen] = useState(false);
  return html`<div class="path">
    <div class="muted" style="font-size:var(--fs-xs);margin-bottom:2px"><${Icon} name="route" size=${14} /> ${path.label}</div>
    <ol class="steps">
      ${foldChips(path.chips, open).map((it) => it.fold !== undefined
        ? html`<li><button type="button" class="btn ghost sm" onClick=${() => setOpen(true)}>… ${it.fold}개 더 보기</button></li>`
        : html`<li>
            <span class="n">${it.n}</span>
            <${Chip} kind=${"id" + (it.chip.warn ? " warn" : "")} title=${it.chip.sheet || ""} onClick=${() => onChip(it.chip)}>${it.chip.tag}<//>
            ${it.chip.via ? html`<span class="muted" style="font-size:var(--fs-xs)">${it.chip.via}</span>` : null}
            ${it.chip.warn ? html`<span class="w" title="미확인 항목"><${Icon} name="alert-triangle" size=${14} /></span>` : null}
          </li>`)}
    </ol></div>`;
}

export function AnswerCard({ card, footer, onChip, onSheet }) {
  const [showCalls, setShowCalls] = useState(false);
  const notes = card.notes || [];
  return html`<div class="ans">
    ${card.no_evidence ? html`<div class="muted" style="font-size:var(--fs-xs)">도면·문서에서 확인한 내용 없음</div>`
      : (card.badges.length ? html`<div class="meta">${card.badges.map((b) => html`<${Chip} key=${b}>${b}<//>`)}</div>` : null)}
    ${card.text ? html`<div class="src"><div class="lbl"><${Icon} name="circle-check" size=${14} /> 도면에서 확인</div><p style="white-space:pre-wrap">${card.text}</p></div>` : null}
    ${card.paths.map((p, i) => html`<div key=${i}><${Steps} path=${p} onChip=${onChip} />
      <div class="sheets" style="margin-top:6px">${p.sheets.map(([sheet, n]) => html`<${Chip} key=${sheet} kind="accent" icon="ruler-2" title="이 도면을 열고 경로를 표시합니다"
        onClick=${() => onSheet(i, sheet)}>${(p.sheet_labels && p.sheet_labels[sheet]) || sheet} · ${n}<//>`)}</div></div>`)}
    ${card.path_notes.map((n, i) => html`<div class="muted" key=${i} style="font-size:var(--fs-xs)">${n}</div>`)}
    ${card.warnings.map((w) => html`<div class="warnline" key=${w.reason} title=${(w.labels || []).slice(0, 20).join(", ")}>
      <${Icon} name="alert-triangle" size=${15} /><span>${w.scope === "path" && w.reason !== "valve_position_ignored" ? "경로에 " : ""}${w.text}</span></div>`)}
    ${card.model_warnings.map((w, i) => html`<div class="muted" key=${i} style="font-size:var(--fs-xs)">AI가 덧붙인 주의: ${w}</div>`)}
    ${card.general ? html`<div class="src general"><div class="lbl"><${Icon} name="sparkles" size=${14} /> AI의 일반 지식 · 도면에서 확인 안 함</div><p style="white-space:pre-wrap">${card.general}</p></div>` : null}
    <div class="meta">
      <span>도구 ${footer.tools}회 · ${footer.model} · ${footer.seconds}초${notes.length ? " · " + notes.join(" · ") : ""}</span>
      ${footer.calls && footer.calls.length ? html`<button type="button" class="btn ghost sm" onClick=${() => setShowCalls(!showCalls)}>근거 보기<${Icon} name=${showCalls ? "chevron-up" : "chevron-down"} size=${12} /></button>` : null}
    </div>
    ${showCalls ? html`<div class="muted mono" style="white-space:pre-wrap;font-size:var(--fs-xs)">${footer.calls.map(([n, a]) => n + " " + JSON.stringify(a).slice(0, 200)).join("\n")}</div>` : null}
  </div>`;
}
