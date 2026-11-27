// 바깥을 누르면 닫기(light dismiss): 도면 위에 뜨는 말풍선·작은 메뉴·팝오버가 모두 같은 규칙을 쓴다.
// - 떠 있는 것 바깥의 아무 곳을 한 번 누르면 닫힌다(pointerdown·pointerup이 같은 자리). 끌기(도면 옮기기·네모)는 닫기로 치지 않는다.
// - 누름은 아래 요소에도 그대로 전해진다(모달이 아니다): 다른 구성요소를 누르면 그 구성요소의 말풍선으로 바뀐다.
// - 닫힐 때 초점이 갈 곳을 잃었으면(본문이나 닫힌 것 안) 연 자리로 돌린다. 다른 입력 칸을 눌러 닫았으면 그 칸에 둔다.
import { useEffect, useRef } from "../../vendor/hooks.module.js";

const SLOP = 4;      // 누른 채 이만큼 넘게 움직이면 끌기다

/** open이 참인 동안 바깥 누름(과 esc가 참이면 Esc)으로 close를 부른다. inside()는 떠 있는 것과 그것을 여닫는 단추 요소들의 목록. */
export function useLightDismiss(open, inside, close, { esc = false } = {}) {
  const latest = useRef({});
  latest.current = { inside, close };
  useEffect(() => {
    if (!open) return undefined;
    const doc = document, opener = doc.activeElement;
    let down = null;
    const isInside = (t) => latest.current.inside().some((el) => el && t && el.contains(t));
    const finish = () => {
      const els = latest.current.inside();
      latest.current.close();
      setTimeout(() => {
        const a = doc.activeElement;
        const lost = !a || a === doc.body || els.some((el) => el && el.contains(a));
        if (lost && opener && opener.isConnected && opener.focus) opener.focus({ preventScroll: true });
      }, 0);
    };
    const onDown = (e) => { down = e.button === 0 && !isInside(e.target) ? { x: e.clientX, y: e.clientY } : null; };
    const onUp = (e) => {
      const d = down;
      down = null;
      if (d && Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) <= SLOP) finish();
    };
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); finish(); } };
    doc.addEventListener("pointerdown", onDown, true);
    doc.addEventListener("pointerup", onUp, true);
    if (esc) window.addEventListener("keydown", onKey, true);
    return () => {
      doc.removeEventListener("pointerdown", onDown, true);
      doc.removeEventListener("pointerup", onUp, true);
      if (esc) window.removeEventListener("keydown", onKey, true);
    };
  }, [open]);
}
