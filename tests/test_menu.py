"""Tests for src/menu.py."""

import pytest
from unittest.mock import MagicMock, call

from src.interfaces import MediaItem, PlaybackState, ErrorEntry
from src.menu import (
    Menu, MenuState,
    _strip_article, _t9_digit_for_name, _t9_digit_for_char, _filter_by_t9_prefix,
    SCRIPT_OPERATOR_OPENER, SCRIPT_GREETING, SCRIPT_EXTENSION_HINT,
    SCRIPT_IDLE_MENU_HEADER, SCRIPT_NOT_IN_SERVICE, SCRIPT_MEDIA_FAILURE,
    SCRIPT_RETRY_PROMPT, SCRIPT_NO_CONTENT, SCRIPT_SHUFFLE_CONNECTING,
    SCRIPT_PLAYING_MENU_DEFAULT, SCRIPT_PLAYING_MENU_ON_HOLD,
    SCRIPT_PLAYING_MENU_LAST_TRACK, SCRIPT_PLAYING_MENU_ON_HOLD_LAST_TRACK,
    SCRIPT_BROWSE_PROMPT_PLAYLIST, SCRIPT_BROWSE_PROMPT_ARTIST,
    SCRIPT_BROWSE_PROMPT_GENRE, SCRIPT_BROWSE_PROMPT_ALBUM,
    SCRIPT_BROWSE_PROMPT_NEXT_LETTER, SCRIPT_BROWSE_AUTO_SELECT_TEMPLATE,
    SCRIPT_CONNECTING_TEMPLATE, SCRIPT_ARTIST_SUBMENU_TEMPLATE,
    SCRIPT_ARTIST_SUBMENU_ALBUMS_SUFFIX, SCRIPT_ASSISTANT_GREETING,
    SCRIPT_ASSISTANT_ALL_CLEAR, SCRIPT_ASSISTANT_REFRESH_SUCCESS,
    SCRIPT_ASSISTANT_REFRESH_FAILURE, SCRIPT_ASSISTANT_NAVIGATION,
    SCRIPT_RADIO_CONNECTING, SCRIPT_RADIO_PLAYING_GREETING, SCRIPT_RADIO_PLAYING_MENU,
    SCRIPT_MISSED_CALL_TEMPLATE,
)
from src.constants import ASSISTANT_NUMBER, INACTIVITY_TIMEOUT, DIAL_ENTRY_TIMEOUT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_audio():
    return MagicMock()


@pytest.fixture
def mock_tts():
    return MagicMock()


@pytest.fixture
def mock_media_client():
    m = MagicMock()
    m.now_playing.return_value = PlaybackState(item=None, is_paused=False)
    m.get_queue_position.return_value = (1, 5)
    return m


@pytest.fixture
def mock_media_store():
    m = MagicMock()
    m.playlists_has_content = True
    m.artists_has_content = True
    m.genres_has_content = True
    m.get_playlists.return_value = []
    m.get_artists.return_value = []
    m.get_genres.return_value = []
    m.get_albums_for_artist.return_value = []
    m.refresh.return_value = {"playlists": "ok", "artists": "ok", "genres": "ok"}
    return m


@pytest.fixture
def mock_phone_book():
    m = MagicMock()
    m.assign_or_get.return_value = "1234567"
    m.lookup_by_phone_number.return_value = None
    return m


@pytest.fixture
def mock_error_queue():
    m = MagicMock()
    m.get_all.return_value = []
    m.get_by_severity.return_value = []
    return m


@pytest.fixture
def mock_radio():
    m = MagicMock()
    m.is_playing.return_value = False
    return m


@pytest.fixture
def menu(mock_audio, mock_tts, mock_media_client, mock_media_store, mock_phone_book,
         mock_error_queue, mock_radio):
    return Menu(
        audio=mock_audio,
        tts=mock_tts,
        media_client=mock_media_client,
        media_store=mock_media_store,
        phone_book=mock_phone_book,
        error_queue=mock_error_queue,
        radio=mock_radio,
    )


def lifted(m, now=100.0):
    """Lift handset at a fixed time."""
    m.on_handset_lifted(now=now)


def _playlist(name="My Playlist", key="pl:1"):
    return MediaItem(media_key=key, name=name, media_type="playlist")


def _artist(name="The Beatles", key="artist:beatles"):
    return MediaItem(media_key=key, name=name, media_type="artist")


def _genre(name="Jazz", key="genre:Jazz"):
    return MediaItem(media_key=key, name=name, media_type="genre")


def _album(name="Abbey Road", key="album:abbey"):
    return MediaItem(media_key=key, name=name, media_type="album")


# ---------------------------------------------------------------------------
# T9 utilities
# ---------------------------------------------------------------------------


class TestStripArticle:
    def test_strips_the(self):
        assert _strip_article("The Beatles") == "Beatles"

    def test_strips_a(self):
        assert _strip_article("A Tribe Called Quest") == "Tribe Called Quest"

    def test_strips_an(self):
        assert _strip_article("An Artist") == "Artist"

    def test_case_insensitive(self):
        assert _strip_article("THE Beatles") == "Beatles"

    def test_no_article(self):
        assert _strip_article("Beatles") == "Beatles"

    def test_empty_string(self):
        assert _strip_article("") == ""

    def test_does_not_strip_partial_match(self):
        assert _strip_article("There") == "There"


class TestT9DigitForChar:
    def test_abc_maps_to_1(self):
        for ch in "ABCabc":
            assert _t9_digit_for_char(ch) == 1

    def test_def_maps_to_2(self):
        for ch in "DEFdef":
            assert _t9_digit_for_char(ch) == 2

    def test_vwxyz_maps_to_8(self):
        for ch in "VWXYZvwxyz":
            assert _t9_digit_for_char(ch) == 8

    def test_digit_char_returns_itself(self):
        for d in "123456789":
            assert _t9_digit_for_char(d) == int(d)

    def test_zero_maps_to_9(self):
        assert _t9_digit_for_char('0') == 9

    def test_special_char_maps_to_9(self):
        assert _t9_digit_for_char('!') == 9


