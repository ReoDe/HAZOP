"""패키징 W4 묶음 검증: 빌드한 one-folder를 저장소 밖 새 폴더에 복사해 묶인 실행으로 ①~⑤·③ V1·V2·S1·로그를 확인한다.

사용(전용 venv, 스냅숏 또는 저장소 루트에서):
  python packaging/verify_bundle.py --dist <out>/dist/HAZOP-verify --target-base %TEMP%\\hz_ascii --out <결과 상위 폴더>
  python packaging/verify_bundle.py --dist <out>/dist/HAZOP --target-base ... --out ... --app-only   # 배포용
순서:
 0) 사전 검사: dist에 HAZOP.exe가 있어야 하고, --app-only가 아니면 HAZOP-check.exe도 있어야 한다(없으면 중단).
    --target-base·--out은 저장소·dist와 서로 포함되면 안 된다. 기존 폴더는 어떤 경우에도 지우지 않는다.
 1) 실행마다 새 폴더 <target-base>/verify-<시각>-<uuid8>(또는 --run-name)를 만든다. 같은 이름이 있으면 실패로 끝낸다.
    그 아래 HAZOP/(dist 사본)과 w4-run/(검사 입력 사본·작업 루트·임시)을 둔다. 결과는 --out 아래 새 폴더(run-<시각>-xxxx).
 2) HAZOP-check.exe w4_flow.py: 루트·datas 해시·자원 경로(분석 전) → ①~⑤ 함수 흐름·기준 자료 읽기 위치·음성 검사
 3) HAZOP-check.exe check_kg_screen.py --skip-tests --screenshots: ③ V2·렌더링·V1·S1·③ 탭과 ③ PNG
    (이 단계만 HAZOP_WORK_ROOT = 입력 사본의 참고 폴더 부모(kg_work_root): 샘플 graph_version이 개발 실행과 같게.
    QT_QPA_PLATFORM = windows: offscreen은 위젯 한글이 빈 상자로 찍힘)
 3b) PDF 어댑터(W9, D15): HAZOP-check.exe pdf_probe.py로 샘플 PDF 사본(SNP-M-102, 가상 샘플)을 묶음 안 pdf_vector로
    추출하고 pypdfium2로 그린다. 추출 요약이 이 검증기(전용 venv)에서 같은 파일을 추출한 결과와 같고, pdfplumber·pdfminer·
    pypdfium2·pypdfium2_raw·PIL·cryptography·charset_normalizer 모듈(7개 키가 모두 결과에 있어야 함)과 실제로 읽힌 pdfium.dll
    (읽은 모듈 핸들의 경로)이 묶음 안인지 본다.
    --app-only(배포용)는 실행 단계 없이 _internal/pypdfium2_raw/pdfium.dll이 있는지만 본다(앱 PYZ의 모듈은 빌드 뒤 검사).
 4) HAZOP.exe --screenshots [--run <④ 실행 폴더>]: ①②(편집 모드 02-viewer-edit 포함)·이전 ④⑤ PNG와 레일 단계
    ①~⑥ × 1366·1920 stages/ PNG(새 ④ 검토구간, 새 ⑤ 분석 결과, ⑥ 초기사건 포함). --app-only는 검증 exe가 없어 1)~3)이
    작업 루트를 채우지 않으므로, 이 검증기가 개발 코드로 표본 구간·고정 응답·지식과 샘플 도면(SNP-M-102) 추출·그래프를
    작업 루트에 먼저 넣는다(seed_app_work). 화면이 빈 안내만 찍히지 않게 하려는 것이고, 묶음의 추출 코드는 보지 않는다.
    <작업 루트>/logs/app.log에 시작 기록이 있는지. 잘못된 옵션(--w4-unknown-option)은 종료 코드 2와 사용법 오류(표준 출력
    사본)만 본다: 하위 프로세스로 띄우면 표준 출력 핸들이 있어 로그 파일 연결(핸들이 없을 때만)이 일어나지 않는다.
    손상 설정(W10, D18): JSON 문법 오류 설정 파일 + --screenshots → 종료 코드 2, 출력에 안내, app.log에 기록, 설정 파일은
    그대로(백업·PNG 없음). 시험 트리거: HAZOP_TEST_EXCEPTHOOK=1 + --screenshots + 손상 설정(두 빌드 같은 실행). 검증용은
    표지 훅(packaging/rthook_verify_build.py)이 있어 앱이 시험용 예외를 sys.excepthook에 넘기고 종료 코드 70, app.log에
    "미처리 예외"와 시험용 메시지(app_log_unhandled). 배포용은 트리거가 꺼져 종료 코드 2, 시험용 메시지 없음
    (app_trigger_off). 단계 4의 실행은 모두 비대화형이라 모달·오류 창이 뜨지 않는다(스크린샷 단계는 비모달 창이 잠깐 뜸)
 5) 저장소 output/·store/ 파일 해시가 전후 같은지, 3)이 입력 사본을 바꾸지 않았는지, PNG가 이번 실행에서 생겼는지
 6) 제3자 고지(W9, D15): 실행 파일 옆 licenses/의 파일 목록·바이트 해시가 저장소 licenses/와 같은지(빠짐·추가·변경
    없음), 이전 위치 _internal/licenses/가 없는지(scripts/build_package.licenses_problems와 같은 규칙)
 7) 기호 사전: 묶음 안 사전이 읽히고 구조·이름 낱말 견본이 들어 있는지(symbols_problems). 견본이 없는 옛 판 사전이 묶이면
    추출이 오류로 멈추므로 여기서 먼저 잡는다
 8) Qt 기본 번역: _internal/PySide6/translations/qtbase_ko.qm이 묶였고, 4)의 스크린샷 실행 로그에 '번역을 읽지 못함'이
    없는지(translation_problems). 없으면 입력 창 단추가 영어(OK/Cancel)로 보인다
자식 프로세스 환경: PYTHONPATH·PYTHONHOME·HAZOP_* 제거, HAZOP_WORK_ROOT·APPDATA·TEMP = 임시, 작업 폴더 = 임시(저장소 아님).
PATH = Windows System32·Windows 폴더만, QT_*·OPENSSL_*·SSL_CERT_* 제거(D10): 사용자 PATH 경유 탐색을 제한한다
(JDK·Git 등 PATH에 있는 UCRT·OpenSSL DLL을 찾지 못함). 다른 PC와 같은 조건이라는 보장은 아니다.
새 폴더를 만든 뒤의 모든 단계는 try 안에서 하고, 끝나면(실패해도, finally) 이번 실행에서 만든 verify-… 폴더만 지운다.
지우지 못하면 errors.cleanup에 남기고 실패 처리한다. 단계별 예외는 summary.json errors에 남긴다. 종료 코드 0 = 전부 통과.
네트워크·AI 호출 없음.
"""

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_SCRIPTS = ("check_kg_screen", "check_kg", "check_kg_algo", "check_kg_renderer", "build_kg", "analyze_kg",
                 "analyze", "extract_drawio", "build_graph")
