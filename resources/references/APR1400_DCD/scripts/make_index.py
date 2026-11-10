"""drawing-list.csv에 국문 계통명 열을 넣고 drawing-list.md 색인을 만든다.

사용: python -E -P make_index.py <APR1400_DCD 폴더>
"""
import csv
import sys
from collections import OrderedDict
from pathlib import Path

KO = {
    "1.7-1": "흐름도 기호 및 범례",
    "5.1.1-1": "원자로냉각재계통(RCS) 개략 흐름도",
    "5.1.2-1": "원자로냉각재계통(RCS)",
    "5.1.2-2": "원자로냉각재펌프(RCP)",
    "5.1.2-3": "가압기 및 파일럿구동안전방출밸브(POSRV)",
    "5.4.1-2": "원자로냉각재펌프 축밀봉계통",
    "5.4.7-3": "정지냉각계통(SCS) - 정지냉각 운전",
    "5.4.12-1": "원자로냉각재 기체배기계통(RCGVS)",
    "6.2.2-1": "격납건물살수계통(CSS)",
    "6.3.1-1": "안전주입계통(SIS) 개략 흐름도",
    "6.3.2-1": "안전주입계통/정지냉각계통(SIS/SCS)",
    "6.4-2": "주제어실 공조계통(정상 운전)",
    "6.4-3": "주제어실 공조계통(비상 운전)",
    "6.4-4": "주제어실 공조계통(재순환 운전)",
    "6.8-3": "격납건물내부 저수계통(IWSS)",
    "9.1.3-1": "사용후연료저장조 냉각 및 정화계통",
    "9.2.1-1": "필수용수계통(ESWS)",
    "9.2.2-1": "기기냉각수계통(CCWS)",
    "9.2.4-1": "생활용수 및 위생계통",
    "9.2.5-1": "최종열제거원(냉각탑)",
    "9.2.6-1": "보충수 탈염계통",
    "9.2.6-2": "복수저장 및 이송계통",
    "9.2.7-1": "필수냉수계통(ECWS)",
    "9.2.7-2": "일반냉수계통(PCWS)",
    "9.2.8-1": "터빈건물 폐쇄냉각수계통",
    "9.2.9-1": "터빈건물 개방냉각수계통",
    "9.3.1-1": "계기용공기계통(IA)",
    "9.3.1-2": "소내용공기계통(SA)",
    "9.3.2-1": "공정 및 사고후 시료채취계통",
    "9.3.2-2": "공정 시료채취계통",
    "9.3.3-1": "방사성배수계통",
    "9.3.4-1": "화학 및 체적제어계통(CVCS)",
    "9.4.1-1": "주제어실 공조계통",
    "9.4.2-1": "핵연료취급지역 공조계통",
    "9.4.3-1": "보조건물 청정지역 공조계통",
    "9.4.4-1": "터빈건물 공조계통",
    "9.4.5-1": "비상디젤발전기실 공조계통",
    "9.4.5-2": "전기·계측제어기기실 공조계통",
    "9.4.5-3": "보조건물 방사선관리구역 공조계통",
    "9.4.6-1": "격납건물 공조계통",
    "9.4.6-2": "격납건물 배기(퍼지)계통",
    "9.4.7-1": "복합건물 공조계통",
    "9.5.1-1": "소방계통",
    "9.5.4-1": "디젤연료유 이송계통",
    "9.5.5-1": "비상디젤엔진 냉각수계통",
    "9.5.6-1": "비상디젤엔진 시동공기계통",
    "9.5.7-1": "비상디젤엔진 윤활유계통",
    "9.5.8-1": "비상디젤엔진 공기흡입 및 배기계통",
    "9.5.9-1": "가스터빈발전기 설비",
    "10.1-2": "증기 및 동력변환계통 전체 흐름도",
    "10.3.2-1": "주증기계통",
    "10.3.2-2": "터빈계통",
    "10.4.2-1": "복수기 진공계통",
    "10.4.3-1": "터빈 증기밀봉계통",
    "10.4.5-1": "순환수계통",
    "10.4.6-1": "복수탈염계통",
    "10.4.7-1": "복수 및 급수계통",
    "10.4.8-1": "증기발생기 취출계통",
    "10.4.9-1": "보조급수계통(AFWS)",
    "10.4.10-1": "보조증기계통",
    "11.2-1": "액체방사성폐기물계통",
    "11.3-1": "기체방사성폐기물계통",
    "11.4-1": "고체방사성폐기물계통",
}

