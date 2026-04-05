# Rotary Phone Media Controller — Design Overview

## Project Summary

A vintage rotary phone is wired to a Raspberry Pi 4 and transformed into a
hands-on interface for a Plex media server. Picking up the handset triggers an
interactive voice menu — styled as a telephone operator experience — that lets
the user browse and play playlists, artists, albums, and genres by dialing.
The rotary dial doubles as both a direct-dial input (for known "phone numbers"
mapped to media) and a menu navigation device.

---

## Hardware

| Component | Part | Notes |
|---|---|---|
| Computer | Raspberry Pi 4 (2GB) | Target platform |
| Amplifier | Adafruit MAX98357A I2S 3W Class D | Connected via I2S |
| Hook switch | Rotary phone hook switch → GPIO | Open = on cradle, closed = lifted |
| Pulse switch | Rotary phone dial → optocoupler → GPIO | Open = resting, closed = pulsing |
| Speaker | Rotary phone handset speaker | Driven by MAX98357A |

### GPIO Signal Conventions

| Signal | Resting state | Active state |
|---|---|---|
| Hook switch | HIGH (open circuit) | LOW (handset lifted) |
| Pulse switch | HIGH (open circuit) | LOW (dial pulsing) |

---

## Software Architecture

### Language & Runtime
Python 3 on Raspberry Pi OS.

### Dependency Philosophy
All hardware-dependent and external-service modules sit behind abstract
interfaces (Python ABCs). No module above the interface layer imports a concrete
dependency directly. This means:
- Unit tests inject mocks without patching
- Swapping `sounddevice` for `pygame`, or Piper for espeak, is a one-file change
- The menu and session logic are fully testable without hardware or network

### Module Map

```
┌─────────────────────────────────────────────────────┐
│                      main.py                        │
│           wires everything together                 │
└────────────────────┬────────────────────────────────┘
                     │
          ┌──────────▼──────────┐
          │       session       │
          │  lifecycle manager  │
          └──┬──────────────┬───┘
             │              │
    ┌────────▼──┐      ┌────▼────────┐
    │gpio_handler│      │    menu     │
    │HW events  │      │state machine│
    └────────────┘      └──┬──────┬──┘
                           │      │
              ┌────────────▼┐   ┌─▼───────────┐
              │ plex_store  │   │  phone_book  │
              │ local cache │   │   (SQLite)   │
              └──────┬──────┘   └─────────────┘
                     │
              ┌──────▼──────┐
              │ plex_client │
              │  interface  │
              └─────────────┘
                     │
              ┌──────▼──────┐   ┌─────────────┐
              │    audio    │   │     tts      │
              │  interface  │   │  interface   │
              └─────────────┘   └─────────────┘
```

---

## Interfaces

### `AudioInterface`
Abstracts all sound output. Concrete: `SounddeviceAudio`. Mock: `MockAudio`.

| Method | Description |
|---|---|
| `play_tone(frequencies, duration_ms)` | Generate and play a sine wave mix |
| `play_file(path)` | Play a pre-rendered audio file |
| `play_off_hook_tone()` | Play off-hook warning tone continuously until `stop()` |
| `stop()` | Stop any current playback immediately |
| `is_playing() -> bool` | True if audio is currently playing |

### `TTSInterface`
Abstracts text-to-speech. Concrete: `PiperTTS`. Mock: `MockTTS`.

| Method | Description |
|---|---|
| `speak(text) -> str` | Synthesize text; return path to audio file |
| `speak_and_play(text)` | Synthesize and play immediately |
| `speak_digits(digits)` | Speak each character as an individual digit word |
| `prerender(prompts: dict)` | Pre-synthesize fixed strings to cached audio files |

Fixed menu prompts are pre-rendered at startup. `speak_and_play` uses the cached
file for known prompts; Piper is only invoked at runtime for dynamic strings
(media names, phone numbers).

