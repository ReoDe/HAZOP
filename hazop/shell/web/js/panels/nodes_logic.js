// 구간 패널·고르기 막대의 순수 계산(DOM·저장소 없음). 시험은 web/test/nodes.test.js.
import { segColor } from "../canvas/marks.js";

export const STATE_LABEL = { applied: "적용됨", confirmed: "확정", locked: "잠금" };

/** 구간 행의 상태 칩: AI가 만들고 사람이 손대지 않은 적용됨 구간은 'AI 적용됨'. */
export function stateChip(n) {
  if (n.state === "locked") return { label: "잠금", kind: "ok", icon: "lock" };
  if (n.state === "confirmed") return { label: "확정", kind: "ok", icon: "check" };
  if (n.origin === "ai") return { label: "AI 적용됨", kind: "ai", icon: "sparkles" };
  return { label: "적용됨", kind: "accent", icon: null };
}

export const canEdit = (n) => !!n && n.state === "applied";

/** 구간 번호별 색(목록에서의 자리 기준). 목록과 도면이 같은 색을 쓴다. */
export function colorOf(list, nodeId) {
  const i = list.findIndex((n) => n.node_id === nodeId);
  return segColor(i < 0 ? 0 : i);
}

/** 도면에 칠할 구간 목록. focus 구간이 있으면 그것만 active. */
export function sheetSegments(sheetView, list, focus) {
  if (!sheetView) return [];
  return sheetView.segments.map((s) => ({ node_id: s.node_id, ids: s.ids, color: colorOf(list, s.node_id), active: s.node_id === focus }));
}

/** 도면 범위 글: 도면 번호와 그 도면의 구성요소 수. drawings는 도면 목록(graph_id, drawing_number, name). */
export function rangeText(n, drawings) {
  const name = (g) => { const d = drawings.find((x) => x.graph_id === g); return (d && (d.drawing_number || d.name)) || g.replace(/^graph-/, ""); };
  const sh = n.sheets || [];
  if (!sh.length) return "도면 없음";
  if (sh.length === 1) return name(sh[0].graph_id);
  return name(sh[0].graph_id) + " 외 " + (sh.length - 1) + "장";
}

/** 명령에 붙일 대상의 판: 화면이 본 구간의 rev·state. */
export function targetsOf(list, ids) {
  const out = [];
  for (const id of ids) {
    const n = list.find((x) => x.node_id === id);
    if (n) out.push({ node_id: n.node_id, rev: n.rev, state: n.state });
  }
  return out;
}

/** 오류 답을 화면 글로. stale이면 다시 읽었다는 안내를 붙인다(엔진 문장을 그대로 보임). */
export function errorText(e) {
  if (!e) return "";
  return (e.message || "처리하지 못했습니다.") + "";
}

/** Esc: 새 구간 카드 → 구간 강조 → (고르기 모드에서 고른 것이 없으면) 이동 모드. 고른 것 비우기는 도면 부품이 한다. */
export function escStep({ card, focus, mode, selection }) {
  if (card) return "card";
  if (focus) return "focus";
  if (mode === "pick" && selection.length === 0) return "pan";
  return null;
}

/** 한 글자 키: 입력 중이 아닐 때만. 결과는 동작 이름 또는 null. */
export function keyAction(e, { selection, typing, panelWide }) {
  if (typing || panelWide || e.ctrlKey || e.metaKey || e.altKey) return null;
  const k = (e.key || "").toLowerCase();
  if (k === "v") return "pan";
  if (k === "s") return "pick";
  if (k === "f" && selection.length) return "fit";
  if (e.key === "Enter" && selection.length) return "card";
  return null;
}

/** 구간 이름 제안 글이 없을 때의 빈 카드 초안. */
export const blankCard = (extra) => Object.assign({ open: true, name: "", intent: "", suggest: null, busy: false, error: null }, extra || {});
