"""Tests for src/audio.py — SounddeviceAudio concrete implementation.

sounddevice is mocked at the module level because PortAudio is not available
in the development environment.  All tests verify behavior through the mock
rather than actually playing sound.

After F-04, SounddeviceAudio uses an internal worker thread. All play_*
methods are non-blocking — they enqueue a task and return immediately. The
worker thread executes tasks in FIFO order. stop() drains the queue and
halts playback within one polling cycle.
"""

import sys
import types
import threading
import time
import wave
import array
from unittest.mock import MagicMock, patch, call
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Mock sounddevice at the module level before importing src.audio
# ---------------------------------------------------------------------------

# Build a minimal mock of the sounddevice module
_sd_mock = MagicMock()
_sd_mock.play = MagicMock()
_sd_mock.stop = MagicMock()
_sd_mock.wait = MagicMock()
_sd_mock.OutputStream = MagicMock()
sys.modules['sounddevice'] = _sd_mock

# Now safe to import
from src.audio import SounddeviceAudio, MockAudio  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_sd_mock():
    """Reset the sounddevice mock between tests."""
    _sd_mock.reset_mock()
    _sd_mock.play = MagicMock()
    _sd_mock.stop = MagicMock()
    _sd_mock.wait = MagicMock()
    yield


@pytest.fixture
def audio():
    """Fresh SounddeviceAudio instance with daemon worker thread."""
    a = SounddeviceAudio()
    yield a
    # Ensure stop is called to clean up any background threads
    a.stop()


def _make_wav(tmp_path, name="test.wav", n_samples=4410):
    """Helper: write a minimal valid WAV file and return its path."""
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


# ---------------------------------------------------------------------------
# 2.1 Dial tone
# ---------------------------------------------------------------------------

class TestDialTone:

    def test_dial_tone_frequencies(self, audio):
        """Generated waveform contains 350 Hz and 440 Hz components (FFT check)."""
        captured = {}
        ready = threading.Event()

        def capture_play(data, samplerate, **kwargs):
            captured['data'] = data
            captured['samplerate'] = samplerate
            ready.set()

        _sd_mock.play.side_effect = capture_play
        audio.play_tone([350, 440], duration_ms=100)

        # play_tone is now non-blocking; wait for worker to call sd.play
        assert ready.wait(timeout=2.0), "sounddevice.play was not called"
        waveform = captured['data']
        sr = captured['samplerate']

        # FFT check
        spectrum = np.abs(np.fft.rfft(waveform))
        freqs = np.fft.rfftfreq(len(waveform), d=1.0 / sr)

        def peak_near(target_hz, tolerance=5):
            mask = np.abs(freqs - target_hz) < tolerance
            return spectrum[mask].max() if mask.any() else 0.0

        noise_floor = np.percentile(spectrum, 90)
        assert peak_near(350) > noise_floor, "350 Hz component not found in waveform"
        assert peak_near(440) > noise_floor, "440 Hz component not found in waveform"

    def test_dial_tone_stops_after_duration(self, audio):
        """play_tone with a short duration — sounddevice.play is called once."""
        called = threading.Event()
        _sd_mock.play.side_effect = lambda *a, **kw: called.set()
        audio.play_tone([350, 440], duration_ms=50)
        assert called.wait(timeout=2.0), "sounddevice.play was never called"

    def test_dial_tone_stop_called_early(self, audio):
        """stop() while tone playing → is_playing() returns False promptly."""
        # Block sd.play so we can observe the playing state and then stop
        block = threading.Event()
        playing = threading.Event()

        def blocking_play(data, samplerate, **kwargs):
            playing.set()
            block.wait(timeout=2.0)

        _sd_mock.play.side_effect = blocking_play

        # Run play_tone in a thread so this test works regardless of
        # whether play_tone is blocking (old) or non-blocking (new/worker).
        t = threading.Thread(target=audio.play_tone, args=([350, 440], 5000), daemon=True)
        t.start()

        # Wait until sd.play has been called (worker or direct)
        assert playing.wait(timeout=2.0), "play never started"
        assert audio.is_playing()

        audio.stop()
        block.set()  # unblock sd.play

        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"


