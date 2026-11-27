# ROS 2 토픽·서비스·액션 인터페이스

`ws_cobot2/src/lockerbot_interfaces`는 기존 [태블릿 흐름](tablet_interface_sequence.mmd)과 [로봇 작업 흐름](robot_operation_sequence.mmd)에 맞춘 ROS 2 Jazzy 통신 타입 패키지다. `.msg` 8개, `.srv` 5개, `.action` 4개를 정의한다. Python과 C++ 타입은 `rosidl` 빌드로 생성된다.

이름과 주고받는 데이터를 쉬운 말로 정리한 [인터페이스 요약](ros_interfaces_summary.md)을 함께 제공한다. 메시지 타입 8종 중 3종이 기본 토픽에 사용되며, 나머지 5종은 서비스·액션의 공통 데이터다. 실제 기본 토픽은 표준 카메라 영상 토픽까지 포함해 4개다.

현재 구현 범위는 **인터페이스 정의와 빌드 설정**이다. 아래 노드 이름·엔드포인트·QoS·검증 규칙은 후속 노드 구현이 따라야 할 계약이며, 발행자/구독자·서비스 서버·액션 서버·SQLite 어댑터·태블릿 WSS/HTTPS 브리지는 아직 구현하지 않았다. 인터페이스를 빌드해도 로봇은 움직이지 않는다.

## 통신 구조

| 종류 | 구조 | 사용처 |
| --- | --- | --- |
| Topic | Publisher → Message → Subscriber | 오디오, 화면·안내, 현재 질문, 카메라 영상 |
| Service | Client → Request / Server → Response | 세션 시작, 질문 응답, DB 조회·확정 결과 저장 |
| Action | Client → Goal / Server → Feedback 여러 번 → Result 한 번 | 출근·복귀·외출·퇴근, 얼굴·카드 인식, 물품 탐색, 로봇 단계 실행 |

`.action` 파일의 실제 구분 순서는 **Goal → `---` → Result → `---` → Feedback**이다. 실행 중에는 Feedback을 여러 번 보내고 마지막에 Result를 반환한다. Goal 접수/거절과 취소는 ROS 2 액션 프로토콜이 제공하며 별도 서비스나 토픽으로 중복 정의하지 않는다.

## 토픽

아래 이름은 `/lockerbot` 네임스페이스의 기본 연결 규약이다. 멀티 장비 구성은 네임스페이스/remap으로 분리한다.

| 토픽 | 타입 | 발행 → 구독 | 내용 | QoS 계약 |
| --- | --- | --- | --- | --- |
| `/lockerbot/audio` | `lockerbot_interfaces/msg/AudioChunk` | `tablet_interface_node` → `dialogue_node` | PCM 오디오와 장비·세션·스트림 ID, 순번 | best effort, volatile, keep last 20 |
| `/lockerbot/tablet_state` | `lockerbot_interfaces/msg/TabletState` | `task_manager_node` → `tablet_interface_node` | 화면, 인증 상태, 안내·음성, 진행률, 종료 정리 | reliable, volatile, keep last 10 |
| `/lockerbot/dialogue_context` | `lockerbot_interfaces/msg/DialogueContext` | `task_manager_node` → `dialogue_node` | 현재 질문 ID·종류·계획·만료 시각 | reliable, volatile, keep last 10 |
| `/lockerbot/camera/image_raw` | `sensor_msgs/msg/Image` (표준 타입) | `perception_node` → `tablet_interface_node` | 얼굴 확인 중 미리보기 영상 | sensor data: best effort, volatile, keep last 5 |

오디오는 signed PCM 16-bit little-endian 인터리브 형식이다. `sample_rate_hz > 0`, `channels > 0`, 바이트 수는 `2 * channels`의 배수여야 한다. `header.stamp`는 첫 샘플 획득 시각이다. `device_id/stream_id/sequence`로 유실·순서를 확인한다. 세션 시작 전 호출어 인식을 위해 `session_id`는 비울 수 있으며, 세션 수립 후에는 서버가 준 ID를 사용한다.

