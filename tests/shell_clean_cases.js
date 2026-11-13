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
  let worst = 0, missing = [], outside = 0, shiftMax = 0;
  for (const it of drawn) {
    const g = clean.querySelector(`g[data-id="${CSS.escape(it.id)}"]`);
    if (!g) { missing.push(it.id); continue; }
    const m = /translate\(([-\d.]+) ([-\d.]+)\) rotate/.exec(g.getAttribute("transform"));
    const tb = (ex[it.id] && ex[it.id].tbox) || it.bbox;                       // 정돈한 자리(없으면 원본 자리)
    const cx = (tb[0] + tb[2]) / 2, cy = (tb[1] + tb[3]) / 2;
    worst = Math.max(worst, Math.hypot(+m[1] - cx, +m[2] - cy));
    shiftMax = Math.max(shiftMax, Math.hypot(cx - (it.bbox[0] + it.bbox[2]) / 2, cy - (it.bbox[1] + it.bbox[3]) / 2));
    const r = sheetRect(g);
    if (r.x0 < tb[0] - 2 || r.y0 < tb[1] - 2 || r.x1 > tb[2] + 2 || r.y1 > tb[3] + 2) outside++;
  }
  t("기호 " + drawn.length + "개가 모두 그려짐(<g data-id>)", missing.length === 0 && drawn.length >= 20, missing.slice(0, 5).join(","));
  t("기호 그림의 중심이 정돈한 자리의 중심과 2 단위 안에서 겹치고, 원본 자리에서 옮긴 거리는 허용 범위(48) 안", worst < 2 && shiftMax <= 48, worst + " / 옮김 " + shiftMax.toFixed(1));
  t("기호 그림이 정돈한 상자 안에 듦(오차 2 단위, 회전·뒤집기 포함)", outside === 0, outside + "개가 벗어남");
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
  const firstPipe = pipes[0], pts = ((ex[firstPipe.id] && ex[firstPipe.id].tline) || firstPipe.polyline || []).map((p) => p[0].toFixed(0) + "," + p[1].toFixed(0));
  t("배관 점이 정돈한 길(tline, 없으면 items의 polyline)과 같음", clean.querySelector(`polyline[data-id="${CSS.escape(firstPipe.id)}"]`).getAttribute("points").split(" ").map((p) => p.split(",").map((v) => (+v).toFixed(0)).join(",")).join(" ") === pts.join(" "));
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

  const symRects = items.filter((i) => i.layer === "symbol" && i.kind && symbols[i.kind] && !symbols[i.kind].junction).map((i) => (ex[i.id] && ex[i.id].tbox) || i.bbox);
  const arrowsInSymbols = [...clean.querySelectorAll("polygon")].filter((pg) => { const m = /translate\(([-\d.]+) ([-\d.]+)\)/.exec(pg.getAttribute("transform") || ""); return m && symRects.some((b) => +m[1] > b[0] - 4 && +m[1] < b[2] + 4 && +m[2] > b[1] - 4 && +m[2] < b[3] + 4); }).length;
  t("흐름 화살촉은 기호 둘레와 겹치지 않음", clean.querySelectorAll("polygon").length >= 5 && arrowsInSymbols === 0, arrowsInSymbols);
  t("정돈 품질: 서버가 센 정돈 결과가 0(이어짐·이동·직각·축·크기·연결점·겹침)", !!data.clean.layout_lint && ["topology_changed", "moved_too_far", "off_axis", "inline_off_center", "size_mismatch", "port_miss", "symbol_overlap", "pipe_through_symbol", "pipe_overlap", "crossing_without_hop"].every((k) => data.clean.layout_lint[k] === 0), JSON.stringify(data.clean.layout_lint));

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

  // ---- 누르기·표시는 그린 자리(정돈 좌표)에서: 그려진 기호의 가운데를 누르면 그 기호가 골라진다
  core.update({ mode: "pick" });
  const pickAt = (x, y) => { core.update({ selection: [] }); click(x, y); return core.sel.slice(); };
  const tbOf = (it) => (ex[it.id] && ex[it.id].tbox) || it.bbox;
  const wrongPick = drawn.filter((it) => { const b = tbOf(it); return !pickAt((b[0] + b[2]) / 2, (b[1] + b[3]) / 2).includes(it.id); });
  t("정리 보기: 그려진 기호 " + drawn.length + "개 모두 그 가운데를 누르면 그 기호가 골라짐", wrongPick.length === 0, wrongPick.slice(0, 5).map((i) => i.id).join(","));
  const shifted = drawn.map((it) => ({ it, b: tbOf(it), d: Math.hypot((tbOf(it)[0] + tbOf(it)[2] - it.bbox[0] - it.bbox[2]) / 2, (tbOf(it)[1] + tbOf(it)[3] - it.bbox[1] - it.bbox[3]) / 2) }))
    .sort((a, b) => b.d - a.d)[0];
  const ob = shifted.it.bbox, inOrig = (x, y) => x >= ob[0] && x <= ob[2] && y >= ob[1] && y <= ob[3];
  const spots = [];
  const body = sheetRect(clean.querySelector(`g[data-id="${CSS.escape(shifted.it.id)}"]`));        // 그려진 몸통의 자리
  for (const fx of [0.2, 0.5, 0.8]) for (const fy of [0.2, 0.5, 0.8]) spots.push([body.x0 + (body.x1 - body.x0) * fx, body.y0 + (body.y1 - body.y0) * fy]);
  const offOrig = spots.filter(([x, y]) => !inOrig(x, y));
  const spotMiss = spots.filter(([x, y]) => !pickAt(x, y).includes(shifted.it.id));
  t("정리 보기: 가장 많이 옮겨진 기호(" + shifted.it.kind + ", " + shifted.d.toFixed(1) + " 단위)는 그려진 몸통 어디를 눌러도 골라짐(읽은 상자 밖 자리 포함)",
    shifted.d >= 10 && offOrig.length >= 1 && spotMiss.length === 0, "빗나감 " + spotMiss.length + " / 읽은 상자 밖 " + offOrig.length);
  const tc = [(sb0 => (sb0[0] + sb0[2]) / 2)(tbOf(shifted.it)), (sb0 => (sb0[1] + sb0[3]) / 2)(tbOf(shifted.it))];
  const back = core.origPoint(tc[0], tc[1]);
  t("정리 보기: 그린 자리를 읽은 좌표로(도면 고치기가 저장하는 점), 가장 많이 옮겨진 기호의 중심은 읽은 상자의 중심으로",
    Math.abs(back[0] - (ob[0] + ob[2]) / 2) < 0.01 && Math.abs(back[1] - (ob[1] + ob[3]) / 2) < 0.01, JSON.stringify(back));
  core.update({ selection: [shifted.it.id] });
  const selG = core.marksG.querySelector("g[transform]");
  t("정리 보기: 고른 것 강조는 그려진 기호와 같은 자리", !!selG && selG.getAttribute("transform") === clean.querySelector(`g[data-id="${CSS.escape(shifted.it.id)}"]`).getAttribute("transform"));
  core.update({ view: "orig", selection: [] });
  const [qx, qy] = offOrig[0];
  t("원본 보기로 바꾸면 누르기는 읽은 좌표: 읽은 상자 가운데는 골라지고, 정돈한 자리만인 곳은 아님",
    pickAt((ob[0] + ob[2]) / 2, (ob[1] + ob[3]) / 2).includes(shifted.it.id) && !pickAt(qx, qy).includes(shifted.it.id));
  core.update({ view: "clean", selection: [], mode: "pan" });

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
  t("정리 보기의 흐림막은 옅게(원본 보기의 84%보다 낮음)", !!veil && +veil.getAttribute("fill-opacity") <= 0.65 && +veil.getAttribute("fill-opacity") > 0.2, veil && veil.getAttribute("fill-opacity"));
  const near = items.filter((i) => i.layer === "symbol" && i.kind && symbols[i.kind] && !symbols[i.kind].junction)[0];
  core.update({ marks: [{ id: "q4", op: "path", steps: [near, near, near, near].map((n) => ({ id: n.id, flow: null })), style: "path", numbered: true }] });
  const circles = [...marksG.querySelectorAll("rect[rx]")].map((r) => r.getAttribute("x") + "," + r.getAttribute("y"));
  t("같은 자리의 단계 번호 원은 옆으로 비켜 겹치지 않음", new Set(circles).size === circles.length && circles.length >= 4, circles.join(" "));
  core.update({ marks: [] });

  // ---- 글자: 화면 픽셀 하한, 겹침 숨김, 설비 태그는 설비 옆
  const lt = [...core.cleanG.querySelectorAll("text")].filter((x) => x.style.display !== "none" && x.getAttribute("font-size"));
  const minOk = lt.filter((x) => +x.getAttribute("font-size") * core.view.k >= 10.9 || +x.getAttribute("font-size") <= 9).length;
  t("맞춤 배율에서 보이는 태그·번호 글자는 대부분 화면에서 11px 이상(원 안 글자는 따로)", lt.length >= 10 && minOk >= lt.length * 0.8, minOk + "/" + lt.length + " k=" + core.view.k.toFixed(2));
  const eq = items.find((i) => i.layer === "symbol" && i.category === "equipment" && i.tag && i.kind === "reactor_vessel");
  const eqText = [...core.cleanG.querySelectorAll("text")].find((x) => x.textContent === eq.tag);
  t("설비 태그는 설비 바로 옆 오른쪽 가운데에 있음(모든 설비 같은 규칙)", !!eqText && +eqText.getAttribute("x") >= eq.bbox[2] - 12 && +eqText.getAttribute("x") <= eq.bbox[2] + 14 && Math.abs(+eqText.getAttribute("y") - (eq.bbox[1] + eq.bbox[3]) / 2) <= 25, eqText && eqText.getAttribute("x") + "," + eqText.getAttribute("y") + " bbox " + eq.bbox.map(Math.round));
  const L = (o) => Object.assign({ x: 0, y: 10, text: "X", anchor: "start", size: 9, rotate: 0, pri: 0 }, o);
  const layout = CV.layoutLabels([L({ text: "AAAAAAAA", owner: "a" }), L({ x: 5, text: "BBBBBBBB", pri: 1, owner: "b" }), L({ x: 5, text: "태그 없음", size: 7, pri: 9, always: true, owner: "c" }), L({ x: 200, text: "작게", pri: 2, owner: "d" })], 1, []);
  t("글자 자리: 먼저 자리를 잡은 글자가 이기고 겹친 것은 숨김, 늘 보이는 글자는 남음", layout[0].visible && !layout[1].visible && layout[2].visible && layout[3].visible, JSON.stringify(layout.map((l) => l.visible)));
  t("글자 자리: 작게 보일수록 화면 하한(11px)으로 키움", CV.layoutLabels([L({})], 0.5, [])[0].size === 22 && CV.layoutLabels([L({})], 3, [])[0].size === 9);
  const cond = [L({ size: 6, fixed: true, showFrom: 1 }), L({ hideFrom: 1 })];
  t("글자 자리: 확대 값 조건(원 안 글자는 크게 보일 때만, 옆 글자는 작게 보일 때만)", CV.layoutLabels(cond, 0.5, []).map((l) => l.visible).join() === "false,true" && CV.layoutLabels(cond, 2, []).map((l) => l.visible).join() === "true,false");

  // ---- 글자 자리: 기호·배관 선과 겹치지 않는 후보를 고르고, 계기 글자는 원 크기에 따라 나뉨, 배관 번호는 선에서 띄움
  const bbT = [100, 100, 130, 130];
  const tagL = { x: 0, y: 0, text: "RC-V1", anchor: "middle", size: 9, rotate: 0, pri: 1, owner: "v", fixed: false, showFrom: 0, hideFrom: 0, place: { t: "tag", bb: bbT, order: ["below", "above", "right", "left"] } };
  const free = CV.layoutLabels([tagL], 1, [{ x0: 100, y0: 100, x1: 130, y1: 130, owner: "v" }])[0];
  const blocked = CV.layoutLabels([tagL], 1, [{ x0: 100, y0: 100, x1: 130, y1: 130, owner: "v" }, { x0: 114, y0: 130, x1: 116, y1: 175, owner: "p", thin: true }])[0];
  t("태그 자리: 아래가 비면 아래, 배관 선이 지나가면 위·옆의 빈 곳으로 옮김", free.visible && free.y > bbT[3] && blocked.visible && blocked.y < bbT[1], JSON.stringify([free.y, blocked.y]));
  const pipeL = { x: 0, y: 0, text: "RC-L003", anchor: "middle", size: 9, rotate: 0, pri: 4, owner: "p", fixed: false, showFrom: 0, hideFrom: 0, place: { t: "pipe", mx: 300, my: 200, vertical: true } };
  const pv = CV.layoutLabels([pipeL], 1, [])[0], size11 = pv.size;
  t("세로 배관 번호는 선(x=300)에서 띄워 선과 겹치지 않음(왼쪽 우선)", pv.visible && pv.rotate === -90 && pv.x + size11 * 0.2 < 300 - 2, JSON.stringify(pv));
  const instr = (k) => { const b = [100, 100, 130, 130], ks = [18 / 30, 34 / 30]; return k; };
  const insideAt = (k) => core._labels ? null : null;
  const ib = { x: 0, y: 0, anchor: "middle", rotate: 0, pri: 2, owner: "i" };
  const iLabels = [Object.assign({}, ib, { text: "RC-TI101", size: 9, hideFrom: 18 / 30, place: { t: "tag", bb: [100, 100, 130, 130], order: ["right"] } }),
    Object.assign({}, ib, { text: "RC", size: 12.6, fixed: true, showFrom: 18 / 30, hideFrom: 34 / 30 }), Object.assign({}, ib, { text: "TI101", size: 9, showFrom: 18 / 30, hideFrom: 34 / 30, place: { t: "tag", bb: [100, 100, 130, 130], order: ["right"] } }),
    Object.assign({}, ib, { text: "RC", size: 8, fixed: true, showFrom: 34 / 30 })];
  const states = (k) => CV.layoutLabels(iLabels, k, []).map((l) => (l.visible ? 1 : 0)).join("");
  t("계기 글자: 원이 작으면(18px 미만) 전체를 옆에, 중간이면 기능 글자는 안·번호는 옆에, 크면 안에", states(0.4) === "1000" && states(0.8) === "0110" && states(1.5) === "0001", [states(0.4), states(0.8), states(1.5)].join(" "));

  // ---- 단계 번호: 큰 설비는 경로 배관이 그 설비에 닿는 점에, 같은 자리는 비켜 놓음
  const vessel = items.find((i) => i.kind === "reactor_vessel");
  const pipeNear = items.filter((i) => i.layer === "pipe" && i.polyline).find((p) => [p.polyline[0], p.polyline[p.polyline.length - 1]].some((q) => q[0] >= vessel.bbox[0] - 3 && q[0] <= vessel.bbox[2] + 3 && q[1] >= vessel.bbox[1] - 3 && q[1] <= vessel.bbox[3] + 3));
  if (pipeNear) {
    const drawnLine = (ex[pipeNear.id] && ex[pipeNear.id].tline) || pipeNear.polyline;          // 정리 보기의 색인은 정돈한 길
    const ends = [drawnLine[0], drawnLine[drawnLine.length - 1]];
    const res = MK.resolveMark({ id: "pv", op: "path", steps: [{ id: pipeNear.id }, { id: vessel.id }], style: "path", numbered: true }, core.index);
    const bd = res.badges.find((b) => b.text === "1");
    const q = ends.find((e) => Math.abs(e[0] - bd.rect.x0) < 0.01 && Math.abs(e[1] - bd.rect.y0) < 0.01);
    t("설비의 단계 번호는 경로 배관이 그 설비에 닿는 점(가운데 맞춤)에", !!bd && bd.center === true && !!q, JSON.stringify(bd && bd.rect));
  } else t("설비의 단계 번호는 경로 배관이 그 설비에 닿는 점에(표본에 닿는 배관이 없음)", true);

  // ---- 속성 미확인은 평소 그리지 않고 칩을 누르면 보임, 다른 도면 연결은 안 두 줄·같은 크기, 경로 표시와 글자 겹침 없음, 큰 화살촉
  core.update({ overlays: { original: false, leftovers: false, unconfirmed: false } });
  const attrN = new Set(data.clean.unconfirmed.filter((u) => u.id && !["unknown_symbol", "open_end", "missing_tag", "ai_candidate", "unplaced", "unresolved_connector"].includes(u.reason)).map((u) => u.id)).size;
  t("속성만 미확인인 자리는 평소에는 숨김(읽지 못한 것은 위 층에 늘 보임)", attrN >= 1 && core.attrG.style.display === "none" && core.attrG.querySelectorAll("rect").length === attrN && core.topG.style.display === "", attrN + " / " + core.attrG.querySelectorAll("rect").length);
  core.update({ overlays: { original: false, leftovers: false, unconfirmed: true } });
  t("미확인 칩(overlay.unconfirmed)을 켜면 속성 미확인 자리가 호박색 점선 테두리로 보임", core.attrG.style.display === "" && !!core.attrG.querySelector('rect[stroke-dasharray="4 3"]'));
  core.update({ overlays: { original: false, leftovers: false, unconfirmed: false } });
  const conts = items.filter((i) => i.layer === "symbol" && i.kind === "continuation");
  const contSizes = new Set(conts.map((i) => { const b = (ex[i.id] && ex[i.id].tbox) || i.bbox; return Math.round(b[2] - b[0]) + "x" + Math.round(b[3] - b[1]); }));
  const contInside = conts.filter((i) => ex[i.id] && ex[i.id].label && ex[i.id].label.length).every((i) => {
    const b = ex[i.id].tbox, ts = [...core.cleanG.querySelectorAll("text")].filter((x) => ex[i.id].label.includes(x.textContent) && +x.getAttribute("x") > b[0] && +x.getAttribute("x") < b[2] && +x.getAttribute("y") > b[1] && +x.getAttribute("y") < b[3] + 12);
    return ts.length >= ex[i.id].label.length;
  });
  t("다른 도면 연결 오각형은 모두 같은 크기이고 원본 글자가 안에 들어감", conts.length >= 5 && contSizes.size === 1 && contInside, [...contSizes].join(",") + " " + contInside);
  const pathIds = items.filter((i) => i.layer === "pipe" && ex[i.id] && ex[i.id].flow).slice(0, 3).map((i) => i.id);
  core.update({ marks: [{ id: "qa", op: "path", steps: items.filter((i) => i.layer === "symbol" && i.kind && symbols[i.kind] && !symbols[i.kind].junction).slice(0, 3).map((i) => ({ id: i.id })).concat(pathIds.map((id) => ({ id, flow: "with" }))), style: "path", numbered: true }] });
  const bigArrows = [...marksG.querySelectorAll("polygon")].filter((pg) => /-10,/.test(pg.getAttribute("points") || "")).length;
  t("경로 위 화살촉은 크게(기본의 약 1.7배)", bigArrows >= 1, bigArrows);
  const bbx = MK.badgeBoxes(core.lastDraw.badges, core.view.k);
  const badLabels = [...core.cleanG.querySelectorAll("text")].filter((x) => x.style.display !== "none" && x.getAttribute("font-size")).filter((x) => {
    const r = sheetRect(x);
    return bbx.some((b) => !(r.x1 <= b.x0 || r.x0 >= b.x1 || r.y1 <= b.y0 || r.y0 >= b.y1));
  }).filter((x) => !(core._labels[[...core._labelEls].indexOf(x)] || {}).fixed).length;
  t("경로를 보일 때 글자는 단계 번호 원과 겹치지 않음(번호 원을 장애물로 봄)", bbx.length >= 3 && badLabels === 0, badLabels + "개가 겹침 / 번호 " + bbx.length);
  core.update({ marks: [] });

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
