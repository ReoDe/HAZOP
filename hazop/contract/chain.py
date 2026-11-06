"""단계 연쇄 검사: ①등록 → ②추출 → ③그래프 → ④분석 → ⑤검토·출력의 저장 결과가 ID·버전·해시·상태대로 이어지는지 본다.

근거: 기획서/단계연쇄검사.md(§2 입력·연쇄 찾기, §3 판정 등급, §4 검사 항목 G·R·X·A·C·E·K, §5 출력).
읽기 전용이다. 어떤 입력 파일도 만들거나 고치지 않는다(write_report로 지정한 보고 파일만 예외). 네트워크·AI 호출 없음.
단계 내부의 형식·내용 검사는 하지 않는다(check_register·check_extract 등의 몫).

판정: PASS(규격대로) / FAIL(규격 위반) / WARN(확인 필요) / SKIP(해당 없음, 사유 필수).
메시지: "[등급] <ID> <대상>: <내용> (기대 <값>, 실제 <값>)". 해시는 앞 12자리만 표시한다.
실행 오류(입력 폴더 없음, JSON 읽기 실패 등)는 결과가 아니라 errors에 모으고 종료 코드 2로 알린다.
"""

import collections
import datetime
import hashlib
import json
import os
import re

from hazop import paths
from hazop.extract import rules as extract_rules
from hazop.graph import build as graph_build
from hazop.review import record as review_record

SCHEMA_VERSION = "0.1"
CHECK_VERSION = "0.1.0"
LEVELS = ("PASS", "FAIL", "WARN", "SKIP")
SAMPLE_SKIP = "샘플 경로(등록 미연동)"
NO_SNAPSHOT_SKIP = "등록 스냅샷 없음(R1 실패)"
NO_REVIEW_SKIP = "검토본 없음"
NO_EXPORT_SKIP = "출력 기록 없음"
NO_COMPARE_SKIP = "평가 비교 보고 없음"
EXPORTS_DIR = "exports"  # 실행 폴더 아래 exports는 후보 폴더가 아님(hazop/review/store.py load_run_reviews와 같은 규칙)
NOT_REGISTERED_FIELDS = ("project_id", "material_id", "registration_version")
FLOW_KEYS = ("from", "to", "from_end", "to_end", "basis")
_VERSION_FILE = re.compile(r"^v(\d+)\.json$")
_STAMP = re.compile(r"\d{8}T\d{6}Z")
# 오래된 실행의 필드 누락·형식 차이: 해당 항목만 FAIL로 표시하고 검사 전체는 계속한다(§6 V19).
_FIELD_ERRORS = (KeyError, TypeError, AttributeError, ValueError, IndexError)


class ContractError(Exception):
    """실행 오류(종료 코드 2): 입력 폴더 없음, 지정한 구간·실행 없음, 보고 경로 거부 등."""


# ---------------------------------------------------------------- 공통
def h12(value):
    """해시 표시: 앞 12자리. 문자열이 아니면 repr."""
    return value[:12] if isinstance(value, str) else repr(value)


