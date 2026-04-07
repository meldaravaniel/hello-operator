# Feature Backlog

Derived from `REVIEW.md`. Features are ordered by priority within each tier.

Decisions incorporated:
- **Playback model:** Pi sends commands to a Plex player running locally on the Pi (e.g., `plexmediaplayer`). The `PlexClient` must target that player by machine identifier.
- **Genre playback:** Kept; fixed by fetching all tracks under the genre and building a shuffle queue.
- **Audio threading:** Dedicated audio worker thread with a FIFO queue. `stop()` clears the queue and signals the active item to halt.
- **Secrets:** Loaded from environment variables at startup.

---

## P0 — Startup Blockers

These prevent the application from starting at all. Fix before anything else.

---

### F-01 · Fix constructor argument mismatches in `main.py`

**Background**
Three concrete classes are instantiated with wrong keyword argument names, causing `TypeError` immediately on `run()`.

**Changes required**

| Location | Wrong call | Correct call |
|---|---|---|
| `main.py:138` | `PiperTTS(model_path=PIPER_MODEL, ...)` | `PiperTTS(piper_model=PIPER_MODEL, ...)` |
| `main.py:146` | `PlexClient(base_url=PLEX_URL, ...)` | `PlexClient(url=PLEX_URL, ...)` |
| `main.py:119–123` | `GPIOHandler(hook_reader=..., pulse_reader=..., hook_debounce=..., pulse_debounce=...)` | `GPIOHandler(hook_pin_reader=..., pulse_pin_reader=...)` (debounce params do not exist on the class) |

**Acceptance criteria**
- `python main.py` reaches the `"hello-operator ready"` log line without raising `TypeError`.
- All existing unit tests continue to pass.

**Testable outcome**
- Input: call `run()` in an environment where GPIO/Plex/Piper are mocked or unavailable.
- Expected: no `TypeError` is raised during object construction.

---

### F-02 · Fix Piper TTS output format

**Background**
`_run_piper()` invokes Piper with `--output-raw`, which writes raw 16-bit LE PCM to stdout — no WAV header. These bytes are saved to `<name>.wav` and later opened with `wave.open()`, which requires a RIFF/WAV header and raises `wave.Error`.

**Changes required**
Replace the `--output-raw` flag with Piper's `--output_file <path>` option so Piper writes a proper WAV file directly. Adjust `_run_piper()` to accept an output path, write to that path, and return success/failure rather than raw bytes.

Alternatively, if stdout capture is required, construct a valid WAV header around the raw PCM before writing to disk. The `--output-raw` PCM format for the default Piper models is 16-bit signed LE, 22050 Hz, mono.

**Acceptance criteria**
- Pre-rendered script WAV files can be opened with `wave.open()` without error.
- `audio.play_file()` successfully plays a pre-rendered script.
- Live synthesis WAV files are also valid.

**Testable outcome**
- Input: call `tts.prerender({"test": "hello world"})` with a real Piper binary.
- Expected: `<cache_dir>/test.wav` is a valid WAV file (passes `wave.open()`, has nonzero frame count).

---

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

---

## P1 — Core Runtime Blockers

The system starts but critical runtime behaviour is broken or missing.

---

### F-04 · Audio worker thread with queued playback

**Background**
All audio methods (`play_tone`, `play_file`, `play_off_hook_tone`) block the calling thread. `PiperTTS.speak_and_play()` calls `audio.play_file()` synchronously, so every TTS utterance freezes the main event loop for the full audio duration. During this time `gpio.poll()` is never called, so `HANDSET_ON_CRADLE` events are lost. The spec requires: *"Hang-up stops all local audio immediately — even mid-TTS."*

**Design**
Introduce a dedicated audio worker thread inside `SounddeviceAudio`:

- An internal `queue.Queue` holds audio tasks. Each task is a callable (e.g., `lambda: sd.play(...); sd.wait()`).
- The worker thread loops: dequeue a task, execute it, repeat.
- `stop()` clears the queue, sets the existing `_stop_event`, and calls `sd.stop()` — this terminates both the currently-playing audio and any queued items.
- All public methods (`play_tone`, `play_file`, `play_dtmf`, `play_off_hook_tone`) become non-blocking: they enqueue a task and return immediately.
- `is_playing()` returns `True` if the worker is currently executing a task or the queue is non-empty.
- The worker thread is a daemon thread started in `__init__`.

