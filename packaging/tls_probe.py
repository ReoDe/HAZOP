"""D10 TLS·DLL 측정(검증 전용, 네트워크 접속 없음). 묶인 인터프리터에서 Qt TLS 백엔드와 실제로 로드된 모듈 목록을 남긴다.

사용(전용 venv, 저장소 또는 스냅숏에서):
  python packaging/tls_probe.py --exe <dist/HAZOP-verify/HAZOP-check.exe> --path-mode user --out <결과.json>
- --path-mode user: 이 PC 사용자 PATH 그대로(Git·JDK 등 포함). system: Windows System32·Windows 폴더만.
- 실행기는 HAZOP-check.exe로 이 파일을 다시 실행한다(묶인 모드). 묶인 모드는 다음을 조회해 표준 출력에 'PROBE=' JSON 한 줄을 쓴다.
  CPython ssl 판, QSslSocket 백엔드 목록·활성 백엔드·supportsSsl·라이브러리 판, QNetworkAccessManager 로컬 파일 읽기,
  EnumProcessModules로 얻은 로드 모듈 전체 경로, 그중 UCRT·OpenSSL 관련 이름.
- 실행기는 원본 표준 출력·오류를 <결과>.raw.txt에, 판독 결과를 <결과.json>에 쓴다. 종료 코드 0 = 측정 성공(판정 아님).
"""

import argparse
import json
import os
import subprocess
import sys

WATCH = ("ucrtbase.dll", "vcruntime140.dll", "libssl-3.dll", "libcrypto-3.dll", "libssl-3-x64.dll",
         "libcrypto-3-x64.dll", "qopensslbackend.dll", "qschannelbackend.dll", "qcertonlybackend.dll")


def loaded_modules():
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.K32EnumProcessModules.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32,
                                          ctypes.POINTER(ctypes.c_uint32)]
    k32.K32GetModuleFileNameExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
    proc = k32.GetCurrentProcess()
    arr = (ctypes.c_void_p * 4096)()
    need = ctypes.c_uint32()
    if not k32.K32EnumProcessModules(proc, arr, ctypes.sizeof(arr), ctypes.byref(need)):
        raise OSError("EnumProcessModules 실패: WinError %d" % ctypes.get_last_error())  # 빈 목록을 성공으로 남기지 않음
    count = need.value // ctypes.sizeof(ctypes.c_void_p)
    if count > len(arr):
        raise OSError("모듈 목록 잘림: %d > %d" % (count, len(arr)))
    out, errors = [], []
    for h in arr[:count]:
        buf = ctypes.create_unicode_buffer(32768)
        n = k32.K32GetModuleFileNameExW(proc, h, buf, 32768)
        if not n or n >= 32767:
            errors.append("모듈 이름 조회 실패 또는 잘림: handle=%s" % h)
        else:
            out.append(buf.value)
    return sorted(out, key=str.lower), errors


def probe():
    import ssl
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, QUrl
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QSslSocket
    out = {"frozen": getattr(sys, "frozen", False), "path": os.environ.get("PATH"), "cpython_ssl": ssl.OPENSSL_VERSION}
    app = QCoreApplication(sys.argv[:1])
    out.update(qt_backends=QSslSocket.availableBackends(), qt_active_backend=QSslSocket.activeBackend(),
               qt_supports_ssl=QSslSocket.supportsSsl(), qt_ssl_library=QSslSocket.sslLibraryVersionString())
    import tempfile
    fd, local = tempfile.mkstemp(prefix="hazop-tls-probe-", suffix=".txt")  # 실행마다 고유 파일(동시 실행·기존 파일 보호)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("local-file-ok")
        nam, loop = QNetworkAccessManager(), QEventLoop()
        rep = nam.get(QNetworkRequest(QUrl.fromLocalFile(local)))
        rep.finished.connect(loop.quit)
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        out["qnam_local_file"] = bytes(rep.readAll()).decode("utf-8", "replace")
    finally:
        try:
            os.remove(local)
        except OSError:
            pass
    mods, errors = loaded_modules()
    out["modules"] = mods
    out["module_errors"] = errors
    out["watched"] = {w: [m for m in mods if os.path.basename(m).lower() == w] for w in WATCH}
    del app
    print("PROBE=" + json.dumps(out, ensure_ascii=False))
    return 0


def launch(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", required=True, help="검증용 묶음의 HAZOP-check.exe")
    ap.add_argument("--path-mode", choices=("user", "system"), required=True)
    ap.add_argument("--out", required=True, help="판독 결과 JSON(원본 출력은 같은 이름 .raw.txt)")
    args = ap.parse_args(argv)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONUTF8"], env["PYTHONIOENCODING"] = "1", "utf-8"  # 자식 표준 출력을 UTF-8로 고정(한글 경로 보존)
    if args.path_mode == "system":
        win = os.environ.get("SystemRoot", r"C:\Windows")
        env = {k: v for k, v in env.items() if k.upper() != "PATH"}
        env["PATH"] = os.pathsep.join([os.path.join(win, "System32"), win])
    r = subprocess.run([args.exe, os.path.abspath(__file__)], env=env, capture_output=True, timeout=300)
    head = ("rc=%s\nexe=%s\npath_mode=%s\n" % (r.returncode, args.exe, args.path_mode)).encode("utf-8")
    with open(os.path.splitext(args.out)[0] + ".raw.txt", "wb") as fh:  # 원본 바이트 그대로 보존
        fh.write(head + r.stdout + b"\n--- stderr ---\n" + r.stderr)
    line = next((ln for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.startswith("PROBE=")), None)
    result = {"rc": r.returncode, "exe": args.exe, "path_mode": args.path_mode,
              "probe": json.loads(line[len("PROBE="):]) if line else None}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    p = result["probe"] or {}
    print("rc=%s backends=%s active=%s x64_ssl=%s" % (r.returncode, p.get("qt_backends"), p.get("qt_active_backend"),
                                                       (p.get("watched") or {}).get("libssl-3-x64.dll")))
    ok = r.returncode == 0 and line and p.get("modules") and not p.get("module_errors")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(probe() if getattr(sys, "frozen", False) else launch(sys.argv[1:]))
