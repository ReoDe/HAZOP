"""잠재 후보(기대 패턴) 규칙 엔진과 사람 판단 상태.

근거: 기획서/지식그래프-스키마.md KD6·§3·§4, 지식그래프-스키마-입력.md §2(규칙 E01~E08, 상태 모델), 지식그래프-스키마-사전.md
§1.3(ID)·§2.4(기대 층)·§3.4(expects·satisfied_by).
- 규칙은 표(schema/expectations.json)다. 코드에는 판정 함수 종류(이웃 탐색·속성 존재·관계 존재·값 비교)만 둔다.
- 입력은 프로젝트 그래프(hazop.graph.project, 도면 한 장 그래프도 됨)와 지식그래프(선택). 결과는 잠재 후보 목록이며 도면 그래프·
  지식그래프 원본에 넣지 않는다(KD1, graph_version·kg_version 불변). 잠재 후보는 사실이 아니므로 계산 뷰(V4·V5)와 근거 경로
  (kg_paths)에 넣지 않는다.
- 이웃 탐색의 홉은 배관 구간 노드를 세지 않는다(기기에서 기기까지 1홉). 화면 계산과 같은 물리 무방향 연결을 쓰고 방향은 표시만 한다.
- 사람 판단은 data/latent-candidates/<project_id>.json에 안정 키(규칙 ID|graph_id#source_object_id)로 둔다. 다시 계산하면 키로 맞추고,
  규칙 판이나 대상·후보·관계 대상 내용(digest)이 바뀌면 확인됨·부재 확정·무관과 후보 기각을 재확인 필요(previous_state)로
  돌린다(U10과 같은 보수적 방식, 입력 §2.1). 허용 전이는 TRANSITIONS 표 하나이며 그 밖의 전이는 거부한다.
- 판단 기록은 적용 전에 하나씩 검사한다. 어긋난 기록은 적용하지 않고 bad_judgements로 알리며 파일에서 지우지 않는다.
- 같은 입력이면 같은 결과(정렬 고정, 시각 기록 없음).
"""

import collections
import copy
import hashlib
import json
import os

from hazop import paths
from hazop.kg import build, claims
from hazop.kg.schema import REGISTRY

RULES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema", "expectations.json")
STORE_KIND = "hazop_expectation_judgements"
STORE_SCHEMA_VERSION = "0.1"
ID_PREFIX = "exp-"
ID_HASH_LEN = 16  # 8자는 서로 다른 대상이 같은 ID가 되는 일이 실제로 나와 늘림(사전 §1.3은 sha8)
KN_FIELDS = ("node_type", "name", "text", "item", "value", "unit", "pressure_basis", "operating_mode", "knowledge_status")

STATES = {"expected": "기대됨", "candidate_found": "후보 발견", "confirmed_present": "확인됨",
          "confirmed_absent": "부재 확정", "not_applicable": "무관"}
RECHECK_LABEL = "재확인 필요"
# 허용 전이 표(입력 §2.1). (출발, 도착, 주체, 사람 동작, 필수 입력). 주체 rule = 규칙 적용, revision = 판·내용 변경
TRANSITIONS = (
    ("expected", "candidate_found", "rule", None, ()),
    ("candidate_found", "confirmed_present", "human", "confirm", ()),
    ("candidate_found", "expected", "human", "reject", ()),
    ("expected", "confirmed_absent", "human", "absent", ("reason", "evidence")),
    ("expected", "not_applicable", "human", "not_applicable", ("reason",)),
    ("confirmed_present", "expected", "human", "undo", ()),
    ("confirmed_absent", "expected", "human", "undo", ()),
    ("not_applicable", "expected", "human", "undo", ()),
    ("confirmed_present", "expected", "revision", None, ()),
    ("confirmed_absent", "expected", "revision", None, ()),
    ("not_applicable", "expected", "revision", None, ()),
)
ACTION_LABELS = {"confirm": "후보 확인", "reject": "후보 기각", "absent": "부재 확정", "not_applicable": "무관",
                 "undo": "판단 되돌리기"}
