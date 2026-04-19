"""Application entry point for hello-operator.

Instantiates all concrete implementations, pre-renders fixed TTS scripts,
wires everything into Session, and starts the event loop.
"""

import json
import os
import time
import logging

from src.constants import (
    MEDIA_BACKEND,
    MPD_HOST, MPD_PORT,
    PIPER_BINARY, PIPER_MODEL, TTS_CACHE_DIR,
    HOOK_SWITCH_PIN, PULSE_SWITCH_PIN, SD_AMP_PIN,
    RADIO_CONFIG_PATH,
    ALSA_DEVICE,
    AUDIO_VOLUME,
)
from src.error_queue import SqliteErrorQueue
from src.phone_book import PhoneBook
from src.audio import SounddeviceAudio
from src.tts import PiperTTS
from src.mpd_client import MPDClient
from src.media_store import MediaStore
from src.radio import RtlFmRadio
from src.gpio_handler import GPIOHandler, GpioEvent
from src.interfaces import RadioStation, MediaClientInterface
from src.session import Session

# Import all pre-renderable script strings from menu
from src.menu import (
    Menu,
    SCRIPT_OPERATOR_OPENER,
    SCRIPT_GREETING,
    SCRIPT_EXTENSION_HINT,
    SCRIPT_PLAYING_MENU_DEFAULT,
    SCRIPT_PLAYING_MENU_ON_HOLD,
    SCRIPT_PLAYING_MENU_LAST_TRACK,
    SCRIPT_PLAYING_MENU_ON_HOLD_LAST_TRACK,
    SCRIPT_NOT_IN_SERVICE,
    SCRIPT_BROWSE_PROMPT_PLAYLIST,
    SCRIPT_BROWSE_PROMPT_ARTIST,
    SCRIPT_BROWSE_PROMPT_GENRE,
    SCRIPT_BROWSE_PROMPT_ALBUM,
    SCRIPT_BROWSE_PROMPT_NEXT_LETTER,
    SCRIPT_MEDIA_FAILURE,
    SCRIPT_RETRY_PROMPT,
    SCRIPT_NO_CONTENT,
    SCRIPT_ASSISTANT_ALL_CLEAR,
    SCRIPT_ASSISTANT_STATUS_INTRO,
    SCRIPT_ASSISTANT_END_OF_MESSAGES,
    SCRIPT_ASSISTANT_NAVIGATION,
    SCRIPT_ASSISTANT_VALEDICTION_MESSAGES,
    SCRIPT_ASSISTANT_REFRESH_SUCCESS,
    SCRIPT_ASSISTANT_REFRESH_FAILURE,
    SCRIPT_SHUFFLE_CONNECTING,
    SCRIPT_RADIO_PLAYING_MENU,
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
_MEDIA_STORE_DB = f"{_DB_DIR}/media_cache.db"


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
    "browse_prompt_playlist": SCRIPT_BROWSE_PROMPT_PLAYLIST,
    "browse_prompt_artist": SCRIPT_BROWSE_PROMPT_ARTIST,
    "browse_prompt_genre": SCRIPT_BROWSE_PROMPT_GENRE,
    "browse_prompt_album": SCRIPT_BROWSE_PROMPT_ALBUM,
    "browse_prompt_next_letter": SCRIPT_BROWSE_PROMPT_NEXT_LETTER,
    "media_failure": SCRIPT_MEDIA_FAILURE,
    "retry_prompt": SCRIPT_RETRY_PROMPT,
    "no_content": SCRIPT_NO_CONTENT,
    "assistant_all_clear": SCRIPT_ASSISTANT_ALL_CLEAR,
    "assistant_status_intro": SCRIPT_ASSISTANT_STATUS_INTRO,
    "assistant_end_of_messages": SCRIPT_ASSISTANT_END_OF_MESSAGES,
    "assistant_navigation": SCRIPT_ASSISTANT_NAVIGATION,
    "assistant_valediction_messages": SCRIPT_ASSISTANT_VALEDICTION_MESSAGES,
    "assistant_refresh_success": SCRIPT_ASSISTANT_REFRESH_SUCCESS,
    "assistant_refresh_failure": SCRIPT_ASSISTANT_REFRESH_FAILURE,
    "shuffle_connecting": SCRIPT_SHUFFLE_CONNECTING,
    "radio_playing_menu": SCRIPT_RADIO_PLAYING_MENU,
}


def load_radio_stations(path: str) -> list:
    """Load radio stations from a JSON config file.

    Parameters
    ----------
    path:
        Filesystem path to the JSON file. Each entry must have keys:
        ``name``, ``frequency_mhz``, and ``phone_number``.

    Returns
    -------
    list[RadioStation]
        A list of RadioStation objects with frequency_hz converted from MHz.
        Returns an empty list if the file does not exist or cannot be parsed.
    """
    try:
        with open(path, "r") as fh:
            entries = json.load(fh)
        stations = []
        for entry in entries:
            stations.append(RadioStation(
                name=entry["name"],
                frequency_hz=entry["frequency_mhz"] * 1_000_000,
                phone_number=entry["phone_number"],
            ))
        return stations
    except FileNotFoundError:
        log.warning("Radio config not found at %s — no stations will be seeded", path)
        return []
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.warning("Failed to parse radio config at %s: %s — no stations will be seeded", path, exc)
        return []


