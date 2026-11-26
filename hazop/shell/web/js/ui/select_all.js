// 목록 맨 위의 '전체 선택': 고를 수 있는 줄이 모두 골라졌으면 켜짐, 일부만이면 중간 상태. 누르면 모두 고르고, 모두 골라진 때는 모두 해제한다.
import { html } from "./html.js";
import { useLayoutEffect, useRef } from "../../vendor/hooks.module.js";

/** ids: 지금 보이는 줄 가운데 고를 수 있는 것, picked: 지금 고른 것, onChange(고를 것 목록, 켬인지). */
export function SelectAll({ ids, picked, label, onChange }) {
  const box = useRef(null);
  const on = ids.length > 0 && ids.every((x) => picked.includes(x));
  const some = !on && ids.some((x) => picked.includes(x));
  useLayoutEffect(() => { if (box.current) { box.current.checked = on; box.current.indeterminate = some; } });
  return html`<label class="selall small muted"><input type="checkbox" ref=${box} aria-label=${label} disabled=${!ids.length} onChange=${() => onChange(ids, !on)} /> 전체 선택</label>`;
}
