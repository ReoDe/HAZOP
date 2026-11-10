"""화면이 보는 프로젝트 맥락: 도면 하나를 보면서 프로젝트 전체 그래프·검토구간(S1…Sn)을 쓴다.

근거: 사용자 결정(2026-11-07) 구간 ID는 프로젝트 전체에서 하나, 어느 도면에서 보든 같다. ④⑤·탐색기·③은
도면별 graph.json이 아니라 hazop.graph.project의 프로젝트 그래프와 그 검토구간 저장본을 쓴다.
- 구간 ID·구성요소 ID는 프로젝트 ID("<graph_id>/<entity_id>"). 뷰어(도면 한 장)의 data-local-id와는 local_of로 잇는다.
- 표기·경계·칩은 hazop.study.span.annotate(view)가 만든다. 저장은 annotate 전 원본(node_set)만 한다.
- 이전: 프로젝트 저장본이 없고 옛 도면별 저장본이 있으면 백업 뒤 legacy_ids를 붙인 프로젝트 집합(제안 상태)을 만든다.
  옛 확정은 legacy_sources에 남고, 범위가 바뀐 구간이 있으므로 프로젝트 집합은 사람이 다시 확정한다.
  ⑤ 결과는 프로젝트 집합이 확정된 뒤(결과의 study_nodes_ref가 확정본 기준이어야 하므로) 옮긴다. 옛 파일은 지우지 않는다.
"""

import hashlib
import json
import os

from hazop import paths, store_io
from hazop.graph import project
from hazop.study import nodes as sn
from hazop.study import results as res
from hazop.study import span

SPAN_MARK = "⇄"


def node_label(n):
    """목록·행 이름: "S7 써지 배관 RC-L010 [101 → 102] ⇄"(여러 도면에 걸친 구간만 ⇄)."""
    text = n.get("display_name") or "%s %s" % (n["node_id"], n["name"])
    return text + (" " + SPAN_MARK if n.get("spans_drawings") else "")


def counts_text(n, drawing_number):
    """"이 도면 4 / 전체 9"."""
    return "이 도면 %d / 전체 %d" % ((n.get("members_by_drawing") or {}).get(drawing_number, 0), n.get("member_count", 0))


def boundary_text(n):
    """"시작: RC-PZ01 (102) / 끝: RC-RV01 (101)"."""
    b = n.get("boundary") or {}

    def one(x):
        if not x:
            return "-"
        short = x.get("drawing_short") or x.get("drawing")
        return "%s (%s)" % (x["label"], short) if short else x["label"]
    return "시작: %s / 끝: %s" % (one(b.get("start")), one(b.get("end")))


_NAMES = {}


def graph_names(project_id):
    """{도면 graph_id: output/graph 폴더 이름(= ②④⑤ 도면 고르기 이름)}. 이 프로젝트 도면만, 같은 graph_id면 가장 최근 것
    (project.load가 고르는 판과 같은 규칙). 입력 파일 지문이 같으면 다시 읽지 않는다."""
    key = _graph_inputs(project_id)
    hit = _NAMES.get(project_id)
    if hit is not None and hit[0] == key:
        return dict(hit[1])
    out = _read_graph_names(project_id)
    _NAMES[project_id] = (key, out)
    return dict(out)


def _read_graph_names(project_id):
    return {gid: v[2] for gid, v in project.pick_graphs(project_id).items() if gid}


_PROJECT_GRAPHS = {}
_VIEWS = {}


def _graph_inputs(project_id):
    """project.load가 읽는 파일의 (경로, 바뀐 시각, 크기). 하나라도 바뀌면 프로젝트 그래프를 다시 짓는다."""
    root = paths.output_root("graph")
    files = [os.path.join(root, n, "graph.json") for n in sorted(os.listdir(root))] if os.path.isdir(root) else []
    files += [project.manual_path(project_id), paths.folder("APR1400", project.SYSTEM_CODES_FILE)]
    out = []
    for f in files:
        try:
            st = os.stat(f)
        except OSError:
            continue
        out.append((f, st.st_mtime_ns, st.st_size))
    return (paths.work_root(), tuple(out))


