"""같은 도면 번호의 원본이 여러 형식으로 들어왔을 때 어느 것을 프로젝트 그래프에 쓸지(HZ-PLN-22 §4.2 (나), 검토 4번).

도면 번호가 같은 그래프는 `graph_id`(`graph-<도면 번호>`)가 같아서, 지금까지는 수정 시각이 가장 늦은 것이 말없이 이겼다. drawio·PDF·DEXPI가
같은 번호로 들어오면 마지막에 추출한 형식이 다른 형식을 밀어냈다. 이 모듈이 그것을 막는다.
- 같은 번호의 그래프가 모두 같은 형식(또는 형식을 알 수 없음)이면 지금 규칙 그대로다(가장 최근 것). 기존 프로젝트의 선택은 바뀌지 않는다.
- 다른 형식이 섞이면 '충돌'이다. 사람이 고르기 전에는 **바꾸지 않는다**: 먼저 있던 형식(그 형식 그래프 중 가장 오래된 것이 더 이른 쪽)을 쓴다.
- 사람이 고른 형식은 `data/drawing-sources/<프로젝트>.json`에 둔다. 고른 형식의 그래프가 없으면(지웠으면) 선택은 무시되고 위 기본을 쓴다.
- PDF·DEXPI 쪽 추출 결과와 사람 수정 기록은 지우지도 옮기지도 않는다(폴더가 따로이므로 섞이지 않는다). 선택을 되돌리면 그대로 다시 쓰인다.
엔진 API: conflicts(충돌 사실), choose(선택 받기), pick(그래프 고르기), registration_conflicts(등록에서 알릴 충돌). Qt 의존 없음.
"""

import json
import os

from hazop import paths, store_io

KIND = "hazop_drawing_sources"
SCHEMA_VERSION = "0.1"
FORMATS = ("drawio", "pdf_vector", "dexpi")  # 추출 결과 source.format 값. 모르는 값도 그대로 다룬다(형식 이름으로만 쓴다)
_FORMAT_CACHE = {}


def choices_path(project_id, root=None):
    base = root or paths.folder("drawing-sources")
    return os.path.join(base, paths.safe_name(project_id) + ".json")