# 레일 단계(hazop/app/main_window.STAGES의 번호·짧은 이름)와 크기(hazop/app/screenshots.STAGE_SIZES). 시험이 같은지 본다
STAGE_NAMES = (("1", "등록"), ("2", "추출"), ("3", "그래프"), ("4", "구간"), ("5", "결과"), ("6", "초기사건"))
STAGE_SIZES = ((1366, 768), (1920, 1080))
STAGE_PNG = tuple("stages/stage%s-%s-%dx%d.png" % (n, short, w, h) for w, h in STAGE_SIZES for n, short in STAGE_NAMES)
APP_PNG = ("01-register.png", "02-viewer.png", "02-viewer-edit.png", "04-analysis.png", "05-review.png") + STAGE_PNG
FULL_PNG = APP_PNG + ("03-knowledge.png", "03-knowledge-1366.png", "05-review-confirmed.png")
TIMEOUT = 900


def _build_package():
    spec = importlib.util.spec_from_file_location("hazop_build_package_v",
                                                  os.path.join(REPO_ROOT, "scripts", "build_package.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bp = _build_package()
from hazop import paths  # noqa: E402  (bp가 저장소를 sys.path에 넣었음)

SAMPLE_DIR = ("pid-samples", "SNP-M-102_RCS-pressurizer")  # 참고 폴더 안
inside = bp.inside  # 드라이브가 다르면 False(ValueError 처리)


def overlaps(a, b):
    return inside(a, b) or inside(b, a)


def tree_hashes(root):
    """{상대 경로: sha256} — 폴더가 없으면 빈 dict(이름이 같아도 내용이 바뀌면 다름)."""
    out = {}
    if not os.path.isdir(root):
        return out
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def tree_size(root):
    total = count = 0
    for d, _, fs in os.walk(root):
        for f in fs:
            total += os.path.getsize(os.path.join(d, f))
            count += 1
    return total, count


def base_problems(base, dist, repo=REPO_ROOT):
    """검증 사본을 만들 상위 폴더 검사. 문제 목록(빈 목록 = 써도 됨)."""
    probs = []
    if overlaps(base, repo):
        probs.append("대상 상위 폴더가 저장소와 겹침: %s" % base)
    if overlaps(base, dist):
        probs.append("대상 상위 폴더가 dist와 겹침: %s" % base)
    return probs


def new_run_root(base, name=None):
    """이번 실행 전용 새 폴더 <base>/<name>(기본 verify-<시각>-<uuid8>). 이미 있으면 FileExistsError(건드리지 않음)."""
    name = name or time.strftime("verify-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    if os.path.basename(name) != name or name in ("", ".", ".."):
        raise ValueError("폴더 이름이 아님: %r" % name)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, name)
    os.mkdir(path)  # 있으면 FileExistsError
    return path


def licenses_problems(bundle_dir, repo=REPO_ROOT):
    """묶음(one-folder)의 실행 파일 옆 licenses/가 저장소 licenses/와 같은지(W9, D15, build_package와 같은 규칙). 문제 목록."""
    return bp.licenses_problems(bundle_dir, repo)


def symbols_problems(bundle_dir):
    """묶음 안 기호 사전(_internal 아래, 저장소와 같은 상대 위치)을 이 검증기의 코드로 읽는다. 읽히지 않거나 구조·이름
    낱말 견본이 없으면(코드보다 옛 판 사전이 묶임) 문제다. 그런 사전은 밸브·계기·설비 분류가 오류 없이 빠진다. 문제 목록."""
    from hazop.extract import symbols
    try:
        missing = symbols.Library.load(paths.folder_in(os.path.join(bundle_dir, "_internal"), "symbols")).missing_rule_shapes()
    except symbols.SymbolLibraryError as e:
        return ["기호 사전을 읽지 못함: %s" % e]
    return ["기호 사전에 %s 견본이 없음(코드보다 옛 판 사전)" % shape for shape in missing]


def icons_problems(bundle_dir, repo=REPO_ROOT):
    """묶음 안 화면 아이콘 폴더(_internal 아래, 저장소와 같은 상대 위치)가 저장소의 manifest.json 목록과 바이트까지 같은지.
    빠짐·다름·목록 밖 파일이 있으면 문제다(아이콘이 없으면 버튼이 빈 그림으로 뜬다). 문제 목록."""
    import hashlib
    src = os.path.join(repo, *paths.FOLDERS["icons"].rel, "tabler")
    dest = paths.folder_in(os.path.join(bundle_dir, "_internal"), "icons", "tabler")
    if not os.path.isdir(dest):
        return ["묶음에 아이콘 폴더가 없음"]
    with open(os.path.join(src, "manifest.json"), encoding="utf-8") as fh:
        listed = json.load(fh)["icons"]
    probs = []
    for name, row in sorted(listed.items()):
        p = os.path.join(dest, name + ".svg")
        if not os.path.isfile(p):
            probs.append("아이콘 빠짐: %s.svg" % name)
            continue
        with open(p, "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != row["sha256"]:
                probs.append("아이콘 바이트 다름: %s.svg" % name)
    probs += ["목록 밖 아이콘: %s" % f for f in sorted(os.listdir(dest)) if f.endswith(".svg") and f[:-4] not in listed]
    return probs


QT_TRANSLATION_FILE = ("PySide6", "translations", "qtbase_ko.qm")  # _internal 아래


def translation_problems(bundle_dir, app_log):
    """Qt 기본 번역 파일이 묶였고 앱이 그것을 읽었는지(읽지 못하면 hazop.app가 TRANSLATION_FAILED를 남긴다). 문제 목록."""
    from hazop.app import TRANSLATION_FAILED
    probs = []
    qm = os.path.join(bundle_dir, "_internal", *QT_TRANSLATION_FILE)
    if not os.path.isfile(qm):
        probs.append("Qt 기본 번역 파일 없음: %s" % qm)
    if TRANSLATION_FAILED in app_log:
        probs.append("앱 로그: %s" % TRANSLATION_FAILED)
    return probs


def _pdf_probe_module():
    spec = importlib.util.spec_from_file_location("hazop_pdf_probe_v",
                                                  os.path.join(REPO_ROOT, "packaging", "pdf_probe.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pdf_expected(pdf, repo=REPO_ROOT):
    """이 검증기(전용 venv)에서 저장소 hazop의 pdf_vector로 같은 PDF를 추출한 요약(pdf_probe.digest 형식)."""
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from hazop.extract.adapters import pdf_vector
    return _pdf_probe_module().digest(pdf_vector.extract(pdf))


PDF_PROBE_MODULES = ("pdfplumber", "pdfminer", "pypdfium2", "pypdfium2_raw", "PIL", "cryptography",
                     "charset_normalizer")  # pdf_probe.PROBE_MODULES와 같아야 한다(테스트로 고정)


def pdf_probe_problems(result, expected, bundle_dir):
    """pdf_probe 결과 판정. 문제 목록(빈 목록 = 통과): 오류 없음, 묶인 실행, 추출 요약이 개발 실행과 같음, 그림 크기,
    필수 모듈 7개(PDF_PROBE_MODULES)와 pdfium.dll 키가 결과에 있고, 실제로 읽힌 경로가 묶음 안."""
    if not isinstance(result, dict):
        return ["결과 없음"]
    if result.get("error"):
        return ["오류: %s" % result["error"]]
    probs = [] if result.get("frozen") else ["묶인 실행이 아님"]
    if result.get("extraction") != expected:
        probs.append("추출 요약이 개발 실행과 다름")
    size = result.get("render_size") or []
    if not (len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size)):
        probs.append("pypdfium2 그림 크기 이상: %r" % (size,))
    got = result.get("module_files") if isinstance(result.get("module_files"), dict) else {}
    probs += ["결과에 없음: %s" % m for m in PDF_PROBE_MODULES if m not in got]
    if "pdfium_dll" not in result:
        probs.append("결과에 없음: pdfium.dll")
    files = {m: got.get(m) for m in PDF_PROBE_MODULES if m in got}
    if "pdfium_dll" in result:
        files["pdfium.dll"] = result.get("pdfium_dll") if result.get("pdfium_dll_exists") else None
    for name, path in sorted(files.items()):
        if not path:
            probs.append("읽히지 않음: %s" % name)
        elif not inside(path, bundle_dir):
            probs.append("묶음 밖에서 읽힘: %s (%s)" % (name, path))
    return probs


def fresh_problems(png_dir, since, want):
    """want 이름의 PNG가 png_dir에 있고 since 이후에 만들어졌는지. 문제 목록."""
    probs = []
    for name in want:
        p = os.path.join(png_dir, name)
        if not os.path.isfile(p):
            probs.append("없음: %s" % name)
        elif os.path.getmtime(p) < since:
            probs.append("이번 실행 전 파일: %s" % name)
    return probs


def make_inputs(dest):
    """검사 입력 사본(작은 저장소: 표본은 저장소와 같은 자리, 샘플 도면은 기록 경로 자리). hazop/ 은 넣지 않는다(묶음의 hazop만
    읽히게). 묶인 실행에서는 저장소의 참고 폴더가 없으므로, 샘플 도면이 기록 경로 자리(paths.logical_dir)에 있어야 사본을 작업
    루트로 삼았을 때 source.file이 저장소와 같게 적히고 그래프 판이 맞는다."""
    os.makedirs(os.path.join(dest, "scripts"))
    for n in CHECK_SCRIPTS:
        shutil.copy2(os.path.join(REPO_ROOT, "scripts", n + ".py"), os.path.join(dest, "scripts"))
    shutil.copy2(os.path.join(REPO_ROOT, "packaging", "w4_flow.py"), os.path.join(dest, "scripts"))
    shutil.copy2(os.path.join(REPO_ROOT, "packaging", "pdf_probe.py"), os.path.join(dest, "scripts"))
    sdir = paths.logical_dir(dest, "references", *SAMPLE_DIR)
    os.makedirs(sdir)
    src = paths.folder("references", *SAMPLE_DIR)
    for p in glob.glob(os.path.join(src, "*.drawio")) + glob.glob(os.path.join(src, "*.drawio.svg")) + \
            glob.glob(os.path.join(src, "*.pdf")):
        shutil.copy2(p, sdir)
    for sub in (("regions",), ("fixed-responses",), ("knowledge-graph", "SNP-SAMPLE")):
        shutil.copytree(paths.folder("samples", *sub), paths.folder_in(dest, "samples", *sub))


def seed_app_work(work):
    """--app-only 작업 루트 채우기(w4_flow와 같은 방법, 개발 코드로): 표본 구간·고정 응답·지식, 샘플 도면 사본(논리 경로
    자리)과 그 추출·그래프. 이 프로세스의 HAZOP_WORK_ROOT만 잠시 바꾸고 되돌린다."""
    from hazop.app import data
    sources = {name: paths.folder("samples", name) for name in ("regions", "fixed-responses", "knowledge-graph")}
    sample = paths.folder("references", *SAMPLE_DIR)
    old = os.environ.get(paths.ENV_WORK_ROOT)
    os.environ[paths.ENV_WORK_ROOT] = work
    try:
        for name, src in sources.items():
            shutil.copytree(src, paths.folder(name), dirs_exist_ok=True)
        dst = paths.logical_dir(work, "references", *SAMPLE_DIR)
        shutil.copytree(sample, dst)
        drawio = glob.glob(os.path.join(dst, "*.drawio"))[0]
        _, ex_dir = data.script_module("extract_drawio").run_one(drawio, paths.output_root("extract"))
        data.script_module("build_graph").build_one(os.path.join(ex_dir, "extraction.json"), paths.output_root("graph"))
        return os.path.basename(ex_dir)
    finally:
        if old is None:
            os.environ.pop(paths.ENV_WORK_ROOT, None)
        else:
            os.environ[paths.ENV_WORK_ROOT] = old


def kg_work_root(inputs):
    """3) check_kg_screen의 작업 루트. 묶인 실행에서는 샘플 도면 사본이 저장소 참고 폴더가 아니어서 source.file을 작업 루트
    기준 상대 경로로 적는다. 그 경로가 저장소의 기록 경로('참고자료/P&ID 도면 샘플/…')와 같아야 graph_version과
    link_candidates의 target_graph_version이 맞는다. make_inputs가 샘플 도면을 사본의 기록 경로 자리에 두므로 사본 자체를
    작업 루트로 쓴다."""
    if not os.path.isdir(paths.logical_dir(inputs, "references", *SAMPLE_DIR)):
        raise ValueError("샘플 도면 사본이 기록 경로 자리에 없음: %s" % inputs)
    return inputs


def expected_datas(repo=REPO_ROOT):
    """{저장소 상대 경로: sha256} — 빌드가 묶은 datas 원본의 바이트 해시."""
    out = {}
    for src, _ in bp.datas_list(repo):
        with open(os.path.join(repo, *src.split("/")), "rb") as fh:
            out[src] = hashlib.sha256(fh.read()).hexdigest()
    return out


def runtime_path(windir=None):
    """묶인 실행 PATH(D10): Windows System32·Windows 폴더만."""
    windir = windir or bp.windows_dir()
    return os.pathsep.join([os.path.join(windir, "System32"), windir])


CHILD_DROP_PREFIXES = ("QT_", "OPENSSL_", "SSL_CERT_", "HAZOP_")  # 대문자로 비교


def child_env(tmp):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP") and k.upper() != "PATH"
           and not k.upper().startswith(CHILD_DROP_PREFIXES)}
    env["PATH"] = runtime_path()
    env["HAZOP_WORK_ROOT"] = os.path.join(tmp, "work")
    env["APPDATA"] = os.path.join(tmp, "appdata")
    env["TEMP"] = env["TMP"] = os.path.join(tmp, "t")
    for k in ("HAZOP_WORK_ROOT", "APPDATA", "TEMP"):
        os.makedirs(env[k], exist_ok=True)
    return env


def decode(raw):
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def run(cmd, env, cwd, log, timeout=TIMEOUT):
    """(종료 코드 또는 'timeout'·'error: …', 초, 출력). 실행 자체의 예외도 결과로 돌려준다."""
    t0 = time.monotonic()
    try:
        with open(log, "wb") as fh:
            proc = subprocess.run(cmd, env=env, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    except OSError as e:
        rc = "error: %s" % e
    text = ""
    if os.path.isfile(log):
        with open(log, "rb") as fh:
            text = decode(fh.read())
    return rc, round(time.monotonic() - t0, 1), text


BAD_SETTINGS = b"{ not json"  # JSON 문법 오류(W10, D18)


def bad_settings_ok(rc, output, log_tail, intact):
    """손상 설정 + --screenshots: 종료 코드 2, 출력에 안내, 앱 로그에 기록, 설정 파일·폴더 그대로(백업·PNG 없음)."""
    return (rc == 2 and "설정 파일을 읽을 수 없어 종료" in output and "JSONDecodeError" in output
            and "설정 파일을 읽을 수 없음" in log_tail and intact)


def trigger_ok(app_only, rc, log_tail):
    """HAZOP_TEST_EXCEPTHOOK=1 + --screenshots + 손상 설정. 검증용: 트리거가 켜져 종료 코드 70, 앱 로그에 '미처리 예외'와
    시험용 메시지. 배포용: 트리거가 꺼져(표지 훅 없음) 손상 설정 처리로 종료 코드 2, 시험용 메시지 없음."""
    hooked = "시험용 미처리 예외(HAZOP_TEST_EXCEPTHOOK)" in log_tail
    if app_only:
        return rc == 2 and not hooked and "설정 파일을 읽을 수 없음" in log_tail
    return rc == 70 and hooked and "미처리 예외" in log_tail


def _bad_settings(tmp, name):
    """tmp/<name>/settings.json에 손상 설정을 쓰고 (설정 경로, 그 폴더) 반환."""
    d = os.path.join(tmp, name)
    os.mkdir(d)
    path = os.path.join(d, "settings.json")
    with open(path, "wb") as fh:
        fh.write(BAD_SETTINGS)
    return path, d


def _intact(path, folder, png):
    """손상 설정이 그대로이고(백업·덮어쓰기 없음) PNG가 생기지 않았다."""
    with open(path, "rb") as fh:
        return (fh.read() == BAD_SETTINGS and os.listdir(folder) == ["settings.json"]
                and not glob.glob(os.path.join(png, "*.png")))


def app_steps(app_exe, env, tmp, out, png, run_dir, app_only, summary):
    """단계 4(HAZOP.exe). 모든 실행이 비대화형(--screenshots 또는 잘못된 옵션)이라 모달·오류 창을 띄우지 않는다
    (--screenshots 스크린샷 단계는 비모달 창이 잠깐 뜬다). (스크린샷 rc, 초, 잘못된 옵션 rc)를 돌려준다."""
    cmd = [app_exe, "--screenshots", png, "--settings", os.path.join(tmp, "settings.json")]
    if run_dir:
        cmd += ["--run", run_dir]
    rc, sec, _ = run(cmd, env, tmp, os.path.join(out, "app.log"))
    summary["steps"]["app_screenshots"] = {"rc": rc, "sec": sec}
    log_path = os.path.join(env["HAZOP_WORK_ROOT"], "logs", "app.log")
    log1 = read_text(log_path)
    rc2, sec2, text2 = run([app_exe, "--w4-unknown-option"], env, tmp, os.path.join(out, "app-badarg.log"))
    log2 = read_text(log_path)
    # 손상 설정(W10, D18): 비대화형(--screenshots)이면 창 없이 stderr 안내·종료 코드 2, 파일은 그대로
    bad, bad_dir = _bad_settings(tmp, "bad-settings")
    bad_png = os.path.join(tmp, "bad-settings-png")
    rc3, sec3, text3 = run([app_exe, "--screenshots", bad_png, "--settings", bad], env, tmp,
                           os.path.join(out, "app-bad-settings.log"), timeout=60)
    log3 = read_text(log_path)
    summary["steps"]["app_bad_settings"] = {"rc": rc3, "sec": sec3}
    summary["checks"]["app_bad_settings"] = bad_settings_ok(rc3, text3, log3[len(log2):],
                                                            _intact(bad, bad_dir, bad_png))
    # 시험 트리거(D18): 두 빌드 모두 같은 비대화형 실행. 검증용은 미처리 예외 기록(rc 70), 배포용은 트리거 꺼짐(rc 2)
    trig, trig_dir = _bad_settings(tmp, "trigger-settings")
    trig_png = os.path.join(tmp, "trigger-png")
    rc4, sec4, _ = run([app_exe, "--screenshots", trig_png, "--settings", trig], dict(env, HAZOP_TEST_EXCEPTHOOK="1"),
                       tmp, os.path.join(out, "app-excepthook.log"), timeout=60)
    summary["steps"]["app_excepthook"] = {"rc": rc4, "sec": sec4}
    key = "app_trigger_off" if app_only else "app_log_unhandled"
    summary["checks"][key] = (trigger_ok(app_only, rc4, read_text(log_path)[len(log3):])
                              and _intact(trig, trig_dir, trig_png))
    if os.path.isfile(log_path):
        shutil.copyfile(log_path, os.path.join(out, "work-logs-app.log"))
    summary["steps"]["app_bad_option"] = {"rc": rc2, "sec": sec2}
    summary["checks"]["app_log_started"] = "시작 pid=" in log1
    summary["checks"]["translation_problems"] = translation_problems(os.path.dirname(app_exe), log1)
    summary["checks"]["app_bad_option_rc2"] = rc2 == 2 and "unrecognized arguments" in text2
    return rc, sec, rc2


def read_text(path):
    if not os.path.isfile(path):
        return ""
    with open(path, "rb") as fh:
        return decode(fh.read())


def steps(args, summary, run_root, out, repo_dirs):
    """새 폴더를 만든 뒤의 단계 전부(main의 try 안에서 부른다)."""
    png = os.path.join(out, "png")
    target, tmp = os.path.join(run_root, "HAZOP"), os.path.join(run_root, "w4-run")
    summary["target"] = target
    summary["repo_before"] = {d: tree_hashes(paths.folder_in(paths.DEV_WORK_ROOT, d)) for d in repo_dirs}
    shutil.copytree(summary["dist"], target)
    os.mkdir(tmp)
    size, count = tree_size(target)
    summary.update(bundle_bytes=size, bundle_files=count,
                   has_reference_samples=any(os.path.isdir(os.path.join(target, "_internal", *rel.split("/")))
                                             for rel in bp.EXCLUDED_DIRS),
                   has_check_exe=os.path.isfile(os.path.join(target, "HAZOP-check.exe")))
    summary["checks"]["licenses_problems"] = licenses_problems(target)
    summary["checks"]["symbols_problems"] = symbols_problems(target)
    summary["checks"]["icons_problems"] = icons_problems(target)
    env = child_env(tmp)
    summary["child_path"] = env["PATH"]
    start = time.time()
    run_dir = None
    if not args.app_only:
        inputs = os.path.join(tmp, "inputs")
        make_inputs(inputs)
        expect = os.path.join(tmp, "expect.json")
        with open(expect, "w", encoding="utf-8") as fh:
            json.dump(expected_datas(), fh, ensure_ascii=False)
        check_exe, scripts = os.path.join(target, "HAZOP-check.exe"), os.path.join(inputs, "scripts")
        rc, sec, text = run([check_exe, os.path.join(scripts, "w4_flow.py"), "--samples", inputs, "--expect",
                             expect, "--result", os.path.join(out, "flow.json")], env, tmp,
                            os.path.join(out, "flow.log"))
        run_dir = next((ln.split("=", 1)[1].strip() for ln in text.splitlines() if ln.startswith("RUN_DIR=")), None)
        run_dir = run_dir if run_dir and run_dir != "None" else None
        summary["steps"]["flow"] = {"rc": rc, "sec": sec, "run_dir": run_dir,
                                    "lines": [ln.strip() for ln in text.splitlines() if ln.startswith("  [")]}
        print("flow rc=%s %ss" % (rc, sec))

        kenv = dict(env, HAZOP_WORK_ROOT=kg_work_root(inputs), QT_QPA_PLATFORM="windows")
        inputs_before = tree_hashes(inputs)
        rc, sec, text = run([check_exe, os.path.join(scripts, "check_kg_screen.py"), "--skip-tests",
                             "--screenshots", png], kenv, tmp, os.path.join(out, "check_kg_screen.log"))
        summary["checks"]["inputs_unchanged_by_kg_check"] = tree_hashes(inputs) == inputs_before
        summary["steps"]["check_kg_screen"] = {
            "rc": rc, "sec": sec,
            "lines": [ln.strip() for ln in text.splitlines() if ln.strip().startswith(("[OK]", "[FAIL]", "결과"))]}
        print("check_kg_screen rc=%s %ss" % (rc, sec))

        pdf = paths.logical_dir(inputs, "references", *SAMPLE_DIR, SAMPLE_DIR[-1] + ".pdf")
        pres = os.path.join(out, "pdf_probe.json")
        rc, sec, _ = run([check_exe, os.path.join(scripts, "pdf_probe.py"), "--pdf", pdf, "--result", pres], env, tmp,
                         os.path.join(out, "pdf_probe.log"))
        result = None
        if os.path.isfile(pres):
            with open(pres, encoding="utf-8") as fh:
                result = json.load(fh)
        summary["steps"]["pdf_probe"] = {"rc": rc, "sec": sec}
        summary["checks"]["pdf_problems"] = pdf_probe_problems(result, pdf_expected(pdf), target)
        print("pdf_probe rc=%s %ss" % (rc, sec))
    else:
        summary["steps"]["flow"] = summary["steps"]["check_kg_screen"] = {"rc": "skipped(--app-only)"}
        summary["steps"]["pdf_probe"] = {"rc": "skipped(--app-only)"}
        dll = os.path.join(target, "_internal", *bp.PDFIUM_DLL)
        summary["checks"]["pdf_problems"] = [] if os.path.isfile(dll) else ["pdfium.dll 없음: %s" % dll]
        summary["steps"]["seed_app_work"] = {"extraction": seed_app_work(env["HAZOP_WORK_ROOT"])}

    rc, sec, rc2 = app_steps(os.path.join(target, "HAZOP.exe"), env, tmp, out, png, run_dir, args.app_only, summary)
    want = APP_PNG if args.app_only else FULL_PNG
    summary["png"] = sorted(os.path.basename(p) for p in glob.glob(os.path.join(png, "*.png")))
    summary["checks"]["png_fresh_problems"] = fresh_problems(png, start, want)
    print("app rc=%s %ss png=%s, 잘못된 옵션 rc=%s" % (rc, sec, summary["png"], rc2))
    summary["checks"]["repo_unchanged"] = {d: tree_hashes(paths.folder_in(paths.DEV_WORK_ROOT, d)) for d in repo_dirs} \
        == summary.pop("repo_before")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dist", required=True, help="빌드 결과 one-folder(<out>/dist/HAZOP-verify 또는 HAZOP)")
    ap.add_argument("--target-base", required=True,
                    help="검증 사본을 만들 상위 폴더(저장소 밖, 예: %%TEMP%%\\한글테스트). 실행마다 새 하위 폴더")
    ap.add_argument("--out", required=True, help="결과 상위 폴더(실행마다 새 하위 폴더를 만든다)")
    ap.add_argument("--run-name", help="새 하위 폴더 이름(기본 verify-<시각>-<uuid8>). 이미 있으면 실패")
    ap.add_argument("--app-only", action="store_true", help="배포용 빌드: HAZOP.exe 단계만(검증 exe 단계는 건너뜀)")
    args = ap.parse_args(argv)
    dist, base, out_parent = (os.path.abspath(p) for p in (args.dist, args.target_base, args.out))

    pre = []
    if not os.path.isfile(os.path.join(dist, "HAZOP.exe")):
        pre.append("dist에 HAZOP.exe 없음: %s" % dist)
    if not args.app_only and not os.path.isfile(os.path.join(dist, "HAZOP-check.exe")):
        pre.append("dist에 HAZOP-check.exe 없음 — 검증용 빌드(--with-check)가 아님. 배포용이면 --app-only")
    if overlaps(out_parent, REPO_ROOT) or overlaps(out_parent, dist) or overlaps(out_parent, base):
        pre.append("--out이 저장소·dist·대상 상위 폴더와 겹침: %s" % out_parent)
    pre += base_problems(base, dist)
    if pre:
        for p in pre:
            print("중단: %s" % p)
        return 2
    try:
        run_root = new_run_root(base, args.run_name)
    except (FileExistsError, ValueError) as e:
        print("중단: 새 실행 폴더를 만들 수 없음(기존 폴더는 지우지 않음): %s" % e)
        return 2

    summary = {"dist": dist, "run_root": run_root, "app_only": args.app_only, "steps": {}, "errors": {},
               "checks": {}}
    repo_dirs = ("output", "store")
    out = None
    try:
        os.makedirs(out_parent, exist_ok=True)
        out = tempfile.mkdtemp(prefix=time.strftime("run-%Y%m%d-%H%M%S-"), dir=out_parent)
        summary["out"] = out
        steps(args, summary, run_root, out, repo_dirs)
    except Exception as e:  # 단계 밖 예외도 남긴다
        summary["errors"]["main"] = "%s: %s" % (type(e).__name__, e)
    finally:
        summary.pop("repo_before", None)
        try:
            shutil.rmtree(run_root)  # 이번 실행에서 만든 폴더만
        except OSError as e:
            summary["errors"]["cleanup"] = "%s: %s" % (type(e).__name__, e)
        summary["run_root_removed"] = not os.path.exists(run_root)
    checks, st = summary["checks"], summary["steps"]
    rc_ok = all(st.get(k, {}).get("rc") in (0, "skipped(--app-only)")
                for k in ("flow", "check_kg_screen", "pdf_probe", "app_screenshots"))
    summary["passed"] = bool(
        rc_ok and not summary["errors"] and summary["run_root_removed"]
        and not checks.get("png_fresh_problems", ["미실행"])
        and not checks.get("licenses_problems", ["미실행"])
        and not checks.get("symbols_problems", ["미실행"])
        and not checks.get("icons_problems", ["미실행"])
        and not checks.get("translation_problems", ["미실행"])
        and not checks.get("pdf_problems", ["미실행"])
        and checks.get("repo_unchanged") and checks.get("app_log_started") and checks.get("app_bad_option_rc2")
        and checks.get("app_bad_settings")
        and checks.get("app_trigger_off" if args.app_only else "app_log_unhandled")
        and (args.app_only or checks.get("inputs_unchanged_by_kg_check"))
        and summary.get("has_reference_samples") is False
        and summary.get("has_check_exe") is (not args.app_only))
    if out:
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        print("결과 폴더 %s" % out)
    print("묶음 %.1f MB, 파일 %s개, 검사 %s, 오류 %s, 결과 %s"
          % ((summary.get("bundle_bytes") or 0) / 1048576, summary.get("bundle_files"), checks,
             summary["errors"] or "없음", "통과" if summary["passed"] else "실패"))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
