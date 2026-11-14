// 채팅 패널(규격 §3.2). 입력(Enter로 보내기, Shift+Enter 줄 바꿈), 예시 질문(누르면 입력칸에 들어가고 바로 보내지 않음), 진행 표시와 멈추기,
// 답 카드, 연결 없는 PC의 안내. 막기(한도·초과 사용·인증)는 엔진(hazop/shell/chat.py)이 정하고 여기서는 availability를 따른다.
import { html } from "../ui/html.js";
import { useEffect, useRef, useState } from "../../vendor/hooks.module.js";
import { store, useStore } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";
import { Icon } from "../ui/icon.js";
import { Btn, Chip } from "../ui/parts.js";
import { AnswerCard } from "./card.js";
import { ActionItems } from "./actions.js";

const MODELS = [["fast", "빠름"], ["normal", "보통"], ["deep", "깊게"]];
const NAMES = { fast: "빠름", normal: "보통", deep: "깊게" };

export function setChat(patch) {
  store.set((s) => ({ chat: Object.assign({}, s.chat, typeof patch === "function" ? patch(s.chat) : patch) }));
}

export function pushMsg(msg) {
  setChat((c) => ({ msgs: [...c.msgs, Object.assign({ key: c.msgs.length + ":" + Date.now() }, msg)] }));
}

export async function loadChat() {
  const [snap, ex] = await Promise.all([read("chat"), read("examples")]);
  setChat({ busy: snap.busy, model: snap.model, availability: snap.availability, examples: ex.groups });
}

