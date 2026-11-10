"""사용자 입장 검증: 실제 HAZOP 창을 키보드·마우스로 조작하는 시나리오를 돌리고 결과 표(HTML)를 만든다.

사용: python scripts/check_user_scenarios.py --out <폴더> [--only S1,S3] [--keep-temp] [--focus-wait 120]

- 임시 작업 루트에 샘플 도면 SNP-M-102(출력/ 사본, 검토구간 확정, 가짜 AI 결과)를 준비한다. 자료저장소/에 쓰지 않는다.
- 앱(run_app.py와 같은 창 + 가짜 AI 클라이언트, 호출마다 AI_DELAY초)을 QTWEBENGINE_REMOTE_DEBUGGING으로 띄우고, Qt 위젯은 Windows UI Automation(scripts/uia_server.ps1),
  웹뷰(②③④)는 CDP로 읽는다. 입력은 Win32 SendInput(실제 키보드·마우스 이벤트)으로 보낸다.
- 입력 전마다 이 실행이 띄운 창이 맨 앞인지 확인하고, 아니면 입력을 보내지 않고 시나리오를 중단한다.
- 끝나면 띄운 프로세스 트리만 정리한다. 결과: <out>/report.html, <out>/results.json, <out>/shots/*.png
종료 코드: 0 모든 시나리오 통과, 1 실패 시나리오 있음, 2 준비·실행 오류.
"""

import argparse
import base64
import html
import json
import os
import re
import shutil
import socket
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from hazop import paths  # noqa: E402  (표준 라이브러리만 쓰는 경로 모듈)
CDP_PORT = 9339
WINDOW_SIZE = (1366, 768)
DRAWIO_SAMPLE = paths.folder("참고", "pid-samples", "SNP-M-201_CVCS", "SNP-M-201_CVCS.drawio")

# KLM 연산자 시간(초). Card, Moran & Newell(1980) "The Keystroke-Level Model for User Performance Time with Interactive
# Systems", CACM 23(7):396-410. K는 비전문 평균 타자(40 wpm) 값 0.28(같은 논문 표 1의 범위 0.08~1.2 중).
KLM = {"K": 0.28, "P": 1.10, "B": 0.10, "H": 0.40, "M": 1.35}
KLM_SOURCE = "Card, Moran & Newell (1980), CACM 23(7):396-410, 표 1"
SEVERITY_ORDER = {"상": 0, "중": 1, "하": 2}
NAMED_TYPES = ("Button", "CheckBox", "Edit", "ComboBox", "RadioButton", "MenuItem", "TabItem", "Hyperlink", "Slider",
               "Spinner", "SplitButton")
STAGE_WHERE = ("①", "②", "③", "④", "⑤")
SCROLLED_TYPES = ("ListItem", "TreeItem", "DataItem", "Header", "HeaderItem", "Custom")  # 스크롤 안 내용은 창 밖이어도 정상


# ------------------------------------------------------------------ 순수 계산(창 없이 시험)
def klm_seconds(ops):
    """KLM 연산자 문자열 목록의 예상 숙련자 시간(초)."""
    return round(sum(KLM[o] for o in ops), 2)


def klm_ops_for(kind, n=1, hand="keyboard"):
    """(연산자 목록, 바뀐 손 위치). kind: key(n개 동시 키) · type(n글자) · click · think."""
    if kind == "think":
        return ["M"], hand
    if kind in ("key", "type"):
        return (["H"] if hand == "mouse" else []) + ["K"] * n, "keyboard"
    if kind == "click":
        return (["H"] if hand == "keyboard" else []) + ["P", "B", "B"], "mouse"
    raise ValueError(kind)


def unnamed_controls(items):
    """UIA 요소 중 이름 없는 조작 요소(화면 밖 제외)."""
    return [e for e in items if e.get("type") in NAMED_TYPES and not (e.get("name") or "").strip()
            and not e.get("offscreen") and e.get("rect")]


def outside_window(items, win_rect):
    """창 왼쪽·오른쪽 끝을 넘는(가로로 잘려 보일) 이름 있는 요소. 스크롤 영역 안 항목은 뺀다."""
    if not win_rect:
        return []
    wx, wy, ww, wh = win_rect
    out = []
    for e in items:
        r = e.get("rect")
        if not r or e.get("offscreen") or e.get("type") == "Window" or not (e.get("name") or "").strip():
            continue
        x, y, w, h = r
        if w <= 0 or h <= 0:
            continue
        if e.get("type") in SCROLLED_TYPES:
            continue
        if x < wx - 1 or x + w > wx + ww + 1:
            out.append(e)
    return out


def ws_frame(payload, mask_key):
    """클라이언트→서버 텍스트 프레임(RFC 6455, 마스킹)."""
    data = payload.encode("utf-8")
    n = len(data)
    head = bytes([0x81])
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 65536:
        head += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack(">Q", n)
    return head + mask_key + bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))


def ws_parse(buf):
    """서버 프레임 하나를 읽는다. (fin, opcode, payload, 쓴 바이트 수) 또는 모자라면 None."""
    if len(buf) < 2:
        return None
    fin, op, n, i = buf[0] >> 7, buf[0] & 0x0F, buf[1] & 0x7F, 2
    if n == 126:
        if len(buf) < 4:
            return None
        n, i = struct.unpack(">H", buf[2:4])[0], 4
    elif n == 127:
        if len(buf) < 10:
            return None
        n, i = struct.unpack(">Q", buf[2:10])[0], 10
    if buf[1] & 0x80:
        if len(buf) < i + 4 + n:
            return None
        key, i = buf[i:i + 4], i + 4
        return fin, op, bytes(b ^ key[k % 4] for k, b in enumerate(buf[i:i + n])), i + n
    if len(buf) < i + n:
        return None
    return fin, op, bytes(buf[i:i + n]), i + n


def verdict(result):
    if not result["passed"]:
        return "실패"
    return "판정 불가" if result.get("inconclusive") else "통과"


def summarize(result):
    lat = [x["seconds"] for x in result["latencies"]]
    return {"clicks": result["clicks"], "keys": result["keys"], "screens": result["screens"],
            "klm": klm_seconds(result["ops"]), "elapsed": result["elapsed"],
            "lat_max": round(max(lat), 2) if lat else None, "lat_median": round(statistics.median(lat), 2) if lat else None,
            "keyboard_only": result["clicks"] == 0, "focus_lost": len(result["focus_lost"])}


def render_report(results, audits, meta):
    """결과 표 한 장(HTML). 스크린샷은 shots/ 상대 경로로 건다."""
    esc = html.escape
    rows, defects = [], []
    for r in results:
        s = summarize(r)
        rows.append("<tr><td>%s<br><small>%s</small></td><td class='%s'>%s</td><td>%d</td><td>%d</td><td>%d</td>"
                    "<td>%.1f</td><td>%.1f</td><td>%s / %s</td><td>%s</td><td>%d</td><td>%d</td></tr>" % (
                        esc(r["id"]), esc(r["title"] + (" · " + r["inconclusive"] if r.get("inconclusive") else "")),
                        "ok" if verdict(r) == "통과" else "bad", verdict(r),
                        s["clicks"], s["keys"], s["screens"], s["klm"], s["elapsed"],
                        "-" if s["lat_median"] is None else "%.2f" % s["lat_median"],
                        "-" if s["lat_max"] is None else "%.2f" % s["lat_max"],
                        "예" if s["keyboard_only"] else "아니오", s["focus_lost"], len(r["defects"])))
        defects += [dict(d, scenario=r["id"]) for d in r["defects"]]
    defects.sort(key=lambda d: (SEVERITY_ORDER.get(d["severity"], 9), d["scenario"]))
    drows = []
    for i, d in enumerate(defects, 1):
        shot = ("<a href='%s'><img src='%s'></a>" % (esc(d["shot"]), esc(d["shot"]))) if d.get("shot") else ""
        drows.append("<tr><td>D%d</td><td>%s</td><td>%s</td><td>%s<br><small>%s</small></td><td><ol>%s</ol></td><td>%s</td></tr>" % (
            i, esc(d["severity"]), esc(d["scenario"]), esc(d["title"]), esc(d.get("detail", "")),
            "".join("<li>%s</li>" % esc(s) for s in d.get("steps", [])), shot))
    arows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(a["where"]), esc(a["kind"]), esc(a["detail"]))
                    for a in audits)
    shots = "".join("<figure><img src='%s'><figcaption>%s · %s</figcaption></figure>" % (esc(p), esc(sid), esc(lbl))
                    for r in results for sid, lbl, p in [(r["id"], s[0], s[1]) for s in r["shots"]])
    klm = "".join("<tr><td>%s</td><td>%.2f</td></tr>" % (k, v) for k, v in KLM.items())
    return """<!doctype html><html lang="ko"><meta charset="utf-8"><title>사용자 시나리오 검증</title>
<style>body{font:14px 'Malgun Gothic',sans-serif;margin:16px;color:#222}table{border-collapse:collapse;margin:8px 0 20px}
td,th{border:1px solid #bbb;padding:4px 6px;vertical-align:top}th{background:#eee}.ok{color:#176d2c;font-weight:bold}
.bad{color:#b00020;font-weight:bold}td img{max-width:220px}figure{display:inline-block;margin:4px;width:300px}
figure img{width:300px;border:1px solid #ccc}figcaption{font-size:12px}small{color:#555}</style>
<h1>사용자 시나리오 검증</h1><p>%s</p>
<h2>시나리오</h2><table><tr><th>시나리오</th><th>결과</th><th>클릭</th><th>키 입력</th><th>화면 전환</th>
<th>KLM 예상(초)</th><th>실측 소요(초)</th><th>응답 중앙/최대(초)</th><th>키보드만</th><th>포커스 이탈</th><th>결함</th></tr>%s</table>
<h2>결함 (%d)</h2><table><tr><th>#</th><th>심각도</th><th>시나리오</th><th>결함</th><th>재현 단계</th><th>스크린샷</th></tr>%s</table>
<h2>화면 점검(접근성 이름·잘림·가로 스크롤)</h2><table><tr><th>화면</th><th>종류</th><th>내용</th></tr>%s</table>
<h2>KLM 연산자</h2><p>출처: %s. K 키 하나, P 가리키기, B 버튼 누름·뗌(클릭=BB), H 키보드↔마우스 손 이동, M 생각. 각 의도 단계 앞에 M 하나.</p>
<table><tr><th>연산자</th><th>초</th></tr>%s</table>
<h2>단계별 스크린샷</h2>%s</html>""" % (esc(meta), "".join(rows), len(defects), "".join(drows), arows, esc(KLM_SOURCE),
                                          klm, shots)


