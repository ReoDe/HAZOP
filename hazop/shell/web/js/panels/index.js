// 왼쪽 메뉴의 영역(패널) 목록. main.js는 이 배열만 읽어 메뉴 단추·단축키·패널 그리기를 만든다.
// 새 영역은 자기 파일(panels/<이름>.js, 선택으로 <이름>.css)을 만든 뒤 아래 배열에 항목 하나를 더한다(규약은 hazop/shell/README.md).
//   name: store.panel에 들어가는 이름 · icon: 메뉴 아이콘 · label: 단추 이름(key가 있으면 " (Ctrl+key)"가 붙는다)
//   key: Ctrl+<key>로 열고 닫음(선택) · component: 패널 컴포넌트({ onClose, onOpen }를 받는다) · css: 전용 CSS(이 폴더 안, 선택)
//   badge: (공용 store 상태) => 숫자|null(선택) · place: "bottom"이면 메뉴 아래쪽(선택)
//   group: 다른 항목의 name. 이 항목은 메뉴에 따로 나오지 않고 그 항목의 화면 위쪽 탭으로 열린다(관련 화면을 한 메뉴로 묶는다)
//   hidden: true면 메뉴 단추 없이 store.panel로만 연다(예: 채팅 머리의 단추) · hint·dot: 메뉴 단추의 보조 글·점(공용 store 상태 => 글|톤)
import { DrawingsPanel } from "./drawings.js";
import { NodesPanel } from "./nodes.js";
import { ResultsPanel } from "./results.js";
import { IePanel } from "./ie.js";
import { KgPanel } from "./kg.js";
import { DocsPanel } from "./docs.js";
import { TitleblockPanel } from "./titleblock.js";
import { AiReviewPanel } from "./aireview.js";
import { ActionLogPanel } from "./actionlog.js";
import { SettingsPanel } from "./settings.js";

export const PANELS = [
  { name: "drawings", icon: "files", label: "도면", key: "1", component: DrawingsPanel, css: "drawings.css",
    badge: (s) => s.drawings.drawings.reduce((n, d) => n + (d.unknowns || 0), 0) || null },
  { name: "nodes", icon: "vector-triangle", label: "구간", key: "2", component: NodesPanel },
  { name: "results", icon: "table", label: "분석 결과", key: "3", component: ResultsPanel, css: "results.css" },
  { name: "ie", icon: "route", label: "초기사건", key: "4", component: IePanel, css: "ie.css" },
  { name: "kg", icon: "topology-star-3", label: "지식그래프", key: "5", component: KgPanel },
  { name: "docs", group: "kg", label: "설계 문서", key: "6", component: DocsPanel },
  { name: "titleblock", group: "drawings", label: "표제란", component: TitleblockPanel, css: "titleblock.css" },
  { name: "aireview", group: "drawings", label: "AI 검토", key: "7", component: AiReviewPanel, css: "aireview.css" },
  { name: "actionlog", hidden: true, label: "AI 실행 기록", component: ActionLogPanel, css: "actionlog.css" },
  { name: "settings", icon: "settings", label: "설정", component: SettingsPanel, css: "settings.css", place: "bottom",
    hint: (s) => "AI 연결: " + (s.conn.chip || s.conn.label), dot: (s) => s.conn.tone || "plain" },
];

export const byName = (name) => PANELS.find((p) => p.name === name) || null;
/** 메뉴 단추가 가리키는 항목의 이름: 묶인 화면은 묶음의 첫 항목. */
export const leadOf = (p) => (p ? p.group || p.name : null);
/** 한 묶음의 탭 목록(묶음이 아니면 빈 목록). */
export function tabsOf(name) {
  const lead = leadOf(byName(name));
  const rows = lead ? PANELS.filter((q) => leadOf(q) === lead) : [];
  return rows.length > 1 ? rows : [];
}

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
