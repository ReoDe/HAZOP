"""같은 시트 이름(graph_id)을 원하는 그래프가 여럿일 때 어느 것을 프로젝트 그래프에 쓸지, 그리고 시트 자리(seat) 표.
근거: HZ-PLN-22 §4.2 (나), docs/units/2026-11-13-drawing-knowledge/evidence/sheet-identity-design.md.

시트 이름 규칙은 hazop.graph.sheets가 정한다(번호가 있으면 graph-<번호>, 없으면 graph-<자료>-p<쪽>). 이 모듈은 그 이름을 여러 그래프가
나눠 쓸 때 고른다. 나눠 쓰는 경우는 같은 번호의 다른 형식(drawio·PDF·DEXPI), 같은 번호의 다른 파일(개정판을 다른 파일로),
같은 자료의 여러 등록 판, 그리고 정착 전 프로젝트에 남은 옛 이름(확정 전 PDF는 모두 graph-drawing)이다.

자리 표: `data/drawing-sources/<프로젝트>.json`
  chosen{도면 번호: {format, by, at}}      사람이 고른 형식(옛 파일 그대로 읽힘)
  seats{graph_id: {material_id, page, why, name, by, at}}   why: legacy(이 규칙 전 이름을 지킴)·in_use(정착 때 쓰던 파일)·chosen(사람이 고름)
  seats_settled{at, rule}                  정착을 마쳤다는 표시. 없으면 고르기·이름은 이 단위 전 규칙 그대로다(열지 않은 프로젝트는 그대로 보임)
이 파일은 프로젝트 그래프 입력 지문에 들어 있어(hazop.app.project_ctx._graph_inputs) 바뀌면 그래프와 도면 이름 캐시를 다시 짓는다.

고르기 차례(정착 뒤, graph_id 묶음 안에서):
  0. (자료, 쪽)마다 가장 새 등록 판 하나(같은 도면이 두 시트가 되지 않게). legacy 자리가 붙박은 폴더는 이름이 다르면 남긴다
  1. 자료가 하나면 그것  2. 사람이 고른 파일, 고른 형식이면 그 형식 안에서  3. 자리 주인(legacy·in_use)
  4. 먼저 등록한 자료(등록 색인 registry.json의 차례, 없는 자료는 맨 뒤에 폴더 이름 차례). 그래프 수정 시각은 쓰지 않는다(다시 추출로 뒤집힘)
읽는 함수(pick, conflicts, sheet_rows, sheet_name)는 파일을 쓰지 않는다. 쓰는 것은 choose와 settle뿐이고, settle은 작업 루트에서만 돈다.
Qt 의존 없음.
"""

import json
import os

from hazop import paths, store_io
from hazop.graph import sheets

KIND = "hazop_drawing_sources"
SCHEMA_VERSION = "0.2"
SETTLE_RULE = "sheet-identity-1"
FORMATS = ("drawio", "pdf_vector", "dexpi")  # 추출 결과 source.format 값. 모르는 값도 그대로 다룬다(형식 이름으로만 쓴다)
_EXTRACT_CACHE = {}

OTHER_FORMAT, OTHER_FILE, BEFORE_SETTLE = "same_number_other_format", "same_number_other_file", "same_name_before_settle"
SETTLE_SKIPPED = "settle_rebuild_failed"
REASONS = {
    OTHER_FORMAT: "같은 도면 번호 %(number)s의 원본이 %(formats)s 형식으로 함께 있습니다. 사람이 고르기 전에는 %(in_use)s를 씁니다.",
    OTHER_FILE: "같은 도면 번호 %(number)s의 다른 파일이 들어왔습니다. 그래프에 쓸 파일을 고르세요. 사람이 고르기 전에는 %(in_use)s를 씁니다.",
    BEFORE_SETTLE: "번호가 없는 도면 %(count)d개가 옛 이름 %(graph_id)s를 나눠 써서 %(in_use)s만 보입니다. 다음 추출·그래프 짓기에서 "
                   "도면마다 따로 들어옵니다.",
    SETTLE_SKIPPED: "가려졌던 도면 %(skipped)s를 새 이름으로 다시 짓지 못해 %(in_use)s만 보입니다(%(why)s). 그 도면을 다시 추출하면 따로 들어옵니다.",
}