NEED_LABELS = {"reason": "사유", "evidence": "근거 문서·쪽"}
# ③ A2 '기대 공백'과 ⑤ AI 맥락 "보호수단 미확인·부재 확정 항목"에 넣는 상태
GAP_STATES = ("expected", "confirmed_absent")
CHECK_TYPES = ("neighbor", "property", "relation", "compare")
COMPARE_OPS = ("<=",)
CONTEXT_NOTE = ("규칙상 있어야 하지만 이 그래프에서 확인하지 못한 항목(기대됨)과 사람이 근거를 보고 없다고 확정한 항목(부재 확정). "
                "근거가 아니라 확인할 단서다. 보호수단이 없다는 결론이 아니라 정보 부족으로 다루고, "
                "kg_paths·sources·참조(cause_refs·consequence_refs·safeguards)에 쓰지 않는다")


class ExpectError(ValueError):
    pass


def _str(x):
    return isinstance(x, str) and bool(x)


def _sha(obj, n=12):
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:n]


# ---------------------------------------------------------------- 상태 기계
def transition(frm, action=None, to=None, actor="human"):
    """허용 전이 표의 행(출발, 도착, 주체, 동작, 필수 입력). 없으면 ExpectError."""
    for row in TRANSITIONS:
        if row[0] == frm and row[2] == actor and (action is None or row[3] == action) and (to is None or row[1] == to):
            return row
    raise ExpectError("허용되지 않는 상태 전이: %s에서 %s" % (STATES.get(frm, frm), ACTION_LABELS.get(action, action or to)))


def allowed(frm, to, actor):
    return any(r[0] == frm and r[1] == to and r[2] == actor for r in TRANSITIONS)


def human_actions(state):
    """그 상태에서 사람이 할 수 있는 동작(표 순서)."""
    return [r[3] for r in TRANSITIONS if r[0] == state and r[2] == "human"]


# ---------------------------------------------------------------- 규칙 표
def _filter_problems(f, where, need_classes, problems):
    if not isinstance(f, dict) or not set(f) <= {"classes", "property", "values", "contains_any"}:
        problems.append("%s: 조건은 classes·property·values·contains_any만 씀" % where)
        return
    if need_classes and not f.get("classes"):
        problems.append("%s: classes 필요" % where)
    for c in f.get("classes") or []:
        if c not in REGISTRY.classes:
            problems.append("%s: 레지스트리에 없는 클래스 %s" % (where, c))
    if "property" in f and f["property"] not in REGISTRY.properties:
        problems.append("%s: 레지스트리에 없는 속성 %s" % (where, f["property"]))
    for k in ("values", "contains_any"):
        if k in f and (not isinstance(f[k], list) or not all(_str(v) for v in f[k]) or "property" not in f):
            problems.append("%s: %s는 property와 함께 쓰는 문자열 목록" % (where, k))


def _relations_problems(rels, layer, where, problems):
    if not isinstance(rels, list) or not rels:
        problems.append("%s: relations 목록 필요" % where)
        return
    for r in rels:
        if (REGISTRY.relations.get(r) or {}).get("layer") != layer:
            problems.append("%s: %s 층 관계가 아님: %s" % (where, layer, r))


def _search_problems(chk, where, problems):
    _relations_problems(chk.get("relations"), "pid", where, problems)
    if not isinstance(chk.get("hops"), int) or isinstance(chk.get("hops"), bool) or chk["hops"] < 1:
        problems.append("%s: hops는 1 이상 정수" % where)
    for c in chk.get("stop_at") or []:
        if c not in REGISTRY.classes:
            problems.append("%s: stop_at 클래스 %s가 없음" % (where, c))


