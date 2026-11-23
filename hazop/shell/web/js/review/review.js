// 도면별 AI 검토(규격 HZ-DSN-06 §3.7, 단위 U10). 엔진 aireview 목록의 도면 행 review로 칩 글자와 단추를 정하고, 세 자리(도면 위 칩 줄 맨 앞,
// 도면 목록 줄, 다음에 할 일 줄)가 같은 글자와 같은 확인 창을 쓴다. 시작은 지금 명령 aireview.run을 그대로 부른다(새 실행 길 없음).
// 끝나면 알림 줄에 '후보 n건 · 검토하기'를 띄운다(대기열은 저절로 열지 않는다).
import { html } from "../ui/html.js";
import { useEffect, useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";
import { Icon } from "../ui/icon.js";
import { addNotice, clearNotice } from "../notices.js";

export const rv = createStore({ rows: [], confirm: null });

export function useReview(selector) {
  const [value, setValue] = useState(() => selector(rv.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const n = selector(s); setValue((p) => (Object.is(p, n) ? p : n)); };
    sync(rv.get());
    return rv.subscribe(sync);
  }, []);
  return value;
}

// ---------------------------------------------------------------- 상태 → 글자·단추(§3.7 표)
/** → {text, action: 'start'|'queue'|null, label, tone}. 화면 세 자리가 모두 이것을 쓴다. */
export function reviewView(row) {
  if (!row || !row.review) return null;
  const r = row.review;
  if (r === "not_run") return { text: "AI 검토 전", action: "start", label: "AI 검토 시작", tone: "" };
  if (r === "nothing") return { text: "AI에 물을 곳 없음", action: null, label: null, tone: "quiet" };
  if (r === "waiting") return { text: "AI 검토 기다리는 중" + (row.ahead ? " · 앞에 " + row.ahead + "장" : ""), action: "stop", label: "취소", tone: "info" };
  if (r === "running") {
    const p = row.progress || {};
    return { text: "AI 검토 중" + (p.total ? " · 호출 " + (p.done || 0) + "/" + p.total + "회" : ""), action: "stop", label: "멈추기", tone: "info" };
  }
  if (r === "candidates") return { text: "AI 후보 " + row.proposed + "건 남음", action: "queue", label: "검토하기", tone: "ai" };
  if (r === "partial") return { text: "AI 검토 일부만 함" + (row.left ? " · 남은 곳 " + row.left : ""), action: "start", label: "이어서 검토", tone: "" };
  if (r === "failed") return { text: "AI 검토를 마치지 못했습니다", action: "start", label: "다시 시도", tone: "warn" };
  if (r === "done") return { text: "AI 검토 끝", action: null, label: null, tone: "ok" };
  return null;
}

/** 도면 목록 머리: "AI 검토 전 2장 · 검토 중 1장 · 후보 남음 1장"(0인 것은 뺀다). */
export function summaryText(rows) {
  const n = (f) => rows.filter(f).length;
  const parts = [["AI 검토 전", n((r) => r.review === "not_run" || r.review === "partial" || r.review === "failed")],
    ["검토 중", n((r) => r.review === "running" || r.review === "waiting")], ["후보 남음", n((r) => r.review === "candidates")]];
  return parts.filter((p) => p[1]).map((p) => p[0] + " " + p[1] + "장").join(" · ");
}

export const rowOf = (gid, s = rv.get()) => s.rows.find((x) => x.graph_id === gid) || null;

// ---------------------------------------------------------------- 읽기
let seq = 0;
export async function load() {
  const mine = ++seq;
  try {
    const d = await read("aireview");
    if (mine === seq && d) rv.set({ rows: d.drawings || [] });
  } catch (e) { /* 칩은 덤이다: 앞 값을 둔다 */ }
}
let timer = null;
const soon = (ms = 150) => { clearTimeout(timer); timer = setTimeout(load, ms); };

// ---------------------------------------------------------------- 누르기
let openQueue = null;
let openSheet = null;
let queueOpen = null;
/** main.js가 이어 준다(순환 가져오기를 피하려고). isOpen(gid): 그 도면 대기열이 열려 있는가. */
export function setOpeners(q, s, isOpen) { openQueue = q; openSheet = s; queueOpen = isOpen || null; }

export function press(gid) {
  const v = reviewView(rowOf(gid));
  if (!v || !v.action) return;
  if (v.action === "queue") { if (openQueue && !(queueOpen && queueOpen(gid))) openQueue("ai", gid); return; }      // 이미 그 대기열이 열려 있으면 다시 열지 않는다
  if (v.action === "stop") { stopReview(gid); return; }
  startReview(gid);
}