# ---------------------------------------------------------------- 자리 표 파일

def choices_path(project_id, root=None):
    base = root or paths.folder("drawing-sources")
    return os.path.join(base, paths.safe_name(project_id) + ".json")


def _read_doc(path):
    """(문서, 지문). 없거나 깨졌으면 ({}, 지문). 깨진 파일은 정착 전처럼 다룬다(기본 규칙으로 되돌아간다)."""
    data, fp = store_io.read_bytes(path)
    try:
        doc = json.loads(data.decode("utf-8")) if data else {}
    except ValueError:
        doc = {}
    return (doc if isinstance(doc, dict) else {}), fp


def _seats(doc):
    raw = doc.get("seats") if isinstance(doc.get("seats"), dict) else {}
    return {k: v for k, v in raw.items() if isinstance(v, dict) and v.get("material_id") and v.get("why") in sheets.SEAT_KINDS}


def _chosen(doc):
    chosen = doc.get("chosen") if isinstance(doc.get("chosen"), dict) else {}
    return {k: v for k, v in chosen.items() if isinstance(v, dict) and v.get("format")}


def load_choices(project_id, root=None):
    """{도면 번호: {"format", "by", "at"}}. 파일이 없거나 깨졌으면 {}."""
    return _chosen(_read_doc(choices_path(project_id, root))[0])


def _skipped(doc):
    """{폴더 이름: 사유} 정착이 다시 짓지 못한 가려진 시트."""
    rows = (doc.get("seats_settled") or {}).get("skipped") if isinstance(doc.get("seats_settled"), dict) else None
    return {r["name"]: str(r.get("reason") or "") for r in rows or () if isinstance(r, dict) and r.get("name")}


def load_seats(project_id, root=None):
    """(자리 표 {graph_id: 자리}, 정착을 마쳤는가)."""
    doc = _read_doc(choices_path(project_id, root))[0]
    return _seats(doc), bool(doc.get("seats_settled"))


def name_for(project_id, f, choices_root=None):
    """sheets.facts 꼴 f로 지을 그래프의 graph_id. 정착 전 프로젝트는 이 단위 전 이름(sheets.legacy_name) 그대로다."""
    seats, settled = load_seats(project_id, choices_root)
    return sheets.sheet_id(f, seats) if settled else sheets.legacy_name(f)


def sheet_name(project_id, extraction, choices_root=None):
    """이 추출 결과로 지을 그래프의 graph_id(name_for)."""
    return name_for(project_id, sheets.facts(extraction), choices_root)


# ---------------------------------------------------------------- 후보와 그 사실

def extract_root_for(graph_root=None):
    """그래프 폴더 옆 추출 결과 폴더. 기본은 작업 루트의 output/extract."""
    if graph_root:
        return os.path.join(os.path.dirname(os.path.abspath(graph_root)), "extract")
    return paths.output_root("extract")


def _extraction_facts(name, extract_root):
    """그 폴더의 추출 결과에서 읽은 {format, registration_version, **sheets.facts}. 없거나 읽을 수 없으면 {}. (시각, 크기)가 같으면 다시 읽지 않는다."""
    path = os.path.join(extract_root, name, "extraction.json")
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (st.st_mtime_ns, st.st_size)
    hit = _EXTRACT_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            ex = json.load(fh)
    except (OSError, ValueError):
        return {}
    src = ex.get("source") or {}
    out = dict(sheets.facts(ex), format=src.get("format"), registration_version=src.get("registration_version"))
    _EXTRACT_CACHE[path] = (key, out)
    return out


def source_format(name, extract_root):
    """그 그래프 폴더의 추출 결과가 어느 형식인가(extraction.json의 source.format). 없거나 읽을 수 없으면 None."""
    return _extraction_facts(name, extract_root).get("format")


def _cheap(c):
    """후보에 자료·판·쪽을 채운다. 새 graph.json은 source에 있고, 이 규칙 전 graph.json은 등록 경로 폴더 이름에서 읽는다(파일을 열지 않음)."""
    if "mat" in c:
        return c
    src = c["graph"].get("source") or {}
    parsed = sheets.from_out_name(c["name"]) or (None, None, None)
    c["mat"] = src.get("material_id") or parsed[0]
    c["ver"] = src.get("registration_version") or parsed[1] or 0
    page = src.get("page_index")
    c["page"] = page if isinstance(page, int) else (parsed[2] or 0)
    return c