class TestT9DigitForName:
    def test_plain_name(self):
        assert _t9_digit_for_name("Beethoven") == 1  # B → 1

    def test_strips_article_before_mapping(self):
        assert _t9_digit_for_name("The Beatles") == 1  # B → 1

    def test_empty_name_returns_9(self):
        assert _t9_digit_for_name("") == 9

    def test_digit_start(self):
        assert _t9_digit_for_name("2Pac") == 2


class TestFilterByT9Prefix:
    def test_empty_prefix_returns_all(self):
        items = [_artist("Bach"), _artist("Mozart")]
        assert _filter_by_t9_prefix(items, []) == items

    def test_filters_by_first_digit(self):
        bach = _artist("Bach")    # B → 1
        mozart = _artist("Mozart")  # M → 5
        result = _filter_by_t9_prefix([bach, mozart], [1])
        assert result == [bach]

    def test_strips_article_when_filtering(self):
        beatles = _artist("The Beatles")  # B → 1
        rolling = _artist("The Rolling Stones")  # R → 6
        result = _filter_by_t9_prefix([beatles, rolling], [1])
        assert result == [beatles]

    def test_no_match_returns_empty(self):
        items = [_artist("Bach")]
        assert _filter_by_t9_prefix(items, [9, 9, 9]) == []

    def test_skips_items_with_empty_names(self):
        empty = MediaItem(media_key="k", name="", media_type="artist")
        bach = _artist("Bach")
        result = _filter_by_t9_prefix([empty, bach], [1])
        assert result == [bach]


# ---------------------------------------------------------------------------
# Menu.__init__ / initial state
# ---------------------------------------------------------------------------


class TestInit:
    def test_initial_state_is_idle_dial_tone(self, menu):
        assert menu.state == MenuState.IDLE_DIAL_TONE

    def test_handset_not_up(self, menu):
        assert menu._handset_up is False

    def test_opener_not_spoken(self, menu):
        assert menu._opener_spoken is False


# ---------------------------------------------------------------------------
# on_handset_lifted
# ---------------------------------------------------------------------------


class TestOnHandsetLifted:
    def test_sets_state_to_idle_dial_tone(self, menu):
        lifted(menu)
        assert menu.state == MenuState.IDLE_DIAL_TONE

    def test_marks_handset_up(self, menu):
        lifted(menu)
        assert menu._handset_up is True

    def test_plays_dial_tone(self, menu, mock_audio):
        lifted(menu)
        mock_audio.play_dial_tone.assert_called_once()

    def test_resets_opener_spoken(self, menu):
        menu._opener_spoken = True
        lifted(menu)
        assert menu._opener_spoken is False

    def test_calls_tts_resume(self, menu, mock_tts):
        lifted(menu)
        mock_tts.resume.assert_called_once()

    def test_clears_dial_digits(self, menu):
        menu._dial_digits = [1, 2, 3]
        lifted(menu)
        assert menu._dial_digits == []

    def test_clears_nav_stack(self, menu):
        menu._nav_stack = [MenuState.IDLE_MENU]
        lifted(menu)
        assert menu._nav_stack == []

    def test_records_handset_up_time(self, menu):
        lifted(menu, now=42.5)
        assert menu._handset_up_time == 42.5


# ---------------------------------------------------------------------------
# on_handset_on_cradle
# ---------------------------------------------------------------------------


class TestOnHandsetOnCradle:
    def test_marks_handset_down(self, menu):
        lifted(menu)
        menu.on_handset_on_cradle()
        assert menu._handset_up is False

    def test_aborts_tts(self, menu, mock_tts):
        lifted(menu)
        menu.on_handset_on_cradle()
        mock_tts.abort.assert_called_once()

    def test_resets_state_to_idle_dial_tone(self, menu):
        lifted(menu)
        menu._state = MenuState.PLAYING_MENU
        menu.on_handset_on_cradle()
        assert menu.state == MenuState.IDLE_DIAL_TONE

    def test_clears_nav_stack(self, menu):
        menu._nav_stack = [MenuState.IDLE_MENU]
        menu.on_handset_on_cradle()
        assert menu._nav_stack == []

    def test_clears_dial_digits(self, menu):
        menu._dial_digits = [1, 2, 3]
        menu.on_handset_on_cradle()
        assert menu._dial_digits == []

    def test_clears_current_artist(self, menu):
        menu._current_artist = _artist()
        menu.on_handset_on_cradle()
        assert menu._current_artist is None


# ---------------------------------------------------------------------------
# on_digit — handset down
# ---------------------------------------------------------------------------


class TestOnDigitHandsetDown:
    def test_digit_ignored_when_handset_down(self, menu, mock_tts):
        menu.on_digit(1)
        mock_tts.speak_and_play.assert_not_called()

    def test_state_unchanged_when_handset_down(self, menu):
        menu.on_digit(5)
        assert menu.state == MenuState.IDLE_DIAL_TONE


# ---------------------------------------------------------------------------
# on_digit — IDLE_DIAL_TONE
# ---------------------------------------------------------------------------


class TestIdleDialToneDigit:
    def test_digit_zero_goes_to_idle_menu_when_nothing_playing(self, menu, mock_media_client):
        mock_media_client.now_playing.return_value = PlaybackState(item=None, is_paused=False)
        lifted(menu)
        menu.on_digit(0)
        assert menu.state == MenuState.IDLE_MENU

    def test_digit_zero_plays_dtmf(self, menu, mock_audio):
        lifted(menu)
        menu.on_digit(0)
        mock_audio.play_dtmf.assert_called_once_with(0)

    def test_digit_zero_goes_to_playing_menu_when_music_playing(
            self, menu, mock_media_client):
        item = _playlist()
        mock_media_client.now_playing.return_value = PlaybackState(item=item, is_paused=False)
        lifted(menu)
        menu.on_digit(0)
        assert menu.state == MenuState.PLAYING_MENU

    def test_digit_zero_goes_to_radio_menu_when_radio_playing(
            self, menu, mock_media_client, mock_radio):
        mock_media_client.now_playing.return_value = PlaybackState(item=None, is_paused=False)
        mock_radio.is_playing.return_value = True
        lifted(menu)
        menu.on_digit(0)
        assert menu.state == MenuState.RADIO_PLAYING_MENU

    def test_nonzero_digit_enters_direct_dial(self, menu):
        lifted(menu)
        menu.on_digit(5)
        assert menu.state == MenuState.DIRECT_DIAL

    def test_direct_dial_plays_dtmf_for_first_digit(self, menu, mock_audio):
        lifted(menu)
        menu.on_digit(3)
        mock_audio.play_dtmf.assert_called_with(3)

    def test_direct_dial_accumulates_first_digit(self, menu):
        lifted(menu)
        menu.on_digit(7)
        assert menu._dial_digits == [7]