def validate_rules(data):
    """규칙 표 형식 문제 목록(빈 목록 = 통과)."""
    if not isinstance(data, dict):
        return ["최상위가 JSON 객체가 아님"]
    problems = []
    if set(data) != {"rules_version", "basis_levels", "rules"}:
        problems.append("최상위 키는 rules_version·basis_levels·rules")
        return problems
    if not _str(data["rules_version"]):
        problems.append("rules_version 없음")
    levels = data["basis_levels"]
    if not isinstance(levels, list) or not all(isinstance(x, dict) and set(x) == {"id", "label_ko"} and _str(x["id"])
                                               and _str(x["label_ko"]) for x in levels):
        return problems + ["basis_levels는 {id, label_ko} 목록"]
    level_ids = {x["id"] for x in levels}
    rules = data["rules"]
    if not isinstance(rules, list) or not rules or not all(isinstance(r, dict) for r in rules):
        return problems + ["rules는 객체 목록"]
    keys = {"id", "version", "label_ko", "target", "check", "hazop_ko", "basis_level", "basis_ko"}
    ids = [r.get("id") for r in rules]
    for i in sorted({i for i in ids if ids.count(i) > 1 and i is not None}):
        problems.append("규칙 id 중복: %s" % i)
    for r in rules:
        rid = r.get("id")
        where = "규칙 %s" % rid
        if set(r) != keys:
            problems.append("%s: 키는 %s" % (where, "·".join(sorted(keys))))
            continue
        if not _str(rid) or not all(_str(r[k]) for k in ("label_ko", "hazop_ko", "basis_ko")):
            problems.append("%s: id·label_ko·hazop_ko·basis_ko는 빈 문자열이 아닌 문자열" % where)
        if not isinstance(r["version"], int) or isinstance(r["version"], bool) or r["version"] < 1:
            problems.append("%s: version은 1 이상 정수" % where)
        if r["basis_level"] not in level_ids:
            problems.append("%s: 근거 수준 %r가 basis_levels에 없음" % (where, r["basis_level"]))
        t = r["target"]
        if not isinstance(t, dict) or not set(t) <= {"classes", "where"} or not t.get("classes"):
            problems.append("%s: target은 {classes, where(선택)}" % where)
        else:
            _filter_problems({"classes": t["classes"]}, where + " target", True, problems)
            if "where" in t:
                _filter_problems(t["where"], where + " target.where", False, problems)
        chk = r["check"]
        typ = chk.get("type") if isinstance(chk, dict) else None
        if typ not in CHECK_TYPES:
            problems.append("%s: check.type은 %s 중 하나" % (where, "/".join(CHECK_TYPES)))
            continue
        allowed_keys = {"neighbor": {"type", "relations", "hops", "stop_at", "need", "mark_direction"},
                        "property": {"type", "properties"}, "relation": {"type", "relations"},
                        "compare": {"type", "property", "op", "other"}}[typ]
        if not set(chk) <= allowed_keys:
            problems.append("%s: %s 판정에 모르는 키 %s" % (where, typ, ", ".join(sorted(set(chk) - allowed_keys))))
            continue
        if typ == "neighbor":
            _search_problems(chk, where, problems)
            need = chk.get("need")
            if not isinstance(need, list) or not need:
                problems.append("%s: need 목록 필요" % where)
            for f in need or []:
                _filter_problems(f, where + " need", True, problems)
            if "mark_direction" in chk and not isinstance(chk["mark_direction"], bool):
                problems.append("%s: mark_direction은 참·거짓" % where)
        elif typ == "property":
            ps = chk.get("properties")
            if not isinstance(ps, list) or not ps or any(p not in REGISTRY.properties for p in ps):
                problems.append("%s: properties는 레지스트리 속성 목록" % where)
        elif typ == "relation":
            _relations_problems(chk.get("relations"), "knowledge", where, problems)
        else:
            if chk.get("property") not in REGISTRY.properties or chk.get("op") not in COMPARE_OPS:
                problems.append("%s: compare는 레지스트리 속성 property와 op(%s) 필요" % (where, "/".join(COMPARE_OPS)))
            o = chk.get("other")
            if not isinstance(o, dict) or set(o) - {"relations", "hops", "stop_at", "classes", "properties"} \
                    or not o.get("classes") or not o.get("properties"):
                problems.append("%s: other는 {relations, hops, stop_at, classes, properties}" % where)
            else:
                _search_problems(o, where + " other", problems)
                _filter_problems({"classes": o["classes"]}, where + " other", True, problems)
                if any(p not in REGISTRY.properties for p in o["properties"]):
                    problems.append("%s: other.properties에 레지스트리에 없는 속성" % where)
    return problems


class Rules:
    def __init__(self, data):
        problems = validate_rules(data)
        if problems:
            raise ExpectError("잠재 후보 규칙 표 형식 오류: " + "; ".join(problems))
        self.data = data
        self.version = data["rules_version"]
        self.levels = {x["id"]: x["label_ko"] for x in data["basis_levels"]}
        self.rules = data["rules"]
        self.by_id = {r["id"]: r for r in self.rules}
        self.sha256 = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                                separators=(",", ":")).encode("utf-8")).hexdigest()


def load_rules(path=RULES_FILE):
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except ValueError as exc:
            raise ExpectError("잠재 후보 규칙 표 JSON 오류: %s" % exc) from None
    return Rules(data)


RULES = load_rules()


