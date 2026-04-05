# Rotary Phone Media Controller — Test Specification

## Overview

A Raspberry Pi 4 controls a rotary phone. Picking up the handset triggers an
interactive voice menu that allows the user to browse and play media from a Plex
server. Audio plays through an Adafruit MAX98357A I2S amplifier.

---

## Hardware Assumptions

| Component | GPIO behavior |
|---|---|
| Hook switch | HIGH = on cradle (idle), LOW = handset lifted |
| Pulse switch (dial) | HIGH = resting, LOW = each pulse |
| Audio | I2S via MAX98357A |

---

## Technology Stack

- **Language:** Python 3
- **Target hardware:** Raspberry Pi 4 (2GB)
- **Audio playback:** `sounddevice` + `numpy` (handles both programmatic tones and file playback)
- **Dial tone generation:** Programmatic 350 Hz + 440 Hz sine wave mix via numpy
- **TTS:** Piper (offline); fixed menu prompts pre-rendered to audio files at install/startup; dynamic strings (media names, phone numbers) synthesized at runtime
- **Plex API:** Behind a mock interface for all tests
- **Phone number DB:** Auto-generated 7-digit numbers, persisted in SQLite

---

## Interfaces

All hardware-dependent and external-service modules are defined as abstract base
classes. Concrete implementations and mocks both satisfy the same interface,
keeping all higher-level logic decoupled from dependencies.

---

### `AudioInterface`

```python
from abc import ABC, abstractmethod

class AudioInterface(ABC):
    @abstractmethod
    def play_tone(self, frequencies: list[float], duration_ms: int) -> None: ...
    @abstractmethod
    def play_file(self, path: str) -> None: ...
    @abstractmethod
    def play_dtmf(self, digit: int) -> None: ...
    """Play the standard DTMF tone for digit 0–9."""
    @abstractmethod
    def play_off_hook_tone(self) -> None: ...
    """Play the off-hook warning tone continuously until stop() is called."""
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def is_playing(self) -> bool: ...
```

**Implementations:**
- `SounddeviceAudio(AudioInterface)` — real implementation using `sounddevice` + `numpy`
- `MockAudio(AudioInterface)` — records all calls; used in all unit tests

---

### `TTSInterface`

```python
from abc import ABC, abstractmethod

class TTSInterface(ABC):
    @abstractmethod
    def speak(self, text: str) -> str:
        """Synthesize text to a temp audio file; return the file path."""
        ...
    @abstractmethod
    def speak_and_play(self, text: str) -> None:
        """Synthesize and play immediately via the injected AudioInterface."""
        ...
    @abstractmethod
    def speak_digits(self, digits: str) -> None:
        """Speak each digit individually (e.g. '555' → 'five five five')."""
        ...
```

**Implementations:**
- `PiperTTS(TTSInterface)` — real implementation wrapping the Piper binary
- `MockTTS(TTSInterface)` — records all calls; returns canned file paths

**Pre-rendering:** At startup, `PiperTTS` pre-renders all fixed menu prompt
strings to audio files in a cache directory. `speak_and_play` for fixed strings
uses `AudioInterface.play_file` on the cached file rather than invoking Piper.

---

### `PlexClientInterface`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

class MediaType(str, Enum):
    PLAYLIST = "playlist"
    ARTIST   = "artist"
    ALBUM    = "album"
    GENRE    = "genre"

@dataclass
class MediaItem:
    plex_key: str
    name: str
    media_type: MediaType

@dataclass
class PlaybackState:
    item: MediaItem | None  # None if nothing is playing
    is_paused: bool         # True if paused; always False when item is None

class PlexClientInterface(ABC):
    @abstractmethod
    def get_playlists(self) -> list[MediaItem]: ...
    @abstractmethod
    def get_artists(self) -> list[MediaItem]: ...
    @abstractmethod
    def get_genres(self) -> list[MediaItem]: ...
    @abstractmethod
    def get_albums_for_artist(self, artist_key: str) -> list[MediaItem]: ...
    @abstractmethod
    def play(self, plex_key: str) -> None: ...
    @abstractmethod
    def shuffle_all(self) -> None: ...
    @abstractmethod
    def pause(self) -> None: ...
    @abstractmethod
    def unpause(self) -> None: ...
    @abstractmethod
    def skip(self) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def now_playing(self) -> PlaybackState: ...
    @abstractmethod
    def get_queue_position(self) -> tuple[int, int]: ...  # (current, total)
