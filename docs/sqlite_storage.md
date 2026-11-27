# 출입·개별 물품 SQLite 기록 관리

작성·검증일: 2026-11-27 (한국 시각). 저장 모듈은 `ws_cobot2/src/lockerbot_storage/lockerbot_storage/database.py`에 있다. Python 표준 라이브러리만 사용하며 ROS2를 import하지 않는다.

## 범위와 설계 선택

이번 프로젝트의 `README.md`, 기존 두 Mermaid 업무 흐름, 요청된 저장 요구사항을 우선했다. clone 직후 기준은 `main`의 `5a8f882`이며 Git 작업 트리는 깨끗했고 AGENTS.md는 없었다. `ws_cobot2`에는 개발 패키지가 없었다. 장비 코드와 기존 Mermaid 문서는 수정하지 않았다.

이전 `CakeBot_SQLite_Analysis_20261127.md`의 전체 구조는 비교 자료로 읽었다. 첨부 문서의 제안을 확정 요구사항으로 취급하지 않았다. `lockerbot_sqlite`의 미검증 초안도 검토만 했다. 이번 코드는 별도 신규 구현이며 초안과 그 DB를 재사용하거나 변환하지 않는다. 특히 참고 MD의 반환 후 사용자 보유 제안은 이번 요구사항과 달라 채택하지 않았다.

| 판단 | 항목 | 이번 프로젝트에서의 이유 |
| --- | --- | --- |
| 채택 | 표준 `sqlite3`, 로컬 파일, 매개변수 바인딩 | 소규모 사용자·물품 기록에 충분하고 ROS 없이 시험 가능 |
| 채택 | 4개 테이블, `items` 안의 현재·마지막 확인 상태 | 사용자별 보관 목록을 바로 조회하며 별도 최신 상태 테이블 없이 업무 이력과 구분 가능 |
| 채택 | 상태·이력 단일 트랜잭션, `BEGIN IMMEDIATE` | 동시 결과의 중복 확인·상태 검사·기록을 직렬화해 부분 저장 방지 |
| 채택 | 각 연결에서 트랜잭션 전에 외래키 활성화 | 미등록 참조와 사용자·물품 소유 관계 보호 |
| 채택 | 기존 이벤트 행의 입력 컬럼 직접 비교 | 재전송을 판별할 필드가 작고 고정되어 해시나 전용 테이블이 불필요 |
| 채택 | `updated_at` 관측값 비교, 기존 이벤트의 최신 시각 비교 | 동시 결과나 최신 실패보다 오래된 결과가 현재 상태를 덮어쓰지 않도록 보호. 실행·복구 revision이나 별도 순서 관리 테이블은 도입하지 않음 |
| 채택 | UTC 정규화, 명시적 초기화, 스키마 버전 확인 | 시각 혼동과 import 부작용을 줄이고 미지원 DB를 임의 변환하지 않음 |
| 보류 | WAL | 짧은 로컬 쓰기에 기본 rollback journal로 검증됨. 실제 읽기 지연·처리량 요구 확인 후 검토 |
| 보류 | 백업 자동화 | 배치·운영 주기·보존 정책이 미정. 배치 확정 후 운영 요구로 결정 |
| 제외 | 별도 `item_state`, 중복 방지 테이블, `payload_hash` | 현재 `items`와 기존 두 이벤트 테이블 및 직접 비교로 해결 |
| 제외 | 작업 실행 추적·claim_token·인수·자동 재시도·복구 시스템 | 이번 모듈은 확정된 결과를 저장하며 실행을 관리하지 않음 |
| 제외 | CakeBot 8개 테이블, 주문번호·일련번호, 케이크·그림·공정 필드, HMI·JSON 로그 | 현재 업무와 무관 |
| 제외 | FastAPI·HTTP 브리지, ROS2 노드·토픽·서비스·액션 정의 | 외부 필드와 배치 미정. Python API에 연결 가능하도록 통신 의존성을 두지 않음 |
| 제외 | 마이그레이션 프레임워크 | 변환할 기존 운영 DB가 없음. 미지원 버전은 거부 |