def project_graph(project_id):
    """프로젝트 그래프. 화면을 옮길 때마다 143쪽을 다시 읽고 짓지 않게, 입력 파일 지문이 같으면 지은 것을 그대로 준다.
    돌려준 dict는 여러 화면이 함께 쓰므로 고치지 않는다(읽기 전용)."""
    key = _graph_inputs(project_id)
    hit = _PROJECT_GRAPHS.get(project_id)
    if hit is not None and hit[0] == key:
        return hit[1]
    pg, names = project.load_with_names(project_id)
    _NAMES[project_id] = (key, names)  # 같은 파일을 읽어 고른 이름(graph_names가 다시 읽지 않게)
    if hit is not None:  # 옛 그래프를 붙잡은 표기 사본은 버린다(143쪽 그래프가 메모리에 여러 벌 남지 않게)
        for k in [k for k, v in _VIEWS.items() if v[0] is hit[1]]:
            del _VIEWS[k]
    _PROJECT_GRAPHS[project_id] = (key, pg)
    return pg


class ProjectContext:
    """도면 하나(name)를 보는 프로젝트 맥락. pg가 None이면 프로젝트 그래프를 만들 수 없는 것(error에 사유)."""

    def __init__(self, name, sheet):
        self.name, self.sheet = name, sheet
        self.graph_id = sheet.get("graph_id")
        self.drawing_number = (sheet.get("source") or {}).get("drawing_number") or sheet.get("drawing_number") or name
        self.project_id = project.project_id_of(sheet)
        self.pg, self.error, self.node_set, self.saved, self.notice = None, None, None, False, None
        self.set_fp = None
        try:
            self.pg = project_graph(self.project_id)
        except (OSError, ValueError) as exc:
            self.error = "프로젝트 그래프를 만들 수 없음: %s" % exc
            return
        self.by_id = {n["entity_id"]: n for n in self.pg["nodes"]}
        self.short = span.short_numbers(s["drawing_number"] for s in self.pg["sheets"])[1]
        self.names = graph_names(self.project_id)
        adopted = next((s for s in self.pg["sheets"] if s["graph_id"] == self.graph_id), None)
        if self.names.get(self.graph_id) not in (name, paths.safe_name(name)) or (adopted or {}).get("graph_version") != sheet.get("graph_version"):
            # 같은 graph_id의 다른(더 최근) 판이 프로젝트 그래프에 들어가 있다. 이 판의 local_id를 프로젝트 ID로 이으면
            # 다른 구성요소를 편집하게 되므로 프로젝트 기능을 막는다.
            self.error = ("이 도면(%s)의 그래프 판이 프로젝트 그래프에 쓰인 판(%s)과 다릅니다. 같은 도면의 최신 추출 결과를 여세요."
                          % (name, self.names.get(self.graph_id) or "없음"))
            self.pg = None
            return
        self.drawing_names = {s["drawing_number"]: self.names.get(s["graph_id"]) for s in self.pg["sheets"]}
        self.local_of, self.pid_of_local = {}, {}
        prefix = self.graph_id + project.SEP
        for n in self.pg["nodes"]:
            if n.get("sheet") == self.graph_id and n.get("local_id"):
                self.local_of[n["entity_id"]] = n["local_id"]
                self.pid_of_local[n["local_id"]] = n["entity_id"]
        for e in self.pg["edges"]:  # has_endpoint 관계는 배관 구간 local_id(data.entity_local_map과 같은 규칙)
            if e.get("sheet") == self.graph_id and e["entity_id"].startswith(prefix):
                seg = self.local_of.get(e.get("segment")) if e.get("kind") == "has_endpoint" else e.get("local_id")
                if seg:
                    self.local_of[e["entity_id"]] = seg

    # ---------------------------------------------------------------- 구간 집합
    def load_set(self):
        """저장본(없으면 이전 또는 새 제안). (node_set, saved). 읽기 실패는 ValueError·OSError 그대로.
        set_fp에 읽은 저장 파일의 지문을 둔다(파일이 없으면 None). 화면이 저장할 때 expect로 쓴다."""
        saved, self.set_fp = sn.load_fp(self.pg)
        if saved is not None:
            self.node_set, self.saved = saved, True
            return saved, True
        migrated = migrate_sets(self.pg)
        if migrated is not None:
            self.node_set, self.saved, self.notice, self.set_fp = migrated[0], True, migrated[1], migrated[2]
            return self.node_set, True
        sheets, problem = sn.exclusion_for(self.pg)
        if problem:
            self.notice = problem
        self.node_set, self.saved = sn.propose(self.pg, exclude_sheets=sheets), False
        return self.node_set, False

    def view(self, node_set=None):
        """표기·경계·칩을 붙인 사본(span.annotate). 경계 항목에 drawing_short를 더한다.
        같은 프로젝트 그래프·같은 내용의 집합이면 지은 사본을 그대로 준다(화면 여럿이 함께 쓰므로 고치지 않는다)."""
        ns = node_set if node_set is not None else self.node_set
        digest = hashlib.sha1(json.dumps(ns, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        key = (id(self.pg), digest)
        hit = _VIEWS.get(key)
        if hit is not None and hit[0] is self.pg:
            return hit[1]
        v = span.annotate(ns, self.pg)
        for n in v["nodes"]:
            for x in (n.get("boundary") or {}).values():
                if x and x.get("drawing"):
                    x["drawing_short"] = self.short.get(x["drawing"], x["drawing"])
        if len(_VIEWS) >= 8:  # 최근 몇 개만(편집마다 새 집합이 생긴다)
            _VIEWS.pop(next(iter(_VIEWS)))
        _VIEWS[key] = (self.pg, v)  # pg를 붙잡아 id 재사용으로 다른 그래프의 사본을 주지 않게
        return v

    def chips(self, n, drawing_number=None):
        """보는 도면(기본: 이 도면)에 있는 연결점 칩 [{entity_id, local_id, text, drawing, name, node_id}].
        같은 상대 도면·상대 구간은 한 번만."""
        dn = drawing_number or self.drawing_number
        out, seen = [], set()
        for c in n.get("continuations") or []:
            if c["drawing"] != dn:
                continue
            target = c["to_node_ids"][0] if c["to_node_ids"] else n["node_id"]
            key = (c["to_drawing"], target)
            if key in seen:
                continue
            seen.add(key)
            out.append({"entity_id": c["entity_id"], "local_id": self.local_of.get(c["entity_id"]),
                        "text": span.continuation_chip(n["node_id"], c), "drawing": c["to_drawing"],
                        "name": self.drawing_names.get(c["to_drawing"]), "node_id": target})
        return out

    def unlinked(self):
        """이 도면의 미연결 연결점 [{entity_id, local_id, label, reason, reason_text, source_object_id}]."""
        out = []
        for l in self.pg["sheet_links"]:
            if l["status"] == project.LINKED:
                continue
            for end in (l["from"], l.get("to")):
                if end and end["graph_id"] == self.graph_id:
                    eid = project.nid(end["graph_id"], end["entity_id"])
                    n = self.by_id.get(eid) or {}
                    out.append({"entity_id": eid, "local_id": n.get("local_id"), "label": continuation_label(n),
                                "reason": l["reason"], "reason_text": project.REASONS.get(l["reason"], l["reason"]),
                                "source_object_id": end.get("source_object_id") or n.get("source_object_id"),
                                "link_id": l["link_id"]})
        return out

    def coverage_text(self, node_set=None):
        """"프로젝트 100% · 이 도면 100%"."""
        c = span.coverage_by_drawing(node_set or self.node_set, self.pg)
        here = c["drawings"].get(self.drawing_number) or {"ratio": 1.0}
        return "프로젝트 %d%% · 이 도면 %d%%" % (round(c["project"]["ratio"] * 100), round(here["ratio"] * 100)), c

    def tag_label(self, text):
        """다른 도면 태그를 "RC-P01(101)"로(표시용)."""
        if not hasattr(self, "_tags"):
            self._tags = span.tag_drawings(self.pg)
        return span.label_tags(text, self._tags, self.drawing_number, self.short)


def continuation_label(n):
    first = (n.get("label_text") or "").split("\n")[0].strip()
    return n.get("tag") or first or n.get("entity_id")


def load(name):
    """추출 이름 → ProjectContext. 도면 그래프가 없으면 None."""
    from hazop.viewer import build as viewer_build
    sheet = viewer_build.load_graph(paths.output_root("graph"), name) if name else None
    return ProjectContext(name, sheet) if sheet else None


# ---------------------------------------------------------------- 이전

def _old_sets(pg):
    out = []
    for s in pg["sheets"]:
        g = {"graph_id": s["graph_id"],
             "project_id": None if pg["project_id"] == project.UNREGISTERED_PROJECT else pg["project_id"]}
        try:
            old = sn.load(g)
        except (OSError, ValueError):
            continue
        if old and old.get("graph_id") == s["graph_id"]:
            out.append((g, old))
    return out


def _write_report(folder, report):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "이전보고.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def migrate_sets(pg):
    """프로젝트 집합 저장본이 없고 옛 도면별 저장본이 있으면 백업 뒤 이전한 집합(제안 상태)을 저장한다.
    (집합, 알림 글, 쓴 파일의 지문) 또는 None(옮길 것 없음). 옛 파일은 그대로 둔다."""
    olds = _old_sets(pg)
    if not olds or os.path.isfile(sn.store_path(pg["project_id"], pg["graph_id"])):
        return None
    old_sets = [o for _g, o in olds]
    files = [sn._readable_path(g.get("project_id"), g["graph_id"]) for g, _o in olds]
    folder = store_io.backup(files, "검토구간-이전")
    sheets, problem = sn.exclusion_for(pg)
    if problem:
        raise ValueError(problem)  # 이전은 한 번뿐이라, 표시를 못 읽은 채 옮기지 않고 저장본을 읽지 못한 것처럼 알린다
    proposal = sn.propose(pg, exclude_sheets=sheets)
    mapping = span.legacy_map(old_sets, proposal, pg)
    out = span.migrate_set(old_sets, proposal, pg)
    path, fp = sn.save_fp(out)
    exact =sum(1 for v in mapping.values() if v["exact"])
    confirmed = [o["graph_id"].replace("graph-", "") for o in old_sets if o.get("status") == "confirmed"]
    _write_report(folder, {"kind": "node_set_migration", "at": sn.now_utc(), "written": path,
                           "mapping": mapping, "old_files": files})
    text = ("도면별 검토구간 %d개를 프로젝트 구간 ID로 옮겼습니다(같은 범위 %d · 도면을 넘어 넓어짐·바뀜 %d). "
            "%s프로젝트 구간은 '제안' 상태라 ④에서 다시 확정해야 합니다. 옛 파일은 그대로 두었고 백업: %s"
            % (len(mapping), exact, len(mapping) - exact,
               ("옛 확정본(%s)은 기록으로 남겼고 " % ", ".join(confirmed)) if confirmed else "", folder))
    return out, text, fp


def migrate_results(pg, node_set):
    """확정된 프로젝트 집합에 프로젝트 결과가 없고 옛 도면별 결과가 있으면 백업 뒤 옮겨 저장한다.
    (결과, 알림 글) 또는 None. 대응 없는 옛 칸이 있으면 쓰지 않고 (None, 사유)."""
    if node_set.get("status") != "confirmed" or os.path.isfile(res.store_path(node_set["project_id"], node_set["graph_id"])):
        return None
    olds = _old_sets(pg)
    old_results, files = [], []
    for g, o in olds:
        try:
            r = res.load(o)
        except (OSError, ValueError) as exc:  # 일부만 옮기면 남은 결과는 프로젝트 결과가 생긴 뒤 다시 옮길 수 없다
            return None, "옛 분석 결과를 옮기지 않음: %s 결과를 읽을 수 없음(%s). 옛 파일은 그대로 있습니다." % (g["graph_id"], exc)
        if r:
            old_results.append(r)
            files.append(res._readable_path(g.get("project_id"), g["graph_id"]))
    if not old_results:
        return None
    out, report = span.migrate_results(old_results, [o for _g, o in olds], node_set, res.load_deviations(), pg)
    stop = span.blocked(report)
    if stop:
        labels = {"unmapped": "옮길 칸 없음", "unmapped_nodes": "대응 구간 없음", "unmapped_deviations": "대응 편차 없음",
                  "to_excluded": "사람 판정 항목이 스크리닝 제외 구간으로 감(④에서 꺼낸 뒤 다시 확정)"}
        return None, "옛 분석 결과를 옮기지 않음: %s. 옛 파일은 그대로 있습니다." % (
            ", ".join("%s %d건" % (labels.get(k, k), len(report[k])) for k in stop))
    folder = store_io.backup(files, "분석결과-이전")
    path = res.save(out, node_set["project_id"])
    _write_report(folder, dict(report, kind="results_migration", at=sn.now_utc(), written=path, old_files=files))
    text = ("옛 도면별 분석 결과 항목 %d건을 프로젝트 구간으로 옮겼습니다(사람 검토 %d건은 상태 그대로, "
            "범위 바뀐 구간 항목 %d건은 '범위 바뀜' 표시). 옛 파일은 그대로 두었고 백업: %s"
            % (report["moved_entries"], report["human_entries"], report["scope_changed_entries"], folder))
    return out, text
