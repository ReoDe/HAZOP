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

const all = [...storeTests, ...bridgeTests, ...cardTests, ...nodesTests, ...tableTests, ...cleanTests, ...editTests, ...resultsDetailTests, ...aiReviewTests, ...cleanDashedTests, ...lostTests, ...nextTests, ...queueTests, ...chipTests, ...reviewTests, ...sourcesTests, ...sheetconfTests, ...drawingsJobsTests];
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
