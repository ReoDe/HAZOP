"""채팅 읽기 도구가 보는 자료 묶음(`ChatContext`)과 읽기 함수. Qt를 import하지 않는다.

규격: docs/specs/chat-panel.md §3.1. 도구(`hazop.chat.tools`)는 이 묶음을 바꾸지 않는다.
- pg: 프로젝트 그래프(`hazop.graph.project`), kg: 프로젝트 지식그래프(없으면 None)
- node_sets: 검토구간 집합 목록(`hazop.study.nodes` 문서), results: 분석 결과(뒤 단위 C3)
- unknowns / unresolved: 도면별 추출 그래프의 `validation.unknowns` / `unresolved`를 프로젝트 그래프 ID로 옮긴 것
무거운 색인(태그 → ID, 질의기, 미확인 ID 집합)은 `graph_version`을 열쇠로 한 번만 만든다(`ctx.index`).
"""

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from hazop import paths
from hazop.graph import project
from hazop.graph.query import GraphQuery

DOC_DIR = "document-knowledge"
DOC_FILE = "document_knowledge.json"
DOC_PART_CHARS = 4000  # get_document가 한 번에 내는 본문 길이
RESULTS_KINDS = ("hazop_study_results",)

# 추출 단계 미확인 항목(`validation.unknowns[].check`) -> 도구가 알리는 사유. 여기 없는 check(포트 미지정, 등록 알림 등)는
# 경로 해석을 흔들지 않으므로 알리지 않는다. 구간 방향(unknown_flow_direction)은 구간 노드의 flow_direction으로 따로 본다.
UNKNOWN_CHECK_REASON = {
    "ambiguous_symbol": "unknown_symbol", "missing_kind": "unknown_symbol", "unclassified_element": "unknown_symbol",
    "unclassified_kind": "unknown_symbol", "position_kind_mismatch": "unknown_symbol",
    "missing_tag": "unknown_tag", "duplicate_tag": "unknown_tag",
    "unconnected_endpoint": "unresolved_connector", "endpoint_not_node": "unresolved_connector",
}


def lift_unknowns(graphs):
    """도면 그래프 목록 -> (미확인 항목, 끊긴 연결). 대상 ID는 프로젝트 그래프 ID(`<graph_id>/<entity_id>`)로 옮긴다."""
    unknowns, unresolved = [], []
    for g in graphs:
        gid = g["graph_id"]
        for u in (g.get("validation") or {}).get("unknowns") or []:
            unknowns.append({"sheet": gid, "check": u.get("check"), "field": u.get("field"), "reason": u.get("reason"),
                             "target": project.nid(gid, u["target"]) if u.get("target") else None})
        for r in g.get("unresolved") or []:
            ends = [project.nid(gid, ep["node_entity_id"]) for ep in r.get("endpoints") or [] if ep.get("node_entity_id")]
            unresolved.append({"sheet": gid, "local_id": r.get("local_id"), "line_no": r.get("line_no"),
                               "nodes": ends, "reason": r.get("reason")})
    return unknowns, unresolved


