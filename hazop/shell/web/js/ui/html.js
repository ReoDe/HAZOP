// Preact + htm. 템플릿은 `html`…``, 구성요소는 <${Comp} prop=${값} />. 글자는 모두 이스케이프되며 innerHTML은 쓰지 않는다(규격 §5.5).
import { h, render, Fragment } from "../../vendor/preact.module.js";
import htm from "../../vendor/htm.module.js";

export const html = htm.bind(h);
export { h, render, Fragment };
