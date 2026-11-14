// 도면 연결(오각형) 짝 지정·끊기(완료 목록 3 B1, 규격 §2.3 '도면 연결 짝'). 고치기를 켠 채 오각형을 누르면 그 고치기 카드 안에 이 칸이 붙는다.
// 늘 떠 있는 단추는 늘리지 않는다(사용자 방침 2026-11-14). 저장은 엔진(links.pair·unlink·clear, hazop/shell/api_links.py)만 하고,
// 카드가 본 판(ver)과 연결점 지문(base)을 함께 보낸다. 엔진이 확인을 물으면(풀리는 짝·확정 구간) 그 글을 그대로 confirm으로 보낸다.
// 도면에서 온 글(라벨·배관 번호·사유)은 htm이 이스케이프하는 텍스트로만 넣는다.
import { html } from "../ui/html.js";
import { useEffect, useLayoutEffect, useRef, useState } from "../../vendor/hooks.module.js";
import { createStore } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Btn, Notice } from "../ui/parts.js";

export const links = createStore({ gid: null, id: null, view: null, q: "", picking: false, picked: null, reason: "", busy: false, error: null, ask: null, notes: [] });

function useLinks(selector) {
  const [value, setValue] = useState(() => selector(links.get()));
  const latest = useRef(selector);
  latest.current = selector;
  useLayoutEffect(() => {
    const sync = (s) => { const next = latest.current(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(links.get());
    return links.subscribe(sync);
  }, []);
  return value;
}

let seq = 0;
/** 연결점 카드 자료를 읽는다. q: 맞은편 후보 찾기 글. */
export async function loadLink(gid, id, q = links.get().q) {
  const mine = ++seq;
  const path = "links/" + encodeURIComponent(gid) + "/" + encodeURIComponent(id) + (q ? "?q=" + encodeURIComponent(q) : "");
  let v = null;
  try { v = await read(path); } catch (e) { v = null; }
  if (mine !== seq) return null;
  links.set({ gid, id, view: v, error: v ? null : "이 연결점의 짝 정보를 읽지 못했습니다." });
  return v;
}

let wired = false;
function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => {                       // 다른 곳(맞은편 도면·채팅)에서 바뀌어도 열린 카드를 새로 읽는다
    const s = links.get();
    if ((topic === "links" || topic === "nodes") && s.gid && s.id) loadLink(s.gid, s.id);
  });
}

async function send(name, args) {
  const s = links.get(), v = s.view;
  if (!v || !v.ok) return null;
  links.set({ busy: true, error: null });
  try {
    const r = await cmd(name, Object.assign({ graph_id: s.gid, local_id: s.id, ver: v.ver, base: v.point.base }, args));
    links.set({ busy: false, ask: null, picking: false, picked: null, reason: "", notes: [...(r.notes || []), ...(r.recheck || [])] });
    await loadLink(s.gid, s.id);
    return r;
  } catch (e) {
    links.set({ busy: false });
    if (e.code === "needs_confirm") links.set({ ask: { message: e.message, run: () => send(name, Object.assign({}, args, { confirm: e.message })) } });
    else if (e.code === "stale") { await loadLink(s.gid, s.id); links.set({ error: e.message }); }
    else links.set({ error: e.message || "저장하지 못했습니다." });
    return null;
  }
}

export function pairWith(c, reason = links.get().reason) {
  return send("links.pair", { peer_graph_id: c.graph_id, peer_local_id: c.local_id, reason: (reason || "").trim() });
}
export function unlinkPoint(reason = links.get().reason) { return send("links.unlink", { reason: (reason || "").trim() }); }
export function clearOp(opId) { return send("links.clear", { op_id: opId }); }

let qTimer = null;
function search(q) {
  links.set({ q });
  clearTimeout(qTimer);
  const s = links.get();
  qTimer = setTimeout(() => loadLink(s.gid, s.id, q), 200);
}

function when(at) { return (at || "").replace("T", " ").replace(/:\d\dZ$/, "").replace("Z", ""); }

function stateLine(p) {
  if (p.status === "linked" && p.peer) {
    return html`<span>짝: <b>${p.peer.drawing_number}</b> ${p.peer.label}${p.origin === "manual" ? " (사람이 지정)" : " (자동)"}</span>`;
  }
  return html`<span class="warn">미연결 · ${p.reason_text || p.reason || "짝 없음"}${p.origin === "manual" ? " (사람이 끊음)" : ""}</span>`;
}