```

**Implementations:**
- `PlexClient(PlexClientInterface)` — real implementation using the Plex HTTP API
- `MockPlexClient(PlexClientInterface)` — configurable returns; records all calls

---

### `ErrorQueueInterface`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ErrorEntry:
    source: str
    severity: str       # "warning" | "error"
    message: str
    count: int
    last_happened: str  # ISO8601

class ErrorQueueInterface(ABC):
    @abstractmethod
    def log(self, source: str, severity: str, message: str) -> None:
        """Add or update entry; deduplicated by (source, message)."""
        ...
    @abstractmethod
    def get_all(self) -> list[ErrorEntry]: ...
    @abstractmethod
    def get_by_severity(self, severity: str) -> list[ErrorEntry]: ...
```

**Implementations:**
- `SqliteErrorQueue(ErrorQueueInterface)` — persisted to disk; owned by `main.py`
- `MockErrorQueue(ErrorQueueInterface)` — records all calls; used in all unit tests

---

## Module Breakdown & Test Suites

---

### 1. `gpio_handler` — Hardware Input

Abstracts GPIO reads. All other modules receive events, not raw GPIO.

#### 1.1 Hook switch
- `test_hook_lifted`: GPIO LOW → emits `HANDSET_LIFTED` event
- `test_hook_on_cradle`: GPIO HIGH → emits `HANDSET_ON_CRADLE` event
- `test_hook_debounce`: rapid HIGH/LOW transitions within debounce window → only
  one event emitted
- `test_hook_no_event_when_state_unchanged`: repeated reads of same state → no
  duplicate events

#### 1.2 Pulse switch / dial decoder
- `test_single_digit_1`: one pulse in a pulse burst → decoded digit `1`
- `test_single_digit_5`: five pulses in a burst → decoded digit `5`
- `test_single_digit_0`: ten pulses in a burst → decoded digit `0`
- `test_pulse_burst_timeout`: pulses stop; after inter-digit timeout → emits
  `DIGIT_DIALED` event with decoded digit
- `test_multiple_digits_sequence`: two bursts separated by timeout → two
  `DIGIT_DIALED` events in order
- `test_pulse_debounce`: noise pulses shorter than minimum pulse width → ignored
- `test_dial_ignored_when_hook_on_cradle`: pulses while handset on cradle → no
  events emitted

---

### 2. `audio` — Audio Output

Tests for the `SounddeviceAudio` concrete implementation. All higher-level
module tests use `MockAudio` instead.

#### 2.1 Dial tone
- `test_dial_tone_frequencies`: generated waveform contains 350 Hz and 440 Hz
  components (FFT check)
- `test_dial_tone_stops_after_duration`: tone auto-stops after specified duration
- `test_dial_tone_stop_called_early`: `stop()` before duration ends → tone stops
  immediately

#### 2.2 Off-hook warning tone
- `test_off_hook_tone_plays_continuously`: `play_off_hook_tone()` → tone plays
  in a loop without stopping on its own
- `test_off_hook_tone_stops_on_stop_call`: `stop()` while off-hook tone playing
  → tone stops immediately

#### 2.3 DTMF tones
- `test_dtmf_digit_frequencies`: `play_dtmf(n)` → generated waveform contains
  the correct row and column frequencies for that digit (FFT check; e.g. digit 1
  → 697 Hz + 1209 Hz)
- `test_dtmf_all_digits`: all digits 0–9 produce distinct frequency pairs
- `test_dtmf_stops_after_short_duration`: DTMF tone is brief (not continuous)

#### 2.4 File playback
- `test_play_file_called_with_correct_path`: given a path, backend receives that
  path
- `test_stop_interrupts_playback`: `stop()` while playing → `is_playing()`
  returns False
- `test_play_file_interrupts_current_playback`: `play_file()` called while
  already playing → current audio stops, new file plays

---

### 3. `tts` — Text-to-Speech

Tests for the `PiperTTS` concrete implementation and pre-rendering logic. All
higher-level module tests use `MockTTS` instead.

- `test_speak_returns_audio_path`: `speak("hello")` → returns path to a non-empty
  audio file
- `test_speak_and_play_calls_audio_interface`: `speak_and_play("hello")` →
  `AudioInterface.play_file` called with a valid path
- `test_speak_digits_individual`: `speak_digits("5551234")` → audio contains
  each digit spoken separately (e.g. "five five five one two three four")
- `test_prerender_creates_files`: `prerender(prompts_dict)` → one audio file
  created per prompt, all non-empty
- `test_prerender_stores_hash`: after prerender, a hash of each script's text is
  stored alongside its audio file
