// 새 화면의 진입점(규격 §2.1): 왼쪽 메뉴 · 위 막대 · 가운데 도면 · 오른쪽 채팅, 메뉴에서 여는 패널 하나.
// 저장하는 자료는 엔진만 쓴다. 여기서는 보기 상태(열린 패널, 보는 도면, 채팅 접힘, 도면 표시)만 갖고 엔진의 바뀜 알림을 받아 다시 읽는다.
import { html, render } from "./ui/html.js";
import { useEffect, useState } from "../vendor/hooks.module.js";
import { store, useStore } from "./store.js";
import { cmd, connect, on, onChanged, read, setProject, ui } from "./bridge.js";
import { Icon, loadIcons } from "./ui/icon.js";
import { Btn } from "./ui/parts.js";
import { ChatPanel, loadChat, pushMsg, setChat } from "./chat/panel.js";
import { addActions, updateAction } from "./chat/actions.js";
import { DrawingsPanel } from "./panels/drawings.js";
import { NodesPanel } from "./panels/nodes.js";
import { ResultsPanel } from "./panels/results.js";
import { IePanel } from "./panels/ie.js";
import { resetAreas } from "./areas.js";
import { SettingsPanel } from "./panels/settings.js";
import { SheetHost } from "./sheet_host.js";

const toast = (text, kind) => store.set({ toast: { text, kind } });

// ---------------------------------------------------------------- 엔진에서 읽기
export async function loadState() {
  const s = await read("state");
  setProject(s.project_id);        // 이후 모든 명령에 이 프로젝트 ID를 실어 보낸다
  store.set((cur) => ({ app: Object.assign({}, cur.app, s), chatCollapsed: !!(s.ui && s.ui.chat_collapsed) }));
  setChat({ model: s.chat_model });
  return s;
}

export async function loadDrawings() {
  const d = await read("drawings");
  store.set((cur) => ({ drawings: d, sheet: cur.sheet && d.drawings.some((x) => x.graph_id === cur.sheet) ? cur.sheet : null }));
  return d;
}

export async function loadConn() { store.set({ conn: await read("connection") }); }

// ---------------------------------------------------------------- 보기 동작
function saveUi() {
  const s = store.get();
  cmd("ui.save", { state: { sheet: s.sheet, chat_collapsed: s.chatCollapsed, panel: s.panel } }).catch(() => {});
}

export function openSheet(graphId) {
  store.set({ sheet: graphId, panel: null, marks: { rid: null, bySheet: {} } });
  cmd("sheet.open", { graph_id: graphId }).catch(() => {});
  saveUi();
}

export function togglePanel(name) {
  store.set((s) => ({ panel: s.panel === name ? null : name }));
}

export function toggleChat() {
  store.set((s) => ({ chatCollapsed: !s.chatCollapsed, chat: Object.assign({}, s.chat, { unread: false }) }));
  saveUi();
}

function zoomTo(ids) { store.set((s) => ({ command: { seq: s.command.seq + 1, type: "zoomTo", ids, pad: 0.15 } })); }

/** 답 카드의 ID 칩: 그 칩의 도면을 열고 그 구성요소에 맞춰 확대한다. */
function onChip(chip) {
  if (chip.sheet && chip.sheet !== store.get().sheet) openSheet(chip.sheet);
  if (chip.local_id) setTimeout(() => zoomTo([chip.local_id]), 0);
}

/** 답 카드의 도면 칩: 그 도면을 열고 그 도면 몫의 경로를 그린다. */
function onSheet(msg, pathIndex, sheet) {
  const path = msg.card.paths[pathIndex];
  const bySheet = (path && path.marks) || {};
  store.set({ sheet, panel: null, marks: { rid: msg.key, bySheet } });
  cmd("sheet.open", { graph_id: sheet }).catch(() => {});
}

