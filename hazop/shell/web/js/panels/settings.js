// 설정 패널: 검토자 이름, AI 연결 상태와 안내, 프로젝트, 정보. 연결 단추의 팝업 내용을 옮긴 것이다(규격 §2.1).
import { html } from "../ui/html.js";
import { useState } from "../../vendor/hooks.module.js";
import { store, useStore } from "../store.js";
import { cmd } from "../bridge.js";
import { Btn, Chip, Switch } from "../ui/parts.js";

export function SettingsPanel({ onClose }) {
  const app = useStore((s) => s.app);
  const conn = useStore((s) => s.conn);
  const data = useStore((s) => s.drawings);
  const [name, setName] = useState(app.reviewer || "");
  const fail = (e) => store.set({ toast: { text: e.message, kind: "err" } });
  const saveName = () => cmd("settings.set_reviewer", { name }).then(() => store.set({ toast: { text: "검토자 이름을 저장했습니다." } })).catch(fail);
  const tone = conn.tone === "ok" || conn.tone === "warn" || conn.tone === "err" ? conn.tone : "";
  return html`<section class="panel" aria-label="설정">
    <div class="panel-h"><h2>설정</h2><span class="acts"><${Btn} kind="ghost" icon="x" label="패널 닫기" title="닫기 (Esc)" onClick=${onClose} /></span></div>
    <div class="panel-b">
      <div class="card"><h3>AI 연결</h3>
        <div class="kv"><div class="k"><b>Claude 구독</b><span>${conn.title || ""}</span></div><${Chip} kind=${tone}>${conn.label}<//></div>
        ${conn.guide ? html`<p class="muted" style="margin:6px 0">${conn.guide}</p>` : null}
        <div class="acts-row"><${Btn} sm=${true} icon="refresh" onClick=${() => cmd("conn.check").catch(fail)}>다시 확인<//></div></div>
      <div class="card"><h3>검토자</h3>
        <div class="field"><label for="reviewer">검토자 이름</label>
          <input id="reviewer" type="text" maxlength="60" value=${name} style="height:34px" onInput=${(e) => setName(e.target.value)} /></div>
        <div class="acts-row" style="margin-top:8px"><${Btn} sm=${true} kind="primary" disabled=${!name.trim()} onClick=${saveName}>저장<//></div></div>
      <div class="card"><h3>프로젝트</h3><div class="kv"><div class="k"><b>${data.project_id || "프로젝트 없음"}</b><span>도면 ${data.drawings.length}장 · 등록 자료 ${data.documents.length}건</span></div></div></div>
      <div class="card"><h3>시작 화면</h3>
        <div class="kv"><div class="k"><b>시작할 때 새 화면 쓰기</b><span>새 화면이 기본입니다. 끄면 다음 실행부터 이전 화면으로 열립니다. 아래 '이전 화면 열기'는 언제나 쓸 수 있습니다.</span></div>
          <${Switch} on=${app.ui_shell} label="시작할 때 새 화면 쓰기" onChange=${(v) => cmd("settings.set_default_shell", { enabled: v }).then(() => store.set((s) => ({ app: Object.assign({}, s.app, { ui_shell: v }) }))).catch(fail)} /></div></div>
      <div class="card"><h3>정보</h3><p class="muted" style="margin:0">HAZOP 분석 도구 ${app.version}</p>
        <div class="acts-row" style="margin-top:8px"><${Btn} sm=${true} onClick=${() => cmd("app.open_classic").catch(fail)}>이전 화면 열기<//></div></div>
    </div></section>`;
}