- `test_prerender_skips_unchanged_scripts`: `prerender` called twice with same
  text → Piper invoked only on first call; second call skips synthesis
- `test_prerender_rerenders_on_text_change`: `prerender` called with updated text
  for a script → Piper re-invoked, new audio file written, hash updated
- `test_prerender_rerenders_on_missing_file`: hash stored but WAV file deleted →
  `prerender` re-synthesizes the missing file
- `test_prerender_cache_persists_across_instantiation`: cache written, `PiperTTS`
  re-created → cached files still present and usable without re-synthesis
- `test_speak_and_play_uses_cache_for_prerendered`: after prerender, `speak_and_play`
  with a known prompt → uses cached file, Piper binary NOT invoked again
- `test_cache_miss_falls_back_to_live`: cached file deleted after prerender →
  `speak_and_play` falls back to live Piper synthesis without error
- `test_cache_miss_logs_warning`: cache miss → warning logged
- `test_cache_miss_attempts_repopulate`: cache miss → system attempts to
  recreate the file
- `test_cache_repopulate_retries_with_backoff`: repopulation fails → retried
  with backoff up to `CACHE_RETRY_MAX` attempts, then stops
- `test_cache_repopulate_exhausted_logs_error`: retries exhausted → persistent
  error logged to error queue, live synthesis continues
- `test_piper_failure_logs_error`: Piper binary non-functional → error logged
  to error queue
- `test_piper_failure_plays_off_hook_tone`: Piper binary non-functional →
  off-hook warning tone plays continuously until user hangs up

---

### 4. `phone_book` — Phone Number Registry

Auto-generates and persists 7-digit phone numbers mapped to Plex media items.

#### Data model
```
{ plex_key: str, media_type: str, name: str, phone_number: str }
```

- `test_assign_new_number`: new Plex key → `PHONE_NUMBER_LENGTH`-digit number
  assigned and stored
- `test_number_format`: assigned number matches `r'^\d{PHONE_NUMBER_LENGTH}$'`
- `test_number_is_unique`: assigning numbers to 100 items → all numbers distinct
- `test_lookup_by_plex_key`: stored item retrieved by Plex key
- `test_lookup_by_phone_number`: stored item retrieved by 7-digit number
- `test_lookup_missing_key`: unknown Plex key → returns `None`
- `test_persistence`: write item, reload DB from disk → item still present
- `test_no_reassignment`: assigning number to already-known Plex key → same
  number returned, no new entry created
- `test_lazy_assignment_on_first_encounter`: number assigned on first call to
  `assign_or_get(plex_key)`; same number returned on all subsequent calls
- `test_assistant_number_excluded`: generated numbers never equal `ASSISTANT_NUMBER`
- `test_db_unreadable_raises`: corrupt or missing DB file at init → raises a
  distinct error (not a generic connection error)

---

### 5. `error_queue` — Persistent Error Log

Tests for the `SqliteErrorQueue` concrete implementation.

- `test_log_new_entry`: `log(source, severity, message)` → entry stored with `count=1` and `last_happened` set
- `test_log_deduplicates_by_source_and_message`: same `(source, message)` logged twice → single entry with `count=2` and updated `last_happened`
- `test_log_different_source_creates_new_entry`: same message from different source → two separate entries
- `test_get_all_returns_all_entries`: multiple entries → `get_all()` returns all, newest first
- `test_get_by_severity_filters_correctly`: mix of warnings and errors → `get_by_severity("warning")` returns only warnings
- `test_persistence_across_instantiation`: entries written, queue re-created from same DB → entries still present
- `test_severity_values_enforced`: invalid severity value → raises error

---

### 7. `plex_store` — Local Plex Cache

Persistent, session-independent store. All browse data flows through here.
The menu never calls `plex_client` directly for browse data.

#### 5.1 Initialization
- `test_store_empty_on_first_run`: fresh DB → all category flags False, all
  lists empty
- `test_store_fetches_from_plex_when_empty`: `get_playlists()` called on empty
  store → fetches from `plex_client`, populates store, returns list
- `test_store_uses_local_data_when_populated`: store already has playlists →
  `get_playlists()` returns local data without calling `plex_client`
- `test_store_persists_across_instantiation`: data written, store re-created
  from same DB → data still present

#### 5.2 Update strategy
- `test_store_updates_on_successful_different_response`: Plex returns different
  list than local → local store updated
- `test_store_no_update_on_same_response`: Plex returns identical list → no
  write to DB
- `test_store_no_update_on_plex_error`: Plex raises exception → local store
  unchanged
