"""도면 하나를 보며 읽는 프로젝트 색인과 관련 항목 계산 (UIUX 개선명세 U-01 명령 팔레트, U-04 탐색기, U-14 관련 항목).

색인은 디스크의 그래프·검토구간·분석 결과·지식그래프를 읽기만 한다. 화면의 편집 상태는 각 화면이 기준이다.
선택(sel)은 {"kind": "component"|"node"|"cell", "drawing", "entity_id", "node_id", "deviation_id"} 중 해당 키를 쓴다.
관련 항목은 [(섹션 이름, [Row])] 이고 Row.target은 누르면 열 선택(sel과 같은 모양) 또는 None이다.
"""

from dataclasses import dataclass

from hazop.app import project_ctx
from hazop.graph import project
from hazop.study import ai_cells, nodes
from hazop.study import results as res

SECTIONS = ("도면 위치", "구성요소", "지식그래프 근거", "같은 구성요소를 쓰는 다른 칸", "변경 이력")
KG_TEXT_FIELDS = ("item", "name", "text")


@dataclass
class Row:
    text: str
    detail: str = ""
    target: dict = None


def entity_label(node):
    if node is None:
        return "?"
    first = (node.get("label_text") or "").split("\n")[0].strip()
    return node.get("tag") or first or node.get("kind") or node["entity_id"]


