"""유지환 담당 흐름의 Python 호출 예시. ROS2 규격/실물 동작을 정의하지 않는다."""

from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from zoneinfo import ZoneInfo

from lockerbot_storage import Storage


def main():
    # 운영 기본 경로를 사용하지 않는다. 실행이 끝나면 예제 DB도 삭제한다.
    with TemporaryDirectory(prefix="lockerbot-example-") as directory:
        db = Storage(Path(directory) / "example.sqlite3")
        db.initialize()
        db.register_user("employee-001", "유지환")
        start = datetime.now(timezone.utc)
        db.register_item("badge-001", "employee-001", "출입증", "ACCESS_CARD",
                         status="WITH_USER", location="user:employee-001", observed_at=start)

        # 인증 성공만으로 호출하지 않는다. 팀 업무 규칙에 따라 출근 확정 후 호출.
        # UUID 등을 생성한다면 최초 결과 생성 시 한 번만 생성하고 인자 전체를 보존한다.
        attendance = dict(user_id="employee-001", event_type="CHECK_IN",
                          event_id="example-attendance-001", occurred_at=start + timedelta(seconds=1))
        db.record_attendance(**attendance)

        before = db.list_items("employee-001")[0]
        # 실제 코드에서는 개별 카드의 배치 성공 결과를 확인한 뒤 아래 값을 전달한다.
        confirmed_badge_result = dict(
            user_id="employee-001", item_id="badge-001", action="STORE", outcome="SUCCESS",
            target_location="badge-slot:001", event_id="example-badge-store-001",
            occurred_at=start + timedelta(seconds=2), expected_updated_at=before["updated_at"],
        )
        saved = db.record_item_result(**confirmed_badge_result)
        assert db.record_item_result(**confirmed_badge_result) == saved  # 응답 유실 후 같은 결과 재전송

        print("출입 이력:", db.attendance_history("employee-001"))
        print("확인된 보관 목록:", db.list_items("employee-001", stored_only=True))
        print("물품 이력:", db.item_history("badge-001"))
        print("한국 시각:", datetime.fromisoformat(saved["occurred_at"]).astimezone(ZoneInfo("Asia/Seoul")))


if __name__ == "__main__":
    main()