# ---------------------------------------------------------------- 그래프 색인
class _Index:
    """프로젝트 그래프(또는 도면 한 장) + 지식그래프. 둘 다 읽기만 한다."""

    def __init__(self, graph, kg=None):
        project = bool(graph.get("sheets"))
        self.nodes = {n["entity_id"]: n for n in graph["nodes"]}
        self.ref_of, self.entity_of = {}, {}
        for e, n in self.nodes.items():
            gid = n.get("sheet") if project else graph["graph_id"]
            if gid and n.get("source_object_id"):
                ref = claims.stable_ref(gid, n["source_object_id"])
                self.ref_of[e] = ref
                self.entity_of[ref] = e
        self.adj = {}
        for edge in graph.get("edges") or []:
            ends = [x for x in edge.get("nodes") or [] if x in self.nodes]
            for a in ends:
                self.adj.setdefault(edge["kind"], {}).setdefault(a, set()).update(b for b in ends if b != a)
        self.kn_nodes = {n["id"]: n for n in (kg or {}).get("nodes") or [] if n.get("id")}
        self.links_from = {}  # P&ID 대상 안정 참조 -> [(관계, 관계 dict, 끝 참조)]
        self.claims_of = {}   # 안정 참조 -> 지식 주장 목록(도면 주장은 그래프 노드에서 직접 읽음)
        for l in (kg or {}).get("links") or []:
            if l.get("link_status") == "rejected":
                continue
            ends = l.get("ends") or {}
            f, t = ends.get("from") or {}, ends.get("to") or {}
            if f.get("layer") != "pid" or not f.get("source_object_id"):
                continue
            other = t.get("ref") if t.get("layer") == "knowledge" else (
                claims.stable_ref(t["graph_id"], t["source_object_id"]) if t.get("source_object_id") else None)
            if other is not None:
                self.links_from.setdefault(claims.stable_ref(f["graph_id"], f["source_object_id"]), []).append(
                    (l.get("kind"), l, other))
        for c in (kg or {}).get("claims") or []:
            if c.get("holder"):
                self.claims_of.setdefault(c["target"], []).append(c)

    def cls(self, e):
        return claims.pid_class(self.nodes[e])

    def is_a(self, e, classes):
        c = self.cls(e)
        return any(REGISTRY.is_a(c, x) for x in classes)

    def values(self, e, prop):
        """대상의 속성 값 [{value, unit, pressure_basis, by}] — 도면 속성(attributes·ISA 태그 해석)과 지식 주장."""
        n, out = self.nodes[e], []
        v = (n.get("attributes") or {}).get(prop)
        spec = REGISTRY.properties[prop]
        if v not in (None, ""):
            value, unit, basis = claims.parse_quantity(v) if spec["type"] == "quantity" else (str(v), None, None)
            out.append({"value": value, "unit": unit, "pressure_basis": basis, "by": "도면"})
        v = (n.get("isa") or {}).get(prop)
        if v not in (None, ""):
            out.append({"value": str(v), "unit": None, "pressure_basis": None, "by": "태그 해석"})
        for c in self.claims_of.get(self.ref_of.get(e), ()):
            if c.get("value") is not None and (c.get("property") == prop
                                               or REGISTRY.property_of_item(c.get("node_type"), c.get("item")) == prop):
                out.append({"value": c["value"], "unit": c.get("unit"), "pressure_basis": c.get("pressure_basis"),
                            "by": c["holder"]})
        return out

    def matches(self, e, f):
        if f.get("classes") and not self.is_a(e, f["classes"]):
            return False
        if "property" not in f:
            return True
        vals = [str(x["value"]) for x in self.values(e, f["property"])]
        if "values" in f and not any(v in f["values"] for v in vals):
            return False
        if "contains_any" in f and not any(ch in v for v in vals for ch in f["contains_any"]):
            return False
        return bool(vals)

    def search(self, start, relations, hops, stop_at=()):
        """start에서 hops 안에 닿는 노드 {entity: 경로(start 포함)}. 배관 구간 노드는 홉으로 세지 않는다(0-1 BFS).
        stop_at 클래스 노드(start 제외)는 찾되 그 너머로는 가지 않는다."""
        best, prev = {start: 0}, {start: None}
        dq = collections.deque([start])
        while dq:
            a = dq.popleft()
            if a != start and stop_at and self.is_a(a, stop_at):
                continue
            nbrs = sorted({b for k in relations for b in self.adj.get(k, {}).get(a, ())})
            for b in nbrs:
                w = 0 if self.nodes[b].get("node_type") == "pipe_segment" else 1
                d = best[a] + w
                if d > hops or (b in best and best[b] <= d):
                    continue
                best[b], prev[b] = d, a
                (dq.appendleft if w == 0 else dq.append)(b)
        out = {}
        for e in best:
            if e == start or self.nodes[e].get("node_type") == "pipe_segment":
                continue
            path, cur = [], e
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            out[e] = (best[e], path[::-1])
        return out

    def direction(self, path):
        """경로의 흐름 방향 표시: 모든 배관 구간이 확인된 방향으로 이어지면 하류·상류, 아니면 방향 미확인."""
        signs = set()
        for i in range(1, len(path) - 1):
            seg = self.nodes[path[i]]
            if seg.get("node_type") != "pipe_segment":
                continue
            fd = seg.get("flow_direction") or {}
            a, b = path[i - 1], path[i + 1]
            signs.add("down" if (fd.get("from"), fd.get("to")) == (a, b) else
                      "up" if (fd.get("from"), fd.get("to")) == (b, a) else "unknown")
        return {frozenset({"down"}): "하류", frozenset({"up"}): "상류"}.get(frozenset(signs), "방향 미확인")

    def found_node(self, e, **extra):
        n = self.nodes[e]
        out = {"ref": self.ref_of.get(e), "entity": e, "tag": n.get("tag"), "kind": n.get("kind")}
        out.update(extra)
        return out

    def fingerprint(self, e):
        n = self.nodes[e]
        return {"kind": n.get("kind"), "tag": n.get("tag"), "attributes": n.get("attributes") or {}, "isa": n.get("isa")}

    def content(self, f):
        """찾은 후보의 판정 관련 내용: 도면 노드면 fingerprint, 지식 노드(예: 설정치)면 KN_FIELDS 값."""
        if f.get("entity") in self.nodes:
            return self.fingerprint(f["entity"])
        n = self.kn_nodes.get(f.get("ref")) or {}
        return {k: n.get(k) for k in KN_FIELDS}


