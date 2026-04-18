"""All configuration constants for hello-operator.

TBD values are set to reasonable placeholder values with TODO comments indicating
they need real values before deployment.

Secrets are loaded from environment variables at import time.  Required
variables raise RuntimeError immediately if absent so startup fails fast
rather than producing a silent authentication failure later.
"""

import os

# ---------------------------------------------------------------------------
# Media backend selection
# ---------------------------------------------------------------------------

MEDIA_BACKEND = os.environ.get("MEDIA_BACKEND", "mpd")  # "mpd" | "mopidy"

# ---------------------------------------------------------------------------
# Audio output device (ALSA device name passed to aplay -D)
# ---------------------------------------------------------------------------

ALSA_DEVICE = os.environ.get("ALSA_DEVICE", "plughw:MAX98357A")

# Software volume multiplier applied to all audio output (0.0–1.0).
# Reduce if the amp clips or buzzes; increase if output is too quiet.
# The MAX98357A GAIN pin floating = 15 dB hardware gain, so a lower
# default is appropriate to avoid clipping.
AUDIO_VOLUME = float(os.environ.get("AUDIO_VOLUME", "0.4"))

# ---------------------------------------------------------------------------
# MPD / Mopidy — only used when MEDIA_BACKEND=mpd or MEDIA_BACKEND=mopidy
# ---------------------------------------------------------------------------

MPD_HOST = os.environ.get("MPD_HOST", "localhost")
MPD_PORT = int(os.environ.get("MPD_PORT", "6600"))

# ---------------------------------------------------------------------------
# Timing constants (in seconds unless noted)
# ---------------------------------------------------------------------------

DIAL_TONE_TIMEOUT_IDLE = 5       # Silence before idle operator prompt
DIAL_TONE_TIMEOUT_PLAYING = 2    # Silence before playing-state prompt
INTER_DIGIT_TIMEOUT = 0.3        # Gap after last pulse → digit complete (300 ms)
DIRECT_DIAL_DISAMBIGUATION_TIMEOUT = 1.5  # TODO: tune on hardware — wait after first digit before treating as single nav input
INACTIVITY_TIMEOUT = 30          # Inactivity in any menu state → off-hook warning tone

# Audio constants
DIAL_TONE_FREQUENCIES = [350, 440]  # Standard PSTN dial tone (Hz)

# Menu constants
MAX_MENU_OPTIONS = 8             # Max items listed before narrowing required
PHONE_NUMBER_LENGTH = 7          # Digits in an assigned phone number
PHONE_NUMBER_GENERATE_MAX_ATTEMPTS = 1000  # Max retries before raising RuntimeError in _generate_unique_number
ASSISTANT_MESSAGE_PAGE_SIZE = 3  # Messages read aloud per page in assistant

# Reserved phone number for the diagnostic assistant — required
_assistant_number = os.environ.get("ASSISTANT_NUMBER")
if not _assistant_number:
    raise RuntimeError(
        "Required environment variable ASSISTANT_NUMBER is not set. "
        "Choose a 7-digit number not used by any media entry "
        "(e.g. export ASSISTANT_NUMBER=5550000)."
    )
if not _assistant_number.isdigit() or len(_assistant_number) != PHONE_NUMBER_LENGTH:
    raise RuntimeError(
        f"ASSISTANT_NUMBER must be exactly {PHONE_NUMBER_LENGTH} digits (got {_assistant_number!r})."
    )
ASSISTANT_NUMBER: str = _assistant_number

# GPIO debounce windows (in seconds)
HOOK_DEBOUNCE = 0.05             # TODO: tune on hardware — hook switch debounce window
PULSE_DEBOUNCE = 0.005           # TODO: tune on hardware — pulse switch debounce window

# TTS cache retry behaviour
CACHE_RETRY_MAX = 3              # TODO: tune — max repopulation attempts for missing TTS cache files
CACHE_RETRY_BACKOFF = 2.0        # TODO: tune — base backoff interval (seconds) between cache repopulation attempts

# TTS (Piper) configuration — optional; defaults match install.sh install paths
PIPER_BINARY = os.environ.get("PIPER_BINARY", "/usr/local/bin/piper")
PIPER_MODEL = os.environ.get("PIPER_MODEL", "/usr/local/share/piper/en_US-lessac-medium.onnx")
TTS_CACHE_DIR = os.environ.get("TTS_CACHE_DIR", "/var/cache/hello-operator/tts")

# GPIO pin assignments (BCM numbering) — optional; defaults match recommended wiring docs
HOOK_SWITCH_PIN = int(os.environ.get("HOOK_SWITCH_PIN", "17"))
PULSE_SWITCH_PIN = int(os.environ.get("PULSE_SWITCH_PIN", "27"))

# Radio configuration
RADIO_CONFIG_PATH = "/etc/hello-operator/radio_stations.json"

# Digit-to-word mapping used by TTS (speak_digits) and Menu (SCRIPT_CONNECTING_TEMPLATE)
DIGIT_WORDS = {
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
    '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
}
