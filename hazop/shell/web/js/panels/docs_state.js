// 설계 문서 패널(완료 목록 2 A7)의 화면 상태와 엔진 잇기. 저장하는 자료는 엔진만 쓴다: 읽어 온 목록·고른 문서의 항목과 보기 상태만 들고,
// 등록·추출·판 대응은 명령으로 보낸 뒤 changed("docs")로 다시 읽는다(낙관적 갱신 없음). 웹은 파일 경로를 보내지 않는다: 파일은 엔진이 창으로 고른다.
// 이 패널이 시작한 작업의 끝(job.done·job.failed)은 여기서 듣고 결과(지식그래프 만들기 실패, 같은 파일, 판 대응)를 알림으로 보인다.
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore, store } from "../store.js";
import { cmd, on, onChanged, read } from "../bridge.js";

const EMPTY = { project_id: null, count_labels: [], docs: [], totals: { docs: 0, problems: 0, asks: 0 }, kg: { state: "none", text: null, build_error: null, recheck: [] } };

export const docs = createStore({
  summary: EMPTY,
  loaded: false,
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
const mine = new Map();       // 이 패널이 시작한 작업 ID -> 이름

export function reset() {
  seq++;
  mine.clear();
  docs.set({ summary: EMPTY, loaded: false, active: null, detail: null, busy: false, error: null, notice: null });
}

export async function loadSummary() {
  const me = ++seq;
  let s;
  try { s = await read("docs"); } catch (e) { s = null; }
  if (me !== seq) return docs.get().summary;
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

export function dismissError() { docs.set({ error: null }); }
export function dismissNotice() { docs.set({ notice: null }); }

export async function toggleItems(id) {
  if (docs.get().active === id) { docs.set({ active: null, detail: null }); return null; }
  docs.set({ active: id, detail: null });
  return loadDetail(id);
}

async function start(name, args, label) {
  docs.set({ busy: true, error: null, notice: null });
  try {
    const r = await cmd(name, args);
    (r.jobs || (r.job ? [r.job] : [])).forEach((id) => mine.set(id, label));
    docs.set({ busy: false });
    return r;
  } catch (e) { docs.set({ busy: false, error: errorText(e) }); return null; }
}

/** 설계 문서 등록: 엔진이 파일 고르기 창을 열고, 고른 PDF마다 등록·추출 작업을 돌린다. 창을 취소하면 아무 일도 없다. */
export const addDocuments = () => start("docs.add", {}, "등록");
export const extractAgain = (materialId) => start("docs.extract", { material_id: materialId }, "추출 다시 하기");
/** 같은 문서의 새 판인지 묻는 물음에 답한다: replace(old를 이 문서가 대신) · separate(다른 문서). */
export const answerRevision = (materialId, answer, old) => start("docs.revision", Object.assign({ material_id: materialId, answer }, old ? { old } : {}), "판 대응");

/** 작업 결과 -> 알림 {text, kind}. 지식그래프를 만들지 못했으면 오류로 보인다(문서 행의 '이어짐'을 믿지 않게). */
export function resultNotice(label, r) {
  const parts = [];
  if (r.skipped) parts.push(r.skipped);
  else if (r.outcome === "replace") parts.push("새 판으로 지정했습니다. 옛 판의 지식은 지식그래프에서 빠집니다.");
  else if (r.outcome === "separate") parts.push("다른 문서로 두었습니다. 두 문서의 지식을 모두 씁니다.");
  else if (r.blocked && r.blocked.length) parts.push(label + ": 추출하지 못했습니다(" + r.blocked.join("; ") + ").");
  else {
    const c = r.counts || {};
    parts.push(label + ": 설정치 " + (c.setpoint || 0) + " · 운전조건 " + (c.condition || 0) + " · 요건 " + (c.requirement || 0) + "개를 뽑았습니다.");
  }
  const v = r.revision;
  if (v && v.action === "replace" && v.old) parts.push("같은 문서의 옛 판(" + v.old + ")을 대신합니다: " + v.reason + ".");
  if (v && v.action === "ask") parts.push("같은 문서의 새 판인지 목록에서 확인해 주세요(" + v.reason + ").");
  (r.kg_notes || []).forEach((n) => parts.push(n));
  if (r.kg_error) return { kind: "err", text: parts.join(" ") + " 다만 지식그래프를 다시 만들지 못했습니다: " + r.kg_error };
  return { kind: "info", text: parts.join(" ") };
}

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "docs" || topic === "drawings") refresh(); });
  on("project.changed", () => { reset(); refresh(); });
  on("job.done", (d) => {
    if (!mine.has(d.id)) return;
    const n = resultNotice(d.label || mine.get(d.id), d.result || {});
    mine.delete(d.id);
    docs.set(n.kind === "err" ? { error: n.text } : { notice: n.text });
    refresh();
  });
  on("job.failed", (d) => {
    if (!mine.has(d.id)) return;
    mine.delete(d.id);
    docs.set({ error: (d.label ? d.label + ": " : "") + (d.message || "처리하지 못했습니다.") });
    refresh();
  });
  refresh();
}

/** 지식그래프 패널에서 그 문서의 항목(또는 문서)을 연다: 도면 구성요소와 이어진 모습이 거기서 보인다. */
export async function showInGraph(nodeId) {
  const K = await import("./kg_state.js");
  store.set({ panel: "kg" });
  K.wire();
  await K.loadSummary();
  if (nodeId) await K.focus("kn:" + nodeId);
}

// 채팅이 '패널 열기'를 부르면 엔진이 docs.open 사건을 보낸다. 모듈을 읽은 때부터 듣는다(패널이 닫혀 있어도 연다).
on("docs.open", () => { store.set({ panel: "docs" }); wire(); });
