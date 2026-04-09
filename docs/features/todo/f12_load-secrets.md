### F-12 · Load secrets from environment variables

**Background**
`PLEX_URL`, `PLEX_TOKEN`, and `PLEX_PLAYER_IDENTIFIER` are currently hardcoded placeholders in `constants.py`. Storing secrets in committed source is a security risk.

**Changes required**

In `constants.py`, replace the hardcoded values with `os.environ` reads:

```python
import os
PLEX_URL = os.environ.get("PLEX_URL", "http://localhost:32400")
PLEX_TOKEN = os.environ["PLEX_TOKEN"]           # required; raise KeyError if absent
PLEX_PLAYER_IDENTIFIER = os.environ["PLEX_PLAYER_IDENTIFIER"]  # required
```

Required variables (`PLEX_TOKEN`, `PLEX_PLAYER_IDENTIFIER`) should raise `KeyError` (or a more descriptive `RuntimeError`) at import time if absent, not silently default to a broken value. Optional variables (`PLEX_URL`) may have a sensible default.

Add a `.env.example` file (not `.env`) to the repository root showing the required variable names with placeholder values.

**Acceptance criteria**
- Starting without `PLEX_TOKEN` set raises a clear error at startup, not a silent authentication failure later.
- Setting `PLEX_TOKEN=mytoken` in the environment is picked up correctly.
- `constants.py` contains no literal token strings.
- `.env.example` documents all required environment variables.

**Testable outcome**
- Input: import `src.constants` with `PLEX_TOKEN` unset in the environment.
- Expected: `RuntimeError` (or `KeyError`) raised with a message identifying the missing variable.