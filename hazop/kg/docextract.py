"""PDF 설계 문서 -> 지식 입력(knowledge.json과 같은 노드·관계 레코드). 규칙 기반, AI 없음, 결정적.

근거: 기획서/그래프활용.md §2.2(노드 종류), §2.4(근거 필드), §2.6(후속 문서 추출기는 같은 계약), §9(자동 생성).
- 글자는 pdfplumber `extract_text()`로 쪽마다 읽는다. 스캔 PDF(글자 없음)는 읽지 않는다(OCR 없음).
- 문서 조각(doc_chunk) = 쪽 안의 절(번호 붙은 제목 줄부터 다음 제목 줄 전까지). 근거 위치는 '<쪽>쪽 · <절 제목> · 줄 a–b'.
- 문장 규칙:
  * 값(숫자+단위) 앞에 설정치 낱말(경보·트립·설정치·설정압력 등)이 있으면 setpoint, 운전·설계 조건 낱말(운전압력·설계온도 등)이
    있으면 condition. 낱말이 없으면 값을 만들지 않는다(추정하지 않음). 압력 기준은 단위 뒤 (g)/(a)·g/a로만 읽고, 없으면 미확인.
  * '~해야 한다'·'~면 … 한다' 같은 요건 문장, '설계 의도'·'목적' 문장은 requirement.
  * 태그(예: RC-PIC110)는 문장별로 기록만 한다. 도면과의 연결은 hazop.kg.auto가 후보 관계로 만든다.
- 모든 항목은 method=extractor, knowledge_status=unknown(자동 추출, 사람 확인 전)이다. 찾지 못한 값은 null(미확인)과 사유.
  문서 노드만 등록 자료 자체이므로 confirmed다.
"""

import hashlib
import io
import re

EXTRACTOR = "hazop.kg.docextract"
EXTRACTOR_VERSION = "0.1.2"   # 0.1.2: 문서 번호·개정(doc_number·revision)을 첫 쪽에서 읽는다
SCHEMA_VERSION = "0.1"
AUTHOR = "자동 추출(%s)" % EXTRACTOR
AUTO_REASON = "자동 추출 — 사람 확인 전"
MISSING_REASON = "자동 추출에서 찾지 못함(미확인)"
NODE_VALUE_FIELDS = ("name", "text", "item", "value", "unit", "pressure_basis", "operating_mode")
SOURCE_FIELDS = ("material_id", "registration_version", "document_id", "page", "locator")

HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.{0,48})$")
PAGE_NO_RE = re.compile(r"^\s*-?\s*\d{1,4}\s*-?\s*$")  # 쪽 번호만 있는 줄(머리말·꼬리말)
SENT_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+")
TAG_RE = re.compile(r"(?<![A-Za-z0-9-])[A-Z]{1,5}-[A-Z]{1,6}\d{1,5}[A-Z]?(?:-[A-Z0-9]+)?(?![A-Za-z0-9])")
# 단위(긴 것 먼저). 압력 단위 뒤의 (g)/(a)·g/a는 압력 기준.
PRESSURE_UNITS = (r"kgf/cm2", r"kgf/cm²", r"kg/cm2", r"kg/cm²", r"MPa", r"kPa", r"bar", r"psi")
OTHER_UNITS = (r"°C", r"℃", r"°F", r"m3/h", r"m³/h", r"kg/s", r"t/h", r"L/min", r"gpm", r"rpm", r"mm", r"%", r"K")
VALUE_RE = re.compile(
    r"(?<![\w.+\-])(?P<value>[-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?:(?P<punit>%s)(?:\s*\(\s*(?P<basis1>[gGaA])\s*\)|(?P<basis2>[gGaA])(?![A-Za-z]))?|(?P<ounit>%s))"
    r"(?![A-Za-z²³/])" % ("|".join(PRESSURE_UNITS), "|".join(re.escape(u) for u in OTHER_UNITS)))
