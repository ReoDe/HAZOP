"""엔티티 연결: 문서 조각 원문 -> mentions 후보(link_candidates.csv) -> 사람 판단 -> knowledge_links.csv 반영.

근거: 기획서/그래프활용.md §3.1(후보 생성 단계), §3.2(확인 흐름·후보 키·재확인), §2.5(target_ref), §2.6(열 규격),
§8.2 D6(정확 일치 일괄 확인: 검토자·사유 기록 조건), T1 decisions D6(위치는 normalize_text 기준, 처리기 이름·점수는
후보 CSV에만 보존).
- 후보는 모두 link_status=candidate로 시작한다. 자동으로 확인하지 않는다.
- 단계: 정규식으로 태그 모양 문자열을 찾고 -> normalize_tag가 같은 P&ID 태그(exact_norm, 1.0) -> 없으면
  difflib 유사 점수 >= FUZZY_THRESHOLD(fuzzy) -> 그래도 없으면 '도면에 없는 언급'(후보를 만들지 않음).
- 같은 언급에 대상이 여러 개(동명 태그·여러 도면)면 대상마다 후보를 만들고 ambiguous=true. 자동으로 고르지 않는다.
- 후보 키 필드 값에 '|'가 있으면 키를 '|'로 이어 쓸 수 없으므로 후보를 만들지 않고 검토 항목으로 남긴다.
- 위치(match_start·match_end)는 normalize_text(조각 원문)의 코드 포인트 오프셋(text_sha256과 같은 정규화).
- 같은 입력이면 같은 결과(조각은 입력 순서, 언급은 위치 순서, 대상은 (graph_id, source_object_id) 순서).
- CSV는 UTF-8(BOM)·LF로 쓰고, 임시 파일에 쓴 뒤 os.replace로 교체한다.
"""

import csv
import datetime
import difflib
import hashlib
import io
import os
import re

from hazop.kg.inputs import (CANDIDATE_KEY_FIELDS, LINK_COLUMNS, NODE_COLUMNS, normalize_tag, normalize_text,
                             read_csv, text_sha256)

LINKER = "hazop.kg.link"
LINKER_VERSION = "0.1.0"
EXTRACTOR = "%s %s" % (LINKER, LINKER_VERSION)
FUZZY_THRESHOLD = 0.85  # §3.1 초기값 [추론]. 샘플(RC-PZ1 -> RC-PZ01 = 0.923)로 확인
_H = "[-‐-―]"  # 하이픈과 변형(‐ ‑ ‒ – — ―)
# 태그 모양: 계통 약어-종류 약어+번호[-접미] (§3.1 [추론]). 앞뒤가 영숫자이면 태그 일부가 아님(한글 조사는 허용).
TAG_RE = re.compile(r"(?<![0-9A-Za-z])[A-Za-z]{1,4}%s[A-Za-z]{1,5}\d{1,5}[A-Za-z]?(?:%s[A-Za-z]{0,3}\d{1,5})?(?![0-9A-Za-z])"
                    % (_H, _H))

JUDGE_COLUMNS = ("link_status", "reviewed_by", "reviewed_at", "reason")
CANDIDATE_COLUMNS = ("candidate_key", "chunk_id", "text_sha256", "material_id", "registration_version",
                     "match_text", "match_start", "match_end", "target_graph_id", "target_graph_version",
                     "target_tag", "target_ref", "target_source_object_id", "target_entity_id",
                     "method", "extractor", "confidence", "ambiguous") + JUDGE_COLUMNS + ("previous_status",)
LINK_STATUS = ("candidate", "confirmed", "rejected")
CANDIDATES_CSV = "link_candidates.csv"
NODES_CSV = "knowledge_nodes.csv"
LINKS_CSV = "knowledge_links.csv"
HEADER_COMMENT = ("# 엔티티 연결 후보(자동 생성: %s). 근거: 기획서/그래프활용.md §3.\n"
                  "# 판단 열(link_status: candidate/confirmed/rejected, reviewed_by, reviewed_at, reason)만 고친다. "
                  "다른 열은 재생성 때 다시 계산된다.\n" % EXTRACTOR)


