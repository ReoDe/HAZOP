// 설계 문서 패널(완료 목록 2 A7)의 화면 상태와 엔진 잇기. 저장하는 자료는 엔진만 쓴다: 읽어 온 목록·고른 문서의 항목과 보기 상태만 들고,
// 등록·추출은 명령으로 보낸 뒤 changed("docs")로 다시 읽는다(낙관적 갱신 없음). 웹은 파일 경로를 보내지 않는다: 파일은 엔진이 창으로 고른다.
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";

const EMPTY = { project_id: null, kinds: [], count_labels: [], docs: [], totals: { docs: 0, ok: 0, problems: 0, items: 0 }, has_kg: false };

export const docs = createStore({
  summary: EMPTY,
  loaded: false,
  kind: "design_document",
  active: null,            // 항목을 펼친 문서의 자료 ID
  detail: null,            // GET docs/<자료 ID>
  busy: false,
  error: null,
  notice: null,
});

export function useDocs(selector) {
  const [value, setValue] = useState(() => selector(docs.get()));
  useLayoutEffect(() => {
    const sync = (s) => { const next = selector(s); setValue((prev) => (Object.is(prev, next) ? prev : next)); };
    sync(docs.get());
    return docs.subscribe(sync);
  }, []);
  return value;
}

const errorText = (e) => (e && e.message) || "처리하지 못했습니다.";
let seq = 0;

export function reset() {
  seq++;
  docs.set({ summary: EMPTY, loaded: false, active: null, detail: null, busy: false, error: null, notice: null });
}

export async function loadSummary() {
  const mine = ++seq;
  let s;
  try { s = await read("docs"); } catch (e) { s = null; }
  if (mine !== seq) return docs.get().summary;
  if (!s) { docs.set({ loaded: true, error: "설계 문서 목록을 읽지 못했습니다." }); return null; }
  docs.set({ summary: s, loaded: true });
  const a = docs.get().active;
  if (a && !s.docs.some((d) => d.material_id === a)) docs.set({ active: null, detail: null });
  return s;
}

export async function loadDetail(id) {
  if (!id) { docs.set({ detail: null }); return null; }
  let d = null;
  try { d = await read("docs/" + encodeURIComponent(id)); } catch (e) { d = null; }
  if (docs.get().active !== id) return null;
  docs.set({ detail: d });
  return d;
}

export async function refresh() {
  await loadSummary();
  const a = docs.get().active;
  if (a) await loadDetail(a);
}

export function setKind(kind) { docs.set({ kind }); }
export function dismissError() { docs.set({ error: null }); }

export async function toggleItems(id) {
  if (docs.get().active === id) { docs.set({ active: null, detail: null }); return null; }
  docs.set({ active: id, detail: null });
  return loadDetail(id);
}

/** 설계 문서 등록: 엔진이 파일 고르기 창을 열고, 고른 PDF마다 등록·추출 작업을 돌린다(진행·끝은 job.* 사건). 창을 취소하면 아무 일도 없다. */
export async function addDocuments() {
  docs.set({ busy: true, error: null, notice: null });
  try {
    const r = await cmd("docs.add", { kind: docs.get().kind });
    docs.set({ busy: false, notice: r.jobs.length ? "등록과 지식 추출을 시작했습니다(" + r.jobs.length + "개). 끝나면 목록에 나옵니다." : null });
    return r;
  } catch (e) { docs.set({ busy: false, error: errorText(e) }); return null; }
}

export async function extractAgain(materialId) {
  docs.set({ busy: true, error: null, notice: null });
  try {
    await cmd("docs.extract", { material_id: materialId });
    docs.set({ busy: false, notice: "지식 추출을 시작했습니다." });
  } catch (e) { docs.set({ busy: false, error: errorText(e) }); }
}

/** 지식그래프 패널에서 그 문서의 항목(또는 문서)을 연다: 도면 구성요소와 이어진 모습이 거기서 보인다. */
export async function showInGraph(nodeId) {
  const K = await import("./kg_state.js");
  store.set({ panel: "kg" });
  K.wire();
  await K.loadSummary();
  if (nodeId) await K.focus("kn:" + nodeId);
}

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "docs" || topic === "drawings") refresh(); });
  on("project.changed", () => { reset(); refresh(); });
  refresh();
}

// 채팅이 '패널 열기'를 부르면 엔진이 docs.open 사건을 보낸다. 모듈을 읽은 때부터 듣는다(패널이 닫혀 있어도 연다).
on("docs.open", () => { store.set({ panel: "docs" }); wire(); });
