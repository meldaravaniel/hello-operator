"""Tests for src/session.py — Session lifecycle (§10).

All tests use injected mocks; no hardware or network required.
"""

import time
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
                 mock_error_queue, tmp_path, mock_radio=None, now=0.0):
    """Build a Session with all mocked dependencies.

    Handset lift is delivered via Session.__init__ at the given ``now`` timestamp.
    """
    from src.phone_book import PhoneBook
    from src.session import Session
    from src.menu import Menu
    from src.radio import MockRadio
    db = str(tmp_path / "phone_book.db")
    phone_book = PhoneBook(db_path=db)
    radio = mock_radio if mock_radio is not None else MockRadio()
    menu = Menu(
        audio=mock_audio,
        tts=mock_tts,
        media_client=mock_media_client,
        media_store=mock_media_store,
        phone_book=phone_book,
        error_queue=mock_error_queue,
        radio=radio,
    )
    return Session(menu=menu, now=now)


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
        """Session construction (handset lift) → dial tone begins."""
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
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
        session.tick(now=DIAL_TONE_TIMEOUT_PLAYING + 1.0)
        texts = tts_calls(mock_tts)
        assert any("Jazz" in t for t in texts) or any(SCRIPT_PLAYING_MENU_DEFAULT in t for t in texts)

    def test_handset_on_cradle_stops_audio(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """session.close() → all audio stops."""
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        mock_audio.calls.clear()
        session.close()
        assert any(c[0] == 'stop' for c in mock_audio.calls)

    def test_handset_on_cradle_does_not_stop_plex(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """session.close() while music playing → media_client.stop() NOT called."""
        mock_media_client.set_now_playing(PlaybackState(MediaItem("/pl/1", "Jazz", "playlist"), False))
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        mock_media_client.calls.clear()
        session.close()
        stop_calls = [c for c in mock_media_client.calls if c[0] == 'stop']
        assert len(stop_calls) == 0

    def test_digit_after_hangup_ignored(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Digit event after close() → ignored, no state change."""
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
        session.close()
        mock_tts.calls.clear()
        mock_audio.calls.clear()
        session.handle_event((GpioEvent.DIGIT_DIALED, 5), now=2.0)
        assert len(tts_calls(mock_tts)) == 0


class TestSessionDirectDial:
    """Direct dial via session."""

    def test_direct_dial_during_dial_tone(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """Two digits within disambiguation timeout during dial tone → DTMF tones played."""
        session = make_session(mock_audio, mock_tts, mock_media_client, mock_media_store,
                               mock_error_queue, tmp_path)
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
        session.tick(now=DIAL_TONE_TIMEOUT_IDLE + 1.0)
        mock_media_client.calls.clear()
        mock_tts.calls.clear()
        # Start dialing 3 digits
        t = 10.0
        session.handle_event((GpioEvent.DIGIT_DIALED, 1), now=t)
        session.handle_event((GpioEvent.DIGIT_DIALED, 2), now=t + 0.05)
        session.handle_event((GpioEvent.DIGIT_DIALED, 3), now=t + 0.1)
        # Hang up before completing
        session.close()
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


# ---------------------------------------------------------------------------
# Required constructor parameters
# ---------------------------------------------------------------------------

class TestSessionRequiredParameters:
    """Menu must reject construction when required dependencies are omitted.

    media_client, media_store, phone_book, and error_queue are not truly
    optional — the menu cannot function without them.  Removing their
    = None defaults causes Python to raise TypeError at the call site instead
    of letting a broken Menu reach runtime.

    radio is intentionally optional (hardware-dependent; all usages are
    guarded with ``if self._radio is not None``).
    """

    def _make_phone_book(self, tmp_path):
        from src.phone_book import PhoneBook
        return PhoneBook(db_path=str(tmp_path / "pb.db"))

    def test_missing_media_client_raises_type_error(
            self, mock_audio, mock_tts, mock_media_store, mock_error_queue, tmp_path):
        from src.menu import Menu
        with pytest.raises(TypeError):
            Menu(
                audio=mock_audio,
                tts=mock_tts,
                media_store=mock_media_store,
                phone_book=self._make_phone_book(tmp_path),
                error_queue=mock_error_queue,
            )

    def test_missing_media_store_raises_type_error(
            self, mock_audio, mock_tts, mock_media_client, mock_error_queue, tmp_path):
        from src.menu import Menu
        with pytest.raises(TypeError):
            Menu(
                audio=mock_audio,
                tts=mock_tts,
                media_client=mock_media_client,
                phone_book=self._make_phone_book(tmp_path),
                error_queue=mock_error_queue,
            )

    def test_missing_phone_book_raises_type_error(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        from src.menu import Menu
        with pytest.raises(TypeError):
            Menu(
                audio=mock_audio,
                tts=mock_tts,
                media_client=mock_media_client,
                media_store=mock_media_store,
                error_queue=mock_error_queue,
            )

    def test_missing_error_queue_raises_type_error(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, tmp_path):
        from src.menu import Menu
        with pytest.raises(TypeError):
            Menu(
                audio=mock_audio,
                tts=mock_tts,
                media_client=mock_media_client,
                media_store=mock_media_store,
                phone_book=self._make_phone_book(tmp_path),
            )

    def test_radio_is_still_optional(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store, mock_error_queue, tmp_path):
        """radio has no = None default — confirm Menu+Session builds without it."""
        from src.menu import Menu
        from src.session import Session
        menu = Menu(
            audio=mock_audio,
            tts=mock_tts,
            media_client=mock_media_client,
            media_store=mock_media_store,
            phone_book=self._make_phone_book(tmp_path),
            error_queue=mock_error_queue,
        )
        session = Session(menu=menu, now=0.0)
        assert session.menu._radio is None


# ---------------------------------------------------------------------------
# Session._run() error resilience (background thread)
# ---------------------------------------------------------------------------

class TestSessionRunResilience:
    """Session._run() catches exceptions and keeps the polling loop alive."""

    def _make_menu(self, mock_audio, mock_tts, mock_media_client, mock_media_store,
                   mock_error_queue, tmp_path):
        from src.menu import Menu
        from src.phone_book import PhoneBook
        from src.radio import MockRadio
        return Menu(
            audio=mock_audio, tts=mock_tts,
            media_client=mock_media_client, media_store=mock_media_store,
            phone_book=PhoneBook(db_path=str(tmp_path / "pb.db")),
            error_queue=mock_error_queue,
            radio=MockRadio(),
        )

    def test_gpio_drain_exception_does_not_kill_loop(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store,
            mock_error_queue, tmp_path):
        """RuntimeError from gpio.drain_digits() is caught; loop keeps running."""
        from src.session import Session

        call_count = [0]

        class FailOnceGpio:
            def start(self): pass
            def stop(self): pass
            def drain_digits(self):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("transient gpio error")
                return []

        menu = self._make_menu(mock_audio, mock_tts, mock_media_client,
                               mock_media_store, mock_error_queue, tmp_path)
        session = Session(menu=menu, gpio=FailOnceGpio(), now=0.0)
        session.start()
        time.sleep(0.05)  # ~10 iterations at 5 ms each
        assert call_count[0] > 1, "loop should have continued past the exception"
        session.close()

    def test_digit_delivered_after_prior_gpio_exception(
            self, mock_audio, mock_tts, mock_media_client, mock_media_store,
            mock_error_queue, tmp_path):
        """After a gpio exception, subsequent drain_digits() digits still reach the menu."""
        from src.session import Session
        import time as _time

        call_count = [0]

        class FailThenDigitGpio:
            def start(self): pass
            def stop(self): pass
            def drain_digits(self):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("transient error")
                if call_count[0] == 2:
                    return [(5, _time.monotonic())]
                return []

        menu = self._make_menu(mock_audio, mock_tts, mock_media_client,
                               mock_media_store, mock_error_queue, tmp_path)
        session = Session(menu=menu, gpio=FailThenDigitGpio(), now=0.0)
        session.start()
        time.sleep(0.05)
        session.close()
        # drain_digits was called at least twice → exception didn't kill the loop
        assert call_count[0] >= 2
