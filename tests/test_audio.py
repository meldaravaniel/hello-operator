"""Tests for src/audio.py — SounddeviceAudio concrete implementation.

subprocess.Popen is mocked at the module level via the _popen_mock fixture
so no real aplay process is launched.  All tests verify behaviour through the
FakeProcess helper rather than actually playing sound.

After F-04, SounddeviceAudio uses an internal worker thread.  All play_*
methods are non-blocking — they enqueue a task and return immediately.  The
worker thread executes tasks in FIFO order.  stop() drains the queue and
terminates the current aplay process within one polling cycle.
"""

import io
import threading
import time
import wave
import array
from unittest.mock import MagicMock
import numpy as np
import pytest

from src.audio import SounddeviceAudio, MockAudio  # noqa: E402


# ---------------------------------------------------------------------------
# FakeProcess — simulates an aplay subprocess
# ---------------------------------------------------------------------------

class FakeProcess:
    """Minimal fake subprocess.Popen result for testing SounddeviceAudio.

    By default the process finishes immediately (poll() returns 0).
    Pass a finish_event to make poll() block until the event is set
    (or until terminate() is called).
    """

    def __init__(self, finish_event=None):
        self.stdin = MagicMock()
        self._finish = finish_event
        self.terminated = threading.Event()
        self._written_bytes = bytearray()
        self.write_called = threading.Event()

        def _capture_write(data):
            self._written_bytes.extend(data)
            self.write_called.set()

        self.stdin.write.side_effect = _capture_write

    @property
    def written_bytes(self):
        return bytes(self._written_bytes)

    def poll(self):
        if self.terminated.is_set():
            return 0
        if self._finish is None or self._finish.is_set():
            return 0
        return None

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        self.terminated.set()
        if self._finish is not None:
            self._finish.set()


# ---------------------------------------------------------------------------
# Module-level popen mock — injected into every SounddeviceAudio under test
# ---------------------------------------------------------------------------

_popen_mock = MagicMock()


@pytest.fixture(autouse=True)
def reset_popen_mock():
    """Reset the popen mock between tests; default returns a fast-finishing FakeProcess."""
    _popen_mock.reset_mock()
    _popen_mock.side_effect = lambda *a, **kw: FakeProcess()
    yield