export function ChatPanel({ collapsed, onToggle, onChip, onSheet }) {
  const chat = useStore((s) => s.chat);
  const conn = useStore((s) => s.conn);
  const chatConn = useChatConn();
  const [text, setText] = useState("");
  const input = useRef(null);
  const list = useRef(null);
  useEffect(() => { if (list.current) list.current.scrollTop = list.current.scrollHeight; }, [chat.msgs.length, chat.progress]);

  async function askText(q) {
    if (chat.busy || chat.availability.blocked) { pushMsg({ kind: "notice", text: "지금은 물어볼 수 없습니다. 답이 끝난 뒤에 다시 눌러 주세요." }); return; }
    try { await cmd("chat.ask", { text: q }); } catch (e) { pushMsg({ kind: "notice", text: e.message }); }
  }

  async function send() {
    const q = text.trim();
    if (!q || chat.busy || chat.availability.blocked) return;
    setText("");
    try { await cmd("chat.ask", { text: q }); } catch (e) { pushMsg({ kind: "notice", text: e.message }); }
  }
  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    if (e.key === "Escape") e.target.blur();
  }
  function onInput(e) {
    setText(e.target.value);
    if (e.target.value.trim()) cmd("chat.prewarm").catch(() => {});
  }
  function nextModel() {
    const i = MODELS.findIndex(([k]) => k === chat.model);
    const next = MODELS[(i + 1) % MODELS.length][0];
    cmd("chat.set_model", { model: next }).then(() => setChat({ model: next })).catch(() => {});
  }

  if (collapsed) {
    return html`<aside class="chat collapsed" aria-label="채팅">
      <button type="button" class="btn ghost icon" title="채팅 펴기 (Ctrl+K)" aria-label="채팅 펴기" onClick=${onToggle}><${Icon} name="layout-sidebar-right-expand" /></button>
      ${chat.unread ? html`<span class="dot-new" title="새 답이 있습니다"></span>` : null}</aside>`;
  }
  const blocked = chat.availability.blocked;
  const empty = chat.msgs.length === 0 && !blocked;
  return html`<aside class="chat" aria-label="채팅">
    <div class="chat-h"><${Icon} name="message-circle" /><b>채팅</b>
      <span class="acts">
        <${Btn} kind="ghost" sm=${true} icon="message-plus" label="새 대화" title="지금까지의 대화를 지우고 새로 시작합니다" onClick=${() => cmd("chat.new")} />
        <${Btn} kind="ghost" sm=${true} icon="file-text" label="AI 실행 기록" title="AI가 실행한 일의 기록" onClick=${() => store.set((s) => ({ panel: s.panel === "actionlog" ? null : "actionlog", backTo: null }))} />
        <${Btn} kind="ghost" sm=${true} icon="layout-sidebar-right-collapse" label="채팅 접기" title="채팅 접기 (Ctrl+Alt+K)" onClick=${onToggle} /></span></div>
    <div class="msgs" ref=${list}>
      ${empty ? html`<div class="muted">도면과 문서에 대해 물어보세요. 아래 질문을 눌러 시작할 수도 있습니다.</div>` : null}
      ${chat.msgs.map((m) => m.kind === "user" ? html`<div class="q" key=${m.key}>${m.text}</div>`
        : m.kind === "notice" ? html`<div class="muted" key=${m.key} style="font-size:var(--fs-xs)">${m.text}</div>`
        : m.kind === "actions" ? html`<${ActionItems} key=${m.key} items=${m.items} onAsk=${askText} />`
        : m.kind === "answer" ? html`<${AnswerCard} key=${m.key} card=${m.card} footer=${m.footer} onChip=${onChip} onSheet=${(i, sheet) => onSheet(m, i, sheet)} />` : null)}
      ${chat.busy ? html`<div class="muted" role="status"><${Icon} name="loader-2" size=${14} cls="spin" /> ${chat.progress ? "도구 " + chat.progress.tools + "회 · " + chat.progress.name : "답을 찾는 중…"}</div>` : null}
      ${blocked ? html`<${GuideCard} availability=${chat.availability} />` : null}
    </div>
    <div class="composer">
      ${empty ? html`<div class="examples">${chat.examples.flatMap(([g, qs]) => qs.map((q) => html`<${Chip} key=${q} title=${g} onClick=${() => { setText(q); if (input.current) input.current.focus(); }}>${q}<//>`))}</div>` : null}
      <div class="box">
        <textarea ref=${input} class="chat-input" rows="2" placeholder="도면에 대해 물어보세요 (Enter로 보내기, Shift+Enter로 줄 바꾸기)" aria-label="채팅 질문"
          value=${text} disabled=${blocked} onInput=${onInput} onKeyDown=${onKey}></textarea>
        ${chat.busy
          ? html`<button type="button" class="send stop" title="멈추기" aria-label="멈추기" onClick=${() => cmd("chat.stop")}><${Icon} name="player-stop" size=${16} /></button>`
          : html`<button type="button" class="send" title="보내기 (Enter)" aria-label="보내기" disabled=${blocked || !text.trim()} onClick=${send}><${Icon} name="send" size=${16} /></button>`}
      </div>
      <div class="foot"><span class=${"dot " + ((chatConn || conn).tone || "plain")}></span> ${chatConn ? chatConn.chip : "구독 · " + (conn.label || "")}
        <button type="button" class="btn ghost sm" title="모델 바꾸기" aria-label=${"모델: " + NAMES[chat.model]} style="margin-left:auto" onClick=${nextModel}>
          <${Icon} name="cpu" size=${14} />${NAMES[chat.model]}</button></div>
    </div></aside>`;
}

// 채팅이 실제로 쓰는 연결(구독·채팅 모델·상태). 분석 연결 칩(conn.chip)은 분석이 API일 때 채팅도 API처럼 보이게 해서 쓰지 않는다.
function useChatConn() {
  const [value, setValue] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => read("chatconn").then((v) => { if (alive) setValue(v); }).catch(() => {});
    load();
    const offs = [on("conn.changed", load), on("chat.state", load), onChanged((topic) => { if (topic === "aisettings" || topic === "chatconn") load(); })];
    return () => { alive = false; offs.forEach((off) => off()); };
  }, []);
  return value;
}

function GuideCard({ availability }) {
  return html`<div class="card" role="alert"><h3>채팅을 쓸 수 없습니다</h3><p style="margin:0 0 8px">${availability.text}</p>
    <div class="muted" style="font-size:var(--fs-sm)">연결 없이도 되는 일: 도면 보기·확대, 도면 등록과 추출, 결과 보기.</div>
    <div class="acts-row" style="margin-top:8px">
      ${availability.button === "install" ? html`<${Btn} sm=${true} onClick=${() => cmd("conn.guide", { name: "install" })}>설치 방법 보기<//>` : null}
      ${availability.button === "login" ? html`<${Btn} sm=${true} onClick=${() => cmd("conn.guide", { name: "login" })}>로그인 창 열기<//>` : null}
      <${Btn} sm=${true} onClick=${() => cmd("conn.check")}>다시 확인<//></div></div>`;
}
