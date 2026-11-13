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
  const top = core.topG;
  const unk = top.querySelector('rect[data-id="x-unknown"]');
  t("미확인 기호: 호박색 점선 네모 '4 3'와 가운데 ?", !!unk && unk.getAttribute("stroke-dasharray") === "4 3" && unk.getAttribute("stroke").includes("warn") && [...top.querySelectorAll("text")].some((x) => x.textContent === "?"));
  t("끊긴 연결: 열린 끝에 호박색 빈 원(지름 6), 배관은 읽은 데까지", top.querySelectorAll('circle[r="3"]').length === 1 && !!clean.querySelector('polyline[data-id="x-open"]'));
  t("태그 없음: 호박색 점선 밑줄과 '태그 없음' 글자", [...clean.querySelectorAll("text")].filter((x) => x.textContent === "태그 없음").length === data.clean.counts.missing_tag && data.clean.counts.missing_tag >= 1, data.clean.counts.missing_tag);
  t("그림 없는 kind: generic 자리표와 머리글자, 알림 목록", ev.built[0].missingKinds.join() === "weird_kind" && !!clean.querySelector('g[data-id="x-weird"]') && [...top.querySelectorAll("text")].some((x) => x.textContent === "W"), ev.built[0].missingKinds.join());
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

  // ---- 불확실한 것은 표시·흐리기 위에 그대로 남음, 흐리기는 옅게, 번호 원은 겹치지 않음
  core.update({ marks: [{ id: "q3", op: "mark", groups: [{ ids: ["x-unknown", symIds[0]], style: "cause" }], dim_others: true }] });
  t("표시(정리): 미확인 자리표는 표시 색으로 다시 칠하지 않고 위 층에 그대로", !!core.topG.querySelector('rect[data-id="x-unknown"]') && !marksG.querySelector("rect[stroke-dasharray='4 3']") && core.topG.style.display === "");
  const veil = marksG.querySelector("rect[fill-opacity]");
  t("정리 보기의 흐림막은 옅게(원본 보기의 84%보다 낮음)", !!veil && +veil.getAttribute("fill-opacity") <= 0.55 && +veil.getAttribute("fill-opacity") > 0.2, veil && veil.getAttribute("fill-opacity"));
  const near = items.filter((i) => i.layer === "symbol" && i.kind && symbols[i.kind] && !symbols[i.kind].junction)[0];
  core.update({ marks: [{ id: "q4", op: "path", steps: [near, near, near, near].map((n) => ({ id: n.id, flow: null })), style: "path", numbered: true }] });
  const circles = [...marksG.querySelectorAll("rect[rx]")].map((r) => r.getAttribute("x") + "," + r.getAttribute("y"));
  t("같은 자리의 단계 번호 원은 옆으로 비켜 겹치지 않음", new Set(circles).size === circles.length && circles.length >= 4, circles.join(" "));
  core.update({ marks: [] });

  // ---- 글자: 화면 픽셀 하한, 겹침 숨김, 설비 태그는 설비 옆
  const lt = [...core.cleanG.querySelectorAll("text")].filter((x) => x.style.display !== "none" && x.getAttribute("font-size"));
  const minOk = lt.filter((x) => +x.getAttribute("font-size") * core.view.k >= 10.9 || +x.getAttribute("font-size") <= 9).length;
  t("맞춤 배율에서 보이는 태그·번호 글자는 화면에서 11px 이상(원 안 글자는 따로)", lt.length >= 10 && minOk === lt.length, minOk + "/" + lt.length + " k=" + core.view.k.toFixed(2));
  const eq = items.find((i) => i.layer === "symbol" && i.category === "equipment" && i.tag && i.kind === "reactor_vessel");
  const eqText = [...core.cleanG.querySelectorAll("text")].find((x) => x.textContent === eq.tag);
  t("설비 태그는 설비 바로 옆(오른쪽)에 있음", !!eqText && +eqText.getAttribute("x") >= eq.bbox[2] && +eqText.getAttribute("x") <= eq.bbox[2] + 10 && +eqText.getAttribute("y") >= eq.bbox[1] && +eqText.getAttribute("y") <= eq.bbox[1] + 40, eqText && eqText.getAttribute("x") + "," + eqText.getAttribute("y") + " bbox " + eq.bbox.map(Math.round));
  const L = (o) => Object.assign({ x: 0, y: 10, text: "X", anchor: "start", size: 9, rotate: 0, pri: 0 }, o);
  const layout = CV.layoutLabels([L({ text: "AAAAAAAA", owner: "a" }), L({ x: 5, text: "BBBBBBBB", pri: 1, owner: "b" }), L({ x: 5, text: "태그 없음", size: 7, pri: 9, always: true, owner: "c" }), L({ x: 200, text: "작게", pri: 2, owner: "d" })], 1, []);
  t("글자 자리: 먼저 자리를 잡은 글자가 이기고 겹친 것은 숨김, 늘 보이는 글자는 남음", layout[0].visible && !layout[1].visible && layout[2].visible && layout[3].visible, JSON.stringify(layout.map((l) => l.visible)));
  t("글자 자리: 작게 보일수록 화면 하한(11px)으로 키움", CV.layoutLabels([L({})], 0.5, [])[0].size === 22 && CV.layoutLabels([L({})], 3, [])[0].size === 9);
  const cond = [L({ size: 6, fixed: true, showFrom: 1 }), L({ hideFrom: 1 })];
  t("글자 자리: 확대 값 조건(원 안 글자는 크게 보일 때만, 옆 글자는 작게 보일 때만)", CV.layoutLabels(cond, 0.5, []).map((l) => l.visible).join() === "false,true" && CV.layoutLabels(cond, 2, []).map((l) => l.visible).join() === "true,false");

  // ---- 연결점 잇기: 그래프에서 실제로 이어진 끝만, 8 단위 안만
  const gapSheet = { graph_id: "gap", width: 400, height: 200, svg: "", links: [], items: [
    { id: "v1", layer: "symbol", kind: "manual_valve", category: "valve", tag: "V1", bbox: [100, 80, 150, 110], unknown: false },
    { id: "pa", layer: "pipe", kind: "physical_connection", polyline: [[40, 95], [94, 95]], bbox: [40, 95, 94, 95] },
    { id: "pb", layer: "pipe", kind: "physical_connection", polyline: [[210, 95], [165, 95]], bbox: [165, 95, 210, 95] },
    { id: "pc", layer: "pipe", kind: "physical_connection", polyline: [[40, 60], [90, 60]], bbox: [40, 60, 90, 60] }] };
  const gapClean = { source_format: "drawio", unconfirmed: [], counts: { total: 0 }, text_items: [], leftovers: { counted: false, n: 0, items: [] }, items: {
    v1: { orient: { rot: 0, flip_h: false, flip_v: false, basis: "none" }, review: "script" },
    pa: { line_type: "process", flow: null, ends: [{ end: "source", point: [40, 95], status: "open", node: null }, { end: "target", point: [94, 95], status: "connected", node: "v1" }] },
    pb: { line_type: "process", flow: null, ends: [{ end: "source", point: [210, 95], status: "open", node: null }, { end: "target", point: [165, 95], status: "connected", node: "v1" }] },
    pc: { line_type: "process", flow: null, ends: [{ end: "source", point: [40, 60], status: "open", node: null }, { end: "target", point: [90, 60], status: "open", node: null }] } } };
  const gh = mount();
  const gc = new SheetCore(gh, {});
  gc.setData(gapSheet); await sleep(80);
  gc.update({ clean: gapClean, symbols, view: "clean" });
  const stubs = [...gc.cleanG.querySelectorAll("line")].filter((l) => !l.getAttribute("stroke-dasharray") && +l.getAttribute("x1") === 100 && +l.getAttribute("x2") === 94);
  t("연결점 잇기: 이어진 끝이 4~8 단위 떨어져 있으면 짧은 선으로 잇는다", stubs.length === 1, stubs.length);
  const ticks = [...gc.topG.querySelectorAll("line")].filter((l) => l.getAttribute("stroke").includes("warn"));
  t("연결점이 8 단위를 넘게 떨어지면 잇지 않고 호박색 눈금(port_gap), 열린 끝은 빈 원", ticks.length === 1 && gc.topG.querySelectorAll('circle[r="3"]').length === 4, ticks.length + " / 열린 끝 " + gc.topG.querySelectorAll('circle[r="3"]').length);
  gc.destroy(); gh.remove();

  // ---- 겹쳐 보기: 원본 30%, 원본에 남은 것(엔진이 센 읽은 방법만)
  core.update({ view: "clean", overlays: { original: true, leftovers: false } });
  t("원본 겹쳐 보기: 정리 위에 원본 그림이 30%로 얹힘", core.ghost.style.display === "" && core.ghost.style.opacity === "0.3" && core.ghost.getAttribute("href") === data.sheet.svg);
  core.update({ overlays: { original: false, leftovers: true } });
  const lo = data.clean.leftovers;
  t("원본에 남은 것 겹치기: 센 읽은 방법에서만 호박색 상자로", core.ghost.style.display === "none" && (lo.counted ? core.leftG.querySelectorAll("rect").length === lo.items.filter((i) => i.bbox).length : core.leftG.style.display === "none"), JSON.stringify({ counted: lo.counted, n: lo.n }));
  core.update({ overlays: { original: false, leftovers: false } });

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
