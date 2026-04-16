"""Tests for src/session.py — Session lifecycle (§10).

All tests use injected mocks; no hardware or network required.
"""

import pytest
from src.gpio_handler import GpioEvent
from src.interfaces import MediaItem, PlaybackState
from src.menu import MenuState
from src.constants import (
    DIRECT_DIAL_DISAMBIGUATION_TIMEOUT, PHONE_NUMBER_LENGTH,
    DIAL_TONE_TIMEOUT_IDLE, DIAL_TONE_TIMEOUT_PLAYING,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                 mock_error_queue, tmp_path, mock_radio=None):
    """Build a Session with all mocked dependencies."""
    from src.phone_book import PhoneBook
    from src.session import Session
    from src.radio import MockRadio
    db = str(tmp_path / "phone_book.db")
    phone_book = PhoneBook(db_path=db)
    radio = mock_radio if mock_radio is not None else MockRadio()
    return Session(
        audio=mock_audio,
        tts=mock_tts,
        media_client=mock_media_client,
        media_store=mock_media_store,
        phone_book=phone_book,
        error_queue=mock_error_queue,
        radio=radio,
    )


def tts_calls(mock_tts):
    """Return list of texts passed to speak_and_play."""
    return [args[0] for method, *args in mock_tts.calls if method == 'speak_and_play']


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSessionHandset:
    """Handset lift and cradle events."""

    def test_handset_lifted_starts_dial_tone(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """HANDSET_LIFTED event → dial tone begins."""
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        # play_tone should have been called
        assert any(c[0] == 'play_tone' for c in mock_audio.calls)

    def test_dial_tone_timeout_idle(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """No digit within idle timeout → dial tone stops, idle menu prompt begins."""
        from src.menu import SCRIPT_GREETING
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        session.tick(now=DIAL_TONE_TIMEOUT_IDLE + 1.0)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_GREETING in t for t in texts)

    def test_dial_tone_timeout_playing(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """No digit within playing timeout → playing menu prompt begins."""
        from src.menu import SCRIPT_PLAYING_MENU_DEFAULT
        mock_media_client.set_now_playing(PlaybackState(MediaItem("/pl/1", "Jazz", "playlist"), False))
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        session.tick(now=DIAL_TONE_TIMEOUT_PLAYING + 1.0)
        texts = tts_calls(mock_tts)
        assert any("Jazz" in t for t in texts) or any(SCRIPT_PLAYING_MENU_DEFAULT in t for t in texts)

    def test_handset_on_cradle_stops_audio(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """HANDSET_ON_CRADLE → all audio stops."""
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        mock_audio.calls.clear()
        session.handle_event(GpioEvent.HANDSET_ON_CRADLE, now=1.0)
        assert any(c[0] == 'stop' for c in mock_audio.calls)

    def test_handset_on_cradle_does_not_stop_plex(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """HANDSET_ON_CRADLE while music playing → plex_client.stop() NOT called."""
        mock_media_client.set_now_playing(PlaybackState(MediaItem("/pl/1", "Jazz", "playlist"), False))
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        mock_media_client.calls.clear()
        session.handle_event(GpioEvent.HANDSET_ON_CRADLE, now=1.0)
        stop_calls = [c for c in mock_media_client.calls if c[0] == 'stop']
        assert len(stop_calls) == 0

    def test_digit_after_hangup_ignored(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Digit event after HANDSET_ON_CRADLE → ignored, no state change."""
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        session.handle_event(GpioEvent.HANDSET_ON_CRADLE, now=1.0)
        mock_tts.calls.clear()
        mock_audio.calls.clear()
        session.handle_event((GpioEvent.DIGIT_DIALED, 5), now=2.0)
        # No TTS or audio changes should happen
        assert len(tts_calls(mock_tts)) == 0


class TestSessionDirectDial:
    """Direct dial via session."""

    def test_direct_dial_during_dial_tone(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Two digits within disambiguation timeout during dial tone → DTMF tones played."""
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        session.handle_event((GpioEvent.DIGIT_DIALED, 5), now=0.5)
        session.handle_event((GpioEvent.DIGIT_DIALED, 5), now=0.6)
        dtmf_calls = [c for c in mock_audio.calls if c[0] == 'play_dtmf']
        assert len(dtmf_calls) >= 2

    def test_single_digit_during_dial_tone_treated_as_navigation(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """One digit during dial tone, no second → treated as menu input."""
        from src.menu import SCRIPT_GREETING
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        session.tick(now=DIAL_TONE_TIMEOUT_IDLE + 1.0)  # deliver idle menu
        mock_tts.calls.clear()
        session.handle_event((GpioEvent.DIGIT_DIALED, 1), now=10.0)
        # Wait for disambiguation timeout
        session.tick(now=10.0 + DIRECT_DIAL_DISAMBIGUATION_TIMEOUT + 0.1)
        texts = tts_calls(mock_tts)
        # Digit 1 in idle menu → browse playlists
        assert len(texts) > 0

    def test_direct_dial_known_number(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """7-digit number matches phone book entry → plays that media."""
        from src.phone_book import PhoneBook
        db = str(tmp_path / "phone_book.db")
        pb = PhoneBook(db_path=db)
        number = pb.assign_or_get("/pl/1", "playlist", "Jazz")
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        session.tick(now=DIAL_TONE_TIMEOUT_IDLE + 1.0)
        mock_media_client.calls.clear()
        # Dial the number
        t = 10.0
        digits = [int(c) for c in number]
        session.handle_event((GpioEvent.DIGIT_DIALED, digits[0]), now=t)
        session.handle_event((GpioEvent.DIGIT_DIALED, digits[1]), now=t + 0.05)
        for d in digits[2:]:
            t += 0.1
            session.handle_event((GpioEvent.DIGIT_DIALED, d), now=t)
        play_calls = [c for c in mock_media_client.calls if c[0] == 'play']
        assert len(play_calls) >= 1

    def test_direct_dial_unknown_number(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """7-digit unknown number → TTS plays SCRIPT_NOT_IN_SERVICE."""
        from src.menu import SCRIPT_NOT_IN_SERVICE
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        session.tick(now=DIAL_TONE_TIMEOUT_IDLE + 1.0)
        mock_tts.calls.clear()
        # Dial unknown number: 1234567
        number = "1234567"
        t = 10.0
        digits = [int(c) for c in number]
        session.handle_event((GpioEvent.DIGIT_DIALED, digits[0]), now=t)
        session.handle_event((GpioEvent.DIGIT_DIALED, digits[1]), now=t + 0.05)
        for d in digits[2:]:
            t += 0.1
            session.handle_event((GpioEvent.DIGIT_DIALED, d), now=t)
        texts = tts_calls(mock_tts)
        assert any(SCRIPT_NOT_IN_SERVICE in txt for txt in texts)

    def test_direct_dial_ignores_digits_after_7(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """8th digit after PHONE_NUMBER_LENGTH reached → ignored, no second lookup."""
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        session.tick(now=DIAL_TONE_TIMEOUT_IDLE + 1.0)
        # Dial 8 digits: 12345678
        t = 10.0
        session.handle_event((GpioEvent.DIGIT_DIALED, 1), now=t)
        session.handle_event((GpioEvent.DIGIT_DIALED, 2), now=t + 0.05)
        for d in [3, 4, 5, 6, 7, 8]:  # 8th digit
            t += 0.1
            session.handle_event((GpioEvent.DIGIT_DIALED, d), now=t)
        # lookup should only fire once (7 digits)
        not_in_service_count = sum(
            1 for txt in tts_calls(mock_tts)
            if "not in service" in txt.lower()
        )
        assert not_in_service_count <= 1

    def test_direct_dial_hangup_before_7_digits(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Hang up before PHONE_NUMBER_LENGTH digits → silent cleanup, no lookup."""
        mock_media_store.set_playlists([MediaItem("/pl/1", "Jazz", "playlist")])
        mock_media_store.set_artists([])
        mock_media_store.set_genres([])
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.handle_event(GpioEvent.HANDSET_LIFTED, now=0.0)
        session.tick(now=DIAL_TONE_TIMEOUT_IDLE + 1.0)
        mock_media_client.calls.clear()
        mock_tts.calls.clear()
        # Start dialing 3 digits
        t = 10.0
        session.handle_event((GpioEvent.DIGIT_DIALED, 1), now=t)
        session.handle_event((GpioEvent.DIGIT_DIALED, 2), now=t + 0.05)
        session.handle_event((GpioEvent.DIGIT_DIALED, 3), now=t + 0.1)
        # Hang up before completing
        session.handle_event(GpioEvent.HANDSET_ON_CRADLE, now=t + 0.2)
        # No lookup or not-in-service
        play_calls = [c for c in mock_media_client.calls if c[0] == 'play']
        not_in_service = [txt for txt in tts_calls(mock_tts) if "not in service" in txt.lower()]
        assert len(play_calls) == 0
        assert len(not_in_service) == 0


# ---------------------------------------------------------------------------
# F-24: Session passes radio to Menu
# ---------------------------------------------------------------------------

class TestSessionRadio:
    """Session forwards radio to Menu."""

    def test_session_passes_radio_to_menu(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store,
            mock_error_queue, mock_radio, tmp_path):
        """Session constructed with mock_radio → session.menu._radio is mock_radio."""
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path, mock_radio=mock_radio)
        assert session.menu._radio is mock_radio
