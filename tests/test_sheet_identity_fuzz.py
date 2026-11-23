"""시트 정체 불변식 퍼즈(U3). 실제 엔진(등록·추출·프로젝트 그래프·표제란 확정·고르기·정착·검토구간 판 이전)을 임시 작업 루트에서
돌리며, 도면 원본을 등록하고(번호 없음·번호 있음·여러 쪽·같은 번호의 다른 형식·다른 파일) 구간·⑥ 초기사건·FMEA·잠재 후보 판단·도면 연결
지정·구간 제외 표시·지식그래프 판단을 만들고, 번호를 확정·취소·바꾸고 파일을 고르고 다시 추출하고 쓰기 중간에 끊는 사슬을 섞는다.
근거: docs/units/2026-11-13-drawing-knowledge/evidence/sheet-identity-design.md §7·§11, sheet-rename-design.md §5.

판정은 코드가 쓴 기록(묘비 기록·판 이전 줄·자리 표)이 아니라 생성기가 들고 다니는 '진짜 정체'로 한다. 구성요소의 진짜 정체는
(자료, 쪽, 원본 안의 기호 id)다. 같은 원본은 같은 기호를 낳으므로(추출은 결정적), 구간·⑥ 참조가 가리키는 기호가 만든 때와 다르면
다른 도면으로 이은 것이다. 시트 이름의 정답은 설계의 이름 규칙(번호가 있으면 graph-<번호>, 없으면 graph-<자료>-p<쪽>, 정착 전에 보이던
옛 이름은 그대로)을 생성기가 따로 셈한 값이다.

불변식(위반 이름의 첫 글자)
V1 시트 유일: 프로젝트 그래프의 시트는 (자료, 쪽)마다 하나이고, 이름은 설계 규칙의 이름과 같다. 추출한 (자료, 쪽)이 시트로 없으면 같은
   이름을 다른 자료가 쓰는 것이고 고르기 줄에 올라 있다(고르기 줄 = 같은 이름을 원하는 자료가 둘 이상인 이름).
V2 등록 단조: 새 자료를 넣거나(번호가 겹쳐도) 보류해도 있던 시트의 이름·주인이 안 바뀌고 깨끗한 구간의 구성요소가 안 사라진다.
V3 다시 추출 불변: 같은 원본을 다시 추출해도 시트 이름·주인과 구간이 그대로다.
V4 정착 멱등: 정착 전 프로젝트의 정착은 보이던 시트의 이름·구간을 바꾸지 않고, 두 번째는 아무것도 바꾸지 않는다.
V5 다른 도면으로 안 이음: 구간·⑥ 참조가 가리키는 기호의 진짜 정체는 처음과 같다. 살아 있는 구성요소가 없는 id를 가리키지 않고, 구간의
   (구성요소 + 찾지 못한 구성요소) 수가 그대로다.
V6 가드 건전: 허락한 번호 바꿈은 그 도면을 가리키던 사람 기록을 끊지 않고(옮기지 못하는 기록은 막아야 했다), 거절은 막을 것이 실제로
   있을 때만이며 사유 코드·글이 있고 글에 임시 이름이 없으며, 글대로 하면(기록을 정리하거나 도면 변경을 반영하면) 다시 허락한다.
   dry는 아무것도 쓰지 않고 실제와 같은 결론이다.
V7 이름 바뀜 보존: 깨끗한 구간의 구성요소는 허락한 확정·취소·번호 바꿈 뒤에도 모두 살아 있고 확정이 그대로다. 되돌리기로 돌아온
   구성요소도 새 이름의 같은 기호다. ⑥ 문서의 참조도 같다.
V8 자료를 넘지 않음: 이름 바뀜·고르기·등록으로 옮긴 참조가 다른 자료의 기호를 가리키지 않는다(V5의 확장, 같은 id가 겹친 다른 파일 포함).
V9 합쳐도 같음: 같은 연산열을 연산마다 판 이전하며 돌린 끝과, 판 이전을 미루고 한 번에 합쳐 돌린 끝이 같다.
V10 끊김 수렴: 쓰기 직전·직후에 끊기거나 다시 추출이 실패해도 다시 읽으면(같은 확정을 다시 하면) 끊기지 않은 흐름과 같은 끝이고, 그
   중간에 화면이 읽어도 틀린 대상이 보이지 않는다.
X  예외: 연산이 예상 밖 예외를 올리지 않는다.

'깨끗한 구간'은 만든 뒤 사람이 파일을 바꿔 고른 적(고르기)이 없고 정착 전에 가려진 시트에 걸치지 않았으며 쓰는 중에 프로세스가 죽은 적(끊김 ③)이
없는 구간이다. 깨끗한 구간은 어느 연산 뒤에도 구성요소가 진짜 정체대로 모두 살아 있어야 한다. 깨끗하지 않은 구간은 V5(다른 도면으로 안 이음)와
구성요소 수 보존만 본다.

시드 수는 HAZOP_FUZZ_SEEDS(기본 SEEDS), 시작 시드는 HAZOP_FUZZ_FIRST로 정한다. 위반 시드는 두 값을 1과 그 시드로 두면 다시 돌릴 수 있다.
실행: python -m unittest tests.test_sheet_identity_fuzz
"""

import collections
import contextlib
import copy
import json
import os
import random
import re
import shutil
import sys
import tempfile
import time
import traceback
import unittest
from unittest import mock

import pypdfium2 as pdfium

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from tests.test_titleblock import BY, P, sample  # noqa: E402

from hazop import paths, store_io  # noqa: E402
from hazop.app import data, project_ctx  # noqa: E402
from hazop.graph import project, sheets as sheet_rules, sources  # noqa: E402
from hazop.ie import fmea, model, store as ie_store  # noqa: E402
from hazop.kg import expect, link  # noqa: E402
from hazop.register import registry, titleblock as tb  # noqa: E402
from hazop.study import follow, idmap, migrate, node_commands, nodes  # noqa: E402

SEEDS = int(os.environ.get("HAZOP_FUZZ_SEEDS") or 10)
FIRST = int(os.environ.get("HAZOP_FUZZ_FIRST") or 0)
STEPS = int(os.environ.get("HAZOP_FUZZ_STEPS") or 14)
COMPOSE = int(os.environ.get("HAZOP_FUZZ_COMPOSE") or 3)
NUMBERS = ["SNP-M-101", "SNP-M-102", "SNP-M-555"]
KNOWN_E4 = "알려진 결함 E4: 문서의 판 이전 기록에 남은 옛 값을 가드가 지금 참조로 셈"
RESERVED = "material-0123456789ab-p0"   # 임시 이름과 같은 꼴이라 번호로 쓸 수 없다
APPLY_TEXT = "도면 변경 반영하기"
TEMP_NAME = re.compile(r"material-[0-9a-f]{12}|graph-material|-p\d+\b")
KNOWN_CODES = {tb.HAS_RECORDS, sheet_rules.CONFIRM_FIRST, sheet_rules.NUMBER_HELD, sheet_rules.NUMBER_RESERVED, tb.CHOICE_PINNED,
               tb.NUMBER_TAKEN}

# 원본 꼴. 같은 번호의 다른 형식(d101·p101), 같은 번호의 다른 파일(p101·p102를 같은 번호로 확정), 파일 id가 겹치는 다른 drawio(d101·d102·dx),
# 여러 쪽 PDF(mp)가 모두 나온다.
SOURCES = {"d101": ("SNP-M-101", "drawio"), "d102": ("SNP-M-102", "drawio"), "dx": ("SNP-M-102", "drawio"),
           "p101": ("SNP-M-101", "pdf"), "p102": ("SNP-M-102", "pdf"), "p201": ("SNP-M-201", "pdf"), "mp": ("SNP-M-101", "pdf")}


class Violation(AssertionError):
    def __init__(self, code, text):
        AssertionError.__init__(self, "%s %s" % (code, text))
        self.code = code


def fail(code, text):
    raise Violation(code, text)