@dataclass
class ChatContext:
    project_id: str
    pg: dict
    kg: dict = None
    node_sets: list = field(default_factory=list)
    results: object = None
    unknowns: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    fingerprint: tuple = None
    docs: dict = field(default_factory=dict)    # chunk_id -> (등록 ID, 버전, 쪽). 문서 도구(C3)가 채운다
    roots: list = field(default_factory=list)   # 서버가 파일을 열어도 되는 폴더(C3). 이 묶음의 도구는 파일을 열지 않는다
    cursors: dict = field(default_factory=dict, repr=False, compare=False)  # 서버가 낸 cursor 표(질문 하나 동안, 200개까지)
    _call: tuple = field(default=None, repr=False, compare=False)
    _index: object = field(default=None, repr=False, compare=False)

    def has_cell(self, result_id):
        """결과 칸 ID(`<node_id>/<deviation_id>/<entry_id>`)가 분석 결과에 있는가. 항목 없이 `<node_id>/<deviation_id>`만 줘도
        그 칸이 있으면 True. 보관 칸도 센다. 답 카드 검사가 근거 ID를 확인하는 데 쓴다."""
        if not isinstance(result_id, str) or not self.results:
            return False
        parts = result_id.split("/")
        if len(parts) not in (2, 3) or not all(parts):
            return False
        key = id(self.results)
        if getattr(self, "_cell_key", None) != key:
            cells = set()
            for doc in self.results.values():
                for name in ("cells", "archived_cells"):
                    for c in (doc or {}).get(name) or []:
                        if isinstance(c, dict):
                            cells.add((str(c.get("node_id")), str(c.get("deviation_id"))))
                            cells.update((str(c.get("node_id")), str(c.get("deviation_id")), str(e.get("entry_id")))
                                         for e in c.get("entries") or [] if isinstance(e, dict))
            self._cell_set, self._cell_key = cells, key
        return tuple(parts) in self._cell_set

    @property
    def index(self):
        if self._index is None or self._index.graph_version != self.pg["graph_version"]:
            self._index = Index(self)
        return self._index


