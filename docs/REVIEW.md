# Code Review: Findings and Recommendations

Analysis of the first-pass implementation against the specs in `DESIGN.md`, `IMPL.md`, and `SCRIPTS.md`.

Issues are grouped by severity. **Critical** items will cause immediate failure at runtime. **High** items are significant bugs or architectural gaps. **Medium** items are correctness concerns or meaningful inefficiencies. **Low** items are minor quality issues.

---

## Critical

### 1. `main.py` — Constructor argument mismatches

Three concrete implementations are instantiated with wrong keyword argument names, causing immediate `TypeError` on startup.

| Call site | Passed kwarg | Actual param |
|---|---|---|
| `PiperTTS(...)` | `model_path=PIPER_MODEL` | `piper_model` |
| `PlexClient(...)` | `base_url=PLEX_URL` | `url` |
| `GPIOHandler(...)` | `hook_reader=...`, `pulse_reader=...`, `hook_debounce=...`, `pulse_debounce=...` | `hook_pin_reader`, `pulse_pin_reader` (no debounce params) |

Fix: align kwarg names in `main.py` with the concrete class signatures, or add the debounce parameters to `GPIOHandler.__init__` if they belong there.

---

### 2. `tts.py` — Raw PCM bytes written as `.wav`, then read as WAV

`_run_piper()` calls Piper with `--output-raw`, which writes raw 16-bit LE PCM to stdout — no WAV header. The bytes are then saved to `<script_name>.wav`. Later, `audio.play_file()` opens the file with `wave.open()`, which expects a RIFF/WAV header and will raise `wave.Error`.

Fix: either (a) drop `--output-raw` and use `--output_file <path>` so Piper writes a valid WAV, or (b) prepend a correct WAV header to the raw bytes before writing. Option (a) is simpler.

---

### 3. `main.py` — Database directory not created

The DB paths are under `/var/lib/hello-operator/`, but nothing creates that directory. If it doesn't exist, all three `sqlite3.connect()` calls fail with `OperationalError`. 

Fix: add `os.makedirs(_DB_DIR, exist_ok=True)` before instantiating any `Sqlite*` class.

---

## High

### 4. Blocking audio architecture prevents mid-speech hang-up

`SounddeviceAudio.play_tone()`, `play_file()`, and `play_off_hook_tone()` all block the calling thread using a `while elapsed < total` polling loop. `PiperTTS.speak_and_play()` calls `audio.play_file()` synchronously, so every TTS utterance blocks the main event loop for the full duration of the audio.

The spec explicitly requires: *"Hang-up (HANDSET_ON_CRADLE) stops all local audio immediately — even mid-TTS."*

This is impossible with the current single-threaded blocking model. While audio is playing, `gpio.poll()` is never called, so `HANDSET_ON_CRADLE` events are lost until the audio finishes.

