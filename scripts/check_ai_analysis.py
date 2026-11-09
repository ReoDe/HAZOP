"""④→⑤ AI 칸 채우기 검사 (QA용). 근거: 4단계 설계 D2·D4·D5·D6·D7·D8.

저장소의 출력/그래프·출력/지식그래프를 임시 작업 루트로 복사해 실제 샘플 도면(SNP-M-102)과 지식그래프로 확인한다
(저장소의 출력/·데이터/에 쓰지 않음). 네트워크 대신 가짜 opener를 끼운 ClaudeHttpClient를 쓴다. Qt 없음.
가짜 응답은 스키마에 맞고, 도면에 없는 태그 1개와 이어지지 않는 경로 1개를 일부러 넣는다.
확인: 요청 결정성, 모델별 요청 모양(Haiku는 대체 모델 없음), 다중 키 보관·옛 키 파일 이전, 근거 경고, 위험도(MATRIX_P86), 저장·읽기 왕복, 키가 파일·요청 본문에 없음(헤더에만),
취소(남은 unit 미호출)·실패 칸 재실행(그 칸만 다시, 나머지 유지).
종료 코드 0 = 전부 통과.
"""

import json
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.analysis.risk import MATRIX_P86  # noqa: E402
from hazop.study import ai_cells as ac  # noqa: E402
from hazop.study import apikey  # noqa: E402
from hazop.study import nodes as sn  # noqa: E402
from hazop.study import results as sr  # noqa: E402
from hazop.study.claude_http import ClaudeHttpClient  # noqa: E402
from hazop.viewer import build as viewer_build  # noqa: E402

DRAWING = "SNP-M-102"
KEY = "sk-ant-api03-CHECKKEY-never-in-files-9876543210"
KEY2 = "sk-ant-api03-SECONDKEY-never-in-files-0123456789"
BAD_TAG = "NO-SUCH-TAG-999"
AT = "2026-11-07T00:00:00Z"


def asked(user_text):
    return [d["deviation_id"] for d in json.loads(user_text.split("\n", 1)[1])]


def evidence(ctx):
    """(이어진 경로, 이어지지 않는 경로, 출처 문서, 도면 태그)."""
    adj = ctx["adjacency"]
    members = [c["entity_id"] for c in ctx["prompt"]["components"]]
    a = next(m for m in members if adj.get(m))
    good = [a, sorted(adj[a])[0]]
    far = next(x for x in sorted(ctx["allowed"]["entity_ids"]) if x != a and x not in adj.get(a, ()))
    tag = next(c["tag"] for c in ctx["prompt"]["components"] + ctx["prompt"]["neighbors"] if c.get("tag"))
    return good, [a, far], sorted(ctx["allowed"]["doc_ids"])[0] if ctx["allowed"]["doc_ids"] else None, tag