`TabletState`의 `event_id`는 음성 중복 출력을 막는 식별자다. 같은 ID 재수신 시 화면은 갱신할 수 있지만 음성을 재생하지 않는다. `clear_session=true`이면 사용자 정보·미리보기·음성 대기열을 정리한다. 상태와 질문은 휘발성으로 전달하며, 재연결 시 오래된 질문/인증 화면을 복원하지 않는다. 작업관리자가 유효 세션의 현재 화면·질문을 새로 발행해야 한다. `camera_enabled=false`는 브리지의 미리보기 연결 종료 지시다.

`DialogueContext.question_id`가 비어 있으면 현재 질문 해제다. 질문이 있으면 `question_type`은 `YES_NO`, `ITEM_SELECTION`, `FREE_TEXT` 중 하나이며 `expires_at`이 필수다. `candidate_item_ids`는 개별 DB 물품 ID다.

## 서비스

| 서비스 | 타입 | 클라이언트 → 서버 | Request | Response |
| --- | --- | --- | --- | --- |
| `/lockerbot/start_session` | `StartSession` | 대화 → 작업관리 | `request_id`, `device_id`, `wake_word`, `detected_at` | `status`, `session_id`, `expires_at` |
| `/lockerbot/submit_answer` | `SubmitAnswer` | 대화 → 작업관리 | `request_id`, `session_id`, `task_id`, `question_id`, `answer_type`, `transcript`, `selected_item_ids`, `answered_at` | `status` |
| `/lockerbot/storage/get_items` | `GetItems` | 작업관리 → 저장 어댑터 | `user_id`, `stored_only` | `status`, `items[]` |
| `/lockerbot/storage/record_attendance` | `RecordAttendance` | 작업관리 → 저장 어댑터 | 확정된 `AttendanceEvent` | `status` |
| `/lockerbot/storage/record_item_result` | `RecordItemResult` | 작업관리 → 저장 어댑터 | 개별 확정 `ItemResult` | `status` |

`StartSession` 성공은 세션 접수이며 얼굴 인증 성공을 뜻하지 않는다. 작업관리자는 활성 세션을 관리하며 바쁜 경우 `BUSY`, 만료된 세션은 `SESSION_EXPIRED`로 응답한다. 같은 `request_id`와 동일 내용을 재전송하면 기존 응답을 반환한다. 같은 ID에 다른 내용이면 `EVENT_CONFLICT`로 거절한다. 이 규칙은 `SubmitAnswer`에도 적용한다. 재전송 확인은 질문 만료/소비 여부 검사보다 먼저 한다. 중복 기억은 해당 세션 수명 동안 유지하며, 서버 재시작 후 기존 세션은 무효화한다.

`SubmitAnswer.answer_type`은 `YES`, `NO`, `ITEMS`, `TEXT`다. `YES_NO` 질문에는 YES/NO, `ITEM_SELECTION`에는 ITEMS, `FREE_TEXT`에는 TEXT만 받는다. 서버는 현재 세션·작업·질문 ID, 실제 접수 시각의 만료 여부와 선택 대상 소유권을 확인한다. `answered_at`을 과거로 지정해 만료를 우회할 수 없다. YES/NO/TEXT의 `selected_item_ids`는 비운다. ITEMS는 후보의 부분집합이며 빈 배열은 명시적 선택 없음이다. 서비스 성공은 응답을 소비했다는 뜻이며 물리 작업 성공을 뜻하지 않는다.

등록되지 않은 사용자 조회는 `NOT_FOUND`다. 등록 사용자에게 물품이 없으면 `OK`와 빈 배열을 반환한다. `stored_only=true`는 현재 `STORED`만 포함하므로, 전체 상태 확인에는 `false`를 사용한다.

## 액션