- `test_store_hasContent_true_when_list_nonempty`: category list populated →
  `has_content` flag is True
- `test_store_hasContent_false_when_list_empty`: category list empty →
  `has_content` flag is False

#### 5.3 Stale data / playback failure
- `test_store_removes_item_on_playback_not_found`: Plex returns "not found"
  during play → item removed from local store
- `test_store_updates_hasContent_after_removal`: last item in category removed
  → `has_content` flag updated to False

#### 5.4 Albums per artist
- `test_store_fetches_albums_on_first_access`: no cached albums for artist →
  fetches from Plex, stores under artist key
- `test_store_uses_cached_albums`: albums already cached for artist → returns
  without calling Plex
- `test_store_updates_albums_on_successful_response`: Plex returns different
  album list → cache updated

#### 5.5 Manual refresh
- `test_store_refresh_fetches_all_categories`: `refresh()` called → fetches
  playlists, artists, genres, and all cached album lists from Plex
- `test_store_refresh_updates_on_success`: successful refresh → local data
  replaced with Plex response
- `test_store_refresh_skips_failed_categories`: one category call fails during
  refresh → that category unchanged, others updated normally
- `test_store_refresh_returns_summary`: `refresh()` → returns dict of which
  categories succeeded and which failed

---

### 8. `plex_client` — Plex API

All production calls go through `PlexClientInterface`. Unit tests use
`MockPlexClient`; integration tests use the real `PlexClient`.

#### 6.1 Mock behavior
- `test_mock_get_playlists_returns_list`: mock returns configured list
- `test_mock_get_artists_returns_list`: mock returns configured list
- `test_mock_play_records_call`: `play(key)` → mock records the key played
- `test_mock_shuffle_all_records_call`: `shuffle_all()` → recorded
- `test_mock_pause_records_call`: `pause()` → recorded
- `test_mock_unpause_records_call`: `unpause()` → recorded
- `test_mock_now_playing_returns_playing_state`: returns configured `PlaybackState` with item and `is_paused=False`
- `test_mock_now_playing_returns_paused_state`: returns configured `PlaybackState` with item and `is_paused=True`
- `test_mock_now_playing_returns_idle_state`: returns `PlaybackState(item=None, is_paused=False)` when nothing playing
- `test_mock_get_queue_position_returns_tuple`: returns configured (current, total)

#### 6.2 Real client (integration, skipped in unit test runs)
- `test_real_get_playlists_returns_list`: hits live server, returns non-empty list
- `test_real_play_starts_playback`: plays a known item, `now_playing()` returns it

---

### 9. `menu` — Menu State Machine

The core logic. Receives digit events and system state; emits audio instructions
and Plex commands.

#### 7.1 Reserved digits and disambiguation
- `test_digit_0_single_goes_to_top_level`: `0` dialed alone (no second digit within `DIRECT_DIAL_DISAMBIGUATION_TIMEOUT`) → state resets to top-level menu
- `test_digit_9_single_goes_back_one_level`: `9` dialed alone → state moves up one level
- `test_digit_9_at_top_level`: `9` at top level → no crash, stays at top level
- `test_disambiguation_timeout_single_digit_is_navigation`: first digit received, no second digit within timeout → treated as navigation/menu input
- `test_disambiguation_second_digit_enters_direct_dial`: second digit received within timeout → `DIRECT_DIAL` mode entered; `0` and `9` treated as literal digits
- `test_disambiguation_0_and_9_literal_in_direct_dial`: after mode switch, `0` and `9` are accumulated as phone number digits, not navigation
- `test_dtmf_plays_for_each_direct_dial_digit`: in `DIRECT_DIAL` mode → `audio.play_dtmf` called for each digit received (including first two that triggered mode switch)

#### 7.2 Idle state top-level menu
- `test_idle_menu_announces_options`: after dial tone timeout with no input →
  TTS plays `SCRIPT_OPERATOR_OPENER` then `SCRIPT_GREETING`
- `test_operator_opener_spoken_once_per_session`: `SCRIPT_OPERATOR_OPENER` is
  played on first prompt only; subsequent menu prompts in same session do not
  replay it
- `test_idle_menu_after_stop_skips_dial_tone`: after user stops music (digit 3
  from playing menu) → state goes directly to `IDLE_MENU` without dial tone;
  `SCRIPT_OPERATOR_OPENER` not replayed
- `test_idle_menu_secondary_prompt`: after brief pause → TTS plays
  `SCRIPT_EXTENSION_HINT`