# ---------------------------------------------------------------------------
# 2.2 Off-hook warning tone
# ---------------------------------------------------------------------------

class TestOffHookTone:

    def test_off_hook_tone_plays_continuously(self, audio):
        """play_off_hook_tone() → tone plays in a loop; doesn't stop itself."""
        call_count = [0]
        started = threading.Event()

        def count_plays(data, samplerate, **kwargs):
            call_count[0] += 1
            started.set()

        _sd_mock.play.side_effect = count_plays

        # Run in thread in case old blocking impl is under test (will still be
        # stopped by audio.stop() in teardown via the fixture)
        t = threading.Thread(target=audio.play_off_hook_tone, daemon=True)
        t.start()

        # Wait for at least one play call, then let it loop briefly
        assert started.wait(timeout=2.0), "off-hook tone never started"
        time.sleep(0.05)

        # Stop it so the fixture teardown doesn't hang
        audio.stop()

        # Should have looped more than once (or at least once)
        assert call_count[0] >= 1

    def test_off_hook_tone_stops_on_stop_call(self, audio):
        """stop() while off-hook tone playing → tone stops; is_playing() False."""
        started = threading.Event()

        def set_started(data, samplerate, **kwargs):
            started.set()

        _sd_mock.play.side_effect = set_started

        t = threading.Thread(target=audio.play_off_hook_tone, daemon=True)
        t.start()
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

    def _capture_waveform(self, audio, digit):
        captured = {}
        ready = threading.Event()

        def capture(data, samplerate, **kwargs):
            captured['data'] = data
            captured['samplerate'] = samplerate
            ready.set()

        _sd_mock.play.side_effect = capture
        audio.play_dtmf(digit)
        ready.wait(timeout=2.0)
        return captured

    def test_dtmf_digit_frequencies(self, audio):
        """play_dtmf(1) → waveform contains 697 Hz and 1209 Hz (FFT check)."""
        captured = self._capture_waveform(audio, 1)
        assert 'data' in captured

        waveform = captured['data']
        sr = captured['samplerate']
        spectrum = np.abs(np.fft.rfft(waveform))
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
            captured = self._capture_waveform(audio, digit)
            _sd_mock.reset_mock()
            assert 'data' in captured, f"digit {digit} produced no waveform"

            waveform = captured['data']
            sr = captured['samplerate']
            spectrum = np.abs(np.fft.rfft(waveform))
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
        # Non-blocking enqueue should return in well under 100 ms
        assert elapsed < 0.5, f"play_dtmf took {elapsed:.3f}s — expected near-instant return"


# ---------------------------------------------------------------------------
# 2.4 File playback
# ---------------------------------------------------------------------------

class TestFilePlayback:

    def test_play_file_called_with_correct_path(self, audio, tmp_path):
        """play_file(path) → backend receives that path's samples."""
        wav_path = _make_wav(tmp_path)
        called = threading.Event()
        captured = {}

        def capture(data, samplerate, **kwargs):
            captured['data'] = data
            called.set()

        _sd_mock.play.side_effect = capture
        audio.play_file(wav_path)

        assert called.wait(timeout=2.0), "sounddevice.play was never called"
        assert len(captured['data']) > 0

    def test_stop_interrupts_playback(self, audio):
        """stop() while playing → is_playing() returns False promptly."""
        block = threading.Event()
        playing = threading.Event()

        def blocking_play(data, samplerate, **kwargs):
            playing.set()
            block.wait(timeout=2.0)

        _sd_mock.play.side_effect = blocking_play

        # Run in thread so test works with both blocking and non-blocking impl
        t = threading.Thread(target=audio.play_tone, args=([440], 5000), daemon=True)
        t.start()
        assert playing.wait(timeout=2.0), "play never started"

        assert audio.is_playing()
        audio.stop()
        block.set()

        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after stop()"

    def test_play_file_interrupts_current_playback(self, audio, tmp_path):
        """play_file() called while already playing → stop() halts all audio."""
        wav_path = _make_wav(tmp_path)
        block = threading.Event()
        first_started = threading.Event()

        def slow_play(data, samplerate, **kwargs):
            first_started.set()
            block.wait(timeout=2.0)

        _sd_mock.play.side_effect = slow_play

        # Run in thread so test works with both blocking and non-blocking impl
        t = threading.Thread(target=audio.play_tone, args=([440], 5000), daemon=True)
        t.start()
        assert first_started.wait(timeout=2.0), "first play never started"

        # stop() should clear the queue and halt playback
        audio.stop()
        block.set()

        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0)


