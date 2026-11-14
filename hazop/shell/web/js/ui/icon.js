// 아이콘(Tabler outline, 선 두께 1.75). 엔진이 준 도형 목록(hazop-app://shell/api/icons)으로 SVG 요소를 만든다. HTML 문자열을 넣지 않는다.
import { h } from "./html.js";
import { store } from "../store.js";

let shapes = {};

export async function loadIcons() {
  try {
    const r = await fetch("/api/icons");
    shapes = (await r.json()).names || {};
  } catch (e) {
    shapes = {};
  }
  store.set({ iconsReady: true });
}

export function Icon({ name, size = 18, cls = "" }) {
  const kids = shapes[name] || [];
  return h("svg", {
    class: "ic " + cls, width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": 1.75, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
  }, kids.map(([tag, attrs]) => h(tag, attrs)));
}
