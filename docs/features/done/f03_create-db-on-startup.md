### F-03 · Create database directory on startup

**Background**
All three SQLite database paths are under `/var/lib/hello-operator/`. If that directory does not exist, `sqlite3.connect()` raises `OperationalError` before any application logic runs. Nothing in `run()` creates the directory first.

**Changes required**
Add `os.makedirs(_DB_DIR, exist_ok=True)` in `main.py` before instantiating `SqliteErrorQueue`, `PhoneBook`, or `PlexStore`. The TTS cache directory is already created by `PiperTTS.__init__`; apply the same pattern here.

**Acceptance criteria**
- On a fresh system where `/var/lib/hello-operator/` does not exist, `run()` creates the directory and all three DB files without error.
- If the directory already exists, `exist_ok=True` suppresses the error and startup proceeds normally.

**Testable outcome**
- Input: run `python main.py` on a system with `/var/lib/hello-operator/` absent.
- Expected: directory is created; no `OperationalError` is raised during startup.