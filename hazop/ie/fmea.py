"""P5 FMEA 입력(설계 HZ-PLN-17 §8.2). 고장모드 및 영향 분석(Failure Modes and Effects Analysis, FMEA; DOE-HDBK-1100 §4 표 4.20).

앱은 FMEA를 대신 하지 않고, 사람이 만든 FMEA 표(Excel 양식)를 가져와 도면 구성요소에 잇고, 사람이 승인한 행을 ⑥ 기본사건 후보의
출처로 붙인다(§8.2 질문 2·3). Qt를 쓰지 않고 파일을 쓰지 않는 순수 함수다(저장은 hazop.ie.store).

- 문서 {"kind": "hazop_fmea", "schema_version", "project_id", "counters": {"FM": n}, "rows": {"FM-001": 행}, "node_marks": {구간: "include"|
  "exclude"}, "imports": [가져오기 기록], "history": []}. 행 ID는 counters로 매기고 행이 빠져도 번호를 다시 쓰지 않는다.
- 다시 가져와도 같은 행은 같은 ID: 양식의 '행 ID' 칸이 있으면 그 ID, 없으면 (태그, 고장모드 코드 또는 글, 원인) 정규화 열쇠(row_key).
- 행 상태 imported(가져옴) / approved(승인) / excluded(제외). 사람만 승인·제외한다. 승인한 행의 내용이 바뀌면 가져옴으로 돌아간다.
- 행 열쇠(key)는 지금 내용, import_key는 마지막으로 가져온 파일 값의 열쇠, file_values는 그 파일 값, edited는 사람이 고친 칸이다.
  다시 가져오기는 사람이 고친 칸을 덮지 않고, 파일도 그 칸을 바꿨으면 conflicts에 두어 사람이 고르게 한다(resolve_conflict).
- 승인 행은 기본사건 후보의 출처('fmea:FM-001')가 된다. 행의 구성요소·고장모드가 바뀌면 옛 기본사건에서 출처를 뗀다(sync_basic_events).
- 태그 대응: 그래프 구성요소 하나와 맞으면 match "ok", 없으면 "none", 둘 이상이면 "many". 사람이 고르면 "human". 대응하지 않은 행은 승인 못 함.
- Severity Class는 받아 두기만 하고 인계 묶음에는 넣지 않는다(E8).
"""

import copy
import re

from hazop import store_io
from hazop.ie import model
from hazop.study import migrate
from hazop.study import refs

KIND = "hazop_fmea"
SCHEMA_VERSION = "0.1"
ID_FORMAT = "FM-%03d"
STATUSES = {"imported": "가져옴", "approved": "승인", "excluded": "제외"}
MATCHES = {"ok": "대응", "none": "대응 실패(없음)", "many": "대응 실패(여럿)", "human": "사람이 고름"}
MARKS = {"include": "전기·제어 구간에 넣음", "exclude": "전기·제어 구간에서 뺌"}
SOURCE_PREFIX = "fmea:"
MAX_ROWS = 5000
MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 2000
# §6.4 고장모드 코드(NUREG/CR-6928 약어표). ELS·ELL은 표에서 한 줄이라 둘로 나눔
FAILURE_MODE_CODES = {
    "FTS": "기동 실패(fail to start)", "FTR": "운전 중 정지(fail to run)", "FTLR": "부하 인수 및 운전 실패(fail to load and run)",
    "FTO": "열림 실패(fail to open)", "FTC": "닫힘 실패(fail to close)", "FTOP": "작동 실패(fail to operate)",
    "SO": "오동작(spurious operation)", "PLG": "막힘(plug)", "ELS": "외부 누설 소(external leak small)",
    "ELL": "외부 누설 대(external leak large)", "FC": "제어 실패(fail to control)",
}
# (키, 양식 머리글, 영문 머리글(표 4.20), 열 너비). 양식·가져오기·화면이 이 표 하나를 쓴다
COLUMNS = (
    ("row_id", "행 ID", "Row ID", 9),
    ("tag", "기기 태그", "Component", 16),
    ("node_id", "구간 ID", "Node", 9),
    ("failure_mode", "고장모드", "Failure Mode", 22),
    ("failure_code", "고장모드 코드", "Failure Mode Code", 10),
    ("cause", "원인", "Cause", 26),
    ("op_mode", "운전 모드", "Operational Mode", 12),
    ("effect", "고장 영향", "Failure Effect", 30),
    ("detection", "탐지 방법", "Failure Detection Method", 20),
    ("compensation", "보상 수단", "Compensating Provisions", 20),
    ("remark", "비고·조치", "Remark/Action", 20),
    ("severity_class", "Severity Class", "Severity Class", 10),
    ("hazop_entry", "관련 HAZOP 항목", "HAZOP Entry", 12),
)
TEXT_FIELDS = tuple(k for k, *_ in COLUMNS if k not in ("row_id", "node_id"))
# 사람이 화면에서 고칠 수 있는 필드. 태그를 고치면 다시 대응하고, entity_id를 주면 사람이 고른 대응이 된다
EDITABLE = TEXT_FIELDS + ("node_id", "entity_id")
CONTENT = ("tag", "failure_mode", "failure_code", "cause", "op_mode", "effect", "detection", "compensation", "remark",
           "severity_class", "hazop_entry", "ref", "node_id")
