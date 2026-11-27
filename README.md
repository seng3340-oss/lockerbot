# ROKEY 협동2

얼굴과 출입증을 확인하고, 개인 소지품을 보관하거나 음성 요청에 따라 돌려주는 협동로봇 프로젝트입니다.

- `ws_dsr/` — 두산 M0609 및 OnRobot RG2 장비 워크스페이스
- `ws_cobot2/` — 협동2 ROS 2 패키지를 개발할 워크스페이스
- `docs/` — 설계와 통신 규약
- `scripts/` — 장비 점검과 실행 스크립트
- `training/` — 데이터 수집, 학습, 평가 코드
- `models/` — 로컬 모델 가중치 배치 위치

## 빌드 순서

ROS 2 Jazzy 환경에서 `ws_dsr`을 먼저 빌드하고, 협동2 패키지가 추가되면 해당 환경을 불러온 뒤 `ws_cobot2`를 빌드합니다. 장비 워크스페이스의 구성은 [드라이버 README](ws_dsr/src/README.md)를 참고하세요.

## 출입·물품 기록

`ws_cobot2/src/lockerbot_storage`는 ROS 없이 실행 가능한 Python 표준 `sqlite3` 저장 모듈입니다. 사용자·개별 물품 등록, 확정된 출입 이벤트, 물품별 보관·트레이 반환 결과 및 현재 상태·누적 이력을 관리합니다.

저장 API·상태 의미·팀 합의 사항·실행 명령은 [SQLite 기록 관리 문서](docs/sqlite_storage.md)를 참고하세요. 운영 DB는 명시적인 `Storage.initialize()` 호출로만 생성되며, 테스트와 예제는 임시 DB를 사용합니다.