class LinkError(ValueError):
    """후보 CSV 판단 열 오류·반영 충돌 등 사람이 고쳐야 하는 입력 오류."""


def candidate_key(row):
    return "|".join("" if row.get(f) is None else str(row[f]) for f in CANDIDATE_KEY_FIELDS)


def relation_id(key):
    """확인 반영 관계 ID = krel-m- + sha256(후보 키) 앞 8자리(§3.2, W3 샘플과 같은 규칙)."""
    return "krel-m-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------- 후보 생성
def _targets(graphs):
    """[(graph, 노드)] 목록과 그래프별 태그 수. 구조 검증을 통과하지 못한 그래프는 받지 않는다."""
    out, counts = [], {}
    for g in sorted(graphs, key=lambda g: g["graph_id"]):
        if g["validation"]["status"] != "passed":
            raise LinkError("P&ID 그래프가 구조 검증을 통과하지 못함: %s" % g["graph_id"])
        for n in g["nodes"]:
            if n.get("tag"):
                out.append((g, n))
                counts[(g["graph_id"], n["tag"])] = counts.get((g["graph_id"], n["tag"]), 0) + 1
    out.sort(key=lambda t: (t[0]["graph_id"], t[1]["source_object_id"]))
    return out, counts


def target_ref(graph_id, node, counts):
    """§2.5: 그래프 안에서 태그가 하나면 graph_id:tag, 둘 이상이면 graph_id#source_object_id."""
    if counts[(graph_id, node["tag"])] == 1:
        return "%s:%s" % (graph_id, node["tag"])
    return "%s#%s" % (graph_id, node["source_object_id"])


def generate(nodes, graphs):
    """지식 노드 행(knowledge_nodes.csv 읽은 dict) + P&ID 그래프 -> 결과 dict.
    candidates: 후보 행(link_status=candidate), unmatched: 도면에 없는 언급, review_items: '|' 등으로 만들지 못한 후보."""
    targets, counts = _targets(graphs)
    by_norm = {}
    for g, n in targets:
        by_norm.setdefault(normalize_tag(n["tag"]), []).append((g, n))
    candidates, unmatched, review_items, seen = [], [], [], set()
    for node in nodes:
        if node.get("node_type") != "doc_chunk" or not node.get("text"):
            continue
        text = normalize_text(node["text"])
        for mt in TAG_RE.finditer(text):
            norm = normalize_tag(mt.group(0))
            hits = [(g, n, "exact_norm", 1.0) for g, n in by_norm.get(norm, [])]
            if not hits:
                for g, n in targets:
                    score = difflib.SequenceMatcher(None, norm, normalize_tag(n["tag"])).ratio()
                    if score >= FUZZY_THRESHOLD:
                        hits.append((g, n, "fuzzy", score))
            base = {"chunk_id": node.get("id"), "match_text": mt.group(0),
                    "match_start": mt.start(), "match_end": mt.end()}
            if not hits:
                unmatched.append(dict(base, reason="도면에 없는 언급(연결을 만들지 않음, 자료 요청·도면 확인 대상)"))
                continue
            for g, n, method, score in hits:
                row = dict(base, text_sha256=text_sha256(node["text"]), material_id=node.get("material_id"),
                           registration_version=node.get("registration_version"),
                           target_graph_id=g["graph_id"], target_graph_version=g["graph_version"],
                           target_tag=n["tag"], target_ref=target_ref(g["graph_id"], n, counts),
                           target_source_object_id=n["source_object_id"], target_entity_id=n["entity_id"],
                           method=method, extractor=EXTRACTOR, confidence="%.3f" % score,
                           ambiguous="true" if len(hits) > 1 else "false",
                           link_status="candidate", reviewed_by=None, reviewed_at=None, reason=None,
                           previous_status=None)
                bad = [f for f in CANDIDATE_KEY_FIELDS if "|" in str(row.get(f) or "")]
                if bad:
                    review_items.append(dict(base, check="pipe_in_key_field", target_ref=row["target_ref"],
                                             reason="후보 키 필드에 '|'가 있어 후보를 만들지 않음: %s" % ", ".join(bad)))
                    continue
                row["candidate_key"] = candidate_key(row)
                if row["candidate_key"] in seen:
                    continue
                seen.add(row["candidate_key"])
                candidates.append({c: (None if row.get(c) is None else str(row[c])) for c in CANDIDATE_COLUMNS})
    return {"candidates": candidates, "unmatched": unmatched, "review_items": review_items}


