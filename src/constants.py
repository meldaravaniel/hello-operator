"""All configuration constants for hello-operator.

TBD values are set to reasonable placeholder values with TODO comments indicating
they need real values before deployment.
"""

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
ASSISTANT_MESSAGE_PAGE_SIZE = 3  # Messages read aloud per page in assistant

# Reserved phone number for the diagnostic assistant
ASSISTANT_NUMBER = "5550000"     # TODO: set to the real reserved 7-digit number before deployment

# GPIO debounce windows (in seconds)
HOOK_DEBOUNCE = 0.05             # TODO: tune on hardware — hook switch debounce window
PULSE_DEBOUNCE = 0.005           # TODO: tune on hardware — pulse switch debounce window

# TTS cache retry behaviour
CACHE_RETRY_MAX = 3              # TODO: tune — max repopulation attempts for missing TTS cache files
CACHE_RETRY_BACKOFF = 2.0        # TODO: tune — base backoff interval (seconds) between cache repopulation attempts

# Plex server configuration
PLEX_URL = "http://localhost:32400"  # TODO: set to real Plex server URL
PLEX_TOKEN = "YOUR_PLEX_TOKEN"       # TODO: set to real Plex auth token
PLEX_PLAYER_IDENTIFIER = "YOUR_PLEX_PLAYER_ID"  # TODO: set to the machine identifier of the local Plex player (found in player settings or via /clients)

# TTS (Piper) configuration
PIPER_BINARY = "/usr/local/bin/piper"  # TODO: set to real Piper binary path
PIPER_MODEL = "/usr/local/share/piper/en_US-lessac-medium.onnx"  # TODO: set to real model path
TTS_CACHE_DIR = "/var/cache/hello-operator/tts"  # TODO: adjust path if needed

# GPIO pin assignments (BCM numbering)
HOOK_SWITCH_PIN = 17   # TODO: set to real GPIO pin number for hook switch
PULSE_SWITCH_PIN = 27  # TODO: set to real GPIO pin number for pulse switch