# ---------------------------------------------------------------------------
# tick — timeouts
# ---------------------------------------------------------------------------


class TestTick:
    def test_no_effect_when_handset_down(self, menu, mock_audio):
        menu.tick(now=9999.0)
        mock_audio.play_off_hook_tone.assert_not_called()

    def test_dial_entry_timeout_triggers_off_hook(self, menu, mock_audio):
        lifted(menu, now=0.0)
        menu.tick(now=DIAL_ENTRY_TIMEOUT + 1)
        assert menu.state == MenuState.OFF_HOOK
        mock_audio.play_off_hook_tone.assert_called_once()

    def test_dial_entry_timeout_not_triggered_before_window(self, menu, mock_audio):
        lifted(menu, now=0.0)
        menu.tick(now=DIAL_ENTRY_TIMEOUT - 1)
        assert menu.state != MenuState.OFF_HOOK

    def test_direct_dial_timeout_also_triggers_off_hook(self, menu, mock_audio):
        lifted(menu, now=0.0)
        menu.on_digit(5)
        menu.tick(now=DIAL_ENTRY_TIMEOUT + 1)
        assert menu.state == MenuState.OFF_HOOK

    def test_inactivity_timeout_in_idle_menu(self, menu, mock_audio):
        lifted(menu, now=0.0)
        menu.on_digit(0)  # enter IDLE_MENU
        menu._last_activity_time = 0.0
        menu.tick(now=INACTIVITY_TIMEOUT + 1)
        assert menu.state == MenuState.OFF_HOOK

    def test_inactivity_timeout_not_triggered_before_window(self, menu):
        lifted(menu, now=0.0)
        menu.on_digit(0)
        menu._last_activity_time = 0.0
        menu.tick(now=INACTIVITY_TIMEOUT - 1)
        assert menu.state != MenuState.OFF_HOOK

    def test_off_hook_state_is_not_timed_out_again(self, menu, mock_audio):
        lifted(menu, now=0.0)
        menu._state = MenuState.OFF_HOOK
        menu._last_activity_time = 0.0
        menu.tick(now=9999.0)
        # play_off_hook_tone only called once (from the transition, not from tick)
        mock_audio.play_off_hook_tone.assert_not_called()


# ---------------------------------------------------------------------------
# _deliver_idle_menu
# ---------------------------------------------------------------------------


class TestDeliverIdleMenu:
    def test_state_becomes_idle_menu(self, menu):
        lifted(menu)
        menu.on_digit(0)
        assert menu.state == MenuState.IDLE_MENU

    def test_speaks_operator_opener_first_time(self, menu, mock_tts):
        lifted(menu)
        menu.on_digit(0)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_OPERATOR_OPENER in calls

    def test_does_not_repeat_opener_second_time(self, menu, mock_tts):
        lifted(menu)
        menu.on_digit(0)
        mock_tts.speak_and_play.reset_mock()
        # Go back and re-enter idle menu
        menu.on_digit(0)  # nav-stack pop → re-deliver idle menu
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_OPERATOR_OPENER not in calls

    def test_speaks_greeting(self, menu, mock_tts):
        lifted(menu)
        menu.on_digit(0)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_GREETING in calls

    def test_speaks_extension_hint(self, menu, mock_tts):
        lifted(menu)
        menu.on_digit(0)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_EXTENSION_HINT in calls

    def test_announces_missed_call_when_error_queue_nonempty(
            self, menu, mock_tts, mock_error_queue):
        entry = ErrorEntry(source="x", severity="warning", message="m", count=1, last_happened="now")
        mock_error_queue.get_all.return_value = [entry]
        lifted(menu)
        menu.on_digit(0)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert any(ASSISTANT_NUMBER in t for t in calls)

    def test_no_missed_call_when_error_queue_empty(self, menu, mock_tts, mock_error_queue):
        mock_error_queue.get_all.return_value = []
        lifted(menu)
        menu.on_digit(0)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert not any("missed" in t.lower() for t in calls)

    def test_includes_playlists_option(self, menu, mock_tts, mock_media_store):
        mock_media_store.playlists_has_content = True
        lifted(menu)
        menu.on_digit(0)
        all_text = " ".join(c.args[0] for c in mock_tts.speak_and_play.call_args_list)
        assert "playlist" in all_text.lower()

    def test_includes_artists_option(self, menu, mock_tts, mock_media_store):
        mock_media_store.artists_has_content = True
        lifted(menu)
        menu.on_digit(0)
        all_text = " ".join(c.args[0] for c in mock_tts.speak_and_play.call_args_list)
        assert "artist" in all_text.lower()

    def test_includes_genres_option(self, menu, mock_tts, mock_media_store):
        mock_media_store.genres_has_content = True
        lifted(menu)
        menu.on_digit(0)
        all_text = " ".join(c.args[0] for c in mock_tts.speak_and_play.call_args_list)
        assert "genre" in all_text.lower()

    def test_no_content_goes_off_hook(self, menu, mock_tts, mock_media_store, mock_audio):
        mock_media_store.playlists_has_content = False
        mock_media_store.artists_has_content = False
        mock_media_store.genres_has_content = False
        mock_media_store.get_playlists.return_value = []
        mock_media_store.get_artists.return_value = []
        mock_media_store.get_genres.return_value = []
        lifted(menu)
        menu.on_digit(0)
        assert menu.state == MenuState.OFF_HOOK
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NO_CONTENT in calls

    def test_media_store_error_enters_failure_mode(
            self, menu, mock_tts, mock_media_store):
        import sqlite3
        mock_media_store.playlists_has_content = False
        mock_media_store.get_playlists.side_effect = sqlite3.Error("db error")
        lifted(menu)
        menu.on_digit(0)
        assert menu._failure_mode == "media"
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_MEDIA_FAILURE in calls
        assert SCRIPT_RETRY_PROMPT in calls


