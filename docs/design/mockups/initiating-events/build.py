"""⑥ 초기사건 화면 시안 생성. 근거: specs/ie-output-design.md §7.

B안 셸 CSS는 design/mockups/final/b-dense-workbench/5-summary-matrix.html의 <style>을 그대로 읽어 쓴다(셸 모양을 맞추려고).
데이터는 모두 가상 예시다. 실행: python build.py → 6-groups.html, 6-completeness-check.html, PNG 1366·1920.
"""

import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
BASE = ROOT.parent / "final" / "b-dense-workbench" / "5-summary-matrix.html"
ENTRY_AT = "20261108T061000Z"

EXTRA_CSS = """
.body.ie{grid-template-columns:minmax(0,1fr) clamp(290px,24vw,380px)}
ul.tree li .ex-n{overflow:hidden;text-overflow:ellipsis;min-width:0}
ul.tree li .chip{flex-shrink:0;margin-left:auto;font-size:10.5px;padding:0 5px}
.def{display:grid;grid-template-columns:96px 1fr;gap:4px 10px;font-size:var(--fs)}
.def .k{color:var(--muted)}
.ai-box{background:repeating-linear-gradient(135deg,var(--ai-a) 0 5px,var(--ai-b) 5px 10px);border:1px dashed var(--ai-line);border-radius:var(--radius);padding:6px 8px}
.hum-box{background:var(--surface);border:1.5px solid var(--ink);border-radius:var(--radius);padding:6px 8px}
.act{display:inline-block;font-size:10.5px;padding:0 5px;border-radius:3px;border:1px solid var(--line-strong)}
.act.auto{background:var(--surface)} .act.op{background:var(--warn-bg);border-color:var(--warn-line);color:var(--warn-ink)}
.note{font-size:var(--fs-sm);color:var(--muted)}
.trace{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}
.trace li{position:relative;padding:4px 0 8px 18px;border-left:2px solid var(--line);margin-left:6px}
.trace li::before{content:"";position:absolute;left:-6px;top:7px;width:10px;height:10px;border-radius:50%;background:var(--surface);border:2px solid var(--line-strong)}
.trace li:last-child{border-left-color:transparent}
.trace .tk{font-size:var(--fs-sm);color:var(--muted);display:block}
.trace .tv{font-weight:600}
.trace .tid{font-family:var(--mono);font-size:var(--fs-sm);color:var(--muted);word-break:break-all}
.cov td.gap{background:var(--warn-bg);color:var(--warn-ink);font-weight:600}
.cov td.na{color:var(--muted)}
.cov td.hit{color:var(--ok);font-weight:600}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:var(--fs-sm);color:var(--muted);align-items:center}
.banner{background:var(--warn-bg);border:1px solid var(--warn-line);color:var(--warn-ink);border-radius:var(--radius);padding:6px 10px;font-size:var(--fs-sm)}
"""

RAIL = [("1", "등록"), ("2", "추출"), ("3", "그래프"), ("4", "구간"), ("5", "결과"), ("6", "초기사건")]
TABS = ("후보 17", "그룹 6", "사건수목 표제 9", "최종상태 4", "기본사건 23", "완전성 대조", "품질 경고 5")

# (그룹 ID, 이름, 일반 범주, 상태 글자, 칩 종류)
GROUPS = [("IEG-01", "주급수 상실", "일반 범주 LOMFW", "확정", "appr"),
          ("IEG-02", "소형 LOCA(가압기 증기공간)", "일반 범주 SLOCA · SORV", "초안", "ai"),
          ("IEG-03", "일반 과도사건", "일반 범주 TRANS", "초안", "edit"),
          ("IEG-04", "기기냉각수 상실", "일반 범주 LOCCW · 지원계통", "초안", "ai"),
          ("IEG-05", "가압기 압력 제어 고장", "플랜트 고유", "보류", "warn"),
          ("IEG-06", "증기발생기 전열관 파단", "일반 범주 SGTR", "확정", "appr")]