### `PlexClientInterface`
Abstracts all Plex API calls. Concrete: `PlexClient`. Mock: `MockPlexClient`.

| Method | Description |
|---|---|
| `get_playlists()` | Return all playlists as `MediaItem` list |
| `get_artists()` | Return all artists |
| `get_genres()` | Return all genres |
| `get_albums_for_artist(artist_key)` | Return albums for a given artist |
| `play(plex_key)` | Start playback of a media item |
| `pause()` | Pause current playback |
| `unpause()` | Resume paused playback |
| `skip()` | Skip to next track |
| `stop()` | Stop playback entirely |
| `now_playing() -> MediaItem | None` | Return currently playing item, or None |
| `get_queue_position() -> tuple[int, int]` | Return (current_track, total_tracks) |

---

## Core Data Types

```python
@dataclass
class MediaItem:
    plex_key: str
    name: str
    media_type: str  # "playlist" | "artist" | "album" | "genre"
```

---

## Module Descriptions

### `gpio_handler`
Polls GPIO pins and emits clean events to the rest of the system. Handles
debouncing for both the hook switch and the pulse switch. Decodes pulse bursts
into digits using the inter-digit timeout. Never exposes raw GPIO state to
higher layers.

**Events emitted:**
- `HANDSET_LIFTED`
- `HANDSET_ON_CRADLE`
- `DIGIT_DIALED(digit: int)`

### `audio`
Concrete implementation of `AudioInterface` using `sounddevice` and `numpy`.
Generates dial tone as a 350 Hz + 440 Hz sine wave mix. Plays pre-rendered audio
files from disk. Supports immediate stop.

### `tts`
Concrete implementation of `TTSInterface` wrapping the Piper binary. At startup,
pre-renders all fixed menu prompt strings to WAV files in a local cache
directory. Runtime synthesis is used only for dynamic content. `speak_digits`
maps each character to its English word and synthesizes the full string.

### `phone_book`
Manages a SQLite database mapping Plex media items to auto-generated 7-digit
phone numbers. Numbers are assigned once and never reassigned. Supports lookup
by Plex key or by phone number. Numbers are formatted and spoken digit-by-digit.

**Schema:**
```sql
CREATE TABLE phone_book (
    plex_key    TEXT PRIMARY KEY,
    media_type  TEXT NOT NULL,
    name        TEXT NOT NULL,
    phone_number TEXT NOT NULL UNIQUE
);
```

### `plex_store`
A persistent, session-independent local cache that sits between the menu and
`plex_client`. The menu never calls `plex_client` directly for browse data —
it always goes through `plex_store`. Plex is treated as the source of truth,
but is assumed to change infrequently.

**Persistence:** SQLite (separate from `phone_book`). Survives restarts and
persists across sessions.

**Stored data:**
- Full list of playlists, artists, genres (as `MediaItem` lists)
- Albums per artist (keyed by artist `plex_key`)
- Derived boolean flags: `playlists_has_content`, `artists_has_content`,
  `genres_has_content`

**Initialization:** If local store is empty for a category, fetch from Plex and
populate. Otherwise use local data without an API call.

**Update strategy:**
- On a successful Plex response that differs from local data: update local store
- On a Plex API error: leave local store unchanged
- On a playback failure where Plex indicates the item no longer exists: remove
  that item from local store, serve `SCRIPT_NOT_IN_SERVICE`

**Refresh:** The diagnostic assistant exposes a manual full-refresh option that
re-fetches all categories from Plex and updates local store (successful calls
only). This is the only way to proactively sync local state with Plex outside
of the normal lazy-update path.

**Schema:**
```sql
CREATE TABLE plex_cache (
    cache_key   TEXT PRIMARY KEY,  -- e.g. "playlists", "albums:artist_key"
    data        TEXT NOT NULL,     -- JSON-serialized list of MediaItems
    updated_at  TEXT NOT NULL      -- ISO8601 timestamp of last successful sync
);
```