# ---------------------------------------------------------------- 판정 함수
def _check_neighbor(idx, e, chk):
    reach = idx.search(e, chk["relations"], chk["hops"], chk.get("stop_at") or ())
    groups = []
    for f in chk["need"]:
        groups.append(sorted(x for x in reach if idx.ref_of.get(x) and idx.matches(x, f)))
    if not all(groups):
        missing = [" 또는 ".join(REGISTRY.label(c, c) for c in f["classes"]) for f, g in zip(chk["need"], groups) if not g]
        return [], "못 찾음: %s" % ", ".join(missing) if any(groups) else None
    found = []
    for x in sorted({x for g in groups for x in g}):
        extra = {"hops": reach[x][0]}
        if chk.get("mark_direction"):
            extra["direction"] = idx.direction(reach[x][1])
        found.append(idx.found_node(x, **extra))
    return found, None


def _check_property(idx, e, chk):
    found = []
    for p in chk["properties"]:
        for v in idx.values(e, p):
            found.append(idx.found_node(e, property=p, value=v["value"], unit=v["unit"], by=v["by"]))
    return found, None


def _check_relation(idx, e, chk):
    found = []
    for kind, l, other in idx.links_from.get(idx.ref_of[e], ()):
        if kind in chk["relations"]:
            ent = idx.entity_of.get(other)
            base = idx.found_node(ent) if ent else {"ref": other, "entity": None, "tag": None, "kind": None}
            base.update(relation=kind, link=l.get("id"), link_status=l.get("link_status"))
            found.append(base)
    return sorted(found, key=lambda f: (f["link"] or "", f["ref"])), None


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _compare_text(own, other, other_label, op):
    a, b = _num(own["value"]), _num(other["value"])
    if a is None or b is None or not own["unit"] or own["unit"] != other["unit"] \
            or not own["pressure_basis"] or not other["pressure_basis"] or own["pressure_basis"] != other["pressure_basis"]:
        return "비교 안 함(단위·압력 기준이 다르거나 미확인): %s %s / %s %s" % (
            own["value"], own["unit"] or "(단위 미확인)", other["value"], other["unit"] or "(단위 미확인)")
    ok = a <= b if op == "<=" else None
    return "설정압력 %s %s %s 설계압력 %s %s(%s)%s" % (own["value"], own["unit"], "≤" if ok else ">", other["value"],
                                                other["unit"], other_label, "" if ok else " — 사람 확인 필요")


