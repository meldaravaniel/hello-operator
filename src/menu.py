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
SCRIPT_SERVICE_DEGRADATION = ("I beg your pardon — we're experiencing some difficulty "
                               "on the line. One moment please.")
SCRIPT_BROWSE_PROMPT_NEXT_LETTER = ("I have quite a few parties on that exchange. "
                                     "Please dial the next letter of your party's name to "
                                     "narrow the connection.")
SCRIPT_BROWSE_LIST_INTRO_TEMPLATE = "I have {n} parties on the line."
SCRIPT_BROWSE_AUTO_SELECT_TEMPLATE = ("One moment — I have exactly one match. "
                                       "Connecting you to {name} now.")
SCRIPT_ARTIST_SUBMENU_TEMPLATE = "To speak to {artist}, dial one."
SCRIPT_ARTIST_SUBMENU_ALBUMS_SUFFIX = " For a particular album, dial two."
SCRIPT_ARTIST_SINGLE_ALBUM_TEMPLATE = "To call {album}, dial one."
SCRIPT_CONNECTING_TEMPLATE = ("Thank you for your patience. I'm connecting your call to "
                               "{digits} — {name}. Please hold.")
SCRIPT_SHUFFLE_CONNECTING = ("One moment, please — I'm putting you through to the general exchange. "
                              "Enjoy your call!")

# Diagnostic assistant scripts
SCRIPT_ASSISTANT_GREETING = "Good day, this is the operator's assistant. Let me pull up your account now."
SCRIPT_ASSISTANT_ALL_CLEAR = ("Everything is running just beautifully, I'm happy to report. "
                               "No messages, no trouble on the lines. You're all set, chief. "
                               "I'll let you get back to it — toodle-oo!")
SCRIPT_ASSISTANT_STATUS_INTRO = "I do have a few things here for you. Let me see now..."
SCRIPT_ASSISTANT_END_OF_MESSAGES = "And that's the last of them. Is there anything else I can help you with?"
SCRIPT_ASSISTANT_NAVIGATION = ("To hear that again, dial one. For the previous menu, dial nine. "
                                "To go back to the switchboard, dial zero.")
SCRIPT_ASSISTANT_VALEDICTION_CLEAR = "Right then, I'll put you back through to the switchboard. Have a wonderful day!"
SCRIPT_ASSISTANT_VALEDICTION_MESSAGES = "I'll put you back through now. Do give a shout if you need anything else!"
SCRIPT_ASSISTANT_REFRESH_SUCCESS = ("All done! I've gone ahead and updated all my records from the exchange. "
                                     "Everything's shipshape.")
SCRIPT_ASSISTANT_REFRESH_FAILURE = ("I'm afraid I had some trouble reaching the exchange just now. "
                                     "My records are unchanged. You might try again in a moment, dear.")
SCRIPT_ASSISTANT_CONTINUE_PROMPT_TEMPLATE = ("That's {page_size}. Shall I go on? "
                                              "Dial one to continue, or dial zero to go back to the switchboard.")
SCRIPT_ASSISTANT_REFRESH_PROMPT = "To refresh my records from the exchange, dial {n}."
# Alias used by tests
SCRIPT_ASSISTANT_CONTINUE_PROMPT = SCRIPT_ASSISTANT_CONTINUE_PROMPT_TEMPLATE


# ---------------------------------------------------------------------------
# T9 utilities
# ---------------------------------------------------------------------------

# T9 digit → letter group
_T9_GROUPS = {
    1: set("ABCabc"),
    2: set("DEFdef"),
    3: set("GHIghi"),
    4: set("JKLjkl"),
    5: set("MNOmno"),
    6: set("PQRpqr"),
    7: set("STUstu"),
    8: set("VWXYZvwxyz"),
}

# Digits that map to themselves
_T9_DIGIT_CHARS = set("0123456789")

_ARTICLES = ("the ", "a ", "an ")


def _strip_article(name: str) -> str:
    """Strip leading articles for T9 indexing (case-insensitive)."""
    lower = name.lower()
    for article in _ARTICLES:
        if lower.startswith(article):
            return name[len(article):]
    return name


