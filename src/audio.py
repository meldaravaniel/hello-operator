"""Audio output for hello-operator.

SounddeviceAudio — concrete implementation using aplay (subprocess).
MockAudio        — records calls for use in unit tests.

All public play_* methods are non-blocking: they enqueue a task onto an
internal queue.Queue and return immediately.  A single daemon worker thread
dequeues and executes tasks in FIFO order.  Calling stop() clears the queue,
sets a stop event, and terminates the current aplay process so current
playback halts within one polling cycle (~5 ms).

aplay is used instead of sounddevice because it talks directly to ALSA and
works in a systemd service context where PulseAudio is not available.
"""

import io
import queue
import subprocess
import threading
import wave
import numpy as np

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


def _array_to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """Convert a float32 numpy array to in-memory WAV bytes (int16).

    Multi-channel arrays (shape [frames, channels]) are flattened to
    interleaved samples before encoding.
    """
    samples_i16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    if samples_i16.ndim > 1:
        n_channels = samples_i16.shape[1]
        data = samples_i16.flatten()
    else:
        n_channels = 1
        data = samples_i16
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(2)  # int16 = 2 bytes per sample
        wf.setframerate(sample_rate)
        wf.writeframes(data.tobytes())
    return buf.getvalue()


class SounddeviceAudio(AudioInterface):
    """Concrete audio implementation using aplay (subprocess).

    All play_* methods enqueue a task and return immediately.  A single daemon
    worker thread executes tasks in FIFO order.  stop() drains the queue and
    terminates the current aplay process so the caller regains control within ~5 ms.

    aplay is invoked as ``aplay -q -`` (read WAV from stdin, quiet mode).  It
    talks directly to ALSA, which works in a systemd service context where
    PulseAudio is not available.

    The _popen parameter is injectable for unit testing.
    """

    def __init__(self, sample_rate: int = _SAMPLE_RATE, _popen=None) -> None:
        self._sample_rate = sample_rate
        self._popen = _popen if _popen is not None else subprocess.Popen
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._busy = False  # True while worker is executing a task
        self._proc = None   # Currently running aplay subprocess (if any)

        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    # ------------------------------------------------------------------
    # AudioInterface implementation
    # ------------------------------------------------------------------

    def play_tone(self, frequencies: list, duration_ms: int) -> None:
        """Enqueue a sine wave mix task; returns immediately."""
        waveform = _generate_tone(frequencies, duration_ms, self._sample_rate)
        wav_bytes = _array_to_wav_bytes(waveform, self._sample_rate)
        self._enqueue(lambda: self._play_bytes(wav_bytes))

    def play_file(self, path: str) -> None:
        """Enqueue a WAV file playback task; returns immediately.

        The file is read eagerly here (in the calling thread) so the data is
        captured before any later stop/clear can race with the enqueue.
        """
        with open(path, 'rb') as f:
            wav_bytes = f.read()
        self._enqueue(lambda: self._play_bytes(wav_bytes))

    def play_dtmf(self, digit: int) -> None:
        """Enqueue the standard DTMF tone for digit 0–9; returns immediately."""
        freqs = list(_DTMF_FREQ[digit])
        self.play_tone(freqs, _DTMF_DURATION_MS)

    def play_off_hook_tone(self) -> None:
        """Enqueue a looping off-hook warning tone task; returns immediately."""
        waveform = _generate_tone(_OFF_HOOK_FREQ, _OFF_HOOK_SEGMENT_MS, self._sample_rate)
        wav_bytes = _array_to_wav_bytes(waveform, self._sample_rate)
        self._enqueue(lambda: self._play_off_hook_loop(wav_bytes))

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
        # Terminate any running aplay process.
        with self._lock:
            proc = self._proc
            self._busy = False
        if proc is not None:
            proc.terminate()

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
            with self._lock:
                self._busy = True
            try:
                task()
            finally:
                self._queue.task_done()
                with self._lock:
                    self._busy = False

    def _play_bytes(self, wav_bytes: bytes) -> None:
        """Play WAV bytes via aplay subprocess, polling for the stop event."""
        proc = self._popen(
            ['aplay', '-q', '-'],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with self._lock:
            self._proc = proc
        try:
            if self._stop_event.is_set():
                proc.terminate()
                return
            try:
                proc.stdin.write(wav_bytes)
                proc.stdin.close()
            except BrokenPipeError:
                return
            while proc.poll() is None:
                if self._stop_event.wait(timeout=0.005):
                    proc.terminate()
                    proc.wait()
                    return
        finally:
            proc.wait()
            with self._lock:
                if self._proc is proc:
                    self._proc = None

    def _play_off_hook_loop(self, wav_bytes: bytes) -> None:
        """Loop aplay with the off-hook waveform until stop() is called."""
        while not self._stop_event.is_set():
            proc = self._popen(
                ['aplay', '-q', '-'],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._proc = proc
            try:
                if self._stop_event.is_set():
                    proc.terminate()
                    return
                try:
                    proc.stdin.write(wav_bytes)
                    proc.stdin.close()
                except BrokenPipeError:
                    return
                while proc.poll() is None:
                    if self._stop_event.wait(timeout=0.005):
                        proc.terminate()
                        proc.wait()
                        return
            finally:
                proc.wait()
                with self._lock:
                    if self._proc is proc:
                        self._proc = None


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