def _lineage(rows):
    """재확인용 계보: (chunk_id, 대상 graph_id, 대상 source_object_id, 정규화 일치 문자열, 같은 조각 안 순번).
    원문·자료 버전·도면 버전이 바뀌어 키가 달라져도 같은 언급을 이어 보기 위한 값이다 [가정].
    순번은 같은 입력 버전(원문 해시·자료 ID·등록 버전·도면 버전) 안에서만 센다. 버전이 다른 이력 행이 섞여도
    같은 언급은 같은 순번을 받는다(위치가 같은 행끼리 순번이 갈리지 않게)."""
    groups = {}
    for i, r in enumerate(rows):
        g = (r["chunk_id"], r["target_graph_id"], r["target_source_object_id"], normalize_tag(r["match_text"] or ""),
             r["text_sha256"], r["material_id"], r["registration_version"], r["target_graph_version"])
        groups.setdefault(g, []).append(i)
    out = {}
    for g, idx in groups.items():
        for k, i in enumerate(sorted(idx, key=lambda i: int(rows[i]["match_start"]))):
            out[i] = g[:4] + (k,)
    return out


def check_judgements(rows):
    """판단 열 검사. 잘못되면 LinkError."""
    for r in rows:
        if r["link_status"] not in LINK_STATUS:
            raise LinkError("%s: link_status 값 오류 %r (candidate/confirmed/rejected)" % (r["candidate_key"], r["link_status"]))
        if r["link_status"] != "candidate" and not r["reviewed_by"]:
            raise LinkError("%s: %s인데 reviewed_by 없음" % (r["candidate_key"], r["link_status"]))
    keys = [r["candidate_key"] for r in rows]
    if len(keys) != len(set(keys)):
        raise LinkError("후보 CSV에 같은 candidate_key가 여러 번 있음")


def merge(new_rows, old_rows):
    """재실행 병합(§3.2, L2·L4).
    - 키가 같은 기존 행: 판단 열(link_status·reviewed_by·reviewed_at·reason)과 previous_status를 그대로 둔다.
    - 새 키: candidate로 올리고, 같은 계보의 이전 판단(confirmed/rejected, 없으면 이전 previous_status)을 previous_status에.
    - 이번에 다시 나오지 않은 기존 행: 사람이 판단한 행은 이력으로 뒤에 보존, 판단 전(candidate) 행은 버린다."""
    check_judgements(old_rows)
    old_by_key = {r["candidate_key"]: r for r in old_rows}
    old_lin = _lineage(old_rows)
    prev = {}
    # 이 함수는 현재 후보를 앞에, 이력을 뒤에(이전 이력 순서 유지) 쓰므로 파일에서 앞선 행이 더 최근 판단이다.
    # 뒤에서부터 채워 앞선 행이 덮게 한다 [가정: 사람이 행 순서를 바꾸지 않음].
    for i in reversed(range(len(old_rows))):
        r = old_rows[i]
        st = r["link_status"] if r["link_status"] != "candidate" else r["previous_status"]
        if st:
            prev[old_lin[i]] = st
    new_lin = _lineage(new_rows)
    out = []
    for i, r in enumerate(new_rows):
        r = dict(r)
        old = old_by_key.get(r["candidate_key"])
        if old:
            for c in JUDGE_COLUMNS + ("previous_status",):
                r[c] = old[c]
        else:
            r["previous_status"] = prev.get(new_lin[i])
        out.append(r)
    keys = {r["candidate_key"] for r in new_rows}
    out += [dict(r) for r in old_rows if r["candidate_key"] not in keys and r["link_status"] != "candidate"]
    return out


