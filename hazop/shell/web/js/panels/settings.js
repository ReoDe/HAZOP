// 설정 패널: AI 연결(지금 쓰는 경로 · Claude 구독 화면 · API 키 화면을 따로), 분석 모델·채팅 모델, 검토자 이름, 프로젝트, 시작 화면, 정보.
// AI 연결은 hazop/shell/api_settings.py(aisettings 읽기, aiconn.* 명령). 화면 설계 docs/design/ai-connection-screens.md §3을 웹으로 옮긴 것이다:
// 화면을 보는 것과 방식을 바꾸는 일을 나눈다('이 방식으로 사용'), API 키로 바꿀 때만 요금 확인, 구독은 처음 한 번 이용 조건.
// **API 키는 웹에서 받지 않는다**: '키 추가'는 창이 Python 쪽 입력 상자를 연다. 웹은 키 이름과 끝 네 자리만 본다.
import { html } from "../ui/html.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { store, useStore } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";
import { Btn, Chip, Notice, Switch } from "../ui/parts.js";

const TONE = (t) => (t === "ok" || t === "warn" || t === "err" ? t : "");
const usd = (v) => "$" + Number(v || 0).toFixed(2);

function useAiSettings() {
  const [v, setV] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => read("aisettings").then((d) => { if (alive) setV(d); }).catch(() => { if (alive) setV({ available: false, reason: "AI 연결 설정을 읽지 못했습니다." }); });
    load();
    const off1 = onChanged((t) => { if (t === "aisettings") load(); });
    const off2 = on("conn.changed", load);
    return () => { alive = false; off1(); if (typeof off2 === "function") off2(); };
  }, []);
  return [v, setV];
}

function ModelSelect({ id, label, value, models, disabled, onPick }) {
  return html`<div class="field set-model"><label for=${id}>${label}</label>
    <select id=${id} value=${value} disabled=${disabled} onChange=${(e) => onPick(e.target.value)}>
      ${models.map((m) => html`<option key=${m.id} value=${m.id}>${m.label}</option>`)}</select></div>`;
}

function Current({ c }) {
  return html`<div class=${"set-current " + (TONE(c.tone) || "plain")} role="status" aria-label=${"지금 AI 연결: " + c.chip}>
    <b>지금 분석에 쓰는 연결</b> <span>${c.method_name}${c.model_name ? " · " + c.model_name : ""}</span> <${Chip} kind=${TONE(c.tone)}>${c.label}<//>
    ${c.can_start ? null : html`<div class="small">${c.guide}</div>`}</div>`;
}

function SubscriptionView({ v, act, busy }) {
  const s = v.subscription;
  const inUse = v.current.via === "subscription";
  return html`<div class="set-view" aria-label="Claude 구독">
    <div class="muted small">${s.cost}</div>
    <div class="kv"><div class="k"><b>상태</b><span>${s.title}${s.plan ? " · " + s.plan : ""}${s.checked_at ? " · " + s.checked_at.slice(11, 16) + " 확인" : ""}</span></div>
      <${Chip} kind=${TONE(s.tone)}>${s.label}<//></div>
    ${s.can_start ? null : html`<${Notice} kind="warn" icon="alert-triangle">${s.guide}<//>`}
    <${ModelSelect} id="sub-model" label="분석 모델" value=${s.model} models=${v.models.map((m) => ({ id: m.id, label: m.label }))} disabled=${busy || v.running}
      onPick=${(m) => act("aiconn.set_model", { method: "subscription", model: m }, "구독 분석 모델을 바꿨습니다.")} />
    <p class="muted small">구독 한도는 claude.ai와 Claude Code에서 쓰는 양과 함께 셉니다. claude.ai 개인정보 설정에서 '모델 개선'이 켜져 있으면 보낸 도면 정보가 학습에 쓰일 수 있습니다.</p>
    <div class="acts-row">
      <${Btn} sm=${true} icon="refresh" label="구독 연결 확인" disabled=${busy} onClick=${() => act("aiconn.check", { method: "subscription" }, "구독 연결을 확인하는 중입니다.")}>연결 확인<//>
      <${Btn} sm=${true} kind="primary" label=${inUse ? "사용 중" : "구독으로 사용"} disabled=${busy || inUse || v.running} onClick=${() => act("aiconn.use", { method: "subscription" })}>${inUse ? "사용 중" : "이 방식으로 사용"}<//></div></div>`;
}

