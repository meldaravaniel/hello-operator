"""Tests for src/phone.py — Phone lifecycle.

All tests use MagicMock dependencies; no hardware or network required.

NOTE: there is a known bug in Phone.__init__ — the `tts` parameter is
accepted but never stored as self._tts, so _on_handset_replaced raises
AttributeError when it calls self._tts.abort().  test_replaces_handset_aborts_tts
will fail until that is fixed.
"""

import threading
import time
from unittest.mock import MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_phone(**overrides):
    """Return a Phone built from MagicMock dependencies.

    Dialer is patched so no real GPIO poll thread is started.
    """
    from src.phone import Phone
    deps = dict(
        hook=MagicMock(),
        pulse=MagicMock(),
        tts=MagicMock(),
        audio=MagicMock(),
        menu=MagicMock(),
    )
    deps.update(overrides)
    with patch("src.phone.Dialer"):
        phone = Phone(**deps)
    phone._test_tts = deps["tts"]
    phone._test_audio = deps["audio"]
    phone._test_menu = deps["menu"]
    return phone


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestPhoneInit:

    def test_handset_not_lifted_at_creation(self):
        assert _make_phone()._handset_lifted is False

    def test_stop_event_clear_at_creation(self):
        assert not _make_phone()._stop_event.is_set()

    def test_dialer_created_with_menu_on_digit_and_pulse(self):
        menu = MagicMock()
        pulse = MagicMock()
        from src.phone import Phone
        with patch("src.phone.Dialer") as MockDialer:
            Phone(hook=MagicMock(), pulse=pulse, tts=MagicMock(),
                  audio=MagicMock(), menu=menu)
        MockDialer.assert_called_once_with(menu.on_digit, pulse)


# ---------------------------------------------------------------------------
# start() / stop()
# ---------------------------------------------------------------------------

class TestPhoneStartStop:

    def test_start_spawns_hook_watcher_thread(self):
        phone = _make_phone()
        phone.start()
        names = [t.name for t in threading.enumerate()]
        phone._stop_event.set()
        assert "hook-watcher" in names

    def test_hook_watcher_thread_is_daemon(self):
        phone = _make_phone()
        phone.start()
        thread = next(t for t in threading.enumerate() if t.name == "hook-watcher")
        phone._stop_event.set()
        assert thread.daemon

    def test_stop_sets_stop_event(self):
        phone = _make_phone()
        phone._handset_lifted = False
        phone.stop()
        assert phone._stop_event.is_set()

    def test_stop_delegates_to_on_handset_replaced(self):
        phone = _make_phone()
        with patch.object(phone, "_on_handset_replaced") as mock:
            phone.stop()
        mock.assert_called_once()


# ---------------------------------------------------------------------------
# Hook watcher thread
# ---------------------------------------------------------------------------

class TestHookWatcher:

    def test_registers_lifted_callback_on_hook(self):
        hook = MagicMock()
        phone = _make_phone(hook=hook)

        def stop_soon():
            time.sleep(0.010)
            phone._stop_event.set()

        t = threading.Thread(target=stop_soon, daemon=True)
        t.start()
        phone._start_hook_watcher()
        t.join()
        assert hook.when_pressed == phone._on_handset_lifted

    def test_registers_replaced_callback_on_hook(self):
        hook = MagicMock()
        phone = _make_phone(hook=hook)

        def stop_soon():
            time.sleep(0.010)
            phone._stop_event.set()

        t = threading.Thread(target=stop_soon, daemon=True)
        t.start()
        phone._start_hook_watcher()
        t.join()
        assert hook.when_released == phone._on_handset_replaced

    def test_exits_promptly_when_stop_event_set(self):
        phone = _make_phone()
        phone._stop_event.set()
        start = time.monotonic()
        phone._start_hook_watcher()
        assert time.monotonic() - start < 0.5

    def test_exception_in_loop_does_not_kill_watcher(self):
        hook = MagicMock()
        call_count = [0]

        original_setattr = type(hook).__setattr__

        def raise_once(self, name, value):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("transient error")
            original_setattr(self, name, value)

        phone = _make_phone(hook=hook)

        def stop_after_two():
            while call_count[0] < 2:
                time.sleep(0.001)
            phone._stop_event.set()

        with patch.object(type(hook), "__setattr__", raise_once):
            t = threading.Thread(target=stop_after_two, daemon=True)
            t.start()
            phone._start_hook_watcher()
            t.join()

        assert call_count[0] >= 2


# ---------------------------------------------------------------------------
# _on_handset_lifted
# ---------------------------------------------------------------------------

