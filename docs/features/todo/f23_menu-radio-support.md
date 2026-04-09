### F-23 · Menu radio support (RADIO_PLAYING_MENU state + radio direct dial)

**Background**
The menu state machine needs to understand radio: when a user dials a radio station's phone number the system should stop Plex, tune the radio, and enter a `RADIO_PLAYING_MENU` state. When the user lifts the handset while radio is already streaming the same menu is delivered. See CLAUDE.md § "Important behavioral rules" for the full radio spec.

**Changes required**

#### 1. New scripts (add to `src/menu.py` with the other `SCRIPT_*` constants)

```python
SCRIPT_RADIO_CONNECTING = (
    "Thank you for your patience. Tuning in to {name} — {frequency} megahertz. Please stand by."
)
SCRIPT_RADIO_PLAYING_GREETING = "You are currently tuned to {name} on {frequency} megahertz."
SCRIPT_RADIO_PLAYING_MENU = "To disconnect your call, dial three. To reach a new party, dial zero."
```

#### 2. New state in `MenuState` enum

```python
RADIO_PLAYING_MENU = auto()
```

#### 3. `Menu.__init__` — accept `RadioInterface`

Add `radio: RadioInterface` as a required parameter. Store as `self._radio`. Also add:
```python
self._current_radio_name: Optional[str] = None
self._current_radio_freq_hz: Optional[float] = None
```

#### 4. `_check_dial_tone_timeout` — route to radio menu

After the existing Plex check, also check `self._radio.is_playing()`:

```python
if elapsed >= timeout:
    self._audio.stop()
    if playback.item is not None:
        self._deliver_playing_menu(playback, now)
    elif self._radio.is_playing():
        self._deliver_radio_playing_menu(now)
    else:
        self._deliver_idle_menu(now)
```

Also use `DIAL_TONE_TIMEOUT_PLAYING` when radio is active (same short timeout as Plex):
```python
if playback.item is not None or self._radio.is_playing():
    timeout = DIAL_TONE_TIMEOUT_PLAYING
else:
    timeout = DIAL_TONE_TIMEOUT_IDLE
```

#### 5. `_execute_direct_dial` — handle `media_type == "radio"`

After the successful phone-book lookup, branch on `entry["media_type"]`:

```python
if entry["media_type"] == "radio":
    # Stop any active Plex session
    self._plex_client.stop()
    # Stop any existing radio stream
    self._radio.stop()
    # Parse frequency from plex_key "radio:{frequency_hz}"
    freq_hz = float(entry["plex_key"].split("radio:", 1)[1])
    freq_mhz = freq_hz / 1_000_000
    name = entry.get("name", "")
    self._current_radio_name = name
    self._current_radio_freq_hz = freq_hz
    self._tts.speak_and_play(
        SCRIPT_RADIO_CONNECTING.format(name=name, frequency=f"{freq_mhz:.1f}")
    )
    self._radio.play(freq_hz)
    self._state = MenuState.RADIO_PLAYING_MENU
else:
    # Existing path: speak connecting template, start Plex
    digit_words_str = " ".join(_DIGIT_WORDS[d] for d in number)
    name = entry.get("name", number)
    self._tts.speak_and_play(
        SCRIPT_CONNECTING_TEMPLATE.format(digits=digit_words_str, name=name)
    )
    self._plex_client.play(entry["plex_key"])
    self._state = MenuState.PLAYING_MENU
```

Note: `number` is already computed before this branch (the 7-digit string). The digit-words announcement is skipped for radio — `SCRIPT_RADIO_CONNECTING` replaces it.

#### 6. `_dispatch_navigation_digit` — handle `RADIO_PLAYING_MENU` before global 0/9

At the top of `_dispatch_navigation_digit`, before the ASSISTANT check and before the global `digit == 0` / `digit == 9` handlers:

```python
if self._state == MenuState.RADIO_PLAYING_MENU:
    self._handle_radio_playing_menu_digit(digit, now)
    return
```

#### 7. New method `_deliver_radio_playing_menu`

```python
def _deliver_radio_playing_menu(self, now: float) -> None:
    self._state = MenuState.RADIO_PLAYING_MENU
    self._last_activity_time = now

    if not self._opener_spoken:
        self._tts.speak_and_play(SCRIPT_OPERATOR_OPENER)
        self._opener_spoken = True

    name = self._current_radio_name or ""
    freq_hz = self._current_radio_freq_hz or 0.0
    freq_mhz = freq_hz / 1_000_000
    self._tts.speak_and_play(
        SCRIPT_RADIO_PLAYING_GREETING.format(name=name, frequency=f"{freq_mhz:.1f}")
    )
    self._tts.speak_and_play(SCRIPT_RADIO_PLAYING_MENU)
```

