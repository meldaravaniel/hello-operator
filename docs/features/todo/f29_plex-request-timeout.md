### F-29 · Configurable Plex request timeout

**Background**
All HTTP calls in `PlexClient` use a hardcoded `timeout=10` (seconds). Ten seconds is reasonable for a local server but may be too short for a remote Plex instance over a slow connection, and longer than necessary when diagnosing failures on a local server. Moving this value to a configurable constant lets deployers tune it without touching source code.

**Changes required**

#### 1. `src/constants.py` — add `PLEX_REQUEST_TIMEOUT`

```python
# Plex HTTP request timeout in seconds — optional; default suits most LAN setups
PLEX_REQUEST_TIMEOUT = int(os.environ.get("PLEX_REQUEST_TIMEOUT", "10"))
```

Cast to `int`; a non-integer value raises `ValueError` at import time (same pattern as `HOOK_SWITCH_PIN`).

#### 2. `src/plex_client.py` — replace hardcoded timeout

Import `PLEX_REQUEST_TIMEOUT` from `src.constants` and replace every `timeout=10` argument (11 occurrences) with `timeout=PLEX_REQUEST_TIMEOUT`.

#### 3. `config.env.example` — document the new variable

Add under the Plex section:

```bash
# HTTP request timeout in seconds for all Plex API calls (optional; default 10)
# Increase for slow remote servers; decrease for fast failure on local servers.
# PLEX_REQUEST_TIMEOUT=10
```

Leave it commented out so the default is visible without being an active assignment.

**Acceptance criteria**
- `constants.PLEX_REQUEST_TIMEOUT` equals `10` when `PLEX_REQUEST_TIMEOUT` is unset.
- Setting `PLEX_REQUEST_TIMEOUT=30` yields `constants.PLEX_REQUEST_TIMEOUT == 30`.
- Setting `PLEX_REQUEST_TIMEOUT=fast` raises `ValueError` at import.
- Every `requests.get` / `requests.post` call in `PlexClient` passes `timeout=PLEX_REQUEST_TIMEOUT`; no call uses a hardcoded integer.
- `config.env.example` documents the variable (commented out).

**Testable outcome**

New tests in `tests/test_constants.py` (extend the existing file):
- `test_plex_request_timeout_default` — with `PLEX_REQUEST_TIMEOUT` unset, `constants.PLEX_REQUEST_TIMEOUT == 10`.
- `test_plex_request_timeout_override` — set `PLEX_REQUEST_TIMEOUT=30`; assert `constants.PLEX_REQUEST_TIMEOUT == 30`.
- `test_plex_request_timeout_non_integer_raises` — set `PLEX_REQUEST_TIMEOUT=fast`; assert `ValueError` is raised on reimport.

New tests in `tests/test_plex_client.py`:
- `test_get_playlists_passes_timeout` — mock `requests.get`; call `client.get_playlists()`; assert the mock was called with `timeout=PLEX_REQUEST_TIMEOUT`.
- `test_play_passes_timeout` — mock `requests.get`; call `client.play("key")`; assert `timeout=PLEX_REQUEST_TIMEOUT` was passed.
- `test_pause_passes_timeout` — mock `requests.get`; call `client.pause()`; assert `timeout=PLEX_REQUEST_TIMEOUT` was passed.
