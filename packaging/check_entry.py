"""검증 전용 실행 파일 HAZOP-check.exe의 입구 (패키징 W4). 검증 전용, 배포본 제외(scripts/build_package.py
--with-check로만 만들고, 배포용 빌드에 없음을 build_package.check_dist로 확인한다). 받은 임의의 .py를 실행할 수 있는
도구이므로 배포하지 않는다.

사용: HAZOP-check.exe <스크립트.py> [인자...]
묶인 인터프리터·묶인 hazop 패키지·묶인 Qt로, 저장소 밖 사본에 둔 검사·준비 스크립트를 __main__으로 실행한다.
- 스크립트가 sys.path 앞에 넣는 사본 폴더에는 hazop/ 패키지를 두지 않는다. 그래서 hazop은 묶음에서만 읽힌다.
- check_kg_screen.py만: 사본의 check_kg_renderer를 먼저 읽어 sys.modules에 두고 vendor 경로를 묶음 안 hazop/kg/vendor로
  바꾼다(check_kg_screen이 import할 때 이 모듈을 써서 V2 해시 대조가 묶인 파일을 검사). 읽는 동안 바꾼 sys.path는 되돌린다.
- 대상 스크립트가 sys.path 앞에 넣는 경로는 그 스크립트를 실행하는 동안만 유지하고 끝나면 원복한다.
"""

import os
import runpy
import sys

VENDOR_CHECKS = ("check_kg_screen.py",)


def point_vendor_to_bundle(script_dir):
    """사본 scripts/의 check_kg_renderer를 읽어 VENDOR_* 경로를 묶음 안 hazop.kg.screen.VENDOR_DIR로 바꾼다."""
    import importlib.util

    from hazop.kg import screen
    path = os.path.join(script_dir, "check_kg_renderer.py")
    saved = list(sys.path)
    try:
        sys.path.insert(0, script_dir)
        spec = importlib.util.spec_from_file_location("check_kg_renderer", path)
        kr = importlib.util.module_from_spec(spec)
        sys.modules["check_kg_renderer"] = kr
        spec.loader.exec_module(kr)
    finally:
        sys.path[:] = saved
    kr.VENDOR_DIR = screen.VENDOR_DIR
    kr.VENDOR_JS = os.path.join(screen.VENDOR_DIR, "force-graph.min.js")
    kr.VENDOR_LICENSE = os.path.join(screen.VENDOR_DIR, "LICENSE")
    kr.VENDOR_SOURCE = os.path.join(screen.VENDOR_DIR, "SOURCE.md")
    return kr


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    script = os.path.abspath(sys.argv[1])
    print("[HAZOP-check] frozen=%s _MEIPASS=%s script=%s" % (getattr(sys, "frozen", False),
                                                            getattr(sys, "_MEIPASS", None), script))
    if os.path.basename(script) in VENDOR_CHECKS:
        point_vendor_to_bundle(os.path.dirname(script))
    sys.argv = [script] + sys.argv[2:]
    saved = list(sys.path)
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.path[:] = saved
    return 0


if __name__ == "__main__":
    sys.exit(main())
