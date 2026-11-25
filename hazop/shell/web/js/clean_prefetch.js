// 정리 자료 미리 읽기(화면 단순화 6): 도면을 여는 순간 정리 자료가 이미 있게, 프로젝트를 열 때와 도면이 등록·바뀐 뒤에 앞쪽 도면부터 조금만 읽어 둔다.
// 읽는 것은 /api/clean 하나뿐이고 한 번에 하나씩, 마지막 변화 뒤 잠깐 쉬었다가 읽는다(등록·추출이 도는 동안 파이썬을 더 바쁘게 하지 않으려는 것이다).
// 쌓는 규칙은 canvas/sheet.js(cleanFor): 도면 목록의 판이 달라지면 버리고, 한도를 넘으면 오래 안 쓴 것부터 버린다. 여기서는 고침·다시 추출 알림에 그 도면 것을 버린다.
import { on, onChanged } from "./bridge.js";
import { store } from "./store.js";

export const PREFETCH_MAX = 6;       // 한 번에 미리 읽는 도면 수(쌓는 한도 CLEAN_KEEP보다 작다)
export const PREFETCH_DELAY_MS = 400;
let timer = null, lastRev = null;

async function sheetMod() {
  try { return await import("./canvas/sheet.js"); } catch (e) { return null; }      // 도면 부품을 못 읽는 환경(대역)에서는 아무 일도 하지 않는다
}
async function factsMod() {
  try { return await import("./canvas/extract_check.js"); } catch (e) { return null; }
}

/** 지금 열린 도면을 먼저, 그다음 목록 앞쪽에서 PREFETCH_MAX개. */
export function planPrefetch(state) {
  const ids = [state.sheet, ...((state.drawings && state.drawings.drawings) || []).map((d) => d.graph_id)].filter(Boolean);
  return { gids: [...new Set(ids)].slice(0, PREFETCH_MAX), rev: state.drawings ? state.drawings.rev : null };
}

export async function runPrefetch() {
  const m = await sheetMod();
  if (!m) return;
  const { gids, rev } = planPrefetch(store.get());
  if (!rev || !gids.length) return;
  try { await m.prefetchClean(gids, rev); } catch (e) { /* 미리 읽기가 안 돼도 도면을 열 때 읽는다 */ }
}

export function schedulePrefetch(delay = PREFETCH_DELAY_MS) {
  clearTimeout(timer);
  timer = setTimeout(runPrefetch, delay);
}

/** 고침·AI 후보 수락·다시 추출이 그 도면의 자료를 바꿨다: 쌓아 둔 것과 나가 있는 읽기를 버린다(오래된 자료를 보이지 않는다). id가 없으면 전부. */
export async function dropClean(id) {
  const m = await sheetMod();
  if (m) m.invalidateClean(id == null ? undefined : id);
  const f = await factsMod();
  if (f && f.dropFacts) f.dropFacts(id == null ? undefined : id);
}

let wired = false;
export function wirePrefetch() {
  if (wired) return;
  wired = true;
  store.subscribe((s) => {
    const rev = s.drawings ? s.drawings.rev : null;
    if (rev !== lastRev) { lastRev = rev; schedulePrefetch(); }
  });
  onChanged((topic, id) => { if (topic === "sheet" || topic === "edit") dropClean(typeof id === "string" ? id : undefined); });
  on("project.changed", () => { dropClean(undefined); lastRev = null; });
}
