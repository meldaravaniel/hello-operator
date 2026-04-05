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
Abstracts all sound output.

| Method | Description |
|---|---|
| `play_tone(frequencies, duration_ms)` | Generate and play a sine wave mix |
| `play_file(path)` | Play a pre-rendered audio file |
| `play_dtmf(digit: int)` | Play the standard DTMF tone for a digit (0–9) |
| `play_off_hook_tone()` | Play off-hook warning tone continuously until `stop()` |
| `stop()` | Stop any current playback immediately |
| `is_playing() -> bool` | True if audio is currently playing |

### `TTSInterface`
Abstracts text-to-speech.

| Method | Description |
|---|---|
| `speak(text) -> str` | Synthesize text; return path to audio file |
| `speak_and_play(text)` | Synthesize and play immediately |
| `speak_digits(digits)` | Speak each character as an individual digit word |
| `prerender(prompts: dict)` | Pre-synthesize fixed strings to cached audio files |

Fixed menu prompts are pre-rendered to a persistent cache directory that survives restarts. At startup, each script's text is hashed and compared against the stored hash; only scripts whose hash has changed or whose audio file is missing are re-synthesized. `speak_and_play` uses cached files for known prompts; live synthesis is used only for dynamic strings (media names, phone numbers).

### `PlexClientInterface`
Abstracts all Plex API calls.

| Method | Description |
|---|---|
| `get_playlists()` | Return all playlists as `MediaItem` list |
| `get_artists()` | Return all artists |
| `get_genres()` | Return all genres |
| `get_albums_for_artist(artist_key)` | Return albums for a given artist |
| `play(plex_key)` | Start playback of a media item |
| `shuffle_all()` | Shuffle and play the entire library |
| `pause()` | Pause current playback |
| `unpause()` | Resume paused playback |
| `skip()` | Skip to next track |
| `stop()` | Stop playback entirely |
| `now_playing() -> PlaybackState` | Return current playback state (see Core Data Types) |
| `get_queue_position() -> tuple[int, int]` | Return (current_track, total_tracks) |

---

## Core Data Types

```python
@dataclass
class MediaItem:
    plex_key: str
    name: str
    media_type: str  # "playlist" | "artist" | "album" | "genre"

@dataclass
class PlaybackState:
    item: MediaItem | None  # None if nothing is playing
    is_paused: bool         # True if playback is paused; always False when item is None
```

### `ErrorQueueInterface`
Abstracts the persistent error log.

| Method | Description |
|---|---|
| `log(source: str, severity: str, message: str)` | Add or update an entry; deduplicated by `(source, message)`; increments count and updates `last_happened` on repeat |
| `get_all() -> list[ErrorEntry]` | Return all entries, newest first |
| `get_by_severity(severity: str) -> list[ErrorEntry]` | Return entries filtered by `"warning"` or `"error"` |

`ErrorEntry` fields: `source`, `severity`, `message`, `count`, `last_happened`.

**Storage:** Persisted to disk; survives restarts. Clearable only via manual intervention outside the system.

**Injection:** `ErrorQueueInterface` is injected into any module that originates errors (`tts`, `plex_store`). Modules that only re-raise exceptions (e.g. `plex_client`) do not receive it — callers decide whether to log.

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
Concrete implementation of `AudioInterface`. Generates dial tone, DTMF tones,
and the off-hook warning tone programmatically. Plays pre-rendered audio files
from disk. All playback supports immediate stop.

### `tts`
Concrete implementation of `TTSInterface`. At startup, `main.py` calls
`prerender({script_name: text, ...})` with all pre-renderable scripts from
`SCRIPTS.md`. Runtime synthesis is used only for dynamic content. `speak_digits`
maps each character to its English word and synthesizes the full string.

### `phone_book`
Manages a persistent database mapping Plex media items to auto-generated 7-digit
phone numbers. Numbers are assigned lazily — on first encounter of a `plex_key`
(either at `plex_store` population time or at first selection) — and never
reassigned. Supports lookup by Plex key or by phone number. Numbers are formatted
and spoken digit-by-digit.

