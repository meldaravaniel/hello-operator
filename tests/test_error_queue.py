"""Tests for SqliteErrorQueue — persistent error log."""

import pytest
from src.error_queue import SqliteErrorQueue


def test_log_new_entry(tmp_error_queue):
    q = SqliteErrorQueue(tmp_error_queue)
    q.log("tts", "warning", "cache miss")
    entries = q.get_all()
    assert len(entries) == 1
    e = entries[0]
    assert e.source == "tts"
    assert e.severity == "warning"
    assert e.message == "cache miss"
    assert e.count == 1
    assert e.last_happened  # non-empty ISO8601 string


def test_log_deduplicates_by_source_and_message(tmp_error_queue):
    q = SqliteErrorQueue(tmp_error_queue)
    q.log("tts", "warning", "cache miss")
    q.log("tts", "warning", "cache miss")
    entries = q.get_all()
    assert len(entries) == 1
    assert entries[0].count == 2


def test_log_different_source_creates_new_entry(tmp_error_queue):
    q = SqliteErrorQueue(tmp_error_queue)
    q.log("tts", "warning", "cache miss")
    q.log("plex_store", "warning", "cache miss")
    entries = q.get_all()
    assert len(entries) == 2


def test_get_all_returns_all_entries(tmp_error_queue):
    q = SqliteErrorQueue(tmp_error_queue)
    q.log("tts", "warning", "msg1")
    q.log("plex_store", "error", "msg2")
    q.log("audio", "warning", "msg3")
    entries = q.get_all()
    assert len(entries) == 3


def test_get_all_returns_newest_first(tmp_error_queue):
    import time
    q = SqliteErrorQueue(tmp_error_queue)
    q.log("tts", "warning", "first")
    time.sleep(0.01)
    q.log("plex_store", "error", "second")
    entries = q.get_all()
    assert entries[0].message == "second"
    assert entries[1].message == "first"


def test_get_by_severity_filters_correctly(tmp_error_queue):
    q = SqliteErrorQueue(tmp_error_queue)
    q.log("tts", "warning", "warn1")
    q.log("plex_store", "error", "err1")
    q.log("audio", "warning", "warn2")
    warnings = q.get_by_severity("warning")
    errors = q.get_by_severity("error")
    assert len(warnings) == 2
    assert len(errors) == 1
    assert all(e.severity == "warning" for e in warnings)
    assert all(e.severity == "error" for e in errors)


def test_persistence_across_instantiation(tmp_error_queue):
    q1 = SqliteErrorQueue(tmp_error_queue)
    q1.log("tts", "error", "persistent error")
    del q1
    q2 = SqliteErrorQueue(tmp_error_queue)
    entries = q2.get_all()
    assert len(entries) == 1
    assert entries[0].message == "persistent error"


def test_severity_values_enforced(tmp_error_queue):
    q = SqliteErrorQueue(tmp_error_queue)
    with pytest.raises((ValueError, Exception)):
        q.log("tts", "critical", "bad severity")


def test_dedup_updates_last_happened(tmp_error_queue):
    import time
    q = SqliteErrorQueue(tmp_error_queue)
    q.log("tts", "warning", "msg")
    first_time = q.get_all()[0].last_happened
    time.sleep(0.01)
    q.log("tts", "warning", "msg")
    second_time = q.get_all()[0].last_happened
    assert second_time >= first_time


def test_log_uses_single_sql_statement(tmp_error_queue, monkeypatch):
    """log() must use a single UPSERT statement (INSERT ... ON CONFLICT), never a SELECT."""
    import sqlite3
    import inspect

    q = SqliteErrorQueue(tmp_error_queue)

    # Inspect the source of log() — it must contain ON CONFLICT and must not SELECT
    source = inspect.getsource(q.log)
    source_upper = source.upper()
    assert "ON CONFLICT" in source_upper, "log() must use INSERT ... ON CONFLICT (UPSERT)"
    assert "SELECT" not in source_upper, "log() must not use a SELECT statement"


def test_dedup_does_not_change_severity(tmp_error_queue):
    """Re-logging the same (source, message) with a different severity does not change severity."""
    q = SqliteErrorQueue(tmp_error_queue)
    q.log("tts", "warning", "msg")
    q.log("tts", "error", "msg")
    entries = q.get_all()
    assert len(entries) == 1
    assert entries[0].severity == "warning"  # severity set on first insert, never updated