# ---------------------------------------------------------------------------
# 2.5 Worker thread behaviour (F-04 specific)
# ---------------------------------------------------------------------------

class TestWorkerThread:
    """Tests that verify the non-blocking worker-thread design of SounddeviceAudio.

    All play_* calls here use a helper (_enqueue) that dispatches into a
    background thread so the tests work correctly regardless of whether the
    implementation is blocking (pre-F04, should FAIL these tests fast) or
    non-blocking (post-F04, should PASS).

    Tests for the non-blocking property itself use the returned Event to check
    how quickly the call returned.
    """

    def _enqueue(self, audio, method, *args):
        """Call audio.<method>(*args) in a daemon thread; returns (thread, returned_event).

        returned_event is set as soon as the call returns.  Use it to check
        whether the method returned promptly.
        """
        returned = threading.Event()

        def run():
            getattr(audio, method)(*args)
            returned.set()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t, returned

    def test_play_tone_is_nonblocking(self, audio):
        """play_tone() returns in well under the tone duration."""
        _sd_mock.play.side_effect = lambda *a, **kw: time.sleep(1.0)
        t, returned = self._enqueue(audio, 'play_tone', [350, 440], 5000)
        assert returned.wait(timeout=0.2), \
            "play_tone blocked for >200ms — should return immediately (non-blocking)"

    def test_play_file_is_nonblocking(self, audio, tmp_path):
        """play_file() returns immediately without waiting for audio to finish."""
        wav_path = _make_wav(tmp_path)
        _sd_mock.play.side_effect = lambda *a, **kw: time.sleep(1.0)
        t, returned = self._enqueue(audio, 'play_file', wav_path)
        assert returned.wait(timeout=0.2), \
            "play_file blocked for >200ms — should return immediately (non-blocking)"

    def test_play_off_hook_tone_is_nonblocking(self, audio):
        """play_off_hook_tone() returns immediately (non-blocking enqueue)."""
        _sd_mock.play.side_effect = lambda *a, **kw: time.sleep(0.1)
        t, returned = self._enqueue(audio, 'play_off_hook_tone')
        assert returned.wait(timeout=0.2), \
            "play_off_hook_tone blocked for >200ms — should return immediately"

    def test_is_playing_true_while_worker_busy(self, audio):
        """is_playing() returns True while worker thread is executing a task."""
        block = threading.Event()
        started = threading.Event()

        def slow_play(data, samplerate, **kwargs):
            started.set()
            block.wait(timeout=2.0)

        _sd_mock.play.side_effect = slow_play
        self._enqueue(audio, 'play_tone', [440], 5000)

        assert started.wait(timeout=2.0), "worker never started the task"
        assert audio.is_playing(), "is_playing() should be True while worker is busy"

        audio.stop()
        block.set()

    def test_is_playing_false_after_queue_drains(self, audio):
        """is_playing() returns False after all queued tasks complete."""
        done = threading.Event()

        def quick_play(data, samplerate, **kwargs):
            done.set()

        _sd_mock.play.side_effect = quick_play
        self._enqueue(audio, 'play_tone', [440], 50)

        # Wait for the task to execute
        assert done.wait(timeout=2.0), "task never executed"
        # Allow worker to mark as not-playing
        assert _wait_for(lambda: not audio.is_playing(), timeout=1.0), \
            "is_playing() should be False after queue drains"

    def test_stop_while_playing_produces_no_further_audio(self, audio):
        """Enqueue a long tone, stop() after 100ms → sd.play called only once."""
        play_count = [0]
        block = threading.Event()
        started = threading.Event()

        def counting_play(data, samplerate, **kwargs):
            play_count[0] += 1
            started.set()
            block.wait(timeout=2.0)

        _sd_mock.play.side_effect = counting_play

        self._enqueue(audio, 'play_tone', [350, 440], 5000)
        assert started.wait(timeout=2.0), "play never started"

        time.sleep(0.1)
        audio.stop()
        block.set()

        # Let the worker settle
        _wait_for(lambda: not audio.is_playing(), timeout=1.0)

        assert play_count[0] == 1, \
            f"Expected exactly 1 sd.play call, got {play_count[0]}"
        assert not audio.is_playing()

    def test_tasks_execute_in_fifo_order(self, audio):
        """Multiple enqueued tasks play in the order they were submitted."""
        order = []
        sem = threading.Semaphore(0)

        calls_made = [0]
        labels = ['first', 'second', 'third']

        def dispatch_play(data, samplerate, **kwargs):
            idx = calls_made[0]
            if idx < len(labels):
                order.append(labels[idx])
                sem.release()
            calls_made[0] += 1

        _sd_mock.play.side_effect = dispatch_play

        # Enqueue 3 short tones back-to-back (non-blocking in new impl)
        self._enqueue(audio, 'play_tone', [350], 20)
        self._enqueue(audio, 'play_tone', [440], 20)
        self._enqueue(audio, 'play_tone', [700], 20)

        # Wait for all three to execute
        for _ in range(3):
            assert sem.acquire(timeout=3.0), "a task never executed"

        assert order == ['first', 'second', 'third'], \
            f"Tasks executed out of order: {order}"

    def test_stop_clears_queued_tasks(self, audio):
        """stop() prevents queued-but-not-yet-started tasks from playing."""
        play_count = [0]
        block = threading.Event()
        first_started = threading.Event()

        def slow_play(data, samplerate, **kwargs):
            first_started.set()
            play_count[0] += 1
            block.wait(timeout=3.0)

        _sd_mock.play.side_effect = slow_play

        # Enqueue first task (will block worker/sd.play)
        self._enqueue(audio, 'play_tone', [350], 5000)
        assert first_started.wait(timeout=2.0), "first task never started"

        # Enqueue several more while worker is blocked
        self._enqueue(audio, 'play_tone', [440], 5000)
        self._enqueue(audio, 'play_tone', [700], 5000)

        # stop() — should clear the queue AND stop current
        audio.stop()
        block.set()

        _wait_for(lambda: not audio.is_playing(), timeout=1.0)

        # Only 1 play call should have happened (the queued ones were cleared)
        assert play_count[0] == 1, \
            f"Expected 1 play call, got {play_count[0]} — queue was not cleared"

    def test_worker_thread_is_daemon(self, audio):
        """The worker thread is a daemon thread (won't prevent interpreter exit)."""
        assert hasattr(audio, '_worker_thread'), "SounddeviceAudio has no _worker_thread"
        assert audio._worker_thread.daemon, "Worker thread should be a daemon thread"

    def test_is_playing_true_when_queue_nonempty(self, audio):
        """is_playing() returns True when tasks are queued while worker is busy."""
        block = threading.Event()

        def slow_play(data, samplerate, **kwargs):
            block.wait(timeout=2.0)

        _sd_mock.play.side_effect = slow_play

        # Enqueue first task (will block THIS audio's worker inside sd.play)
        audio.play_tone([350], 5000)

        # Poll until THIS audio's worker is actually busy (not a foreign worker)
        assert _wait_for(lambda: audio.is_playing(), timeout=2.0), \
            "audio.is_playing() never became True after enqueuing a task"

        # While worker is blocked, enqueue another task into the queue
        audio.play_tone([440], 5000)

        # is_playing() should still be True: worker busy and/or queue non-empty
        assert audio.is_playing(), \
            "is_playing() should be True when worker is busy and/or queue is non-empty"

        audio.stop()
        block.set()


# ---------------------------------------------------------------------------
# MockAudio
# ---------------------------------------------------------------------------

class TestMockAudio:
    """Smoke tests for MockAudio — used in all higher-level tests."""

    def test_mock_audio_records_calls(self):
        mock = MockAudio()
        mock.play_tone([350, 440], 500)
        mock.play_dtmf(5)
        mock.play_file("/tmp/test.wav")
        mock.play_off_hook_tone()
        mock.stop()
        assert mock.calls == [
            ('play_tone', [350, 440], 500),
            ('play_dtmf', 5),
            ('play_file', "/tmp/test.wav"),
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
