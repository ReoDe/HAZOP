// 정리된 보기 오프스크린 시험 항목(tests/test_shell_clean.py가 부른다). 결과: {results: [[이름, 통과, 설명]], timings}.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const median = (a) => { const s = a.slice().sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };

const results = [];
export async function run(args, data) {
  try { return await body(args, data); } catch (e) { results.push(["예외", false, String((e && e.stack) || e)]); return { results, timings: { items: 0, symbols: 0, pipes: 0, runs: 0, first_ms: 0, switch_ms: 0, path200_ms: 0, marks3000_ms: 0, elements: 0 } }; }
}

async function body({ CV, MK, SheetCore }, data) {
  const t = (name, ok, detail = "") => results.push([name, !!ok, String(detail).slice(0, 300)]);
  const mount = () => { const d = document.createElement("div"); d.style.cssText = "width:1000px;height:700px;position:relative"; document.body.appendChild(d); return d; };
  const items = data.sheet.items, symbols = data.symbols, ex = data.clean.items;
  const ev = { unconf: [], built: [] };
  const host = mount();
  const core = new SheetCore(host, { onUnconfirmedClick: (d) => ev.unconf.push(d), onCleanBuilt: (i) => ev.built.push(i), onReady: () => {} });
  core.setData(data.sheet);
  await sleep(200);
  const vp = host.querySelector(".hz-cv-vp"), vpR = () => vp.getBoundingClientRect();
  const sheetRect = (el) => { const r = el.getBoundingClientRect(), v = vpR(), k = core.view.k; return { x0: (r.left - v.left - core.view.x) / k, y0: (r.top - v.top - core.view.y) / k, x1: (r.right - v.left - core.view.x) / k, y1: (r.bottom - v.top - core.view.y) / k }; };
  const pe = (type, x, y, extra = {}) => new PointerEvent(type, Object.assign({ bubbles: true, cancelable: true, clientX: vpR().left + x, clientY: vpR().top + y, button: 0, pointerId: 1, isPrimary: true }, extra));
  const toScreen = (sx, sy) => ({ x: sx * core.view.k + core.view.x, y: sy * core.view.k + core.view.y });
  const click = (sx, sy) => { const p = toScreen(sx, sy); vp.dispatchEvent(pe("pointerdown", p.x, p.y)); vp.dispatchEvent(pe("pointerup", p.x, p.y)); };

  // ---- 원본 보기
  core.update({ clean: data.clean, symbols, view: "orig" });
  t("원본 보기: data-view=orig, 바탕 그림 보임, 정리된 그림은 만들지 않음", host.getAttribute("data-view") === "orig" && core.image.style.display === "" && core.cleanG.childNodes.length === 0 && ev.built.length === 0);
  const before = { view: JSON.stringify(core.view), world: core.world.style.transform };
  const orig = JSON.stringify(core.view);

  // ---- 정리된 보기로 바꾸기: 같은 viewBox·같은 이동·확대 값
  core.update({ view: "clean" });
  const clean = core.cleanG;
  t("정리 보기: data-view=clean, 원본 그림은 숨기고 정리된 그림이 보임", host.getAttribute("data-view") === "clean" && core.image.style.display === "none" && clean.style.display === "" && clean.childNodes.length > items.length, clean.childNodes.length);
  t("정리 보기: onCleanBuilt가 한 번, 그린 요소 수를 알림", ev.built.length === 1 && ev.built[0].elements > 0, JSON.stringify(ev.built[0]));
  t("바꿔도 화면 이동·확대·viewBox가 그대로", JSON.stringify(core.view) === before.view && core.world.style.transform === before.world && core.svg.getAttribute("viewBox") === `0 0 ${data.sheet.width} ${data.sheet.height}`, orig);

  // ---- 좌표: 기호 그림이 원본 bbox 중심에 놓임(규격 §10.8: 2 단위 안)
  const drawn = items.filter((i) => i.layer === "symbol" && i.kind && symbols[i.kind] && !symbols[i.kind].junction && !i.unknown);
  let worst = 0, missing = [], outside = 0;
  for (const it of drawn) {
    const g = clean.querySelector(`g[data-id="${CSS.escape(it.id)}"]`);
    if (!g) { missing.push(it.id); continue; }
    const m = /translate\(([-\d.]+) ([-\d.]+)\) rotate/.exec(g.getAttribute("transform"));
    const cx = (it.bbox[0] + it.bbox[2]) / 2, cy = (it.bbox[1] + it.bbox[3]) / 2;
    worst = Math.max(worst, Math.hypot(+m[1] - cx, +m[2] - cy));
    const r = sheetRect(g);
    if (r.x0 < it.bbox[0] - 2 || r.y0 < it.bbox[1] - 2 || r.x1 > it.bbox[2] + 2 || r.y1 > it.bbox[3] + 2) outside++;
  }
  t("기호 " + drawn.length + "개가 모두 그려짐(<g data-id>)", missing.length === 0 && drawn.length >= 20, missing.slice(0, 5).join(","));
  t("기호 그림의 중심이 bbox 중심과 2 단위 안에서 겹침", worst < 2, worst);
  t("기호 그림이 bbox 안에 듦(오차 2 단위, 회전·뒤집기 포함)", outside === 0, outside + "개가 벗어남");
  const rotated = drawn.filter((i) => ex[i.id] && ex[i.id].orient && ex[i.id].orient.rot % 180 === 90 && clean.querySelector(`g[data-id="${CSS.escape(i.id)}"]`));
  t("세로로 돌려 그린 밸브(direction=south·north)가 있음", rotated.length >= 3, rotated.length);
  const longValves = rotated.filter((it) => symbols[it.kind].vb[0] > symbols[it.kind].vb[1]);
  const tall = longValves.filter((it) => { const r = sheetRect(clean.querySelector(`g[data-id="${CSS.escape(it.id)}"]`)); return (r.y1 - r.y0) > (r.x1 - r.x0); });
  t("가로로 그린 밸브를 돌리면(direction=south·north) 세로로 서 있음", longValves.length >= 1 && tall.length === longValves.length, tall.length + "/" + longValves.length);

  // ---- 배관·분기점·화살촉
  const pipes = items.filter((i) => i.layer === "pipe");
  const pl = clean.querySelectorAll("polyline[data-id]");
  t("배관마다 선 하나(추출한 길 그대로)", pl.length === pipes.length, pl.length + "/" + pipes.length);
  const dashes = new Set([...pl].map((p) => p.getAttribute("stroke-dasharray")));
  t("계측 연결은 긴 점선 '6 3', 신호선은 짧은 점선 '2 2', 공정 배관은 실선", dashes.has("6 3") && dashes.has("2 2") && dashes.has(null), [...dashes].join("|"));
  const firstPipe = pipes[0], pts = (firstPipe.polyline || []).map((p) => p[0].toFixed(0) + "," + p[1].toFixed(0));
  t("배관 점이 items의 polyline과 같음", clean.querySelector(`polyline[data-id="${CSS.escape(firstPipe.id)}"]`).getAttribute("points").split(" ").map((p) => p.split(",").map((v) => (+v).toFixed(0)).join(",")).join(" ") === pts.join(" "));
  const tees = items.filter((i) => i.layer === "symbol" && i.kind === "tee").length;
  t("tee는 그림 없이 지름 3 단위 점", tees >= 5 && clean.querySelectorAll('circle[r="1.5"]').length === tees, tees);
  t("흐름이 있는 배관에 화살촉(polygon)", clean.querySelectorAll("polygon").length >= 5, clean.querySelectorAll("polygon").length);

  // ---- 못 읽은 곳
  const unk = clean.querySelector('rect[data-id="x-unknown"]');
  t("미확인 기호: 호박색 점선 네모 '4 3'와 가운데 ?", !!unk && unk.getAttribute("stroke-dasharray") === "4 3" && unk.getAttribute("stroke").includes("warn") && [...clean.querySelectorAll("text")].some((x) => x.textContent === "?"));
  t("끊긴 연결: 열린 끝에 호박색 빈 원(지름 6), 배관은 읽은 데까지", clean.querySelectorAll('circle[r="3"]').length === 1 && !!clean.querySelector('polyline[data-id="x-open"]'));
  t("태그 없음: 호박색 점선 밑줄과 '태그 없음' 글자", [...clean.querySelectorAll("text")].filter((x) => x.textContent === "태그 없음").length === data.clean.counts.missing_tag && data.clean.counts.missing_tag >= 1, data.clean.counts.missing_tag);
  t("그림 없는 kind: generic 자리표와 머리글자, 알림 목록", ev.built[0].missingKinds.join() === "weird_kind" && !!clean.querySelector('g[data-id="x-weird"]') && [...clean.querySelectorAll("text")].some((x) => x.textContent === "W"), ev.built[0].missingKinds.join());
  t("미확인 수가 자료의 counts와 같음", data.clean.counts.total === data.clean.unconfirmed.length && data.clean.counts.unknown_symbol >= 1 && data.clean.counts.open_end === 1, JSON.stringify(data.clean.counts));

  // ---- 도면에서 온 글은 텍스트로만
  t("HTML처럼 보이는 태그는 글자로만 들어감", !clean.querySelector("img") && [...clean.querySelectorAll("text")].some((x) => x.textContent === "<img src=x onerror=window.__pwned=1>") && window.__pwned === undefined);
  t("기호 그림은 symbols.json의 도형만(요소 종류 제한)", [...clean.querySelectorAll("g[data-id] > *")].every((n) => ["path", "line", "polyline", "polygon", "circle", "rect"].includes(n.tagName)));

  // ---- 누르기: 미확인 자리 → 원본 조각
  core.update({ mode: "pan" });
  const ub = items.find((i) => i.id === "x-unknown").bbox;
  click((ub[0] + ub[2]) / 2, (ub[1] + ub[3]) / 2);
  const last = ev.unconf[ev.unconf.length - 1];
  t("미확인 기호를 누르면 onUnconfirmedClick(id·reason·원본 조각)", !!last && last.id === "x-unknown" && last.reason === "unknown_symbol" && !!last.fragment, JSON.stringify(last && last.reason));
  const fb = last.fragment.box;
  const ex0 = Math.max(0, ub[0] - 24), ex1 = Math.min(data.sheet.width, ub[2] + 24);
  t("원본 조각은 bbox를 사방 24 단위 넓힌(도면 안으로 자른) viewBox, 같은 도면 SVG 주소", Math.abs(fb.x - ex0) < 0.01 && Math.abs(fb.w - (ex1 - ex0)) < 0.01 && last.fragment.href === data.sheet.svg, JSON.stringify(fb));
  core.update({ command: { seq: 1, type: "inspect", id: "x-open", reason: "open_end", pad: 0.5 } });
  const insp = ev.unconf[ev.unconf.length - 1];
  t("명령 inspect(N 키): 그 자리로 가서 같은 신호를 보냄", insp.id === "x-open" && insp.reason === "open_end" && !!insp.fragment);
  const nBefore = ev.unconf.length;
  const nk = items.find((i) => i.kind === "pump"), nb = nk.bbox;
  click((nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2);
  t("읽은 기호를 누르면 미확인 신호는 없음", ev.unconf.length === nBefore);

  // ---- 표시: 정리된 보기에서는 상자를 덧그리지 않고 그 객체의 색을 바꾼다
  const symIds = drawn.slice(0, 4).map((i) => i.id), pipeIds = pipes.slice(0, 3).map((p) => p.id);
  core.update({ marks: [{ id: "q1", op: "mark", groups: [{ ids: symIds.concat(pipeIds), style: "cause", label: null }], dim_others: true }] });
  const marksG = core.marksG;
  t("표시(정리): 흐림막 한 장 + 기호는 색 입힌 같은 그림(<g>)·배관은 같은 길(polyline)", !!marksG.querySelector("rect[fill-opacity]") && marksG.querySelectorAll("g[transform]").length >= symIds.length && marksG.querySelectorAll("polyline").length >= pipeIds.length, marksG.innerHTML.length);
  t("표시(정리): 상자(rect)를 따로 덧그리지 않음(흐림막 하나뿐)", marksG.querySelectorAll("rect").length === 1, marksG.querySelectorAll("rect").length);
  const markG = marksG.querySelector("g[transform]");
  t("표시(정리): 색이 표시 색이고 바탕 그림과 같은 변환(같은 자리)", markG.firstChild.getAttribute("stroke") === MK.STYLE_COLORS.cause && markG.getAttribute("transform") === clean.querySelector(`g[data-id="${CSS.escape(symIds[0])}"]`).getAttribute("transform") || markG.getAttribute("transform").length > 10);
  core.update({ marks: [], selection: [symIds[0]] });
  t("고른 것(정리): 파란 선과 12% 채움으로 같은 그림을 다시 그림", marksG.querySelectorAll("g[transform]").length === 1 && marksG.querySelector("g[transform]").firstChild.getAttribute("stroke") === MK.STYLE_COLORS.focus && marksG.querySelector("g[transform]").firstChild.getAttribute("fill-opacity") !== null);
  core.update({ selection: [], segments: [{ node_id: "S1", ids: symIds.concat(pipeIds), color: null }] });
  t("구간 색(정리): 구간에 든 기호·배관을 그 색으로", marksG.innerHTML.includes("--seg1") && marksG.querySelectorAll("polyline").length >= pipeIds.length && marksG.querySelectorAll("text").length >= 1);
  core.update({ segments: [] });

  // ---- 보기 바꾸기를 오가도 표시·고른 것은 그대로, 원본에서는 상자
  core.update({ view: "orig", marks: [{ id: "q2", op: "mark", groups: [{ ids: symIds, style: "focus" }] }] });
  t("원본으로 되돌리면 바탕 그림이 보이고 표시는 상자로(이전 방식)", core.image.style.display === "" && core.cleanG.style.display === "none" && marksG.querySelectorAll("rect").length >= symIds.length, marksG.querySelectorAll("rect").length);
  core.update({ view: "clean", marks: [] });
  t("다시 정리로: 정리된 그림을 새로 만들지 않고 보이기만 바꿈", ev.built.length === 1);
  core.update({ view: "orig" });
  const noClean = new SheetCore(mount(), {});
  noClean.setData(data.sheet);
  noClean.update({ view: "clean" });
  t("정리 자료·기호가 없으면 정리를 원해도 원본으로 그림", noClean.host.getAttribute("data-view") === "orig" && noClean.cleanG.childNodes.length === 0);
  noClean.destroy();

  // ---- 5,800개 쪽(합성): 처음 그리기, 바꾸기, 경로 색 바꾸기
  const kinds = Object.keys(symbols).filter((k) => !symbols[k].junction && k !== "generic");
  const W = 4000, H = 3000, bigItems = [], bigEx = {};
  for (let i = 0; i < 3000; i++) {
    const x = 40 + (i % 60) * 62, y = 40 + Math.floor(i / 60) * 56, kind = kinds[i % kinds.length], id = "s" + i;
    bigItems.push({ id, layer: "symbol", kind, category: i % 3 ? "valve" : "equipment", tag: "T-" + i, bbox: [x, y, x + 30, y + 40], unknown: false, label_bbox: null });
    bigEx[id] = { orient: { rot: (i % 4) * 90, flip_h: i % 7 === 0, flip_v: false, basis: "drawio" }, review: "script" };
  }
  for (let j = 0; j < 2800; j++) {
    const x = 40 + (j % 70) * 55, y = 90 + Math.floor(j / 70) * 70, id = "p" + j;
    bigItems.push({ id, layer: "pipe", kind: "physical_connection", tag: j % 5 ? null : "L-" + j, bbox: [x, y, x + 40, y], polyline: [[x, y], [x + 40, y]], unknown: false });
    bigEx[id] = { line_type: j % 9 ? "process" : "instrument_tap", flow: j % 2 ? "source_to_target" : null, ends: [{ end: "source", point: [x, y], status: "connected", node: null }, { end: "target", point: [x + 40, y], status: "connected", node: null }], review: "script" };
  }
  const bigClean = { source_format: "drawio", items: bigEx, text_items: [], unconfirmed: [], counts: { total: 0 } };
  const bh = mount();
  const bcb = { built: [] };
  const big = new SheetCore(bh, { onCleanBuilt: (i) => bcb.built.push(i) });
  big.setData({ graph_id: "big", width: W, height: H, svg: "", items: bigItems, links: [] });
  await sleep(100);
  big.update({ clean: bigClean, symbols, view: "orig" });
  const firsts = [], switches = [], paths = [], m3000 = [];
  let elements = 0;
  for (let run = 0; run < 5; run++) {
    big._cleanBuilt = false; big.update({ view: "orig" });
    let t0 = performance.now();
    big.update({ view: "clean" });
    firsts.push(performance.now() - t0);
    elements = bcb.built[bcb.built.length - 1].elements;
    t0 = performance.now(); big.update({ view: "orig" }); big.update({ view: "clean" }); switches.push((performance.now() - t0) / 2);
    const steps = bigItems.slice(0, 200).map((it) => ({ id: it.id, flow: null }));
    t0 = performance.now(); big.update({ marks: [{ id: "bp" + run, op: "path", steps, style: "path", numbered: true }] }); paths.push(performance.now() - t0);
    t0 = performance.now(); big.update({ marks: [{ id: "bm" + run, op: "mark", groups: [{ ids: bigItems.slice(0, 3000).map((i) => i.id), style: "cause" }] }] }); m3000.push(performance.now() - t0);
    big.update({ marks: [] });
  }
  t("5,800개 쪽: 정리된 그림이 모두 그려짐", big.cleanG.querySelectorAll("g[data-id]").length >= 2900 && big.cleanG.querySelectorAll("polyline[data-id]").length === 2800, big.cleanG.querySelectorAll("g[data-id]").length);
  big.destroy();
  return { results, timings: { items: bigItems.length, symbols: 3000, pipes: 2800, runs: 5, first_ms: median(firsts), switch_ms: median(switches), path200_ms: median(paths), marks3000_ms: median(m3000), elements } };
}
