"""APR1400 DCD Rev.3 Tier 2 장별 PDF에서 P&ID·계통 흐름도 쪽만 골라낸다.

사용: python -E -P extract_pid.py <원본폴더> <출력폴더>
출력: <출력>/APR1400_DCD_Rev3_PID_전체.pdf (책갈피 포함)
      <출력>/도면별/*.pdf, <출력>/도면목록.csv, <출력>/후보_제외도면.csv
"""
import csv
import re
import sys
from pathlib import Path

import fitz

CHAPTERS = {f"ML18228A{648 + i}": i + 1 for i in range(19)}  # ML..648 = 1장 ... 666 = 19장

CAPTION = re.compile(
    r"^Figure\s+(\d+(?:\.\d+)*-\d+[A-Za-z]?)\s{2,}(\S.*)$", re.M
)
SHEET = re.compile(r"\((\d+)\s+of\s+(\d+)\)")
PID_KW = re.compile(r"flow\s+diagram|P\s*&\s*ID|piping\s+(and|&)\s+instrument", re.I)
OTHER_DIAGRAM_KW = re.compile(r"schematic|mode diagram|system diagram|flow path|piping diagram", re.I)
WITHHELD_KW = re.compile(r"withheld|security[- ]related information|proprietary", re.I)


def caption_of(page):
    """그림 쪽이면 (번호, 제목, 시트, 전체시트)를, 아니면 None을 돌려준다."""
    text = page.get_text()
    m = None
    for m in CAPTION.finditer(text):
        pass  # 쪽 아래쪽 캡션이 마지막 매치
    if not m:
        return None
    num = m.group(1)
    rest = text[m.end():].split("\n")[1:]
    title = m.group(2).strip()
    # 제목이 다음 줄로 이어지는 경우 ("Rev. 3" 또는 시트 표기 전까지)
    if "...." in title:  # 그림 목차 쪽
        return None
    for line in rest[:3]:
        s = line.strip()
        if (not s or s.startswith("Rev.") or SHEET.fullmatch(s)
                or s.upper().startswith("NOTE") or s.isupper()):
            if SHEET.fullmatch(s):
                title += " " + s
            break
        title += " " + s
    title = re.sub(r"\s+", " ", title).strip()
    sm = SHEET.search(title)
    sheet, total = (int(sm.group(1)), int(sm.group(2))) if sm else (1, 1)
    clean = SHEET.sub("", title).strip(" ;,")
    return num, clean, sheet, total, text


def section_titles(doc):
    out = {}
    for _lvl, t, _p in doc.get_toc():
        t = re.sub(r"\s+", " ", t).strip()
        m = re.match(r"(\d+(?:\.\d+)+)\s+(.*)", t)
        if m:
            out.setdefault(m.group(1), m.group(2))
    return out


def section_for(fig_num, sections):
    base = fig_num.split("-")[0]
    parts = base.split(".")
    while parts:
        key = ".".join(parts)
        if key in sections:
            return key, sections[key]
        parts.pop()
    return base, ""


def slug(s, n=60):
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:n].rstrip("_")


def main(src_dir, out_dir):
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    per_dir = out_dir / "도면별"
    per_dir.mkdir(parents=True, exist_ok=True)
    rows, others = [], []
    for ml, ch in sorted(CHAPTERS.items(), key=lambda kv: kv[1]):
        f = src_dir / f"{ml}.pdf"
        if not f.exists():
            print(f"[누락] {ch}장 {f.name}")
            continue
        doc = fitz.open(f)
        sections = section_titles(doc)
        found = 0
        for i, page in enumerate(doc):
            cap = caption_of(page)
            if not cap:
                continue
            num, title, sheet, total, text = cap
            # 목차(List of Figures) 쪽은 점선 지시자가 있어 제외
            if "....." in text[:4000] and text.count("Figure ") > 4:
                continue
            sec, sec_title = section_for(num, sections)
            rec = {
                "장": ch,
                "그림번호": num,
                "시트": sheet,
                "전체시트": total,
                "제목": title,
                "절번호": sec,
                "절제목": sec_title,
                "원본파일": f.name,
                "원본쪽": i + 1,
                "비공개표시": "예" if WITHHELD_KW.search(text) else "",
                "텍스트문자수": len(text.strip()),
                "이미지수": len(page.get_images()),
            }
            # 7장 계측 채널 "Flow Diagram"은 신호 흐름도라 P&ID가 아니다
            if PID_KW.search(title) and not re.search(r"\bchannel\b", title, re.I):
                rows.append((rec, doc, i))
                found += 1
            elif OTHER_DIAGRAM_KW.search(title) or PID_KW.search(title):
                others.append(rec)
        print(f"{ch:>2}장 {f.name}: {doc.page_count}쪽, 도면 {found}쪽")

    combined = fitz.open()
    toc = []
    out_rows = []
    for n, (rec, doc, i) in enumerate(rows, 1):
        combined.insert_pdf(doc, from_page=i, to_page=i)
        label = f"Fig {rec['그림번호']} {rec['제목']}"
        if rec["전체시트"] > 1:
            label += f" ({rec['시트']}/{rec['전체시트']})"
        toc.append([1, label, combined.page_count])
        sheet = f"_s{rec['시트']}of{rec['전체시트']}" if rec["전체시트"] > 1 else ""
        name = f"{n:03d}_Ch{rec['장']:02d}_Fig{rec['그림번호']}{sheet}_{slug(rec['제목'])}.pdf"
        single = fitz.open()
        single.insert_pdf(doc, from_page=i, to_page=i)
        single.save(per_dir / name, garbage=3, deflate=True)
        out_rows.append({"순번": n, **rec, "통합PDF쪽": combined.page_count, "개별파일": name})
    combined.set_toc(toc)
    combined.save(out_dir / "APR1400_DCD_Rev3_PID_전체.pdf", garbage=3, deflate=True)

    cols = ["순번", "장", "그림번호", "시트", "전체시트", "제목", "절번호", "절제목",
            "원본파일", "원본쪽", "통합PDF쪽", "개별파일", "비공개표시", "텍스트문자수", "이미지수"]
    with open(out_dir / "도면목록.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)
    ocols = [c for c in cols if c not in ("순번", "통합PDF쪽", "개별파일")]
    with open(out_dir / "후보_제외도면.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=ocols)
        w.writeheader()
        w.writerows(others)
    print(f"합계: 도면 {len(out_rows)}쪽, 제외 후보 {len(others)}쪽")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