def temp_name(mid, page=0):
    return "graph-%s-p%d" % (mid, page)


def legacy_name(_project_id, extraction, **_kw):
    """이 단위 전의 이름 규칙(정착 전 앱이 쓰던 것)."""
    return "graph-%s" % ((extraction.get("drawing") or {}).get("drawing_number")
                         or (extraction.get("source_context") or {}).get("page_name") or "drawing")


class Snap:
    """한 시점의 관측: 프로젝트 그래프의 시트·구성요소와 저장된 구간(읽어서 판 이전을 마친 것)."""

    def __init__(self, pg, ns, conflicts):
        self.pg = pg
        self.idx = {n["entity_id"]: n for n in pg["nodes"]}
        self.sheets = {s["graph_id"]: s for s in pg["sheets"]}
        self.owner = {g: (s["material_id"], s.get("page_index") or 0) for g, s in self.sheets.items()}
        self.ns = ns
        self.conflicts = conflicts
        self.current = bool(ns) and ns.get("graph_version") == pg.get("graph_version")
        self.segs = {}
        for n in (ns or {}).get("nodes") or []:
            members = list(n.get("members") or [])
            self.segs[n["node_id"]] = {"members": members, "lost": len(n.get("lost") or []), "state": nodes.node_state(n),
                                       "syms": [self.sym(m) for m in members]}

    def sym(self, eid):
        n = self.idx.get(eid)
        s = self.sheets.get(n["sheet"]) if n else None
        if s is None:
            return None
        return (s["material_id"], s.get("page_index") or 0, n.get("source_object_id") or n.get("local_id"))

    def ref_sym(self, ref):
        """'<시트>#<기호 id>' 참조가 가리키는 기호의 정체. 묘비·모르는 시트면 None."""
        gid, sep, soid = (ref or "").partition("#")
        o = self.owner.get(gid)
        return (o[0], o[1], soid) if sep and o else None


KNOWN_DEFECTS = False   # E1·E2(고치는 중)이 퍼즈에 나타나면 위반으로 세지 않고 따로 센다. 고침이 들어오면 False로 바꾼다(docs: u3/PROGRESS.md)


# 총괄이 알고 있는 가드 결함(611afc1부터, 다음 '파일 고르기 기록 가드' 단위에서 고침). 시드마다 위반 코드가 같을 때만 따로 센다
KNOWN_SEEDS = {155: ("V6", "choose가 낀 흐름에서 가드가 거절·허락하는 기록 셈이 고른 파일 쪽 이름과 어긋남(새 번호를 가리키는 옛 기록으로 거절)"),
               214: ("V6", "choose가 낀 흐름에서 가드가 옮길 구간을 0개로 알림(고른 파일의 이름을 옛 주인 기준으로 셈)"),
               246: ("V6", "214와 같은 꼴: 옛 자리 주인을 고르기로 다시 고른 뒤 가드가 옮길 구간을 0개로 알림")}


def known_defect(w, exc):
    """알려진 결함(E1: 낡은 in_use 자리, E2: 옛 자리 주인을 고르기로 다시 고름)의 꼴이면 그 이름, 아니면 None."""
    if w.seed in KNOWN_SEEDS and KNOWN_SEEDS[w.seed][0] == exc.code:
        return "시드%d" % w.seed
    if not KNOWN_DEFECTS:
        return None
    if exc.code in ("E1", "E5"):
        return exc.code
    if w.known == "E2" and exc.code in ("V1", "V2", "V3", "V6", "V7", "V8"):
        return "E2"
    return None


