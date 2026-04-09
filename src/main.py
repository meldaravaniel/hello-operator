"""Application entry point for hello-operator.

Instantiates all concrete implementations, pre-renders fixed TTS scripts,
wires everything into Session, and starts the event loop.
"""

import os
import time
import logging

from src.constants import (
    PLEX_URL, PLEX_TOKEN, PLEX_PLAYER_IDENTIFIER,
    PIPER_BINARY, PIPER_MODEL, TTS_CACHE_DIR,
    HOOK_SWITCH_PIN, PULSE_SWITCH_PIN,
)
from src.error_queue import SqliteErrorQueue
from src.phone_book import PhoneBook
from src.audio import SounddeviceAudio
from src.tts import PiperTTS
from src.plex_client import PlexClient
from src.plex_store import PlexStore
from src.gpio_handler import GPIOHandler, GpioEvent
from src.session import Session

# Import all pre-renderable script strings from menu
from src.menu import (
    SCRIPT_OPERATOR_OPENER,
    SCRIPT_GREETING,
    SCRIPT_EXTENSION_HINT,
    SCRIPT_PLAYING_MENU_DEFAULT,
    SCRIPT_PLAYING_MENU_ON_HOLD,
    SCRIPT_PLAYING_MENU_LAST_TRACK,
    SCRIPT_PLAYING_MENU_ON_HOLD_LAST_TRACK,
    SCRIPT_NOT_IN_SERVICE,
    SCRIPT_SERVICE_DEGRADATION,
    SCRIPT_BROWSE_PROMPT_PLAYLIST,
    SCRIPT_BROWSE_PROMPT_ARTIST,
    SCRIPT_BROWSE_PROMPT_GENRE,
    SCRIPT_BROWSE_PROMPT_ALBUM,
    SCRIPT_BROWSE_PROMPT_NEXT_LETTER,
    SCRIPT_PLEX_FAILURE,
    SCRIPT_DB_FAILURE,
    SCRIPT_RETRY_PROMPT,
    SCRIPT_NO_CONTENT,
    SCRIPT_TERMINAL_FALLBACK,
    SCRIPT_ASSISTANT_ALL_CLEAR,
    SCRIPT_ASSISTANT_STATUS_INTRO,
    SCRIPT_ASSISTANT_END_OF_MESSAGES,
    SCRIPT_ASSISTANT_NAVIGATION,
    SCRIPT_ASSISTANT_VALEDICTION_CLEAR,
    SCRIPT_ASSISTANT_VALEDICTION_MESSAGES,
    SCRIPT_ASSISTANT_REFRESH_SUCCESS,
    SCRIPT_ASSISTANT_REFRESH_FAILURE,
    SCRIPT_SHUFFLE_CONNECTING,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("hello-operator")


# ---------------------------------------------------------------------------
# Database paths
# ---------------------------------------------------------------------------
_DB_DIR = "/var/lib/hello-operator"
_ERROR_QUEUE_DB = f"{_DB_DIR}/error_queue.db"
_PHONE_BOOK_DB = f"{_DB_DIR}/phone_book.db"
_PLEX_STORE_DB = f"{_DB_DIR}/plex_cache.db"


# ---------------------------------------------------------------------------
# Pre-renderable scripts
# ---------------------------------------------------------------------------
_PRERENDER_SCRIPTS = {
    "operator_opener": SCRIPT_OPERATOR_OPENER,
    "greeting": SCRIPT_GREETING,
    "extension_hint": SCRIPT_EXTENSION_HINT,
    "playing_menu_default": SCRIPT_PLAYING_MENU_DEFAULT,
    "playing_menu_on_hold": SCRIPT_PLAYING_MENU_ON_HOLD,
    "playing_menu_last_track": SCRIPT_PLAYING_MENU_LAST_TRACK,
    "playing_menu_on_hold_last_track": SCRIPT_PLAYING_MENU_ON_HOLD_LAST_TRACK,
    "not_in_service": SCRIPT_NOT_IN_SERVICE,
    "service_degradation": SCRIPT_SERVICE_DEGRADATION,
    "browse_prompt_playlist": SCRIPT_BROWSE_PROMPT_PLAYLIST,
    "browse_prompt_artist": SCRIPT_BROWSE_PROMPT_ARTIST,
    "browse_prompt_genre": SCRIPT_BROWSE_PROMPT_GENRE,
    "browse_prompt_album": SCRIPT_BROWSE_PROMPT_ALBUM,
    "browse_prompt_next_letter": SCRIPT_BROWSE_PROMPT_NEXT_LETTER,
    "plex_failure": SCRIPT_PLEX_FAILURE,
    "db_failure": SCRIPT_DB_FAILURE,
    "retry_prompt": SCRIPT_RETRY_PROMPT,
    "no_content": SCRIPT_NO_CONTENT,
    "terminal_fallback": SCRIPT_TERMINAL_FALLBACK,
    "assistant_all_clear": SCRIPT_ASSISTANT_ALL_CLEAR,
    "assistant_status_intro": SCRIPT_ASSISTANT_STATUS_INTRO,
    "assistant_end_of_messages": SCRIPT_ASSISTANT_END_OF_MESSAGES,
    "assistant_navigation": SCRIPT_ASSISTANT_NAVIGATION,
    "assistant_valediction_clear": SCRIPT_ASSISTANT_VALEDICTION_CLEAR,
    "assistant_valediction_messages": SCRIPT_ASSISTANT_VALEDICTION_MESSAGES,
    "assistant_refresh_success": SCRIPT_ASSISTANT_REFRESH_SUCCESS,
    "assistant_refresh_failure": SCRIPT_ASSISTANT_REFRESH_FAILURE,
    "shuffle_connecting": SCRIPT_SHUFFLE_CONNECTING,
}


def _gpio_cleanup() -> None:
    """Call GPIO.cleanup() to release pin reservations on shutdown.

    Imports RPi.GPIO lazily so this module can be imported on non-Pi hosts.
    Module-level so tests can patch it; run() only calls it after
    build_gpio_handler() has succeeded (i.e. GPIO was actually initialised).
    """
    try:
        import RPi.GPIO as GPIO  # type: ignore[import]
        GPIO.cleanup()
    except ImportError:
        pass  # Non-Pi environment — nothing to clean up


def build_gpio_handler() -> GPIOHandler:
    """Construct GPIOHandler with real RPi.GPIO pin readers."""
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(HOOK_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PULSE_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def hook_reader() -> int:
        return GPIO.input(HOOK_SWITCH_PIN)

    def pulse_reader() -> int:
        return GPIO.input(PULSE_SWITCH_PIN)

    return GPIOHandler(
        hook_pin_reader=hook_reader,
        pulse_pin_reader=pulse_reader,
    )


def run() -> None:
    """Main entry point — wire all components and start the event loop."""
    log.info("hello-operator starting up")

    # Ensure database directory exists before opening any SQLite files
    os.makedirs(_DB_DIR, exist_ok=True)

    # Data stores
    error_queue = SqliteErrorQueue(db_path=_ERROR_QUEUE_DB)
    phone_book = PhoneBook(db_path=_PHONE_BOOK_DB)

    # Hardware interfaces
    audio = SounddeviceAudio()
    tts = PiperTTS(
        piper_binary=PIPER_BINARY,
        piper_model=PIPER_MODEL,
        cache_dir=TTS_CACHE_DIR,
        audio=audio,
        error_queue=error_queue,
    )

    # Plex
    plex_client = PlexClient(url=PLEX_URL, token=PLEX_TOKEN, player_identifier=PLEX_PLAYER_IDENTIFIER)
    plex_store = PlexStore(db_path=_PLEX_STORE_DB, plex_client=plex_client)

    # Pre-render all fixed TTS scripts
    log.info("Pre-rendering %d TTS scripts...", len(_PRERENDER_SCRIPTS))
    tts.prerender(_PRERENDER_SCRIPTS)
    log.info("Pre-render complete.")

    # GPIO handler — track whether GPIO was successfully initialised so the
    # finally block only calls _gpio_cleanup() when it is safe to do so.
    _gpio_ready = False
    gpio = build_gpio_handler()
    _gpio_ready = True

    # Session
    session = Session(
        audio=audio,
        tts=tts,
        plex_client=plex_client,
        plex_store=plex_store,
        phone_book=phone_book,
        error_queue=error_queue,
    )

    log.info("hello-operator ready — waiting for handset lift")

    # Event loop
    try:
        while True:
            now = time.monotonic()
            event = gpio.poll(now=now)
            if event is not None:
                session.handle_event(event, now=now)
            session.tick(now=now)
            time.sleep(0.005)  # ~200 Hz polling
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        audio.stop()
        if _gpio_ready:
            _gpio_cleanup()


if __name__ == "__main__":
    run()
