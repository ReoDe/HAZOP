// 프로젝트가 바뀌면 영역별 화면 상태(구간·분석 결과·초기사건)를 모두 비우고 새 프로젝트의 것을 다시 읽는다. 앞 프로젝트의 목록·판 표시가 남아 있으면 그것으로
// 보낸 명령이 다른 프로젝트에 닿을 수 있다(엔진도 프로젝트 ID로 막지만, 화면이 낡은 자료를 보이는 일 자체를 없앤다).
import * as N from "./panels/nodes_state.js";
import * as R from "./panels/results_state.js";
import * as I from "./panels/ie_state.js";

const EMPTY_NODES = { available: false, set_rev: 0, nodes: [], batches: [], outside: { count: 0, total: 0 }, stale: false, read_only: null, pending_ai: 0 };

export function resetAreas() {
  N.nodes.set({ list: EMPTY_NODES, sheetView: null, detail: null, focus: null, selection: [], card: null, checked: [], busy: false, error: null, needArchive: null });
  R.reset();
  I.reset();
  N.refresh();
  R.refresh();
  I.refresh();
}
