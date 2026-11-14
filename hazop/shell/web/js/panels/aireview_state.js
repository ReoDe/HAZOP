// AI 검토 후보 영역의 화면 상태와 엔진 잇기(hazop/shell/api_aireview.py). 저장하는 자료는 엔진만 쓴다: 읽어 온 후보 목록·예상 호출 수와 보기 상태(고른 도면,
// 상한 입력, 묶음 수락 확인 중인 묶음)만 들고, 쓰기는 읽은 판(ver)을 실어 명령으로 보낸 뒤 changed("aireview")로 다시 읽는다(낙관적 갱신 없음).
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";

const EMPTY = { available: false, reason: "", ver: "", counts: {}, groups: [], bulk: [], last_run: null };

export const ai = createStore({
  graphId: null,           // 고른 도면(처음에는 보는 도면)
  overview: { drawings: [], cap: 20, run_cap: 300, seconds_per_call: 30 },
  view: EMPTY,             // GET aireview/<도면 ID>
  estimate: null,          // GET aireview/estimate?cap=
  cap: null,               // 상한 입력(없으면 설정값)
  asking: null,            // 묶음 수락을 확인 중인 할 일 이름
  busy: false,
  error: null,
  notice: null,
  picked: null,            // 도면에서 보인 후보 ID
});

export function useAi(selector) {
  const [value, setValue] = useState(() => selector(ai.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const next = selector(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(ai.get());
    return ai.subscribe(sync);
  }, []);
  return value;
}

const errorText = (e) => (e && e.message) || "처리하지 못했습니다.";
let seq = 0;

/** 프로젝트가 바뀌었을 때: 읽어 둔 것을 모두 버린다(areas.js의 resetAreas가 부를 한 줄). */
export function reset() {
  seq++;
  ai.set({ graphId: null, overview: { drawings: [], cap: 20, run_cap: 300, seconds_per_call: 30 }, view: EMPTY, estimate: null, cap: null,
    asking: null, busy: false, error: null, notice: null, picked: null });
}

export async function refresh() {
  const mine = ++seq;
  let ov = null;
  try { ov = await read("aireview"); } catch (e) { ov = null; }
  if (mine !== seq || !ov) return;
  let gid = ai.get().graphId;
  const ids = ov.drawings.map((d) => d.graph_id);
  if (!gid || !ids.includes(gid)) gid = ids.includes(store.get().sheet) ? store.get().sheet : (ov.drawings.find((d) => d.proposed) || ov.drawings[0] || {}).graph_id || null;
  ai.set({ overview: ov, graphId: gid, cap: ai.get().cap || ov.cap });
  await Promise.all([loadView(gid, mine), loadEstimate(mine)]);
}

async function loadView(gid, mine) {
  if (!gid) { ai.set({ view: EMPTY }); return; }
  let v = null;
  try { v = await read("aireview/" + encodeURIComponent(gid)); } catch (e) { v = Object.assign({}, EMPTY, { reason: "AI 후보를 읽지 못했습니다." }); }
  if (mine !== seq || ai.get().graphId !== gid) return;
  ai.set({ view: v });
}

async function loadEstimate(mine) {
  let e = null;
  try { e = await read("aireview/estimate?cap=" + encodeURIComponent(ai.get().cap || 20)); } catch (err) { e = null; }
  if (mine === seq) ai.set({ estimate: e });
}

export function pickDrawing(gid) { ai.set({ graphId: gid, asking: null, error: null, notice: null, picked: null }); refresh(); }
export function setCap(n) { ai.set({ cap: Math.max(1, Math.min(200, n || 20)) }); refresh(); }
export function dismiss() { ai.set({ error: null, notice: null }); }
export function ask(task) { ai.set({ asking: task }); }

async function write(name, args, notice) {
  ai.set({ busy: true, error: null, notice: null, asking: null });
  try {
    const r = await cmd(name, Object.assign({ graph_id: ai.get().graphId, ver: ai.get().view.ver }, args));
    const failed = (r && r.failed) || [];
    ai.set({ busy: false, notice: notice(r) + (failed.length ? " 하지 못한 후보 " + failed.length + "건: " + failed.slice(0, 3).map((f) => f.reason).join(" · ") : "")
      + ((r && r.notes && r.notes.length) ? " " + r.notes.join(" ") : "") + ((r && r.recheck && r.recheck.length) ? " " + r.recheck.join(" ") : "") });
    await refresh();
    return r;
  } catch (e) {
    ai.set({ busy: false, error: errorText(e) });
    if (e && e.code === "stale") await refresh();
    return null;
  }
}

export const accept = (id) => write("aireview.accept", { cand_ids: [id] }, (r) => r.changed.length ? "수락했습니다. 그래프에 바로 반영했습니다." : "바뀐 것이 없습니다.");
export const reject = (id) => write("aireview.reject", { cand_ids: [id] }, (r) => r.changed.length ? "거절했습니다." : "바뀐 것이 없습니다.");
export const revert = (id) => write("aireview.revert", { cand_ids: [id] }, (r) => r.changed.length ? "되돌렸습니다. 그래프도 되돌렸습니다." : "바뀐 것이 없습니다.");
export const acceptBulk = (task) => write("aireview.accept_bulk", { task }, (r) => r.changed.length + "건을 한 번에 수락했습니다. 하나씩 되돌릴 수 있습니다.");

/** 고른 도면에 AI 검토 실행(작업 줄에 진행이 보인다). 끝나면 엔진이 changed("aireview")를 보낸다. */
export async function run() {
  ai.set({ busy: true, error: null, notice: null });
  try {
    const est = ai.get().estimate;
    await cmd("aireview.run", { graph_ids: [ai.get().graphId], cap: ai.get().cap || 20, conn_ver: (est && est.conn && est.conn.conn_ver) || "-" });
    ai.set({ busy: false, notice: "AI 검토를 시작했습니다. 진행은 도면 패널의 작업 줄에 보입니다." });
  } catch (e) {
    ai.set({ busy: false, error: errorText(e) });
    if (e && e.code === "conn_changed") await refresh();      // 연결이 바뀌었으면 새 연결을 보이고 다시 누르게 한다
  }
}

// ---------------------------------------------------------------- 도면에서 보기
function bump(command) { store.set((s) => ({ command: Object.assign({ seq: s.command.seq + 1 }, command) })); }

/** 후보 자리로 이동해 강조한다: 그 도면을 열고(다르면), 호박색 표시를 그리고, 그 자리로 확대한다. 패널은 도면을 가리므로 닫는다(지식그래프 패널의
 *  '도면에서 보기'와 같다). 다시 열면 고른 도면·고른 후보가 그대로 남아 있다. */
export function showOnSheet(row) {
  const gid = ai.get().graphId;
  if (!gid || !row || !row.local_id) return false;
  const opened = store.get().sheet !== gid;
  const mark = { op: "mark", groups: [{ ids: [row.local_id], style: "warn", label: "AI 후보 · " + row.field_label }], dim_others: false };
  store.set({ sheet: gid, panel: null, marks: { rid: "aireview", bySheet: { [gid]: [mark] } } });
  ai.set({ picked: row.cand_id });
  if (opened) {
    cmd("sheet.open", { graph_id: gid }).catch(() => {});
    [350, 900, 1800].forEach((ms) => setTimeout(() => { if (store.get().sheet === gid) bump({ type: "zoomTo", ids: [row.local_id], pad: 4 }); }, ms));
  } else bump({ type: "zoomTo", ids: [row.local_id], pad: 4 });
  return true;
}

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "aireview" || topic === "drawings" || topic === "aisettings") refresh(); });
  refresh();
}
