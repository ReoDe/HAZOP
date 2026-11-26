// 웹 단위 시험 모음(규격 §5.6). `run.html`을 오프스크린 웹 엔진에 띄우면 결과가 window.__results에 남는다. Node를 쓰지 않는다.
// 각 시험 파일은 { name, run(assert) } 목록을 내보낸다. 도면 구성요소(canvas/)의 시험도 같은 방식으로 여기에 더한다.
import { tests as storeTests } from "./store.test.js";
import { tests as bridgeTests } from "./bridge.test.js";
import { tests as cardTests } from "./card.test.js";
import { tests as nodesTests } from "./nodes.test.js";
import { tests as cleanTests } from "./clean.test.js";
import { tests as tableTests } from "./table.test.js";
import { tests as editTests } from "./edit.test.js";
import { tests as resultsDetailTests } from "./results_detail.test.js";
import { tests as aiReviewTests } from "./aireview.test.js";
import { tests as cleanDashedTests } from "./clean_dashed.test.js";
import { tests as lostTests } from "./lost.test.js";
import { tests as nextTests } from "./next.test.js";
import { tests as queueTests } from "./queue.test.js";
import { tests as chipTests } from "./chips.test.js";
import { tests as reviewTests } from "./review.test.js";
import { tests as sourcesTests } from "./sources.test.js";
import { tests as sheetconfTests } from "./sheetconf.test.js";
import { tests as drawingsJobsTests } from "./drawings_jobs.test.js";
import { tests as titleblockTests } from "./titleblock.test.js";
import { tests as extractCheckTests } from "./extract_check.test.js";
import { tests as cleanPrefetchTests } from "./clean_prefetch.test.js";

import { tests as lightDismissTests } from "./light_dismiss.test.js";

// 바깥 누르면 닫기 시험은 맨 앞에서 돈다: 뒤의 시험들이 화면에 남긴 것이 다시 그리다 던지면 그 뒤의 화면 갱신이 멈춘다
const all = [...lightDismissTests, ...storeTests, ...bridgeTests, ...cardTests, ...nodesTests, ...tableTests, ...cleanTests, ...editTests, ...resultsDetailTests, ...aiReviewTests, ...cleanDashedTests, ...lostTests, ...nextTests, ...queueTests, ...chipTests, ...reviewTests, ...sourcesTests, ...sheetconfTests, ...drawingsJobsTests, ...titleblockTests, ...extractCheckTests, ...cleanPrefetchTests];
const results = [];

function assert(cond, msg) { if (!cond) throw new Error(msg || "assert 실패"); }
assert.equal = (a, b, msg) => { if (a !== b && JSON.stringify(a) !== JSON.stringify(b)) throw new Error((msg || "같지 않음") + ": " + JSON.stringify(a) + " != " + JSON.stringify(b)); };

for (const t of all) {
  try {
    await t.run(assert);
    results.push({ name: t.name, ok: true });
  } catch (e) {
    results.push({ name: t.name, ok: false, error: String(e && e.message) });
  }
}
window.__results = results;
document.getElementById("out").textContent = results.map((r) => (r.ok ? "통과 " : "실패 ") + r.name + (r.error ? " — " + r.error : "")).join("\n");
