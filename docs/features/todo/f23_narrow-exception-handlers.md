### F-23 · Narrow broad `except Exception` handlers

**Background**
Three handlers in `src/menu.py` and one in `src/tts.py` use bare `except Exception:`, which catches `MemoryError`, `RecursionError`, and other conditions that indicate bugs rather than expected runtime failures. Masking these makes debugging significantly harder.

| Location | Context |
|---|---|
| `menu.py` line 407 | Plex store browse call fails → enters failure mode |
| `menu.py` line 753 | Phone book lookup by number → treated as not found |
| `menu.py` line 971 | `plex_store.refresh()` in assistant → speaks failure script |
| `tts.py` line 169 | `_run_piper()` subprocess call fails → returns `False` |

**Changes required**

Replace each `except Exception:` with the specific exception types that the called code can actually raise:

- `menu.py` line 407 — `plex_store.get_*()` methods can raise `sqlite3.Error` (DB failure) or `Exception` from network errors. Use `except (sqlite3.Error, OSError):` or consult the `plex_store` interface for its documented exceptions.
- `menu.py` line 753 — `phone_book.lookup_by_phone_number()` wraps SQLite. Use `except sqlite3.Error:`.
- `menu.py` line 971 — `plex_store.refresh()` wraps SQLite + HTTP. Use `except (sqlite3.Error, OSError):`.
- `tts.py` line 169 — `subprocess.Popen` / `communicate()` raises `OSError` (binary not found, I/O error). Use `except OSError:`.

Import `sqlite3` at the top of `menu.py` if not already present.

**Acceptance criteria**
- No `except Exception:` remains in `menu.py` or `tts.py`.
- Each handler catches only the specific exceptions the called code can raise.
- All existing tests pass.
- A test that forces each handler to trigger (by injecting a mock that raises the specific exception) verifies that the correct recovery path runs.