/** 확인 창을 연다(그 도면을 열고). 예상 호출 수·연결은 엔진의 aireview/estimate에서 읽는다. */
export async function startReview(gid) {
  if (!gid) return;
  if (store.get().sheet !== gid && openSheet) openSheet(gid);
  store.set({ panel: null });
  const cap = (store.get().app && store.get().app.ai_review_cap) || 20;
  rv.set({ confirm: { gid, cap, est: null, busy: false, error: null } });
  await estimate(cap);
}

async function estimate(cap) {
  const c = rv.get().confirm;
  if (!c) return;
  let e = null;
  try { e = await read("aireview/estimate?cap=" + encodeURIComponent(cap) + "&graph_id=" + encodeURIComponent(c.gid)); } catch (err) { e = null; }
  const cur = rv.get().confirm;
  if (!cur || cur.gid !== c.gid) return;
  rv.set({ confirm: Object.assign({}, cur, { cap, est: e, error: e ? null : "예상 호출 수를 읽지 못했습니다." }) });
}

/** 묻는 중이면 지금 호출 뒤 멈추고, 기다리는 중이면 빠진다(aireview.stop: 그 도면만, 다른 작업은 그대로). 창을 닫지 않고 멈출 수 있다. */
export async function stopReview(gid) {
  try {
    const r = await cmd("aireview.stop", { graph_id: gid });
    store.set({ toast: { text: r && r.was === "waiting" ? "AI 검토를 취소했습니다." : "AI 검토를 멈추는 중입니다. 지금 묻는 것 하나를 마치고 멈춥니다." } });
  } catch (e) { store.set({ toast: { text: (e && e.message) || "멈추지 못했습니다.", kind: "err" } }); }
  soon(0);
}

export function setCap(n) { estimate(Math.max(1, Math.min(200, parseInt(n, 10) || 20))); }
export function cancel() { rv.set({ confirm: null }); }

export async function confirmStart() {
  const c = rv.get().confirm;
  if (!c || c.busy || !c.est || !c.est.conn || !c.est.conn.can_start) return null;
  rv.set({ confirm: Object.assign({}, c, { busy: true, error: null }) });
  try {
    const r = await cmd("aireview.run", { graph_ids: [c.gid], cap: c.cap, conn_ver: c.est.conn.conn_ver || "-" });
    rv.set({ confirm: null });
    soon(0);
    return r;
  } catch (e) {
    const cur = rv.get().confirm;
    rv.set({ confirm: cur && Object.assign({}, cur, { busy: false, error: (e && e.message) || "시작하지 못했습니다." }) });
    if (e && e.code === "conn_changed") estimate(c.cap);      // 연결이 바뀌었으면 새 연결을 보이고 다시 누르게 한다
    return null;
  }
}

// ---------------------------------------------------------------- 끝난 뒤 알림
function finished(result) {
  for (const d of (result && result.drawings) || []) {
    const row = rowOf(d.graph_id);
    const num = (row && row.drawing_number) || d.graph_id;
    if (d.candidates > 0) {
      addNotice({ id: "review:" + d.graph_id, key: String(Date.now()), kind: "info", text: num + " AI 검토가 끝났습니다 · 후보 " + d.candidates + "건",
        action: { label: "검토하기", run: () => { clearNotice("review:" + d.graph_id); if (openQueue) openQueue("ai", d.graph_id); } } });
    } else store.set({ toast: { text: num + " AI 검토가 끝났습니다. 새 후보는 없습니다." } });
  }
}

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((t) => { if (t === "aireview" || t === "drawings") soon(); });
  on("job.progress", (d) => { if (/AI 검토/.test(String(d.label || ""))) soon(400); });
  on("job.done", (d) => { if (d.result && Array.isArray(d.result.drawings) && "estimate" in d.result) { finished(d.result); soon(0); } });
  on("job.failed", (d) => { if (/AI 검토/.test(String(d.label || ""))) soon(0); });
  window.addEventListener("keydown", (e) => {
    if (!rv.get().confirm) return;
    const tag = (e.target && e.target.tagName) || "";
    if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); cancel(); }
    else if (e.key === "Enter" && tag !== "INPUT") { e.preventDefault(); e.stopImmediatePropagation(); confirmStart(); }
  }, true);
  load();
}

