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
        """Start the internal GPIO digit-polling loop in a daemon thread.

        Call this in production after construction. Tests omit this and
        drive the session directly via handle_event() and tick().
        """
        t = threading.Thread(target=self._run, daemon=True, name="session-poll")
        t.start()

    def close(self) -> None:
        """Stop polling and deliver the hang-up event to the menu."""
        self._stop_event.set()
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

    def _run(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            event = self._gpio.poll(now=now)
            if isinstance(event, tuple) and event[0] == GpioEvent.DIGIT_DIALED:
                self._menu.on_digit(event[1], now=now)
            self._menu.tick(now=now)
            time.sleep(0.005)
