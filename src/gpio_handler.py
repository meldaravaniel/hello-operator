"""GPIO handler for hello-operator.

Polls the pulse pin and decodes bursts into digits.  The hook switch is
handled entirely by the dedicated hook-watcher thread in main.py; this
module has no knowledge of hook state.

Production usage::

    gpio = GPIOHandler(pulse_pin_reader=...)
    gpio.start()   # 1 ms polling thread begins
    # ... each tick:
    for digit, now in gpio.drain_digits():
        menu.on_digit(digit, now=now)
    # ... on hang-up:
    gpio.stop()

Test usage (no background thread)::

    gpio = GPIOHandler(pulse_pin_reader=lambda: 1)
    event = gpio.poll(now=0.5)   # drive directly

Debounce model
--------------
The pulse switch uses a duration-based edge filter:

    A falling edge (HIGH→LOW) starts a potential pulse.  A rising edge
    (LOW→HIGH) ends it; only counted if the LOW duration was at least
    PULSE_DEBOUNCE seconds (filters noise/glitches).

Digit decoding (rotary convention)
-----------------------------------
After the last pulse in a burst, if INTER_DIGIT_TIMEOUT elapses with no
further pulses, the burst is decoded:  N pulses → digit N (1–9), 10 pulses → 0.
"""

import logging
import queue
import threading
import time
from enum import Enum, auto
from typing import Callable, List, Optional, Tuple

from src.constants import PULSE_DEBOUNCE, INTER_DIGIT_TIMEOUT

log = logging.getLogger(__name__)


class GpioEvent(Enum):
    DIGIT_DIALED = auto()


# Rotary convention: 10 pulses = digit 0
_PULSE_TO_DIGIT = {i: i for i in range(1, 10)}
_PULSE_TO_DIGIT[10] = 0


class GPIOHandler:
    """Polls the pulse pin and emits decoded digit events.

    Parameters
    ----------
    pulse_pin_reader:
        Callable returning current pulse-switch GPIO level: 0 = pulsing, 1 = resting.
    """

    def __init__(self, pulse_pin_reader: Callable[[], int]) -> None:
        self._pulse_reader = pulse_pin_reader
        self._stop_event = threading.Event()
        self._digit_queue: queue.Queue = queue.Queue()

        self._pulse_last_raw: int = 1
        self._pulse_last_change_time: float = 0.0

        self._in_pulse: bool = False
        self._pulse_start_time: float = 0.0

        self._pulse_count: int = 0
        self._burst_active: bool = False
        self._last_pulse_end_time: float = 0.0

    # ------------------------------------------------------------------
    # Production API (background thread)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start a 1 ms daemon polling thread for a new session.

        Resets pulse state and drains any stale digits from a prior session
        before launching the thread.
        """
        self._reset_burst()
        self._pulse_last_raw = 1
        self._pulse_last_change_time = 0.0
        while True:
            try:
                self._digit_queue.get_nowait()
            except queue.Empty:
                break
        self._stop_event.clear()
        t = threading.Thread(target=self._poll_loop, daemon=True, name="gpio-poll")
        t.start()

    def stop(self) -> None:
        """Signal the polling thread to exit."""
        self._stop_event.set()

    def drain_digits(self) -> List[Tuple[int, float]]:
        """Return all decoded (digit, now) pairs queued since the last call."""
        result = []
        while True:
            try:
                result.append(self._digit_queue.get_nowait())
            except queue.Empty:
                break
        return result

    # ------------------------------------------------------------------
    # Test API (direct polling, no background thread)
    # ------------------------------------------------------------------

    def poll(self, now: Optional[float] = None) -> Optional[object]:
        """Read the pulse pin once and return an event if ready, else None.

        Returns
        -------
        (GpioEvent.DIGIT_DIALED, digit: int), or None.
        """
        if now is None:
            now = time.monotonic()
        return self._process_pulse(self._pulse_reader(), now)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        log.info("gpio-poll thread started")
        while not self._stop_event.is_set():
            try:
                now = time.monotonic()
                event = self.poll(now=now)
                if isinstance(event, tuple) and event[0] == GpioEvent.DIGIT_DIALED:
                    self._digit_queue.put((event[1], now))
            except Exception:
                log.exception("gpio-poll error")
            time.sleep(0.001)
        log.info("gpio-poll thread exiting")

    def _process_pulse(self, raw: int, now: float) -> Optional[object]:
        """Detect pulse edges and decode bursts into digits."""
        if raw != self._pulse_last_raw:
            prev_raw = self._pulse_last_raw
            duration = now - self._pulse_last_change_time

            self._pulse_last_raw = raw
            self._pulse_last_change_time = now

            if prev_raw == 1 and raw == 0:
                self._in_pulse = True
                self._pulse_start_time = now

            elif prev_raw == 0 and raw == 1:
                if self._in_pulse and duration >= PULSE_DEBOUNCE:
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

    def _reset_burst(self) -> None:
        self._pulse_count = 0
        self._burst_active = False
        self._in_pulse = False
