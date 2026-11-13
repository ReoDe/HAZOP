// 작은 저장소(규격 §5.1): get·set·subscribe와 useStore 갈고리. 웹이 가진 것은 보기 상태뿐이다(저장하는 자료는 엔진만 쓴다).
import { useEffect, useState } from "../vendor/hooks.module.js";

export function createStore(initial) {
  let state = Object.assign({}, initial);
  const subs = new Set();
  return {
    get: () => state,
    set(patch) {
      const next = typeof patch === "function" ? patch(state) : patch;
      state = Object.assign({}, state, next);
      subs.forEach((fn) => fn(state));
    },
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  };
}

export const store = createStore({
  panel: null,            // null | "drawings" | "settings"
  sheet: null,            // 보는 도면 graph_id
  drawings: { drawings: [], documents: [], project_id: null, rev: null },
  app: { version: "", reviewer: null, chat_model: "fast", ai_review: false, ai_review_cap: 20, ui: {}, debug: false },
  conn: { state: "unchecked", label: "확인 안 함", tone: "plain", guide: "", detail: "" },
  chat: { msgs: [], busy: false, progress: null, model: "fast", availability: { blocked: false, text: "", button: null }, examples: [] },
  chatCollapsed: false,
  jobs: {},               // 작업 ID → {label, state, text, done, total, message}
  marks: { rid: null, bySheet: {} },   // 도면에 겹쳐 그릴 표시(채팅 카드가 만든다)
  command: { seq: 0 },    // 도면 부품에 한 번 하는 명령(zoomTo·fit·clearMarks)
  toast: null,
  dropOver: false,
  backTo: null,           // '분석 결과로 돌아가기' 칩: 도면에서 보기로 패널을 닫았을 때 "results"
  bubble: null,           // 도면에서 누른 구성요소 말풍선 {sheet, id, tag, kind, rect}
  iconsReady: false,
  canvasReady: false,
});

/** 저장소의 한 부분을 구독한다. selector가 같은 값을 주면 다시 그리지 않는다. */
export function useStore(selector) {
  const [value, setValue] = useState(() => selector(store.get()));
  useEffect(() => store.subscribe((s) => {
    const next = selector(s);
    setValue((prev) => (Object.is(prev, next) ? prev : next));
  }), []);
  return value;
}