def _t9_digit_for_name(name: str) -> int:
    """Return the T9 digit (1–8) for the first indexable character of name."""
    stripped = _strip_article(name)
    if not stripped:
        return 8
    first = stripped[0]
    if first in _T9_DIGIT_CHARS:
        return int(first) if first != '0' else 8  # '0' falls under 8
    for digit, chars in _T9_GROUPS.items():
        if first in chars:
            return digit
    return 8  # special chars → 8


def _filter_by_t9_prefix(items: List[MediaItem], prefix: List[int]) -> List[MediaItem]:
    """Filter items whose T9-stripped name matches the given digit prefix."""
    if not prefix:
        return list(items)
    result = []
    for item in items:
        stripped = _strip_article(item.name)
        if not stripped:
            continue
        match = True
        for i, digit in enumerate(prefix):
            if i >= len(stripped):
                match = False
                break
            ch = stripped[i]
            expected = _t9_digit_for_char(ch)
            if expected != digit:
                match = False
                break
        if match:
            result.append(item)
    return result


def _t9_digit_for_char(ch: str) -> int:
    """Return T9 digit for a single character."""
    if ch in _T9_DIGIT_CHARS:
        return int(ch) if ch != '0' else 8
    for digit, chars in _T9_GROUPS.items():
        if ch in chars:
            return digit
    return 8