class World:
    """한 시드의 프로젝트. 생성기가 '진짜 정체'와 설계 규칙의 이름을 따로 들고 있다."""

    def __init__(self, seed, tmp):
        self.seed, self.tmp = seed, tmp
        self.rng = random.Random(seed)
        self.files = {}
        self.mats = {}        # 원본 이름 -> {"mid", "number", "pages", "extracted"}
        self.segs = {}        # node_id -> {"truth": {정체}, "clean": 깨끗한가, "state": 기대 확정 상태, "n": 구성요소 수}
        self.order = []       # 등록 차례(자료 id)
        self.removed = []     # 지운 구간의 되돌리기 묶음
        self.blockers = []    # 옮기지 못하는 기록(도면 연결·구간 제외·지식그래프 판단): {kind, gid, owner, ...}
        self.docs = []        # ⑥ 문서에 둔 참조: {kind, key, node_id, truth}
        self.link_ops = []
        self.kg_rows = {}
        self.trace = []
        self.settled = True
        self.legacy_gid = {}
        self.moved = False
        self.known = None
        self.chosen = {}      # 사람이 고른 파일: 시트 이름 -> 자료
        self.unpinned = set()
        self.ended = False
        self.pre_extracted = set()
        self.settled_at_entry = True
        self.last_links = frozenset()
        self.stats = collections.Counter()

    # ---------------------------------------------------------------- 파일
    def file(self, key):
        if key in self.files:
            return self.files[key]
        drawing, ext = SOURCES[key]
        src = sample(drawing, ext)
        folder = os.path.join(self.tmp, "in", key)
        dst = os.path.join(folder, os.path.basename(src))
        if key == "mp":
            os.makedirs(folder)
            doc = pdfium.PdfDocument.new()
            for d in ("SNP-M-101", "SNP-M-102"):
                doc.import_pages(pdfium.PdfDocument(sample(d, "pdf")))
            dst = os.path.join(folder, "two.pdf")
            doc.save(dst)
        elif ext == "drawio":
            shutil.copytree(os.path.dirname(src), folder)
            if key == "dx":   # 쪽 이름이 101인 102 도면(파일 id가 102와 같다)
                with open(dst, encoding="utf-8") as fh:
                    text = fh.read()
                with open(dst, "w", encoding="utf-8") as fh:
                    fh.write(text.replace('name="SNP-M-102"', 'name="SNP-M-101"', 1))
        else:
            os.makedirs(folder)
            shutil.copy(src, dst)
        self.files[key] = dst
        return dst

    def log(self, text):
        self.trace.append(text)

    # ---------------------------------------------------------------- 이름 규칙(설계에서 따로 셈한 정답)
    def predicted(self, key, page):
        m = self.mats[key]
        if m["number"] and m["pages"] == 1:
            return "graph-" + m["number"]
        return self.legacy_gid.get((m["mid"], page)) or temp_name(m["mid"], page)

    def claimants(self):
        out = collections.defaultdict(list)
        for key, m in self.mats.items():
            if m["extracted"]:
                for p in range(m["pages"]):
                    out[self.predicted(key, p)].append((m["mid"], p))
        return out

    def key_of(self, mid):
        return next(k for k, m in self.mats.items() if m["mid"] == mid)

    # ---------------------------------------------------------------- 관측
    def snapshot(self, read=True):
        try:
            pg = project_ctx.project_graph(P)
        except ValueError:   # 추출한 도면이 아직 없음
            return Snap({"nodes": [], "sheets": [], "graph_version": None}, None, [])
        ns = nodes.load(pg) if read else None
        try:
            conflicts = sources.conflicts(P)
        except (OSError, ValueError):
            conflicts = None
        return Snap(pg, ns, conflicts)

    def work_files(self):
        out = {}
        for d, _dirs, names in os.walk(os.environ["HAZOP_WORK_ROOT"]):
            for n in names:
                f = os.path.join(d, n)
                st = os.stat(f)
                out[f] = (st.st_size, st.st_mtime_ns)
        return out

    def refresh_settled(self):
        self.settled = bool(sources.load_seats(P)[1])

    # ---------------------------------------------------------------- 연산
    def register(self, key, number=None, extract=True):
        src = self.file(key)
        m = self.mats.get(key)
        meta = {"drawing_number": number, "by": BY, "reason": "명령줄 등록"} if number else None
        self.log("register %s number=%s extract=%s" % (key, number, extract))
        res = registry.register(src, P, "P&ID", paths.store_root(), meta, BY)
        pages = 2 if key == "mp" else 1
        if number == RESERVED:
            want = "on_hold"
        elif m is None:
            want = "on_hold" if number and pages > 1 else "registered"
        else:
            want = "reused" if number in (None, m["number"]) else "on_hold"
        if res["outcome"] != want:
            fail("X", "등록 결과가 %s여야 하는데 %s(%s)" % (want, res["outcome"], res.get("notes")))
        if res["outcome"] == "on_hold":
            codes = {b.get("check") for b in (res["record"].get("validation") or {}).get("blockers") or []}
            if not codes or not codes <= {sheet_rules.CONFIRM_FIRST, sheet_rules.NUMBER_HELD, sheet_rules.NUMBER_RESERVED}:
                fail("V6", "보류에 사유 코드가 없거나 모름: %s" % codes)
            if m is not None and res.get("registration_file"):
                fail("V6", "보류가 등록정보 경로를 돌려줌")
            self.stats["held"] += 1
            return
        if m is None:
            mid = res["record"]["material_id"]
            self.mats[key] = m = {"mid": mid, "number": number, "pages": pages, "extracted": False}
            self.order.append(mid)
        if extract and res.get("registration_file"):
            self.extract_file(key, res["registration_file"])

    def extract_file(self, key, registration_file=None):
        m = self.mats[key]
        if registration_file is None:
            rec, _p = registry.latest(P, m["mid"])
            registration_file = registry.Store(paths.store_root(), P).snapshot_path(m["mid"], rec["registration_version"])
        data.extract_and_graph(registration_file)
        m["extracted"] = True

    def visible(self, snap=None):
        """지금 프로젝트 그래프에 보이는 시트가 있는 원본 이름."""
        snap = snap or self.snapshot(read=False)
        have = {o[0] for o in snap.owner.values()}
        return [k for k, m in self.mats.items() if m["mid"] in have]

    def seg_new(self, key):
        m = self.mats[key]
        snap = self.snapshot()
        gids = [g for g, o in snap.owner.items() if o[0] == m["mid"]]
        if not gids:
            return False
        picked, gid_log = [], []
        for gid in [self.rng.choice(gids)] + ([self.rng.choice(list(snap.owner))] if self.rng.random() < 0.25 else []):
            pool = [n for n in snap.pg["nodes"] if n["sheet"] == gid and n.get("local_id") and n["entity_id"] not in picked]
            if len(pool) < 3 and not picked:
                return False
            picked += [n["entity_id"] for n in self.rng.sample(pool, min(len(pool), self.rng.randint(3, 6)))]
            gid_log.append(gid)
        cur = nodes.load(snap.pg)
        before = {n["node_id"] for n in (cur or {}).get("nodes") or []}
        out = node_commands.execute(snap.pg, "create", {"items": [{"members": picked, "name": "S-%d" % len(picked), "basis": "퍼즈"}]},
                                    author="user", confirmed_by=BY, set_rev=(cur or {}).get("set_rev") or 0)
        if not out["ok"]:
            fail("X", "구간 만들기가 거절됨: %s" % out.get("refused"))
        made = [n for n in nodes.load(snap.pg)["nodes"] if n["node_id"] not in before]
        for n in made:
            truth = {snap.sym(e) for e in n["members"]}
            hidden_before = not self.settled and any((s[0], s[1]) in self.hidden_legacy for s in truth)
            self.segs[n["node_id"]] = {"truth": truth, "clean": not hidden_before, "state": nodes.node_state(n), "n": len(n["members"])}
        self.log("seg_new %s %s -> %s" % (key, gid_log, [n["node_id"] for n in made]))
        return True

    hidden_legacy = frozenset()

    def node_cmd(self, name, args):
        snap = self.snapshot()
        cur = nodes.load(snap.pg)
        return node_commands.execute(snap.pg, name, args, author="user", confirmed_by=BY, set_rev=(cur or {}).get("set_rev") or 0)

    def seg_remove(self):
        snap = self.snapshot()
        live = [n for n in (snap.ns or {}).get("nodes") or [] if n["node_id"] in self.segs]
        if not live:
            return False
        n = self.rng.choice(live)
        out = self.node_cmd("remove", {"node_id": n["node_id"]})
        self.log("seg_remove %s ok=%s" % (n["node_id"], out["ok"]))
        if out["ok"] and out.get("batch_id"):
            self.removed.append((out["batch_id"], n["node_id"]))
        return True

    def seg_undo(self):
        if not self.removed:
            return False
        batch, nid = self.removed.pop()
        here = set(self.snapshot(read=False).owner.values())
        if any((x[0], x[1]) not in here for x in self.segs[nid]["truth"]):
            self.segs[nid]["clean"] = False   # 지운 구간은 가드가 지키지 않는다(U2 판단): 그사이 그 시트가 번호를 다른 파일에 내줘 가려졌으면 되돌려도 구성요소는 묘비다
            self.stats["undo_after_sheet_hidden"] += 1
        out = self.node_cmd("undo", {"batch_id": batch})
        self.log("seg_undo %s ok=%s" % (batch, out["ok"]))
        if out["ok"]:
            snap = self.snapshot()
            for n in (snap.ns or {}).get("nodes") or []:
                if n["node_id"] in self.segs:
                    self.segs[n["node_id"]]["state"] = nodes.node_state(n)
        return True

    def seg_confirm(self):
        snap = self.snapshot()
        live = [n for n in (snap.ns or {}).get("nodes") or [] if n["node_id"] in self.segs and nodes.node_state(n) == "applied"]
        if not live:
            return False
        n = self.rng.choice(live)
        out = self.node_cmd("confirm", {"node_ids": [n["node_id"]]})
        self.log("seg_confirm %s ok=%s" % (n["node_id"], out["ok"]))
        if out["ok"]:
            self.segs[n["node_id"]]["state"] = "confirmed"
        return True

    # ---------------------------------------------------------------- 사람 기록(옮기는 것: ⑥ 문서 / 옮기지 못하는 것: 연결·제외·지식그래프 판단)
    def doc_new(self):
        snap = self.snapshot()
        cands = [(nid, s) for nid, s in snap.segs.items() if nid in self.segs and s["members"]]
        if not cands or not snap.current:
            return False
        nid, s = self.rng.choice(cands)
        i = self.rng.randrange(len(s["members"]))
        member, ref = s["members"][i], snap.ns["graph_member_refs"].get(s["members"][i])
        if not ref:
            return False
        kind = self.rng.choice([idmap.IE, idmap.FMEA, idmap.LATENT])
        mark = {snap.ns["graph_id"]: {"graph_version": snap.ns["graph_version"], "step": len(migrate.lines(snap.ns))}}
        path = {idmap.IE: ie_store.store_path(P), idmap.FMEA: ie_store.fmea_path(P), idmap.LATENT: expect.store_path(P)}[kind]
        raw = self.read_doc(path)
        doc = follow.catch_up(raw, kind, P)[0] if raw else {idmap.IE: model.empty, idmap.FMEA: fmea.empty, idmap.LATENT: expect.empty_store}[kind](P)
        n = sum(1 for d in self.docs if d["kind"] == kind) + 1
        k = "k%d" % n
        if kind == idmap.IE:
            doc["counters"]["H"] = n
            doc["headings"]["H-%02d" % n] = {"name": "h", "targets": [ref], "status": "live", "origin": "human"}
            k = "H-%02d" % n
        elif kind == idmap.FMEA:
            doc["counters"]["FM"] = n
            k = "FM-%03d" % n
            doc["rows"][k] = {"status": "imported", "match": "ok", "key": "k%d" % n, "ref": ref, "entity_id": member, "tag": "T"}
        else:
            doc["judgements"]["rule-%s|%s" % (k, ref)] = {"key": "rule-%s|%s" % (k, ref), "target": ref}
        doc["ref_versions"] = mark
        self.write_doc(path, doc)
        self.docs.append({"kind": kind, "key": k, "node_id": nid, "truth": snap.sym(member), "path": path})
        self.log("doc_new %s %s on %s" % (kind, k, nid))
        return True

    def read_doc(self, path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def write_doc(self, path, doc):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)

    def doc_syms(self, snap, d):
        """⑥ 문서의 그 항목이 읽는 길(follow.catch_up)로 지금 가리키는 기호들 [(정체 또는 None, 값)]."""
        doc = self.read_doc(d["path"])
        if doc is None:
            return []
        doc, _r = follow.catch_up(doc, d["kind"], P)
        k = d["key"]
        if d["kind"] == idmap.IE:
            refs = (doc.get("headings", {}).get(k) or {}).get("targets") or []
            return [(snap.ref_sym(r), r) for r in refs]
        if d["kind"] == idmap.FMEA:
            row = (doc.get("rows") or {}).get(k) or {}
            return [(snap.ref_sym(row.get("ref")), row.get("ref")), (snap.sym(row.get("entity_id")), row.get("entity_id"))]
        out = []
        for key in doc.get("judgements") or {}:
            if key.startswith("rule-%s|" % k):
                out.append((snap.ref_sym(key.partition("|")[2]), key))
        return out

    def blocker_new(self):
        snap = self.snapshot()
        kind = self.rng.choice(["excluded", "link", "kg", "kg", "cache"])
        if kind == "cache":   # 채팅 도구의 구간 후보 캐시: 가드가 세지 않는다(지울 화면이 없다)
            ns = snap.ns
            if not ns or not ns["nodes"]:
                return False
            path = os.path.join(nodes.store_dir(), paths.safe_name(P), "candidates", "d%d.json" % (len(self.blockers) + 1))
            self.write_doc(path, {"members": ns["nodes"][0]["members"]})
            self.log("cache 후보")
            return True
        owned = [(g, o) for g, o in snap.owner.items() if self.numbered_owner(g, o)]
        if kind in ("excluded", "link"):
            if not owned or (kind == "link" and len(owned) < 2):
                kind = "kg"
        if kind == "kg":
            gid = self.rng.choice(list(snap.owner)) if snap.owner else None
            if gid is None:
                return False
            row = {c: "" for c in link.CANDIDATE_COLUMNS}
            key = "k%d" % (len(self.blockers) + 1)
            row.update(candidate_key=key, target_graph_id=gid, target_tag="T", target_ref=gid + ":T", link_status="confirmed", reviewed_by=BY)
            self.kg_rows[key] = row
            self.write_kg()
            b = {"kind": "kg", "gid": gid, "owner": snap.owner[gid], "key": key}
        elif kind == "excluded":
            gid, o = self.rng.choice(owned)
            nodes.set_excluded(P, gid[len("graph-"):], True, BY, "범례 도면")
            b = {"kind": "excluded", "gid": gid, "owner": o}
        else:
            (g1, o1), (g2, _o2) = self.rng.sample(owned, 2)
            op = {"op_id": "op-%d" % (len(self.link_ops) + 1), "op": "link", "by": BY, "at": "2026-11-23T00:00:00Z", "reason": "퍼즈",
                  "ends": [{"drawing_number": g1[len("graph-"):], "source_object_id": "n1"},
                           {"drawing_number": g2[len("graph-"):], "source_object_id": "n2"}]}
            self.link_ops.append(op)
            project.save_manual(P, self.link_ops, BY, "2026-11-23T00:00:00Z")
            b = {"kind": "link", "gid": g1, "owner": o1, "op": op, "gid2": g2, "owner2": snap.owner[g2]}
        self.blockers.append(b)
        self.log("blocker_new %s %s" % (b["kind"], b["gid"]))
        return True

    def kg_block(self, gid, owner):
        row = {c: "" for c in link.CANDIDATE_COLUMNS}
        key = "k%d" % (len(self.blockers) + 1)
        row.update(candidate_key=key, target_graph_id=gid, target_tag="T", target_ref=gid + ":T", link_status="confirmed", reviewed_by=BY)
        self.kg_rows[key] = row
        self.write_kg()
        self.blockers.append({"kind": "kg", "gid": gid, "owner": owner, "key": key})

    def numbered_owner(self, gid, o):
        m = next((m for m in self.mats.values() if m["mid"] == o[0]), None)
        return bool(m and m["number"] and m["pages"] == 1 and gid == "graph-" + m["number"])

    def write_kg(self):
        folder = paths.folder("knowledge-graph", paths.safe_name(P, "project"))
        os.makedirs(folder, exist_ok=True)
        link.write_candidates(os.path.join(folder, link.CANDIDATES_CSV), list(self.kg_rows.values()))

    def clear_blocker(self, b):
        if b["kind"] == "excluded":
            nodes.set_excluded(P, b["gid"][len("graph-"):], False, BY)
        elif b["kind"] == "link":
            self.link_ops = [o for o in self.link_ops if o is not b["op"]]
            project.save_manual(P, self.link_ops, BY, "2026-11-23T00:00:00Z")
        else:
            row = self.kg_rows[b["key"]]
            row.update(link_status="candidate", reviewed_by="")
            self.write_kg()
        self.blockers.remove(b)

    # ---------------------------------------------------------------- 번호 바꾸기(표제란 확정·취소)
    def row(self, key):
        return tb.row(P, self.mats[key]["mid"])

    def call(self, key, number, dry=False, extract=None):
        m = self.mats[key]
        ver = self.row(key)["ver"]
        if number is None:
            return tb.unconfirm(P, m["mid"], ["drawing_number"], BY, ver=ver, dry=dry, extract=extract)
        return tb.confirm(P, m["mid"], {"drawing_number": number}, BY, ver=ver, dry=dry, extract=extract)

    def settle(self):
        self.log("settle")
        return data.settle_sheets(P)

    def choose(self, gid, mid):
        self.log("choose %s %s" % (gid, mid))
        snap = self.snapshot(read=False)
        old = snap.owner.get(gid)
        if self.legacy_gid.get((mid, 0)) == gid:
            self.known = "E2"   # 옛 자리 주인을 고르기로 다시 고름
        sources.choose(P, gid, None, BY, material_id=mid)
        self.chosen[gid] = mid
        for k, v in list(self.legacy_gid.items()):
            if v == gid and k[0] != mid:
                self.unpinned.add(k)   # 자리는 이름마다 하나라 다른 파일을 고르면 앞 주인의 옛 이름 붙박기가 풀린다(그 파일을 다시 추출할 때 임시 이름이 됨)
        for s in self.segs.values():
            if any((x[0], x[1]) == old for x in s["truth"]):
                s["clean"] = False
        new = self.snapshot(read=False).owner.get(gid)
        for b in self.blockers:
            if b["gid"] == gid:
                b["owner"] = new
            if b.get("gid2") == gid:
                b["owner2"] = new

    # ---------------------------------------------------------------- 관측 판정
    @staticmethod
    def links_now(snap):
        return frozenset(l["link_id"] for l in snap.pg.get("sheet_links") or [] if l.get("status") == project.LINKED)

    def check(self, snap, op, before=None):
        try:
            self.check_all(snap, op, before)
        finally:
            self.last_links = self.links_now(snap)

    def check_all(self, snap, op, before=None):
        self.refresh_settled()
        for k in list(self.unpinned):
            if snap.owner.get(temp_name(k[0], k[1])) == k:   # 다시 추출해 임시 이름으로 옮겨 감
                self.legacy_gid.pop(k, None)
                self.unpinned.discard(k)
        self.check_sheets(snap, op, before)
        self.check_segs(snap, op)
        self.check_docs(snap, op)
        self.check_blockers(snap, op)

    def check_sheets(self, snap, op, before):
        if len(snap.sheets) != len(snap.pg["sheets"]):
            fail("V1", "%s: 시트 이름이 겹침" % op)
        keys = collections.Counter(snap.owner.values())
        if any(n > 1 for n in keys.values()):
            fail("V1", "%s: (자료, 쪽)이 시트 둘에 들어감: %s" % (op, keys))
        if not self.settled:
            return
        known = {m["mid"]: k for k, m in self.mats.items()}
        claim = self.claimants()
        for gid, (mid, page) in snap.owner.items():
            key = known.get(mid)
            if key is None:
                fail("V1", "%s: 등록하지 않은 자료의 시트 %s" % (op, gid))
            if gid != self.predicted(key, page):
                fail("V1", "%s: 시트 이름 %s가 설계 이름 %s와 다름(%s)" % (op, gid, self.predicted(key, page), key))
        for gid, who in claim.items():
            if gid not in snap.sheets:
                fail("V1", "%s: 추출한 시트 %s가 프로젝트 그래프에 없음(원하는 자료 %s)" % (op, gid, who))
            if snap.owner[gid] not in who:
                fail("V1", "%s: %s의 주인 %s가 그 이름을 원하는 자료가 아님 %s" % (op, gid, snap.owner[gid], who))
            if len({m for m, _p in who}) > 1 and gid not in sources.load_seats(P)[0]:
                first = min((m for m, _p in who), key=self.order.index)   # 자리도 고른 파일도 없으면 먼저 등록한 자료가 쓴다(고르기 차례 4)
                if snap.owner[gid][0] != first:
                    fail("V1", "%s: 자리 없는 시트 %s를 먼저 등록한 자료 %s가 아니라 %s가 씀" % (op, gid, first, snap.owner[gid][0]))
        if snap.conflicts is not None:
            rows = {c["graph_id"]: {x["material_id"] for x in c["candidates"]} for c in snap.conflicts}
            want = {g: {m for m, _p in who} for g, who in claim.items() if len({m for m, _p in who}) > 1}
            if rows != want:
                fail("V1", "%s: 고르기 줄 %s가 같은 이름을 원하는 자료 %s와 다름" % (op, rows, want))
        if before is not None and before.owner:
            for gid, o in before.owner.items():
                if o in claim.get(gid, ()) and snap.owner.get(gid) != o and not op.startswith("choose"):
                    seat = sources.load_seats(P)[0].get(gid) or {}
                    if snap.owner.get(gid) and snap.owner[gid][0] not in self.pre_extracted and op.split()[0] in ("register", "extract"):
                        fail("E5", "%s: 먼저 등록했지만 아직 추출하지 않았던 자료가 추출되며 시트 %s의 주인이 %s에서 %s로 뒤집힘" % (op, gid, o, snap.owner.get(gid)))
                    if seat.get("why") == sheet_rules.IN_USE:
                        fail("E1", "%s: 낡은 in_use 자리 때문에 시트 %s의 주인이 %s에서 %s로 뒤집힘" % (op, gid, o, snap.owner.get(gid)))
                    fail("V3" if op.startswith("extract") else "V2", "%s: 시트 %s의 주인이 %s에서 %s로 바뀜(그 자료가 아직 그 이름을 원함)"
                         % (op, gid, o, snap.owner.get(gid)))

    def check_segs(self, snap, op, loose=False):
        for nid, s in snap.segs.items():
            truth = self.segs.get(nid)
            if truth is None:
                continue
            if len(s["members"]) + s["lost"] != truth["n"]:
                fail("V5", "%s: 구간 %s의 구성요소+찾지 못한 구성요소가 %d개에서 %d개로 바뀜" % (op, nid, truth["n"], len(s["members"]) + s["lost"]))
            if not snap.current:
                continue   # 판 이전 전(중간 상태)은 따로 본다
            for m, sym in zip(s["members"], s["syms"]):
                if sym is None:
                    fail("V5", "%s: 구간 %s의 구성요소 %s가 살아 있는 구성요소가 아님" % (op, nid, m))
                if sym not in truth["truth"]:
                    fail("V8", "%s: 구간 %s의 구성요소 %s가 만들 때와 다른 기호 %s를 가리킴(처음 %s…)" % (op, nid, m, sym, sorted(truth["truth"])[:2]))
            if truth["clean"] and not loose:
                lost = truth["truth"] - set(s["syms"])
                if lost:
                    fail("V7", "%s: 깨끗한 구간 %s가 구성요소 %d개를 잃음(찾지 못함 %d, 예 %s)" % (op, nid, len(lost), s["lost"], sorted(lost)[:2]))
                if truth.pop("exempt", False):
                    truth["state"] = s["state"]      # 끊김 ③ 뒤의 확정은 재확인으로 남을 수 있다(설계 예외)
                if s["state"] == "applied" and truth["state"] == "confirmed" and self.links_now(snap) != self.last_links:
                    truth["state"] = "applied"   # 번호를 확정한 시트가 다른 시트의 연결점과 이어져 구성요소의 연결이 바뀐 재확인(내용이 바뀐 것)
                    self.stats["demoted_by_new_links"] += 1
                if s["state"] != truth["state"]:
                    fail("V7", "%s: 깨끗한 구간 %s의 확정 상태가 %s에서 %s로 바뀜" % (op, nid, truth["state"], s["state"]))

    def check_docs(self, snap, op):
        if not snap.current:
            return
        for d in self.docs:
            clean = self.segs[d["node_id"]]["clean"]
            for sym, value in self.doc_syms(snap, d):
                if sym is None or idmap.is_tomb(value):
                    if clean:
                        fail("V7", "%s: 깨끗한 구간의 %s 문서 참조 %s를 잃음" % (op, d["kind"], value))
                elif sym != d["truth"]:
                    fail("V8", "%s: %s 문서 참조 %s가 만들 때와 다른 기호 %s를 가리킴(처음 %s)" % (op, d["kind"], value, sym, d["truth"]))

    def check_blockers(self, snap, op):
        for b in self.blockers:
            for gid, want in ((b["gid"], b["owner"]), (b.get("gid2"), b.get("owner2"))):
                if gid is not None and snap.owner.get(gid) != want:
                    fail("V6", "%s: 허락한 연산이 %s 기록의 도면 %s를 끊거나 다른 파일로 옮김(처음 %s, 지금 %s)" % (op, b["kind"], gid, want, snap.owner.get(gid)))

    # ---------------------------------------------------------------- 거절의 정당성
    def carriers(self, snap, gid):
        """그 시트를 지금 가리키는 옮길 수 있는 기록(구간 구성원·⑥ 문서)의 수."""
        mine = snap.owner.get(gid)
        n = 0
        for nid, s in snap.segs.items():
            if any(snap.idx.get(m, {}).get("sheet") == gid for m in s["members"]):
                n += 1
            elif s["lost"] and nid in self.segs and any((x[0], x[1]) == mine for x in self.segs[nid]["truth"]):
                n += 1   # 찾지 못한 구성요소가 그 도면을 가리키는 구간도 센다(되찾으면 그 시트로 돌아옴)
        for d in self.docs:
            n += sum(1 for sym, _v in self.doc_syms(snap, d) if sym and snap.owner.get(gid) == (sym[0], sym[1]))
        return n

    def justified(self, key, number, snap, row):
        """거절한 까닭이 생성기의 지식으로 실제 있는가. 있으면 글, 없으면 None."""
        m = self.mats[key]
        old = next((g for g, o in snap.owner.items() if o[0] == m["mid"]), None)
        new = "graph-" + number if number else self.legacy_gid.get((m["mid"], 0)) or temp_name(m["mid"])
        if number is None and not m["number"]:
            return None
        names = {old, new} - {None}
        hit = [b for b in self.blockers if b["gid"] in names or b.get("gid2") in names]
        if hit:
            return "막는 기록 %s" % [b["kind"] for b in hit]
        carry = self.carriers(snap, old) if old else 0
        other = snap.owner.get(new)
        if other and self.chosen.get(new) == m["mid"] and other[0] != m["mid"]:
            return "사람이 고른 파일이 번호를 다시 받으면 주인이 되어 그 이름의 기록이 옮겨 감(number_taken)"
        if carry and other and other != snap.owner.get(old):
            return "새 번호를 다른 파일이 쓰고 이 도면에 구간·문서가 있음"
        if carry and not snap.current:
            return "구간 저장본이 지금 판에 맞춰지지 않음"
        if other is None and (any(s["lost"] for s in snap.segs.values())
                              or any(idmap.is_tomb(v) for d in self.docs for _sym, v in self.doc_syms(snap, d))):
            return "찾지 못한 구성요소·문서 참조가 새 이름을 가리킬 수 있음"
        if other is None and self.log_mentions(new):
            return KNOWN_E4
        return None

    def log_mentions(self, gid):
        """⑥ 문서 파일의 원문에 그 이름의 옛 참조가 글로 남아 있는가(판 이전 기록 ref_migrations의 옛 값, 또는 읽을 때만 옮겨 파일은 고치지 않은 참조).
        읽는 길이 지금 가리키는 값에는 그 이름이 없는 것만 센다(있으면 정말 그 이름을 가리키는 기록이다)."""
        for d in self.docs:
            raw = self.read_doc(d["path"]) or {}
            text = json.dumps(raw, ensure_ascii=False)
            if (gid + "#" in text or gid + "/" in text) and not any(str(v).startswith((gid + "#", gid + "/")) for _s, v in self.doc_syms(self.snapshot(read=False), d)):
                return True
        return False

    def intermediate(self, op, before, ns=None):
        """판 이전 전·쓰기 중간 상태를 화면이 읽어도 틀린 대상이 보이지 않는다: 저장본(또는 읽기가 돌려준 집합)의 구성요소가 지금 그래프에 있으면 만들 때의 기호다."""
        pg = project_ctx.project_graph(P)
        ns = ns if ns is not None else nodes.read_as_is(pg)
        snap = Snap(pg, ns, None)
        now = Snap(pg, None, None)
        for nid, s in snap.segs.items():
            truth = self.segs.get(nid)
            if truth is None:
                continue
            for m, sym in zip(s["members"], s["syms"]):
                gid = m.partition("/")[0]
                if sym is not None and sym not in truth["truth"] and before.owner.get(gid) != now.owner.get(gid):
                    self.stats["stale_name_reused"] += 1   # 한계: 낡음으로 표시된 판 이전 전 저장본의 옛 이름을 같은 판 이전에서 다른 자료가 이어받음
                    continue
                if sym is not None and sym not in truth["truth"]:
                    fail("V10", "%s: 중간 상태에서 구간 %s의 구성요소 %s가 다른 기호 %s를 가리킴" % (op, nid, m, sym))

    @contextlib.contextmanager
    def write_fault(self, when):
        """검토구간 파일 쓰기 직전(before)·직후(after)에 끊긴다."""
        target = os.path.join(nodes.store_dir(), paths.safe_name(P), "project-%s.json" % paths.safe_name(P))
        real = store_io.write_json

        def faulty(path, *a, **k):
            if path != target:
                return real(path, *a, **k)
            if when == "before":
                raise OSError("쓰기 직전 끊김")
            real(path, *a, **k)
            raise OSError("쓰기 직후 끊김")
        with mock.patch.object(store_io, "write_json", faulty):
            yield

    def stored_bytes(self):
        path = os.path.join(nodes.store_dir(), paths.safe_name(P), "project-%s.json" % paths.safe_name(P))
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def run_number_call(self, key, number, mode, before, old, label):
        """모드별로 번호 바꾸기를 부른다. 끊김 ③(kill)은 다시 읽고 되찾는 일까지 여기서 마친다."""
        m = self.mats[key]
        self.settled_at_entry = self.settled
        if mode == "fail_retry":
            def boom(_path):
                raise RuntimeError("추출 실패")
            out = self.call(key, number, extract=boom)
            if not out["ok"] and out["refused"][0].get("target") == "extraction":
                self.stats["failed_extract"] += 1
                snap = self.snapshot()
                if any(snap.owner.get(g) != o for g, o in before.owner.items()) or (self.settled_at_entry and snap.owner != before.owner):
                    fail("V10", "%s: 다시 추출이 실패했는데 시트가 앞과 다름 %s -> %s" % (label, before.owner, snap.owner))
                self.check_segs(snap, label + " 실패 뒤")
                guarded = old and self.rng.random() < 0.4
                if guarded:   # 실패와 재시도 사이에 사람이 그 도면에 옮기지 못하는 기록을 만든다: 재시도 길도 같은 가드로 막아야 한다
                    self.kg_block(old, snap.owner[old])
                out = self.call(key, number)
                if guarded:
                    self.stats["retry_guarded"] += 1
                    if not out["ok"]:
                        self.ended = True   # 등록정보는 이미 새 번호라 모델과 갈린다: 이 시드는 여기서 끝낸다
                        return out
                elif not out["ok"]:
                    fail("V10", "%s: 같은 확정을 다시 했는데 거절: %s" % (label, out["refused"][0].get("reason")))
            return out
        if mode == "kill":
            before_gid = old

            def killed(_path):
                raise KeyboardInterrupt
            try:
                return self.call(key, number, extract=killed)
            except KeyboardInterrupt:
                self.stats["killed"] += 1
                m["number"] = number
                for nid, s in self.segs.items():
                    if any((x[0], x[1]) == (m["mid"], 0) for x in s["truth"]):
                        s["exempt"] = True
                snap = self.snapshot()
                self.check_segs(snap, label + " 끊긴 뒤", loose=True)
                self.extract_file(key)
                taken = self.snapshot(read=False).owner.get(before_gid)
                if taken is not None and taken[0] != m["mid"]:
                    # 알려진 한계(끊김 ③): 그 사이 같은 이름을 다른 자료가 이어받으면 묘비 되찾기는 이름을 옮기지 않는다(설계 §8). 구성요소는 사람이 다시 고른다.
                    self.stats["kill_old_name_taken"] += 1
                    for t in self.segs.values():
                        if any((x[0], x[1]) == (m["mid"], 0) for x in t["truth"]):
                            t["clean"] = False
                return {"ok": True, "changed": True, "renames": [], "killed": True}
        if mode.startswith("cut"):
            data.set_graph_listener(None)
            try:
                out = self.call(key, number)
            finally:
                data.set_graph_listener(data.catch_up_study)
            if out["ok"] and out.get("changed"):
                self.stats[mode] += 1
                pg = project_ctx.project_graph(P)
                if mode == "cut_before":
                    self.intermediate(label + " 판 이전 전", before)
                else:
                    with self.write_fault("before" if mode == "cut_wfail" else "after"):
                        ns = nodes.load(pg)
                    self.intermediate(label + " 쓰기 끊김", before, ns)
                    self.intermediate(label + " 쓰기 끊긴 뒤 저장본", before)
                snap = self.snapshot()
                again = self.stored_bytes()
                nodes.load(project_ctx.project_graph(P))
                if self.stored_bytes() != again:
                    fail("V10", "%s: 판 이전을 마친 뒤 한 번 더 읽었더니 저장본이 달라짐" % label)
                self.check_segs(snap, label + " 다시 읽은 뒤")
            return out
        return self.call(key, number)

    def apply_number(self, key, number, mode="plain"):
        m = self.mats[key]
        label = "%s %s %s -> %s %s" % ("unconfirm" if number is None else "confirm", key, m["number"], number, mode)
        self.log(label)
        before = self.snapshot()
        old = next((g for g, o in before.owner.items() if o[0] == m["mid"]), None)
        carriers = [nid for nid, s in before.segs.items() if any(before.idx.get(x, {}).get("sheet") == old for x in s["members"])] if old else []
        if mode == "kill" and (not old or all(o[0] == m["mid"] for o in before.owner.values())):
            mode = "plain"
        if mode == "fail_retry" and not old:
            mode = "plain"
        dry, settled_before = None, self.settled
        if mode == "dry":
            files = self.work_files()
            dry = self.call(key, number, dry=True)
            if self.work_files() != files:
                fail("V6", "dry가 파일을 썼다")
        out = self.run_number_call(key, number, mode, before, old, label)
        self.refresh_settled()
        if dry is not None and settled_before:    # 정착 전 프로젝트의 dry는 이름 검사를 건너뛴다
            if dry["ok"] != out["ok"]:
                fail("V6", "dry %s인데 실제는 %s: dry=%s 실제=%s" % (dry["ok"], out["ok"], dry.get("refused"), out.get("refused")))
            if not out["ok"] and dry["refused"][0].get("reason_code") != out["refused"][0].get("reason_code"):
                fail("V6", "dry와 실제의 거절 사유 코드가 다름")
            if out["ok"] and out.get("changed") and (dry.get("carries"), dry.get("renames")) != (out.get("carries"), out.get("renames")):
                fail("V6", "dry의 carries·renames가 실제와 다름: %s %s / %s %s" % (dry.get("carries"), dry.get("renames"), out.get("carries"), out.get("renames")))
        if number == RESERVED and out["ok"]:
            fail("V6", "%s: 임시 이름과 같은 꼴의 번호를 허락함" % label)
        if not out["ok"]:
            row = out["refused"][0]
            self.stats["refused"] += 1
            self.stats["refused:" + str(row.get("reason_code"))] += 1
            if row.get("reason_code") not in KNOWN_CODES:
                fail("V6", "거절에 알려진 사유 코드가 없음: %s" % row)
            if not row.get("reason") or (TEMP_NAME.search(row["reason"]) and row.get("reason_code") != sheet_rules.NUMBER_RESERVED):   # 예약 꼴은 사용자가 친 번호가 글에 나온다
                fail("V6", "거절 글이 없거나 임시 이름이 보임: %s" % row.get("reason"))
            if row["reason_code"] in (sheet_rules.NUMBER_HELD, sheet_rules.NUMBER_RESERVED):
                return out
            why = self.justified(key, number, before, row)
            if why is None:
                fail("V6", "%s: 막을 것이 없는데 거절함: %s" % (label, row["reason"]))
            if APPLY_TEXT in row["reason"] and before.current:
                after = "graph-" + number if number else self.legacy_gid.get((m["mid"], 0)) or temp_name(m["mid"])
                if before.owner.get(after) in (None, before.owner.get(old)):
                    fail("V6", "%s: 판이 이미 맞는데 '도면 변경 반영하기'를 하라는 막다른 글: %s" % (label, row["reason"]))
                self.stats["known_dead_end_text"] += 1   # 알려진 한계: 정착이 붙박은 옛 자리 이름을 다른 파일의 번호가 쓰는 경우(글이 짝 증명 실패로만 말함)
            if why == KNOWN_E4 and KNOWN_DEFECTS:
                self.stats["known_E4"] += 1
            out = self.remedy(key, number, before, row, why)
            if not out["ok"]:
                return out
        if out.get("changed"):
            self.stats["accepted"] += 1
            if carriers:
                self.stats["accepted_with_segment"] += 1
            self.moved = True
            if old and carriers and out.get("renames"):
                got = (out.get("carries") or {}).get("구간", 0)
                if got < len(carriers):   # 찾지 못한 구성요소가 그 도면을 가리키는 구간도 세므로 더 많이 알릴 수는 있다
                    fail("V6", "%s: 옮길 구간을 %d개로 알렸는데 실제 %d개(%s)" % (label, got, len(carriers), carriers))
            m["number"] = number
            if number and old and out.get("renames") and [r["to"] for r in out["renames"]] != ["graph-" + number]:
                fail("V6", "%s: 이름 바뀜이 graph-%s가 아님: %s" % (label, number, out["renames"]))
        return out

    def remedy(self, key, number, before, row, why):
        """거절 글대로 하면(기록을 정리하고 도면 변경을 반영하면) 다시 허락해야 한다. 아직 막을 까닭이 남으면 그대로 거절."""
        did = []
        if why.startswith("막는 기록"):
            for b in list(self.blockers):
                self.clear_blocker(b)
                did.append(b["kind"])
        snap = self.snapshot()      # 도면 변경 반영하기: 구간 저장본을 지금 판으로 맞춤
        out = self.call(key, number)
        if out["ok"]:
            self.stats["remedied"] += 1
            return out
        left = self.justified(key, number, snap, out["refused"][0])
        if left is None or (did and left.startswith("막는 기록")):
            fail("V6", "거절 글대로 정리(%s)했는데도 막음: %s" % (did, out["refused"][0]["reason"]))
        return out

    # ---------------------------------------------------------------- 사슬
    def step(self):
        """연산 하나를 고르고 돌린 뒤 불변식을 본다. 연산을 하지 못하면 False."""
        r = self.rng
        reg = [k for k, m in self.mats.items() if m["mid"]]
        weights = [("register", 5), ("extract", 2), ("seg", 3), ("seg_remove", 1), ("seg_undo", 1), ("seg_confirm", 1),
                   ("confirm", 7), ("unconfirm", 3), ("choose", 2), ("doc", 2), ("blocker", 2), ("settle", 1)]
        name = r.choices([w[0] for w in weights], [w[1] for w in weights])[0]
        before = self.snapshot()
        self.moved = False
        self.pre_extracted = {m["mid"] for m in self.mats.values() if m["extracted"]}
        label = name
        if name == "register":
            key = r.choice(list(SOURCES))
            number = r.choice([None, None] + NUMBERS) if key != "mp" else r.choice([None, None, None, NUMBERS[0]])
            number = RESERVED if r.random() < 0.05 else number
            label = "register %s" % key
            self.register(key, number, extract=r.random() < 0.85)
        elif name == "extract":
            if not reg:
                return False
            key = r.choice(reg)
            label = "extract %s" % key
            self.log(label)
            self.extract_file(key)
        elif name == "settle":
            if self.settled:
                return False
            label = "settle"
            self.settle()
        elif name in ("seg", "seg_remove", "seg_undo", "seg_confirm", "doc", "blocker"):
            if name == "seg":
                todo = [k for k in self.visible(before)]
                if not todo or not self.seg_new(r.choice(todo)):
                    return False
            elif not getattr(self, {"doc": "doc_new", "blocker": "blocker_new"}.get(name, name))():
                return False
        elif name in ("confirm", "unconfirm"):
            todo = [k for k in reg if self.mats[k]["pages"] == 1 or name == "unconfirm"]
            if name == "unconfirm":
                todo = [k for k in todo if self.mats[k]["number"]]
            if not todo:
                return False
            weighted = [k for k in todo if k in self.segment_keys()] or todo
            key = r.choice(weighted if r.random() < 0.6 else todo)
            number = r.choice([n for n in NUMBERS if n != self.mats[key]["number"]]) if name == "confirm" else None
            number = RESERVED if name == "confirm" and r.random() < 0.05 else number
            label = "%s %s" % (name, key)
            mode = r.choices(["plain", "dry", "fail_retry", "cut_before", "cut_wfail", "cut_wafter", "kill"], [45, 25, 8, 7, 5, 5, 5])[0]
            self.apply_number(key, number, mode)
        elif name == "choose":
            rows = sources.conflicts(P)
            if not rows:
                return False
            row = r.choice(rows)
            cand = r.choice(row["candidates"])
            label = "choose %s" % row["graph_id"]
            try:
                self.choose(row["graph_id"], cand["material_id"])
            except ValueError:
                return False
        snap = self.snapshot()
        self.stats["op:" + name] += 1
        self.check(snap, label, before)
        return True

    def segment_keys(self):
        have = {x[0] for s in self.segs.values() for x in s["truth"]}
        return [k for k, m in self.mats.items() if m["mid"] in have]


