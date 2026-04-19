"""Tests for src/gpio_handler.py — GPIOHandler pulse decoder."""

import pytest
from src.gpio_handler import GPIOHandler, GpioEvent
from src.constants import PULSE_DEBOUNCE, INTER_DIGIT_TIMEOUT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_handler(pulse_pin_reader=None):
    """Build a GPIOHandler with an injectable pulse-reader callable."""
    return GPIOHandler(pulse_pin_reader=pulse_pin_reader or (lambda: 1))


def poll_at(handler, pulse_val, t):
    """Single poll at fake time t, overriding the pulse reader inline."""
    handler._pulse_reader = lambda: pulse_val
    return handler.poll(now=t)


# ---------------------------------------------------------------------------
# Pulse switch / dial decoder
# ---------------------------------------------------------------------------

class TestPulseDecoder:
    """
    Pulse timing is simulated by injecting fake timestamps via handler.poll(now=t).
    Each pulse is LOW for ~25 ms (above PULSE_DEBOUNCE), HIGH for ~60 ms between
    pulses.  After the last pulse, a gap of INTER_DIGIT_TIMEOUT + margin triggers
    the DIGIT_DIALED event.
    """

    PULSE_LOW_MS = 0.025   # 25 ms LOW per pulse (above PULSE_DEBOUNCE ~5 ms)
    PULSE_HIGH_MS = 0.060  # 60 ms HIGH between pulses

    def _build_pulse_sequence(self, num_pulses, start_t=0.0):
        """Return list of (pulse_val, timestamp) for `num_pulses` pulses
        followed by an inter-digit gap."""
        events = []
        t = start_t
        for _ in range(num_pulses):
            events.append((0, t))               # pulse LOW
            t += self.PULSE_LOW_MS
            events.append((1, t))               # pulse HIGH
            t += self.PULSE_HIGH_MS
        # Idle beyond inter-digit timeout
        events.append((1, t + INTER_DIGIT_TIMEOUT + 0.05))
        return events

    def _run_sequence(self, seq):
        """Drive a GPIOHandler through (pulse_val, t) pairs."""
        handler = make_handler()
        collected = []
        for pulse_val, t in seq:
            handler._pulse_reader = lambda p=pulse_val: p
            event = handler.poll(now=t)
            if event is not None:
                collected.append(event)
        return collected

    def test_single_digit_1(self):
        seq = self._build_pulse_sequence(1)
        events = self._run_sequence(seq)
        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert len(digit_events) == 1
        assert digit_events[0][1] == 1

    def test_single_digit_5(self):
        seq = self._build_pulse_sequence(5)
        events = self._run_sequence(seq)
        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert len(digit_events) == 1
        assert digit_events[0][1] == 5

    def test_single_digit_0(self):
        """Ten pulses → digit 0 (rotary convention)."""
        seq = self._build_pulse_sequence(10)
        events = self._run_sequence(seq)
        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert len(digit_events) == 1
        assert digit_events[0][1] == 0

    def test_pulse_burst_timeout(self):
        """After pulses stop and inter-digit timeout elapses → DIGIT_DIALED emitted."""
        seq = self._build_pulse_sequence(3)
        events = self._run_sequence(seq)
        assert any(
            isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED and e[1] == 3
            for e in events
        )

    def test_multiple_digits_sequence(self):
        """Two bursts separated by timeout → two DIGIT_DIALED events in order."""
        seq1 = self._build_pulse_sequence(3, start_t=0.0)
        t_offset = seq1[-1][1] + 0.2
        seq2 = self._build_pulse_sequence(7, start_t=t_offset)

        events = self._run_sequence(seq1 + seq2)
        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert len(digit_events) == 2
        assert digit_events[0][1] == 3
        assert digit_events[1][1] == 7

    def test_pulse_debounce(self):
        """Noise pulses shorter than PULSE_DEBOUNCE → ignored."""
        handler = make_handler()
        events = []
        t = 0.0

        # Stable HIGH
        events.append(poll_at(handler, pulse_val=1, t=t))

        # Brief LOW — noise spike
        t += 0.01
        events.append(poll_at(handler, pulse_val=0, t=t))

        # Back HIGH within noise threshold
        t += PULSE_DEBOUNCE * 0.4
        events.append(poll_at(handler, pulse_val=1, t=t))

        # Long idle — should NOT emit a digit
        t += INTER_DIGIT_TIMEOUT + 0.1
        events.append(poll_at(handler, pulse_val=1, t=t))

        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert digit_events == []

    def test_no_event_when_idle(self):
        """Repeated reads of resting HIGH → no events."""
        handler = make_handler(pulse_pin_reader=lambda: 1)
        events = [handler.poll(now=float(i) * 0.1) for i in range(10)]
        assert all(e is None for e in events)