# ------------------------------------------------------------------ Win32 입력·화면
class Win32:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.u = ctypes.windll.user32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except OSError:
            pass

    def window_pid(self, hwnd):
        pid = self.wt.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
        return pid.value

    def foreground_title(self):
        hwnd = self.u.GetForegroundWindow()
        buf = self.ct.create_unicode_buffer(256)
        self.u.GetWindowTextW(hwnd, buf, 256)
        return "%s (pid %d)" % (buf.value, self.window_pid(hwnd))

    def foreground_pid(self):
        return self.window_pid(self.u.GetForegroundWindow())

    def activate(self, hwnd):
        fg = self.u.GetForegroundWindow()
        cur = self.ct.windll.kernel32.GetCurrentThreadId()
        fg_thread = self.u.GetWindowThreadProcessId(fg, None)
        self.u.AttachThreadInput(cur, fg_thread, True)
        self.u.ShowWindow(hwnd, 9)
        self.u.BringWindowToTop(hwnd)
        self.u.SetForegroundWindow(hwnd)
        self.u.AttachThreadInput(cur, fg_thread, False)
        if self.window_pid(self.u.GetForegroundWindow()) != self.window_pid(hwnd):
            self.u.SwitchToThisWindow(hwnd, True)

    def resize(self, hwnd, w, h):
        r = self.wt.RECT()
        self.u.GetWindowRect(hwnd, self.ct.byref(r))
        self.u.ShowWindow(hwnd, 9)
        self.u.SetWindowPos(hwnd, 0, r.left, r.top, w, h, 0x0004)

    def _unicode(self, ch, up):
        ct = self.ct

        class KI(ct.Structure):
            _fields_ = [("wVk", ct.c_ushort), ("wScan", ct.c_ushort), ("dwFlags", ct.c_ulong), ("time", ct.c_ulong),
                        ("extra", ct.c_size_t)]

        class INPUT(ct.Structure):
            _fields_ = [("type", ct.c_ulong), ("ki", KI), ("pad", ct.c_ubyte * 8)]
        inp = INPUT(1, KI(0, ch, 0x0004 | (0x0002 if up else 0), 0, 0))
        self.u.SendInput(1, ct.byref(inp), ct.sizeof(INPUT))

    def chord(self, vks):
        for vk in vks:
            self.u.keybd_event(vk, 0, 0, 0)
        for vk in reversed(vks):
            self.u.keybd_event(vk, 0, 0x0002, 0)

    def ime_hangul(self, hwnd):
        """창의 IME 변환 상태가 한글이면 True(IMC_GETCONVERSIONMODE). 알 수 없으면 None."""
        ime = self.ct.windll.imm32.ImmGetDefaultIMEWnd(hwnd)
        return bool(self.u.SendMessageW(ime, 0x0283, 0x0001, 0) & 1) if ime else None

    def set_hangul(self, hwnd, on):
        """IME를 한글/영문으로. IMC_SETCONVERSIONMODE를 보내고, 안 바뀌면 한/영 키(스캔 코드 0xF2)를 한 번 보낸다."""
        ime = self.ct.windll.imm32.ImmGetDefaultIMEWnd(hwnd)
        if ime:
            self.u.SendMessageW(ime, 0x0283, 0x0002, 1 if on else 0)
        time.sleep(0.1)
        if self.ime_hangul(hwnd) is not None and self.ime_hangul(hwnd) != on:
            self.u.keybd_event(VK["hangul"], 0xF2, 0, 0)
            self.u.keybd_event(VK["hangul"], 0xF2, 0x0002, 0)
            time.sleep(0.1)

    def type_text(self, text):
        for ch in text:
            self._unicode(ord(ch), False)
            self._unicode(ord(ch), True)

    def pid_at(self, x, y):
        """화면 좌표 아래 최상위 창의 프로세스."""
        pt = self.wt.POINT(int(x), int(y))
        hwnd = self.u.WindowFromPoint(pt)
        return self.window_pid(self.u.GetAncestor(hwnd, 2)) if hwnd else 0

    def click(self, x, y):
        self.u.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        self.u.mouse_event(0x0002, 0, 0, 0, 0)
        self.u.mouse_event(0x0004, 0, 0, 0, 0)

    def grab(self, rect, path):
        from PIL import ImageGrab
        x, y, w, h = rect
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(path)


VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "back": 0x08, "left": 0x25,
      "up": 0x26, "right": 0x27, "down": 0x28, "f1": 0x70, "f2": 0x71, "f4": 0x73, "f6": 0x75, "hangul": 0x15, "space": 0x20}


def parse_chord(chord):
    """'ctrl+shift+e' → 가상 키 코드 목록."""
    out = []
    for part in chord.lower().split("+"):
        if part in VK:
            out.append(VK[part])
        elif len(part) == 1 and (part.isalnum()):
            out.append(ord(part.upper()))
        else:
            raise ValueError("모르는 키: %s" % part)
    return out


# ------------------------------------------------------------------ UIA·CDP 클라이언트
class Uia:
    def __init__(self):
        self.p = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                   os.path.join(REPO_ROOT, "scripts", "uia_server.ps1")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding="utf-8")

    def q(self, **kw):
        self.p.stdin.write(json.dumps(kw) + "\n")
        self.p.stdin.flush()
        r = json.loads(self.p.stdout.readline().lstrip("\ufeff"))
        if not r.get("ok"):
            raise RuntimeError("UIA: %s" % r.get("error"))
        for e in r["items"]:
            for k in ("name", "aid", "cls"):
                if k in e and e[k] is None:
                    e[k] = ""
        return r["items"]

    def close(self):
        try:
            self.p.stdin.write('{"op":"quit"}\n')
            self.p.stdin.flush()
            self.p.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            self.p.kill()


