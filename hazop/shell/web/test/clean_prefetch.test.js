// 정리 자료 미리 읽기와 같은 읽기 줄이기(화면 단순화 6): 미리 읽은 뒤 열면 요청 0, 겹친 읽기는 1, 알림 n번에 읽기 묶음 1, 오래된 자료는 보이지 않는다.
import { sharedJson, inflightCount } from "../js/net_share.js";
import { CLEAN_KEEP, cleanFor, invalidateClean, peekClean, prefetchClean } from "../js/canvas/sheet.js";
import { PREFETCH_MAX, planPrefetch } from "../js/clean_prefetch.js";
import { connect, onChanged, read } from "../js/bridge.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
/** 요청 수를 세는 가짜 fetch. 응답은 delay 뒤에 온다. */
function counter(delay = 0, make = (url, n) => ({ url, n })) {
  const calls = [];
  const f = async (url) => {
    calls.push(String(url));
    const n = calls.length;      // 응답 내용은 요청이 나간 차례로 정한다(늦게 와도 같다)
    if (delay) await sleep(delay);
    const data = make(String(url), n);
    return { ok: data !== null, status: data !== null ? 200 : 500, json: async () => data };
  };
  f.calls = calls;
  return f;
}

export const tests = [
  { name: "같은 주소의 읽기가 나가 있으면 새로 보내지 않고 응답을 함께 쓴다(요청 1, 서로 고쳐도 영향 없음), 끝난 뒤에는 새로 읽는다", async run(assert) {
    const f = counter(20);
    const [a, b, c] = await Promise.all([sharedJson("/api/x", f), sharedJson("/api/x", f), sharedJson("/api/x", f)]);
    assert.equal(f.calls.length, 1);
    a.data.n = 99;
    assert(b.data.n !== 99 && c.data.n !== 99, "받은 쪽이 고쳐도 다른 쪽에 번지지 않는다");
    assert.equal(inflightCount(), 0);
    await sharedJson("/api/x", f);
    assert.equal(f.calls.length, 2);
  } },
  { name: "bridge.read도 같은 주소의 겹친 읽기는 요청 하나", async run(assert) {
    const real = window.fetch;
    const f = counter(20, () => ({ ok: 1 }));
    window.fetch = f;
    try {
      const rs = await Promise.all([read("nodes/sheet/g1"), read("nodes/sheet/g1"), read("nodes/sheet/g1"), read("nodes/sheet/g2")]);
      assert.equal(f.calls.length, 2);
      assert.equal(rs.length, 4);
    } finally { window.fetch = real; }
  } },
  { name: "정리 자료: 미리 읽어 둔 뒤 여는 것은 요청 0, 겹쳐 여는 것은 요청 1", async run(assert) {
    invalidateClean();
    const f = counter(10);
    await prefetchClean(["g1", "g2"], "r1", f);
    assert.equal(f.calls.length, 2);
    assert(peekClean("g1", "r1") && peekClean("g2", "r1"), "쌓였다");
    await cleanFor("g1", "r1", f); await cleanFor("g2", "r1", f);
    assert.equal(f.calls.length, 2, "여는 순간 요청 없음");
    invalidateClean();
    const g = counter(30);
    await Promise.all([cleanFor("g3", "r1", g), cleanFor("g3", "r1", g), cleanFor("g3", "r1", g)]);
    assert.equal(g.calls.length, 1);
  } },
  { name: "정리 자료: 판(rev)이 바뀌면 새로 읽고, 고침 알림이 오면 그 도면만 버려 새 자료를 보인다", async run(assert) {
    invalidateClean();
    const f = counter(0, (url, n) => ({ v: n }));
    const first = await cleanFor("g1", "r1", f);
    await cleanFor("g2", "r1", f);
    assert.equal(first.v, 1);
    const next = await cleanFor("g1", "r2", f);
    assert(next.v > 1 && f.calls.length === 3, "판이 달라지면 다시 읽는다");
    invalidateClean("g2");
    assert.equal(peekClean("g2", "r1"), null);
    const again = await cleanFor("g2", "r1", f);
    assert(again.v === 4 && f.calls.length === 4, "고친 도면은 새 자료");
    assert(peekClean("g1", "r2"), "다른 도면은 그대로");
  } },
  { name: "정리 자료: 읽는 중에 버려지면 그 뒤 여는 쪽은 새로 읽는다(옛 읽기의 답이 새 자리를 채우지 않는다)", async run(assert) {
    invalidateClean();
    const f = counter(30, (url, n) => ({ v: n }));
    const old = cleanFor("g1", "r1", f);
    invalidateClean("g1");
    const fresh = await cleanFor("g1", "r1", f);
    await old;
    assert.equal(f.calls.length, 2);
    assert.equal(fresh.v, 2);
    assert.equal(peekClean("g1", "r1").v, 2, "쌓인 것은 새 자료");
  } },
  { name: "정리 자료: 못 읽은 것(null)은 쌓지 않아 다음에 다시 읽는다", async run(assert) {
    invalidateClean();
    const f = counter(0, () => null);
    assert.equal(await cleanFor("g1", "r1", f), null);
    await cleanFor("g1", "r1", f);
    assert.equal(f.calls.length, 2);
  } },
  { name: "정리 자료: 메모리 한도를 넘으면 가장 오래 안 쓴 것부터 버린다", async run(assert) {
    invalidateClean();
    const f = counter();
    for (let i = 0; i < CLEAN_KEEP; i++) await cleanFor("g" + i, "r1", f);
    await cleanFor("g0", "r1", f);               // g0를 다시 써서 가장 새 것으로
    await cleanFor("extra", "r1", f);            // 한도 초과: g1이 가장 오래됨
    assert(peekClean("g0", "r1") && peekClean("extra", "r1"), "새 것과 다시 쓴 것은 남는다");
    assert.equal(peekClean("g1", "r1"), null);
  } },
  { name: "미리 읽기 계획: 열린 도면 먼저, 목록 앞쪽에서 한도까지", run(assert) {
    const drawings = Array.from({ length: 20 }, (_, i) => ({ graph_id: "g" + i }));
    const p = planPrefetch({ sheet: "g9", drawings: { drawings, rev: "r" } });
    assert.equal(p.gids.length, PREFETCH_MAX);
    assert.equal(p.gids[0], "g9");
    assert.equal(p.gids.slice(1), ["g0", "g1", "g2", "g3", "g4"]);
    assert.equal(p.rev, "r");
    assert.equal(planPrefetch({ sheet: null, drawings: { drawings: [], rev: null } }).gids, []);
  } },
  { name: "엔진의 바뀜 알림 n번은 마지막 알림 뒤 한 번으로 모아 알린다(같은 알림은 하나, 다른 것은 각각 한 번)", async run(assert) {
    let handler = null;
    window.hazopBridge.setHandler = (fn) => { handler = fn; };
    connect();
    const seen = [];
    const off = onChanged((t, rev) => seen.push(t + ":" + (rev == null ? "" : rev)));
    for (let i = 0; i < 12; i++) handler(JSON.stringify({ t: "changed", topic: "drawings", rev: "x" + i }));
    for (let i = 0; i < 12; i++) handler(JSON.stringify({ t: "changed", topic: "nodes", rev: null }));
    for (let i = 0; i < 5; i++) handler(JSON.stringify({ t: "changed", topic: "drawings", rev: null }));
    assert.equal(seen.length, 0, "바로 알리지 않는다");
    await sleep(400);
    off();
    assert.equal(seen.filter((s) => s === "nodes:").length, 1, "nodes 알림 12번 → 한 번");
    assert.equal(seen.filter((s) => s === "drawings:").length, 1, "같은 알림 5번 → 한 번");
    assert.equal(seen.length, 14, "도면 알림은 rev가 다른 12개와 rev 없는 1개, nodes 1개");
  } },
  { name: "바뀜 알림이 오면 그 앞에 나간 읽기는 잊는다: 알림 뒤의 읽기가 옛 응답에 얹히지 않는다", async run(assert) {
    let handler = null;
    window.hazopBridge.setHandler = (fn) => { handler = fn; };
    connect();
    const real = window.fetch;
    const f = counter(60, (url, n) => ({ n }));
    window.fetch = f;
    try {
      const before = read("nodes");                                   // 알림 전에 나간 읽기
      handler(JSON.stringify({ t: "changed", topic: "nodes", rev: null }));
      const after = read("nodes");                                    // 알림 뒤의 읽기: 새로 나간다
      const [a, b] = await Promise.all([before, after]);
      assert.equal(f.calls.length, 2);
      assert(a.n !== b.n, "서로 다른 응답");
    } finally { window.fetch = real; }
    await sleep(250);
  } },
  { name: "알림이 끊이지 않아도 최대 기다림 안에 한 번은 알린다", async run(assert) {
    let handler = null;
    window.hazopBridge.setHandler = (fn) => { handler = fn; };
    connect();
    let n = 0;
    const off = onChanged(() => { n++; });
    const end = Date.now() + 1300;
    while (Date.now() < end) { handler(JSON.stringify({ t: "changed", topic: "sources", rev: Date.now() })); await sleep(40); }
    off();
    assert(n > 0, "끊이지 않는 알림에도 한 번은 알렸다");
    await sleep(300);
  } },
];
