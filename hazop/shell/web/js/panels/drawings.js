// 도면 패널(규격 §2.1·§2.3 ①등록 줄). 끌어 놓기 자리(파일은 Qt가 받는다), 도면·문서 목록, 작업 줄, 추출 카드의 AI 검토 토글·호출 상한.
import { html } from "../ui/html.js";
import { store, useStore } from "../store.js";
import { cmd } from "../bridge.js";
import { Icon } from "../ui/icon.js";
import { Btn, Chip, Notice, Switch } from "../ui/parts.js";

function toastError(e) { store.set({ toast: { text: e.message, kind: "err" } }); }

export function DrawingsPanel({ onOpen, onClose }) {
  const data = useStore((s) => s.drawings);
  const sheet = useStore((s) => s.sheet);
  const app = useStore((s) => s.app);
  const jobs = useStore((s) => s.jobs);
  const over = useStore((s) => s.dropOver);
  const conn = useStore((s) => s.conn);
  const running = Object.entries(jobs);

  const pick = () => cmd("register.pick").catch(toastError);
  const setReview = (patch) => cmd("extract.set_ai_review", patch).then((r) => store.set((s) => ({
    app: Object.assign({}, s.app, { ai_review: r.enabled, ai_review_cap: r.cap || s.app.ai_review_cap }) }))).catch(toastError);

  return html`<section class="panel" aria-label="도면">
    <div class="panel-h"><h2>도면</h2><span class="acts"><${Btn} kind="ghost" icon="x" label="패널 닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      <div class=${"drop" + (over ? " over" : "")} role="button" tabindex="0" aria-label="도면 파일 고르기" onClick=${pick}
        onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } }}>
        <${Icon} name="upload" size=${22} /><div><b>도면 파일을 여기에 끌어 놓으세요</b><br /><span>.drawio, .pdf 여러 개 · 눌러서 고르기</span></div></div>
      ${running.map(([id, j]) => html`<div class="card" key=${id}>
        <div class="kv"><div class="k"><b>${j.label}</b><span>${j.state === "failed" ? j.message : (j.text || "준비 중")}${j.total ? " (" + j.done + "/" + j.total + ")" : ""}</span></div>
          ${j.state === "running" ? html`<${Icon} name="loader-2" cls="spin" />` : j.state === "done" ? html`<${Chip} kind="ok" icon="check">완료<//>` : html`<${Chip} kind="err" icon="alert-triangle">실패<//>`}</div>
          ${j.state === "done" && j.result && j.result.ai_review && j.result.ai_review.ran ? html`<${Chip} kind="ai" icon="sparkles">AI 후보 ${j.result.ai_review.candidates}개<//>` : null}</div>`)}
      <div class="card"><h3>추출 설정</h3>
        <div class="kv"><div class="k"><b>AI 검토</b><span>추출 뒤 AI가 미확인 항목의 후보를 제안합니다(구독 한도를 씁니다). 처음 값은 꺼짐입니다.</span></div>
          <${Switch} on=${app.ai_review} label="AI 검토" onChange=${(v) => setReview({ enabled: v })} /></div>
        ${app.ai_review ? html`<div class="kv"><div class="k"><b>도면당 호출 상한</b><span>${app.ai_review_cap}회 (예상 ${Math.max(1, Math.round(app.ai_review_cap * 6 / 60))}분 안쪽)</span></div>
          <input type="number" min="1" max="200" value=${app.ai_review_cap} aria-label="도면당 호출 상한" style="width:72px;height:30px"
            onChange=${(e) => setReview({ cap: Math.max(1, Math.min(200, parseInt(e.target.value, 10) || 20)) })} /></div>` : null}
        ${app.ai_review && !conn.can_start ? html`<${Notice} kind="warn" icon="alert-triangle">AI 연결이 준비되지 않아 검토는 건너뜁니다.<//>` : null}</div>
      <div><div class="muted" style="font-size:var(--fs-sm);margin-bottom:6px">도면 ${data.drawings.length}장${data.project_id ? " · 프로젝트 " + data.project_id : ""}</div>
        ${data.drawings.length === 0 ? html`<${Notice}>등록된 도면이 없습니다. 위 자리에 도면 파일을 끌어 놓으면 등록하고 읽습니다.<//>` : html`<div class="list">
          ${data.drawings.map((d) => html`<div class=${"row" + (d.graph_id === sheet ? " on" : "")} key=${d.graph_id}>
            <div class="thumb" aria-hidden="true"></div>
            <div class="main"><b>${d.drawing_number || d.name}</b><span>${d.title || "표제란 확인 전"}</span></div>
            ${d.unknowns ? html`<${Chip} kind="warn" title="추출에서 읽지 못한 항목">미확인 ${d.unknowns}<//>` : html`<${Chip} kind="ok" icon="check">읽음<//>`}
            <${Btn} sm=${true} label=${(d.drawing_number || d.name) + " 열기"} onClick=${() => onOpen(d.graph_id)}>열기<//></div>`)}</div>`}</div>
      ${data.documents.length ? html`<div><div class="muted" style="font-size:var(--fs-sm);margin-bottom:6px">등록 자료 ${data.documents.length}건</div><div class="list">
        ${data.documents.map((d) => html`<div class="row" key=${d.material_id + ":" + d.version}><div class="main"><b>${d.name || d.material_id}</b><span>버전 ${d.version} · ${d.type}</span></div>
          <${Chip} kind=${d.status === "registered" ? "ok" : "warn"}>${d.status === "registered" ? "등록됨" : d.status}<//>${d.graphed ? html`<${Chip} kind="accent">그래프<//>` : null}</div>`)}</div></div>` : null}
    </div></section>`;
}