# ---------------------------------------------------------------- 시험

@contextlib.contextmanager
def seed_root():
    tmp = tempfile.mkdtemp(prefix="hazop-sidfuzz-")
    env = mock.patch.dict(os.environ, {"HAZOP_WORK_ROOT": os.path.join(tmp, "work"), "HAZOP_STORE_ROOT": os.path.join(tmp, "store")})
    env.start()
    os.makedirs(os.environ["HAZOP_WORK_ROOT"])
    for cache in (project_ctx._PROJECT_GRAPHS, project_ctx._NAMES, project_ctx._VIEWS, data._MARKED):
        cache.clear()
    try:
        yield tmp
    finally:
        env.stop()
        shutil.rmtree(tmp, True)


def legacy_phase(w):
    """정착 전 프로젝트: 이 단위 전 이름 규칙으로 도면을 넣는다(번호 없는 PDF 여럿이 graph-drawing을 나눠 쓰고 하나만 보인다)."""
    r = w.rng
    w.settled = False
    with mock.patch("hazop.graph.sources.sheet_name", legacy_name, create=True), \
            mock.patch("hazop.app.data.settle_sheets", lambda *a, **k: None, create=True):
        for key in r.sample(["p101", "p102", "p201", "d101", "d102", "dx"], r.randint(2, 3)):
            w.register(key, r.choice([None, None, None, NUMBERS[0]]))
        vis = w.visible()
        if vis:
            w.seg_new(r.choice(vis))
    snap = w.snapshot(read=False)
    for gid, (mid, page) in snap.owner.items():
        if gid != "graph-" + (w.mats[w.key_of(mid)]["number"] or "\0"):
            w.legacy_gid[(mid, page)] = gid
    w.stats["legacy"] += 1


