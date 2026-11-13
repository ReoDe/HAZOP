// 설정 패널: AI 연결, 검토자 이름, 프로젝트, 시작 화면, 정보.
// AI 연결은 hazop/shell/api_settings.py(aisettings 읽기, aiconn.* 명령). 사용자 방침(2026-11-14): 이전 대화상자 모양을 옮기지 않고 단순하게 —
// 맨 위 한 줄에 '지금 무엇으로 연결돼 있는지', 그 아래 Claude 구독 / API 키 두 카드, 카드마다 모델 드롭다운 하나와 '이 방식으로 사용'.
// 안전장치만 이전 화면에서 가져온다: API 키로 바꿀 때 요금 확인, 구독은 처음 한 번 이용 조건, 키 지우기 확인, 연결 시험.
// **API 키는 웹에서 받지 않는다**: '키 추가'는 창이 Python 쪽 입력 상자를 연다. 웹은 키 이름과 끝 네 자리만 본다.
import { html } from "../ui/html.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { store, useStore } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";
import { Btn, Chip, Switch } from "../ui/parts.js";

const TONE = (t) => (t === "ok" || t === "warn" || t === "err" ? t : "");

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

/** 확인 줄(요금 확인·이용 조건·키 지우기): 카드 안에 한 줄로 끼운다. */
function Ask({ text, yes, onYes, onNo, children }) {
  return html`<div class="set-ask" role="alertdialog" aria-label=${yes}><span>${text}</span>${children}
    <span class="set-ask-b"><${Btn} sm=${true} kind="primary" label=${yes} disabled=${!onYes} onClick=${onYes}>${yes}<//><${Btn} sm=${true} kind="ghost" label="취소" onClick=${onNo}>취소<//></span></div>`;
}

function MethodCard({ name, st, inUse, model, models, busy, running, onModel, onUse, onCheck, checkLabel, children }) {
  return html`<div class=${"set-card" + (inUse ? " on" : "")} aria-label=${name}>
    <div class="set-card-h"><b>${name}</b>${inUse ? html`<span class="set-inuse">사용 중</span>` : null}<${Chip} kind=${TONE(st.tone)}>${st.label}<//></div>
    ${st.can_start ? null : html`<div class="small set-why">${st.title}</div>`}
    ${children}
    <select class="set-model" aria-label=${name + " 분석 모델"} value=${model} disabled=${busy || running} onChange=${(e) => onModel(e.target.value)}>
      ${models.map((m) => html`<option key=${m.id} value=${m.id}>${m.label}</option>`)}</select>
    <div class="set-card-b">
      <${Btn} sm=${true} kind="ghost" icon="refresh" label=${checkLabel} disabled=${busy} onClick=${onCheck}>${checkLabel}<//>
      ${inUse ? null : html`<${Btn} sm=${true} kind="primary" label=${name + "로 사용"} disabled=${busy || running} onClick=${onUse}>이 방식으로 사용<//>`}</div></div>`;
}