function ApiView({ v, act, busy }) {
  const a = v.api;
  const inUse = v.current.via === "api";
  const [asking, setAsking] = useState(null);       // 지울 키 ID
  const [renaming, setRenaming] = useState(null);   // [키 ID, 새 이름]
  return html`<div class="set-view" aria-label="API 키">
    <div class="muted small">${a.cost}</div>
    <div class="kv"><div class="k"><b>상태</b><span>${a.title}</span></div><${Chip} kind=${TONE(a.tone)}>${a.label}<//></div>
    ${a.can_start ? null : html`<${Notice} kind="warn" icon="alert-triangle">${a.guide}<//>`}
    ${a.load_error ? html`<${Notice} kind="err" icon="alert-triangle">저장된 키 일부를 읽지 못했습니다. 키를 다시 추가하세요.<//>` : null}
    <div class="list" role="list" aria-label="API 키 목록">${a.keys.length ? a.keys.map((k) => html`<div class=${"row" + (k.active ? " on" : "")} role="listitem" key=${k.id}>
      <div class="main"><b>${k.name} <span class="muted">${k.hint}</span></b>
        <span>${k.persisted ? "이 PC에 저장(암호화)" : "이번 실행에만"}${k.last_test ? " · 마지막 시험 " + (k.last_test.ok ? "성공" : "실패") : " · 시험 안 함"}</span></div>
      ${renaming && renaming[0] === k.id ? html`<input type="text" class="set-rename" maxlength="40" aria-label="새 키 이름" value=${renaming[1]} onInput=${(e) => setRenaming([k.id, e.target.value])} />
          <${Btn} sm=${true} kind="primary" label="이름 저장" disabled=${!renaming[1].trim()} onClick=${() => { act("aiconn.rename_key", { key_id: k.id, name: renaming[1].trim() }, "이름을 바꿨습니다."); setRenaming(null); }}>저장<//>
          <${Btn} sm=${true} kind="ghost" label="이름 바꾸기 취소" onClick=${() => setRenaming(null)}>취소<//>`
        : asking === k.id ? html`<span class="set-ask">'${k.name}'(${k.hint}) 키를 지울까요? 이 PC에 저장한 암호화 사본도 지워지며 되돌릴 수 없습니다.</span>
          <${Btn} sm=${true} kind="primary" label=${k.name + " 지우기 확인"} onClick=${() => { act("aiconn.remove_key", { key_id: k.id, confirmed: true }, "키를 지웠습니다."); setAsking(null); }}>지우기<//>
          <${Btn} sm=${true} kind="ghost" label="지우기 취소" onClick=${() => setAsking(null)}>취소<//>`
        : html`<span class="acts">
          ${k.active ? html`<${Chip} kind="ok">사용 키<//>` : html`<${Btn} sm=${true} label=${k.name + " 사용"} disabled=${busy || v.running} onClick=${() => act("aiconn.select_key", { key_id: k.id }, "사용할 키를 바꿨습니다.")}>사용<//>`}
          <${Btn} sm=${true} kind="ghost" label=${k.name + " 이름 바꾸기"} onClick=${() => setRenaming([k.id, k.name])}>이름<//>
          <${Btn} sm=${true} kind="ghost" label=${k.name + " 지우기"} disabled=${v.running} onClick=${() => setAsking(k.id)}>지우기<//></span>`}</div>`)
      : html`<div class="muted">키가 없습니다. 'API 키 추가'를 누르면 키를 넣는 창이 열립니다.</div>`}</div>
    <${ModelSelect} id="api-model" label="분석 모델" value=${a.model} models=${v.models.map((m) => ({ id: m.id, label: m.label + " · 구간당 약 " + usd(m.section_usd) }))}
      disabled=${busy || v.running} onPick=${(m) => act("aiconn.set_model", { method: "api", model: m }, "API 분석 모델을 바꿨습니다. 새 모델로 연결 시험을 해 보세요.")} />
    <div class="acts-row">
      <${Btn} sm=${true} icon="plus" label="API 키 추가" disabled=${busy} onClick=${() => act("aiconn.add_key", {}, null)}>API 키 추가<//>
      <${Btn} sm=${true} icon="refresh" label="API 연결 시험" disabled=${busy || !a.keys.length} onClick=${() => act("aiconn.check", { method: "api" }, "연결 시험 중입니다(요금 없음).")}>연결 시험<//>
      <${Btn} sm=${true} kind="primary" label=${inUse ? "사용 중" : "API 키로 사용"} disabled=${busy || inUse || v.running} onClick=${() => act("aiconn.use", { method: "api" })}>${inUse ? "사용 중" : "이 방식으로 사용"}<//></div></div>`;
}

function AiConnection() {
  const [v, setV] = useAiSettings();
  const [tab, setTab] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);           // {text, kind}
  const [confirm, setConfirm] = useState(null);   // API 요금 확인 글
  const [terms, setTerms] = useState(false);      // 구독 이용 조건 보이기
  const [checked, setChecked] = useState(false);
  if (!v) return html`<div class="card"><h3>AI 연결</h3><div class="muted">읽는 중…</div></div>`;
  if (!v.available) return html`<div class="card"><h3>AI 연결</h3><${Current} c=${v.current} /></div>`;
  const view = tab || v.current.via || "subscription";
  async function act(name, args, done) {
    setBusy(true); setMsg(null);
    try {
      const r = await cmd(name, args);
      if (r && r.need_confirm) setConfirm(r.text);
      else if (r && r.need_terms) setTerms(true);
      else {
        if (r && r.view) setV(r.view);
        const text = done !== undefined ? done : (r && r.changed ? "연결 방식을 바꿨습니다. 연결을 확인하는 중입니다." : null);
        if (name === "aiconn.add_key") setMsg(r && r.added ? { text: "키 '" + r.key.name + "'(" + r.key.hint + ")를 추가했습니다. 연결 시험 중입니다." } : null);
        else if (text) setMsg({ text });
      }
    } catch (e) { setMsg({ text: e.message || "처리하지 못했습니다.", kind: "err" }); }
    setBusy(false);
  }
  const tabBtn = (m, label) => html`<button type="button" role="tab" class=${"set-tab" + (view === m ? " on" : "")} aria-selected=${view === m ? "true" : "false"}
    onClick=${() => setTab(m)}>${label}${v.current.via === m ? html` <span class="set-inuse">사용 중</span>` : null}</button>`;
  return html`<div class="card ai-settings"><h3>AI 연결</h3>
    <${Current} c=${v.current} />
    ${v.running ? html`<${Notice} kind="warn" icon="alert-triangle">AI 분석이 돌고 있어 연결 방식과 모델을 바꿀 수 없습니다. 실행이 끝나거나 멈춘 뒤 바꾸세요.<//>` : null}
    <div class="set-tabs" role="tablist" aria-label="연결 방식">${v.subscription ? tabBtn("subscription", "Claude 구독") : null}${v.api ? tabBtn("api", "API 키") : null}</div>
    ${confirm ? html`<div class="set-confirm" role="alertdialog" aria-label="API 키로 바꾸기"><span>${confirm}</span>
        <${Btn} sm=${true} kind="primary" label="API 키로 바꾸기" onClick=${() => { setConfirm(null); act("aiconn.use", { method: "api", confirmed: true }); }}>API 키로 바꾸기<//>
        <${Btn} sm=${true} kind="ghost" label="취소" onClick=${() => setConfirm(null)}>취소<//></div>` : null}
    ${terms ? html`<div class="set-confirm" role="alertdialog" aria-label="Claude 구독으로 분석하기 전에"><b>Claude 구독으로 분석하기 전에</b>
        <ul class="tight"><li>이 PC에 설치하고 본인 계정으로 로그인한 Claude Code를 거쳐 본인 구독 사용량으로 분석합니다. 다른 사람의 계정이나 공용 계정으로 쓰지 마세요.</li>
          <li>Claude 구독은 소비자 약관을 따릅니다. '모델 개선'이 켜져 있으면 보낸 도면 정보가 학습에 쓰일 수 있습니다. 보안 등급이 있는 자료 전에 확인하세요.</li>
          <li>앱은 로그인 정보를 읽거나 저장하지 않습니다.</li></ul>
        <label class="small"><input type="checkbox" checked=${checked} onChange=${(e) => setChecked(e.target.checked)} /> 위 내용을 확인했습니다</label>
        <span class="acts-row"><${Btn} sm=${true} kind="primary" label="확인하고 구독으로 사용" disabled=${!checked} onClick=${async () => { setTerms(false); await cmd("aiconn.ack_terms").catch(() => {}); act("aiconn.use", { method: "subscription" }); }}>확인하고 계속<//>
          <${Btn} sm=${true} kind="ghost" label="취소" onClick=${() => setTerms(false)}>취소<//></span></div>` : null}
    ${view === "api" && v.api ? html`<${ApiView} v=${v} act=${act} busy=${busy} />` : html`<${SubscriptionView} v=${v} act=${act} busy=${busy} />`}
    ${msg ? html`<div class=${"set-msg" + (msg.kind === "err" ? " err" : "")} role="status">${msg.text}</div>` : null}
    <${ModelSelect} id="chat-model" label="채팅 모델(구독 연결로 돕니다)" value=${v.chat.model} models=${v.chat.models} disabled=${busy}
      onPick=${(m) => cmd("chat.set_model", { model: m }).then(() => setV(Object.assign({}, v, { chat: Object.assign({}, v.chat, { model: m }) }))).catch((e) => setMsg({ text: e.message, kind: "err" }))} />
  </div>`;
}

export function SettingsPanel({ onClose }) {
  const app = useStore((s) => s.app);
  const data = useStore((s) => s.drawings);
  const [name, setName] = useState(app.reviewer || "");
  const fail = (e) => store.set({ toast: { text: e.message, kind: "err" } });
  const saveName = () => cmd("settings.set_reviewer", { name }).then(() => store.set({ toast: { text: "검토자 이름을 저장했습니다." } })).catch(fail);
  return html`<section class="panel settings" aria-label="설정">
    <div class="panel-h"><h2>설정</h2><span class="acts"><${Btn} kind="ghost" icon="x" label="패널 닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      <div class="card"><h3>검토자</h3>
        <div class="field"><label for="reviewer">검토자 이름</label>
          <input id="reviewer" type="text" maxlength="60" value=${name} style="height:34px" onInput=${(e) => setName(e.target.value)} /></div>
        <div class="acts-row" style="margin-top:8px"><${Btn} sm=${true} kind="primary" disabled=${!name.trim()} onClick=${saveName}>저장<//></div></div>
      <${AiConnection} />
      <div class="card"><h3>프로젝트</h3><div class="kv"><div class="k"><b>${data.project_id || "프로젝트 없음"}</b><span>도면 ${data.drawings.length}장 · 등록 자료 ${data.documents.length}건</span></div></div></div>
      <div class="card"><h3>시작 화면</h3>
        <div class="kv"><div class="k"><b>시작할 때 새 화면 쓰기</b><span>새 화면이 기본입니다. 끄면 다음 실행부터 이전 화면으로 열립니다. 아래 '이전 화면 열기'는 언제나 쓸 수 있습니다.</span></div>
          <${Switch} on=${app.ui_shell} label="시작할 때 새 화면 쓰기" onChange=${(v) => cmd("settings.set_default_shell", { enabled: v }).then(() => store.set((s) => ({ app: Object.assign({}, s.app, { ui_shell: v }) }))).catch(fail)} /></div></div>
      <div class="card"><h3>정보</h3><p class="muted" style="margin:0">HAZOP 분석 도구 ${app.version}</p>
        <div class="acts-row" style="margin-top:8px"><${Btn} sm=${true} onClick=${() => cmd("app.open_classic").catch(fail)}>이전 화면 열기<//></div></div>
    </div></section>`;
}
