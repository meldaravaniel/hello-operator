"""Session lifecycle for hello-operator.

Owns the application lifecycle for a single handset interaction. Listens for
GPIO events, routes them to the Menu state machine, and handles cleanup on
hang-up. Does not stop media playback on hang-up — music continues.

Usage::

    session = Session(audio, tts, media_client, media_store, phone_book, error_queue, radio)
    # In an event loop:
    event = gpio_handler.poll(now=time.monotonic())
    if event is not None:
        session.handle_event(event, now=time.monotonic())
    session.tick(now=time.monotonic())
"""

import time
from typing import Optional, Tuple, Union

from src.gpio_handler import GpioEvent
from src.interfaces import AudioInterface, TTSInterface, MediaClientInterface, ErrorQueueInterface
from src.menu import Menu


class Session:
    """Ties GPIO events to the Menu state machine.

    Parameters
    ----------
    audio : AudioInterface
    tts : TTSInterface
    media_client : MediaClientInterface
    media_store : MediaStore or MockMediaStore
    phone_book : PhoneBook
    error_queue : ErrorQueueInterface
    radio : RadioInterface
    """

    def __init__(
        self,
        audio: AudioInterface,
        tts: TTSInterface,
        media_client: MediaClientInterface = None,
        media_store=None,
        phone_book=None,
        error_queue: ErrorQueueInterface = None,
        radio=None,  # RadioInterface
        # Backward-compat aliases
        plex_client: MediaClientInterface = None,
        plex_store=None,
    ) -> None:
        self._menu = Menu(
            audio=audio,
            tts=tts,
            media_client=media_client or plex_client,
            media_store=media_store or plex_store,
            phone_book=phone_book,
            error_queue=error_queue,
            radio=radio,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_event(
        self,
        event: Union[GpioEvent, Tuple[GpioEvent, int]],
        now: Optional[float] = None,
    ) -> None:
        """Route a GPIO event to the menu.

        Parameters
        ----------
        event:
            A ``GpioEvent`` member or a ``(GpioEvent.DIGIT_DIALED, digit)``
            tuple as returned by ``GPIOHandler.poll()``.
        now:
            Monotonic clock value in seconds. Defaults to ``time.monotonic()``.
        """
        if now is None:
            now = time.monotonic()

        if isinstance(event, tuple):
            gpio_event, digit = event
            if gpio_event == GpioEvent.DIGIT_DIALED:
                self._menu.on_digit(digit, now=now)
        elif event == GpioEvent.HANDSET_LIFTED:
            self._menu.on_handset_lifted(now=now)
        elif event == GpioEvent.HANDSET_ON_CRADLE:
            self._menu.on_handset_on_cradle()

    def tick(self, now: Optional[float] = None) -> None:
        """Advance menu timeouts. Call from the polling loop.

        Parameters
        ----------
        now:
            Monotonic clock value in seconds. Defaults to ``time.monotonic()``.
        """
        if now is None:
            now = time.monotonic()
        self._menu.tick(now=now)

    @property
    def menu(self) -> Menu:
        """The underlying Menu instance (for state inspection in tests)."""
        return self._menu