def shell(title, explorer, tab_on, page):
    css = BASE.read_text(encoding="utf-8")
    css = css[css.find("<style>") + 7:css.find("</style>")]
    rail = "".join('<a class="rail-i%s" aria-label="%s"><b>%s</b><span>%s</span></a>'
                   % (" on" if n == "6" else "", t, n, t) for n, t in RAIL)
    tabs = "".join('<span class="tab%s">%s</span>' % (" on" if t == tab_on else "", t) for t in TABS)
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>%s</title><style>%s%s</style></head>"
            "<body><div class=\"app shell-b\"><header class=\"titlebar\"><b class=\"logo\">HAZOP</b>"
            "<span class=\"menu\">파일</span><span class=\"menu\">편집</span><span class=\"menu\">보기</span>"
            "<span class=\"menu\">도움말</span><span class=\"crumb\">가상 PWR 예시 / 초기사건</span>"
            "<span class=\"user\">검토자 김OO</span></header><nav class=\"rail\" aria-label=\"단계\">%s</nav>"
            "<aside class=\"explorer\">%s</aside><section class=\"work\"><div class=\"tabs\">%s</div>"
            "<main class=\"main\">%s</main></section><footer class=\"statusbar\">"
            "<span class=\"chip ok\">추적 경로 검증 통과 — 완전성을 뜻하지 않음</span><span>최근 저장 15:10 KST</span>"
            "<span class=\"sb-r\">가상 예시 데이터 · 실제 설계값 아님 · 빈도는 다루지 않음</span></footer></div></body></html>"
            % (title, css, EXTRA_CSS, rail, explorer, tabs, page))


def explorer(selected):
    items = "".join('<li class="%s" title="%s · %s"><span class="ex-n">%s %s</span><span class="chip %s">%s</span></li>'
                    % ("on" if g == selected else "", n, c, g, n, k, s) for g, n, c, s, k in GROUPS)
    return ('<div class="ex-h">탐색기</div><ul class="tree"><li class="grp">초기사건 그룹 6</li>' + items +
            '<li class="warn-t">미배정 후보 1</li>'
            '<li class="grp">판정 대기</li><li>보류 4 · 사람 판정 필요</li><li>AI 초안 미검토 6</li>'
            '<li class="grp">완전성 대조</li><li class="warn-t">공백 범주 9</li>'
            '<li class="grp">내보내기</li><li>IE 인계 묶음(Excel·JSON)</li><li>PRA 도구용 CSV</li></ul>')


HEAD = """<div class="page-head"><div class="ph-txt"><h1>⑥ 초기사건 후보·그룹</h1>
<div class="sub">⑤에서 승인한 원인을 초기사건 후보로 판정하고 PRA 초기사건 그룹으로 묶습니다. 빈도 산정과 정량화는 PRA 도구에서 합니다</div></div>
<div class="acts"><button class="btn">완전성 대조</button><button class="btn primary">IE 인계 묶음 내보내기</button></div></div>
<div class="kpis"><div class="kpi"><span class="kpi-l">승인된 원인</span><span class="kpi-v">42</span></div>
<div class="kpi"><span class="kpi-l">IE 후보</span><span class="kpi-v">17</span></div>
<div class="kpi"><span class="kpi-l">제외(사유 기록)</span><span class="kpi-v">21</span></div>
<div class="kpi warn"><span class="kpi-l">보류</span><span class="kpi-v">4</span></div>
<div class="kpi"><span class="kpi-l">그룹</span><span class="kpi-v">6</span></div>
<div class="kpi warn"><span class="kpi-l">대조 공백 범주</span><span class="kpi-v">9</span></div></div>"""


