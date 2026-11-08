"""노드·관계 타입 레지스트리(registry.json) 읽기 (기획서/지식그래프-스키마.md KD2·§6, 사전 §4).

레지스트리를 읽는 곳은 이 모듈 하나다. 읽을 때 형식을 검사하고(RegistryError), 다른 모듈은 아래 조회 함수만 쓴다.
"""

import hashlib
import json
import os

REGISTRY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registry.json")
SHAPES = ("circle", "square", "page", "hex", "diamond", "capsule", "tri")
LEGEND_LINES = ("solid", "dashed")
LAYER_FILTERS = ("type", "state")  # ③ 왼쪽 패널: 종류별 켜기·끄기 / 상태별 켜기·끄기(기대 층)
A2_ROLES = (None, "mention", "apply")
PID_VIEWS = ("V1", "V3")
PID_ROOT = "plant_item"
CLASS_KEYS = {"id", "parent", "layer", "label_ko", "label_en", "legend", "kind", "id_prefix", "dexpi_class",
              "properties", "required"}
PROPERTY_KEYS = {"id", "type", "values", "label_ko", "dimension", "needs_basis", "knowledge_items"}
PROPERTY_TYPES = ("enum", "quantity", "text")
RELATION_KEYS = {"id", "layer", "from", "to", "group", "v4", "a2_role", "evidence_gap", "conflict_check",
                 "pid_view", "label_ko"}
GROUP_KEYS = {"id", "label_ko", "width"}
LAYER_KEYS = {"id", "label_ko", "screen", "filter", "default_on"}
ORIGIN_KEYS = {"id", "label_ko", "layer", "legacy_methods", "confirm_needs_reviewer"}


class RegistryError(ValueError):
    pass


def _str(x):
    return isinstance(x, str) and bool(x)


def _check_items(items, name, allowed, problems):
    ids = []
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        problems.append("%s가 객체 목록이 아님" % name)
        return []
    for it in items:
        if not _str(it.get("id")):
            problems.append("%s 항목에 id 없음" % name)
            continue
        extra = sorted(set(it) - allowed)
        if extra:
            problems.append("%s %s: 모르는 키 %s" % (name, it["id"], ", ".join(extra)))
        ids.append(it["id"])
    for i in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append("%s id 중복: %s" % (name, i))
    return ids