실제 로봇·인식·음성·태블릿·물품 겹침 처리, 근무시간·지각 계산은 구현 범위 밖이다. 저장 성공은 물리 작업 성공이나 전체 업무 성공 판정이 아니다.

## 최소 DB 구조

| 테이블 | 주요 내용 | 역할 |
| --- | --- | --- |
| `users` | `user_id` PK, `name` | 사용자 ID와 이름만 저장 |
| `items` | `item_id` PK, `owner_id` FK, `name`, `kind`, `status`, `location`, `updated_at`, `last_confirmed_status/location/at` | 개별 물품 정보와 현재/마지막 확인 상태 |
| `attendance_events` | `event_id` PK, `user_id` FK, `event_type`, `occurred_at` | 출근·외출·복귀·퇴근 누적 이력 |
| `item_events` | `event_id` PK, `user_id`, `item_id`, `action`, `outcome`, `expected_updated_at`, `previous_status/location`, `resulting_status/location`, `target_location`, `occurred_at`, `reason` | 물품별 보관·반환 결과와 전후 상태 누적 이력 |

외래키 `items.owner_id → users.user_id`, `attendance_events.user_id → users.user_id`, `item_events.user_id → users.user_id`, `(item_events.item_id, user_id) → items(item_id, owner_id)`를 사용한다. 마지막 복합 외래키는 Python 소유자 검사와 함께 다른 사람의 물품 이력 삽입을 막는다. PK·UNIQUE·CHECK로 중복 키, 빈 ID, 허용하지 않는 분류·상태·결과, 불명 상태의 현재 위치 등을 제한한다. 사용자별 상태 조회와 사용자별/물품별 시간순 이력에 인덱스를 둔다.

`kind`는 `BELONGING`(일반 소지품) 또는 `ACCESS_CARD`(출입증)다. `name`은 물품 이름/종류이고, `item_id`는 개별 실물 ID다. 같은 이름이 `차키`인 물품을 여러 ID로 등록할 수 있다. YOLO 클래스명은 개별 ID를 대신하지 않는다. 물품 ID·소유자는 호출부가 전달하며, 위치가 변해도 `owner_id`는 바뀌지 않는다. 얼굴 이미지·임베딩·음성 원본·사원번호·별도 로그/JSON은 저장하지 않는다.

이력은 추가만 하는 API를 제공하고 수정·삭제 API는 제공하지 않는다. `items`의 현재 상태만 갱신한다. 여러 물품 결과는 물품별로 각각 호출·확정하므로 일부 실패가 다른 물품의 성공을 취소하지 않는다. 출입과 물품 결과도 독립적이어서 물품 없는 사용자의 출입을 기록할 수 있다.

## 상태와 결과의 의미

| `items.status` | 의미 | `location` |
| --- | --- | --- |
| `WITH_USER` | 호출부가 사용자 보유를 확인한 초기 관측 | 예: `user:employee-001` |
| `STORED` | 지정된 보관 위치에 배치 완료를 확인 | 예: `drawer:1` 또는 `badge-slot:001` |
| `ON_TRAY` | 반환 작업으로 지정 트레이에 배치 완료를 확인 | 예: `tray:1`. 사용자가 집어 갔다는 뜻이 아님 |
| `UNKNOWN` | 현재 위치/상태를 확정할 수 없음 또는 아직 관측하지 않음 | 반드시 NULL |

위치 문자열 예시는 내부 식별자 예시이며 슬롯·트레이의 외부 명명 규약을 정하지 않는다. 소유자 식별과 현재 위치는 서로 다른 값이다. 등록 기본 상태는 `UNKNOWN`이다. 등록했다는 이유로 사용자 보유를 추정하지 않는다. 확인된 초기 상태를 등록하려면 `status`, 비어 있지 않은 `location`, 시간대가 있는 `observed_at`을 전달한다. 이 관측은 등록 정보로 저장하며 보관/반환 성공 이벤트를 만들어 내지 않는다. `WITH_USER`는 초기 관측에만 사용하며 트레이 반환 후 자동 전환하지 않는다.