def group_page():
    members = [("IEC-004", "주급수펌프 FW-P01A 정지", "S12 · 유량 없음", "FW-P01A", "기기 고장", "appr", "승인"),
               ("IEC-005", "주급수 조절밸브 FCV-478 닫힘 방향 오동작", "S12 · 유량 적음", "FCV-478", "기기 고장", "appr", "승인"),
               ("IEC-009", "급수 가열기 출구 차단밸브 오조작 닫힘", "S13 · 유량 없음", "MV-0312", "운전원 오조작", "edit", "수정"),
               ("IEC-014", "복수펌프 CD-P02 전원 상실로 정지", "S14 · 유량 적음", "CD-P02", "지원계통 상실", "edit", "수정")]
    mrows = "".join("<tr><td class=mono>%s</td><td>%s</td><td>%s</td><td class=mono>%s</td><td>%s</td>"
                    "<td><span class=\"chip %s\">%s</span></td></tr>" % m for m in members)
    heads = [("H-01", "원자로 정지", "RPS 급수 유량 낮음·SG 수위 낮음 신호", "auto", "자동"),
             ("H-02", "보조급수 기동", "MDAFW·TDAFW 자동 기동", "auto", "자동"),
             ("H-03", "운전원 급수 회복", "주제어실 경보 → 비정상절차서", "op", "운전원"),
             ("H-04", "가압기 압력 방출", "PORV 압력 신호 개방 · 안전밸브 RV-8010", "auto", "자동 · 자체작동"),
             ("H-05", "급수·방출 운전", "운전원 PORV 개방 + 안전주입", "op", "운전원")]
    hrows = "".join('<tr><td class=mono>%s</td><td>%s</td><td>%s</td><td><span class="act %s">%s</span></td>'
                    '<td><span class="chip appr">사람</span></td></tr>' % h for h in heads)
    center = """<section class="panel"><div class="panel-h"><span class="ph-t">IEG-01 주급수 상실</span>
<span class="chip appr">확정 · 검토자 김OO</span><span class="ph-r"><button class="btn sm">그룹 나누기</button><button class="btn sm">후보 옮기기</button></span></div>
<div class="panel-b"><div class="hum-box def"><span class="k">정의</span><span>주급수 유량이 전부 끊겨 증기발생기 2차측 열제거가 줄고 원자로가 정지하는 사건(가상 예시 정의)</span>
<span class="k">일반 범주</span><span><b>LOMFW</b> 주급수 완전 상실 <span class="muted">· 출처 INL 2015 IE 범주(§6.1 기준표)</span></span>
<span class="k">대표 원인</span><span>IEC-004 주급수펌프 FW-P01A 정지 <span class="muted">· 응답이 가장 빠름</span></span>
<span class="k">플랜트 응답</span><span>원자로 자동 정지, 터빈 정지, 보조급수 자동 기동 요구</span>
<span class="k">완화계통</span><span>보조급수계통, 가압기 압력 방출, 안전주입(급수·방출 운전 때)</span>
<span class="k">빈도 근거</span><span class="muted">앱에서 다루지 않음 — PRA 담당 기입 칸</span></div>
<div class="sub-h">소속 후보 4 <span class="muted">원인 단위 · ⑤ 승인 항목에서 파생 · 모두 사람 확정이라 그룹 확정 가능</span></div>
<table class="t"><thead><tr><th>후보</th><th>원인</th><th>구간 · 편차</th><th>위치</th><th>원인 유형</th><th>상태</th></tr></thead><tbody>%s</tbody></table>
<div class="sub-h">사건수목 표제 후보 5 <span class="muted">⑤ 보호수단에서 모음 · 순서·분기·성공기준은 PRA 담당이 정함</span></div>
<table class="t"><thead><tr><th>표제</th><th>이름(제안)</th><th>구현 대상</th><th>작동 방식</th><th>작성</th></tr></thead><tbody>%s</tbody></table>
<div class="note">최종상태 후보: ES-03 노심 냉각 위협(비완화 결과). 성공 쪽 최종상태는 PRA 담당이 정합니다</div>
</div></section>""" % (mrows, hrows)
    right = """<section class="panel"><div class="panel-h"><span class="ph-t">추적 · IEC-004</span><span class="ph-r"><span class="chip appr">승인</span></span></div>
<div class="panel-b"><ul class="trace">
<li><span class="tk">편차</span><span class="tv">유량 없음</span> <span class="tid">S12 · D01</span></li>
<li><span class="tk">원인(⑤ 승인)</span><span class="tv">주급수펌프 FW-P01A 정지</span> <span class="tid">S12-D01-%s-2</span></li>
<li><span class="tk">원인 위치 · 고장모드</span><span class="tv">FW-P01A · FTR(운전 중 정지)</span> <span class="tid">graph-SNP-F-201#obj-88</span></li>
<li><span class="tk">IE 판정</span><span class="tv">정상운전 교란 예 · 안전기능 도전 예(2차측 열제거)</span></li>
<li><span class="tk">초기사건 그룹</span><span class="tv">IEG-01 주급수 상실</span> <span class="tid">LOMFW</span></li>
<li><span class="tk">비완화 결과 → 최종상태 후보</span><span class="tv">SG 수위 저하 → 열제거 상실</span> <span class="tid">ES-03</span></li>
</ul>
<div class="sub-h">근거 경로 <span class="muted">지식그래프 · 출처 문서</span></div>
<div class="path"><span class="pn">FW-P01A</span><span class="pe">물리</span><span class="pn">FCV-478</span><span class="pe">물리</span><span class="pn sel">SG-A</span></div>
<ul class="links docs"><li><b>주급수 계통설명서 §3.2</b><span class="muted">DOC-0011 · 14쪽(가상)</span></li></ul>
<div class="sub-h">기본사건 후보 <span class="muted">PRA 이름 칸은 비워 둠</span></div>
<table class="t"><thead><tr><th>앱 제안 이름</th><th>고장모드</th></tr></thead><tbody>
<tr><td class=mono>FW-MDP-FTR-P01A</td><td>운전 중 정지</td></tr><tr><td class=mono>FW-MDP-FTS-P01B</td><td>대기 펌프 기동 실패</td></tr>
<tr><td class=mono>FW-AOV-SO-FCV478</td><td>닫힘 방향 오동작</td></tr></tbody></table>
<div class="actions"><button class="btn primary sm">후보 확정</button><button class="btn sm">제외(사유)</button><button class="btn sm">보류</button></div>
</div></section>""" % ENTRY_AT
    return HEAD + '<div class="body ie">%s%s</div>' % (center, right)