def sheet_key(c):
    """후보의 시트 정체 (material_id, 쪽). 등록 밖이면 (None, 쪽). 이 규칙 전 graph.json은 폴더 이름에서 읽는다."""
    _cheap(c)
    return c["mat"], c["page"]


def _format(c, extract_root):
    if "format" not in c:
        c["format"] = (c["graph"].get("source") or {}).get("format") or source_format(c["name"], extract_root)
    return c["format"]


def facts_of(c, extract_root):
    """이름을 정하는 데 쓰는 sheets.facts 꼴. 새 graph.json은 source에서, 옛 것은 추출 결과에서 읽는다."""
    f = sheets.from_graph(c["graph"])
    if f.get("material_id") and f.get("page_count") is not None:
        return f
    got = _extraction_facts(c["name"], extract_root)
    return got if got else dict(f, material_id=_cheap(c)["mat"], page_index=c["page"], page_count=f.get("page_count") or 1)


def drawing_number_of(graph):
    return (graph.get("source") or {}).get("drawing_number") or graph.get("graph_id")


def _latest(group):
    return max(group, key=lambda c: c["key"])


def _newest(group):
    """같은 자료의 후보 가운데 가장 새 등록 판(같으면 가장 최근 그래프)."""
    return max(group, key=lambda c: (c["ver"], c["key"]))


def _owner(c, extract_root):
    """후보의 주인: 등록 경로는 자료 ID, 등록 밖(표본 실행 등)은 ("unregistered", 형식). 등록 밖은 형식마다 가장 최근 것이 이 단위 전 규칙이다."""
    return _cheap(c)["mat"] or ("unregistered", _format(c, extract_root))


def _by_material(group, extract_root):
    """{주인(_owner): 그 주인의 가장 새 후보}."""
    out = {}
    for c in group:
        out.setdefault(_owner(c, extract_root), []).append(c)
    return {m: (_newest(v) if isinstance(m, str) else _latest(v)) for m, v in out.items()}


def registration_order(project_id, store_root=None):
    """{자료 ID: 등록 색인(registry.json)에서의 차례}. 다시 추출해도 바뀌지 않는 '먼저 등록한 자료'의 기준. 색인이 없으면 {}."""
    from hazop.register import registry
    try:
        index = registry.Store(store_root or paths.store_root(), project_id).load_index(project_id)
    except (OSError, ValueError):
        return {}
    return {m.get("material_id"): i for i, m in enumerate(index.get("materials") or [])}


# ---------------------------------------------------------------- 고르기

def _legacy_decide(group, choice, extract_root):
    """이 단위 전 규칙(정착 전 프로젝트): 같은 형식이면 가장 최근 것, 형식이 섞이면 사람이 고른 형식, 없으면 먼저 있던 형식.
    -> (후보, 사람이 고른 것을 따랐는가)."""
    formats = {_format(c, extract_root) for c in group} - {None} if len(group) > 1 else set()
    if len(formats) < 2:
        return _latest(group), False
    if choice and choice.get("format") in formats:
        return _latest([c for c in group if c["format"] == choice["format"]]), True
    first = min(formats, key=lambda f: min(c["key"] for c in group if c["format"] == f))
    return _latest([c for c in group if c["format"] == first]), False


def _decide(group, seat, choice, order, extract_root):
    """정착 뒤 규칙(모듈 설명의 차례 1~4) -> (후보, 사람이 고른 것을 따랐는가)."""
    mats = _by_material(group, extract_root)
    if len(mats) == 1:
        return next(iter(mats.values())), False
    if seat and seat.get("why") == sheets.CHOSEN and seat["material_id"] in mats:
        return mats[seat["material_id"]], True
    pool, followed = mats, False
    formats = {_format(c, extract_root) for c in mats.values()} - {None}
    if len(formats) > 1 and choice and choice.get("format") in formats:
        pool, followed = {m: c for m, c in mats.items() if c["format"] == choice["format"]}, True
    if seat and seat["material_id"] in pool:
        return pool[seat["material_id"]], followed
    since = {m: min(c["key"] for c in group if _owner(c, extract_root) == m) for m in pool}   # 등록 밖은 먼저 있던 것(이 단위 전 규칙)
    first = min(pool, key=lambda m: (order.get(m, len(order)), since[m], pool[m]["name"]))
    return pool[first], followed


