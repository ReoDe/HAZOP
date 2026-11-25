// 도면 패널(규격 §2.1·§2.3 ①등록 줄). 끌어 놓기 자리(파일은 Qt가 받는다), 도면·문서 목록(줄을 누르면 열림, 줄의 체크로 분석에서 빼기·다시 넣기), 작업 줄.
import { Fragment, html } from "../ui/html.js";
import { store, useStore } from "../store.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Icon } from "../ui/icon.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import { SourceConflicts, choicesCount, displacedOf } from "./drawings_sources.js";
import { focusSheet as openTitleblock } from "./titleblock.js";
import { DrawingExcludedChip, DrawingPicks } from "./nodes_screen.js";
import { ReviewChip } from "../review/review.js";      // 도면별 AI 검토 시작(자동 확정이 들어오기 전까지 유일한 길: 별도 커밋에서 뺀다)

function toastError(e) { store.set({ toast: { text: e.message, kind: "err" } }); }

/** DEXPI 내보내기(항목 11): 단추 하나. 내보낼 수 있는(쪽 확정을 마친) 쪽을 모두 한 번에 낸다. 저장 폴더는 창이 대화상자로 한 번 묻고 웹은 경로를 보내지 않는다.
 *  고르는 창·설명 줄은 없다. 낼 수 있는 쪽이 없으면 단추가 꺼져 있다. 끝나면 한 줄로 몇 쪽을 어느 폴더에 냈는지와 내보내지 못한 쪽 수만 보인다. */
function DexpiExport() {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState(null);
  const jobs = useStore((s) => s.jobs);          // 선택 함수가 jobId를 붙들면 낡은 값을 보므로 전체를 받아 고른다
  const job = jobId ? jobs[jobId] : null;
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const reload = () => read("dexpi").then(setInfo).catch(() => setInfo({ drawings: [], any: false }));
  useEffect(() => { reload(); return onChanged((t) => { if (t === "sheetconf" || t === "drawings") reload(); }); }, []);
  useEffect(() => {
    if (!job) return;
    if (job.state === "done") { setBusy(false); setResult(job.result); setJobId(null); reload(); }
    else if (job.state === "failed" || job.state === "stopped") { setBusy(false); setError(job.state === "stopped" ? "" : (job.message || "내보내지 못했습니다.")); setJobId(null); reload(); }
  }, [job && job.state]);
  async function run() {
    setBusy(true); setError(""); setResult(null);
    try { const r = await cmd("dexpi.export", { graph_ids: info.drawings.filter((d) => d.exportable).map((d) => d.graph_id) }); setJobId(r.job); }
    catch (e) { setError(e.message || "내보내지 못했습니다."); setBusy(false); reload(); }
  }
  if (!info || !info.drawings.length) return null;
  const done = result && !result.cancelled ? result : null;
  return html`<div class="dexpi-card"><div class="acts-row"><${Btn} kind="primary" sm=${true} icon="file-export" label="DEXPI로 내보내기" disabled=${busy || !info.any} onClick=${run}>DEXPI로 내보내기<//>
    ${done ? html`<span class="muted small">${done.drawings.length}쪽을 내보냈습니다 · 폴더 ${done.folder}${done.not_exported.length ? " · 내보내지 못한 쪽 " + done.not_exported.length : ""}</span>` : null}</div>
    ${error ? html`<${Notice} kind="err" icon="alert-triangle"><span style="white-space:pre-wrap">${error}</span><//>` : null}</div>`;
}

/** 끝난 작업 카드를 닫는다(작업 기록은 엔진에 그대로). */
function dismissJob(id) { store.set((s) => { const j = Object.assign({}, s.jobs); delete j[id]; return { jobs: j }; }); }

