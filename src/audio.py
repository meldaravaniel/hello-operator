"""Audio output for hello-operator.

SounddeviceAudio — concrete implementation using a persistent aplay subprocess.
MockAudio        — records calls for use in unit tests.

All public play_* methods are non-blocking: they enqueue a task onto an
internal queue.Queue and return immediately.  A single daemon worker thread
dequeues and executes tasks in FIFO order.

A single long-running aplay process is kept alive for the lifetime of the
object, fed raw mono PCM at a fixed sample rate.  Between clips the worker
writes silence so the I2S clock never stops, preventing the MAX98357A (and
similar I2S amps) from powering down and producing a startup transient on
the next clip.  stop() drains the queue and sets a stop event so the current
clip exits within one chunk period (~20 ms); it does NOT kill the aplay
process.
"""

import io
import queue
import subprocess
import threading
import time
import wave
import numpy as np

from src.interfaces import AudioInterface

# Sample rate for the persistent aplay stream.  All audio is converted to
# this rate before being written.
_SAMPLE_RATE = 44100

# Number of frames per PCM write to aplay (~20 ms at 44100 Hz).
# Small enough for responsive stop(), large enough to avoid constant syscalls.
_CHUNK_FRAMES = 882  # 44100 * 0.02

# Duration of a single DTMF tone (ms).
_DTMF_DURATION_MS = 150

# Duration of each off-hook warning tone segment (ms).
_OFF_HOOK_SEGMENT_MS = 250

# Duration of the initial warmup silence written synchronously in __init__ (ms).
# This causes the MAX98357A to initialise (and produce its startup transient)
# at app launch time rather than on the first real user-facing audio clip.
_WARMUP_MS = 500

# Settle delay between writing warmup silence and raising the SD pin (ms).
# Gives aplay time to read from the pipe and push samples to the I2S hardware
# before the amp powers up — eliminates the startup transient entirely.
_SD_SETTLE_MS = 100

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
    """Generate a normalised sine wave mix for the given frequencies (float32, mono)."""
    n_samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000.0, n_samples, endpoint=False)
    wave_data = sum(np.sin(2 * np.pi * f * t) for f in frequencies)
    peak = np.max(np.abs(wave_data))
    if peak > 0:
        wave_data = wave_data / peak
    return wave_data.astype(np.float32)


