// <Sheet> 구성요소(Preact). 도면 한 장을 그리고 입력을 받는다. 입력(props)과 이벤트(콜백 props)는 ./README.md가 정한다.
// 몸통은 core.js(SheetCore)이고, 여기서는 마운트·도면 자료 읽기·props 전달만 한다. 상태 저장소는 직접 읽지 않는다(틀이 props로 내려보낸다).
//
// 도면 자료는 hazop-app://api/sheet/<graph_id> (JSON). 판(rev)이 바뀌면 다시 읽는다.

import { h } from "../../vendor/preact.module.js";
import { useEffect, useRef } from "../../vendor/hooks.module.js";
import { SheetCore } from "./core.js";

export const SHEET_API = "hazop-app://api/sheet/";

/** 도면 자료를 읽는다. 시험에서 바꿀 수 있게 따로 둔다. */
export async function fetchSheet(graphId, rev, fetchImpl = fetch) {
  const url = SHEET_API + encodeURIComponent(graphId) + (rev != null ? "?rev=" + encodeURIComponent(rev) : "");
  const res = await fetchImpl(url);
  if (!res.ok) throw new Error("도면 자료를 읽지 못함: " + res.status);
  return res.json();
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
    return ["onReady", "onItemClick", "onItemDblClick", "onHover", "onSelection", "onViewport", "onMarkResult", "onEsc", "onLinkClick", "onClearMarks"]
      .reduce((o, n) => { o[n] = call(n); return o; }, {});
  };

  useEffect(() => {
    core.current = new SheetCore(host.current, callbacks());
    return () => { core.current.destroy(); core.current = null; };
  }, []);

  const gid = props.sheet && props.sheet.graph_id, rev = props.sheet && props.sheet.rev;
  useEffect(() => {
    if (!gid) return undefined;
    let alive = true;
    fetchSheet(gid, rev, props.fetchImpl || fetch)
      .then((data) => { if (alive && core.current) { core.current.setData(data); core.current.update(latest.current); } })
      .catch((err) => { if (alive && latest.current.onError) latest.current.onError(err); });
    return () => { alive = false; };
  }, [gid, rev]);

  useEffect(() => { if (core.current) core.current.update(props); });

  return h("div", { class: "hz-sheet" + (props.class ? " " + props.class : ""), ref: host, style: "width:100%;height:100%" });
}
