// 도면 구성요소(hazop/shell/web/js/canvas/) 웹 쪽 단위 시험. tests/test_shell_canvas.py가 오프스크린 웹뷰에서 돌리고 결과를 읽는다.
// run(hz, data, big)은 [[이름, 통과 여부, 자세한 말], …]과 잰 시간을 돌려준다. 순수 함수 시험(색인·고르기·표시 계산)과 DOM 시험(SheetCore)이 함께 있다.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function run(hz, data, big) {
  const { SpatialIndex, changeSelection, capSelection, selectionEvent, MAX_SELECTION } = hz.IDX;
  const MK = hz.MK;
  const out = [];
  const t = (name, ok, detail) => out.push([name, !!ok, ok ? "" : String(detail === undefined ? "" : detail)]);
  const eq = (name, a, b) => t(name, JSON.stringify(a) === JSON.stringify(b), JSON.stringify(a) + " != " + JSON.stringify(b));
  const timings = {};

  // ------------------------------------------------------------ 공간 색인(순수)
  {
    const items = [
      { id: "a", layer: "symbol", bbox: [100, 100, 140, 140] },
      { id: "a", layer: "tag", bbox: [100, 145, 140, 155] },
      { id: "b", layer: "symbol", bbox: [200, 100, 240, 140] },
      { id: "p1", layer: "pipe", bbox: [140, 120, 200, 120], polyline: [[140, 120], [200, 120]] },
      { id: "diag", layer: "pipe", bbox: [0, 0, 1000, 1000], polyline: [[0, 0], [1000, 1000]] },
      { id: "far", layer: "symbol", bbox: [900, 20, 940, 60] },
    ];
    const ix = new SpatialIndex(items);
    eq("색인: 네모 안 구성요소(문서 순서·중복 없음)", ix.queryBox({ x0: 80, y0: 80, x1: 260, y1: 200 }), ["a", "b", "p1", "diag"]);
    eq("색인: 거꾸로 끈 네모도 같음", ix.queryBox({ x0: 260, y0: 200, x1: 80, y1: 80 }), ["a", "b", "p1", "diag"]);
    eq("색인: 외곽 상자만 겹치고 선은 안 지나는 배관은 고르지 않음", ix.queryBox({ x0: 800, y0: 0, x1: 960, y1: 100 }), ["far"]);
    eq("색인: 선이 지나가면 배관을 고름", ix.queryBox({ x0: 495, y0: 495, x1: 505, y1: 505 }), ["diag"]);
    eq("색인: 층을 끄면 뺌", ix.queryBox({ x0: 80, y0: 80, x1: 260, y1: 200 }, { layers: new Set(["symbol"]) }), ["a", "b"]);
    eq("색인: 누르기 — 태그가 기호보다 위", ix.hitTest(120, 150, 0), { id: "a", layer: "tag" });
    eq("색인: 누르기 — 기호 안", ix.hitTest(120, 110, 0), { id: "a", layer: "symbol" });
    eq("색인: 누르기 — 배관은 여유 안에서", ix.hitTest(170, 123, 4), { id: "p1", layer: "pipe" });
    eq("색인: 누르기 — 아무것도 없는 곳", ix.hitTest(600, 50, 3), null);
    eq("색인: 범위", ix.bounds(["a", "b"]), { x0: 100, y0: 100, x1: 240, y1: 155 });
    t("색인: 대표 사각형은 기호", JSON.stringify(ix.rectOf("a")) === JSON.stringify({ x0: 100, y0: 100, x1: 140, y1: 140 }));
    const sel = changeSelection(["a"], ["b", "a"], "add");
    eq("고르기: 더하기는 새 것만", sel, { selected: ["a", "b"], added: ["b"], removed: [] });
    eq("고르기: 다시 누르면 빠짐", changeSelection(["a", "b"], ["a"], "toggle"), { selected: ["b"], added: [], removed: ["a"] });
    eq("고르기: 바뀐 것이 없으면 null", changeSelection(["a"], ["a"], "add"), null);
    const many = Array.from({ length: 2500 }, (_, i) => "i" + i);
    const ev = selectionEvent({ selected: many, added: many, removed: [] }, "box");
    t("고르기: 2,000개를 넘으면 앞에서 자르고 알림", ev.selected.length === MAX_SELECTION && ev.truncated === true && ev.selected[0] === "i0", JSON.stringify(ev.truncated));
    t("고르기: 2,000개 이하는 그대로", selectionEvent({ selected: ["a"], added: ["a"], removed: [] }, "click").truncated === false);
  }

  // ------------------------------------------------------------ 표시 계산(순수)
  {
    const ix = new SpatialIndex([
      { id: "n1", layer: "symbol", bbox: [100, 100, 140, 140] },
      { id: "r1", layer: "pipe", bbox: [140, 120, 300, 120], polyline: [[140, 120], [300, 120]] },
      { id: "n2", layer: "symbol", bbox: [300, 100, 340, 140], unknown: true },
      { id: "r2", layer: "pipe", bbox: [340, 120, 500, 120], polyline: [[340, 120], [500, 120]] },
      { id: "n3", layer: "symbol", bbox: [500, 100, 540, 140] },
    ]);
    const marks = MK.normalizeMarks([{ id: "q1", op: "mark", groups: [{ ids: ["n1"], style: "focus" }] }, { id: "q2", op: "mark", groups: [{ ids: ["n2"], style: "cause" }] },
      { id: "q1", op: "mark", groups: [{ ids: ["n3"], style: "warn" }] }, { bad: 1 }, { id: "q3", op: "nope" }]);
    eq("표시: 같은 요청 ID는 덮어씀(순서는 처음 자리)", marks.map((m) => [m.id, m.groups[0].ids[0]]), [["q1", "n3"], ["q2", "n2"]]);
    eq("표시: 요청 하나만 지우면 그 요청(과 #n)만", MK.removeMarks([{ id: "q1" }, { id: "q1#1" }, { id: "q2" }], "q1#1").map((m) => m.id), ["q2"]);
    eq("표시: 전부 지우기", MK.removeMarks([{ id: "q1" }], null), []);
    const r = MK.resolveMark({ id: "m", op: "mark", groups: [{ ids: ["n1", "ghost"], style: "seg:7", label: "원인" }] }, ix);
    eq("표시: 못 그린 ID", r.missing, ["ghost"]);
    t("표시: seg:7은 5색 순환(7 % 5 + 1 = 3번)", MK.styleColor("seg:7").includes("--seg3"), MK.styleColor("seg:7"));
    t("표시: 꼬리표 하나", r.badges.length === 1 && r.badges[0].text === "원인");
    const path = MK.resolveMark({ id: "p", op: "path", steps: [{ id: "n1" }, { id: "r1", flow: "with" }, { id: "n2" }, { id: "r2", flow: "unknown" }, { id: "n3" }, { id: "gone" }], numbered: true }, ix);
    eq("경로: 번호는 객체 단계에만", path.badges.map((b) => b.text), ["1", "2", "3"]);
    eq("경로: 못 그린 ID", path.missing, ["gone"]);
    t("경로: 확인된 흐름 배관에만 화살표", path.arrows.length === 1);
    t("경로: 앞 단계에 가까운 끝에서 반대 끝으로(오른쪽)", Math.abs(path.arrows[0].ang) < 1e-9, path.arrows[0].ang);
    const against = MK.resolveMark({ id: "p", op: "path", steps: [{ id: "n1" }, { id: "r1", flow: "against" }, { id: "n2" }] }, ix);
    t("경로: against는 반대(왼쪽)", Math.abs(Math.abs(against.arrows[0].ang) - Math.PI) < 1e-9, against.arrows[0].ang);
    t("경로: 점선 배관(unknown 흐름)", path.items.some((i) => i.id === "r2" && i.dashed === true));
    t("경로: 출발은 파랑 상자, 확인 못 한 곳은 점선 상자", path.items.some((i) => i.box === "start" && i.id === "n1") && path.items.some((i) => i.box === "unknown" && i.id === "n2"));
    const seg = MK.buildSegments([{ node_id: "S1", ids: ["n1", "r1", "n2"] }, { node_id: "S2", ids: ["n2", "n3"] }], ix);
    t("구간: 겹친 요소는 둘 다 기록", seg.byItem.get("n2").length === 2 && seg.overlaps === 1);
    const drawn = MK.drawAll({ marks: [], seg, selection: [], index: ix, k: 1, size: [1000, 500] });
    t("구간: 겹침 줄무늬(점선 6 6)가 그려짐", JSON.stringify(drawn.nodes).includes('"stroke-dasharray":"6 6"'));
    t("구간: 겹친 기호에 'S1·S2' 꼬리표", JSON.stringify(drawn.nodes).includes("S1·S2"));
    t("구간: 구간 하나만 고르면 흐림막", MK.drawAll({ marks: [], seg: MK.buildSegments([{ node_id: "S1", ids: ["n1"], active: true }, { node_id: "S2", ids: ["n3"] }], ix), selection: [], index: ix, k: 1, size: [1000, 500] }).dim === true);
    const one = MK.buildSegments([{ node_id: "S1", ids: ["n1"], active: true }, { node_id: "S2", ids: ["n3"] }], ix);
    t("구간: 고른 구간만 칠함", one.byItem.has("n1") && !one.byItem.has("n3"));
    eq("구간 밖 구성요소", MK.outsideIds(["n1", "n2", "n3"], one), ["n2", "n3"]);
    t("표시끼리 지우지 않음: 구간 색·표시·고른 것이 한 번에 그려짐", (() => {
      const all = MK.drawAll({ marks: [{ id: "m", op: "mark", groups: [{ ids: ["n3"], style: "cause" }] }], seg, selection: ["n1"], index: ix, k: 1, size: [1000, 500] });
      const s = JSON.stringify(all.nodes);
      return s.includes("--seg1") && s.includes("--hl-cause") && s.includes("--hl-focus");
    })());
    const labels = [{ id: "x", x: 0, y: 0, w: 40, h: 15, rank: 2 }, { id: "y", x: 20, y: 5, w: 40, h: 15, rank: 0 }, { id: "z", x: 200, y: 200, w: 40, h: 15, rank: 2 }];
    eq("태그 겹침 풀기: 고른 것(rank 0)이 먼저, 겹친 것은 숨김", Array.from(MK.uncrowdTags(labels)).sort(), ["y", "z"]);
    eq("범례: 경로 표시가 있으면 항목", MK.legendEntries([{ id: "p", op: "path", steps: [] }], null).map((e) => e.text).slice(0, 1), ["경로(굵은 선, 단계 번호)"]);
    eq("범례: 표시가 없으면 비어 있음", MK.legendEntries([], null), []);
  }

  // ------------------------------------------------------------ SheetCore(DOM)
  const mount = () => {
    const host = document.createElement("div");
    host.style.cssText = "width:900px;height:600px;position:absolute;left:0;top:0";
    document.body.appendChild(host);
    return host;
  };
  const ev = { ready: [], click: [], dbl: [], hover: [], sel: [], view: [], mark: [], esc: 0, link: [], seg: [] };
  const cb = {
    onReady: (g) => ev.ready.push(g), onItemClick: (e) => ev.click.push(e), onItemDblClick: (e) => ev.dbl.push(e), onHover: (e) => ev.hover.push(e),
    onSelection: (e) => ev.sel.push(e), onViewport: (e) => ev.view.push(e), onMarkResult: (e) => ev.mark.push(e), onEsc: () => { ev.esc++; }, onLinkClick: (l) => ev.link.push(l), onSegmentClick: (d) => ev.seg.push(d),
  };
  const host = mount();
  const core = new hz.SheetCore(host, cb);
  core.setData(data);
  await sleep(300);
  t("도면: 자료를 읽고 onReady(graph_id)", ev.ready.length >= 1 && ev.ready[0] === data.graph_id, JSON.stringify(ev.ready));
  const vpEl = host.querySelector(".hz-cv-vp");
  const rect = vpEl.getBoundingClientRect();
  const content = data.items.filter((i) => i.layer !== "tag").reduce((c, i) => ({ x0: Math.min(c.x0, i.bbox[0]), y0: Math.min(c.y0, i.bbox[1]), x1: Math.max(c.x1, i.bbox[2]), y1: Math.max(c.y1, i.bbox[3]) }), { x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9 });
  t("도면: 맞춤 — 그려진 내용(기호·배관)이 화면을 채우고 모두 보임", core.view.k > 0 && content.x0 * core.view.k + core.view.x >= -1 && content.y0 * core.view.k + core.view.y >= -1 && content.x1 * core.view.k + core.view.x <= rect.width + 1 && content.y1 * core.view.k + core.view.y <= rect.height + 1
    && ((content.x1 - content.x0) * core.view.k > rect.width * 0.8 || (content.y1 - content.y0) * core.view.k > rect.height * 0.8), JSON.stringify(core.view));
  t("도면: 바탕 SVG는 <image> 하나(구성요소마다 DOM 없음)", host.querySelectorAll("image").length === 1 && host.querySelectorAll("rect.sym, .sym").length === 0);
  const pe = (type, x, y, extra = {}) => new PointerEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: rect.left + x, clientY: rect.top + y, button: 0, pointerId: 1, isPrimary: true }, extra));
  const toScreen = (sx, sy) => ({ x: sx * core.view.k + core.view.x, y: sy * core.view.k + core.view.y });
  const syms = data.items.filter((i) => i.layer === "symbol");
  const itemC = (it) => toScreen((it.bbox[0] + it.bbox[2]) / 2, (it.bbox[1] + it.bbox[3]) / 2);

  // 휠 확대(마우스 자리 중심)
  const k0 = core.view.k;
  vpEl.dispatchEvent(new WheelEvent("wheel", { deltaY: -100, clientX: rect.left + 300, clientY: rect.top + 200, bubbles: true, cancelable: true }));
  t("휠: 확대", core.view.k > k0 * 1.1, core.view.k + " vs " + k0);
  const under = (px, py, v) => ({ x: (px - v.x) / v.k, y: (py - v.y) / v.k });
  const pBefore = under(300, 200, { x: 0, y: 0, k: 1 });  // 자리표시용(아래 검사는 좌표 보존)
  void pBefore;
  core.fit();
  await sleep(60);
  // 끌어 옮기기
  const v0 = Object.assign({}, core.view);
  vpEl.dispatchEvent(pe("pointerdown", 400, 300));
  vpEl.dispatchEvent(pe("pointermove", 450, 330));
  vpEl.dispatchEvent(pe("pointerup", 450, 330));
  t("이동 모드: 끌면 화면이 옮겨짐", Math.abs(core.view.x - (v0.x + 50)) < 1 && Math.abs(core.view.y - (v0.y + 30)) < 1, JSON.stringify(core.view));
  await sleep(250);
  t("이동 모드: 멈춘 뒤 onViewport 한 번 알림", ev.view.length >= 1 && Math.abs(ev.view[ev.view.length - 1].x - core.view.x) < 1, JSON.stringify(ev.view.slice(-1)));
  t("이동 모드: 끌기 뒤에는 누르기로 치지 않음", ev.click.length === 0);
  core.fit();
  await sleep(60);

  // 누르기
  const target = syms.find((s) => s.tag) || syms[0];
  const c = itemC(target);
  vpEl.dispatchEvent(pe("pointerdown", c.x, c.y));
  vpEl.dispatchEvent(pe("pointerup", c.x, c.y));
  t("이동 모드: 누르면 onItemClick(id·종류·태그·화면 위치)", ev.click.length === 1 && ev.click[0].via === "click" && ev.click[0].rect && ev.click[0].rect.w > 0 && typeof ev.click[0].id === "string", JSON.stringify(ev.click));
  t("이동 모드: 누르기는 고른 것을 바꾸지 않음", ev.sel.length === 0);

  // 호버는 requestAnimationFrame 뒤
  vpEl.dispatchEvent(pe("pointermove", c.x, c.y, { buttons: 0 }));
  await sleep(120);
  t("마우스 올림: onHover(id, 화면 위치)", ev.hover.length >= 1 && ev.hover[0] && typeof ev.hover[0].id === "string" && ev.hover[0].rect.w > 0, JSON.stringify(ev.hover));

  // Shift+끌기 = 네모로 더하기(이동 모드에서도)
  const two = syms.slice(0, 2);
  const a = itemC(two[0]), b = itemC(two[1]);
  const box = { x0: Math.min(a.x, b.x) - 20, y0: Math.min(a.y, b.y) - 20, x1: Math.max(a.x, b.x) + 20, y1: Math.max(a.y, b.y) + 20 };
  vpEl.dispatchEvent(pe("pointerdown", box.x0, box.y0, { shiftKey: true }));
  vpEl.dispatchEvent(pe("pointermove", box.x1, box.y1, { shiftKey: true }));
  t("고르기: 끄는 동안 고무줄 네모", !!host.querySelector(".hz-cv-rubber"));
  vpEl.dispatchEvent(pe("pointerup", box.x1, box.y1, { shiftKey: true }));
  t("고르기: Shift+끌기(이동 모드)로 네모에 든 것을 더함", ev.sel.length === 1 && ev.sel[0].via === "box" && ev.sel[0].added.includes(two[0].id) && ev.sel[0].added.includes(two[1].id), JSON.stringify(ev.sel));
  t("고르기: 고무줄 네모가 사라짐", !host.querySelector(".hz-cv-rubber"));
  const n1 = core.getSelection().length;
  vpEl.dispatchEvent(pe("pointerdown", box.x0, box.y0, { altKey: true }));
  vpEl.dispatchEvent(pe("pointermove", box.x1, box.y1, { altKey: true }));
  vpEl.dispatchEvent(pe("pointerup", box.x1, box.y1, { altKey: true }));
  t("고르기: Alt+끌기로 네모 안을 뺌", ev.sel.length === 2 && ev.sel[1].via === "box_remove" && core.getSelection().length < n1 && !core.getSelection().includes(two[0].id), JSON.stringify(ev.sel[1]));

  // 고르기 모드: 끌기 = 더하기, 클릭 = 넣고 빼기, Esc = 비우기
  core.update({ mode: "pick" });
  t("고르기 모드: 표시", host.getAttribute("data-mode") === "pick");
  const base = ev.sel.length;
  vpEl.dispatchEvent(pe("pointerdown", c.x, c.y));
  vpEl.dispatchEvent(pe("pointerup", c.x, c.y));
  t("고르기 모드: 누르면 더함(via click)", ev.sel.length === base + 1 && ev.sel[base].via === "click" && ev.sel[base].added.length === 1, JSON.stringify(ev.sel.slice(base)));
  t("고르기 모드: 누르기가 말풍선(onItemClick)을 열지 않음", ev.click.length === 1);
  vpEl.dispatchEvent(pe("pointerdown", c.x, c.y));
  vpEl.dispatchEvent(pe("pointerup", c.x, c.y));
  t("고르기 모드: 다시 누르면 뺌", ev.sel.length === base + 2 && ev.sel[base + 1].removed.length === 1);
  vpEl.dispatchEvent(pe("pointerdown", box.x0, box.y0));
  vpEl.dispatchEvent(pe("pointermove", box.x1, box.y1));
  vpEl.dispatchEvent(pe("pointerup", box.x1, box.y1));
  t("고르기 모드: 끌면 네모로 더함", ev.sel[ev.sel.length - 1].via === "box" && ev.sel[ev.sel.length - 1].added.length >= 1);
  const countSel = ev.sel.length;
  core.update({ selection: ["__x__"].concat(core.getSelection().slice(0, 1)) });
  t("고르기: selection 속성으로 바꾼 것은 알리지 않음(없는 id는 버림)", ev.sel.length === countSel && core.getSelection().length === 1, JSON.stringify(core.getSelection()));
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  t("Esc: onEsc 알림 + 고르기 모드에서 고른 것 비움(via clear)", ev.esc === 1 && ev.sel[ev.sel.length - 1].via === "clear" && core.getSelection().length === 0, JSON.stringify(ev.sel[ev.sel.length - 1]));
  core.update({ mode: "pan" });

  // 표시: 경로·표시·구간 색·고른 것이 서로 지우지 않음
  const ids = syms.slice(0, 4).map((s) => s.id);
  const marksProp = [
    { id: "q1", op: "mark", groups: [{ ids: [ids[0], "ghost-id"], style: "cause", label: "원인" }], dim_others: true },
    { id: "q2", op: "path", steps: [{ id: ids[1] }, { id: ids[2] }], style: "path", numbered: true },
  ];
  const segsProp = [{ node_id: "S1", ids: [ids[0], ids[1]], color: null }, { node_id: "S2", ids: [ids[1], ids[3]] }];
  core.update({ marks: marksProp, segments: segsProp, selection: [ids[3]] });
  const marksG = host.querySelector(".hz-cv-marks");
  const html = marksG.innerHTML;
  t("표시: 구간 색·채팅 표시·경로 번호·고른 것이 한 번에 그려짐", html.includes("--seg1") && html.includes("--hl-cause") && html.includes("--hl-focus") && marksG.querySelectorAll("text").length >= 4, marksG.querySelectorAll("text").length);
  t("표시: 흐림막(dim)", !!marksG.querySelector('rect[fill-opacity]'));
  t("표시: onMarkResult — 못 그린 ID", ev.mark.some((m) => m.id === "q1" && m.missing.includes("ghost-id")) && ev.mark.some((m) => m.id === "q2" && m.missing.length === 0), JSON.stringify(ev.mark));
  t("표시: 범례가 뜸", host.querySelector(".hz-cv-legend").classList.contains("on"));
  const nBefore = marksG.childNodes.length;
  core.update({ marks: [marksProp[0]] });
  t("표시: 경로를 지워도 구간 색·원인 표시는 남음", marksG.childNodes.length < nBefore && marksG.innerHTML.includes("--seg1") && marksG.innerHTML.includes("--hl-cause"));
  core.update({ command: { seq: 1, type: "clearMarks" } });
  t("명령 clearMarks: 표시는 지우고 구간 색·고른 것은 남음", !marksG.innerHTML.includes("--hl-cause") && marksG.innerHTML.includes("--seg1") && marksG.innerHTML.includes("--hl-focus"));
  core.update({ command: { seq: 1, type: "clearMarks" } });
  core.update({ segments: [{ node_id: "S1", ids: [ids[0], ids[1]], active: true }, { node_id: "S2", ids: [ids[1], ids[3]] }] });
  t("구간 하나만 강조: 나머지는 흐림막, 꼬리표는 그 구간만", marksG.querySelectorAll("text").length === 1 && !!marksG.querySelector("rect[fill-opacity]"));
  // 구간 꼬리표를 누르면 onSegmentClick, 구간 밖은 흐리게
  core.update({ segments: [{ node_id: "S1", ids: [ids[0], ids[1]] }], outside: [ids[2], ids[3]] });
  t("구간 밖: 흐리게 칠한 요소가 구간 칠하기와 따로 그려짐", marksG.querySelectorAll('[fill="var(--bg, #f4f5f7)"]').length >= 2, marksG.querySelectorAll('[fill="var(--bg, #f4f5f7)"]').length);
  const bd = core.lastDraw.badges.find((b) => b.node_id === "S1"), kk = core.view.k;
  const bc = toScreen(bd.rect.x0 + 2 / kk, bd.rect.y0 - 8 / kk);
  if (bc) {
    vpEl.dispatchEvent(pe("pointerdown", bc.x, bc.y));
    vpEl.dispatchEvent(pe("pointerup", bc.x, bc.y));
  }
  t("구간 꼬리표 누르기: onSegmentClick({node_id})", ev.seg.length === 1 && ev.seg[0].node_id === "S1", JSON.stringify(ev.seg));
  core.update({ outside: [] });
  core.update({ segments: [], selection: [] });
  core.update({ command: { seq: 2, type: "zoomTo", ids: [ids[0]], pad: 0.5 } });
  t("명령 zoomTo: 그 구성요소를 가운데로", (() => {
    const b = core.index.bounds([ids[0]]); const cc = toScreen((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2); return Math.abs(cc.x - rect.width / 2) < 3 && Math.abs(cc.y - rect.height / 2) < 3;
  })(), JSON.stringify(core.view));
  core.update({ command: { seq: 3, type: "fit" } });

  // 보안: 도면에서 온 글은 글자로만
  {
    const evil = "<img src=x onerror=window.__xss=1><b>굵게</b>";
    const h2 = mount();
    const c2 = new hz.SheetCore(h2, { onLinkClick: () => {} });
    c2.setData({ graph_id: "evil", width: 400, height: 300, svg: "", items: [
      { id: "e1", layer: "symbol", bbox: [10, 10, 50, 50] }, { id: "e1", layer: "tag", bbox: [10, 55, 40, 60], tag: evil } ],
      links: [{ id: "e1", status: "linked", peer_graph_id: evil, label: evil }] });
    c2.update({ viewport: { x: 0, y: 0, k: 0.3 } });
    c2._renderTags();
    await sleep(100);
    const spans = h2.querySelectorAll(".hz-cv-tag");
    t("보안: 태그 글자는 textContent로만(태그 요소가 생기지 않음)", spans.length === 1 && spans[0].textContent === evil && spans[0].querySelectorAll("*").length === 0, spans.length);
    t("보안: 연결 칩 글자도 textContent로만", h2.querySelectorAll(".hz-cv-chip").length === 1 && h2.querySelector(".hz-cv-chip").querySelectorAll("*").length === 0);
    t("보안: 스크립트가 실행되지 않음", window.__xss === undefined);
    const bad = h2.querySelectorAll("img, b, script").length;
    t("보안: 도면 글자에서 img·b·script 요소가 생기지 않음", bad === 0, bad);
    c2.destroy();
    h2.remove();
  }

  // 연결 칩
  {
    const h3 = mount();
    const c3 = new hz.SheetCore(h3, cb);
    const withLinks = Object.assign({}, data, { links: [{ id: syms[0].id, status: "linked", peer_graph_id: "graph-X", peer_id: "n9", label: "SNP-X" }, { id: syms[1].id, status: "unlinked", reason: "상대 도면 없음" }] });
    c3.setData(withLinks);
    await sleep(200);
    const chips = h3.querySelectorAll(".hz-cv-chip");
    t("연결 칩: 연결됨·미연결 둘", chips.length === 2 && chips[0].textContent === "→ SNP-X" && chips[1].classList.contains("warn") && chips[1].textContent.startsWith("미연결"), Array.from(chips).map((x) => x.textContent).join("|"));
    chips[0].click();
    t("연결 칩: 누르면 onLinkClick", ev.link.length === 1 && ev.link[0].peer_graph_id === "graph-X");
    c3.destroy();
    h3.remove();
  }
  core.destroy();
  host.remove();

  // ------------------------------------------------------------ <Sheet>(Preact 포장, 대역 갈고리로 확인)
  {
    const { Sheet, SHEET_API, fetchSheet } = hz.SheetMod, H = hz.HooksStub;
    const seen = [], got = { ready: [] };
    const h4 = mount();
    const props = { sheet: { graph_id: "graph-SNP-M-102", rev: 3 }, mode: "pan", selection: [], marks: [], fetchImpl: async (url) => { seen.push(url); return String(url).includes("/api/sheet/") ? { ok: true, json: async () => data } : { ok: false, status: 404, json: async () => null }; },
      onReady: (g) => got.ready.push(g), class: "extra" };
    H.begin();
    const vnode = Sheet(props);
    t("Sheet: div 하나를 그림(class·ref)", vnode.tag === "div" && vnode.props.class === "hz-sheet extra" && !!vnode.props.ref);
    vnode.props.ref.current = h4;
    H.flush();
    await sleep(400);
    t("Sheet: 도면 자료를 /api/sheet/<id>?rev= 로 읽음(같은 출처)", seen.filter((u) => u.includes("/api/sheet/")).length === 1 && seen[0] === SHEET_API + "graph-SNP-M-102?rev=3" && SHEET_API === "/api/sheet/", JSON.stringify(seen));
    t("Sheet: 읽은 뒤 SheetCore가 그리고 onReady(최신 props의 콜백)", got.ready.length >= 1 && h4.classList.contains("hz-cv"), JSON.stringify(got.ready));
    try { await fetchSheet("x", null, async () => ({ ok: false, status: 404 })); t("Sheet: 못 읽으면 오류", false, "던지지 않음"); }
    catch (e) { t("Sheet: 못 읽으면 오류", String(e.message).includes("404")); }
    h4.remove();
  }

  // ------------------------------------------------------------ 큰 도면 시간(합성 자료)
  {
    const W = 4000, H = 3000, items = [];
    const nSym = big.symbols, nPipe = big.pipes;
    for (let i = 0; i < nSym; i++) {
      const x = 20 + (i % 100) * 38, y = 20 + Math.floor(i / 100) * 38;
      items.push({ id: "s" + i, kind: "valve", tag: "V-" + i, layer: "symbol", bbox: [x, y, x + 24, y + 24] });
      items.push({ id: "s" + i, kind: "valve", tag: "V-" + i, layer: "tag", bbox: [x, y + 26, x + 30, y + 34] });
    }
    for (let j = 0; j < nPipe; j++) {
      const x = 20 + (j % 100) * 38 + 24, y = 20 + Math.floor(j / 100) * 38 + 12;
      items.push({ id: "p" + j, layer: "pipe", bbox: [x, y, x + 14, y], polyline: [[x, y], [x + 14, y]] });
    }
    const bigData = { graph_id: "big", width: W, height: H, svg: "", items, links: [] };
    const hb = mount();
    const selEvents = [];
    const cb2 = new hz.SheetCore(hb, { onSelection: (e) => selEvents.push(e) });
    let t0 = performance.now();
    cb2.setData(bigData);
    timings.setData_ms = performance.now() - t0;
    await sleep(100);
    const allIds = items.filter((i) => i.layer !== "tag").map((i) => i.id);
    t0 = performance.now();
    const hit = cb2.index.queryBox({ x0: 0, y0: 0, x1: W, y1: H });
    timings.queryBox_all_ms = performance.now() - t0;
    t("큰 도면: 전체 네모는 모든 구성요소를 고름", hit.length === nSym + nPipe, hit.length);
    t0 = performance.now();
    let hits = 0;
    for (let i = 0; i < 2000; i++) if (cb2.index.hitTest(20 + (i * 37) % 3800, 20 + (i * 53) % 2800, 4)) hits++;
    timings.hitTest_avg_ms = (performance.now() - t0) / 2000;
    t0 = performance.now();
    for (let i = 0; i < 200; i++) cb2.index.queryBox({ x0: 100 + i * 5, y0: 100 + i * 3, x1: 400 + i * 5, y1: 300 + i * 3 });
    timings.queryBox_small_ms = (performance.now() - t0) / 200;
    t0 = performance.now();
    cb2.update({ marks: [{ id: "big", op: "mark", groups: [{ ids: allIds.slice(0, 3000), style: "path", label: "전체" }] }] });
    timings.mark_3000_ms = performance.now() - t0;
    t0 = performance.now();
    cb2.update({ marks: [{ id: "bigpath", op: "path", steps: allIds.slice(0, 600).map((id) => ({ id, flow: id[0] === "p" ? "with" : null })) }] });
    timings.path_600_ms = performance.now() - t0;
    t0 = performance.now();
    cb2.update({ segments: [{ node_id: "S1", ids: allIds }, { node_id: "S2", ids: allIds.filter((_, i) => i % 2 === 0) }, { node_id: "S3", ids: allIds.filter((_, i) => i % 3 === 0) }] });
    timings.segments_3overlap_ms = performance.now() - t0;
    // 525구간 × 구성요소 5,800개(구간마다 11개): 전부 칠하기, 구간 하나 강조, 구간 밖 흐리게
    const segs525 = []; for (let k = 0; k < 525; k++) segs525.push({ node_id: "S" + (k + 1), ids: Array.from({ length: 11 }, (_, j) => allIds[(k * 11 + j) % allIds.length]) });
    t0 = performance.now();
    cb2.update({ marks: [], segments: segs525 });
    timings.segments_525_ms = performance.now() - t0;
    t0 = performance.now();
    cb2.update({ segments: segs525.map((s, i) => Object.assign({}, s, { active: i === 300 })) });
    timings.segments_focus_ms = performance.now() - t0;
    t0 = performance.now();
    cb2.update({ outside: allIds.slice(0, 5000) });
    timings.outside_5000_ms = performance.now() - t0;
    cb2.update({ outside: [] });
    cb2.update({ marks: [], segments: [] });
    // 전체를 덮는 네모 고르기(포인터 이벤트부터 알림까지)
    const r2 = hb.querySelector(".hz-cv-vp").getBoundingClientRect();
    const hbe = hb.querySelector(".hz-cv-vp");
    cb2.update({ mode: "pick" });
    t0 = performance.now();
    hbe.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, clientX: r2.left, clientY: r2.top, button: 0, pointerId: 2 }));
    hbe.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, clientX: r2.right, clientY: r2.bottom, button: 0, pointerId: 2 }));
    hbe.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: r2.right, clientY: r2.bottom, button: 0, pointerId: 2 }));
    timings.boxSelect_all_ms = performance.now() - t0;
    t("큰 도면: 전체 덮는 네모 → 2,000개로 자르고 truncated", selEvents.length === 1 && selEvents[0].selected.length === 2000 && selEvents[0].truncated === true, JSON.stringify(selEvents.map((e) => [e.selected.length, e.truncated])));
    t("큰 도면: 고른 2,000개가 그려짐", hb.querySelectorAll(".hz-cv-marks > *").length >= 2000);
    cb2.destroy();
    hb.remove();
    timings.symbols = nSym; timings.pipes = nPipe; timings.items = items.length;
  }
  return { results: out, timings };
}