/** 고치기 카드 안의 '도면 연결' 칸. item: 고치기 카드의 항목(kind continuation). */
export function LinkSection({ gid, item }) {
  wire();
  const s = useLinks((x) => x);
  useEffect(() => {
    links.set({ q: "", picking: false, picked: null, reason: "", ask: null, error: null, notes: [], view: null });
    if (gid && item) loadLink(gid, item.local_id, "");
  }, [gid, item && item.local_id]);
  const v = s.view;
  if (!v || !v.ok || s.id !== item.local_id) {
    return html`<div class="field ec-link"><label>도면 연결</label>${s.error ? html`<${Notice} kind="err" icon="alert-triangle">${s.error}<//>` : html`<span class="muted small">읽는 중…</span>`}</div>`;
  }
  const p = v.point;
  return html`<div class="field ec-link" role="group" aria-label="도면 연결 짝">
    <label>도면 연결 ${p.line_no ? html`<span class="muted small">${p.line_no}</span>` : null}</label>
    <div class="acts-row">${stateLine(p)}</div>
    ${p.op ? html`<div class="muted small">${p.op.by} · ${when(p.op.at)}${p.op.reason ? " · " + p.op.reason : ""}</div>` : null}
    ${p.check === "no_fingerprint" ? html`<${Notice} kind="warn" icon="alert-triangle">확인 필요: 연결점 지문 없이 남은 예전 지정이라 번호로만 붙였습니다. 맞으면 다시 지정하세요(다시 추출로 번호가 밀리면 다른 연결점에 붙을 수 있습니다).<//>` : null}
    ${(v.relocated || []).length ? html`<div class="muted small">다시 추출로 번호가 밀린 연결점 ${v.relocated.length}개를 지문으로 찾아 옮겨 붙였습니다(${v.relocated.map((m) => m.from + " → " + m.to).join(", ")}). 다음 저장 때 기록에 남습니다.</div>` : null}
    ${v.stale.length ? html`<${Notice} kind="warn" icon="alert-triangle">이 도면의 오래된 지정 ${v.stale.length}: 원본이 바뀌어 적용하지 못했습니다.
      ${v.stale.map((o) => html`<div class="acts-row" key=${o.op_id}><span class="small">${o.op === "link" ? "짝" : "끊기"} · ${(o.ends || []).map((e) => e.drawing_number + " " + e.source_object_id).join(" ↔ ")} · ${o.reason}</span>
        <${Btn} sm=${true} label=${"오래된 지정 빼기 " + o.op_id} disabled=${s.busy} onClick=${() => clearOp(o.op_id)}>빼기<//></div>`)}<//>` : null}
    <div class="acts-row">
      <${Btn} sm=${true} icon="link" label="짝 지정" disabled=${s.busy} onClick=${() => links.set({ picking: !s.picking, picked: null })}>짝 지정<//>
      ${p.status === "linked" ? html`<${Btn} sm=${true} icon="link-off" label="짝 끊기" disabled=${s.busy} onClick=${() => unlinkPoint()}>끊기<//>` : null}
      ${p.op ? html`<${Btn} sm=${true} kind="ghost" label="지정 빼기(자동 판정으로)" title="사람이 한 지정을 빼고 자동 판정으로 돌아갑니다" disabled=${s.busy} onClick=${() => clearOp(p.op.op_id)}>지정 빼기<//>` : null}
    </div>
    ${s.picking ? html`<div class="ec-pick">
      <input class="textbox" aria-label="맞은편 찾기" placeholder="도면 번호·배관 번호로 찾기" value=${s.q} onInput=${(e) => search(e.target.value)} />
      <ul class="ec-cands" role="listbox" aria-label="맞은편 후보">${v.candidates.map((c) => {
        const on = s.picked && s.picked.graph_id === c.graph_id && s.picked.local_id === c.local_id;
        return html`<li key=${c.graph_id + "/" + c.local_id} role="option" aria-selected=${on ? "true" : "false"} class=${on ? "on" : ""} tabindex="0"
          onClick=${() => links.set({ picked: c })} onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); links.set({ picked: c }); } }}>
          <b>${c.drawing_number}</b> ${c.line_no || "-"} · ${c.label}${c.linked ? html` <span class="muted small">· 지금 ${c.peer_drawing}와 짝</span>` : null}
          ${(c.warn || []).length ? html` <span class="warn small" title=${c.warn.join(", ")}>⚠ ${c.warn.length}</span>` : null}</li>`;
      })}${v.more ? html`<li class="muted small">그 밖에 ${v.more}개: 찾기로 좁히세요</li>` : null}
      ${!v.candidates.length ? html`<li class="muted small">맞는 후보가 없습니다.</li>` : null}</ul>
      <input class="textbox" aria-label="지정 사유" maxlength="300" placeholder="사유(선택): 예) 도면 개정으로 배관 번호가 바뀜" value=${s.reason} onInput=${(e) => links.set({ reason: e.target.value })} />
      ${s.picked && (s.picked.warn || []).length ? html`<${Notice} kind="warn" icon="alert-triangle">고른 후보: ${s.picked.warn.join(", ")}. 맞는 짝인지 확인하고 사유를 남기세요.<//>` : null}
      <div class="acts-row"><${Btn} sm=${true} kind="primary" label="이 짝으로 지정" disabled=${s.busy || !s.picked} onClick=${() => pairWith(s.picked)}>이 짝으로 지정<//></div>
    </div>` : null}
    ${s.ask ? html`<${Notice} kind="warn" icon="alert-triangle">${s.ask.message}<div class="acts-row"><${Btn} sm=${true} kind="danger" label="그래도 하기" onClick=${s.ask.run}>그래도 하기<//>
      <${Btn} sm=${true} label="취소" onClick=${() => links.set({ ask: null })}>취소<//></div><//>` : null}
    ${s.error ? html`<${Notice} kind="err" icon="alert-triangle">${s.error}<//>` : null}
    ${s.notes.length ? html`<div class=${"small" + (s.notes.some((t) => t.includes("재확인")) ? " warn" : "")}>${s.notes.map((t) => html`<div>${t}</div>`)}</div>` : null}
  </div>`;
}