`action`은 `STORE` 또는 `RETURN`이다. 호출부가 개별 물품의 실제 결과를 확인한 뒤 다음 `outcome` 중 하나를 전달한다.

| `outcome` | 상태·위치 처리 | 마지막 확인 정보 | 이력 |
| --- | --- | --- | --- |
| `SUCCESS` | STORE → STORED, RETURN → ON_TRAY. 위치를 `target_location`으로 변경 | 새 상태·위치·발생 시각으로 갱신 | 전후 상태·위치를 추가 |
| `FAILED_UNCHANGED` | 상태·위치·`updated_at` 모두 유지 | 유지 | 실패 사유와 동일한 전후 상태를 추가 |
| `UNKNOWN` | UNKNOWN으로 변경, 현재 위치 NULL, `updated_at` 갱신 | 이전 확인 정보를 보존 | 불명 사유와 전후 상태를 추가 |

실패와 불명은 비어 있지 않은 `reason`이 필수다. 이동하지 않았다고 확인하지 못했으면 `FAILED_UNCHANGED`로 저장하지 않는다. `target_location`은 시도한 목적지이며 실패/불명 결과의 실제 위치를 뜻하지 않는다. UNKNOWN 등록 이후 아직 확인한 적이 없다면 `last_confirmed_*`도 모두 NULL이다. 연속 불명 결과는 마지막 확인 사실을 덮어쓰지 않는다.

예: STORED(drawer:1) → 반환 중 위치 불명은 현재 `status=UNKNOWN, location=NULL`, 마지막 확인 `STORED, drawer:1, 당시 시각`으로 조회된다. `stored_only=True`는 현재 확인된 STORED만 반환한다. 따라서 UNKNOWN은 보관 목록에 포함되지 않지만, 보관 목록 제외가 사용자 수령·분실·전체 반환 완료를 뜻하지는 않는다. 후속 판단에는 `list_items()`의 전체 상태도 확인해야 한다.

성공한 STORE는 이전 상태와 관계없이 STORED로, 성공한 RETURN은 ON_TRAY로 기록한다. 마지막 확인 상태만으로 실제 작업의 허용 순서를 임의 결정하지 않는다. 예를 들어 새로 확인된 보관 위치 변경은 STORED → STORED로 저장할 수 있다. 어느 경우든 호출부가 개별 물리 작업 완료를 확인해야 하며 중복·소유자·관측 상태·시각 검사는 통과해야 한다. 실패/불명도 같은 보호 검사를 거친다. 저장 모듈은 확인·탐색·복구 작업을 수행하거나 재시도를 예약하지 않는다.

## Python API — 임시 내부 규약

반환된 조회 목록은 `dict`의 리스트다. 이벤트 저장은 저장된 이벤트 `dict`를 반환하며 동일 재전송도 같은 내용의 `dict`를 반환한다. 등록/초기화는 정상 반환으로 저장 성공을 나타낸다.

| 호출 | 인자와 동작 |
| --- | --- |
| `Storage(db_path=None)` | 객체 구성만 수행. 기본 `~/.local/share/lockerbot/records.sqlite3`. 파일/폴더/연결을 만들지 않음 |
| `initialize()` | DB·부모 디렉터리를 명시적으로 생성하고 버전 확인. 반복 실행으로 기존 기록을 지우지 않음 |
| `register_user(user_id, name)` | 사용자 등록. 기존 ID를 덮어쓰지 않으며 재등록은 오류 |
| `register_item(item_id, owner_id, name, kind='BELONGING', *, status='UNKNOWN', location=None, observed_at=None)` | 사용자 존재 검사 후 개별 물품 등록. 재등록은 오류. 알려진 상태에는 관측 시각 필수 |
| `record_attendance(user_id, event_type, *, event_id, occurred_at)` | 호출부가 확정한 CHECK_IN/GO_OUT/RETURN/CHECK_OUT을 누적 |
| `record_item_result(user_id, item_id, action, *, outcome, target_location, event_id, occurred_at, expected_updated_at, reason='')` | 개별 결과 저장과 필요 시 현재 상태 갱신을 한 번에 확정 |
| `list_items(user_id, *, stored_only=False)` | 사용자 물품 전체 또는 현재 확인된 보관 목록 |
| `attendance_history(user_id)` | 사용자 출입 이력. 발생 시각순, 같은 시각이면 삽입순 |
| `item_history(item_id)` | 물품 처리 이력. 발생 시각순, 같은 시각이면 삽입순 |

