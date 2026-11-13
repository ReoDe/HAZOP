"""도면 한 장의 수정 기록이 바뀐 뒤(사람 고침·AI 후보 수락) 그래프를 다시 만드는 공용 길. Qt를 import하지 않는다.

- `ver_of(name)`: 화면이 본 판. 쪽 확정과 같은 세 파일(추출 결과·사람 수정 기록·AI 후보, `confirmation.file_paths`)의 지문을 묶은 값.
- `rebuild(name)`: 그 도면의 그래프(scripts/build_graph.build_one이 기록을 적용)와 프로젝트 지식그래프를 다시 만든다(hazop.app.data.save_corrections와 같은 길).
  → (알림 글 목록, 재확인 안내 목록). 재확인은 새 화면이 쓰는 프로젝트 구간 집합과 분석 결과로 판정한다.
- `refresh(name)`: rebuild를 부르고, 실패하면 예외를 올리지 않고 낡은 그래프 표시를 남긴다. 저장은 이미 끝났으니 화면은 '저장됨, 그래프 갱신 실패'를 보인다.
- `ensure_graph(name)`: 낡은 그래프 표시가 있으면 다시 만들어 본다(다음에 열 때·다음 동작 때).

AI 후보(api_aireview)와 도면 고치기(api_corrections)가 함께 쓴다. 낡은 그래프 표시 파일은 하나라서 어느 쪽이 실패해도 다음 동작에서 다시 만든다.
"""

import hashlib
import logging
import os

from hazop import paths, store_io

LOG = logging.getLogger("hazop.shell.sheet_refresh")


def ver_of(name):
    from hazop.extract import confirmation
    files = confirmation.file_paths(name)
    text = "|".join("%s=%s" % (k, store_io.fingerprint(files[k]) or "-") for k in sorted(files))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def stale_path(name):
    return paths.folder("ai-review", paths.safe_name(name) + ".graph-stale.json")


def mark_stale(name, why):
    try:
        store_io.write_json(stale_path(name), {"why": str(why)[:200]})
    except OSError:
        LOG.exception("낡은 그래프 표시를 남기지 못함")


def graph_stale(name):
    return os.path.isfile(stale_path(name))


def project_recheck(project_id):
    """새 화면의 프로젝트 구간 집합·분석 결과가 지금 프로젝트 그래프보다 낡았으면 안내 글."""
    from hazop.app import project_ctx
    from hazop.study import nodes as study_nodes
    from hazop.study import results as study_results
    out = []
    try:
        pg = project_ctx.project_graph(project_id)
        ns = study_nodes.read_as_is(pg)
    except (OSError, ValueError, KeyError):
        return out
    if not ns or (ns.get("schema_version") or study_nodes.LEGACY_SCHEMA_VERSION) == study_nodes.LEGACY_SCHEMA_VERSION or not ns.get("nodes"):
        return out
    if study_nodes.is_stale(ns, pg):
        held = [n["node_id"] for n in ns["nodes"] if study_nodes.node_state(n) != "applied"]
        out.append("④ 검토구간이 고치기 전 도면 기준입니다. 구간 패널에서 재확인하세요%s." % ("(확정·잠금 " + ", ".join(held[:8]) + ")" if held else ""))
        try:
            doc, _fp = study_results.load_fp(ns)
        except (OSError, ValueError, KeyError):
            doc = None
        if doc and doc.get("cells"):
            out.append("⑤ 분석 결과가 고치기 전 도면 기준입니다. 재확인이 필요합니다.")
    return out


def rebuild(name):
    from hazop.app import data
    notes = []
    graph, _ = data.script_module("build_graph").build_one(data.extraction_path(name), paths.output_root("graph"))
    if graph.get("project_id"):
        try:
            data.build_project_kg(graph["project_id"])
        except (OSError, ValueError, KeyError) as exc:
            notes.append("지식그래프를 다시 만들지 못했습니다(%s)." % str(exc)[:120])
    return notes, project_recheck(graph.get("project_id")) if graph.get("project_id") else []


def refresh(name):
    """→ (그래프가 낡은 채인지, 알림 글, 재확인 안내)."""
    try:
        notes, recheck = rebuild(name)
    except Exception as exc:  # noqa: BLE001 - 저장은 끝났다. 다시 만들기 실패는 표시로 남기고 다음 동작에서 다시 해 본다
        LOG.exception("그래프 다시 만들기 실패")
        mark_stale(name, exc)
        return True, ["저장했지만 그래프를 다시 만들지 못했습니다(%s). 다음 동작에서 다시 만듭니다." % type(exc).__name__], []
    try:
        os.remove(stale_path(name))
    except OSError:
        pass
    return False, notes, recheck


def ensure_graph(name):
    if not graph_stale(name):
        return False, [], []
    return refresh(name)