// ---------------------------------------------------------------- 화면 부품
/** 'AI 검토' 칩 단추(도면 위 칩 줄 맨 앞, 도면 목록 줄). 단추가 없는 상태는 글자만 보인다. */
export function ReviewChip({ gid, compact }) {
  wire();
  const row = useReview((s) => s.rows.find((x) => x.graph_id === gid) || null);
  const v = reviewView(row);
  if (!v) return null;
  const cls = "chip review " + (v.tone === "ai" ? "ai" : v.tone === "warn" ? "warn" : v.tone === "ok" ? "ok" : v.tone === "info" ? "accent" : "");
  const icon = v.tone === "ok" ? "circle-check" : v.tone === "warn" ? "alert-triangle" : v.tone === "info" ? "loader-2" : "sparkles";
  if (!v.action) return html`<span class=${cls} role="status" title=${v.text}><${Icon} name=${icon} size=${14} /> ${v.text}</span>`;
  return html`<button type="button" class=${cls + " act"} aria-label=${(row.drawing_number || "") + " " + v.text + " · " + v.label}
    onClick=${(e) => { e.stopPropagation(); press(gid); }}><${Icon} name=${icon} size=${14} /> ${compact ? "" : v.text + " · "}<b>${v.label}</b></button>`;
}

const minutes = (s) => Math.max(1, Math.round((s || 0) / 60));

/** 확인 창(모달). 구독 한도를 쓰고 도면 조각을 밖으로 보내는 일이라 확인을 받는다. */
export function ReviewConfirm() {
  wire();
  const c = useReview((s) => s.confirm);
  const rows = useReview((s) => s.rows);
  useEffect(() => { if (c) { const b = document.querySelector(".rv-modal .btn.primary"); if (b) b.focus(); } }, [c && c.gid, c && !!c.est]);
  if (!c) return null;
  const row = rows.find((x) => x.graph_id === c.gid) || {};
  const e = c.est;
  const page = e && (e.pages || []).find((p) => p.graph_id === c.gid);
  const conn = (e && e.conn) || {};
  const ahead = rows.filter((x) => x.graph_id !== c.gid && (x.review === "running" || x.review === "waiting")).length;
  const capped = page && page.needed > page.calls;
  const img = page ? page.image : e && e.images && e.images.on;
  return html`<div class="rv-back" onClick=${cancel}><div class="rv-modal" role="dialog" aria-modal="true" aria-label=${(row.drawing_number || "") + " AI 검토"} onClick=${(ev) => ev.stopPropagation()}>
    <h3>${row.drawing_number || ""} AI 검토</h3>
    ${!e ? html`<div class="muted">${c.error || "예상 호출 수를 읽고 있습니다."}</div>` : html`<dl>
      <dt>물을 곳</dt><dd>종류를 정하지 못했거나 다시 볼 곳 ${page ? page.items : 0}곳</dd>
      <dt>예상</dt><dd>AI 호출 약 ${page ? page.calls : 0}회 · 약 ${minutes((page ? page.calls : 0) * 30)}분${capped ? html`<div class="muted small">상한 ${c.cap}회에 걸려 일부만 묻습니다</div>` : null}</dd>
      <dt>도면당 상한</dt><dd><input type="number" min="1" max="200" value=${c.cap} aria-label="도면당 호출 상한" onChange=${(ev) => setCap(ev.target.value)} /> 회 <span class="muted small">(한 번 실행은 ${e.run_cap || 300}회까지)</span></dd>
      <dt>연결</dt><dd>${[conn.method_name, conn.model_name, conn.cost_text].filter(Boolean).join(" · ") || "연결 안 됨"}</dd>
      <dt>보내는 것</dt><dd>${img ? "종류를 정하지 못한 기호 둘레의 도면 조각 그림과 범례판을 AI에 보냅니다. 구독 연결로만 보냅니다." : "도면 조각 그림은 보내지 않고 글자 정보만 보냅니다."}</dd></dl>`}
    ${e && !conn.can_start ? html`<div class="qmsg err" role="alert">${conn.guide || "AI 연결이 준비되지 않았습니다."} <button type="button" class="btn sm" onClick=${() => { cancel(); store.set({ panel: "settings" }); }}>설정 열기</button></div>` : null}
    ${ahead ? html`<div class="muted small">앞선 도면 ${ahead}장이 끝난 뒤 시작합니다</div>` : null}
    ${c.error && e ? html`<div class="qmsg err" role="alert">${c.error}</div>` : null}
    <div class="acts"><button type="button" class="btn primary" disabled=${c.busy || !e || !conn.can_start || !(page && page.calls)} onClick=${confirmStart}>검토 시작 Enter</button>
      <button type="button" class="btn" onClick=${cancel}>취소 Esc</button></div></div></div>`;
}
