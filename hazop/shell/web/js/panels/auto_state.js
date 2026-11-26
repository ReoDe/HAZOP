// 자동 확정의 화면 쪽(읽기 aireview/auto, 명령 aireview.consent): 도면 줄의 까닭 점, 처음 한 번의 전송 동의 질문, 설정의 같은 선택.
// 판정과 저장은 엔진이 한다. 여기는 읽어 온 값을 보이고 사람의 답을 명령으로 보낼 뿐이다.
import { html } from "../ui/html.js";
import { useEffect, useState } from "../../vendor/hooks.module.js";
import { store } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";
import { Btn, Switch } from "../ui/parts.js";
import { addNotice, clearNotice } from "../notices.js";

/** 자동 확정이 '추출만 됨'으로 멈춘 도면의 까닭(사람 말, 할 일이 있는 말로). 여기에 없는 까닭(started·error·stopped)은 표시하지 않는다: 곧 이어지거나 사람이 멈춘 것이다. */
export const WAIT_TEXT = {
  no_connection: "연결된 AI가 없습니다(설정).",
  no_consent: "조각을 AI에 보내도록 허락하지 않았습니다(설정).",
  images_off: "그림 보내기가 꺼져 있습니다(설정).",
  ai_off: "이 프로젝트는 AI로 보내지 않게 해 두었습니다.",
  limit: "AI 사용 한도에 닿았습니다. 한도가 풀리면 이어 합니다.",
  error_final: "읽기를 마치지 못했습니다. 채팅에서 다시 읽기를 요청하세요.",
  run_cap: "한 번에 보낼 호출 수에 닿아 나머지는 읽기만 했습니다.",
  taken: "같은 번호의 도면이 있어 기다립니다. 채팅에서 번호를 알려 주세요.",
  scan: "스캔 그림이라 읽기만 했습니다.",
  no_image: "도면 그림이 없어 AI가 보지 못했습니다.",
};
export const UNREAD_TEXT = "읽지 못했습니다.";
export const UNSAVED_TEXT = "저장하지 못했습니다. 이번 실행 동안은 보내지 않지만, 다시 열면 보내게 됩니다. 다시 시도하세요.";

/** 엔진이 주는 자동 확정 요약(없으면 null): {consent: {allow, asked, unsaved}, connected, ask, sheets: [...]}. 바뀔 때마다 다시 읽는다. */
export function useAuto() {
  const [auto, setAuto] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => read("aireview/auto").then((d) => { if (alive) setAuto(d); }).catch(() => { if (alive) setAuto(null); });
    load();
    const off = onChanged((t) => { if (t === "aireview" || t === "sheetconf" || t === "drawings" || t === "state" || t === "aisettings") load(); });
    return () => { alive = false; off(); };
  }, []);
  useEffect(() => { syncUnsavedNotice(auto); }, [auto]);
  return auto;
}

/** 동의를 거두는 저장이 실패한 동안은 알림 줄에 남긴다(자료가 밖으로 나가는 일이라 사라지는 토스트로 끝내지 않는다). */
export function syncUnsavedNotice(auto) {
  if (auto && auto.consent && auto.consent.unsaved) addNotice({ id: "consent-unsaved", key: "1", kind: "warn", text: UNSAVED_TEXT });
  else if (auto) clearNotice("consent-unsaved");
}

/** 도면 {graph_id: 까닭 글}: 멈춘 도면만. 잘 끝난 도면과 진행 중인 도면은 없다. 연결된 AI가 없으면 '허락 안 함'보다 그 까닭이 먼저다. */
export function waitsOf(auto) {
  const out = {};
  for (const r of (auto && auto.sheets) || []) {
    if (r.result !== "waiting") continue;
    const why = r.why === "no_consent" && auto.connected === false ? "no_connection" : r.why;
    if (WAIT_TEXT[why]) out[r.graph_id] = WAIT_TEXT[why];
  }
  return out;
}

const fail = (e) => store.set({ toast: { text: (e && e.message) || "저장하지 못했습니다.", kind: "err" } });
export const answer = (allow) => cmd("aireview.consent", { allow }).catch((e) => {
  if (allow) fail(e);
  else addNotice({ id: "consent-unsaved", key: "1", kind: "warn", text: (e && e.message) || UNSAVED_TEXT });      // 철회가 저장되지 않았다: 남는 알림
});

/** AI가 연결돼 있는데 아직 묻지 않았고 기다리는 도면이 있을 때만 한 번 묻는다. 답하면 다시 묻지 않는다. */
export function ConsentAsk({ auto }) {
  if (!auto || !auto.ask) return null;
  return html`<div class="set-ask" role="alertdialog" aria-label="도면 조각 전송 동의"><span>올린 도면의 조각을 AI에 보내 읽기를 돕게 할까요?</span>
    <span class="set-ask-b"><${Btn} sm=${true} kind="primary" label="보냄" onClick=${() => answer(true)}>보냄<//><${Btn} sm=${true} kind="ghost" label="보내지 않음" onClick=${() => answer(false)}>보내지 않음<//></span></div>`;
}

/** 도면 조각 그림을 AI에 보낼지(설정, 기본 켬). 바뀌면 엔진이 changed("aireview")를 보낸다. */
const setImages = (on) => cmd("extract.set_ai_review", { images: !!on }).catch(fail);

/** 설정의 같은 선택(언제든 바꾼다)과 그 아래 그림 보내기 한 줄. 스위치는 저장된 값을 보인다: 철회 저장이 실패한 동안은 파일에 남은 '보냄'이다. */
export function ConsentSetting() {
  const auto = useAuto();
  const [images, setImg] = useState(true);
  useEffect(() => {
    let alive = true;
    const load = () => read("aireview").then((d) => { if (alive) setImg(!d || d.images !== false); }).catch(() => {});
    load();
    const off = onChanged((t) => { if (t === "aireview") load(); });
    return () => { alive = false; off(); };
  }, []);
  if (!auto) return null;
  const on = auto.consent.unsaved ? true : !!auto.consent.allow;
  return html`<div class="card"><div class="kv"><div class="k"><b>도면 조각을 AI에 보내 읽기 돕기</b></div>
    <${Switch} on=${on} label="도면 조각을 AI에 보내 읽기 돕기" onChange=${answer} /></div>
    <div class="kv"><div class="k"><b>조각 그림도 보내기</b></div>
    <${Switch} on=${images} label="조각 그림도 보내기" onChange=${(v) => { setImg(v); setImages(v); }} /></div></div>`;
}
