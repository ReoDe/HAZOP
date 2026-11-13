"""도면 한 장의 수정 기록이 바뀐 뒤(사람 고침·AI 후보 수락) 그래프를 다시 만드는 공용 길. Qt를 import하지 않는다.

- `lock(name)`: 도면별 잠금. 수정 기록을 읽기 → 판 대조 → 쓰기 → 다시 만들기는 이 잠금 안에서 한다(같은 판을 본 두 스레드가 고침 하나를 잃지 않게).
  사람 고침(api_corrections)과 AI 후보 수락·되돌리기(api_aireview)가 같은 잠금을 쓴다. 한 프로세스 안의 잠금이다(다른 프로세스는 store_io의 expect가 막는다).
- `ver_of(name)`: 화면이 본 판. 쪽 확정과 같은 세 파일(추출 결과·사람 수정 기록·AI 후보, `confirmation.file_paths`)의 지문을 묶은 값.
  `ver_from(files)`는 이미 읽은 바이트의 지문으로 같은 값을 만든다(읽은 것과 대조한 것이 같은 바이트이게).
- `rebuild(name)`: 그 도면의 그래프(scripts/build_graph.build_one이 기록을 적용)와 프로젝트 지식그래프를 다시 만든다.
  → (알림 글 목록, 재확인 안내 목록). 그래프나 지식그래프를 만들지 못하면 예외를 올린다(삼키지 않는다).
- `refresh(name)`: rebuild를 부르고, 실패하면 예외를 올리지 않고 낡은 그래프 표시를 남긴다. 저장은 이미 끝났으니 화면은 '저장됨, 그래프 갱신 실패'를 보인다.
- `ensure_graph(name)`: 낡은 그래프 표시가 있으면 다시 만들어 본다(다음에 열 때·다음 동작 때).
- `ensure_project(project_id)`: 그 프로젝트의 낡은 그래프 표시를 모두 다시 만들어 본다. 프로젝트 그래프를 짓는 한 곳(hazop.app.project_ctx.project_graph)이
  먼저 부르므로 쪽 확정·구간·내보내기가 고치기 전 graph.json으로 짓지 않는다.
"""

import contextlib
import glob
import hashlib
import json
import logging
import os
import threading

from hazop import paths, store_io

LOG = logging.getLogger("hazop.shell.sheet_refresh")
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_ENSURING = threading.local()


@contextlib.contextmanager
def lock(name):
    with _LOCKS_GUARD:
        lk = _LOCKS.setdefault(name, threading.RLock())
    with lk:
        yield


def ver_from(files):
    """{extraction, edits, ai_review: 지문 또는 None} → 판."""
    text = "|".join("%s=%s" % (k, files[k] or "-") for k in sorted(files))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def ver_of(name):
    from hazop.extract import confirmation
    files = confirmation.file_paths(name)
    return ver_from({k: store_io.fingerprint(files[k]) for k in files})


def stale_path(name):
    return paths.folder("ai-review", paths.safe_name(name) + ".graph-stale.json")


def mark_stale(name, why):
    pid = None
    try:
        from hazop.app import data
        pid = data.read_json(data.extraction_path(name)).get("project_id")
    except (OSError, ValueError):
        pass
    try:
        store_io.write_json(stale_path(name), {"why": str(why)[:200], "name": name, "project_id": pid})
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
    graph, _ = data.script_module("build_graph").build_one(data.extraction_path(name), paths.output_root("graph"))
    if graph.get("project_id"):
        try:
            data.build_project_kg(graph["project_id"])
        except (OSError, ValueError, KeyError) as exc:
            raise RuntimeError("지식그래프를 다시 만들지 못함: %s" % str(exc)[:120]) from exc
    return [], project_recheck(graph.get("project_id")) if graph.get("project_id") else []


def refresh(name):
    """→ (그래프가 낡은 채인지, 알림 글, 재확인 안내)."""
    with lock(name):
        try:
            notes, recheck = rebuild(name)
        except Exception as exc:  # noqa: BLE001 - 저장은 끝났다. 다시 만들기 실패는 표시로 남기고 다음 동작에서 다시 해 본다
            LOG.exception("그래프 다시 만들기 실패")
            mark_stale(name, exc)
            return True, ["저장했지만 그래프·지식그래프를 다시 만들지 못했습니다(%s). 다음 동작에서 다시 만듭니다." % str(exc)[:120]], []
        try:
            os.remove(stale_path(name))
        except OSError:
            pass
        return False, notes, recheck


def ensure_graph(name):
    if not graph_stale(name):
        return False, [], []
    return refresh(name)


def stale_names(project_id=None):
    """낡은 그래프 표시가 남은 도면 이름(project_id를 주면 그 프로젝트 것과 프로젝트를 모르는 것)."""
    out = []
    for p in sorted(glob.glob(paths.folder("ai-review", "*.graph-stale.json"))):
        try:
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            doc = {}
        name = doc.get("name") or _name_of_marker(p)          # 이름을 적지 않은 옛 표시(api_aireview가 남긴 것)도 읽는다
        if not name:
            continue
        if project_id is None or doc.get("project_id") in (None, project_id):
            out.append(name)
    return out


def _name_of_marker(path):
    stem = os.path.basename(path)[:-len(".graph-stale.json")]
    for d in sorted(glob.glob(os.path.join(paths.output_root("extract"), "*"))):
        if os.path.isdir(d) and paths.safe_name(os.path.basename(d)) == stem:
            return os.path.basename(d)
    return None


def ensure_project(project_id):
    """프로젝트 그래프를 짓기 전에 그 프로젝트의 낡은 그래프를 다시 만들어 본다. → 아직 낡은 도면 이름 목록."""
    if getattr(_ENSURING, "on", False):          # 다시 만들기 안에서 프로젝트 그래프를 또 지으면 되풀이하지 않는다
        return []
    _ENSURING.on = True
    try:
        left = []
        for name in stale_names(project_id):
            stale, _notes, _recheck = refresh(name)
            if stale:
                left.append(name)
        return left
    finally:
        _ENSURING.on = False
