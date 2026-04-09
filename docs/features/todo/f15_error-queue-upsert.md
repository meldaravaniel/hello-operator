### F-15 · Error queue uses atomic UPSERT

**Background**
`SqliteErrorQueue.log()` performs a `SELECT` followed by either `UPDATE` or `INSERT`. This is not atomic. While the system is single-threaded and race conditions are unlikely, the pattern is fragile and verbose. SQLite natively supports `INSERT ... ON CONFLICT DO UPDATE` (UPSERT).

**Changes required**

Replace the SELECT + conditional UPDATE/INSERT in `log()` with:

```sql
INSERT INTO error_queue (source, message, severity, count, last_happened)
VALUES (?, ?, ?, 1, ?)
ON CONFLICT(source, message) DO UPDATE SET
    count        = count + 1,
    last_happened = excluded.last_happened
```

Note: this also means `severity` is set on first insert and never updated thereafter (same as current behaviour). If re-logging the same `(source, message)` with an escalated severity (warning → error) should be reflected, add `severity = excluded.severity` to the `DO UPDATE` clause. Choose the desired behaviour and document it in the method's docstring.

**Acceptance criteria**
- `log()` produces the same external behaviour as before (deduplication, count increment, timestamp update).
- The implementation uses a single SQL statement with no intermediate `SELECT`.
- All existing `test_error_queue.py` tests pass.