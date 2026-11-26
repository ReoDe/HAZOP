// 새 화면의 진입점(규격 §2.1): 왼쪽 메뉴 · 위 막대 · 가운데 도면 · 오른쪽 채팅, 메뉴에서 여는 패널 하나.
// 저장하는 자료는 엔진만 쓴다. 여기서는 보기 상태(열린 패널, 보는 도면, 채팅 접힘, 도면 표시)만 갖고 엔진의 바뀜 알림을 받아 다시 읽는다.
import { html, render } from "./ui/html.js";
import { useEffect, useState } from "../vendor/hooks.module.js";
import { store, useStore } from "./store.js";
import { cmd, connect, holdReads, on, onChanged, read, releaseReads, setProject, ui } from "./bridge.js";
import { Icon, loadIcons } from "./ui/icon.js";
import { Btn } from "./ui/parts.js";
import { ChatPanel, loadChat, pushMsg, setChat } from "./chat/panel.js";
import { addActions, updateAction } from "./chat/actions.js";
import { PANELS, byName, leadOf, loadPanelCss, panelLabel, tabsOf } from "./panels/index.js";
import { resetAreas } from "./areas.js";
import { wirePrefetch } from "./clean_prefetch.js";
import { clean } from "./canvas/clean_ui.js";
import { setOpenSheet } from "./panels/results_state.js";
import { SheetHost } from "./sheet_host.js";
import { Notices, addNotice, lostNotice, refreshLostNotice } from "./notices.js";
import { go as nextGo, next as nextStore, setGo, wireNotice as wireNextNotice } from "./next/next.js";
import { closeQueue, openQueue, q as queueStore, useQueue, wire as wireQueue } from "./queue/queue.js";
import { QueueCard, QueueLine } from "./queue/card.js";
import { ReviewConfirm, setOpeners as setReviewOpeners, startReview, wire as wireReview } from "./review/review.js";
import { RevertGuard } from "./review/revert_guard.js";
import { locate } from "./locate.js";

// '다음에 할 일' 단추가 가는 자리(엔진 next의 go). 도면 위 자리로 갈 때는 열린 패널을 닫는다(가리지 않게). 패널 모듈은 누를 때 읽는다
setGo("panel:drawings#titleblock", async (t) => { const m = await import("./panels/titleblock.js"); if (t) m.focusMaterial(t); else store.set({ panel: "titleblock" }); });
setGo("panel:drawings#sheetconf", async (t) => {
  store.set({ panel: null });
  if (t && store.get().sheet !== t) openSheet(t);
  const c = await import("./sheet_confirm.js");
  c.openNext(t || store.get().sheet);      // 조건이 다 찼으면 견주기 화면을 바로(견줌 기록하고 확정까지 한 흐름, U8)
});
setGo("panel:drawings#sources", () => {      // 같은 번호 자리의 파일·형식 고르기 카드로(도면 패널 안)
  store.set({ panel: "drawings" });
  [80, 400, 1200].forEach((ms) => setTimeout(() => { const el = document.querySelector(".src-card"); if (el) el.scrollIntoView({ block: "start" }); }, ms));
});
// 확정 안 한 구간 목록을 보인 확인 카드(한 번에 확정). 구간 패널은 열지 않는다: 카드는 도면 위 창으로(실제 창 3차, 클릭 줄이기)
setGo("panel:nodes#pick", async () => { store.set({ panel: null }); const N = await import("./panels/nodes_state.js"); N.setMode("pick"); });      // 도면 위 안내 줄이 할 일을 보인다(nodes_canvas PickHint)
setGo("confirm:inputs.build", (t) => cmd("inputs.build", t ? { graph_id: t } : {}).catch((e) => toast((e && e.message) || "다시 읽지 못했습니다.", "err")));      // 반영 전 수락이 남은 도면 다시 읽기(작업 줄에 진행)
setGo("confirm:ie.suggest", async () => {      // 초기사건 규칙 초안 만들기(확정하지 않음, 두 번 해도 더하는 것이 없다): 패널을 열고 만든다
  store.set({ panel: "ie" });
  const I = await import("./panels/ie_state.js");
  await I.loadSummary();
  await I.suggest();
});
setGo("queue:lost", () => openQueue("lost"));
setGo("queue:ai", (t) => openQueue("ai", t));
setGo("confirm:aireview.run", (t) => startReview(t || store.get().sheet));
setGo("confirm:nodes.catch_up", async () => { store.set({ panel: "nodes" }); const N = await import("./panels/nodes_state.js"); N.catchUp(); });
setGo("panel:results#run", async () => { store.set({ panel: "results" }); const R = await import("./panels/results_state.js"); R.planRun("all"); });
setGo("confirm:results.export_excel", async () => { const R = await import("./panels/results_state.js"); R.exportExcel("all"); });

