import { cmd, connect, deliver, on, onChanged, setProject } from "../js/bridge.js";

// 브릿지 대역: 보낸 메시지를 모으고, 시험이 deliver로 답을 넣는다.
const sent = [];
window.hazopBridge = { send(text) { sent.push(JSON.parse(text)); }, setHandler() {} };
connect();

export const tests = [
  { name: "bridge: cmd는 명령을 보내고 reply의 data로 풀린다", async run(assert) {
    const p = cmd("chat.stop", {});
    const m = sent[sent.length - 1];
    assert.equal(m.t, "cmd");
    assert.equal(m.name, "chat.stop");
    deliver(JSON.stringify({ t: "reply", id: m.id, ok: true, data: { x: 1 } }));
    assert.equal(await p, { x: 1 });
  } },
  { name: "bridge: 오류 답은 code와 message를 가진 오류로 거절한다", async run(assert) {
    const p = cmd("chat.ask", { text: "" });
    const m = sent[sent.length - 1];
    deliver(JSON.stringify({ t: "reply", id: m.id, ok: false, error: { code: "bad_args", message: "text: 글자 1~4000자가 와야 함" } }));
    let err = null;
    try { await p; } catch (e) { err = e; }
    assert(err && err.code === "bad_args" && /글자/.test(err.message), "오류 모양");
  } },
  { name: "bridge: 사건과 바뀜 알림을 받는다", run(assert) {
    const seen = [];
    on("chat.notice", (d) => seen.push(d.text));
    const topics = [];
    onChanged((t) => topics.push(t));
    deliver(JSON.stringify({ t: "event", name: "chat.notice", data: { text: "안녕" } }));
    deliver(JSON.stringify({ t: "changed", topic: "drawings", rev: "x" }));
    assert.equal(seen, ["안녕"]);
    assert.equal(topics, ["drawings"]);
  } },
  { name: "bridge: 프로젝트를 정하면 모든 명령에 그 프로젝트 ID를 싣고, 바뀌면 바뀐 ID를 싣는다", run(assert) {
    setProject(null);
    cmd("chat.stop", {});
    assert.equal("project" in sent[sent.length - 1], false);
    setProject("A-프로젝트");
    cmd("results.stop", {});
    assert.equal(sent[sent.length - 1].project, "A-프로젝트");
    assert.equal(sent[sent.length - 1].args, {}, "프로젝트는 인자 밖에 싣는다");
    setProject("B");
    cmd("nodes.confirm", { x: 1 });
    assert.equal(sent[sent.length - 1].project, "B");
    setProject(null);
  } },
  { name: "bridge: 깨진 메시지와 모르는 답은 버린다", run(assert) {
    deliver("{깨짐");
    deliver("5");
    deliver(JSON.stringify({ t: "reply", id: "없는ID", ok: true }));
    assert(true);
  } },
];
