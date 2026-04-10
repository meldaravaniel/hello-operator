"""Persistent error log implementation using SQLite."""

import sqlite3
from datetime import datetime, timezone
from typing import List

from src.interfaces import ErrorEntry, ErrorQueueInterface

VALID_SEVERITIES = {"warning", "error"}


class SqliteErrorQueue(ErrorQueueInterface):
    """Persists error entries to a SQLite database."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS error_queue (
                    source        TEXT NOT NULL,
                    message       TEXT NOT NULL,
                    severity      TEXT NOT NULL CHECK(severity IN ('warning','error')),
                    count         INTEGER NOT NULL DEFAULT 1,
                    last_happened TEXT NOT NULL,
                    PRIMARY KEY (source, message)
                )
            """)

    def log(self, source: str, severity: str, message: str) -> None:
        """Persist an error entry, deduplicating by (source, message).

        If an entry with the same (source, message) already exists, its count is
        incremented and last_happened is updated. The severity is set on first
        insert and never updated on subsequent calls — re-logging the same message
        with an escalated severity does not change the stored severity.

        Uses a single atomic INSERT ... ON CONFLICT DO UPDATE (UPSERT) statement
        with no intermediate read query.
        """
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity: {severity!r}. Must be one of {VALID_SEVERITIES}")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO error_queue (source, message, severity, count, last_happened)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(source, message) DO UPDATE SET
                    count         = count + 1,
                    last_happened = excluded.last_happened
                """,
                (source, message, severity, now)
            )

    def get_all(self) -> List[ErrorEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, severity, message, count, last_happened FROM error_queue ORDER BY last_happened DESC"
            ).fetchall()
        return [ErrorEntry(
            source=r["source"],
            severity=r["severity"],
            message=r["message"],
            count=r["count"],
            last_happened=r["last_happened"]
        ) for r in rows]

    def get_by_severity(self, severity: str) -> List[ErrorEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, severity, message, count, last_happened FROM error_queue WHERE severity = ? ORDER BY last_happened DESC",
                (severity,)
            ).fetchall()
        return [ErrorEntry(
            source=r["source"],
            severity=r["severity"],
            message=r["message"],
            count=r["count"],
            last_happened=r["last_happened"]
        ) for r in rows]


class MockErrorQueue(ErrorQueueInterface):
    """In-memory mock for unit tests. Records all calls."""

    def __init__(self):
        self.logged_calls: list = []
        self.entries: List[ErrorEntry] = []  # public for test inspection

    def log(self, source: str, severity: str, message: str) -> None:
        self.logged_calls.append((source, severity, message))
        # Dedup by (source, message)
        for e in self.entries:
            if e.source == source and e.message == message:
                e.count += 1
                e.last_happened = datetime.now(timezone.utc).isoformat()
                return
        self.entries.append(ErrorEntry(
            source=source,
            severity=severity,
            message=message,
            count=1,
            last_happened=datetime.now(timezone.utc).isoformat()
        ))

    def get_all(self) -> List[ErrorEntry]:
        return list(reversed(self.entries))

    def get_by_severity(self, severity: str) -> List[ErrorEntry]:
        return [e for e in reversed(self.entries) if e.severity == severity]