class TestOnHandsetLifted:

    def _lifted(self, phone):
        """Lift the handset and wait for the session thread to start, then stop it."""
        started = threading.Event()
        original = phone._start_phone_session

        def tracked():
            started.set()
            # let the real loop run briefly then exit
            phone._handset_lifted = False

        phone._start_phone_session = tracked
        phone._on_handset_lifted()
        started.wait(timeout=1.0)
        phone._start_phone_session = original

    def test_sets_handset_lifted_flag(self):
        phone = _make_phone()
        with patch.object(phone, "_start_phone_session"):
            phone._on_handset_lifted()
        assert phone._handset_lifted is True

    def test_turns_amp_on(self):
        audio = MagicMock()
        phone = _make_phone(audio=audio)
        with patch.object(phone, "_start_phone_session"):
            phone._on_handset_lifted()
        audio.amp_on.assert_called_once()

    def test_starts_dialer(self):
        phone = _make_phone()
        with patch.object(phone, "_start_phone_session"):
            phone._on_handset_lifted()
        phone._dialer.start.assert_called_once()

    def test_notifies_menu(self):
        menu = MagicMock()
        phone = _make_phone(menu=menu)
        with patch.object(phone, "_start_phone_session"):
            phone._on_handset_lifted()
        menu.on_handset_lifted.assert_called_once()

    def test_starts_phone_session_in_thread(self):
        phone = _make_phone()
        started = threading.Event()

        def signal_start():
            started.set()
            phone._handset_lifted = False

        with patch.object(phone, "_start_phone_session", side_effect=signal_start):
            phone._on_handset_lifted()
            assert started.wait(timeout=1.0), "phone-session thread never started"

    def test_phone_session_thread_is_daemon(self):
        phone = _make_phone()
        started = threading.Event()

        def signal_start():
            started.set()
            phone._handset_lifted = False

        with patch.object(phone, "_start_phone_session", side_effect=signal_start):
            phone._on_handset_lifted()
            started.wait(timeout=1.0)

        threads = [t for t in threading.enumerate() if t.name == "phone-session"]
        # thread may have already exited; if still alive it must be a daemon
        for t in threads:
            assert t.daemon

    def test_idempotent_when_already_lifted(self):
        audio = MagicMock()
        phone = _make_phone(audio=audio)
        phone._handset_lifted = True
        with patch.object(phone, "_start_phone_session"):
            phone._on_handset_lifted()
        audio.amp_on.assert_not_called()


# ---------------------------------------------------------------------------
# _on_handset_replaced
# ---------------------------------------------------------------------------

class TestOnHandsetReplaced:

    def _lifted_phone(self, **overrides):
        phone = _make_phone(**overrides)
        phone._handset_lifted = True
        return phone

    def test_clears_handset_lifted_flag(self):
        phone = self._lifted_phone()
        phone._on_handset_replaced()
        assert phone._handset_lifted is False

    def test_turns_amp_off(self):
        audio = MagicMock()
        phone = self._lifted_phone(audio=audio)
        phone._on_handset_replaced()
        audio.amp_off.assert_called_once()

    def test_stops_dialer(self):
        phone = self._lifted_phone()
        phone._on_handset_replaced()
        phone._dialer.stop.assert_called_once()

    def test_notifies_menu(self):
        menu = MagicMock()
        phone = self._lifted_phone(menu=menu)
        phone._on_handset_replaced()
        menu.on_handset_on_cradle.assert_called_once()

    def test_aborts_tts(self):
        # NOTE: this test exposes a bug — Phone.__init__ accepts tts but never
        # assigns self._tts, so this will raise AttributeError until fixed.
        tts = MagicMock()
        phone = self._lifted_phone(tts=tts)
        phone._on_handset_replaced()
        tts.abort.assert_called_once()

    def test_idempotent_when_already_on_cradle(self):
        audio = MagicMock()
        phone = _make_phone(audio=audio)
        phone._handset_lifted = False
        phone._on_handset_replaced()
        audio.amp_off.assert_not_called()


# ---------------------------------------------------------------------------
# _start_phone_session
# ---------------------------------------------------------------------------

class TestPhoneSession:

    def test_tick_called_while_handset_lifted(self):
        menu = MagicMock()
        phone = _make_phone(menu=menu)
        phone._handset_lifted = True

        def put_down():
            time.sleep(0.020)
            phone._handset_lifted = False

        t = threading.Thread(target=put_down, daemon=True)
        t.start()
        phone._start_phone_session()
        t.join()

        assert menu.tick.call_count >= 1

    def test_session_exits_once_handset_lowered(self):
        phone = _make_phone()
        phone._handset_lifted = True

        def put_down():
            time.sleep(0.015)
            phone._handset_lifted = False

        t = threading.Thread(target=put_down, daemon=True)
        t.start()
        start = time.monotonic()
        phone._start_phone_session()
        elapsed = time.monotonic() - start
        t.join()

        assert elapsed < 0.5

    def test_tick_not_called_when_handset_not_lifted(self):
        menu = MagicMock()
        phone = _make_phone(menu=menu)
        phone._handset_lifted = False
        phone._start_phone_session()
        menu.tick.assert_not_called()

    def test_exception_in_tick_does_not_kill_session(self):
        menu = MagicMock()
        tick_count = [0]

        def tick_raise_once(**kwargs):
            tick_count[0] += 1
            if tick_count[0] == 1:
                raise RuntimeError("transient tick error")

        menu.tick.side_effect = tick_raise_once
        phone = _make_phone(menu=menu)
        phone._handset_lifted = True

        def put_down():
            time.sleep(0.020)
            phone._handset_lifted = False

        t = threading.Thread(target=put_down, daemon=True)
        t.start()
        phone._start_phone_session()
        t.join()

        assert tick_count[0] >= 2
