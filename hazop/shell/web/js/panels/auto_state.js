// 자동 확정의 화면 쪽(읽기 aireview/auto, 명령 aireview.consent): 도면 줄의 까닭 점, 처음 한 번의 전송 동의 질문, 설정의 같은 선택.
// 판정과 저장은 엔진이 한다. 여기는 읽어 온 값을 보이고 사람의 답을 명령으로 보낼 뿐이다.
import { html } from "../ui/html.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { store } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Btn, Switch } from "../ui/parts.js";

/** 자동 확정이 '추출만 됨'으로 멈춘 도면의 까닭(사람 말). 여기에 없는 까닭(started·error·stopped)은 표시하지 않는다: 곧 이어지거나 사람이 멈춘 것이다. */
export const WAIT_TEXT = {
  no_connection: "AI에 연결되지 않아 추출만 됐습니다. 설정에서 연결하세요.",
  no_consent: "AI로 보내는 것을 허락하지 않아 추출만 됐습니다.",
  images_off: "도면 조각 그림을 AI로 보내지 않게 해 두어 추출만 됐습니다.",
  ai_off: "이 프로젝트는 AI로 보내지 않게 해 두어 추출만 됐습니다.",
  limit: "AI 사용 한도에 닿아 추출만 됐습니다. 한도가 풀리면 이어 합니다.",
  error_final: "AI가 여러 번 답하지 못해 추출만 됐습니다.",
  run_cap: "한 번에 보낼 호출 수에 닿아 나머지는 추출만 됐습니다.",
  taken: "같은 번호의 도면이 이미 있어 번호를 확정하지 못했습니다.",
  scan: "스캔 도면이라 자동으로 메우지 못했습니다.",
  no_image: "도면 그림이 없어 AI가 보지 못했습니다.",
};

/** 엔진이 주는 자동 확정 요약(없으면 null): {consent: {allow, asked}, ask, sheets: [...]}. 바뀔 때마다 다시 읽는다. */
export function useAuto() {
  const [auto, setAuto] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => read("aireview/auto").then((d) => { if (alive) setAuto(d); }).catch(() => { if (alive) setAuto(null); });
    load();
    const off = onChanged((t) => { if (t === "aireview" || t === "sheetconf" || t === "drawings" || t === "state") load(); });
    return () => { alive = false; off(); };
  }, []);
  return auto;
}

/** 도면 {graph_id: 까닭 글}: 멈춘 도면만. 잘 끝난 도면과 진행 중인 도면은 없다. */
export function waitsOf(auto) {
  const out = {};
  for (const r of (auto && auto.sheets) || []) if (r.result === "waiting" && WAIT_TEXT[r.why]) out[r.graph_id] = WAIT_TEXT[r.why];
  return out;
}

const fail = (e) => store.set({ toast: { text: (e && e.message) || "저장하지 못했습니다.", kind: "err" } });
export const answer = (allow) => cmd("aireview.consent", { allow }).catch(fail);

/** AI가 연결돼 있는데 아직 묻지 않았고 기다리는 도면이 있을 때만 한 번 묻는다. 답하면 다시 묻지 않는다. */
export function ConsentAsk({ auto }) {
  if (!auto || !auto.ask) return null;
  return html`<div class="set-ask" role="alertdialog" aria-label="도면 조각 전송 동의"><span>올린 도면의 조각을 AI에 보내 읽기를 돕게 할까요?</span>
    <span class="set-ask-b"><${Btn} sm=${true} kind="primary" label="보냄" onClick=${() => answer(true)}>보냄<//><${Btn} sm=${true} kind="ghost" label="보내지 않음" onClick=${() => answer(false)}>보내지 않음<//></span></div>`;
}

/** 설정의 같은 선택 한 줄(언제든 바꾼다). */
export function ConsentSetting() {
  const auto = useAuto();
  if (!auto) return null;
  return html`<div class="card"><div class="kv"><div class="k"><b>도면 조각을 AI에 보내 읽기 돕기</b></div>
    <${Switch} on=${!!auto.consent.allow} label="도면 조각을 AI에 보내 읽기 돕기" onChange=${answer} /></div></div>`;
}