| 액션 | 타입 | 클라이언트 → 서버 | Goal | Feedback | Result |
| --- | --- | --- | --- | --- | --- |
| `/lockerbot/execute_task` | `ExecuteTask` | 대화 → 작업관리 | 세션·작업 ID, 업무 종류, 포함·제외 물품, 출입증 반환 선택, 제한 시간 | 단계, 진행률, 현재 물품, 처리 수, 안내 | 전체 `status`, 인증 사용자, 개별 결과, 미완료 물품 |
| `/lockerbot/identify_user` | `IdentifyUser` | 작업관리 → 인식 | `FACE` / `BADGE_OWNER`, 세션, 제한 시간 | 인식 단계·진행률·안내 | 실제 사용자/카드 소유자 ID·이름·신뢰도·관측 시각 |
| `/lockerbot/detect_items` | `DetectItems` | 작업관리 → 인식 | `BADGE_GRASP` / `SCAN_TRAY` / `FIND_ITEMS`, 위치·대상, 제한 시간 | 탐색 단계·진행률·검출 수 | 관측 물품·집기 자세·가림·누락 ID |
| `/lockerbot/execute_robot_step` | `ExecuteRobotStep` | 작업관리 → 로봇 실행 | 단계 종류, 위치·자세·관측 유효 기간, 결과 이벤트 ID | 실행 단계·진행률·안내 | 단계 `status`, 도달 자세, 있으면 개별 확정 물품 결과 |

### 업무 실행

`ExecuteTask.task_type`은 `CHECK_IN`(출근), `RETURN`(복귀), `GO_OUT`(외출), `CHECK_OUT`(퇴근)이다. 사용자 ID는 Goal에서 받지 않고 작업관리자의 인증된 세션에서 얻는다. `include_item_ids`/`exclude_item_ids`는 외출·퇴근 시 반환 대상을 고르는 조건이며, 출근·복귀에서는 모두 비운다. 빈 포함 배열은 해당 사용자의 반환 가능한 모든 물품, 제외 배열은 그중 제외할 물품이다. 중복 ID, 포함/제외 교집합, 타인 소유 물품은 거절한다.

출입증은 별도 정책으로 처리한다. 외출은 `return_access_card`로 선택하며 포함/제외 배열에 출입증을 넣지 않는다. 퇴근은 이 값과 관계없이 출입증 반환이 필수이고, 필수 출입증을 제외하려는 요청은 거절한다. 출근의 출입증 소유자 대조와 수납 동의, 복귀 시 얼굴 확인, 반환 전 재탐색, 가림 물품의 임시 이동·원복은 작업관리자 책임이다. `unresolved_item_ids`는 확정 성공으로 끝나지 않은 요청 물품 목록이며, 전체 탐색 실패처럼 대상 목록 자체가 불명확한 경우 빈 목록이어도 전체 성공을 의미하지 않는다.

`task_id`는 활성 중복 목표를 차단하는 업무 식별자다. 동일한 ROS Goal 재전송은 ROS 프로토콜이 다룬다. 새 Goal UUID로 완료/취소된 작업을 재실행하면 새로운 물리 작업이 될 수 있으므로 클라이언트는 자동 재실행하지 않는다. DB `event_id` 중복 방지는 물리 작업 중복 방지 기능이 아니다.

### 인식과 좌표

`IdentifyUser`는 실제로 판독된 사용자 ID를 반환한다. `BADGE_OWNER` 결과와 얼굴 확인 사용자가 같은지는 작업관리자가 비교한다. 미등록·불명확 판독은 `NOT_RECOGNIZED`이며 임의 사용자 ID를 채우지 않는다. `confidence`는 [0, 1]이며 인증 임계치는 인식 노드 설정으로 관리한다.

`DetectItems`에서 트레이가 비어 있는 정상 관측은 `OK + items=[]`다. `FIND_ITEMS`에는 `target_item_ids`가 필요하며 확인하지 못한 대상은 `missing_item_ids`에 넣는다. 누락이 있으면 전체 상태는 `NOT_FOUND` 또는 `PARTIAL_FAILURE`로 구분하고, 찾은 관측은 보존한다. 가림·잘못된 자세는 `occluded`, `pose_valid`로 표시한다. `BADGE_GRASP`에서 유효한 집기 자세를 얻지 못하면 `POSE_INVALID`다.

`DetectedItem.detection_id`는 영상 관측 ID이고 `item_id`는 등록된 개별 물품 ID다. 검출 클래스명/라벨을 개별 물품 ID로 쓰지 않는다. 대응이 확정되지 않은 `item_id`는 빈 값으로 반환하고, 작업관리자가 소유자·개별 물품과 연결하기 전에는 보관/반환 결과를 저장하지 않는다.

