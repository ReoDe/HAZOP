"""엔티티 연결 검사 L1~L4를 한 번에 실행한다 (QA용). 하위 프로세스·네트워크를 쓰지 않는다.

근거: 기획서/그래프활용.md §3(후보 생성·확인 흐름), §7.2 L1~L4.
정상 샘플(data/knowledge-graph/SNP-SAMPLE)은 읽기만 하고, 쓰기가 필요한 판정은 임시 폴더에 복사해서 한다.
P&ID 그래프는 output/graph/SNP-M-102/graph.json (없으면 먼저 build_graph.py).
L3의 V5·알고리즘 결과 제외는 W5(hazop/kg/algo.py) 범위라 여기서는 V4(compute_view)만 판정한다.
종료 코드 0 = 전부 통과.
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from hazop.console import safe_console  # noqa: E402

import build_kg  # noqa: E402
from hazop.kg import build, inputs, link  # noqa: E402

SAMPLE_PROJECT = "SNP-SAMPLE"
SAMPLE_DIR = os.path.join(build_kg.DEFAULT_INPUT_ROOT, SAMPLE_PROJECT)
SAMPLE_GRAPH = "graph-SNP-M-102"


def copy_sample(sample_dir):
    tmp = tempfile.mkdtemp()
    dst = os.path.join(tmp, SAMPLE_PROJECT)
    shutil.copytree(sample_dir, dst)
    return tmp, dst


def build_dir(input_dir, graphs):
    k = inputs.load_knowledge(os.path.join(input_dir, link.NODES_CSV), os.path.join(input_dir, link.LINKS_CSV),
                              SAMPLE_PROJECT)
    return build.build_kg(k, graphs)


def edit_nodes(input_dir, node_id, **changes):
    """임시 폴더의 knowledge_nodes.csv에서 노드 한 개의 값을 바꿔 다시 쓴다."""
    path = os.path.join(input_dir, link.NODES_CSV)
    rows = inputs.read_csv(path, inputs.NODE_COLUMNS)
    for r in rows:
        if r["id"] == node_id:
            r.update(changes)
    link.write_atomic(path, ",".join(inputs.NODE_COLUMNS) + "\n" + link._csv_text(inputs.NODE_COLUMNS, rows))


def links_count(input_dir):
    return len(inputs.read_csv(os.path.join(input_dir, link.LINKS_CSV), inputs.LINK_COLUMNS))


def file_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _by(rows, text):
    return [r for r in rows if r["match_text"] == text]


def check_l1(sample_dir, graphs):
    res = []
    nodes = inputs.read_csv(os.path.join(sample_dir, link.NODES_CSV), inputs.NODE_COLUMNS)
    gen = link.generate(nodes, graphs)
    c = gen["candidates"]
    texts = {n["id"]: inputs.normalize_text(n["text"]) for n in nodes if n["text"]}
    pv, pz, l011 = _by(c, "RC-PV101"), _by(c, "RC-PZ1"), _by(c, "RC-L011")
    res.append(("L1", "모든 후보가 link_status=candidate로 시작, 처리기 이름·점수 기록",
                bool(c) and all(r["link_status"] == "candidate" and r["extractor"] == link.EXTRACTOR
                                and r["confidence"] for r in c)))
    res.append(("L1", "정확 일치 RC-PV101 -> exact_norm 1.0, 비모호, target_ref graph_id:tag",
                len(pv) == 1 and pv[0]["method"] == "exact_norm" and pv[0]["confidence"] == "1.000"
                and pv[0]["ambiguous"] == "false" and pv[0]["target_ref"] == SAMPLE_GRAPH + ":RC-PV101"))
    res.append(("L1", "0 채움 차이 RC-PZ1 -> RC-PZ01 fuzzy, 점수 < 1",
                len(pz) == 1 and pz[0]["method"] == "fuzzy" and pz[0]["target_tag"] == "RC-PZ01"
                and float(pz[0]["confidence"]) < 1))
    res.append(("L1", "없는 태그 RC-V999 -> 후보 없음, 도면에 없는 언급으로 보고",
                not _by(c, "RC-V999") and [u["match_text"] for u in gen["unmatched"]] == ["RC-V999"]))
    res.append(("L1", "동명 태그 RC-L011 -> 후보 3개, 서로 다른 source_object_id·관계 ID, ambiguous, graph_id#source_object_id",
                len(l011) == 3 and len({r["target_source_object_id"] for r in l011}) == 3
                and len({link.relation_id(r["candidate_key"]) for r in l011}) == 3
                and all(r["ambiguous"] == "true" and "#" in r["target_ref"] for r in l011)))
    res.append(("L1", "위치는 normalize_text(원문) 기준, 후보 키 = 행 값, 같은 입력이면 같은 결과",
                all(texts[r["chunk_id"]][int(r["match_start"]):int(r["match_end"])] == r["match_text"]
                    and r["candidate_key"] == link.candidate_key(r) for r in c)
                and link.generate(nodes, graphs) == gen))
    return res


def check_l2(sample_dir, graphs):
    res = []
    tmp, d = copy_sample(sample_dir)
    try:
        cpath = os.path.join(d, link.CANDIDATES_CSV)
        before = file_bytes(cpath)
        link.run_generate(d, graphs)
        res.append(("L2", "판단이 든 후보 CSV에서 재실행 -> 바이트 그대로(판단 보존, 중복 없음)", file_bytes(cpath) == before))
        rows = link.read_candidates(cpath)
        for r in rows:
            if r["match_text"] == "RC-PIC110":
                r.update(link_status="confirmed", reviewed_by="검사자", reviewed_at="2026-11-05", reason="L2")
            if r["target_source_object_id"] == "e13":
                r.update(link_status="rejected", reviewed_by="검사자", reviewed_at="2026-11-05", reason="L2")
        link.write_candidates(cpath, rows)
        link.run_generate(d, graphs)
        again = link.read_candidates(cpath)
        st = {r["candidate_key"]: r["link_status"] for r in again}
        res.append(("L2", "confirmed·rejected 판단이 재실행에 덮어써지지 않고 행 수·키 중복 없음",
                    st == {r["candidate_key"]: r["link_status"] for r in rows} and len(again) == len(rows) == len(st)))
        n0 = links_count(d)
        a1 = link.run_apply(d, graphs)
        n1 = links_count(d)
        a2 = link.run_apply(d, graphs)
        n2 = links_count(d)
        added = a1["add"]
        rej = [r for r in again if r["link_status"] == "rejected"]
        link_ids = {r["id"] for r in inputs.read_csv(os.path.join(d, link.LINKS_CSV), inputs.LINK_COLUMNS)}
        res.append(("L2", "확인분 반영 1건(RC-PIC110) -> 두 번째 반영은 0건, knowledge_links 행 수 그대로, 기각분은 들어가지 않음",
                    len(added) == 1 and n1 == n0 + 1 and not a2["add"] and n2 == n1
                    and not any(link.relation_id(r["candidate_key"]) in link_ids for r in rej)))
        row = added[0] if added else {}
        res.append(("L2", "반영 행: mentions, link_status·knowledge_status confirmed, reviewed_by, ID = krel-m-+sha256(키)[:8]",
                    row.get("kind") == "mentions" and row.get("link_status") == "confirmed"
                    and row.get("knowledge_status") == "confirmed" and row.get("reviewed_by") == "검사자"
                    and row.get("id") == link.relation_id(row.get("candidate_key") or "")))
    finally:
        shutil.rmtree(tmp)
    return res


def check_l3(sample_dir, graphs):
    res = []
    tmp, d = copy_sample(sample_dir)
    try:
        cpath = os.path.join(d, link.CANDIDATES_CSV)
        rows = link.read_candidates(cpath)
        for r in rows:
            if r["match_text"] == "RC-PIC110":
                r.update(link_status="confirmed", reviewed_by="검사자", reviewed_at="2026-11-05", reason="L3")
        link.write_candidates(cpath, rows)
        added = link.run_apply(d, graphs)["add"]
        kg = build_dir(d, graphs)
        lk = {l["id"]: l for l in kg["links"]}
        res.append(("L3", "반영 후 재빌드 passed, 반영한 mentions는 V4 포함",
                    kg["validation"]["status"] == "passed" and len(added) == 1 and lk[added[0]["id"]]["compute_view"]["v4"]))
        # 후보·기각 mentions 행을 넣은 변형도 passed이고 V4에서 빠져야 함. knowledge_status는 confirmed로 두어
        # link_status 규칙 하나만으로 빠지는지 본다(제외 사유가 link_status 하나뿐이어야 함).
        extra = []
        for r in rows:
            if r["target_source_object_id"] in ("e13", "e14"):
                status = "candidate" if r["target_source_object_id"] == "e13" else "rejected"
                m = link.mention_row(dict(r, reviewed_by="검사자" if status == "rejected" else None),
                                     link_status=status, knowledge_status="confirmed")
                extra.append(m)
        link.append_links(os.path.join(d, link.LINKS_CSV), extra)
        kg2 = build_dir(d, graphs)
        lk2 = {l["id"]: l for l in kg2["links"]}
        nd2 = {n["id"]: n for n in kg2["nodes"]}
        res.append(("L3", "candidate·rejected mentions(knowledge_status confirmed)는 passed 빌드에서도 V4 제외, "
                    "제외 사유는 link_status 하나",
                    kg2["validation"]["status"] == "passed" and len(extra) == 2
                    and all(lk2[m["id"]]["compute_view"] == {"v4": False,
                                                            "excluded_reasons": ["link_status=" + m["link_status"]]}
                            for m in extra)))
        res.append(("L3", "hypothesis·unknown 노드(case-001, setpt-003)와 hypothesis 관계(krel-015)는 V4 제외",
                    not nd2["case-001"]["compute_view"]["v4"] and not nd2["setpt-003"]["compute_view"]["v4"]
                    and not lk2["krel-015"]["compute_view"]["v4"]))
    finally:
        shutil.rmtree(tmp)
    return res


def _recheck_case(sample_dir, graphs, label, edit=None, graph_version=None):
    """한 값을 바꾼 뒤: 재생성하면 RC-PV101 후보가 candidate·previous_status=confirmed로 다시 올라오고,
    기존 confirmed 행은 이력으로 남으며, 빌드에서 기존 mentions(krel-m-114485f2)는 재확인 필요·V4 제외, 반영 시 재사용 안 됨."""
    tmp, d = copy_sample(sample_dir)
    try:
        old = _by(link.read_candidates(os.path.join(d, link.CANDIDATES_CSV)), "RC-PV101")[0]
        if edit:
            edit_nodes(d, "chunk-001", **edit)
        gs = copy.deepcopy(graphs)
        if graph_version:
            for g in gs:
                if g["graph_id"] == SAMPLE_GRAPH:
                    g["graph_version"] = graph_version
        rows = link.run_generate(d, gs)["rows"]
        pv = _by(rows, "RC-PV101")
        new = [r for r in pv if r["candidate_key"] != old["candidate_key"]]
        kept = [r for r in pv if r["candidate_key"] == old["candidate_key"]]
        n0 = links_count(d)
        ap = link.run_apply(d, gs)
        kg = build_dir(d, gs)
        lk = {l["id"]: l for l in kg["links"]}
        rid = link.relation_id(old["candidate_key"])
        ok = (len(new) == 1 and new[0]["link_status"] == "candidate" and new[0]["previous_status"] == "confirmed"
              and len(kept) == 1 and kept[0]["link_status"] == "confirmed"
              and old["candidate_key"] in ap["stale"] and not ap["add"] and links_count(d) == n0
              and kg["validation"]["status"] == "passed" and lk[rid]["recheck"] is not None
              and not lk[rid]["compute_view"]["v4"]
              and any(u["check"] == "recheck_required" and u["target"] == rid for u in kg["validation"]["unknowns"]))
        return ("L4", "%s 변경 -> 기존 판단 재사용 안 함, candidate+previous_status로 재등장, 기존 mentions 재확인 필요·V4 제외"
                % label, ok)
    finally:
        shutil.rmtree(tmp)


def check_l4(sample_dir, graphs):
    return [
        _recheck_case(sample_dir, graphs, "조각 원문(text_sha256)",
                      edit={"text": "개정(가상). 3.1절(가상). 가압기 압력이 높아지면 압력제어기 RC-PIC110이 압력제어밸브 RC-PV101을 연다."}),
        _recheck_case(sample_dir, graphs, "조각 자료 material_id", edit={"material_id": "MAT-KG-002"}),
        _recheck_case(sample_dir, graphs, "조각 자료 registration_version", edit={"registration_version": "2"}),
        _recheck_case(sample_dir, graphs, "대상 graph_version", graph_version="v-000000000000"),
    ]


def link_checks(sample_dir, graphs):
    return check_l1(sample_dir, graphs) + check_l2(sample_dir, graphs) + check_l3(sample_dir, graphs) + \
        check_l4(sample_dir, graphs)


def main():
    safe_console()
    failures = []
    graphs = [g for g in build_kg.load_graphs(build_kg.DEFAULT_GRAPH_ROOT) if g["graph_id"] == SAMPLE_GRAPH]
    if not graphs:
        print("  P&ID 그래프 %s 없음 - 먼저 build_graph.py 실행" % SAMPLE_GRAPH)
        return 1
    print("== 1. 샘플 L1~L4 (%s, %s)" % (SAMPLE_PROJECT, SAMPLE_GRAPH))
    for k, label, ok in link_checks(SAMPLE_DIR, graphs):
        print("  [%s] %s %s" % ("OK" if ok else "FAIL", k, label))
        if not ok:
            failures.append("%s: %s" % (k, label))
    print("== 2. unittest tests.test_kg_link")
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_kg_link")
    outcome = unittest.TextTestRunner(verbosity=1).run(suite)
    if not outcome.wasSuccessful():
        failures.append("unittest 실패 (failures %d, errors %d)" % (len(outcome.failures), len(outcome.errors)))
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
