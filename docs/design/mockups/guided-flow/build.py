"""쉬운 흐름 시안(HZ-DSN-05 §12) 생성.

하는 일
- template.html에 공통 CSS(../app-shell-web/assets/app-shell.css), Tabler 아이콘(3.51.0 outline, MIT), SNP-M-101 표본 SVG를 넣어
  파일 하나로 열리는 1-guided-flow.html을 쓴다. 네트워크 요청은 없다.
- Chrome 헤드리스로 장면마다 1366×768(100%) PNG를 찍고, 같은 크기에서 넘친 요소가 있는지 DOM의 body[data-overflow]로 확인한다.
  1920×1080(125%, 1536×864 CSS 픽셀)은 장면 둘만 찍는다.

도면은 resources/references/pid-samples의 SNP-M-101 공개 표본에서 바깥 링크만 지운 것(app-shell-web/assets/snp-m-101.svg)이다.
대기열의 항목·확신·문장은 화면 표현을 보이기 위한 예시 값이다.

실행: <venv>/python.exe docs/design/mockups/guided-flow/build.py [--no-png]
아이콘 원본 폴더는 환경변수 HAZOP_TABLER_OUTLINE으로, Chrome은 HAZOP_CHROME으로 바꿀 수 있다.
"""

import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[3]
BASE = ROOT.parent / "app-shell-web" / "assets"
ICON_DIRS = [pathlib.Path(os.environ["HAZOP_TABLER_OUTLINE"])] if os.environ.get("HAZOP_TABLER_OUTLINE") else []
ICON_DIRS += [REPO / "resources" / "library" / "icons" / "tabler"]   # 여기 없는 아이콘은 HAZOP_TABLER_OUTLINE(Tabler 3.51.0 outline 폴더)로 준다
CHROME = os.environ.get("HAZOP_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
OUT = ROOT / "1-guided-flow.html"

SHOTS = [("2-next-step", "home"), ("3-next-list", "list"), ("4-nothing-left", "none"), ("5-queue-ai", "queue_ai"),
         ("6-queue-lost", "queue_lost"), ("7-queue-done", "done"), ("8-reextract-ok", "reextract_ok"), ("9-reextract-lost", "reextract_lost"),
         ("10-ai-before", "ai_before"), ("11-ai-confirm", "ai_confirm"), ("12-ai-running", "ai_running"), ("13-ai-ready", "ai_ready")]
SHOTS_1920 = [("5-queue-ai", "queue_ai"), ("9-reextract-lost", "reextract_lost"), ("11-ai-confirm", "ai_confirm")]


def icon(name):
    for d in ICON_DIRS:
        p = d / ("%s.svg" % name)
        if p.exists():
            raw = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S).strip()
            raw = re.sub(r'\s(width|height|class)="[^"]*"', "", raw)
            raw = re.sub(r"\s+", " ", raw).replace("> <", "><")
            return raw.replace("<svg", '<svg class="ic" aria-hidden="true"', 1)
    raise SystemExit("아이콘 없음: %s (환경변수 HAZOP_TABLER_OUTLINE에 Tabler Icons 3.51.0 outline 폴더를 주세요)" % name)


def build():
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    # 아이콘 이름은 ic("…")·icon: "…"·삼항식 안 등 여러 꼴로 나오므로, 따옴표 안 낱말 가운데 아이콘 파일이 있는 것을 모두 넣는다
    words = set(re.findall(r'"([a-z0-9]+(?:-[a-z0-9]+)*)"', tpl)) | set(re.findall(r"@@([a-z0-9-]+)@@", tpl))
    names = sorted(w for w in words if any((d / ("%s.svg" % w)).exists() for d in ICON_DIRS))
    icons = {n: icon(n) for n in names}
    css = (BASE / "app-shell.css").read_text(encoding="utf-8")
    sheet = (BASE / "snp-m-101.svg").read_bytes()
    if re.search(rb'href="https?://', sheet):
        raise SystemExit("도면 SVG에 바깥 링크가 남아 있음")
    html = tpl.replace("/*@@BASE_CSS@@*/", css).replace("/*@@ICONS_JSON@@*/", json.dumps(icons, ensure_ascii=False))
    html = html.replace("@@SHEET_DATA@@", "data:image/svg+xml;base64," + base64.b64encode(sheet).decode())
    html = re.sub(r"@@([a-z0-9-]+)@@", lambda m: icons[m.group(1)], html)
    if re.search(r"(src|href)=\"https?://", html):
        raise SystemExit("바깥 주소가 남아 있음")
    OUT.write_text(html, encoding="utf-8")
    print("썼음:", OUT.relative_to(REPO), "%d KB, 아이콘 %d개" % (len(html.encode()) // 1024, len(icons)))


def chrome(args, prof):
    base = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--user-data-dir=" + prof,
            "--virtual-time-budget=3000", "--run-all-compositor-stages-before-draw"]
    return subprocess.run(base + args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)


def shoot():
    url = OUT.as_uri()
    bad = []
    with tempfile.TemporaryDirectory() as prof:
        for sets in (("1366", "1366,768", "1", SHOTS), ("1920", "1536,864", "1.25", SHOTS_1920)):
            tag, size, scale, shots = sets
            for name, scene in shots:
                png = ROOT / ("%s-%s.png" % (name, tag))
                u = "%s#scene=%s&cap=1" % (url, scene)
                chrome(["--window-size=" + size, "--force-device-scale-factor=" + scale, "--screenshot=" + str(png), u], prof)
                dom = chrome(["--window-size=" + size, "--force-device-scale-factor=" + scale, "--dump-dom", u], prof).stdout
                m = re.search(r'data-overflow="([^"]*)"', dom)
                ovf = m.group(1) if m else "?"
                print("%-22s %s  넘침: %s" % (png.name, "있음" if png.exists() else "못 찍음", ovf))
                if ovf != "none":
                    bad.append((png.name, ovf))
    return bad


if __name__ == "__main__":
    build()
    if "--no-png" not in sys.argv:
        bad = shoot()
        if bad:
            print("넘친 장면:", bad)
            sys.exit(1)
