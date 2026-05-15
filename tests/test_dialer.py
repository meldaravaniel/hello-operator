"""Tests for src/dialer.py."""

import threading
from unittest.mock import MagicMock, patch, call

import pytest

from src.dialer import Dialer, _PULSE_TO_DIGIT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pulse():
    return MagicMock()


@pytest.fixture
def mock_rotary():
    m = MagicMock()
    m.wait_for_active = MagicMock()
    m.wait_for_inactive = MagicMock()
    return m


@pytest.fixture
def callback():
    return MagicMock()


@pytest.fixture
def dialer(callback, mock_pulse, mock_rotary):
    return Dialer(callback, mock_pulse, mock_rotary)


# ---------------------------------------------------------------------------
# _PULSE_TO_DIGIT mapping
# ---------------------------------------------------------------------------


class TestPulseToDigit:
    def test_one_through_nine_map_to_themselves(self):
        for i in range(1, 10):
            assert _PULSE_TO_DIGIT[i] == i

    def test_ten_pulses_map_to_zero(self):
        assert _PULSE_TO_DIGIT[10] == 0


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_stores_pulse(self, dialer, mock_pulse):
        assert dialer._pulse is mock_pulse

    def test_stores_rotary(self, dialer, mock_rotary):
        assert dialer._rotary is mock_rotary

    def test_stores_callback(self, dialer, callback):
        assert dialer._dial_digit_callback is callback

    def test_pulse_count_starts_at_zero(self, dialer):
        assert dialer._pulse_count == 0

    def test_dialing_starts_false(self, dialer):
        assert dialer._dialing is False

    def test_stop_event_starts_clear(self, dialer):
        assert not dialer._stop_event.is_set()


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    def test_spawns_a_thread(self, dialer):
        with patch("src.dialer.threading.Thread") as MockThread:
            dialer.start()
        MockThread.assert_called_once()

    def test_thread_is_daemon(self, dialer):
        with patch("src.dialer.threading.Thread") as MockThread:
            dialer.start()
        _, kwargs = MockThread.call_args
        assert kwargs.get("daemon") is True

    def test_thread_name_is_gpio_poll(self, dialer):
        with patch("src.dialer.threading.Thread") as MockThread:
            dialer.start()
        _, kwargs = MockThread.call_args
        assert kwargs.get("name") == "gpio-poll"

    def test_thread_target_is_poll_loop(self, dialer):
        with patch("src.dialer.threading.Thread") as MockThread:
            dialer.start()
        _, kwargs = MockThread.call_args
        assert kwargs.get("target") == dialer._poll_loop

    def test_thread_is_started(self, dialer):
        with patch("src.dialer.threading.Thread") as MockThread:
            dialer.start()
        MockThread.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    def test_sets_stop_event(self, dialer):
        dialer.stop()
        assert dialer._stop_event.is_set()

    def test_stop_is_idempotent(self, dialer):
        dialer.stop()
        dialer.stop()
        assert dialer._stop_event.is_set()


# ---------------------------------------------------------------------------
# _poll_loop()
# ---------------------------------------------------------------------------


class TestPollLoop:
    def test_registers_when_activated_callback(self, dialer, mock_rotary):
        dialer._stop_event.set()
        dialer._poll_loop()
        assert mock_rotary.when_activated == dialer._on_dialing_started

    def test_registers_when_deactivated_callback(self, dialer, mock_rotary):
        dialer._stop_event.set()
        dialer._poll_loop()
        assert mock_rotary.when_deactivated == dialer._on_dialing_stopped

    def test_registers_when_pressed_callback(self, dialer, mock_pulse):
        dialer._stop_event.set()
        dialer._poll_loop()
        assert mock_pulse.when_pressed == dialer._on_switch_opened

    def test_exits_immediately_when_stop_event_preset(self, dialer, mock_rotary):
        dialer._stop_event.set()
        dialer._poll_loop()
        mock_rotary.wait_for_active.assert_not_called()

    def test_calls_wait_for_active_then_wait_for_inactive_each_iteration(
            self, dialer, mock_rotary):
        def stop_after_inactive():
            dialer._stop_event.set()

        mock_rotary.wait_for_inactive.side_effect = stop_after_inactive
        dialer._poll_loop()
        mock_rotary.wait_for_active.assert_called_once()
        mock_rotary.wait_for_inactive.assert_called_once()

    def test_loops_multiple_times_until_stop_event(self, dialer, mock_rotary):
        call_counts = {"n": 0}

        def stop_after_three():
            call_counts["n"] += 1
            if call_counts["n"] >= 3:
                dialer._stop_event.set()

        mock_rotary.wait_for_inactive.side_effect = stop_after_three
        dialer._poll_loop()
        assert call_counts["n"] == 3

    def test_swallows_exception_from_wait_for_active(self, dialer, mock_rotary):
        call_counts = {"n": 0}

        def raise_then_stop():
            call_counts["n"] += 1
            if call_counts["n"] == 1:
                raise RuntimeError("gpio blip")
            dialer._stop_event.set()

        mock_rotary.wait_for_active.side_effect = raise_then_stop
        dialer._poll_loop()  # must not propagate RuntimeError

    def test_swallows_exception_from_wait_for_inactive(self, dialer, mock_rotary):
        call_counts = {"n": 0}

        def raise_then_stop():
            call_counts["n"] += 1
            if call_counts["n"] == 1:
                raise RuntimeError("gpio blip")
            dialer._stop_event.set()

        mock_rotary.wait_for_inactive.side_effect = raise_then_stop
        dialer._poll_loop()  # must not propagate RuntimeError

    def test_continues_loop_after_swallowed_exception(self, dialer, mock_rotary):
        call_counts = {"n": 0}

        def raise_first_then_stop():
            call_counts["n"] += 1
            if call_counts["n"] == 1:
                raise RuntimeError("transient error")
            dialer._stop_event.set()

        mock_rotary.wait_for_active.side_effect = raise_first_then_stop
        dialer._poll_loop()
        assert call_counts["n"] == 2


