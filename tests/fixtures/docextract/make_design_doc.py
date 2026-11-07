"""가상(fictitious) 설계 문서 PDF 생성기 — 문서 지식 추출기(hazop/kg/docextract.py) 시험용.

문장과 값은 모두 가상이며 실제 발전소 설계자료가 아니다. 태그는 샘플 도면 SNP-M-102(가상)의 태그를 쓴다.
Qt(QPdfWriter + QTextDocument)로 글자가 들어 있는 PDF를 만든다(이미지 없음). 패키지 설치 없이 전용 venv에서 실행:
  <전용 venv python> tests/fixtures/docextract/make_design_doc.py
결과: 같은 폴더의 SNP-DOC-102_가압기압력제어_설계설명서(가상).pdf (3쪽)
"""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "windows"  # offscreen 플랫폼에는 글꼴이 없어 PDF에 글자가 들어가지 않음

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QFont, QGuiApplication, QPageLayout, QPageSize, QPdfWriter, QTextDocument

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "SNP-DOC-102_가압기압력제어_설계설명서(가상).pdf")

PAGES = [
    """<h2>가압기 압력제어 계통 설계 설명서 (가상)</h2>
<p>문서번호 SNP-DOC-102 · 개정 0 · 가상(fictitious) 문서 — 실제 발전소 설계값이 아님</p>
<h3>1. 설계 의도</h3>
<p>가압기 압력제어 계통의 설계 의도는 원자로냉각재계통 압력을 정상 운전 범위 안에 유지하는 것이다.</p>
<p>대상 도면은 SNP-M-102(가상)이다.</p>
<h3>2. 운전조건</h3>
<p>가압기 정상 운전압력은 15.5 MPa(a)이다.</p>
<p>가압기 설계압력은 17.2 MPa(g)이다.</p>
<p>가압기 정상 운전온도는 345 °C이다.</p>""",
    """<h3>3. 설정치</h3>
<p>압력제어기 RC-PIC110의 고압 경보 설정치는 16.2 MPa(a)이다.</p>
<p>가압기 고압 트립 설정치는 16.6 MPa이다.</p>
<p>안전밸브 RC-PSV101의 설정압력은 17.2 MPa(g)이다.</p>""",
    """<h3>4. 요건</h3>
<p>가압기 압력이 높아지면 압력제어기 RC-PIC110이 압력제어밸브 RC-PV101을 연다.</p>
<p>RC-PV101은 계기용 공기 상실 시 닫힘 위치로 가야 한다.</p>
<p>가압기 수위 전송기 RC-LT110의 신호가 상실되면 운전원에게 경보를 주어야 한다.</p>""",
]


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 (글꼴 사용에 필요)
    w = QPdfWriter(OUT)
    w.setPageSize(QPageSize(QPageSize.A4))
    w.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Millimeter)
    w.setResolution(300)
    w.setTitle("SNP-DOC-102 가압기 압력제어 계통 설계 설명서 (가상)")
    w.setCreator("hazop tests/fixtures/docextract/make_design_doc.py")
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Malgun Gothic", 11))
    doc.setHtml("".join(html if i == 0 else '<div style="page-break-before: always">%s</div>' % html
                        for i, html in enumerate(PAGES)))
    doc.print_(w)
    print(OUT)


if __name__ == "__main__":
    main()