def file_sha256(path):
    """파일 바이트 SHA-256. 없으면 None."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except (FileNotFoundError, NotADirectoryError):
        return None  # 그 밖의 OSError(권한 등)는 호출자에게 올린다(실행 오류, 종료 코드 2)


def _get(doc, *keys):
    """중첩 dict 값. 중간이 dict가 아니거나 키가 없으면 None."""
    for k in keys:
        if not isinstance(doc, dict):
            return None
        doc = doc.get(k)
    return doc


def _join(root, *names):
    """root 아래 경로(각 이름은 한 단계, 루트 밖이면 None)."""
    try:
        for n in names:
            if not isinstance(n, str) or not n:
                return None
            root = paths.safe_join(root, n)
    except ValueError:
        return None
    return root


def _int_or_none(value):
    """버전 값을 정수로 정규화: 정수(불 제외) 또는 ASCII 숫자만으로 된 문자열(앞뒤 공백 허용). 그 밖은 None."""
    if type(value) is int:
        return value
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        return int(value.strip())
    return None


def _ver(value, label):
    """버전 비교용 정수. 바꿀 수 없으면 ValueError(해당 항목 FAIL)."""
    v = _int_or_none(value)
    if v is None:
        raise ValueError("%s 값을 정수로 바꿀 수 없음: %r" % (label, value))
    return v


def _resolve(path, root):
    return path if os.path.isabs(path) else os.path.join(root, path)


def _run_sort_key(name):
    """분석 실행 폴더 이름의 시각(YYYYMMDDTHHMMSSZ) 순. 시각이 없으면 이름 순으로 뒤에 둔다."""
    m = _STAMP.search(name)
    return (m.group(0) if m else "", name)


# ---------------------------------------------------------------- 연쇄 하나
class _Chain:
    """분석 실행 1개에서 거꾸로 찾은 연쇄(§2.1). 파일을 읽기만 한다."""

    def __init__(self, work_root, store_root, run_dir, region_file):
        self.work_root, self.store_root, self.run_dir = work_root, store_root, run_dir
        self.errors, self.results = [], []
        self.run_folder = os.path.basename(run_dir)
        self.region_folder = os.path.basename(os.path.dirname(run_dir))
        self.run_id = self.run_folder
        self.analysis = self.analysis_sha = self.copy_graph = self.copy_region = None
        self.path = "samples"
        self.extraction_path = self.extraction = self.ext_name = self.graph_dir = None
        self.graph = self.mapping_doc = self.current_region = None
        self.snapshot = self.snapshot_path = self.project_root = None
        self.material_id = self.registration_version = None
        self.review_base = None
        self.reviews = {}  # {candidate 폴더 이름: {번호: 문서}}
        self.exports = []  # [(파일 이름 줄기, 문서)]
        self.compares = []  # [(파일 이름 줄기, 문서)]
        self.r1_ok = False
        try:
            self._load(region_file)
        except OSError as exc:  # 권한 없음 등 파일 접근 실패: 실행 오류(종료 코드 2)
            self.errors.append("파일 접근 실패: %s" % exc)
        except ValueError as exc:  # 경로·이름 형식 오류 등: 실행 오류(종료 코드 2)
            self.errors.append("입력 형식 오류: %s" % exc)

    def _load(self, region_file):
        work_root, store_root, run_dir = self.work_root, self.store_root, self.run_dir
        apath = os.path.join(run_dir, "analysis.json")
        if not os.path.isfile(apath):
            self.errors.append("analysis.json 없음: %s" % apath)
        self.analysis = self._json(apath)
        self.analysis_sha = file_sha256(apath)
        a = self.analysis if isinstance(self.analysis, dict) else {}
        if isinstance(a.get("analysis_run_id"), str):
            self.run_id = a["analysis_run_id"]
        self.copy_graph = self._json(os.path.join(run_dir, "inputs", "graph.json"))
        self.copy_region = self._json(os.path.join(run_dir, "inputs", "region.json"))
        basis = self.copy_graph if isinstance(self.copy_graph, dict) else a
        # 등록 경로 판정: 그래프의 project_id가 있음(hazop.analysis.run.graph_source_of와 같은 기준, §2.2)
        self.path = "registration" if basis.get("project_id") else "samples"

        # ② 현재 추출: 그래프 사본의 source.extraction_file(작업 루트 기준)
        ext_file = _get(self.copy_graph, "source", "extraction_file")
        self.extraction_path = _resolve(ext_file, work_root) if isinstance(ext_file, str) and ext_file else None
        self.extraction = self._json(self.extraction_path) if self.extraction_path else None
        # ③ 현재 그래프: 추출 결과 폴더 이름(scripts/build_graph.py build_one과 같은 이름 규칙)으로
        # 먼저 extraction_file의 형제 폴더(…/추출/<이름> → …/그래프/<이름>, 예: run_samples의 출력/samples/그래프)에서 찾고,
        # graph.json이 없으면 출력/그래프/<이름>을 본다(총괄 추가 지시 2026-11-06, 기획 §2 표는 출력/그래프만 적음).
        self.ext_name = os.path.basename(os.path.dirname(self.extraction_path)) if self.extraction_path else None
        if self.ext_name:
            name = paths.safe_name(self.ext_name)
            sibling = _join(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(self.extraction_path))),
                                         "그래프"), name)
            default = _join(os.path.join(work_root, "출력", "그래프"), name)
            self.graph_dir = (sibling if sibling and os.path.isfile(os.path.join(sibling, "graph.json"))
                              else default)
        self.graph = self._json(os.path.join(self.graph_dir, "graph.json")) if self.graph_dir else None
        self.mapping_doc = self._json(os.path.join(self.graph_dir, "entity_mapping.json")) if self.graph_dir else None
        self.current_region = self._json(region_file) if region_file else None

        # ① 등록 스냅샷(등록 경로만): 추출의 project_id·source.material_id·registration_version으로 찾는다.
        ext = self.extraction if isinstance(self.extraction, dict) else {}
        self.material_id = _get(ext, "source", "material_id")
        self.registration_version = _get(ext, "source", "registration_version")
        if self.path == "registration" and ext:
            self.project_root = _join(store_root, ext.get("project_id"))
            ver = _int_or_none(self.registration_version)
            if self.project_root and ver is not None:
                self.snapshot_path = _join(self.project_root, "registrations", self.material_id, "%d.json" % ver)
            if self.snapshot_path and os.path.isfile(self.snapshot_path):
                self.snapshot = self._json(self.snapshot_path)

        # ⑤ 검토본·출력 기록: 분석의 region_ref.region_id·analysis_run_id로 찾는다.
        region_id = _get(a, "region_ref", "region_id")
        self.review_base = _join(store_root, "reviews", region_id, a.get("analysis_run_id"))
        if self.review_base and os.path.isdir(self.review_base):
            for name in sorted(os.listdir(self.review_base)):
                d = os.path.join(self.review_base, name)
                if name == EXPORTS_DIR or not os.path.isdir(d):
                    continue
                versions = {}
                for fname in os.listdir(d):
                    m = _VERSION_FILE.match(fname)
                    if m:
                        doc = self._json(os.path.join(d, fname))
                        if doc is not None:
                            versions[int(m.group(1))] = doc
                if versions:
                    self.reviews[name] = versions
            exp_dir = os.path.join(self.review_base, EXPORTS_DIR)
            if os.path.isdir(exp_dir):
                for fname in sorted(os.listdir(exp_dir)):
                    if fname.endswith(".json") and os.path.isfile(os.path.join(exp_dir, fname)):
                        doc = self._json(os.path.join(exp_dir, fname))
                        if doc is not None:
                            self.exports.append((fname[:-5], doc))
        cmp_dir = _join(os.path.join(work_root, "출력", "평가비교"), region_id, a.get("analysis_run_id"))
        if cmp_dir and os.path.isdir(cmp_dir):
            for fname in sorted(os.listdir(cmp_dir)):
                if fname.endswith(".json") and os.path.isfile(os.path.join(cmp_dir, fname)):
                    doc = self._json(os.path.join(cmp_dir, fname))
                    if doc is not None:
                        self.compares.append((fname[:-5], doc))

    def _json(self, path):
        """JSON 객체 읽기. 없으면 None. 읽기 실패·접근 실패·객체가 아닌 JSON(예: [])은 실행 오류(종료 코드 2)로
        모으고 None(입력 파일은 모두 JSON 객체여야 함)."""
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except OSError as exc:
            self.errors.append("파일 접근 실패: %s (%s)" % (path, exc))
            return None
        except ValueError as exc:
            self.errors.append("JSON 읽기 실패: %s (%s)" % (path, exc))
            return None
        if not isinstance(doc, dict):
            self.errors.append("JSON 객체가 아님: %s (%s)" % (path, type(doc).__name__))
            return None
        return doc

    def add(self, cid, level, target, message):
        self.results.append({"id": cid, "level": level, "target": target, "message": message})

    def fail(self, cid, target, message):
        self.add(cid, "FAIL", target, message)

    # 대상 이름
    @property
    def graph_target(self):
        return _get(self.graph, "graph_id") or _get(self.copy_graph, "graph_id") or "graph-?"

    @property
    def extraction_target(self):
        return "extraction %s" % (self.ext_name or "?")

    @property
    def snapshot_target(self):
        return "%s v%s" % (self.material_id, self.registration_version)

    def need(self, cid, target, *what):
        """검사에 필요한 파일이 없으면 FAIL을 남기고 False."""
        names = {"extraction": ("현재 추출 결과", self.extraction, self.extraction_path),
                 "graph": ("현재 그래프", self.graph, os.path.join(self.graph_dir, "graph.json")
                           if self.graph_dir else None),
                 "copy_graph": ("실행 사본 inputs/graph.json", self.copy_graph, None),
                 "copy_region": ("실행 사본 inputs/region.json", self.copy_region, None),
                 "analysis": ("analysis.json", self.analysis, None)}
        ok = True
        for w in what:
            label, doc, path = names[w]
            if not isinstance(doc, dict):
                self.fail(cid, target, "%s 없음%s" % (label, " (기대 경로 %s)" % path if path else ""))
                ok = False
        return ok

    def review_items(self):
        for cid in sorted(self.reviews):
            for n in sorted(self.reviews[cid]):
                yield cid, n, self.reviews[cid][n]

    def review_target(self, cid, n, doc):
        rid = doc.get("review_id") if isinstance(doc, dict) else None
        return "%s v%d" % (rid if isinstance(rid, str) else "review-%s" % cid, n)

    def export_target(self, stem, doc):
        eid = doc.get("export_id") if isinstance(doc, dict) else None
        return eid if isinstance(eid, str) else "export-%s" % stem


# ---------------------------------------------------------------- 4.1 공통
def _g1(c):
    files = []
    if c.path == "registration" and c.snapshot is not None:
        files.append(("registration %s" % c.snapshot_target, c.snapshot))
    if c.extraction is not None:
        files.append((c.extraction_target, c.extraction))
    if c.graph is not None:
        files.append(("graph %s" % c.graph_target, c.graph))
    if c.analysis is not None:
        files.append(("analysis %s" % c.run_id, c.analysis))
    for cid, n, doc in c.review_items():
        files.append((c.review_target(cid, n, doc), doc))
    for stem, doc in c.exports:
        files.append((c.export_target(stem, doc), doc))
    for label, doc in files:
        if "schema_version" not in doc:
            c.fail("G1", label, "schema_version 없음")
        elif doc["schema_version"] != SCHEMA_VERSION:
            c.fail("G1", label, "schema_version 다름 (기대 %r, 실제 %r)" % (SCHEMA_VERSION, doc["schema_version"]))
    return c.run_id, "파일 %d개 schema_version %r" % (len(files), SCHEMA_VERSION)


def _g2(c):
    if c.path == "samples":  # 샘플 경로는 대상 파일의 project_id가 모두 null이어야 함(§4.1 G2)
        basis_label, expected = "샘플 경로 null", None
    else:
        basis_label, basis = ("그래프 사본", c.copy_graph) if isinstance(c.copy_graph, dict) else ("분석", c.analysis)
        expected = basis["project_id"] if "project_id" in basis else None
    items = []
    if c.path == "registration" and c.snapshot is not None:
        items.append(("등록 스냅샷", c.snapshot))
    items += [("추출", c.extraction), ("그래프", c.graph), ("그래프 사본", c.copy_graph), ("구간 사본", c.copy_region),
              ("분석", c.analysis)]
    items += [("검토본 %s v%d" % (cid, n), doc) for cid, n, doc in c.review_items()]
    items = [(label, doc) for label, doc in items if doc is not None]
    bad = []
    for label, doc in items:
        if "project_id" not in doc:
            bad.append("%s 필드 없음" % label)
        elif doc["project_id"] != expected:
            bad.append("%s %r" % (label, doc["project_id"]))
    if bad:
        c.fail("G2", c.run_id, "project_id 불일치 (기대 %r(%s), 실제 %s)" % (expected, basis_label, ", ".join(bad)))
    return c.run_id, "project_id %r로 같음 (파일 %d개%s)" % (
        expected, len(items), ", 샘플 경로는 모두 null" if c.path == "samples" else "")


# ---------------------------------------------------------------- 4.2 ① → ②
def _r_skip(c, cid):
    if c.path == "samples":
        c.add(cid, "SKIP", c.extraction_target if cid == "R1" else "registration", SAMPLE_SKIP)
        return True
    if cid != "R1" and not c.r1_ok:
        c.add(cid, "SKIP", c.snapshot_target, NO_SNAPSHOT_SKIP)
        return True
    return False


def _r1(c):
    if _r_skip(c, "R1"):
        return None
    if not c.need("R1", c.extraction_target, "extraction"):
        return None
    if c.snapshot is None:
        c.fail("R1", c.extraction_target, "등록 스냅샷 없음 %s (추출 project_id %r, 기대 파일 %s)"
               % (c.snapshot_target, c.extraction.get("project_id"), c.snapshot_path or "경로를 만들 수 없음"))
        return None
    c.r1_ok = True
    return c.extraction_target, "등록 스냅샷 %s 있음" % c.snapshot_target


def _r2(c):
    if _r_skip(c, "R2"):
        return None
    st, vs = c.snapshot.get("status"), _get(c.snapshot, "validation", "status")
    if st != "registered":
        c.fail("R2", c.snapshot_target, "등록 미완료 (기대 status 'registered', 실제 %r)" % st)
    if vs != "passed":
        c.fail("R2", c.snapshot_target, "등록 검증 미통과 (기대 validation.status 'passed', 실제 %r)" % vs)
    return c.snapshot_target, "status registered, validation.status passed"


def _r3(c):
    if _r_skip(c, "R3"):
        return None
    ext_sha = _get(c.extraction, "source", "sha256")
    snap_sha = c.snapshot.get("sha256")
    ref = c.snapshot.get("storage_ref")
    stored = _join(c.project_root, *ref.replace("\\", "/").split("/")) if isinstance(ref, str) and ref else None
    stored_sha = file_sha256(stored) if stored else None
    if stored_sha is None:
        c.fail("R3", c.snapshot_target, "저장 원본 없음 (storage_ref %r)" % ref)
    if not (ext_sha == snap_sha and (stored_sha is None or stored_sha == snap_sha)):
        c.fail("R3", c.snapshot_target, "원본 해시 불일치 (등록 %s, 추출 %s, 저장 원본 %s)"
               % (h12(snap_sha), h12(ext_sha), h12(stored_sha) if stored_sha else "없음"))
    return c.snapshot_target, "추출·등록·저장 원본 해시 %s 같음" % h12(snap_sha)


def _r4(c):
    if _r_skip(c, "R4"):
        return None
    current = _ver(c.registration_version, "추출 registration_version")
    versions = {current}
    index = c._json(os.path.join(c.project_root, "registry.json"))
    for m in (index or {}).get("materials") or []:
        if isinstance(m, dict) and m.get("material_id") == c.material_id:
            versions.update(_ver(v, "registry.json versions") for v in m.get("versions") or [])
    folder = os.path.dirname(c.snapshot_path)
    versions.update(int(f[:-5]) for f in os.listdir(folder) if f.endswith(".json") and f[:-5].isascii() and f[:-5].isdigit())
    latest = max(versions)
    if latest > current:
        c.add("R4", "WARN", c.material_id, "추출은 v%d, 최신 등록은 v%d" % (current, latest))
    return c.snapshot_target, "최신 등록 버전 v%d" % latest


# ---------------------------------------------------------------- 4.3 ② → ③ (현재 산출물끼리)
def _x1(c):
    t = c.graph_target
    if not c.need("X1", t, "extraction", "graph"):
        return None
    run = c.extraction["extraction_run_id"]
    if run not in c.graph["input_runs"]:
        c.fail("X1", t, "추출 실행 ID가 input_runs에 없음 (기대 %s, 실제 %s)" % (run, c.graph["input_runs"]))
    if c.graph["source"]["extraction_run_id"] != run:
        c.fail("X1", t, "추출 실행 ID 불일치 (기대 %s, 실제 source.extraction_run_id %s)"
               % (run, c.graph["source"]["extraction_run_id"]))
    return t, "추출 실행 ID %s" % run


def _graph_version_with(extraction, builder_version):
    """hazop.graph.build._graph_version을 기록된 빌더 버전으로 계산(식 재사용, 모듈 값은 계산 뒤 되돌림)."""
    current = graph_build.BUILDER_VERSION
    graph_build.BUILDER_VERSION = builder_version
    try:
        return graph_build._graph_version(extraction)
    finally:
        graph_build.BUILDER_VERSION = current


def _x2(c):
    t = c.graph_target
    if not c.need("X2", t, "extraction", "graph"):
        return None
    again = graph_build._graph_version(c.extraction)
    if again != c.graph["graph_version"]:
        # 판정은 기획대로 현재 빌더로 재계산한 값과 비교(FAIL). 원인 표시만 나눈다: 그래프에 기록된 빌더 버전이
        # 현재와 다르면 그 기록 버전으로 같은 식(build._graph_version)을 다시 계산해 추출 변경 여부를 함께 적는다.
        recorded = _get(c.graph, "builder", "version")
        if isinstance(recorded, str) and recorded != graph_build.BUILDER_VERSION:
            old = _graph_version_with(c.extraction, recorded)
            c.fail("X2", t, "빌더 버전이 그래프 생성 뒤 바뀜(기록 %s, 현재 %s) — 그래프 재생성 필요. 기록 빌더 버전 기준 "
                            "추출 변경 %s (기록 %s, 재계산 %s)"
                   % (recorded, graph_build.BUILDER_VERSION, "없음" if old == c.graph["graph_version"] else "있음",
                      c.graph["graph_version"], again))
        else:
            c.fail("X2", t, "추출 결과가 그래프 생성 뒤 바뀜 (기록 %s, 재계산 %s)" % (c.graph["graph_version"], again))
    return t, "그래프 버전 %s = 재계산" % again


def _x3(c):
    t = c.graph_target
    if not c.need("X3", t, "extraction", "graph"):
        return None
    run = c.extraction["extraction_run_id"]
    local_ids = [x["local_id"] for x in c.extraction["nodes"] + c.extraction["relations"]]
    pairs = collections.Counter((m["extraction_run_id"], m["local_id"]) for m in c.graph["entity_mapping"])
    # 관계 종류 미확인 관계는 빌더가 매핑하지 않고 unknowns(check unknown_relation_kind, target = local_id)에 1건 남긴다
    # (hazop/graph/build.py). 그 기록이 정확히 1건 있으면 매핑 의무에서 뺀다(총괄 재작업 지시 2026-11-06).
    unknown_kind = collections.Counter(u.get("target") for u in c.graph["validation"]["unknowns"]
                                       if u.get("check") == "unknown_relation_kind")
    # 면제 조건: 기록이 정확히 1건이고 추출 관계의 kind가 알려진 관계 종류(hazop/extract/rules.py LINE_TYPE_RELATION 값)가
    # 아님. 알려진 종류인데 매핑이 없으면 기록이 있어도 FAIL(총괄 재작업 2회차).
    known_kinds = set(extract_rules.LINE_TYPE_RELATION.values())
    rel_kind = {r["local_id"]: r.get("kind") for r in c.extraction["relations"]}
    exempt = []
    for lid in local_ids:
        n = pairs.get((run, lid), 0)
        if n == 0 and lid in rel_kind and rel_kind[lid] not in known_kinds and unknown_kind[lid] == 1:
            exempt.append(lid)
        elif n == 0 and lid in rel_kind and rel_kind[lid] in known_kinds and unknown_kind[lid]:
            c.fail("X3", t, "매핑 없는 local_id %s (관계 종류 %s는 알려진 종류라 unknown_relation_kind 면제 대상 아님)"
                   % (lid, rel_kind[lid]))
        elif n == 0:
            c.fail("X3", t, "매핑 없는 local_id %s%s" % (lid, " (unknown_relation_kind 기록 %d개, 기대 1개)"
                                                      % unknown_kind[lid] if unknown_kind[lid] else ""))
        elif n > 1:
            c.fail("X3", t, "local_id %s 매핑이 여러 개 (기대 1개, 실제 %d개)" % (lid, n))
    known = {(run, lid) for lid in local_ids}
    for pair in sorted(pairs):
        if pair not in known:
            c.fail("X3", t, "추출에 없는 매핑 (%s, %s)" % pair)
    return t, "추출 local_id %d개가 매핑에 한 번씩 있음(관계 종류 미확인으로 매핑 제외 %d개)" % (
        len(local_ids) - len(exempt), len(exempt))


def _x4(c):
    t = c.graph_target
    if not c.need("X4", t, "graph"):
        return None
    doc = c.mapping_doc
    if not isinstance(doc, dict):
        c.fail("X4", t, "entity_mapping.json 없음 (기대 경로 %s)" % os.path.join(c.graph_dir, "entity_mapping.json"))
        return None
    for key in ("project_id", "graph_id", "graph_version", "input_runs"):
        if key not in doc or doc[key] != c.graph[key]:
            c.fail("X4", t, "entity_mapping.json의 %s가 graph.json과 다름 (기대 %r, 실제 %r)"
                   % (key, c.graph[key], doc.get(key, "없음")))

    def triples(items):
        return [(m["extraction_run_id"], m["local_id"], m["entity_id"]) for m in items]
    if triples(doc["entity_mapping"]) != triples(c.graph["entity_mapping"]):
        c.fail("X4", t, "entity_mapping.json의 (extraction_run_id, local_id, entity_id) 목록이 graph.json과 다름 "
                        "(기대 %d개, 실제 %d개)" % (len(c.graph["entity_mapping"]), len(doc["entity_mapping"])))
    return t, "entity_mapping.json = graph.json (%d개)" % len(doc["entity_mapping"])


def _x5(c):
    t = c.graph_target
    if not c.need("X5", t, "graph"):
        return None
    st = c.graph["validation"]["status"]
    if st != "passed":
        c.fail("X5", t, "validation.status %r (기대 'passed')" % st)
    return t, "validation.status passed"


# ---------------------------------------------------------------- 4.4 ③ → ④ (실행 사본 기준)
def _a1(c):
    a = c.analysis
    if a["analysis_run_id"] != c.run_folder:
        c.fail("A1", c.run_id, "폴더 이름과 analysis_run_id 다름 (기대 %s, 실제 %s)" % (c.run_folder, a["analysis_run_id"]))
    if a["region_ref"]["region_id"] != c.region_folder:
        c.fail("A1", c.run_id, "상위 폴더 이름과 region_ref.region_id 다름 (기대 %s, 실제 %s)"
               % (c.region_folder, a["region_ref"]["region_id"]))
    return c.run_id, "폴더 이름 = analysis_run_id·region_id"


def _a2(c):
    files = c.analysis["analysis_run"]["input_files"]
    inputs_dir = os.path.join(c.run_dir, "inputs")
    for f in files:
        role = f["role"]
        p = _join(inputs_dir, "%s.json" % role)
        actual = file_sha256(p) if p else None
        if actual is None:
            c.fail("A2", c.run_id, "inputs/%s.json 없음" % role)
        elif actual != f["sha256"]:
            c.fail("A2", c.run_id, "inputs/%s.json 해시 불일치 (기대 %s, 실제 %s)" % (role, h12(f["sha256"]), h12(actual)))
    return c.run_id, "입력 사본 %d개 해시 일치" % len(files)


def _a3(c):
    if not c.need("A3", c.run_id, "copy_graph", "copy_region"):
        return None
    ag = c.analysis["graph_ref"]
    a = (ag["graph_id"], ag["graph_version"])
    g = (c.copy_graph["graph_id"], c.copy_graph["graph_version"])
    rr = c.copy_region["graph_ref"]
    r = (rr["graph_id"], rr["graph_version"])
    if not a == g == r:
        c.fail("A3", c.run_id, "graph_ref 불일치 (분석 %s/%s, 사본 그래프 %s/%s, 사본 구간 %s/%s)" % (a + g + r))
    return c.run_id, "graph_ref %s/%s" % a


def _a4(c):
    if not c.need("A4", c.run_id, "copy_region"):
        return None
    ar = c.analysis["region_ref"]
    a = (ar["region_id"], ar["region_version"])
    r = (c.copy_region["region_id"], c.copy_region["region_version"])
    if a[0] != r[0]:
        c.fail("A4", c.run_id, "region_id 불일치 (분석 %s, 사본 %s)" % (a[0], r[0]))
    if _ver(a[1], "분석 region_version") != _ver(r[1], "사본 region_version"):
        c.fail("A4", c.run_id, "region_version 불일치 (분석 %s, 사본 %s)" % (a[1], r[1]))
    return c.run_id, "region_ref %s v%s" % a


def _a5(c):
    if not c.need("A5", c.run_id, "copy_graph"):
        return None
    nodes = {n["entity_id"]: n for n in c.copy_graph["nodes"]}
    rels = {e["entity_id"] for e in c.copy_graph["edges"]}
    scenarios = c.analysis["scenarios"]
    for s in scenarios:
        ge = s["graph_evidence"]
        bad = ["노드 %s" % n for n in ge["node_ids"] if n not in nodes]
        bad += ["관계 %s" % r for r in ge["relation_ids"] if r not in rels]
        bad += ["원인 설비 %s" % n for n in s["cause_equipment"] if n not in nodes]
        for g in s["safeguards"]:
            n = nodes.get(g["node_id"])
            if n is None:
                bad.append("보호수단 노드 %s" % g["node_id"])
            elif g.get("tag") != n.get("tag"):
                bad.append("보호수단 %s 태그 (기대 %r, 실제 %r)" % (g["node_id"], n.get("tag"), g.get("tag")))
        if bad:
            c.fail("A5", s["scenario_id"], "그래프에 없는 %s" % ", ".join(bad))
    return c.run_id, "시나리오 %d개 근거 ID가 사본 그래프에 있음" % len(scenarios)


def _a6(c):
    if not c.need("A6", c.run_id, "copy_graph"):
        return None
    g = c.copy_graph
    want = {"graph_id": g["graph_id"], "graph_version": g["graph_version"],
            "extraction_run_id": g["source"]["extraction_run_id"]}
    pairs = {(m["extraction_run_id"], m["local_id"]) for m in g["entity_mapping"]}
    n = 0
    for s in c.analysis["scenarios"]:
        for loc in s["source_locations"]:
            n += 1
            for key, val in want.items():
                if loc[key] != val:
                    c.fail("A6", s["scenario_id"], "source_locations의 %s가 실행 그래프와 다름 (기대 %s, 실제 %s)"
                           % (key, val, loc[key]))
            if (loc["extraction_run_id"], loc["local_id"]) not in pairs:
                c.fail("A6", s["scenario_id"], "source_locations의 (%s, %s)가 사본 그래프 매핑에 없음"
                       % (loc["extraction_run_id"], loc["local_id"]))
    return c.run_id, "source_locations %d개가 실행 그래프와 같음" % n


def _a7(c):
    if not c.need("A7", c.run_id, "copy_graph"):
        return None
    old = c.copy_graph["graph_version"]
    if not isinstance(c.graph, dict):
        c.add("A7", "WARN", c.run_id, "현재 그래프 없음(비교 불가, 실행은 당시 버전 %s 고정)" % old)
        return None
    cur = c.graph["graph_version"]
    if cur != old:
        c.add("A7", "WARN", c.run_id, "현재 그래프 %s는 실행 당시 %s와 다름(실행은 당시 버전 고정)" % (cur, old))
    return c.run_id, "현재 그래프 = 실행 당시 %s" % old


def _a8(c):
    if not c.need("A8", c.run_id, "copy_region"):
        return None
    old = _ver(c.copy_region["region_version"], "사본 region_version")
    if not isinstance(c.current_region, dict):
        c.add("A8", "WARN", c.run_id, "현재 구간 JSON 없음(비교 불가, 실행 당시 v%s)" % old)
        return None
    cur = _ver(c.current_region["region_version"], "현재 region_version")
    if cur > old:
        c.add("A8", "WARN", c.run_id, "구간이 실행 뒤 v%s → v%s로 바뀜" % (old, cur))
    elif cur < old:
        c.add("A8", "WARN", c.run_id, "현재 구간 v%s가 실행 당시 v%s보다 작음" % (cur, old))
    return c.run_id, "현재 구간 = 실행 당시 v%s" % old


# ---------------------------------------------------------------- 4.5 ④ → ⑤
def _no_reviews(c, cid):
    if not c.reviews:
        c.add(cid, "SKIP", c.run_id, NO_REVIEW_SKIP)
        return True
    return False


def _c1(c):
    if _no_reviews(c, "C1"):
        return None
    cands = {x["candidate_id"] for x in c.analysis["candidates"]}
    run_id = c.analysis["analysis_run_id"]
    n = 0
    for cid, v, doc in c.review_items():
        n += 1
        t = c.review_target(cid, v, doc)
        if doc["analysis_run_id"] != run_id:
            c.fail("C1", t, "analysis_run_id 불일치 (기대 %s, 실제 %s)" % (run_id, doc["analysis_run_id"]))
        if doc["candidate_id"] not in cands:
            c.fail("C1", t, "candidate_id가 분석에 없음 (%s)" % doc["candidate_id"])
        if doc["candidate_id"] != cid:
            c.fail("C1", t, "candidate_id가 폴더 이름과 다름 (기대 %s, 실제 %s)" % (cid, doc["candidate_id"]))
        if doc["review_id"] != "review-%s" % cid:
            c.fail("C1", t, "review_id 다름 (기대 review-%s, 실제 %s)" % (cid, doc["review_id"]))
    return c.run_id, "검토본 %d개 ID 일치" % n


def _c2(c):
    if _no_reviews(c, "C2"):
        return None
    n = 0
    for cid, v, doc in c.review_items():
        n += 1
        t = c.review_target(cid, v, doc)
        ref = doc["analysis_ref"]
        if ref["analysis_sha256"] != c.analysis_sha:
            c.fail("C2", t, "검토 뒤 analysis.json이 바뀜 (기록 %s, 현재 %s)" % (h12(ref["analysis_sha256"]),
                                                                       h12(c.analysis_sha)))
        for key in ("region_ref", "graph_ref"):
            if ref[key] != c.analysis[key]:
                c.fail("C2", t, "analysis_ref.%s가 분석과 다름 (기대 %s, 실제 %s)" % (key, c.analysis[key], ref[key]))
    return c.run_id, "검토본 %d개 analysis_ref 일치(analysis_sha256 %s)" % (n, h12(c.analysis_sha))


def _c3(c):
    if _no_reviews(c, "C3"):
        return None
    for cid in sorted(c.reviews):
        versions = c.reviews[cid]
        nums = sorted(versions)
        t = "review-%s" % cid
        if nums[0] < 1:
            c.fail("C3", t, "시작 버전이 v1이 아님 (%s 있음)" % ", ".join("v%d" % k for k in nums if k < 1))
        missing = [k for k in range(1, nums[-1] + 1) if k not in versions]
        if missing:
            c.fail("C3", t, "%s 없음 (%s만 있음)" % (", ".join("v%d" % k for k in missing),
                                                 ", ".join("v%d" % k for k in nums)))
        for k in nums:
            doc = versions[k]
            tk = "%s v%d" % (t, k)
            rv = _int_or_none(doc.get("review_version"))
            if rv is None:
                c.fail("C3", tk, "review_version을 정수로 바꿀 수 없음 (실제 %r)" % (doc.get("review_version"),))
            elif rv != k:
                c.fail("C3", tk, "review_version이 파일 번호와 다름 (기대 %d, 실제 %r)" % (k, doc["review_version"]))
            if k == 1:  # v1은 previous_review_version이 없거나 null
                if doc.get("previous_review_version") is not None:
                    c.fail("C3", tk, "previous_review_version 다름 (기대 None, 실제 %r)"
                           % (doc["previous_review_version"],))
            elif _int_or_none(doc.get("previous_review_version")) != k - 1:
                c.fail("C3", tk, "previous_review_version 다름 (기대 %d, 실제 %r)"
                       % (k - 1, doc.get("previous_review_version")))
    return c.run_id, "후보 %d개 검토본 버전이 v1부터 이어짐" % len(c.reviews)


def _c4(c):
    if _no_reviews(c, "C4"):
        return None
    scen = {s["scenario_id"]: s["candidate_id"] for s in c.analysis["scenarios"]}
    dics = {d["dic_id"]: d["candidate_id"] for d in c.analysis.get("design_improvement_candidates", [])}
    for cid, v, doc in c.review_items():
        t = c.review_target(cid, v, doc)
        for d in doc["scenario_decisions"]:
            sid = d["scenario_id"]
            if sid not in scen:
                c.fail("C4", t, "분석에 없는 시나리오 %s" % sid)
            elif scen[sid] != doc["candidate_id"]:
                c.fail("C4", t, "다른 후보의 시나리오 %s (기대 %s, 실제 %s)" % (sid, doc["candidate_id"], scen[sid]))
        for d in doc["design_improvement_decisions"]:
            did = d["dic_id"]
            if did not in dics:
                c.fail("C4", t, "분석에 없는 설계보완 후보 %s" % did)
            elif dics[did] != doc["candidate_id"]:
                c.fail("C4", t, "다른 후보의 설계보완 후보 %s (기대 %s, 실제 %s)" % (did, doc["candidate_id"], dics[did]))
    return c.run_id, "결정 항목이 모두 그 후보 소속"


def _c5(c):
    if _no_reviews(c, "C5"):
        return None
    for cid, v, doc in c.review_items():
        again = review_record.compute_review_status(c.analysis, doc["candidate_id"], doc)
        if doc["review_status"] != again:
            c.fail("C5", c.review_target(cid, v, doc), "review_status %r이나 재계산 %r" % (doc["review_status"], again))
    return c.run_id, "review_status = 재계산 값"


# ---------------------------------------------------------------- 4.6 ⑤ 출력 기록
def _no_exports(c, cid):
    if not c.exports:
        c.add(cid, "SKIP", c.run_id, NO_EXPORT_SKIP)
        return True
    return False


def _e1(c):
    if _no_exports(c, "E1"):
        return None
    for stem, doc in c.exports:
        t, tg = c.export_target(stem, doc), doc["target"]
        if tg["analysis_run_id"] != c.analysis["analysis_run_id"]:
            c.fail("E1", t, "analysis_run_id 불일치 (기대 %s, 실제 %s)" % (c.analysis["analysis_run_id"],
                                                                     tg["analysis_run_id"]))
        if tg["analysis_sha256"] != c.analysis_sha:
            c.fail("E1", t, "analysis_sha256 불일치 (기대 %s, 실제 %s)" % (h12(c.analysis_sha), h12(tg["analysis_sha256"])))
        for key in ("region_ref", "graph_ref"):
            if tg[key] != c.analysis[key]:
                c.fail("E1", t, "%s 불일치 (기대 %s, 실제 %s)" % (key, c.analysis[key], tg[key]))
    return c.run_id, "출력 기록 %d개 대상 일치" % len(c.exports)


def _e2(c):
    if _no_exports(c, "E2"):
        return None
    for stem, doc in c.exports:
        t = c.export_target(stem, doc)
        for r in doc["target"]["reviews"]:
            cid, v = r["candidate_id"], _int_or_none(r["review_version"])
            if v is None:
                c.fail("E2", t, "검토본 %s의 review_version을 정수로 바꿀 수 없음 (실제 %r)" % (cid, r["review_version"]))
                continue
            rec = c.reviews.get(cid, {}).get(v) if isinstance(cid, str) else None
            if rec is None:
                c.fail("E2", t, "검토본 %s v%s 없음" % (cid, v))
            elif rec["review_status"] != r["review_status"]:
                c.fail("E2", t, "검토본 %s v%s review_status 다름 (기대 %r, 실제 %r)"
                       % (cid, v, r["review_status"], rec["review_status"]))
    return c.run_id, "출력 기록이 가리키는 검토본 있음·상태 일치"


def _e3(c):
    if _no_exports(c, "E3"):
        return None
    for stem, doc in c.exports:
        t = c.export_target(stem, doc)
        f = doc["file"]
        if not isinstance(f, str) or not f:
            c.fail("E3", t, "file 값 없음 (실제 %r)" % (f,))
            continue
        actual = file_sha256(_resolve(f, c.work_root))
        if actual is None:
            c.add("E3", "WARN", t, "워크시트 파일 없음(삭제됨, 해시 확인 불가): %s" % f)
        elif actual != doc["file_sha256"]:
            c.fail("E3", t, "워크시트 파일 해시 불일치 (기대 %s, 실제 %s)" % (h12(doc["file_sha256"]), h12(actual)))
    return c.run_id, "워크시트 파일 해시 일치"


def _e4(c):
    if _no_exports(c, "E4"):
        return None
    cands = {x["candidate_id"]: x for x in c.analysis["candidates"]}
    scen = {s["scenario_id"]: s for s in c.analysis["scenarios"]}
    dics = {d["dic_id"]: d for d in c.analysis.get("design_improvement_candidates", [])}
    count = collections.Counter(s["candidate_id"] for s in c.analysis["scenarios"])
    for stem, doc in c.exports:
        t = c.export_target(stem, doc)
        for r in doc["rows"]["worksheet"]:
            row, cid, sid = r["row"], r["candidate_id"], r["scenario_id"]
            if cid not in cands:
                c.fail("E4", t, "행 %s의 candidate_id %s가 분석에 없음" % (row, cid))
            elif sid is None:
                if cands[cid]["selection_status"] != "selected" or count[cid]:
                    c.fail("E4", t, "행 %s는 시나리오 없음 행이나 %s에 시나리오 %d개(선택 상태 %s)"
                           % (row, cid, count[cid], cands[cid]["selection_status"]))
            elif sid not in scen:
                c.fail("E4", t, "행 %s의 scenario_id가 분석에 없음 (%s)" % (row, sid))
            elif scen[sid]["candidate_id"] != cid:
                c.fail("E4", t, "행 %s의 %s은 %s 소속이 아님 (실제 %s 소속)" % (row, sid, cid, scen[sid]["candidate_id"]))
        for r in doc["rows"]["recommendations"]:
            no, did = r["no"], r["dic_id"]
            bad = []
            if r["candidate_id"] not in cands:
                bad.append("candidate_id %s가 분석에 없음" % r["candidate_id"])
            if r["scenario_id"] not in scen:
                bad.append("scenario_id %s가 분석에 없음" % r["scenario_id"])
            if did not in dics:
                bad.append("dic_id %s가 분석에 없음" % did)
            elif (dics[did]["scenario_id"], dics[did]["candidate_id"]) != (r["scenario_id"], r["candidate_id"]):
                bad.append("%s 소속 불일치 (기대 %s/%s, 실제 %s/%s)" % (did, dics[did]["scenario_id"],
                                                                 dics[did]["candidate_id"], r["scenario_id"],
                                                                 r["candidate_id"]))
            for b in bad:
                c.fail("E4", t, "권고 행 %s의 %s" % (no, b))
    return c.run_id, "출력 행의 ID·소속 일치"


def _e5(c):
    if _no_exports(c, "E5"):
        return None
    if c.analysis["validation"]["status"] == "blocked":
        c.fail("E5", c.run_id, "blocked 분석 결과에 출력 기록 있음 (%d개)" % len(c.exports))
    return c.run_id, "분석 validation.status %s" % c.analysis["validation"]["status"]


def _e6(c):
    if not c.compares:
        c.add("E6", "SKIP", c.run_id, NO_COMPARE_SKIP)
        return None
    for stem, doc in c.compares:
        t = doc.get("comparison_id") if isinstance(doc.get("comparison_id"), str) else stem
        sha = doc["target"]["analysis_sha256"]
        if sha != c.analysis_sha:
            c.fail("E6", t, "비교 뒤 analysis.json이 바뀜 (기대 %s, 실제 %s)" % (h12(c.analysis_sha), h12(sha)))
    return c.run_id, "평가 비교 보고 %d개 analysis_sha256 일치" % len(c.compares)


# ---------------------------------------------------------------- 4.7 확인 수준 전달
def _k1(c):
    t = c.graph_target
    if not c.need("K1", t, "extraction", "graph"):
        return None
    ent = {m["local_id"]: m["entity_id"] for m in c.graph["entity_mapping"]}
    nodes = {n["entity_id"]: n for n in c.graph["nodes"]}
    gunk = c.graph["validation"]["unknowns"]
    unresolved = {u["local_id"] for u in c.graph["unresolved"]}
    flow_items = collections.Counter(u["target"] for u in gunk
                                     if u["check"] == "unknown_flow_direction" and u.get("field") == "flow_direction"
                                     and u.get("origin") != "extraction")
    expected, ext_n = collections.Counter(), 0
    for u in c.extraction["validation"]["unknowns"]:
        ext_n += 1
        if u["check"] == "unknown_flow_direction":
            lid = u["target"]
            eid = ent.get(lid)
            if eid is None:
                if lid not in unresolved:
                    c.fail("K1", lid or t, "흐름 방향 미확인 대상이 매핑에도 그래프 unresolved에도 없음")
            elif eid.startswith("entity-seg-"):
                if flow_items[eid] != 1:
                    c.fail("K1", lid, "흐름 방향 미확인이 구간 노드 %s에 다시 기록되지 않음 (기대 1개, 실제 %d개)"
                           % (eid, flow_items[eid]))
            elif eid.startswith("relation-"):
                c.add("K1", "WARN", lid, "직접 관계 %s의 흐름 방향 미확인이 그래프 unknowns에 다시 기록되지 않음(방어 규칙)" % eid)
            else:
                c.fail("K1", lid, "흐름 방향 미확인 대상이 구간·관계가 아닌 %s로 매핑됨" % eid)
            continue
        expected[(u["check"], u.get("field"), u.get("source_object_id"), u.get("target"))] += 1
    actual = collections.Counter()
    for g in gunk:
        if g.get("origin") != "extraction":
            continue
        key = (g["check"], g.get("field"), g.get("source_object_id"), g.get("local_id"))
        actual[key] += 1
        want = ent.get(g.get("local_id"))
        if g.get("target") != want:
            c.fail("K1", t, "추출 미확인 %s/%s(local_id %s)의 target이 매핑과 다름 (기대 %r, 실제 %r)"
                   % (key[0], key[1], key[3], want, g.get("target")))
    for key in sorted(set(expected) | set(actual), key=repr):
        if expected[key] != actual[key]:
            what = "%s/%s" % (key[0], key[1]) + (" (local_id %s)" % key[3] if key[3] else "")
            c.fail("K1", t, "추출 미확인 %s가 그래프에 %s (기대 %d개, 실제 %d개)"
                   % (what, "없음" if not actual[key] else "개수 다름", expected[key], actual[key]))
    for g in gunk:  # 반대 방향: 그래프의 흐름 방향 미확인은 대상 구간의 flow_direction이 null일 때만
        if g["check"] == "unknown_flow_direction" and g.get("origin") != "extraction":
            n = nodes.get(g["target"])
            if n is None or n.get("node_type") != "pipe_segment":
                c.fail("K1", g["target"] or t, "흐름 방향 미확인 대상이 그래프 배관 구간 노드가 아님")
            elif n.get("flow_direction") is not None:
                c.fail("K1", g["target"], "흐름 방향이 있는 구간에 흐름 방향 미확인 기록")
    if c.path == "samples":
        have = collections.Counter(g.get("field") for g in gunk
                                   if g.get("origin") == "extraction" and g["check"] == "not_registered")
        miss = [f for f in NOT_REGISTERED_FIELDS if have[f] != 1]
        if miss:
            c.fail("K1", t, "추출 미확인 not_registered/%s가 그래프에 없음 (기대 1개씩, 실제 %s)"
                   % (",".join(miss), {f: have[f] for f in miss}))
        else:
            c.add("K1", "PASS", t, "샘플 경로 not_registered %d건(%s)이 그래프로 이어짐"
                  % (len(NOT_REGISTERED_FIELDS), ", ".join(NOT_REGISTERED_FIELDS)))
    if not any(r["id"] == "K1" and r["level"] in ("FAIL", "WARN") for r in c.results):
        c.add("K1", "PASS", t, "추출 미확인 %d건이 그래프 미확인으로 이어짐" % ext_n)
    return None


def _k2(c):
    t = c.graph_target
    if not c.need("K2", t, "extraction", "graph"):
        return None
    ent = {m["local_id"]: m["entity_id"] for m in c.graph["entity_mapping"]}
    rels = {r["local_id"]: r for r in c.extraction["relations"]}
    targets = [n for n in c.graph["nodes"] if n.get("node_type") == "pipe_segment"]
    targets += [e for e in c.graph["edges"] if e["entity_id"].startswith("relation-") and "flow_direction" in e]
    n = 0
    for obj in targets:
        gf = obj.get("flow_direction")
        if gf is None:
            continue
        n += 1
        r = rels.get(obj["local_id"])
        fd = r.get("flow_direction") if r else None
        if not fd:
            c.fail("K2", obj["entity_id"], "추출에 없는 흐름 방향 (local_id %s)" % obj["local_id"])
            continue
        want = {"from": ent.get(fd["from"]), "to": ent.get(fd["to"]), "from_end": fd["from_end"],
                "to_end": fd["to_end"], "basis": fd["basis"]}
        got = {k: gf.get(k) for k in FLOW_KEYS}
        if got != want:
            c.fail("K2", obj["entity_id"], "흐름 방향이 추출과 다름 (기대 %s, 실제 %s)" % (want, got))
    # 체크밸브 허용 방향: 그래프 check_direction이 있으면 추출 판정(local_id -> entity_id)과 같아야 함
    ext_nodes = {x["local_id"]: x for x in c.extraction["nodes"]}
    cv = 0
    for node in c.graph["nodes"]:
        gcd = node.get("check_direction")
        if gcd is None:
            continue
        cv += 1
        cd = ext_nodes.get(node.get("local_id"), {}).get("check_direction")
        if not cd:
            c.fail("K2", node["entity_id"], "추출에 없는 체크밸브 허용 방향 (local_id %s)" % node.get("local_id"))
            continue
        want = {"inlet": ent.get(cd["inlet"]), "outlet": ent.get(cd["outlet"])}
        got = {k: gcd.get(k) for k in ("inlet", "outlet")}
        if got != want:
            c.fail("K2", node["entity_id"], "체크밸브 입구·출구가 추출 판정과 다름 (기대 %s, 실제 %s)" % (want, got))
        want = {"basis": list(cd["basis"]), "status": cd["status"]}
        got = {k: gcd.get(k) for k in ("basis", "status")}
        if got != want:
            c.fail("K2", node["entity_id"], "체크밸브 근거·상태가 추출 판정과 다름 (기대 %s, 실제 %s)" % (want, got))
    # 반대 방향: 추출에는 판정이 있는데 그래프 노드에서 빠졌으면 FAIL(빌더 전달 누락)
    graph_by_local = {x.get("local_id"): x for x in c.graph["nodes"]}
    for lid, x in ext_nodes.items():
        if x.get("check_direction") and lid in graph_by_local and graph_by_local[lid].get("check_direction") is None:
            c.fail("K2", graph_by_local[lid]["entity_id"], "그래프에 없는 체크밸브 허용 방향 (추출 local_id %s)" % lid)
    return t, "흐름 방향 %d개, 체크밸브 허용 방향 %d개가 추출과 같음" % (n, cv)


def _k3(c):
    if not c.need("K3", c.run_id, "copy_graph"):
        return None
    members = set(c.analysis["analysis_run"]["region_members"])
    nodes = {x["entity_id"]: x for x in c.copy_graph["nodes"]}
    expected = collections.Counter()
    for u in c.copy_graph["validation"]["unknowns"]:
        if u.get("target") is None or u["target"] in members:
            expected[(u.get("target") or "그래프 전체", "%s 미확인" % u.get("field"))] += 1
    actual = collections.defaultdict(list)
    for h in c.analysis["holds"]:
        if h["source"] != "graph" or h["candidate_id"] is not None:
            continue
        n = nodes.get(h["scope"])
        if (n is not None and n.get("category") == "valve" and (n.get("attributes") or {}).get("normal_position") is None
                and h["item"] == "%s 정상 위치 미확인" % (n.get("tag") or h["scope"])):
            continue  # 밸브 정상 위치 보류는 그래프 미확인과 대응하지 않음(_run_level_holds)
        actual[(h["scope"], h["item"])].append(h["hold_id"])
    for key in sorted(set(expected) | set(actual), key=repr):
        e, a = expected[key], len(actual.get(key, []))
        if a < e:
            c.fail("K3", c.run_id, "그래프 미확인 (%s, %s)에 대응 보류 %d개(기대 %d개)" % (key + (a, e)))
        elif a > e:
            c.add("K3", "WARN", c.run_id, "근거 미확인이 없는 graph 보류 %s (%s, %s)"
                  % (", ".join(actual[key][e:]), key[0], key[1]))
    return c.run_id, "그래프 미확인 %d건과 graph 보류가 1:1" % sum(expected.values())


def _k4(c):
    if not c.need("K4", c.run_id, "copy_region"):
        return None
    reg = c.copy_region
    expected = collections.Counter()
    if reg["design_intent"].get("knowledge_status") != "confirmed":
        expected[("구간 설계 의도", "설계 의도 미확정")] += 1
    for cond in reg.get("normal_operating_conditions") or []:
        if cond.get("knowledge_status") != "confirmed":
            expected[("운전조건", cond["item"])] += 1
    actual = collections.Counter((h["scope"], h["item"]) for h in c.analysis["holds"] if h["source"] == "input")
    for key in sorted(set(expected) | set(actual), key=repr):
        if expected[key] != actual[key]:
            c.fail("K4", c.run_id, "(%s, %s) 보류 %d개(기대 %d개)" % (key + (actual[key], expected[key])))
    return c.run_id, "구간 미확정 %d건과 input 보류가 1:1" % sum(expected.values())


def _k5(c):
    scenarios = c.analysis["scenarios"]
    for s in scenarios:
        if s["knowledge_status"] != "hypothesis":
            c.fail("K5", s["scenario_id"], "knowledge_status %r (기대 'hypothesis')" % s["knowledge_status"])
    return c.run_id, "시나리오 %d개 모두 hypothesis" % len(scenarios)


def _k6(c):
    for s in c.analysis["scenarios"]:
        rp = s["risk_proposal"]
        if rp["status"] != "proposed" and rp.get("risk") is not None:
            c.fail("K6", s["scenario_id"], "%s 위험도에 등급 %r" % (rp["status"], rp["risk"]))
    for cand in c.analysis["candidates"]:
        if cand["selection_status"] == "excluded":
            st = _get(cand, "risk_proposal", "status")
            if st != "not_applicable":
                c.fail("K6", cand["candidate_id"], "제외 후보의 위험도 상태 (기대 'not_applicable', 실제 %r)" % st)
    return c.run_id, "보류 위험도에 등급 없음, 제외 후보 not_applicable"


CHECKS = (("G1", _g1), ("G2", _g2),
          ("R1", _r1), ("R2", _r2), ("R3", _r3), ("R4", _r4),
          ("X1", _x1), ("X2", _x2), ("X3", _x3), ("X4", _x4), ("X5", _x5),
          ("A1", _a1), ("A2", _a2), ("A3", _a3), ("A4", _a4), ("A5", _a5), ("A6", _a6), ("A7", _a7), ("A8", _a8),
          ("C1", _c1), ("C2", _c2), ("C3", _c3), ("C4", _c4), ("C5", _c5),
          ("E1", _e1), ("E2", _e2), ("E3", _e3), ("E4", _e4), ("E5", _e5), ("E6", _e6),
          ("K1", _k1), ("K2", _k2), ("K3", _k3), ("K4", _k4), ("K5", _k5), ("K6", _k6))
CHECK_IDS = tuple(cid for cid, _ in CHECKS)


def _run_checks(c):
    for cid, fn in CHECKS:
        start = len(c.results)
        try:
            out = fn(c)
        except _FIELD_ERRORS as exc:
            c.fail(cid, c.run_id, "필드 누락·형식 오류로 검사 불가(오래된 형식 또는 검사 오류): %s: %s"
                   % (type(exc).__name__, exc))
            continue
        except OSError as exc:  # 권한 없음 등 파일 접근 실패: 결과가 아니라 실행 오류(종료 코드 2)
            c.errors.append("파일 접근 실패(%s): %s" % (cid, exc))
            continue
        if out is not None and not any(r["id"] == cid for r in c.results[start:]):
            c.add(cid, "PASS", out[0], out[1])


def _chain_doc(c):
    a = c.analysis if isinstance(c.analysis, dict) else {}
    graph_ref = a.get("graph_ref") if isinstance(a.get("graph_ref"), dict) else None
    return {"path": c.path, "region_id": _get(a, "region_ref", "region_id") or c.region_folder,
            "analysis_run_id": c.run_id, "graph_ref": graph_ref,
            "extraction_run_id": _get(c.copy_graph, "source", "extraction_run_id"),
            "material_ref": None if c.path == "samples" else {"material_id": c.material_id,
                                                               "registration_version": c.registration_version},
            "results": c.results, "errors": c.errors}


# ---------------------------------------------------------------- 연쇄 찾기·실행
def _region_files(work_root, errors):
    """데이터/구간/*.json → {region_id: 경로}. region_id가 없으면 파일 이름 줄기."""
    folder = os.path.join(work_root, "데이터", "구간")
    out = {}
    if not os.path.isdir(folder):
        return out
    try:
        names = sorted(os.listdir(folder))
    except OSError as exc:
        errors.append("파일 접근 실패: %s (%s)" % (folder, exc))
        return out
    for fname in names:
        if not fname.endswith(".json"):
            continue
        path = os.path.join(folder, fname)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except OSError as exc:
            errors.append("파일 접근 실패: %s (%s)" % (path, exc))
            continue
        except ValueError as exc:
            errors.append("JSON 읽기 실패: %s (%s)" % (path, exc))
            continue
        if not isinstance(doc, dict):
            errors.append("JSON 객체가 아님: %s (%s)" % (path, type(doc).__name__))
            continue
        rid = doc.get("region_id")
        out.setdefault(rid if isinstance(rid, str) and rid else fname[:-5], path)
    return out


def check(work_root=None, store_root=None, region=None, run="latest"):
    """연쇄를 찾아 검사한다. 반환 {"roots", "chains", "errors", "notes"}.
    입력 폴더 없음·지정한 구간/실행 없음은 ContractError(종료 코드 2)."""
    work_root = os.path.abspath(work_root or paths.work_root())
    store_root = os.path.abspath(store_root or os.environ.get(paths.ENV_STORE_ROOT)
                                 or os.path.join(work_root, "자료저장소"))
    run = run or "latest"
    errors, notes = [], []
    analysis_root = os.path.join(work_root, "출력", "분석")
    if not os.path.isdir(analysis_root):
        raise ContractError("입력 폴더 없음: %s" % analysis_root)
    region_files = _region_files(work_root, errors)
    if region:
        regions = [region]
        if not os.path.isdir(os.path.join(analysis_root, region)):
            raise ContractError("구간의 분석 폴더 없음: %s" % os.path.join(analysis_root, region))
    else:
        regions = sorted(region_files)
    chains = []
    found_run = False
    for rid in regions:
        rdir = _join(analysis_root, rid)
        if not rdir or not os.path.isdir(rdir):
            notes.append("%s: 분석 실행 없음" % rid)
            continue
        try:
            runs = sorted((d for d in os.listdir(rdir) if os.path.isdir(os.path.join(rdir, d))), key=_run_sort_key)
        except OSError as exc:
            errors.append("파일 접근 실패: %s (%s)" % (rdir, exc))
            continue
        if run == "latest":
            # 최신 = analysis.json이 있는 실행 폴더 중 시각이 가장 늦은 것. 미완성 폴더는 참고로만 알린다.
            done = [d for d in runs if os.path.isfile(os.path.join(rdir, d, "analysis.json"))]
            later = [d for d in runs if d not in done and (not done or _run_sort_key(d) > _run_sort_key(done[-1]))]
            notes += ["%s: analysis.json 없는(미완성) 실행 폴더 %s — latest 대상에서 제외" % (rid, d) for d in later]
            runs = done[-1:]
        elif run == "all":
            # all도 latest와 같은 규칙: analysis.json 없는 폴더는 참고로 알리고 건너뜀(총괄 판정 2026-11-06).
            # 지정 실행 ID에 analysis.json이 없을 때만 실행 오류(2).
            done = [d for d in runs if os.path.isfile(os.path.join(rdir, d, "analysis.json"))]
            notes += ["%s: analysis.json 없는(미완성) 실행 폴더 %s — all 대상에서 제외" % (rid, d)
                      for d in runs if d not in done]
            runs = done
        else:
            runs = [d for d in runs if d == run]
        if not runs:
            if run in ("latest", "all"):
                notes.append("%s: 분석 실행 없음" % rid)
            continue
        found_run = True
        for name in runs:
            c = _Chain(work_root, store_root, os.path.join(rdir, name), region_files.get(rid))
            if isinstance(c.analysis, dict):
                _run_checks(c)
            chains.append(_chain_doc(c))
    if run not in ("latest", "all") and not found_run:
        raise ContractError("지정한 분석 실행 없음: %s" % run)
    return {"roots": {"work_root": work_root, "store_root": store_root}, "chains": chains,
            "errors": errors + [e for ch in chains for e in ch["errors"]], "notes": notes}


# ---------------------------------------------------------------- 출력
def counts(result):
    out = {lv: 0 for lv in LEVELS}
    for ch in result["chains"]:
        for r in ch["results"]:
            out[r["level"]] += 1
    return out


def exit_code(result):
    """0 = FAIL 없음, 1 = FAIL 1개 이상, 2 = 실행 오류."""
    if result["errors"]:
        return 2
    return 1 if counts(result)["FAIL"] else 0


def format_line(r):
    return "[%s] %s %s: %s" % (r["level"], r["id"], r["target"], r["message"])


def summary_line(result):
    n = counts(result)
    return "요약: " + " · ".join("%s %d" % (lv, n[lv]) for lv in LEVELS)


def render_console(result):
    lines = []
    for ch in result["chains"]:
        lines.append("== %s / %s (%s 경로)" % (ch["region_id"], ch["analysis_run_id"],
                                             "샘플" if ch["path"] == "samples" else "등록"))
        lines += [format_line(r) for r in ch["results"]]
        lines += ["[ERROR] %s" % e for e in ch["errors"]]
    lines += ["참고: %s" % n for n in result["notes"]]
    chain_errors = {e for ch in result["chains"] for e in ch["errors"]}
    lines += ["[ERROR] %s" % e for e in result["errors"] if e not in chain_errors]
    lines.append(summary_line(result))
    return lines


def report_doc(result, checked_at=None):
    """§5 보고 JSON. errors(실행 오류 목록)·notes(미완성 실행 폴더 등 참고)는 기획 예시에 없는 추가 필드다."""
    checked_at = checked_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chains = [{k: v for k, v in ch.items() if k != "errors"} for ch in result["chains"]]
    return {"schema_version": SCHEMA_VERSION, "check": "contract", "check_version": CHECK_VERSION,
            "checked_at": checked_at, "roots": result["roots"], "chains": chains, "summary": counts(result),
            "errors": result["errors"], "notes": result["notes"]}


def _inside(path, folder):
    """path가 folder 안이면 True. realpath 공통 경로 검사에 더해, abspath에서 위로 올라가며 이미 있는 상위마다
    os.path.samefile(상위, folder)로 비교한다(긴 경로 접두, localhost 관리 공유 UNC 등 표기만 다른 같은 폴더 포함)."""
    try:
        if os.path.commonpath([os.path.realpath(path), os.path.realpath(folder)]) == os.path.realpath(folder):
            return True
    except ValueError:  # 다른 드라이브·표기 방식
        pass
    if not os.path.exists(folder):
        return False
    cur = os.path.abspath(path)
    while True:
        if os.path.exists(cur):
            try:
                if os.path.samefile(cur, folder):
                    return True
            except OSError:
                pass
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent


def _link_in_path(path):
    """경로(절대)와 그 상위 중 이미 있는 것에 심볼릭 링크·정션이 있으면 그 경로, 없으면 None.
    realpath가 abspath와 다르면(다른 재분석 지점 등) 그것도 링크로 본다."""
    cur = os.path.abspath(path)
    while True:
        if os.path.lexists(cur) and (os.path.islink(cur) or os.path.isjunction(cur)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    absp = os.path.abspath(path)
    if os.path.normcase(os.path.realpath(absp)) != os.path.normcase(absp):
        return absp
    return None


def write_report(result, path, checked_at=None):
    """보고 JSON을 새 파일로 쓴다(키 정렬, 끝 줄바꿈). ContractError(종료 코드 2):
    - 실제 경로(realpath)가 입력 폴더(<작업 루트>/출력·데이터, 저장 루트) 안
    - 경로나 그 상위에 심볼릭 링크·정션이 있음
    - 같은 이름 파일이 이미 있음(덮어쓰지 않음)
    - 드라이브 뒤 경로에 ':'가 있음(NTFS 대체 데이터 스트림)"""
    roots = result["roots"]
    tail = os.path.splitdrive(os.path.abspath(path))[1]
    if ":" in tail:  # NTFS 대체 데이터 스트림(예: 출력:e.json) 등
        raise ContractError("보고 파일 경로의 드라이브 뒤에 ':'가 있어 거부함: %s" % path)
    link = _link_in_path(path)
    if link:
        raise ContractError("보고 파일 경로에 링크·정션이 있어 거부함: %s (%s)" % (path, link))
    for folder in (os.path.join(roots["work_root"], "출력"), os.path.join(roots["work_root"], "데이터"),
                   roots["store_root"]):
        if _inside(path, folder):
            raise ContractError("보고 파일 경로가 입력 폴더 안이라 거부함: %s (입력 폴더 %s)" % (path, folder))
    if os.path.lexists(path):
        raise ContractError("보고 파일이 이미 있음(덮어쓰지 않음): %s" % path)
    doc = report_doc(result, checked_at)
    parent = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(parent, exist_ok=True)
        with open(path, "x", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        raise ContractError("보고 파일 쓰기 실패: %s (%s)" % (path, exc))
    return path
