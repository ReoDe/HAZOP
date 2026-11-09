"""APR1400 DCD 계통 흐름도 점수판과 톱니 검사. 원본 PDF는 저장소에 없으므로 입력 폴더를 인자로 받는다.

  python scripts/check_apr1400.py --input-dir <도면별 폴더> [--catalog <도면목록.csv>] [--jobs 8]
  python scripts/check_apr1400.py --input-dir <…> --update     # 점수 기준값을 지금 결과로 바꿈(이유는 커밋 메시지에)
  python scripts/check_apr1400.py --input-dir <…> --pages 6,28 # 몇 쪽만(점수 비교 없이 보기만)

쪽마다 pdf_vector로 추출하고 그래프를 만든 뒤, 같은 PDF의 텍스트 층에서 센 기준과 견준다(대리 지표, 독립 정답 아님).
- 재현율: tag_exact(계기 원 글자와 정확히 같은 태그가 그 원 위치의 노드에 붙은 수), connectors_detected(연결 표기
  위치에 연결점 노드를 만든 수), paired(프로젝트 그래프에서 짝지은 연결 수)
- 정밀도(오류 수): tag_not_in_text(글자에 없는 태그. 계기 글자로 만든 태그(근거 isa_label…)는 그 노드 상자 안에 찍힌
  위아래 두 줄을 이은 글자와 같아야 하고, 나머지 태그는 그 쪽 텍스트 층 낱말에 있어야 한다),
  connector_bad_target(짝지은 글자와 계통이 다르거나, 짝이 없는데 계통을 단 연결점)
독립 정답(tests/fixtures/apr1400/answer_key/*.json, 렌더한 그림을 눈으로 읽어 만든 정답, tests/fixtures/apr1400/SOURCE.md)이 있는 쪽은 정답 대비 값도 낸다.
톱니: 재현율 값은 기준값보다 낮아지면, 오류 값은 높아지면 실패(종료 코드 1). 합계·쪽마다·정답 쪽마다 모두 본다.
쪽 수·계기 원 수·연결 표기 수(입력과 대리 지표)가 기준값과 다르면 비교하지 않고 실패한다.
"""

import argparse
import csv
import glob
import json
import multiprocessing
import os
import re
import shutil
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

SCORE = os.path.join(REPO_ROOT, "tests", "baselines", "apr1400_score.json")
ANSWER_KEY = os.path.join(REPO_ROOT, "tests", "fixtures", "apr1400", "answer_key")
PAIR_KEY = os.path.join(REPO_ROOT, "tests", "fixtures", "apr1400", "pairs_key.json")
HIGHER = ("tag_exact", "connectors_detected", "paired", "pair_key_hit")
LOWER = ("tag_not_in_text", "connector_bad_target", "pair_key_wrong")
PAGE_HIGHER = ("tag_exact", "connectors_detected")
PAGE_LOWER = ("tag_not_in_text", "connector_bad_target")
OFFPAGE_RE = re.compile(r"^(?:[\d/.]+\")?([A-Z]{2,3}):[A-Z0-9]")  # 'CV:CHARGING'. 배관 크기가 붙은 '4"CV:IRWST'도
ISA_LETTERS_RE = re.compile(r"^[A-Z]{2,5}$")
LOOP_NO_RE = re.compile(r"^\d{1,4}[A-Z]?$")  # 루프 번호는 한 자리도 있음(TEW / 8, PDT / 1D)
NEAR = 3.0        # 계기 원 글자 중심이 노드 상자 안(여유 pt)
CONN_NEAR = 12.0  # 연결 표기 글자 중심이 연결점 노드 상자 안(여유 pt)
LABEL_REACH = 30.0  # 여러 줄 연결 표기의 첫 줄이 화살표에서 떨어질 수 있는 거리(글자 쓰는 쪽, pt)
SPAN_SLACK = 6.0  # 연결 표기 글자 가운데가 화살표 길이 방향 범위를 벗어나도 되는 거리(pt)


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def default_input_dir():
    from hazop import paths
    return paths.folder("APR1400", "도면별")


# ---------------------------------------------------------------- 텍스트 층 기준(대리 지표)