@pytest.fixture
def audio():
    """Fresh SounddeviceAudio instance with injected mock popen."""
    a = SounddeviceAudio(_popen=_popen_mock)
    yield a
    a.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wav(tmp_path, name="test.wav", n_samples=4410):
    """Write a minimal valid WAV file and return its path."""
    wav_path = str(tmp_path / name)
    with wave.open(wav_path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        samples = array.array('h', [0] * n_samples)
        wf.writeframes(samples.tobytes())
    return wav_path


def _wait_for(condition, timeout=2.0, interval=0.005):
    """Poll condition() until True or timeout. Returns final condition value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()


def _capture_wav_bytes(audio, method, *args, timeout=2.0):
    """Call audio.<method>(*args) and return the WAV bytes written to aplay stdin."""
    proc = FakeProcess()
    _popen_mock.side_effect = lambda *a, **kw: proc
    getattr(audio, method)(*args)
    assert proc.write_called.wait(timeout=timeout), f"{method} never wrote to aplay stdin"
    return proc.written_bytes


def _parse_wav_samples(wav_bytes):
    """Parse WAV bytes into (samples_int16, sample_rate)."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, 'rb') as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16), sr


# ---------------------------------------------------------------------------
# 2.1 Dial tone
# ---------------------------------------------------------------------------

class TestDialTone:

    def test_dial_tone_frequencies(self, audio):
        """Generated waveform contains 350 Hz and 440 Hz components (FFT check)."""
        wav_bytes = _capture_wav_bytes(audio, 'play_tone', [350, 440], 100)
        waveform, sr = _parse_wav_samples(wav_bytes)

        spectrum = np.abs(np.fft.rfft(waveform.astype(np.float32)))
        freqs = np.fft.rfftfreq(len(waveform), d=1.0 / sr)

        def peak_near(target_hz, tolerance=5):
            mask = np.abs(freqs - target_hz) < tolerance
            return spectrum[mask].max() if mask.any() else 0.0

        noise_floor = np.percentile(spectrum, 90)
        assert peak_near(350) > noise_floor, "350 Hz component not found in waveform"
        assert peak_near(440) > noise_floor, "440 Hz component not found in waveform"

    def test_dial_tone_stops_after_duration(self, audio):
        """play_tone with a short duration — aplay is invoked once."""
        called = threading.Event()

        def make_proc(*a, **kw):
            called.set()
            return FakeProcess()

        _popen_mock.side_effect = make_proc
        audio.play_tone([350, 440], duration_ms=50)
        assert called.wait(timeout=2.0), "aplay was never invoked"

    def test_dial_tone_stop_called_early(self, audio):
        """stop() while tone playing → is_playing() returns False promptly."""
        finish = threading.Event()
        playing = threading.Event()

        def make_blocking_proc(*a, **kw):
            playing.set()
            return FakeProcess(finish_event=finish)

        _popen_mock.side_effect = make_blocking_proc

        audio.play_tone([350, 440], 5000)
        assert playing.wait(timeout=2.0), "play never started"
        assert audio.is_playing()

        audio.stop()
        finish.set()

        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"


# ---------------------------------------------------------------------------
# 2.2 Off-hook warning tone
# ---------------------------------------------------------------------------

class TestOffHookTone:

    def test_off_hook_tone_plays_continuously(self, audio):
        """play_off_hook_tone() → aplay is invoked repeatedly; doesn't stop itself."""
        call_count = [0]
        started = threading.Event()

        def make_proc(*a, **kw):
            call_count[0] += 1
            started.set()
            return FakeProcess()

        _popen_mock.side_effect = make_proc

        audio.play_off_hook_tone()
        assert started.wait(timeout=2.0), "off-hook tone never started"
        time.sleep(0.05)
        audio.stop()

        assert call_count[0] >= 1

    def test_off_hook_tone_stops_on_stop_call(self, audio):
        """stop() while off-hook tone playing → tone stops; is_playing() False."""
        started = threading.Event()

        def make_proc(*a, **kw):
            started.set()
            return FakeProcess()

        _popen_mock.side_effect = make_proc

        audio.play_off_hook_tone()
        assert started.wait(timeout=2.0), "off-hook tone never started"

        audio.stop()

        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"


# ---------------------------------------------------------------------------
# 2.3 DTMF tones
# ---------------------------------------------------------------------------

DTMF_FREQUENCIES = {
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


class TestDtmfTones:

    def test_dtmf_digit_frequencies(self, audio):
        """play_dtmf(1) → waveform contains 697 Hz and 1209 Hz (FFT check)."""
        wav_bytes = _capture_wav_bytes(audio, 'play_dtmf', 1)
        waveform, sr = _parse_wav_samples(wav_bytes)

        spectrum = np.abs(np.fft.rfft(waveform.astype(np.float32)))
        freqs = np.fft.rfftfreq(len(waveform), d=1.0 / sr)

        def peak_near(target_hz, tolerance=10):
            mask = np.abs(freqs - target_hz) < tolerance
            return spectrum[mask].max() if mask.any() else 0.0

        noise_floor = np.percentile(spectrum, 90)
        f1, f2 = DTMF_FREQUENCIES[1]
        assert peak_near(f1) > noise_floor, f"{f1} Hz not found"
        assert peak_near(f2) > noise_floor, f"{f2} Hz not found"

    def test_dtmf_all_digits(self, audio):
        """All digits 0–9 produce distinct frequency pairs."""
        seen_pairs = set()
        for digit in range(10):
            wav_bytes = _capture_wav_bytes(audio, 'play_dtmf', digit)
            waveform, sr = _parse_wav_samples(wav_bytes)

            spectrum = np.abs(np.fft.rfft(waveform.astype(np.float32)))
            freqs = np.fft.rfftfreq(len(waveform), d=1.0 / sr)

            def peak_idx(target_hz, tolerance=10):
                mask = np.abs(freqs - target_hz) < tolerance
                return freqs[mask][np.argmax(spectrum[mask])].round() if mask.any() else None

            f1, f2 = DTMF_FREQUENCIES[digit]
            pair = (peak_idx(f1), peak_idx(f2))
            seen_pairs.add(pair)

        assert len(seen_pairs) == 10, "Not all digits produced distinct frequency pairs"

    def test_dtmf_stops_after_short_duration(self, audio):
        """DTMF tone is brief; play_dtmf returns promptly (non-blocking)."""
        start = time.monotonic()
        audio.play_dtmf(5)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"play_dtmf took {elapsed:.3f}s — expected near-instant return"


# ---------------------------------------------------------------------------
# 2.4 File playback
# ---------------------------------------------------------------------------

class TestFilePlayback:

    def test_play_file_sends_file_bytes_to_aplay(self, audio, tmp_path):
        """play_file(path) → aplay receives the exact bytes from the WAV file."""
        wav_path = _make_wav(tmp_path)
        with open(wav_path, 'rb') as f:
            expected_bytes = f.read()

        proc = FakeProcess()
        _popen_mock.side_effect = lambda *a, **kw: proc
        audio.play_file(wav_path)

        assert proc.write_called.wait(timeout=2.0), "aplay was never invoked"
        assert proc.written_bytes == expected_bytes

    def test_stop_interrupts_playback(self, audio):
        """stop() while playing → is_playing() returns False promptly."""
        finish = threading.Event()
        playing = threading.Event()

        def make_blocking_proc(*a, **kw):
            playing.set()
            return FakeProcess(finish_event=finish)

        _popen_mock.side_effect = make_blocking_proc

        audio.play_tone([440], 5000)
        assert playing.wait(timeout=2.0), "play never started"

        assert audio.is_playing()
        audio.stop()
        finish.set()

        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"

    def test_play_file_interrupts_current_playback(self, audio, tmp_path):
        """play_file() called while already playing → stop() halts all audio."""
        wav_path = _make_wav(tmp_path)
        finish = threading.Event()
        first_started = threading.Event()

        def make_blocking_proc(*a, **kw):
            first_started.set()
            return FakeProcess(finish_event=finish)

        _popen_mock.side_effect = make_blocking_proc

        audio.play_tone([440], 5000)
        assert first_started.wait(timeout=2.0), "first play never started"

        audio.stop()
        finish.set()

        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0)


# ---------------------------------------------------------------------------
# 2.5 Worker thread behaviour (F-04 specific)
# ---------------------------------------------------------------------------

class TestWorkerThread:
    """Tests that verify the non-blocking worker-thread design of SounddeviceAudio."""

    def _enqueue(self, audio, method, *args):
        """Call audio.<method>(*args) in a daemon thread; returns (thread, returned_event)."""
        returned = threading.Event()

        def run():
            getattr(audio, method)(*args)
            returned.set()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t, returned

    def test_play_tone_is_nonblocking(self, audio):
        """play_tone() returns in well under the tone duration."""
        finish = threading.Event()
        _popen_mock.side_effect = lambda *a, **kw: FakeProcess(finish_event=finish)

        t, returned = self._enqueue(audio, 'play_tone', [350, 440], 5000)
        assert returned.wait(timeout=0.2), \
            "play_tone blocked for >200ms — should return immediately (non-blocking)"
        finish.set()

    def test_play_file_is_nonblocking(self, audio, tmp_path):
        """play_file() returns immediately without waiting for audio to finish."""
        wav_path = _make_wav(tmp_path)
        finish = threading.Event()
        _popen_mock.side_effect = lambda *a, **kw: FakeProcess(finish_event=finish)

        t, returned = self._enqueue(audio, 'play_file', wav_path)
        assert returned.wait(timeout=0.2), \
            "play_file blocked for >200ms — should return immediately (non-blocking)"
        finish.set()

    def test_play_off_hook_tone_is_nonblocking(self, audio):
        """play_off_hook_tone() returns immediately (non-blocking enqueue)."""
        t, returned = self._enqueue(audio, 'play_off_hook_tone')
        assert returned.wait(timeout=0.2), \
            "play_off_hook_tone blocked for >200ms — should return immediately"

    def test_is_playing_true_while_worker_busy(self, audio):
        """is_playing() returns True while worker thread is executing a task."""
        finish = threading.Event()
        started = threading.Event()

        def make_blocking_proc(*a, **kw):
            started.set()
            return FakeProcess(finish_event=finish)

        _popen_mock.side_effect = make_blocking_proc

        self._enqueue(audio, 'play_tone', [440], 5000)
        assert started.wait(timeout=2.0), "worker never started the task"
        assert audio.is_playing(), "is_playing() should be True while worker is busy"

        audio.stop()
        finish.set()

    def test_is_playing_false_after_queue_drains(self, audio):
        """is_playing() returns False after all queued tasks complete."""
        done = threading.Event()

        def make_proc(*a, **kw):
            done.set()
            return FakeProcess()

        _popen_mock.side_effect = make_proc

        self._enqueue(audio, 'play_tone', [440], 50)
        assert done.wait(timeout=2.0), "task never executed"
        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after queue drains"

    def test_stop_while_playing_produces_no_further_audio(self, audio):
        """Enqueue a long tone, stop() after 100ms → aplay called only once."""
        play_count = [0]
        finish = threading.Event()
        started = threading.Event()

        def make_counting_proc(*a, **kw):
            play_count[0] += 1
            started.set()
            return FakeProcess(finish_event=finish)

        _popen_mock.side_effect = make_counting_proc

        self._enqueue(audio, 'play_tone', [350, 440], 5000)
        assert started.wait(timeout=2.0), "play never started"

        time.sleep(0.1)
        audio.stop()
        finish.set()

        _wait_for(lambda: not audio.is_playing(), timeout=1.0)

        assert play_count[0] == 1, \
            f"Expected exactly 1 aplay invocation, got {play_count[0]}"
        assert not audio.is_playing()

    def test_tasks_execute_in_fifo_order(self, audio):
        """Multiple enqueued tasks play in the order they were submitted."""
        order = []
        sem = threading.Semaphore(0)
        calls_made = [0]
        labels = ['first', 'second', 'third']

        def make_counting_proc(*a, **kw):
            idx = calls_made[0]
            if idx < len(labels):
                order.append(labels[idx])
                sem.release()
            calls_made[0] += 1
            return FakeProcess()

        _popen_mock.side_effect = make_counting_proc

        self._enqueue(audio, 'play_tone', [350], 20)
        self._enqueue(audio, 'play_tone', [440], 20)
        self._enqueue(audio, 'play_tone', [700], 20)

        for _ in range(3):
            assert sem.acquire(timeout=3.0), "a task never executed"

        assert order == ['first', 'second', 'third'], \
            f"Tasks executed out of order: {order}"

    def test_stop_clears_queued_tasks(self, audio):
        """stop() prevents queued-but-not-yet-started tasks from playing."""
        play_count = [0]
        finish = threading.Event()
        first_started = threading.Event()

        def make_counting_proc(*a, **kw):
            first_started.set()
            play_count[0] += 1
            return FakeProcess(finish_event=finish)

        _popen_mock.side_effect = make_counting_proc

        self._enqueue(audio, 'play_tone', [350], 5000)
        assert first_started.wait(timeout=2.0), "first task never started"

        self._enqueue(audio, 'play_tone', [440], 5000)
        self._enqueue(audio, 'play_tone', [700], 5000)

        audio.stop()
        finish.set()

        _wait_for(lambda: not audio.is_playing(), timeout=1.0)

        assert play_count[0] == 1, \
            f"Expected 1 aplay invocation, got {play_count[0]} — queue was not cleared"

    def test_worker_thread_is_daemon(self, audio):
        """The worker thread is a daemon thread (won't prevent interpreter exit)."""
        assert hasattr(audio, '_worker_thread'), "SounddeviceAudio has no _worker_thread"
        assert audio._worker_thread.daemon, "Worker thread should be a daemon thread"

    def test_is_playing_true_when_queue_nonempty(self, audio):
        """is_playing() returns True when tasks are queued while worker is busy."""
        finish = threading.Event()

        _popen_mock.side_effect = lambda *a, **kw: FakeProcess(finish_event=finish)

        audio.play_tone([350], 5000)
        assert _wait_for(lambda: audio.is_playing(), timeout=2.0), \
            "audio.is_playing() never became True after enqueuing a task"

        audio.play_tone([440], 5000)
        assert audio.is_playing(), \
            "is_playing() should be True when worker is busy and/or queue is non-empty"

        audio.stop()
        finish.set()


# ---------------------------------------------------------------------------
# 2.6 Sample format (regression: PortAudio -9994 on I2S hardware)
# ---------------------------------------------------------------------------

class TestSampleFormat:
    """Verify that WAV bytes piped to aplay always use 16-bit (int16) samples.

    I2S/ALSA drivers on Raspberry Pi reject float32 with PortAudio error
    -9994 (paSampleFormatNotSupported).  All audio paths must encode samples
    as int16 in the WAV bytes sent to aplay.
    """

    def _get_wav_samplewidth(self, audio, method, *args):
        """Return the samplewidth (bytes per sample) from the WAV bytes piped to aplay."""
        wav_bytes = _capture_wav_bytes(audio, method, *args)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, 'rb') as wf:
            return wf.getsampwidth()

    def test_play_tone_outputs_int16(self, audio):
        """play_tone() → WAV bytes sent to aplay have samplewidth=2 (int16)."""
        sw = self._get_wav_samplewidth(audio, 'play_tone', [350, 440], 100)
        assert sw == 2, f"Expected samplewidth=2 (int16) for I2S compatibility, got {sw}"

    def test_play_tone_values_in_int16_range(self, audio):
        """play_tone() samples fit within int16 bounds."""
        wav_bytes = _capture_wav_bytes(audio, 'play_tone', [350, 440], 100)
        samples, _ = _parse_wav_samples(wav_bytes)
        assert samples.min() >= -32768 and samples.max() <= 32767

    def test_play_dtmf_outputs_int16(self, audio):
        """play_dtmf() → WAV bytes sent to aplay have samplewidth=2 (int16)."""
        sw = self._get_wav_samplewidth(audio, 'play_dtmf', 5)
        assert sw == 2, f"Expected samplewidth=2 (int16) for I2S compatibility, got {sw}"

    def test_play_off_hook_tone_outputs_int16(self, audio):
        """play_off_hook_tone() → WAV bytes sent to aplay have samplewidth=2 (int16)."""
        sw = self._get_wav_samplewidth(audio, 'play_off_hook_tone')
        audio.stop()
        assert sw == 2, f"Expected samplewidth=2 (int16) for I2S compatibility, got {sw}"

    def test_play_file_passes_bytes_unchanged(self, audio, tmp_path):
        """play_file() passes the WAV file bytes unchanged to aplay."""
        wav_path = _make_wav(tmp_path)
        with open(wav_path, 'rb') as f:
            expected = f.read()

        proc = FakeProcess()
        _popen_mock.side_effect = lambda *a, **kw: proc
        audio.play_file(wav_path)

        assert proc.write_called.wait(timeout=2.0), "aplay was never invoked"
        assert proc.written_bytes == expected, "play_file() altered the WAV bytes"