조회 대상 사용자·물품이 없으면 오류이며, 등록된 사용자에게 물품/이력이 없으면 빈 리스트다. 등록 재호출을 이벤트 재전송과 혼동하지 않는다. 자동 사용자 생성·이름 변경·소유자 변경은 제공하지 않는다.

`event_id`, ID들, 위치는 비어 있지 않은 문자열이다. `occurred_at`은 UTC로 변환할 수 있는 **시간대가 있는 Python datetime**이 필수다. 함수가 이벤트 ID나 이벤트 시각을 임의 생성하지 않는다. 등록 기본 UNKNOWN의 `observed_at`만 생략할 수 있고, 이때 등록 시점 UTC를 사용한다.

`expected_updated_at`은 호출부가 작업 전에 `list_items()`에서 읽은 해당 물품의 `updated_at` 문자열 그대로다. 최초 결과를 만들 때 보존하고, 재전송하면서 새 조회값으로 교체하지 않는다. 이 값은 ROS2 메시지 필드 확정안이 아니라 내부 동시 갱신 방지 규약이다. 신규 결과는 현재 값과 달라지면 거부한다. 상태가 바뀌는 SUCCESS/UNKNOWN의 발생 시각은 현재 `updated_at`보다 늦어야 하며, FAILED_UNCHANGED는 같은 시각까지 허용한다. 물품별 기존 이벤트의 가장 늦은 발생 시각보다 오래된 신규 결과도 거부한다. FAILED_UNCHANGED가 `items`를 바꾸지 않아도 그 이후에 과거 결과를 덧씌우지 못하게 하기 위해서다. 중복 재전송 비교는 이 모든 검사보다 먼저 한다.

내부 규약은 공통 UTC와 물품별 발생 순서를 전제로 한다. `updated_at`을 동시 갱신 비교값으로도 쓰므로 연속 상태 변경의 시각을 구별할 정밀도가 필요하다. 외부 시계 정합·시각 정밀도·지연 결과 처리 정책은 연결부 합의 사항이다. 저장 거절을 피하려고 원본 발생 시각을 바꾸지는 않는다.

출입 이벤트의 업무상 순서와 완료 시점은 검사하지 않는다. 인증 완료/용건 확정/로봇 완료 중 어느 시점인지 팀이 결정해 호출한다. 요청 접수·인증 실패에서 `record_attendance()`를 호출하지 않는다. 출입증 필수 반환 등 외출/퇴근 정책, 전체 업무 성공, 물품 소유자 확인은 호출부의 책임이다.

## 재전송·트랜잭션·오류

이벤트 처리 순서는 쓰기 잠금 획득 → 두 이벤트 테이블에서 ID 중복 확인/입력 내용 비교 → 참조/소유자/현재 상태/시각 검사 → 이력 삽입 → 필요한 현재 상태 갱신 → commit이다. 어떤 단계든 실패하면 rollback하고 연결을 닫는다. 정상 반환도 연결을 닫는다. 각 연결은 트랜잭션 전에 `PRAGMA foreign_keys=ON`을 실행한다. 잠금 대기는 10초이며 저장 모듈의 자동 물리 재시도는 없다.

같은 이벤트 ID와 같은 입력이면 현재 상태가 후속 작업으로 바뀌었어도 기존 이벤트를 반환한다. 다른 내용이면 `EventConflictError`다. 입력 비교에는 사용자·물품·작업·결과·대상 위치·사유·발생 시각·관측 `expected_updated_at` 전체를 포함한다. 시각은 UTC 마이크로초 문자열로 정규화한 후 비교한다. 다른 이벤트 계열에서 같은 ID를 사용해도 충돌로 거부하며, 별도 중복 방지 테이블은 없다. 두 테이블 사이 ID 확인은 저장 API의 같은 쓰기 트랜잭션에서 수행한다.

