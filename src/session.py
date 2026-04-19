"""Session lifecycle for hello-operator.

Manages a single handset interaction. Created when the handset is lifted;
closed when it is replaced. Owns the GPIO digit-polling loop.

Production usage (via hook watcher in main.py)::

    menu = Menu(...)
    session = Session(menu=menu, gpio=gpio_handler)
    session.start()   # starts internal polling thread
    # ... on hang-up:
    session.close()

Test usage (no background thread)::

    session = Session(menu=menu, now=0.0)
    session.handle_event((GpioEvent.DIGIT_DIALED, 5), now=0.5)
    session.tick(now=DIAL_TONE_TIMEOUT_IDLE + 1.0)
    session.close()
"""

import threading
import time
from typing import Optional, Tuple, Union

from src.gpio_handler import GpioEvent
from src.menu import Menu


class Session:
    """Manages a single handset interaction.

    Parameters
    ----------
    menu:
        Pre-constructed Menu instance owned by the caller.
    gpio:
        GPIOHandler for the internal digit-polling loop. Omit in tests.
    now:
        Monotonic clock value for the handset-lifted event. Defaults to
        ``time.monotonic()`` if not provided.
    """

    def __init__(
        self,
        menu: Menu,
        gpio=None,
        now: Optional[float] = None,
    ) -> None:
        if now is None:
            now = time.monotonic()
        self._menu = menu
        self._gpio = gpio
        self._stop_event = threading.Event()
        self._menu.on_handset_lifted(now=now)

    def start(self) -> None:
        """Start the GPIO polling thread and the session tick loop.

        Call this in production after construction. Tests omit this and
        drive the session directly via handle_event() and tick().
        """
        if self._gpio is not None:
            self._gpio.start()
        t = threading.Thread(target=self._tick_loop, daemon=True, name="session-tick")
        t.start()

    def close(self) -> None:
        """Stop polling and deliver the hang-up event to the menu."""
        self._stop_event.set()
        if self._gpio is not None:
            self._gpio.stop()
        self._menu.on_handset_on_cradle()

    def handle_event(
        self,
        event: Union[GpioEvent, Tuple[GpioEvent, int]],
        now: Optional[float] = None,
    ) -> None:
        """Dispatch a digit event directly (used in tests).

        Only DIGIT_DIALED events are processed; hook events are ignored
        since the hook watcher handles those in production.
        """
        if now is None:
            now = time.monotonic()
        if isinstance(event, tuple) and event[0] == GpioEvent.DIGIT_DIALED:
            self._menu.on_digit(event[1], now=now)

    def tick(self, now: Optional[float] = None) -> None:
        """Advance menu timeouts (used in tests)."""
        if now is None:
            now = time.monotonic()
        self._menu.tick(now=now)

    @property
    def menu(self) -> Menu:
        """The underlying Menu instance (for state inspection in tests)."""
        return self._menu

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tick_loop(self) -> None:
        import logging
        log = logging.getLogger(__name__)
        log.info("session-tick thread started")
        while not self._stop_event.is_set():
            try:
                now = time.monotonic()
                if self._gpio is not None:
                    for digit, digit_now in self._gpio.drain_digits():
                        log.info("digit dialed: %d", digit)
                        self._menu.on_digit(digit, now=digit_now)
                self._menu.tick(now=now)
            except Exception:
                log.exception("session-tick error")
            time.sleep(0.005)
        log.info("session-tick thread exiting")
