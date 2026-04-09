"""All configuration constants for hello-operator.

TBD values are set to reasonable placeholder values with TODO comments indicating
they need real values before deployment.

Secrets are loaded from environment variables at import time.  Required
variables raise RuntimeError immediately if absent so startup fails fast
rather than producing a silent authentication failure later.
"""

import os

# ---------------------------------------------------------------------------
# Secrets — loaded from environment variables
# ---------------------------------------------------------------------------

PLEX_URL = os.environ.get("PLEX_URL", "http://localhost:32400")

_plex_token = os.environ.get("PLEX_TOKEN")
if not _plex_token:
    raise RuntimeError(
        "Required environment variable PLEX_TOKEN is not set. "
        "Export it before starting hello-operator (e.g. export PLEX_TOKEN=<your-token>)."
    )
PLEX_TOKEN: str = _plex_token

_plex_player_identifier = os.environ.get("PLEX_PLAYER_IDENTIFIER")
if not _plex_player_identifier:
    raise RuntimeError(
        "Required environment variable PLEX_PLAYER_IDENTIFIER is not set. "
        "Export it before starting hello-operator "
        "(e.g. export PLEX_PLAYER_IDENTIFIER=<machine-identifier>)."
    )
PLEX_PLAYER_IDENTIFIER: str = _plex_player_identifier

# Timing constants (in seconds unless noted)
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

# Reserved phone number for the diagnostic assistant
ASSISTANT_NUMBER = "5550000"     # TODO: set to the real reserved 7-digit number before deployment

# GPIO debounce windows (in seconds)
HOOK_DEBOUNCE = 0.05             # TODO: tune on hardware — hook switch debounce window
PULSE_DEBOUNCE = 0.005           # TODO: tune on hardware — pulse switch debounce window

# TTS cache retry behaviour
CACHE_RETRY_MAX = 3              # TODO: tune — max repopulation attempts for missing TTS cache files
CACHE_RETRY_BACKOFF = 2.0        # TODO: tune — base backoff interval (seconds) between cache repopulation attempts

# TTS (Piper) configuration
PIPER_BINARY = "/usr/local/bin/piper"  # TODO: set to real Piper binary path
PIPER_MODEL = "/usr/local/share/piper/en_US-lessac-medium.onnx"  # TODO: set to real model path
TTS_CACHE_DIR = "/var/cache/hello-operator/tts"  # TODO: adjust path if needed

# GPIO pin assignments (BCM numbering)
HOOK_SWITCH_PIN = 17   # TODO: set to real GPIO pin number for hook switch
PULSE_SWITCH_PIN = 27  # TODO: set to real GPIO pin number for pulse switch

# Digit-to-word mapping used by TTS (speak_digits) and Menu (SCRIPT_CONNECTING_TEMPLATE)
DIGIT_WORDS = {
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
    '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
}