- 같은 결과를 재전송할 때 **동일 ID·동일 발생 시각·동일 인자 전체**를 사용한다. UUID가 필요하면 호출부가 최초 결과 생성 시 한 번만 생성해 보존한다.
- 새로운 물리적 재시도 결과에는 새 ID를 사용하고 새 작업 전 상태를 읽는다. 기존 실패와 새 성공은 각각 이력으로 남는다.
- `StaleStateError`는 DB에 기록되지 않은 저장 거절이다. 시각/관측값만 바꿔 같은 물리 결과를 새 결과로 꾸미지 않는다. 호출부가 기존 처리 여부·관측 상태를 확인해야 한다.

| 오류 | 의미 |
| --- | --- |
| `ValueError` / 필수 인자 누락 `TypeError` | 입력 형식·허용값·시간대·사유 오류 |
| `EventConflictError` | 같은 ID에 다른 입력 또는 다른 이벤트 계열 |
| `UnknownReferenceError` | 등록되지 않은 사용자·물품 |
| `OwnershipError` | 다른 사용자의 물품 |
| `StaleStateError` | 작업 전 관측 상태가 바뀜 또는 과거 결과 |
| `SchemaVersionError` | 미초기화/미지원 버전 또는 버전 없는 비어 있지 않은 DB |
| `sqlite3.IntegrityError` | 중복 등록 등 DB 제약/쓰기 오류 |
| `sqlite3.OperationalError` 등 | 미존재 DB 접근, 잠금 시간 초과, 파일 I/O 등 SQLite 오류 |

사용자/물품 등록은 새로운 결과 이벤트가 아니므로 `event_id`가 없다. 실패한 입력·소유자 오류·오래된 관측·충돌은 업무 이력에 성공/실패 이벤트로 추가하지 않는다. 호출부가 전달한 실제 실행 실패 `FAILED_UNCHANGED`와 저장 거절을 구분한다.

## 초기화·버전·운영 파일

스키마 버전은 `PRAGMA user_version=1`이고, SQLite 내장 `application_id=0x4C424F54`(LBOT)로 이번 저장 모듈의 DB를 식별한다. 이전 미검증 초안도 v1을 쓰므로 버전만으로 오인하지 않기 위한 식별값이며 별도 테이블은 없다. 다른 애플리케이션 표식이 없는 빈 DB의 버전 0만 초기화한다. 식별값이 맞는 기존 v1은 데이터를 보존한다. 그 외 버전, 식별값 불일치, 또는 버전 0인데 기존 테이블 등이 있는 DB는 거부하고 자동 변환하지 않는다. 업무 함수도 연결 때마다 버전과 식별값을 확인한다. 기존 초안 DB는 v1 표식이 같아도 거부하므로 별도 새 경로를 사용한다. 초안 DB 변환은 구현하지 않았다.

`initialize()` 이외 함수는 `mode=rw`로 연결해서 DB가 없을 때 새 DB를 만들지 않고 오류를 낸다. 호출별 연결을 사용하므로 `:memory:`는 지원하지 않으며 테스트는 임시 **파일** DB를 쓴다. 운영 DB와 예제/테스트 DB를 구분한다. 운영 경로는 인자로 변경할 수 있다. `runtime/records.sqlite3` 같은 저장소 내부 실행 경로도 `.gitignore`로 제외되며, `*.db`, `*.db3`, `*.sqlite`, `*.sqlite3`와 저널·WAL·SHM 패턴도 제외된다. 다른 확장자의 DB 파일은 `runtime/` 아래에 배치한다.

배포 노드/서버/호스트를 이번에 정하지 않았다. 서로 다른 PC나 태블릿이 DB 파일을 직접 공유한다고 가정하지 않는다. 모듈은 동일 호스트의 로컬 파일에 대한 SQLite 잠금으로 동시 호출을 처리한다. 향후 통신 수신부가 입력을 Python 함수 인자로 변환한다.