- `test_idle_menu_plays_options`: available categories announced → TTS plays
  `SCRIPT_IDLE_MENU`
- `test_idle_menu_option_1_playlist`: digit `1` → TTS plays
  `SCRIPT_BROWSE_PROMPT_PLAYLIST`, enters playlist browse state
- `test_idle_menu_option_2_artist`: digit `2` → TTS plays
  `SCRIPT_BROWSE_PROMPT_ARTIST`, enters artist browse state
- `test_idle_menu_option_3_genre`: digit `3` → TTS plays
  `SCRIPT_BROWSE_PROMPT_GENRE`, enters genre browse state
- `test_idle_menu_option_4_shuffle`: digit `4` → calls `plex_client.shuffle_all()`
- `test_idle_menu_omits_empty_category`: `plex_store.has_content` False for a
  category → not announced as an option, no Plex API call made
- `test_idle_menu_uses_local_store_when_populated`: store already initialized →
  top-level menu built without any Plex API call
- `test_idle_menu_initializes_store_when_empty`: store not yet populated →
  fetches from Plex to initialize, then builds menu
- `test_idle_menu_missed_call_indicator`: error queue non-empty → top-level
  menu includes `SCRIPT_MISSED_CALL`
- `test_idle_menu_no_missed_call_when_queue_empty`: error queue empty → no
  `SCRIPT_MISSED_CALL` played
- `test_idle_menu_invalid_digit`: digit with no corresponding option →
  TTS plays `SCRIPT_NOT_IN_SERVICE` and re-reads menu
- `test_idle_menu_plex_failure_at_load`: Plex unreachable at handset lift →
  TTS plays `SCRIPT_PLEX_FAILURE` then `SCRIPT_RETRY_PROMPT`
- `test_idle_menu_plex_failure_retry_loop`: digit `1` after failure message →
  retry attempted; failure message and retry prompt repeat if still failing
- `test_idle_menu_plex_failure_no_forced_hangup`: Plex failure never ends
  session; user remains in retry loop until they hang up
- `test_idle_menu_db_unreadable`: phone book DB unreadable at startup →
  TTS plays `SCRIPT_DB_FAILURE` then `SCRIPT_RETRY_PROMPT`
- `test_idle_menu_db_unreadable_retry_loop`: digit `1` after DB failure →
  retry attempted; stays in loop if still unreadable
- `test_idle_menu_no_content_plays_off_hook_tone`: pre-load finds zero playable
  content → TTS plays `SCRIPT_NO_CONTENT`, brief pause, then continuous
  off-hook tone until user hangs up
- `test_idle_menu_no_content_after_navigation`: user returns to top level and
  all categories now empty → same out-of-service + off-hook tone behavior
- `test_terminal_fallback_plays_script`: system reaches unrecoverable dead-end
  → TTS plays `SCRIPT_TERMINAL_FALLBACK`, brief pause, then continuous
  off-hook tone until user hangs up
- `test_off_hook_tone_stops_on_hangup`: off-hook tone playing → user hangs up
  → tone stops immediately
- `test_inactivity_timeout_triggers_off_hook_tone`: no digit received for
  `INACTIVITY_TIMEOUT` while in any menu state → off-hook warning tone plays
  continuously until user hangs up
- `test_inactivity_timeout_reset_on_digit`: digit received before timeout →
  inactivity timer resets

#### 7.3 Playing state top-level menu
- `test_playing_menu_announces_options`: handset lifted while playing →
  TTS plays `SCRIPT_OPERATOR_OPENER` then `SCRIPT_PLAYING_GREETING` (with media name)
- `test_playing_menu_option_1_pause`: digit `1` when `PlaybackState.is_paused=False`
  → calls `plex_client.pause()`
- `test_playing_menu_option_1_unpause`: digit `1` when `PlaybackState.is_paused=True`
  → calls `plex_client.unpause()`
- `test_playing_menu_pause_label_when_playing`: `PlaybackState.is_paused=False`
  → TTS plays `SCRIPT_PLAYING_MENU_DEFAULT`
- `test_playing_menu_unpause_label_when_paused`: `PlaybackState.is_paused=True`
  → TTS plays `SCRIPT_PLAYING_MENU_ON_HOLD`
- `test_playing_menu_option_2_skip`: digit `2` → calls `plex_client.skip()`
- `test_playing_menu_skip_not_offered_on_last_track`: `get_queue_position()`
  returns (n, n) → TTS plays `SCRIPT_PLAYING_MENU_LAST_TRACK` or
  `SCRIPT_PLAYING_MENU_ON_HOLD_LAST_TRACK`; digit `2` treated as invalid
