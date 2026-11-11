"""PyInstaller 런타임 훅(HAZOP.exe 전용, scripts/build_package.py가 spec에 넣는다). 패키징 W4 재작업(총괄 L2).

창 프로그램(console=False)은 stdout·stderr가 없어 오류가 사라진다. 묶인 실행에서만 <작업 루트>/logs/app.log에
logging 출력(root, INFO 이상)·stdout·stderr·미처리 예외(sys.excepthook)를 남긴다. 작업 루트는 hazop.paths.work_root()
(HAZOP_WORK_ROOT, 없으면 %LOCALAPPDATA%\\HAZOP). 로그 준비에 실패해도 앱 기동은 막지 않는다. 네트워크를 쓰지 않는다.
"""

import os
import sys


def install(log_dir):
    """log_dir/app.log에 기록을 연결하고 경로를 돌려준다(개발 실행 테스트에서도 직접 부를 수 있다)."""
    import logging

    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "app.log")
    stream = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        try:  # 로그 쓰기가 실패해도 이전 훅(기본 처리·PyInstaller 오류 표시)은 반드시 부른다
            logging.getLogger("hazop.unhandled").critical("미처리 예외", exc_info=(exc_type, exc, tb))
            handler.flush()
        except Exception:
            pass
        finally:
            previous(exc_type, exc, tb)

    sys.excepthook = hook
    logging.getLogger("hazop.startup").info("시작 pid=%d frozen=%s argv=%r", os.getpid(),
                                            bool(getattr(sys, "frozen", False)), sys.argv[1:])
    return path


if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
    try:
        from hazop import paths

        install(os.path.join(paths.raw_work_root(), "logs"))  # 로그는 옛 작업 폴더를 옮기기 전에도 남긴다
    except Exception:  # 로그를 못 남겨도 앱은 띄운다
        pass
