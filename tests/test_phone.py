"""Tests for src/phone.py."""

import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from src.phone import Phone


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hook():
    hook = MagicMock()
    hook.wait_for_active = MagicMock()
    hook.wait_for_inactive = MagicMock()
    return hook


@pytest.fixture
def mock_pulse():
    return MagicMock()


@pytest.fixture
def mock_rotary():
    return MagicMock()


@pytest.fixture
def mock_audio():
    return MagicMock()


@pytest.fixture
def mock_menu():
    return MagicMock()


@pytest.fixture
def mock_tts():
    return MagicMock()


@pytest.fixture
def phone(mock_hook, mock_pulse, mock_rotary, mock_tts, mock_audio, mock_menu):
    """Phone instance with Dialer patched out so no GPIO threads start."""
    with patch("src.phone.Dialer"):
        return Phone(mock_hook, mock_pulse, mock_rotary, mock_tts, mock_audio, mock_menu)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_handset_lifted_starts_false(self, phone):
        assert phone._handset_lifted is False

    def test_stop_event_starts_clear(self, phone):
        assert not phone._stop_event.is_set()

    def test_dialer_receives_menu_on_digit_as_callback(
        self, mock_hook, mock_pulse, mock_rotary, mock_tts, mock_audio, mock_menu
    ):
        with patch("src.phone.Dialer") as MockDialer:
            Phone(mock_hook, mock_pulse, mock_rotary, mock_tts, mock_audio, mock_menu)
        positional, _ = MockDialer.call_args
        assert positional[0] is mock_menu.on_digit

    def test_dialer_receives_pulse_and_rotary(
        self, mock_hook, mock_pulse, mock_rotary, mock_tts, mock_audio, mock_menu
    ):
        with patch("src.phone.Dialer") as MockDialer:
            Phone(mock_hook, mock_pulse, mock_rotary, mock_tts, mock_audio, mock_menu)
        positional, _ = MockDialer.call_args
        assert positional[1] is mock_pulse
        assert positional[2] is mock_rotary


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    def test_spawns_hook_watcher_thread(self, phone):
        with patch("src.phone.threading.Thread") as MockThread:
            phone.start()
        MockThread.assert_called_once()
        _, kwargs = MockThread.call_args
        assert kwargs.get("name") == "hook-watcher"

    def test_hook_watcher_thread_is_daemon(self, phone):
        with patch("src.phone.threading.Thread") as MockThread:
            phone.start()
        _, kwargs = MockThread.call_args
        assert kwargs.get("daemon") is True

    def test_hook_watcher_thread_is_started(self, phone):
        with patch("src.phone.threading.Thread") as MockThread:
            phone.start()
        MockThread.return_value.start.assert_called_once()

    def test_hook_watcher_target_is_start_hook_watcher(self, phone):
        with patch("src.phone.threading.Thread") as MockThread:
            phone.start()
        _, kwargs = MockThread.call_args
        assert kwargs.get("target") == phone._start_hook_watcher


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    def test_sets_stop_event(self, phone):
        phone.stop()
        assert phone._stop_event.is_set()

    def test_calls_amp_off_when_handset_was_lifted(self, phone, mock_audio):
        phone._handset_lifted = True
        phone.stop()
        mock_audio.amp_off.assert_called_once()

    def test_calls_dialer_stop_when_handset_was_lifted(self, phone):
        phone._handset_lifted = True
        phone.stop()
        phone._dialer.stop.assert_called_once()

    def test_calls_menu_on_handset_on_cradle_when_lifted(self, phone, mock_menu):
        phone._handset_lifted = True
        phone.stop()
        mock_menu.on_handset_on_cradle.assert_called_once()

    def test_no_audio_call_when_handset_not_lifted(self, phone, mock_audio):
        phone.stop()
        mock_audio.amp_off.assert_not_called()


# ---------------------------------------------------------------------------
# _on_handset_lifted()
# ---------------------------------------------------------------------------


class TestOnHandsetLifted:
    def test_sets_handset_lifted_flag(self, phone):
        with patch("src.phone.threading.Thread"):
            phone._on_handset_lifted()
        assert phone._handset_lifted is True

    def test_calls_amp_on(self, phone, mock_audio):
        with patch("src.phone.threading.Thread"):
            phone._on_handset_lifted()
        mock_audio.amp_on.assert_called_once()

    def test_calls_dialer_start(self, phone):
        with patch("src.phone.threading.Thread"):
            phone._on_handset_lifted()
        phone._dialer.start.assert_called_once()

    def test_calls_menu_on_handset_lifted(self, phone, mock_menu):
        with patch("src.phone.threading.Thread"):
            phone._on_handset_lifted()
        mock_menu.on_handset_lifted.assert_called_once()

    def test_spawns_phone_session_daemon_thread(self, phone):
        with patch("src.phone.threading.Thread") as MockThread:
            phone._on_handset_lifted()
        MockThread.assert_called_once()
        _, kwargs = MockThread.call_args
        assert kwargs.get("name") == "phone-session"
        assert kwargs.get("daemon") is True

    def test_phone_session_thread_is_started(self, phone):
        with patch("src.phone.threading.Thread") as MockThread:
            phone._on_handset_lifted()
        MockThread.return_value.start.assert_called_once()

    def test_idempotent_second_lift_ignored(self, phone, mock_audio):
        with patch("src.phone.threading.Thread"):
            phone._on_handset_lifted()
            mock_audio.amp_on.reset_mock()
            phone._on_handset_lifted()
        mock_audio.amp_on.assert_not_called()

    def test_idempotent_second_lift_does_not_spawn_extra_thread(self, phone):
        with patch("src.phone.threading.Thread") as MockThread:
            phone._on_handset_lifted()
            phone._on_handset_lifted()
        MockThread.assert_called_once()