# (코드, 이름, 대응 그룹, 후보 수, 상태 hit|gap|na, 메모)
COVERAGE = [
    ("TRANS", "일반 과도사건", "IEG-03", 5, "hit", ""),
    ("LOMFW", "주급수 완전 상실", "IEG-01", 4, "hit", ""),
    ("LOCHS", "복수기 열제거원 상실", "", 0, "gap", "복수기·순환수 도면 미등록 — 검토 범위 밖일 수 있음"),
    ("LOOP", "외부전원 상실(소내·개폐소·전력망·기상 기인)", "", 0, "gap", "전력계통은 P&ID HAZOP으로 찾기 어려움 — 다른 기법"),
    ("LOAC", "필수 교류 모선 상실", "", 0, "gap", "전기 계통 FMEA 필요"),
    ("LODC", "필수 직류 모선 상실", "", 0, "gap", "전기 계통 FMEA 필요"),
    ("LOCCW", "기기냉각수 완전 상실", "IEG-04", 2, "hit", "지원계통 초기사건"),
    ("LOESW", "비상 사용수 완전 상실", "", 0, "gap", "사용수 계통 도면 미등록"),
    ("LOIA", "계기용 공기 완전 상실", "(미배정)", 1, "gap", "IEC-031 배정 대기"),
    ("SGTR", "증기발생기 전열관 파단", "IEG-06", 1, "hit", ""),
    ("SLOCA", "소형 냉각재상실사고", "IEG-02", 2, "hit", ""),
    ("MLOCA", "중형 냉각재상실사고", "", 0, "gap", "배관 파단 크기는 HAZOP 원인으로 잘 안 나옴"),
    ("LLOCA", "대형 냉각재상실사고", "", 0, "gap", "같은 사유"),
    ("ISLOCA", "연계계통 냉각재상실사고", "", 0, "gap", "경계 밸브 구간이 검토구간에 있는지 확인"),
    ("SORV", "안전·방출밸브 열림 고착", "IEG-02", 1, "hit", "SLOCA와 같은 그룹으로 묶음"),
    ("SLBOC", "격납건물 밖 증기관 파단", "", 0, "na", "가상 예시: 주증기 계통 이번 범위 밖(사유 기록)"),
]


