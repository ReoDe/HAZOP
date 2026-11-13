// 엔진과 잇기(규격 §5.2). 웹 → 엔진은 명령(cmd)과 답(reply), 엔진 → 웹은 바뀜(changed)과 사건(event).
// 큰 자료는 신호로 받지 않고 hazop-app://api/…로 읽는다. 브릿지가 없으면(브라우저·시험) 아무 일도 하지 않는 대역을 둔다.
const pending = new Map();
const listeners = new Map();
const changedListeners = new Set();
let seq = 0;

if (!window.hazopBridge) window.hazopBridge = { send() {}, setHandler() {} };

function handle(text) {
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
    changedListeners.forEach((fn) => fn(msg.topic, msg.rev));
  }
}

export function connect() { window.hazopBridge.setHandler(handle); }
export function deliver(text) { handle(text); }   // 시험이 엔진 대신 메시지를 넣는다

function send(obj) { window.hazopBridge.send(JSON.stringify(obj)); }

/** 명령 하나를 보내고 답을 기다린다(120초). 실패하면 {code, message}를 가진 오류로 거절한다. */
export function cmd(name, args = {}) {
  return new Promise((resolve, reject) => {
    const id = "c" + (++seq);
    const timer = setTimeout(() => { pending.delete(id); reject(Object.assign(new Error("엔진이 응답하지 않습니다."), { code: "timeout" })); }, 120000);
    pending.set(id, { resolve, reject, timer });
    send({ t: "cmd", id, name, args });
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

/** hazop-app://api/<경로>를 읽어 JSON으로 돌려준다. */
export async function read(path) {
  const r = await fetch("/api/" + path);
  if (!r.ok) throw Object.assign(new Error("읽지 못했습니다: " + path), { code: "http_" + r.status });
  return r.json();
}
