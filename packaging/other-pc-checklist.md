# 다른 PC에서 배포본 실행 확인하기

이 문서는 빌드한 PC가 아닌 Windows PC에서 배포본(`HAZOP.exe`)이 제대로 도는지 사람이 직접 확인하는 절차다. 빌드 PC의 `verify_bundle.py`는 PATH를 줄이고 임시 폴더를 쓰지만 같은 PC라서 다른 PC와 같은 조건이라고 할 수 없다. 그래서 이 점검이 따로 필요하다.

**상태: 사용자 확인 대기.** 아래 결과 표는 아직 비어 있다. 다른 PC 실행은 사용자가 한다.

## 준비물

- 확인할 PC 한 대 이상. Windows 10(64비트)이 한 대 있으면 좋다. 지원 OS는 Windows 10 이상 64비트다(`packaging/README.md`).
- 배포용 빌드 폴더 `dist\HAZOP`을 묶은 zip. 검증용 `HAZOP-verify`(안에 `HAZOP-check.exe`가 있음)는 가져가지 않는다.
- 시험용 도면 파일 한두 개(`.drawio` 또는 `.pdf`). 배포본에는 샘플 도면이 들어 있지 않다.

확인할 PC에는 Python이나 venv가 필요 없다. venv는 빌드 PC에서만 쓴다. 빌드 PC의 venv 경로는 환경변수 `HAZOP_VENV`이고, 이 변수가 없으면 `%USERPROFILE%\.hazop\venv-py312`다.

## 빌드 PC에서 zip 만들기

1. 빌드 PC의 저장소 루트(예: `D:\HAZOP`)에서 배포용으로 빌드한다. 출력 폴더는 저장소 밖에 둔다. 이 절의 명령은 모두 저장소 루트에서 실행한다.

   ```powershell
   Set-Location D:\HAZOP
   $env:PYTHONIOENCODING = "utf-8"
   $py = if ($env:HAZOP_VENV) { "$env:HAZOP_VENV\Scripts\python.exe" } else { "$env:USERPROFILE\.hazop\venv-py312\Scripts\python.exe" }
   $out = "$env:TEMP\hazop-pkg-<날짜>"   # 저장소 밖이면 어디든 된다
   & $py scripts\build_package.py --out "$out\build-app" --build
   ```

2. 같은 PC에서 배포용 검증을 먼저 통과시킨다. `summary.json`의 `passed`가 `true`여야 한다.

   ```powershell
   & $py packaging\verify_bundle.py --dist "$out\build-app\dist\HAZOP" --target-base $env:TEMP\hz_ascii --out "$out\verify" --app-only
   ```

3. `dist\HAZOP` 폴더를 통째로 zip으로 묶는다. zip 안의 맨 위 폴더 이름은 `HAZOP`이다.
4. zip의 크기와 SHA-256을 적어 둔다(`Get-FileHash <zip> -Algorithm SHA256`). 확인할 PC에서 같은 값인지 본다.

## 확인할 PC에서 점검하기

각 단계의 결과를 아래 결과 표에 적는다. 단계마다 '기대 결과'가 아니면 화면을 찍고 `%LOCALAPPDATA%\HAZOP\logs\app.log`를 함께 보관한다.

0. 기존 작업을 먼저 보관한다. 배포본은 작업 자료를 `%LOCALAPPDATA%\HAZOP`에 쓰고, 이 점검은 시험 도면을 그곳에 등록한다. 그 PC에서 HAZOP을 이미 쓰고 있었다면 시험 자료가 실제 작업과 섞인다.
   - `%LOCALAPPDATA%\HAZOP` 폴더가 있는지 본다. 결과 표의 '기존 폴더' 칸에 '있음' 또는 '없음'을 적는다.
   - 폴더가 있으면 HAZOP을 모두 닫은 뒤 폴더째 다른 곳에 복사한다. 예: `robocopy "%LOCALAPPDATA%\HAZOP" "D:\HAZOP-보관-<날짜>" /E`. 복사본의 파일 수가 원본과 같은지 확인한다.
   - 폴더가 없으면 14단계에서 시험 자료를 지워도 된다.
