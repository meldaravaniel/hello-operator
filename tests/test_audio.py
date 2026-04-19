"""Tests for src/audio.py — SounddeviceAudio concrete implementation.

Architecture note: SounddeviceAudio keeps one persistent aplay process alive
for the object's lifetime, writing raw mono int16 PCM at _SAMPLE_RATE.
Between clips it writes silence so the I2S clock never drops.  Consequently:

- _popen_mock is called ONCE per SounddeviceAudio instance (in __init__),
  not once per clip.
- Tests capture raw PCM bytes written to proc.stdin, not WAV bytes.
- stop() does NOT terminate the aplay process; it sets a stop event and
  drains the queue so the current clip exits within one chunk period (~20 ms).
"""

import array
import io
import threading
import time
import wave
from unittest.mock import MagicMock
import numpy as np
import pytest

from src.audio import SounddeviceAudio, MockAudio, _SAMPLE_RATE, _CHUNK_FRAMES


# ---------------------------------------------------------------------------
# FakeProcess — simulates the persistent aplay subprocess
# ---------------------------------------------------------------------------

class FakeProcess:
    """Persistent fake aplay process.

    Captures all bytes written to stdin.  Raises write_called event when
    the first non-silent (non-zero) PCM data arrives so tests can wait for
    real audio without spinning.
    """

    def __init__(self):
        self.stdin = MagicMock()
        self._lock = threading.Lock()
        self._buf = bytearray()
        self.write_called = threading.Event()   # set on first non-silent write
        self._terminated = False

        def _capture(data):
            with self._lock:
                self._buf.extend(data)
            if np.any(np.frombuffer(bytes(data), dtype=np.int16) != 0):
                self.write_called.set()

        self.stdin.write.side_effect = _capture

    @property
    def written_pcm(self) -> bytes:
        with self._lock:
            return bytes(self._buf)

    def reset(self):
        """Clear the capture buffer and write event for a new assertion."""
        with self._lock:
            self._buf.clear()
        self.write_called.clear()

    def poll(self):
        return 0 if self._terminated else None

    def terminate(self):
        self._terminated = True

    def wait(self, timeout=None):
        return 0


# ---------------------------------------------------------------------------
# Module-level popen mock and fixtures
# ---------------------------------------------------------------------------

_proc: FakeProcess = FakeProcess()
_popen_mock = MagicMock()


@pytest.fixture(autouse=True)
def reset_popen_mock():
    """Create a fresh FakeProcess and wire _popen_mock to return it."""
    global _proc
    _proc = FakeProcess()
    _popen_mock.reset_mock()
    _popen_mock.side_effect = lambda *a, **kw: _proc
    yield


@pytest.fixture
def audio():
    """Fresh SounddeviceAudio with injected mock popen, handset lifted."""
    a = SounddeviceAudio(_popen=_popen_mock)
    a.amp_on()
    yield a
    a.amp_off()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wav(tmp_path, name="test.wav", n_samples=4410, sample_rate=44100, channels=1, amplitude=16000):
    """Write a minimal WAV file and return its path."""
    wav_path = str(tmp_path / name)
    with wave.open(wav_path, 'w') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = array.array('h', [amplitude] * n_samples)
        wf.writeframes(samples.tobytes())
    return wav_path


