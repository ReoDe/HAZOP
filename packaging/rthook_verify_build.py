"""PyInstaller 런타임 훅(검증용 빌드 --with-check의 HAZOP.exe 전용, D18). 배포용 빌드에는 넣지 않는다.

검증용 빌드 표지만 세운다. scripts/run_app.py는 이 표지가 있을 때만 시험 전용 환경변수 HAZOP_TEST_EXCEPTHOOK을
받아들인다(배포용에서는 트리거가 꺼진다). 파일·네트워크를 쓰지 않는다.
"""

import sys

sys._hazop_verify_build = True
