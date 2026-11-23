"""판 이전 불변식 퍼즈(hazop.study.migrate·idmap). 합성 도면을 여러 번 다시 추출한 것처럼 바꾸며(기호 지움·옮김·종류·
태그 바꿈·되살림·순서만 섞임·판 문자열만 바뀜·앞 판으로 되돌아감) 무작위 검토구간 집합(편집 묶음 포함)과 ⑤ 결과를 판
이전하고, 생성기가 따로 들고 다니는 기호의 진짜 정체(_uid)와 견준다. 배관은 더하고 지우고 나누고 합치며 한쪽 끝만 남기도
한다. 사슬 가운데 구간을 새로 제안해 집합을 바꾸기도
한다(결과는 옛 집합이 지은 묘비를 그대로 든다). 판정은 판 이전 코드가 남긴 기록(묘비 기록·되찾기 기록)을 정답으로 쓰지
않는다. 판 문자열은 실제 graph_version처럼 내용 해시라 앞 판으로 되돌아가면 같은 판 문자열이다.

도면 꼴은 벡터 PDF·스캔(img-)·drawio·DEXPI(파일 id와 가져오기가 지은 id가 섞임)이고, 프로젝트 그래프(도면 둘을 도면
연결점으로 이음, 한 도면만 다시 추출)도 돈다. 집합 꼴은 새 꼴·A꼴(표시 없음)·B꼴(순번 정규식 표시, lost_members)이다.
⑤ 결과는 판 이전마다 따라가는 것, 몇 판 이전을 건너뛰고 늦게 따라오는 것(집합 저장 뒤 결과 저장 실패), 되돌아온 판에서
새로 단 참조를 함께 본다. 사슬 가운데 집합을 앞 판 백업으로 되돌리거나(결과는 그대로), 이력 줄을 옛 꼴(kept_*·step 없음)로
바꾸거나, 결과의 줄 번호를 지우기도 한다.
알려진 한계는 종류·태그·상자가 같은 기호(표시가 같아 가릴 수 없음)와, 상자 없는 배관 하나를 지우고 같은 두 끝 사이에
겉모습(종류·태그)이 같은 배관을 새로 그은 것(도면에서 가를 정보가 없음, 시드 584), 같은 source id·같은 종류로 돌아온 다른
기호(source 묘비는 참조와 겉모습으로 되찾음)뿐이다. 상자 없는 구성요소가 겉모습이
같아도 끝이 다른 것으로 이어지거나 둘이 하나로 모이면 위반이다.

불변식(위반 이름의 첫 글자)
① 옛 구성요소·참조는 이어지거나 묘비가 된다. 조용히 사라지지 않고, 자리·참조 수가 줄지 않는다. 묘비 id 하나는 기호 하나다.
② 이어진 것·되찾은 것·⑤ 참조·실행 취소 기록이 가리키는 기호의 진짜 정체는 처음과 같다(표지가 같은 다른 기호는 알려진
  한계로 따로 센다).
③ 묘비는 되찾기 말고는 어떤 기호도 가리키지 않고, 처음부터 대상이 없던 참조가 판 이전 뒤 기호를 가리키지 않는다.
④ 같은 판 이전을 두 번 해도 같고, 판이 같으면 결과를 다시 옮기지 않으며, 즉시 옮긴 결과와 이력으로 늦게 옮긴 결과가 같다.
⑤ 예외가 없다.
⑥ 등록되지 않은 자리에서 옛 id를 만나지 않는다.
⑦ 다시 추출에서 순번 구성요소를 이었으면 앞뒤 기호의 종류·태그·위치가 같다(사람 고침은 ⑬).
⑧ 내용이 같은 다시 추출(순서만 섞임·판 문자열만 바뀜·범주만 바뀜)은 확인할 수 있는 구성요소를 잃지 않고 재확인 구간을 만들지 않는다.
  나누기를 되돌렸다 다시 해 같은 나눈 id·같은 종류(잃을 때 태그가 있었으면 같은 태그)로 돌아온 기호는, 그 기호를 든 열린
  묘비가 하나뿐이고 잃을 때 집합이 겉모습을 적어 두었으면 되찾는다.
⑬ 덧바르는 사람 고침(태그·종류·배관 번호·경로·끝, 기준 추출 판이 같음)은 새 판에도 있는 기호를 잃지 않는다.

프로젝트 문서(M3: ⑥ 초기사건 문서·FMEA·잠재 후보 판단, hazop.study.follow)도 ⑤ 결과처럼 따라간다. 판 이전마다 따라가거나
건너뛰고(판 표지로 늦게 따라옴), 되돌아온 판에서 새로 단 표제 대상을 함께 보며, 판 표지가 없는 옛 문서는 사슬 끝에 한 번
따라간다(문서 시각 사이에 판 이전이 끼면 묘비). 집합을 읽지 않고 그래프 판으로 표지를 찍은 문서(③을 ④보다 먼저)도 섞고,
판 이전 전에 새 판 그래프로 쓰려 하면 거절되는지 본다(옛 표지 아래 새 판 참조를 쓰면 위반 ④). ①~⑥을 같은 진짜 정체로 판정한다. 시각은 사슬 차례대로 c00(집합) <
c00a(문서) < c01(첫 판 이전) < c01b(그 뒤 새로 제안한 집합) < c02 … 이다.

시드 수는 HAZOP_FUZZ_SEEDS(기본 SEEDS)로 늘린다.
"""

import collections
import copy
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import traceback
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.extract import ids  # noqa: E402
from hazop.graph import project  # noqa: E402
from hazop.kg import expect  # noqa: E402
from hazop.study import follow, idmap, migrate, node_tools  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402

SEEDS = int(os.environ.get("HAZOP_FUZZ_SEEDS") or 700)  # 200에서는 시드 174·584 같은 드문 꼴을 놓쳤다(700시드 약 32초)
GID = "graph-T"
KINDS = ["manual_valve", "manual_valve", "manual_valve", "pump", "tank", "check_valve"]
TAGS = [None, None, None, "V-1", "V-2", "P-1", "V-1"]
FORMATS = ["pdf_vector", "pdf_vector", "raster_png", "drawio", "dexpi"]
LIMIT = "표지가 같은 다른 기호(알려진 한계)"
LIMIT_PIPE = "같은 두 끝 사이 겉모습이 같은 상자 없는 배관(알려진 한계, 위 한계 수에 듦)"
LIMIT_SOURCE = "같은 source id·같은 종류로 돌아온 다른 기호(알려진 한계, 위 한계 수에 듦)"
RULE = "R-1"
SET_HOLDERS = tuple(p for p, s in idmap.FIELDS[idmap.SET] if s == idmap.MEMBERS)
DOC_KINDS = (idmap.IE, idmap.FMEA, idmap.LATENT)


def to_b_form(ns, g):
    """49033f1 판이 썼을 꼴: 표시는 순번 정규식에 걸린 것만, id 근거 없음, 묘비 대신 lost_members(나중에 들인 칸도 없음)."""
    out = copy.deepcopy(ns)
    for k in ("graph_member_basis", "graph_member_ends", "tombstones", "tomb_seq") + idmap.OPTIONAL_SNAPSHOT:
        out.pop(k, None)
    out["schema_version"] = "0.2"
    out["graph_member_marks"] = idmap.legacy_marks(g)
    return out


def to_c_form(ns):
    """f945ff2 전에 저장한 0.3 집합: 나중에 들인 판 사진 칸(source 겉모습·시트 자료)이 없다. 실제로 가장 흔한 옛 꼴."""
    out = copy.deepcopy(ns)
    for k in idmap.OPTIONAL_SNAPSHOT:
        out.pop(k, None)
    return out


def to_a_form(ns, g):
    out = to_b_form(ns, g)
    out.pop("graph_member_marks")
    return out


# ---------------------------------------------------------------- 합성 도면

def place(r):
    return [r.randrange(0, 12) * 20.0, r.randrange(0, 3) * 20.0, 5.0, 5.0]