# ---------------------------------------------------------------------------
# _on_handset_replaced()
# ---------------------------------------------------------------------------


class TestOnHandsetReplaced:
    def test_no_effect_when_handset_not_lifted(self, phone, mock_audio):
        phone._on_handset_replaced()
        mock_audio.amp_off.assert_not_called()

    def test_clears_handset_lifted_flag(self, phone):
        phone._handset_lifted = True
        phone._on_handset_replaced()
        assert phone._handset_lifted is False

    def test_calls_amp_off(self, phone, mock_audio):
        phone._handset_lifted = True
        phone._on_handset_replaced()
        mock_audio.amp_off.assert_called_once()

    def test_calls_dialer_stop(self, phone):
        phone._handset_lifted = True
        phone._on_handset_replaced()
        phone._dialer.stop.assert_called_once()

    def test_calls_menu_on_handset_on_cradle(self, phone, mock_menu):
        phone._handset_lifted = True
        phone._on_handset_replaced()
        mock_menu.on_handset_on_cradle.assert_called_once()

    def test_idempotent_second_replace_ignored(self, phone, mock_audio):
        phone._handset_lifted = True
        phone._on_handset_replaced()
        mock_audio.amp_off.reset_mock()
        phone._on_handset_replaced()
        mock_audio.amp_off.assert_not_called()

    def test_idempotent_does_not_call_menu_twice(self, phone, mock_menu):
        phone._handset_lifted = True
        phone._on_handset_replaced()
        phone._on_handset_replaced()
        mock_menu.on_handset_on_cradle.assert_called_once()


# ---------------------------------------------------------------------------
# _start_hook_watcher()
# ---------------------------------------------------------------------------


class TestStartHookWatcher:
    def test_sets_when_activated_to_on_handset_lifted(self, phone, mock_hook):
        phone._stop_event.set()
        phone._start_hook_watcher()
        assert mock_hook.when_activated == phone._on_handset_lifted

    def test_sets_when_deactivated_to_on_handset_replaced(self, phone, mock_hook):
        phone._stop_event.set()
        phone._start_hook_watcher()
        assert mock_hook.when_deactivated == phone._on_handset_replaced

    def test_exits_immediately_when_stop_event_pre_set(self, phone, mock_hook):
        phone._stop_event.set()
        phone._start_hook_watcher()
        mock_hook.wait_for_active.assert_not_called()

    def test_calls_wait_for_active_then_wait_for_inactive(self, phone, mock_hook):
        def set_stop(*_):
            phone._stop_event.set()

        mock_hook.wait_for_inactive.side_effect = set_stop
        phone._start_hook_watcher()
        mock_hook.wait_for_active.assert_called_once()
        mock_hook.wait_for_inactive.assert_called_once()

    def test_loops_until_stop_event(self, phone, mock_hook):
        call_counts = {"n": 0}

        def increment_and_maybe_stop(*_):
            call_counts["n"] += 1
            if call_counts["n"] >= 3:
                phone._stop_event.set()

        mock_hook.wait_for_inactive.side_effect = increment_and_maybe_stop
        phone._start_hook_watcher()
        assert call_counts["n"] == 3

    def test_swallows_exception_from_wait_for_active(self, phone, mock_hook):
        call_counts = {"n": 0}

        def raise_then_stop(*_):
            call_counts["n"] += 1
            if call_counts["n"] == 1:
                raise RuntimeError("GPIO blip")
            phone._stop_event.set()

        mock_hook.wait_for_active.side_effect = raise_then_stop
        phone._start_hook_watcher()  # must not propagate the RuntimeError


# ---------------------------------------------------------------------------
# _start_phone_session()
# ---------------------------------------------------------------------------


class TestStartPhoneSession:
    def test_does_not_tick_when_handset_not_lifted(self, phone, mock_menu):
        phone._handset_lifted = False
        with patch("src.phone.time.sleep"):
            phone._start_phone_session()
        mock_menu.tick.assert_not_called()

    def test_calls_menu_tick_with_now_kwarg(self, phone, mock_menu):
        phone._handset_lifted = True

        def stop_after_first(now):
            phone._handset_lifted = False

        mock_menu.tick.side_effect = stop_after_first
        with patch("src.phone.time.sleep"):
            phone._start_phone_session()

        mock_menu.tick.assert_called_once()
        _, kwargs = mock_menu.tick.call_args
        assert "now" in kwargs
        assert isinstance(kwargs["now"], float)

    def test_stops_when_handset_replaced(self, phone, mock_menu):
        phone._handset_lifted = True
        ticks = []

        def tick_and_stop(now):
            ticks.append(now)
            if len(ticks) >= 3:
                phone._handset_lifted = False

        mock_menu.tick.side_effect = tick_and_stop
        with patch("src.phone.time.sleep"):
            phone._start_phone_session()

        assert len(ticks) == 3

    def test_swallows_exception_from_menu_tick(self, phone, mock_menu):
        phone._handset_lifted = True
        call_counts = {"n": 0}

        def raise_then_stop(now):
            call_counts["n"] += 1
            if call_counts["n"] == 1:
                raise RuntimeError("menu crash")
            phone._handset_lifted = False

        mock_menu.tick.side_effect = raise_then_stop
        with patch("src.phone.time.sleep"):
            phone._start_phone_session()  # must not propagate RuntimeError

        assert call_counts["n"] == 2

    def test_sleeps_between_ticks(self, phone, mock_menu):
        phone._handset_lifted = True

        def stop_after_first(now):
            phone._handset_lifted = False

        mock_menu.tick.side_effect = stop_after_first
        with patch("src.phone.time.sleep") as mock_sleep:
            phone._start_phone_session()

        mock_sleep.assert_called_once_with(0.005)
