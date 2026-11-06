"""프로젝트 지식그래프 자동 생성: 도면 그래프 + 문서 지식(자동 추출) + 사람이 쓴 지식 CSV(있으면) -> knowledge_graph.json.

근거: 기획서/그래프활용.md §9(자동 생성). 앱 ①에서 도면을 추출하거나 설계 문서를 등록하면 이 모듈로 다시 빌드한다.
- 프로젝트 도면 = 출력/그래프/*/graph.json 중 project_id가 같은 것. 같은 graph_id가 여럿이면 graph.json이 가장 최근인 것
  하나만 쓰고 notes에 남긴다(빌더가 같은 graph_id 여러 버전을 차단하므로).
- 문서 지식 = 출력/문서지식/*/document_knowledge.json 중 project_id가 같은 것(자료마다 최신 등록 버전).
- 사람 지식 = 데이터/지식/<project_id>/knowledge_nodes.csv·knowledge_links.csv(둘 다 있을 때만).
- 태그 연결: 문서 문장에서 찾은 태그가 프로젝트 도면에 정확히 하나 있으면 설비 적용 관계(has_setpoint·has_condition·
  governed_by)를 후보(link_status=candidate)로 만든다. 같은 태그가 여럿(배관 라인 번호 등)이면 만들지 않고 notes에 남긴다.
- 결과는 build.write_outputs로 출력/지식그래프/kg-<project_id>/에 쓴다(같은 입력이면 같은 kg_version, 다시 써도 그대로).
"""

import hashlib
import json
import os

from hazop import paths
from hazop.kg import build, docextract, inputs

ASSEMBLER = "hazop.kg.auto"
ASSEMBLER_VERSION = "0.1.0"
DOC_FILE = "document_knowledge.json"
NODES_CSV = "knowledge_nodes.csv"
LINKS_CSV = "knowledge_links.csv"
# 문서 지식 노드 종류 -> 도면 노드에서 그 노드로 가는 설비 적용 관계(§2.3)
APPLY_KIND = {"setpoint": "has_setpoint", "condition": "has_condition", "requirement": "governed_by"}


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _scan(root, filename):
    """root/*/filename -> [(경로, dict)] (폴더 이름순). 읽을 수 없는 파일은 건너뛴다."""
    out = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        p = os.path.join(root, name, filename)
        if os.path.isfile(p):
            try:
                out.append((p, _read(p)))
            except (OSError, ValueError):
                continue
    return out


def project_ids(graph_root, doc_root):
    """도면 그래프·문서 지식에 나오는 project_id 집합(등록 경로로 만든 것만)."""
    ids = {g.get("project_id") for _, g in _scan(graph_root, "graph.json")}
    ids |= {d.get("project_id") for _, d in _scan(doc_root, DOC_FILE)}
    return sorted(i for i in ids if i)


def project_graphs(project_id, graph_root):
    """(graph 목록, notes). 같은 graph_id는 graph.json 수정 시각이 가장 늦은 것 하나."""
    best, notes = {}, []
    for path, g in _scan(graph_root, "graph.json"):
        if g.get("project_id") != project_id:
            continue
        key = (os.path.getmtime(path), path)
        gid = g.get("graph_id")
        if gid in best:
            notes.append("같은 도면 ID %s의 그래프가 여럿 — 가장 최근 추출만 씀" % gid)
        if gid not in best or key > best[gid][0]:
            best[gid] = (key, g)
    return [best[k][1] for k in sorted(best)], sorted(set(notes))


def project_documents(project_id, doc_root):
    """문서 지식 목록(자료마다 최신 등록 버전, 자료 ID순)."""
    latest = {}
    for _, d in _scan(doc_root, DOC_FILE):
        if d.get("project_id") != project_id:
            continue
        mid = d.get("material_id")
        if mid not in latest or (d.get("registration_version") or 0) > (latest[mid].get("registration_version") or 0):
            latest[mid] = d
    return [latest[k] for k in sorted(latest)]


