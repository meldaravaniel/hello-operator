### F-24 · Log phone book lookup failures to the error queue

**Background**
When `phone_book.lookup_by_phone_number()` raises an exception during direct-dial resolution (`menu.py` line 751–754), the error is silently swallowed and the user hears "not in service". Unlike Plex store and TTS errors — which both log to `ErrorQueueInterface` — phone book failures produce no diagnostic entry, so the operator assistant never surfaces them.

```python
# menu.py lines 751-754
try:
    entry = self._phone_book.lookup_by_phone_number(number)
except Exception:
    entry = None  # ← no error queue entry
```

**Changes required**

Catch the specific exception (see F-23) and log it to the error queue before treating `entry` as `None`:

```python
except sqlite3.Error as e:
    self._error_queue.log("menu", "error", f"Phone book lookup failed: {e}")
    entry = None
```

The `Menu` constructor already accepts `ErrorQueueInterface`; no signature changes needed.

**Acceptance criteria**
- When `phone_book.lookup_by_phone_number()` raises, an error entry is created via `error_queue.log("menu", "error", ...)`.
- The user still hears `SCRIPT_NOT_IN_SERVICE` and state transitions to `IDLE_MENU`.
- A new test verifies the error queue receives the entry when the phone book raises.
- All existing tests pass.