# ---------------------------------------------------------------------------
# _deliver_playing_menu
# ---------------------------------------------------------------------------


class TestDeliverPlayingMenu:
    def _enter_playing_menu(self, menu, mock_media_client, is_paused=False, pos=1, total=5):
        item = _playlist()
        mock_media_client.now_playing.return_value = PlaybackState(item=item, is_paused=is_paused)
        mock_media_client.get_queue_position.return_value = (pos, total)
        lifted(menu)
        menu.on_digit(0)

    def test_state_becomes_playing_menu(self, menu, mock_media_client):
        self._enter_playing_menu(menu, mock_media_client)
        assert menu.state == MenuState.PLAYING_MENU

    def test_speaks_playing_greeting(self, menu, mock_tts, mock_media_client):
        self._enter_playing_menu(menu, mock_media_client)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert any("My Playlist" in t for t in calls)

    def test_default_menu_when_playing_not_last_track(
            self, menu, mock_tts, mock_media_client):
        self._enter_playing_menu(menu, mock_media_client, is_paused=False, pos=1, total=5)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_PLAYING_MENU_DEFAULT in calls

    def test_on_hold_menu_when_paused_not_last_track(
            self, menu, mock_tts, mock_media_client):
        self._enter_playing_menu(menu, mock_media_client, is_paused=True, pos=1, total=5)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_PLAYING_MENU_ON_HOLD in calls

    def test_last_track_menu_when_playing_last(
            self, menu, mock_tts, mock_media_client):
        self._enter_playing_menu(menu, mock_media_client, is_paused=False, pos=5, total=5)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_PLAYING_MENU_LAST_TRACK in calls

    def test_on_hold_last_track_when_paused_and_last(
            self, menu, mock_tts, mock_media_client):
        self._enter_playing_menu(menu, mock_media_client, is_paused=True, pos=5, total=5)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_PLAYING_MENU_ON_HOLD_LAST_TRACK in calls

    def test_opener_spoken_once(self, menu, mock_tts, mock_media_client):
        self._enter_playing_menu(menu, mock_media_client)
        opener_calls = sum(
            1 for c in mock_tts.speak_and_play.call_args_list
            if c.args[0] == SCRIPT_OPERATOR_OPENER
        )
        assert opener_calls == 1


# ---------------------------------------------------------------------------
# _deliver_radio_playing_menu
# ---------------------------------------------------------------------------


class TestDeliverRadioPlayingMenu:
    def _enter_radio_menu(self, menu, mock_media_client, mock_radio, name="KEXP", freq_hz=90_300_000.0):
        mock_media_client.now_playing.return_value = PlaybackState(item=None, is_paused=False)
        mock_radio.is_playing.return_value = True
        menu._current_radio_name = name
        menu._current_radio_freq_hz = freq_hz
        lifted(menu)
        menu.on_digit(0)

    def test_state_becomes_radio_playing_menu(self, menu, mock_media_client, mock_radio):
        self._enter_radio_menu(menu, mock_media_client, mock_radio)
        assert menu.state == MenuState.RADIO_PLAYING_MENU

    def test_speaks_radio_greeting_with_name(self, menu, mock_tts, mock_media_client, mock_radio):
        self._enter_radio_menu(menu, mock_media_client, mock_radio, name="KEXP")
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert any("KEXP" in t for t in calls)

    def test_speaks_radio_playing_menu(self, menu, mock_tts, mock_media_client, mock_radio):
        self._enter_radio_menu(menu, mock_media_client, mock_radio)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_RADIO_PLAYING_MENU in calls

    def test_digit_3_stops_radio_and_delivers_idle(
            self, menu, mock_radio, mock_media_client):
        self._enter_radio_menu(menu, mock_media_client, mock_radio)
        mock_radio.is_playing.return_value = False
        menu.on_digit(3)
        mock_radio.stop.assert_called_once()
        assert menu.state == MenuState.IDLE_MENU

    def test_digit_0_stops_radio_and_delivers_idle(
            self, menu, mock_radio, mock_media_client):
        self._enter_radio_menu(menu, mock_media_client, mock_radio)
        mock_radio.is_playing.return_value = False
        menu.on_digit(0)
        mock_radio.stop.assert_called_once()
        assert menu.state == MenuState.IDLE_MENU

    def test_other_digit_speaks_not_in_service(
            self, menu, mock_tts, mock_media_client, mock_radio):
        self._enter_radio_menu(menu, mock_media_client, mock_radio)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(5)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls


# ---------------------------------------------------------------------------
# IDLE_MENU digit handling
# ---------------------------------------------------------------------------