### `plex_store`
A persistent, session-independent local cache that sits between the menu and
`plex_client`. The menu never calls `plex_client` directly for browse data —
it always goes through `plex_store`. Plex is treated as the source of truth,
but is assumed to change infrequently.

**Persistence:** Survives restarts and persists across sessions.

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

### `plex_client`
Concrete implementation of `PlexClientInterface`. Called only by `plex_store`
for browse data, and directly by the menu for playback commands (`play`,
`shuffle_all`, `pause`, `unpause`, `skip`, `stop`, `now_playing`,
`get_queue_position`). `now_playing()` returns a `PlaybackState` containing the
current `MediaItem` (or `None`) and whether playback is paused. Raises exceptions
on API failures; callers decide whether to log. Integration tests against the
real server are marked and skipped during normal unit test runs.

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

**Reserved digits (all states except `DIRECT_DIAL`):**
| Digit | Action |
|---|---|
| `0` | Return to top-level menu for current system state |
| `9` | Go back one menu level (or stay at top) |

**Digit disambiguation:** When a digit is received, the system waits up to
`DIRECT_DIAL_DISAMBIGUATION_TIMEOUT` for a second digit before acting. If no
second digit arrives, the single digit is treated as a navigation/menu input
(`0` and `9` are reserved as above; `1`–`8` select menu options). If a second
digit arrives within the timeout, the system enters `DIRECT_DIAL` mode and all
subsequent digits — including `0` and `9` — are treated as literal phone number
digits. This applies in all states, including `IDLE_DIAL_TONE`.

**DTMF feedback:** When the system enters `DIRECT_DIAL` mode, a DTMF tone is
played for each digit as it is received (including the first two that triggered
the mode switch).

**Inactivity timeout:** If no digit is received for `INACTIVITY_TIMEOUT` while
the handset is lifted and the system is in any menu state, the off-hook warning
tone plays continuously until the user hangs up.

**"Operator." opener:** The `SCRIPT_OPERATOR_OPENER` ("Operator.") is spoken
only once per session — at the first menu prompt after the handset is lifted.
Subsequent menu prompts (including after stopping music) skip the opener.

**State after stopping music:** When the user ends a call (stops Plex playback)
from the playing menu, the system transitions directly to `IDLE_MENU` without
replaying the dial tone or `SCRIPT_OPERATOR_OPENER`.

**Invalid digit handling:** Any digit that has no corresponding option in the
current menu state → TTS plays `SCRIPT_NOT_IN_SERVICE` and re-reads the current
menu options.

