"""All databases are temporary. No ROS, robot, network, or operating DB is used."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import os
import sqlite3
import subprocess
import sys
import unittest
from zoneinfo import ZoneInfo

from lockerbot_storage import (
    EventConflictError, OwnershipError, SchemaVersionError,
    StaleStateError, Storage, UnknownReferenceError,
)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="lockerbot-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "records.sqlite3"
        self.db = Storage(self.path)
        self.db.initialize()
        self.db.register_user("u1", "강승묵")
        self.db.register_user("u2", "유지환")
        self.start = datetime(2026, 11, 27, 0, tzinfo=timezone.utc)
        self.add_item("key-1")

    def add_item(self, item_id, **kwargs):
        self.db.register_item(item_id, "u1", "차키", observed_at=self.start,
                              status="WITH_USER", location="user:u1", **kwargs)

    def item(self, item_id="key-1"):
        return next(item for item in self.db.list_items("u1") if item["item_id"] == item_id)

    def result_args(self, event_id="store-1", *, item_id="key-1", action="STORE",
                    outcome="SUCCESS", second=1, **overrides):
        args = dict(user_id="u1", item_id=item_id, action=action, outcome=outcome,
                    target_location="drawer:1" if action == "STORE" else "tray:1",
                    event_id=event_id, occurred_at=self.start + timedelta(seconds=second),
                    expected_updated_at=self.item(item_id)["updated_at"],
                    reason={"SUCCESS": "", "FAILED_UNCHANGED": "상태 변화 없음 확인",
                            "UNKNOWN": "현재 위치 확인 불가"}.get(outcome, ""))
        args.update(overrides)
        return args

    def test_attendance_sequence_and_user_without_items(self):
        kinds = ("CHECK_IN", "GO_OUT", "RETURN", "CHECK_OUT")
        for index, kind in enumerate(kinds):
            self.db.record_attendance("u2", kind, event_id=f"attendance-{index}",
                                      occurred_at=self.start + timedelta(hours=index))
        self.assertEqual([], self.db.list_items("u2"))
        self.assertEqual(list(kinds), [event["event_type"] for event in self.db.attendance_history("u2")])
        # No attendance state machine or attendance/item success coupling is invented.
        self.db.record_attendance("u2", "CHECK_IN", event_id="second-in", occurred_at=self.start)
        self.assertEqual(5, len(self.db.attendance_history("u2")))

    def test_store_then_return_means_on_tray(self):
        self.db.record_item_result(**self.result_args())
        self.assertEqual(["key-1"], [i["item_id"] for i in self.db.list_items("u1", stored_only=True)])
        returned = self.db.record_item_result(**self.result_args("return-1", action="RETURN", second=2))
        self.assertEqual("ON_TRAY", self.item()["status"])
        self.assertEqual("tray:1", self.item()["location"])
        self.assertEqual("STORED", returned["previous_status"])
        self.assertEqual("drawer:1", returned["previous_location"])
        self.assertEqual([], self.db.list_items("u1", stored_only=True))
        self.assertEqual(2, len(self.db.item_history("key-1")))

    def test_confirmed_unchanged_failure_preserves_entire_state(self):
        self.db.record_item_result(**self.result_args())
        before = self.item()
        result = self.db.record_item_result(**self.result_args(
            "failed", action="RETURN", outcome="FAILED_UNCHANGED", second=2))
        self.assertEqual(before, self.item())
        self.assertEqual(result["previous_status"], result["resulting_status"])
        self.assertEqual(2, len(self.db.item_history("key-1")))

    def test_unknown_clears_current_location_and_keeps_last_confirmed(self):
        self.db.record_item_result(**self.result_args())
        before = self.item()
        args = self.result_args("unknown", action="RETURN", outcome="UNKNOWN", second=2,
                                reason="물품 낙하 후 위치 확인 불가")
        event = self.db.record_item_result(**args)
        unknown = self.item()
        self.assertEqual("UNKNOWN", unknown["status"])
        self.assertIsNone(unknown["location"])
        self.assertEqual("STORED", unknown["last_confirmed_status"])
        self.assertEqual("drawer:1", unknown["last_confirmed_location"])
        self.assertEqual(before["updated_at"], unknown["last_confirmed_at"])
        self.assertNotEqual(before["updated_at"], unknown["updated_at"])
        self.assertIsNone(event["resulting_location"])
        self.assertEqual([], self.db.list_items("u1", stored_only=True))
        self.assertEqual(event, self.db.record_item_result(**args))
        # Only a newly confirmed physical completion restores known state; no auto recovery.
        self.db.record_item_result(**self.result_args("new-return", action="RETURN", second=3))
        self.assertEqual("ON_TRAY", self.item()["status"])

    def test_default_registration_does_not_infer_user_possession(self):
        self.db.register_item("badge", "u2", "출입증", "ACCESS_CARD")
        badge = self.db.list_items("u2")[0]
        self.assertEqual("UNKNOWN", badge["status"])
        self.assertIsNone(badge["location"])
        self.assertIsNone(badge["last_confirmed_at"])
        self.assertEqual([], self.db.item_history("badge"))

    def test_multiple_items_partial_success_and_individual_ids(self):
        self.add_item("key-2")  # Same class/name, distinct item ID.
        self.db.record_item_result(**self.result_args())
        self.db.record_item_result(**self.result_args("failed-2", item_id="key-2", outcome="FAILED_UNCHANGED"))
        self.assertEqual("WITH_USER", self.item("key-2")["status"])
        self.assertEqual(["key-1"], [i["item_id"] for i in self.db.list_items("u1", stored_only=True)])

    def test_duplicate_precedes_state_and_time_validation_even_after_later_result(self):
        args = self.result_args()
        saved = self.db.record_item_result(**args)
        self.assertEqual(saved, self.db.record_item_result(**args))
        self.db.record_item_result(**self.result_args("returned", action="RETURN", second=2))
        self.assertEqual(saved, self.db.record_item_result(**args))
        self.assertEqual("ON_TRAY", self.item()["status"])
        self.assertEqual(2, len(self.db.item_history("key-1")))

    def test_item_id_conflict_checks_all_input_fields(self):
        args = self.result_args()
        self.db.record_item_result(**args)
        variations = dict(user_id="u2", item_id="missing", action="RETURN", outcome="UNKNOWN",
                          target_location="drawer:2", occurred_at=self.start + timedelta(seconds=9),
                          expected_updated_at="different", reason="different reason")
        for field, value in variations.items():
            with self.subTest(field=field), self.assertRaises(EventConflictError):
                self.db.record_item_result(**dict(args, **{field: value}))
        self.assertEqual(1, len(self.db.item_history("key-1")))

    def test_attendance_duplicate_conflict_and_cross_family_ids(self):
        args = dict(user_id="u1", event_type="CHECK_IN", event_id="a1", occurred_at=self.start)
        saved = self.db.record_attendance(**args)
        self.assertEqual(saved, self.db.record_attendance(**args))
        for changes in (dict(user_id="u2"), dict(event_type="RETURN"),
                        dict(occurred_at=self.start + timedelta(seconds=1))):
            with self.assertRaises(EventConflictError):
                self.db.record_attendance(**dict(args, **changes))
        with self.assertRaises(EventConflictError):
            self.db.record_item_result(**self.result_args("a1"))
        self.db.record_item_result(**self.result_args())
        with self.assertRaises(EventConflictError):
            self.db.record_attendance(**dict(args, event_id="store-1"))

    def test_utc_normalization_and_korean_display(self):
        korea = self.start.astimezone(ZoneInfo("Asia/Seoul"))
        saved = self.db.record_attendance("u1", "CHECK_IN", event_id="utc", occurred_at=korea)
        self.assertEqual("2026-11-27T00:00:00.000000+00:00", saved["occurred_at"])
        self.assertEqual(saved, self.db.record_attendance("u1", "CHECK_IN", event_id="utc", occurred_at=self.start))
        self.assertEqual(9, datetime.fromisoformat(saved["occurred_at"]).astimezone(ZoneInfo("Asia/Seoul")).hour)

    def test_missing_references_and_foreign_ownership_are_rejected(self):
        with self.assertRaises(UnknownReferenceError):
            self.db.record_attendance("missing", "CHECK_IN", event_id="bad", occurred_at=self.start)
        with self.assertRaises(UnknownReferenceError):
            self.db.register_item("bad", "missing", "차키")
        for changes, error in ((dict(user_id="missing"), UnknownReferenceError),
                               (dict(item_id="missing"), UnknownReferenceError),
                               (dict(user_id="u2"), OwnershipError)):
            with self.assertRaises(error):
                self.db.record_item_result(**dict(self.result_args(), **changes))
        self.assertEqual([], self.db.item_history("key-1"))
        self.assertEqual("WITH_USER", self.item()["status"])

    def test_stale_snapshot_and_delayed_result_are_rejected(self):
        initial = self.result_args()
        self.db.record_item_result(**initial)
        with self.assertRaises(StaleStateError):
            self.db.record_item_result(**dict(initial, event_id="stale"))
        with self.assertRaises(StaleStateError):
            self.db.record_item_result(**self.result_args("late", action="RETURN", second=0))
        self.assertEqual(1, len(self.db.item_history("key-1")))

    def test_confirmed_success_does_not_require_an_invented_workflow_sequence(self):
        self.db.record_item_result(**self.result_args())
        # A newly confirmed placement may update a previously known stored location.
        moved = self.db.record_item_result(**self.result_args(
            "new-placement", second=2, target_location="drawer:2"))
        self.assertEqual("STORED", moved["previous_status"])
        self.assertEqual("STORED", moved["resulting_status"])
        self.assertEqual("drawer:2", self.item()["location"])
        self.add_item("key-2")
        # Last known WITH_USER must not overrule a newly confirmed tray placement.
        returned = self.db.record_item_result(**self.result_args(
            "confirmed-tray", item_id="key-2", action="RETURN"))
        self.assertEqual("WITH_USER", returned["previous_status"])
        self.assertEqual("ON_TRAY", self.item("key-2")["status"])

    def test_failure_history_prevents_older_results_from_overriding_current_state(self):
        initial = self.result_args()
        saved = self.db.record_item_result(**initial)
        self.db.record_item_result(**self.result_args(
            "later-failure", action="RETURN", outcome="FAILED_UNCHANGED", second=3))
        before = self.item()
        for outcome in ("SUCCESS", "UNKNOWN", "FAILED_UNCHANGED"):
            with self.subTest(outcome=outcome), self.assertRaises(StaleStateError):
                self.db.record_item_result(**self.result_args(
                    f"old-{outcome}", action="RETURN", outcome=outcome, second=2))
        self.assertEqual(before, self.item())
        self.assertEqual(2, len(self.db.item_history("key-1")))
        # Replay is checked before the newer failure timestamp too.
        self.assertEqual(saved, self.db.record_item_result(**initial))

    def test_new_physical_retry_uses_new_id_and_preserves_failed_history(self):
        args = self.result_args("failed-attempt", outcome="FAILED_UNCHANGED")
        failed = self.db.record_item_result(**args)
        self.db.record_item_result(**self.result_args("new-attempt", second=2))
        self.assertEqual(failed, self.db.record_item_result(**args))
        self.assertEqual(["FAILED_UNCHANGED", "SUCCESS"],
                         [event["outcome"] for event in self.db.item_history("key-1")])
        self.assertEqual("STORED", self.item()["status"])

    def test_repeated_unknown_and_unchanged_failure_preserve_last_confirmation(self):
        self.db.record_item_result(**self.result_args())
        confirmed = self.item()
        for second in (2, 3):
            self.db.record_item_result(**self.result_args(
                f"unknown-{second}", action="RETURN", outcome="UNKNOWN", second=second))
            unknown = self.item()
            self.assertEqual("UNKNOWN", unknown["status"])
            self.assertIsNone(unknown["location"])
            for field in ("last_confirmed_status", "last_confirmed_location", "last_confirmed_at"):
                self.assertEqual(confirmed[field], unknown[field])
        self.db.record_item_result(**self.result_args(
            "unchanged-unknown", action="RETURN", outcome="FAILED_UNCHANGED", second=4))
        self.assertEqual(unknown, self.item())

    def test_unobserved_unknown_has_no_fabricated_last_confirmation(self):
        self.db.register_item("unobserved", "u1", "출입증", "ACCESS_CARD", observed_at=self.start)
        self.db.record_item_result(**self.result_args(
            "unknown-initial", item_id="unobserved", outcome="UNKNOWN"))
        item = self.item("unobserved")
        self.assertEqual("UNKNOWN", item["status"])
        self.assertIsNone(item["location"])
        self.assertIsNone(item["last_confirmed_status"])
        self.assertIsNone(item["last_confirmed_location"])
        self.assertIsNone(item["last_confirmed_at"])

    def test_reconnect_reinitialize_preserves_all_records(self):
        self.db.record_item_result(**self.result_args())
        self.db.record_attendance("u1", "CHECK_IN", event_id="a", occurred_at=self.start)
        before = (self.item(), self.db.item_history("key-1"), self.db.attendance_history("u1"))
        self.db = Storage(self.path)
        self.db.initialize()
        self.db.initialize()
        self.assertEqual(before, (self.item(), self.db.item_history("key-1"), self.db.attendance_history("u1")))

    def test_sql_constraints_and_foreign_keys_enabled_on_every_connection(self):
        for write in (False, True, False):
            with self.db._connection(write=write) as conn:
                self.assertEqual(1, conn.execute("PRAGMA foreign_keys").fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError), self.db._connection(write=True) as conn:
            conn.execute("INSERT INTO attendance_events VALUES ('bad','missing','CHECK_IN','time')")
        with self.assertRaises(sqlite3.IntegrityError), self.db._connection(write=True) as conn:
            conn.execute("UPDATE items SET status='BAD' WHERE item_id='key-1'")
        with self.assertRaises(sqlite3.IntegrityError), self.db._connection(write=True) as conn:
            conn.execute("UPDATE items SET status='UNKNOWN' WHERE item_id='key-1'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.register_user("u1", "다른 이름")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_item("key-1")
        with self.db._connection() as conn:
            self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())

    def test_rollback_when_history_insert_or_state_update_fails(self):
        for target, outcome in ((table, outcome) for table in ("item_events", "items")
                                for outcome in ("SUCCESS", "UNKNOWN")):
            with self.subTest(target=target, outcome=outcome):
                before = self.item()
                # AFTER UPDATE exercises rollback after both history and state were written.
                operation = "BEFORE INSERT" if target == "item_events" else "AFTER UPDATE"
                with sqlite3.connect(self.path) as conn:
                    conn.execute(f"""CREATE TRIGGER inject_failure {operation} ON {target}
                                     BEGIN SELECT RAISE(FAIL, 'injected disk/write failure'); END""")
                args = self.result_args(f"retry-{target}-{outcome}", outcome=outcome)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.record_item_result(**args)
                self.assertEqual(before, self.item())
                self.assertEqual([], self.db.item_history("key-1"))
                with sqlite3.connect(self.path) as conn:
                    conn.execute("DROP TRIGGER inject_failure")
        # Connection/lock cleaned up; exact failed input can now be saved.
        self.db.record_item_result(**args)
        self.assertEqual("UNKNOWN", self.item()["status"])

    def test_concurrent_same_event_is_applied_once(self):
        args = self.result_args()
        barrier = Barrier(12)

        def run(_):
            barrier.wait(timeout=10)
            return Storage(self.path).record_item_result(**args)

        with ThreadPoolExecutor(max_workers=12) as pool:
            rows = list(pool.map(run, range(12)))
        self.assertTrue(all(row == rows[0] for row in rows))
        self.assertEqual(1, len(self.db.item_history("key-1")))
        self.assertEqual("STORED", self.item()["status"])

    def test_concurrent_conflicting_results_cannot_overwrite_state(self):
        barrier = Barrier(8)
        args = self.result_args()

        def run(index):
            barrier.wait(timeout=10)
            try:
                return Storage(self.path).record_item_result(**dict(
                    args, event_id=f"racing-{index}", target_location=f"drawer:{index}"))
            except StaleStateError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            successes = [row for row in pool.map(run, range(8)) if row is not None]
        self.assertEqual(1, len(successes))
        self.assertEqual(successes[0]["target_location"], self.item()["location"])
        self.assertEqual(1, len(self.db.item_history("key-1")))

    def test_concurrent_same_id_different_contents_are_conflicts(self):
        args = self.result_args()
        barrier = Barrier(8)

        def run(index):
            barrier.wait(timeout=10)
            try:
                return Storage(self.path).record_item_result(**dict(args, target_location=f"drawer:{index}"))
            except EventConflictError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            successes = [row for row in pool.map(run, range(8)) if row is not None]
        self.assertEqual(1, len(successes))
        self.assertEqual(successes[0]["target_location"], self.item()["location"])
        self.assertEqual(1, len(self.db.item_history("key-1")))

    def test_concurrent_success_and_unknown_cannot_silently_overwrite_each_other(self):
        args = self.result_args()
        barrier = Barrier(8)

        def run(index):
            payload = dict(args, event_id=f"mixed-{index}")
            if index % 2:
                payload.update(outcome="UNKNOWN", reason="배치 후 위치 확인 불가")
            barrier.wait(timeout=10)
            try:
                return Storage(self.path).record_item_result(**payload)
            except StaleStateError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            successes = [row for row in pool.map(run, range(8)) if row is not None]
        self.assertEqual(1, len(successes))
        self.assertEqual(successes[0]["resulting_status"], self.item()["status"])
        self.assertEqual(successes[0]["resulting_location"], self.item()["location"])
        self.assertEqual(1, len(self.db.item_history("key-1")))

    def test_concurrent_attendance_duplicate_is_applied_once(self):
        barrier = Barrier(8)

        def run(_):
            barrier.wait(timeout=10)
            return Storage(self.path).record_attendance(
                "u2", "CHECK_IN", event_id="concurrent-in", occurred_at=self.start)

        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(run, range(8)))
        self.assertTrue(all(row == rows[0] for row in rows))
        self.assertEqual(1, len(self.db.attendance_history("u2")))

    def test_direct_sql_wrong_owner_is_rejected_by_composite_foreign_key(self):
        # Python owner check is backed by a composite foreign key as well.
        event = self.db.record_item_result(**self.result_args())
        event.update(event_id="wrong-owner", user_id="u2")
        with self.assertRaises(sqlite3.IntegrityError), self.db._connection(write=True) as conn:
            self.db._insert(conn, "item_events", event)
        self.assertEqual(1, len(self.db.item_history("key-1")))

    def test_concurrent_independent_items_all_succeed(self):
        for index in range(6):
            self.add_item(f"parallel-{index}")
        args = [self.result_args(f"p-{index}", item_id=f"parallel-{index}") for index in range(6)]
        barrier = Barrier(6)

        def run(payload):
            barrier.wait(timeout=10)
            return Storage(self.path).record_item_result(**payload)

        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(6, len(list(pool.map(run, args))))
        self.assertEqual(6, len(self.db.list_items("u1", stored_only=True)))

    def test_input_validation_and_sql_parameter_binding(self):
        for changes in (dict(event_id=""), dict(occurred_at=datetime(2026, 1, 1)),
                        dict(outcome="FAILED"), dict(action="REQUEST"),
                        dict(outcome="UNKNOWN", reason=""), dict(target_location="")):
            with self.assertRaises(ValueError):
                self.db.record_item_result(**self.result_args(**changes))
        with self.assertRaises(TypeError):
            self.db.record_attendance("u1", "CHECK_IN", occurred_at=self.start)
        tricky = "user'); DROP TABLE users; --"
        self.db.register_user(tricky, "O'Connor")
        self.db.record_attendance(tricky, "CHECK_IN", event_id=tricky, occurred_at=self.start)
        self.assertEqual(1, len(self.db.attendance_history(tricky)))
        self.assertEqual([], self.db.attendance_history("u1"))

    def test_schema_versions_refuse_unsupported_and_unversioned_nonempty_db(self):
        for version in (2, 99):
            path = Path(self.directory.name) / f"future-{version}.db"
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE sentinel(value TEXT)")
                conn.execute("INSERT INTO sentinel VALUES ('preserve')")
                conn.execute(f"PRAGMA user_version={version}")
            db = Storage(path)
            with self.assertRaises(SchemaVersionError):
                db.initialize()
            with self.assertRaises(SchemaVersionError):
                db.register_user("x", "name")
            with sqlite3.connect(path) as conn:
                self.assertEqual("preserve", conn.execute("SELECT value FROM sentinel").fetchone()[0])
        path = Path(self.directory.name) / "unversioned.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE legacy(value TEXT)")
        with self.assertRaises(SchemaVersionError):
            Storage(path).initialize()

    def test_import_and_construction_do_not_create_database(self):
        path = Path(self.directory.name) / "not-created" / "records.db"
        Storage(path)
        self.assertFalse(path.parent.exists())
        with self.assertRaises(sqlite3.OperationalError):
            Storage(path).list_items("u1")
        self.assertFalse(path.exists())
        # Separate process proves import/default constructor do not initialize HOME.
        env = dict(os.environ, HOME=str(Path(self.directory.name) / "isolated-home"))
        subprocess.run([sys.executable, "-c", "from lockerbot_storage import Storage; Storage()"],
                       env=env, check=True, capture_output=True)
        self.assertFalse(Path(env["HOME"]).exists())

    def test_initialization_refuses_table_names_similar_to_sqlite_internal_prefix(self):
        path = Path(self.directory.name) / "existing.db"
        with sqlite3.connect(path) as conn:
            # '_' is a wildcard in LIKE, but a literal in GLOB.
            conn.execute("CREATE TABLE sqliteXlegacy(value TEXT)")
            conn.execute("INSERT INTO sqliteXlegacy VALUES ('preserve')")
        with self.assertRaises(SchemaVersionError):
            Storage(path).initialize()
        with sqlite3.connect(path) as conn:
            self.assertEqual("preserve", conn.execute("SELECT value FROM sqliteXlegacy").fetchone()[0])
            self.assertEqual(0, conn.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(0, conn.execute("PRAGMA application_id").fetchone()[0])
            self.assertEqual([("sqliteXlegacy",)], conn.execute("SELECT name FROM sqlite_master").fetchall())

    def test_draft_v1_and_other_application_db_are_refused_without_changes(self):
        path = Path(self.directory.name) / "draft-v1.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE users(user_id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO users VALUES ('draft-user', '초안 자료')")
            conn.execute("PRAGMA user_version=1")
        db = Storage(path)
        with self.assertRaises(SchemaVersionError):
            db.initialize()
        with self.assertRaises(SchemaVersionError):
            db.list_items("draft-user")
        with sqlite3.connect(path) as conn:
            self.assertEqual("초안 자료", conn.execute("SELECT name FROM users").fetchone()[0])
            self.assertEqual(0, conn.execute("PRAGMA application_id").fetchone()[0])
        other_path = Path(self.directory.name) / "other.db"
        with sqlite3.connect(other_path) as conn:
            conn.execute("PRAGMA application_id=123")
        with self.assertRaises(SchemaVersionError):
            Storage(other_path).initialize()

    def test_concurrent_initialize_is_idempotent(self):
        path = Path(self.directory.name) / "fresh.db"
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _: Storage(path).initialize(), range(6)))
        db = Storage(path)
        db.register_user("new", "새 사용자")
        self.assertEqual([], db.list_items("new"))


if __name__ == "__main__":
    unittest.main()
