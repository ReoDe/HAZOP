// 남은 조건·미확인 곳마다 '그것을 푸는 단추'(규격 HZ-DSN-06 §3.1 기준값 규칙, 단위 U8). 등록 직후의 칩('확정 조건 n개 남음'·'미확인 n곳')이
// 막다른 길이 되지 않게, 까닭마다 지금 할 일로 바로 가는 단추 하나를 준다. 패널 모듈은 누를 때 읽는다(순환 가져오기를 피함).
import { store } from "./store.js";

/** 까닭 코드 → {label, run(gid)} 또는 null(푸는 단추가 없음: 도면 고치기로 직접). */
export function fixFor(reason) {
  if (reason === "registration_unknown" || reason === "missing_drawing_number" || reason === "not_registered") {
    return { label: "표제란 확정", run: async (gid) => { const m = await import("./panels/titleblock.js"); m.focusSheet(gid); } };
  }
  if (reason === "ai_candidate") {
    return { label: "AI 후보 검토하기", run: async (gid) => { const q = await import("./queue/queue.js"); q.openQueue("ai", gid); } };
  }
  if (reason === "unplaced" || reason === "no_position") return null;
  return { label: "도면 고치기", run: async () => { store.set({ panel: null }); const e = await import("./canvas/edit.js"); e.setOn(true); } };
}

/** 미확인 말풍선에 원본 조각이 없을 때의 글(그냥 '없습니다'로 끝내지 않는다). */
export function noFragmentText(reason) {
  if (reason === "registration_unknown") return "표제란에서 온 항목이라 도면 위 자리가 없습니다. 표제란을 확정하면 사라집니다.";
  if (!fixFor(reason)) return "이 도면은 원본 그림 조각이 없어 자리만 보입니다. 위치를 주거나 도면에 없음으로 지워야 합니다.";
  return "이 도면은 원본 그림 조각이 없어 자리만 보입니다. 아래 '" + fixFor(reason).label + "' 단추로 처리하세요.";
}