- `test_playing_menu_option_3_end_call`: digit `3` → calls `plex_client.stop()`,
  transitions directly to `IDLE_MENU` (no dial tone)
- `test_playing_menu_option_0_go_to_idle_menu`: digit `0` → transitions to idle
  top-level menu
- `test_playing_menu_now_playing_idle_at_speak_time`: `now_playing()` returns
  `PlaybackState(item=None, is_paused=False)` when menu is about to speak →
  idle prompt delivered instead of playing prompt
- `test_playing_menu_uses_playback_state_not_local_state`: mock `now_playing()`
  returns paused state that contradicts what the system last commanded → menu
  reflects Plex state, not local assumption

#### 7.4 T9-style browsing (shared by playlist, artist, genre, album)
- `test_browse_t9_digit_1_maps_to_ABC`: digit `1` → filters items starting with
  A, B, or C
- `test_browse_t9_digit_mapping`: digits 1–8 map to correct letter groups
  (1=ABC, 2=DEF, 3=GHI, 4=JKL, 5=MNO, 6=PQR, 7=STU, 8=VWX/YZ + special chars)
- `test_browse_t9_number_literal_match`: digit `3` → also matches items whose
  name starts with the character "3" (e.g. "30 Seconds to Mars")
- `test_browse_t9_special_chars_under_8`: item starting with "!" → matched by
  digit `8`
- `test_browse_article_stripping_the`: "The Beatles" indexed as "Beatles" →
  found under digit `1` (ABC)
- `test_browse_article_stripping_a`: "A Tribe Called Quest" indexed as "Tribe"
  → found under digit `7` (STU)
- `test_browse_article_stripping_an`: "An Artist" indexed as "Artist" → found
  under digit `1` (ABC)
- `test_browse_article_full_name_spoken`: stripped item selected → TTS speaks
  full original name, not stripped version
- `test_browse_t9_case_insensitive`: item with lowercase name (e.g. "beatles")
  matches the same digit as uppercase equivalent ("Beatles") → found under digit `1`
- `test_browse_exactly_8_results_listed`: exactly 8 matching items → TTS plays
  `SCRIPT_BROWSE_LIST_INTRO` (with count), no further narrowing prompted
- `test_browse_8_or_fewer_results_listed`: <8 matching items → TTS plays
  `SCRIPT_BROWSE_LIST_INTRO` (with count) followed by each option
- `test_browse_more_than_8_prompts_next_letter`: >8 results → TTS plays
  `SCRIPT_BROWSE_PROMPT_NEXT_LETTER`
- `test_browse_narrow_until_8_or_fewer`: multi-digit prefix filtering → stops
  prompting when ≤8 remain
- `test_browse_no_upper_limit_on_narrowing`: narrowing continues indefinitely
  until ≤8 results; no artificial depth limit
- `test_browse_single_result_auto_selects`: exactly 1 result → TTS plays
  `SCRIPT_BROWSE_AUTO_SELECT` (with name), auto-selected without digit input
- `test_browse_no_results_says_no_match`: 0 results → TTS plays
  `SCRIPT_NOT_IN_SERVICE`, returns to previous level
- `test_browse_excludes_items_with_no_content`: items with no playable content
  never appear in browse results
- `test_browse_uses_local_store`: browse data served from `plex_store` without
  calling `plex_client` when store is populated
- `test_browse_plex_failure_mid_browse`: Plex API raises exception mid-browse →
  `plex_store` unchanged, TTS plays `SCRIPT_SERVICE_DEGRADATION`, re-prompts
  from last cached state
- `test_browse_plex_failure_no_cache`: Plex API fails and store is empty →
  returns to top-level menu
- `test_browse_playback_not_found_removes_from_store`: play called, Plex returns
  not-found → item removed from `plex_store`, TTS plays `SCRIPT_NOT_IN_SERVICE`
- `test_browse_playback_not_found_updates_has_content`: last item in category
  removed after not-found → `has_content` flag updated to False in store
- `test_browse_invalid_digit`: digit with no corresponding option → TTS plays
  `SCRIPT_NOT_IN_SERVICE` and re-reads current options

#### 7.5 Artist submenu
- `test_artist_submenu_option_1_shuffle_artist`: after artist selected, digit `1`
  → TTS plays `SCRIPT_ARTIST_SUBMENU` (with artist name) and plays entire artist shuffled
- `test_artist_submenu_option_2_choose_album`: digit `2` → TTS plays
  `SCRIPT_BROWSE_PROMPT_ALBUM`, enters T9 album browsing for that artist