WAL을 활성화하지 않았고 새 DB는 SQLite 기본 rollback journal로 동작한다. 백업 자동화도 포함하지 않는다. 운영 백업이 필요하면 쓰기 정지 후 연결을 모두 닫고 사본을 보관하거나 SQLite backup API를 사용하는 절차를 배치 담당자가 마련한다. 운영 파일을 Git에 추가하는 방식으로 백업하지 않는다.

## 실행 명령

저장소 루트에서 실행한다. ROS2 설치·장비 연결·추가 pip 설치는 필요 없다.

```bash
export PYTHONPATH="$PWD/ws_cobot2/src/lockerbot_storage${PYTHONPATH:+:$PYTHONPATH}"
python3 -m unittest discover -s ws_cobot2/src/lockerbot_storage/tests -v
python3 ws_cobot2/src/lockerbot_storage/examples/attendance_and_badge.py
```

예제는 `TemporaryDirectory` 안에 전용 DB를 만들고 종료 시 삭제한다. 운영 기본 경로를 사용하지 않는다. 테스트도 각 테스트의 임시 디렉터리에 DB를 만든다. `setup.py`, `package.xml`, `resource/lockerbot_storage`는 향후 workspace 설치를 위한 `ament_python` 패키지 메타데이터이며 ROS2 실행 노드나 메시지는 정의하지 않는다. Python 직접 실행에는 이 메타데이터 설치도 필요 없다.

운영 경로를 선택해 명시적으로 초기화하는 호출은 다음과 같다. 이 코드는 예제 스크립트에서 실행하지 않는다.

```python
from lockerbot_storage import Storage

db = Storage()  # ~/.local/share/lockerbot/records.sqlite3, 아직 생성 안 됨
db.initialize()  # 명시적 운영 초기화. 기존 기록 보존
```

## 유지환 담당 코드에서 연결할 호출 예시

아래는 Python 호출 예시다. 확정된 ROS2 인터페이스가 아니며 출근 확정 시점을 정하지 않는다. 전체 실행 예제는 `examples/attendance_and_badge.py`에 있다.

```python
from datetime import datetime, timezone

# db: 명시적으로 초기화한 Storage. 등록 ID와 개별 출입증 ID는 호출부가 관리.
# 사용자·카드는 사전 등록되어 있다고 가정한다.
before = next(i for i in db.list_items(user_id) if i["item_id"] == badge_item_id)

# 팀 업무 규칙에 따라 출근을 확정한 뒤, 보존해 둔 ID/시각으로 기록.
attendance_payload = dict(
    user_id=user_id, event_type="CHECK_IN",
    event_id=stable_attendance_event_id, occurred_at=confirmed_attendance_time,
)
db.record_attendance(**attendance_payload)

# 별도로 개별 출입증 보관 성공을 확인한 뒤 전달. 요청 접수 때는 호출하지 않는다.
badge_result_payload = dict(
    user_id=user_id, item_id=badge_item_id, action="STORE", outcome="SUCCESS",
    target_location=confirmed_badge_slot, event_id=stable_badge_result_event_id,
    occurred_at=confirmed_badge_store_time,
    expected_updated_at=before["updated_at"],
)
db.record_item_result(**badge_result_payload)

# 저장 응답을 못 받았을 때: 위에서 보존한 동일 인자로 재전송.
db.record_item_result(**badge_result_payload)

# 저장 시각은 UTC. 표시할 때만 한국 시각으로 변환한다.
from zoneinfo import ZoneInfo
event = db.attendance_history(user_id)[-1]
print(datetime.fromisoformat(event["occurred_at"]).astimezone(ZoneInfo("Asia/Seoul")))
```

강승묵 담당 흐름도 같은 함수로 `STORE`/`RETURN`의 개별 결과를 전달한다. 실제 작업 전 `list_items()`에서 대상의 관측 시각을 보존하고, 성공 물품만 SUCCESS, 상태 불변 확인 실패는 FAILED_UNCHANGED, 위치 불명은 UNKNOWN으로 각각 전달한다. 여러 물품 전체를 하나의 성공으로 저장하지 않는다.

## 직접 검증 결과와 미정 사항

