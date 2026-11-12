# 폴더 구조 표준화 (2026-11-12)

문서 폴더를 `docs/` 아래로 모으고, 모든 폴더에 같은 양식의 규칙서(`README.md`)를 두는 작업 단위다. 사용자 결정 2026-11-12(질문 답변 세 건과 완료 목록 확인)에 따른다.

## 목표 배치

```
hazop/  scripts/  tests/  packaging/     코드
docs/
  specs/        제품 규격 (+ flows/)
  design/       화면 설계 (+ mockups/)
  methodology/  방법론 카드
  records/      결정로그·남은 작업
  units/        작업 단위 기록 (지금의 docs/YYYY-MM-DD-<slug>/)
  governance/   이름 규칙 등 운영 문서
resources/  licenses/  work/             자료·작업
README.md  CLAUDE.md  INTENT.md
```

## 완료 목록

1. 이름 규칙 문서(HZ-GOV-02)의 폴더 표·문서번호 표·검사 항목을 새 배치로 개정한다.
2. `specs/`, `design/`, `methodology/`, `records/`를 `docs/` 아래로 옮기고, 날짜 폴더를 `docs/units/`로, 이름 규칙 문서를 `docs/governance/`로 옮긴다.
3. 문서 링크, `.claude/agents`, `CLAUDE.md`·`INTENT.md`·`README.md`, 지침서 경로(`hazop/paths.py`)와 배포본 묶음 경로를 새 위치에 맞춘다.
4. 모든 폴더에 같은 양식의 `README.md`를 두고, 양식을 시험이 검사하게 한다.
5. 문서 30개의 `status`를 실제 상태로 매기고 목록을 보고한다.
6. 전체 시험, 기준값 검사 두 개(`--update` 없이 점수 그대로), 배포본 빌드와 묶음 검증을 통과한다.
7. 결정로그·백로그에 기록하고 PR을 연다.

하지 않는 것: 코드·자료 폴더의 파일 이동, 결정로그 본문 문장에 적힌 옛 경로 고치기, 사용자 작업 폴더(`work/`) 변경, 파일 삭제.

## 폴더 규칙서 양식

폴더마다 `README.md`에 다음 다섯 항목을 같은 순서로 적는다. ISO 9001 §7.5(문서화된 정보의 식별·승인·개정·보존)의 항목과 맞춘 것이다.

| 항목 | 내용 |
| --- | --- |
| 무엇을 넣는가 | 이 폴더에 두는 것 |
| 넣지 않는 것 | 헷갈리기 쉬운 것과 그것을 둘 곳 |
| 이름 형식 | 파일·하위 폴더 이름 규칙과 예 |
| 주인 | 누가 고치고 누가 승인하는가 |
| 폐기 기준 | 언제 지우거나 `obsolete`로 두는가 |

## 진행 방식

- 세션 둘: `folder-standard`(규칙 개정 → 이동 → 규칙서 작성을 이어서), `doc-status`(문서 상태 제안표). 자문은 세션 넷을 권했으나, 앞 단계 결과에 기대는 일이라 한 세션이 잇게 했다.
- 모델: 둘 다 Sonnet 5.5(`CLAUDE.md` 모델 배정표). 해시·배포 경로에 닿는 단계는 강도 high.
- 근거 문서는 `evidence/`에 둔다.
