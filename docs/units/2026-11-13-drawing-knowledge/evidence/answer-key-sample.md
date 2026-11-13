# 정답지 사용자 확인 목록 (D-read/R1, 2026-11-13)

APR1400 정답지 12쪽에서 쪽마다 20건을 무작위로 뽑은 목록입니다. 정답지는 Claude 하위 에이전트가 쪽 그림만 보고 쓴 초안이고, 아직 사람이 확인하지 않았습니다. 절차는 [`docs/specs/extraction.md`](../../../specs/extraction.md#answer-key-procedure) '정답지 절차'입니다.

## 확인하는 법

1. 그림 조각을 엽니다. 빨간 네모가 그 항목의 자리입니다. 조각은 저장소 밖 `D:\HAZOP-trials\2026-11-13-answer-key\crops\`에 있습니다. 주변이 더 필요하면 같은 폴더의 `tiles\<순번>\overview.png`(쪽 전체, 100pt 격자)를 봅니다.
2. '정답 값'이 그림과 맞으면 '확인' 칸에 `맞음`, 다르면 `틀림: 바른 값`을 적습니다.
   - 기호 종류: 이름 뒤에 태그가 붙어 있으면 그 기호입니다. `unlisted(…)`는 사전 목록에 맞는 종류가 없다고 본 것입니다.
   - 연결: 두 기호가 사이에 다른 기호 없이 배관으로 이어지는지 봅니다(티·분기점은 지나감).
   - 흐름 방향: 화살표가 가리키는 쪽이 맞는지 봅니다.
3. 쪽마다 틀림이 1건 이하면 그 건을 고쳐 정답지를 채택하고, 2건 이상이면 그 쪽을 다시 씁니다.
4. 다 보시면 아래 '쪽별 결과' 표에 일치 건수를 적어 주십시오. 일치율은 정답지의 `verified`에도 옮겨 적습니다.

뽑는 방법: `python scripts/check_read_quality.py sample D:\HAZOP-trials\2026-11-13-answer-key` (씨앗 20261113 + 순번). 정답지를 고치면 같은 명령으로 다시 뽑습니다.

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
| 1 | 태그·번호 | 태그·번호 (relief_valve) | (960, 404)–(974, 419) | 1403 | `crops\apr1400-008-01.png` |  |
| 2 | 기호 종류 | 기호 종류 | (573, 604)–(602, 610) | continuation | `crops\apr1400-008-02.png` |  |
| 3 | 기호 종류 | 기호 종류 | (912, 572)–(927, 575) | unlisted(sparger (bar with 4 triangle nozzles)) | `crops\apr1400-008-03.png` |  |
| 4 | 태그·번호 | 태그·번호 (relief_valve) | (521, 162)–(536, 181) | 201 | `crops\apr1400-008-04.png` |  |
| 5 | 연결 | 연결 | (955, 414)–(970, 559) | relief_valve 1403 ↔ unlisted(sparger (bar with 4 triangle nozzles)) | `crops\apr1400-008-05.png` |  |
| 6 | 연결 | 연결 | (461, 162)–(536, 534) | pressurizer ↔ relief_valve 201 | `crops\apr1400-008-06.png` |  |
| 7 | 기호 종류 | 기호 종류 | (622, 174)–(632, 184) | unlisted(position indicating light (ZL, square-framed circle)) ZL 315C | `crops\apr1400-008-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (temperature_element) | (548, 183)–(562, 199) | TEW 39B | `crops\apr1400-008-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (630, 139)–(644, 155) | temperature_element TEW 38H | `crops\apr1400-008-09.png` |  |
| 10 | 기호 종류 | 기호 종류 | (309, 136)–(323, 152) | temperature_element TEW 38C | `crops\apr1400-008-10.png` |  |
| 11 | 기호 종류 | 기호 종류 | (675, 450)–(681, 480) | continuation | `crops\apr1400-008-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (783, 366)–(790, 375) | manual_valve V240 | `crops\apr1400-008-12.png` |  |
| 13 | 태그·번호 | 태그·번호 (motor_operated_valve) | (492, 212)–(507, 228) | 132 | `crops\apr1400-008-13.png` |  |
| 14 | 태그·번호 | 태그·번호 (manual_valve) | (411, 186)–(418, 192) | V312 | `crops\apr1400-008-14.png` |  |
| 15 | 기호 종류 | 기호 종류 | (804, 371)–(832, 377) | continuation | `crops\apr1400-008-15.png` |  |
| 16 | 기호 종류 | 기호 종류 | (973, 162)–(1001, 167) | continuation | `crops\apr1400-008-16.png` |  |
| 17 | 연결 | 연결 | (816, 186)–(821, 210) | manual_valve V317 ↔ relief_valve 307 | `crops\apr1400-008-17.png` |  |
| 18 | 태그·번호 | 태그·번호 (temperature_element) | (580, 136)–(595, 152) | TEW 38G | `crops\apr1400-008-18.png` |  |
| 19 | 태그·번호 | 태그·번호 (motor_operated_valve) | (634, 213)–(648, 228) | 125 | `crops\apr1400-008-19.png` |  |
| 20 | 태그·번호 | 태그·번호 (unlisted) | (390, 194)–(400, 204) | ZL 302B | `crops\apr1400-008-20.png` |  |

## apr1400-012 (5.4.12-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 기호 종류 | 기호 종류 | (179, 264)–(184, 275) | solenoid_valve 418 | `crops\apr1400-012-01.png` |  |
| 2 | 연결 | 연결 | (353, 510)–(367, 514) | reducer ↔ solenoid_valve 412 | `crops\apr1400-012-02.png` |  |
| 3 | 속성 | normal_position (solenoid_valve 416) | (363, 675)–(373, 680) | LC | `crops\apr1400-012-03.png` |  |
| 4 | 속성 | 배관 size | (638, 673)–(646, 682) | ¾" | `crops\apr1400-012-04.png` |  |
| 5 | 연결 | 연결 | (235, 408)–(392, 444) | solenoid_valve 420 ↔ reducer | `crops\apr1400-012-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (321, 363)–(345, 390) | temperature_element TEW 108 | `crops\apr1400-012-06.png` |  |
| 7 | 속성 | 배관 size | (451, 436)–(459, 446) | 2" | `crops\apr1400-012-07.png` |  |
| 8 | 속성 | normal_position (solenoid_valve 420) | (235, 408)–(245, 412) | LC | `crops\apr1400-012-08.png` |  |
| 9 | 태그·번호 | 태그·번호 (solenoid_valve) | (382, 587)–(408, 610) | 417 | `crops\apr1400-012-09.png` |  |
| 10 | 속성 | 배관 size | (243, 336)–(263, 346) | 3"X4" | `crops\apr1400-012-10.png` |  |
| 11 | 기호 종류 | 기호 종류 | (682, 673)–(729, 682) | continuation | `crops\apr1400-012-11.png` |  |
| 12 | 연결 | 연결 | (520, 338)–(874, 588) | manual_valve V1430 ↔ unlisted(sparger) | `crops\apr1400-012-12.png` |  |
| 13 | 기호 종류 | 기호 종류 | (520, 338)–(530, 342) | manual_valve V1430 | `crops\apr1400-012-13.png` |  |
| 14 | 연결 | 연결 | (392, 440)–(509, 444) | solenoid_valve 413 ↔ solenoid_valve 411 | `crops\apr1400-012-14.png` |  |
| 15 | 기호 종류 | 기호 종류 | (462, 336)–(471, 344) | unlisted(sight glass (FG in circle)) SY01 | `crops\apr1400-012-15.png` |  |
| 16 | 기호 종류 | 기호 종류 | (235, 408)–(245, 412) | solenoid_valve 420 | `crops\apr1400-012-16.png` |  |
| 17 | 연결 | 연결 | (441, 336)–(471, 344) | unlisted(flange pair (removal spool)) ↔ unlisted(sight glass (FG in circle)) SY01 | `crops\apr1400-012-17.png` |  |
| 18 | 태그·번호 | 태그·번호 (solenoid_valve) | (434, 491)–(460, 514) | 410 | `crops\apr1400-012-18.png` |  |
| 19 | 기호 종류 | 기호 종류 | (353, 510)–(358, 514) | reducer | `crops\apr1400-012-19.png` |  |
| 20 | 연결 | 연결 | (209, 408)–(245, 619) | solenoid_valve 420 ↔ reducer | `crops\apr1400-012-20.png` |  |

## apr1400-016 (6.3.2-1-S2)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 기호 종류 | 기호 종류 | (565, 179)–(594, 184) | continuation | `crops\apr1400-016-01.png` |  |
| 2 | 연결 | 연결 | (409, 146)–(425, 212) | motor_operated_valve 301 ↔ motor_operated_valve 303 | `crops\apr1400-016-02.png` |  |
| 3 | 연결 | 연결 | (596, 646)–(599, 663) | orifice OR20D ↔ manual_valve V255 | `crops\apr1400-016-03.png` |  |
| 4 | 태그·번호 | 태그·번호 (manual_valve) | (697, 357)–(704, 366) | V701 | `crops\apr1400-016-04.png` |  |
| 5 | 기호 종류 | 기호 종류 | (584, 671)–(591, 674) | check_valve V448 | `crops\apr1400-016-05.png` |  |
| 6 | 속성 | fail_position (motor_operated_valve 693) | (891, 226)–(900, 232) | FL | `crops\apr1400-016-06.png` |  |
| 7 | 기호 종류 | 기호 종류 | (623, 270)–(630, 273) | check_valve V405 | `crops\apr1400-016-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (orifice) | (749, 554)–(759, 561) | OR18B | `crops\apr1400-016-08.png` |  |
| 9 | 태그·번호 | 태그·번호 (manual_valve) | (711, 372)–(721, 379) | V715 | `crops\apr1400-016-09.png` |  |
| 10 | 연결 | 연결 | (700, 668)–(776, 676) | motor_operated_valve 609 ↔ continuation | `crops\apr1400-016-10.png` |  |
| 11 | 연결 | 흐름 방향 | (805, 493)–(816, 558) | motor_operated_valve 313 → motor_operated_valve 311 | `crops\apr1400-016-11.png` |  |
| 12 | 연결 | 도면 밖 연결 | (970, 471)–(1000, 477) | CV:EDT / SHEET 6 (계통 CV, 시트 6, 그림 None) | `crops\apr1400-016-12.png` |  |
| 13 | 기호 종류 | 기호 종류 | (606, 672)–(612, 675) | manual_valve V413 | `crops\apr1400-016-13.png` |  |
| 14 | 기호 종류 | 기호 종류 | (558, 535)–(584, 544) | heat_exchanger HE02B | `crops\apr1400-016-14.png` |  |
| 15 | 연결 | 연결 | (370, 514)–(418, 540) | continuation ↔ motor_operated_valve 342 | `crops\apr1400-016-15.png` |  |
| 16 | 기호 종류 | 기호 종류 | (670, 204)–(699, 210) | continuation | `crops\apr1400-016-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (686, 299)–(692, 301) | manual_valve V703 | `crops\apr1400-016-17.png` |  |
| 18 | 연결 | 연결 | (409, 202)–(614, 324) | motor_operated_valve 303 ↔ manual_valve V411 | `crops\apr1400-016-18.png` |  |
| 19 | 기호 종류 | 기호 종류 | (476, 628)–(495, 648) | pump PP02D | `crops\apr1400-016-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (736, 269)–(764, 274) | continuation | `crops\apr1400-016-20.png` |  |

## apr1400-025 (9.2.2-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 속성 | 배관 size | (488, 398)–(496, 406) | 26" | `crops\apr1400-025-01.png` |  |
| 2 | 연결 | 연결 | (709, 231)–(752, 382) | motor_operated_valve 027 ↔ reducer | `crops\apr1400-025-02.png` |  |
| 3 | 태그·번호 | 태그·번호 (pump) | (542, 174)–(561, 206) | PP01A | `crops\apr1400-025-03.png` |  |
| 4 | 연결 | 연결 | (830, 262)–(840, 288) | motor_operated_valve 033 ↔ manual_valve V1043 | `crops\apr1400-025-04.png` |  |
| 5 | 태그·번호 | 태그·번호 (manual_valve) | (254, 238)–(263, 245) | V1105 | `crops\apr1400-025-05.png` |  |
| 6 | 연결 | 연결 | (388, 271)–(490, 352) | manual_valve V1127 ↔ manual_valve V1123 | `crops\apr1400-025-06.png` |  |
| 7 | 연결 | 도면 밖 연결 | (321, 172)–(350, 177) | FC: SPENT FUEL POOL / SHEET 1 (계통 FC, 시트 1, 그림 None) | `crops\apr1400-025-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (manual_valve) | (254, 132)–(263, 139) | V1321 | `crops\apr1400-025-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (523, 399)–(552, 405) | continuation | `crops\apr1400-025-09.png` |  |
| 10 | 연결 | 연결 | (388, 259)–(517, 352) | continuation ↔ manual_valve V1127 | `crops\apr1400-025-10.png` |  |
| 11 | 태그·번호 | 태그·번호 (manual_valve) | (345, 250)–(352, 259) | V1327 | `crops\apr1400-025-11.png` |  |
| 12 | 태그·번호 | 태그·번호 (temperature_element) | (578, 242)–(593, 258) | TE 3233 | `crops\apr1400-025-12.png` |  |
| 13 | 속성 | normal_position (manual_valve V1141) | (712, 140)–(722, 143) | LO | `crops\apr1400-025-13.png` |  |
| 14 | 속성 | 배관 size | (463, 176)–(471, 184) | 28" | `crops\apr1400-025-14.png` |  |
| 15 | 연결 | 연결 | (749, 258)–(782, 298) | heat_exchanger HE03A ↔ relief_valve 1035 | `crops\apr1400-025-15.png` |  |
| 16 | 태그·번호 | 태그·번호 (relief_valve) | (739, 169)–(754, 185) | 1033 | `crops\apr1400-025-16.png` |  |
| 17 | 속성 | 배관 size | (695, 376)–(703, 384) | 36" | `crops\apr1400-025-17.png` |  |
| 18 | 연결 | 도면 밖 연결 | (982, 186)–(1011, 191) | QUADRANT A SUPPLY HEADER / SHEET 3"E" (계통 None, 시트 3, 그림 None) | `crops\apr1400-025-18.png` |  |
| 19 | 연결 | 연결 | (542, 266)–(625, 281) | pump PP02A ↔ check_valve V1003 | `crops\apr1400-025-19.png` |  |
| 20 | 속성 | 배관 size | (346, 346)–(354, 354) | 3" | `crops\apr1400-025-20.png` |  |

## apr1400-033 (9.2.7-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (606, 309)–(674, 312) | manual_valve ↔ manual_valve V1019A | `crops\apr1400-033-01.png` |  |
| 2 | 연결 | 연결 | (367, 351)–(388, 384) | check_valve V1003A ↔ check_valve V1022A | `crops\apr1400-033-02.png` |  |
| 3 | 연결 | 연결 | (600, 517)–(674, 602) | manual_valve V1024A ↔ manual_valve | `crops\apr1400-033-03.png` |  |
| 4 | 태그·번호 | 태그·번호 (air_operated_valve) | (310, 337)–(333, 356) | 907A | `crops\apr1400-033-04.png` |  |
| 5 | 연결 | 연결 | (371, 230)–(458, 384) | tank TK01A ↔ check_valve V1022A | `crops\apr1400-033-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (682, 493)–(693, 504) | indicator TI 027 | `crops\apr1400-033-06.png` |  |
| 7 | 연결 | 연결 | (358, 455)–(384, 458) | check_valve V1011A ↔ manual_valve | `crops\apr1400-033-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (pump) | (521, 307)–(543, 334) | PP01A | `crops\apr1400-033-08.png` |  |
| 9 | 속성 | normal_position (manual_valve V1023A) | (664, 484)–(674, 488) | LO | `crops\apr1400-033-09.png` |  |
| 10 | 기호 종류 | 기호 종류 | (583, 308)–(590, 312) | check_valve V1010A | `crops\apr1400-033-10.png` |  |
| 11 | 연결 | 연결 | (546, 546)–(571, 560) | relief_valve 1041 ↔ drain | `crops\apr1400-033-11.png` |  |
| 12 | 속성 | normal_position (manual_valve V1019A) | (664, 309)–(674, 312) | LO | `crops\apr1400-033-12.png` |  |
| 13 | 기호 종류 | 기호 종류 | (546, 546)–(553, 554) | relief_valve 1041 | `crops\apr1400-033-13.png` |  |
| 14 | 연결 | 연결 | (351, 351)–(374, 355) | check_valve V1032A ↔ check_valve V1003A | `crops\apr1400-033-14.png` |  |
| 15 | 연결 | 연결 | (244, 390)–(370, 417) | continuation ↔ manual_valve V1008A | `crops\apr1400-033-15.png` |  |
| 16 | 연결 | 연결 | (371, 191)–(458, 264) | tank TK01A ↔ relief_valve 1001A | `crops\apr1400-033-16.png` |  |
| 17 | 태그·번호 | 태그·번호 (indicator) | (338, 436)–(350, 447) | PI 251 | `crops\apr1400-033-17.png` |  |
| 18 | 연결 | 연결 | (664, 304)–(824, 351) | manual_valve V1019A ↔ unlisted(chiller (evaporator + condenser package)) CH01A | `crops\apr1400-033-18.png` |  |
| 19 | 태그·번호 | 태그·번호 (indicator) | (567, 284)–(578, 295) | PI 013 | `crops\apr1400-033-19.png` |  |
| 20 | 연결 | 연결 | (225, 460)–(280, 466) | continuation ↔ manual_valve | `crops\apr1400-033-20.png` |  |

## apr1400-046 (9.3.1-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 기호 종류 | 기호 종류 | (839, 414)–(844, 422) | relief_valve | `crops\apr1400-046-01.png` |  |
| 2 | 연결 | 연결 | (887, 259)–(978, 432) | unlisted(supply ring header box) ↔ continuation YARD AREA SUPPLY | `crops\apr1400-046-02.png` |  |
| 3 | 연결 | 연결 | (108, 359)–(192, 407) | compressor ↔ air_operated_valve | `crops\apr1400-046-03.png` |  |
| 4 | 연결 | 연결 | (818, 376)–(850, 391) | manual_valve ↔ relief_valve | `crops\apr1400-046-04.png` |  |
| 5 | 연결 | 연결 | (789, 383)–(821, 397) | check_valve ↔ manual_valve | `crops\apr1400-046-05.png` |  |
| 6 | 연결 | 연결 | (887, 334)–(1012, 432) | unlisted(supply ring header box) ↔ continuation CB SUPPLY | `crops\apr1400-046-06.png` |  |
| 7 | 기호 종류 | 기호 종류 | (362, 560)–(380, 580) | transmitter PIT | `crops\apr1400-046-07.png` |  |
| 8 | 속성 | 배관 size | (727, 605)–(735, 614) | 4" | `crops\apr1400-046-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (225, 462)–(229, 471) | manual_valve | `crops\apr1400-046-09.png` |  |
| 10 | 연결 | 연결 | (614, 575)–(657, 606) | manual_valve ↔ filter | `crops\apr1400-046-10.png` |  |
| 11 | 연결 | 연결 | (260, 552)–(315, 611) | manual_valve ↔ vessel | `crops\apr1400-046-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (507, 380)–(537, 411) | filter | `crops\apr1400-046-12.png` |  |
| 13 | 연결 | 연결 | (417, 545)–(437, 593) | check_valve ↔ manual_valve | `crops\apr1400-046-13.png` |  |
| 14 | 연결 | 연결 | (614, 380)–(657, 411) | manual_valve ↔ filter | `crops\apr1400-046-14.png` |  |
| 15 | 연결 | 연결 | (461, 577)–(500, 592) | air_operated_valve ↔ manual_valve | `crops\apr1400-046-15.png` |  |
| 16 | 연결 | 연결 | (559, 379)–(621, 412) | unlisted(air dryer (box)) ↔ manual_valve | `crops\apr1400-046-16.png` |  |
| 17 | 연결 | 연결 | (775, 393)–(797, 397) | manual_valve ↔ check_valve | `crops\apr1400-046-17.png` |  |
| 18 | 속성 | 배관 size | (922, 349)–(931, 357) | 3" | `crops\apr1400-046-18.png` |  |
| 19 | 연결 | 연결 | (789, 376)–(850, 397) | check_valve ↔ relief_valve | `crops\apr1400-046-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (277, 552)–(315, 611) | vessel | `crops\apr1400-046-20.png` |  |

## apr1400-062 (9.3.3-1-S7)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 기호 종류 | 기호 종류 | (778, 562)–(799, 615) | pump PP40 | `crops\apr1400-062-01.png` |  |
| 2 | 연결 | 연결 | (432, 397)–(518, 468) | manual_valve V1073 ↔ unlisted(in-line box on pipe with corner mark, tied to AX circle by thin line) | `crops\apr1400-062-02.png` |  |
| 3 | 연결 | 도면 밖 연결 | (659, 544)–(666, 550) | HOT MACHINE SHOP AREA DRAIN (계통 None, 시트 None, 그림 None) | `crops\apr1400-062-03.png` |  |
| 4 | 연결 | 도면 밖 연결 | (668, 606)–(672, 614) | COMPOUND BLDG. DRAIN (계통 None, 시트 None, 그림 None) | `crops\apr1400-062-04.png` |  |
| 5 | 연결 | 연결 | (1087, 261)–(1126, 301) | continuation ↔ continuation | `crops\apr1400-062-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (537, 423)–(545, 427) | manual_valve V2132 | `crops\apr1400-062-06.png` |  |
| 7 | 연결 | 연결 | (726, 350)–(759, 384) | strainer ST01 ↔ manual_valve V2125 | `crops\apr1400-062-07.png` |  |
| 8 | 연결 | 흐름 방향 | (913, 426)–(950, 611) | pump PP41 → check_valve V1044 | `crops\apr1400-062-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (431, 489)–(436, 498) | check_valve V1070 | `crops\apr1400-062-09.png` |  |
| 10 | 태그·번호 | 태그·번호 (manual_valve) | (945, 332)–(954, 344) | V1045 | `crops\apr1400-062-10.png` |  |
| 11 | 기호 종류 | 기호 종류 | (215, 404)–(219, 408) | reducer | `crops\apr1400-062-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (86, 532)–(93, 537) | continuation | `crops\apr1400-062-12.png` |  |
| 13 | 속성 | normal_position (manual_valve V1045) | (945, 334)–(950, 342) | LT | `crops\apr1400-062-13.png` |  |
| 14 | 기호 종류 | 기호 종류 | (267, 460)–(272, 468) | manual_valve V1065 | `crops\apr1400-062-14.png` |  |
| 15 | 연결 | 연결 | (270, 428)–(298, 432) | check_valve V2121 ↔ manual_valve V2122 | `crops\apr1400-062-15.png` |  |
| 16 | 태그·번호 | 태그·번호 (strainer) | (726, 350)–(737, 364) | ST01 | `crops\apr1400-062-16.png` |  |
| 17 | 연결 | 흐름 방향 | (668, 583)–(840, 630) | continuation → tank | `crops\apr1400-062-17.png` |  |
| 18 | 연결 | 연결 | (431, 460)–(436, 498) | manual_valve V1071 ↔ check_valve V1070 | `crops\apr1400-062-18.png` |  |
| 19 | 태그·번호 | 태그·번호 (manual_valve) | (462, 399)–(475, 408) | V2130 | `crops\apr1400-062-19.png` |  |
| 20 | 태그·번호 | 태그·번호 (indicator) | (736, 558)–(750, 571) | LI 062 | `crops\apr1400-062-20.png` |  |

## apr1400-063 (9.3.4-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 도면 밖 연결 | (472, 599)–(506, 606) | EDT / SHEET 6"EB" (계통 None, 시트 6, 그림 None) | `crops\apr1400-063-01.png` |  |
| 2 | 연결 | 흐름 방향 | (681, 514)–(743, 524) | relief_valve 354 → continuation | `crops\apr1400-063-02.png` |  |
| 3 | 연결 | 연결 | (732, 189)–(773, 280) | air_operated_valve 240 ↔ manual_valve V434 | `crops\apr1400-063-03.png` |  |
| 4 | 기호 종류 | 기호 종류 | (574, 444)–(578, 452) | check_valve V341 | `crops\apr1400-063-04.png` |  |
| 5 | 태그·번호 | 태그·번호 (orifice) | (237, 531)–(249, 542) | OR02A | `crops\apr1400-063-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (721, 462)–(734, 472) | manual_valve V349 | `crops\apr1400-063-06.png` |  |
| 7 | 연결 | 도면 밖 연결 | (878, 358)–(912, 365) | SI:SHUTDOWN COOLING HEAT EXCHANGER 2 / SHEET 2 (계통 SI, 시트 2, 그림 None) | `crops\apr1400-063-07.png` |  |
| 8 | 연결 | 연결 | (241, 299)–(367, 599) | heat_exchanger ↔ orifice OR03A | `crops\apr1400-063-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (722, 412)–(733, 422) | manual_valve V350 | `crops\apr1400-063-09.png` |  |
| 10 | 기호 종류 | 기호 종류 | (258, 524)–(266, 536) | motor_operated_valve 110Y | `crops\apr1400-063-10.png` |  |
| 11 | 기호 종류 | 기호 종류 | (665, 418)–(672, 422) | manual_valve V348 | `crops\apr1400-063-11.png` |  |
| 12 | 연결 | 연결 | (306, 468)–(326, 473) | orifice OR01B ↔ orifice OR01C | `crops\apr1400-063-12.png` |  |
| 13 | 연결 | 연결 | (878, 333)–(912, 365) | continuation ↔ continuation | `crops\apr1400-063-13.png` |  |
| 14 | 연결 | 연결 | (736, 514)–(830, 573) | relief_valve 354 ↔ manual_valve V373 | `crops\apr1400-063-14.png` |  |
| 15 | 태그·번호 | 태그·번호 (transmitter) | (409, 588)–(425, 607) | PT 1 | `crops\apr1400-063-15.png` |  |
| 16 | 기호 종류 | 기호 종류 | (522, 296)–(526, 304) | manual_valve V2003 | `crops\apr1400-063-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (472, 321)–(505, 328) | continuation | `crops\apr1400-063-17.png` |  |
| 18 | 기호 종류 | 기호 종류 | (323, 531)–(326, 536) | orifice OR02C | `crops\apr1400-063-18.png` |  |
| 19 | 연결 | 연결 | (432, 632)–(602, 693) | continuation ↔ flow_element FE 212B | `crops\apr1400-063-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (984, 482)–(995, 493) | flow_element FE 202 | `crops\apr1400-063-20.png` |  |

## apr1400-072 (9.4.2-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (281, 466)–(394, 623) | continuation ↔ damper Y0005A | `crops\apr1400-072-01.png` |  |
| 2 | 기호 종류 | 기호 종류 | (505, 393)–(516, 403) | unlisted(instrument PDAH (differential pressure alarm high, shared HSI)) PDAH 026 | `crops\apr1400-072-02.png` |  |
| 3 | 기호 종류 | 기호 종류 | (571, 414)–(582, 424) | switch PDIS 3042 | `crops\apr1400-072-03.png` |  |
| 4 | 속성 | fail_position (damper Y0003A) | (659, 296)–(667, 304) | FC | `crops\apr1400-072-04.png` |  |
| 5 | 기호 종류 | 기호 종류 | (552, 566)–(563, 577) | switch TIS 3046B | `crops\apr1400-072-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (810, 382)–(823, 388) | vent | `crops\apr1400-072-06.png` |  |
| 7 | 기호 종류 | 기호 종류 | (198, 374)–(228, 380) | continuation | `crops\apr1400-072-07.png` |  |
| 8 | 연결 | 연결 | (303, 186)–(337, 194) | damper Y1202A ↔ damper Y0001A | `crops\apr1400-072-08.png` |  |
| 9 | 연결 | 연결 | (496, 220)–(509, 225) | manual_valve ↔ continuation | `crops\apr1400-072-09.png` |  |
| 10 | 태그·번호 | 태그·번호 (indicator) | (445, 158)–(455, 169) | TI 3002 | `crops\apr1400-072-10.png` |  |
| 11 | 태그·번호 | 태그·번호 (damper) | (302, 186)–(313, 198) | Y1202A | `crops\apr1400-072-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (458, 393)–(469, 403) | unlisted(instrument PDAH (differential pressure alarm high, shared HSI)) PDAH 025 | `crops\apr1400-072-12.png` |  |
| 13 | 연결 | 도면 밖 연결 | (496, 226)–(504, 231) | FROM & TO WI (계통 WI, 시트 None, 그림 None) | `crops\apr1400-072-13.png` |  |
| 14 | 기호 종류 | 기호 종류 | (547, 609)–(557, 631) | unlisted(carbon adsorber (AD, dotted)) | `crops\apr1400-072-14.png` |  |
| 15 | 속성 | normal_position (damper Y0029) | (602, 296)–(609, 304) | NO | `crops\apr1400-072-15.png` |  |
| 16 | 연결 | 연결 | (897, 208)–(927, 265) | continuation ↔ continuation | `crops\apr1400-072-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (464, 271)–(474, 282) | switch PDIS 3003 | `crops\apr1400-072-17.png` |  |
| 18 | 연결 | 연결 | (532, 181)–(823, 553) | fan HV01 ↔ vent | `crops\apr1400-072-18.png` |  |
| 19 | 연결 | 연결 | (596, 437)–(654, 452) | fan AU02B ↔ damper Y0008B | `crops\apr1400-072-19.png` |  |
| 20 | 연결 | 흐름 방향 | (365, 441)–(394, 484) | vent → damper Y0006B | `crops\apr1400-072-20.png` |  |

## apr1400-097 (9.5.4-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (932, 346)–(976, 352) | manual_valve V5292A ↔ unlisted(flexible hose) | `crops\apr1400-097-01.png` |  |
| 2 | 속성 | 배관 size | (736, 338)–(745, 346) | 3" | `crops\apr1400-097-02.png` |  |
| 3 | 속성 | 배관 size | (752, 164)–(760, 172) | 1" | `crops\apr1400-097-03.png` |  |
| 4 | 태그·번호 | 태그·번호 (flow_element) | (636, 554)–(650, 587) | FE 031 | `crops\apr1400-097-04.png` |  |
| 5 | 기호 종류 | 기호 종류 | (452, 570)–(460, 573) | manual_valve V1010A | `crops\apr1400-097-05.png` |  |
| 6 | 연결 | 연결 | (562, 458)–(582, 483) | manual_valve V2009A ↔ check_valve V1007A | `crops\apr1400-097-06.png` |  |
| 7 | 연결 | 연결 | (748, 425)–(976, 511) | manual_valve V5290A ↔ unlisted(flexible hose) | `crops\apr1400-097-07.png` |  |
| 8 | 연결 | 연결 | (597, 293)–(622, 297) | manual_valve V4019A ↔ manual_valve V4103A | `crops\apr1400-097-08.png` |  |
| 9 | 기호 종류 | 기호 종류 | (326, 505)–(330, 513) | manual_valve V2027A | `crops\apr1400-097-09.png` |  |
| 10 | 연결 | 연결 | (217, 496)–(345, 580) | manual_valve V1001A ↔ tank TK01A | `crops\apr1400-097-10.png` |  |
| 11 | 기호 종류 | 기호 종류 | (672, 544)–(676, 552) | manual_valve V2010A | `crops\apr1400-097-11.png` |  |
| 12 | 태그·번호 | 태그·번호 (manual_valve) | (611, 293)–(624, 302) | V4019A | `crops\apr1400-097-12.png` |  |
| 13 | 연결 | 도면 밖 연결 | (696, 558)–(720, 566) | A (계통 None, 시트 None, 그림 None) | `crops\apr1400-097-13.png` |  |
| 14 | 기호 종류 | 기호 종류 | (786, 425)–(790, 429) | reducer | `crops\apr1400-097-14.png` |  |
| 15 | 속성 | 배관 size | (834, 502)–(842, 512) | ½" | `crops\apr1400-097-15.png` |  |
| 16 | 기호 종류 | 기호 종류 | (857, 425)–(864, 429) | manual_valve V4320A | `crops\apr1400-097-16.png` |  |
| 17 | 태그·번호 | 태그·번호 (check_valve) | (560, 555)–(574, 563) | V1005A | `crops\apr1400-097-17.png` |  |
| 18 | 속성 | normal_position (manual_valve V2027A) | (326, 505)–(330, 513) | LO | `crops\apr1400-097-18.png` |  |
| 19 | 기호 종류 | 기호 종류 | (217, 496)–(225, 500) | manual_valve V1001A | `crops\apr1400-097-19.png` |  |
| 20 | 연결 | 연결 | (724, 372)–(812, 386) | air_operated_valve 4035A ↔ continuation C | `crops\apr1400-097-20.png` |  |

## apr1400-105 (10.3.2-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 연결 | 연결 | (506, 252)–(664, 315) | relief_valve 1305 ↔ pipe_cap | `crops\apr1400-105-01.png` |  |
| 2 | 기호 종류 | 기호 종류 | (286, 577)–(298, 590) | transmitter FT 1022X | `crops\apr1400-105-02.png` |  |
| 3 | 연결 | 연결 | (428, 526)–(510, 533) | relief_valve 1311 ↔ relief_valve 1315 | `crops\apr1400-105-03.png` |  |
| 4 | 연결 | 연결 | (430, 158)–(664, 222) | relief_valve 1302 ↔ pipe_cap | `crops\apr1400-105-04.png` |  |
| 5 | 연결 | 연결 | (469, 158)–(744, 218) | relief_valve 1304 ↔ unlisted(electro-hydraulic (E/H) operated isolation valve) 016 | `crops\apr1400-105-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (558, 152)–(568, 157) | unlisted(drip pan elbow (vent stack inlet)) | `crops\apr1400-105-06.png` |  |
| 7 | 연결 | 연결 | (543, 153)–(658, 166) | relief_valve 1308 ↔ manual_valve V1257 | `crops\apr1400-105-07.png` |  |
| 8 | 연결 | 연결 | (494, 471)–(533, 480) | air_operated_valve 111 ↔ orifice | `crops\apr1400-105-08.png` |  |
| 9 | 연결 | 도면 밖 연결 | (674, 512)–(703, 520) | NT NITROGEN SUPPLY (계통 NT, 시트 None, 그림 None) | `crops\apr1400-105-09.png` |  |
| 10 | 연결 | 연결 | (362, 402)–(588, 425) | motor_operated_valve 108 ↔ relief_valve 1320 | `crops\apr1400-105-10.png` |  |
| 11 | 속성 | fail_position (unlisted(electro-hydraulic (E/H) operated isolation valve) 013) | (738, 548)–(744, 555) | FC | `crops\apr1400-105-11.png` |  |
| 12 | 기호 종류 | 기호 종류 | (653, 521)–(658, 528) | manual_valve V1073 | `crops\apr1400-105-12.png` |  |
| 13 | 연결 | 연결 | (362, 158)–(512, 178) | motor_operated_valve 106 ↔ relief_valve 1306 | `crops\apr1400-105-13.png` |  |
| 14 | 연결 | 연결 | (506, 252)–(744, 311) | relief_valve 1305 ↔ unlisted(electro-hydraulic (E/H) operated isolation valve) 015 | `crops\apr1400-105-14.png` |  |
| 15 | 연결 | 연결 | (469, 402)–(550, 409) | relief_valve 1314 ↔ relief_valve 1318 | `crops\apr1400-105-15.png` |  |
| 16 | 연결 | 연결 | (434, 296)–(674, 313) | air_operated_valve 090 ↔ manual_valve V1151 | `crops\apr1400-105-16.png` |  |
| 17 | 태그·번호 | 태그·번호 (temperature_element) | (635, 258)–(647, 271) | TEW 002 | `crops\apr1400-105-17.png` |  |
| 18 | 연결 | 연결 | (506, 397)–(530, 409) | relief_valve 1316 ↔ unlisted(drip pan elbow (vent stack inlet)) | `crops\apr1400-105-18.png` |  |
| 19 | 기호 종류 | 기호 종류 | (287, 620)–(298, 633) | transmitter PT 1023B | `crops\apr1400-105-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (540, 476)–(546, 480) | manual_valve V1154 | `crops\apr1400-105-20.png` |  |

## apr1400-128 (10.4.9-1-S1)

| 번호 | 항목 | 무엇 | 위치(pt) | 정답 값 | 그림 조각 | 확인 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 기호 종류 | 기호 종류 | (859, 248)–(863, 252) | reducer | `crops\apr1400-128-01.png` |  |
| 2 | 속성 | 배관 size | (763, 174)–(771, 185) | 6" | `crops\apr1400-128-02.png` |  |
| 3 | 기호 종류 | 기호 종류 | (648, 566)–(652, 574) | manual_valve V1624 | `crops\apr1400-128-03.png` |  |
| 4 | 속성 | normal_position (manual_valve) | (693, 425)–(701, 429) | LT | `crops\apr1400-128-04.png` |  |
| 5 | 기호 종류 | 기호 종류 | (272, 336)–(307, 343) | continuation | `crops\apr1400-128-05.png` |  |
| 6 | 기호 종류 | 기호 종류 | (550, 207)–(584, 214) | continuation | `crops\apr1400-128-06.png` |  |
| 7 | 속성 | 배관 size | (870, 562)–(878, 570) | 6" | `crops\apr1400-128-07.png` |  |
| 8 | 태그·번호 | 태그·번호 (manual_valve) | (903, 259)–(916, 266) | V2679A | `crops\apr1400-128-08.png` |  |
| 9 | 연결 | 연결 | (672, 425)–(701, 442) | manual_valve ↔ manual_valve | `crops\apr1400-128-09.png` |  |
| 10 | 속성 | 배관 size | (608, 423)–(616, 431) | 6" | `crops\apr1400-128-10.png` |  |
| 11 | 연결 | 연결 | (386, 150)–(515, 297) | manual_valve V1607 ↔ tank TK01A | `crops\apr1400-128-11.png` |  |
| 12 | 연결 | 연결 | (859, 265)–(948, 284) | reducer ↔ continuation | `crops\apr1400-128-12.png` |  |
| 13 | 기호 종류 | 기호 종류 | (669, 380)–(682, 392) | switch HS 016 | `crops\apr1400-128-13.png` |  |
| 14 | 속성 | 배관 size | (633, 403)–(641, 411) | 10" | `crops\apr1400-128-14.png` |  |
| 15 | 속성 | normal_position (manual_valve) | (456, 615)–(463, 619) | LO | `crops\apr1400-128-15.png` |  |
| 16 | 연결 | 연결 | (590, 149)–(614, 165) | manual_valve ↔ manual_valve | `crops\apr1400-128-16.png` |  |
| 17 | 기호 종류 | 기호 종류 | (604, 103)–(617, 116) | switch HS 015 | `crops\apr1400-128-17.png` |  |
| 18 | 연결 | 흐름 방향 | (648, 541)–(863, 574) | manual_valve V1624 → reducer | `crops\apr1400-128-18.png` |  |
| 19 | 속성 | normal_position (manual_valve) | (509, 544)–(513, 551) | LO | `crops\apr1400-128-19.png` |  |
| 20 | 기호 종류 | 기호 종류 | (474, 669)–(482, 672) | check_valve V2778B | `crops\apr1400-128-20.png` |  |
