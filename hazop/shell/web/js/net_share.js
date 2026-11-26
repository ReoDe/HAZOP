// 같은 주소의 읽기가 이미 나가 있으면 새로 보내지 않고 그 응답을 함께 쓴다(파이썬이 바쁠 때 같은 읽기가 쌓여 대기열을 늘리지 않게).
// 끝난 읽기는 기억하지 않는다: 이 모듈은 '지금 나가 있는 것'만 나눠 쓴다(자료를 오래 들고 있는 일은 호출하는 쪽 캐시의 몫).
const inflight = new Map();      // 주소 → {promise, count}

/** 주소의 JSON을 읽는다 -> {ok, status, data}. 첫 호출자는 읽은 객체를, 같이 쓰는 뒤 호출자는 그 복사본을 받는다(서로 고쳐도 영향이 없다). */
export function sharedJson(url, fetchImpl = fetch) {
  let e = inflight.get(url);
  if (!e) {
    const promise = (async () => {
      const res = await fetchImpl(url);
      return { ok: !!res.ok, status: res.status, data: res.ok ? await res.json() : null };
    })();
    e = { promise, count: 0 };
    inflight.set(url, e);
    const done = () => { if (inflight.get(url) === e) inflight.delete(url); };
    promise.then(done, done);
  }
  const first = e.count++ === 0;
  return e.promise.then((r) => (first || !r.ok ? r : { ok: r.ok, status: r.status, data: structuredClone(r.data) }));
}

/** 주소의 나가 있는 읽기를 잊는다(자료가 바뀌었으니 다음 호출은 새로 읽는다). 이미 나간 읽기는 받은 쪽에 그대로 돌아간다. */
export function forget(url) { inflight.delete(url); }
/** 나가 있는 읽기를 모두 잊는다: 엔진이 '바뀜'을 알렸다면 그 앞에 나간 읽기는 옛 자료일 수 있어, 알림 뒤의 읽기가 그 응답에 얹히지 않게 한다. */
export function forgetAll() { inflight.clear(); }
export const inflightCount = () => inflight.size;