def load_choices(project_id, root=None):
    """{도면 번호: {"format", "by", "at"}}. 파일이 없거나 깨졌으면 {}(깨진 선택은 기본 규칙으로 되돌아간다)."""
    try:
        with open(choices_path(project_id, root), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    chosen = doc.get("chosen") if isinstance(doc, dict) else None
    return {k: v for k, v in (chosen or {}).items() if isinstance(v, dict) and v.get("format")}


def extract_root_for(graph_root=None):
    """그래프 폴더 옆 추출 결과 폴더. 기본은 작업 루트의 output/extract."""
    if graph_root:
        return os.path.join(os.path.dirname(os.path.abspath(graph_root)), "extract")
    return paths.output_root("extract")


def source_format(name, extract_root):
    """그 그래프 폴더의 추출 결과가 어느 형식인가(extraction.json의 source.format). 없거나 읽을 수 없으면 None."""
    path = os.path.join(extract_root, name, "extraction.json")
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _FORMAT_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            fmt = ((json.load(fh).get("source") or {}).get("format"))
    except (OSError, ValueError):
        return None
    _FORMAT_CACHE[path] = (key, fmt)
    return fmt


def drawing_number_of(graph):
    return (graph.get("source") or {}).get("drawing_number") or graph.get("graph_id")


def _group(cands, extract_root):
    """graph_id별 후보 묶음. 후보가 하나뿐인 묶음은 형식을 읽지 않는다(큰 추출 결과를 읽지 않으려고)."""
    by_gid = {}
    for c in cands:
        by_gid.setdefault(c["gid"], []).append(c)
    for group in by_gid.values():
        if len(group) > 1:
            for c in group:
                c["format"] = source_format(c["name"], extract_root)
    return by_gid


def _formats(group):
    return {c.get("format") for c in group if c.get("format")}


def _latest(group):
    return max(group, key=lambda c: c["key"])


def _decide(group, choice):
    """묶음에서 쓸 후보 -> (후보, 충돌인가, 사람이 고른 것을 따랐는가)."""
    formats = _formats(group)
    if len(formats) < 2:
        return _latest(group), False, False
    if choice and choice.get("format") in formats:
        return _latest([c for c in group if c.get("format") == choice["format"]]), True, True
    first = min(formats, key=lambda f: min(c["key"] for c in group if c.get("format") == f))  # 먼저 있던 형식을 바꾸지 않는다
    return _latest([c for c in group if c.get("format") == first]), True, False


def pick(project_id, cands, graph_root=None, choices_root=None):
    """cands: [{"gid", "key"(바뀐 시각, 경로), "graph", "name"}] -> ({gid: 고른 후보}, notes).
    같은 graph_id의 후보가 모두 같은 형식이면 가장 최근 것(지금 규칙). 형식이 섞이면 사람이 고른 형식, 없으면 먼저 있던 형식."""
    extract_root = extract_root_for(graph_root)
    choices = load_choices(project_id, choices_root)
    best, notes = {}, []
    for gid, group in _group(cands, extract_root).items():
        chosen, conflict, followed = _decide(group, choices.get(drawing_number_of(group[0]["graph"])))
        best[gid] = chosen
        if conflict and not followed:
            notes.append("같은 도면 번호 %s가 %s 형식으로 함께 있음 — 사람이 고르기 전에는 %s 형식(먼저 있던 것)을 씀"
                         % (drawing_number_of(chosen["graph"]), "·".join(sorted(_formats(group))), chosen.get("format")))
    return best, sorted(set(notes))


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


def conflicts(project_id, graph_root=None, choices_root=None):
    """충돌 사실(파일을 쓰지 않음). [{"drawing_number", "graph_id", "formats", "candidates": [{"name", "format", "modified"}],
    "in_use": 지금 프로젝트 그래프에 쓰는 폴더 이름, "in_use_format", "chosen": 사람이 고른 형식 또는 None}]. 충돌이 없으면 []."""
    extract_root = extract_root_for(graph_root)
    choices = load_choices(project_id, choices_root)
    out = []
    for gid, group in sorted(_group(_candidates(project_id, graph_root), extract_root).items(), key=lambda kv: str(kv[0])):
        if len(_formats(group)) < 2:
            continue
        dwg = drawing_number_of(group[0]["graph"])
        chosen, _, followed = _decide(group, choices.get(dwg))
        out.append({"drawing_number": dwg, "graph_id": gid, "formats": sorted(_formats(group)),
                    "candidates": [{"name": c["name"], "format": c.get("format"), "modified": c["key"][0]}
                                   for c in sorted(group, key=lambda c: c["name"])],
                    "in_use": chosen["name"], "in_use_format": chosen.get("format"),
                    "chosen": choices.get(dwg, {}).get("format") if followed else None})
    return out


def choose(project_id, drawing_number, source_format_name, by, at=None, graph_root=None, choices_root=None):
    """사람이 고른 원본 형식을 받아 저장한다(원자적, 읽은 뒤 바뀌었으면 store_io.Conflict). 그 도면 번호에 충돌이 없거나 그 형식의
    그래프가 없으면 ValueError. 반환: 저장한 선택 {"format", "by", "at"}. 사람 수정 기록·추출 결과는 건드리지 않는다."""
    if not by:
        raise ValueError("고른 사람 이름이 없음")
    found = [c for c in conflicts(project_id, graph_root, choices_root) if c["drawing_number"] == drawing_number]
    if not found:
        raise ValueError("도면 번호 %s에 형식이 다른 원본의 충돌이 없음" % drawing_number)
    if source_format_name not in found[0]["formats"]:
        raise ValueError("도면 번호 %s에 %s 형식의 그래프가 없음(있는 형식: %s)" % (drawing_number, source_format_name, ", ".join(found[0]["formats"])))
    path = choices_path(project_id, choices_root)
    data, fp = store_io.read_bytes(path)
    try:
        doc = json.loads(data.decode("utf-8")) if data else {}
    except ValueError:
        doc = {}
    if not isinstance(doc, dict) or not isinstance(doc.get("chosen"), dict):
        doc = {"chosen": {}}
    record = {"format": source_format_name, "by": by, "at": at or store_io.now_utc()}
    doc.update(schema_version=SCHEMA_VERSION, kind=KIND, project_id=project_id)
    doc["chosen"][drawing_number] = record
    store_io.write_json(path, doc, expect=fp)
    return record


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