실행 환경: Python 3.12.3, SQLite 3.45.1. 2026-11-27 요구사항 재검토·수정 후 임시 DB 기반 `unittest` **33개 테스트 통과**, 출근·출입증 보관 Python 예제 정상 실행. Python 문법·package.xml 파싱, `setup.py check`, `git diff --check`, 실행 파일 Git 제외 패턴도 확인했다. 이전 CakeBot의 테스트 결과나 개수를 가져오지 않았다.

| 요구/추가 확인 | 실제 결과 |
| --- | --- |
| 출근 → 외출 → 복귀 → 퇴근 누적, 물품 없는 사용자 | 통과 |
| 보관 성공·현재 목록, 트레이 반환·목록 제외 | 통과. ON_TRAY이며 WITH_USER로 바꾸지 않음 |
| 상태 불변 확인 실패 | 통과. 상태·위치·갱신 시각·마지막 확인 정보 전체 유지 |
| 결과 불명과 마지막 확인 구분 | 통과. 현재 위치 NULL, 마지막 STORED 위치/시각 유지 |
| 여러 물품 중 일부 성공 | 통과. 같은 종류의 서로 다른 ID 중 성공 물품만 보관됨 |
| 같은 이벤트 재전송, 후속 상태 변경 뒤 과거 성공 재전송 | 통과. 상태 검사보다 중복 비교 우선 |
| ID 충돌·모든 입력 비교·다른 이벤트 계열의 ID 충돌 | 통과 |
| 없는 사용자/물품·다른 소유자 | 통과. Python 검사와 DB 복합 FK 검증 |
| DB 재연결·재초기화 기록 보존 | 통과 |
| 이력 삽입 실패 및 상태 UPDATE 이후 오류 주입 | SUCCESS와 UNKNOWN 모두 통과. 전체 rollback, 상태/이력 일관성 유지, 연결 정리 후 재쓰기 가능 |
| 같은 물품 결과 동시 12건 재전송 | 모두 같은 이력 반환, 실제 적용 1건 |
| 서로 다른 ID·다른 목적지의 동시 결과 8건 | 1건 확정, 7건 오래된 관측 거부, 상태와 이력 일치 |
| 같은 ID·다른 목적지의 동시 결과 8건 | 1건 확정, 7건 ID 충돌 |
| 출입 동일 이벤트 동시 8건 | 실제 적용 1건 |
| 서로 다른 물품 동시 6건 | 6건 모두 확정 |
| 신규 DB 동시 초기화 6건 | 통과. 기존 구조 중복 생성 없음 |
| UTC 정규화·한국 표시, SQL 바인딩·CHECK·FK, 필수 인자 | 통과 |
| import/객체 구성의 무부작용·일반 조회의 DB 자동 생성 방지 | 별도 프로세스와 임시 경로에서 통과 |
| 미지원 버전 2/99 및 버전 없는 기존 DB | 거부·기존 자료 보존 확인 |
| 초안과 같은 v1이지만 식별값이 다른 DB, 다른 애플리케이션 DB | 거부·초안 자료 보존 확인 |
| 최신 상태 불변 실패보다 오래된 성공·불명·실패 수신 | 모두 거부. 최신 실패 이력과 현재 상태의 모순 방지 |
| 실제 재시도 결과에 새 ID 사용 | 기존 실패와 새 성공 모두 누적. 과거 실패 재전송도 중복 처리 |
| 연속 UNKNOWN 및 불명 상태에서 FAILED_UNCHANGED | 현재 위치 NULL과 마지막 확인 정보 보존 |
| 관측 전 UNKNOWN의 처리 | 마지막 확인 상태·위치·시각을 지어내지 않고 NULL 유지 |
| 새로 확인된 STORED → STORED 배치, 마지막 WITH_USER 이후 트레이 배치 | 호출부의 확정 결과 기록. 임의 업무 전이 규칙으로 차단하지 않음 |
| 성공/불명이 섞인 동시 결과 8건 | 1건 확정, 7건 오래된 관측 거부. 현재 상태·위치와 저장 이력 일치 |
| `sqliteXlegacy`처럼 내부 접두사와 비슷한 이름의 기존 테이블 | 초기화 거부, 기존 자료와 버전/식별값 보존 |

