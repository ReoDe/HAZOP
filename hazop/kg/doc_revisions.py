"""설계 문서의 판 대응: 같은 문서의 새 판이 옛 판을 대신한다(완료 목록 2 A7, 검토 2026-11-14 재현 C).

- 등록 자료 ID(material_id)는 원본 해시로 정해지므로 개정본은 다른 자료가 된다. 그대로 두면 옛 판과 새 판의 지식이 함께 지식그래프에 들어가
  같은 설정치가 둘이 된다. 그래서 프로젝트마다 '어느 자료가 어느 자료를 대신하는가'를 이 파일 하나에 적고, 지식그래프 조립(hazop.kg.auto)이
  대신된 자료의 문서 지식을 빼고 쓴다. 문서 지식 파일과 등록 기록은 지우지 않는다(되돌릴 수 있게).
- 같은 문서인지는 첫 쪽에서 읽은 문서 번호·개정(hazop.kg.docextract.identity)으로 가린다(decide). 규칙(권장안):
  * 문서 번호가 같고 새 판의 개정이 옛 판보다 낮지 않으면(같거나 높거나, 한쪽 개정을 못 읽음) 새 판이 옛 판을 대신한다(auto).
  * 문서 번호는 같은데 새 판의 개정이 더 낮으면, 또는 새 문서의 번호를 못 읽었는데 프로젝트에 다른 문서가 있으면 사람에게 묻는다(pending).
  * 그 밖은 다른 문서다.
- 사람 답: replace(새 판으로 지정) · separate(다른 문서). 대신된 자료에 걸린 사람 판단(조각 언급 확인 등)은 지우지 않는다. 조립이 '재확인 필요'로 알린다.
파일: <작업 루트>/data/knowledge-graph/<project_id>/document_revisions.json(사람 지식·언급 판단 link_candidates.csv와 같은 폴더)
{"kind", "schema_version", "project_id", "replaced": {옛 자료 ID: {"by", "how", "reason", "who", "at"}}, "pending": {새 자료 ID: [후보 자료 ID]}}
"""

import json
import os
import re
import threading

from hazop import paths

KIND = "hazop_document_revisions"
SCHEMA_VERSION = "0.1"
LOCK = threading.RLock()
FILE = "document_revisions.json"


def path(project_id):
    return paths.folder("knowledge-graph", paths.safe_name(project_id, "project"), FILE)


def load(project_id):
    """판 대응 문서. 없으면 빈 문서. 형식이 틀리면 ValueError(덮어쓰지 않게 호출자가 멈춘다)."""
    p = path(project_id)
    if not os.path.isfile(p):
        return {"kind": KIND, "schema_version": SCHEMA_VERSION, "project_id": project_id, "replaced": {}, "pending": {}}
    with open(p, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("kind") != KIND or doc.get("project_id") != project_id \
            or not isinstance(doc.get("replaced"), dict) or not isinstance(doc.get("pending"), dict):
        raise ValueError("%s: 문서 판 대응 파일 형식이 아님" % p)
    return doc


def _save(doc):
    from hazop.kg import build
    build.write_json_atomic(path(doc["project_id"]), doc)


def replaced_ids(project_id):
    """대신된(옛 판) 자료 ID 집합. 파일을 읽을 수 없으면 빈 집합(지식을 숨기지 않는 쪽)."""
    try:
        return set(load(project_id)["replaced"])
    except (OSError, ValueError):
        return set()


def _rev_key(rev):
    if rev is None:
        return None
    return (0, int(rev)) if str(rev).isdigit() else (1, str(rev))


def decide(new, others):
    """new: 새로 추출한 문서 지식, others: 같은 프로젝트의 지금 쓰는(대신되지 않은) 다른 문서 지식 목록.
    -> ("replace", [옛 문서], 까닭) | ("ask", [후보 문서], 까닭) | ("separate", None, None)."""
    others = [d for d in others if d.get("material_id") != new.get("material_id")]
    num = new.get("doc_number")
    if num:
        same = [d for d in others if (d.get("doc_number") or "").upper() == num.upper()]
        if same:
            a = _rev_key(new.get("revision"))
            higher = [d for d in same if a is not None and _rev_key(d.get("revision")) is not None and _rev_key(d.get("revision")) > a]
            if higher:
                return "ask", same, "문서 번호 %s인데 새 판의 개정(%s)이 이미 있는 판(%s)보다 낮음" % (
                    num, new.get("revision"), ", ".join(sorted({str(d.get("revision")) for d in higher})))
            revs = sorted({str(d.get("revision") or "?") for d in same})
            why = "문서 번호 %s, 개정 %s → %s" % (num, "·".join(revs), new.get("revision") or "?")
            if a is not None and any(_rev_key(d.get("revision")) == a for d in same):
                why += " (개정이 같은데 내용이 달라 나중에 등록한 판을 씀)"
            return "replace", same, why      # 같은 번호로 지금 쓰는 판 모두(동시에 등록돼 둘 이상일 수 있음)
        return "separate", None, None
    if others:
        return "ask", others, "문서 번호를 읽지 못해 같은 문서의 새 판인지 알 수 없음"
    return "separate", None, None


def record_replace(project_id, old_mid, new_mid, how, reason, who, at):
    with LOCK:
        doc = load(project_id)
        if old_mid == new_mid or doc["replaced"].get(new_mid, {}).get("by") == old_mid:
            raise ValueError("서로를 대신하게 할 수 없음")
        doc["replaced"][old_mid] = {"by": new_mid, "how": how, "reason": reason, "who": who, "at": at}
        doc["pending"].pop(new_mid, None)
        _save(doc)
        return doc


def record_pending(project_id, new_mid, candidates):
    with LOCK:
        doc = load(project_id)
        doc["pending"][new_mid] = sorted(set(candidates))
        _save(doc)
        return doc


def record_separate(project_id, new_mid):
    """사람이 '다른 문서'라고 답함: 묻던 것을 지우고, 새 자료가 대신했던 것도 되돌린다."""
    with LOCK:
        doc = load(project_id)
        doc["pending"].pop(new_mid, None)
        for old in [o for o, r in doc["replaced"].items() if r.get("by") == new_mid]:
            del doc["replaced"][old]
        _save(doc)
        return doc


def chunk_prefix(material_id):
    """그 자료의 문서 조각 ID 앞부분(docextract.extract의 'chunk-<자료 ID 끝 조각>-')."""
    key = re.sub(r"[^A-Za-z0-9]", "", (material_id or "unregistered").split("-")[-1])
    return "chunk-%s-" % key
