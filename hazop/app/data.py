"""화면이 읽는 데이터 목록·표시 계산. 파일 쓰기는 기존 API(등록·추출·그래프·뷰어 빌드)만 거친다.

- 목록: 등록정보, 추출 결과, 구간 JSON, 분석 실행 (경로는 hazop/paths.py)
- 뷰어 HTML: hazop/viewer/build.build_drawing_html (scripts/build_viewer.py와 같은 함수, 한 도면만)
- 근거 집계: 기획서/인터페이스.md §3.3 '근거 집계'(N 정의·분류 순서), 강조 요청 만들기
"""

import glob
import importlib.util
import json
import os

from hazop import paths
from hazop.analysis import ai as ai_mod
from hazop.kg.context import omission_texts
from hazop.register import registry
from hazop.viewer import build as viewer_build

# 참고값(이름만 남김): 가져올 때의 scripts/ 위치. 로딩에는 쓰지 않으며 script_module은 호출 시점 경로를 쓴다
SCRIPTS_DIR = paths.program_path("scripts")
SCRIPT_NAMES = ("extract_drawio", "extract_pdf", "build_graph")  # 화면이 읽는 스크립트(허용 목록, 묶음 datas 대상)
_script_cache = {}  # 키: 정규화한 파일 경로(루트가 바뀌면 새로 읽음)


def script_module(name):
    """scripts/<name>.py의 함수를 화면에서 그대로 쓰기 위해 모듈로 읽는다(화면 전용 처리 경로를 만들지 않음, §2.4).
    위치는 paths.program_path("scripts"): 개발 실행은 저장소, 묶인 실행(PyInstaller)은 묶음 폴더의 scripts/.
    name은 SCRIPT_NAMES 중 하나. 경로 구분자·절대 경로·목록 밖 이름은 ValueError."""
    if not isinstance(name, str) or os.path.isabs(name) or any(c in name for c in "/\\:") or ".." in name:
        raise ValueError("스크립트 이름이 아님: %r" % (name,))
    if name not in SCRIPT_NAMES:
        raise ValueError("허용하지 않은 스크립트: %r (허용: %s)" % (name, ", ".join(SCRIPT_NAMES)))
    path = paths.program_path("scripts", name + ".py")
    key = os.path.normcase(os.path.realpath(path))
    if key not in _script_cache:
        if not os.path.isfile(path):
            raise FileNotFoundError("스크립트 파일 없음(묶음에 scripts/가 들어갔는지 확인): %s" % path)
        spec = importlib.util.spec_from_file_location("hazop_script_" + name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _script_cache[key] = mod
    return _script_cache[key]


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- ① 등록 목록
def list_registrations(store_root=None):
    """<저장 루트>/<프로젝트>/registrations/<자료>/<버전>.json 최신 버전 목록. 추출·그래프 생성 여부 포함."""
    store_root = store_root or paths.store_root()
    out = []
    for path in sorted(glob.glob(os.path.join(store_root, "*", "registrations", "*", "*.json"))):
        try:
            rec = read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or "material_id" not in rec:
            continue
        out.append({"path": path, "record": rec})
    latest = {}
    for e in out:
        r = e["record"]
        key = (r.get("project_id"), r["material_id"])
        if key not in latest or (r.get("registration_version") or 0) > (latest[key]["record"].get("registration_version") or 0):
            latest[key] = e
    rows = []
    for e in sorted(latest.values(), key=lambda x: x["path"]):
        r = e["record"]
        name = None
        if r.get("status") == "registered":
            try:
                name = script_module("extract_drawio").registered_out_name(r, 0)
            except (KeyError, TypeError):
                name = None
        e["extract_name"] = name
        e["extracted"] = bool(name) and os.path.isfile(os.path.join(paths.output_root("추출"), name, "extraction.json"))
        e["graphed"] = bool(name) and os.path.isfile(os.path.join(paths.output_root("그래프"), name, "graph.json"))
        rows.append(e)
    return rows


def extract_and_graph(registration_path):
    """등록정보 → `--registration` 추출 → 그래프 생성 (scripts/extract_drawio.run_one 또는 PDF면
    scripts/extract_pdf.run_one, 그리고 scripts/build_graph.build_one). 출력 폴더 이름은 두 형식이 같다.
    반환 {"extraction", "extract_dir", "graph", "graph_dir"}. 등록 완료가 아니거나 해시 불일치면 ValueError."""
    ex = script_module("extract_drawio")
    bg = script_module("build_graph")
    record, original = registry.load_for_extraction(registration_path)
    if record.get("format") == "pdf":
        result, out_dir = script_module("extract_pdf").run_one(
            original, paths.output_root("추출"), page=0, registration=record,
            out_name=ex.registered_out_name(record, 0))
    else:
        reg_svg = registry.registered_svgs(registration_path, record)
        result, out_dir = ex.run_one(original, paths.output_root("추출"), svg="auto", page=0, registration=record,
                                     registered_svgs=reg_svg)
    graph, gdir = bg.build_one(os.path.join(out_dir, "extraction.json"), paths.output_root("그래프"))
    return {"extraction": result, "extract_dir": out_dir, "graph": graph, "graph_dir": gdir}


# ---------------------------------------------------------------- ② 추출 결과·뷰어
def list_extractions():
    root = paths.output_root("추출")
    out = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name, "extraction.json")
            if os.path.isfile(p):
                out.append({"name": name, "path": p})
    return out


