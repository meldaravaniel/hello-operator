"""GPIO handler for hello-operator.

Polls GPIO pins and emits clean events to the rest of the system.
Handles debouncing for both the hook switch and the pulse switch.
Decodes pulse bursts into digits using the inter-digit timeout.

No RPi.GPIO dependency in this module — all pin reads go through injected
callables (hook_pin_reader and pulse_pin_reader), enabling full unit testing
without hardware.

Debounce model
--------------
Both the hook switch and the pulse switch use the same debounce pattern:

    "commit when the raw value has been continuously stable for at least
    DEBOUNCE_WINDOW seconds since it last changed"

The implementation tracks (candidate_value, candidate_start_time).  On each
poll call:
  1. If the raw value differs from the current candidate, update the candidate
     and record the current time.
  2. If the raw value matches the current candidate AND (now - candidate_start)
     >= debounce_window, the value is considered stable.

For the hook switch, a stable transition from the committed state fires an event.
For the pulse switch, stable LOW → rising edge starts a pulse; stable HIGH after
LOW → rising edge ends a pulse (validated by its duration).

Digit decoding (rotary convention)
-----------------------------------
After the last pulse in a burst, if the inter-digit gap elapses with no further
pulses, the burst is decoded:  N pulses → digit N (1–9), 10 pulses → digit 0.
"""

import time
from enum import Enum, auto
from typing import Callable, Optional

from src.constants import (
    HOOK_DEBOUNCE,
    PULSE_DEBOUNCE,
    INTER_DIGIT_TIMEOUT,
)


class GpioEvent(Enum):
    HANDSET_LIFTED = auto()
    HANDSET_ON_CRADLE = auto()
    DIGIT_DIALED = auto()


# Rotary convention: 10 pulses = digit 0
_PULSE_TO_DIGIT = {i: i for i in range(1, 10)}
_PULSE_TO_DIGIT[10] = 0


class GPIOHandler:
    """Polls GPIO and emits decoded events.

    Parameters
    ----------
    hook_pin_reader:
        Callable returning current hook-switch GPIO level: 0 = lifted, 1 = on cradle.
    pulse_pin_reader:
        Callable returning current pulse-switch GPIO level: 0 = pulsing, 1 = resting.
    """

    def __init__(
        self,
        hook_pin_reader: Callable[[], int],
        pulse_pin_reader: Callable[[], int],
    ) -> None:
        self._hook_reader = hook_pin_reader
        self._pulse_reader = pulse_pin_reader

        # Hook state machine — debounce
        self._hook_state: int = 1              # last committed state (1 = on cradle)
        self._hook_candidate: int = 1          # current candidate raw value
        self._hook_candidate_time: float = 0.0 # when candidate last changed

        # Pulse state machine — edge detection + burst decoding
        self._pulse_last_raw: int = 1          # most recent raw pulse reading
        self._pulse_last_change_time: float = 0.0  # when raw last changed

        # Whether we are currently inside a LOW pulse (after stable falling edge)
        self._in_pulse: bool = False
        self._pulse_start_time: float = 0.0

        # Burst accumulator
        self._pulse_count: int = 0
        self._burst_active: bool = False
        self._last_pulse_end_time: float = 0.0

    def poll(self, now: Optional[float] = None) -> Optional[object]:
        """Read GPIO pins once and return an event if one is ready, else None.

        Parameters
        ----------
        now:
            Fake clock value (seconds). If None, ``time.monotonic()`` is used.
            Injected in tests to avoid real sleeps.

        Returns
        -------
        GpioEvent.HANDSET_LIFTED, GpioEvent.HANDSET_ON_CRADLE,
        (GpioEvent.DIGIT_DIALED, digit: int), or None.
        """
        if now is None:
            now = time.monotonic()

        # --- Hook switch debounce ------------------------------------------------
        hook_event = self._process_hook(self._hook_reader(), now)
        if hook_event is not None:
            return hook_event

        # --- Pulse decoder (only when handset is lifted) -------------------------
        if self._hook_state == 0:  # handset lifted
            return self._process_pulse(self._pulse_reader(), now)

        # Handset on cradle — discard any in-progress burst
        if self._burst_active:
            self._reset_burst()

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_hook(self, raw: int, now: float) -> Optional[GpioEvent]:
        """Debounce hook switch; emit event when a stable transition is detected."""
        if raw != self._hook_candidate:
            # Value changed — restart debounce timer
            self._hook_candidate = raw
            self._hook_candidate_time = now

        elapsed = now - self._hook_candidate_time
        if elapsed >= HOOK_DEBOUNCE - 1e-9 and raw != self._hook_state:
            # Candidate has been stable long enough and differs from committed state
            self._hook_state = raw
            if raw == 0:
                return GpioEvent.HANDSET_LIFTED
            else:
                return GpioEvent.HANDSET_ON_CRADLE
        return None

    def _process_pulse(self, raw: int, now: float) -> Optional[object]:
        """Detect pulse edges and decode bursts into digits.

        Edge detection uses duration-based validation:
        - A falling edge (HIGH→LOW) starts a potential pulse.
        - A rising edge (LOW→HIGH) ends the pulse; only counted if the LOW
          duration was at least PULSE_DEBOUNCE (filters noise glitches).
        - After INTER_DIGIT_TIMEOUT with no new pulses, the burst is decoded.
        """
        if raw != self._pulse_last_raw:
            prev_raw = self._pulse_last_raw
            duration = now - self._pulse_last_change_time

            self._pulse_last_raw = raw
            self._pulse_last_change_time = now

            if prev_raw == 1 and raw == 0:
                # Falling edge: LOW started — begin potential pulse
                self._in_pulse = True
                self._pulse_start_time = now

            elif prev_raw == 0 and raw == 1:
                # Rising edge: LOW ended
                if self._in_pulse and duration >= PULSE_DEBOUNCE:
                    # Valid pulse: LOW was long enough
                    self._pulse_count += 1
                    self._burst_active = True
                    self._last_pulse_end_time = now
                self._in_pulse = False

        return self._check_inter_digit_timeout(now)

    def _check_inter_digit_timeout(self, now: float) -> Optional[object]:
        """Emit DIGIT_DIALED if a burst has finished and the timeout has elapsed."""
        if self._burst_active and not self._in_pulse:
            elapsed = now - self._last_pulse_end_time
            if elapsed >= INTER_DIGIT_TIMEOUT:
                digit = _PULSE_TO_DIGIT.get(self._pulse_count)
                self._reset_burst()
                if digit is not None:
                    return (GpioEvent.DIGIT_DIALED, digit)
        return None

    def _reset_burst(self):
        self._pulse_count = 0
        self._burst_active = False
        self._in_pulse = False
