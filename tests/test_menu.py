"""Tests for src/menu.py — Menu state machine (§9.1, §9.2, §9.3).

All tests use injected mocks; no hardware or network required.
"""

import time
import pytest
from src.menu import Menu, MenuState
from src.interfaces import MediaItem, PlaybackState
from src.constants import DIRECT_DIAL_DISAMBIGUATION_TIMEOUT, INACTIVITY_TIMEOUT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path):
    """Build a Menu with all mocked dependencies."""
    from src.phone_book import PhoneBook
    db = str(tmp_path / "phone_book.db")
    phone_book = PhoneBook(db_path=db)
    return Menu(
        audio=mock_audio,
        tts=mock_tts,
        plex_client=mock_plex,
        plex_store=mock_plex_store,
        phone_book=phone_book,
        error_queue=mock_error_queue,
    )


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

    def test_digit_0_single_goes_to_top_level(self, mock_audio, mock_tts, mock_plex,
                                               mock_plex_store, mock_error_queue, tmp_path):
        """Digit 0 alone → state resets to top-level menu."""
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
        menu.on_digit(0, now=0.0)
        # After disambiguation timeout: should be at top level
        menu.tick(now=0.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state in (MenuState.IDLE_MENU, MenuState.PLAYING_MENU)

    def test_digit_9_single_goes_back_one_level(self, mock_audio, mock_tts, mock_plex,
                                                 mock_plex_store, mock_error_queue, tmp_path):
        """Digit 9 alone → state moves up one level."""
        mock_plex_store.set_playlists([
            MediaItem("/p/1", "Jazz Mix", "playlist")
        ])
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
        # Enter idle menu
        menu.tick(now=10.0)  # past dial tone timeout
        # Navigate into playlist browse
        menu.on_digit(1, now=10.1)
        menu.tick(now=10.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Now press 9 to go back
        menu.on_digit(9, now=11.0)
        menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state in (MenuState.IDLE_MENU, MenuState.PLAYING_MENU)

    def test_digit_9_at_top_level(self, mock_audio, mock_tts, mock_plex,
                                   mock_plex_store, mock_error_queue, tmp_path):
        """Digit 9 at top level → no crash, stays at top level."""
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
        menu.tick(now=10.0)
        menu.on_digit(9, now=10.1)
        menu.tick(now=10.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert menu.state in (MenuState.IDLE_MENU, MenuState.PLAYING_MENU)

    def test_disambiguation_timeout_single_digit_is_navigation(
            self, mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path):
        """First digit received, no second digit within timeout → treated as navigation."""
        mock_plex_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
        menu.tick(now=10.0)
        menu.on_digit(1, now=10.1)
        # Tick past disambiguation timeout
        menu.tick(now=10.1 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        # Digit 1 navigated to playlist browse — not direct dial
        assert menu.state != MenuState.DIRECT_DIAL

    def test_disambiguation_second_digit_enters_direct_dial(
            self, mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path):
        """Second digit within timeout → DIRECT_DIAL mode entered."""
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
        t = 10.0
        menu.on_digit(1, now=t)
        # Second digit within timeout
        menu.on_digit(2, now=t + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT * 0.5)
        menu.tick(now=t + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT * 0.5 + 0.01)
        assert menu.state == MenuState.DIRECT_DIAL

    def test_disambiguation_0_and_9_literal_in_direct_dial(
            self, mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path):
        """In DIRECT_DIAL mode, 0 and 9 are accumulated as phone number digits."""
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
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
            self, mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path):
        """In DIRECT_DIAL mode, audio.play_dtmf called for each digit."""
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
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
SCRIPT_PLEX_FAILURE = "long-distance exchange appears to be temporarily out of service"
SCRIPT_RETRY_PROMPT = "dial one"
SCRIPT_NO_CONTENT = "no parties available"
SCRIPT_TERMINAL_FALLBACK = "Your call cannot be completed"


@pytest.fixture
def idle_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path):
    """Menu fixture with content available, nothing playing."""
    mock_plex_store.set_playlists([
        MediaItem("/p/1", "Jazz Mix", "playlist"),
        MediaItem("/p/2", "Rock Classics", "playlist"),
    ])
    mock_plex_store.set_artists([
        MediaItem("/a/1", "The Beatles", "artist"),
    ])
    mock_plex_store.set_genres([
        MediaItem("/g/1", "Jazz", "genre"),
    ])
    mock_plex.set_now_playing(PlaybackState(item=None, is_paused=False))
    return make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)


class TestIdleMenu:

    def _advance_to_idle_menu(self, menu, now=10.0):
        """Lift handset and advance past dial tone timeout."""
        menu.on_handset_lifted()
        menu.tick(now=now)

    def test_idle_menu_announces_options(self, idle_menu, mock_tts, mock_plex):
        """After dial tone timeout → TTS plays SCRIPT_OPERATOR_OPENER then SCRIPT_GREETING."""
        self._advance_to_idle_menu(idle_menu)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_OPERATOR_OPENER in t for t in texts), f"opener not found: {texts}"
        assert any(SCRIPT_GREETING in t for t in texts), f"greeting not found: {texts}"

    def test_operator_opener_spoken_once_per_session(self, idle_menu, mock_tts, mock_plex_store):
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

    def test_idle_menu_option_1_playlist(self, idle_menu, mock_tts, mock_plex_store):
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

    def test_idle_menu_option_4_shuffle(self, idle_menu, mock_plex):
        """Digit 4 → calls plex_client.shuffle_all()."""
        self._advance_to_idle_menu(idle_menu)
        mock_plex.calls.clear()
        idle_menu.on_digit(4, now=11.0)
        idle_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'shuffle_all' for c in mock_plex.calls)

    def test_idle_menu_omits_empty_category(self, mock_audio, mock_tts, mock_plex,
                                             mock_plex_store, mock_error_queue, tmp_path):
        """plex_store.has_content False for a category → not in menu."""
        mock_plex_store.set_playlists([])
        mock_plex_store.set_artists([MediaItem("/a/1", "Beatles", "artist")])
        mock_plex_store.set_genres([])
        mock_plex.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
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

    def test_idle_menu_plex_failure_at_load(self, mock_audio, mock_tts, mock_plex,
                                             mock_plex_store, mock_error_queue, tmp_path):
        """Plex unreachable at handset lift → SCRIPT_PLEX_FAILURE + SCRIPT_RETRY_PROMPT."""
        class FailingStore:
            playlists_has_content = False
            artists_has_content = False
            genres_has_content = False
            calls = []
            def get_playlists(self): raise RuntimeError("Plex down")
            def get_artists(self): raise RuntimeError("Plex down")
            def get_genres(self): raise RuntimeError("Plex down")
            def get_albums_for_artist(self, k): raise RuntimeError("Plex down")
            def remove_item(self, k): pass
            def refresh(self): raise RuntimeError("Plex down")

        menu = make_menu(mock_audio, mock_tts, mock_plex, FailingStore(), mock_error_queue, tmp_path)
        menu.on_handset_lifted()
        menu.tick(now=10.0)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_PLEX_FAILURE in t for t in texts), f"plex failure not found: {texts}"
        assert any(SCRIPT_RETRY_PROMPT in t for t in texts), f"retry prompt not found: {texts}"

    def test_idle_menu_no_content_plays_off_hook_tone(self, mock_audio, mock_tts, mock_plex,
                                                       mock_plex_store, mock_error_queue, tmp_path):
        """Zero playable content → TTS plays SCRIPT_NO_CONTENT, then off-hook tone."""
        mock_plex_store.set_playlists([])
        mock_plex_store.set_artists([])
        mock_plex_store.set_genres([])
        mock_plex.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
        menu.tick(now=10.0)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NO_CONTENT in t for t in texts), f"no_content not found: {texts}"
        off_hook = [c for c in mock_audio.calls if c[0] == 'play_off_hook_tone']
        assert len(off_hook) >= 1

    def test_off_hook_tone_stops_on_hangup(self, mock_audio, mock_tts, mock_plex,
                                            mock_plex_store, mock_error_queue, tmp_path):
        """Off-hook tone playing → user hangs up → tone stops."""
        mock_plex_store.set_playlists([])
        mock_plex_store.set_artists([])
        mock_plex_store.set_genres([])
        mock_plex.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
        menu.tick(now=10.0)
        mock_audio.calls.clear()
        menu.on_handset_on_cradle()
        stop_calls = [c for c in mock_audio.calls if c[0] == 'stop']
        assert len(stop_calls) >= 1

    def test_inactivity_timeout_triggers_off_hook_tone(self, idle_menu, mock_audio):
        """No digit for INACTIVITY_TIMEOUT → off-hook warning tone plays."""
        idle_menu.on_handset_lifted()
        # Advance past dial tone AND inactivity timeout
        idle_menu.tick(now=INACTIVITY_TIMEOUT + 20.0)
        off_hook = [c for c in mock_audio.calls if c[0] == 'play_off_hook_tone']
        assert len(off_hook) >= 1

    def test_inactivity_timeout_reset_on_digit(self, idle_menu, mock_audio):
        """Digit before inactivity timeout → timer resets, off-hook not triggered."""
        idle_menu.on_handset_lifted()
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
    return MediaItem(plex_key="/library/metadata/1", name="Abbey Road", media_type="album")