def viewer_html_for(name):
    """출력/추출/<name>의 뷰어 HTML을 출력/뷰어/<name>.html로 만든다(scripts/build_viewer.py와 같은 빌드 함수).
    반환 {"html", "extraction", "graph", "svg"(bool), "error"}. SVG가 없으면 html None과 사유."""
    extraction = read_json(os.path.join(paths.output_root("추출"), name, "extraction.json"))
    graph = viewer_build.load_graph(paths.output_root("그래프"), name)
    al = extraction["coordinate_system"].get("svg_alignment") or {}
    info = {"html": None, "extraction": extraction, "graph": graph, "svg": bool(al.get("svg_file")), "error": None}
    if not al.get("svg_file"):
        info["error"] = "SVG 없음 — 도면 오버레이를 만들 수 없음(그래프 보기만 가능)"
        if graph is None:
            info["error"] += ". 그래프도 없어 표시할 수 없음 — ①에서 그래프를 만드세요"
            return info
        out_root = paths.output_root("뷰어")
        os.makedirs(out_root, exist_ok=True)
        out = paths.safe_join(out_root, "%s.graph-only.html" % paths.safe_name(name))
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(graph_only_html(graph, extraction["drawing"].get("drawing_number") or name, info["error"]))
        info["html"], info["graph_only"] = out, True
        return info
    try:
        # build_all과 같은 SVG 위치 제한(작업 루트 또는 저장 루트 안)
        svg_path = viewer_build._svg_path(al["svg_file"], [paths.work_root(), paths.store_root()])
        with open(svg_path, encoding="utf-8") as fh:
            svg_text = fh.read()
        html_text = viewer_build.build_drawing_html(extraction, svg_text, graph)
    except (OSError, ValueError) as exc:
        info["error"] = "뷰어를 만들 수 없음: %s" % exc
        return info
    out_root = paths.output_root("뷰어")
    os.makedirs(out_root, exist_ok=True)
    out = paths.safe_join(out_root, "%s.html" % paths.safe_name(name))
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html_text)
    info["html"] = out
    return info