The main event loop in `main.py` gains back full GPIO polling responsiveness. `speak_and_play` sequences (e.g., opener → greeting → hint) remain ordered because tasks are FIFO.

**Acceptance criteria**
- Calling `audio.stop()` while audio is playing terminates playback within one polling cycle (~5 ms).
- Multi-step TTS sequences play in the correct order.
- `is_playing()` returns `False` promptly after `stop()` or after the queue drains.
- All existing `MockAudio`-based unit tests continue to pass unchanged (the mock is unaffected).
- A new test demonstrates that `stop()` called during `play_tone` results in no further audio output.

**Testable outcome**
- Input: enqueue a 5-second tone, then call `stop()` after 100 ms.
- Expected: audio halts within ~5 ms of `stop()`; `is_playing()` returns `False`; no additional audio plays.

---

### F-05 · Plex local player targeting

**Background**
The playback methods (`play`, `pause`, `unpause`, `skip`, `stop`) use `/player/playback/...`, the Plex server's player-proxy API. This API requires the caller to identify which registered Plex player to target via `X-Plex-Target-Client-Identifier`. Without it, the server cannot route the command. The target is the Plex player running locally on the Pi.

**Changes required**

1. Add a new constant `PLEX_PLAYER_IDENTIFIER` to `constants.py` (with a TODO comment) representing the machine identifier of the local Plex player (found in the player's settings or via `/clients`).

2. Update `PlexClient.__init__` to accept `player_identifier: str` and store it.

3. Add `X-Plex-Target-Client-Identifier: <player_identifier>` to the headers sent with all playback commands. Also add an incrementing `commandID` parameter, as some Plex proxy implementations require it to order commands. Store a `_command_id` counter on the instance, incrementing with each playback call.

4. Update `main.py` to pass `PLEX_PLAYER_IDENTIFIER` when constructing `PlexClient`.

5. Remove the duplicate `X-Plex-Token` from the `params` dict in each playback method — it is already in `_headers`.

**Acceptance criteria**
- Calling `plex_client.play(plex_key)` with a valid key causes the local Plex player to begin playback.
- Calling `pause()`, `unpause()`, `skip()`, `stop()` produces the expected state change on the local player.
- `commandID` increments on each call.
- `X-Plex-Token` appears exactly once per request (in headers, not query params).

**Testable outcome (unit)**
- Input: construct `PlexClient` with a `player_identifier` of `"test-machine-123"` and call `pause()`.
- Expected: the outgoing request includes `X-Plex-Target-Client-Identifier: test-machine-123` in headers and `commandID=1` (or similar) in params; `X-Plex-Token` does not appear in params.

**Testable outcome (integration)**
- Input: call `plex_client.play(<valid_plex_key>)` against a real server with the Pi's player running.
- Expected: the local Plex player begins playing the specified item within ~2 seconds.

---

### F-06 · Genre playback via track queue

**Background**
The Plex genre browse API returns a path-style key (e.g., `/library/sections/1/genre/Jazz`) rather than a `ratingKey`. This path cannot be passed to `play()`. Genre playback requires fetching all tracks under the genre and starting a shuffled queue.

**Changes required**

1. Add `get_tracks_for_genre(section_id: str, genre_key: str) -> list` to `PlexClientInterface` and `PlexClient`. This method calls `/library/sections/{section_id}/all?genre={genre_key}` (or the equivalent Plex filter path) and returns a list of track `ratingKey` values.

2. Add `play_tracks(track_keys: list, shuffle: bool = True) -> None` to `PlexClientInterface` and `PlexClient`. This creates a Plex play queue from the provided keys and starts playback. (Plex API: `POST /playQueues` with `uri` and `shuffle=1`.)

3. Store the `section_id` in `MediaItem` for genre items — or encode it into `plex_key` in a parseable format (e.g., `"section:1/genre:Jazz"`). The `plex_key` field currently conflates the browse path with the playable key.

4. Update `PlexStore.get_genres()` and `PlexClient.get_genres()` to capture the `section_id` alongside each genre.

5. Update `menu._select_item()` to detect `media_type == "genre"` and call `plex_client.get_tracks_for_genre(...)` + `plex_client.play_tracks(...)` instead of the generic `plex_client.play()`.

6. Update `MockPlexClient` to add stub implementations of the two new methods.

**Acceptance criteria**
- Selecting a genre causes the local Plex player to begin playing tracks from that genre in shuffled order.
- If a genre has no tracks, `SCRIPT_NOT_IN_SERVICE` is spoken and the user is returned to the browse state.
- Existing playlist and artist playback is unaffected.

**Testable outcome (unit)**
- Input: mock `get_tracks_for_genre` returning `["key1", "key2"]`; select a genre item in the menu.
- Expected: `play_tracks(["key1", "key2"], shuffle=True)` is called; state transitions to `PLAYING_MENU`.

---

### F-07 · TTS temp file cleanup

**Background**
`PiperTTS._synthesize()` creates a file with `tempfile.mkstemp()` for live synthesis but never deletes it. Every dynamic string (media name, error message, phone number) that goes through live synthesis leaves a `.wav` file in the system temp directory permanently.

**Changes required**

Use a dedicated temp directory under `TTS_CACHE_DIR` (e.g., `<cache_dir>/live/`) for live synthesis files. At `__init__` time, clear this directory. After `audio.play_file(path)` completes (or after enqueueing, once the audio worker signals completion), delete the file.

If the worker-thread model from F-04 is in place, the cleanup callback can be registered as a follow-up task in the queue (a no-op audio task that deletes the file after the preceding play task drains).

Alternatively, if simplicity is preferred: wipe `<cache_dir>/live/` at startup and let files accumulate per session (bounded by session length).

**Acceptance criteria**
- After the application shuts down cleanly, no live-synthesis `.wav` files remain in the temp location.
- Pre-rendered cache files are not affected.

**Testable outcome**
- Input: call `tts.speak_and_play("some dynamic text")` for a string that is not pre-rendered.
- Expected: a temp `.wav` file is created; after playback completes, the file is removed.

---

## P2 — UX Gaps

The system starts and runs but user-facing behaviour is wrong or incomplete.

---

### F-08 · Shuffle confirmation announcement and state transition

**Background**
When the user selects the shuffle option in `_handle_idle_menu_digit`, `plex_client.shuffle_all()` is called but no TTS announcement is made and the state remains `IDLE_MENU`. The user gets silence. The system should announce the connection and transition to `PLAYING_MENU`.

**Changes required**

After `plex_client.shuffle_all()`:
1. Speak `SCRIPT_CONNECTING_TEMPLATE` with a placeholder name (e.g., `"the general exchange"`) and the digits spoken as the configured shuffle option digit.
2. Transition state to `PLAYING_MENU`.

Determine whether `SCRIPT_CONNECTING_TEMPLATE` fits the shuffle use case or if a dedicated shuffle confirmation script (`SCRIPT_SHUFFLE_CONNECTING`) is more appropriate. The script text should be added to `SCRIPTS.md` and pre-rendered.

**Acceptance criteria**
- After dialing the shuffle option, the user hears a connection announcement before music starts.
- State transitions to `PLAYING_MENU`.
- Hanging up after shuffle confirmation leaves music playing (existing hang-up behaviour).

**Testable outcome**
- Input: mock `plex_store` with artists present; call `on_digit(shuffle_digit)` in `IDLE_MENU` state.
- Expected: `mock_plex.shuffle_all` called; `mock_tts.speak_and_play` called with connecting text; `menu.state == MenuState.PLAYING_MENU`.

---

### F-09 · Browse and artist selection connecting announcement

**Background**
`_select_item()` for playlists, genres, and albums calls `plex_client.play()` and transitions to `PLAYING_MENU` without speaking `SCRIPT_CONNECTING_TEMPLATE`. Only the direct-dial path announces the connection. The spec describes the template for all final selections.

**Changes required**

In `_select_item()`, before calling `plex_client.play()` for non-artist items:
1. Assign or retrieve the phone number via `phone_book.assign_or_get(item.plex_key, item.media_type, item.name)`.
2. Build `digit_words_str` from the phone number digits using `_DIGIT_WORDS`.
3. Speak `SCRIPT_CONNECTING_TEMPLATE.format(digits=digit_words_str, name=item.name)`.
4. Then call `plex_client.play(item.plex_key)`.

Similarly, in `_handle_artist_submenu_digit` when digit `1` is pressed (shuffle artist):
1. Retrieve the phone number for the current artist.
2. Speak the connecting template.
3. Then call `plex_client.play(self._current_artist.plex_key)`.

**Acceptance criteria**
- Selecting any playlist, album, or genre speaks the connecting template before playback begins.
- Selecting artist shuffle (digit 1 in artist submenu) speaks the connecting template.
- The phone number spoken matches the entry in the phone book.
- State is `PLAYING_MENU` after the announcement.

**Testable outcome**
- Input: set up mock store with one playlist; navigate to `BROWSE_PLAYLISTS`; dial the listing digit.
- Expected: `mock_tts.speak_and_play` called with text matching `SCRIPT_CONNECTING_TEMPLATE`; `mock_plex.play` called with the playlist's plex_key; `menu.state == MenuState.PLAYING_MENU`.

---

### F-10 · Artist submenu re-delivery on back navigation

**Background**
`_re_deliver_current_state()` handles `IDLE_MENU`, `PLAYING_MENU`, and all `BROWSE_*` states but not `ARTIST_SUBMENU`. If the system ends up needing to re-deliver `ARTIST_SUBMENU` (e.g., after an invalid digit), the method silently does nothing, leaving the user in silence.

**Changes required**

Add an `ARTIST_SUBMENU` case to `_re_deliver_current_state()`:

```python
elif self._state == MenuState.ARTIST_SUBMENU:
    if self._current_artist:
        albums = self._plex_store.get_albums_for_artist(self._current_artist.plex_key)
        text = SCRIPT_ARTIST_SUBMENU_TEMPLATE.format(artist=self._current_artist.name)
        if albums:
            text += SCRIPT_ARTIST_SUBMENU_ALBUMS_SUFFIX
        self._tts.speak_and_play(text)
```

**Acceptance criteria**
- Dialing an invalid digit while in `ARTIST_SUBMENU` speaks `SCRIPT_NOT_IN_SERVICE` followed by a re-read of the artist submenu options.
- `_current_artist` is preserved through the re-delivery.

**Testable outcome**
- Input: navigate to `ARTIST_SUBMENU` for a mock artist with albums; dial digit `5` (invalid).
- Expected: `mock_tts.speak_and_play` called with `SCRIPT_NOT_IN_SERVICE`; then called again with text containing the artist name and album option.

---

### F-11 · Digit received before dial-tone menu is delivered

**Background**
If a digit is dialed during the `IDLE_DIAL_TONE` window (before the timeout fires the menu), disambiguation queues it. When the disambiguation timeout fires, `_dispatch_navigation_digit` is called while state is still `IDLE_DIAL_TONE`. The menu options check runs without having first delivered the menu prompt, and the dial tone may still be playing.

**Changes required**

In `_dispatch_navigation_digit`, add a guard at the top:

```python
if self._state == MenuState.IDLE_DIAL_TONE:
    # Deliver the appropriate menu first, then process the digit
    self._audio.stop()
    playback = self._plex_client.now_playing()
    if playback.item is not None:
        self._deliver_playing_menu(playback, now)
    else:
        self._deliver_idle_menu(now)
    # After menu delivery, process the digit against the new state
```

Because `_deliver_idle_menu` and `_deliver_playing_menu` are synchronous in the current architecture (they speak the menu), the digit would be processed after the full menu prompt. Consider whether the digit should be silently dropped in this case (user dialed before hearing options) or processed (user knew what they wanted). The safer default is to drop it and let the user dial again after hearing the menu.

**Acceptance criteria**
- A digit dialed during `IDLE_DIAL_TONE` does not cause an invalid state routing.
- The menu prompt is spoken before any navigation action is taken.
- The dial tone is stopped before the menu prompt begins.

**Testable outcome**
- Input: call `on_handset_lifted(now=0)`; call `on_digit(1, now=0.1)` (well within `DIAL_TONE_TIMEOUT_IDLE=5s`); advance `tick` to `now=1.7` (past disambiguation timeout).
- Expected: state is `IDLE_MENU` (menu was delivered); no `SCRIPT_NOT_IN_SERVICE` spoken; dial tone stopped.

---

## P3 — Correctness Improvements

Functionality works but with subtle incorrectness that will cause confusion in production.

---

### F-12 · Load secrets from environment variables

**Background**
`PLEX_URL`, `PLEX_TOKEN`, and `PLEX_PLAYER_IDENTIFIER` are currently hardcoded placeholders in `constants.py`. Storing secrets in committed source is a security risk.

**Changes required**

In `constants.py`, replace the hardcoded values with `os.environ` reads:

```python
import os
PLEX_URL = os.environ.get("PLEX_URL", "http://localhost:32400")
PLEX_TOKEN = os.environ["PLEX_TOKEN"]           # required; raise KeyError if absent
PLEX_PLAYER_IDENTIFIER = os.environ["PLEX_PLAYER_IDENTIFIER"]  # required
```

Required variables (`PLEX_TOKEN`, `PLEX_PLAYER_IDENTIFIER`) should raise `KeyError` (or a more descriptive `RuntimeError`) at import time if absent, not silently default to a broken value. Optional variables (`PLEX_URL`) may have a sensible default.

Add a `.env.example` file (not `.env`) to the repository root showing the required variable names with placeholder values.

**Acceptance criteria**
- Starting without `PLEX_TOKEN` set raises a clear error at startup, not a silent authentication failure later.
- Setting `PLEX_TOKEN=mytoken` in the environment is picked up correctly.
- `constants.py` contains no literal token strings.
- `.env.example` documents all required environment variables.

**Testable outcome**
- Input: import `src.constants` with `PLEX_TOKEN` unset in the environment.
- Expected: `RuntimeError` (or `KeyError`) raised with a message identifying the missing variable.

---

### F-13 · Idle menu retry fetches all categories, not just playlists

**Background**
In `_handle_idle_menu_digit` with `_failure_mode == "plex"`, the retry calls only `plex_store.get_playlists()`. If the original failure was fetching artists or genres, a successful playlist fetch clears `_failure_mode` and calls `_deliver_idle_menu()`, which may immediately fail again on artists or genres, re-entering the failure loop in a confusing way.

**Changes required**

Replace the single `get_playlists()` call in the retry path with a call to `plex_store.refresh()`, which re-fetches all categories and returns a summary dict. If all categories return `"error"`, keep `_failure_mode` set and re-speak the failure and retry prompts. If at least one category returns `"ok"`, clear `_failure_mode` and call `_deliver_idle_menu()`.

**Acceptance criteria**
- A retry attempt that succeeds for playlists but fails for artists proceeds to the menu showing only the successfully fetched categories.
- A retry attempt that fails for all categories re-speaks the failure prompt and retry option.
- A complete success clears failure mode and delivers the full menu.

**Testable outcome**
- Input: mock `plex_store.refresh()` to return `{'playlists': 'ok', 'artists': 'error', 'genres': 'error'}`; dial `1` in failure mode.
- Expected: `_failure_mode` is `None`; `_deliver_idle_menu` called; only playlists offered in menu.

---

### F-14 · Assistant pagination says "next" after the first page

**Background**
`_read_assistant_page()` always says *"I'll read you the first X"* regardless of which page is being read. On pages 2 and beyond this is incorrect.

**Changes required**

Track whether this is the first read of the current message list. One approach: check `self._assistant_page_offset == 0` before the read to determine which word to use.

```python
ordinal = "first" if self._assistant_page_offset == 0 else "next"
self._tts.speak_and_play(
    f"All right, here we go. I have {total} message{'s' if total != 1 else ''} for you. "
    f"I'll read you the {ordinal} {min(page_size, len(page))}."
)
```

**Acceptance criteria**
- First page of messages: announcement says "first X".
- Second and subsequent pages: announcement says "next X".

**Testable outcome**
- Input: set up 6 error messages (2 pages of 3); enter reading mode; read page 1; then dial `1` to continue.
- Expected: first `speak_and_play` call contains "first 3"; second contains "next 3".

---

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

---

### F-16 · `has_content` properties use existence check instead of full deserialize

**Background**
`PlexStore.playlists_has_content`, `artists_has_content`, and `genres_has_content` each read the full JSON blob from SQLite and deserialize it into a `List[MediaItem]` just to evaluate `bool(items)`. These are called multiple times per session start from `_deliver_idle_menu`. For large libraries this is wasteful.

**Changes required**

Replace the full read with a lightweight existence query:

```python
@property
def playlists_has_content(self) -> bool:
    with self._connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM plex_cache WHERE cache_key = ? AND data != '[]'",
            (_KEY_PLAYLISTS,)
        ).fetchone()
    return row is not None
```

Apply the same pattern to `artists_has_content` and `genres_has_content`.

**Acceptance criteria**
- Properties return `True` when the corresponding cache entry exists and is non-empty.
- Properties return `False` when the entry is absent or is `'[]'`.
- `MockPlexStore` `has_content` properties continue to work as before (they are already in-memory booleans and need no change).

**Testable outcome**
- Input: write `'[]'` to `plex_cache` for `"playlists"`; call `playlists_has_content`.
- Expected: returns `False`.
- Input: write `'[{"plex_key": "1", "name": "A", "media_type": "playlist"}]'`; call `playlists_has_content`.
- Expected: returns `True`.

---

## P4 — Code Quality

Minor issues that don't affect user-visible behaviour but improve maintainability.

---

### F-17 · Deduplicate `_DIGIT_WORDS`

**Background**
An identical `_DIGIT_WORDS = {'0': 'zero', '1': 'one', ...}` dict is defined in both `src/tts.py` and `src/menu.py`. If the mapping ever changes, both must be updated in sync.

**Changes required**

Move `_DIGIT_WORDS` to `src/constants.py` (public name: `DIGIT_WORDS`) and import it in both `tts.py` and `menu.py`. No behaviour changes.

**Acceptance criteria**
- `_DIGIT_WORDS` / `DIGIT_WORDS` appears in exactly one source file.
- All tests that exercise digit-word output continue to pass.

---

### F-18 · GPIO cleanup on exit

**Background**
`build_gpio_handler()` calls `GPIO.setmode()` and `GPIO.setup()` but the `finally` block in `run()` never calls `GPIO.cleanup()`. This leaves pull-up resistors active and triggers `RuntimeWarning: No channels have been set up yet` on the next startup.

**Changes required**

Add `GPIO.cleanup()` to the `finally` block in `run()`, after `audio.stop()`. Guard it so it only runs if the GPIO module was successfully imported (i.e., if `build_gpio_handler()` did not raise).

**Acceptance criteria**
- Clean shutdown (`KeyboardInterrupt`) calls `GPIO.cleanup()`.
- Subsequent startup does not emit GPIO RuntimeWarnings.

---

### F-19 · Remove duplicate auth token from Plex playback request params

**Background**
The `_headers` dict in `PlexClient` already contains `"X-Plex-Token": token`. Each playback method (`play`, `shuffle_all`, `pause`, `unpause`, `skip`, `stop`) also adds `"X-Plex-Token": self._token` to the `params` dict, sending the token twice per request.

**Changes required**

Remove `"X-Plex-Token": self._token` from the `params` dict in each of the six playback methods. The token in `_headers` is sufficient.

**Acceptance criteria**
- Outgoing playback requests contain `X-Plex-Token` exactly once (in the `Authorization` header, not in query params).
- All existing unit tests pass.

---

### F-20 · Bound the phone number generation retry loop

**Background**
`PhoneBook._generate_unique_number()` retries indefinitely until a unique number is found. While the number space (9 million entries) makes exhaustion implausible, an unbounded loop is fragile.

**Changes required**

Add a maximum iteration count (e.g., 1000). If exceeded, raise `RuntimeError("Phone book number space exhausted")`. This is a hard-fail condition that should never occur in practice but provides a safe termination instead of an infinite loop.

**Acceptance criteria**
- Normal assignment succeeds within a small number of iterations.
- Forcing all numbers to be "taken" (via a mock) causes `RuntimeError` after the iteration limit, not an infinite loop.
