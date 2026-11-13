// 지식그래프 패널(완료 목록 2 A6, INTENT §3.3): 프로젝트 전체 도면을 한 그래프로 보는 밝은 화면(옵시디언 그래프 보기처럼 색은 절제).
// 노드를 누르면 오른쪽에 무엇인지·근거·이웃이 나오고 '도면에서 보기'로 그 구성요소로 간다. 잠재 후보는 엔진이 정한 상태와 허용 동작만 보이고
// 판단은 엔진에 맡긴다. 큰 그래프는 엔진이 도면별 묶음으로 먼저 주고(노드 수 상한), 묶음을 누르면 펼친다.
// 그리기 라이브러리는 이미 묶인 hazop/kg/vendor의 force-graph를 읽기 API(/api/kg/force-graph.js)로 받는다. 도면·모델에서 온 글은 ${}로만 넣는다.
import { html } from "../ui/html.js";
import { useEffect, useRef, useState } from "../../vendor/hooks.module.js";
import { Icon } from "../ui/icon.js";
import { Btn, Chip, Notice } from "../ui/parts.js";
import { store } from "../store.js";
import * as K from "./kg_state.js";

const cssHref = new URL("kg.css", import.meta.url).href;
if (typeof document !== "undefined" && !document.querySelector("link[data-kg-css]")) {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = cssHref; l.setAttribute("data-kg-css", "");
  document.head.appendChild(l);
}

// 색은 절제: 도면 노드는 회색 계열, 지식은 녹색 하나, 잠재 후보는 공백(기대됨·부재 확정)만 호박색. 고른 것만 파랑.
const C = { bg: "#fbfbfc", pid: "#8a94a1", equip: "#4b5563", seg: "#c3c9d1", kn: "#3f8f63", gap: "#d9a23a", found: "#6b8fc4", quiet: "#c9ced5",
  group: "#9aa5b4", link: "#dde1e6", linkHi: "#0a5fc2", sel: "#0a5fc2", ink: "#2a313b", faint: "#9aa1aa" };
const TYPE_NAMES = { equipment: "설비", valve: "밸브", instrument: "계장", inline_component: "배관 부품", piping_element: "배관 요소", pipe_segment: "배관 분기",
  unclassified: "미분류", document: "문서", doc_chunk: "문서 조각", requirement: "요건", setpoint: "설정치", condition: "운전조건·설계값",
  analysis_case: "해석 사례", expectation: "잠재 후보", sheet: "도면", kn: "도면 밖 지식" };
const LAYER_NAMES = { pid: "도면", kn: "지식", exp: "잠재 후보", group: "묶음" };
const GAP = new Set(["expected", "confirmed_absent"]);
const SHOWN_STATES = new Set(["expected", "candidate_found", "confirmed_absent"]);
const STATE_KIND = { expected: "warn", candidate_found: "accent", confirmed_absent: "warn", confirmed_present: "ok", not_applicable: "plain" };

function colorOf(n) {
  if (n.layer === "group") return C.group;
  if (n.layer === "kn") return C.kn;
  if (n.layer === "exp") return GAP.has(n.xs) ? C.gap : n.xs === "candidate_found" ? C.found : C.quiet;
  if (n.type === "pipe_segment") return C.seg;
  return n.type === "equipment" ? C.equip : C.pid;
}

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const idOf = (x) => (x && typeof x === "object" ? x.id : x);
let fgPromise = null;
function loadForceGraph() {
  if (window.ForceGraph) return Promise.resolve(window.ForceGraph);
  if (!fgPromise) {
    fgPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "/api/kg/force-graph.js";
      s.onload = () => (window.ForceGraph ? resolve(window.ForceGraph) : reject(new Error("그리기 라이브러리를 읽지 못했습니다.")));
      s.onerror = () => { fgPromise = null; reject(new Error("그리기 라이브러리를 읽지 못했습니다.")); };
      document.head.appendChild(s);
    });
  }
  return fgPromise;
}

