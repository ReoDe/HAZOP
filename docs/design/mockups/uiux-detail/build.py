"""UIUX 디테일 개선 시안 생성기 (B안 고밀도 작업대 + A안 단계 표시 + 옵시디언식 셸).

python docs/design/mockups/uiux-detail/build.py          HTML만 다시 만든다
python docs/design/mockups/uiux-detail/build.py --shoot  Chrome 헤드리스로 1366×768·1920×1080 PNG도 찍는다

색은 hazop/app/tokens.py COLORS를 그대로 읽는다(앱 코드는 고치지 않음). 데이터는 가상 표본이다.
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[3]))
from hazop.app.tokens import COLORS, FONT_FAMILY  # noqa: E402

SEG = ["seg1", "seg2", "seg3", "seg4", "seg5"]

CSS = """
:root{%(vars)s;--exp:clamp(200px,14vw,260px);--rel:clamp(264px,20vw,340px);--r:4px}
*{box-sizing:border-box}html,body{margin:0;height:100%%}
body{font:12.5px/1.45 "%(font)s",sans-serif;color:var(--ink);background:var(--bg);display:grid;grid-template-rows:32px 1fr 24px;overflow:hidden}
button{font:inherit}
kbd{font:11px/1 Consolas,monospace;padding:2px 4px;border:1px solid var(--line);border-bottom-width:2px;border-radius:3px;background:var(--card);color:var(--muted)}
.title{background:var(--nav-bg);color:var(--nav-ink);display:grid;grid-template-columns:auto 1fr auto;align-items:center;padding:0 12px;gap:16px}
.title b{font-size:13px;letter-spacing:.5px}.title .menu span{margin-right:14px;color:var(--nav-muted)}
.cmd{justify-self:center;width:min(440px,40vw);height:22px;border-radius:var(--r);background:#343b45;color:var(--nav-muted);display:flex;align-items:center;justify-content:space-between;padding:0 8px;font-size:12px}
.cmd kbd{background:#2b313a;border-color:#4b5563;color:var(--nav-muted)}
.title .who{color:var(--nav-muted);font-size:12px}
.mid{display:grid;grid-template-columns:48px var(--exp) 1fr var(--rel);min-height:0}
.rail{background:var(--nav-bg);display:flex;flex-direction:column;align-items:center;padding-top:6px;gap:4px}
.st{width:40px;height:40px;border-radius:var(--r);display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--nav-muted);font-size:10.5px;position:relative}
.st i{font-style:normal;width:18px;height:18px;border-radius:50%%;border:1.5px solid var(--nav-muted);display:flex;align-items:center;justify-content:center;font-size:10.5px;font-weight:700;margin-bottom:1px}
.st.done i{background:var(--ok);border-color:var(--ok);color:#fff}
.st.done::after{content:"✓";position:absolute;right:3px;top:3px;font-size:9px;color:#7ee2a0}
.st.cur{background:var(--nav-active-bg);color:#fff}.st.cur i{border-color:#fff;color:#fff}
.rail .sep{flex:1}
.exp{background:var(--surface-2);border-right:1px solid var(--line);overflow:hidden;display:flex;flex-direction:column}
.exp .flt{margin:8px;height:24px;border:1px solid var(--line-strong);border-radius:var(--r);background:var(--card);color:var(--muted);padding:3px 8px;font-size:12px}
.tree{padding:0 4px;overflow:auto}
.grp{display:flex;align-items:center;gap:4px;padding:3px 4px;font-weight:700;color:var(--ink-2);font-size:12px}
.grp .n{margin-left:auto;font-weight:400;color:var(--muted);font-size:11px}
.it{display:flex;align-items:center;gap:6px;padding:2px 4px 2px 18px;border-radius:3px;white-space:nowrap;overflow:hidden}
.it .t{overflow:hidden;text-overflow:ellipsis}.it .n{margin-left:auto;color:var(--muted);font-size:11px}
.it.on{background:var(--ui-weak);color:var(--ui-ink);box-shadow:inset 2px 0 var(--ui)}
.it.hov{background:#e6e8ec}
.empty-row{padding:2px 4px 2px 18px;color:var(--muted);font-style:italic;font-size:11.5px}
.dot{width:8px;height:8px;border-radius:2px;flex:none}
.main{display:flex;flex-direction:column;min-width:0;min-height:0}
.tabs{height:32px;display:flex;align-items:flex-end;background:var(--surface-2);border-bottom:1px solid var(--line);padding-left:4px;gap:2px}
.tab{height:28px;display:flex;align-items:center;gap:6px;padding:0 10px;border:1px solid transparent;border-bottom:0;border-radius:var(--r) var(--r) 0 0;color:var(--muted);max-width:240px;white-space:nowrap}
.tab .t{overflow:hidden;text-overflow:ellipsis}.tab .x{color:var(--muted);font-size:11px}
.tab.on{background:var(--card);border-color:var(--line);color:var(--ink);margin-bottom:-1px;height:29px;box-shadow:inset 0 2px var(--ui)}
.tab .dirty{width:6px;height:6px;border-radius:50%%;background:var(--ink-2)}
.tabs .split{margin-left:auto;align-self:center;color:var(--muted);padding:0 10px;font-size:12px}
.body{flex:1;min-height:0;display:flex;flex-direction:column;background:var(--card)}
.bar{display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--line);flex-wrap:nowrap;white-space:nowrap}
.bar .sp{flex:1}.muted{color:var(--muted)}
.btn{height:24px;padding:0 10px;border:1px solid var(--line-strong);border-radius:var(--r);background:var(--card);color:var(--ink);display:inline-flex;align-items:center;gap:6px}
.btn.pri{background:var(--ui);border-color:var(--ui);color:var(--on-fill)}
.btn.ghost{border-color:transparent;background:transparent;color:var(--ui-ink)}
.btn.danger{color:var(--err-ink);border-color:var(--err-line)}
.btn kbd{font-size:10px;padding:1px 3px}
.btn.pri kbd{background:transparent;color:#dbe7f7;border-color:#7aa7df}
.sel{height:24px;border:1px solid var(--line-strong);border-radius:var(--r);padding:0 8px;display:inline-flex;align-items:center;gap:8px;background:var(--card)}
.prog{display:inline-flex;align-items:center;gap:6px;color:var(--muted)}
.prog .track{width:120px;height:4px;border-radius:2px;background:var(--line)}.prog .fill{height:4px;border-radius:2px;background:var(--ok)}
.chip{display:inline-flex;align-items:center;gap:4px;height:18px;padding:0 6px;border-radius:3px;font-size:11px;white-space:nowrap}
.chip.ok{background:var(--ok-bg);color:var(--ok)}.chip.warn{background:var(--warn-bg);color:var(--warn-ink)}
.chip.err{background:var(--err-bg);color:var(--err-ink);border:1px solid var(--err-line)}
.chip.ai{background:repeating-linear-gradient(135deg,var(--ai-hatch-a) 0 4px,var(--ai-hatch-b) 4px 8px);color:var(--ai-ink);border:1px dashed var(--line-strong)}
.chip.seg{color:var(--on-seg);font-weight:700}
.rel{background:var(--surface-2);border-left:1px solid var(--line);overflow:auto;min-height:0}
.rel h3{margin:0;padding:8px 10px;font-size:12px;border-bottom:1px solid var(--line);display:flex;gap:6px;align-items:center;background:var(--card)}
.rel h3 .muted{font-weight:400}
.sec{border-bottom:1px solid var(--line);padding:6px 10px}
.sec h4{margin:0 0 4px;font-size:11.5px;color:var(--ink-2);display:flex;align-items:center;gap:4px}
.sec h4 .n{margin-left:auto;color:var(--muted);font-weight:400}
.ln{display:flex;gap:6px;align-items:baseline;padding:2px 0;color:var(--ui-ink)}
.ln .s{color:var(--muted);font-size:11px;margin-left:auto;white-space:nowrap}
.ctx{color:var(--muted);font-size:11.5px;padding-left:12px;margin-bottom:3px}
.ctx mark{background:#fff3b0;color:var(--ink)}
.status{background:var(--nav-bg);color:var(--nav-muted);display:flex;align-items:center;gap:14px;padding:0 10px;font-size:11.5px;white-space:nowrap}
.status .sp{flex:1}.status kbd{background:#2b313a;color:var(--nav-muted);border-color:#4b5563}.status b{color:var(--nav-ink);font-weight:400}
.status .okd{color:#7ee2a0}.status .errd{color:#ff9b93}
.toast{position:fixed;right:calc(var(--rel) + 16px);bottom:36px;background:var(--ink);color:#fff;border-radius:6px;padding:8px 12px;display:flex;gap:12px;align-items:center;box-shadow:0 6px 20px rgba(0,0,0,.25);font-size:12.5px}
.toast a{color:#9cc6ff;font-weight:700;text-decoration:none}.toast kbd{background:#2a313b;color:#c9d1db;border-color:#4b5563}
.ann{position:fixed;background:#fffbe6;border:1px solid #d4a72c;color:#5c4400;border-radius:4px;padding:3px 7px;font-size:11px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.15);z-index:50}
.ann::before{content:attr(data-n);display:inline-block;background:#d4a72c;color:#fff;border-radius:50%%;width:15px;height:15px;text-align:center;line-height:15px;margin-right:4px;font-size:10px}
/* ⑤ 행렬 */
.mx{overflow:auto;border-bottom:1px solid var(--line);flex:none;max-height:46%%}
.mx table{border-collapse:separate;border-spacing:0;font-size:11.5px}
.mx th,.mx td{border-right:1px solid var(--line);border-bottom:1px solid var(--line);padding:0;text-align:center;white-space:nowrap}
.mx thead th{position:sticky;top:0;background:var(--surface-2);font-weight:400;color:var(--muted);height:20px;z-index:1}
.mx thead tr:nth-child(2) th{top:20px}
.mx thead th.p{color:var(--ink-2);font-weight:700;border-bottom:1px solid var(--line-strong)}
.mx .rh{position:sticky;left:0;background:var(--card);text-align:left;padding:0 8px;width:210px;min-width:210px;max-width:210px;z-index:2;overflow:hidden;text-overflow:ellipsis}
.mx thead .rh{z-index:3;background:var(--surface-2)}
.mx td.c{width:54px;min-width:54px;height:30px;font-weight:700;position:relative}
.mx td.c small{position:absolute;right:3px;top:2px;font-size:9.5px;font-weight:400}
.c.ok{background:var(--risk-ok-bg);color:var(--risk-ok-ink)}.c.cond{background:var(--risk-cond-bg);color:var(--risk-cond-ink)}
.c.deny{background:var(--risk-deny-bg);color:var(--risk-deny-ink)}
.c.na{background:repeating-linear-gradient(135deg,var(--ai-hatch-a) 0 4px,var(--ai-hatch-b) 4px 8px);color:var(--muted);font-weight:400}
.c.fail{background:var(--card);color:var(--err-ink);outline:1.5px dashed var(--err-ink);outline-offset:-4px;font-weight:700}
.c.cur{box-shadow:inset 0 0 0 2px var(--ui),inset 0 0 0 3px #fff}
.legend{display:flex;gap:12px;align-items:center;padding:4px 10px;color:var(--muted);font-size:11px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.legend .sw{display:inline-block;width:14px;height:12px;vertical-align:-2px;margin-right:3px;border-radius:2px}
.ws{flex:1;min-height:0;overflow:auto}
.ws .hd{display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--line)}
.ws .hd b{font-size:14px}
.ws table{width:100%%;border-collapse:collapse;table-layout:fixed}
.ws th{position:sticky;top:0;background:var(--surface-2);font-weight:400;color:var(--muted);text-align:left;padding:4px 8px;border-bottom:1px solid var(--line)}
.ws td{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.ws tr.ai td:first-child{box-shadow:inset 3px 0 0 var(--line-strong)}
.ws tr.ai{background:linear-gradient(90deg,#f7f8fa,#fff 40px)}
.ws tr.on{background:var(--ui-weak)}
.ws tr.on td:first-child{box-shadow:inset 3px 0 0 var(--ui)}
.ws .chip{white-space:normal;height:auto;padding:1px 6px}
.ws .acts{display:flex;gap:4px;flex-wrap:wrap}
.rk{display:inline-block;padding:1px 6px;border-radius:3px;font-weight:700}
/* 도면 */
.canvas{flex:1;min-height:0;position:relative;background:#fff;overflow:hidden}
.canvas svg{width:100%%;height:100%%}
.float{position:absolute;background:var(--card);border:1px solid var(--line);border-radius:var(--r);box-shadow:0 1px 4px rgba(0,0,0,.08);font-size:11.5px}
.zoom{left:10px;bottom:10px;display:flex;align-items:center;gap:2px;padding:2px}
.zoom span{padding:2px 8px}
.layers{right:10px;top:10px;display:flex;gap:2px;padding:2px}
.layers span{padding:2px 8px;border-radius:3px}.layers span.on{background:var(--ui-weak);color:var(--ui-ink)}
.seglegend{left:10px;top:10px;display:flex;gap:4px;padding:4px 6px;align-items:center}
.pop{position:fixed;width:300px;background:var(--card);border:1px solid var(--line-strong);border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.18);z-index:20;font-size:12px}
.pop .ph{padding:8px 10px;border-bottom:1px solid var(--line);display:flex;gap:6px;align-items:center}
.pop .pb{padding:8px 10px}
.pop .mini{height:96px;border:1px solid var(--line);border-radius:3px;background:#fff;margin:6px 0}
/* ④ 구간 패널 */
.seglist .row{display:grid;grid-template-columns:26px 1fr auto;gap:6px;align-items:center;padding:3px 10px;border-bottom:1px solid var(--line);background:var(--card)}
.seglist .row .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.seglist .row.on{background:var(--ui-weak);box-shadow:inset 3px 0 var(--ui)}
.subtabs{display:flex;border-bottom:1px solid var(--line);background:var(--card)}
.subtabs span{padding:5px 10px;color:var(--muted)}.subtabs span.on{color:var(--ink);box-shadow:inset 0 -2px var(--ui)}
/* 팔레트 */
.dim{position:fixed;inset:0;background:rgba(15,20,25,.32);z-index:30}
.pal{position:fixed;left:50%%;top:64px;transform:translateX(-50%%);width:min(640px,60vw);background:var(--card);border-radius:8px;box-shadow:0 16px 48px rgba(0,0,0,.3);z-index:31;overflow:hidden}
.pal .in{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--line);font-size:15px}
.pal .in .scope{font-size:11px;background:var(--surface-2);border:1px solid var(--line);border-radius:3px;padding:1px 6px;color:var(--muted)}
.pal .g{padding:6px 14px 2px;font-size:11px;color:var(--muted)}
.pal .r{display:flex;align-items:center;gap:8px;padding:5px 14px}
.pal .r.on{background:var(--ui-weak)}
.pal .r .s{color:var(--muted);font-size:11.5px}.pal .r .k{margin-left:auto;display:flex;gap:3px}
.pal mark{background:none;color:var(--ui);font-weight:700}
.pal .ft{display:flex;gap:14px;padding:6px 14px;border-top:1px solid var(--line);color:var(--muted);font-size:11px;background:var(--surface-2)}
/* ① */
.reg{display:grid;grid-template-columns:1fr minmax(300px,36%%);flex:1;min-height:0}
.list table{width:100%%;border-collapse:collapse}
.list th{text-align:left;font-weight:400;color:var(--muted);padding:4px 10px;border-bottom:1px solid var(--line);background:var(--surface-2)}
.list td{padding:6px 10px;border-bottom:1px solid var(--line)}
.pbar{height:4px;background:var(--line);border-radius:2px;width:120px;display:inline-block;vertical-align:middle}
.pbar i{display:block;height:4px;background:var(--ui);border-radius:2px}
.form{border-left:1px solid var(--line);padding:10px 12px;overflow:auto}
.form .f{display:grid;grid-template-columns:56px 1fr auto;gap:6px;align-items:center;margin-bottom:6px}
.form .inp{height:24px;border:1px solid var(--line-strong);border-radius:var(--r);padding:3px 8px;background:var(--card)}
.form .cand{color:var(--ui-ink);font-size:11.5px}
.drop{border:1.5px dashed var(--line-strong);border-radius:6px;padding:14px;text-align:center;color:var(--muted);margin-bottom:10px;background:var(--surface-2)}
.empty{margin:auto;text-align:center;max-width:420px;color:var(--muted)}
.empty .ic{width:56px;height:56px;margin:0 auto 10px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line);display:flex;align-items:center;justify-content:center;font-size:26px;color:var(--line-strong)}
.empty h2{font-size:15px;color:var(--ink);margin:0 0 6px}
.empty .acts{display:flex;gap:8px;justify-content:center;margin:12px 0}
.empty ol{text-align:left;display:inline-block;margin:6px 0 0;padding-left:18px;font-size:12px}
""" % {"vars": ";".join("--%s:%s" % kv for kv in COLORS.items()), "font": FONT_FAMILY}

STEPS = [("1", "등록"), ("2", "추출"), ("3", "그래프"), ("4", "구간"), ("5", "결과")]
SEGS = [("S1", "RC-PZ01 가압기", 3), ("S2", "배관 RC-L010 (RC-PZ01→RC-PT110)", 2), ("S3", "배관 RC-L011 (RC-PZ01→RC-L030)", 2),
        ("S4", "배관 RC-L030 외 1 (RC-L031·RC-PSV101)", 4), ("S5", "배관 RC-L031-T37", 1)]


def rail(cur, done):
    out = []
    for n, name in STEPS:
        cls = "cur" if n == cur else ("done" if n in done else "")
        out.append('<div class="st %s"><i>%s</i>%s</div>' % (cls, n, name))
    return '<nav class="rail">%s<div class="sep"></div><div class="st" title="설정">⚙</div></nav>' % "".join(out)


def explorer(active=None, hover=None, filt="필터 (Ctrl+Shift+E)"):
    def it(key, txt, n="", dot=""):
        cls = "on" if key == active else ("hov" if key == hover else "")
        d = '<span class="dot" style="background:var(--%s)"></span>' % dot if dot else ""
        return '<div class="it %s">%s<span class="t">%s</span><span class="n">%s</span></div>' % (cls, d, txt, n)
    segs = "".join(it(s, "%s %s" % (s, name), "미%d" % (u * 12), SEG[i]) for i, (s, name, u) in enumerate(SEGS))
    return """<aside class="exp"><div class="flt">⌕ %s</div><div class="tree">
<div class="grp">▾ 자료<span class="n">3</span></div>%s%s%s
<div class="grp">▾ 지식그래프<span class="n">1</span></div>%s
<div class="grp">▾ 검토구간 · SNP-M-102<span class="n">5</span></div>%s
<div class="grp">▸ 권고<span class="n">0</span></div><div class="empty-row">AI 분석 후 권고가 모입니다</div>
</div></aside>""" % (filt, it("d1", "SNP-M-101 · Rev.0"), it("d2", "SNP-M-102 · Rev.0", "", ""), it("d3", "설정치 목록.pdf"),
                      it("kg", "kg-SNP-SAMPLE", "노드 61"), segs)


def tabs(items):
    out = []
    for on, title, dirty in items:
        mark = '<span class="dirty" title="저장 안 됨"></span>' if dirty else '<span class="x">✕</span>'
        out.append('<div class="tab %s"><span class="t">%s</span>%s</div>' % ("on" if on else "", title, mark))
    return '<div class="tabs">%s<span class="split" title="오른쪽으로 분할 (Ctrl+\\)">⫿ 분할</span></div>' % "".join(out)


def status(left, right):
    return '<footer class="status">%s<span class="sp"></span>%s</footer>' % (left, right)


def page(title, step, done, tab_items, body, related, st, extra="", active=None, hover=None):
    return """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>%s</title><style>%s</style></head><body>
<header class="title"><div><b>HAZOP</b> <span class="menu"><span>파일</span><span>보기</span><span>도움말</span></span></div>
<div class="cmd"><span>⌕ 구간·구성요소·명령 찾기</span><kbd>Ctrl+P</kbd></div><div class="who">검토자 EJ</div></header>
<div class="mid">%s%s<section class="main">%s<div class="body">%s</div></section><aside class="rel">%s</aside></div>%s%s</body></html>""" % (
        title, CSS, rail(step, done), explorer(active, hover), tabs(tab_items), body, related, st, extra)


def ann(n, x, y, text):
    return '<div class="ann" data-n="%s" style="left:%s;top:%s">%s</div>' % (n, x, y, text)


DEVS = [("압력", ["증가", "감소", "없음"]), ("유량", ["증가", "감소", "없음", "역류"]), ("온도", ["증가", "감소"]),
        ("액면", ["증가", "감소"]), ("조성", ["변화", "오염"]), ("계측", ["오지시", "고장"]), ("운전", ["기동", "정지", "정비"]),
        ("외부", ["화재", "지진"])]
PATTERN = ["deny5", "ok1", "na", "cond4", "fail", "cond3", "ok2", "na", "deny5", "cond4", "ok1", "fail", "na", "cond3",
           "ok2", "cond4", "na", "ok1", "deny5", "cond3", "na"]


def cell(i, r):
    k = PATTERN[(i * 5 + r * 3) % len(PATTERN)]
    if k == "na":
        return '<td class="c na" title="분석 전">–</td>'
    if k == "fail":
        return '<td class="c fail" title="AI 실행 실패: 응답 형식 오류 · Enter로 다시 실행">! 실패</td>'
    band, n = k[:-1], k[-1]
    u = "" if (i + r) % 3 else '<small>미1</small>'
    return '<td class="c %s">%s%s</td>' % (band, n, u)


def matrix(cur=(0, 4)):
    h1 = "".join('<th class="p" colspan="%d">%s</th>' % (len(v), p) for p, v in DEVS)
    h2 = "".join("<th>%s</th>" % g for _, v in DEVS for g in v)
    rows = []
    for r, (s, name, _) in enumerate(SEGS):
        cells = []
        for i in range(sum(len(v) for _, v in DEVS)):
            c = cell(i, r)
            if (r, i) == cur:
                c = c.replace('class="c ', 'class="c cur ')
            cells.append(c)
        rows.append('<tr><th class="rh" title="%s %s"><span class="chip seg" style="background:var(--%s)">%s</span> %s</th>%s</tr>' % (
            s, name, SEG[r], s, name, "".join(cells)))
    return """<div class="mx"><table><thead><tr><th class="rh" rowspan="2">구간 × 편차 <span class="muted">(시안 표본 21개)</span></th>%s</tr><tr>%s</tr></thead>
<tbody>%s</tbody></table></div>""" % (h1, h2, "".join(rows))


LEGEND = """<div class="legend"><span>칸 숫자 = 최고 위험도</span><span><i class="sw c ok"></i>1·2 수용</span><span><i class="sw c cond"></i>3·4 조건부</span>
<span><i class="sw c deny"></i>5 불허</span><span><i class="sw c na"></i>– 분석 전</span><span><i class="sw" style="outline:1.5px dashed var(--err-ink);outline-offset:-3px"></i>! AI 실행 실패(위험도 아님)</span>
<span>미N = 미검토 시나리오</span><span class="sp" style="flex:1"></span><span>←↑↓→ 칸 이동 · <kbd>J</kbd> 다음 미검토 · <kbd>Enter</kbd> 열기</span></div>"""


def screen5():
    bar = """<div class="bar"><span class="sel">SNP-M-102 ▾</span><span class="muted">구간 5 · 편차 44 · 시나리오 175 · 미검토 173</span><span class="sp"></span>
<span class="prog"><span class="track"><span class="fill" style="display:block;width:100%"></span></span>AI 50/50 · 실패 10</span>
<button class="btn">실패 칸 다시 실행</button><button class="btn pri">AI 일괄 분석</button></div>"""
    ws = """<div class="ws"><div class="hd"><span class="chip seg" style="background:var(--seg1)">S1</span><b>RC-PZ01 가압기 × 유량 증가</b>
<span class="chip ai">AI 초안 2건</span><span class="muted">설계의도: 가압기 수위·압력 유지 (설계 문서 §4.2)</span><span class="sp" style="flex:1"></span><span class="muted">2 / 2 시나리오</span></div>
<table><colgroup><col style="width:3%"><col style="width:17%"><col style="width:16%"><col style="width:12%"><col style="width:13%"><col style="width:10%"><col style="width:15%"><col style="width:14%"></colgroup>
<thead><tr><th>#</th><th>원인</th><th>결과</th><th>보호수단</th><th>권고</th><th>위험도</th><th>AI 근거</th><th>상태 · 동작</th></tr></thead><tbody>
<tr class="ai on"><td>1</td><td>가압기 압력 제어 실패로 살수 밸브가 열린 채 고착 (RC-PZ01)</td><td>가압기 압력 급감, 원자로냉각재 압력 저하</td><td>RC-LI110 경보</td><td>제어 논리 설정치 확인</td>
<td><span class="rk" style="background:var(--risk-cond-bg);color:var(--risk-cond-ink)">4 조건부</span></td>
<td><span class="ln" style="color:var(--ui-ink)">RC-PZ01 → RC-PT110</span><span class="chip err">⚠ 도면에 없는 태그 PZR-HTR-99</span></td>
<td><span class="chip ai">AI 초안 · 제안</span><div class="acts" style="margin-top:4px"><button class="btn">승인 <kbd>A</kbd></button><button class="btn">기각 <kbd>R</kbd></button><button class="btn ghost">수정 <kbd>E</kbd></button></div></td></tr>
<tr class="ai"><td>2</td><td>충전 유량 제어 밸브 CV-L020 과개방</td><td>가압기 수위 상승, 고수위 정지 신호</td><td>RC-LT110 고수위 경보, 원자로 정지</td><td>충전 유량 상한 확인</td>
<td><span class="rk" style="background:var(--risk-ok-bg);color:var(--risk-ok-ink)">2 수용</span></td><td><span class="ln">CV-L020 → RC-PZ01</span></td>
<td><span class="chip ai">AI 초안 · 제안</span></td></tr></tbody></table></div>"""
    rel = """<h3>관련 항목 <span class="muted">· S1 × 유량 증가</span></h3>
<div class="sec"><h4>▾ 도면 위치<span class="n">SNP-M-102</span></h4><div class="mini" style="height:110px;border:1px solid var(--line);border-radius:3px;background:#fff">%s</div>
<div class="muted" style="font-size:11px">클릭하면 ④ 도면 탭에서 S1을 확대 <kbd>Alt+D</kbd></div></div>
<div class="sec"><h4>▾ 구성요소<span class="n">3</span></h4><div class="ln">RC-PZ01 <span class="s">가압기</span></div><div class="ln">RC-PT110 <span class="s">압력 전송기</span></div><div class="ln">RC-LT110 <span class="s">수위 전송기</span></div></div>
<div class="sec"><h4>▾ 지식그래프 근거<span class="n">2</span></h4><div class="ln">설정치 목록.pdf p.3<span class="s">설정치</span></div>
<div class="ctx">… 가압기 압력 고 경보 <mark>RC-PT110</mark> 설정치 158 kg/cm² …</div><div class="ln">계통 설명서 §4.2<span class="s">요건</span></div></div>
<div class="sec"><h4>▾ 같은 구성요소를 쓰는 다른 칸<span class="n">4</span></h4><div class="ln">S1 × 압력 감소<span class="s">위험 5 · 미검토</span></div>
<div class="ln">S2 × 유량 증가<span class="s">위험 4</span></div><div class="ln">S2 × 압력 증가<span class="s">! 실패</span></div><div class="ln">S4 × 역류<span class="s">분석 전</span></div></div>
<div class="sec"><h4>▸ 변경 이력<span class="n">1</span></h4></div>""" % mini_svg()
    st = status('<b>SNP-M-102</b><span>구간 5</span><span>미검토 173</span><span class="errd">실패 10</span>',
                '<span class="okd">● 저장됨 12:46</span><span>AI 초안은 사람이 승인해야 확정</span><span><kbd>Ctrl+P</kbd> 명령</span><span><kbd>?</kbd> 단축키</span>')
    toast = '<div class="toast">S1 × 압력 감소 시나리오 1을 기각했습니다 <a>실행 취소</a><kbd>Ctrl+Z</kbd></div>'
    return page("⑤ 결과 · 옵시디언식 셸", "5", "1234",
                [(False, "SNP-M-102 · 도면", False), (False, "S1 구간", False), (True, "⑤ 결과 · SNP-M-102", True), (False, "그래프 · RC-PZ01 로컬", False)],
                bar + matrix() + LEGEND + ws, rel, st, toast, active="S1")


def mini_svg():
    return """<svg viewBox="0 0 300 110" width="100%" height="100%"><g fill="none" stroke="#9aa3ad" stroke-width="1.5">
<path d="M20 70 H280"/><path d="M150 20 V70"/><rect x="220" y="40" width="40" height="55" rx="18"/></g>
<rect x="125" y="14" width="50" height="78" rx="22" fill="rgba(11,114,133,.15)" stroke="var(--seg1)" stroke-width="2.5"/>
<text x="150" y="104" font-size="10" text-anchor="middle" fill="var(--seg1)" font-weight="700">S1 RC-PZ01</text></svg>"""


def pid_svg(highlight=None):
    segc = {"S1": "var(--seg1)", "S2": "var(--seg2)", "S3": "var(--seg3)", "S4": "var(--seg4)", "S5": "var(--seg5)"}
    def w(s):
        return 5 if s == highlight else 3
    def op(s):
        return 1 if (highlight is None or s == highlight) else 0.35
    tags = [(395, 92, "RC-PT110"), (395, 152, "RC-LT110"), (232, 300, "RC-PZ01"), (612, 300, "RC-L030"), (742, 190, "RC-PSV101"),
            (520, 420, "CV-L020"), (160, 420, "RC-L031-T37")]
    tg = "".join('<g><rect x="%d" y="%d" width="%d" height="20" rx="3" fill="#fff" stroke="#111827" stroke-width="1"/>'
                 '<text x="%d" y="%d" font-size="13" text-anchor="middle" fill="#111827">%s</text></g>' % (
                     x - 44, y - 14, 88, x, y + 1, t) for x, y, t in tags)
    return """<svg viewBox="0 0 900 520" preserveAspectRatio="xMidYMid meet">
<rect x="20" y="20" width="860" height="480" fill="none" stroke="#111827" stroke-width="1"/>
<g opacity="%s"><rect x="200" y="110" width="64" height="170" rx="30" fill="rgba(11,114,133,.12)" stroke="%s" stroke-width="%s"/></g>
<g opacity="%s"><path d="M232 110 V80 H380" fill="none" stroke="%s" stroke-width="%s"/></g>
<g opacity="%s"><path d="M264 240 H600" fill="none" stroke="%s" stroke-width="%s"/></g>
<g opacity="%s"><path d="M600 240 H740 V200 M600 240 V380 H700" fill="none" stroke="%s" stroke-width="%s"/>
<rect x="690" y="345" width="70" height="110" rx="28" fill="none" stroke="#111827"/></g>
<g opacity="%s"><path d="M232 280 V440 H520" fill="none" stroke="%s" stroke-width="%s"/></g>
<circle cx="395" cy="122" r="18" fill="#fff" stroke="#0d97d6" stroke-width="2"/><circle cx="395" cy="182" r="18" fill="#fff" stroke="#0d97d6" stroke-width="2"/>
<path d="M395 140 V164 M395 200 V240" stroke="#d67506" stroke-width="2"/>
<path d="M500 430 l20 10 l-20 10 z M540 430 l-20 10 l20 10 z" fill="#111827"/>
%s
<g font-size="11" fill="#525b67"><rect x="640" y="460" width="240" height="40" fill="none" stroke="#111827"/><text x="650" y="476">TITLE: REACTOR COOLANT SYSTEM</text><text x="650" y="492">DWG NO. SNP-M-102  REV. 0</text></g>
</svg>""" % (op("S1"), segc["S1"], w("S1"), op("S2"), segc["S2"], w("S2"), op("S3"), segc["S3"], w("S3"), op("S4"), segc["S4"], w("S4"),
             op("S5"), segc["S5"], w("S5"), tg)


def seg_panel(on="S4"):
    rows = "".join('<div class="row %s"><span class="chip seg" style="background:var(--%s)">%s</span><span class="t">%s</span><span class="muted">%d개 · %s</span></div>' % (
        "on" if s == on else "", SEG[i], s, name, n, "제안" if i % 2 else "확정") for i, (s, name, n) in enumerate(SEGS))
    rows += "".join('<div class="row"><span class="chip seg" style="background:var(--%s)">S%d</span><span class="t">배관 MS-L%03d</span><span class="muted">1개 · 제안</span></div>' % (
        SEG[(k - 1) % 5], k, k * 7) for k in range(6, 11))
    return """<h3>검토구간 <span class="muted">· 10개 · 덮음 61/61 · 미포함 0</span></h3>
<div style="height:3px;background:var(--ok)"></div>
<div class="seglist">%s</div>
<div class="bar" style="background:var(--card)"><button class="btn">병합 <kbd>M</kbd></button><button class="btn">분할</button><button class="btn">이름 <kbd>F2</kbd></button><span class="sp"></span><button class="btn ghost">⑤ →</button></div>
<div class="subtabs"><span class="on">구성요소 4</span><span>미포함 0</span><span>속한 구간</span></div>
<div class="sec" style="background:var(--card)"><div class="ln">RC-L030 <span class="s">배관</span></div><div class="ln">RC-L031 <span class="s">배관</span></div><div class="ln">RC-PSV101 <span class="s">안전밸브</span></div><div class="ln">RC-L030-T25 <span class="s">티</span></div></div>""" % rows


def screen4():
    bar = """<div class="bar"><span class="sel">SNP-M-102 ▾</span><span class="chip warn">제안 · 저장 전</span><span class="chip ok">● 구조 검증 통과 · 미확인 11</span><span class="sp"></span>
<button class="btn danger">다시 제안…</button><button class="btn">확정 해제</button><button class="btn pri">구간 확정 <kbd>Ctrl+Enter</kbd></button></div>"""
    canvas = """<div class="canvas">%s
<div class="float seglegend"><span class="muted">구간</span>%s</div>
<div class="float layers"><span class="on">심볼</span><span class="on">배관</span><span class="on">태그</span><span>범례 ▾</span></div>
<div class="float zoom"><span>－</span><span>62%%</span><span>＋</span><span>맞춤 <kbd>0</kbd></span></div></div>""" % (
        pid_svg("S4"), "".join('<span class="chip seg" style="background:var(--%s)">%s</span>' % (SEG[i], s) for i, (s, _, _) in enumerate(SEGS)))
    pop = """<div class="pop" style="left:calc(48px + var(--exp) + 6px);top:252px"><div class="ph"><span class="chip seg" style="background:var(--seg4)">S4</span><b>배관 RC-L030 외 1 (RC-L031·RC-PSV101)</b></div>
<div class="pb"><div class="muted">구성요소 4 · 확정 · ⑤ 시나리오 38 · 미검토 35</div><div class="mini">%s</div>
<div class="muted" style="font-size:11px">클릭 = 이 탭에서 열기 · <kbd>Ctrl</kbd>+클릭 = 새 탭 · 미리보기는 <kbd>Ctrl</kbd>를 누른 채 올리면 뜸</div></div></div>""" % mini_svg().replace("var(--seg1)", "var(--seg4)").replace("S1 RC-PZ01", "S4 RC-L030")
    st = status('<b>SNP-M-102</b><span>구간 10 (제안)</span><span>덮음 61/61</span>',
                '<span style="color:#f5c56b">● 저장 안 됨 · 확정하면 저장</span><span><kbd>Ctrl+P</kbd> 명령</span><span><kbd>?</kbd> 단축키</span>')
    extra = pop + ann(1, "calc(48px + var(--exp) + 312px)", "258px", "마우스 올림 미리보기") + ann(2, "calc(100% - var(--rel) - 330px)", "150px", "레이어·범례는 접힌 칩")
    return page("④ 검토구간 · 미리보기", "4", "123",
                [(False, "SNP-M-102 · 도면", False), (True, "④ 구간 · SNP-M-102", True), (False, "⑤ 결과 · SNP-M-102", False)],
                bar + canvas, seg_panel(), st, extra, active="S4", hover="S4")


def screen_palette():
    pal = """<div class="dim"></div><div class="pal"><div class="in"><span class="scope">전체</span><b>pz01</b><span class="muted" style="margin-left:auto;font-size:11px"># 구간 · @ 구성요소 · &gt; 명령</span></div>
<div class="g">구성요소</div><div class="r on"><span class="chip seg" style="background:var(--seg1)">S1</span><span><mark>RC-PZ01</mark> 가압기</span><span class="s">SNP-M-102 · 구간 S1 · 시나리오 22</span><span class="k"><kbd>Enter</kbd></span></div>
<div class="r"><span class="chip seg" style="background:var(--seg2)">S2</span><span>배관 RC-L010 (<mark>RC-PZ01</mark>→RC-PT110)</span><span class="s">구간</span></div>
<div class="g">워크시트 칸</div><div class="r"><span class="rk" style="background:var(--risk-deny-bg);color:var(--risk-deny-ink)">5</span><span>S1 <mark>RC-PZ01</mark> × 압력 감소</span><span class="s">미검토 1</span></div>
<div class="r"><span class="rk" style="background:var(--risk-cond-bg);color:var(--risk-cond-ink)">4</span><span>S1 <mark>RC-PZ01</mark> × 유량 증가</span><span class="s">AI 초안 2</span></div>
<div class="g">지식그래프</div><div class="r"><span>그래프: <mark>RC-PZ01</mark> 로컬 (깊이 2)</span><span class="s">노드 14</span></div>
<div class="g">명령</div><div class="r"><span>다음 미검토 칸으로 이동</span><span class="k"><kbd>J</kbd></span></div><div class="r"><span>구간 확정</span><span class="k"><kbd>Ctrl</kbd><kbd>Enter</kbd></span></div>
<div class="ft"><span><kbd>↑</kbd><kbd>↓</kbd> 이동</span><span><kbd>Enter</kbd> 열기</span><span><kbd>Ctrl</kbd>+<kbd>Enter</kbd> 새 탭</span><span><kbd>Esc</kbd> 닫기</span><span style="margin-left:auto">최근 연 항목이 먼저</span></div></div>"""
    bar = '<div class="bar"><span class="sel">SNP-M-102 ▾</span><span class="sp"></span><button class="btn pri">구간 확정</button></div>'
    st = status('<b>SNP-M-102</b><span>구간 10</span>', '<span><kbd>Ctrl+P</kbd> 명령</span>')
    return page("명령 팔레트", "4", "123", [(False, "SNP-M-102 · 도면", False), (True, "④ 구간 · SNP-M-102", False)],
                bar + '<div class="canvas">%s</div>' % pid_svg(), seg_panel("S1"), st, pal, active="S1")


def screen1():
    bar = '<div class="bar"><b>등록 자료</b><span class="muted">3건 · 진행 1 · 실패 1</span><span class="sp"></span><button class="btn">파일 선택 <kbd>Ctrl+O</kbd></button></div>'
    lst = """<div class="list"><table><thead><tr><th>상태</th><th>자료</th><th>종류</th><th>도면번호 · 개정</th><th>단계</th></tr></thead><tbody>
<tr><td><span class="chip ok">✓ 완료</span></td><td>SNP-M-101.drawio</td><td>P&amp;ID</td><td>SNP-M-101 · 0</td><td class="muted">추출·그래프 끝 12:31</td></tr>
<tr style="background:var(--ui-weak)"><td><span class="chip" style="background:var(--card);color:var(--ui-ink);border:1px solid var(--ui)">◐ 진행</span></td><td>SNP-M-102.pdf</td><td>P&amp;ID (벡터 PDF)</td><td>SNP-M-102 · 0</td>
<td><span class="pbar"><i style="width:55%"></i></span> 2/4 선·기호 추출 · 약 20초 남음 <button class="btn ghost">취소</button></td></tr>
<tr><td><span class="chip err">! 실패</span></td><td>설정치 목록(스캔).pdf</td><td>설계 문서</td><td class="muted">미확인</td><td style="color:var(--err-ink)">글자층이 없는 스캔 PDF <button class="btn">원인 보기</button><button class="btn">다시 시도</button></td></tr>
</tbody></table></div>"""
    form = """<div class="form"><div class="drop">여기에 .drawio · 벡터 PDF · 설계 문서 PDF를 놓거나 <b style="color:var(--ui-ink)">눌러서 선택</b></div>
<div style="font-weight:700;margin:4px 0 6px">SNP-M-102.pdf 식별정보 <span class="muted" style="font-weight:400">· 표제란에서 찾은 후보</span></div>
<div class="f"><span>도면번호</span><span class="inp">SNP-M-102</span><span class="chip ok">후보와 같음</span></div>
<div class="f"><span>개정번호</span><span class="inp muted">미확인</span><button class="btn">후보 "0" 쓰기</button></div>
<div class="f"><span>제목</span><span class="inp muted">미확인</span><button class="btn">후보 쓰기</button></div>
<div class="f"><span>등록자</span><span class="inp">EJ</span><span></span></div>
<div style="display:flex;gap:6px;margin-top:10px"><button class="btn pri">등록·추출 시작</button><button class="btn">등록만</button></div></div>"""
    st = status('<b>자료 3</b><span class="errd">실패 1</span>', '<span>◐ SNP-M-102.pdf 추출 2/4 · 55%</span><span><kbd>Ctrl+P</kbd> 명령</span>')
    rel = """<h3>선택한 자료 <span class="muted">· SNP-M-102.pdf</span></h3><div class="sec"><h4>▾ 추출 단계<span class="n">2/4</span></h4>
<div class="ln" style="color:var(--ok)">✓ 쪽 읽기 · 1쪽</div><div class="ln" style="color:var(--ui-ink)">◐ 선·기호 추출</div><div class="ln muted">○ 태그 연결</div><div class="ln muted">○ 지식그래프 반영</div></div>
<div class="sec"><h4>▾ 같은 도면번호의 다른 개정<span class="n">0</span></h4><div class="muted">없음</div></div>"""
    return page("① 등록 · 진행·오류 상태", "1", "", [(True, "① 등록", False)],
                bar + '<div style="padding:10px 10px 0">%s</div>' % form.split('<div style="font-weight:700')[0].replace('<div class="form">', '') + lst,
                '<h3>속성 <span class="muted">· SNP-M-102.pdf</span></h3><div class="form" style="border:0">%s</div>' % (
                    '<div style="font-weight:700' + form.split('<div style="font-weight:700', 1)[1].rsplit("</div>", 1)[0]) + rel.split("</h3>", 1)[1], st)


def screen_empty():
    body = """<div class="bar"><span class="sel">SNP-M-102 ▾</span><span class="muted">구간 —</span></div>
<div class="empty"><div class="ic">▦</div><h2>이 도면의 검토구간이 아직 확정되지 않았습니다</h2>
<div>⑤ 분석은 확정된 구간마다 편차 44개를 채웁니다. 구간 10개가 제안 상태로 기다리고 있습니다.</div>
<div class="acts"><button class="btn pri">④ 검토구간 열기 <kbd>Ctrl+4</kbd></button><button class="btn">다른 도면 고르기</button></div>
<ol><li>④에서 제안된 구간을 확인합니다</li><li>"구간 확정"을 누릅니다</li><li>이 탭으로 돌아오면 행렬이 나타납니다</li></ol></div>"""
    rel = """<h3>관련 항목</h3><div class="sec"><div class="muted">행렬 칸을 고르면 도면 위치, 구성요소, 지식그래프 근거, 같은 구성요소를 쓰는 다른 칸이 여기에 모입니다.</div></div>"""
    st = status('<b>SNP-M-102</b><span>구간 미확정</span>', '<span><kbd>Ctrl+P</kbd> 명령</span><span><kbd>?</kbd> 단축키</span>')
    return page("⑤ 빈 상태", "5", "123", [(False, "④ 구간 · SNP-M-102", False), (True, "⑤ 결과 · SNP-M-102", False)], body, rel, st)


SCREENS = [("1-results-shell", "⑤ 결과 + 셸 전체", screen5), ("2-region-preview", "④ 구간 + 미리보기", screen4),
           ("3-command-palette", "명령 팔레트", screen_palette), ("4-register-progress-error", "① 진행·오류", screen1), ("5-results-empty", "⑤ 빈 상태", screen_empty)]


def build():
    for key, _, fn in SCREENS:
        (ROOT / ("%s.html" % key)).write_text(fn(), encoding="utf-8")
    btns = "".join('<button onclick="f.src=\'%s.html\'">%d. %s</button>' % (k, i + 1, t) for i, (k, t, _) in enumerate(SCREENS))
    keys = "".join("if(e.key=='%d')f.src='%s.html';" % (i + 1, k) for i, (k, _, _) in enumerate(SCREENS))
    (ROOT / "index.html").write_text("""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>UIUX 디테일 시안</title>
<style>body{margin:0;font:13px "%s",sans-serif;background:#23282f}nav{padding:6px;display:flex;gap:6px}button{font:inherit;padding:4px 10px}
iframe{border:0;width:1366px;height:768px;display:block;margin:0 auto;background:#fff}</style></head><body>
<nav>%s<span style="color:#aab2bd;margin-left:8px">키보드 1~%d로 전환 · 시안(구현물 아님) · 가상 데이터</span></nav>
<iframe id="f" src="%s.html"></iframe><script>const f=document.getElementById('f');addEventListener('keydown',e=>{%s});</script></body></html>""" % (
        FONT_FAMILY, btns, len(SCREENS), SCREENS[0][0], keys), encoding="utf-8")


def shoot():
    chrome = pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    prof = pathlib.Path.home() / "AppData/Local/Temp/hazop-uiux-shoot-profile"
    for key, _, _ in SCREENS:
        for w, h in ((1366, 768), (1920, 1080)):
            out = ROOT / "png" / ("%s-%d.png" % (key, w))
            out.parent.mkdir(exist_ok=True)
            subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--user-data-dir=%s" % prof,
                            "--force-device-scale-factor=1", "--window-size=%d,%d" % (w, h), "--virtual-time-budget=3000",
                            "--screenshot=%s" % out, (ROOT / ("%s.html" % key)).as_uri()], check=True, capture_output=True, timeout=120)
            print("saved", out.relative_to(ROOT))


if __name__ == "__main__":
    build()
    if "--shoot" in sys.argv:
        shoot()