def validate(data):
    """형식 문제 목록(빈 목록 = 통과). 사전 §4 검사 R1(상위 클래스 존재·순환 없음), R2(관계 허용 쌍이 있는 클래스),
    R4(kind 중복 없음)와 필드 자료형. R3(사용자 확장)은 확장 파일을 아직 읽지 않으므로 해당 없음."""
    if not isinstance(data, dict):
        return ["최상위가 JSON 객체가 아님"]
    problems = []
    extra = sorted(set(data) - {"registry_version", "layers", "classes", "properties", "relations", "groups", "origins"})
    if extra:
        problems.append("모르는 최상위 키 %s" % ", ".join(extra))
    if not _str(data.get("registry_version")):
        problems.append("registry_version 없음")
    layer_ids = _check_items(data.get("layers"), "layers", LAYER_KEYS, problems)
    class_ids = _check_items(data.get("classes"), "classes", CLASS_KEYS, problems)
    group_ids = _check_items(data.get("groups"), "groups", GROUP_KEYS, problems)
    _check_items(data.get("relations"), "relations", RELATION_KEYS, problems)
    _check_items(data.get("origins"), "origins", ORIGIN_KEYS, problems)
    prop_ids = set(_check_items(data.get("properties", []), "properties", PROPERTY_KEYS, problems))
    if problems:
        return problems
    layers = tuple(layer_ids)
    screens = []
    for ly in data["layers"]:
        if not _str(ly.get("label_ko")) or not _str(ly.get("screen")) or ly.get("filter") not in LAYER_FILTERS \
                or not isinstance(ly.get("default_on"), bool):
            problems.append("layers %s: label_ko·screen·filter(%s)·default_on(참·거짓) 필요"
                            % (ly["id"], "/".join(LAYER_FILTERS)))
        screens.append(ly.get("screen"))
    for x in sorted({x for x in screens if _str(x) and screens.count(x) > 1}):
        problems.append("layers: 화면 키 %s 중복" % x)
    classes = {c["id"]: c for c in data["classes"]}
    kinds = {}
    for c in data["classes"]:
        cid, parent = c["id"], c.get("parent")
        if parent is not None and not _str(parent):
            problems.append("classes %s: parent는 클래스 ID(문자열) 또는 null" % cid)
        elif parent is None:
            if c.get("layer") not in layers:
                problems.append("classes %s: 최상위 클래스의 layer가 %s 중 하나가 아님" % (cid, "/".join(layers)))
        elif parent not in classes:
            problems.append("classes %s: 상위 클래스 %s가 없음(R1)" % (cid, parent))
        elif "layer" in c and c["layer"] not in layers:
            problems.append("classes %s: layer 값 오류" % cid)
        for f in ("label_ko", "label_en"):
            if not _str(c.get(f)):
                problems.append("classes %s: %s 없음" % (cid, f))
        for f in ("kind", "id_prefix", "dexpi_class"):
            if f in c and not _str(c[f]):
                problems.append("classes %s: %s가 빈 문자열이 아닌 문자열이 아님" % (cid, f))
        if "kind" in c:
            kinds.setdefault(c["kind"], []).append(cid)
            if not _str(parent) or classes.get(parent, {}).get("parent") is None:
                problems.append("classes %s: kind 클래스의 상위는 분류(최상위 아래 클래스)여야 함" % cid)
        lg = c.get("legend")
        if "legend" in c and (not isinstance(lg, dict) or not {"shape", "token"} <= set(lg) <= {"shape", "token", "line"}
                              or lg["shape"] not in SHAPES or not _str(lg["token"]) or not lg["token"].startswith("kg-")
                              or lg.get("line", "solid") not in LEGEND_LINES):
            problems.append("classes %s: legend는 {shape(%s), token(kg-...), line(%s, 선택)}이어야 함"
                            % (cid, "/".join(SHAPES), "/".join(LEGEND_LINES)))
    for p in data.get("properties", []):
        pid = p["id"]
        if p.get("type") not in PROPERTY_TYPES or not _str(p.get("label_ko")):
            problems.append("properties %s: type(%s)·label_ko 필요" % (pid, "/".join(PROPERTY_TYPES)))
        vals = p.get("values")
        if p.get("type") == "enum" and (not isinstance(vals, list) or not vals or not all(_str(v) for v in vals)):
            problems.append("properties %s: enum은 values(문자열 목록) 필요" % pid)
        if p.get("type") != "enum" and "values" in p:
            problems.append("properties %s: values는 enum에만 씀" % pid)
        if "needs_basis" in p and not isinstance(p["needs_basis"], bool):
            problems.append("properties %s: needs_basis는 참·거짓" % pid)
        ki = p.get("knowledge_items", [])
        if not isinstance(ki, list) or not all(isinstance(x, dict) and set(x) == {"node_type", "item"}
                                               and _str(x["node_type"]) and _str(x["item"]) for x in ki):
            problems.append("properties %s: knowledge_items는 {node_type, item} 목록이어야 함" % pid)
    for c in data["classes"]:
        for f in ("properties", "required"):
            if f not in c:
                continue
            v = c[f]
            if not isinstance(v, list) or not all(_str(x) for x in v):
                problems.append("classes %s: %s는 속성 ID 목록이어야 함" % (c["id"], f))
                continue
            for x in v:
                if x not in prop_ids:
                    problems.append("classes %s: %s의 속성 %s가 없음" % (c["id"], f, x))
    for k, cids in sorted(kinds.items()):
        if len(cids) > 1:
            problems.append("kind %s가 클래스 %s에 겹침(R4)" % (k, ", ".join(cids)))
    if problems:
        return problems
    for cid in classes:
        seen, cur = [], cid
        while cur is not None and cur in classes:
            if cur in seen:
                problems.append("classes %s: 상위 클래스 순환(R1)" % cid)
                break
            seen.append(cur)
            cur = classes[cur].get("parent")
    if problems:
        return problems
    for c in data["classes"]:
        missing = [x for x in c.get("required", []) if x not in _class_properties(classes, c["id"])]
        if missing:
            problems.append("classes %s: required %s가 이 클래스·상위 클래스의 properties에 없음"
                            % (c["id"], ", ".join(missing)))
    for c in data["classes"]:
        if c.get("parent") is not None and "layer" in c and c["layer"] != _layer(classes, c["parent"]):
            problems.append("classes %s: layer가 상위 클래스와 다름" % c["id"])
    for g in data["groups"]:
        if not _str(g.get("label_ko")) or isinstance(g.get("width"), bool) or not isinstance(g.get("width"), (int, float)):
            problems.append("groups %s: label_ko·width(숫자) 필요" % g["id"])
    for r in data["relations"]:
        rid = r["id"]
        if r.get("layer") not in layers:
            problems.append("relations %s: layer 값 오류" % rid)
        for side in ("from", "to"):
            ends = r.get(side)
            if not isinstance(ends, list) or not ends or not all(_str(x) for x in ends):
                problems.append("relations %s: %s는 클래스 ID 목록이어야 함" % (rid, side))
                continue
            for x in ends:
                if x not in classes:
                    problems.append("relations %s: %s 클래스 %s가 없음(R2)" % (rid, side, x))
        if r.get("group") not in group_ids:
            problems.append("relations %s: 범례 묶음 %r가 없음" % (rid, r.get("group")))
        if not isinstance(r.get("v4"), bool):
            problems.append("relations %s: v4(참·거짓) 필요" % rid)
        if r.get("a2_role") not in A2_ROLES:
            problems.append("relations %s: a2_role 값 오류 %r" % (rid, r.get("a2_role")))
        if r.get("a2_role") == "apply" and not isinstance(r.get("evidence_gap"), bool):
            problems.append("relations %s: 설비 적용 관계는 evidence_gap(참·거짓) 필요" % rid)
        if r.get("a2_role") != "apply" and "evidence_gap" in r:
            problems.append("relations %s: evidence_gap은 설비 적용 관계에만 씀" % rid)
        if "conflict_check" in r and (not isinstance(r["conflict_check"], bool) or len(r.get("to") or []) != 1):
            problems.append("relations %s: conflict_check는 참·거짓이고 to가 클래스 하나여야 함" % rid)
        if r.get("layer") == "pid" and r.get("pid_view") not in PID_VIEWS:
            problems.append("relations %s: P&ID 관계는 pid_view(%s) 필요" % (rid, "/".join(PID_VIEWS)))
        if r.get("layer") != "pid" and "pid_view" in r:
            problems.append("relations %s: pid_view는 P&ID 관계에만 씀" % rid)
    methods = []
    for o in data["origins"]:
        if not _str(o.get("label_ko")) or o.get("layer") not in layers:
            problems.append("origins %s: label_ko·layer(%s) 필요" % (o["id"], "/".join(layers)))
        lm = o.get("legacy_methods")
        if not isinstance(lm, list) or not all(_str(m) for m in lm):
            problems.append("origins %s: legacy_methods는 method 이름 목록이어야 함" % o["id"])
        else:
            methods += lm
        if "confirm_needs_reviewer" in o and not isinstance(o["confirm_needs_reviewer"], bool):
            problems.append("origins %s: confirm_needs_reviewer는 참·거짓" % o["id"])
    for m in sorted({m for m in methods if methods.count(m) > 1}):
        problems.append("method %s가 생성 주체 둘 이상의 legacy_methods에 있음" % m)
    seen_items = {}
    for p in data.get("properties", []):
        for x in p.get("knowledge_items", []):
            if x["node_type"] not in classes or _layer(classes, x["node_type"]) != "knowledge":
                problems.append("properties %s: knowledge_items의 %s가 지식 층 클래스가 아님" % (p["id"], x["node_type"]))
            seen_items.setdefault(_item_key(x["node_type"], x["item"]), []).append(p["id"])
    for k, ps in sorted(seen_items.items()):
        if len(ps) > 1:
            problems.append("문서 항목 %s/%s가 속성 둘 이상(%s)에 대응" % (k[0], k[1], ", ".join(ps)))
    if problems:
        return problems
    if not any(r.get("pid_view") == "V1" for r in data["relations"]):
        problems.append("relations: 물리 연결 뷰(pid_view V1) 관계가 하나도 없음")
    # 적용 관계 끝은 상위 클래스로 적어도 하위 클래스에 적용된다. 한 클래스에 둘 이상 걸리면 A2 판정이 모호하다.
    for cid in classes:
        hits = sorted({r["id"] for r in data["relations"] if r.get("a2_role") == "apply"
                       for t in r["to"] if t in _ancestors(classes, cid)})
        if len(hits) > 1:
            problems.append("설비 적용 관계 둘 이상이 같은 클래스 %s를 가리킴(%s)" % (cid, ", ".join(hits)))
    return problems


