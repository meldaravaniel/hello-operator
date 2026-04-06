"""Tests for src/gpio_handler.py — GPIOHandler hardware abstraction."""

import pytest
from src.gpio_handler import GPIOHandler, GpioEvent
from src.constants import HOOK_DEBOUNCE, PULSE_DEBOUNCE, INTER_DIGIT_TIMEOUT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_handler(hook_pin_reader=None, pulse_pin_reader=None):
    """Build a GPIOHandler with injectable pin-reader callables."""
    return GPIOHandler(
        hook_pin_reader=hook_pin_reader or (lambda: 1),
        pulse_pin_reader=pulse_pin_reader or (lambda: 1),
    )


def poll_at(handler, hook_val, pulse_val, t):
    """Single poll at fake time t, overriding pin readers inline."""
    handler._hook_reader = lambda: hook_val
    handler._pulse_reader = lambda: pulse_val
    return handler.poll(now=t)


# ---------------------------------------------------------------------------
# 1.1 Hook switch
# ---------------------------------------------------------------------------

class TestHookSwitch:

    def test_hook_lifted(self):
        """GPIO LOW (0) stable for debounce window → emits HANDSET_LIFTED."""
        handler = make_handler()
        t = 0.0
        # First reading: LOW appears (candidate starts)
        poll_at(handler, hook_val=0, pulse_val=1, t=t)
        # After debounce window: still LOW → commit → HANDSET_LIFTED
        event = poll_at(handler, hook_val=0, pulse_val=1, t=t + HOOK_DEBOUNCE)
        assert event == GpioEvent.HANDSET_LIFTED

    def test_hook_on_cradle(self):
        """GPIO HIGH stable after being lifted → emits HANDSET_ON_CRADLE."""
        handler = make_handler()
        t = 0.0
        # Lift handset
        poll_at(handler, hook_val=0, pulse_val=1, t=t)
        poll_at(handler, hook_val=0, pulse_val=1, t=t + HOOK_DEBOUNCE)
        # Replace handset
        t2 = t + HOOK_DEBOUNCE + 0.1
        poll_at(handler, hook_val=1, pulse_val=1, t=t2)
        event = poll_at(handler, hook_val=1, pulse_val=1, t=t2 + HOOK_DEBOUNCE)
        assert event == GpioEvent.HANDSET_ON_CRADLE

    def test_hook_debounce(self):
        """Rapid HIGH/LOW transitions within debounce window → only one event."""
        handler = make_handler()
        t = 0.0
        dt = HOOK_DEBOUNCE * 0.1  # much shorter than debounce window

        # Sequence: HIGH resting, bounces LOW/HIGH/LOW quickly, then settles LOW
        results = []
        # Bounce 1: LOW
        results.append(poll_at(handler, hook_val=0, pulse_val=1, t=t))
        t += dt
        # Bounce 2: HIGH (within window — resets candidate)
        results.append(poll_at(handler, hook_val=1, pulse_val=1, t=t))
        t += dt
        # Bounce 3: LOW (within window again)
        results.append(poll_at(handler, hook_val=0, pulse_val=1, t=t))
        t += dt
        # Settle LOW for full debounce window
        results.append(poll_at(handler, hook_val=0, pulse_val=1, t=t + HOOK_DEBOUNCE))

        lifted_events = [e for e in results if e == GpioEvent.HANDSET_LIFTED]
        assert len(lifted_events) == 1

    def test_hook_no_event_when_state_unchanged(self):
        """Repeated reads of same HIGH state → no duplicate events."""
        handler = make_handler(hook_pin_reader=lambda: 1)
        # Initial state is HIGH (on cradle); poll many times with HIGH
        events = [handler.poll(now=float(i) * 0.1) for i in range(10)]
        assert all(e is None for e in events)


# ---------------------------------------------------------------------------
# 1.2 Pulse switch / dial decoder
# ---------------------------------------------------------------------------