def make_world(r, sheet="T", conts=()):
    syms = [{"uid": "%s:s%d" % (sheet, u), "kind": r.choice(KINDS), "tag": r.choice(TAGS), "bbox": place(r),
             "nobox": r.random() < 0.05, "fixed": r.random() < 0.15} for u in range(r.randint(2, 9))]
    if r.random() < 0.3 and len(syms) > 1:  # 태그 없는 같은 종류가 같은 자리(알려진 한계)
        syms[1].update(kind=syms[0]["kind"], tag=None, bbox=list(syms[0]["bbox"]))
    syms += [{"uid": "%s:k%d" % (sheet, i), "kind": "continuation", "tag": None, "bbox": place(r), "label": lbl,
              "nobox": r.random() < 0.05, "fixed": False} for i, lbl in enumerate(conts)]
    juncs = [{"uid": "%s:j%d" % (sheet, u), "kind": "tee", "tag": None, "bbox": place(r)[:2] + [2.0, 2.0],
              "nobox": False, "fixed": False} for u in range(r.randint(0, 2))]
    allu = [s["uid"] for s in syms + juncs]
    pipes = [{"uid": "%s:c%d" % (sheet, u), "ends": r.sample(allu, 2), "bbox": place(r)[:2] + [15.0, 1.0],
              "nobox": r.random() < 0.4, "tag": r.choice([None, "L-1"])} for u in range(r.randint(1, 6))]
    return {"sheet": sheet, "syms": syms, "juncs": juncs, "pipes": pipes, "next": 100, "fmt": r.choice(FORMATS),
            "basis": r.random() > 0.1, "order_seed": 0, "stamp": 0}


def make_project(r):
    k = r.randint(1, 3)
    a = make_world(r, "A", ["TO B\nL-%d" % i for i in range(1, k + 1)])
    b = make_world(r, "B", ["FROM A\nL-%d" % i for i in range(1, k + 1)])
    return {"sheets": {"A": a, "B": b}}


def _repoint(pipes, mapping):
    for p in pipes:
        ends = []
        for k, e in enumerate(p["ends"]):
            to = mapping.get(e, e)
            to = to[min(k, len(to) - 1)] if isinstance(to, list) else to
            if to not in ends:
                ends.append(to)
        p["ends"] = ends


def split_or_unsplit(r, w):
    """사람의 나누기 연산(U1)과 그 되돌림. 순번 도면(벡터 PDF·스캔)에서 덩어리 기호 하나를 기호 2~3개로 나눈다. 나눈 기호는
    연산마다 id가 `<머리>-split-<op>`로 고정이고(hazop.extract.ids), 덩어리는 없어지거나 몸체만 남아 상자가 바뀐다. 배관 끝은
    나눈 기호로 옮겨 붙는다. 되돌리면 나눈 기호가 모두 빠지고 덩어리가 처음 모습으로 돌아오며 배관 끝도 덩어리로 돌아간다.
    되돌린 것을 다시 하면(redo) 같은 연산이라 같은 나눈 기호(같은 id·uid·종류·태그)가 돌아온다. 다시 할 때 조각 하나를 다른
    종류로 고쳐 나누면(redo_other) 같은 나눈 id의 다른 기호(새 uid)다. 새로 나누면 새 연산이라 새 id다. 일어난 일은
    w["split_events"]에 적는다(판 문자열에는 들지 않음)."""
    if w["fmt"] not in ("pdf_vector", "raster_png"):
        return
    events = w.setdefault("split_events", [])
    done = w.setdefault("split_blobs", [])
    if done and r.random() < 0.4:
        unsplit(r, w)
        return
    if redo_split(r, w):
        return
    cand = [s for s in w["syms"] if s["kind"] != "continuation" and not s.get("fixed") and not s.get("split")
            and s["uid"] not in {d["blob"]["uid"] for d in done}]
    if not cand or r.random() >= 0.3:
        return
    blob = r.choice(cand)
    w["next"] += 1
    group = "g%d" % w["next"]
    pieces = []
    for _ in range(r.randint(2, 3)):
        w["next"] += 1
        pieces.append({"uid": "%s:s%d" % (w["sheet"], w["next"]), "kind": r.choice(KINDS), "tag": r.choice(TAGS),
                       "bbox": place(r), "nobox": False, "fixed": False, "split": "op%d" % w["next"],
                       "split_group": group})
    body = place(r) if r.random() < 0.5 else None
    done.append({"group": group, "blob": copy.deepcopy(blob), "pieces": copy.deepcopy(pieces), "body": body})
    w["syms"] = [s for s in w["syms"] if s is not blob] + ([dict(blob, bbox=body)] if body is not None else []) + pieces
    _repoint(w["pipes"], {blob["uid"]: [pieces[0]["uid"], pieces[-1]["uid"]]})
    events.append("split")


def unsplit(r, w):
    """나누기 하나를 되돌린다(split_or_unsplit)."""
    rec = w["split_blobs"].pop(r.randrange(len(w["split_blobs"])))
    pieces = [s["uid"] for s in w["syms"] if s.get("split_group") == rec["group"]]
    blob = rec["blob"]
    w["syms"] = [s for s in w["syms"] if s.get("split_group") != rec["group"] and s["uid"] != blob["uid"]]
    w["syms"].append(copy.deepcopy(blob))
    _repoint(w["pipes"], {u: blob["uid"] for u in pieces})
    w.setdefault("split_undone", []).append(rec)
    w.setdefault("split_events", []).append("unsplit")


def redo_ready(w):
    """다시 할 수 있는 되돌린 나누기의 차례들. 덩어리가 살아 있고 다른 나누기에 들지 않았으며, 지운 조각이 되살아나 있지
    않아야 한다(그러면 같은 id가 둘이 된다)."""
    here = {s["uid"] for s in w.get("syms") or ()}
    busy = {d["blob"]["uid"] for d in w.get("split_blobs") or ()}
    return [i for i, d in enumerate(w.get("split_undone") or ()) if d["blob"]["uid"] in here
            and d["blob"]["uid"] not in busy and not here & {x["uid"] for x in d["pieces"]}]


def redo_split(r, w):
    """되돌린 나누기 하나를 다시 한다(split_or_unsplit). 했으면 True."""
    ready = redo_ready(w)
    if not ready:
        return False
    rec = w["split_undone"].pop(r.choice(ready))
    pieces = copy.deepcopy(rec["pieces"])
    w["deleted"] = [d for d in w.get("deleted") or [] if d["uid"] not in {x["uid"] for x in pieces}]
    other = r.random() < 0.4
    if other:  # 같은 연산 id로 다시 나누되 조각 하나를 다른 종류로: 같은 나눈 id의 다른 기호
        k = r.randrange(len(pieces))
        w["next"] += 1
        pieces[k] = dict(pieces[k], uid="%s:s%d" % (w["sheet"], w["next"]),
                         kind=r.choice(sorted(set(KINDS) - {pieces[k]["kind"]})))
    blob = next(s for s in w["syms"] if s["uid"] == rec["blob"]["uid"])
    body = [dict(blob, bbox=list(rec["body"]))] if rec["body"] is not None else []
    w["syms"] = [s for s in w["syms"] if s is not blob] + body + copy.deepcopy(pieces)
    _repoint(w["pipes"], {blob["uid"]: [pieces[0]["uid"], pieces[-1]["uid"]]})
    w["split_blobs"].append(dict(rec, pieces=pieces))
    w.setdefault("split_events", []).append("redo_other" if other else "redo")
    return True


def undo_or_redo(kind):
    """나누기를 되돌리기만, 또는 되돌린 나누기를 다시 하기만 하는 다시 추출(사람이 수정 기록에서 누름)."""
    def step(r, w):
        w = copy.deepcopy(w)
        w["split_events"] = []
        if kind == "redo":
            redo_split(r, w)
        else:
            unsplit(r, w)
        return w
    return step


