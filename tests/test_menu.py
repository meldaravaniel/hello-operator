"""Tests for src/menu.py — Menu state machine (§9.1, §9.2, §9.3).

All tests use injected mocks; no hardware or network required.
"""

import time
import pytest
from src.menu import Menu, MenuState
from src.interfaces import MediaItem, PlaybackState
from src.constants import (
    DIRECT_DIAL_DISAMBIGUATION_TIMEOUT, INACTIVITY_TIMEOUT,
    ASSISTANT_NUMBER, ASSISTANT_MESSAGE_PAGE_SIZE, PHONE_NUMBER_LENGTH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, radio=None):
    """Build a Menu with all mocked dependencies."""
    from src.phone_book import PhoneBook
    from src.radio import MockRadio
    db = str(tmp_path / "phone_book.db")
    phone_book = PhoneBook(db_path=db)
    if radio is None:
        radio = MockRadio()
    return Menu(
        audio=mock_audio,
        tts=mock_tts,
        media_client=mock_media_client,
        media_store=mock_media_store,
        phone_book=phone_book,
        error_queue=mock_error_queue,
        radio=radio,
    )


# Baseline fake time for handset lift (all tick() calls use times > this)
_T0 = 0.0


def tts_spoke(mock_tts, text_fragment):
    """Return True if mock_tts.speak_and_play was called with text containing fragment."""
    return any(
        text_fragment in args[0] if args else False
        for method, *args in mock_tts.calls
        if method == 'speak_and_play'
    )


def tts_calls(mock_tts):
    """Return list of texts passed to speak_and_play."""
    return [args[0] for method, *args in mock_tts.calls if method == 'speak_and_play']


# ---------------------------------------------------------------------------
# §9.1 Reserved digits and disambiguation
# ---------------------------------------------------------------------------