class TestIdleMenuDigits:
    def _in_idle_menu(self, menu):
        lifted(menu)
        menu.on_digit(0)
        assert menu.state == MenuState.IDLE_MENU

    def test_digit_1_enters_browse_playlists(self, menu, mock_media_store):
        mock_media_store.playlists_has_content = True
        mock_media_store.get_playlists.return_value = [_playlist("Jazz")]
        self._in_idle_menu(menu)
        menu.on_digit(1)
        assert menu.state == MenuState.BROWSE_PLAYLISTS

    def test_digit_2_enters_browse_artists(self, menu, mock_media_store):
        mock_media_store.get_artists.return_value = [_artist("Bach")]
        self._in_idle_menu(menu)
        menu.on_digit(2)
        assert menu.state == MenuState.BROWSE_ARTISTS

    def test_digit_3_enters_browse_genres(self, menu, mock_media_store):
        mock_media_store.get_genres.return_value = [_genre("Jazz")]
        self._in_idle_menu(menu)
        menu.on_digit(3)
        assert menu.state == MenuState.BROWSE_GENRES

    def test_shuffle_option_calls_shuffle_all(self, menu, mock_media_client, mock_media_store):
        mock_media_store.playlists_has_content = True
        mock_media_store.artists_has_content = True
        mock_media_store.genres_has_content = True
        self._in_idle_menu(menu)
        menu.on_digit(4)  # option 4 is shuffle when all three categories present
        mock_media_client.shuffle_all.assert_called_once()

    def test_shuffle_speaks_connecting(self, menu, mock_tts, mock_media_store):
        mock_media_store.playlists_has_content = True
        mock_media_store.artists_has_content = True
        mock_media_store.genres_has_content = True
        self._in_idle_menu(menu)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(4)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_SHUFFLE_CONNECTING in calls

    def test_shuffle_transitions_to_playing_menu(self, menu, mock_media_store):
        mock_media_store.playlists_has_content = True
        mock_media_store.artists_has_content = True
        mock_media_store.genres_has_content = True
        self._in_idle_menu(menu)
        menu.on_digit(4)
        assert menu.state == MenuState.PLAYING_MENU

    def test_out_of_range_digit_speaks_not_in_service(self, menu, mock_tts):
        self._in_idle_menu(menu)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(9)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls

    def test_failure_mode_digit_1_retries(
            self, menu, mock_tts, mock_media_store):
        menu._state = MenuState.IDLE_MENU
        menu._handset_up = True
        menu._failure_mode = "media"
        menu.on_digit(1)
        mock_media_store.refresh.assert_called_once()

    def test_failure_mode_retry_success_clears_failure_mode(
            self, menu, mock_media_store):
        menu._state = MenuState.IDLE_MENU
        menu._handset_up = True
        menu._failure_mode = "media"
        mock_media_store.refresh.return_value = {"playlists": "ok"}
        menu.on_digit(1)
        assert menu._failure_mode is None

    def test_failure_mode_retry_failure_speaks_media_failure(
            self, menu, mock_tts, mock_media_store):
        menu._state = MenuState.IDLE_MENU
        menu._handset_up = True
        menu._failure_mode = "media"
        mock_media_store.refresh.return_value = {"playlists": "error"}
        menu.on_digit(1)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_MEDIA_FAILURE in calls

    def test_failure_mode_non_1_digit_speaks_not_in_service(
            self, menu, mock_tts):
        menu._state = MenuState.IDLE_MENU
        menu._handset_up = True
        menu._failure_mode = "media"
        menu.on_digit(5)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls


# ---------------------------------------------------------------------------
# PLAYING_MENU digit handling
# ---------------------------------------------------------------------------


class TestPlayingMenuDigits:
    def _in_playing_menu(self, menu, mock_media_client, is_paused=False, pos=1, total=5):
        item = _playlist()
        mock_media_client.now_playing.return_value = PlaybackState(item=item, is_paused=is_paused)
        mock_media_client.get_queue_position.return_value = (pos, total)
        lifted(menu)
        menu.on_digit(0)
        assert menu.state == MenuState.PLAYING_MENU

    def test_digit_1_pauses_when_playing(
            self, menu, mock_media_client):
        self._in_playing_menu(menu, mock_media_client, is_paused=False)
        mock_media_client.now_playing.return_value = PlaybackState(
            item=_playlist(), is_paused=False)
        menu.on_digit(1)
        mock_media_client.pause.assert_called_once()

    def test_digit_1_unpauses_when_paused(
            self, menu, mock_media_client):
        self._in_playing_menu(menu, mock_media_client, is_paused=True)
        mock_media_client.now_playing.return_value = PlaybackState(
            item=_playlist(), is_paused=True)
        menu.on_digit(1)
        mock_media_client.unpause.assert_called_once()

    def test_digit_2_skips_when_not_last_track(
            self, menu, mock_media_client):
        self._in_playing_menu(menu, mock_media_client, pos=1, total=5)
        mock_media_client.get_queue_position.return_value = (1, 5)
        menu.on_digit(2)
        mock_media_client.skip.assert_called_once()

    def test_digit_2_speaks_not_in_service_on_last_track(
            self, menu, mock_tts, mock_media_client):
        self._in_playing_menu(menu, mock_media_client, pos=5, total=5)
        mock_media_client.get_queue_position.return_value = (5, 5)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(2)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls

    def test_digit_3_stops_media(self, menu, mock_media_client):
        self._in_playing_menu(menu, mock_media_client)
        menu.on_digit(3)
        mock_media_client.stop.assert_called_once()

    def test_digit_3_transitions_to_idle_menu(
            self, menu, mock_media_client):
        self._in_playing_menu(menu, mock_media_client)
        mock_media_client.now_playing.return_value = PlaybackState(item=None, is_paused=False)
        menu.on_digit(3)
        assert menu.state == MenuState.IDLE_MENU

    def test_other_digit_speaks_not_in_service(
            self, menu, mock_tts, mock_media_client):
        self._in_playing_menu(menu, mock_media_client)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(7)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls


# ---------------------------------------------------------------------------
# Browse / T9 narrowing
# ---------------------------------------------------------------------------