def _one_per_sheet(cands, seats):
    """고르기 차례 0: (자료, 쪽)마다 가장 새 등록 판의 후보만 남긴다. legacy 자리가 붙박은 폴더는 남은 후보와 이름이 다르면 남긴다."""
    pinned = {s.get("name") for s in seats.values() if s.get("why") == sheets.LEGACY}
    by_key, out = {}, []
    for c in cands:
        if _cheap(c)["mat"]:
            by_key.setdefault((c["mat"], c["page"]), []).append(c)
        else:
            out.append(c)
    for group in by_key.values():
        top = _newest(group)
        gids = {top["gid"]}
        out.append(top)
        for c in sorted(group, key=lambda c: c["name"]):
            if c is not top and c["name"] in pinned and c["gid"] not in gids:
                gids.add(c["gid"])
                out.append(c)
    return out


def _state(project_id, cands, graph_root, choices_root, store_root, doc=None):
    """[(gid, 묶음, 고른 후보, 사람이 고른 것을 따랐는가)], 정착했는가. doc: 자리 표 대신 쓸 문서(미리 셈용)."""
    extract_root = extract_root_for(graph_root)
    doc = _read_doc(choices_path(project_id, choices_root))[0] if doc is None else doc
    seats, chosen, settled = _seats(doc), _chosen(doc), bool(doc.get("seats_settled"))
    pool = _one_per_sheet(cands, seats) if settled else cands
    by_gid = {}
    for c in pool:
        by_gid.setdefault(c["gid"], []).append(c)
    order = None
    out = []
    for gid, group in sorted(by_gid.items(), key=lambda kv: str(kv[0])):
        choice = chosen.get(drawing_number_of(group[0]["graph"]))
        if not settled:
            pick_c, followed = _legacy_decide(group, choice, extract_root)
        else:
            if order is None and len(_by_material(group, extract_root)) > 1:
                order = registration_order(project_id, store_root)
            pick_c, followed = _decide(group, seats.get(gid), choice, order or {}, extract_root)
        pick_c["rivals"] = len(_by_material(group, extract_root)) - 1 if len(group) > 1 else 0   # 이 이름을 원하는 다른 자료 수
        out.append((gid, group, pick_c, followed))
    return out, settled


def pick(project_id, cands, graph_root=None, choices_root=None, store_root=None):
    """cands: [{"gid", "key"(바뀐 시각, 경로), "graph", "name"}] -> ({gid: 고른 후보}, notes). 파일을 쓰지 않는다."""
    state, settled = _state(project_id, cands, graph_root, choices_root, store_root)
    extract_root = extract_root_for(graph_root)
    notes = [_row(gid, group, c, settled, extract_root)["text"] for gid, group, c, followed in state  # 사람이 고른 것을 따른 줄은 알리지 않는다
             if not followed and _is_conflict(group, extract_root)]
    return {gid: c for gid, _g, c, _f in state}, sorted(set(notes))


def _renamed(cands, material_id, page, graph_id, number):
    """cands 가운데 그 (자료, 쪽)의 후보를 graph_id(번호 number)로 이름을 바꾼 사본."""
    out = []
    for c in cands:
        if sheet_key(c) == (material_id, page):
            src = dict(c["graph"].get("source") or {}, drawing_number=number)
            c = dict(c, gid=graph_id, graph=dict(c["graph"], graph_id=graph_id, source=src))
        out.append(c)
    return out


def owner_if(project_id, material_id, page, graph_id, number, keep=False, graph_root=None, choices_root=None, store_root=None):
    """그 (자료, 쪽)의 시트 이름이 graph_id(이름에 쓴 번호 number)가 되면 고르기가 그 이름에 쓸 자료 ID(없으면 None). 파일을 쓰지 않는다.
    keep: 지금 그 이름의 주인을 자리(in_use)로 붙박은 셈(keep_owner를 부른 뒤의 고르기). 표제란 가드가 번호를 바꾸기 전에 묻는다."""
    doc = _read_doc(choices_path(project_id, choices_root))[0]
    cands = _candidates(project_id, graph_root)
    if keep:
        seat = _seat_for_owner(project_id, cands, graph_id, doc, graph_root, choices_root, store_root)
        if seat:
            doc = dict(doc, seats=dict(_seats(doc), **{graph_id: seat}))
    state, _ = _state(project_id, _renamed(cands, material_id, page, graph_id, number), graph_root, choices_root, store_root, doc)
    c = next((c for gid, _g, c, _f in state if gid == graph_id), None)
    return _cheap(c)["mat"] if c else None