SHEET = "FMEA"


def empty(project_id):
    return {"kind": KIND, "schema_version": SCHEMA_VERSION, "project_id": project_id, "counters": {"FM": 0}, "rows": {},
            "node_marks": {}, "imports": [], "history": []}


def problems(doc):
    """형식 문제 목록(빈 목록이면 편집 가능). store가 경계 검사로 쓴다."""
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        return ["kind가 %s가 아님" % KIND]
    c = doc.get("counters")
    if not isinstance(c, dict) or set(c) != {"FM"} or type(c["FM"]) is not int or c["FM"] < 0:
        return ["counters 형식이 맞지 않음"]
    out = []
    if not isinstance(doc.get("rows"), dict) or not isinstance(doc.get("node_marks"), dict) \
            or not isinstance(doc.get("imports"), list) or not isinstance(doc.get("history"), list):
        return ["rows·node_marks·imports·history 형식이 맞지 않음"]
    keys = set()
    for rid, r in doc["rows"].items():
        m = re.fullmatch(r"FM-(\d{3,})", rid)
        if not m or int(m.group(1)) > c["FM"] or not isinstance(r, dict):
            out.append("%s: ID 형식 또는 번호가 맞지 않음" % rid)
            continue
        if r.get("status") not in STATUSES or r.get("match") not in MATCHES:
            out.append("%s: status·match 값이 맞지 않음" % rid)
        if r.get("status") == "approved" and not r.get("ref"):
            out.append("%s: 대응하지 않은 행이 승인됨" % rid)
        if r.get("key") in keys:
            other = next(x for x, y in doc["rows"].items() if y.get("key") == r.get("key"))
            out.append("%s: %s와 태그·고장모드·원인·운전 모드가 같음(열쇠 중복)" % (rid, other))
        keys.add(r.get("key"))
    for nid, mark in doc["node_marks"].items():
        if mark not in MARKS:
            out.append("%s: 구간 표시 값 %r" % (nid, mark))
    return out


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def norm_tag(tag):
    return re.sub(r"[\s_]+", "-", str(tag or "").strip().upper())


def row_key(r):
    """행 열쇠: 태그, 고장모드 코드(없으면 고장모드 글), 원인, 운전 모드. 운전 모드만 다른 행은 다른 행이다(R2)."""
    return "|".join((norm_tag(r.get("tag")), (r.get("failure_code") or "").upper() or _norm(r.get("failure_mode")), _norm(r.get("cause")),
                     _norm(r.get("op_mode"))))


def code_of(text):
    """'FTO', 'fto', 'FTO(열림 실패)' → 'FTO'. 목록 밖이면 ''."""
    head = re.split(r"[\s(:·/-]", str(text or "").strip(), maxsplit=1)[0].upper()
    return head if head in FAILURE_MODE_CODES else ""


# ---------------------------------------------------------------- 태그 대응

def tag_index(pg):
    """{정규화 태그: [구성요소]} 프로젝트 그래프 기준(안정 참조가 있는 구성요소만)."""
    gid = pg.get("graph_id")
    out = {}
    for n in pg.get("nodes") or []:
        if not migrate.ref_of(n, gid):
            continue
        for t in {n.get("tag"), refs.node_text(n)}:
            if t:
                out.setdefault(norm_tag(t), [])
                if n not in out[norm_tag(t)]:
                    out[norm_tag(t)].append(n)
    return out