### `plex_client`
Concrete implementation of `PlexClientInterface` using the Plex HTTP API and a
configured server URL + auth token. Called only by `plex_store` for browse
data, and directly by the menu for playback commands (`play`, `pause`,
`unpause`, `skip`, `stop`, `now_playing`, `get_queue_position`). Integration
tests against the real server are marked and skipped during normal unit test
runs.

### `menu`
The heart of the application. A state machine that receives digit events and
system state, then issues audio and Plex commands. Has no knowledge of GPIO,
audio hardware, or HTTP — only the interfaces.

**States:**
- `IDLE_DIAL_TONE` — handset lifted, playing dial tone, waiting
- `IDLE_MENU` — browsing from idle (no music playing)
- `PLAYING_MENU` — browsing while music is active
- `BROWSE_PLAYLISTS` / `BROWSE_ARTISTS` / `BROWSE_GENRES` — narrowing by T9
- `ARTIST_SUBMENU` — shuffle artist or pick album
- `BROWSE_ALBUMS` — T9 narrowing through an artist's albums
- `DIRECT_DIAL` — accumulating digits for a direct phone number
- `ASSISTANT` — diagnostic status readout

**Reserved digits (all states):**
| Digit | Action |
|---|---|
| `0` | Return to top-level menu for current system state |
| `9` | Go back one menu level (or stay at top) |

**Invalid digit handling:** Any digit that has no corresponding option in the
current menu state → TTS says "I'm sorry, that number is not in service." and
re-reads the current menu options.

**Local state vs. Plex queries:**
- **Local state** tracks: paused/unpaused, current session activity — things
  the system itself caused and are deterministic
- **Plex query** determines: whether something is currently playing (`now_playing()`)
  and queue position (`get_queue_position()`) — nondeterministic, can change
  without system input (e.g. playlist ends naturally)

### `session`
Owns the application lifecycle for a single handset interaction. Listens for
GPIO events, starts/stops the dial tone timer, routes digits to the menu state
machine, and handles graceful cleanup on hang-up. Does not stop Plex playback
on hang-up — music continues if it was playing.

At handset lift, checks `plex_store` for category availability flags. If local
store is already populated, no API call is made — the flags are used directly.
If local store is not yet populated, fetches from Plex to initialize it. Only
categories with at least one playable item are offered as options. If the Plex
connection fails and local store is also empty, plays `SCRIPT_PLEX_FAILURE` and
enters the retry loop.

Caches each successful Plex browse result as the user navigates. If a Plex API
call fails mid-browse, apologizes about "service degradation" and re-prompts
from the last successful cached state. If no cached state exists, returns to
top level.

Hang-up (HANDSET_ON_CRADLE) stops all local audio immediately — even mid-TTS
— and cleans up session state. Plex playback is not affected.

Direct dial accumulates up to 7 digits. Lookup fires at exactly 7; subsequent
digits are ignored. Hang-up before 7 digits silently abandons the partial number.

---

## User Experience Flow

### Handset lifted — system idle (no music playing)

```
Lift handset
  → Dial tone plays (350 Hz + 440 Hz)
  → [5 second timeout, no input]
  → "Operator, how may I direct your call?"
  → [brief pause]
  → "If you know your party's extension, please dial their number."
  → Wait for digit input

Digit 1 → Browse playlists
Digit 2 → Browse artists
Digit 3 → Browse genres
Digit 4 → Shuffle everything
```

### Handset lifted — music is playing

```
Lift handset
  → Dial tone plays (350 Hz + 440 Hz)
  → [2 second timeout, no input]
  → Check now_playing() at speak time:
      If None (music ended during dial tone): deliver idle prompt instead
  → "Operator. Your call with [media name] is in progress."
  → Options announced dynamically based on current state:
      Digit 1 → "pause your call" (if playing) or "resume your call" (if paused)
      Digit 2 → "skip" (only offered if not on last track)
      Digit 3 → End call (stop music, go to idle state)
      Digit 0 → Go to idle top-level menu
```

