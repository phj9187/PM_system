# PM_system

의사결정, 실행, 자원관리, 기록을 연결하는 조직 운영 시스템입니다.
현재는 설계 단계이며, 실행 가능한 통합 프로그램은 아직 없습니다.

## Colab에서 바로 실행

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/phj9187/PM_system/blob/main/notebooks/PM_system.ipynb)

위 버튼을 누르고 **런타임 → 모두 실행**을 선택하면 GitHub의 최신 `main`을 가져와 대시보드 전체·확대 보기 시안을 생성하고 표시합니다.
CPU 런타임이면 충분하며 API 키나 추가 패키지는 필요하지 않습니다.
현재는 정적 시안 실행용입니다. 업무 관리 서버와 AI 백엔드는 아직 포함되어 있지 않습니다.
노트북 실행 출력은 저장소에 커밋하지 않습니다.

## 설계 범위

| 영역 | 현재 방향 |
| --- | --- |
| 의사결정·통합관제 | 목표와 주요 정보를 고정 표시하고, 실제 시간에 비례한 가지형 타임라인으로 진행 상황 탐색 |
| 실행·자원관리 | 작업 조건·팀원 상태·가용 자원을 연결해 작업 배정과 수행 지원 |
| 기록 | 대시보드와 Discord의 진행 내용을 주기적으로 정리하여 Notion에 저장 |
| 공통 백엔드 | Colab에서 데이터 흐름·정제·검증·AI 처리·저장 연결을 개발하고 검증 |

저장소, 공통 데이터 형식, 승인 규칙, 기록 주기, AI 개입 조건과 실제 운영 환경은 아직 미정입니다.
Colab은 개발·검증 환경이며, 상시 운영 환경은 별도로 결정합니다.

## 현재 파일

- `build_design.py`: Python 표준 라이브러리로 예시 화면 SVG 생성
- `designs/01-overview.svg`: 전체 보기 예시
- `designs/02-detail.svg`: 확대 보기 예시
- `CONTRIBUTING.md`: 공동 개발 방식
- `notebooks/PM_system.ipynb`: Colab에서 저장소 준비·시안 생성·미리보기

화면의 이름·일정·수치는 예시이며 실제 팀 운영 정보가 아닙니다.

## 화면 예시 생성

Python 3 환경에서 저장소 루트에서 실행합니다.

```sh
python build_design.py
```

## 공동 개발

작업을 Issue로 정리하고, 작업별 브랜치에서 변경한 뒤 Pull Request로 검토합니다.
세부 방식은 [협업 안내](CONTRIBUTING.md)를 참고하세요.
공식 저장소: https://github.com/phj9187/PM_system

저장소는 공개이며 라이선스는 아직 정하지 않았습니다.