// ---------------------------------------------------------------- 사건
function wireEvents() {
  on("chat.user", (d) => pushMsg({ kind: "user", text: d.text }));
  on("chat.progress", (d) => setChat({ progress: d }));
  on("chat.notice", (d) => pushMsg({ kind: "notice", text: d.text }));
  on("chat.cleared", () => { setChat({ msgs: [], progress: null }); store.set({ marks: { rid: null, bySheet: {} } }); });
  on("chat.state", (d) => setChat({ busy: d.busy, model: d.model, availability: d.availability, progress: d.busy ? store.get().chat.progress : null }));
  on("chat.answer", (d) => {
    pushMsg({ kind: "answer", card: d.card, footer: d.footer });
    const key = store.get().chat.msgs.length ? store.get().chat.msgs[store.get().chat.msgs.length - 1].key : null;
    const first = d.card.paths[0];
    const bySheet = first ? first.marks : (d.card.highlight_marks || {});
    store.set({ marks: { rid: key, bySheet } });     // 카드가 나타날 때 지금 도면에 먼저 그린다(도면을 갑자기 바꾸지 않는다)
    if (store.get().chatCollapsed) setChat({ unread: true });
  });
  on("chat.actions", (d) => { addActions(setChat, d); if (store.get().chatCollapsed) setChat({ unread: true }); });
  on("chat.action.result", (d) => updateAction(setChat, d));
  on("project.changed", (d) => { setProject(d.project_id); store.set({ sheet: null, marks: { rid: null, bySheet: {} } }); resetAreas(); });
  on("conn.changed", (d) => store.set({ conn: d }));
  on("drop.hover", (d) => store.set({ dropOver: !!d.over }));
  on("drop.refused", (d) => toast(d.text, "err"));
  on("app.notice", (d) => toast(d.text));
  const job = (state) => (d) => store.set((s) => ({ jobs: Object.assign({}, s.jobs, { [d.id]: Object.assign({}, s.jobs[d.id], d, { state }) }) }));
  on("job.progress", job("running"));
  on("job.done", (d) => { job("done")(d); loadDrawings().then((x) => { if (!store.get().sheet && x.drawings.length === 1) openSheet(x.drawings[0].graph_id); }); });
  on("job.failed", (d) => { job("failed")(d); toast(d.label + ": " + d.message, "err"); });
  onChanged((topic) => {
    if (topic === "drawings") loadDrawings().catch(() => {});
    if (topic === "state") loadState().catch(() => {});
  });
}

// ---------------------------------------------------------------- 화면
function Rail() {
  const panel = useStore((s) => s.panel);
  const conn = useStore((s) => s.conn);
  const b = (name, icon, label, badge) => html`<button type="button" class=${panel === name ? "on" : ""} title=${label} aria-label=${label} onClick=${() => togglePanel(name)}>
    <${Icon} name=${icon} />${badge ? html`<span class="badge">${badge}</span>` : null}</button>`;
  const unknowns = useStore((s) => s.drawings.drawings.reduce((n, d) => n + (d.unknowns || 0), 0));
  return html`<nav class="rail" aria-label="메뉴"><div class="logo" aria-hidden="true">HZ</div>
    ${b("drawings", "files", "도면 (Ctrl+1)", unknowns || null)}
    ${b("nodes", "vector-triangle", "구간 (Ctrl+2)", null)}
    ${b("results", "table", "분석 결과 (Ctrl+3)", null)}
    ${b("ie", "route", "초기사건 (Ctrl+4)", null)}
    <div class="spacer"></div>
    <button type="button" class=${panel === "settings" ? "on" : ""} title=${"AI 연결 · " + conn.label} aria-label=${"AI 연결: " + conn.label} onClick=${() => togglePanel("settings")}>
      <${Icon} name="plug-connected" /><span class=${"conn " + (conn.tone || "plain")}></span></button>
    ${b("settings", "settings", "설정")}</nav>`;
}

function ProjectBox({ id }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(id || "");
  useEffect(() => setValue(id || ""), [id]);
  async function apply(raw) {
    const v = (raw === undefined ? value : raw).trim();
    setEditing(false);
    if (!v || v === id) return;
    try {
      await cmd("project.set", { project_id: v });
      store.set({ sheet: null, marks: { rid: null, bySheet: {} } });
      await Promise.all([loadState(), loadDrawings()]);
    } catch (e) { toast(e.message, "err"); }
  }
  if (!editing) {
    return html`<button type="button" class="sheet" title="프로젝트 바꾸기" aria-label=${"프로젝트: " + (id || "없음") + ", 바꾸기"} onClick=${() => setEditing(true)}>${id || "프로젝트"}</button>`;
  }
  return html`<input type="text" class="proj-input" maxlength="60" value=${value} aria-label="프로젝트 ID" style="height:28px;width:160px" autofocus
    onInput=${(e) => setValue(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") apply(e.target.value); if (e.key === "Escape") { setValue(id || ""); setEditing(false); } }} onBlur=${(e) => apply(e.target.value)} />`;
}

