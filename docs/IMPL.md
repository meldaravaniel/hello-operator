# Rotary Phone Media Controller — Implementation Notes

Implementation details for the system described in `DESIGN.md`. This document
covers technology choices, concrete class names, database schemas, and
suggested development order.

---

## Technology Stack

| Concern | Choice |
|---|---|
| Language | Python 3 on Raspberry Pi OS |
| Audio playback | `sounddevice` + `numpy` |
| TTS | Piper (offline binary) |
| Plex integration | Plex HTTP API (server URL + auth token) |
| FM radio | `rtl_fm` subprocess (from `rtl-sdr` package) piped to `aplay` |
| Persistence | SQLite (three separate DB files) |
| Web backend | Flask 3 — pure JSON REST API, no templates |
| Web frontend | Angular 21 SPA — standalone components, `marked` for Markdown rendering |

---

## Concrete Implementations

| Interface | Concrete class | Mock class |
|---|---|---|
| `AudioInterface` | `SounddeviceAudio` | `MockAudio` |
| `TTSInterface` | `PiperTTS` | `MockTTS` |
| `PlexClientInterface` | `PlexClient` | `MockPlexClient` |
| `RadioInterface` | `RtlFmRadio` | `MockRadio` |
| `ErrorQueueInterface` | `SqliteErrorQueue` | `MockErrorQueue` |

---

## Audio Implementation (`SounddeviceAudio`)

- Dial tone: 350 Hz + 440 Hz sine wave mix generated via `numpy`, played via `sounddevice`
- DTMF tones: two-frequency sine wave mix per digit; standard frequency pairs:

| Digit | Frequencies (Hz) |
|---|---|
| 0 | 941 + 1336 |
| 1 | 697 + 1209 |
| 2 | 697 + 1336 |
| 3 | 697 + 1477 |
| 4 | 770 + 1209 |
| 5 | 770 + 1336 |
| 6 | 770 + 1477 |
| 7 | 852 + 1209 |
| 8 | 852 + 1336 |
| 9 | 852 + 1477 |

- File playback: pre-rendered WAV files read from disk via `sounddevice`
- All playback supports immediate stop

---

## TTS Implementation (`PiperTTS`)

- Wraps the Piper binary; invoked as a subprocess
- `prerender(prompts: dict)` expects `{script_name: text}` (e.g.
  `{"SCRIPT_GREETING": "How may I direct your call?"}`). Called by `main.py` at
  startup with all pre-renderable scripts from `SCRIPTS.md`.
- The cache directory is persistent across restarts. Each entry stores the WAV
  file and a hash of the source text. At startup, `prerender` compares the hash
  of each script against the stored hash; only scripts whose hash has changed or
  whose WAV file is missing are re-synthesized. Unchanged scripts are skipped.
- `speak_and_play` uses `AudioInterface.play_file` on the cached WAV for known
  prompts; invokes Piper live only for dynamic strings
- `speak_digits` maps each character to its English word
  (e.g. `"5551234"` → `"five five five one two three four"`) then synthesizes

---

## Radio Implementation (`RtlFmRadio`)

- Launches `rtl_fm` and `aplay` as a two-process pipeline on `play(frequency_hz)`
- Command pattern:
  ```
  rtl_fm -f {frequency_hz} -M fm -s 200k -r 48k - | aplay -r 48k -f S16_LE -t raw -
  ```
- Both processes are stored as instance attributes; `stop()` terminates them both and waits for clean exit
- `is_playing()` returns `True` while the `rtl_fm` process is alive (`poll() is None`)
- Raises `RuntimeError` if `rtl_fm` or `aplay` is not found on `PATH`
- `MockRadio` records calls and exposes `set_playing(bool)` for test configuration

### Radio station config (`radio_stations.json`)

Loaded at startup from `RADIO_CONFIG_PATH`. Format:

```json
[
  {"name": "KEXP",  "frequency_mhz": 90.3, "phone_number": "5550903"},
  {"name": "KNKX",  "frequency_mhz": 88.5, "phone_number": "5550885"}
]
```

Each entry is seeded into the phone book at startup via `phone_book.seed(phone_number, plex_key, media_type, name)`, where `plex_key = "radio:{frequency_hz}"` and `media_type = "radio"`. The `seed()` method inserts the entry only if the phone number is not already present — it never overwrites an existing entry.

## Plex Client Implementation (`PlexClient`)

- Uses the Plex HTTP API with a configured server URL and auth token
- Called by `plex_store` for browse data; called directly by `menu` for all
  playback commands
- Raises exceptions on API failures; callers decide whether to log to the error queue
- Integration tests (tagged `integration`, skipped by default) hit a live server

---

## Database Schemas

### `phone_book` (SQLite)

```sql
CREATE TABLE phone_book (
    plex_key     TEXT PRIMARY KEY,
    media_type   TEXT NOT NULL CHECK(media_type IN ('playlist','artist','album','genre','radio')),
    name         TEXT NOT NULL,
    phone_number TEXT NOT NULL UNIQUE
);
```

Radio station entries use `plex_key = "radio:{frequency_hz}"` (e.g. `"radio:90300000.0"`). These are pre-seeded at startup via `phone_book.seed()`; their phone numbers are user-configured and never auto-generated.

### `plex_cache` (SQLite, separate file from `phone_book`)