# ---------------------------------------------------------------------------
# _on_dialing_started()
# ---------------------------------------------------------------------------


class TestOnDialingStarted:
    def test_sets_dialing_true(self, dialer):
        dialer._on_dialing_started()
        assert dialer._dialing is True

    def test_does_not_affect_pulse_count(self, dialer):
        dialer._pulse_count = 3
        dialer._on_dialing_started()
        assert dialer._pulse_count == 3


# ---------------------------------------------------------------------------
# _on_dialing_stopped()
# ---------------------------------------------------------------------------


class TestOnDialingStopped:
    def test_calls_callback_with_digit(self, dialer, callback):
        dialer._dialing = True
        dialer._pulse_count = 5
        dialer._on_dialing_stopped()
        callback.assert_called_once_with(5)

    def test_resets_pulse_count_to_zero(self, dialer, callback):
        dialer._pulse_count = 7
        dialer._on_dialing_stopped()
        assert dialer._pulse_count == 0

    def test_sets_dialing_false(self, dialer, callback):
        dialer._dialing = True
        dialer._on_dialing_stopped()
        assert dialer._dialing is False

    def test_ten_pulses_fires_callback_with_zero(self, dialer, callback):
        dialer._dialing = True
        dialer._pulse_count = 10
        dialer._on_dialing_stopped()
        callback.assert_called_once_with(0)

    def test_one_pulse_fires_callback_with_one(self, dialer, callback):
        dialer._dialing = True
        dialer._pulse_count = 1
        dialer._on_dialing_stopped()
        callback.assert_called_once_with(1)

    def test_nine_pulses_fires_callback_with_nine(self, dialer, callback):
        dialer._dialing = True
        dialer._pulse_count = 9
        dialer._on_dialing_stopped()
        callback.assert_called_once_with(9)

    def test_always_fires_callback_even_with_zero_pulses(self, dialer, callback):
        dialer._pulse_count = 0
        dialer._on_dialing_stopped()
        callback.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# _on_switch_opened()
# ---------------------------------------------------------------------------


class TestOnSwitchOpened:
    def test_increments_pulse_count_when_dialing(self, dialer):
        dialer._dialing = True
        dialer._on_switch_opened()
        assert dialer._pulse_count == 1

    def test_increments_multiple_times(self, dialer):
        dialer._dialing = True
        dialer._on_switch_opened()
        dialer._on_switch_opened()
        dialer._on_switch_opened()
        assert dialer._pulse_count == 3

    def test_does_not_increment_when_not_dialing(self, dialer):
        dialer._dialing = False
        dialer._on_switch_opened()
        assert dialer._pulse_count == 0

    def test_ignores_pulses_before_dialing_starts(self, dialer):
        dialer._on_switch_opened()
        dialer._on_switch_opened()
        assert dialer._pulse_count == 0


# ---------------------------------------------------------------------------
# Full digit sequence (integration of the above methods)
# ---------------------------------------------------------------------------


class TestDigitSequences:
    def _dial(self, dialer, pulse_count):
        """Simulate a complete dial: start → N pulses → stop."""
        dialer._on_dialing_started()
        for _ in range(pulse_count):
            dialer._on_switch_opened()
        dialer._on_dialing_stopped()

    @pytest.mark.parametrize("pulses,expected_digit", [
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (6, 6),
        (7, 7),
        (8, 8),
        (9, 9),
        (10, 0),
    ])
    def test_pulse_to_digit_mapping(self, dialer, callback, pulses, expected_digit):
        self._dial(dialer, pulses)
        callback.assert_called_once_with(expected_digit)

    def test_state_is_clean_after_dial(self, dialer, callback):
        self._dial(dialer, 5)
        assert dialer._pulse_count == 0
        assert dialer._dialing is False

    def test_two_consecutive_dials_fire_two_callbacks(self, dialer, callback):
        self._dial(dialer, 3)
        self._dial(dialer, 7)
        assert callback.call_count == 2
        callback.assert_any_call(3)
        callback.assert_any_call(7)

    def test_pulses_before_dialing_started_are_ignored(self, dialer, callback):
        dialer._on_switch_opened()  # spurious pulse before dial starts
        dialer._on_switch_opened()
        self._dial(dialer, 3)
        callback.assert_called_once_with(3)