/** 보일 노드·관계: 꺼 둔 층과 기본으로 숨긴 잠재 후보 상태(확인됨·무관)를 뺀다. 고른 노드는 늘 보인다. */
function visible(graph, layers, allStates, selected) {
  if (!graph) return { nodes: [], links: [] };
  const keep = new Set();
  for (const n of graph.nodes) {
    if (n.id === selected) { keep.add(n.id); continue; }
    if (n.layer !== "group" && layers[n.layer] === false) continue;
    if (n.layer === "exp" && !allStates && !SHOWN_STATES.has(n.xs)) continue;
    keep.add(n.id);
  }
  return { nodes: graph.nodes.filter((n) => keep.has(n.id)), links: graph.links.filter((l) => keep.has(l.s) && keep.has(l.t)) };
}

function GraphCanvas() {
  const host = useRef(null);
  const fg = useRef(null);
  const known = useRef(new Map());     // id -> 노드 객체(다시 그려도 자리를 지키게)
  const [failed, setFailed] = useState(null);
  const graph = K.useKg((s) => s.graph);
  const layers = K.useKg((s) => s.layers);
  const allStates = K.useKg((s) => s.allStates);
  const selected = K.useKg((s) => s.selected);
  const seq = K.useKg((s) => s.seq);
  const hover = useRef(null);
  const near = useRef(new Set());

  useEffect(() => {
    let alive = true;
    loadForceGraph().then((ForceGraph) => {
      if (!alive || !host.current) return;
      const g = ForceGraph()(host.current)
        .backgroundColor(C.bg).nodeId("id").linkSource("source").linkTarget("target")
        .nodeRelSize(4).cooldownTicks(160).d3VelocityDecay(0.35)
        .nodeLabel((n) => esc(n.layer === "group" ? n.label + " · 노드 " + n.count + " (눌러 펼치기)" : (n.label || TYPE_NAMES[n.type] || n.type)))   // 라이브러리가 innerHTML로 넣으므로 글자로 거른다
        .linkColor((l) => (near.current.size && (near.current.has(idOf(l.source)) && near.current.has(idOf(l.target))) ? C.linkHi
          : l.st === "recheck" ? C.gap : l.st === "excluded" ? C.quiet : C.link))
        .linkWidth((l) => (l.kind === "group" ? Math.min(4, 1 + Math.log2(l.n || 1)) : (near.current.size && near.current.has(idOf(l.source)) && near.current.has(idOf(l.target)) ? 1.6 : 0.8)))
        .linkDirectionalArrowLength((l) => (l.flow ? 3 : 0)).linkDirectionalArrowRelPos(0.6)
        .linkLineDash((l) => (l.st === "recheck" ? [1, 2] : l.st === "excluded" ? [4, 3] : l.kind === "expects" || l.kind === "satisfied_by" || l.st === "candidate" ? [2, 2] : null))
        .nodeCanvasObject((n, ctx, scale) => drawNode(n, ctx, scale, K.kg.get().selected, hover.current, near.current))
        .nodePointerAreaPaint((n, color, ctx) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(n.x, n.y, radius(n) + 2, 0, 2 * Math.PI); ctx.fill(); })
        .onNodeHover((n) => { hover.current = n ? n.id : null; host.current.style.cursor = n ? "pointer" : ""; })
        .onNodeClick((n) => { if (n.layer === "group") K.expand(n.group); else K.select(n.id); })
        .onEngineStop(() => {
          // 배치가 멈춘 뒤에 맞춘다(움직이는 동안 가운데를 맞추면 노드가 화면 밖으로 흘러간다). 고를 노드가 있으면 그 노드로, 없으면 전체 맞춤
          g.__running = false;
          const id = g.__centerAfter;
          const n = id ? known.current.get(id) : null;
          if (id && n && n.x !== undefined) { g.__centerAfter = null; g.__fitPending = false; centerOn(g, id); }
          else if (!id && g.__fitPending) { g.__fitPending = false; g.zoomToFit(400, 40); }   // 고를 노드가 아직 그래프에 없으면 다음 배치가 멈출 때까지 기다린다
        });
      g.__centerAfter = K.kg.get().center;      // 패널이 열리기 전에 찾기·채팅이 고른 노드
      fg.current = g;
      if (store.get().app.debug) window.__hzKg = g;     // 시험 갈고리: 디버그 실행에서만(실제 창 검증이 노드 화면 자리를 읽는다)
      const size = () => { if (host.current) g.width(host.current.clientWidth).height(host.current.clientHeight); };
      size();
      const ro = new ResizeObserver(size);
      ro.observe(host.current);
      fg.current.__ro = ro;
      push(true);
    }).catch((e) => setFailed(e.message));
    return () => { alive = false; if (fg.current) { fg.current.__ro && fg.current.__ro.disconnect(); fg.current.pauseAnimation(); fg.current._destructor && fg.current._destructor(); fg.current = null; } };
  }, []);

  function push(fitAfter) {
    const g = fg.current;
    if (!g) return;
    const v = visible(K.kg.get().graph, K.kg.get().layers, K.kg.get().allStates, K.kg.get().selected);
    const map = known.current;
    const next = new Map();
    const nodes = v.nodes.map((n) => { const old = map.get(n.id); const o = old ? Object.assign(old, n) : Object.assign({}, n); next.set(n.id, o); return o; });
    known.current = next;
    const links = v.links.map((l) => Object.assign({}, l, { source: l.s, target: l.t }));
    const fresh = nodes.some((n) => n.x === undefined);
    g.cooldownTicks(fresh || fitAfter ? 160 : 0);     // 새 노드가 없으면 배치를 다시 돌리지 않는다(판단 뒤 그림이 흩어지지 않게)
    g.__running = fresh || fitAfter;
    g.graphData({ nodes, links });
    if (fitAfter || fresh) g.__fitPending = true;
  }

  useEffect(() => { push(false); }, [graph, layers, allStates]);
  useEffect(() => {
    const g = fg.current;
    near.current = new Set();
    if (selected && g) {
      near.current.add(selected);
      for (const l of (K.kg.get().graph || { links: [] }).links) {
        if (l.s === selected) near.current.add(l.t);
        if (l.t === selected) near.current.add(l.s);
      }
    }
    if (g) g.linkWidth(g.linkWidth());      // 멈춘 그래프는 스스로 다시 그리지 않으므로 강조를 바로 보이게 한 번 다시 그린다
  }, [selected, graph]);
  useEffect(() => {
    const g = fg.current;
    if (!g || !seq) return;
    const id = K.kg.get().center;
    if (!id) { g.zoomToFit(400, 40); return; }
    const n = known.current.get(id);
    if (g.__running || !n || n.x === undefined) { g.__centerAfter = id; return; }       // 배치가 도는 중이거나 아직 없는 노드면 멈춘 뒤에(onEngineStop)
    centerOn(g, id);
  }, [seq]);

  function centerOn(g, id) {
    let tries = 0;
    const go = () => {
      const n = known.current.get(id);
      if (n && n.x !== undefined) { g.centerAt(n.x, n.y, 500); g.zoom(Math.max(g.zoom(), 3), 500); }
      else if (tries++ < 20) setTimeout(go, 100);
    };
    go();
  }

  return html`<div class="kg-canvas" ref=${host} role="img" aria-label="지식그래프 그림. 노드를 누르면 오른쪽에 상세가 나옵니다. 키보드로는 찾기 칸을 쓰세요.">
    ${failed ? html`<div class="center-empty"><p>${failed}</p></div>` : null}</div>`;
}