def _nodes_of(node_set, entity_id):
    return [n["node_id"] for n in node_set.get("nodes") or [] if entity_id in (n.get("members") or [])]


def _placed(pg, node_set, n, how, node_id=None):
    homes = _nodes_of(node_set, n["entity_id"])
    return {"ref": migrate.ref_of(n, pg.get("graph_id")), "entity_id": n["entity_id"], "equipment_kind": n.get("kind") or "",
            "match": how, "node_id": node_id if node_id in homes else (homes[0] if homes else None)}


def match_tag(pg, node_set, tag, node_id=None, index=None):
    """태그 하나의 대응 결과 {ref, entity_id, equipment_kind, match, node_id}. 대응 실패면 ref·entity_id가 None."""
    hits = (index if index is not None else tag_index(pg)).get(norm_tag(tag)) or []
    if len(hits) == 1:
        return _placed(pg, node_set, hits[0], "ok", node_id)
    return {"ref": None, "entity_id": None, "equipment_kind": "", "match": "many" if hits else "none", "node_id": node_id}


# ---------------------------------------------------------------- 양식 읽기·쓰기

def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()[:MAX_TEXT]


def read_rows(path):
    """(행 목록 [{키: 글}], 문제 목록). 'FMEA' 시트(없으면 첫 시트)의 1행을 머리글로 읽는다. 한국어·영문 머리글 모두 받는다.
    태그와 고장모드가 모두 빈 줄은 건너뛴다. 수식은 계산하지 않고 글로 둔다(수식 실행 없음)."""
    import os
    import zipfile
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError("파일이 너무 큽니다(%dMB 넘음)" % (MAX_BYTES // (1024 * 1024)))
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise ValueError("Excel(.xlsx) 파일이 아니거나 깨졌습니다(%s)" % type(exc).__name__) from None
    try:
        ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        head = next(it, None) or ()
        names = {}
        for i, h in enumerate(head):
            text = _cell(h).lower()
            for key, ko, en, _w in COLUMNS:
                if text in (ko.lower(), en.lower()):
                    names[i] = key
        miss = [ko for key, ko, _en, _w in COLUMNS if key in ("tag", "failure_mode") and key not in names.values()]
        if miss:
            return [], ["머리글에 %s 열이 없습니다(양식의 1행을 지우지 마세요)" % ", ".join(miss)]
        rows, bad = [], []
        for n, values in enumerate(it, 2):
            r = {names[i]: _cell(v) for i, v in enumerate(values) if i in names}
            if not r.get("tag") and not r.get("failure_mode"):
                continue
            if len(rows) >= MAX_ROWS:
                bad.append("%d행 넘게 있어 %d행까지만 읽었습니다" % (MAX_ROWS, MAX_ROWS))
                break
            r["line"] = n
            rows.append(r)
        return rows, bad
    finally:
        wb.close()


def template_workbook(doc, ec_rows=()):
    """빈 양식(지금 있는 행을 채움, 다시 가져와도 같은 ID). ec_rows: 전기·제어 구간 구성요소 [(구간, 태그, 종류)] 참고 시트."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from hazop.export.study_xlsx import put
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    for c, (_k, ko, _en, w) in enumerate(COLUMNS, 1):
        put(ws, 1, c, ko, bold=True)
        ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = w
    for r, (rid, row) in enumerate(sorted(doc["rows"].items()), 2):
        for c, (k, *_x) in enumerate(COLUMNS, 1):
            put(ws, r, c, rid if k == "row_id" else row.get(k) or "")
    ws.freeze_panes = "A2"
    codes = wb.create_sheet("고장모드 코드")
    put(codes, 1, 1, "코드", bold=True)
    put(codes, 1, 2, "뜻(NUREG/CR-6928 약어표)", bold=True)
    for r, (k, v) in enumerate(FAILURE_MODE_CODES.items(), 2):
        put(codes, r, 1, k)
        put(codes, r, 2, v)
    codes.column_dimensions["B"].width = 44
    if ec_rows:
        ec = wb.create_sheet("전기·제어 구성요소")
        for c, h in enumerate(("구간 ID", "기기 태그", "종류"), 1):
            put(ec, 1, c, h, bold=True)
        for r, row in enumerate(ec_rows, 2):
            for c, v in enumerate(row, 1):
                put(ec, r, c, v)
    guide = wb.create_sheet("읽는 법")
    for r, (k, v) in enumerate((
            ("양식", "DOE-HDBK-1100 표 4.20의 열에 앱이 연결용 열(행 ID, 구간 ID, 관련 HAZOP 항목)을 더했습니다."),
            ("행 ID", "앱이 매깁니다. 다시 가져올 때 같은 행으로 알아보니 지우거나 바꾸지 마세요. 새 행은 비워 두세요."),
            ("기기 태그", "도면의 태그 그대로 적습니다. 도면 구성요소 하나와 맞지 않으면 화면에 '대응 실패'로 따로 보입니다."),
            ("고장모드 코드", "'고장모드 코드' 시트의 코드. 맞는 코드가 없으면 비워 두면 '코드 미정'이 됩니다."),
            ("Severity Class", "받아 두기만 하고 초기사건 인계 묶음에는 넣지 않습니다."),
            ("승인", "가져온 행은 화면에서 사람이 승인해야 기본사건 후보의 출처가 됩니다.")), 1):
        put(guide, r, 1, k, bold=True)
        put(guide, r, 2, v)
    guide.column_dimensions["A"].width = 16
    guide.column_dimensions["B"].width = 90
    ws["A1"].font = Font(bold=True)
    return wb


# ---------------------------------------------------------------- 고치기

def _change(doc, op, ids, at, fn, **detail):
    out = copy.deepcopy(doc)
    value = fn(out)
    out["history"].append(store_io.history_row(op, dict({"ids": list(ids)}, **detail), at))
    return out, value


def _next_id(out):
    out["counters"]["FM"] += 1
    return ID_FORMAT % out["counters"]["FM"]


def _clean(r):
    """가져온 한 줄을 행 필드로. 코드 칸이 비었으면 고장모드 글에서 코드를 찾는다."""
    out = {k: (r.get(k) or "").strip()[:MAX_TEXT] for k in TEXT_FIELDS}
    out["failure_code"] = code_of(out["failure_code"]) or code_of(out["failure_mode"])
    return out


def _import_key(row):
    """행 ID 없는 줄을 맞출 열쇠: 이 행을 마지막으로 가져올 때 파일에 있던 값의 열쇠(사람이 고쳐도 바뀌지 않음, R3)."""
    return row.get("import_key") or row_key(row)


def import_rows(doc, rows, pg, node_set, filename, by, at=None):
    """(새 문서, 보고 {new, changed, same, unmatched, missing, reopened, conflicts, problems}).

    - 같은 행 찾기: '행 ID' 칸이 있으면 그 ID, 없으면 지난 가져오기 때의 파일 값 열쇠(import_key). 사람이 고친 행도 그대로 찾는다.
    - 파일 값이 지난 가져오기와 같은 칸은 지금 값(사람이 고친 값 포함)을 둔다. 파일 값이 바뀐 칸은, 사람이 고친 칸이면 덮지 않고 충돌
      (conflicts)로 남겨 사람이 고르게 하고, 아니면 파일 값으로 고치고 앞값을 이력(before)에 남긴다.
    - 승인한 행의 내용이 바뀌면 가져옴으로 돌린다. 이번 파일에 없는 옛 행은 지우지 않고 in_last_import를 False로 둔다.
    - 같은 열쇠(태그·고장모드·원인·운전 모드)의 다른 행과 겹치는 줄은 넣지 않고 몇째 줄인지와 이유를 problems에 적는다."""
    at = at or store_io.now_utc()
    index = tag_index(pg)
    report = {"new": [], "changed": [], "same": [], "unmatched": [], "missing": [], "reopened": [], "conflicts": [], "problems": []}
    befores = {}

    def apply(o):
        by_import = {_import_key(r): rid for rid, r in o["rows"].items()}
        by_key = {r["key"]: rid for rid, r in o["rows"].items()}
        seen = set()
        for r in rows:
            f = _clean(r)
            if not f["tag"] and not f["failure_mode"]:
                continue
            key = row_key(f)
            line = r.get("line")
            rid = r.get("row_id") if r.get("row_id") in o["rows"] else by_import.get(key)
            if r.get("row_id") and r["row_id"] not in o["rows"]:
                report["problems"].append("%s행: 모르는 행 ID %s — 새 행으로 넣음" % (line, r["row_id"]))
            if rid in seen:
                report["problems"].append("%s행: 같은 행(%s)이 파일에 두 번 있음 — 뒤의 줄은 넣지 않음" % (line, rid))
                continue
            old = o["rows"].get(rid)
            if old is None:
                clash = by_key.get(key)
                if clash is not None:
                    report["problems"].append("%s행: %s와 태그·고장모드·원인·운전 모드가 같음 — 넣지 않음" % (line, clash))
                    continue
                place = match_tag(pg, node_set, f["tag"], (r.get("node_id") or "").strip() or None, index)
                rid = _next_id(o)
                o["rows"][rid] = dict(f, key=key, import_key=key, file_values=dict(f), edited={}, conflicts={},
                                      status="imported", in_last_import=True, **place)
                by_key[key] = by_import[key] = rid
                report["new"].append(rid)
            else:
                prev = old.get("file_values") or {k: old.get(k, "") for k in TEXT_FIELDS}
                new = dict(old)
                before, conflicts = {}, dict(old.get("conflicts") or {})
                for k in TEXT_FIELDS:
                    if f[k] == prev.get(k, ""):
                        continue                                  # 파일 값이 그대로면 지금 값(사람이 고친 값 포함)을 둔다
                    if k in (old.get("edited") or {}) and f[k] != old.get(k, ""):
                        conflicts[k] = f[k]                       # 사람이 고친 칸을 파일이 다르게 바꿈: 덮지 않고 고르게 한다
                        continue
                    if old.get(k, "") != f[k]:
                        before[k] = old.get(k, "")
                        new[k] = f[k]
                if "tag" in before and old.get("match") != "human":
                    new.update(match_tag(pg, node_set, new["tag"], (r.get("node_id") or "").strip() or None, index))
                new_key = row_key(new)
                if new_key != old["key"] and by_key.get(new_key) not in (None, rid):
                    report["problems"].append("%s행: 바꾸면 %s와 태그·고장모드·원인·운전 모드가 같아짐 — 이 줄은 넣지 않음" % (line, by_key[new_key]))
                    seen.add(rid)
                    continue
                new.update(key=new_key, import_key=key, file_values=dict(f), conflicts=conflicts, in_last_import=True)
                if before:
                    befores[rid] = before
                    report["changed"].append(rid)
                    if new["status"] == "approved":
                        new["status"] = "imported"
                        report["reopened"].append(rid)
                else:
                    report["same"].append(rid)
                if set(conflicts) - set(old.get("conflicts") or {}):
                    report["conflicts"].append(rid)
                by_key.pop(old["key"], None)
                by_key[new_key] = rid
                o["rows"][rid] = new
            seen.add(rid)
            if o["rows"][rid]["ref"] is None:
                report["unmatched"].append(rid)
        for rid, row in o["rows"].items():
            if rid not in seen and row.get("in_last_import", True):
                row["in_last_import"] = False
                report["missing"].append(rid)
        o["imports"].append({"at": at, "file": filename, "by": by, "rows": len(seen),
                             **{k: len(report[k]) for k in ("new", "changed", "unmatched", "missing", "conflicts")}})
    out, _ = _change(doc, "import", [], at, apply, file=filename, by=by)
    if befores:
        out["history"][-1]["before"] = befores                    # 파일 값으로 덮은 칸의 앞값(행별)
    return out, report


def edit_row(doc, rid, fields, pg, node_set, at=None):
    """행 필드를 고친다(EDITABLE). 고친 글 칸은 edited에 적어 다시 가져오기가 덮지 않게 한다. entity_id를 주면 사람이 고른 대응,
    태그만 바꾸면 다시 대응한다. 내용이 바뀌면 승인이 풀린다. 앞값은 이력에 남는다."""
    row = doc["rows"].get(rid)
    if row is None:
        raise ValueError("없는 FMEA 행: %s" % rid)
    unknown = sorted(set(fields) - set(EDITABLE))
    if unknown:
        raise ValueError("고칠 수 없는 필드: %s" % ", ".join(unknown))
    for k, v in fields.items():
        if v is not None and not isinstance(v, str):
            raise ValueError("%s는 글이어야 함" % k)
    if fields.get("failure_code") and not code_of(fields["failure_code"]):
        raise ValueError("목록에 없는 고장모드 코드: %s (%s)" % (fields["failure_code"], "/".join(FAILURE_MODE_CODES)))
    new = {k: (v or "").strip()[:MAX_TEXT] for k, v in fields.items() if k not in ("entity_id", "node_id")}
    if "failure_code" in new:
        new["failure_code"] = code_of(new["failure_code"])
    place = None
    if fields.get("entity_id"):
        n = next((x for x in pg.get("nodes") or [] if x.get("entity_id") == fields["entity_id"]), None)
        if n is None or not migrate.ref_of(n, pg.get("graph_id")):
            raise ValueError("도면에 없는 구성요소: %s" % fields["entity_id"])
        place = _placed(pg, node_set, n, "human", fields.get("node_id"))
    elif "tag" in new and norm_tag(new["tag"]) != norm_tag(row["tag"]):
        place = match_tag(pg, node_set, new["tag"], fields.get("node_id"))
    elif fields.get("node_id") is not None:
        homes = _nodes_of(node_set, row.get("entity_id")) if row.get("entity_id") else []
        if fields["node_id"] and fields["node_id"] not in homes:
            raise ValueError("%s 구간에는 이 구성요소가 없습니다" % fields["node_id"])
        place = {"node_id": fields["node_id"] or None}
    merged = dict(row, **new, **(place or {}))
    merged["key"] = row_key(merged)
    if merged["key"] != row["key"] and any(r["key"] == merged["key"] for x, r in doc["rows"].items() if x != rid):
        raise ValueError("같은 태그·고장모드·원인·운전 모드의 행이 이미 있습니다")
    if {k: merged.get(k) for k in CONTENT} == {k: row.get(k) for k in CONTENT}:
        return doc
    changed = [k for k in new if new[k] != row.get(k, "")]

    def apply(o):
        r = o["rows"][rid]
        before = {k: r.get(k) for k in CONTENT if r.get(k) != merged.get(k)}
        reopened = r["status"] == "approved"
        r.update(merged)
        r["edited"] = dict(r.get("edited") or {}, **{k: merged[k] for k in changed})
        r["conflicts"] = {k: v for k, v in (r.get("conflicts") or {}).items() if k not in changed}   # 사람이 다시 고르면 충돌은 풀림
        if reopened:
            r["status"] = "imported"
        return before, reopened
    out, (before, reopened) = _change(doc, "edit", [rid], at, apply)
    out["history"][-1].update(before=before, reopened=reopened)
    return out


def resolve_conflict(doc, rid, field, take, at=None):
    """다시 가져오기 충돌 하나를 사람이 고른다. take='file'이면 파일 값을 쓰고(앞값은 이력, 승인은 풀림), 'mine'이면 지금 값을 둔다."""
    row = doc["rows"].get(rid)
    if row is None or field not in (row.get("conflicts") or {}):
        raise ValueError("%s 행의 %s 칸에 충돌이 없습니다" % (rid, field))
    if take not in ("file", "mine"):
        raise ValueError("take는 file 또는 mine")
    file_value = row["conflicts"][field]

    def apply(o):
        r = o["rows"][rid]
        r["conflicts"].pop(field)
        if take == "file":
            before = r.get(field, "")
            r[field] = file_value
            r["edited"].pop(field, None)
            r["key"] = row_key(r)
            if r["status"] == "approved":
                r["status"] = "imported"
            return before
        return None
    if take == "file":
        merged = dict(row, **{field: file_value})
        if any(r["key"] == row_key(merged) for x, r in doc["rows"].items() if x != rid):
            raise ValueError("파일 값을 쓰면 다른 행과 열쇠가 같아집니다")
    out, before = _change(doc, "resolve", [rid], at, apply, field=field, take=take)
    if take == "file":
        out["history"][-1]["before"] = {field: before}
    return out


def set_status(doc, rids, status, by, at=None):
    """사람이 행을 승인·제외하거나 가져옴으로 되돌린다. 대응하지 않은 행은 승인하지 못한다."""
    if status not in STATUSES:
        raise ValueError("상태 값 %r(%s)" % (status, "/".join(STATUSES)))
    if not (by or "").strip():
        raise ValueError("검토자 이름이 있어야 합니다")
    for rid in rids:
        r = doc["rows"].get(rid)
        if r is None:
            raise ValueError("없는 FMEA 행: %s" % rid)
        if status == "approved" and not r.get("ref"):
            raise ValueError("%s: 도면 구성요소에 대응하지 않아 승인할 수 없습니다(구성요소를 먼저 고르세요)" % rid)
    todo = [rid for rid in rids if doc["rows"][rid]["status"] != status]
    if not todo:
        return doc

    def apply(o):
        for rid in todo:
            o["rows"][rid]["status"] = status
    return _change(doc, "status", todo, at, apply, to=status, by=by.strip())[0]


def set_node_mark(doc, node_id, mark, at=None):
    """전기·제어 구간 사람 표시(include/exclude, None이면 지움). 규칙보다 앞선다(§8.2 질문 7)."""
    if mark is not None and mark not in MARKS:
        raise ValueError("표시 값 %r(%s)" % (mark, "/".join(MARKS)))
    if doc["node_marks"].get(node_id) == mark:
        return doc

    def apply(o):
        if mark is None:
            o["node_marks"].pop(node_id, None)
        else:
            o["node_marks"][node_id] = mark
    return _change(doc, "node_mark", [node_id], at, apply, mark=mark)[0]


# ---------------------------------------------------------------- 대조

CONTROL_CATEGORY = "instrument"
# 전기로 움직이거나 제어 신호를 받는 밸브. P&ID에 전동기·전원은 따로 그려지지 않아 펌프·팬의 전동기는 세지 못한다 [추론]
ELECTRIC_KINDS = frozenset({"motor_operated_valve", "solenoid_valve", "control_valve"})


def rule_nodes(node_set, pg):
    """규칙이 고른 전기·제어 구간: 계기·제어 구성요소나 전동·제어·솔레노이드 밸브가 든 구간(검토구간 순서) [추론]."""
    control = {n["entity_id"] for n in pg.get("nodes") or []
               if n.get("category") == CONTROL_CATEGORY or n.get("kind") in ELECTRIC_KINDS}
    return [n["node_id"] for n in node_set.get("nodes") or [] if control & set(n.get("members") or [])]


def ec_nodes(node_set, pg, doc=None, among=None):
    """전기·제어 구간 = 규칙 + 사람 표시(include 더함, exclude 뺌). among을 주면 그 안에서만."""
    marks = (doc or {}).get("node_marks") or {}
    rule = set(rule_nodes(node_set, pg))
    out = [n["node_id"] for n in node_set.get("nodes") or []
           if (marks.get(n["node_id"]) == "include" or (n["node_id"] in rule and marks.get(n["node_id"]) != "exclude"))]
    return [x for x in out if among is None or x in among]


def approved(doc):
    return [(rid, r) for rid, r in sorted(((doc or {}).get("rows") or {}).items()) if r["status"] == "approved"]


def done_nodes(node_set, doc=None):
    """승인 FMEA 행이 있는 구간: 행의 구성요소를 품은 구간 모두(겹친 구간이면 여럿)와 사람이 적은 구간."""
    ents = {r.get("entity_id") for _rid, r in approved(doc) if r.get("entity_id")}
    out = {r.get("node_id") for _rid, r in approved(doc) if r.get("node_id")}
    out |= {n["node_id"] for n in node_set.get("nodes") or [] if ents & set(n.get("members") or [])}
    return out


def pending_nodes(node_set, pg, analysed, doc=None):
    """'FMEA 대조 전' 구간: 승인 항목이 있는 전기·제어 구간 가운데 승인 FMEA 행이 하나도 없는 구간(done_nodes 밖)."""
    done = done_nodes(node_set, doc)
    return [n for n in ec_nodes(node_set, pg, doc, among=analysed) if n not in done]


def live_sources(doc):
    """기본사건 출처 열쇠 가운데 승인 FMEA 행인 것('fmea:FM-001')."""
    return frozenset(SOURCE_PREFIX + rid for rid, _r in approved(doc))


def be_key(row):
    """승인 FMEA 행이 가리키는 기본사건 열쇠: (안정 참조, 고장모드 코드 — 없으면 고장모드 글). HAZOP 규칙 초안과 같은 꼴."""
    return "%s|%s" % (row["ref"], row["failure_code"] or row["failure_mode"])


def sync_basic_events(ie_doc, doc, at=None):
    """⑥ 기본사건 후보를 FMEA 행에 맞춘다. 할 일이 없으면 받은 문서를 그대로 돌려준다.

    1) 기본사건에 달린 FMEA 출처('fmea:FM-001') 가운데 그 행이 없어졌거나, 승인 행인데 지금 열쇠(be_key)가 그 기본사건의 열쇠와 다르면
       (구성요소·고장모드를 고침) 출처를 뗀다(R1). FMEA에서만 온 기본사건(origin 'fmea')에 출처가 하나도 안 남으면 지운 기록이 되어
       묶음에서 빠진다. ID는 남아 다시 쓰지 않고, 같은 열쇠가 다시 승인되면 그 ID로 되살린다.
    2) 승인 FMEA 행마다 같은 열쇠의 기본사건(HAZOP 후보든 FMEA 후보든)을 찾아 출처를 더하고, 없으면 origin 'fmea'로 새로 만든다.
       사람이 받아들인 기본사건에는 출처만 더한다."""
    rows = dict((doc or {}).get("rows") or {})
    want = {rid: be_key(r) for rid, r in rows.items() if r["status"] == "approved" and r.get("ref")}
    detach = []
    for bid, b in ie_doc["basic_events"].items():
        for s in b["sources"]:
            if s["kind"] != "fmea":
                continue
            rid = s["key"][len(SOURCE_PREFIX):]
            if rid not in rows or (rid in want and want[rid] != b["key"]):
                detach.append((bid, s))
    live = {v["key"]: k for k, v in sorted(ie_doc["basic_events"].items()) if v["status"] == "live"}
    revive = {v["key"]: k for k, v in sorted(ie_doc["basic_events"].items()) if v["status"] == "deleted" and v["origin"] == "fmea"}
    attach = []
    for rid, key in sorted(want.items()):
        src = {"kind": "fmea", "key": SOURCE_PREFIX + rid}
        bid = live.get(key) or revive.get(key)
        if bid is None or src not in ie_doc["basic_events"][bid]["sources"] or ie_doc["basic_events"][bid]["status"] != "live":
            attach.append((rid, key, src))
    if not detach and not attach:
        return ie_doc

    def apply(o):
        removed = []
        for bid, s in detach:
            b = o["basic_events"][bid]
            if s in b["sources"]:
                b["sources"].remove(s)
                removed.append([bid, s["key"]])
            if b["origin"] == "fmea" and not b["sources"] and b["status"] == "live":
                b["status"] = "deleted"
        by_key = {v["key"]: k for k, v in sorted(o["basic_events"].items()) if v["status"] == "live"}
        dead = {v["key"]: k for k, v in sorted(o["basic_events"].items()) if v["status"] == "deleted" and v["origin"] == "fmea"}
        for rid, key, src in attach:
            r = rows[rid]
            bid = by_key.get(key)
            if bid is None and key in dead:
                bid = dead[key]
                o["basic_events"][bid]["status"] = "live"
                by_key[key] = bid
            if bid is None:
                bid = model._next_id(o, "BE")
                tag = r["tag"]
                mode = r["failure_code"] or r["failure_mode"]
                o["basic_events"][bid] = {"key": key, "ref": r["ref"], "tag": tag,
                                          "name": model._be_name({"kind": r.get("equipment_kind")}, tag, mode),
                                          "equipment_kind": r.get("equipment_kind") or "",
                                          "system": tag.partition("-")[0] if "-" in tag else "", "failure_mode": r["failure_code"],
                                          "failure_text": r["failure_mode"], "sources": [], "heading_ids": [], "origin": "fmea",
                                          "status": "live"}
                by_key[key] = bid
            if src not in o["basic_events"][bid]["sources"]:
                o["basic_events"][bid]["sources"].append(src)
        return removed
    out, removed = model._change(ie_doc, "fmea_sync", [rid for rid, *_x in attach], [], at, apply)
    if removed:
        out["history"][-1]["detached"] = removed
    return out