def tag_links(documents, graphs):
    """문서 문장의 태그 -> 설비 적용 후보 관계와 notes. 태그 비교는 inputs.normalize_tag."""
    index = {}
    for g in graphs:
        for n in g["nodes"]:
            if n.get("tag"):
                index.setdefault(g["graph_id"], {}).setdefault(inputs.normalize_tag(n["tag"]), []).append(n)
    kinds = {n["id"]: n["node_type"] for d in documents for n in d["nodes"]}
    links, notes = [], []
    for d in documents:
        for m in d.get("tag_mentions") or []:
            kind = APPLY_KIND.get(kinds.get(m["node_id"]))
            if kind is None:
                continue
            for tag in m["tags"]:
                hits = [(gid, idx[inputs.normalize_tag(tag)]) for gid, idx in sorted(index.items())
                        if inputs.normalize_tag(tag) in idx]
                for gid, nodes in hits:
                    if len(nodes) > 1:
                        notes.append("태그 %s가 %s에 %d개 — 자동 연결하지 않음" % (tag, gid, len(nodes)))
                        continue
                    ref = "%s:%s" % (gid, nodes[0]["tag"])
                    lid = "krel-%s-%s" % (m["node_id"], hashlib.sha256(ref.encode("utf-8")).hexdigest()[:8])
                    links.append(docextract.link_record(lid, kind, ref, m["node_id"],
                                                        "자동 연결(문장 속 태그 %s) — 사람 확인 전" % tag))
                if not hits:
                    notes.append("태그 %s가 프로젝트 도면에 없음 — 연결하지 않음" % tag)
    return links, sorted(set(notes))


def assemble(project_id, graphs, documents, csv_dir=None):
    """입력 -> (knowledge dict, notes). knowledge는 hazop.kg.inputs.load_knowledge와 같은 계약에 pid_graphs를 더한 것."""
    nodes, links, ins = [], [], {"assembler": "%s %s" % (ASSEMBLER, ASSEMBLER_VERSION)}
    csv_paths = [os.path.join(csv_dir, f) for f in (NODES_CSV, LINKS_CSV)] if csv_dir else []
    if csv_paths and all(os.path.isfile(p) for p in csv_paths):
        manual = inputs.load_knowledge(csv_paths[0], csv_paths[1], project_id)
        nodes += manual["nodes"]
        links += manual["links"]
        ins.update(manual["inputs"])
    for d in documents:
        nodes += d["nodes"]
        links += d["links"]
    auto_links, notes = tag_links(documents, graphs)
    links += auto_links
    ins["documents"] = [{"material_id": d["material_id"], "registration_version": d["registration_version"],
                         "source_sha256": d.get("source_sha256"), "extractor": d["extractor"]} for d in documents]
    knowledge = {"schema_version": inputs.SCHEMA_VERSION, "project_id": project_id, "kg_id": "kg-%s" % project_id,
                 "inputs": ins, "pid_graphs": [g["graph_id"] for g in graphs], "nodes": nodes, "links": links}
    return knowledge, notes


def build_project(project_id, graph_root, doc_root, csv_root, out_root):
    """프로젝트 하나를 조립·빌드·저장한다. 반환 {"kg", "dir", "notes"}. 도면도 문서도 없으면 ValueError."""
    graphs, notes = project_graphs(project_id, graph_root)
    documents = project_documents(project_id, doc_root)
    if not graphs and not documents:
        raise ValueError("프로젝트 %s에 추출한 도면도 등록한 문서도 없음" % project_id)
    knowledge, more = assemble(project_id, graphs, documents, paths.safe_join(csv_root, project_id))
    kg = build.build_kg(knowledge, graphs)
    out = build.write_outputs(paths.safe_join(out_root, paths.safe_name(knowledge["kg_id"])), knowledge, kg)
    return {"kg": kg, "dir": out, "notes": notes + more}