function radius(n) {
  if (n.layer === "group") return 6 + Math.min(18, Math.sqrt(n.count || 1));
  if (n.layer === "exp") return 3.2;
  if (n.type === "pipe_segment") return 2;
  return n.type === "equipment" ? 5 : 3.6;
}

function drawNode(n, ctx, scale, selected, hover, near) {
  const r = radius(n);
  const dim = near.size && !near.has(n.id);
  ctx.globalAlpha = dim ? 0.25 : 1;
  ctx.beginPath();
  if (n.layer === "exp") {
    ctx.moveTo(n.x, n.y - r - 0.6); ctx.lineTo(n.x + r + 0.6, n.y); ctx.lineTo(n.x, n.y + r + 0.6); ctx.lineTo(n.x - r - 0.6, n.y); ctx.closePath();
  } else ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
  if (n.layer === "exp" && n.xs === "expected") { ctx.fillStyle = C.bg; ctx.fill(); ctx.lineWidth = 1.4; ctx.strokeStyle = C.gap; ctx.stroke(); }
  else if (n.layer === "kn" && (n.ks !== "confirmed" || n.ai)) {
    // 확인 전 지식(미확인·가설)과 AI 초안은 속이 빈 원으로, AI 초안은 점선 테로 확정 지식과 갈라 보인다
    ctx.fillStyle = C.bg; ctx.fill(); ctx.lineWidth = 1.4; ctx.strokeStyle = C.kn;
    if (n.ai) ctx.setLineDash([1.5, 1.2]);
    ctx.stroke(); ctx.setLineDash([]);
  } else { ctx.fillStyle = colorOf(n); ctx.fill(); }
  if (n.recheck) { ctx.lineWidth = 1; ctx.setLineDash([1.5, 1.5]); ctx.strokeStyle = C.gap; ctx.beginPath(); ctx.arc(n.x, n.y, r + 2.5, 0, 2 * Math.PI); ctx.stroke(); ctx.setLineDash([]); }
  if (n.id === selected) { ctx.lineWidth = 2 / Math.max(scale, 0.5); ctx.strokeStyle = C.sel; ctx.beginPath(); ctx.arc(n.x, n.y, r + 3, 0, 2 * Math.PI); ctx.stroke(); }
  // 큰 노드(설비)는 맞춤 배율에서도 이름을 보인다. 나머지는 고르거나 가리키거나 확대하면 나온다
  const show = n.layer === "group" || n.type === "equipment" || n.id === selected || n.id === hover || (near.size && near.has(n.id)) || scale > 2.2;
  if (show && n.label) {
    const fs = Math.max(9 / scale, n.layer === "group" ? 4.5 : 3);
    ctx.font = (n.layer === "group" || n.id === selected ? "600 " : "") + fs + "px " + "Malgun Gothic, sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    ctx.fillStyle = n.layer === "group" ? C.ink : (dim ? C.faint : C.ink);
    ctx.fillText(n.layer === "group" ? n.label + " (" + n.count + ")" : n.label, n.x, n.y + r + 1.5);
  }
  ctx.globalAlpha = 1;
}