def coverage_page():
    rows = "".join('<tr><td class=mono>%s</td><td>%s</td><td class=mono>%s</td><td>%s</td><td class="%s">%s</td><td>%s</td></tr>'
                   % (code, name, grp or "—", n or "—", st, {"hit": "대응 있음", "gap": "공백", "na": "해당 없음"}[st], memo)
                   for code, name, grp, n, st, memo in COVERAGE)
    n = {k: sum(1 for c in COVERAGE if c[4] == k) for k in ("hit", "gap", "na")}
    counts = "대응 있음 %d · 공백 %d · 해당 없음 %d (가상 예시 일부 범주만 보임)" % (n["hit"], n["gap"], n["na"])
    center = """<section class="panel"><div class="panel-h"><span class="ph-t">완전성 대조 · 경수로 일반 초기사건 범주</span>
<span class="chip neutral">기준표 INL 2015 IE 범주(§6.1) · 가상 예시 일부</span><span class="ph-r"><button class="btn sm">기준표 바꾸기</button></span></div>
<div class="panel-b"><div class="banner">공백은 "HAZOP이 이 범주의 후보를 내지 않았다"는 뜻입니다. 사건이 없다는 뜻이 아니며, 앱이 초기사건을 대신 만들지 않습니다. 공백마다 다른 기법(FMEA·운전경험·MLD) 확인이나 범위 밖 사유를 적어 주십시오.</div>
<table class="t cov"><thead><tr><th>범주 코드</th><th>범주 이름</th><th>대응 그룹</th><th>후보</th><th>상태</th><th>메모(사유)</th></tr></thead><tbody>%s</tbody></table>
<div class="legend"><span>%s</span></div></div></section>""" % (rows, counts)
    right = """<section class="panel"><div class="panel-h"><span class="ph-t">공백 · LOCHS 복수기 열제거원 상실</span></div>
<div class="panel-b"><div class="def"><span class="k">왜 공백인가</span><span>대응하는 후보 0. 복수기·순환수 계통 도면이 등록되지 않아 검토구간이 없음</span>
<span class="k">가능한 처리</span><span>① 도면 등록 후 HAZOP ② 계통 FMEA로 확인 ③ 범위 밖 사유 기록</span></div>
<div class="sub-h">사람 판정</div><div class="hum-box">
<label><input type="radio" checked> 범위 밖(사유 기록)</label><br><label><input type="radio"> 다른 기법으로 확인 예정</label><br><label><input type="radio"> 해당 없음(설계 특성)</label>
<div class="note" style="margin-top:6px">사유: 2차측 복수 계통은 이번 HAZOP 범위가 아님. PRA 담당이 일반 자료로 다룸(가상)</div></div>
<div class="sub-h">이 범주로 갈 만한 후보 <span class="muted">규칙·AI 제안</span></div>
<div class="ai-box note">없음. 규칙: 복수기 진공·순환수 유량 편차 원인 → LOCHS. 검토구간에 복수기 구성요소가 없어 규칙이 걸리지 않음</div>
</div></section>"""
    return HEAD + '<div class="body ie">%s%s</div>' % (center, right)


def shoot(name):
    chrome = pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    for w, h in ((1366, 768), (1920, 1080)):
        out = ROOT / ("%s-%d.png" % (name, w))
        with tempfile.TemporaryDirectory() as prof:
            subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--user-data-dir=%s" % prof, "--window-size=%d,%d" % (w, h),
                            "--screenshot=%s" % out, (ROOT / ("%s.html" % name)).as_uri()],
                           check=True, capture_output=True, timeout=120)


if __name__ == "__main__":
    for name, page, tab, sel in (("6-groups", group_page(), "그룹 6", "IEG-01"),
                                 ("6-completeness-check", coverage_page(), "완전성 대조", None)):
        (ROOT / ("%s.html" % name)).write_text(shell("⑥ 초기사건 · " + tab, explorer(sel), tab, page), encoding="utf-8")
        shoot(name)
