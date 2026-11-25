// 엔진과 잇기(규격 §5.2). 웹 → 엔진은 명령(cmd)과 답(reply), 엔진 → 웹은 바뀜(changed)과 사건(event).
// 큰 자료는 신호로 받지 않고 hazop-app://shell/api/…로 읽는다. 브릿지가 없으면(브라우저·시험) 아무 일도 하지 않는 대역을 둔다.
import { forgetAll, sharedJson } from "./net_share.js";
const pending = new Map();
const listeners = new Map();
const changedListeners = new Set();
let seq = 0;

if (!window.hazopBridge) window.hazopBridge = { send() {}, setHandler() {} };

// 엔진의 '바뀜' 알림은 모아서 한 번에 알린다: 등록·추출이 도는 동안 알림이 연달아 와도 읽기 묶음은 마지막 알림 뒤 한 번만 나간다(같은 알림은 하나로).
// 알림이 끊이지 않아도 MAX_WAIT 안에는 한 번 내보낸다. 시험이 deliver로 넣는 알림은 모으지 않고 바로 알린다.
export const CHANGED_QUIET_MS = 150, CHANGED_MAX_WAIT_MS = 1000;
let changedBuf = new Map(), changedTimer = null, changedFirst = 0;
function flushChanged() {
  clearTimeout(changedTimer);
  changedTimer = null; changedFirst = 0;
  const batch = [...changedBuf.values()];
  changedBuf = new Map();
  forgetAll();
  for (const m of batch) changedListeners.forEach((fn) => fn(m.topic, m.rev));
}
function queueChanged(msg) {
  forgetAll();      // 알림 앞에 나간 읽기는 옛 자료일 수 있다: 알림 뒤의 읽기가 그 응답을 함께 쓰지 않게
  const key = msg.topic + "|" + (msg.rev == null ? "" : msg.rev);
  changedBuf.delete(key);
  changedBuf.set(key, msg);
  const now = Date.now();
  if (!changedFirst) changedFirst = now;
  clearTimeout(changedTimer);
  changedTimer = setTimeout(flushChanged, Math.max(0, Math.min(CHANGED_QUIET_MS, changedFirst + CHANGED_MAX_WAIT_MS - now)));
}

function handle(text, direct = false) {
  let msg;
  try { msg = JSON.parse(text); } catch (e) { return; }
  if (!msg || typeof msg !== "object") return;
  if (msg.t === "reply") {
    const p = pending.get(msg.id);
    if (!p) return;
    pending.delete(msg.id);
    clearTimeout(p.timer);
    if (msg.ok) p.resolve(msg.data);
    else p.reject(Object.assign(new Error((msg.error && msg.error.message) || "처리하지 못했습니다."), { code: msg.error && msg.error.code }));
  } else if (msg.t === "event") {
    (listeners.get(msg.name) || []).forEach((fn) => fn(msg.data));
    (listeners.get("*") || []).forEach((fn) => fn(msg.name, msg.data));
  } else if (msg.t === "changed") {
    if (direct) changedListeners.forEach((fn) => fn(msg.topic, msg.rev));
    else queueChanged(msg);
  }
}

export function connect() { window.hazopBridge.setHandler(handle); }
export function deliver(text) { handle(text, true); }   // 시험이 엔진 대신 메시지를 넣는다

function send(obj) { window.hazopBridge.send(JSON.stringify(obj)); }

let project = null;
/** 웹이 보고 있는 프로젝트 ID. 모든 명령에 실어 보내고, 엔진은 지금 프로젝트와 다르면 프로젝트에 묶인 명령(구간·결과·초기사건)을 거절한다. */
export function setProject(id) { project = id || null; }

/** 명령 하나를 보내고 답을 기다린다(120초). 실패하면 {code, message}를 가진 오류로 거절한다. */
export function cmd(name, args = {}) {
  return new Promise((resolve, reject) => {
    const id = "c" + (++seq);
    const timer = setTimeout(() => { pending.delete(id); reject(Object.assign(new Error("프로그램이 응답하지 않습니다."), { code: "timeout" })); }, 120000);
    pending.set(id, { resolve, reject, timer });
    send(Object.assign({ t: "cmd", id, name, args }, project ? { project } : {}));
  });
}

/** 도면 부품의 신호 같은 웹 → 엔진 알림(답이 없다). */
export function ui(name, data) { send({ t: "ui", name, data }); }

export function on(name, fn) {
  if (!listeners.has(name)) listeners.set(name, new Set());
  listeners.get(name).add(fn);
  return () => listeners.get(name).delete(fn);
}

export function onChanged(fn) { changedListeners.add(fn); return () => changedListeners.delete(fn); }

// 처음 화면(틀·도면 목록)이 뜨기 전에는 첫 화면에 필요한 읽기만 먼저 보내고, 나머지(구간·결과·지식그래프 등 큰 프로젝트에서 수 초 걸리는 읽기)는 목록이 뜬 뒤로 미룬다.
// 큰 프로젝트에서는 그런 읽기 하나가 파이썬 쪽 자원을 오래 차지해 도면 목록이 같이 늦어졌다(143쪽에서 열기 7초 → 아래 첫 화면 읽기만 먼저 보내면 줄어든다).
const FIRST_READS = new Set(["icons", "state", "drawings", "connection", "chat", "sheet"]);
let hold = null;
/** 부팅이 시작할 때 부른다. releaseReads()나 안전 한도(safetyMs)가 올 때까지 첫 화면 밖의 읽기를 붙잡아 둔다. */
export function holdReads(safetyMs = 6000) {
  if (hold) return;
  let open;
  const gate = new Promise((resolve) => { open = resolve; });
  hold = { gate, open, timer: setTimeout(releaseReads, safetyMs) };
}
export function releaseReads() {
  if (!hold) return;
  clearTimeout(hold.timer);
  hold.open();
  hold = null;
}

/** hazop-app://shell/api/<경로>를 읽어 JSON으로 돌려준다. */
export async function read(path) {
  if (hold && !FIRST_READS.has(String(path).split(/[/?]/)[0])) await hold.gate;
  const r = await sharedJson("/api/" + path);      // 같은 주소의 읽기가 이미 나가 있으면 그 응답을 함께 쓴다
  if (!r.ok) throw Object.assign(new Error("읽지 못했습니다: " + path), { code: "http_" + r.status });
  return r.data;
}