# ---------------------------------------------------------------------------
# Background polling thread: start / stop / drain_digits
# ---------------------------------------------------------------------------

class TestGPIOHandlerThread:
    """Tests for the dedicated 1 ms polling thread interface."""

    def test_drain_digits_empty_before_start(self):
        """drain_digits() returns [] when no digits have been queued."""
        handler = make_handler()
        assert handler.drain_digits() == []

    def test_start_and_stop_do_not_raise(self):
        """start() launches thread without error; stop() signals clean exit."""
        import time
        handler = make_handler(pulse_pin_reader=lambda: 1)
        handler.start()
        time.sleep(0.02)
        handler.stop()

    def test_thread_detects_digit_via_drain(self):
        """Pulse sequence fed through _process_pulse with fake clock → digit decoded."""
        from src.constants import INTER_DIGIT_TIMEOUT

        PULSE_LOW = 0.025    # 25 ms LOW
        PULSE_HIGH = 0.060   # 60 ms HIGH between pulses

        # 3 pulses: LOW/HIGH pairs, then idle beyond INTER_DIGIT_TIMEOUT
        events = []
        handler = make_handler()
        t = 0.0
        for _ in range(3):
            events.append(handler._process_pulse(0, t)); t += PULSE_LOW
            events.append(handler._process_pulse(1, t)); t += PULSE_HIGH

        # Drive idle ticks until inter-digit timeout fires
        step = 0.010
        limit = t + INTER_DIGIT_TIMEOUT + 0.2
        while t < limit:
            ev = handler._process_pulse(1, t)
            if ev is not None:
                events.append(ev)
                break
            t += step

        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert len(digit_events) == 1
        assert digit_events[0][1] == 3

    def test_start_resets_stale_queue(self):
        """start() drains any digits left from a prior session."""
        import time
        handler = make_handler(pulse_pin_reader=lambda: 1)
        # Manually stuff a stale digit into the queue
        handler._digit_queue.put((9, 0.0))
        assert len(handler.drain_digits()) == 1

        # Second start() on a fresh handler should drain queue first
        handler2 = make_handler(pulse_pin_reader=lambda: 1)
        handler2._digit_queue.put((7, 0.0))
        handler2.start()
        time.sleep(0.01)
        handler2.stop()
        # After start(), the stale 7 should have been drained internally;
        # any new digits are from the real thread (none expected for idle HIGH).
        digits = handler2.drain_digits()
        assert all(d != 7 for d, _ in digits)

    def test_stop_halts_thread(self):
        """stop() causes the polling thread to exit within 50 ms."""
        import time
        poll_count = [0]

        def counting_reader():
            poll_count[0] += 1
            return 1

        handler = GPIOHandler(pulse_pin_reader=counting_reader)
        handler.start()
        time.sleep(0.02)
        count_at_stop = poll_count[0]
        handler.stop()
        time.sleep(0.05)
        count_after_stop = poll_count[0]
        # Some polls may fire in the 50 ms window, but the count should not
        # grow by more than ~1-2 after stop() was called.
        assert count_after_stop - count_at_stop <= 5
