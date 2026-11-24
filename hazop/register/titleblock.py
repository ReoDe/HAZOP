"""표제란 값(도면 번호·개정·제목)의 후보와 사람 확정(INTENT §3.1, 완료 목록 2 A3, 화면 규격 HZ-DSN-05 '표제란 후보 확정').

표제란에서 읽은 값은 등록정보의 `auto_candidates`에 후보로만 있고, 사람이 확정한 값만 등록정보의 `drawing_number`·`design_revision`·
`title`에 들어간다(hazop.register.registry). 이 모듈은 그 둘을 화면·채팅이 쓸 꼴로 보이고, 확정·확정 취소를 엔진 한 곳에서 한다.
Qt를 import하지 않는다. 명령 표는 docs/units/2026-11-13-drawing-knowledge/evidence/titleblock-commands.md.

- view(project_id): 자료(도면)마다 세 항목의 확정값·후보·근거(읽은 자리)·누가 언제 확정했는가, 상태, 판 표시(ver).
- confirm(project_id, material_id, fields, by, ver): 후보 그대로 또는 고친 값으로 확정. unconfirm(..., field_names): 확정 취소.
- execute(project_id, command, args, by, ver): 채팅이 부를 실행 함수(view·confirm·unconfirm).

확정하면 등록정보에 새 등록 버전이 생기고(이력 confirm_metadata·unconfirm_metadata), 이미 추출한 도면이면 새 버전으로 다시 추출한다.
추출 결과 폴더 이름에는 등록 버전이 들어가므로(`<프로젝트>__<자료>-r<버전>-p<쪽>`) 다시 추출하기 **전에** 지금 쪽의 사람 수정 기록과
AI 후보 기록을 새 이름으로 옮겨 쓰고(그래야 새 그래프가 사람 수정을 담는다, 앞 파일은 지우지 않음), 앞 버전의 graph.json은
graph.superseded.json으로 비켜 둔다(한 도면이 프로젝트 그래프에 두 번 들어가지 않게). 다시 추출이 실패하면 비켜 둔 그래프를 되돌리고,
그 자료는 '다시 읽기 필요'로 보인다. 같은 확정을 다시 하면 새 버전 없이 다시 읽기만 한다. 쪽 확정 기록은 옮기지 않는다(추출 결과가
바뀌어 어차피 풀리고, 사람이 바뀐 도면을 다시 보고 확정해야 한다).

'지금 쪽'은 쪽마다 추출 결과가 있는 가장 새 등록 버전이다(다시 추출이 실패해 최신 버전에는 추출이 없을 수 있다).

도면 번호는 그래프 ID(`graph-<도면 번호>`)이고 검토구간·분석 결과의 열쇠다(파일 이름은 paths.safe_name, Windows에서는 대소문자 무시).
- 그래프 ID가 바뀌는 확정·취소·번호 바꾸기는 같은 자료의 1:1 이름 바뀜이면 판 이전이 구간·분석 결과·초기사건·FMEA·잠재 후보 판단을 새 이름으로
  옮긴다(hazop.study.idmap.sheet_pairs). 가드는 기록 자리를 옮김(CARRY)과 막음(BLOCK)으로 나눈 표(_places)로 센다. 허락 조건은 넷이다:
  이 자료가 옛 이름의 주인, 확정 뒤 새 이름의 주인(sources.owner_if), 구간 저장본의 판 사진으로 짝이 증명됨, 막음 자리의 참조 0
  (번호가 바뀌는 쪽이면 번호로 적는 기록과 이 도면에 닿는 도면 연결 구간도 막음). 하나라도 안 되면 막고, 거절 글에 막는 자리와 할 일을 적는다.
  dry와 실제 결과에 carries {자리: 수}(옮길 기록)·renames [{from, to, from_label, to_label}]를 싣는다.
- 새 ID의 파일 열쇠가 다른 자료의 그래프 ID(확정 번호 또는 확정 전 쪽 이름에서 온 것)와 같으면: 글자가 다르면(대소문자·특수 문자만
  다름) 막고, 글자가 같고 형식도 같으면 막고, 형식이 다르면(drawio·PDF·DEXPI) 막지 않고 충돌을 알린다(hazop.graph.sources의 길).
- 여러 쪽 자료(PDF 여러 쪽)는 번호를 확정하지 않는다(사유 multi_page_number, 쪽별 확정은 후속). 그 전에 받아 둔 자료 번호는 이름에 쓰이지
  않으므로 취소는 막지 않는다. 임시 이름 꼴 번호(material-…-p쪽)는 받지 않는다(reserved_number).
- 지금 이름의 참조는 이 쪽이 그 이름의 주인일 때만 센다(같은 번호의 다른 파일, 정착 전에 가려진 도면은 남의 구간 때문에 갇히지 않음).
- 번호를 바꾸기 전에 시트 자리를 정착해(정착 전 프로젝트만) 예측 이름이 다시 추출 뒤의 이름과 같게 한다.
- 거절 줄은 {target, code, reason, reason_code}. reason_code는 REASON_CODES 가운데 하나(가드가 아닌 거절은 None).
"""

import csv
import io
import json
import logging
import os
import re
import unicodedata

from hazop import paths, store_io
from hazop.graph import sheets as sheet_rules
from hazop.register import registry

FIELDS = (("drawing_number", "도면 번호"), ("design_revision", "개정"), ("title", "제목"))
LABELS = dict(FIELDS)
COMMANDS = ("view", "confirm", "unconfirm")
CODES = ("unknown_command", "bad_actor", "bad_args", "stale", "not_found", "rule", "conflict", "io")
MAX_VALUE = 200
SUPERSEDED = "graph.superseded.json"
LOG = logging.getLogger(__name__)
# 도면 번호 가드의 사유 코드(거절 줄의 reason_code). 번호 꼴 사유 셋은 hazop.graph.sheets와 같은 값이다.
HAS_RECORDS = "sheet_has_records"            # 그 도면을 가리키는 사람 기록이 있어 번호를 바꾸면 끊김
CHOICE_PINNED = "source_choice_pinned"       # 그 번호에 사람이 고른 원본 형식이 걸려 있음
NUMBER_TAKEN = "number_taken"                # 다른 자료가 같은(또는 글자만 다른) 번호를 씀
REASON_CODES = (sheet_rules.CONFIRM_FIRST, sheet_rules.NUMBER_HELD, sheet_rules.NUMBER_RESERVED, HAS_RECORDS, CHOICE_PINNED,
                NUMBER_TAKEN)


class Refused(Exception):
    def __init__(self, target, code, reason, reason_code=None):
        Exception.__init__(self, reason)
        self.row = {"target": target, "code": code, "reason": reason, "reason_code": reason_code}


# ---------------------------------------------------------------- 읽기

def _store_root(store_root):
    return store_root or paths.store_root()


def _materials(project_id, store_root):
    store = registry.Store(_store_root(store_root), project_id)
    if not os.path.isfile(store.index_path):
        return []
    return [m["material_id"] for m in store.load_index(project_id)["materials"] if m.get("versions")]


def _out_name(record, page, version=None):
    from hazop.app import data
    rec = record if version is None else dict(record, registration_version=version)
    return data.script_module("extract_drawio").registered_out_name(rec, page)


def _page_count(record):
    return sum(len(d.get("page_ids") or []) for d in record.get("documents") or []) or 1


def _graph_id_of(extraction, project_id):
    """그래프를 지을 때와 같은 규칙의 그래프 ID(hazop.graph.sources.sheet_name)."""
    from hazop.graph import sources
    return sources.sheet_name(project_id, extraction)