def graph_only_html(graph, title, warning):
    """SVG가 없을 때 쓰는 그래프 전용 정적 HTML(앱 생성, 스크립트·외부 참조 없음).
    노드·관계를 도면 좌표(position)로 그린다. data-local-id·data-entity-id·#graphsvg는 기존 뷰어와 같아
    앱 브리지(노드 클릭·강조)를 그대로 쓴다. 문자열은 모두 HTML 이스케이프한다."""
    import html as _h
    from hazop.app import tokens
    col = tokens.COLORS
    pos = {n["entity_id"]: n["position"] for n in graph.get("nodes", []) if n.get("position")}
    if pos:
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        vb = "%g %g %g %g" % (min(xs) - 60, min(ys) - 60, max(xs) - min(xs) + 160, max(ys) - min(ys) + 120)
    else:
        vb = "0 0 100 100"
    edge_color = {"has_endpoint": col["physical_connection"], "signal_connection": col["signal_connection"],
                  "measurement_connection": col["measurement_connection"]}
    parts = []
    for e in graph.get("edges", []):
        a, b = (pos.get(i) for i in e["nodes"])
        if not a or not b:
            continue
        xy = 'x1="%g" y1="%g" x2="%g" y2="%g"' % (a[0], a[1], b[0], b[1])
        parts.append('<g><line class="gedge-hit" %s data-local-id="%s" stroke="transparent" stroke-width="8"/>'
                     '<line class="gedge" %s stroke="%s" stroke-width="1.6"/></g>'
                     % (xy, _h.escape(str(e.get("local_id") or ""), True), xy,
                        edge_color.get(e.get("kind"), col["unclassified"])))
    for n in graph.get("nodes", []):
        p = pos.get(n["entity_id"])
        if not p:
            continue
        seg = n.get("node_type") == "pipe_segment"
        fill = col["physical_connection"] if seg else col.get(n.get("category") or "unclassified", col["unclassified"])
        parts.append('<circle class="gnode" cx="%g" cy="%g" r="%d" fill="%s" stroke="%s" stroke-width="1.5" '
                     'data-local-id="%s" data-entity-id="%s"><title>%s</title></circle>'
                     % (p[0], p[1], 4 if seg else 7, fill, col["card"], _h.escape(str(n.get("local_id") or ""), True),
                        _h.escape(n["entity_id"], True), _h.escape("%s %s" % (n.get("tag") or "", n["entity_id"]))))
        if n.get("tag") and not seg:
            parts.append('<text x="%g" y="%g" font-size="10" fill="%s">%s</text>'
                         % (p[0] + 9, p[1] + 3, col["ink-2"], _h.escape(n["tag"])))
    return """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>%(title)s - 그래프 보기</title>
<style>html,body{margin:0;height:100%%;font-family:"%(font)s",sans-serif;background:%(bg)s;color:%(ink)s}
header{padding:8px 16px;background:%(card)s;border-bottom:1px solid %(line)s;font-size:13px}
.warn{display:inline-block;margin-left:10px;padding:2px 10px;border-radius:999px;background:%(wbg)s;color:%(wink)s}
#viewport{position:absolute;top:40px;left:0;right:0;bottom:0}#graphsvg{width:100%%;height:100%%;background:%(card)s}
.gnode{cursor:pointer}</style></head><body>
<header>도면 <b>%(title)s</b> · 그래프 보기 <span class="warn">%(warning)s</span></header>
<div id="viewport"><svg id="graphsvg" xmlns="http://www.w3.org/2000/svg" viewBox="%(vb)s" preserveAspectRatio="xMidYMid meet">
%(body)s</svg></div></body></html>
""" % {"title": _h.escape(str(title)), "warning": _h.escape(warning), "vb": vb, "body": "\n".join(parts),
       "font": tokens.FONT_FAMILY, "bg": col["bg"], "card": col["card"], "ink": col["ink"], "line": col["line"], "wbg": col["warn-bg"],
       "wink": col["warn-ink"]}


def extraction_name_for_graph_file(graph_file):
    """구간 JSON의 graph_ref.graph_file(출력/그래프/<name>/graph.json) → 추출 폴더 이름 <name>."""
    if not graph_file:
        return None
    return os.path.basename(os.path.dirname(graph_file.replace("\\", "/")))


# ---------------------------------------------------------------- ④ 구간·실행
def list_regions():
    root = paths.work_path("데이터", "구간")
    return sorted(glob.glob(os.path.join(root, "*.json")))


def list_runs(region_id):
    root = paths.output_root("분석", paths.safe_name(region_id))
    if not os.path.isdir(root):
        return []
    return sorted((os.path.join(root, n) for n in os.listdir(root)
                   if os.path.isfile(os.path.join(root, n, "analysis.json"))), reverse=True)


