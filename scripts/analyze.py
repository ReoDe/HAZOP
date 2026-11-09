"""단계 ④ HAZOP 분석 실행 -> 출력/분석/<구간 ID>/<실행 ID>/analysis.json (+ inputs/ 입력 사본)

사용 예:
  python scripts/analyze.py                                   # 기본 구간(SNP-M-102 가압기), 고정 응답
  python scripts/analyze.py --region 데이터/구간/region-SNP-M-102-pzr.json --fixed-dir 데이터/고정응답/region-SNP-M-102-pzr
  python scripts/analyze.py --live --only p86-d09             # 실제 Claude API 호출(명시 옵션, 자격 증명 필요)
  python scripts/analyze.py --resume 출력/분석/region-SNP-M-102-pzr/<실행 ID> [--live]   # AI 단계부터 재시도
  python scripts/analyze.py --rebind-graph [--graph 출력/그래프/SNP-M-102/graph.json]      # 그래프 버전 차이 보기
  python scripts/analyze.py --rebind-graph --confirm --by 이름 --reason "사유"              # 확인 후 구간 JSON 갱신(이력 기록)

그래프가 없으면 먼저 구간 JSON graph_ref.how_to_build의 명령을 실행한다.
  samples 경로: python scripts/extract_drawio.py --samples && python scripts/build_graph.py
  등록 경로: python scripts/run_samples.py  (graph_version·project_id가 달라지므로 --rebind-graph로 다시 고정)
    run_samples 그래프로 다시 고정하려면 --rebind-graph --graph 출력/samples/그래프/<이름>/graph.json 을 지정한다.
--live 없이 실행하면 실제 API를 호출하지 않는다(고정 응답만). --resume는 원래 실행의 AI 모드를 그대로 쓰며,
실제 API 실행을 재시도할 때도 --live를 명시해야 한다.
경로: 구간·그래프·고정 응답·출력은 작업 루트(HAZOP_WORK_ROOT), 카탈로그·적용 판단·패턴·기준표는 자원 루트
(HAZOP_RESOURCE_ROOT) 기준. 둘 다 기본은 저장소 루트(hazop/paths.py). 화면은 hazop.analysis.api의 같은 함수를 쓴다.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop.console import safe_console  # noqa: E402

from hazop import paths  # noqa: E402
from hazop.analysis import ai, api, run  # noqa: E402

DEFAULT_REGION = paths.folder("구간", "region-SNP-M-102-pzr.json")
DEFAULT_FIXED = paths.folder("고정응답", "region-SNP-M-102-pzr")
DEFAULT_OUT = paths.output_root("분석")


def make_client(args):
    if args.live:
        if not ai.AnthropicClient.credentials_available():
            print("실제 호출 불가: ANTHROPIC_API_KEY(또는 SDK가 찾는 자격 증명)가 없음. 고정 응답으로 바꾸지 않고 중단함")
            return None
        return ai.AnthropicClient(model=args.model)
    return api.make_client("fixed_response", args.fixed_dir)


def resume_client(args):
    """원래 실행의 AI 모드를 기록에서 읽어 같은 클라이언트를 만든다. 옵션과 다르면 거부."""
    rec = run.recorded_ai_mode(args.resume)
    if rec.get("type") == "anthropic_api":
        if not args.live:
            raise run.InputError("원래 실행은 실제 API(--live) — 재시도에도 --live를 명시해야 함")
        if not ai.AnthropicClient.credentials_available():
            raise run.InputError("실제 호출 불가: 자격 증명 없음")
        return ai.AnthropicClient(model=rec.get("model") or args.model)
    if args.live:
        raise run.InputError("원래 실행은 고정 응답 — --live로 재시도할 수 없음")
    return ai.FixedResponseClient(os.path.join(paths.work_root(), rec["response_dir"]), repo_root=paths.work_root(),
                                  verify_bundle=rec.get("verify_bundle", True))


def summary(doc, where):
    v = doc["validation"]
    c = v["counts"]
    print("%s: 결과 검증 %s 후보 %d(선택 %d·제외 %d·보류 %d) 시나리오 %d 위험도 제안 %d 설계보완 후보 %d "
          "AI 검증 통과 %d·미완료 %d·거부 시나리오 %d 보류 %d -> %s" % (
              doc["analysis_run_id"], v["status"], c["candidates"], c["selected"], c["excluded"], c["deferred"],
              c["scenarios"], c["risk_proposed"], c["design_improvement_candidates"], c["ai_validated"], c["ai_failed"],
              c["ai_rejected_scenarios"], c["holds_open"], paths.rel_or_abs(where, paths.work_root())))
    for e in v["errors"]:
        print("  오류:", e)


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default=DEFAULT_REGION, help="구간 지정 JSON")
    ap.add_argument("--graph", help="그래프 JSON (기본: 구간 JSON의 graph_ref.graph_file)")
    ap.add_argument("--fixed-dir", default=DEFAULT_FIXED, help="고정 응답 폴더(<candidate_id>.json)")
    ap.add_argument("--live", action="store_true", help="실제 Claude API 호출(자격 증명 필요)")
    ap.add_argument("--model", default=ai.DEFAULT_MODEL, choices=ai.ALLOWED_MODELS,
                    help="--live 모델 (허용 목록만, 기본 %(default)s)")
    ap.add_argument("--only", action="append", default=[], help="AI 대상 후보 ID 또는 item_id(여러 번 지정)")
    ap.add_argument("--run-id", help="실행 ID (기본: 시각+입력 해시)")
    ap.add_argument("--out-root", default=DEFAULT_OUT)
    ap.add_argument("--resume", help="저장된 실행 폴더: AI 단계부터 재시도")
    ap.add_argument("--rebind-graph", action="store_true", help="구간 JSON의 그래프 버전 차이 확인·갱신")
    ap.add_argument("--confirm", action="store_true", help="--rebind-graph 갱신 실행")
    ap.add_argument("--by", help="--rebind-graph 변경 주체")
    ap.add_argument("--reason", help="--rebind-graph 변경 사유")
    args = ap.parse_args(argv)
    only = set(args.only) or None
    if args.rebind_graph:
        lines, changed = run.rebind_graph(args.region, args.graph, paths.work_root(), args.by, args.reason, args.confirm)
        for line in lines:
            print(line)
        return 0 if changed or not args.confirm else 1
    if args.resume:
        try:
            client = resume_client(args)
            doc = run.resume(args.resume, client, only=only)
        except (run.InputError, OSError, ValueError) as exc:
            print("재시도 오류:", exc)
            return 1
        summary(doc, args.resume)
        return 0 if doc["validation"]["status"] == "passed" else 1
    client = make_client(args)
    if client is None:
        return 2
    try:
        res = api.run_analysis(args.region, client=client, out_root=args.out_root, graph_path=args.graph,
                               run_id=args.run_id, only=only)
    except (run.InputError, ValueError) as exc:
        print("입력 오류:", exc)
        return 1
    if res["blockers"]:
        print("입력 차단 오류 — 분석하지 않음:")
        for b in res["blockers"]:
            print("  -", b)
        return 1
    summary(res["doc"], res["run_dir"])
    return 0 if res["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
