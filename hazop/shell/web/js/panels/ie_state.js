// 초기사건(3단계 ⑥)의 화면 상태와 엔진 잇기. 저장하는 자료는 엔진만 쓴다: 읽어 온 판(요약·그룹 상세)과 보기 상태(보기·고른 그룹·고른 후보)만 들고,
// 쓰기는 읽은 판 지문(ver)·⑤ 결과 지문(rver)·화면이 본 항목 지문(seen)을 실어 명령으로 보낸 뒤 changed("ie")로 다시 읽는다(낙관적 갱신 없음).
// 엔진이 'confirm'으로 되물으면(지우기, 확정 그룹을 초안으로 내리는 변경) 그 글을 ask에 두고, 사용자가 '계속'을 누르면 같은 인자에 confirmed를 붙여 다시 보낸다.
import { useLayoutEffect, useState } from "../../vendor/hooks.module.js";
import { createStore } from "../store.js";
import { cmd, onChanged, read } from "../bridge.js";

const EMPTY = { available: false, reason: "", ver: "none", rver: "none", kpi: null, groups: [], unassigned: [], completeness: [], warnings: [], warning_summary: [] };

export const ie = createStore({
  summary: EMPTY,
  view: "groups",          // "groups" | "completeness" | "warnings"
  active: null,            // 고른 그룹 ID
  detail: null,            // GET ie/group/<id>
  picked: [],              // 고른 후보 ID(묶이지 않은 후보 또는 고른 그룹의 소속 후보)
  busy: false,
  error: null,
  notice: null,
  ask: null,               // {name, args, notice, message}: 엔진이 되물은 것
  fmea: null,              // GET ie/fmea (P5: FMEA 행·전기·제어 구간·구성요소)
  mld: null,               // GET ie/mld (P5: MLD 잎 가지 대조)
  frow: null,              // 고른 FMEA 행 ID
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
  ie.set({ summary: EMPTY, view: "groups", active: null, detail: null, picked: [], busy: false, error: null, notice: null, ask: null, fmea: null, mld: null, frow: null });
}

export async function loadSummary() {
  const mine = ++seq;
  let s = null;
  try { s = await read("ie"); } catch (e) { s = Object.assign({}, EMPTY, { reason: "초기사건을 읽지 못했습니다." }); }
  if (mine !== seq) return ie.get().summary;
  ie.set({ summary: s });
  const a = ie.get().active;
  if (a && !(s.groups || []).some((g) => g.group_id === a)) ie.set({ active: null, detail: null });
  const live = new Set((s.unassigned || []).map((c) => c.candidate_id));
  const d = ie.get().detail;
  if (d) d.members.forEach((c) => live.add(c.candidate_id));
  ie.set({ picked: ie.get().picked.filter((x) => live.has(x)) });
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
  const v = ie.get().view;
  if (v === "fmea") await loadFmea();
  if (v === "completeness") await loadMld();
}

export async function loadFmea() {
  let f = null;
  try { f = await read("ie/fmea"); } catch (e) { f = null; }
  ie.set({ fmea: f });
  return f;
}

export async function loadMld() {
  let m = null;
  try { m = await read("ie/mld"); } catch (e) { m = null; }
  ie.set({ mld: m });
  return m;
}

export function setView(view) {
  ie.set({ view });
  if (view === "fmea") loadFmea();
  if (view === "completeness") loadMld();
}
export function openGroup(gid) { ie.set({ active: gid, detail: null, view: "groups", error: null, picked: [] }); return loadDetail(gid); }
export function dismissError() { ie.set({ error: null }); }
export function togglePick(id) { const p = ie.get().picked; ie.set({ picked: p.includes(id) ? p.filter((x) => x !== id) : p.concat([id]) }); }
export function clearPicked() { ie.set({ picked: [] }); }

/** 화면이 지금 보고 있는 항목 지문. 명령이 건드리는 그룹·후보·기록은 모두 여기에 있어야 엔진이 받는다. */
export function seenMap() {
  const { summary: s, detail: d } = ie.get();
  const m = {};
  (s.unassigned || []).forEach((c) => { m["member:" + c.candidate_id] = c.fp; });
  (s.groups || []).forEach((g) => { m["group:" + g.group_id] = g.fp; });
  (s.completeness || []).forEach((r) => { if (r.code) m["coverage:" + r.code] = r.fp; });
  const mld = ie.get().mld;
  if (mld) (mld.branches || []).forEach((b) => { m["coverage:MLD:" + b.id] = b.fp; });
  if (d) {
    m["group:" + d.group.group_id] = d.group.fp;
    d.members.forEach((c) => { m["member:" + c.candidate_id] = c.fp; });
    d.headings.forEach((h) => { m["heading:" + h.heading_id] = h.fp; });
    d.end_states.forEach((e) => { m["end_state:" + e.end_state_id] = e.fp; });
    d.basic_events.forEach((b) => { m["basic_event:" + b.be_id] = b.fp; });
  }
  return m;
}

async function write(name, args, notice, sent) {
  ie.set({ busy: true, error: null, notice: null, ask: null });
  const s = ie.get().summary;
  const full = sent || Object.assign({ ver: s.ver, rver: s.rver, seen: seenMap() }, args);
  try {
    const r = await cmd(name, full);
    if (r && r.ask) {           // 엔진이 되물음: 카드가 보인 때의 인자(지문 포함)와 확정이 풀릴 그룹 목록을 그대로 들고 있는다
      ie.set({ busy: false, ask: { name, full, notice, message: r.ask.message, groups: r.ask.groups || [] } });
      return null;
    }
    await refresh();                      // 다시 읽기가 끝날 때까지 busy: 그 사이 누르면 옛 지문이 실려 거절된다
    ie.set({ busy: false, notice: (typeof notice === "function" ? notice(r) : notice) || null });
    return r;
  } catch (e) {
    if (e && e.code === "confirm") { ie.set({ busy: false, ask: { name, full, notice, message: errorText(e), groups: [] } }); return null; }
    if (e && e.code === "stale") await refresh();
    ie.set({ busy: false, error: errorText(e) });
    return null;
  }
}

/** 되물은 것에 '계속': 카드가 보인 때의 인자(ver·rver·seen) 그대로 confirmed와 카드에 보인 그룹 목록을 붙여 보낸다.
 *  그 사이 무엇이든 바뀌었거나 확정이 풀릴 그룹이 카드와 다르면 엔진이 거절한다. */
export function confirmAsk() {
  const a = ie.get().ask;
  if (!a) return null;
  return write(a.name, {}, a.notice, Object.assign({}, a.full, { confirmed: true, confirm_groups: a.groups }));
}
export function cancelAsk() { ie.set({ ask: null }); }

export const suggest = () => write("ie.suggest", {}, "규칙 초안을 만들었습니다. 초안은 확정하지 않은 상태입니다.");
export const confirmGroup = (gid) => write("ie.confirm", { group_id: gid }, gid + " 그룹을 확정했습니다.");
export const reopenGroup = (gid) => write("ie.reopen", { group_id: gid }, gid + " 그룹의 확정을 풀었습니다.");

export async function createGroup(name, iecs) {
  const r = await write("ie.create_group", { name, iecs }, (x) => x.group_id + " 그룹을 만들었습니다(초안).");
  if (r && r.group_id) { ie.set({ picked: [] }); await openGroup(r.group_id); }
  return r;
}
export async function moveTo(iecs, to) {
  const r = await write("ie.move", { iecs, to: to || "" }, to ? "후보 " + iecs.length + "개를 " + to + "(으)로 옮겼습니다." : "후보 " + iecs.length + "개를 그룹에서 뺐습니다.");
  if (r) ie.set({ picked: [] });
  return r;
}
export const acceptMembers = (iecs) => write("ie.accept_members", { iecs }, "소속을 확인했습니다.");
export const editGroup = (gid, fields) => write("ie.edit_group", { group_id: gid, fields }, gid + " 그룹을 고쳤습니다.");
export async function splitGroup(gid, moved) {
  const r = await write("ie.split", { group_id: gid, moved }, (x) => gid + " 그룹을 " + x.groups.join(" · ") + "(으)로 나눴습니다.");
  if (r && r.groups) { ie.set({ picked: [] }); await openGroup(r.groups[1]); }
  return r;
}
export const deleteGroup = (gid) => write("ie.delete_group", { group_id: gid }, gid + " 그룹을 지웠습니다.");
export const addRecord = (kind, gid, fields) => write("ie.add_record", { kind, group_id: gid, fields }, (x) => x.id + "을(를) 더했습니다.");
export const editRecord = (kind, id, fields) => write("ie.edit_record", { kind, id, fields }, id + "을(를) 고쳤습니다.");
export const acceptRecord = (kind, id) => write("ie.accept_record", { kind, id }, id + "을(를) 받아들였습니다.");
export const removeRecord = (kind, id) => write("ie.remove_record", { kind, id }, id + "을(를) 지웠습니다.");
export const setCoverage = (code, disposition, reason) => write("ie.set_coverage", { code, disposition: disposition || "", reason: reason || "" },
  disposition ? code + " 범주 판정을 저장했습니다." : code + " 범주 판정을 지웠습니다.");
export const replaceUnreadable = () => write("ie.replace_unreadable", {}, "원본을 백업하고 빈 문서로 새로 시작했습니다.");

let wired = false;
export function wire() {
  if (wired) return;
  wired = true;
  onChanged((topic) => { if (topic === "ie" || topic === "results" || topic === "nodes") refresh(); });
  refresh();
}

/** 인계 묶음 내보내기(승인 항목만, Excel + 같은 이름의 JSON): 저장 위치와 덮어쓰기는 창이 묻고 웹에는 파일 이름만 돌아온다. */
export async function exportBundle() {
  ie.set({ busy: true, error: null, notice: null });
  const s = ie.get().summary;
  try {
    const r = await cmd("ie.export", { ver: s.ver, rver: s.rver });
    ie.set({ busy: false, notice: r.cancelled ? (r.reason || null) : "초기사건 인계 묶음을 내보냈습니다: " + r.path + " · " + r.json_path + " · 후보 " + r.candidates + "개 · 그룹 " + r.groups + "개" });
    return r;
  } catch (e) {
    ie.set({ busy: false, error: errorText(e) });
    if (e && e.code === "stale") await refresh();
    return null;
  }
}

// ---------------------------------------------------------------- P5: FMEA·MLD(설계 §8.2). 쓰기는 그 파일의 지문(fver·mver)과 화면이 본 행 지문을 싣는다
async function sideWrite(name, args, notice, after) {
  ie.set({ busy: true, error: null, notice: null });
  try {
    const r = await cmd(name, args);
    await refresh();
    if (after) after(r);
    ie.set({ busy: false, notice: (typeof notice === "function" ? notice(r) : notice) || null });
    return r;
  } catch (e) {
    if (e && e.code === "stale") await refresh();
    ie.set({ busy: false, error: errorText(e) });
    return null;
  }
}
const fseen = () => Object.fromEntries(((ie.get().fmea || {}).rows || []).map((r) => ["fmea:" + r.row_id, r.fp]));
const fver = () => (ie.get().fmea || {}).fver || "none";
export const pickRow = (id) => ie.set({ frow: ie.get().frow === id ? null : id });
export const fmeaTemplate = () => sideWrite("ie.fmea_template", {}, (r) => (r.cancelled ? null : "FMEA 양식을 내보냈습니다: " + r.path + " · 행 " + r.rows + "개"));
export const fmeaImport = () => sideWrite("ie.fmea_import", { fver: fver() }, (r) => (r.cancelled ? null
  : "FMEA를 가져왔습니다: " + r.file + " · 새 행 " + r.report.new + " · 바뀐 행 " + r.report.changed + " · 대응 실패 " + r.report.unmatched
    + (r.reopened.length ? " · 승인이 풀린 행 " + r.reopened.join(", ") : "") + (r.report.problems.length ? " · " + r.report.problems.join(" ") : "")));
export const fmeaStatus = (ids, status) => sideWrite("ie.fmea_status", { fver: fver(), seen: fseen(), row_ids: ids, status },
  ids.join(", ") + ({ approved: " 승인", excluded: " 제외", imported: " 가져옴으로 되돌림" }[status] || ""));
export const fmeaEdit = (id, fields) => sideWrite("ie.fmea_edit", { fver: fver(), seen: fseen(), row_id: id, fields }, id + "을(를) 고쳤습니다.");
export const fmeaMark = (nodeId, mark) => sideWrite("ie.fmea_mark", { fver: fver(), seen: fseen(), node_id: nodeId, mark: mark || "" },
  nodeId + (mark === "include" ? " 구간을 전기·제어 구간에 넣었습니다." : mark === "exclude" ? " 구간을 전기·제어 구간에서 뺐습니다." : " 구간 표시를 지웠습니다."));
const mver = () => (ie.get().mld || {}).mver || "none";
export const mldImport = () => sideWrite("ie.mld_import", { mver: mver() }, (r) => (r.cancelled ? null : "MLD를 가져왔습니다: " + r.file + " · 가지 " + r.branches + "개"));
export const mldLink = (branchId, groupIds) => sideWrite("ie.mld_link", { mver: mver(), seen: seenMap(), branch_id: branchId, group_ids: groupIds },
  branchId + (groupIds.length ? " 가지에 " + groupIds.join(", ") + "을(를) 이었습니다." : " 가지의 연결을 지웠습니다."));
