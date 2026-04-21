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
from gpiozero import Button, OutputDevice                                             
from src.error_queue import SqliteErrorQueue
from src.phone import Phone
from src.phone_book import PhoneBook
from src.audio import SounddeviceAudio
from src.tts import PiperTTS
from src.mpd_client import MPDClient
from src.media_store import MediaStore
from src.radio import RtlFmRadio
from src.interfaces import RadioStation, MediaClientInterface

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
    
    # Set up the GPIO "Buttons"
    hook_pin_button = Button(HOOK_SWITCH_PIN, pull_up=True)
    pulse_pin_button = Button(PULSE_SWITCH_PIN, pull_up=False)
    shutdown_pin_output = OutputDevice(SD_AMP_PIN)

    # Hardware interfaces
    audio = SounddeviceAudio(shutdown_pin_output, device=ALSA_DEVICE, volume=AUDIO_VOLUME)
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
    
   phone = Phone(hook_pin_button, pulse_pin_button, tts, audio, menu)
    phone.start()
    log.info("hello-operator ready — waiting for handset lift")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        audio.stop()


if __name__ == "__main__":
    run()