BASIS = {"g": "gauge", "a": "absolute"}
# (노드 종류, 낱말 정규식). 항목(item)은 낱말 일치 원문(공백 하나로 정리). 설정치를 먼저 본다('설정압력'의 '압력').
SETPOINT_WORDS = re.compile(r"(?:(?:고|저)(?:압|수위|온|유량)\s*)?(?:경보|트립)(?:\s*설정(?:치|값))?|설정\s*(?:압력|온도)|"
                            r"설정(?:치|값)|set\s*point|trip|alarm", re.I)
CONDITION_WORDS = re.compile(r"(?:운전|설계|최대|최소)\s*(?:압력|온도|유량|수위)|"
                             r"(?:operating|design)\s+(?:pressure|temperature|flow)", re.I)
MODE_WORDS = re.compile(r"정상\s*운전|기동|고온\s*대기|저온\s*정지|normal\s+operation|startup|shutdown", re.I)
REQUIREMENT_RE = re.compile(r"야\s*한다|할\s*것|않아야|\bshall\b|\bmust\b|"
                            r"(?:높아|낮아|올라가|내려가|상실되|초과하|도달하|넘으)(?:지)?면")
# 같은 문서의 새 판을 가리는 근거(첫 쪽 머리). 못 읽으면 None이고, 그때는 등록할 때 사람에게 묻는다(hazop.kg.doc_revisions)
DOC_NO_RE = re.compile(r"(?:문서\s*번호|도서\s*번호|document\s*(?:no\.?|number))\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{2,40})", re.I)
REV_RE = re.compile(r"(?:개정(?:\s*번호)?|rev(?:ision)?\.?)\s*[:：]?\s*([0-9]{1,3}|[A-Z]{1,2})(?![A-Za-z0-9])", re.I)
INTENT_RE = re.compile(r"설계\s*의도|목적은|기능은|design\s+intent", re.I)


class DocExtractError(ValueError):
    pass


def _ws(s):
    return re.sub(r"\s+", " ", s).strip()


