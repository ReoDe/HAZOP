# 정답지 사용자 확인 목록 (D-read/R1, 2026-11-13)

APR1400 정답지 12쪽에서 쪽마다 20건을 무작위로 뽑은 목록입니다. 정답지는 Claude 하위 에이전트 둘이 쪽 그림만 보고 따로 쓰고, 어긋난 항목을 셋째 에이전트가 그림으로 판정한 최종본입니다(두 판의 일치율은 [answer-key-agreement.md](answer-key-agreement.md)). 아직 사람이 확인하지 않았습니다. 이 확인은 정답지 채택을 막지 않는 나중 확인입니다(총괄 지시 2026-11-13). 절차는 [`docs/specs/extraction.md`](../../../specs/extraction.md#answer-key-procedure) '정답지 절차'입니다.

## 확인하는 법

1. 그림 조각을 엽니다. 빨간 네모가 그 항목의 자리입니다. 조각은 저장소 밖 `D:\HAZOP-trials\2026-11-13-answer-key\sample-final\crops\`에 있습니다. 주변이 더 필요하면 같은 폴더의 `tiles\<순번>\overview.png`(쪽 전체, 100pt 격자)를 봅니다.
2. '정답 값'이 그림과 맞으면 '확인' 칸에 `맞음`, 다르면 `틀림: 바른 값`을 적습니다.
   - 기호 종류: 이름 뒤에 태그가 붙어 있으면 그 기호입니다. `unlisted(…)`는 사전 목록에 맞는 종류가 없다고 본 것입니다.
   - 연결: 두 기호가 사이에 다른 기호 없이 배관으로 이어지는지 봅니다(티·분기점은 지나감).
   - 흐름 방향: 화살표가 가리키는 쪽이 맞는지 봅니다.
3. 쪽마다 틀림이 1건 이하면 그 건을 고쳐 정답지를 채택하고, 2건 이상이면 그 쪽을 다시 씁니다.
4. 다 보시면 아래 '쪽별 결과' 표에 일치 건수를 적어 주십시오. 일치율은 정답지의 `verified`에도 옮겨 적습니다.

뽑는 방법: `python scripts/check_read_quality.py sample D:\HAZOP-trials\2026-11-13-answer-key\sample-final` (씨앗 20261113 + 순번). 정답지를 고치면 같은 명령으로 다시 뽑습니다.

## 쪽별 결과

| 쪽 | 그림 | 확인 건수 | 일치 | 일치율 | 판정 | 확인한 사람·날짜 |
| --- | --- | --- | --- | --- | --- | --- |
| apr1400-008 | 5.1.2-3-S1 | 20 |  |  |  |  |
| apr1400-012 | 5.4.12-1-S1 | 20 |  |  |  |  |
| apr1400-016 | 6.3.2-1-S2 | 20 |  |  |  |  |
| apr1400-025 | 9.2.2-1-S1 | 20 |  |  |  |  |
| apr1400-033 | 9.2.7-1-S1 | 20 |  |  |  |  |
| apr1400-046 | 9.3.1-1-S1 | 20 |  |  |  |  |
| apr1400-062 | 9.3.3-1-S7 | 20 |  |  |  |  |
| apr1400-063 | 9.3.4-1-S1 | 20 |  |  |  |  |
| apr1400-072 | 9.4.2-1-S1 | 20 |  |  |  |  |
| apr1400-097 | 9.5.4-1-S1 | 20 |  |  |  |  |
| apr1400-105 | 10.3.2-1-S1 | 20 |  |  |  |  |
| apr1400-128 | 10.4.9-1-S1 | 20 |  |  |  |  |

## apr1400-008 (5.1.2-3-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (588, 207)–(924, 300) | relief_valve 304 ↔ motor_operated_valve 386 | `sample-final\crops\apr1400-008-01.png` |  |
| 2 | 태그·번호 | 태그·번호 (relief_valve) | (521, 162)–(536, 181) | 201 | `sample-final\crops\apr1400-008-02.png` |  |
| 3 | 연결 | 연결 | (409, 162)–(536, 228) | motor_operated_valve 122 ↔ relief_valve 201 | `sample-final\crops\apr1400-008-03.png` |  |
| 4 | 연결 | 연결 | (901, 296)–(924, 542) | motor_operated_valve 386 ↔ unlisted(sparger (bar with 4 triangle nozzles)) | `sample-final\crops\apr1400-008-04.png` |  |
| 5 | 연결 | 연결 | (746, 364)–(790, 375) | control_valve 100E ↔ manual_valve V240 | `sample-final\crops\apr1400-008-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (973, 162)–(1001, 167) | continuation | `sample-final\crops\apr1400-008-06.png` |  |
| 7 | 연결 | 연결 | (424, 314)–(522, 665) | pressurizer ↔ continuation | `sample-final\crops\apr1400-008-07.png` |  |
| 8 | 기호 종류 | 기호 종류 | (746, 284)–(754, 292) | manual_valve V237 | `sample-final\crops\apr1400-008-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (358, 141)–(368, 151) | unlisted(position indicating light (ZL, square-framed circle)) ZL 200A | `sample-final\crops\apr1400-008-09.png` |  |
| 10 | 태그·번호 | 태그·번호 (motor_operated_valve) | (492, 212)–(507, 228) | 132 | `sample-final\crops\apr1400-008-10.png` |  |
| 11 | 태그·번호 | 태그·번호 (relief_valve) | (271, 198)–(284, 210) | 301 | `sample-final\crops\apr1400-008-11.png` |  |
| 12 | 연결 | 연결 | (875, 424)–(927, 575) | relief_valve 1404 ↔ unlisted(sparger (bar with 4 triangle nozzles)) | `sample-final\crops\apr1400-008-12.png` |  |
| 13 | 연결 | 연결 | (857, 424)–(879, 430) | relief_valve 1402 ↔ relief_valve 1404 | `sample-final\crops\apr1400-008-13.png` |  |
| 14 | 태그·번호 | 태그·번호 (unlisted) | (395, 174)–(405, 184) | ZL 312B | `sample-final\crops\apr1400-008-14.png` |  |
| 15 | 태그·번호 | 태그·번호 (motor_operated_valve) | (312, 212)–(326, 228) | 130 | `sample-final\crops\apr1400-008-15.png` |  |
| 16 | 연결 | 연결 | (853, 205)–(879, 430) | motor_operated_valve 137 ↔ relief_valve 1404 | `sample-final\crops\apr1400-008-16.png` |  |
| 17 | 연결 | 연결 | (858, 556)–(895, 575) | unlisted(sparger (bar with 4 triangle nozzles)) ↔ unlisted(sparger (bar with 4 triangle nozzles)) | `sample-final\crops\apr1400-008-17.png` |  |
| 18 | 연결 | 연결 | (944, 414)–(964, 575) | relief_valve 1403 ↔ unlisted(sparger (bar with 4 triangle nozzles)) | `sample-final\crops\apr1400-008-18.png` |  |
| 19 | 연결 | 연결 | (857, 424)–(872, 560) | relief_valve 1402 ↔ unlisted(sparger (bar with 4 triangle nozzles)) | `sample-final\crops\apr1400-008-19.png` |  |
| 20 | 연결 | 연결 | (858, 296)–(924, 560) | motor_operated_valve 386 ↔ unlisted(sparger (bar with 4 triangle nozzles)) | `sample-final\crops\apr1400-008-20.png` |  |

## apr1400-012 (5.4.12-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 기호 종류 | 기호 종류 | (179, 264)–(184, 275) | solenoid_valve 418 | `sample-final\crops\apr1400-012-01.png` |  |
| 2 | 연결 | 연결 | (451, 507)–(676, 516) | solenoid_valve 410 ↔ continuation | `sample-final\crops\apr1400-012-02.png` |  |
| 3 | 속성 | 배관 size | (173, 273)–(186, 289) | 3"X2" | `sample-final\crops\apr1400-012-03.png` |  |
| 4 | 연결 | 연결 | (209, 440)–(392, 619) | reducer ↔ reducer | `sample-final\crops\apr1400-012-04.png` |  |
| 5 | 기호 종류 | 기호 종류 | (321, 363)–(345, 390) | temperature_element TEW 108 | `sample-final\crops\apr1400-012-05.png` |  |
| 6 | 속성 | 배관 size | (207, 610)–(219, 622) | 1"X3" | `sample-final\crops\apr1400-012-06.png` |  |
| 7 | 속성 | normal_position (solenoid_valve 411) | (500, 440)–(509, 444) | LC | `sample-final\crops\apr1400-012-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (solenoid_valve) | (347, 657)–(373, 680) | 416 | `sample-final\crops\apr1400-012-08.png` |  |
| 9 | 속성 | 배관 size | (773, 394)–(783, 402) | 4" | `sample-final\crops\apr1400-012-09.png` |  |
| 10 | 태그·번호 | 태그·번호 (solenoid_valve) | (161, 249)–(184, 275) | 418 | `sample-final\crops\apr1400-012-10.png` |  |
| 11 | 연결 | 연결 | (353, 510)–(367, 514) | reducer ↔ solenoid_valve 412 | `sample-final\crops\apr1400-012-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (840, 582)–(874, 588) | unlisted(sparger) | `sample-final\crops\apr1400-012-12.png` |  |
| 13 | 연결 | 연결 | (500, 440)–(676, 516) | solenoid_valve 411 ↔ continuation | `sample-final\crops\apr1400-012-13.png` |  |
| 14 | 기호 종류 | 기호 종류 | (520, 338)–(530, 342) | manual_valve V1430 | `sample-final\crops\apr1400-012-14.png` |  |
| 15 | 기호 종류 | 기호 종류 | (235, 408)–(245, 412) | solenoid_valve 420 | `sample-final\crops\apr1400-012-15.png` |  |
| 16 | 연결 | 연결 | (520, 338)–(874, 588) | manual_valve V1430 ↔ unlisted(sparger) | `sample-final\crops\apr1400-012-16.png` |  |
| 17 | 태그·번호 | 태그·번호 (solenoid_valve) | (490, 587)–(515, 610) | 415 | `sample-final\crops\apr1400-012-17.png` |  |
| 18 | 기호 종류 | 기호 종류 | (451, 510)–(460, 514) | solenoid_valve 410 | `sample-final\crops\apr1400-012-18.png` |  |
| 19 | 연결 | 연결 | (235, 408)–(358, 514) | solenoid_valve 420 ↔ reducer | `sample-final\crops\apr1400-012-19.png` |  |
| 20 | 연결 | 연결 | (462, 336)–(530, 344) | unlisted(sight glass (FG in circle)) SY01 ↔ manual_valve V1430 | `sample-final\crops\apr1400-012-20.png` |  |

## apr1400-016 (6.3.2-1-S2)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 기호 종류 | 기호 종류 | (565, 179)–(594, 184) | continuation | `sample-final\crops\apr1400-016-01.png` |  |
| 2 | 연결 | 흐름 방향 | (639, 151)–(800, 250) | continuation → orifice OR05B | `sample-final\crops\apr1400-016-02.png` |  |
| 3 | 연결 | 연결 | (646, 624)–(776, 634) | manual_valve V447 ↔ continuation | `sample-final\crops\apr1400-016-03.png` |  |
| 4 | 태그·번호 | 태그·번호 (manual_valve) | (793, 360)–(801, 367) | V721 | `sample-final\crops\apr1400-016-04.png` |  |
| 5 | 기호 종류 | 기호 종류 | (646, 624)–(654, 632) | manual_valve V447 | `sample-final\crops\apr1400-016-05.png` |  |
| 6 | 속성 | fail_position (motor_operated_valve 309) | (348, 639)–(354, 648) | FL | `sample-final\crops\apr1400-016-06.png` |  |
| 7 | 기호 종류 | 기호 종류 | (623, 270)–(630, 273) | check_valve V405 | `sample-final\crops\apr1400-016-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (temperature_element) | (831, 475)–(846, 491) | TEW 5B | `sample-final\crops\apr1400-016-08.png` |  |
| 9 | 태그·번호 | 태그·번호 (switch) | (385, 311)–(395, 321) | FIS 309 | `sample-final\crops\apr1400-016-09.png` |  |
| 10 | 연결 | 연결 | (736, 521)–(761, 557) | heat_exchanger HE01B ↔ orifice OR18B | `sample-final\crops\apr1400-016-10.png` |  |
| 11 | 연결 | 도면 밖 연결 | (757, 330)–(786, 335) | CV:EDT / SHEET 6 (계통 CV, 시트 6, 그림 None) | `sample-final\crops\apr1400-016-11.png` |  |
| 12 | 속성 | normal_position (manual_valve V715) | (711, 372)–(718, 379) | LC | `sample-final\crops\apr1400-016-12.png` |  |
| 13 | 기호 종류 | 기호 종류 | (716, 590)–(720, 596) | relief_valve 449 | `sample-final\crops\apr1400-016-13.png` |  |
| 14 | 기호 종류 | 기호 종류 | (665, 412)–(670, 440) | continuation | `sample-final\crops\apr1400-016-14.png` |  |
| 15 | 연결 | 연결 | (378, 566)–(402, 586) | check_valve V158 ↔ motor_operated_valve 348 | `sample-final\crops\apr1400-016-15.png` |  |
| 16 | 기호 종류 | 기호 종류 | (670, 204)–(699, 210) | continuation | `sample-final\crops\apr1400-016-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (686, 299)–(692, 301) | manual_valve V703 | `sample-final\crops\apr1400-016-17.png` |  |
| 18 | 연결 | 연결 | (464, 180)–(640, 210) | manual_valve V290 ↔ relief_valve 286 | `sample-final\crops\apr1400-016-18.png` |  |
| 19 | 기호 종류 | 기호 종류 | (578, 659)–(581, 662) | orifice OR08D | `sample-final\crops\apr1400-016-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (736, 269)–(764, 274) | continuation | `sample-final\crops\apr1400-016-20.png` |  |

## apr1400-025 (9.2.2-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 속성 | 배관 size | (621, 394)–(629, 402) | 1" | `sample-final\crops\apr1400-025-01.png` |  |
| 2 | 연결 | 연결 | (712, 109)–(754, 143) | manual_valve V1141 ↔ relief_valve 1031 | `sample-final\crops\apr1400-025-02.png` |  |
| 3 | 태그·번호 | 태그·번호 (pump) | (542, 174)–(561, 206) | PP01A | `sample-final\crops\apr1400-025-03.png` |  |
| 4 | 연결 | 연결 | (830, 311)–(840, 350) | motor_operated_valve 025 ↔ motor_operated_valve 035 | `sample-final\crops\apr1400-025-04.png` |  |
| 5 | 태그·번호 | 태그·번호 (manual_valve) | (254, 238)–(263, 245) | V1105 | `sample-final\crops\apr1400-025-05.png` |  |
| 6 | 연결 | 연결 | (470, 282)–(548, 374) | reducer ↔ manual_valve V1119 | `sample-final\crops\apr1400-025-06.png` |  |
| 7 | 연결 | 도면 밖 연결 | (193, 131)–(222, 137) | AF:AUXILIARY FEED WATER STORGE TANK A / SHEET 1 (계통 AF, 시트 1, 그림 None) | `sample-final\crops\apr1400-025-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (manual_valve) | (254, 132)–(263, 139) | V1321 | `sample-final\crops\apr1400-025-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (671, 359)–(677, 362) | manual_valve V1207 | `sample-final\crops\apr1400-025-09.png` |  |
| 10 | 연결 | 연결 | (388, 221)–(446, 352) | motor_operated_valve 939 ↔ manual_valve V1127 | `sample-final\crops\apr1400-025-10.png` |  |
| 11 | 태그·번호 | 태그·번호 (manual_valve) | (345, 250)–(352, 259) | V1327 | `sample-final\crops\apr1400-025-11.png` |  |
| 12 | 태그·번호 | 태그·번호 (temperature_element) | (578, 242)–(593, 258) | TE 3233 | `sample-final\crops\apr1400-025-12.png` |  |
| 13 | 속성 | normal_position (manual_valve V1123) | (482, 271)–(490, 274) | LO | `sample-final\crops\apr1400-025-13.png` |  |
| 14 | 속성 | 배관 size | (402, 386)–(410, 394) | ¾" | `sample-final\crops\apr1400-025-14.png` |  |
| 15 | 연결 | 연결 | (830, 155)–(840, 208) | motor_operated_valve 021 ↔ manual_valve V1041 | `sample-final\crops\apr1400-025-15.png` |  |
| 16 | 태그·번호 | 태그·번호 (relief_valve) | (739, 169)–(754, 185) | 1033 | `sample-final\crops\apr1400-025-16.png` |  |
| 17 | 속성 | 배관 size | (488, 398)–(496, 406) | 26" | `sample-final\crops\apr1400-025-17.png` |  |
| 18 | 연결 | 도면 밖 연결 | (523, 399)–(552, 405) | FROM QUADRANT C RETURN HEADER / SHEET 2"C" (계통 None, 시트 2, 그림 None) | `sample-final\crops\apr1400-025-18.png` |  |
| 19 | 연결 | 연결 | (661, 249)–(677, 362) | reducer ↔ manual_valve V1207 | `sample-final\crops\apr1400-025-19.png` |  |
| 20 | 속성 | 배관 size | (246, 254)–(254, 262) | 6" | `sample-final\crops\apr1400-025-20.png` |  |

## apr1400-033 (9.2.7-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (606, 309)–(626, 418) | manual_valve ↔ manual_valve V1025A | `sample-final\crops\apr1400-033-01.png` |  |
| 2 | 연결 | 연결 | (371, 230)–(458, 377) | tank TK01A ↔ manual_valve | `sample-final\crops\apr1400-033-02.png` |  |
| 3 | 연결 | 흐름 방향 | (663, 342)–(674, 637) | manual_valve V1020A → manual_valve V1028A | `sample-final\crops\apr1400-033-03.png` |  |
| 4 | 태그·번호 | 태그·번호 (indicator) | (392, 329)–(404, 340) | FI 373 | `sample-final\crops\apr1400-033-04.png` |  |
| 5 | 연결 | 연결 | (367, 230)–(458, 355) | tank TK01A ↔ check_valve V1003A | `sample-final\crops\apr1400-033-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (682, 493)–(693, 504) | indicator TI 027 | `sample-final\crops\apr1400-033-06.png` |  |
| 7 | 연결 | 연결 | (312, 454)–(364, 476) | pump PP03A ↔ check_valve V1011A | `sample-final\crops\apr1400-033-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (manual_valve) | (452, 316)–(466, 323) | V1009A | `sample-final\crops\apr1400-033-08.png` |  |
| 9 | 속성 | normal_position (manual_valve) | (606, 484)–(612, 488) | LT | `sample-final\crops\apr1400-033-09.png` |  |
| 10 | 기호 종류 | 기호 종류 | (583, 308)–(590, 312) | check_valve V1010A | `sample-final\crops\apr1400-033-10.png` |  |
| 11 | 연결 | 연결 | (514, 546)–(561, 589) | tank TK03A ↔ relief_valve 1041 | `sample-final\crops\apr1400-033-11.png` |  |
| 12 | 속성 | normal_position (manual_valve) | (606, 309)–(612, 312) | LT | `sample-final\crops\apr1400-033-12.png` |  |
| 13 | 기호 종류 | 기호 종류 | (546, 546)–(553, 554) | relief_valve 1041 | `sample-final\crops\apr1400-033-13.png` |  |
| 14 | 연결 | 연결 | (331, 351)–(359, 356) | manual_valve ↔ check_valve V1032A | `sample-final\crops\apr1400-033-14.png` |  |
| 15 | 연결 | 연결 | (244, 390)–(276, 418) | continuation ↔ continuation | `sample-final\crops\apr1400-033-15.png` |  |
| 16 | 연결 | 흐름 방향 | (371, 167)–(458, 264) | check_valve V1031A → tank TK01A | `sample-final\crops\apr1400-033-16.png` |  |
| 17 | 태그·번호 | 태그·번호 (indicator) | (298, 436)–(309, 447) | PI 247 | `sample-final\crops\apr1400-033-17.png` |  |
| 18 | 연결 | 연결 | (621, 309)–(674, 418) | manual_valve V1025A ↔ manual_valve V1019A | `sample-final\crops\apr1400-033-18.png` |  |
| 19 | 태그·번호 | 태그·번호 (indicator) | (491, 288)–(502, 299) | PI 005 | `sample-final\crops\apr1400-033-19.png` |  |
| 20 | 연결 | 연결 | (351, 351)–(374, 355) | check_valve V1032A ↔ check_valve V1003A | `sample-final\crops\apr1400-033-20.png` |  |

## apr1400-046 (9.3.1-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (206, 394)–(267, 397) | reducer ↔ manual_valve | `sample-final\crops\apr1400-046-01.png` |  |
| 2 | 연결 | 연결 | (892, 321)–(1012, 342) | pipe_cap ↔ continuation CB SUPPLY | `sample-final\crops\apr1400-046-02.png` |  |
| 3 | 기호 종류 | 기호 종류 | (116, 414)–(136, 420) | continuation | `sample-final\crops\apr1400-046-03.png` |  |
| 4 | 연결 | 연결 | (108, 554)–(192, 603) | compressor AIR COMPRESSOR 02 ↔ control_valve | `sample-final\crops\apr1400-046-04.png` |  |
| 5 | 속성 | 배관 size | (549, 391)–(557, 399) | 3" | `sample-final\crops\apr1400-046-05.png` |  |
| 6 | 연결 | 흐름 방향 | (98, 396)–(116, 420) | continuation → manual_valve | `sample-final\crops\apr1400-046-06.png` |  |
| 7 | 기호 종류 | 기호 종류 | (260, 589)–(267, 592) | manual_valve | `sample-final\crops\apr1400-046-07.png` |  |
| 8 | 연결 | 연결 | (133, 349)–(192, 407) | filter F ↔ compressor AIR COMPRESSOR 01 | `sample-final\crops\apr1400-046-08.png` |  |
| 9 | 연결 | 연결 | (829, 321)–(894, 419) | manual_valve ↔ pipe_cap | `sample-final\crops\apr1400-046-09.png` |  |
| 10 | 연결 | 도면 밖 연결 | (98, 414)–(103, 420) | CLCS (계통 None, 시트 None, 그림 None) | `sample-final\crops\apr1400-046-10.png` |  |
| 11 | 연결 | 연결 | (844, 376)–(1102, 434) | relief_valve ↔ continuation AB SUPPLY | `sample-final\crops\apr1400-046-11.png` |  |
| 12 | 연결 | 연결 | (892, 321)–(1102, 434) | pipe_cap ↔ continuation AB SUPPLY | `sample-final\crops\apr1400-046-12.png` |  |
| 13 | 기호 종류 | 기호 종류 | (976, 334)–(1012, 342) | continuation CB SUPPLY | `sample-final\crops\apr1400-046-13.png` |  |
| 14 | 기호 종류 | 기호 종류 | (417, 393)–(424, 397) | check_valve | `sample-final\crops\apr1400-046-14.png` |  |
| 15 | 속성 | 배관 size | (727, 410)–(735, 418) | 4" | `sample-final\crops\apr1400-046-15.png` |  |
| 16 | 기호 종류 | 기호 종류 | (1034, 442)–(1048, 455) | switch HS | `sample-final\crops\apr1400-046-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (1066, 427)–(1102, 434) | continuation AB SUPPLY | `sample-final\crops\apr1400-046-17.png` |  |
| 18 | 기호 종류 | 기호 종류 | (362, 365)–(380, 385) | transmitter PIT | `sample-final\crops\apr1400-046-18.png` |  |
| 19 | 연결 | 연결 | (1069, 499)–(1094, 503) | check_valve ↔ manual_valve | `sample-final\crops\apr1400-046-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (225, 462)–(229, 471) | manual_valve | `sample-final\crops\apr1400-046-20.png` |  |

## apr1400-062 (9.3.3-1-S7)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 기호 종류 | 기호 종류 | (778, 562)–(799, 615) | pump PP40 | `sample-final\crops\apr1400-062-01.png` |  |
| 2 | 연결 | 연결 | (432, 397)–(518, 468) | manual_valve V1073 ↔ unlisted(in-line box on pipe with corner mark, tied to AX circle by thin line) | `sample-final\crops\apr1400-062-02.png` |  |
| 3 | 연결 | 도면 밖 연결 | (659, 544)–(666, 550) | HOT MACHINE SHOP AREA DRAIN (계통 None, 시트 None, 그림 None) | `sample-final\crops\apr1400-062-03.png` |  |
| 4 | 연결 | 도면 밖 연결 | (668, 606)–(672, 614) | COMPOUND BLDG. DRAIN (계통 None, 시트 None, 그림 None) | `sample-final\crops\apr1400-062-04.png` |  |
| 5 | 연결 | 연결 | (1087, 261)–(1126, 301) | continuation ↔ continuation | `sample-final\crops\apr1400-062-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (537, 423)–(545, 427) | manual_valve V2132 | `sample-final\crops\apr1400-062-06.png` |  |
| 7 | 연결 | 연결 | (726, 350)–(759, 384) | strainer ST01 ↔ manual_valve V2125 | `sample-final\crops\apr1400-062-07.png` |  |
| 8 | 연결 | 흐름 방향 | (913, 426)–(950, 611) | pump PP41 → check_valve V1044 | `sample-final\crops\apr1400-062-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (431, 489)–(436, 498) | check_valve V1070 | `sample-final\crops\apr1400-062-09.png` |  |
| 10 | 태그·번호 | 태그·번호 (manual_valve) | (945, 332)–(954, 344) | V1045 | `sample-final\crops\apr1400-062-10.png` |  |
| 11 | 기호 종류 | 기호 종류 | (215, 404)–(219, 408) | reducer | `sample-final\crops\apr1400-062-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (86, 532)–(93, 537) | continuation | `sample-final\crops\apr1400-062-12.png` |  |
| 13 | 속성 | normal_position (manual_valve V1045) | (945, 334)–(950, 342) | LT | `sample-final\crops\apr1400-062-13.png` |  |
| 14 | 기호 종류 | 기호 종류 | (267, 460)–(272, 468) | manual_valve V1065 | `sample-final\crops\apr1400-062-14.png` |  |
| 15 | 연결 | 연결 | (270, 428)–(298, 432) | check_valve V2121 ↔ manual_valve V2122 | `sample-final\crops\apr1400-062-15.png` |  |
| 16 | 태그·번호 | 태그·번호 (strainer) | (726, 350)–(737, 364) | ST01 | `sample-final\crops\apr1400-062-16.png` |  |
| 17 | 연결 | 흐름 방향 | (668, 583)–(840, 630) | continuation → tank | `sample-final\crops\apr1400-062-17.png` |  |
| 18 | 연결 | 연결 | (431, 460)–(436, 498) | manual_valve V1071 ↔ check_valve V1070 | `sample-final\crops\apr1400-062-18.png` |  |
| 19 | 태그·번호 | 태그·번호 (manual_valve) | (462, 399)–(475, 408) | V2130 | `sample-final\crops\apr1400-062-19.png` |  |
| 20 | 태그·번호 | 태그·번호 (indicator) | (736, 558)–(750, 571) | LI 062 | `sample-final\crops\apr1400-062-20.png` |  |

## apr1400-063 (9.3.4-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 속성 | fail_position (air_operated_valve 516) | (397, 104)–(403, 122) | FC | `sample-final\crops\apr1400-063-01.png` |  |
| 2 | 연결 | 연결 | (890, 467)–(899, 499) | filter ↔ manual_valve V2081 | `sample-final\crops\apr1400-063-02.png` |  |
| 3 | 연결 | 연결 | (492, 190)–(578, 278) | heat_exchanger ↔ manual_valve V2004 | `sample-final\crops\apr1400-063-03.png` |  |
| 4 | 기호 종류 | 기호 종류 | (574, 444)–(578, 452) | check_valve V341 | `sample-final\crops\apr1400-063-04.png` |  |
| 5 | 태그·번호 | 태그·번호 (orifice) | (237, 531)–(249, 542) | OR02A | `sample-final\crops\apr1400-063-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (721, 462)–(734, 472) | manual_valve V349 | `sample-final\crops\apr1400-063-06.png` |  |
| 7 | 연결 | 도면 밖 연결 | (761, 618)–(794, 625) | CHARGING PUMPS / SHEET 3"C" (계통 None, 시트 3, 그림 None) | `sample-final\crops\apr1400-063-07.png` |  |
| 8 | 연결 | 연결 | (241, 299)–(367, 599) | heat_exchanger ↔ orifice OR03A | `sample-final\crops\apr1400-063-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (722, 412)–(733, 422) | manual_valve V350 | `sample-final\crops\apr1400-063-09.png` |  |
| 10 | 기호 종류 | 기호 종류 | (258, 524)–(266, 536) | motor_operated_valve 110Y | `sample-final\crops\apr1400-063-10.png` |  |
| 11 | 기호 종류 | 기호 종류 | (665, 418)–(672, 422) | manual_valve V348 | `sample-final\crops\apr1400-063-11.png` |  |
| 12 | 연결 | 연결 | (306, 468)–(326, 473) | orifice OR01B ↔ orifice OR01C | `sample-final\crops\apr1400-063-12.png` |  |
| 13 | 연결 | 흐름 방향 | (698, 611)–(794, 625) | continuation → motor_operated_valve 576 | `sample-final\crops\apr1400-063-13.png` |  |
| 14 | 연결 | 연결 | (819, 460)–(830, 573) | manual_valve V358 ↔ manual_valve V373 | `sample-final\crops\apr1400-063-14.png` |  |
| 15 | 태그·번호 | 태그·번호 (transmitter) | (409, 588)–(425, 607) | PT 1 | `sample-final\crops\apr1400-063-15.png` |  |
| 16 | 기호 종류 | 기호 종류 | (522, 296)–(526, 304) | manual_valve V2003 | `sample-final\crops\apr1400-063-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (472, 321)–(505, 328) | continuation | `sample-final\crops\apr1400-063-17.png` |  |
| 18 | 기호 종류 | 기호 종류 | (323, 531)–(326, 536) | orifice OR02C | `sample-final\crops\apr1400-063-18.png` |  |
| 19 | 연결 | 연결 | (450, 598)–(491, 669) | manual_valve V716 ↔ relief_valve 125 | `sample-final\crops\apr1400-063-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (984, 467)–(995, 493) | flow_element FE 202 | `sample-final\crops\apr1400-063-20.png` |  |

## apr1400-072 (9.4.2-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (281, 466)–(394, 623) | continuation ↔ damper Y0005A | `sample-final\crops\apr1400-072-01.png` |  |
| 2 | 기호 종류 | 기호 종류 | (505, 393)–(516, 403) | unlisted(instrument PDAH (differential pressure alarm high, shared HSI)) PDAH 026 | `sample-final\crops\apr1400-072-02.png` |  |
| 3 | 기호 종류 | 기호 종류 | (571, 414)–(582, 424) | switch PDIS 3042 | `sample-final\crops\apr1400-072-03.png` |  |
| 4 | 속성 | fail_position (damper Y0003A) | (659, 296)–(667, 304) | FC | `sample-final\crops\apr1400-072-04.png` |  |
| 5 | 기호 종류 | 기호 종류 | (552, 566)–(563, 577) | switch TIS 3046B | `sample-final\crops\apr1400-072-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (810, 382)–(823, 388) | unlisted(duct opening (thick bar + air-flow arrow, duct open end to room)) | `sample-final\crops\apr1400-072-06.png` |  |
| 7 | 기호 종류 | 기호 종류 | (198, 374)–(228, 380) | continuation | `sample-final\crops\apr1400-072-07.png` |  |
| 8 | 연결 | 연결 | (303, 186)–(337, 194) | damper Y1202A ↔ damper Y0001A | `sample-final\crops\apr1400-072-08.png` |  |
| 9 | 연결 | 연결 | (496, 220)–(509, 225) | manual_valve ↔ continuation | `sample-final\crops\apr1400-072-09.png` |  |
| 10 | 태그·번호 | 태그·번호 (indicator) | (445, 158)–(455, 169) | TI 3002 | `sample-final\crops\apr1400-072-10.png` |  |
| 11 | 태그·번호 | 태그·번호 (damper) | (302, 186)–(313, 198) | Y1202A | `sample-final\crops\apr1400-072-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (458, 393)–(469, 403) | unlisted(instrument PDAH (differential pressure alarm high, shared HSI)) PDAH 025 | `sample-final\crops\apr1400-072-12.png` |  |
| 13 | 연결 | 도면 밖 연결 | (496, 226)–(504, 231) | FROM & TO WI (계통 WI, 시트 None, 그림 None) | `sample-final\crops\apr1400-072-13.png` |  |
| 14 | 기호 종류 | 기호 종류 | (547, 609)–(557, 631) | unlisted(carbon adsorber (AD, dotted)) | `sample-final\crops\apr1400-072-14.png` |  |
| 15 | 속성 | normal_position (damper Y0029) | (602, 296)–(609, 304) | NO | `sample-final\crops\apr1400-072-15.png` |  |
| 16 | 연결 | 연결 | (897, 208)–(927, 265) | continuation ↔ continuation | `sample-final\crops\apr1400-072-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (464, 271)–(474, 282) | switch PDIS 3003 | `sample-final\crops\apr1400-072-17.png` |  |
| 18 | 연결 | 연결 | (532, 181)–(823, 553) | fan HV01 ↔ unlisted(duct opening (thick bar + air-flow arrow, duct open end to room)) | `sample-final\crops\apr1400-072-18.png` |  |
| 19 | 연결 | 연결 | (596, 437)–(654, 452) | fan AU02B ↔ damper Y0008B | `sample-final\crops\apr1400-072-19.png` |  |
| 20 | 연결 | 흐름 방향 | (365, 441)–(394, 484) | unlisted(duct opening (thick bar + air-flow arrow, duct open end to room)) → damper Y0006B | `sample-final\crops\apr1400-072-20.png` |  |

## apr1400-097 (9.5.4-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (637, 242)–(812, 385) | tank TK02A ↔ control_valve 4035A | `sample-final\crops\apr1400-097-01.png` |  |
| 2 | 연결 | 연결 | (828, 348)–(907, 352) | manual_valve V4034A ↔ manual_valve V5291A | `sample-final\crops\apr1400-097-02.png` |  |
| 3 | 태그·번호 | 태그·번호 (manual_valve) | (611, 293)–(624, 302) | V4019A | `sample-final\crops\apr1400-097-03.png` |  |
| 4 | 태그·번호 | 태그·번호 (strainer) | (434, 563)–(446, 574) | ST02A | `sample-final\crops\apr1400-097-04.png` |  |
| 5 | 태그·번호 | 태그·번호 (flow_element) | (636, 554)–(650, 587) | FE 031 | `sample-final\crops\apr1400-097-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (641, 554)–(645, 559) | flow_element FE 031 | `sample-final\crops\apr1400-097-06.png` |  |
| 7 | 연결 | 연결 | (246, 524)–(364, 580) | tank TK01A ↔ manual_valve V1002A | `sample-final\crops\apr1400-097-07.png` |  |
| 8 | 기호 종류 | 기호 종류 | (268, 449)–(274, 453) | vent | `sample-final\crops\apr1400-097-08.png` |  |
| 9 | 태그·번호 | 태그·번호 (manual_valve) | (217, 496)–(234, 504) | V1001A | `sample-final\crops\apr1400-097-09.png` |  |
| 10 | 태그·번호 | 태그·번호 (manual_valve) | (695, 318)–(704, 332) | V4102A | `sample-final\crops\apr1400-097-10.png` |  |
| 11 | 기호 종류 | 기호 종류 | (808, 291)–(813, 299) | unlisted(hose connection (coupler)) | `sample-final\crops\apr1400-097-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (857, 425)–(864, 429) | manual_valve V4320A | `sample-final\crops\apr1400-097-12.png` |  |
| 13 | 연결 | 연결 | (590, 480)–(645, 559) | manual_valve V1008A ↔ flow_element FE 031 | `sample-final\crops\apr1400-097-13.png` |  |
| 14 | 태그·번호 | 태그·번호 (strainer) | (764, 425)–(774, 434) | ST01A | `sample-final\crops\apr1400-097-14.png` |  |
| 15 | 연결 | 연결 | (637, 242)–(758, 330) | tank TK02A ↔ manual_valve V4101A | `sample-final\crops\apr1400-097-15.png` |  |
| 16 | 연결 | 연결 | (434, 569)–(460, 574) | strainer ST02A ↔ manual_valve V1010A | `sample-final\crops\apr1400-097-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (958, 482)–(976, 488) | unlisted(flexible hose) | `sample-final\crops\apr1400-097-17.png` |  |
| 18 | 연결 | 연결 | (958, 331)–(1057, 525) | unlisted(flexible hose) ↔ unlisted(diesel engine) DG01A | `sample-final\crops\apr1400-097-18.png` |  |
| 19 | 속성 | 배관 size | (566, 477)–(574, 486) | 2" | `sample-final\crops\apr1400-097-19.png` |  |
| 20 | 연결 | 연결 | (925, 439)–(933, 470) | orifice OR20A ↔ control_valve 4037A | `sample-final\crops\apr1400-097-20.png` |  |

## apr1400-105 (10.3.2-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (544, 252)–(744, 311) | relief_valve 1307 ↔ unlisted(electro-hydraulic (E/H) operated isolation valve) 015 | `sample-final\crops\apr1400-105-01.png` |  |
| 2 | 기호 종류 | 기호 종류 | (286, 577)–(298, 590) | transmitter FT 1022X | `sample-final\crops\apr1400-105-02.png` |  |
| 3 | 연결 | 연결 | (504, 521)–(658, 533) | relief_valve 1315 ↔ manual_valve V1073 | `sample-final\crops\apr1400-105-03.png` |  |
| 4 | 연결 | 연결 | (430, 158)–(512, 166) | relief_valve 1302 ↔ relief_valve 1306 | `sample-final\crops\apr1400-105-04.png` |  |
| 5 | 연결 | 연결 | (469, 158)–(588, 166) | relief_valve 1304 ↔ relief_valve 1310 | `sample-final\crops\apr1400-105-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (562, 126)–(564, 132) | vent | `sample-final\crops\apr1400-105-06.png` |  |
| 7 | 연결 | 연결 | (506, 153)–(658, 166) | relief_valve 1306 ↔ manual_valve V1257 | `sample-final\crops\apr1400-105-07.png` |  |
| 8 | 연결 | 연결 | (362, 402)–(588, 422) | motor_operated_valve 108 ↔ relief_valve 1320 | `sample-final\crops\apr1400-105-08.png` |  |
| 9 | 속성 | fail_position (control_valve 103) | (360, 518)–(376, 529) | FC | `sample-final\crops\apr1400-105-09.png` |  |
| 10 | 연결 | 연결 | (469, 402)–(550, 409) | relief_valve 1314 ↔ relief_valve 1318 | `sample-final\crops\apr1400-105-10.png` |  |
| 11 | 속성 | 배관 size | (598, 234)–(606, 242) | 26" | `sample-final\crops\apr1400-105-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (690, 575)–(719, 580) | continuation | `sample-final\crops\apr1400-105-12.png` |  |
| 13 | 연결 | 연결 | (362, 158)–(436, 178) | motor_operated_valve 106 ↔ relief_valve 1302 | `sample-final\crops\apr1400-105-13.png` |  |
| 14 | 연결 | 연결 | (559, 220)–(568, 250) | unlisted(drip pan elbow (vent stack inlet)) ↔ vent | `sample-final\crops\apr1400-105-14.png` |  |
| 15 | 연결 | 연결 | (544, 402)–(588, 409) | relief_valve 1318 ↔ relief_valve 1320 | `sample-final\crops\apr1400-105-15.png` |  |
| 16 | 연결 | 흐름 방향 | (754, 275)–(877, 300) | motor_operated_valve 019 → continuation | `sample-final\crops\apr1400-105-16.png` |  |
| 17 | 태그·번호 | 태그·번호 (relief_valve) | (534, 242)–(550, 259) | 1307 | `sample-final\crops\apr1400-105-17.png` |  |
| 18 | 연결 | 연결 | (261, 526)–(434, 605) | flow_element ↔ relief_valve 1311 | `sample-final\crops\apr1400-105-18.png` |  |
| 19 | 기호 종류 | 기호 종류 | (287, 620)–(298, 633) | transmitter PT 1023B | `sample-final\crops\apr1400-105-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (362, 540)–(374, 548) | motor_operated_valve 107 | `sample-final\crops\apr1400-105-20.png` |  |

## apr1400-128 (10.4.9-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 기호 종류 | 기호 종류 | (859, 248)–(863, 252) | reducer | `sample-final\crops\apr1400-128-01.png` |  |
| 2 | 속성 | 배관 size | (667, 146)–(675, 154) | 6" | `sample-final\crops\apr1400-128-02.png` |  |
| 3 | 기호 종류 | 기호 종류 | (648, 566)–(652, 574) | manual_valve V1624 | `sample-final\crops\apr1400-128-03.png` |  |
| 4 | 속성 | fail_position (motor_operated_valve) | (671, 417)–(680, 429) | FL | `sample-final\crops\apr1400-128-04.png` |  |
| 5 | 기호 종류 | 기호 종류 | (272, 336)–(307, 343) | continuation | `sample-final\crops\apr1400-128-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (550, 207)–(584, 214) | continuation | `sample-final\crops\apr1400-128-06.png` |  |
| 7 | 속성 | 배관 size | (884, 553)–(892, 561) | 8" | `sample-final\crops\apr1400-128-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (manual_valve) | (903, 259)–(916, 266) | V2679A | `sample-final\crops\apr1400-128-08.png` |  |
| 9 | 연결 | 연결 | (654, 417)–(680, 429) | manual_valve ↔ motor_operated_valve | `sample-final\crops\apr1400-128-09.png` |  |
| 10 | 속성 | 배관 size | (633, 403)–(641, 411) | 10" | `sample-final\crops\apr1400-128-10.png` |  |
| 11 | 연결 | 연결 | (386, 150)–(515, 297) | manual_valve V1607 ↔ tank TK01A | `sample-final\crops\apr1400-128-11.png` |  |
| 12 | 연결 | 흐름 방향 | (859, 265)–(948, 284) | reducer → continuation | `sample-final\crops\apr1400-128-12.png` |  |
| 13 | 기호 종류 | 기호 종류 | (669, 380)–(682, 392) | switch HS 016 | `sample-final\crops\apr1400-128-13.png` |  |
| 14 | 속성 | 배관 size | (585, 403)–(593, 411) | 10" | `sample-final\crops\apr1400-128-14.png` |  |
| 15 | 속성 | normal_position (manual_valve) | (527, 566)–(530, 573) | LO | `sample-final\crops\apr1400-128-15.png` |  |
| 16 | 연결 | 연결 | (590, 149)–(614, 165) | manual_valve ↔ manual_valve | `sample-final\crops\apr1400-128-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (604, 103)–(617, 116) | switch HS 015 | `sample-final\crops\apr1400-128-17.png` |  |
| 18 | 연결 | 연결 | (648, 541)–(863, 574) | manual_valve V1624 ↔ reducer | `sample-final\crops\apr1400-128-18.png` |  |
| 19 | 속성 | normal_position (manual_valve) | (693, 425)–(701, 429) | LT | `sample-final\crops\apr1400-128-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (474, 669)–(482, 672) | check_valve V2778B | `sample-final\crops\apr1400-128-20.png` |  |
