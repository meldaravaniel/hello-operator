# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Hello Operator** is a vintage rotary phone wired to a Raspberry Pi 4 that acts as a hands-on interface for a Plex media server. Picking up the handset triggers an interactive voice menu styled as a telephone operator experience. The rotary dial inputs digits for T9-style browsing and direct-dial access to media.

## Commands

```bash
# Run all unit tests
python -m pytest

# Run a single test
python -m pytest tests/test_menu.py::test_idle_menu_announces_options

# Run integration tests (requires live Plex server)
python -m pytest -m integration

# Run all tests except integration
python -m pytest -m "not integration"

# Run the application
python main.py
```

## Project Structure

```
src/
  interfaces.py       # All ABCs, MediaItem, PlaybackState, ErrorEntry
  error_queue.py      # SqliteErrorQueue
  phone_book.py       # PhoneBook
  gpio_handler.py     # GPIOHandler
  audio.py            # SounddeviceAudio
  tts.py              # PiperTTS
  plex_client.py      # PlexClient
  plex_store.py       # PlexStore
  menu.py             # Menu state machine
  session.py          # Session lifecycle
  constants.py        # All configuration constants
  main.py             # Wires everything together

tests/
  conftest.py         # Shared pytest fixtures (all mocks)
  test_error_queue.py
  test_phone_book.py
  test_gpio_handler.py
  test_audio.py
  test_tts.py
  test_plex_client.py
  test_plex_store.py
  test_menu.py
  test_session.py
```

## Conventions

- All constants live in constants.py; no magic numbers elsewhere
- All TBD constants are defined with a placeholder value and a TODO comment
- Mocks are defined in tests/conftest.py as pytest fixtures
- Integration tests are marked with @pytest.mark.integration

## Architecture

All hardware-dependent and external-service modules sit behind Python ABCs. **No module above the interface layer imports a concrete dependency directly.** This is the central design rule — it enables mock injection without patching and full testability without hardware.

```
main.py
  └── session         (lifecycle: GPIO events → menu state machine)
        ├── gpio_handler  (decodes raw GPIO pulses into HANDSET_LIFTED / HANDSET_ON_CRADLE / DIGIT_DIALED)
        └── menu          (state machine; uses only interfaces, never concrete impls)
              ├── plex_store      (local SQLite cache; menu never calls plex_client directly for browse data)
              │     └── plex_client  (PlexClientInterface — HTTP calls to Plex)
              ├── phone_book      (SQLite: auto-assigns 7-digit numbers to plex_keys)
              ├── AudioInterface  (SounddeviceAudio / MockAudio)
              └── TTSInterface    (PiperTTS / MockTTS)
```

### Key interfaces
- `AudioInterface` — `play_tone`, `play_file`, `play_dtmf`, `play_off_hook_tone`, `stop`, `is_playing`; all `play_*` methods on `SounddeviceAudio` are **non-blocking** (enqueue a task and return immediately); a daemon worker thread executes tasks in FIFO order; `stop()` clears the queue and halts playback within ~5 ms; `is_playing()` returns `True` if the worker is busy or the queue is non-empty
- `TTSInterface` — `speak`, `speak_and_play`, `speak_digits`, `prerender({script_name: text})`
- `PlexClientInterface` — browse (`get_playlists/artists/genres/albums_for_artist`) + genre tracks (`get_tracks_for_genre(section_id, genre_key) -> list`) + playback (`play/shuffle_all/play_tracks(track_keys, shuffle=True)/pause/unpause/skip/stop/now_playing/get_queue_position`); `now_playing()` returns `PlaybackState(item, is_paused)`
- `ErrorQueueInterface` — `log(source, severity, message)`, `get_all()`, `get_by_severity()`; injected into modules that originate errors (`tts`, `plex_store`)

### Important behavioral rules