### Browsing (playlist, artist, genre, album)

```
System asks user to dial by first letter (T9, starting at 1)

T9 mapping (1-indexed, 9 reserved for back):
  1 → A B C
  2 → D E F
  3 → G H I
  4 → J K L
  5 → M N O
  6 → P Q R
  7 → S T U
  8 → V W X Y Z / special characters (!, @, #, etc.)
  Each number digit (0–8) also matches names starting with that literal digit
    e.g. dialing 3 matches "30 Seconds to Mars" alongside G/H/I names

Article stripping: leading "The ", "A ", and "An " are ignored for T9 indexing
and sorting. The full name is always used when speaking to the user.
  e.g. "The Beatles" is indexed as "Beatles" → found under dial 1 (ABC)
  e.g. "A Tribe Called Quest" → indexed as "Tribe" → found under dial 7 (STU)

Items with no playable content are excluded from all browse results entirely.

If results > 8: "There are a lot of parties. Please dial the next letter."
               → prompt for next letter, repeat indefinitely until ≤ 8
If results ≤ 8: list as numbered options (1–8)
If results = 1: auto-select
If results = 0: "I'm sorry, that number is not in service." → back one level
```

### Artist submenu

```
Artist selected →
  "To speak to [artist], dial 1."
  If artist has albums: "For a particular album, dial 2."

Digit 1 → Play artist shuffled
Digit 2 → Browse albums using T9 narrowing (same system as playlists/artists)
  If artist has exactly 1 album: "To call [album name], dial 1."
```

### Final selection

```
Selection confirmed →
  "Thank you. I'm connecting you to [digit] [digit] [digit] - [digit] [digit] [digit] [digit].
   [media name]."
  → Plex begins playback
  → Handset can be hung up; music continues
```

### Direct dial

```
Digit dialed during dial tone →
  Dial tone stops
  System accumulates up to 7 digits
  After 7 digits: look up in phone book
    Found → announce and play
    Not found → "I'm sorry, that number is not in service."
  8th digit and beyond → ignored
  Hang up before 7 digits → silent cleanup, no lookup
```

### Diagnostic assistant

A reserved 7-digit number (configured at setup, never assigned to media) connects
to the system's built-in diagnostic assistant.

```
If error queue is non-empty:
  Top-level idle menu includes: "You have a missed call. To reach your assistant,
  dial [assistant number]." (optional — normal operation continues regardless)

Calling the assistant number →
  Assistant answers with overall system status summary
  If no errors/warnings:
    "Everything's fine, boss." + valediction + theatrical "hang up" language
    → redirects to idle or playing menu (whichever is appropriate)
  If messages present:
    Options offered dynamically by type (e.g. warnings = 1, errors = 2)
    Plus option to return to top-level menu
    If message type selected:
      States count, reads first 3, then asks "shall I continue?"
      Digit input to continue reading (next 3), or dial 0/9 to navigate
    Assistant always offers: repeat last, go deeper, go back, return to menu
    "Hang up" language used for flavor only — actual result is always a menu redirect
  Additional assistant option (always available):
    "To refresh my information from the exchange, dial [n]."
    → triggers full re-fetch of all categories from Plex
    → updates local store for all successful responses
    → reports back: "All done, I've updated my records." or
      "I'm sorry, I had some trouble reaching the exchange." if Plex unreachable
    → then offers to return to menu or stay in assistant
  Messages are NEVER marked as read via phone interaction.
  Clearing requires manual intervention outside the system.
```

### Core principle: never hang up on the user

As long as the handset is lifted, the system must always be doing something.
Forced termination is never acceptable. The only exception is a true dead-end
where no further interaction is possible — in that case the system plays:

> "I'm sorry, your call cannot be connected at this time. Please hang up and
> try again later."