def _check_compare(idx, e, chk):
    o = chk["other"]
    own = idx.values(e, chk["property"])
    reach = idx.search(e, o["relations"], o["hops"], o.get("stop_at") or ())
    others = []
    for x in sorted(reach):
        if idx.ref_of.get(x) and idx.is_a(x, o["classes"]):
            for p in o["properties"]:
                for v in idx.values(x, p):
                    others.append((x, p, v))
    prop_label = REGISTRY.properties[chk["property"]]["label_ko"]
    if not own or not others:
        missing = ([prop_label] if not own else []) + (["보호 대상 설계압력"] if not others else [])
        return [], "미확인: %s" % ", ".join(missing)
    found = [idx.found_node(e, property=chk["property"], value=v["value"], unit=v["unit"], by=v["by"]) for v in own]
    notes = []
    for x, p, v in others:
        found.append(idx.found_node(x, property=p, value=v["value"], unit=v["unit"], by=v["by"]))
        notes += [_compare_text(w, v, idx.nodes[x].get("tag") or x, chk["op"]) for w in own]
    return found, "; ".join(dict.fromkeys(notes))


CHECKS = {"neighbor": _check_neighbor, "property": _check_property, "relation": _check_relation,
          "compare": _check_compare}


# ---------------------------------------------------------------- 계산
def expectation_id(rule_id, target_ref):
    return "%s%s-%s" % (ID_PREFIX, rule_id, hashlib.sha256(target_ref.encode("utf-8")).hexdigest()[:ID_HASH_LEN])


def judgement_key(rule_id, target_ref):
    return "%s|%s" % (rule_id, target_ref)


def _targets(idx, rule):
    t = rule["target"]
    out = []
    for e, n in idx.nodes.items():
        if n.get("node_type") != "drawing_object" or e not in idx.ref_of:
            continue
        if idx.is_a(e, t["classes"]) and ("where" not in t or idx.matches(e, t["where"])):
            out.append(e)
    return sorted(out, key=lambda x: idx.ref_of[x])


def _item(rule, rules, idx, e, found, note, j):
    ref = idx.ref_of[e]
    n = idx.nodes[e]
    digest = "xd-" + _sha({"rule_version": rule["version"], "target": idx.fingerprint(e), "found": found,
                           "contents": [idx.content(f) for f in found]})
    valid = bool(j) and j.get("rule_version") == rule["version"] and j.get("digest") == digest
    rejected = sorted(set(j.get("rejected") or ())) if valid else []
    shown = [f for f in found if f["ref"] not in rejected]
    auto = "candidate_found" if shown else "expected"
    state, previous, recheck = auto, None, False
    if j and (j["state"] != "expected" or j.get("rejected")):
        if valid:
            state = j["state"] if j["state"] != "expected" else auto
        elif j["state"] == "expected" or allowed(j["state"], "expected", "revision"):
            previous, recheck = j["state"], True
        else:
            state = j["state"]
    return {"id": expectation_id(rule["id"], ref), "key": judgement_key(rule["id"], ref),
            "rule_id": rule["id"], "rule_version": rule["version"], "label": rule["label_ko"],
            "basis_level": rule["basis_level"], "basis_label": rules.levels[rule["basis_level"]],
            "basis": rule["basis_ko"], "hazop": rule["hazop_ko"],
            "target": ref, "target_entity": e, "target_tag": n.get("tag"), "target_kind": n.get("kind"),
            "graph_id": ref.split("#", 1)[0], "found": shown, "rejected": rejected, "note": note,
            "auto_state": auto, "state": state, "state_label": STATES[state], "previous_state": previous,
            "recheck": recheck, "digest": digest, "judgement": copy.deepcopy(j) if j else None,
            "actions": human_actions(state)}


_EVALUATED = []  # (graph, kg 열쇠, 판단 지문, 결과) 최근 몇 개


