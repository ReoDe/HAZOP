// 초기사건(3단계 ⑥)의 화면 상태와 엔진 잇기. 저장하는 자료는 엔진만 쓴다: 읽어 온 판(요약·그룹 상세)과 보기 상태(보기·고른 그룹)만 들고, 쓰기는 읽은 판 지문(ver)을
// 실어 명령으로 보낸 뒤 changed("ie")로 다시 읽는다(낙관적 갱신 없음).
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";

const EMPTY = { available: false, reason: "", ver: "none", kpi: null, groups: [], unassigned: [], completeness: [], warnings: [], warning_summary: [] };

export const ie = createStore({
  summary: EMPTY,
  view: "groups",          // "groups" | "completeness" | "warnings"
  active: null,            // 고른 그룹 ID
  detail: null,            // GET ie/group/<id>
  busy: false,
  error: null,
  notice: null,
});

export function useIe(selector) {
  const [value, setValue] = useState(() => selector(ie.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const next = selector(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(ie.get());
    return ie.subscribe(sync);
  }, []);
  return value;
}

const errorText = (e) => (e && e.message) || "처리하지 못했습니다.";

let seq = 0;

/** 프로젝트가 바뀌었을 때: 읽어 둔 것과 진행 중인 읽기 결과를 모두 버린다. */
export function reset() {
  seq++;
  ie.set({ summary: EMPTY, view: "groups", active: null, detail: null, busy: false, error: null, notice: null });
}

export async function loadSummary() {
  const mine = ++seq;
  let s = null;
  try { s = await read("ie"); } catch (e) { s = Object.assign({}, EMPTY, { reason: "초기사건을 읽지 못했습니다." }); }
  if (mine !== seq) return ie.get().summary;
  ie.set({ summary: s });
  const a = ie.get().active;
  if (a && !(s.groups || []).some((g) => g.group_id === a)) ie.set({ active: null, detail: null });
  return s;
}

export async function loadDetail(gid) {
  if (!gid) { ie.set({ detail: null }); return null; }
  let d = null;
  try { d = await read("ie/group/" + encodeURIComponent(gid)); } catch (e) { d = null; }
  if (ie.get().active !== gid) return null;
  ie.set({ detail: d });
  return d;
}

export async function refresh() {
  await loadSummary();
  const a = ie.get().active;
  if (a) await loadDetail(a);
}

export function setView(view) { ie.set({ view }); }
export function openGroup(gid) { ie.set({ active: gid, detail: null, view: "groups", error: null }); return loadDetail(gid); }
export function dismissError() { ie.set({ error: null }); }

async function write(name, args, notice) {
  ie.set({ busy: true, error: null, notice: null });
  try {
    const r = await cmd(name, Object.assign({ ver: ie.get().summary.ver }, args));
    ie.set({ busy: false, notice: notice || null });
    await refresh();
    return r;
  } catch (e) {
    ie.set({ busy: false, error: errorText(e) });
    if (e && e.code === "stale") await refresh();
    return null;
  }
}

export const suggest = () => write("ie.suggest", {}, "규칙 초안을 만들었습니다. 초안은 확정하지 않은 상태입니다.");
export const confirmGroup = (gid) => write("ie.confirm", { group_id: gid }, gid + " 그룹을 확정했습니다.");
export const reopenGroup = (gid) => write("ie.reopen", { group_id: gid }, gid + " 그룹의 확정을 풀었습니다.");

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "ie" || topic === "results" || topic === "nodes") refresh(); });
  refresh();
}

/** 인계 묶음 내보내기: 저장 위치는 창이 대화상자로 묻고 웹에는 파일 이름만 돌아온다. */
export async function exportBundle() {
  ie.set({ busy: true, error: null, notice: null });
  try {
    const r = await cmd("results.export_ie");
    ie.set({ busy: false, notice: r.cancelled ? null : "초기사건 인계 묶음을 내보냈습니다: " + r.path + " · 후보 " + r.candidates + "개" });
    return r;
  } catch (e) { ie.set({ busy: false, error: errorText(e) }); return null; }
}
