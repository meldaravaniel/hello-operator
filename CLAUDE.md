# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Hello Operator** is a vintage rotary phone wired to a Raspberry Pi 4 that acts as a hands-on interface for a media player. Picking up the handset triggers an interactive voice menu styled as a telephone operator experience. The rotary dial inputs digits for T9-style browsing and direct-dial access to media. Supports **Plex** and **MPD** as swappable backends via `MEDIA_BACKEND`.

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

# Run Angular Jest tests
cd web/angular && npm test

# Run Angular Jest tests with coverage
cd web/angular && npm run test:coverage

# Run a single Angular spec file
cd web/angular && npx jest src/app/api.service.spec.ts

# Run the application
python main.py

# Trigger a Pi OS image build (GitHub Actions)
# Push a tag:  git tag v1.x.x && git push origin v1.x.x
# Or run manually via the Actions tab → "Build Raspberry Pi Image" → Run workflow
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
  plex_client.py      # PlexClient (implements MediaClientInterface)
  mpd_client.py       # MPDClient (implements MediaClientInterface)
  media_store.py      # MediaStore — backend-agnostic local SQLite browse cache
  plex_store.py       # Shim: re-exports MediaStore for backward compat
  radio.py            # RtlFmRadio, MockRadio
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
  test_mpd_client.py
  test_plex_store.py  # tests MediaStore via the plex_store shim; uses MockMediaClient
  test_radio.py
  test_menu.py
  test_session.py
  test_web.py         # Flask REST API tests (78 tests; no systemd/sudo required)

scripts/
  build-image-chroot.sh  # Runs inside the ARM chroot during CI image build

web/
  app.py                # Flask REST API (port 8080) — no templates
  angular/              # Angular 21 SPA
    src/app/            # AppComponent (nav), StatusComponent, DocsComponent, ConfigComponent
    proxy.config.json   # Dev proxy: forwards /api and /service/* to Flask on :8080
    dist/               # Production build output — served by Flask; excluded from git

.github/workflows/
  test.yml              # CI: runs unit tests on PRs and main
  build-image.yml       # Builds a flashable Raspberry Pi OS image (.img.xz)
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
              ├── media_store     (local SQLite cache; menu never calls media_client directly for browse data)
              │     └── media_client  (MediaClientInterface — PlexClient or MPDClient)
              ├── phone_book      (SQLite: auto-assigns 7-digit numbers to media_keys; radio stations pre-seeded)
              ├── AudioInterface  (SounddeviceAudio / MockAudio)
              ├── TTSInterface    (PiperTTS / MockTTS)
              └── RadioInterface  (RtlFmRadio / MockRadio)
