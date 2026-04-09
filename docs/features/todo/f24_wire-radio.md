### F-24 · Wire radio into session, main, and constants

**Background**
`Session` and `main.py` need to accept and inject `RadioInterface`. `main.py` also needs to load `radio_stations.json`, seed the phone book from it, and construct the `RtlFmRadio` instance. A new constant `RADIO_CONFIG_PATH` specifies where the JSON lives.

**Changes required**

#### 1. `src/constants.py` — add config path

```python
RADIO_CONFIG_PATH = "/etc/hello-operator/radio_stations.json"
```

#### 2. `src/session.py` — accept and pass through radio

Add `radio` as a required parameter to `Session.__init__`, store it, and forward it to `Menu`:

```python
def __init__(
    self,
    audio: AudioInterface,
    tts: TTSInterface,
    plex_client: PlexClientInterface,
    plex_store,
    phone_book,
    error_queue: ErrorQueueInterface,
    radio,  # RadioInterface
) -> None:
    self._menu = Menu(
        audio=audio,
        tts=tts,
        plex_client=plex_client,
        plex_store=plex_store,
        phone_book=phone_book,
        error_queue=error_queue,
        radio=radio,
    )
```

#### 3. `src/main.py` — load radio config, seed phone book, build RtlFmRadio

a. Add import of `RADIO_CONFIG_PATH` from constants and `RtlFmRadio` from radio.

b. Add import of `SCRIPT_RADIO_PLAYING_MENU` from menu to the prerender block.

c. Add a helper function `load_radio_stations(path: str) -> list[RadioStation]` that:
   - Reads and parses the JSON file at `path`.
   - Converts each entry: `frequency_hz = entry["frequency_mhz"] * 1_000_000`.
   - Returns a list of `RadioStation` objects.
   - If the file does not exist or cannot be parsed, logs a warning and returns `[]`.

d. In `run()`, after constructing `phone_book`:
   ```python
   # Seed phone book with radio stations
   stations = load_radio_stations(RADIO_CONFIG_PATH)
   for station in stations:
       phone_book.seed(
           phone_number=station.phone_number,
           plex_key=f"radio:{station.frequency_hz}",
           media_type="radio",
           name=station.name,
       )
   ```

e. Construct `RtlFmRadio`:
   ```python
   radio = RtlFmRadio()
   ```

f. Pass `radio=radio` to `Session(...)`.

g. Add `"radio_playing_menu": SCRIPT_RADIO_PLAYING_MENU` to `_PRERENDER_SCRIPTS`.

h. Also update `CLAUDE.md` project structure to add `radio.py`.

#### 4. `tests/test_session.py` — update to pass mock_radio

In existing `Session(...)` construction calls in tests, add `radio=mock_radio` (using the `mock_radio` fixture from conftest). Verify session still passes `radio` through to menu correctly by inspecting `session.menu.state` after a radio-number direct dial.

**Acceptance criteria**
- `Session.__init__` accepts a `radio` parameter and passes it to `Menu`.
- `run()` loads `radio_stations.json`, seeds the phone book, and creates `RtlFmRadio` before building `Session`.
- If `radio_stations.json` is absent, `run()` logs a warning but continues normally with no stations seeded.
- `RADIO_CONFIG_PATH` is defined in `constants.py`.
- `SCRIPT_RADIO_PLAYING_MENU` is included in `_PRERENDER_SCRIPTS`.
- All existing `test_session.py` tests pass with `radio=mock_radio` added to `Session(...)` calls.

**Testable outcome**
- `test_load_radio_stations_returns_list` — write a temp JSON file with two station entries; call `load_radio_stations(path)`; assert returns list of two `RadioStation` objects with correct `frequency_hz` (converted from MHz), names, and phone numbers.
- `test_load_radio_stations_missing_file` — call `load_radio_stations` with a nonexistent path; assert returns `[]` without raising.
- `test_session_passes_radio_to_menu` — construct a `Session` with `mock_radio`; verify that `session.menu._radio is mock_radio`.
