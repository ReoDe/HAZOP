"""검사용 분석 실행 만들기. output/(git 제외 폴더)의 기존 실행에 의존하지 않는다.

샘플 drawio(참고자료/P&ID 도면 샘플)에서 SNP-M-102 그래프를 임시 폴더에 만들고(tests/test_analysis.py와 같은 방법),
scripts/analyze.py를 하위 프로세스로 실행해 고정 응답(data/fixed-responses/region-SNP-M-102-pzr)으로 분석한다.
네트워크·AI 호출 없음(--live를 쓰지 않음). 결과는 프로세스 종료 시 지우는 임시 폴더에 한 번만 만든다.
"""

import atexit
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from hazop import paths  # noqa: E402
REGION_FILE = paths.folder("samples", "regions", "region-SNP-M-102-pzr.json")
FIXED_DIR = paths.folder("samples", "fixed-responses", "region-SNP-M-102-pzr")
RUN_ID = "analysis-20261104T000000Z-fixture"

_cache = {}


def python_exe():
    """하위 프로세스로 쓸 Python 실행 파일. 내장 Python(예: LibreOffice)은 sys.executable이 폴더일 수 있음."""
    exe = sys.executable
    return exe if os.path.isfile(exe) else os.path.join(os.path.dirname(exe), "python.exe")


def _sample_graph():
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    from hazop.extract import drawio, svg_align
    from hazop.graph import build
    path = [p for p in glob.glob(paths.folder("references", "pid-samples", "*", "*.drawio"))
            if "SNP-M-102" in p][0]
    result = drawio.extract(path, page=0, repo_root=REPO_ROOT)
    svg = glob.glob(os.path.join(os.path.dirname(path), "*.drawio.svg"))
    if len(svg) == 1:
        al = svg_align.align(svg[0], result)
        al["svg_file"] = paths.rel_or_abs(svg[0], REPO_ROOT)
        result["coordinate_system"]["svg_alignment"] = al
    return build.build_graph(result)


def fresh_run_dir():
    """고정 응답으로 새로 만든 분석 실행 폴더(<임시>/analysis/region-SNP-M-102-pzr/<RUN_ID>). 실패하면 RuntimeError.
    호출자는 이 폴더를 읽기만 하고, 고칠 때는 복사해서 쓴다."""
    if "run_dir" in _cache:
        return _cache["run_dir"]
    tmp = tempfile.mkdtemp(prefix="hazop-fixture-run-")
    atexit.register(shutil.rmtree, tmp, True)
    graph_path = os.path.join(tmp, "graph.json")
    with open(graph_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(_sample_graph(), fh, ensure_ascii=False, indent=2)
    out_root = os.path.join(tmp, "analysis")
    cmd = [python_exe(), os.path.join(REPO_ROOT, "scripts", "analyze.py"), "--region", REGION_FILE,
           "--graph", graph_path, "--fixed-dir", FIXED_DIR, "--out-root", out_root, "--run-id", RUN_ID]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    run_dir = os.path.join(out_root, "region-SNP-M-102-pzr", RUN_ID)
    if proc.returncode != 0 or not os.path.isfile(os.path.join(run_dir, "analysis.json")):
        raise RuntimeError("scripts/analyze.py 실행 실패(종료 코드 %d): %s"
                           % (proc.returncode, proc.stdout.decode("utf-8", "replace")))
    _cache["run_dir"] = run_dir
    return run_dir