- **`plex_store` is the only browse data path** — `menu` never calls `plex_client` directly for browse; playback commands (`play`, `shuffle_all`, `pause`, etc.) go directly to `plex_client`
- **Plex player targeting** — `PlexClient` sends `X-Plex-Target-Client-Identifier: <player_identifier>` and an auto-incrementing `commandID` param on every playback call; `X-Plex-Token` lives in headers only (never in query params for playback methods)
- **TTS pre-rendering** — all fixed `SCRIPT_*` strings from `SCRIPTS.md` are pre-rendered via `prerender({script_name: text})` at startup; only dynamic strings use live Piper at runtime
- **Piper invocation** — `_run_piper(text, output_path)` uses `--output_file <path>` so Piper writes a valid RIFF/WAV file directly; never use `--output-raw` (raw PCM) as it produces files that `wave.open()` cannot read
- **Live TTS temp files** — `_synthesize()` writes to `<cache_dir>/live/` (not system `/tmp`); `PiperTTS.__init__` wipes this directory on startup to clear session orphans; each live file is deleted immediately after `audio.play_file()` returns (safe because `SounddeviceAudio.play_file` reads the file eagerly before enqueuing); `speak()` returns a path the caller owns — it is not auto-deleted by `PiperTTS`
- **Hang-up never stops Plex** — `HANDSET_ON_CRADLE` stops local audio only; music keeps playing
- **Never hang up on the user** — the system must always be doing something while the handset is lifted; the only exit is the off-hook warning tone for unrecoverable dead-ends or inactivity timeout (`INACTIVITY_TIMEOUT = 30s`)
- **Digit disambiguation** — first digit waits `DIRECT_DIAL_DISAMBIGUATION_TIMEOUT` for a second; single digit = navigation (`0`=top, `9`=back, `1`–`8`=option); two digits within timeout = enter `DIRECT_DIAL` mode where `0`/`9` are literal
- **Digit before menu guard** — if a digit's disambiguation timeout fires while state is still `IDLE_DIAL_TONE`, `_dispatch_navigation_digit` stops the dial tone, delivers the appropriate menu (idle or playing), then **drops the digit**; the user must dial again after hearing the options; this prevents `SCRIPT_NOT_IN_SERVICE` from being spoken for premature digits
- **DTMF feedback** — `play_dtmf(digit)` called for each digit in `DIRECT_DIAL` mode
- **No local playback state** — all pause/play state derived from `now_playing()` → `PlaybackState` at speak time; never tracked locally
- **`SCRIPT_OPERATOR_OPENER` spoken once per session** — only on the first menu prompt after handset lift; subsequent prompts omit it
- **Stopping music → `IDLE_MENU` directly** — no dial tone replay after user ends a call
- **T9 browsing** — case-insensitive; strips leading "The ", "A ", "An " for indexing/sorting but speaks full names; digit `8` catches V/W/X/Y/Z and all special characters
- **Phone numbers assigned lazily** — on first encounter of a `plex_key`, never reassigned
- **`ErrorQueueInterface`** — deduplicated by `(source, message)`; persisted to SQLite; severity = `"warning"` | `"error"`; `SqliteErrorQueue.log()` uses a single atomic `INSERT ... ON CONFLICT DO UPDATE` (UPSERT) — severity is set on first insert and never updated on re-log of the same `(source, message)`
- **ASSISTANT state owns its own digit routing** — `0` and `9` are NOT reserved navigation digits inside the ASSISTANT state; `_dispatch_navigation_digit` delegates to `_handle_assistant_digit` before applying global `0`/`9` rules
- **ASSISTANT always stays in ASSISTANT until digit input** — even all-clear path stays in `ASSISTANT` state; redirect to idle/playing only happens when user dials `0`, `9`, or the redirect fires automatically after all-clear
- **Refresh always offered in ASSISTANT** — `plex_store.refresh()` option appears in every assistant menu, even when error queue is empty
- **Final selection announces digits individually** — `SCRIPT_CONNECTING_TEMPLATE` receives digits spoken as words (e.g. "five five five one two three four"), assembled from `_DIGIT_WORDS` map
- **PhoneBook returns dicts** — `lookup_by_phone_number` and `lookup_by_plex_key` return `Optional[dict]` with keys `plex_key`, `media_type`, `name`, `phone_number`; use `assign_or_get(plex_key, media_type, name)` to create entries
- **Genre plex_key encoding** — genre `MediaItem.plex_key` is stored as `"section:{section_id}/genre:{genre_key}"` (e.g., `"section:1/genre:/library/sections/1/genre/15"`); `menu._select_item()` parses this with `_parse_genre_plex_key()` to extract the two parts before calling `get_tracks_for_genre`
- **Genre playback flow** — selecting a genre calls `get_tracks_for_genre(section_id, genre_key)` then `play_tracks(track_keys, shuffle=True)`; if the genre has no tracks, `SCRIPT_NOT_IN_SERVICE` is spoken and state returns to `BROWSE_GENRES`; `play()` is never called for genres
- **`play_tracks` API** — `POST /playQueues` with `uri`, `shuffle`, and `commandID` params to create a queue, then `GET /player/playback/playMedia` with `playQueueID` to start playback