class DrawingIndex:
    """도면 하나(name)를 보며 읽는 프로젝트 색인. 없는 것은 None.
    graph는 프로젝트 그래프(구성요소 ID = 프로젝트 ID), node_set은 프로젝트 검토구간 저장본(확정·제안)만 본다.
    옛 도면별 저장본 이전은 ④가 한다(색인은 읽기만). view는 표기·경계를 붙인 node_set 사본."""

    def __init__(self, name):
        self.name = name
        self.ctx = project_ctx.load(name) if name else None
        self.graph = self.ctx.pg if self.ctx else None
        self.node_set = self.view = self.results = self.kg = None
        self.deviations = res.load_deviations()
        self.entities = {n["entity_id"]: n for n in (self.graph or {}).get("nodes", [])}
        if not self.graph:
            return
        self._dn_of_sheet = {s["graph_id"]: s["drawing_number"] for s in self.graph["sheets"]}
        try:
            self.node_set = nodes.load(self.graph)
        except (OSError, ValueError):
            self.node_set = None
        if self.node_set:
            self.view = self.view_of(self.node_set)
        usable = (self.node_set and nodes.active_nodes(self.node_set)  # ⑤ 화면이 쓰는 조건과 같다(구간 밖과 상관없음)
                  and not nodes.is_stale(self.node_set, self.graph))
        if usable:
            try:
                doc = res.load(self.node_set)
            except (OSError, ValueError):
                doc = None
            if doc is not None:
                doc, problems, _bad = res.partition(doc, self.node_set)  # 문제 칸만 빼고 나머지는 쓴다(⑤와 같음)
                self.results = None if problems else doc
        kg = ai_cells.load_kg_for(self.node_set or {"graph_id": self.graph["graph_id"],
                                                    "project_id": self.graph.get("project_id")})[0]
        self.kg = project.kg_view(kg, self.graph) if kg is not None else None

    def view_of(self, node_set):
        """표기를 붙인 사본. 그래프가 바뀌어 없는 구성요소를 가리키는 저장본이면 None."""
        try:
            return self.ctx.view(node_set)
        except (KeyError, ValueError):
            return None

    @property
    def drawing_number(self):
        return self.ctx.drawing_number if self.ctx else self.name

    def label(self, entity_id):
        """구성요소 글자. 다른 도면의 것은 "RC-P01(101)"처럼 짧은 도면 번호를 붙인다."""
        n = self.entities.get(entity_id)
        dn = self._dn_of_sheet.get((n or {}).get("sheet")) if self.graph else None
        text = entity_label(n)
        return "%s(%s)" % (text, self.ctx.short.get(dn, dn)) if dn and dn != self.drawing_number else text

    def drawing_name_of(self, entity_id):
        """구성요소가 있는 도면의 추출 이름(②에서 열 이름). 도면 밖(도면 연결 배관)이면 None."""
        n = self.entities.get(entity_id) or {}
        return self.ctx.names.get(n.get("sheet")) if self.ctx and self.graph else None

    def node_drawing_name(self, node_id):
        """구간을 열 도면의 추출 이름: 이 도면을 지나면 이 도면, 아니면 그 구간의 첫 도면."""
        vn = next((n for n in (self.view or {}).get("nodes", []) if n["node_id"] == node_id), None)
        if not vn or not vn.get("drawings") or self.drawing_number in vn["drawings"]:
            return self.name
        return self.ctx.drawing_names.get(vn["drawings"][0]) or self.name

    def node(self, node_id):
        return next((n for n in (self.node_set or {}).get("nodes", []) if n["node_id"] == node_id), None)

    def node_index(self, node_id):
        return next((i for i, n in enumerate((self.node_set or {}).get("nodes", [])) if n["node_id"] == node_id), None)

    def deviation(self, deviation_id):
        return next((d for d in self.deviations if d["deviation_id"] == deviation_id), None)

    def summary(self):
        return res.matrix_summary(self.results) if self.results else {}

    def unreviewed(self, node_id):
        return sum(s.get("unreviewed") or 0 for s in self.summary().get(node_id, {}).values())

    def components(self):
        """도면 객체(태그나 이름이 있는 노드)만. [(entity_id, 글자, 종류)]"""
        out = []
        for n in (self.graph or {}).get("nodes", []):
            if n.get("node_type", "drawing_object") != "drawing_object" or not n.get("local_id"):
                continue
            out.append((n["entity_id"], self.label(n["entity_id"]), n.get("kind") or ""))
        return out

    def cells(self):
        """[(node, deviation, 요약)] 확정 구간 × 편차 전부(결과가 없으면 요약은 None)."""
        if not self.node_set:
            return []
        summary = self.summary()
        return [(n, d, summary.get(n["node_id"], {}).get(d["deviation_id"]))
                for n in nodes.active_nodes(self.node_set) for d in self.deviations]

    def cell_doc(self, node_id, deviation_id):
        return next((c for c in (self.results or {}).get("cells", [])
                     if (c["node_id"], c["deviation_id"]) == (node_id, deviation_id)), None)

    def kg_evidence(self, entity_ids):
        """선택한 구성요소에 닿는 지식 항목(적용 관계의 지식 노드, 언급한 문서 조각). [Row]"""
        if self.kg is None or not self.graph or not entity_ids:
            return []
        from hazop.kg import algo
        try:
            _nodes, links, _ = algo.v4_items(self.kg, self.graph)
        except (KeyError, ValueError):
            return []
        knodes = {n["id"]: n for n in self.kg["nodes"] if n.get("id") is not None}
        ids, seen, rows = set(entity_ids), set(), []
        for link, a, b in links:
            kid = b if a in ids and link["kind"] != "mentions" else a if b in ids and link["kind"] == "mentions" else None
            if kid is None or kid in seen or kid not in knodes:
                continue
            seen.add(kid)
            k = knodes[kid]
            text = next((str(k[f]) for f in KG_TEXT_FIELDS if k.get(f)), kid)
            if k.get("value") is not None:
                text = "%s %s%s" % (text, k["value"], k.get("unit") or "")
            src = k.get("source") or {}
            where = " ".join(str(src[f]) for f in ("document_id", "locator") if src.get(f))
            rows.append(Row(text, "%s · %s" % (k.get("node_type") or "-", where) if where else k.get("node_type") or "-"))
        return rows


