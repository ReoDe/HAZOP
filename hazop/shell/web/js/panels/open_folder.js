// 내보낸 글 줄 끝의 '폴더 열기'(명령 export.open_folder): 앱이 실제로 내보낸 자리만 엔진이 탐색기로 연다. 종류는 excel·ie·fmea·dexpi.
import { html } from "../ui/html.js";
import { cmd } from "../bridge.js";
import { store } from "../store.js";
import { Btn } from "../ui/parts.js";

const fail = (e) => store.set({ toast: { text: (e && e.message) || "폴더를 열지 못했습니다.", kind: "err" } });

export function OpenFolder({ kind }) {
  return html`<${Btn} sm=${true} label="내보낸 폴더 열기" onClick=${() => cmd("export.open_folder", { kind }).catch(fail)}>폴더 열기<//>`;
}