// ---------------------------------------------------------------- 머리: 수치·찾기·층
function Head({ s }) {
  const q = K.useKg((x) => x.query);
  const hits = K.useKg((x) => x.hits);
  const layers = K.useKg((x) => x.layers);
  const allStates = K.useKg((x) => x.allStates);
  const expanded = K.useKg((x) => x.expanded);
  const gaps = s.expect.states.filter((x) => GAP.has(x.state)).reduce((n, x) => n + x.count, 0);
  const timer = useRef(null);
  const onInput = (e) => { const v = e.target.value; K.kg.set({ query: v }); clearTimeout(timer.current); timer.current = setTimeout(() => K.search(v), 200); };
  const onKey = (e) => {
    if (e.key === "Enter" && hits.length) { e.preventDefault(); K.focus(hits[0].id, hits[0].group); }
    if (e.key === "Escape" && q) { e.stopPropagation(); K.search(""); }
  };
  const layer = (k) => html`<label class="kg-tg"><input type="checkbox" checked=${layers[k] !== false} onChange=${(e) => K.setLayer(k, e.target.checked)} /> ${LAYER_NAMES[k]} ${s.layers[k] || 0}</label>`;
  return html`<div class="kg-head">
    <div class="kg-search"><${Icon} name="search" size=${16} />
      <input type="text" value=${q} maxlength="100" placeholder="태그·이름·규칙 찾기 (Enter로 첫 결과)" aria-label="지식그래프에서 찾기" onInput=${onInput} onKeyDown=${onKey} />
      ${hits.length ? html`<div class="kg-hits" role="listbox" aria-label="찾은 노드">${hits.map((h) => html`<button type="button" role="option" class="kg-hit" key=${h.id} onClick=${() => K.focus(h.id, h.group)}>
        <b>${h.label}</b><span class="muted small">${TYPE_NAMES[h.type] || h.type} · ${h.drawing}</span></button>`)}</div>` : null}</div>
    <div class="acts-row kg-chips">
      <${Chip}>도면 ${s.sheets}<//><${Chip}>노드 ${s.total.toLocaleString()}<//>
      <${Chip} kind=${gaps ? "warn" : ""} title="기대됨 + 부재 확정: 규칙상 있어야 하는데 확인하지 못했거나 없다고 확정한 것">잠재 후보 공백 ${gaps}<//>
      ${s.expect.recheck ? html`<${Chip} kind="warn" title="규칙 판이나 대상 내용이 바뀌어 이전 판단을 다시 봐야 합니다">재확인 ${s.expect.recheck}<//>` : null}
      <span class="kg-sep"></span>${layer("pid")}${layer("kn")}${layer("exp")}
      <label class="kg-tg" title="확인됨·무관 잠재 후보도 그립니다"><input type="checkbox" checked=${allStates} onChange=${(e) => K.setAllStates(e.target.checked)} /> 판단 끝난 후보도</label>
      <span class="kg-sep"></span>
      <${Btn} sm=${true} kind="ghost" icon="zoom-scan" label="그래프에 맞추기" onClick=${K.fit}>맞추기<//>
      ${s.mode === "overview" && expanded.length ? html`<${Btn} sm=${true} kind="ghost" icon="minus" label="모두 접기" onClick=${K.collapseAll}>모두 접기<//>` : null}</div>
    ${s.mode === "overview" ? html`<div class="muted small">노드가 ${s.total.toLocaleString()}개라 도면별 묶음으로 그렸습니다(한 번에 ${s.cap.toLocaleString()}개까지). 묶음을 누르면 그 도면을 펼치고, 찾기로 바로 갈 수 있습니다.</div>` : null}</div>`;
}

// ---------------------------------------------------------------- 오른쪽 상세
const ACTION_NAMES = { confirm: "후보 확인", reject: "후보 기각", absent: "부재 확정", not_applicable: "무관", undo: "판단 되돌리기" };
function localTime(at) {
  const d = at ? new Date(at) : null;
  return d && !isNaN(d) ? d.toLocaleString("ko-KR", { hour12: false }) : String(at || "-");
}
function judgementRows(j) {
  const rows = [["마지막 판단", ACTION_NAMES[j.action] || j.action || "-"], ["판단한 사람", j.by || "-"], ["시각", localTime(j.at)]];
  if (j.reason) rows.push(["사유", j.reason]);
  if (j.evidence) rows.push(["근거 문서", j.evidence]);
  return rows;
}
const kv = (rows) => html`<dl class="kg-kv">${rows.map(([k, v], i) => html`<dt key=${"k" + i}>${k}</dt><dd key=${"v" + i}>${v}</dd>`)}</dl>`;

function Judge({ d }) {
  const x = d.expectation;
  const busy = K.useKg((s) => s.busy);
  const [open, setOpen] = useState(null);
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  useEffect(() => { setOpen(null); setReason(""); setEvidence(""); }, [d.id, x.state]);
  const run = (a) => {
    if (a.needs.length && open !== a.action) { setOpen(a.action); return; }
    K.judge(d.id, a.action, reason.trim(), evidence.trim());
  };
  const cur = x.actions.find((a) => a.action === open);
  const ready = cur && cur.needs.every(([k]) => (k === "reason" ? reason : evidence).trim());
  return html`<div class="kg-judge">
    <div class="acts-row">${x.actions.map((a) => html`<${Btn} sm=${true} key=${a.action} kind=${a.action === "undo" || a.action === "reject" ? "" : "primary"}
      icon=${a.action === "undo" ? "arrow-back-up" : null} label=${a.label} disabled=${busy || !d.can_judge} onClick=${() => run(a)}>${a.label}<//>`)}</div>
    ${cur ? html`<div class="acts-col kg-form">${cur.needs.map(([k, label]) => html`<label key=${k} class="small">${label}
        <input type="text" maxlength=${k === "reason" ? 500 : 300} value=${k === "reason" ? reason : evidence} aria-label=${label}
          placeholder=${k === "evidence" ? "예: 계통설계기술서 3.2절" : ""} onInput=${(e) => (k === "reason" ? setReason : setEvidence)(e.target.value)} /></label>`)}
      <div class="acts-row"><${Btn} sm=${true} kind="primary" label=${cur.label + " 저장"} disabled=${busy || !ready} onClick=${() => K.judge(d.id, cur.action, reason.trim(), evidence.trim())}>${cur.label} 저장<//>
        <${Btn} sm=${true} kind="ghost" label="취소" onClick=${() => setOpen(null)}>취소<//></div></div>` : null}
    ${d.can_judge ? null : html`<div class="muted small">판단 파일을 읽을 수 없어 지금은 판단을 저장하지 않습니다.</div>`}</div>`;
}

function Detail() {
  const d = K.useKg((s) => s.detail);
  const sel = K.useKg((s) => s.selected);
  if (!sel) return html`<aside class="kg-side"><div class="muted kg-empty"><b>고른 노드 없음</b><p>그래프에서 노드를 누르거나 찾기로 고르면 무엇인지와 근거, 이어진 것이 여기에 나옵니다. 그림의 자리는 근거가 아닙니다.</p></div></aside>`;
  if (!d) return html`<aside class="kg-side"><div class="muted">불러오는 중…</div></aside>`;
  const x = d.expectation;
  return html`<aside class="kg-side" aria-label=${(d.label || d.id) + " 상세"}>
    <div class="kg-dh"><b>${d.label || TYPE_NAMES[d.type] || d.type}</b>
      <${Chip}>${TYPE_NAMES[d.type] || d.type}<//>${d.layer === "kn" && d.ks !== "confirmed" ? html`<${Chip} kind="warn">확인 전<//>` : null}${d.ai ? html`<${Chip} kind="ai" icon="sparkles">AI 초안<//>` : null}${x ? html`<${Chip} kind=${STATE_KIND[x.state]}>${x.state_label}<//>` : null}
      ${x && x.recheck ? html`<${Chip} kind="warn" title="규칙 판이나 대상·후보 내용이 바뀌었습니다">재확인 필요<//>` : null}</div>
    <div class="muted small">${d.drawing}</div>
    ${d.at ? html`<div><${Btn} sm=${true} icon="map-pin" label="도면에서 보기" onClick=${() => K.showOnSheet(d.at)}>도면에서 보기<//></div>` : null}
    ${x ? html`<${Notice} kind="info" icon="info-circle">${x.caution}<//>` : null}
    <h4>무엇인가</h4>${kv(d.what)}
    ${x ? html`<div class="small"><span class="muted">HAZOP에서</span> ${x.hazop}</div>
      <div class="small"><span class="muted">대상</span> <button type="button" class="linkbtn" onClick=${() => K.focus(x.target.id)}>${x.target.label}</button>
        <span class="muted"> · 자동 판정 ${x.auto_state_label}</span></div>
      ${x.found.length ? html`<div class="small"><span class="muted">찾은 후보</span> ${x.found.map((f) => html`<${Chip} key=${f.ref}>${f.label}<//>`)}</div>` : null}
      ${x.note ? html`<div class="small muted">${x.note}</div>` : null}
      ${x.recheck ? html`<${Notice} kind="warn" icon="alert-triangle">이전 판단 '${x.previous_label}'은(는) 규칙 판이나 대상·후보 내용이 바뀌어 다시 봐야 합니다.<//>` : null}` : null}
    <h4>근거</h4>${kv(d.evidence)}
    ${x && x.judgement ? html`<h4>판단 기록</h4>${kv(judgementRows(x.judgement))}` : null}
    ${x ? html`<h4>판단</h4><${Judge} d=${d} />` : null}
    ${d.attrs.length ? html`<details><summary>속성 ${d.attrs.length}</summary>${kv(d.attrs)}</details>` : null}
    ${d.expectations.length ? html`<h4>걸린 잠재 후보 ${d.expectations.length}</h4><div class="list" role="list">${d.expectations.map((e) => html`<button type="button" class="kg-nb" role="listitem" key=${e.id} onClick=${() => K.focus(e.id)}>
      <span>${e.label}</span><${Chip} kind=${STATE_KIND[e.xs]}>${e.state_label}${e.recheck ? " · 재확인" : ""}<//></button>`)}</div>` : null}
    <h4>이어진 것 ${d.neighbors_total}</h4>
    <div class="list" role="list">${d.neighbors.map((nb) => html`<button type="button" class="kg-nb" role="listitem" key=${nb.id + nb.kind} onClick=${() => K.focus(nb.id)}>
      <span>${nb.label}</span><span class="muted small">${nb.kind}${nb.st ? " (" + nb.st + ")" : ""} · ${TYPE_NAMES[nb.type] || nb.type}${nb.drawing !== d.drawing ? " · " + nb.drawing : ""}</span></button>`)}
      ${d.neighbors_total > d.neighbors.length ? html`<div class="muted small">나머지 ${d.neighbors_total - d.neighbors.length}개는 그래프에서 보세요.</div>` : null}</div>
  </aside>`;
}

export function KgPanel({ onClose }) {
  K.wire();
  const s = K.useKg((x) => x.summary);
  const error = K.useKg((x) => x.error);
  const notice = K.useKg((x) => x.notice);
  return html`<section class="panel wide kg" aria-label="지식그래프">
    <div class="panel-h"><h2>지식그래프</h2><span class="muted small">프로젝트 ${s.project_id || ""}</span>
      <span class="acts"><${Btn} kind="ghost" icon="x" label="닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b kg-b">
      ${!s.available ? html`<div class="center-empty"><p>${s.reason || "불러오는 중…"}</p></div>` : html`
        <${Head} s=${s} />
        ${(s.blocks || []).map((b) => html`<${Notice} kind="err" icon="alert-triangle" key=${b.kind}>${b.text}<//>`)}
        ${(s.notes || []).map((t, i) => html`<${Notice} kind="warn" icon="alert-triangle" key=${i}>${t}<//>`)}
        ${error ? html`<${Notice} kind="err" icon="alert-triangle">${error} <${Btn} sm=${true} kind="ghost" label="알림 닫기" onClick=${K.dismissError}>닫기<//><//>` : null}
        ${notice ? html`<${Notice} kind="info" icon="circle-check">${notice}<//>` : null}
        <div class="kg-main"><${GraphCanvas} /><${Detail} /></div>`}
    </div></section>`;
}