def _seat_for_owner(project_id, cands, graph_id, doc, graph_root, choices_root, store_root):
    """지금 그 이름의 주인을 붙박을 자리 기록(이미 자리가 있거나 주인이 없거나 정착 전이면 None)."""
    if not doc.get("seats_settled") or graph_id in _seats(doc):
        return None
    state, _ = _state(project_id, cands, graph_root, choices_root, store_root, doc)
    c = next((c for gid, _g, c, _f in state if gid == graph_id), None)
    if c is None or not _cheap(c)["mat"]:
        return None
    return {"material_id": c["mat"], "page": c["page"], "why": sheets.IN_USE, "name": c["name"]}


def keep_owner(project_id, graph_id, by, at=None):
    """다른 파일이 같은 이름(같은 도면 번호)을 받기 전에 지금 주인을 자리(in_use)로 붙박는다(말없이 갈아타지 않게, 먼저 있던 파일이 주인으로 남음).
    이미 자리가 있거나 주인이 없거나 정착 전이면 쓰지 않는다. -> 쓴 자리 기록 또는 None. 원자적, 읽은 뒤 바뀌었으면 store_io.Conflict."""
    path = choices_path(project_id)
    doc, fp = _read_doc(path)
    seat = _seat_for_owner(project_id, _candidates(project_id, None), graph_id, doc, None, None, None)
    if not seat:
        return None
    seat.update(by=by, at=at or store_io.now_utc())
    doc.setdefault("seats", {})[graph_id] = seat
    _write_doc(project_id, path, doc, fp)
    return seat


def _is_conflict(group, extract_root):
    if len(group) < 2:
        return False
    mats = _by_material(group, extract_root)
    return len(mats) > 1 or len({_format(c, extract_root) for c in group} - {None}) > 1


def _file_name(c, extract_root):
    return facts_of(c, extract_root).get("file") or c["name"]


def _row(gid, group, chosen, settled, extract_root, skipped=None):
    """고를 것이 있는 묶음 한 줄(conflicts의 꼴, chosen·chosen_material 칸 빼고). skipped: 정착이 다시 짓지 못한 폴더 {이름: 사유}."""
    mats = _by_material(group, extract_root)
    members = list(mats.values()) if settled else sorted(group, key=lambda c: c["name"])
    formats = sorted({_format(c, extract_root) for c in members} - {None})
    usable = sheets.usable_number(facts_of(chosen, extract_root))
    number = usable if usable and gid == sheets.PREFIX + usable else None
    stuck = [c for c in members if c is not chosen and c["name"] in (skipped or {})]
    if len(formats) > 1:
        kind, reason = "format", OTHER_FORMAT
    elif stuck:
        kind, reason = "file", SETTLE_SKIPPED
    else:
        kind, reason = "file", OTHER_FILE if number else BEFORE_SETTLE
    in_use = "%s(%s)" % (_file_name(chosen, extract_root), chosen.get("format") or "형식 모름")
    shown = number or drawing_number_of(chosen["graph"])
    text = REASONS[reason] % {"number": shown, "formats": "·".join(formats), "in_use": in_use, "count": len(mats), "graph_id": gid,
                              "skipped": "·".join(_file_name(c, extract_root) for c in stuck),
                              "why": "; ".join(skipped[c["name"]] for c in stuck) if stuck else ""}
    return {"kind": kind, "reason": reason, "text": text, "graph_id": gid, "drawing_number": shown,
            "formats": formats, "in_use": chosen["name"], "in_use_format": chosen.get("format"), "in_use_material": chosen.get("mat"),
            "in_use_file": _file_name(chosen, extract_root),
            "candidates": [{"name": c["name"], "format": c.get("format"), "modified": c["key"][0], "material_id": c.get("mat"),
                            "registration_version": c.get("ver"), "file": _file_name(c, extract_root),
                            "in_use": c is chosen} for c in sorted(members, key=lambda c: c["name"])]}