def run_seed(seed, steps=STEPS):
    data.set_graph_listener(data.catch_up_study)
    with seed_root() as tmp:
        w = World(seed, tmp)
        try:
            if random.Random(seed * 31 + 7).random() < 0.3:
                legacy_phase(w)
            else:
                for key in w.rng.sample(["p101", "d101", "d102", "p102"], 2):
                    w.register(key, None)
            w.check(w.snapshot(), "start")
            if w.stats["legacy"] and w.rng.random() < 0.6:   # 정착 전 프로젝트의 dry는 아무것도 쓰지 않는다
                todo = [k for k, m in w.mats.items() if m["extracted"] and m["pages"] == 1 and not m["number"]]
                if todo:
                    w.apply_number(w.rng.choice(todo), w.rng.choice(NUMBERS), "dry")
                    w.check(w.snapshot(), "정착 전 dry", None)
            done = 0
            for _ in range(steps * 3):
                if done >= steps:
                    break
                done += 1 if w.step() else 0
                if w.ended:
                    break
        except Violation as exc:
            known = known_defect(w, exc)
            if known:
                w.stats["known_" + known] += 1   # 이 시드는 여기서 끝낸다(앞의 판정은 모두 통과했다)
                return w
            raise Violation(exc.code, "%s\n    연산: %s" % (exc.args[0][len(exc.code) + 1:], " | ".join(w.trace[-14:]))) from None
        except Exception:  # noqa: BLE001 - 예상 밖 예외는 위반 X
            raise Violation("X", "예외 %s\n%s" % (" | ".join(w.trace[-8:]), traceback.format_exc()[-1500:])) from None
    return w