class Cdp:
    def __init__(self, port):
        self.port, self.sock, self.n, self.url = port, None, 0, None

    def pages(self):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % self.port, timeout=3) as fh:
                return [p for p in json.load(fh) if p.get("type") == "page"]
        except OSError:
            return []

    def _connect(self, ws_url):
        hostport, path = ws_url[len("ws://"):].split("/", 1)
        host, port = hostport.split(":")
        s = socket.create_connection((host, int(port)), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall(("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key)).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += s.recv(4096)
        if b" 101 " not in buf.split(b"\r\n", 1)[0]:
            raise RuntimeError("CDP 연결 실패")
        self.sock, self.buf, self.url = s, buf.split(b"\r\n\r\n", 1)[1], ws_url

    def _recv(self):
        parts = b""
        while True:
            r = ws_parse(self.buf)
            if r is None:
                self.buf += self.sock.recv(65536)
                continue
            fin, op, payload, used = r
            self.buf = self.buf[used:]
            if op in (0x1, 0x0):
                parts += payload
                if fin:
                    return json.loads(parts.decode("utf-8"))

    def evaluate(self, expr):
        pages = self.pages()
        if not pages:
            return None
        if self.url != pages[0]["webSocketDebuggerUrl"]:
            self.close()
            self._connect(pages[0]["webSocketDebuggerUrl"])
        self.n += 1
        self.sock.sendall(ws_frame(json.dumps({"id": self.n, "method": "Runtime.evaluate",
                                               "params": {"expression": expr, "returnByValue": True}}), os.urandom(4)))
        while True:
            msg = self._recv()
            if msg.get("id") == self.n:
                return msg.get("result", {}).get("result", {}).get("value")

    def close(self):
        if self.sock:
            self.sock.close()
        self.sock, self.url = None, None


DOM_AUDIT_JS = r"""(() => {
  const de = document.documentElement, out = {url: location.pathname.split('/').pop(), hscroll: de.scrollWidth > de.clientWidth + 1,
    scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, truncated: [], offscreen: [], unnamed: [], overlaps: []};
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('svg'); };
  const label = e => (e.getAttribute('aria-label') || e.getAttribute('title') || e.textContent || e.value || e.placeholder ||
    (e.labels && e.labels[0] && e.labels[0].textContent) || '').trim();
  const desc = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : '');
  const leaves = [];
  for (const e of document.querySelectorAll('body *')) {
    if (!vis(e)) continue;
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (own && e.scrollWidth > e.clientWidth + 1 && !['auto', 'scroll'].includes(s.overflowX) && s.overflowX !== 'visible')
      out.truncated.push(desc(e) + ' "' + e.textContent.trim().slice(0, 40) + '"');
    if (own && (r.right > de.clientWidth + 1 || r.bottom > de.clientHeight + 1) && s.position === 'fixed')
      out.offscreen.push(desc(e));
    if (e.matches('button,a[href],input,select,textarea,[role=button],[tabindex]:not([tabindex="-1"])') && !label(e))
      out.unnamed.push(desc(e));
    if (own && leaves.length < 400) leaves.push([e, r]);
  }
  for (let i = 0; i < leaves.length && out.overlaps.length < 20; i++) for (let j = i + 1; j < leaves.length; j++) {
    const [a, ra] = leaves[i], [b, rb] = leaves[j];
    if (a.contains(b) || b.contains(a)) continue;
    const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left), h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
    if (w > 4 && h > 4) { out.overlaps.push(desc(a) + ' × ' + desc(b)); if (out.overlaps.length >= 20) break; }
  }
  return out;
})()"""


# ------------------------------------------------------------------ 실행기
class Abort(Exception):
    pass


class Driver:
    """시나리오가 쓰는 조작·관찰. 조작마다 KLM 연산자·키·클릭·화면 전환·포커스를 기록한다."""

    def __init__(self, w32, uia, cdp, app_pid, hwnd, shots_dir, data_root):
        self.w32, self.uia, self.cdp, self.pid, self.hwnd = w32, uia, cdp, app_pid, hwnd
        self.shots_dir, self.data_root = shots_dir, data_root
        self.audits, self.audited = [], set()
        self.family = {app_pid}
        self.focus_wait = 120

    def ours(self, pid):
        """앱 프로세스와 그 자식(QtWebEngineProcess)이면 참."""
        if pid not in self.family:
            self.family = {self.pid} | {c["pid"] for c in self.uia.q(op="children", pid=self.pid)}
        return pid in self.family

    def begin(self, sid, title):
        self.r = {"id": sid, "title": title, "passed": True, "clicks": 0, "keys": 0, "screens": 0, "ops": [],
                  "latencies": [], "focus_lost": [], "defects": [], "shots": [], "steps": [], "elapsed": 0.0}
        self.hand, self.t0, self.last_where = "keyboard", time.time(), self.where()
        return self.r

    def end(self):
        self.r["elapsed"] = round(time.time() - self.t0, 1)

    # 관찰
    def tree(self):
        return self.uia.q(op="tree", pid=self.pid, cap=1500)

    def find(self, pred, items=None):
        return [e for e in (items if items is not None else self.tree()) if pred(e)]

    def where(self):
        hits = [e for e in self.uia.q(op="tree", pid=self.pid, cap=40) if e["aid"].endswith("header.where")]
        return hits[0]["name"] if hits else ""

    def windows(self):
        return self.uia.q(op="windows", pid=self.pid)

    def texts(self):
        return [e["name"] for e in self.tree() if e.get("name")]

    def entry_counts(self):
        counts = {}
        for root, _dirs, files in os.walk(self.data_root):
            for f in files:
                if f.endswith(".json") and ".bak." not in f:
                    try:
                        with open(os.path.join(root, f), encoding="utf-8") as fh:
                            self._count(json.load(fh), counts)
                    except (OSError, ValueError):
                        pass
        return counts

    def data_stamp(self):
        """저장 파일들의 (이름, 수정 시각). 실행 중 결과가 저장될 때마다 바뀐다."""
        out = []
        for root, _dirs, files in os.walk(self.data_root):
            out += [(f, os.path.getmtime(os.path.join(root, f))) for f in files if f.endswith(".json") and ".bak." not in f]
        return sorted(out)

    def _count(self, o, counts):
        if isinstance(o, dict):
            if "origin" in o and o.get("status") in ("proposed", "revised", "approved", "rejected"):
                counts[o["status"]] = counts.get(o["status"], 0) + 1
            for v in o.values():
                self._count(v, counts)
        elif isinstance(o, list):
            for v in o:
                self._count(v, counts)

    # 조작
    def step(self, text, think=True):
        self.r["steps"].append(text)
        if think:
            self.r["ops"] += ["M"]

    def _guard(self):
        for _ in range(4):
            if self.ours(self.w32.foreground_pid()):
                return
            self.w32.activate(self.hwnd)
            time.sleep(0.3)
        print("  Windows가 창 전환을 막았습니다. 깜박이는 'HAZOP 분석 도구' 창을 한 번 클릭하고, 끝날 때까지 "
              "키보드·마우스를 만지지 마세요(최대 %d초 기다림)" % self.focus_wait, flush=True)
        self.w32.u.FlashWindow(self.hwnd, True)
        end = time.time() + self.focus_wait
        while time.time() < end:
            if self.ours(self.w32.foreground_pid()):
                self.r["focus_waits"] = self.r.get("focus_waits", 0) + 1
                time.sleep(1.0)
                return
            time.sleep(0.3)
        raise Abort("이 실행이 띄운 HAZOP 창이 맨 앞이 아니어서 입력을 보내지 않았습니다(맨 앞 창: %s)"
                    % self.w32.foreground_title())

    def _after(self):
        time.sleep(0.15)
        f = self.uia.q(op="focus")
        if not f or not self.ours(f[0]["pid"]):
            self.r["focus_lost"].append("%s → %s" % (self.r["steps"][-1] if self.r["steps"] else "?",
                                                     "%s '%s' pid %s" % (f[0]["type"], (f[0]["name"] or "")[:30], f[0]["pid"])
                                                     if f else "초점 요소 없음"))
        w = self.where()
        if w != self.last_where:
            self.r["screens"] += 1
            self.last_where = w

    def key(self, chord):
        self._guard()
        vks = parse_chord(chord)
        ops, self.hand = klm_ops_for("key", len(vks), self.hand)
        self.r["ops"] += ops
        self.r["keys"] += len(vks)
        self.w32.chord(vks)
        self._after()

    def type(self, text):
        self._guard()
        ops, self.hand = klm_ops_for("type", len(text), self.hand)
        self.r["ops"] += ops
        self.r["keys"] += len(text)
        self.w32.type_text(text)
        self._after()

    def click(self, el, dx=None, dy=None):
        self._guard()
        x, y, w, h = el["rect"]
        cx, cy = x + (w // 2 if dx is None else dx), y + (h // 2 if dy is None else dy)
        if not self.ours(self.w32.pid_at(cx, cy)):
            raise Abort("클릭할 자리(%d,%d) 아래 창이 이 실행의 앱이 아니어서 클릭하지 않았습니다" % (cx, cy))
        ops, self.hand = klm_ops_for("click", 1, self.hand)
        self.r["ops"] += ops
        self.r["clicks"] += 1
        self.w32.click(cx, cy)
        self._after()

    def wait(self, pred, what, timeout=10.0, since=None):
        """pred()가 참이 될 때까지 기다리고 응답 시간을 기록한다. 시간 초과면 False."""
        start = since if since is not None else time.time()
        while time.time() - start < timeout:
            v = pred()
            if v:
                self.r["latencies"].append({"what": what, "seconds": round(time.time() - start, 2)})
                return v
            time.sleep(0.05)
        return False

    def inconclusive(self, title, detail=""):
        """시험 전제가 서지 않아 판정하지 못함. 앱 결함이 아니므로 실패로 세지 않는다."""
        self.r["inconclusive"] = "%s %s" % (title, detail)
        self.shot("판정 불가")

    def expect(self, ok, title, detail="", severity="중"):
        if not ok:
            self.r["passed"] = False
            self.defect(severity, title, detail)
        return ok

    def defect(self, severity, title, detail=""):
        shot = self.shot("결함-" + title[:20])
        self.r["defects"].append({"severity": severity, "title": title, "detail": detail,
                                  "steps": list(self.r["steps"]), "shot": shot})

    def shot(self, label):
        n = len(self.r["shots"]) + 1
        name = "%s-%02d.png" % (self.r["id"], n)
        rects = [w["rect"] for w in self.windows() if w.get("rect")]
        if not rects:
            return None
        x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
        x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
        try:
            self.w32.grab((x0, y0, x1 - x0, y1 - y0), os.path.join(self.shots_dir, name))
        except OSError:
            return None
        rel = "shots/" + name
        self.r["shots"].append((label, rel))
        return rel

    def audit(self):
        """지금 화면을 한 번만 점검한다: UIA 이름 없는 조작 요소·창 밖 요소, 웹뷰 DOM 잘림·겹침·가로 스크롤."""
        where = self.where()
        if where in self.audited:
            return
        self.audited.add(where)
        items = self.tree()
        win = next((w for w in items if w["type"] == "Window" and w["cls"] == "MainWindow"), None)
        for e in unnamed_controls(items):
            self.audits.append({"where": where, "kind": "UIA 이름 없음",
                                "detail": "%s · %s" % (e["type"], e["aid"].split("QApplication.MainWindow.")[-1])})
        for e in outside_window(items, win and win["rect"]):
            self.audits.append({"where": where, "kind": "창 밖으로 잘림", "detail": "%s '%s'" % (e["type"], e["name"][:40])})
        if not where.startswith(("②", "③", "④")):
            return
        d = None
        for _ in range(20):
            d = self.cdp.evaluate(DOM_AUDIT_JS)
            if d:
                break
            time.sleep(0.25)
        if not d:
            self.audits.append({"where": where, "kind": "CDP", "detail": "웹뷰 페이지를 읽지 못함"})
            return
        if d["hscroll"]:
            self.audits.append({"where": where, "kind": "웹뷰 가로 스크롤",
                                "detail": "scrollWidth %d > clientWidth %d" % (d["scrollWidth"], d["clientWidth"])})
        for k, label in (("truncated", "웹뷰 글자 잘림"), ("unnamed", "웹뷰 이름 없는 조작 요소"), ("overlaps", "웹뷰 글자 겹침"),
                         ("offscreen", "웹뷰 화면 밖 고정 요소")):
            for x in d[k][:15]:
                self.audits.append({"where": "%s (%s)" % (where, d["url"]), "kind": label, "detail": x})


# ------------------------------------------------------------------ 시나리오
def goto_stage(d, k):
    d.step("Ctrl+%d로 %s 단계로 이동" % (k, STAGE_WHERE[k - 1]))
    t = time.time()
    d.key("ctrl+%d" % k)
    ok = d.wait(lambda: d.where().startswith(STAGE_WHERE[k - 1]), "Ctrl+%d → %s" % (k, STAGE_WHERE[k - 1]), since=t)
    d.expect(ok, "Ctrl+%d로 %s 화면이 열리지 않음" % (k, STAGE_WHERE[k - 1]), "머리말 위치: %s" % d.where())
    return ok


def s1_keyboard_stages(d):
    """키보드만으로 ①→⑤ 이동, 뒤로·앞으로."""
    for k in range(1, 6):
        if goto_stage(d, k):
            time.sleep(1.0 if k in (2, 3, 4) else 0.3)
            d.shot("%s 화면" % STAGE_WHERE[k - 1])
            d.audit()
    d.step("Alt+←로 뒤로")
    t = time.time()
    d.key("alt+left")
    d.expect(d.wait(lambda: d.where().startswith("④"), "Alt+← 뒤로", since=t), "Alt+←로 이전 화면(④)에 가지 않음",
             "머리말 위치: %s" % d.where())
    d.step("? 단축키 표 열기")
    t = time.time()
    d.key("f1")
    ok = d.wait(lambda: any(x.startswith("Ctrl+1 ~ Ctrl+") for x in d.texts()), "F1 단축키 표", since=t)
    d.shot("단축키 표")
    d.expect(ok, "F1로 단축키 표가 뜨지 않음")
    d.step("Esc로 닫기", think=False)
    d.key("esc")


def s2_palette_related(d):
    """Ctrl+P로 구성요소 찾기 → 관련 항목 패널 → 다른 화면으로 이동."""
    goto_stage(d, 5)
    d.step("Ctrl+P로 명령 팔레트 열기")
    before = len(d.windows())
    t = time.time()
    d.key("ctrl+p")
    d.expect(d.wait(lambda: len(d.windows()) > before or any(e["aid"].endswith("palette_list") for e in d.tree()),
                    "Ctrl+P 팔레트", since=t), "Ctrl+P로 팔레트가 뜨지 않음")
    d.step("구성요소 'PZR' 입력")
    t = time.time()
    d.type("@PZR")
    items = d.wait(lambda: [e for e in d.tree() if e["type"] == "ListItem" and "palette_list" in e["aid"]],
                   "팔레트 검색 결과", since=t)
    d.shot("팔레트 검색 결과")
    if not d.expect(bool(items), "팔레트에서 '@PZR' 검색 결과가 없음"):
        d.key("esc")
        return
    d.step("Enter로 첫 결과 열기")
    w0 = d.where()
    t = time.time()
    d.key("enter")
    d.wait(lambda: d.where() != w0, "구성요소 열기", since=t)
    time.sleep(1.0)
    d.shot("구성요소 연 화면")
    d.step("관련 항목 패널 확인")
    rel = [e for e in d.tree() if "rel_list" in e["aid"] and e["type"] in ("ListItem", "TreeItem") and e.get("name")
           and not e.get("offscreen")]
    if not rel:
        d.step("Ctrl+Alt+B로 관련 항목 패널 펴기")
        d.key("ctrl+alt+b")
        rel = d.wait(lambda: [e for e in d.tree() if "rel_list" in e["aid"] and e["type"] in ("ListItem", "TreeItem")
                              and e.get("name") and not e.get("offscreen")], "관련 항목 패널", timeout=3)
    d.shot("관련 항목")
    if not d.expect(bool(rel), "구성요소를 연 뒤 관련 항목 패널에 항목이 없음", "위치: %s" % d.where()):
        return
    here = d.where()[:1]
    rel = [e for e in rel if any(m in e["name"] for m in STAGE_WHERE if m != here)]
    if not rel:
        d.inconclusive("관련 항목에 다른 단계로 가는 항목이 보이지 않아 이동은 판정하지 않음", "위치: %s" % d.where())
        return
    d.step("관련 항목 '%s' 클릭으로 이동" % rel[0]["name"][:30])
    w1 = d.where()
    t = time.time()
    d.click(rel[0])
    moved = d.wait(lambda: d.where() != w1, "관련 항목 이동", timeout=4, since=t)
    d.shot("관련 항목으로 이동한 화면")
    d.expect(bool(moved), "관련 항목을 눌러도 다른 화면으로 가지 않음", "위치: %s, 항목: %s" % (d.where(), rel[0]["name"][:40]),
             severity="하")


WORKSHEET_EMPTY = "행렬의 칸을 누르면 구간 × 편차 워크시트가 열립니다."


def open_cell_by_key(d, what):
    """J로 칸을 연다. 안 열리면 결함으로 남기고 행렬 첫 칸을 클릭해 이어 간다."""
    d.step("J로 다음 미검토 칸 열기")
    f = d.uia.q(op="focus")
    focus = "%s '%s'" % (f[0]["type"], (f[0]["name"] or "")[:30]) if f else "없음"
    t = time.time()
    d.key("j")
    if d.wait(lambda: WORKSHEET_EMPTY not in d.texts(), "J 칸 열기", timeout=3, since=t):
        return True
    d.expect(False, "%s J를 눌러도 칸이 열리지 않음" % what, "J를 누르기 전 초점: %s. 화면 단축키는 초점이 ⑤ 화면 안에 "
             "있어야 들음(WidgetWithChildrenShortcut)" % focus)
    matrix = [e for e in d.tree() if e["aid"].endswith(".matrix") and e.get("rect")]
    if not matrix:
        return False
    d.step("행렬 첫 칸 클릭으로 칸 열기")
    d.click(matrix[0], dx=260, dy=55)
    return bool(d.wait(lambda: WORKSHEET_EMPTY not in d.texts(), "클릭 칸 열기", timeout=3))


def worksheet(d):
    """⑤ 워크시트 표(행렬이 아닌 Table)."""
    return [e for e in d.tree() if e["type"] in ("Table", "DataGrid") and not e["aid"].endswith(".matrix")
            and e.get("rect") and not e.get("offscreen")]


def pick_first_row(d):
    """워크시트 첫 행을 클릭해 고른다. A·R·E는 고른 행에만 듣는다(개선명세 U-02)."""
    ws = worksheet(d)
    if not d.expect(bool(ws), "⑤ 워크시트 표를 찾지 못함"):
        return False
    d.step("워크시트 첫 행 클릭")
    d.click(ws[0], dx=120, dy=38)
    time.sleep(0.4)
    return True


def s3_review_keys(d):
    """⑤ 칸 열기 → 승인(A) → 기각(R) → 실행 취소(Ctrl+Z)를 키보드로. 저장 파일의 상태 수로 확인한다."""
    goto_stage(d, 5)
    if not open_cell_by_key(d, "Ctrl+5로 ⑤에 온 직후"):
        return
    d.shot("칸 연 화면")
    c0 = d.entry_counts()
    d.step("행을 고르지 않은 채 A")
    texts0 = set(d.texts())
    d.key("a")
    time.sleep(0.8)
    new = [x for x in set(d.texts()) - texts0 if len(x) > 3]
    d.r["a_without_row"] = {"saved": d.entry_counts() != c0, "new_texts": new[:5]}
    d.shot("행 없이 A 후")
    d.expect(d.entry_counts() != c0 or bool(new), "칸을 연 뒤 행을 고르지 않고 A를 누르면 아무 안내 없이 무시됨",
             "칸을 열면 워크시트 선택이 비워진다. 사용자는 A가 왜 안 듣는지 알 수 없음", severity="하")
    if not pick_first_row(d):
        return
    # 칸을 열면 첫 미검토 항목이 골라져 있어 앞의 A가 이미 승인했을 수 있다. 기각(R) 다음 승인(A)이면 어느 경우든 수가 는다.
    c0 = d.entry_counts()
    d.step("R로 기각")
    t = time.time()
    d.key("r")
    ok = d.wait(lambda: d.entry_counts().get("rejected", 0) > c0.get("rejected", 0), "R 기각 저장", since=t)
    d.shot("R 기각 후")
    d.expect(ok, "R을 눌러도 기각이 저장되지 않음", "상태 수: %s" % d.entry_counts())
    c1 = d.entry_counts()
    d.step("A로 승인")
    t = time.time()
    d.key("a")
    ok = d.wait(lambda: d.entry_counts().get("approved", 0) > c1.get("approved", 0), "A 승인 저장", since=t)
    d.shot("A 승인 후")
    d.expect(ok, "칸을 연 뒤 A를 눌러도 승인이 저장되지 않음", "상태 수: %s" % d.entry_counts())
    c2 = d.entry_counts()
    d.step("Ctrl+Z로 실행 취소")
    t = time.time()
    d.key("ctrl+z")
    ok = d.wait(lambda: d.entry_counts() != c2, "Ctrl+Z 실행 취소 저장", since=t)
    d.shot("Ctrl+Z 후")
    d.expect(ok, "Ctrl+Z로 방금 동작이 되돌려지지 않음", "상태 수: %s → %s" % (c2, d.entry_counts()))


def s4_ime_shortcut(d):
    """한글 입력 상태에서 한 글자 단축키 A가 동작하는지 영문 상태와 비교한다. 한/영 전환은 WM_IME_CONTROL로 한다
    (주입한 VK_HANGUL은 한국어 IME가 받지 않음). 끝나면 영문 상태로 돌린다."""
    goto_stage(d, 5)
    d.step("Ctrl+Shift+E로 탐색기 필터에 초점")
    d.key("ctrl+shift+e")
    time.sleep(0.3)
    d.step("한글 입력 상태로 바꾸고 필터에 a, Space 입력(조합을 끝내야 값에 보임)", think=False)
    d.w32.set_hangul(d.hwnd, True)
    d.key("a")
    d.key("space")
    time.sleep(0.4)
    val = "".join(e.get("value") or "" for e in d.tree() if e["aid"].endswith("explorer_filter"))
    d.r["ime_filter_value"] = val
    d.r["ime_mode_read"] = d.w32.ime_hangul(d.hwnd)
    d.shot("필터에 한글 입력 상태")
    d.key("back")
    d.key("back")
    d.key("esc")
    if "ㅁ" not in val:
        d.w32.set_hangul(d.hwnd, False)
        d.inconclusive("한글 입력 상태를 만들지 못해 판정하지 않음", "필터 값: %r" % val)
        return
    results = {}
    for mode, hangul in (("한글", True), ("영문", False)):
        d.w32.set_hangul(d.hwnd, hangul)
        matrix = [e for e in d.tree() if e["aid"].endswith(".matrix") and e.get("rect")]
        if not d.expect(bool(matrix), "⑤ 행렬을 찾지 못함"):
            break
        d.step("%s 상태: 행렬 칸 클릭 후 A" % mode)
        # 가짜 AI 결과는 SNP-M-102를 지나는 구간(첫 행 S4, 4번째 행)에만 있다. 첫 행을 누르고 ↓로 내려가 Enter로 연다.
        d.click(matrix[0], dx=260 + (100 if hangul else 200), dy=55)
        d.key("down")
        d.key("down")
        d.key("down")
        d.key("enter")
        d.wait(lambda: WORKSHEET_EMPTY not in d.texts(), "%s 상태 칸 열기" % mode, timeout=3)
        if not pick_first_row(d):
            break
        c0 = d.entry_counts()
        t = time.time()
        d.key("a")
        results[mode] = bool(d.wait(lambda: d.entry_counts().get("approved", 0) > c0.get("approved", 0),
                                    "%s 상태 A" % mode, timeout=3, since=t))
        d.shot("%s 상태 A 후" % mode)
        if results[mode]:
            d.key("ctrl+z")
    d.w32.set_hangul(d.hwnd, False)
    d.r["ime"] = results
    if results.get("영문") and not results.get("한글"):
        d.expect(False, "한글 입력 상태에서 한 글자 단축키 A가 듣지 않음(영문 상태에서는 동작)",
                 "사용자는 한글 입력 상태로 일하는 경우가 많음")
    elif not results.get("영문"):
        d.expect(False, "영문 상태에서도 칸을 클릭한 뒤 A 승인이 저장되지 않음", "결과: %s" % results)


PROGRESS_KEYS = ("AI", "호출", "분석 중")


def progress_texts(d):
    """진행 표시로 보이는 글자: ⑤ 진행 글자(progress_label), 상태 줄 메시지, 진행 막대 유무."""
    items = d.tree()
    texts = [e["name"] for e in items if e.get("name") and not e.get("offscreen")
             and any(k in e["name"] for k in PROGRESS_KEYS) and e["type"] == "Text"]
    bars = [e for e in items if e["type"] == "ProgressBar" and not e.get("offscreen")]
    return texts, len(bars)


def running_text(texts):
    """진행 글자 'AI n/m 호출'에서 n < m이면 실행 중."""
    for x in texts:
        m = re.search(r"(\d+)\s*/\s*(\d+)\s*호출", x)
        if m and int(m.group(1)) < int(m.group(2)):
            return True
    return False


def start_failed_rerun(d):
    """명령 팔레트로 '실패 칸 다시 실행'(가짜 AI, 호출마다 지연)을 시작한다. 시작했으면 True."""
    d.step("Ctrl+P에서 '>실패 칸 다시 실행' 실행")
    d.key("ctrl+p")
    time.sleep(0.4)
    d.type(">실패 칸 다시")
    time.sleep(0.5)
    t = time.time()
    d.key("enter")

    def confirm():
        return [e for e in d.tree() if e["type"] == "Window" and e.get("name") == "AI 분석 시작"]
    if d.wait(lambda: confirm() or running_text(progress_texts(d)[0]), "실행 확인 또는 시작", timeout=5, since=t) and confirm():
        d.r["confirm_text"] = [x for x in d.texts() if "시작할까요" in x][:1]
        d.shot("AI 실행 확인 대화상자")
        d.step("확인 대화상자에서 Enter(예)")
        t = time.time()
        d.key("enter")
    ok = d.wait(lambda: running_text(progress_texts(d)[0]), "AI 실행 시작 표시", timeout=5, since=t)
    d.shot("AI 실행 시작")
    return d.expect(bool(ok), "'실패 칸 다시 실행' 뒤 진행 표시가 보이지 않음", "보인 글자: %s" % (progress_texts(d)[0],))


def wait_run_end(d, timeout=90):
    return d.wait(lambda: not running_text(progress_texts(d)[0]), "AI 실행 끝", timeout=timeout)


def s7_progress_visibility(d):
    """오래 걸리는 AI 실행 중 진행 상태가 보이는지: 무엇을 하는지, 경과·남은 시간, 비용, 결과의 실시간 반영."""
    goto_stage(d, 5)
    if not start_failed_rerun(d):
        return
    d.step("손대지 않고 진행 표시를 1초마다 기록", think=False)
    samples, counts = [], []
    end = time.time() + 90
    while time.time() < end:
        texts, bars = progress_texts(d)
        samples.append({"t": round(time.time() - end + 90, 1), "texts": texts, "bars": bars})
        counts.append(d.data_stamp())
        if len(samples) == 3:
            d.shot("실행 중 진행 표시")
        if not running_text(texts) and len(samples) > 2:
            break
        time.sleep(1.0)
    d.r["progress_samples"] = samples
    d.shot("실행 끝")
    shown = " | ".join(sorted({x for s in samples for x in s["texts"] if "호출" in x}))[:300]
    has = lambda pat: any(re.search(pat, x) for s in samples for x in s["texts"] if "호출" in x)  # noqa: E731
    d.expect(has(r"\d+\s*/\s*\d+"), "진행 표시에 몇 번째/전체가 없음", shown, severity="중")
    d.expect(has(r"구간|S\d|편차|칸"), "진행 표시가 지금 무엇(어느 구간·칸)을 하는지 말하지 않음", shown, severity="중")
    d.expect(has(r"\d+\s*(초|분)|\d+:\d\d|경과"), "진행 표시에 경과 시간이 없음", shown, severity="중")
    d.expect(has(r"남은|남음|예상"), "진행 표시에 남은 시간(예상)이 없음", shown, severity="중")
    d.expect(has(r"\$|비용|원"), "진행 중 비용(누적·예상)이 보이지 않음", shown, severity="하")
    changes = sum(1 for a, b in zip(counts, counts[1:]) if a != b)
    d.r["live_saves"] = changes
    d.expect(changes >= 2, "실행 중 결과가 호출마다 저장·반영되지 않음", "결과 파일이 바뀐 횟수 %d(호출 수만큼 기대)" % changes,
             severity="중")


def s8_ops_during_run(d):
    """오래 걸리는 작업 중 조작: 탐색기 구간 클릭, 화면 옮기기, Ctrl+P. 화면 이동·진행 표시·결과가 유지되는지."""
    goto_stage(d, 5)
    c0 = d.entry_counts()
    if not start_failed_rerun(d):
        return
    seg = [e for e in d.tree() if e["type"] == "TreeItem" and "explorer" in e["aid"] and re.match(r"S\d", e.get("name") or "")
           and not e.get("offscreen")]
    if d.expect(bool(seg), "탐색기에서 검토구간 Sx 항목을 찾지 못함"):
        d.step("실행 중 탐색기의 '%s' 클릭" % seg[0]["name"][:20])
        w0 = d.where()
        d.click(seg[0])
        time.sleep(0.8)
        d.shot("탐색기 구간 클릭 후")
        d.expect(d.where()[:1] == w0[:1], "⑤에서 탐색기의 구간(Sx)을 누르면 다른 단계(%s)로 넘어감" % d.where()[:1],
                 "누르기 전 %s → 누른 뒤 %s. 사용자는 ⑤의 그 구간 행을 기대(사용자 보고)" % (w0, d.where()))
        if not d.where().startswith("⑤"):
            goto_stage(d, 5)
    d.expect(any("호출" in x for x in progress_texts(d)[0]), "실행 중 다른 조작 뒤 ⑤ 진행 표시가 사라짐",
             "보인 글자: %s" % (progress_texts(d)[0],))
    d.step("실행 중 Ctrl+P로 '@PZR' 찾고 Esc")
    d.key("ctrl+p")
    time.sleep(0.4)
    d.type("@PZR")
    time.sleep(0.5)
    d.shot("실행 중 팔레트")
    d.key("esc")
    d.step("실행 중 ④로 갔다가 ⑤로 돌아오기")
    goto_stage(d, 4)
    time.sleep(0.5)
    goto_stage(d, 5)
    time.sleep(0.5)
    d.shot("④ 갔다 온 ⑤")
    running = running_text(progress_texts(d)[0])
    d.r["progress_after_return"] = running
    if not running:  # 표시가 없는데 결과 파일이 계속 바뀌면 실행 중인데 표시만 사라진 것
        st = d.data_stamp()
        still = d.wait(lambda: d.data_stamp() != st, "표시 없이 계속 저장되는지", timeout=AI_DELAY * 2)
        d.expect(not still, "화면을 옮겼다 돌아오면 실행이 계속되는데 ⑤ 진행 표시가 사라짐", "돌아온 뒤에도 결과 파일이 저장됨")
    done = wait_run_end(d)
    d.shot("실행 끝")
    d.expect(bool(done), "가짜 AI 실행이 90초 안에 끝나지 않음")
    c1 = d.entry_counts()
    d.expect(sum(c1.values()) >= sum(c0.values()), "실행 중 조작 뒤 결과 항목이 줄어듦",
             "전 %s → 후 %s" % (c0, c1), severity="상")


SEL_JS = r"""(() => {
  const segs = [...document.querySelectorAll('[data-hz-seg]')].filter(e => e.getAttribute('data-hz-seg') !== 'uncovered');
  const labels = [...new Set(segs.map(e => e.getAttribute('data-hz-seg')))];
  const others = [...document.querySelectorAll('#overlay .sym, #overlay .pipe-line, #overlay .tagbox')]
    .filter(e => !e.classList.contains('hz-seg-in'));
  const op = e => parseFloat(getComputedStyle(e).opacity);
  return {focused: document.body.classList.contains('hz-segfocus'), labels: labels, painted: segs.length,
          colored_others: others.filter(e => e.getAttribute('data-hz-seg') && op(e) > 0.6).length,
          bright_others: others.filter(e => op(e) > 0.6).length, others: others.length};
})()"""  # ④ 구간 색(hazop/app/webview.py segments()): 구간 색은 data-hz-seg, 고른 구간 요소는 hz-seg-in, 나머지는 흐림


def s9_selection_feedback(d):
    """④에서 구간 하나를 고르면 그 구간 구성요소만 색이 남고 다른 구간·요소는 흐려지는지(CDP로 도면 요소를 센다).
    도면 원본 SVG의 인라인 stroke는 세지 않는다(앞 판은 이것까지 세어 '고르지 않은 구간 색칠 74'로 잘못 판정)."""
    goto_stage(d, 4)
    time.sleep(1.0)
    rows = [e for e in d.tree() if e["type"] == "ListItem" and "SegList" in e["aid"] and not e["offscreen"]]
    if not d.expect(len(rows) >= 2, "④ 구간 목록을 읽지 못함"):
        return
    seen = []
    for row in rows[:2]:
        d.step("구간 '%s' 클릭" % row["name"][:24])
        d.click(row, dx=60)
        time.sleep(0.8)
        m = d.cdp.evaluate(SEL_JS) or {}
        seen.append(m)
        d.shot("구간 선택 후")
        detail = ("색 구간 %s · 색칠 요소 %d · 고른 구간 밖인데 색이 남은 요소 %d · 흐리지 않은 구간 밖 요소 %d/%d"
                  % (m.get("labels"), m.get("painted", 0), m.get("colored_others", 0), m.get("bright_others", 0),
                     m.get("others", 0)))
        if not d.expect(m.get("focused") and m.get("painted", 0) > 0, "④에서 구간을 골라도 도면에서 그 구간만 강조되지 않음",
                        detail):
            continue
        d.expect(len(m.get("labels") or []) == 1 and not m.get("colored_others") and not m.get("bright_others"),
                 "④에서 구간 하나를 골라도 다른 구간 요소가 색이 남거나 흐려지지 않음(사용자 보고)", detail)
    d.r["selection"] = seen


def s11_cross_drawing_node(d):
    """도면을 넘는 구간: ④에서 ⇄ 구간을 고르면 범위·경계·수가 보이고, 연결점 칩으로 상대 도면에 가도 같은 구간이 고른 채로
    열리며, ⑤ 행 이름에도 도면 범위가 있는지."""
    goto_stage(d, 4)
    time.sleep(1.0)

    def rows():
        return [e for e in d.tree() if e["type"] == "ListItem" and "SegList" in e["aid"] and not e["offscreen"]]
    span_rows = [e for e in rows() if "⇄" in (e["name"] or "")]
    if not d.expect(bool(span_rows), "④ 이 도면 구간 목록에 여러 도면에 걸친 구간(⇄)이 없음",
                    "목록: %s" % [e["name"][:30] for e in rows()]):
        return
    row = span_rows[0]
    node_id = (row["name"] or "").split()[0]
    d.step("⇄ 구간 '%s' 클릭" % row["name"][:30])
    d.click(row, dx=60)
    time.sleep(0.8)
    d.shot("⇄ 구간 선택")
    texts = d.texts()
    rng = re.search(r"\[(\d+(?: → \d+)+)\]", row["name"] or "")
    d.expect(bool(rng), "⇄ 구간 이름에 도면 범위 [101 → 102]가 없음", row["name"])
    d.expect(any("시작:" in t and "끝:" in t for t in texts), "고른 구간의 경계(시작·끝)가 보이지 않음")
    d.expect(any(re.search(r"이 도면 \d+ / 전체 \d+", t) for t in texts), "고른 구간의 '이 도면 N / 전체 M'이 보이지 않음")
    d.expect(any("프로젝트" in t and "이 도면" in t and "%" in t for t in texts), "덮음률이 '프로젝트 · 이 도면' 둘 다 보이지 않음")
    web = d.cdp.evaluate("[...document.querySelectorAll('.hz-chip')].map(e => e.textContent)") or []
    d.expect(any("에서 계속" in t for t in web), "④ 도면의 연결점 옆에 '… 에서 계속' 칩이 없음", "도면 칩: %s" % web[:5])
    chips = [e for e in d.tree() if e["type"] == "Button" and "에서 계속" in (e["name"] or "") and not e["offscreen"]]
    if not d.expect(bool(chips), "④ 패널에 연결점 칩 버튼이 없음"):
        return
    target = re.search(r"→ (\S+)에서 계속", chips[0]["name"]).group(1)
    d.step("칩 '%s' 클릭" % chips[0]["name"])
    t = time.time()
    d.click(chips[0])
    moved = d.wait(lambda: target in d.where(), "칩 → 상대 도면", timeout=10, since=t)
    time.sleep(1.0)
    d.shot("칩으로 상대 도면")
    d.expect(bool(moved), "칩을 눌러도 상대 도면 %s로 가지 않음" % target, "머리말: %s" % d.where())
    m = d.cdp.evaluate(SEL_JS) or {}
    d.expect(m.get("focused") and m.get("labels") == [node_id], "상대 도면에서 같은 구간 %s가 고른 채로 열리지 않음" % node_id,
             "도면 색 구간 %s" % m.get("labels"))
    if goto_stage(d, 5):
        time.sleep(1.0)
        d.shot("⑤ 행렬")
        names = [x for x in d.texts() if x.startswith(node_id + " ")]
        d.expect(any(rng and rng.group(1) in x for x in names), "⑤ 행 이름에 도면 범위가 없음", "행: %s" % names[:3])
    d.r["cross_drawing"] = {"node": node_id, "target": target}


def explorer_view(d):
    """(머리 단계 글자, 보이는 탐색기 줄 이름)."""
    tree = d.tree()
    title = next((e["name"] for e in tree if e["aid"].endswith("explorer_title")), "")
    names = [e["name"] for e in tree if e["type"] == "TreeItem" and "explorer" in e["aid"] and not e.get("offscreen")]
    return title, names


def s10_explorer_structure(d):
    """⑤ 탐색기가 결과를 찾을 곳을 보이는지: 구간별 분석 묶음과 그 수, 권고 묶음."""
    goto_stage(d, 5)
    time.sleep(0.5)
    _title, names = explorer_view(d)
    d.r["explorer"] = names
    d.shot("⑤ 탐색기")
    groups = {n: int(names[i + 1]) for i, n in enumerate(names[:-1])
              if (n == "권고" or n.startswith("구간별 분석")) and re.fullmatch(r"\d+", names[i + 1] or "")}
    d.r["explorer_groups"] = groups
    d.expect(any(k.startswith("구간별 분석") and v > 0 for k, v in groups.items()),
             "⑤ 탐색기에 구간별 분석 진행이 없음(사용자 질문: 결과는 어디?)", "묶음: %s" % groups, severity="하")


# 단계별 탐색기 모듈(hazop/app/explorer.py)의 묶음 이름. 앞부분이 같으면 그 묶음이다(검토구간 · SNP-SAMPLE)
STAGE_GROUPS = {1: ("도면", "문서", "등록 없이 추출"), 2: ("도면 추출", "미추출"), 3: ("지식그래프", "요약"),
                4: ("검토구간",), 5: ("구간별 분석", "권고")}


def s14_stage_explorer(d):
    """레일 단계마다 탐색기 내용이 바뀌는지: 머리에 그 단계, 그 단계 묶음만, 다른 단계 묶음 없음."""
    seen = {}
    for k in range(1, 6):
        if not goto_stage(d, k):
            continue
        time.sleep(1.0 if k in (2, 3, 4) else 0.4)
        title, names = explorer_view(d)
        def group_of(n):
            return next((st for st, gs in STAGE_GROUPS.items() for g in gs if n == g or n.startswith(g + " · ")), None)
        present = {n: group_of(n) for n in names if group_of(n)}
        seen[k] = {"title": title, "groups": sorted(present)}
        d.shot("%s 탐색기" % STAGE_WHERE[k - 1])
        d.expect(title.startswith("①②③④⑤"[k - 1]), "탐색기 머리에 지금 단계가 없음", "단계 %d, 머리: %r" % (k, title))
        d.expect(any(st == k for st in present.values()), "%s 탐색기에 그 단계 묶음이 없음" % STAGE_WHERE[k - 1],
                 "줄: %s" % names[:12])
        other = sorted(n for n, st in present.items() if st != k)
        d.expect(not other, "%s 탐색기에 다른 단계 묶음이 보임" % STAGE_WHERE[k - 1], "다른 단계 묶음: %s" % other)
    d.r["stage_explorer"] = seen


def s13_kg_graph(d):
    """③ 지식그래프(옵시디언식): 검색어 입력 → 캔버스 강조, 노드에 마우스 올림 → 이웃 강조, 클릭 → 선택, 로컬 그래프.
    입력은 실제 키보드·마우스. 판정은 페이지 상태(hzKG.state)로 한다."""
    if not goto_stage(d, 3):
        return
    if not d.expect(d.wait(lambda: d.cdp.evaluate("!!(window.hzKG && hzKG.ready)") is True, "③ 그래프 준비", 30),
                    "③ 그래프가 준비되지 않음"):
        return
    time.sleep(3.0)  # 힘 배치가 멈출 때까지
    st = lambda: d.cdp.evaluate("hzKG.state()") or {}
    box = [e for e in d.tree() if e["type"] == "Edit" and e["name"] == "태그·이름으로 찾기" and not e["offscreen"]]
    if not d.expect(box, "③ 검색 상자('태그·이름으로 찾기')를 UIA에서 찾지 못함"):
        return
    d.step("검색 상자 클릭 후 'RC-P' 입력")
    d.click(box[0])
    d.w32.set_hangul(d.hwnd, False)
    d.type("RC-P")
    ok = d.wait(lambda: st().get("matches", 0) > 0, "검색 → 캔버스 강조")
    d.shot("검색 강조")
    d.expect(ok, "검색어를 넣어도 캔버스에서 맞는 노드가 강조되지 않음", "matches=%s" % st().get("matches"))
    d.step("Ctrl+A, Backspace로 검색어 지움")
    d.key("ctrl+a")
    d.key("back")
    d.expect(d.wait(lambda: st().get("matches") == 0, "검색 지움 → 강조 해제"), "검색어를 지워도 강조가 남음")
    hub = d.cdp.evaluate("""(function(){var b=null,m=-1;hzKG.visibleIds().forEach(function(i){
        var k=hzKG.bfs(i,1).length;if(k>m){m=k;b=i;}});return b;})()""")
    css = d.cdp.evaluate("(function(){var r=document.getElementById('q').getBoundingClientRect();"
                         "var p=hzKG.pageOf(%s);return p&&{qx:r.left,qy:r.top,x:p.x,y:p.y,dpr:devicePixelRatio};})()"
                         % json.dumps(hub))
    if not d.expect(css, "③ 노드 화면 좌표를 얻지 못함", "hub=%s" % hub):
        return
    bx, by = box[0]["rect"][0], box[0]["rect"][1]
    sx, sy = bx + (css["x"] - css["qx"]) * css["dpr"], by + (css["y"] - css["qy"]) * css["dpr"]
    far = d.cdp.evaluate("(function(h){var nb=hzKG.bfs(h,1),c=hzKG.pageOf(h),b=null,m=-1;hzKG.visibleIds().forEach("
                         "function(i){var p=hzKG.pageOf(i);if(nb.indexOf(i)>=0||!p)return;var e=Math.hypot(p.x-c.x,p.y-c.y);"
                         "if(e>m){m=e;b=i;}});return b;})(%s)" % json.dumps(hub))  # 라벨에 가리지 않게 가장 먼 비이웃
    # 이웃이 아닌 노드 중심의 불투명도(3×3 최댓값). 캔버스 바탕은 투명이라 흐려지면 줄어든다.
    ink = lambda: d.cdp.evaluate("(function(id){var c=document.querySelector('#graph canvas'),r=c.getBoundingClientRect(),"
                                 "p=hzKG.pageOf(id),k=c.width/r.width,x=Math.round((p.x-r.left)*k),y=Math.round((p.y-r.top)*k),"
                                 "a=c.getContext('2d').getImageData(x-1,y-1,3,3).data,m=0;for(var i=3;i<a.length;i+=4)"
                                 "m=Math.max(m,a[i]);return m;})(%s)" % json.dumps(far)) or 0
    ink0 = ink()
    d.step("가장 연결이 많은 노드(%s) 위에 마우스 올림" % hub)
    d._guard()
    if not d.ours(d.w32.pid_at(sx, sy)):
        raise Abort("마우스를 올릴 자리(%d,%d) 아래 창이 이 실행의 앱이 아님" % (sx, sy))
    for k in (3, 0):
        d.w32.u.SetCursorPos(int(sx) + k, int(sy) + k)
        time.sleep(0.2)
    ok = d.wait(lambda: st().get("hover") == hub and ink() < ink0 * 0.6, "마우스 올림 → 이웃 강조(캔버스 다시 그림)")
    d.shot("마우스 올림")
    d.expect(ok, "노드에 마우스를 올려도 캔버스에서 나머지가 흐려지지 않음",
             "hover=%s · 이웃 아닌 노드 %s의 불투명도 %s → %s" % (st().get("hover"), far, ink0, ink()))
    d.step("그 노드 클릭")
    d.click({"rect": [int(sx) - 1, int(sy) - 1, 2, 2]})
    sel = d.wait(lambda: (st().get("sel") or {}).get("id") == hub, "클릭 → 선택")
    d.expect(sel, "노드를 클릭해도 선택되지 않음", "sel=%s" % st().get("sel"))
    local = [e for e in d.tree() if e["type"] == "Button" and e["name"] == "로컬" and not e["offscreen"]]
    if not d.expect(local, "③ '로컬' 버튼을 찾지 못함"):
        return
    d.step("'로컬' 버튼 클릭")
    d.click(local[0])
    s = d.wait(lambda: (lambda v: v if v.get("mode") == "local" else None)(st()), "로컬 그래프")
    time.sleep(1.5)
    d.shot("로컬 그래프")
    d.expect(s and s.get("center") == hub and 0 < s.get("visible", 0) < s.get("nodes", 0),
             "로컬 그래프가 선택 노드를 중심으로 일부 노드만 보이지 않음", str({k: (s or {}).get(k) for k in ("center", "visible", "nodes")}))
    d.expect(not st().get("errors"), "③ 페이지 JS 오류", str(st().get("errors")))
    d.audit()


def s5_register_drawio(d):
    """drawio 등록 → 추출 → ② 도면 확인."""
    goto_stage(d, 1)
    d.step("'파일 선택…' 누르기")
    btn = d.find(lambda e: e["type"] == "Button" and e["name"] == "파일 선택…" and not e["offscreen"])
    if not d.expect(bool(btn), "① 빈 상태에 '파일 선택…' 버튼이 없음"):
        return
    def dialog():  # 파일 대화상자는 주 창이 소유한 창이라 UIA에서 주 창 아래에 있다
        return [e for e in d.tree() if e["type"] == "Window" and (e["cls"] == "#32770" or "선택" in (e.get("name") or ""))]
    d.click(btn[0])
    dlg = d.wait(dialog, "파일 대화상자", timeout=8)
    d.shot("파일 대화상자")
    if not d.expect(bool(dlg), "파일 선택 대화상자가 뜨지 않음"):
        return
    d.step("파일 이름 칸에 경로 입력하고 Enter")
    time.sleep(0.5)
    d.type(DRAWIO_SAMPLE)
    d.key("enter")
    d.wait(lambda: not dialog(), "대화상자 닫힘", timeout=5)
    time.sleep(0.5)
    d.shot("파일 고른 뒤")
    d.step("'등록' 누르기")
    reg = d.find(lambda e: e["type"] == "Button" and e["name"] == "등록" and e["enabled"] and not e["offscreen"])
    if not d.expect(bool(reg), "파일을 고른 뒤 '등록' 버튼이 켜지지 않음"):
        return
    t = time.time()
    d.click(reg[0])
    ext = d.wait(lambda: d.find(lambda e: e["type"] == "Button" and e["name"] == "추출·그래프 만들기" and e["enabled"]),
                 "등록 완료", timeout=20, since=t)
    d.shot("등록 후")
    if not d.expect(bool(ext), "등록 뒤 '추출·그래프 만들기'가 켜지지 않음"):
        return
    graphs = paths.output_in(os.path.dirname(os.path.dirname(d.data_root)), "그래프")

    def graph_dirs():
        return set(os.listdir(graphs)) if os.path.isdir(graphs) else set()
    g0 = graph_dirs()
    d.step("'추출·그래프 만들기' 누르기")
    t = time.time()
    d.click(ext[0])
    def new_graph():
        return [g for g in graph_dirs() - g0
                if any(f.endswith(".json") for f in os.listdir(os.path.join(graphs, g)))]
    done = d.wait(new_graph, "추출·그래프 완료(출력/그래프에 새 그래프 파일)", timeout=60, since=t)
    time.sleep(2.0)
    d.shot("추출 후")
    d.expect(bool(done), "추출·그래프 만들기가 60초 안에 끝나지 않음")
    if not d.where().startswith("②"):
        goto_stage(d, 2)
    ok = d.wait(lambda: (d.cdp.evaluate("document.querySelectorAll('svg *').length") or 0) > 50, "② 도면 그림", timeout=15)
    time.sleep(0.8)
    d.shot("② 도면")
    title = d.cdp.evaluate("(document.getElementById('dwg') || document.body).textContent.slice(0, 200)") or ""
    # 등록 때 도면 번호를 넣지 않으면 머리말에 번호가 없다. 새로 생긴 추출 이름(② 도면 고르기 값)으로도 판정한다.
    combo = [e["name"] for e in d.tree() if e["type"] == "ComboBox" and "viewer" in e["aid"].lower()]
    shown = title + d.where() + " ".join(combo) + " ".join(x for x in d.texts() if x in (done or []))
    d.expect(bool(ok) and ("SNP-M-201" in shown or any(g in shown for g in (done or []))),
             "추출을 마치고 ②로 가도 방금 만든 SNP-M-201이 아니라 이전 도면이 열려 있음",
             "위치: %s. 새 추출 %s. 사용자가 ② 도면 목록에서 새 도면을 직접 골라야 함" % (d.where(), done))


def s6_merge_confirm(d):
    """④ 구간 확정 해제 → 두 구간 병합(M) → 확정(Ctrl+Enter)."""
    goto_stage(d, 4)
    time.sleep(0.5)

    def nodes():
        return [e for e in d.tree() if e["type"] == "ListItem" and "SegList" in e["aid"] and not e["offscreen"]]
    n0 = nodes()
    d.shot("④ 처음")
    if not d.expect(len(n0) >= 2, "④ 구간 목록을 UIA로 읽지 못함(%d개)" % len(n0)):
        return
    d.step("Ctrl+P에서 '>확정 해제' 실행")
    d.key("ctrl+p")
    time.sleep(0.4)
    d.type(">확정 해제")
    time.sleep(0.4)
    before = len(d.windows())
    d.key("enter")
    time.sleep(0.8)
    if len(d.windows()) > before - 1 and len(d.windows()) > 1:
        d.shot("확정 해제 확인 대화상자")
        d.step("대화상자에서 Enter", think=False)
        d.key("enter")
        time.sleep(0.5)
    d.step("첫 구간 클릭, Space로 체크, ↓, Space로 둘째 구간 체크")
    d.click(nodes()[0])
    d.key("space")
    d.key("down")
    d.key("space")
    d.step("M으로 병합")
    t = time.time()
    d.key("m")
    merged = d.wait(lambda: len(nodes()) < len(n0), "M 병합", timeout=5, since=t)
    d.shot("M 병합 후")
    d.expect(bool(merged), "두 구간을 고르고 M을 눌러도 병합되지 않음", "구간 수 %d → %d" % (len(n0), len(nodes())))
    d.step("Ctrl+Enter로 구간 확정")
    before = len(d.windows())
    t = time.time()
    d.key("ctrl+enter")
    time.sleep(0.8)
    if len(d.windows()) > before:
        d.shot("확정 확인 대화상자")
        d.key("enter")
    ok = d.wait(lambda: any("확정" in x and ("했" in x or "됨" in x) for x in d.texts()), "구간 확정", timeout=5, since=t)
    d.shot("확정 후")
    d.expect(bool(ok), "Ctrl+Enter 뒤 확정 표시가 보이지 않음")


def s12_excel_export(d):
    """⑤ Ctrl+P '>Excel' → 범위 대화상자 Enter(전체) → 저장 대화상자에 경로 입력 → 파일·토스트 [열기]·[폴더 열기] 확인.
    파일은 openpyxl로 다시 읽어 시나리오 행 수가 저장된 결과의 항목 수와 같은지 본다. [열기]는 누르지 않는다(Excel 실행)."""
    import openpyxl
    goto_stage(d, 5)
    out = os.path.join(os.path.dirname(os.path.dirname(d.data_root)), "내보내기", "S12-export.xlsx")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    d.step("Ctrl+P에서 '>Excel' 실행")
    d.key("ctrl+p")
    time.sleep(0.4)
    d.type(">Excel")
    time.sleep(0.4)
    t = time.time()
    d.key("enter")
    dlg = d.wait(lambda: d.find(lambda e: e["type"] == "Window" and e.get("name") == "Excel로 내보내기"),
                 "범위 대화상자", timeout=5, since=t)
    d.shot("범위 대화상자")
    if not d.expect(bool(dlg), "Ctrl+P '>Excel'로 내보내기 대화상자가 뜨지 않음"):
        return
    d.step("범위 '전체' 그대로 Enter(저장 위치 고르기)")
    t = time.time()
    d.key("enter")

    def save_dialog():
        return [e for e in d.tree() if e["type"] == "Window" and e["cls"] == "#32770"]
    sd = d.wait(save_dialog, "저장 대화상자", timeout=8, since=t)
    d.shot("저장 대화상자")
    if not d.expect(bool(sd), "범위를 고른 뒤 저장 대화상자가 뜨지 않음"):
        return
    time.sleep(0.5)
    f = d.uia.q(op="focus")  # 파일 목록이 길면 tree 상한(1500)에 걸려 파일 이름 칸이 빠지므로 초점 칸을 읽는다
    value = (f[0].get("value") or "") if f else ""
    if not value:
        d.inconclusive("저장 대화상자 파일 이름 칸 값을 UIA로 읽지 못해 기본 이름은 스크린샷으로만 확인")
    else:
        d.expect(value.startswith("HAZOP-") and value.endswith(".xlsx"),
                 "저장 대화상자 파일 이름 칸에 기본 이름(HAZOP-…xlsx)이 없음", "초점 칸 값: %r" % value, severity="하")
    d.step("파일 이름 칸에 경로 입력하고 Enter")
    time.sleep(0.5)
    d.key("ctrl+a")
    d.type(out)
    t = time.time()
    d.key("enter")
    saved = d.wait(lambda: os.path.isfile(out), "파일 저장", timeout=10, since=t)
    toast = d.wait(lambda: d.find(lambda e: e["type"] == "Button" and e.get("name") == "폴더 열기"
                                  and not e["offscreen"]), "토스트 [폴더 열기]", timeout=5, since=t)
    d.shot("내보낸 뒤 토스트")
    if not d.expect(bool(saved), "저장 대화상자에서 Enter 뒤 xlsx 파일이 생기지 않음", out):
        return
    d.expect(bool(toast) and any("Excel로 내보냄" in x for x in d.texts())
             and d.find(lambda e: e["type"] == "Button" and e.get("name") == "열기"),
             "내보낸 뒤 토스트에 '열기'·'폴더 열기'가 보이지 않음", severity="중")
    entries = 0
    for root, _dirs, files in os.walk(d.data_root):
        for f in files:
            if f.endswith(".json") and ".bak." not in f:
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    doc = json.load(fh)
                if isinstance(doc, dict) and doc.get("kind") == "hazop_study_results":
                    entries += sum(len(c["entries"]) for c in doc["cells"])
    ws = openpyxl.load_workbook(out)["워크시트"]
    head = [c.value for c in ws[1]]
    status = [row[head.index("상태")] for row in ws.iter_rows(min_row=2, values_only=True)]
    rows = sum(1 for x in status if x and x.split(" · ")[0] in ("제안", "수정", "승인", "기각"))
    dn = [row[head.index("도면 번호")] for row in ws.iter_rows(min_row=2, values_only=True)]
    d.expect(rows == entries and entries > 0 and all(dn), "내보낸 워크시트 시나리오 행 수가 저장된 결과와 다르거나 도면 번호가 빔",
             "워크시트 %d행, 결과 항목 %d개, 도면 번호 빈 행 %d" % (rows, entries, sum(1 for x in dn if not x)))


def _inside(e, rect):
    x, y, w, h = e.get("rect") or (0, 0, 0, 0)
    return rect[0] <= x and rect[1] <= y and x + w <= rect[0] + rect[2] and y + h <= rect[1] + rect[3]


def window_named(d, name):
    return [e for e in d.tree() if e["type"] == "Window" and e.get("name") == name]


def window_texts(d, win):
    return [e["name"] for e in d.tree() if e.get("name") and e is not win and _inside(e, win["rect"])]


def s15_subscription_cancel_close(d):
    """연결 방식을 Claude 구독으로 바꾸고 가짜 CLI로 ⑤ 실행 → 실행 중 취소 → 창 닫기(기다렸다 닫기).
    구독 화면에 $가 없는지, 진행 중 호출이 있을 때 묻는지, 받은 칸을 저장하고 닫히는지 본다. 앱을 닫으므로 맨 마지막에 돈다."""
    goto_stage(d, 5)
    d.step("Ctrl+P에서 '>AI 연결 설정' 실행")
    d.key("ctrl+p")
    time.sleep(0.4)
    d.type(">AI 연결 설정")
    time.sleep(0.5)
    d.key("enter")
    if not d.expect(bool(d.wait(lambda: window_named(d, "AI 연결 설정"), "설정 창", 5)), "AI 연결 설정 창이 열리지 않음"):
        return
    d.shot("AI 연결 설정")
    item = d.find(lambda e: e["type"] == "ListItem" and (e.get("name") or "").startswith("Claude 구독"))
    if not d.expect(bool(item), "설정 창 목록에 Claude 구독이 없음"):
        return
    d.step("목록에서 Claude 구독 클릭")
    d.click(item[0])
    d.step("Alt+U(이 방식으로 사용)")
    d.key("alt+u")
    if d.wait(lambda: window_named(d, "Claude 구독으로 분석하기 전에"), "이용 조건 창", 5):
        d.shot("구독 처음 사용(이용 조건)")
        d.step("Space(확인란) → Alt+O(확인하고 계속)")
        d.key("space")
        d.key("alt+o")
    chip = d.wait(lambda: d.find(lambda e: (e.get("name") or "").startswith("AI 연결: Claude 구독")), "칩이 구독으로", 15)
    d.expect(bool(chip), "구독으로 바꿨는데 연결 칩이 'AI 연결: Claude 구독…'이 아님")
    d.r["chip"] = chip[0]["name"] if chip else None
    d.shot("구독으로 바꾼 뒤")
    d.step("Esc로 설정 창 닫기")
    d.key("esc")
    time.sleep(0.5)
    d.step("Ctrl+P에서 '>AI 일괄 분석' 실행")
    d.key("ctrl+p")
    time.sleep(0.4)
    d.type(">AI 일괄 분석")
    time.sleep(0.5)
    t = time.time()
    d.key("enter")
    confirm = d.wait(lambda: window_named(d, "AI 분석 시작"), "실행 확인", 15, since=t)
    if not d.expect(bool(confirm), "구독 실행 확인 창이 뜨지 않음"):
        return
    texts = window_texts(d, confirm[0])
    d.r["confirm_text"] = texts
    d.shot("구독 실행 확인")
    d.expect(any("건별 요금 없음" in x for x in texts), "구독 실행 확인에 '건별 요금 없음'이 없음", " | ".join(texts)[:300])
    d.expect(not any("$" in x for x in texts), "구독 실행 확인에 $가 보임", " | ".join(texts)[:300], severity="상")
    d.step("Enter(시작)")
    t = time.time()
    d.key("enter")
    if not d.expect(bool(d.wait(lambda: running_text(progress_texts(d)[0]), "실행 시작", 15, since=t)),
                    "구독 실행이 시작되지 않음"):
        return
    time.sleep(1.0)
    shown = progress_texts(d)[0]
    d.r["progress"] = shown
    d.shot("구독 실행 중")
    d.expect(any("구독 사용량 차감" in x for x in shown), "구독 진행 줄에 '구독 사용량 차감'이 없음", " | ".join(shown)[:300])
    d.expect(not any("$" in x for x in shown), "구독 진행 줄에 $가 보임", " | ".join(shown)[:300], severity="상")
    cancel = d.find(lambda e: e["type"] == "Button" and e.get("name") == "취소" and _inside(e, d.windows()[0]["rect"]))
    if not d.expect(bool(cancel), "실행 중 '취소' 단추가 없음"):
        return
    d.step("'취소' 클릭(남은 호출 멈춤, 진행 중 1건은 받음)")
    d.click(cancel[0])
    d.expect(bool(d.wait(lambda: d.find(lambda e: e["type"] == "Button" and e.get("name") == "바로 끊기"), "바로 끊기", 5)),
             "취소한 뒤 '바로 끊기' 단추가 보이지 않음", severity="하")
    d.shot("취소 뒤(진행 중 1건 기다림)")
    d.step("Alt+F4로 창 닫기")
    t = time.time()
    d.key("alt+f4")
    ask = d.wait(lambda: window_named(d, "AI 분석 중에 닫기"), "닫기 물음", 5, since=t)
    if not d.expect(bool(ask), "진행 중인 호출이 있는데 창을 닫을 때 묻지 않음", severity="상"):
        return
    d.r["close_text"] = window_texts(d, ask[0])
    d.shot("창 닫기 물음")
    d.step("Enter(기다렸다 닫기, 기본 단추)")
    d.key("enter")
    gone = d.wait(lambda: not d.windows(), "창이 닫힘", 60)
    d.expect(bool(gone), "기다렸다 닫기를 골랐는데 호출이 끝난 뒤에도 창이 닫히지 않음", severity="상")
    vias = []
    for root, _dirs, files in os.walk(d.data_root):
        for f in files:
            if f.endswith(".json") and ".bak." not in f:
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    vias += [r.get("via") for r in json.load(fh).get("ai_log") or []]
    d.r["saved_vias"] = vias
    d.expect("subscription" in vias, "구독으로 받은 칸이 결과 파일에 저장되지 않음", "기록된 연결 방식: %s" % vias, severity="상")


SCENARIOS = (("S1", "키보드만으로 ①→⑤ 이동·뒤로·단축키 표", s1_keyboard_stages),
             ("S2", "Ctrl+P 구성요소 찾기 → 관련 항목 → 이동", s2_palette_related),
             ("S3", "⑤ J·A·R·Ctrl+Z 검토 키", s3_review_keys),
             ("S4", "한글 IME 상태의 한 글자 단축키", s4_ime_shortcut),
             ("S7", "오래 걸리는 AI 실행의 진행 표시(무엇·경과·남은 시간·비용·실시간 반영)", s7_progress_visibility),
             ("S8", "AI 실행 중 조작(탐색기 구간·Ctrl+P·화면 이동)", s8_ops_during_run),
             ("S9", "④ 구간 선택 때 그 구간만 강조", s9_selection_feedback),
             ("S10", "⑤ 탐색기 결과 위치(구간별 분석·권고)", s10_explorer_structure),
             ("S14", "단계마다 탐색기 내용이 바뀌는지(①~⑤ 모듈)", s14_stage_explorer),
             ("S11", "도면을 넘는 구간: ④ ⇄ 구간·경계·칩으로 상대 도면 이동·⑤ 행 이름", s11_cross_drawing_node),
             ("S12", "⑤에서 Excel 내보내기(Ctrl+P → 범위 → 저장 대화상자 → 토스트)", s12_excel_export),
             ("S13", "③ 그래프 검색 강조·마우스 올림·클릭 선택·로컬 그래프", s13_kg_graph),
             ("S5", "drawio 등록 → 추출 → ② 확인", s5_register_drawio),
             ("S6", "④ 확정 해제 → 병합(M) → 확정(Ctrl+Enter)", s6_merge_confirm),
             ("S15", "연결 방식 구독으로 바꾸기 → 가짜 CLI 실행 → 실행 중 취소 → 창 닫기(기다림)",
              s15_subscription_cancel_close))  # 앱을 닫으므로 맨 마지막


# ------------------------------------------------------------------ 준비·실행
def prepare(work_root):
    """오프스크린 앱으로 샘플 도면과 가짜 AI 결과를 만든다(네트워크 없음). 별도 프로세스에서 부른다."""
    sys.path.insert(0, REPO_ROOT)
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import shoot_results
    shoot_results.prepare(work_root)
    # ②④ 뷰어 바탕 그림: 샘플 도면 사본을 기록 경로 자리에 둔다
    shutil.copytree(paths.folder("참고", "pid-samples"), paths.logical_dir(work_root, "참고", "pid-samples"))
    from hazop.app import make_application
    from hazop.app.main_window import MainWindow
    from hazop.app.screenshots import wait
    app = make_application(["prepare"])
    win = MainWindow(settings_path=os.path.join(os.path.dirname(work_root), "settings.json"), ask_reviewer=False)
    win.api_keys.set(shoot_results.KEY, persist=False)
    win.ai_prefs.choose("api")  # 준비는 가짜 API 클라이언트로(구독 확인·이용 조건 창을 띄우지 않음)
    win.go(6)
    res = win.screens[6]
    res.make_client = lambda: shoot_results.FakeClient()
    for nid in shoot_results.drawing_node_ids():
        res.matrix.setCurrentCell(res._row_of(nid), 0)
        res.run_ai("node")
        if not wait(lambda: not res.running(), 180):
            raise SystemExit("가짜 AI 분석이 끝나지 않음")
    win.close()
    app.processEvents()
    return 0


AI_DELAY = 4.0  # 가짜 AI 호출 한 번의 지연(초). 실제는 15~60초


def app_main(settings_path):
    """시험용 앱 실행: run_app.py와 같은 창에 가짜 AI 클라이언트(호출마다 AI_DELAY초)를 넣는다. 네트워크 없음.
    키는 파일에 쓰지 않는다(persist=False). 시작 방식은 API 키(S7·S8). Claude 구독은 가짜 CLI(tests/fake_claude_flow.py,
    호출마다 4초)를 이 경로 안에서만 주입한다(S15). 설정 파일·화면으로는 실행 명령을 바꿀 수 없다."""
    sys.path.insert(0, REPO_ROOT)
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    from hazop.app import make_application
    app = make_application(["hazop-user-check"])
    import shoot_results  # QApplication 뒤에: 이 모듈은 import할 때 QT_QPA_PLATFORM을 offscreen으로 정한다
    from hazop.app.main_window import MainWindow

    class SlowFake(shoot_results.FakeClient):
        """호출마다 AI_DELAY초. 홀수 번째 호출은 과부하 오류로 끝내 다음 '실패 칸 다시 실행'할 칸을 남긴다."""

        def analyze(self, request):
            time.sleep(AI_DELAY)
            r = super().analyze(request)
            if self.calls % 2:
                r = dict(r, status="api_error", output=None, usage=None, error_type="overloaded", status_code=529,
                         error="AI 서비스가 과부하 상태임(HTTP 529, 시험용 가짜 응답)")
            return r
    from hazop.study import claude_cli
    win = MainWindow(settings_path=settings_path, ask_reviewer=False)
    win.api_keys.set(shoot_results.KEY, persist=False)
    win.ai_prefs.choose("api")
    tmp = os.path.dirname(os.path.abspath(settings_path))
    fake = [sys.executable, os.path.join(REPO_ROOT, "tests", "fake_claude_flow.py"), "slow20", os.path.join(tmp, "fake-cli")]
    win.ai_conn.cli_factory = lambda path, **kw: claude_cli.ClaudeCliClient(
        argv_prefix=fake, limits_path=os.path.join(tmp, "ai_limits.json"), run_root=os.path.join(tmp, "cli-run"), **kw)
    scr = win.screens[6]
    scr.make_client = lambda: SlowFake() if scr.run_method == "api" else win.ai_conn.make_client(scr.run_method)
    win.show()
    code = app.exec()
    win.close()
    return code


def launch(tmp):
    env = dict(os.environ, HAZOP_WORK_ROOT=os.path.join(tmp, "work"), HAZOP_STORE_ROOT=os.path.join(tmp, "store"),
               QTWEBENGINE_REMOTE_DEBUGGING="127.0.0.1:%d" % CDP_PORT)
    env.pop("QT_QPA_PLATFORM", None)
    return subprocess.Popen([sys.executable, os.path.abspath(__file__), "--_app", os.path.join(tmp, "settings.json")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def find_app(uia, launcher, timeout=60):
    """venv python.exe는 실제 python을 자식으로 띄운다. 창이 있는 프로세스(자신 또는 자식)를 찾는다."""
    end = time.time() + timeout
    while time.time() < end:
        for pid in [launcher.pid] + [c["pid"] for c in uia.q(op="children", pid=launcher.pid)]:
            wins = [w for w in uia.q(op="windows", pid=pid) if w["cls"] == "MainWindow"]
            if wins:
                return pid, wins[0]["hwnd"]
        time.sleep(0.5)
    raise RuntimeError("HAZOP 창이 %d초 안에 뜨지 않음" % timeout)


def cdp_port_free():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", CDP_PORT)) != 0


def run(out_dir, only=None, keep_temp=False, focus_wait=120):
    shots = os.path.join(out_dir, "shots")
    shutil.rmtree(shots, ignore_errors=True)
    os.makedirs(shots, exist_ok=True)
    for f in ("report.html", "results.json"):
        if os.path.exists(os.path.join(out_dir, f)):
            os.remove(os.path.join(out_dir, f))
    if not cdp_port_free():
        print("CDP 포트 %d를 이미 다른 프로그램이 씁니다. 그 프로그램을 끝낸 뒤 다시 실행하세요." % CDP_PORT)
        return 2
    tmp = tempfile.mkdtemp(prefix="hazop-user-check-")
    with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as fh:
        json.dump({"reviewer_name": "검증봇", "work_root": None, "recent_regions": [], "recent_runs": []}, fh, ensure_ascii=False)
    env = dict(os.environ, HAZOP_WORK_ROOT=os.path.join(tmp, "work"), HAZOP_STORE_ROOT=os.path.join(tmp, "store"),
               QT_QPA_PLATFORM="offscreen")
    if os.path.isdir(r"C:\Windows\Fonts"):
        env["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
    print("준비: 샘플 도면·가짜 AI 결과를 %s에 만듭니다" % tmp)
    rc = subprocess.run([sys.executable, os.path.abspath(__file__), "--_prepare", env["HAZOP_WORK_ROOT"]], env=env).returncode
    if rc != 0:
        print("준비 실패(rc=%d)" % rc)
        shutil.rmtree(tmp, ignore_errors=True)
        return 2
    w32, uia, cdp = Win32(), Uia(), Cdp(CDP_PORT)
    proc = launch(tmp)
    results, audits = [], []
    try:
        try:
            pid, hwnd = find_app(uia, proc)
        except RuntimeError as exc:
            print(exc)
            return 2
        w32.resize(hwnd, *WINDOW_SIZE)
        d = Driver(w32, uia, cdp, pid, hwnd, shots, paths.folder_in(os.path.join(tmp, "work"), "분석결과"))
        d.focus_wait = focus_wait
        w32.activate(hwnd)
        time.sleep(1.0)
        for sid, title, fn in SCENARIOS:
            if only and sid not in only:
                continue
            print("시나리오 %s %s" % (sid, title))
            d.begin(sid, title)
            try:
                fn(d)
            except Abort as exc:
                d.r["passed"] = False
                d.r["defects"].append({"severity": "중", "title": "시험 중단: %s" % exc, "steps": list(d.r["steps"])})
                d.end()
                results.append(d.r)
                print("  중단: %s" % exc)
                break
            except Exception as exc:  # 시나리오 하나의 오류가 나머지를 막지 않게 기록하고 넘어간다
                d.r["passed"] = False
                d.r["defects"].append({"severity": "중", "title": "시나리오 오류: %s: %s" % (type(exc).__name__, exc),
                                       "steps": list(d.r["steps"])})
            d.end()
            results.append(d.r)
            for k in range(3):  # 열린 팔레트·대화상자를 닫는다(시나리오 수치에는 넣지 않음)
                if len([e for e in d.tree() if e["type"] == "Window"]) <= 1:
                    break
                try:
                    d._guard()
                except Abort:
                    break
                d.w32.chord([VK["esc"]])
                time.sleep(0.3)
            s = summarize(d.r)
            print("  %s 클릭 %d 키 %d 전환 %d KLM %.1fs 결함 %d" % ("통과" if d.r["passed"] else "실패", s["clicks"],
                                                              s["keys"], s["screens"], s["klm"], len(d.r["defects"])))
        audits = d.audits
    finally:
        cdp.close()
        uia.close()
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not keep_temp:
            shutil.rmtree(tmp, ignore_errors=True)
    meta = "%s · 창 %dx%d · 샘플 SNP-M-102(준비)·SNP-M-201(등록) · 작업 루트 %s(%s)" % (
        time.strftime("%Y-%m-%d %H:%M"), WINDOW_SIZE[0], WINDOW_SIZE[1], tmp, "남김" if keep_temp else "지움")
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "klm": KLM, "klm_source": KLM_SOURCE, "results": results, "audits": audits}, fh,
                  ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(render_report(results, audits, meta))
    print(os.path.join(out_dir, "report.html"))
    return 0 if results and all(r["passed"] for r in results) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=paths.output_in(paths.DEV_WORK_ROOT, "사용자검증"), help="결과 폴더")
    ap.add_argument("--only", help="돌릴 시나리오 ID(쉼표), 예: S1,S3")
    ap.add_argument("--keep-temp", action="store_true", help="임시 작업 루트를 지우지 않음")
    ap.add_argument("--focus-wait", type=int, default=120, help="창 전환이 막히면 사용자가 창을 클릭하길 기다릴 초")
    ap.add_argument("--_prepare", help=argparse.SUPPRESS)
    ap.add_argument("--_app", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args._prepare:
        return prepare(args._prepare)
    if args._app:
        return app_main(args._app)
    if sys.platform != "win32":
        print("Windows에서만 동작합니다(UI Automation·SendInput)")
        return 2
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import devenv
    try:  # 실제 데스크톱은 한 번에 하나만(scripts/desktop_lease.py)
        devenv.acquire_desktop("check_user_scenarios %s" % (args.only or "전체"))
    except devenv.DesktopBusy as exc:
        print(exc)
        return 2
    try:
        return run(os.path.abspath(args.out), set(args.only.split(",")) if args.only else None, args.keep_temp,
                   args.focus_wait)
    finally:
        devenv.release_desktop()


if __name__ == "__main__":
    sys.exit(main())