def _candidates(project_id, graph_root):
    out = []
    root = graph_root or paths.output_root("graph")
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        p = os.path.join(root, name, "graph.json")
        try:
            with open(p, encoding="utf-8") as fh:
                g = json.load(fh)
            mtime = os.path.getmtime(p)
        except (OSError, ValueError):
            continue
        if (g.get("project_id") or "SNP-SAMPLE") == project_id:
            out.append({"gid": g.get("graph_id"), "key": (mtime, p), "graph": g, "name": name})
    return out


def conflicts(project_id, graph_root=None, choices_root=None, store_root=None):
    """고를 것이 있는 시트 이름(파일을 쓰지 않음). 충돌이 없으면 [].
    줄 = {"kind": "format"|"file", "reason": 사유 코드, "text": 사람용 글, "graph_id", "drawing_number", "formats",
          "in_use": 지금 쓰는 폴더 이름, "in_use_format", "in_use_material", "in_use_file", "chosen": 사람이 고른 형식 또는 None,
          "chosen_material": 사람이 고른 자료 또는 None, "candidates": [{"name", "format", "modified", "material_id",
          "registration_version", "file"(원본 파일 이름), "in_use"}]}."""
    extract_root = extract_root_for(graph_root)
    doc = _read_doc(choices_path(project_id, choices_root))[0]
    seats, chosen_fmt, skipped = _seats(doc), _chosen(doc), _skipped(doc)
    state, settled = _state(project_id, _candidates(project_id, graph_root), graph_root, choices_root, store_root)
    out = []
    for gid, group, c, followed in state:
        if not _is_conflict(group, extract_root):
            continue
        row = _row(gid, group, c, settled, extract_root, skipped)
        seat = seats.get(gid) if settled else None
        row["chosen_material"] = seat["material_id"] if seat and seat.get("why") == sheets.CHOSEN and followed else None
        fmt = chosen_fmt.get(drawing_number_of(c["graph"]), {}).get("format")
        row["chosen"] = fmt if followed and row["kind"] == "format" and row["chosen_material"] is None else None
        out.append(row)
    return out


def sheet_rows(project_id, graph_root=None, choices_root=None, store_root=None):
    """프로젝트 그래프에 들어가는 시트마다 도면 목록 한 줄에 쓸 엔진 값(파일을 쓰지 않음), graph_id 차례.
    줄 = sheets.describe 값 {graph_id, label, drawing_number, number_state, notice} + {"name"(폴더), "material_id", "page_index",
    "conflict": 이 이름에 고를 것이 있으면 conflicts 줄의 reason, 없으면 None}."""
    extract_root = extract_root_for(graph_root)
    state, settled = _state(project_id, _candidates(project_id, graph_root), graph_root, choices_root, store_root)
    out = []
    for gid, group, c, _followed in state:
        f = facts_of(c, extract_root)
        conflict = _row(gid, group, c, settled, extract_root)["reason"] if _is_conflict(group, extract_root) else None
        out.append(dict(sheets.describe(f, gid), name=c["name"], material_id=f.get("material_id"), page_index=f.get("page_index"),
                        conflict=conflict))
    return out


# ---------------------------------------------------------------- 쓰기: 고르기·정착

def _write_doc(project_id, path, doc, fp):
    doc.update(schema_version=SCHEMA_VERSION, kind=KIND, project_id=project_id)
    if not isinstance(doc.get("chosen"), dict):
        doc["chosen"] = {}
    store_io.write_json(path, doc, expect=fp)