1. Windows 판을 확인한다. `winver`를 실행해 판 번호와 빌드 번호를 적는다. 화면 배율(설정 > 디스플레이 > 배율)도 적는다.
2. zip의 SHA-256이 빌드 PC에서 적은 값과 같은지 확인한다.
3. zip을 한글과 공백이 든 경로에 푼다. 예: `C:\사용자 시험\HAZOP`. 기대 결과는 폴더 안에 `HAZOP.exe`, `_internal\`, `licenses\`가 있는 것이다.
4. `HAZOP.exe`를 두 번 눌러 실행한다. 서명하지 않은 실행 파일이라 SmartScreen이나 백신이 막을 수 있다. 막히면 그 안내 문구를 그대로 적고, 사내 규정이 허용할 때만 **추가 정보 > 실행**으로 넘어간다.
5. 첫 화면이 뜨는지 본다. 검토자 이름을 묻는 창이 뜨면 이름을 넣는다. 기대 결과는 30초 안에 ① 자료 등록 화면이 뜨고 한글이 빈 상자로 보이지 않는 것이다. 걸린 시간을 적는다.
6. 작업 루트를 확인한다. **도움말 > 버전·데이터 위치**를 연다. 기대 결과는 작업 루트가 `%LOCALAPPDATA%\HAZOP`이고, 고지 위치가 실행 파일 옆 `licenses\`인 것이다. 같은 창에서 **라이선스 고지 열기**를 눌러 탐색기가 그 폴더를 여는지 본다.
7. ①에서 시험용 도면을 등록한다. 기대 결과는 등록 목록에 도면이 생기는 것이다.
8. ② 도면 추출로 가서 도면이 그려지는지 본다. **편집**을 눌러 편집 패널이 열리는지 보고, 아무것도 고치지 않은 채 다시 눌러 끈다.
9. ③ 지식그래프, ④ 검토구간, ⑤ 분석 결과, ⑥ 초기사건을 차례로 연다(Ctrl+3 ~ Ctrl+6). 기대 결과는 오류 창 없이 각 화면이나 빈 상태 안내가 보이는 것이다.
10. 첫 창을 띄운 채 `HAZOP.exe`를 한 번 더 실행한다. 기대 결과는 "HAZOP이 이미 실행 중입니다" 안내가 뜨고, **확인**을 누르면 두 번째 실행만 끝나며 첫 창은 그대로인 것이다.
11. 첫 창을 닫고 다시 실행한다. 기대 결과는 잠금 안내 없이 바로 뜨는 것이다. 앞 실행이 남긴 잠금 파일(`%LOCALAPPDATA%\HAZOP\.hazop-app.lock`)이 다음 실행을 막으면 안 된다.
12. 인터넷을 끊은 상태(랜선을 뽑거나 Wi-Fi 끄기)에서 4~9를 한 번 더 한다. 기대 결과는 결과가 같은 것이다. 프로그램은 네트워크를 쓰지 않는다.
13. 배율이 125% 이상인 PC가 있으면 그 PC에서 5·8·9를 한 번 더 하고, 글자나 단추가 잘리는지 본다.
14. 끝나면 `%LOCALAPPDATA%\HAZOP\logs\app.log`를 보관한다. 그다음 0단계 기록에 따라 정리한다.
    - 0단계에서 '없음'이었던 PC만 `%LOCALAPPDATA%\HAZOP` 폴더를 지운다.
    - '있음'이었던 PC는 이 폴더를 지우지 않는다. HAZOP을 닫고 시험 폴더 이름을 `HAZOP-시험-<날짜>`로 바꾼 뒤, 0단계 복사본을 `%LOCALAPPDATA%\HAZOP`로 다시 복사한다. HAZOP을 열어 기존 작업이 보이는지 확인한다.
    - 푼 폴더(예: `C:\사용자 시험\HAZOP`)는 지워도 된다.

## 결과 표

PC마다 한 줄씩 적는다. 칸에는 통과, 실패(무엇이 달랐는지), 해당 없음 가운데 하나를 쓴다.

| PC | 기존 폴더(0) | Windows 판·빌드 | 배율 | 3 풀기 | 4 실행 허용 | 5 첫 화면(초) | 6 작업 루트·고지 | 7 등록 | 8 ②·편집 | 9 ③~⑥ | 10 두 번째 실행 | 11 다시 실행 | 12 오프라인 | 13 배율 | 확인한 사람·날짜 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| (사용자 확인 대기) | | | | | | | | | | | | | | | |

실패가 나오면 결과 표의 해당 칸, 화면 사진, `app.log`를 총괄에게 넘긴다. `메모리/남은작업.md`의 '다른 PC·Windows 10 실기기 실행 확인' 항목은 결과 표가 채워진 뒤에 닫는다.