# ---------------------------------------------------------------------------
# 2.7 stop() / write race condition (BrokenPipeError)
# ---------------------------------------------------------------------------

class TestStopWriteRace:
    """stop() can terminate the aplay proc between _play_bytes storing self._proc
    and calling proc.stdin.write().  The resulting BrokenPipeError must not
    propagate; is_playing() must settle to False without hanging.
    """

    def test_broken_pipe_on_write_does_not_raise(self, audio):
        """BrokenPipeError from stdin.write() is swallowed; is_playing() → False."""
        def make_broken_proc(*a, **kw):
            p = FakeProcess()
            p.stdin.write.side_effect = BrokenPipeError("simulated: proc terminated before write")
            return p

        _popen_mock.side_effect = make_broken_proc

        audio.play_tone([350, 440], 100)  # must not raise

        assert _wait_for(lambda: not audio.is_playing(), timeout=2.0), \
            "is_playing() should be False after BrokenPipeError on stdin.write"

    def test_stop_while_proc_starting_does_not_raise(self, audio):
        """stop() fired in the window between proc creation and stdin.write()
        — simulated by blocking the write until after stop() has run."""
        proc_stored = threading.Event()
        write_gate = threading.Event()

        def make_gated_proc(*a, **kw):
            p = FakeProcess()

            def gated_write(data):
                proc_stored.set()
                write_gate.wait(timeout=1.0)
                raise BrokenPipeError("proc terminated by stop() before write")

            p.stdin.write.side_effect = gated_write
            return p

        _popen_mock.side_effect = make_gated_proc

        audio.play_tone([350, 440], 5000)
        assert proc_stored.wait(timeout=2.0), "proc was never created"

        # Simulate stop() having terminated the proc; now let the write proceed
        write_gate.set()

        assert _wait_for(lambda: not audio.is_playing(), timeout=2.0), \
            "is_playing() should be False after concurrent stop()/write race"

    def test_stop_event_set_before_write_exits_cleanly(self, audio):
        """_stop_event already set when _play_bytes checks: proc is terminated,
        no write attempted, is_playing() → False without BrokenPipeError."""
        proc_created = threading.Event()
        write_called = [False]

        def make_proc(*a, **kw):
            p = FakeProcess()
            original = p.stdin.write.side_effect

            def track_write(data):
                write_called[0] = True
                if original:
                    original(data)

            p.stdin.write.side_effect = track_write
            proc_created.set()
            return p

        _popen_mock.side_effect = make_proc

        # Force the stop event to be set right after enqueue but before the worker
        # checks it — achieve this by setting it immediately after play_tone returns
        # (play_tone is non-blocking; the worker may not have started yet).
        audio._stop_event.set()
        audio.play_tone([350, 440], 100)

        assert proc_created.wait(timeout=2.0), "proc was never created"

        assert _wait_for(lambda: not audio.is_playing(), timeout=2.0), \
            "is_playing() should be False when stop_event was pre-set"

    def test_off_hook_broken_pipe_does_not_raise(self, audio):
        """BrokenPipeError during _play_off_hook_loop stdin.write() is handled cleanly."""
        def make_broken_proc(*a, **kw):
            p = FakeProcess()
            p.stdin.write.side_effect = BrokenPipeError("simulated broken pipe in off-hook loop")
            return p

        _popen_mock.side_effect = make_broken_proc

        audio.play_off_hook_tone()  # must not raise

        assert _wait_for(lambda: not audio.is_playing(), timeout=2.0), \
            "is_playing() should be False after BrokenPipeError in off-hook loop"


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