- `test_artist_submenu_album_option_omitted_when_no_albums`: artist has no albums
  → "dial 2 for an album" not announced; digit `2` treated as invalid
- `test_artist_submenu_single_album`: artist has exactly 1 album → submenu still
  offered; digit `2` → TTS plays `SCRIPT_ARTIST_SINGLE_ALBUM` (with album name)
- `test_artist_album_t9_browsing`: album browsing uses same T9 narrowing as
  other browse modes
- `test_artist_album_selection_plays_album`: digit selects album → calls
  `plex_client.play(album_key)`

#### 7.6 Diagnostic assistant
- `test_assistant_number_routes_to_assistant`: direct dial of `ASSISTANT_NUMBER`
  → enters `ASSISTANT` state, TTS plays `SCRIPT_ASSISTANT_GREETING`
- `test_assistant_no_errors_says_all_clear`: error queue empty → TTS plays
  `SCRIPT_ASSISTANT_ALL_CLEAR` then `SCRIPT_ASSISTANT_VALEDICTION_CLEAR`,
  then redirects to idle or playing menu
- `test_assistant_no_errors_redirects_not_hangs_up`: after all-clear, session
  continues — user is redirected to appropriate menu, not disconnected
- `test_assistant_errors_offers_options_by_type`: error queue has warnings and
  errors → TTS plays `SCRIPT_ASSISTANT_STATUS_INTRO` then
  `SCRIPT_ASSISTANT_MESSAGE_OPTIONS` with two options
- `test_assistant_errors_only_one_option`: error queue has only errors → one
  option announced
- `test_assistant_always_offers_return_to_menu`: return-to-menu option always
  present alongside message options
- `test_assistant_message_option_states_count`: message type selected → TTS
  plays `SCRIPT_ASSISTANT_READING_INTRO` (with count and `ASSISTANT_MESSAGE_PAGE_SIZE`)
- `test_assistant_reads_first_page_then_asks`: more than `ASSISTANT_MESSAGE_PAGE_SIZE`
  messages of selected type → first `ASSISTANT_MESSAGE_PAGE_SIZE` read, then
  TTS plays `SCRIPT_ASSISTANT_CONTINUE_PROMPT`
- `test_assistant_end_of_messages`: no more messages → TTS plays
  `SCRIPT_ASSISTANT_END_OF_MESSAGES`
- `test_assistant_continue_reads_next_page`: user dials to continue → next
  `ASSISTANT_MESSAGE_PAGE_SIZE` messages read
- `test_assistant_always_offers_navigation`: after reading messages, TTS plays
  `SCRIPT_ASSISTANT_NAVIGATION`
- `test_assistant_hangup_language_redirects`: TTS plays
  `SCRIPT_ASSISTANT_VALEDICTION_MESSAGES` → actual result is redirect to idle
  or playing menu, not session end
- `test_assistant_redirects_to_playing_when_music_active`: music playing when
  assistant called → redirect goes to playing menu, not idle menu
- `test_assistant_hangup_stops_readout`: physical hang up during message readout
  → audio stops immediately, session cleans up
- `test_assistant_messages_not_marked_read`: messages heard → error queue
  unchanged after session ends
- `test_assistant_refresh_option_always_offered`: refresh option always included
  in assistant menu → TTS plays `SCRIPT_ASSISTANT_REFRESH_PROMPT`
- `test_assistant_refresh_calls_plex_store_refresh`: user selects refresh →
  `plex_store.refresh()` called
- `test_assistant_refresh_success_message`: `plex_store.refresh()` succeeds →
  TTS plays `SCRIPT_ASSISTANT_REFRESH_SUCCESS`
- `test_assistant_refresh_failure_message`: `plex_store.refresh()` fails →
  TTS plays `SCRIPT_ASSISTANT_REFRESH_FAILURE`
- `test_assistant_refresh_offers_return_to_menu`: after refresh (success or
  failure) → TTS plays `SCRIPT_ASSISTANT_NAVIGATION`

#### 7.7 Final selection announcement
- `test_final_selection_speaks_connecting`: on selection → TTS plays
  `SCRIPT_CONNECTING` (with digits and media name)
- `test_final_selection_phone_number_spoken_digit_by_digit`: a
  `PHONE_NUMBER_LENGTH`-digit number spoken as individual digit words
  (e.g. "5551234" → "five five five one two three four")
- `test_final_selection_starts_playback`: after announcement → `plex_client.play`
  called with correct key

---