class TestBrowse:
    def _in_browse_artists(self, menu, mock_media_store, items):
        mock_media_store.get_artists.return_value = items
        lifted(menu)
        menu.on_digit(0)  # idle menu
        menu.on_digit(2)  # browse artists (option 2 with playlists+artists+genres)
        assert menu.state == MenuState.BROWSE_ARTISTS

    def test_t9_narrowing_speaks_next_letter_prompt_when_too_many(
            self, menu, mock_tts, mock_media_store):
        # 9 items starting with B, more than MAX_MENU_OPTIONS(8)
        items = [_artist(f"Beta{i}", f"k{i}") for i in range(9)]
        self._in_browse_artists(menu, mock_media_store, items)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(1)  # B → digit 1
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_BROWSE_PROMPT_NEXT_LETTER in calls

    def test_t9_narrowing_lists_items_when_few_enough(
            self, menu, mock_tts, mock_media_store):
        items = [_artist("Bach", "k1"), _artist("Beethoven", "k2")]
        self._in_browse_artists(menu, mock_media_store, items)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(1)  # B → digit 1
        all_text = " ".join(c.args[0] for c in mock_tts.speak_and_play.call_args_list)
        assert "Bach" in all_text
        assert "Beethoven" in all_text

    def test_t9_auto_select_when_single_match(
            self, menu, mock_tts, mock_media_store, mock_phone_book, mock_media_client):
        items = [_artist("Bach", "artist:bach")]
        self._in_browse_artists(menu, mock_media_store, items)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(1)  # B → single match → auto-select
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert any("Bach" in t for t in calls)

    def test_t9_no_match_speaks_not_in_service(
            self, menu, mock_tts, mock_media_store):
        items = [_artist("Mozart", "k1")]  # M → digit 5
        self._in_browse_artists(menu, mock_media_store, items)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(1)  # no match
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls

    def test_t9_no_match_does_not_consume_prefix(
            self, menu, mock_media_store):
        items = [_artist("Mozart", "k1")]
        self._in_browse_artists(menu, mock_media_store, items)
        prefix_before = list(menu._browse_prefix)
        menu.on_digit(1)
        # Prefix should not grow on a no-match
        assert menu._browse_prefix == prefix_before

    def test_listed_mode_digit_selects_item(
            self, menu, mock_media_store, mock_phone_book, mock_media_client):
        items = [_artist("Bach", "artist:bach"), _artist("Beethoven", "artist:beethoven")]
        self._in_browse_artists(menu, mock_media_store, items)
        menu.on_digit(1)  # narrows to list
        menu.on_digit(1)  # selects Bach
        assert menu.state == MenuState.ARTIST_SUBMENU

    def test_digit_0_pops_nav_stack(self, menu, mock_media_store):
        items = [_artist("Bach", "k1"), _artist("Beethoven", "k2")]
        self._in_browse_artists(menu, mock_media_store, items)
        menu.on_digit(1)  # narrow
        menu.on_digit(0)  # back → idle menu
        assert menu.state == MenuState.IDLE_MENU

    def test_browse_playlists_prompt_spoken(self, menu, mock_tts, mock_media_store):
        mock_media_store.get_playlists.return_value = [_playlist("Pop")]
        lifted(menu)
        menu.on_digit(0)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(1)  # browse playlists
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_BROWSE_PROMPT_PLAYLIST in calls

    def test_browse_genres_prompt_spoken(self, menu, mock_tts, mock_media_store):
        mock_media_store.get_genres.return_value = [_genre("Jazz")]
        lifted(menu)
        menu.on_digit(0)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(3)  # browse genres
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_BROWSE_PROMPT_GENRE in calls


# ---------------------------------------------------------------------------
# Playlist / album selection → play
# ---------------------------------------------------------------------------


class TestSelectItem:
    def test_selecting_playlist_calls_play(
            self, menu, mock_media_store, mock_media_client, mock_phone_book):
        item = _playlist("Pop", "pl:pop")
        mock_media_store.get_playlists.return_value = [item]
        mock_phone_book.assign_or_get.return_value = "1234567"
        lifted(menu)
        menu.on_digit(0)
        menu.on_digit(1)  # browse playlists
        menu.on_digit(6)  # P → digit 6
        mock_media_client.play.assert_called_with("pl:pop")

    def test_selecting_playlist_transitions_to_playing_menu(
            self, menu, mock_media_store, mock_phone_book):
        item = _playlist("Pop", "pl:pop")
        mock_media_store.get_playlists.return_value = [item]
        lifted(menu)
        menu.on_digit(0)
        menu.on_digit(1)
        menu.on_digit(6)  # P → single match → auto-select
        assert menu.state == MenuState.PLAYING_MENU

    def test_selecting_genre_calls_play_tracks(
            self, menu, mock_media_store, mock_media_client, mock_phone_book):
        item = _genre("Jazz", "genre:Jazz")
        mock_media_store.get_genres.return_value = [item]
        mock_media_client.get_tracks_for_genre.return_value = ["track:1", "track:2"]
        lifted(menu)
        menu.on_digit(0)
        menu.on_digit(3)  # browse genres
        menu.on_digit(4)  # J → digit 4
        mock_media_client.play_tracks.assert_called_with(["track:1", "track:2"], shuffle=True)

    def test_selecting_genre_with_no_tracks_speaks_not_in_service(
            self, menu, mock_tts, mock_media_store, mock_media_client):
        item = _genre("Jazz", "genre:Jazz")
        mock_media_store.get_genres.return_value = [item]
        mock_media_client.get_tracks_for_genre.return_value = []
        lifted(menu)
        menu.on_digit(0)
        menu.on_digit(3)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(4)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls

    def test_selecting_genre_with_no_tracks_returns_to_browse_genres(
            self, menu, mock_media_store, mock_media_client):
        item = _genre("Jazz", "genre:Jazz")
        mock_media_store.get_genres.return_value = [item]
        mock_media_client.get_tracks_for_genre.return_value = []
        lifted(menu)
        menu.on_digit(0)
        menu.on_digit(3)
        menu.on_digit(4)
        assert menu.state == MenuState.BROWSE_GENRES


# ---------------------------------------------------------------------------
# ARTIST_SUBMENU
# ---------------------------------------------------------------------------