def current_graph(region):
    """구간 JSON graph_ref.graph_file이 가리키는 현재 그래프. 없으면 None."""
    gf = (region.get("graph_ref") or {}).get("graph_file")
    if not gf:
        return None
    full = gf if os.path.isabs(gf) else paths.work_path(gf)
    return read_json(full) if os.path.isfile(full) else None


# ---------------------------------------------------------------- 표시 계산
SELECTION_LABELS = {"selected": "선택", "excluded": "제외", "deferred": "보류"}
AI_STATUS_LABELS = ai_mod.STATUS_LABELS_KO  # 정본은 hazop/analysis/ai.py(한국어만, 영문 코드는 실행 기록 탭의 툴팁·실행 기록에만)
STATUS_LABELS = {"not_reviewed": "미검토", "reviewing": "검토 중", "deferred": "보류", "confirmed": "확정"}
DECISION_LABELS = {"accept": "수용", "modify": "수정", "reject": "기각", "defer": "보류", "not_applicable": "해당 없음",
                   "confirm_no_scenario": "시나리오 없음 확인"}
TRIGGER_LABELS = {"risk_conditional_or_worse": "제안 위험도가 〈표9〉 조건부 수용 이상",
                  "no_safeguard_found_in_graph": "그래프에서 원인과 독립인 보호수단을 찾지 못함(없음이 아니라 미확인)"}


def candidate_rows(doc):
    """편차 목록 행(§3.3 편차 목록). 제외 후보도 숨기지 않는다."""
    scen = {s["scenario_id"]: s for s in doc["scenarios"]}
    rows = []
    for c in doc["candidates"]:
        an = c.get("analysis") or {}
        sids = an.get("scenario_ids") or []
        risks = [(scen[s].get("risk_proposal") or {}).get("risk") for s in sids if s in scen]
        risks = [r for r in risks if isinstance(r, int)]
        rows.append({
            "candidate_id": c["candidate_id"], "item_id": c.get("item_id"),
            "deviation": "%s · %s(%s) — %s" % (c.get("parameter_ko"), c.get("guide_word_ko"), c.get("guide_word_en"),
                                              c.get("deviation")),
            "selection_status": c["selection_status"], "reason": c.get("reason"),
            "ai_status": an.get("ai_status") if c["selection_status"] == "selected" else None,
            "scenarios": len(sids), "max_risk": max(risks) if risks else None,
            "dics": sum(1 for d in doc["design_improvement_candidates"] if d["candidate_id"] == c["candidate_id"]),
            "holds": sum(1 for h in doc["holds"] if h.get("candidate_id") == c["candidate_id"] and h.get("status") == "open"),
        })
    return rows


def entity_local_map(graph):
    """그래프 entity_id → 뷰어 data-local-id. has_endpoint 관계는 배관 구간의 local_id를 쓴다."""
    out = {}
    if not graph:
        return out
    seg_local = {}
    for n in graph.get("nodes", []):
        if n.get("local_id"):
            out[n["entity_id"]] = n["local_id"]
            seg_local[n["entity_id"]] = n["local_id"]
    for e in graph.get("edges", []):
        if e.get("kind") == "has_endpoint":
            if e.get("segment") in seg_local:
                out[e["entity_id"]] = seg_local[e["segment"]]
        elif e.get("local_id"):
            out[e["entity_id"]] = e["local_id"]
    return out


def estimated_ids(graph):
    """추정 경로(§3.3): 분석 당시 그래프에서 flow_direction이 없는 배관 구간과 그 구간의 has_endpoint 관계."""
    if not graph:
        return set()
    segs = {n["entity_id"] for n in graph.get("nodes", [])
            if n.get("node_type") == "pipe_segment" and not n.get("flow_direction")}
    rels = {e["entity_id"] for e in graph.get("edges", []) if e.get("kind") == "has_endpoint" and e.get("segment") in segs}
    return segs | rels