def choose(project_id, drawing_number, source_format_name, by, at=None, graph_root=None, choices_root=None, material_id=None):
    """사람이 고른 원본을 받아 저장한다(원자적, 읽은 뒤 바뀌었으면 store_io.Conflict). drawing_number는 도면 번호나 graph_id.
    material_id를 주면 그 파일(자료)을 고른다(자리 표 seats[graph_id] why chosen, 정착한 프로젝트만). 아니면 형식을 고른다(옛 chosen).
    고를 것이 없거나 그 형식·자료의 그래프가 없거나 형식이 같아 형식으로 고를 수 없으면 ValueError.
    반환: 저장한 기록. 사람 수정 기록·추출 결과는 건드리지 않는다."""
    if not by:
        raise ValueError("고른 사람 이름이 없음")
    found = [c for c in conflicts(project_id, graph_root, choices_root) if drawing_number in (c["drawing_number"], c["graph_id"])]
    if not found:
        raise ValueError("도면 %s에 고를 원본이 없음(같은 번호의 다른 형식·다른 파일이 없음)" % drawing_number)
    row = found[0]
    path = choices_path(project_id, choices_root)
    doc, fp = _read_doc(path)
    at = at or store_io.now_utc()
    if material_id is not None:
        cand = next((c for c in row["candidates"] if c["material_id"] == material_id), None)
        if cand is None:
            raise ValueError("도면 %s의 후보에 자료 %s가 없음" % (drawing_number, material_id))
        if not doc.get("seats_settled"):
            raise ValueError("이 프로젝트의 시트 자리를 아직 정하지 않아 파일을 고를 수 없음(다시 추출하거나 그래프를 다시 지은 뒤 고르세요)")
        page = sheets.from_out_name(cand["name"])
        record = {"material_id": material_id, "page": page[2] if page else 0, "why": sheets.CHOSEN, "name": cand["name"],
                  "by": by, "at": at}
        doc.setdefault("seats", {})[row["graph_id"]] = record
        _write_doc(project_id, path, doc, fp)
        return record
    if row["kind"] != "format":
        raise ValueError("도면 %s는 같은 형식(%s)의 다른 파일이라 형식으로 고를 수 없음: 파일(자료)을 고르세요"
                         % (drawing_number, ", ".join(row["formats"])))
    if source_format_name not in row["formats"]:
        raise ValueError("도면 번호 %s에 %s 형식의 그래프가 없음(있는 형식: %s)" % (drawing_number, source_format_name, ", ".join(row["formats"])))
    record = {"format": source_format_name, "by": by, "at": at}
    if not isinstance(doc.get("chosen"), dict):
        doc["chosen"] = {}
    doc["chosen"][row["drawing_number"]] = record
    seat = (doc.get("seats") or {}).get(row["graph_id"])
    if isinstance(seat, dict) and seat.get("why") == sheets.CHOSEN:   # 형식을 새로 고르면 앞서 고른 파일은 내려놓는다
        del doc["seats"][row["graph_id"]]
    _write_doc(project_id, path, doc, fp)
    return record