Fix: run audio playback in a background thread (or use `sounddevice`'s non-blocking `sd.play()` / `sd.wait()` in a thread). The main event loop should remain free to call `gpio.poll()` at all times. `stop()` sets the existing `_stop_event`, so the thread architecture is already partially designed for this.

---

### 5. Plex playback API requires additional parameters

The playback methods (`play`, `pause`, `unpause`, `skip`, `stop`) target `/player/playback/...`, which is the Plex server's player-proxy API. This API requires at minimum:
- `X-Plex-Target-Client-Identifier` or equivalent to specify which player to control
- Incrementing `commandID` values for ordering

Without these, the server returns a 400 or silently ignores the command. The Pi itself must be registered as a Plex player or a remote player must be specified.

This needs real-hardware validation but should be designed for from the start. Recommend testing against a real server and reviewing the Plex API docs for the player proxy endpoint requirements.

---

### 6. `menu.py` — `shuffle_all` gives no user feedback and no state transition

In `_handle_idle_menu_digit`, when the shuffle option is selected:

```python
if name == 'shuffle':
    self._plex_client.shuffle_all()
```

There is no TTS announcement (no connecting template, no confirmation), and the state remains `IDLE_MENU`. The user gets silence after dialing. The spec implies a connecting-style announcement and transition to `PLAYING_MENU`.

---

### 7. `menu.py` — Browse selection doesn't speak connecting template

`_select_item()` for non-artist items (playlist, genre, album) calls `plex_client.play()` and immediately sets state to `PLAYING_MENU` with no announcement. The `SCRIPT_CONNECTING_TEMPLATE` is only used in the direct-dial path. The spec describes this template for final selections: *"Thank you for your patience. I'm connecting your call to..."*

---

### 8. `tts.py` — Temp files accumulate and are never cleaned up

`_synthesize()` creates a file with `tempfile.mkstemp()` for live synthesis but never deletes it. On a system that processes many dynamic strings over time (media names, error messages), this will accumulate `.wav` files in the system temp directory indefinitely.

Fix: track the path and delete after playback, or use a dedicated temp directory that gets cleared at startup.

---

### 9. `plex_client.py` — Genre `plex_key` is a URL path, not a playable key

`get_genres()` builds `MediaItem` with:
```python
plex_key=item.get("key", item.get("title", ""))
```

The Plex genre API returns `"key"` as a path like `/library/sections/1/genre/Jazz`. This path cannot be passed directly to `play()` which expects a `ratingKey`-style integer string. Genre playback via the Plex API requires a different approach (querying all tracks in that genre and building a queue).

---

## Medium

### 10. `menu.py` — `_re_deliver_current_state` missing `ARTIST_SUBMENU` case

`_re_deliver_current_state()` handles all `BROWSE_*` states and `IDLE_MENU`/`PLAYING_MENU`, but not `ARTIST_SUBMENU`. If the user presses `9` while in `ARTIST_SUBMENU`, the state is popped from the nav stack and `_re_deliver_current_state` is called for the parent state (correct), but if `_re_deliver_current_state` is called while *in* `ARTIST_SUBMENU` for any reason it silently does nothing.

---

### 11. `menu.py` — Digit received during `IDLE_DIAL_TONE` before menu is delivered

If a digit arrives while state is `IDLE_DIAL_TONE` (before the dial-tone timeout fires the menu), the disambiguation logic queues it. When it resolves, `_dispatch_navigation_digit` is called which routes to `_handle_idle_menu_digit`. At that point the state is still `IDLE_DIAL_TONE` and the dial tone may still be playing. The options check (`playlists_has_content`, etc.) runs against an unmigrated state.

`_handle_idle_menu_digit` should either guard against this or the transition to `IDLE_MENU` should happen before digit routing.

---

### 12. `menu.py` — `_read_assistant_page` always says "first X" on every page

```python
f"I'll read you the first {min(page_size, total)}."
```

On pages 2, 3, etc. this still says "first". It should say "next" for pages beyond the first.

---

### 13. `menu.py` — Idle menu retry only calls `get_playlists()`

In `_handle_idle_menu_digit` with `failure_mode == "plex"`, retrying calls only `get_playlists()`. If the original failure was fetching artists or genres, a successful playlist fetch clears `_failure_mode` and proceeds to `_deliver_idle_menu()`, which may immediately fail again on artists/genres.

---

### 14. `plex_store.py` — `has_content` properties deserialize full data just to check length

Each call to `playlists_has_content`, `artists_has_content`, or `genres_has_content` does:
1. Open a new DB connection
2. Read the full JSON blob from SQLite
3. Deserialize it into a `List[MediaItem]`
4. Return `bool(items)`

These properties are called multiple times per session start from `_deliver_idle_menu`. A simple `SELECT 1 FROM plex_cache WHERE cache_key = ? AND data != '[]'` or storing the count as a separate column would be far cheaper.

---

### 15. `error_queue.py` — `log()` uses SELECT + conditional INSERT/UPDATE instead of UPSERT

The current two-step approach (SELECT to check existence, then UPDATE or INSERT) is a TOCTOU pattern. SQLite supports `INSERT INTO ... ON CONFLICT DO UPDATE` (UPSERT) natively, which is both simpler and atomic:

```sql
INSERT INTO error_queue (source, message, severity, count, last_happened)
VALUES (?, ?, ?, 1, ?)
ON CONFLICT(source, message) DO UPDATE SET
    count = count + 1,
    last_happened = excluded.last_happened
```

The current approach also doesn't update `severity` on repeat occurrences; if the same `(source, message)` pair is re-logged with a different severity, the original severity is kept.

---

### 16. `plex_client.py` — Auth token duplicated in both headers and query params

The `_headers` dict already includes `"X-Plex-Token": token`. The playback methods (`play`, `shuffle_all`, `pause`, etc.) additionally add `"X-Plex-Token": self._token` to the `params` dict. This is redundant.

---

### 17. `main.py` — No `GPIO.cleanup()` on exit

`build_gpio_handler()` calls `GPIO.setmode()` and `GPIO.setup()` but the `finally` block in `run()` only calls `audio.stop()`. On exit, GPIO pins are left configured, which can trigger `RuntimeWarning` on next startup and may leave pull-up resistors active.

Fix: call `GPIO.cleanup()` in the `finally` block.

---

### 18. `_DIGIT_WORDS` defined in both `tts.py` and `menu.py`

Two identical `_DIGIT_WORDS` dicts exist, one in each file. If the mapping ever changes, both must be updated. Move to `constants.py` and import from there.

---

## Low

### 19. `audio.py` — Polling loop reinvents `sd.wait()`

The `while elapsed < total` pattern in `play_tone()` and `play_file()` manually tracks elapsed time in 10ms steps to simulate blocking. `sounddevice` provides `sd.wait()` which blocks until playback completes and integrates cleanly with `sd.stop()`. (Note: fixing the blocking architecture per issue #4 supersedes this — but if blocking playback is kept, `sd.wait()` in a thread is cleaner than the polling loop.)

---

### 20. `phone_book.py` — `_generate_unique_number` could stall on a full table

The number generation loop retries indefinitely. In the extremely unlikely case the phone book is near its 9-million-entry capacity, this could spin for a long time. A hard iteration limit with a raised exception would be safer than an infinite loop.

---

### 21. Config — Secrets in source file

`PLEX_TOKEN = "YOUR_PLEX_TOKEN"` and `PLEX_URL` are in `constants.py`. For deployment, these should come from environment variables or a local config file excluded from version control. The current approach requires editing a committed file to deploy, which risks accidentally committing a real token.

---

### 22. `session.py` — Passes `plex_store` and `phone_book` without type annotation

The `Session.__init__` signature uses untyped `plex_store` and `phone_book` parameters (typed as plain comments). Since `PlexStore` and `PhoneBook` are concrete classes with no shared ABC, this is somewhat unavoidable, but a `Protocol` or informal ABC would make the contract explicit.

---

## Summary Table

| # | Module | Severity | Issue |
|---|---|---|---|
| 1 | `main.py` | Critical | Constructor kwarg mismatches (PiperTTS, PlexClient, GPIOHandler) |
| 2 | `tts.py` | Critical | Raw PCM written as `.wav`, incompatible with `wave.open()` |
| 3 | `main.py` | Critical | DB directory not created before opening connections |
| 4 | `audio.py` / `tts.py` | High | Blocking playback prevents mid-speech hang-up |
| 5 | `plex_client.py` | High | Player API requires machine identifier + commandID |
| 6 | `menu.py` | High | `shuffle_all` has no feedback and no state transition |
| 7 | `menu.py` | High | Browse selection skips connecting template |
| 8 | `tts.py` | High | Temp WAV files never deleted |
| 9 | `plex_client.py` | High | Genre `plex_key` is a path, not a playable key |
| 10 | `menu.py` | Medium | `_re_deliver_current_state` missing `ARTIST_SUBMENU` |
| 11 | `menu.py` | Medium | Digit during `IDLE_DIAL_TONE` before state transition |
| 12 | `menu.py` | Medium | Pagination always says "first X" messages |
| 13 | `menu.py` | Medium | Retry only fetches playlists, may re-fail on artists/genres |
| 14 | `plex_store.py` | Medium | `has_content` deserializes full list to check bool |
| 15 | `error_queue.py` | Medium | SELECT + UPDATE/INSERT should be a single UPSERT |
| 16 | `plex_client.py` | Medium | Token in both headers and query params |
| 17 | `main.py` | Medium | No `GPIO.cleanup()` on exit |
| 18 | `tts.py` / `menu.py` | Low | `_DIGIT_WORDS` duplicated |
| 19 | `audio.py` | Low | Manual polling loop reinvents `sd.wait()` |
| 20 | `phone_book.py` | Low | Infinite retry loop in `_generate_unique_number` |
| 21 | `constants.py` | Low | Auth token in committed source file |
| 22 | `session.py` | Low | `plex_store` and `phone_book` untyped |