# ---------------------------------------------------------------- 일괄 확인(D6)
def history_status(rows):
    """행마다 같은 파일의 이력에서 다시 계산한 이전 판단(CSV previous_status 열은 쓰지 않음).
    계보가 같고 키가 다른 행 중 confirmed·rejected 판단이 있는 행에서, 파일에서 가장 앞선 행(= 가장 최근, merge의
    쓰기 순서)의 link_status. 없으면 None."""
    lin = _lineage(rows)
    out = []
    for i, r in enumerate(rows):
        out.append(next((rows[j]["link_status"] for j in range(len(rows))
                         if j != i and lin[j] == lin[i] and rows[j]["candidate_key"] != r["candidate_key"]
                         and rows[j]["link_status"] in ("confirmed", "rejected")), None))
    return out


def _exact_literal(cur):
    """다시 계산한 후보 행이 일괄 확인 조건(exact_norm, 비모호, 원문 문자열 = 태그 글자 그대로)을 만족하는지."""
    return cur["method"] == "exact_norm" and cur["ambiguous"] == "false" and cur["match_text"] == cur["target_tag"]


def confirm_exact(rows, current_rows, reviewer, reason, reviewed_at):
    """정확 일치 후보 일괄 확인(§8.2 D6). 검토자·사유 필수.
    조건은 CSV 열이 아니라 현재 원문·그래프로 다시 계산한 후보(current_rows)로 판단한다: 키가 현재 후보에 있고
    다시 계산한 method=exact_norm·ambiguous=false·일치 문자열이 태그와 글자 그대로 같을 것
    [가정: 대소문자·하이픈 변형 일치는 한 건씩]. link_status=candidate이고, previous_status 열이 비었으며
    같은 파일 이력에서 다시 계산한 이전 판단(history_status)도 없는 행만 대상(재확인 후보는 한 건씩). 유사·모호 후보는 건드리지 않는다. 확인한 행 수를 돌려준다."""
    if not (reviewer or "").strip() or not (reason or "").strip():
        raise LinkError("일괄 확인에는 검토자(reviewed_by)와 사유(reason)가 모두 필요함")
    current = {r["candidate_key"]: r for r in current_rows}
    hist = history_status(rows)
    n = 0
    for i, r in enumerate(rows):
        cur = current.get(r["candidate_key"])
        if r["link_status"] == "candidate" and not r["previous_status"] and not hist[i] and cur and _exact_literal(cur):
            r.update(link_status="confirmed", reviewed_by=reviewer.strip(), reviewed_at=reviewed_at,
                     reason=reason.strip())
            n += 1
    return n


# ---------------------------------------------------------------- 확인 반영
def mention_row(cand, link_status="confirmed", knowledge_status="confirmed"):
    """후보 행 -> knowledge_links.csv mentions 행(LINK_COLUMNS). 처리기 이름·점수는 넣지 않는다(T1 D6 ⑦)."""
    row = {c: None for c in LINK_COLUMNS}
    row.update({"id": relation_id(cand["candidate_key"]), "kind": "mentions", "from": cand["chunk_id"],
                "to": cand["target_ref"], "method": cand["method"], "knowledge_status": knowledge_status,
                "link_status": link_status, "material_id": cand["material_id"],
                "registration_version": cand["registration_version"], "author": LINKER,
                "reviewed_by": cand["reviewed_by"], "reviewed_at": cand["reviewed_at"], "reason": cand["reason"],
                "candidate_key": cand["candidate_key"], "chunk_id": cand["chunk_id"],
                "text_sha256": cand["text_sha256"], "graph_version": cand["target_graph_version"],
                "target_source_object_id": cand["target_source_object_id"]})
    return row