CHAPTER_KO = {
    1: "1장 개요 및 발전소 일반 설명",
    5: "5장 원자로냉각재계통 및 연결계통",
    6: "6장 공학적안전설비",
    9: "9장 보조계통",
    10: "10장 증기 및 동력변환계통",
    11: "11장 방사성폐기물 관리",
}


def main(root):
    root = Path(root)
    path = root / "drawing-list.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    missing = sorted({r["그림번호"] for r in rows} - KO.keys())
    if missing:
        sys.exit(f"국문 계통명이 없는 그림: {missing}")
    cols = list(rows[0].keys())
    if "계통명" not in cols:
        cols.insert(cols.index("제목") + 1, "계통명")
    for r in rows:
        r["계통명"] = KO[r["그림번호"]]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    figs = OrderedDict()
    for r in rows:
        figs.setdefault(r["그림번호"], []).append(r)

    lines = [
        "# APR1400 DCD Rev.3 Tier 2 P&ID·계통 흐름도 목록",
        "",
        "미국 NRC에 제출된 APR1400 설계인증 DCD Rev.3(2018-08-13) Tier 2 1~19장에서 "
        "계통 흐름도(P&ID 형식) 쪽만 뽑았다. 도구 실험용 참고자료다.",
        "",
        f"- 그림 {len(figs)}개, {len(rows)}쪽. 도면이 실린 장은 1·5·6·9·10·11장이다.",
        "- 통합본: `APR1400_DCD_Rev3_PID_all.pdf` (그림마다 책갈피가 있다)",
        "- 쪽별 파일: `by-drawing/` 아래 `순번_장_그림번호_시트_영문제목.pdf`",
        "- 표 데이터: `drawing-list.csv` (원본 쪽, 통합본 쪽, 텍스트 문자 수 포함)",
        "- 제외한 도식: `excluded-drawings.csv` (계측 신호 흐름도, 기기 개략도, 통신계통도 등)",
        "- 원본: `source/ML18228A648.pdf`(1장) ~ `source/ML18228A666.pdf`(19장)",
        "- 모든 도면은 벡터로 되어 있어 기기 태그와 배관 번호를 텍스트로 뽑을 수 있다. "
        "다만 5.4.1-2 한 쪽은 이미지가 섞여 있다.",
        "- 공개본이라 상세 P&ID보다 단순하다. 비공개 표시가 붙은 도면 쪽은 없다.",
        "",
        "출처: https://www.nrc.gov/facilities-safety/new-reactors/large-light-water-reactors/"
        "design-certification-applications-for-new-reactors/apr1400/"
        "apr1400-design-control-document-and-environmental-report",
        "",
    ]
    cur = None
    for num, rs in figs.items():
        ch = int(rs[0]["장"])
        if ch != cur:
            cur = ch
            lines += ["", f"## {CHAPTER_KO.get(ch, f'{ch}장')}", "",
                      "| 그림 | 계통 | 원문 제목 | 시트 | 통합본 쪽 | 원본 쪽 |",
                      "| --- | --- | --- | --- | --- | --- |"]
        r0 = rs[0]
        pages = [int(r["통합PDF쪽"]) for r in rs]
        src = [int(r["원본쪽"]) for r in rs]
        span = lambda p: str(p[0]) if len(p) == 1 else f"{p[0]}–{p[-1]}"
        lines.append(
            f"| {num} | {KO[num]} | {r0['제목']} | {len(rs)} | {span(pages)} | "
            f"{r0['원본파일']} {span(src)} |"
        )
    lines += [
        "",
        "## 다시 만들기",
        "",
        "`scripts/extract_pid.py`로 원본에서 도면 쪽을 뽑고, "
        "`scripts/make_index.py`로 계통명과 이 문서를 만든다.",
        "",
        "```bash",
        "python -E -P scripts/extract_pid.py source .",
        "python -E -P scripts/make_index.py .",
        "```",
        "",
    ]
    (root / "drawing-list.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(figs)} figures, {len(rows)} pages")


if __name__ == "__main__":
    main(sys.argv[1])