const toast = (text, kind) => store.set({ toast: { text, kind } });
/** 엔진이 app.notice로 올려도 사람이 할 일이 없는 글(화면에 띄우지 않는다). 나머지(다시 읽기 실패·나누기 반영 뒤 다시 묻기·구간 재확인·AI 연결·창 닫기 대기)는 띄운다. */
const QUIET_NOTICES = [/새 이름 규칙으로 정리하지 못했습니다/];

// ---------------------------------------------------------------- 엔진에서 읽기
export async function loadState() {
  const s = await read("state");
  setProject(s.project_id);        // 이후 모든 명령에 이 프로젝트 ID를 실어 보낸다
  // 채팅은 사람이 접거나 편 적이 있으면 그대로, 처음이면 좁은 창(1280 미만)에서만 접은 채로 연다
  const saved = s.ui && typeof s.ui.chat_collapsed === "boolean" ? s.ui.chat_collapsed : window.innerWidth < 1280;
  store.set((cur) => ({ app: Object.assign({}, cur.app, s), chatCollapsed: saved }));
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

/** 도면을 열 때 도면·구간 패널(늘 고정)은 그대로 둔다. 다른 패널은 도면을 가리므로 닫는다. */
const FIXED_PANELS = ["drawings", "nodes"];
/** 도면·구간 패널은 화면에 늘 고정이다: 어디서든 패널을 비우면(다른 패널 닫기 포함) 마지막에 보던 고정 패널이 된다. */
function pinFixedPanels() {
  const raw = store.set;
  let last = "drawings";
  store.set = (patch) => raw((s) => {
    const next = typeof patch === "function" ? patch(s) : patch;
    if (!next || !("panel" in next)) return next;
    if (FIXED_PANELS.includes(next.panel)) last = next.panel;
    else if (!next.panel) return Object.assign({}, next, { panel: last });
    return next;
  });
  store.set({ panel: store.get().panel });
}
const fitSheet = () => store.set((s) => ({ command: { seq: s.command.seq + 1, type: "fit" } }));
const keptPanel = () => (FIXED_PANELS.includes(store.get().panel) ? store.get().panel : null);
export function openSheet(graphId) {
  if (store.get().sheet === graphId) fitSheet();      // 다른 도면은 도면 부품이 자료를 읽으며 맞춘다
  store.set({ sheet: graphId, panel: keptPanel(), marks: { rid: null, bySheet: {} } });
  cmd("sheet.open", { graph_id: graphId }).catch(() => {});
  saveUi();
}

export function togglePanel(name) {
  store.set((s) => ({ panel: s.panel === name && !FIXED_PANELS.includes(name) ? null : name, backTo: null }));
}

setOpenSheet(openSheet);      // 분석 결과의 '도면에서 보기'가 도면을 바꿀 때 쓴다

const closePanel = () => store.set({ panel: null });

export function toggleChat() {
  store.set((s) => ({ chatCollapsed: !s.chatCollapsed, chat: Object.assign({}, s.chat, { unread: false }) }));
  saveUi();
}

/** 답 카드의 ID 칩: 그 칩의 도면을 전체 맞춤으로 보이고 그 구성요소만 강조한다. */
function onChip(chip) {
  locate({ sheet: chip.sheet, ids: chip.local_id ? [chip.local_id] : [] });
}

/** 답 카드의 도면 칩: 그 도면을 열고 그 도면 몫의 경로(차례 번호)를 그린다. */
function onSheet(msg, pathIndex, sheet) {
  const path = msg.card.paths[pathIndex];
  locate({ sheet, marks: (path && path.marks) || {}, rid: msg.key });
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
  on("project.changed", (d) => { setProject(d.project_id); store.set({ sheet: null, marks: { rid: null, bySheet: {} } }); resetAreas(); checkLost(); });
  on("conn.changed", (d) => store.set({ conn: d }));
  on("drop.hover", (d) => store.set({ dropOver: !!d.over }));
  on("drop.refused", (d) => toast(d.text, "err"));
  on("app.notice", (d) => { if (!QUIET_NOTICES.some((re) => re.test(d.text || ""))) toast(d.text); });      // 할 일이 없는 엔진 알림은 거른다
  on("study.lost", (d) => { const n = lostNotice(d); if (n) addNotice(n); });      // 다시 추출 뒤 새로 찾지 못한 구성요소(엔진이 판 이전을 이어서 한 결과)
  const job = (state) => (d) => store.set((s) => ({ jobs: Object.assign({}, s.jobs, { [d.id]: Object.assign({}, s.jobs[d.id], d, { state }) }) }));
  on("job.progress", job("running"));
  on("job.done", (d) => {
    job("done")(d);
    const dup = d.result && d.result.conflicts;
    if (dup && dup.length) toast("같은 도면 번호 " + dup.join(", ") + "의 원본이 둘입니다. 도면 패널에서 쓸 것을 고르세요.");
    loadDrawings().then((x) => { if (!store.get().sheet && x.drawings.length === 1) openSheet(x.drawings[0].graph_id); }); });
  on("job.failed", (d) => {       // 사람이 한 멈춤·취소(stopped)는 실패가 아니다: 빨간 표시를 하지 않고 조용히 알린다(실제 창 3차 결함 3)
    if (d.stopped) { job("stopped")(d); return; }
    job("failed")(d); toast(d.label + ": " + d.message, "err");
  });
  onChanged((topic) => {
    if (topic === "drawings") loadDrawings().catch(() => {});
    if (topic === "state") loadState().catch(() => {});
    if (topic === "nodes") refreshLostNotice();       // 확인을 마쳐 없어졌으면 알림도 사라진다
  });
}

// ---------------------------------------------------------------- 화면
function Rail() {
  const panel = useStore((s) => s.panel);
  const here = leadOf(byName(panel));          // 묶음 안의 어느 화면이 열려 있어도 그 묶음의 단추가 켜진다
  const shown = (p) => !p.group && !p.hidden;
  return html`<nav class="rail" aria-label="메뉴"><div class="logo" aria-hidden="true">HZ</div>
    ${PANELS.filter((p) => shown(p) && p.place !== "bottom").map((p) => html`<${RailButton} key=${p.name} p=${p} on=${here === p.name} />`)}
    <div class="spacer"></div>
    ${PANELS.filter((p) => shown(p) && p.place === "bottom").map((p) => html`<${RailButton} key=${p.name} p=${p} on=${here === p.name} />`)}</nav>`;
}

/** 메뉴 단추 하나: panels/index.js의 항목에서 이름·아이콘·숫자(badge)·보조 글(hint)·점(dot)을 읽는다. 묶음에 속한 화면이 열려 있으면 누르면 닫는다. */
function RailButton({ p, on }) {
  const badge = useStore(p.badge || nothing);
  const hint = useStore(p.hint || nothing);
  const dot = useStore(p.dot || nothing);
  const label = panelLabel(p) + (hint ? " · " + hint : "");
  const press = () => { if (on && !FIXED_PANELS.includes(leadOf(byName(store.get().panel)))) store.set({ panel: null, backTo: null }); else if (!on) togglePanel(p.name); };      // 도면·구간은 다시 눌러도 닫히지 않는다
  return html`<button type="button" class=${on ? "on" : ""} title=${label} aria-label=${label} onClick=${press}>
    <${Icon} name=${p.icon} />${badge ? html`<span class="badge">${badge}</span>` : null}${dot ? html`<span class=${"conn " + dot}></span>` : null}</button>`;
}

/** 한 묶음의 화면을 오가는 탭(예: 도면 · 표제란 · AI 검토). 묶음이 아니면 아무것도 그리지 않는다. */
function PanelTabs({ panel }) {
  const rows = tabsOf(panel);
  if (!rows.length) return null;
  return html`<div class="ptabs" role="tablist" aria-label="같은 메뉴의 화면">${rows.map((p) => html`<button type="button" role="tab" key=${p.name} class=${p.name === panel ? "on" : ""} aria-label=${p.label}
    aria-selected=${p.name === panel ? "true" : "false"} onClick=${() => store.set({ panel: p.name, backTo: null })}>${p.label}</button>`)}</div>`;
}
const nothing = () => null;

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

// 도면으로 건너온 화면의 '돌아가기' 칩. backTo가 이 표의 키일 때만 그린다(조사가 달라 문구를 직접 적는다).
const BACK_CHIPS = { results: "분석 결과로 돌아가기", ie: "초기사건으로 돌아가기" };

function TopBar() {
  const sheet = useStore((s) => s.sheet);
  const d = useStore((s) => s.drawings);
  const backTo = useStore((s) => s.backTo);
  const queueOpen = useQueue((s) => s.open);
  const row = d.drawings.find((x) => x.graph_id === sheet);
  return html`<header class="topbar"><div class="crumb"><${ProjectBox} id=${d.project_id} /><span class="muted">›</span>
    <button type="button" class="sheet" aria-label="도면 바꾸기" title=${row && row.title ? row.title : null} onClick=${() => store.set({ panel: "drawings" })}>${row ? (row.display || row.drawing_number || row.name) : "도면 고르기"}<${Icon} name="chevron-down" size=${14} /></button>
    ${BACK_CHIPS[backTo] ? html`<button type="button" class="chip accent" aria-label=${BACK_CHIPS[backTo]} onClick=${() => store.set({ panel: backTo, backTo: null })}><${Icon} name=${(byName(backTo) || {}).icon || "arrow-left"} size=${14} /> ${BACK_CHIPS[backTo]}</button>` : null}</div>
    ${queueOpen ? html`<${QueueLine} />` : null}</header>`;     // 도면 제목은 도면 번호에 마우스를 올리면 보인다. '다음에 할 일' 한 줄은 화면에서 내렸다(화면 단순화, 코드는 next/에 남김)
}

function Toast() {
  const t = useStore((s) => s.toast);
  useEffect(() => { if (!t) return undefined; const id = setTimeout(() => store.set({ toast: null }), 5000); return () => clearTimeout(id); }, [t]);
  return t ? html`<div class=${"toast" + (t.kind === "err" ? " err" : "")} role="status">${t.text}</div>` : null;
}

function App() {
  const panel = useStore((s) => s.panel);
  const collapsed = useStore((s) => s.chatCollapsed);
  const queueOpen = useQueue((s) => s.open);
  useStore((s) => s.iconsReady);
  useEffect(() => {
    function key(e) {
      const tag = (e.target && e.target.tagName) || "";
      const typing = tag === "TEXTAREA" || tag === "INPUT";
      if (e.ctrlKey && e.altKey && (e.key === "k" || e.key === "K")) { e.preventDefault(); toggleChat(); }
      else if (e.ctrlKey && !e.altKey && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        if (queueStore.get().open) closeQueue();      // 대기열 카드 자리에서 채팅으로(이미 한 판정은 저장돼 있다)
        if (store.get().chatCollapsed) toggleChat();
        setTimeout(() => { const el = document.querySelector(".chat-input"); if (el) el.focus(); }, 0);
      } else if (e.ctrlKey && PANELS.some((p) => p.key === e.key)) { e.preventDefault(); togglePanel(PANELS.find((p) => p.key === e.key).name); }
      else if ((e.ctrlKey && e.key === "0") || (e.key === "Escape" && !typing)) { if (store.get().panel && !FIXED_PANELS.includes(store.get().panel)) { e.preventDefault(); store.set({ panel: null }); } }
    }
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("keydown", key); };
  }, []);
  return html`<div class=${"app" + (collapsed && !queueOpen ? " chat-collapsed" : "") + (queueOpen ? " queue-open" : "")}>
    <${Rail} />
    <main class="center"><${TopBar} /><${Notices} /><${SheetHost} />
      ${PANELS.map((p) => (panel === p.name ? html`<div class="pwrap" key=${p.name} data-panel=${p.name}><${PanelTabs} panel=${p.name} /><${p.component} onOpen=${openSheet} onClose=${closePanel} /></div>` : null))}
      <${Toast} /><${ReviewConfirm} /><${RevertGuard} /></main>
    ${queueOpen ? html`<${QueueCard} onChat=${() => { closeQueue(); if (store.get().chatCollapsed) toggleChat(); }} />`
      : html`<${ChatPanel} collapsed=${collapsed} onToggle=${toggleChat} onChip=${onChip} onSheet=${onSheet} />`}
  </div>`;      // 오른쪽 칸은 채팅 또는 대기열 카드 하나(HZ-DSN-06 §3.5)
}

