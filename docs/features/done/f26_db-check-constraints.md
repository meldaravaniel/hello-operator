### F-26 · CHECK constraints on enum-like database columns

**Background**
The `phone_book` and `error_queue` tables have columns that act as enums (`media_type` and `severity`) but are declared as plain `TEXT NOT NULL`. Invalid values can be written without any database-level complaint. Adding `CHECK` constraints enforces valid values at the SQLite layer, catching bugs that bypass Python-level validation.

**Changes required**

#### 1. `src/phone_book.py` — add CHECK to `media_type`

```sql
CREATE TABLE IF NOT EXISTS phone_book (
    plex_key     TEXT PRIMARY KEY,
    media_type   TEXT NOT NULL CHECK(media_type IN ('playlist','artist','album','genre','radio')),
    name         TEXT NOT NULL,
    phone_number TEXT NOT NULL UNIQUE
)
```

#### 2. `src/error_queue.py` — add CHECK to `severity`

```sql
CREATE TABLE IF NOT EXISTS error_queue (
    source        TEXT NOT NULL,
    message       TEXT NOT NULL,
    severity      TEXT NOT NULL CHECK(severity IN ('warning','error')),
    count         INTEGER NOT NULL DEFAULT 1,
    last_happened TEXT NOT NULL,
    PRIMARY KEY (source, message)
)
```

#### 3. `docs/IMPL.md` — update both schema blocks to match.

#### 4. Existing databases

`CREATE TABLE IF NOT EXISTS` silently skips recreation when the table already exists, so existing database files will not gain the new constraints. Since the project has not been deployed, simply delete the local `.db` files and let the application recreate them on next startup. No migration script is needed at this stage.

**Acceptance criteria**
- On a fresh database, inserting a row with an invalid `media_type` (e.g. `"track"`) into `phone_book` raises `sqlite3.IntegrityError`.
- On a fresh database, inserting a row with an invalid `severity` (e.g. `"critical"`) into `error_queue` raises `sqlite3.IntegrityError`.
- All valid values (`'playlist'`, `'artist'`, `'album'`, `'genre'`, `'radio'` for `media_type`; `'warning'`, `'error'` for `severity`) insert without error.
- All existing tests in `test_phone_book.py` and `test_error_queue.py` pass unchanged (they only write valid values).

**Testable outcome**
New tests in `test_phone_book.py`:
- `test_invalid_media_type_rejected` — attempt `conn.execute("INSERT INTO phone_book VALUES (?, ?, ?, ?)", ("/k/1", "track", "Name", "5551234"))`; assert `sqlite3.IntegrityError` is raised.
- `test_valid_media_types_accepted` — insert one row for each of `'playlist'`, `'artist'`, `'album'`, `'genre'`, `'radio'`; assert no exception.

New tests in `test_error_queue.py`:
- `test_invalid_severity_rejected` — attempt to insert a row with `severity = "critical"` directly via the connection; assert `sqlite3.IntegrityError` is raised.
- `test_valid_severities_accepted` — call `log()` with `severity="warning"` and `severity="error"`; assert no exception.
