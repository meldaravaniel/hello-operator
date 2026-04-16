# Rotary Phone Media Controller — Design Overview

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
              │ media_store │   │  phone_book  │
              │ local cache │   │   (SQLite)   │
              └──────┬──────┘   └─────────────┘
                     │
              ┌──────▼──────────────────────────┐
              │       media_client               │
              │  MediaClientInterface            │
              │  (MPDClient)                     │
              └──────────────────────────────────┘
                     │
              ┌──────▼──────┐   ┌─────────────┐   ┌─────────────┐
              │    audio    │   │     tts      │   │    radio    │
              │  interface  │   │  interface   │   │  interface  │
              └─────────────┘   └─────────────┘   └─────────────┘
```

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
  → Media backend begins playback
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

### Radio direct dial

Radio stations are pre-configured with specific 7-digit phone numbers in `radio_stations.json`. Dialing one of these numbers tunes the RTL-SDR dongle to that station's frequency.

```
7-digit number dialed → phone book lookup → media_type == "radio"
  → Stop any active media playback
  → Stop any active radio stream
  → Speak SCRIPT_RADIO_CONNECTING (contains station name and frequency)
  → radio.play(frequency_hz)
  → State → RADIO_PLAYING_MENU
  → Handset can be hung up; radio continues streaming

Handset lifted while radio is playing:
  → Dial tone plays briefly
  → SCRIPT_RADIO_PLAYING_GREETING (contains station name and frequency)
  → SCRIPT_RADIO_PLAYING_MENU: "To disconnect, dial three. To reach a new party, dial zero."
  → Digit 3 → radio.stop() → IDLE_MENU
  → Digit 0 → radio.stop() → IDLE_MENU (then deliver idle menu)
  → No pause, no skip (radio is live)
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
    → triggers full re-fetch of all categories from media backend
    → updates local store for all successful responses
    → reports back: "All done, I've updated my records." or
      "I'm sorry, I had some trouble reaching the exchange." if backend unreachable
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

**Media backend connection failure at session start:**
- Play vintage "service disconnected" message
- Offer retry loop: "If you'd like me to retry, dial 1. Otherwise, please hang
  up and try again later."
- Retry as many times as user requests; never force session end

**Phone book DB unreadable:**
- Play distinct vintage message implying internal switchboard failure (not a
  connection/line issue)
- Offer same retry loop as media backend connection failure
- Never force session end

**No playable content at top level:**
Triggered when:
- Pre-load at handset lift finds zero playable content across all categories, OR
- User navigates back to top level and all categories are now empty

Response:
- Play vintage "out of service" message
- Brief pause
- Off-hook warning tone, played continuously until user hangs up

**Media client failure mid-browse:**
- Apologize about "service degradation"
- Return to last successfully cached browse state and re-prompt
- If no cached state: return to top level
- If top level also has no content: treat as "no playable content" above

**Error queue:**
- Entries: `source`, `severity` (`"warning"` | `"error"`), `message`, `count`, `last_happened`
- Deduplicated by `(source, message)` — repeat occurrences increment `count` and update `last_happened`
- Read-only from phone interface; clearable only via manual intervention outside the system

---

## Database Schemas

### `phone_book` (SQLite)

```sql
CREATE TABLE phone_book (
    media_key    TEXT PRIMARY KEY,
    media_type   TEXT NOT NULL CHECK(media_type IN ('playlist','artist','album','genre','radio')),
    name         TEXT NOT NULL,
    phone_number TEXT NOT NULL UNIQUE
);
```

Radio station entries use `media_key = "radio:{frequency_hz}"` (e.g. `"radio:90300000.0"`). Pre-seeded at startup via `phone_book.seed()`; phone numbers are user-configured and never auto-generated.

### `media_cache` (SQLite, separate file)

Used by `MediaStore` (`src/media_store.py`):

```sql
CREATE TABLE media_cache (
    cache_key  TEXT PRIMARY KEY,  -- e.g. "playlists", "albums:media_key"
    data       TEXT NOT NULL,     -- JSON list of MediaItems (field: "media_key")
    updated_at TEXT NOT NULL      -- ISO8601 timestamp of last successful sync
);
```

### `error_queue` (SQLite, separate file)

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

## DTMF Frequencies

Standard frequency pairs used by `SounddeviceAudio.play_dtmf`:

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