def evaluate_cached(graph, kg=None, judgements=None):
    """evaluate와 같지만, 같은 그래프 객체·같은 지식그래프 판·같은 판단이면 계산한 결과를 그대로 준다(③·⑤가 화면에
    들어올 때마다 143쪽 그래프로 다시 계산하지 않게). 돌려준 결과는 여러 화면이 함께 쓰므로 고치지 않는다."""
    kg_key = (kg or {}).get("kg_version") or (kg or {}).get("kg_id") or id(kg)
    digest = json.dumps(judgements or {}, sort_keys=True, ensure_ascii=False)
    for g, k, d, out in _EVALUATED:
        if g is graph and k == kg_key and d == digest:
            return out
    out = evaluate(graph, kg, judgements)
    _EVALUATED.append((graph, kg_key, digest, out))
    del _EVALUATED[:-4]
    return out


def evaluate(graph, kg=None, judgements=None, rules=None):
    """잠재 후보 계산. graph: 프로젝트 그래프(또는 도면 그래프), kg: 지식그래프 또는 None, judgements: load_judgements 결과.
    입력은 바꾸지 않는다."""
    rules = rules or RULES
    judgements = judgements or {}
    bad = [{"key": k, "problems": p} for k, p in sorted((k, judgement_problems(k, r)) for k, r in judgements.items()) if p]
    good = {k: r for k, r in judgements.items() if k not in {b["key"] for b in bad}}
    idx = _Index(graph, kg)
    items = []
    for rule in rules.rules:
        for e in _targets(idx, rule):
            found, note = CHECKS[rule["check"]["type"]](idx, e, rule["check"])
            items.append(_item(rule, rules, idx, e, found, note, good.get(judgement_key(rule["id"], idx.ref_of[e]))))
    dup = sorted(i for i, c in collections.Counter(i["id"] for i in items).items() if c > 1)
    if dup:
        raise ExpectError("잠재 후보 ID 중복: %s" % ", ".join(dup))
    keys = {i["key"] for i in items}
    # 대상이 그래프에서 사라졌거나 규칙이 빠진 판단: 파일에는 그대로 두고 따로 알린다(조용히 잃지 않게)
    orphans = sorted(k for k in good if k not in keys)
    return {"rules_version": rules.version, "rules_sha256": rules.sha256, "registry_version": REGISTRY.version,
            "graph_id": graph.get("graph_id"), "graph_version": graph.get("graph_version"),
            "kg_version": (kg or {}).get("kg_version"), "items": items, "orphan_judgements": orphans,
            "bad_judgements": bad, "summary": summary(items, rules)}


def summary(items, rules=None):
    """규칙별 대상·자동 후보 발견·미발견 수와 상태별 수."""
    rules = rules or RULES
    out = {}
    for r in rules.rules:
        mine = [i for i in items if i["rule_id"] == r["id"]]
        out[r["id"]] = {"label": r["label_ko"], "targets": len(mine),
                        "candidate_found": sum(1 for i in mine if i["auto_state"] == "candidate_found"),
                        "not_found": sum(1 for i in mine if i["auto_state"] == "expected"),
                        "states": dict(sorted(collections.Counter(i["state"] for i in mine).items())),
                        "recheck": sum(1 for i in mine if i["recheck"])}
    return out


def previous_label(item):
    """재확인 항목의 이전 판단 이름. 기대됨으로 남은 사람 판단은 후보 기각뿐이다."""
    p = item.get("previous_state")
    return ACTION_LABELS["reject"] if p == "expected" else STATES.get(p, "")


def gap_items(items):
    """③ A2 '기대 공백': 부재 확정 + 아직 기대됨(재확인 필요 포함)."""
    return [i for i in items if i["state"] in GAP_STATES]


def context_items(items, refs):
    """⑤ AI 맥락 항목: refs(대상 안정 참조 집합)에 걸린 기대 공백. 잠재 후보 ID는 넣지 않는다(근거 경로에 쓰지 않게)."""
    out = []
    for i in gap_items(items):
        if i["target"] not in refs:
            continue
        j = i["judgement"] if i["state"] == "confirmed_absent" else None
        out.append({"rule_id": i["rule_id"], "expected": i["label"], "target_tag": i["target_tag"],
                    "target_kind": i["target_kind"], "state": i["state_label"], "recheck": i["recheck"],
                    "basis_level": i["basis_label"], "reason": (j or {}).get("reason"),
                    "evidence": (j or {}).get("evidence")})
    return sorted(out, key=lambda x: (x["target_tag"] or "", x["rule_id"]))