### Data stores
- **`phone_book`** (SQLite): maps `plex_key → 7-digit phone_number`; numbers never reassigned; `ASSISTANT_NUMBER` excluded from assignment
- **`plex_store`** (SQLite): persistent cache of playlists/artists/genres/albums; survives restarts; lazy-loaded, updated on successful Plex responses, unchanged on errors

### Configuration constants (from `DESIGN.md`)
| Constant | Value |
|---|---|
| `DIAL_TONE_TIMEOUT_IDLE` | 5 s |
| `DIAL_TONE_TIMEOUT_PLAYING` | 2 s |
| `INTER_DIGIT_TIMEOUT` | 300 ms |
| `DIAL_TONE_FREQUENCIES` | [350, 440] Hz |
| `MAX_MENU_OPTIONS` | 8 |
| `PHONE_NUMBER_LENGTH` | 7 |
| `ASSISTANT_MESSAGE_PAGE_SIZE` | 3 |
| `PLEX_URL` | `os.environ.get("PLEX_URL", "http://localhost:32400")` |
| `PLEX_TOKEN` | `os.environ["PLEX_TOKEN"]` (required; raises `RuntimeError` if absent) |
| `PLEX_PLAYER_IDENTIFIER` | `os.environ["PLEX_PLAYER_IDENTIFIER"]` (required; raises `RuntimeError` if absent) |

### Secrets and environment variables

- **No hardcoded secrets** — `PLEX_TOKEN` and `PLEX_PLAYER_IDENTIFIER` are read from the environment at import time; the app raises `RuntimeError` immediately if either is absent
- **`.env.example`** at the repo root documents all three Plex variables with placeholder values; never commit a real `.env` file
- **Tests that import `src.constants`** must set `PLEX_TOKEN` and `PLEX_PLAYER_IDENTIFIER` in the environment (or use `_reimport_constants()` helper from `test_constants.py`); the CI/test runner command should include these: `PLEX_TOKEN=tok PLEX_PLAYER_IDENTIFIER=pid python -m pytest`

## Development Process

Follow the Session Development Process for every coding session:

1. Write all tests for the module from TEST_SPEC.md
2. Run them — confirm they all fail
3. Implement until all tests pass
4. Check for anything the spec implies but the tests don't cover

Never skip ahead to the next module until the current one is fully tested and passing.

## Implementation Order

See `IMPL.md` § *Development Order* — interfaces first, then `error_queue`, `phone_book`, `gpio_handler`, `audio`, `tts`, `plex_client`, `plex_store`, `menu`, `session`, `main`.

## Test Strategy

- Unit tests inject mocks directly (no patching needed — ABCs are the seam)
- Integration tests are tagged and skipped by default; they hit a real Plex server
- GPIO is abstracted so `gpio_handler` can be driven by a mock pin reader
- Shared fixtures: `mock_gpio`, `mock_audio`, `mock_tts`, `mock_plex`, `mock_plex_store`, `tmp_phone_book`, `tmp_plex_store`
- Full test suite is specified in `TEST_SPEC.md`; all TTS script strings are in `SCRIPTS.md`