def _item_key(node_type, item):
    """문서 항목 비교 키: 공백을 지우고 대소문자를 무시한다('설정 압력' = '설정압력')."""
    return node_type, "".join(str(item).split()).casefold()


def _ancestors(classes, cid):
    out = []
    while cid is not None and cid in classes:
        out.append(cid)
        cid = classes[cid].get("parent")
    return out


def _class_properties(classes, cid):
    """상속 포함 속성 ID(위 클래스 것부터, 중복 없이)."""
    out = []
    for a in reversed(_ancestors(classes, cid)):
        out += [p for p in classes[a].get("properties", []) if p not in out]
    return out


def _layer(classes, cid):
    cur = classes[cid]
    while "layer" not in cur:
        cur = classes[cur["parent"]]
    return cur["layer"]


class Registry:
    """검사를 통과한 레지스트리. 목록 순서는 파일 순서 그대로다(화면 범례 순서·kind 순서가 여기서 정해짐)."""

    def __init__(self, data):
        problems = validate(data)
        if problems:
            raise RegistryError("타입 레지스트리 형식 오류: " + "; ".join(problems))
        self.data = data
        self.version = data["registry_version"]
        # 파일 바이트가 아니라 정규화한 내용의 해시: 줄끝·들여쓰기만 바뀌면 kg_version이 바뀌지 않게
        self.sha256 = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                                separators=(",", ":")).encode("utf-8")).hexdigest()
        self.classes = {c["id"]: c for c in data["classes"]}
        self.layers = {ly["id"]: ly for ly in data["layers"]}
        self.relations = {r["id"]: r for r in data["relations"]}
        self.groups = {g["id"]: g for g in data["groups"]}
        self.origins = {o["id"]: o for o in data["origins"]}
        self.properties = {p["id"]: p for p in data.get("properties", [])}
        self.kind_class = {c["kind"]: c["id"] for c in data["classes"] if "kind" in c}
        self.item_property = {_item_key(x["node_type"], x["item"]): p["id"]
                              for p in data.get("properties", []) for x in p.get("knowledge_items", [])}

    def layer(self, cid):
        return _layer(self.classes, cid)

    def is_a(self, cid, ancestor):
        """단일 상속: cid가 ancestor이거나 그 하위 클래스면 True. 레지스트리에 없는 cid는 False."""
        while cid is not None and cid in self.classes:
            if cid == ancestor:
                return True
            cid = self.classes[cid].get("parent")
        return False

    def class_properties(self, cid):
        """클래스가 가질 수 있는 속성 ID(상속 포함). 레지스트리에 없는 클래스는 빈 목록."""
        return _class_properties(self.classes, cid)

    def class_required(self, cid):
        """없으면 미확인으로 기록하는 속성 ID(상속 포함)."""
        out = []
        for a in reversed(_ancestors(self.classes, cid)):
            out += [p for p in self.classes[a].get("required", []) if p not in out]
        return out

    def property_of_item(self, node_type, item):
        """설정치·운전조건의 항목(item) -> 같은 칸으로 비교할 P&ID 속성 ID(knowledge_items). 없으면 None."""
        if not node_type or not item:
            return None
        return self.item_property.get(_item_key(node_type, item))

    def kinds_requiring(self, prop):
        return {k for k, cid in self.kind_class.items() if prop in self.class_required(cid)}

    def label(self, cid, default=None):
        c = self.classes.get(cid)
        return c["label_ko"] if c else default

    def pid_categories(self):
        """P&ID 분류(최상위 plant_item 바로 아래 클래스) ID, 파일 순서."""
        return [c["id"] for c in self.data["classes"] if c.get("parent") == PID_ROOT]

    def kind_category(self):
        """kind -> 분류(상위 클래스 ID). 추출 규칙의 KIND_CATEGORY."""
        return {c["kind"]: c["parent"] for c in self.data["classes"] if "kind" in c}

    def node_prefix(self):
        """지식 층 클래스 -> 권고 ID 접두어."""
        return {c["id"]: c["id_prefix"] for c in self.data["classes"] if "id_prefix" in c and self.layer(c["id"]) == "knowledge"}

    def link_types(self):
        """지식 층 관계 -> (허용 시작 클래스 집합, 허용 끝 클래스 집합)."""
        return {r["id"]: (set(r["from"]), set(r["to"])) for r in self.data["relations"] if r["layer"] == "knowledge"}

    def pid_view_kinds(self, view):
        return tuple(r["id"] for r in self.data["relations"] if r.get("pid_view") == view)

    def apply_relation_of(self, cid, evidence_gap=None):
        """지식 클래스 -> 그 노드를 설비에 적용하는 관계(끝 클래스를 상위 클래스로 적은 관계 포함). 없으면 None.
        evidence_gap=True면 근거 공백 판정에 세는 관계만."""
        ancestors = _ancestors(self.classes, cid)
        for r in self.data["relations"]:
            if r.get("a2_role") == "apply" and (evidence_gap is None or r["evidence_gap"] is evidence_gap) \
                    and any(t in ancestors for t in r["to"]):
                return r["id"]
        return None

    def apply_kind_of(self, evidence_gap=None):
        """A2 '설비 적용' 관계를 가진 클래스 -> 관계(파일 순서, 상속 포함). evidence_gap=True면 근거 공백 판정에 세는 것만."""
        out = {}
        for cid in self.classes:
            rel = self.apply_relation_of(cid, evidence_gap)
            if rel is not None:
                out[cid] = rel
        return out

    def pair_allowed(self, relation, from_cls, to_cls):
        """관계 허용 쌍: 끝 클래스가 허용 클래스이거나 그 하위 클래스(단일 상속)."""
        r = self.relations.get(relation)
        return r is not None and any(self.is_a(from_cls, a) for a in r["from"]) \
            and any(self.is_a(to_cls, a) for a in r["to"])

    def screen_layer(self, layer):
        """레지스트리 층 -> ③ 화면 층 키."""
        return self.layers[layer]["screen"]

    def conflict_kinds(self):
        """같은 대상·항목 값 충돌(K7)을 비교하는 관계 -> 끝 클래스."""
        return {r["id"]: r["to"][0] for r in self.data["relations"] if r.get("conflict_check")}

    def origin_of_method(self):
        """method -> origin. origin이 없던 옛 지식 입력을 읽을 때 쓴다."""
        return {m: o["id"] for o in self.data["origins"] for m in o["legacy_methods"]}

    def origins_needing_reviewer(self):
        """사람 확인(reviewed_by) 없이 confirmed가 될 수 없는 생성 주체."""
        return tuple(o["id"] for o in self.data["origins"] if o.get("confirm_needs_reviewer"))

    def legend_classes(self):
        """범례가 있는 클래스(파일 순서)."""
        return [c for c in self.data["classes"] if "legend" in c]


def load(path=REGISTRY_FILE):
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except ValueError as exc:
            raise RegistryError("타입 레지스트리 JSON 오류: %s" % exc) from None
    return Registry(data)


REGISTRY = load()
