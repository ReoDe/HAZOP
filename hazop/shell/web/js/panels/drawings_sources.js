// 같은 시트 자리에 원본이 둘 이상일 때 프로젝트 그래프에 쓸 것을 사람이 고르는 카드(DEXPI 규격 §4.2 (나), 시트 정체 U4).
// 줄은 엔진(hazop.graph.sources.conflicts)이 준 그대로 보인다: 형식이 다르면(kind format) 형식을, 같은 형식의 다른 파일이면(kind file) 파일을 고른다.
// 고르기 전에는 먼저 쓰던 것을 쓴다. 갈아타기 전에 '지금 도면 위의 구간 n개가 다시 확인 대상이 됩니다'를 보이고 확인을 받는다.
// 갈아타면 엔진이 검토구간을 이어서 맞추고(자동 반영), 잃은 것이 있으면 알림 줄이 뜬다. 정착이 들이지 못한 도면(settle_rebuild_failed)은 사유만 보인다.
import { html } from "../ui/html.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { cmd, onChanged, read } from "../bridge.js";
import { store } from "../store.js";
import { Btn, Chip, Notice } from "../ui/parts.js";

const FORMAT = { drawio: "drawio", pdf_vector: "PDF", dexpi: "DEXPI" };
const fmt = (f) => FORMAT[f] || f || "형식 모름";

/** 갈아타기 미리 알림 글. 후보마다 엔진이 센 수(recheck)를 쓴다: 지금 쓰는 파일이면 바뀌는 것이 없다(검토 지적 3). */
export function previewText(c, x) {
  if (x && x.using) return "지금 쓰는 원본입니다. 사람이 고른 것으로 붙박을 뿐 도면과 구간은 그대로입니다.";
  if (unknownImpact(c, x)) return "구간 파일을 읽지 못해 이 원본으로 바꿨을 때 다시 확인할 구간이 몇 개인지 알 수 없습니다. 구간 패널에서 먼저 확인하거나, 영향을 모른 채 바꾸려면 아래에서 한 번 더 확인하세요.";
  const n = x && typeof x.recheck === "number" ? x.recheck : (c.nodes_on_sheet || 0);
  const firm = x && typeof x.released === "number" ? x.released : (c.confirmed_on_sheet || 0);
  return n ? "이 원본으로 바꾸면 지금 도면 위의 구간 " + n + "개가 다시 확인 대상이 됩니다."
      + (firm ? " 그 가운데 확정한 구간 " + firm + "개는 확정이 풀립니다(다시 확인한 뒤 확정하세요)." : "")
      + " 같은 기호로 증명되지 않는 구성요소는 '찾지 못한 구성요소'로 남습니다."
    : "이 도면에는 아직 구간이 없어 바꿔도 다시 확인할 것이 없습니다.";
}

/** 엔진이 구간 파일을 읽지 못해 수를 셀 수 없음(검토 ⑥ 나: 0으로 '다시 확인할 것이 없다'고 안심시키지 않는다). */
export const unknownImpact = (c, x) => !(x && x.using) && (!!c.nodes_unknown || (!!x && x.recheck === null));

/** 이 줄에서 지금 쓰지 않는 파일 이름(밀린 파일). */
const idle = (c) => (c.candidates || []).filter((x) => !x.in_use && x.file).map((x) => x.file);

const fileChoice =(c, x, withFormat) => ({ key: x.material_id, kind: "file",
  label: (x.file || "파일") + (withFormat ? " (" + fmt(x.format) + ")" : "") + (x.modified ? " · " + x.modified : ""),
  args: { drawing_number: c.graph_id, material_id: x.material_id }, using: !!x.in_use, recheck: x.recheck });

/** 한 줄의 고를 수 있는 것: [{key, kind, label, args, using, recheck}]. 파일 줄은 파일마다. 형식 줄은 형식마다 고르고, 한 형식에 파일이
 *  둘 이상이면 파일로도 고른다(검토 지적 1: pdf a·drawio b·pdf c에서 형식 단추만으로는 a로 돌아갈 길이 없었다). */
export function choicesOf(c) {
  if (c.reason === "settle_rebuild_failed") return [];
  if (c.kind === "file") return c.candidates.map((x) => fileChoice(c, x, false));
  const byFormat = (f) => c.candidates.filter((x) => x.format === f);
  const out = c.formats.map((f) => ({ key: f, kind: "format", label: fmt(f), args: { drawing_number: c.drawing_number || c.graph_id, format: f },
    using: f === c.in_use_format && byFormat(f).length < 2,
    recheck: f === c.in_use_format ? (byFormat(f).length < 2 ? 0 : undefined) : (byFormat(f)[0] || {}).recheck }));
  if (c.formats.some((f) => byFormat(f).length > 1) && c.candidates.every((x) => x.material_id)) {
    // 한 형식에 파일이 둘 이상이면 파일 단추만 둔다(실제 창 4·5차: 형식 단추와 파일 단추가 같은 일을 하는 단추로 함께 보였다). 파일 단추에 형식을 적는다
    return c.candidates.map((x) => fileChoice(c, x, true));
  }
  return out;
}

