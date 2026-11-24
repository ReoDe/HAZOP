// 도면 연결 칩 놓기(web/js/canvas/marks.js placeChips): 미연결 칩이 겹치면 한 칩 '미연결 n곳'으로 모으고, 이어진 칩은 겹치지 않게 아래로 내린다.
import { placeChips } from "../js/canvas/marks.js";

const at = (map) => (id) => map[id] || null;
const R = (x, y) => ({ x, y, w: 20, h: 20 });
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export const tests = [
  { name: "도면 칩: 겹치는 미연결 칩 셋은 '미연결 3곳' 하나, 떨어진 것은 따로", async run(assert) {
    const reason = "상대 도면이 프로젝트에 없음(미등록·미추출)";
    const links = ["a", "b", "c", "d"].map((id) => ({ id, status: "unlinked", reason }));
    const out = placeChips(links, at({ a: R(100, 100), b: R(110, 104), c: R(120, 100), d: R(600, 400) }));
    assert.equal(out.map((c) => c.text), ["미연결 3곳", "미연결"]);
    assert(out[0].title.includes(reason) && !out[0].text.includes(reason), "사유는 title에만");
    assert.equal(out[0].link.id, "a", "누르면 첫 곳");
  } },
  { name: "도면 칩: 이어진 칩끼리는 겹치지 않게 아래 줄로", async run(assert) {
    const links = [{ id: "a", status: "linked", label: "SNP-M-102 (RC-L011)" }, { id: "b", status: "linked", label: "SNP-M-103 (RC-L012)" }];
    const out = placeChips(links, at({ a: R(100, 100), b: R(104, 100) }));
    assert.equal(out.length, 2);
    assert(!overlap(out[0], out[1]), JSON.stringify(out.map((c) => [c.x, c.y, c.w])));
  } },
];