# 후보 CSV에서 사람이 고치면 안 되는 열(판단 근거). 반영 직전에 다시 계산한 값과 다르면 반영을 거부한다.
# extractor·confidence·target_entity_id는 처리기·그래프 빌드 참고값이라 비교하지 않는다.
CHECKED_COLUMNS = ("chunk_id", "text_sha256", "material_id", "registration_version", "match_text", "match_start",
                   "match_end", "target_graph_id", "target_graph_version", "target_tag", "target_ref",
                   "target_source_object_id", "method", "ambiguous")


def apply_confirmed(cand_rows, current_rows, link_rows):
    """confirmed 후보만 mentions 행으로 만든다. 반영 직전에 현재 원문·그래프로 다시 계산한 후보(current_rows)와
    대조해, 확인 행의 판단 근거 열(CHECKED_COLUMNS)이 다르면(예: fuzzy 후보의 method를 exact_norm으로 고침)
    LinkError로 반영 전체를 거부한다. 반영 행은 판단 열만 후보 CSV에서, 나머지는 다시 계산한 값에서 가져온다.
    결과 dict: add(추가할 행), skipped_existing, stale(키가 현재와 달라 반영하지 않은 확인 후보 = 재확인 필요.
    같은 언급의 현재 후보가 이미 다시 확인된 옛 이력은 빼고 셈), rejected_but_linked(기각했는데 이미
    knowledge_links에 있는 관계: 지우지 않고 보고)."""
    check_judgements(cand_rows)
    current = {r["candidate_key"]: r for r in current_rows}
    hist = history_status(cand_rows)
    for i, c in enumerate(cand_rows):
        cur = current.get(c["candidate_key"])
        if c["link_status"] == "confirmed" and cur:
            diff = [f for f in CHECKED_COLUMNS if (c[f] or None) != (cur[f] or None)]
            if hist[i] and c["previous_status"] != hist[i]:
                diff.append("previous_status(이력 판단 %s)" % hist[i])
            if diff:
                raise LinkError("%s: 확인 행의 열이 현재 원문·그래프·이력으로 다시 계산한 값과 다름(%s) - 반영 중단. "
                                "후보를 다시 생성하고 판단할 것" % (c["candidate_key"], ", ".join(diff)))
    lin = _lineage(cand_rows)
    reconfirmed = {lin[i] for i, c in enumerate(cand_rows)
                   if c["link_status"] == "confirmed" and c["candidate_key"] in current}
    by_id = {r["id"]: r for r in link_rows if r.get("id")}
    mention_rows = [r for r in link_rows if r.get("kind") == "mentions" and r.get("candidate_key")]
    linked_keys = {r["candidate_key"] for r in mention_rows}
    # 이미 knowledge_links에서 rejected로 고친 행은 조치 대상이 아님
    active_keys = {r["candidate_key"] for r in mention_rows if r.get("link_status") != "rejected"}
    res = {"add": [], "skipped_existing": [], "stale": [], "rejected_but_linked": []}
    for i, c in enumerate(cand_rows):
        key = c["candidate_key"]
        if c["link_status"] == "rejected" and key in active_keys:
            res["rejected_but_linked"].append(key)
        if c["link_status"] != "confirmed":
            continue
        if key not in current:
            if lin[i] not in reconfirmed:
                res["stale"].append(key)
            continue
        rid = relation_id(key)
        if key in linked_keys:
            res["skipped_existing"].append(rid)
            continue
        if rid in by_id:
            raise LinkError("관계 ID %s가 이미 다른 행에 쓰임(후보 키 다름) - 반영 중단" % rid)
        row = mention_row(dict(current[key], **{k: c[k] for k in JUDGE_COLUMNS}))
        res["add"].append(row)
        by_id[rid] = row
        linked_keys.add(key)
    return res