class TestArtistSubmenu:
    def _in_artist_submenu(self, menu, mock_media_store, mock_phone_book,
                           has_albums=False):
        artist = _artist("Bach", "artist:bach")
        mock_media_store.get_artists.return_value = [artist]
        albums = [_album("WTC", "album:wtc")] if has_albums else []
        mock_media_store.get_albums_for_artist.return_value = albums
        mock_phone_book.assign_or_get.return_value = "1234567"
        lifted(menu)
        menu.on_digit(0)  # idle menu
        menu.on_digit(2)  # browse artists
        menu.on_digit(1)  # B → auto-select Bach
        assert menu.state == MenuState.ARTIST_SUBMENU

    def test_digit_1_plays_artist(
            self, menu, mock_media_store, mock_phone_book, mock_media_client):
        self._in_artist_submenu(menu, mock_media_store, mock_phone_book)
        menu.on_digit(1)
        mock_media_client.play.assert_called_with("artist:bach")

    def test_digit_1_transitions_to_playing_menu(
            self, menu, mock_media_store, mock_phone_book):
        self._in_artist_submenu(menu, mock_media_store, mock_phone_book)
        menu.on_digit(1)
        assert menu.state == MenuState.PLAYING_MENU

    def test_digit_2_with_albums_enters_browse_albums(
            self, menu, mock_media_store, mock_phone_book):
        self._in_artist_submenu(menu, mock_media_store, mock_phone_book, has_albums=True)
        menu.on_digit(2)
        assert menu.state == MenuState.BROWSE_ALBUMS

    def test_digit_2_without_albums_speaks_not_in_service(
            self, menu, mock_tts, mock_media_store, mock_phone_book):
        self._in_artist_submenu(menu, mock_media_store, mock_phone_book, has_albums=False)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(2)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls

    def test_artist_submenu_menu_includes_album_option_when_available(
            self, menu, mock_tts, mock_media_store, mock_phone_book):
        self._in_artist_submenu(menu, mock_media_store, mock_phone_book, has_albums=True)
        all_text = " ".join(c.args[0] for c in mock_tts.speak_and_play.call_args_list)
        assert "album" in all_text.lower()


# ---------------------------------------------------------------------------
# Direct dial
# ---------------------------------------------------------------------------


class TestDirectDial:
    def _dial(self, menu, digits):
        lifted(menu, now=0.0)
        for d in digits:
            menu.on_digit(d)

    def test_seven_digits_completes_dial(self, menu, mock_phone_book):
        self._dial(menu, [1, 2, 3, 4, 5, 6, 7])
        mock_phone_book.lookup_by_phone_number.assert_called_once_with("1234567")

    def test_extra_digits_ignored(self, menu, mock_phone_book):
        self._dial(menu, [1, 2, 3, 4, 5, 6, 7, 8])
        mock_phone_book.lookup_by_phone_number.assert_called_once()

    def test_unknown_number_speaks_not_in_service(
            self, menu, mock_tts, mock_phone_book):
        mock_phone_book.lookup_by_phone_number.return_value = None
        self._dial(menu, [1, 2, 3, 4, 5, 6, 7])
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls

    def test_unknown_number_delivers_idle_menu_when_nothing_playing(
            self, menu, mock_phone_book, mock_media_client):
        mock_phone_book.lookup_by_phone_number.return_value = None
        mock_media_client.now_playing.return_value = PlaybackState(item=None, is_paused=False)
        self._dial(menu, [1, 2, 3, 4, 5, 6, 7])
        assert menu.state == MenuState.IDLE_MENU

    def test_unknown_number_delivers_playing_menu_when_music_playing(
            self, menu, mock_phone_book, mock_media_client):
        mock_phone_book.lookup_by_phone_number.return_value = None
        mock_media_client.now_playing.return_value = PlaybackState(
            item=_playlist(), is_paused=False)
        self._dial(menu, [1, 2, 3, 4, 5, 6, 7])
        assert menu.state == MenuState.PLAYING_MENU

    def test_known_playlist_calls_play(
            self, menu, mock_phone_book, mock_media_client, mock_tts):
        mock_phone_book.lookup_by_phone_number.return_value = {
            "media_key": "pl:jazz", "media_type": "playlist", "name": "Jazz"
        }
        self._dial(menu, [1, 2, 3, 4, 5, 6, 7])
        mock_media_client.play.assert_called_with("pl:jazz")

    def test_known_playlist_transitions_to_playing_menu(
            self, menu, mock_phone_book, mock_tts):
        mock_phone_book.lookup_by_phone_number.return_value = {
            "media_key": "pl:jazz", "media_type": "playlist", "name": "Jazz"
        }
        self._dial(menu, [1, 2, 3, 4, 5, 6, 7])
        assert menu.state == MenuState.PLAYING_MENU

    def test_connecting_announcement_includes_name(
            self, menu, mock_phone_book, mock_tts):
        mock_phone_book.lookup_by_phone_number.return_value = {
            "media_key": "pl:jazz", "media_type": "playlist", "name": "Jazz"
        }
        self._dial(menu, [1, 2, 3, 4, 5, 6, 7])
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert any("Jazz" in t for t in calls)

    def test_radio_entry_plays_radio(
            self, menu, mock_phone_book, mock_radio, mock_media_client):
        mock_phone_book.lookup_by_phone_number.return_value = {
            "media_key": "radio:90300000.0", "media_type": "radio", "name": "KEXP"
        }
        self._dial(menu, [5, 5, 5, 0, 9, 0, 3])
        mock_radio.play.assert_called_once_with(90300000.0)

    def test_radio_entry_stops_media_first(
            self, menu, mock_phone_book, mock_radio, mock_media_client):
        mock_phone_book.lookup_by_phone_number.return_value = {
            "media_key": "radio:90300000.0", "media_type": "radio", "name": "KEXP"
        }
        self._dial(menu, [5, 5, 5, 0, 9, 0, 3])
        mock_media_client.stop.assert_called_once()

    def test_radio_entry_transitions_to_radio_playing_menu(
            self, menu, mock_phone_book, mock_radio, mock_tts):
        mock_phone_book.lookup_by_phone_number.return_value = {
            "media_key": "radio:90300000.0", "media_type": "radio", "name": "KEXP"
        }
        self._dial(menu, [5, 5, 5, 0, 9, 0, 3])
        assert menu.state == MenuState.RADIO_PLAYING_MENU

    def test_assistant_number_enters_assistant(self, menu):
        digits = [int(d) for d in ASSISTANT_NUMBER]
        self._dial(menu, digits)
        assert menu.state == MenuState.ASSISTANT

    def test_dtmf_played_for_each_direct_dial_digit(self, menu, mock_audio, mock_phone_book):
        self._dial(menu, [1, 2, 3, 4, 5, 6, 7])
        dtmf_calls = [c.args[0] for c in mock_audio.play_dtmf.call_args_list]
        assert dtmf_calls == [1, 2, 3, 4, 5, 6, 7]