def mutate(r, w):
    w = copy.deepcopy(w)
    w["split_events"] = []
    split_or_unsplit(r, w)
    out = []
    for s in w["syms"]:
        x = r.random()
        if x < 0.15:
            w.setdefault("deleted", []).append(s)
            continue
        if x < 0.25:
            s["bbox"] = place(r)
        elif x < 0.30:
            s["kind"] = r.choice(KINDS)
        elif x < 0.40:
            s["tag"] = r.choice(TAGS)
        out.append(s)
    for d in list(w.get("deleted") or []):
        if r.random() < 0.15:  # 지운 자리에 다른 기호(새 uid)
            w["next"] += 1
            out.append(dict({k: v for k, v in d.items() if k not in ("split", "split_group")},
                            uid="%s:s%d" % (w["sheet"], w["next"]), tag=None))
    for d in list(w.get("deleted") or []):
        if r.random() < 0.4 and d["uid"] not in {s["uid"] for s in out}:  # 같은 기호가 돌아옴
            out.append(copy.deepcopy(d))
            w["deleted"].remove(d)
    for _ in range(r.randint(0, 2)):
        w["next"] += 1
        out.append({"uid": "%s:s%d" % (w["sheet"], w["next"]), "kind": r.choice(KINDS), "tag": r.choice(TAGS),
                    "bbox": place(r), "nobox": False, "fixed": r.random() < 0.15})
    w["syms"] = out
    alive = {s["uid"] for s in out + w["juncs"]}
    pipes = []
    for p in w["pipes"]:
        p["ends"] = [e for e in p["ends"] if e in alive]
        x = r.random()
        if x < 0.08:  # 배관을 지움
            continue
        if x < 0.14 and len(p["ends"]) == 2:  # 가운데 새 이음점으로 둘로 나눔
            w["next"] += 2
            j = {"uid": "%s:j%d" % (w["sheet"], w["next"]), "kind": "tee", "tag": None, "bbox": place(r)[:2] + [2.0, 2.0],
                 "nobox": False, "fixed": False}
            w["juncs"].append(j)
            pipes.append(dict(p, ends=[p["ends"][0], j["uid"]]))
            pipes.append(dict(copy.deepcopy(p), uid="%s:c%d" % (w["sheet"], w["next"] - 1), ends=[j["uid"], p["ends"][1]],
                              bbox=place(r)[:2] + [15.0, 1.0]))
            continue
        if x < 0.18 and p["ends"]:  # 한쪽 끝이 끊김
            p["ends"] = p["ends"][:1]
        if r.random() < 0.1:
            p["bbox"] = place(r)[:2] + [15.0, 1.0]
        pipes.append(p)
    pairs = [(a, b) for a in pipes for b in pipes if a is not b and len(a["ends"]) == 2 and len(b["ends"]) == 2
             and len(set(a["ends"]) & set(b["ends"])) == 1]
    if pairs and r.random() < 0.15:  # 끝 하나를 나눠 가진 두 배관을 하나로 합침
        a, b = r.choice(pairs)
        a["ends"] = sorted(set(a["ends"]) ^ set(b["ends"]))
        pipes.remove(b)
    ends_pool = sorted(alive | {j["uid"] for j in w["juncs"]})
    if len(ends_pool) > 1 and r.random() < 0.3:  # 새 배관
        w["next"] += 1
        pipes.append({"uid": "%s:c%d" % (w["sheet"], w["next"]), "ends": r.sample(ends_pool, 2),
                      "bbox": place(r)[:2] + [15.0, 1.0], "nobox": r.random() < 0.4, "tag": r.choice([None, "L-1"])})
    w["pipes"] = pipes
    w["order_seed"] = r.random()
    return w


def overlay(r, w):
    """덧바르는 사람 고침(태그·종류·배관 번호·경로·끝): 기준 추출이 같아 순번 id가 그대로다(기호 목록·순서는 그대로)."""
    w = copy.deepcopy(w)
    w["split_events"] = []
    alive = [s["uid"] for s in w["syms"] if s["kind"] in KINDS]
    for s in w["syms"]:
        if s["kind"] in KINDS and r.random() < 0.3:
            s.update({"tag": r.choice(TAGS)} if r.random() < 0.5 else {"kind": r.choice(KINDS)})
    for p in w["pipes"]:
        x = r.random()
        if x < 0.15:
            p["tag"] = r.choice([None, "L-1", "L-H"])
        elif x < 0.3:
            p["bbox"] = place(r)[:2] + [15.0, 1.0]
        elif x < 0.4 and len(p["ends"]) == 2 and set(alive) - set(p["ends"]):
            p["ends"] = [p["ends"][0], r.choice(sorted(set(alive) - set(p["ends"])))]
    return w


def reorder(r, w):
    """내용은 같고 열거 순서만 다른 다시 추출(순번이 밀림)."""
    return dict(copy.deepcopy(w), order_seed=r.random())


def restamp(w):
    """내용도 순서도 같고 판 문자열만 다른 다시 추출."""
    return dict(copy.deepcopy(w), stamp=w["stamp"] + 1)


def recategorize(w):
    """분류 규칙이 바뀌어 범주(종류에서 나오는 값)만 다른 다시 추출."""
    return dict(copy.deepcopy(w), cat=w.get("cat", 0) + 1)


def ver(w):
    key = {k: w.get(k) for k in ("syms", "juncs", "pipes", "fmt", "basis", "order_seed", "stamp", "cat")}
    return "v-" + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:10]


def soid_of(fmt, s, k, what):
    """(source_object_id, 어댑터가 지은 id인가). k는 그 판의 열거 순번."""
    if fmt == "drawio":
        return ("edge-" if what == "conn" else "cell-") + s["uid"].split(":")[1], False
    if fmt == "dexpi":
        if what == "conn":
            return "Seg_1__Connection_%d" % k, True
        if what == "junction" or s["fixed"]:
            return "Item-" + s["uid"].split(":")[1], False
        return "Seg_1__item_%d" % k, True
    head = "img" if fmt == "raster_png" else "pdf-p0"
    if s.get("split"):
        return "%s-split-%s" % (head, s["split"]), False
    if s.get("fixed"):
        return "manual-c-" + s["uid"].split(":")[1], False
    return "%s-%s-%04d" % (head, what, k), False


def build(w, gid=GID):
    fmt, key = w["fmt"], random.Random(w["order_seed"])
    nodes, by_uid, edges = [], {}, []

    def add(eid, s, k, what, extra):
        soid, made = soid_of(fmt, s, k, what)
        n = dict({"entity_id": eid, "source_object_id": soid, "bbox": None if s["nobox"] else list(s["bbox"]),
                  "_uid": s["uid"], "attributes": {}}, **extra)
        n["category"] = "c%d-%s" % (w.get("cat", 0), n["kind"])
        if w["basis"]:
            n["id_basis"] = ids.basis(fmt, soid, made)
        nodes.append(n)
        by_uid[s["uid"]] = n
    for i, s in enumerate(sorted(w["syms"], key=lambda s: key.random()), 1):
        extra = {"node_type": "drawing_object", "kind": s["kind"], "tag": s["tag"]}
        if s["kind"] == "continuation":
            extra.update(label_text=s["label"], attributes={"kind": "continuation"})
        add("entity-node-%03d" % i, s, i, "sym", extra)
    base = len(nodes)
    for j, s in enumerate(w["juncs"], 1):
        add("entity-node-%03d" % (base + j), s, j, "junction", {"node_type": "drawing_object", "kind": "tee", "tag": None})
    rel = 0
    for i, p in enumerate(sorted(w["pipes"], key=lambda s: key.random()), 1):
        sid = "entity-seg-%03d" % i
        add(sid, p, i, "conn", {"node_type": "pipe_segment", "kind": "pipe_segment", "tag": p["tag"], "line_no": p["tag"]})
        for e in p["ends"]:
            rel += 1
            edges.append({"entity_id": "relation-%03d" % rel, "kind": "has_endpoint", "nodes": [sid, by_uid[e]["entity_id"]]})
    return dict({"project_id": None, "graph_id": gid, "graph_version": ver(w), "source": {"drawing_number": w["sheet"]},
                 "validation": {"status": "passed"}, "nodes": nodes, "edges": edges},
                **({"base_version": w["base"]} if w.get("base") else {}))


def build_any(world):
    if "sheets" in world:
        sheets = [dict(build(w, "graph-" + name), project_id="P") for name, w in sorted(world["sheets"].items())]
        return project.build("P", sheets)
    return build(world)


def next_world(r, world, kind):
    if "sheets" not in world:
        out = {"mutate": mutate, "reorder": reorder, "recategorize": lambda r, w: recategorize(w), "overlay": overlay,
               "redo": undo_or_redo("redo"), "unsplit": undo_or_redo("unsplit")}.get(
            kind, lambda r, w: restamp(w))(r, world)
        if kind != "overlay":   # 다시 추출·나누기는 순번을 매긴 입력(기준 추출)을 바꾼다
            out["base"] = "b" + ver(out)
        return out
    out = copy.deepcopy(world)
    for s in out["sheets"].values():
        s.pop("split_events", None)
    names = sorted(out["sheets"])
    if kind == "redo":
        names = [n for n in names if redo_ready(out["sheets"][n])]
    elif kind == "unsplit":
        names = [n for n in names if out["sheets"][n].get("split_blobs")]
    pick = names if kind == "mutate" and r.random() < 0.3 else [r.choice(names)]  # 보통은 한 도면만 다시 추출
    for name in pick:
        out["sheets"][name] = next_world(r, out["sheets"][name], kind)
    return out


# ---------------------------------------------------------------- 진짜 정체

def look_of(n):
    return (n.get("sheet"), n.get("kind"), n.get("tag"), n.get("bbox"))


def same_look(a, b):
    """겉모습(도면·종류·태그·상자)이 같은가(⑦: 이은 순번 구성요소의 앞뒤)."""
    if a is None or b is None or a[0] == "xlink" or b[0] == "xlink":
        return a is not None and a == b
    if a[:3] != b[:3] or (a[3] is None) != (b[3] is None):
        return False
    return a[3] is None or all(abs(x - y) <= idmap.MARK_TOL for x, y in zip(a[3], b[3]))