# ---------------------------------------------------------------- 합쳐도 같음(V9)

def compose_script(seed):
    """구간을 만든 뒤 판을 바꾸는 연산 몇 개(번호 확정·취소·다른 자료 등록·다시 추출)."""
    r = random.Random(seed * 7919 + 13)
    keys = r.sample(["p101", "p102", "d101", "d102", "dx", "p201"], 3)
    setup = [("register", keys[0], None), ("register", keys[1], None), ("seg", keys[0]), ("seg", keys[1])]
    batch = []
    if r.random() < 0.5:   # 두 파일이 번호를 맞바꾸고 그사이 집합을 읽지 않음(R11)
        setup += [("confirm", keys[0], "SNP-M-101"), ("confirm", keys[1], "SNP-M-102")]
        return setup, [("confirm", keys[0], "SNP-M-555"), ("confirm", keys[1], "SNP-M-101"), ("confirm", keys[0], "SNP-M-102")]
    for _ in range(r.randint(2, 5)):
        k, c = r.choice(keys[:2]), r.random()
        if c < 0.45:
            batch.append(("confirm", k, r.choice(NUMBERS)))
        elif c < 0.6:
            batch.append(("unconfirm", k))
        elif c < 0.8:
            batch.append(("register", keys[2], r.choice(NUMBERS + [None])))
        else:
            batch.append(("extract", k))
    return setup, batch