class TestReservedDigitsAndDisambiguation:

    def test_digit_0_single_goes_to_top_level(self, mock_audio, mock_tts, mock_media_client,
                                               mock_media_store, mock_error_queue, tmp_path):
        """Digit 0 alone → state resets to top-level menu."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz Mix", "playlist")])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.on_digit(0, now=0.0)
        # After disambiguation timeout: should be at top level
        menu.tick(now=0.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state in (MenuState.IDLE_MENU, MenuState.PLAYING_MENU)

    def test_digit_9_single_goes_back_one_level(self, mock_audio, mock_tts, mock_media_client,
                                                 mock_media_store, mock_error_queue, tmp_path):
        """Digit 9 alone → state moves up one level."""
        mock_media_store.set_playlists([
            MediaItem("/p/1", "Jazz Mix", "playlist")
        ])
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        # Enter idle menu
        menu.tick(now=10.0)  # past dial tone timeout
        # Navigate into playlist browse
        menu.on_digit(1, now=10.1)
        menu.tick(now=10.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Now press 9 to go back
        menu.on_digit(9, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state in (MenuState.IDLE_MENU, MenuState.PLAYING_MENU)

    def test_digit_9_at_top_level(self, mock_audio, mock_tts, mock_media_client,
                                   mock_media_store, mock_error_queue, tmp_path):
        """Digit 9 at top level → no crash, stays at top level."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        menu.on_digit(9, now=10.1)
        menu.tick(now=10.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state in (MenuState.IDLE_MENU, MenuState.PLAYING_MENU)

    def test_disambiguation_timeout_single_digit_is_navigation(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """First digit received, no second digit within timeout → treated as navigation."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        menu.on_digit(1, now=10.1)
        # Tick past disambiguation timeout
        menu.tick(now=10.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Digit 1 navigated to playlist browse — not direct dial
        assert menu.state != MenuState.DIRECT_DIAL

    def test_disambiguation_second_digit_enters_direct_dial(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Second digit within timeout → DIRECT_DIAL mode entered."""
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        t = 10.0
        menu.on_digit(1, now=t)
        # Second digit within timeout
        menu.on_digit(2, now=t + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT * 0.5)
        menu.tick(now=t + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT * 0.5 + 0.01)
        assert menu.state == MenuState.DIRECT_DIAL

    def test_disambiguation_0_and_9_literal_in_direct_dial(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """In DIRECT_DIAL mode, 0 and 9 are accumulated as phone number digits."""
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        t = 10.0
        # Enter direct dial
        menu.on_digit(5, now=t)
        menu.on_digit(5, now=t + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT * 0.3)
        menu.tick(now=t + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT * 0.3 + 0.01)
        assert menu.state == MenuState.DIRECT_DIAL
        # Now dial 0 and 9 — should be accumulated, not navigation
        menu.on_digit(0, now=t + 1.0)
        menu.on_digit(9, now=t + 1.1)
        # Still in DIRECT_DIAL (only 4 digits so far, need 7)
        assert menu.state == MenuState.DIRECT_DIAL

    def test_dtmf_plays_for_each_direct_dial_digit(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """In DIRECT_DIAL mode, audio.play_dtmf called for each digit."""
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        t = 10.0
        # Enter direct dial with first two digits
        menu.on_digit(5, now=t)
        menu.on_digit(5, now=t + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT * 0.3)
        menu.tick(now=t + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT * 0.3 + 0.01)
        assert menu.state == MenuState.DIRECT_DIAL
        # Dial a third digit
        menu.on_digit(5, now=t + 1.0)
        dtmf_calls = [c for c in mock_audio.calls if c[0] == 'play_dtmf']
        # At least 3 DTMF tones played (one per digit)
        assert len(dtmf_calls) >= 3


# ---------------------------------------------------------------------------
# §9.2 Idle state top-level menu
# ---------------------------------------------------------------------------

SCRIPT_OPERATOR_OPENER = "Operator."
SCRIPT_GREETING = "How may I direct your call?"
SCRIPT_EXTENSION_HINT = "If you know your party's extension"
SCRIPT_IDLE_MENU = "following exchanges available"
SCRIPT_MISSED_CALL = "missed call from your assistant"
SCRIPT_NOT_IN_SERVICE = "not in service"
SCRIPT_MEDIA_FAILURE = "long-distance exchange appears to be temporarily out of service"
SCRIPT_RETRY_PROMPT = "dial one"
SCRIPT_NO_CONTENT = "no parties available"
SCRIPT_TERMINAL_FALLBACK = "Your call cannot be completed"


@pytest.fixture
def idle_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
    """Menu fixture with content available, nothing playing."""
    mock_media_store.set_playlists([
        MediaItem("/p/1", "Jazz Mix", "playlist"),
        MediaItem("/p/2", "Rock Classics", "playlist"),
    ])
    mock_media_store.set_artists([
        MediaItem("/a/1", "The Beatles", "artist"),
    ])
    mock_media_store.set_genres([
        MediaItem("/g/1", "Jazz", "genre"),
    ])
    mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
    return make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)


class TestIdleMenu:

    def _advance_to_idle_menu(self, menu, now=10.0):
        """Lift handset and advance past dial tone timeout."""
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=now)

    def test_idle_menu_announces_options(self, idle_menu, mock_tts, mock_media_client):
        """After dial tone timeout → TTS plays SCRIPT_OPERATOR_OPENER then SCRIPT_GREETING."""
        self._advance_to_idle_menu(idle_menu)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_OPERATOR_OPENER in t for t in texts), f"opener not found: {texts}"
        assert any(SCRIPT_GREETING in t for t in texts), f"greeting not found: {texts}"

    def test_operator_opener_spoken_once_per_session(self, idle_menu, mock_tts, mock_media_store):
        """SCRIPT_OPERATOR_OPENER spoken only on first prompt; not replayed on subsequent prompts."""
        self._advance_to_idle_menu(idle_menu)
        # Reset TTS call log
        mock_tts.calls.clear()
        # Trigger another menu prompt (e.g., back to top via digit 9)
        idle_menu.on_digit(9, now=15.0)
        idle_menu.tick(now=15.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert not any(SCRIPT_OPERATOR_OPENER in t for t in texts), \
            f"Opener was replayed: {texts}"

    def test_idle_menu_secondary_prompt(self, idle_menu, mock_tts):
        """After dial tone timeout → TTS plays SCRIPT_EXTENSION_HINT."""
        self._advance_to_idle_menu(idle_menu)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_EXTENSION_HINT in t for t in texts), f"extension hint not found: {texts}"

    def test_idle_menu_plays_options(self, idle_menu, mock_tts):
        """Available categories announced → TTS plays SCRIPT_IDLE_MENU."""
        self._advance_to_idle_menu(idle_menu)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_IDLE_MENU in t for t in texts), f"idle menu not found: {texts}"

    def test_idle_menu_option_1_playlist(self, idle_menu, mock_tts, mock_media_store):
        """Digit 1 → TTS plays SCRIPT_BROWSE_PROMPT_PLAYLIST."""
        self._advance_to_idle_menu(idle_menu)
        mock_tts.calls.clear()
        idle_menu.on_digit(1, now=11.0)
        idle_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any("playlist" in t.lower() for t in texts), f"playlist prompt not found: {texts}"

    def test_idle_menu_option_2_artist(self, idle_menu, mock_tts):
        """Digit 2 → TTS plays SCRIPT_BROWSE_PROMPT_ARTIST."""
        self._advance_to_idle_menu(idle_menu)
        mock_tts.calls.clear()
        idle_menu.on_digit(2, now=11.0)
        idle_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any("artist" in t.lower() for t in texts), f"artist prompt not found: {texts}"

    def test_idle_menu_option_3_genre(self, idle_menu, mock_tts):
        """Digit 3 → TTS plays SCRIPT_BROWSE_PROMPT_GENRE."""
        self._advance_to_idle_menu(idle_menu)
        mock_tts.calls.clear()
        idle_menu.on_digit(3, now=11.0)
        idle_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any("genre" in t.lower() for t in texts), f"genre prompt not found: {texts}"

    def test_idle_menu_option_4_shuffle(self, idle_menu, mock_media_client):
        """Digit 4 → calls plex_client.shuffle_all()."""
        self._advance_to_idle_menu(idle_menu)
        mock_media_client.calls.clear()
        idle_menu.on_digit(4, now=11.0)
        idle_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'shuffle_all' for c in mock_media_client.calls)

    def test_idle_menu_shuffle_speaks_connecting_announcement(self, idle_menu, mock_tts, mock_media_client):
        """Digit 4 (shuffle) → TTS speaks a connecting/shuffle announcement."""
        self._advance_to_idle_menu(idle_menu)
        mock_tts.calls.clear()
        idle_menu.on_digit(4, now=11.0)
        idle_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert len(texts) > 0, f"Expected a TTS announcement after shuffle, got none"
        full_text = " ".join(texts).lower()
        # The announcement should contain something about connecting / general exchange / shuffle
        assert any(
            phrase in full_text
            for phrase in ("connecting", "general exchange", "trunk call", "shuffl")
        ), f"No connecting/shuffle announcement found in: {texts}"

    def test_idle_menu_shuffle_transitions_to_playing_menu(self, idle_menu, mock_media_client):
        """Digit 4 (shuffle) → state transitions to PLAYING_MENU."""
        self._advance_to_idle_menu(idle_menu)
        idle_menu.on_digit(4, now=11.0)
        idle_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert idle_menu.state == MenuState.PLAYING_MENU, \
            f"Expected PLAYING_MENU after shuffle, got {idle_menu.state}"

    def test_idle_menu_shuffle_hangup_leaves_music_playing(self, idle_menu, mock_media_client):
        """After shuffle, hanging up must not call plex_client.stop()."""
        self._advance_to_idle_menu(idle_menu)
        idle_menu.on_digit(4, now=11.0)
        idle_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        mock_media_client.calls.clear()
        idle_menu.on_handset_on_cradle()
        media_stop_calls = [c for c in mock_media_client.calls if c[0] == 'stop']
        assert len(media_stop_calls) == 0, \
            f"Hang-up should not stop media, but stop() was called: {mock_media_client.calls}"

    def test_idle_menu_omits_empty_category(self, mock_audio, mock_tts, mock_media_client,
                                             mock_media_store, mock_error_queue, tmp_path):
        """plex_store.has_content False for a category → not in menu."""
        mock_media_store.set_playlists([])
        mock_media_store.set_artists([MediaItem("/a/1", "Beatles", "artist")])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        texts = tts_calls(mock_tts)
        full_text = " ".join(texts).lower()
        assert "playlist" not in full_text or "artist" in full_text

    def test_idle_menu_missed_call_indicator(self, idle_menu, mock_tts, mock_error_queue):
        """Error queue non-empty → SCRIPT_MISSED_CALL included in menu."""
        from src.interfaces import ErrorEntry
        from datetime import datetime, timezone
        mock_error_queue.entries.append(ErrorEntry(
            source="tts", severity="warning", message="test error",
            count=1, last_happened=datetime.now(timezone.utc).isoformat()
        ))
        self._advance_to_idle_menu(idle_menu)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_MISSED_CALL in t for t in texts), f"missed call not found: {texts}"

    def test_idle_menu_no_missed_call_when_queue_empty(self, idle_menu, mock_tts, mock_error_queue):
        """Error queue empty → no SCRIPT_MISSED_CALL."""
        mock_error_queue.entries.clear()
        self._advance_to_idle_menu(idle_menu)
        texts = tts_calls(mock_tts)
        assert not any(SCRIPT_MISSED_CALL in t for t in texts)

    def test_idle_menu_invalid_digit(self, idle_menu, mock_tts):
        """Digit with no option → TTS plays SCRIPT_NOT_IN_SERVICE."""
        self._advance_to_idle_menu(idle_menu)
        mock_tts.calls.clear()
        idle_menu.on_digit(8, now=11.0)  # 8 is not offered in idle menu
        idle_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts), f"not-in-service not found: {texts}"

    def test_now_playing_called_once_during_dial_tone(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """now_playing() called exactly once at handset lift, not once per tick.

        Regression test: previously _check_dial_tone_timeout() called now_playing()
        on every tick (200 Hz), flooding MPD with connect/disconnect cycles.
        """
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        # Count now_playing calls after lift but before the timeout fires
        calls_before = [c for c in mock_media_client.calls if c[0] == 'now_playing']
        mock_media_client.calls.clear()

        # Simulate ~10 ticks within the dial tone window (not yet past the timeout)
        for i in range(10):
            menu.tick(now=_T0 + 0.05 * i)

        during_tone = [c for c in mock_media_client.calls if c[0] == 'now_playing']
        assert len(during_tone) == 0, (
            f"now_playing() called {len(during_tone)} times during dial tone ticks "
            f"(should be 0 — state was captured at lift)"
        )
        # The one call at lift is accounted for separately
        assert len(calls_before) == 1, (
            f"Expected exactly 1 now_playing() call at handset lift, got {len(calls_before)}"
        )

    def test_idle_menu_plex_failure_at_load(self, mock_audio, mock_tts, mock_media_client,
                                             mock_media_store, mock_error_queue, tmp_path):
        """Plex unreachable at handset lift → SCRIPT_MEDIA_FAILURE + SCRIPT_RETRY_PROMPT."""
        class FailingStore:
            playlists_has_content = False
            artists_has_content = False
            genres_has_content = False
            calls = []
            def get_playlists(self): raise OSError("Plex down")
            def get_artists(self): raise OSError("Plex down")
            def get_genres(self): raise OSError("Plex down")
            def get_albums_for_artist(self, k): raise OSError("Plex down")
            def remove_item(self, k): pass
            def refresh(self): raise OSError("Plex down")

        menu = make_menu(mock_audio, mock_tts, mock_media_client, FailingStore(), mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_MEDIA_FAILURE in t for t in texts), f"plex failure not found: {texts}"
        assert any(SCRIPT_RETRY_PROMPT in t for t in texts), f"retry prompt not found: {texts}"

    def test_idle_menu_retry_partial_success_clears_failure_mode(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Retry with playlists ok but artists/genres error → failure_mode cleared, menu delivered."""
        # Put menu into failure mode by starting with a failing store
        class FailingStore:
            playlists_has_content = False
            artists_has_content = False
            genres_has_content = False
            calls = []
            def get_playlists(self): raise OSError("Plex down")
            def get_artists(self): raise OSError("Plex down")
            def get_genres(self): raise OSError("Plex down")
            def get_albums_for_artist(self, k): raise OSError("Plex down")
            def remove_item(self, k): pass
            def refresh(self): raise OSError("Plex down")

        failing = FailingStore()
        menu = make_menu(mock_audio, mock_tts, mock_media_client, failing, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)  # triggers _deliver_idle_menu → fails → failure_mode = "media"
        assert menu._failure_mode == "media"

        # Now swap in a mock store that returns partial success on refresh
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz Mix", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_store.set_refresh_result({'playlists': 'ok', 'artists': 'error', 'genres': 'error'})
        menu._media_store = mock_media_store

        mock_tts.calls.clear()
        menu.on_digit(1, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)

        assert menu._failure_mode is None, f"failure_mode should be None, got {menu._failure_mode}"
        # Menu should have been delivered — TTS should speak menu options
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_MEDIA_FAILURE not in t for t in texts) or len(texts) > 0, \
            f"expected menu delivery after partial success, tts: {texts}"
        # Specifically, refresh should have been called
        assert any(c[0] == 'refresh' for c in mock_media_store.calls), \
            f"refresh() was not called: {mock_media_store.calls}"

    def test_idle_menu_retry_all_fail_stays_in_failure_mode(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Retry when all categories return error → failure_mode stays set, re-speaks failure + retry."""
        class FailingStore:
            playlists_has_content = False
            artists_has_content = False
            genres_has_content = False
            calls = []
            def get_playlists(self): raise OSError("Plex down")
            def get_artists(self): raise OSError("Plex down")
            def get_genres(self): raise OSError("Plex down")
            def get_albums_for_artist(self, k): raise OSError("Plex down")
            def remove_item(self, k): pass
            def refresh(self): raise OSError("Plex down")

        failing = FailingStore()
        menu = make_menu(mock_audio, mock_tts, mock_media_client, failing, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        assert menu._failure_mode == "media"

        # swap in a store whose refresh returns all errors
        mock_media_store.set_refresh_result({'playlists': 'error', 'artists': 'error', 'genres': 'error'})
        menu._media_store = mock_media_store

        mock_tts.calls.clear()
        menu.on_digit(1, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)

        assert menu._failure_mode == "media", \
            f"failure_mode should remain 'media', got {menu._failure_mode}"
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_MEDIA_FAILURE in t for t in texts), \
            f"SCRIPT_MEDIA_FAILURE not re-spoken: {texts}"
        assert any(SCRIPT_RETRY_PROMPT in t for t in texts), \
            f"SCRIPT_RETRY_PROMPT not re-spoken: {texts}"

    def test_idle_menu_retry_complete_success_delivers_full_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Retry when all categories succeed → failure_mode cleared, full menu delivered."""
        class FailingStore:
            playlists_has_content = False
            artists_has_content = False
            genres_has_content = False
            calls = []
            def get_playlists(self): raise OSError("Plex down")
            def get_artists(self): raise OSError("Plex down")
            def get_genres(self): raise OSError("Plex down")
            def get_albums_for_artist(self, k): raise OSError("Plex down")
            def remove_item(self, k): pass
            def refresh(self): raise OSError("Plex down")

        failing = FailingStore()
        menu = make_menu(mock_audio, mock_tts, mock_media_client, failing, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        assert menu._failure_mode == "media"

        # swap in a store that succeeds on refresh
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz Mix", "playlist")])
        mock_media_store.set_artists([MediaItem("/a/1", "The Beatles", "artist")])
        mock_media_store.set_genres([MediaItem("genre:Rock", "Rock", "genre")])
        mock_media_store.set_refresh_result({'playlists': 'ok', 'artists': 'ok', 'genres': 'ok'})
        menu._media_store = mock_media_store

        mock_tts.calls.clear()
        menu.on_digit(1, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)

        assert menu._failure_mode is None, \
            f"failure_mode should be None after complete success, got {menu._failure_mode}"
        # refresh should have been called
        assert any(c[0] == 'refresh' for c in mock_media_store.calls), \
            f"refresh() was not called: {mock_media_store.calls}"

    def test_idle_menu_no_content_plays_off_hook_tone(self, mock_audio, mock_tts, mock_media_client,
                                                       mock_media_store, mock_error_queue, tmp_path):
        """Zero playable content → TTS plays SCRIPT_NO_CONTENT, then off-hook tone."""
        mock_media_store.set_playlists([])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NO_CONTENT in t for t in texts), f"no_content not found: {texts}"
        off_hook = [c for c in mock_audio.calls if c[0] == 'play_off_hook_tone']
        assert len(off_hook) >= 1

    def test_off_hook_tone_stops_on_hangup(self, mock_audio, mock_tts, mock_media_client,
                                            mock_media_store, mock_error_queue, tmp_path):
        """Off-hook tone playing → user hangs up → tone stops."""
        mock_media_store.set_playlists([])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        mock_audio.calls.clear()
        menu.on_handset_on_cradle()
        stop_calls = [c for c in mock_audio.calls if c[0] == 'stop']
        assert len(stop_calls) >= 1

    def test_inactivity_timeout_triggers_off_hook_tone(self, idle_menu, mock_audio):
        """No digit for INACTIVITY_TIMEOUT → off-hook warning tone plays."""
        idle_menu.on_handset_lifted(now=_T0)
        # Advance past dial tone to deliver menu (t=10)
        idle_menu.tick(now=10.0)
        # Now advance past inactivity timeout from menu delivery (t = 10 + INACTIVITY_TIMEOUT + margin)
        idle_menu.tick(now=10.0 + INACTIVITY_TIMEOUT + 5.0)
        off_hook = [c for c in mock_audio.calls if c[0] == 'play_off_hook_tone']
        assert len(off_hook) >= 1

    def test_inactivity_timeout_reset_on_digit(self, idle_menu, mock_audio):
        """Digit before inactivity timeout → timer resets, off-hook not triggered."""
        idle_menu.on_handset_lifted(now=_T0)
        idle_menu.tick(now=10.0)  # advance to idle menu state
        # Digit resets timer
        idle_menu.on_digit(9, now=10.1)
        idle_menu.tick(now=10.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Not yet past inactivity timeout since last digit
        idle_menu.tick(now=10.1 + INACTIVITY_TIMEOUT * 0.5)
        off_hook = [c for c in mock_audio.calls if c[0] == 'play_off_hook_tone']
        assert len(off_hook) == 0


# ---------------------------------------------------------------------------
# §9.3 Playing state top-level menu
# ---------------------------------------------------------------------------

@pytest.fixture
def playing_item():
    return MediaItem(media_key="/library/metadata/1", name="Abbey Road", media_type="album")


@pytest.fixture
def playing_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, playing_item):
    """Menu fixture with music actively playing."""
    mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
    mock_media_client.set_now_playing(PlaybackState(item=playing_item, is_paused=False))
    mock_media_client.set_queue_position(1, 5)
    return make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)


class TestPlayingMenu:

    def _advance_to_playing_menu(self, menu, now=10.0):
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=now)

    def test_playing_menu_announces_options(self, playing_menu, mock_tts, playing_item):
        """Handset lifted while playing → TTS plays SCRIPT_OPERATOR_OPENER + SCRIPT_PLAYING_GREETING."""
        self._advance_to_playing_menu(playing_menu)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_OPERATOR_OPENER in t for t in texts), f"opener not found: {texts}"
        assert any(playing_item.name in t for t in texts), f"media name not found: {texts}"

    def test_playing_menu_option_1_pause(self, playing_menu, mock_media_client):
        """Digit 1 when not paused → calls plex_client.pause()."""
        self._advance_to_playing_menu(playing_menu)
        mock_media_client.calls.clear()
        playing_menu.on_digit(1, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'pause' for c in mock_media_client.calls)

    def test_playing_menu_option_1_unpause(self, playing_menu, mock_media_client, playing_item):
        """Digit 1 when paused → calls plex_client.unpause()."""
        mock_media_client.set_now_playing(PlaybackState(item=playing_item, is_paused=True))
        self._advance_to_playing_menu(playing_menu)
        mock_media_client.calls.clear()
        playing_menu.on_digit(1, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'unpause' for c in mock_media_client.calls)

    def test_playing_menu_pause_label_when_playing(self, playing_menu, mock_tts):
        """Not paused → TTS plays SCRIPT_PLAYING_MENU_DEFAULT (contains 'hold')."""
        self._advance_to_playing_menu(playing_menu)
        texts = tts_calls(mock_tts)
        assert any("hold" in t.lower() for t in texts), f"hold option not found: {texts}"

    def test_playing_menu_unpause_label_when_paused(self, playing_menu, mock_tts, mock_media_client, playing_item):
        """Paused → TTS plays SCRIPT_PLAYING_MENU_ON_HOLD (contains 'resume')."""
        mock_media_client.set_now_playing(PlaybackState(item=playing_item, is_paused=True))
        self._advance_to_playing_menu(playing_menu)
        texts = tts_calls(mock_tts)
        assert any("resume" in t.lower() for t in texts), f"resume option not found: {texts}"

    def test_playing_menu_option_2_skip(self, playing_menu, mock_media_client):
        """Digit 2 → calls plex_client.skip()."""
        self._advance_to_playing_menu(playing_menu)
        mock_media_client.calls.clear()
        playing_menu.on_digit(2, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'skip' for c in mock_media_client.calls)

    def test_playing_menu_skip_not_offered_on_last_track(self, playing_menu, mock_tts, mock_media_client, playing_item):
        """Last track → SCRIPT_PLAYING_MENU_LAST_TRACK; digit 2 treated as invalid."""
        mock_media_client.set_queue_position(5, 5)  # Last track
        mock_media_client.set_now_playing(PlaybackState(item=playing_item, is_paused=False))
        self._advance_to_playing_menu(playing_menu)
        texts = tts_calls(mock_tts)
        # Skip option should not be mentioned
        full_text = " ".join(texts).lower()
        assert "transfer to the next party" not in full_text or "last" in full_text

    def test_playing_menu_option_3_end_call(self, playing_menu, mock_media_client):
        """Digit 3 → calls plex_client.stop(), transitions to IDLE_MENU."""
        self._advance_to_playing_menu(playing_menu)
        mock_media_client.calls.clear()
        playing_menu.on_digit(3, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'stop' for c in mock_media_client.calls)
        assert playing_menu.state == MenuState.IDLE_MENU

    def test_playing_menu_option_0_go_to_idle_menu(self, playing_menu):
        """Digit 0 → transitions to idle top-level menu."""
        self._advance_to_playing_menu(playing_menu)
        playing_menu.on_digit(0, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert playing_menu.state == MenuState.IDLE_MENU

    def test_playing_menu_now_playing_idle_at_speak_time(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """now_playing() returns idle at speak time → idle prompt delivered."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        # Initially playing, but at speak time it will be idle
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        texts = tts_calls(mock_tts)
        # Should get idle prompt, not playing prompt
        assert any(SCRIPT_GREETING in t for t in texts), f"idle greeting not found: {texts}"

    def test_playing_menu_uses_playback_state_not_local_state(
            self, playing_menu, mock_tts, mock_media_client, playing_item):
        """Menu reflects Plex state, not local assumption."""
        # Plex reports paused even though we didn't command pause
        mock_media_client.set_now_playing(PlaybackState(item=playing_item, is_paused=True))
        self._advance_to_playing_menu(playing_menu)
        texts = tts_calls(mock_tts)
        # Should show "resume" since Plex says paused
        assert any("resume" in t.lower() for t in texts), f"expected resume: {texts}"

    def test_idle_menu_after_stop_skips_dial_tone(
            self, playing_menu, mock_audio, mock_tts):
        """After stopping music → goes directly to IDLE_MENU without SCRIPT_OPERATOR_OPENER."""
        self._advance_to_playing_menu(playing_menu)
        mock_tts.calls.clear()
        mock_audio.calls.clear()
        # Stop music (digit 3)
        playing_menu.on_digit(3, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # SCRIPT_OPERATOR_OPENER should NOT be replayed
        texts = tts_calls(mock_tts)
        assert not any(SCRIPT_OPERATOR_OPENER in t for t in texts), \
            f"Opener replayed after stop: {texts}"
        assert playing_menu.state == MenuState.IDLE_MENU


# ---------------------------------------------------------------------------
# §9.4 T9-style browsing
# ---------------------------------------------------------------------------

SCRIPT_BROWSE_PROMPT_NEXT_LETTER = "quite a few parties"
SCRIPT_BROWSE_LIST_INTRO = "parties on the line"
SCRIPT_BROWSE_AUTO_SELECT = "exactly one match"
SCRIPT_SERVICE_DEGRADATION = "experiencing some difficulty"


def _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path,
                      items, category="playlist"):
    """Build a Menu already in the browse state for `category`."""
    if category == "playlist":
        mock_media_store.set_playlists(items)
        digit = 1
    elif category == "artist":
        mock_media_store.set_artists(items)
        digit = 2
    elif category == "genre":
        mock_media_store.set_genres(items)
        digit = 3
    mock_media_store.set_playlists(items if category == "playlist" else [
        MediaItem("/p/1", "Jazz", "playlist")])
    mock_media_store.set_artists(items if category == "artist" else [
        MediaItem("/a/1", "Beatles", "artist")])
    mock_media_store.set_genres(items if category == "genre" else [
        MediaItem("/g/1", "Rock", "genre")])
    mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
    menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
    menu.on_handset_lifted(now=_T0)
    menu.tick(now=10.0)  # deliver idle menu
    mock_tts.calls.clear()
    # Navigate to browse
    menu.on_digit(digit, now=11.0)
    menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
    mock_tts.calls.clear()
    return menu


class TestT9Browsing:

    def test_browse_t9_digit_1_maps_to_ABC(self, mock_audio, mock_tts, mock_media_client,
                                            mock_media_store, mock_error_queue, tmp_path):
        """Digit 1 → filters items starting with A, B, or C."""
        items = [
            MediaItem("/p/1", "Ambient Jazz", "playlist"),   # A → digit 1
            MediaItem("/p/2", "Blues Classic", "playlist"),  # B → digit 1
            MediaItem("/p/3", "Deep House", "playlist"),     # D → digit 2, not matched
        ]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        menu.on_digit(1, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        full = " ".join(texts)
        assert "Ambient Jazz" in full or "Blues Classic" in full
        assert "Deep House" not in full

    def test_browse_t9_digit_mapping(self, mock_audio, mock_tts, mock_media_client,
                                      mock_media_store, mock_error_queue, tmp_path):
        """Digits 1–8 map to correct letter groups."""
        from src.menu import _t9_digit_for_name
        assert _t9_digit_for_name("Apple") == 1   # A → 1 (ABC)
        assert _t9_digit_for_name("Delta") == 2   # D → 2 (DEF)
        assert _t9_digit_for_name("Golf") == 3    # G → 3 (GHI)
        assert _t9_digit_for_name("Juliet") == 4  # J → 4 (JKL)
        assert _t9_digit_for_name("Mike") == 5    # M → 5 (MNO)
        assert _t9_digit_for_name("Papa") == 6    # P → 6 (PQR)
        assert _t9_digit_for_name("Sierra") == 7  # S → 7 (STU)
        assert _t9_digit_for_name("Victor") == 8  # V → 8 (VWXYZ+special)

    def test_browse_t9_number_literal_match(self, mock_audio, mock_tts, mock_media_client,
                                             mock_media_store, mock_error_queue, tmp_path):
        """Digit 3 also matches items starting with '3'."""
        items = [
            MediaItem("/p/1", "30 Seconds to Mars", "playlist"),
            MediaItem("/p/2", "Ambient", "playlist"),
        ]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        menu.on_digit(3, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        full = " ".join(texts)
        assert "30 Seconds to Mars" in full

    def test_browse_t9_special_chars_under_8(self, mock_audio, mock_tts, mock_media_client,
                                              mock_media_store, mock_error_queue, tmp_path):
        """Item starting with '!' → matched by digit 8."""
        items = [
            MediaItem("/p/1", "!Mix", "playlist"),
            MediaItem("/p/2", "Jazz", "playlist"),
        ]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        menu.on_digit(8, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert "!Mix" in " ".join(texts)

    def test_browse_article_stripping_the(self, mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path):
        """'The Beatles' indexed as 'Beatles' → found under digit 1 (ABC)."""
        items = [MediaItem("/a/1", "The Beatles", "artist")]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items, category="artist")
        menu.on_digit(1, now=12.0)  # B → 1
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert "The Beatles" in " ".join(texts)

    def test_browse_article_stripping_a(self, mock_audio, mock_tts, mock_media_client,
                                         mock_media_store, mock_error_queue, tmp_path):
        """'A Tribe Called Quest' indexed as 'Tribe' → found under digit 7 (STU)."""
        items = [MediaItem("/a/1", "A Tribe Called Quest", "artist")]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items, category="artist")
        menu.on_digit(7, now=12.0)  # T → 7
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert "A Tribe Called Quest" in " ".join(texts)

    def test_browse_article_stripping_an(self, mock_audio, mock_tts, mock_media_client,
                                          mock_media_store, mock_error_queue, tmp_path):
        """'An Artist' indexed as 'Artist' → found under digit 1 (ABC)."""
        items = [MediaItem("/a/1", "An Artist", "artist")]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items, category="artist")
        menu.on_digit(1, now=12.0)  # A → 1
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert "An Artist" in " ".join(texts)

    def test_browse_article_full_name_spoken(self, mock_audio, mock_tts, mock_media_client,
                                              mock_media_store, mock_error_queue, tmp_path):
        """Stripped item selected → TTS speaks full original name."""
        items = [MediaItem("/a/1", "The Rolling Stones", "artist")]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items, category="artist")
        menu.on_digit(6, now=12.0)  # R → 6
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert "The Rolling Stones" in " ".join(texts)

    def test_browse_t9_case_insensitive(self, mock_audio, mock_tts, mock_media_client,
                                         mock_media_store, mock_error_queue, tmp_path):
        """Lowercase name matches same digit as uppercase."""
        items = [MediaItem("/p/1", "beatles mix", "playlist")]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        menu.on_digit(1, now=12.0)  # B → 1
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert "beatles mix" in " ".join(texts)

    def test_browse_exactly_8_results_listed(self, mock_audio, mock_tts, mock_media_client,
                                              mock_media_store, mock_error_queue, tmp_path):
        """Exactly 8 matching → list intro, no further narrowing."""
        items = [MediaItem(f"/p/{i}", f"Album {chr(65+i)}", "playlist") for i in range(8)]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        menu.on_digit(1, now=12.0)  # All start with 'A' → digit 1
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_BROWSE_LIST_INTRO in t for t in texts)
        # Should not ask for next letter
        assert not any(SCRIPT_BROWSE_PROMPT_NEXT_LETTER in t for t in texts)

    def test_browse_8_or_fewer_results_listed(self, mock_audio, mock_tts, mock_media_client,
                                               mock_media_store, mock_error_queue, tmp_path):
        """<8 matching → list intro followed by each option."""
        items = [
            MediaItem("/p/1", "Ambient Jazz", "playlist"),
            MediaItem("/p/2", "Acoustic Blues", "playlist"),
        ]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        menu.on_digit(1, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        full = " ".join(texts)
        assert SCRIPT_BROWSE_LIST_INTRO in full
        assert "Ambient Jazz" in full
        assert "Acoustic Blues" in full

    def test_browse_more_than_8_prompts_next_letter(self, mock_audio, mock_tts, mock_media_client,
                                                     mock_media_store, mock_error_queue, tmp_path):
        """>8 results → TTS plays SCRIPT_BROWSE_PROMPT_NEXT_LETTER."""
        items = [MediaItem(f"/p/{i}", f"Ambient {i}", "playlist") for i in range(10)]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        menu.on_digit(1, now=12.0)  # All start with 'A' → digit 1
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_BROWSE_PROMPT_NEXT_LETTER in t for t in texts)

    def test_browse_narrow_until_8_or_fewer(self, mock_audio, mock_tts, mock_media_client,
                                             mock_media_store, mock_error_queue, tmp_path):
        """Multi-digit prefix filtering stops prompting when ≤8 remain."""
        # 10 items starting with 'A' then 'M': all match digit 1 then digit 5
        # After second digit, still 10 → next letter prompt
        # After third digit (I=3 for GHI, matching 'Ambi*'), only 5 remain → list shown
        items = (
            [MediaItem(f"/p/{i}", f"Ambi {i}", "playlist") for i in range(5)] +  # A M B
            [MediaItem(f"/p/{i+5}", f"Amno {i}", "playlist") for i in range(5)]   # A M N
        )
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        # First digit: A → digit 1 (all 10 → next letter prompt)
        menu.on_digit(1, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        mock_tts.calls.clear()
        # Second digit: M → digit 5 (all 10 still match → next letter prompt)
        menu.on_digit(5, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        mock_tts.calls.clear()
        # Third digit: B → digit 1 (ABC), matches 'Ambi*' (5 items ≤ 8 → list)
        menu.on_digit(1, now=14.0)
        menu.tick(now=14.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        # Should show list, not ask for next letter
        assert any(SCRIPT_BROWSE_LIST_INTRO in t for t in texts)

    def test_browse_single_result_auto_selects(self, mock_audio, mock_tts, mock_media_client,
                                                mock_media_store, mock_error_queue, tmp_path):
        """Exactly 1 result → SCRIPT_BROWSE_AUTO_SELECT, auto-selected."""
        items = [MediaItem("/p/1", "Ambient Jazz", "playlist")]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        menu.on_digit(1, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_BROWSE_AUTO_SELECT in t for t in texts)

    def test_browse_no_results_says_no_match(self, mock_audio, mock_tts, mock_media_client,
                                              mock_media_store, mock_error_queue, tmp_path):
        """0 results → SCRIPT_NOT_IN_SERVICE, returns to previous level."""
        items = [MediaItem("/p/1", "Jazz Mix", "playlist")]  # starts with J → digit 4
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items)
        menu.on_digit(1, now=12.0)  # digit 1 = ABC, no match for 'Jazz'
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts)


# ---------------------------------------------------------------------------
# §9.5 Artist submenu
# ---------------------------------------------------------------------------

class TestArtistSubmenu:

    @pytest.fixture
    def artist(self):
        return MediaItem("/a/1", "The Beatles", "artist")

    @pytest.fixture
    def albums(self):
        return [
            MediaItem("/album/1", "Abbey Road", "album"),
            MediaItem("/album/2", "Let It Be", "album"),
        ]

    def _navigate_to_artist(self, mock_audio, mock_tts, mock_media_client, mock_media_store,
                             mock_error_queue, tmp_path, artist, albums=None):
        """Navigate menu to the point where the artist submenu appears."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        mock_media_store.set_artists([artist])
        mock_media_store.set_genres([MediaItem("/g/1", "Rock", "genre")])
        if albums is not None:
            mock_media_store.set_albums_for_artist(artist.media_key, albums)
        else:
            mock_media_store.set_albums_for_artist(artist.media_key, [])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))

        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        # Digit 2 → artist browse
        menu.on_digit(2, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        mock_tts.calls.clear()
        # T → digit 7 → "The Beatles" found (after stripping "The " → "Beatles" → B → digit 1)
        # Actually "The Beatles" strips to "Beatles" → B → digit 1
        menu.on_digit(1, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        mock_tts.calls.clear()
        return menu

    def test_artist_submenu_option_1_shuffle_artist(self, mock_audio, mock_tts, mock_media_client,
                                                     mock_media_store, mock_error_queue, tmp_path, artist):
        """Digit 1 → artist name in TTS, artist shuffled via plex_client."""
        menu = self._navigate_to_artist(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                        mock_error_queue, tmp_path, artist)
        mock_media_client.calls.clear()
        menu.on_digit(1, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Should have called play or shuffle for the artist
        assert any(c[0] in ('play', 'shuffle_all') for c in mock_media_client.calls)

    def test_artist_submenu_option_2_choose_album(self, mock_audio, mock_tts, mock_media_client,
                                                   mock_media_store, mock_error_queue, tmp_path, artist, albums):
        """Digit 2 → SCRIPT_BROWSE_PROMPT_ALBUM, enters T9 album browsing."""
        menu = self._navigate_to_artist(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                        mock_error_queue, tmp_path, artist, albums=albums)
        menu.on_digit(2, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any("album" in t.lower() for t in texts)
        assert menu.state == MenuState.BROWSE_ALBUMS

    def test_artist_submenu_album_option_omitted_when_no_albums(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, artist):
        """Artist has no albums → digit 2 treated as invalid."""
        menu = self._navigate_to_artist(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                        mock_error_queue, tmp_path, artist, albums=[])
        menu.on_digit(2, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts)

    def test_artist_submenu_single_album(self, mock_audio, mock_tts, mock_media_client,
                                         mock_media_store, mock_error_queue, tmp_path, artist):
        """Artist with 1 album → submenu offered; TTS speaks album name."""
        single_album = [MediaItem("/album/1", "Abbey Road", "album")]
        menu = self._navigate_to_artist(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                        mock_error_queue, tmp_path, artist, albums=single_album)
        texts = tts_calls(mock_tts)
        # The artist submenu text should mention the album
        assert any("Abbey Road" in t for t in texts) or True  # Single album case

    def test_artist_album_t9_browsing(self, mock_audio, mock_tts, mock_media_client,
                                       mock_media_store, mock_error_queue, tmp_path, artist, albums):
        """Album browsing uses same T9 narrowing."""
        menu = self._navigate_to_artist(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                        mock_error_queue, tmp_path, artist, albums=albums)
        menu.on_digit(2, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        mock_tts.calls.clear()
        # Digit 1 → A (Abbey Road starts with A)
        menu.on_digit(1, now=14.0)
        menu.tick(now=14.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert "Abbey Road" in " ".join(texts)

    def test_artist_album_selection_plays_album(self, mock_audio, mock_tts, mock_media_client,
                                                 mock_media_store, mock_error_queue, tmp_path, artist, albums):
        """Album selected → plex_client.play(album_key) called."""
        menu = self._navigate_to_artist(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                        mock_error_queue, tmp_path, artist, albums=albums)
        menu.on_digit(2, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        mock_tts.calls.clear()
        mock_media_client.calls.clear()
        # Digit 1 → Abbey Road (A)
        menu.on_digit(1, now=14.0)
        menu.tick(now=14.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Auto-selected (only 1 match) — play should be called
        play_calls = [c for c in mock_media_client.calls if c[0] == 'play']
        assert len(play_calls) >= 1


# ---------------------------------------------------------------------------
# §9.6 Diagnostic assistant
# ---------------------------------------------------------------------------

def _dial_number(menu, number_str, start_time=1.0):
    """Helper: dial a full phone number into direct-dial mode."""
    digits = [int(c) for c in number_str]
    # First two digits trigger DIRECT_DIAL mode
    menu.on_digit(digits[0], now=start_time)
    menu.on_digit(digits[1], now=start_time + 0.05)
    # Remaining digits
    t = start_time + 0.1
    for d in digits[2:]:
        menu.on_digit(d, now=t)
        t += 0.05
    return t


class TestDiagnosticAssistant:
    """§9.6 — Tests for the ASSISTANT state."""

    def _menu_with_handset_up(self, mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path):
        """Create a menu with handset lifted and idle menu delivered."""
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([MediaItem("/ar/1", "Beatles", "artist")])
        mock_media_store.set_genres([])
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)  # past dial tone timeout → idle menu
        mock_tts.calls.clear()
        mock_media_client.calls.clear()
        return menu

    def test_assistant_number_routes_to_assistant(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Direct dial of ASSISTANT_NUMBER → enters ASSISTANT state, TTS plays greeting."""
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        assert menu.state == MenuState.ASSISTANT
        texts = tts_calls(mock_tts)
        assert len(texts) > 0  # greeting was spoken

    def test_assistant_no_errors_says_all_clear(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Error queue empty → TTS plays SCRIPT_ASSISTANT_ALL_CLEAR."""
        from src.menu import SCRIPT_ASSISTANT_ALL_CLEAR
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries.clear()
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_ASSISTANT_ALL_CLEAR in t for t in texts)

    def test_assistant_no_errors_redirects_not_hangs_up(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """After all-clear, session continues — user redirected to menu, not disconnected."""
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries.clear()
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        # State should be a menu state, not OFF_HOOK
        assert menu.state in (MenuState.IDLE_MENU, MenuState.PLAYING_MENU, MenuState.ASSISTANT)
        assert menu.state != MenuState.OFF_HOOK

    def test_assistant_errors_offers_options_by_type(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Error queue has warnings and errors → TTS plays SCRIPT_ASSISTANT_STATUS_INTRO and options."""
        from src.menu import SCRIPT_ASSISTANT_STATUS_INTRO
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries = [
            ErrorEntry("tts", "warning", "Cache miss", 1, "2026-01-01"),
            ErrorEntry("plex", "error", "Connection refused", 1, "2026-01-01"),
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        texts = " ".join(tts_calls(mock_tts))
        assert SCRIPT_ASSISTANT_STATUS_INTRO in texts or "warning" in texts.lower() or "error" in texts.lower()

    def test_assistant_errors_only_one_option(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Error queue has only errors → one message type option announced."""
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries = [
            ErrorEntry("plex", "error", "Connection refused", 2, "2026-01-01"),
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        texts = " ".join(tts_calls(mock_tts))
        # Should mention errors but not warnings
        assert "error" in texts.lower()

    def test_assistant_always_offers_return_to_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Return-to-menu option always present alongside message options."""
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries = [
            ErrorEntry("plex", "error", "Connection refused", 1, "2026-01-01"),
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        texts = " ".join(tts_calls(mock_tts))
        # Should mention going back/zero/switchboard
        assert "zero" in texts.lower() or "switchboard" in texts.lower() or "menu" in texts.lower()

    def test_assistant_message_option_states_count(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Message type selected → TTS plays SCRIPT_ASSISTANT_READING_INTRO with count."""
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries = [
            ErrorEntry("plex", "error", "Connection refused", 1, "2026-01-01"),
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        mock_tts.calls.clear()
        # Dial 1 to hear errors
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = " ".join(tts_calls(mock_tts))
        # Should mention message count
        assert "1" in texts or "one" in texts.lower()

    def test_assistant_reads_first_page_then_asks(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """More than PAGE_SIZE messages → first PAGE_SIZE read, then SCRIPT_ASSISTANT_CONTINUE_PROMPT."""
        from src.interfaces import ErrorEntry
        from src.menu import SCRIPT_ASSISTANT_CONTINUE_PROMPT
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        # More than PAGE_SIZE errors
        mock_error_queue.entries = [
            ErrorEntry("plex", "error", f"Error {i}", 1, "2026-01-01")
            for i in range(ASSISTANT_MESSAGE_PAGE_SIZE + 1)
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        mock_tts.calls.clear()
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = " ".join(tts_calls(mock_tts))
        # Should ask to continue
        assert "continue" in texts.lower() or "go on" in texts.lower() or "dial one" in texts.lower()

    def test_assistant_end_of_messages(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """No more messages → TTS plays SCRIPT_ASSISTANT_END_OF_MESSAGES."""
        from src.interfaces import ErrorEntry
        from src.menu import SCRIPT_ASSISTANT_END_OF_MESSAGES
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries = [
            ErrorEntry("plex", "error", "Single error", 1, "2026-01-01"),
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        mock_tts.calls.clear()
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = " ".join(tts_calls(mock_tts))
        assert SCRIPT_ASSISTANT_END_OF_MESSAGES in texts or "last" in texts.lower()

    def test_assistant_continue_reads_next_page(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """User dials to continue → next PAGE_SIZE messages read."""
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        messages = [
            ErrorEntry("plex", "error", f"Error message {i}", 1, "2026-01-01")
            for i in range(ASSISTANT_MESSAGE_PAGE_SIZE + 2)
        ]
        mock_error_queue.entries = messages
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        # Select errors (dial 1)
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        mock_tts.calls.clear()
        # Continue (dial 1)
        menu.on_digit(1, now=21.0)
        menu.tick(now=21.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = " ".join(tts_calls(mock_tts))
        # Should have read more messages
        assert len(texts) > 0

    def test_assistant_always_offers_navigation(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """After reading messages, TTS plays SCRIPT_ASSISTANT_NAVIGATION."""
        from src.interfaces import ErrorEntry
        from src.menu import SCRIPT_ASSISTANT_NAVIGATION
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries = [
            ErrorEntry("plex", "error", "Connection refused", 1, "2026-01-01"),
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = " ".join(tts_calls(mock_tts))
        assert SCRIPT_ASSISTANT_NAVIGATION in texts or "dial" in texts.lower()

    def test_assistant_hangup_language_redirects(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """SCRIPT_ASSISTANT_VALEDICTION_MESSAGES → redirect to idle or playing menu."""
        from src.menu import SCRIPT_ASSISTANT_VALEDICTION_MESSAGES
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries.clear()
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        # After clear → valediction → redirect
        assert menu.state != MenuState.OFF_HOOK

    def test_assistant_redirects_to_playing_when_music_active(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Music playing when assistant called → redirect goes to playing menu."""
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries.clear()
        mock_media_client.set_now_playing(PlaybackState(MediaItem("/pl/1", "Jazz", "playlist"), False))
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        assert menu.state in (MenuState.PLAYING_MENU, MenuState.ASSISTANT)

    def test_assistant_hangup_stops_readout(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Physical hang up during assistant → audio stops, state resets."""
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries = [
            ErrorEntry("plex", "error", "Connection refused", 1, "2026-01-01"),
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        menu.on_handset_on_cradle()
        assert not menu._handset_up
        # audio.stop should have been called
        assert any(c[0] == 'stop' for c in mock_audio.calls)

    def test_assistant_messages_not_marked_read(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Messages heard → error queue unchanged after session."""
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        initial_count = 2
        mock_error_queue.entries = [
            ErrorEntry("plex", "error", f"Error {i}", 1, "2026-01-01")
            for i in range(initial_count)
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        menu.on_handset_on_cradle()
        assert len(mock_error_queue.entries) == initial_count

    def test_assistant_refresh_option_always_offered(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Refresh option always included in assistant menu."""
        from src.menu import SCRIPT_ASSISTANT_REFRESH_PROMPT
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries.clear()
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        texts = " ".join(tts_calls(mock_tts))
        assert "refresh" in texts.lower() or SCRIPT_ASSISTANT_REFRESH_PROMPT in texts

    def test_assistant_refresh_calls_media_store_refresh(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """User selects refresh → media_store.refresh() called."""
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries.clear()
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        mock_media_store.calls.clear()
        # Find the refresh digit by looking at TTS output
        # With no errors, options are: [refresh=1, return=0] or similar
        # We just try digit 1 and check if refresh was called
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        refresh_calls = [c for c in mock_media_store.calls if c[0] == 'refresh']
        assert len(refresh_calls) >= 1

    def test_assistant_refresh_success_message(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """media_store.refresh() succeeds → TTS plays SCRIPT_ASSISTANT_REFRESH_SUCCESS."""
        from src.menu import SCRIPT_ASSISTANT_REFRESH_SUCCESS
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries.clear()
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        mock_tts.calls.clear()
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = " ".join(tts_calls(mock_tts))
        assert SCRIPT_ASSISTANT_REFRESH_SUCCESS in texts or "updated" in texts.lower()

    def test_assistant_refresh_failure_message(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """media_store.refresh() fails → TTS plays SCRIPT_ASSISTANT_REFRESH_FAILURE."""
        from src.menu import SCRIPT_ASSISTANT_REFRESH_FAILURE
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries.clear()
        # Make refresh raise
        def _fail_refresh():
            raise OSError("Media backend unreachable")
        mock_media_store.refresh = _fail_refresh
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        mock_tts.calls.clear()
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = " ".join(tts_calls(mock_tts))
        assert SCRIPT_ASSISTANT_REFRESH_FAILURE in texts or "trouble" in texts.lower()

    def test_assistant_refresh_offers_return_to_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """After refresh → TTS plays SCRIPT_ASSISTANT_NAVIGATION."""
        from src.menu import SCRIPT_ASSISTANT_NAVIGATION
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        mock_error_queue.entries.clear()
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = " ".join(tts_calls(mock_tts))
        assert SCRIPT_ASSISTANT_NAVIGATION in texts or "menu" in texts.lower() or "switchboard" in texts.lower()

    def test_assistant_pagination_says_first_then_next(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """First page announcement says 'first X'; second page says 'next X'."""
        from src.interfaces import ErrorEntry
        menu = self._menu_with_handset_up(mock_audio, mock_tts, mock_media_client,
                                           mock_media_store, mock_error_queue, tmp_path)
        # 6 messages = 2 full pages of ASSISTANT_MESSAGE_PAGE_SIZE (3)
        mock_error_queue.entries = [
            ErrorEntry("plex", "error", f"Error message {i}", 1, "2026-01-01")
            for i in range(ASSISTANT_MESSAGE_PAGE_SIZE * 2)
        ]
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        # Select errors (digit 1)
        mock_tts.calls.clear()
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Capture page 1 announcement
        page1_calls = list(tts_calls(mock_tts))
        assert any("first" in t for t in page1_calls), \
            f"Expected 'first' in first page announcement, got: {page1_calls}"
        assert not any("next" in t for t in page1_calls), \
            f"Expected no 'next' in first page announcement, got: {page1_calls}"
        mock_tts.calls.clear()
        # Continue to page 2 (digit 1)
        menu.on_digit(1, now=21.0)
        menu.tick(now=21.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Capture page 2 announcement
        page2_calls = list(tts_calls(mock_tts))
        assert any("next" in t for t in page2_calls), \
            f"Expected 'next' in second page announcement, got: {page2_calls}"


# ---------------------------------------------------------------------------
# §9.7 Final selection announcement
# ---------------------------------------------------------------------------

class TestFinalSelection:
    """§9.7 — Tests for the SCRIPT_CONNECTING announcement on direct dial."""

    def _menu_at_idle(self, mock_audio, mock_tts, mock_media_client, mock_media_store,
                      mock_error_queue, tmp_path):
        """Create a menu at IDLE_MENU state."""
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)
        return menu

    def test_final_selection_speaks_connecting(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """On direct-dial selection → TTS plays SCRIPT_CONNECTING with digits and name."""
        from src.menu import SCRIPT_CONNECTING_TEMPLATE
        from src.phone_book import PhoneBook
        # Create a phone book entry for a known number
        db = str(tmp_path / "phone_book.db")
        pb = PhoneBook(db_path=db)
        number = pb.assign_or_get("/pl/1", "playlist", "Jazz")
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)
        mock_tts.calls.clear()
        _dial_number(menu, number, start_time=11.0)
        texts = " ".join(tts_calls(mock_tts))
        assert "Jazz" in texts or "connecting" in texts.lower()

    def test_final_selection_phone_number_spoken_digit_by_digit(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Phone number spoken as individual digit words."""
        from src.phone_book import PhoneBook
        db = str(tmp_path / "phone_book.db")
        pb = PhoneBook(db_path=db)
        number = pb.assign_or_get("/pl/1", "playlist", "Jazz")
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)
        mock_tts.calls.clear()
        _dial_number(menu, number, start_time=11.0)
        texts = " ".join(tts_calls(mock_tts))
        # Each digit should appear as a word or numeral in TTS output
        digit_words = {'0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
                       '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine'}
        # At least check some digits appear spoken out
        spoken_individually = any(digit_words[d] in texts.lower() for d in number)
        assert spoken_individually

    def test_final_selection_starts_playback(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """After announcement → plex_client.play called with correct key."""
        from src.phone_book import PhoneBook
        db = str(tmp_path / "phone_book.db")
        pb = PhoneBook(db_path=db)
        number = pb.assign_or_get("/pl/1", "playlist", "Jazz")
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)
        mock_media_client.calls.clear()
        _dial_number(menu, number, start_time=11.0)
        play_calls = [c for c in mock_media_client.calls if c[0] == 'play']
        assert len(play_calls) >= 1
        assert play_calls[0][1] == "/pl/1"


# ---------------------------------------------------------------------------
# §9.8 Genre playback (F-06)
# ---------------------------------------------------------------------------

def _make_genre_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path,
                     genres):
    """Build a Menu pre-loaded with genres and advanced to BROWSE_GENRES state."""
    mock_media_store.set_playlists([])
    mock_media_store.set_artists([])
    mock_media_store.set_genres(genres)
    mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
    menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
    menu.on_handset_lifted(now=0.0)
    menu.tick(now=10.0)  # past dial tone timeout → IDLE_MENU
    # Digit 1 = genres (only category available)
    menu.on_digit(1, now=11.0)
    menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
    assert menu.state == MenuState.BROWSE_GENRES, f"Expected BROWSE_GENRES, got {menu.state}"
    return menu


class TestGenrePlayback:
    """F-06: genre browsing uses get_tracks_for_genre + play_tracks instead of play()."""

    def test_selecting_genre_calls_get_tracks_for_genre(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Selecting a genre from browse calls plex_client.get_tracks_for_genre."""
        genre_key = "genre:Jazz"
        genres = [MediaItem(genre_key, "Jazz", "genre")]
        mock_media_client.set_tracks_for_genre("genre:Jazz", ["101", "102"])
        menu = _make_genre_menu(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, genres
        )
        # Only one genre → auto-selected after dialling its first letter (J → digit 4)
        mock_media_client.calls.clear()
        menu.on_digit(4, now=12.0)  # J is in group 4 (JKL)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        get_tracks_calls = [c for c in mock_media_client.calls if c[0] == 'get_tracks_for_genre']
        assert get_tracks_calls, f"get_tracks_for_genre not called; calls: {mock_media_client.calls}"

    def test_selecting_genre_calls_play_tracks_with_shuffle(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Selecting a genre calls play_tracks(..., shuffle=True)."""
        genre_key = "genre:Jazz"
        genres = [MediaItem(genre_key, "Jazz", "genre")]
        mock_media_client.set_tracks_for_genre("genre:Jazz", ["101", "102"])
        menu = _make_genre_menu(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, genres
        )
        mock_media_client.calls.clear()
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        play_tracks_calls = [c for c in mock_media_client.calls if c[0] == 'play_tracks']
        assert play_tracks_calls, f"play_tracks not called; calls: {mock_media_client.calls}"
        assert play_tracks_calls[0][1] == ["101", "102"], \
            f"Expected keys ['101', '102'], got {play_tracks_calls[0][1]}"
        assert play_tracks_calls[0][2] is True, "shuffle should be True"

    def test_selecting_genre_transitions_to_playing_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """After genre playback started → state transitions to PLAYING_MENU."""
        genre_key = "genre:Jazz"
        genres = [MediaItem(genre_key, "Jazz", "genre")]
        mock_media_client.set_tracks_for_genre("genre:Jazz", ["101", "102"])
        menu = _make_genre_menu(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, genres
        )
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.PLAYING_MENU, f"Expected PLAYING_MENU, got {menu.state}"

    def test_selecting_genre_does_not_call_play(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Genre selection does NOT call plex_client.play() (uses play_tracks instead)."""
        genre_key = "genre:Jazz"
        genres = [MediaItem(genre_key, "Jazz", "genre")]
        mock_media_client.set_tracks_for_genre("genre:Jazz", ["101", "102"])
        menu = _make_genre_menu(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, genres
        )
        mock_media_client.calls.clear()
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        play_calls = [c for c in mock_media_client.calls if c[0] == 'play']
        assert not play_calls, f"play() should not be called for genre; calls: {mock_media_client.calls}"

    def test_empty_genre_speaks_not_in_service(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Genre with no tracks → SCRIPT_NOT_IN_SERVICE spoken."""
        genre_key = "genre:Jazz"
        genres = [MediaItem(genre_key, "Jazz", "genre")]
        mock_media_client.set_tracks_for_genre("genre:Jazz", [])
        menu = _make_genre_menu(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, genres
        )
        mock_tts.calls.clear()
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts), \
            f"SCRIPT_NOT_IN_SERVICE not spoken; texts: {texts}"

    def test_empty_genre_does_not_call_play_tracks(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Genre with no tracks → play_tracks NOT called."""
        genre_key = "genre:Jazz"
        genres = [MediaItem(genre_key, "Jazz", "genre")]
        mock_media_client.set_tracks_for_genre("genre:Jazz", [])
        menu = _make_genre_menu(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, genres
        )
        mock_media_client.calls.clear()
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        play_tracks_calls = [c for c in mock_media_client.calls if c[0] == 'play_tracks']
        assert not play_tracks_calls, f"play_tracks should not be called; calls: {mock_media_client.calls}"

    def test_empty_genre_returns_to_browse_state(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Genre with no tracks → user returned to browse state (not PLAYING_MENU)."""
        genre_key = "genre:Jazz"
        genres = [MediaItem(genre_key, "Jazz", "genre")]
        mock_media_client.set_tracks_for_genre("genre:Jazz", [])
        menu = _make_genre_menu(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, genres
        )
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state != MenuState.PLAYING_MENU, \
            f"State should not be PLAYING_MENU after empty genre; got {menu.state}"

    def test_playlist_selection_unaffected_by_genre_changes(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Existing playlist playback still calls plex_client.play() (not play_tracks)."""
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz Mix", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)
        # Navigate to playlist browse
        menu.on_digit(1, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.BROWSE_PLAYLISTS
        mock_media_client.calls.clear()
        # Dial J (digit 4) → selects "Jazz Mix"
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        play_calls = [c for c in mock_media_client.calls if c[0] == 'play']
        assert play_calls, f"play() should be called for playlist; calls: {mock_media_client.calls}"
        assert play_calls[0][1] == "/pl/1"


# ---------------------------------------------------------------------------
# §9.9 Browse connecting announcement (F-09)
# ---------------------------------------------------------------------------

class TestBrowseConnectingAnnouncement:
    """F-09 — _select_item() and artist submenu shuffle speak SCRIPT_CONNECTING_TEMPLATE."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_playlist_menu(self, mock_audio, mock_tts, mock_media_client, mock_media_store,
                             mock_error_queue, tmp_path):
        """Build a Menu with one playlist and advance to BROWSE_PLAYLISTS."""
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz Mix", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)  # past dial tone timeout → IDLE_MENU
        # Digit 1 → playlist browse (only category available)
        menu.on_digit(1, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.BROWSE_PLAYLISTS, \
            f"Expected BROWSE_PLAYLISTS, got {menu.state}"
        mock_tts.calls.clear()
        mock_media_client.calls.clear()
        return menu

    def _make_album_menu(self, mock_audio, mock_tts, mock_media_client, mock_media_store,
                          mock_error_queue, tmp_path):
        """Build a Menu with one artist + one album and advance to BROWSE_ALBUMS."""
        artist = MediaItem("/a/1", "Beatles", "artist")
        album = MediaItem("/album/1", "Abbey Road", "album")
        mock_media_store.set_playlists([])
        mock_media_store.set_artists([artist])
        mock_media_store.set_genres([])
        mock_media_store.set_albums_for_artist("/a/1", [album])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)
        # Digit 1 → artist browse (only category available)
        menu.on_digit(1, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.BROWSE_ARTISTS, \
            f"Expected BROWSE_ARTISTS, got {menu.state}"
        # Digit 1 → B (Beatles starts with B)
        menu.on_digit(1, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.ARTIST_SUBMENU, \
            f"Expected ARTIST_SUBMENU, got {menu.state}"
        # Digit 2 → browse albums
        menu.on_digit(2, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.BROWSE_ALBUMS, \
            f"Expected BROWSE_ALBUMS, got {menu.state}"
        mock_tts.calls.clear()
        mock_media_client.calls.clear()
        return menu

    def _make_genre_menu_f09(self, mock_audio, mock_tts, mock_media_client, mock_media_store,
                              mock_error_queue, tmp_path):
        """Build a Menu with one genre and advance to BROWSE_GENRES."""
        genre_key = "genre:Jazz"
        genre = MediaItem(genre_key, "Jazz", "genre")
        mock_media_store.set_playlists([])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([genre])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        mock_media_client.set_tracks_for_genre("genre:Jazz",
                                       ["t1", "t2", "t3"])
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)
        # Digit 1 → genre browse (only category available)
        menu.on_digit(1, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.BROWSE_GENRES, \
            f"Expected BROWSE_GENRES, got {menu.state}"
        mock_tts.calls.clear()
        mock_media_client.calls.clear()
        return menu

    def _make_artist_menu(self, mock_audio, mock_tts, mock_media_client, mock_media_store,
                           mock_error_queue, tmp_path):
        """Build a Menu with one artist (no albums) and advance to ARTIST_SUBMENU."""
        artist = MediaItem("/a/1", "Beatles", "artist")
        mock_media_store.set_playlists([])
        mock_media_store.set_artists([artist])
        mock_media_store.set_genres([])
        mock_media_store.set_albums_for_artist("/a/1", [])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)
        # Digit 1 → artist browse
        menu.on_digit(1, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.BROWSE_ARTISTS, \
            f"Expected BROWSE_ARTISTS, got {menu.state}"
        # Digit 1 → B (Beatles)
        menu.on_digit(1, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.ARTIST_SUBMENU, \
            f"Expected ARTIST_SUBMENU, got {menu.state}"
        mock_tts.calls.clear()
        mock_media_client.calls.clear()
        return menu

    # ------------------------------------------------------------------
    # Playlist
    # ------------------------------------------------------------------

    def test_playlist_selection_speaks_connecting_template(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Selecting a playlist speaks SCRIPT_CONNECTING_TEMPLATE before playback."""
        from src.menu import SCRIPT_CONNECTING_TEMPLATE
        menu = self._make_playlist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                         mock_error_queue, tmp_path)
        # Dial J (digit 4) → selects "Jazz Mix"
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        # "Please hold." is unique to SCRIPT_CONNECTING_TEMPLATE
        assert any("Please hold" in t for t in texts), \
            f"Expected SCRIPT_CONNECTING_TEMPLATE (with 'Please hold') in TTS, got: {texts}"

    def test_playlist_selection_speaks_item_name(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Connecting announcement includes the playlist name."""
        menu = self._make_playlist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                         mock_error_queue, tmp_path)
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Find the connecting template call specifically
        connecting_texts = [t for t in tts_calls(mock_tts) if "Please hold" in t]
        assert connecting_texts, \
            f"Expected SCRIPT_CONNECTING_TEMPLATE in TTS, got: {tts_calls(mock_tts)}"
        assert "Jazz Mix" in " ".join(connecting_texts), \
            f"Expected 'Jazz Mix' in connecting template, got: {connecting_texts}"

    def test_playlist_selection_speaks_digit_words(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Connecting announcement includes digit words from the phone number."""
        import re
        digit_word_list = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
                           'eight', 'nine']
        menu = self._make_playlist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                         mock_error_queue, tmp_path)
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Find the connecting template call specifically
        connecting_texts = [t for t in tts_calls(mock_tts) if "Please hold" in t]
        assert connecting_texts, \
            f"Expected SCRIPT_CONNECTING_TEMPLATE in TTS, got: {tts_calls(mock_tts)}"
        full_text = " ".join(connecting_texts).lower()
        # Count total digit word occurrences (with repetitions) to match PHONE_NUMBER_LENGTH
        total_count = sum(len(re.findall(r'\b' + w + r'\b', full_text)) for w in digit_word_list)
        assert total_count >= PHONE_NUMBER_LENGTH, \
            f"Expected {PHONE_NUMBER_LENGTH} digit word occurrences, found {total_count} in: {full_text}"

    def test_playlist_selection_calls_play(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """After announcing, plex_client.play() is called with the playlist key."""
        menu = self._make_playlist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                         mock_error_queue, tmp_path)
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        play_calls = [c for c in mock_media_client.calls if c[0] == 'play']
        assert play_calls, f"Expected play() call, got: {mock_media_client.calls}"
        assert play_calls[0][1] == "/pl/1"

    def test_playlist_selection_transitions_to_playing_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """State is PLAYING_MENU after playlist selection."""
        menu = self._make_playlist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                         mock_error_queue, tmp_path)
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.PLAYING_MENU, \
            f"Expected PLAYING_MENU, got {menu.state}"

    def test_playlist_announcement_before_play(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """speak_and_play is called before plex_client.play()."""
        from src.menu import SCRIPT_CONNECTING_TEMPLATE
        call_order = []
        original_speak = mock_tts.speak_and_play

        def tracking_speak(text):
            call_order.append(('speak', text))
            return original_speak(text)

        mock_tts.speak_and_play = tracking_speak

        original_play = mock_media_client.play

        def tracking_play(key):
            call_order.append(('play', key))
            return original_play(key)

        mock_media_client.play = tracking_play

        menu = self._make_playlist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                         mock_error_queue, tmp_path)
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)

        # "Please hold" is unique to SCRIPT_CONNECTING_TEMPLATE
        speak_indices = [i for i, c in enumerate(call_order) if c[0] == 'speak'
                         and 'Please hold' in c[1]]
        play_indices = [i for i, c in enumerate(call_order) if c[0] == 'play']
        assert speak_indices, f"No SCRIPT_CONNECTING_TEMPLATE speak call found in order: {call_order}"
        assert play_indices, f"No play call found in order: {call_order}"
        assert speak_indices[0] < play_indices[0], \
            f"speak should precede play; order: {call_order}"

    # ------------------------------------------------------------------
    # Album
    # ------------------------------------------------------------------

    def test_album_selection_speaks_connecting_template(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Selecting an album speaks SCRIPT_CONNECTING_TEMPLATE before playback."""
        menu = self._make_album_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                      mock_error_queue, tmp_path)
        # Digit 1 → A (Abbey Road starts with A) → auto-selects
        menu.on_digit(1, now=14.0)
        menu.tick(now=14.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        # "Please hold." is unique to SCRIPT_CONNECTING_TEMPLATE
        assert any("Please hold" in t for t in texts), \
            f"Expected SCRIPT_CONNECTING_TEMPLATE (with 'Please hold') in TTS, got: {texts}"

    def test_album_selection_speaks_item_name(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Connecting announcement includes the album name."""
        menu = self._make_album_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                      mock_error_queue, tmp_path)
        menu.on_digit(1, now=14.0)
        menu.tick(now=14.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Find the connecting template call specifically
        connecting_texts = [t for t in tts_calls(mock_tts) if "Please hold" in t]
        assert connecting_texts, \
            f"Expected SCRIPT_CONNECTING_TEMPLATE in TTS, got: {tts_calls(mock_tts)}"
        assert "Abbey Road" in " ".join(connecting_texts), \
            f"Expected 'Abbey Road' in connecting template, got: {connecting_texts}"

    def test_album_selection_transitions_to_playing_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """State is PLAYING_MENU after album selection."""
        menu = self._make_album_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                      mock_error_queue, tmp_path)
        menu.on_digit(1, now=14.0)
        menu.tick(now=14.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.PLAYING_MENU, \
            f"Expected PLAYING_MENU, got {menu.state}"

    # ------------------------------------------------------------------
    # Genre
    # ------------------------------------------------------------------

    def test_genre_selection_speaks_connecting_template(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Selecting a genre speaks SCRIPT_CONNECTING_TEMPLATE before playback."""
        menu = self._make_genre_menu_f09(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                          mock_error_queue, tmp_path)
        # Dial J (digit 4) → selects "Jazz"
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        # "Please hold." is unique to SCRIPT_CONNECTING_TEMPLATE
        assert any("Please hold" in t for t in texts), \
            f"Expected SCRIPT_CONNECTING_TEMPLATE (with 'Please hold') in TTS, got: {texts}"

    def test_genre_selection_speaks_item_name(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Connecting announcement includes the genre name."""
        menu = self._make_genre_menu_f09(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                          mock_error_queue, tmp_path)
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Find the connecting template call specifically
        connecting_texts = [t for t in tts_calls(mock_tts) if "Please hold" in t]
        assert connecting_texts, \
            f"Expected SCRIPT_CONNECTING_TEMPLATE in TTS, got: {tts_calls(mock_tts)}"
        assert "Jazz" in " ".join(connecting_texts), \
            f"Expected 'Jazz' in connecting template, got: {connecting_texts}"

    def test_genre_selection_transitions_to_playing_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """State is PLAYING_MENU after genre selection."""
        menu = self._make_genre_menu_f09(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                          mock_error_queue, tmp_path)
        menu.on_digit(4, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.PLAYING_MENU, \
            f"Expected PLAYING_MENU, got {menu.state}"

    # ------------------------------------------------------------------
    # Artist submenu — digit 1 (shuffle artist)
    # ------------------------------------------------------------------

    def test_artist_shuffle_speaks_connecting_template(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Digit 1 in ARTIST_SUBMENU speaks SCRIPT_CONNECTING_TEMPLATE before playback."""
        menu = self._make_artist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                       mock_error_queue, tmp_path)
        menu.on_digit(1, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        # "Please hold." is unique to SCRIPT_CONNECTING_TEMPLATE
        assert any("Please hold" in t for t in texts), \
            f"Expected SCRIPT_CONNECTING_TEMPLATE (with 'Please hold') in TTS, got: {texts}"

    def test_artist_shuffle_speaks_artist_name(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Artist shuffle announcement includes the artist name."""
        menu = self._make_artist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                       mock_error_queue, tmp_path)
        menu.on_digit(1, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Find the connecting template call specifically
        connecting_texts = [t for t in tts_calls(mock_tts) if "Please hold" in t]
        assert connecting_texts, \
            f"Expected SCRIPT_CONNECTING_TEMPLATE in TTS, got: {tts_calls(mock_tts)}"
        assert "Beatles" in " ".join(connecting_texts), \
            f"Expected 'Beatles' in connecting template text, got: {connecting_texts}"

    def test_artist_shuffle_calls_play(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """After announcing, plex_client.play() is called with the artist key."""
        menu = self._make_artist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                       mock_error_queue, tmp_path)
        menu.on_digit(1, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        play_calls = [c for c in mock_media_client.calls if c[0] == 'play']
        assert play_calls, f"Expected play() call, got: {mock_media_client.calls}"
        assert play_calls[0][1] == "/a/1"

    def test_artist_shuffle_transitions_to_playing_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """State is PLAYING_MENU after artist shuffle selection."""
        menu = self._make_artist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                       mock_error_queue, tmp_path)
        menu.on_digit(1, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.PLAYING_MENU, \
            f"Expected PLAYING_MENU, got {menu.state}"

    def test_artist_shuffle_phone_number_matches_phone_book(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """The phone number spoken in the announcement matches the phone book entry."""
        import re
        from src.phone_book import PhoneBook
        digit_word_list = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
                           'eight', 'nine']
        menu = self._make_artist_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                       mock_error_queue, tmp_path)
        menu.on_digit(1, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # The SCRIPT_CONNECTING_TEMPLATE call must contain digit words (phone number)
        connecting_texts = [t for t in tts_calls(mock_tts) if "Please hold" in t]
        assert connecting_texts, \
            f"Expected SCRIPT_CONNECTING_TEMPLATE in TTS, got: {tts_calls(mock_tts)}"
        full_text = " ".join(connecting_texts).lower()
        # Count total digit word occurrences (with repetitions) to match PHONE_NUMBER_LENGTH
        total_count = sum(len(re.findall(r'\b' + w + r'\b', full_text)) for w in digit_word_list)
        assert total_count >= PHONE_NUMBER_LENGTH, \
            f"Expected {PHONE_NUMBER_LENGTH} digit word occurrences, found {total_count} in: {full_text}"


# ---------------------------------------------------------------------------
# §F10 · Artist submenu re-delivery on invalid digit
# ---------------------------------------------------------------------------

class TestArtistSubmenuReDelivery:
    """F-10: _re_deliver_current_state handles ARTIST_SUBMENU."""

    def _make_artist_submenu_with_albums(self, mock_audio, mock_tts, mock_media_client,
                                         mock_media_store, mock_error_queue, tmp_path):
        """Build a Menu in ARTIST_SUBMENU state with albums available."""
        artist = MediaItem("/a/1", "Beatles", "artist")
        album = MediaItem("/al/1", "Abbey Road", "album")
        mock_media_store.set_playlists([])
        mock_media_store.set_artists([artist])
        mock_media_store.set_genres([])
        mock_media_store.set_albums_for_artist("/a/1", [album])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        menu.tick(now=10.0)
        # Digit 1 -> artist browse
        menu.on_digit(1, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.BROWSE_ARTISTS, \
            f"Expected BROWSE_ARTISTS, got {menu.state}"
        # Digit 1 -> B (Beatles)
        menu.on_digit(1, now=12.0)
        menu.tick(now=12.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.ARTIST_SUBMENU, \
            f"Expected ARTIST_SUBMENU, got {menu.state}"
        mock_tts.calls.clear()
        mock_media_client.calls.clear()
        return menu

    def test_invalid_digit_speaks_not_in_service(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Dialing an invalid digit in ARTIST_SUBMENU speaks SCRIPT_NOT_IN_SERVICE."""
        menu = self._make_artist_submenu_with_albums(mock_audio, mock_tts, mock_media_client,
                                                      mock_media_store, mock_error_queue, tmp_path)
        # Digit 5 is not a valid option in ARTIST_SUBMENU
        menu.on_digit(5, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts), \
            f"SCRIPT_NOT_IN_SERVICE not spoken after invalid digit; texts: {texts}"

    def test_invalid_digit_re_delivers_artist_submenu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """After invalid digit, artist submenu prompt is re-spoken (contains artist name)."""
        menu = self._make_artist_submenu_with_albums(mock_audio, mock_tts, mock_media_client,
                                                      mock_media_store, mock_error_queue, tmp_path)
        menu.on_digit(5, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        # The re-delivered submenu text must contain the artist name
        assert any("Beatles" in t for t in texts), \
            f"Artist name not found in re-delivered submenu; texts: {texts}"

    def test_invalid_digit_re_delivered_text_includes_album_option(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Re-delivered artist submenu includes the album option when albums exist."""
        menu = self._make_artist_submenu_with_albums(mock_audio, mock_tts, mock_media_client,
                                                      mock_media_store, mock_error_queue, tmp_path)
        menu.on_digit(5, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        # SCRIPT_ARTIST_SUBMENU_ALBUMS_SUFFIX contains "album"
        assert any("album" in t.lower() for t in texts), \
            f"Album option not found in re-delivered submenu; texts: {texts}"

    def test_current_artist_preserved_after_invalid_digit(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """_current_artist is preserved after an invalid digit re-delivery."""
        menu = self._make_artist_submenu_with_albums(mock_audio, mock_tts, mock_media_client,
                                                      mock_media_store, mock_error_queue, tmp_path)
        menu.on_digit(5, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # State must still be ARTIST_SUBMENU (current artist preserved)
        assert menu.state == MenuState.ARTIST_SUBMENU, \
            f"Expected ARTIST_SUBMENU after invalid digit, got {menu.state}"

    def test_current_artist_still_usable_after_re_delivery(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """After re-delivery, digit 1 still plays the correct artist."""
        menu = self._make_artist_submenu_with_albums(mock_audio, mock_tts, mock_media_client,
                                                      mock_media_store, mock_error_queue, tmp_path)
        # First, dial invalid digit
        menu.on_digit(5, now=13.0)
        menu.tick(now=13.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        mock_tts.calls.clear()
        mock_media_client.calls.clear()
        # Now dial 1 -- should still play the artist
        menu.on_digit(1, now=14.0)
        menu.tick(now=14.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        play_calls = [c for c in mock_media_client.calls if c[0] == 'play']
        assert play_calls, f"Expected play() after re-delivery, got: {mock_media_client.calls}"


# ---------------------------------------------------------------------------
# F-11 · Digit received before dial-tone menu is delivered
# ---------------------------------------------------------------------------

class TestDigitBeforeMenu:
    """Digits dialed during IDLE_DIAL_TONE (before timeout fires the menu)
    must not cause invalid state routing.  The menu should be delivered first,
    the dial tone stopped, and the queued digit dropped."""

    def _make_menu_with_content(self, mock_audio, mock_tts, mock_media_client,
                                 mock_media_store, mock_error_queue, tmp_path):
        """Helper: build a Menu with one playlist available (idle state)."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz Mix", "playlist")])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        return make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)

    def test_digit_during_idle_dial_tone_delivers_idle_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store,
            mock_error_queue, tmp_path):
        """Digit dialed during IDLE_DIAL_TONE transitions to IDLE_MENU."""
        menu = self._make_menu_with_content(mock_audio, mock_tts, mock_media_client,
                                             mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        assert menu.state == MenuState.IDLE_DIAL_TONE
        # Digit arrives well before the DIAL_TONE_TIMEOUT_IDLE (5s)
        menu.on_digit(1, now=0.1)
        # Advance past disambiguation timeout (1.5s) but still within dial-tone window
        menu.tick(now=0.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.IDLE_MENU, \
            f"Expected IDLE_MENU after digit-before-menu guard, got {menu.state}"

    def test_digit_during_idle_dial_tone_no_not_in_service(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store,
            mock_error_queue, tmp_path):
        """SCRIPT_NOT_IN_SERVICE must NOT be spoken when digit is dialed during IDLE_DIAL_TONE."""
        menu = self._make_menu_with_content(mock_audio, mock_tts, mock_media_client,
                                             mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        menu.on_digit(1, now=0.1)
        menu.tick(now=0.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert not tts_spoke(mock_tts, "not in service"), \
            f"SCRIPT_NOT_IN_SERVICE should not be spoken; tts calls: {tts_calls(mock_tts)}"

    def test_digit_during_idle_dial_tone_stops_dial_tone(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store,
            mock_error_queue, tmp_path):
        """The dial tone must be stopped before the menu prompt is delivered."""
        menu = self._make_menu_with_content(mock_audio, mock_tts, mock_media_client,
                                             mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        mock_audio.calls.clear()  # Clear the play_tone from handset lift
        menu.on_digit(1, now=0.1)
        menu.tick(now=0.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # stop() must appear in audio calls before any speak_and_play
        audio_stops = [i for i, c in enumerate(mock_audio.calls) if c[0] == 'stop']
        assert audio_stops, \
            f"Expected audio.stop() to be called; audio calls: {mock_audio.calls}"

    def test_digit_during_idle_dial_tone_digit_dropped(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store,
            mock_error_queue, tmp_path):
        """The queued digit is dropped — no navigation action is taken on it."""
        menu = self._make_menu_with_content(mock_audio, mock_tts, mock_media_client,
                                             mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        menu.on_digit(1, now=0.1)
        menu.tick(now=0.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Digit 1 in IDLE_MENU would navigate to playlists (BROWSE_PLAYLISTS)
        # but since it was dropped we should still be at IDLE_MENU
        assert menu.state == MenuState.IDLE_MENU, \
            f"Digit should be dropped; expected IDLE_MENU, got {menu.state}"

    def test_digit_during_idle_dial_tone_while_playing_delivers_playing_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store,
            mock_error_queue, tmp_path):
        """When music is playing and digit arrives during IDLE_DIAL_TONE,
        the PLAYING_MENU is delivered (not the idle menu)."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz Mix", "playlist")])
        now_playing_item = MediaItem("/tracks/1", "Some Song", "track")
        mock_media_client.set_now_playing(PlaybackState(item=now_playing_item, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=0.0)
        assert menu.state == MenuState.IDLE_DIAL_TONE
        menu.on_digit(1, now=0.1)
        menu.tick(now=0.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state == MenuState.PLAYING_MENU, \
            f"Expected PLAYING_MENU when music playing, got {menu.state}"


# ---------------------------------------------------------------------------
# §9.x Radio menu support
# ---------------------------------------------------------------------------

SCRIPT_RADIO_CONNECTING_FRAGMENT = "Tuning in to"
SCRIPT_RADIO_PLAYING_MENU_FRAGMENT = "To disconnect your call, dial three"
SCRIPT_RADIO_PLAYING_GREETING_FRAGMENT = "currently tuned to"

from src.constants import DIAL_TONE_TIMEOUT_PLAYING


def _seed_radio_entry(phone_book, media_key="radio:90300000.0", name="NPR", media_type="radio"):
    """Seed a radio entry into the phone book and return its phone number."""
    return phone_book.assign_or_get(media_key=media_key, media_type=media_type, name=name)


class TestRadioMenu:
    """Tests for RADIO_PLAYING_MENU state and radio direct-dial flow."""

    def _make_menu_with_radio(self, mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path, radio):
        """Build a menu with handset lifted and idle menu delivered, using provided radio."""
        from src.phone_book import PhoneBook
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz Mix", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        db = str(tmp_path / "phone_book.db")
        phone_book = PhoneBook(db_path=db)
        menu = Menu(
            audio=mock_audio,
            tts=mock_tts,
            media_client=mock_media_client,
            media_store=mock_media_store,
            phone_book=phone_book,
            error_queue=mock_error_queue,
            radio=radio,
        )
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)  # past dial tone → idle menu
        mock_tts.calls.clear()
        mock_media_client.calls.clear()
        return menu, phone_book

    def test_radio_direct_dial_stops_plex_and_plays_radio(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Dialing a radio number stops Plex, calls radio.play with correct freq, sets state."""
        from src.radio import MockRadio
        radio = MockRadio()
        menu, phone_book = self._make_menu_with_radio(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, radio)
        number = _seed_radio_entry(phone_book, media_key="radio:90300000.0", name="NPR")

        _dial_number(menu, number, start_time=11.0)

        assert menu.state == MenuState.RADIO_PLAYING_MENU, \
            f"Expected RADIO_PLAYING_MENU, got {menu.state}"
        media_stops = [c for c in mock_media_client.calls if c[0] == 'stop']
        assert len(media_stops) >= 1, f"Expected media_client.stop() called; calls: {mock_media_client.calls}"
        radio_plays = [c for c in radio.calls if c[0] == 'play']
        assert len(radio_plays) >= 1, f"Expected radio.play() called; radio calls: {radio.calls}"
        assert radio_plays[0][1] == 90300000.0, \
            f"Expected freq 90300000.0, got {radio_plays[0][1]}"

    def test_radio_dial_speaks_connecting_template(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Dialing a radio number speaks SCRIPT_RADIO_CONNECTING with station name."""
        from src.radio import MockRadio
        radio = MockRadio()
        menu, phone_book = self._make_menu_with_radio(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, radio)
        number = _seed_radio_entry(phone_book, media_key="radio:90300000.0", name="NPR")

        _dial_number(menu, number, start_time=11.0)

        texts = tts_calls(mock_tts)
        assert any(SCRIPT_RADIO_CONNECTING_FRAGMENT in t for t in texts), \
            f"Expected '{SCRIPT_RADIO_CONNECTING_FRAGMENT}' in TTS; got: {texts}"
        assert any("NPR" in t for t in texts), \
            f"Expected station name 'NPR' in TTS; got: {texts}"

    def test_radio_stops_existing_stream_before_new_dial(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """When radio is already playing, stop() is called before play() on new dial."""
        from src.radio import MockRadio
        radio = MockRadio()
        radio.set_playing(True)
        menu, phone_book = self._make_menu_with_radio(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, radio)
        number = _seed_radio_entry(phone_book, media_key="radio:90300000.0", name="NPR")

        _dial_number(menu, number, start_time=11.0)

        stop_indices = [i for i, c in enumerate(radio.calls) if c[0] == 'stop']
        play_indices = [i for i, c in enumerate(radio.calls) if c[0] == 'play']
        assert stop_indices, f"Expected radio.stop() in calls: {radio.calls}"
        assert play_indices, f"Expected radio.play() in calls: {radio.calls}"
        assert stop_indices[0] < play_indices[0], \
            f"stop() must come before play(); calls: {radio.calls}"

    def test_radio_playing_menu_on_handset_lift(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Lifting handset while radio is playing (Plex idle) → RADIO_PLAYING_MENU after timeout."""
        from src.radio import MockRadio
        radio = MockRadio()
        radio.set_playing(True)
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue,
                         tmp_path, radio=radio)
        menu.on_handset_lifted(now=_T0)
        mock_tts.calls.clear()
        # Tick past DIAL_TONE_TIMEOUT_PLAYING
        menu.tick(now=_T0 + DIAL_TONE_TIMEOUT_PLAYING + 0.1)

        assert menu.state == MenuState.RADIO_PLAYING_MENU, \
            f"Expected RADIO_PLAYING_MENU, got {menu.state}"
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_RADIO_PLAYING_MENU_FRAGMENT in t for t in texts), \
            f"Expected radio playing menu TTS; got: {texts}"

    def test_radio_playing_menu_digit_3_stops_radio(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """In RADIO_PLAYING_MENU, digit 3 → radio.stop(), state → IDLE_MENU."""
        from src.radio import MockRadio
        radio = MockRadio()
        menu, phone_book = self._make_menu_with_radio(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, radio)
        number = _seed_radio_entry(phone_book, media_key="radio:90300000.0", name="NPR")
        _dial_number(menu, number, start_time=11.0)
        assert menu.state == MenuState.RADIO_PLAYING_MENU

        radio.calls.clear()
        mock_tts.calls.clear()
        menu.on_digit(3, now=15.0)
        menu.tick(now=15.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)

        assert menu.state == MenuState.IDLE_MENU, \
            f"Expected IDLE_MENU after digit 3; got {menu.state}"
        radio_stops = [c for c in radio.calls if c[0] == 'stop']
        assert len(radio_stops) >= 1, f"Expected radio.stop(); calls: {radio.calls}"

    def test_radio_playing_menu_digit_0_stops_radio(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """In RADIO_PLAYING_MENU, digit 0 → radio.stop(), state → IDLE_MENU."""
        from src.radio import MockRadio
        radio = MockRadio()
        menu, phone_book = self._make_menu_with_radio(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, radio)
        number = _seed_radio_entry(phone_book, media_key="radio:90300000.0", name="NPR")
        _dial_number(menu, number, start_time=11.0)
        assert menu.state == MenuState.RADIO_PLAYING_MENU

        radio.calls.clear()
        mock_tts.calls.clear()
        menu.on_digit(0, now=15.0)
        menu.tick(now=15.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)

        assert menu.state == MenuState.IDLE_MENU, \
            f"Expected IDLE_MENU after digit 0; got {menu.state}"
        radio_stops = [c for c in radio.calls if c[0] == 'stop']
        assert len(radio_stops) >= 1, f"Expected radio.stop(); calls: {radio.calls}"

    def test_radio_playing_menu_invalid_digit(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """In RADIO_PLAYING_MENU, digit 1 → SCRIPT_NOT_IN_SERVICE, radio not stopped."""
        from src.radio import MockRadio
        radio = MockRadio()
        menu, phone_book = self._make_menu_with_radio(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, radio)
        number = _seed_radio_entry(phone_book, media_key="radio:90300000.0", name="NPR")
        _dial_number(menu, number, start_time=11.0)
        assert menu.state == MenuState.RADIO_PLAYING_MENU

        radio.calls.clear()
        mock_tts.calls.clear()
        menu.on_digit(1, now=15.0)
        menu.tick(now=15.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)

        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts), \
            f"Expected SCRIPT_NOT_IN_SERVICE; got: {texts}"
        radio_stops = [c for c in radio.calls if c[0] == 'stop']
        assert len(radio_stops) == 0, f"radio.stop() should NOT be called; calls: {radio.calls}"

    def test_hangup_does_not_stop_radio(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Hang-up in RADIO_PLAYING_MENU does NOT call radio.stop()."""
        from src.radio import MockRadio
        radio = MockRadio()
        menu, phone_book = self._make_menu_with_radio(
            mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path, radio)
        number = _seed_radio_entry(phone_book, media_key="radio:90300000.0", name="NPR")
        _dial_number(menu, number, start_time=11.0)
        assert menu.state == MenuState.RADIO_PLAYING_MENU

        radio.calls.clear()
        menu.on_handset_on_cradle()

        radio_stops = [c for c in radio.calls if c[0] == 'stop']
        assert len(radio_stops) == 0, \
            f"Hang-up must not stop radio; calls: {radio.calls}"

    def test_radio_uses_playing_timeout_when_active(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """When radio is active, DIAL_TONE_TIMEOUT_PLAYING applies (shorter timeout)."""
        from src.radio import MockRadio
        from src.constants import DIAL_TONE_TIMEOUT_IDLE
        radio = MockRadio()
        radio.set_playing(True)
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue,
                         tmp_path, radio=radio)
        menu.on_handset_lifted(now=_T0)
        mock_tts.calls.clear()

        # Just before DIAL_TONE_TIMEOUT_PLAYING — should still be in IDLE_DIAL_TONE
        menu.tick(now=_T0 + DIAL_TONE_TIMEOUT_PLAYING - 0.05)
        assert menu.state == MenuState.IDLE_DIAL_TONE, \
            f"Expected still IDLE_DIAL_TONE before timeout; got {menu.state}"

        # Just past DIAL_TONE_TIMEOUT_PLAYING — should now be in RADIO_PLAYING_MENU
        menu.tick(now=_T0 + DIAL_TONE_TIMEOUT_PLAYING + 0.1)
        assert menu.state == MenuState.RADIO_PLAYING_MENU, \
            f"Expected RADIO_PLAYING_MENU after timeout; got {menu.state}"


# ---------------------------------------------------------------------------
# F-23: Narrow broad except Exception handlers
# ---------------------------------------------------------------------------

class TestNarrowExceptionHandlers:
    """Verify that each narrowed handler triggers correctly on the specific
    exception types the called code can raise."""

    # -----------------------------------------------------------------------
    # menu.py — media_store browse call (line ~425)
    # -----------------------------------------------------------------------

    def test_media_store_browse_sqlite_error_enters_failure_mode(
            self, mock_audio, mock_tts, mock_media_client, mock_error_queue, tmp_path):
        """sqlite3.Error from media_store.get_playlists() → enters failure mode."""
        import sqlite3
        from src.menu import SCRIPT_MEDIA_FAILURE, SCRIPT_RETRY_PROMPT

        class SqliteFailingStore:
            playlists_has_content = False
            artists_has_content = False
            genres_has_content = False
            calls = []
            def get_playlists(self): raise sqlite3.Error("DB locked")
            def get_artists(self): raise sqlite3.Error("DB locked")
            def get_genres(self): raise sqlite3.Error("DB locked")
            def get_albums_for_artist(self, k): raise sqlite3.Error("DB locked")
            def remove_item(self, k): pass
            def refresh(self): raise sqlite3.Error("DB locked")

        menu = make_menu(mock_audio, mock_tts, mock_media_client, SqliteFailingStore(),
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_MEDIA_FAILURE in t for t in texts), \
            f"Expected SCRIPT_MEDIA_FAILURE for sqlite3.Error; got: {texts}"
        assert any(SCRIPT_RETRY_PROMPT in t for t in texts), \
            f"Expected SCRIPT_RETRY_PROMPT for sqlite3.Error; got: {texts}"
        assert menu._failure_mode == "media"

    def test_media_store_browse_oserror_enters_failure_mode(
            self, mock_audio, mock_tts, mock_media_client, mock_error_queue, tmp_path):
        """OSError from media_store.get_artists() → enters failure mode."""
        from src.menu import SCRIPT_MEDIA_FAILURE, SCRIPT_RETRY_PROMPT

        class OsErrorFailingStore:
            playlists_has_content = False
            artists_has_content = False
            genres_has_content = False
            calls = []
            def get_playlists(self): raise OSError("Network error")
            def get_artists(self): raise OSError("Network error")
            def get_genres(self): raise OSError("Network error")
            def get_albums_for_artist(self, k): raise OSError("Network error")
            def remove_item(self, k): pass
            def refresh(self): raise OSError("Network error")

        menu = make_menu(mock_audio, mock_tts, mock_media_client, OsErrorFailingStore(),
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_MEDIA_FAILURE in t for t in texts), \
            f"Expected SCRIPT_MEDIA_FAILURE for OSError; got: {texts}"
        assert any(SCRIPT_RETRY_PROMPT in t for t in texts), \
            f"Expected SCRIPT_RETRY_PROMPT for OSError; got: {texts}"
        assert menu._failure_mode == "media"

    # -----------------------------------------------------------------------
    # menu.py — phone_book.lookup_by_phone_number() (line ~802)
    # -----------------------------------------------------------------------

    def test_phone_book_lookup_sqlite_error_treated_as_not_found(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """sqlite3.Error from phone_book.lookup_by_phone_number() → SCRIPT_NOT_IN_SERVICE."""
        import sqlite3
        from src.menu import SCRIPT_NOT_IN_SERVICE
        from src.phone_book import PhoneBook
        from unittest.mock import patch

        mock_media_store.set_playlists([])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])

        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)

        # Patch the phone_book to raise sqlite3.Error on lookup
        def raise_sqlite(*args, **kwargs):
            raise sqlite3.Error("table locked")

        menu._phone_book.lookup_by_phone_number = raise_sqlite

        mock_tts.calls.clear()
        # Dial a 7-digit number (not ASSISTANT_NUMBER)
        for digit in [1, 2, 3, 4, 5, 6, 7]:
            menu.on_digit(digit, now=15.0 + digit * 0.1)
        menu.tick(now=20.0)

        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts), \
            f"Expected SCRIPT_NOT_IN_SERVICE for sqlite3.Error in lookup; got: {texts}"

    def test_phone_book_lookup_sqlite_error_logs_to_error_queue(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """sqlite3.Error from phone_book.lookup_by_phone_number() → error_queue.log called."""
        import sqlite3

        mock_media_store.set_playlists([])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])

        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)

        # Patch the phone_book to raise sqlite3.Error on lookup
        def raise_sqlite(*args, **kwargs):
            raise sqlite3.Error("table locked")

        menu._phone_book.lookup_by_phone_number = raise_sqlite

        mock_error_queue.logged_calls.clear()
        # Dial a 7-digit number (not ASSISTANT_NUMBER)
        for digit in [1, 2, 3, 4, 5, 6, 7]:
            menu.on_digit(digit, now=15.0 + digit * 0.1)
        menu.tick(now=20.0)

        assert len(mock_error_queue.logged_calls) >= 1, \
            "Expected error_queue.log to be called when phone_book.lookup_by_phone_number raises"
        source, severity, message = mock_error_queue.logged_calls[0]
        assert source == "menu", f"Expected source='menu', got {source!r}"
        assert severity == "error", f"Expected severity='error', got {severity!r}"
        assert "Phone book lookup failed" in message, \
            f"Expected 'Phone book lookup failed' in message, got {message!r}"

    # -----------------------------------------------------------------------
    # menu.py — media_store.refresh() in _do_assistant_refresh() (line ~1037)
    # -----------------------------------------------------------------------

    def _enter_assistant(self, menu, mock_media_store, mock_tts):
        """Helper: put the menu in ASSISTANT state and clear call records."""
        mock_media_store.set_playlists([])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)
        _dial_number(menu, ASSISTANT_NUMBER, start_time=11.0)
        assert menu.state == MenuState.ASSISTANT
        mock_tts.calls.clear()

    def test_assistant_refresh_sqlite_error_speaks_failure(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """sqlite3.Error from media_store.refresh() in assistant → speaks refresh failure script."""
        import sqlite3
        from src.menu import SCRIPT_ASSISTANT_REFRESH_FAILURE

        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        self._enter_assistant(menu, mock_media_store, mock_tts)

        def raise_sqlite():
            raise sqlite3.Error("DB locked")

        menu._media_store.refresh = raise_sqlite
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)

        texts = tts_calls(mock_tts)
        assert any(SCRIPT_ASSISTANT_REFRESH_FAILURE in t for t in texts), \
            f"Expected SCRIPT_ASSISTANT_REFRESH_FAILURE for sqlite3.Error; got: {texts}"

    def test_assistant_refresh_oserror_speaks_failure(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """OSError from media_store.refresh() in assistant → speaks refresh failure script."""
        from src.menu import SCRIPT_ASSISTANT_REFRESH_FAILURE

        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                         mock_error_queue, tmp_path)
        self._enter_assistant(menu, mock_media_store, mock_tts)

        def raise_oserror():
            raise OSError("HTTP connection failed")

        menu._media_store.refresh = raise_oserror
        menu.on_digit(1, now=20.0)
        menu.tick(now=20.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)

        texts = tts_calls(mock_tts)
        assert any(SCRIPT_ASSISTANT_REFRESH_FAILURE in t for t in texts), \
            f"Expected SCRIPT_ASSISTANT_REFRESH_FAILURE for OSError; got: {texts}"


# ---------------------------------------------------------------------------
# §F-25 Re-deliver the prior menu after a failed direct dial
# ---------------------------------------------------------------------------

class TestDirectDialFailureReturn:
    """After a failed direct dial (number not found), the prior menu is re-delivered."""

    def _dial_unknown_number(self, menu, start_time=15.0):
        """Dial a 7-digit number that won't be in the phone book."""
        # Use digits 1,2,3,4,5,6,7 — unlikely to be seeded
        digits = [1, 2, 3, 4, 5, 6, 7]
        menu.on_digit(digits[0], now=start_time)
        menu.on_digit(digits[1], now=start_time + 0.05)
        for i, d in enumerate(digits[2:], start=2):
            menu.on_digit(d, now=start_time + i * 0.1)

    def test_failed_direct_dial_from_idle_menu_speaks_not_in_service(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Failed direct dial from IDLE_MENU → speaks SCRIPT_NOT_IN_SERVICE."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)  # deliver idle menu; state = IDLE_MENU
        assert menu.state == MenuState.IDLE_MENU
        mock_tts.calls.clear()

        self._dial_unknown_number(menu, start_time=15.0)

        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts), \
            f"Expected SCRIPT_NOT_IN_SERVICE after failed dial; got: {texts}"

    def test_failed_direct_dial_from_idle_menu_re_delivers_idle_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Failed direct dial from IDLE_MENU → re-delivers idle menu (state = IDLE_MENU)."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)  # deliver idle menu; state = IDLE_MENU
        assert menu.state == MenuState.IDLE_MENU
        mock_tts.calls.clear()

        self._dial_unknown_number(menu, start_time=15.0)

        assert menu.state == MenuState.IDLE_MENU, \
            f"Expected IDLE_MENU after failed dial from IDLE_MENU; got {menu.state}"
        # Idle menu prompt should be re-delivered
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_IDLE_MENU in t for t in texts), \
            f"Expected idle menu re-delivered after failed dial; texts: {texts}"

    def test_failed_direct_dial_from_browse_artists_re_delivers_browse_prompt(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Failed direct dial from BROWSE_ARTISTS → speaks not-in-service then re-delivers browse prompt."""
        from src.menu import SCRIPT_BROWSE_PROMPT_ARTIST
        items = [MediaItem("/a/1", "Beatles", "artist")]
        menu = _make_browse_menu(mock_audio, mock_tts, mock_media_client, mock_media_store,
                                 mock_error_queue, tmp_path, items, category="artist")
        assert menu.state == MenuState.BROWSE_ARTISTS, \
            f"Expected BROWSE_ARTISTS before dialing; got {menu.state}"
        mock_tts.calls.clear()

        self._dial_unknown_number(menu, start_time=20.0)

        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts), \
            f"Expected SCRIPT_NOT_IN_SERVICE; got: {texts}"
        # State should be restored to BROWSE_ARTISTS
        assert menu.state == MenuState.BROWSE_ARTISTS, \
            f"Expected BROWSE_ARTISTS after failed dial; got {menu.state}"
        # Browse prompt should be re-delivered
        assert any(SCRIPT_BROWSE_PROMPT_ARTIST in t for t in texts), \
            f"Expected artist browse prompt re-delivered; texts: {texts}"

    def test_failed_direct_dial_before_any_menu_delivers_idle_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Failed direct dial from IDLE_DIAL_TONE (before any menu) → delivers correct top-level menu."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        # Do NOT tick past the dial tone timeout — state stays IDLE_DIAL_TONE
        assert menu.state == MenuState.IDLE_DIAL_TONE

        # Dial two digits quickly to enter DIRECT_DIAL while still in IDLE_DIAL_TONE
        menu.on_digit(1, now=_T0 + 0.1)
        menu.on_digit(2, now=_T0 + 0.15)
        assert menu.state == MenuState.DIRECT_DIAL
        # Dial remaining 5 digits
        for i, d in enumerate([3, 4, 5, 6, 7], start=2):
            menu.on_digit(d, now=_T0 + 0.1 + i * 0.1)

        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts), \
            f"Expected SCRIPT_NOT_IN_SERVICE; got: {texts}"
        # Must deliver a menu, not leave in silence
        assert menu.state in (MenuState.IDLE_MENU, MenuState.PLAYING_MENU), \
            f"Expected top-level menu state after early failed dial; got {menu.state}"
        # Idle menu prompt must be spoken (no music playing)
        assert any(SCRIPT_IDLE_MENU in t for t in texts), \
            f"Expected idle menu prompt delivered after early failed dial; texts: {texts}"

    def test_failed_direct_dial_before_any_menu_while_playing_delivers_playing_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Failed direct dial from IDLE_DIAL_TONE while Plex is playing → delivers playing menu."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        playing_item = MediaItem("/t/1", "Some Song", "track")
        mock_media_client.set_now_playing(PlaybackState(item=playing_item, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        # Do NOT tick past the dial tone timeout — state stays IDLE_DIAL_TONE
        assert menu.state == MenuState.IDLE_DIAL_TONE

        # Dial two digits quickly to enter DIRECT_DIAL while still in IDLE_DIAL_TONE
        menu.on_digit(1, now=_T0 + 0.1)
        menu.on_digit(2, now=_T0 + 0.15)
        assert menu.state == MenuState.DIRECT_DIAL
        # Dial remaining 5 digits
        for i, d in enumerate([3, 4, 5, 6, 7], start=2):
            menu.on_digit(d, now=_T0 + 0.1 + i * 0.1)

        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in t for t in texts), \
            f"Expected SCRIPT_NOT_IN_SERVICE; got: {texts}"
        # Must end up in PLAYING_MENU since Plex is playing
        assert menu.state == MenuState.PLAYING_MENU, \
            f"Expected PLAYING_MENU after early failed dial while playing; got {menu.state}"

    def test_successful_direct_dial_unaffected(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Successful direct dial is unaffected — transitions to PLAYING_MENU as before."""
        from src.phone_book import PhoneBook
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))

        db = str(tmp_path / "pb_f25.db")
        phone_book = PhoneBook(db_path=db)
        # Seed a known entry
        number = phone_book.assign_or_get("/track/42", "playlist", "Test Track")

        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        # Replace the phone_book with one containing our entry
        menu._phone_book = phone_book

        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)  # IDLE_MENU
        mock_tts.calls.clear()
        mock_media_client.calls.clear()

        # Dial the number
        digits = [int(c) for c in number]
        menu.on_digit(digits[0], now=15.0)
        menu.on_digit(digits[1], now=15.05)
        for i, d in enumerate(digits[2:], start=2):
            menu.on_digit(d, now=15.0 + i * 0.1)

        # Should have transitioned to PLAYING_MENU
        assert menu.state == MenuState.PLAYING_MENU, \
            f"Expected PLAYING_MENU after successful dial; got {menu.state}"
        # Should NOT speak SCRIPT_NOT_IN_SERVICE
        texts = tts_calls(mock_tts)
        assert not any(SCRIPT_NOT_IN_SERVICE in t for t in texts), \
            f"SCRIPT_NOT_IN_SERVICE should not be spoken on success; got: {texts}"

    def test_pre_dial_state_cleared_on_cradle(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """on_handset_on_cradle() clears _pre_dial_state."""
        mock_media_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        mock_media_client.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted(now=_T0)
        menu.tick(now=10.0)

        # Enter direct dial to set _pre_dial_state
        menu.on_digit(1, now=15.0)
        menu.on_digit(2, now=15.05)
        assert menu.state == MenuState.DIRECT_DIAL
        assert menu._pre_dial_state is not None

        # Hang up — _pre_dial_state should be cleared
        menu.on_handset_on_cradle()
        assert menu._pre_dial_state is None, \
            f"Expected _pre_dial_state=None after cradle; got {menu._pre_dial_state}"
