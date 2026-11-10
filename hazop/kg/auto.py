"""프로젝트 지식그래프 자동 생성: 도면 그래프 + 문서 지식(자동 추출) + 사람이 쓴 지식 CSV(있으면) -> knowledge_graph.json.

근거: 기획서/그래프활용.md §9(자동 생성). 앱 ①에서 도면을 추출하거나 설계 문서를 등록하면 이 모듈로 다시 빌드한다.
- 프로젝트 도면 = output/graph/*/graph.json 중 project_id가 같은 것. 같은 graph_id가 여럿이면 graph.json이 가장 최근인 것
  하나만 쓰고 notes에 남긴다(빌더가 같은 graph_id 여러 버전을 차단하므로).
- 문서 지식 = output/document-knowledge/*/document_knowledge.json 중 project_id가 같은 것(자료마다 최신 등록 버전).
- 사람 지식 = data/knowledge-graph/<project_id>/knowledge_nodes.csv·knowledge_links.csv(둘 다 있을 때만).
- 태그 연결: 문서 문장에서 찾은 태그가 프로젝트 도면에 정확히 하나 있으면 설비 적용 관계(has_setpoint·has_condition·
  governed_by)를 후보(link_status=candidate)로 만든다. 같은 태그가 여럿(배관 라인 번호 등)이면 만들지 않고 notes에 남긴다.
- 언급 후보: 문서 지식의 문서 조각 원문에서 hazop.kg.link.generate(정확 일치·유사 일치)로 조각 -> 도면 mentions 후보를 만든다.
  판단은 사람 지식 폴더의 link_candidates.csv 판단 열을 후보 키로 읽어 쓴다(confirmed면 확인된 언급, rejected면 넣지 않음).
  이 모듈은 그 파일을 쓰지 않는다. 사람 CSV의 조각은 기존 link.py 흐름(run_generate·run_apply)이 맡는다.
- 결과는 build.write_outputs로 output/knowledge-graph/kg-<project_id>/에 쓴다(같은 입력이면 같은 kg_version, 다시 써도 그대로).
"""

import hashlib
import json
import os

from hazop import paths
from hazop.kg import build, docextract, inputs, link
from hazop.kg.schema import REGISTRY

ASSEMBLER = "hazop.kg.auto"
ASSEMBLER_VERSION = "0.2.0"
DOC_FILE = "document_knowledge.json"
NODES_CSV = "knowledge_nodes.csv"
LINKS_CSV = "knowledge_links.csv"
CANDIDATES_CSV = link.CANDIDATES_CSV
# 문서 지식 노드 종류 -> 도면 노드에서 그 노드로 가는 설비 적용 관계(§2.3). 근거 공백 판정에 세는 3종만(analyzed_in 제외)
APPLY_KIND = REGISTRY.apply_kind_of(evidence_gap=True)


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


_HEADS = {}
HEAD_KEYS = ("project_id", "graph_id", "graph_version")


def forget_heads():
    """머리 캐시를 비운다(읽은 뒤 파일이 바뀐 것을 알았을 때)."""
    _HEADS.clear()