# ---------------------------------------------------------------- 파일 입출력
def _csv_text(columns, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in rows:
        w.writerow(["" if r.get(c) is None else r[c] for c in columns])
    return buf.getvalue()


def write_atomic(path, text, bom=True):
    """UTF-8(기본 BOM)로 임시 파일에 쓴 뒤 os.replace로 교체."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def read_candidates(path):
    return read_csv(path, CANDIDATE_COLUMNS) if os.path.isfile(path) else []


def _head_comment(path):
    """파일 머리글 앞의 '#' 주석 줄(줄끝 LF). 파일이 없거나 주석이 없으면 빈 문자열."""
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        lines = fh.read().splitlines()
    out = []
    for ln in lines:
        if ln.lstrip().startswith("#"):
            out.append(ln + "\n")
        elif ln.strip():
            break
    return "".join(out)


def write_candidates(path, rows):
    """후보 CSV를 쓴다. 기존 파일의 머리 주석(가상 자료 고지 등)은 그대로 두고, 없으면 기본 안내를 쓴다."""
    head = _head_comment(path) or HEADER_COMMENT
    write_atomic(path, head + ",".join(CANDIDATE_COLUMNS) + "\n" + _csv_text(CANDIDATE_COLUMNS, rows))


def append_links(path, rows):
    """knowledge_links.csv 끝에 행을 덧붙인다. 열은 기존 파일 머리글 순서를 이름으로 따르고, 기존 바이트(주석·BOM·
    줄바꿈 CRLF/LF·행 순서)는 그대로 둔다. 추가할 행이 없으면 쓰지 않는다."""
    if not rows:
        return
    with open(path, "rb") as fh:
        raw = fh.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    nl = "\r\n" if "\r\n" in text else "\n"
    header = next((ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")), "")
    columns = [h.strip() for h in next(csv.reader([header]))] if header else []
    if sorted(columns) != sorted(LINK_COLUMNS):
        raise LinkError("%s: 머리글이 knowledge_links 열 규격과 다름 - 덧붙이지 않음" % path)
    if text and not text.endswith(("\n", "\r")):
        text += nl
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=nl)
    for r in rows:
        w.writerow(["" if r.get(c) is None else r[c] for c in columns])
    write_atomic(path, text + buf.getvalue(), bom=bom)


def run_generate(input_dir, graphs):
    """후보 생성·병합 후 link_candidates.csv를 쓴다. 결과 dict(generate 결과 + rows)."""
    res = generate(read_csv(os.path.join(input_dir, NODES_CSV), NODE_COLUMNS), graphs)
    path = os.path.join(input_dir, CANDIDATES_CSV)
    res["rows"] = merge(res["candidates"], read_candidates(path))
    write_candidates(path, res["rows"])
    return res


def run_confirm_exact(input_dir, graphs, reviewer, reason, reviewed_at=None):
    """일괄 확인. 조건 판단은 노드 CSV·그래프로 다시 계산한 후보로 한다."""
    path = os.path.join(input_dir, CANDIDATES_CSV)
    rows = read_candidates(path)
    check_judgements(rows)
    current = generate(read_csv(os.path.join(input_dir, NODES_CSV), NODE_COLUMNS), graphs)["candidates"]
    n = confirm_exact(rows, current, reviewer, reason, reviewed_at or datetime.date.today().isoformat())
    if n:
        write_candidates(path, rows)
    return n


def run_apply(input_dir, graphs):
    """후보 CSV의 confirmed 행을 knowledge_links.csv에 반영. 현재 키는 노드 CSV·그래프로 다시 계산해 대조한다."""
    current = generate(read_csv(os.path.join(input_dir, NODES_CSV), NODE_COLUMNS), graphs)["candidates"]
    links_path = os.path.join(input_dir, LINKS_CSV)
    res = apply_confirmed(read_candidates(os.path.join(input_dir, CANDIDATES_CSV)), current,
                          read_csv(links_path, LINK_COLUMNS))
    append_links(links_path, res["add"])
    return res