class FakeApi:
    """ClaudeHttpClient의 opener. 받은 헤더·본문을 기록하고 스키마에 맞는 응답을 돌려준다.
    fail_ids의 편차를 묻는 호출은 HTTP 500. on_call(n)은 n번째 호출 때 부른다."""

    def __init__(self, ctxs, fail_ids=(), on_call=None):
        self.ctxs, self.fail_ids, self.on_call = ctxs, set(fail_ids), on_call
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((dict(headers), body))
        if self.on_call:
            self.on_call(len(self.calls))
        req = json.loads(body.decode("utf-8"))
        ids = asked(req["messages"][0]["content"][1]["text"])
        if self.fail_ids & set(ids):
            return 500, b'{"type":"error","error":{"type":"api_error","message":"fake"}}'
        node_id = json.loads(req["messages"][0]["content"][0]["text"].split("\n", 1)[1])["node"]["node_id"]
        good, broken, doc, tag = evidence(self.ctxs[node_id])
        out = {"deviations": [{"deviation_id": d, "applicable": True, "note": "", "scenarios": [{
            "cause": "원인 %s" % d, "consequence": "결과", "safeguards": ["보호"], "recommendation": "권고",
            "severity": 4, "frequency": 1, "equipment_tags": [tag, BAD_TAG], "kg_paths": [good, broken],
            "sources": [{"doc": doc, "where": "p.1"}] if doc else []}]} for d in ids]}
        resp = {"model": "claude-opus-5-5", "stop_reason": "end_turn",
                "usage": {"input_tokens": 1000, "output_tokens": 200},
                "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}
        return 200, json.dumps(resp, ensure_ascii=False).encode("utf-8")


def run(results, client, jobs, devs, cancel_after=None):
    """작업 스레드와 같은 순서(취소 확인 → run_unit)를 Qt 없이 돈다. 반환 (results, 부른 unit 수)."""
    n = 0
    for unit, ctx in jobs:
        if cancel_after is not None and n >= cancel_after:
            break
        results = ac.apply_unit(results, ac.run_unit(client, unit, ctx, devs, "%s-%d" % (AT, n)))
        n += 1
    return results, n


def check(tmp):
    f = []
    graph = viewer_build.load_graph(paths.output_root("그래프"), DRAWING)
    ns = sn.confirm(sn.propose(graph, at=AT), graph, "검사", at=AT)
    sn.save(ns)
    devs = sr.load_deviations()
    kg, why = ac.load_kg_for(ns)
    if kg is None:
        return ["지식그래프를 읽지 못함: %s" % why]
    ctxs = {n["node_id"]: ac.node_context(n, graph, kg) for n in ns["nodes"]}
    if any(c["kg_note"] == ac.NO_KG_NOTE or (c["kg_note"] or "").startswith("지식그래프를 쓰지 않음")
           for c in ctxs.values()):
        f.append("실제 지식그래프가 맥락에 들어가지 않음")
    units = ac.plan_units(ns, devs)
    jobs = [(u, ctxs[u["node_id"]]) for u in units]

    first = jobs[0]
    again = ac.build_request(first[0], ac.node_context(ns["nodes"][0], graph, kg), devs)
    if ac.build_request(*first, devs) != again:
        f.append("같은 입력에 다른 요청")
    same_node = [ac.build_request(u, c, devs)["context"] for u, c in jobs if u["node_id"] == first[0]["node_id"]]
    if len(set(same_node)) != 1:
        f.append("같은 구간의 context 바이트가 호출마다 다름(캐시 불가)")

    api = FakeApi(ctxs)
    client = ClaudeHttpClient(lambda: KEY, opener=api)
    results, n = run(sr.empty_results(ns, devs), client, jobs, devs)
    if n != len(units) or len(api.calls) != len(units):
        f.append("호출 수 %d ≠ unit 수 %d" % (len(api.calls), len(units)))
    for headers, body in api.calls:
        if headers.get("x-api-key") != KEY:
            f.append("요청 헤더에 키가 없음")
            break
        if KEY.encode("utf-8") in body:
            f.append("요청 본문에 키가 있음")
            break
    entries = [e for c in results["cells"] for e in c["entries"]]
    if len(entries) != len(results["cells"]) or ac.failed_cells(results):
        f.append("모든 칸이 항목 1개로 채워지지 않음(실패 %d)" % len(ac.failed_cells(results)))
    for e in entries[:1] + entries[-1:]:
        w = e["ai_basis"]["warnings"]
        if "도면에 없는 태그: %s" % BAD_TAG not in w:
            f.append("도면에 없는 태그 경고 없음: %s" % w)
        if not any(x.startswith("이어지지 않는 경로 단계") for x in w):
            f.append("이어지지 않는 경로 경고 없음: %s" % w)
        if len(w) != 2:
            f.append("올바른 태그·경로·출처까지 경고됨: %s" % w)
        if e["risk"] != MATRIX_P86[4][1] or e["origin"] != "ai_draft" or e["status"] != "proposed":
            f.append("위험도·출처·상태 %r %r %r" % (e["risk"], e["origin"], e["status"]))
    problems = sr.validate(results, ns)
    if problems:
        f.append("validate 실패: %s" % problems[:3])

    path = sr.save(results, ns.get("project_id"))
    if sr.load(ns) != results or sr.is_stale(sr.load(ns), ns):
        f.append("저장·읽기 왕복 불일치")
    if not path.startswith(tmp):
        f.append("임시 루트 밖에 저장: %s" % path)

    cancelled = FakeApi(ctxs)
    part, n = run(sr.empty_results(ns, devs), ClaudeHttpClient(lambda: KEY, opener=cancelled), jobs, devs, 1)
    done = {(first[0]["node_id"], d) for d in first[0]["deviation_ids"]}
    if len(cancelled.calls) != 1 or any((c["state"] == "analyzed") != ((c["node_id"], c["deviation_id"]) in done)
                                        for c in part["cells"]):
        f.append("취소 뒤 남은 unit을 부르거나 끝난 unit이 빠짐")

    bad = set(units[1]["deviation_ids"])
    failing = FakeApi(ctxs, fail_ids=bad)
    res1, _ = run(sr.empty_results(ns, devs), ClaudeHttpClient(lambda: KEY, opener=failing), jobs, devs)
    failed = ac.failed_cells(res1)
    if sorted(failed) != sorted((n["node_id"], d) for n in ns["nodes"] for d in bad):
        f.append("실패 칸이 기대와 다름: %d" % len(failed))
    keep = {(c["node_id"], c["deviation_id"]): c["entries"] for c in res1["cells"] if c["state"] == "analyzed"}
    retry_api = FakeApi(ctxs)
    retry_jobs = [(u, ctxs[u["node_id"]]) for u in ac.plan_units(ns, devs, failed)]
    res2, _ = run(res1, ClaudeHttpClient(lambda: KEY, opener=retry_api), retry_jobs, devs)
    if len(retry_api.calls) != len(failed) or ac.failed_cells(res2):
        f.append("재실행이 실패 칸만 칸마다 부르지 않음(%d회, 남은 실패 %d)" % (len(retry_api.calls),
                                                              len(ac.failed_cells(res2))))
    if any(c["entries"] != keep[k] for c in res2["cells"] for k in [(c["node_id"], c["deviation_id"])] if k in keep):
        f.append("재실행이 성공했던 칸을 바꿈")
    sr.save(res2, ns.get("project_id"))

    f += check_key_store(tmp, ctxs, jobs[0], devs)
    hits = []
    for base, _dirs, files in os.walk(tmp):
        for name in files:
            with open(os.path.join(base, name), "rb") as fh:
                raw = fh.read()
                if any(k.encode(enc) in raw for k in (KEY, KEY2) for enc in ("utf-8", "utf-16-le")):
                    hits.append(os.path.relpath(os.path.join(base, name), tmp))
    if hits:
        f.append("키가 파일에 남음: %s" % hits)
    print("%-10s nodes %d · units %d · cells %d · retry %d · warnings/entry %d"
          % (DRAWING, len(ns["nodes"]), len(units), len(results["cells"]), len(failed),
             len(entries[0]["ai_basis"]["warnings"]) if entries else -1))
    return f


def check_key_store(tmp, ctxs, job, devs):
    """다중 키 보관(옛 파일 이전·저장·시험 결과)과 모델별 요청 모양. 키는 임시 폴더의 가짜 값만 쓴다."""
    f = []
    haiku = FakeApi(ctxs)
    ClaudeHttpClient(lambda: KEY, model="claude-haiku-5-5", opener=haiku).analyze(ac.build_request(*job, devs))
    headers, body = haiku.calls[0]
    if b'"fallbacks"' in body or "anthropic-beta" in headers:
        f.append("Haiku 요청에 대체 모델(fallbacks)이 붙음")
    if sys.platform != "win32":
        return f
    legacy = os.path.join(tmp, apikey.LEGACY_FILE_NAME)
    with open(legacy, "wb") as fh:
        fh.write(apikey.protect(KEY.encode("utf-8")))
    path = os.path.join(tmp, apikey.STORE_FILE_NAME)
    store = apikey.KeyStore(path)
    if store.get() != KEY or os.path.exists(legacy):
        f.append("옛 단일 키 파일을 새 목록으로 옮기지 못함")
    kid = store.add("둘째 키", KEY2, persist=True)
    store.record_test(kid, False, "거부됨 %s" % KEY2, "2026-11-07T00:00:00Z", store.model)
    again = apikey.KeyStore(path)
    if again.get() != KEY2 or [e["name"] for e in again.entries()] != [apikey.LEGACY_NAME, "둘째 키"]:
        f.append("저장한 키 목록을 다시 읽지 못함")
    if KEY2 in repr(again) or KEY2 in str(again.entries()):
        f.append("키 목록 표시에 키가 보임")
    return f


def main():
    safe_console()
    tmp = tempfile.mkdtemp(prefix="hazop-ai-check-")
    old = os.environ.get(paths.ENV_WORK_ROOT)
    os.environ[paths.ENV_WORK_ROOT] = tmp
    failures = []
    try:
        for d in ("그래프", "지식그래프"):
            shutil.copytree(os.path.join(paths.DEV_WORK_ROOT, "출력", d), os.path.join(tmp, "출력", d))
        failures = check(tmp)
    finally:
        if old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = old
        shutil.rmtree(tmp, ignore_errors=True)
    print("== 결과:", "통과" if not failures else "실패 %d건" % len(failures))
    for x in failures:
        print("  -", x)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