def graph_head(path):
    """도면 graph.json의 {project_id, graph_id, graph_version}. 파일이 없거나 지금 읽지 못하면 None, JSON이 아니면 값이 모두 None.
    바뀐 시각·크기가 같으면 다시 읽지 않는다(143쪽이면 화면마다 수 초가 걸려서)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _HEADS.get(path)
    if hit is not None and hit[0] == key:
        return dict(hit[1])
    try:
        g = _read(path)
    except OSError:
        return None  # 잠깐 못 읽은 것은 기억하지 않는다(다음에 다시 읽게)
    except ValueError:
        g = {}
    head = {k: g.get(k) if isinstance(g, dict) else None for k in HEAD_KEYS}
    _HEADS[path] = (key, head)
    return dict(head)


def project_ids(graph_root, doc_root):
    """도면 그래프·문서 지식에 나오는 project_id 집합(등록 경로로 만든 것만)."""
    ids = {(graph_head(os.path.join(graph_root, n, "graph.json")) or {}).get("project_id")
           for n in (sorted(os.listdir(graph_root)) if os.path.isdir(graph_root) else [])}
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
                total = sum(len(nodes) for _, nodes in hits)
                if total > 1:  # 프로젝트 전체에서 하나뿐일 때만 연결(도면 여러 장·같은 도면 안 중복 모두 모호)
                    notes.append("태그 %s가 프로젝트 도면에 %d개(%s) — 자동 연결하지 않음"
                                 % (tag, total, ", ".join(gid for gid, _ in hits)))
                elif total == 1:
                    gid, nodes = hits[0]
                    ref = "%s:%s" % (gid, nodes[0]["tag"])
                    lid = "krel-%s-%s" % (m["node_id"], hashlib.sha256(ref.encode("utf-8")).hexdigest()[:8])
                    inferred = "[추론]" in (nodes[0].get("tag_basis") or "")
                    links.append(docextract.link_record(
                        lid, kind, ref, m["node_id"], "자동 연결(문장 속 태그 %s%s) — 사람 확인 전"
                        % (tag, ", 도면 태그는 계통 접두를 추정한 값 [추론]" if inferred else "")))
                else:
                    notes.append("태그 %s가 프로젝트 도면에 없음 — 연결하지 않음" % tag)
    return links, sorted(set(notes))


def read_judgements(csv_dir):
    """(link_candidates.csv의 판단 행 {후보 키: 행}, notes). 파일이 없으면 빈 dict. 판단 열이 잘못되면 판단을 쓰지 않고 notes에 남긴다."""
    path = os.path.join(csv_dir, CANDIDATES_CSV) if csv_dir else None
    if not path or not os.path.isfile(path):
        return {}, []
    try:
        rows = link.read_candidates(path)
        link.check_judgements(rows)
    except (ValueError, OSError) as exc:
        return {}, ["link_candidates.csv 판단을 읽지 못함 — 언급 후보는 모두 후보로 둠: %s" % exc]
    return {r["candidate_key"]: r for r in rows if r["link_status"] != "candidate"}, []


def mention_links(documents, graphs, judgements=None):
    """문서 조각 -> mentions 관계 레코드(inputs.link_record 형식, origin doc_rule). 판단이 없으면 link_status=candidate."""
    chunks = [{"id": n["id"], "node_type": n["node_type"], "text": n.get("text"),
               "material_id": (n.get("source") or {}).get("material_id"),
               "registration_version": (n.get("source") or {}).get("registration_version")}
              for d in documents for n in d["nodes"] if n.get("node_type") == "doc_chunk"]
    passed = [g for g in graphs if (g.get("validation") or {}).get("status") == "passed"]
    out = []
    for cand in link.generate(chunks, passed)["candidates"]:
        judged = (judgements or {}).get(cand["candidate_key"])
        status = judged["link_status"] if judged else "candidate"
        if status == "rejected":
            continue
        if judged:
            cand = dict(cand, **{k: judged[k] for k in link.JUDGE_COLUMNS})
        row = link.mention_row(cand, link_status=status, knowledge_status="confirmed" if status == "confirmed" else "unknown")
        if status == "candidate":
            row["reason"] = "자동 연결 후보(%s %s) — 사람 확인 전" % (cand["method"], cand["confidence"])
        out.append(dict(inputs.link_record(row), origin="doc_rule"))
    return out


def _lost_judgements(documents, mentions, judgements):
    """사람이 확인한 조각 언급 중 지금 후보 키와 맞지 않는 것(도면·문서 판이 바뀜)을 알린다. 알리지 않으면 확인이 조용히 후보로 돌아간다."""
    chunk_ids = {n["id"] for d in documents for n in d["nodes"] if n.get("node_type") == "doc_chunk"}
    current = {(l.get("mention") or {}).get("candidate_key") for l in mentions}
    lost = [k for k, r in (judgements or {}).items()
            if r["link_status"] == "confirmed" and r.get("chunk_id") in chunk_ids and k not in current]
    if not lost:
        return []
    return ["확인한 조각 언급 %d건이 도면이나 문서 판이 바뀌어 다시 후보가 됨 — 재확인 필요" % len(lost)]


def assemble(project_id, graphs, documents, csv_dir=None, graph_notes=()):
    """입력 -> (knowledge dict, notes). knowledge는 hazop.kg.inputs.load_knowledge와 같은 계약에 pid_graphs를 더한 것.
    notes(같은 도면 ID 여럿, 연결하지 않은 태그)는 inputs.notes에도 남겨 결과 파일에서 볼 수 있게 한다."""
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
    judgements, judge_notes = read_judgements(csv_dir)
    notes = sorted(set(graph_notes)) + notes + judge_notes
    links += auto_links
    taken = {l.get("id") for l in links}
    mentions = mention_links(documents, graphs, judgements)
    links += [l for l in mentions if l["id"] not in taken]
    notes += _lost_judgements(documents, mentions, judgements)
    ins["notes"] = notes
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
    knowledge, notes = assemble(project_id, graphs, documents, paths.safe_join(csv_root, project_id), notes)
    kg = build.build_kg(knowledge, graphs)
    out = build.write_outputs(paths.safe_join(out_root, paths.safe_name(knowledge["kg_id"])), knowledge, kg)
    return {"kg": kg, "dir": out, "notes": notes}