def _parse_genre_plex_key(plex_key: str):
    """Parse a genre plex_key of the form 'section:{section_id}/genre:{genre_key}'.

    Returns (section_id, genre_key).
    """
    # Format: section:{section_id}/genre:{genre_key}
    section_part, genre_part = plex_key.split("/genre:", 1)
    section_id = section_part.split("section:", 1)[1]
    return section_id, genre_part


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

        # Browse state
        self._browse_prefix: List[int] = []          # accumulated T9 digits
        self._browse_items: List[MediaItem] = []     # current filtered items
        self._browse_listed: List[MediaItem] = []    # currently listed (≤8) options
        self._current_artist: Optional[MediaItem] = None  # selected artist

        # Assistant sub-state
        self._assistant_mode: str = "menu"  # "menu" | "reading" | "refreshed"
        self._assistant_messages: List = []          # current message list being read
        self._assistant_page_offset: int = 0         # how many messages already read
        self._assistant_digit_map: dict = {}         # digit → action

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

        # ASSISTANT state handles its own navigation (0 and 9 are not reserved there)
        if self._state == MenuState.ASSISTANT:
            self._handle_assistant_digit(digit, now)
            return

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
        elif self._state == MenuState.BROWSE_ALBUMS:
            self._handle_browse_digit(digit, now, "album")
        elif self._state == MenuState.ARTIST_SUBMENU:
            self._handle_artist_submenu_digit(digit, now)
        elif self._state == MenuState.ASSISTANT:
            self._handle_assistant_digit(digit, now)
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
            self._tts.speak_and_play(SCRIPT_SHUFFLE_CONNECTING)
            self._state = MenuState.PLAYING_MENU
        elif next_state == MenuState.BROWSE_PLAYLISTS:
            items = self._plex_store.get_playlists()
            self._start_browse(items, MenuState.BROWSE_PLAYLISTS,
                               SCRIPT_BROWSE_PROMPT_PLAYLIST, now)
        elif next_state == MenuState.BROWSE_ARTISTS:
            items = self._plex_store.get_artists()
            self._start_browse(items, MenuState.BROWSE_ARTISTS,
                               SCRIPT_BROWSE_PROMPT_ARTIST, now)
        elif next_state == MenuState.BROWSE_GENRES:
            items = self._plex_store.get_genres()
            self._start_browse(items, MenuState.BROWSE_GENRES,
                               SCRIPT_BROWSE_PROMPT_GENRE, now)

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
        """T9 browse digit — narrows or selects from the browse list."""
        if self._browse_listed:
            # We're in "listed" mode — digit selects an item
            idx = digit - 1
            if idx < 0 or idx >= len(self._browse_listed):
                self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
                self._re_deliver_current_state(now)
                return
            selected = self._browse_listed[idx]
            self._select_item(selected, media_type, now)
            return

        # T9 narrowing mode
        self._browse_prefix.append(digit)
        filtered = _filter_by_t9_prefix(self._browse_items, self._browse_prefix)

        if len(filtered) == 0:
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
            # Return to previous prefix
            self._browse_prefix.pop()
            return

        if len(filtered) == 1:
            # Auto-select
            item = filtered[0]
            self._tts.speak_and_play(
                SCRIPT_BROWSE_AUTO_SELECT_TEMPLATE.format(name=item.name)
            )
            self._select_item(item, media_type, now)
            return

        if len(filtered) <= MAX_MENU_OPTIONS:
            # List them
            self._browse_listed = filtered
            parts = [SCRIPT_BROWSE_LIST_INTRO_TEMPLATE.format(n=len(filtered))]
            for i, item in enumerate(filtered, start=1):
                parts.append(f"For {item.name}, dial {i}.")
            self._tts.speak_and_play(" ".join(parts))
            return

        # Too many — ask for next letter
        self._browse_items = filtered  # narrow the pool
        self._browse_listed = []
        self._tts.speak_and_play(SCRIPT_BROWSE_PROMPT_NEXT_LETTER)

    def _start_browse(self, items: List[MediaItem], state: MenuState,
                      prompt: str, now: float) -> None:
        """Enter a browse state with the given items."""
        self._nav_stack.append(self._state)
        self._state = state
        self._browse_items = list(items)
        self._browse_prefix = []
        self._browse_listed = []
        self._tts.speak_and_play(prompt)

    def _select_item(self, item: MediaItem, media_type: str, now: float) -> None:
        """Handle final selection of a browse item."""
        if media_type == "artist":
            self._current_artist = item
            self._state = MenuState.ARTIST_SUBMENU
            albums = self._plex_store.get_albums_for_artist(item.plex_key)
            if albums:
                text = SCRIPT_ARTIST_SUBMENU_TEMPLATE.format(artist=item.name)
                text += SCRIPT_ARTIST_SUBMENU_ALBUMS_SUFFIX
            else:
                text = SCRIPT_ARTIST_SUBMENU_TEMPLATE.format(artist=item.name)
            self._tts.speak_and_play(text)
            self._browse_listed = []
        elif media_type == "genre":
            # Genre: decode section_id and genre_key from plex_key, fetch tracks, play shuffled
            # plex_key format: "section:{section_id}/genre:{genre_key}"
            section_id, genre_key = _parse_genre_plex_key(item.plex_key)
            track_keys = self._plex_client.get_tracks_for_genre(section_id, genre_key)
            if not track_keys:
                self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
                # Return to the genre browse state
                self._state = MenuState.BROWSE_GENRES
            else:
                number = self._phone_book.assign_or_get(item.plex_key, item.media_type, item.name)
                digit_words_str = " ".join(_DIGIT_WORDS[d] for d in number)
                self._tts.speak_and_play(
                    SCRIPT_CONNECTING_TEMPLATE.format(digits=digit_words_str, name=item.name)
                )
                self._plex_client.play_tracks(track_keys, shuffle=True)
                self._state = MenuState.PLAYING_MENU
        else:
            # Playlist, album → play directly
            number = self._phone_book.assign_or_get(item.plex_key, item.media_type, item.name)
            digit_words_str = " ".join(_DIGIT_WORDS[d] for d in number)
            self._tts.speak_and_play(
                SCRIPT_CONNECTING_TEMPLATE.format(digits=digit_words_str, name=item.name)
            )
            self._plex_client.play(item.plex_key)
            self._state = MenuState.PLAYING_MENU

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

        # Route to diagnostic assistant
        if number == ASSISTANT_NUMBER:
            self._enter_assistant(now)
            return

        try:
            entry = self._phone_book.lookup_by_phone_number(number)
        except Exception:
            entry = None

        if entry is None:
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
            self._state = MenuState.IDLE_MENU
            return

        # Speak connecting announcement with digits spoken individually
        digit_words_str = " ".join(_DIGIT_WORDS[d] for d in number)
        name = entry.get("name", number)
        self._tts.speak_and_play(
            SCRIPT_CONNECTING_TEMPLATE.format(digits=digit_words_str, name=name)
        )
        self._plex_client.play(entry["plex_key"])
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
        elif self._state == MenuState.BROWSE_ALBUMS:
            self._tts.speak_and_play(SCRIPT_BROWSE_PROMPT_ALBUM)
        elif self._state == MenuState.ARTIST_SUBMENU:
            if self._current_artist:
                albums = self._plex_store.get_albums_for_artist(self._current_artist.plex_key)
                text = SCRIPT_ARTIST_SUBMENU_TEMPLATE.format(artist=self._current_artist.name)
                if albums:
                    text += SCRIPT_ARTIST_SUBMENU_ALBUMS_SUFFIX
                self._tts.speak_and_play(text)

    def _handle_artist_submenu_digit(self, digit: int, now: float) -> None:
        """Handle digit in ARTIST_SUBMENU state."""
        if self._current_artist is None:
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
            return
        albums = self._plex_store.get_albums_for_artist(self._current_artist.plex_key)
        if digit == 1:
            # Play / shuffle artist — announce connection first
            number = self._phone_book.assign_or_get(
                self._current_artist.plex_key,
                self._current_artist.media_type,
                self._current_artist.name,
            )
            digit_words_str = " ".join(_DIGIT_WORDS[d] for d in number)
            self._tts.speak_and_play(
                SCRIPT_CONNECTING_TEMPLATE.format(
                    digits=digit_words_str, name=self._current_artist.name
                )
            )
            self._plex_client.play(self._current_artist.plex_key)
            self._state = MenuState.PLAYING_MENU
        elif digit == 2 and albums:
            # Browse albums for this artist
            self._start_browse(albums, MenuState.BROWSE_ALBUMS,
                               SCRIPT_BROWSE_PROMPT_ALBUM, now)
        else:
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
            self._re_deliver_current_state(now)

    # ------------------------------------------------------------------
    # Diagnostic assistant
    # ------------------------------------------------------------------

    def _enter_assistant(self, now: float) -> None:
        """Enter ASSISTANT state and deliver initial status."""
        self._state = MenuState.ASSISTANT
        self._assistant_mode = "menu"
        self._assistant_messages = []
        self._assistant_page_offset = 0
        self._assistant_digit_map = {}
        self._last_activity_time = now

        self._tts.speak_and_play(SCRIPT_ASSISTANT_GREETING)

        all_entries = self._error_queue.get_all()

        option_num = 1
        digit_map = {}
        parts = []

        if not all_entries:
            # All clear — speak and stay in ASSISTANT; any digit will redirect
            self._tts.speak_and_play(SCRIPT_ASSISTANT_ALL_CLEAR)
            # Still offer refresh and return
            refresh_digit = option_num
            parts.append(SCRIPT_ASSISTANT_REFRESH_PROMPT.format(n=refresh_digit))
            digit_map[refresh_digit] = ('refresh', None)
            option_num += 1
            parts.append(f"Or dial zero to go back to the switchboard.")
            self._tts.speak_and_play(" ".join(parts))
            self._assistant_digit_map = digit_map
            self._assistant_mode = "menu"
            return

        # Build options for messages
        warnings = self._error_queue.get_by_severity("warning")
        errors = self._error_queue.get_by_severity("error")

        self._tts.speak_and_play(SCRIPT_ASSISTANT_STATUS_INTRO)

        if warnings:
            parts.append(f"I have {len(warnings)} warning{'s' if len(warnings) != 1 else ''} in the queue. "
                         f"For warnings, dial {option_num}.")
            digit_map[option_num] = ('warnings', warnings)
            option_num += 1
        if errors:
            parts.append(f"I have {len(errors)} error{'s' if len(errors) != 1 else ''} in the queue. "
                         f"For errors, dial {option_num}.")
            digit_map[option_num] = ('errors', errors)
            option_num += 1

        # Refresh option always present
        refresh_digit = option_num
        parts.append(SCRIPT_ASSISTANT_REFRESH_PROMPT.format(n=refresh_digit))
        digit_map[refresh_digit] = ('refresh', None)

        parts.append("Or dial zero to go back to the switchboard.")
        self._tts.speak_and_play(" ".join(parts))
        self._assistant_digit_map = digit_map
        self._assistant_mode = "menu"

    def _handle_assistant_digit(self, digit: int, now: float) -> None:
        """Handle a digit while in ASSISTANT state."""
        self._last_activity_time = now

        if self._assistant_mode == "reading":
            self._assistant_continue_or_navigate(digit, now)
            return

        if digit == 0 or digit == 9:
            self._deliver_assistant_redirect(now)
            return

        action = self._assistant_digit_map.get(digit)
        if action is None:
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
            return

        kind, messages = action
        if kind == 'refresh':
            self._do_assistant_refresh(now)
        elif kind in ('warnings', 'errors'):
            self._assistant_messages = list(messages)
            self._assistant_page_offset = 0
            self._assistant_mode = "reading"
            self._read_assistant_page(now)

    def _read_assistant_page(self, now: float) -> None:
        """Read the current page of assistant messages."""
        from src.constants import ASSISTANT_MESSAGE_PAGE_SIZE
        messages = self._assistant_messages
        offset = self._assistant_page_offset
        page = messages[offset:offset + ASSISTANT_MESSAGE_PAGE_SIZE]
        remaining = messages[offset + ASSISTANT_MESSAGE_PAGE_SIZE:]

        total = len(messages)
        page_size = ASSISTANT_MESSAGE_PAGE_SIZE
        self._tts.speak_and_play(
            f"All right, here we go. I have {total} message{'s' if total != 1 else ''} for you. "
            f"I'll read you the first {min(page_size, total)}."
        )
        for entry in page:
            self._tts.speak_and_play(entry.message)

        if remaining:
            self._tts.speak_and_play(
                SCRIPT_ASSISTANT_CONTINUE_PROMPT_TEMPLATE.format(page_size=page_size)
            )
        else:
            self._tts.speak_and_play(SCRIPT_ASSISTANT_END_OF_MESSAGES)

        self._tts.speak_and_play(SCRIPT_ASSISTANT_NAVIGATION)
        self._assistant_page_offset += len(page)

    def _assistant_continue_or_navigate(self, digit: int, now: float) -> None:
        """Handle digit while reading messages."""
        from src.constants import ASSISTANT_MESSAGE_PAGE_SIZE
        if digit == 1:
            # Continue reading
            if self._assistant_page_offset < len(self._assistant_messages):
                self._read_assistant_page(now)
            else:
                self._tts.speak_and_play(SCRIPT_ASSISTANT_END_OF_MESSAGES)
                self._tts.speak_and_play(SCRIPT_ASSISTANT_NAVIGATION)
        elif digit == 0 or digit == 9:
            self._tts.speak_and_play(SCRIPT_ASSISTANT_VALEDICTION_MESSAGES)
            self._deliver_assistant_redirect(now)
        else:
            self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)

    def _do_assistant_refresh(self, now: float) -> None:
        """Perform the assistant refresh action."""
        try:
            self._plex_store.refresh()
            self._tts.speak_and_play(SCRIPT_ASSISTANT_REFRESH_SUCCESS)
        except Exception:
            self._tts.speak_and_play(SCRIPT_ASSISTANT_REFRESH_FAILURE)
        self._tts.speak_and_play(SCRIPT_ASSISTANT_NAVIGATION)

    def _deliver_assistant_redirect(self, now: float) -> None:
        """Redirect from assistant to appropriate menu."""
        playback = self._plex_client.now_playing()
        if playback.item is not None:
            self._deliver_playing_menu(playback, now)
        else:
            self._deliver_idle_menu(now)

    def _go_off_hook(self) -> None:
        """Enter the off-hook warning state."""
        self._state = MenuState.OFF_HOOK
        self._audio.play_off_hook_tone()