```

### Key interfaces
- `AudioInterface` — `play_tone`, `play_file`, `play_dtmf`, `play_off_hook_tone`, `stop`, `is_playing`; all `play_*` methods on `SounddeviceAudio` are **non-blocking** (enqueue a task and return immediately); a daemon worker thread executes tasks in FIFO order; `stop()` clears the queue and halts playback within ~5 ms; `is_playing()` returns `True` if the worker is busy or the queue is non-empty
- `TTSInterface` — `speak`, `speak_and_play`, `speak_digits`, `prerender({script_name: text})`
- `MediaClientInterface` — browse (`get_playlists/artists/genres/albums_for_artist`) + genre tracks (`get_tracks_for_genre(genre_media_key: str) -> list`) + playback (`play/shuffle_all/play_tracks(track_keys, shuffle=True)/pause/unpause/skip/stop/now_playing/get_queue_position`); `now_playing()` returns `PlaybackState(item, is_paused)`; concrete impls: `PlexClient` and `MPDClient`
- `RadioInterface` — `play(frequency_hz: float)`, `stop()`, `is_playing() -> bool`; `RtlFmRadio` launches `rtl_fm | aplay` as a subprocess pipeline; `stop()` terminates both processes; no pause, no skip, no queue position
- `ErrorQueueInterface` — `log(source, severity, message)`, `get_all()`, `get_by_severity()`; injected into modules that originate errors (`tts`, `media_store`)

### Important behavioral rules

- **`media_store` is the only browse data path** — `menu` never calls `media_client` directly for browse; playback commands (`play`, `shuffle_all`, `pause`, etc.) go directly to `media_client`
- **Plex player targeting** — `PlexClient` sends `X-Plex-Target-Client-Identifier: <player_identifier>` and an auto-incrementing `commandID` param on every playback call; `X-Plex-Token` lives in headers only (never in query params for playback methods)
- **TTS pre-rendering** — all fixed `SCRIPT_*` strings from `SCRIPTS.md` are pre-rendered via `prerender({script_name: text})` at startup; only dynamic strings use live Piper at runtime
- **Piper invocation** — `_run_piper(text, output_path)` uses `--output_file <path>` so Piper writes a valid RIFF/WAV file directly; never use `--output-raw` (raw PCM) as it produces files that `wave.open()` cannot read
- **Live TTS temp files** — `_synthesize()` writes to `<cache_dir>/live/` (not system `/tmp`); `PiperTTS.__init__` wipes this directory on startup to clear session orphans; each live file is deleted immediately after `audio.play_file()` returns (safe because `SounddeviceAudio.play_file` reads the file eagerly before enqueuing); `speak()` returns a path the caller owns — it is not auto-deleted by `PiperTTS`
- **GPIO cleanup on exit** — `run()` sets `_gpio_ready = True` after `build_gpio_handler()` succeeds and calls the module-level `_gpio_cleanup()` in the `finally` block only when `_gpio_ready` is set; `_gpio_cleanup` is a real function (not a lambda) at module scope so tests can patch `src.main._gpio_cleanup` to assert it was called
- **Hang-up never stops media playback** — `HANDSET_ON_CRADLE` stops local audio only; music keeps playing on the backend
- **Never hang up on the user** — the system must always be doing something while the handset is lifted; the only exit is the off-hook warning tone for unrecoverable dead-ends or inactivity timeout (`INACTIVITY_TIMEOUT = 30s`)
- **Digit disambiguation** — first digit waits `DIRECT_DIAL_DISAMBIGUATION_TIMEOUT` for a second; single digit = navigation (`0`=top, `9`=back, `1`–`8`=option); two digits within timeout = enter `DIRECT_DIAL` mode where `0`/`9` are literal
- **Digit before menu guard** — if a digit's disambiguation timeout fires while state is still `IDLE_DIAL_TONE`, `_dispatch_navigation_digit` stops the dial tone, delivers the appropriate menu (idle or playing), then **drops the digit**; the user must dial again after hearing the options; this prevents `SCRIPT_NOT_IN_SERVICE` from being spoken for premature digits
- **DTMF feedback** — `play_dtmf(digit)` called for each digit in `DIRECT_DIAL` mode
- **No local playback state** — all pause/play state derived from `now_playing()` → `PlaybackState` at speak time; never tracked locally
- **`SCRIPT_OPERATOR_OPENER` spoken once per session** — only on the first menu prompt after handset lift; subsequent prompts omit it
- **Stopping music → `IDLE_MENU` directly** — no dial tone replay after user ends a call
- **T9 browsing** — case-insensitive; strips leading "The ", "A ", "An " for indexing/sorting but speaks full names; digit `8` catches V/W/X/Y/Z and all special characters
- **Phone numbers assigned lazily** — on first encounter of a `media_key`, never reassigned
- **`ErrorQueueInterface`** — deduplicated by `(source, message)`; persisted to SQLite; severity = `"warning"` | `"error"`; `SqliteErrorQueue.log()` uses a single atomic `INSERT ... ON CONFLICT DO UPDATE` (UPSERT) — severity is set on first insert and never updated on re-log of the same `(source, message)`
- **ASSISTANT state owns its own digit routing** — `0` and `9` are NOT reserved navigation digits inside the ASSISTANT state; `_dispatch_navigation_digit` delegates to `_handle_assistant_digit` before applying global `0`/`9` rules
- **ASSISTANT always stays in ASSISTANT until digit input** — even all-clear path stays in `ASSISTANT` state; redirect to idle/playing only happens when user dials `0`, `9`, or the redirect fires automatically after all-clear
- **Refresh always offered in ASSISTANT** — `media_store.refresh()` option appears in every assistant menu, even when error queue is empty
- **Final selection announces digits individually** — `SCRIPT_CONNECTING_TEMPLATE` receives digits spoken as words (e.g. "five five five one two three four"), assembled from `DIGIT_WORDS` in `constants.py`
- **PhoneBook returns dicts** — `lookup_by_phone_number` and `lookup_by_media_key` return `Optional[dict]` with keys `media_key`, `media_type`, `name`, `phone_number`; use `assign_or_get(media_key, media_type, name)` to create entries
- **Genre media_key encoding (Plex)** — genre `MediaItem.media_key` is stored as `"section:{section_id}/genre:{genre_key}"` (e.g., `"section:1/genre:/library/sections/1/genre/15"`); `menu._select_item()` passes this whole key to `get_tracks_for_genre(genre_media_key)` and the Plex client parses it internally
- **Genre media_key encoding (MPD)** — genre `MediaItem.media_key` is stored as `"genre:{name}"` (e.g., `"genre:Jazz"`); `MPDClient.get_tracks_for_genre` parses the name from the key
- **Genre playback flow** — selecting a genre calls `get_tracks_for_genre(genre_media_key)` then `play_tracks(track_keys, shuffle=True)`; if the genre has no tracks, `SCRIPT_NOT_IN_SERVICE` is spoken and state returns to `BROWSE_GENRES`; `play()` is never called for genres
- **`play_tracks` API (Plex)** — `POST /playQueues` with `uri`, `shuffle`, and `commandID` params to create a queue, then `GET /player/playback/playMedia` with `playQueueID` to start playback
- **Radio media_key encoding** — radio entries in the phone book use `media_key = "radio:{frequency_hz}"` (e.g. `"radio:90300000.0"`) and `media_type = "radio"`; seeded at startup via `phone_book.seed()` from `radio_stations.json`; `menu._execute_direct_dial()` parses the frequency from the media_key and calls `radio.play(frequency_hz)`
- **Radio playback flow** — dialing a radio number stops any active media playback, stops any active radio stream, speaks `SCRIPT_RADIO_CONNECTING`, calls `radio.play(frequency_hz)`, and transitions to `RADIO_PLAYING_MENU`; hang-up never stops radio
- **Radio playing menu** — `RADIO_PLAYING_MENU` state offers only disconnect (digit 3 → `radio.stop()` → `IDLE_MENU`) and new party (digit 0 → `radio.stop()` → `IDLE_MENU`); no pause, no skip; lifting the handset while radio is playing delivers `SCRIPT_RADIO_PLAYING_GREETING` then `SCRIPT_RADIO_PLAYING_MENU`
- **Radio state is local** — unlike Plex/MPD state (never tracked locally; always queried via `now_playing()`), radio playing state is tracked via `radio.is_playing()`; there is no remote authority to query; menu checks `radio.is_playing()` when `media_client.now_playing().item is None` to decide between idle and radio playing menus
- **Failed direct dial re-delivers prior menu** — `_pre_dial_state` is set in `_enter_direct_dial()` to the state before DIRECT_DIAL was entered; on failure (`entry is None`), if `_pre_dial_state` was `IDLE_DIAL_TONE` (user dialed before any menu was delivered), `now_playing()` is queried to pick the correct top-level menu; otherwise `_state` is restored to `_pre_dial_state` and `_re_deliver_current_state()` re-announces the menu; `_pre_dial_state` is cleared in `on_handset_on_cradle()`
- **`load_radio_stations(path)`** — module-level helper in `main.py`; reads `radio_stations.json`, converts `frequency_mhz` → `frequency_hz` (multiply by 1_000_000), returns `list[RadioStation]`; returns `[]` (with warning log) on `FileNotFoundError` or JSON/key parse error; never raises

### Data stores
- **`phone_book`** (SQLite): maps `media_key → 7-digit phone_number`; numbers never reassigned; `ASSISTANT_NUMBER` excluded from assignment
- **`media_store`** (SQLite, `src/media_store.py`): persistent cache of playlists/artists/genres/albums; survives restarts; lazy-loaded, updated on successful media client responses, unchanged on errors; `plex_store.py` is a backward-compat shim that re-exports `MediaStore`

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
| `MEDIA_BACKEND` | `os.environ.get("MEDIA_BACKEND", "plex")` — `"plex"` or `"mpd"` |
| `PLEX_URL` | `os.environ.get("PLEX_URL", "http://localhost:32400")` |
| `PLEX_TOKEN` | `os.environ.get("PLEX_TOKEN", "")` — required when `MEDIA_BACKEND=plex`; raises `RuntimeError` at startup if absent |
| `PLEX_PLAYER_IDENTIFIER` | `os.environ.get("PLEX_PLAYER_IDENTIFIER", "")` — required when `MEDIA_BACKEND=plex`; raises `RuntimeError` at startup if absent |
| `MPD_HOST` | `os.environ.get("MPD_HOST", "localhost")` |
| `MPD_PORT` | `int(os.environ.get("MPD_PORT", "6600"))` |
| `ASSISTANT_NUMBER` | `os.environ["ASSISTANT_NUMBER"]` (always required; raises `RuntimeError` if absent) |
| `HOOK_SWITCH_PIN` | `int(os.environ.get("HOOK_SWITCH_PIN", "17"))` — BCM pin; non-integer value raises `ValueError` at import |
| `PULSE_SWITCH_PIN` | `int(os.environ.get("PULSE_SWITCH_PIN", "27"))` — BCM pin; non-integer value raises `ValueError` at import |
| `PIPER_BINARY` | `os.environ.get("PIPER_BINARY", "/usr/local/bin/piper")` |
| `PIPER_MODEL` | `os.environ.get("PIPER_MODEL", "/usr/local/share/piper/en_US-lessac-medium.onnx")` |
| `TTS_CACHE_DIR` | `os.environ.get("TTS_CACHE_DIR", "/var/cache/hello-operator/tts")` |
| `PHONE_NUMBER_GENERATE_MAX_ATTEMPTS` | `1000` — max retries in `_generate_unique_number`; exceeding this raises `RuntimeError("Phone book number space exhausted")` |
| `RADIO_CONFIG_PATH` | `"/etc/hello-operator/radio_stations.json"` — path to JSON file seeding radio stations into phone book at startup |

### Secrets and environment variables

- **No hardcoded secrets** — `PLEX_TOKEN` and `PLEX_PLAYER_IDENTIFIER` are validated at startup (when `MEDIA_BACKEND=plex`); `ASSISTANT_NUMBER` is always required; the app raises `RuntimeError` if any required variable is absent
- **`config.env.example`** at the repo root documents all environment variables accepted by `constants.py` with placeholder or default values; copy it to `/etc/hello-operator/config.env` for deployment; never commit a real `.env` file
- **Tests that import `src.constants`** must set `ASSISTANT_NUMBER` in the environment; when testing Plex-specific code also set `PLEX_TOKEN` and `PLEX_PLAYER_IDENTIFIER`; the CI/test runner command should include these: `PLEX_TOKEN=tok PLEX_PLAYER_IDENTIFIER=pid ASSISTANT_NUMBER=5550000 python -m pytest`

## Development Process

Follow the Session Development Process for every coding session:

1. Write all tests for the module from TEST_SPEC.md
2. Run them — confirm they all fail
3. Implement until all tests pass
4. Check for anything the spec implies but the tests don't cover

Never skip ahead to the next module until the current one is fully tested and passing.

## Implementation Order

See `IMPL.md` § *Development Order* — interfaces first, then `error_queue`, `phone_book`, `gpio_handler`, `audio`, `tts`, `plex_client` / `mpd_client`, `media_store`, `menu`, `session`, `main`.

## Test Strategy

- Unit tests inject mocks directly (no patching needed — ABCs are the seam)
- Integration tests are tagged and skipped by default; they hit a real Plex or MPD server
- GPIO is abstracted so `gpio_handler` can be driven by a mock pin reader
- Shared fixtures: `mock_gpio`, `mock_audio`, `mock_tts`, `mock_plex` (also `MockMediaClient`), `mock_plex_store` (also `MockMediaStore`), `tmp_phone_book`, `tmp_plex_store`
- All TTS script strings are in `SCRIPTS.md`

**What is NOT covered by unit tests:**
- Physical GPIO wiring correctness
- I2S audio hardware driver behavior
- Actual Plex or MPD server responses (covered by integration tests, skipped by default)
- TTS audio quality

### Clean-room rules (unit tests only; integration tests are exempt)

- **No writes outside `tmp_path`** — any file I/O in a unit test must go through
  pytest's `tmp_path` fixture. Never pass production paths
  (`/var/lib/hello-operator/`, `/etc/hello-operator/`, `/var/cache/hello-operator/`,
  `/usr/local/`) to any class under test.
- **Use the `tmp_*` fixtures** — always use `tmp_phone_book`, `tmp_plex_store` (for `MediaStore`), and
  `tmp_error_queue` from `conftest.py`; never construct real DB paths manually.
- **`tmp_path` not `/tmp/`** — use pytest's `tmp_path`, not hardcoded `/tmp/` paths.
  `tmp_path` is isolated per test and cleaned up automatically.
- **Environment variables via `monkeypatch`** — use `monkeypatch.setenv` /
  `monkeypatch.delenv`, never assign to `os.environ` directly. `monkeypatch`
  auto-restores the environment after each test.
- **`src.constants` reimport** — `src.constants` reads env vars at module level, so
  tests that need different values must call `monkeypatch.setenv` before
  `importlib.reload(src.constants)`. Always reload again in teardown (or use a
  fixture) so the modified module does not leak into subsequent tests.
- **No real subprocess launches** — mock `subprocess.Popen` or the concrete class
  (`RtlFmRadio`, `PiperTTS`) for all unit tests. Never launch real `rtl_fm`,
  `aplay`, or `piper` processes.
- **Project-root file tests are read-only** — tests that verify repo files
  (`install.sh`, `*.service.template`, `*.example`, `INSTALL.md`) only read and
  parse those files. They never write to system paths or execute the files.