def evidence_items(doc, scenario):
    """근거 N 구성(§3.3): 원인 설비, 보호수단 node_id, graph_evidence·ai_interpretation의 노드·관계,
    노드·경로가 아닌 근거 ID, 그 시나리오를 범위로 하는 보류. ev-node-<id>는 <id>와 같은 것으로 본다.
    반환 [(id, 역할)] (중복 없음, 순서 유지)."""
    seen, items = set(), []

    def add(i, role):
        if i and i not in seen:
            seen.add(i)
            items.append((i, role))

    for i in scenario.get("cause_equipment") or []:
        add(i, "cause")
    for g in scenario.get("safeguards") or []:
        add(g.get("node_id"), "safeguard")
    ge = scenario.get("graph_evidence") or {}
    ai = scenario.get("ai_interpretation") or {}
    for src in (ge, ai):
        for i in (src.get("node_ids") or []) + (src.get("relation_ids") or []):
            add(i, "path")
    for src in (ge, ai):
        for e in src.get("evidence_ids") or []:
            if e.startswith("ev-node-"):
                add(e[len("ev-node-"):], "path")
            elif not e.startswith("ev-path-"):
                add(e, "document")
    for h in doc.get("holds") or []:
        if h.get("scope") == scenario["scenario_id"]:
            add(h["hold_id"], "hold")
    return items


def evidence_summary(doc, scenario, run_graph, local_map, version_mismatch, missing_local=()):
    """근거 집계 "근거 N 중 도면 표시 a · 추정 경로 b · 미표시 c". 분류 순서: 미표시 → 추정 경로 → 도면 표시.
    local_map: 현재 뷰어의 entity→local 대응, missing_local: 웹이 highlightResult로 못 그렸다고 알린 local_id."""
    est = estimated_ids(run_graph)
    missing_local = set(missing_local)
    out = {"shown": [], "estimated": [], "unshown": []}
    for i, role in evidence_items(doc, scenario):
        lid = local_map.get(i)
        if version_mismatch or role in ("document", "hold") or lid is None or lid in missing_local:
            out["unshown"].append(i)
        elif i in est:
            out["estimated"].append(i)
        else:
            out["shown"].append(i)
    out["n"] = len(out["shown"]) + len(out["estimated"]) + len(out["unshown"])
    return out


def evidence_text(summary):
    s = "근거 %d 중 도면 표시 %d · 추정 경로 %d" % (summary["n"], len(summary["shown"]), len(summary["estimated"]))
    if summary["estimated"]:
        s += " (파선 — 실제 흐름 경로 아님)"
    return s + " · 미표시 %d" % len(summary["unshown"])


def highlight_spec(scenario, local_map, run_graph):
    """웹뷰 highlight 메시지(§2.3, §3.3 강조 규칙). 원인·경로·보호수단·추정 경로를 local_id로 보낸다."""
    est = estimated_ids(run_graph)

    def loc(ids):
        return sorted({local_map[i] for i in ids if i in local_map})

    ge = scenario.get("graph_evidence") or {}
    ai = scenario.get("ai_interpretation") or {}
    path_ids = set((ge.get("node_ids") or []) + (ge.get("relation_ids") or []) +
                   (ai.get("node_ids") or []) + (ai.get("relation_ids") or []))
    cause = set(scenario.get("cause_equipment") or [])
    sgs = [g for g in scenario.get("safeguards") or [] if g.get("node_id") in local_map]
    return {"cause": loc(cause), "path": loc(path_ids - est - cause), "estimated": loc(path_ids & est),
            "safeguards": [{"local_id": local_map[g["node_id"]], "counted": bool(g.get("counts_as_found"))}
                           for g in sgs],
            "request_id": scenario["scenario_id"]}


KG_TYPE_LABELS = {"requirement": "요건", "setpoint": "설정치", "condition": "운전조건"}
KG_CONFLICT_REASONS = {"truncated": "상한", "not_in_v4": "분석 범위 제외", "out_of_scope": "범위 밖"}
KG_TRUNC_REASONS = {"max_items": "항목 수 상한", "max_bytes": "크기 상한", "per_item_limits": "항목별 연결 상한",
                    "max_list": "목록 상한"}