def _built_graph_id(name):
    """그 폴더의 graph.json이 지닌 그래프 ID(프로젝트 그래프가 이 쪽을 부르는 이름) 또는 None(아직 짓지 않았거나 비켜 둠)."""
    try:
        with open(os.path.join(paths.output_root("graph"), name, "graph.json"), encoding="utf-8") as fh:
            return json.load(fh).get("graph_id")
    except (OSError, ValueError, AttributeError):
        return None


def _sheets(record):
    """쪽마다 추출 결과가 있는 가장 새 등록 버전 [{page, version, name, graph_id, page_name, material_id, page_count, file, number}].
    추출한 적 없는 쪽은 뺀다. graph_id는 지은 graph.json의 이름이고, 짓지 않았으면 규칙이 셈한 이름이다. 둘은 다를 수 있다: 사람이 다른 파일을
    고르면 옛 이름 붙박기가 풀리지만(sheets.seat) 다시 추출하기 전까지 이 쪽은 옛 이름으로 보이고 기록도 그 이름을 가리킨다."""
    out = []
    for page in range(_page_count(record)):
        for version in range(record["registration_version"], 0, -1):
            name = _out_name(record, page, version)
            try:
                with open(os.path.join(paths.output_root("extract"), name, "extraction.json"), encoding="utf-8") as fh:
                    ex = json.load(fh)
            except (OSError, ValueError):
                continue
            f = sheet_rules.facts(ex)
            out.append({"page": page, "version": version, "name": name,
                        "graph_id": _built_graph_id(name) or _graph_id_of(ex, record.get("project_id")),
                        "page_name": f["page_name"], "material_id": f["material_id"], "page_count": f["page_count"], "file": f["file"],
                        "number": f["number"]})
            break
    return out


def _key(graph_id):
    return paths.safe_name(graph_id).casefold()


CARRY, BLOCK = "carry", "block"
# 막음 자리마다 사람이 할 일(거절 글). 옮김 자리는 판 이전이 옮기므로 할 일이 없다
TODO = {"지식그래프 판단": "지식그래프 화면의 연결 후보에서 이 도면의 판단을 '판단 전'으로 되돌리고, 번호를 확정한 뒤 지식그래프를 다시 만들어 다시 판단하세요",
        "저장하지 못한 AI 답": "분석 결과 화면에서 남은 AI 답을 이어서 실행으로 결과에 합치거나 지운 뒤 다시 확정하세요",
        "옛 도면별 구간": "옛 화면의 도면별 구간 파일은 옮기지 않으니 그 구간을 정리한 뒤 다시 확정하세요",
        "옛 도면별 분석 결과": "옛 화면의 도면별 분석 결과 파일은 옮기지 않으니 그 결과를 정리한 뒤 다시 확정하세요",
        "도면 연결 지정": "도면 연결에서 이 번호로 지정한 연결을 풀고, 번호 확정·취소를 마친 뒤 다시 지정하세요",
        "구간 제외 표시": "구간 패널에서 이 도면의 구간 제외를 풀고, 번호 확정·취소를 마친 뒤 다시 표시하세요",
        "다른 도면과의 연결 구간이 든 구간": "그 구간에서 다른 도면과의 연결 구간을 빼고, 번호 확정·취소를 마친 뒤 다시 넣으세요"}
XLINK_PLACE = "다른 도면과의 연결 구간이 든 구간"


def _places(project_id):
    """그래프 ID(도면 번호)를 열쇠로 쓰는 프로젝트 기록 [(이름, 파일 목록, CARRY|BLOCK)]. 새 화면은 구간·분석 결과를 프로젝트 그래프
    (study-nodes/<프로젝트>/project-<프로젝트>.json)에 두고 구성원을 '<그래프 ID>/<엔터티 ID>'로 적으므로, 도면 파일 이름이 아니라
    파일 안의 참조를 센다. 옮김(CARRY)은 판 이전이 같은 자료의 이름 바뀜을 따라 옮기는 자리(프로젝트 구간·분석 결과, 초기사건·FMEA·잠재
    후보 판단), 막음(BLOCK)은 옮기지 않는 자리(옛 도면별 파일, 저장하지 못한 AI 답, 지식그래프 판단 CSV). 다시 만드는 자리(구간 AI 검토 제안,
    명령 복구 옆 파일 .pending, 채팅 도구의 구간 후보 캐시 candidates/)는 세지 않는다. 도면 번호로 적는 기록(도면 연결 지정의 끝, 구간 제외 표시)은 _number_refs가 센다."""
    from hazop.graph import project
    from hazop.ie import store as ie_store
    from hazop.kg import expect
    from hazop.study import nodes
    pid = paths.safe_name(project_id)
    whole = "project-%s.json" % pid

    def files(folder, ends=(".json",)):
        out = []
        for d, _dirs, names in os.walk(folder):
            out += [os.path.join(d, n) for n in sorted(names) if n.endswith(ends)]
        return out

    def split(folder, keep):
        """(프로젝트 파일, 옛 도면별 파일, unsaved 아래 파일). keep(이름)이 거짓인 파일과 candidates/ 아래(구간 후보 캐시)는 뺀다."""
        mine, old, unsaved = [], [], []
        for f in files(folder):
            name = os.path.basename(f)
            if not keep(name) or os.path.relpath(f, folder).split(os.sep)[0] == "candidates":
                continue
            if os.path.basename(os.path.dirname(f)) == "unsaved":
                unsaved.append(f)
            elif os.path.dirname(f) == folder and name == whole:
                mine.append(f)
            else:
                old.append(f)
        return mine, old, unsaved
    study, old_study, _u = split(os.path.join(nodes.store_dir(), pid), lambda n: not n.startswith("구간AI검토-"))
    results, old_results, unsaved = [], [], []
    for folder in (paths.folder("analysis-results", pid), paths.folder("analysis-results-test", pid)):
        a, b, c = split(folder, lambda n: not n.endswith(".pending.json"))
        results, old_results, unsaved = results + a, old_results + b, unsaved + c
    unsaved += files(os.path.join(os.path.dirname(paths.settings_path()), "unsaved-analysis", paths.safe_name(project_id or "project")))
    return [("구간", study, CARRY), ("옛 도면별 구간", old_study, BLOCK),
            ("분석 결과", results, CARRY), ("옛 도면별 분석 결과", old_results, BLOCK), ("저장하지 못한 AI 답", unsaved, BLOCK),
            ("초기사건", [ie_store.store_path(project_id)], CARRY),
            ("FMEA", [ie_store.fmea_path(project_id)], CARRY),
            ("잠재 후보 판단", [expect.store_path(project_id)], CARRY),
            ("도면 연결 지정", [project.manual_path(project_id)], BLOCK),
            ("지식그래프 판단", files(paths.folder("knowledge-graph", paths.safe_name(project_id, "project")), (".json", ".csv")), BLOCK)]