def twin_look(a, b):
    """알려진 한계: 종류·태그·상자가 같은 기호(표시가 같아 가릴 수 없음). 상자 없는 것은 끝(진짜 정체)까지 같은 배관만
    한계다(겉모습 뒤에 끝을 붙인 look). 도면 연결 구간은 두 끝의 겉모습이 모두 같을 때(끝 기호가 한계로 이어지면 그 구간도 따라감)."""
    if a is None or b is None:
        return False
    if a[0] == "xlink" or b[0] == "xlink":
        return a == b
    if a[3] is None and b[3] is None:
        return len(a) == len(b) == 5 and a == b
    return a[3] is not None and b[3] is not None and same_look(a, b)


class Truth:
    """그래프 하나의 진짜 정체 색인. 도면 연결 구간은 두 끝의 정체, 관계는 종류와 양 끝의 정체."""

    def __init__(self, g):
        gid = g["graph_id"]
        self.eid = {n["entity_id"]: n["_uid"] for n in g["nodes"] if "_uid" in n}
        self.look = {n["_uid"]: look_of(n) for n in g["nodes"] if "_uid" in n}
        ends = collections.defaultdict(list)
        for e in g["edges"]:
            if e.get("sheet_link"):
                ends[e["segment"]].append(e["node"])
        for x, es in ends.items():
            u = "x:" + "+".join(sorted(self.eid[e] for e in es))
            self.eid[x] = u
            self.look[u] = ("xlink",) + tuple(sorted(json.dumps(self.look[self.eid[e]]) for e in es))
        self.ref = {}
        for n in g["nodes"]:
            r = idmap.ref_of(n, gid)
            if r is not None:
                self.ref[r] = self.eid[n["entity_id"]]
        self.exp = {expect.expectation_id(RULE, r): u for r, u in self.ref.items()}
        self.rel = {e["entity_id"]: "r:%s:%s" % (e["kind"], "+".join(sorted(self.eid.get(x, "?") for x in e["nodes"])))
                    for e in g["edges"]}
        pipe_ends = collections.defaultdict(set)
        for e in g["edges"]:
            if e.get("kind") == "has_endpoint" and len(e.get("nodes") or []) >= 2:
                pipe_ends[e["nodes"][0]].update(self.eid.get(x, "?") for x in e["nodes"][1:])
        for n in g["nodes"]:  # 상자 없는 배관은 겉모습 뒤에 끝(진짜 정체)을 붙인다(twin_look)
            if "_uid" in n and n.get("bbox") is None and n["entity_id"] in pipe_ends:
                self.look[n["_uid"]] += ("+".join(sorted(pipe_ends[n["entity_id"]])),)

    def resolve(self, space, v):
        if space == idmap.REF:
            return self.ref.get(v)
        if space == idmap.EXP:
            return self.exp.get(v)
        return self.eid.get(v) or self.rel.get(v)


def stale_targets(world, g):
    """처음 판에는 없고 다음 판에 생길 수 있는 참조·id(다음 순번)."""
    w = world["sheets"]["A"] if "sheets" in world else world
    sheet = "graph-A" if "sheets" in world else GID
    soid, _ = soid_of(w["fmt"], {"uid": "%s:s%d" % (w["sheet"], w["next"] + 1), "fixed": False}, len(w["syms"]) + 1, "sym")
    lift = (sheet + "/") if "sheets" in world else ""
    return "%s#%s" % (sheet, soid), lift + "entity-node-%03d" % (len(w["syms"]) + 1)


# ---------------------------------------------------------------- 집합과 결과

