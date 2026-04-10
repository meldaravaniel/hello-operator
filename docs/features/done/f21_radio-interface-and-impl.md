### F-21 · RadioInterface, RadioStation, and RtlFmRadio/MockRadio

**Background**
The DESIGN.md and CLAUDE.md have been updated to specify RTL-SDR FM radio reception as a new capability. An FM tuner (RTL2832U dongle) will be driven by the `rtl_fm` command-line tool. All radio state sits behind a new ABC — `RadioInterface` — so the menu can be tested without a real dongle.

**Changes required**

1. **`src/interfaces.py`** — add two new types:

```python
@dataclass
class RadioStation:
    name: str            # Human-readable station name (e.g. "KEXP")
    frequency_hz: float  # Carrier frequency in Hz (e.g. 90_300_000.0)
    phone_number: str    # Pre-configured 7-digit direct-dial number

class RadioInterface(ABC):
    @abstractmethod
    def play(self, frequency_hz: float) -> None:
        """Tune to the given frequency and begin streaming audio."""

    @abstractmethod
    def stop(self) -> None:
        """Stop radio playback."""

    @abstractmethod
    def is_playing(self) -> bool:
        """True if radio is currently streaming."""
```

Also update the `MediaItem` comment: `media_type: str  # "playlist" | "artist" | "album" | "genre" | "radio"`.

2. **`src/radio.py`** (new file) — `RtlFmRadio` and `MockRadio`:

`RtlFmRadio`:
- `play(frequency_hz)` checks that `rtl_fm` and `aplay` are on `PATH` (via `shutil.which`); raises `RuntimeError` if either is missing. Launches a pipeline:
  ```
  rtl_fm -f {int(frequency_hz)} -M fm -s 200k -r 48k - | aplay -r 48k -f S16_LE -t raw -
  ```
  Implemented by opening `aplay` first with `stdin=subprocess.PIPE`, then opening `rtl_fm` with `stdout=aplay_proc.stdin`. Stores both process objects as instance attributes.
- `stop()` terminates both processes (SIGTERM then wait up to 2 s; SIGKILL on timeout). Clears stored references to `None`.
- `is_playing()` returns `True` while `rtl_fm` process `poll()` returns `None`.

`MockRadio`:
- Tracks `calls: list` of `('play', freq)` or `('stop',)` tuples.
- Internal `_playing: bool` flag, initially `False`.
- `play()` appends `('play', frequency_hz)` and sets `_playing = True`.
- `stop()` appends `('stop',)` and sets `_playing = False`.
- `is_playing()` returns `_playing`.
- `set_playing(value: bool)` sets `_playing` directly (for test setup).

3. **`tests/conftest.py`** — add a `mock_radio` fixture:

```python
@pytest.fixture
def mock_radio():
    """MockRadio instance for menu/session tests."""
    from src.radio import MockRadio
    return MockRadio()
```

**Acceptance criteria**
- `RadioInterface` and `RadioStation` are importable from `src.interfaces`.
- `RtlFmRadio` and `MockRadio` are importable from `src.radio`.
- `MockRadio` correctly tracks play/stop calls and `is_playing()` state.
- `RtlFmRadio.play()` raises `RuntimeError` when `rtl_fm` is not on `PATH`.
- `mock_radio` fixture is available in all test files.

**Testable outcome**
New file `tests/test_radio.py`:
- `test_mock_radio_initial_state` — `is_playing()` is `False` before any call.
- `test_mock_radio_play` — after `play(90_300_000.0)`, `is_playing()` is `True` and `calls` contains `('play', 90_300_000.0)`.
- `test_mock_radio_stop` — after `play()` then `stop()`, `is_playing()` is `False` and `('stop',)` is in `calls`.
- `test_mock_radio_set_playing` — `set_playing(True)` makes `is_playing()` return `True`; `set_playing(False)` returns it to `False`.
- `test_rtl_fm_raises_when_not_on_path` — monkeypatch `src.radio.shutil.which` to return `None`; `RtlFmRadio().play(90_300_000.0)` raises `RuntimeError` with `"rtl_fm"` in the message.