function AiConnection() {
  const [v, setV] = useAiSettings();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);          // {text, err}
  const [ask, setAsk] = useState(null);          // {kind: "api"|"terms"|"remove", text, key}
  const [checked, setChecked] = useState(false);
  if (!v) return html`<div class="card"><h3>AI 연결</h3><div class="muted">읽는 중…</div></div>`;
  const c = v.current;
  const now = html`<div class=${"set-now " + (TONE(c.tone) || "plain")} role="status" aria-label=${"지금 AI 연결: " + (c.chip || c.label)}>
    <span class="dot"></span><b>${c.method_name}${c.model_name ? " · " + c.model_name : ""}</b><span>${c.label}</span></div>`;
  if (!v.available) return html`<div class="card"><h3>AI 연결</h3>${now}<div class="small muted">${c.guide}</div></div>`;
  async function act(name, args, done) {
    setBusy(true); setMsg(null);
    try {
      const r = await cmd(name, args);
      if (r && r.need_confirm) setAsk({ kind: "api", text: r.text });
      else if (r && r.need_terms) { setChecked(false); setAsk({ kind: "terms" }); }
      else {
        if (r && r.view) setV(r.view);
        if (name === "aiconn.add_key") setMsg(r && r.added ? { text: "키 " + r.key.hint + "를 추가했습니다. 연결을 시험하는 중입니다." } : null);
        else if (done) setMsg({ text: done });
      }
    } catch (e) { setMsg({ text: e.message || "처리하지 못했습니다.", err: true }); }
    setBusy(false);
  }
  const models = v.models.map((m) => ({ id: m.id, label: m.label }));
  const s = v.subscription, a = v.api;
  const key = a && a.keys.find((k) => k.active);
  return html`<div class="card ai-settings"><h3>AI 연결</h3>
    ${now}
    ${v.running ? html`<div class="small set-why">AI 분석이 도는 동안에는 연결과 모델을 바꿀 수 없습니다.</div>` : null}
    ${ask && ask.kind === "api" ? html`<${Ask} text=${ask.text} yes="API 키로 바꾸기" onYes=${() => { setAsk(null); act("aiconn.use", { method: "api", confirmed: true }, "API 키로 바꿨습니다."); }} onNo=${() => setAsk(null)} />` : null}
    ${ask && ask.kind === "terms" ? html`<${Ask} text="Claude 구독은 이 PC에 로그인한 본인 계정의 사용량으로 분석합니다. claude.ai 설정에서 '모델 개선'이 켜져 있으면 보낸 도면 정보가 학습에 쓰일 수 있습니다."
        yes="확인하고 구독으로 사용" onYes=${checked ? async () => { setAsk(null); await cmd("aiconn.ack_terms").catch(() => {}); act("aiconn.use", { method: "subscription" }, "Claude 구독으로 바꿨습니다."); } : null} onNo=${() => setAsk(null)}>
        <label class="small"><input type="checkbox" checked=${checked} onChange=${(e) => setChecked(e.target.checked)} /> 확인했습니다</label><//>` : null}
    <div class="set-cards">
      ${s ? html`<${MethodCard} name="Claude 구독" st=${s} inUse=${c.via === "subscription"} model=${s.model} models=${models} busy=${busy} running=${v.running}
          checkLabel="연결 확인" onCheck=${() => act("aiconn.check", { method: "subscription" }, "구독 연결을 확인하는 중입니다.")}
          onUse=${() => act("aiconn.use", { method: "subscription" }, "Claude 구독으로 바꿨습니다.")}
          onModel=${(m) => act("aiconn.set_model", { method: "subscription", model: m }, "구독 모델을 바꿨습니다.")}>
          <div class="small muted">건별 요금 없음 · 구독 한도에서 빠짐${s.plan ? " · " + s.plan : ""}</div><//>` : null}
      ${a ? html`<${MethodCard} name="API 키" st=${a} inUse=${c.via === "api"} model=${a.model} models=${models} busy=${busy} running=${v.running}
          checkLabel="연결 시험" onCheck=${() => (key ? act("aiconn.check", { method: "api" }, "연결을 시험하는 중입니다(요금 없음).") : setMsg({ text: "시험할 키가 없습니다. 키를 먼저 추가하세요.", err: true }))}
          onUse=${() => act("aiconn.use", { method: "api" })}
          onModel=${(m) => act("aiconn.set_model", { method: "api", model: m }, "API 모델을 바꿨습니다. 연결 시험을 해 보세요.")}>
          <div class="small muted">호출마다 요금 · 구간당 약 $${Number(a.section_usd).toFixed(2)}</div>
          <div class="set-key">
            ${a.keys.length > 1 ? html`<select aria-label="사용할 API 키" value=${key ? key.id : ""} disabled=${busy || v.running} onChange=${(e) => act("aiconn.select_key", { key_id: e.target.value }, "사용할 키를 바꿨습니다.")}>
                ${a.keys.map((k) => html`<option key=${k.id} value=${k.id}>${k.name} ${k.hint}</option>`)}</select>`
              : html`<span>${key ? key.name + " " + key.hint : "키 없음"}</span>`}
            <${Btn} sm=${true} kind="ghost" icon="plus" label="API 키 추가" disabled=${busy} onClick=${() => act("aiconn.add_key", {})}>추가<//>
            ${key ? html`<${Btn} sm=${true} kind="ghost" label=${key.name + " 지우기"} disabled=${busy || v.running} onClick=${() => setAsk({ kind: "remove", key })}>지우기<//>` : null}</div>
          ${ask && ask.kind === "remove" ? html`<${Ask} text=${"'" + ask.key.name + "'(" + ask.key.hint + ") 키를 지울까요? 이 PC에 저장한 사본도 지워집니다."} yes="지우기"
              onYes=${() => { const k = ask.key; setAsk(null); act("aiconn.remove_key", { key_id: k.id, confirmed: true }, "키를 지웠습니다."); }} onNo=${() => setAsk(null)} />` : null}<//>` : null}
    </div>
    ${msg ? html`<div class=${"small set-msg" + (msg.err ? " err" : "")} role="status">${msg.text}</div>` : null}
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
