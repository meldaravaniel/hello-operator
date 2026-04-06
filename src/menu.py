"""Menu state machine for hello-operator.

Receives digit events and system state; emits audio instructions and Plex
commands.  Has no knowledge of GPIO, audio hardware, or HTTP — only the
interfaces.

States
------
IDLE_DIAL_TONE   — handset lifted, playing dial tone, waiting
IDLE_MENU        — browsing from idle (no music playing)
PLAYING_MENU     — browsing while music is active
BROWSE_PLAYLISTS / BROWSE_ARTISTS / BROWSE_GENRES / BROWSE_ALBUMS — T9 narrowing
ARTIST_SUBMENU   — shuffle artist or pick album
DIRECT_DIAL      — accumulating digits for a direct phone number
ASSISTANT        — diagnostic status readout
OFF_HOOK         — terminal state; off-hook warning tone playing

Reserved digits (all states except DIRECT_DIAL):
    0 → return to top-level menu
    9 → go back one level (or stay at top)
"""

import time
from enum import Enum, auto
from typing import Optional, List

from src.interfaces import (
    AudioInterface, TTSInterface, PlexClientInterface, ErrorQueueInterface,
    MediaItem, PlaybackState,
)
from src.constants import (
    DIAL_TONE_FREQUENCIES,
    DIAL_TONE_TIMEOUT_IDLE,
    DIAL_TONE_TIMEOUT_PLAYING,
    DIRECT_DIAL_DISAMBIGUATION_TIMEOUT,
    INACTIVITY_TIMEOUT,
    PHONE_NUMBER_LENGTH,
    MAX_MENU_OPTIONS,
    ASSISTANT_NUMBER,
)

# Script text (must match SCRIPTS.md)
SCRIPT_OPERATOR_OPENER = "Operator."
SCRIPT_GREETING = "How may I direct your call?"
SCRIPT_EXTENSION_HINT = ("If you know your party's extension, please dial it now. "
                          "Otherwise, stay on the line and I'll connect you shortly.")
SCRIPT_IDLE_MENU_HEADER = "I have the following exchanges available."
SCRIPT_BROWSE_PROMPT_PLAYLIST = "Please dial the first letter of your playlist's name."
SCRIPT_BROWSE_PROMPT_ARTIST = "Please dial the first letter of your artist's name."
SCRIPT_BROWSE_PROMPT_GENRE = "Please dial the first letter of your genre."
SCRIPT_BROWSE_PROMPT_ALBUM = "Please dial the first letter of your album's name."
SCRIPT_NOT_IN_SERVICE = "I'm sorry, that number is not in service. Please check the number and try again."
SCRIPT_MISSED_CALL_TEMPLATE = "You have a missed call from your assistant. To reach them, dial {number}."
SCRIPT_PLAYING_GREETING_TEMPLATE = "Your call with {name} is currently in progress."
SCRIPT_PLAYING_MENU_DEFAULT = ("To place your call on hold, dial one. "
                                "To transfer to the next party, dial two. "
                                "To disconnect your call, dial three. "
                                "To reach a new party, dial zero.")
SCRIPT_PLAYING_MENU_ON_HOLD = ("To resume your call, dial one. "
                                "To transfer to the next party, dial two. "
                                "To disconnect your call, dial three. "
                                "To reach a new party, dial zero.")
SCRIPT_PLAYING_MENU_LAST_TRACK = ("To place your call on hold, dial one. "
                                   "To disconnect your call, dial three. "
                                   "To reach a new party, dial zero.")
SCRIPT_PLAYING_MENU_ON_HOLD_LAST_TRACK = ("To resume your call, dial one. "
                                           "To disconnect your call, dial three. "
                                           "To reach a new party, dial zero.")
SCRIPT_PLEX_FAILURE = ("I'm sorry, our long-distance exchange appears to be temporarily "
                        "out of service. We apologize for the inconvenience.")
SCRIPT_DB_FAILURE = ("I'm sorry, our directory appears to be temporarily unavailable. "
                     "The switchboard is experiencing an internal fault.")
