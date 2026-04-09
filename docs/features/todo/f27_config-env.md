### F-27 · config.env.example and env-var loading for remaining TODO constants

**Background**
f12 moved Plex secrets to environment variables. Several other constants still carry `TODO` comments and require editing `src/constants.py` before deployment: `ASSISTANT_NUMBER`, `PIPER_BINARY`, `PIPER_MODEL`, `HOOK_SWITCH_PIN`, and `PULSE_SWITCH_PIN`. Moving these to env vars means a deployer never needs to touch source code — all site-specific configuration lives in one file outside the repo.

Hardware-tuning constants (`HOOK_DEBOUNCE`, `PULSE_DEBOUNCE`, `CACHE_RETRY_MAX`, etc.) are intentionally left in `constants.py`; they require code-level understanding to tune and are not deployment configuration.

**Changes required**

#### 1. `src/constants.py` — move remaining TODO constants to env vars

Replace each hardcoded TODO value with an `os.environ` read. Use the same pattern as f12: required variables raise `RuntimeError` at import time; optional variables use a sensible default.

```python
# TTS (Piper) configuration — optional; defaults match install.sh install paths
PIPER_BINARY = os.environ.get("PIPER_BINARY", "/usr/local/bin/piper")
PIPER_MODEL  = os.environ.get("PIPER_MODEL",  "/usr/local/share/piper/en_US-lessac-medium.onnx")
TTS_CACHE_DIR = os.environ.get("TTS_CACHE_DIR", "/var/cache/hello-operator/tts")

# GPIO pin assignments (BCM numbering) — optional; defaults match recommended wiring docs
HOOK_SWITCH_PIN  = int(os.environ.get("HOOK_SWITCH_PIN",  "17"))
PULSE_SWITCH_PIN = int(os.environ.get("PULSE_SWITCH_PIN", "27"))

# Reserved diagnostic assistant number — required
_assistant_number = os.environ.get("ASSISTANT_NUMBER")
if not _assistant_number:
    raise RuntimeError(
        "Required environment variable ASSISTANT_NUMBER is not set. "
        "Choose a 7-digit number not used by any media entry "
        "(e.g. export ASSISTANT_NUMBER=5550000)."
    )
ASSISTANT_NUMBER: str = _assistant_number
```

Remove the `TODO` comments from all affected lines.

#### 2. `config.env.example` — add to project root

```bash
# hello-operator configuration
# Copy to /etc/hello-operator/config.env and fill in values before starting.
# Lines beginning with # are comments and are ignored.

# ---------------------------------------------------------------------------
# Plex (required)
# ---------------------------------------------------------------------------

# Full URL of your Plex Media Server
PLEX_URL=http://localhost:32400

# Plex authentication token
# Find yours at: https://support.plex.tv/articles/204059436
PLEX_TOKEN=

# Machine identifier of the Plex player to control
# Find yours in Plex Settings → Troubleshooting → "Download logs" or via the API
PLEX_PLAYER_IDENTIFIER=

# ---------------------------------------------------------------------------
# Phone system (required)
# ---------------------------------------------------------------------------

# 7-digit number reserved for the diagnostic assistant
# Must not conflict with any auto-assigned media number
ASSISTANT_NUMBER=5550000

# ---------------------------------------------------------------------------
# GPIO pin assignments — BCM numbering (optional; defaults match wiring docs)
# ---------------------------------------------------------------------------

HOOK_SWITCH_PIN=17
PULSE_SWITCH_PIN=27

# ---------------------------------------------------------------------------
# Piper TTS (optional; defaults match paths used by install.sh)
# ---------------------------------------------------------------------------

PIPER_BINARY=/usr/local/bin/piper
PIPER_MODEL=/usr/local/share/piper/en_US-lessac-medium.onnx
TTS_CACHE_DIR=/var/cache/hello-operator/tts
```

**Acceptance criteria**
- `src/constants.py` contains no literal TODO values for `ASSISTANT_NUMBER`, `PIPER_BINARY`, `PIPER_MODEL`, `HOOK_SWITCH_PIN`, or `PULSE_SWITCH_PIN`.
- Starting without `ASSISTANT_NUMBER` set raises a clear `RuntimeError` at import time.
- `HOOK_SWITCH_PIN` and `PULSE_SWITCH_PIN` are cast to `int`; passing a non-integer string raises `ValueError` at startup.
- `config.env.example` exists at the project root and documents every variable accepted by `constants.py`.
- All existing tests pass (they set env vars in `conftest.py` or `monkeypatch`, as needed).

**Testable outcome**
New tests in a new `tests/test_constants.py`:
- `test_missing_plex_token_raises` — unset `PLEX_TOKEN` and reimport `src.constants`; assert `RuntimeError`.
- `test_missing_assistant_number_raises` — unset `ASSISTANT_NUMBER`; assert `RuntimeError`.
- `test_hook_pin_default` — with `HOOK_SWITCH_PIN` unset, `constants.HOOK_SWITCH_PIN == 17`.
- `test_hook_pin_override` — set `HOOK_SWITCH_PIN=22`; assert `constants.HOOK_SWITCH_PIN == 22`.

> **Note:** `src.constants` must be reimported (via `importlib.reload` or `subprocess`) in each test because it runs top-level code at import time. Using `monkeypatch.setenv` before the import achieves this cleanly when combined with `importlib.reload(src.constants)`.