def build_media_client() -> MediaClientInterface:
    """Construct the configured media client (MPD or Mopidy)."""
    if MEDIA_BACKEND == "mopidy":
        log.info("Media backend: Mopidy (%s:%d)", MPD_HOST, MPD_PORT)
    else:
        log.info("Media backend: MPD (%s:%d)", MPD_HOST, MPD_PORT)
    return MPDClient(host=MPD_HOST, port=MPD_PORT)


def _gpio_cleanup() -> None:
    """Call GPIO.cleanup() to release pin reservations on shutdown.

    Imports RPi.GPIO lazily so this module can be imported on non-Pi hosts.
    Module-level so tests can patch it; run() only calls it after
    build_gpio_handler() has succeeded (i.e. GPIO was actually initialised).
    """
    try:
        import RPi.GPIO as GPIO  # type: ignore[import]
        GPIO.cleanup()
    except (ImportError, RuntimeError):
        pass  # Non-Pi environment — nothing to clean up


def build_gpio_handler() -> GPIOHandler:
    """Construct GPIOHandler with a real RPi.GPIO pulse-pin reader.

    Raises ImportError if RPi.GPIO is not installed, RuntimeError if not on a Pi.
    run() catches both and skips GPIO setup.
    """
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(HOOK_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PULSE_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def pulse_reader() -> int:
        return GPIO.input(PULSE_SWITCH_PIN)

    return GPIOHandler(pulse_pin_reader=pulse_reader)

def _start_hook_watcher(hook_pin: int, audio, tts, menu, gpio) -> None:
    """Spin a daemon thread that watches the hook pin at ~1 ms intervals.

    Drives the amp and creates/closes Session the instant the pin changes
    state, bypassing the polling loop's debounce delay.  No-op on non-Pi hosts.
    """
    import threading

    def _watch():
        try:
            import RPi.GPIO as GPIO
        except (ImportError, RuntimeError):
            return
        last = GPIO.input(hook_pin)
        session = None
        while True:
            try:
                val = GPIO.input(hook_pin)
                if val != last:
                    last = val
                    if val == 1:   # HIGH = on cradle
                        log.info("hook: handset on cradle")
                        audio.amp_off()
                        tts.abort()
                        if session is not None:
                            session.close()
                            session = None
                    else:          # LOW = lifted
                        log.info("hook: handset lifted → starting session")
                        audio.amp_on()
                        session = Session(menu=menu, gpio=gpio)
                        session.start()
            except Exception:
                log.exception("hook-watcher error")
            time.sleep(0.001)

    t = threading.Thread(target=_watch, daemon=True, name="hook-watcher")
    t.start()
    log.info("Hook watcher thread started on BCM %d", hook_pin)


def run() -> None:
    """Main entry point — wire all components and start the event loop."""
    log.info("hello-operator starting up")

    # Ensure database directory exists before opening any SQLite files
    os.makedirs(_DB_DIR, exist_ok=True)

    # Data stores
    error_queue = SqliteErrorQueue(db_path=_ERROR_QUEUE_DB)
    phone_book = PhoneBook(db_path=_PHONE_BOOK_DB)

    # Seed phone book with radio stations
    stations = load_radio_stations(RADIO_CONFIG_PATH)
    for station in stations:
        phone_book.seed(
            phone_number=station.phone_number,
            media_key=f"radio:{station.frequency_hz}",
            media_type="radio",
            name=station.name,
        )

    # Hardware interfaces
    audio = SounddeviceAudio(device=ALSA_DEVICE, volume=AUDIO_VOLUME, sd_pin=SD_AMP_PIN)
    tts = PiperTTS(
        piper_binary=PIPER_BINARY,
        piper_model=PIPER_MODEL,
        cache_dir=TTS_CACHE_DIR,
        audio=audio,
        error_queue=error_queue,
    )

    # Media client + local cache
    media_client = build_media_client()
    media_store = MediaStore(db_path=_MEDIA_STORE_DB, media_client=media_client,
                             error_queue=error_queue)

    # Radio
    radio = RtlFmRadio()

    # Pre-render all fixed TTS scripts
    log.info("Pre-rendering %d TTS scripts...", len(_PRERENDER_SCRIPTS))
    tts.prerender(_PRERENDER_SCRIPTS)
    log.info("Pre-render complete.")

    # Menu state machine — constructed once, reused across sessions
    menu = Menu(
        audio=audio,
        tts=tts,
        media_client=media_client,
        media_store=media_store,
        phone_book=phone_book,
        error_queue=error_queue,
        radio=radio,
    )

    # GPIO handler — track whether GPIO was successfully initialised so the
    # finally block only calls _gpio_cleanup() when it is safe to do so.
    _gpio_ready = False
    gpio = build_gpio_handler()
    _gpio_ready = True
    _start_hook_watcher(HOOK_SWITCH_PIN, audio, tts, menu, gpio)

    log.info("hello-operator ready — waiting for handset lift")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        audio.stop()
        if _gpio_ready:
            _gpio_cleanup()


if __name__ == "__main__":
    run()
