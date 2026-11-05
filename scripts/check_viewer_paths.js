// 뷰어 JS 경로 질의와 Python 경로 질의(hazop/graph/query.py)의 결과를 대조한다.
// 실행: node scripts/check_viewer_paths.js   (하위 프로세스를 쓰지 않음)
// - 출력/뷰어/<도면>.html 에서 내장 그래프 JSON과 PATH-ENGINE 블록(hazopPathEngine)을 꺼내 실행
// - 출력/그래프/<도면>/path_expectations.json(Python이 미리 쓴 기대값)과 모든 사례를 비교
// 종료 코드 0 = 불일치 0, 6개 도면 모두 대조됨.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const VIEWER = path.join(ROOT, "출력", "뷰어");
const GRAPH = path.join(ROOT, "출력", "그래프");
const EXPECTED_DRAWINGS = 6;

function extract(html, re, what) {
  const m = html.match(re);
  if (!m) throw new Error(what + " 없음");
  return m[1];
}

let total = 0, mismatches = 0, drawings = 0;
const problems = [];
const pages = fs.readdirSync(VIEWER).filter((f) => f.endsWith(".html") && f !== "index.html").sort();
for (const page of pages) {
  const name = page.slice(0, -5);
  const html = fs.readFileSync(path.join(VIEWER, page), "utf8");
  // 도면 뷰어가 아닌 페이지(예: ③ kg-screen.html)는 건너뛴다. 도면 뷰어 표지(PATH-ENGINE 블록)가 있는데
  // 내장 그래프가 없으면 아래 extract가 그대로 오류를 낸다.
  if (!html.includes("PATH-ENGINE-BEGIN") && !/<script type="application\/json" id="graph">/.test(html)) continue;
  const graphJson = extract(html, /<script type="application\/json" id="graph">([\s\S]*?)<\/script>/, "내장 그래프");
  const G = JSON.parse(graphJson);
  if (!G) { problems.push(name + ": 내장 그래프가 null"); continue; }
  const engineSrc = extract(html, /\/\* PATH-ENGINE-BEGIN[\s\S]*?\*\/([\s\S]*?)\/\* PATH-ENGINE-END \*\//, "PATH-ENGINE 블록");
  const makeEngine = vm.runInNewContext(engineSrc + "\n;hazopPathEngine", {});
  const engine = makeEngine(G);
  const expPath = path.join(GRAPH, name, "path_expectations.json");
  if (!fs.existsSync(expPath)) { problems.push(name + ": 기대값 파일 없음 " + expPath); continue; }
  const exp = JSON.parse(fs.readFileSync(expPath, "utf8"));
  // 오래된 결과 판정: graph_version(입력 해시)이 뷰어 내장 그래프·graph.json·기대값에서 모두 같아야 한다.
  const graphFile = path.join(GRAPH, name, "graph.json");
  const fileVersion = fs.existsSync(graphFile) ? JSON.parse(fs.readFileSync(graphFile, "utf8")).graph_version : null;
  if (!G.graph_version || exp.graph_version !== G.graph_version || fileVersion !== G.graph_version) {
    problems.push(`${name}: graph_version 불일치(뷰어 ${G.graph_version}, graph.json ${fileVersion}, 기대값 ${exp.graph_version}) — 그래프·뷰어를 다시 빌드할 것`);
    continue;
  }
  let n = 0, bad = 0;
  for (const [key, want] of Object.entries(exp.cases)) {
    const [a, b, mode] = key.split("|");
    const got = engine.signature(a, b, mode);
    n++;
    if (JSON.stringify(got) !== JSON.stringify(want)) {
      bad++;
      if (bad <= 5) problems.push(name + ": " + key + "\n    JS " + JSON.stringify(got) + "\n    PY " + JSON.stringify(want));
    }
  }
  if (!exp.segment_pairs_sampled) problems.push(name + ": 배관 구간 끝점 사례가 기대값에 없음");
  console.log(`${name}: 사례 ${n}건(구간 끝점 쌍 ${exp.segment_pairs_sampled}개 포함), 불일치 ${bad}건, graph_version ${G.graph_version}`);
  total += n; mismatches += bad; drawings++;
}
if (drawings < EXPECTED_DRAWINGS) problems.push(`대조한 도면 ${drawings}개 < ${EXPECTED_DRAWINGS}`);
console.log(`== 합계: 도면 ${drawings}개, 사례 ${total}건, 불일치 ${mismatches}건`);
for (const p of problems) console.log("  - " + p);
const ok = mismatches === 0 && problems.length === 0;
console.log("== 결과:", ok ? "통과" : "실패");
process.exit(ok ? 0 : 1);