def make_set(r, g, form=None, at="c00"):
    ns = sn.new_set(g)
    ns["history"].append({"at": at, "op": "propose", "detail": {}})
    ids_ = [n["entity_id"] for n in g["nodes"]]
    for i in range(r.randint(1, 4)):
        mem = sorted(r.sample(ids_, r.randint(1, len(ids_))))
        ns["nodes"].append(dict({"node_id": "S%d" % (i + 1), "name": "n%d" % i, "basis": "b", "members": mem},
                                **sn._v2_fields("script")))
    for _ in range(r.randint(0, 3)):  # 실행 취소 기록을 만드는 편집
        live = [n for n in ns["nodes"] if n["state"] == "applied"]
        try:
            x = r.random()
            if x < 0.4 and live:
                n = r.choice(live)
                if len(n["members"]) > 1:
                    ns = sn.split(ns, n["node_id"], r.sample(n["members"], len(n["members"]) // 2), at=at)
            elif x < 0.7 and live:
                n = r.choice(live)
                ns = sn.remove_member(ns, n["node_id"], r.choice(n["members"]), at=at)
            elif len(live) > 1:
                ns = sn.merge(ns, [n["node_id"] for n in r.sample(live, 2)], at=at)
        except ValueError:
            pass
    pick = [n["node_id"] for n in ns["nodes"] if r.random() < 0.6]
    if pick:
        ns = sn.confirm_nodes(ns, g, pick, "x", at=at)
    for n in ns["nodes"]:
        if n["state"] == "confirmed" and r.random() < 0.2:
            n["state"], n["locked"] = "locked", {"at": "t", "by": "x"}
    form = form or r.choice(["new", "new", "a", "b", "b"])
    if form == "a":
        ns = to_a_form(ns, g)
    elif form == "new" and len(ns["nodes"]) % 3 == 0:   # 난수 흐름을 바꾸지 않고 새 꼴의 셋에 하나쯤을 옛 0.3 꼴로
        ns = to_c_form(ns)
    elif form == "b":
        ns = to_b_form(ns, g)
        for n in ns["nodes"]:
            if r.random() < 0.15:  # 앞 판 이전이 남긴 잃은 기록(되찾을 수 없는 자리, 손상 기록)
                n["lost_members"] = r.choice([
                    [{"entity_id": "entity-node-900", "ref": g["graph_id"] + "#pdf-p0-sym-0900",
                      "mark": ["drawing_object", None, "pump", None, 999.0, 999.0, 1004.0, 1004.0], "from": "v-0"}],
                    [None], ["x"], [{}]])
    return ns, form


def make_entry(r, g, members, stale):
    by_id = {n["entity_id"]: n for n in g["nodes"]}
    refs = [idmap.ref_of(by_id[m], g["graph_id"]) for m in members]
    refs = [x for x in refs if x]
    pick = lambda: [{"ref": x} for x in r.sample(refs, r.randint(0, len(refs)))]  # noqa: E731
    path = list(members) + ["cond-001"]
    touching = [e["entity_id"] for e in g["edges"] if set(e["nodes"]) & set(members)]
    if touching and r.random() < 0.5:
        path.append(r.choice(touching))
    causes = [{"ref": x} for x in refs]
    if stale and r.random() < 0.5:
        causes.append({"ref": stale[0]})
        path.append(stale[1])
    entry = {"cause_refs": causes, "consequence_refs": pick(), "safeguards": [{"refs": pick()}],
             "expectation_refs": [expect.expectation_id(RULE, x) for x in refs], "ai_basis": {"kg_paths": [path]}}
    if r.random() < 0.3:
        entry["history"] = [{"before": {"cause_refs": pick(), "expectation_refs": [expect.expectation_id(RULE, x)
                                                                                    for x in refs[:1]]}}]
    return entry


def make_results(r, ns, g, stale):
    cells = [{"node_id": n["node_id"], "entries": [make_entry(r, g, n["members"], stale)]} for n in ns["nodes"]]
    archived = [{"cell": {"node_id": c["node_id"], "entries": [make_entry(r, g, ns["nodes"][0]["members"], None)]},
                 "reason": "x"} for c in cells[:1] if r.random() < 0.4]
    return {"schema_version": "0.3", "graph_id": g["graph_id"], "graph_version": g["graph_version"], "cells": cells,
            **({"archived_cells": archived} if archived else {})}


def make_doc(r, kind, g, at="c00a"):
    """프로젝트 문서 하나(등록부 자리만 채운 꼴). 참조는 이 판 그래프의 것."""
    gid = g["graph_id"]
    nodes = [n for n in g["nodes"] if idmap.ref_of(n, gid)]
    refs = [idmap.ref_of(n, gid) for n in nodes]
    pick = lambda k: r.sample(refs, min(k, len(refs)))  # noqa: E731
    if kind == idmap.IE:
        bes = {}
        for i, x in enumerate(pick(r.randint(1, 4)), 1):
            bes["BE-%03d" % i] = {"ref": x, "key": "%s|%s" % (x, r.choice(["FTO", "FTC", ""]))}
        return {"headings": {"H-%02d" % i: {"targets": pick(r.randint(1, 3))} for i in range(1, r.randint(2, 4))},
                "basic_events": bes, "history": [{"at": at, "op": "edit", "before": {"targets": pick(2)}}]}
    if kind == idmap.FMEA:
        rows = {"FM-%03d" % i: {"ref": idmap.ref_of(n, gid), "entity_id": n["entity_id"], "status": "approved"}
                for i, n in enumerate(r.sample(nodes, min(3, len(nodes))), 1)}
        return {"rows": rows, "history": [{"at": at, "op": "edit", "before": {"ref": r.choice(refs)}}],
                "imports": [{"at": at}]}
    judg = {}
    for x in pick(3):
        k = "%s|%s" % (r.choice(["E01", "E04"]), x)
        rec = {"key": k, "target": x, "found": pick(1), "rejected": pick(1), "at": at}
        judg.setdefault(k, dict(rec, history=[copy.deepcopy(rec)]))  # 파일에서 읽은 문서처럼 목록을 함께 쓰지 않음
    return {"judgements": judg}


def doc_slots(doc, kind):
    """{(등록 경로, 공간): [값]} 프로젝트 문서의 등록된 자리 전부(차례 고정, 열쇠 꼴은 참조 부분만, 공간은 REF로)."""
    out = {}
    for p, s in idmap.FIELDS[kind]:
        if p.endswith("{}"):
            vals = [k for h, key in idmap.walk(doc, p[:-2]) for k in h[key]]
        else:
            vals = [h[k] for h, k in idmap.walk(doc, p)]
        if s == idmap.HEAD:
            vals = [v.partition("|")[0] for v in vals]
        elif s == idmap.TAIL:
            vals = [v.partition("|")[2] for v in vals]
        out[(p, idmap.REF if s in (idmap.HEAD, idmap.TAIL) else s)] = vals
    return out


def holders(ns):
    """{등록 경로: [members를 가진 사전 또는 None]} 집합의 MEMBERS 자리 전부(차례 고정)."""
    return {p: [h[k] for h, k in idmap.walk(ns, p)] for p in SET_HOLDERS}


def ref_slots(doc):
    """{(등록 경로, 공간): [값]} 결과의 등록된 id 자리 전부(차례 고정)."""
    return {(p, s): [h[k] for h, k in idmap.walk(doc, p)] for p, s in idmap.FIELDS[idmap.RESULTS]}


# ---------------------------------------------------------------- 판정

class Judge:
    def __init__(self):
        self.stats = collections.Counter()
        self.examples = collections.defaultdict(list)

    def note(self, kind, info):
        self.stats[kind] += 1
        if len(self.examples[kind]) < 3:
            self.examples[kind].append(info)


class Track:
    """한 사슬의 판정 상태. 생성기가 아는 정체만 쓰고, 판 이전 코드의 묘비·되찾기 기록은 견줄 대상일 뿐이다."""

    def __init__(self, judge, seed):
        self.j, self.seed = judge, seed
        self.looks = collections.defaultdict(list)  # 정체 → 지나온 판에서 보인 겉모습들
        self.tomb_truth = {}   # 묘비 id → 처음 잃은 기호의 정체
        self.tomb_first = {}   # 묘비 id → 처음 본 기록
        self.tomb_seen = {}    # 묘비 id → (잃기 전 판의 참조, 겉모습)
        self.sets = {}         # 등록 경로 → [{"allowed": 정체 집합, "taint": bool}]

    def see(self, truth):
        for u, lk in truth.look.items():
            if lk not in self.looks[u]:
                self.looks[u].append(lk)

    def looked_like(self, uids, look):
        hit = any(twin_look(x, look) for u in uids for x in self.looks.get(u, ()))
        if hit and look is not None and look[0] != "xlink" and look[3] is None:
            self.j.stats[LIMIT_PIPE] += 1
        return hit

    # -- 집합

    def adopt_set(self, ns, truth, start=0):
        for p, hs in holders(ns).items():
            rows = self.sets.setdefault(p, [])
            for h in hs[len(rows):]:
                mem = (h or {}).get("members") if isinstance(h, dict) else None
                lost = (h or {}).get("lost") if isinstance(h, dict) else None  # 백업에서 되돌린 집합의 묘비가 가리키던 기호
                rows.append({"allowed": {truth.eid[m] for m in mem or () if m in truth.eid}
                             | {self.tomb_truth[t] for t in lost or () if self.tomb_truth.get(t)}, "taint": False})

    def judge_limit(self, u_new, allowed, truth_new):
        return self.looked_like(allowed, truth_new.look.get(u_new))

    def check_holder(self, where, h, row, truth_new):
        if not isinstance(h, dict) or not isinstance(h.get("members"), list):
            if row["allowed"]:
                self.j.note("① 자리가 사라짐", (self.seed, where))
            return
        live = set()
        for e in h["members"]:
            u = truth_new.eid.get(e)
            if u is None:
                self.j.note("③ 새 판에 없는 id가 members에 있음", (self.seed, where, e))
                continue
            live.add(u)
            if u not in row["allowed"]:
                if self.judge_limit(u, row["allowed"], truth_new):
                    self.j.note(LIMIT, (self.seed, where, e))
                    row["allowed"].add(u)
                    row["taint"] = True
                else:
                    self.j.note("② 구간에 없던 기호가 members에 들어옴", (self.seed, where, e, u, sorted(row["allowed"])))
        tombs = set()
        for t in (h.get("lost") or []) + (h.get("discarded") or []):  # 사람이 버린 묘비도 사라진 것이 아님
            if not idmap.is_tomb(t) or t in truth_new.eid:
                self.j.note("③ lost에 살아 있는 id", (self.seed, where, t))
            tombs.add(self.tomb_truth.get(t))
        missing = row["allowed"] - live - tombs
        if missing:  # 표지가 같은 다른 기호가 그 자리를 가져갔으면 알려진 한계
            twin = row["taint"] or all(any(self.looked_like([u], truth_new.look.get(x)) for x in live) for u in missing)
            row["taint"] = row["taint"] or twin
            self.j.note(LIMIT if twin else "① 사라짐(이어지지도 묘비도 아님)", (self.seed, where, sorted(missing)))

    def check_set(self, ns_a, ns_b, truth_a, truth_b):
        d = ns_b["history"][-1]["detail"]
        for t, rec in (ns_b.get("tombstones") or {}).items():
            key = json.dumps([rec.get(k) for k in ("entity_id", "ref", "mark", "lost_from", "lost_at")])
            if self.tomb_first.setdefault(t, key) != key:
                self.j.note("① 묘비 기록이 덮어써짐", (self.seed, t))
        for m, t in (d.get("lost") or {}).items():
            u = truth_a.eid.get(m)
            if self.tomb_truth.setdefault(t, u) != u:
                self.j.note("① 같은 묘비 id가 다른 기호에 다시 쓰임", (self.seed, t, self.tomb_truth[t], u))
            if u is not None:
                self.tomb_seen.setdefault(t, (next((r for r, x in truth_a.ref.items() if x == u), None), truth_a.look[u]))
        for t, e in (d.get("found") or {}).items():
            want, got = self.tomb_truth.get(t), truth_b.eid.get(e)
            if want is not None and got != want:
                ok = self.looked_like([want], truth_b.look.get(got))
                if not ok and self.same_source(t, got, truth_b):
                    ok = True
                    self.j.stats[LIMIT_SOURCE] += 1
                self.j.note(LIMIT if ok else "② 되찾은 묘비가 다른 기호", (self.seed, t, want, got))
            self.j.stats["되찾은 묘비"] += 1
            if self.tomb_seen.get(t, (None,))[0] and truth_b.ref.get(self.tomb_seen[t][0]) == got:
                self.j.stats["같은 source id로 되찾은 묘비"] += 1
        self.check_redo(ns_b, truth_a, truth_b)
        before, after = holders(ns_a), holders(ns_b)
        for p in SET_HOLDERS:
            if len(before[p]) != len(after[p]):
                self.j.note("① 자리 수가 바뀜", (self.seed, p, len(before[p]), len(after[p])))
                continue
            for i, h in enumerate(after[p]):
                self.j.stats["구간 자리 점검"] += 1
                self.check_holder("%s[%d]" % (p, i), h, self.sets[p][i], truth_b)

    def same_source(self, t, u, truth):
        """잃은 기호와 같은 참조·같은 종류(잃을 때 태그가 있었으면 같은 태그)로 돌아온 기호인가."""
        ref, look = self.tomb_seen.get(t, (None, None))
        now = truth.look.get(u)
        return (ref is not None and now is not None and truth.ref.get(ref) == u and now[:2] == look[:2]
                and (look[2] is None or now[2] == look[2]))

    def check_redo(self, ns_b, truth_a, truth_b):
        """⑧ 앞 판에 없던 기호가 잃을 때와 같은 참조·종류로 돌아왔고(나누기 되돌림 뒤 다시 나누기), 그 기호를 든 열린
        묘비가 하나뿐이며 구간 lost에 있고 잃을 때 집합이 겉모습을 적어 두었으면 되찾았어야 한다."""
        tombs = ns_b.get("tombstones") or {}
        gone = idmap.discarded_tombs(ns_b)
        held = {t for n in ns_b["nodes"] for t in n.get("lost") or []}
        open_ = collections.defaultdict(list)
        for t, rec in tombs.items():
            u = self.tomb_truth.get(t)
            if (isinstance(rec, dict) and rec.get("found") is None and t not in gone and u is not None
                    and u not in truth_a.look and self.same_source(t, u, truth_b)):
                open_[u].append(t)
        for u, ts in open_.items():
            if len(ts) == 1 and ts[0] in held and tombs[ts[0]].get("look") is not None:
                self.j.note("⑧ 같은 나눈 id로 돌아온 기호의 묘비를 되찾지 못함", (self.seed, ts[0], u))

    def check_seq_look(self, ns_b, g_a, g_b):
        """⑦ 순번 구성요소는 표시로만 잇는다: 이은 앞뒤 기호의 종류·태그·위치가 같다."""
        d = ns_b["history"][-1]["detail"]
        ua = {n["entity_id"]: n for n in g_a["nodes"]}
        ub = {n["entity_id"]: n for n in g_b["nodes"]}
        basis = idmap.bases(g_a)
        for m, e in (d.get("renamed") or {}).items():
            o, n = ua.get(m), ub.get(e)
            if o and n and "_uid" in o and basis[m] == ids.SEQUENCE and o["_uid"] == n["_uid"] \
                    and not same_look(look_of(o), look_of(n)):
                self.j.note("⑦ 순번 구성요소인데 표지가 다른 기호로 이음", (self.seed, m, e))

    def check_overlay(self, ns_a, ns_b, g_b, truth_a, truth_b):
        """⑬ 덧바르는 사람 고침의 판 이전: 옛 판 사진과 새 그래프의 기준 추출 판이 같은 시트에서 새 판에도 있는 기호를 잃지 않는다."""
        now = idmap.sheet_bases(g_b)
        same_base = {s for s, b in (ns_a.get("graph_member_bases") or {}).items() if now.get(s) == b}
        refs = ns_a.get("graph_member_refs") or {}
        self.j.stats["덧바르는 사람 고침(기준 같음)" if same_base else "덧바르는 사람 고침(기준 판 모름)"] += 1
        for m in ns_b["history"][-1]["detail"].get("lost") or {}:
            if idmap.drawing_of(refs.get(m)) in same_base and truth_a.eid.get(m) in truth_b.look:
                self.j.note("⑬ 사람 고침만 한 기호를 잃음", (self.seed, m))

    def check_same_content(self, ns_a, ns_b, plan, g_a):
        """⑧ 확인할 수 있는 구성요소(상자가 있고 표시가 겹치지 않는 순번, source)는 내용이 같은 다시 추출에서 잃지 않는다."""
        if ns_a.get("graph_member_basis") is None:
            return
        basis = idmap.bases(g_a)
        ends = collections.defaultdict(set)
        for e in g_a["edges"]:
            if e["kind"] == "has_endpoint":
                ends[e["nodes"][0]].update(e["nodes"][1:])
        marks = collections.Counter()
        for n in g_a["nodes"]:
            m = idmap.mark_of(n, basis[n["entity_id"]])
            if m is not None:
                marks[json.dumps(m[:4])] += 1  # 종류·도면·기호 종류·태그가 같은 것 둘 이상은 상자 비교가 허용오차에 걸릴 수 있음
        sure = {n["entity_id"] for n in g_a["nodes"] if basis[n["entity_id"]] == ids.SOURCE or (
            idmap.mark_of(n, ids.SEQUENCE) is not None and marks[json.dumps(idmap.mark_of(n, ids.SEQUENCE)[:4])] == 1)}
        by_end = [n for n in g_a["nodes"] if n["entity_id"] not in sure and len(ends.get(n["entity_id"]) or ()) >= 2
                  and idmap.mark_of(n, ids.SEQUENCE) is None]  # 한쪽 끝만 있는 구간은 잇지 않는다(끊긴 끝으로 잇지 않게)
        keys = collections.Counter(json.dumps([look_of(n)[:3], sorted(ends[n["entity_id"]])]) for n in by_end)
        grew = True
        while grew:  # 끝이 모두 확인되고 겉모습·끝이 겹치지 않는 상자 없는 구성요소(배관 구간·도면 연결 구간)
            grew = False
            for n in by_end:
                e = n["entity_id"]
                if e not in sure and ends[e] <= sure and keys[json.dumps([look_of(n)[:3], sorted(ends[e])])] == 1:
                    sure.add(e)
                    grew = True
        d = ns_b["history"][-1]["detail"]
        for m in d.get("lost") or {}:
            if m in sure:
                self.j.note("⑧ 내용이 같은데 확인할 수 있는 구성요소를 잃음", (self.seed, m))
        twins = any(v > 1 for v in marks.values())  # 표지가 같은 둘이 맞바뀌면 연결이 바뀐 것으로 보이는 것도 안전한 쪽이다
        if not d.get("lost") and not d.get("found") and not twins:  # 잃은 이웃이 있어 지문이 바뀌는 것도 안전한 쪽
            for nid, why in plan["recheck"].items():
                if "기록이 없음" not in why:  # 모두 잃어 지문이 없는 구간은 확인할 길이 없다
                    self.j.note("⑧ 내용이 같은데 재확인", (self.seed, nid, why))

    # -- 결과

    def adopt_results(self, slots, doc, truth, kind=idmap.RESULTS):
        for key, vals in (ref_slots(doc) if kind == idmap.RESULTS else doc_slots(doc, kind)).items():
            rows = slots.setdefault(key, [])
            for v in vals[len(rows):]:
                rows.append({"uid": truth.resolve(key[1], v), "orig": v, "dead": False})

    def check_results(self, slots, doc, truth_new, label, kind=idmap.RESULTS):
        for key, vals in (ref_slots(doc) if kind == idmap.RESULTS else doc_slots(doc, kind)).items():
            rows = slots.get(key, [])
            if len(rows) != len(vals):
                self.j.note("① 참조 수가 바뀜(%s)" % label, (self.seed, key[0], len(rows), len(vals)))
                continue
            for row, v in zip(rows, vals):
                self.j.stats["참조 점검"] += 1
                if idmap.is_tomb(v):
                    row["dead"] = True
                    self.j.stats["묘비가 된 ⑤ 참조" if kind == idmap.RESULTS else "묘비가 된 문서 참조"] += 1
                    continue
                u = truth_new.resolve(key[1], v)
                if row["uid"] is None:
                    if u is not None:
                        self.j.note("③ 처음부터 대상이 없던 참조가 기호를 가리킴(%s)" % label, (self.seed, key[0], v, u))
                    continue
                if u == row["uid"]:
                    continue
                if u is None:
                    self.j.note("③ 참조가 묘비도 살아 있는 대상도 아님(%s)" % label, (self.seed, key[0], row["orig"], v))
                elif any(self.looked_like([row["uid"]], lk) for lk in [truth_new.look.get(u)] + self.looks.get(u, [])):
                    # 늦게 따라온 참조는 이은 그 판의 겉모습으로 본다(그 뒤 사람 고침이 태그·종류를 바꿨을 수 있음)
                    self.j.note(LIMIT, (self.seed, key[0], v))
                    row["uid"] = u
                else:
                    head = "③ 묘비였던 참조가 다른 기호로 풀림" if row["dead"] else "② 참조가 다른 기호"
                    self.j.note("%s(%s)" % (head, label), (self.seed, key[0], row["orig"], v, row["uid"], u))
                    row["uid"] = u


def undo_check(track, ns_b, truth_b):
    """판 이전 뒤 마지막 묶음을 되돌리고 되살린 구간이 그 실행 취소 기록이 처음 가진 기호만 갖는지 본다."""
    live = [b for b in ns_b.get("batches") or [] if not b.get("undone")]
    if not live:
        return
    bid = live[-1]["batch_id"]
    try:
        out, _ = node_tools.undo_batch(ns_b, {"cells": []}, bid, ns_b["set_rev"], "x", "user", at="t")
    except node_tools.Refused:
        return
    track.j.stats["되돌림"] += 1
    flat = [(b["batch_id"], o) for b in ns_b["batches"] for o in b["ops"]]
    rows = track.sets["batches[].ops[].before"]
    for (b, o), row in zip(flat, rows):
        if b != bid or o["before"] is None:
            continue
        node = next((n for n in out["nodes"] if n["node_id"] == o["node_id"]), None)
        if node is None:
            continue
        for e in node["members"]:
            u = truth_b.eid.get(e)
            if u not in row["allowed"]:
                ok = u is not None and track.judge_limit(u, row["allowed"], truth_b)
                track.j.note(LIMIT if ok else "③ 되돌린 구간이 다른 기호를 가리킴", (track.seed, o["node_id"], e))
        for t in node.get("lost") or []:
            if not idmap.is_tomb(t) or t in truth_b.eid:
                track.j.note("③ 되돌린 구간의 lost에 살아 있는 id", (track.seed, t))


def plan_chain(r, project_mode):
    """[(다시 추출 종류, 세계)]. 되돌아감은 앞서 지나간 판 가운데 하나로 간다."""
    first = make_project(r) if project_mode else make_world(r)
    for w in first["sheets"].values() if project_mode else [first]:
        if r.random() < 0.8:   # 나머지는 기준 추출 판을 남기기 전에 지은 그래프
            w["base"] = "b" + ver(w)
    worlds, steps = [first], []
    for _ in range(r.randint(3, 6)):
        x = r.random()
        sheets = worlds[-1]["sheets"].values() if "sheets" in worlds[-1] else [worlds[-1]]
        if any(redo_ready(w) for w in sheets) and r.random() < 0.8:
            kind, w = "redo", next_world(r, worlds[-1], "redo")
        elif any(w.get("split_blobs") for w in sheets) and r.random() < 0.3:
            kind, w = "unsplit", next_world(r, worlds[-1], "unsplit")
        elif len(worlds) > 1 and x < 0.3:
            kind, w = "revisit", copy.deepcopy(r.choice(worlds[:-1]))
        elif x < 0.42:
            kind, w = "reorder", next_world(r, worlds[-1], "reorder")
        elif x < 0.50:
            kind, w = "restamp", next_world(r, worlds[-1], "restamp")
        elif x < 0.58:
            kind, w = "recategorize", next_world(r, worlds[-1], "recategorize")
        elif x < 0.86:
            kind, w = "mutate", next_world(r, worlds[-1], "mutate")
        else:
            kind, w = "overlay", next_world(r, worlds[-1], "overlay")
        worlds.append(w)
        steps.append((kind, w))
    return first, steps


def unregistered(ns, res, docs=()):
    rows = [h["detail"] for h in ns["history"] if h["op"] == migrate.OP]
    rows += res.get("version_migrations") or []
    rows += [m for d in docs for m in d.get("ref_migrations") or []]
    return [p for r in rows for p in r.get("unregistered") or []]


def same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def run(seeds, judge, after_step=None):
    """after_step(seed, i, ns2, track, truth2) -> ns2: 판 이전마다 되돌리기 점검 전에 집합을 더 고치는 갈고리(test_study_discard_fuzz)."""
    for seed in seeds:
        r = random.Random(seed)
        project_mode = r.random() < 0.3
        first, steps = plan_chain(r, project_mode)
        stage = "만들기"
        track = Track(judge, seed)
        try:
            g = build_any(first)
            truth = Truth(g)
            track.see(truth)
            ns, form = make_set(r, g)
            stale = stale_targets(first, g)
            res = make_results(r, ns, g, stale)
            judge.stats["집합 꼴 " + form] += 1
            judge.stats["사슬 " + ("프로젝트 그래프" if project_mode else "도면 " + first["fmt"])] += 1
            for kind, w in steps:
                sheets = w["sheets"].values() if "sheets" in w else [w]
                for e in [e for s in sheets for e in s.get("split_events") or ()] if kind in ("mutate", "redo", "unsplit") else ():
                    judge.stats["나누기 연산 " + e] += 1
            track.adopt_set(ns, truth)
            live_slots = {}
            track.adopt_results(live_slots, res, truth)
            docs, doc_slots_ = {}, {}
            old_docs = {}  # 판 표지가 없는 옛 문서: 사슬 끝에 한 번 따라간다
            for kind in DOC_KINDS:
                docs[kind] = make_doc(r, kind, g)
                if r.random() < 0.3:  # 집합을 읽지 않고 그래프만 보고 쓴 문서(③을 ④보다 먼저): 쓸 때 그래프 판을 표지로
                    docs[kind] = follow.mark_for(docs[kind], g["graph_id"], g["graph_version"])
                    judge.stats["그래프 판으로 표지를 찍은 문서"] += 1
                else:
                    docs[kind] = follow.follow(docs[kind], kind, ns, at="c00a")[0]
                doc_slots_[kind] = {}
                track.adopt_results(doc_slots_[kind], docs[kind], truth, kind)
                old_docs[kind] = (make_doc(r, kind, g), {})
                track.adopt_results(old_docs[kind][1], old_docs[kind][0], truth, kind)
            mixed = r.random() < 0.3  # 옛 문서를 사슬 가운데에 고침(그 시각 사이에 판 이전이 낌)
            late = None
            seen = {g["graph_version"]}
            backups, restored = [(copy.deepcopy(ns), g, truth)], False
            for i, (kind, world) in enumerate(steps, 1):
                g2 = build_any(world)
                if g2["graph_version"] == ns["graph_version"]:
                    continue
                truth2 = Truth(g2)
                stage = "옛 꼴 %d" % i
                if r.random() < 0.1:  # 앞 판 이전 줄이 옛 꼴(kept_*·step·unnamed_refs 없음, cff108c~M2)
                    judge.stats["옛 꼴 이력 줄"] += 1
                    ns = copy.deepcopy(ns)
                    for h in ns["history"]:
                        if h.get("op") == migrate.OP:
                            for k in ("kept_eids", "kept_refs", "step", "unnamed_refs"):
                                h["detail"].pop(k, None)
                if late is None and r.random() < 0.1 and res.get("version_migrations"):
                    judge.stats["결과 줄 번호 없음"] += 1
                    res = copy.deepcopy(res)
                    for m in res["version_migrations"]:
                        m.pop("step", None)
                stage = "판 이전 %d(%s)" % (i, kind)
                ns2, p = migrate.migrate_set(ns, g2, at="c%02d" % i)
                if p["state"] != "kept":
                    judge.note("⑤ 판이 다른데 판 이전을 하지 않음", (seed, i, p["state"]))
                    break
                judge.stats["판 이전"] += 1
                judge.stats["다시 추출 " + kind] += 1
                if g2["graph_version"] in seen:
                    judge.stats["앞 판으로 되돌아감"] += 1
                track.check_set(ns, ns2, truth, truth2)
                if kind == "overlay":   # ⑦ 대신 ⑬: 사람 고침은 표시를 바꾸지만 기준 추출이 같으면 순번 구성요소를 잃지 않는다
                    track.check_overlay(ns, ns2, g2, truth, truth2)
                else:
                    track.check_seq_look(ns2, g, g2)
                if kind in ("reorder", "restamp", "recategorize") and not restored:  # 되돌린 집합에는 앞 세계가 다르다
                    track.check_same_content(ns, ns2, p, g)
                stage = "두 번 적용 %d" % i
                if not same(migrate.migrate_set(copy.deepcopy(ns), g2, at="c%02d" % i)[0], ns2):
                    judge.note("④ 같은 판 이전을 두 번 하면 다름", (seed, i))
                if migrate.migrate_set(ns2, g2, at="c%02d" % i)[0] is not ns2:
                    judge.note("④ 같은 판에서 다시 바꿈", (seed, i))
                stage = "결과 %d" % i
                if late is None and r.random() < 0.3:  # 이 판 이전부터 결과 저장이 실패해 늦게 따라옴
                    late = (copy.deepcopy(res), copy.deepcopy(live_slots))
                if r.random() < 0.2:
                    judge.stats["결과가 이번 판 이전을 건너뜀"] += 1
                else:
                    moved, _ = migrate.migrate_results(res, ns2, at="t%d" % i, table=p["table"])
                    by_history, _ = migrate.migrate_results(res, ns2, at="t%d" % i)
                    if not same(moved, by_history):
                        judge.note("④ 즉시 옮긴 결과와 이력으로 옮긴 결과가 다름", (seed, i))
                    res = moved
                    track.see(truth)
                    track.check_results(live_slots, res, truth2, "따라감")
                    if not same(migrate.migrate_results(res, ns2, at="again")[0], res):
                        judge.note("④ 판이 같은 결과를 다시 옮김", (seed, i))
                stage = "문서 %d" % i
                for kind in DOC_KINDS:
                    m = (docs[kind].get("ref_versions") or {}).get(ns2["graph_id"]) or {}
                    if m.get("graph_version") not in (None, g2["graph_version"]):  # 판 이전 전에 새 판 그래프로 쓰려 함
                        try:
                            follow.mark_for(docs[kind], ns2["graph_id"], g2["graph_version"])
                            judge.note("④ 옛 표지 아래 새 판 참조를 씀", (seed, i, kind))
                        except follow.Stale:
                            judge.stats["옛 표지 아래 새 판 쓰기를 거절함"] += 1
                    if r.random() < 0.2:
                        judge.stats["문서가 이번 판 이전을 건너뜀"] += 1
                        continue
                    moved, _rep = follow.follow(docs[kind], kind, ns2, at="c%02da" % i)
                    if follow.follow(moved, kind, ns2, at="again")[0] is not moved:
                        judge.note("④ 판이 같은 문서를 다시 옮김", (seed, i, kind))
                    docs[kind] = moved
                    judge.stats["문서 따라감"] += 1
                    track.check_results(doc_slots_[kind], moved, truth2, "문서 " + kind, kind)
                if mixed and i == 1:  # 옛 문서에 첫 판 이전 뒤 시각의 기록이 더해짐(참조는 그대로)
                    for kind, (d, _s) in old_docs.items():
                        if kind == idmap.LATENT:
                            for rec in d["judgements"].values():
                                rec["history"].append({"at": "c01a"})
                        else:
                            d["history"].append({"at": "c01a", "op": "edit"})
                if after_step is not None:
                    stage = "갈고리 %d" % i
                    ns2 = after_step(seed, i, ns2, track, truth2)
                stage = "되돌리기 %d" % i
                undo_check(track, ns2, truth2)
                track.see(truth2)
                if g2["graph_version"] in seen and res["graph_version"] == g2["graph_version"]:
                    judge.stats["되돌아온 판에서 새로 단 참조"] += 1
                    ids_ = [n["entity_id"] for n in g2["nodes"]]
                    res["cells"].append({"node_id": "S1", "entries": [make_entry(r, g2, r.sample(ids_, min(3, len(ids_))), None)]})
                    track.adopt_results(live_slots, res, truth2)
                    if (docs[idmap.IE].get("ref_versions") or {}).get(ns2["graph_id"], {}).get("graph_version") == g2["graph_version"]:
                        judge.stats["되돌아온 판에서 새로 단 문서 참조"] += 1
                        docs[idmap.IE]["headings"]["H-9%d" % i] = {"targets": [idmap.ref_of(n, g2["graph_id"]) for n in g2["nodes"]
                                                                            if idmap.ref_of(n, g2["graph_id"])][:2]}
                        track.adopt_results(doc_slots_[idmap.IE], docs[idmap.IE], truth2, idmap.IE)
                    ns2 = copy.deepcopy(ns2)
                    ns2["nodes"].append(dict({"node_id": "S9%d" % i, "name": "new", "basis": "b",
                                              "members": sorted(r.sample(ids_, min(2, len(ids_))))},
                                             **sn._v2_fields("script")))
                    track.adopt_set(ns2, truth2)
                if late is None and res["graph_version"] == g2["graph_version"] and r.random() < 0.25:
                    judge.stats["구간을 새로 제안"] += 1  # 옛 집합의 묘비를 모르는 새 집합
                    ns2, _ = make_set(r, g2, "new", at="c%02db" % i)
                    track.sets = {}
                    track.adopt_set(ns2, truth2)
                seen.add(g2["graph_version"])
                backups.append((copy.deepcopy(ns2), g2, truth2))
                restored = len(backups) > 2 and r.random() < 0.15
                if restored:  # 집합 파일만 앞 판 백업으로 되돌림(결과는 그대로)
                    judge.stats["집합을 백업으로 되돌림"] += 1
                    ns2, g2, truth2 = copy.deepcopy(r.choice(backups[:-1]))
                    track.sets = {}
                    track.adopt_set(ns2, truth2)
                ns, g, truth = ns2, g2, truth2
            stage = "늦게 따라옴"
            if res["graph_version"] != ns["graph_version"]:
                res, _ = migrate.migrate_results(res, ns, at="end")
                track.check_results(live_slots, res, truth, "마지막에 따라감")
            if late is not None:
                judge.stats["늦게 따라온 결과"] += 1
                moved, _ = migrate.migrate_results(late[0], ns, at="late")
                track.check_results(late[1], moved, truth, "늦게 따라옴")
            stage = "문서 늦게 따라옴"
            for kind in DOC_KINDS:
                moved, rep = follow.follow(docs[kind], kind, ns, at="end")
                track.check_results(doc_slots_[kind], moved, truth, "문서 마지막에 따라감", kind)
                docs[kind] = moved
                d, slots = old_docs[kind]
                moved, rep = follow.follow(d, kind, ns, at="end")
                judge.stats["표지 없는 옛 문서 " + ("묘비(증명 못 함)" if rep and rep.get("unproven") else "옮김")] += 1
                track.check_results(slots, moved, truth, "표지 없는 옛 문서", kind)
                old_docs[kind] = (moved, slots)
            stage = "형식 검사"
            sn._check_shape(json.loads(json.dumps(ns)), "x")
            for p in unregistered(ns, res, list(docs.values()) + [d for d, _s in old_docs.values()]):
                judge.note("⑥ 등록되지 않은 자리의 옛 id", (seed, p))
        except Exception as exc:  # noqa: BLE001  예외 자체가 불변식 ⑤ 위반이다
            tb = traceback.extract_tb(exc.__traceback__)[-1]
            judge.note("⑤ 예외 %s: %s (%s:%d)" % (stage, type(exc).__name__, os.path.basename(tb.filename), tb.lineno),
                       (seed, str(exc)[:120]))
    return judge


def failures(judge):
    return {k: v for k, v in judge.stats.items() if k[0] in "①②③④⑤⑥⑦⑧⑬"}


def report(judge):
    lines = []
    for k, v in sorted(judge.stats.items()):
        lines.append("%6d  %s" % (v, k))
        lines += ["          %s" % (ex,) for ex in judge.examples.get(k, [])]
    return "\n".join(lines)


class MigrateFuzzTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {paths.ENV_WORK_ROOT: self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_invariants_hold_over_chains_of_reextractions(self):
        judge = run(range(SEEDS), Judge())
        s = judge.stats
        self.assertGreater(s["판 이전"], 3 * SEEDS, "판 이전을 사슬로 실제로 돌림")
        self.assertGreater(s["문서 따라감"], 6 * SEEDS, "프로젝트 문서를 실제로 따라감")
        self.assertGreater(s["앞 판으로 되돌아감"], SEEDS // 4, "앞 판으로 되돌아가는 사슬을 실제로 돌림")
        self.assertGreater(s["사슬 프로젝트 그래프"], SEEDS // 5, "프로젝트 그래프를 실제로 돌림")
        for k in ("다시 추출 overlay", "덧바르는 사람 고침(기준 같음)", "다시 추출 reorder", "다시 추출 restamp", "다시 추출 recategorize", "되돌림", "되찾은 묘비", "늦게 따라온 결과",
                  "되돌아온 판에서 새로 단 참조", "결과가 이번 판 이전을 건너뜀", "구간을 새로 제안", "옛 꼴 이력 줄",
                  "결과 줄 번호 없음", "집합을 백업으로 되돌림", "문서가 이번 판 이전을 건너뜀",
                  "되돌아온 판에서 새로 단 문서 참조", "표지 없는 옛 문서 옮김", "표지 없는 옛 문서 묘비(증명 못 함)",
                  "그래프 판으로 표지를 찍은 문서", "옛 표지 아래 새 판 쓰기를 거절함", "나누기 연산 split",
                  "나누기 연산 unsplit", "같은 source id로 되찾은 묘비"):
            self.assertGreater(s[k], SEEDS // 20, k)
        for k in ("나누기 연산 redo", "나누기 연산 redo_other"):  # 나누고 되돌린 뒤 차례가 더 남은 사슬에서만 난다
            self.assertGreater(s[k], SEEDS // 40, k)
        for form in ("new", "a", "b"):
            self.assertGreater(s["집합 꼴 " + form], SEEDS // 10)
        self.assertEqual(failures(judge), {}, report(judge))


if __name__ == "__main__":
    print(report(run(range(int(sys.argv[1]) if len(sys.argv) > 1 else SEEDS), Judge())))
