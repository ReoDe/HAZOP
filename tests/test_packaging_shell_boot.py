"""묶음 검증의 새 화면 기동 단계(packaging/verify_bundle.py 4c) 시험. 실행: python -m unittest tests.test_packaging_shell_boot

실제 빌드 없이 판정 규칙(shell_problems)과 표준 라이브러리 CDP 클라이언트(Cdp)의 WebSocket 틀 처리(가림, 긴 틀, 조각, ping)를
프로세스 안 작은 서버로 확인한다. 묶인 실행에서 새 화면을 띄우는 일은 verify_bundle 실행에서 본다.
"""

import base64
import hashlib
import importlib.util
import json
import os
import socket
import threading
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load():
    spec = importlib.util.spec_from_file_location("vb_shell_boot", os.path.join(REPO, "packaging", "verify_bundle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VB = load()
GOOD = {"booted": True, "assets": {a: 100 for a in VB.SHELL_ASSETS}, "icons": 54, "symbols": 31,
        "panels": {"도면 (Ctrl+1)": "도면", "설정": "설정"}, "script_errors": [], "errors_run": []}


class ShellProblemsTest(unittest.TestCase):
    def test_a_good_run_passes(self):
        self.assertEqual(VB.shell_problems(GOOD), [])

    def test_each_failure_is_named(self):
        cases = {
            "뜨지 않음": dict(GOOD, booted=False, boot_text="화면을 시작하지 못했습니다: x"),
            "웹 자원": dict(GOOD, assets=dict(GOOD["assets"], **{"vendor/htm.module.js": -404})),
            "아이콘": dict(GOOD, icons=0),
            "기호 그림": dict(GOOD, symbols="TypeError"),
            "패널 단추가 없음": dict(GOOD, panels={}),
            "패널이 열리지 않음: 설정": dict(GOOD, panels={"설정": None}),
            "스크립트 오류": dict(GOOD, script_errors=["ReferenceError: x"]),
            "페이지를 찾지 못함": dict(GOOD, errors_run=["새 화면 페이지를 찾지 못함(종료 코드 1)"]),
        }
        for want, result in cases.items():
            with self.subTest(want):
                self.assertTrue(any(want in p for p in VB.shell_problems(result)), VB.shell_problems(result))
        self.assertEqual(VB.shell_problems(None), ["새 화면 점검 결과 없음"])


def _frame(op, payload, fin=True):
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | op])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + n.to_bytes(2, "big")
    else:
        head += bytes([127]) + n.to_bytes(8, "big")
    return head + payload


def _read_client_frame(conn):
    def read(n):
        out = b""
        while len(out) < n:
            out += conn.recv(n - len(out))
        return out
    b0, b1 = read(2)
    n = b1 & 0x7F
    if n == 126:
        n = int.from_bytes(read(2), "big")
    elif n == 127:
        n = int.from_bytes(read(8), "big")
    assert b1 & 0x80, "클라이언트 틀은 가려야 함"
    mask = read(4)
    data = bytes(b ^ mask[i % 4] for i, b in enumerate(read(n)))
    return b0 & 0x0F, data


class CdpFramingTest(unittest.TestCase):
    def test_masking_long_fragmented_and_ping(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        seen = {}

        def serve():
            conn, _ = srv.accept()
            head = b""
            while b"\r\n\r\n" not in head:
                head += conn.recv(1024)
            key = [ln.split(b": ", 1)[1] for ln in head.split(b"\r\n") if ln.lower().startswith(b"sec-websocket-key")][0]
            accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
            op, data = _read_client_frame(conn)
            req = json.loads(data)
            seen["request"] = req
            big = "가" * 40000   # 64KB를 넘는 응답(8바이트 길이)
            event = json.dumps({"method": "Runtime.exceptionThrown", "params": {}}).encode("utf-8")
            reply = json.dumps({"id": req["id"], "result": {"result": {"value": big}}}, ensure_ascii=False).encode("utf-8")
            conn.sendall(_frame(0x9, b"hi"))                              # ping
            conn.sendall(_frame(0x1, event))                              # 다른 사건 하나
            conn.sendall(_frame(0x1, reply[:10], fin=False) + _frame(0x0, reply[10:]))   # 두 조각
            seen["pong"] = _read_client_frame(conn)
            conn.close()
            srv.close()

        t = threading.Thread(target=serve)
        t.start()
        cdp = VB.Cdp("ws://127.0.0.1:%d/devtools/page/x" % port, timeout=10)
        value = cdp.evaluate("1+1")
        cdp.close()
        t.join(10)
        self.assertEqual(len(value), 40000)
        self.assertEqual(seen["request"]["method"], "Runtime.evaluate")
        self.assertEqual(seen["pong"], (0xA, b"hi"), "ping에는 같은 내용의 pong")
        self.assertEqual([m["method"] for m in cdp.events], ["Runtime.exceptionThrown"], "응답이 아닌 사건은 따로 모음")


if __name__ == "__main__":
    unittest.main()