#### 8. New method `_handle_radio_playing_menu_digit`

```python
def _handle_radio_playing_menu_digit(self, digit: int, now: float) -> None:
    if digit == 3 or digit == 0:
        self._radio.stop()
        self._deliver_idle_menu(now)
    else:
        self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
```

#### 9. `make_menu` helper in `tests/test_menu.py`

Update to accept an optional `radio` parameter (defaults to a fresh `MockRadio()`):

```python
def make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path, radio=None):
    from src.phone_book import PhoneBook
    from src.radio import MockRadio
    db = str(tmp_path / "phone_book.db")
    phone_book = PhoneBook(db_path=db)
    if radio is None:
        radio = MockRadio()
    return Menu(
        audio=mock_audio,
        tts=mock_tts,
        plex_client=mock_plex,
        plex_store=mock_plex_store,
        phone_book=phone_book,
        error_queue=mock_error_queue,
        radio=radio,
    )
```

All existing tests that call `make_menu()` without `radio` will receive a no-op `MockRadio` and continue to pass.

**Acceptance criteria**
- Dialing a 7-digit number whose phone-book entry has `media_type == "radio"` stops Plex, stops any existing radio, speaks `SCRIPT_RADIO_CONNECTING`, calls `radio.play(freq_hz)`, and leaves state as `RADIO_PLAYING_MENU`.
- Lifting the handset while `radio.is_playing()` → `True` (and Plex is idle) delivers `SCRIPT_RADIO_PLAYING_GREETING` + `SCRIPT_RADIO_PLAYING_MENU` after the short dial-tone timeout.
- In `RADIO_PLAYING_MENU`, digit `3` calls `radio.stop()` and delivers `IDLE_MENU`.
- In `RADIO_PLAYING_MENU`, digit `0` calls `radio.stop()` and delivers `IDLE_MENU`.
- In `RADIO_PLAYING_MENU`, any other digit (e.g. `1`, `9`) speaks `SCRIPT_NOT_IN_SERVICE`.
- `on_handset_on_cradle()` does NOT call `radio.stop()` (radio continues after hang-up).
- All existing `test_menu.py` tests pass unchanged.

**Testable outcome**
New test class `TestRadioMenu` in `tests/test_menu.py` (or standalone tests):

- `test_radio_direct_dial_stops_plex_and_plays_radio` — seed phone book with a radio entry; dial the 7-digit number; assert `mock_plex.stop` called, `mock_radio.play` called with the correct frequency, state is `RADIO_PLAYING_MENU`, TTS spoke text containing `"Tuning in to"`.
- `test_radio_dial_speaks_connecting_template` — dial a radio number; assert `SCRIPT_RADIO_CONNECTING` text (with station name) appeared in `mock_tts.speak_and_play` calls.
- `test_radio_stops_existing_stream_before_new_dial` — set `mock_radio.set_playing(True)`; dial a radio number; assert `mock_radio.calls` contains `('stop',)` before `('play', ...)`.
- `test_radio_playing_menu_on_handset_lift` — set `mock_radio.set_playing(True)`, `mock_plex.set_now_playing(PlaybackState(None, False))`; lift handset; tick past `DIAL_TONE_TIMEOUT_PLAYING`; assert TTS spoke `SCRIPT_RADIO_PLAYING_MENU` text.
- `test_radio_playing_menu_digit_3_stops_radio` — enter `RADIO_PLAYING_MENU`; dial `3`; assert `mock_radio.stop()` called, state is `IDLE_MENU`.
- `test_radio_playing_menu_digit_0_stops_radio` — enter `RADIO_PLAYING_MENU`; dial `0`; assert `mock_radio.stop()` called, state is `IDLE_MENU`.
- `test_radio_playing_menu_invalid_digit` — enter `RADIO_PLAYING_MENU`; dial `1`; assert `SCRIPT_NOT_IN_SERVICE` spoken, state remains `RADIO_PLAYING_MENU` (or transitions to idle — whichever the implementation does, but no radio stop).
- `test_hangup_does_not_stop_radio` — enter `RADIO_PLAYING_MENU`; call `on_handset_on_cradle()`; assert `radio.stop` was NOT called.
- `test_radio_uses_playing_timeout_when_active` — set `mock_radio.set_playing(True)`; lift handset; tick to just before `DIAL_TONE_TIMEOUT_PLAYING`; assert state is still `IDLE_DIAL_TONE`; tick past it; assert state is `RADIO_PLAYING_MENU`.