def read_pages(source):
    """PDF(경로·바이트·파일 객체) -> [(쪽 번호 1부터, [줄])]. pdfplumber가 없거나 읽기 실패면 DocExtractError."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise DocExtractError("PDF를 읽을 pdfplumber가 없음") from exc
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    try:
        with pdfplumber.open(source) as pdf:
            return [(i, (p.extract_text() or "").splitlines()) for i, p in enumerate(pdf.pages, 1)]
    except Exception as exc:  # 손상·암호화 등
        raise DocExtractError("PDF를 읽을 수 없음: %s" % exc) from exc


def _join(lines):
    """줄을 이어 붙인다. 줄 끝이 '영문자-'이면(태그가 줄에서 끊김) 공백 없이 잇는다."""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if out and re.search(r"[A-Z]-$", out):
            out += ln
        else:
            out = (out + " " + ln) if out else ln
    return out


def sections(pages):
    """[(쪽, 제목 또는 None, 시작 줄, 끝 줄, 본문)] — 쪽마다 제목 줄에서 끊는다. 쪽 번호 줄은 버린다."""
    out = []
    carry = None  # 앞 쪽에서 이어지는 절 제목
    for page, lines in pages:
        cur = {"title": carry, "start": None, "end": None, "lines": [], "cont": carry is not None}
        for no, raw in enumerate(lines, 1):
            ln = raw.strip()
            if not ln or PAGE_NO_RE.match(ln):
                continue
            m = HEADING_RE.match(ln)
            if m and not ln.endswith(("다.", "다", ".")) and not VALUE_RE.search(ln):  # 값으로 시작하는 본문 줄은 제목 아님
                if cur["lines"]:
                    out.append(cur)
                cur = {"title": _ws(ln), "start": no, "end": no, "lines": [], "cont": False}
                continue
            cur["lines"].append(ln)
            cur["start"] = cur["start"] or no
            cur["end"] = no
        if cur["lines"]:
            out.append(cur)
        carry = cur["title"]
        for c in out:
            c.setdefault("page", page)
    return [(c["page"], c["title"], c["start"], c["end"], _join(c["lines"]), c["cont"]) for c in out]


def _locator(page, title, start, end, cont):
    where = ("'%s'%s" % (title, " (이어짐)" if cont else "")) if title else "제목 없는 부분"
    return "%s쪽 · %s · 줄 %s–%s" % (page, where, start, end)


def _values(sentence):
    """문장 -> [(종류, 항목, 값, 단위, 압력 기준, 운전 모드, 태그 목록)]. 값마다 자기 마디(앞 값 뒤부터 이 값 앞까지)의
    낱말·운전 모드·태그만 본다(다른 값의 낱말·설비를 빌리지 않음). 마디에 낱말이 없는 값은 버린다.
    태그·운전 모드가 마디에 없고 문장에 값이 하나뿐이면 문장 전체에서 찾는다."""
    found = list(VALUE_RE.finditer(sentence))
    out, prev = [], 0
    for m in found:
        seg, prev = sentence[prev:m.start()], m.end()
        sp, cd = list(SETPOINT_WORDS.finditer(seg)), list(CONDITION_WORDS.finditer(seg))
        if not sp and not cd:
            continue
        # 마디 안에서 값에 가장 가까운(가장 늦게 끝나는) 낱말을 쓴다
        kind, hit = max([("setpoint", h) for h in sp] + [("condition", h) for h in cd], key=lambda kh: kh[1].end())
        scope = sentence if len(found) == 1 else seg
        tags = sorted(set(TAG_RE.findall(seg))) or (sorted(set(TAG_RE.findall(sentence))) if len(found) == 1 else [])
        mode = MODE_WORDS.search(seg) or (MODE_WORDS.search(scope))
        unit = m.group("punit") or m.group("ounit")
        basis = (m.group("basis1") or m.group("basis2") or "").lower() or None
        out.append((kind, _ws(hit.group(0)), m.group("value").replace(",", ""), unit, BASIS.get(basis) if basis else None,
                    _ws(mode.group(0)) if mode else None, tags))
    return out


def _node(nid, ntype, source, status="unknown", reason=AUTO_REASON, **values):
    rec = {"id": nid, "node_type": ntype}
    rec.update({f: values.get(f) for f in NODE_VALUE_FIELDS})
    rec["source"] = dict(source, unregistered_reason=None)
    rec.update({"method": "extractor", "extractor": "%s %s" % (EXTRACTOR, EXTRACTOR_VERSION), "confidence": None,
                "knowledge_status": status, "author": AUTHOR, "reason": reason})
    rec["null_reasons"] = {f: MISSING_REASON for f in NODE_VALUE_FIELDS if rec.get(f) is None}
    rec["null_reasons"].update({f: MISSING_REASON for f in SOURCE_FIELDS if source.get(f) is None})
    return rec


def link_record(lid, kind, frm, to, reason=AUTO_REASON):
    """자동 관계 레코드(hazop.kg.inputs.link_record와 같은 키). 근거 열은 비워 지식 쪽 끝 노드 근거를 상속한다(§2.4)."""
    return {"id": lid, "kind": kind, "from": frm, "to": to, "method": "extractor",
            "extractor": "%s %s" % (EXTRACTOR, EXTRACTOR_VERSION), "confidence": None,
            "knowledge_status": "unknown", "link_status": "candidate",
            "source": {f: None for f in SOURCE_FIELDS} | {"unregistered_reason": None},
            "author": AUTHOR, "reviewed_by": None, "reviewed_at": None, "reason": reason, "mention": None,
            "unused_mention_columns": []}


def identity(pages):
    """첫 쪽(없으면 둘째 쪽) 글에서 (문서 번호, 개정). 못 읽은 값은 None."""
    text = " ".join(" ".join(lines) for _, lines in pages[:2])
    m, r = DOC_NO_RE.search(text), REV_RE.search(text)
    return (m.group(1).rstrip(".-/") if m else None), (r.group(1).upper() if r else None)


def extract(pages, material_id, registration_version, document_id, title=None, source_sha256=None):
    """쪽 목록(read_pages 결과) -> 문서 지식 dict. ID는 자료 ID(해시 12자리)·쪽·순번으로 결정적으로 만든다."""
    key = (material_id or "unregistered").split("-")[-1]
    base = {"material_id": material_id, "registration_version": None if registration_version is None
            else str(registration_version), "document_id": document_id, "page": None, "locator": None}
    doc_id = "doc-%s" % key
    nodes = [_node(doc_id, "document", base, status="confirmed", reason="등록 자료(①) — 문서 자체",
                   name=title or document_id)]
    links, mentions = [], []
    counts = {"doc_chunk": 0, "setpoint": 0, "condition": 0, "requirement": 0}
    secs = sections(pages)
    seq = {}
    for page, sec_title, start, end, text, cont in secs:
        seq[page] = seq.get(page, 0) + 1
        cid = "chunk-%s-p%d-%02d" % (key, page, seq[page])
        src = dict(base, page=str(page), locator=_locator(page, sec_title, start, end, cont))
        nodes.append(_node(cid, "doc_chunk", src, name=sec_title, text=text))
        counts["doc_chunk"] += 1
        links.append(link_record("krel-%s-part" % cid, "part_of", cid, doc_id))
        n = 0
        for sent in (s.strip() for s in SENT_SPLIT_RE.split(text)):
            if not sent:
                continue
            made = []  # (노드 ID, 그 노드에 걸리는 태그)
            for kind, item, value, unit, basis, mode, tags in _values(sent):
                n += 1
                nid = "%s-%s-p%d-%02d-%02d" % ("setpt" if kind == "setpoint" else "cond", key, page, seq[page], n)
                nodes.append(_node(nid, kind, src, text=sent, item=item, value=value, unit=unit,
                                   pressure_basis=basis, operating_mode=mode))
                made.append((nid, tags))
                counts[kind] += 1
            if REQUIREMENT_RE.search(sent) or INTENT_RE.search(sent):
                n += 1
                nid = "req-%s-p%d-%02d-%02d" % (key, page, seq[page], n)
                nodes.append(_node(nid, "requirement", src, text=sent,
                                   item="설계 의도" if INTENT_RE.search(sent) else None))
                made.append((nid, sorted(set(TAG_RE.findall(sent)))))
                counts["requirement"] += 1
            for nid, tags in made:
                links.append(link_record("krel-%s-spec" % nid, "specified_in", nid, cid))
                if tags:
                    mentions.append({"node_id": nid, "tags": tags})
    unknowns = [{"check": "unknown_value", "target": nd["id"], "field": f, "reason": MISSING_REASON}
                for nd in nodes if nd["node_type"] in ("setpoint", "condition")
                for f in ("unit", "pressure_basis") if nd.get(f) is None]
    blockers = []
    if not any(text for _, _, _, _, text, _ in secs):
        blockers.append({"check": "no_text", "target": material_id,
                         "reason": "PDF에서 글자를 읽지 못함(스캔 PDF는 지원하지 않음, OCR 없음)"})
    return {
        "schema_version": SCHEMA_VERSION,
        "extractor": {"name": EXTRACTOR, "version": EXTRACTOR_VERSION},
        "material_id": material_id, "registration_version": registration_version, "document_id": document_id,
        "title": title, "source_sha256": source_sha256, "page_count": len(pages),
        "doc_number": identity(pages)[0], "revision": identity(pages)[1],
        "nodes": nodes, "links": links, "tag_mentions": mentions,
        "summary": dict(counts, links=len(links), tag_mentions=len(mentions)),
        "validation": {"status": "blocked" if blockers else "passed", "blockers": blockers, "unknowns": unknowns},
    }


def extract_pdf(path, material_id, registration_version, document_id, title=None):
    with open(path, "rb") as fh:
        data = fh.read()
    return extract(read_pages(data), material_id, registration_version, document_id, title,
                   hashlib.sha256(data).hexdigest())
