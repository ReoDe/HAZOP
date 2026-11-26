// <Sheet> 구성요소(Preact). 도면 한 장을 그리고 입력을 받는다. 입력(props)과 이벤트(콜백 props)는 ./README.md가 정한다.
// 몸통은 core.js(SheetCore)이고, 여기서는 마운트·도면 자료 읽기·props 전달만 한다. 상태 저장소는 직접 읽지 않는다(틀이 props로 내려보낸다).
//
// 도면 자료는 /api/sheet/<graph_id> (JSON, 같은 출처). 판(rev)이 바뀌면 다시 읽는다.

import { h } from "../../vendor/preact.module.js";
import { useEffect, useRef } from "../../vendor/hooks.module.js";
import { SheetCore } from "./core.js";
import { forget, sharedJson } from "../net_share.js";

export const SHEET_API = "/api/sheet/"; // 같은 출처 상대 경로(다른 호스트면 CORS로 막힌다)
export const CLEAN_API = "/api/clean/";   // 정리된 보기용 추가 자료(방향·선 종류·열린 끝·미확인)
const SYMBOLS_URL = new URL("symbols.json", import.meta.url).href;
let symbolsPromise = null;

/** 기호 도형 자료(저장소의 symbols.json)를 한 번만 읽는다. */
export function loadSymbols(fetchImpl = fetch) {
  if (!symbolsPromise) symbolsPromise = fetchImpl(SYMBOLS_URL).then((r) => { if (!r.ok) throw new Error("기호 자료를 읽지 못함"); return r.json(); }).then((d) => d.symbols).catch(() => { symbolsPromise = null; return null; });
  return symbolsPromise;
}

/** 정리된 보기용 자료. 없거나 못 읽으면 null(원본 보기만 된다). 같은 도면의 읽기가 나가 있으면 그 응답을 함께 쓴다. */
export async function fetchClean(graphId, fetchImpl = fetch) {
  try {
    const r = await sharedJson(CLEAN_API + encodeURIComponent(graphId), fetchImpl);
    return r.ok ? r.data : null;
  } catch (e) {
    return null;
  }
}

// 정리 자료 쌓아 두기: 도면 하나에 한 벌(graph_id → {rev, promise, data}). 도면 목록의 판(rev)이 달라지면 버리고, 고침·다시 추출 알림이 오면 그 도면 것을 버린다.
// 메모리 한도는 CLEAN_KEEP벌(가장 오래 안 쓴 것부터 버린다). 못 읽은 것(null)은 쌓지 않는다: 다음에 다시 읽는다.
export const CLEAN_KEEP = 10;
const cleanCache = new Map();

/** 이 판(rev)의 정리 자료를 약속으로 돌려준다. 쌓아 둔 것이 있으면 요청 없이, 읽는 중이면 그 읽기를 함께 쓴다. */
export function cleanFor(gid, rev, fetchImpl = fetch) {
  const hit = cleanCache.get(gid);
  if (hit && hit.rev === rev) { cleanCache.delete(gid); cleanCache.set(gid, hit); return hit.promise; }
  const entry = { rev, data: undefined, promise: null };
  entry.promise = fetchClean(gid, fetchImpl).then((d) => {
    if (cleanCache.get(gid) === entry) { if (d) entry.data = d; else cleanCache.delete(gid); }
    return d;
  });
  cleanCache.set(gid, entry);
  while (cleanCache.size > CLEAN_KEEP) cleanCache.delete(cleanCache.keys().next().value);
  return entry.promise;
}

/** 이미 읽어 둔 자료(없으면 null). 요청을 보내지 않는다. */
export function peekClean(gid, rev) {
  const hit = cleanCache.get(gid);
  return hit && hit.rev === rev && hit.data ? hit.data : null;
}

/** 그 도면의 쌓은 자료와 나가 있는 읽기를 버린다(gid 없이 부르면 전부). 자료가 바뀌었을 때 오래된 것을 보이지 않으려는 것이다. */
export function invalidateClean(gid) {
  if (gid == null) { for (const k of cleanCache.keys()) forget(CLEAN_API + encodeURIComponent(k)); cleanCache.clear(); return; }
  cleanCache.delete(gid);
  forget(CLEAN_API + encodeURIComponent(gid));
}

/** 미리 읽기: 아직 없는 도면의 정리 자료를 차례로(한 번에 하나씩) 읽어 둔다. 도면을 여는 순간 이미 있게 하려는 것이다. */
export async function prefetchClean(gids, rev, fetchImpl = fetch) {
  for (const gid of gids) if (!peekClean(gid, rev)) await cleanFor(gid, rev, fetchImpl);
}

/** 도면 자료를 읽는다. 시험에서 바꿀 수 있게 따로 둔다. */
export async function fetchSheet(graphId, rev, fetchImpl = fetch) {
  const url = SHEET_API + encodeURIComponent(graphId) + (rev != null ? "?rev=" + encodeURIComponent(rev) : "");
  const res = await sharedJson(url, fetchImpl);
  if (!res.ok) throw new Error("도면 자료를 읽지 못함: " + res.status);
  return res.data;
}

/**
 * @param {object} props README의 `<Sheet>` 입력과 이벤트. 추가: `fetchImpl`(시험용), `class`.
 */
export function Sheet(props) {
  const host = useRef(null), core = useRef(null), latest = useRef(props);
  latest.current = props;

  // 콜백은 늘 최신 props의 것을 부른다(마운트는 한 번이라 옛 props를 붙들지 않게)
  const callbacks = () => {
    const call = (name) => (...a) => { const f = latest.current[name]; return f ? f(...a) : undefined; };
    return ["onReady", "onItemClick", "onItemDblClick", "onHover", "onSelection", "onViewport", "onMarkResult", "onEsc", "onLinkClick", "onClearMarks", "onSegmentClick", "onPlainClick", "onCleanBuilt", "onEditPick"]
      .reduce((o, n) => { o[n] = call(n); return o; }, {});
  };

  useEffect(() => {
    core.current = new SheetCore(host.current, callbacks());
    return () => { core.current.destroy(); core.current = null; };
  }, []);

  const gid = props.sheet && props.sheet.graph_id, rev = props.sheet && props.sheet.rev;
  const extra = useRef({ clean: undefined, symbols: undefined });
  useEffect(() => {
    if (!gid) return undefined;
    let alive = true;
    const dataRev = latest.current.dataRev;
    const cached = peekClean(gid, dataRev);
    extra.current = { clean: cached, symbols: extra.current.symbols };
    fetchSheet(gid, rev, props.fetchImpl || fetch)
      .then((data) => { if (alive && core.current) { core.current.setData(data); core.current.update(Object.assign({}, latest.current, extra.current)); } })
      .catch((err) => { if (alive && latest.current.onError) latest.current.onError(err); });
    // 정리된 보기 자료는 도면이 뜬 뒤에 따로 읽는다(원본 그리기를 늦추지 않는다)
    Promise.all([cached ? Promise.resolve(cached) : cleanFor(gid, dataRev, props.fetchImpl || fetch), loadSymbols(props.fetchImpl || fetch)]).then(([clean, symbols]) => {
      if (!alive || !core.current) return;
      extra.current = { clean, symbols };
      if (latest.current.onClean) latest.current.onClean(gid, clean);
      core.current.update(Object.assign({}, latest.current, extra.current));
    });
    return () => { alive = false; };
  }, [gid, rev]);

  useEffect(() => { if (core.current) core.current.update(Object.assign({}, props, extra.current)); });

  return h("div", { class: "hz-sheet" + (props.class ? " " + props.class : ""), ref: host, style: "width:100%;height:100%" });
}
