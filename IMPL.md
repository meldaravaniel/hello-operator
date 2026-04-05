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
| Persistence | SQLite (three separate DB files) |

---

## Concrete Implementations

| Interface | Concrete class | Mock class |
|---|---|---|
| `AudioInterface` | `SounddeviceAudio` | `MockAudio` |
| `TTSInterface` | `PiperTTS` | `MockTTS` |
| `PlexClientInterface` | `PlexClient` | `MockPlexClient` |
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
    media_type   TEXT NOT NULL,
    name         TEXT NOT NULL,
    phone_number TEXT NOT NULL UNIQUE
);
```

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
    severity      TEXT NOT NULL,
    count         INTEGER NOT NULL DEFAULT 1,
    last_happened TEXT NOT NULL,   -- ISO8601
    PRIMARY KEY (source, message)
);
```

---

## Development Order

Suggested implementation sequence, each layer building on the last:

1. **Interfaces** — define ABCs, `MediaItem`, `PlaybackState`, `ErrorEntry`; no logic, all tests pass trivially
2. **`error_queue`** — `SqliteErrorQueue` + `MockErrorQueue`; pure Python + SQLite
3. **`phone_book`** — pure Python + SQLite, no other dependencies
4. **`gpio_handler`** — mock GPIO pin reader; fully unit-testable
5. **`audio`** — `SounddeviceAudio` + `MockAudio`
6. **`tts`** — `PiperTTS` + `MockTTS` + pre-render logic
7. **`plex_client`** — `MockPlexClient` first; real client + integration tests after
8. **`plex_store`** — uses `MockPlexClient`; tests persistence and update strategy
9. **`menu`** — state machine; uses mocks for everything including `plex_store`
10. **`session`** — wires GPIO events to menu; uses mocks
11. **`main`** — wires concrete implementations together; smoke test on real hardware