export function DrawingsPanel({ onOpen, onClose }) {
  const data = useStore((s) => s.drawings);
  const sheet = useStore((s) => s.sheet);
  const jobs = useStore((s) => s.jobs);
  const over = useStore((s) => s.dropOver);
  // 작업 카드: 도는 것과 끝난 것 가운데 가장 새 것 둘만(멈춘 것은 알림으로 끝: 카드로 쌓여 도면 줄의 단추를 밀어내지 않게, 실제 창 3차 결함 4)
  // 작업 표시가 도면 줄을 밀지 않게(실제 창 4차 결함 4): AI 검토 작업은 도면 줄의 칩이 진행과 멈추기·취소를 보이므로 따로 그리지 않고,
  // 다른 도는 작업은 한 줄로, 끝난 작업은 접힌 '끝난 작업 n개' 안에 둔다(멈춘 작업은 알림으로 끝)
  const all = Object.entries(jobs).filter(([, j]) => j.state !== "stopped" && !/^AI 검토/.test(String(j.label || "")));
  const running = all.filter(([, j]) => j.state === "running");
  const ended = all.filter(([, j]) => j.state !== "running");
  const failedJobs = ended.filter(([, j]) => j.state === "failed");
  const [picked, setPicked] = useState([]);          // 줄 왼쪽 체크로 고른 도면
  const toggle = (g) => setPicked((p) => (p.includes(g) ? p.filter((x) => x !== g) : [...p, g]));
  const sources = useStore((s) => s.sources);          // 원본 고르기 카드가 읽어 둔 값(같은 번호의 다른 원본)
  const many = choicesCount(sources), idle = displacedOf(sources);
  const toCard = () => { const el = document.getElementById("src-card"); if (el) el.scrollIntoView({ block: "nearest" }); };

  const pick = () => cmd("register.pick").catch(toastError);

  return html`<section class="panel" aria-label="도면">
    <div class="panel-h"><h2>도면</h2><span class="acts"><${Btn} kind="ghost" icon="x" label="패널 닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      <div class=${"drop" + (over ? " over" : "")} role="button" tabindex="0" aria-label="도면 파일 고르기" onClick=${pick}
        onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } }}>
        <${Icon} name="upload" size=${22} /><div><b>도면 파일을 여기에 끌어 놓으세요</b><br /><span>.drawio, .pdf, DEXPI .xml 여러 개 · 눌러서 고르기</span></div></div>
      ${running.map(([id, j]) => html`<div class="job-line" key=${id} role="status"><${Icon} name="loader-2" cls="spin" size=${14} />
        <b>${j.label}</b><span class="muted small">${j.text || "준비 중"}${j.total ? " (" + j.done + "/" + j.total + ")" : ""}</span></div>`)}
      ${ended.length ? html`<details class="jobs-done" open=${failedJobs.length > 0}><summary class="muted small">끝난 작업 ${ended.length}개${failedJobs.length ? " · 실패 " + failedJobs.length : ""}</summary>
        ${ended.map(([id, j]) => html`<div class="job-line" key=${id}>${j.state === "done" ? html`<${Chip} kind="ok" icon="check">완료<//>` : html`<${Chip} kind="err" icon="alert-triangle">실패<//>`}
          <b>${j.label}</b><span class="muted small">${j.state === "failed" ? j.message : (j.text || "")}</span>
          ${j.state === "done" && j.result && j.result.ai_review && j.result.ai_review.ran ? html`<${Chip} kind="ai" icon="sparkles">AI 후보 ${j.result.ai_review.candidates}개<//>` : null}
          <${Btn} sm=${true} kind="ghost" icon="x" label=${j.label + " 알림 닫기"} title="닫기" onClick=${() => dismissJob(id)} /></div>`)}</details>` : null}
      <div>${picked.length ? html`<${DrawingPicks} ids=${picked} onDone=${() => setPicked([])} />` : null}
        ${data.drawings.length === 0 ? html`<${Notice}>등록된 도면이 없습니다.<//>` : html`<div class="list">
          ${data.drawings.map((d) => html`<div key=${d.graph_id} class=${"row drow" + (d.graph_id === sheet ? " on" : "")} onClick=${(e) => { if (!e.target.closest("input,label,.acts-end")) onOpen(d.graph_id); }}>
            <input type="checkbox" aria-label=${d.display + " 고르기"} checked=${picked.includes(d.graph_id)} onChange=${() => toggle(d.graph_id)} />
            <button type="button" class="main drow-open" aria-label=${d.display + (d.title ? " " + d.title : "") + " 열기"}><b>${d.display}</b><span>${d.title || ""}</span></button>
            <span class="acts-end">
              ${many[d.graph_id] ? html`<${Btn} sm=${true} kind="ghost" label=${d.display + " 원본 " + many[d.graph_id] + "개, 고르기 카드로 가기"}
                title="같은 도면 자리에 원본이 둘 이상 있습니다. 분석에 쓸 원본은 아래 원본 고르기 카드에서 고릅니다." onClick=${toCard}>원본 ${many[d.graph_id]}개<//>` : null}
              <${DrawingExcludedChip} graphId=${d.graph_id} />
              <${ReviewChip} gid=${d.graph_id} />
              <${Btn} sm=${true} kind="ghost" label=${d.display + " 표제란"} title=${d.title ? "표제란 확정·고치기" : "표제란을 확인해 도면 번호와 제목을 확정합니다"} onClick=${() => openTitleblock(d.graph_id)}>표제란<//></span></div>`)}</div>`}</div>
      <${SourceConflicts} />
      <${DexpiExport} />
      ${data.documents.length ? html`<div><div class="muted" style="font-size:var(--fs-sm);margin-bottom:6px">등록 자료 ${data.documents.length}건</div><div class="list">
        ${data.documents.map((d) => html`<div class="row" key=${d.material_id + ":" + d.version}><div class="main"><b>${d.name || d.material_id}</b><span>버전 ${d.version} · ${d.type}</span></div>
          <${Chip} kind=${d.status === "registered" ? "ok" : "warn"}>${d.status === "registered" ? "등록됨" : d.status}<//>${idle[d.material_id]
            ? html`<${Chip} kind="warn" title=${idle[d.material_id]}>쓰이지 않음<//>`
            : d.graphed ? html`<${Chip} kind="accent">그래프<//>` : null}</div>`)}</div></div>` : null}
    </div></section>`;
}
