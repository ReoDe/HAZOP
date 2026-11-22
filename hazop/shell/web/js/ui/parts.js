// 작은 부품: 단추, 칩, 알림 띠, 스위치(규격 §4.4). 접근 이름(aria-label)은 호출하는 쪽이 준다.
import { html } from "./html.js";
import { Icon } from "./icon.js";

export function Btn({ kind = "", sm = false, icon, label, title, onClick, disabled, children, cls = "" }) {
  const c = ["btn", kind, sm ? "sm" : "", icon && !children ? "icon" : "", cls].filter(Boolean).join(" ");
  return html`<button type="button" class=${c} title=${title || label} aria-label=${label || title} disabled=${disabled} onClick=${onClick}>
    ${icon ? html`<${Icon} name=${icon} size=${sm ? 15 : 18} />` : null}${children}</button>`;
}

export function Chip({ kind = "", icon, title, onClick, children }) {
  const c = ["chip", kind].filter(Boolean).join(" ");
  if (onClick) {
    return html`<button type="button" class=${c} title=${title} onClick=${onClick}>${icon ? html`<${Icon} name=${icon} size=${14} />` : null}${children}</button>`;
  }
  return html`<span class=${c} title=${title}>${icon ? html`<${Icon} name=${icon} size=${14} />` : null}${children}</span>`;
}

export function Notice({ kind = "info", icon = "info-circle", children }) {
  return html`<div class=${"notice " + kind} role=${kind === "err" ? "alert" : "status"}><${Icon} name=${icon} size=${15} /><div>${children}</div></div>`;
}

export function Switch({ on, label, onChange }) {
  return html`<button type="button" role="switch" aria-checked=${on ? "true" : "false"} aria-label=${label} class=${"switch" + (on ? " on" : "")}
    style="border:0;padding:0;cursor:pointer" onClick=${() => onChange(!on)}></button>`;
}