**Plex state:** The menu never tracks paused/playing state locally. All playback
state (playing, paused, what's playing) is derived from `now_playing()` →
`PlaybackState` at menu-speak time. This ensures the menu always reflects actual
Plex state regardless of changes made by other clients.

**T9 matching is case-insensitive.** "beatles" and "Beatles" both match digit `1`
(ABC).

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

Direct dial is entered when a second digit is received within
`DIRECT_DIAL_DISAMBIGUATION_TIMEOUT` of the first. All digits including `0` and
`9` are treated as literal. Lookup fires at exactly 7 digits; subsequent digits
are ignored. Hang-up before 7 digits silently abandons the partial number.

---

## User Experience Flow

### Handset lifted — system idle (no music playing)

```
Lift handset
  → Dial tone plays (350 Hz + 440 Hz)
  → [5 second timeout, no input]
  → SCRIPT_OPERATOR_OPENER: "Operator." (spoken once per session)
  → SCRIPT_GREETING: "How may I direct your call?"
  → [brief pause]
  → SCRIPT_EXTENSION_HINT: "If you know your party's extension, please dial it now..."
  → Wait for digit input (disambiguation timeout applies to first digit)

Digit 1 → Browse playlists
Digit 2 → Browse artists
Digit 3 → Browse genres
Digit 4 → Shuffle everything (calls shuffle_all())
```

### Handset lifted — music is playing

```
Lift handset
  → Dial tone plays (350 Hz + 440 Hz)
  → [2 second timeout, no input]
  → Check now_playing() → PlaybackState at speak time:
      If item is None (music ended during dial tone): deliver idle prompt instead
  → SCRIPT_OPERATOR_OPENER: "Operator." (spoken once per session)
  → SCRIPT_PLAYING_GREETING: "Your call with [media name] is currently in progress."
  → Options announced dynamically based on PlaybackState:
      Digit 1 → "pause your call" (if not paused) or "resume your call" (if paused)
      Digit 2 → "skip" (only offered if not on last track)
      Digit 3 → End call (stop music, transition directly to IDLE_MENU)
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

T9 matching is case-insensitive. "beatles" and "Beatles" both index under dial 1.

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
First digit dialed (in any state) →
  System waits up to DIRECT_DIAL_DISAMBIGUATION_TIMEOUT for a second digit
  If no second digit → treat as single navigation/menu input (0=top, 9=back, 1–8=option)
  If second digit arrives within timeout →
    Enter DIRECT_DIAL mode
    Dial tone stops (if playing)
    DTMF tone plays for each digit received (including the first two)
    System accumulates up to 7 digits total
    After 7 digits: look up in phone book
      Found → announce and play
      Not found → SCRIPT_NOT_IN_SERVICE
    8th digit and beyond → ignored
    Hang up before 7 digits → silent cleanup, no lookup
    0 and 9 are treated as literal digits in DIRECT_DIAL mode
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
- Entries: `source`, `severity` (`"warning"` | `"error"`), `message`, `count`, `last_happened`
- Deduplicated by `(source, message)` — repeat occurrences increment `count` and update `last_happened`
- Read-only from phone interface; clearable only via manual intervention outside the system

---

## Configuration Constants

| Constant | Value | Description |
|---|---|---|
| `DIAL_TONE_TIMEOUT_IDLE` | 5 s | Silence before idle operator prompt |
| `DIAL_TONE_TIMEOUT_PLAYING` | 2 s | Silence before playing-state prompt |
| `INTER_DIGIT_TIMEOUT` | 300 ms | Gap after last pulse → digit complete |
| `DIRECT_DIAL_DISAMBIGUATION_TIMEOUT` | TBD | Wait after first digit before treating as single navigation input |
| `INACTIVITY_TIMEOUT` | 30 s | Inactivity in any menu state → off-hook warning tone |
| `DIAL_TONE_FREQUENCIES` | [350, 440] Hz | Standard PSTN dial tone |
| `MAX_MENU_OPTIONS` | 8 | Max items listed before narrowing required |
| `PHONE_NUMBER_LENGTH` | 7 | Digits in an assigned phone number |
| `ASSISTANT_MESSAGE_PAGE_SIZE` | 3 | Messages read aloud per page in assistant |
| `ASSISTANT_NUMBER` | set in constants file | Reserved 7-digit diagnostic number; excluded from phone book assignment |
| `HOOK_DEBOUNCE` | TBD | Hook switch debounce window; requires hardware tuning |
| `PULSE_DEBOUNCE` | TBD | Pulse switch debounce window; requires hardware tuning |
| `CACHE_RETRY_MAX` | TBD | Max repopulation attempts for missing TTS cache files |
| `CACHE_RETRY_BACKOFF` | TBD | Base backoff interval between cache repopulation attempts |

---

## Testing Strategy

All unit tests run without hardware, network, or audio output. The four
interfaces (`AudioInterface`, `TTSInterface`, `PlexClientInterface`,
`ErrorQueueInterface`) are the seams where mocks are injected. GPIO is also
abstracted so the handler can be driven by a mock pin reader in tests.

Integration tests (tagged, skipped by default) cover the real Plex client
against a live server.

See `TEST_SPEC.md` for the full test suite. See `IMPL.md` for concrete class
names, technology choices, database schemas, and development order.