# ---------------------------------------------------------------- 사람 판단
def judgement_problems(key, rec):
    """판단 기록 하나의 문제 목록(빈 목록 = 적용 가능). 상태가 마지막 동작의 도착 상태인지, 그 동작의 필수 입력과
    판단자가 있는지 전이 표로 본다."""
    if not isinstance(rec, dict):
        return ["기록이 객체가 아님"]
    out = []
    if rec.get("key") != key:
        out.append("키가 다름")
    if rec.get("state") not in STATES:
        out.append("모르는 상태 %r" % rec.get("state"))
    if not (isinstance(rec.get("by"), str) and rec["by"].strip()):
        out.append("판단자 없음")
    rows = [r for r in TRANSITIONS if r[2] == "human" and r[3] == rec.get("action") and r[1] == rec.get("state")]
    if not rows:
        out.append("상태와 마지막 동작(%s)이 맞지 않음" % rec.get("action"))
    for k in sorted({k for r in rows for k in r[4]}):
        if not (isinstance(rec.get(k), str) and rec[k].strip()):
            out.append("%s 없음" % NEED_LABELS[k])
    r = rec.get("rejected")
    if r is not None and not (isinstance(r, list) and all(isinstance(x, str) for x in r)):
        out.append("기각 목록 형식 오류")
    return out


def apply_action(item, action, by, reason="", evidence="", at=None, found_ref=None):
    """잠재 후보 하나에 사람 판단을 적용한 새 판단 기록. 허용 전이 표에 없거나 필수 입력이 없으면 ExpectError."""
    row = transition(item["state"], action=action)
    if not _str((by or "").strip()):
        raise ExpectError("판단한 사람 이름이 필요함")
    given = {"reason": (reason or "").strip(), "evidence": (evidence or "").strip()}
    missing = [NEED_LABELS[k] for k in row[4] if not given[k]]
    if missing:
        raise ExpectError("%s에는 %s이 필요함" % (ACTION_LABELS[action], "·".join(missing)))
    refs = [f["ref"] for f in item["found"]]
    if found_ref is not None and found_ref not in refs:
        raise ExpectError("후보 목록에 없는 대상: %s" % found_ref)
    rejected = sorted(set(item["rejected"]) | (set(refs) if action == "reject" else set()))
    return {"key": item["key"], "rule_id": item["rule_id"], "rule_version": item["rule_version"],
            "target": item["target"], "target_tag": item["target_tag"], "state": row[1], "action": action,
            "digest": item["digest"], "found": [found_ref] if found_ref else (refs if action == "confirm" else []),
            "rejected": rejected, "reason": given["reason"] or None, "evidence": given["evidence"] or None,
            "by": by.strip(), "at": at, "previous_state": item["state"]}


def store_path(project_id):
    return paths.folder("latent-candidates", paths.safe_name(project_id, "project") + ".json")


def _check_store(doc, project_id, path):
    if not isinstance(doc, dict) or doc.get("kind") != STORE_KIND or not isinstance(doc.get("judgements"), dict):
        raise ExpectError("%s: 잠재 후보 판단 파일 형식이 아님" % path)
    if doc.get("project_id") != project_id:
        raise ExpectError("%s: 다른 프로젝트(%s)의 판단 파일" % (path, doc.get("project_id")))


def load_judgements(path, project_id):
    """판단 파일 -> {키: 기록}. 파일이 없으면 빈 dict. 파일 형식이 틀리면 ExpectError(덮어쓰지 않게 호출자가 멈춘다).
    기록 하나하나의 검사는 evaluate가 한다(어긋난 기록도 그대로 돌려줘 저장 때 잃지 않게)."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError as exc:
        raise ExpectError("%s: 잠재 후보 판단 파일 JSON 오류: %s" % (path, exc)) from None
    _check_store(doc, project_id, path)
    return doc["judgements"]


def save_judgement(path, project_id, rec):
    """판단 하나를 파일에 더한다(같은 키는 바꾸고 이전 기록은 history에 남김). 기존 파일을 읽지 못하면 쓰지 않는다."""
    current = load_judgements(path, project_id)
    prev = current.get(rec["key"])
    new = dict(rec)
    if isinstance(prev, dict):
        new["history"] = list(prev.get("history") or []) + [{k: v for k, v in prev.items() if k != "history"}]
    elif prev is not None:
        new["history"] = [prev]
    current[rec["key"]] = new
    build.write_json_atomic(path, {"kind": STORE_KIND, "schema_version": STORE_SCHEMA_VERSION,
                                   "project_id": project_id, "judgements": dict(sorted(current.items()))})
    return current
