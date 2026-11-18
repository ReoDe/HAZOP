import { createStore } from "../js/store.js";

export const tests = [
  { name: "store: set은 합치고 get은 새 값을 준다", run(assert) {
    const s = createStore({ a: 1, b: 2 });
    s.set({ b: 3 });
    assert.equal(s.get(), { a: 1, b: 3 });
  } },
  { name: "store: 함수 갱신은 이전 값을 받는다", run(assert) {
    const s = createStore({ n: 1 });
    s.set((cur) => ({ n: cur.n + 1 }));
    assert.equal(s.get().n, 2);
  } },
  { name: "store: 구독은 바뀔 때마다 부르고 해제하면 멈춘다", run(assert) {
    const s = createStore({ n: 0 });
    const seen = [];
    const off = s.subscribe((st) => seen.push(st.n));
    s.set({ n: 1 });
    off();
    s.set({ n: 2 });
    assert.equal(seen, [1]);
  } },
  { name: "store: 처음 값 객체를 밖에서 바꿔도 저장소는 그대로", run(assert) {
    const init = { n: 1 };
    const s = createStore(init);
    init.n = 99;
    assert.equal(s.get().n, 1);
  } },
];