def replay(w, op):
    """연산 하나를 돌리고 결과('ok'·거절 사유 코드·'skip')를 돌려준다. 읽기(판 이전)는 하지 않는다."""
    kind = op[0]
    if kind == "register":
        w.register(op[1], op[2])
        return "ok"
    if kind == "extract":
        w.extract_file(op[1])
        return "ok"
    m = w.mats.get(op[1])
    if m is None or (kind == "unconfirm" and not m["number"]):
        return "skip"
    number = op[2] if kind == "confirm" else None
    out = w.call(op[1], number)
    if out["ok"] and out.get("changed"):
        m["number"] = number
    return "ok" if out["ok"] else out["refused"][0].get("reason_code")


def run_script(seed, lazy):
    """같은 연산열을 연산마다 판 이전하며(lazy 아님) 또는 판 이전을 미루고(lazy) 돌린 끝."""
    data.set_graph_listener(data.catch_up_study)
    with seed_root() as tmp:
        w = World(seed, tmp)
        setup, batch = compose_script(seed)
        try:
            for op in setup:
                replay(w, op) if op[0] != "seg" else w.seg_new(op[1])
            if lazy:
                data.set_graph_listener(None)
            outcomes = []
            for op in batch:
                outcomes.append(replay(w, op))
                if not lazy:
                    w.snapshot()
            data.set_graph_listener(data.catch_up_study)
            snap = w.snapshot()
            w.check(snap, "합침" if lazy else "하나씩")
        except Violation as exc:
            raise Violation(exc.code, "%s\n    연산: %s" % (exc.args[0][len(exc.code) + 1:], " | ".join(w.trace[-10:]))) from None
        finally:
            data.set_graph_listener(None)
        end = {"sheets": snap.owner, "segs": {nid: (frozenset(s["syms"]), s["lost"], s["state"]) for nid, s in snap.segs.items()}}
        return outcomes, end, w.trace