```sql
CREATE TABLE plex_cache (
    cache_key  TEXT PRIMARY KEY,  -- e.g. "playlists", "albums:artist_key"
    data       TEXT NOT NULL,     -- JSON-serialized list of MediaItems
    updated_at TEXT NOT NULL      -- ISO8601 timestamp of last successful sync
);
```

### `error_queue` (SQLite)

```sql
CREATE TABLE error_queue (
    source        TEXT NOT NULL,
    message       TEXT NOT NULL,
    severity      TEXT NOT NULL CHECK(severity IN ('warning','error')),
    count         INTEGER NOT NULL DEFAULT 1,
    last_happened TEXT NOT NULL,   -- ISO8601
    PRIMARY KEY (source, message)
);
```

---

## Web Implementation (`web/app.py` + `web/angular/`)

### Flask REST API (`web/app.py`)

No templates. All routes return JSON. Key paths:

- `read_config_env()` / `write_config_env(updates)` — parse and update `config.env` in-place, preserving comments
- `read_radio_stations()` / `write_radio_stations(stations)` — JSON file I/O
- `get_service_status()` — `systemctl is-active hello-operator` via subprocess
- `restart_service()` — `sudo systemctl restart hello-operator` via subprocess; requires sudoers rule from `install.sh`
- SPA catch-all — serves `ANGULAR_DIST/index.html` for all non-API routes; serves static Angular assets by path; 404s for unknown `/api/` paths

`ANGULAR_DIST` defaults to `web/angular/dist/hello-operator/browser/` (Angular 21 `application` builder output). Override with the `ANGULAR_DIST` environment variable for testing or alternative builds.

### Angular SPA (`web/angular/`)

Built with Angular 21 standalone components (no NgModules). Key files:

| File | Purpose |
|---|---|
| `src/main.ts` | Bootstrap with `provideRouter` and `provideHttpClient` |
| `src/app/app.routes.ts` | Routes: `/` → Status, `/docs/:slug` → Docs, `/config` → Config |
| `src/app/api.service.ts` | Shared `HttpClient` wrapper; owns service-status `BehaviorSubject` |
| `src/app/status/` | Service badge + restart button |
| `src/app/docs/` | Sidebar nav, `marked.parse()` rendering, heading-ID post-processing |
| `src/app/config/` | Config field form (grouped by section) + radio station table |
| `src/styles.css` | Global styles — vintage operator aesthetic (Special Elite + IBM Plex Mono) |
| `proxy.config.json` | Dev proxy: `/api` and `/service` → `http://localhost:8080` |

**Local dev workflow:**
1. `WEB_PORT=8080 CONFIG_ENV_PATH=… python web/app.py` — Flask API
2. `cd web/angular && npm start` — Angular dev server at `:4200` (proxies API to `:8080`)

**Production build:** `cd web/angular && npm run build` — output at `dist/hello-operator/browser/`.

**Angular test setup:**

| File | Purpose |
|---|---|
| `jest.config.ts` | Jest config: `jest-preset-angular` preset, `jsdom` env, `marked` CJS alias |
| `tsconfig.spec.json` | Compiler overrides for Jest: `module: CommonJS`, `moduleResolution: node` |
| `setup-jest.ts` | Calls `setupZoneTestEnv()` from `jest-preset-angular/setup-env/zone` |

Key test patterns:
- Service tests use `provideHttpClient()` + `provideHttpClientTesting()` with `HttpTestingController`
- Component tests import the standalone component under test; dependencies are provided as jest mock objects via `{ provide: ServiceClass, useValue: fakeService }`
- Components that use `RouterLink` in their template require `provideRouter([])` so the directive has a real `Router.events` observable; the `navigate` method is then spied on with `jest.spyOn`
- `ActivatedRoute` is provided as a plain object with a `BehaviorSubject`-backed `paramMap` observable for full control over route params
- `marked` is an ES module; `moduleNameMapper` in `jest.config.ts` redirects the import to `lib/marked.cjs`

Run tests: `cd web/angular && npm test` (or `npm run test:coverage`).

---

## Development Order

Suggested implementation sequence, each layer building on the last:

1. **Interfaces** — define ABCs, `MediaItem`, `PlaybackState`, `RadioStation`, `ErrorEntry`; no logic, all tests pass trivially
2. **`error_queue`** — `SqliteErrorQueue` + `MockErrorQueue`; pure Python + SQLite
3. **`phone_book`** — pure Python + SQLite, no other dependencies; includes `seed()` method
4. **`gpio_handler`** — mock GPIO pin reader; fully unit-testable
5. **`audio`** — `SounddeviceAudio` + `MockAudio`
6. **`tts`** — `PiperTTS` + `MockTTS` + pre-render logic
7. **`plex_client`** — `MockPlexClient` first; real client + integration tests after
8. **`plex_store`** — uses `MockPlexClient`; tests persistence and update strategy
9. **`radio`** — `RtlFmRadio` + `MockRadio`; subprocess pipeline management
10. **`menu`** — state machine; uses mocks for everything including `plex_store` and `radio`
11. **`session`** — wires GPIO events to menu; uses mocks
12. **`main`** — wires concrete implementations together; loads radio config; smoke test on real hardware
13. **`web`** — Flask REST API + Angular SPA; tested via Flask test client (no Angular build required)