### 10. `session` — Session Lifecycle

Ties hardware events to the menu state machine.

- `test_handset_lifted_starts_dial_tone`: `HANDSET_LIFTED` event → dial tone
  begins
- `test_dial_tone_timeout_idle`: no digit dialed within timeout (idle state) →
  dial tone stops, idle menu prompt begins
- `test_dial_tone_timeout_playing`: no digit dialed within timeout (playing
  state) → shorter timeout, playing menu prompt begins
- `test_direct_dial_during_dial_tone`: two digits dialed within
  `DIRECT_DIAL_DISAMBIGUATION_TIMEOUT` during dial tone → dial tone stops,
  both digits routed to direct-dial handler, DTMF tones played
- `test_single_digit_during_dial_tone_treated_as_navigation`: one digit dialed
  during dial tone, no second digit within timeout → treated as menu input,
  dial tone stops, appropriate menu state entered
- `test_direct_dial_known_number`: 7-digit number matches phone book entry →
  plays that media
- `test_direct_dial_unknown_number`: 7-digit number not in phone book → TTS plays
  `SCRIPT_NOT_IN_SERVICE`
- `test_direct_dial_ignores_digits_after_7`: digit dialed after
  `PHONE_NUMBER_LENGTH` reached → ignored, no second lookup triggered
- `test_direct_dial_hangup_before_7_digits`: hang up before `PHONE_NUMBER_LENGTH`
  digits dialed → silent cleanup, no lookup attempted
- `test_handset_on_cradle_stops_audio`: `HANDSET_ON_CRADLE` → all audio stops
  immediately (even mid-TTS), session cleaned up
- `test_handset_on_cradle_does_not_stop_plex`: `HANDSET_ON_CRADLE` while music
  playing → `plex_client.stop()` NOT called, music continues
- `test_digit_after_hangup_ignored`: digit event after `HANDSET_ON_CRADLE` →
  ignored, no state change

---

## Test Infrastructure

### Fixtures / shared mocks
- `mock_gpio` — injectable GPIO pin reader; controllable in tests
- `mock_audio` — records all `play_tone`, `play_file`, `play_dtmf`, `stop` calls
- `mock_tts` — records all `speak` calls; returns canned audio paths
- `mock_plex` — configurable `PlaybackState` returns; records all playback commands including `shuffle_all`
- `mock_plex_store` — configurable `has_content` flags and list returns;
  records all calls; used by menu and session tests
- `mock_error_queue` — records all `log` calls; returns configurable entry lists
- `tmp_phone_book` — temporary DB file, cleaned up after each test
- `tmp_plex_store` — temporary plex store DB file, cleaned up after each test
- `tmp_error_queue` — temporary error queue DB file, cleaned up after each test

### What is NOT tested here
- Physical GPIO wiring correctness
- I2S audio hardware driver behavior
- Actual Plex server responses (covered by integration tests, skipped by default)
- TTS audio quality

---

## Configuration Constants

| Constant | Value | Notes |
|---|---|---|
| `DIAL_TONE_TIMEOUT_IDLE` | 5 seconds | Time before idle operator prompt |
| `DIAL_TONE_TIMEOUT_PLAYING` | 2 seconds | Time before playing-state prompt |
| `INTER_DIGIT_TIMEOUT` | 300 ms | Time after last pulse before digit is decoded |
| `DIRECT_DIAL_DISAMBIGUATION_TIMEOUT` | TBD | Wait after first digit before treating as single navigation input |
| `INACTIVITY_TIMEOUT` | 30 seconds | Inactivity in any menu state → off-hook warning tone |
| `DIAL_TONE_FREQUENCIES` | 350 Hz + 440 Hz | Standard PSTN dial tone |
| `MAX_MENU_OPTIONS` | 8 | Max items listed before narrowing required |
| `PHONE_NUMBER_LENGTH` | 7 | Digits in an assigned phone number |
| `ASSISTANT_MESSAGE_PAGE_SIZE` | 3 | Messages read aloud per page in assistant |
| `ASSISTANT_NUMBER` | set in constants file | Reserved 7-digit diagnostic number; excluded from phone book |
| `HOOK_DEBOUNCE` | TBD | Hook switch debounce window; requires hardware tuning |
| `PULSE_DEBOUNCE` | TBD | Pulse switch debounce window; requires hardware tuning |
| `CACHE_RETRY_MAX` | TBD | Max repopulation attempts for missing TTS cache files |
| `CACHE_RETRY_BACKOFF` | TBD | Base backoff interval between repopulation attempts |
