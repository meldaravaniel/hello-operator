import logging
import threading
import time
from gpiozero import Button, DigitalInputDevice
from typing import Optional
from threading import Lock

from src.constants import PULSE_DEBOUNCE, INTER_DIGIT_TIMEOUT

log = logging.getLogger(__name__)

# Rotary convention: 10 pulses = digit 1
_PULSE_TO_DIGIT = {i: i for i in range(1, 10)}
_PULSE_TO_DIGIT[10] = 0


class Dialer:
    def __init__(self, dial_digit_callback, pulse: Button, rotary: DigitalInputDevice) -> None:
        self._pulse = pulse
        self._rotary = rotary
        self._stop_event = threading.Event()
        self._dial_digit_callback = dial_digit_callback
        
        self._pulse_count: int = 0
        self._pulse_lock = Lock()
        self._dialing: bool = False
        
    def start(self) -> None:
        t = threading.Thread(target=self._poll_loop, daemon=True, name="gpio-poll")
        t.start()

    def stop(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        log.debug("gpio-poll thread started")
        self._rotary.when_activated = self._on_dialing_started
        self._rotary.when_deactivated = self._on_dialing_stopped
        self._pulse.when_pressed = self._on_switch_opened
        while not self._stop_event.is_set():
            try:
                log.debug("waiting for a dial")
                self._rotary.wait_for_active()
                log.debug("processing a dial")
                self._rotary.wait_for_inactive()
            except Exception:
                log.exception("gpio-poll error")
        log.debug("gpio-poll thread exiting")

    def _on_dialing_started(self) -> None:
        log.debug("dialing started")
        self._dialing = True

    def _on_dialing_stopped(self) -> None:
        log.debug("dialing stopped")
        self._pulse_lock.acquire()
        digit = self._pulse_count % 10
        log.debug("digit " + str(digit))
        if(digit is not None):
            self._dial_digit_callback(digit)
        self._dialing = False
        self._pulse_count = 0
        self._pulse_lock.release()

    def _on_switch_opened(self) -> None:
        if (self._dialing):
            self._pulse_lock.acquire()
            self._pulse_count += 1
            log.debug("pulse opened")
            self._pulse_lock.release()