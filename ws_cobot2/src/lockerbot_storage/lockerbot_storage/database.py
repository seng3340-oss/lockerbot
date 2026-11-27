"""Local persistence only: callers confirm business events and physical outcomes."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


SCHEMA_VERSION = 1
APPLICATION_ID = 0x4C424F54  # LBOT; distinguish the unverified draft's unrelated v1.

SCHEMA = """
CREATE TABLE users (
    user_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(user_id)) > 0),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0)
);
CREATE TABLE attendance_events (
    event_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(event_id)) > 0),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    event_type TEXT NOT NULL CHECK(event_type IN
        ('CHECK_IN', 'GO_OUT', 'RETURN', 'CHECK_OUT')),
    occurred_at TEXT NOT NULL
);
CREATE INDEX attendance_by_user ON attendance_events(user_id, occurred_at);
CREATE TABLE items (
    item_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(item_id)) > 0),
    owner_id TEXT NOT NULL REFERENCES users(user_id),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    kind TEXT NOT NULL CHECK(kind IN ('BELONGING', 'ACCESS_CARD')),
    status TEXT NOT NULL CHECK(status IN ('WITH_USER', 'STORED', 'ON_TRAY', 'UNKNOWN')),
    location TEXT,
    updated_at TEXT NOT NULL,
    last_confirmed_status TEXT CHECK(last_confirmed_status IN
        ('WITH_USER', 'STORED', 'ON_TRAY')),
    last_confirmed_location TEXT,
    last_confirmed_at TEXT,
    UNIQUE(item_id, owner_id),
    CHECK((status = 'UNKNOWN' AND location IS NULL) OR
          (status != 'UNKNOWN' AND location IS NOT NULL AND length(trim(location)) > 0)),
    CHECK((last_confirmed_status IS NULL AND last_confirmed_location IS NULL
           AND last_confirmed_at IS NULL) OR
          (last_confirmed_status IS NOT NULL AND last_confirmed_location IS NOT NULL
           AND length(trim(last_confirmed_location)) > 0 AND last_confirmed_at IS NOT NULL)),
    CHECK(status = 'UNKNOWN' OR
          (last_confirmed_status IS NOT NULL AND status = last_confirmed_status
           AND location = last_confirmed_location AND updated_at = last_confirmed_at))
);
CREATE INDEX items_by_owner ON items(owner_id, status);
CREATE TABLE item_events (
    event_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(event_id)) > 0),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    item_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('STORE', 'RETURN')),
    outcome TEXT NOT NULL CHECK(outcome IN ('SUCCESS', 'FAILED_UNCHANGED', 'UNKNOWN')),
    expected_updated_at TEXT NOT NULL,
    previous_status TEXT NOT NULL CHECK(previous_status IN
        ('WITH_USER', 'STORED', 'ON_TRAY', 'UNKNOWN')),
    resulting_status TEXT NOT NULL CHECK(resulting_status IN
        ('WITH_USER', 'STORED', 'ON_TRAY', 'UNKNOWN')),
    previous_location TEXT,
    resulting_location TEXT,
    target_location TEXT NOT NULL CHECK(length(trim(target_location)) > 0),
    occurred_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    FOREIGN KEY(item_id, user_id) REFERENCES items(item_id, owner_id),
    CHECK((previous_status = 'UNKNOWN' AND previous_location IS NULL) OR
          (previous_status != 'UNKNOWN' AND previous_location IS NOT NULL
           AND length(trim(previous_location)) > 0)),
    CHECK((resulting_status = 'UNKNOWN' AND resulting_location IS NULL) OR
          (resulting_status != 'UNKNOWN' AND resulting_location IS NOT NULL
           AND length(trim(resulting_location)) > 0)),
    CHECK(outcome = 'SUCCESS' OR length(trim(reason)) > 0),
    CHECK((outcome = 'SUCCESS' AND resulting_location = target_location AND
           ((action = 'STORE' AND resulting_status = 'STORED') OR
            (action = 'RETURN' AND resulting_status = 'ON_TRAY'))) OR
          (outcome = 'FAILED_UNCHANGED' AND resulting_status = previous_status
           AND resulting_location IS previous_location) OR
          (outcome = 'UNKNOWN' AND resulting_status = 'UNKNOWN'
           AND resulting_location IS NULL))
);
CREATE INDEX events_by_item ON item_events(item_id, occurred_at);
"""


class StorageError(Exception):
    """Base for storage business/precondition errors (SQL errors stay sqlite3 errors)."""


class SchemaVersionError(StorageError):
    """Explicit initialization or a compatible database is required."""


class EventConflictError(StorageError):
    """An event ID was already used for different content or another event family."""


class UnknownReferenceError(StorageError):
    """The user or individual item is not registered."""


class OwnershipError(StorageError):
    """The item does not belong to the supplied user."""


class StaleStateError(StorageError):
    """The observed state changed, or the result predates state/latest history."""


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: nonempty string required")
    return value


def _time(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _choice(value, choices, field):
    if value not in choices:
        raise ValueError(f"{field}: expected one of {choices}")


class Storage:
    """One short-lived connection per call; no I/O at import or construction.

    Default: ~/.local/share/lockerbot/records.sqlite3. Pass a separate path for
    tests/examples. Call initialize() explicitly before any other operation.
    """

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = Path.home() / ".local/share/lockerbot/records.sqlite3"
        if str(db_path) == ":memory:":
            raise ValueError("file path required: each call opens a new connection")
        self.db_path = Path(db_path).expanduser().absolute()

    @contextmanager
    def _connection(self, *, write=False, initialize=False):
        # mode=rw prevents accidental creation by ordinary writes/queries.
        uri = self.db_path.as_uri() + ("?mode=rwc" if initialize else "?mode=rw")
        conn = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if write:
                # Serialize duplicate lookup + state validation + state/history write.
                conn.execute("BEGIN IMMEDIATE")
            if not initialize:
                self._check_version(conn)
            yield conn
            if write:
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _check_version(conn):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise SchemaVersionError(f"schema version {version}; supported: {SCHEMA_VERSION}")
        if conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise SchemaVersionError("not a supported lockerbot storage DB (application_id differs)")

    def initialize(self):
        """Create v1 only in an empty database; never erase or migrate existing data."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(write=True, initialize=True) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if conn.execute("PRAGMA application_id").fetchone()[0] not in (0, APPLICATION_ID):
                    raise SchemaVersionError("DB belongs to another application")
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchone():
                    raise SchemaVersionError("unversioned nonempty DB: automatic conversion refused")
                # executescript implicitly commits; execute individual DDL in this transaction.
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            else:
                self._check_version(conn)

    @staticmethod
    def _require_user(conn, user_id):
        if conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone() is None:
            raise UnknownReferenceError(f"unknown user: {user_id}")

    @staticmethod
    def _existing_event(conn, table, payload):
        # Only internal fixed table names reach SQL; all caller data is bound.
        other = "item_events" if table == "attendance_events" else "attendance_events"
        event_id = payload["event_id"]
        if conn.execute(f"SELECT 1 FROM {other} WHERE event_id=?", (event_id,)).fetchone():
            raise EventConflictError(f"event_id already used in {other}: {event_id}")
        old = conn.execute(f"SELECT * FROM {table} WHERE event_id=?", (event_id,)).fetchone()
        if old is not None:
            if any(old[key] != value for key, value in payload.items()):
                raise EventConflictError(f"event_id content differs: {event_id}")
            return dict(old)
        return None

    @staticmethod
    def _insert(conn, table, values):
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))

    def register_user(self, user_id, name):
        """Register once; duplicate IDs raise sqlite3.IntegrityError, never overwrite."""
        values = {"user_id": _text(user_id, "user_id"), "name": _text(name, "name")}
        with self._connection(write=True) as conn:
            self._insert(conn, "users", values)

    def register_item(self, item_id, owner_id, name, kind="BELONGING", *,
                      status="UNKNOWN", location=None, observed_at=None):
        """Register an individual item. Known initial state requires observation time.

        UNKNOWN is the default: ownership/registration never implies possession.
        Initial observation is metadata, not a fabricated STORE/RETURN result.
        """
        for field, value in (("item_id", item_id), ("owner_id", owner_id), ("name", name)):
            _text(value, field)
        _choice(kind, ("BELONGING", "ACCESS_CARD"), "kind")
        _choice(status, ("WITH_USER", "STORED", "ON_TRAY", "UNKNOWN"), "status")
        if status == "UNKNOWN":
            if location is not None:
                raise ValueError("UNKNOWN requires location=None")
        else:
            _text(location, "location")
            if observed_at is None:
                raise ValueError("known initial state requires observed_at")
        timestamp = _time(observed_at if observed_at is not None else datetime.now(timezone.utc))
        known = status != "UNKNOWN"
        values = dict(item_id=item_id, owner_id=owner_id, name=name, kind=kind,
                      status=status, location=location, updated_at=timestamp,
                      last_confirmed_status=status if known else None,
                      last_confirmed_location=location if known else None,
                      last_confirmed_at=timestamp if known else None)
        with self._connection(write=True) as conn:
            self._require_user(conn, owner_id)
            self._insert(conn, "items", values)

    def record_attendance(self, user_id, event_type, *, event_id, occurred_at):
        """Append an event already confirmed by the caller's business rule."""
        _choice(event_type, ("CHECK_IN", "GO_OUT", "RETURN", "CHECK_OUT"), "event_type")
        payload = dict(event_id=_text(event_id, "event_id"), user_id=_text(user_id, "user_id"),
                       event_type=event_type, occurred_at=_time(occurred_at))
        with self._connection(write=True) as conn:
            old = self._existing_event(conn, "attendance_events", payload)
            if old is not None:
                return old
            self._require_user(conn, user_id)
            self._insert(conn, "attendance_events", payload)
        return payload

    def record_item_result(self, user_id, item_id, action, *, outcome, target_location,
                           event_id, occurred_at, expected_updated_at, reason=""):
        """Append one confirmed per-item result and atomically update its state.

        expected_updated_at is copied verbatim from list_items(), before the work.
        Replays must retain all arguments, including this precondition and time.
        FAILED_UNCHANGED means no movement was confirmed; UNKNOWN means no current
        location can be asserted. Neither is an automatic retry instruction.
        """
        _choice(action, ("STORE", "RETURN"), "action")
        _choice(outcome, ("SUCCESS", "FAILED_UNCHANGED", "UNKNOWN"), "outcome")
        if not isinstance(reason, str):
            raise ValueError("reason must be a string")
        payload = dict(event_id=_text(event_id, "event_id"), user_id=_text(user_id, "user_id"),
                       item_id=_text(item_id, "item_id"), action=action, outcome=outcome,
                       target_location=_text(target_location, "target_location"),
                       occurred_at=_time(occurred_at),
                       expected_updated_at=_text(expected_updated_at, "expected_updated_at"),
                       reason=reason)
        with self._connection(write=True) as conn:
            old = self._existing_event(conn, "item_events", payload)
            if old is not None:
                return old
            if outcome != "SUCCESS":
                _text(reason, "reason")
            self._require_user(conn, user_id)
            item = conn.execute("SELECT * FROM items WHERE item_id=?", (item_id,)).fetchone()
            if item is None:
                raise UnknownReferenceError(f"unknown item: {item_id}")
            if item["owner_id"] != user_id:
                raise OwnershipError(f"item {item_id} does not belong to {user_id}")
            if item["updated_at"] != expected_updated_at:
                raise StaleStateError("item state changed since caller observation")
            timestamp = payload["occurred_at"]
            # FAILED_UNCHANGED deliberately leaves items untouched. Its newer
            # confirmation must still prevent an older result from rewriting state.
            latest = conn.execute(
                "SELECT occurred_at FROM item_events WHERE item_id=? ORDER BY occurred_at DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            if latest is not None and timestamp < latest["occurred_at"]:
                raise StaleStateError("result predates the latest item result")
            if timestamp < item["updated_at"] or (outcome != "FAILED_UNCHANGED" and
                                                  timestamp == item["updated_at"]):
                raise StaleStateError("result time must follow state update time")
            status, location = item["status"], item["location"]
            if outcome == "SUCCESS":
                # Actual per-item completion is supplied by the caller. Do not
                # invent a workflow state machine from the last known location.
                status = "STORED" if action == "STORE" else "ON_TRAY"
                location = target_location
            elif outcome == "UNKNOWN":
                status, location = "UNKNOWN", None
            event = dict(payload, previous_status=item["status"], resulting_status=status,
                         previous_location=item["location"], resulting_location=location)
            self._insert(conn, "item_events", event)
            if outcome == "SUCCESS":
                conn.execute("""UPDATE items SET status=?, location=?, updated_at=?,
                                last_confirmed_status=?, last_confirmed_location=?, last_confirmed_at=?
                                WHERE item_id=?""",
                             (status, location, timestamp, status, location, timestamp, item_id))
            elif outcome == "UNKNOWN":
                conn.execute("UPDATE items SET status='UNKNOWN', location=NULL, updated_at=? WHERE item_id=?",
                             (timestamp, item_id))
        return event

    def list_items(self, user_id, *, stored_only=False):
        """Known STORED only when filtered; UNKNOWN is never a confirmed stored item."""
        _text(user_id, "user_id")
        if type(stored_only) is not bool:
            raise ValueError("stored_only must be bool")
        query = "SELECT * FROM items WHERE owner_id=?"
        if stored_only:
            query += " AND status='STORED'"
        with self._connection() as conn:
            self._require_user(conn, user_id)
            return [dict(row) for row in conn.execute(query + " ORDER BY item_id", (user_id,))]

    def attendance_history(self, user_id):
        _text(user_id, "user_id")
        with self._connection() as conn:
            self._require_user(conn, user_id)
            return [dict(row) for row in conn.execute(
                "SELECT * FROM attendance_events WHERE user_id=? ORDER BY occurred_at,rowid", (user_id,))]

    def item_history(self, item_id):
        _text(item_id, "item_id")
        with self._connection() as conn:
            if conn.execute("SELECT 1 FROM items WHERE item_id=?", (item_id,)).fetchone() is None:
                raise UnknownReferenceError(f"unknown item: {item_id}")
            return [dict(row) for row in conn.execute(
                "SELECT * FROM item_events WHERE item_id=? ORDER BY occurred_at,rowid", (item_id,))]