/** 같은 번호의 다른 원본에 밀려 지금 분석에 쓰지 않는 파일: {material_id: 알림 글}. 도면 패널의 등록 자료 줄이 쓴다(밀린 파일은 도면 목록에 없다). */
export function displacedOf(info) {
  const out = {};
  for (const c of (info && info.conflicts) || []) {
    const using = c.in_use_file || fmt(c.in_use_format);
    for (const x of c.candidates || []) {
      if (!x.in_use && x.material_id) out[x.material_id] = "같은 번호 " + c.display + "의 " + using + "에 밀려 지금 분석에 쓰지 않습니다. 도면 패널의 원본 고르기 카드에서 바꿀 수 있습니다.";
    }
  }
  return out;
}

/** 원본이 둘 이상인 도면: {graph_id: 원본 수}. 도면 줄의 칩이 쓴다. */
export function choicesCount(info) {
  const out = {};
  for (const c of (info && info.conflicts) || []) out[c.graph_id] = (c.candidates || []).length || (c.formats || []).length;
  return out;
}

export function SourceConflicts() {
  const [info, setInfoRaw] = useState(null);
  const setInfo = (v) => { setInfoRaw(v); store.set({ sources: v }); };      // 도면 줄·등록 자료 줄의 '원본 n개'·'쓰이지 않음' 표시가 같은 값을 본다
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(null);      // {c, x}: 갈아타기 확인 중
  const [blindOk, setBlindOk] = useState(false);   // 영향을 모른 채 바꾸기를 한 번 더 확인함
  const [unapplied, setUnapplied] = useState(null);      // 고른 뒤 검토구간 반영에 실패했을 때의 글(검토 지적 2)
  const reload = () => read("sources").then(setInfo).catch(() => setInfo({ conflicts: [] }));
  useEffect(() => { reload(); return onChanged((t) => { if (t === "sources" || t === "drawings") reload(); }); }, []);
  async function choose(x) {
    setBusy(true); setError(""); setAsking(null); setUnapplied(null);
    try {
      const r = await cmd("sources.choose", x.args);
      if (r && r.applied === false) setUnapplied(r.apply_text || "검토구간에 도면 변경을 반영하지 못했습니다.");
    } catch (e) { setError(e.message || "고르지 못했습니다."); }
    setBusy(false);
    reload();
  }
  async function catchUp() {
    setBusy(true);
    try { await cmd("nodes.catch_up", { project_id: store.get().drawings.project_id }); setUnapplied(null); }
    catch (e) { setUnapplied(e.message || "도면 변경을 반영하지 못했습니다."); }
    setBusy(false);
  }
  if (!info || !info.conflicts.length) return null;
  return html`<div class="card src-card" id="src-card" aria-label="같은 도면 자리의 원본 고르기"><h3>같은 도면 자리에 원본이 둘 이상 있습니다</h3>
    <div class="muted small">분석에 쓸 원본을 고르세요. 다른 원본의 기록은 지우지 않으며 다시 고르면 되돌아옵니다.</div>
    <div class="list" role="list" aria-label="고를 원본이 있는 도면">${info.conflicts.map((c) => {
      const choices = choicesOf(c);
      const picked = !!(c.chosen_material || c.chosen);       // 사람이 형식이나 파일을 고름
      return html`<div class="row src-row" role="listitem" key=${c.graph_id}>
        <div class="main"><b>${c.display}</b>
          ${c.text ? html`<span>${c.text}</span>` : null}
          ${choices.length ? html`<span>지금 쓰는 것: ${c.kind === "file" ? (c.in_use_file || "먼저 있던 파일") : (c.in_use_file ? c.in_use_file + " (" + fmt(c.in_use_format) + ")" : fmt(c.in_use_format))}${picked ? " (사람이 고름)" : " (먼저 있던 것)"}</span>` : null}
          ${idle(c).length ? html`<span class="muted">쓰이지 않음: ${idle(c).join(", ")}</span>` : null}</div>
        <div class="acts">${choices.map((x) => (x.using && picked
          ? html`<${Chip} kind="ok" icon="check" key=${x.key}>${x.label} 쓰는 중<//>`
          : html`<${Btn} sm=${true} key=${x.key} label=${c.display + ": " + x.label + " 쓰기"} disabled=${busy}
              onClick=${() => { setBlindOk(false); setAsking({ c, x }); }}>${x.label} 쓰기<//>`))}</div>
        ${asking && asking.c.graph_id === c.graph_id ? html`<div class="src-ask" role="alertdialog" aria-label="원본 바꾸기 확인">
          <div>${previewText(c, asking.x)}</div>
          ${unknownImpact(c, asking.x) ? html`<label class="small"><input type="checkbox" checked=${blindOk} onChange=${(e) => setBlindOk(e.target.checked)} /> 영향을 모른 채 바꿉니다</label>` : null}
          <div class="acts-row"><${Btn} sm=${true} kind="primary" label=${asking.x.label + "로 바꾸기"} disabled=${busy || (unknownImpact(c, asking.x) && !blindOk)} onClick=${() => choose(asking.x)}>바꾸기<//>
            <${Btn} sm=${true} label="바꾸지 않기" onClick=${() => setAsking(null)}>취소<//></div></div>` : null}</div>`;
    })}</div>
    ${unapplied ? html`<${Notice} kind="warn" icon="alert-triangle">${unapplied}
      <div class="acts-row"><${Btn} sm=${true} kind="primary" label="도면 변경 반영하기" disabled=${busy} onClick=${catchUp}>도면 변경 반영하기<//></div><//>` : null}
    ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error}<//>` : null}</div>`;
}
