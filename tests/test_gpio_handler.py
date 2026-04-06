"""Tests for src/gpio_handler.py — GPIOHandler hardware abstraction."""

import time
import pytest
from src.gpio_handler import GPIOHandler, GpioEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_handler(hook_pin_reader=None, pulse_pin_reader=None):
    """Build a GPIOHandler with injectable pin-reader callables."""
    return GPIOHandler(
        hook_pin_reader=hook_pin_reader or (lambda: 1),
        pulse_pin_reader=pulse_pin_reader or (lambda: 1),
    )


def drain_events(handler, max_events=20):
    """Poll the handler until no more events are produced (up to max_events)."""
    events = []
    for _ in range(max_events):
        e = handler.poll()
        if e is not None:
            events.append(e)
    return events


# ---------------------------------------------------------------------------
# 1.1 Hook switch
# ---------------------------------------------------------------------------

class TestHookSwitch:

    def test_hook_lifted(self):
        """GPIO LOW (0) → emits HANDSET_LIFTED."""
        handler = make_handler(hook_pin_reader=lambda: 0)
        event = handler.poll()
        assert event == GpioEvent.HANDSET_LIFTED

    def test_hook_on_cradle(self):
        """GPIO HIGH (1) after being lifted → emits HANDSET_ON_CRADLE."""
        readings = iter([0, 0, 1])
        handler = make_handler(hook_pin_reader=lambda: next(readings))
        # First poll: detects lift
        handler.poll()
        # consume extra HIGH=0 poll
        handler.poll()
        # Now hook goes back HIGH → HANDSET_ON_CRADLE
        event = handler.poll()
        assert event == GpioEvent.HANDSET_ON_CRADLE

    def test_hook_debounce(self):
        """Rapid HIGH/LOW transitions within debounce window → only one event."""
        # We provide a sequence that bounces before settling LOW
        bounce_readings = [1, 0, 1, 0, 0, 0]  # starts HIGH, bounces, settles LOW
        idx = [0]

        def reader():
            v = bounce_readings[min(idx[0], len(bounce_readings) - 1)]
            idx[0] += 1
            return v

        handler = make_handler(hook_pin_reader=reader)
        events = drain_events(handler, max_events=len(bounce_readings) + 2)
        lifted_events = [e for e in events if e == GpioEvent.HANDSET_LIFTED]
        assert len(lifted_events) == 1

    def test_hook_no_event_when_state_unchanged(self):
        """Repeated reads of same HIGH state → no duplicate events."""
        handler = make_handler(hook_pin_reader=lambda: 1)
        events = drain_events(handler, max_events=10)
        # No state change → no events
        assert events == []


# ---------------------------------------------------------------------------
# 1.2 Pulse switch / dial decoder
# ---------------------------------------------------------------------------

class TestPulseDecoder:
    """
    Pulse timing is simulated by controlling what the pin reader returns.
    GPIOHandler.poll() accepts an optional 'now' parameter so tests can inject
    a fake clock without sleeping.
    """

    def _build_pulse_sequence(self, num_pulses, inter_digit_gap=0.4):
        """
        Return a list of (pin_value, timestamp) pairs that simulate `num_pulses`
        pulses followed by a long inter-digit gap.

        Each pulse is LOW for 20 ms, then HIGH for 60 ms (80 ms per pulse cycle).
        """
        events = []
        t = 0.0
        for _ in range(num_pulses):
            events.append((0, t))        # LOW: pulse start
            t += 0.02
            events.append((1, t))        # HIGH: pulse end
            t += 0.06
        # Add idle time beyond inter-digit timeout
        events.append((1, t + inter_digit_gap))
        return events

    def _run_sequence(self, seq):
        """Drive a GPIOHandler through a timed sequence, collecting events."""
        idx = [0]
        def pulse_reader():
            return seq[min(idx[0], len(seq) - 1)][0]

        handler = make_handler(
            hook_pin_reader=lambda: 0,  # handset lifted
            pulse_pin_reader=pulse_reader,
        )

        collected = []
        for i, (pin_val, ts) in enumerate(seq):
            idx[0] = i
            event = handler.poll(now=ts)
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
        seq1 = self._build_pulse_sequence(3)
        # Build second burst starting at the time after the first sequence ends
        t_offset = seq1[-1][1] + 0.1
        seq2_raw = self._build_pulse_sequence(7)
        seq2 = [(v, t + t_offset) for v, t in seq2_raw]
        full_seq = seq1 + seq2

        events = self._run_sequence(full_seq)
        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert len(digit_events) == 2
        assert digit_events[0][1] == 3
        assert digit_events[1][1] == 7

    def test_pulse_debounce(self):
        """Noise pulses shorter than minimum pulse width → ignored."""
        # Very short LOW spike (1 ms) — below debounce threshold
        noise_seq = [
            (1, 0.0),
            (0, 0.005),   # LOW for only 1 ms — noise
            (1, 0.006),
            (1, 0.5),     # settle with long timeout — no digit emitted
        ]
        idx = [0]
        def pulse_reader():
            return noise_seq[min(idx[0], len(noise_seq) - 1)][0]

        handler = make_handler(
            hook_pin_reader=lambda: 0,
            pulse_pin_reader=pulse_reader,
        )

        events = []
        for i, (_, ts) in enumerate(noise_seq):
            idx[0] = i
            e = handler.poll(now=ts)
            if e is not None:
                events.append(e)

        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert digit_events == []

    def test_dial_ignored_when_hook_on_cradle(self):
        """Pulses while handset on cradle (hook HIGH) → no events emitted."""
        seq = self._build_pulse_sequence(5)
        idx = [0]
        def pulse_reader():
            return seq[min(idx[0], len(seq) - 1)][0]

        handler = make_handler(
            hook_pin_reader=lambda: 1,  # on cradle
            pulse_pin_reader=pulse_reader,
        )

        events = []
        for i, (_, ts) in enumerate(seq):
            idx[0] = i
            e = handler.poll(now=ts)
            if e is not None:
                events.append(e)

        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert digit_events == []
