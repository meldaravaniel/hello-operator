"""Audio output for hello-operator.

SounddeviceAudio — concrete implementation using sounddevice + numpy.
MockAudio        — records calls for use in unit tests.

All public play_* methods are non-blocking: they enqueue a task onto an
internal queue.Queue and return immediately.  A single daemon worker thread
dequeues and executes tasks in FIFO order.  Calling stop() clears the queue,
sets a stop event, and calls sd.stop() so current playback halts within one
polling cycle (~5 ms).
"""

import queue
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

# Sentinel object used to signal the worker thread to exit cleanly.
_STOP_SENTINEL = object()


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
    """Concrete audio implementation using sounddevice + numpy.

    All play_* methods enqueue a task and return immediately.  A single daemon
    worker thread executes tasks in FIFO order.  stop() drains the queue and
    halts current playback so the caller regains control within ~5 ms.
    """

    def __init__(self, sample_rate: int = _SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._busy = False  # True while worker is executing a task

        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    # ------------------------------------------------------------------
    # AudioInterface implementation
    # ------------------------------------------------------------------

    def play_tone(self, frequencies: list, duration_ms: int) -> None:
        """Enqueue a sine wave mix task; returns immediately."""
        waveform = _generate_tone(frequencies, duration_ms, self._sample_rate)
        self._enqueue(lambda: self._play_waveform(waveform))

    def play_file(self, path: str) -> None:
        """Enqueue a WAV file playback task; returns immediately."""
        # Read the file here (in the calling thread) so the path is accessed
        # before any later stop/clear can race with the enqueue.
        with wave.open(path, 'rb') as wf:
            sr = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())

        dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
        dtype = dtype_map.get(sample_width, np.int16)
        samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
        max_val = float(np.iinfo(dtype).max)
        samples = samples / max_val
        if n_channels > 1:
            samples = samples.reshape(-1, n_channels)

        self._enqueue(lambda: self._play_waveform(samples, sr))

    def play_dtmf(self, digit: int) -> None:
        """Enqueue the standard DTMF tone for digit 0–9; returns immediately."""
        freqs = list(_DTMF_FREQ[digit])
        self.play_tone(freqs, _DTMF_DURATION_MS)

    def play_off_hook_tone(self) -> None:
        """Enqueue a looping off-hook warning tone task; returns immediately."""
        waveform = _generate_tone(_OFF_HOOK_FREQ, _OFF_HOOK_SEGMENT_MS, self._sample_rate)
        self._enqueue(lambda: self._play_off_hook_loop(waveform))

    def stop(self) -> None:
        """Stop any current playback immediately and clear all queued tasks."""
        # Set stop event so the currently-executing task exits its polling loop.
        self._stop_event.set()
        # Drain all pending tasks from the queue.
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        # Tell sounddevice to stop immediately.
        sd.stop()
        # Mark as not playing.
        with self._lock:
            self._busy = False

    def is_playing(self) -> bool:
        """True if the worker is currently executing a task or the queue is non-empty."""
        with self._lock:
            return self._busy or not self._queue.empty()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enqueue(self, task) -> None:
        """Put a callable task onto the work queue.

        Also clears the stop event so the worker knows it should run tasks again
        (stop() sets it; enqueue clears it so new tasks execute normally).
        """
        self._stop_event.clear()
        self._queue.put(task)

    def _worker_loop(self) -> None:
        """Daemon worker: dequeue tasks and execute them sequentially."""
        while True:
            task = self._queue.get()
            if task is _STOP_SENTINEL:
                self._queue.task_done()
                break
            with self._lock:
                self._busy = True
            try:
                task()
            finally:
                self._queue.task_done()
                with self._lock:
                    self._busy = False

    def _play_waveform(self, samples: np.ndarray, sample_rate: int = None) -> None:
        """Play samples via sounddevice, polling for stop()."""
        if sample_rate is None:
            sample_rate = self._sample_rate
        self._stop_event.clear()
        sd.play(samples, samplerate=sample_rate)
        total = len(samples) / sample_rate
        interval = 0.005  # 5 ms polling — within one cycle of the stop guarantee
        elapsed = 0.0
        while elapsed < total:
            if self._stop_event.wait(timeout=interval):
                sd.stop()
                return
            elapsed += interval

    def _play_off_hook_loop(self, waveform: np.ndarray) -> None:
        """Loop the off-hook waveform segment until stop() is called."""
        self._stop_event.clear()
        while not self._stop_event.is_set():
            sd.play(waveform, samplerate=self._sample_rate)
            total = _OFF_HOOK_SEGMENT_MS / 1000.0
            interval = 0.005
            elapsed = 0.0
            while elapsed < total:
                if self._stop_event.wait(timeout=interval):
                    sd.stop()
                    return
                elapsed += interval


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
