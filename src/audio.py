"""Audio output for hello-operator.

SounddeviceAudio — concrete implementation using sounddevice + numpy.
MockAudio        — records calls for use in unit tests.

All playback supports immediate stop via stop().
"""

import threading
import wave
import numpy as np
import sounddevice as sd

from src.interfaces import AudioInterface

# Sample rate used for all generated waveforms and file playback.
_SAMPLE_RATE = 44100

# Duration of a single DTMF tone (ms).
_DTMF_DURATION_MS = 150

# Duration of each off-hook warning tone segment (ms) — looped continuously.
_OFF_HOOK_SEGMENT_MS = 250

# DTMF frequency pairs (row, column) per digit.
_DTMF_FREQ = {
    0: (941, 1336),
    1: (697, 1209),
    2: (697, 1336),
    3: (697, 1477),
    4: (770, 1209),
    5: (770, 1336),
    6: (770, 1477),
    7: (852, 1209),
    8: (852, 1336),
    9: (852, 1477),
}

# Off-hook warning tone frequencies (alternating cadence — standard US ROH).
_OFF_HOOK_FREQ = [1400, 2060, 2450, 2600]


def _generate_tone(frequencies: list, duration_ms: int, sample_rate: int = _SAMPLE_RATE) -> np.ndarray:
    """Generate a normalized sine wave mix for the given frequencies."""
    n_samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000.0, n_samples, endpoint=False)
    wave_data = sum(np.sin(2 * np.pi * f * t) for f in frequencies)
    # Normalize to [-1, 1]
    peak = np.max(np.abs(wave_data))
    if peak > 0:
        wave_data = wave_data / peak
    return wave_data.astype(np.float32)


class SounddeviceAudio(AudioInterface):
    """Concrete audio implementation using sounddevice + numpy."""

    def __init__(self, sample_rate: int = _SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._lock = threading.Lock()
        self._playing = False
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # AudioInterface implementation
    # ------------------------------------------------------------------

    def play_tone(self, frequencies: list, duration_ms: int) -> None:
        """Generate and play a sine wave mix; blocks for the duration."""
        self._stop_playing()
        waveform = _generate_tone(frequencies, duration_ms, self._sample_rate)
        with self._lock:
            self._playing = True
            self._stop_event.clear()
        sd.play(waveform, samplerate=self._sample_rate)
        # Wait for either natural end or stop() call
        n_samples = len(waveform)
        interval = 0.01
        elapsed = 0.0
        total = duration_ms / 1000.0
        while elapsed < total:
            if self._stop_event.wait(timeout=interval):
                sd.stop()
                break
            elapsed += interval
        with self._lock:
            self._playing = False

    def play_file(self, path: str) -> None:
        """Read a WAV file and play it via sounddevice."""
        self._stop_playing()
        with wave.open(path, 'rb') as wf:
            sr = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())

        dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
        dtype = dtype_map.get(sample_width, np.int16)
        samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
        # Normalize
        max_val = float(np.iinfo(dtype).max)
        samples = samples / max_val
        if n_channels > 1:
            samples = samples.reshape(-1, n_channels)

        with self._lock:
            self._playing = True
            self._stop_event.clear()
        sd.play(samples, samplerate=sr)
        total = len(samples) / sr
        interval = 0.01
        elapsed = 0.0
        while elapsed < total:
            if self._stop_event.wait(timeout=interval):
                sd.stop()
                break
            elapsed += interval
        with self._lock:
            self._playing = False

    def play_dtmf(self, digit: int) -> None:
        """Play the standard DTMF tone for digit 0–9."""
        freqs = list(_DTMF_FREQ[digit])
        self.play_tone(freqs, _DTMF_DURATION_MS)

    def play_off_hook_tone(self) -> None:
        """Play off-hook warning tone in a loop until stop() is called."""
        self._stop_playing()
        waveform = _generate_tone(_OFF_HOOK_FREQ, _OFF_HOOK_SEGMENT_MS, self._sample_rate)
        with self._lock:
            self._playing = True
            self._stop_event.clear()
        while not self._stop_event.is_set():
            sd.play(waveform, samplerate=self._sample_rate)
            interval = 0.01
            elapsed = 0.0
            total = _OFF_HOOK_SEGMENT_MS / 1000.0
            while elapsed < total:
                if self._stop_event.wait(timeout=interval):
                    sd.stop()
                    break
                elapsed += interval
        with self._lock:
            self._playing = False

    def stop(self) -> None:
        """Stop any current playback immediately."""
        self._stop_event.set()
        sd.stop()
        with self._lock:
            self._playing = False

    def is_playing(self) -> bool:
        """True if audio is currently playing."""
        with self._lock:
            return self._playing

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stop_playing(self) -> None:
        """Stop any current playback before starting new audio."""
        if self.is_playing():
            self.stop()


class MockAudio(AudioInterface):
    """Records all calls; used in all higher-level unit tests."""

    def __init__(self) -> None:
        self.calls: list = []
        self._playing = False

    def play_tone(self, frequencies: list, duration_ms: int) -> None:
        self.calls.append(('play_tone', frequencies, duration_ms))
        self._playing = True

    def play_file(self, path: str) -> None:
        self.calls.append(('play_file', path))
        self._playing = True

    def play_dtmf(self, digit: int) -> None:
        self.calls.append(('play_dtmf', digit))
        self._playing = True

    def play_off_hook_tone(self) -> None:
        self.calls.append(('play_off_hook_tone',))
        self._playing = True

    def stop(self) -> None:
        self.calls.append(('stop',))
        self._playing = False

    def is_playing(self) -> bool:
        return self._playing