...followed by a brief pause and then the **off-hook warning tone**, played
continuously until the user physically hangs up.

---

### Error handling

**Pre-rendered cache miss at runtime:**
- Log warning to error queue
- Fall back to live Piper synthesis immediately
- Attempt to repopulate cache file with finite retry/backoff in background
- If retries exhausted: log persistent error to error queue, continue live synthesis

**Piper completely non-functional:**
- Log error to error queue
- No TTS possible; play off-hook warning tone continuously until user hangs up

**Plex connection failure at session start:**
- Play vintage "service disconnected" message
- Offer retry loop: "If you'd like me to retry, dial 1. Otherwise, please hang
  up and try again later."
- Retry as many times as user requests; never force session end

**Phone book DB unreadable:**
- Play distinct vintage message implying internal switchboard failure (not a
  connection/line issue)
- Offer same retry loop as Plex connection failure
- Never force session end

**No playable content at top level:**
Triggered when:
- Pre-load at handset lift finds zero playable content across all categories, OR
- User navigates back to top level and all categories are now empty

Response:
- Play vintage "out of service" message
- Brief pause
- Off-hook warning tone, played continuously until user hangs up

**Plex API failure mid-browse:**
- Apologize about "service degradation"
- Return to last successfully cached browse state and re-prompt
- If no cached state: return to top level
- If top level also has no content: treat as "no playable content" above

**Error queue:**
- Deduplicated — same error does not pile up
- Read-only from phone interface
- Clearable only via manual intervention outside the system

---

## Configuration Constants

| Constant | Value | Description |
|---|---|---|
| `DIAL_TONE_TIMEOUT_IDLE` | 5 s | Silence before idle operator prompt |
| `DIAL_TONE_TIMEOUT_PLAYING` | 2 s | Silence before playing-state prompt |
| `INTER_DIGIT_TIMEOUT` | 300 ms | Gap after last pulse → digit complete |
| `DIAL_TONE_FREQUENCIES` | [350, 440] Hz | Standard PSTN dial tone |
| `MAX_MENU_OPTIONS` | 8 | Max items listed before narrowing required |
| `PHONE_NUMBER_LENGTH` | 7 | Digits in an assigned phone number |
| `ASSISTANT_MESSAGE_PAGE_SIZE` | 3 | Messages read aloud per page in assistant |
| `ASSISTANT_NUMBER` | configured at setup | Reserved 7-digit diagnostic number; excluded from phone book assignment |
| `CACHE_RETRY_MAX` | TBD | Max repopulation attempts for missing TTS cache files |
| `CACHE_RETRY_BACKOFF` | TBD | Base backoff interval between cache repopulation attempts |

---

## Testing Strategy

All unit tests run without hardware, network, or audio output. The three
interfaces (`AudioInterface`, `TTSInterface`, `PlexClientInterface`) are the
seams where mocks are injected. GPIO is also abstracted so the handler can be
driven by a mock pin reader in tests.

Integration tests (tagged, skipped by default) cover the real `PlexClient`
against a live server.

See `TEST_SPEC.md` for the full test suite.

---

## Development Order

Suggested implementation sequence, each layer building on the last:

1. **Interfaces** — define ABCs and `MediaItem`; no logic, all tests pass trivially
2. **`phone_book`** — pure Python + SQLite, no other dependencies
3. **`gpio_handler`** — mock GPIO pin reader; fully unit-testable
4. **`audio`** — `SounddeviceAudio` + `MockAudio`
5. **`tts`** — `PiperTTS` + `MockTTS` + pre-render logic
6. **`plex_client`** — `MockPlexClient` first; real client + integration tests after
7. **`plex_store`** — uses `MockPlexClient`; tests persistence and update strategy
8. **`menu`** — state machine; uses mocks for everything including `plex_store`
9. **`session`** — wires GPIO events to menu; uses mocks
10. **`main`** — wires concrete implementations together; smoke test on real hardware