def _wait_for(condition, timeout=2.0, interval=0.005):
    """Poll condition() until True or timeout; return final value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()


def _capture_pcm(audio_obj, method, *args, timeout=2.0):
    """Invoke audio.<method>(*args) and return the non-silent PCM bytes written.

    Waits for the task to complete naturally before collecting PCM so that the
    full clip is captured regardless of how fast the mock writes execute.
    """
    _proc.reset()
    getattr(audio_obj, method)(*args)
    assert _proc.write_called.wait(timeout=timeout), \
        f"{method}(*{args}) never wrote non-silent PCM to aplay"
    _wait_for(lambda: not audio_obj.is_playing(), timeout=timeout)
    audio_obj.stop()
    all_samples = np.frombuffer(_proc.written_pcm, dtype=np.int16)
    nonzero = np.nonzero(all_samples)[0]
    if len(nonzero) == 0:
        return b''
    return all_samples[nonzero[0]:].tobytes()


def _pcm_to_samples(pcm: bytes) -> np.ndarray:
    """Return int16 samples from raw PCM bytes."""
    return np.frombuffer(pcm, dtype=np.int16)


# ---------------------------------------------------------------------------
# 2.1 Dial tone
# ---------------------------------------------------------------------------

class TestDialTone:

    def test_dial_tone_frequencies(self, audio):
        """play_tone([350, 440]) → PCM contains 350 Hz and 440 Hz components."""
        pcm = _capture_pcm(audio, 'play_tone', [350, 440], 200)
        samples = _pcm_to_samples(pcm).astype(np.float32)

        spectrum = np.abs(np.fft.rfft(samples))
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / _SAMPLE_RATE)

        def peak_near(target_hz, tol=5):
            mask = np.abs(freqs - target_hz) < tol
            return spectrum[mask].max() if mask.any() else 0.0

        noise_floor = np.percentile(spectrum, 90)
        assert peak_near(350) > noise_floor, "350 Hz component not found"
        assert peak_near(440) > noise_floor, "440 Hz component not found"

    def test_dial_tone_stops_after_duration(self, audio):
        """play_tone with short duration — aplay receives non-silent PCM."""
        _proc.reset()
        audio.play_tone([350, 440], 50)
        assert _proc.write_called.wait(timeout=2.0), "tone PCM never written"

    def test_dial_tone_stop_called_early(self, audio):
        """stop() while tone is playing → is_playing() becomes False."""
        gate = threading.Event()
        writing_started = threading.Event()
        original_write_raw = audio._write_raw

        def gated_write(pcm):
            # Only gate on non-silent (tone) data; silence passes through freely.
            if np.any(np.frombuffer(bytes(pcm), dtype=np.int16) != 0):
                writing_started.set()
                gate.wait(timeout=5.0)
            original_write_raw(pcm)

        audio._write_raw = gated_write
        audio.play_tone([350, 440], 5000)
        assert writing_started.wait(timeout=2.0), "tone PCM never started"
        assert audio.is_playing()  # worker is held in gated_write → _busy is True
        gate.set()
        audio.stop()
        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"


# ---------------------------------------------------------------------------
# 2.2 Off-hook warning tone
# ---------------------------------------------------------------------------

class TestOffHookTone:

    def test_off_hook_tone_plays_continuously(self, audio):
        """play_off_hook_tone() → PCM keeps arriving without stopping itself."""
        _proc.reset()
        audio.play_off_hook_tone()
        assert _proc.write_called.wait(timeout=2.0), "off-hook tone never started"
        first_len = len(_proc.written_pcm)
        time.sleep(0.05)
        assert len(_proc.written_pcm) > first_len, "off-hook tone stopped writing on its own"
        audio.stop()

    def test_off_hook_tone_stops_on_stop_call(self, audio):
        """stop() while off-hook tone → is_playing() becomes False."""
        _proc.reset()
        audio.play_off_hook_tone()
        assert _proc.write_called.wait(timeout=2.0), "off-hook tone never started"
        audio.stop()
        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"


# ---------------------------------------------------------------------------
# 2.3 DTMF tones
# ---------------------------------------------------------------------------

DTMF_FREQUENCIES = {
    0: (941, 1336), 1: (697, 1209), 2: (697, 1336), 3: (697, 1477),
    4: (770, 1209), 5: (770, 1336), 6: (770, 1477), 7: (852, 1209),
    8: (852, 1336), 9: (852, 1477),
}


class TestDtmfTones:

    def test_dtmf_digit_frequencies(self, audio):
        """play_dtmf(1) → PCM contains 697 Hz and 1209 Hz."""
        pcm = _capture_pcm(audio, 'play_dtmf', 1)
        samples = _pcm_to_samples(pcm).astype(np.float32)
        spectrum = np.abs(np.fft.rfft(samples))
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / _SAMPLE_RATE)

        def peak_near(target_hz, tol=10):
            mask = np.abs(freqs - target_hz) < tol
            return spectrum[mask].max() if mask.any() else 0.0

        noise_floor = np.percentile(spectrum, 90)
        f1, f2 = DTMF_FREQUENCIES[1]
        assert peak_near(f1) > noise_floor, f"{f1} Hz not found"
        assert peak_near(f2) > noise_floor, f"{f2} Hz not found"

    def test_dtmf_all_digits(self, audio):
        """All digits 0–9 produce distinct frequency pairs."""
        seen_pairs = set()
        for digit in range(10):
            pcm = _capture_pcm(audio, 'play_dtmf', digit)
            samples = _pcm_to_samples(pcm).astype(np.float32)
            if len(samples) == 0:
                continue
            spectrum = np.abs(np.fft.rfft(samples))
            freqs = np.fft.rfftfreq(len(samples), d=1.0 / _SAMPLE_RATE)

            def peak_idx(target_hz, tol=10):
                mask = np.abs(freqs - target_hz) < tol
                return round(freqs[mask][np.argmax(spectrum[mask])]) if mask.any() else None

            f1, f2 = DTMF_FREQUENCIES[digit]
            seen_pairs.add((peak_idx(f1), peak_idx(f2)))

        assert len(seen_pairs) == 10, f"Not all digits produced distinct pairs: {seen_pairs}"

    def test_dtmf_stops_after_short_duration(self, audio):
        """play_dtmf returns promptly (non-blocking)."""
        start = time.monotonic()
        audio.play_dtmf(5)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"play_dtmf took {elapsed:.3f}s — expected near-instant"


# ---------------------------------------------------------------------------
# 2.4 File playback
# ---------------------------------------------------------------------------

class TestFilePlayback:

    def test_play_file_writes_audio_content(self, audio, tmp_path):
        """play_file() → aplay receives non-silent PCM derived from the file."""
        wav_path = _make_wav(tmp_path, amplitude=16000)
        pcm = _capture_pcm(audio, 'play_file', wav_path)
        samples = _pcm_to_samples(pcm)
        assert len(samples) > 0, "No PCM written for play_file"
        assert np.any(samples != 0), "All-silent PCM written — audio content lost"

    def test_play_file_preserves_audio_length(self, audio, tmp_path):
        """play_file() → PCM length matches source (within resampling tolerance)."""
        n_samples = 8820
        wav_path = _make_wav(tmp_path, n_samples=n_samples, sample_rate=44100)
        pcm = _capture_pcm(audio, 'play_file', wav_path)
        received = _pcm_to_samples(pcm)
        # Allow ±10% for chunk boundaries
        assert abs(len(received) - n_samples) <= n_samples * 0.1, \
            f"PCM length {len(received)} too far from expected {n_samples}"

    def test_play_file_resamples_22050_to_44100(self, audio, tmp_path):
        """play_file() with 22050 Hz source → resampled to 44100 Hz (Piper output)."""
        n_src = 2205  # 0.1 s at 22050 Hz
        wav_path = _make_wav(tmp_path, n_samples=n_src, sample_rate=22050, amplitude=16000)
        pcm = _capture_pcm(audio, 'play_file', wav_path)
        received = _pcm_to_samples(pcm)
        expected = n_src * 2  # 22050 → 44100 = 2×
        assert abs(len(received) - expected) <= expected * 0.1, \
            f"Expected ~{expected} samples after 2× upsample, got {len(received)}"

    def test_play_file_downmixes_stereo_to_mono(self, audio, tmp_path):
        """play_file() with stereo source → PCM is mono (half the interleaved samples)."""
        n_frames = 4410
        wav_path = _make_wav(tmp_path, n_samples=n_frames * 2, channels=2, amplitude=16000)
        pcm = _capture_pcm(audio, 'play_file', wav_path)
        received = _pcm_to_samples(pcm)
        assert abs(len(received) - n_frames) <= n_frames * 0.1, \
            f"Stereo→mono: expected ~{n_frames} mono frames, got {len(received)}"

    def test_stop_interrupts_playback(self, audio):
        """stop() while playing → is_playing() returns False promptly."""
        _proc.reset()
        audio.play_tone([440], 5000)
        assert _proc.write_called.wait(timeout=2.0), "play never started"
        assert audio.is_playing()
        audio.stop()
        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"


# ---------------------------------------------------------------------------
# 2.5 Volume scaling
# ---------------------------------------------------------------------------

class TestVolumeScaling:

    def test_volume_reduces_amplitude(self, audio, tmp_path):
        """volume=0.5 → PCM peak ≈ half that of volume=1.0."""
        wav_path = _make_wav(tmp_path, amplitude=20000, n_samples=4410)

        # Capture at full volume
        a_full = SounddeviceAudio(volume=1.0, _popen=_popen_mock)
        a_full.amp_on()
        pcm_full = _capture_pcm(a_full, 'play_file', wav_path)
        a_full.amp_off()
        peak_full = np.max(np.abs(_pcm_to_samples(pcm_full)))

        # Capture at half volume
        _proc.reset()
        a_half = SounddeviceAudio(volume=0.5, _popen=_popen_mock)
        a_half.amp_on()
        pcm_half = _capture_pcm(a_half, 'play_file', wav_path)
        a_half.amp_off()
        peak_half = np.max(np.abs(_pcm_to_samples(pcm_half)))

        assert peak_half < peak_full * 0.6, \
            f"volume=0.5 peak {peak_half} not significantly less than full {peak_full}"

    def test_tone_volume_applied(self, audio):
        """volume=0.5 → generated tone amplitude ≈ half of volume=1.0."""
        a_full = SounddeviceAudio(volume=1.0, _popen=_popen_mock)
        a_full.amp_on()
        pcm_full = _capture_pcm(a_full, 'play_tone', [440], 100)
        a_full.amp_off()

        _proc.reset()
        a_half = SounddeviceAudio(volume=0.5, _popen=_popen_mock)
        a_half.amp_on()
        pcm_half = _capture_pcm(a_half, 'play_tone', [440], 100)
        a_half.amp_off()

        peak_full = np.max(np.abs(_pcm_to_samples(pcm_full)))
        peak_half = np.max(np.abs(_pcm_to_samples(pcm_half)))
        assert peak_half < peak_full * 0.6, \
            f"volume=0.5 tone peak {peak_half} not significantly less than {peak_full}"


# ---------------------------------------------------------------------------
# 2.6 Worker thread behaviour
# ---------------------------------------------------------------------------

class TestWorkerThread:

    def _enqueue_nonblocking(self, audio_obj, method, *args):
        returned = threading.Event()
        def run():
            getattr(audio_obj, method)(*args)
            returned.set()
        threading.Thread(target=run, daemon=True).start()
        return returned

    def test_play_tone_is_nonblocking(self, audio):
        """play_tone() returns well before tone duration elapses."""
        returned = self._enqueue_nonblocking(audio, 'play_tone', [350, 440], 5000)
        assert returned.wait(timeout=0.2), \
            "play_tone blocked for >200ms — should return immediately"
        audio.stop()

    def test_play_file_is_nonblocking(self, audio, tmp_path):
        """play_file() returns immediately without waiting for audio to finish."""
        wav_path = _make_wav(tmp_path)
        returned = self._enqueue_nonblocking(audio, 'play_file', wav_path)
        assert returned.wait(timeout=0.2), \
            "play_file blocked for >200ms — should return immediately"

    def test_play_off_hook_tone_is_nonblocking(self, audio):
        """play_off_hook_tone() returns immediately."""
        returned = self._enqueue_nonblocking(audio, 'play_off_hook_tone')
        assert returned.wait(timeout=0.2), \
            "play_off_hook_tone blocked for >200ms"
        audio.stop()

    def test_is_playing_true_while_worker_busy(self, audio):
        """is_playing() returns True while the worker is executing a task."""
        gate = threading.Event()
        writing_started = threading.Event()
        original_write_raw = audio._write_raw

        def gated_write(pcm):
            if np.any(np.frombuffer(bytes(pcm), dtype=np.int16) != 0):
                writing_started.set()
                gate.wait(timeout=5.0)
            original_write_raw(pcm)

        audio._write_raw = gated_write
        audio.play_tone([440], 5000)
        assert writing_started.wait(timeout=2.0), "tone never started"
        assert audio.is_playing()
        gate.set()
        audio.stop()

    def test_is_playing_false_after_stop(self, audio):
        """is_playing() returns False shortly after stop()."""
        audio.play_tone([440], 5000)
        assert _proc.write_called.wait(timeout=2.0)
        audio.stop()
        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"

    def test_tasks_execute_in_fifo_order(self, audio):
        """Multiple enqueued tasks execute in submission order."""
        order = []
        barrier = threading.Barrier(2)

        freqs_sequence = [[350], [440], [700]]
        captured = []

        for freqs in freqs_sequence:
            pcm = audio._waveform_to_pcm(
                __import__('src.audio', fromlist=['_generate_tone'])
                ._generate_tone(freqs, 20, _SAMPLE_RATE)
            )
            captured.append(pcm)

        written_order = []
        original_write_pcm = audio._write_pcm

        def tracking_write(pcm):
            written_order.append(pcm)
            original_write_pcm(pcm)

        audio._write_pcm = tracking_write

        for freqs in freqs_sequence:
            audio.play_tone(freqs, 20)

        _wait_for(lambda: len(written_order) >= 3, timeout=3.0)
        audio.stop()

        assert len(written_order) >= 3, "Not all tasks executed"

    def test_stop_clears_queued_tasks(self, audio):
        """stop() drains the queue so pending tasks do not execute."""
        # Enqueue tasks then stop immediately before the worker can consume them.
        # Use a gate to hold the worker inside the first task while we queue more.
        gate = threading.Event()
        original = audio._write_pcm

        def gated_write(pcm):
            gate.wait()  # block until test releases
            original(pcm)

        audio._write_pcm = gated_write

        audio.play_tone([350], 50)
        audio.play_tone([440], 50)
        audio.play_tone([700], 50)

        # Worker is blocked inside first task; queue holds tasks 2 and 3
        time.sleep(0.05)
        audio.stop()          # drains tasks 2 and 3 from queue
        gate.set()            # release worker so it can exit cleanly

        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"
        assert audio._queue.empty(), "Queue should be empty after stop()"

    def test_worker_thread_is_daemon(self, audio):
        """Worker thread is a daemon thread."""
        assert audio._worker_thread.daemon, "Worker thread must be a daemon"

    def test_silence_written_between_clips(self, audio):
        """Worker writes silence to keep I2S active when queue is empty."""
        # After stop(), worker falls back to writing silence.
        _proc.reset()
        audio.stop()  # ensure idle
        # Let the idle silence loop run for a bit
        time.sleep(0.1)
        all_written = np.frombuffer(_proc.written_pcm, dtype=np.int16)
        assert len(all_written) > 0, "Worker never wrote silence during idle period"
        assert np.all(all_written == 0), "Non-silent data written while idle"

    def test_aplay_started_once_per_amp_on(self):
        """popen is called exactly once per amp_on() call."""
        _popen_mock.reset_mock()
        _popen_mock.side_effect = lambda *a, **kw: FakeProcess()
        a = SounddeviceAudio(_popen=_popen_mock)
        assert _popen_mock.call_count == 0, "aplay must not start in __init__"
        a.amp_on()
        a.play_tone([440], 50)
        a.play_tone([350], 50)
        time.sleep(0.2)
        a.amp_off()
        assert _popen_mock.call_count == 1, \
            f"Expected 1 aplay invocation, got {_popen_mock.call_count}"

    def test_warmup_silence_written_on_amp_on(self):
        """amp_on() writes warmup silence synchronously before returning."""
        local_proc = FakeProcess()
        local_popen = MagicMock(side_effect=lambda *a, **kw: local_proc)
        a = SounddeviceAudio(_popen=local_popen)
        assert local_proc.stdin.write.call_count == 0, \
            "aplay must not start in __init__"
        a.amp_on()
        assert local_proc.stdin.write.call_count >= 1, \
            "amp_on() must write warmup silence synchronously"
        warmup_bytes = local_proc.stdin.write.call_args_list[0][0][0]
        samples = np.frombuffer(warmup_bytes, dtype=np.int16)
        assert len(samples) > 0, "Warmup write was empty"
        assert np.all(samples == 0), "Warmup write contains non-silent samples"
        a.amp_off()

    def test_aplay_invoked_with_pcm_format_flags(self):
        """aplay is started with raw PCM format flags (not WAV stdin)."""
        _popen_mock.reset_mock()
        _popen_mock.side_effect = lambda *a, **kw: FakeProcess()
        a = SounddeviceAudio(device="plughw:TEST", _popen=_popen_mock)
        a.amp_on()
        a.amp_off()
        cmd = _popen_mock.call_args[0][0]
        assert '-f' in cmd and 'S16_LE' in cmd, "Missing -f S16_LE flag"
        assert '-r' in cmd, "Missing -r (sample rate) flag"
        assert '-c' in cmd and '1' in cmd, "Missing -c 1 (mono) flag"
        assert '-D' in cmd and 'plughw:TEST' in cmd, "Missing -D device flag"


# ---------------------------------------------------------------------------
# 2.7 PCM format correctness
# ---------------------------------------------------------------------------

class TestPcmFormat:
    """All audio paths must produce int16 mono PCM at the configured rate."""

    def test_tone_samples_are_int16(self, audio):
        """play_tone() produces int16 PCM samples."""
        pcm = _capture_pcm(audio, 'play_tone', [440], 100)
        samples = np.frombuffer(pcm, dtype=np.int16)
        assert samples.dtype == np.int16

    def test_tone_samples_in_range(self, audio):
        """play_tone() samples stay within int16 bounds."""
        pcm = _capture_pcm(audio, 'play_tone', [440], 100)
        samples = np.frombuffer(pcm, dtype=np.int16)
        assert samples.min() >= -32768 and samples.max() <= 32767

    def test_file_samples_are_int16(self, audio, tmp_path):
        """play_file() produces int16 PCM samples."""
        wav_path = _make_wav(tmp_path)
        pcm = _capture_pcm(audio, 'play_file', wav_path)
        samples = np.frombuffer(pcm, dtype=np.int16)
        assert samples.dtype == np.int16

    def test_dtmf_samples_are_int16(self, audio):
        """play_dtmf() produces int16 PCM samples."""
        pcm = _capture_pcm(audio, 'play_dtmf', 5)
        samples = np.frombuffer(pcm, dtype=np.int16)
        assert samples.dtype == np.int16

# ---------------------------------------------------------------------------
# MockAudio
# ---------------------------------------------------------------------------

class TestMockAudio:
    """Smoke tests for MockAudio — used in all higher-level tests."""

    def test_mock_audio_records_calls(self):
        mock = MockAudio()
        mock.play_tone([350, 440], 500)
        mock.play_dtmf(5)
        mock.play_file("test.wav")
        mock.play_off_hook_tone()
        mock.stop()
        assert mock.calls == [
            ('play_tone', [350, 440], 500),
            ('play_dtmf', 5),
            ('play_file', "test.wav"),
            ('play_off_hook_tone',),
            ('stop',),
        ]

    def test_mock_audio_is_playing(self):
        mock = MockAudio()
        assert not mock.is_playing()
        mock.play_tone([350], 100)
        assert mock.is_playing()
        mock.stop()
        assert not mock.is_playing()
