"""④ 분석 실행 API. 데스크톱 화면(Qt)과 scripts/analyze.py가 같은 함수를 쓴다(기획서/인터페이스.md §2.4·§2.5).

경로는 hazop/paths.py가 정한다: 구간·그래프·고정 응답·출력은 작업 루트, 카탈로그·적용 판단·패턴·기준표는 자원 루트 기준.
AI 응답 출처는 이번 구현에서 고정 응답 폴더만 쓴다(make_client). 실제 API 호출은 CLI의 --live에만 있다.
"""

from hazop import paths

from . import ai, run

AI_SOURCES = ("fixed_response",)  # 화면에서 활성화하는 응답 출처. API 호출은 확장 지점(비활성)


def make_client(source="fixed_response", response_dir=None):
    """AI 응답 출처별 클라이언트를 한 곳에서 만든다. 이번 구현은 고정 응답 폴더만 지원한다."""
    if source not in AI_SOURCES:
        raise ValueError("지원하지 않는 AI 응답 출처 %r — 이번 구현은 고정 응답 폴더만 사용" % source)
    if not response_dir:
        raise ValueError("고정 응답 폴더가 필요함")
    return ai.FixedResponseClient(response_dir, repo_root=paths.work_root())


def load_region_inputs(region_path, graph_path=None):
    """구간 JSON과 입력 파일을 작업 루트·자원 루트 기준으로 읽어 검사한다(run.load_inputs)."""
    return run.load_inputs(region_path, paths.work_root(), graph_path=graph_path, resource_root=paths.resource_root())


def run_analysis(region_path, response_dir=None, client=None, out_root=None, graph_path=None, run_id=None, only=None):
    """분석을 실행해 <out_root>/<구간 ID>/<실행 ID>/analysis.json을 만든다.

    response_dir: 고정 응답 폴더(<candidate_id>.json). client를 주면 그것을 쓴다.
    out_root: 기본 <작업 루트>/출력/분석.
    반환: {"status": "input_blocked"|"passed"|"blocked", "blockers": [...], "doc": dict|None, "run_dir": str|None}
    입력 파일 없음·JSON 오류·같은 실행 ID 결과 있음은 run.InputError 또는 ValueError로 올린다.
    """
    client = client or make_client("fixed_response", response_dir)
    inputs = load_region_inputs(region_path, graph_path)
    if inputs["blockers"]:
        return {"status": "input_blocked", "blockers": inputs["blockers"], "doc": None, "run_dir": None}
    doc, run_dir = run.execute(inputs, client, out_root or paths.output_root("analysis"), run_id=run_id, only=only)
    return {"status": doc["validation"]["status"], "blockers": [], "doc": doc, "run_dir": run_dir}