class Index:
    """한 번 만들어 두고 쓰는 조회용 색인."""

    def __init__(self, ctx):
        pg = ctx.pg
        self.graph_version = pg["graph_version"]
        self.q = GraphQuery(pg)
        self.nodes = self.q.nodes
        self.by_tag, self.by_entity = {}, {}
        for n in pg["nodes"]:
            if n.get("tag"):
                self.by_tag.setdefault(str(n["tag"]).lower(), []).append(n["entity_id"])
            if n.get("sheet_entity_id"):
                self.by_entity.setdefault(n["sheet_entity_id"], []).append(n["entity_id"])
        self.drawing_number = {s["graph_id"]: s.get("drawing_number") for s in pg["sheets"]}
        self.check = self._check_valves()
        self.uncertain = self._uncertain(ctx)
        self.node_of = {}  # 구성요소 ID -> 속한 검토구간 node_id 목록
        for ns in ctx.node_sets or []:
            for nd in (ns or {}).get("nodes") or []:
                for m in nd.get("members") or []:
                    self.node_of.setdefault(m, []).append(nd.get("node_id"))
        self._summary = None
        self._allowed = {}
        self._reverse = None
        self._kg_view = None

    def _uncertain(self, ctx):
        """노드 ID -> {사유}. 경로에 낀 곳을 앱이 다시 찾을 때 쓴다(규격 §3.1 `uncertain.reason`)."""
        out = {}

        def add(nid_, reason):
            out.setdefault(nid_, set()).add(reason)

        for n in ctx.pg["nodes"]:
            eid = n["entity_id"]
            if n["node_type"] == "pipe_segment":
                if not n.get("flow_direction"):
                    add(eid, "direction_unknown")
            elif n.get("classification") not in (None, "classified") or n.get("kind") in (None, "unclassified"):
                add(eid, "unknown_symbol")
            if n.get("kind") == "check_valve" and not self.check.get(eid):
                add(eid, "direction_unknown")
            if n.get("kind") == "continuation":
                link = n.get("sheet_link") or {}
                if link.get("status") != project.LINKED:
                    add(eid, "unlinked_sheet")
        ids = {n["entity_id"] for n in ctx.pg["nodes"]}
        for u in ctx.unknowns or []:
            if u.get("target") in ids and u.get("check") in UNKNOWN_CHECK_REASON:
                add(u["target"], UNKNOWN_CHECK_REASON[u["check"]])
        for r in ctx.unresolved or []:
            for eid in r.get("nodes") or []:
                add(eid, "unresolved_connector")
        return out

    def _check_valves(self):
        """체크밸브 ID -> (입구 배관 구간, 출구 배관 구간). check_direction이 확정된 것만(그래프의 값은 도면 안 ID라 프로젝트 ID로 옮긴다)."""
        out = {}
        for eid, n in self.nodes.items():
            cd = n.get("check_direction") if n.get("kind") == "check_valve" else None
            if cd and cd.get("inlet") and cd.get("outlet"):
                lift = lambda x: x if x in self.nodes else project.nid(n.get("sheet"), x)  # noqa: E731
                out[eid] = (lift(cd["inlet"]), lift(cd["outlet"]))
        return out

    def allowed(self, direction):
        """흐름 방향 탐색용: 노드 -> 갈 수 있는 이웃 집합. 방향마다 한 번만 만든다."""
        if direction not in self._allowed:
            adj = self.q.adjacency("directed") if direction == "down" else self.reverse_directed()
            self._allowed[direction] = {u: {v for v, _e in lst} for u, lst in adj.items()}
        return self._allowed[direction]

    def reverse_directed(self):
        """확인된 흐름 방향 인접 목록의 거꾸로(거슬러 올라가는 탐색용)."""
        if self._reverse is None:
            rev = {k: [] for k in self.q.adjacency("directed")}
            for u, lst in self.q.adjacency("directed").items():
                for v, e in lst:
                    rev[v].append((u, e))
            for lst in rev.values():
                lst.sort()
            self._reverse = rev
        return self._reverse

    def kg_view(self, ctx):
        if self._kg_view is None:
            self._kg_view = project.kg_view(ctx.kg, ctx.pg)
        return self._kg_view

    def summary(self, ctx):
        """hazop.graph.project.summary와 같은 값. 연결 성분은 networkx 대신 합집합 찾기로 세어 APR1400 크기에서도 빠르다."""
        if self._summary is None:
            pg = ctx.pg
            by_reason = Counter(l["reason"] for l in pg["sheet_links"] if l["status"] != project.LINKED)
            parent = {n["entity_id"]: n["entity_id"] for n in pg["nodes"]}

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def components(kinds):
                for k in parent:
                    parent[k] = k
                touched = set()
                for e in pg["edges"]:
                    if kinds is None or e["kind"] in kinds:
                        a, b = e["nodes"]
                        touched.update((a, b))
                        parent[find(a)] = find(b)
                groups = {}
                for t in touched:
                    groups.setdefault(find(t), []).append(t)
                return [g for g in groups.values() if len(g) > 1], touched
            phys, _ = components({project.PHYSICAL})
            every, touched = components(None)
            sheet = {n["entity_id"]: n.get("sheet") for n in pg["nodes"]}
            self._summary = {
                "project_id": pg["project_id"], "graph_version": pg["graph_version"], "sheets": len(pg["sheets"]),
                "continuations": sum(1 for n in pg["nodes"] if n.get("kind") == "continuation"),
                "linked": sum(1 for l in pg["sheet_links"] if l["status"] == project.LINKED),
                "unlinked": dict(sorted(by_reason.items())), "direction_conflicts": by_reason.get("direction_conflict", 0),
                "physical_components": len(phys), "all_components": len(every),
                "cross_sheet_components": sum(1 for c in every if len({sheet[i] for i in c if sheet[i]}) > 1),
                "isolated_nodes": len(pg["nodes"]) - sum(len(c) for c in every),
                "duplicate_tags": len(pg["duplicate_tags"]), "manual_skipped": len(pg["manual_skipped"])}
        return self._summary


def from_graphs(project_id, graphs, node_sets=(), kg=None, results=None, fingerprint=None, manual_ops=(), system_codes=None):
    """도면 그래프 목록으로 바로 묶음을 만든다(시험과 앱 안 호출용)."""
    pg = project.build(project_id, graphs, manual_ops, system_codes)
    unknowns, unresolved = lift_unknowns(graphs)
    return ChatContext(project_id=project_id, pg=pg, kg=kg, node_sets=list(node_sets), results=results,
                       unknowns=unknowns, unresolved=unresolved, fingerprint=fingerprint)