class TestPulseDecoder:
    """
    Pulse timing is simulated by injecting fake timestamps via handler.poll(now=t).
    Each pulse is LOW for ~20 ms (above PULSE_DEBOUNCE), HIGH for ~60 ms between
    pulses.  After the last pulse, a gap of INTER_DIGIT_TIMEOUT + margin triggers
    the DIGIT_DIALED event.
    """

    PULSE_LOW_MS = 0.025   # 25 ms LOW per pulse (above PULSE_DEBOUNCE ~5 ms)
    PULSE_HIGH_MS = 0.060  # 60 ms HIGH between pulses

    def _build_pulse_sequence(self, num_pulses, start_t=0.0):
        """
        Return list of (hook_val, pulse_val, timestamp) for `num_pulses` pulses
        followed by an inter-digit gap.
        """
        events = []
        t = start_t
        for _ in range(num_pulses):
            events.append((0, 0, t))               # pulse start (LOW)
            t += self.PULSE_LOW_MS
            events.append((0, 1, t))               # pulse end (HIGH)
            t += self.PULSE_HIGH_MS
        # After last pulse, add idle beyond inter-digit timeout
        events.append((0, 1, t + INTER_DIGIT_TIMEOUT + 0.05))
        return events

    def _run_sequence(self, seq):
        """Drive a GPIOHandler through (hook_val, pulse_val, t) triples.

        A two-poll hook-settling prefix is prepended automatically at t=-0.2
        and t=-0.1 (before any sequence timestamps) so that the hook switch is
        fully committed to 'lifted' before the first pulse arrives.
        """
        handler = make_handler()
        collected = []
        # Settle hook to 'lifted' before pulses begin
        for pre_t in (-0.2, -0.2 + HOOK_DEBOUNCE):
            handler._hook_reader = lambda: 0
            handler._pulse_reader = lambda: 1
            handler.poll(now=pre_t)

        for hook_val, pulse_val, t in seq:
            handler._hook_reader = lambda h=hook_val: h
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
        t_offset = seq1[-1][2] + 0.2  # start well after first digit settles
        seq2 = self._build_pulse_sequence(7, start_t=t_offset)
        full_seq = seq1 + seq2

        events = self._run_sequence(full_seq)
        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert len(digit_events) == 2
        assert digit_events[0][1] == 3
        assert digit_events[1][1] == 7

    def test_pulse_debounce(self):
        """Noise pulses shorter than minimum pulse width → ignored."""
        handler = make_handler()

        # Handset is lifted
        handler._hook_reader = lambda: 0

        t = 0.0
        # Very short LOW (less than PULSE_DEBOUNCE — noise)
        noise_duration = PULSE_DEBOUNCE * 0.4

        events = []

        # Stable HIGH initially
        handler._pulse_reader = lambda: 1
        events.append(handler.poll(now=t))

        # Brief LOW — noise spike
        t += 0.01
        handler._pulse_reader = lambda: 0
        events.append(handler.poll(now=t))

        # Back HIGH quickly (within noise threshold)
        t += noise_duration
        handler._pulse_reader = lambda: 1
        events.append(handler.poll(now=t))

        # Long idle → should NOT emit a digit
        t += INTER_DIGIT_TIMEOUT + 0.1
        events.append(handler.poll(now=t))

        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert digit_events == []

    def test_dial_ignored_when_hook_on_cradle(self):
        """Pulses while handset on cradle (hook HIGH) → no digit events emitted."""
        # Build a valid pulse sequence (hook_val=0 = lifted), then change to on-cradle
        seq_lifted = self._build_pulse_sequence(5)
        # Change all hook_val to 1 (on cradle)
        seq_cradle = [(1, pulse_val, t) for _, pulse_val, t in seq_lifted]

        events = self._run_sequence(seq_cradle)
        digit_events = [e for e in events if isinstance(e, tuple) and e[0] == GpioEvent.DIGIT_DIALED]
        assert digit_events == []