def related_knowledge(doc, scenario):
    """⑤ 시나리오별 관련 지식(그래프활용 §6.4.5). 실행의 근거 묶음 knowledge_context에서만 읽는다(현재 지식그래프 아님).
    지식그래프 없이 분석한 실행이면 None.
    대상 항목: applies_to.entity_id가 시나리오 관련 노드(원인·전제 설비, graph_evidence·ai_interpretation 노드, 보호수단)인 항목과
    인용 배지가 붙는 항목. 배지: 시나리오 인용(ai_interpretation·graph_evidence의 evidence_ids), 사실 인용(후보 ai_facts)."""
    kc = ((doc.get("evidence_bundles") or {}).get(scenario["candidate_id"]) or {}).get("knowledge_context")
    if kc is None:
        return None
    ge, ai = scenario.get("graph_evidence") or {}, scenario.get("ai_interpretation") or {}
    sgs = (scenario.get("safeguards") or []) + (ai.get("safeguards") or [])
    nodes = list(dict.fromkeys((scenario.get("cause_equipment") or []) + (scenario.get("assumed_equipment") or [])
                               + (ge.get("node_ids") or []) + (ai.get("node_ids") or [])
                               + [g.get("node_id") for g in sgs if g.get("node_id")]))
    scen_cited = set((ai.get("evidence_ids") or []) + (ge.get("evidence_ids") or []))
    cand = next((c for c in doc.get("candidates") or [] if c["candidate_id"] == scenario["candidate_id"]), {})
    fact_cited = {e for f in (cand.get("analysis") or {}).get("ai_facts") or [] for e in f.get("evidence_ids") or []}
    items = []
    for it in kc.get("items") or []:
        hit = [a["entity_id"] for a in it.get("applies_to") or [] if a["entity_id"] in nodes]
        sc, fc = it["evidence_id"] in scen_cited, it["evidence_id"] in fact_cited
        if not (hit or sc or fc):
            continue
        badges = [(KG_TYPE_LABELS.get(it.get("node_type"), it.get("node_type")), "plain")]
        if it.get("unknown_fields"):
            badges.append(("미확인", "warn"))
        if it.get("conflict_with"):
            badges.append(("충돌", "err"))
        elif it.get("conflict_outside"):
            reasons = sorted({KG_CONFLICT_REASONS.get(c["reason"], c["reason"]) for c in it["conflict_outside"]})
            badges += [("충돌(상대 미포함: %s)" % r, "err") for r in reasons]
        if sc:
            badges.append(("시나리오 인용", "ui"))
        if fc:
            badges.append(("사실 인용", "ui"))
        items.append({"item": it, "entities": hit, "badges": badges, "scenario_cited": sc, "fact_cited": fc,
                      "conflict": bool(it.get("conflict_with") or it.get("conflict_outside"))})
    trunc = kc.get("truncated") or {}
    affected = set(trunc.get("affected_entity_ids") or [])
    excluded = {}
    for x in (kc.get("excluded") or {}).get("not_in_v4") or []:
        excluded[x["entity_id"]] = excluded.get(x["entity_id"], 0) + 1
    classes = []
    for n in nodes:
        labels = []
        if n in (kc.get("nodes_without_knowledge") or []):
            labels.append("지식 입력 없음")
        if n in (kc.get("nodes_with_gap") or []):
            labels.append("적용 근거 공백 — 문서 언급만 있음")
        if excluded.get(n):
            labels.append("분석 범위 제외 %d건(가설·미확인 등)" % excluded[n])
        if n in affected:
            labels.append("상한으로 생략")
        if labels:
            classes.append({"entity_id": n, "labels": labels})
    trunc_text = None
    if trunc:  # 생략 사유마다 다른 문구(항목 생략 / 연결만 생략 / 분류 목록만 생략)
        trunc_text = "지식 맥락: " + "; ".join(t.replace("포함(", "분석에 사용(", 1) if t.startswith("항목 %d개 중" % trunc["total"])
                                             else t for t in omission_texts(trunc, KG_TRUNC_REASONS))
    return {"kg_id": kc.get("kg_id"), "items": items, "nodes": classes, "truncated_text": trunc_text}


def unknown_text(value, reason=None):
    """미확인 값은 빈칸·0·'없음'으로 바꾸지 않는다."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "미확인" + (" (%s)" % reason if reason else "")
    return str(value)