def _csv_refs(path, graph_id):
    """CSV 칸 가운데 그 도면을 가리키는 것의 수. 지식그래프 판단 CSV는 따옴표 없이 'graph-<번호>:<태그>'·'graph-<번호>#<파일 id>'로 적는다.
    판단 열(link_status)이 있는 파일은 사람이 판단한 행만 센다(판단 전 후보는 다시 만들 때 새 이름으로 다시 셈됨)."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        lines = [l for l in fh.read().splitlines(keepends=True) if not l.lstrip().startswith("#")]
    rows = list(csv.reader(io.StringIO("".join(lines))))
    if not rows:
        return 0
    status = rows[0].index("link_status") if "link_status" in rows[0] else None
    heads = (graph_id + ":", graph_id + "#", graph_id + "/")
    n = 0
    for row in rows[1:]:
        if status is not None and (row[status] if status < len(row) else "") in ("", "candidate"):
            continue
        n += sum(1 for cell in row if cell == graph_id or cell.startswith(heads))
    return n


def _number_refs(project_id, graph_id):
    """도면 번호로 적는 기록의 수 {이름: 수}: 도면 연결 지정의 끝(hazop.graph.project.end_ref), 구간 제외 표시(hazop.study.nodes).
    번호를 이름에 쓰지 않는 시트(임시 이름)는 이런 기록을 가질 수 없다."""
    from hazop.graph import project
    from hazop.study import nodes
    if not graph_id.startswith(sheet_rules.PREFIX) or sheet_rules.is_temp_name(graph_id):
        return {}
    want = nodes.drawing_key(graph_id[len(sheet_rules.PREFIX):])
    try:
        ops = (project.load_manual(project_id) or {}).get("ops") or []
    except (OSError, ValueError):
        ops = []
    try:
        marked = nodes.load_excluded(project_id)
    except (OSError, ValueError):
        marked = {}
    out = {"도면 연결 지정": sum(1 for op in ops if isinstance(op, dict) for e in op.get("ends") or []
                             if isinstance(e, dict) and nodes.drawing_key(e.get("drawing_number")) == want),
           "구간 제외 표시": sum(1 for k in marked if nodes.drawing_key(k) == want)}
    return {k: v for k, v in out.items() if v}


# 지난 일의 기록: 되돌리기 묶음, 이력, 판 이전 줄의 도면 목록, 문서의 판 표지와 옮긴 기록(ref_versions·ref_migrations, 잃은 참조의 옛 값이 글로 남음)
PAST_KEYS = ("batches", "history", "log", "drawings", "ref_versions", "ref_migrations")


def _links(project_id, graph_id):
    """그 도면에 끝이 닿아 이어진 도면 연결 구간 id(xlink-…). 연결 구간 id에는 도면 접두가 없고 두 끝의 '<그래프 ID>#…'를 해시한 값이라,
    그 도면의 이름이 바뀌면 다른 도면 구간에 든 연결 구간도 사라진다(R13)."""
    from hazop.app import project_ctx
    from hazop.graph import project
    try:
        links = project_ctx.project_graph(project_id).get("sheet_links") or []
    except (OSError, ValueError, KeyError):
        LOG.exception("도면 연결 구간을 읽지 못함: %s", project_id)
        return frozenset()
    return frozenset(l["link_id"] for l in links if l.get("status") == project.LINKED
                     and graph_id in ((l.get("from") or {}).get("graph_id"), (l.get("to") or {}).get("graph_id")))


def _points_at(text, graph_id, links=frozenset()):
    """그 도면을 가리키는가: '<그래프 ID>'·'<그래프 ID>/…'·'#…'·':…', 또는 그 도면에 닿는 연결 구간과 그 두 끝 관계('<연결 구간>-a'·'-b')."""
    if not isinstance(text, str):
        return False
    return text == graph_id or text.startswith((graph_id + "/", graph_id + "#", graph_id + ":"))         or text in links or text[:-2] in links and text[-2:] in ("-a", "-b")


def _live_nodes(doc, graph_id, links=frozenset()):
    """검토구간 집합에서 그 도면을 지금 가리키는 구간 수: 구성원, 또는 찾지 못한·버린 구성요소(묘비 기록의 ref·lost_from)가 그 도면인 구간.
    그 도면에 닿는 도면 연결 구간을 구성원으로 둔 다른 도면의 구간도 센다(이름이 바뀌면 그 연결 구간을 잃는다).
    되돌리기 묶음(batches)과 이력은 세지 않는다(지운 구간을 세면 '그 기록을 먼저 정리하세요'대로 해도 풀리지 않는다)."""
    tombs = doc.get("tombstones") if isinstance(doc.get("tombstones"), dict) else {}

    def tomb_hits(t):
        rec = tombs.get(t)
        return isinstance(rec, dict) and any(_points_at(v, graph_id, links) for v in rec.values())
    return sum(1 for n in doc.get("nodes") or [] if isinstance(n, dict) and (
        any(_points_at(m, graph_id, links) for m in n.get("members") or [])
        or any(tomb_hits(t) for k in ("lost", "discarded") for t in n.get(k) or [])))


def _live(x):
    """지금 값만 남긴 사본: 판 사진(graph_member_*)과 PAST_KEYS를 뺀다."""
    if isinstance(x, dict):
        return {k: _live(v) for k, v in x.items() if not k.startswith("graph_member_") and k not in PAST_KEYS}
    if isinstance(x, list):
        return [_live(v) for v in x]
    return x


NOWHERE = "\0"   # 어떤 그래프 ID와도 같지 않은 값(연결 구간만 셀 때)


STALE = "\1stale"   # _json_refs 줄 이름: 판 사진에 없어 판 이전이 묘비로 할 참조 수


def _json_refs(text, graph_id, links=frozenset(), known=None):
    """[(이름 또는 None, 수, 단위)]. 검토구간 집합은 구간 수, 다른 기록은 지금 값 안의 참조 수. 이 도면에 닿는 도면 연결 구간(links)은 이름이
    XLINK_PLACE인 줄로 따로 센다(이름 바뀜이 옮기지 못함). 이름 None은 그 파일 자리의 이름이다. known(구간 저장본 판 사진의 참조·id)을 주면
    그 안에 없는 참조 수를 STALE 줄로 더 낸다(같은 수가 None 줄에도 들어 있다)."""
    from hazop.study import nodes
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if isinstance(doc, dict) and doc.get("kind") == nodes.KIND:
        return [(None, _live_nodes(doc, graph_id), "개"), (XLINK_PLACE, _live_nodes(doc, NOWHERE, links), "개")]
    live = text if doc is None else json.dumps(_live(doc), ensure_ascii=False)
    own = re.findall(r'"(%s(?:[/#:][^"]*)?)"' % re.escape(graph_id), live)
    stale = 0 if known is None else sum(1 for v in own if v.split("|")[0] not in known)
    return [(None, len(own), "곳"), (STALE, stale, "곳"),
            (XLINK_PLACE, sum(len(re.findall(r'"%s(?="|-[ab]")' % re.escape(l), live)) for l in sorted(links)), "곳")]


def _split_refs(project_id, graph_id, stale=None):
    """그 도면을 지금 가리키는 사람 기록 ({옮김 이름: (수, 단위)}, {막음 이름: (수, 단위)})(0인 것은 뺀다). JSON 안의 "<그래프 ID>"·"<그래프 ID>/…"·
    "<그래프 ID>#…"와 그 도면에 닿는 도면 연결 구간 id(_links, 막음), CSV 칸(_csv_refs), 도면 번호로 적는 기록(_number_refs, 막음).
    지난 일의 기록(되돌리기 묶음·이력·판 사진)은 세지 않는다. stale(사전)을 주면 옮김 자리 참조 가운데 구간 저장본 판 사진에 없어 판 이전이
    묘비로 할 것의 수를 {이름: 수}로 채운다(옮김 수에도 들어 있다)."""
    carry, block = {}, {}
    if not graph_id:
        return carry, block
    links = _links(project_id, graph_id)
    known = None
    if stale is not None:
        ns = _stored_set(project_id) or {}
        refs = ns.get("graph_member_refs") or {}
        known = set(refs) | {r for r in refs.values() if r}

    def add(out, name, n, unit):
        if n:
            have = out.get(name, (0, unit))
            out[name] = (have[0] + n, have[1])
    try:
        followed = _followed_docs(project_id)
    except Exception:  # noqa: BLE001 - 따라갈 문서 목록을 못 얻으면 모두 원문으로 센다(가드가 덜 막는 쪽으로 틀리지 않게)
        LOG.warning("가드가 따라갈 문서 목록을 얻지 못해 원문으로 셈: %s", project_id, exc_info=True)
        followed = {}
    for name, files, rule in _places(project_id):
        for f in files:
            try:
                if f.endswith(".csv"):
                    add(block if rule == BLOCK else carry, name, _csv_refs(f, graph_id), "곳")
                    continue
                with open(f, encoding="utf-8") as fh:
                    text = fh.read()
                rows = _json_refs(_as_read(text, followed.get(os.path.normcase(os.path.abspath(f))), project_id), graph_id, links,
                                  known if rule == CARRY else None)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            for place, n, unit in rows:
                if place == STALE:
                    if n:
                        stale[name] = stale.get(name, 0) + n
                    continue
                add(block if place or rule == BLOCK else carry, place or name, n, unit)
    for name, n in _number_refs(project_id, graph_id).items():
        add(block, name, n, "곳")
    return carry, block


def _followed_docs(project_id):
    """{파일 경로(normcase): 종류} 판 이전을 읽을 때 메모리에서 따라가는 프로젝트 문서(초기사건·FMEA·잠재 후보 판단, hazop.study.follow)."""
    from hazop.study import follow
    return {os.path.normcase(os.path.abspath(path)): kind for kind, path, _problems in follow.documents(project_id)}


def _as_read(text, kind, project_id):
    """그 문서를 읽는 길이 보는 글: 판 이전을 따르는 문서(kind)는 원문이 아니라 따라간 값(follow.catch_up)으로 센다. 파일에 아직 옛 이름이
    남았어도 읽는 길은 이미 새 이름으로 옮겨 보이므로 그 옛 이름은 지금 참조가 아니다. 따라가지 못하면 원문 그대로 센다(더 막는 쪽)."""
    if kind is None:
        return text
    from hazop.study import follow
    try:
        doc = json.loads(text)
        return json.dumps(follow.catch_up(doc, kind, project_id)[0], ensure_ascii=False) if isinstance(doc, dict) else text
    except Exception:  # noqa: BLE001 - 따라가지 못한 문서는 원문으로 센다(가드가 덜 막는 쪽으로 틀리지 않게)
        LOG.warning("가드가 문서를 따라가지 못해 원문으로 셈: %s", kind, exc_info=True)
        return text


def _references(project_id, graph_id):
    """그 도면을 지금 가리키는 사람 기록 {이름: (수, 단위)}(옮김·막음 모두, 0인 것은 뺀다)."""
    carry, block = _split_refs(project_id, graph_id)
    out = dict(carry)
    for k, (n, unit) in block.items():
        out[k] = (out.get(k, (0, unit))[0] + n, unit)
    return out


def _stored_set(project_id):
    """프로젝트 구간 저장본(읽은 그대로) 또는 None. 짝을 증명할 판 사진을 본다."""
    from hazop.study import nodes
    path = os.path.join(nodes.store_dir(), paths.safe_name(project_id), "project-%s.json" % paths.safe_name(project_id))
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _pairs_after(project_id, material_id, old, new):
    """이 자료의 시트 이름이 old → new가 된 뒤 판 이전이 셀 짝(hazop.study.idmap.sheet_pairs). 구간 저장본이 없으면 None(옮길 길이 없음)."""
    from hazop.app import project_ctx
    from hazop.study import idmap
    ns = _stored_set(project_id)
    if ns is None:
        return None
    try:
        pg = project_ctx.project_graph(project_id)
    except (OSError, ValueError):
        return None
    now = pg.get("sheets") or []
    if "graph_member_sheets" not in ns and ns.get("graph_version") == pg.get("graph_version"):
        # 판이 같으면 확정 길(_reextract의 prepared_for_reextract)이 비키기 전에 이 칸을 지금 그래프의 자료로 채운다
        ns = dict(ns, graph_member_sheets=idmap.sheet_materials(pg))
    sheets = [{"graph_id": s["graph_id"], "material_id": s.get("material_id")} for s in now if s.get("graph_id") not in (old, new)]
    return idmap.sheet_pairs(ns, {"sheets": sheets + [{"graph_id": new, "material_id": material_id}]})


def _shown(graph_id, sheet=None):
    """안내 글에 쓸 도면 이름(임시 이름 대신 파일 이름·쪽)."""
    if sheet is not None and not sheet_rules.usable_number(sheet):   # 임시 이름, 정착이 붙박은 옛 이름(graph-drawing 등)
        return sheet_rules.label({"material_id": sheet.get("material_id"), "page_index": sheet.get("page") or 0,
                                  "page_count": sheet.get("page_count") or 1, "number": None, "file": sheet.get("file")})
    return sheet_rules.display_name({"graph_id": graph_id})


def _describe(refs):
    return "·".join("%s %d%s" % (k, n, unit) for k, (n, unit) in refs.items())


def _evidence(cand):
    if not cand:
        return None
    src = cand.get("source")
    where = {"title_block": "표제란", "dexpi_meta": "DEXPI 도면 정보"}.get(src, src or "?")
    page = cand.get("page_id")
    cell = cand.get("value_object_id")
    text = where + (" · %s" % page if page else "") + (" · 칸 %s" % cell if cell else "")
    return {"source": src, "page_id": page, "key_object_id": cand.get("key_object_id"), "value_object_id": cell, "text": text}


def _who(record, field):
    """그 항목을 지금 값으로 확정한 마지막 기록 {by, at, reason} 또는 None."""
    for h in reversed(record.get("history") or []):
        if h.get("field") == field and h.get("action") in ("confirm_metadata", "unconfirm_metadata"):
            if h.get("action") == "confirm_metadata" and h.get("after") == record.get(field):
                return {"by": h.get("by"), "at": h.get("at"), "reason": h.get("reason")}
            return None
    return None


def row(project_id, material_id, store_root=None):
    """자료 하나의 표제란 상태. 없으면 None."""
    record, path = registry.latest(project_id, material_id, _store_root(store_root))
    if record is None:
        return None
    cands = record.get("auto_candidates") or {}
    fields = []
    for field, label in FIELDS:
        cand = cands.get(field)
        who = _who(record, field) if record.get(field) is not None else None
        fields.append({"field": field, "label": label, "value": record.get(field),
                       "candidate": str(cand["value"]) if cand and cand.get("value") is not None else None,
                       "evidence": _evidence(cand), "confirmed_by": (who or {}).get("by"), "confirmed_at": (who or {}).get("at")})
    done = sum(1 for f in fields if f["value"] is not None)
    sheets = _sheets(record) if record.get("status") == "registered" else []
    return {"material_id": material_id, "project_id": project_id, "version": record.get("registration_version"),
            "name": record.get("original_name"), "format": record.get("format"), "material_type": record.get("material_type"),
            "status": record.get("status"), "pages": _page_count(record),
            "state": "confirmed" if done == len(FIELDS) else ("partial" if done else "unconfirmed"),
            "fields": fields, "ver": store_io.fingerprint(path), "sheets": sheets,
            "needs_reextract": any(s["version"] != record.get("registration_version") for s in sheets),
            "review_data": [_describe(r) for r in [_merged_refs(project_id, sheets)] if r],
            "multi_page": _page_count(record) > 1}


def _merged_refs(project_id, sheets):
    out = {}
    for gid in sorted({s["graph_id"] for s in sheets if s.get("graph_id")}):
        for k, (n, unit) in _references(project_id, gid).items():
            out[k] = (out.get(k, (0, unit))[0] + n, unit)
    return out


def view(project_id, store_root=None, material_type="P&ID"):
    """프로젝트의 도면 자료마다 row(...)."""
    out = []
    for mid in _materials(project_id, store_root):
        r = row(project_id, mid, store_root)
        if r is not None and (material_type is None or (r["material_type"] or "P&ID") == material_type):
            out.append(r)
    return out


# ---------------------------------------------------------------- 확정·취소

def _check_values(fields):
    if not isinstance(fields, dict) or not fields:
        raise Refused("fields", "bad_args", "확정할 항목이 없음")
    out = {}
    for k, v in fields.items():
        if k not in LABELS:
            raise Refused("fields", "bad_args", "알 수 없는 항목: %s" % k)
        if not isinstance(v, str):
            raise Refused(k, "bad_args", "%s 값은 글이어야 함" % LABELS[k])
        if any(unicodedata.category(ch) in ("Cc", "Cf") and ch not in "\t\n\r" for ch in v):
            raise Refused(k, "bad_args", "%s 값에 보이지 않는 제어 문자가 있음" % LABELS[k])
        text = " ".join(v.split())
        if not text or len(text) > MAX_VALUE:
            raise Refused(k, "bad_args", "%s 값은 비어 있지 않은 %d자 이하 글이어야 함" % (LABELS[k], MAX_VALUE))
        out[k] = text
    return out


def _gid(number, sheet, project_id):
    """번호가 number가 되면 그 쪽이 얻을 그래프 ID(그래프를 지을 때와 같은 규칙)."""
    from hazop.graph import sources
    return sources.name_for(project_id, {"material_id": sheet.get("material_id"), "page_index": sheet.get("page") or 0,
                                         "page_count": sheet.get("page_count") or 1, "number": number,
                                         "page_name": sheet.get("page_name"), "file": sheet.get("file")})


def _others(project_id, material_id, store_root):
    """다른 자료가 쓰는 그래프 ID [(그래프 ID, 형식, 자료 이름, 자료 ID)]: 추출한 쪽의 그래프 ID, 추출 전이면 확정 번호."""
    out = []
    for mid in _materials(project_id, store_root):
        if mid == material_id:
            continue
        other, _p = registry.latest(project_id, mid, _store_root(store_root))
        if not other or other.get("status") != "registered" or (other.get("material_type") or "P&ID") != "P&ID":
            continue
        gids = [s["graph_id"] for s in _sheets(other)]
        if not gids and other.get("drawing_number"):
            gids = ["graph-%s" % other["drawing_number"]]
        out += [(g, other.get("format"), other.get("original_name"), mid) for g in gids]
    return out


def _owner_of(project_id, graph_id):
    """그 이름을 지금 프로젝트 그래프가 쓰는 (자료 ID, 쪽) 또는 None(아무도 쓰지 않음). 등록 밖 폴더는 ("", 0)."""
    from hazop.app import project_ctx
    folder = project_ctx.graph_names(project_id).get(graph_id)
    if not folder:
        return None
    seat = sheet_rules.from_out_name(folder)
    return (seat[0], seat[2]) if seat else ("", 0)


def _owns(project_id, graph_id, sheet):
    """이 쪽(sheet)이 그 이름의 지금 주인인가(아무도 쓰지 않으면 주인으로 본다). 주인이 아닌 쪽(같은 번호의 다른 형식·파일, 정착 전에
    가려진 도면)의 이름이 바뀌어도 그 이름을 가리키는 기록은 주인 도면에 그대로 붙는다."""
    owner = _owner_of(project_id, graph_id)
    return owner is None or owner == (sheet.get("material_id"), sheet.get("page") or 0)


def _records_refusal(what, gid, sheet, refs, why=None):
    """막는 거절 줄. refs는 막는 자리 {이름: (수, 단위)}, why는 옮김 자리를 옮기지 못하는 까닭(있으면). 글에는 막는 자리와 할 일을 적는다."""
    shown, where = _shown(gid, sheet), _describe(refs)
    todo = [TODO[k] for k in refs if k in TODO]
    tail = (" " + why if why else "") + (" " + ". ".join(todo) + "." if todo else "") or " 그 기록을 먼저 정리하세요."
    if sheet is not None and not sheet_rules.usable_number(sheet):
        return Refused("drawing_number", "rule", "번호가 확정되지 않은 이 도면(%s)을 가리키는 기록 가운데 번호를 확정할 때 옮기지 못하는 것이 있어(%s) "
                       "지금 확정하면 그 기록이 끊깁니다.%s" % (shown, where, tail), sheet_rules.CONFIRM_FIRST)
    return Refused("drawing_number", "rule", "%s(%s)을 가리키는 기록 가운데 도면 번호를 바꿀 때 옮기지 못하는 것이 있어(%s) 바꾸면 그 기록이 끊기거나 "
                   "다른 도면과 섞입니다.%s" % (what, shown, where, tail), HAS_RECORDS)


NO_PROOF = "구간 저장본이 지금 판에 맞춰지지 않아 같은 파일임을 증명하지 못합니다. 구간 패널에서 '도면 변경 반영하기'를 누른 뒤 다시 확정하세요."
NO_SET = "검토구간 저장본이 없어 이 기록을 새 이름으로 옮길 길이 없습니다. 그 기록을 정리하거나 검토구간을 먼저 저장한 뒤 다시 확정하세요."
NOT_OWNER = ("도면 번호 %s는 이미 다른 파일(%s)이 써서, 확정해도 이 파일은 그 번호의 고르기 후보로만 오르고 도면 목록에 쓰이지 않으므로 "
             "기록을 옮길 곳이 없습니다. 다른 번호를 쓰거나, 그 파일의 번호를 먼저 바꾸거나, 그 기록을 정리한 뒤 다시 확정하세요.")
NOT_OWNER_UNCONFIRM = ("번호를 취소하면 이 도면이 돌아갈 이름(%s)을 이미 다른 파일(%s)이 써서, 취소해도 이 파일은 그 이름의 고르기 후보로만 오르고 "
                       "도면 목록에 쓰이지 않으므로 기록을 옮길 곳이 없습니다. 번호를 그대로 두거나, 그 파일의 번호를 먼저 바꾸거나, 그 기록을 정리한 뒤 "
                       "다시 취소하세요.")


SHARED_NUMBER = ("도면 번호 %s는 이미 다른 파일(%s)이 씁니다. 번호를 확정하면 도면 목록에서 어느 파일을 쓸지 고를 수 있고, 고르기 전에는 "
                 "지금 쓰는 파일을 그대로 씁니다.")


def _guard_number(project_id, record, sheets, new_number, store_root, names=True):
    """도면 번호가 new_number(None이면 확정 취소)가 될 때 끊기거나 겹치는 것을 막는다(가드 건전: 허락한 바꾸기는 사람 기록을 끊지 않음).
    - 지금 이름의 참조는 이 쪽이 그 이름의 주인일 때만 센다(_owns). 참조는 지금 값만 센다(_split_refs).
    - 옮김 자리의 참조는 확정 뒤 이 쪽이 새 이름의 주인이고(owner_if) 구간 저장본의 판 사진이 짝(옛 → 새)을 증명할 때 판 이전이 옮긴다.
      막음 자리의 참조가 하나라도 있으면 막는다.
    - 새 이름을 다른 파일이 쓰고 있으면 그 파일을 주인으로 붙박을 것으로 셈하고(sources.owner_if keep), 그래도 이 쪽이 주인이 될 때만 새 이름의
      참조를 센다. 아무도 쓰지 않는 새 이름의 참조(지운 도면의 기록)는 늘 센다. 다만 그 이름이 같은 판 이전에서 다른 자료의 짝으로 옮겨 가면
      (아직 옮기지 않은 맞바꿈) 옮김 자리의 참조는 그 자료를 따라가므로 세지 않는다.
    names가 False면(정착 전 프로젝트의 dry) 이름으로 셈하는 검사를 건너뛴다(옛 이름으로 셈하면 정착 뒤에는 없을 거절이 나온다).
    다시 추출이 실패한 뒤 같은 확정을 다시 하는 길(등록정보 번호는 이미 new_number, 시트는 옛 이름)도 시트의 지금 이름 → 새 이름을 같은 규칙으로 본다.
    -> (붙박을 새 이름 목록, 알림 글 목록, 옮길 기록 {자리: 수}, 이름 바뀜 [{from, to, from_label, to_label}],
        판 사진에 없어 판 이전이 묘비로 할 옮김 자리 참조 {자리: 수})."""
    from hazop.graph import sources
    retry = record.get("drawing_number") == new_number
    if retry and all(s.get("graph_id") == _gid(new_number, s, project_id) for s in sheets):
        return [], [], {}, [], {}
    problem = sheet_rules.number_problem(new_number, _page_count(record))
    if problem:
        raise Refused("drawing_number", "rule", problem["text"], problem["code"])
    old_number = record.get("drawing_number")
    if not retry and old_number is not None and old_number in sources.load_choices(project_id):
        raise Refused("drawing_number", "rule", "도면 번호 %s에는 사람이 고른 원본 형식 선택이 걸려 있어 번호를 바꾸지 않습니다. "
                      "그 선택은 새 번호로 옮겨지지 않습니다." % old_number, CHOICE_PINNED)
    if not names:
        return [], [], {}, [], {}
    targets = [(s.get("graph_id"), _gid(new_number, s, project_id), s) for s in sheets]
    if not sheets and new_number is not None:
        targets = [(None, "graph-%s" % new_number, None)]
    keep, notes, carries, renames, lost = [], [], {}, [], {}
    for old, new, sheet in targets:
        if old is not None and old != new:
            mine = (sheet.get("material_id"), sheet.get("page") or 0)
            owner = _owner_of(project_id, new)
            shown_number = new[len(sheet_rules.PREFIX):] if new_number and new == sheet_rules.PREFIX + new_number else None
            takes = owner is None or owner == mine or \
                sources.owner_if(project_id, mine[0], mine[1], new, shown_number, keep=True) == mine[0]
            pairs = _pairs_after(project_id, mine[0], old, new) if takes else None
            renames.append({"from": old, "to": new, "from_label": _shown(old, sheet), "to_label": shown_number or _shown(new)})
            if _owns(project_id, old, sheet):
                stale = {}
                carry, block = _split_refs(project_id, old, stale)
                not_owner = (NOT_OWNER if new_number else NOT_OWNER_UNCONFIRM) % (shown_number or _shown(new), _owner_file(project_id, new))
                proof = None if not carry else not_owner if not takes \
                    else NO_SET if pairs is None else NO_PROOF if pairs.get(old) != new else None
                refs = dict(block, **(carry if proof else {}))
                if refs:
                    where = "연결 구간이 든 구간: %s." % ", ".join(_xlink_nodes(project_id, _links(project_id, old))) if XLINK_PLACE in block else None
                    raise _records_refusal("이 도면", old, sheet, refs, " ".join(x for x in (proof, where) if x) or None)
                for k, (n, _unit) in carry.items():
                    if n - stale.get(k, 0):
                        carries[k] = carries.get(k, 0) + n - stale.get(k, 0)
                for k, n in stale.items():
                    lost[k] = lost.get(k, 0) + n
            if owner is not None and owner != mine:
                if takes:
                    refs = _references(project_id, new)
                    if refs:
                        raise Refused("drawing_number", "rule", "도면 번호 %s는 이미 다른 파일이 쓰고 그 도면을 가리키는 기록이 있습니다(%s). 사람이 고른 "
                                      "원본 형식 때문에 이 파일이 그 번호를 차지하게 되어 그 기록이 다른 도면으로 옮겨 갑니다. 도면 목록에서 원본 "
                                      "고르기를 먼저 바꾸세요." % (shown_number or _shown(new), _describe(refs)), NUMBER_TAKEN)
                keep.append(new)
                notes.append(SHARED_NUMBER % (shown_number or _shown(new), _owner_file(project_id, new)))
            else:
                carry, block = _split_refs(project_id, new)
                refs = dict(block, **({} if new in (pairs or {}) else carry))
                if refs:
                    raise _records_refusal("새 번호의 도면", new, None, refs)
        elif old is None and _owner_of(project_id, new) is not None:   # 아직 추출하지 않은 자료: 추출하면 그 이름을 함께 원한다
            keep.append(new)
            notes.append(SHARED_NUMBER % (new_number, _owner_file(project_id, new)))
        for gid, _fmt, name, _mid in _others(project_id, record["material_id"], store_root):
            if _key(gid) == _key(new) and gid != new:
                raise Refused("drawing_number", "conflict", "다른 자료 %s의 도면 번호(%s)와 글자만 달라 같은 파일을 쓰게 됩니다. 같은 도면이면 "
                              "그 번호를 그대로 쓰고, 다른 도면이면 다른 번호를 쓰세요." % (name, gid[len("graph-"):]), NUMBER_TAKEN)
    return keep, notes, carries, renames, lost


def _xlink_nodes(project_id, links):
    """그 연결 구간을 구성원으로 둔 구간의 이름 목록(거절 글에 어느 구간인지 밝힌다)."""
    ns = _stored_set(project_id) or {}
    return [str(n.get("name") or n.get("node_id")) for n in ns.get("nodes") or [] if isinstance(n, dict)
            and any(_points_at(m, NOWHERE, links) for m in n.get("members") or [])] or ["?"]


def _owner_file(project_id, graph_id):
    """그 이름을 지금 쓰는 파일의 원본 이름(모르면 '다른 파일')."""
    owner = _owner_of(project_id, graph_id)
    record = registry.latest(project_id, owner[0])[0] if owner and owner[0] else None
    return (record or {}).get("original_name") or "다른 파일"


def _union(first, second, key):
    """first 목록에 second에서 key가 겹치지 않는 항목을 더한 것(first가 이긴다)."""
    seen = {x.get(key) for x in first if isinstance(x, dict)}
    return list(first) + [x for x in second if isinstance(x, dict) and x.get(key) not in seen]


def _merge(kind, src, dst):
    """옮겨 쓸 기록(src, 지금 쪽 = 사람이 마지막으로 고친 곳)과 새 이름에 이미 있는 기록(dst)을 연산·후보 단위로 합친다. 지금 쪽이 이긴다."""
    out = dict(src)
    if kind == "edits":
        removed = {i for e in src.get("log") or [] if isinstance(e, dict) for i in e.get("removed") or []}
        extra = [o for o in dst.get("ops") or [] if isinstance(o, dict) and o.get("op_id") not in removed]
        out["ops"] = _union(src.get("ops") or [], extra, "op_id")   # 지금 쪽에서 지운 연산은 되살리지 않는다
        out["log"] = list(dst.get("log") or []) + [e for e in src.get("log") or [] if e not in (dst.get("log") or [])]
    else:
        out["candidates"] = _union(src.get("candidates") or [], dst.get("candidates") or [], "cand_id")
        out["runs"] = list(dst.get("runs") or []) + [r for r in src.get("runs") or [] if r not in (dst.get("runs") or [])]
    return out


def _carry(sheets, new_record):
    """지금 쪽 이름의 사람 수정 기록·AI 후보 기록을 새 등록 버전 이름으로 옮겨 쓴다(앞 파일은 지우지 않음). 새 이름에 이미 기록이 있으면
    (앞서 다시 추출이 실패한 시도가 옮겨 둔 것 등) 덮지 않고 연산·후보 단위로 합친다(지금 쪽이 이긴다).
    반환 ([{from, to, edits, ai_review}], 이번에 새로 만든 파일 경로 목록)."""
    from hazop.extract import ai_review, corrections
    out, created = [], []
    for s in sheets:
        new_name = _out_name(new_record, s["page"])
        if new_name == s["name"]:
            continue
        moved = {"from": s["name"], "to": new_name, "edits": False, "ai_review": False}
        for key, path_of in (("edits", corrections.store_path), ("ai_review", ai_review.store_path)):
            data, _fp = store_io.read_bytes(path_of(s["name"]))
            if data is None:
                continue
            doc = json.loads(data.decode("utf-8"))
            if not isinstance(doc, dict):
                continue
            target = path_of(new_name)
            have, have_fp = store_io.read_bytes(target)
            if have is not None:
                old = json.loads(have.decode("utf-8"))
                doc = _merge(key, doc, old if isinstance(old, dict) else {})
            doc["extraction_name"] = new_name
            doc["carried_from"] = list(dict.fromkeys(list(doc.get("carried_from") or []) + [s["name"]]))
            store_io.write_json(target, doc, expect=have_fp, sort_keys=False)
            if have is None:
                created.append(target)
            moved[key] = True
        out.append(moved)
    return out, created


def _set_aside(sheets, new_record):
    """새 이름이 될 쪽의 앞 graph.json을 graph.superseded.json으로 비켜 둔다. 반환 [(앞 경로, 비켜 둔 경로)]."""
    moved = []
    for s in sheets:
        if _out_name(new_record, s["page"]) == s["name"]:
            continue
        folder = os.path.join(paths.output_root("graph"), s["name"])
        src, dst = os.path.join(folder, "graph.json"), os.path.join(folder, SUPERSEDED)
        if os.path.isfile(src):
            os.replace(src, dst)
            moved.append((src, dst))
    return moved


def _put_back(moved):
    for src, dst in moved:
        if os.path.isfile(dst) and not os.path.exists(src):
            os.replace(dst, src)


def _confirmed_sheets(sheets):
    from hazop.extract import confirmation
    out = []
    for s in sheets:
        try:
            if confirmation.sheet_confirmation(s["name"])["state"] == "confirmed":
                out.append(s["name"])
        except (OSError, ValueError):
            pass
    return out


def _reextract(record, registration_path, sheets, extract, progress):
    """sheets를 record(새 등록 버전)로 옮겨 다시 추출한다: 기록 옮겨 쓰기 → 앞 그래프 비켜 두기 → 추출. 실패하면 그래프를 되돌린다."""
    from hazop.app import data
    with data.prepared_for_reextract(record.get("project_id")):   # 비켜 두기 전에 검토구간 표지를 채운다(이미 채웠으면 그대로)
        return _reextract_prepared(record, registration_path, sheets, extract, progress)


def _reextract_prepared(record, registration_path, sheets, extract, progress):
    carried, created = _carry(sheets, record)
    moved = _set_aside(sheets, record)
    progress("도면 다시 읽는 중", 2, 2)
    try:
        extract(registration_path)
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 앞 그래프와 옮겨 쓴 기록을 되돌리고 사유를 알린다
        _put_back(moved)
        for path in created:  # 이번 시도가 새로 만든 사본만 지운다: 지금 쪽(앞 이름)의 기록 하나만 진실로 남게
            try:
                os.remove(path)
            except OSError:
                pass
        raise Refused("extraction", "io", "확정은 저장했으나 도면을 다시 읽지 못함(%s). 같은 확정을 다시 하면 다시 읽음"
                      % (" ".join(str(exc).split())[:160] or type(exc).__name__))
    return carried


SETTLE_FIRST_NOTE = "도면 목록을 새 이름 규칙으로 아직 정리하지 않은 프로젝트라, 확정할 때 먼저 정리한 뒤 다시 검사합니다."


def _settle(project_id):
    """번호를 바꾸기 전에 시트 자리를 정착한다(hazop.app.data.settle_sheets, 멱등). 사람이 확정을 승인한 뒤(dry가 아닌 차례)에만 부른다.
    다시 추출이 맨 앞에서 정착하므로, 가드가 옛 규칙(graph-drawing 등)으로 이름을 예측하면 정착 뒤 실제 이름과 달라진다."""
    from hazop.app import data
    try:
        data.settle_sheets(project_id)
    except Exception:  # noqa: BLE001 - 정착이 안 되면 번호를 바꾸지 않는다(이름을 맞게 예측할 수 없음). 사유는 기록에만 남긴다
        LOG.exception("표제란 확정 전 시트 정착 실패: %s", project_id)
        raise Refused("extraction", "io", "도면 목록을 새 이름 규칙으로 정리하지 못해 번호를 바꾸지 않았습니다. 잠시 뒤 다시 시도하세요.")


def _apply(project_id, material_id, by, ver, store_root, change, extract, progress, dry=False):
    """change(record) -> (새 버전을 만드는 함수 또는 None, 새 도면 번호). 공통: 판 대조, 정착, 번호 검사, 새 버전, 옮겨 쓰기, 다시 추출.
    dry면 검사까지만 하고 아무것도 쓰지 않는다(화면·채팅이 사람 승인 전에 거절 사유를 바로 보이려고). 정착 전 프로젝트에서 번호를 바꾸면
    dry는 이름으로 셈하는 검사를 건너뛰고 알림(SETTLE_FIRST_NOTE)을 달며, 실제 확정이 먼저 정착한 뒤 모든 검사를 한다.
    다른 파일이 쓰는 번호를 받으면 그 파일을 주인으로 붙박은 뒤(sources.keep_owner) 새 판을 만든다."""
    by = (by or "").strip()
    if not by:
        raise Refused("by", "bad_actor", "확정한 사람 이름이 있어야 함(설정의 검토자 이름)")
    record, path = registry.latest(project_id, material_id, _store_root(store_root))
    if record is None:
        raise Refused("material_id", "not_found", "등록된 자료가 아님: %s" % material_id)
    if ver is not None and ver != store_io.fingerprint(path):
        raise Refused("ver", "stale", "본 뒤 등록정보가 바뀜(다시 보고 확정할 것)")
    if record.get("status") != "registered":
        raise Refused("material_id", "rule", "등록이 끝나지 않은 자료라 확정할 수 없음")
    from hazop.graph import sources
    make, new_number = change(record)
    renaming = make is not None and new_number != record.get("drawing_number")
    unsettled = renaming and not sources.load_seats(project_id)[1]
    if unsettled and not dry:
        _settle(project_id)
    sheets = _sheets(record)
    behind = [s for s in sheets if s["version"] != record["registration_version"]]
    if make is None and not behind:
        return {"ok": True, "changed": False, "row": row(project_id, material_id, store_root), "refused": []}
    keep, notes, carries, renames, lost = _guard_number(project_id, record, sheets if make is not None else behind, new_number, store_root,
                                                        names=not (dry and unsettled and sheets))
    if dry:
        notes += [SETTLE_FIRST_NOTE] if unsettled and sheets else []
        return {"ok": True, "changed": True, "dry": True, "re_extract": bool(sheets), "notes": notes, "carries": carries,
                "carries_lost": lost, "renames": renames, "refused": []}
    for gid in keep:
        try:
            sources.keep_owner(project_id, gid, by)
        except (OSError, ValueError, store_io.Conflict):
            raise Refused("drawing_number", "io", "같은 번호를 쓰는 파일의 자리를 적지 못해 번호를 바꾸지 않았습니다. 잠시 뒤 다시 시도하세요.")
    released = _confirmed_sheets(sheets)
    if make is None:  # 앞서 다시 추출이 실패한 자료: 새 버전 없이 다시 읽기만
        carried = _reextract(record, path, behind, extract, progress)
        return {"ok": True, "changed": True, "version": record["registration_version"], "re_extracted": True,
                "carried": carried, "released_sheet_confirmations": released, "conflicts": [], "notes": notes + ["다시 읽기만 함"],
                "carries": carries, "carries_lost": lost, "renames": renames, "row": row(project_id, material_id, store_root), "refused": []}
    progress("표제란 확정 저장", 1, 2)
    try:
        res = make()
    except (OSError, ValueError) as exc:
        raise Refused("registration", "io", "등록정보를 쓰지 못함(%s)" % exc)
    rec = res["record"]
    if res["outcome"] != "new_version" or rec.get("status") != "registered":
        cause = "; ".join(str(b.get("reason")) for b in (rec.get("validation") or {}).get("blockers") or []) \
            or "; ".join(res.get("notes") or []) or res["outcome"]
        raise Refused("registration", "io", "새 등록 버전을 만들지 못함: %s" % cause)
    carried = _reextract(rec, res["registration_file"], sheets, extract, progress) if sheets else []
    return {"ok": True, "changed": True, "version": rec["registration_version"], "re_extracted": bool(sheets),
            "carried": carried, "released_sheet_confirmations": released, "conflicts": res.get("conflicts") or [],
            "notes": notes + (res.get("notes") or []), "carries": carries, "carries_lost": lost, "renames": renames,
            "row": row(project_id, material_id, store_root), "refused": []}


def _default_extract(registration_path):
    from hazop.app import data
    return data.extract_and_graph(registration_path)


def _quiet(*_a):
    return None


def confirm(project_id, material_id, fields, by, ver=None, reason=None, store_root=None, extract=None, progress=None, now=None,
            dry=False):
    """fields {항목: 값}을 사람 확정값으로 저장한다(후보 그대로든 고친 값이든 사람이 고른 값). ver(본 등록정보의 판, row의 ver)가
    None이 아니면 지금 판과 같아야 한다. 반환 {ok, changed, version, re_extracted, carried, released_sheet_confirmations, conflicts,
    notes, row, refused}. 막히면 ok False와 refused [{target, code, reason}]. 바뀐 값이 없으면 changed False(새 버전을 만들지 않음).
    앞서 다시 추출이 실패한 자료면 값이 같아도 다시 읽는다. dry면 검사만 한다({ok, changed, dry, re_extract})."""
    try:
        values = _check_values(fields)

        def change(record):
            diff = {k: v for k, v in values.items() if record.get(k) != v}
            if not diff:
                return None, record.get("drawing_number")
            meta = dict(diff, by=by.strip(), reason=(reason or "").strip() or "표제란 확정")
            src = registry.Store(_store_root(store_root), project_id).abs_ref(record["storage_ref"])
            return (lambda: registry.register(src, project_id, record.get("material_type") or "P&ID", _store_root(store_root),
                                              meta, by.strip(), now, number_checked=True)), \
                diff.get("drawing_number", record.get("drawing_number"))
        return _apply(project_id, material_id, by, ver, store_root, change, extract or _default_extract, progress or _quiet, dry)
    except Refused as exc:
        return {"ok": False, "changed": False, "refused": [exc.row]}


def unconfirm(project_id, material_id, field_names, by, ver=None, reason=None, store_root=None, extract=None, progress=None,
              now=None, dry=False):
    """확정을 취소해 그 항목을 다시 후보만 있는 상태로 둔다. field_names가 None이면 세 항목 모두, 빈 목록은 거절.
    돌려주는 꼴은 confirm과 같다."""
    try:
        if field_names is not None and not field_names:
            raise Refused("fields", "bad_args", "취소할 항목이 없음")
        names = list(field_names) if field_names is not None else [f for f, _ in FIELDS]
        bad = [f for f in names if f not in LABELS]
        if bad:
            raise Refused("fields", "bad_args", "알 수 없는 항목: %s" % ", ".join(map(str, bad)))

        def change(record):
            if all(record.get(f) is None for f in names):
                return None, record.get("drawing_number")
            return (lambda: registry.clear_metadata(project_id, material_id, names, (by or "").strip(), reason,
                                                    _store_root(store_root), now)), \
                (None if "drawing_number" in names else record.get("drawing_number"))
        return _apply(project_id, material_id, by, ver, store_root, change, extract or _default_extract, progress or _quiet, dry)
    except Refused as exc:
        return {"ok": False, "changed": False, "refused": [exc.row]}


def execute(project_id, command, args=None, by=None, ver=None, store_root=None, extract=None, progress=None):
    """채팅이 부를 실행 함수. view(args.material_id 선택) · confirm(args.material_id, args.fields, args.reason) ·
    unconfirm(args.material_id, args.fields 목록 선택, args.reason). 쓰는 명령은 사람 확인을 거친 뒤에만 부르고, ver(view가 준 판)가
    없으면 거절한다(채팅 규격의 확인 상자)."""
    a = dict(args or {})
    if command not in COMMANDS:
        return {"ok": False, "changed": False, "refused": [{"target": "command", "code": "unknown_command",
                                                           "reason": "모르는 명령(%s 가운데 하나)" % ", ".join(COMMANDS)}]}
    if command == "view":
        if a.get("material_id"):
            r = row(project_id, a["material_id"], store_root)
            if r is None:
                return {"ok": False, "changed": False, "refused": [{"target": "material_id", "code": "not_found",
                                                                   "reason": "등록된 자료가 아님"}]}
            return {"ok": True, "changed": False, "rows": [r], "refused": []}
        return {"ok": True, "changed": False, "rows": view(project_id, store_root), "refused": []}
    if not isinstance(ver, str) or not ver:   # 채팅은 본 판(row의 ver)을 꼭 넘긴다: 그 사이 다른 창이 바꾼 것을 덮지 않게
        return {"ok": False, "changed": False, "refused": [{"target": "ver", "code": "bad_args",
                                                           "reason": "본 등록정보의 판(ver)이 있어야 함(view의 ver)"}]}
    if command == "confirm":
        return confirm(project_id, a.get("material_id"), a.get("fields"), by, ver, a.get("reason"), store_root, extract, progress)
    return unconfirm(project_id, a.get("material_id"), a.get("fields"), by, ver, a.get("reason"), store_root, extract, progress)
