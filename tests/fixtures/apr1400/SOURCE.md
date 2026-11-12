# APR1400 DCD 시험 자료 출처

이 폴더의 PDF 쪽과 정답 파일은 미국 NRC에 제출된 APR1400 설계인증 DCD Rev.3(2018-08-13) Tier 2의 계통 흐름도에서 왔다.
NRC ADAMS로 누구나 받을 수 있는 공개 문서이며, 비공개 표시가 붙은 쪽은 없다.

- 출처 목록: https://www.nrc.gov/facilities-safety/new-reactors/large-light-water-reactors/design-certification-applications-for-new-reactors/apr1400/apr1400-design-control-document-and-environmental-report
- 원본 묶음: ML18228A648(1장) ~ ML18228A666(19장)
- 전체 143쪽은 저장소에 넣지 않는다(원본은 git 제외 `resources/references/APR1400_DCD/`). 검사는 `scripts/check_apr1400.py --input-dir <쪽별 폴더>`로 돈다.

## 정답 파일 (`answer_key/`)

PDF를 렌더한 그림에서 눈으로 읽어 만든 정답이다. 텍스트 층에서 센 대리 지표와 따로 만들었다.
처음 판(2026-11-09)은 Claude 시험 세션이 그림을 보고 만들었고, 다른 Claude 검토 에이전트가 겹쳐 본 그림으로 다시
확인했다. 사람 검토자는 아직 확인하지 않았다(확인하면 각 JSON의 `verified`에 이름과 날짜를 적는다).
뒤에 더한 항목도 사람 확인 전이다: `closed_valves`·`half_filled_valves`(2026-11-11 단위 F1-3), `valve_numbers`·`valve_positions`(2026-11-11 단위 F1-5, 012·062쪽, bbox는 2026-11-12에 그림 기준으로 채움). 각 항목의 `*_method`에 만든 방법을 적었다.
만든 방법·범위·한계는 각 JSON의 `method`·`scope`에 적었다. 다시 확인하려면
`python scripts/apr1400_key_overlay.py overlay <쪽.pdf> <정답.json> <출력.png>`로 정답 상자를 그림 위에 겹쳐 본다.

| 정답 파일 | 그림·시트 | 제목 | 원본 쪽 |
| --- | --- | --- | --- |
| `012_5.4.12-1-S1.json` | 5.4.12-1 | Reactor Coolant Gas Vent System Flow Diagram | ML18228A652.pdf 298 |
| `062_9.3.3-1-S7.json` | 9.3.3-1 시트 7 | Radioactive Drain System Flow Diagram | ML18228A656.pdf 433 |
| `063_9.3.4-1-S1.json` | 9.3.4-1 시트 1 | Chemical and Volume Control System Flow Diagram | ML18228A656.pdf 434 |
