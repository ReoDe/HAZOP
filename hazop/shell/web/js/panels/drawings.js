// 도면 패널(규격 §2.1·§2.3 ①등록 줄). 끌어 놓기 자리(파일은 Qt가 받는다), 도면·문서 목록, 작업 줄, 추출 카드의 AI 검토 토글·호출 상한.
import { html } from "../ui/html.js";
import { store, useStore } from "../store.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Icon } from "../ui/icon.js";
import { Btn, Chip, Notice, Switch } from "../ui/parts.js";

function toastError(e) { store.set({ toast: { text: e.message, kind: "err" } }); }

const STATE_TEXT = { open: "확정 조건 남음", ready: "확정만 남음", confirmed: "확정됨" };

/** DEXPI 내보내기(앱 틀 규격 V5, DEXPI 규격 §6.1): 확정된 쪽만 낸다. 저장 폴더는 창이 대화상자로 묻고 웹은 경로를 보내지 않는다. 확정된 쪽이 없으면 단추 대신 안내를 보인다. */
function DexpiExport() {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const reload = () => read("dexpi").then(setInfo).catch(() => setInfo({ drawings: [], any: false }));
  useEffect(() => { reload(); return onChanged((t) => { if (t === "sheetconf" || t === "drawings") reload(); }); }, []);
  async function run() {
    setBusy(true); setError(""); setResult(null);
    try { setResult(await cmd("dexpi.export", { graph_ids: info.drawings.map((d) => d.graph_id) })); } catch (e) { setError(e.message || "내보내지 못했습니다."); }
    setBusy(false);
    reload();
  }
  if (!info) return null;
  const label = (d) => d.drawing_number || d.name;
  return html`<div class="card dexpi-card"><h3>DEXPI로 내보내기</h3>
    <div class="muted small">사람이 '쪽 확정'을 마친 쪽만 DEXPI XML로 냅니다. 확정 전 쪽과 옮기지 못한 항목은 아래 요약에 나옵니다.</div>
    ${info.drawings.length === 0 ? html`<${Notice}>내보낼 도면이 없습니다.<//>` : html`<div class="list" role="list" aria-label="내보내기 대상">${info.drawings.map((d) => html`<div class="row" role="listitem" key=${d.graph_id}>
      <div class="main"><b>${label(d)}</b><span>${d.exportable ? "내보낼 수 있음" : (d.why[0] || "내보낼 수 없음")}</span></div>
      <${Chip} kind=${d.state === "confirmed" ? "ok" : "warn"}>${STATE_TEXT[d.state] || "확정 전"}<//></div>`)}</div>`}
    ${info.any ? html`<div class="acts-row"><${Btn} kind="primary" sm=${true} icon="file-export" label="확정된 쪽 DEXPI로 내보내기" disabled=${busy} onClick=${run}>확정된 쪽 내보내기<//></div>`
      : (info.drawings.length ? html`<${Notice} kind="warn" icon="alert-triangle">확정된 쪽이 하나도 없어 내보낼 수 없습니다. 도면에서 쪽 확정을 마친 뒤 다시 오세요.<//>` : null)}
    ${error ? html`<${Notice} kind="err" icon="alert-triangle"><span style="white-space:pre-wrap">${error}</span><//>` : null}
    ${result && result.cancelled ? html`<${Notice} kind="info">${result.overwrite_refused ? "덮어쓰기를 취소해 내보내지 않았습니다." : "저장 위치를 고르지 않아 내보내지 않았습니다."}<//>` : null}
    ${result && !result.cancelled ? html`<div class="card" aria-label="내보내기 결과"><b>${result.drawings.length}쪽을 내보냈습니다</b> <span class="muted small">폴더 ${result.folder}</span>
      <ul class="tight">${result.drawings.map((d) => html`<li key=${d.graph_id}>${d.drawing_number || d.graph_id}: ${d.files.join(", ")}
        ${d.stats && (d.stats.excluded_components || d.stats.excluded_connections || d.stats.excluded_attributes) ? html`<span class="muted small"> · 뺀 구성요소 ${d.stats.excluded_components || 0} · 연결 ${d.stats.excluded_connections || 0} · 속성 ${d.stats.excluded_attributes || 0}</span>` : null}</li>`)}</ul>
      ${result.not_exported.length ? html`<div class="muted small">내보내지 않은 쪽: ${result.not_exported.map((x) => (x.drawing_number || x.graph_id) + "(" + (STATE_TEXT[x.state] || x.state) + ", 남은 미확인 " + x.unconfirmed + ")").join(" · ")}</div>` : null}</div>` : null}</div>`;
}

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
        <${Icon} name="upload" size=${22} /><div><b>도면 파일을 여기에 끌어 놓으세요</b><br /><span>.drawio, .pdf, DEXPI .xml 여러 개 · 눌러서 고르기</span></div></div>
      ${running.map(([id, j]) => html`<div class="card" key=${id}>
        <div class="kv"><div class="k"><b>${j.label}</b><span>${j.state === "failed" ? j.message : (j.text || "준비 중")}${j.total ? " (" + j.done + "/" + j.total + ")" : ""}</span></div>
          ${j.state === "running" ? html`<${Icon} name="loader-2" cls="spin" />` : j.state === "done" ? html`<${Chip} kind="ok" icon="check">완료<//>` : html`<${Chip} kind="err" icon="alert-triangle">실패<//>`}</div>
          ${j.state === "done" && j.result && j.result.ai_review && j.result.ai_review.ran ? html`<${Chip} kind="ai" icon="sparkles">AI 후보 ${j.result.ai_review.candidates}개<//>` : null}</div>`)}
      <div class="card"><h3>추출 설정</h3>
        <div class="kv"><div class="k"><b>AI 검토</b><span>추출 뒤 AI가 미확인 항목의 후보를 제안합니다(구독 한도를 씁니다). 처음 값은 꺼짐이고, 한 번 실행에 최대 ${app.ai_review_run_cap}회까지 부릅니다.</span></div>
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
      <${DexpiExport} />
      ${data.documents.length ? html`<div><div class="muted" style="font-size:var(--fs-sm);margin-bottom:6px">등록 자료 ${data.documents.length}건</div><div class="list">
        ${data.documents.map((d) => html`<div class="row" key=${d.material_id + ":" + d.version}><div class="main"><b>${d.name || d.material_id}</b><span>버전 ${d.version} · ${d.type}</span></div>
          <${Chip} kind=${d.status === "registered" ? "ok" : "warn"}>${d.status === "registered" ? "등록됨" : d.status}<//>${d.graphed ? html`<${Chip} kind="accent">그래프<//>` : null}</div>`)}</div></div>` : null}
    </div></section>`;
}
