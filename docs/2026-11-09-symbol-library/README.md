# P&ID 기호 목록 초안 (APR1400, 2026-11-09)

[설계서](../../specs/pid-symbol-dictionary.md)의 1단계 산출물이다. 사전에 넣기 전의 후보 목록이며, 짝 검수와 국내 용어는 사람이 확정한다.

## 출처

- U.S. NRC, APR1400 Design Control Document Tier 2 Rev.3(2018-08-13), Figure 1.7-1 "Flow Diagram Symbols and Legend" 1~4/4(DCD 1.7-9~1.7-12쪽, 원본 `ML18228A648.pdf`).
- 같은 DCD 1·5·6·9·10·11장의 계통 흐름도 139쪽(목록: `자원/참고자료/APR1400_DCD/도면목록.md`).
- NRC 공개 자료다. 여기 그림은 원본 PDF에서 잘라 축소한 것이다.
- 공개 페이지: https://www.nrc.gov/facilities-safety/new-reactors/large-light-water-reactors/design-certification-applications-for-new-reactors/apr1400/apr1400-design-control-document-and-environmental-report

## 파일

| 파일 | 내용 |
| --- | --- |
| `legend-items.csv` | 범례 4쪽에서 기호와 오른쪽 설명을 자동으로 짝지은 239개 항목. 범례 쪽, 구획(EQUIPMENT SYMBOLS 등), 원문, 국내 용어 초안(209개), 짝 검수, 지금 추출기 kind, 위치(pt), 그림 |
| `drawing-unclassified-groups.csv` | 실제 도면 139쪽에서 지금 추출기(HEAD 0a0b9e9 + U1)가 kind를 못 정한 기호 11,572개를 모양별로 묶은 1,139묶음 중 상위 60개. 사전 항목 대응과 확신도 |
| `dictionary-items-prototype.csv` | 시제품 사전 21항목(기호 20 + 버림 1). 원문, 국내 용어, 범주, 앱 kind, 범례 위치, 시험 쪽 매칭 수 |
| `figures/legend/L*.png` | 범례 항목마다 잘라 낸 기호(긴 변 160px 이하) |
| `figures/drawings/c*.png` | 미분류 묶음마다 서로 다른 쪽에서 고른 예시 8개(빨간 테가 추출기가 묶은 기호 상자) |

## 숫자로 본 범례

| 시트 | 쪽 | 추출기가 묶은 기호 | 설명과 짝지은 항목 | 짝 못 지은 기호 |
| --- | --- | --- | --- | --- |
| 1/4 | 1.7-9 | 258 | 177 | 35 |
| 2/4 | 1.7-10 | 68 | 47 | 7 |
| 3/4 | 1.7-11 | 23 | 15 | 7 |
| 4/4 | 1.7-12 | 1 | 0 | 1 |

- 4/4쪽은 계기 표기 예시와 신호선 종류라서 닫힌 기호가 거의 없다. 선 종류(공압·전기·유압 신호, 모세관)는 기호 사전이 아니라 선 규칙의 몫이다.
- 3/4쪽 대부분은 계기 문자 코드표와 계통 약어표다. 이 표는 기호가 아니라 글자 규칙(`hazop/extract/isa.py`)과 계통 약어 사전으로 간다.
- 짝 검수는 L1-001~L1-080만 눈으로 했다. 80개 중 70개가 맞았다. 틀린 10개는 설명이 기호 아래 캡션에 붙거나(L1-001 CANNED 펌프에 WET PIT), 머리글을 설명으로 읽은 경우(L1-033·034)다. 나머지 159개는 미검수다.

## 범례와 실제 도면의 대응

미분류 상위 묶음과 범례의 대응은 `drawing-unclassified-groups.csv`의 `사전 항목` 열에 있다. 요약하면 다음과 같다.

- **범례에 있는 기호.** 도면 간 배관 연결 깃발(810개, 미분류 1위), 게이트·글로브·플러그 밸브, 동심 리듀서, 상자형 체크 밸브, 공유 HSI 표시, 제어 장치 상자, 전동·솔레노이드·다이어프램·전기유압 구동부, 기기 배수(DE/ED), 시험 연결, 상시 열림·닫힘 댐퍼, 같은 도면 안 연결 문자.
- **범례에 없거나 다르게 그린 기호.** 밸브 번호 타원(범례는 원만 보임), 비석형 계기 안의 가로 칸막이, 탱크 무늬 점(크기 0 도형, 버림), 네모 안 X 밸브(c021·c056, 이름 미확인), 네모 안 사선 화살 밸브(c022·c047, 이름 미확인).
- **범례에서 닫힌 상태를 검게 칠한 밸브.** 범례 VALVE SYMBOLS는 같은 밸브를 "정상 운전 중 열림(흰색)"과 "닫힘(검정)" 두 열로 그린다. 검게 칠한 게이트 밸브는 6×3pt라 추출기가 화살촉(표식)으로 읽고 기호로 만들지 않는다. 설계서 §2.3 참고.

## 사전(`자원/기준/기호/`)을 만든 방법

1단계 구현(2026-11-09)에서 시제품 라벨을 저장소 도구로 옮겨 사전을 만들었다.

1. HEAD 4674340(U1·U2 포함) 추출기로 005~143쪽 미분류를 묶었다. 기호 14,770개 중 미분류 10,417개, 1,051묶음.
   ```
   python scripts/symbols/cluster_unclassified.py --set APR1400 --input-dir <도면별> --pages 5-143 --no-library
   ```
2. 시제품 라벨(33묶음)을 (쪽, 기호 상자)로 이어 새 묶음 순위에 옮겼다. 구성원 80% 이상이 같은 라벨인 33묶음, 4,930개 기호, 21항목. 결과가 `labels-apr1400.csv`다.
3. 항목 이름·범주·역할·kind는 `item-info.csv`에서 읽어 사전을 만들었다. 같은 입력으로 다시 돌리면 바뀌는 항목이 없다.
   ```
   python scripts/symbols/add_symbols.py --set APR1400 --labels labels-apr1400.csv --meta item-info.csv --input-dir <도면별> --source-note "APR1400 DCD Rev.3"
   python scripts/check_symbols.py
   ```

홀수 쪽 표본만으로 만든 사전을 짝수 쪽(69쪽, 미분류 5,091개)에 대 보니 켜진 항목에 1,945개가 맞았고 애매함은 0이었다. 기존 kind로 정해지는 것이 1,312개(25.8%), ISA 글자에 맡기는 계기 모양 351개, 밸브 속성이 될 구동부 282개다. 밸브 번호 원·댐퍼·시험 연결은 레지스트리에 kind가 들어가기 전이라 꺼져 있다(`enabled: false`).

검토(적대 검토 2, Codex 1)에서 글자 없는 상자·'G' 상자가 솔레노이드로, 구역 표시 상자('055-A34A')가 같은 도면 연결 문자로 맞는 것이 드러났다. 그래서 솔레노이드(`^S$`), 연결 문자(영문 한두 자), 전동(`^M$`), 전기유압(E/H), 제어 장치(영문 1~5자)에 상자 안 글자 조건을 붙였다. 붙이기 전 1,984개에서 39개가 줄었다(솔레노이드 110→79, 연결 문자 106→99).

## 다시 만들기(시제품)

시험 폴더 `C:\Users\kim92\HAZOP-trials\symbols-2026-11-09\`의 스크립트로 이 폴더 전체를 다시 만든다.

```
python -I scan_pages.py --jobs 8
python -I harvest_legend.py
python -I cluster_none.py --top 60
python -I match_eval.py
python -I build_docs.py --dst <이 폴더>
```