class SounddeviceAudio(AudioInterface):
    """Concrete audio implementation using a persistent aplay subprocess (raw PCM).

    One aplay process is started at construction and kept alive indefinitely.
    The worker thread feeds it audio PCM when playing, and silence when idle,
    so the I2S clock never drops and I2S amps never produce a startup transient.

    All audio is converted to mono int16 PCM at _sample_rate before being
    written.  WAV files at different sample rates are resampled via linear
    interpolation.  Volume scaling is applied during conversion.

    aplay is invoked as:
        aplay -q -D <device> -f S16_LE -r <sample_rate> -c 1

    The _popen and _gpio_output parameters are injectable for unit testing.

    SD pin control (optional):
        If sd_pin is set, __init__ drives it LOW before starting aplay (keeping
        the amp in shutdown while the I2S clock starts), writes warmup silence,
        waits _SD_SETTLE_MS for the silence to reach the hardware, then drives
        SD HIGH so the amp powers up into a stable, silent stream — eliminating
        the startup transient entirely.  _gpio_output(pin, value) is the
        callable used to drive the pin; when None a lazy RPi.GPIO import is used.
    """

    def __init__(self, sample_rate: int = _SAMPLE_RATE, device: str = "default",
                 volume: float = 1.0, sd_pin: int = None,
                 _popen=None, _gpio_output=None) -> None:
        self._sample_rate = sample_rate
        self._device = device
        self._volume = max(0.0, min(1.0, volume))
        self._popen = _popen if _popen is not None else subprocess.Popen
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._busy = False

        # Resolve SD pin GPIO callable.
        self._sd_pin = sd_pin
        self._gpio_output = None
        if sd_pin is not None:
            if _gpio_output is not None:
                self._gpio_output = _gpio_output
            else:
                try:
                    import RPi.GPIO as GPIO  # type: ignore[import]
                    GPIO.setmode(GPIO.BCM)
                    GPIO.setup(sd_pin, GPIO.OUT, initial=GPIO.LOW)
                    self._gpio_output = lambda pin, val: GPIO.output(pin, val)
                except (ImportError, RuntimeError):
                    self._sd_pin = None  # GPIO unavailable; SD control disabled

        # Drive SD LOW (amp shutdown) before aplay starts so the I2S clock
        # cannot trigger a power-up transient during process launch.
        if self._sd_pin is not None:
            self._gpio_output(self._sd_pin, 0)

        self._proc = self._popen(
            ['aplay', '-q', '-D', self._device,
             '-f', 'S16_LE', '-r', str(self._sample_rate), '-c', '1'],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Write warmup silence so the I2S clock is running and the pipe buffer
        # is loaded before the amp is allowed to power up.
        _warmup_frames = int(self._sample_rate * _WARMUP_MS / 1000)
        _warmup_silence = np.zeros(_warmup_frames, dtype=np.int16).tobytes()
        try:
            self._proc.stdin.write(_warmup_silence)
        except (BrokenPipeError, OSError):
            pass

        # Raise SD so the amp powers up into a stable, silent I2S stream.
        # The settle delay gives aplay time to read from the pipe and push
        # samples to the hardware before the amp initialises.
        if self._sd_pin is not None:
            time.sleep(_SD_SETTLE_MS / 1000)
            self._gpio_output(self._sd_pin, 1)

        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    # ------------------------------------------------------------------
    # AudioInterface implementation
    # ------------------------------------------------------------------

    def play_tone(self, frequencies: list, duration_ms: int) -> None:
        """Enqueue a sine wave mix task; returns immediately."""
        waveform = _generate_tone(frequencies, duration_ms, self._sample_rate)
        pcm = self._waveform_to_pcm(waveform)
        self._enqueue(lambda: self._write_pcm(pcm))

    def play_file(self, path: str) -> None:
        """Enqueue a WAV file playback task; returns immediately.

        The file is decoded eagerly in the calling thread so the data is
        captured before any later stop/clear can race with the enqueue.
        """
        with open(path, 'rb') as f:
            wav_bytes = f.read()
        pcm = self._wav_to_pcm(wav_bytes)
        self._enqueue(lambda: self._write_pcm(pcm))

    def play_dtmf(self, digit: int) -> None:
        """Enqueue the standard DTMF tone for digit 0–9; returns immediately."""
        freqs = list(_DTMF_FREQ[digit])
        self.play_tone(freqs, _DTMF_DURATION_MS)

    def play_off_hook_tone(self) -> None:
        """Enqueue a looping off-hook warning tone task; returns immediately."""
        waveform = _generate_tone(_OFF_HOOK_FREQ, _OFF_HOOK_SEGMENT_MS, self._sample_rate)
        pcm = self._waveform_to_pcm(waveform)
        self._enqueue(lambda: self._write_pcm_loop(pcm))

    def stop(self) -> None:
        """Stop current playback and clear all queued tasks.

        Sets the stop event (causing the current clip to exit within one chunk
        period, ~20 ms) and drains the queue.  The aplay process is left
        running so the I2S clock stays active.
        """
        self._stop_event.set()
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
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
        """Put a callable task onto the work queue and clear the stop event."""
        self._stop_event.clear()
        self._queue.put(task)

    def _worker_loop(self) -> None:
        """Daemon worker: run tasks from the queue; write silence when idle."""
        chunk_duration = _CHUNK_FRAMES / self._sample_rate
        silence = np.zeros(_CHUNK_FRAMES, dtype=np.int16).tobytes()
        while True:
            try:
                task = self._queue.get(timeout=chunk_duration)
            except queue.Empty:
                # Keep I2S clock alive between clips.
                self._write_raw(silence)
                continue
            with self._lock:
                self._busy = True
            try:
                task()
            finally:
                self._queue.task_done()
                with self._lock:
                    self._busy = False

    def _write_raw(self, pcm: bytes) -> None:
        """Write raw PCM bytes to the persistent aplay stdin; swallow broken pipe."""
        try:
            self._proc.stdin.write(pcm)
        except (BrokenPipeError, OSError):
            pass

    def _write_pcm(self, pcm: bytes) -> None:
        """Write PCM in chunks, returning early if stop() is called."""
        chunk_bytes = _CHUNK_FRAMES * 2  # int16 = 2 bytes per sample
        offset = 0
        while offset < len(pcm):
            if self._stop_event.is_set():
                return
            self._write_raw(pcm[offset:offset + chunk_bytes])
            offset += chunk_bytes

    def _write_pcm_loop(self, pcm: bytes) -> None:
        """Write PCM in a loop until stop() is called (used for off-hook tone)."""
        chunk_bytes = _CHUNK_FRAMES * 2
        offset = 0
        while not self._stop_event.is_set():
            end = offset + chunk_bytes
            self._write_raw(pcm[offset:min(end, len(pcm))])
            offset = end
            if offset >= len(pcm):
                offset = 0

    def _waveform_to_pcm(self, waveform: np.ndarray) -> bytes:
        """Convert a float32 mono waveform [-1, 1] to int16 PCM with volume."""
        samples = (np.clip(waveform, -1.0, 1.0) * 32767 * self._volume).astype(np.int16)
        return samples.tobytes()

    def _wav_to_pcm(self, wav_bytes: bytes) -> bytes:
        """Decode WAV bytes to mono int16 PCM at self._sample_rate with volume.

        Handles stereo→mono downmix and resampling via linear interpolation.
        """
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, 'rb') as wf:
            sr = wf.getframerate()
            nch = wf.getnchannels()
            sw = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
        dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sw, np.int16)
        samples = np.frombuffer(raw, dtype=dtype).copy().astype(np.float32)
        samples /= float(np.iinfo(dtype).max)  # normalise to [-1, 1]
        if nch == 2:
            samples = samples.reshape(-1, 2).mean(axis=1)
        if sr != self._sample_rate:
            n_out = int(len(samples) * self._sample_rate / sr)
            old_t = np.arange(len(samples))
            new_t = np.linspace(0, len(samples) - 1, n_out)
            samples = np.interp(new_t, old_t, samples)
        return (np.clip(samples, -1.0, 1.0) * 32767 * self._volume).astype(np.int16).tobytes()


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
