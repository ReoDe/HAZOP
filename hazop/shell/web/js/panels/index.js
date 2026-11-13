// 왼쪽 메뉴의 영역(패널) 목록. main.js는 이 배열만 읽어 메뉴 단추·단축키·패널 그리기를 만든다.
// 새 영역은 자기 파일(panels/<이름>.js, 선택으로 <이름>.css)을 만든 뒤 아래 배열에 항목 하나를 더한다(규약은 hazop/shell/README.md).
//   name: store.panel에 들어가는 이름 · icon: 메뉴 아이콘 · label: 단추 이름(key가 있으면 " (Ctrl+key)"가 붙는다)
//   key: Ctrl+<key>로 열고 닫음(선택) · component: 패널 컴포넌트({ onClose, onOpen }를 받는다) · css: 전용 CSS(이 폴더 안, 선택)
//   badge: (공용 store 상태) => 숫자|null(선택) · place: "bottom"이면 메뉴 아래쪽(선택)
import { DrawingsPanel } from "./drawings.js";
import { NodesPanel } from "./nodes.js";
import { ResultsPanel } from "./results.js";
import { IePanel } from "./ie.js";
import { SettingsPanel } from "./settings.js";

export const PANELS = [
  { name: "drawings", icon: "files", label: "도면", key: "1", component: DrawingsPanel, css: "drawings.css",
    badge: (s) => s.drawings.drawings.reduce((n, d) => n + (d.unknowns || 0), 0) || null },
  { name: "nodes", icon: "vector-triangle", label: "구간", key: "2", component: NodesPanel },
  { name: "results", icon: "table", label: "분석 결과", key: "3", component: ResultsPanel, css: "results.css" },
  { name: "ie", icon: "route", label: "초기사건", key: "4", component: IePanel, css: "ie.css" },
  { name: "settings", icon: "settings", label: "설정", component: SettingsPanel, place: "bottom" },
];

/** 단추 이름: 단축키가 있으면 뒤에 붙인다. */
export function panelLabel(p) { return p.key ? p.label + " (Ctrl+" + p.key + ")" : p.label; }

/** 전용 CSS를 한 번만 붙인다(패널이 처음 열릴 때까지 기다리지 않고 불러 둔다). 패널이 스스로 붙이는 경우(nodes·kg)는 css를 적지 않는다. */
export function loadPanelCss() {
  if (typeof document === "undefined") return;
  for (const p of PANELS) {
    if (!p.css || document.querySelector('link[data-panel-css="' + p.name + '"]')) continue;
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.href = new URL(p.css, import.meta.url).href; l.setAttribute("data-panel-css", p.name);
    document.head.appendChild(l);
  }
}