@pytest.fixture
def playing_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path, playing_item):
    """Menu fixture with music actively playing."""
    mock_plex_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
    mock_plex.set_now_playing(PlaybackState(item=playing_item, is_paused=False))
    mock_plex.set_queue_position(1, 5)
    return make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)


class TestPlayingMenu:

    def _advance_to_playing_menu(self, menu, now=10.0):
        menu.on_handset_lifted()
        menu.tick(now=now)

    def test_playing_menu_announces_options(self, playing_menu, mock_tts, playing_item):
        """Handset lifted while playing → TTS plays SCRIPT_OPERATOR_OPENER + SCRIPT_PLAYING_GREETING."""
        self._advance_to_playing_menu(playing_menu)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_OPERATOR_OPENER in t for t in texts), f"opener not found: {texts}"
        assert any(playing_item.name in t for t in texts), f"media name not found: {texts}"

    def test_playing_menu_option_1_pause(self, playing_menu, mock_plex):
        """Digit 1 when not paused → calls plex_client.pause()."""
        self._advance_to_playing_menu(playing_menu)
        mock_plex.calls.clear()
        playing_menu.on_digit(1, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'pause' for c in mock_plex.calls)

    def test_playing_menu_option_1_unpause(self, playing_menu, mock_plex, playing_item):
        """Digit 1 when paused → calls plex_client.unpause()."""
        mock_plex.set_now_playing(PlaybackState(item=playing_item, is_paused=True))
        self._advance_to_playing_menu(playing_menu)
        mock_plex.calls.clear()
        playing_menu.on_digit(1, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'unpause' for c in mock_plex.calls)

    def test_playing_menu_pause_label_when_playing(self, playing_menu, mock_tts):
        """Not paused → TTS plays SCRIPT_PLAYING_MENU_DEFAULT (contains 'hold')."""
        self._advance_to_playing_menu(playing_menu)
        texts = tts_calls(mock_tts)
        assert any("hold" in t.lower() for t in texts), f"hold option not found: {texts}"

    def test_playing_menu_unpause_label_when_paused(self, playing_menu, mock_tts, mock_plex, playing_item):
        """Paused → TTS plays SCRIPT_PLAYING_MENU_ON_HOLD (contains 'resume')."""
        mock_plex.set_now_playing(PlaybackState(item=playing_item, is_paused=True))
        self._advance_to_playing_menu(playing_menu)
        texts = tts_calls(mock_tts)
        assert any("resume" in t.lower() for t in texts), f"resume option not found: {texts}"

    def test_playing_menu_option_2_skip(self, playing_menu, mock_plex):
        """Digit 2 → calls plex_client.skip()."""
        self._advance_to_playing_menu(playing_menu)
        mock_plex.calls.clear()
        playing_menu.on_digit(2, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'skip' for c in mock_plex.calls)

    def test_playing_menu_skip_not_offered_on_last_track(self, playing_menu, mock_tts, mock_plex, playing_item):
        """Last track → SCRIPT_PLAYING_MENU_LAST_TRACK; digit 2 treated as invalid."""
        mock_plex.set_queue_position(5, 5)  # Last track
        mock_plex.set_now_playing(PlaybackState(item=playing_item, is_paused=False))
        self._advance_to_playing_menu(playing_menu)
        texts = tts_calls(mock_tts)
        # Skip option should not be mentioned
        full_text = " ".join(texts).lower()
        assert "transfer to the next party" not in full_text or "last" in full_text

    def test_playing_menu_option_3_end_call(self, playing_menu, mock_plex):
        """Digit 3 → calls plex_client.stop(), transitions to IDLE_MENU."""
        self._advance_to_playing_menu(playing_menu)
        mock_plex.calls.clear()
        playing_menu.on_digit(3, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert any(c[0] == 'stop' for c in mock_plex.calls)
        assert playing_menu.state == MenuState.IDLE_MENU

    def test_playing_menu_option_0_go_to_idle_menu(self, playing_menu):
        """Digit 0 → transitions to idle top-level menu."""
        self._advance_to_playing_menu(playing_menu)
        playing_menu.on_digit(0, now=11.0)
        playing_menu.tick(now=11.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        assert playing_menu.state == MenuState.IDLE_MENU

    def test_playing_menu_now_playing_idle_at_speak_time(
            self, mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path):
        """now_playing() returns idle at speak time → idle prompt delivered."""
        mock_plex_store.set_playlists([MediaItem("/p/1", "Jazz", "playlist")])
        # Initially playing, but at speak time it will be idle
        mock_plex.set_now_playing(PlaybackState(item=None, is_paused=False))
        menu = make_menu(mock_audio, mock_tts, mock_plex, mock_plex_store, mock_error_queue, tmp_path)
        menu.on_handset_lifted()
        menu.tick(now=10.0)
        texts = tts_calls(mock_tts)
        # Should get idle prompt, not playing prompt
        assert any(SCRIPT_GREETING in t for t in texts), f"idle greeting not found: {texts}"

    def test_playing_menu_uses_playback_state_not_local_state(
            self, playing_menu, mock_tts, mock_plex, playing_item):
        """Menu reflects Plex state, not local assumption."""
        # Plex reports paused even though we didn't command pause
        mock_plex.set_now_playing(PlaybackState(item=playing_item, is_paused=True))
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