def symbol_boxes(page):
    """계기 기호 후보: 작은 닫힌 곡선(원·비석 모양), 폭 8~30pt·높이/폭 0.8~1.45. 같은 자리에 두 번 그린 것은 하나로."""
    out = []
    for c in page.curves:
        w, h = c["x1"] - c["x0"], c["bottom"] - c["top"]
        if 8 <= w <= 30 and 8 <= h <= 34 and 0.8 <= h / w <= 1.45:
            box = (c["x0"], c["top"], c["x1"], c["bottom"])
            if not any(abs(box[0] - b[0]) < 1 and abs(box[1] - b[1]) < 1 for b in out):
                out.append(box)
    return out


def text_layer(path):
    """→ {"bubbles": [(문자, 번호, 중심 x, 중심 y)], "offpage": [(글자, 계통, x, y)], "tokens": set(norm),
    "chars": [(글자, 중심 x, 중심 y, 위 끝, x0, x1)]}.
    계기 원: 작은 닫힌 곡선(symbol_boxes) 안에 든 글자만 줄로 묶어, 기능 문자 줄 바로 아래 루프 번호 줄이 있는 것.
    (글자를 한 자씩 따로 놓은 도면은 pdfplumber 낱말이 'P'·'D'·'IS'로 쪼개지므로 낱말 대신 글자를 묶는다.)
    연결 표기: 'CV:CHARGING'처럼 계통 약어로 시작하는 낱말(회전 글자는 char_dir_rotated='btt'로 읽음)."""
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(char_dir_rotated="btt")
        chars = [(c["text"], (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2, c["top"], c["x0"], c["x1"])
                 for c in page.chars if c["upright"] and c["text"].strip()]
        # 90° 돌린 글자(아래→위로 읽음)는 읽는 방향이 가로가 되게 좌표를 돌려 둔다: x' = -y, y' = x
        turned = [(c["text"], -(c["top"] + c["bottom"]) / 2, (c["x0"] + c["x1"]) / 2, c["x0"], -c["bottom"], -c["top"])
                  for c in page.chars if not c["upright"] and c["text"].strip() and c["matrix"][1] > 0]
        # 위→아래로 읽는 글자: x' = y, y' = -x
        down = [(c["text"], (c["top"] + c["bottom"]) / 2, -(c["x0"] + c["x1"]) / 2, -c["x1"], c["top"], c["bottom"])
                for c in page.chars if not c["upright"] and c["text"].strip() and c["matrix"][1] < 0]
        boxes = symbol_boxes(page)
    bubbles = []
    for b in boxes:
        lines = box_lines(chars, b)
        i = next((i for i, t in enumerate(lines) if ISA_LETTERS_RE.match(t)), None)
        if i is not None and i + 1 < len(lines) and LOOP_NO_RE.match(lines[i + 1]):
            bubbles.append((lines[i], lines[i + 1], (b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
    labels = join_fragments([w for w in words if w["upright"]]) + [w for w in words if not w["upright"]]
    offpage = [(w["text"], OFFPAGE_RE.match(w["text"]).group(1), (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2)
               for w in labels if OFFPAGE_RE.match(w["text"])]
    tokens = {norm(w["text"]) for w in words} | {norm(a + b) for a, b, _, _ in bubbles}
    return {"bubbles": bubbles, "offpage": offpage, "tokens": tokens, "chars": chars, "turned": turned, "down": down}


def join_fragments(words, gap=0.5):
    """글자를 한 자씩 따로 놓은 도면(예: 9.3.2-1 시트 1)에서 pdfplumber가 'R'·'C'·':'·'RC'로 쪼갠 낱말을 다시 잇는다.
    같은 줄(위 끝 0.5pt 안)에서 앞 낱말 끝과 -0.5~gap pt 안에 붙은 것만 잇는다(낱말 사이 띄어쓰기는 약 0.9pt)."""
    out = []
    for w in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        last = next((o for o in reversed(out) if abs(o["top"] - w["top"]) < 0.5 and -0.5 <= w["x0"] - o["x1"] <= gap),
                    None)
        if last is not None:
            last.update(text=last["text"] + w["text"], x1=w["x1"], bottom=max(last["bottom"], w["bottom"]))
        else:
            out.append(dict(w))
    return out


def box_words(chars, box, gap=0.5):
    """상자 안(중심 기준) 글자를 위 끝 1.5pt 안으로 줄을 묶고, 줄 안에서 gap pt 넘게 떨어지거나 위 끝이 0.5pt 넘게
    다른 곳에서 낱말을 나눈다(한 낱말의 글자는 붙어 있고 위 끝이 같다).
    → 줄마다 [(낱말, 중심 x)] (위 줄부터). 기호 상자에 걸친 옆 글자('LL', 'I/')가 태그 글자에 붙지 않게 한다."""
    lines = []
    for c in sorted((c for c in chars if _inside((c[1], c[2]), box)), key=lambda c: c[3]):
        if lines and abs(lines[-1][0][3] - c[3]) < 1.5:
            lines[-1].append(c)
        else:
            lines.append([c])
    out = []
    for line in lines:
        words = []
        for c in sorted(line, key=lambda c: c[4]):
            if words and c[4] - words[-1][-1][5] <= gap and abs(c[3] - words[-1][-1][3]) < 0.5:
                words[-1].append(c)
            else:
                words.append([c])
        out.append([("".join(c[0] for c in w), (w[0][4] + w[-1][5]) / 2) for w in words])
    return out


def box_lines(chars, box):
    """상자 안 글자의 줄마다 이은 글자 목록(위 줄부터). 계기 원 안은 줄마다 낱말 하나라 이것으로 읽는다."""
    return ["".join(t for t, _ in line) for line in box_words(chars, box)]


def tag_in_text(node, tl):
    """태그가 도면에 찍힌 글자와 같은가. 계기 글자로 만든 태그는 노드 상자 안 위아래 두 줄을 이은 글자와 같아야 한다
    (접두를 추정해 붙였거나 기호 밖 번호를 가져온 태그는 틀림). 나머지는 그 쪽 낱말 하나와 같아야 한다."""
    if (node.get("evidence") or {}).get("tag_basis", "").startswith("isa_label"):
        x0, y0, x1, y1 = _box(node, 1.0)
        pairs = set()
        for chars, box in ((tl["chars"], (x0, y0, x1, y1)), (tl.get("turned") or [], (-y1, x0, -y0, x1)),
                           (tl.get("down") or [], (y0, -x1, y1, -x0))):
            lines = box_words(chars, box)
            pairs |= {norm(a + b) for up, down in zip(lines, lines[1:]) for a, ax in up for b, bx in down
                      if abs(ax - bx) < 6}
        return norm(node["tag"]) in pairs
    return norm(node["tag"]) in tl["tokens"]


def _box(node, margin):
    g = node.get("geometry") or {}
    if "x" not in g:
        return None
    return (g["x"] - margin, g["y"] - margin, g["x"] + g["width"] + margin, g["y"] + g["height"] + margin)


def _inside(pt, box):
    return box is not None and box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]


def _dist(pt, node):
    g = node["geometry"]
    return abs(g["x"] + g["width"] / 2 - pt[0]) + abs(g["y"] + g["height"] / 2 - pt[1])


def match_one_to_one(points, nodes, ok, margin):
    """points [(키, x, y)]마다 상자(+margin) 안에 들고 ok(키, 노드)인 노드 중 가장 가까운 것을 짝짓는다.
    노드 하나는 한 번만 쓴다(큰 노드 하나가 여러 표시를 덮어 점수를 부풀리지 않게). → [(키, 노드)]"""
    used, pairs = set(), []
    for key, x, y in points:
        cand = [n for n in nodes if n["local_id"] not in used and _inside((x, y), _box(n, margin)) and ok(key, n)]
        if cand:
            n = min(cand, key=lambda n: _dist((x, y), n))
            used.add(n["local_id"])
            pairs.append((key, n))
    return pairs


def match_connectors(points, conts):
    """연결 표기 글자와 연결점 노드를 위치만으로 1:1로 짝짓는다(계통은 보지 않는다. 계통은 짝을 정한 뒤 따로 맞춘다).
    DCD는 가로 화살표의 글자를 화살표 위에, 세로 화살표의 글자를 왼쪽에 쓴다. 그래서 글자 아래(가로)·오른쪽(세로)에 있는
    화살표를 먼저 고르고, 그런 화살표가 없을 때만 반대쪽을 고른다. 화살표가 촘촘히 쌓여 글자 하나가 위아래 화살표에
    똑같이 가까울 때 생기는 오대응을 막는다. 짝은 비용이 작은 것부터 정한다."""
    cand = []
    for i, (code, x, y) in enumerate(points):
        for n in conts:
            g = n["geometry"]
            across = g["width"] >= g["height"]
            # 상자 둘레 CONN_NEAR 안, 또는 글자를 쓰는 쪽(가로 화살표 위·세로 화살표 왼쪽)으로 LABEL_REACH 안(여러 줄 글자)
            reach = ((g["x"] - CONN_NEAR, g["y"] - LABEL_REACH, g["x"] + g["width"] + CONN_NEAR, g["y"]) if across else
                     (g["x"] - LABEL_REACH, g["y"] - CONN_NEAR, g["x"], g["y"] + g["height"] + CONN_NEAR))
            if not (_inside((x, y), _box(n, CONN_NEAR)) or _inside((x, y), reach)):
                continue
            ahead = (g["y"] - y) if across else (g["x"] - x)  # 화살표가 글자 아래·오른쪽이면 ≥ 0
            cost = ahead if ahead >= -2 else 1000 - ahead
            span = (g["x"], g["x"] + g["width"], x) if across else (g["y"], g["y"] + g["height"], y)
            if not span[0] - SPAN_SLACK <= span[2] <= span[1] + SPAN_SLACK:
                continue  # 글자 가운데가 화살표 길이 방향 범위 밖: 옆 화살표(추출 못 했을 수 있음)의 글자다
            cand.append((cost, i, n["local_id"], code, n))
    used_pt, used_node, pairs = set(), set(), []
    for cost, i, nid, code, n in sorted(cand, key=lambda c: c[:3]):
        if i not in used_pt and nid not in used_node:
            used_pt.add(i)
            used_node.add(nid)
            pairs.append((code, n))
    return pairs


def continuation_target(node):
    attrs = node.get("attributes") or {}
    t = attrs.get("to_drawing") or attrs.get("to_system")
    if t:
        return t
    m = OFFPAGE_RE.match((node.get("label_text") or "").strip())
    return m.group(1) if m else None


def score_page(ex, tl):
    nodes = ex["nodes"]
    tagged = [n for n in nodes if n.get("tag")]
    exact = match_one_to_one([(norm(a + b), x, y) for a, b, x, y in tl["bubbles"]], tagged,
                             lambda want, n: norm(n["tag"]) == want, NEAR)
    conts = [n for n in nodes if n.get("kind") == "continuation"]
    pairs = match_connectors([(code, x, y) for _, code, x, y in tl["offpage"]], conts)
    paired_ids = {n["local_id"] for _, n in pairs}
    # 계통을 못 읽은 연결점(None)은 놓친 것이지 틀린 대상이 아니다
    bad = sum(1 for code, n in pairs if continuation_target(n) not in (None, code))
    # 짝이 없는데 계통을 단 연결점: 그 계통 글자는 다른 화살표 몫으로 짝지어졌거나 없는 글자다(이웃 화살표 글자를 가져옴).
    # 상대를 적지 않은 표시(계통 약어 생략, 범례 1.7-1)는 틀린 대상이 아니다. 쌍점 없이 쓴 두 글자 약어('CC / SHEET 4')는
    # 대리 지표의 연결 표기 글자(XX:)에 없어 짝이 안 생기므로 이 벌점에서 뺀다(짝이 생기면 위에서 계통을 맞춘다)
    bad += sum(1 for n in conts if n["local_id"] not in paired_ids and continuation_target(n) is not None
               and ":" in ((n.get("attributes") or {}).get("to_label") or n.get("label_text") or ""))
    return {"bubbles": len(tl["bubbles"]), "offpage_labels": len(tl["offpage"]), "tagged": len(tagged),
            "tag_exact": len(exact), "tag_not_in_text": sum(1 for n in tagged if not tag_in_text(n, tl)),
            "continuations": len(conts), "connectors_detected": len(pairs), "connector_bad_target": bad,
            "unknowns": ex["summary"]["unknowns"], "nodes": len(nodes),
            "unclassified": sum(1 for n in nodes if not n.get("kind"))}


def _center(bbox):
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


def score_against_key(ex, key):
    """독립 정답 대비(한 노드는 한 정답에만): 계기(정답 기호 위치에 같은 글자 태그) · 연결 표시(정답 화살표 근처 연결점)."""
    tagged = [n for n in ex["nodes"] if n.get("tag")]
    conts = [n for n in ex["nodes"] if n.get("kind") == "continuation"]
    inst = match_one_to_one([(norm(i["tag"]),) + _center(i["bbox"]) for i in key["instruments"]], tagged,
                            lambda want, n: norm(n["tag"]) == want, NEAR)
    conn = match_one_to_one([(i["label"],) + _center(i["bbox"]) for i in key["connectors"]], conts,
                            lambda k, n: True, CONN_NEAR)
    return {"instruments": len(key["instruments"]), "instrument_hits": len(inst), "tagged": len(tagged),
            "tagged_correct": len(inst), "connectors": len(key["connectors"]), "connector_hits": len(conn),
            "continuations": len(conts), "continuations_correct": len(conn)}


def proxy_against_key(tl, key):
    """대리 지표가 정답과 얼마나 맞는지. 계기 원은 정답 기호 상자 안에 있고 글자도 같아야 맞은 것으로 센다."""
    inst_ok = sum(1 for a, b, x, y in tl["bubbles"]
                  if any(_inside((x, y), i["bbox"]) and norm(a + b) == norm(i["tag"]) for i in key["instruments"]))
    cboxes = [i["bbox"] for i in key["connectors"]]
    cinside = sum(1 for _, _, x, y in tl["offpage"] if any(_inside((x, y), (b[0] - CONN_NEAR, b[1] - CONN_NEAR,
                                                                           b[2] + CONN_NEAR, b[3] + CONN_NEAR))
                                                          for b in cboxes))
    return {"proxy_bubbles": len(tl["bubbles"]), "proxy_bubbles_in_key": inst_ok,
            "key_instruments": len(key["instruments"]), "proxy_offpage": len(tl["offpage"]),
            "proxy_offpage_in_key": cinside, "key_connectors": len(cboxes)}


# ---------------------------------------------------------------- 쪽 작업(프로세스마다)

def _work(job):
    path, dwg, work_root = job
    os.environ["HAZOP_WORK_ROOT"] = work_root
    from hazop.extract.adapters import pdf_vector
    from hazop.graph import build
    t = time.time()
    try:
        ex = pdf_vector.extract(path, page=0, repo_root=work_root)
        ex["drawing"]["drawing_number"] = dwg
        ex["project_id"] = "APR1400"
        graph = build.build_graph(ex)
        tl = text_layer(path)
        return {"dwg": dwg, "ok": True, "seconds": round(time.time() - t, 1), "ex": ex, "graph": graph, "tl": tl}
    except Exception as exc:  # 한 쪽 실패도 점수(오류 쪽)로 남기고 나머지를 잰다
        return {"dwg": dwg, "ok": False, "seconds": round(time.time() - t, 1), "error": "%s: %s" % (type(exc).__name__, exc)}


def catalog_rows(path):
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def run(input_dir, catalog, jobs, pages=None):
    rows = catalog_rows(catalog)
    if pages:
        rows = [r for r in rows if int(r["순번"]) in pages]
    missing = [r["개별파일"] for r in rows if not os.path.isfile(os.path.join(input_dir, r["개별파일"]))]
    if missing:
        raise SystemExit("입력 PDF 없음 %d개(예: %s)" % (len(missing), missing[0]))
    work = tempfile.mkdtemp(prefix="hazop_apr1400_")
    todo = [(os.path.join(input_dir, r["개별파일"]), "%s-S%s" % (r["그림번호"], r["시트"]), work) for r in rows]
    try:
        pool = multiprocessing.Pool(jobs)
        try:
            done = pool.map(_work, todo, chunksize=1)
        finally:
            pool.close()
            pool.join()  # 작업 프로세스가 임시 폴더 파일을 놓은 뒤에 지운다(Windows 파일 잠금)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    per_page = []
    for r, d in zip(rows, done):
        row = {"seq": int(r["순번"]), "drawing": d["dwg"], "ok": d["ok"], "seconds": d["seconds"],
               "error": d.get("error", "")}
        if d["ok"]:
            row.update(score_page(d["ex"], d["tl"]))
        per_page.append(row)
    from hazop.graph import project
    graphs = [d["graph"] for d in done if d["ok"]]
    codes = project.load_system_codes(os.path.join(os.path.dirname(input_dir), project.SYSTEM_CODES_FILE))
    built = project.build("APR1400", graphs, (), codes) if graphs else None
    pg = project.summary(built) if built else {"linked": 0}
    totals = {k: sum(p.get(k, 0) for p in per_page) for k in
              ("bubbles", "offpage_labels", "tagged", "tag_exact", "tag_not_in_text", "continuations",
               "connectors_detected", "connector_bad_target", "unknowns", "nodes", "unclassified")}
    totals.update(pages=len(per_page), failed_pages=sum(1 for p in per_page if not p["ok"]), paired=pg["linked"])
    totals.update(score_pairs(built, {d["dwg"]: d for d in done if d["ok"]}))
    totals["pair_candidates"] = sum(1 for l in (built or {}).get("sheet_links") or [] if l["reason"] == "system_candidate")
    keyed = {}
    for kp in sorted(glob.glob(os.path.join(ANSWER_KEY, "*.json"))):
        with open(kp, encoding="utf-8") as fh:
            key = json.load(fh)
        for r, d in zip(rows, done):
            if int(r["순번"]) == key["seq"] and d["ok"]:
                keyed[d["dwg"]] = dict(score_against_key(d["ex"], key), **proxy_against_key(d["tl"], key),
                                       proxy=score_page(d["ex"], d["tl"]))
    return {"totals": totals, "answer_key": keyed, "per_page": per_page}


def score_pairs(built, by_dwg):
    """짝 정답(PAIR_KEY, 렌더한 그림을 눈으로 확인한 짝) 대비: 맞게 이은 짝 수와 틀린 짝 수(정답 화살표가 다른 화살표와
    이어짐). 화살표는 그 도면에서 정답 상자 가운데를 품는 연결점 노드로 찾는다."""
    if not os.path.isfile(PAIR_KEY):
        return {}
    with open(PAIR_KEY, encoding="utf-8") as fh:
        key = json.load(fh)
    peer = {}
    for l in (built or {}).get("sheet_links") or []:
        if l["status"] == "linked":
            a, b = (project_ref(l["from"]), project_ref(l["to"]))
            peer[a], peer[b] = b, a

    def ref(end):
        d = by_dwg.get(end["drawing"])
        if d is None:
            return None
        c = _center(end["bbox"])
        hit = [n for n in d["ex"]["nodes"] if n.get("kind") == "continuation" and _inside(c, _box(n, 2.0))]
        return "%s#%s" % (d["graph"]["graph_id"], hit[0]["source_object_id"]) if len(hit) == 1 else None

    hits = wrong = 0
    for p in key["pairs"]:
        a, b = ref(p["a"]), ref(p["b"])
        hits += bool(a and b and peer.get(a) == b)
        wrong += bool((a and peer.get(a) not in (None, b)) or (b and peer.get(b) not in (None, a)))
    return {"pair_key": len(key["pairs"]), "pair_key_hit": hits, "pair_key_wrong": wrong}


def project_ref(end):
    return "%s#%s" % (end["graph_id"], end["source_object_id"] or end["entity_id"])


def ratchet(base, now):
    """기준값(base: {"totals", "answer_key"}) 대비 후퇴 목록. 입력 집합·대리 지표가 바뀌면(쪽·원·연결 표기 수) 비교하지
    않고 실패한다(--update로 기준값을 바꾸고 커밋 메시지에 이유를 적는다)."""
    bt, nt = base["totals"], now["totals"]
    bad = ["입력·대리 지표가 기준값과 다름: %s %s → %s" % (k, bt[k], nt[k])
           for k in ("pages", "bubbles", "offpage_labels") if bt[k] != nt[k]]
    if bad:
        return bad
    bad += ["%s %d → %d (낮아짐)" % (k, bt.get(k, 0), nt.get(k, 0)) for k in HIGHER if nt.get(k, 0) < bt.get(k, 0)]
    bad += ["%s %d → %d (늘어남)" % (k, bt.get(k, 0), nt.get(k, 0)) for k in LOWER + ("failed_pages",)
            if nt.get(k, 0) > bt.get(k, 0)]
    bk, nk = base["answer_key"], now["answer_key"]
    if set(bk) != set(nk):
        return bad + ["정답 쪽 집합이 다름: %s → %s" % (sorted(bk), sorted(nk))]
    for dwg in sorted(bk):
        b, n = bk[dwg], nk[dwg]
        bad += ["정답 %s %s %d → %d (낮아짐)" % (dwg, k, b[k], n[k]) for k in ("instrument_hits", "connector_hits")
                if n[k] < b[k]]
        for k, ok in (("tagged", "tagged_correct"), ("continuations", "continuations_correct")):
            if n[k] - n[ok] > b[k] - b[ok]:
                bad.append("정답 %s 틀린 %s %d → %d (늘어남)" % (dwg, k, b[k] - b[ok], n[k] - n[ok]))
    bp, np_ = base.get("pages") or {}, now.get("pages") or {}
    for seq in sorted(set(bp) & set(np_), key=int):  # 한 쪽의 후퇴가 다른 쪽의 나아짐에 묻히지 않게 쪽마다도 본다
        b, n = bp[seq], np_[seq]
        bad += ["%s쪽 %s %d → %d (낮아짐)" % (seq, k, b[k], n[k]) for k in PAGE_HIGHER if n.get(k, 0) < b.get(k, 0)]
        bad += ["%s쪽 %s %d → %d (늘어남)" % (seq, k, b[k], n[k]) for k in PAGE_LOWER if n.get(k, 0) > b.get(k, 0)]
    return bad


def headline(t):
    return ("APR1400: 태그 정확 %d/%d(원) · 텍스트 층에 없는 태그 %d · 연결 표기 검출 %d/%d · 없는 대상 %d · 짝 %d"
            "(정답 짝 %d/%d · 틀린 짝 %d · 후보 %d) · 미확인 %d"
            % (t["tag_exact"], t["bubbles"], t["tag_not_in_text"], t["connectors_detected"], t["offpage_labels"],
               t["connector_bad_target"], t["paired"], t.get("pair_key_hit", 0), t.get("pair_key", 0),
               t.get("pair_key_wrong", 0), t.get("pair_candidates", 0), t["unknowns"]))


def main(argv=None):
    from hazop.console import safe_console
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from hazop import paths
    ap.add_argument("--input-dir", default=None, help="쪽별 PDF 폴더(기본: 저장소의 %s/도면별)" % paths.folder_rel("APR1400"))
    ap.add_argument("--catalog", default=None, help="도면목록.csv(기본: 입력 폴더의 상위 폴더)")
    ap.add_argument("--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 2)))
    ap.add_argument("--pages", help="순번 몇 개만(쉼표). 점수 비교·갱신을 하지 않음")
    ap.add_argument("--score", default=SCORE)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--out", help="쪽별 결과 CSV를 쓸 경로")
    args = ap.parse_args(argv)
    input_dir = os.path.abspath(args.input_dir or default_input_dir())
    catalog = os.path.abspath(args.catalog or os.path.join(os.path.dirname(input_dir), "도면목록.csv"))
    pages = {int(x) for x in args.pages.split(",")} if args.pages else None
    t = time.time()
    res = run(input_dir, catalog, args.jobs, pages)
    res["totals"]["seconds"] = round(time.time() - t)
    if args.out:
        with open(args.out, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, sorted({k for p in res["per_page"] for k in p}))
            w.writeheader()
            w.writerows(res["per_page"])
    print(headline(res["totals"]))
    for dwg, k in res["answer_key"].items():
        print("  정답 %s: 계기 %d/%d(태그 %d 중 맞음 %d) · 연결 %d/%d(연결점 %d 중 맞음 %d) · 대리 원 %d(정답 안 %d)/정답 %d"
              " · 대리 연결 표기 %d(정답 안 %d)/정답 %d"
              % (dwg, k["instrument_hits"], k["instruments"], k["tagged"], k["tagged_correct"], k["connector_hits"],
                 k["connectors"], k["continuations"], k["continuations_correct"], k["proxy_bubbles"],
                 k["proxy_bubbles_in_key"], k["key_instruments"], k["proxy_offpage"], k["proxy_offpage_in_key"],
                 k["key_connectors"]))
    if pages:
        return 0
    saved = {"totals": res["totals"], "answer_key": res["answer_key"],
             "pages": {str(p["seq"]): {k: p.get(k, 0) for k in PAGE_HIGHER + PAGE_LOWER} for p in res["per_page"]}}
    if args.update:
        os.makedirs(os.path.dirname(args.score), exist_ok=True)
        with open(args.score, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(saved, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print("점수 기준값을 썼음: %s" % args.score)
        return 0
    with open(args.score, encoding="utf-8") as fh:
        base = json.load(fh)
    bad = ratchet(base, saved)
    for line in bad:
        print("후퇴: %s" % line)
    print("기준값: %s" % headline(base["totals"]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