def settle(project_id, render, at=None):
    """정착: 이 단위 전 규칙이 지금 보여 주는 시트의 이름을 자리 표에 붙박고, 가려졌던 시트를 새 이름으로 다시 짓는다. 작업 루트에서만 돈다.
    render(extraction_path, seats) -> (graph, {파일 이름: 바이트}): 그 폴더의 그래프 파일들을 쓰지 않고 만든다(scripts/build_graph.render_one).
    - 이미 정착했으면 아무것도 쓰지 않는다(멱등). 자리를 다시 셈하지 않는다(다시 지은 뒤의 고르기가 달라지므로).
    - 다시 지을 그래프를 모두 먼저 만든 뒤에 쓴다. 한 시트를 만들지 못하면(추출 결과 깨짐 등) 그 시트만 옛 이름 그대로 두고 skipped에
      사유를 적어 나머지를 마친다(가려진 도면 하나 때문에 프로젝트의 추출이 막히지 않게). 사유는 자리 표 seats_settled.skipped에 남고
      고르기 줄(reason settle_rebuild_failed)로 사용자에게 보인다. 쓰다 실패하면(디스크) 예외를 올린다.
    - 쓰기 전에 바꿀 파일(자리 표·다시 지을 폴더의 파일)을 store_io.backup으로 백업하고, 파일마다 원자적으로 쓴다. 자리 표를 맨 끝에 쓴다:
      그 앞에서 끊기면 정착 전 상태로 남고(다시 지은 시트는 새 이름이라 옛 규칙으로도 겹치지 않음) 다음 정착이 같은 끝 상태로 간다.
    그래프가 아직 없는 새 프로젝트도 정착을 마친 것으로 적는다(붙박을 옛 이름이 없으므로 처음부터 새 이름을 쓴다).
    -> {"project_id", "changed", "state": "already"|"settled", "seats", "renamed": [{"name", "from", "to"}], "skipped": [{"name", "reason"}],
        "backup", "backup_files"}."""
    path = choices_path(project_id)
    doc, fp = _read_doc(path)
    out = {"project_id": project_id, "changed": False, "state": "already", "seats": _seats(doc), "renamed": [], "skipped": [],
           "backup": None, "backup_files": []}
    if doc.get("seats_settled"):
        return out
    at = at or store_io.now_utc()
    extract_root, graph_root = paths.output_root("extract"), paths.output_root("graph")
    cands = _candidates(project_id, None)
    state, _ = _state(project_id, cands, None, None, None)
    seats = dict(_seats(doc))
    for gid, group, c, _followed in state:
        f = facts_of(c, extract_root)
        if not f.get("material_id") or gid in seats:
            continue
        why = sheets.LEGACY if gid != sheets.natural(f) else sheets.IN_USE if len(_by_material(group, extract_root)) > 1 else None
        if why:
            seats[gid] = {"material_id": f["material_id"], "page": f.get("page_index") or 0, "why": why, "name": c["name"],
                          "by": "settle", "at": at}
    todo = []
    for c in cands:
        f = facts_of(c, extract_root)
        if not f.get("material_id"):
            continue
        want = sheets.sheet_id(f, seats)
        if want == c["gid"]:
            continue
        ex_path = os.path.join(extract_root, c["name"], "extraction.json")
        if not os.path.isfile(ex_path):
            out["skipped"].append({"name": c["name"], "reason": "추출 결과가 없어 다시 지을 수 없음"})
            continue
        try:
            graph, files = render(ex_path, seats)
        except Exception as exc:  # noqa: BLE001 - 가려진 시트 하나 때문에 프로젝트의 추출·다시 짓기를 막지 않는다(그 시트만 옛 이름으로 남김)
            out["skipped"].append({"name": c["name"], "reason": "다시 짓지 못함: %s" % (str(exc)[:160] or type(exc).__name__)})
            continue
        if graph.get("graph_id") != want:
            out["skipped"].append({"name": c["name"], "reason": "다시 지은 이름이 %s가 아님(%s)" % (want, graph.get("graph_id"))})
            continue
        todo.append((c, want, files))
    backup_files = ([path] if os.path.isfile(path) else []) + [
        os.path.join(graph_root, c["name"], n) for c, _w, files in todo for n in sorted(files)
        if os.path.isfile(os.path.join(graph_root, c["name"], n))]
    if backup_files:
        out["backup"], out["backup_files"] = store_io.backup(backup_files, "sheet-identity"), backup_files
    for c, want, files in todo:
        for n, data in sorted(files.items()):
            store_io.write_bytes(os.path.join(graph_root, c["name"], n), data)
        out["renamed"].append({"name": c["name"], "from": c["gid"], "to": want})
    doc["seats"] = seats
    doc["seats_settled"] = dict({"at": at, "rule": SETTLE_RULE}, **({"skipped": out["skipped"]} if out["skipped"] else {}))
    _write_doc(project_id, path, doc, fp)
    out.update(changed=True, state="settled", seats=seats)
    return out


def registration_conflicts(project_id, store_root=None):
    """등록 기록(사람이 확정한 도면 번호)에서 형식이 다른 자료가 같은 번호를 쓰는 곳. 등록 화면이 알릴 자료.
    [{"drawing_number", "materials": [{"material_id", "format", "registration_version"}]}]."""
    from hazop.register import registry
    store = registry.Store(store_root or registry.DEFAULT_STORE, project_id)
    index = store.load_index(project_id)
    by_number = {}
    for m in index.get("materials", []):
        if not m.get("versions"):
            continue
        try:
            with open(store.snapshot_path(m["material_id"], m["versions"][-1]), encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if rec.get("status") != "registered" or not rec.get("drawing_number"):
            continue
        by_number.setdefault(rec["drawing_number"], []).append(
            {"material_id": rec["material_id"], "format": rec.get("format"), "registration_version": rec.get("registration_version")})
    return [{"drawing_number": k, "materials": v} for k, v in sorted(by_number.items())
            if len({x["format"] for x in v}) > 1]