동시 시험은 같은 호스트에서 스레드마다 독립 Storage/SQLite 연결을 열어 수행했다. 실제 로봇, ROS2 메시지 송수신, ament/colcon 빌드, 장비 통합, PC 간 통신, 전원 차단/실제 디스크 고장은 검증하지 않았다. 오류 주입은 SQLite 트리거로 수행했다.

## 최초 요구사항 대조 결과

| 요구사항 | 검토 결과 |
| --- | --- |
| 1. 작업 위치·보존 | 사용자 추가 허용에 따라 현 폴더에 clone. AGENTS.md/Git 상태 확인, 초안·장비·Mermaid 보존, commit/push/PR 없음 |
| 2. 분업·범위 | 두 담당자가 사용할 공통 저장 API만 구현. 로봇·인식·대화·근태 계산 없음 |
| 3. 미정 인터페이스 | ROS 없이 실행. 메시지/요청·응답/배치 미확정, 내부 API와 어댑터 연결 지점 문서화 |
| 4. CakeBot 선택 적용 | 채택/보류/제외 이유 명시. 4개 테이블과 기존 이벤트 비교를 유지하며 별도 실행·중복·복구 구조 없음 |
| 5. 저장 데이터 | 사용자, 출입 4종, 개별 물품/분류/소유자/상태/위치, 결과·전후 상태·목적지·시각·사유 저장 |
| 6. 업무 의미 | 개별 확정 결과만 입력, 부분 성공 독립 처리, ON_TRAY와 WITH_USER 구분, UNKNOWN과 마지막 확인 구분. 요청되지 않은 성공 전이 제한 제거 |
| 7. 데이터 보호 | 중복 우선·충돌 오류, 트랜잭션/FK/제약/바인딩, 명시 초기화·비파괴 재초기화, 경로/UTC/버전/실행 데이터 제외 |
| 8. 함수·예제 | 초기화·등록·출입/물품 결과 저장·4종 조회 제공. 유지환 담당 호출 예제는 전용 임시 DB에서 실행 |
| 9. 검증 | 최초 필수 시나리오와 위 회귀 시나리오를 임시 DB에서 실행. 실제 장비/ROS2 검증과 구분 |
| 10. 설계·보고 | 최소 구조·상태·선택 이유·실행 명령·미정 사항 기록. 재검토에서 아래 세 항목 수정 |

재검토에서 수정한 항목은 기존 DB 검사에서 SQL LIKE의 `_` 와일드카드 오인 제거, 최신 실패 이력을 무시한 과거 결과 적용 방지, 저장 모듈이 임의로 정했던 성공 전이 규칙 및 `InvalidTransitionError` 제거다. 테이블·필드·스키마 버전은 바꾸지 않았고 기존 지원 v1 DB는 그대로 사용할 수 있다. `expected_updated_at` 비교와 `application_id`는 각각 동시 덮어쓰기 차단, 동일 v1인 미검증 초안 DB 오인 차단에 필요한 최소 보호로 유지했다.

팀 합의 후 연결할 부분은 다음과 같다.

1. 출입 확정 시점과 외출/퇴근 출입증 반환 정책. 저장 계층의 정책으로 만들지 않음.
2. 인증 사용자 ID, 개별 물품 ID/소유자 연결, 개별 결과 판정 근거, 위치 식별자 규약.
3. 안정된 이벤트 ID·원본 발생 시각·재전송 인자 보존 방법. 수신부는 전송할 때마다 ID를 다시 생성하지 않음.
4. 실제 통신 필드/요청·응답/오류 매핑, 지연·시계 차이·동시 관측 처리. 외부 메시지를 현재 Python API로 변환하는 어댑터를 추가.
5. 저장 담당 노드/서버/호스트, DB 경로, 운영 권한, 백업 주기·보존 정책. 태블릿의 DB 직접 공유를 전제하지 않음.

이 결정들과 독립적인 저장·조회·원자성·중복 처리는 구현·검증했다.
