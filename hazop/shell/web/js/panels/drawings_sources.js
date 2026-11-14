// 같은 도면 번호의 원본이 형식 둘 이상으로 들어왔을 때(drawio·PDF·DEXPI) 어느 쪽을 프로젝트 그래프에 쓸지 사람이 고르는 카드(DEXPI 규격 §4.2 (나)).
// 충돌 사실과 '지금 쓰는 형식'은 엔진(hazop.graph.sources)이 준 값을 그대로 보이고, 고른 형식만 명령으로 보낸다. 고르기 전에는 먼저 있던 형식을 쓴다.
import { html } from "../ui/html.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Btn, Chip, Notice } from "../ui/parts.js";

const FORMAT = { drawio: "drawio", pdf_vector: "PDF", dexpi: "DEXPI" };
const fmt = (f) => FORMAT[f] || f || "형식 모름";

export function SourceConflicts() {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reload = () => read("sources").then(setInfo).catch(() => setInfo({ conflicts: [] }));
  useEffect(() => { reload(); return onChanged((t) => { if (t === "sources" || t === "drawings") reload(); }); }, []);
  async function choose(c, f) {
    setBusy(true); setError("");
    try { await cmd("sources.choose", { drawing_number: c.drawing_number, format: f }); } catch (e) { setError(e.message || "고르지 못했습니다."); }
    setBusy(false);
    reload();
  }
  if (!info || !info.conflicts.length) return null;
  return html`<div class="card src-card" aria-label="같은 도면 번호의 원본 선택"><h3>같은 도면 번호의 원본이 여러 형식으로 있습니다</h3>
    <div class="muted small">어느 형식을 프로젝트 그래프에 쓸지 고르세요. 고르기 전에는 먼저 있던 형식을 씁니다. 다른 형식의 읽은 결과와 수정 기록은 지우지 않고 그대로 두며, 다시 고르면 바로 되돌아옵니다.</div>
    <div class="list" role="list" aria-label="형식이 섞인 도면">${info.conflicts.map((c) => html`<div class="row src-row" role="listitem" key=${c.drawing_number}>
      <div class="main"><b>${c.drawing_number}</b>
        <span>${c.candidates.map((x) => fmt(x.format) + " " + x.modified).join(" · ")}</span>
        <span>지금 쓰는 것: ${fmt(c.in_use_format)}${c.chosen ? " (사람이 고름)" : " (먼저 있던 형식)"}</span></div>
      <div class="acts">${c.formats.map((f) => (f === c.in_use_format && c.chosen
        ? html`<${Chip} kind="ok" icon="check" key=${f}>${fmt(f)} 쓰는 중<//>`
        : html`<${Btn} sm=${true} key=${f} label=${c.drawing_number + ": " + fmt(f) + " 쓰기"} disabled=${busy} onClick=${() => choose(c, f)}>${fmt(f)} 쓰기<//>`))}</div></div>`)}</div>
    ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}</div>`;
}