SCRIPT_RETRY_PROMPT = ("If you'd like me to try the exchange again, dial one. "
                        "Otherwise, you may replace your handset and try your call again later.")
SCRIPT_NO_CONTENT = ("We're sorry. There are no parties available on this exchange at this time. "
                      "Please replace your handset.")
SCRIPT_TERMINAL_FALLBACK = ("We're sorry. Your call cannot be completed as dialed. "
                              "Please replace your handset and try again later.")


class MenuState(Enum):
    IDLE_DIAL_TONE = auto()
    IDLE_MENU = auto()
    PLAYING_MENU = auto()
    BROWSE_PLAYLISTS = auto()
    BROWSE_ARTISTS = auto()
    BROWSE_GENRES = auto()
    BROWSE_ALBUMS = auto()
    ARTIST_SUBMENU = auto()
    DIRECT_DIAL = auto()
    ASSISTANT = auto()
    OFF_HOOK = auto()


_DIGIT_WORDS = {
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
    '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
}


class Menu:
    """Menu state machine.

    Call on_handset_lifted() when the handset is picked up.
    Call on_handset_on_cradle() when it is replaced.
    Call on_digit(digit, now) when a digit is decoded by gpio_handler.
    Call tick(now) from a polling loop to advance timeouts.
    """

    def __init__(
        self,
        audio: AudioInterface,
        tts: TTSInterface,
        plex_client: PlexClientInterface,
        plex_store,   # PlexStore or MockPlexStore
        phone_book,   # PhoneBook
        error_queue: ErrorQueueInterface,
    ) -> None:
        self._audio = audio
        self._tts = tts
        self._plex_client = plex_client
        self._plex_store = plex_store
        self._phone_book = phone_book
        self._error_queue = error_queue

        self._state: MenuState = MenuState.IDLE_DIAL_TONE
        self._handset_up: bool = False

        # Whether the opener has been spoken this session
        self._opener_spoken: bool = False

        # Timing
        self._handset_up_time: float = 0.0
        self._last_activity_time: float = 0.0

        # Disambiguation
        self._pending_digit: Optional[int] = None
        self._pending_digit_time: float = 0.0

        # Direct dial accumulator
        self._dial_digits: List[int] = []

        # Navigation stack (for '9' = back)
        self._nav_stack: List[MenuState] = []

        # Failure state (for retry loops)
        self._failure_mode: Optional[str] = None  # "plex" | "db" | None

        # Playing menu: whether we just stopped music
        self._just_stopped_music: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> MenuState:
        return self._state

    def on_handset_lifted(self, now: Optional[float] = None) -> None:
        """Called when the handset is picked up."""
        if now is None:
            now = time.monotonic()
        self._handset_up = True
        self._opener_spoken = False
        self._just_stopped_music = False
        self._handset_up_time = now
        self._last_activity_time = now
        self._state = MenuState.IDLE_DIAL_TONE
        self._nav_stack.clear()
        self._dial_digits.clear()
        self._pending_digit = None
        self._failure_mode = None
        self._audio.play_tone(DIAL_TONE_FREQUENCIES, 500)

    def on_handset_on_cradle(self) -> None:
        """Called when the handset is replaced."""
        self._handset_up = False
        self._audio.stop()
        self._state = MenuState.IDLE_DIAL_TONE
        self._nav_stack.clear()
        self._dial_digits.clear()
        self._pending_digit = None

    def on_digit(self, digit: int, now: Optional[float] = None) -> None:
        """Called when a digit is decoded."""
        if not self._handset_up:
            return
        if now is None:
            now = time.monotonic()
        self._last_activity_time = now

        if self._state == MenuState.DIRECT_DIAL:
            self._handle_direct_dial_digit(digit, now)
            return

        # Disambiguation logic
        if self._pending_digit is None:
            self._pending_digit = digit
            self._pending_digit_time = now
        else:
            # Second digit within window → enter DIRECT_DIAL
            first = self._pending_digit
            self._pending_digit = None
            self._enter_direct_dial(first, digit, now)

    def tick(self, now: Optional[float] = None) -> None:
        """Advance timeouts. Call from polling loop."""
        if not self._handset_up:
            return
        if now is None:
            now = time.monotonic()

        # Check for pending disambiguation timeout
        if self._pending_digit is not None:
            elapsed = now - self._pending_digit_time
            if elapsed >= DIRECT_DIAL_DISAMBIGUATION_TIMEOUT:
                digit = self._pending_digit
                self._pending_digit = None
                self._dispatch_navigation_digit(digit, now)
                return

        # Inactivity timeout
        if self._state not in (MenuState.OFF_HOOK, MenuState.IDLE_DIAL_TONE):
            if now - self._last_activity_time >= INACTIVITY_TIMEOUT:
                self._go_off_hook()
                return

        # Dial tone timeout → deliver menu
        if self._state == MenuState.IDLE_DIAL_TONE:
            self._check_dial_tone_timeout(now)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _check_dial_tone_timeout(self, now: float) -> None:
        """Fire the menu prompt after the appropriate dial tone silence."""
        elapsed = now - self._handset_up_time
        # Determine which timeout applies
        playback = self._plex_client.now_playing()
        if playback.item is not None:
            timeout = DIAL_TONE_TIMEOUT_PLAYING
        else:
            timeout = DIAL_TONE_TIMEOUT_IDLE

        if elapsed >= timeout:
            self._audio.stop()
            if playback.item is not None:
                self._deliver_playing_menu(playback, now)
            else:
                self._deliver_idle_menu(now)

    def _deliver_idle_menu(self, now: float) -> None:
        """Deliver the idle top-level menu prompt."""
        self._last_activity_time = now

        # Try to load content
        try:
            has_playlists = self._plex_store.playlists_has_content
            has_artists = self._plex_store.artists_has_content
            has_genres = self._plex_store.genres_has_content

            if not has_playlists:
                self._plex_store.get_playlists()
                has_playlists = self._plex_store.playlists_has_content
            if not has_artists:
                self._plex_store.get_artists()
                has_artists = self._plex_store.artists_has_content
            if not has_genres:
                self._plex_store.get_genres()
                has_genres = self._plex_store.genres_has_content

        except Exception:
            self._failure_mode = "plex"
            self._state = MenuState.IDLE_MENU
            self._tts.speak_and_play(SCRIPT_PLEX_FAILURE)
            self._tts.speak_and_play(SCRIPT_RETRY_PROMPT)
            return

        if not has_playlists and not has_artists and not has_genres:
            self._state = MenuState.OFF_HOOK
            self._tts.speak_and_play(SCRIPT_NO_CONTENT)
            self._audio.play_off_hook_tone()
            return

        self._state = MenuState.IDLE_MENU
        self._failure_mode = None

        if not self._opener_spoken:
            self._tts.speak_and_play(SCRIPT_OPERATOR_OPENER)
            self._opener_spoken = True

        self._tts.speak_and_play(SCRIPT_GREETING)
        self._tts.speak_and_play(SCRIPT_EXTENSION_HINT)

        # Check for missed calls (non-empty error queue)
        if self._error_queue.get_all():
            self._tts.speak_and_play(
                SCRIPT_MISSED_CALL_TEMPLATE.format(number=ASSISTANT_NUMBER)
            )

        # Build dynamic menu
        parts = [SCRIPT_IDLE_MENU_HEADER]
        option_num = 1
        if has_playlists and option_num <= MAX_MENU_OPTIONS:
            parts.append(f"For playlists, dial {option_num}.")
            option_num += 1
        if has_artists and option_num <= MAX_MENU_OPTIONS:
            parts.append(f"For artists, dial {option_num}.")
            option_num += 1
        if has_genres and option_num <= MAX_MENU_OPTIONS:
            parts.append(f"For genres, dial {option_num}.")
            option_num += 1
        parts.append(f"To place a trunk call to the general exchange, dial {option_num}.")
        self._tts.speak_and_play(" ".join(parts))

    def _deliver_playing_menu(self, playback: PlaybackState, now: float) -> None:
        """Deliver the playing state top-level menu prompt."""
        self._last_activity_time = now
        self._state = MenuState.PLAYING_MENU

        if not self._opener_spoken:
            self._tts.speak_and_play(SCRIPT_OPERATOR_OPENER)
            self._opener_spoken = True

        self._tts.speak_and_play(
            SCRIPT_PLAYING_GREETING_TEMPLATE.format(name=playback.item.name)
        )

        # Determine skip availability
        pos, total = self._plex_client.get_queue_position()
        is_last_track = (pos == total)

        if playback.is_paused:
            if is_last_track:
                self._tts.speak_and_play(SCRIPT_PLAYING_MENU_ON_HOLD_LAST_TRACK)
            else:
                self._tts.speak_and_play(SCRIPT_PLAYING_MENU_ON_HOLD)
        else:
            if is_last_track:
                self._tts.speak_and_play(SCRIPT_PLAYING_MENU_LAST_TRACK)
            else:
                self._tts.speak_and_play(SCRIPT_PLAYING_MENU_DEFAULT)

    # ------------------------------------------------------------------
    # Digit dispatching
    # ------------------------------------------------------------------

    def _dispatch_navigation_digit(self, digit: int, now: float) -> None:
        """Handle a single confirmed navigation digit."""
        self._last_activity_time = now

        if digit == 0:
            # Return to top-level menu (always idle, even if music is playing)
            self._nav_stack.clear()
            self._deliver_idle_menu(now)
            return

        if digit == 9:
            # Go back one level
            if self._nav_stack:
                self._state = self._nav_stack.pop()
                # Re-deliver the menu for that state
                self._re_deliver_current_state(now)
            else:
                # Already at top level; stay
                self._go_top_level(now)
            return

        # State-specific digit handling
        if self._state == MenuState.IDLE_MENU:
            self._handle_idle_menu_digit(digit, now)
        elif self._state == MenuState.PLAYING_MENU:
            self._handle_playing_menu_digit(digit, now)
        elif self._state == MenuState.BROWSE_PLAYLISTS:
            self._handle_browse_digit(digit, now, "playlist")
        elif self._state == MenuState.BROWSE_ARTISTS:
            self._handle_browse_digit(digit, now, "artist")
        elif self._state == MenuState.BROWSE_GENRES:
            self._handle_browse_digit(digit, now, "genre")
        else:
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)

    def _handle_idle_menu_digit(self, digit: int, now: float) -> None:
        """Process digit in IDLE_MENU state."""
        if self._failure_mode == "plex":
            if digit == 1:
                # Retry
                try:
                    self._plex_store.get_playlists()
                    self._failure_mode = None
                    self._deliver_idle_menu(now)
                except Exception:
                    self._tts.speak_and_play(SCRIPT_PLEX_FAILURE)
                    self._tts.speak_and_play(SCRIPT_RETRY_PROMPT)
            else:
                self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
            return

        # Determine available options dynamically
        has_playlists = self._plex_store.playlists_has_content
        has_artists = self._plex_store.artists_has_content
        has_genres = self._plex_store.genres_has_content

        options = []
        if has_playlists:
            options.append(('playlist', MenuState.BROWSE_PLAYLISTS))
        if has_artists:
            options.append(('artist', MenuState.BROWSE_ARTISTS))
        if has_genres:
            options.append(('genre', MenuState.BROWSE_GENRES))
        options.append(('shuffle', None))  # shuffle_all

        idx = digit - 1  # digits are 1-based
        if idx < 0 or idx >= len(options):
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
            self._re_deliver_current_state(now)
            return

        name, next_state = options[idx]
        if name == 'shuffle':
            self._plex_client.shuffle_all()
        elif next_state == MenuState.BROWSE_PLAYLISTS:
            self._nav_stack.append(MenuState.IDLE_MENU)
            self._state = MenuState.BROWSE_PLAYLISTS
            self._tts.speak_and_play(SCRIPT_BROWSE_PROMPT_PLAYLIST)
        elif next_state == MenuState.BROWSE_ARTISTS:
            self._nav_stack.append(MenuState.IDLE_MENU)
            self._state = MenuState.BROWSE_ARTISTS
            self._tts.speak_and_play(SCRIPT_BROWSE_PROMPT_ARTIST)
        elif next_state == MenuState.BROWSE_GENRES:
            self._nav_stack.append(MenuState.IDLE_MENU)
            self._state = MenuState.BROWSE_GENRES
            self._tts.speak_and_play(SCRIPT_BROWSE_PROMPT_GENRE)

    def _handle_playing_menu_digit(self, digit: int, now: float) -> None:
        """Process digit in PLAYING_MENU state."""
        playback = self._plex_client.now_playing()
        pos, total = self._plex_client.get_queue_position()
        is_last_track = (pos == total)

        if digit == 1:
            if playback.is_paused:
                self._plex_client.unpause()
            else:
                self._plex_client.pause()
        elif digit == 2:
            if not is_last_track:
                self._plex_client.skip()
            else:
                self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
        elif digit == 3:
            self._plex_client.stop()
            self._just_stopped_music = True
            self._state = MenuState.IDLE_MENU
            # Go to idle menu without re-delivering opener
            # deliver idle menu directly (opener already spoken)
            self._deliver_idle_menu(now)
        else:
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)

    def _handle_browse_digit(self, digit: int, now: float, media_type: str) -> None:
        """T9 browse digit (§9.4 — not yet implemented in this session)."""
        self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)

    # ------------------------------------------------------------------
    # Direct dial
    # ------------------------------------------------------------------

    def _enter_direct_dial(self, first: int, second: int, now: float) -> None:
        """Enter DIRECT_DIAL mode with the first two digits."""
        self._state = MenuState.DIRECT_DIAL
        self._dial_digits = []
        self._audio.stop()
        self._audio.play_dtmf(first)
        self._dial_digits.append(first)
        self._audio.play_dtmf(second)
        self._dial_digits.append(second)
        self._last_activity_time = now

    def _handle_direct_dial_digit(self, digit: int, now: float) -> None:
        """Accumulate a direct dial digit."""
        if len(self._dial_digits) >= PHONE_NUMBER_LENGTH:
            return  # ignore extra digits
        self._audio.play_dtmf(digit)
        self._dial_digits.append(digit)
        self._last_activity_time = now
        if len(self._dial_digits) == PHONE_NUMBER_LENGTH:
            self._execute_direct_dial(now)

    def _execute_direct_dial(self, now: float) -> None:
        """Look up and play the phone number."""
        number = "".join(str(d) for d in self._dial_digits)
        try:
            entry = self._phone_book.lookup_by_phone_number(number)
        except Exception:
            entry = None

        if entry is None:
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
            self._state = MenuState.IDLE_MENU
            return

        self._plex_client.play(entry.plex_key)
        self._state = MenuState.PLAYING_MENU

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _go_top_level(self, now: float) -> None:
        """Navigate to the appropriate top-level menu."""
        playback = self._plex_client.now_playing()
        if playback.item is not None:
            self._deliver_playing_menu(playback, now)
        else:
            self._deliver_idle_menu(now)

    def _re_deliver_current_state(self, now: float) -> None:
        """Re-deliver the current state's menu prompt."""
        if self._state == MenuState.IDLE_MENU:
            self._deliver_idle_menu(now)
        elif self._state == MenuState.PLAYING_MENU:
            playback = self._plex_client.now_playing()
            self._deliver_playing_menu(playback, now)
        elif self._state == MenuState.BROWSE_PLAYLISTS:
            self._tts.speak_and_play(SCRIPT_BROWSE_PROMPT_PLAYLIST)
        elif self._state == MenuState.BROWSE_ARTISTS:
            self._tts.speak_and_play(SCRIPT_BROWSE_PROMPT_ARTIST)
        elif self._state == MenuState.BROWSE_GENRES:
            self._tts.speak_and_play(SCRIPT_BROWSE_PROMPT_GENRE)

    def _go_off_hook(self) -> None:
        """Enter the off-hook warning state."""
        self._state = MenuState.OFF_HOOK
        self._audio.play_off_hook_tone()