def _listdir(path):
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _fingerprint(project_id):
    """graph.json·사람 지정 연결 기록·분석 결과·문서 지식의 (경로, 크기, 바뀐 시각). 파일 이름만 훑고 JSON은 읽지 않는다."""
    root = paths.output_root("graph")
    files = [os.path.join(root, d, "graph.json") for d in _listdir(root)]
    files.append(project.manual_path(project_id))
    res_dir = paths.folder("analysis-results", paths.safe_name(project_id))
    files += [os.path.join(res_dir, f) for f in _listdir(res_dir) if f.endswith(".json")]
    doc_root = paths.output_root(DOC_DIR)
    files += [os.path.join(doc_root, d, DOC_FILE) for d in _listdir(doc_root)]
    out = []
    for p in files:
        try:
            st = os.stat(p)
            out.append((p, st.st_size, st.st_mtime_ns))
        except OSError:
            out.append((p, None, None))
    return tuple(out)


def _load_kg(project_id):
    from hazop.kg import build as kg_build
    root = os.path.join(paths.output_root("knowledge-graph"), paths.safe_name("kg-%s" % project_id))
    if not os.path.isfile(os.path.join(root, kg_build.POINTER_FILE)):
        return None
    return kg_build.load_outputs(root)[1]


def _load_node_sets(pg):
    from hazop.study import nodes as sn
    try:
        doc = sn.load(pg)
    except Exception:  # 검토구간 파일이 깨졌어도 채팅은 도면 질문에 답한다
        return []
    return [doc] if doc else []


def roots_of(project_id):
    """서버가 파일을 열어도 되는 폴더(규격 §3.1 해석 범위 4). 폴더가 아직 없어도 자리는 적는다."""
    pid = paths.safe_name(project_id)
    return [paths.folder("study-nodes", pid), paths.folder("analysis-results", pid), paths.folder("knowledge-graph", pid),
            paths.output_root("graph"), os.path.join(paths.output_root("knowledge-graph"), paths.safe_name("kg-%s" % project_id)),
            paths.output_root(DOC_DIR), os.path.join(paths.store_root(), pid)]


def _plain(path):
    """비교용 모양: 8.3 단축 이름을 긴 이름으로 펴고(링크는 풀지 않는다) 대소문자·구분자를 맞춘다."""
    return os.path.normcase(paths.long_path(os.path.abspath(path)))


def inside_roots(path, roots):
    """열기 직전 검사. realpath로 푼 경로가 roots 중 한 곳 안이고, 푼 경로가 원래 경로와 같아야(링크·정션이 아니어야) 한다.
    두 쪽을 같은 방식(_plain)으로 고쳐 비교한다: 작업 루트가 8.3 단축 이름(러너 TEMP, 한글 계정 PC)으로 들어와도 링크로 오해하지 않는다."""
    try:
        real = _plain(os.path.realpath(path))
        if real != _plain(path):
            return False
        for root in roots:
            base = _plain(os.path.realpath(root))
            if base != _plain(root):
                continue  # 루트 자체가 링크이면 쓰지 않는다
            try:
                if os.path.commonpath([base, real]) == base:
                    return True
            except ValueError:  # 다른 드라이브
                continue
    except (OSError, ValueError):
        return False
    return False


def load_results(project_id, graph_ids, roots):
    """{도면 graph_id: 분석 결과 문서}. hazop.study.results의 읽기 함수로 저장본 그대로 읽는다(옛 0.1도 모양대로. 쓰지 않는다)."""
    from hazop.study import results as res
    out = {}
    for gid in graph_ids:
        path = res.store_path(project_id, gid)
        if not os.path.isfile(path) or not inside_roots(path, roots):
            continue
        try:
            doc = res.read(path)
        except (OSError, ValueError):
            continue
        if doc:
            out[gid] = doc
    return out