STATUS_LABELS = {"proposed": "제안", "revised": "수정", "approved": "승인", "rejected": "기각"}
OP_LABELS = {"propose": "제안", "status": "상태", "edit": "수정", "merge": "병합", "split": "분할", "rename": "이름",
             "confirm": "확정", "reopen": "확정 해제", "add": "넣기", "remove": "빼기",
             "ie_hint": "초기사건 판정"}


NO_RESULTS = ("", "⑤ 결과 없음(구간 확정 전이거나 분석 전)")


def progress_table(results, n_deviations, summary=None):
    """탐색기 구간 진행 {node_id: (오른쪽 짧은 글자, 도구 설명)}. 결과 칸을 한 번만 훑는다(구간마다 전체 요약을 다시 만들면
    구간 수의 제곱으로 느려짐). 결과에 칸이 없는 구간은 표에 없으므로 node_progress(표, node_id)로 읽는다.
    summary: 이미 만든 res.matrix_summary(results)(없으면 여기서 한 번 만든다)."""
    if not results:
        return {}
    summary = res.matrix_summary(results) if summary is None else summary
    by_node = {}
    for c in results["cells"]:
        by_node.setdefault(c["node_id"], []).append(c)
    return {nid: _progress(cells, summary.get(nid, {}), n_deviations) for nid, cells in by_node.items()}


def node_progress(table, node_id, n_deviations):
    """progress_table 한 줄. 결과가 없으면(표가 None) ("", 이유), 결과에 이 구간 칸이 없으면 '분석 전'."""
    if table is None:
        return NO_RESULTS
    return table.get(node_id) or _progress([], {}, n_deviations)


def _progress(cells, node_summary, n_deviations):
    """수치는 ⑤ 행렬과 같다: 분석된 칸(분석 전·실패 아님), 미검토 항목, AI 실행 실패 칸."""
    failed = sum((c.get("ai_run") or {}).get("status") == "failed" for c in cells)
    analyzed = sum(c["state"] != "not_analyzed" and (c.get("ai_run") or {}).get("status") != "failed" for c in cells)
    unreviewed = sum(s["unreviewed"] for s in node_summary.values())
    detail = "⑤ 결과: 분석 %d/%d칸 · 미검토 %d · 실패 %d" % (analyzed, n_deviations, unreviewed, failed)
    parts = (["미%d" % unreviewed] if unreviewed else []) + (["실패%d" % failed] if failed else [])
    if parts:
        return "·".join(parts), detail
    if not analyzed:
        return "분석 전", detail
    return ("완료" if analyzed >= n_deviations else "%d/%d" % (analyzed, n_deviations)), detail


def history_text(h):
    op = h.get("op") or "-"
    if op == "status":
        return "%s → %s" % (STATUS_LABELS.get(h.get("from"), h.get("from") or "-"), STATUS_LABELS.get(h.get("to"), h.get("to")))
    d = h.get("detail") if isinstance(h.get("detail"), dict) else {}
    what = d.get("node_id") or d.get("into") or d.get("reviewer") or ""
    return OP_LABELS.get(op, op) + (" · %s" % what if what else "")


def cell_text(index, node, dev, s):
    """칸 한 줄 요약: 'S2 × 유량 증가', '위험 4 · 미검토 1' 같은 꼬리."""
    run = ((index.cell_doc(node["node_id"], dev["deviation_id"]) or {}).get("ai_run") or {})
    if run.get("status") == "failed":
        tail = "! 실패"
    elif not s or s.get("state") == "not_analyzed":
        tail = "분석 전"
    else:
        parts = ["위험 %d" % s["max_risk"]] if s.get("max_risk") is not None else []
        parts.append("미검토 %d" % s["unreviewed"] if s.get("unreviewed") else "%d건" % (s.get("scenarios") or 0))
        tail = " · ".join(parts)
    return "%s × %s" % (node["node_id"], dev["label"]), tail