/** 프로젝트를 연 뒤 검토구간에 찾지 못한 구성요소(묘비)·확인할 참조가 있으면 토스트 한 줄. 읽기 실패는 조용히 넘어간다. */
const checkLost = refreshLostNotice;      // 닫을 수 있는 알림 줄(notices.js): 처리돼 없어지면 사라진다

async function boot() {
  holdReads();      // 도면 목록이 뜰 때까지 큰 프로젝트에서 오래 걸리는 읽기(구간·결과·지식그래프 등)는 미룬다(bridge.js)
  connect();
  wireEvents();
  wireQueue();
  setReviewOpeners(openQueue, openSheet, (gid) => queueStore.get().open && queueStore.get().kind === "ai" && queueStore.get().gid === gid);
  wireReview();
  pinFixedPanels();
  render(html`<${App} />`, document.getElementById("app"));
  loadPanelCss();
  await loadIcons();
  const [s, d] = await Promise.all([loadState(), loadDrawings()]);
  releaseReads();
  await loadConn();
  const ui0 = s.ui || {};
  if (ui0.sheet && d.drawings.some((x) => x.graph_id === ui0.sheet)) openSheet(ui0.sheet);
  else if (d.drawings.length === 1) openSheet(d.drawings[0].graph_id);
  else store.set({ panel: "drawings" });   // 열 도면이 없거나 여럿이면 도면 패널을 먼저 보인다
  if (!s.reviewer) { store.set({ panel: "settings" }); }   // 처음 실행할 때 묻는 것은 그대로
  if (s.debug) window.__hz = { store, cmd, read, ui, clean, next: nextStore, queue: queueStore, go: nextGo };
  cmd("project.open_check").catch(() => {});      // 앱을 끈 사이 도면이 다시 읽혔으면 검토구간을 뒤에서 맞춘다(잃은 것이 있으면 알림이 온다)
  wirePrefetch();      // 정리 자료 미리 읽기와 오래된 자료 버리기
  wireNextNotice();      // '다음에 할 일' 줄은 내렸지만 수락하고 반영하지 않은 입력 연산 알림은 이어서 맞춘다
  checkLost();        // 다시 추출 뒤 찾지 못한 구성요소가 있으면 한 줄로 알린다(읽기는 뒤에서, 화면을 붙잡지 않는다)
  await loadChat();   // 채팅 예시 질문은 프로젝트 그래프를 읽어 큰 프로젝트에서 수 초 걸린다. 도면 목록이 먼저 보이게 맨 끝에서 읽는다
}

boot().catch((e) => { document.getElementById("app").textContent = "화면을 시작하지 못했습니다: " + (e && e.message); });
