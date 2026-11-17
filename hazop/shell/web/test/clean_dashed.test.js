// 정리된 보기의 점선: 배관 굵기 점선(pdf_dashed, 물리 연결)은 배관 굵기의 점선 획으로, 신호 점선(pdf_dashed, 신호 연결)은 가는 점선 획으로 그린다.
import * as V from "../js/canvas/clean_view.js";

const rec = { id: "r", layer: "pipe", lines: [[[0, 0], [100, 0]]] };
const stroke = (extra) => { const s = V.pipeShapes(rec, extra)[0].a; return { w: +s["stroke-width"], dash: s["stroke-dasharray"] }; };      // 그림 서술자({t, a}): a가 속성

export const tests = [
  { name: "정리된 보기: 점선 배관(pdf_dashed·물리 연결)은 공정 배관 굵기의 점선으로 그린다", run(assert) {
    const pipe = stroke({ line_type: "pdf_dashed", rel_kind: "physical_connection" });
    const process = stroke({ line_type: "process" });
    assert.equal(pipe.w, process.w, "배관과 같은 굵기");
    assert(pipe.dash && pipe.dash !== "none", "점선 획");
    assert(!process.dash, "실선 배관은 점선이 아니다");
  } },
  { name: "정리된 보기: 신호 점선(pdf_dashed·신호 연결)은 배관보다 가는 점선이다", run(assert) {
    const pipe = stroke({ line_type: "pdf_dashed", rel_kind: "physical_connection" });
    const signal = stroke({ line_type: "pdf_dashed", rel_kind: "signal_connection" });
    assert(signal.w < pipe.w, "신호선은 배관보다 가늘다");
    assert(signal.dash && signal.dash !== "none", "점선 획");
  } },
];