function TopBar() {
  const sheet = useStore((s) => s.sheet);
  const d = useStore((s) => s.drawings);
  const row = d.drawings.find((x) => x.graph_id === sheet);
  return html`<header class="topbar"><div class="crumb"><${ProjectBox} id=${d.project_id} /><span class="muted">›</span>
    <button type="button" class="sheet" aria-label="도면 바꾸기" onClick=${() => togglePanel("drawings")}>${row ? (row.drawing_number || row.name) : "도면 고르기"}<${Icon} name="chevron-down" size=${14} /></button>
    ${row && row.title ? html`<span class="title">${row.title}</span>` : null}</div></header>`;
}

function Toast() {
  const t = useStore((s) => s.toast);
  useEffect(() => { if (!t) return undefined; const id = setTimeout(() => store.set({ toast: null }), 5000); return () => clearTimeout(id); }, [t]);
  return t ? html`<div class=${"toast" + (t.kind === "err" ? " err" : "")} role="status">${t.text}</div>` : null;
}

function App() {
  const panel = useStore((s) => s.panel);
  const collapsed = useStore((s) => s.chatCollapsed);
  useStore((s) => s.iconsReady);
  useEffect(() => {
    function key(e) {
      const tag = (e.target && e.target.tagName) || "";
      const typing = tag === "TEXTAREA" || tag === "INPUT";
      if (e.ctrlKey && e.altKey && (e.key === "k" || e.key === "K")) { e.preventDefault(); toggleChat(); }
      else if (e.ctrlKey && !e.altKey && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        if (store.get().chatCollapsed) toggleChat();
        setTimeout(() => { const el = document.querySelector(".chat-input"); if (el) el.focus(); }, 0);
      } else if (e.ctrlKey && e.key === "1") { e.preventDefault(); togglePanel("drawings"); }
      else if (e.ctrlKey && e.key === "2") { e.preventDefault(); togglePanel("nodes"); }
      else if (e.ctrlKey && e.key === "3") { e.preventDefault(); togglePanel("results"); }
      else if (e.ctrlKey && e.key === "4") { e.preventDefault(); togglePanel("ie"); }
      else if ((e.ctrlKey && e.key === "0") || (e.key === "Escape" && !typing)) { if (store.get().panel) { e.preventDefault(); store.set({ panel: null }); } }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  return html`<div class=${"app" + (collapsed ? " chat-collapsed" : "")}>
    <${Rail} />
    <main class="center"><${TopBar} /><${SheetHost} />
      ${panel === "drawings" ? html`<${DrawingsPanel} onOpen=${openSheet} onClose=${() => store.set({ panel: null })} />` : null}
      ${panel === "nodes" ? html`<${NodesPanel} onClose=${() => store.set({ panel: null })} />` : null}
      ${panel === "results" ? html`<${ResultsPanel} onClose=${() => store.set({ panel: null })} />` : null}
      ${panel === "ie" ? html`<${IePanel} onClose=${() => store.set({ panel: null })} />` : null}
      ${panel === "settings" ? html`<${SettingsPanel} onClose=${() => store.set({ panel: null })} />` : null}
      <${Toast} /></main>
    <${ChatPanel} collapsed=${collapsed} onToggle=${toggleChat} onChip=${onChip} onSheet=${onSheet} />
  </div>`;
}

async function boot() {
  connect();
  wireEvents();
  render(html`<${App} />`, document.getElementById("app"));
  await loadIcons();
  const [s, d] = await Promise.all([loadState(), loadDrawings()]);
  await Promise.all([loadConn(), loadChat()]);
  const ui0 = s.ui || {};
  if (ui0.sheet && d.drawings.some((x) => x.graph_id === ui0.sheet)) openSheet(ui0.sheet);
  else if (d.drawings.length === 1) openSheet(d.drawings[0].graph_id);
  else store.set({ panel: "drawings" });   // 열 도면이 없거나 여럿이면 도면 패널을 먼저 보인다
  if (!s.reviewer) { store.set({ panel: "settings" }); toast("검토자 이름을 입력하세요. 승인·확정 기록에 남습니다."); }   // 처음 실행할 때 묻는 것은 그대로
  if (s.debug) window.__hz = { store, cmd, read, ui };
}

boot().catch((e) => { document.getElementById("app").textContent = "화면을 시작하지 못했습니다: " + (e && e.message); });