모든 `PoseStamped`는 미터와 단위 쿼터니언을 사용한다. 관측 자세의 `header.stamp`는 관측 시각, `header.frame_id`는 실제 좌표계다. 서버는 0이 아닌 시각, 유효한 frame/TF, 유한한 좌표·회전, `valid_until`/`observation_valid_until`과 도달 가능한 작업 범위를 검사한다. 변환·좌표·IK 검사 실패는 동작 전에 거절한다. 실제 로봇 기준 좌표계·보정값·관측 유효 시간·자세별 위치는 장비 설정으로 확정하며 타입에 하드코딩하지 않는다.

### 로봇 단계 실행

`ExecuteRobotStep.operation`은 다음과 같다.

| operation | 필수 입력 | 결과 의미 |
| --- | --- | --- |
| `MOVE_NAMED_POSE` | `named_pose` | 등록된 대기/사용자 관측/트레이 관측 자세 이동 |
| `OPEN_DRAWER`, `CLOSE_DRAWER` | `user_id`, `target_location` | 소유자의 지정 서랍 개폐 |
| `STORE_ITEM`, `RETURN_ITEM` | `user_id`, `item_id`, 출발·목적 위치, pick/place 자세, 관측 유효 기간, `result_event_id`, `expected_updated_at` | 개별 최종 배치 시도와 물품 결과 |
| `TEMP_MOVE_ITEM`, `RESTORE_ITEM` | `user_id`, `item_id`, 출발·목적 위치, pick/place 자세, 관측 유효 기간 | 가림 해소·원복 단계. STORE/RETURN 이벤트를 만들지 않음 |

모든 Goal은 `session_id`, `task_id`, `step_id`, 양수 `timeout`을 갖는다. `named_pose` 기본 식별자는 `standby_down`, `face_observation`, `tray_observation`이며 실제 자세는 서버 설정에 있어야 한다. 사용하지 않는 문자열/배열은 비우고 사용하지 않는 자세는 무시한다. 로봇 실행부는 활성 단계 ID 중복, 허용 작업·위치, 소유자 관계와 현재 실행 상태를 검사한다. 개인 물품 이동 시 RG2 Z축 수직 유지 조건은 서버의 필수 동작 규칙이며 클라이언트가 끄는 옵션을 두지 않았다.

`reached_pose_valid=false`이면 `reached_pose`를 사용하지 않는다. `has_item_result=true`일 때만 `item_result`가 유효하다. 최종 보관/반환을 실제로 시도했다면 실패·취소에서도 확인된 SUCCESS/FAILED_UNCHANGED 또는 UNKNOWN 결과를 보고해야 한다. 접수 거절이나 동작 전 검증 실패에는 물리 결과를 만들어 내지 않는다. 임시 이동/원복의 실패·위치 불명은 단계 상태로 보고하여 작업관리자가 전체 작업을 보류한다. 임시 이동 성공을 최종 보관/반환 성공으로 저장하지 않는다.

### 접수·피드백·종료

액션 서버는 잘못된 enum, 비어 있는 필수 ID, 만료 세션, 0 이하 timeout, 처리 불가능한 동시 Goal을 접수 전에 거절한다. ROS Goal 거절 응답은 accepted=false이며 커스텀 Result를 포함하지 않는다. 접수 뒤 확인된 실패는 `abort()`와 실패 Result, 정상 완료는 `succeed()`와 성공 Result, 수락한 취소는 `canceled()`와 취소 Result로 끝낸다. 취소는 안전한 정지/인계가 가능한 지점에서 수락하며, 취소 응답 시점에 물건이 원래 위치로 돌아갔다고 추정하지 않는다.

timeout이나 취소 시 하위 액션을 정리하고, 이미 확정된 개별 물품 결과를 상위 Result에 보존한다. 전체 실패여도 완료된 물품 결과는 취소하지 않는다. 결과의 전체 `status`는 `PARTIAL_FAILURE`, `STATE_UNKNOWN`, `TIMEOUT`, `CANCELLED` 등을 구분한다. 퇴근 출입증 미반환이나 필수 원복 실패를 전체 OK로 보고하지 않는다.