# ---------------------------------------------------------------------------
# Navigation (digit 0 = back)
# ---------------------------------------------------------------------------


class TestNavigation:
    def test_digit_0_in_browse_returns_to_idle_menu(self, menu, mock_media_store):
        mock_media_store.get_playlists.return_value = [_playlist("Pop")]
        lifted(menu)
        menu.on_digit(0)  # idle menu
        menu.on_digit(1)  # browse playlists
        assert menu.state == MenuState.BROWSE_PLAYLISTS
        menu.on_digit(0)  # back
        assert menu.state == MenuState.IDLE_MENU

    def test_digit_0_at_idle_menu_re_delivers_top_level(
            self, menu, mock_tts, mock_media_client):
        lifted(menu)
        menu.on_digit(0)  # idle menu (nav stack is empty now)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(0)  # at top → re-deliver
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_GREETING in calls


# ---------------------------------------------------------------------------
# Assistant state
# ---------------------------------------------------------------------------


class TestAssistant:
    def _enter_assistant(self, menu, mock_error_queue, errors=None, warnings=None):
        mock_error_queue.get_all.return_value = (errors or []) + (warnings or [])
        mock_error_queue.get_by_severity.side_effect = lambda sev: (
            errors if sev == "error" and errors else
            warnings if sev == "warning" and warnings else []
        )
        digits = [int(d) for d in ASSISTANT_NUMBER]
        lifted(menu, now=0.0)
        for d in digits:
            menu.on_digit(d)
        assert menu.state == MenuState.ASSISTANT

    def test_speaks_assistant_greeting(self, menu, mock_tts, mock_error_queue):
        self._enter_assistant(menu, mock_error_queue)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_ASSISTANT_GREETING in calls

    def test_all_clear_spoken_when_no_errors(self, menu, mock_tts, mock_error_queue):
        self._enter_assistant(menu, mock_error_queue)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_ASSISTANT_ALL_CLEAR in calls

    def test_refresh_option_offered_in_all_clear(self, menu, mock_tts, mock_error_queue):
        self._enter_assistant(menu, mock_error_queue)
        all_text = " ".join(c.args[0] for c in mock_tts.speak_and_play.call_args_list)
        assert "refresh" in all_text.lower()

    def test_digit_0_from_assistant_delivers_idle_menu(
            self, menu, mock_error_queue, mock_media_client):
        mock_media_client.now_playing.return_value = PlaybackState(item=None, is_paused=False)
        self._enter_assistant(menu, mock_error_queue)
        menu.on_digit(0)
        assert menu.state == MenuState.IDLE_MENU

    def test_digit_9_from_assistant_delivers_idle_menu(
            self, menu, mock_error_queue, mock_media_client):
        mock_media_client.now_playing.return_value = PlaybackState(item=None, is_paused=False)
        self._enter_assistant(menu, mock_error_queue)
        menu.on_digit(9)
        assert menu.state == MenuState.IDLE_MENU

    def test_refresh_digit_calls_media_store_refresh(
            self, menu, mock_error_queue, mock_media_store):
        self._enter_assistant(menu, mock_error_queue)
        # In all-clear mode, refresh is digit 1
        menu.on_digit(1)
        mock_media_store.refresh.assert_called_once()

    def test_refresh_success_speaks_success(
            self, menu, mock_tts, mock_error_queue, mock_media_store):
        self._enter_assistant(menu, mock_error_queue)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(1)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_ASSISTANT_REFRESH_SUCCESS in calls

    def test_refresh_failure_speaks_failure(
            self, menu, mock_tts, mock_error_queue, mock_media_store):
        import sqlite3
        self._enter_assistant(menu, mock_error_queue)
        mock_media_store.refresh.side_effect = sqlite3.Error("fail")
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(1)
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_ASSISTANT_REFRESH_FAILURE in calls

    def test_with_errors_speaks_error_count(
            self, menu, mock_tts, mock_error_queue):
        errors = [
            ErrorEntry(source="s", severity="error", message="err", count=1, last_happened="now")
        ]
        self._enter_assistant(menu, mock_error_queue, errors=errors)
        all_text = " ".join(c.args[0] for c in mock_tts.speak_and_play.call_args_list)
        assert "error" in all_text.lower()

    def test_reading_digit_1_continues_to_next_page(
            self, menu, mock_tts, mock_error_queue):
        errors = [
            ErrorEntry(source="s", severity="error", message=f"err{i}", count=1, last_happened="now")
            for i in range(6)
        ]
        self._enter_assistant(menu, mock_error_queue, errors=errors)
        # Find the errors digit from digit_map
        error_digit = None
        for d, (kind, _) in menu._assistant_digit_map.items():
            if kind == "errors":
                error_digit = d
                break
        assert error_digit is not None
        menu.on_digit(error_digit)  # start reading
        assert menu._assistant_mode == "reading"
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(1)  # continue
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert any("err" in t for t in calls)

    def test_reading_digit_0_redirects_to_menu(
            self, menu, mock_tts, mock_error_queue, mock_media_client):
        errors = [
            ErrorEntry(source="s", severity="error", message="err", count=1, last_happened="now")
        ]
        mock_media_client.now_playing.return_value = PlaybackState(item=None, is_paused=False)
        self._enter_assistant(menu, mock_error_queue, errors=errors)
        error_digit = next(
            d for d, (kind, _) in menu._assistant_digit_map.items() if kind == "errors"
        )
        menu.on_digit(error_digit)
        menu.on_digit(0)
        assert menu.state == MenuState.IDLE_MENU

    def test_invalid_digit_in_assistant_menu_speaks_not_in_service(
            self, menu, mock_tts, mock_error_queue):
        self._enter_assistant(menu, mock_error_queue)
        mock_tts.speak_and_play.reset_mock()
        menu.on_digit(7)  # not in digit_map
        calls = [c.args[0] for c in mock_tts.speak_and_play.call_args_list]
        assert SCRIPT_NOT_IN_SERVICE in calls