def load_docs(project_id, roots):
    """{chunk_id: 조각 기록}. 등록된 설계 문서의 문서 지식(docextract 결과)에서만 만든다. 파일 경로는 어디에도 남기지 않는다."""
    root = paths.output_root(DOC_DIR)
    documents = []
    for name in _listdir(root):
        p = os.path.join(root, name, DOC_FILE)
        if os.path.isfile(p) and inside_roots(p, roots):
            try:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and d.get("project_id") == project_id:
                documents.append(d)
    latest = {}
    for d in sorted(documents, key=lambda d: (str(d.get("material_id")), d.get("registration_version") or 0)):
        latest[d.get("material_id")] = d  # 자료마다 최신 등록 버전(auto.project_documents와 같은 규칙)
    # 같은 문서의 새 판이 대신한 옛 판은 뺀다(auto.split_documents와 같은 규칙: 대신한 새 판이 목록에 없으면 옛 판을 그대로 둔다)
    try:
        from hazop.kg import doc_revisions
        replaced = doc_revisions.load(project_id)["replaced"]
    except (OSError, ValueError, KeyError, ImportError):
        replaced = {}
    for mid in [m for m in latest if m in replaced and (replaced[m] or {}).get("by") in latest]:
        del latest[mid]
    return docs_from_documents([latest[k] for k in sorted(latest, key=str)])


def _safe_part(text):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(text))[:60] or "x"


def docs_from_documents(documents):
    """문서 지식 목록(docextract.extract 결과 모양) -> {chunk_id: 기록}. 같은 절의 설정치·운전조건·요건은 조각에 붙인다.
    chunk_id는 노드 ID이고, 다른 문서와 겹치면 '<자료 ID(material_id)>:<노드 ID>'로 구분한다. docextract가 문서 ID를 문서마다
    같은 값으로 줄 수 있어서(등록 흐름이 넘긴 상수) 문서 ID로는 구분하지 못한다. 그래도 겹치면 '#2'처럼 번호를 붙여 덮어쓰지 않는다."""
    count = Counter(n["id"] for d in documents for n in d.get("nodes") or [] if n.get("node_type") == "doc_chunk")
    out = {}
    for pos, d in enumerate(documents):
        items = {}
        for n in d.get("nodes") or []:
            if n.get("node_type") in ("setpoint", "condition", "requirement"):
                items.setdefault((n.get("source") or {}).get("locator"), []).append(n)
        owner = d.get("material_id") if d.get("material_id") is not None else "d%d" % pos
        for n in d.get("nodes") or []:
            if n.get("node_type") != "doc_chunk":
                continue
            src = n.get("source") or {}
            cid = n["id"] if count[n["id"]] == 1 else "%s:%s" % (_safe_part(owner), n["id"])
            base, k = cid, 1
            while cid in out:
                k += 1
                cid = "%s#%d" % (base, k)
            out[cid] = {"chunk_id": cid, "document_id": d.get("document_id"), "material_id": d.get("material_id"),
                        "registration_version": d.get("registration_version"), "title": d.get("title"),
                        "section": n.get("name"), "page": src.get("page"), "locator": src.get("locator"),
                        "text": n.get("text") or "",
                        "items": [{k2: i.get(k2) for k2 in ("node_type", "item", "value", "unit", "pressure_basis", "operating_mode", "text")}
                                  for i in items.get(src.get("locator"), [])]}
    return out


def load_context(project_id):
    """저장된 프로젝트 자료를 읽는다. 추출한 도면이 없으면 ValueError(프로젝트 그래프와 같음)."""
    best = project.pick_graphs(project_id)
    pg, _names = project.load_with_names(project_id)
    graphs = [best[k][1] for k in sorted(best)]
    unknowns, unresolved = lift_unknowns(graphs)
    try:
        kg = _load_kg(project_id)
    except (OSError, ValueError):
        kg = None
    roots = roots_of(project_id)
    return ChatContext(project_id=project_id, pg=pg, kg=kg, node_sets=_load_node_sets(pg),
                       results=load_results(project_id, [x["graph_id"] for x in pg["sheets"]], roots),
                       unknowns=unknowns, unresolved=unresolved, docs=load_docs(project_id, roots), roots=roots,
                       fingerprint=_fingerprint(project_id))


def refresh(ctx):
    """읽은 파일의 지문이 그대로면 같은 묶음을, 바뀌었으면 새로 읽은 묶음을 돌려준다."""
    if ctx.fingerprint is None:
        return ctx
    if _fingerprint(ctx.project_id) == ctx.fingerprint:
        return ctx
    return load_context(ctx.project_id)