def selection_entities(index, sel):
    if sel.get("kind") == "component":
        return [sel["entity_id"]] if sel.get("entity_id") else []
    n = index.node(sel.get("node_id"))
    return list(n["members"]) if n else []


def selection_title(index, sel):
    kind = sel.get("kind")
    if kind == "component":
        return index.label(sel.get("entity_id"))
    n = index.node(sel.get("node_id"))
    name = "%s %s" % (n["node_id"], n["name"]) if n else sel.get("node_id") or "?"
    if kind == "cell":
        d = index.deviation(sel.get("deviation_id"))
        return "%s × %s" % (sel.get("node_id"), d["label"] if d else sel.get("deviation_id"))
    return name


def related(index, sel):
    """선택 하나의 관련 항목 섹션들. 섹션은 SECTIONS 순서이고 행이 없는 섹션도 빈 목록으로 둔다."""
    out = {k: [] for k in SECTIONS}
    if not sel or not index.graph:
        return [(k, out[k]) for k in SECTIONS]
    drawing = index.name
    ents = selection_entities(index, sel)
    by_id = index.entities
    tags = [index.label(e) for e in ents]
    n = index.node(sel.get("node_id")) if sel.get("node_id") else None
    if n is not None:
        vn = next((v for v in (index.view or {}).get("nodes", []) if v["node_id"] == n["node_id"]), {})
        out["도면 위치"].append(Row("%s · 도면 %s" % (n["node_id"], ", ".join(vn.get("drawings") or [index.drawing_number])),
                                  "④ 구간에서 보기",
                                  {"kind": "node", "drawing": index.node_drawing_name(n["node_id"]),
                                   "node_id": n["node_id"]}))
    for eid in ents[:1] if sel.get("kind") == "component" else []:
        dn = index._dn_of_sheet.get((by_id.get(eid) or {}).get("sheet")) or index.drawing_number
        out["도면 위치"].append(Row("%s · 도면 %s" % (tags[0], dn), "② 도면에서 보기",
                                  {"kind": "component", "drawing": index.drawing_name_of(eid) or drawing,
                                   "entity_id": eid, "open": "drawing"}))
    for eid, tag in zip(ents, tags):
        out["구성요소"].append(Row(tag, (by_id.get(eid) or {}).get("kind") or "그래프에 없음",
                                {"kind": "component", "drawing": index.drawing_name_of(eid) or drawing,
                                 "entity_id": eid, "open": "drawing"}))
    out["지식그래프 근거"] = index.kg_evidence(ents)
    here = (sel.get("node_id"), sel.get("deviation_id")) if sel.get("kind") == "cell" else None
    owners = set()
    for e in ents:
        owners |= set(nodes.nodes_of(index.node_set, e)) if index.node_set else set()
    for node, dev, s in index.cells():
        if node["node_id"] not in owners or (node["node_id"], dev["deviation_id"]) == here:
            continue
        doc = index.cell_doc(node["node_id"], dev["deviation_id"]) or {}
        if not doc.get("entries") and (doc.get("ai_run") or {}).get("status") != "failed":
            continue  # 분석 전·항목 없는 칸까지 늘어놓지 않는다(구간 5 × 편차 44)
        text, tail = cell_text(index, node, dev, s)
        out["같은 구성요소를 쓰는 다른 칸"].append(
            Row(text, tail, {"kind": "cell", "drawing": drawing, "node_id": node["node_id"],
                             "deviation_id": dev["deviation_id"]}))
    if sel.get("kind") == "cell":
        doc = index.cell_doc(sel.get("node_id"), sel.get("deviation_id")) or {}
        for e in doc.get("entries") or []:
            for h in e.get("history") or []:
                out["변경 이력"].append(Row(history_text(h), h.get("at") or ""))
    elif index.node_set:
        for h in (index.node_set.get("history") or [])[-8:]:
            out["변경 이력"].append(Row(history_text(h), h.get("at") or ""))
    return [(k, out[k]) for k in SECTIONS]