`stage`는 사람이 읽을 수 있는 현재 단계 이름이다(예: `AUTHENTICATING`, `WAITING_CONSENT`, `SCANNING`, `STORING`, `RETURNING`, `RESTORING`). 로봇 명령으로 해석하지 않는다. 모든 진행률은 [0, 1], 산출 불가 시 -1이다. `completed_items`는 최종 배치 성공이 확인된 항목 수이고, 발견된 대상 수에 따라 `total_items`가 바뀔 수 있다. 진행률 1.0만으로 성공 판정하지 않고 최종 Result와 ROS 액션 종료 상태를 확인한다.

## 공통 상태와 SQLite 연결 규칙

`OperationStatus`는 모든 서비스 응답·액션 Result에 공통으로 들어간다. `success=true`는 `code=OK(0)`일 때만 사용하며, 실패는 설명 `message`를 채운다. 기본 생성값은 `success=false, code=INVALID_REQUEST(1)`로 미작성 응답이 성공으로 보이지 않게 했다.

코드는 `.msg`의 상수를 사용한다: `OK`, `INVALID_REQUEST`, `BUSY`, `SESSION_EXPIRED`, `QUESTION_EXPIRED`, `NOT_RECOGNIZED`, `IDENTITY_MISMATCH`, `NOT_FOUND`, `POSE_INVALID`, `TIMEOUT`, `CANCELLED`, `PARTIAL_FAILURE`, `EXECUTION_FAILED`, `STATE_UNKNOWN`, `EVENT_CONFLICT`, `STALE_STATE`, `STORAGE_ERROR`, `OWNERSHIP_ERROR`.

저장 어댑터의 매핑 대상은 기존 [SQLite API](sqlite_storage.md)다. 저장 모듈 자체는 ROS 독립성을 유지한다.

| 인터페이스 | Python API/변환 |
| --- | --- |
| `GetItems` | `Storage.list_items(user_id, stored_only=...)` → `ItemState[]` |
| `AttendanceEvent` | `record_attendance(user_id, event_type, event_id=..., occurred_at=...)` |
| `ItemResult` | `record_item_result(user_id, item_id, action, outcome=..., target_location=..., event_id=..., occurred_at=..., expected_updated_at=..., reason=...)` |
| DB `None`인 위치·마지막 확인 정보 | ROS 문자열은 `""`로 직렬화. 그 외 빈 ID/위치는 오류 |
| DB `updated_at`, `last_confirmed_at` | UTC ISO-8601 문자열 그대로 전달. `expected_updated_at`은 이전 조회값을 그대로 보존 |
| ROS `occurred_at` | UTC 실제 사건 시각 → 시간대 있는 Python `datetime`. 나노초는 1000의 배수인 마이크로초 정밀도만 허용하고 나머지는 거절 |

`builtin_interfaces/Time`에는 시간대 정보가 없으므로 모든 사건·만료 시각은 UTC Unix 시간으로 해석한다. DB 사건 시각에 ROS 시뮬레이션 시간을 사용하지 않는다. 시각·duration의 `nanosec`는 0 이상 10억 미만이고 사건 시각은 0이 아니어야 한다. 여러 서버의 시계를 맞춘다. ROS 타입에 문자열 상수/범위를 정의해도 값 검증이 자동 생성되지는 않으므로 서버가 허용값과 상호 조건을 검사해야 한다.

`ItemResult.action`은 STORE/RETURN, `outcome`은 SUCCESS/FAILED_UNCHANGED/UNKNOWN이다. RETURN 성공은 **트레이 배치 확인(ON_TRAY)**이며 사용자 수령을 의미하지 않는다. FAILED_UNCHANGED는 이동하지 않았음을 확인한 실패만, 위치를 확정할 수 없으면 UNKNOWN을 쓴다. 실패/불명에는 사유가 필수다. 결과 이벤트 ID와 원본 발생 시각, 작업 전 `expected_updated_at`을 재전송 때 바꾸지 않는다. 이벤트 ID는 출입/물품 이벤트 전체에서 유일하다.