# ---------------------------------------------------------------- 시험

class SheetIdentityFuzzTest(unittest.TestCase):
    def tearDown(self):
        data.set_graph_listener(None)

    def test_fuzz(self):
        bad, stats, t0 = [], collections.Counter(), time.time()
        for seed in range(FIRST, FIRST + SEEDS):
            try:
                w = run_seed(seed)
                stats.update(w.stats)
            except Violation as exc:
                bad.append("시드 %d %s" % (seed, exc))
        print("\n시드 %d개 %.0f초 %s 위반 %d" % (SEEDS, time.time() - t0, dict(sorted(stats.items())), len(bad)))
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_composition(self):
        """V9. 같은 연산열을 하나씩 판 이전한 끝과 판 이전을 미루고 합쳐 한 번에 한 끝이 같다. 가드가 합친 쪽만 거절하는 연산열(판이 이미 다르면
        막고 '도면 변경 반영하기'로 푼다)은 비교하지 않고 센다."""
        bad, same, diverged, t0 = [], 0, 0, time.time()
        for seed in range(FIRST, FIRST + COMPOSE):
            try:
                step_out, step_end, trace = run_script(seed, False)
                lazy_out, lazy_end, _t = run_script(seed, True)
            except Violation as exc:
                bad.append("시드 %d %s" % (seed, exc))
                continue
            if step_out != lazy_out:
                diverged += 1
            elif step_end != lazy_end:
                bad.append("시드 %d V9 합쳐 돌린 끝이 하나씩 돌린 끝과 다름\n    연산: %s\n    하나씩 %s\n    합침   %s" % (seed, trace[-8:], step_end, lazy_end))
            else:
                same += 1
        print("\n합침 시드 %d개 %.0f초 같음 %d 연산 결과가 갈림 %d 위반 %d" % (COMPOSE, time.time() - t0, same, diverged, len(bad)))
        self.assertEqual(bad, [], "\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
