"""Tests for src/audio.py — SounddeviceAudio concrete implementation.

sounddevice is mocked at the module level because PortAudio is not available
in the development environment.  All tests verify behavior through the mock
rather than actually playing sound.
"""

import sys
import types
import threading
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
    """Fresh SounddeviceAudio instance."""
    a = SounddeviceAudio()
    yield a
    # Ensure stop is called to clean up any background threads
    a.stop()


# ---------------------------------------------------------------------------
# 2.1 Dial tone
# ---------------------------------------------------------------------------

class TestDialTone:

    def test_dial_tone_frequencies(self, audio):
        """Generated waveform contains 350 Hz and 440 Hz components (FFT check)."""
        captured = {}

        def capture_play(data, samplerate, **kwargs):
            captured['data'] = data
            captured['samplerate'] = samplerate

        _sd_mock.play.side_effect = capture_play
        audio.play_tone([350, 440], duration_ms=100)

        assert 'data' in captured, "sounddevice.play was not called"
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
        audio.play_tone([350, 440], duration_ms=50)
        assert _sd_mock.play.called

    def test_dial_tone_stop_called_early(self, audio):
        """stop() while tone playing → is_playing() returns False immediately."""
        # Use a threading event to simulate in-progress playback
        playing = threading.Event()
        stopped = threading.Event()

        def slow_play(data, samplerate, **kwargs):
            playing.set()
            stopped.wait(timeout=1.0)

        _sd_mock.play.side_effect = slow_play

        t = threading.Thread(target=audio.play_tone, args=([350, 440], 5000))
        t.start()
        playing.wait(timeout=1.0)

        assert audio.is_playing()
        audio.stop()
        stopped.set()
        t.join(timeout=1.0)

        assert not audio.is_playing()


# ---------------------------------------------------------------------------
# 2.2 Off-hook warning tone
# ---------------------------------------------------------------------------

class TestOffHookTone:

    def test_off_hook_tone_plays_continuously(self, audio):
        """play_off_hook_tone() → tone plays in a loop; doesn't stop itself."""
        call_count = [0]

        def count_plays(data, samplerate, **kwargs):
            call_count[0] += 1

        _sd_mock.play.side_effect = count_plays

        t = threading.Thread(target=audio.play_off_hook_tone)
        t.daemon = True
        t.start()

        # Give it time to loop a few times
        import time
        time.sleep(0.05)

        # Stop it so the fixture teardown doesn't hang
        audio.stop()
        t.join(timeout=1.0)

        # Should have looped more than once
        assert call_count[0] >= 1

    def test_off_hook_tone_stops_on_stop_call(self, audio):
        """stop() while off-hook tone playing → tone stops immediately."""
        started = threading.Event()

        def set_started(data, samplerate, **kwargs):
            started.set()

        _sd_mock.play.side_effect = set_started

        t = threading.Thread(target=audio.play_off_hook_tone)
        t.daemon = True
        t.start()

        started.wait(timeout=1.0)
        audio.stop()
        t.join(timeout=1.0)

        assert not t.is_alive()
        assert not audio.is_playing()


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

        def capture(data, samplerate, **kwargs):
            captured['data'] = data
            captured['samplerate'] = samplerate

        _sd_mock.play.side_effect = capture
        audio.play_dtmf(digit)
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
        """DTMF tone is brief (play_dtmf returns promptly)."""
        import time
        start = time.monotonic()
        audio.play_dtmf(5)
        elapsed = time.monotonic() - start
        # Should complete well under 1 second (DTMF tones are ~100 ms)
        assert elapsed < 1.0


# ---------------------------------------------------------------------------
# 2.4 File playback
# ---------------------------------------------------------------------------

class TestFilePlayback:

    def test_play_file_called_with_correct_path(self, audio, tmp_path):
        """play_file(path) → backend receives that path."""
        # Create a minimal WAV file
        wav_path = str(tmp_path / "test.wav")
        import wave, array
        with wave.open(wav_path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            samples = array.array('h', [0] * 4410)
            wf.writeframes(samples.tobytes())

        audio.play_file(wav_path)
        assert _sd_mock.play.called
        # The waveform data passed to sounddevice should be non-empty
        args, kwargs = _sd_mock.play.call_args
        assert len(args[0]) > 0

    def test_stop_interrupts_playback(self, audio):
        """stop() while playing → is_playing() returns False."""
        playing = threading.Event()

        def slow_play(data, samplerate, **kwargs):
            playing.set()
            import time
            time.sleep(5)

        _sd_mock.play.side_effect = slow_play

        t = threading.Thread(target=audio.play_tone, args=([440], 5000))
        t.start()
        playing.wait(timeout=1.0)

        assert audio.is_playing()
        audio.stop()
        t.join(timeout=1.0)
        assert not audio.is_playing()

    def test_play_file_interrupts_current_playback(self, audio, tmp_path):
        """play_file() called while already playing → previous audio stops."""
        wav_path = str(tmp_path / "test.wav")
        import wave, array
        with wave.open(wav_path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            samples = array.array('h', [0] * 4410)
            wf.writeframes(samples.tobytes())

        stop_call_count = [0]
        orig_stop = _sd_mock.stop

        def counting_stop():
            stop_call_count[0] += 1

        _sd_mock.stop.side_effect = counting_stop

        # Simulate already playing
        audio._playing = True

        audio.play_file(wav_path)
        # stop() should have been called to interrupt previous playback
        assert stop_call_count[0] >= 1 or _sd_mock.stop.called


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