저장 응답 OK는 결과가 저장되었다는 뜻이다. UNKNOWN 물리 결과도 정상 저장되면 서비스는 OK이며 물리 성공으로 바뀌지 않는다. 동일 재전송도 OK다. `EventConflictError`→EVENT_CONFLICT, `StaleStateError`→STALE_STATE, `UnknownReferenceError`→NOT_FOUND, `OwnershipError`→OWNERSHIP_ERROR, 입력 오류→INVALID_REQUEST, DB 초기화/버전/SQL 오류→STORAGE_ERROR로 매핑한다. 저장 오류 때문에 물리 동작을 재실행하지 않는다.

## 빌드와 타입 확인

저장소 `lockerbot` 루트에서 실행한다. 이 패키지는 장비 드라이버에 의존하지 않아 단독 빌드할 수 있다.

```bash
source /opt/ros/jazzy/setup.bash
cd ws_cobot2
colcon build --packages-select lockerbot_interfaces
source install/setup.bash

ros2 interface list | rg lockerbot_interfaces
ros2 interface show lockerbot_interfaces/msg/TabletState
ros2 interface show lockerbot_interfaces/srv/StartSession
ros2 interface show lockerbot_interfaces/action/ExecuteTask
```

현재 PC에는 `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`가 설정되어 있으나 해당 라이브러리는 설치되어 있지 않다. 타입 확인·직렬화 검증은 설치된 Fast DDS로 실행했다. 같은 로딩 오류가 나면 현재 셸에서 `export RMW_IMPLEMENTATION=rmw_fastrtps_cpp` 후 확인한다. 시스템 설정은 변경하지 않았다.

Python 생성 타입 사용 예:

```python
from lockerbot_interfaces.msg import OperationStatus, TabletState
from lockerbot_interfaces.srv import StartSession
from lockerbot_interfaces.action import ExecuteTask

request = StartSession.Request()
request.request_id = "wake-001"
request.device_id = "tablet-01"
request.wake_word = "Hello ROKEY"
# detected_at에는 실제 획득 시각을 채운다.

goal = ExecuteTask.Goal()
goal.session_id = "session-from-start-session"
goal.task_id = "task-001"
goal.task_type = ExecuteTask.Goal.CHECK_IN
goal.timeout.sec = 120

# rclpy: create_publisher(TabletState, ...), create_service(StartSession, ...),
# ActionServer(node, ExecuteTask, ...) / ActionClient(node, ExecuteTask, ...)
# 응답 성공은 status.success=True와 status.code=OperationStatus.OK를 함께 지정.
```

C++에서는 `lockerbot_interfaces/msg/tablet_state.hpp`, `lockerbot_interfaces/srv/start_session.hpp`, `lockerbot_interfaces/action/execute_task.hpp`를 include한다. 소비 패키지의 `package.xml`에 `lockerbot_interfaces` 의존성을 선언한다. 실제 노드 구현은 이 계약의 세션·소유자·좌표·만료·중복 검사를 포함해야 한다.

## 검증 결과

2026-11-27, 설치된 ROS 2 Jazzy에서 임시 경로 `/tmp/lockerbot-interface-check`로 `colcon build`를 실행해 성공했다. C/C++ 타입 지원과 Python 생성 타입, 전체 17개 정의의 CMake 등록, `.msg`/`.srv`/`.action` 구분, `ros2 interface show`를 확인했다.

생성된 공개 payload 30종(메시지 8, 서비스 요청/응답 10, 액션 Goal/Result/Feedback 12)을 포함한 **CDR 직렬화·역직렬화 41건**이 통과했다. 한글 안내·PCM 배열·중첩 결과와 임시 SQLite를 사용한 필드 대응, 동일 이벤트 재전송, UTC 마이크로초·관측 토큰 보존, UNKNOWN/마지막 확인 상태 구분을 확인했다. 검증용 변환은 임시 fixture이며 운영 어댑터 구현을 의미하지 않는다. 실제 DDS 노드 간 통신·Goal 접수/취소 처리·장비 동작 검증은 포함하지 않았다.
