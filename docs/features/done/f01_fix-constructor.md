### F-01 · Fix constructor argument mismatches in `main.py`

**Background**
Three concrete classes are instantiated with wrong keyword argument names, causing `TypeError` immediately on `run()`.

**Changes required**

| Location | Wrong call | Correct call |
|---|---|---|
| `main.py:138` | `PiperTTS(model_path=PIPER_MODEL, ...)` | `PiperTTS(piper_model=PIPER_MODEL, ...)` |
| `main.py:146` | `PlexClient(base_url=PLEX_URL, ...)` | `PlexClient(url=PLEX_URL, ...)` |
| `main.py:119–123` | `GPIOHandler(hook_reader=..., pulse_reader=..., hook_debounce=..., pulse_debounce=...)` | `GPIOHandler(hook_pin_reader=..., pulse_pin_reader=...)` (debounce params do not exist on the class) |

**Acceptance criteria**
- `python main.py` reaches the `"hello-operator ready"` log line without raising `TypeError`.
- All existing unit tests continue to pass.

**Testable outcome**
- Input: call `run()` in an environment where GPIO/Plex/Piper are mocked or unavailable.
- Expected: no `TypeError` is raised during object construction.
