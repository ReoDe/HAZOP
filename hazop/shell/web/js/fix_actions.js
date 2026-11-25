// 남은 조건·미확인 곳마다 '그것을 푸는 단추'(규격 HZ-DSN-06 §3.1 기준값 규칙, 단위 U8). 등록 직후의 칩('확정 조건 n개 남음'·'미확인 n곳')이
// 막다른 길이 되지 않게, 까닭마다 지금 할 일로 바로 가는 단추 하나를 준다. 패널 모듈은 누를 때 읽는다(순환 가져오기를 피함).

/** 까닭 코드 → {label, run(gid)} 또는 null(푸는 단추가 없음: 채팅으로 고친다). */
export function fixFor(reason) {
  if (reason === "registration_unknown" || reason === "missing_drawing_number" || reason === "not_registered") {
    return { label: "표제란 확정", run: async (gid) => { const m = await import("./panels/titleblock.js"); m.focusSheet(gid); } };
  }
  if (reason === "ai_candidate") {
    return { label: "AI 후보 검토하기", run: async (gid) => { const q = await import("./queue/queue.js"); q.openQueue("ai", gid); } };
  }
  return null;      // 그 밖의 까닭은 화면에서 직접 고치지 않는다(화면 단순화: 잘못 읽은 곳은 채팅으로 고친다)
}

/** 미확인 말풍선에 원본 조각이 없을 때의 글(그냥 '없습니다'로 끝내지 않는다). */
export function noFragmentText(reason) {
  if (reason === "registration_unknown") return "표제란에서 온 항목이라 도면 위 자리가 없습니다. 표제란을 확정하면 사라집니다.";
  if (!fixFor(reason)) return "이 도면은 원본 그림 조각이 없어 자리만 보입니다. 잘못 읽었으면 채팅으로 고치도록 요청하세요.";
  return "이 도면은 원본 그림 조각이 없어 자리만 보입니다. 아래 '" + fixFor(reason).label + "' 단추로 처리하세요.";
}
